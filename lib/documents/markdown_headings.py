"""共享 Markdown 标题、锚点与原文坐标，供定点读取、目录和链接校验使用。"""

from __future__ import annotations

from io import StringIO
from itertools import tee
import re
from typing import Iterable, Iterator

from lib.documents.markdown_links import prose_lines


ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*)?$")
COMMENT_OR_INLINE_CODE = re.compile(r"<!--|-->|`+|\\[\\<`]")


def _mask_comment_line(line: str, in_comment: bool) -> tuple[str, bool]:
    """在一行内屏蔽 HTML 注释，向下一行携带尚未闭合的注释状态。"""
    if not in_comment and "<!--" not in line:
        return line, False
    tokens = list(COMMENT_OR_INLINE_CODE.finditer(line))
    inline_ends: dict[int, int] = {}
    next_tick: dict[int, int] = {}
    # 行内代码可展示 `<!--` 示例。一次逆序查找同宽结束符，避免对每个反引号
    # 从头重扫长行；未配对的反引号只是文字，不能隐藏其后的真实注释。
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index][0]
        if token.startswith("`"):
            width = len(token)
            if width in next_tick:
                inline_ends[index] = next_tick[width]
            next_tick[width] = index

    output: list[str] = []
    visible_from = 0
    comment_from = 0 if in_comment else None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if comment_from is not None:
            if token[0] == "-->":
                output.append(line[visible_from:comment_from])
                output.append(" " * (token.end() - comment_from))
                visible_from = token.end()
                comment_from = None
        elif token[0] == "<!--":
            comment_from = token.start()
        elif index in inline_ends:
            index = inline_ends[index]
        index += 1
    if comment_from is not None:
        output.append(line[visible_from:comment_from])
        output.append(re.sub(r"[^\r\n]", " ", line[comment_from:]))
    else:
        output.append(line[visible_from:])
    return "".join(output), comment_from is not None


_LIST_MARKER = re.compile(r"^ {0,3}(?P<marker>[-+*]|[0-9]{1,9}[.)])(?:[ \t]+(?P<content>.*)|$)")


def _list_content(line: str, indents: list[int]) -> tuple[int, str]:
    """定位列表内容相对行首的缩进；保留各祖先，以便从子列表退回父项的围栏。"""
    # 仅解析结构时按 Markdown 的四列制表位计算；最终返回的标题、正文和
    # 字符坐标都来自原行。空行不会提前结束列表或跨行围栏。
    line = line.expandtabs(4)
    leading = len(line) - len(line.lstrip(" "))
    if leading != len(line):
        while indents and leading < indents[-1]:
            indents.pop()
    base = indents[-1] if indents else 0
    content = line[base:]
    item = _LIST_MARKER.fullmatch(content)
    if item:
        # 标记后多于四个空格时，Markdown 只使用一个作列表间隔；剩余
        # 缩进属于项目内容，可能是缩进代码，不能误判成紧跟列表的围栏。
        marker_end = item.end("marker")
        padding = (item.start("content") - marker_end) if item["content"] else 1
        step = marker_end + (padding if 1 <= padding <= 4 else 1)
        base += step
        indents.append(base)
        content = content[step:]
    return base, content


def _section_container(line: str, in_list: bool) -> bool:
    """精确分页仅处理可确定的顶层标题；复杂容器交回有界字面查找。"""
    content = line.lstrip(" \t")
    item = _LIST_MARKER.fullmatch(line)
    if item:
        content = (item["content"] or "").lstrip(" \t")
    # 围栏和独立 HTML 注释由原解析器屏蔽。原生 HTML、块引用及列表内
    # 的结构行需要完整的块级解析器，推测哪里结束会提前报 EOF 或吞入邻节。
    # 项目文档常用的单行空锚点完整闭合，也不能按独立的 HTML 标签起块。
    standalone_comment = bool(re.match(r"^ {0,3}<!--", line))
    anchor = re.fullmatch(r' {0,3}<a (?:id|name)="[^"<>]*"></a>[ \t]*', line)
    nested = item is not None or (in_list and line.startswith((" ", "\t")))
    structural = r"(?:#{1,6}(?:[ \t]|$)|`{3,}|~{3,}|<|>)"
    # 模板开头的普通引用提示不会开启跨行结构；只有引用中的嵌套结构需回退。
    quoted_structure = content.startswith(">") and re.match(structural, content[1:].lstrip(" \t"))
    if ((content.startswith("<") and not standalone_comment and not anchor)
            or ("<!--" in line and not standalone_comment)
            or quoted_structure or (nested and re.match(structural, content))):
        raise ValueError("文档含复杂 HTML、块引用或嵌套 Markdown，须用 --find 核对范围")
    # 普通列表项不妨碍后面的顶层章节；无缩进 ATX 标题一定会结束之前的列表。
    return (in_list or item is not None) and not (line.startswith("#") and ATX_HEADING.fullmatch(line))


def iter_visible_lines(lines: Iterable[str], *, hide_comments: bool = False,
                       section_mode: bool = False, list_fences: bool = False) -> Iterator[str]:
    """保留原行和偏移，支持在首个真实章节停读；旧目录仍使用原围栏语义。"""
    fence = ""
    width = 0
    list_indent = 0
    in_comment = False
    in_list = False
    item_indents: list[int] = []
    for line in lines:
        content = line.rstrip("\r\n")
        if list_indent and section_mode:
            content = content.expandtabs(4)
        if list_indent and content.strip() and not content.startswith(" " * list_indent):
            # 未在列表内关闭的围栏随列表结束；重新按普通行处理本行。
            fence, list_indent = "", 0
        indent = 0
        if list_fences and not fence and not in_comment:
            if section_mode:
                indent, content = _list_content(content, item_indents)
            else:
                # 旧计划证据允许最多三空格缩进的普通围栏，即使前文以列表
                # 结束也沿用顶层解释。只把标记与围栏同一行的情况绑定到该列表。
                item = _LIST_MARKER.fullmatch(content)
                if item and item["content"]:
                    indent, content = item.start("content"), item["content"]
        elif list_indent:
            content = content[list_indent:]
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", content)
        opening = marker and not (marker[1][0] == "`" and "`" in marker[2])
        if section_mode and not fence:
            # 新导航只有在已认出有效围栏时才略过容器歧义检查；旧 --section
            # 沿用原来的保守拒绝。普通嵌套标题、HTML、块引用仍须核对结构。
            if not in_comment and not (list_fences and opening):
                in_list = _section_container(line.rstrip("\r\n"), bool(item_indents) if list_fences else in_list)
            if (in_comment or "<!--" in line) and "-->" in line and line.partition("-->")[2].strip():
                raise ValueError("HTML 注释结束行含额外内容，须用 --find 核对范围")
        if fence:
            closing = marker and marker[1][0] == fence and len(marker[1]) >= width and not marker[2].strip()
            yield re.sub(r"[^\r\n]", " ", line)
            if closing:
                fence, list_indent = "", 0
        elif not in_comment and opening:
            # 将列表项内的首个围栏与其续行绑定。否则带两个空格的结束符会被误认
            # 为新的顶层围栏，随后整页真实主题链接都会被遮住。旧入口不启用此模式。
            fence, width, list_indent = marker[1][0], len(marker[1]), indent
            yield re.sub(r"[^\r\n]", " ", line)
        elif hide_comments:
            # 围栏内的注释标记只是示例，注释里的围栏也不能吞掉之后的真实章节。
            visible, in_comment = _mask_comment_line(line, in_comment)
            yield visible
        else:
            yield line


def without_fenced_code(body: str) -> str:
    """保留旧的仅围栏屏蔽语义，供已有评审的原字节合同使用。"""
    return "".join(iter_visible_lines(body.splitlines(keepends=True)))


def visible_markdown_lines(body: str) -> Iterator[str]:
    """逐行屏蔽示例围栏与 HTML 注释，保留行号及字符位置，供主题和关系查询共用。"""
    return iter_visible_lines(body.splitlines(), hide_comments=True, list_fences=True)


_FLAT_FRONTMATTER = re.compile(
    r"\A---[ \t]*(?:\r\n?|\n)(?:[\w-]+:[^\r\n]*(?:\r\n?|\n))+---[ \t]*(?:\r\n?|\n|\Z)"
)


def _heading_markers(body: str, *, navigation: bool = False) -> Iterator[tuple[int, int, int, str]]:
    """产生标题行的原文区间、级别与文字；级别 0 表示可能的 Setext 边界。"""
    # Skill 的平面键值页首有完整的 --- 起止行。新导航跳过这段元信息，防止
    # 闭合线被当成 Setext。没有匹配完整形状的普通分隔线沿用原有判断。
    header = _FLAT_FRONTMATTER.match(body) if navigation else None
    offset = header.end() if header else 0
    lines = StringIO(body, newline="")
    lines.seek(offset)
    previous_text = False
    # newline="" 保留 CRLF／独立 CR 的长度，每次只处理一行。屏蔽函数保留
    # 原字符数，所以注释、围栏中的假标题都不会截断章节或改变 Unicode 坐标。
    for visible in iter_visible_lines(lines, hide_comments=True, section_mode=True, list_fences=navigation):
        line = visible.rstrip("\r\n")
        heading = ATX_HEADING.fullmatch(line)
        if heading:
            yield offset, offset + len(visible), len(heading[1]), heading[2] or ""
        elif previous_text and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line):
            yield offset, offset + len(visible), 0, ""
        previous_text = heading is None and bool(line.strip())
        offset += len(visible)


def atx_section_bounds(body: str, title: str) -> tuple[int, int]:
    """定位唯一 ATX 标题的原文半开区间；含下级章节，止于下个同级或上级标题。"""
    start = end = None
    level = 0
    for offset, _, depth, name in _heading_markers(body):
        if depth:
            if start is not None and end is None and depth <= level:
                end = offset
            if name == title:
                if start is not None:
                    raise ValueError("章节标题不唯一，请用 --find 定位所需位置")
                start, level = offset, depth
        elif start is not None and end is None:
            # 项目受控 Markdown 约定使用 ATX 标题；若选区内出现可能是
            # Setext 标题的下划线，就无法证明边界，交给字面定位核对原文。
            raise ValueError("章节内出现可能的 Setext 标题，须用 --find 核对范围")
    if start is None:
        raise ValueError("未找到对应 ATX 章节标题，请用 --find 核对原文")
    return start, len(body) if end is None else end


def heading_ranges(body: str, path: tuple[str, ...], *, outline: bool,
                   subtree: bool) -> Iterator[tuple[int, int]]:
    """逐段给出所选标题／正文的原文半开区间，必须耗尽迭代以核对完整路径的唯一性。"""
    levels: list[int] = []
    names: list[str] = []
    found: set[int] = set()
    body_from = None
    for start, heading_end, level, title in _heading_markers(body, navigation=True):
        if not level:
            raise ValueError("文档出现可能的 Setext 标题，须用 --find 核对层级")
        if body_from is not None:
            yield body_from, start
            body_from = None
        # 下一个同级或更浅的标题结束旧节点。命令中的父子关系按实际嵌套，
        # 因而 H2 后的 H4 可以是直接孩子，无需创造一层文档里不存在的 H3。
        while levels and levels[-1] >= level:
            levels.pop()
            names.pop()
        levels.append(level)
        names.append(title)
        depth = len(names)
        current = tuple(names)
        if depth <= len(path) and path[:depth] == current:
            # 即使两个重名父节点的孩子不同，父路径本身也不唯一。继续扫描至
            # 文件末尾再发布结果，防止第一页已返回看似正确的另一分支正文。
            if depth in found:
                raise ValueError("标题路径存在同名兄弟，须用 --find 定位并用 --lines 核对")
            found.add(depth)
        if current[:len(path)] != path:
            continue
        if not outline and (depth == len(path) or subtree):
            body_from = start
        elif depth == len(path) + 1:
            yield start, heading_end
    if path and len(path) not in found:
        raise ValueError("未找到此 ATX 标题路径，请用 --outline 逐层核对")
    if body_from is not None:
        yield body_from, len(body)


def markdown_anchors(body: str) -> set[str]:
    """主题目录可跳到实际 ATX 标题或显式 HTML 锚点；示例围栏／注释不定义导航。"""
    anchors: set[str] = set()
    heading_ids: set[str] = set()
    next_suffix: dict[str, int] = {}
    original, for_headings = tee(visible_markdown_lines(body))
    for line, visible in zip(original, prose_lines(for_headings)):
        if not visible.strip():
            continue
        # 项目文档用单行空锚点为会改名的标题提供长期入口，匹配其原始大小写。
        anchor = re.fullmatch(r""" {0,3}<a\s+(?:id|name)=(["'])([^"'<>]+)\1\s*></a>[ \t]*""", line)
        if anchor:
            anchors.add(anchor[2])
        # 行内代码可以是标题文字的一部分，生成标题锚点时取可见标题的原文。
        heading = ATX_HEADING.fullmatch(line) if ATX_HEADING.fullmatch(visible) else None
        if heading and heading[2]:
            title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading[2])
            slug = re.sub(r"[^\w -]", "", re.sub(r"<[^>]+>", "", title).lower()).replace(" ", "-")
            unique = slug
            suffix = next_suffix.get(slug, 0)
            while unique in heading_ids:
                suffix += 1
                unique = f"{slug}-{suffix}"
            heading_ids.add(unique)
            next_suffix[slug] = suffix
    return anchors | heading_ids
