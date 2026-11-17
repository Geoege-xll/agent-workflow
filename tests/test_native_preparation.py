"""原生准备的真实隔离文件事务：不读取或改写运行者的宿主配置。"""

from __future__ import annotations

from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import tomllib
import unittest
from unittest import mock

from native_config import preparation, storage
from native_config.contracts import ConfigError, ConflictError
from native_config.server import configuration_identity
from native_config.service import ModelService, _Plan


TEST_NAMES = ("xy-web", "xy-desktop", "xy-backend", "xy-apple", "xy-android", "xy-uiux", "xy-qa")


def make_source(root, names=TEST_NAMES):
    """最小真实双摘要源包；测试修改后须显式重签，避免绕过完整性检查。"""
    root.mkdir(parents=True)
    files = {"roles/source.md": b"canonical role\n", "product/ROLES.yaml": b"roles: canonical\n",
             "platforms/codex/WORKER_CONSTRAINTS.md": b"constraints\n", "plugins/codex/native-agent-context.md": b"context\n",
             ".codex-plugin/plugin.json": json.dumps({"name": "xy-workflow", "version": "3.0.4"}).encode()}
    entries, projections = [], {}
    dependencies = {name: hashlib.sha256(files[name]).hexdigest() for name in
                    ("product/ROLES.yaml", "platforms/codex/WORKER_CONSTRAINTS.md", "plugins/codex/native-agent-context.md")}
    for name in names:
        files["roles/" + name + ".md"] = b"canonical role\n"
        document = {"name": name, "description": "角色 " + name,
                    "developer_instructions": "角色正文；物理来源 " + preparation.PLACEHOLDER}
        body = ("\n".join(key + " = " + json.dumps(value, ensure_ascii=False) for key, value in document.items()) + "\n").encode()
        relative = "native-agent-templates/codex/" + name + ".toml"
        files[relative] = body
        entries.append({"name": name, "description": document["description"], "path": relative,
                        "sha256": hashlib.sha256(body).hexdigest()})
        projections[relative] = {"source": "roles/" + name + ".md", "transform": "codex-native-template-v1",
                                 "adapter": "plugins/codex/native-agent-context.md", "dependencies": dependencies,
                                 "source_sha256": hashlib.sha256(files["roles/" + name + ".md"]).hexdigest(),
                                 "projection_sha256": hashlib.sha256(body).hexdigest()}
    files[preparation.INDEX] = json.dumps({"schema_version": 1, "product": "xy-workflow", "host": "codex",
                                           "version": "3.0.4", "templates": entries}).encode()
    canonical = {key: hashlib.sha256(value).hexdigest() for key, value in files.items()
                 if not key.startswith("native-agent-templates/") and key != ".codex-plugin/plugin.json"}
    projections[preparation.INDEX] = {"source": "product/ROLES.yaml", "transform": "codex-native-template-index-v1",
                                      "source_sha256": canonical["product/ROLES.yaml"],
                                      "projection_sha256": hashlib.sha256(files[preparation.INDEX]).hexdigest(),
                                      "dependencies": {entry["path"]: entry["sha256"] for entry in entries}}
    files["workflow-sources.json"] = json.dumps({"schema_version": 1, "files": canonical}).encode()
    files["sources.json"] = json.dumps({"schema_version": 1, "plugin_name": "xy-workflow", "plugin_version": "3.0.4",
                                        "host": "codex", "product": "workflow-core",
                                        "source_files": canonical, "projections": projections,
                                        "payload_sha256": {key: hashlib.sha256(value).hexdigest() for key, value in files.items()}}).encode()
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return root


class NativePreparationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.source = make_source(self.root / 'plugin "quoted"')
        self.home = self.root / "isolated-home"
        self.project = self.root / "project"
        self.project.mkdir()
        self.service = ModelService(self.root / "data", home=self.home, preparation_source=self.source)

    def tearDown(self):
        self.temporary.cleanup()

    def context(self, project=False):
        return self.service.context("codex", "project" if project else "global", str(self.project) if project else None)

    def plan(self, service=None, project=None):
        """构造内部未发布计划，以真实来源和清单测试既有 guard 的并发拒绝。"""
        service = service or self.service
        state = service._capture("codex", "project" if project is not None else "global", project)
        return _Plan(state, preparation.missing_plan(state.preparation, state, service.host_roots["codex"]),
                     time.monotonic(), "native_preparation")

    def test_first_creation_native_edit_and_second_open_preserves_bytes_and_mtime(self):
        context = self.context()
        self.assertEqual(context["roles"], [])
        self.assertNotIn("native_preparation", context)
        self.assertFalse(self.home.exists())
        receipt = self.service.prepare_missing_builtins()
        self.assertEqual(receipt["created"], 7)
        context = self.context()
        self.assertEqual({row["name"] for row in context["roles"]}, set(TEST_NAMES))
        for row in context["roles"]:
            self.assertEqual(row["overrides"], {})
            document = tomllib.loads(Path(row["source_path"]).read_text())
            self.assertEqual(set(document), {"name", "description", "developer_instructions"})
            self.assertIn(str(self.source), document["developer_instructions"])
        agent = context["roles"][0]
        edit = self.service.preview({"host": "codex", "revision": context["revision"],
                                     "edits": {agent["role"]: {"model": "gpt-test", "effort": "high"}}})
        self.assertTrue(self.service.apply(edit["preview_id"])["saved"])
        before = {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                  for path in (self.home / ".codex/agents").glob("*.toml")}
        with mock.patch.object(storage, "write_batch", side_effect=AssertionError("幂等补齐不应进入写事务")):
            self.assertEqual(self.service.prepare_missing_builtins()["status"], "unchanged")
        self.assertEqual(before, {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                                  for path in before})
        self.assertEqual(tomllib.loads(Path(agent["source_path"]).read_text())["model"], "gpt-test")

    def test_project_same_name_definition_is_preserved_without_project_write(self):
        project_agent = self.project / ".codex/agents/xy-web.toml"
        project_agent.parent.mkdir(parents=True)
        project_agent.write_text('name="xy-web"\ndescription="project"\ndeveloper_instructions="project body"\nmodel="project-model"\n')
        before = project_agent.read_bytes(), project_agent.stat().st_mtime_ns
        receipt = self.service.prepare_missing_builtins(project=self.project)
        self.assertEqual((receipt["created"], receipt["project_provided"], receipt["preserved"]), (6, 1, 0))
        context = self.context(project=True)
        same = [row for row in context["roles"] if row["name"] == "xy-web"]
        self.assertEqual(len(same), 1)
        # 本次打开不新增重复用户定义，已有唯一项目定义保持原发现状态。
        self.assertEqual(same[0]["definition_status"], "effective_in_discovered_sources")
        self.assertEqual(same[0]["overrides"]["model"], "project-model")
        self.assertFalse((self.home / ".codex/agents/xy-web.toml").exists())
        with mock.patch.object(storage, "write_batch", side_effect=AssertionError("项目已提供定义不应重复写入")):
            second = self.service.prepare_missing_builtins(project=self.project)
        self.assertEqual((second["created"], second["project_provided"], second["preserved"]), (0, 1, 6))
        self.assertEqual(before, (project_agent.read_bytes(), project_agent.stat().st_mtime_ns))
        self.assertEqual(len(list(project_agent.parent.glob("*.toml"))), 1)

    def test_project_name_addition_or_removal_invalidates_same_plan(self):
        project_agent = self.project / ".codex/agents/xy-web.toml"
        project_agent.parent.mkdir(parents=True)
        body = 'name="xy-web"\ndescription="project"\ndeveloper_instructions="keep"\n'
        for change in ("addition", "removal"):
            with self.subTest(change=change):
                if change == "removal":
                    project_agent.write_text(body)
                plan = self.plan(project=self.project)
                if change == "addition":
                    project_agent.write_text(body)
                else:
                    project_agent.unlink()
                with self.assertRaises(ConflictError):
                    self.service._apply_plan(plan)
                self.assertFalse(self.home.exists(), "项目同名变化必须在任何用户目录创建前拒绝")
                if project_agent.exists():
                    project_agent.unlink()

    def test_project_name_race_after_user_directory_creation_is_rejected(self):
        project_agent = self.project / ".codex/agents/xy-web.toml"
        project_agent.parent.mkdir(parents=True)
        original = storage._rename_directory_exclusive

        def race(parent, source, destination):
            original(parent, source, destination)
            if destination == "agents":
                project_agent.write_text('name="xy-web"\ndescription="project"\ndeveloper_instructions="keep"\n')

        with mock.patch.object(storage, "_rename_directory_exclusive", side_effect=race):
            with self.assertRaises(ConflictError):
                self.service.prepare_missing_builtins(project=self.project)
        self.assertFalse((self.home / ".codex/agents/xy-web.toml").exists())
        self.assertEqual(list((self.home / ".codex/agents").glob("*.toml")), [])
        self.assertTrue(project_agent.is_file())

    def test_same_name_elsewhere_and_occupied_target_are_preserved_across_source_upgrade(self):
        parent = self.home / ".codex/agents"
        parent.mkdir(parents=True)
        custom = parent / "custom.toml"
        custom.write_text('name="xy-web"\ndescription="existing"\ndeveloper_instructions="keep"\nmodel="saved"\nmodel_reasoning_effort="high"\n')
        occupied = parent / "xy-backend.toml"
        occupied.write_text('name="other"\ndescription="existing"\ndeveloper_instructions="keep"\n')
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (custom, occupied)}
        self.assertEqual(self.service.prepare_missing_builtins()["created"], 5)
        source2 = make_source(self.root / "next-plugin")
        next_service = ModelService(self.root / "data", home=self.home, preparation_source=source2)
        with mock.patch.object(storage, "write_batch", side_effect=AssertionError("来源升级不能重写现有定义")):
            self.assertEqual(next_service.prepare_missing_builtins()["status"], "unchanged")
        self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before})
        self.assertFalse((parent / "xy-web.toml").exists())

    def test_invalid_inventory_symlink_and_incomplete_source_fail_without_creation(self):
        parent = self.home / ".codex/agents"
        parent.mkdir(parents=True)
        unknown = parent / "unknown.toml"
        unknown.write_text("not valid TOML")
        with self.assertRaises(ConfigError):
            self.service.prepare_missing_builtins()
        unknown.unlink()
        (parent / "xy-web.toml").symlink_to(self.root / "outside")
        with self.assertRaises(ConfigError):
            self.service.prepare_missing_builtins()
        (self.source / "roles/xy-web.md").unlink()
        with self.assertRaises(ConfigError):
            self.service.prepare_missing_builtins()
        self.assertTrue(any(row["code"] == "native_preparation_source_unavailable" for row in self.context()["diagnostics"]))
        self.assertEqual(len(list(parent.glob("*.toml"))), 1)

    def test_real_unwritable_directory_refuses_creation(self):
        if os.geteuid() == 0:
            self.skipTest("root 可绕过目录写权限；真实权限负控须以普通用户执行")
        parent = self.home / ".codex/agents"
        parent.mkdir(parents=True)
        parent.chmod(0o500)
        try:
            with self.assertRaises(PermissionError):
                self.service.prepare_missing_builtins()
            self.assertEqual(list(parent.glob("*.toml")), [])
        finally:
            parent.chmod(0o700)

    def test_real_competing_directory_lock_refuses_without_retry(self):
        # 真实持有最近既有祖先目录锁；不模拟storage或guard，验证并发失败关闭。
        with storage.directory(self.root) as handle:
            fcntl.flock(handle.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ConflictError):
                self.service.prepare_missing_builtins()
        self.assertFalse(self.home.exists())

    def test_public_manual_api_removed_and_context_is_read_only(self):
        before = list(self.root.rglob("*"))
        for host in ("codex", "claude", "antigravity"):
            with mock.patch.object(storage, "write_batch", side_effect=AssertionError("读取清单发生写入")):
                self.assertNotIn("native_preparation", self.service.context(host))
        self.assertEqual(before, list(self.root.rglob("*")))
        with self.assertRaises(ConfigError):
            self.service.preview({"host": "codex", "revision": self.context()["revision"], "native_preparation": {}})
        self.assertFalse(self.home.exists())

    def test_source_and_target_cas_refuse_stale_internal_plan(self):
        plan = self.plan()
        (self.source / "roles/xy-web.md").write_bytes(b"changed")
        with self.assertRaises(ConflictError):
            self.service._apply_plan(plan)
        self.assertFalse(self.home.exists())
        (self.source / "roles/xy-web.md").write_bytes(b"canonical role\n")
        plan = self.plan()
        parent = self.home / ".codex/agents"
        parent.mkdir(parents=True)
        (parent / "xy-web.toml").write_bytes(b"external")
        with self.assertRaises(ConflictError):
            self.service._apply_plan(plan)
        self.assertEqual((parent / "xy-web.toml").read_bytes(), b"external")

    def test_concurrent_file_after_own_directory_creation_is_rejected(self):
        original = storage._rename_directory_exclusive

        def race(parent, source, destination):
            original(parent, source, destination)
            if destination == "agents":
                path = self.home / ".codex/agents/concurrent.toml"
                path.write_text('name="external"\ndescription="external"\ndeveloper_instructions="keep"\n')

        with mock.patch.object(storage, "_rename_directory_exclusive", side_effect=race):
            with self.assertRaises(ConflictError):
                self.service.prepare_missing_builtins()
        self.assertFalse((self.home / ".codex/agents/xy-web.toml").exists())
        self.assertTrue((self.home / ".codex/agents/concurrent.toml").is_file())

    def test_authoritative_context_source_is_checked_before_any_write(self):
        for source_state in ("unavailable", "changed"):
            with self.subTest(source_state=source_state):
                home = self.root / ("authority-" + source_state)
                service = ModelService(self.root / ("state-" + source_state), home=home,
                                       preparation_source=self.source)
                plan = self.plan(service)
                original_capture = service._capture

                def invalidate_context(*args, **kwargs):
                    current = original_capture(*args, **kwargs)
                    prepared = (None if source_state == "unavailable" else
                                replace(current.preparation, revision="0" * 64))
                    return replace(current, preparation=prepared)

                with mock.patch.object(service, "_capture", side_effect=invalidate_context):
                    with self.assertRaises(ConflictError):
                        service._apply_plan(plan)
                self.assertFalse(home.exists(), "初始来源 guard 必须在创建目标目录前拒绝")

    def test_source_identity_and_unsupported_standalone(self):
        standalone = ModelService(self.root / "data", home=self.home)
        self.assertNotEqual(configuration_identity(standalone), configuration_identity(self.service))
        with self.assertRaises(ConfigError):
            standalone.prepare_missing_builtins()
        metadata = self.source / "sources.json"
        record = json.loads(metadata.read_bytes())
        record["host"] = "claude"
        metadata.write_text(json.dumps(record))
        self.assertTrue(any(row["code"] == "native_preparation_source_host_unsupported" for row in self.context()["diagnostics"]))
        self.assertFalse(self.home.exists())

    def test_static_manifest_path_escape_and_template_model_are_rejected(self):
        metadata_path = self.source / "sources.json"
        original = metadata_path.read_bytes()
        metadata = json.loads(original)
        metadata["payload_sha256"]["../escape"] = "0" * 64
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaises(ConfigError):
            preparation.load(self.source)
        metadata_path.write_bytes(original)
        template = self.source / "native-agent-templates/codex/xy-web.toml"
        template.write_bytes(template.read_bytes() + b'model = "forbidden"\n')
        self.assertIsNone(preparation.capture(self.source))
        # 即使攻击者同步重签索引/发行摘要，准备 schema 仍禁止模型或权限字段。
        relative = template.relative_to(self.source).as_posix()
        index_path = self.source / preparation.INDEX
        index = json.loads(index_path.read_bytes())
        new_hash = hashlib.sha256(template.read_bytes()).hexdigest()
        next(entry for entry in index["templates"] if entry["path"] == relative)["sha256"] = new_hash
        index_path.write_text(json.dumps(index))
        metadata = json.loads(original)
        metadata["payload_sha256"][relative] = new_hash
        metadata["payload_sha256"][preparation.INDEX] = hashlib.sha256(index_path.read_bytes()).hexdigest()
        metadata["projections"][relative]["projection_sha256"] = new_hash
        metadata["projections"][preparation.INDEX]["projection_sha256"] = metadata["payload_sha256"][preparation.INDEX]
        metadata["projections"][preparation.INDEX]["dependencies"][relative] = new_hash
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ConfigError, "不允许模型"):
            preparation.load(self.source)


if __name__ == "__main__":
    unittest.main()
