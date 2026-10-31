from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACK = Path(__file__).resolve().parents[1]
HELPER = PACK / "lib/ensure_project_id.py"


def load_helper():
    # 以真实包名加载，沿用生产代码的相对导入；不能伪装为单文件而漏掉平台文件系统依赖。
    spec = importlib.util.spec_from_file_location("lib.ensure_project_id", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectIdInitializationTest(unittest.TestCase):
    def make_project(
        self, name: str = "My Project"
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory(prefix="project-id-init-")
        project = Path(temporary.name) / name
        pack = project / "agent_workflow"
        pack.mkdir(parents=True)
        config = pack / "project.yaml"
        shutil.copy2(PACK / "templates/project.yaml.example", config)
        return temporary, project, config

    def run_helper(
        self, config: Path, project: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HELPER), str(config), str(project)],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )

    def test_shared_initializer_exists(self) -> None:
        self.assertTrue(HELPER.is_file(), "missing shared project ID initializer")

    def test_project_directory_names_are_derived_as_stable_slugs(self) -> None:
        derive = getattr(load_helper(), "derive_project_id", None)
        self.assertIsNotNone(derive, "initializer must expose derive_project_id")
        if derive is None:
            return
        cases = {
            "My Project": "my-project",
            "OmniMind": "omnimind",
            "wechat_explorer": "wechat-explorer",
            "  Many---Separators__Here  ": "many-separators-here",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(expected, derive(name))

        unicode_name = "我的项目"
        expected = "project-" + hashlib.sha256(
            unicode_name.encode("utf-8")
        ).hexdigest()[:12]
        self.assertEqual(expected, derive(unicode_name))

    def test_placeholder_is_atomically_initialized_once_and_mode_is_preserved(self) -> None:
        temporary, project, config = self.make_project()
        self.addCleanup(temporary.cleanup)
        config.chmod(0o640)

        first = self.run_helper(config, project)

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("[OK] memory.project_id initialized to my-project", first.stdout)
        body = config.read_text(encoding="utf-8")
        self.assertIn("project_id: my-project", body)
        self.assertNotIn("replace-with-unique-project-id", body)
        self.assertEqual(1, body.count("project_id:"))
        self.assertEqual(0o640, stat.S_IMODE(config.stat().st_mode))

        before = config.read_bytes()
        second = self.run_helper(config, project)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(before, config.read_bytes())
        self.assertEqual("", second.stdout)

    def test_configured_project_id_is_never_changed(self) -> None:
        temporary, project, config = self.make_project()
        self.addCleanup(temporary.cleanup)
        original = config.read_text(encoding="utf-8").replace(
            "replace-with-unique-project-id", "custom-project-id", 1
        )
        config.write_text(original, encoding="utf-8")

        result = self.run_helper(config, project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(original.encode("utf-8"), config.read_bytes())
        self.assertEqual("", result.stdout)

    def test_unsafe_or_invalid_project_yaml_is_rejected_without_traceback(self) -> None:
        for case in ("symlink", "hardlink", "directory", "invalid-utf8"):
            with self.subTest(case=case):
                temporary, project, config = self.make_project(case)
                self.addCleanup(temporary.cleanup)
                if case == "symlink":
                    real = config.with_name("real-project.yaml")
                    config.replace(real)
                    config.symlink_to(real.name)
                elif case == "hardlink":
                    real = config.with_name("real-project.yaml")
                    config.replace(real)
                    os.link(real, config)
                elif case == "directory":
                    config.unlink()
                    config.mkdir()
                else:
                    config.write_bytes(b"memory:\n  project_id: \xff\xfe\n")
                before = sorted(
                    (path.relative_to(project).as_posix(), path.is_symlink())
                    for path in project.rglob("*")
                )

                result = self.run_helper(config, project)

                self.assertNotEqual(result.returncode, 0)
                combined = result.stdout + result.stderr
                self.assertIn("[ERROR]", combined)
                self.assertNotIn("Traceback", combined)
                after = sorted(
                    (path.relative_to(project).as_posix(), path.is_symlink())
                    for path in project.rglob("*")
                )
                self.assertEqual(before, after)


class ProjectIdSetupIntegrationTest(unittest.TestCase):
    def make_fixture(
        self, name: str = "Auto Project"
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory(prefix="project-id-setup-")
        project = Path(temporary.name) / name
        pack = project / "agent_workflow"
        project.mkdir()
        shutil.copytree(
            PACK,
            pack,
            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
            symlinks=True,
        )
        shutil.copy2(pack / "templates/project.yaml.example", pack / "project.yaml")
        return temporary, project, pack

    @staticmethod
    def run_script(
        project: Path, script: str, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", f"agent_workflow/{script}", *arguments],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )

    def test_each_normal_setup_entrypoint_initializes_the_placeholder(self) -> None:
        for script in (
            "setup_codex.sh",
            "setup_claude.sh",
            "setup_antigravity.sh",
            "setup_all.sh",
        ):
            with self.subTest(script=script):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)

                result = self.run_script(project, script)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                body = (pack / "project.yaml").read_text(encoding="utf-8")
                self.assertIn("project_id: auto-project", body)
                self.assertNotIn("replace-with-unique-project-id", body)

    def test_setup_all_initializes_once_and_is_repeatable(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        config = pack / "project.yaml"

        first = self.run_script(project, "setup_all.sh")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        initialized = config.read_bytes()
        second = self.run_script(project, "setup_all.sh")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(initialized, config.read_bytes())
        check = self.run_script(project, "setup_all.sh", "--check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_read_only_modes_do_not_initialize_the_placeholder(self) -> None:
        invocations = (
            ("setup_codex.sh", "--preflight", 0),
            ("setup_claude.sh", "--preflight", 0),
            ("setup_antigravity.sh", "--preflight", 0),
            ("setup_codex.sh", "--check", 1),
            ("setup_claude.sh", "--check", 1),
            ("setup_antigravity.sh", "--check", 1),
            ("setup_all.sh", "--check", 1),
        )
        for script, argument, expected_returncode in invocations:
            with self.subTest(script=script, argument=argument):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                config = pack / "project.yaml"
                before = config.read_bytes()

                result = self.run_script(project, script, argument)

                self.assertEqual(
                    expected_returncode,
                    result.returncode,
                    result.stdout + result.stderr,
                )
                self.assertEqual(before, config.read_bytes())
                self.assertEqual(
                    ["agent_workflow"], sorted(path.name for path in project.iterdir())
                )

    def test_readme_documents_automatic_and_read_only_behavior(self) -> None:
        readme = (PACK / "README.md").read_text(encoding="utf-8")
        self.assertIn("automatically derives `memory.project_id`", readme)
        self.assertIn("`--check` and `--preflight` never initialize", readme)


if __name__ == "__main__":
    unittest.main()
