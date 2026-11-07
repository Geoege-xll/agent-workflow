"""Trusted entry for isolated embedded CPython; never add the caller cwd.

The runtime copy lives next to python.exe outside the npx cache. Only the
explicit script/package directory is added, matching normal Python CLI imports.
"""

from __future__ import annotations

import os
import importlib.util
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path, PureWindowsPath
import runpy
import subprocess
import sys


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


def _filesystem():
    """仅加载 bootstrap 同目录的私有后端；别名避免污染固定核心的模块命名空间。"""
    name = "_agent_workflow_bootstrap_windows_fs"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).absolute().with_name("windows_fs.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _execute(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    msys = arguments[:1] == ["--msys"]
    if msys:
        arguments.pop(0)
    # 在加入任何显式项目/脚本路径前冻结解释器自身路径。中央薄入口在首个
    # 非 builtin import 前恢复这组路径，并只接收本进程注入的安全读取能力。
    # 不占用 windows_fs / platform_fs 名字，否则后续 pin 可能误用当前私有版。
    trusted_paths = tuple(sys.path)
    capabilities = {}
    if os.name == "nt":
        fs = _filesystem()
        os.environ["AGENT_WORKFLOW_BOOTSTRAP"] = str(Path(__file__).absolute())
        capabilities = {"__agent_workflow_windows_fs__": fs,
                        "__agent_workflow_trusted_path__": trusted_paths}
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
            sys.path.insert(0, str(Path(runtime) / "lib"))
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
        # runpy.run_path 会在目标第一行前 import pkgutil，因此薄入口不能
        # 先加入项目目录再依赖脚本恢复 sys.path。只识别两个固定项目入口；
        # 已验证核心 helper 等普通显式脚本保留原 script.parent 导入语义。
        thin_entry = (
            script.name.casefold() == "runtime.py" and script.parent.name.casefold() == ".agent-workflow"
        ) or (
            script.name.casefold() == "workflow_hooks.py" and script.parent.name.casefold() == "lib"
            and script.parent.parent.name.casefold() == ".agent-workflow"
        )
        if thin_entry:
            # --msys 可能已为通用 inline helper 加入 PROJECT_RUNTIME/lib；
            # 薄入口在 runpy 自身导入前一并撤下它，不能只省略 script.parent。
            sys.path[:] = trusted_paths
        else:
            sys.path.insert(0, str(script.parent))
        argv = [str(script), *arguments[1:]]
        sys.argv = _convert(argv, _script_paths(str(script), argv) + path_indices) if msys else argv
        runpy.run_path(str(script), run_name="__main__", init_globals=capabilities)
    return 0


def main(arguments: list[str] | None = None) -> int:
    """内部有界捕获不另建进程后端；整个解释器仍由调用方 Job 控制并收割。"""
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments[:1] != ["--capture-dir"]:
        return _execute(arguments)
    if os.name != "nt" or len(arguments) < 3:
        raise ValueError("capture-dir requires native Windows and an explicit command")
    fs = _filesystem()
    root = fs.absolute_path(arguments[1])
    # 父进程先排他创建私有目录及三个普通文件。这里不创建文件、不接受项目
    # 提供的路径或共享 fixture；任何未知 owner/DACL/重解析点都拒绝。
    fs.assert_private(root)
    with ExitStack() as stack:
        streams = []
        for name, flags, mode in (("stdin", os.O_RDONLY, "rb"),
                                  ("stdout", os.O_WRONLY | os.O_TRUNC, "w"),
                                  ("stderr", os.O_WRONLY | os.O_TRUNC, "w")):
            fs.assert_private(root / name, directory=False)
            fd = fs.secure_os.open(root / name, flags)
            options = {} if mode == "rb" else {"encoding": "utf-8", "newline": ""}
            streams.append(stack.enter_context(fs.secure_os.fdopen(fd, mode, **options)))
        previous = sys.stdin
        # 仅调整当前解释器的 Python 流；不改系统标准句柄，不影响宿主进程。
        sys.stdin = streams[0]
        stack.callback(setattr, sys, "stdin", previous)
        with redirect_stdout(streams[1]), redirect_stderr(streams[2]):
            return _execute(arguments[2:])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2)
