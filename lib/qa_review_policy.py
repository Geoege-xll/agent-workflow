#!/usr/bin/env python3
"""Validate the pack's single-reviewer QA method policy."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

# CLI 和包导入使用相同的契约读取实现，避免测试入口与安装入口行为不一致。
if __package__:
    from .business_confirmation_policy import read_instruction_contract
else:
    from business_confirmation_policy import read_instruction_contract


METHODS = (
    "host-native-review",
    "installed-code-review-skill",
    "internal-xy-qa-procedure",
)

POLICY_BLOCK = """qa_review_policy:
  owner: xy-qa
  max_active_reviewers: 1
  method_selection_order:
    - host-native-review
    - installed-code-review-skill
    - internal-xy-qa-procedure
  external_skill_selection: installed-and-capable-only
  superpowers_prompt: requesting-code-review/code-reviewer.md
  fallback_on_technical_unavailability_only: true
  findings_or_fail_do_not_trigger_fallback: true"""

METHOD_CLAUSE = (
    "`host-native-review`, then one `installed-code-review-skill` proven installed and capable, "
    "then `internal-xy-qa-procedure`, moving forward only on technical unavailability."
)

RETIRED_TERMS = (
    "xy-qa-" + "direct-review",
    "superpowers-" + "requesting-code-review",
    "review_" + "provider",
    "max_active_" + "providers",
    "fallback_on_" + "provider_failure_only",
)

MACHINE_AUTHORITIES = (
    "product/WORKFLOW.md",
    "product/AGENT_SCHEMA.md",
    "platforms/shared/skills/xy-qa-review/SKILL.md",
)

PROSE_AUTHORITIES = (
    "platforms/shared/skills/xy-workflow/SKILL.md",
    "platforms/claude/AGENTS.claude.tpl",
    "platforms/codex/AGENTS.codex.tpl",
    "platforms/antigravity/AGENTS.antigravity.tpl",
)

ACTIVE_ROOTS = ("lib", "platforms", "product", "roles", "scripts", "templates")
ACTIVE_ROOT_FILES = (
    "README.md",
    "project.yaml",
    "setup_all.sh",
    "setup_codex.sh",
    "setup_claude.sh",
    "setup_antigravity.sh",
)


def _read_regular(pack: Path, relative: str, errors: list[str]) -> str | None:
    path = pack / relative
    try:
        info = path.lstat()
    except OSError as exc:
        errors.append(f"QA review policy source is unavailable: {relative}: {exc}")
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        errors.append(f"QA review policy source must be a single-link regular file: {relative}")
        return None
    try:
        # 渐进加载的规则必须连同入口一起审计，不能因正文搬进 references 而漏检。
        return read_instruction_contract(pack, relative)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"QA review policy source is unreadable UTF-8: {relative}: {exc}")
        return None


def _machine_policy_errors(relative: str, body: str) -> list[str]:
    policy_tokens = re.findall(
        r"(?<![A-Za-z0-9_])qa_review_policy(?![A-Za-z0-9_])",
        body,
    )
    if len(policy_tokens) != 1:
        return [
            f"{relative} must contain exactly one qa_review_policy token; "
            f"found {len(policy_tokens)}"
        ]
    headers = re.findall(r"(?m)^[ \t]*qa_review_policy:[ \t]*$", body)
    if len(headers) != 1:
        return [f"{relative} must contain exactly one qa_review_policy header"]
    blocks = [
        match.group(0).rstrip()
        for match in re.finditer(r"(?m)^qa_review_policy:\n(?:(?:  .*)\n?)+", body)
    ]
    if blocks != [POLICY_BLOCK]:
        return [f"{relative} must contain exactly one canonical qa_review_policy block"]
    return []


def _prose_policy_errors(relative: str, body: str) -> list[str]:
    normalized = " ".join(body.split())
    errors: list[str] = []
    if normalized.count(METHOD_CLAUSE) != 1:
        errors.append(f"{relative} must contain exactly one canonical QA review-method clause")
    for method in METHODS:
        if normalized.count(method) != 1:
            errors.append(f"{relative} must contain exactly one QA review method {method}")
    for phrase in (
        "Findings or `FAIL` never switch review method or reviewer",
        "requesting-code-review/code-reviewer.md",
        "Grill Me remains requirements-only",
    ):
        if phrase not in normalized:
            errors.append(f"{relative} missing QA review-method boundary: {phrase}")
    return errors


def _active_files(pack: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative in ACTIVE_ROOT_FILES:
        path = pack / relative
        if path.is_file():
            files.append(path)
    for relative in ACTIVE_ROOTS:
        root = pack / relative
        if not root.is_dir():
            continue
        for current, directories, names in os.walk(root, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name
                for name in directories
                if name != "__pycache__" and not (current_path / name).is_symlink()
            ]
            for name in names:
                if name.endswith((".pyc", ".pyo")):
                    continue
                path = current_path / name
                try:
                    info = path.lstat()
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    files.append(path)
    return tuple(sorted(set(files)))


def validate_pack_qa_review_policy(pack: Path) -> tuple[str, ...]:
    """Return deterministic policy errors for current source authorities."""

    pack = Path(pack)
    errors: list[str] = []
    for relative in MACHINE_AUTHORITIES:
        body = _read_regular(pack, relative, errors)
        if body is not None:
            errors.extend(_machine_policy_errors(relative, body))
    for relative in PROSE_AUTHORITIES:
        body = _read_regular(pack, relative, errors)
        if body is not None:
            errors.extend(_prose_policy_errors(relative, body))

    encoded_terms = tuple((term, term.encode("utf-8")) for term in RETIRED_TERMS)
    for path in _active_files(pack):
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(f"cannot scan active QA policy source {path.relative_to(pack)}: {exc}")
            continue
        for term, encoded in encoded_terms:
            if encoded in data:
                errors.append(f"retired QA policy term {term} remains in {path.relative_to(pack)}")

    return tuple(errors)
