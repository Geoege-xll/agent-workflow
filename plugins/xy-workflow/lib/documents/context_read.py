#!/usr/bin/env python3
"""只读定位或分页展开单个 UTF-8 文档，续查与续页绑定完整文件的 SHA-256。"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Iterable

from lib.documents.markdown_headings import atx_section_bounds, heading_ranges
from lib.safe_text import read_file
from lib.task_sources import PLUGIN_ENV, project_root, validate_task_source, validate_pack_source


# 预算只约束返回的文本字符数，不假定不同宿主／模型的 token 编码相同。
# 完整输入仍复用 read_file 的 4 MiB 上限；本工具不扫描目录，也不写缓存或读取状态。
DEFAULT_LIMIT = 6000
MAX_LIMIT = 24000
# 命中数限制位置元数据，片段上限避免一次命中带出整条超长行；--limit 另管片段总量。
DEFAULT_MAX_MATCHES = 8
MAX_MATCHES = 32
SNIPPET_CHARS = 96


class ContextReadError(ValueError):
    """输入、安全读取或版本绑定不满足分页合同；错误消息不包含文件正文。"""


def _identity(info) -> tuple[int, ...]:
    """比较内容与节点相关元数据；不比较可能因本次读取改变的访问时间。"""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _find_matches(text: str, literal: str, offset: int, limit: int, max_matches: int) -> dict[str, object]:
    """定位 Unicode 字面量，包含重叠命中；next_offset 指向第一个尚未返回的命中。"""
    matches = []
    remaining = limit
    line = 1
    line_start = 0
    # 逐个消费命中之前的换行，无须为每一行建立索引。CRLF 计作一个换行，
    # 因而落在 CR 或 LF 自身上的命中仍属于上一行，独立 CR 也能正确定位。
    breaks = re.finditer(r"\r\n?|\n", text)
    line_break = next(breaks, None)
    start = text.find(literal, offset)
    while start >= 0 and len(matches) < max_matches and remaining:
        while line_break is not None and line_break.end() <= start:
            line_start = line_break.end()
            line += 1
            line_break = next(breaks, None)
        # 片段从命中起点开始；即使长字面量超过预算，仍保留其完整半开区间，
        # 调用者可用普通分页及同一摘要准确展开。limit 仅计算实际返回的原文字符。
        snippet = text[start:start + min(SNIPPET_CHARS, remaining)]
        matches.append({
            "offset": start, "end_offset": start + len(literal),
            "line": line, "column": start - line_start + 1,
            "snippet": snippet, "snippet_end_offset": start + len(snippet),
        })
        remaining -= len(snippet)
        # 预取下一个起点可区分“恰好用完预算”和“还有未返回的命中”。
        start = text.find(literal, start + 1)
    return {"matches": matches, "next_offset": None if start < 0 else start, "eof": start < 0}


def _line_bounds(text: str, lines: str) -> tuple[int, int, int, int]:
    """把从 1 起算、两端均含的源码行号转换为字符半开区间，保留每行原始换行符。"""
    # 单个输入至多 4 MiB，超长数字不可能是有效行号；提前拒绝也避免整数转换异常。
    match = re.fullmatch(r"([1-9][0-9]{0,7}):([1-9][0-9]{0,7})", lines) if isinstance(lines, str) else None
    if not match:
        raise ContextReadError("lines 须为 起行:止行，两者均为从 1 开始的十进制行号")
    first, last = map(int, match.groups())
    if first > last:
        raise ContextReadError("lines 的起行不能大于止行")
    # 只遍历到所选末行，不为大文件建立逐行副本。CRLF、独立 CR 和 LF 均为
    # 单个行界；空文件和最后一个换行后的空匹配均不产生一条虚构的源码行。
    start = 0
    for number, line in enumerate(re.finditer(r"[^\r\n]*(?:\r\n?|\n|$)", text), 1):
        if line.start() == line.end():
            break
        if number == first:
            start = line.start()
        if number == last:
            return first, last, start, line.end()
    raise ContextReadError("lines 超出实际文件行数，请核对当前文件或行号")


def _heading_page(text: str, ranges: Iterable[tuple[int, int]], offset: int, limit: int) -> dict:
    """从选区返回至多 limit 个原文字符；所有坐标仍指向原文件，翻页可越过未选正文。"""
    fragments: list[str] = []
    page_start = None
    page_end = offset
    next_offset = None
    last_stop = 0
    for start, stop in ranges:
        last_stop = stop
        if stop <= offset or next_offset is not None:
            # 已满页也要耗尽扫描器，确认后面没有同名路径或无法判定的 Markdown 边界。
            continue
        if page_start is None:
            if offset and offset < start:
                raise ContextReadError("offset 位于未选中的内容，请沿 next_offset 续页")
            page_start = max(start, offset)
        start = max(start, offset)
        if not limit:
            next_offset = start
            continue
        end = min(start + limit, stop)
        fragments.append(text[start:end])
        limit -= end - start
        page_end = end
        if end < stop:
            next_offset = end
    if page_start is None and offset and offset != last_stop:
        raise ContextReadError("offset 超出指定标题的读取范围")
    return {"offset": offset if page_start is None else page_start, "end_offset": page_end,
            "next_offset": next_offset, "eof": next_offset is None, "text": "".join(fragments)}


def read_page(
    path: Path,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    expect_sha256: str | None = None,
    task_pack: Path | None = None,
    root: Path | None = None,
    find: str | None = None,
    max_matches: int | None = None,
    section: str | None = None,
    lines: str | None = None,
    heading: list[str] | tuple[str, ...] = (),
    outline: bool = False,
    subtree: bool = False,
) -> dict[str, object]:
    """返回文件页、字面命中、章节、行段或标题导航；各模式共享来源验证与快照。

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
    if find is not None and (not isinstance(find, str) or not find):
        raise ContextReadError("find 必须是非空字面量")
    # 路径按多次 --heading 的顺序原样比较，不按斜线拆分；跳级时照实际父子
    # 关系传参。ATX 最多六层，拒绝把单个字符串误作一串单字标题。
    if (not isinstance(heading, (list, tuple)) or len(heading) > 6
            or any(not isinstance(name, str) or "\r" in name or "\n" in name for name in heading)):
        raise ContextReadError("heading 须为至多六个单行 ATX 标题文字组成的路径")
    if type(outline) is not bool or type(subtree) is not bool:
        raise ContextReadError("outline 与 subtree 须为布尔值")
    if subtree and (not heading or outline):
        raise ContextReadError("subtree 只用于有 --heading 路径的正文读取")
    if (heading or outline) and any(value is not None for value in (section, lines, find)):
        raise ContextReadError("heading、outline 导航不能与 section、lines 或 find 混用")
    if lines is not None and (section is not None or find is not None):
        raise ContextReadError("lines 与 section、find 不能同时使用")
    if section is not None:
        if not isinstance(section, str) or not section.strip() or "\r" in section or "\n" in section:
            raise ContextReadError("section 必须是非空的单行 ATX 标题文字")
        if find is not None:
            raise ContextReadError("section 与 find 不能同时使用")
    if max_matches is not None:
        if find is None:
            raise ContextReadError("max-matches 仅用于 --find 查找")
        if type(max_matches) is not int or not 1 <= max_matches <= MAX_MATCHES:
            raise ContextReadError(f"max-matches 必须是 1..{MAX_MATCHES} 之间的整数")

    try:
        path = Path(path)
    except TypeError:
        raise ContextReadError("path 必须是单个文件路径") from None
    # 不 resolve 用户路径，否则可能先跟随符号链接再绕过已有安全边界。
    # 拒绝 .. 也避免其路径折叠掩盖中间父目录的真实节点。
    if ".." in path.parts:
        raise ContextReadError("path 不得包含父目录跳转 ..")
    try:
        # 先验证任务与项目均属于当前来源，再决定正文由插件还是项目提供。
        selected_root = project_root(root)
        if task_pack is not None:
            validate_pack_source(task_pack, root=selected_root)
        else:
            validate_task_source({}, root=selected_root)
        plugin_source = None
        if PLUGIN_ENV in os.environ:
            # 由插件资源所有者解析物理入口并核对本页的完整字节；项目同名路径
            # 可能是逻辑别名，回包中的 path 必须标识真正提供正文的文件。
            from lib.plugin_resources import read_pager_source
            plugin_source = read_pager_source(path, selected_root)
        if plugin_source is not None:
            path, body = plugin_source
        else:
            # 普通业务／scratch 文档仍使用原读取器，不跟随任意项目软链。
            bounded = root is not None or PLUGIN_ENV in os.environ
            path = (selected_root / path if bounded else path).absolute()
            # 插件资源授权不能外溢到普通项目文档；直接调用时遵循显式项目根。
            if PLUGIN_ENV in os.environ and not path.is_relative_to(selected_root):
                raise ContextReadError("普通项目文档必须位于实际项目根内")
            before = path.lstat()
            body = read_file(path)
            after = path.lstat()
            if body is None or _identity(before) != _identity(after) or len(body) != before.st_size:
                raise ContextReadError("文件在读取期间发生变化，请从 offset 0 重新读取")
        text = body.decode("utf-8", errors="strict")
    except ContextReadError:
        raise
    except UnicodeError:
        # UnicodeDecodeError 的默认说明可能包含坏字节；CLI 不回显任何正文片段。
        raise ContextReadError("文件必须是完整、有效的 UTF-8 文本") from None
    except FileNotFoundError:
        raise ContextReadError("文件不存在或在读取期间消失") from None
    except ValueError as exc:
        raise ContextReadError(
            "文件或固定版本不符合安全读取要求：须为单链接普通文件、无符号链接父目录且不超过 4 MiB；"
            + str(exc)
        ) from exc
    except OSError:
        raise ContextReadError("无法安全读取文件，请检查路径、节点类型与读取权限") from None
    digest = hashlib.sha256(body).hexdigest()
    if expect_sha256 is not None and digest != expect_sha256:
        raise ContextReadError("文件 SHA-256 已变化，拒绝续读；请从 offset 0 重新读取")

    if offset > len(text):
        raise ContextReadError("offset 超出文件总字符数")
    result = {
        "path": str(path),
        "sha256": digest,
        "position_unit": "unicode_characters",
        "offset": offset,
        "total_chars": len(text),
        "total_bytes": len(body),
    }
    if find is not None:
        return {**result, **_find_matches(text, find, offset, limit, max_matches or DEFAULT_MAX_MATCHES)}
    if heading or outline:
        try:
            ranges = heading_ranges(text, tuple(heading), outline=outline, subtree=subtree)
            return {**result, **_heading_page(text, ranges, offset, limit)}
        except ValueError as exc:
            raise ContextReadError(str(exc)) from exc
    stop = len(text)
    if section is not None:
        try:
            start, stop = atx_section_bounds(text, section)
        except ValueError as exc:
            raise ContextReadError(str(exc)) from exc
        result.update(section_start_offset=start, section_end_offset=stop)
    elif lines is not None:
        first, last, start, stop = _line_bounds(text, lines)
        result.update(first_line=first, last_line=last, lines_start_offset=start, lines_end_offset=stop)
    if section is not None or lines is not None:
        # 0 表示从所选范围首页开始；续页仍用文件绝对坐标，便于和查找结果核对。
        # EOF 仅指所选范围的边界；超长行也须按字符预算续页，不能泄出相邻正文。
        if offset == 0:
            offset = start
        if not start <= offset <= stop:
            raise ContextReadError("offset 超出指定读取范围")
        result.update(offset=offset)
    end = min(offset + limit, stop)
    eof = end == stop
    return {**result, "end_offset": end, "next_offset": None if eof else end,
            "eof": eof, "text": text[offset:end]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="明确指定一个 UTF-8 文本文件，不扫描目录")
    parser.add_argument("--offset", type=int, default=0, help="从 0 开始的 Unicode 字符位置")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"正文或所有命中片段合计的最大字符数，默认 {DEFAULT_LIMIT}，最多 {MAX_LIMIT}")
    parser.add_argument("--find", help="定位区分大小写的非空字面量，行列从 1 开始；保持相同字面量续查")
    parser.add_argument("--section", help="按唯一 ATX 标题文字（不含 # 前缀）读取本节和子节；续页传相同标题")
    parser.add_argument("--heading", action="append", default=[], metavar="标题",
                        help="从根依次重复传入各级 ATX 标题文字；默认仅读本节正文和直接子标题")
    parser.add_argument("--outline", action="store_true", help="仅列根或所选标题的直接子标题，沿 next_offset 续页")
    parser.add_argument("--subtree", action="store_true", help="读取 --heading 所指章节，包含全部下级章节")
    parser.add_argument("--lines", help="按从 1 开始的 起行:止行 读取原文（含两端）；续页传相同行段")
    parser.add_argument("--max-matches", type=int,
                        help=f"每次查找最多返回的命中数，默认 {DEFAULT_MAX_MATCHES}，最多 {MAX_MATCHES}")
    parser.add_argument("--expect-sha256", help="首次页的 sha256；offset > 0 时必填")
    parser.add_argument("--task-pack", type=Path, help="校验当前 schema 2 自包含任务包和项目来源")
    parser.add_argument("--root", type=Path, help="指定项目根，默认使用当前工作目录；插件入口已切换到所选项目")
    args = parser.parse_args()
    try:
        page = read_page(args.path, offset=args.offset, limit=args.limit,
                         expect_sha256=args.expect_sha256, task_pack=args.task_pack, root=args.root,
                         find=args.find, max_matches=args.max_matches, section=args.section, lines=args.lines,
                         heading=args.heading, outline=args.outline, subtree=args.subtree)
    except ContextReadError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    # 单页只输出一个结构化结果，不附带其他长文；JSON 转义保留原始换行字节语义。
    print(json.dumps(page, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
