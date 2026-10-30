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
import tomllib
import unittest
from unittest.mock import patch
import uuid

from lib import windows_hook_command as codec
from lib import workflow_hook_install as installer


ROOT = Path(__file__).resolve().parents[1]
PYTHON = r"C:\Users\测试 用户\AppData\Local\AgentWorkflow\runtimes\cpython-fixture\python.exe"
BOOTSTRAP = str(PureWindowsPath(PYTHON).parent / "windows_bootstrap.py")
PROJECT = PureWindowsPath(r"C:\work\Owner's 中文 & %PATH% !name! ^ project")
PACK = PROJECT / ".agent-workflow"


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
        self.assertIn("$p.WaitForExit()", script)
        self.assertIn("exit $p.ExitCode", script)
        self.assertNotIn("Invoke-Expression", script)
        self.assertNotIn("$input", script)

    def test_mutated_flags_payload_script_version_and_trailing_commands_are_rejected(self):
        command = codec.encode_command(argv())
        script = base64.b64decode(command[len(codec.PREFIX):]).decode("utf-16-le")
        mutations = [
            command.replace("-NoProfile ", ""),
            command.replace("-NoProfile", "-noprofile"),
            command.replace("powershell.exe", "pwsh.exe"),
            command + " & echo injected",
            command + " ",
            command[:-1] + "!",
            codec.PREFIX + base64.b64encode(script.replace("windows-hook-command-v2", "windows-hook-command-v3").encode("utf-16-le")).decode(),
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
        manifest["arguments"] += " --injected"
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
                       [PYTHON, "a\0b"], [PYTHON, 3], [PYTHON, "x" * 10000]):
            with self.subTest(values=str(values)[:80]), self.assertRaises(ValueError):
                codec.encode_command(values)


class WindowsHookRuntimePreflightTest(unittest.TestCase):
    def test_stable_explicit_bootstrap_and_existing_sibling_fallback(self):
        for configured in (BOOTSTRAP, None):
            with self.subTest(configured=configured), patch.dict(os.environ), \
                    patch.object(codec.sys, "executable", PYTHON), \
                    patch.object(codec.Path, "is_file", return_value=True), \
                    patch.object(codec, "validate_powershell") as preflight:
                os.environ.pop("AGENT_WORKFLOW_BOOTSTRAP", None)
                if configured is not None:
                    os.environ["AGENT_WORKFLOW_BOOTSTRAP"] = configured
                self.assertEqual((PYTHON, BOOTSTRAP), codec.runtime_paths())
                preflight.assert_called_once()

    def test_invalid_bootstrap_never_falls_back_to_npx_or_guesses_another_interpreter(self):
        cases = ("relative/windows_bootstrap.py", r"\stable\windows_bootstrap.py", "",
                 r"C:\cache\_npx\package\windows_bootstrap.py",
                 r"C:\cache\_cacache\windows_bootstrap.py", r"C:\stable\different.py")
        for configured in cases:
            with self.subTest(configured=configured), patch.dict(os.environ, {"AGENT_WORKFLOW_BOOTSTRAP": configured}), \
                    patch.object(codec.sys, "executable", PYTHON), \
                    patch.object(codec.Path, "is_file", return_value=True), \
                    patch.object(codec, "validate_powershell") as preflight, self.assertRaises(ValueError):
                codec.runtime_paths()
            preflight.assert_not_called()
        with patch.dict(os.environ), patch.object(codec.sys, "executable", PYTHON), \
                patch.object(codec.Path, "is_file", return_value=False), self.assertRaisesRegex(ValueError, "persistent"):
            os.environ.pop("AGENT_WORKFLOW_BOOTSTRAP", None)
            codec.runtime_paths()

    def test_interpreter_in_npx_cache_is_rejected(self):
        with patch.object(codec.sys, "executable", r"C:\npm\_npx\python.exe"), self.assertRaisesRegex(ValueError, "cache"):
            codec.runtime_paths()

    def test_only_current_resolution_to_system_powershell_is_accepted_without_path_edits(self):
        system = Path("/fixture/Windows/System32")
        before = dict(os.environ)
        with patch.object(codec, "_system_directory", return_value=system), \
                patch.object(codec.Path, "is_file", return_value=True), \
                patch.object(codec.shutil, "which", return_value="/fixture/resolved/powershell.exe"), \
                patch.object(codec.os.path, "samefile", return_value=True) as same:
            self.assertEqual(str(system / "WindowsPowerShell/v1.0/powershell.exe"), codec.validate_powershell())
            same.assert_called_once()
        for resolved in (None, "/fixture/attacker/powershell.exe"):
            with self.subTest(resolved=resolved), patch.object(codec, "_system_directory", return_value=system), \
                    patch.object(codec.Path, "is_file", return_value=True), \
                    patch.object(codec.shutil, "which", return_value=resolved), \
                    patch.object(codec.os.path, "samefile", return_value=False), self.assertRaisesRegex(ValueError, "preserved PATH/profile"):
                codec.validate_powershell()
        self.assertEqual(before, dict(os.environ))


class WindowsHookOwnershipTest(unittest.TestCase):
    def group(self, host="claude", event="UserPromptSubmit", matcher=""):
        with patch.object(installer.os, "name", "nt"), \
                patch.object(codec, "runtime_paths", return_value=(PYTHON, BOOTSTRAP)):
            return installer.signed_group(PACK, PROJECT, host, event, matcher)

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
                    self.handler(unsigned)["command"] = codec.encode_command(values)
                    self.assertEqual(hashlib.sha256(installer.canonical(unsigned)).hexdigest(),
                                     codec.decode_command(command)[-1])

    def test_every_handler_group_field_and_encoded_command_edit_is_protected(self):
        original = self.group(event="SessionStart", matcher="startup|resume|clear|compact")
        for mutation in ("timeout", "type", "extra", "matcher", "mixed", "command", "prefix", "payload"):
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
            else:
                values = codec.decode_command(handler["command"])
                values[13] = r"C:\other-project"
                handler["command"] = codec.encode_command(values)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                installer.owned_group(group)

    def test_invalid_windows_hook_argv_is_not_claimed_even_with_managed_marker(self):
        for position, value in ((1, "-c"), (5, r"C:\stable\different.py"),
                                (6, "--other"), (7, r"C:\not-workflow.py"),
                                (9, "unknown"), (13, "relative-project"), (17, "not-a-signature")):
            values = argv()
            values[position] = value
            group = {"hooks": [{"type": "command", "command": codec.encode_command(values), "timeout": 3}]}
            with self.subTest(position=position), self.assertRaises(ValueError):
                installer.owned_group(group)

    def test_even_resigned_commands_require_persistent_fully_qualified_paths(self):
        for position, value in ((0, r"C:\npm\_npx\python.exe"),
                                (5, r"C:\npm\_cacache\windows_bootstrap.py"),
                                (7, r"C:\npm\_npx\lib\workflow_hooks.py"),
                                (13, r"\current-drive-project")):
            values = argv(installer.SIGNATURE)
            values[position] = value
            group = {"hooks": [{"type": "command", "command": codec.encode_command(values), "timeout": 3}]}
            values[-1] = hashlib.sha256(installer.canonical(group)).hexdigest()
            group["hooks"][0]["command"] = codec.encode_command(values)
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
            merged = installer.merge_json(user, PACK, PROJECT, "claude", "assist")
            self.assertEqual(merged, installer.merge_json(merged, PACK, PROJECT, "claude", "assist"))
            removed = installer.merge_json(merged, PACK, PROJECT, "claude", "off")
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
            rendered = installer.merge_inline(user, PACK, PROJECT, "assist")
            self.assertEqual(rendered, installer.merge_inline(rendered, PACK, PROJECT, "assist"))
            self.assertEqual(user, installer.merge_inline(rendered, PACK, PROJECT, "off"))
        self.assertTrue(rendered.startswith(user))
        data = tomllib.loads(rendered.decode())
        self.assertFalse(data["features"]["hooks"])
        self.assertTrue(installer.owned_group(data["hooks"]["UserPromptSubmit"][-1]))
        tampered = rendered.replace(b"timeout = 3", b"timeout = 99")
        with self.assertRaisesRegex(ValueError, "modified"):
            installer.merge_inline(tampered, PACK, PROJECT, "off")

    def test_antigravity_disabled_owner_entry_and_user_hooks_are_preserved(self):
        group = self.group("antigravity", "PreInvocation")
        user = {"user-hook": {"enabled": False, "Stop": [{"command": "echo keep"}]},
                installer.OWNER: {"enabled": False, "PreInvocation": [group]}}
        with patch.object(installer.os, "name", "nt"), \
                patch.object(codec, "runtime_paths", return_value=(PYTHON, BOOTSTRAP)):
            merged = installer.merge_json(user, PACK, PROJECT, "antigravity", "assist")
            removed = installer.merge_json(merged, PACK, PROJECT, "antigravity", "off")
        self.assertFalse(merged[installer.OWNER]["enabled"])
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
                    event = "PreInvocation" if host == "antigravity" else "UserPromptSubmit"
                    group = installer.signed_group(runtime, self.root, host, event, "")
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
