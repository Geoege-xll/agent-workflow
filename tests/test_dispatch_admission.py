"""只用本 request 的临时数据验证聚合、原记录 CAS 与真实中央薄桥消费者。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib import dispatch_admission_cli as cli, task_graph_records as records
from lib.platform_fs import directory_lock
from tests.test_task_graph_records import graph


PACK = Path(__file__).resolve().parents[1]
# macOS 沿项目 wrapper；Windows 直接复用原生隔离 bootstrap，不依赖 Git Bash。
PYTHON = ([sys.executable, "-I", "-B", "-X", "utf8", str(PACK / "lib/windows_bootstrap.py"), "--script"]
          if os.name == "nt" else ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8"])


class AdmissionTest(unittest.TestCase):
    def setUp(self):
        # 使用任务既有 scratch 分配入口，多个用例在同一 request 夹具内复用；
        # unittest 的清理由夹具所有者负责，不触碰真实项目、HOME 或宿主配置。
        self.temporary = tempfile.TemporaryDirectory(prefix="admission-", dir=Path(__file__).resolve().parents[2])
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()
        self.project = self.workspace / "project"
        self.project.mkdir()
        # 独立 one/two 资源的共同父目录真实存在，才能核实该父目录的名称规则；
        # 未创建的中间目录应保守占子树，不能靠原夹具隐含“未来目录继承”来并行。
        (self.project / "src").mkdir()
        (self.project / "src/name-rule-fixture.txt").write_text("fixture\n")
        self.manifest = {"schema_version": 1, "project_root": str(self.project), "records": [],
                         "capacity": {"configured_subagents": 4, "configured_writers": 3,
                                      "host_available_subagents": 4}}
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith("AGENT_WORKFLOW_")}
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
        self.environment_patch = patch.dict(os.environ, self.environment, clear=True)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def add_record(self, name, *, state="DECLARED", owned="src/one", lock="api", level="Full", task_type="writer", approved=True):
        value = graph()
        value.update(active_paths=[], active_semantic_locks=[])
        task = value["tasks"][0]
        task.update(request_id=name, state=state, owned_paths=[owned], semantic_locks=[lock] if lock else [])
        for document in task["controlled_document_access"]["documents"]:
            document["applies_to"] = [owned]
        if task_type != "writer":
            task.update(task_type=task_type, role="xy-qa" if task_type == "qa" else "xy-backend", owned_paths=[], semantic_locks=[])
            task["controlled_document_access"] = {"adapter": "project.yaml", "documents": []}
            task["audit_surfaces"] = []
        if not approved:
            value["approved_gates"] = []
        if state == "RUNNING":
            value.update(active_paths=list(task["owned_paths"]), active_semantic_locks=list(task["semantic_locks"]))
        if level == "Light":
            from lib.task_graph_cli import export_task_pack
            value = export_task_pack(value, task["id"])
            value["task"]["workflow_level"] = "Light"
        path = self.project / f"{name}.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        self.manifest["records"].append({"path": str(path), "sha256": records.digest(path.read_bytes()),
                                         "execution_roots": {task["id"]: str(self.project)}})
        return path

    def refresh(self, path):
        next(item for item in self.manifest["records"] if item["path"] == str(path))["sha256"] = records.digest(path.read_bytes())

    def modify(self, path, change):
        value = json.loads(path.read_bytes())
        change(value)
        path.write_text(json.dumps(value), encoding="utf-8")
        self.refresh(path)

    def key(self, path):
        value = json.loads(path.read_bytes())
        task = value.get("task") or value["tasks"][0]
        return {"record": str(path), "request_id": task["request_id"], "task_id": task["id"]}

    def test_running_a_conflicting_b_waits_and_independent_c_advances_without_gate_leak(self):
        self.add_record("a", state="RUNNING")
        b = self.add_record("b", owned="src/one/sub", lock="different")
        c = self.add_record("c", owned="src/two", lock="other")
        denied = self.add_record("d", owned="src/three", lock="third", approved=False)
        before = set(self.project.iterdir())
        result = cli.admission("view", self.manifest)
        self.assertEqual([self.key(c)], result["candidates"])
        waiting = {row["record"]: row["reasons"] for row in result["waiting"]}
        self.assertIn("path_conflict", waiting[str(b)])
        self.assertIn("record_gates_dependencies_locks_or_qa", waiting[str(denied)])
        self.assertEqual((1, 1), (result["active_subagents"], result["active_writers"]))
        self.assertEqual(before, set(self.project.iterdir()))
        self.assertFalse(records._project_scratch_base(self.project).exists())

    def test_candidates_reserve_resources_and_writer_limit_leaves_read_only_and_light_qa_slots(self):
        a = self.add_record("a", level="Light")
        self.add_record("b", owned="src/other", lock="api")
        read_only = self.add_record("c", task_type="read_only")
        qa = self.add_record("d", level="Light", task_type="qa")
        self.manifest["capacity"]["configured_writers"] = 1
        result = cli.admission("view", self.manifest)
        self.assertEqual([self.key(a), self.key(read_only), self.key(qa)], result["candidates"])
        self.assertIn("semantic_lock_conflict", result["waiting"][0]["reasons"])
        self.assertIn("writer_capacity", result["waiting"][0]["reasons"])

    def test_unbound_claim_reserves_the_native_slot_before_agent_creation(self):
        a = self.add_record("a")
        self.add_record("b", owned="src/two", lock="other")
        self.manifest["capacity"].update(configured_subagents=8, configured_writers=8, host_available_subagents=1)
        cli.admission("claim", self.manifest, self.key(a))
        self.refresh(a)
        held = cli.admission("view", self.manifest)
        self.assertEqual([], held["candidates"])
        self.assertEqual(1, held["unbound_claims"])
        self.assertEqual(0, held["remaining_subagent_slots"])

    def test_claim_duplicate_unknown_and_confirmed_failure_release_use_original_state_and_sha(self):
        path = self.add_record("a", level="Light", state="READY")
        key = self.key(path)
        receipt = cli.admission("claim", self.manifest, key)
        self.assertEqual("RUNNING", json.loads(path.read_bytes())["task"]["state"])
        self.assertNotIn("agent_ref", json.loads(path.read_bytes())["task"])
        with self.assertRaisesRegex(ValueError, "fingerprint changed"):
            cli.admission("claim", self.manifest, key)
        self.refresh(path)
        with self.assertRaisesRegex(ValueError, "not an admitted"):
            cli.admission("claim", self.manifest, key)
        held = path.read_bytes()
        malformed = {**receipt, "prior_state": []}
        with self.assertRaisesRegex(ValueError, "invalid prior_state"):
            cli.admission("release", self.manifest, receipt=malformed, outcome="definitely_not_created")
        retained = cli.admission("release", self.manifest, receipt=receipt, outcome="unknown")
        self.assertEqual("retained", retained["status"])
        self.assertEqual(held, path.read_bytes())
        result = cli.admission("release", self.manifest, receipt=receipt, outcome="definitely_not_created")
        self.assertEqual("READY", result["state"])
        self.assertEqual("READY", json.loads(path.read_bytes())["task"]["state"])
        with self.assertRaises(ValueError):
            cli.admission("release", self.manifest, receipt=receipt, outcome="definitely_not_created")

    def test_sha_change_bound_or_retired_claim_cannot_release_or_spawn_again(self):
        path = self.add_record("a")
        key = self.key(path)
        receipt = cli.admission("claim", self.manifest, key)
        self.modify(path, lambda value: value["tasks"][0].update(agent_ref={"host": "codex", "agent_id": "/fixture/a"}))
        # 原生创建已成功但后续绑定/发布失败都不能被当作“确定未创建”自动释放。
        with self.assertRaisesRegex(ValueError, "release requires"):
            cli.admission("release", self.manifest, receipt=receipt, outcome="definitely_not_created")
        self.assertEqual([], cli.admission("view", self.manifest)["candidates"])
        self.modify(path, lambda value: value["tasks"][0].update(agent_retired=True))
        result = cli.admission("view", self.manifest)
        self.assertEqual(1, result["active_writers"])
        self.assertIn("agent_retired", result["waiting"][0]["reasons"])

    def test_duplicate_sources_handoff_packs_agent_identity_and_forged_validation_are_rejected(self):
        path = self.add_record("a", state="RUNNING")
        other = self.add_record("b", state="BUILD_VERIFIED", owned="src/two", lock="other")
        self.manifest["records"].append(copy.deepcopy(self.manifest["records"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate authoritative"):
            cli.admission("view", self.manifest)
        self.manifest["records"].pop()
        for source in (path, other):
            self.modify(source, lambda value: value["tasks"][0].update(agent_ref={"host": "codex", "agent_id": "/same"}))
        with self.assertRaisesRegex(ValueError, "shared across"):
            cli.admission("view", self.manifest)
        self.manifest["records"][0]["validated"] = True
        with self.assertRaisesRegex(ValueError, "requires exactly"):
            cli.admission("view", self.manifest)
        self.manifest["records"][0].pop("validated")
        from lib.task_graph_cli import export_task_pack
        self.modify(path, lambda value: None)
        path.write_text(json.dumps(export_task_pack(json.loads(path.read_bytes()), "api")))
        self.refresh(path)
        with self.assertRaisesRegex(ValueError, "Full handoff"):
            cli.admission("view", self.manifest)

    def test_all_record_sha_rechecked_under_lock_and_failed_publish_keeps_claim(self):
        a = self.add_record("a")
        b = self.add_record("b", owned="src/two", lock="other")
        original = cli._recheck
        def drift(views):
            b.write_bytes(b.read_bytes() + b"\n")
            original(views)
        with patch.object(cli, "_recheck", side_effect=drift), self.assertRaisesRegex(ValueError, "changed during"):
            cli.admission("claim", self.manifest, self.key(a))
        self.assertEqual("DECLARED", json.loads(a.read_bytes())["tasks"][0]["state"])
        self.refresh(b)
        receipt = cli.admission("claim", self.manifest, self.key(a))
        self.refresh(a)
        original_payload = json.loads(a.read_bytes())
        binding_patch = {"tasks": {"api": {"set": {"agent_ref": {"host": "codex", "agent_id": "/fixture/observed"}}}}}
        with self.assertRaisesRegex(ValueError, "fingerprint differs"):
            cli._helper(original_payload, self.project,
                        ["update", "--input", str(a), "--root", str(self.project), "--patch", "-",
                         "--expect-sha256", receipt["previous_sha256"]], json.dumps(binding_patch).encode())
        self.assertNotIn("agent_ref", json.loads(a.read_bytes())["tasks"][0])
        self.assertEqual("RUNNING", json.loads(a.read_bytes())["tasks"][0]["state"])
        # 用真实记录的父目录发布锁制造 CAS 发布失败，验证不会偷偷释放已有领取。
        with directory_lock(self.project, "taskgraph"), self.assertRaisesRegex(ValueError, "helper rejected"):
            cli.admission("release", self.manifest, receipt=receipt, outcome="definitely_not_created")
        self.assertEqual("RUNNING", json.loads(a.read_bytes())["tasks"][0]["state"])

    def test_project_claim_lock_rejects_concurrent_writer_without_blocking_view(self):
        path = self.add_record("a")
        manifest = self.workspace / "manifest.json"
        manifest.write_text(json.dumps(self.manifest))
        with cli._project_lock(self.project):
            # 使用真实另一个进程；Windows mutex 同线程可重入，进程内嵌套不能
            # 证明跨进程领取互斥，POSIX/Windows 在此共用同一可观察边界。
            competing = subprocess.run([*PYTHON, str(PACK / "lib/dispatch_admission_cli.py"), "claim", "--input", str(manifest),
                                        "--record", str(path), "--request-id", "a", "--task-id", "api"],
                                       env=self.environment, cwd=self.project, capture_output=True, text=True, timeout=30)
            self.assertEqual(2, competing.returncode, competing.stdout + competing.stderr)
            self.assertEqual([self.key(path)], cli.admission("view", self.manifest)["candidates"])

    def test_lost_update_result_retains_real_published_claim_without_automatic_retry(self):
        path = self.add_record("a")
        run = subprocess.run
        updates = []
        def lose_result(command, *args, **kwargs):
            result = run(command, *args, **kwargs)
            if "update" in command:
                updates.append(command)
                # 实际子进程已经完成原 CAS，模拟调用者未收到其结果的边界。
                # 这里不是把 mock 当原生启动：只验证真实磁盘发布后的未知结果。
                raise subprocess.TimeoutExpired(command, 120)
            return result
        with patch.object(cli.subprocess, "run", side_effect=lose_result), self.assertRaisesRegex(ValueError, "inspect original record"):
            cli.admission("claim", self.manifest, self.key(path))
        self.assertEqual(1, len(updates))
        self.assertEqual("RUNNING", json.loads(path.read_bytes())["tasks"][0]["state"])
        self.refresh(path)
        self.assertEqual([], cli.admission("view", self.manifest)["candidates"])

    def test_full_qa_uses_existing_request_barrier_and_shared_thread_capacity(self):
        path = self.add_record("a", state="RUNNING")
        def append_qa(value):
            from tests.test_scheduler_boundaries import v2_task
            value["tasks"].append(v2_task({"id": "qa", "request_id": "a", "task_type": "qa", "state": "DECLARED",
                "depends_on": [], "blocks": [], "gates": [], "owned_paths": [], "semantic_locks": []}))
        self.modify(path, append_qa)
        self.manifest["records"][0]["execution_roots"]["qa"] = str(self.project)
        qa_key = {"record": str(path), "request_id": "a", "task_id": "qa"}
        self.assertEqual([], cli.admission("view", self.manifest)["candidates"])
        self.modify(path, lambda value: value["tasks"][0].update(state="BUILD_VERIFIED"))
        self.modify(path, lambda value: value.update(active_paths=[], active_semantic_locks=[]))
        self.assertEqual([qa_key], cli.admission("view", self.manifest)["candidates"])
        claimed = cli.admission("claim", self.manifest, qa_key)
        self.assertEqual("claimed", claimed["status"])
        self.refresh(path)
        self.assertEqual(1, cli.admission("view", self.manifest)["active_subagents"])
        self.assertEqual(0, cli.admission("view", self.manifest)["active_writers"])

    def test_actual_source_cli_and_invalid_schema_return_json_exit_two(self):
        path = self.add_record("a")
        manifest = self.workspace / "manifest.json"
        manifest.write_text(json.dumps(self.manifest))
        result = subprocess.run([*PYTHON, str(PACK / "lib/dispatch_admission_cli.py"), "claim", "--input", str(manifest),
                                 "--record", str(path), "--request-id", "a", "--task-id", "api"],
                                env=self.environment, cwd=self.project, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("claimed", json.loads(result.stdout)["status"])
        manifest.write_text("[]")
        failed = subprocess.run([*PYTHON, str(PACK / "lib/dispatch_admission_cli.py"), "claim", "--input", str(manifest)],
                                env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(2, failed.returncode)
        self.assertIn("error", json.loads(failed.stderr))

    def test_actual_worktree_roots_separate_paths_but_share_semantic_locks(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)
        git("init", "-q")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture")
        head = subprocess.check_output(["git", "-C", str(self.project), "rev-parse", "HEAD"], text=True).strip()
        roots = []
        for name in ("worker-a", "worker-b", "integration-a", "integration-b"):
            root = self.workspace / name
            git("worktree", "add", "--detach", "-q", str(root), head)
            roots.append(root)
        a = self.add_record("a", state="RUNNING")
        b = self.add_record("b", lock="other")
        for path, root, integration in ((a, roots[0], roots[2]), (b, roots[1], roots[3])):
            def bind(value):
                request_id = value["tasks"][0]["request_id"]
                value["tasks"][0]["execution_workspace"] = {"root": str(root), "base_revision": head, "head_revision": None}
                value["worktree_integrations"] = {request_id: {"root": str(integration), "target_branch": "main",
                    "target_base": head, "head_revision": None, "verification": []}}
            self.modify(path, bind)
            next(item for item in self.manifest["records"] if item["path"] == str(path))["execution_roots"]["api"] = str(root)
        self.assertEqual([self.key(b)], cli.admission("view", self.manifest)["candidates"])
        other_entry = copy.deepcopy(self.manifest)
        other_entry["project_root"] = str(roots[0])
        manifest = self.workspace / "worktree-entry.json"
        manifest.write_text(json.dumps(other_entry))
        git_root = Path(cli._git_identity(self.project))
        git_names = set(git_root.iterdir())
        # 同 Git 项目从另一个 worktree 进入也必须命中同一临界区；锁本身
        # 仍位于系统 scratch，不能把 .git 当成新的资源账本或状态目录。
        with cli._project_lock(self.project) as scope:
            self.assertEqual(scope, cli._git_identity(roots[0]))
            competing = subprocess.run([*PYTHON, str(PACK / "lib/dispatch_admission_cli.py"), "claim", "--input", str(manifest),
                                        "--record", str(b), "--request-id", "b", "--task-id", "api"],
                                       env=self.environment, cwd=roots[0], capture_output=True, text=True, timeout=30)
            self.assertEqual(2, competing.returncode, competing.stdout + competing.stderr)
        self.assertEqual(git_names, set(git_root.iterdir()))
        self.modify(b, lambda value: value["tasks"][0].update(semantic_locks=["api"]))
        result = cli.admission("view", self.manifest)
        self.assertEqual([], result["candidates"])
        self.assertIn("semantic_lock_conflict", result["waiting"][1]["reasons"])
        other_entry["records"] = copy.deepcopy(self.manifest["records"])
        self.assertEqual([], cli.admission("view", other_entry)["candidates"])
        self.manifest["records"][1]["execution_roots"]["api"] = str(self.project)
        with self.assertRaisesRegex(ValueError, "differs from original"):
            cli.admission("view", self.manifest)

    def test_native_name_equivalence_conflicts_for_existing_and_not_yet_created_resources(self):
        """使用当前真实卷判断大小写别名，覆盖不存在叶以及不存在中间目录。"""
        existing = self.project / "CaseArea"
        existing.mkdir()
        leaf = existing / "Existing.py"
        leaf.write_text("fixture\n")
        insensitive = (self.project / "casearea/existing.PY").exists()
        for first, second in (("CaseArea/Existing.py", "casearea/existing.PY"),
                              ("CaseArea/NotYet/New.py", "casearea/notyet/NEW.PY")):
            with self.subTest(first=first, second=second):
                self.manifest["records"] = []
                self.add_record("a", state="RUNNING", owned=first, lock="")
                candidate = self.add_record("b", owned=second, lock="")
                projected = cli.admission("view", self.manifest)
                if insensitive:
                    self.assertEqual([], projected["candidates"])
                    self.assertIn("path_conflict", projected["waiting"][1]["reasons"])
                else:
                    self.assertEqual([self.key(candidate)], projected["candidates"])

        # Python 官方合同：Windows DirEntry.stat 的身份字段恒零，不能和
        # Path.lstat 的实际 ID 混用。此处只注入缓存/查找结果的边界差异，
        # 上面的真实卷与真实 CLI 冲突断言完整保留，不冒充 Windows 实机。
        from contextlib import nullcontext
        from types import SimpleNamespace
        fresh = leaf.lstat()
        different = existing / "Distinct.py"
        different.write_text("another physical node\n")
        distinct = different.lstat()
        unknown = SimpleNamespace(st_mode=fresh.st_mode, st_dev=0, st_ino=0, st_file_attributes=0)
        entry = SimpleNamespace(name=leaf.name, stat=lambda **kwargs: unknown)
        for label, original, alias, expected in (("same", fresh, fresh, False),
                                                  ("different", fresh, distinct, True),
                                                  ("unknown-original", unknown, fresh, None),
                                                  ("unknown-alias", fresh, unknown, None)):
            with self.subTest(cache_zero_and_fresh_identity=label):
                def lookup(location, *args, **kwargs):
                    if location.name == leaf.name:
                        return original
                    if location.name == leaf.name.swapcase():
                        return alias
                    raise AssertionError("unexpected identity lookup")
                with patch.object(cli.sys, "platform", "case-probe"), \
                        patch.object(cli.os, "scandir", side_effect=lambda directory: nullcontext([entry])), \
                        patch.object(Path, "lstat", new=lookup):
                    self.assertIs(expected, cli._directory_case_sensitive(existing))

    def test_sensitive_names_stay_distinct_and_unknown_future_names_lock_the_existing_parent(self):
        """只验证已核实规则的映射合同，不把注入的策略冒充敏感卷实机验收。"""
        from lib.dispatch_admission import _overlap
        first = self.project / "NotYet/One.py"
        second = self.project / "notyet/ONE.PY"
        with patch.object(cli, "_directory_case_sensitive", return_value=True):
            self.assertFalse(_overlap(cli._resource_identity(first, {}), cli._resource_identity(second, {})))
        with patch.object(cli, "_directory_case_sensitive", return_value=None):
            self.assertTrue(_overlap(cli._resource_identity(first, {}),
                                     cli._resource_identity(self.project / "independent/new.py", {})))
        # 大小写规则不能证明未创建 Unicode 名称的卷规范化规则；保守占住现有父树。
        with patch.object(cli, "_directory_case_sensitive", return_value=True):
            self.assertTrue(_overlap(cli._resource_identity(self.project / "新文件.py", {}),
                                     cli._resource_identity(first, {})))

    def test_future_directory_children_do_not_inherit_the_existing_parents_case_rule(self):
        """仅第一不存在分量的父规则已知，未来目录内的 Foo/foo 必须保守冲突。"""
        from lib.dispatch_admission import _overlap
        with patch.object(cli, "_directory_case_sensitive", return_value=True):
            first = cli._resource_identity(self.project / "FutureCaseDir214/Foo.py", {})
            second = cli._resource_identity(self.project / "FutureCaseDir214/foo.py", {})
            self.assertTrue(_overlap(first, second))
            # 敏感父目录内不同的第一分量仍独立，不能粗锁整个项目。
            other = cli._resource_identity(self.project / "futureCaseDir214/Foo.py", {})
            self.assertFalse(_overlap(first, other))

    def test_execution_root_binding_uses_physical_identity_when_path_equality_folds_case(self):
        """注入 Windows 式词法相等控制流，实际根身份仍来自两个真实独立目录。"""
        from pathlib import PureWindowsPath
        self.assertEqual(PureWindowsPath("C:/Project"), PureWindowsPath("C:/project"))
        unrelated = self.workspace / "other-project"
        unrelated.mkdir()
        self.assertFalse(self.project.samefile(unrelated))
        path = self.add_record("a")
        self.manifest["records"][0]["execution_roots"]["api"] = str(unrelated)
        selected_roots = {str(self.project), str(unrelated)}
        class FoldingPath(type(Path())):
            def __eq__(self, other):
                if str(self) in selected_roots and str(other) in selected_roots:
                    return True
                return super().__eq__(other)
            __hash__ = type(Path()).__hash__
        absolute = cli._absolute
        def folded_absolute(value, **kwargs):
            result = absolute(value, **kwargs)
            return FoldingPath(result) if str(result) in selected_roots else result
        with patch.object(cli, "_absolute", side_effect=folded_absolute), self.assertRaisesRegex(ValueError, "differs from original"):
            cli.admission("view", self.manifest)
        self.assertEqual("DECLARED", json.loads(path.read_bytes())["tasks"][0]["state"])

    def test_worktree_qa_uses_its_original_request_integration_root(self):
        """QA 不伪造 writer-only execution_workspace，从请求集成记录选择审查树。"""
        from tests.test_scheduler_boundaries import v2_task
        def git(*arguments):
            return subprocess.run(["git", "-C", str(self.project), *arguments], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git("init", "-q")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture")
        head = git("rev-parse", "HEAD")
        for request_id in ("a", "b"):
            writer = self.workspace / (request_id + "-writer")
            integration = self.workspace / (request_id + "-integration")
            for execution in (writer, integration):
                git("worktree", "add", "--detach", "-q", str(execution), head)
            path = self.add_record(request_id, state="BUILD_VERIFIED", owned="src/" + request_id, lock="")
            def bind(value):
                value["tasks"][0]["execution_workspace"] = {"root": str(writer), "base_revision": head, "head_revision": head}
                value["tasks"].append(v2_task({"id": "qa", "request_id": request_id, "task_type": "qa", "state": "DECLARED",
                    "depends_on": [], "blocks": [], "gates": [], "owned_paths": [], "semantic_locks": []}))
                value["worktree_integrations"] = {request_id: {"root": str(integration), "target_branch": "main",
                    "target_base": head, "head_revision": head,
                    "verification": [{"command": "fixture-key-entry", "exit_code": 0,
                                      "log_ref": "fixture-contract-only", "head_revision": head}]}}
            self.modify(path, bind)
            next(item for item in self.manifest["records"] if item["path"] == str(path))["execution_roots"] = {
                "api": str(writer), "qa": str(integration)}
        projected = cli.admission("view", self.manifest)
        self.assertEqual(["qa", "qa"], [item["task_id"] for item in projected["candidates"]])
        qa = projected["candidates"][0]
        claimed = cli.admission("claim", self.manifest, qa)
        self.assertEqual("claimed", claimed["status"])
        original = json.loads(Path(qa["record"]).read_bytes())
        self.assertNotIn("execution_workspace", original["tasks"][1])
        self.assertEqual("RUNNING", original["tasks"][1]["state"])
        self.refresh(Path(qa["record"]))
        self.manifest["records"][0]["execution_roots"]["qa"] = str(self.project)
        with self.assertRaisesRegex(ValueError, "differs from original"):
            cli.admission("view", self.manifest)

    def test_detached_installed_cli_mixed_pins_validate_and_claim_through_each_original_core(self):
        """双版本是真实冻结安装，不把调用者的 validated 标志或 mock 当作验证。

        混合 pin 的必要输入是两个完整核心。只为本用例建立一次可复用 source
        夹具，版本差异是一条无行为影响的中文注释；两版均经真实清单/安装校验。
        运行时 cwd 是薄项目且环境固定 B，A 必须通过原桥显式转入自身核心。
        """
        from lib import runtime_store as store
        from lib.central.runtime_project import Tree, json_bytes
        from manager import runtime_policy as policy, runtime_service as projects
        from manager.runtime_state import read_state, write_control
        import uuid

        state = self.workspace / "machine-state"
        core_a = store.import_core(PACK, state)
        source = self.workspace / "version-source"
        source.mkdir()
        for relative in store.CORE_DIRECTORIES:
            shutil.copytree(PACK / relative, source / relative,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for relative in store.SETUP_FILES:
            shutil.copy2(PACK / relative, source / relative)
        with (source / "lib/dispatch_admission.py").open("a", encoding="utf-8") as stream:
            stream.write("\n# 中央双版本回归夹具：仅区分内容身份，业务合同保持一致。\n")
        core_b = store.import_core(source, state)
        self.assertNotEqual(core_a.binding(), core_b.binding())
        def set_current(binding):
            with policy.coordination(state), Tree(state) as tree:
                write_control(tree, policy.CURRENT,
                              json_bytes({"schema_version": 1, "runtime_binding": binding,
                                          "previous_binding": None, "generation": uuid.uuid4().hex,
                                          "native_roots": []}), expected=read_state(state, policy.CURRENT))
        set_current(core_a.binding())
        projects.apply(projects.preview(state, self.project, "enable", binding=core_a.binding()))
        a = self.add_record("a", state="RUNNING")
        self.modify(a, lambda value: value.update(runtime_binding=core_a.binding()))
        b = self.add_record("b", owned="src/two", lock="other", level="Light")
        self.modify(b, lambda value: value.update(runtime_binding=core_b.binding()))
        set_current(core_b.binding())
        projects.apply(projects.preview(state, self.project, "use", binding=core_b.binding()))
        # 仅保留中央内容库，移走必要测试source夹具，保证实际入口不依赖原源码路径。
        shutil.rmtree(source)
        environment = {**self.environment, "AGENT_WORKFLOW_STATE_DIR": str(state)}
        manifest = self.workspace / "manifest.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        launcher = ([sys.executable, "-I", "-B", "-X", "utf8"] if os.name == "nt" else
                    ["bash", str(self.project / ".agent-workflow/lib/python_runtime.sh"), "-B", "-X", "utf8"])
        command = [*launcher, str(self.project / ".agent-workflow/runtime.py"),
                   "--binding", json.dumps(core_b.binding()), "helper", "lib/dispatch_admission_cli.py"]
        def installed(*arguments):
            result = subprocess.run([*command, *arguments], env=environment, cwd=self.project,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return json.loads(result.stdout)
        viewed = installed("view", "--input", str(manifest))
        self.assertEqual([self.key(b)], viewed["candidates"])
        claimed = installed("claim", "--input", str(manifest), "--record", str(b),
                            "--request-id", "b", "--task-id", "api")
        self.assertEqual("claimed", claimed["status"])
        self.assertEqual(core_a.binding(), json.loads(a.read_bytes())["runtime_binding"])
        self.assertEqual(core_b.binding(), json.loads(b.read_bytes())["runtime_binding"])
        self.assertEqual("RUNNING", json.loads(b.read_bytes())["task"]["state"])
        self.refresh(b)
        manifest.write_text(json.dumps(self.manifest))
        receipt = self.workspace / "receipt.json"
        receipt.write_text(json.dumps(claimed))
        self.assertEqual("released", installed("release", "--input", str(manifest), "--receipt", str(receipt),
                                                "--outcome", "definitely_not_created")["status"])
        # B 环境中领取 A：先明确把 A 的原状态恢复为 pending，仍保留 A pin。
        # 本用例未调用原生spawn；状态变更只是测试输入，不是实例存活证据。
        self.modify(a, lambda value: value["tasks"][0].update(state="DECLARED"))
        self.modify(a, lambda value: value.update(active_paths=[], active_semantic_locks=[]))
        self.refresh(b)
        manifest.write_text(json.dumps(self.manifest))
        claimed_a = installed("claim", "--input", str(manifest), "--record", str(a),
                              "--request-id", "a", "--task-id", "api")
        self.assertEqual("claimed", claimed_a["status"])
        self.assertEqual(core_a.binding(), json.loads(a.read_bytes())["runtime_binding"])


if __name__ == "__main__":
    unittest.main()
