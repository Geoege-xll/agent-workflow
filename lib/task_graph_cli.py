#!/usr/bin/env python3
"""通过 JSON 快照为 PM 提供确定性的任务图门禁。

原有查询保持只读；显式 update/task 操作可更新内部快照或导出任务包，不派发
Agent、不运行验证、不写项目计划，也不生成批准或 QA 结论。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .worktree_policy import WorktreePolicyError, integration_ready, validate_execution
    from .standard_paths import canonical_standard_path, standard_domain
    from .task_graph import (
        Task,
        TaskGraphError,
        effective_dispatch_capacity,
        qa_ready,
        ready_tasks,
        validate_graph,
    )
except ImportError:
    from worktree_policy import WorktreePolicyError, integration_ready, validate_execution
    from standard_paths import canonical_standard_path, standard_domain
    from task_graph import (  # type: ignore[no-redef]
        Task,
        TaskGraphError,
        effective_dispatch_capacity,
        qa_ready,
        ready_tasks,
        validate_graph,
    )


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
PLAN_ONLY_FIELDS = {
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
    "standards_exceptions",
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and evaluate a PM task graph JSON snapshot.")
    parser.add_argument(
        "command",
        choices=("validate", "ready", "qa-ready", "capacity", "update", "task", "fingerprints", "scratch", "cleanup-scratch"),
    )
    parser.add_argument("--input", type=Path, help="JSON file; omit to read UTF-8 JSON from stdin")
    parser.add_argument("--patch", help="update patch JSON file, or - for stdin")
    parser.add_argument("--expect-sha256", help="required old output fingerprint for writes; missing for new task output")
    parser.add_argument("--task-id", help="existing task to export")
    parser.add_argument("--output", type=Path, help="explicit task-pack output; never created by default")
    parser.add_argument("--root", type=Path, help="explicit root for selected file fingerprints or scratch workspace")
    parser.add_argument("--select", action="append", default=[], help="select an existing receipt fingerprint-map field")
    parser.add_argument("--request-id", help="request identifier for deterministic scratch workspace allocation/cleanup")
    parser.add_argument("--all", action="store_true", help="clean all managed scratch workspaces for the project root")
    return parser


def _read_payload(path: Path | None) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8") if path is not None else sys.stdin.read()
        value = json.loads(raw)
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
    if not isinstance(fingerprint, str) or not SHA256_RE.fullmatch(fingerprint):
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
        if leaf_path.casefold() in {path.casefold() for path in leaves}:
            raise TaskGraphError("standards_contract.leaves must not duplicate paths")
        domain = raw_leaf["domain"]
        if domain not in {"engineering", "design"}:
            raise TaskGraphError(f"{label}.domain must be engineering or design")
        if not canonical_standard_path(leaf_path, root) or standard_domain(leaf_path, root) != domain:
            raise TaskGraphError(f"{label}.path must be a direct {domain} Markdown leaf inside {root}")
        leaf_fingerprint = raw_leaf["content_fingerprint"]
        if not isinstance(leaf_fingerprint, str) or not SHA256_RE.fullmatch(
            leaf_fingerprint
        ):
            raise TaskGraphError(f"{label}.content_fingerprint must be lowercase SHA-256")
        leaf_rule_ids = _stable_id_list(raw_leaf["rule_ids"], f"{label}.rule_ids")
        if not leaf_rule_ids:
            raise TaskGraphError(f"{label}.rule_ids must not be empty")
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
    if value["adapter"] != "project.yaml":
        raise TaskGraphError(
            f"tasks[{index}].controlled_document_access.adapter must be 'project.yaml'"
        )
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
        # 每条规范读取都必须验证，不能因领域不在 required_domains 中便静默过滤。
        # 原型是单独的证据分支；其余旧目录/未知叶子不允许假装普通文档加入读集合。
        standards_root = standards_contract["root"]
        if _is_within(path.casefold(), standards_root.casefold()):
            prototype_root = f"{standards_root}/prototype"
            if not _is_within(path, prototype_root):
                leaf = standards_contract["leaves"].get(path)
                if not canonical_standard_path(path, standards_root) or leaf is None:
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
    if len(index_documents) != 1:
        raise TaskGraphError(
            f"tasks[{index}] must include configured STANDARDS index exactly once"
        )
    index_document = index_documents[0]
    if index_document["mode"] == "skip":
        raise TaskGraphError(f"tasks[{index}] must not skip the STANDARDS index")
    if index_document["content_fingerprint"] != standards_contract["index_fingerprint"]:
        raise TaskGraphError(f"tasks[{index}] STANDARDS index fingerprint does not match contract")
    if index_document["rule_ids"]:
        raise TaskGraphError(f"tasks[{index}] STANDARDS index must not claim leaf rule IDs")

    owned_paths = tuple(
        _safe_relative_path(item, f"tasks[{index}].owned_paths[{position}]")
        for position, item in enumerate(
            _string_list(raw["owned_paths"], f"tasks[{index}].owned_paths")
        )
    )
    for owned_path in owned_paths:
        if not any(
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
            if standard_domain(document["path"], standards_contract["root"]) == domain
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

    # GENERAL 是生产代码任务的基础工程叶；只验证其他工程叶的路径与规则覆盖，
    # 会让任务包绕过通用规范。原型设计任务仍仅使用设计叶。
    if "engineering" in required_domains:
        baseline_path = f"{standards_contract['root']}/GENERAL.md"
        if baseline_path not in standards_contract["leaves"]:
            raise TaskGraphError(
                f"tasks[{index}] production writer requires GENERAL.md baseline in standards_contract"
            )
        baseline_document = next(
            (
                document
                for document in normalized_documents
                if document["path"] == baseline_path and document["mode"] != "skip"
            ),
            None,
        )
        if baseline_document is None:
            raise TaskGraphError(
                f"tasks[{index}] production writer requires selected GENERAL.md baseline"
            )
        for owned_path in owned_paths:
            if not any(
                _is_within(owned_path, access_path)
                for access_path in baseline_document["applies_to"]
            ):
                raise TaskGraphError(
                    f"tasks[{index}] GENERAL.md baseline does not cover owned path {owned_path!r}"
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
    if "surface_kind" not in raw:
        raise TaskGraphError(f"tasks[{index}] with role requires surface_kind")
    if "qa_scope" not in raw:
        raise TaskGraphError(f"tasks[{index}] with role requires qa_scope")
    if raw["qa_scope"] != "request":
        raise TaskGraphError(f"tasks[{index}].qa_scope must be 'request'")
    surface_kind = raw["surface_kind"]
    if surface_kind not in {"production_ui", "design_ui", "non_ui"}:
        raise TaskGraphError(f"tasks[{index}].surface_kind is unsupported: {surface_kind!r}")
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
        if role == "xy-uiux":
            raise TaskGraphError(f"tasks[{index}] production_ui cannot use role xy-uiux")
        if "ui_change" not in raw:
            raise TaskGraphError(f"tasks[{index}] production_ui requires ui_change")
        if not {"ui", "accessibility"}.issubset(audit_surfaces):
            raise TaskGraphError(
                f"tasks[{index}] production_ui requires ui and accessibility audit surfaces"
            )
        return

    if surface_kind == "design_ui":
        if role != "xy-uiux":
            raise TaskGraphError(f"tasks[{index}] design_ui must use role xy-uiux")
        if raw.get("task_type") != "writer":
            raise TaskGraphError(f"tasks[{index}] design_ui must be a writer")
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
    if "requirements_approved" not in gates:
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


def _tasks(payload: dict[str, Any]) -> list[Task]:
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
        _validate_plan_contract(raw, index, prototype_paths, design_standards_root)
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
        # 只有已进入正式调度快照的 Writer 必须声明需求确认依赖；非 UI 开发不能
        # 绕过 UI 分支已有的要求。只读调查和 QA 不新增门禁，Trivial 也不因此被
        # 强制物化为调度任务；真正的批准状态仍由 ready_tasks 按当前快照判断。
        if task_type == "writer" and "requirements_approved" not in gates:
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
            )
        )
    _validate_ui_dependencies(typed_raw_tasks, prototype_paths)
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


def _execute(command: str, payload: dict[str, Any]) -> dict[str, Any]:
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

    tasks = _tasks(payload)
    validate_graph(tasks)
    validate_execution(payload)
    if command == "validate":
        return {"status": "valid"}
    if command == "ready":
        return {
            "ready": ready_tasks(
                tasks,
                approved_gates=set(
                    _string_list(payload.get("approved_gates"), "approved_gates")
                ),
                active_paths=set(_string_list(payload.get("active_paths"), "active_paths")),
                active_semantic_locks=set(
                    _string_list(
                        payload.get("active_semantic_locks"), "active_semantic_locks"
                    )
                ),
                capacity=_nonnegative_integer(payload, "capacity"),
            )
        }
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TaskGraphError("request_id must be a non-empty string")
    # 分支各自验证成功不等于组合正确；只有 worktree 分支额外检查集成证据。
    return {"qa_ready": qa_ready(tasks, request_id) and integration_ready(payload, request_id),
            "request_id": request_id}


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command in {"update", "task", "fingerprints", "scratch", "cleanup-scratch"}:
            result = _record_command(args)
        else:
            if any((args.patch, args.expect_sha256, args.task_id, args.output, args.root, args.select, args.request_id, args.all)):
                raise TaskGraphError("record-operation options do not apply to read-only queries")
            result = _execute(args.command, _read_payload(args.input))
    except (TaskGraphError, WorktreePolicyError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.command == "fingerprints" and not result["matched"]:
        return 1
    return 0


def _record_command(args: argparse.Namespace) -> dict[str, Any]:
    """按需加载记录工具，不改变现有纯计算 API 或只读查询的输出。"""
    if __package__:
        from . import task_graph_records as records
    else:
        import task_graph_records as records
    if args.command == "scratch":
        if args.root is None or any((args.input, args.patch, args.expect_sha256, args.task_id, args.output, args.select, args.all)):
            raise TaskGraphError("scratch requires --root and accepts only --request-id")
        return records.scratch_workspace(args.root, args.request_id)
    if args.command == "cleanup-scratch":
        if args.root is None or any((args.input, args.patch, args.expect_sha256, args.task_id, args.output, args.select)):
            raise TaskGraphError("cleanup-scratch requires --root and accepts only --request-id or --all")
        return records.cleanup_scratch(args.root, args.request_id, remove_all=args.all)
    if args.request_id or args.all:
        raise TaskGraphError("--request-id and --all apply only to scratch and cleanup-scratch")
    body = records.read_record(args.input) if args.input else sys.stdin.buffer.read()
    payload = records.decode(body)
    if args.command == "fingerprints":
        if args.root is None or any((args.patch, args.output, args.task_id, args.expect_sha256)):
            raise TaskGraphError("fingerprints requires --root and accepts only --input/--select")
        return records.fingerprints(args.root, payload, args.select)
    if not args.input:
        raise TaskGraphError("update/task requires an existing --input graph")
    if not isinstance(payload, dict):
        raise TaskGraphError("task graph input must be a JSON object")
    _execute("validate", payload)
    if args.command == "update":
        if not args.patch or not args.expect_sha256 or any((args.output, args.task_id, args.select)):
            raise TaskGraphError("update requires --patch and --expect-sha256; no task output is implicit")
        if records.digest(body) != args.expect_sha256:
            raise TaskGraphError("graph fingerprint differs from --expect-sha256")
        patch_body = sys.stdin.buffer.read() if args.patch == "-" else records.read_record(Path(args.patch))
        updated = records.update(payload, records.decode(patch_body), args.root, _execute)
        new_body = body if updated == payload else (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        changed = records.publish(args.input, new_body, args.expect_sha256)
        return {"updated": changed, "sha256": records.digest(new_body)}
    if not args.task_id or any((args.patch, args.root, args.select)):
        raise TaskGraphError("task requires --task-id and accepts only explicit output options")
    matches = [task for task in payload["tasks"] if task["id"] == args.task_id]
    if len(matches) != 1:
        raise TaskGraphError(f"unknown task ID: {args.task_id}")
    if args.output is None:
        if args.expect_sha256:
            raise TaskGraphError("--expect-sha256 requires an explicit --output")
        return matches[0]
    if (args.output.resolve() == args.input.resolve()
            or (args.output.exists() and args.output.samefile(args.input)) or not args.expect_sha256):
        raise TaskGraphError("task output must differ from graph and requires --expect-sha256 (or missing)")
    new_body = (json.dumps(matches[0], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if records.read_record(args.input) != body:
        raise TaskGraphError("graph changed during task export")
    changed = records.publish(args.output, new_body, args.expect_sha256)
    return {"exported": changed, "sha256": records.digest(new_body), "graph_sha256": records.digest(body)}


if __name__ == "__main__":
    raise SystemExit(main())
