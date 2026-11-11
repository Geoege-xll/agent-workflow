"""对原生文件做保留字节的局部编辑；无法证明边界的语法明确拒绝。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import tomllib

from .contracts import ConfigError, MAX_FILE_BYTES, UnsupportedFormat, unique_json, validate_fields


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    value_start: int
    value_end: int
    comment_start: int | None
    indent: str


@dataclass(frozen=True)
class AgentDocument:
    name: str
    description: str
    fields: dict
    text: str
    spans: dict[str, Span]
    insertion: int
    newline: str


def _text(body: bytes) -> str:
    if not isinstance(body, bytes) or len(body) > MAX_FILE_BYTES:
        raise ConfigError("Agent 文件超过容量限制")
    try:
        value = body.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise UnsupportedFormat("Agent 文件必须是 UTF-8") from exc
    if value.startswith("\ufeff") or "\x00" in value:
        raise UnsupportedFormat("不支持含 BOM 或空字节的 Agent 文件")
    return value


def _metadata(data: dict, *, codex=False):
    name, description = data.get("name"), data.get("description")
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", name)
            or not isinstance(description, str) or not description.strip()):
        raise ConfigError("Agent 缺少有效 name / description")
    if codex and not isinstance(data.get("developer_instructions"), str):
        raise ConfigError("Codex Agent 缺少 developer_instructions")
    return name, description


def _statements(text: str):
    """识别 TOML 完整语句，字符串、注释和容器中的伪赋值不会变成字段。

    tomllib 先负责完整语法校验；此扫描器只定位语句，不尝试再次实现 TOML
    值语义。三引号的 4/5 引号结束形式也完整消费，避免尾引号误开新字符串。
    """
    start = index = depth = 0
    quote, comment = None, False
    while index < len(text):
        char = text[index]
        if comment:
            if char == "\n":
                comment = False
        elif quote is not None:
            if quote in {'"', '"""'} and char == "\\":
                index += 2
                continue
            if len(quote) == 3 and text.startswith(quote, index):
                run = 3
                while index + run < len(text) and text[index + run] == quote[0]:
                    run += 1
                if run > 5:
                    raise UnsupportedFormat("复杂 TOML 引号结束形式不支持局部编辑")
                index += run
                quote = None
                continue
            if len(quote) == 1 and char == quote:
                quote = None
        elif char == "#":
            comment = True
        elif char in "\"'":
            quote = char * 3 if text.startswith(char * 3, index) else char
            index += len(quote)
            continue
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        if char == "\n" and quote is None and depth == 0:
            yield start, index + 1
            start = index + 1
        index += 1
    if start < len(text):
        yield start, len(text)


def _comment(text: str, *, yaml=True) -> int | None:
    """定位单行标量外的注释；引号内 # 和单引号转义不是注释边界。"""
    quote, index = None, 0
    while index < len(text):
        char = text[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if quote == "'" and text[index:index + 2] == "''":
            index += 2
            continue
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#" and (not yaml or index == 0 or text[index - 1].isspace()):
            return index
        index += 1
    return None


def _toml(text: str) -> AgentDocument:
    try:
        data = tomllib.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ConfigError("原生 TOML 无效，未显示正文") from exc
    name, description = _metadata(data, codex=True)
    mapping = {"model": "model", "model_reasoning_effort": "effort"}
    fields = validate_fields("codex", {target: data[source] for source, target in mapping.items() if source in data})
    spans, insertion, root = {}, len(text), True
    for start, end in _statements(text):
        statement = text[start:end]
        stripped = statement.lstrip(" \t")
        if stripped.startswith("["):
            if root:
                insertion = start
            root = False
        if not root:
            continue
        match = re.match(r'''([ \t]*)(model_reasoning_effort|model|"model_reasoning_effort"|"model"|'model_reasoning_effort'|'model')([ \t]*=[ \t]*)(.*)''', statement)
        if match is None:
            continue
        key = match[2].strip("\"'")
        field = mapping[key]
        value = match[4].rstrip("\r\n")
        if "\n" in statement[match.start(4):].rstrip("\r\n"):
            raise UnsupportedFormat("多行 model / effort 不支持局部编辑")
        comment = _comment(value, yaml=False)
        token = value[:comment] if comment is not None else value
        token = token.rstrip(" \t\r\n")
        # 已解析的根字段必须是独立单行字符串；不能覆盖多行或奇异拼接形式。
        if not token or not (token.startswith('"') or token.startswith("'")):
            raise UnsupportedFormat("模型字段必须是独立字符串赋值")
        offset = start + match.start(4)
        spans[field] = Span(start, end, offset, offset + len(token),
                            offset + comment if comment is not None else None, match[1])
    if set(fields) != set(spans):
        raise UnsupportedFormat("无法精确定位原生根模型字段")
    return AgentDocument(name, description, fields, text, spans, insertion, "\r\n" if "\r\n" in text else "\n")


def _yaml_scalar(token: str):
    """仅解析无歧义标量和简单流式列表；锚点、标签和任意 YAML 对象不求值。"""
    if not token:
        return None
    if token.startswith('"'):
        try:
            value = json.loads(token)
        except ValueError as exc:
            raise UnsupportedFormat("复杂 YAML 双引号标量不支持") from exc
        if not isinstance(value, str):
            raise UnsupportedFormat("YAML 引号标量无效")
        return value
    if token.startswith("'"):
        if not re.fullmatch(r"'(?:[^']|'')*'", token):
            raise UnsupportedFormat("YAML 单引号标量无效")
        return token[1:-1].replace("''", "'")
    if token.startswith("["):
        if not token.endswith("]"):
            raise UnsupportedFormat("YAML 流式列表未闭合")
        contents = token[1:-1].strip()
        if not contents:
            return []
        # 分隔只允许一层、无引号逗号的简单元素；复杂列表明确只读。
        if any(char in contents for char in "[]{}\"'"):
            try:
                return unique_json(token.encode("utf-8"))
            except ValueError as exc:
                raise UnsupportedFormat("复杂 YAML 列表不支持") from exc
        parts = contents.split(",")
        if not parts[-1].strip():
            parts.pop()  # YAML 允许最后一个元素后有逗号，但中间空元素不接受。
        if any(not part.strip() for part in parts):
            raise UnsupportedFormat("YAML 列表包含空元素")
        return [_yaml_scalar(part.strip()) for part in parts]
    if token.startswith("{"):
        try:
            return unique_json(token.encode("utf-8"))
        except ValueError as exc:
            raise UnsupportedFormat("非 JSON 形式的 YAML 对象不支持") from exc
    if token[0] in "!&*|>@`%?" or ": " in token or "\t" in token or any(char in token for char in "{}[]"):
        raise UnsupportedFormat("复杂 YAML 标量不支持局部编辑")
    if token in {"true", "false", "null", "~"}:
        return {"true": True, "false": False, "null": None, "~": None}[token]
    return token


def _yaml(host: str, text: str) -> AgentDocument:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ConfigError("Agent 缺少 YAML frontmatter")
    closing = next((index for index, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "---"), None)
    if closing is None:
        raise ConfigError("Agent frontmatter 未闭合")
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    data, spans, index = {}, {}, 1
    while index < closing:
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):([ \t]*)([^\r\n]*)(\r?\n)?", line)
        if match is None or match[1] in data:
            raise UnsupportedFormat("重复字段或复杂 YAML 映射不支持")
        key, raw = match[1], match[3]
        comment = _comment(raw)
        token = (raw[:comment] if comment is not None else raw).rstrip()
        following = index + 1
        while following < closing and (not lines[following].strip() or lines[following].startswith((" ", "\t"))):
            following += 1
        nested = lines[index + 1:following]
        if token in {"|", "|-", "|+", ">", ">-", ">+"}:
            if key in {"name", "model", "effort"}:
                raise UnsupportedFormat("模型及名称字段不能使用块标量")
            if any(line.strip() and (not line.startswith(" ") or line.startswith("\t")) for line in nested):
                raise UnsupportedFormat("YAML 块标量缩进无效")
            content = [line for line in nested if line.strip()]
            indentation = len(content[0]) - len(content[0].lstrip(" ")) if content else 0
            if any(len(line) - len(line.lstrip(" ")) < indentation for line in content):
                raise UnsupportedFormat("YAML 块标量缩进无效")
            data[key] = "".join(nested).strip()
        elif nested and any(line.strip() and not line.lstrip().startswith("#") for line in nested):
            if token:
                raise UnsupportedFormat("标量后出现无法解释的 YAML 嵌套")
            items = []
            indentation = None
            for item in nested:
                if not item.strip() or item.lstrip().startswith("#"):
                    continue
                item_match = re.fullmatch(r" +-[ ]+([^\r\n]*)(?:\r?\n)?", item)
                if item_match is None:
                    raise UnsupportedFormat("复杂 YAML 嵌套映射不支持局部编辑")
                width = len(item) - len(item.lstrip(" "))
                if indentation is not None and width != indentation:
                    raise UnsupportedFormat("YAML 列表缩进不一致")
                indentation = width
                item_token = item_match[1]
                item_comment = _comment(item_token)
                items.append(_yaml_scalar(item_token[:item_comment].rstrip() if item_comment is not None else item_token))
            data[key] = items
        else:
            data[key] = _yaml_scalar(token)
        if key in {"model", "effort"}:
            start = offsets[index]
            value_start = start + match.start(3)
            spans[key] = Span(start, start + len(line), value_start, value_start + len(token),
                              value_start + comment if comment is not None else None, "")
        index = following
    name, description = _metadata(data)
    fields = validate_fields(host, {field: data[field] for field in ("model", "effort") if field in data})
    return AgentDocument(name, description, fields, text, spans, offsets[closing], "\r\n" if "\r\n" in text else "\n")


def parse(host: str, body: bytes) -> AgentDocument:
    text = _text(body)
    return _toml(text) if host == "codex" else _yaml(host, text)


def patch(host: str, body: bytes, edits: dict) -> bytes:
    """按原解析跨度从后往前替换；非目标字段、注释、正文和换行保持原字节。"""
    document = parse(host, body)
    edits = validate_fields(host, edits, edits=True)
    replacements, inserted = [], []
    for field, value in edits.items():
        span = document.spans.get(field)
        if span is not None:
            if value is None:
                comment = (span.indent + document.text[span.comment_start:span.end]) if span.comment_start is not None else ""
                replacements.append((span.start, span.end, comment))
            else:
                replacements.append((span.value_start, span.value_end, json.dumps(value, ensure_ascii=False)))
        elif value is not None:
            key = "model_reasoning_effort" if host == "codex" and field == "effort" else field
            inserted.append(key + (" = " if host == "codex" else ": ") + json.dumps(value, ensure_ascii=False) + document.newline)
    if inserted:
        prefix = document.newline if document.insertion and document.text[document.insertion - 1] != "\n" else ""
        replacements.append((document.insertion, document.insertion, prefix + "".join(inserted)))
    result = document.text
    for start, end, value in sorted(replacements, key=lambda item: (item[0], item[1]), reverse=True):
        result = result[:start] + value + result[end:]
    raw = result.encode("utf-8")
    checked = parse(host, raw)
    expected = dict(document.fields)
    for field, value in edits.items():
        if value is None:
            expected.pop(field, None)
        else:
            expected[field] = value
    if checked.fields != expected or checked.name != document.name:
        raise UnsupportedFormat("局部编辑无法通过原生字段复核")
    return raw
