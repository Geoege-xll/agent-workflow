"""校验任务图中的可选原生身份，并按 PM 当前观察提供只读续用建议。

原生工具仍由当前宿主暴露和执行。本模块不查询宿主、不发消息、不派发 Agent，
不保存另一份存活／权限／任务状态；ID 的形状校验也不能证明它真实存在。
"""

from __future__ import annotations

from typing import Any
import unicodedata
import re
from pathlib import PurePosixPath

try:
    from .task_graph import TaskGraphError
except ImportError:
    from task_graph import TaskGraphError


HOSTS = ("codex", "claude", "antigravity")
OBSERVED_STATES = ("running", "idle", "cancelled", "missing", "unknown")
INTENTS = ("observe", "progress", "append", "independent")
CAPABILITIES = ("non_interrupting_message", "idle_followup")
MAX_AGENT_ID_LENGTH = 256
IDENTITY_FIELDS = frozenset({"workflow_level", "module", "role", "agent_alias", "instance_policy", "context_policy"})
ALIAS_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
ROLE_RE = re.compile(r"xy-[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def validate_identity(task: dict[str, Any]) -> None:
    """绑定职责别名与模块根；声明只约束交接，不证明宿主已隔离上下文。

    根模块`.`不是整个仓库写许可，实际授权仍由owned_paths及原有保护门禁限定。
    不接收继承/复制历史的替代策略，也不替调用方推断实际原生身份。
    """
    missing = IDENTITY_FIELDS - set(task)
    if missing:
        raise TaskGraphError("task is missing 2.0 identity field(s): " + ", ".join(sorted(missing)))
    if task["workflow_level"] not in ("Light", "Full"):
        raise TaskGraphError("workflow_level must be Light or Full")
    if task["instance_policy"] != "fresh" or task["context_policy"] != "handoff_only":
        raise TaskGraphError("2.0 requires instance_policy fresh and context_policy handoff_only")
    for field, pattern in (("agent_alias", ALIAS_RE), ("role", ROLE_RE)):
        if not isinstance(task[field], str) or not pattern.fullmatch(task[field]):
            raise TaskGraphError(f"task {field} must be a bounded canonical identifier")
    module = task["module"]
    if (not isinstance(module, str) or not module.strip() or "\\" in module
            or PurePosixPath(module).is_absolute() or ".." in module.split("/")
            or any(char in module for char in "*?[]")
            or any(unicodedata.category(char).startswith("C") for char in module)
            or module != PurePosixPath(module).as_posix()):
        raise TaskGraphError("module must be a normalized project-relative module root (or .)")
    for path in task.get("owned_paths", []):
        if isinstance(path, str) and module != "." and not (
                path.rstrip("/") == module or path.startswith(module + "/")):
            raise TaskGraphError(f"owned_paths must stay inside module {module}: {path}")
    if "agent_retired" in task and not isinstance(task["agent_retired"], bool):
        raise TaskGraphError("agent_retired must be a boolean")
    if "handoff_assessment" in task:
        assessment = task["handoff_assessment"]
        if (not isinstance(assessment, dict)
                or set(assessment) != {"independent_qa", "documentation", "reason"}
                or any(assessment.get(key) not in ("required", "not_required")
                       for key in ("independent_qa", "documentation"))
                or not isinstance(assessment.get("reason"), str) or not assessment["reason"].strip()):
            raise TaskGraphError("handoff_assessment requires independent_qa, documentation and a non-empty reason")
        if task["workflow_level"] == "Full" and assessment["independent_qa"] != "required":
            raise TaskGraphError("Full handoff_assessment cannot waive independent QA")


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
    """别名稳定对应模块/角色，不同任务不能复用同宿主原生ID，包括历史引用。

    已完成历史引用只作追溯，不能据此证明另一个任务已获派发或角色授权。
    该不变量在整个更新结果上校验，避免多任务补丁或重入 RUNNING 绕过冲突。
    """
    owners: dict[tuple[str, str], str] = {}
    aliases: dict[str, tuple[str, str]] = {}
    for task in tasks:
        validate_identity(task)
        binding = (task["module"], task["role"])
        if aliases.setdefault(task["agent_alias"], binding) != binding:
            raise TaskGraphError("agent_alias cannot drift between module or role bindings")
        if "agent_ref" not in task:
            continue
        reference = validate_reference(task["agent_ref"], f"task {task.get('id')}.agent_ref")
        key = (reference["host"], reference["agent_id"])
        if key in owners:
            raise TaskGraphError(f"agent_ref is shared across tasks (including history): {owners[key]}, {task.get('id')}")
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
    elif before.get("agent_retired") or not active(before):
        raise TaskGraphError("first agent_ref binding requires an existing RUNNING task or explicit qa task in QA")


def continuation(task: dict[str, Any], host: str, observed_state: str, *,
                 intent: str | None = None, capabilities: tuple[str, ...] = ()) -> dict[str, Any]:
    """按当前观察、动作意图与实际能力返回建议，不执行原生动作。

    不传 intent 的旧调用保留 running→wait、idle→followup 合同；新调用必须显式
    声明当前工具已核实的能力。文档、版本和配置均不能推导消息不会中断运行。
    追加的批准、完整修订交接和收到修订的确认仍由 PM 负责，不能由本纯查询生成。
    """
    if host not in HOSTS or observed_state not in OBSERVED_STATES:
        raise TaskGraphError("continuation requires a supported host and explicit observed-state")
    if intent is not None and intent not in INTENTS:
        raise TaskGraphError("unsupported continuation intent")
    if (not isinstance(capabilities, (tuple, list))
            or any(not isinstance(item, str) or item not in CAPABILITIES for item in capabilities)
            or len(set(capabilities)) != len(capabilities)):
        raise TaskGraphError("continuation capabilities must be unique supported names")
    if intent is None and capabilities:
        raise TaskGraphError("explicit capabilities require an explicit continuation intent")
    reference = task.get("agent_ref")
    reason = "unbound"
    if reference is not None:
        validate_reference(reference)
        if task.get("agent_retired"):
            reason = "agent_retired"
        elif reference["host"] != host:
            reason = "host_mismatch"
        elif not active(task):
            reason = "task_not_active"
        else:
            reason = observed_state
    elif task.get("agent_retired"):
        reason = "agent_retired"
    allowed = reason in {"running", "idle"}
    result = {
        "task_id": task["id"], "agent_alias": task["agent_alias"], "agent_ref": reference, "observed_state": observed_state,
        "reuse_allowed": allowed, "reason": reason,
        "action": "wait" if reason == "running" else "followup" if reason == "idle" else "blocked",
        "handoff_required": True,
        "advice": (
            "核对当前完整 Task Pack、scope、角色与授权后，通过当前宿主原生工具复用同一 ID；running 时先等待。"
            if allowed else "停止自动续用，先由 PM 核实原生身份、当前宿主观察及任务授权；本查询不创建替代 Agent。"
        ),
        "limitations": "ID 不证明存活、角色权限、批准或完成；本结果不派发、不发消息、不改状态。",
    }
    if intent is None:
        return result

    # 先保留身份、取消与退役拒绝，再考虑意图；独立任务也不能借此复活旧实例。
    # 能力只是调用方刚核实的工具事实，不落盘、不形成另一份生命周期状态。
    result.update(intent=intent, capabilities=list(capabilities), revision_required=intent == "append",
                  acceptance_requires_ack=intent == "append", runtime_verified=False)
    if not allowed:
        return result
    if intent == "independent":
        result.update(action="new_task", reason="independent_task", reuse_allowed=False,
                      advice="由 PM 为独立需求建立各自获批的新记录与新实例；不要追加到原实例或复用旧结果。")
    elif observed_state == "running":
        if intent in {"progress", "append"} and "non_interrupting_message" in capabilities:
            result.update(action="message", reason="non_interrupting_message_available",
                          advice="通过当前已核实的非打断消息工具向同一原生 ID 发送；保持原任务连续执行，不用 interrupt 替代 steer。")
        else:
            result.update(action="wait", reason="running" if intent == "observe" else "non_interrupting_message_unavailable",
                          advice="等待原实例下一次报告或完成；不打断、不重启、不重复派发，也不轮询历史。")
    elif "idle_followup" not in capabilities:
        result.update(action="blocked", reason="idle_followup_unavailable", reuse_allowed=False,
                      advice="当前未核实原生 idle 续发能力，由 PM 核实；不要用新用户会话冒充同实例续用。")
    else:
        result.update(advice="核对当前完整 Task Pack、角色与授权后，用当前原生续发工具恢复同一 idle ID。")
    if intent == "append":
        result["advice"] += " 追加前修订完整约定并取得必要批准；确认工作者收到修订后才接受新范围结果，旧结果不证明新范围完成。"
    return result
