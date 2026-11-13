"""插件启停配置的保字节编辑；与 Agent frontmatter/model codec 完全分离。"""

from __future__ import annotations

import copy
import json
import re
import tomllib

from .codecs import _statements
from .contracts import ConfigError, MAX_FILE_BYTES, UnsupportedFormat, unique_json


def parse(host, body):
    """只读取宿主原生配置，不为缺失键推断插件默认已启用。"""
    if body is None:
        return {}
    if not isinstance(body, bytes) or len(body) > MAX_FILE_BYTES:
        raise ConfigError("启停配置超过容量限制")
    try:
        text = body.decode("utf-8")
        if text.startswith("\ufeff") or "\x00" in text:
            raise ValueError("unsupported text")
        value = tomllib.loads(text) if host == "codex" else unique_json(body)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UnsupportedFormat("启停配置不是可安全编辑的原生格式") from exc
    if not isinstance(value, dict):
        raise UnsupportedFormat("启停配置根必须是对象")
    return value


def state(host, body, plugin_id):
    data = parse(host, body)
    mapping = data.get("plugins" if host == "codex" else "enabledPlugins", {})
    if not isinstance(mapping, dict):
        raise UnsupportedFormat("插件配置映射无效")
    if plugin_id not in mapping:
        return "inherit"
    value = mapping[plugin_id]
    if host == "codex":
        if not isinstance(value, dict):
            raise UnsupportedFormat("插件设置必须是表")
        if "enabled" not in value:
            return "inherit"
        value = value["enabled"]
    if type(value) is not bool:
        raise UnsupportedFormat("插件 enabled 必须是布尔值")
    return "enabled" if value else "disabled"


def _toml_path(raw):
    """借用 tomllib 解析带引号/点的键名，不自行猜测点是否在引号内。"""
    node = tomllib.loads(raw + " = 0")
    parts = []
    while isinstance(node, dict) and len(node) == 1:
        key, node = next(iter(node.items()))
        parts.append(key)
    if node != 0:
        raise UnsupportedFormat("无法定位 TOML 键")
    return tuple(parts)


def _toml_patch(text, plugin_id, value):
    target = ("plugins", plugin_id, "enabled")
    section, located, insertion = (), None, None
    newline = "\r\n" if "\r\n" in text else "\n"
    for start, end in _statements(text):
        statement = text[start:end]
        stripped = statement.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            if stripped.startswith("[["):
                section = None
                continue
            match = re.fullmatch(r"\[([^\n]+)\][ \t]*(?:#[^\n]*)?", stripped)
            if match is None:
                section = None  # 数组表绝不被误认作目标插件表。
            else:
                section = _toml_path(match[1].strip())
                if section == target[:-1]:
                    insertion = end
            continue
        # 用短键扫描定位 '='；完整 TOML 的合法性已由 parse 验证。
        match = re.match(r'''([ \t]*)(\s*(?:"(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+)(?:\s*\.\s*(?:"(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+))*)[ \t]*=[ \t]*(true|false)(?=[ \t\r\n#]|$)''', statement)
        if section is not None and match is not None and section + _toml_path(match[2].strip()) == target:
            comment = statement.find("#", match.end(3))
            located = (start, end, start + match.start(3), start + match.end(3),
                       match[1] + statement[comment:] if comment >= 0 else "")
    if located is not None:
        start, end, left, right, comment = located
        return text[:start] + comment + text[end:] if value is None else text[:left] + json.dumps(value) + text[right:]
    if value is None:
        return text
    # 现存目标值若采用内联表等布局，追加表会重复定义；明确拒绝而非重排全文。
    if insertion is not None:
        prefix = newline if insertion and text[insertion - 1] != "\n" else ""
        return text[:insertion] + prefix + "enabled = " + json.dumps(value) + newline + text[insertion:]
    prefix = newline if text and not text.endswith("\n") else ""
    return text + prefix + '[plugins.' + json.dumps(plugin_id) + ']'+ newline + "enabled = " + json.dumps(value) + newline


def _objects(text):
    """索引 JSON 对象成员跨度，字符串内的花括号/逗号不会成为编辑边界。"""
    decoder, objects = json.JSONDecoder(), {}

    def whitespace(index):
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        return index

    def walk(index, path):
        index = whitespace(index)
        if text[index] != "{":
            return decoder.raw_decode(text, index)[1]
        opening, members = index, []
        index = whitespace(index + 1)
        while text[index] != "}":
            begin = index
            key, index = decoder.raw_decode(text, index)
            index = whitespace(index)
            if text[index] != ":":
                raise UnsupportedFormat("JSON 对象边界无效")
            left = whitespace(index + 1)
            right = walk(left, path + (key,))
            index = whitespace(right)
            comma = index if text[index] == "," else None
            members.append((key, begin, left, right, comma))
            if comma is None:
                break
            index = whitespace(index + 1)
        closing = index
        objects[path] = (opening, closing, members)
        return closing + 1

    walk(0, ())
    return objects


def _json_patch(text, plugin_id, value):
    objects = _objects(text)
    path = ("enabledPlugins",)
    if path not in objects:
        path, key, new = (), "enabledPlugins", {plugin_id: value}
        if value is None:
            return text
    else:
        key, new = plugin_id, value
    opening, closing, members = objects[path]
    for index, (member, begin, left, right, comma) in enumerate(members):
        if member != key:
            continue
        if value is not None:
            return text[:left] + json.dumps(new, ensure_ascii=False) + text[right:]
        # 只删除目标成员及一个必要分隔符，其他成员和值的字节保持原样。
        start = members[index - 1][4] if comma is None and index else begin
        end = comma + 1 if comma is not None else right
        return text[:start] + text[end:]
    if value is None:
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    insertion = json.dumps(key, ensure_ascii=False) + ": " + json.dumps(new, ensure_ascii=False)
    if members:
        right = members[-1][3]
        return text[:right] + "," + newline + "  " + insertion + text[right:]
    return text[:opening + 1] + newline + "  " + insertion + text[opening + 1:]


def patch(host, body, plugin_id, new_state):
    if not isinstance(new_state, str) or new_state not in {"inherit", "enabled", "disabled"}:
        raise ConfigError("启停状态无效")
    before = parse(host, body)
    state(host, body, plugin_id)
    value = None if new_state == "inherit" else new_state == "enabled"
    expected = copy.deepcopy(before)
    name = "plugins" if host == "codex" else "enabledPlugins"
    mapping = expected.setdefault(name, {})
    if host == "codex":
        entry = mapping.setdefault(plugin_id, {})
        entry.pop("enabled", None) if value is None else entry.update(enabled=value)
    else:
        mapping.pop(plugin_id, None) if value is None else mapping.update({plugin_id: value})
    text = (body or (b"" if host == "codex" else b"{}\n")).decode("utf-8")
    result = (_toml_patch(text, plugin_id, value) if host == "codex" else _json_patch(text, plugin_id, value)).encode("utf-8")
    actual = parse(host, result)
    # 删除键可能留下空表，也可能原先根本没有表；比较规范化目标之外的数据，
    # 使语法扫描的任何定位错误都在落盘前被完整宿主解析器拦截。
    def normalized(data):
        data = copy.deepcopy(data)
        container = data.get(name, {})
        if host == "codex" and container.get(plugin_id) == {}:
            container.pop(plugin_id)
        if container == {}:
            data.pop(name, None)
        return data
    if normalized(actual) != normalized(expected) or state(host, result, plugin_id) != new_state:
        raise UnsupportedFormat("无法精确保留启停配置的其他设置")
    return result
