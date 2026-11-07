"""Explicit filesystem backend selection; importing it never changes stdlib os."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

if os.name == "nt":
    if __package__:
        from .windows_fs import secure_os as os, directory_lock
    else:
        from windows_fs import secure_os as os, directory_lock
else:
    @contextmanager
    def directory_lock(path, purpose="publication", *, blocking=False):
        import fcntl
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(descriptor, flags)
            yield descriptor
        finally:
            os.close(descriptor)


def publish_exclusive(source: Path, target: Path) -> None:
    """Publish a temporary regular file without replacing a concurrent target."""
    if os.name == "nt":
        os.rename(source, target)
    else:
        os.link(source, target, follow_symlinks=False)
        os.unlink(source)


def publish_exclusive_at(source: str, target: str, *, src_dir_fd: int, dst_dir_fd: int) -> None:
    """在已锚定父目录中排他移动完整节点，保留 inode 及其原权限。

    POSIX 复用原 no-follow link/unlink；Windows 用同卷句柄 rename，避免
    临时双硬链窗口触发普通文件安全守卫。软链输入只允许已经由业务验证的叶，
    不能借本函数跟随目标或复制正文；目标碰撞必须保留两边并报告失败。
    """
    if os.name == "nt":
        os.rename(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    else:
        os.link(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=False)
        os.unlink(source, dir_fd=src_dir_fd)


@contextmanager
def project_install_lock(project: Path):
    """Hold the same project identity until setup writers and recovery finish."""
    with directory_lock(project, "install"):
        if os.name == "nt":
            # Probe metadata durability before creating a stage or any project
            # file. Unsupported filesystem/account capabilities fail closed.
            descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        yield


def publish_skill_symlink(directory: int, name: str, target: Path, *, core_root: Path) -> None:
    """仅向已锚定的 Skill 父目录排他发布一个中央 Skill 链接。

    普通文件发布和读取合同完全不变。调用方须先用 runtime_store.load_core
    验证 core_root，并证明项目中的精确宿主路径归属本次事务；本函数只接受
    单个受管 Skill 的固定目标，不接受任意链接、相对目标或覆盖现有节点。
    安装/预览入口先执行真实能力检查；此处仍由同一安全后端完成真实发布，
    任何权限撤销或持久化失败继续传播，不能复制正文或更换链接类型。
    """
    core_root, target = Path(core_root), Path(target)
    if (not re.fullmatch(r"(?:xy-[a-z0-9]+(?:-[a-z0-9]+)*|grill-me)", name)
            or not core_root.is_absolute() or core_root.name != "core"
            or not re.fullmatch(r"[0-9a-f]{64}", core_root.parent.name)
            or core_root.parent.parent.name != "runtimes"
            or target != core_root / "platforms/shared/skills" / name):
        raise ValueError("受管 Skill 链接只能指向选定中央版本的同名 Skill")
    os.symlink(str(target), name, dir_fd=directory, target_is_directory=True)
    os.fsync(directory)


def require_skill_symlinks() -> None:
    """持久状态写入前，以当前令牌真实验证软链及目录持久化能力。

    探针只在随机私有临时目录内产生空目标和目录 SYMLINK，随调用清理，
    不写项目/中央状态、不设置权限或系统配置，也不缓存另一令牌的成功。
    路径、重解析点、权限与 FlushFileBuffers 的真实错误均原样传播。
    """
    if os.symlink not in os.supports_dir_fd or os.readlink not in os.supports_dir_fd:
        raise ValueError("当前文件系统后端不支持安全的受管 Skill 软链发布")
    if os.name != "nt":
        return
    root = Path(tempfile.gettempdir()) / ("agent-workflow-capability-" + uuid.uuid4().hex)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    anchor = os.open(root.parent, flags)
    parent = None
    root_identity = target_identity = None
    root_created = False
    failure = None
    stamp = lambda info: (info.st_dev, info.st_ino)

    def cleanup():
        # 后端 mkdir/symlink 可在真实创建完成后因验证/flush 抛错，所以不能
        # 以“函数尚未返回”推断没有节点。只有本次已锚定私有根内的精确类型、
        # 身份及真实替代目标一致，才回收；未知状态保留，不猜测或递归删除。
        if parent is None:
            try:
                os.stat(root.name, dir_fd=anchor, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise ValueError("能力探针根未取得完整锚定身份，保留现场")
        if (stamp(os.fstat(parent)) != root_identity
                or stamp(os.stat(root.name, dir_fd=anchor, follow_symlinks=False)) != root_identity):
            raise ValueError("能力探针根身份已变化，保留现场")
        if set(os.listdir(parent)) - {"target", "link"}:
            raise ValueError("能力探针出现未知内容，保留现场")
        try:
            linked = os.stat("link", dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            linked = None
        if linked is not None:
            if (target_identity is None or not stat.S_ISLNK(linked.st_mode)
                    or linked.st_nlink != 1
                    or os.readlink("link", dir_fd=parent) != str(root / "target")
                    or stamp(os.stat("link", dir_fd=parent, follow_symlinks=False)) != stamp(linked)):
                raise ValueError("能力探针链接归属或目标未知，保留现场")
            os.unlink("link", dir_fd=parent)
        try:
            target = os.stat("target", dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            target = None
        if target is not None:
            if (target_identity is None or not stat.S_ISDIR(target.st_mode)
                    or stamp(target) != target_identity):
                raise ValueError("能力探针目标身份未知，保留现场")
            os.rmdir("target", dir_fd=parent)  # 非空即失败，不删除未知后续内容。
        os.fsync(parent)

    try:
        # 创建也纳入受控生命周期；mkdir 后置失败尚未登记身份时，cleanup
        # 只报告保留路径，不能把随机名称本身当作删除授权。
        os.mkdir(root.name, 0o700, dir_fd=anchor)
        root_created = True
        root_identity = stamp(os.stat(root.name, dir_fd=anchor, follow_symlinks=False))
        parent = os.open(root.name, flags, dir_fd=anchor)
        if stamp(os.fstat(parent)) != root_identity:
            raise ValueError("能力探针根在打开期间变化")
        os.fsync(parent)
        os.mkdir("target", 0o700, dir_fd=parent)
        target_identity = stamp(os.stat("target", dir_fd=parent, follow_symlinks=False))
        os.symlink(str(root / "target"), "link", target_is_directory=True, dir_fd=parent)
        if os.readlink("link", dir_fd=parent) != str(root / "target"):
            raise ValueError("真实目录软链的目标与能力探针不一致")
        os.fsync(parent)
    except BaseException as primary:
        failure = primary
        raise
    finally:
        errors = []
        clean = False
        try:
            cleanup()
            clean = True
        except BaseException as cleanup_error:
            errors.append(cleanup_error)
        # 根目录的 pin 必须先释放才可在 Windows 删除；祖先 anchor 仍保持，
        # 删除前重核根身份。失败后的未知现场只关闭句柄，绝不追加猜测删除。
        if parent is not None:
            try:
                os.close(parent)
            except BaseException as close_error:
                errors.append(close_error)
        if clean and root_created and root_identity is not None and not errors:
            try:
                if stamp(os.stat(root.name, dir_fd=anchor, follow_symlinks=False)) != root_identity:
                    raise ValueError("能力探针根在删除前变化")
                os.rmdir(root.name, dir_fd=anchor)
                os.fsync(anchor)
            except BaseException as cleanup_error:
                errors.append(cleanup_error)
        try:
            os.close(anchor)
        except BaseException as close_error:
            errors.append(close_error)
        if errors:
            # 原 API/flush 失败必须保持其类型、对象及因果；清理失败仍逐项
            # 可见，不能吞错后报绿。没有主异常时，清理失败本身就是失败。
            import json
            retained = json.dumps({"capability_directory": str(root),
                                   "cleanup_errors": [repr(error) for error in errors]},
                                  ensure_ascii=False, sort_keys=True)
            if failure is not None:
                failure.add_note(retained)
            else:
                errors[0].add_note(retained)
                raise errors[0]
