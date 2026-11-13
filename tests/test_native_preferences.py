"""独立调用偏好：真实隔离文件、纯 reader、继承与安全事务。"""
from __future__ import annotations
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from native_config import ModelService, storage
from native_config import preference_contract as contract
from native_config.contracts import ConflictError
from native_config.server import ConsoleServer
from tests.test_native_inventory import claude_plugin, write_agent


class NativePreferencesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-preferences-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.service = ModelService(self.root / "service-state", self.home)

    def save(self, edits=None, *, host="codex", project=False, reset=False, service=None):
        service = service or self.service
        context = service.context(host, "project" if project else "global", self.project if project else None)
        preview = service.preview({"host": host, "scope": context["scope"], "project": context["project"],
                                   "revision": context["revision"], "dispatch_preferences": {"edits": edits or {}, "reset": reset}})
        return service.apply(preview["preview_id"])

    def test_no_definition_default_first_save_fixed_root_and_reader_cli(self):
        context = self.service.context("codex")
        self.assertEqual(context["roles"], [])
        self.assertEqual([row["target"] for row in context["dispatch_preferences"]["targets"]], ["*"])
        self.assertFalse((self.home / ".codex").exists())
        saved = self.save({"*": {"model": "gpt-6", "effort": "ultra"}})
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["effect"]["kind"], "dispatch_preferences")
        self.assertTrue(saved["effect"]["next_dispatch"])
        self.assertFalse(saved["effect"]["pending_reload"])
        self.assertFalse(saved["effect"]["runtime_verified"])
        path = contract.preference_path("codex", self.home)
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.service.data_dir.exists())
        other = ModelService(self.root / "another-service", self.home)
        self.assertEqual(other.context("codex")["dispatch_preferences"]["targets"][0]["overrides"], {"model": "gpt-6", "effort": "ultra"})
        reader = Path(contract.__file__)
        result = subprocess.run([sys.executable, "-I", "-B", str(reader), "--host", "codex", "--agent", "default",
                                 "--home", str(self.home)], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        resolved = json.loads(result.stdout)
        self.assertEqual(set(resolved), {"schema_version", "host", "agent", "status", "configured", "preferences", "sources", "runtime_verified"})
        self.assertEqual(resolved["preferences"], {"model": "gpt-6", "effort": "ultra"})
        self.assertEqual(contract.resolve_preferences("codex", "*", home=self.home)["preferences"], resolved["preferences"])
        self.assertEqual(list(self.project.iterdir()), [])

    def test_inheritance_plugin_identity_project_clear_and_history(self):
        _, plugin_path = claude_plugin(self.home)
        plugin_before = plugin_path.read_bytes()
        context = self.service.context("claude")
        role = context["roles"][0]
        name = role["invoke_name"]
        self.assertIn(":", name)
        self.assertFalse(role["writable"])
        self.save({"*": {"model": "sonnet", "effort": "low"}, name: {"model": "opus"}}, host="claude")
        self.save({"*": {"effort": "high"}, name: {"model": "haiku"}}, host="claude", project=True)
        result = contract.resolve_preferences("claude", name, self.project, self.home)
        self.assertEqual(result["preferences"], {"model": "haiku", "effort": "high"})
        self.assertEqual(result["sources"], {"model": "project_agent", "effort": "project_default"})
        saved = self.save({name: {"model": None}}, host="claude", project=True)
        self.assertTrue(saved["saved"])
        result = contract.resolve_preferences("claude", name, self.project, self.home)
        self.assertEqual(result["preferences"]["model"], "opus")
        self.assertEqual(result["sources"]["model"], "user_agent")
        self.save(host="claude", project=True, reset=True)
        self.assertEqual(contract.resolve_preferences("claude", name, self.project, self.home)["sources"]["effort"], "user_default")
        self.assertEqual(plugin_path.read_bytes(), plugin_before)
        # 历史身份仍展示和可清除，但移除真实定义后不能被当作已验证原生派发。
        plugin_path.unlink()
        row = next(row for row in self.service.context("claude")["dispatch_preferences"]["targets"] if row["target"] == name)
        self.assertEqual(row["origin"], "configured")
        self.assertFalse(row["dispatch_ready"])
        self.assertFalse(row["invoke_name_verified"])
        self.save({name: {"model": None}}, host="claude")

    def test_known_legacy_claude_roles_fill_fields_at_each_layer_without_writes(self):
        """七个精确旧键只补新键缺失字段，四层优先级和原文件字节都保留。"""
        identity = contract.load_identity(contract.PACKAGE_ROOT)
        for role in identity["managed_roles"]:
            old, new = "agent-workflow:" + role, "xy-workflow:" + role
            document = {**contract.empty_document("claude"), "defaults": {"model": "sonnet", "effort": "low"},
                "agents": {old: {"model": "opus", "effort": "medium"}, new: {"effort": "high"}},
                "projects": {str(self.project): {"defaults": {"model": "haiku"},
                    "agents": {old: {"effort": "max"}, new: {"model": "fable"}}}}}
            path = contract.preference_path("claude", self.home)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document))
            before = path.read_bytes()
            user = contract.resolve_preferences("claude", new, home=self.home)
            self.assertEqual(user["preferences"], {"model": "opus", "effort": "high"})
            result = contract.resolve_preferences("claude", new, self.project, self.home)
            self.assertEqual(result["preferences"], {"model": "fable", "effort": "max"})
            self.assertEqual(result["sources"], {"model": "project_agent", "effort": "project_agent"})
            self.assertEqual(path.read_bytes(), before)
            # 未知角色、其他插件及 opaque inventory ID 没有别名回退。
            for unknown in ("xy-workflow:unknown", "other:" + role, "agent_opaque_123"):
                self.assertEqual(contract.project_preferences(document, unknown)["preferences"], document["defaults"])
            # Codex 身份不使用 Claude 命名空间回退。
            document["host"] = "codex"
            self.assertEqual(contract.project_preferences(document, new)["preferences"], {"model": "sonnet", "effort": "high"})
        self.assertFalse(self.service.data_dir.exists())

    def test_exclusive_preview_no_writes_cancel_revision_once_and_null(self):
        context = self.service.context("codex")
        payload = {"host": "codex", "revision": context["revision"], "dispatch_preferences": {"edits": {"*": {"effort": "high"}}}}
        for extra in ({"edits": {}}, {"reset": False}, {"workflow_activation": {"state": "disabled"}}):
            with self.assertRaises(ValueError):
                self.service.preview({**payload, **extra})
        first, second = self.service.preview(payload), self.service.preview(payload)
        self.assertFalse((self.home / ".codex").exists())
        self.assertTrue(self.service.apply(first["preview_id"])["saved"])
        with self.assertRaises(ConflictError):
            self.service.apply(first["preview_id"])
        with self.assertRaises(ConflictError):
            self.service.apply(second["preview_id"])
        self.save({"*": {"effort": None}})
        self.assertFalse(contract.resolve_preferences("codex", "default", home=self.home)["configured"])

    def test_malformed_version_duplicate_null_unsafe_paths_fail_closed(self):
        path = contract.preference_path("codex", self.home)
        path.parent.mkdir(parents=True)
        for body in (b"{broken", b'{"schema_version":99}', b'{"schema_version":1,"schema_version":1}',
                     json.dumps({**contract.empty_document("codex"), "defaults": {"effort": None}}).encode()):
            path.write_bytes(body)
            with self.assertRaises(ValueError):
                self.service.context("codex")
            result = subprocess.run([sys.executable, "-B", str(Path(contract.__file__)), "--host", "codex", "--agent", "default", "--home", str(self.home)], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_preferences")
            self.assertNotIn(body, result.stdout)
        path.unlink()
        outside = self.root / "outside"
        outside.write_bytes(json.dumps(contract.empty_document("codex")).encode())
        path.symlink_to(outside)
        for read in (lambda: self.service.context("codex"), lambda: contract.resolve_preferences("codex", "default", home=self.home)):
            with self.assertRaises(ValueError):
                read()
        path.unlink()
        os.link(outside, path)
        with self.assertRaises(ValueError):
            contract.resolve_preferences("codex", "default", home=self.home)
        path.unlink()
        path.parent.rmdir()
        path.parent.symlink_to(self.root)
        with self.assertRaises(ValueError):
            self.service.context("codex")

    def test_source_change_after_preview_and_restore_real_preimage(self):
        self.save({"*": {"model": "original"}})
        path = contract.preference_path("codex", self.home)
        before = path.read_bytes()
        context = self.service.context("codex")
        request = {"host": "codex", "revision": context["revision"], "dispatch_preferences": {"edits": {"*": {"model": "new"}}}}
        plan = self.service.preview(request)
        path.write_bytes(json.dumps({**contract.empty_document("codex"), "defaults": {"model": "external"}}).encode())
        with self.assertRaises(ConflictError):
            self.service.apply(plan["preview_id"])
        self.assertEqual(contract.resolve_preferences("codex", "default", home=self.home)["preferences"]["model"], "external")
        path.write_bytes(before)
        context = self.service.context("codex")
        plan = self.service.preview({**request, "revision": context["revision"]})
        real_link = storage.os.link
        def fail_candidate(source, *args, **kwargs):
            if source == "candidate.new":
                raise OSError("fixture failure after real inode isolation")
            return real_link(source, *args, **kwargs)
        with patch.object(storage.os, "link", side_effect=fail_candidate):
            result = self.service.apply(plan["preview_id"])
        self.assertFalse(result["saved"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result["results"][0]["status"], "rolled_back")
        backup = next(item for item in result["recovery"] if item["kind"] == "preview_preimage")
        self.assertEqual(Path(backup["backup"]).read_bytes(), before)
        self.assertEqual(backup["sha256"], hashlib.sha256(before).hexdigest())

    def test_parent_replacement_before_first_save_is_not_followed(self):
        (self.home / ".codex").mkdir()
        context = self.service.context("codex")
        preview = self.service.preview({"host": "codex", "revision": context["revision"], "dispatch_preferences": {"edits": {"*": {"effort": "high"}}}})
        moved = self.home / "moved"
        (self.home / ".codex").rename(moved)
        outside = self.root / "outside-root"
        outside.mkdir()
        (self.home / ".codex").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.service.apply(preview["preview_id"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_host_root_same_source_and_capability_negative_controls(self):
        env = {"CODEX_HOME": str(self.root / "real-codex"), "CLAUDE_CONFIG_DIR": str(self.root / "real-claude")}
        self.assertEqual(contract.preference_path("codex", environment=env), self.root / "real-codex/native-agent-config/dispatch-preferences.json")
        self.assertEqual(contract.preference_path("codex", self.home, env), self.home / ".codex/native-agent-config/dispatch-preferences.json")
        for host, edits in (("claude", {"model": "claude-full-id"}), ("antigravity", {"model": "gemini-4-argon-medium"}), ("antigravity", {"effort": "high"})):
            with self.assertRaises(ValueError):
                self.save({"*": edits}, host=host)
        self.assertTrue(self.save({"*": {"model": "flash"}}, host="antigravity")["saved"])
        row = self.service.context("antigravity")["dispatch_preferences"]["targets"][0]
        self.assertFalse(row["dispatch_ready"])
        self.assertEqual(row["effective"], {"model": "flash"})

    def final_selection_fixture(self, document):
        """真实配置文件仅提供本用例的已观察能力，不调用外部模型。"""
        directory = self.home / ".codex"
        directory.mkdir(exist_ok=True)
        (directory / "config.toml").write_text('model_catalog_json="models.json"\n')
        (directory / "models.json").write_text(json.dumps({"models": [
            {"id": "model-a", "supported_reasoning_levels": ["low", "high"]},
            {"id": "model-b", "supported_reasoning_levels": ["low"]}]}))
        write_agent(directory / "agents", "codex", "worker")
        path = contract.preference_path("codex", self.home)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(document))
        self.assertEqual(self.service.catalog("codex")["status"], "ready")
        return path

    def final_preview(self, edits, *, project=False):
        context = self.service.context("codex", "project" if project else "global", self.project if project else None)
        return self.service.preview({"host": "codex", "scope": context["scope"], "project": context["project"],
                                     "revision": context["revision"], "dispatch_preferences": {"edits": edits}})

    def test_final_transaction_invalid_combination_rejected_in_both_edit_orders(self):
        document = {**contract.empty_document("codex"), "defaults": {"model": "model-a"},
                    "agents": {"worker": {"effort": "low"}}}
        path = self.final_selection_fixture(document)
        original = path.read_bytes()
        pairs = [("worker", {"effort": "high"}), ("*", {"model": "model-b"})]
        for ordered in (pairs, list(reversed(pairs))):
            with self.subTest(order=[key for key, _ in ordered]), self.assertRaisesRegex(ValueError, "不支持所选推理档位"):
                self.final_preview(dict(ordered))
            self.assertEqual(path.read_bytes(), original)

    def test_default_only_change_checks_discovered_and_configured_inheriting_targets(self):
        document = {**contract.empty_document("codex"), "defaults": {"model": "model-a"}}
        path = self.final_selection_fixture(document)
        for target in ("worker", "offline-configured"):
            document["agents"] = {target: {"effort": "high"}}
            path.write_text(json.dumps(document))
            original = path.read_bytes()
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "不支持所选推理档位"):
                self.final_preview({"*": {"model": "model-b"}})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(contract.resolve_preferences("codex", target, home=self.home)["preferences"], {"model": "model-a", "effort": "high"})

    def test_final_transaction_explicit_clear_or_reselect_saves_in_both_orders(self):
        document = {**contract.empty_document("codex"), "defaults": {"model": "model-a"},
                    "agents": {"worker": {"effort": "high"}}}
        path = self.final_selection_fixture(document)
        for effort in (None, "low"):
            path.write_text(json.dumps(document))
            pairs = [("worker", {"effort": effort}), ("*", {"model": "model-b"})]
            first = self.final_preview(dict(pairs))
            second = self.final_preview(dict(reversed(pairs)))
            self.assertEqual(first["changes"], second["changes"])
            self.assertEqual(first["warnings"], second["warnings"])
            # 两个顺序都分别实际保存同一最终文档，复用同一隔离home而不复制源树。
            one = self.service.apply(first["preview_id"])
            self.assertTrue(one["saved"])
            expected = path.read_bytes()
            path.write_text(json.dumps(document))
            two = self.service.apply(self.final_preview(dict(reversed(pairs)))["preview_id"])
            self.assertTrue(two["saved"])
            self.assertEqual(path.read_bytes(), expected)
            resolved = contract.resolve_preferences("codex", "worker", home=self.home)["preferences"]
            self.assertEqual(resolved, {"model": "model-b", **({"effort": effort} if effort else {})})

    def test_final_validation_skips_unchanged_old_errors_other_projects_and_unknown_capability(self):
        document = {**contract.empty_document("codex"), "defaults": {"model": "model-a"},
                    "agents": {"legacy-invalid": {"model": "model-b", "effort": "high"},
                               "unknown": {"model": "unobserved-model", "effort": "high"},
                               "worker": {"model": "model-a", "effort": "low"}},
                    "projects": {str(self.project): {"defaults": {"model": "model-b"}, "agents": {"offline": {"effort": "high"}}}}}
        path = self.final_selection_fixture(document)
        preview = self.final_preview({"*": {"model": "model-b"}, "unknown": {"effort": "low"}})
        self.assertTrue(any("unverified" in warning for warning in preview["warnings"]))
        saved = self.service.apply(preview["preview_id"])
        self.assertTrue(saved["saved"])
        after = json.loads(path.read_text())
        self.assertEqual(after["agents"]["legacy-invalid"], document["agents"]["legacy-invalid"])
        self.assertEqual(after["projects"], document["projects"])
        self.assertFalse(saved["effect"]["runtime_verified"])

    def test_final_validation_never_borrows_another_context_catalog(self):
        self.final_selection_fixture(contract.empty_document("codex"))
        # 已观察的是通用上下文目录；尚未获取项目目录时不能用它拒绝项目值。
        preview = self.final_preview({"*": {"model": "model-b", "effort": "high"}}, project=True)
        self.assertTrue(any("unverified" in warning for warning in preview["warnings"]))
        saved = self.service.apply(preview["preview_id"])
        self.assertTrue(saved["saved"])
        self.assertEqual(contract.resolve_preferences("codex", "worker", self.project, self.home)["preferences"],
                         {"model": "model-b", "effort": "high"})
        self.assertFalse(saved["effect"]["runtime_verified"])

    def test_readonly_preference_file_cannot_be_overwritten(self):
        self.save({"*": {"effort": "high"}})
        path = contract.preference_path("codex", self.home)
        path.chmod(0o400)
        original = path.read_bytes()
        self.assertFalse(self.service.context("codex")["dispatch_preferences"]["targets"][0]["writable"])
        with self.assertRaises(ValueError):
            self.save({"*": {"effort": "low"}})
        self.assertEqual(path.read_bytes(), original)

    def test_actual_loopback_context_preview_apply_and_reader_agree(self):
        server = ConsoleServer(self.service)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def request(method, path, payload=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request(method, path, body=json.dumps(payload) if payload is not None else None,
                                   headers={"Authorization": "Bearer " + server.token, "Origin": server.origin, "Content-Type": "application/json"})
                response = connection.getresponse()
                body = json.loads(response.read())
                self.assertEqual(response.status, 200, body)
                return body
            finally:
                connection.close()
        context = request("GET", "/api/context?host=codex")
        self.assertRegex(context["catalog_source_stamp"], r"^[0-9a-f]{64}$")
        preview = request("POST", "/api/preview", {"host": "codex", "revision": context["revision"], "dispatch_preferences": {"edits": {"*": {"model": "gpt-6"}}}})
        result = request("POST", "/api/apply", {"preview_id": preview["preview_id"]})
        self.assertTrue(result["saved"])
        self.assertEqual(contract.resolve_preferences("codex", "default", home=self.home)["preferences"], result["context"]["dispatch_preferences"]["targets"][0]["effective"])
