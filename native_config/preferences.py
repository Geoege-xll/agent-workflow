"""调用偏好的可编辑投影；持久化仍复用核心的条件保存事务。"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import os

from . import preference_contract as contract, storage
from .contracts import ConfigError, MAX_BATCH, json_bytes


@dataclass(frozen=True)
class Preferences:
    host: str
    project: str | None
    path: object
    snapshot: storage.Snapshot
    parent_stamp: tuple
    document: dict

    def revision(self, *, include_parent=True):
        return hashlib.sha256(json_bytes([str(self.path), self.snapshot.revision(),
                                         self.parent_stamp if include_parent else None])).hexdigest()


def capture(host, root, project):
    path = root / "native-agent-config/dispatch-preferences.json"
    snapshot = storage.read(path)
    return Preferences(host, str(project) if project else None, path, snapshot,
                       storage.directory_stamp(path.parent), contract.parse_document(snapshot.body, host))


def capabilities(host):
    """偏好写入能力与原生文件格式不同：仅接受能供调用方解释的模型形状。"""
    return {"model": True, "effort": host != "antigravity",
            "model_format": "alias" if host == "claude" else "tier" if host == "antigravity" else "model_id",
            "model_aliases": ["sonnet", "opus", "haiku", "fable", "inherit"] if host == "claude" else [],
            "model_tiers": ["inherit", "flash", "pro"] if host == "antigravity" else [],
            "efforts": [] if host == "antigravity" else ["low", "medium", "high", "xhigh", "max"] if host == "claude" else
                       ["low", "medium", "high", "xhigh", "max", "ultra"],
            "effort_capability_status": "unsupported" if host == "antigravity" else "model_dependent_unverified",
            "dispatch_schema_status": "unverified" if host == "antigravity" else "host_tool_must_confirm",
            "reason": "调用方必须逐项核对当前原生工具参数；未支持的已配置参数阻断派发，不可静默丢弃。",
            "runtime_verified": False}


def _layer(state, scope, document=None):
    document = state.document if document is None else document
    if scope == "global":
        return document
    return document["projects"].get(state.project, {"defaults": {}, "agents": {}})


def _writable(state):
    if state.snapshot.identity and not state.snapshot.identity[2] & 0o200:
        return False, "偏好文件没有属主写权限。"
    existing = [entry for entry in state.parent_stamp if entry[1] is not None]
    if existing and (existing[-1][4] != os.getuid() or existing[-1][3] & 0o300 != 0o300):
        return False, "偏好父目录属主或写入权限不允许安全保存。"
    return True, None


def public(state, scope, agents):
    layer = _layer(state, scope)
    discovered = {}
    for agent in agents:
        discovered.setdefault(agent.invoke_name, agent)
    names = set(discovered) | set(state.document["agents"]) | set(layer["agents"])
    targets = []
    writable, reason = _writable(state)
    for target in ["*", *sorted(names)]:
        agent = discovered.get(target)
        resolved = contract.project_preferences(state.document, target, state.project)
        overrides = layer["defaults"] if target == "*" else layer["agents"].get(target, {})
        verified = bool(agent and agent.invoke_name_verified)
        targets.append({"target": target, "name": "通用调用默认" if target == "*" else target,
                        "origin": "default" if target == "*" else agent.origin if agent else "configured",
                        "overrides": dict(overrides), "effective": resolved["preferences"], "sources": resolved["sources"],
                        "writable": writable, "read_only_reason": reason,
                        "invoke_name_verified": verified, "discovered": agent is not None,
                        "dispatch_ready": False,
                        "blocked_reason": "偏好须由当前宿主工具确认并映射后用于下一次派发；本投影不证明调用能力。" if target == "*" or verified else
                                          "未发现或未验证此原生调用身份；可管理历史偏好，不能据此派发。",
                        "runtime_verified": False})
    return {"status": "ready", "targets": targets, "capabilities": capabilities(state.host),
            "source_path": str(state.path), "runtime_verified": False}


def effect(*, saved=False, published=False):
    return {"kind": "dispatch_preferences", "saved": saved, "pending_reload": False,
            "next_dispatch": published, "runtime_verified": False, "running_agents_changed": False,
            "cross_filesystem_crash_atomic": False,
            "message": "调用偏好保存后供下一次派发前只读解析；实际工具参数、原生完整定义优先级与模型执行仍须宿主确认。"}


def preview(state, scope, payload, agents, selection):
    if not isinstance(payload, dict) or set(payload) - {"edits", "reset"}:
        raise ConfigError("调用偏好预览字段无效")
    if not _writable(state)[0]:
        raise ConfigError("调用偏好文件或父目录为只读")
    edits, reset = payload.get("edits", {}), payload.get("reset", False)
    if not isinstance(edits, dict) or type(reset) is not bool or (reset and edits) or len(edits) > MAX_BATCH:
        raise ConfigError("调用偏好编辑或重置参数无效")
    document = copy.deepcopy(state.document)
    before_view = {row["target"]: row for row in public(state, scope, agents)["targets"]}
    layer = document if scope == "global" else document["projects"].setdefault(state.project, {"defaults": {}, "agents": {}})
    if reset:
        edits = {"*": {field: None for field in layer["defaults"]},
                 **{target: {field: None for field in row} for target, row in layer["agents"].items()}}
    warnings = [effect()["message"]]
    for target, values in edits.items():
        if target != "*":
            contract.target_name(target)
        if target not in before_view:
            raise ConfigError("调用偏好目标不属于当前清单；请先发现原生调用身份")
        if not isinstance(values, dict) or (not values and not reset):
            raise ConfigError("每个调用偏好目标须提供部分字段")
        checked = contract.validate_values(state.host, values, edits=True)
        row = layer["defaults"] if target == "*" else layer["agents"].setdefault(target, {})
        for field, value in checked.items():
            if value is None:
                row.pop(field, None)
            else:
                row[field] = value
        if target != "*" and not row:
            layer["agents"].pop(target, None)
    if scope == "project" and not layer["defaults"] and not layer["agents"]:
        document["projects"].pop(state.project, None)
    body = json_bytes(document, limit=contract.MAX_BYTES)
    contract.parse_document(body, state.host)
    after_state = Preferences(state.host, state.project, state.path, state.snapshot, state.parent_stamp, document)
    after_view = {row["target"]: row for row in public(after_state, scope, agents)["targets"]}
    # 整批 edits 先形成最终文档，再验证当前上下文实际变化的有效组合。
    # 逐目标写入时验证会把中间态当最终态，使相同 JSON 仅因键顺序不同而
    # 接受或拒绝；只验证显式 edits 又会漏掉继承默认 model/effort 的目标。
    # 当前可见目标并集包含已发现和历史已配置身份，但不遍历其他项目，避免
    # 把当前项目目录能力冒充其他项目的证据。未变化的旧组合也不因无关编辑
    # 被重新拒绝；模型变化始终保留 effort，用户须显式清除或重选不兼容值。
    for target in sorted(set(before_view) | set(after_view)):
        before = contract.project_preferences(state.document, target, state.project)["preferences"]
        after = contract.project_preferences(document, target, state.project)["preferences"]
        if before != after:
            warnings.append(selection(after))
    changes = []
    for target in sorted(edits):
        old, new = before_view[target], after_view.get(target)
        # 清空最后一条历史记录后该目标可消失，仍须展示移除后的继承结果。
        if new is None:
            resolved = contract.project_preferences(document, target, state.project)
            new = {"overrides": {}, "effective": resolved["preferences"], "sources": resolved["sources"]}
        for field in contract.FIELDS:
            if old["overrides"].get(field) != new["overrides"].get(field):
                changes.append({"role": target, "target": target, "name": old["name"], "origin": old["origin"],
                                "field": field, "before": old["overrides"].get(field), "after": new["overrides"].get(field),
                                "effective_before": old["effective"].get(field, "inherit"),
                                "effective_after": new["effective"].get(field, "inherit"),
                                "source_before": old["sources"][field], "source_after": new["sources"][field]})
    writes = [storage.Write("dispatch_preferences", state.path, state.snapshot, body, state.parent_stamp)] if changes else []
    return writes, changes, warnings
