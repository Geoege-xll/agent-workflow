"""Portable codec/ownership checks and separately gated native shell protocols."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch
import uuid
from types import SimpleNamespace

from lib.hosts import windows_hook_command as codec
from lib.hosts import workflow_hook_install as installer


ROOT = Path(__file__).resolve().parents[1]
PYTHON = r"C:\Users\测试 用户\AppData\Local\AgentWorkflow\runtimes\cpython-fixture\python.exe"
BOOTSTRAP = str(PureWindowsPath(PYTHON).parent / "windows_bootstrap.py")
PROJECT = PureWindowsPath(r"C:\work\Owner's 中文 & %PATH% !name! ^ project")
PACK = PROJECT / ".agent-workflow"
SUPERVISOR = {"path": r"C:\stable\core\lib\install\windows_process.py", "sha256": "a" * 64}
WINDOWS_OPTIONS = {"windows_runtime": (PYTHON, BOOTSTRAP), "supervisor": SUPERVISOR}


def argv(signature="0" * 64, host="claude", event="UserPromptSubmit"):
    return [PYTHON, "-I", "-B", "-X", "utf8", BOOTSTRAP, "--script",
            str(PACK / "lib/workflow_hooks.py"), "--host", host, "--event", event,
            "--project", str(PROJECT), "--owner", installer.OWNER, "--signature", signature]


class WindowsHookCodecTest(unittest.TestCase):
    def test_round_trip_is_deterministic_and_contains_only_shell_safe_outer_tokens(self):
        arguments = argv()
        command = codec.encode_command(arguments)
        self.assertEqual(arguments, codec.decode_command(command))
        self.assertEqual(command, codec.encode_command(arguments))
        self.assertTrue(command.startswith(codec.PREFIX))
        self.assertIn(codec.ENCODED_MARKER, command)
        self.assertNotIn(str(PROJECT), command)
        self.assertNotIn("-ExecutionPolicy", command)
        self.assertRegex(command[len(codec.PREFIX):], r"^[A-Za-z0-9+/]+={0,2}$")

    def test_native_argument_quoting_is_data_not_powershell_argument_marshalling(self):
        arguments = [PYTHON, "", "中文 🚀", 'embedded "quotes"', "ends\\", "a b\\",
                     "%PATH%", "!value!", "&|<>^", "$(Write-Output injected)", "a\nb"]
        command = codec.encode_command(arguments)
        self.assertEqual(arguments, codec.decode_command(command))
        script = base64.b64decode(command[len(codec.PREFIX):]).decode("utf-16-le")
        self.assertIn("$psi.UseShellExecute=$false", script)
        for stream in ("Input", "Output", "Error"):
            self.assertIn(f"$psi.RedirectStandard{stream}=$false", script)
        self.assertIn("$psi.ArgumentList.Add", script)
        self.assertIn("$p.WaitForExit(", script)
        self.assertIn("exit $p.ExitCode", script)
        self.assertNotIn("Invoke-Expression", script)
        self.assertNotIn("$input", script)

    def test_mutated_flags_payload_script_version_and_trailing_commands_are_rejected(self):
        command = codec.encode_command(argv())
        script = base64.b64decode(command[len(codec.PREFIX):]).decode("utf-16-le")
        mutations = [
            command.replace("-NoProfile ", ""),
            command.replace("-NoProfile", "-noprofile"),
            command.replace("pwsh.exe", "powershell.exe"),
            command + " & echo injected",
            command + " ",
            command[:-1] + "!",
            codec.PREFIX + base64.b64encode(script.replace("windows-hook-command-v3", "windows-hook-command-v4").encode("utf-16-le")).decode(),
            codec.PREFIX + base64.b64encode((script + "Write-Output injected\n").encode("utf-16-le")).decode(),
        ]
        for mutated in mutations:
            with self.subTest(command=mutated[:100]), self.assertRaises(ValueError):
                codec.decode_command(mutated)
            self.assertTrue(codec.looks_managed(mutated, installer.OWNER))

    def test_manifest_quoting_cannot_be_modified_independently_of_argv(self):
        command = codec.encode_command(argv())
        script = base64.b64decode(command[len(codec.PREFIX):]).decode("utf-16-le")
        token = script[len(codec._SCRIPT_BEFORE):-len(codec._SCRIPT_AFTER)]
        manifest = json.loads(base64.b64decode(token))
        manifest["unexpected"] = " --injected"
        changed = base64.b64encode(codec._canonical(manifest)).decode()
        script = codec._SCRIPT_BEFORE + changed + codec._SCRIPT_AFTER
        mutated = codec.PREFIX + base64.b64encode(script.encode("utf-16-le")).decode()
        with self.assertRaises(ValueError):
            codec.decode_command(mutated)

    def test_unrelated_powershell_user_command_is_not_claimed(self):
        command = "powershell.exe -EncodedCommand " + base64.b64encode("Write-Output user".encode("utf-16-le")).decode()
        self.assertFalse(codec.looks_managed(command, installer.OWNER))
        self.assertFalse(installer.owned_group({"hooks": [{"type": "command", "command": command}]}))

    def test_invalid_or_oversized_arguments_fail_without_silent_truncation(self):
        for values in ([], ["python.exe"], [r"\python.exe"], ["/python.exe"], ["C:python.exe"],
                       [r"\\server\share\python.exe"], [r"\\?\C:\python.exe"],
                       [r"C:\tools\..\python.exe"], [r"C:\tools\python.exe:stream"],
                       [PYTHON, "a\0b"], [PYTHON, 3], [PYTHON, "x" * 10000]):
            with self.subTest(values=str(values)[:80]), self.assertRaises(ValueError):
                codec.encode_command(values)


class WindowsHookRuntimePreflightTest(unittest.TestCase):
    def test_bootstrap_compiles_the_same_verified_bytes_without_reopening(self):
        from lib import windows_bootstrap
        with tempfile.TemporaryDirectory(prefix="workflow-bootstrap-digest-") as raw:
            backend = Path(raw) / "windows_process.py"
            body = b"def supervise_hook(command, parent, created, deadline):\n    return 'verified-original'\n"
            backend.write_bytes(body)
            digest = hashlib.sha256(body).hexdigest()
            real_hash = hashlib.sha256

            def replace_after_read(value):
                backend.write_bytes(b"raise RuntimeError('replacement must not execute')\n")
                return real_hash(value)

            with patch.object(windows_bootstrap, "os", SimpleNamespace(name="nt")), \
                    patch.object(windows_bootstrap.hashlib, "sha256", side_effect=replace_after_read):
                self.assertEqual("verified-original", windows_bootstrap._supervise([str(backend), digest, "1", "2", "1000", "--script", "target.py"]))
            with patch.object(windows_bootstrap, "os", SimpleNamespace(name="nt")), self.assertRaisesRegex(ValueError, "frozen digest"):
                windows_bootstrap._supervise([str(backend), digest, "1", "2", "1000", "--script", "target.py"])

    def test_explicit_bootstrap_is_required_without_sibling_guessing(self):
        with patch.dict(os.environ, {"AGENT_WORKFLOW_BOOTSTRAP": BOOTSTRAP}), \
                patch.object(codec.sys, "executable", PYTHON), \
                patch.object(codec.Path, "is_file", return_value=True), \
                patch.object(codec, "validate_powershell") as preflight:
            self.assertEqual((PYTHON, BOOTSTRAP), codec.runtime_paths())
            preflight.assert_called_once()
        with patch.dict(os.environ), patch.object(codec.sys, "executable", PYTHON):
            os.environ.pop("AGENT_WORKFLOW_BOOTSTRAP", None)
            with self.assertRaisesRegex(ValueError, "explicitly deployed"):
                codec.runtime_paths()

    def test_invalid_bootstrap_never_falls_back(self):
        for configured in ("", "relative/windows_bootstrap.py", r"C:\cache\_npx\windows_bootstrap.py", r"C:\stable\other.py"):
            with self.subTest(configured=configured), patch.dict(os.environ, {"AGENT_WORKFLOW_BOOTSTRAP": configured}), \
                    patch.object(codec.sys, "executable", PYTHON), self.assertRaises(ValueError):
                codec.runtime_paths()

    def test_only_native_pwsh_seven_or_newer_is_accepted(self):
        from lib.install import install_process
        before = dict(os.environ)
        trusted = r"C:\Program Files\PowerShell\7\pwsh.exe"
        native = SimpleNamespace(name="nt", environ={}, path=SimpleNamespace(samefile=lambda a, b: True))
        for version, code, accepted in ((b"7", 0, True), (b"8", 0, True), (b"5", 0, False), (b"7", 1, False), (b"bad", 0, False)):
            with self.subTest(version=version, code=code), patch.object(codec, "os", native), \
                    patch.object(codec, "_program_files", return_value=PureWindowsPath(r"C:\Program Files")), \
                    patch.object(codec.shutil, "which", return_value=trusted), \
                    patch.object(codec.Path, "is_file", return_value=True), \
                    patch.object(install_process, "capture_process", return_value=subprocess.CompletedProcess([], code, version, b"")) as capture:
                if accepted:
                    self.assertEqual(trusted, codec.validate_powershell())
                    self.assertEqual(trusted, capture.call_args.args[0][0])
                    self.assertIn("-NoProfile", capture.call_args.args[0])
                else:
                    with self.assertRaises(ValueError):
                        codec.validate_powershell()
        self.assertEqual(before, dict(os.environ))

    def test_cwd_pwsh_is_rejected_before_any_probe_executes(self):
        from lib.install import install_process
        # 负控的业务 cwd 候选必须在版本调用之前拒绝；不能先执行未知 EXE。
        native = SimpleNamespace(name="nt", environ={}, path=SimpleNamespace(samefile=lambda a, b: False))
        with patch.object(codec, "os", native), \
                patch.object(codec, "_program_files", return_value=PureWindowsPath(r"C:\Program Files")), \
                patch.object(codec.shutil, "which", return_value=r"C:\business\pwsh.exe"), \
                patch.object(codec.Path, "is_file", return_value=True), \
                patch.object(install_process, "capture_process") as capture, self.assertRaisesRegex(ValueError, "trusted installation"):
            codec.validate_powershell()
        capture.assert_not_called()

    def test_explicit_pwsh_never_falls_back_and_rejects_path_aliases(self):
        from lib.install import install_process
        for value in ("", "pwsh.exe", r"\\server\share\pwsh.exe", r"\\?\C:\pwsh.exe", r"C:\tools\..\pwsh.exe", r"C:\tools\pwsh.exe:stream", r"C:\NUL\pwsh.exe"):
            native = SimpleNamespace(name="nt", environ={"AGENT_WORKFLOW_PWSH": value})
            with self.subTest(value=value), patch.object(codec, "os", native), \
                    patch.object(codec, "_program_files") as fallback, \
                    patch.object(install_process, "capture_process") as capture, self.assertRaises(ValueError):
                codec.validate_powershell()
            fallback.assert_not_called()
            capture.assert_not_called()


class WindowsHookOwnershipTest(unittest.TestCase):
    def test_windows_production_requires_explicit_verified_material(self):
        for options in ({}, {"windows_runtime": (PYTHON, BOOTSTRAP)}, {"supervisor": SUPERVISOR}):
            with self.subTest(options=tuple(options)), patch.object(installer.os, "name", "nt"), \
                    patch.object(codec, "runtime_paths") as guess, self.assertRaisesRegex(ValueError, "explicit managed"):
                installer.signed_group(PACK, PROJECT, "claude", "UserPromptSubmit", "", **options)
            guess.assert_not_called()

    def group(self, host="claude", event="UserPromptSubmit", matcher=""):
        with patch.object(installer.os, "name", "nt"), \
                patch.object(codec, "runtime_paths", return_value=(PYTHON, BOOTSTRAP)):
            return installer.signed_group(PACK, PROJECT, host, event, matcher, **WINDOWS_OPTIONS)

    def handler(self, group):
        return group.get("hooks", [group])[0]

    def test_signed_windows_group_and_all_registered_hosts_keep_canonical_full_content_signature(self):
        for host, events in installer.EVENTS.items():
            for event, matcher in events:
                with self.subTest(host=host, event=event):
                    group = self.group(host, event, matcher)
                    self.assertTrue(installer.owned_group(group))
                    command = self.handler(group)["command"]
                    values = codec.decode_command(command)
                    self.assertEqual(argv(host=host, event=event)[:-1], values[:-1])
                    self.assertNotIn("_npx", " ".join(values).casefold())
                    unsigned = copy.deepcopy(group)
                    values[-1] = installer.SIGNATURE
                    self.handler(unsigned)["command"] = codec.encode_command(values, supervisor=SUPERVISOR)
                    self.assertEqual(hashlib.sha256(installer.canonical(unsigned)).hexdigest(),
                                     codec.decode_command(command)[-1])

    def test_every_handler_group_field_and_encoded_command_edit_is_protected(self):
        original = self.group(event="SessionStart", matcher="startup|resume|clear|compact")
        for mutation in ("timeout", "type", "extra", "matcher", "mixed", "command", "prefix", "payload", "supervisor-path", "supervisor-sha"):
            group = copy.deepcopy(original)
            handler = self.handler(group)
            if mutation == "timeout":
                handler["timeout"] = 99
            elif mutation == "type":
                handler["type"] = "prompt"
            elif mutation == "extra":
                group["user-extra"] = True
            elif mutation == "matcher":
                group["matcher"] = "everything"
            elif mutation == "mixed":
                group["hooks"].append({"type": "command", "command": "echo user"})
            elif mutation == "command":
                handler["command"] += " && echo user"
            elif mutation == "prefix":
                handler["command"] = handler["command"].replace("-NoProfile ", "")
            elif mutation.startswith("supervisor-"):
                manifest = codec.decode_manifest(handler["command"])
                key = "path" if mutation.endswith("path") else "sha256"
                manifest["supervisor"][key] = r"C:\other\windows_process.py" if key == "path" else "b" * 64
                handler["command"] = codec.encode_command(manifest["argv"], supervisor=manifest["supervisor"])
            else:
                values = codec.decode_command(handler["command"])
                values[13] = r"C:\other-project"
                handler["command"] = codec.encode_command(values, supervisor=SUPERVISOR)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                installer.owned_group(group)

    def test_invalid_windows_hook_argv_is_not_claimed_even_with_managed_marker(self):
        for position, value in ((1, "-c"), (5, r"C:\stable\different.py"),
                                (6, "--other"), (7, r"C:\not-workflow.py"),
                                (9, "unknown"), (13, "relative-project"), (17, "not-a-signature")):
            values = argv()
            values[position] = value
            if position in (1, 5):
                # supervisor codec 已在生成边界拒绝不隔离的解释器或错误bootstrap，
                # 不再要求先造出非法生产命令后才由归属检查拒绝。
                with self.subTest(position=position), self.assertRaises(ValueError):
                    codec.encode_command(values, supervisor=SUPERVISOR)
                continue
            group = {"hooks": [{"type": "command", "command": codec.encode_command(values, supervisor=SUPERVISOR), "timeout": 15}]}
            with self.subTest(position=position), self.assertRaises(ValueError):
                installer.owned_group(group)

    def test_even_resigned_commands_require_persistent_fully_qualified_paths(self):
        for position, value in ((0, r"C:\npm\_npx\python.exe"),
                                (5, r"C:\npm\_cacache\windows_bootstrap.py"),
                                (7, r"C:\npm\_npx\lib\workflow_hooks.py"),
                                (13, r"\current-drive-project")):
            values = argv(installer.SIGNATURE)
            values[position] = value
            group = {"hooks": [{"type": "command", "command": codec.encode_command(values, supervisor=SUPERVISOR), "timeout": 15}]}
            values[-1] = hashlib.sha256(installer.canonical(group)).hexdigest()
            group["hooks"][0]["command"] = codec.encode_command(values, supervisor=SUPERVISOR)
            with self.subTest(position=position), self.assertRaises(ValueError):
                installer.owned_group(group)

    def test_existing_posix_v1_is_byte_compatible_and_can_be_replaced_by_windows_v2(self):
        pack, project = Path("/stable/project/.agent-workflow"), Path("/stable/project")
        with patch.object(installer.os, "name", "posix"):
            old = installer.signed_group(pack, project, "claude", "UserPromptSubmit", "")
        unsigned_command = shlex.join([sys.executable, "-B", str(pack / "lib/workflow_hooks.py"),
                                     "--host", "claude", "--event", "UserPromptSubmit",
                                     "--project", str(project), "--owner", installer.OWNER,
                                     "--signature", installer.SIGNATURE])
        unsigned = {"hooks": [{"type": "command", "command": unsigned_command, "timeout": 3}]}
        expected = unsigned_command[:-len(installer.SIGNATURE)] + hashlib.sha256(installer.canonical(unsigned)).hexdigest()
        self.assertEqual(expected, old["hooks"][0]["command"])
        self.assertTrue(installer.owned_group(old))
        user = {"disableAllHooks": True, "permissions": {"deny": ["Bash(rm *)"]},
                "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo user"}]}, old]}}
        before = copy.deepcopy(user)
        with patch.object(installer.os, "name", "nt"), \
                patch.object(codec, "runtime_paths", return_value=(PYTHON, BOOTSTRAP)):
            merged = installer.merge_json(user, PACK, PROJECT, "claude", "assist", **WINDOWS_OPTIONS)
            self.assertEqual(merged, installer.merge_json(merged, PACK, PROJECT, "claude", "assist", **WINDOWS_OPTIONS))
            removed = installer.merge_json(merged, PACK, PROJECT, "claude", "off", **WINDOWS_OPTIONS)
        self.assertEqual(before, user)
        self.assertEqual(user["permissions"], merged["permissions"])
        self.assertTrue(merged["disableAllHooks"])
        self.assertEqual(user["hooks"]["UserPromptSubmit"][0], merged["hooks"]["UserPromptSubmit"][0])
        expected_off = copy.deepcopy(user)
        expected_off["hooks"]["UserPromptSubmit"].pop()
        self.assertEqual(expected_off, removed)

    def test_windows_inline_codex_preserves_native_disabled_flags_user_bytes_and_signature(self):
        user = b'# user config\n[features]\nhooks = false\n[[hooks.UserPromptSubmit]]\n[[hooks.UserPromptSubmit.hooks]]\ntype="command"\ncommand="echo user"\n'
        with patch.object(installer.os, "name", "nt"), \
                patch.object(codec, "runtime_paths", return_value=(PYTHON, BOOTSTRAP)):
            rendered = installer.merge_inline(user, PACK, PROJECT, "assist", **WINDOWS_OPTIONS)
            self.assertEqual(rendered, installer.merge_inline(rendered, PACK, PROJECT, "assist", **WINDOWS_OPTIONS))
            self.assertEqual(user, installer.merge_inline(rendered, PACK, PROJECT, "off", **WINDOWS_OPTIONS))
        self.assertTrue(rendered.startswith(user))
        data = tomllib.loads(rendered.decode())
        self.assertFalse(data["features"]["hooks"])
        self.assertTrue(installer.owned_group(data["hooks"]["UserPromptSubmit"][-1]))
        tampered = rendered.replace(b"timeout = 15", b"timeout = 99")
        with self.assertRaisesRegex(ValueError, "modified"):
            installer.merge_inline(tampered, PACK, PROJECT, "off")

    def test_antigravity_disabled_owner_entry_and_user_hooks_are_preserved(self):
        # 当前只管理 SessionStart；用户禁用开关和无关 Hook 在同一现行合同下保留。
        # PreInvocation 是已拒绝的历史事件，不能靠成功夹具隐式恢复旧版转换。
        group = self.group("antigravity", "SessionStart")
        user = {"user-hook": {"enabled": False, "Stop": [{"command": "echo keep"}]},
                installer.OWNER: {"enabled": False, "SessionStart": [group]}}
        with patch.object(installer.os, "name", "nt"), \
                patch.object(codec, "runtime_paths", return_value=(PYTHON, BOOTSTRAP)):
            merged = installer.merge_json(user, PACK, PROJECT, "antigravity", "assist", **WINDOWS_OPTIONS)
            removed = installer.merge_json(merged, PACK, PROJECT, "antigravity", "off", **WINDOWS_OPTIONS)
            legacy = copy.deepcopy(user)
            legacy[installer.OWNER] = {"enabled": False, "PreInvocation": [
                self.group("antigravity", "PreInvocation")]}
            with self.assertRaisesRegex(ValueError, "collision"):
                installer.merge_json(legacy, PACK, PROJECT, "antigravity", "assist", **WINDOWS_OPTIONS)
        self.assertFalse(merged[installer.OWNER]["enabled"])
        self.assertIn("SessionStart", merged[installer.OWNER])
        self.assertNotIn("PreInvocation", merged[installer.OWNER])
        self.assertEqual({"user-hook": user["user-hook"]}, removed)


@unittest.skipUnless(os.name == "nt", "native Windows shell protocol acceptance is not run on macOS")
class NativeWindowsHookProtocolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-windows-hook-shell-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Owner's 中文 & %PATH% !name! ^ project"
        self.root.mkdir()
        self.system_powershell = codec.validate_powershell()

    def git_bash(self):
        git = shutil.which("git.exe")
        candidates = []
        configured = os.environ.get("AGENT_WORKFLOW_GIT_BASH")
        if configured:
            candidates.append(Path(configured))
        if git:
            candidates.extend((Path(git).parent.parent / "bin/bash.exe", Path(git).parent / "bash.exe"))
        candidates.extend((Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe",
                           Path(os.environ.get("LOCALAPPDATA", "C:/missing")) / "Programs/Git/bin/bash.exe"))
        found = next((path for path in candidates if path.is_file() and "windows/system32" not in str(path).replace("\\", "/").casefold()), None)
        if found is None:
            self.skipTest("Git for Windows unavailable; native Git Bash Hook protocol remains unverified")
        return str(found)

    def through_shell(self, shell, command, payload=b""):
        if shell == "cmd":
            arguments = [str(codec._system_directory() / "cmd.exe"), "/d", "/s", "/c", command]
        elif shell == "powershell":
            arguments = [self.system_powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            arguments = [self.git_bash(), "--noprofile", "--norc", "-c", command]
        # Execute the actual command string in each shell; never shlex->spawn.
        return subprocess.run(arguments, cwd=self.root, input=payload, capture_output=True, timeout=15)

    def round_trip(self, shell):
        script = self.root / "protocol.py"
        script.write_text(
            "import base64,json,os,sys\n"
            "data={'argv':sys.argv[1:],'cwd':os.getcwd(),'stdin':base64.b64encode(sys.stdin.buffer.read()).decode()}\n"
            "sys.stdout.buffer.write(json.dumps(data,ensure_ascii=False).encode('utf-8'))\n"
            "sys.stderr.buffer.write(b'protocol-stderr\\n')\n", encoding="utf-8")
        values = ["", "中文 🚀", 'embedded "quotes"', "ends\\", "%PATH%", "!name!", "&|<>^", "$(echo injected)"]
        command = codec.encode_command([sys.executable, "-I", "-B", "-X", "utf8", str(script), *values])
        payload = b'{"prompt":"' + "中文\nraw bytes".encode() + b'"}\r\n'
        result = self.through_shell(shell, command, payload)
        self.assertEqual(0, result.returncode, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(values, data["argv"])
        self.assertEqual(str(self.root), data["cwd"])
        self.assertEqual(payload, base64.b64decode(data["stdin"]))
        self.assertEqual(b"protocol-stderr\n", result.stderr)

    def test_cmd_actual_command_string_protocol(self):
        self.round_trip("cmd")

    def test_powershell_actual_command_string_protocol(self):
        self.round_trip("powershell")

    def test_git_bash_actual_command_string_protocol(self):
        self.round_trip("git-bash")

    def test_payload_preserves_native_exitcode_and_outer_powershell_mapping_is_explicit(self):
        command = codec.encode_command([sys.executable, "-I", "-B", "-c", "raise SystemExit(37)"])
        # This first check is the payload, not a claim about a host shell.
        direct = subprocess.run([self.system_powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                                 "-EncodedCommand", command[len(codec.PREFIX):]],
                                cwd=self.root, capture_output=True, timeout=15)
        self.assertEqual(37, direct.returncode, direct.stderr)
        self.assertEqual(37, self.through_shell("cmd", command).returncode)
        # PowerShell -Command itself maps nonzero external status to 1. A host
        # requiring exact nonzero codes needs its own documented exit contract;
        # do not hide that by appending "exit $LASTEXITCODE" only in the test.
        self.assertEqual(1, self.through_shell("powershell", command).returncode)
        self.assertEqual(37, self.through_shell("git-bash", command).returncode)

    def supervised_command(self, script):
        bootstrap = ROOT / "lib/windows_bootstrap.py"
        backend = ROOT / "lib/install/windows_process.py"
        return codec.encode_command([sys.executable, "-I", "-B", "-X", "utf8", str(bootstrap), "--script", str(script)],
                                    supervisor={"path": str(backend), "sha256": hashlib.sha256(backend.read_bytes()).hexdigest()})

    def test_supervised_payload_preserves_raw_streams_exit_and_authoritative_deadline(self):
        script = self.root / "supervised-protocol.py"
        script.write_text("import os,sys,time\nassert float(os.environ['AGENT_WORKFLOW_HOOK_DEADLINE']) > time.monotonic()\nsys.stdout.buffer.write(sys.stdin.buffer.read())\nsys.stderr.buffer.write(b'raw\\xff')\nraise SystemExit(37)\n", encoding="utf-8")
        command = self.supervised_command(script)
        payload = b"\x00\xff" + "中文\n".encode("utf-8")
        with patch.dict(os.environ, {"AGENT_WORKFLOW_HOOK_DEADLINE": "nan"}):
            result = self.through_shell("cmd", command, payload)
        self.assertEqual((37, payload, b"raw\xff"), (result.returncode, result.stdout, result.stderr))

    def test_supervised_budget_is_end_to_end_and_discards_partial_output(self):
        script = self.root / "budget.py"
        late = self.root / "budget-late"
        script.write_text("import subprocess,sys,time\nsys.stdout.buffer.write(b'partial');sys.stdout.buffer.flush()\n"
                          "subprocess.Popen([sys.executable,'-c'," + repr("import time;from pathlib import Path;time.sleep(14);Path(" + repr(str(late)) + ").write_text('late')") + "])\ntime.sleep(30)\n", encoding="utf-8")
        started = time.monotonic()
        result = self.through_shell("cmd", self.supervised_command(script))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"{}\n", result.stdout)
        self.assertLess(time.monotonic() - started, 15)
        time.sleep(3.1)
        self.assertFalse(late.exists(), "budget returned before its descendant was stopped")

    def test_terminating_outer_powershell_drains_supervised_descendants(self):
        script = self.root / "outer-kill.py"
        ready, late = self.root / "outer-ready", self.root / "outer-late"
        child = "import time;from pathlib import Path;Path(" + repr(str(ready)) + ").write_text('ready');time.sleep(3);Path(" + repr(str(late)) + ").write_text('late')"
        script.write_text("import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c'," + repr(child) + "])\ntime.sleep(30)\n", encoding="utf-8")
        # 执行宿主实际收到的完整字符串；杀的是 -Command 外层，不能只终止
        # 内部 payload pwsh 来规避多层原生 shell 的生命周期问题。
        outer = subprocess.Popen([self.system_powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", self.supervised_command(script)],
                                 cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 8
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "supervised descendant did not start")
            outer.terminate()
            outer.communicate(timeout=5)
            time.sleep(3.1)
            self.assertFalse(late.exists(), "descendant survived real outer PowerShell termination")
        finally:
            if outer.poll() is None:
                outer.kill()
                outer.communicate(timeout=5)

    def test_generated_hooks_use_bootstrap_after_source_copy_is_removed(self):
        source = self.root / "source"
        source.mkdir()
        shutil.copytree(ROOT / "lib", source / "lib", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        runtime = self.root / ".agent-workflow"
        shutil.copytree(source, runtime)
        (runtime / "project.yaml").write_text("workflow_hooks:\n  mode: assist\n", encoding="utf-8")
        (self.root / "AGENTS.md").write_text("<!-- pack:product-begin -->\n", encoding="utf-8")
        for host in (".agents", ".claude"):
            skill = self.root / host / "skills/xy-workflow"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: xy-workflow\n---\n", encoding="utf-8")
        persistent = self.root / "persistent-python-bootstrap"
        persistent.mkdir()
        bootstrap = persistent / "windows_bootstrap.py"
        shutil.copyfile(ROOT / "lib/windows_bootstrap.py", bootstrap)
        shutil.rmtree(source)
        with patch.dict(os.environ, {"AGENT_WORKFLOW_BOOTSTRAP": str(bootstrap)}):
            for shell in ("cmd", "powershell", "git-bash"):
                for host in installer.EVENTS:
                    event = "SessionStart" if host == "antigravity" else "UserPromptSubmit"
                    group = installer.signed_group(runtime, self.root, host, event, "", windows_runtime=(sys.executable, str(bootstrap)), supervisor={"path": str(ROOT / "lib/install/windows_process.py"), "sha256": hashlib.sha256((ROOT / "lib/install/windows_process.py").read_bytes()).hexdigest()})
                    command = group.get("hooks", [group])[0]["command"]
                    self.assertTrue(installer.owned_group(group))
                    values = codec.decode_command(command)
                    self.assertEqual(str(bootstrap), values[5])
                    self.assertEqual(str(runtime / "lib/workflow_hooks.py"), values[7])
                    # Invalid/missing AGY identity is deliberately neutral and
                    # does not create a cache in the real user's LocalAppData.
                    payload = ({"workspacePaths": [str(self.root)]} if host == "antigravity" else
                               {"session_id": str(uuid.uuid4()), "cwd": str(self.root), "hook_event_name": event})
                    result = self.through_shell(shell, command, json.dumps(payload).encode())
                    self.assertEqual(0, result.returncode, result.stderr)
                    data = json.loads(result.stdout)
                    if host == "antigravity":
                        self.assertEqual({}, data)
                    else:
                        self.assertIn("additionalContext", data["hookSpecificOutput"])


if __name__ == "__main__":
    unittest.main()
