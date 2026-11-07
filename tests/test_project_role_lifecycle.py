"""验证先原型后源码的角色生命周期；所有安装和刷新只作用于临时项目。"""

from __future__ import annotations

import subprocess
import json
import os
import tempfile
import unittest
from pathlib import Path

from lib.project.project_discovery import discover_project


PACK = Path(__file__).resolve().parents[1]
ROLE_LOCATIONS = {"codex": (".codex/agents", ".toml"),
                  "claude": (".claude/agents", ".md"),
                  "antigravity": (".agents/agents", ".md")}


class ProjectRoleLifecycleTest(unittest.TestCase):
    def test_backend_install_passes_aggregate_acceptance_without_prototype(self):
        """真实首装同时验证三平台：基础 UI 角色不能让纯后端验收要求原型目录。"""
        with tempfile.TemporaryDirectory(prefix="workflow-backend-install-") as raw:
            project = Path(raw).resolve() / "Backend Only"
            project.mkdir()
            state = project.parent / "state"
            manifest = project / "go.mod"
            source = "module example.test/backend\n\ngo 1.24\n"
            manifest.write_text(source, encoding="utf-8")
            # 中央安装返回前会真实消费固定 core 并核对受管资源；角色集合和业务
            # 文件仍在下面逐项检查，不再调用项目中已取消的复制 setup 入口。
            # 真实安装只写此用例唯一的中央状态，不读取或创建用户的默认内容库。
            installed = subprocess.run(["bash", str(PACK / "install.sh"), str(project), "--state-dir", str(state)],
                                       capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(0, installed.returncode, (installed.stdout + installed.stderr)[-5000:])
            self.assertFalse((project / "docs/standards/prototype").exists())
            self.assertFalse((project / "docs/standards/DESIGN_FOUNDATIONS.md").exists())
            self.assertFalse((project / "docs/standards/DESIGN_COMPONENTS.md").exists())
            self.assertTrue((project / "docs/PROJECT.md").is_file())
            self.assertEqual(source, manifest.read_text(encoding="utf-8"))
            for host, (directory, suffix) in ROLE_LOCATIONS.items():
                with self.subTest(host=host):
                    self.assertEqual({"xy-backend", "xy-uiux", "xy-qa"},
                                     {p.stem for p in (project / directory).glob(f"*{suffix}")})

    def test_prototype_first_and_backend_keep_roles_separate_from_ui_work(self):
        with tempfile.TemporaryDirectory(prefix="workflow-prototype-role-") as raw:
            root = Path(raw).resolve()
            # 空项目和只有独立 HTML 的原型项目均须能派发设计，不虚构实现模块。
            for prototype in (False, True):
                if prototype:
                    page = root / "docs/standards/prototype/knowledge.html"
                    page.parent.mkdir(parents=True)
                    page.write_text("<!doctype html><title>知识库候选</title>")
                profile = discover_project(root)
                self.assertEqual((), profile.modules)
                self.assertEqual({"xy-uiux", "xy-qa"}, set(profile.enabled_roles))
                self.assertTrue(profile.design_scaffold_required)
            (root / "go.mod").write_text("module example.test/backend\n\ngo 1.24\n")
            profile = discover_project(root)
            self.assertEqual({"xy-backend", "xy-uiux", "xy-qa"}, set(profile.enabled_roles))
            self.assertFalse(profile.design_scaffold_required)

    def test_three_host_install_then_added_desktop_module_detects_and_refreshes_roles(self):
        with tempfile.TemporaryDirectory(prefix="workflow-role-lifecycle-") as raw:
            project = Path(raw).resolve() / "Prototype First"
            project.mkdir()
            state = project.parent / "state"
            env = {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(state)}
            installed = subprocess.run(["bash", str(PACK / "install.sh"), str(project), "--state-dir", str(state)],
                                       capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(0, installed.returncode, (installed.stdout + installed.stderr)[-5000:])
            runtime = project / ".agent-workflow"
            binding = json.loads((runtime / "runtime.json").read_bytes())["runtime_binding"]
            config_before = (runtime / "project.yaml").read_bytes()
            docs_before = {p.relative_to(project): p.read_bytes()
                           for p in (project / "docs").rglob("*") if p.is_file()}

            def check(host):
                return subprocess.run(
                    ["bash", str(runtime / "lib/python_runtime.sh"),
                     "-B", "-X", "utf8", str(runtime / "runtime.py"), "--binding", json.dumps(binding),
                     "helper", "lib/project/project_profile_cli.py", "check-roles", host,
                     str(runtime), str(project)],
                    cwd=project, env=env, capture_output=True, text=True, check=False, timeout=15,
                )

            for host, (directory, suffix) in ROLE_LOCATIONS.items():
                with self.subTest(host=host, phase="prototype"):
                    roles = {p.stem for p in (project / directory).glob(f"*{suffix}")}
                    self.assertEqual({"xy-uiux", "xy-qa"}, roles)
                    result = check(host)
                    self.assertEqual(0, result.returncode, result.stderr)
            # 重现 kf：安装后才加入 Tauri/React 源码。资源检查只读报告缺少实现角色。
            module = project / "llmwiki"
            module.mkdir()
            source = '{"dependencies":{"@tauri-apps/api":"2","react":"19"}}\n'
            (module / "package.json").write_text(source)
            # Tauri API 依赖本身不等于客户端；真实宿主清单提供桌面模块判定依据。
            tauri = module / "src-tauri"
            tauri.mkdir()
            (tauri / "tauri.conf.json").write_text('{"productName":"Fixture","version":"0.1.0"}')
            (tauri / "Cargo.toml").write_text('[package]\nname="fixture"\nversion="0.1.0"\n'
                                            '[dependencies]\ntauri="2"\n')
            for host in ROLE_LOCATIONS:
                result = check(host)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("xy-desktop", result.stderr)
            self.assertEqual(config_before, (runtime / "project.yaml").read_bytes())
            self.assertEqual(docs_before, {p.relative_to(project): p.read_bytes()
                             for p in (project / "docs").rglob("*") if p.is_file()})

            # 复用真实中央 enable 刷新当前项目画像；薄项目不复制 setup 或 helper。
            refreshed = subprocess.run(["bash", str(PACK / "install.sh"), str(project), "--state-dir", str(state)],
                                       capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(0, refreshed.returncode, refreshed.stdout + refreshed.stderr)
            for host, (directory, suffix) in ROLE_LOCATIONS.items():
                with self.subTest(host=host, phase="desktop"):
                    self.assertEqual({"xy-uiux", "xy-qa", "xy-desktop"},
                                     {p.stem for p in (project / directory).glob(f"*{suffix}")})
                    result = check(host)
                    self.assertEqual(0, result.returncode, result.stderr)
            verified = subprocess.run(["bash", str(runtime / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                                       str(runtime / "runtime.py"), "--binding", json.dumps(binding), "check"],
                                      cwd=project, env=env, capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(0, verified.returncode, verified.stdout + verified.stderr)
            self.assertEqual(source, (module / "package.json").read_text())
            self.assertEqual(config_before, (runtime / "project.yaml").read_bytes())
            self.assertEqual(docs_before, {p.relative_to(project): p.read_bytes()
                             for p in (project / "docs").rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
