"""原生准备的真实隔离文件事务：不读取或改写运行者的宿主配置。"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock

from native_config import preparation, storage
from native_config.contracts import ConfigError, ConflictError
from native_config.server import configuration_identity
from native_config.service import ModelService


def make_source(root, names=("xy-web", "xy-backend")):
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

    def request(self, context, candidates=None):
        native = context["native_preparation"]
        return {key: context[key] for key in ("host", "scope", "project", "revision")} | {
            "native_preparation": {"source_id": native["source_id"], "source_revision": native["source_revision"],
                                   "candidate_ids": candidates or [row["candidate_id"] for row in native["candidates"] if row["status"] == "missing"]}}

    def test_preview_zero_write_first_directory_creation_and_real_native_edit(self):
        context = self.context()
        self.assertEqual(context["roles"], [])
        self.assertEqual(context["dispatch_preferences"]["targets"][0]["target"], "*")
        plan = self.service.preview(self.request(context))
        self.assertEqual(plan["kind"], "native_preparation")
        self.assertFalse(plan["dispatch_ready"])
        self.assertFalse(self.home.exists())
        self.assertIn(str(self.source), tomllib.loads(plan["changes"][0]["after"])["developer_instructions"])
        receipt = self.service.apply(plan["preview_id"])
        self.assertTrue(receipt["saved"], receipt)
        self.assertEqual(len(receipt["context"]["roles"]), 2)
        self.assertTrue(all(row["status"] == "existing" for row in receipt["context"]["native_preparation"]["candidates"]))
        agent = receipt["context"]["roles"][0]
        self.assertEqual(agent["overrides"], {})
        edit = self.service.preview({"host": "codex", "revision": receipt["context"]["revision"],
                                     "edits": {agent["role"]: {"model": "gpt-test", "effort": "high"}}})
        edited = self.service.apply(edit["preview_id"])
        self.assertTrue(edited["saved"])
        self.assertEqual(tomllib.loads(Path(agent["source_path"]).read_text())["model"], "gpt-test")

    def test_project_target_is_exact_and_same_name_user_definition_preserved(self):
        plan = self.service.preview(self.request(self.context(project=True)))
        result = self.service.apply(plan["preview_id"])
        self.assertTrue(result["saved"], result)
        self.assertTrue((self.project / ".codex/agents/xy-web.toml").is_file())
        self.assertFalse(self.home.exists())
        self.assertFalse((self.root / ".codex").exists())
        user = self.home / ".codex/agents/other-name.toml"
        user.parent.mkdir(parents=True)
        user.write_text('name = "xy-web"\ndescription = "user"\ndeveloper_instructions = "keep"\nmodel = "saved"\n')
        context = self.context(project=True)
        row = next(row for row in context["native_preparation"]["candidates"] if row["name"] == "xy-web")
        self.assertEqual(row["status"], "conflict")
        before = user.read_bytes()
        with self.assertRaises(ConfigError):
            self.service.preview(self.request(context, [row["candidate_id"]]))
        self.assertEqual(user.read_bytes(), before)

    def test_same_name_different_file_and_occupied_target_are_never_overwritten(self):
        parent = self.home / ".codex/agents"
        parent.mkdir(parents=True)
        (parent / "custom.toml").write_text('name="xy-web"\ndescription="existing"\ndeveloper_instructions="keep"\n')
        (parent / "xy-backend.toml").write_text('name="other"\ndescription="existing"\ndeveloper_instructions="keep"\n')
        context = self.context()
        self.assertTrue(all(row["status"] == "conflict" for row in context["native_preparation"]["candidates"]))
        for row in context["native_preparation"]["candidates"]:
            with self.assertRaises(ConfigError):
                self.service.preview(self.request(context, [row["candidate_id"]]))

    def test_invalid_inventory_symlink_and_incomplete_source_are_blocked(self):
        parent = self.home / ".codex/agents"
        parent.mkdir(parents=True)
        (parent / "unknown.toml").write_text("not valid TOML")
        self.assertTrue(all(row["status"] == "blocked" for row in self.context()["native_preparation"]["candidates"]))
        (parent / "unknown.toml").unlink()
        (parent / "xy-web.toml").symlink_to(self.root / "outside")
        self.assertTrue(all(row["status"] == "blocked" for row in self.context()["native_preparation"]["candidates"]))
        (self.source / "roles/xy-web.md").unlink()
        context = self.context()
        self.assertFalse(context["native_preparation"]["supported"])
        self.assertTrue(any(row["code"] == "native_preparation_source_unavailable" for row in context["diagnostics"]))

    def test_source_and_target_cas_and_request_boundaries(self):
        context = self.context()
        request = self.request(context)
        for extra in ({"edits": {}}, {"reset": False}, {"workflow_activation": {}}, {"dispatch_preferences": {}}):
            with self.assertRaises(ConfigError):
                self.service.preview(request | extra)
        forged = self.request(context)
        forged["native_preparation"]["target_path"] = str(self.root / "escape")
        with self.assertRaises(ConfigError):
            self.service.preview(forged)
        plan = self.service.preview(request)
        (self.source / "roles/xy-web.md").write_bytes(b"changed")
        with self.assertRaises(ConflictError):
            self.service.apply(plan["preview_id"])
        self.assertFalse(self.home.exists())
        # 来源恢复后重新预览，但另一个作者创建的目标必须触发原生清单 CAS。
        (self.source / "roles/xy-web.md").write_bytes(b"canonical role\n")
        plan = self.service.preview(self.request(self.context()))
        parent = self.home / ".codex/agents"
        parent.mkdir(parents=True)
        (parent / "xy-web.toml").write_bytes(b"external")
        with self.assertRaises(ConflictError):
            self.service.apply(plan["preview_id"])
        self.assertEqual((parent / "xy-web.toml").read_bytes(), b"external")

    def test_concurrent_file_after_own_directory_creation_is_rejected(self):
        plan = self.service.preview(self.request(self.context()))
        original = storage._rename_directory_exclusive

        def race(parent, source, destination):
            original(parent, source, destination)
            if destination == "agents":
                path = self.home / ".codex/agents/concurrent.toml"
                path.write_text('name="external"\ndescription="external"\ndeveloper_instructions="keep"\n')

        with mock.patch.object(storage, "_rename_directory_exclusive", side_effect=race):
            result = self.service.apply(plan["preview_id"])
        self.assertFalse(result["saved"], result)
        self.assertFalse((self.home / ".codex/agents/xy-web.toml").exists())
        self.assertTrue((self.home / ".codex/agents/concurrent.toml").is_file())

    def test_authoritative_context_source_is_checked_before_any_write(self):
        # 两个场景都让真实插件来源保持有效，只在完整权威上下文回读结束后
        # 注入失效/不同修订的来源快照，精确覆盖“另一次读取成功掩盖本次失效”。
        # 仅替换 _capture 的结果，不模拟 guard 或 storage，目录/文件仍走真实事务。
        for source_state in ("unavailable", "changed"):
            with self.subTest(source_state=source_state):
                home = self.root / ("authority-" + source_state)
                service = ModelService(self.root / ("state-" + source_state), home=home,
                                       preparation_source=self.source)
                context = service.context("codex")
                plan = service.preview(self.request(context))
                self.assertEqual(preparation.capture(self.source).revision,
                                 context["native_preparation"]["source_revision"])
                original_capture = service._capture

                def invalidate_context(*args, **kwargs):
                    current = original_capture(*args, **kwargs)
                    prepared = (None if source_state == "unavailable" else
                                replace(current.preparation, revision="0" * 64))
                    return replace(current, preparation=prepared)

                with mock.patch.object(service, "_capture", side_effect=invalidate_context):
                    with self.assertRaises(ConflictError):
                        service.apply(plan["preview_id"])
                self.assertFalse(home.exists(), "初始来源 guard 必须在创建目标目录前拒绝")
                self.assertFalse((home / ".codex/agents/xy-web.toml").exists())

    def test_source_identity_and_unsupported_standalone(self):
        standalone = ModelService(self.root / "data", home=self.home)
        self.assertEqual(standalone.context("codex")["native_preparation"],
                         {"supported": False, "source_id": None, "source_revision": None, "candidates": []})
        self.assertFalse(self.service.context("claude")["native_preparation"]["supported"])
        self.assertNotEqual(configuration_identity(standalone), configuration_identity(self.service))
        source2 = make_source(self.root / "second-plugin")
        alternate = ModelService(self.root / "data", home=self.home, preparation_source=source2)
        self.assertNotEqual(configuration_identity(alternate), configuration_identity(self.service))
        metadata = self.source / "sources.json"
        record = json.loads(metadata.read_bytes())
        record["host"] = "claude"
        metadata.write_text(json.dumps(record))
        context = self.context()
        self.assertFalse(context["native_preparation"]["supported"])
        self.assertTrue(any(row["code"] == "native_preparation_source_host_unsupported" for row in context["diagnostics"]))
        self.assertFalse(any(row["code"] == "native_preparation_source_unavailable" for row in context["diagnostics"]))

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
        self.assertFalse(self.context()["native_preparation"]["supported"])
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
