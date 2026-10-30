"""Platform-specific setup argv/environment; never alter the caller environment."""

from __future__ import annotations

import os
from pathlib import Path
import shutil


GIT_TOOLS = ("bash", "sh", "env", "cygpath", "awk", "sed", "grep", "find",
             "sort", "cat", "cp", "mv", "rm", "mkdir", "mktemp", "chmod", "ln",
             "stat", "dirname", "basename", "cut", "tr", "head", "tail", "wc", "date", "cmp", "rmdir")


def git_root(bash: Path) -> Path:
    if bash.name.lower() != "bash.exe" or bash.parent.name.lower() != "bin":
        raise ValueError("Git for Windows bash.exe is required; WSL is unsupported")
    root = bash.parent.parent
    if root.name.lower() == "usr":
        root = root.parent
    if (not bash.is_file()
            or not all((root / "usr/bin" / (name + ".exe")).is_file() for name in GIT_TOOLS)
            or not any((root / directory / "git.exe").is_file()
                       for directory in ("cmd", "bin", "mingw64/bin"))):
        raise ValueError("a complete Git for Windows installation is required")
    return root


def locate_bash() -> Path:
    explicit = os.environ.get("AGENT_WORKFLOW_BASH")
    if explicit is not None:
        if not explicit or "\x00" in explicit:
            raise ValueError("AGENT_WORKFLOW_BASH must name Git for Windows bash.exe")
        candidate = Path(explicit).absolute()
        git_root(candidate)  # An invalid explicit setting never falls back.
        return candidate
    candidates = []
    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]) / "Git/bin/bash.exe")
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Programs/Git/bin/bash.exe")
    found = shutil.which("bash.exe")
    if found:
        candidates.append(Path(found))
    if os.name == "nt":
        import winreg
        for hive, subkey in ((winreg.HKEY_CURRENT_USER, r"SOFTWARE\GitForWindows"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GitForWindows"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GitForWindows")):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    value, kind = winreg.QueryValueEx(key, "InstallPath")
                if kind == winreg.REG_SZ and isinstance(value, str) and Path(value).is_absolute():
                    candidates.append(Path(value) / "bin/bash.exe")
            except OSError:
                continue
    for candidate in candidates:
        try:
            git_root(candidate)
        except ValueError:
            continue
        return candidate.absolute()
    raise ValueError("Git for Windows was not found; set AGENT_WORKFLOW_BASH to its bin\\bash.exe (PATH is unchanged)")


def msys_path(path: Path) -> str:
    # The source path is explicit, local and already checked by the caller.
    path = path.absolute()
    if not path.drive or path.drive.startswith("\\\\"):
        raise ValueError("Git Bash setup requires a local drive path")
    return "/" + path.drive[0].lower() + "/" + "/".join(path.parts[1:])


def setup_command(runtime: Path, options: tuple[str, ...]) -> tuple[list[str], dict[str, str] | None]:
    if os.name != "nt":
        return ["bash", str(runtime / "setup_all.sh"), *options], None
    bash = locate_bash()
    root = git_root(bash)
    env = dict(os.environ)
    original_path = next((value for key, value in env.items() if key.upper() == "PATH"), "")
    # Nested shell/coreutils resolution is scoped to this one setup process tree.
    for key in tuple(env):
        if key.upper() in {"PATH", "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "CDPATH",
                           "MSYS2_ARG_CONV_EXCL", "MSYS_NO_PATHCONV"}:
            env.pop(key)
    env["PATH"] = ";".join(str(root / part) for part in ("usr/bin", "mingw64/bin", "bin", "cmd"))
    env["PATH"] += ";" + original_path
    env["CDPATH"] = ""
    env["AGENT_WORKFLOW_BASH"] = str(bash)
    env["AGENT_WORKFLOW_PROJECT_RUNTIME"] = str(runtime)
    env["MSYSTEM"] = "MINGW64"
    env["CHERE_INVOKING"] = "1"
    return [str(bash), "--noprofile", "--norc", msys_path(runtime / "setup_all.sh"), *options], env


def main(argv=None) -> int:
    """Explicit project-local host maintenance; no global manager or registration."""
    import argparse
    import subprocess
    import sys
    if __package__:
        from .install_process import SetupRunner
    else:
        from install_process import SetupRunner
    parser = argparse.ArgumentParser(description="Run existing setup/check through the verified Bash")
    parser.add_argument("--host", choices=("claude", "codex", "antigravity"), required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)
    runtime = Path(__file__).absolute().parent.parent
    options = (f"--only={args.host}",)
    if args.check:
        options += ("--check",)
    elif args.preflight:
        options += ("--preflight",)
    runner = SetupRunner(timeout=600)
    try:
        command, env = setup_command(runtime, options)
        runner.run(command, runtime.parent, env=env)
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    finally:
        runner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
