"""只用本 request 的临时数据验证聚合、原记录 CAS 与真实插件同包消费者。"""

from __future__ import annotations

import copy
import importlib.util
import zipfile
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib import dispatch_admission_cli as cli, task_graph_records as records
from lib.platform_fs import directory_lock
from tests.test_task_graph_records import graph


PACK = Path(__file__).resolve().parents[1]
# 非 Windows 源码入口沿唯一解释器wrapper；插件用其真实载荷入口。
PYTHON = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8"]


def plugin_fixture(root: Path) -> Path:
    """真实离线构建并解包当前候选；不调用安装器，不生成中央pin或用户配置。"""
    spec = importlib.util.spec_from_file_location("p7_plugin_builder", PACK / "packaging/build_plugin.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    archive = builder.build(PACK, root / "archives", "codex")
    installed = root / "installed-plugin"
    installed.mkdir()
    with zipfile.ZipFile(archive) as payload:
        payload.extractall(installed)
    return installed


def plugin_helper(installed: Path, project: Path, helper: str) -> list[str]:
    """只执行真实包内白名单入口，不依赖源码cwd或旧中央桥。"""
    return [sys.executable, "-B", "-X", "utf8", str(installed / "plugins/source_pack.py"),
            "helper", "--project", str(project), helper]



class AdmissionTest(unittest.TestCase):
    def setUp(self):
        # 使用任务既有 scratch 分配入口，多个用例在同一 request 夹具内复用；
        # unittest 的清理由夹具所有者负责，不触碰真实项目、HOME 或宿主配置。
        self.temporary = tempfile.TemporaryDirectory(prefix="admission-", dir=os.environ.get("AWF_TEST_SCRATCH"))
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

    def test_actual_light_qa_claim_preserves_original_qa_scope_metadata(self):
        """Light QA同一完整包可领取；临时就绪投影不删除正式审查范围。"""
        path = self.add_record("qa-request", level="Light", task_type="qa")
        before = json.loads(path.read_bytes())
        self.assertIn("reviewed_ui_changes", before)
        # 先证明错误QA范围不能被临时投影静默删除；拒绝时原记录字节保持。
        self.modify(path, lambda value: value.update(reviewed_ui_changes=["forged-ui-scope"]))
        invalid = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "record helper rejected"):
            cli.admission("claim", self.manifest, self.key(path))
        self.assertEqual(invalid, path.read_bytes())
        path.write_text(json.dumps(before), encoding="utf-8")
        self.refresh(path)
        result = cli.admission("claim", self.manifest, self.key(path))
        self.assertEqual("claimed", result["status"])
        after = json.loads(path.read_bytes())
        self.assertEqual("qa", after["task"]["task_type"])
        self.assertEqual(before["reviewed_ui_changes"], after["reviewed_ui_changes"])
        self.assertEqual("RUNNING", after["task"]["state"])

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
        # 原 pin 的 ready 必须先完成完整校验，坏 schema/tasks 不可先触发物理
        # owned_paths 投影；此处调用真实校验 helper，只监测投影边界是否被进入。
        for invalid in ("schema_version", "tasks"):
            with self.subTest(invalid_before_resource_projection=invalid):
                self.manifest["records"] = []
                broken = self.add_record("invalid")
                self.modify(broken, lambda value: value.update({invalid: 1 if invalid == "schema_version" else None}))
                with patch.object(cli, "_resource_identity", side_effect=AssertionError("invalid contract reached projection")) as projection:
                    with self.assertRaisesRegex(ValueError, "record helper rejected"):
                        cli.admission("view", self.manifest)
                    projection.assert_not_called()
        self.manifest["records"] = []
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
        query = cli._query
        def drift_after_ready(payload, root, command):
            result = query(payload, root, command)
            if command == "ready" and payload.get("tasks", [{}])[0].get("request_id") == "b":
                # 最后一条记录已真实就绪后，较早读取的 A 发生字节漂移；初始
                # ready 不能被当作已领取，仍须在原协作锁内拒绝后续 CAS。
                a.write_bytes(a.read_bytes() + b"\n")
            return result
        with patch.object(cli, "_query", side_effect=drift_after_ready), self.assertRaisesRegex(ValueError, "changed during"):
            cli.admission("claim", self.manifest, self.key(a))
        self.assertEqual("DECLARED", json.loads(a.read_bytes())["tasks"][0]["state"])
        self.refresh(a)
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
            # 使用真实另一个进程竞争同一短锁，不能用进程内嵌套模拟领取互斥。
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

    def test_actual_cli_rejects_same_request_duplicate_qa_before_any_claim(self):
        """复现两个合法空owned/locks的QA；真实核心校验先拒绝，view/claim均不写记录。"""
        from tests.test_scheduler_boundaries import v2_task
        path = self.add_record("a", state="BUILD_VERIFIED")
        def append_reviewers(value):
            for task_id in ("qa1", "qa2"):
                value["tasks"].append(v2_task({"id": task_id, "request_id": "a", "task_type": "qa",
                    "state": "DECLARED", "depends_on": [], "blocks": [], "gates": [],
                    "owned_paths": [], "semantic_locks": []}))
        self.modify(path, append_reviewers)
        self.manifest["records"][0]["execution_roots"].update(qa1=str(self.project), qa2=str(self.project))
        manifest = self.workspace / "duplicate-reviewers.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        before = path.read_bytes()
        for command, task_id in (("view", None), ("claim", "qa1"), ("claim", "qa2")):
            arguments = [*PYTHON, str(PACK / "lib/dispatch_admission_cli.py"), command, "--input", str(manifest)]
            if task_id:
                arguments.extend(["--record", str(path), "--request-id", "a", "--task-id", task_id])
            rejected = subprocess.run(arguments, env=self.environment, cwd=self.project,
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
            self.assertIn("one QA task per request", rejected.stderr)
            self.assertEqual(before, path.read_bytes())

    def test_cross_record_qa_identity_stays_unique_including_history_and_requests_remain_independent(self):
        original = self.add_record("original-review", level="Light", task_type="qa")
        second = self.add_record("second-review", level="Light", task_type="qa")
        self.assertEqual([self.key(original), self.key(second)], cli.admission("view", self.manifest)["candidates"])
        self.modify(second, lambda value: value["task"].update(request_id="original-review"))
        for state in ("DECLARED", "RUNNING", "QA_PASSED", "FAILED"):
            self.modify(original, lambda value: value["task"].update(state=state))
            before = (original.read_bytes(), second.read_bytes())
            for command in ("view", "claim"):
                with self.subTest(state=state, command=command), self.assertRaisesRegex(ValueError, "one QA task per request"):
                    cli.admission(command, self.manifest, self.key(second) if command == "claim" else None)
            self.assertEqual(before, (original.read_bytes(), second.read_bytes()))

    def test_original_reviewer_delta_review_preserves_identity_and_idempotent_running_update(self):
        """复查更新同一QA，不能重新claim或换绑；既有失败恢复及幂等状态语义保留。"""
        path = self.add_record("review", level="Light", task_type="qa")
        self.assertEqual("claimed", cli.admission("claim", self.manifest, self.key(path))["status"])
        reference = {"host": "codex", "agent_id": "fixture-original-reviewer"}
        def update(fields):
            return subprocess.run([*PYTHON, str(PACK / "lib/task_graph_cli.py"), "update", "--input", str(path),
                "--expect-sha256", records.digest(path.read_bytes()), "--patch", "-"],
                input=json.dumps({"tasks": {"api": {"set": fields}}}), env=self.environment,
                cwd=self.project, capture_output=True, text=True, timeout=30)
        for fields in ({"agent_ref": reference}, {"state": "RUNNING", "agent_ref": reference},
                       {"state": "FAILED"}, {"state": "RUNNING"}, {"state": "QA"}):
            observed = update(fields)
            self.assertEqual(0, observed.returncode, observed.stdout + observed.stderr)
        before = path.read_bytes()
        rejected = update({"agent_ref": {**reference, "agent_id": "another-reviewer"}})
        self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertEqual(before, path.read_bytes())
        self.refresh(path)
        self.assertEqual([], cli.admission("view", self.manifest)["candidates"])
        with self.assertRaisesRegex(ValueError, "not an admitted"):
            cli.admission("claim", self.manifest, self.key(path))
        self.assertEqual(reference, json.loads(path.read_bytes())["task"]["agent_ref"])

    def test_actual_git_scopes_share_reviewer_across_worktrees_but_not_other_repositories(self):
        """以真实Git共同目录投影身份，同名request跨仓独立、跨worktree仍属同请求。"""
        from lib.dispatch_admission import select_candidates
        def git(root, *arguments):
            return subprocess.run(["git", "-C", str(root), *arguments], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git(self.project, "init", "-q")
        git(self.project, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "--allow-empty", "-qm", "fixture")
        worktree = self.workspace / "review-worktree"
        git(self.project, "worktree", "add", "--detach", "-q", str(worktree), "HEAD")
        other = self.workspace / "independent-project"
        other.mkdir()
        git(other, "init", "-q")
        path = self.add_record("shared-request", level="Light", task_type="qa")
        original = json.loads(path.read_bytes())
        views = []
        for index, root in enumerate((self.project, worktree, other)):
            source = root / f"review-{index}.json"
            source.write_text(json.dumps(original), encoding="utf-8")
            manifest = {**self.manifest, "project_root": str(root), "records": [{"path": str(source),
                "sha256": records.digest(source.read_bytes()), "execution_roots": {"api": str(root)}}]}
            views.append(cli._load(manifest)[1][0])
        self.assertEqual(views[0].semantic_scope, views[1].semantic_scope)
        self.assertNotEqual(views[0].semantic_scope, views[2].semantic_scope)
        with self.assertRaisesRegex(ValueError, "one QA task per request"):
            select_candidates(tuple(views[:2]), self.manifest["capacity"])
        admitted = select_candidates((views[0], views[2]), self.manifest["capacity"])
        self.assertEqual(2, len(admitted["candidates"]))

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



    def test_actual_plugin_helper_claims_current_record_and_rejects_all_legacy_contexts(self):
        installed = plugin_fixture(self.workspace)
        path = self.add_record("a")
        manifest = self.workspace / "plugin-manifest.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        command = plugin_helper(installed, self.project, "lib/dispatch_admission_cli.py")
        def invoke(*arguments, environment=None):
            return subprocess.run([*command, *arguments, "--input", str(manifest)], cwd=self.project,
                                  env=self.environment if environment is None else environment,
                                  text=True, capture_output=True, timeout=60)
        observed = invoke("view")
        self.assertEqual(0, observed.returncode, observed.stdout + observed.stderr)
        self.assertEqual([self.key(path)], json.loads(observed.stdout)["candidates"])
        before = path.read_bytes()
        for value in (None, {}, {"core_version": "2.1.4", "content_id": "0" * 64, "manifest_sha256": "0" * 64}):
            self.modify(path, lambda payload: payload.update(runtime_binding=value))
            manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
            rejected = invoke("view")
            self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
            self.assertIn("runtime_binding", rejected.stderr)
        path.write_bytes(before)
        self.refresh(path)
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        for name in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                     "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"):
            with self.subTest(central_environment=name):
                rejected = invoke("view", environment={**self.environment, name: "legacy-context"})
                self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
                self.assertIn("central", rejected.stderr)
                self.assertEqual(before, path.read_bytes())
        marker = self.project / ".agent-workflow/runtime.json"
        marker.parent.mkdir()
        marker.write_bytes(b"{}")
        rejected = invoke("view")
        self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertIn("central", rejected.stderr)
        self.assertEqual(before, path.read_bytes())
        marker.unlink()
        marker.parent.rmdir()
        claimed = invoke("claim", "--record", str(path), "--request-id", "a", "--task-id", "api")
        self.assertEqual(0, claimed.returncode, claimed.stdout + claimed.stderr)
        self.assertEqual("claimed", json.loads(claimed.stdout)["status"])
        self.assertNotIn("runtime_binding", json.loads(path.read_bytes()))
        print("PLUGIN_ADMISSION: actual packaged view/claim; old bindings rejected; native creation unverified", flush=True)

    def test_old_binding_never_calls_bridge_or_manager_even_without_plugin_environment(self):
        path = self.add_record("a")
        self.modify(path, lambda payload: payload.update(runtime_binding={"unexpected": "old core"}))
        # 应在本地资源守卫明确拒绝；禁止启动任何记录helper或访问旧中央内容库。
        with patch("lib.runtime_store.load_core", side_effect=AssertionError("legacy store must not run")), \
                patch.object(cli.subprocess, "run", side_effect=AssertionError("helper must not start")):
            # 非Git项目身份查询也是只读进程，因此只直接进入同包调用边界做负控。
            with self.assertRaisesRegex(ValueError, "runtime_binding"):
                cli._invocation(json.loads(path.read_bytes()), self.project, ["ready"])

    def test_unlisted_external_activity_reserves_unknown_subtrees_and_semantic_resources(self):
        path = self.add_record("a", owned="unknown-child/future.py", lock="external-lock")
        self.modify(path, lambda payload: payload.update(active_paths=["unknown-child/other.py"],
                                                         active_semantic_locks=["external-lock"]))
        with patch.object(cli, "_directory_case_sensitive", return_value=None):
            observed = cli.admission("view", self.manifest)
        self.assertEqual([], observed["candidates"])
        self.assertIn("path_conflict", observed["waiting"][0]["reasons"])
        self.assertIn("semantic_lock_conflict", observed["waiting"][0]["reasons"])


    def test_two_real_claim_processes_cannot_allocate_the_same_record_twice(self):
        """同一快照由两个真实进程并发领取，仅一个原记录CAS可成功。"""
        path = self.add_record("a")
        manifest = self.workspace / "racing-manifest.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        command = [*PYTHON, str(PACK / "lib/dispatch_admission_cli.py"), "claim", "--input", str(manifest),
                   "--record", str(path), "--request-id", "a", "--task-id", "api"]
        processes = [subprocess.Popen(command, cwd=self.project, env=self.environment,
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        observations = [(process, *process.communicate(timeout=45)) for process in processes]
        self.assertEqual([0, 2], sorted(process.returncode for process in processes), observations)
        successes = [json.loads(stdout) for process, stdout, _ in observations if process.returncode == 0]
        self.assertEqual(1, len(successes))
        self.assertEqual("claimed", successes[0]["status"])
        task = json.loads(path.read_bytes())["tasks"][0]
        self.assertEqual("RUNNING", task["state"])
        self.assertNotIn("agent_ref", task)
        print("CLAIM_RACE: two actual processes, one CAS claim, no native agent created", flush=True)


if __name__ == "__main__":
    unittest.main()
