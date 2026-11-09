"""既有本地 Python 的可信隔离启动入口。

只把显式脚本或包目录加入导入路径，不加入调用者工作目录；这保留正常
Python CLI 的导入语义，并避免业务目录及临时缓存注入同名模块。
本模块不提供解释器下载、部署或安装渠道。
"""

from __future__ import annotations

import os
import hashlib
import math
from pathlib import Path, PureWindowsPath
import runpy
import subprocess
import sys
import time


def _supervise(arguments: list[str]) -> int:
    """只执行生成端清单已冻结的 stdlib 后端；校验与编译使用同一份字节。"""
    if os.name != "nt" or len(arguments) < 7:
        raise ValueError("Windows Hook supervision requires native Windows and an explicit backend")
    backend, digest, parent, created, remaining = arguments[:5]
    budget = float(remaining)
    deadline = time.monotonic() + budget / 1000
    if (not math.isfinite(deadline) or budget > 12000
            or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
            or not Path(backend).is_absolute()):
        raise ValueError("Invalid Windows Hook backend or budget")
    if budget <= 0:
        sys.stdout.buffer.write(b"{}\n")
        return 0
    with open(backend, "rb") as stream:
        body = stream.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("Windows Hook supervisor does not match its frozen digest")
    # 不先 import，也不核验后 runpy 重开路径，防止并发替换把另一份代码带进
    # 监督者。该后端仅依赖标准库，导入闭包不会借用项目 cwd/PYTHONPATH。
    namespace = {"__name__": "_workflow_windows_supervisor", "__file__": backend}
    exec(compile(body, backend, "exec"), namespace)
    command = [sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).absolute()), *arguments[5:]]
    return namespace["supervise_hook"](command, int(parent), int(created), deadline)


def _native_path(value: str) -> str:
    # Git Bash supplies only known script paths in POSIX form. Do not convert
    # JSON, code, regular expressions or arbitrary following arguments.
    if os.name != "nt" or not value.startswith("/"):
        return value
    if len(value) > 2 and value[1].isascii() and value[1].isalpha() and value[2] == "/":
        return value[1].upper() + ":/" + value[3:]
    bash = PureWindowsPath(os.environ.get("AGENT_WORKFLOW_BASH", ""))
    if (not bash.is_absolute() or len(bash.drive) != 2
            or bash.name.lower() != "bash.exe" or bash.parent.name.lower() != "bin"):
        raise ValueError("Git mount paths require an explicitly validated Git for Windows Bash")
    root = bash.parent.parent
    if root.name.lower() == "usr":
        root = root.parent
    cygpath = root / "usr" / "bin" / "cygpath.exe"
    try:
        result = subprocess.run(
            [str(cygpath), "-am", "--", value], shell=False,
            capture_output=True, encoding="utf-8", errors="strict", timeout=10,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ValueError(f"cannot convert typed Git mount path: {value!r}") from exc
    converted = result.stdout.removesuffix("\n").removesuffix("\r")
    native = PureWindowsPath(converted)
    if (result.returncode != 0 or not native.is_absolute() or len(native.drive) != 2
            or not native.drive[0].isascii() or not native.drive[0].isalpha()
            or len(converted) > 32768 or any(ord(char) < 32 for char in converted)):
        raise ValueError(f"Git returned an invalid local path for {value!r}")
    return converted


def _script_paths(script: str, argv: list[str]) -> tuple[int, ...]:
    """Only typed CLI path positions are converted; payload arguments stay bytes."""
    name = Path(script).name
    fixed = {
        "ensure_project_id.py": (1, 2), "validate_project_config.py": (1, 2, 3),
        "validate_project_docs.py": (1, 2), "role_models.py": (1,),
        "business_confirmation_policy.py": (1,), "claude_instructions.py": (2, 3),
        "workflow_hook_install.py": (2, 3), "merge_codex_config.py": (1,),
        "apply_antigravity_setup.py": (2, 3, 4),
        "validate_claude_artifacts.py": (2, 3, 4),
        "validate_antigravity_artifacts.py": (2, 3),
        "render_antigravity_agent.py": (2,) if argv[1:2] == ["--roles"] else (1,),
    }
    if name == "project_profile_cli.py":
        return (3, 4) if argv[1:2] == ["check-roles"] else (2, 3)
    if name == "shared_core_skills.py":
        return (2, 3) if argv[1:2] in (["stage-copy"], ["target-safe"], ["sync-tree"], ["tree-match"]) else (2,)
    return fixed.get(name, ())


def _convert(argv: list[str], indices: tuple[int, ...]) -> list[str]:
    result = list(argv)
    for index in indices:
        if 0 < index < len(result):
            result[index] = _native_path(result[index])
    return result


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments[:1] == ["--hook-supervise"]:
        return _supervise(arguments[1:])
    msys = arguments[:1] == ["--msys"]
    if msys:
        arguments.pop(0)
    path_indices = ()
    if arguments and arguments[0].startswith("--workflow-paths="):
        raw = arguments.pop(0).partition("=")[2]
        if not raw or any(not item.isdecimal() or int(item) <= 0 for item in raw.split(",")):
            raise ValueError("invalid explicit path argument indices")
        path_indices = tuple(map(int, raw.split(",")))
    if msys:
        # These are explicitly path-valued environment variables used by inline
        # renderers; do not enable MSYS's heuristic conversion of arbitrary data.
        for name in ("TPL", "OUT_PATH", "AGENT_WORKFLOW_PROJECT_RUNTIME"):
            if name in os.environ:
                os.environ[name] = _native_path(os.environ[name])
        runtime = os.environ.get("AGENT_WORKFLOW_PROJECT_RUNTIME")
        if runtime:
            sys.path.insert(0, str(Path(runtime)))
    if arguments[:1] == ["--script"]:
        arguments.pop(0)
    while arguments:
        if arguments[0] in {"-B", "-I", "-u"}:
            arguments.pop(0)
        elif arguments[:2] == ["-X", "utf8"]:
            del arguments[:2]
        else:
            break
    if not arguments or arguments[0] == "-":
        sys.argv = _convert(["-", *(arguments[1:] if arguments else [])], path_indices) if msys else ["-", *(arguments[1:] if arguments else [])]
        exec(compile(sys.stdin.read(), "<stdin>", "exec"), {"__name__": "__main__"})
    elif arguments[0] == "-c":
        if len(arguments) < 2:
            raise ValueError("-c requires source code")
        sys.argv = _convert(["-c", *arguments[2:]], path_indices) if msys else ["-c", *arguments[2:]]
        exec(compile(arguments[1], "<string>", "exec"), {"__name__": "__main__"})
    elif arguments[0] == "-m":
        if len(arguments) < 2:
            raise ValueError("-m requires a module")
        # Modules in the installed project are explicit, not cwd imports.
        runtime = os.environ.get("AGENT_WORKFLOW_PROJECT_RUNTIME")
        if runtime:
            sys.path.insert(0, str(Path(_native_path(runtime)).absolute()))
        sys.argv = arguments[1:]
        runpy.run_module(arguments[1], run_name="__main__", alter_sys=True)
    elif arguments[0].startswith("-"):
        raise ValueError(f"unsupported runtime option: {arguments[0]}")
    else:
        script = Path(_native_path(arguments[0])).absolute()
        # This is the explicit script directory, not the project working dir.
        sys.path.insert(0, str(script.parent))
        argv = [str(script), *arguments[1:]]
        sys.argv = _convert(argv, _script_paths(str(script), argv) + path_indices) if msys else argv
        runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2)
