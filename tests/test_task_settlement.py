"""只用request自有夹具验证原记录原子结算；原生模型观察由独立补验负责。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from lib import task_graph_records as records
from lib.agent_continuation import active, continuation
from lib.task_graph import TaskGraphError, Task, validate_graph
from lib.task_graph_cli import _execute, export_task_pack, pack_snapshot, replace_pack_task
from tests.test_agent_continuation import PACK, PYTHON
from tests.test_task_graph_records import graph


class TaskSettlementTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="settlement-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "record.json"
        self.accepted = self.root / "accepted-pack.json"
        self.evidence = self.root / "result.log"
        # 此处是明确标记的测试输入，不能被作为真实原生完成或模型运行证据。
        self.evidence.write_bytes(b"fixture native completion and verification output\n")

    def fixture(self, *, kind="evidence", light=False, downstream=False):
        payload = graph()
        task = payload["tasks"][0]
        task.update(task_type=kind, state="RUNNING", agent_ref={"host": "codex", "agent_id": "fixture-native-a"})
        payload.update(active_paths=["src/one", "external/"], active_semantic_locks=["api", "external-lock"])
        if downstream:
            other = copy.deepcopy(task)
            other.update(id="next", agent_alias="fixture-next", task_type="read_only", state="DECLARED",
                         depends_on=["api"], blocks=[])
            other.pop("agent_ref")
            task["blocks"] = ["next"]
            payload["tasks"].append(other)
        if light:
            payload = export_task_pack(payload, "api")
            payload["task"]["workflow_level"] = "Light"
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        pack = copy.deepcopy(payload) if light else export_task_pack(payload, "api")
        self.accepted.write_text(json.dumps(pack), encoding="utf-8")
        evidence = {"path": str(self.evidence), "sha256": records.digest(self.evidence.read_bytes())}
        sha = records.digest(self.accepted.read_bytes())
        reference = task["agent_ref"]
        value = {"schema_version": 1, "agent_ref": reference,
                 "task_pack": {"path": str(self.accepted), "sha256": sha},
                 "completion": {"state": "completed", "agent_ref": reference, "task_pack_sha256": sha, "evidence": evidence},
                 "result": {"task_pack_sha256": sha, "evidence": [evidence]},
                 "verification": [{"command": task["verification_commands"][0], "exit_code": 0, "evidence": evidence}],
                 "retire": True}
        return payload, {"tasks": {"api": {"settle": value}}}

    def update(self, payload, patch):
        if "task" not in payload:
            return records.update(payload, patch, None, _execute)
        def validate(command, candidate):
            return _execute(command, replace_pack_task(payload, candidate["tasks"][0]))
        result = records.update(pack_snapshot(payload), patch, None, validate)
        return replace_pack_task(payload, result["tasks"][0])

    def invoke(self, payload, patch, *, command=None, environment=None, cwd=PACK, expected=None):
        """真正通过保护CLI的已有update传输新操作，失败必须留下完整原记录。"""
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        before = self.source.read_bytes()
        result = subprocess.run([*(command or [*PYTHON, str(PACK / "lib/task_graph_cli.py")]),
                                 "update", "--input", str(self.source), "--expect-sha256", expected or records.digest(before),
                                 "--patch", "-"], input=json.dumps(patch), cwd=cwd, env=environment,
                                text=True, capture_output=True, check=False, timeout=60)
        return result, before

    def test_both_result_types_settle_full_and_light_release_only_owned_activity(self):
        for kind in ("read_only", "evidence"):
            for light in (False, True):
                payload, patch = self.fixture(kind=kind, light=light)
                before = copy.deepcopy(payload)
                result, _ = self.invoke(payload, patch)
                self.assertEqual(0, result.returncode, result.stderr)
                updated = records.decode(self.source.read_bytes())
                task = updated.get("task") or updated["tasks"][0]
                self.assertEqual("RESULT_VERIFIED", task["state"])
                self.assertTrue(task["agent_retired"])
                self.assertEqual(before.get("task", before.get("tasks", [None])[0])["agent_ref"], task["agent_ref"])
                self.assertFalse(active(task))
                self.assertEqual("blocked", continuation(task, "codex", "idle")["action"])
                self.assertIn("RESULT_VERIFIED settlement:", task["acceptance_evidence"][-1])
                if not light:
                    self.assertEqual(["external/"], updated["active_paths"])
                    self.assertEqual(["external-lock"], updated["active_semantic_locks"])
                self.assertEqual(before, payload)

    def test_refuses_unknown_running_old_scope_unbound_and_failed_or_changed_evidence(self):
        mutations = (
            lambda p, s: s["completion"].update(state="running"),
            lambda p, s: s["completion"].update(state="unknown"),
            lambda p, s: s["completion"].update(agent_ref={"host": "codex", "agent_id": "other"}),
            lambda p, s: s.update(agent_ref={"host": "claude", "agent_id": "fixture-native-a"}),
            lambda p, s: s["completion"].update(task_pack_sha256="0" * 64),
            lambda p, s: s["result"].update(task_pack_sha256="0" * 64),
            lambda p, s: p["tasks"][0].pop("agent_ref"),
            lambda p, s: p["tasks"][0]["input_contracts"].append("new accepted scope"),
            lambda p, s: s["verification"][0].update(exit_code=1),
            lambda p, s: s.update(verification=[]),
            lambda p, s: s["task_pack"].update(sha256="0" * 64),
            lambda p, s: s["completion"]["evidence"].update(sha256="0" * 64),
            lambda p, s: s["result"].update(evidence=[]),
            lambda p, s: s.update(retire="true"),
            lambda p, s: p.update(approved_gates=[]),
            lambda p, s: p["standards_contract"].update(index_fingerprint="f" * 64),
        )
        for index, mutate in enumerate(mutations):
            payload, patch = self.fixture()
            mutate(payload, patch["tasks"]["api"]["settle"])
            with self.subTest(index=index), self.assertRaises((TaskGraphError, ValueError)):
                self.update(payload, patch)
        payload, patch = self.fixture()
        self.evidence.unlink()
        with self.assertRaises(ValueError):
            self.update(payload, patch)

    def test_safe_pack_read_rejects_links_duplicate_json_and_oversized_inputs(self):
        payload, patch = self.fixture()
        target = self.root / "pack-target.json"
        target.write_bytes(self.accepted.read_bytes())
        self.accepted.unlink()
        self.accepted.symlink_to(target)
        with self.assertRaises(ValueError):
            self.update(payload, patch)
        self.accepted.unlink()
        for body in (b'{"schema_version":2,"schema_version":2}', b"x" * (4 * 1024 * 1024 + 1), b"[]"):
            self.accepted.write_bytes(body)
            patch["tasks"]["api"]["settle"]["task_pack"]["sha256"] = records.digest(body)
            with self.subTest(body_size=len(body)), self.assertRaises(ValueError):
                self.update(payload, patch)

    def test_only_settle_can_enter_result_state_and_no_writer_or_qa_gate_is_bypassed(self):
        payload, patch = self.fixture()
        invalid = (
            {"tasks": {"api": {"set": {"state": "RESULT_VERIFIED"}}}},
            {"tasks": {"api": {**patch["tasks"]["api"], "set": {"state": "RUNNING"}}}},
            {**patch, "capacity": 20},
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(TaskGraphError):
                self.update(payload, change)
        for kind in ("writer", "qa"):
            payload, patch = self.fixture(kind=kind)
            with self.subTest(kind=kind), self.assertRaisesRegex(TaskGraphError, "read_only or evidence"):
                self.update(payload, patch)
            with self.assertRaisesRegex(TaskGraphError, "RESULT_VERIFIED"):
                validate_graph([Task("invalid", "request", task_type=kind, state="RESULT_VERIFIED")])

    def test_completed_scope_change_requires_pending_and_retirement_does_not_complete_running(self):
        payload, patch = self.fixture()
        retired = self.update(payload, {"tasks": {"api": {"set": {"agent_retired": True}}}})
        self.assertTrue(active(retired["tasks"][0]))
        self.assertEqual(set(payload["active_paths"]), set(retired["active_paths"]))
        completed = self.update(retired, patch)
        with self.assertRaisesRegex(TaskGraphError, "pending state"):
            self.update(completed, {"tasks": {"api": {"append": {"input_contracts": ["new scope"]}}}})
        with self.assertRaisesRegex(TaskGraphError, "retired"):
            self.update(completed, {"tasks": {"api": {"set": {"state": "RUNNING"}}}})
        self.assertFalse(_execute("qa-ready", completed)["qa_ready"])

    def test_declared_expected_negative_control_and_observation_only_need_no_fake_shell_check(self):
        for commands in ([], [{"run": "fixture-negative", "expected": "demonstrate declared failure"}]):
            payload, patch = self.fixture()
            payload["tasks"][0]["verification_commands"] = commands
            self.accepted.write_text(json.dumps(export_task_pack(payload, "api")), encoding="utf-8")
            settle = patch["tasks"]["api"]["settle"]
            sha = records.digest(self.accepted.read_bytes())
            settle["task_pack"]["sha256"] = sha
            settle["completion"]["task_pack_sha256"] = sha
            settle["result"]["task_pack_sha256"] = sha
            settle["verification"] = [] if not commands else [{"command": "fixture-negative", "exit_code": 1,
                "expected": commands[0]["expected"], "evidence": settle["completion"]["evidence"]}]
            self.assertEqual("RESULT_VERIFIED", self.update(payload, patch)["tasks"][0]["state"])

    def test_source_cli_stale_cas_keeps_original_and_success_unblocks_downstream(self):
        payload, patch = self.fixture(downstream=True)
        failed, before = self.invoke(payload, patch, expected="0" * 64)
        self.assertEqual(2, failed.returncode)
        self.assertEqual(before, self.source.read_bytes())
        passed, _ = self.invoke(payload, patch)
        self.assertEqual(0, passed.returncode, passed.stderr)
        updated = records.decode(self.source.read_bytes())
        self.assertEqual(["next"], _execute("ready", updated)["ready"])

    def test_installed_pin_cli_settles_original_record_and_admission_releases_execution_slot(self):
        """真实当前候选安装后调用原保护CLI和准入；不创建原生模型或伪造其通过。"""
        project = self.root / "project"
        project.mkdir()
        (project / "go.mod").write_text("module example.test/settlement\n", encoding="utf-8")
        home = self.root / "home"
        home.mkdir()
        state = self.root / "state"
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "CODEX_HOME": str(home / ".codex"),
               "CLAUDE_CONFIG_DIR": str(home / ".claude"), "AGENT_WORKFLOW_STATE_DIR": str(state)}
        installed = subprocess.run([*PYTHON, str(PACK / "lib/install/install_workflow.py"), str(project), "--state-dir", str(state)],
                                   cwd=PACK, env=env, text=True, capture_output=True, check=False, timeout=180)
        self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
        runtime = project / ".agent-workflow"
        binding = json.loads((runtime / "runtime.json").read_bytes())["runtime_binding"]
        # 原生Windows独立使用隔离解释器，POSIX仍沿唯一wrapper；不引入Bash依赖。
        import base64
        import sys
        launcher = ([sys.executable, "-I", "-B", "-X", "utf8"] if os.name == "nt" else
                    ["bash", str(runtime / "lib/python_runtime.sh"), "-B", "-X", "utf8"])
        flags = (["--binding-b64", base64.b64encode(json.dumps(binding).encode()).decode()]
                 if os.name == "nt" else ["--binding", json.dumps(binding)])
        bridge = [*launcher, str(runtime / "runtime.py"), *flags, "helper"]
        payload, patch = self.fixture(downstream=True)
        payload["runtime_binding"] = binding
        accepted = json.loads(self.accepted.read_bytes())
        accepted["runtime_binding"] = binding
        self.accepted.write_text(json.dumps(accepted), encoding="utf-8")
        settle = patch["tasks"]["api"]["settle"]
        sha = records.digest(self.accepted.read_bytes())
        settle["task_pack"]["sha256"] = sha
        settle["completion"]["task_pack_sha256"] = sha
        settle["result"]["task_pack_sha256"] = sha
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        manifest = self.root / "manifest.json"
        data = {"schema_version": 1, "project_root": str(project), "records": [],
                "capacity": {"configured_subagents": 1, "configured_writers": 1, "host_available_subagents": 1}}
        def view():
            data["records"] = [{"path": str(self.source), "sha256": records.digest(self.source.read_bytes()),
                                "execution_roots": {"api": str(project), "next": str(project)}}]
            manifest.write_text(json.dumps(data), encoding="utf-8")
            observed = subprocess.run([*bridge, "lib/dispatch_admission_cli.py", "view", "--input", str(manifest)],
                                      cwd=project, env=env, text=True, capture_output=True, check=False, timeout=60)
            self.assertEqual(0, observed.returncode, observed.stdout + observed.stderr)
            return json.loads(observed.stdout)
        self.assertEqual(1, view()["active_subagents"])
        # 错误接受包pin不能借调用环境的新核心补齐；失败后原状态及占用保持。
        wrong = copy.deepcopy(accepted)
        wrong["runtime_binding"].update(content_id="0" * 64, manifest_sha256="0" * 64)
        self.accepted.write_text(json.dumps(wrong), encoding="utf-8")
        rejected_patch = copy.deepcopy(patch)
        wrong_sha = records.digest(self.accepted.read_bytes())
        rejected_patch["tasks"]["api"]["settle"]["task_pack"]["sha256"] = wrong_sha
        rejected, before = self.invoke(payload, rejected_patch, command=[*bridge, "lib/task_graph_cli.py"], environment=env, cwd=project)
        self.assertEqual(2, rejected.returncode)
        self.assertEqual(before, self.source.read_bytes())
        self.accepted.write_text(json.dumps(accepted), encoding="utf-8")
        result, _ = self.invoke(payload, patch, command=[*bridge, "lib/task_graph_cli.py"], environment=env, cwd=project)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        after = view()
        self.assertEqual(0, after["active_subagents"])
        self.assertEqual(0, after["active_writers"])
        self.assertEqual("next", after["candidates"][0]["task_id"])
        print("INSTALLED_SETTLEMENT: pinned original update + admission; RESULT_VERIFIED; active_subagents 1->0; downstream ready; native close/runtime unverified", flush=True)


class SettlementWorktreeConsumerTest(unittest.TestCase):
    def test_actual_merge_check_accepts_result_dependency_but_keeps_writer_qa_gates(self):
        """复用已有真实Git/验证QA夹具，只增加本变更缺失的结果依赖消费者场景。"""
        from tests.test_worktree_delivery import GitDeliveryTest
        from tests.test_scheduler_boundaries import v2_task
        from lib.delivery.worktree_cli import merge_check
        fixture = GitDeliveryTest()
        try:
            fixture.setUp()
            dependency = v2_task({"id": "result", "request_id": "req", "task_type": "read_only",
                                  "state": "RESULT_VERIFIED", "depends_on": [], "blocks": ["a"],
                                  "gates": [], "owned_paths": [], "semantic_locks": []})
            fixture.tasks[0]["depends_on"] = ["result"]
            fixture.tasks.append(dependency)
            self.assertEqual("merge_ready", merge_check(fixture.repo, fixture.config, fixture.payload)["status"])
        finally:
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
