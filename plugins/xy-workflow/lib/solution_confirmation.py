"""把 PM 明示的材料性方案决定绑定到任务和本次请求，沿用任务图的批准与就绪机制。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from lib.task_graph import SOLUTION_GATE_RE, TaskGraphError


EXECUTING_OR_DELIVERED = {"RUNNING", "QA", "BUILD_VERIFIED", "QA_SCOPE_READY"}


def decision_gates(task: dict) -> dict[str, str]:
    """按决定 ID 返回当前门。正文是用户获知的具体方案，摘要不含任务或交付档位。

    这样同请求多个任务可以使用同一次明确批准。JSON 数组保留分隔边界，不会因请求名、
    ID 或正文含标点和换行而混淆；原始正文改变就需要 PM 重新核实对应的用户决定。
    """
    decisions = task.get("solution_decisions", [])
    if not isinstance(decisions, list):
        raise TaskGraphError("solution_decisions must be an array")
    if not decisions:
        return {}
    request = task.get("request_id")
    if task.get("task_type") != "writer" or not isinstance(request, str) or not request.strip():
        raise TaskGraphError("solution_decisions require a writer and a current request_id")
    gates = {}
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {"id", "content"}:
            raise TaskGraphError("solution_decisions entries require exactly id and content")
        key, content = decision["id"], decision["content"]
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", key) or key in gates:
            raise TaskGraphError("solution_decisions require unique canonical decision IDs")
        if not isinstance(content, str) or not content.strip():
            raise TaskGraphError("solution_decisions require non-empty decision content")
        binding = json.dumps([request, key, content], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        gates[key] = f"solution_approved:{key}@{hashlib.sha256(binding).hexdigest()}"
    return gates


def bind_decisions(task: dict) -> None:
    """初始化、Light 单包或显式修订时补出依赖门，不写入 approved_gates。

    已提供的门若指向旧版本或来自另一请求，应当报错；忽略它会掩盖拿错权威的交接。
    """
    required = decision_gates(task)
    gates = task.get("gates", [])
    if not isinstance(gates, list) or any(not isinstance(gate, str) for gate in gates):
        raise TaskGraphError("task gates must be an array of strings")
    supplied = {gate for gate in gates if gate.startswith("solution_approved")}
    if supplied - set(required.values()):
        raise TaskGraphError("solution_approved gate differs from current request and solution_decisions")
    if required:
        task["gates"] = [*gates, *(gate for gate in required.values() if gate not in supplied)]


def check_shared_decisions(seen: dict, task: dict) -> dict[str, str]:
    """同请求同一决定只存在一个当前正文。分开的工作流以不同 ID 独立前进。"""
    decisions = decision_gates(task)
    for key, gate in decisions.items():
        if seen.setdefault((task["request_id"], key), gate) != gate:
            raise TaskGraphError(f"conflicting solution_decisions for request {task['request_id']!r}: {key}")
    return decisions


def validate_decisions(graph: dict, *, for_handoff: bool) -> None:
    """待决可持久化、查询和修订；活动、已交付或正式交接的 Writer 必须已有对应批准。"""
    approved = graph.get("approved_gates", [])
    if not isinstance(approved, list) or any(not isinstance(gate, str) for gate in approved):
        raise TaskGraphError("approved_gates must be an array of strings")
    if any(gate.startswith("solution_approved") and not SOLUTION_GATE_RE.fullmatch(gate) for gate in approved):
        raise TaskGraphError("approved_gates require fully bound solution_approved gates")
    confirmed = set(approved)
    sources = graph.get("solution_approval_sources", {})
    if (not isinstance(sources, dict) or any(gate not in confirmed or not SOLUTION_GATE_RE.fullmatch(gate)
            or not isinstance(reference, str) or not reference.strip() for gate, reference in sources.items())):
        raise TaskGraphError("solution_approval_sources require a current approved gate and non-empty source_ref")
    seen = {}
    for task in graph["tasks"]:
        required = set(check_shared_decisions(seen, task).values())
        actual = {gate for gate in task["gates"] if gate.startswith("solution_approved")}
        if actual != required:
            raise TaskGraphError("task gates must match current request and solution_decisions")
        needs_approval = for_handoff or task["state"] in EXECUTING_OR_DELIVERED
        if needs_approval and required - confirmed:
            raise TaskGraphError("writer requires current solution_approved gates")
        if for_handoff and required and set(task["gates"]) - confirmed:
            # 带决定的交接可能同时依赖页面视觉、上游例外等既有门。用户只同意方案
            # 时，这些独立批准仍必须在正式交接前具备；历史无方案记录沿原导出合同。
            raise TaskGraphError("solution approval cannot replace other required writer approvals")


def record_approvals(graph: dict, choices: Any, *, operation: str) -> None:
    """只记录 PM 根据用户明确答复提交的批准或撤回。两种操作都核对请求、任务与完整正文。

    外层 update 用源记录 SHA 做 CAS。调用方须单独提交批准，不能同补丁替换内容再批准；
    重复记录同一决定保持幂等，既有视觉、需求和例外授权均不由此入口改变。
    """
    if operation not in {"approve_solutions", "revoke_solutions"}:
        raise TaskGraphError("unknown solution approval operation")
    if not isinstance(choices, list) or not choices:
        raise TaskGraphError(f"{operation} requires a non-empty array")
    tasks = {task["id"]: task for task in graph["tasks"]}
    bound = {}
    for approval in choices:
        required = {"request_id", "task_id", "id", "content"}
        optional = {"source_ref"} if operation == "approve_solutions" else set()
        if not isinstance(approval, dict) or not required <= set(approval) <= required | optional:
            raise TaskGraphError(f"{operation} requires request_id, task_id, id and content")
        task = tasks.get(approval["task_id"]) if isinstance(approval["task_id"], str) else None
        choice = {"id": approval["id"], "content": approval["content"]}
        if (task is None or task["request_id"] != approval["request_id"]
                or choice not in task.get("solution_decisions", [])):
            raise TaskGraphError(f"{operation} does not match a current request, task and decision")
        source = approval.get("source_ref")
        if "source_ref" in approval and (not isinstance(source, str) or not source.strip()):
            raise TaskGraphError("approval source_ref must be a non-empty reference to the user decision")
        gate = decision_gates(task)[choice["id"]]
        if gate in bound and bound[gate] != source:
            raise TaskGraphError("conflicting source_ref for the same solution approval")
        bound[gate] = source
    if operation == "approve_solutions":
        approved = graph.setdefault("approved_gates", [])
        for gate, source in bound.items():
            if source is not None:
                # 指向真实用户答复的引用由 PM 提交；旧记录只保留门，不为其生成出处。
                refs = graph.setdefault("solution_approval_sources", {})
                if gate in refs and refs[gate] != source:
                    raise TaskGraphError("existing solution approval already references a different source_ref")
                refs[gate] = source
            if gate not in approved:
                approved.append(gate)
        return
    # 门由同请求的多个 Writer 共享；只允许撤回尚未用于实际执行的批准。
    # 若已有运行/交付，PM 须先协调真实执行或重定待开发范围，不能靠此命令
    # 假称停机、擦除历史证据，或把其他使用者的旧包当作当前已获批的方案。
    revoked = set(bound)
    for task in tasks.values():
        if task["state"] in EXECUTING_OR_DELIVERED and revoked.intersection(task["gates"]):
            raise TaskGraphError("revoke_solutions requires coordination with running or delivered writers")
    if "approved_gates" in graph:
        graph["approved_gates"] = [gate for gate in graph["approved_gates"] if gate not in revoked]
        for gate in revoked:
            graph.get("solution_approval_sources", {}).pop(gate, None)
