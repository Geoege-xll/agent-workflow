"""读取受控 Markdown 中的普通行内链接；保持物理行号，代码示例不生成关系。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Iterator


@dataclass(frozen=True)
class MarkdownLink:
    raw: str
    label: str
    start: int
    end: int


_TICKS = re.compile(r"`+")
# 扫描器只认同一行的 [标题](目的地)，图片、转义括号和引用式链接均不产生文档关系。
_OPEN = re.compile(
    r"""\\[\\!\[\]]|</?[A-Za-z][\w-]*(?=[\s/>])(?:[^<>"']|"[^"]*"|'[^']*')*>|!?\[([^\[\]\n]*)\]\("""
)
_REFERENCE_LABEL = r"[^\[\]\n]{1,999}"
# 引用式的候选共用行内链接的扫描位置，避免重新扫描 URL、标题或 HTML 属性里的方括号。
# 普通关系查询保持原有行内链接合同；只有调用者实际提供定义时才匹配引用标签。
_WITH_REFERENCES = re.compile(_OPEN.pattern + rf"|(!?)\[({_REFERENCE_LABEL})\](?:\[({_REFERENCE_LABEL})?\])?")
_REFERENCE_TITLE = r"""(?:"[^"]*"|'[^']*'|\([^()]*\))"""
_DEFINITION = re.compile(rf"^ {{0,3}}\[({_REFERENCE_LABEL})\]:[ \t]*(?:<([^<>\n]+)>|([^\s<]\S*?))(?:[ \t]+({_REFERENCE_TITLE}))?[ \t]*$")
_DEFINITION_START = re.compile(rf"^ {{0,3}}\[{_REFERENCE_LABEL}\]:[ \t]*$")
_TITLE = re.compile(r"""(?:[ \t]+(?:"[^"]*"|'[^']*'|\([^()]*\)))?[ \t]*\)""")
_HTML_BLOCK = re.compile(r"^ {0,3}<(pre|script|style|textarea|code)\b", re.I)
_HTML_CONTAINER = re.compile(r"^ {0,3}</?(?:div|table|section|article|aside|details|figure|ul|ol|p|blockquote)\b", re.I)


def _without_inline_code(lines: list[str]) -> Iterator[str]:
    """按相同宽度的反引号配对，跨软换行保留行数；未闭合的字面反引号照常可见。"""
    if not any("`" in line for line in lines):
        yield from lines
        return
    paragraph = "\n".join(lines)
    # 先记每种宽度的最后位置，再顺扫一次。即使文档含大量未配对的反引号，也不会
    # 为每个可能的起点从头搜索。代码段里的反斜杠只是正文，不能转义其闭合符。
    last = {tick.end() - tick.start(): tick.start() for tick in _TICKS.finditer(paragraph)}
    output: list[str] = []
    copied = width = 0
    for tick in _TICKS.finditer(paragraph):
        size = tick.end() - tick.start()
        if width:
            if size == width:
                output.append(re.sub(r"[^\n]+", lambda m: " " * len(m[0]), paragraph[start:tick.end()]))
                copied, width = tick.end(), 0
        elif tick.start() < last[size]:
            before = tick.start()
            while before and paragraph[before - 1] == "\\":
                before -= 1
            if (tick.start() - before) % 2 == 0:
                start, width = tick.start(), size
                output.append(paragraph[copied:start])
    output.append(paragraph[copied:])
    yield from "".join(output).split("\n")


def without_html_blocks(visible: Iterable[str]) -> Iterator[str]:
    """保留物理行数，屏蔽 HTML 容器中的 Markdown 字面示例，包括看似列表项的行。"""
    html_end = ""
    for line in visible:
        stripped = line.lstrip()
        # 块引用和缩进代码可能嵌套多层围栏。受控资料以普通正文表达关系，只消费
        # 可确定的行；HTML 示例也不解释为 Markdown。空行终止普通 HTML 容器。
        block = _HTML_BLOCK.match(line)
        if block and not html_end:
            html_end = "</" + block[1].lower() + ">"
        elif not html_end and _HTML_CONTAINER.match(line):
            html_end = "\n"
        html = bool(html_end)
        if (html_end == "\n" and not stripped) or (html_end and html_end in line.lower()):
            html_end = ""
        yield "" if html else line


def prose_lines(visible: Iterable[str], *, include_containers: bool = False) -> Iterator[str]:
    """屏蔽代码与 HTML 示例；选中计划也检查引用块和缩进容器原有的资源引用。"""
    paragraph: list[str] = []
    for line in without_html_blocks(visible):
        stripped = line.lstrip()
        # 导航和关系只取普通正文；计划安全校验原本还覆盖引用块和缩进容器中的
        # 资源（如引用使用说明里的图片）。两种消费方式共用后续的行内代码屏蔽。
        container = line.startswith(("    ", "\t")) or stripped.startswith(">")
        skip = container and not include_containers
        # ATX 标题／列表项开启新块，前一段未闭合的行内代码不能吞入新的主题。
        new_block = re.match(r"^ {0,3}(?:#{1,6}|[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)", line)
        if skip or not stripped or new_block:
            if paragraph:
                yield from _without_inline_code(paragraph)
                paragraph.clear()
        if skip or not stripped:
            yield ""
        elif new_block and stripped.startswith("#"):
            yield from _without_inline_code([line])
        else:
            paragraph.append(line)
    if paragraph:
        yield from _without_inline_code(paragraph)


def _reference_key(label: str) -> str:
    """引用标签按大小写折叠并合并空白，对应普通阅读器里的同一条定义。"""
    return " ".join(label.casefold().split())


def document_links(prose: Iterable[str], *, include_images: bool = False) -> Iterator[tuple[int, MarkdownLink]]:
    """读取所用行内及引用式链接，可按需纳入图片。定义本身不产生引用，行号指向使用处。"""
    lines = list(prose)
    definitions: dict[str, str] = {}
    for index, line in enumerate(lines):
        # 定义的目的地和标题也可各占下一行，仍按使用位置报错。标题中出现的方括号
        # 只是说明文字，不能把标题示例再次解析成项目文件。
        end = index
        if _DEFINITION_START.fullmatch(line) and end + 1 < len(lines):
            end += 1
            line += " " + lines[end].lstrip(" \t")
        match = _DEFINITION.fullmatch(line)
        if match:
            # 定义可位于使用点之后。重复标签采用第一次定义；未定义的方括号在阅读器中
            # 是普通文字，未用到的定义也不会单独触发目标文件读取。
            definitions.setdefault(_reference_key(match[1]), match[2] or match[3])
            if not match[4] and end + 1 < len(lines) and re.fullmatch(_REFERENCE_TITLE, lines[end + 1].strip()):
                end += 1
            for consumed in range(index, end + 1):
                lines[consumed] = ""
    for number, line in enumerate(lines, 1):
        for link in line_links(line, references=definitions, include_images=include_images):
            yield number, link


def line_links(line: str, original: str | None = None, *, include_images: bool = False,
               references: dict[str, str] | None = None) -> Iterator[MarkdownLink]:
    """解析普通或尖括号目的地、平衡括号和可选标题。检查资源安全时可同时返回图片。"""
    pos = 0
    scanner = _WITH_REFERENCES if references else _OPEN
    while match := scanner.search(line, pos):
        pos = match.end()
        if references and match[3] is not None:
            raw = references.get(_reference_key(match[4] or match[3]))
            if raw and (include_images or not match[2]):
                yield MarkdownLink(raw, match[3], match.start(), pos)
            continue
        if match[1] is None:
            # HTML 标签属性中可包含 Markdown 示例；行内 code 元素的正文也只是代码。
            # 这里仍保留同一行在闭合元素之后的真实链接。
            if re.match(r"<code(?=[\s>])", match[0], re.I):
                end_tag = line.lower().find("</code>", pos)
                pos = end_tag + 7 if end_tag >= 0 else len(line)
            continue
        start = pos
        if line.startswith("<", start):
            end = line.find(">", start + 1, start + 4098)
            if end < 0:
                continue
            raw, pos = line[start + 1:end], end + 1
        else:
            # URI 内未转义的成对括号属于文件名；最外层的右括号才结束该目的地。
            depth = 0
            while pos < len(line) and not line[pos].isspace():
                char = line[pos]
                if char == "\\" and line[pos + 1:pos + 2] in ("(", ")"):
                    # 转义括号属于目的地字面值，不能改变外层链接的结束位置。
                    pos += 2
                    continue
                if char == ")" and not depth:
                    break
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                pos += 1
            raw = line[start:pos]
            if depth:
                continue
        tail = _TITLE.match(line, pos)
        if not tail:
            continue
        pos = tail.end()
        # 图片对关系查询是嵌入资源；指定计划的路径安全校验则须检查其真实节点。
        if raw and (include_images or not match[0].startswith("!")):
            # 原文只用于显示标题。判定链接仍依据掩码后的行，因此标题内用行内
            # 代码排版的文件名能展示，而被转义或作为代码展示的整个链接不会进入结果。
            label = (original if original is not None else line)[match.start(1):match.end(1)]
            yield MarkdownLink(raw, label.strip(), match.start(), pos)
