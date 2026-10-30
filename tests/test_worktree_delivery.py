"""真实临时 Git 仓库验证隔离和交付；不接触用户项目，也不以文字匹配代替 Git 行为。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lib.task_graph_cli import _execute
from lib.worktree_cli import DeliveryError, create, git, head, merge, merge_check, scope, target_branch
from lib.worktree_policy import WorktreePolicyError, settings
from tests import test_qa_handoff as qa_fixtures
from tests.test_scheduler_boundaries import _writer_payload
from tests.test_unified_host_workflow import HOSTS, UnifiedHostFixture


PACK = Path(__file__).resolve().parents[1]


class SettingsTest(unittest.TestCase):
    def test_defaults_and_explicit_auto(self) -> None:
        self.assertEqual({"mode": "auto", "merge": "confirm", "target_branch": "auto"}, settings([]))
        self.assertEqual("auto", settings(["parallel_worktrees:", "  merge: auto"])["merge"])

    def test_bad_settings_do_not_silently_fall_back(self) -> None:
        for content in ("  merge: yes", "  merge: AUTO", "  unknown: auto", "    merge: auto",
                        "  mode: force", "  merge: auto\n  merge: confirm", "  merge: 'auto", '  merge: auto"'):
            with self.subTest(content=content), self.assertRaises(WorktreePolicyError):
                settings(("parallel_worktrees:\n" + content).splitlines())


class GitDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="workflow-delivery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "main"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Workflow Fixture")
        git(self.repo, "config", "user.email", "workflow-fixture@example.invalid")
        # 各夹具使用本地身份和确切文件；测试提交代表 PM 授权的临时检查点。
        self.config = self.repo / "agent_workflow/project.yaml"
        self.config.parent.mkdir()
        self.config.write_text((PACK / "project.yaml").read_text())
        (self.repo / "src").mkdir()
        (self.repo / "src/a.py").write_text("a = 0\n")
        (self.repo / "src/b.py").write_text("b = 0\n")
        (self.repo / "docs/standards").mkdir(parents=True)
        (self.repo / "docs/STANDARDS.md").write_text("# Standards\n[General](standards/GENERAL.md)\n")
        (self.repo / "docs/standards/GENERAL.md").write_text(
            "# General\n- Domain: engineering\n[eng-source-boundary] [hard] Preserve ownership.\n")
        (self.repo / "docs/features").mkdir()
        (self.repo / "docs/features/baseline.md").write_text("# Baseline\n- Feature ID: baseline\n- Status: active\n")
        (self.repo / "docs/PROJECT.md").write_text("# Project\n[Baseline](features/baseline.md)\n")
        git(self.repo, "add", "agent_workflow/project.yaml", "src/a.py", "src/b.py",
            "docs/STANDARDS.md", "docs/standards/GENERAL.md", "docs/PROJECT.md", "docs/features/baseline.md")
        git(self.repo, "commit", "-m", "fixture baseline")
        self.base = head(self.repo)
        template = _writer_payload()
        standards = template["standards_contract"]
        standards.update(index_fingerprint=hashlib.sha256((self.repo / "docs/STANDARDS.md").read_bytes()).hexdigest(),
                         required_engineering_rule_ids=["eng-source-boundary"], protected_paths=[])
        standards["leaves"][0].update(rule_ids=["eng-source-boundary"], content_fingerprint=hashlib.sha256(
            (self.repo / "docs/standards/GENERAL.md").read_bytes()).hexdigest())
        self.workers: list[Path] = []
        self.tasks: list[dict] = []
        for name in ("a", "b"):
            worker = self.root / f"worker-{name}"
            create(self.repo, worker, self.base)
            (worker / f"src/{name}.py").write_text(f"{name} = 1\n")
            git(worker, "add", f"src/{name}.py")
            git(worker, "commit", "-m", f"PM local checkpoint {name}")
            self.workers.append(worker)
            task = _writer_payload(f"src/{name}.py")["tasks"][0]
            task.update({"id": name, "request_id": "req", "task_type": "writer",
                               "depends_on": [], "blocks": [], "gates": ["requirements_approved"],
                               "owned_paths": [f"src/{name}.py"], "semantic_locks": [],
                               "state": "BUILD_VERIFIED", "execution_workspace": {
                                   "root": str(worker), "base_revision": self.base,
                                   "head_revision": head(worker)}})
            for document in task["controlled_document_access"]["documents"]:
                if document["path"] == "docs/STANDARDS.md":
                    document["content_fingerprint"] = standards["index_fingerprint"]
                else:
                    document["rule_ids"] = ["eng-source-boundary"]
                    document["content_fingerprint"] = standards["leaves"][0]["content_fingerprint"]
            self.tasks.append(task)
        self.integration = self.root / "integration"
        create(self.repo, self.integration, self.base)
        for worker in self.workers:
            git(self.integration, "merge", "--no-ff", "--no-edit", head(worker))
        self.tip = head(self.integration)
        self.record = {"root": str(self.integration), "target_branch": "main", "target_base": self.base,
                       "head_revision": self.tip, "verification": [{
                           "command": "python -c 'assert a == b == 1'", "exit_code": 0,
                           "log_ref": "fixture:integration-check", "head_revision": self.tip}]}
        # 真正执行组合行为检查，而不是仅在 JSON 中填入成功退出码。
        checked = subprocess.run([sys.executable, "-c", "from src.a import a; from src.b import b; assert a == b == 1"],
                                 cwd=self.integration, capture_output=True, check=False)
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.graph = {"request_id": "req", "tasks": self.tasks, "approved_gates": ["requirements_approved"],
                      "worktree_integrations": {"req": self.record}, "standards_contract": standards}
        fixture = qa_fixtures.QAHandoffValidationTest()
        fixture.setUp()
        qa = copy.deepcopy(fixture.payload)
        actual = scope(self.repo, self.base, self.tip)
        qa["review_method"]["scope_ref"]["repositories"] = [actual]
        coverage = qa["standards_policy_coverage"]
        coverage["index_fingerprint"] = hashlib.sha256((self.repo / "docs/STANDARDS.md").read_bytes()).hexdigest()
        coverage["path_checks"] = [{"path": path, "applicable_rule_ids": ["eng-source-boundary"],
                                    "reason": "fixture source"} for path in actual["changed_paths"]]
        coverage["rule_checks"][0]["affected_paths"] = actual["changed_paths"]
        coverage["rule_checks"][0]["source_fingerprint"] = hashlib.sha256(
            (self.repo / "docs/standards/GENERAL.md").read_bytes()).hexdigest()
        self.payload = {"task_graph": self.graph, "qa_handoff": qa, "authorization": {
            "mode": "confirm", "source": "user:approve-current-merge", "request_id": "req",
            "target_branch": "main", "target_base": self.base, "head_revision": self.tip,
            "diff_fingerprint": actual["diff_fingerprint"]}}

    def test_parallel_writes_are_isolated_and_confirmed_merge_delivers_both(self) -> None:
        self.assertEqual("b = 0\n", (self.workers[0] / "src/b.py").read_text())
        self.assertEqual("a = 0\n", (self.repo / "src/a.py").read_text())
        before = head(self.repo)
        self.assertEqual("merge_ready", merge_check(self.repo, self.config, self.payload)["status"])
        self.assertEqual(before, head(self.repo))
        result = merge(self.repo, self.config, self.payload)
        self.assertEqual("merged", result["status"])
        self.assertFalse(result["pushed"])
        self.assertEqual(self.tip, head(self.repo))
        self.assertEqual("a = 1\n", (self.repo / "src/a.py").read_text())
        self.assertEqual("b = 1\n", (self.repo / "src/b.py").read_text())
        self.assertTrue(all(path.is_dir() for path in self.workers))

    def refresh_candidate(self, base: str | None = None) -> None:
        """夹具中真实提交变化后同步完整候选绑定；不制造与实际差异不一致的成功证据。"""
        self.tip = head(self.integration)
        self.record.update(target_base=base or self.record["target_base"], head_revision=self.tip)
        self.record["verification"][0]["head_revision"] = self.tip
        actual = scope(self.repo, self.record["target_base"], self.tip)
        self.payload["qa_handoff"]["review_method"]["scope_ref"]["repositories"] = [actual]
        coverage = self.payload["qa_handoff"]["standards_policy_coverage"]
        coverage["path_checks"] = [{"path": path, "applicable_rule_ids": ["eng-source-boundary"],
                                    "reason": "fixture source"} for path in actual["changed_paths"]]
        coverage["rule_checks"][0]["affected_paths"] = actual["changed_paths"]
        self.payload["authorization"].update(target_base=self.record["target_base"], head_revision=self.tip,
                                              diff_fingerprint=actual["diff_fingerprint"])

    def test_running_or_failed_qa_cannot_be_overridden_by_a_cached_pass(self) -> None:
        reviewer = {"id": "qa", "request_id": "req", "task_type": "qa", "depends_on": [],
                    "blocks": [], "gates": [], "owned_paths": [], "semantic_locks": [], "state": "QA_PASSED"}
        self.tasks.append(reviewer)
        for mode in ("confirm", "auto"):
            self.payload["authorization"].update(mode=mode, source=("user:approved" if mode == "confirm"
                                                                  else "project:parallel_worktrees.merge"))
            for state in ("DECLARED", "BLOCKED", "READY", "RUNNING", "QA", "FAILED", "QA_SCOPE_READY"):
                reviewer["state"] = state
                with self.subTest(mode=mode, state=state), self.assertRaisesRegex(DeliveryError, "not complete: qa"):
                    merge(self.repo, self.config, self.payload)
                self.assertEqual(self.base, head(self.repo))
        reviewer["state"] = "QA_PASSED"
        self.payload["authorization"].update(mode="confirm", source="user:approved")
        self.assertEqual("merge_ready", merge_check(self.repo, self.config, self.payload)["status"])

    def prepare_delivered_dependency(self) -> None:
        """A 已交付并正常清理后，B 从含 A 的真实基线继续；不重建历史目录。"""
        old_tip = head(self.workers[0])
        self.tasks[0].update(request_id="previous", blocks=["b"])
        self.graph["worktree_integrations"]["previous"] = copy.deepcopy(self.record)
        self.tasks[1]["depends_on"] = ["a"]
        git(self.repo, "merge", "--ff-only", old_tip)
        git(self.workers[1], "merge", "--no-edit", old_tip)
        self.tasks[1]["execution_workspace"].update(base_revision=old_tip, head_revision=head(self.workers[1]))
        git(self.integration, "merge", "--no-edit", head(self.workers[1]))
        git(self.repo, "worktree", "remove", str(self.workers[0]))
        self.refresh_candidate(old_tip)

    def test_completed_previous_request_does_not_require_its_removed_worktree(self) -> None:
        self.prepare_delivered_dependency()
        self.assertFalse(self.workers[0].exists())
        self.assertEqual("merged", merge(self.repo, self.config, self.payload)["status"])
        self.assertEqual("a = 1\n", (self.repo / "src/a.py").read_text())
        self.assertEqual("b = 1\n", (self.repo / "src/b.py").read_text())

    def test_previous_request_ownership_does_not_authorize_new_changes(self) -> None:
        self.prepare_delivered_dependency()
        (self.integration / "src/a.py").write_text("a = 9\n")
        git(self.integration, "add", "src/a.py")
        git(self.integration, "commit", "-m", "unexpected historical scope edit")
        self.refresh_candidate()
        with self.assertRaisesRegex(DeliveryError, "outside the request"):
            merge(self.repo, self.config, self.payload)

    def test_pm_projection_is_not_a_directory_or_code_write_permission(self) -> None:
        for projection in (["docs/plans"], ["docs/features/"], ["docs/plans/../x.md"],
                           ["src/a.py"], ["docs/plans/new.md", "docs/plans/new.md"]):
            self.payload["projection_paths"] = projection
            with self.subTest(projection=projection), self.assertRaisesRegex(DeliveryError, "exact changed Markdown"):
                merge(self.repo, self.config, self.payload)
            self.assertEqual(self.base, head(self.repo))

    def test_exact_validated_pm_projection_merges_with_refreshed_full_qa_scope(self) -> None:
        document = self.integration / "docs/plans/features.md"
        document.parent.mkdir()
        document.write_text("# Feature delivery\n- Status: awaiting merge\nBoth feature units verified.\n")
        git(self.integration, "add", "docs/plans/features.md")
        git(self.integration, "commit", "-m", "PM assessed recovery projection")
        self.payload["projection_paths"] = ["docs/plans/features.md"]
        self.refresh_candidate()
        self.assertEqual("merged", merge(self.repo, self.config, self.payload)["status"])
        self.assertEqual(document.read_bytes(), (self.repo / "docs/plans/features.md").read_bytes())

    def test_transitive_writer_dependency_cannot_be_hidden_behind_evidence(self) -> None:
        self.tasks[0]["blocks"] = ["evidence"]
        self.tasks[1]["depends_on"] = ["evidence"]
        self.tasks.append({"id": "evidence", "request_id": "req", "task_type": "evidence", "depends_on": ["a"],
                           "blocks": ["b"], "gates": [], "owned_paths": [], "semantic_locks": [],
                           "state": "QA_SCOPE_READY"})
        with self.assertRaises(DeliveryError):
            merge(self.repo, self.config, self.payload)
        self.assertEqual(self.base, head(self.repo))
        # 同一拓扑只修正真实基线即可放行，不需要重复 A 或新增一轮业务批准。
        git(self.workers[1], "merge", "--no-edit", head(self.workers[0]))
        self.tasks[1]["execution_workspace"].update(base_revision=head(self.workers[0]),
                                                    head_revision=head(self.workers[1]))
        git(self.integration, "merge", "--no-edit", head(self.workers[1]))
        self.refresh_candidate()
        self.assertEqual("merge_ready", merge_check(self.repo, self.config, self.payload)["status"])

    def test_ignored_local_file_is_not_overwritten_by_delivery(self) -> None:
        # 仅操作临时仓库的本地忽略规则，模拟主目录中不应被分支交付覆盖的用户文件。
        (self.repo / ".git/info/exclude").write_text("local.txt\n")
        (self.repo / "local.txt").write_text("user ignored data\n")
        (self.workers[0] / "local.txt").write_text("task version\n")
        git(self.workers[0], "add", "-f", "local.txt")
        git(self.workers[0], "commit", "-m", "task adds a tracked file")
        self.tasks[0]["owned_paths"].append("local.txt")
        for document in self.tasks[0]["controlled_document_access"]["documents"]:
            document["applies_to"].append("local.txt")
        self.tasks[0]["execution_workspace"]["head_revision"] = head(self.workers[0])
        git(self.integration, "merge", "--no-edit", head(self.workers[0]))
        self.refresh_candidate()
        with self.assertRaises(DeliveryError):
            merge(self.repo, self.config, self.payload)
        self.assertEqual(self.base, head(self.repo))
        self.assertEqual("user ignored data\n", (self.repo / "local.txt").read_text())

    def test_qa_cannot_substitute_task_rules_or_standard_sources(self) -> None:
        for defect in ("task_rules", "source", "required"):
            payload = copy.deepcopy(self.payload)
            coverage = payload["qa_handoff"]["standards_policy_coverage"]
            if defect == "task_rules":
                coverage["task_pack_rule_ids"].append("eng-unassigned")
            elif defect == "source":
                coverage["rule_checks"][0]["source_fingerprint"] = "0" * 64
            else:
                # 独立报告内部仍自洽，但把必审规则替换为另一规则；必须由交叉合同校验拦截。
                coverage["required_engineering_rule_ids"] = ["eng-unassigned"]
                coverage["task_pack_rule_ids"].append("eng-unassigned")
                coverage["rule_checks"][0]["rule_id"] = "eng-unassigned"
                for check in coverage["path_checks"]:
                    check["applicable_rule_ids"] = ["eng-unassigned"]
            with self.subTest(defect=defect), self.assertRaises(DeliveryError):
                merge(self.repo, self.config, payload)

    def test_cli_merges_exact_candidate_without_pushing(self) -> None:
        result = subprocess.run([sys.executable, str(PACK / "lib/worktree_cli.py"), "merge", "--repo", str(self.repo),
                                 "--config", str(self.config)], input=json.dumps(self.payload), capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("merged", json.loads(result.stdout)["status"])
        self.assertFalse(json.loads(result.stdout)["pushed"])
        self.assertEqual(self.tip, head(self.repo))

    def test_missing_or_stale_consent_preserves_main(self) -> None:
        for key, value in (("source", "recommendation"), ("head_revision", self.base),
                           ("target_branch", "master"), ("diff_fingerprint", "0" * 64)):
            payload = copy.deepcopy(self.payload)
            payload["authorization"][key] = value
            with self.subTest(key=key), self.assertRaises(DeliveryError):
                merge(self.repo, self.config, payload)
            self.assertEqual(self.base, head(self.repo))

    def test_auto_cannot_be_inferred_from_requirements_approval(self) -> None:
        self.payload["authorization"].update(mode="auto", source="project:parallel_worktrees.merge")
        with self.assertRaisesRegex(DeliveryError, "explicit project"):
            merge(self.repo, self.config, self.payload)
        self.assertEqual(self.base, head(self.repo))

    def test_explicit_auto_mode_needs_no_user_reply(self) -> None:
        # 配置本身的改动必须进入共同基线，不能留下脏主目录再以测试之名绕过检查。
        self.config.write_text(self.config.read_text().replace("merge: confirm", "merge: auto"))
        git(self.repo, "add", "agent_workflow/project.yaml")
        git(self.repo, "commit", "-m", "enable project automatic delivery")
        new_base = head(self.repo)
        git(self.integration, "merge", "--no-edit", new_base)
        new_tip = head(self.integration)
        # 工作单元原基线不包含项目策略新提交，因此重建该场景的工作单元到新共同基线。
        for task, worker in zip(self.tasks, self.workers):
            git(worker, "merge", "--no-edit", new_base)
            task["execution_workspace"].update(base_revision=new_base, head_revision=head(worker))
            git(self.integration, "merge", "--no-edit", head(worker))
        new_tip = head(self.integration)
        self.record.update(target_base=new_base, head_revision=new_tip)
        self.record["verification"][0]["head_revision"] = new_tip
        actual = scope(self.repo, new_base, new_tip)
        self.payload["qa_handoff"]["review_method"]["scope_ref"]["repositories"] = [actual]
        self.payload["authorization"].update(mode="auto", source="project:parallel_worktrees.merge",
                                              target_base=new_base, head_revision=new_tip,
                                              diff_fingerprint=actual["diff_fingerprint"])
        self.assertEqual("merged", merge(self.repo, self.config, self.payload)["status"])

    def test_changed_target_is_not_automatically_rebased_or_merged(self) -> None:
        (self.repo / "user.txt").write_text("user's concurrent work\n")
        git(self.repo, "add", "user.txt")
        git(self.repo, "commit", "-m", "user change")
        current = head(self.repo)
        with self.assertRaisesRegex(DeliveryError, "target branch moved"):
            merge(self.repo, self.config, self.payload)
        self.assertEqual(current, head(self.repo))
        self.assertTrue(self.integration.is_dir())

    def test_refreshed_integration_reuses_completed_checkpoints_after_target_advances(self) -> None:
        original_workers = [head(worker) for worker in self.workers]
        (self.repo / "user.txt").write_text("new main branch work\n")
        git(self.repo, "add", "user.txt")
        git(self.repo, "commit", "-m", "user advances main")
        new_base = head(self.repo)
        git(self.integration, "merge", "--no-edit", new_base)
        self.refresh_candidate(new_base)
        self.assertEqual("merged", merge(self.repo, self.config, self.payload)["status"])
        self.assertEqual(original_workers, [head(worker) for worker in self.workers])
        self.assertEqual("new main branch work\n", (self.repo / "user.txt").read_text())

    def test_dirty_or_untracked_user_work_is_preserved(self) -> None:
        target = self.repo / "src/a.py"
        target.write_text("user unfinished edit\n")
        (self.repo / "user.txt").write_text("untracked user work\n")
        with self.assertRaisesRegex(DeliveryError, "not clean"):
            merge(self.repo, self.config, self.payload)
        self.assertEqual("user unfinished edit\n", target.read_text())
        self.assertEqual("untracked user work\n", (self.repo / "user.txt").read_text())

    def test_failed_stale_or_missing_integration_evidence_blocks_qa(self) -> None:
        for evidence in ([], [{**self.record["verification"][0], "exit_code": 1}],
                         [{**self.record["verification"][0], "head_revision": self.base}]):
            graph = copy.deepcopy(self.graph)
            graph["worktree_integrations"]["req"]["verification"] = evidence
            self.assertFalse(_execute("qa-ready", graph)["qa_ready"])
        self.assertTrue(_execute("qa-ready", self.graph)["qa_ready"])

    def test_lost_integration_metadata_cannot_silently_use_ordinary_qa(self) -> None:
        graph = copy.deepcopy(self.graph)
        del graph["worktree_integrations"]
        with self.assertRaises(WorktreePolicyError):
            _execute("qa-ready", graph)

    def test_incomplete_nonwriter_also_blocks_final_delivery(self) -> None:
        self.tasks.append({"id": "acceptance", "request_id": "req", "task_type": "evidence",
                           "depends_on": [], "blocks": [], "gates": [], "owned_paths": [],
                           "semantic_locks": [], "state": "RUNNING"})
        with self.assertRaisesRegex(DeliveryError, "not complete"):
            merge(self.repo, self.config, self.payload)

    def test_unrelated_request_does_not_block_delivery(self) -> None:
        self.tasks.append({"id": "other", "request_id": "unrelated", "task_type": "evidence",
                           "depends_on": [], "blocks": [], "gates": [], "owned_paths": [],
                           "semantic_locks": [], "state": "RUNNING"})
        self.assertEqual("merged", merge(self.repo, self.config, self.payload)["status"])

    def test_qa_failure_or_wrong_scope_blocks_delivery(self) -> None:
        for defect in ("fail", "scope", "standards"):
            payload = copy.deepcopy(self.payload)
            qa = payload["qa_handoff"]
            if defect == "fail":
                qa["audit_result"] = "FAIL"
            elif defect == "scope":
                qa["review_method"]["scope_ref"]["repositories"][0]["diff_fingerprint"] = "0" * 64
            else:
                qa["standards_policy_coverage"]["index_fingerprint"] = "0" * 64
            with self.subTest(defect=defect), self.assertRaises(DeliveryError):
                merge(self.repo, self.config, payload)
            self.assertEqual(self.base, head(self.repo))

    def test_changed_worker_head_or_dirty_integration_invalidates_handoff(self) -> None:
        (self.integration / "src/a.py").write_text("a = 3\n")
        with self.assertRaisesRegex(DeliveryError, "not clean"):
            merge(self.repo, self.config, self.payload)

    def test_dependency_must_actually_be_in_worker_base(self) -> None:
        self.tasks[0]["blocks"] = ["b"]
        self.tasks[1]["depends_on"] = ["a"]
        with self.assertRaises(DeliveryError):
            merge(self.repo, self.config, self.payload)
        self.assertEqual(self.base, head(self.repo))

    def test_worker_scope_cannot_expand_beyond_ownership(self) -> None:
        self.tasks[0]["owned_paths"] = ["src/other.py"]
        for document in self.tasks[0]["controlled_document_access"]["documents"]:
            document["applies_to"] = ["src/other.py"]
        with self.assertRaisesRegex(DeliveryError, "owned_paths"):
            merge(self.repo, self.config, self.payload)

    def test_main_resolution_does_not_guess_ambiguous_names(self) -> None:
        self.assertEqual("main", target_branch(self.repo, "auto"))
        git(self.repo, "branch", "master")
        with self.assertRaisesRegex(DeliveryError, "cannot resolve"):
            target_branch(self.repo, "auto")
        self.assertEqual("main", target_branch(self.repo, "main"))

    def test_create_does_not_overwrite_or_use_inherited_root(self) -> None:
        for candidate in (self.repo, self.repo / "nested", self.workers[0]):
            with self.subTest(candidate=candidate), self.assertRaises(DeliveryError):
                create(self.repo, candidate, self.base)
        self.assertEqual(self.base, head(self.repo))

    def test_missing_cli_inputs_report_controlled_errors(self) -> None:
        result = subprocess.run([sys.executable, str(PACK / "lib/worktree_cli.py"), "merge", "--repo", str(self.repo)],
                                capture_output=True, text=True)
        self.assertEqual(2, result.returncode)
        self.assertNotIn("Traceback", result.stderr)


class HostWorktreePolicyTest(UnifiedHostFixture, unittest.TestCase):
    def test_all_hosts_install_reference_without_forcing_every_role_to_worktree(self) -> None:
        temporary, project, pack = self.install_all()
        self.addCleanup(temporary.cleanup)
        for root in (".agents/skills", ".claude/skills"):
            relative = "xy-workflow/references/worktree-delivery.md"
            self.assertEqual((pack / "platforms/shared/skills" / relative).read_bytes(),
                             (project / root / relative).read_bytes())
        for role in (project / ".claude/agents").glob("*.md"):
            self.assertNotIn("\nisolation: worktree\n", role.read_text())
        for host in HOSTS:
            result = self.run_script(project, f"setup_{host}.sh", "--check")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_invalid_merge_setting_stops_every_host_before_writes(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                config = pack / "project.yaml"
                config.write_text(config.read_text().replace("merge: confirm", "merge: force"))
                result = self.run_script(project, f"setup_{host}.sh", "--preflight")
                self.assertNotEqual(0, result.returncode)
                self.assert_no_project_outputs(project)
