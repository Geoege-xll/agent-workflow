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
HELPER = PACK / "lib/project/ensure_project_id.py"


def load_helper():
    # 以真实包名加载，沿用生产代码的相对导入；不能伪装为单文件而漏掉平台文件系统依赖。
    spec = importlib.util.spec_from_file_location("lib.project.ensure_project_id", HELPER)
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



class ProjectIdNativePublisherContractTest(unittest.TestCase):
    def test_original_native_read_is_forwarded_with_original_one_mib_policy(self):
        """真实初始化器消费原读五字段；这里只替换原生边界，不冒称 Windows。"""
        from types import SimpleNamespace
        from unittest.mock import patch
        from lib import windows_fs
        from lib.platform_fs import os as platform_os
        class NativeOs:
            name = "nt"
            # 委托产品实际façade：Windows目录flag和伪目录fd不能交给stdlib。
            def __getattr__(self, name): return getattr(platform_os, name)
        with tempfile.TemporaryDirectory(prefix="project-id-native-contract-") as raw:
            project = Path(raw).resolve() / "My Project"
            project.mkdir()
            config = project / "project.yaml"
            original = b"memory:\r\n  project_id: replace-with-unique-project-id\r\n"
            config.write_bytes(original)
            # 原像的mode/ChangeTime也沿同一后端，与生产完整身份的含义一致。
            info = platform_os.stat(config, follow_symlinks=False)
            before = dict(kind="file", payload=original, mode=stat.S_IMODE(info.st_mode), security="a" * 64,
                identity=(info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            module = load_helper()
            with patch.object(module, "os", NativeOs()), patch.object(windows_fs, "node_snapshot", return_value=before) as reading, \
                    patch.object(windows_fs, "write_regular_if_unchanged", return_value=before) as writing:
                self.assertEqual("my-project", module.initialize_project_id(config, project))
            self.assertEqual(module.MAX_CONFIG_SIZE, reading.call_args.kwargs["max_bytes"])
            self.assertEqual(before, writing.call_args.kwargs["expected"])
            self.assertEqual(b"memory:\r\n  project_id: my-project\r\n", writing.call_args.kwargs["payload"])
            self.assertEqual(module.MAX_CONFIG_SIZE, writing.call_args.kwargs["max_bytes"])
            self.assertEqual(original, config.read_bytes(), "此测试不以替身制造真实文件发布成功")


    def test_native_write_failure_preserves_public_initialization_error_and_exact_cause(self):
        """执行真实入口的异常包装合同；物理故障边界独立于NTFS资源验收。"""
        from unittest.mock import patch
        from lib import windows_fs
        from lib.platform_fs import os as platform_os
        class NativeOs:
            name = "nt"
            def __init__(self): self.opened, self.closed = [], []
            # 委托产品实际façade：Windows目录flag和伪目录fd不能交给stdlib。
            def __getattr__(self, name): return getattr(platform_os, name)
            def open(self, *args, **kwargs):
                descriptor = platform_os.open(*args, **kwargs); self.opened.append(descriptor); return descriptor
            def close(self, descriptor):
                self.closed.append(descriptor); platform_os.close(descriptor)
        with tempfile.TemporaryDirectory(prefix="project-id-native-error-") as raw:
            project = Path(raw).resolve() / "My Project"; project.mkdir()
            config = project / "project.yaml"
            original = b"memory:\n  project_id: replace-with-unique-project-id\n"
            config.write_bytes(original)
            # 使用后端实际mode/ChangeTime，避免Windows原生字段投影提前误拒。
            info = platform_os.stat(config, follow_symlinks=False)
            before = dict(kind="file", payload=original, mode=stat.S_IMODE(info.st_mode), security="a" * 64,
                identity=(info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            module = load_helper()
            for fault in ("fdopen", "write", "fsync"):
                with self.subTest(fault=fault):
                    injected = OSError("fixture public boundary " + fault)
                    backend = NativeOs()
                    with patch.object(module, "os", backend), patch.object(windows_fs, "node_snapshot", return_value=before), \
                            patch.object(windows_fs, "write_regular_if_unchanged", side_effect=injected):
                        with self.assertRaises(module.InitializationError) as caught:
                            module.initialize_project_id(config, project)
                    self.assertIs(caught.exception.__cause__, injected)
                    self.assertIn(str(injected), str(caught.exception))
                    self.assertEqual(backend.opened, backend.closed, "入口自有目录fd应逐一释放")
                    self.assertEqual(original, config.read_bytes())
                    self.assertEqual([config.name], sorted(item.name for item in project.iterdir()))



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

    def test_usage_documents_automatic_and_read_only_behavior(self) -> None:
        # 安装行为仍须公开说明，文档位置迁移不能删除初始化／只读边界的保护。
        self.assertIn("docs/usage.md", (PACK / "README.md").read_text(encoding="utf-8"))
        usage = (PACK / "docs/usage.md").read_text(encoding="utf-8")
        self.assertIn("自动派生 `memory.project_id` 并原子写入配置", usage)
        self.assertIn("已配置 ID 不覆盖", usage)
        self.assertIn("`--check` 和 `--preflight` 从不初始化", usage)


if __name__ == "__main__":
    unittest.main()
