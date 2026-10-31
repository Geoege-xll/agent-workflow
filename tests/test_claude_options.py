"""Claude 可选能力的边界反例；不调用模型、不读取真实用户设置。"""

import unittest

from lib.claude_options import parse, frontmatter_window
from lib.role_models import patch_artifact


class ClaudeOptionsTest(unittest.TestCase):
    def test_missing_options_inherit_and_model_edits_preserve_native_window(self):
        self.assertEqual({}, parse("project_name: test\n")["auto_compact_windows"])
        self.assertEqual("inherit", parse("")["block_writes_outside_working_directories"])
        # 模型事务的写域仍只有 model/effort，不能重建 frontmatter 丢掉上下文窗口。
        raw = b'---\nname: xy-qa\nmodel: inherit\nautoCompactWindow: 200000\ntools: Read\n---\n<!-- agent-workflow-pack:managed-agent -->\nBODY\n'
        updated = patch_artifact(raw, "claude", {"model": "opus", "effort": "high"})
        self.assertEqual(200000, frontmatter_window(updated))
        self.assertTrue(updated.endswith(b"<!-- agent-workflow-pack:managed-agent -->\nBODY\n"))
        self.assertIn(b"tools: Read\n", updated)

    def test_strict_options_reject_lossy_values_duplicates_and_permission_weakening(self):
        entries = [
            'auto_compact_windows: {"xy-qa": 99999}',
            'auto_compact_windows: {"xy-qa": 1000001}',
            'auto_compact_windows: {"xy-qa": true}',
            'auto_compact_windows: {"xy-qa": 200000.0}',
            'auto_compact_windows: {"xy-qa": "200k"}',
            'auto_compact_windows: {"xy-qa": 200000, "xy-qa": 300000}',
            'auto_compact_windows: {"other": 200000}',
            'auto_compact_windows: []',
            'block_writes_outside_working_directories: false',
            'block_writes_outside_working_directories: true\n  block_writes_outside_working_directories: inherit',
            'unknown: true',
        ]
        for entry in entries:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                parse("claude_options:\n  " + entry + "\n")
        for text in ("claude_options: []", "claude_options:\nclaude_options:\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse(text)
        for value in (100000, 1000000):
            self.assertEqual(value, parse('claude_options:\n  auto_compact_windows: {"xy-qa": %d}\n' % value)["auto_compact_windows"]["xy-qa"])

    def test_native_window_rejects_invalid_or_duplicate_frontmatter_and_ignores_body(self):
        for field in ('200k', '99999', '1000001', 'true', '\n200000', '200000\nautoCompactWindow: 300000'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                frontmatter_window(('---\nname: xy-qa\nautoCompactWindow: ' + field + '\n---\n').encode())
        self.assertIsNone(frontmatter_window(b'---\nname: xy-qa\n---\nautoCompactWindow: 200000\n'))
        self.assertEqual(200000, frontmatter_window(b'---\r\nname: xy-qa\r\nautoCompactWindow: 200000\r\n---\r\n'))
