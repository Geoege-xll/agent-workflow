"""定向检查项目 Markdown 可点击的本地引用，错误定位在实际引用方。"""

from __future__ import annotations

from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
from itertools import groupby
from pathlib import Path
import re
from typing import Iterable, Iterator
from urllib.parse import unquote, urlsplit

from lib.documents.markdown_headings import iter_visible_lines, markdown_anchors, visible_markdown_lines
from lib.documents.markdown_links import document_links, prose_lines, without_html_blocks
from lib.documents.safe_documents import snapshot


_QUOTE = re.compile(r"^(?: {0,3}>[ \t]?)+")
_LIST_ITEM = re.compile(r"^ {0,3}(?:[-+*]|[0-9]{1,9}[.)])(?P<gap>[ \t]+|$)")
_ENTITY = re.compile(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);")


def _list_contents(lines: Iterable[str]) -> Iterator[tuple[int | None, str]]:
    """按条目标记宽度分出同层各列表项，保留每个物理行及条目内的相对缩进。"""
    item = None
    indent = 0
    for number, line in enumerate(lines):
        # Markdown 的制表位宽四列；只展开前导缩进，不改链接地址和正文中的字符。
        prefix = len(line) - len(line.lstrip(" \t"))
        line = line[:prefix].expandtabs(4) + line[prefix:]
        if item is not None and (not line.strip() or line.startswith(" " * indent)):
            yield item, line[indent:]
            continue
        marker = _LIST_ITEM.match(line)
        if marker:
            # 标记后的一至四格属于条目缩进。五格及以上只消费一格，余下四格
            # 是条目内真正的代码缩进。空项也按标记后占一格确定后续正文列。
            gap = len(marker[0].expandtabs(4)) - marker.start("gap")
            indent = marker.start("gap") + (gap if 1 <= gap <= 4 else 1)
            item = number
            extra = gap - 1 if gap > 4 else 0
            yield item, " " * extra + line[marker.end():]
        else:
            item = None
            yield None, line


def _list_prose(lines: Iterable[str], depth: int = 0) -> Iterator[str]:
    """先去除每层条目的相对缩进，再用同一围栏和代码屏蔽器读取其正文。"""
    for item, block in groupby(_list_contents(without_html_blocks(lines)), key=lambda row: row[0]):
        contents = (content for _, content in block)
        if item is None:
            yield from prose_lines(contents)
        else:
            # 在进入嵌套列表前屏蔽本层围栏；代码示例里的列表标记不能开启新项。
            # 超深容器明确报错，避免恶意同一行反复嵌套耗尽解释器栈并误报检查通过。
            if depth >= 32:
                raise ValueError("列表嵌套超过 32 层，无法完整检查链接")
            masked = iter_visible_lines(contents, hide_comments=True, list_fences=True)
            yield from _list_prose(masked, depth + 1)


def document_prose(body: str) -> Iterator[str]:
    """引用块里也能出现可点击链接；去掉引用标记后仍须屏蔽该块里的围栏和行内代码。"""
    def quote_content(line: str) -> tuple[int, str]:
        prefix = _QUOTE.match(line)
        return (prefix[0].count(">"), line[prefix.end():]) if prefix else (0, line)

    # 先遮住外层围栏，再按连续引用层级处理。一个引用块里的未闭合围栏不应吞掉块外的正文。
    # 各层只移除行首标记；每个输入行仍输出一行，以便将断链准确定位到作者的实际来源。
    for depth, block in groupby(map(quote_content, visible_markdown_lines(body)), key=lambda row: row[0]):
        lines = (content for _, content in block)
        if depth:
            lines = iter_visible_lines(lines, hide_comments=True, list_fences=True)
        yield from _list_prose(lines)


HTML_SUFFIXES = {".html", ".htm"}


class _HtmlAnchors(HTMLParser):
    """收集静态文档中的真实节点；脚本字串、注释、模板和文本示例不会生成链接目标。"""

    CDATA_CONTENT_ELEMENTS = ("script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = set()
        self.templates = 0

    def handle_starttag(self, tag, attributes):
        if not self.templates:
            # 同名属性在 HTML 中以首个为准，普通元素的 name 并非命名锚点。
            attrs = dict(reversed(attributes))
            for name in ("id", "name") if tag == "a" else ("id",):
                if attrs.get(name):
                    self.anchors.add(attrs[name])
        if tag == "template":
            self.templates += 1

    def handle_endtag(self, tag):
        if tag == "template" and self.templates:
            self.templates -= 1


def decoded_link(raw: str) -> str:
    # 只展开带分号的实体和 Markdown 转义的括号，文件名中的 &copy.md 保持原样。
    return re.sub(r"\\([()])", r"\1", _ENTITY.sub(lambda match: unescape(match[0]), raw))


def target_anchors(path):
    # 目标沿用同一单链接、无软链祖先、UTF-8 和大小上限。解析器仅消费静态文本。
    data, _ = snapshot(path)
    text = data.decode("utf-8")
    if path.suffix.lower() in HTML_SUFFIXES:
        parser = _HtmlAnchors()
        parser.feed(text)
        parser.close()
        return parser.anchors
    return markdown_anchors(text)


def body_link_errors(root, source, body, read_anchors, *, html_only=False):
    from lib.documents.plan_documents import local_target
    errors = []
    label = source.relative_to(root).as_posix()
    own_anchors = None
    for number, link in document_links(document_prose(body)):
        try:
            # Markdown 只在实体带分号时解码；例如文件名里的 &copy.md 应保留原样。
            raw = decoded_link(link.raw)
            if any(ord(char) < 32 or ord(char) == 127 for char in raw):
                raise ValueError("链接中含控制字符")
            address = urlsplit(raw)
            # 网络地址、mailto 等交由阅读器处理，既不联网也不检查站外片段。
            if html_only:
                suffix = Path(unquote(address.path, errors="strict")).suffix.lower()
                if not address.fragment or suffix not in HTML_SUFFIXES:
                    continue
            if address.scheme == "file":
                raise ValueError("本地链接须相对于项目文档")
            if address.netloc or address.scheme:
                continue
            target = source
            if address.path:
                target = local_target(root, source, address.path, inspect_only=True, allow_spaces=True)
            if not address.fragment or target.suffix.lower() not in {".md", *HTML_SUFFIXES} or target.is_dir():
                continue
            fragment = unquote(address.fragment, errors="strict")
            # 自身片段用读取链接的同一份正文，避免文件恰在两次读取间变更时混用版本。
            if target == source:
                if own_anchors is None:
                    own_anchors = markdown_anchors(body)
                anchors = own_anchors
            else:
                anchors = read_anchors(target)
            if fragment not in anchors:
                kind = "HTML id 或 a[name]" if target.suffix.lower() in HTML_SUFFIXES else "ATX 标题或单行显式锚点"
                raise ValueError(f"找不到 {kind} #{fragment}")
        except FileNotFoundError:
            errors.append(f"{label}:{number}: 目标不存在：{link.raw!r}")
        except (OSError, ValueError) as exc:
            errors.append(f"{label}:{number}: {link.raw!r}：{exc}")
    return errors


def validate_document_links(root: Path, documents: list[Path]) -> list[str]:
    """只读检查指定来源及直接目的地，按引用方与实际行号报告错误。"""
    from lib.documents.plan_documents import project_directory, project_path
    root = project_directory(root)
    errors = []
    checked = set()
    read_anchors = lru_cache(maxsize=32)(target_anchors)
    for selected in documents:
        try:
            source = project_path(root, selected)
            if source.suffix.lower() != ".md":
                raise ValueError("--document 须指定项目内的 Markdown (.md) 文件")
            if source in checked:
                continue
            checked.add(source)
            data, _ = snapshot(source)
            errors.extend(body_link_errors(root, source, data.decode("utf-8"), read_anchors))
        except (OSError, ValueError) as exc:
            errors.append(f"{selected}: {exc}")
    return errors
