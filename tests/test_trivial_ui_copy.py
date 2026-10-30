"""验证轻量文案规则的三端安装传播，以及完整任务图没有新增跳过门禁的后门。

这些确定性检查不宣称能证明模型正确理解每一句文案；语义分类另外通过独立
场景核查验证。这里仅验证真实安装产物与既有调度器的可观测行为。
"""

from __future__ import annotations

import unittest

from tests import test_design_standards_lifecycle as lifecycle
from tests.test_unified_host_workflow import UnifiedHostFixture


class TrivialUICopyContractTest(UnifiedHostFixture, unittest.TestCase):
    def test_all_host_entries_install_the_early_exit_and_keep_full_workflow(self):
        temporary, project, pack = self.install_all()
        self.addCleanup(temporary.cleanup)

        # 三个平台统一使用 AGENTS.md 正文，Claude 通过薄入口导入。用户真正加载
        # 的入口必须在完整 UI 路由之前看到轻量规则，而不是只改源包中的说明。
        self.assertEqual((project / "CLAUDE.md").read_bytes(), b"@AGENTS.md\n")
        for filename in ("AGENTS.md",):
            with self.subTest(entry=filename):
                body = (project / filename).read_text(encoding="utf-8")
                self.assertLess(body.index("Trivial UI copy"), body.index("UI-Conformance"))
                self.assertIn(".agent-workflow/product/WORKFLOW.md", body)
                self.assertIn("local checks", body)
                self.assertIn("Stricter project rules and requested review still apply", body)
                # 轻量入口保留早退出，完整校验程序可从明确路由找到，不再常驻全文。
                self.assertIn("implementation-and-qa.md", body)
                self.assertIn("qa_handoff_cli.py validate", (pack / "platforms/antigravity/references/pm-integration.md").read_text())
                self.assertIn("General Trivial early exit", body)

        # 所有相关 Skill 都必须完整同步；旧版 build/QA/memory 不能在收口时恢复
        # 强制 QA。按字节比较同时保护未改动的完整任务流程，防止宿主产生分叉。
        for skill in ("xy-workflow", "xy-build-verify", "xy-qa-review", "xy-project-memory"):
            source = (pack / "platforms/shared/skills" / skill / "SKILL.md").read_bytes()
            for root in (".agents/skills", ".claude/skills"):
                with self.subTest(skill=skill, root=root):
                    actual = (project / root / skill / "SKILL.md").read_bytes()
                    self.assertEqual(source, actual)
                    self.assertIn(b"Trivial UI copy", actual)

        # 主动要求的独立审查不能被旧接收合同拉回完整任务包；两端实际安装的
        # QA 指令都应携带专门的范围限定，而非只在 PM 入口声明例外。
        for root in (".agents/skills", ".claude/skills"):
            review = (project / root / "xy-qa-review/SKILL.md").read_text(encoding="utf-8")
            self.assertIn("For an explicitly requested Trivial UI copy review", review)
            self.assertIn("Do not require a formal Task Pack", review)
            self.assertIn("Then stop", review)

        checked = self.run_script(project, "setup_all.sh", "--check")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_scheduled_ui_cannot_self_declare_a_qa_or_approval_bypass(self):
        fixture = lifecycle.DesignStandardsLifecycleTest()
        for field, value in (("skip_qa", True), ("classification", "Trivial")):
            with self.subTest(field=field):
                payload = fixture.fixture(production=True)
                payload["tasks"][1][field] = value
                rejected = fixture.invoke(payload, "ready")
                self.assertEqual(2, rejected.returncode)
                self.assertIn("unsupported field", rejected.stderr)

        # 轻量分支不进入 DAG；一旦采用现有完整任务图，用户批准仍是实际门禁。
        payload = fixture.fixture(production=True)
        payload["approved_gates"] = []
        waiting = fixture.invoke(payload, "ready")
        self.assertEqual(0, waiting.returncode, waiting.stderr)
        self.assertIn('"ready": []', waiting.stdout)


if __name__ == "__main__":
    unittest.main()
