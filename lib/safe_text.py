"""在插件和项目中按 UTF-8 读取有界普通文件，拒绝符号链接与特殊节点。"""

from contextlib import contextmanager
import os
from pathlib import Path
import stat


@contextmanager
def open_file(path: Path):
    """共用安全打开边界；调用者为自己读取的范围设置限额和编码检查。"""
    for parent in path.parents:
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f"unsafe instruction parent: {parent}")
    try:
        info = path.lstat()
    except FileNotFoundError:
        yield None
        return
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"instruction must be a single-link regular file: {path}")
    # 沿用包内安全读取方式：支持的平台使用内核 no-follow，其余仍核对节点身份。
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError(f"instruction changed while opening: {path}")
        yield stream


def read_file(path: Path) -> bytes | None:
    """按原限额读取完整 UTF-8 字节；缺失叶节点返回 None。"""
    with open_file(path) as stream:
        if stream is None:
            return None
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError(f"instruction exceeds safe read size: {path}")
    data.decode("utf-8", errors="strict")
    return data
