#!/usr/bin/env python3
"""把可删除的安装包发布为项目内自包含的隐藏运行时。"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
if __package__:
    from .platform_fs import os, project_install_lock
    from .platform_process import setup_command
else:
    from platform_fs import os, project_install_lock
    from platform_process import setup_command
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

# CLI 直接执行与测试按包导入使用同一入口读写逻辑，避免恢复路径另造安全规则。
if __package__:
    from .claude_instructions import CLAUDE_IMPORT, atomic_write, read_file
    from .validate_project_config import parse_project_name, strip_inline_comment
    from .workflow_hook_install import plan_hooks
    from .standards_baseline import ensure_general_link, merge_general
    from .validate_project_docs import parse_docs
    from .install_process import ACTIVE_RUNNER, SetupRunner, SetupRunError
else:
    from claude_instructions import CLAUDE_IMPORT, atomic_write, read_file
    from validate_project_config import parse_project_name, strip_inline_comment
    from workflow_hook_install import plan_hooks
    from standards_baseline import ensure_general_link, merge_general
    from validate_project_docs import parse_docs
    from install_process import ACTIVE_RUNNER, SetupRunner, SetupRunError


RUNTIME_NAME = ".agent-workflow"
MANIFEST_NAME = ".install-manifest.json"
PACK_FILES = (
    "setup_all.sh",
    "setup_claude.sh",
    "setup_codex.sh",
    "setup_antigravity.sh",
    "project.yaml",
)
PACK_DIRECTORIES = ("product", "roles", "platforms", "lib", "scripts", "templates")


class InstallError(Exception):
    """安装前置条件或受管运行时校验失败。"""


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


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    if os.name == "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        stream = os.fdopen(descriptor, "rb")
    else:
        stream = path.open("rb")
    with stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _managed_files(root: Path) -> dict[str, str]:
    """配置由项目维护；其他运行时文件由安装包管理并记录指纹。"""

    result: dict[str, str] = {}
    if os.name == "nt":
        def visit(directory: Path) -> None:
            with os.scandir(directory) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    path = Path(entry.path)
                    if stat.S_ISLNK(info.st_mode):
                        raise InstallError(f"受管运行时不能包含重解析点：{path}")
                    if stat.S_ISDIR(info.st_mode):
                        if path.name != "__pycache__":
                            visit(path)
                    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        relative = path.relative_to(root).as_posix()
                        if relative not in {"project.yaml", MANIFEST_NAME} and path.name != ".DS_Store":
                            result[relative] = _digest(path)
                    else:
                        raise InstallError(f"受管运行时必须为单链接普通文件：{path}")
        visit(root)
        return result
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise InstallError(f"受管运行时不能包含符号链接：{path}")
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        if relative in {"project.yaml", MANIFEST_NAME}:
            continue
        if path.name == ".DS_Store" or "__pycache__" in relative_path.parts:
            continue
        result[relative] = _digest(path)
    return result


def _validate_existing(runtime: Path) -> None:
    """升级前拒绝覆盖用户改过或来源不明的隐藏目录。"""

    if runtime.is_symlink() or not runtime.is_dir():
        raise InstallError(f"已存在非受管运行时目录：{runtime}")
    manifest_path = runtime / MANIFEST_NAME
    if not manifest_path.is_file():
        raise InstallError(f"已存在未标记的目录，不能自动覆盖：{runtime}")
    try:
        manifest_body = read_file(manifest_path) if os.name == "nt" else manifest_path.read_bytes()
        if manifest_body is None:
            raise ValueError("installation manifest is missing")
        manifest = json.loads(manifest_body)
    except (OSError, ValueError) as exc:
        raise InstallError(f"安装记录无法读取：{manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("managed_files"), dict
    ):
        raise InstallError("安装记录格式未知，不能安全升级。")
    actual = _managed_files(runtime)
    if actual != manifest["managed_files"]:
        raise InstallError(
            "隐藏运行时含有新增、删除或修改过的受管文件；已停止升级并保留原状。"
        )


def _windows_copy(source: Path, target: Path, identities: dict[Path, tuple[int, int]]) -> None:
    info = os.lstat(source)
    if stat.S_ISDIR(info.st_mode):
        os.mkdir(target, 0o700)
        with os.scandir(source) as entries:
            for entry in entries:
                if entry.name in {"__pycache__", ".DS_Store"} or entry.name.endswith(".pyc"):
                    continue
                if source.name == "lib" and entry.name == "install_workflow.py":
                    continue
                _windows_copy(Path(entry.path), target / entry.name, identities)
    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(source_fd, "rb") as input_file:
            opened = os.fstat(input_file.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise InstallError(f"安装源文件在复制前变化：{source}")
            target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(target_fd, "wb") as output:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
                created = os.fstat(output.fileno())
                identities[target] = (created.st_dev, created.st_ino)
            after = os.fstat(input_file.fileno())
            if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise InstallError(f"安装源文件在复制期间变化：{source}")
    else:
        raise InstallError(f"安装源包含链接或不支持的类型：{source}")


def _discard_windows_stage(stage: Path, expected: dict[str, tuple[str, tuple[int, int]]] | None) -> None:
    # An interrupted copy without a full inventory is left for diagnosis. Never
    # recursively delete unknown entries or a user's concurrent staged edits.
    if expected is None:
        return
    if __package__:
        from .windows_fs import remove_file_if_unchanged
    else:
        from windows_fs import remove_file_if_unchanged
    for relative, (digest, identity) in expected.items():
        path = stage / relative
        try:
            remove_file_if_unchanged(path, digest, identity)
        except (OSError, ValueError):
            pass
    directories = set()
    for relative in expected:
        directories.update((stage / relative).parents)
    for directory in sorted((p for p in directories if p == stage or p.is_relative_to(stage)),
                            key=lambda p: -len(p.parts)):
        try:
            os.rmdir(directory)
        except (OSError, ValueError):
            pass


def _copy_runtime(source_root: Path, stage: Path, identities=None) -> None:
    """只复制安装后运行所需的文件，避免把测试和历史草稿留在项目中。"""

    if os.name == "nt":
        if identities is None:
            identities = {}
        for name in (*PACK_FILES, *PACK_DIRECTORIES):
            _windows_copy(source_root / name, stage / name, identities)
        return
    for name in (*PACK_FILES, *PACK_DIRECTORIES):
        source = source_root / name
        if not source.exists() or source.is_symlink():
            raise InstallError(f"安装包缺少正常文件或目录：{source}")
        target = stage / name
        if source.is_dir():
            for child in source.rglob("*"):
                if child.is_symlink():
                    raise InstallError(f"安装包含符号链接，停止复制：{child}")
            ignored = ["__pycache__", "*.pyc", ".DS_Store"]
            if name == "lib":
                ignored.append("install_workflow.py")
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(*ignored),
            )
        elif source.is_file():
            shutil.copy2(source, target)
        else:
            raise InstallError(f"安装包含不支持的文件类型：{source}")


def _run_setup(runtime: Path, project: Path, *options: str) -> None:
    command, environment = setup_command(runtime, options)
    # 只影响展示：把含空格的路径按 shell 可读形式显示，实际执行仍使用参数数组。
    print(f"[安装] {shlex.join(command)}", flush=True)
    runner = ACTIVE_RUNNER.get() or SetupRunner()
    if environment is None:
        runner.run(command, project)
    else:
        runner.run(command, project, env=environment)


def _initialize_project_name(config: Path, project: Path) -> tuple[int, int] | None:
    """仅替换暂存配置的默认显示名；显式名称和其余配置均属于项目。"""
    try:
        body = read_file(config)
        if body is None:
            raise ValueError("project.yaml is missing")
        text = body.decode("utf-8")
        matches = list(re.finditer(r"^project_name:[ \t]*([^\r\n]*)", text, re.MULTILINE))
        if len(matches) != 1:
            raise ValueError("project.yaml must contain exactly one top-level project_name")
        match = matches[0]
        raw = match.group(1)
        if parse_project_name(raw) != "MyProject":
            return
        # 目标根目录才是项目名；不能取源包、随机暂存目录或某个子模块的包名。
        # JSON 字符串也是合法 YAML，可安全保存中文、空格、引号和 # 等目录字符。
        # 只替换标量，保留行内注释、原换行符和 memory.project_id 等其他配置字节。
        value = json.dumps(project.name, ensure_ascii=False)
        suffix = raw[len(strip_inline_comment(raw)):]
        updated = (text[:match.start(1)] + value + suffix + text[match.end(1):]).encode("utf-8")
        if updated != body:
            identity = atomic_write(config, updated, stat.S_IMODE(config.stat().st_mode))
            print(f"[项目] project_name 已按目标目录初始化为 {value}", flush=True)
            return identity
    except ValueError as exc:
        raise InstallError(f"无法初始化项目名称：{exc}") from exc


def _restore_claude_entry(project: Path, original: bytes | None, mode: int) -> None:
    """撤回本轮发布的薄入口；先恢复入口，再让原运行时重建其他受管产物。"""
    path = project / "CLAUDE.md"
    current = read_file(path)
    if current == original:
        return
    # 只能撤回仍为本轮精确产物的入口；并发新增、修改或删除的用户内容不能覆盖。
    # 原先没有入口时只删除这一个确认过的文件，不触碰其他 Claude 指令。
    if current != CLAUDE_IMPORT:
        raise InstallError("CLAUDE.md 在升级期间发生其他变更；已保留现状，停止自动恢复入口。")
    atomic_write(path, original, mode)


def _restore_hook_configs(snapshots: list[tuple[Path, bytes | None, bytes, int]]) -> None:
    """只撤回仍等于本轮精确产物的配置；并发用户修改宁可报错，也不能覆盖。

    旧运行时可能不认识新 Hooks，故先恢复配置，再由原运行时重建其自身产物。
    首次安装保留可诊断状态；这里仅处理已有完整备份的升级失败。
    """
    for path, before, published, mode in reversed(snapshots):
        current = read_file(path)
        if current == before:
            continue
        if current != published:
            raise InstallError(f"Hook 配置升级期间发生其他变更，已保留：{path}")
        atomic_write(path, before, mode)


def _standard_update_snapshots(pack: Path, project: Path) -> list[tuple[Path, bytes, bytes, int]]:
    """记录本轮可能更新的两个非空规范文件，供宿主安装失败时精确撤回。

    只接管已标记的通用区和索引补链；其他文档仍由原有的缺失/空文件策略处理。
    预检后才调用，且再次核对路径和普通文件归属，不假定文件名等于写入授权。
    """

    docs = parse_docs(pack / "project.yaml")
    general = project / docs["standards_root"] / "GENERAL.md"
    index = project / docs["standards"]
    result = []
    for path in (general, index):
        if not path.resolve().is_relative_to(project):
            raise InstallError("规范路径必须位于项目内")
        before = read_file(path)
        if not before:
            continue
        after = (merge_general(before, (pack / "templates/docs/standards/GENERAL.md").read_bytes())
                 if path == general else ensure_general_link(before, index, general))
        if after != before:
            result.append((path, before, after, stat.S_IMODE(path.stat().st_mode)))
    return result


def _restore_standard_updates(snapshots: list[tuple[Path, bytes, bytes, int]]) -> None:
    """只恢复仍等于本轮产物的规范，不能覆盖安装期间的项目专项并发修改。"""

    errors: list[str] = []
    for path, before, published, mode in reversed(snapshots):
        try:
            current = read_file(path)
            if current == before:
                continue
            # 权限本身也是项目修改；不能只因内容相同就把并发 chmod 一起撤回。
            if current != published or stat.S_IMODE(path.stat().st_mode) != mode:
                raise InstallError(f"规范在升级期间发生其他变更，已保留现状：{path}")
            atomic_write(path, before, mode)
        except (InstallError, OSError, ValueError) as exc:
            errors.append(str(exc))
    # 一个项目文件有并发冲突，不阻止撤回其他仍精确属于本轮的独立规范文件。
    if errors:
        raise InstallError("; ".join(errors))


def _install(project: Path, source_root: Path, *, timeout: float | None = None) -> None:
    """给一次事务绑定超时控制；仅限制管理操作，不改变项目开发编排。"""
    runner = SetupRunner(timeout)
    token = ACTIVE_RUNNER.set(runner)
    try:
        control = nullcontext()
        if os.name == "nt":
            if __package__:
                from .windows_runtime import cancellation_guard
            else:
                from windows_runtime import cancellation_guard
            raw = os.environ.get("AGENT_WORKFLOW_CANCEL_FILE")
            if not raw:
                raise InstallError("Windows init requires its private npx cancellation channel")
            control = cancellation_guard(raw)
        # Shared boundary, independent of the manager's outer registry lock.
        # Both locks remain held until all writers and exact recovery finish.
        with project_install_lock(project), control:
            _install_transaction(project, source_root)
    finally:
        runner.close()
        ACTIVE_RUNNER.reset(token)


def _install_transaction(project: Path, source_root: Path) -> None:
    runtime = project / RUNTIME_NAME
    old_pack = project / "agent_workflow"
    # 新安装方式不迁移旧的项目内安装包，也不允许两个入口并存。
    # 这里只识别旧包的明确签名，避免误伤同名但属于业务的目录。
    if (old_pack / "setup_all.sh").is_file() and (
        old_pack / "product/WORKFLOW.md"
    ).is_file():
        raise InstallError(
            f"发现旧工作流目录 {old_pack}；请先备份并移除旧工作流，"
            "再使用本安装器。不会自动兼容或删除旧目录。"
        )
    if runtime.is_symlink():
        raise InstallError(f"不能覆盖符号链接：{runtime}")
    upgrading = runtime.exists()
    if upgrading:
        _validate_existing(runtime)

    # 暂存目录与项目同一文件系统，发布时可用重命名切换；前置检查失败不会
    # 触碰现有运行时或宿主入口。目录名由发现器明确排除，避免误识别为业务模块。
    if os.name == "nt":
        stage = project / (".agent-workflow-stage-" + uuid.uuid4().hex)
        os.mkdir(stage, 0o700)
    else:
        stage = Path(tempfile.mkdtemp(prefix=".agent-workflow-stage-", dir=project))
    stage_inventory: dict[str, tuple[str, tuple[int, int]]] | None = None
    created_files: dict[Path, tuple[int, int]] = {}
    backup: Path | None = None
    try:
        if os.name == "nt":
            _copy_runtime(source_root, stage, created_files)
        else:
            _copy_runtime(source_root, stage)
        if os.name == "nt":
            bootstrap = os.environ.get("AGENT_WORKFLOW_BOOTSTRAP", "")
            if not bootstrap or not Path(bootstrap).is_absolute():
                raise InstallError("Windows init requires its stable bootstrap path")
            if any(char in str(sys.executable) + bootstrap for char in "\r\n\x00"):
                raise InstallError("Windows runtime paths must be single-line absolute paths")
            record = stage / "lib/windows-runtime.paths"
            created_files[record] = atomic_write(
                record, f"{sys.executable}\n{bootstrap}\n".encode("utf-8"), 0o600)
        if upgrading:
            if os.name == "nt":
                original_config = read_file(runtime / "project.yaml")
                if original_config is None:
                    raise InstallError("旧运行时缺少 project.yaml")
                created_files[stage / "project.yaml"] = atomic_write(stage / "project.yaml", original_config, 0o600)
                if __package__:
                    from .windows_fs import copy_permissions
                else:
                    from windows_fs import copy_permissions
                copy_permissions(runtime / "project.yaml", stage / "project.yaml")
            else:
                shutil.copy2(runtime / "project.yaml", stage / "project.yaml")
        # 先保留升级前的项目配置，再只补默认名称；修改留在暂存区，预检失败或
        # 发布回滚时仍可恢复旧配置。宿主 --check / --preflight 本身保持只读。
        configured_identity = _initialize_project_name(stage / "project.yaml", project)
        if configured_identity is not None:
            created_files[stage / "project.yaml"] = configured_identity
        manifest = {
            "schema_version": 1,
            "managed_files": _managed_files(stage),
        }
        manifest_body = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if os.name == "nt":
            created_files[stage / MANIFEST_NAME] = atomic_write(stage / MANIFEST_NAME, manifest_body, 0o600)
            digests = manifest["managed_files"] | {
                name: _digest(stage / name) for name in ("project.yaml", MANIFEST_NAME)
            }
            stage_inventory = {
                name: (digest, created_files[stage / name]) for name, digest in digests.items()
                if created_files.get(stage / name) is not None
            }
            if __package__:
                from .windows_fs import flush_tree
            else:
                from windows_fs import flush_tree
            flush_tree(stage)
        else:
            (stage / MANIFEST_NAME).write_bytes(manifest_body)
        _run_setup(stage, project, "--preflight")

        standard_snapshots = _standard_update_snapshots(stage, project) if upgrading else []
        if upgrading:
            # 发布前保留准确入口状态。仅恢复旧运行时不足以撤回新入口：
            # 原运行时可能采用不同入口合同，不能要求它识别本轮新增产物。
            claude_entry = project / "CLAUDE.md"
            claude_before = read_file(claude_entry)
            claude_mode = stat.S_IMODE(claude_entry.stat().st_mode) if claude_before is not None else 0o644
            backup = project / f".agent-workflow-backup-{uuid.uuid4().hex[:12]}"
        hook_snapshots: list[tuple[Path, bytes | None, bytes, int]] = []
        setup_started = False
        try:
            # 两次目录发布也在事务异常边界内；取消不能留下只有 backup 的悬空项目。
            if backup is not None:
                os.replace(runtime, backup)
            os.replace(stage, runtime)
            if backup is not None:
                for host in ("claude", "codex", "antigravity"):
                    path, before, after = plan_hooks(runtime, project, host, simulate_codex_setup=host == "codex")
                    mode = stat.S_IMODE(path.stat().st_mode) if before is not None else 0o644
                    hook_snapshots.append((path, before, after, mode))
            setup_started = True
            _run_setup(runtime, project)
            _run_setup(runtime, project, "--check")
        except (subprocess.CalledProcessError, OSError, ValueError, KeyboardInterrupt) as exc:
            runner = ACTIVE_RUNNER.get()
            if runner is not None:
                runner.begin_recovery()
            failure = (f"退出码 {exc.returncode}" if isinstance(exc, subprocess.CalledProcessError)
                       else "用户取消" if isinstance(exc, KeyboardInterrupt) else str(exc))
            if backup is not None and not backup.exists():
                raise InstallError(f"升级发布未开始（{failure}），旧运行时保持原状。") from exc
            if backup is not None and not runtime.exists():
                # 以实际目录状态识别“replace 已完成，标志赋值前被中断”的情况。
                os.replace(backup, runtime)
                raise InstallError(f"升级发布中断（{failure}），旧运行时已恢复。") from exc
            # 首次安装可能已经写入部分宿主入口；此时必须保留它们引用的
            # .agent-workflow 路径，不能把运行时搬走造成悬空指令。
            if backup is None:
                raise InstallError(
                    f"首次安装或验收失败（{failure}）；"
                    f"运行时仍在 {runtime}，请检查并重试，原始安装包尚不可删除。"
                ) from exc

            # 升级失败时保留失败版本供诊断，再恢复旧运行时和宿主入口，
            # 避免旧版本被新版本的部分产物覆盖后无法继续使用。
            failed = project / f".agent-workflow-failed-{uuid.uuid4().hex[:12]}"
            os.replace(runtime, failed)
            os.replace(backup, runtime)
            if not setup_started:
                # 快照准备失败时尚未发布任何宿主产物；仅恢复运行时，不覆盖预检后
                # 用户更改的配置，也不运行一个可能再次写入项目的旧安装脚本。
                raise InstallError(
                    f"升级发布前准备失败（{failure}）；旧运行时已恢复，用户配置保持原状；"
                    f"失败版本保留在 {failed}。"
                ) from exc
            try:
                restore_errors: list[str] = []
                # 文档冲突不能阻止薄入口与 Hook 的独立安全恢复；任一冲突仍会
                # 阻止执行旧 setup，避免它重新写入需要人工核对的并发项目文档。
                for restore in (
                    lambda: _restore_standard_updates(standard_snapshots),
                    lambda: _restore_claude_entry(project, claude_before, claude_mode),
                    lambda: _restore_hook_configs(hook_snapshots),
                ):
                    try:
                        restore()
                    except (InstallError, OSError, ValueError) as restore_exc:
                        restore_errors.append(str(restore_exc))
                if restore_errors:
                    raise InstallError("; ".join(restore_errors))
                _run_setup(runtime, project)
                _run_setup(runtime, project, "--check")
            except (InstallError, OSError, UnicodeError, ValueError) as restore_exc:
                raise InstallError(
                    f"新版本安装失败，旧运行时已恢复，但入口/Hook/规范无法安全恢复：{restore_exc}；"
                    f"失败版本保留在 {failed}，请人工核对上述文件。"
                ) from restore_exc
            except subprocess.CalledProcessError as restore_exc:
                raise InstallError(
                    f"新版本安装失败，旧运行时已恢复，但旧入口重建也失败；"
                    f"请检查 {failed} 与命令退出码 {restore_exc.returncode}。"
                ) from restore_exc
            raise InstallError(
                f"安装或验收失败（{failure}）；失败版本保留在 {failed}，"
                "原始安装包尚不可删除。"
            ) from exc

        print(f"[完成] 项目运行时：{runtime}")
        if backup is not None:
            print(f"[备份] 上一版本保留在：{backup}")
        print(
            "[完成] 可移除本次使用的原始 agent_workflow 安装包；"
            "项目内 .agent-workflow 必须保留。"
        )
    finally:
        if stage.exists():
            if os.name == "nt":
                if __package__:
                    from .windows_process import WindowsJobCleanupError
                else:
                    from windows_process import WindowsJobCleanupError
                if not isinstance(sys.exception(), WindowsJobCleanupError):
                    _discard_windows_stage(stage, stage_inventory)
            else:
                shutil.rmtree(stage)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="install.sh",
        description="将 agent_workflow 安装到指定项目，安装后原始安装包可移除。"
    )
    parser.add_argument("project", nargs="?", help="项目根目录；省略时可拖入终端")
    parser.add_argument("--timeout", type=float, help="安装事务的应用预算秒数；超时后停止 setup 并执行恢复")
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parent.parent
    try:
        raw = args.project
        if raw is None:
            raw = input("请将需要安装的项目文件夹拖入终端，然后按回车：")
        project = _target_path(raw, source_root)
        print(f"[目标] {project}", flush=True)
        if args.timeout is None:
            _install(project, source_root)
        else:
            _install(project, source_root, timeout=args.timeout)
    except (EOFError, KeyboardInterrupt):
        print("\n[取消] 未安装。", file=sys.stderr)
        return 2
    except (InstallError, OSError, ValueError, subprocess.CalledProcessError, SetupRunError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
