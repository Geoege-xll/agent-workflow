"""跨请求的临时资源投影；原记录中的 Task.state 始终是唯一状态权威。

这里只接收 CLI 已经通过各自固定核心校验的快照，既不读取文件，也不调用宿主。
候选是一次确定性的建议：每选中一项即占用本轮名额与资源，避免同批候选互撞。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent_continuation import active
from .task_graph import TaskGraphError


@dataclass(frozen=True)
class ResourceIdentity:
    """实际存在的每级节点身份，及从该节点到资源的名称语义后缀。

    文件系统读取只在 CLI 完成。同一 inode 的不同名称/硬链接共享空后缀；
    不存在路径以实际目录为锚点，仍能和该目录及其后代比较资源前缀。
    """

    anchors: tuple[tuple[tuple[int, int], tuple[str, ...]], ...]


@dataclass(frozen=True)
class RecordView:
    """一次读取的原记录及其局部就绪结果；不是可由 JSON 自报的验证凭据。"""

    path: str
    sha256: str
    project_root: str
    tasks: tuple[dict[str, Any], ...]
    execution_roots: dict[str, str]
    eligible: frozenset[str]
    semantic_scope: str | None = None
    external_paths: tuple[str, ...] = ()
    external_semantic_locks: tuple[str, ...] = ()
    resource_paths: dict[str, tuple[ResourceIdentity, ...]] | None = None
    external_resources: tuple[ResourceIdentity, ...] | None = None


def task_key(record: RecordView, task: dict[str, Any]) -> dict[str, str]:
    """任务 ID 只在原记录内唯一，跨请求输出必须保留来源和 request_id。"""
    return {"record": record.path, "request_id": task["request_id"], "task_id": task["id"]}


def _paths(record: RecordView, task: dict[str, Any]) -> tuple[ResourceIdentity, ...]:
    if not task.get("owned_paths"):
        return ()
    if record.resource_paths is None or task["id"] not in record.resource_paths:
        # 词法路径无法证明真实文件系统的名称等价；纯算法拒绝缺失的边界投影，
        # 不暗中访问文件系统，也不退回原先可能漏锁的 Path 字符串比较。
        raise TaskGraphError("resource identities must be projected by the admission file boundary")
    return record.resource_paths[task["id"]]


def _overlap(left: ResourceIdentity, right: ResourceIdentity) -> bool:
    for left_node, left_suffix in left.anchors:
        for right_node, right_suffix in right.anchors:
            if left_node == right_node:
                common = min(len(left_suffix), len(right_suffix))
                if left_suffix[:common] == right_suffix[:common]:
                    return True
    return False


def select_candidates(records: tuple[RecordView, ...], capacity: dict[str, int]) -> dict[str, Any]:
    """投影共享线程、Writer、真实执行路径与项目级语义锁，逐项解释等待。

    本轮输入的 host_available_subagents 是 PM 的原生宿主观察，不能由记录证明。
    即使退役或尚未绑定，RUNNING 仍占资源；退役不证明底层实例已经停止。
    Writer 上限只约束 Writer，不能阻止有线程名额的只读/QA 工作。
    """
    expected = {"configured_subagents", "configured_writers", "host_available_subagents"}
    if not isinstance(capacity, dict) or set(capacity) != expected:
        raise TaskGraphError("capacity requires configured_subagents/configured_writers/host_available_subagents")
    for name, value in capacity.items():
        minimum = 0 if name == "host_available_subagents" else 1
        if type(value) is not int or value < minimum:
            raise TaskGraphError(f"{name} must be integer >= {minimum}")
    paths: list[ResourceIdentity] = []
    locks: set[tuple[str, str]] = set()
    threads = writers = unbound_claims = 0
    references: set[tuple[str, str]] = set()
    for record in records:
        scope = record.semantic_scope or record.project_root
        if record.external_paths and record.external_resources is None:
            raise TaskGraphError("external resource identities must be projected by the admission file boundary")
        paths.extend(record.external_resources or ())
        locks.update((scope, item) for item in record.external_semantic_locks)
        for task in record.tasks:
            reference = task.get("agent_ref")
            if reference is not None:
                identity = (reference["host"], reference["agent_id"])
                if identity in references:
                    raise TaskGraphError("agent_ref is shared across authoritative records, including history")
                references.add(identity)
            if active(task):
                threads += 1
                writers += task["task_type"] == "writer"
                unbound_claims += "agent_ref" not in task
                paths.extend(_paths(record, task))
                locks.update((scope, item) for item in task.get("semantic_locks", ()))
    # 宿主“剩余”已经扣除了已创建实例，却还看不见未绑定的领取。将领取再次
    # 视作项目槽位之外的宿主预留，防止同一原生空槽被连续 claim 重复使用。
    # 宿主创建成功但绑定失败时仍保留这份预留，直到 PM 核实并补绑定/明确释放。
    thread_slots = max(0, min(capacity["configured_subagents"] - threads,
                              capacity["host_available_subagents"] - unbound_claims))
    writer_slots = max(0, capacity["configured_writers"] - writers)
    candidates, waiting = [], []
    for record in sorted(records, key=lambda value: value.path):
        for task in sorted(record.tasks, key=lambda value: (value["request_id"], value["id"])):
            key = task_key(record, task)
            reasons = []
            if task.get("agent_retired"):
                reasons.append("agent_retired")
            if "agent_ref" in task:
                reasons.append("already_bound")
            if task["state"] not in {"DECLARED", "BLOCKED", "READY"}:
                reasons.append("task_not_pending")
            if task["id"] not in record.eligible:
                reasons.append("record_gates_dependencies_locks_or_qa")
            owned = _paths(record, task)
            semantic = {(record.semantic_scope or record.project_root, item) for item in task.get("semantic_locks", ())}
            if any(_overlap(candidate, held) for candidate in owned for held in paths):
                reasons.append("path_conflict")
            if semantic & locks:
                reasons.append("semantic_lock_conflict")
            if not thread_slots:
                reasons.append("thread_capacity")
            if task["task_type"] == "writer" and not writer_slots:
                reasons.append("writer_capacity")
            if reasons:
                waiting.append({**key, "reasons": reasons})
                continue
            candidates.append(key)
            paths.extend(owned)
            locks.update(semantic)
            thread_slots -= 1
            if task["task_type"] == "writer":
                writer_slots -= 1
    return {"schema_version": 1, "candidates": candidates, "waiting": waiting,
            "active_subagents": threads, "active_writers": writers,
            "unbound_claims": unbound_claims,
            "remaining_subagent_slots": thread_slots, "remaining_writer_slots": writer_slots,
            "limitations": "One PM must provide the complete explicit active-record inventory and fresh native capacity. Shared locks cannot discover omitted records or guarantee independent-PM scheduling. RUNNING means claimed, not proof of a started native agent."}
