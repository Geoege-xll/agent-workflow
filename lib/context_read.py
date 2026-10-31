#!/usr/bin/env python3
"""只读、按字符分页返回单个 UTF-8 文档，续页绑定完整文件的 SHA-256。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__:
    from .claude_instructions import read_file
else:
    from claude_instructions import read_file


# 预算只约束返回的文本字符数，不假定不同宿主／模型的 token 编码相同。
# 完整输入仍复用 read_file 的 4 MiB 上限；本工具不扫描目录，也不写缓存或读取状态。
DEFAULT_LIMIT = 6000
MAX_LIMIT = 24000


class ContextReadError(ValueError):
    """输入、安全读取或版本绑定不满足分页合同；错误消息不包含文件正文。"""


def _identity(info) -> tuple[int, ...]:
    """比较内容与节点相关元数据；不比较可能因本次读取改变的访问时间。"""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_page(
    path: Path,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    expect_sha256: str | None = None,
) -> dict[str, str | int | bool | None]:
    """返回连续的半开字符区间，完整重组须按 next_offset 读取到 eof。

    offset 与 limit 都基于 Python 解码后的 Unicode 字符，而非字节、行或 token。
    先按严格 UTF-8 解码原始字节，避免多字节中文被切坏或 CRLF 被自动归一化；
    超长单行也可直接按字符切页。续页强制核对完整字节 SHA，拒绝跨版本拼接。
    """
    if type(offset) is not int or offset < 0:
        raise ContextReadError("offset 必须是非负整数字符位置")
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ContextReadError(f"limit 必须是 1..{MAX_LIMIT} 之间的整数字符预算")
    if expect_sha256 is not None and (
            not isinstance(expect_sha256, str)
            or re.fullmatch(r"[a-f0-9]{64}", expect_sha256) is None):
        raise ContextReadError("expect-sha256 必须是 64 位小写十六进制 SHA-256")
    if offset > 0 and expect_sha256 is None:
        raise ContextReadError("续页 offset > 0 时必须提供 expect-sha256")

    try:
        path = Path(path)
    except TypeError:
        raise ContextReadError("path 必须是单个文件路径") from None
    # 不 resolve 用户路径，否则可能先跟随符号链接再绕过已有安全边界。
    # 拒绝 .. 也避免其路径折叠掩盖中间父目录的真实节点。
    if ".." in path.parts:
        raise ContextReadError("path 不得包含父目录跳转 ..")
    path = path.absolute()
    try:
        before = path.lstat()
        body = read_file(path)
        after = path.lstat()
    except UnicodeError:
        # UnicodeDecodeError 的默认说明可能包含坏字节；CLI 不回显任何正文片段。
        raise ContextReadError("文件必须是完整、有效的 UTF-8 文本") from None
    except FileNotFoundError:
        raise ContextReadError("文件不存在或在读取期间消失") from None
    except ValueError:
        raise ContextReadError(
            "文件不符合安全读取要求：须为单链接普通文件、无符号链接父目录且不超过 4 MiB"
        ) from None
    except OSError:
        raise ContextReadError("无法安全读取文件，请检查路径、节点类型与读取权限") from None
    # read_file 校验打开时的文件身份；这里补上读取结束后的变化与完整长度检查。
    # 即使变动后的文本恰好还可解码，也不能把它作为一次稳定的完整文件读取。
    if body is None or _identity(before) != _identity(after) or len(body) != before.st_size:
        raise ContextReadError("文件在读取期间发生变化，请从 offset 0 重新读取")
    digest = hashlib.sha256(body).hexdigest()
    if expect_sha256 is not None and digest != expect_sha256:
        raise ContextReadError("文件 SHA-256 已变化，拒绝续读；请从 offset 0 重新读取")

    text = body.decode("utf-8", errors="strict")
    if offset > len(text):
        raise ContextReadError("offset 超出文件总字符数")
    end = min(offset + limit, len(text))
    eof = end == len(text)
    return {
        "sha256": digest,
        "position_unit": "unicode_characters",
        "offset": offset,
        "end_offset": end,
        "next_offset": None if eof else end,
        "eof": eof,
        "total_chars": len(text),
        "total_bytes": len(body),
        "text": text[offset:end],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="明确指定一个 UTF-8 文本文件，不扫描目录")
    parser.add_argument("--offset", type=int, default=0, help="从 0 开始的 Unicode 字符位置")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"返回的最大字符数，默认 {DEFAULT_LIMIT}，最多 {MAX_LIMIT}")
    parser.add_argument("--expect-sha256", help="首次页的 sha256；offset > 0 时必填")
    args = parser.parse_args()
    try:
        page = read_page(args.path, offset=args.offset, limit=args.limit,
                         expect_sha256=args.expect_sha256)
    except ContextReadError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    # 单页只输出一个结构化结果，不附带其他长文；JSON 转义保留原始换行字节语义。
    print(json.dumps(page, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
