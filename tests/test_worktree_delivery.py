"""真实临时 Git 仓库验证隔离和交付；不接触用户项目，也不以文字匹配代替 Git 行为。"""

from __future__ import annotations

import copy
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib import task_graph_records as records
from lib.task_graph_cli import _execute, export_task_pack
from lib.delivery import worktree_cli
from lib.delivery.worktree_cli import DeliveryError, create, git, head, merge, merge_check, scope, target_branch
from lib.worktree_policy import WorktreePolicyError, settings
from tests import test_qa_handoff as qa_fixtures
from tests.test_scheduler_boundaries import _writer_payload, v2_graph, v2_task


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
    def setUp(self, *, pending_qa=False, adapter="agent_workflow/project.yaml") -> None:
        temporary = tempfile.TemporaryDirectory(prefix="workflow-delivery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "main"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Workflow Fixture")
        git(self.repo, "config", "user.email", "workflow-fixture@example.invalid")
        # 各夹具使用本地身份和确切文件；测试提交代表 PM 授权的临时检查点。
        self.config = self.repo / adapter
        self.config.parent.mkdir(exist_ok=True)
        self.config.write_text((PACK / "project.yaml").read_text())
        (self.repo / "src").mkdir()
        (self.repo / "src/a.py").write_text("a = 0\n")
        (self.repo / "src/b.py").write_text("b = 0\n")
        (self.repo / "docs/standards").mkdir(parents=True)
        (self.repo / "docs/STANDARDS.md").write_text("# Standards\n[General](standards/GENERAL.md)\n")
        (self.repo / "docs/standards/GENERAL.md").write_text(
            "# General\n- Domain: engineering\n[eng-source-boundary] [hard] Preserve ownership.\n")
        builtin_path = "platforms/shared/skills/xy-code-standards/references/rules.md"
        # 内置来源只存在于执行中的源包；业务仓库不复制规则来掩盖来源定位缺陷。
        builtin = PACK / builtin_path
        (self.repo / "docs/plans").mkdir()
        (self.repo / "docs/plans/baseline.md").write_text("# 已验收基线\n- 主题 ID: baseline\n- 阶段: active\n- 模块: .\n- 任务等级: Light\n- 已验收版本: v1\n"
            "## 验收结果与当前已交付行为\n已有行为。\n## 批准依据与必要证据\n"
            "- 批准依据: 既有用户批准\n- 验收证据: 既有验收记录\n")
        (self.repo / "docs/PROJECT.md").write_text("# Project\n[Baseline](plans/baseline.md)\n")
        git(self.repo, "add", adapter, "src/a.py", "src/b.py",
            "docs/STANDARDS.md", "docs/standards/GENERAL.md", "docs/PROJECT.md", "docs/plans/baseline.md")
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
                elif document["path"] == "docs/standards/GENERAL.md":
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
        self.qa_task = v2_task({"id": "qa", "request_id": "req", "task_type": "qa", "state": "QA",
                               "depends_on": [], "blocks": [], "gates": [], "owned_paths": [], "semantic_locks": [],
                               "agent_ref": {"host": "codex", "agent_id": "current-reviewer"}})
        self.tasks.append(self.qa_task)
        self.graph = v2_graph({"request_id": "req", "tasks": self.tasks, "approved_gates": ["requirements_approved"],
                               "worktree_integrations": {"req": self.record}, "standards_contract": standards})
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
        coverage["task_pack_rule_ids"].append("eng-common-005")
        coverage["required_engineering_rule_ids"].append("eng-common-005")
        coverage["rule_checks"].append({**copy.deepcopy(coverage["rule_checks"][0]), "rule_id": "eng-common-005",
            "source_path": builtin_path, "source_fingerprint": hashlib.sha256(builtin.read_bytes()).hexdigest(),
            "source_anchor": "配置、错误和维护"})
        self.qa_pack_file = self.root / "current-qa-pack.json"
        self.payload = {"task_graph": self.graph, "qa_handoff": qa, "qa_task_pack": str(self.qa_pack_file), "authorization": {
            "mode": "confirm", "source": "user:approve-current-merge", "request_id": "req",
            "target_branch": "main", "target_base": self.base, "head_revision": self.tip,
            "diff_fingerprint": actual["diff_fingerprint"]}}
        if pending_qa:
            # 宿主集成用例从未领取的 QA 开始，由其真实任务池绑定并验收这同一候选。
            self.qa_task["state"] = "DECLARED"
            self.qa_task.pop("agent_ref")
        else:
            self.accept_candidate()

    def accept_candidate(self) -> None:
        """使用同一测试 Reviewer 的真实导出与接收入口，测试随后单独运行正式 Git 交付。"""
        if self.qa_task["state"] == "QA_PASSED":
            reopened = records.update(self.graph, {"tasks": {"qa": {"set": {"state": "QA"}}}}, self.repo, _execute)
            self.qa_task.clear()
            self.qa_task.update(next(task for task in reopened["tasks"] if task["id"] == "qa"))
        current_pack = export_task_pack(self.graph, "qa", root=self.repo)
        body = json.dumps(current_pack).encode("utf-8")
        qa = self.payload["qa_handoff"]
        qa["handoff_ref"] = qa_fixtures.handoff_ref(current_pack, body)
        result_file = self.root / "current-qa-handoff.json"
        result = json.dumps(qa).encode("utf-8")
        self.qa_pack_file.write_bytes(body)
        result_file.write_bytes(result)
        accepted = records.update(self.graph, {"tasks": {"qa": {"accept_request": {
            "task_pack": {"path": str(self.qa_pack_file), "sha256": records.digest(body)},
            "handoff": {"path": str(result_file), "sha256": records.digest(result)},
        }}}}, self.repo, _execute)
        self.qa_task.update(next(task for task in accepted["tasks"] if task["id"] == "qa"))

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

    def test_cleaned_candidate_satisfies_dependencies_only_after_its_actual_delivery(self) -> None:
        from lib.foundation_qa import current_request_receipt
        from tests.test_foundation_qa import working_root

        self.tasks.append(v2_task({"id": "after-delivery", "request_id": "downstream", "task_type": "read_only",
                                   "state": "DECLARED", "depends_on": ["qa"], "blocks": [], "gates": [],
                                   "owned_paths": [], "semantic_locks": []}))
        self.graph.update(active_paths=[], active_semantic_locks=[], capacity=2)
        self.qa_task["blocks"] = ["after-delivery"]
        with working_root(self.repo):
            self.assertIn("after-delivery", _execute("ready", self.graph)["ready"])
            git(self.repo, "worktree", "remove", str(self.integration))
            self.assertNotIn("after-delivery", _execute("ready", self.graph)["ready"])
            with self.assertRaises((OSError, ValueError)):
                merge_check(self.repo, self.config, self.payload)
            # 重建同一真实候选并经正式交付后清理。只有目标分支的实际祖先关系
            # 才允许依赖继续使用原收据；单独拥有候选 Git 对象不构成交付事实。
            create(self.repo, self.integration, self.tip)
            self.assertEqual("merged", merge(self.repo, self.config, self.payload)["status"])
            git(self.repo, "worktree", "remove", str(self.integration))
            for worker in self.workers:
                git(self.repo, "worktree", "remove", str(worker))
            self.assertTrue(current_request_receipt(self.graph, self.qa_task))
            self.assertIn("after-delivery", _execute("ready", self.graph)["ready"])
            updated = records.update(self.graph, {"capacity": 2}, self.repo, _execute)
            self.assertEqual("QA_PASSED", next(task for task in updated["tasks"] if task["id"] == "qa")["state"])

    def refresh_candidate(self, base: str | None = None, *, accept: bool = True) -> None:
        """同步真实提交范围；针对陈旧/不安全候选的负控须保留上一轮已验收回执。"""
        self.tip = head(self.integration)
        self.record.update(target_base=base or self.record["target_base"], head_revision=self.tip)
        self.record["verification"][0]["head_revision"] = self.tip
        actual = scope(self.repo, self.record["target_base"], self.tip)
        self.payload["qa_handoff"]["review_method"]["scope_ref"]["repositories"] = [actual]
        coverage = self.payload["qa_handoff"]["standards_policy_coverage"]
        coverage["path_checks"] = [{"path": path, "applicable_rule_ids": list(coverage["required_engineering_rule_ids"]),
                                    "reason": "fixture source"} for path in actual["changed_paths"]]
        for check in coverage["rule_checks"]:
            check["affected_paths"] = actual["changed_paths"]
        self.payload["authorization"].update(target_base=self.record["target_base"], head_revision=self.tip,
                                              diff_fingerprint=actual["diff_fingerprint"])
        if accept:
            self.accept_candidate()

    def test_running_or_failed_qa_cannot_be_overridden_by_a_cached_pass(self) -> None:
        reviewer = self.qa_task
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

    def test_post_qa_plan_and_reviewed_architecture_merge_with_original_receipt(self) -> None:
        """结构说明进入受审候选；只有计划验收事实在 PASS 后提交，授权绑定最终合并 diff。"""
        from lib.foundation_qa import current_request_receipt
        architecture = "docs/ARCHITECTURE.md"
        (self.integration / architecture).write_text("# 架构\n模块 A 和 B 分别维护独立配置。\n")
        git(self.integration, "add", architecture)
        git(self.integration, "commit", "-m", "review the actual architecture description")
        name = "docs/plans/baseline.md"
        # 被审 Writer 也从这个 PM 主题选读已批准的内容。隔离候选的后像要同时
        # 按文档差异及该真实读取合同回放，最终集成可继续复用原回执。
        self.tasks[0]["controlled_document_access"]["documents"].append({
            "path": name, "mode": "targeted", "reason": "保留旧基线的批准依据",
            "sections_or_queries": ["批准依据"], "content_fingerprint": records.digest((self.integration / name).read_bytes()),
            "applies_to": self.tasks[0]["owned_paths"], "rule_ids": []})
        self.refresh_candidate()
        original = copy.deepcopy(self.qa_task["request_receipt"])
        path = self.integration / name
        saved = self.root / "reviewed-baseline.md"
        saved.write_bytes(path.read_bytes())
        path.write_text(path.read_text().replace("已有行为。", "新交付说明。\n\n已有行为。").replace(
            "既有验收记录", "既有验收记录 " + original["handoff"]["sha256"]))
        git(self.integration, "add", name)
        git(self.integration, "commit", "-m", "PM records acceptance evidence")
        projected_tip = head(self.integration)
        operation = {"adapter": str(self.config.relative_to(self.repo)), "head_revision": projected_tip, "documents": [{
            "path": name, "reviewed": {"path": str(saved), "sha256": records.digest(saved.read_bytes())},
            "projected_sha256": records.digest(path.read_bytes())}]}
        updated = records.update(self.graph, {"tasks": {"qa": {"record_qa_projection": operation}}}, self.repo, _execute)
        self.payload["task_graph"] = updated
        reviewer = next(task for task in updated["tasks"] if task["id"] == "qa")
        self.assertEqual(original, reviewer["request_receipt"])
        self.payload["projection_paths"] = [architecture, name]
        with self.assertRaisesRegex(DeliveryError, "authorization"):
            merge_check(self.repo, self.config, self.payload)
        self.payload["authorization"].update(head_revision=projected_tip,
            diff_fingerprint=scope(self.repo, self.base, projected_tip)["diff_fingerprint"])
        self.assertEqual("merged", merge(self.repo, self.config, self.payload)["status"])
        self.assertEqual(original, reviewer["request_receipt"])
        git(self.repo, "worktree", "remove", str(self.integration))
        self.assertTrue(current_request_receipt(updated, reviewer, root=self.repo))
        # 清理候选后仍要从已合并的 Git 对象和原档重放，不能仅凭目标分支祖先放行。
        saved.write_text("事后替换原档")
        self.assertFalse(current_request_receipt(updated, reviewer, root=self.repo))

    def test_exact_validated_pm_projection_merges_with_refreshed_full_qa_scope(self) -> None:
        document = self.integration / "docs/plans/features.md"
        document.parent.mkdir(exist_ok=True)
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
        self.tasks.append(v2_task({"id": "evidence", "request_id": "req", "task_type": "evidence", "depends_on": ["a"],
                           "blocks": ["b"], "gates": [], "owned_paths": [], "semantic_locks": [],
                           "state": "RESULT_VERIFIED"}))
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
        result = subprocess.run([sys.executable, str(PACK / "lib/delivery/worktree_cli.py"), "merge", "--repo", str(self.repo),
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
        self.accept_candidate()
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
        self.tasks.append(v2_task({"id": "acceptance", "request_id": "req", "task_type": "evidence",
                           "depends_on": [], "blocks": [], "gates": [], "owned_paths": [],
                           "semantic_locks": [], "state": "RUNNING"}))
        with self.assertRaisesRegex(DeliveryError, "not complete"):
            merge(self.repo, self.config, self.payload)

    def test_unrelated_request_does_not_block_delivery(self) -> None:
        self.tasks.append(v2_task({"id": "other", "request_id": "unrelated", "task_type": "evidence",
                           "depends_on": [], "blocks": [], "gates": [], "owned_paths": [],
                           "semantic_locks": [], "state": "RUNNING"}))
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

    def test_read_only_cli_runs_git_with_local_objects_only(self) -> None:
        cases = (
            ("target", ["--config", str(self.config)], {"target_branch": "main", "target_base": self.base}),
            ("inspect", ["--base", self.base, "--head", self.tip], {
                "path": ".", "base_revision": self.base, "head_revision": self.tip,
                "changed_paths": ["src/a.py", "src/b.py"],
                "diff_fingerprint": self.payload["authorization"]["diff_fingerprint"],
            }),
        )
        for command, options, expected in cases:
            with self.subTest(command=command):
                output = StringIO()
                argv = ["worktree_cli.py", command, "--repo", str(self.repo), *options]
                # 执行真实 Git，并确认外部环境变量无法放开对象传输。
                with (
                    patch.object(sys, "argv", argv),
                    patch.dict("os.environ", GIT_NO_LAZY_FETCH="0", GIT_ALLOW_PROTOCOL="file"),
                    redirect_stdout(output),
                    patch.object(subprocess, "run", wraps=subprocess.run) as commands,
                ):
                    self.assertEqual(0, worktree_cli.main())
                self.assertEqual(expected, json.loads(output.getvalue()))
                self.assertTrue(commands.call_args_list)
                for call in commands.call_args_list:
                    environment = call.kwargs["env"]
                    self.assertEqual("1", environment.get("GIT_NO_LAZY_FETCH"), call.args[0])
                    self.assertEqual("", environment.get("GIT_ALLOW_PROTOCOL"), call.args[0])

    def test_create_does_not_overwrite_or_use_inherited_root(self) -> None:
        for candidate in (self.repo, self.repo / "nested", self.workers[0]):
            with self.subTest(candidate=candidate), self.assertRaises(DeliveryError):
                create(self.repo, candidate, self.base)
        self.assertEqual(self.base, head(self.repo))

    def test_missing_cli_inputs_report_controlled_errors(self) -> None:
        result = subprocess.run([sys.executable, str(PACK / "lib/delivery/worktree_cli.py"), "merge", "--repo", str(self.repo)],
                                capture_output=True, text=True)
        self.assertEqual(2, result.returncode)
        self.assertNotIn("Traceback", result.stderr)
