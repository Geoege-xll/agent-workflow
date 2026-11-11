"""实际原型 CLI 的适配器选择回归，拒绝重新猜测配置或扩大项目读取边界。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_prototype_workspace import (
    PACK, PROTOTYPE_RELATIVE, bind_requirement_documents, tree_snapshot, write_valid_project,
)
from tests.test_plugin_delivery import isolated_environment


class PrototypeAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="awf-prototype-adapter-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = write_valid_project(self.root)
        bind_requirement_documents(self.project)

    def invoke(self, adapter: str | None, prototype: str | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-B", str(PACK / "lib/documents/validate_prototype_workspace.py"),
                   str(self.project), prototype or PROTOTYPE_RELATIVE.as_posix(), "--json"]
        if adapter is not None:
            command += ["--adapter", adapter]
        return subprocess.run(command, cwd=self.root, env=isolated_environment(self.root / "environment"),
                              capture_output=True, text=True, timeout=8)

    def test_only_awf_and_legacy_root_each_use_the_explicit_adapter(self) -> None:
        old = self.invoke("project.yaml")
        self.assertEqual(0, old.returncode, old.stderr)
        config = self.project / ".awf/project.yaml"
        config.parent.mkdir()
        (self.project / "project.yaml").rename(config)
        before = tree_snapshot(self.project)
        current = self.invoke(".awf/project.yaml")
        self.assertEqual(0, current.returncode, current.stderr)
        self.assertEqual(json.loads(old.stdout), json.loads(current.stdout))
        self.assertEqual(before, tree_snapshot(self.project))
        self.assertFalse((self.project / "project.yaml").exists())
        missing_selection = self.invoke(None)
        self.assertEqual(1, missing_selection.returncode)
        self.assertIn("--adapter", missing_selection.stderr)

    def test_two_adapters_and_custom_docs_follow_selection_without_precedence(self) -> None:
        config = self.project / ".awf/project.yaml"
        config.parent.mkdir()
        config.write_bytes((self.project / "project.yaml").read_bytes())
        # 两份配置刻意使用不同文档根；有效原型也分别声明自己的真实 Markdown。
        # 这样即便任意优先级碰巧通过一侧，也无法通过另一侧的正负对照。
        shutil.copytree(self.project / "docs/standards", self.project / "docs/custom/standards")
        shutil.copytree(self.project / "docs/plans", self.project / "docs/custom/plans")
        root_config = self.project / "project.yaml"
        root_config.write_text(root_config.read_text().replace("docs/", "docs/custom/"), encoding="utf-8")
        custom_page = self.project / "docs/custom/standards/prototype/settings.html"
        custom_page.write_text(custom_page.read_text().replace("docs/plans/settings.md", "docs/custom/plans/settings.md"),
                               encoding="utf-8")
        for adapter, prototype in ((".awf/project.yaml", "docs/standards/prototype"),
                                   ("project.yaml", "docs/custom/standards/prototype")):
            with self.subTest(adapter=adapter):
                good = self.invoke(adapter, prototype)
                self.assertEqual(0, good.returncode, good.stderr)
                self.assertEqual(prototype + "/settings.html", json.loads(good.stdout)["pages"][0]["path"])
        for adapter, prototype in (("project.yaml", "docs/standards/prototype"),
                                   (".awf/project.yaml", "docs/custom/standards/prototype")):
            with self.subTest(wrong_selection=adapter):
                wrong = self.invoke(adapter, prototype)
                self.assertEqual(1, wrong.returncode)
                self.assertIn("docs.standards_root", wrong.stderr)
        self.assertEqual(1, self.invoke(None).returncode)

    def test_adapter_alias_escape_symlink_and_fifo_are_rejected(self) -> None:
        config = self.project / "project.yaml"
        original = config.read_bytes()
        external = self.root / "outside.yaml"
        external.write_bytes(original)
        for adapter in ("../outside.yaml", str(external), "./project.yaml"):
            with self.subTest(adapter=adapter):
                result = self.invoke(adapter)
                self.assertEqual(1, result.returncode)
        config.unlink()
        config.symlink_to(external)
        self.assertEqual(1, self.invoke("project.yaml").returncode)
        config.unlink()
        import os
        os.mkfifo(config)
        self.assertEqual(1, self.invoke("project.yaml").returncode)

    def test_role_and_skill_commands_preserve_the_selected_adapter(self) -> None:
        """模型调用合同覆盖两个实际入口，动态包测试另核对实际 .awf 消费结果。"""
        role = (PACK / "roles/xy-uiux.md").read_text(encoding="utf-8")
        self.assertIn("validate_project_docs.py <selected-project-adapter>", role)
        self.assertIn("--adapter <selected-project-adapter>", role)
        self.assertNotIn("validate_project_docs.py .agent-workflow/project.yaml", role)
        skill = (PACK / "platforms/shared/skills/xy-prototype-verify/SKILL.md").read_text(encoding="utf-8")
        commands = [command for command in re.findall(r"```bash\n(.*?)```", skill, re.S)
                    if "validate_prototype_workspace.py" in command]
        self.assertEqual(2, len(commands))
        for command in commands:
            self.assertIn("--adapter <selected-project-adapter>", command)
