"""原请求交付范围的读取与校验；只消费现有图、单包和项目路径，不生成业务批准。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from lib.task_graph import TaskGraphError
from lib.task_sources import project_root


def request_scopes(record: dict[str, Any]) -> dict[str, str]:
    """读取原记录中的交付上限。Full 图可含多个请求，单包只投影自己所属请求。

    旧记录缺字段时继续使用该请求已有的授权；显式空值或未知范围则是坏数据。
    此处只解释 PM 已从原始委托确定的范围，不分析对话文字或生成授权。
    """
    if "request_scope" not in record:
        return {}
    scopes = record["request_scope"]
    if "task" in record:
        request_id = record["task"].get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            raise TaskGraphError("request_scope needs a task request_id")
        scopes = {request_id: scopes}
    if not isinstance(scopes, dict) or not scopes:
        raise TaskGraphError("graph request_scope must map request IDs to their delivery scopes")
    for request_id, value in scopes.items():
        if not isinstance(request_id, str) or not request_id.strip() or value not in (
            "discussion_only", "prototype_only", "implementation"
        ):
            raise TaskGraphError("invalid request_scope: expected discussion_only, prototype_only or implementation")
    return scopes


def validate_scoped_tasks(graph: dict[str, Any], standards_root: str | None, root: Path | None) -> None:
    """在原图完成任务字段与角色校验后，按原请求限制这些任务；未声明范围的旧记录沿用原合同。"""
    scopes = request_scopes(graph)
    if not scopes:
        return
    tasks = graph["tasks"]
    request_ids = {task["request_id"] for task in tasks}
    if isinstance(graph.get("request_id"), str):
        request_ids.add(graph["request_id"])
    if any(request not in request_ids and scope != "discussion_only" for request, scope in scopes.items()):
        raise TaskGraphError("request_scope references an unknown request_id")
    gate_owners: dict[str, str] = {}
    for task in tasks:
        request = task["request_id"]
        scope = scopes.get(request)
        if scope == "discussion_only":
            raise TaskGraphError("discussion_only does not authorize any execution task")
        if scope == "prototype_only":
            _validate_prototype_task(task, standards_root, root)
        # 旧批准数组按门禁名记录，两个请求用了同一个名字时无法证明批准属于谁。
        # 这些请求各用自己的权威图；没有执行节点的讨论可以留在原图中。
        for gate in task["gates"]:
            if gate_owners.setdefault(gate, request) != request:
                raise TaskGraphError("shared approval gates across request IDs require separate authoritative graphs")


def check_record_scopes(seen: dict[tuple[str, str], str | None], project: str,
                        request_ids: Iterable[str], declared: dict[str, str]) -> None:
    """在调度器当前显式清单内比对同请求范围，project 是已核实的物理 Git／项目身份。"""
    for request in declared.keys() | set(request_ids):
        key = (project, request)
        current = declared.get(request)
        previous = seen.setdefault(key, current)
        # 无范围旧包继续服务独立请求，但不能绕过同一请求已声明的讨论／原型限制。
        if current != previous and {current, previous} & {"discussion_only", "prototype_only"}:
            raise TaskGraphError(f"conflicting request_scope across authoritative records: {request}")


def _validate_prototype_task(task: dict[str, Any], standards_root: str | None, root: Path | None) -> None:
    """仅原型委托允许设计角色写入已选适配器的原型子路径，支持尚未创建的页面。"""
    # 先排除只读角色伪装、标准维护或生产节点，再读取经过常规 Writer 校验的适配器。
    if (task["task_type"] != "writer" or task.get("role") != "xy-uiux"
            or task.get("surface_kind") != "design_ui" or task.get("design_mode", "prototype") != "prototype"):
        raise TaskGraphError("prototype_only authorizes only the prototype design writer")
    prototype_root = PurePosixPath(standards_root) / "prototype"
    for path in task["owned_paths"]:
        # 所有权来自图中的具体原型子路径，工作树只改变物理执行位置。
        if prototype_root not in PurePosixPath(path).parents:
            raise TaskGraphError("prototype_only writes require owned paths within the prototype directory")
    project = project_root(root)
    _check_prototype_paths(project, task, standards_root)
    workspace = task.get("execution_workspace")
    if workspace is not None:
        from lib.delivery.worktree_cli import linked, primary_worktree
        from lib.worktree_policy import root_path

        if not isinstance(workspace, dict):
            raise TaskGraphError("execution_workspace requires a worktree root")
        raw_root = workspace.get("root")
        root_path(raw_root, "execution_workspace.root")
        # 从任一 checkout 进入时都检查主树和绑定执行树；只有完成 Git 身份核验后，
        # 才可复用上面已经检查过的同一物理根，避免改变 --project 就绕过另一侧的约束。
        primary = primary_worktree(project)
        execution = linked(primary, raw_root)
        for actual_root in (primary, execution):
            if not actual_root.samefile(project):
                _check_prototype_paths(actual_root, task, standards_root)


def _check_prototype_paths(project: Path, task: dict[str, Any], standards_root: str) -> None:
    """从指定物理根检查授权；同名路径在不同 checkout 中可能指向不同资源。"""
    from lib.project.validate_project_config import path_has_symlink
    from lib.task_graph_init import adapter_docs

    docs, _ = adapter_docs(project, task["controlled_document_access"]["adapter"])
    if docs["standards_root"].rstrip("/") != standards_root:
        raise TaskGraphError("prototype_only standards root differs from the selected project adapter")
    for path in task["owned_paths"]:
        actual = project / path
        if path_has_symlink(project, Path(path)) or actual.is_file() and actual.stat().st_nlink != 1:
            raise TaskGraphError("prototype_only owned paths must not traverse links")
