#!/usr/bin/env python3
"""固定版本中央安装入口；共享路径安全、事务预算与真实薄桥进程边界。"""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sys
import time

if __package__:
    from .platform_fs import os
    from .install_process import ACTIVE_RUNNER, SetupRunner, SetupRunError
else:
    from platform_fs import os
    from install_process import ACTIVE_RUNNER, SetupRunner, SetupRunError

class InstallError(Exception):
    """中央安装前置条件或目标边界校验失败。"""


def _central_imports():
    """仅加入安装器自身可信根，不从当前业务目录导入同名模块。"""
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)


def capture_process(command: list[str], *, env: dict | None = None, body: bytes | None = None):
    """真实薄桥消费的有界进程入口；沿用安装预算、进程组回收和中断传播。"""
    runner = ACTIVE_RUNNER.get()
    remaining = 60.0 if runner is None or runner.deadline is None else min(60.0, runner.deadline - time.monotonic())
    if remaining <= 0:
        raise SetupRunError("安装预算已耗尽，未启动下一纯读取阶段")
    env = dict(os.environ) if env is None else dict(env)
    for key in ("BASH_ENV", "ENV", "CDPATH", "SHELLOPTS", "BASHOPTS"):
        env.pop(key, None)
    process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE if body is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        output, error = process.communicate(body, timeout=remaining)
    except BaseException:
        SetupRunner.stop(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, output, error)


def _target_path(raw: str, source_root: Path) -> Path:
    """兼容终端拖入的引号与反斜杠转义，但绝不通过 shell 执行路径。"""

    value = raw.rstrip("\r\n")
    if not value.strip():
        raise InstallError("未提供项目目录。请拖入目录后按回车，或将目录作为参数传入。")
    candidates = [value]
    if value.strip() != value:
        candidates.append(value.strip())
    # 参数模式收到的是 shell 已解引用的真实路径，文件夹名本身可能含单引号；
    # 只有原样和去除误输入空白的路径都不存在时，才解析终端拖入的转义形式。
    if not any(Path(candidate).expanduser().is_dir() for candidate in candidates):
        try:
            tokens = shlex.split(value)
        except ValueError as exc:
            raise InstallError(f"项目路径的引号或转义不完整：{exc}") from exc
        if len(tokens) == 1:
            candidates.append(tokens[0])
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.is_dir():
            continue
        if os.name == "nt":
            if __package__:
                from .windows_fs import Directory
            else:
                from windows_fs import Directory
            # Reject junction ancestors before resolve can erase their identity.
            with Directory(path):
                resolved = path.resolve(strict=True)
        else:
            resolved = path.resolve(strict=True)
        if resolved == source_root or resolved.is_relative_to(source_root):
            raise InstallError("目标项目不能是安装包本身或其子目录。")
        if source_root.is_relative_to(resolved):
            raise InstallError("目标目录不能包含当前安装包；请选择具体项目根目录。")
        return resolved
    raise InstallError(f"项目目录不存在或不是文件夹：{value}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="install.sh",
        description="将项目接入固定版本中央工作流；原始安装包可移除。"
    )
    parser.add_argument("project", nargs="?", help="项目根目录；省略时可拖入终端")
    parser.add_argument("--timeout", type=float, help="安装事务的应用预算秒数；超时后停止 setup 并执行恢复")
    parser.add_argument("--state-dir", type=Path, help="本机中央状态根；默认沿现有状态配置")
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parent.parent
    try:
        raw = args.project
        if raw is None:
            raw = input("请将需要安装的项目文件夹拖入终端，然后按回车：")
        project = _target_path(raw, source_root)
        print(f"[目标] {project}", flush=True)
        installed = install_central(project, source_root, state=args.state_dir,
                                    timeout=args.timeout)
        print("[完成] 中央项目已启用；固定内容 ID：" + installed["runtime_binding"]["content_id"])
    except (EOFError, KeyboardInterrupt):
        print("\n[取消] 未安装。", file=sys.stderr)
        return 2
    except (InstallError, OSError, ValueError, subprocess.CalledProcessError, SetupRunError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    return 0


def install_central(project: Path, source_root: Path, *, state: Path | None = None,
                    timeout: float | None = None) -> dict:
    """源码与 Homebrew 共用中央入口；不默认复制完整核心到项目。

    Windows 缺少安全软链后端时在导入、状态创建及项目写入之前明确拒绝；
    旧自包含残留只由当前预览拒绝，安装器不复制整包或执行历史转换。
    """
    if __package__:
        from .platform_fs import require_skill_symlinks
    else:
        from platform_fs import require_skill_symlinks
    # 平台能力拒绝早于中央模块导入和任何资源创建，避免缺少安全软链能力时
    # 留下半安装状态；不能回退到复制 Skill 或完整核心来绕过边界。
    require_skill_symlinks()
    _central_imports()
    from lib.install_process import ACTIVE_RUNNER as central_runner
    from lib import runtime_store
    from manager import runtime_service
    runner = SetupRunner(timeout)
    token = central_runner.set(runner)
    original = ACTIVE_RUNNER.set(runner)
    try:
        plan = runtime_service.preview(runtime_store.state_root(state), project, "enable",
                                       source_root=source_root)
        if not plan.summary["can_apply"]:
            raise InstallError("；".join(item["reason"] for item in plan.summary["conflicts"]))
        if runner.deadline is not None and runner.deadline <= time.monotonic():
            raise SetupRunError("安装预算已耗尽，项目尚未发布")
        return runtime_service.apply(plan)
    finally:
        ACTIVE_RUNNER.reset(original)
        central_runner.reset(token)
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())
