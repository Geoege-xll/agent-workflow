"""真实临时原生清单：非 AWF 名称、同名多来源、插件和明确发现边界。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from native_config import ModelService


def write_agent(root, host, name, fields=None, *, relative=None):
    """只向测试 scratch 写入官方格式；名称不来自任何工作流角色集合。"""
    path = root / (relative or (name + (".toml" if host == "codex" else ".md")))
    path.parent.mkdir(parents=True, exist_ok=True)
    if host == "codex":
        text = f'name = {json.dumps(name)}\ndescription = "Native fixture"\n'
        for field, value in (fields or {}).items():
            key = "model_reasoning_effort" if field == "effort" else field
            text += key + " = " + json.dumps(value) + "\n"
        text += 'developer_instructions = """\nRead source.\nmodel = "fake-body"\n"""\n'
    else:
        text = f'---\nname: {name}\ndescription: Native fixture\n'
        for field, value in (fields or {}).items():
            text += field + ": " + json.dumps(value) + "\n"
        text += 'tools: [Read, Grep]\n---\nRead source.\nmodel: fake-body\n'
    path.write_bytes(text.encode())
    return path


def claude_plugin(home, name="review-kit", agent_name="semantic-auditor", *, enabled=True, declarations=None):
    root = home / ".claude/plugins/cache/market" / name / "1.0"
    (root / ".claude-plugin").mkdir(parents=True)
    manifest = {"name": name}
    if declarations is not None:
        manifest["agents"] = declarations
    (root / ".claude-plugin/plugin.json").write_text(json.dumps(manifest))
    path = write_agent(root / "agents", "claude", agent_name, {"model": "opus"}, relative="review/security.md")
    registry = home / ".claude/plugins/installed_plugins.json"
    registry.write_text(json.dumps({"version": 2, "plugins": {name + "@market": [{"scope": "user", "installPath": str(root), "version": "1.0"}]}}))
    (home / ".claude/settings.json").write_text(json.dumps({"enabledPlugins": {name + "@market": enabled}}))
    return root, path


class NativeInventoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-inventory-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.service = ModelService(self.root / "state", self.home)

    def test_arbitrary_native_names_are_discovered_at_documented_locations(self):
        roots = {"codex": self.home / ".codex/agents", "claude": self.home / ".claude/agents",
                 "antigravity": self.home / ".gemini/config/agents"}
        for host, root in roots.items():
            write_agent(root, host, "organization-auditor", {"model": "pro" if host == "antigravity" else "future-model"},
                        relative="nested/agent.md" if host == "antigravity" else "deep/audit.md" if host == "claude" else None)
            context = self.service.context(host)
            self.assertEqual([row["name"] for row in context["roles"]], ["organization-auditor"])
            self.assertTrue(context["roles"][0]["role"].startswith("agent_"))
            self.assertTrue(context["roles"][0]["writable"])
            self.assertFalse(context["runtime_verified"])
        self.assertFalse((self.root / "state").exists())

    def test_claude_same_name_three_origins_preserve_identity_and_full_definition_resolution(self):
        write_agent(self.home / ".claude/agents", "claude", "semantic-auditor", {"model": "sonnet", "effort": "high"})
        write_agent(self.project / ".claude/agents", "claude", "semantic-auditor", {"model": "haiku"})
        _, plugin_path = claude_plugin(self.home)
        global_id = next(row["role"] for row in self.service.context("claude")["roles"] if row["origin"] == "user")
        rows = self.service.context("claude", "project", self.project)["roles"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["role"] for row in rows}), 3)
        by_origin = {row["origin"]: row for row in rows}
        self.assertEqual(by_origin["user"]["role"], global_id)
        self.assertEqual(by_origin["user"]["definition_status"], "shadowed")
        self.assertEqual(by_origin["user"]["shadowed_by"], by_origin["project"]["role"])
        self.assertEqual(by_origin["project"]["effective"], {"model": "haiku", "effort": "inherit"})
        self.assertEqual(by_origin["project"]["sources"]["effort"], "host_unresolved")
        self.assertFalse(by_origin["plugin"]["writable"])
        self.assertEqual(by_origin["plugin"]["invoke_name"], "review-kit:review:semantic-auditor")
        self.assertEqual(by_origin["plugin"]["source_path"], str(plugin_path))
        self.assertFalse(self.service.resolve_subagent("claude", global_id, self.project)["dispatch_ready"])

    def test_claude_default_scan_and_explicit_manifest_use_frontmatter_with_distinct_subfolder_rules(self):
        """同一原文件的发现方式决定是否带子目录，最后一段始终来自 frontmatter。"""
        root, path = claude_plugin(self.home)
        default = self.service.context("claude")["roles"][0]
        self.assertEqual(default["invoke_name"], "review-kit:review:semantic-auditor")
        self.assertNotEqual(default["invoke_name"], "review-kit:review:security")
        self.assertTrue(default["invoke_ready"])
        resolved = self.service.resolve_subagent("claude", default["role"])
        self.assertEqual(resolved["dispatch"]["subagent_type"], "review-kit:review:semantic-auditor")
        (root / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "review-kit", "agents": ["./agents/review/security.md"]}))
        explicit = self.service.context("claude")["roles"][0]
        self.assertEqual(explicit["source_path"], str(path))
        self.assertEqual(explicit["role"], default["role"], "发现模式改变不能伪造新的源文件身份")
        self.assertEqual(explicit["invoke_name"], "review-kit:semantic-auditor")
        self.assertNotEqual(explicit["invoke_name"], default["invoke_name"])
        self.assertTrue(explicit["invoke_name_verified"])
        self.assertEqual(self.service.resolve_subagent("claude", explicit["role"])["dispatch"]["subagent_type"], "review-kit:semantic-auditor")
        custom = write_agent(root / "custom", "claude", "external-auditor", relative="review/other.md")
        (root / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "review-kit", "agents": "./custom/review/other.md"}))
        row = self.service.context("claude")["roles"][0]
        self.assertEqual(row["source_path"], str(custom))
        self.assertEqual(row["invoke_name"], "review-kit:external-auditor")
        self.assertTrue(row["invoke_ready"])
        self.assertFalse(row["writable"])

    def test_claude_native_invocation_collision_blocks_every_source_instead_of_selecting_file_order(self):
        """文件名不同但原生调用名相同时，默认扫描与 manifest 都必须显示歧义。"""
        root, first = claude_plugin(self.home)
        second = write_agent(root / "agents", "claude", "semantic-auditor", relative="review/other.md")
        for manifest in ({"name": "review-kit"}, {"name": "review-kit", "agents": ["./agents/review/security.md", "./agents/review/other.md"]}):
            (root / ".claude-plugin/plugin.json").write_text(json.dumps(manifest))
            rows = self.service.context("claude")["roles"]
            self.assertEqual({row["source_path"] for row in rows}, {str(first), str(second)})
            self.assertEqual(len({row["role"] for row in rows}), 2)
            self.assertEqual(len({row["invoke_name"] for row in rows}), 1)
            for row in rows:
                self.assertEqual(row["definition_status"], "ambiguous")
                self.assertFalse(row["invoke_ready"])
                self.assertFalse(row["dispatch_ready"])
                self.assertEqual(self.service.resolve_subagent("claude", row["role"])["dispatch"], {})
        # 默认扫描保留目录，因此不同目录的同名 agent 可以独立调用；manifest
        # 改为显式列文件后去掉目录段，必须重新按真正的调用名检出冲突。
        other = root / "agents/audit/other.md"
        other.parent.mkdir()
        second.rename(other)
        (root / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "review-kit"}))
        scanned = self.service.context("claude")["roles"]
        self.assertEqual({row["invoke_name"] for row in scanned}, {"review-kit:review:semantic-auditor", "review-kit:audit:semantic-auditor"})
        self.assertTrue(all(row["invoke_ready"] for row in scanned))
        (root / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "review-kit", "agents": ["./agents/review/security.md", "./agents/audit/other.md"]}))
        explicit = self.service.context("claude")["roles"]
        self.assertEqual({row["invoke_name"] for row in explicit}, {"review-kit:semantic-auditor"})
        self.assertTrue(all(row["definition_status"] == "ambiguous" and not row["invoke_ready"] for row in explicit))

    def test_same_tree_duplicate_is_ambiguous_and_not_sorted_into_fake_precedence(self):
        root = self.home / ".claude/agents"
        write_agent(root, "claude", "duplicate", {"model": "sonnet"}, relative="first.md")
        write_agent(root, "claude", "duplicate", {"model": "opus"}, relative="nested/second.md")
        rows = self.service.context("claude")["roles"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["definition_status"] == "ambiguous" and not row["dispatch_ready"] for row in rows))
        for row in rows:
            self.assertEqual(self.service.resolve_subagent("claude", row["role"])["dispatch"], {})

    def test_nested_claude_project_walk_stops_at_repository_root(self):
        (self.project / ".git").mkdir()
        nested = self.project / "services/api"
        nested.mkdir(parents=True)
        write_agent(self.project / ".claude/agents", "claude", "reviewer", {"model": "opus"})
        write_agent(nested / ".claude/agents", "claude", "reviewer", {"model": "haiku"})
        write_agent(self.root / ".claude/agents", "claude", "outside", {"model": "sonnet"})
        rows = self.service.context("claude", "project", nested)["roles"]
        self.assertEqual(len(rows), 2)
        winner = next(row for row in rows if row["definition_status"] == "effective_in_discovered_sources")
        self.assertEqual(winner["effective"]["model"], "haiku")

    def test_codex_collisions_and_plugin_discovery_are_explicitly_unverified(self):
        write_agent(self.home / ".codex/agents", "codex", "audit-scout", {"model": "custom"})
        write_agent(self.project / ".codex/agents", "codex", "audit-scout", {"effort": "ultra"})
        write_agent(self.home / ".codex/plugins/cache/unsupported/agents", "codex", "invented-plugin-agent")
        context = self.service.context("codex", "project", self.project)
        self.assertEqual(len(context["roles"]), 2)
        self.assertTrue(all(row["definition_status"] == "ambiguous" for row in context["roles"]))
        self.assertIn("codex_plugin_agent_discovery_not_documented", {item["code"] for item in context["diagnostics"]})

    def test_unsupported_registry_damaged_agent_symlink_and_manifest_have_visible_diagnostics(self):
        agents = self.home / ".claude/agents"
        safe = write_agent(agents, "claude", "valid-reader")
        (agents / "bad.md").write_bytes(b"---\nname: duplicate\nname: other\n---\nBODY")
        (agents / "linked.md").symlink_to(safe)
        (self.home / ".claude/plugins").mkdir()
        (self.home / ".claude/plugins/installed_plugins.json").write_text('{"version":999,"plugins":{}}')
        context = self.service.context("claude")
        self.assertEqual(len(context["roles"]), 1)
        codes = {item["code"] for item in context["diagnostics"]}
        self.assertIn("symlink_rejected", codes)
        self.assertIn("unsupported_format", codes)
        self.assertIn("unsupported_claude_install_registry", codes)
        self.assertFalse(context["inventory_complete"])
        self.assertFalse(context["roles"][0]["dispatch_ready"])

    def test_high_priority_invalid_enablement_is_unknown_and_does_not_inherit_user_true(self):
        claude_plugin(self.home, enabled=True)
        write_agent(self.project / ".claude/agents", "claude", "independent-editor")
        (self.project / ".claude/settings.json").write_text(json.dumps({"enabledPlugins": {"review-kit@market": "unknown-type"}}))
        context = self.service.context("claude", "project", self.project)
        plugin = next(row for row in context["roles"] if row["origin"] == "plugin")
        editor = next(row for row in context["roles"] if row["origin"] == "project")
        self.assertFalse(context["inventory_complete"])
        self.assertIsNone(plugin["enabled"])
        self.assertFalse(plugin["dispatch_ready"])
        self.assertFalse(self.service.resolve_subagent("claude", plugin["role"], self.project)["dispatch_ready"])
        self.assertTrue(editor["writable"], "不完整启用观察不能禁止编辑已完整解析的用户定义")
        preview = self.service.preview({"host": "claude", "scope": "project", "project": str(self.project),
                                        "revision": context["revision"], "edits": {editor["role"]: {"effort": "high"}}})
        self.assertTrue(self.service.apply(preview["preview_id"])["saved"])

    def test_invalid_enablement_mapping_and_omitted_install_candidate_lower_completeness(self):
        claude_plugin(self.home, enabled=True)
        setting = self.project / ".claude/settings.json"
        setting.parent.mkdir(parents=True, exist_ok=True)
        for value in (None, ["review-kit@market"]):
            setting.write_text(json.dumps({"enabledPlugins": value}))
            context = self.service.context("claude", "project", self.project)
            self.assertFalse(context["inventory_complete"])
            self.assertIsNone(context["roles"][0]["enabled"])
            self.assertFalse(context["roles"][0]["dispatch_ready"])
        setting.write_text("{}")
        registry = self.home / ".claude/plugins/installed_plugins.json"
        data = json.loads(registry.read_bytes())
        data["plugins"]["unknown@market"] = {"unsupported": "installation record"}
        registry.write_text(json.dumps(data))
        context = self.service.context("claude", "project", self.project)
        self.assertFalse(context["inventory_complete"])
        self.assertIn("unsupported_claude_install_record", {item["code"] for item in context["diagnostics"]})
        self.assertFalse(context["roles"][0]["dispatch_ready"])

    def test_agy_user_project_and_installed_plugin_are_found_without_invented_invoke_schema(self):
        write_agent(self.home / ".gemini/config/agents", "antigravity", "data-scout", {"model": "flash_lite"})
        write_agent(self.project / ".agents/agents", "antigravity", "data-scout", {"model": "pro"})
        plugin = self.home / ".gemini/config/plugins/native-kit"
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text('{"name":"native-kit","version":"1.0"}')
        write_agent(plugin / "agents", "antigravity", "plugin-researcher", {"model": "flash"})
        (self.project / ".agents/agents.json").write_text('{"entries":[{"path":"external"}]}')
        context = self.service.context("antigravity", "project", self.project)
        self.assertEqual(len(context["roles"]), 3)
        project = next(row for row in context["roles"] if row["origin"] == "project")
        self.assertEqual(project["definition_status"], "effective_in_discovered_sources")
        for row in context["roles"]:
            resolved = self.service.resolve_subagent("antigravity", row["role"], self.project)
            self.assertEqual(resolved["dispatch"], {})
            self.assertFalse(resolved["invoke_ready"])
        self.assertIn("external_discovery_manifest_not_supported", {item["code"] for item in context["diagnostics"]})


if __name__ == "__main__":
    unittest.main()
