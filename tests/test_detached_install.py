from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.install import install_workflow
from lib.install import project_paths


PACK = Path(__file__).resolve().parents[1]


class DetachedInstallTest(unittest.TestCase):
    def test_existing_path_with_apostrophe_is_not_reparsed(self) -> None:
        """参数形式的真实路径允许文件夹名含单引号。"""

        with tempfile.TemporaryDirectory(prefix="workflow-quoted-path-") as raw:
            project = Path(raw) / "Owner's Project"
            project.mkdir()
            self.assertEqual(project.resolve(), project_paths.target_path(str(project), PACK))

    def test_dragged_path_preserves_escaped_trailing_space(self) -> None:
        """终端拖入路径时不能把文件夹名末尾的空格裁掉。"""

        with tempfile.TemporaryDirectory(prefix="workflow-trailing-space-") as raw:
            project = Path(raw) / "Project "
            project.mkdir()
            dragged = str(project).replace(" ", "\\ ")
            self.assertEqual(project.resolve(), project_paths.target_path(dragged, PACK))

    def test_old_in_project_pack_requires_explicit_removal(self) -> None:
        """新入口拒绝和旧项目内安装包形成双工作流。"""

        with tempfile.TemporaryDirectory(prefix="workflow-old-pack-") as raw:
            project = Path(raw) / "project"
            old_pack = project / "agent_workflow"
            (old_pack / "product").mkdir(parents=True)
            (old_pack / "setup_all.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            (old_pack / "product/WORKFLOW.md").write_text("old\n", encoding="utf-8")
            from manager import runtime_service
            with self.assertRaisesRegex(ValueError, "旧工作流目录"):
                runtime_service.preview(Path(raw).resolve() / "state", project.resolve(), "enable", source_root=PACK)
            self.assertFalse((project / ".agent-workflow").exists())


    def test_terminal_drag_install_uses_central_runtime(self) -> None:
        """真实公共交互入口生成薄桥和中央链接；可删除来源的执行证据由桥测试复用。"""
        from lib import runtime_store
        from manager import runtime_service
        with tempfile.TemporaryDirectory(prefix="workflow-central-install-") as raw:
            workspace = Path(raw).resolve()
            project = workspace / "Project With Spaces"
            state = workspace / "state"
            project.mkdir()
            source_config = (PACK / "project.yaml").read_bytes()
            dragged = str(project).replace(" ", "\\ ") + "\n"
            result = subprocess.run(["bash", str(PACK / "install.sh"), "--state-dir", str(state)],
                                    input=dragged, text=True, capture_output=True,
                                    cwd=workspace, timeout=60)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            runtime = project / ".agent-workflow"
            self.assertTrue((runtime / "runtime.py").is_file())
            self.assertFalse((runtime / "product").exists())
            self.assertFalse((runtime / ".install-manifest.json").exists())
            self.assertEqual(source_config, (PACK / "project.yaml").read_bytes())
            self.assertIn('project_name: "Project With Spaces"', (runtime / "project.yaml").read_text())
            self.assertTrue((project / ".agents/skills/xy-workflow").is_symlink())
            checked = runtime_service.status(state, project)
            self.assertTrue(checked["enabled"])
            core = runtime_store.load_core(checked["runtime_binding"], state)
            self.assertEqual((PACK / "product/WORKFLOW.md").read_bytes(),
                             runtime_store.read_core_source(core, "product/WORKFLOW.md"))


    def test_unsupported_skill_backend_rejects_public_entry_before_writes(self):
        from lib import platform_fs
        temporary = tempfile.TemporaryDirectory(prefix="workflow-backend-boundary-")
        self.addCleanup(temporary.cleanup)
        workspace = Path(temporary.name).resolve()
        project = workspace / "unsupported-project"
        project.mkdir()
        state = workspace / "unsupported-state"
        # 只证明当前真实入口的能力拒绝，不把 POSIX 夹具冒称 Windows 原生验收。
        with patch.object(platform_fs.os, "supports_dir_fd", set()), self.assertRaisesRegex(ValueError, "受管 Skill 软链"):
            install_workflow.install_central(project, PACK, state=state)
        # 直接覆盖公共入口实际判断的 Windows 分支；此处只模拟能力拒绝，不
        # 声称 Windows 原生安装验收。中央模块导入前即失败，旧打包入口也能
        # 给出相同明确诊断，不会先触发缺模块异常或进入任何发布流程。
        with patch.object(platform_fs.os, "name", "nt"), patch.object(install_workflow, "_central_imports") as imports:
            with self.assertRaisesRegex(ValueError, "受管 Skill 软链"):
                install_workflow.install_central(project, PACK, state=state)
            imports.assert_not_called()
        self.assertEqual([], list(project.iterdir()))
        self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
