"""Worktree 配置与集成门禁：纯校验，不创建目录、不操作 Git 或派发 Agent。

文件写入仍由现有 owned_paths/semantic_locks 管理。目录隔离不会解除业务归属，
也不会让各分支的 BUILD_VERIFIED 自动变成集成 QA 就绪。
"""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any


class WorktreePolicyError(ValueError):
    """配置、隔离身份或集成证据不完整。"""


REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
DEFAULTS = {"mode": "auto", "merge": "confirm", "target_branch": "auto"}


def settings(lines: list[str]) -> dict[str, str]:
    """读取有意保持扁平的可选配置；缺省确认合并，拼错键不能静默开启自动模式。"""
    result = dict(DEFAULTS)
    active = False
    seen: set[str] = set()
    sections = 0
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            active = re.fullmatch(r"parallel_worktrees:\s*(?:#.*)?", raw) is not None
            if raw.startswith("parallel_worktrees:") and not active:
                raise WorktreePolicyError("parallel_worktrees must be a block mapping")
            sections += int(active)
            continue
        if not active:
            continue
        match = re.fullmatch(r"  ([a-z_]+):\s*([^#]*?)(?:\s+#.*)?", raw)
        if not match:
            raise WorktreePolicyError("parallel_worktrees supports only flat scalar settings")
        key, value = match.groups()
        value = value.strip()
        # 不把损坏的 YAML 引号静默剥除为 auto，避免配置拼写错误意外改变交付策略。
        if value[:1] in {"\"", "'"}:
            if len(value) < 2 or value[-1] != value[0] or value[0] in value[1:-1]:
                raise WorktreePolicyError("parallel_worktrees scalar has malformed quotes")
            value = value[1:-1]
        elif any(quote in value for quote in ("\"", "'")):
            raise WorktreePolicyError("parallel_worktrees scalar has malformed quotes")
        if key not in DEFAULTS or key in seen:
            raise WorktreePolicyError(f"unsupported or duplicate parallel_worktrees key: {key}")
        seen.add(key)
        result[key] = value
    if sections > 1:
        raise WorktreePolicyError("duplicate parallel_worktrees section")
    if result["mode"] not in {"auto", "off"}:
        raise WorktreePolicyError("parallel_worktrees.mode must be auto or off")
    if result["merge"] not in {"confirm", "auto"}:
        raise WorktreePolicyError("parallel_worktrees.merge must be confirm or auto")
    if not result["target_branch"] or any(c.isspace() for c in result["target_branch"]):
        raise WorktreePolicyError("parallel_worktrees.target_branch must be auto or an exact local branch")
    return result


def revision(value: Any, label: str, *, pending: bool = False) -> None:
    if pending and value is None:
        return
    if not isinstance(value, str) or not REVISION.fullmatch(value):
        raise WorktreePolicyError(f"{label} requires a full lowercase Git object ID")


def root_path(value: Any, label: str) -> None:
    """绝对目录只标识执行位置，绝不替代相对 owned_paths；实际身份另由 Git 工具核实。"""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise WorktreePolicyError(f"{label} requires an absolute worktree root")
    path = PurePath(value)
    if not path.is_absolute() or ".." in path.parts or str(path) != value:
        raise WorktreePolicyError(f"{label} requires a normalized absolute worktree root")


def validate_execution(payload: dict[str, Any]) -> None:
    """校验每个启用隔离的请求及工作单元；旧的普通任务不被强制带入 worktree 分支。"""
    tasks = payload["tasks"]
    integrations = payload.get("worktree_integrations", {})
    if not isinstance(integrations, dict):
        raise WorktreePolicyError("worktree_integrations must be an object keyed by request ID")
    isolated: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        workspace = task.get("execution_workspace")
        if workspace is None:
            continue
        if task["task_type"] != "writer" or not isinstance(workspace, dict):
            raise WorktreePolicyError("execution_workspace belongs only to a writer")
        if set(workspace) != {"root", "base_revision", "head_revision"}:
            raise WorktreePolicyError("execution_workspace requires root/base_revision/head_revision")
        root_path(workspace["root"], "execution_workspace.root")
        revision(workspace["base_revision"], "execution_workspace.base_revision")
        revision(workspace["head_revision"], "execution_workspace.head_revision",
                 pending=task["state"] != "BUILD_VERIFIED")
        isolated.setdefault(task["request_id"], []).append(task)
    if set(integrations) != set(isolated):
        raise WorktreePolicyError("worktree integrations must exactly match isolated request IDs")
    for request_id, writers in isolated.items():
        all_writers = [t for t in tasks if t["request_id"] == request_id and t["task_type"] == "writer"]
        if len(writers) != len(all_writers):
            raise WorktreePolicyError("an isolated request must bind every writer, including design work")
        record = integrations[request_id]
        required = {"root", "target_branch", "target_base", "head_revision", "verification"}
        if not isinstance(record, dict) or set(record) != required:
            raise WorktreePolicyError("worktree integration requires root/target_branch/target_base/head_revision/verification")
        root_path(record["root"], "integration.root")
        if not isinstance(record["target_branch"], str) or not record["target_branch"].strip():
            raise WorktreePolicyError("integration.target_branch must be explicit, never auto")
        if record["target_branch"] == "auto":
            raise WorktreePolicyError("integration.target_branch must be resolved before dispatch")
        revision(record["target_base"], "integration.target_base")
        revision(record["head_revision"], "integration.head_revision", pending=True)
        # 一个集成目录不能同时充当正在编辑的工作单元；不同任务默认各自独立。
        roots = [t["execution_workspace"]["root"] for t in writers]
        if record["root"] in roots or len(roots) != len(set(roots)):
            raise WorktreePolicyError("writers and integration require distinct worktree roots")
        evidence = record["verification"]
        if not isinstance(evidence, list):
            raise WorktreePolicyError("integration.verification must be an array")
        for check in evidence:
            if not isinstance(check, dict) or set(check) != {"command", "exit_code", "log_ref", "head_revision"}:
                raise WorktreePolicyError("integration check requires command/exit_code/log_ref/head_revision")
            if any(not isinstance(check[key], str) or not check[key].strip() for key in ("command", "log_ref")):
                raise WorktreePolicyError("integration command and resolvable log reference must not be empty")
            if type(check["exit_code"]) is not int:
                raise WorktreePolicyError("integration exit_code must be an integer")
            revision(check["head_revision"], "integration check.head_revision")


def integration_ready(payload: dict[str, Any], request_id: str) -> bool:
    """普通任务保持原 QA 路由；隔离请求必须具有同一集成修订上的成功验证证据。"""
    record = payload.get("worktree_integrations", {}).get(request_id)
    if record is None:
        return True
    head = record["head_revision"]
    evidence = record["verification"]
    return bool(head and evidence and all(
        check["head_revision"] == head and check["exit_code"] == 0 for check in evidence
    ))
