"""官方插件的真实离线载荷回归，不以manifest解析代替宿主运行验收。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit
import zipfile


PACK = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("awf_plugin_builder", PACK / "packaging/build_plugin.py")
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


def isolated_environment(root: Path) -> dict[str, str]:
    """只用应用专属配置位置隔离测试，不重设HOME或CODEX_HOME等宿主根变量。"""
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("AGENT_WORKFLOW_") and key != "PYTHONPATH"}
    environment.update(CLAUDE_CONFIG_DIR=str(root / "claude-config"), PYTHONDONTWRITEBYTECODE="1")
    return environment


class ArchiveModesTest(unittest.TestCase):
    def test_shared_archive_modes_preserve_root_and_prefixed_locked_resources(self):
        """同一权限权威同时覆盖ZIP写入、根启动器与带prefix的上游可执行文件。"""
        vendor = "third_party/selected-skills/playwright-cli/runtime/tool.sh"
        lock = json.dumps({"dependencies": {"playwright-cli": {"files": {"runtime/tool.sh": {"mode": 0o755}}}}}).encode()
        files = {"README.md": b"readme", "plugins/source_pack.py": b"entry",
                 "lib/python_runtime.sh": b"python", "plugins/maintenance/launcher.sh": b"launcher",
                 builder.SELECTED_LOCK: lock, vendor: b"tool"}
        expected = {name: 0o100644 for name in files}
        expected.update({name: 0o100755 for name in ("plugins/source_pack.py", "lib/python_runtime.sh", "plugins/maintenance/launcher.sh", vendor)})
        self.assertEqual(expected, builder.archive_modes(files))
        prefix = "plugins/xy-workflow/"
        local = {prefix + name: body for name, body in files.items()}
        local_modes = {name: 0o100644 for name in local}
        local_modes[prefix + vendor] = 0o100755
        self.assertEqual(local_modes, builder.archive_modes(local))
        with tempfile.TemporaryDirectory(prefix="awf-archive-modes-") as temporary:
            target = Path(temporary) / "plugin.zip"
            builder.write_archive(local, target)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(local_modes, {entry.filename: entry.external_attr >> 16 for entry in archive.infolist()})

    def test_archive_modes_reject_permissions_outside_the_fixed_file_contract(self):
        for mode in (0o600, 0o777, 0o4755, True, "755"):
            with self.subTest(mode=mode):
                lock = json.dumps({"dependencies": {"playwright-cli": {"files": {"runtime/tool.sh": {"mode": mode}}}}}).encode()
                with self.assertRaisesRegex(ValueError, "644 or 755"):
                    builder.archive_modes({builder.SELECTED_LOCK: lock})


class PluginDeliveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="awf-plugin-delivery-")
        cls.root = Path(cls.temporary.name).resolve()
        cls.archives, cls.installed = {}, {}
        for host in builder.HOSTS:
            archive = builder.build(PACK, cls.root / "first", host)
            installed = cls.root / "installed" / host
            installed.mkdir(parents=True)
            with zipfile.ZipFile(archive) as payload:
                payload.extractall(installed)
            cls.archives[host], cls.installed[host] = archive, installed

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_two_offline_builds_are_byte_identical(self):
        # 第二个输出目录及归档mtime不同，ZIP内固定元数据仍必须让字节完全相同。
        for host in builder.HOSTS:
            with self.subTest(host=host):
                second = builder.build(PACK, self.root / "second", host)
                self.assertEqual(self.archives[host].read_bytes(), second.read_bytes())
                expected = hashlib.sha256(second.read_bytes()).hexdigest()
                self.assertEqual(expected, second.with_suffix(".zip.sha256").read_text().split()[0])

    def test_native_manifest_shapes_use_only_documented_fields(self):
        allowed = {
            "codex": {"name", "version", "description", "author", "skills", "hooks"},
            "claude": {"name", "version", "description", "author"},
            "antigravity": {"$schema", "name", "displayName", "version", "description", "author"},
        }
        for host, root in self.installed.items():
            with self.subTest(host=host):
                manifest = json.loads((root / builder.MANIFESTS[host]).read_bytes())
                self.assertEqual(allowed[host], set(manifest))
                self.assertNotIn("agents", manifest)
                self.assertEqual((PACK / "product/PLUGIN_VERSION").read_text().strip(), manifest["version"])
                self.assertEqual((PACK / "product/VERSION").read_text().strip(),
                                 (root / "product/VERSION").read_text().strip())
                self.assertTrue((root / "skills/xy-workflow/SKILL.md").is_file())
                self.assertEqual(host != "codex", (root / "agents").exists())
                if host == "codex":
                    # 真实 CLI 0.167.0 遇到 portable 根清单会漏发现 Hook；禁止
                    # 构建再次同时输出两套入口，从而掩盖默认 PM 入口的缺失。
                    self.assertEqual(".codex-plugin/plugin.json", builder.MANIFESTS[host])
                    self.assertFalse((root / "plugin.json").exists())
                    self.assertEqual("./skills/", manifest["skills"])
                    self.assertEqual("./hooks/hooks.json", manifest["hooks"])
                if host == "antigravity":
                    self.assertIn("skills/xy-workflow/SKILL.md", (root / "rules/AGENTS.md").read_text())
                if host == "claude":
                    self.assertEqual({"agent": "pm"}, json.loads((root / "settings.json").read_bytes()))
                    header, _ = builder.split_frontmatter((root / "agents/pm.md").read_bytes())
                    self.assertNotIn(b"model:", header)
                    self.assertNotIn(b"tools:", header)
                    self.assertNotIn(b"permissionMode:", header)

    def test_codex_hook_is_only_an_entry_reminder_with_explicit_trust_boundary(self):
        root = self.installed["codex"]
        hook = json.loads((root / "hooks/hooks.json").read_bytes())
        self.assertEqual({"SessionStart"}, set(hook["hooks"]))
        self.assertNotIn("fork", hook["hooks"]["SessionStart"][0]["matcher"])
        result = subprocess.run([sys.executable, "-B", str(root / "hooks/session_start.py")],
                                cwd=self.root, env=isolated_environment(self.root / "hook-home"),
                                input='{"source":"startup"}', capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual("SessionStart", output["hookEventName"])
        self.assertIn(str(root / "skills/xy-workflow/SKILL.md"), output["additionalContext"])
        self.assertNotIn("requirements_approved", output["additionalContext"])
        self.assertFalse((self.root / "hook-home").exists())
        self.assertTrue(json.loads((root / "sources.json").read_bytes())["hook_trust_required"])

    def test_antigravity_preserves_authority_with_its_recorded_adapter_and_native_body_budget(self):
        # 原生 CLI 已证明旧通用适配会让主技能超过 24KB；核对每个实际发现技能
        # 的完整源正文、真实适配来源和字节预算，不能靠删掉流程末尾通过校验。
        root = self.installed["antigravity"]
        adapter_source = "plugins/antigravity/plugin-context.md"
        adapter = (PACK / adapter_source).read_bytes()
        self.assertIn("完整连续覆盖".encode("utf-8"), adapter)
        self.assertIn("按缺失行范围续读".encode("utf-8"), adapter)
        self.assertIn("不重复读取已覆盖内容".encode("utf-8"), adapter)
        metadata = json.loads((root / "sources.json").read_bytes())
        self.assertEqual(adapter, (root / adapter_source).read_bytes())
        self.assertEqual(hashlib.sha256(adapter).hexdigest(), metadata["source_files"][adapter_source])
        for skill in builder.CORE_SKILLS:
            relative = f"skills/{skill}/SKILL.md"
            original = (PACK / "platforms/shared" / relative).read_bytes()
            header, original_body = builder.split_frontmatter(original)
            generated = (root / relative).read_bytes()
            self.assertEqual(header + b"\n" + adapter + b"\n" + original_body, generated)
            self.assertEqual(adapter_source, metadata["projections"][relative]["adapter"])
            self.assertLessEqual(len(builder.split_frontmatter(generated)[1].strip()), 24_000)

    def test_antigravity_rejects_native_truncation_before_creating_an_archive(self):
        # 模拟适配文本将来增长；UTF-8 中文按字节计数，不能把字符数误当预算。
        # 使用真实构建路径验证会在创建输出目录前失败，避免产生可安装的残缺候选。
        read_source = builder.read_source
        def oversized_adapter(source, relative):
            original = read_source(source, relative)
            if relative == "plugins/antigravity/plugin-context.md":
                return original + ("中" * 2_000).encode("utf-8")
            return original
        output = self.root / "oversized-antigravity-output"
        with mock.patch.object(builder, "read_source", side_effect=oversized_adapter):
            with self.assertRaisesRegex(ValueError, "Antigravity skill body exceeds 24000 bytes"):
                builder.build(PACK, output, "antigravity")
        self.assertFalse(output.exists())

    def test_builder_rejects_an_undocumented_codex_agents_field(self):
        root = self.installed["codex"]
        manifest = json.loads((root / builder.MANIFESTS["codex"]).read_bytes())
        manifest["agents"] = "./agents/"
        with self.assertRaisesRegex(ValueError, "undocumented"):
            builder.validate_manifest("codex", manifest, "3.0.0-alpha.1")

    def test_package_has_no_external_links_installers_or_paused_delivery_assets(self):
        for host, archive in self.archives.items():
            with self.subTest(host=host), zipfile.ZipFile(archive) as files:
                for entry in files.infolist():
                    name = entry.filename
                    self.assertFalse(stat.S_ISLNK(entry.external_attr >> 16), name)
                    self.assertNotIn("..", Path(name).parts)
                    self.assertFalse(name.startswith("/"), name)
                    # 上游完整资产含技术品牌图标，不是被暂停的Windows发行入口。
                    if not name.startswith("third_party/selected-skills/taste/skills/taste-skill/assets/"):
                        self.assertNotIn("windows", name.casefold())
                    # 原版Playwright完整闭包允许其精确vendor/node_modules根，不能放行任意依赖目录。
                    playwright_runtime = name.startswith("third_party/selected-skills/playwright-cli/runtime/node_modules/")
                    if not playwright_runtime:
                        self.assertNotIn("node_modules", name)
                    if not playwright_runtime and not name.startswith("third_party/selected-skills/taste/skills/taste-skill/assets/"):
                        self.assertNotIn("npm", name.casefold())
                    self.assertNotIn("npx", name.casefold())
                    self.assertNotIn(name, {"package.json", "package-lock.json", "manager/cli.py", "manager/tui.py"})
                    self.assertFalse(name.startswith(("lib/install/", "packaging/", ".github/")), name)
                    self.assertFalse(Path(name).name.startswith("setup_"), name)
                self.assertIn("lib/documents/safe_documents.py", files.namelist())
                self.assertIn("lib/documents/validate_prototype_workspace.py", files.namelist())
                # 文档与模板沿现有声明目录进入三端包，不能依靠开发仓补齐反馈依赖。
                for relative in ("lib/documents/prototype_feedback.py",
                                 "lib/documents/prototype_review.py",
                                 "lib/documents/prototype_feedback_cli.py",
                                 "templates/prototype/feedback.js", "templates/prototype/feedback.css",
                                 "platforms/shared/skills/xy-ui-design/references/prototype-feedback.md"):
                    self.assertIn(relative, files.namelist())
                self.assertNotIn("lib/documents/requirement_html.py", files.namelist())
                self.assertFalse(any(name.startswith("lib/vendor/answer-me-with-html/") for name in files.namelist()))
                self.assertFalse(any(name.startswith(("plugin_runtime/", "native_config/", "manager/")) for name in files.namelist()))
                for script in ("scripts/plugin_service.py", "scripts/agent_config.py", "scripts/agent_config.sh"):
                    self.assertNotIn(script, files.namelist())
                self.assertTrue({"mcp.json", ".mcp.json", "mcp_config.json"}.isdisjoint(files.namelist()))

    def test_default_core_builds_with_configuration_service_sources_physically_absent(self):
        # 只用已声明来源构成独立源码夹具；不复制服务、网页、manager或服务启动脚本。
        source = self.root / "core-only-source"
        source.mkdir()
        originals = set()
        for root in self.installed.values():
            originals.update(json.loads((root / "sources.json").read_bytes())["source_files"])
        for relative in originals:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((PACK / relative).read_bytes())
        self.assertFalse((source / "plugin_runtime").exists())
        self.assertEqual([source / builder.PREFERENCE_SOURCE],
                         list((source / "native_config").rglob("*")))
        self.assertFalse((source / "manager").exists())
        self.assertFalse((source / "scripts/plugin_service.py").exists())
        for host in builder.HOSTS:
            with self.subTest(host=host):
                archive = builder.build(source, self.root / "core-only-build", host)
                with zipfile.ZipFile(archive) as files:
                    metadata = json.loads(files.read("sources.json"))
                    self.assertEqual("workflow-core", metadata["product"])
                    self.assertNotIn("model_service_included", metadata)
                    self.assertIn("lib/task_graph_cli.py", files.namelist())
                    self.assertIn(builder.PREFERENCE_PROJECTION, files.namelist())
                    self.assertFalse(any(name.startswith("native_config/") for name in files.namelist()))

    def test_local_sources_have_complete_payloads_and_real_relative_marketplace_targets(self):
        output = self.root / "local-source-output"
        for host, archive in self.archives.items():
            with self.subTest(host=host):
                emitted = builder.local_source(archive, output, host)
                if host == "antigravity":
                    plugin = emitted
                else:
                    index = emitted / (".agents/plugins/marketplace.json" if host == "codex" else ".claude-plugin/marketplace.json")
                    manifest = json.loads(index.read_bytes())
                    source = manifest["plugins"][0]["source"]
                    relative = source["path"] if isinstance(source, dict) else source
                    self.assertTrue(relative.startswith("./"))
                    plugin = (emitted / relative).resolve()
                    self.assertTrue(plugin.is_relative_to(emitted))
                with zipfile.ZipFile(archive) as package:
                    for relative in package.namelist():
                        self.assertEqual(package.read(relative), (plugin / relative).read_bytes(), relative)
                self.assertTrue((plugin / builder.MANIFESTS[host]).is_file())
                source_zip = archive.with_name(archive.stem + "-local-source.zip")
                self.assertTrue(source_zip.is_file())
                with zipfile.ZipFile(source_zip) as distribution:
                    expected = plugin.relative_to(output / "local" / host) / builder.MANIFESTS[host]
                    self.assertIn(expected.as_posix(), distribution.namelist())
                with self.assertRaises(FileExistsError):
                    builder.local_source(archive, output, host)

    @unittest.skipUnless(shutil.which("claude"), "Claude CLI unavailable; local marketplace validation pending")
    def test_claude_native_validator_accepts_the_complete_local_marketplace(self):
        market = builder.local_source(self.archives["claude"], self.root / "claude-marketplace-output", "claude")
        result = subprocess.run([shutil.which("claude"), "plugin", "validate", str(market)],
                                cwd=self.root, env=isolated_environment(self.root / "marketplace-check"),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_source_manifest_matches_actual_unmodified_authority(self):
        for host, root in self.installed.items():
            with self.subTest(host=host):
                sources = json.loads((root / "workflow-sources.json").read_bytes())
                self.assertEqual({"schema_version", "files"}, set(sources))
                self.assertEqual(1, sources["schema_version"])
                for relative, expected in sources["files"].items():
                    self.assertEqual((PACK / relative).read_bytes(), (root / relative).read_bytes(), relative)
                    self.assertEqual(expected, hashlib.sha256((root / relative).read_bytes()).hexdigest())
                metadata = json.loads((root / "sources.json").read_bytes())
                self.assertFalse(metadata["runtime_verified"])
                self.assertEqual("workflow-core", metadata["product"])
                self.assertNotIn("model_service_included", metadata)
                self.assertEqual({builder.PREFERENCE_SOURCE},
                                 {name for name in metadata["source_files"] if name.startswith("native_config/")})
                self.assertFalse(any(name.startswith(("plugin_runtime/", "manager/"))
                                     for name in metadata["source_files"]))
                self.assertTrue(metadata["pending_acceptance"])

    def test_dispatch_reader_is_identical_to_its_only_standard_library_source(self):
        expected = (PACK / builder.PREFERENCE_SOURCE).read_bytes()
        for host, root in self.installed.items():
            with self.subTest(host=host):
                actual = (root / builder.PREFERENCE_PROJECTION).read_bytes()
                self.assertEqual(expected, actual)
                metadata = json.loads((root / "sources.json").read_bytes())
                projection = metadata["projections"][builder.PREFERENCE_PROJECTION]
                digest = hashlib.sha256(expected).hexdigest()
                dependencies = {relative: hashlib.sha256((PACK / relative).read_bytes()).hexdigest()
                                for relative in ("product/__init__.py", "product/command_identity.py", "product/command_identity.json")}
                self.assertEqual({"source": builder.PREFERENCE_SOURCE, "transform": "identity",
                                  "source_sha256": digest, "projection_sha256": digest, "dependencies": dependencies}, projection)
                self.assertEqual(digest, metadata["source_files"][builder.PREFERENCE_SOURCE])
        for body in (b"from .service import ConfigService", b"import native_config.server", b"import lib.role_models"):
            with self.subTest(forbidden_import=body):
                with self.assertRaisesRegex(ValueError, "standard library|relative imports"):
                    builder.validate_preference_reader(body)

    def test_detached_dispatch_preferences_use_same_source_without_http_or_configuration_writes(self):
        # 三宿主均离开源码执行真正投影与 wrapper；fixture 只写显式隔离 home，
        # 缺失、继承与损坏负控共享同一个根。有效结果与源包入口逐字段一致。
        base = self.root / "dispatch-preferences"
        home, project = base / "home", base / "project"
        project.mkdir(parents=True)
        suffixes = {"codex": ".codex", "claude": ".claude", "antigravity": ".gemini/config"}
        for host, root in self.installed.items():
            with self.subTest(host=host):
                arguments = ["dispatch-preferences", "--host", host, "--agent", "*",
                             "--project", str(project), "--home", str(home)]
                command = [sys.executable, "-I", "-B", str(root / "plugins/source_pack.py"), *arguments]
                env = isolated_environment(base)
                def query(argv):
                    return subprocess.run(argv, cwd=base, env=env, capture_output=True, text=True, timeout=10)
                missing = query(command)
                self.assertEqual(0, missing.returncode, missing.stderr)
                self.assertEqual({"schema_version", "host", "agent", "status", "configured", "preferences",
                                  "sources", "runtime_verified"}, set(json.loads(missing.stdout)))
                self.assertFalse(json.loads(missing.stdout)["configured"])
                path = home / suffixes[host] / "native-agent-config/dispatch-preferences.json"
                self.assertFalse(path.parent.exists())
                path.parent.mkdir(parents=True)
                document = {"schema_version": 1, "host": host, "defaults": {"model": "inherit"},
                            "agents": {"agent-workflow:xy-qa": {"model": "ignored-agent-model"}} if host == "codex" else {},
                            "projects": {str(project): {"defaults": {"model": "inherit"}, "agents": {}}}}
                path.write_text(json.dumps(document))
                before = path.read_bytes()
                result = query(command)
                source = query([sys.executable, "-I", "-B", str(PACK / "plugins/source_pack.py"), *arguments])
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(0, source.returncode, source.stderr)
                self.assertEqual(json.loads(source.stdout), json.loads(result.stdout))
                value = json.loads(result.stdout)
                self.assertEqual({"model": "inherit"}, value["preferences"])
                self.assertEqual("project_default", value["sources"]["model"])
                self.assertFalse(value["runtime_verified"])
                self.assertEqual(before, path.read_bytes())
                path.write_text('{"secret_fixture":"must-never-echo"}')
                rejected = query(command)
                self.assertNotEqual(0, rejected.returncode)
                self.assertEqual("invalid_preferences", json.loads(rejected.stdout)["error"]["code"])
                self.assertNotIn("must-never-echo", rejected.stdout + rejected.stderr)
                path.unlink()
        self.assertFalse(any(path.name in {"launch.json", "token", "service.json"} for path in base.rglob("*")))

    def test_dispatch_reader_keeps_central_context_and_project_boundaries(self):
        root = self.installed["codex"]
        base = self.root / "dispatch-boundaries"
        project = base / "project"
        project.mkdir(parents=True)
        command = [sys.executable, "-I", "-B", str(root / "plugins/source_pack.py"), "dispatch-preferences",
                   "--host", "codex", "--agent", "*", "--home", str(base / "home")]
        env = isolated_environment(base)
        linked = base / "linked-parent"
        linked.symlink_to(base, target_is_directory=True)
        for target, changed in ((root, {}), (project, {"AGENT_WORKFLOW_CORE_ROOT": str(root)}),
                                (project, {"AGENT_WORKFLOW_PLUGIN_ROOT": str(base)}),
                                (linked / "project", {})):
            with self.subTest(target=target, environment=changed):
                result = subprocess.run([*command, "--project", str(target)], cwd=base,
                    env={**env, **changed}, capture_output=True, text=True, timeout=10)
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        marker = project / ".agent-workflow/runtime.json"
        marker.parent.mkdir()
        marker.write_text("{}")
        result = subprocess.run([*command, "--project", str(project)], cwd=base, env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)

    def test_retired_integration_option_rejects_before_creating_output(self):
        # 旧调用不能静默构建另一个产品；参数预校验失败也不能留下半套安装载荷。
        output = self.root / "retired-integration-output"
        result = subprocess.run([sys.executable, "-B", str(PACK / "packaging/build_plugin.py"),
                                 "--with-model-service", "--output-dir", str(output)],
                                cwd=self.root, env=isolated_environment(self.root / "retired-option"),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(2, result.returncode)
        self.assertIn("unrecognized arguments", result.stderr)
        self.assertFalse(output.exists())

    def test_detached_resource_entry_uses_packaged_authority_without_project_bridge(self):
        project = self.root / "resource-project"
        project.mkdir(exist_ok=True)
        for host, root in self.installed.items():
            with self.subTest(host=host):
                result = subprocess.run([sys.executable, "-B", str(root / "plugins/source_pack.py"),
                                         "resource", ".agent-workflow/product/WORKFLOW.md"],
                                        cwd=project, env=isolated_environment(self.root / "home"),
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                resource = json.loads(result.stdout)
                self.assertEqual(str(root / "product/WORKFLOW.md"), resource["path"])
                self.assertFalse(resource["runtime_verified"])
                self.assertEqual([], list(project.iterdir()))

    def test_detached_selected_skill_failures_reject_before_any_script(self):
        from lib.skills.selected_skills import VENDOR, skill_path
        root = self.installed["codex"]
        command = [sys.executable, "-B", str(root / "plugins/source_pack.py"), "selected-skills", "check"]
        target = root / skill_path("grilling")
        original = target.read_bytes()
        extra = root / VENDOR / "unexpected-file"
        environment = isolated_environment(self.root / "selected-rejection")
        def rejected():
            result = subprocess.run(command, cwd=self.root, env=environment, capture_output=True, text=True, timeout=20)
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        try:
            target.unlink()
            rejected()
            target.write_bytes(original + b"tampered")
            rejected()
            target.unlink()
            target.symlink_to(root / skill_path("grill-me"))
            rejected()
            target.unlink()
            target.write_bytes(original)
            extra.write_bytes(b"not in upstream inventory")
            rejected()
            extra.unlink()
            result = subprocess.run([sys.executable, "-B", str(root / "plugins/source_pack.py"), "resource", "../outside"], cwd=self.root, env=environment, capture_output=True, text=True, timeout=20)
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        finally:
            target.unlink(missing_ok=True)
            target.write_bytes(original)
            extra.unlink(missing_ok=True)

    def test_selected_skills_are_complete_detached_and_do_not_register_taste_hooks(self):
        """真实三端载荷消费同一原文，连续读取覆盖全部字节，绝不执行原版脚本。"""
        from lib.skills.selected_skills import LOCK, VENDOR, SPECS, snapshot, skill_path
        lock, originals = snapshot(PACK)
        project = self.root / "selected-skills-project"
        project.mkdir()
        for host, root in self.installed.items():
            with self.subTest(host=host):
                self.assertEqual((PACK / LOCK).read_bytes(), (root / LOCK).read_bytes())
                metadata = json.loads((root / "sources.json").read_bytes())
                for relative, body in originals.items():
                    self.assertEqual(body, (root / relative).read_bytes())
                    self.assertEqual(hashlib.sha256(body).hexdigest(), metadata["source_files"][relative])
                from lib.skills.role_skills import SELECTED_SKILL_ALIASES
                for alias, canonical in SELECTED_SKILL_ALIASES.items():
                    self.assertEqual((PACK / "plugins/selected-skills" / alias / "SKILL.md").read_bytes(),
                                     (root / "skills" / alias / "SKILL.md").read_bytes())
                    self.assertFalse((root / "skills" / canonical).exists())
                adapter = (root / "skills/xy-taste/SKILL.md").read_bytes()
                header, _ = builder.split_frontmatter(adapter)
                self.assertNotIn(b"hooks:", header)
                self.assertNotIn(b"gate.mjs", (root / "hooks/hooks.json").read_bytes() if host == "codex" else b"")
                self.assertFalse((root / "skills/xy-taste/scripts").exists())
                command = ["bash", str(root / "lib/python_runtime.sh"), "-B", "-X", "utf8", str(root / "plugins/source_pack.py")]
                environment = isolated_environment(self.root / "selected-home")
                checked = subprocess.run([*command, "selected-skills", "check"], cwd=project, env=environment, capture_output=True, text=True, timeout=20)
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
                self.assertFalse(json.loads(checked.stdout)["upstream_scripts_executed"])
                # 包外真实启动固定官方CLI，不依赖全局旧版；doctor不启动或安装browser。
                version = subprocess.run([*command, "xy-playwright", "--", "--version"], cwd=project, env=environment, capture_output=True, text=True, timeout=20)
                self.assertEqual(0, version.returncode, version.stdout + version.stderr)
                self.assertEqual("0.1.24", version.stdout.strip())
                diagnosis = subprocess.run([*command, "xy-playwright", "--", "doctor"], cwd=project, env=environment, capture_output=True, text=True, timeout=20)
                self.assertEqual(0, diagnosis.returncode, diagnosis.stdout + diagnosis.stderr)
                ready = json.loads(diagnosis.stdout)
                self.assertEqual("0.1.24", ready["cli"]["version"])
                self.assertTrue(ready["node"]["ready"])
                self.assertFalse(ready["browser"]["runtime_verified"])
                self.assertFalse(ready["upstream_browser_launched"])
                chunks, offset = [], 0
                while True:
                    result = subprocess.run([*command, "selected-skills", "read", "xy-taste", "--offset", str(offset), "--length", "12000"], cwd=project, env=environment, capture_output=True, text=True, timeout=20)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    page = json.loads(result.stdout)
                    self.assertEqual(offset, page["offset"])
                    chunks.append(page["content"].encode("utf-8"))
                    offset = page["next_offset"]
                    if page["eof"]:
                        break
                self.assertEqual(originals[skill_path("design-taste-frontend")], b"".join(chunks))
                resource = subprocess.run([*command, "resource", skill_path("design-taste-frontend")], cwd=project, env=environment, capture_output=True, text=True, timeout=20)
                self.assertEqual(0, resource.returncode, resource.stdout + resource.stderr)
                self.assertEqual(str(root / skill_path("design-taste-frontend")), json.loads(resource.stdout)["path"])
                self.assertEqual([], list(project.iterdir()))

    def test_detached_awf_prototype_navigation_fingerprints_and_visual_gate(self):
        """真实独立包从空项目创建 .awf，原型证据继续约束原有视觉门禁。"""
        from tests.test_prototype_workspace import (
            INDEX_HTML, PROTOTYPE_CSS, PAGE_HTML, bind_requirement_documents, tree_snapshot,
        )
        from tests.test_plugin_workflow_contract import visual_request

        for host, root in self.installed.items():
            with self.subTest(host=host):
                project = self.root / ("prototype-awf-" + host)
                project.mkdir()
                base = ["bash", str(root / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                        str(root / "plugins/source_pack.py"), "helper", "--project", str(project)]

                def invoke(helper, *arguments):
                    return subprocess.run([*base, helper, *map(str, arguments)], cwd=project,
                                          env=isolated_environment(self.root / "prototype-context"),
                                          capture_output=True, text=True, timeout=15)

                applied = invoke("plugins/project_context.py", "apply", "--adapter", ".awf/project.yaml")
                self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
                self.assertTrue(json.loads(applied.stdout)["created"])
                prototype = project / "docs/standards/prototype"
                prototype.mkdir(parents=True)
                for name, body in (("index.html", INDEX_HTML), ("prototype.css", PROTOTYPE_CSS),
                                   ("settings.html", PAGE_HTML)):
                    (prototype / name).write_text(body, encoding="utf-8")
                source, historical = bind_requirement_documents(project, adapter=".awf/project.yaml")
                # 当前项目概况由这次原型交付维护，不能要求空项目 apply 自动创建文档。
                # 没有实际验收基线，因此不把 active 需求冒写成 PROJECT 的已交付链接。
                (project / "docs/PROJECT.md").write_text(
                    "# 原型导航测试项目\n\n## 当前项目\n验证设置页原型交付。\n\n"
                    "## 当前已验收基线\n当前原型尚未验收。\n", encoding="utf-8")
                self.assertFalse((project / "project.yaml").exists())
                # 角色的标准文档校验与原型校验消费同一已选适配器；包内原样角色
                # 通过真实 helper 执行，不能只改示例文字却仍借用源码根配置。
                role = (root / "roles/xy-uiux.md").read_text(encoding="utf-8")
                self.assertIn("--adapter <selected-project-adapter>", role)
                self.assertNotIn("validate_project_docs.py .agent-workflow/project.yaml", role)
                checked_docs = invoke("lib/validate_project_docs.py", ".awf/project.yaml", project)
                self.assertEqual(0, checked_docs.returncode, checked_docs.stdout + checked_docs.stderr)
                before = tree_snapshot(project)
                arguments = [project, "docs/standards/prototype", "--adapter", ".awf/project.yaml", "--json"]
                first = invoke("lib/documents/validate_prototype_workspace.py", *arguments)
                self.assertEqual(0, first.returncode, first.stdout + first.stderr)
                fingerprint = json.loads(first.stdout)["pages"][0]["dependency_fingerprint"]
                same = invoke("lib/documents/validate_prototype_workspace.py", *arguments,
                              "--expect", "settings.html=" + fingerprint)
                self.assertEqual(0, same.returncode, same.stderr)
                self.assertEqual(before, tree_snapshot(project))
                # Markdown 与历史页继续安全导航，但不进入页面的画面依赖闭包。
                source.write_bytes(source.read_bytes() + b"\nupdated requirements progress")
                historical.write_bytes(historical.read_bytes() + b"\nretained historical note")
                unchanged = invoke("lib/documents/validate_prototype_workspace.py", *arguments,
                                   "--expect", "settings.html=" + fingerprint)
                self.assertEqual(0, unchanged.returncode, unchanged.stderr)
                missing_adapter = invoke("lib/documents/validate_prototype_workspace.py",
                                         project, "docs/standards/prototype", "--json")
                self.assertEqual(1, missing_adapter.returncode)
                self.assertIn("--adapter", missing_adapter.stderr)
                retired = invoke("lib/documents/requirement_html.py", "render")
                self.assertEqual(2, retired.returncode)
                self.assertIn("invalid choice", retired.stderr)
                # 原有实际任务图消费刚取得的证据；没有用户视觉批准仍然不能 ready。
                value, _ = visual_request("UI-Page")
                value = json.loads(json.dumps(value).replace("b" * 64, fingerprint))
                for task in value["tasks"]:
                    if "controlled_document_access" in task:
                        task["controlled_document_access"]["adapter"] = ".awf/project.yaml"
                current = project / "current.json"
                current.write_text(json.dumps(value), encoding="utf-8")
                waiting = invoke("lib/task_graph_cli.py", "ready", "--input", current)
                self.assertEqual(0, waiting.returncode, waiting.stderr)
                self.assertEqual([], json.loads(waiting.stdout)["ready"])
                value["approved_gates"].append("visual_approved:settings@" + fingerprint)
                current.write_text(json.dumps(value), encoding="utf-8")
                ready = invoke("lib/task_graph_cli.py", "ready", "--input", current)
                self.assertEqual(0, ready.returncode, ready.stderr)
                self.assertEqual(["web"], json.loads(ready.stdout)["ready"])
                (prototype / "prototype.css").write_text(PROTOTYPE_CSS + "\nbody { color: red; }", encoding="utf-8")
                stale = invoke("lib/documents/validate_prototype_workspace.py", *arguments,
                               "--expect", "settings.html=" + fingerprint)
                self.assertEqual(1, stale.returncode)
                self.assertIn("fingerprint mismatch", stale.stderr)
                self.assertFalse((project / "project.yaml").exists())
                self.assertFalse((project / ".agent-workflow").exists())

    def test_detached_feedback_prepare_validate_rejects_stale_unknown_and_central_binding(self):
        """三宿主独立包消费真实模板；反馈复核只能产生交接，不能改项目权威。"""
        from tests.test_prototype_workspace import tree_snapshot

        # 同一最小项目依次消费三端载荷，不复制业务项目、用户配置或旧宿主环境。
        project = self.root / "feedback-project"
        project.mkdir()
        adapter = ".awf/project.yaml"
        plan = "docs/plans/feedback.md"
        page = "docs/standards/prototype/feedback.html"
        prototype = project / "docs/standards/prototype"
        prototype.mkdir(parents=True)
        source = project / plan
        source.parent.mkdir(parents=True)
        source.write_text("# 反馈需求\n\nREQ-001：查看当前状态。\n", encoding="utf-8")

        for host, root in self.installed.items():
            with self.subTest(host=host):
                base = ["bash", str(root / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                        str(root / "plugins/source_pack.py")]

                def invoke(*arguments):
                    return subprocess.run([*base, *map(str, arguments)], cwd=project,
                                          env=isolated_environment(self.root / "feedback-context"),
                                          capture_output=True, text=True, timeout=20)

                def helper(*arguments):
                    return invoke("helper", "--project", project, *arguments)

                applied = helper("plugins/project_context.py", "apply", "--adapter", adapter)
                self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
                # 必须由物理安装的 resource 解析器取得模板及摘要，项目同名路径
                # 和源码树不能让独立载荷缺失时偶然通过。复制仅构成这次最小项目。
                for name in ("page.html", "prototype.css"):
                    relative = "templates/prototype/" + name
                    located = invoke("resource", relative)
                    self.assertEqual(0, located.returncode, located.stdout + located.stderr)
                    resource = json.loads(located.stdout)
                    self.assertEqual(str(root / relative), resource["path"])
                    body = Path(resource["path"]).read_bytes()
                    self.assertEqual(hashlib.sha256(body).hexdigest(), resource["sha256"])
                    (prototype / ("feedback.html" if name == "page.html" else name)).write_bytes(body)
                # 旧索引只是导航来源，不要求其采用当前通用壳结构，更不执行其脚本。
                # 别名和hash保留原语义；新项目实际只需上方具体页面和CSS。
                (prototype / "index.html").write_text(
                    '<!doctype html><html><body><details open><summary>业务分组</summary>'
                    '<a href="./feedback.html#state">原业务反馈页</a></details></body></html>', encoding="utf-8")
                concrete = project / page
                html = concrete.read_text(encoding="utf-8").replace(
                    'data-prototype-plan-source=""', 'data-prototype-plan-source="' + plan + '"')
                html = html.replace('<span>尚未绑定需求文档</span>',
                    '<a data-prototype-document="markdown" href="../../plans/feedback.md" '
                    'target="_blank" rel="noopener">需求</a>')
                html = html.replace('<div class="prototype-placeholder">',
                                    '<div id="feedback-state" class="prototype-placeholder">')
                concrete.write_text(html, encoding="utf-8")
                before = tree_snapshot(project)
                command = ("lib/documents/prototype_feedback_cli.py", "prepare", "--root", project,
                           "--adapter", adapter, "--plan", plan, "--request-id", "feedback-packaged",
                           "--pages", page, "--data-dir", self.root / "review-data")
                prepared = helper(*command)
                self.assertEqual(0, prepared.returncode, prepared.stdout + prepared.stderr)
                ready = json.loads(prepared.stdout)
                self.assertEqual("ready", ready["status"])
                self.assertEqual(before, tree_snapshot(project))
                self.assertEqual(adapter, ready["context"]["adapter"])
                self.assertEqual(plan, ready["context"]["plan_source"])
                self.assertEqual([page], [item["path"] for item in ready["context"]["pages"]])
                self.assertEqual(["REQ-001"], [item["id"] for item in ready["context"]["requirements"]])
                fragment = parse_qs(urlsplit(ready["review_url"]).fragment)
                self.assertEqual({"page"}, set(fragment))
                self.assertEqual(["feedback.html"], fragment["page"])
                bundle = Path(ready["bundle_path"])
                self.assertTrue(bundle.is_relative_to(self.root / "review-data"))
                self.assertEqual(2, ready["context"]["schema_version"])
                self.assertEqual((root / "product/PLUGIN_VERSION").read_text().strip(),
                                 ready["context"]["tool"]["version"])
                self.assertEqual((root / "lib/documents/prototype_review.py").read_bytes(),
                                 (PACK / "lib/documents/prototype_review.py").read_bytes())
                derived = (bundle / "project" / page).read_text(encoding="utf-8")
                self.assertEqual(1, derived.count('data-prototype-review-bridge'))
                self.assertNotIn('data-prototype-review-bridge', concrete.read_text(encoding="utf-8"))
                for name in ("index.html", "workspace.css", "workspace.js", "feedback.css", "feedback.js", "page-shell.js"):
                    self.assertEqual((root / "templates/prototype" / name).read_bytes(),
                                     (bundle / "tool" / name).read_bytes())
                    if name != "index.html":
                        self.assertFalse((prototype / name).exists())
                repeated = helper(*command)
                self.assertEqual(0, repeated.returncode, repeated.stdout + repeated.stderr)
                self.assertTrue(json.loads(repeated.stdout)["reused"])
                self.assertEqual(ready["review_url"], json.loads(repeated.stdout)["review_url"])

                # JSON 仅是显式交接输入。以整树字节/节点快照证明 validate 没有
                # 写需求、HTML、adapter、批准或新 spec/sidecar；错误输入也不能写。
                item = {"id": "feedback-1", "page": page, "target_id": "feedback-state",
                        "kind": "suggestion", "message": "建议说明当前状态 approved", "req_ids": ["REQ-001"],
                        "comparison": {"before_text": "产品页面内容", "after_text": "当前状态"}}
                feedback = {"schema_version": 2, "context": ready["context"], "items": [item]}
                exported = self.root / "feedback-input.json"

                def validate(value):
                    exported.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                    original = exported.read_bytes()
                    result = helper("lib/documents/prototype_feedback_cli.py", "validate",
                                    "--root", project, "--adapter", adapter, "--input", exported,
                                    "--data-dir", self.root / "review-data")
                    self.assertEqual(original, exported.read_bytes())
                    return result

                validated = validate(feedback)
                self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)
                current = json.loads(validated.stdout)
                self.assertEqual("current", current["status"])
                self.assertEqual([{"page": page, "target_id": "feedback-state", "items": [item]}], current["changes"])
                self.assertEqual(before, tree_snapshot(project))
                unknown = json.loads(json.dumps(feedback))
                unknown["items"][0]["approved"] = True
                rejected = validate(unknown)
                self.assertNotEqual(0, rejected.returncode, rejected.stdout + rejected.stderr)
                self.assertEqual("error", json.loads(rejected.stdout)["status"])
                self.assertIn("未知字段", json.loads(rejected.stdout)["error"]["message"])
                self.assertEqual(before, tree_snapshot(project))
                # 需求字节变化即使没有改变页面画面依赖，也必须让旧反馈失败。
                original_plan = source.read_bytes()
                source.write_bytes(original_plan + "\n修订需求字节。\n".encode())
                changed = tree_snapshot(project)
                stale = validate(feedback)
                self.assertNotEqual(0, stale.returncode, stale.stdout + stale.stderr)
                self.assertEqual("error", json.loads(stale.stdout)["status"])
                self.assertEqual(changed, tree_snapshot(project))
                source.write_bytes(original_plan)
                # 原型公共依赖变化由既有算法重算，不能只信任 context 声明。
                css = prototype / "prototype.css"
                original_css = css.read_bytes()
                css.write_bytes(original_css + b"\nbody { color: red; }\n")
                changed = tree_snapshot(project)
                stale = validate(feedback)
                self.assertNotEqual(0, stale.returncode, stale.stdout + stale.stderr)
                self.assertEqual("error", json.loads(stale.stdout)["status"])
                self.assertEqual(changed, tree_snapshot(project))
                css.write_bytes(original_css)
                marker = project / ".agent-workflow/runtime.json"
                marker.parent.mkdir(exist_ok=True)
                marker.write_text("{}\n", encoding="utf-8")
                central = helper(*command)
                self.assertNotEqual(0, central.returncode)
                self.assertIn("original pinned runtime", central.stderr)
                marker.unlink()
                marker.parent.rmdir()
                self.assertFalse((project / "project.yaml").exists())

    def test_packaged_interpreter_selector_locates_an_existing_supported_python(self):
        project = self.root / "interpreter-project"
        project.mkdir()
        for host, root in self.installed.items():
            with self.subTest(host=host):
                result = subprocess.run(["bash", str(root / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                                         str(root / "plugins/source_pack.py"), "resource", "product/WORKFLOW.md"],
                                        cwd=project, env=isolated_environment(self.root / "home"),
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(str(root / "product/WORKFLOW.md"), json.loads(result.stdout)["path"])
                self.assertEqual([], list(project.iterdir()))

    @unittest.skipUnless(shutil.which("claude"), "Claude Code CLI unavailable; actual host validation pending")
    def test_claude_native_plugin_validator_without_model_task(self):
        home = self.root / "claude-validator-home"
        home.mkdir(exist_ok=True)
        result = subprocess.run([shutil.which("claude"), "plugin", "validate", str(self.installed["claude"])],
                                cwd=home, env=isolated_environment(home), capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("claude"), "Claude Code CLI unavailable; actual inventory discovery pending")
    def test_claude_native_inventory_discovers_skills_workers_and_main_entry(self):
        home = self.root / "claude-inventory-home"
        home.mkdir()
        result = subprocess.run([shutil.which("claude"), "--plugin-dir", str(self.installed["claude"]),
                                 "plugin", "details", "xy-workflow"],
                                cwd=home, env=isolated_environment(home), capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Skills (13)", result.stdout)
        self.assertIn("xy-config", result.stdout)
        self.assertIn("Agents (8)", result.stdout)
        self.assertIn("pm", result.stdout)
        self.assertIn("MCP servers (0)", result.stdout)

    def test_codex_native_local_marketplace_requires_supported_isolation(self):
        # 当前CLI没有--plugin-dir式临时加载入口；不能为测试覆盖宿主根变量，
        # 也不能将插件写入用户真实cache。因此该原生验收条件明确留为未覆盖。
        self.skipTest("native Codex isolation requires an official temporary-plugin entry; HOME/CODEX_HOME overrides are forbidden")

    def test_modified_canonical_source_is_rejected_before_helper_runs(self):
        root = self.root / "tampered"
        shutil.copytree(self.installed["codex"], root)
        (root / "product/WORKFLOW.md").write_bytes(b"changed authority\n")
        result = subprocess.run([sys.executable, "-B", str(root / "plugins/source_pack.py"),
                                 "resource", "product/WORKFLOW.md"],
                                cwd=self.root, env=isolated_environment(self.root / "home"),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(2, result.returncode)
        self.assertIn("digest mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
