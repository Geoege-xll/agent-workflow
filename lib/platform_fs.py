"""Explicit filesystem backend selection; importing it never changes stdlib os."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re

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
    Windows 当前安全后端尚未提供锚定重解析点发布，必须在任何项目写入前
    由调用方调用 require_skill_symlinks 拒绝，不能偷偷复制 Skill 正文。
    """
    require_skill_symlinks()
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
    """发布前确认具备 no-follow、dir_fd 软链能力；缺少能力时失败关闭。"""
    if (os.name == "nt" or os.symlink not in os.supports_dir_fd
            or os.readlink not in os.supports_dir_fd):
        raise ValueError("当前文件系统后端不支持安全的受管 Skill 软链发布")
