#!/usr/bin/env python3
"""通过 JSON 快照为 PM 提供确定性的任务图门禁。

原有查询保持只读；显式 init/update/task 操作可创建内部快照、更新或导出任务包，不派发
Agent、不运行验证、不写项目计划，也不生成批准或 QA 结论。
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .agent_continuation import HOSTS, OBSERVED_STATES, continuation, validate_references
    from .worktree_policy import WorktreePolicyError, integration_ready, validate_execution
    from .standard_paths import canonical_standard_path, standard_domain, builtin_source_path, source_domain, canonical_standard_source_path
    from .validate_project_docs import builtin_standard_rule_catalog
    from .task_sources import project_root, validate_task_source
    from .request_scope import request_scopes, validate_scoped_tasks
    from .task_graph import (
        Task,
        TaskGraphError,
        effective_dispatch_capacity,
        qa_ready,
        ready_tasks,
        request_closure,
        validate_graph,
    )
except ImportError:
    from agent_continuation import HOSTS, OBSERVED_STATES, continuation, validate_references
    from worktree_policy import WorktreePolicyError, integration_ready, validate_execution
    from standard_paths import canonical_standard_path, standard_domain, builtin_source_path, source_domain, canonical_standard_source_path
    from validate_project_docs import builtin_standard_rule_catalog
    from task_sources import project_root, validate_task_source
    from request_scope import request_scopes, validate_scoped_tasks
    from task_graph import (  # type: ignore[no-redef]
        Task,
        TaskGraphError,
        effective_dispatch_capacity,
        qa_ready,
        ready_tasks,
        request_closure,
        validate_graph,
    )

from lib import task_intent
from lib.hosts.dispatch_contract import DEFAULT_DISPATCH, DispatchPolicy, bound_export_reference
from lib.hosts.factory import dispatch_policy, handoff_policy, packaged_host
from lib.solution_confirmation import bind_decisions, validate_decisions
from lib.verification_inputs import command_fingerprints, validate_command
from lib.writer_prerequisites import (business_confirmation, require_writer, reviewed_business_confirmations,
                                      validate_visual_record, writer_blockers)


GRAPH_FIELDS = {
    "id",
    "request_id",
    "task_type",
    "depends_on",
    "blocks",
    "gates",
    "owned_paths",
    "semantic_locks",
    "state",
}
PLAN_ONLY_FIELDS = task_intent.RECORD_FIELDS | {
    "workflow_level", "module", "agent_alias", "instance_policy", "context_policy",
    "agent_retired", "handoff_assessment",
    "agent_ref",
    "execution_workspace",
    "role",
    "goal",
    "input_contracts",
    "output_contracts",
    "acceptance_evidence",
    "verification_commands",
    "ui_change",
    "required_skills",
    "audit_surfaces",
    "surface_kind",
    "design_mode",
    "qa_scope",
    "controlled_document_access",
    "standards_exceptions", "additional_business_confirmation", "visual_approval",
    "foundation_task_id", "foundation_receipt", "request_receipt", "qa_review_revision", "qa_projection",
    "qa_scope_ref", "qa_scope_fingerprint", "qa_projection_baselines", "solution_decisions", "solution_consultation",
}
UI_CHANGE_FIELDS = {
    "route",
    "design_delta",
    "prototype_policy",
    "prototype_decision",
    "design_authority_refs",
    "affected_surfaces",
    "justification",
}
PROTOTYPE_DECISION_FIELDS = {
    "source",
    "choice_ref",
    "requirement_fingerprint",
    "affected_surfaces",
    "recommended_policy",
    "recommendation_reason",
    "selected_policy",
}
UI_AUTHORITY_REF_FIELDS = {
    "kind",
    "authority_id",
    "path",
    "anchor",
    "content_fingerprint",
    "resolution_state",
}
UI_CONTRACT_FIELDS = {"prototype_paths"}
UI_ROUTES = {"UI-Conformance", "UI-Patch", "UI-Page", "UI-Flow"}
UI_DESIGN_ROUTES = UI_ROUTES - {"UI-Conformance"}
PROTOTYPE_POLICIES = {"not_applicable", "required", "waived_by_user"}
USER_SELECTABLE_PROTOTYPE_POLICIES = {"required", "waived_by_user"}
UI_AUTHORITY_KINDS = {
    "controlled_document",
    "prototype_contract",
    "design_standard",
    "production_baseline",
}
STANDARDS_CONTRACT_FIELDS = {
    "index_path",
    "root",
    "index_fingerprint",
    "required_engineering_rule_ids",
    "required_design_rule_ids",
    "leaves",
    "protected_paths",
}
STANDARD_LEAF_FIELDS = {"path", "domain", "content_fingerprint", "rule_ids"}
PROTECTED_PATH_FIELDS = {
    "path",
    "rule_id",
    "direct_edit",
    "allowed_paths",
}
CONTROLLED_DOCUMENT_ACCESS_FIELDS = {"adapter", "documents"}
CONTROLLED_DOCUMENT_FIELDS = {
    "path",
    "mode",
    "reason",
    "sections_or_queries",
    "content_fingerprint",
    "applies_to",
    "rule_ids",
}
STANDARDS_EXCEPTION_FIELDS = {
    "rule_id",
    "gate",
    "reason",
    "patch_surface",
    "rollback_plan",
    "verification_commands",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
AUTHORITY_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
EXCEPTIONAL_GATE_RE = re.compile(r"exceptional:[a-z0-9][a-z0-9._-]*\Z")
USER_CHOICE_REF_RE = re.compile(r"user:[a-z0-9][a-z0-9._:/-]*\Z")
PACK_FIELDS = {"solution_approval_sources", "schema_version", "task", "standards_contract", "approved_gates", "request_scope",
               "requirements_fingerprint", "ui_contract", "runtime_binding", "reviewed_ui_changes",
               "qa_checkpoint", "qa_checkpoint_fingerprint", "qa_document_base", "reviewed_solution_decisions",
               "reviewed_business_confirmations"}
REVIEWED_UI_FIELDS = {"id", "task_type", "role", "surface_kind", "workflow_level",
                      "qa_scope", "ui_change", "owned_paths", "gates", "audit_surfaces"}


def _require_version(payload: dict[str, Any]) -> None:
    """schema 2直接拒绝旧格式；不会把缺版本、布尔或字符串版本静默升级。"""
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 2:
        raise TaskGraphError("schema_version must be integer 2; old formats are not accepted")
    validate_task_source(payload)


def pack_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """将单包归一为仅供现有校验/更新核心使用的快照，不发布第二份图。

    调度边只存在于Full图；交接消费者不复制兄弟任务，也不能从引用重建兄弟历史。
    Light保留同一个Task.state，因此首次绑定、CAS与退役规则无需另造生命周期。
    """
    _require_version(payload)
    if set(payload) - PACK_FIELDS or not isinstance(payload.get("task"), dict):
        raise TaskGraphError("schema 2 task pack must contain one task and only current contract fields")
    if not isinstance(payload.get("standards_contract"), dict):
        raise TaskGraphError("self-contained task pack requires standards_contract")
    result = {key: copy.deepcopy(value) for key, value in payload.items() if key != "task"}
    if "request_scope" in payload:
        result["request_scope"] = request_scopes(payload)
    task = copy.deepcopy(payload["task"])
    if task.get("workflow_level") == "Light" and (task.get("depends_on") or task.get("blocks")):
        raise TaskGraphError("Light single pack must not declare graph dependencies")
    task.setdefault("depends_on", [])
    task.setdefault("blocks", [])
    task.setdefault("semantic_locks", [])
    task.setdefault("gates", [])
    if task.get("workflow_level") == "Light":
        # Light 可以直接写成独立单包；不要求用户手算待决门，也不借此授予批准。
        bind_decisions(task)
    result.update(tasks=[task], request_id=task.get("request_id"), capacity=1,
                  active_paths=[], active_semantic_locks=[])
    return result


def replace_pack_task(payload: dict[str, Any], task: dict[str, Any], *,
                      approved_gates: list[str] | None = None,
                      solution_sources: dict | None = None) -> dict[str, Any]:
    """写回同一Light单包，剔除仅为核心校验补出的空调度边。"""
    result = copy.deepcopy(payload)
    result["task"] = copy.deepcopy(task)
    if solution_sources is not None:
        if solution_sources:
            result["solution_approval_sources"] = copy.deepcopy(solution_sources)
        else:
            result.pop("solution_approval_sources", None)
    if approved_gates is not None:
        result["approved_gates"] = copy.deepcopy(approved_gates)
    if payload["task"].get("task_type") == "qa" and task.get("task_type") == "read_only":
        # 原QA包先按完整合同校验，不能先丢审查范围再把伪造元数据当作有效输入。
        # 仅records的临时就绪副本不携带QA专属字段；正式写回仍是qa，因此其范围
        # 不经过本分支，原包/导出/验收和verify-ui-scope的防伪逻辑保持完整。
        _execute("validate", payload)
        result.pop("reviewed_ui_changes", None)
        result.pop("reviewed_business_confirmations", None)
        result.pop("reviewed_solution_decisions", None)
        result.pop("qa_document_base", None)
        result.pop("qa_checkpoint", None)
        result.pop("qa_checkpoint_fingerprint", None)
    for field in ("depends_on", "blocks", "semantic_locks", "gates"):
        if field not in payload["task"] and not result["task"].get(field):
            result["task"].pop(field, None)
    return result


def reviewed_solutions(writers: list[dict], source: dict) -> list[dict]:
    """独立 QA 只接收当前检查点的决定。相同请求和正文共享一条批准，保留实际采用者。

    approval_gate 精确定位原图 approved_gates 条目。早期记录没有用户消息引用时
    不补造一条；有真实来源的新记录同时传递 source_ref，供按原材料复核。
    """
    from lib.solution_confirmation import decision_gates
    sources = source.get("solution_approval_sources", {})
    reviewed = {}
    for writer in sorted(writers, key=lambda item: item["id"]):
        gates = decision_gates(writer)
        for decision in writer.get("solution_decisions", []):
            gate = gates[decision["id"]]
            item = reviewed.setdefault(gate, dict(request_id=writer["request_id"], **decision,
                                                  approval_gate=gate, writer_ids=[]))
            item["writer_ids"].append(writer["id"])
            if gate in sources:
                item["source_ref"] = sources[gate]
    return sorted(reviewed.values(), key=lambda item: (item["request_id"], item["id"]))


def validate_reviewed_solutions(pack: dict) -> None:
    """用正常 Writer 的请求/ID/正文编码复算批准，拒绝替换来源、重复决定和越界 Writer。"""
    from lib.solution_confirmation import decision_gates
    items = pack["reviewed_solution_decisions"]
    if pack["task"]["task_type"] != "qa" or not isinstance(items, list):
        raise TaskGraphError("reviewed_solution_decisions requires a QA pack and decision array")
    seen = set()
    for item in items:
        required = {"id", "content", "approval_gate", "request_id", "writer_ids"}
        if not isinstance(item, dict) or set(item) not in (required, required | {"source_ref"}):
            raise TaskGraphError("incomplete reviewed_solution_decisions entry")
        key = {"id": item["id"], "content": item["content"]}
        gate = decision_gates({"task_type": "writer", "request_id": item["request_id"],
                               "solution_decisions": [key]})[item["id"]]
        writers = item["writer_ids"]
        identity = (item["request_id"], item["id"])
        if (identity in seen or item["approval_gate"] != gate or gate not in pack.get("approved_gates", [])
                or ("source_ref" in item) != (gate in pack.get("solution_approval_sources", {}))
                or item.get("source_ref") != pack.get("solution_approval_sources", {}).get(gate)
                or not isinstance(writers, list) or not writers
                or any(not isinstance(value, str) or not value.strip() for value in writers)
                or writers != sorted(set(writers))
                or "qa_checkpoint" in pack and not set(writers) <= set(pack["qa_checkpoint"]["writer_ids"])):
            raise TaskGraphError("QA decision does not match its approved source or reviewed Writers")
        seen.add(identity)


def export_task_pack(payload: dict[str, Any], task_id: str, *, root: Path | None = None,
                     require_current_qa: bool = False, freezing_qa_scope: bool = False) -> dict[str, Any]:
    """由当前已校验图导出唯一任务及适用依据，不携带其他任务或完整 PM 会话。"""
    pack, _ = task_pack_with_review_scope(payload, task_id, root=root, require_current_qa=require_current_qa,
                                          freezing_qa_scope=freezing_qa_scope)
    return pack


def task_pack_with_review_scope(payload: dict, task_id: str, *, root: Path | None = None,
                                require_current_qa: bool = False, freezing_qa_scope: bool = False) -> tuple[dict, str | None]:
    """从同一次权威读取返回交接包与实际审查范围，不把 Reviewer 轮次当作返工。"""
    scope_fingerprint = None
    _execute("validate", payload, root=root)
    matches = [task for task in payload["tasks"] if task["id"] == task_id]
    if len(matches) != 1:
        raise TaskGraphError(f"unknown task ID: {task_id}")
    task = matches[0]
    task_intent.check_delivery(payload, task)
    require_writer(payload, task, root)
    result = {"schema_version": 2, "task": copy.deepcopy(task_intent.handoff_task(task))}
    scopes = request_scopes(payload)
    if task["request_id"] in scopes:
        result["request_scope"] = scopes[task["request_id"]]
    if "requirements_fingerprint" in payload:
        result["requirements_fingerprint"] = payload["requirements_fingerprint"]
    # 规范仍以原图为唯一权威；导出只投影当前任务已声明的读取来源。QA审查本请求
    # 闭包的Writer，因此保留该闭包所需规则，而不把整图其他请求的规范一起交接。
    relevant = [task]
    ordinary_qa = False
    request_qa = False
    if task["task_type"] == "qa":
        from lib.foundation_qa import (checkpoint, fingerprint, is_ordinary_reviewer, request_fingerprints,
                                       request_writers, verify_frozen_scope)
        ordinary_qa = is_ordinary_reviewer(task)
        if ordinary_qa:
            relevant = request_writers(payload, task)
            result["qa_checkpoint"] = {"kind": "request", "writer_ids": [item["id"] for item in relevant]}
            # 反向依赖和运行锁只服务权威图调度；其他请求新增下游不应使同一审查失效。
            result["task"]["blocks"] = []
            result["task"]["semantic_locks"] = []
            result["task"].pop("handoff_assessment", None)
        else:
            selected = checkpoint(payload, task, root=root)
            result["qa_checkpoint"] = selected
            if selected["kind"] == "foundation":
                scope_fingerprint = fingerprint(payload, task, root=root)
                result["qa_checkpoint_fingerprint"] = scope_fingerprint
            relevant = [item for item in payload["tasks"] if item["id"] in selected["writer_ids"]]
        request_qa = result["qa_checkpoint"]["kind"] == "request"
        if request_qa and not ordinary_qa and "qa_scope_ref" not in task and task["request_id"] not in payload.get("worktree_integrations", {}):
            # 分阶段请求可没有普通 QA 的冻结差异。只在实际单仓存在提交时把该
            # Git 对象写入最终独立包，以便后来核对 Writer 范围外的 PM 文档前像。
            from lib.task_sources import project_root
            from lib.delivery.worktree_cli import git
            repo = project_root(root)
            if (repo / ".git").exists():
                revision = git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", allowed=(0, 1)).decode().strip()
                if revision:
                    result["qa_document_base"] = revision
        decisions = reviewed_solutions(relevant, payload)
        if decisions:
            result["reviewed_solution_decisions"] = decisions
        relevant = relevant or [task]
        # 受审项可能来自非 UI Writer；只传受审者的完整例外及关联门，不带完整兄弟任务。
        exceptions = reviewed_business_confirmations(relevant)
        if exceptions:
            result["reviewed_business_confirmations"] = exceptions
        # 只投影请求闭包中生产 Writer 的审查合同，不给 QA 写权限或复制其他任务。
        result["reviewed_ui_changes"] = [
            {key: copy.deepcopy(item[key]) for key in REVIEWED_UI_FIELDS if key in item}
            for item in relevant if item.get("surface_kind") == "production_ui"
        ]
    domains = {domain for item in relevant for domain in (
        ("design",) if item.get("surface_kind") == "design_ui" else
        ("engineering", "design") if item.get("surface_kind") == "production_ui" else ("engineering",))}
    sources = {document["path"] for item in relevant
               for document in item.get("controlled_document_access", {}).get("documents", [])
               if not ordinary_qa or document["mode"] != "skip"}
    sources.update(ref["path"] for item in relevant
                   for ref in item.get("ui_change", {}).get("design_authority_refs", []))
    if "standards_contract" in payload:
        contract = copy.deepcopy(payload["standards_contract"])
        contract["leaves"] = [leaf for leaf in contract["leaves"] if leaf["path"] in sources or (
            not sources and leaf["domain"] in domains and builtin_source_path(leaf["path"]) is not None)]
        # 只读任务未显式选叶时仍携带其声明领域的当前依据；不生成不存在的规则源。
        if not contract["leaves"]:
            contract["leaves"] = [copy.deepcopy(leaf) for leaf in payload["standards_contract"]["leaves"] if leaf["domain"] in domains]
        if ordinary_qa and sources:
            rules = {rule for item in [task, *relevant]
                     for document in item.get("controlled_document_access", {}).get("documents", [])
                     if document["mode"] != "skip" for rule in document["rule_ids"]}
            rules.update(policy["rule_id"] for policy in contract["protected_paths"]
                         if any(_paths_overlap(path, policy["path"]) for item in relevant for path in item["owned_paths"]))
            # 同一权威叶子可能被多个请求采用；只保留当前 Writer 所采用的规则，
            # 不让其他请求增加同一叶的选读条款改变当前包。规则文件的字节仍冻结。
            for leaf in contract["leaves"]:
                leaf["rule_ids"] = sorted(set(leaf["rule_ids"]) & rules)
        for domain in ("engineering", "design"):
            available = {rule for leaf in contract["leaves"] if leaf["domain"] == domain for rule in leaf["rule_ids"]}
            contract[f"required_{domain}_rule_ids"] = [rule for rule in contract[f"required_{domain}_rule_ids"] if domain in domains and rule in available]
        scopes = [path for item in relevant for path in item["owned_paths"]]
        contract["protected_paths"] = [policy for policy in contract["protected_paths"] if any(_paths_overlap(path, policy["path"]) for path in scopes)]
        result["standards_contract"] = contract
    if (any(item.get("surface_kind") in {"production_ui", "design_ui"} for item in relevant)
            and "ui_contract" in payload):
        result["ui_contract"] = copy.deepcopy(payload["ui_contract"])
    # Reviewer自己的gates通常为空；仍须保留本请求闭包实际采用的批准，才能审查
    # 视觉/上游例外的来源。该集合只投影已有批准，不替任何任务生成新授权。
    relevant_gates = {gate for item in [task, *relevant] for gate in item["gates"]}
    result["approved_gates"] = [gate for gate in payload.get("approved_gates", []) if gate in relevant_gates]
    approval_sources = {gate: ref for gate, ref in payload.get("solution_approval_sources", {}).items()
                        if gate in result["approved_gates"]}
    if approval_sources:
        result["solution_approval_sources"] = approval_sources
    if request_qa:
        result["approved_gates"].sort(key=lambda gate: (gate != "requirements_approved", gate))
        if "standards_contract" not in result:
            raise TaskGraphError("self-contained task pack requires standards_contract")
        if require_current_qa and not relevant_gates <= set(result["approved_gates"]):
            raise TaskGraphError("request QA requires the current Writer and Reviewer approvals")
        writers = [item for item in relevant if item["task_type"] == "writer"]
        fingerprint, scope_fingerprint = request_fingerprints(
            payload, task, writers, result, root=root, require_current=require_current_qa or freezing_qa_scope)
        result["qa_checkpoint_fingerprint"] = fingerprint
        if ((ordinary_qa or "qa_scope_ref" in task) and task["request_id"] not in payload.get("worktree_integrations", {})
                and (require_current_qa or freezing_qa_scope)):
            verify_frozen_scope(task, writers, scope_fingerprint, freezing=freezing_qa_scope)
        if freezing_qa_scope:
            result["task"]["qa_scope_fingerprint"] = scope_fingerprint
    _execute("validate", result, root=root)
    return result, scope_fingerprint


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and evaluate a PM task graph JSON snapshot.")
    parser.add_argument(
        "command",
        choices=("validate", "ready", "qa-ready", "capacity", "init", "update", "task", "fingerprints", "scratch", "cleanup-scratch", "continuation", "verify-ui-scope", "verify-solution-scope"),
    )
    parser.add_argument("--input", type=Path, help="JSON graph or explicit init decisions; omit to read UTF-8 JSON from stdin")
    parser.add_argument("--source", type=Path, help="authoritative Full graph or Light writer pack for UI QA scope verification")
    parser.add_argument("--patch", help="update patch JSON file, or - for stdin")
    parser.add_argument("--expect-sha256", help="old output fingerprint for writes, or prior metadata snapshot for scratch deletion")
    parser.add_argument("--task-id", help="existing task to export")
    parser.add_argument("--host", choices=HOSTS, help="current native host, only for continuation")
    parser.add_argument("--observed-state", choices=OBSERVED_STATES, help="PM's current native observation, only for continuation")
    parser.add_argument("--claude-event", type=Path, help="当前终止通知对应的同 ID 单条原生 JSON 事件，仅限 continuation")
    parser.add_argument("--output", type=Path, help="explicit new graph or task-pack output; never created by default")
    parser.add_argument("--root", type=Path, help="explicit root for initialization, selected file fingerprints or scratch workspace")
    parser.add_argument("--select", action="append", default=[], help="select an existing receipt fingerprint-map field")
    parser.add_argument("--pm-id", help="仅独立原型 task 导出：已登记原件的实际 PM 身份")
    parser.add_argument("--check-command", help="仅 fingerprints 使用：核对当前单包中这条命令声明的文件输入")
    parser.add_argument("--request-id", help="request identifier for deterministic scratch workspace allocation/cleanup")
    parser.add_argument("--all", action="store_true", help="clean all managed scratch workspaces for the project root")
    parser.add_argument("--dry-run", action="store_true", help="preview scratch cleanup without creating, changing or removing files")
    parser.add_argument("--keep", action="append", default=[], help="retain an exact existing scratch-relative regular file; repeat as needed")
    return parser


def read_claude_event(path: Path | None) -> dict[str, Any] | None:
    """双入口复用有界、安全的记录读取；只接收调用方明确指定的一条事件，不发现或遍历会话。"""
    if path is None:
        return None
    if __package__:
        from .task_graph_records import decode, read_record
    else:
        from task_graph_records import decode, read_record
    event = decode(read_record(path))
    if not isinstance(event, dict):
        raise TaskGraphError("--claude-event requires a single native event object")
    return event


def _read_payload(path: Path | None) -> dict[str, Any]:
    if __package__:
        from .task_graph_records import decode
    else:
        from task_graph_records import decode
    try:
        # 查询仍从原有文件或标准输入读取文本，与导出/更新共用解析规则，
        # 防止同一份带重复字段的记录通过查询后却无法导出。
        raw = path.read_text(encoding="utf-8") if path is not None else sys.stdin.read()
        value = decode(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TaskGraphError(f"cannot read task graph JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise TaskGraphError("task graph input must be a JSON object")
    return value


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TaskGraphError(f"{label} must be an array of strings")
    return tuple(value)


def _safe_relative_path(value: Any, label: str) -> str:
    """返回规范化项目相对路径，并拒绝绝对路径、反斜杠和目录穿越。"""

    if not isinstance(value, str) or not value.strip():
        raise TaskGraphError(f"{label} must be a non-empty project-relative path")
    if "\\" in value:
        raise TaskGraphError(f"{label} must use forward slashes")
    normalized = value.rstrip("/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not normalized or any(part in {"", ".", ".."} for part in path.parts):
        raise TaskGraphError(f"{label} must be a normalized project-relative path")
    if normalized != path.as_posix():
        raise TaskGraphError(f"{label} must be a normalized project-relative path")
    return path.as_posix()


def _paths_overlap(left: str, right: str) -> bool:
    """按路径段判断相等或祖先/后代关系，避免字符串前缀误判。"""

    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def _is_within(path: str, boundary: str) -> bool:
    """判断路径是否等于边界或位于边界之下；该检查有方向，不能用对称交叠替代。"""

    path_parts = PurePosixPath(path).parts
    boundary_parts = PurePosixPath(boundary).parts
    return len(path_parts) >= len(boundary_parts) and (
        path_parts[: len(boundary_parts)] == boundary_parts
    )


def _nonempty_string(value: Any, label: str) -> str:
    """读取去除首尾空白的必填字符串，避免空理由伪装成有效合同。"""

    if not isinstance(value, str) or not value.strip():
        raise TaskGraphError(f"{label} must be a non-empty string")
    return value.strip()


def _stable_id_list(value: Any, label: str) -> tuple[str, ...]:
    """验证稳定规则编号；规则编号用于跨计划、实现和 QA 结果做确定性关联。"""

    values = _string_list(value, label)
    if any(not AUTHORITY_ID_RE.fullmatch(item) for item in values):
        raise TaskGraphError(f"{label} contains an invalid stable rule ID")
    if len(set(values)) != len(values):
        raise TaskGraphError(f"{label} must not contain duplicates")
    return values


def _resolved_standards_contract(payload: dict[str, Any]) -> dict[str, Any] | None:
    """读取 PM 从统一规范目录冻结的机器合同。

    索引与目录边界由 ``project.yaml`` 解析，规则正文仍通过任务自己的
    ``controlled_document_access`` 按需携带，避免把整棵规范树塞入上下文。
    """

    if "engineering_contract" in payload:
        raise TaskGraphError(
            "engineering_contract is unsupported after the direct STANDARDS upgrade"
        )
    value = payload.get("standards_contract")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TaskGraphError("standards_contract must be an object")
    missing = STANDARDS_CONTRACT_FIELDS - set(value)
    unknown = set(value) - STANDARDS_CONTRACT_FIELDS
    if missing:
        raise TaskGraphError(
            "standards_contract is missing field(s): " + ", ".join(sorted(missing))
        )
    if unknown:
        raise TaskGraphError(
            "standards_contract has unsupported field(s): "
            + ", ".join(sorted(unknown))
        )

    index_path = _safe_relative_path(
        value["index_path"], "standards_contract.index_path"
    )
    root = _safe_relative_path(value["root"], "standards_contract.root")
    if _is_within(index_path, root):
        raise TaskGraphError(
            "standards_contract.index_path must stay outside standards_contract.root"
        )
    fingerprint = value["index_fingerprint"]
    if fingerprint is not None and (not isinstance(fingerprint, str) or not SHA256_RE.fullmatch(fingerprint)):
        raise TaskGraphError(
            "standards_contract.index_fingerprint must be lowercase SHA-256"
        )
    required_engineering_rule_ids = _stable_id_list(
        value["required_engineering_rule_ids"],
        "standards_contract.required_engineering_rule_ids",
    )
    required_design_rule_ids = _stable_id_list(
        value["required_design_rule_ids"],
        "standards_contract.required_design_rule_ids",
    )
    raw_leaves = value["leaves"]
    if not isinstance(raw_leaves, list) or not raw_leaves:
        raise TaskGraphError("standards_contract.leaves must be a non-empty array")
    leaves: dict[str, dict[str, Any]] = {}
    domain_contract_rule_ids: dict[str, set[str]] = {
        "engineering": set(),
        "design": set(),
    }
    builtin_catalog = None
    source_identities: set[str] = set()
    for position, raw_leaf in enumerate(raw_leaves):
        label = f"standards_contract.leaves[{position}]"
        if not isinstance(raw_leaf, dict):
            raise TaskGraphError(f"{label} must be an object")
        missing_leaf = STANDARD_LEAF_FIELDS - set(raw_leaf)
        unknown_leaf = set(raw_leaf) - STANDARD_LEAF_FIELDS
        if missing_leaf:
            raise TaskGraphError(
                f"{label} is missing field(s): {', '.join(sorted(missing_leaf))}"
            )
        if unknown_leaf:
            raise TaskGraphError(
                f"{label} has unsupported field(s): {', '.join(sorted(unknown_leaf))}"
            )
        leaf_path = _safe_relative_path(raw_leaf["path"], f"{label}.path")
        identity = builtin_source_path(leaf_path) or leaf_path
        if identity.casefold() in source_identities:
            raise TaskGraphError("standards_contract.leaves must not duplicate paths")
        source_identities.add(identity.casefold())
        domain = raw_leaf["domain"]
        if domain not in {"engineering", "design"}:
            raise TaskGraphError(f"{label}.domain must be engineering or design")
        if not canonical_standard_source_path(leaf_path, root) or source_domain(leaf_path, root) != domain:
            raise TaskGraphError(f"{label}.path must be an exact builtin source or direct {domain} Markdown leaf inside {root}")
        leaf_fingerprint = raw_leaf["content_fingerprint"]
        if not isinstance(leaf_fingerprint, str) or not SHA256_RE.fullmatch(
            leaf_fingerprint
        ):
            raise TaskGraphError(f"{label}.content_fingerprint must be lowercase SHA-256")
        leaf_rule_ids = _stable_id_list(raw_leaf["rule_ids"], f"{label}.rule_ids")
        if not leaf_rule_ids:
            raise TaskGraphError(f"{label}.rule_ids must not be empty")
        builtin = builtin_source_path(leaf_path)
        if builtin is not None:
            # 固定内置来源可以由当前运行时直接核对；任意伪ID/陈旧SHA不能冒充平台底线。
            try:
                if builtin_catalog is None:
                    builtin_catalog = builtin_standard_rule_catalog(
                        Path(__file__).resolve().parents[1])
            except (OSError, UnicodeError, ValueError) as exc:
                raise TaskGraphError(f"invalid builtin standards sources: {exc}") from exc
            current = builtin_catalog[builtin]
            if leaf_fingerprint != current["content_fingerprint"]:
                raise TaskGraphError(f"{label} builtin standards fingerprint is stale")
            if set(leaf_rule_ids) - set(current["rules"]):
                raise TaskGraphError(f"{label} builtin standards source claims unknown rule(s)")
        duplicate_rule_ids = domain_contract_rule_ids[domain].intersection(leaf_rule_ids)
        if duplicate_rule_ids:
            raise TaskGraphError(
                f"standards_contract {domain} rule IDs must have one leaf owner: "
                + ", ".join(sorted(duplicate_rule_ids))
            )
        domain_contract_rule_ids[domain].update(leaf_rule_ids)
        leaves[leaf_path] = {
            "path": leaf_path,
            "domain": domain,
            "content_fingerprint": leaf_fingerprint,
            "rule_ids": leaf_rule_ids,
        }
    if fingerprint is None and any(builtin_source_path(path) is None for path in leaves):
        raise TaskGraphError("null index_fingerprint requires no project standards leaves")
    for domain, required_ids in (
        ("engineering", required_engineering_rule_ids),
        ("design", required_design_rule_ids),
    ):
        missing_from_leaves = sorted(
            set(required_ids) - domain_contract_rule_ids[domain]
        )
        if missing_from_leaves:
            raise TaskGraphError(
                f"standards_contract {domain} leaves are missing required rule(s): "
                + ", ".join(missing_from_leaves)
            )
    raw_protected = value["protected_paths"]
    if not isinstance(raw_protected, list):
        raise TaskGraphError("standards_contract.protected_paths must be an array")

    protected_paths: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for position, raw_policy in enumerate(raw_protected):
        label = f"standards_contract.protected_paths[{position}]"
        if not isinstance(raw_policy, dict):
            raise TaskGraphError(f"{label} must be an object")
        missing_policy = PROTECTED_PATH_FIELDS - set(raw_policy)
        unknown_policy = set(raw_policy) - PROTECTED_PATH_FIELDS
        if missing_policy:
            raise TaskGraphError(
                f"{label} is missing field(s): {', '.join(sorted(missing_policy))}"
            )
        if unknown_policy:
            raise TaskGraphError(
                f"{label} has unsupported field(s): {', '.join(sorted(unknown_policy))}"
            )
        protected_path = _safe_relative_path(raw_policy["path"], f"{label}.path")
        if protected_path in seen_paths:
            raise TaskGraphError("standards_contract.protected_paths must not duplicate paths")
        seen_paths.add(protected_path)
        rule_id = _nonempty_string(raw_policy["rule_id"], f"{label}.rule_id")
        if not AUTHORITY_ID_RE.fullmatch(rule_id):
            raise TaskGraphError(f"{label}.rule_id has an invalid stable identifier")
        if raw_policy["direct_edit"] != "forbidden_without_exception":
            raise TaskGraphError(
                f"{label}.direct_edit must be 'forbidden_without_exception'"
            )
        allowed_paths = tuple(
            _safe_relative_path(item, f"{label}.allowed_paths[{item_position}]")
            for item_position, item in enumerate(
                _string_list(raw_policy["allowed_paths"], f"{label}.allowed_paths")
            )
        )
        if len(set(allowed_paths)) != len(allowed_paths):
            raise TaskGraphError(f"{label}.allowed_paths must not contain duplicates")
        if any(not _is_within(item, protected_path) for item in allowed_paths):
            raise TaskGraphError(f"{label}.allowed_paths must stay inside its protected path")
        protected_paths.append(
            {
                "path": protected_path,
                "rule_id": rule_id,
                "direct_edit": "forbidden_without_exception",
                "allowed_paths": allowed_paths,
            }
        )

    return {
        "index_path": index_path,
        "root": root,
        "index_fingerprint": fingerprint,
        "required_engineering_rule_ids": required_engineering_rule_ids,
        "required_design_rule_ids": required_design_rule_ids,
        "leaves": leaves,
        "protected_paths": tuple(protected_paths),
    }


def _validated_standards_exceptions(
    raw: dict[str, Any], index: int, owned_paths: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """验证受保护上游修改的显式例外，防止用一句自由文本绕过硬规则。"""

    value = raw.get("standards_exceptions", [])
    if not isinstance(value, list):
        raise TaskGraphError(f"tasks[{index}].standards_exceptions must be an array")
    result: dict[str, dict[str, Any]] = {}
    gates = set(_string_list(raw["gates"], f"tasks[{index}].gates"))
    for position, raw_exception in enumerate(value):
        label = f"tasks[{index}].standards_exceptions[{position}]"
        if not isinstance(raw_exception, dict):
            raise TaskGraphError(f"{label} must be an object")
        missing = STANDARDS_EXCEPTION_FIELDS - set(raw_exception)
        unknown = set(raw_exception) - STANDARDS_EXCEPTION_FIELDS
        if missing:
            raise TaskGraphError(f"{label} is missing field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise TaskGraphError(
                f"{label} has unsupported field(s): {', '.join(sorted(unknown))}"
            )
        rule_id = _nonempty_string(raw_exception["rule_id"], f"{label}.rule_id")
        if not AUTHORITY_ID_RE.fullmatch(rule_id):
            raise TaskGraphError(f"{label}.rule_id has an invalid stable identifier")
        if rule_id in result:
            raise TaskGraphError(
                f"tasks[{index}].standards_exceptions must not duplicate rule_id {rule_id!r}"
            )
        gate = _nonempty_string(raw_exception["gate"], f"{label}.gate")
        if not EXCEPTIONAL_GATE_RE.fullmatch(gate):
            raise TaskGraphError(f"{label}.gate must be an exceptional:<id> gate")
        if gate not in gates:
            raise TaskGraphError(
                f"tasks[{index}] standards exception {rule_id!r} must declare its exceptional gate"
            )
        reason = _nonempty_string(raw_exception["reason"], f"{label}.reason")
        rollback_plan = _nonempty_string(
            raw_exception["rollback_plan"], f"{label}.rollback_plan"
        )
        patch_surface = tuple(
            _safe_relative_path(item, f"{label}.patch_surface[{item_position}]")
            for item_position, item in enumerate(
                _string_list(raw_exception["patch_surface"], f"{label}.patch_surface")
            )
        )
        if not patch_surface:
            raise TaskGraphError(f"{label}.patch_surface must not be empty")
        if len(set(patch_surface)) != len(patch_surface):
            raise TaskGraphError(f"{label}.patch_surface must not contain duplicates")
        # 例外记录描述的是本任务实际补丁面，而不是可任意扩张的上游授权。
        # 因此使用有方向的包含关系，不能用“相交”接受 owned_paths 外的父目录。
        if any(
            not any(_is_within(item, owned_path) for owned_path in owned_paths)
            for item in patch_surface
        ):
            raise TaskGraphError(f"{label}.patch_surface must stay within task owned_paths")
        verification_commands = _string_list(
            raw_exception["verification_commands"], f"{label}.verification_commands"
        )
        if not verification_commands or any(not command.strip() for command in verification_commands):
            raise TaskGraphError(f"{label}.verification_commands must contain real commands")
        result[rule_id] = {
            "gate": gate,
            "reason": reason,
            "rollback_plan": rollback_plan,
            "patch_surface": patch_surface,
            "verification_commands": verification_commands,
        }
    return result


def _validate_standards_access(
    raw: dict[str, Any],
    index: int,
    standards_contract: dict[str, Any] | None,
) -> None:
    """验证 Writer 对统一规范索引和最小相关叶文档的按需读取合同。

    后端等非 UI Writer 只要求工程规则；生产 UI 同时要求工程与设计规则；
    原型设计 Writer 只要求设计规则。每个必需领域都必须独立覆盖全部写路径，
    防止用一份宽泛索引或另一领域的规则伪装成完整规范覆盖。
    """

    if raw.get("task_type") != "writer":
        return
    if standards_contract is None:
        raise TaskGraphError(f"tasks[{index}] writer requires standards_contract")
    if "controlled_document_access" not in raw:
        raise TaskGraphError(
            f"tasks[{index}] writer requires controlled_document_access"
        )
    audit_surfaces = set(
        _string_list(raw.get("audit_surfaces"), f"tasks[{index}].audit_surfaces")
    )
    if "standards-conformance" not in audit_surfaces:
        raise TaskGraphError(
            f"tasks[{index}] writer requires standards-conformance audit surface"
        )

    value = raw["controlled_document_access"]
    if not isinstance(value, dict):
        raise TaskGraphError(f"tasks[{index}].controlled_document_access must be an object")
    missing = CONTROLLED_DOCUMENT_ACCESS_FIELDS - set(value)
    unknown = set(value) - CONTROLLED_DOCUMENT_ACCESS_FIELDS
    if missing:
        raise TaskGraphError(
            f"tasks[{index}].controlled_document_access is missing field(s): "
            f"{', '.join(sorted(missing))}"
        )
    if unknown:
        raise TaskGraphError(
            f"tasks[{index}].controlled_document_access has unsupported field(s): "
            f"{', '.join(sorted(unknown))}"
        )
    # 两种 3.x 适配器均归项目所有；具体文件的读取与插件来源认证各自独立。
    if value["adapter"] not in ("project.yaml", ".awf/project.yaml"):
        raise TaskGraphError(f"tasks[{index}].controlled_document_access.adapter must be project.yaml or .awf/project.yaml")
    documents = value["documents"]
    if not isinstance(documents, list):
        raise TaskGraphError(
            f"tasks[{index}].controlled_document_access.documents must be an array"
        )

    normalized_documents: list[dict[str, Any]] = []
    seen_document_paths: set[str] = set()
    for position, document in enumerate(documents):
        label = f"tasks[{index}].controlled_document_access.documents[{position}]"
        if not isinstance(document, dict):
            raise TaskGraphError(f"{label} must be an object")
        missing_document = CONTROLLED_DOCUMENT_FIELDS - set(document)
        unknown_document = set(document) - CONTROLLED_DOCUMENT_FIELDS
        if missing_document:
            raise TaskGraphError(
                f"{label} is missing field(s): {', '.join(sorted(missing_document))}"
            )
        if unknown_document:
            raise TaskGraphError(
                f"{label} has unsupported field(s): {', '.join(sorted(unknown_document))}"
            )
        path = _safe_relative_path(document["path"], f"{label}.path")
        if path in seen_document_paths:
            raise TaskGraphError(
                f"tasks[{index}].controlled_document_access.documents must not duplicate paths"
            )
        seen_document_paths.add(path)
        mode = document["mode"]
        if mode not in {"targeted", "full", "skip"}:
            raise TaskGraphError(f"{label}.mode must be targeted, full, or skip")
        reason = _nonempty_string(document["reason"], f"{label}.reason")
        sections = _string_list(document["sections_or_queries"], f"{label}.sections_or_queries")
        if any(not item.strip() for item in sections) or len(set(sections)) != len(sections):
            raise TaskGraphError(
                f"{label}.sections_or_queries must contain unique non-empty values"
            )
        if mode == "targeted" and not sections:
            raise TaskGraphError(f"{label} targeted access requires sections_or_queries")
        fingerprint = document["content_fingerprint"]
        if not isinstance(fingerprint, str) or not SHA256_RE.fullmatch(fingerprint):
            raise TaskGraphError(f"{label}.content_fingerprint must be lowercase SHA-256")
        applies_to = tuple(
            _safe_relative_path(item, f"{label}.applies_to[{item_position}]")
            for item_position, item in enumerate(
                _string_list(document["applies_to"], f"{label}.applies_to")
            )
        )
        if len(set(applies_to)) != len(applies_to):
            raise TaskGraphError(f"{label}.applies_to must not contain duplicates")
        rule_ids = _stable_id_list(document["rule_ids"], f"{label}.rule_ids")
        if rule_ids and path not in standards_contract["leaves"]:
            raise TaskGraphError(f"{label} standards rule source is absent from contract: {path!r}")
        # 每条规范读取都必须验证，不能因领域不在 required_domains 中便静默过滤。
        # 原型是单独的证据分支；其余旧目录/未知叶子不允许假装普通文档加入读集合。
        standards_root = standards_contract["root"]
        if builtin_source_path(path) is not None or _is_within(path.casefold(), standards_root.casefold()):
            prototype_root = f"{standards_root}/prototype"
            if not _is_within(path, prototype_root):
                leaf = standards_contract["leaves"].get(path)
                if not canonical_standard_source_path(path, standards_root) or leaf is None:
                    raise TaskGraphError(f"{label} standards leaf is absent from contract or not canonical: {path!r}")
                if fingerprint != leaf["content_fingerprint"]:
                    raise TaskGraphError(f"tasks[{index}] {leaf['domain']} standards leaf fingerprint is stale: {path!r}")
                if set(rule_ids) - set(leaf["rule_ids"]):
                    raise TaskGraphError(f"{label} standards leaf claims unknown rule(s)")
            elif rule_ids:
                raise TaskGraphError(f"{label} prototype evidence must not claim standards rule IDs")
        normalized_documents.append(
            {
                "path": path,
                "mode": mode,
                "reason": reason,
                "sections_or_queries": sections,
                "content_fingerprint": fingerprint,
                "applies_to": applies_to,
                "rule_ids": rule_ids,
            }
        )

    index_documents = [
        document
        for document in normalized_documents
        if document["path"] == standards_contract["index_path"]
    ]
    index_required = standards_contract["index_fingerprint"] is not None
    if len(index_documents) != int(index_required):
        raise TaskGraphError(
            f"tasks[{index}] must include configured STANDARDS index exactly once when present, and omit it when absent"
        )
    index_document = index_documents[0] if index_required else None
    if index_document is not None and index_document["mode"] == "skip":
        raise TaskGraphError(f"tasks[{index}] must not skip the STANDARDS index")
    if index_document is not None and index_document["content_fingerprint"] != standards_contract["index_fingerprint"]:
        raise TaskGraphError(f"tasks[{index}] STANDARDS index fingerprint does not match contract")
    if index_document is not None and index_document["rule_ids"]:
        raise TaskGraphError(f"tasks[{index}] STANDARDS index must not claim leaf rule IDs")

    owned_paths = tuple(
        _safe_relative_path(item, f"tasks[{index}].owned_paths[{position}]")
        for position, item in enumerate(
            _string_list(raw["owned_paths"], f"tasks[{index}].owned_paths")
        )
    )
    for owned_path in owned_paths:
        if index_document is not None and not any(
            _is_within(owned_path, access_path)
            for access_path in index_document["applies_to"]
        ):
            raise TaskGraphError(
                f"tasks[{index}] STANDARDS index does not cover owned path {owned_path!r}"
            )

    surface_kind = raw.get("surface_kind")
    required_domains = (
        ("design",)
        if surface_kind == "design_ui"
        else ("engineering", "design")
        if surface_kind == "production_ui"
        else ("engineering",)
    )
    domain_rule_ids: dict[str, set[str]] = {}
    for domain in required_domains:
        domain_documents = [
            document
            for document in normalized_documents
            if source_domain(document["path"], standards_contract["root"]) == domain
        ]
        if not domain_documents:
            raise TaskGraphError(
                f"tasks[{index}] requires at least one selected {domain} standards leaf"
            )
        if any(not document["path"].endswith(".md") for document in domain_documents):
            raise TaskGraphError(
                f"tasks[{index}] selected {domain} standards leaves must be Markdown files"
            )
        for document in domain_documents:
            leaf_contract = standards_contract["leaves"].get(document["path"])
            if leaf_contract is None or leaf_contract["domain"] != domain:
                raise TaskGraphError(
                    f"tasks[{index}] selected {domain} standards leaf is absent from contract: "
                    f"{document['path']!r}"
                )
            if document["content_fingerprint"] != leaf_contract["content_fingerprint"]:
                raise TaskGraphError(
                    f"tasks[{index}] {domain} standards leaf fingerprint is stale: "
                    f"{document['path']!r}"
                )
            unknown_leaf_rules = sorted(
                set(document["rule_ids"]) - set(leaf_contract["rule_ids"])
            )
            if unknown_leaf_rules:
                raise TaskGraphError(
                    f"tasks[{index}] {domain} standards leaf claims unknown rule(s): "
                    + ", ".join(unknown_leaf_rules)
                )
        if any(document["mode"] == "skip" for document in domain_documents):
            raise TaskGraphError(
                f"tasks[{index}] must not skip a selected {domain} standards leaf"
            )
        for owned_path in owned_paths:
            if not any(
                _is_within(owned_path, access_path)
                for document in domain_documents
                for access_path in document["applies_to"]
            ):
                raise TaskGraphError(
                    f"tasks[{index}] {domain} standards do not cover owned path {owned_path!r}"
                )
        selected_rule_ids = {
            rule_id for document in domain_documents for rule_id in document["rule_ids"]
        }
        required_rule_ids = set(
            standards_contract[f"required_{domain}_rule_ids"]
        )
        if not required_rule_ids:
            raise TaskGraphError(
                f"tasks[{index}] requires non-empty applicable {domain} rule IDs"
            )
        missing_rules = sorted(required_rule_ids - selected_rule_ids)
        if missing_rules:
            raise TaskGraphError(
                f"tasks[{index}] {domain} standards are missing required rule(s): "
                f"{', '.join(missing_rules)}"
            )
        domain_rule_ids[domain] = selected_rule_ids

    # schema 2没有GENERAL替代内置来源的旧窗口。项目叶只补业务特有规则，每个适用领域
    # 都必须显式读取实际内置底线；索引/项目规则覆盖不能冒充内置来源覆盖。
    for domain in required_domains:
        baselines = [document for document in normalized_documents
                     if builtin_source_path(document["path"]) is not None
                     and source_domain(document["path"], standards_contract["root"]) == domain
                     and document["mode"] != "skip"]
        if not baselines:
            raise TaskGraphError(f"tasks[{index}] requires selected builtin {domain} baseline in standards_contract")
        for owned_path in owned_paths:
            if not any(
                _is_within(owned_path, access_path)
                for document in baselines for access_path in document["applies_to"]
            ):
                raise TaskGraphError(
                    f"tasks[{index}] builtin {domain} baseline does not cover owned path {owned_path!r}"
                )

    exceptions = _validated_standards_exceptions(raw, index, owned_paths)
    touched_protected_rules: set[str] = set()
    engineering_rule_ids = domain_rule_ids.get("engineering", set())
    for policy in standards_contract["protected_paths"]:
        touched_paths: list[str] = []
        for owned_path in owned_paths:
            if not _paths_overlap(owned_path, policy["path"]):
                continue
            # 父目录所有权同样包含其下的受保护源码。取两条路径交集的较窄边界，
            # 既阻止用 vendor 绕过 vendor/core，也不要求例外覆盖无关兄弟目录。
            touched_path = (
                owned_path
                if _is_within(owned_path, policy["path"])
                else policy["path"]
            )
            # 只有整个交集都在明确允许的子树中才免例外。若任务拥有更宽目录，
            # 不能因为其中有一个 allowed_paths 子目录便把其余保护区域一并放行。
            if any(_is_within(touched_path, allowed) for allowed in policy["allowed_paths"]):
                continue
            touched_paths.append(touched_path)
        if not touched_paths:
            continue
        rule_id = policy["rule_id"]
        touched_protected_rules.add(rule_id)
        if rule_id not in engineering_rule_ids:
            raise TaskGraphError(
                f"tasks[{index}] protected path requires engineering rule {rule_id!r}"
            )
        exception = exceptions.get(rule_id)
        if exception is None:
            raise TaskGraphError(
                f"tasks[{index}] writes protected path {policy['path']!r} "
                f"without an approved standards exception for {rule_id!r}"
            )
        for touched_path in touched_paths:
            if not any(
                _is_within(touched_path, patch_path)
                for patch_path in exception["patch_surface"]
            ):
                raise TaskGraphError(
                    f"tasks[{index}] standards exception {rule_id!r} does not cover "
                    f"protected path {touched_path!r}"
                )
    unused_exceptions = sorted(set(exceptions) - touched_protected_rules)
    if unused_exceptions:
        raise TaskGraphError(
            f"tasks[{index}] declares unused standards exception(s): "
            f"{', '.join(unused_exceptions)}"
        )


def _resolved_ui_contract(payload: dict[str, Any], required: bool) -> tuple[str, ...]:
    """读取 PM 从 project.yaml 解析并冻结到快照中的原型路径边界。"""

    value = payload.get("ui_contract")
    if value is None:
        if required:
            raise TaskGraphError(
                "production_ui or design_ui tasks require ui_contract prototype_paths"
            )
        return ()
    if not isinstance(value, dict):
        raise TaskGraphError("ui_contract must be an object")
    missing = UI_CONTRACT_FIELDS - set(value)
    unknown = set(value) - UI_CONTRACT_FIELDS
    if missing:
        raise TaskGraphError(f"ui_contract is missing field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise TaskGraphError(
            f"ui_contract has unsupported field(s): {', '.join(sorted(unknown))}"
        )
    raw_paths = _string_list(value["prototype_paths"], "ui_contract.prototype_paths")
    if not raw_paths:
        raise TaskGraphError("ui_contract.prototype_paths must not be empty")
    paths = tuple(
        _safe_relative_path(path, f"ui_contract.prototype_paths[{position}]")
        for position, path in enumerate(raw_paths)
    )
    if len(set(paths)) != len(paths):
        raise TaskGraphError("ui_contract.prototype_paths must not contain duplicates")
    return paths


def _validate_authority_refs(value: Any, label: str) -> tuple[dict[str, str], ...]:
    """验证已解析且冻结的设计依据，防止自由文本引用伪装成机器证据。"""

    if not isinstance(value, list):
        raise TaskGraphError(f"{label} must be an array of resolved authority objects")
    refs: list[dict[str, str]] = []
    identities: set[tuple[str, str, str]] = set()
    for position, raw_ref in enumerate(value):
        ref_label = f"{label}[{position}]"
        if not isinstance(raw_ref, dict):
            raise TaskGraphError(f"{ref_label} must be an object")
        missing = UI_AUTHORITY_REF_FIELDS - set(raw_ref)
        unknown = set(raw_ref) - UI_AUTHORITY_REF_FIELDS
        if missing:
            raise TaskGraphError(
                f"{ref_label} is missing field(s): {', '.join(sorted(missing))}"
            )
        if unknown:
            raise TaskGraphError(
                f"{ref_label} has unsupported field(s): {', '.join(sorted(unknown))}"
            )
        if not all(isinstance(raw_ref[field], str) for field in UI_AUTHORITY_REF_FIELDS):
            raise TaskGraphError(f"{ref_label} fields must all be strings")

        kind = raw_ref["kind"]
        authority_id = raw_ref["authority_id"]
        anchor = raw_ref["anchor"]
        fingerprint = raw_ref["content_fingerprint"]
        if kind not in UI_AUTHORITY_KINDS:
            raise TaskGraphError(f"{ref_label}.kind is unsupported: {kind!r}")
        if not AUTHORITY_ID_RE.fullmatch(authority_id):
            raise TaskGraphError(f"{ref_label}.authority_id has an invalid stable identifier")
        path = _safe_relative_path(raw_ref["path"], f"{ref_label}.path")
        if not anchor.strip():
            raise TaskGraphError(f"{ref_label}.anchor must be non-empty")
        if not SHA256_RE.fullmatch(fingerprint):
            raise TaskGraphError(f"{ref_label}.content_fingerprint must be lowercase SHA-256")
        if raw_ref["resolution_state"] != "resolved":
            raise TaskGraphError(f"{ref_label}.resolution_state must be 'resolved'")

        identity = (authority_id, path, anchor)
        if identity in identities:
            raise TaskGraphError(f"{label} must not contain duplicate authorities")
        identities.add(identity)
        refs.append(
            {
                "kind": kind,
                "authority_id": authority_id,
                "path": path,
                "anchor": anchor,
                "content_fingerprint": fingerprint,
                "resolution_state": "resolved",
            }
        )
    return tuple(refs)


def _validate_authority_path_bindings(
    authority_refs: tuple[dict[str, str], ...],
    prototype_paths: tuple[str, ...],
    design_standards_root: str | None,
    design_standard_fingerprints: dict[str, str],
    label: str,
) -> None:
    """把结构化 authority 的类型绑定到适配器冻结路径，阻止只改 kind 标签的伪证据。"""

    for position, ref in enumerate(authority_refs):
        ref_label = f"{label}[{position}]"
        kind = ref["kind"]
        path = ref["path"]
        inside_prototype = any(
            _is_within(path, prototype_path) for prototype_path in prototype_paths
        )
        inside_design_standards = (
            design_standards_root is not None
            and standard_domain(path, design_standards_root) == "design"
        )
        configured_design_standard = path in design_standard_fingerprints

        if (
            design_standards_root is not None
            and _is_within(path, design_standards_root)
            and not inside_prototype
            and standard_domain(path, design_standards_root) is None
        ):
            raise TaskGraphError(f"{ref_label} standards authority must be a shallow Markdown leaf")

        if kind == "prototype_contract" and not inside_prototype:
            raise TaskGraphError(
                f"{ref_label} prototype_contract path must be inside ui_contract.prototype_paths"
            )
        if kind == "design_standard" and not configured_design_standard:
            raise TaskGraphError(
                f"{ref_label} design_standard path must match a frozen design leaf "
                "in standards_contract.leaves"
            )
        # 规范依据与读取合同必须指向同一个已采用版本，不能只刷新读集合后
        # 仍把旧 authority 标记为 resolved。原型使用依赖指纹，不做逐文档比较。
        if kind == "design_standard" and (
            ref["content_fingerprint"] != design_standard_fingerprints[path]
        ):
            raise TaskGraphError(
                f"{ref_label} design_standard fingerprint must match the current "
                "standards_contract leaf"
            )
        if inside_prototype and kind != "prototype_contract":
            raise TaskGraphError(
                f"{ref_label} path inside ui_contract.prototype_paths must use "
                "kind prototype_contract"
            )
        if inside_design_standards and kind != "design_standard":
            raise TaskGraphError(
                f"{ref_label} design leaf inside standards_contract.root must use "
                "kind design_standard"
            )


def _overlaps_design_path(
    owned_path: str, prototype_paths: tuple[str, ...], standards_root: str | None
) -> bool:
    """浅层化后仍拒绝生产 Writer 占有设计叶、原型或它们的祖先目录。

    设计文件前缀形成可在文件尚未生成时检查的边界；无需赋予 UI Agent 整个
    standards/ 的写权限，也不能借由修改 domain 标签获得工程规范的修改权。
    """

    return any(_paths_overlap(owned_path.casefold(), path.casefold()) for path in prototype_paths) or (
        standards_root is not None
        and (
            _is_within(standards_root.casefold(), owned_path.casefold())
            or standard_domain(owned_path, standards_root) == "design"
        )
    )


def _validate_plan_contract(
    raw: dict[str, Any],
    index: int,
    prototype_paths: tuple[str, ...],
    design_standards_root: str | None,
    request_scope: str | None,
) -> None:
    """校验带角色任务的计划外壳，并显式标记生产 UI，避免漏掉 ui_change。"""

    # 设计路径的写入资格是全图不变量，不能依赖任务自报的 role/surface_kind 才触发。
    # 因此先检查每个 Writer；这样非设计角色、无角色任务和过宽父目录都无法改写
    # 一致性路由引用的冻结原型后，再让生产任务跳过视觉批准。
    if raw.get("task_type") == "writer" and (prototype_paths or design_standards_root):
        owned_paths = tuple(
            _safe_relative_path(path, f"tasks[{index}].owned_paths[{position}]")
            for position, path in enumerate(
                _string_list(raw["owned_paths"], f"tasks[{index}].owned_paths")
            )
        )
        overlaps_design_boundary = any(
            _overlaps_design_path(owned_path, prototype_paths, design_standards_root)
            for owned_path in owned_paths
        )
        # 规范正文直接存放于根目录；旧层级或任意嵌套文件不能恢复平行权威。
        for owned_path in owned_paths:
            if (
                design_standards_root is not None
                and _is_within(owned_path.casefold(), design_standards_root.casefold())
                and owned_path != design_standards_root
                and not any(_is_within(owned_path, path) for path in prototype_paths)
                and not canonical_standard_path(owned_path, design_standards_root)
            ):
                raise TaskGraphError(f"tasks[{index}] standards writes require exact shallow Markdown leaves")
        is_design_writer = (
            raw.get("role") == "xy-uiux"
            and raw.get("surface_kind") == "design_ui"
        )
        # production_ui 有更具体的 ui_change 路径错误，交给后续路由校验输出；
        # 其他 Writer 在这里统一拒绝角色伪装或缺失角色。
        if (
            overlaps_design_boundary
            and raw.get("surface_kind") != "production_ui"
            and not is_design_writer
        ):
            raise TaskGraphError(
                f"tasks[{index}] writer overlapping a typed design path must use "
                "role xy-uiux and surface_kind design_ui"
            )

    # 纯规范维护沿用设计角色，不另造一个宿主角色；显式模式只缩小写入权限，
    # 不能被生产角色或无角色任务拿来规避原型选择和设计路径的保护。
    if "design_mode" in raw:
        mode = raw["design_mode"]
        if not isinstance(mode, str) or mode not in {"prototype", "standards_only"}:
            raise TaskGraphError(f"tasks[{index}].design_mode is unsupported")
        if raw.get("role") != "xy-uiux" or raw.get("surface_kind") != "design_ui":
            raise TaskGraphError(f"tasks[{index}].design_mode requires xy-uiux + design_ui")

    if "role" not in raw:
        # 运行时快照中的 Writer 必须能追溯到唯一实现角色；否则它既能绕过角色路由，
        # 也能绕过工程规范必读门禁。只读、证据和 QA 任务仍可省略实现角色。
        if raw.get("task_type") == "writer":
            raise TaskGraphError(f"tasks[{index}] writer requires a non-empty role")
        if "surface_kind" in raw or "qa_scope" in raw or "ui_change" in raw:
            raise TaskGraphError(
                f"tasks[{index}] plan-only UI fields require a non-empty role"
            )
        return
    role = raw["role"]
    if not isinstance(role, str) or not role.strip():
        raise TaskGraphError(f"tasks[{index}].role must be non-empty")
    if raw.get("task_type") == "writer" and role == "xy-qa":
        raise TaskGraphError(f"tasks[{index}] writer cannot use role xy-qa")
    if "surface_kind" not in raw:
        raise TaskGraphError(f"tasks[{index}] with role requires surface_kind")
    if "qa_scope" not in raw and raw.get("workflow_level") != "Light":
        raise TaskGraphError(f"tasks[{index}] with role requires qa_scope")
    if "qa_scope" in raw and raw["qa_scope"] != "request":
        raise TaskGraphError(f"tasks[{index}].qa_scope must be 'request'")
    surface_kind = raw["surface_kind"]
    if surface_kind not in {"production_ui", "design_ui", "non_ui"}:
        raise TaskGraphError(f"tasks[{index}].surface_kind is unsupported: {surface_kind!r}")
    if "solution_consultation" in raw:
        from lib.project.project_discovery import IMPLEMENTATION_ROLES
        # 普通历史证据任务可能用路径作资源锁；明确的方案咨询从创建到正式交接都
        # 没有项目文件所有权。所读源码、规范及独立结果证据由各自读取合同表达。
        if (raw["solution_consultation"] is not True or raw.get("workflow_level") != "Full"
                or raw.get("task_type") != "read_only" or raw.get("owned_paths") != []
                or {"design_mode", "ui_change", "standards_exceptions"} & raw.keys()
                or (role, surface_kind) != ("xy-uiux", "design_ui")
                and not (role in IMPLEMENTATION_ROLES and surface_kind == "non_ui")):
            raise TaskGraphError(f"tasks[{index}] solution_consultation requires a Full read_only engineering "
                                 "or design role, empty owned_paths and no design or production write mode")
    if role == "xy-uiux" and surface_kind != "design_ui":
        raise TaskGraphError(
            f"tasks[{index}] role xy-uiux requires surface_kind design_ui"
        )
    audit_surfaces = set(
        _string_list(raw.get("audit_surfaces"), f"tasks[{index}].audit_surfaces")
    )

    if surface_kind == "production_ui":
        if raw.get("task_type") != "writer":
            raise TaskGraphError(f"tasks[{index}] production_ui must be a writer")
        if role in {"xy-uiux", "xy-qa"}:
            raise TaskGraphError(f"tasks[{index}] production_ui cannot use role {role}")
        if not isinstance(raw.get("ui_change"), dict):
            raise TaskGraphError(f"tasks[{index}] production_ui requires ui_change")
        if not {"ui", "accessibility"}.issubset(audit_surfaces):
            raise TaskGraphError(
                f"tasks[{index}] production_ui requires ui and accessibility audit surfaces"
            )
        return

    if surface_kind == "design_ui":
        # 仅原型的每个设计委托可以直接使用原 Light 单包。请求范围取自包顶层；
        # 角色、精确路径、需求和方案批准仍走同一校验，不能靠自称原型降级生产 UI。
        if raw.get("workflow_level") == "Light" and request_scope != "prototype_only":
            raise TaskGraphError(f"tasks[{index}] design work requires Full or an explicit prototype_only pack")
        if role != "xy-uiux":
            raise TaskGraphError(f"tasks[{index}] design_ui must use role xy-uiux")
        if raw.get("solution_consultation") is True:
            # 正常实施委托中，PM 可先请设计角色核实现状或说明选项。咨询复用设计
            # 领域的读取依据，但只有 Writer 才可以申请文件、原型模式或生产变更。
            # 原请求范围仍由公共校验检查；此节点不能替代下游要求的原型 Writer。
            return
        if raw.get("task_type") != "writer":
            raise TaskGraphError(f"tasks[{index}] design_ui must be a writer or an explicit read_only solution_consultation")
        if "ui_change" in raw:
            raise TaskGraphError(f"tasks[{index}] design_ui must not carry production ui_change")
        gates = _string_list(raw["gates"], f"tasks[{index}].gates")
        if "requirements_approved" not in gates:
            raise TaskGraphError(f"tasks[{index}] design_ui requires requirements_approved")
        if not {"ui", "accessibility"}.issubset(audit_surfaces):
            raise TaskGraphError(
                f"tasks[{index}] design_ui requires ui and accessibility audit surfaces"
            )
        owned_paths = tuple(
            _safe_relative_path(path, f"tasks[{index}].owned_paths[{position}]")
            for position, path in enumerate(
                _string_list(raw["owned_paths"], f"tasks[{index}].owned_paths")
            )
        )
        if not owned_paths:
            raise TaskGraphError(f"tasks[{index}] design_ui requires owned_paths")
        if raw.get("design_mode", "prototype") == "standards_only":
            # 标准维护不制作原型，也不消费或制造视觉批准。这里按路径交集检查，
            # 同时拒绝整个 design 根目录、prototype 父目录、HTML/CSS 与生产源码。
            if any(gate == "visual_approved" or gate.startswith("visual_approved:") for gate in gates):
                raise TaskGraphError(f"tasks[{index}] standards_only must not declare a visual gate")
            for owned_path in owned_paths:
                if (
                    design_standards_root is None
                    or standard_domain(owned_path, design_standards_root) != "design"
                ):
                    raise TaskGraphError(
                        f"tasks[{index}] standards_only owns only exact design-standard Markdown leaves: {owned_path!r}"
                    )
            return
        for owned_path in owned_paths:
            # 原型与设计规范都是目录边界，但 Writer 只能拥有其中的具体叶路径，
            # 不能把整个设计规范根目录声明为自己的写权限。
            inside_prototype = any(
                _is_within(owned_path, boundary) for boundary in prototype_paths
            )
            inside_design_standards = (
                design_standards_root is not None
                and standard_domain(owned_path, design_standards_root) == "design"
            )
            if not inside_prototype and not inside_design_standards:
                raise TaskGraphError(
                    f"tasks[{index}] design_ui owned path must be inside a configured "
                    f"prototype or design-standards path: {owned_path!r}"
                )
        return

    if "ui_change" in raw:
        raise TaskGraphError(f"tasks[{index}] non_ui must not carry ui_change")
    # QA/read-only 任务可以审计 UI，但只有 Writer 把 UI 审计面标成 non_ui 时才构成
    # 生产分类矛盾；否则会误伤统一 QA 对多表面的请求级审计。
    if raw.get("task_type") == "writer" and (
        "ui" in audit_surfaces or "accessibility" in audit_surfaces
    ):
        raise TaskGraphError(
            f"tasks[{index}] non_ui conflicts with ui or accessibility audit surfaces"
        )


def _validate_prototype_decision(
    value: Any,
    label: str,
    affected_surfaces: tuple[str, ...],
    current_requirement_fingerprint: Any,
    current_prototype_policy: str,
) -> None:
    """验证需求确认中的原型选择，防止 PM 用默认值替代用户决定。

    设计变更的两条生产路径都必须携带同一份选择记录：PM 先给出建议和理由，
    用户再选择制作原型或直接开发。记录同时绑定冻结需求与精确 UI 表面，避免
    旧选择被复用到扩大的范围；推荐结果可以与用户选择不同，但最终策略必须
    与用户选择一致。
    """

    if not isinstance(value, dict):
        raise TaskGraphError(f"{label} requires prototype_decision")
    missing = PROTOTYPE_DECISION_FIELDS - set(value)
    unknown = set(value) - PROTOTYPE_DECISION_FIELDS
    if missing:
        raise TaskGraphError(f"{label} is missing field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise TaskGraphError(
            f"{label} has unsupported field(s): {', '.join(sorted(unknown))}"
        )
    if value["source"] != "requirements_confirmation_user_choice":
        raise TaskGraphError(
            f"{label}.source must be 'requirements_confirmation_user_choice'"
        )
    choice_ref = _nonempty_string(
        value["choice_ref"], f"{label}.choice_ref"
    )
    if not USER_CHOICE_REF_RE.fullmatch(choice_ref):
        raise TaskGraphError(
            f"{label}.choice_ref must be a stable user:<reference>"
        )
    requirement_fingerprint = value["requirement_fingerprint"]
    if not isinstance(requirement_fingerprint, str) or not SHA256_RE.fullmatch(
        requirement_fingerprint
    ):
        raise TaskGraphError(
            f"{label}.requirement_fingerprint must be lowercase SHA-256"
        )
    if (
        not isinstance(current_requirement_fingerprint, str)
        or not SHA256_RE.fullmatch(current_requirement_fingerprint)
        or requirement_fingerprint != current_requirement_fingerprint
    ):
        raise TaskGraphError(
            f"{label}.requirement_fingerprint must match task graph "
            "requirements_fingerprint"
        )
    decision_surfaces = _string_list(
        value["affected_surfaces"], f"{label}.affected_surfaces"
    )
    if not decision_surfaces or any(not item.strip() for item in decision_surfaces):
        raise TaskGraphError(
            f"{label}.affected_surfaces must contain non-empty values"
        )
    if len(set(decision_surfaces)) != len(decision_surfaces):
        raise TaskGraphError(f"{label}.affected_surfaces must not contain duplicates")
    if set(decision_surfaces) != set(affected_surfaces):
        raise TaskGraphError(
            f"{label}.affected_surfaces must exactly match ui_change.affected_surfaces"
        )
    recommended_policy = value["recommended_policy"]
    selected_policy = value["selected_policy"]
    if recommended_policy not in USER_SELECTABLE_PROTOTYPE_POLICIES:
        raise TaskGraphError(
            f"{label}.recommended_policy must be 'required' or 'waived_by_user'"
        )
    _nonempty_string(
        value["recommendation_reason"], f"{label}.recommendation_reason"
    )
    if selected_policy not in USER_SELECTABLE_PROTOTYPE_POLICIES:
        raise TaskGraphError(
            f"{label}.selected_policy must be 'required' or 'waived_by_user'"
        )
    if selected_policy != current_prototype_policy:
        raise TaskGraphError(
            f"{label}.selected_policy must match ui_change.prototype_policy"
        )


def _validate_ui_change(
    raw: dict[str, Any],
    index: int,
    prototype_paths: tuple[str, ...],
    design_standards_root: str | None,
    design_standard_fingerprints: dict[str, str],
    requirement_fingerprint: Any,
) -> None:
    """校验四种 UI 路由、冻结依据、路径边界和视觉 Gate 的一一绑定。"""

    value = raw.get("ui_change")
    if value is None:
        return
    if not isinstance(value, dict):
        raise TaskGraphError(f"tasks[{index}].ui_change must be an object")
    missing = UI_CHANGE_FIELDS - set(value)
    unknown = set(value) - UI_CHANGE_FIELDS
    if missing:
        raise TaskGraphError(
            f"tasks[{index}].ui_change is missing field(s): {', '.join(sorted(missing))}"
        )
    if unknown:
        raise TaskGraphError(
            f"tasks[{index}].ui_change has unsupported field(s): {', '.join(sorted(unknown))}"
        )

    route = value["route"]
    design_delta = value["design_delta"]
    prototype_policy = value["prototype_policy"]
    justification = value["justification"]
    if not isinstance(route, str) or route not in UI_ROUTES:
        raise TaskGraphError(f"tasks[{index}].ui_change has unsupported route: {route!r}")
    if raw.get("workflow_level") == "Light" and route != "UI-Conformance":
        raise TaskGraphError(f"tasks[{index}] Light UI copy requires UI-Conformance; design changes require Full")
    expected_delta = "none" if route == "UI-Conformance" else "changed"
    if not isinstance(design_delta, str) or design_delta != expected_delta:
        raise TaskGraphError(
            f"tasks[{index}].ui_change route {route!r} requires design_delta {expected_delta!r}"
        )
    if not isinstance(prototype_policy, str) or prototype_policy not in PROTOTYPE_POLICIES:
        raise TaskGraphError(
            f"tasks[{index}].ui_change has unsupported prototype_policy: "
            f"{prototype_policy!r}"
        )
    authority_refs = _validate_authority_refs(
        value["design_authority_refs"],
        f"tasks[{index}].ui_change.design_authority_refs",
    )
    _validate_authority_path_bindings(
        authority_refs,
        prototype_paths,
        design_standards_root,
        design_standard_fingerprints,
        f"tasks[{index}].ui_change.design_authority_refs",
    )
    affected_surfaces = _string_list(
        value["affected_surfaces"], f"tasks[{index}].ui_change.affected_surfaces"
    )
    if not isinstance(justification, str) or not justification.strip():
        raise TaskGraphError(f"tasks[{index}].ui_change.justification must be non-empty")
    if not affected_surfaces or any(not item.strip() for item in affected_surfaces):
        raise TaskGraphError(
            f"tasks[{index}].ui_change.affected_surfaces must contain non-empty values"
        )
    if prototype_policy != "waived_by_user" and not authority_refs:
        raise TaskGraphError(
            f"tasks[{index}].ui_change {route} requires non-empty design_authority_refs"
        )
    if raw.get("role") == "xy-uiux":
        raise TaskGraphError(f"tasks[{index}].ui_change cannot use role xy-uiux")
    gates = _string_list(raw["gates"], f"tasks[{index}].gates")
    if raw.get("workflow_level") == "Full" and "requirements_approved" not in gates:
        raise TaskGraphError(
            f"tasks[{index}].ui_change {route} requires requirements_approved"
        )
    owned_paths = tuple(
        _safe_relative_path(path, f"tasks[{index}].owned_paths[{position}]")
        for position, path in enumerate(
            _string_list(raw["owned_paths"], f"tasks[{index}].owned_paths")
        )
    )
    for owned_path in owned_paths:
        if _overlaps_design_path(owned_path, prototype_paths, design_standards_root):
            raise TaskGraphError(
                f"tasks[{index}].ui_change must not overlap configured design path: {owned_path!r}"
            )

    visual_gates = [gate for gate in gates if gate.startswith("visual_approved")]
    if route == "UI-Conformance":
        if prototype_policy != "not_applicable":
            raise TaskGraphError(
                f"tasks[{index}].ui_change UI-Conformance requires "
                "prototype_policy 'not_applicable'"
            )
        if value["prototype_decision"] is not None:
            raise TaskGraphError(
                f"tasks[{index}].ui_change UI-Conformance must not declare prototype_decision"
            )
        if visual_gates:
            raise TaskGraphError(
                f"tasks[{index}].ui_change UI-Conformance must not declare a visual gate"
            )
        return

    if prototype_policy == "not_applicable":
        raise TaskGraphError(
            f"tasks[{index}].ui_change {route} requires prototype_policy "
            "'required' or 'waived_by_user'"
        )

    # 设计变更不再采用 PM 默认原型策略。无论最终走原型还是直接开发，
    # 都必须能证明该策略来自同一次需求确认中的用户选择。
    _validate_prototype_decision(
        value["prototype_decision"],
        f"tasks[{index}].ui_change {prototype_policy}",
        affected_surfaces,
        requirement_fingerprint,
        prototype_policy,
    )
    if prototype_policy == "waived_by_user":
        if any(ref["kind"] == "prototype_contract" for ref in authority_refs):
            raise TaskGraphError(
                f"tasks[{index}].ui_change waived_by_user must not use "
                "prototype_contract authority"
            )
        if visual_gates:
            raise TaskGraphError(
                f"tasks[{index}].ui_change waived_by_user must not declare a visual gate"
            )
        return

    prototype_refs = [ref for ref in authority_refs if ref["kind"] == "prototype_contract"]
    if not prototype_refs:
        raise TaskGraphError(
            f"tasks[{index}].ui_change {route} requires a resolved prototype_contract authority"
        )
    prototype_authority_ids = [ref["authority_id"] for ref in prototype_refs]
    if len(set(prototype_authority_ids)) != len(prototype_authority_ids):
        raise TaskGraphError(
            f"tasks[{index}].ui_change prototype authority_id values must be unique"
        )
    prototype_ref_paths = [ref["path"] for ref in prototype_refs]
    if len(set(prototype_ref_paths)) != len(prototype_ref_paths):
        raise TaskGraphError(f"tasks[{index}].ui_change prototype paths must be unique")
    for ref_path in prototype_ref_paths:
        if not any(_is_within(ref_path, boundary) for boundary in prototype_paths):
            raise TaskGraphError(
                f"tasks[{index}].ui_change prototype authority must be inside a configured "
                f"prototype path: {ref_path!r}"
            )
    expected_visual_gates = {
        f"visual_approved:{ref['authority_id']}@{ref['content_fingerprint']}"
        for ref in prototype_refs
    }
    if set(visual_gates) != expected_visual_gates or len(visual_gates) != len(
        expected_visual_gates
    ):
        raise TaskGraphError(
            f"tasks[{index}].ui_change {route} requires exact visual gate(s): "
            f"{', '.join(sorted(expected_visual_gates))}"
        )


def _validate_ui_dependencies(
    raw_tasks: list[dict[str, Any]], prototype_paths: tuple[str, ...]
) -> None:
    """校验 UI 生产任务对设计任务的依赖方向，阻止一致性路由伪装。"""

    tasks_by_id = {
        raw.get("id"): raw
        for raw in raw_tasks
        if isinstance(raw.get("id"), str) and raw.get("id")
    }
    for index, raw in enumerate(raw_tasks):
        ui_change = raw.get("ui_change")
        if not isinstance(ui_change, dict):
            continue
        route = ui_change.get("route")
        prototype_policy = ui_change.get("prototype_policy")
        pending = list(_string_list(raw.get("depends_on"), f"tasks[{index}].depends_on"))
        visited: set[str] = set()
        design_dependencies: list[dict[str, Any]] = []
        while pending:
            dependency_id = pending.pop()
            if dependency_id in visited:
                continue
            visited.add(dependency_id)
            dependency = tasks_by_id.get(dependency_id)
            if dependency is None:
                continue
            if (
                dependency.get("role") == "xy-uiux"
                and dependency.get("surface_kind") == "design_ui"
                and dependency.get("task_type") == "writer"
            ):
                design_dependencies.append(dependency)
            pending.extend(
                _string_list(
                    dependency.get("depends_on"),
                    f"task {dependency_id!r}.depends_on",
                )
            )

        if route == "UI-Conformance" and design_dependencies:
            raise TaskGraphError(
                f"tasks[{index}].ui_change UI-Conformance must not depend on xy-uiux: "
                f"{', '.join(sorted(str(item.get('id')) for item in design_dependencies))}"
            )
        # 用户跳过的是原型，不是已批准设计规则的文档维护。必须检查整个传递依赖闭包：
        # standards_only 后面如果藏着原型任务，仍然属于未经用户选择的原型依赖。
        prototype_dependencies = [
            dependency for dependency in design_dependencies
            if dependency.get("design_mode", "prototype") != "standards_only"
        ]
        if prototype_policy == "waived_by_user" and prototype_dependencies:
            raise TaskGraphError(
                f"tasks[{index}].ui_change waived_by_user must not depend on xy-uiux: "
                f"{', '.join(sorted(str(item.get('id')) for item in prototype_dependencies))}"
            )
        if route in UI_DESIGN_ROUTES and prototype_policy == "required":
            matching_dependencies = [
                dependency
                for dependency in prototype_dependencies
                if dependency.get("request_id") == raw.get("request_id")
            ]
            if not matching_dependencies:
                raise TaskGraphError(
                    f"tasks[{index}].ui_change {route} requires a matching xy-uiux design dependency"
                )
            prototype_refs = [
                ref
                for ref in ui_change.get("design_authority_refs", [])
                if isinstance(ref, dict) and ref.get("kind") == "prototype_contract"
            ]
            produced_paths = [
                _safe_relative_path(
                    path,
                    f"design dependency {dependency.get('id')!r}.owned_paths[{position}]",
                )
                for dependency in matching_dependencies
                for position, path in enumerate(
                    _string_list(
                        dependency.get("owned_paths"),
                        f"design dependency {dependency.get('id')!r}.owned_paths",
                    )
                )
            ]
            for ref in prototype_refs:
                ref_path = _safe_relative_path(
                    ref.get("path"),
                    f"tasks[{index}].ui_change prototype authority path",
                )
                if not any(_is_within(ref_path, boundary) for boundary in prototype_paths):
                    raise TaskGraphError(
                        f"tasks[{index}].ui_change {route} prototype authority must be inside "
                        "a configured prototype path"
                    )
                if not any(_is_within(ref_path, path) for path in produced_paths):
                    raise TaskGraphError(
                        f"tasks[{index}].ui_change {route} prototype authority is not owned "
                        "by its matching xy-uiux dependency"
                    )


def _tasks(payload: dict[str, Any], *, handoff: bool = False, root: Path | None = None) -> list[Task]:
    _require_version(payload)
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        raise TaskGraphError("tasks must be an array")
    typed_raw_tasks: list[dict[str, Any]] = []
    ui_task_present = False
    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict):
            raise TaskGraphError(f"tasks[{index}] must be an object")
        typed_raw_tasks.append(raw)
        ui_task_present = ui_task_present or raw.get("surface_kind") in {
            "production_ui",
            "design_ui",
        }
    prototype_paths = _resolved_ui_contract(payload, ui_task_present)
    standards_contract = _resolved_standards_contract(payload)
    design_standards_root = (
        standards_contract["root"] if standards_contract is not None else None
    )
    design_standard_fingerprints = {
        path: leaf["content_fingerprint"]
        for path, leaf in (
            standards_contract["leaves"].items()
            if standards_contract is not None
            else ()
        )
        if leaf["domain"] == "design"
    }
    if design_standards_root is not None and prototype_paths:
        # 原型已经并入统一设计权威分支。运行时快照只能冻结这个由适配器推导的
        # 单一目录，不能重新声明一个平行或更宽的设计路径。
        expected_prototype_root = f"{design_standards_root}/prototype"
        if prototype_paths != (expected_prototype_root,):
            raise TaskGraphError(
                "ui_contract.prototype_paths must equal "
                "standards_contract.root/prototype"
            )

    tasks: list[Task] = []
    scopes = request_scopes(payload)
    for index, raw in enumerate(typed_raw_tasks):
        unknown = set(raw) - GRAPH_FIELDS - PLAN_ONLY_FIELDS
        if unknown:
            raise TaskGraphError(
                f"tasks[{index}] has unsupported field(s): {', '.join(sorted(unknown))}"
            )
        missing = GRAPH_FIELDS - set(raw)
        if missing:
            raise TaskGraphError(
                f"tasks[{index}] is missing scheduler field(s): {', '.join(sorted(missing))}"
            )
        if not handoff and raw.get("workflow_level") != "Full":
            raise TaskGraphError("graph tasks require workflow_level Full; Light uses a single task pack")
        # 原图、单包、交接与修订共用命令语法。只有自足 Writer 另要求非空，
        # 历史图及只读观察任务仍可没有命令或以空列表表示无需运行命令。
        if "verification_commands" in raw:
            if not isinstance(raw["verification_commands"], list):
                raise TaskGraphError("verification_commands must be an array")
            for command in raw["verification_commands"]:
                validate_command(command, "verification_commands")
        _validate_plan_contract(raw, index, prototype_paths, design_standards_root,
                                scopes.get(raw["request_id"]) if isinstance(raw["request_id"], str) else None)
        _validate_ui_change(
            raw,
            index,
            prototype_paths,
            design_standards_root,
            design_standard_fingerprints,
            payload.get("requirements_fingerprint"),
        )
        _validate_standards_access(raw, index, standards_contract)
        task_id = raw["id"]
        request_id = raw["request_id"]
        task_type = raw["task_type"]
        state = raw["state"]
        if not all(isinstance(value, str) for value in (task_id, request_id, task_type, state)):
            raise TaskGraphError(f"tasks[{index}] scalar scheduler fields must be strings")
        gates = _string_list(raw["gates"], f"tasks[{index}].gates")
        task_intent.validate_intent(raw)
        business_confirmation(raw)
        validate_visual_record(payload, raw)
        # Full保留需求确认；Light不会因复用校验器而被提升为Full。UI及保护路径的
        # 专用门禁仍由各自原校验器执行，此处不为Light增加绕过分支。
        if task_type == "writer" and raw.get("workflow_level") == "Full" and "requirements_approved" not in gates:
            raise TaskGraphError(f"tasks[{index}] writer requires requirements_approved")
        tasks.append(
            Task(
                id=task_id,
                request_id=request_id,
                task_type=task_type,
                depends_on=_string_list(raw["depends_on"], f"tasks[{index}].depends_on"),
                blocks=_string_list(raw["blocks"], f"tasks[{index}].blocks"),
                gates=gates,
                owned_paths=_string_list(raw["owned_paths"], f"tasks[{index}].owned_paths"),
                semantic_locks=_string_list(
                    raw["semantic_locks"], f"tasks[{index}].semantic_locks"
                ),
                state=state,
                agent_retired=raw.get("agent_retired", False),
            )
        )
    validate_scoped_tasks(payload, design_standards_root, root)
    validate_decisions(payload, for_handoff=handoff and any(
        task.get("workflow_level") == "Full" for task in typed_raw_tasks))
    if not handoff:
        _validate_ui_dependencies(typed_raw_tasks, prototype_paths)
    from lib.foundation_qa import validate_contract
    validate_contract(payload, handoff=handoff)
    # 原生ID只作身份元数据；退役标记仅排除后续派发，不另存宿主存活或任务状态。
    validate_references(typed_raw_tasks)
    return tasks


def _nonnegative_integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TaskGraphError(f"{key} must be an integer >= 0")
    return value


def _positive_integer(payload: dict[str, Any], key: str) -> int:
    value = _nonnegative_integer(payload, key)
    if value < 1:
        raise TaskGraphError(f"{key} must be an integer >= 1")
    return value


def _execute(command: str, payload: dict[str, Any], *, root: Path | None = None,
             record_path: Path | None = None) -> dict[str, Any]:
    if command == "capacity":
        return {
            "capacity": effective_dispatch_capacity(
                configured_subagents=_positive_integer(payload, "configured_subagents"),
                configured_writers=_positive_integer(payload, "configured_writers"),
                host_available_subagents=_nonnegative_integer(
                    payload, "host_available_subagents"
                ),
                active_subagents=_nonnegative_integer(payload, "active_subagents"),
                active_writers=_nonnegative_integer(payload, "active_writers"),
            )
        }

    is_pack = "task" in payload
    snapshot = pack_snapshot(payload) if is_pack else payload
    if is_pack:
        # Full交接包的依赖已在权威图中校验；只保留当前任务做局部合同核验，
        # 不向接收方复制依赖任务，也不拿单包假冒请求级READY/QA-ready证据。
        snapshot["tasks"][0]["depends_on"] = []
        snapshot["tasks"][0]["blocks"] = []
        if command != "validate" and payload["task"].get("workflow_level") == "Full":
            raise TaskGraphError("Full readiness queries require the authoritative graph")
        if payload["task"].get("task_type") == "writer":
            task = payload["task"]
            _nonempty_string(task.get("goal"), "self-contained task.goal")
            for field in ("input_contracts", "output_contracts", "acceptance_evidence", "verification_commands"):
                if not isinstance(task.get(field), list) or not task[field]:
                    raise TaskGraphError(f"self-contained task requires non-empty {field}")
                if field != "verification_commands":
                    for item in task[field]:
                        _nonempty_string(item, f"task.{field}")
    tasks = _tasks(snapshot, handoff=is_pack, root=root)
    validate_graph(tasks)
    if is_pack:
        checkpoint = payload.get("qa_checkpoint")
        handoff_task = payload["task"]
        foundation = handoff_task.get("foundation_task_id")
        from lib.foundation_qa import is_ordinary_reviewer
        ordinary = is_ordinary_reviewer(handoff_task)
        if "qa_document_base" in payload and (not foundation or not isinstance(checkpoint, dict)
                or checkpoint.get("kind") != "request" or not isinstance(payload["qa_document_base"], str)
                or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", payload["qa_document_base"])):
            raise TaskGraphError("qa_document_base requires a final Foundation QA pack and Git commit")
        if foundation or ordinary and ("qa_checkpoint" in payload or "qa_checkpoint_fingerprint" in payload):
            if (not isinstance(checkpoint, dict) or set(checkpoint) != {"kind", "writer_ids"}
                    or checkpoint.get("kind") not in (("foundation", "request") if foundation else ("request",))
                    or not isinstance(checkpoint.get("writer_ids"), list)
                    or any(not isinstance(item, str) or not item for item in checkpoint["writer_ids"])
                    or checkpoint["writer_ids"] != sorted(set(checkpoint["writer_ids"]))
                    or foundation and foundation not in checkpoint["writer_ids"]
                    or not isinstance(payload.get("qa_checkpoint_fingerprint"), str)
                    or not SHA256_RE.fullmatch(payload["qa_checkpoint_fingerprint"])):
                raise TaskGraphError("Full QA pack requires a valid checkpoint and fingerprint")
        elif "qa_checkpoint" in payload or "qa_checkpoint_fingerprint" in payload:
            raise TaskGraphError("QA checkpoint metadata requires Full QA")
    if is_pack and "reviewed_solution_decisions" in payload:
        validate_reviewed_solutions(payload)
    if is_pack and "reviewed_business_confirmations" in payload:
        checkpoint = payload.get("qa_checkpoint", {})
        rows = payload["reviewed_business_confirmations"]
        if (payload["task"]["task_type"] != "qa" or not isinstance(rows, list) or not rows
                or not checkpoint and payload["task"].get("workflow_level") != "Light"):
            raise TaskGraphError("reviewed_business_confirmations requires the current QA checkpoint")
        seen = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"writer_id", "request_id", "gates", "additional_business_confirmation"}
                    or not isinstance(row["writer_id"], str) or row["writer_id"] in seen
                    or checkpoint and row["writer_id"] not in checkpoint["writer_ids"]
                    or not checkpoint and row["request_id"] != payload["task"]["request_id"]
                    or not isinstance(row["request_id"], str) or not row["request_id"].strip()
                    or not isinstance(row["gates"], list) or len(row["gates"]) != 1
                    or not isinstance(row["gates"][0], str) or not EXCEPTIONAL_GATE_RE.fullmatch(row["gates"][0])
                    or row["gates"][0] not in payload.get("approved_gates", [])):
                raise TaskGraphError("reviewed_business_confirmations must identify a reviewed Writer and its exact exceptional gate")
            seen.add(row["writer_id"])
            business_confirmation(row)
    if is_pack and payload["task"].get("foundation_task_id") and "reviewed_ui_changes" not in payload:
        raise TaskGraphError("Foundation QA pack requires complete reviewed_ui_changes")
    if is_pack and "reviewed_ui_changes" in payload:
        # 交接包中的投影只能由 QA 消费；逐项复用生产路由校验，防止格式合法但
        # 不完整或伪造的依据成为审查依据。实际请求范围仍以权威图及其导出字节为准。
        if payload["task"].get("task_type") != "qa":
            raise TaskGraphError("reviewed_ui_changes is only valid for QA packs")
        reviewed = payload["reviewed_ui_changes"]
        if not isinstance(reviewed, list):
            raise TaskGraphError("reviewed_ui_changes must be an array")
        prototype_paths = _resolved_ui_contract(payload, bool(reviewed))
        contract = _resolved_standards_contract(payload)
        root = contract["root"] if contract else None
        fingerprints = {path: leaf["content_fingerprint"] for path, leaf in
                        (contract["leaves"].items() if contract else ())
                        if leaf["domain"] == "design"}
        seen = set()
        for index, item in enumerate(reviewed):
            optional = {"qa_scope"} if isinstance(item, dict) and item.get("workflow_level") == "Light" else set()
            if (not isinstance(item, dict) or set(item) - REVIEWED_UI_FIELDS
                    or REVIEWED_UI_FIELDS - set(item) - optional):
                raise TaskGraphError("reviewed_ui_changes entries require complete production writer fields")
            if item["task_type"] != "writer" or item["surface_kind"] != "production_ui":
                raise TaskGraphError("reviewed_ui_changes entries must describe production writers")
            identity = _nonempty_string(item["id"], "reviewed_ui_changes.id")
            if identity in seen:
                raise TaskGraphError("reviewed_ui_changes contains duplicate writer IDs")
            seen.add(identity)
            # 受审投影上文已限定为生产 Writer；这里不能继承独立设计单包的准入范围。
            _validate_plan_contract(item, index, prototype_paths, root, request_scope=None)
            _validate_ui_change(item, index, prototype_paths, root, fingerprints,
                                payload.get("requirements_fingerprint"))
        if payload.get("qa_checkpoint") and (foundation and not seen
                or not seen <= set(payload["qa_checkpoint"]["writer_ids"])):
            raise TaskGraphError("QA checkpoint must include its production UI review scope")
        if reviewed and not {"ui", "accessibility"}.issubset(
            _string_list(payload["task"].get("audit_surfaces"), "QA audit_surfaces")
        ):
            raise TaskGraphError("production UI QA requires ui and accessibility audit surfaces")
    if not is_pack:
        # 请求闭包可能包含跨请求的共享 Writer；统一 QA 必须覆盖其中的界面和无障碍。
        for raw in snapshot["tasks"]:
            if raw["task_type"] != "qa":
                continue
            closure = request_closure(tasks, raw["request_id"])
            if any(item["id"] in closure and item.get("task_type") == "writer"
                   and item.get("surface_kind") == "production_ui" for item in snapshot["tasks"]):
                surfaces = set(_string_list(raw.get("audit_surfaces"), "QA audit_surfaces"))
                if not {"ui", "accessibility"}.issubset(surfaces):
                    raise TaskGraphError("production UI QA requires ui and accessibility audit surfaces")
    if not is_pack:
        validate_execution(payload)
    if command == "validate":
        return {"status": "valid"}
    if command == "ready":
        if not is_pack:
            from lib.foundation_qa import current_request_receipt, is_full_reviewer
            # 原图可保留早期 QA_PASSED 供追溯；调度只把当前可校验的验收视为完成依赖。
            stale = {task["id"] for task in snapshot["tasks"] if is_full_reviewer(task)
                     and task["state"] == "QA_PASSED" and not current_request_receipt(snapshot, task, root=root)}
            tasks = [replace(task, state="DECLARED") if task.id in stale else task for task in tasks]
        return {
            "ready": _foundation_ready(snapshot, ready_tasks(
                tasks,
                approved_gates=set(
                    _string_list(snapshot.get("approved_gates", []), "approved_gates")
                ),
                active_paths=set(_string_list(snapshot.get("active_paths"), "active_paths")),
                active_semantic_locks=set(
                    _string_list(
                        snapshot.get("active_semantic_locks"), "active_semantic_locks"
                    )
                ),
                capacity=len(tasks),
            ), root=root, record_path=record_path)
        }
    request_id = snapshot.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TaskGraphError("request_id must be a non-empty string")
    if request_scopes(snapshot).get(request_id) in ("discussion_only", "prototype_only"):
        # 设计结果由页面自查和用户视觉确认收口，即使该 Writer 已完成，也没有生产验收。
        return {"qa_ready": False, "request_id": request_id}
    # 分支各自验证成功不等于组合正确；只有 worktree 分支额外检查集成证据。
    from lib.foundation_qa import checkpoint
    qa = next((task for task in snapshot["tasks"] if task["task_type"] == "qa"
               and task["request_id"] == request_id and task.get("foundation_task_id")), None)
    if qa:
        ids = set(checkpoint(snapshot, qa, root=root)["writer_ids"])
        ready = qa_ready(tasks, request_id, writer_ids=ids)
    else:
        ids = request_closure(tasks, request_id)
        ready = qa_ready(tasks, request_id)
    # 历史构建状态仍可阅读；原型返工、阶段回执过期或缺批准时不能继续发起新的正式审查。
    ready = ready and not any(writer_blockers(snapshot, item, root, review_request=request_id) for item in snapshot["tasks"]
                              if item["id"] in ids and item["task_type"] == "writer")
    return {"qa_ready": ready and integration_ready(payload, request_id),
            "request_id": request_id}


def _foundation_ready(payload: dict[str, Any], candidates: list[str], *, root: Path | None = None,
                      record_path: Path | None = None) -> list[str]:
    """在原依赖、批准、锁规则上检查实际方案前置交付和 Foundation 阶段证据。"""
    selected = set(candidates)
    blocked = {item["id"] for item in payload["tasks"] if item["id"] in selected and writer_blockers(payload, item, root)}
    eligible = [task_id for task_id in candidates if task_id not in blocked]
    capacity = _nonnegative_integer(payload, "capacity")
    first = eligible[:capacity]
    if not first or record_path is None:
        return first
    from lib.shared_solution_records import filter_ready
    # 有名额不代表已通过共享方案门。优先复核原先会查询的候选；只有其中一项被挡下
    # 才从原始排序的后续候选补足名额。普通图和已批准的首批不额外读取任何成员。
    ready = filter_ready(record_path, payload["tasks"], first)
    remaining = capacity - len(ready)
    if remaining and len(eligible) > capacity:
        later = filter_ready(record_path, payload["tasks"], eligible[capacity:])
        ready.extend(later[:remaining])
    return ready


def _verify_solution_scope(pack: dict, source: dict) -> None:
    """按原图或同请求 Light Writer 单包回验，防止省略未列出的非 UI 决定或批准出处。"""
    _execute("validate", pack)
    _execute("validate", source)
    qa = pack.get("task", {})
    if qa.get("task_type") != "qa":
        raise TaskGraphError("solution scope verification requires a QA pack")
    if "task" in source:
        writer = source["task"]
        if (qa.get("workflow_level") != "Light" or writer.get("workflow_level") != "Light"
                or qa["request_id"] != writer["request_id"] or writer["task_type"] != "writer"):
            raise TaskGraphError("Light solution verification requires the same request's Writer pack")
        expected = reviewed_solutions([writer], source)
        expected_business = reviewed_business_confirmations([writer])
    else:
        exported = export_task_pack(source, qa["id"])
        if any(qa.get(key) != exported["task"].get(key) for key in ("request_id", "role", "agent_alias", "agent_ref")):
            raise TaskGraphError("QA solution scope Reviewer differs from authoritative graph")
        expected = exported.get("reviewed_solution_decisions", [])
        expected_business = exported.get("reviewed_business_confirmations", [])
    if pack.get("reviewed_business_confirmations", []) != expected_business:
        raise TaskGraphError("QA business confirmations differ from their authoritative source")
    if (pack.get("reviewed_solution_decisions", []) != expected
            or any(row["approval_gate"] not in source.get("approved_gates", []) for row in expected)):
        raise TaskGraphError("QA solution decisions differ from their authoritative source")


def _verify_ui_scope(pack: dict[str, Any], source: dict[str, Any]) -> None:
    """对照现存权威来源确认生产界面范围；单包自报的空列表不能证明完整性。"""
    _execute("validate", pack)
    if "task" not in pack or pack["task"].get("task_type") != "qa" or pack["task"].get("role") != "xy-qa":
        raise TaskGraphError("UI scope verification requires a QA task pack")
    _execute("validate", source)
    qa = pack["task"]
    if "task" in source:
        # Light 没有图，来源必须是同请求的当前生产 Writer 单包，不能用 QA 自报代替。
        writer = source["task"]
        if (qa.get("workflow_level") != "Light" or writer.get("workflow_level") != "Light"
                or writer.get("task_type") != "writer" or writer.get("surface_kind") != "production_ui"
                or writer.get("request_id") != qa.get("request_id")):
            raise TaskGraphError("Light UI scope requires the same request's production writer pack")
        expected = [{key: copy.deepcopy(writer[key]) for key in REVIEWED_UI_FIELDS if key in writer}]
        expected_decisions = reviewed_solutions([writer], source)
        expected_business = reviewed_business_confirmations([writer])
        expected_contract = source.get("ui_contract")
        expected_requirements = source.get("requirements_fingerprint")
    else:
        if qa.get("workflow_level") != "Full":
            raise TaskGraphError("Full graph cannot serve as Light UI scope source")
        exported = export_task_pack(source, qa.get("id"))
        if any(exported["task"].get(field) != qa.get(field)
               for field in ("id", "request_id", "task_type", "role", "agent_alias")):
            raise TaskGraphError("QA identity does not match the authoritative graph")
        expected = exported["reviewed_ui_changes"]
        expected_decisions = exported.get("reviewed_solution_decisions", [])
        expected_business = exported.get("reviewed_business_confirmations", [])
        expected_contract = exported.get("ui_contract")
        expected_requirements = exported.get("requirements_fingerprint")
    if "task" not in source and (pack.get("qa_checkpoint") != exported.get("qa_checkpoint")
            or pack.get("qa_checkpoint_fingerprint") != exported.get("qa_checkpoint_fingerprint")):
        raise TaskGraphError("QA checkpoint differs from its authoritative source")
    if expected_business != pack.get("reviewed_business_confirmations", []):
        raise TaskGraphError("QA business confirmations differ from their authoritative source")
    if (expected_decisions != pack.get("reviewed_solution_decisions", [])
            or any(row["approval_gate"] not in source.get("approved_gates", []) for row in expected_decisions)):
        raise TaskGraphError("QA solution decisions differ from their authoritative source")
    if source.get("runtime_binding") != pack.get("runtime_binding"):
        raise TaskGraphError("UI scope source and QA pack runtime bindings differ")
    if request_scopes(source).get(qa["request_id"]) != pack.get("request_scope"):
        raise TaskGraphError("QA request_scope differs from its authoritative source")
    if (not expected or pack.get("reviewed_ui_changes") != expected
            or pack.get("ui_contract") != expected_contract
            or pack.get("requirements_fingerprint") != expected_requirements):
        raise TaskGraphError("QA production UI scope differs from its authoritative source")
    if not {"ui", "accessibility"}.issubset(qa.get("audit_surfaces", [])):
        raise TaskGraphError("production UI QA requires ui and accessibility audit surfaces")


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.pm_id is not None and args.command != "task":
            raise TaskGraphError("--pm-id applies only to standalone prototype task export")
        if args.check_command is not None and (args.command != "fingerprints" or not args.check_command.strip()):
            raise TaskGraphError("--check-command requires fingerprints and an exact nonempty command")
        if args.claude_event and (args.command != "continuation" or args.host != "claude"):
            raise TaskGraphError("--claude-event applies only to Claude continuation")
        if args.command != "cleanup-scratch" and (args.dry_run or args.keep):
            raise TaskGraphError("--dry-run and --keep apply only to cleanup-scratch")
        if args.command in {"verify-ui-scope", "verify-solution-scope"}:
            if (not args.input or not args.source or any((args.patch, args.expect_sha256,
                    args.task_id, args.host, args.observed_state, args.output, args.root,
                    args.select, args.request_id, args.all))):
                raise TaskGraphError(f"{args.command} requires --input and --source only")
            if __package__:
                from . import task_graph_records as records
            else:
                import task_graph_records as records
            pack_body, source_body = records.read_record(args.input), records.read_record(args.source)
            verify_scope = _verify_ui_scope if args.command == "verify-ui-scope" else _verify_solution_scope
            verify_scope(records.decode(pack_body), records.decode(source_body))
            result = {"status": "valid", "task_pack_sha256": records.digest(pack_body),
                      "source_sha256": records.digest(source_body)}
        elif args.source and args.command != "task" and not args.check_command:
            raise TaskGraphError("--source applies only to scope verification or Light QA export")
        elif args.command == "continuation":
            if (not args.input or not args.task_id or not args.host or not args.observed_state
                    or any((args.patch, args.expect_sha256, args.output, args.root, args.select, args.request_id, args.all))):
                raise TaskGraphError("continuation requires --input, --task-id, --host and --observed-state only")
            payload = _read_payload(args.input)
            _execute("validate", payload)
            tasks = [payload["task"]] if "task" in payload else payload["tasks"]
            matches = [task for task in tasks if task["id"] == args.task_id]
            if not matches:
                raise TaskGraphError(f"unknown task ID: {args.task_id}")
            result = continuation(matches[0], args.host, args.observed_state,
                                  claude_event=read_claude_event(args.claude_event))
        elif args.host or args.observed_state:
            raise TaskGraphError("--host and --observed-state apply only to continuation")
        elif args.command in {"init", "update", "task", "fingerprints", "scratch", "cleanup-scratch"}:
            result = _record_command(args)
        else:
            if any((args.patch, args.expect_sha256, args.task_id, args.output, args.root, args.select, args.request_id, args.all)):
                raise TaskGraphError("record-operation options do not apply to read-only queries")
            payload = _read_payload(args.input)
            result = _execute(args.command, payload, record_path=args.input)
    except (TaskGraphError, WorktreePolicyError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.command == "cleanup-scratch" and result.get("status") == "failed":
        # 删除可能已部分发生；保留完整的实际成功计数，并让调用者收到非零退出码。
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.command == "fingerprints" and not result["matched"]:
        return 1
    return 0


def is_standalone_prototype(payload: dict) -> bool:
    """只收紧新启用的 Light 仅原型原件；导出的 Full 单包仍由原图管理。"""
    return (payload.get("request_scope") == "prototype_only" and isinstance(payload.get("task"), dict)
            and payload["task"].get("workflow_level") == "Light")


def publish_task_update(path, root, payload, body, expected, patch, *, pool_operation=False,
                        policy: DispatchPolicy = DEFAULT_DISPATCH):
    """公开更新与持锁准入共用同一次原记录语义、校验与 CAS 发布。

    调用方提供刚读到的原字节，在持有项目/池锁的调用中也必须再次比对目标 SHA。
    业务批准、许可和依赖仍消费原包；这里不依据调用方提供的 JSON 声明池准入。
    """
    from lib import task_graph_records as records

    if records.digest(body) != expected:
        raise TaskGraphError("graph fingerprint differs from --expect-sha256")
    # AGY 的首次身份只能由任务池核验原生回执。公开 update 同时服务 Light 和 Full，
    # 不能通过改写 --host、伪造领取字段或用已经 RUNNING 的旧图绕开此检查。
    # 已有引用由原更新协议处理，因此历史读取、同值重放和其它宿主保持兼容。
    if not pool_operation and isinstance(patch, dict) and isinstance(patch.get("tasks"), dict):
        for task in ([payload["task"]] if "task" in payload else payload["tasks"]):
            operation = patch["tasks"].get(task["id"])
            if isinstance(operation, dict):
                policy.guard_public_update(task, operation)
    if "task" in payload:
        if payload["task"].get("workflow_level") != "Light":
            raise TaskGraphError("Full task updates require the authoritative graph")
        if not isinstance(patch, dict) or set(patch) - {
                "tasks", "refresh_documents", "approve_solutions", "revoke_solutions"}:
            raise TaskGraphError("Light update supports only its current task, refresh_documents or solution approval updates")
        # 独立仅原型的领取和首次绑定要有本 PM 任务池的完整准入／身份核对。
        # 这个调用标志仅来自池锁内的内存调用；公开 JSON、CLI 选项和环境不授予它。
        if is_standalone_prototype(payload) and not pool_operation:
            task = payload["task"]
            changes = patch.get("tasks")
            operation = changes.get(task["id"]) if isinstance(changes, dict) else None
            if isinstance(operation, dict):
                fields = operation.get("set")
                first_binding = isinstance(fields, dict) and "agent_ref" in fields and "agent_ref" not in task
                if "claim" in operation or first_binding:
                    raise TaskGraphError("standalone prototype claim or first binding requires the registered task pool")
        # 仍调用同一个update核心和CAS发布，不保存内部归一快照。
        def validate_single(command: str, value: dict[str, Any]) -> dict[str, Any]:
            current = replace_pack_task(payload, value["tasks"][0], approved_gates=value.get("approved_gates"),
                                        solution_sources=value.get("solution_approval_sources", {}))
            return _execute(command, current, root=root)
        updated_snapshot = records.update(pack_snapshot(payload), patch, root, validate_single, record_sha=expected)
        updated = replace_pack_task(payload, updated_snapshot["tasks"][0],
                                    approved_gates=updated_snapshot.get("approved_gates"),
                                    solution_sources=updated_snapshot.get("solution_approval_sources", {}))
    else:
        updated = records.update(payload, patch, root,
                                 lambda command, graph: _execute(command, graph, root=root), record_sha=expected)
    new_body = body if updated == payload else (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    changed = records.publish(path, new_body, expected, root=root, task_update=patch)
    return {"updated": changed, "sha256": records.digest(new_body)}


def _record_command(args: argparse.Namespace) -> dict[str, Any]:
    """按需加载记录工具，不改变现有纯计算 API 或只读查询的输出。"""
    if __package__:
        from . import task_graph_records as records
    else:
        import task_graph_records as records
    if args.root is not None:
        # scratch／普通文件指纹同样不能误用另一项目；检查一致性不授予核心读取权。
        validate_task_source({}, root=args.root)
    if args.command in {"scratch", "cleanup-scratch"}:
        # 以当前代码所属实体包识别 AGY，不接受任务参数、角色或环境变量切换宿主。
        host = packaged_host()
        handoff = handoff_policy(host)
    if args.command == "scratch":
        if args.root is None or any((args.input, args.patch, args.expect_sha256, args.task_id, args.output, args.select, args.all)):
            raise TaskGraphError("scratch requires --root and accepts only --request-id")
        return records.scratch_workspace(args.root, args.request_id, handoff=handoff)
    if args.command == "cleanup-scratch":
        if args.root is None or any((args.input, args.patch, args.task_id, args.output, args.select)):
            raise TaskGraphError("cleanup-scratch requires --root and accepts --request-id/--all, --dry-run, --keep and --expect-sha256")
        if host == "antigravity" and not args.dry_run and args.all != bool(args.request_id):
            from lib.hosts.handoff import validated_scratch_slot
            from lib.task_pool import require_registered_scratch_keeps
            slot = None if args.all else validated_scratch_slot(args.request_id)
            base = handoff.cleanup_base(args.root, slot)
            target = base if slot is None else base / slot
            require_registered_scratch_keeps(args.root, target, records._scratch_keep_paths(tuple(args.keep)))
        try:
            return records.cleanup_scratch(args.root, args.request_id, remove_all=args.all,
                                           dry_run=args.dry_run, keep=tuple(args.keep), expected=args.expect_sha256,
                                           handoff=handoff)
        except records.ScratchCleanupError as exc:
            return exc.report
    if args.request_id or args.all:
        raise TaskGraphError("--request-id and --all apply only to scratch and cleanup-scratch")
    if args.command == "init":
        if args.root is None or args.output is None or any((args.patch, args.expect_sha256, args.task_id, args.select)):
            raise TaskGraphError("init requires --root and an explicit new --output; accepts only --input")
        if __package__:
            from .task_graph_init import initialize
        else:
            from task_graph_init import initialize
        body = records.read_record(args.input) if args.input else sys.stdin.buffer.read()
        return initialize(records.decode(body), args.root, args.output,
                          lambda command, graph: _execute(command, graph, root=args.root),
                          input_path=args.input, input_body=body)
    body = records.read_record(args.input) if args.input else sys.stdin.buffer.read()
    payload = records.decode(body)
    if args.command == "fingerprints":
        if args.root is None or any((args.patch, args.output, args.task_id, args.expect_sha256)):
            raise TaskGraphError("fingerprints requires --root and accepts only --input/--select")
        if args.check_command:
            if not args.input or args.select or not isinstance(payload, dict) or "task" not in payload:
                raise TaskGraphError("--check-command requires the current single Task Pack and no --select")
            _execute("validate", payload, root=args.root)
            previous = records.decode(records.read_record(args.source)) if args.source else None
            if args.source and not isinstance(previous, dict):
                raise TaskGraphError("previous command fingerprints require an object")
            return command_fingerprints(args.root, payload, args.check_command, previous)
        return records.fingerprints(args.root, payload, args.select)
    if not args.input:
        raise TaskGraphError("update/task requires an existing --input graph")
    if not isinstance(payload, dict):
        raise TaskGraphError("task graph input must be a JSON object")
    if args.pm_id is not None and not is_standalone_prototype(payload):
        raise TaskGraphError("--pm-id applies only to standalone prototype task export")
    _execute("validate", payload, root=args.root)
    if args.command == "update":
        if not args.patch or not args.expect_sha256 or any((args.output, args.task_id, args.select)):
            raise TaskGraphError("update requires --patch and --expect-sha256; no task output is implicit")
        if records.digest(body) != args.expect_sha256:
            raise TaskGraphError("graph fingerprint differs from --expect-sha256")
        patch_body = sys.stdin.buffer.read() if args.patch == "-" else records.read_record(Path(args.patch))
        patch = records.decode(patch_body)
        return publish_task_update(args.input, args.root, payload, body, args.expect_sha256, patch,
                                   policy=dispatch_policy())
    if any((args.patch, args.select)):
        raise TaskGraphError("task accepts only --input, --task-id and explicit output options")
    if "task" in payload:
        if args.task_id or payload["task"].get("workflow_level") != "Light":
            raise TaskGraphError("single-pack task input requires Light and no --task-id")
        # 独立包同时是 Light 权威记录，validate/ready 允许保留待决定稿；task 是
        # Writer 交接出口，因此发布前必须核实每个当前方案均已获批。
        snapshot = pack_snapshot(payload)
        validate_decisions(snapshot, for_handoff=True)
        task_intent.check_delivery(snapshot, snapshot["tasks"][0])
        require_writer(snapshot, snapshot["tasks"][0], args.root)
        if is_standalone_prototype(payload):
            if not args.pm_id or "claim_basis_sha256" not in payload["task"] or payload["task"]["state"] in task_intent.PENDING:
                raise TaskGraphError("standalone prototype handoff requires --pm-id and its claimed original pack")
            from lib.task_pool import check_handoff
            check_handoff(project_root(args.root), args.pm_id, args.input, records.digest(body))
        exported = replace_pack_task(payload, task_intent.handoff_task(snapshot["tasks"][0]))
    else:
        if not args.task_id:
            raise TaskGraphError("graph task export requires --task-id")
        exported = export_task_pack(payload, args.task_id, root=args.root)
    if args.source:
        # Light 没有权威图。仅从明示的同请求 Writer 原包派生可读批准，去掉模板里
        # 已经过时的决定。验收前仍可用 verify-solution-scope 对比这两份原始来源。
        source_body = records.read_record(args.source)
        source = records.decode(source_body)
        _execute("validate", source, root=args.root)
        writer = source.get("task", {})
        if (exported["task"].get("workflow_level") != "Light" or exported["task"]["task_type"] != "qa"
                or writer.get("workflow_level") != "Light" or writer.get("task_type") != "writer"
                or writer["request_id"] != exported["task"]["request_id"]):
            raise TaskGraphError("--source for task requires a Light QA and its same-request Light Writer")
        task_intent.check_delivery(pack_snapshot(source), writer)
        if writer.get("solution_decisions"):
            from lib.shared_solution_records import filter_ready
            if not filter_ready(args.source, [writer], [writer["id"]]):
                raise TaskGraphError("QA export requires current shared solution approvals")
        for field, rows in (("reviewed_solution_decisions", reviewed_solutions([writer], source)),
                            ("reviewed_business_confirmations", reviewed_business_confirmations([writer]))):
            if rows:
                exported[field] = rows
            else:
                exported.pop(field, None)
        # 只带入此 Writer 真正采用且已经批准的门；QA 模板上独立的自身门继续保留。
        wanted = set(writer.get("gates", [])) | {row["approval_gate"] for row in exported.get("reviewed_solution_decisions", [])}
        exported["approved_gates"] = sorted((wanted & set(source.get("approved_gates", [])))
                                            | (set(exported["task"].get("gates", [])) & set(exported.get("approved_gates", []))))
        sources = {gate: value for gate, value in source.get("solution_approval_sources", {}).items() if gate in wanted}
        if sources:
            exported["solution_approval_sources"] = sources
        else:
            exported.pop("solution_approval_sources", None)
        _verify_solution_scope(exported, source)
        if records.read_record(args.source) != source_body:
            raise TaskGraphError("Light Writer changed during QA export")
    if exported["task"].get("solution_decisions"):
        from lib.shared_solution_records import filter_ready
        chosen = exported["task"]
        if not filter_ready(args.input, [chosen], [chosen["id"]]):
            raise TaskGraphError("task requires current shared solution approval in every registered record")
    if args.output is None:
        if args.expect_sha256:
            raise TaskGraphError("--expect-sha256 requires an explicit --output")
        return exported
    if args.source and args.output.resolve() == args.source.resolve():
        raise TaskGraphError("QA export must preserve its original Light Writer")
    if (args.output.resolve() == args.input.resolve()
            or (args.output.exists() and args.output.samefile(args.input)) or not args.expect_sha256):
        raise TaskGraphError("task output must differ from graph and requires --expect-sha256 (or missing)")
    new_body = (json.dumps(exported, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if records.read_record(args.input) != body:
        raise TaskGraphError("graph changed during task export")
    # Light 原件与导出的交接包外形相同。原件已通过 AGY 领取及绑定时，允许
    # 合法地用最新同实例的引用刷新旧交接包；旧文件中的未证实身份不能据此变成新绑定。
    original = payload["task"] if "task" in payload else next(t for t in payload["tasks"] if t["id"] == args.task_id)
    changed = records.publish(args.output, new_body, args.expect_sha256,
                              bound_export=bound_export_reference(original), policy=dispatch_policy())
    return {"exported": changed, "sha256": records.digest(new_body), "graph_sha256": records.digest(body)}


if __name__ == "__main__":
    raise SystemExit(main())
