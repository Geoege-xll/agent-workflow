"""校验任务图中的可选原生身份，并按 PM 当前观察提供只读续用建议。

原生工具仍由当前宿主暴露和执行。本模块不查询宿主、不发消息、不派发 Agent，
不保存另一份存活／权限／任务状态；ID 的形状校验也不能证明它真实存在。
"""

from __future__ import annotations

from typing import Any
import unicodedata

try:
    from .task_graph import TaskGraphError
except ImportError:
    from task_graph import TaskGraphError


HOSTS = ("codex", "claude", "antigravity")
OBSERVED_STATES = ("running", "idle", "cancelled", "missing", "unknown")
MAX_AGENT_ID_LENGTH = 256


def active(task: dict[str, Any]) -> bool:
    """沿用原任务图的活动语义：Writer 的 QA 已交接，显式 QA 的 QA 仍在审查。"""
    return task.get("state") == "RUNNING" or (
        task.get("task_type") == "qa" and task.get("state") == "QA"
    )


def validate_reference(value: Any, label: str = "agent_ref") -> dict[str, str]:
    """只接受有界原生 ID，不归一化或截断身份，避免不同身份被静默合并。

    原生 ID 可带路径分隔符（例如当前宿主的任务名），但不允许空白、控制字符
    或额外状态字段。真实 ID 必须来自 PM 已获授权的原生派发结果。
    """
    if not isinstance(value, dict) or set(value) != {"host", "agent_id"}:
        raise TaskGraphError(f"{label} must contain exactly host and agent_id")
    host, agent_id = value["host"], value["agent_id"]
    if host not in HOSTS:
        raise TaskGraphError(f"{label}.host must be codex, claude or antigravity")
    if (not isinstance(agent_id, str) or not 1 <= len(agent_id) <= MAX_AGENT_ID_LENGTH
            or any(char.isspace() or unicodedata.category(char).startswith("C") for char in agent_id)):
        raise TaskGraphError(f"{label}.agent_id must be 1..256 characters without whitespace or controls")
    return value


def validate_references(tasks: list[dict[str, Any]]) -> None:
    """兼容未绑定旧图；同宿主同 ID 不能同时代表两个活动任务。

    已完成历史引用只作追溯，不能据此证明另一个任务已获派发或角色授权。
    该不变量在整个更新结果上校验，避免多任务补丁或重入 RUNNING 绕过冲突。
    """
    owners: dict[tuple[str, str], str] = {}
    for task in tasks:
        if "agent_ref" not in task:
            continue
        reference = validate_reference(task["agent_ref"], f"task {task.get('id')}.agent_ref")
        if active(task):
            key = (reference["host"], reference["agent_id"])
            if key in owners:
                raise TaskGraphError(f"agent_ref is shared by active tasks: {owners[key]}, {task.get('id')}")
            owners[key] = task.get("id", "")


def check_binding(before: dict[str, Any], reference: Any) -> None:
    """首次绑定只补记已经运行的任务；已绑定身份仅允许同值幂等。

    先看补丁前状态，防止把 DECLARED→RUNNING 与首次绑定合在一起当作真实
    原生派发观察。换绑或清空须回到 PM 解决实际身份问题，不能静默覆盖历史。
    """
    validate_reference(reference)
    if "agent_ref" in before:
        if before["agent_ref"] != reference:
            raise TaskGraphError("existing agent_ref cannot be replaced or cleared")
    elif not active(before):
        raise TaskGraphError("first agent_ref binding requires an existing RUNNING task or explicit qa task in QA")


def continuation(task: dict[str, Any], host: str, observed_state: str) -> dict[str, Any]:
    """返回建议而非执行许可；存活、批准、角色和完整交接仍由 PM 与原宿主确认。"""
    if host not in HOSTS or observed_state not in OBSERVED_STATES:
        raise TaskGraphError("continuation requires a supported host and explicit observed-state")
    reference = task.get("agent_ref")
    reason = "unbound"
    if reference is not None:
        validate_reference(reference)
        if reference["host"] != host:
            reason = "host_mismatch"
        elif not active(task):
            reason = "task_not_active"
        else:
            reason = observed_state
    allowed = reason in {"running", "idle"}
    return {
        "task_id": task["id"], "agent_ref": reference, "observed_state": observed_state,
        "reuse_allowed": allowed, "reason": reason,
        "action": "wait" if reason == "running" else "followup" if reason == "idle" else "blocked",
        "handoff_required": True,
        "advice": (
            "核对当前完整 Task Pack、scope、角色与授权后，通过当前宿主原生工具复用同一 ID；running 时先等待。"
            if allowed else "停止自动续用，先由 PM 核实原生身份、当前宿主观察及任务授权；本查询不创建替代 Agent。"
        ),
        "limitations": "ID 不证明存活、角色权限、批准或完成；本结果不派发、不发消息、不改状态。",
    }
