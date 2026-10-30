"""原生安装升级边界回归：只在隔离临时项目中构造旧产物和用户碰撞。"""

from __future__ import annotations

import subprocess
import unittest

from tests.test_antigravity_workflow import AntigravityFixtureMixin


class AntigravityUpgradeBoundaryTest(AntigravityFixtureMixin, unittest.TestCase):
    def test_native_claude_shared_entry_overflow_is_rejected_before_publication(self) -> None:
        # 根据当前精简模板构造临界用户内容，而不是把旧入口体积固化成测试条件。
        # 全部模板加上受管标记会超出 Codex 默认保护值，最后一端安装前必须拒绝。
        template_bytes = sum((self.pack / relative).stat().st_size for relative in (
            "platforms/shared/AGENTS.product.tpl", "platforms/codex/AGENTS.codex.tpl",
            "platforms/claude/AGENTS.claude.tpl", "platforms/antigravity/AGENTS.antigravity.tpl",
        ))
        agents = self.project / "AGENTS.md"
        agents.write_bytes(b"# Project instructions\n" + b"u" * (32768 - template_bytes) + b"\n")
        before = self.project_tree_snapshot()
        for arguments in (("--preflight",), ()):
            result = self.invoke_all(*arguments)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("32 KiB", result.stdout + result.stderr)
            self.assertEqual(before, self.project_tree_snapshot())
        for host in ("claude", "codex"):
            result = subprocess.run(
                ["bash", f"agent_workflow/setup_{host}.sh"], cwd=self.project,
                text=True, capture_output=True, check=False, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLessEqual(len(agents.read_bytes()), 32768)
        before = self.project_tree_snapshot()
        for arguments in (("--preflight",), ()):
            result = self.invoke_setup(*arguments)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("32 KiB", result.stdout + result.stderr)
            self.assertEqual(before, self.project_tree_snapshot())

    def invoke_all(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """走真实聚合入口，以证明 Antigravity 失败不会晚于其他宿主写入。"""
        return subprocess.run(
            ["bash", "agent_workflow/setup_all.sh", *arguments],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )

    def test_old_managed_qa_missing_new_phrase_is_upgraded_not_executed(self) -> None:
        self.run_setup()
        qa = self.project / ".agents/agents/xy-qa.md"
        current = qa.read_text(encoding="utf-8")
        # 旧版本仍具备完整的受限工具策略和 PM 回传边界，只缺后来新增的正文短语。
        # 升级必须接管并替换它，但 --check 不应把旧业务语义认定为当前合格产物。
        self.assertIn("rendered frame ephemerally in memory", current)
        qa.write_text(
            current.replace("rendered frame ephemerally in memory", "rendered inspection"),
            encoding="utf-8",
        )
        before = self.project_tree_snapshot()
        checked = self.invoke_setup("--check")
        self.assertNotEqual(checked.returncode, 0)
        self.assertEqual(before, self.project_tree_snapshot())

        self.run_setup("--preflight")
        self.assertEqual(before, self.project_tree_snapshot())
        self.run_setup()
        self.assertEqual(current, qa.read_text(encoding="utf-8"))
        self.run_setup("--check")

    def test_empty_native_directories_are_safe_to_initialize(self) -> None:
        (self.project / ".agents/agents").mkdir(parents=True)
        (self.project / ".agents/skills").mkdir()
        before = self.project_tree_snapshot()
        result = self.invoke_all("--preflight")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, self.project_tree_snapshot())
        result = self.invoke_all()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.run_setup("--check")

    def test_upgrade_ownership_still_rejects_qa_write_authority(self) -> None:
        self.run_setup()
        qa = self.project / ".agents/agents/xy-qa.md"
        body = qa.read_text(encoding="utf-8")
        # 缺少新版正文不是拒绝升级的理由，但 QA 工具越权仍必须在旧归属分支被拒绝。
        qa.write_text(
            body.replace("rendered frame ephemerally in memory", "rendered inspection")
            .replace("tools:\n", "tools:\n  - write_to_file\n", 1),
            encoding="utf-8",
        )
        before = self.project_tree_snapshot()
        result = self.invoke_setup("--preflight")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("tools must exactly match approved policy", result.stderr)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_marker_and_frontmatter_without_execution_contract_do_not_prove_ownership(self) -> None:
        self.run_setup()
        qa = self.project / ".agents/agents/xy-qa.md"
        body = qa.read_text(encoding="utf-8")
        marker = "<!-- agent-workflow-pack:managed-antigravity-agent -->"
        # 保留合法 frontmatter 与 marker 也不能把任意用户正文当成工作流产物覆盖。
        qa.write_text(
            body.split(marker, 1)[0] + marker + "\nUser-owned reviewer body.\n",
            encoding="utf-8",
        )
        before = self.project_tree_snapshot()
        result = self.invoke_setup("--preflight")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Antigravity execution contract", result.stderr)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_upgrade_ownership_retains_qa_no_edit_and_no_command_boundaries(self) -> None:
        self.run_setup()
        qa = self.project / ".agents/agents/xy-qa.md"
        body = qa.read_text(encoding="utf-8")
        for required_boundary in (
            "Do not edit production business code",
            "Do not command implementers",
        ):
            with self.subTest(boundary=required_boundary):
                self.assertIn(required_boundary, body)
                # 旧正文的新视觉细节可以缺失，但稳定的只读和不可指挥执行者边界不能删除。
                qa.write_text(body.replace(required_boundary, "Removed boundary"), encoding="utf-8")
                before = self.project_tree_snapshot()
                result = self.invoke_setup("--preflight")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(required_boundary, result.stderr)
                self.assertEqual(before, self.project_tree_snapshot())

    def test_empty_agent_directory_beside_managed_skills_can_be_reinstalled(self) -> None:
        self.run_setup()
        # 模拟仅移除了旧原生 Agent 文件，保留 Codex 也会使用的受管 Skill 目录。
        for agent in (self.project / ".agents/agents").iterdir():
            agent.unlink()
        before = self.project_tree_snapshot()
        self.run_setup("--preflight")
        self.assertEqual(before, self.project_tree_snapshot())
        self.run_setup()
        self.run_setup("--check")

    def test_aggregate_preflight_rejects_user_agent_without_any_project_write(self) -> None:
        self.run_setup()
        user_agent = self.project / ".agents/agents/user-reviewer.md"
        user_agent.write_text("User-owned reviewer; do not replace.\n", encoding="utf-8")
        before = self.project_tree_snapshot()
        for arguments in (("--preflight",), ()):
            with self.subTest(arguments=arguments):
                result = self.invoke_all(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("[ERROR]", result.stdout + result.stderr)
                self.assertEqual(before, self.project_tree_snapshot())

    def test_aggregate_preflight_rejects_extra_user_skill_without_any_project_write(self) -> None:
        self.run_setup()
        user_skill = self.project / ".agents/skills/user-notes/SKILL.md"
        user_skill.parent.mkdir()
        user_skill.write_text("User-owned Skill; do not replace.\n", encoding="utf-8")
        before = self.project_tree_snapshot()
        for arguments in (("--preflight",), ()):
            with self.subTest(arguments=arguments):
                result = self.invoke_all(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("[ERROR]", result.stdout + result.stderr)
                self.assertEqual(before, self.project_tree_snapshot())


if __name__ == "__main__":
    unittest.main()
