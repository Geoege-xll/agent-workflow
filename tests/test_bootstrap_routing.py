"""验证目录入口的安全引用与真实安装，不把文本校验冒充模型执行效果。"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from lib.business_confirmation_policy import read_instruction_contract
from lib.skill_contracts import BOOTSTRAP_TARGETS, expand_bootstrap_contract
from tests.test_unified_host_workflow import HOSTS, UnifiedHostFixture


PACK = Path(__file__).resolve().parents[1]
TARGET = BOOTSTRAP_TARGETS["platforms/codex/AGENTS.codex.tpl"]


class BootstrapReferenceTest(unittest.TestCase):
    def entry(self, target: str = TARGET) -> str:
        return (f"仅 Codex 首次编排时读取 [宿主细则](.agent-workflow/{target})\n"
                f"<!-- bootstrap-contract: {target} -->\n")

    def test_machine_expands_contract_without_expanding_auxiliary_links(self):
        reader = Mock(return_value="审批与 QA 完整约束\n")
        body = self.entry() + "[辅助项目事实](docs/PROJECT.md)\n"
        result = expand_bootstrap_contract(body, reader, TARGET)
        reader.assert_called_once_with(TARGET)
        self.assertIn("审批与 QA 完整约束", result)
        self.assertIn("[辅助项目事实](docs/PROJECT.md)", result)

    def test_unknown_or_cross_host_reference_fails_before_read(self):
        # 不允许 URL、父目录、绝对路径或另一个宿主的契约作为当前宿主的正文。
        for target in ("../secret.md", "/tmp/secret.md", "https://example.test/rules.md",
                       BOOTSTRAP_TARGETS["platforms/claude/AGENTS.claude.tpl"]):
            with self.subTest(target=target):
                reader = Mock()
                with self.assertRaises(ValueError):
                    expand_bootstrap_contract(self.entry(target), reader, TARGET)
                reader.assert_not_called()

    def test_missing_duplicate_unlinked_empty_or_nested_contract_is_rejected(self):
        for body, detail in (("无路由", "规则"), (self.entry() * 2, "规则"),
                             (self.entry().splitlines()[1], "规则"),
                             (self.entry(), " \n"), (self.entry(), self.entry())):
            with self.subTest(body=body, detail=detail), self.assertRaises(ValueError):
                expand_bootstrap_contract(body, lambda _path: detail, TARGET)

    def test_every_source_entry_is_a_route_to_a_complete_contract(self):
        for relative in BOOTSTRAP_TARGETS:
            with self.subTest(relative=relative):
                entry = (PACK / relative).read_text(encoding="utf-8")
                contract = read_instruction_contract(PACK, relative)
                self.assertLess(len(entry.encode()), len(contract.encode()))
                # 普通链接不是 Claude 的全文 @ 导入，也不是 Antigravity 的全文 include。
                self.assertNotRegex(entry, r"(?m)^\s*@|@\[[^]]+\]\(")


class BootstrapInstallTest(UnifiedHostFixture, unittest.TestCase):
    def test_each_host_independent_install_contains_shared_bootstrap(self):
        # 逐个平台独立安装，确保共享规则不是聚合安装恰好补齐的隐含依赖。
        for host in HOSTS:
            with self.subTest(host=host):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                result = self.run_script(project, f"setup_{host}.sh")
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                entry = (project / "AGENTS.md").read_text(encoding="utf-8")
                self.assertIn("<!-- pack:product-begin -->", entry)
                self.assertIn((pack / "platforms/shared/AGENTS.product.tpl").read_text().strip(), entry)
                checked = self.run_script(project, f"setup_{host}.sh", "--check")
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_missing_detail_blocks_preflight_without_project_writes(self):
        for host in HOSTS:
            with self.subTest(host=host):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                # 只删除临时夹具中本次测试拥有的文件，不触及源包和实际项目。
                detail = pack / f"platforms/{host}/references/pm-integration.md"
                detail.unlink()
                before = {str(p.relative_to(project)): p.read_bytes()
                          for p in project.rglob("*") if p.is_file()}
                result = self.run_script(project, f"setup_{host}.sh", "--preflight")
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("pm-integration.md", result.stdout + result.stderr)
                after = {str(p.relative_to(project)): p.read_bytes()
                         for p in project.rglob("*") if p.is_file()}
                self.assertEqual(before, after)

    def test_detached_install_resolves_routes_preserves_user_rules_and_checks_all_hosts(self):
        with tempfile.TemporaryDirectory(prefix="workflow-bootstrap-routing-") as raw:
            project = Path(raw) / "项目 With Spaces"
            project.mkdir()
            user_rules = "# 用户规则\n\n中文沟通；不要改动业务代码。\n"
            (project / "AGENTS.md").write_text(user_rules, encoding="utf-8")
            sentinel = project / "business.txt"
            sentinel.write_bytes(b"user-owned business bytes\n")
            result = subprocess.run(["bash", str(PACK / "install.sh"), str(project)],
                                    text=True, capture_output=True, check=False, timeout=90)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            entry = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertTrue(entry.startswith(user_rules))
            self.assertEqual(b"@AGENTS.md\n", (project / "CLAUDE.md").read_bytes())
            self.assertEqual(b"user-owned business bytes\n", sentinel.read_bytes())
            targets = re.findall(r"\[[^]\n]+\]\((\.agent-workflow/[^)]+)\)", entry)
            self.assertEqual(4, len(targets))
            for target in targets:
                self.assertTrue((project / target).is_file(), target)
            # 入口不再常驻三平台完整细则，也不以机械行数/字节目标定义规范。
            detail_bytes = sum((project / ".agent-workflow" / target).stat().st_size
                               for relative, target in BOOTSTRAP_TARGETS.items()
                               if "/shared/" not in relative)
            self.assertLess(len(entry.encode()), detail_bytes)
            self.assertNotIn("installed-code-review-skill", entry)
            for host in HOSTS:
                checked = subprocess.run(
                    ["bash", str(project / ".agent-workflow" / f"setup_{host}.sh"), "--check"],
                    cwd=project, text=True, capture_output=True, check=False, timeout=90)
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
