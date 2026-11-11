"""原生事务的有界单日志编码；不执行文件操作，也不授予节点或路径权限。"""

from __future__ import annotations

import base64
import json
import sys

from lib.central.runtime_project import LIMIT, ProjectRuntimeError, json_bytes, unique_json


# 8MiB 只限制 RAM 中按 compact JSON 逐次计入引用的逻辑展开量；实际文件仍
# 必须经过 json_bytes 的默认 4MiB 检查，单个 Node 的原 4MiB 合同也不变。
LOGICAL_LIMIT = 2 * LIMIT
MAX_REFERENCES = 131072
MAX_TREE_NODES = 2 * LIMIT
MAX_DEPTH = max(1024, sys.getrecursionlimit())
_NODE_KEYS = frozenset({"kind", "body", "mode", "identity"})


def _fail() -> ProjectRuntimeError:
    return ProjectRuntimeError("原生事务日志编码、引用或逻辑容量无效")


def _logical_budget(value: dict) -> None:
    """流式累计规范 compact UTF-8，绝不先组装可能被引用放大的展开正文。"""
    size = 0
    try:
        for chunk in json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":")).iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > LOGICAL_LIMIT:
                raise _fail()
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise _fail() from exc


def _transform(value: dict, convert) -> dict:
    """迭代复制容器，检测祖先循环；共享输入 dict/list 也各自复制成独立容器。

    只有正文表内不可变 str 可以共享。深度界不窄于既有 JSON 解析器；节点数
    按每个 JSON value 至少一个字节覆盖旧 4MiB 输入，不按一次成功的 33 步
    假定恢复次数。编码按键排序遍历，使插入顺序不同的相同逻辑内容字节一致。
    """
    result, ancestors, count = [None], set(), 0
    pending = [(value, result, 0, 0)]
    while pending:
        current, parent, key, depth = pending.pop()
        if parent is None:
            ancestors.remove(current)
            continue
        count += 1
        if count > MAX_TREE_NODES or depth > MAX_DEPTH:
            raise _fail()
        if isinstance(current, (dict, list)):
            identifier = id(current)
            if identifier in ancestors:
                raise _fail()
            ancestors.add(identifier)
            pending.append((identifier, None, None, 0))
            if isinstance(current, dict):
                if any(not isinstance(name, str) for name in current):
                    raise _fail()
                fields = convert(current)
                target = {}
                parent[key] = target
                for name in reversed(sorted(fields)):
                    pending.append((fields[name], target, name, depth + 1))
            else:
                target = [None] * len(current)
                parent[key] = target
                for index in range(len(current) - 1, -1, -1):
                    pending.append((current[index], target, index, depth + 1))
        elif current is None or isinstance(current, (str, int, float, bool)):
            parent[key] = current
        else:
            raise _fail()
    return result[0]


def _body(value: str) -> None:
    if not isinstance(value, str) or len(value) > LIMIT:
        raise _fail()
    try:
        if len(base64.b64decode(value, validate=True)) > LIMIT:
            raise _fail()
    except (TypeError, ValueError) as exc:
        raise _fail() from exc


def _node(fields: dict, body_key: str) -> bool:
    keys = _NODE_KEYS - {"body"} | {body_key}
    return fields.keys() == keys or fields.keys() == keys | {"security"}


def encode(journal: dict) -> bytes:
    """将完整 logical schema1 写成 wire2；每次重建表，不修改或重复封装 RAM。

    去重只比较完整 base64 字符串，不合并身份、mode、ACL 或路径。最小合法
    compact Node 为 48B，旧 4MiB 日志最多 87381 个内联 Node；131072 引用
    与表项硬界因此不会排除旧格式本来能保存的快照数量。
    """
    if (not isinstance(journal, dict) or type(journal.get("schema_version")) is not int
            or journal["schema_version"] != 1 or "bodies" in journal):
        raise _fail()
    bodies, indexes, references, unique_size = [], {}, 0, 0

    def intern(fields: dict) -> dict:
        nonlocal references, unique_size
        if "body_ref" in fields:
            raise _fail()
        if not _node(fields, "body"):
            return fields
        references += 1
        if references > MAX_REFERENCES:
            raise _fail()
        body = fields["body"]
        if not isinstance(body, str):
            raise _fail()
        if body not in indexes:
            _body(body)
            unique_size += len(body)
            if unique_size > LIMIT or len(bodies) >= MAX_REFERENCES:
                raise _fail()
            indexes[body] = len(bodies)
            bodies.append(body)
        return {**{name: item for name, item in fields.items() if name != "body"}, "body_ref": indexes[body]}

    wire = _transform(journal, intern)
    _logical_budget(journal)
    wire["schema_version"], wire["bodies"] = 2, bodies
    return json_bytes(wire)


def decode(payload: bytes) -> dict:
    """解码 wire1/2，但不认领文件；调用者继续原有完整授权与 Node 校验。

    wire1 只沿既有 4MiB/唯一字段 JSON 规则读取，不施加 wire2 新增计数界。
    wire2 表仅含字符串，不递归解析正文；引用赋回同一不可变 str，防止复制
    放大内存。重复、未使用和未知引用均拒绝，逻辑总量再按每次引用计账。
    """
    if not isinstance(payload, bytes) or len(payload) > LIMIT:
        raise _fail()
    wire = unique_json(payload)
    if not isinstance(wire, dict) or type(wire.get("schema_version")) is not int:
        raise _fail()
    if wire["schema_version"] == 1:
        return wire
    if wire["schema_version"] != 2 or not isinstance(wire.get("bodies"), list):
        raise _fail()
    bodies = wire["bodies"]
    if len(bodies) > MAX_REFERENCES:
        raise _fail()
    seen, unique_size = set(), 0
    for body in bodies:
        _body(body)
        unique_size += len(body)
        if body in seen or unique_size > LIMIT:
            raise _fail()
        seen.add(body)
    used, references = set(), 0

    def expand(fields: dict) -> dict:
        nonlocal references
        if "body_ref" not in fields:
            if _node(fields, "body"):
                raise _fail()
            return fields
        reference = fields["body_ref"]
        if (not _node(fields, "body_ref") or type(reference) is not int
                or not 0 <= reference < len(bodies)):
            raise _fail()
        references += 1
        if references > MAX_REFERENCES:
            raise _fail()
        used.add(reference)
        return {**{name: item for name, item in fields.items() if name != "body_ref"}, "body": bodies[reference]}

    logical = _transform({name: item for name, item in wire.items() if name != "bodies"}, expand)
    if len(used) != len(bodies):
        raise _fail()
    logical["schema_version"] = 1
    _logical_budget(logical)
    return logical
