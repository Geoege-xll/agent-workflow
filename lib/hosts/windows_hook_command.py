"""Strict PowerShell 7+ Windows Hook command v3.

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
import sys


PREFIX = "pwsh.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
HEADER = "# agent-workflow-assist-v1 windows-hook-command-v3\n"
_HEADER_BYTES = HEADER.encode("utf-16-le")
# Keep complete base64 triples, so this remains a stable prefix of all payloads.
ENCODED_MARKER = base64.b64encode(_HEADER_BYTES[:len(_HEADER_BYTES) // 3 * 3]).decode("ascii")
MAX_COMMAND_LENGTH = 8191  # cmd.exe is the narrowest supported shell boundary.
HOST_TIMEOUT_SECONDS = 15
WORK_TIMEOUT_MS = 12000
# 内部统一预算保留 500ms 给 Python 冷启动、Job 清理与原字节回放；PS 的
# 12000ms 仍是全链硬截止时间，绝不为 supervisor 再启动一轮完整预算。
_SCRIPT_BEFORE = HEADER + (
    "$t=[Diagnostics.Stopwatch]::StartNew()\n"
    "$ErrorActionPreference='Stop'\n"
    "if($PSVersionTable.PSVersion.Major -lt 7){exit 2}\n"
    "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
    "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)\n"
    "$aw=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
)
_SCRIPT_AFTER = (
    "'))|ConvertFrom-Json\n"
    "$psi=[Diagnostics.ProcessStartInfo]::new()\n"
    "$psi.UseShellExecute=$false\n"
    "$psi.RedirectStandardInput=$false\n"
    "$psi.RedirectStandardOutput=$false\n"
    "$psi.RedirectStandardError=$false\n"
    "$psi.FileName=[string]($aw.argv[0])\n"
    "for($i=1;$i -lt $aw.argv.Count;$i++){\n"
    "$psi.ArgumentList.Add([string]$aw.argv[$i])\n"
    "if($i -eq 5 -and $null -ne $aw.supervisor){\n"
    "$pp=[Diagnostics.Process]::GetCurrentProcess()\n"
    "foreach($v in @('--hook-supervise',$aw.supervisor.path,$aw.supervisor.sha256,$PID,$pp.StartTime.ToFileTimeUtc(),"
    f"({WORK_TIMEOUT_MS - 500}-$t.ElapsedMilliseconds))){{$psi.ArgumentList.Add([string]$v)}}\n"
    "}}\n"
    "$p=[System.Diagnostics.Process]::Start($psi)\n"
    f"if(!$p.WaitForExit([int][Math]::Max(1,{WORK_TIMEOUT_MS}-$t.ElapsedMilliseconds))){{$p.Kill($true);$p.WaitForExit();exit 0}}\n"
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
    # 外层始终是 base64，不需要把中文膨胀成六字符转义；canonical UTF-8
    # 同时保留精确字节和 cmd.exe 8191 字符的真实入口容量。
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _absolute_windows_path(value: str) -> bool:
    # Python 3.11's ntpath.isabs also accepts drive-relative roots (\foo).
    # Persistent commands must not depend on the host's current drive.
    return bool(ntpath.splitdrive(value)[0]) and ntpath.isabs(value)


def _arguments(argv):
    if not isinstance(argv, (tuple, list)) or not argv:
        raise ValueError("Windows Hook argv must be a nonempty list")
    if any(not isinstance(value, str) or "\0" in value for value in argv):
        raise ValueError("invalid Windows Hook argument")
    persistent_path(argv[0], "Python executable")
    return list(argv)


def _supervisor(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])):
        raise ValueError("Windows Hook supervisor requires an exact path/digest descriptor")
    persistent_path(value["path"], "supervisor")
    return dict(value)


def encode_command(argv, *, supervisor=None) -> str:
    arguments = _arguments(argv)
    supervisor = _supervisor(supervisor)
    if supervisor is not None and (len(arguments) < 6 or arguments[1:5] != ["-I", "-B", "-X", "utf8"]
                                   or ntpath.basename(arguments[5]).casefold() != "windows_bootstrap.py"):
        raise ValueError("Windows Hook supervision requires the explicit isolated bootstrap argv")
    manifest = {"argv": arguments, "supervisor": supervisor}
    encoded = base64.b64encode(_canonical(manifest)).decode("ascii")
    script = _SCRIPT_BEFORE + encoded + _SCRIPT_AFTER
    command = PREFIX + base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    if len(command) > MAX_COMMAND_LENGTH:
        raise ValueError("Windows Hook command exceeds the supported cmd.exe length limit")
    return command


def decode_manifest(command: str) -> dict:
    if not isinstance(command, str) or not command.startswith(PREFIX) or len(command) > MAX_COMMAND_LENGTH:
        raise ValueError("unproven Windows Hook command/version")
    try:
        script = _base64(command[len(PREFIX):]).decode("utf-16-le")
        match = re.fullmatch(re.escape(_SCRIPT_BEFORE) + r"([A-Za-z0-9+/]+={0,2})" + re.escape(_SCRIPT_AFTER), script)
        if match is None:
            raise ValueError("modified Windows Hook script grammar")
        raw = _base64(match.group(1))
        manifest = json.loads(raw.decode("utf-8"))
        if (not isinstance(manifest, dict) or set(manifest) != {"argv", "supervisor"}
                or _canonical(manifest) != raw):
            raise ValueError("noncanonical Windows Hook manifest")
        argv = _arguments(manifest["argv"])
        if encode_command(argv, supervisor=manifest["supervisor"]) != command:
            raise ValueError("modified Windows Hook command encoding")
        return {"argv": argv, "supervisor": manifest["supervisor"]}
    except (UnicodeError, TypeError, KeyError) as exc:
        raise ValueError("invalid Windows Hook command payload") from exc


def decode_command(command: str) -> list[str]:
    return decode_manifest(command)["argv"]


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
    """验证当前进程实际找到的 pwsh.exe 为 7+，不改 PATH/profile 或回退 5.1。

    This cannot inspect functions/aliases in an already-running host shell, or
    guarantee a host's future environment. Native host-shell protocol acceptance
    remains a separate gate; no profile or user configuration is changed here.
    """
    if os.name != "nt":
        raise OSError("Windows Hook preflight requires native Windows")
    configured = os.environ.get("AGENT_WORKFLOW_PWSH")
    expected = configured if configured is not None else str(_program_files() / "PowerShell/7/pwsh.exe")
    expected = persistent_path(expected, "PowerShell executable")
    if ntpath.basename(expected).casefold() != "pwsh.exe" or not Path(expected).is_file():
        raise ValueError("Windows Hook requires an existing persistent pwsh.exe >= 7")
    found = shutil.which("pwsh.exe")
    try:
        matched = found is not None and os.path.samefile(found, expected)
    except OSError:
        matched = False
    if not matched:
        # Windows 3.11 的 which 会考虑 cwd；先证明它是既定可信安装，才能执行
        # 版本探针。不能运行业务项目放置的同名 EXE，再用其自报版本作安全证据。
        raise ValueError("pwsh.exe resolution differs from the trusted installation; preserved PATH/profile settings")
    from lib.install.install_process import capture_process
    result = capture_process([expected, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                              "[Console]::Out.Write([string]$PSVersionTable.PSVersion.Major)"], timeout=5)
    if result.returncode != 0 or not re.fullmatch(rb"[0-9]{1,3}", result.stdout) or int(result.stdout) < 7:
        raise ValueError("Windows Hook requires PowerShell >= 7; no Windows PowerShell fallback")
    return expected


def _program_files() -> Path:
    """从 Windows 已知目录 API 定位标准安装根，不信任业务进程可改的同名环境。"""
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    function = shell.SHGetFolderPathW
    function.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p]
    function.restype = ctypes.c_int32
    buffer = ctypes.create_unicode_buffer(32768)
    if function(None, 0x26, None, 0, buffer) != 0 or not buffer.value:
        raise OSError("Cannot locate the trusted Program Files directory")
    return Path(buffer.value)


def persistent_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not _absolute_windows_path(value) or "\0" in value:
        raise ValueError(f"Windows Hook {label} must be an absolute persistent path")
    drive, tail = ntpath.splitdrive(value)
    if len(drive) != 2 or drive[1] != ":" or not drive[0].isascii() or not drive[0].isalpha():
        raise ValueError(f"Windows Hook {label} requires a local drive path")
    # 复用文件系统负责层的纯组件规则，不在命令生成层维护另一份保留名表。
    # 原始拼写先校验，再交给 Win32；不能让 ..、ADS 或末尾空白先被规范化隐藏。
    from lib.windows_fs import validate_component
    parts = re.split(r"[\\/]", tail)
    for part in parts:
        if part:
            validate_component(part)
    if any(part.casefold() in {"_npx", "_cacache"} for part in parts):
        raise ValueError(f"Windows Hook {label} must not reference the npm/npx cache")
    return value


def runtime_paths() -> tuple[str, str]:
    """Use the selected persistent interpreter/bootstrap, never package-cache paths."""
    python = persistent_path(sys.executable, "Python executable")
    configured = os.environ.get("AGENT_WORKFLOW_BOOTSTRAP")
    if configured is None:
        raise ValueError("Windows Hook requires an explicitly deployed persistent bootstrap")
    bootstrap = configured
    bootstrap = persistent_path(bootstrap, "bootstrap")
    if ntpath.basename(bootstrap).casefold() != "windows_bootstrap.py":
        raise ValueError("Windows Hook bootstrap must be windows_bootstrap.py")
    if not Path(bootstrap).is_file():
        raise ValueError("Windows Hook requires an explicitly deployed persistent windows_bootstrap.py; no cache fallback")
    validate_powershell()
    return python, bootstrap
