"""Native-only local-tgz acceptance checks. Never install into a real project."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt", "requires native Windows x64; portable mocks are not acceptance")
class WindowsNpxEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        archive = os.environ.get("AGENT_WORKFLOW_NPX_TGZ")
        if not archive:
            raise unittest.SkipTest("set AGENT_WORKFLOW_NPX_TGZ to a complete local tgz; no E2E result")
        cls.archive = Path(archive).absolute()
        if not cls.archive.is_file():
            raise AssertionError("AGENT_WORKFLOW_NPX_TGZ is not an existing local archive")
        cls.node = shutil.which("node.exe")
        cls.npm = shutil.which("npm.cmd")
        if not cls.node or not cls.npm:
            raise AssertionError("native x64 Node.js/npm are required")
        # Invoke npm's actual JS CLI, not a .cmd file through shell=True.
        cls.npm_cli = Path(cls.npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not cls.npm_cli.is_file():
            raise AssertionError("cannot find npm-cli.js next to npm.cmd")
        buffer = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
            raise ctypes.WinError()
        cls.system = Path(buffer.value)
        cls.powershell = cls.system / "WindowsPowerShell/v1.0/powershell.exe"
        cls.cmd = cls.system / "cmd.exe"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="awf-native-e2e-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "项目 with spaces & (parentheses)"
        self.project.mkdir()
        self.cache = self.root / "private npm cache"
        self.artifacts = self.root / "local artifacts"
        self.artifacts.mkdir()
        self.tgz = self.artifacts / self.archive.name
        shutil.copyfile(self.archive, self.tgz)
        self.env = dict(os.environ)
        # The supported default is bundled Python, not this test runner's Python.
        for key in tuple(self.env):
            if key.upper() in {"AGENT_WORKFLOW_PYTHON", "AGENT_WORKFLOW_BOOTSTRAP",
                               "AGENT_WORKFLOW_CANCEL_FILE", "AGENT_WORKFLOW_PROJECT_RUNTIME"}:
                self.env.pop(key)
        self.env.update(npm_config_registry="http://127.0.0.1:9", npm_config_audit="false",
                        npm_config_fund="false", npm_config_update_notifier="false")
        self.sentinel = self.project / "USER_CONTENT.txt"
        self.sentinel.write_bytes(b"never replace user content\n")

    def execute(self, arguments, *, env=None, cwd=None, timeout=240):
        return subprocess.run(
            [self.node, str(self.npm_cli), "exec", "--offline", "--ignore-scripts", "--yes",
             "--cache", str(self.cache), "--package", str(self.tgz), "--", "agent-workflow", *arguments],
            cwd=cwd or self.project, env=self.env if env is None else env,
            capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def profile_snapshot(self):
        import winreg
        registry = {}
        for hive, subkey in ((winreg.HKEY_CURRENT_USER, "Environment"),
                             (winreg.HKEY_LOCAL_MACHINE,
                              r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            with winreg.OpenKey(hive, subkey) as key:
                try:
                    registry[(str(hive), subkey)] = winreg.QueryValueEx(key, "Path")
                except FileNotFoundError:
                    registry[(str(hive), subkey)] = None
        policies = subprocess.run(
            [str(self.powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
             "Get-ExecutionPolicy -List | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        profiles = subprocess.run(
            [str(self.powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
             "@($PROFILE.AllUsersAllHosts,$PROFILE.AllUsersCurrentHost,"
             "$PROFILE.CurrentUserAllHosts,$PROFILE.CurrentUserCurrentHost) | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        files = [Path(item) for item in json.loads(profiles)]
        files += [Path.home() / name for name in (".bashrc", ".bash_profile", ".profile", ".zshrc",
                                                  ".gitconfig", ".config/git/config")]
        # Compare only hashes. Never print profile or Git configuration contents.
        hashes = {str(file): hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None
                  for file in files}
        return registry, policies, hashes, dict(os.environ)

    def test_help_and_invalid_explicit_dependencies_do_not_write_project(self):
        before = self.profile_snapshot()
        for args in ([], ["--help"], ["--version"]):
            self.assert_success(self.execute(args))
        for args, additions in ((["init", "--timeout", "nan"], {}),
                                (["init", "--unknown"], {}),
                                (["init"], {"AGENT_WORKFLOW_PYTHON": "missing-python.exe"}),
                                (["init"], {"AGENT_WORKFLOW_PYTHON": ""}),
                                (["init"], {"AGENT_WORKFLOW_BASH": "missing-bash.exe"})):
            with self.subTest(args=args, additions=additions):
                result = self.execute(args, env={**self.env, **additions})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([self.sentinel], list(self.project.iterdir()))
        self.assertEqual(before, self.profile_snapshot())

    def test_init_with_existing_hooks_and_msys_mount_temp(self):
        before = self.profile_snapshot()
        agents = self.project / ".agents"
        agents.mkdir()
        hooks = agents / "hooks.json"
        hooks.write_bytes(b"{}\n")
        self.env["TMPDIR"] = "/tmp"
        self.assert_success(self.execute(["init"]))
        self.assertIsInstance(json.loads(hooks.read_text(encoding="utf-8")), dict)
        runtime = self.project / ".agent-workflow"
        result = subprocess.run(
            [self.node, str(runtime / "lib/python_runtime.cjs"),
             str(runtime / "lib/platform_process.py"), "--host", "antigravity", "--check"],
            cwd=self.project, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=180,
        )
        self.assert_success(result)
        self.assertEqual(b"never replace user content\n", self.sentinel.read_bytes())
        self.assertEqual(before, self.profile_snapshot())

    def test_offline_init_upgrade_timeout_and_cache_independent_helper_and_hook(self):
        before = self.profile_snapshot()
        # Git can be discovered from installation information, not the caller PATH.
        path_key = next(key for key in self.env if key.upper() == "PATH")
        self.env[path_key] = ";".join(map(str, (
            Path(self.node).parent, self.system, self.powershell.parent,
        )))
        self.assert_success(self.execute(["init"]))
        runtime = self.project / ".agent-workflow"
        config = runtime / "project.yaml"
        configured = config.read_bytes() + b"\n# preserved user configuration\n"
        config.write_bytes(configured)
        self.assert_success(self.execute(["init", "--project", "."]))
        self.assertEqual(configured, config.read_bytes())
        expired = self.execute(["init", "--timeout", "0.000001"])
        self.assertNotEqual(expired.returncode, 0, expired.stdout + expired.stderr)
        self.assertEqual(configured, config.read_bytes())
        self.assertEqual(b"never replace user content\n", self.sentinel.read_bytes())
        # Delete only this test's private npm cache and archive copy, never the
        # user's global cache or any persistent interpreter used by old projects.
        shutil.rmtree(self.cache)
        self.tgz.unlink()
        helper = runtime / "lib/python_runtime.cjs"
        command = [self.node, str(helper), "-c",
                   "import json,sys,tomllib; print(json.dumps({'python':sys.executable}))"]
        result = subprocess.run(command, cwd=self.project, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assert_success(result)
        selected = Path(json.loads(result.stdout)["python"])
        self.assertTrue(selected.is_file())
        self.assertNotIn("_npx", selected.parts)
        self.assertFalse(selected.is_relative_to(self.root))
        checked = subprocess.run(
            [self.node, str(helper), str(runtime / "lib/platform_process.py"), "--host", "claude", "--check"],
            cwd=self.project, env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        self.assert_success(checked)
        settings = json.loads((self.project / ".claude/settings.json").read_text(encoding="utf-8"))
        hooks = settings["hooks"]["SessionStart"]
        commands = [hook["command"] for group in hooks for hook in group["hooks"]
                    if hook.get("command", "").startswith("powershell.exe ")]
        self.assertEqual(len(commands), 1)
        # Real cmd -> real PowerShell -> persistent Python; stdin is not a mock.
        hooked = subprocess.run(
            [str(self.cmd), "/d", "/s", "/c", commands[0]], cwd=self.project, env=self.env,
            input=json.dumps({"cwd": str(self.project), "session_id": "native-e2e",
                              "hook_event_name": "SessionStart", "source": "resume"}),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assert_success(hooked)
        output = json.loads(hooked.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        self.assertTrue(output["additionalContext"])
        self.assertNotIn("permissionDecision", output)
        self.assertEqual(before, self.profile_snapshot())


if __name__ == "__main__":
    unittest.main()
