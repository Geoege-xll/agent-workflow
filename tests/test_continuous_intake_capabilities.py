"""诊断证据分层回归：文档、版本、实际工具和会话验收不得互相替代。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from manager.capabilities import diagnose


PACK = Path(__file__).resolve().parents[1]


class ContinuousIntakeCapabilitiesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="intake-diagnostics-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()

    def test_documented_client_controls_never_grant_actual_messaging_or_runtime_proof(self):
        for host in ("codex", "claude", "antigravity"):
            with self.subTest(host=host), patch("manager.capabilities.subprocess.run", side_effect=AssertionError("不启动宿主")):
                result = diagnose(host, home=self.home, environment={})
            intake = result["continuous_intake"]
            self.assertEqual("not_inspected", intake["current_tool_surface"])
            self.assertEqual({"non_interrupting_message": None, "idle_followup": None}, intake["observed_capabilities"])
            self.assertEqual({"message_delivery", "wait_wakeup", "original_task_continuity", "same_agent_followup", "parent_final_lifecycle"},
                             {row["name"] for row in intake["runtime_checks"]})
            for check in intake["runtime_checks"]:
                self.assertEqual("runtime_unverified", check["status"])
                self.assertFalse(check["runtime_verified"])
                self.assertIsNone(check["evidence_ref"])
            features = {row["name"]: row for row in result["documented_capabilities"]}
            if host == "codex":
                self.assertEqual("Enter / Tab", features["cli_mid_turn_input"]["interface"])
                self.assertIn("chatgpt.followUpQueueMode", features["app_followup_behavior"]["boundary"])
                self.assertIn("expectedTurnId", features["app_server_steer"]["boundary"])
            elif host == "antigravity":
                self.assertIn("interrupt", features["running_parent_message"]["boundary"])
            self.assertTrue(all(not row["runtime_verified"] for row in features.values()))
        self.assertEqual([], list(self.home.iterdir()))

    def test_observed_version_and_missing_path_keep_all_runtime_cases_unverified(self):
        version = subprocess.CompletedProcess(["codex", "--version"], 0, "codex-cli 0.167.0\n", "")
        with patch("manager.capabilities.shutil.which", return_value="/fixture/codex"), \
                patch("manager.capabilities.subprocess.run", return_value=version):
            observed = diagnose("codex", home=self.home, environment={}, probe=True)
        self.assertEqual("source_observed", observed["client"]["evidence_level"])
        self.assertTrue(all(row["status"] == "runtime_unverified" for row in observed["continuous_intake"]["runtime_checks"]))
        with patch("manager.capabilities.shutil.which", return_value=None):
            missing = diagnose("antigravity", home=self.home, environment={}, probe=True)
        self.assertEqual("not_found", missing["client"]["status"])
        self.assertIn("PATH", missing["continuous_intake"]["client_not_found_scope"])
        self.assertFalse(missing["runtime_verified"])

    def test_actual_doctor_cli_emits_new_diagnostics_without_changing_isolated_home(self):
        """实际管理入口加载新字段；版本探测留给获授权的目标客户端，不代替五项验收。"""
        env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), "CODEX_HOME": str(self.home / ".codex"),
               "CLAUDE_CONFIG_DIR": str(self.home / ".claude"), "GEMINI_CLI_HOME": str(self.home / ".gemini"),
               "AGENT_WORKFLOW_STATE_DIR": str(self.home / "state")}
        # 此基线公开管理入口为 workflow.sh，由它选择实际解释器并进入 manager.cli。
        completed = subprocess.run(["bash", str(PACK / "workflow.sh"), "--host-home", str(self.home), "doctor", "--platform", "codex"],
                                   cwd=PACK, env=env, text=True, capture_output=True, check=False, timeout=20)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        # 管理入口返回宿主数组；验证真实公开结构而不是模拟输出。
        selected = result[0]
        self.assertEqual("not_probed", selected["client"]["status"])
        self.assertEqual(5, len(selected["continuous_intake"]["runtime_checks"]))
        self.assertEqual([], list(self.home.iterdir()))


if __name__ == "__main__":
    unittest.main()
