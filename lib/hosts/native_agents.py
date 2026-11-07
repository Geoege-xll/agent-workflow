"""原生角色的有界发现、完整描述符编译与归属验证原语；本模块不写文件。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
import tomllib

from lib import role_models
from lib.central.runtime_project import (MARKER, Node, Resources, Tree, absolute_directory,
                                         json_bytes, role_resource, unique_json)
from lib.hosts.native_context import HostPaths, NativeContext
from lib.platform_fs import os

OWNER = ".agent-workflow-native-roles.json"
DISCOVERY_LIMIT = 512


def role_relative(host: str, role: str) -> str:
    if host not in role_models.HOSTS or role not in role_models.ROLES:
        raise ValueError("未知宿主或角色")
    return "agents/" + role + (".toml" if host == "codex" else ".md")


def record_relative(root: Path) -> str:
    return "native-agents/roots/" + hashlib.sha256(str(root).encode()).hexdigest() + ".json"


def read_node(root: Path, relative: str) -> Node:
    try:
        with Tree(root) as tree:
            return tree.read(relative)
    except FileNotFoundError:
        return Node()


def root_identity(root: Path) -> tuple[int, int] | None:
    try:
        with absolute_directory(root) as descriptor:
            info = os.fstat(descriptor)
            return info.st_dev, info.st_ino
    except FileNotFoundError:
        return None


def declared_name(body: bytes, host: str) -> str | None:
    """只读取同名检测所需的声明，不解析/执行宿主文件的其余指令。"""
    try:
        if host == "codex":
            value = tomllib.loads(body.decode("utf-8")).get("name")
        else:
            text = body.decode("utf-8")
            front, separator, _ = text.partition("\n---\n")
            rows = re.findall(r"(?m)^name:[ \t]*(.+)$", front)
            if not text.startswith("---\n") or not separator or len(rows) != 1:
                return None
            raw = rows[0].strip()
            value = json.loads(raw) if raw.startswith('"') else raw.strip("'")
        return value if isinstance(value, str) and value in role_models.ROLES else None
    except (ValueError, UnicodeError, RecursionError):
        return None


def discover(root: Path, host: str) -> tuple[tuple[str, Node, str | None], ...]:
    """仅在声明的 agents 根有界遍历，别名文件也不能隐藏已知角色的 name 冲突。

    祖先和叶节点均不跟随链接；目录深度/条目数超限直接拒绝，不能将未读部分
    误报为无冲突。文件正文只保存在私有计划，不进入公开 summary 或诊断。
    """
    suffix = ".toml" if host == "codex" else ".md"
    rows = []
    count = 0
    try:
        with Tree(root) as tree:
            try:
                first = tree.directory("agents")
            except FileNotFoundError:
                return ()
            pending = [("agents", first, 0)]
            while pending:
                relative, descriptor, depth = pending.pop()
                for name in sorted(os.listdir(descriptor)):
                    count += 1
                    if count > DISCOVERY_LIMIT:
                        raise ValueError("宿主角色发现超过有界条目限制")
                    path = relative + "/" + name
                    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        if depth >= 4:
                            raise ValueError("宿主角色发现超过有界目录深度")
                        pending.append((path, tree.directory(path), depth + 1))
                    elif stat.S_ISREG(info.st_mode) and name.endswith(suffix):
                        node = tree.read(path)
                        rows.append((path, node, declared_name(node.payload, host)))
                    elif stat.S_ISLNK(info.st_mode):
                        raise ValueError("宿主角色发现不接受符号链接")
    except FileNotFoundError:
        return ()
    return tuple(sorted(rows, key=lambda row: row[0]))


def compile_role(resources: Resources, host: str, role: str, preferences: dict) -> bytes:
    # role_resource 统一权限与正文政策；全局入口只取最小稳定引导，不复制完整角色，
    # 也不将本次安装 binding 写进全局正文。该参数仅满足原编译器封闭类型合同。
    return role_resource(resources, b"project_name: global\n", host, role, resources.binding,
                         preferences=preferences, global_role=True)


def validate_descriptor(body: bytes, host: str, role: str) -> None:
    """校验中央描述符完整权限及 pin-first 引导；不宣称宿主已加载或执行模型。"""
    if declared_name(body, host) != role or MARKER.encode() not in body:
        raise ValueError("原生中央角色声明或受管摘要无效")
    text = body.decode("utf-8")
    if host == "codex":
        header, payload = text.split("\n", 1)
        expected = "# " + MARKER + ":v1 sha256=" + hashlib.sha256(payload.encode()).hexdigest()
        data = tomllib.loads(payload)
        if header != expected or any(key in data for key in ("sandbox_mode", "approval_policy", "model_provider", "mcp_servers")):
            raise ValueError("Codex 中央角色摘要无效或含不能覆盖父会话的伪权限字段")
        if role == "xy-qa" and "read-only review role" not in data.get("developer_instructions", ""):
            raise ValueError("QA 角色必须声明只读职责及父会话权限边界")
        role_models.validate(host, {"model": data.get("model", "inherit"),
                                    "effort": data.get("model_reasoning_effort", "inherit")})
    else:
        front = text.split("\n---\n", 1)[0]
        if re.search(r"(?m)^skills:", front):
            raise ValueError("中央角色不得预载可变内置 Skill")
        if host == "claude":
            if "disallowedTools: Agent" not in front or "permissionMode: default" not in front:
                raise ValueError("Claude 中央角色必须禁止嵌套委派并保持默认权限")
            if role == "xy-qa" and re.search(r"(?m)^tools:.*\b(?:Edit|Write)\b", front):
                raise ValueError("QA 角色必须保持只读")
        elif "mainAgent: false" not in front or "subagent: true" not in front:
            raise ValueError("Antigravity 中央角色缺少子角色边界")
    if (text.find("complete current schema_version: 2 Task Pack") < 0 or
            text.find("Before any project check") < 0 or "context_policy: handoff_only" not in text):
        raise ValueError("中央角色缺少完整 Task Pack 与 pin-first 引导")


def parse_record(node: Node, *, state: Path, root: Path, host: str,
                 identity: tuple[int, int] | None) -> dict | None:
    if node.kind == "missing":
        return None
    value = unique_json(node.payload)
    keys = {"schema_version", "host", "native_root", "root_identity", "state", "files"}
    if (not isinstance(value, dict) or set(value) != keys or type(value["schema_version"]) is not int
            or value["schema_version"] != 1 or value["host"] != host or value["native_root"] != str(root)
            or value["state"] != str(state) or value["root_identity"] != list(identity or ())
            or not isinstance(value["files"], dict)
            or set(value["files"]) != {role_relative(host, role) for role in role_models.ROLES}):
        raise ValueError("全局原生归属记录不属于当前状态及宿主物理根")
    for path, entry in value["files"].items():
        if not isinstance(entry, dict) or set(entry) != {"baseline", "expected"}:
            raise ValueError("全局原生归属条目无效")
        before, after = Node.from_value(entry["baseline"]), Node.from_value(entry["expected"])
        if before.kind not in {"missing", "file"} or after.kind != "file" or len(after.identity) != 7:
            raise ValueError("全局原生归属只接受精确普通文件")
        role = Path(path).stem
        validate_descriptor(after.payload, host, role)
    return value
