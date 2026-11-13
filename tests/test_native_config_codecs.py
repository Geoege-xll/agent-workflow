"""原生文件精确编辑：真实语法、复杂正文保留以及不支持格式拒绝。"""

from __future__ import annotations

import unittest

from native_config import activation_codecs, codecs


class NativeCodecsTest(unittest.TestCase):
    def test_activation_toml_preserves_comments_crlf_and_unrelated_plugin_settings(self):
        plugin = "agent-workflow@agent-workflow-alpha"
        raw = (b'# retain\r\nmodel="x"\r\n[plugins."agent-workflow@agent-workflow-alpha"]\r\n'
               b'enabled = true # retain explanation\r\nother = "unchanged"\r\n'
               b'[[unrelated]]\r\nname="preserve"\r\n')
        changed = activation_codecs.patch("codex", raw, plugin, "disabled")
        self.assertEqual(changed, raw.replace(b'enabled = true', b'enabled = false'))
        cleared = activation_codecs.patch("codex", raw, plugin, "inherit")
        self.assertEqual(cleared, raw.replace(b'enabled = true #', b'#'))
        self.assertEqual(activation_codecs.state("codex", cleared, plugin), "inherit")
        dotted = b'plugins."agent-workflow@agent-workflow-alpha".enabled = true\n'
        self.assertEqual(activation_codecs.patch("codex", dotted, plugin, "disabled"), dotted.replace(b'true', b'false'))
        with self.assertRaises(ValueError):
            activation_codecs.patch("codex", b'plugins = {"agent-workflow@agent-workflow-alpha"={enabled=true}}\n', plugin, "disabled")

    def test_activation_json_precise_edit_delete_and_insert_preserve_other_bytes(self):
        plugin = "agent-workflow@agent-workflow-alpha"
        for mapping in ('"other": false, "' + plugin + '": true', '"' + plugin + '": true, "other": false', '"' + plugin + '": true'):
            raw = ('{\r\n "enabledPlugins": {' + mapping + '},\r\n "permissions": {"allow":["Read(a,b)"]}\r\n}\r\n').encode()
            changed = activation_codecs.patch("claude", raw, plugin, "disabled")
            self.assertEqual(changed, raw.replace(('"' + plugin + '": true').encode(), ('"' + plugin + '": false').encode()))
            cleared = activation_codecs.patch("claude", raw, plugin, "inherit")
            self.assertEqual(activation_codecs.state("claude", cleared, plugin), "inherit")
            self.assertIn(b'"permissions": {"allow":["Read(a,b)"]}', cleared)
            self.assertNotIn(b'\n', cleared.replace(b'\r\n', b''))
        raw = b'{"extra": {"text": "enabledPlugins:{fake},"}}\n'
        inserted = activation_codecs.patch("claude", raw, plugin, "enabled")
        self.assertIn(b'"extra": {"text": "enabledPlugins:{fake},"}', inserted)
        self.assertEqual(activation_codecs.state("claude", inserted, plugin), "enabled")
        self.assertEqual(activation_codecs.state("claude", None, plugin), "inherit")
        for raw in (b'{"enabledPlugins": []}', b'{"enabledPlugins":{"agent-workflow@agent-workflow-alpha":"true"}}', b'{"x":1,"x":2}'):
            with self.assertRaises(ValueError):
                activation_codecs.patch("claude", raw, plugin, "enabled")

    def test_toml_adjacent_inline_comment_is_not_replaced_as_part_of_value(self):
        raw = b'name="a"\ndescription="x"\nmodel="old"#comment\ndeveloper_instructions="x"\n'
        updated = codecs.patch("codex", raw, {"model": "new"})
        self.assertEqual(updated, raw.replace(b'"old"', b'"new"'))
        cleared = codecs.patch("codex", raw, {"model": None})
        self.assertIn(b"#comment\n", cleared)

    def test_codex_multiline_body_fake_model_lines_crlf_and_nested_table_are_preserved(self):
        body = (b'# native comments\r\nname = "audit-scout"\r\ndescription = "Audit source"\r\n'
                b'model = "old-model"  # model explanation\r\nmodel_reasoning_effort = "high" # effort explanation\r\n'
                b'developer_instructions = """\r\nRead files.\r\nmodel = "fake-body-model"\r\n'
                b'model_reasoning_effort = "fake-body-effort"\r\n[features]\r\n"""\r\n'
                b'[features]\r\nshell_tool = false\r\nmodel = "unrelated-nested-value"\r\n')
        changed = codecs.patch("codex", body, {"model": "future/model", "effort": "ultra"})
        self.assertEqual(changed, body.replace(b'model = "old-model"', b'model = "future/model"')
                         .replace(b'model_reasoning_effort = "high"', b'model_reasoning_effort = "ultra"'))
        self.assertEqual(codecs.parse("codex", changed).fields, {"model": "future/model", "effort": "ultra"})
        self.assertNotIn(b"\n", changed.replace(b"\r\n", b""))

    def test_codex_literal_triple_quotes_and_quoted_keys_clear_only_real_fields(self):
        body = (b'name="personal-reader"\ndescription="Read source"\n"model" = "old" # retain\n'
                b"developer_instructions = '''\nmodel = 'fake'\n'''\n")
        changed = codecs.patch("codex", body, {"model": None, "effort": "medium"})
        self.assertIn(b"# retain\n", changed)
        self.assertIn(b"model = 'fake'", changed)
        self.assertEqual(codecs.parse("codex", changed).fields, {"effort": "medium"})

    def test_codex_adds_root_fields_before_table_and_preserves_no_final_newline(self):
        body = b'name="data-researcher"\ndescription="Research"\ndeveloper_instructions="read"\n[features]\nshell_tool=false'
        changed = codecs.patch("codex", body, {"model": "custom", "effort": "ultra"})
        self.assertTrue(changed.endswith(b"[features]\nshell_tool=false"))
        self.assertLess(changed.index(b'model = "custom"'), changed.index(b"[features]"))

    def test_claude_frontmatter_block_description_body_and_inline_comments_survive(self):
        body = (b'---\r\nname: semantic-auditor\r\ndescription: >-\r\n  Reviews source and catches defects.\r\n'
                b'  model: fake-description\r\ntools:\r\n  - Read\r\n  - Grep\r\n'
                b'model: sonnet # keep model explanation\r\neffort: high # keep effort explanation\r\n'
                b'permissionMode: plan\r\n---\r\n# SYSTEM BODY\r\nmodel: fake-body\r\n---\r\nMORE\r\n')
        changed = codecs.patch("claude", body, {"model": "claude-custom-123", "effort": None})
        self.assertIn(b'model: "claude-custom-123" # keep model explanation', changed)
        self.assertIn(b"# keep effort explanation\r\n", changed)
        self.assertEqual(changed.split(b"---\r\n", 2)[-1], body.split(b"---\r\n", 2)[-1])
        self.assertEqual(codecs.parse("claude", changed).fields, {"model": "claude-custom-123"})

    def test_inherit_is_host_specific_and_null_only_removes_field(self):
        for host, body in (("codex", b'name="a"\ndescription="x"\ndeveloper_instructions="x"\nmodel="x"\nmodel_reasoning_effort="high"\n'),
                           ("claude", b'---\nname: a\ndescription: x\nmodel: sonnet\neffort: high\n---\nBODY'),
                           ("antigravity", b'---\nname: a\ndescription: x\nmodel: pro\n---\nBODY')):
            edits = {"model": "inherit"} if host == "antigravity" else {"model": "inherit", "effort": "inherit"}
            fields = codecs.parse(host, codecs.patch(host, body, edits)).fields
            self.assertEqual(fields, {} if host == "codex" else {"model": "inherit"})
            self.assertEqual(codecs.parse(host, codecs.patch(host, body, {"model": None})).fields.get("model"), None)

    def test_unknown_nested_yaml_and_broken_or_injected_files_fail_without_mutation(self):
        bodies = [("codex", b'name="a"\ndescription="x"\nmodel="x"\nmodel="y"\ndeveloper_instructions="x"\n'),
                  ("codex", b'name="a"\ndescription="x"\nmodel="inherit"\ndeveloper_instructions="x"\n'),
                  ("claude", b'---\nname: a\ndescription: x\nmodel: sonnet\nmodel: opus\n---\nBODY'),
                  ("claude", b'---\nname: a\ndescription: x\nhooks:\n  Stop:\n    - matcher: x\n---\nBODY'),
                  ("claude", b'---\nname: a\ndescription: x\ntools: [Read, Grep\n---\nBODY'),
                  ("claude", b'---\nname: a\ndescription: x\nmodel: !!python/object:unsafe\n---\nBODY'),
                  ("claude", b'---\nname: a\ndescription: |\n  valid indent\n wrong indent\n---\nBODY'),
                  ("claude", b'---\nname: a\ndescription: x\ntools:\n - Read\n  - Grep\n---\nBODY'),
                  ("antigravity", b'---\nname: a\ndescription: x\nmodel: pro\neffort: high\n---\nBODY')]
        for host, body in bodies:
            with self.subTest(host=host, body=body[:30]), self.assertRaises(ValueError):
                codecs.patch(host, body, {"model": "inherit"})
        safe = b'---\nname: a\ndescription: x\n---\nBODY'
        with self.assertRaises(ValueError):
            codecs.patch("claude", safe, {"model": "x\npermissionMode: bypassPermissions"})


if __name__ == "__main__":
    unittest.main()
