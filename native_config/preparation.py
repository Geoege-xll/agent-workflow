"""显式插件来源的只读候选与原生文件创建计划，不执行插件内任何代码。"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tomllib

from . import codecs, storage
from .contracts import ConfigError, ConflictError, MAX_BATCH, absolute_path, unique_json

INDEX = "native-agent-templates/codex/index.json"
PLACEHOLDER = "__XY_WORKFLOW_PLUGIN_ROOT__"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _hash(body):
    return hashlib.sha256(body).hexdigest()


def _relative(root, value):
    """来源清单仅授权根内规范相对文件；实际读取仍由 storage no-follow 校验。"""
    if (not isinstance(value, str) or not value or len(value) > 4096 or "\\" in value
            or PurePosixPath(value).is_absolute() or PurePosixPath(value).as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ConfigError("准备来源包含不安全资源路径")
    return root / value


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    description: str
    body: bytes


@dataclass(frozen=True)
class Source:
    root: Path
    id: str
    revision: str
    candidates: tuple[Candidate, ...]


def load(root: Path) -> Source:
    """静态、有界地核对双摘要；摘要只证明字节一致，信任来自显式启动来源。

    不扫描宿主缓存，不导入源包 verifier。清单全部校验路径/摘要形状，实际
    字节核对只覆盖本业务消费的候选与其规范源闭包，不加载无关 CLI 运行时。
    读取复用已有单链接、有界、目录链 no-follow 快照，并进入来源 CAS。
    """
    root = absolute_path(root)
    identity = storage.project_identity(root)
    nodes, total = {}, 0

    def read(relative):
        nonlocal total
        if relative not in nodes:
            node = storage.read(_relative(root, relative))
            if node.body is None:
                raise ConfigError("准备来源资源不完整")
            total += len(node.body)
            if len(nodes) >= 8192 or total > 128 * 1048576:
                raise ConfigError("准备来源超过读取容量")
            nodes[relative] = node
        return nodes[relative].body

    metadata = unique_json(read("sources.json"))
    canonical = unique_json(read("workflow-sources.json"))
    if (not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int or metadata.get("schema_version") != 1
            or metadata.get("plugin_name") != "xy-workflow" or metadata.get("product") != "workflow-core"
            or metadata.get("host") != "codex" or not isinstance(metadata.get("plugin_version"), str)
            or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", metadata["plugin_version"])
            or not isinstance(canonical, dict) or set(canonical) != {"schema_version", "files"}
            or type(canonical["schema_version"]) is not int or canonical["schema_version"] != 1):
        raise ConfigError("准备来源身份无效")
    payload = metadata.get("payload_sha256")
    sources = canonical["files"]
    if (not isinstance(payload, dict) or not isinstance(sources, dict) or not sources
            or not {INDEX, "workflow-sources.json", ".codex-plugin/plugin.json"} <= set(payload)
            or "sources.json" in payload or len(payload) + len(sources) > 8192):
        raise ConfigError("准备来源摘要清单无效")
    for mapping in (payload, sources):
        for relative, expected in mapping.items():
            _relative(root, relative)
            if not isinstance(expected, str) or not _DIGEST.fullmatch(expected):
                raise ConfigError("准备来源摘要清单无效")
    # 规范源必须同时被发行摘要覆盖，禁止两份清单各自声明互不相关的正文。
    if any(payload.get(relative) != expected for relative, expected in sources.items()):
        raise ConfigError("准备来源双摘要不一致")
    if _hash(read("workflow-sources.json")) != payload["workflow-sources.json"]:
        raise ConfigError("准备来源规范清单摘要不一致")
    manifest = unique_json(read(".codex-plugin/plugin.json"))
    if (not isinstance(manifest, dict) or manifest.get("name") != "xy-workflow"
            or manifest.get("version") != metadata["plugin_version"]):
        raise ConfigError("准备来源插件身份不一致")
    index = unique_json(read(INDEX))
    if (not isinstance(index, dict) or set(index) != {"schema_version", "product", "host", "version", "templates"}
            or type(index["schema_version"]) is not int or index["schema_version"] != 1 or index["product"] != "xy-workflow" or index["host"] != "codex"
            or index["version"] != metadata["plugin_version"] or not isinstance(index["templates"], list)
            or not 1 <= len(index["templates"]) <= MAX_BATCH):
        raise ConfigError("准备候选索引无效")
    candidates, names, paths = [], set(), set()
    source_id = "source_" + _hash(str(root).encode())
    projections = metadata.get("projections")
    source_files = metadata.get("source_files")
    if not isinstance(projections, dict) or not isinstance(source_files, dict):
        raise ConfigError("准备来源缺少规范投影关系")
    dependencies = ("product/ROLES.yaml", "platforms/codex/WORKER_CONSTRAINTS.md", "plugins/codex/native-agent-context.md")
    for entry in index["templates"]:
        if (not isinstance(entry, dict) or set(entry) != {"name", "description", "path", "sha256"}
                or not isinstance(entry["name"], str) or not re.fullmatch(r"xy-[a-z][a-z0-9-]{0,63}", entry["name"])
                or not isinstance(entry["description"], str) or not 1 <= len(entry["description"]) <= 2048
                or entry["name"] in names or not isinstance(entry["path"], str) or entry["path"] in paths
                or not entry["path"].startswith("native-agent-templates/codex/")
                or not entry["path"].endswith(".toml") or payload.get(entry["path"]) != entry["sha256"]):
            raise ConfigError("准备候选条目无效")
        body = read(entry["path"])
        projection = projections.get(entry["path"])
        role_source = "roles/" + entry["name"] + ".md"
        if (not isinstance(projection, dict) or projection.get("source") != role_source
                or projection.get("transform") != "codex-native-template-v1"
                or projection.get("adapter") != dependencies[2]
                or projection.get("source_sha256") != sources.get(role_source)
                or projection.get("projection_sha256") != entry["sha256"]
                or projection.get("dependencies") != {name: sources.get(name) for name in dependencies}):
            raise ConfigError("准备候选规范投影关系无效")
        for relative in (role_source, *dependencies):
            expected = sources.get(relative)
            if expected is None or source_files.get(relative) != expected or _hash(read(relative)) != expected:
                raise ConfigError("准备候选规范源双摘要不匹配")
        try:
            document = tomllib.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ConfigError("准备候选 TOML 无效") from exc
        if (set(document) != {"name", "description", "developer_instructions"}
                or document["name"] != entry["name"] or document["description"] != entry["description"]
                or not isinstance(document["developer_instructions"], str)
                or PLACEHOLDER not in document["developer_instructions"]
                or not document["developer_instructions"].strip()):
            raise ConfigError("准备模板只能声明原生身份与正文，不允许模型或权限默认")
        # 先解析再序列化，物理插件根即使含引号/反斜杠也只能成为字符串正文，
        # 不能通过原文替换注入 TOML 字段。仅此一个固定占位符具有替换语义。
        document["developer_instructions"] = document["developer_instructions"].replace(PLACEHOLDER, str(root))
        rendered = ("# 由显式选择的 xy-workflow 插件候选创建；后续修改由用户维护。\n"
                    + "\n".join(key + " = " + json.dumps(value, ensure_ascii=False) for key, value in document.items()) + "\n").encode()
        codecs.parse("codex", rendered)
        names.add(entry["name"])
        paths.add(entry["path"])
        candidates.append(Candidate("candidate_" + _hash((source_id + "\0" + entry["name"]).encode()),
                                    entry["name"], entry["description"], rendered))
    index_projection = projections.get(INDEX)
    if (not isinstance(index_projection, dict) or index_projection.get("source") != "product/ROLES.yaml"
            or index_projection.get("transform") != "codex-native-template-index-v1"
            or index_projection.get("source_sha256") != sources.get("product/ROLES.yaml")
            or index_projection.get("projection_sha256") != payload[INDEX]
            or index_projection.get("dependencies") != {entry["path"]: entry["sha256"] for entry in index["templates"]}):
        raise ConfigError("准备索引规范投影关系无效")
    # 所有实际消费的文件都须被发行摘要覆盖。无关运行时仅验证清单形状，
    # 此能力不宣称验证整个插件运行时或发行发布者身份。
    if any(payload.get(relative) != _hash(node.body) for relative, node in nodes.items() if relative != "sources.json"):
        raise ConfigError("准备来源消费闭包摘要不匹配")
    # 逐项重读关闭“先验证旧文件、随后读取新索引”的窗口；下次 guard 同样重做。
    for relative, node in nodes.items():
        if storage.read(root / relative) != node:
            raise ConflictError("准备来源在读取期间变化")
    revision = _hash(repr((identity, [(relative, node.revision()) for relative, node in sorted(nodes.items())])).encode())
    return Source(root, source_id, revision, tuple(candidates))


def capture(root):
    """无来源与危险/残缺来源均不授予准备能力；错误由调用方统一诊断。"""
    if root is None:
        return None
    try:
        return load(root)
    except (ValueError, OSError, TypeError, RecursionError):
        return None


def unavailable_diagnostic(root):
    """区分正常的其他宿主入口与损坏来源；仅检查显式根，绝不寻找替代缓存。"""
    try:
        node = storage.read(absolute_path(root) / "sources.json")
        metadata = unique_json(node.body) if node.body is not None else None
        if (isinstance(metadata, dict) and metadata.get("schema_version") == 1
                and metadata.get("plugin_name") == "xy-workflow" and metadata.get("product") == "workflow-core"
                and metadata.get("host") in {"claude", "antigravity"}):
            return {"code": "native_preparation_source_host_unsupported",
                    "message": "当前插件入口未提供 Codex 原生候选；需要准备时请从 Codex 插件入口重新打开。已有原生定义仍可编辑。",
                    "runtime_verified": False}
    except (ValueError, OSError, TypeError, RecursionError):
        pass
    return {"code": "native_preparation_source_unavailable",
            "message": "显式插件准备来源缺失、损坏或无法安全验证；请从完整 Codex 插件重新打开。已有原生定义仍可编辑。",
            "runtime_verified": False}


def public(source, state, host_root):
    result = {"supported": source is not None, "source_id": source.id if source else None,
              "source_revision": source.revision if source else None, "candidates": []}
    if source is None:
        return result
    parent = (state.project / ".codex" if state.scope == "project" else host_root) / "agents"
    for item in source.candidates:
        path = parent / (item.name + ".toml")
        status = "missing"
        try:
            storage.directory_stamp(parent)
            node = storage.read(path)
            same = [agent for agent in state.inventory.agents if agent.document.name == item.name]
            if node.body is not None or same:
                status = "existing" if len(same) == 1 and same[0].path == path else "conflict"
            if not state.inventory.complete or any(row.get("code") in {"invalid_agent", "unsupported_format", "agent_missing"}
                                                    for row in state.inventory.diagnostics):
                status = "blocked"
        except (ValueError, OSError):
            status = "blocked"
        result["candidates"].append({"candidate_id": item.id, "name": item.name, "description": item.description,
                                     "status": status, "target_path": str(path)})
    return result


def preview(source, state, host_root, request):
    """客户端只能选择服务端候选 ID；路径、正文和替换项完全由已校验来源决定。"""
    if (source is None or not isinstance(request, dict)
            or set(request) != {"source_id", "source_revision", "candidate_ids"}):
        raise ConfigError("当前来源不支持原生 Agent 准备")
    if request["source_id"] != source.id or request["source_revision"] != source.revision:
        raise ConflictError("准备来源已变化，请重新读取并预览")
    selected = request["candidate_ids"]
    if (not isinstance(selected, list) or not 1 <= len(selected) <= MAX_BATCH
            or any(not isinstance(value, str) for value in selected) or len(set(selected)) != len(selected)):
        raise ConfigError("准备候选选择无效")
    candidates = {item.id: item for item in source.candidates}
    rows = {row["candidate_id"]: row for row in public(source, state, host_root)["candidates"]}
    writes, changes = [], []
    for opaque in selected:
        if opaque not in candidates or rows[opaque]["status"] != "missing":
            raise ConfigError("只能准备当前缺失且无冲突的候选；现有定义保持原样")
        item, row = candidates[opaque], rows[opaque]
        path = Path(row["target_path"])
        writes.append(storage.Write(opaque, path, storage.Snapshot(), item.body, storage.directory_stamp(path.parent)))
        changes.append({"role": opaque, "name": item.name, "origin": "project" if state.scope == "project" else "user",
                        "field": "native_definition", "before": None, "after": item.body.decode(), "path": str(path),
                        "source_id": source.id, "source_revision": source.revision})
    return writes, changes, ["仅创建缺失原生定义，保留全部现有文件；未设置模型或推理默认。",
                             "文件保存后请启动新会话核实宿主加载；保存不证明实际执行。"]


def inventory_revision(found, created):
    """仅归一化 storage 已排他创建且仍为空的目录，其余清单前像完整保留。

    此函数只在首个文件发布前由 guard 调用。发现任何并发文件、其他来源或
    不同 inode 时均保持新 revision，让现有 CAS 拒绝；不能整体跳过 inventory。
    """
    adjusted = copy.copy(found)
    adjusted.directories = []
    for entry in found.directories:
        expected = created.get(Path(entry[0]))
        if expected is not None and len(entry) == 4 and tuple(entry[1:3]) == expected and not entry[3]:
            adjusted.directories.append((entry[0], None))
        else:
            adjusted.directories.append(entry)
    return adjusted.revision()
