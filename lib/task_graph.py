"""任务图的确定性校验、READY 计算、容量计算与请求级 QA 判定。

本模块保持纯函数：不读取文件、不派发 Agent、不修改宿主状态。PM/宿主适配层通过
``task_graph_cli.py`` 传入当前快照，从而避免提示词中的状态和实际调度状态漂移。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from pathlib import PurePosixPath
from typing import Iterable


class TaskGraphError(ValueError):
    """任务图、运行时锁或容量输入违反编排契约。"""


WITHDRAWAL_STATES = frozenset({"STOP_REQUESTED", "WITHDRAWN"})
VALID_STATES = WITHDRAWAL_STATES | frozenset(
    {"DECLARED", "BLOCKED", "READY", "RUNNING", "BUILD_VERIFIED", "QA_SCOPE_READY", "QA", "QA_PASSED", "RESULT_VERIFIED", "FAILED"}
)
VALID_TASK_TYPES = frozenset({"writer", "evidence", "read_only", "qa"})
SATISFIED_DEPENDENCY_STATES = frozenset({"BUILD_VERIFIED", "QA_SCOPE_READY", "QA", "QA_PASSED", "RESULT_VERIFIED"})
SEMANTIC_LOCK_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
EXCEPTIONAL_GATE_RE = re.compile(r"^exceptional:[a-z0-9][a-z0-9._-]*$")
VISUAL_GATE_RE = re.compile(r"^visual_approved:[^@\s]+@[A-Fa-f0-9]{8,128}$")
SOLUTION_GATE_RE = re.compile(r"solution_approved:[a-z0-9][a-z0-9._-]*@[0-9a-f]{64}\Z")


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
    agent_retired: bool = False


def delivery_complete(task_type: str, state: str) -> bool:
    """交付完成按任务类型判断，不能让只读结果冒充构建或独立 QA。

    Writer 的既有交付门禁保持原样；只读/证据仅接受身份和证据闭环后的
    RESULT_VERIFIED，旧文件保留为只读历史，不提升为当前任务完成。
    显式 QA 仍须已有handoff验证；此谓词不确认原生close或宿主线程额度。
    """
    if task_type == "qa":
        return state == "QA_PASSED"
    if task_type in {"read_only", "evidence"}:
        return state == "RESULT_VERIFIED"
    return task_type == "writer" and state in {"BUILD_VERIFIED", "QA_SCOPE_READY"}


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
    if VISUAL_GATE_RE.fullmatch(gate) or SOLUTION_GATE_RE.fullmatch(gate) or EXCEPTIONAL_GATE_RE.fullmatch(gate):
        return
    raise TaskGraphError(f"task {task_id} has unsupported gate: {gate}")


def _tasks_by_id(tasks: Iterable[Task]) -> dict[str, Task]:
    indexed: dict[str, Task] = {}
    reviewers: dict[str, str] = {}
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
        if task.task_type == "qa":
            # 唯一Reviewer是请求合同，不是路径锁或瞬时线程额度。声明时即拒绝
            # 第二个QA节点，历史、失败或退役也不自动授权换人；原Reviewer的
            # 差量复查更新同一任务和既有身份，因此不需要另存Reviewer账本。
            if task.request_id in reviewers:
                raise TaskGraphError(f"one QA task per request is required: {task.request_id} "
                                     f"({reviewers[task.request_id]}, {task.id})")
            reviewers[task.request_id] = task.id
        # 只给显式 QA 节点新增完成态，不能让 Writer 用审查结果冒充自身构建完成。
        if task.state == "QA_PASSED" and task.task_type != "qa":
            raise TaskGraphError(f"task {task.id}: QA_PASSED belongs only to a qa task")
        if task.state == "RESULT_VERIFIED" and task.task_type not in {"read_only", "evidence"}:
            raise TaskGraphError(f"task {task.id}: RESULT_VERIFIED belongs only to read_only or evidence tasks")
        if task.task_type in {"read_only", "evidence"} and task.state in {"BUILD_VERIFIED", "QA_SCOPE_READY", "QA"}:
            raise TaskGraphError(f"task {task.id}: read_only/evidence completion requires RESULT_VERIFIED settlement")
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


def validate_graph(tasks: Iterable[Task]) -> None:
    """校验 ID、双向边、循环、Gate、路径重叠和语义锁冲突。"""

    indexed = _tasks_by_id(tasks)
    expected_blocks: dict[str, set[str]] = {task_id: set() for task_id in indexed}
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

        for dependency in task.depends_on:
            expected_blocks[dependency].add(task.id)

    # 标准库按拓扑顺序迭代并检测环；合法依赖链的深度不应受解释器递归栈限制。
    # 按稳定的 ID 顺序建图，让多个可行遍历顺序中的首个诊断可重现。
    graph = TopologicalSorter({task_id: indexed[task_id].depends_on for task_id in sorted(indexed)})
    try:
        ordered_ids = tuple(graph.static_order())
    except CycleError as exc:
        raise TaskGraphError(f"dependency cycle detected at task: {exc.args[1][0]}") from exc

    for task in indexed.values():
        if set(task.blocks) != expected_blocks[task.id]:
            raise TaskGraphError(
                f"task {task.id} blocks/depends_on mismatch: "
                f"declared={sorted(task.blocks)}, expected={sorted(expected_blocks[task.id])}"
            )

    # 只需比较持有资源的任务。拓扑序保证此前的任务不可能依赖当前任务，
    # 因而每个任务至多回溯一次祖先，不必为每一对任务双向遍历依赖链。
    previous_paths: dict[str, dict[str, tuple[str, ...]]] = {}
    for task_id in ordered_ids:
        task = indexed[task_id]
        if not task.owned_paths and not task.semantic_locks:
            continue
        paths = {raw: _normalized_path_parts(raw, label=f"task {task.id} owned_paths")
                 for raw in task.owned_paths}
        ancestors = _transitive_dependencies(indexed, task_id) if previous_paths else set()
        for previous_id, earlier_paths in previous_paths.items():
            if previous_id in ancestors:
                continue
            for first_raw, first_parts in earlier_paths.items():
                for second_raw, second_parts in paths.items():
                    if _paths_overlap(first_parts, second_parts):
                        raise TaskGraphError(
                            "unordered tasks have overlapping owned paths: "
                            f"{previous_id}:{first_raw!r}, {task_id}:{second_raw!r}"
                        )
            shared_locks = sorted(set(indexed[previous_id].semantic_locks).intersection(task.semantic_locks))
            if shared_locks:
                raise TaskGraphError(
                    "unordered tasks share semantic lock(s): "
                    f"{previous_id}, {task_id}: {', '.join(shared_locks)}"
                )
        previous_paths[task_id] = paths


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
        if task.agent_retired:
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


def qa_ready(tasks: Iterable[Task], request_id: str, *, writer_ids: set[str] | None = None) -> bool:
    """核对当前检查点的 Writer barrier，缺省仍为完整请求闭包。

    Foundation 的唯一固定阶段由权威图适配层推导 writer_ids；本纯函数只核对
    该集合真实属于请求闭包且都是 Writer，不允许外部任务或空集合冒充通过。
    最终检查点不传子集，继续等待请求闭包所有 Writer BUILD_VERIFIED。
    """

    indexed = _tasks_by_id(tasks)
    validate_graph(indexed.values())
    closure = request_closure(indexed.values(), request_id)
    if writer_ids is not None:
        if not writer_ids or not writer_ids <= closure or any(indexed[key].task_type != "writer" for key in writer_ids):
            raise TaskGraphError("QA checkpoint writer IDs must be non-empty writers in the request closure")
        closure = writer_ids
    # 撤回不是成功依赖。只阻断当前检查点及其实际前置项，不阻塞无关请求。
    checkpoint = set(closure)
    if writer_ids is not None:
        for key in writer_ids:
            checkpoint.update(_transitive_dependencies(indexed, key))
    if any(indexed[key].state in WITHDRAWAL_STATES for key in checkpoint) or any(
        task.task_type == "qa" and task.request_id == request_id and task.state in WITHDRAWAL_STATES
        for task in indexed.values()
    ):
        return False
    writers = [indexed[task_id] for task_id in closure if indexed[task_id].task_type == "writer"]
    if not writers:
        return False
    return all(task.state == "BUILD_VERIFIED" for task in writers)


__all__ = [
    "Task",
    "TaskGraphError",
    "delivery_complete",
    "downstream_tasks",
    "effective_dispatch_capacity",
    "qa_ready",
    "ready_tasks",
    "request_closure",
    "validate_graph",
]
