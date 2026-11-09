"""Explicit filesystem backend selection; importing it never changes stdlib os."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re

if os.name == "nt":
    if __package__:
        from .windows_fs import secure_os as os, directory_lock, project_mode
    else:
        from windows_fs import secure_os as os, directory_lock, project_mode
else:
    def project_mode(mode: int, *, directory=False) -> int:
        return mode

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
        if __package__:
            from .windows_fs import move_regular, node_snapshot
        else:
            from windows_fs import move_regular, node_snapshot
        parent = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            expected = node_snapshot(parent, source.name)
            if expected is None:
                raise FileNotFoundError(str(source))
            # Windows rename 已消费源名称；句柄内再次核对完整快照，调用者不能
            # 再 unlink source。POSIX 的 link/unlink 发布合同在下方维持不变。
            move_regular(source.name, target, src_dir_fd=parent, expected=expected)
        finally:
            os.close(parent)
    else:
        os.link(source, target, follow_symlinks=False)
        os.unlink(source)


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
    Windows 使用受管 Skill 专用的句柄边界，普通未知重解析点仍然拒绝。
    """
    require_skill_symlinks()
    core_root, target = Path(core_root), Path(target)
    if (not re.fullmatch(r"(?:xy-[a-z0-9]+(?:-[a-z0-9]+)*|grill-me)", name)
            or not core_root.is_absolute() or core_root.name != "core"
            or not re.fullmatch(r"[0-9a-f]{64}", core_root.parent.name)
            or core_root.parent.parent.name != "runtimes"
            or target != core_root / "platforms/shared/skills" / name):
        raise ValueError("受管 Skill 链接只能指向选定中央版本的同名 Skill")
    if os.name == "nt":
        if __package__:
            from .windows_fs import create_skill_symlink
        else:
            from windows_fs import create_skill_symlink
        create_skill_symlink(directory, name, target, core_root=core_root)
    else:
        os.symlink(str(target), name, dir_fd=directory, target_is_directory=True)
        os.fsync(directory)


def require_skill_symlinks() -> None:
    """发布前确认具备 no-follow、dir_fd 软链能力；缺少能力时失败关闭。"""
    if os.name == "nt":
        if __package__:
            from .windows_fs import require_skill_symlinks as windows_require
        else:
            from windows_fs import require_skill_symlinks as windows_require
        windows_require()
    elif (os.symlink not in os.supports_dir_fd or os.readlink not in os.supports_dir_fd):
        raise ValueError("当前文件系统后端不支持安全的受管 Skill 软链发布")
