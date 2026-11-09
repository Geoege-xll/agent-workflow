"""覆盖动作意图/实际能力边界及真实源码、固定中央薄桥消费者；不冒充宿主运行。"""

from __future__ import annotations

import copy
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lib.agent_continuation import HOSTS, continuation
from lib.task_graph import TaskGraphError
from tests.test_task_graph_records import graph


PACK = Path(__file__).resolve().parents[1]
# 测试入口也遵循平台解释器合同；原生 Windows 不能为调用新 CLI 反向依赖 Bash。
PYTHON = ([sys.executable, "-I", "-B", "-X", "utf8", str(PACK / "lib/windows_bootstrap.py"), "--script"]
          if os.name == "nt" else ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8"])


def running_record(host="codex"):
    """复用原有合法图合同，原生ID仅为算法输入，绝不称为真实已派发身份。"""
    record = graph()
    record["tasks"][0].update(state="RUNNING", agent_ref={"host": host, "agent_id": "test-native-id"})
    return record


class ContinuationDecisionTest(unittest.TestCase):
    def test_intent_and_capability_decisions_across_hosts_keep_original_identity(self):
        for host in HOSTS:
            task = running_record(host)["tasks"][0]
            before = copy.deepcopy(task)
            for intent, state, capabilities, action in (
                ("observe", "running", (), "wait"),
                ("observe", "running", ("non_interrupting_message",), "wait"),
                ("progress", "running", (), "wait"),
                ("append", "running", ("idle_followup",), "wait"),
                ("progress", "running", ("non_interrupting_message",), "message"),
                ("append", "running", ("non_interrupting_message",), "message"),
                ("append", "idle", (), "blocked"),
                ("append", "idle", ("idle_followup",), "followup"),
                ("independent", "running", ("non_interrupting_message",), "new_task"),
            ):
                with self.subTest(host=host, intent=intent, state=state, capabilities=capabilities):
                    result = continuation(task, host, state, intent=intent, capabilities=capabilities)
                    self.assertEqual(action, result["action"])
                    self.assertEqual(task["agent_ref"], result["agent_ref"])
                    self.assertEqual(intent == "append", result["acceptance_requires_ack"])
                    self.assertFalse(result["runtime_verified"])
                    if intent == "independent":
                        self.assertFalse(result["reuse_allowed"])
            self.assertEqual(before, task)

    def test_invalid_lifecycle_blocks_even_with_capabilities_or_independent_intent(self):
        for state in ("cancelled", "missing", "unknown"):
            for intent in ("progress", "append", "independent"):
                result = continuation(running_record()["tasks"][0], "codex", state, intent=intent,
                                      capabilities=("non_interrupting_message", "idle_followup"))
                self.assertEqual("blocked", result["action"])
        for patch, host in (({"agent_retired": True}, "codex"), ({}, "claude"),
                            ({"state": "BUILD_VERIFIED"}, "codex"), ({"agent_ref": None}, "codex")):
            task = running_record()["tasks"][0]
            task.update(patch)
            result = continuation(task, host, "running", intent="append", capabilities=("non_interrupting_message",))
            self.assertEqual("blocked", result["action"])

    def test_old_api_and_explicit_input_validation(self):
        task = running_record()["tasks"][0]
        for state, action in (("running", "wait"), ("idle", "followup")):
            result = continuation(task, "codex", state)
            self.assertEqual(action, result["action"])
            self.assertNotIn("intent", result)
        for options in ({"intent": "stop"}, {"intent": "append", "capabilities": ("unknown",)},
                        {"intent": "append", "capabilities": ("idle_followup", "idle_followup")},
                        {"capabilities": ("idle_followup",)}, {"intent": "append", "capabilities": "idle_followup"}):
            with self.subTest(options=options), self.assertRaises(TaskGraphError):
                continuation(task, "codex", "running", **options)


class ContinuationCliTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="continuation-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "record.json"
        self.source.write_text(json.dumps(running_record()), encoding="utf-8")
        self.command = [*PYTHON, str(PACK / "lib/agent_continuation_cli.py")]

    def invoke(self, *options, env=None):
        return subprocess.run([*self.command, "--input", str(self.source), "--task-id", "api", "--host", "codex",
                               "--observed-state", "running", *options], cwd=PACK, env=env,
                              capture_output=True, text=True, check=False, timeout=20)

    def test_source_graph_and_light_pack_are_read_only_and_reject_bad_identity(self):
        for single in (False, True):
            record = running_record()
            if single:
                from lib.task_graph_cli import export_task_pack
                record = export_task_pack(record, "api")
                record["task"]["workflow_level"] = "Light"
            self.source.write_text(json.dumps(record), encoding="utf-8")
            before = self.source.read_bytes()
            result = self.invoke("--intent", "append", "--capability", "non_interrupting_message")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("message", json.loads(result.stdout)["action"])
            self.assertEqual(before, self.source.read_bytes())
        record["task"]["context_policy"] = "fork"
        self.source.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(2, self.invoke().returncode)

    def test_rejects_unknown_capabilities_unsafe_files_and_invalid_records(self):
        self.assertEqual(2, self.invoke("--capability", "interrupt").returncode)
        self.assertEqual(2, self.invoke("--capability", "idle_followup", "--capability", "idle_followup").returncode)
        for body in (b"[]", b'{"schema_version":2,"schema_version":2}', b"x" * (4 * 1024 * 1024 + 1), b"\xff"):
            self.source.write_bytes(body)
            result = self.invoke()
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertFalse(result.stdout)
        target = self.root / "target.json"
        target.write_text(json.dumps(running_record()), encoding="utf-8")
        self.source.unlink()
        self.source.symlink_to(target)
        self.assertEqual(2, self.invoke().returncode)

    def test_installed_pinned_bridge_consumes_new_helper_and_rejects_pin_conflict(self):
        """真实导入当前候选、安装薄项目并执行查询；不调用宿主模型或真实HOME。"""
        project = self.root / "业务项目"
        project.mkdir()
        (project / "go.mod").write_text("module example.test/continuation\n", encoding="utf-8")
        home = self.root / "home"
        home.mkdir()
        state = self.root / "state"
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "CODEX_HOME": str(home / ".codex"),
               "CLAUDE_CONFIG_DIR": str(home / ".claude"), "GEMINI_CLI_HOME": str(home / ".gemini"),
               "AGENT_WORKFLOW_STATE_DIR": str(state)}
        installed = subprocess.run([*PYTHON, str(PACK / "lib/install/install_workflow.py"), str(project), "--state-dir", str(state)],
                                   cwd=PACK, env=env, text=True, capture_output=True, check=False, timeout=180)
        self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
        runtime = project / ".agent-workflow"
        binding = json.loads((runtime / "runtime.json").read_bytes())["runtime_binding"]
        record = running_record()
        record["runtime_binding"] = copy.deepcopy(binding)
        self.source.write_text(json.dumps(record), encoding="utf-8")
        before = self.source.read_bytes()
        launcher = ([sys.executable, "-I", "-B", "-X", "utf8"] if os.name == "nt" else
                    ["bash", str(runtime / "lib/python_runtime.sh"), "-B", "-X", "utf8"])
        pin_arguments = (["--binding-b64", base64.b64encode(json.dumps(binding).encode("utf-8")).decode("ascii")]
                         if os.name == "nt" else ["--binding", json.dumps(binding)])
        bridge = [*launcher, str(runtime / "runtime.py"), *pin_arguments, "helper", "lib/agent_continuation_cli.py"]
        options = ["--input", str(self.source), "--task-id", "api", "--host", "codex", "--observed-state", "running",
                   "--intent", "append", "--capability", "non_interrupting_message"]
        result = subprocess.run([*bridge, *options], cwd=project, env=env, text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("message", json.loads(result.stdout)["action"])
        self.assertEqual(before, self.source.read_bytes())
        # 当前pin固定读取该版本；伪造包pin不能被环境或latest静默覆盖。
        record["runtime_binding"]["content_id"] = "0" * 64
        record["runtime_binding"]["manifest_sha256"] = "0" * 64
        self.source.write_text(json.dumps(record), encoding="utf-8")
        rejected = subprocess.run([*bridge, *options], cwd=project, env=env, text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(2, rejected.returncode, rejected.stderr)
        # 用同一真实安装态消费已运输的准入CLI；领取/未知保留/明确未创建释放
        # 都写原夹具记录，不把这些机械结果当作原生创建证据。
        pending = graph()
        pending.update(runtime_binding=binding, active_paths=[], active_semantic_locks=[])
        self.source.write_text(json.dumps(pending), encoding="utf-8")
        manifest = self.root / "admission.json"
        data = {"schema_version": 1, "project_root": str(project),
                "records": [{"path": str(self.source), "sha256": "", "execution_roots": {"api": str(project)}}],
                "capacity": {"configured_subagents": 2, "configured_writers": 2, "host_available_subagents": 2}}

        def refresh_manifest():
            from lib.task_graph_records import digest
            data["records"][0]["sha256"] = digest(self.source.read_bytes())
            manifest.write_text(json.dumps(data), encoding="utf-8")

        admission = [*bridge[:-1], "lib/dispatch_admission_cli.py"]

        def admit(*arguments):
            completed = subprocess.run([*admission, *arguments, "--input", str(manifest)], cwd=project, env=env,
                                       text=True, capture_output=True, check=False, timeout=60)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            return json.loads(completed.stdout)

        refresh_manifest()
        self.assertEqual("api", admit("view")["candidates"][0]["task_id"])
        claim = admit("claim", "--record", str(self.source), "--request-id", "request-1", "--task-id", "api")
        self.assertEqual("claimed", claim["status"])
        receipt = self.root / "claim.json"
        receipt.write_text(json.dumps(claim), encoding="utf-8")
        refresh_manifest()
        self.assertEqual("retained", admit("release", "--receipt", str(receipt), "--outcome", "unknown")["status"])
        self.assertEqual("released", admit("release", "--receipt", str(receipt), "--outcome", "definitely_not_created")["status"])
        print("INSTALLED_CONTINUATION: actual current-source import/install/bridge action=message; mismatched pack pin rejected; native runtime unverified", flush=True)
        print("INSTALLED_ADMISSION: actual same-pin bridge view/claim/unknown-retain/definite-release; no native worker created", flush=True)


if __name__ == "__main__":
    unittest.main()
