"""文档消费者共用的只读快照与规范路径，不包含格式生成或发布入口。"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from lib.hosts.claude_instructions import read_file


class DocumentSafetyError(ValueError):
    """文档路径、文件类型或读取期间的身份不符合安全合同。"""


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def identity(info) -> tuple[int, ...]:
    # 读取本身可能改变访问时间，因此只固定节点身份、链接数与内容相关属性。
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def snapshot(path: Path, *, required: bool = True) -> tuple[bytes | None, tuple | None]:
    """复用 no-follow、单硬链接、UTF-8 和限额读取，并复核读取前后的身份。

    缺失叶节点也必须经过共用读取器，避免把符号链接祖先下的缺失文件当成安全路径。
    返回原始字节与固定身份，调用者可在产生证据前再次快照，拒绝期间的修改或替换。
    """
    try:
        before = path.lstat()
    except FileNotFoundError:
        if read_file(path) is not None:
            raise DocumentSafetyError(f"读取期间文件出现：{path}")
        if required:
            raise DocumentSafetyError(f"文件不存在：{path}")
        return None, None
    body = read_file(path)
    try:
        after = path.lstat()
    except FileNotFoundError as exc:
        raise DocumentSafetyError(f"读取期间文件变化：{path}") from exc
    if body is None or identity(before) != identity(after) or len(body) != before.st_size:
        raise DocumentSafetyError(f"读取期间文件变化：{path}")
    return body, identity(before)


def normalized_relative(raw: str) -> Path:
    """拒绝绝对路径、父跳转和等价别名，让声明路径只有一种稳定表示。"""
    path = PurePosixPath(raw)
    if (not raw or not path.parts or "\\" in raw or "\0" in raw or path.is_absolute()
            or path.as_posix() != raw or any(part in {".", ".."} for part in path.parts)):
        raise DocumentSafetyError(f"须使用规范的相对路径：{raw!r}")
    return Path(raw)
