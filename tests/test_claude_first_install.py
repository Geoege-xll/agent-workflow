"""隔离 Claude 安装管理接口，在临时用户目录核验来源同意、安装范围和失败恢复。"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import install_claude as installer


class ClaudeFirstInstallTest(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(root)
        self.config = self.root / "user config"
        self.config.mkdir()
        self.settings = self.config / "settings.json"
        self.enterContext(patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.config)}))
        self.markets = []
        self.plugins = []
        self.mutations = []
        self.enterContext(patch.object(installer, "claude", side_effect=self.official))
        self.enterContext(patch("sys.stdin.isatty", return_value=True))

    def official(self, cwd, *args, listing=False):
        # 模拟仅官方管理命令产生的结果。调用路径始终与被调用项目及它的覆盖设置隔离。
        self.assertFalse(any(Path(cwd).iterdir()))
        if args == ("marketplace", "list", "--json") and listing:
            return self.markets
        if args == ("list", "--json") and listing:
            return self.plugins
        self.mutations.append(args)
        if args == ("marketplace", "add", installer.URL + "#" + installer.REF, "--scope", "user"):
            self.markets.append({"name": installer.MARKET, "source": "git",
                                 "url": installer.URL, "ref": installer.REF})
        elif args == ("install", installer.PLUGIN, "--scope", "user"):
            self.plugins.append({"id": installer.PLUGIN, "enabled": True, "scope": "user"})
        else:
            self.fail(args)

    def run_install(self, *args, answer=None):
        # 未预期的重复提示令用例直接失败。可调用回答用来模拟用户确认期间另一个设置编辑器保存。
        prompt = answer if callable(answer) else lambda _: self.fail("意外提示") if answer is None else answer
        with patch("sys.argv", ["install_claude.py", *args]), patch("builtins.input", side_effect=prompt):
            with redirect_stdout(io.StringIO()) as output:
                installer.main()
        return output.getvalue()

    def test_first_install_then_second_project_without_reprompt(self):
        for name in ("project-a", "project-b"):
            project = self.root / name
            project.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(project)
                self.run_install(answer="yes" if name == "project-a" else None)
            finally:
                os.chdir(previous)
            self.assertEqual([], list(project.iterdir()))
        self.assertEqual(2, len(self.mutations))
        self.assertEqual({"autoMode": {"environment": ["$defaults", installer.SOURCE]}},
                         json.loads(self.settings.read_text()))

    def test_decline_then_no_prompt_until_explicit_configuration(self):
        original = b'{"theme":"dark", "autoMode":{"environment":[], "allow":["private rule"]}}'
        self.settings.write_bytes(original)
        self.run_install(answer="")
        self.run_install()
        self.assertEqual(original, self.settings.read_bytes())

        def consent(_):
            value = json.loads(original)
            value["newPreference"] = True
            self.settings.write_text(json.dumps(value))
            return "yes"

        self.run_install("--configure-source", answer=consent)
        value = json.loads(self.settings.read_bytes())
        self.assertEqual(["private rule"], value["autoMode"]["allow"])
        self.assertEqual([installer.SOURCE], value["autoMode"]["environment"])
        self.assertTrue(value["newPreference"])
        self.assertEqual("dark", value["theme"])
        self.assertEqual(2, len(self.mutations))

    def test_existing_exact_english_and_chinese_are_preserved(self):
        for source in (installer.SOURCE, installer.PREVIOUS_SOURCE):
            with self.subTest(source=source[:12]):
                original = json.dumps({"autoMode": {"environment": ["custom", "$defaults", source]}})
                self.settings.write_text(original)
                self.run_install("--configure-source")
                self.assertEqual(original, self.settings.read_text())
        # 独立分发的脚本不能依赖其它文件；这里核对安装提示与项目维护的中文手动配置内容同步。
        guide = Path(__file__).resolve().parents[1] / "platforms/claude/references/pm-integration.md"
        self.assertIn(json.dumps(installer.SOURCE, ensure_ascii=False), guide.read_text())

    def test_conflicting_market_and_disabled_plugin_fail_closed(self):
        for url, ref in ((installer.URL, "other-branch"), ("https://example.invalid/other.git", installer.REF)):
            with self.subTest(url=url, ref=ref):
                self.markets[:] = [{"name": installer.MARKET, "source": "git", "url": url, "ref": ref}]
                with self.assertRaisesRegex(ValueError, "同名市场"):
                    self.run_install()
                self.assertFalse(self.mutations)
        self.markets.clear()
        self.run_install(answer="")
        self.plugins[0]["enabled"] = False
        with self.assertRaisesRegex(ValueError, "停用"):
            self.run_install("--configure-source")
        self.assertFalse(self.settings.exists())
        self.assertEqual(2, len(self.mutations))

    def test_declaration_conflict_and_invalid_files_preserve_original(self):
        for original in (b'{"extraKnownMarketplaces":{"xy-workflow":{"source":{"source":"directory"}}}}',
                         b'{"autoMode":null}', b'{"a":1,"a":2}', b'invalid'):
            with self.subTest(original=original):
                self.settings.write_bytes(original)
                with self.assertRaises(ValueError):
                    self.run_install()
                self.assertEqual(original, self.settings.read_bytes())
                self.assertFalse(self.mutations)

    def test_concurrent_settings_write_is_not_lost(self):
        self.settings.write_text('{"theme":"dark"}')
        sync = os.fsync

        def concurrent_save(fd):
            sync(fd)
            self.settings.write_text('{"theme":"light"}')

        with patch.object(os, "fsync", side_effect=concurrent_save):
            with self.assertRaisesRegex(ValueError, "发生变化"):
                self.run_install(answer="yes")
        self.assertEqual('{"theme":"light"}', self.settings.read_text())
        self.assertEqual([self.settings], list(self.config.iterdir()))

    def test_editor_replaces_settings_at_final_exchange(self):
        self.settings.write_text('{"theme":"dark"}')
        exchange = installer.exchange_files
        calls = []

        def edit_just_before_exchange(staged, target):
            # 第一次系统调用前替换 inode，恰好落在最后一次快照比对之后。在回换前再
            # 保存一次，证明即使又一个编辑器介入，双方写入的字节也都有可定位的文件。
            editor = self.root / "editor-save"
            next_value = b'{"theme":"light"}' if not calls else b'{"fontSize":21}'
            editor.write_bytes(next_value)
            os.replace(editor, target)
            calls.append(staged)
            exchange(staged, target)

        with patch.object(installer, "exchange_files", side_effect=edit_just_before_exchange):
            with self.assertRaisesRegex(ValueError, "发布瞬间发生变化") as conflict:
                self.run_install(answer="yes")
        self.assertEqual(2, len(calls))
        self.assertEqual(b'{"theme":"light"}', self.settings.read_bytes())
        self.assertEqual(b'{"fontSize":21}', calls[0].read_bytes())
        self.assertIn(str(calls[0]), str(conflict.exception))

    def test_market_declaration_changed_while_prompt_open(self):
        conflicting = b'{"extraKnownMarketplaces":{"xy-workflow":{"source":{"source":"directory"}}}}'

        def change_declaration(_):
            self.settings.write_bytes(conflicting)
            # CLI 的模拟列表保留安装时的正确地址，只有重新检查磁盘快照才能发现来源已经变更。
            return "yes"

        with self.assertRaisesRegex(ValueError, "声明不同来源"):
            self.run_install(answer=change_declaration)
        self.assertEqual(conflicting, self.settings.read_bytes())
        self.assertEqual([self.settings], list(self.config.iterdir()))

    def test_piped_input_leaves_consent_to_the_user(self):
        with patch("sys.stdin.isatty", return_value=False):
            self.run_install()
        self.assertEqual(2, len(self.mutations))
        self.assertFalse(self.settings.exists())
