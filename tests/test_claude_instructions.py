"""验证共享正文与 Claude 薄入口；静态产物测试不代表宿主会话已经加载。"""

from pathlib import Path
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from lib import claude_instructions as entry


class ClaudeInstructionsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="claude-native-entry-")
        self.addCleanup(self.temporary.cleanup)
        # 与 CLI 一样规范化系统 /var -> /private/var 别名，再校验项目内危险链接。
        self.root = Path(self.temporary.name).resolve() / "project"
        self.pack = self.root / "agent_workflow"
        self.template = self.pack / "platforms/claude/AGENTS.claude.tpl"
        self.template.parent.mkdir(parents=True)
        self.template.write_bytes(b"# Claude Code\nOnly applies in Claude Code.\n")
        self.shared_template = self.pack / "platforms/shared/AGENTS.product.tpl"
        self.shared_template.parent.mkdir(parents=True)
        self.shared_template.write_bytes(b"# Shared workflow\nTrivial checks stay local.\n")
        self.agents = self.root / "AGENTS.md"
        self.claude = self.root / "CLAUDE.md"
        self.legacy = f"{entry.BEGIN}\n# Old workflow\n{entry.END}\n".encode()

    def run_entry(self, action="apply"):
        entry.process(self.pack, self.root, action)

    def test_fresh_install_uses_thin_import_and_is_idempotent(self):
        self.run_entry("preflight")
        self.assertFalse(self.agents.exists())
        self.assertFalse((self.root / ".claude").exists())
        self.run_entry()
        expected = self.agents.read_bytes()
        self.assertEqual(self.claude.read_bytes(), b"@AGENTS.md\n")
        self.assertNotIn(b"@AGENTS.md", expected)
        self.run_entry()
        self.run_entry("check")
        self.assertEqual(self.agents.read_bytes(), expected)
        self.assertEqual(self.claude.read_bytes(), b"@AGENTS.md\n")
        self.assertFalse((self.root / ".claude").exists())

    def test_old_managed_claude_body_is_rejected_without_migration_or_backup(self):
        self.claude.write_bytes(self.legacy)
        self.claude.chmod(0o640)
        for action in ("preflight", "preflight-all", "apply", "check"):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "unsupported"):
                self.run_entry(action)
        self.assertEqual(self.claude.read_bytes(), self.legacy)
        self.assertFalse(self.agents.exists())
        self.assertEqual(stat.S_IMODE(self.claude.stat().st_mode), 0o640)
        self.assertFalse((self.root / ".claude").exists())

    def test_user_claude_content_blocks_before_writes(self):
        # 纯用户文件、混合文件、伪导入和未证明所有权的空文件都不能擅自覆盖。
        for body in (b"user instructions\n", b"user\n" + self.legacy, self.legacy + b"user\n", b"",
                     b"@AGENTS.md\nuser\n", b"Read AGENTS.md\n", b"`@AGENTS.md`\n",
                     b"```\n@AGENTS.md\n```\n", b"@other/AGENTS.md\n"):
            with self.subTest(body=body):
                self.claude.write_bytes(body)
                for action in ("preflight", "apply", "check"):
                    with self.assertRaisesRegex(ValueError, "user-owned"):
                        self.run_entry(action)
                self.assertEqual(self.claude.read_bytes(), body)
                self.assertFalse(self.agents.exists())
                self.assertFalse((self.root / ".claude").exists())

    def test_preserves_unicode_user_bytes_other_hosts_and_permissions(self):
        prefix = "项目中文规则\r\n<!-- pack:codex-begin -->\nCodex only\n<!-- pack:codex-end -->\n".encode()
        suffix = "\n用户尾部，无末尾换行".encode()
        self.agents.write_bytes(prefix + self.legacy + suffix)
        self.agents.chmod(0o640)
        self.run_entry()
        actual = self.agents.read_bytes()
        self.assertTrue(actual.startswith(prefix))
        self.assertTrue(actual.endswith(suffix))
        self.assertEqual(stat.S_IMODE(self.agents.stat().st_mode), 0o640)
        self.run_entry("check")

    def test_malformed_and_cross_host_nested_blocks_fail_without_writes(self):
        for body in (
            entry.BEGIN.encode(),
            (entry.END + "\n" + entry.BEGIN + "\n").encode(),
            self.legacy * 2,
            b"prefix " + self.legacy,
            self.legacy.replace(b"# Old workflow", b"<!-- pack:codex-begin -->") + b"<!-- pack:codex-end -->\n",
        ):
            with self.subTest(body=body):
                self.agents.write_bytes(body)
                with self.assertRaises(ValueError):
                    self.run_entry()
                self.assertEqual(self.agents.read_bytes(), body)
                self.assertFalse(self.claude.exists())

    def test_rejects_links_and_special_files_without_touching_outside(self):
        outside = Path(self.temporary.name) / "external"
        outside.write_bytes(b"outside user bytes\n")
        for target in (self.agents, self.claude):
            for kind in ("symlink", "hardlink", "fifo", "directory"):
                with self.subTest(target=target.name, kind=kind):
                    if kind == "symlink":
                        target.symlink_to(outside)
                    elif kind == "hardlink":
                        os.link(outside, target)
                    elif kind == "fifo":
                        os.mkfifo(target)
                    else:
                        target.mkdir()
                    with self.assertRaises(ValueError):
                        self.run_entry("preflight")
                    self.assertEqual(outside.read_bytes(), b"outside user bytes\n")
                    target.rmdir() if kind == "directory" else target.unlink()

    def test_missing_or_injected_shared_template_fails_before_publishing(self):
        self.shared_template.unlink()
        with self.assertRaisesRegex(ValueError, "missing instruction template"):
            self.run_entry("preflight")
        self.shared_template.write_bytes(self.legacy)
        with self.assertRaisesRegex(ValueError, "marker injection"):
            self.run_entry()
        self.assertFalse(self.agents.exists())
        self.assertFalse(self.claude.exists())

    def test_failed_thin_entry_publication_rolls_back_agents(self):
        self.agents.write_bytes(b"existing user instructions\n")
        real_write = entry.atomic_write

        def fail_publication(path, data, mode):
            if path == self.claude and data == b"@AGENTS.md\n":
                raise OSError("simulated failed publication")
            real_write(path, data, mode)

        with patch.object(entry, "atomic_write", side_effect=fail_publication):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.run_entry()
        self.assertEqual(self.agents.read_bytes(), b"existing user instructions\n")
        self.assertFalse(self.claude.exists())
        self.assertFalse((self.root / ".claude").exists())

    def test_check_rejects_drift_or_unsupported_claude_entry(self):
        self.run_entry()
        self.claude.write_bytes(self.legacy)
        with self.assertRaises(ValueError):
            self.run_entry("check")
        self.claude.unlink()
        # 共享正文正确但薄入口缺失，也必须拒绝通过只读检查。
        with self.assertRaises(ValueError):
            self.run_entry("check")
        self.claude.write_bytes(b"@AGENTS.md\n")
        self.agents.write_bytes(self.agents.read_bytes().replace(b"Only applies", b"Changed"))
        with self.assertRaises(ValueError):
            self.run_entry("check")

    def test_native_host_settings_are_never_modified(self):
        settings = self.root / ".claude/settings.json"
        settings.parent.mkdir()
        original = b'{"disableAllHooks":true,"custom":"user-owned"}\n'
        settings.write_bytes(original)
        local = self.root / "CLAUDE.local.md"
        local.write_bytes(b"user local instructions\n")
        self.run_entry()
        self.assertEqual(settings.read_bytes(), original)
        self.assertEqual(local.read_bytes(), b"user local instructions\n")
        self.assertEqual(self.claude.read_bytes(), b"@AGENTS.md\n")

    def test_native_only_install_gains_import_without_changing_existing_rules(self):
        """已安装的共享正文保持原字节，只补入口，不产生无意义备份。"""
        self.run_entry()
        self.claude.unlink()
        original = self.agents.read_bytes()
        self.run_entry()
        self.run_entry("check")
        self.assertEqual(self.agents.read_bytes(), original)
        self.assertEqual(self.claude.read_bytes(), b"@AGENTS.md\n")
        self.assertFalse((self.root / ".claude/workflow-backups").exists())

    def test_existing_exact_import_is_preserved_without_backup(self):
        self.claude.write_bytes(b"@AGENTS.md\n")
        self.claude.chmod(0o600)
        self.run_entry()
        self.run_entry("check")
        self.assertEqual(self.claude.read_bytes(), b"@AGENTS.md\n")
        self.assertEqual(stat.S_IMODE(self.claude.stat().st_mode), 0o600)
        self.assertFalse((self.root / ".claude/workflow-backups").exists())

    def test_failed_first_entry_publication_removes_only_new_agents_file(self):
        """第二个入口发布失败时，撤回本轮新建正文，不能留下半套安装。"""
        real_write = entry.atomic_write

        def fail_publication(path, data, mode):
            if path == self.claude:
                raise OSError("simulated first publication failure")
            real_write(path, data, mode)

        with patch.object(entry, "atomic_write", side_effect=fail_publication):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.run_entry()
        self.assertFalse(self.agents.exists())
        self.assertFalse(self.claude.exists())

    def test_template_marker_injection_is_rejected(self):
        self.template.write_bytes(self.legacy)
        with self.assertRaisesRegex(ValueError, "marker injection"):
            self.run_entry("preflight")
        self.assertFalse(self.agents.exists())

    def test_aggregate_preview_checks_final_entry_without_writing(self):
        # 各宿主单独合成尚未超限，但最终组合会超过已有 Codex 入口保护值。
        for host, relative in (("product", "shared/AGENTS.product.tpl"),
                               ("codex", "codex/AGENTS.codex.tpl"),
                               ("antigravity", "antigravity/AGENTS.antigravity.tpl")):
            target = self.pack / "platforms" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(host.encode() + b"\n" + b"x" * 8000 + b"\n")
        user = b"# User instructions\n" + b"u" * 10000 + b"\n"
        self.agents.write_bytes(user)
        self.run_entry("preflight")
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            self.run_entry("preflight-all")
        self.assertEqual(self.agents.read_bytes(), user)
        self.assertFalse((self.root / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
