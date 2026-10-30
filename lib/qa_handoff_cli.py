#!/usr/bin/env python3
"""确定性验证 QA handoff 的固定审计范围与统一规范覆盖证据。

该工具只读取内部 JSON 并返回验证结果，不修改项目文件，也不向用户展示原始覆盖表。
自然语言 QA 结论只有在这份内部证据通过校验后，才可以被 PM 接受为最终 PASS。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .standard_paths import canonical_standard_path, standard_domain
except ImportError:
    from standard_paths import canonical_standard_path, standard_domain


SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
STABLE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
REPOSITORY_FIELDS = {
    "path",
    "base_revision",
    "head_revision",
    "diff_fingerprint",
    "changed_paths",
}
PATH_CHECK_FIELDS = {"path", "applicable_rule_ids", "reason"}
RULE_CHECK_FIELDS = {
    "rule_id",
    "source_path",
    "source_fingerprint",
    "source_anchor",
    "domain",
    "severity",
    "disposition",
    "affected_paths",
    "evidence_refs",
    "not_applicable_reason",
    "exception_ref",
}
STANDARDS_COVERAGE_FIELDS = {
    "index_path",
    "root",
    "index_fingerprint",
    "task_pack_rule_ids",
    "required_engineering_rule_ids",
    "required_design_rule_ids",
    "path_checks",
    "rule_checks",
}


class QAHandoffError(ValueError):
    """QA handoff 缺少固定范围、规则覆盖或证据时抛出。"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate fixed QA scope and standards-policy coverage JSON."
    )
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--input", type=Path, help="JSON file; omit to read UTF-8 JSON from stdin")
    return parser


def _read_payload(path: Path | None) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8") if path is not None else sys.stdin.read()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QAHandoffError(f"cannot read QA handoff JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise QAHandoffError("QA handoff input must be a JSON object")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QAHandoffError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise QAHandoffError(f"{label} must be an array")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QAHandoffError(f"{label} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, label: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    raw = _array(value, label)
    if not all(isinstance(item, str) and item.strip() for item in raw):
        raise QAHandoffError(f"{label} must contain non-empty strings")
    values = tuple(item.strip() for item in raw)
    if not allow_empty and not values:
        raise QAHandoffError(f"{label} must not be empty")
    if len(set(values)) != len(values):
        raise QAHandoffError(f"{label} must not contain duplicates")
    return values


def _safe_project_path(value: Any, label: str) -> str:
    """规范化项目相对路径；审计范围中的仓库根 `.` 由调用方单独处理。"""

    raw = _nonempty_string(value, label)
    if "\\" in raw:
        raise QAHandoffError(f"{label} must use forward slashes")
    normalized = raw.rstrip("/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or not normalized
        or any(part in {"", ".", ".."} for part in path.parts)
        or normalized != path.as_posix()
    ):
        raise QAHandoffError(f"{label} must be a normalized project-relative path")
    return path.as_posix()


def _is_within(path: str, boundary: str) -> bool:
    if boundary == ".":
        return True
    path_parts = PurePosixPath(path).parts
    boundary_parts = PurePosixPath(boundary).parts
    return len(path_parts) >= len(boundary_parts) and (
        path_parts[: len(boundary_parts)] == boundary_parts
    )


def _stable_ids(value: Any, label: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    values = _string_list(value, label, allow_empty=allow_empty)
    if any(not STABLE_ID_RE.fullmatch(item) for item in values):
        raise QAHandoffError(f"{label} contains an invalid stable rule ID")
    return values


def _validate_scope(review_method: dict[str, Any]) -> tuple[str, ...]:
    """冻结每个仓库自己的 base/head 与 diff 指纹，避免子仓库已提交改动从 QA 消失。"""

    _nonempty_string(review_method.get("selected"), "review_method.selected")
    scope_ref = _object(review_method.get("scope_ref"), "review_method.scope_ref")
    repositories = _array(
        scope_ref.get("repositories"), "review_method.scope_ref.repositories"
    )
    if not repositories:
        raise QAHandoffError("review_method.scope_ref.repositories must not be empty")

    changed_paths: list[str] = []
    seen_repositories: set[str] = set()
    for position, raw_repository in enumerate(repositories):
        label = f"review_method.scope_ref.repositories[{position}]"
        repository = _object(raw_repository, label)
        missing = REPOSITORY_FIELDS - set(repository)
        unknown = set(repository) - REPOSITORY_FIELDS
        if missing:
            raise QAHandoffError(f"{label} is missing field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise QAHandoffError(
                f"{label} has unsupported field(s): {', '.join(sorted(unknown))}"
            )
        raw_path = _nonempty_string(repository["path"], f"{label}.path")
        repository_path = "." if raw_path == "." else _safe_project_path(raw_path, f"{label}.path")
        if repository_path in seen_repositories:
            raise QAHandoffError("review_method.scope_ref.repositories must not duplicate paths")
        seen_repositories.add(repository_path)
        _nonempty_string(repository["base_revision"], f"{label}.base_revision")
        _nonempty_string(repository["head_revision"], f"{label}.head_revision")
        fingerprint = repository["diff_fingerprint"]
        if not isinstance(fingerprint, str) or not SHA256_RE.fullmatch(fingerprint):
            raise QAHandoffError(f"{label}.diff_fingerprint must be lowercase SHA-256")
        repository_changes = tuple(
            _safe_project_path(item, f"{label}.changed_paths[{item_position}]")
            for item_position, item in enumerate(
                _string_list(repository["changed_paths"], f"{label}.changed_paths")
            )
        )
        if any(not _is_within(item, repository_path) for item in repository_changes):
            raise QAHandoffError(f"{label}.changed_paths must stay inside its repository path")
        changed_paths.extend(repository_changes)

    if not changed_paths:
        raise QAHandoffError("review_method.scope_ref must include at least one changed path")
    if len(set(changed_paths)) != len(changed_paths):
        raise QAHandoffError("review_method.scope_ref changed paths must not overlap repositories")
    return tuple(changed_paths)


def _validate_standards_coverage(
    coverage: dict[str, Any], changed_paths: tuple[str, ...], audit_result: str
) -> None:
    """逐条验证规范索引、叶规则、变更路径和证据的闭合关系。

    QA 必须独立声明真实适用规则。若 PM Task Pack 漏掉其中任何规则，FAIL 可以
    如实交接，但 PASS 会被拒绝，避免 QA 静默补读后掩盖派发合同缺陷。
    """

    missing_fields = STANDARDS_COVERAGE_FIELDS - set(coverage)
    unknown_fields = set(coverage) - STANDARDS_COVERAGE_FIELDS
    if missing_fields:
        raise QAHandoffError(
            "standards_policy_coverage is missing field(s): "
            + ", ".join(sorted(missing_fields))
        )
    if unknown_fields:
        raise QAHandoffError(
            "standards_policy_coverage has unsupported field(s): "
            + ", ".join(sorted(unknown_fields))
        )

    index_path = _safe_project_path(
        coverage["index_path"], "standards_policy_coverage.index_path"
    )
    standards_root = _safe_project_path(
        coverage["root"], "standards_policy_coverage.root"
    )
    if _is_within(index_path, standards_root):
        raise QAHandoffError(
            "standards_policy_coverage.index_path must stay outside its root"
        )
    index_fingerprint = coverage["index_fingerprint"]
    if not isinstance(index_fingerprint, str) or not SHA256_RE.fullmatch(
        index_fingerprint
    ):
        raise QAHandoffError(
            "standards_policy_coverage.index_fingerprint must be lowercase SHA-256"
        )
    task_pack_rule_ids = set(
        _stable_ids(
            coverage["task_pack_rule_ids"],
            "standards_policy_coverage.task_pack_rule_ids",
        )
    )
    required_engineering_rule_ids = _stable_ids(
        coverage["required_engineering_rule_ids"],
        "standards_policy_coverage.required_engineering_rule_ids",
    )
    required_design_rule_ids = _stable_ids(
        coverage["required_design_rule_ids"],
        "standards_policy_coverage.required_design_rule_ids",
    )
    required_rule_ids = set(required_engineering_rule_ids) | set(required_design_rule_ids)
    duplicated_domain_ids = set(required_engineering_rule_ids) & set(required_design_rule_ids)
    if duplicated_domain_ids:
        raise QAHandoffError(
            "engineering and design required rule IDs must be disjoint: "
            + ", ".join(sorted(duplicated_domain_ids))
        )
    if not required_rule_ids:
        raise QAHandoffError(
            "standards_policy_coverage must declare at least one independently applicable rule"
        )

    raw_rule_checks = _array(
        coverage["rule_checks"], "standards_policy_coverage.rule_checks"
    )
    rule_checks: dict[str, dict[str, Any]] = {}
    for position, raw_check in enumerate(raw_rule_checks):
        label = f"standards_policy_coverage.rule_checks[{position}]"
        check = _object(raw_check, label)
        missing = RULE_CHECK_FIELDS - set(check)
        unknown = set(check) - RULE_CHECK_FIELDS
        if missing:
            raise QAHandoffError(f"{label} is missing field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise QAHandoffError(
                f"{label} has unsupported field(s): {', '.join(sorted(unknown))}"
            )
        rule_id = _nonempty_string(check["rule_id"], f"{label}.rule_id")
        if not STABLE_ID_RE.fullmatch(rule_id):
            raise QAHandoffError(f"{label}.rule_id has an invalid stable identifier")
        if rule_id in rule_checks:
            raise QAHandoffError(
                "standards_policy_coverage.rule_checks must not duplicate rule IDs"
            )
        source_path = _safe_project_path(check["source_path"], f"{label}.source_path")
        source_fingerprint = check["source_fingerprint"]
        if not isinstance(source_fingerprint, str) or not SHA256_RE.fullmatch(
            source_fingerprint
        ):
            raise QAHandoffError(f"{label}.source_fingerprint must be lowercase SHA-256")
        domain = check["domain"]
        if domain not in {"engineering", "design"}:
            raise QAHandoffError(f"{label}.domain must be engineering or design")
        # 扁平路径仍保留类型约束，不能通过改写 domain 将工程规范伪装成设计规范。
        if not canonical_standard_path(source_path, standards_root) or standard_domain(source_path, standards_root) != domain:
            raise QAHandoffError(
                f"{label}.source_path must be a direct {domain} Markdown leaf inside {standards_root}"
            )
        source_anchor = _nonempty_string(check["source_anchor"], f"{label}.source_anchor")
        severity = check["severity"]
        if severity not in {"hard", "advisory"}:
            raise QAHandoffError(f"{label}.severity must be hard or advisory")
        disposition = check["disposition"]
        if disposition not in {"pass", "fail", "not_applicable"}:
            raise QAHandoffError(
                f"{label}.disposition must be pass, fail, or not_applicable"
            )
        affected_paths = tuple(
            _safe_project_path(item, f"{label}.affected_paths[{item_position}]")
            for item_position, item in enumerate(
                _string_list(check["affected_paths"], f"{label}.affected_paths")
            )
        )
        unknown_paths = sorted(set(affected_paths) - set(changed_paths))
        if unknown_paths:
            raise QAHandoffError(
                f"{label}.affected_paths contains paths outside fixed scope: "
                f"{', '.join(unknown_paths)}"
            )
        evidence_refs = _string_list(check["evidence_refs"], f"{label}.evidence_refs")
        not_applicable_reason = check["not_applicable_reason"]
        exception_ref = check["exception_ref"]
        if not isinstance(not_applicable_reason, str) or not isinstance(exception_ref, str):
            raise QAHandoffError(
                f"{label}.not_applicable_reason and exception_ref must be strings"
            )
        if disposition == "not_applicable":
            if not not_applicable_reason.strip():
                raise QAHandoffError(f"{label}.not_applicable_reason must explain N/A")
            if affected_paths:
                raise QAHandoffError(f"{label} not_applicable must not claim affected_paths")
        else:
            if not affected_paths:
                raise QAHandoffError(f"{label} {disposition} requires affected_paths")
            if not evidence_refs:
                raise QAHandoffError(f"{label} {disposition} requires evidence_refs")
        rule_checks[rule_id] = {
            "source_path": source_path,
            "source_fingerprint": source_fingerprint,
            "source_anchor": source_anchor,
            "domain": domain,
            "severity": severity,
            "disposition": disposition,
            "affected_paths": affected_paths,
        }

    missing_required = sorted(required_rule_ids - set(rule_checks))
    if missing_required:
        raise QAHandoffError(
            "missing required standards rule check(s): " + ", ".join(missing_required)
        )
    wrong_domain_rules = sorted(
        rule_id
        for rule_id in required_engineering_rule_ids
        if rule_checks[rule_id]["domain"] != "engineering"
    ) + sorted(
        rule_id
        for rule_id in required_design_rule_ids
        if rule_checks[rule_id]["domain"] != "design"
    )
    if wrong_domain_rules:
        raise QAHandoffError(
            "required standards rule has the wrong domain: "
            + ", ".join(wrong_domain_rules)
        )
    # 同一叶文档在一次冻结审计中只能有一个内容版本；否则不同规则可能来自不同时间点。
    fingerprints_by_path: dict[str, str] = {}
    for rule in rule_checks.values():
        previous = fingerprints_by_path.setdefault(
            rule["source_path"], rule["source_fingerprint"]
        )
        if previous != rule["source_fingerprint"]:
            raise QAHandoffError(
                "standards leaf uses inconsistent source fingerprints: "
                + rule["source_path"]
            )

    raw_path_checks = _array(
        coverage["path_checks"], "standards_policy_coverage.path_checks"
    )
    path_checks: dict[str, tuple[str, ...]] = {}
    for position, raw_check in enumerate(raw_path_checks):
        label = f"standards_policy_coverage.path_checks[{position}]"
        check = _object(raw_check, label)
        missing = PATH_CHECK_FIELDS - set(check)
        unknown = set(check) - PATH_CHECK_FIELDS
        if missing:
            raise QAHandoffError(f"{label} is missing field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise QAHandoffError(
                f"{label} has unsupported field(s): {', '.join(sorted(unknown))}"
            )
        path = _safe_project_path(check["path"], f"{label}.path")
        if path in path_checks:
            raise QAHandoffError("standards_policy_coverage.path_checks must not duplicate paths")
        applicable = _stable_ids(check["applicable_rule_ids"], f"{label}.applicable_rule_ids")
        _nonempty_string(check["reason"], f"{label}.reason")
        unknown_rules = sorted(set(applicable) - set(rule_checks))
        if unknown_rules:
            raise QAHandoffError(
                f"{label} references unknown standards rule(s): {', '.join(unknown_rules)}"
            )
        for rule_id in applicable:
            rule = rule_checks[rule_id]
            if rule["disposition"] == "not_applicable":
                raise QAHandoffError(
                    f"{label} maps applicable rule {rule_id!r} to not_applicable"
                )
            if path not in rule["affected_paths"]:
                raise QAHandoffError(
                    f"{label} path is missing from rule {rule_id!r} affected_paths"
                )
        path_checks[path] = applicable

    if set(path_checks) != set(changed_paths):
        raise QAHandoffError(
            "standards_policy_coverage.path_checks must classify every changed path"
        )
    if audit_result == "PASS":
        missing_from_task_pack = sorted(required_rule_ids - task_pack_rule_ids)
        if missing_from_task_pack:
            raise QAHandoffError(
                "PASS cannot hide applicable rule(s) omitted from the PM Task Pack: "
                + ", ".join(missing_from_task_pack)
            )
        failed_hard_rules = sorted(
            rule_id
            for rule_id, rule in rule_checks.items()
            if rule["severity"] == "hard" and rule["disposition"] == "fail"
        )
        if failed_hard_rules:
            raise QAHandoffError(
                "PASS cannot contain hard standards rule failure(s): "
                + ", ".join(failed_hard_rules)
            )


def validate_qa_handoff(payload: dict[str, Any]) -> None:
    """验证 QA 内部结果；成功即返回，失败抛出稳定、可测试的错误。"""

    audit_result = payload.get("audit_result")
    if audit_result not in {"PASS", "FAIL"}:
        raise QAHandoffError("audit_result must be PASS or FAIL")
    review_method = _object(payload.get("review_method"), "review_method")
    changed_paths = _validate_scope(review_method)
    if "engineering_policy_coverage" in payload:
        raise QAHandoffError(
            "engineering_policy_coverage is unsupported after the direct STANDARDS upgrade"
        )
    coverage = _object(
        payload.get("standards_policy_coverage"), "standards_policy_coverage"
    )
    _validate_standards_coverage(coverage, changed_paths, audit_result)


def main() -> int:
    args = _parser().parse_args()
    try:
        payload = _read_payload(args.input)
        validate_qa_handoff(payload)
    except QAHandoffError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "valid"}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
