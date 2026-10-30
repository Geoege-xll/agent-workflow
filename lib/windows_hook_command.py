"""Strict Windows Hook command v2, independent of the host's quoting rules.

Only a bare executable name, fixed switches and base64 reach the host shell.
The payload starts native Python with inherited (not PowerShell-transcoded)
standard streams. No profiles, ExecutionPolicy changes or PATH changes.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


PREFIX = "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
HEADER = "# agent-workflow-assist-v1 windows-hook-command-v2\n"
_HEADER_BYTES = HEADER.encode("utf-16-le")
# Keep complete base64 triples, so this remains a stable prefix of all payloads.
ENCODED_MARKER = base64.b64encode(_HEADER_BYTES[:len(_HEADER_BYTES) // 3 * 3]).decode("ascii")
MAX_COMMAND_LENGTH = 8191  # cmd.exe is the narrowest supported shell boundary.
_SCRIPT_BEFORE = HEADER + (
    "$ErrorActionPreference='Stop'\n"
    "$aw=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
)
_SCRIPT_AFTER = (
    "'))|ConvertFrom-Json\n"
    "$psi=New-Object System.Diagnostics.ProcessStartInfo\n"
    "$psi.UseShellExecute=$false\n"
    "$psi.RedirectStandardInput=$false\n"
    "$psi.RedirectStandardOutput=$false\n"
    "$psi.RedirectStandardError=$false\n"
    "$psi.FileName=[string]($aw.argv[0])\n"
    "$psi.Arguments=[string]$aw.arguments\n"
    "$p=[System.Diagnostics.Process]::Start($psi)\n"
    "$p.WaitForExit()\n"
    "exit $p.ExitCode\n"
)


def _base64(value: str) -> bytes:
    try:
        body = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid Windows Hook base64") from exc
    if base64.b64encode(body).decode("ascii") != value:
        raise ValueError("noncanonical Windows Hook base64")
    return body


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _absolute_windows_path(value: str) -> bool:
    # Python 3.11's ntpath.isabs also accepts drive-relative roots (\foo).
    # Persistent commands must not depend on the host's current drive.
    return bool(ntpath.splitdrive(value)[0]) and ntpath.isabs(value)


def _arguments(argv):
    if not isinstance(argv, (tuple, list)) or not argv:
        raise ValueError("Windows Hook argv must be a nonempty list")
    if any(not isinstance(value, str) or "\0" in value for value in argv):
        raise ValueError("invalid Windows Hook argument")
    if not argv[0] or not _absolute_windows_path(argv[0]):
        raise ValueError("Windows Hook Python executable must be absolute")
    return list(argv)


def encode_command(argv) -> str:
    arguments = _arguments(argv)
    manifest = {"argv": arguments, "arguments": subprocess.list2cmdline(arguments[1:])}
    encoded = base64.b64encode(_canonical(manifest)).decode("ascii")
    script = _SCRIPT_BEFORE + encoded + _SCRIPT_AFTER
    command = PREFIX + base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    if len(command) > MAX_COMMAND_LENGTH:
        raise ValueError("Windows Hook command exceeds the supported cmd.exe length limit")
    return command


def decode_command(command: str) -> list[str]:
    if not isinstance(command, str) or not command.startswith(PREFIX) or len(command) > MAX_COMMAND_LENGTH:
        raise ValueError("unproven Windows Hook command/version")
    try:
        script = _base64(command[len(PREFIX):]).decode("utf-16-le")
        match = re.fullmatch(re.escape(_SCRIPT_BEFORE) + r"([A-Za-z0-9+/]+={0,2})" + re.escape(_SCRIPT_AFTER), script)
        if match is None:
            raise ValueError("modified Windows Hook script grammar")
        raw = _base64(match.group(1))
        manifest = json.loads(raw.decode("ascii"))
        if (not isinstance(manifest, dict) or set(manifest) != {"argv", "arguments"}
                or _canonical(manifest) != raw):
            raise ValueError("noncanonical Windows Hook manifest")
        argv = _arguments(manifest["argv"])
        if encode_command(argv) != command:
            raise ValueError("modified Windows Hook command encoding")
        return argv
    except (UnicodeError, TypeError, KeyError) as exc:
        raise ValueError("invalid Windows Hook command payload") from exc


def looks_managed(command: str, owner: str) -> bool:
    """Detect ownership *candidates*, never claim ownership from a marker alone."""
    if owner in command or ENCODED_MARKER in command:
        return True
    # Recognize a damaged/reordered launcher if its payload still names us.
    match = re.search(r"(?:^|\s)-EncodedCommand\s+([A-Za-z0-9+/=]+)", command, re.I)
    if match and len(match.group(1)) <= MAX_COMMAND_LENGTH:
        try:
            return owner in _base64(match.group(1)).decode("utf-16-le")
        except (ValueError, UnicodeError):
            pass
    return False


def _system_directory() -> Path:
    if os.name != "nt":
        raise OSError("Windows Hook preflight requires native Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.GetSystemDirectoryW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    function.restype = ctypes.c_uint32
    size = 32768
    buffer = ctypes.create_unicode_buffer(size)
    count = function(buffer, size)
    if not count or count >= size:
        raise ctypes.WinError(ctypes.get_last_error())
    return Path(buffer.value)


def validate_powershell() -> str:
    """Prove current process PATH/cwd resolve the bare name to system PowerShell.

    This cannot inspect functions/aliases in an already-running host shell, or
    guarantee a host's future environment. Native host-shell protocol acceptance
    remains a separate gate; no profile or user configuration is changed here.
    """
    expected = _system_directory() / "WindowsPowerShell/v1.0/powershell.exe"
    found = shutil.which("powershell.exe")
    try:
        valid = found is not None and expected.is_file() and os.path.samefile(found, expected)
    except OSError:
        valid = False
    if not valid:
        raise ValueError("Windows Hook requires powershell.exe to resolve to Windows system PowerShell; "
                         "preserved PATH/profile settings (no automatic workaround)")
    return str(expected)


def persistent_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not _absolute_windows_path(value) or "\0" in value:
        raise ValueError(f"Windows Hook {label} must be an absolute persistent path")
    parts = re.split(r"[\\/]", value)
    if any(part.casefold() in {"_npx", "_cacache"} for part in parts):
        raise ValueError(f"Windows Hook {label} must not reference the npm/npx cache")
    return value


def runtime_paths() -> tuple[str, str]:
    """Use the selected persistent interpreter/bootstrap, never package-cache paths."""
    python = persistent_path(sys.executable, "Python executable")
    configured = os.environ.get("AGENT_WORKFLOW_BOOTSTRAP")
    bootstrap = configured if configured is not None else ntpath.join(ntpath.dirname(python), "windows_bootstrap.py")
    bootstrap = persistent_path(bootstrap, "bootstrap")
    if ntpath.basename(bootstrap).casefold() != "windows_bootstrap.py":
        raise ValueError("Windows Hook bootstrap must be windows_bootstrap.py")
    if not Path(bootstrap).is_file():
        raise ValueError("Windows Hook requires a persistent windows_bootstrap.py beside the selected Python "
                         "or absolute AGENT_WORKFLOW_BOOTSTRAP; no npx-cache fallback")
    validate_powershell()
    return python, bootstrap
