"""任务图的确定性校验、READY 计算、容量计算与请求级 QA 判定。

本模块保持纯函数：不读取文件、不派发 Agent、不修改宿主状态。PM/宿主适配层通过
``task_graph_cli.py`` 传入当前快照，从而避免提示词中的状态和实际调度状态漂移。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable


class TaskGraphError(ValueError):
    """任务图、运行时锁或容量输入违反编排契约。"""


VALID_STATES = frozenset(
    {"DECLARED", "BLOCKED", "READY", "RUNNING", "BUILD_VERIFIED", "QA_SCOPE_READY", "QA", "QA_PASSED", "FAILED"}
)
VALID_TASK_TYPES = frozenset({"writer", "evidence", "read_only", "qa"})
SATISFIED_DEPENDENCY_STATES = frozenset({"BUILD_VERIFIED", "QA_SCOPE_READY", "QA", "QA_PASSED"})
SEMANTIC_LOCK_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
EXCEPTIONAL_GATE_RE = re.compile(r"^exceptional:[a-z0-9][a-z0-9._-]*$")
VISUAL_GATE_RE = re.compile(r"^visual_approved:[^@\s]+@[A-Fa-f0-9]{8,128}$")


@dataclass(frozen=True)
class Task:
    """可被确定性调度器消费的最小任务包快照。"""

    id: str
    request_id: str
    depends_on: tuple[str, ...] = ()
    gates: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()
    owned_paths: tuple[str, ...] = ()
    semantic_locks: tuple[str, ...] = ()
    task_type: str = "writer"
    state: str = "DECLARED"


def _require_unique(values: tuple[str, ...], task_id: str, field: str) -> None:
    """重复边或锁容易掩盖生成错误，因此在进入图算法前直接拒绝。"""

    if len(values) != len(set(values)):
        raise TaskGraphError(f"task {task_id} has duplicate {field} values")


def _normalized_path_parts(raw: str, *, label: str) -> tuple[str, ...]:
    """把任务包路径规范为仓库内 POSIX 片段，并拒绝逃逸或宿主歧义。"""

    if not isinstance(raw, str) or not raw.strip():
        raise TaskGraphError(f"{label} contains an empty path")
    value = raw.strip()
    if "\\" in value:
        raise TaskGraphError(f"{label} must use forward slashes: {raw!r}")
    # 调度锁按路径前缀计算，不解释 shell/gitignore glob；允许 glob 会让 ``a/**`` 与
    # ``a/file`` 被误判为不冲突，因此必须在计划阶段改写为明确目录 ``a/``。
    if any(character in value for character in "*?[]"):
        raise TaskGraphError(f"{label} must not contain glob metacharacters: {raw!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or path == PurePosixPath("."):
        raise TaskGraphError(f"{label} must be a project-relative path: {raw!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise TaskGraphError(f"{label} must not contain traversal segments: {raw!r}")
    return path.parts


def _paths_overlap(first: tuple[str, ...], second: tuple[str, ...]) -> bool:
    """文件相等、目录祖先或目录后代都属于同一运行时写锁。"""

    common = min(len(first), len(second))
    return first[:common] == second[:common]


def _validate_gate(gate: str, task_id: str) -> None:
    if gate in {"requirements_approved", "platform_security_prompt"}:
        return
    if VISUAL_GATE_RE.fullmatch(gate) or EXCEPTIONAL_GATE_RE.fullmatch(gate):
        return
    raise TaskGraphError(f"task {task_id} has unsupported gate: {gate}")


def _tasks_by_id(tasks: Iterable[Task]) -> dict[str, Task]:
    indexed: dict[str, Task] = {}
    for task in tasks:
        if not isinstance(task, Task):
            raise TaskGraphError("tasks must contain Task values")
        if not task.id or not task.id.strip():
            raise TaskGraphError("task IDs must be non-empty")
        if task.id in indexed:
            raise TaskGraphError(f"duplicate task ID: {task.id}")
        if not task.request_id or not task.request_id.strip():
            raise TaskGraphError(f"task {task.id} has an empty request_id")
        if task.state not in VALID_STATES:
            raise TaskGraphError(f"task {task.id} has unsupported state: {task.state}")
        if task.task_type not in VALID_TASK_TYPES:
            raise TaskGraphError(f"task {task.id} has unsupported task_type: {task.task_type}")
        # 只给显式 QA 节点新增完成态，不能让 Writer 用审查结果冒充自身构建完成。
        if task.state == "QA_PASSED" and task.task_type != "qa":
            raise TaskGraphError(f"task {task.id}: QA_PASSED belongs only to a qa task")
        for field, values in (
            ("depends_on", task.depends_on),
            ("blocks", task.blocks),
            ("gates", task.gates),
            ("owned_paths", task.owned_paths),
            ("semantic_locks", task.semantic_locks),
        ):
            _require_unique(values, task.id, field)
        for path in task.owned_paths:
            _normalized_path_parts(path, label=f"task {task.id} owned_paths")
        for lock in task.semantic_locks:
            if not SEMANTIC_LOCK_RE.fullmatch(lock):
                raise TaskGraphError(f"task {task.id} has invalid semantic lock: {lock}")
        for gate in task.gates:
            _validate_gate(gate, task.id)
        indexed[task.id] = task
    return indexed


def _transitive_dependencies(indexed: dict[str, Task], task_id: str) -> set[str]:
    result: set[str] = set()
    pending = list(indexed[task_id].depends_on)
    while pending:
        dependency = pending.pop()
        if dependency in result:
            continue
        result.add(dependency)
        pending.extend(indexed[dependency].depends_on)
    return result


def _ordered(indexed: dict[str, Task], first: str, second: str) -> bool:
    """存在任意方向的传递依赖即说明两个任务不会成为并行 Writer。"""

    return (
        first in _transitive_dependencies(indexed, second)
        or second in _transitive_dependencies(indexed, first)
    )


def validate_graph(tasks: Iterable[Task]) -> None:
    """校验 ID、双向边、循环、Gate、路径重叠和语义锁冲突。"""

    indexed = _tasks_by_id(tasks)
    for task in indexed.values():
        if task.id in task.depends_on:
            raise TaskGraphError(f"task {task.id} cannot depend on itself")
        if task.id in task.blocks:
            raise TaskGraphError(f"task {task.id} cannot block itself")
        missing_dependencies = sorted(set(task.depends_on) - indexed.keys())
        if missing_dependencies:
            raise TaskGraphError(
                f"task {task.id} depends on unknown task(s): {', '.join(missing_dependencies)}"
            )
        missing_blocks = sorted(set(task.blocks) - indexed.keys())
        if missing_blocks:
            raise TaskGraphError(
                f"task {task.id} blocks unknown task(s): {', '.join(missing_blocks)}"
            )

    # 先验证无环，再做传递依赖判断；否则冲突检查可能在错误图上循环。
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise TaskGraphError(f"dependency cycle detected at task: {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in indexed[task_id].depends_on:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(indexed):
        visit(task_id)

    for task in indexed.values():
        expected_blocks = {
            candidate.id
            for candidate in indexed.values()
            if task.id in candidate.depends_on
        }
        if set(task.blocks) != expected_blocks:
            raise TaskGraphError(
                f"task {task.id} blocks/depends_on mismatch: "
                f"declared={sorted(task.blocks)}, expected={sorted(expected_blocks)}"
            )

    ordered_ids = sorted(indexed)
    for position, first_id in enumerate(ordered_ids):
        first = indexed[first_id]
        first_paths = [
            (raw, _normalized_path_parts(raw, label=f"task {first.id} owned_paths"))
            for raw in first.owned_paths
        ]
        for second_id in ordered_ids[position + 1 :]:
            if _ordered(indexed, first_id, second_id):
                continue
            second = indexed[second_id]
            second_paths = [
                (raw, _normalized_path_parts(raw, label=f"task {second.id} owned_paths"))
                for raw in second.owned_paths
            ]
            for first_raw, first_parts in first_paths:
                for second_raw, second_parts in second_paths:
                    if _paths_overlap(first_parts, second_parts):
                        raise TaskGraphError(
                            "unordered tasks have overlapping owned paths: "
                            f"{first.id}:{first_raw!r}, {second.id}:{second_raw!r}"
                        )
            shared_locks = sorted(set(first.semantic_locks) & set(second.semantic_locks))
            if shared_locks:
                raise TaskGraphError(
                    "unordered tasks share semantic lock(s): "
                    f"{first.id}, {second.id}: {', '.join(shared_locks)}"
                )


def ready_tasks(
    tasks: Iterable[Task],
    *,
    approved_gates: set[str],
    active_paths: set[str],
    active_semantic_locks: set[str],
    capacity: int,
) -> list[str]:
    """从唯一的 Task.state 快照返回当前可派发任务，容量等待不会新增依赖。"""

    if capacity < 0:
        raise TaskGraphError("capacity must be >= 0")
    indexed = _tasks_by_id(tasks)
    validate_graph(indexed.values())
    active_path_parts = [
        _normalized_path_parts(path, label="active_paths") for path in active_paths
    ]
    for lock in active_semantic_locks:
        if not SEMANTIC_LOCK_RE.fullmatch(lock):
            raise TaskGraphError(f"invalid active semantic lock: {lock}")

    # 容量耗尽时不允许先入队一个任务再检查上限；但必须放在输入校验之后，
    # 避免暂时没有槽位时将损坏的 DAG、路径或语义锁快照误判为正常等待。
    if capacity == 0:
        return []

    ready: list[str] = []
    for task_id in sorted(indexed):
        task = indexed[task_id]
        if task.task_type == "qa":
            continue
        if task.state not in {"DECLARED", "BLOCKED", "READY"}:
            continue
        dependencies = [indexed[dependency] for dependency in task.depends_on]
        if any(dependency.state == "FAILED" for dependency in dependencies):
            continue
        if any(
            dependency.state not in SATISFIED_DEPENDENCY_STATES
            for dependency in dependencies
        ):
            continue
        if any(gate not in approved_gates for gate in task.gates):
            continue
        owned_parts = [
            _normalized_path_parts(path, label=f"task {task.id} owned_paths")
            for path in task.owned_paths
        ]
        if any(
            _paths_overlap(candidate, active)
            for candidate in owned_parts
            for active in active_path_parts
        ):
            continue
        if set(task.semantic_locks) & active_semantic_locks:
            continue
        ready.append(task_id)
        if len(ready) >= capacity:
            break
    return ready


def effective_dispatch_capacity(
    *,
    configured_subagents: int,
    configured_writers: int,
    host_available_subagents: int,
    active_subagents: int,
    active_writers: int,
) -> int:
    """计算项目上限、宿主剩余槽位和活跃 Writer 共同允许的新增派发数。"""

    for label, value in (
        ("configured_subagents", configured_subagents),
        ("configured_writers", configured_writers),
    ):
        if value < 1:
            raise TaskGraphError(f"{label} must be >= 1")
    for label, value in (
        ("host_available_subagents", host_available_subagents),
        ("active_subagents", active_subagents),
        ("active_writers", active_writers),
    ):
        if value < 0:
            raise TaskGraphError(f"{label} must be >= 0")
    return max(
        0,
        min(
            configured_subagents - active_subagents,
            configured_writers - active_writers,
            host_available_subagents,
        ),
    )


def downstream_tasks(tasks: Iterable[Task], task_id: str) -> list[str]:
    """返回直接下游任务，结果稳定排序。"""

    indexed = _tasks_by_id(tasks)
    validate_graph(indexed.values())
    if task_id not in indexed:
        raise TaskGraphError(f"unknown task ID: {task_id}")
    return sorted(
        candidate.id for candidate in indexed.values() if task_id in candidate.depends_on
    )


def request_closure(tasks: Iterable[Task], request_id: str) -> set[str]:
    """返回请求任务及其跨请求共享的全部传递依赖。"""

    indexed = _tasks_by_id(tasks)
    validate_graph(indexed.values())
    closure = {task.id for task in indexed.values() if task.request_id == request_id}
    pending = list(sorted(closure))
    while pending:
        task_id = pending.pop()
        for dependency in indexed[task_id].depends_on:
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    return closure


def qa_ready(tasks: Iterable[Task], request_id: str) -> bool:
    """仅当请求闭包中的 Writer 全部 BUILD_VERIFIED 时允许派发统一 QA。"""

    indexed = _tasks_by_id(tasks)
    validate_graph(indexed.values())
    closure = request_closure(indexed.values(), request_id)
    writers = [indexed[task_id] for task_id in closure if indexed[task_id].task_type == "writer"]
    if not writers:
        return False
    return all(task.state == "BUILD_VERIFIED" for task in writers)


__all__ = [
    "Task",
    "TaskGraphError",
    "downstream_tasks",
    "effective_dispatch_capacity",
    "qa_ready",
    "ready_tasks",
    "request_closure",
    "validate_graph",
]
