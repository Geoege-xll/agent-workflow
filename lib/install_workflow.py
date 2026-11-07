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

# 离线 NPM 构建器静态读取此字面量白名单；它描述源包载荷，不代表项目整包复制。
PACK_FILES = ("setup_all.sh", "setup_claude.sh", "setup_codex.sh", "setup_antigravity.sh", "project.yaml")
PACK_DIRECTORIES = ("product", "roles", "platforms", "lib", "scripts", "templates", "manager")

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
    if os.name == "nt":
        return _capture_windows(command, env, body, remaining, runner)
    process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE if body is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        output, error = process.communicate(body, timeout=remaining)
    except BaseException:
        SetupRunner.stop(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, output, error)


def _capture_windows(command, env, body, remaining, parent_runner):
    """用既有 Windows Job 运行真实薄桥；临时私有流在 Job 收割后才读取和删除。"""
    import tempfile
    import uuid
    if __package__:
        from .windows_hook_command import runtime_paths
        from .windows_fs import assert_private, read_file
        from .windows_process import WindowsJobCleanupError
    else:
        from windows_hook_command import runtime_paths
        from windows_fs import assert_private, read_file
        from windows_process import WindowsJobCleanupError
    # 不接受任意 shell 命令；唯一消费者传入当前解释器及显式脚本。
    if command[:4] != [sys.executable, "-B", "-X", "utf8"] or len(command) < 5:
        raise SetupRunError("Windows 捕获入口只接受当前解释器的显式 UTF-8 脚本")
    python, bootstrap = runtime_paths()
    root = Path(tempfile.gettempdir()) / ("agent-workflow-capture-" + uuid.uuid4().hex)
    os.mkdir(root, 0o700)
    child_runner = SetupRunner(remaining)
    child_runner.cancel_file = None if parent_runner and parent_runner.recovering else (
        parent_runner.cancel_file if parent_runner else child_runner.cancel_file)
    created = []
    unconfirmed_job = False
    try:
        assert_private(root)
        for name, payload in (("stdin", body or b""), ("stdout", b""), ("stderr", b"")):
            fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            created.append(name)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        wrapped = [python, "-I", "-B", "-X", "utf8", bootstrap, "--capture-dir", str(root),
                   "--script", *command[4:]]
        code = 0
        try:
            child_runner.run(wrapped, cwd=Path.cwd(), env=env)
        except subprocess.CalledProcessError as failure:
            code = failure.returncode
        except WindowsJobCleanupError as failure:
            # fatal 表示未确认写进程已停止。任何 unlink/rmdir 或普通清理异常
            # 都不能把它降为可补偿错误，更不能交还一个仍可能写入的目录。
            # 结构化属性和 JSON note 只记录本调用创建的路径，不包含捕获正文。
            import json
            unconfirmed_job = True
            failure.capture_directory = str(root)
            failure.add_note(json.dumps({"capture_directory": str(root), "job_stopped": False},
                                        ensure_ascii=False, sort_keys=True))
            raise
        return subprocess.CompletedProcess(command, code, read_file(root / "stdout"), read_file(root / "stderr"))
    finally:
        if not unconfirmed_job:
            child_runner.close()
            for name in created:
                os.unlink(root / name)
            os.rmdir(root)
        # SetupRunner.close 只恢复 signal，不证明 Job 已停止。fatal 分支保持
        # 原异常及全部自有捕获现场，等待外层明确报告后由人工/受控恢复处理。


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
    """源码/Homebrew/NPM 共用默认入口；不再默认复制完整核心到项目。

    Windows 以当前令牌真实检查安全软链能力，失败在导入、状态及项目写入前拒绝；
    旧自包含残留只由当前预览拒绝，安装器不复制整包或执行历史转换。
    """
    if __package__:
        from .platform_fs import require_skill_symlinks
    else:
        from platform_fs import require_skill_symlinks
    # 此能力拒绝早于导入中央 manager/新增模块；旧 Windows 打包入口也必须给
    # 出明确平台边界，不能因不含 manager 而先抛缺模块错误，更不能回退复制。
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
