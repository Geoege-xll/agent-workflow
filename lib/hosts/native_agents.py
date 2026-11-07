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
            if not text.startswith("---\n") or not separator:
                return None
            if len(rows) > 1:
                raise ValueError("原生角色含重复name声明，不能证明无同名冲突")
            if not rows:
                return None
            raw = rows[0].strip()
            if raw.startswith('"'):
                value, end = json.JSONDecoder().raw_decode(raw)
                tail = raw[end:].strip()
                if tail and not tail.startswith("#"):
                    raise ValueError("原生角色name声明尾部无法确认")
            elif raw.startswith("'"):
                match = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", raw)
                if match is None:
                    raise ValueError("原生角色name声明无法确认")
                value = match[1].replace("''", "'")
            else:
                # YAML普通标量的空白+#是注释；不把合法注释误当作name的一部分。
                value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
                if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
                    raise ValueError("原生角色name声明不是可确认的单行标量")
        return value if isinstance(value, str) and value in role_models.ROLES else None
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("原生角色声明无法安全解析") from exc


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


def native_settings(raw: bytes, host: str) -> dict[str, str]:
    """统一读取完整原生描述符的模型投影，缺省字段仍表示宿主inherit。"""
    if host == "codex":
        data = tomllib.loads(raw.decode())
        return role_models.validate(host, {"model": data.get("model", "inherit"), "effort": data.get("model_reasoning_effort", "inherit")})
    front = raw.decode().split("\n---\n", 1)[0]
    model = re.findall(r"^model: (.+)$", front, re.MULTILINE)
    effort = re.findall(r"^effort: (.+)$", front, re.MULTILINE)
    if len(model) != 1 or len(effort) > 1:
        raise ValueError("角色模型字段缺失或重复")
    return role_models.validate(host, {"model": model[0].strip("\"'"), "effort": effort[0] if effort else "inherit"})


def validate_descriptor(body: bytes, host: str, role: str) -> None:
    """校验中央描述符完整权限及 pin-first 引导；不宣称宿主已加载或执行模型。"""
    if declared_name(body, host) != role or MARKER.encode() not in body:
        raise ValueError("原生中央角色声明或受管摘要无效")
    text = body.decode("utf-8")
    if host == "codex":
        header, payload = text.split("\n", 1)
        expected = "# " + MARKER + ":v1 sha256=" + hashlib.sha256(payload.encode()).hexdigest()
        data = tomllib.loads(payload)
        allowed = {"name", "description", "model", "model_reasoning_effort", "developer_instructions"}
        if header != expected or set(data) - allowed or not {"name", "description", "developer_instructions"} <= set(data):
            raise ValueError("Codex 中央角色摘要无效或含不能覆盖父会话的伪权限字段")
        if (not isinstance(data.get("description"), str) or not data["description"].strip()
                or not isinstance(data.get("developer_instructions"), str)):
            raise ValueError("Codex中央角色缺少完整描述或引导正文")
        if role == "xy-qa" and "read-only review role" not in data.get("developer_instructions", ""):
            raise ValueError("QA 角色必须声明只读职责及父会话权限边界")
        role_models.validate(host, {"model": data.get("model", "inherit"),
                                    "effort": data.get("model_reasoning_effort", "inherit")})
    else:
        front = text.split("\n---\n", 1)[0]
        names = re.findall(r"(?m)^([A-Za-z][A-Za-z0-9]*):", front)
        required = {"name", "description", "model", "tools"}
        allowed = required | ({"permissionMode", "disallowedTools", "effort", "autoCompactWindow"} if host == "claude"
                              else {"mainAgent", "subagent", "commandExecutionPolicy"})
        if len(names) != len(set(names)) or set(names) - allowed or not required <= set(names):
            raise ValueError("中央角色frontmatter字段缺失、重复或未受支持")
        model = re.findall(r"(?m)^model: (.+)$", front)
        effort = re.findall(r"(?m)^effort: (.+)$", front)
        if len(model) != 1 or len(effort) > 1:
            raise ValueError("中央角色model/effort字段必须是完整单行值")
        descriptions = re.findall(r"(?m)^description: (.+)$", front)
        try:
            description = json.loads(descriptions[0]) if len(descriptions) == 1 else None
        except ValueError as exc:
            raise ValueError("中央角色description必须是完整JSON/YAML安全字符串") from exc
        if not isinstance(description, str) or not description.strip():
            raise ValueError("中央角色缺少完整description")
        role_models.validate(host, {"model": model[0].strip('"'), "effort": effort[0] if effort else "inherit"})
        if host == "claude":
            tools = "Read, Grep, Glob, Bash, Skill" if role == "xy-qa" else "Read, Grep, Glob, Bash, Edit, Write, Skill"
            if (re.findall(r"(?m)^disallowedTools: (.+)$", front) != ["Agent"]
                    or re.findall(r"(?m)^permissionMode: (.+)$", front) != ["default"]
                    or re.findall(r"(?m)^tools: (.+)$", front) != [tools]):
                raise ValueError("Claude中央角色工具白名单、委派或权限边界无效")
            if "autoCompactWindow" in names:
                from lib.hosts.claude_options import validate_window
                window = re.findall(r"(?m)^autoCompactWindow: ([0-9]+)$", front)
                if len(window) != 1:
                    raise ValueError("Claude中央角色窗口必须是完整token整数")
                validate_window(int(window[0]))
        else:
            from lib.validate_antigravity_artifacts import ROLE_TOOLS
            tools = re.findall(r"(?m)^  - ([A-Za-z0-9_]+)$", front)
            if (re.findall(r"(?m)^mainAgent: (.+)$", front) != ["false"]
                    or re.findall(r"(?m)^subagent: (.+)$", front) != ["true"]
                    or re.findall(r"(?m)^commandExecutionPolicy: (.+)$", front) != ["sandbox"]
                    or tuple(tools) != ROLE_TOOLS[role]):
                raise ValueError("Antigravity中央角色工具白名单或子角色边界无效")
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
