"""维护入口的真实插件载荷合同；不把静态投影冒充模型路由前向验收。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from lib.skills.role_skills import CORE_SKILLS, ROLE_SKILLS, SELECTED_SKILLS
from tests.test_plugin_delivery import PACK, builder, isolated_environment


class PluginMaintenanceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="plugin-maintenance-")
        cls.root = Path(cls.temporary.name).resolve()
        cls.installed = {}
        for host in builder.HOSTS:
            archive = builder.build(PACK, cls.root / "archives", host)
            target = cls.root / host
            target.mkdir()
            with zipfile.ZipFile(archive) as package:
                package.extractall(target)
            cls.installed[host] = target

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_discoverable_skills_keep_eight_core_and_unchanged_worker_preloads(self):
        # Grill Me 已移入四个精选 adapter；核心表精确保留八项，维护入口独立发现。
        self.assertEqual(8, len(CORE_SKILLS))
        self.assertNotIn("xy-config", CORE_SKILLS)
        for role, skills in ROLE_SKILLS.items():
            self.assertNotIn("xy-config", skills, role)
        for host, root in self.installed.items():
            with self.subTest(host=host):
                actual = {path.parent.name for path in (root / "skills").glob("*/SKILL.md")}
                self.assertEqual(set(CORE_SKILLS) | set(SELECTED_SKILLS) | {"xy-config"}, actual)
                for role in ROLE_SKILLS:
                    self.assertEqual((PACK / "roles" / (role + ".md")).read_bytes(),
                                     (root / "roles" / (role + ".md")).read_bytes())
                    if host != "codex":
                        header, _ = builder.split_frontmatter((root / "agents" / (role + ".md")).read_bytes())
                        self.assertNotIn(b"xy-config", header)

    def test_host_metadata_is_explicit_only_and_maintenance_has_no_business_envelope(self):
        original = (PACK / "plugins/maintenance/skills/xy-config/SKILL.md").read_bytes()
        for host, root in self.installed.items():
            with self.subTest(host=host):
                loaded = (root / "skills/xy-config/SKILL.md").read_bytes()
                header, body = builder.split_frontmatter(loaded)
                # 直接检查实际发现目录中的官方字段与工具授权面；不是只对源文案断言。
                self.assertNotIn(b"allowed-tools:", header)
                self.assertNotIn(b"context:", header)
                self.assertNotIn(b"agent:", header)
                self.assertNotIn(b"model:", header)
                self.assertNotIn(b"@HOST@", loaded)
                self.assertNotIn(b"@INVOCATION@", loaded)
                self.assertIn(b"--host " + host.encode(), body)
                self.assertEqual(builder.render_maintenance_skill(original, host), loaded)
                adapter = "plugins/antigravity/plugin-context.md" if host == "antigravity" else "plugins/plugin-context.md"
                self.assertNotIn((PACK / adapter).read_bytes(), body)
                policy = root / "skills/xy-config/agents/openai.yaml"
                if host == "codex":
                    self.assertEqual((PACK / "plugins/maintenance/skills/xy-config/agents/openai.yaml").read_bytes(),
                                     policy.read_bytes())
                    self.assertIn(b"policy:\n  allow_implicit_invocation: false\n", policy.read_bytes())
                    self.assertNotIn(b"disable-model-invocation:", header)
                else:
                    self.assertIn(b"disable-model-invocation: true\n", header)
                    self.assertFalse(policy.exists())

    def test_main_entries_consume_only_the_short_route_and_defer_business_authority(self):
        original = (PACK / "plugins/main-session-context.md").read_bytes()
        for host, root in self.installed.items():
            with self.subTest(host=host):
                adapter = "plugins/antigravity/plugin-context.md" if host == "antigravity" else "plugins/plugin-context.md"
                expected = builder.render_main_context(original, host, adapter)
                self.assertEqual(expected, (root / "main-session-context.md").read_bytes())
                self.assertEqual(original, (root / "plugins/main-session-context.md").read_bytes())
                if host == "claude":
                    entry = (root / "agents/pm.md").read_bytes()
                elif host == "antigravity":
                    entry = (root / "rules/AGENTS.md").read_bytes()
                else:
                    # 在摘除业务权威的临时副本中运行真实 Hook，证明其载入路径只需短
                    # 主会话适配。它只提醒分支，不执行业务或维护命令。
                    authorities = [root / "product/WORKFLOW.md", root / "skills/xy-workflow/SKILL.md"]
                    for path in authorities:
                        path.rename(path.with_suffix(".temporarily-absent"))
                    try:
                        result = subprocess.run([sys.executable, "-B", str(root / "hooks/session_start.py")],
                            cwd=self.root, env=isolated_environment(self.root / "hook-scope"),
                            input='{"prompt":"实现 xy-config status"}', capture_output=True, text=True, timeout=10)
                    finally:
                        for path in authorities:
                            path.with_suffix(".temporarily-absent").rename(path)
                    self.assertEqual(0, result.returncode, result.stderr)
                    entry = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"].encode()
                self.assertIn(expected, entry)
                self.assertNotIn((PACK / adapter).read_bytes(), entry)
                # 原业务权威逐字节保留且仍可解析，普通业务调用继续消费既有门禁。
                self.assertEqual((PACK / "product/WORKFLOW.md").read_bytes(),
                                 (root / "product/WORKFLOW.md").read_bytes())

    def test_component_payload_is_a_closed_thin_whitelist_with_provenance(self):
        expected = {"plugins/maintenance/" + name for name in
                    ("launcher.sh", "launcher.py", "component_store.py", "component.json")}
        for host, root in self.installed.items():
            with self.subTest(host=host):
                metadata = json.loads((root / "sources.json").read_bytes())
                actual = {path.relative_to(root).as_posix() for path in (root / "plugins/maintenance").iterdir()
                          if path.is_file()}
                self.assertEqual(expected, actual)
                for relative in expected:
                    content = (root / relative).read_bytes()
                    self.assertEqual((PACK / relative).read_bytes(), content)
                    self.assertEqual(hashlib.sha256(content).hexdigest(), metadata["source_files"][relative])
                self.assertFalse((root / "native_config").exists())
                self.assertEqual([], list(root.rglob("*.zip")))
                self.assertFalse(any(path.name in {"mcp.json", ".mcp.json", "mcp_config.json"}
                                     for path in root.rglob("*")))

    def test_detached_packaged_readonly_commands_use_the_real_parser_without_writes_or_start(self):
        # 显式 API 注入只用于短命测试根；生产 Skill 不传这些隔离路径。真实打包
        # launcher 与 component_store 离开源码后运行，任何子进程调用都会立即失败。
        code = '''import json, runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1])
def forbidden(*args, **kwargs):
    raise AssertionError("只读命令不能启动独立组件")
report, status = module["run"](sys.argv[3:], component_root=Path(sys.argv[2]), invoke=forbidden)
print(json.dumps({"report": report, "exit": status}))
'''
        for host, root in self.installed.items():
            for action in ("status", "doctor"):
                with self.subTest(host=host, action=action):
                    absent = self.root / ("absent-component-" + host + "-" + action)
                    result = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                        str(root / "plugins/maintenance/launcher.py"), str(absent), action, "--host", host],
                        cwd=self.root, env=isolated_environment(self.root / "readonly-home"),
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    value = json.loads(result.stdout)
                    self.assertEqual(2, value["exit"])
                    self.assertEqual("preparation_required", value["report"]["state"])
                    self.assertEqual({"host": host, "scope": "global", "project": None}, value["report"]["location"])
                    self.assertIsNone(value["report"]["launch_file"])
                    self.assertFalse(absent.exists())

    def test_antigravity_budget_includes_maintenance_and_rejects_its_own_overflow(self):
        root = self.installed["antigravity"]
        actual = list((root / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(CORE_SKILLS | SELECTED_SKILLS) + 1, len(actual))
        for path in actual:
            self.assertLessEqual(len(builder.split_frontmatter(path.read_bytes())[1].strip()), 24_000)
        read_source = builder.read_source
        def oversized(source, relative):
            body = read_source(source, relative)
            return body + ("中" * 8_001).encode() if relative == builder.MAINTENANCE_SKILL else body
        output = self.root / "oversized-maintenance"
        with mock.patch.object(builder, "read_source", side_effect=oversized):
            with self.assertRaisesRegex(ValueError, "skills/xy-config/SKILL.md"):
                builder.build(PACK, output, "antigravity")
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
