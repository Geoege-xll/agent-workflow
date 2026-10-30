"""验证先原型后源码的角色生命周期；所有安装和刷新只作用于临时项目。"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.project_discovery import discover_project


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
            manifest = project / "go.mod"
            source = "module example.test/backend\n\ngo 1.24\n"
            manifest.write_text(source, encoding="utf-8")
            # install.sh 已包含安装后的聚合 --check；成功即获得完整验收证据，
            # 此处不再追加一轮相同检查，避免测试本身重复安装和验证。
            installed = subprocess.run(["bash", str(PACK / "install.sh"), str(project)],
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
            installed = subprocess.run(["bash", str(PACK / "install.sh"), str(project)],
                                       capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(0, installed.returncode, (installed.stdout + installed.stderr)[-5000:])
            runtime = project / ".agent-workflow"
            config_before = (runtime / "project.yaml").read_bytes()
            docs_before = {p.relative_to(project): p.read_bytes()
                           for p in (project / "docs").rglob("*") if p.is_file()}

            def check(host):
                return subprocess.run(
                    ["bash", str(runtime / "lib/python_runtime.sh"),
                     str(runtime / "lib/project_profile_cli.py"), "check-roles", host,
                     str(runtime), str(project)],
                    capture_output=True, text=True, check=False, timeout=15,
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

            # 使用既有聚合 setup 刷新：三宿主恢复同一角色集合，原文档与源码保留。
            refreshed = subprocess.run(["bash", str(runtime / "setup_all.sh")],
                                       capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(0, refreshed.returncode, refreshed.stdout + refreshed.stderr)
            for host, (directory, suffix) in ROLE_LOCATIONS.items():
                with self.subTest(host=host, phase="desktop"):
                    self.assertEqual({"xy-uiux", "xy-qa", "xy-desktop"},
                                     {p.stem for p in (project / directory).glob(f"*{suffix}")})
                    result = check(host)
                    self.assertEqual(0, result.returncode, result.stderr)
            verified = subprocess.run(["bash", str(runtime / "setup_all.sh"), "--check"],
                                      capture_output=True, text=True, check=False, timeout=120)
            self.assertEqual(0, verified.returncode, verified.stdout + verified.stderr)
            self.assertEqual(source, (module / "package.json").read_text())
            self.assertEqual(config_before, (runtime / "project.yaml").read_bytes())
            self.assertEqual(docs_before, {p.relative_to(project): p.read_bytes()
                             for p in (project / "docs").rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
