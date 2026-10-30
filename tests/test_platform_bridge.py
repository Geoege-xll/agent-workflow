"""Portable contract checks; native Windows behavior is tested separately."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK / "lib"))
import platform_fs
import platform_process
import windows_bootstrap


class ExclusivePublicationTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX hard-link publication contract")
    def test_exclusive_publish_and_concurrent_target(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, target = root / "source", root / "target"
            source.write_bytes(b"owned")
            target.write_bytes(b"user")
            with self.assertRaises(FileExistsError):
                platform_fs.publish_exclusive(source, target)
            self.assertEqual(source.read_bytes(), b"owned")
            self.assertEqual(target.read_bytes(), b"user")
            target.unlink()
            platform_fs.publish_exclusive(source, target)
            self.assertFalse(source.exists())
            self.assertEqual(target.read_bytes(), b"owned")
            self.assertEqual(target.stat().st_nlink, 1)

    def test_windows_uses_no_replace_rename_not_hardlinks(self):
        calls = []
        backend = SimpleNamespace(name="nt", rename=lambda *args: calls.append(args))
        with patch.object(platform_fs, "os", backend):
            platform_fs.publish_exclusive(Path("source"), Path("target"))
        self.assertEqual(calls, [(Path("source"), Path("target"))])

    @unittest.skipIf(os.name == "nt", "POSIX advisory project lock")
    def test_shared_install_lock_is_nonblocking_and_released(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with platform_fs.project_install_lock(root):
                with self.assertRaises(BlockingIOError):
                    with platform_fs.project_install_lock(root):
                        self.fail("concurrent project lock was accepted")
            with platform_fs.project_install_lock(root):
                pass
            self.assertEqual(list(root.iterdir()), [])


class SetupEnvironmentTest(unittest.TestCase):
    def test_posix_setup_shape_and_environment_are_unchanged(self):
        backend = SimpleNamespace(name="posix")
        runtime = Path("/tmp/workflow")
        with patch.object(platform_process, "os", backend):
            self.assertEqual(platform_process.setup_command(runtime, ("--check",)),
                             (["bash", str(runtime / "setup_all.sh"), "--check"], None))

    def test_windows_environment_changes_are_child_only(self):
        original = {"Path": "caller-path", "BASH_ENV": "user-profile", "ENV": "user-env",
                    "CDPATH": "search", "SHELLOPTS": "xtrace", "MSYS_NO_PATHCONV": "1",
                    "MSYS2_ARG_CONV_EXCL": "user-value", "KEEP": "unchanged"}
        backend = SimpleNamespace(name="nt", environ=original)
        bash = Path("/git/bin/bash.exe")
        runtime = Path("/project/.agent-workflow")
        with patch.object(platform_process, "os", backend), \
                patch.object(platform_process, "locate_bash", return_value=bash), \
                patch.object(platform_process, "git_root", return_value=Path("/git")), \
                patch.object(platform_process, "msys_path", return_value="/c/project/setup_all.sh"):
            command, child = platform_process.setup_command(runtime, ("--preflight",))
        self.assertEqual(command, [str(bash), "--noprofile", "--norc",
                                   "/c/project/setup_all.sh", "--preflight"])
        self.assertEqual(original["Path"], "caller-path")
        self.assertEqual(original["BASH_ENV"], "user-profile")
        self.assertNotIn("PATH", original)
        self.assertNotIn("BASH_ENV", child)
        self.assertNotIn("ENV", child)
        self.assertNotIn("MSYS_NO_PATHCONV", child)
        self.assertNotIn("MSYS2_ARG_CONV_EXCL", child)
        self.assertEqual(child["CDPATH"], "")
        self.assertEqual(child["KEEP"], "unchanged")
        self.assertEqual(child["AGENT_WORKFLOW_PROJECT_RUNTIME"], str(runtime))
        self.assertTrue(child["PATH"].endswith(";caller-path"))

    def test_only_explicit_local_drive_paths_become_msys_paths(self):
        path = SimpleNamespace(absolute=lambda: PureWindowsPath(r"D:\临时 项目\a&b"))
        self.assertEqual(platform_process.msys_path(path), "/d/临时 项目/a&b")
        remote = SimpleNamespace(absolute=lambda: PureWindowsPath(r"\\server\share\project"))
        with self.assertRaises(ValueError):
            platform_process.msys_path(remote)


class HostMaintenanceCliTest(unittest.TestCase):
    def test_selected_host_and_mode_reuse_existing_setup(self):
        runtime = Path(platform_process.__file__).absolute().parent.parent
        for host in ("claude", "codex", "antigravity"):
            for mode in (None, "--check", "--preflight"):
                options = (f"--only={host}",) + ((mode,) if mode else ())
                with self.subTest(host=host, mode=mode), \
                        patch("install_process.SetupRunner") as factory, \
                        patch.object(platform_process, "setup_command", return_value=(["verified-bash"], {"child": "only"})) as setup:
                    args = ["--host", host] + ([mode] if mode else [])
                    self.assertEqual(platform_process.main(args), 0)
                    setup.assert_called_once_with(runtime, options)
                    factory.assert_called_once_with(timeout=600)
                    factory.return_value.run.assert_called_once_with(
                        ["verified-bash"], runtime.parent, env={"child": "only"})
                    factory.return_value.close.assert_called_once_with()

    def test_failure_exit_status_is_preserved_and_runner_closed(self):
        import io
        for error, expected in ((subprocess.CalledProcessError(23, ["bash"]), 23),
                                (OSError("missing dependency"), 2), (ValueError("invalid runtime"), 2)):
            with self.subTest(error=error), patch("install_process.SetupRunner") as factory, \
                    patch.object(platform_process, "setup_command", side_effect=error), \
                    patch("sys.stderr", io.StringIO()):
                self.assertEqual(platform_process.main(["--host", "claude"]), expected)
                factory.return_value.run.assert_not_called()
                factory.return_value.close.assert_called_once_with()

    def test_invalid_cli_never_starts_setup(self):
        import io
        for args in ([], ["--host", "unknown"], ["--host", "codex", "--check", "--preflight"]):
            with self.subTest(args=args), patch("install_process.SetupRunner") as factory, \
                    patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as raised:
                platform_process.main(args)
            self.assertEqual(raised.exception.code, 2)
            factory.assert_not_called()


class TypedArgumentBridgeTest(unittest.TestCase):
    def test_only_declared_paths_are_converted(self):
        argv = ["-c", "/d/project", "/regex/body", '{"path":"/c/data"}', "/c/code"]
        with patch.object(windows_bootstrap, "os", SimpleNamespace(name="nt")):
            self.assertEqual(windows_bootstrap._convert(argv, (1, 4)),
                             ["-c", "D:/project", "/regex/body", '{"path":"/c/data"}', "C:/code"])
        self.assertEqual(argv[1], "/d/project")

    def test_cli_path_schemas_leave_modes_hosts_and_payloads_alone(self):
        cases = [
            ("project_profile_cli.py", ["check-roles", "claude", "/c/pack", "/c/project"], (3, 4)),
            ("project_profile_cli.py", ["preview", "/c/pack", "/c/project"], (2, 3)),
            ("render_antigravity_agent.py", ["--roles", "/c/pack"], (2,)),
            ("render_antigravity_agent.py", ["/c/pack", "xy-qa"], (1,)),
            ("shared_core_skills.py", ["sync-tree", "/c/source", "/c/target", "xy-workflow"], (2, 3)),
            ("workflow_hook_install.py", ["apply", "/c/pack", "/c/project", "claude"], (2, 3)),
        ]
        for script, args, indices in cases:
            with self.subTest(script=script, args=args):
                self.assertEqual(windows_bootstrap._script_paths(script, [script, *args]), indices)

    def test_unknown_script_does_not_guess_argument_types(self):
        self.assertEqual(windows_bootstrap._script_paths("business.py", ["business.py", "/c/text"]), ())


if __name__ == "__main__":
    unittest.main()
