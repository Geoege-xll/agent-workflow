#!/usr/bin/env python3
"""Strictly validate Antigravity source, staged, and generated artifacts.

The parser intentionally supports only the small YAML subset emitted by this pack.  A
general YAML parser would make malformed or duplicate controlled fields too easy to
silently accept.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from business_confirmation_policy import read_instruction_contract, validate_business_confirmation_pack
from qa_review_policy import validate_pack_qa_review_policy
from validate_project_config import validate_with_profile
from skill_contracts import BOOTSTRAP_TARGETS, expand_bootstrap_contract, expand_skill_contract

from shared_core_skills import (
    SharedCoreSkillError,
    audit_managed_skill_root,
    load_shared_core_skills,
    parse_managed_skill_bytes,
    validate_stale_managed_skill_directory,
    validate_staged_shared_core_skills,
)


AGENT_MARKER = "<!-- agent-workflow-pack:managed-antigravity-agent -->"
PRODUCT_BEGIN = "<!-- pack:product-begin -->"
PRODUCT_END = "<!-- pack:product-end -->"
CODEX_BEGIN = "<!-- pack:codex-begin -->"
CODEX_END = "<!-- pack:codex-end -->"
ANTIGRAVITY_BEGIN = "<!-- pack:antigravity-begin -->"
ANTIGRAVITY_END = "<!-- pack:antigravity-end -->"
CLAUDE_BEGIN = "<!-- agent-workflow-pack:claude-begin -->"
CLAUDE_END = "<!-- agent-workflow-pack:claude-end -->"
MANAGED_BLOCK_MARKERS = {
    CLAUDE_BEGIN,
    CLAUDE_END,
    PRODUCT_BEGIN,
    PRODUCT_END,
    CODEX_BEGIN,
    CODEX_END,
    ANTIGRAVITY_BEGIN,
    ANTIGRAVITY_END,
}
AGENT_KEYS = {
    "name",
    "description",
    "tools",
    "mainAgent",
    "subagent",
    "model",
    "commandExecutionPolicy",
    "skills",
}
CORE_SKILLS = {
    "grill-me",
    "xy-workflow",
    "xy-plan",
    "xy-project-memory",
    "xy-build-verify",
    "xy-qa-review",
    "xy-prototype-verify",
}
IMPLEMENTER_ROLES = {
    "xy-web",
    "xy-desktop",
    "xy-backend",
    "xy-apple",
    "xy-android",
}

# Verified against the installed Antigravity desktop v2.7.1 frontmatter fields and
# embedded language_server tool registry.  The official Supported Tools reference is
# https://www.antigravity.google/docs/hooks.  These smaller exact sets are the approved
# project policy: UIUX can create design artifacts and research, while QA remains
# read-only. Collaboration, permission, scheduling, browser-subagent, and question
# tools are deliberately not granted to static role Agents.
IMPLEMENTER_TOOLS = (
    "view_file",
    "list_dir",
    "find_by_name",
    "grep_search",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "run_command",
    "manage_task",
)
UIUX_TOOLS = (
    "view_file",
    "list_dir",
    "find_by_name",
    "grep_search",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "run_command",
    "manage_task",
    "search_web",
    "read_url_content",
    "generate_image",
)
QA_TOOLS = (
    "view_file",
    "list_dir",
    "find_by_name",
    "grep_search",
    "run_command",
    "manage_task",
    "search_web",
    "read_url_content",
)
NESTED_DELEGATION_TOOLS = {
    "invoke_subagent",
    "define_subagent",
    "send_message",
}
ROLE_SKILLS = {
    **{role: ("skills/xy-build-verify",) for role in IMPLEMENTER_ROLES},
    "xy-uiux": ("skills/xy-prototype-verify",),
    "xy-qa": ("skills/xy-qa-review",),
}
ROLE_TOOLS = {
    **{role: IMPLEMENTER_TOOLS for role in IMPLEMENTER_ROLES},
    "xy-uiux": UIUX_TOOLS,
    "xy-qa": QA_TOOLS,
}
ALL_APPROVED_TOOLS = set().union(*map(set, ROLE_TOOLS.values()))
CANONICAL_ROLES = tuple(sorted(ROLE_TOOLS))

PRECEDENCE = (
    "Current controlled documents and explicit user approvals win over recalled memory."
)


LOCAL_NEGATION_PATTERN = re.compile(
    r"\b(?:must|should|may|can|do|does|is|are)\s+(?:strictly\s+)?not\b"
    r"|\b(?:doesn't|don't|shouldn't|mustn't|isn't|aren't|can't)\b"
    r"|\bnot\s+to\b|\binstructed\s+not\s+to\b"
    r"|\bnever\b|\bneither\b|\bforbidden\b|\bprohibited\b|\bcannot\b",
    re.I,
)
UI_ACTION_PATTERN = re.compile(
    r"production\s+UI(?P<polarity>[^.;!?]{0,100}?)"
    r"(?P<action>start|starts|begin|begins|implement|implements|implemented)\b"
    r"[^.;!?]{0,80}\bbefore\b[^.;!?]{0,100}"
    r"(?:Baseline\s+Proceed|IA\s+Proceed|Visual\s+Proceed|visual_approved|named\s+gate|approval)",
    re.I,
)
MEMORY_AUTHORITY_PATTERNS = (
    re.compile(
        r"(?:recalled\s+memory|agentmemory|memory)\b"
        r"(?P<polarity>[^.;!?]{0,80}?)"
        r"(?P<action>override(?:s)?|wins?\s+over|takes?\s+precedence\s+over)"
        r"[^.;!?]{0,100}(?:controlled|current\s+(?:project\s+)?documents?|user\s+approvals?)",
        re.I,
    ),
    re.compile(
        r"(?:recalled\s+memory|agentmemory|memory)\b"
        r"(?P<polarity>[^.;!?]{0,80}?)"
        r"(?P<action>has|have|is|becomes?)\s+(?:the\s+)?(?:approved\s+)?"
        r"(?:priority|authority|source\s+of\s+truth)"
        r"[^.;!?]{0,80}(?:controlled|current\s+(?:project\s+)?documents?|user\s+approvals?)",
        re.I,
    ),
)
FINAL_REPORT_PATTERNS = (
    re.compile(
        r"(?P<polarity>[^.;!?]{0,40}?)(?P<action>report|send|issue)(?:s|ed|ing)?\b"
        r"[^.;!?]{0,80}(?:final\s+result|final\s+user\s+report|to\s+the\s+user)"
        r"[^.;!?]{0,80}\bbefore\b[^.;!?]{0,80}(?:QA|closeout)",
        re.I,
    ),
    re.compile(
        r"(?:the\s+)?final\s+user\s+report"
        r"(?P<polarity>[^.;!?]{0,40}?)(?P<action>occurs?|happens?|is\s+sent|is\s+issued)"
        r"[^.;!?]{0,80}\bbefore\b[^.;!?]{0,80}(?:QA|closeout)",
        re.I,
    ),
)
FALLBACK_CONDITION_PATTERN = re.compile(
    r"(?:project\s+)?(?:isolation|filter(?:ing)?|provenance)\b[^\n]{0,100}?"
    r"(?:is\s+)?(?:unavailable|missing|not\s+(?:available|enforced|verified))\b",
    re.I,
)
FALLBACK_ACTION_PATTERN = re.compile(r"memory_(?:recall|save)|\brecall\b|\bsave\b", re.I)
QA_EDIT_ACTION_PATTERN = re.compile(
    r"(?P<action>edits?|editing|modif(?:y|ies|ying)|fix(?:es|ing)?|writes?)"
    r"[^.;!?]{0,50}\bproduction\b",
    re.I,
)
QA_COMMAND_ACTION_PATTERN = re.compile(
    r"(?P<action>command|dispatch|assign|drive|direct)(?:s|es|ing)?"
    r"[^.;!?]{0,50}\bimplementers?\b",
    re.I,
)
ACTOR_PATTERN = re.compile(
    r"\b(?P<actor>static\s+role\s+Agents?|role\s+Agents?|static\s+roles?|"
    r"subagents?|QA|PM|roles?)\b",
    re.I,
)
NESTED_ACTOR_PATTERN = re.compile(
    r"\b(?P<actor>static\s+role\s+Agents?|role\s+Agents?|static\s+roles?|"
    r"subagents?|QA|roles?|implementers?|xy-[a-z0-9]+(?:-[a-z0-9]+)*|PM)\b",
    re.I,
)
NESTED_ACTION_PATTERN = re.compile(
    r"(?P<action>delegate(?:s|d|ing)?|invoke_subagent|define_subagent|send_message|"
    r"sends?\s+messages?)\b",
    re.I,
)
QA_PRONOUN_EDIT_PATTERN = re.compile(
    r"\bQA\b[^;]{0,80};\s*it\s+(?P<polarity>[^;]{0,30}?)"
    r"(?P<action>edits?|editing|modif(?:y|ies|ying)|fix(?:es|ing)?|writes?)"
    r"[^;]{0,50}\bproduction\b",
    re.I,
)
STATIC_AGENT_DENIAL_PATTERNS = (
    re.compile(r"static\s+agent\s+files.{0,80}\*\*No\*\*", re.I),
    re.compile(r"No\s+fixed\s+on-disk\s+agent\s+schema", re.I),
)
LEGACY_UI_ACTION_PATTERNS = (
    re.compile(
        r"(?P<action>generate|persist|save|write|attach|present|return|provide|capture)"
        r"(?:s|d|ing)?\b[^.;!?]{0,100}\bscreenshots?\b",
        re.I,
    ),
    re.compile(
        r"(?P<action>create|generate|write|persist)(?:s|d|ing)?\b"
        r"[^.;!?]{0,120}\btask-specific\b[^.;!?]{0,80}\bMarkdown\b",
        re.I,
    ),
    re.compile(
        r"(?P<action>create|generate|write|persist)(?:s|d|ing)?\b"
        r"[^.;!?]{0,100}\bManifest\b",
        re.I,
    ),
    re.compile(
        r"(?P<action>create|store|keep|place|write)(?:s|d|ing)?\b"
        r"[^.;!?]{0,100}\bprototypes?/<task>/",
        re.I,
    ),
    re.compile(
        r"(?P<action>copy|reuse|ship)(?:s|ied|ping)?\b[^.;!?]{0,100}"
        r"\bprototype\b[^.;!?]{0,100}\b(?:mock|runtime)\b"
        r"[^.;!?]{0,100}\bproduction\b",
        re.I,
    ),
    re.compile(
        r"(?P<action>persist|save|write|attach|present|use)(?:s|d|ing)?\b"
        r"[^.;!?]{0,100}\brendered frame\b[^.;!?]{0,100}"
        r"\bapproval evidence\b",
        re.I,
    ),
)
ROOT_INDEX_SUFFICIENT_PATTERN = re.compile(
    r"\broot\s+prototype\s+index\b(?P<polarity>[^.;!?]{0,60}?)"
    r"(?P<action>is|remains|becomes)\s+sufficient\b",
    re.I,
)

MAX_CONTROLLED_FILE_SIZE = 4 * 1024 * 1024
AMBIGUOUS_YAML_PLAIN_WORDS = {
    "false",
    "n",
    "no",
    "null",
    "off",
    "on",
    "true",
    "y",
    "yes",
    "~",
}
YAML_PLAIN_NUMBER_PATTERN = re.compile(
    r"""
    [+-]?(?:
        0[bB][01_]+
        |0[oO][0-7_]+
        |0[xX][0-9a-fA-F_]+
        |[0-9][0-9_]*
        |(?:[0-9][0-9_]*)?\.[0-9_]+(?:[eE][+-]?[0-9_]+)?
        |[0-9][0-9_]*\.(?:[0-9_]*)?(?:[eE][+-]?[0-9_]+)?
        |[0-9][0-9_]*[eE][+-]?[0-9_]+
        |\.(?:inf|nan)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
YAML_PLAIN_DATE_OR_TIME_PATTERN = re.compile(
    r"""
    (?:
        [0-9]{4}-[0-9]{1,2}-[0-9]{1,2}
        (?:[Tt\x20\t]+[0-9]{1,2}:[0-9]{2}:[0-9]{2}
            (?:\.[0-9]+)?
            (?:[\x20\t]*(?:Z|[+-][0-9]{1,2}(?::?[0-9]{2})?))?
        )?
        |[0-9]{1,2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?
    )
    """,
    re.VERBOSE,
)
YAML_PLAIN_STRUCTURAL_STARTS = frozenset("-?:,[]{}#&*!|>%@`")


@dataclass(frozen=True)
class SourceContext:
    roles: tuple[str, ...]
    skill_names: tuple[str, ...]


class SecureReadError(ValueError):
    """A controlled input cannot be securely opened or decoded."""


def render_antigravity_host_aliases(body: str) -> str:
    """Render portable/Codex Skill calls with Antigravity slash syntax."""

    body = re.sub(r"\$(xy-[a-z0-9]+(?:-[a-z0-9]+)*)", r"/\1", body)
    return body.replace("$ui-ux-pro-max", "/ui-ux-pro-max")


def require_real_root(path: Path, label: str) -> None:
    """Require the named root itself to be a no-follow real directory."""

    descriptor = -1
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        descriptor = os.open(path, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise SecureReadError(f"{label} must be a real directory: {path}")
    except OSError as exc:
        raise SecureReadError(
            f"cannot securely open {label} as a real no-follow directory {path}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def secure_read_bytes(root: Path, relative: Path, label: str) -> bytes:
    """Read a single-link regular file by walking below ``root`` with dir fds."""

    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise SecureReadError(f"unsafe relative path for {label}: {relative}")

    directory_fd = -1
    final_fd = -1
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        directory_fd = os.open(root, directory_flags)
        root_info = os.fstat(directory_fd)
        if not stat.S_ISDIR(root_info.st_mode):
            raise SecureReadError(f"controlled root must be a real directory: {root}")

        for component in relative.parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            info = os.fstat(next_fd)
            if not stat.S_ISDIR(info.st_mode):
                os.close(next_fd)
                raise SecureReadError(
                    f"directory component for {label} is not a real directory: "
                    f"{root / relative}"
                )
            os.close(directory_fd)
            directory_fd = next_fd

        final_fd = os.open(relative.parts[-1], file_flags, dir_fd=directory_fd)
        info = os.fstat(final_fd)
        if not stat.S_ISREG(info.st_mode):
            raise SecureReadError(
                f"{label} must be a real regular file: {root / relative}"
            )
        if info.st_nlink != 1:
            raise SecureReadError(
                f"hard link is forbidden for {label}: {root / relative}"
            )
        if info.st_size > MAX_CONTROLLED_FILE_SIZE:
            raise SecureReadError(
                f"{label} exceeds {MAX_CONTROLLED_FILE_SIZE} bytes: {root / relative}"
            )

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                final_fd,
                min(1024 * 1024, MAX_CONTROLLED_FILE_SIZE + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_CONTROLLED_FILE_SIZE:
                raise SecureReadError(
                    f"{label} exceeds {MAX_CONTROLLED_FILE_SIZE} bytes: {root / relative}"
                )
        return b"".join(chunks)
    except SecureReadError:
        raise
    except OSError as exc:
        raise SecureReadError(
            f"cannot securely read {label} {root / relative}: {exc}"
        ) from exc
    finally:
        if final_fd >= 0:
            os.close(final_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def secure_read_text(root: Path, relative: Path, label: str) -> str:
    body = secure_read_bytes(root, relative, label)
    try:
        return body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SecureReadError(
            f"{label} is not valid UTF-8: {root / relative}: {exc}"
        ) from exc


def discovered_roles(pack: Path, project: Path, errors: list[str]) -> list[str]:
    """Return the validated, read-only ProjectProfile roster for one project."""

    try:
        result = validate_with_profile(
            pack / "project.yaml",
            project,
            pack / "roles",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"cannot discover Antigravity project profile: {exc}")
        return []
    errors.extend(result.errors)
    if result.errors or result.profile is None:
        return []
    roles = list(result.profile.enabled_roles)
    unsupported = sorted(set(roles) - set(CANONICAL_ROLES))
    if unsupported:
        errors.append(
            "unsupported discovered Antigravity roles: " + ", ".join(unsupported)
        )
    return roles


def _description_scalar(
    raw: str,
    role: str,
    path: Path,
    errors: list[str],
) -> str | None:
    value = raw.strip()
    if not value:
        errors.append(f"empty role description for {role}: {path}")
        return None
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            errors.append(
                f"invalid double-quoted role description for {role} in {path}: "
                f"{exc.msg}"
            )
            return None
        if not isinstance(decoded, str) or not decoded.strip():
            errors.append(f"role description must be a non-empty string for {role}: {path}")
            return None
        return decoded
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            errors.append(f"invalid single-quoted role description for {role}: {path}")
            return None
        inner = value[1:-1]
        result: list[str] = []
        index = 0
        while index < len(inner):
            if inner[index] != "'":
                result.append(inner[index])
                index += 1
                continue
            if index + 1 >= len(inner) or inner[index + 1] != "'":
                errors.append(
                    f"invalid single-quoted role description for {role}: {path}"
                )
                return None
            result.append("'")
            index += 2
        decoded = "".join(result)
        if not decoded.strip():
            errors.append(f"role description must be non-empty for {role}: {path}")
            return None
        return decoded
    if any(ord(character) < 0x20 and character != "\t" for character in value):
        errors.append(f"control character in role description for {role}: {path}")
        return None
    plain_is_ambiguous = (
        value.casefold() in AMBIGUOUS_YAML_PLAIN_WORDS
        or value in {"---", "..."}
        or value[0] in YAML_PLAIN_STRUCTURAL_STARTS
        or YAML_PLAIN_NUMBER_PATTERN.fullmatch(value) is not None
        or YAML_PLAIN_DATE_OR_TIME_PATTERN.fullmatch(value) is not None
        or re.search(r":(?:[ \t]|$)|[ \t]#", value) is not None
    )
    if plain_is_ambiguous:
        errors.append(
            f"ambiguous unquoted role description for {role} in {path}; "
            "use JSON double quotes or strict YAML single quotes"
        )
        return None
    return value


def role_descriptions(
    pack: Path,
    roles: list[str] | tuple[str, ...],
    errors: list[str],
) -> dict[str, str]:
    """Securely parse one controlled single-line description per enabled role."""

    relative = Path("product/ROLES.yaml")
    path = pack / relative
    try:
        body = secure_read_text(pack, relative, "role metadata")
    except SecureReadError as exc:
        errors.append(str(exc))
        return {}
    role_set = set(roles)
    found: dict[str, list[str]] = {role: [] for role in roles}
    current: str | None = None
    for line in body.splitlines():
        role_match = re.fullmatch(r"  (xy-[a-z0-9]+(?:-[a-z0-9]+)*):", line)
        if role_match:
            current = role_match.group(1)
            continue
        if current in role_set:
            description_match = re.fullmatch(r"    description:\s*(.+?)\s*", line)
            if description_match:
                found[current].append(description_match.group(1))
    descriptions: dict[str, str] = {}
    for role in roles:
        values = found[role]
        if len(values) != 1:
            errors.append(
                f"role {role} must have exactly one single-line description in {path}"
            )
        else:
            decoded = _description_scalar(values[0], role, path, errors)
            if decoded is not None:
                descriptions[role] = decoded
        try:
            secure_read_text(pack, Path("roles") / f"{role}.md", f"role source {role}")
        except SecureReadError as exc:
            errors.append(str(exc))
    return descriptions


def shared_skill_names(pack: Path, errors: list[str]) -> tuple[str, ...]:
    try:
        names = load_shared_core_skills(pack)
    except (OSError, UnicodeError, SharedCoreSkillError) as exc:
        errors.append(f"invalid shared core Skill sources: {exc}")
        return ()
    if set(names) != CORE_SKILLS:
        errors.append(
            "shared Skill manifest must contain exactly: "
            + ", ".join(sorted(CORE_SKILLS))
        )
    return names


def parse_agent_frontmatter(
    body: str,
    path: Path,
    errors: list[str],
) -> tuple[dict[str, object], str]:
    lines = body.splitlines()
    if not lines or lines[0] != "---":
        errors.append(f"missing opening Agent frontmatter delimiter: {path}")
        return {}, body
    try:
        end = lines.index("---", 1)
    except ValueError:
        errors.append(f"missing closing Agent frontmatter delimiter: {path}")
        return {}, body

    fields: dict[str, object] = {}
    index = 1
    while index < end:
        line = lines[index]
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*):(?:\s+(.*))?", line)
        if not match:
            errors.append(f"malformed Agent frontmatter line in {path}: {line!r}")
            index += 1
            continue
        key, raw_value = match.groups()
        if key in fields:
            errors.append(f"duplicate Agent frontmatter key {key}: {path}")
        if raw_value is None:
            items: list[str] = []
            index += 1
            while index < end and lines[index].startswith("  - "):
                item = lines[index][4:]
                if not item or not re.fullmatch(r"[A-Za-z0-9_./-]+", item):
                    errors.append(
                        f"invalid {key} list item in {path}: {item!r}"
                    )
                items.append(item)
                index += 1
            if not items:
                errors.append(f"Agent {key} must be a non-empty list: {path}")
            if len(items) != len(set(items)):
                errors.append(f"Agent {key} list contains duplicates: {path}")
            fields[key] = items
            continue

        if key in {"tools", "skills"}:
            errors.append(f"Agent {key} must be a block list: {path}")
            fields[key] = raw_value
        elif key == "description":
            try:
                decoded = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                errors.append(
                    f"Agent description must be a valid JSON/YAML-safe quoted string "
                    f"in {path}: {exc.msg}"
                )
                decoded = raw_value
            if not isinstance(decoded, str) or not decoded.strip():
                errors.append(f"Agent description must be a non-empty string: {path}")
            fields[key] = decoded
        elif key in {"mainAgent", "subagent"}:
            if raw_value not in {"true", "false"}:
                errors.append(f"Agent {key} must be a real boolean: {path}")
                fields[key] = raw_value
            else:
                fields[key] = raw_value == "true"
        else:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", raw_value):
                errors.append(f"unsafe Agent scalar for {key} in {path}: {raw_value!r}")
            fields[key] = raw_value
        index += 1

    unknown = sorted(set(fields) - AGENT_KEYS)
    missing = sorted(AGENT_KEYS - set(fields))
    if unknown:
        errors.append(f"unknown Agent frontmatter keys in {path}: {', '.join(unknown)}")
    if missing:
        errors.append(f"missing Agent frontmatter keys in {path}: {', '.join(missing)}")
    return fields, "\n".join(lines[end + 1 :])


def validate_skill_ref(
    ref: str,
    available_skills: set[str],
    role: str,
    errors: list[str],
) -> None:
    if not re.fullmatch(r"skills/xy-[a-z0-9]+(?:-[a-z0-9]+)*", ref):
        errors.append(f"Agent {role} has unsafe Skill reference: {ref!r}")
        return
    relative = Path(ref)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"Agent {role} Skill reference escapes its root: {ref!r}")
        return
    skill_name = relative.name
    if skill_name not in available_skills:
        errors.append(f"Agent {role} references unresolved Skill: {ref}")


def policy_for_role(role: str, errors: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tools = ROLE_TOOLS.get(role)
    skills = ROLE_SKILLS.get(role)
    if tools is None or skills is None:
        errors.append(f"no approved Antigravity role policy for: {role}")
        return (), ()
    return tools, skills


def semantic_segments(body: str) -> list[str]:
    """Return sentence/line-local segments so unrelated paragraphs cannot combine."""

    segments: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for sentence in re.split(r"(?<=[.!?。！？;；])\s+", line):
            for segment in re.split(
                r"\b(?:but|however|yet)\b|(?:但是|然而|但)",
                sentence,
                flags=re.I,
            ):
                normalized = " ".join(segment.strip(" ,").split())
                if normalized:
                    segments.append(normalized)
    return segments


def has_local_negation(text: str) -> bool:
    return LOCAL_NEGATION_PATTERN.search(text) is not None


def predicate_is_negated(prefix: str) -> bool:
    """Recognize negation governing the immediately following predicate/list item."""

    return re.search(
        r"(?:"
        r"\b(?:must|should|may|can|do|does|is|are)\s+(?:strictly\s+)?not"
        r"|\b(?:doesn't|don't|shouldn't|mustn't|isn't|aren't|can't)"
        r"|\bmust\s+never|\bnever|\bcannot"
        r"|\bneither"
        r"|\b(?:forbidden|prohibited)(?:\s+(?:to|from))?"
        r"|\bnot\s+to|\binstructed\s+not\s+to"
        r")"
        r"(?:\s+[A-Za-z_][A-Za-z0-9_-]*(?:\s*,\s*|\s+(?:or|nor)\s+))*"
        r"(?:\s+(?:or|nor|and))?\s*$",
        prefix,
        re.I,
    ) is not None


def actor_clauses(
    segment: str,
    pattern: re.Pattern[str] = ACTOR_PATTERN,
) -> list[tuple[str, str]]:
    matches = list(pattern.finditer(segment))
    clauses: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(segment)
        clauses.append((match.group("actor").casefold(), segment[match.end() : end]))
    return clauses


def fallback_action_is_negated(tail: str, action: re.Match[str]) -> bool:
    prefix = tail[: action.start()]
    local_prefix = re.split(r"[,;]", prefix)[-1][-50:]
    if predicate_is_negated(local_prefix):
        return True
    suffix = tail[action.end() : action.end() + 80]
    return re.match(
        r"^\s*(?:and\s+(?:memory_)?(?:recall|save)\s*)?"
        r"(?:(?:must|should|may|can|is|are|was|were)\s+(?:strictly\s+)?not"
        r"|(?:shouldn't|mustn't|isn't|aren't|can't)"
        r"|must\s+never|(?:is|are)\s+(?:forbidden|prohibited))\b",
        suffix,
        re.I,
    ) is not None


def add_semantic_error(
    path: Path,
    label: str,
    excerpt: str,
    errors: list[str],
) -> None:
    errors.append(f"{label} in {path}: {excerpt[:180]}")


def scan_common_semantics(path: Path, body: str, errors: list[str]) -> None:
    for raw_line in body.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        condition = FALLBACK_CONDITION_PATTERN.search(line)
        if condition is not None:
            tail = line[condition.end() :]
            for action in FALLBACK_ACTION_PATTERN.finditer(tail):
                if not fallback_action_is_negated(tail, action):
                    add_semantic_error(
                        path,
                        "memory isolation fallback bypass",
                        line,
                        errors,
                    )
                    break
        pronoun_edit = QA_PRONOUN_EDIT_PATTERN.search(line)
        if pronoun_edit is not None and not has_local_negation(
            pronoun_edit.group("polarity")
        ):
            add_semantic_error(path, "QA production edit authority", line, errors)

    for segment in semantic_segments(body):
        if re.search(r"\bPASS_WITH_NITS\b", segment):
            add_semantic_error(path, "legacy UI artifact model", segment, errors)

        root_only = ROOT_INDEX_SUFFICIENT_PATTERN.search(segment)
        if root_only is not None and not predicate_is_negated(
            root_only.group("polarity")
        ):
            add_semantic_error(path, "legacy UI artifact model", segment, errors)

        for pattern in LEGACY_UI_ACTION_PATTERNS:
            legacy_ui = pattern.search(segment)
            action_to_target = segment[
                legacy_ui.end("action") : legacy_ui.end()
            ] if legacy_ui is not None else ""
            if (
                legacy_ui is not None
                and not predicate_is_negated(segment[: legacy_ui.start("action")])
                and re.search(r"\b(?:no|without)\b", action_to_target, re.I) is None
            ):
                add_semantic_error(path, "legacy UI artifact model", segment, errors)
                break

        ui_match = UI_ACTION_PATTERN.search(segment)
        if ui_match is not None and not predicate_is_negated(
            ui_match.group("polarity")
        ):
            add_semantic_error(path, "UI gate bypass", segment, errors)

        for pattern in MEMORY_AUTHORITY_PATTERNS:
            authority = pattern.search(segment)
            if authority is not None and not predicate_is_negated(
                authority.group("polarity")
            ):
                add_semantic_error(path, "memory authority inversion", segment, errors)
                break

        for pattern in FINAL_REPORT_PATTERNS:
            report = pattern.search(segment)
            if report is not None and not predicate_is_negated(report.group("polarity")):
                add_semantic_error(
                    path,
                    "final user report before closeout",
                    segment,
                    errors,
                )
                break

        if re.search(r"write\+delegation.{0,120}may\s+nest", segment, re.I):
            add_semantic_error(path, "nested delegation authority", segment, errors)

        for actor, clause in actor_clauses(segment):
            if actor == "pm":
                continue
            if actor == "qa":
                edit = QA_EDIT_ACTION_PATTERN.search(clause)
                if edit is not None and not predicate_is_negated(
                    clause[: edit.start()]
                ):
                    add_semantic_error(
                        path,
                        "QA production edit authority",
                        segment,
                        errors,
                    )
                command = QA_COMMAND_ACTION_PATTERN.search(clause)
                if command is not None and not predicate_is_negated(
                    clause[: command.start()]
                ):
                    add_semantic_error(path, "QA commands implementers", segment, errors)

        for actor, clause in actor_clauses(segment, NESTED_ACTOR_PATTERN):
            if actor == "pm":
                continue
            nested = NESTED_ACTION_PATTERN.search(clause)
            if nested is not None and not predicate_is_negated(
                clause[: nested.start()]
            ):
                add_semantic_error(path, "nested delegation authority", segment, errors)


def require_phrases(path: Path, body: str, phrases: tuple[str, ...], errors: list[str]) -> None:
    normalized = " ".join(body.split())
    for phrase in phrases:
        if " ".join(phrase.split()) not in normalized:
            errors.append(f"{path} missing required contract phrase: {phrase}")


def require_order(
    path: Path,
    body: str,
    phrases: tuple[str, ...],
    label: str,
    errors: list[str],
) -> None:
    normalized = " ".join(body.split())
    cursor = -1
    valid = True
    for phrase in phrases:
        position = normalized.find(" ".join(phrase.split()), cursor + 1)
        if position < 0:
            valid = False
            break
        cursor = position
    if not valid:
        errors.append(f"{path} must order {label}: {' -> '.join(phrases)}")


def validate_semantic_sources(
    pack: Path,
    errors: list[str],
    *,
    shared_skills_valid: bool,
) -> None:
    errors.extend(validate_business_confirmation_pack(pack, "antigravity"))
    errors.extend(validate_pack_qa_review_policy(pack))
    relatives = {
        "memory": Path("platforms/shared/skills/xy-project-memory/SKILL.md"),
        "workflow": Path("platforms/shared/skills/xy-workflow/SKILL.md"),
        "qa_skill": Path("platforms/shared/skills/xy-qa-review/SKILL.md"),
        "build_skill": Path("platforms/shared/skills/xy-build-verify/SKILL.md"),
        "template": Path("platforms/antigravity/AGENTS.antigravity.tpl"),
        "product_template": Path("platforms/shared/AGENTS.product.tpl"),
        "global": Path("product/GLOBAL_CONSTRAINTS.md"),
        "product_workflow": Path("product/WORKFLOW.md"),
        "uiux_role": Path("roles/xy-uiux.md"),
        "web_role": Path("roles/xy-web.md"),
        "qa_role": Path("roles/xy-qa.md"),
    }
    paths = {name: pack / relative for name, relative in relatives.items()}
    bodies: dict[str, str] = {}
    entry_bodies: dict[str, str] = {}
    for name, relative in relatives.items():
        if relative.name == "SKILL.md" and not shared_skills_valid:
            continue
        path = pack / relative
        try:
            if relative.name == "SKILL.md":
                raw = secure_read_bytes(pack, relative, "semantic Skill source")
                parse_managed_skill_bytes(raw, relative.parent.name, str(path))
                # 语义扫描读完整契约，Agent 运行时仍只读对应分支。引用继续走宿主的
                # 描述符锚定读取，禁止符号链接、硬链接和目录逃逸，不降级为普通读取。
                body = expand_skill_contract(
                    raw.decode("utf-8", errors="strict"),
                    lambda reference: secure_read_text(
                        pack, relative.parent / reference, "semantic Skill reference"
                    ),
                )
            else:
                body = secure_read_text(pack, relative, "semantic source")
                entry_bodies[name] = body
                if relative.as_posix() in BOOTSTRAP_TARGETS:
                    # 保留描述符锚定读取：先检查入口，再展开受控来源的完整契约。
                    body = expand_bootstrap_contract(
                        body, lambda reference: read_instruction_contract(pack, reference),
                        BOOTSTRAP_TARGETS[relative.as_posix()],
                    )
        except (SecureReadError, SharedCoreSkillError, UnicodeDecodeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        bodies[name] = body
        scan_common_semantics(path, body, errors)

    memory = bodies.get("memory", "")
    require_phrases(
        paths["memory"],
        memory,
        (
            PRECEDENCE,
            "call neither recall nor save",
            # memory Skill 仍然安装，但接单检索必须保持条件触发，不能恢复成宿主必经步骤。
            "auxiliary information sources at task intake",
            "If start retrieval was not needed, omit `memory_context` entirely",
        ),
        errors,
    )

    workflow = bodies.get("workflow", "")
    require_phrases(
        paths["workflow"],
        workflow,
        (
            "Project documents (`PROJECT.md`, feature details, and requirement plans) and agentmemory are",
            "Activate `xy-project-memory` in start mode only when bounded cross-session recall or historical",
            "When no start retrieval ran, omit `memory_context`",
            "requirements_approved",
            "visual_approved",
            "UI-Conformance",
            "prototype_policy",
            "waived_by_user",
            "prototype_decision",
            "requirements_confirmation_user_choice",
            "design_authority_refs",
            "surface_kind",
            "qa_scope",
            "content_fingerprint",
            "resolution_state",
            "Platform security prompts",
            "Do not allow nested delegation",
            "Build a DAG",
            "Dispatch all currently ready independent tasks",
            "Re-evaluate downstream readiness after each completion",
            "capacity delay",
            "independent branches continue.",
            "current request dependency closure",
            "exactly one integrated read-only `xy-qa` reviewer for this request",
            "`installed-code-review-skill` proven installed and capable",
            "`internal-xy-qa-procedure`",
            "Do not wait for unrelated project work",
            "After QA PASS",
            "closeout mode",
            "report to the user",
        ),
        errors,
    )
    require_order(
        paths["workflow"],
        workflow,
        (
            "Activate `xy-project-memory` in start mode only when bounded cross-session recall or historical",
            "Dispatch all currently ready independent tasks",
            "## Default business confirmations and exceptions",
            "## Implementation and QA loop",
            "exactly one integrated read-only `xy-qa` reviewer for this request",
            "After QA PASS",
            "closeout mode",
            "report to the user",
        ),
        "on-demand retrieval policy -> default business confirmations -> implementation -> QA -> closeout -> report",
        errors,
    )
    for pattern, label in (
        (r"Wait for all project work\b", "project-wide QA barrier"),
        (r"module QA for every task\b", "default module-level QA"),
        (r"independent branches wait\b", "unrelated branch blocking"),
    ):
        match = re.search(pattern, workflow, re.I)
        if match is not None:
            add_semantic_error(paths["workflow"], label, match.group(0), errors)

    qa_skill = bodies.get("qa_skill", "")
    require_phrases(
        paths["qa_skill"],
        qa_skill,
        (
            "Current controlled documents",
            "win over recalled memory",
            # QA 接受没有进行 start retrieval 的请求，避免辅助记忆重新成为 QA 门禁。
            "When no start retrieval ran, omit `memory_context`",
            "Final QA outcome: PASS | FAIL",
            "does not edit production code",
            "does not edit production code, direct implementers",
            "must not preload or manually read the complete prototype dependency tree",
            "waived_by_user",
            "prototype_decision",
        ),
        errors,
    )

    qa_role = bodies.get("qa_role", "")
    require_phrases(
        paths["qa_role"],
        qa_role,
        (
            "Never edit project files, add tests, dispatch fixes, or widen task scope",
            "[Audit result] PASS | FAIL",
            "QA never dispatches or implements it directly",
            "prototype_policy",
            "waived_by_user",
            "prototype_decision",
        ),
        errors,
    )

    uiux_role = bodies.get("uiux_role", "")
    require_phrases(
        paths["uiux_role"],
        uiux_role,
        (
            "stable build-free interactive HTML pages",
            "Page design and interaction contract",
            "purpose",
            "navigation",
            "interactions",
            "states",
            "exceptions",
            "direct page links",
            "root index alone is insufficient",
            "dependency fingerprints",
        ),
        errors,
    )

    web_role = bodies.get("web_role", "")
    require_phrases(
        paths["web_role"],
        web_role,
        (
            "existing framework, components, tokens, and verification commands",
            "Do not copy prototype-only mock data",
            "page dependency fingerprint",
            "prototype_policy",
            "waived_by_user",
        ),
        errors,
    )

    global_constraints = bodies.get("global", "")
    require_phrases(
        paths["global"],
        global_constraints,
        (
            "Current controlled documents and explicit user approvals win over recalled memory.",
            "PM Report Contract",
        ),
        errors,
    )

    product_workflow = bodies.get("product_workflow", "")
    require_phrases(
        paths["product_workflow"],
        product_workflow,
        (
            "alignment and classification with on-demand auxiliary retrieval",
            "xy-qa",
            "memory closeout",
            "report to the user",
        ),
        errors,
    )
    require_order(
        paths["product_workflow"],
        product_workflow,
        (
            "alignment and classification with on-demand auxiliary retrieval",
            "xy-qa",
            "memory closeout",
            "report to the user",
        ),
        "classification/on-demand retrieval -> QA -> memory closeout -> user report",
        errors,
    )

    template = bodies.get("template", "")
    product_template = bodies.get("product_template", "")
    # 官方采用按需 Skill 控制上下文，没有规定 900 词或 7KB 的 PM 入口硬上限。
    # 必要规则允许略长；下方仍严格检查托管边界、语义完整性和重复上下文。
    for source_name in ("template", "product_template"):
        source_body = bodies.get(source_name, "")
        source_path = paths[source_name]
        for marker in MANAGED_BLOCK_MARKERS:
            if marker in source_body:
                errors.append(
                    f"managed block marker must not be embedded in source template "
                    f"{source_path}: {marker}"
                )
    if re.search(r"\$(?:xy-[a-z0-9-]+|ui-ux-pro-max)", template):
        errors.append(
            f"Antigravity template uses the wrong host alias in {paths['template']}"
        )
    if re.search(
        r"(?:\$|(?<![A-Za-z0-9])/)(?:xy-[a-z0-9-]+|ui-ux-pro-max)",
        entry_bodies.get("product_template", ""),
    ):
        errors.append(
            f"shared product template uses a host-specific alias in "
            f"{paths['product_template']}"
        )
    if "{{SANDBOX_TABLE}}" in product_template:
        errors.append(
            f"shared product template must not contain runtime placeholders: "
            f"{paths['product_template']}"
        )
    for pattern in STATIC_AGENT_DENIAL_PATTERNS:
        match = pattern.search(template)
        if match:
            errors.append(
                f"legacy static Agent denial in {paths['template']}: "
                f"{' '.join(match.group(0).split())[:180]}"
            )
    require_phrases(
        paths["template"],
        template,
        (
            "/xy-workflow",
            ".agents/agents/",
            ".agents/skills/",
            PRECEDENCE,
            "call neither recall nor save",
            "requirements_approved",
            "visual_approved",
            "UI-Conformance",
            "prototype_policy",
            "waived_by_user",
            "prototype_decision",
            "requirements_confirmation_user_choice",
            "design_authority_refs",
            "surface_kind: production_ui",
            "qa_scope: request",
            "resolved/fingerprinted",
            "Platform security prompts",
            "dependency fingerprint",
            "Only the PM may use",
            "invoke_subagent",
            "`inherit` stays `inherit`",
            "`worktree` becomes `branch`",
            "`share` is forbidden",
            # 原型是用户确认材料，宿主即使提供 /browser，也不能把能力存在误解为默认门禁。
            # 这里只允许“用户明确要求”或“用户报告故障后的最小诊断”两个例外来源。
            "Prototype verification MUST NOT invoke Computer Use or `/browser` by default",
            "user explicitly requests",
            "reports a concrete failure",
            "Production QA may still use risk-based browser testing",
            "No rendered frame may be persisted",
            "exactly one integrated, read-only `xy-qa`",
            "Final QA outcome: PASS | FAIL",
            "QA PASS",
            "memory closeout",
            "final user report",
        ),
        errors,
    )
    require_order(
        paths["template"],
        template,
        ("QA PASS", "memory closeout", "final user report"),
        "QA PASS -> memory closeout -> final user report",
        errors,
    )

    require_phrases(
        paths["product_template"],
        product_template,
        (
            "`xy-workflow`",
            "`xy-project-memory`",
            "requirements_approved",
            "visual_approved",
            "UI-Conformance",
            "prototype_policy",
            "waived_by_user",
            "prototype_decision",
            "design_authority_refs",
            "surface_kind: production_ui",
            "qa_scope: request",
            "resolved/fingerprinted",
            "Platform security prompts",
            "READY independent tasks",
            "exactly one `xy-qa` request audit",
            # 共享启动规则必须明确 PM 进行合同语义审核，而不是重复机器静态校验。
            "does not repeat deterministic checks already proven by current evidence",
            "Final QA outcome: PASS | FAIL",
            "QA PASS",
            "final user report",
        ),
        errors,
    )
    require_order(
        paths["product_template"],
        product_template,
        ("QA PASS", "`xy-project-memory` closeout", "final user report"),
        "QA PASS -> memory closeout -> final user report",
        errors,
    )


def validate_sources(pack: Path, errors: list[str]) -> SourceContext:
    roles = list(CANONICAL_ROLES)
    role_descriptions(pack, roles, errors)
    manifest_names = shared_skill_names(pack, errors)
    for role in roles:
        _, refs = policy_for_role(role, errors)
        for ref in refs:
            skill_name = Path(ref).name
            if skill_name not in manifest_names:
                errors.append(
                    f"role {role} requires Skill absent from shared manifest: {ref}"
                )
    validate_semantic_sources(
        pack,
        errors,
        shared_skills_valid=bool(manifest_names),
    )
    return SourceContext(tuple(roles), tuple(manifest_names))


def require_artifact_root(root: Path, errors: list[str]) -> Path | None:
    try:
        info = root.lstat()
    except OSError as exc:
        errors.append(f"cannot inspect Antigravity artifact root {root}: {exc}")
        return None
    if not stat.S_ISDIR(info.st_mode):
        errors.append(f"Antigravity artifact root must be a real directory: {root}")
        return None
    try:
        return root.resolve(strict=True)
    except OSError as exc:
        errors.append(f"cannot resolve Antigravity artifact root {root}: {exc}")
        return None


def require_artifact_node(
    root: Path,
    resolved_root: Path,
    path: Path,
    expected_type: str,
    errors: list[str],
) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        errors.append(f"Antigravity artifact path is outside its lexical root: {path}")
        return False
    current = root
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            info = current.lstat()
        except OSError as exc:
            errors.append(f"cannot inspect Antigravity artifact path {current}: {exc}")
            return False
        if stat.S_ISLNK(info.st_mode):
            errors.append(f"symlink is forbidden in Antigravity artifacts: {current}")
            return False
        is_final = index == len(relative.parts) - 1
        if not is_final and not stat.S_ISDIR(info.st_mode):
            errors.append(
                f"Antigravity artifact path component must be a directory: {current}"
            )
            return False
        if is_final and expected_type == "directory" and not stat.S_ISDIR(info.st_mode):
            errors.append(f"Antigravity artifact must be a real directory: {current}")
            return False
        if is_final and expected_type == "file":
            if not stat.S_ISREG(info.st_mode):
                errors.append(f"Antigravity artifact must be a regular file: {current}")
                return False
            if info.st_nlink != 1:
                errors.append(f"hard link is forbidden for Antigravity artifact: {current}")
                return False
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        errors.append(f"cannot resolve Antigravity artifact path {path}: {exc}")
        return False
    if not resolved.is_relative_to(resolved_root):
        errors.append(f"Antigravity artifact escapes its root: {path}")
        return False
    return True


def validate_agent(
    path: Path,
    body: str,
    role: str,
    available_skills: set[str],
    errors: list[str],
    *,
    enforce_context_boundaries: bool = False,
    ownership_only: bool = False,
) -> None:
    fields, body = parse_agent_frontmatter(body, path, errors)
    if enforce_context_boundaries:
        # 校验常驻内容是否误复制了整份资料，不提供旧的“上下文预算”参数适配。
        # 这里是内容归属边界，不能据此断言超过宿主 token 或文件大小限制。
        for copied_heading in (
            "# Global Mandatory Constraints",
            "## Discovered project modules",
            "Repository-native verification commands:",
        ):
            if copied_heading in body:
                errors.append(
                    f"{path} copies unbounded always-loaded context: {copied_heading}"
                )
    name = fields.get("name")
    if name != role or name != path.stem:
        errors.append(
            f"Antigravity Agent name/file mismatch for {path}: {name!r} != {role!r}"
        )
    if not isinstance(name, str) or not re.fullmatch(
        r"xy-[a-z0-9]+(?:-[a-z0-9]+)*", name
    ):
        errors.append(f"Antigravity Agent name must use lowercase hyphens: {path}")
    description = fields.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(
            f"Antigravity Agent description must be a non-empty quoted string: {path}"
        )
    if fields.get("mainAgent") is not False:
        errors.append(f"Antigravity Agent mainAgent must be false: {path}")
    if fields.get("subagent") is not True:
        errors.append(f"Antigravity Agent subagent must be true: {path}")
    # 官方静态角色仅支持这三个档位；不将主会话的内部模型枚举写进角色。
    if fields.get("model") not in {"inherit", "flash", "pro"}:
        errors.append(f"Antigravity Agent model must be inherit / flash / pro: {path}")
    if fields.get("commandExecutionPolicy") != "sandbox":
        errors.append(f"Antigravity Agent commandExecutionPolicy must be sandbox: {path}")

    expected_tools, expected_skills = policy_for_role(role, errors)
    tools_value = fields.get("tools")
    if not isinstance(tools_value, list):
        errors.append(f"Antigravity Agent tools must be list[str]: {path}")
        tools: tuple[str, ...] = ()
    else:
        tools = tuple(item for item in tools_value if isinstance(item, str))
        if len(tools) != len(tools_value):
            errors.append(f"Antigravity Agent tools must contain only strings: {path}")
    unknown_tools = sorted(set(tools) - ALL_APPROVED_TOOLS)
    if unknown_tools:
        errors.append(f"Antigravity Agent has unknown tools in {path}: {', '.join(unknown_tools)}")
    nested = sorted(set(tools) & NESTED_DELEGATION_TOOLS)
    if nested:
        errors.append(f"Antigravity Agent has nested delegation tools in {path}: {', '.join(nested)}")
    if tools != expected_tools:
        errors.append(
            f"Antigravity Agent {role} tools must exactly match approved policy: {path}"
        )
    if role == "xy-qa" and set(tools) & {
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
        "generate_image",
    }:
        errors.append(f"Antigravity QA Agent must remain read-only: {path}")

    skills_value = fields.get("skills")
    if not isinstance(skills_value, list):
        errors.append(f"Antigravity Agent skills must be list[str]: {path}")
        skills: tuple[str, ...] = ()
    else:
        skills = tuple(item for item in skills_value if isinstance(item, str))
        if len(skills) != len(skills_value):
            errors.append(f"Antigravity Agent skills must contain only strings: {path}")
    if skills != expected_skills:
        errors.append(
            f"Antigravity Agent {role} skills must exactly match approved policy: {path}"
        )
    for ref in skills:
        validate_skill_ref(ref, available_skills, role, errors)

    body_lines = body.splitlines()
    nonempty_body_lines = [line for line in body_lines if line.strip()]
    if (
        body_lines.count(AGENT_MARKER) != 1
        or not nonempty_body_lines
        or nonempty_body_lines[0] != AGENT_MARKER
    ):
        errors.append(
            "Antigravity Agent must start its body with exactly one managed marker "
            f"line: {path}"
        )
    scan_common_semantics(path, body, errors)
    if ownership_only:
        # 升级时校验的是“旧文件能否安全替换”，不能要求它已包含将要安装的新版正文。
        # 仍保留上面的严格 frontmatter、精确工具/Skill 策略、唯一 marker 和危险语义检查；
        # 再验证稳定的宿主执行结构，避免仅靠 marker 或同名文件接管用户 Agent。
        # 这里仅用于归属识别；staging/generated 不启用此分支，始终执行下方新版完整验证。
        boundary = (
            "## Antigravity handoff"
            if role in IMPLEMENTER_ROLES
            else "## Antigravity UIUX boundary"
            if role == "xy-uiux"
            else "## Antigravity read-only QA boundary"
        )
        require_phrases(
            path,
            body,
            (
                "## Antigravity execution contract",
                f"You are `{role}`; PM owns routing.",
                "Execute only the PM task pack.",
                "Never delegate or contact Agents.",
                "Return the result to the PM only.",
                "Do not report completion directly to the user.",
                "Block on missing authority/evidence/gates.",
                boundary,
            ),
            errors,
        )
        if role == "xy-qa":
            # run_command 仍可承载任意命令；因此旧产物归属不能只看工具名就丢掉只读约束。
            # 这两项是稳定的权限否定边界，不属于允许旧版本暂缺的新版业务细节。
            require_phrases(
                path,
                body,
                ("Do not edit production business code", "Do not command implementers"),
                errors,
            )
        return
    if role == "xy-uiux":
        require_phrases(
            path,
            body,
            (
                "stable, build-free, framework-independent",
                "Page design and interaction contract",
                "purpose",
                "navigation",
                "interactions",
                "states",
                "exceptions",
                "concrete changed-page",
                "dependency fingerprint",
                "root index alone is insufficient",
                # 静态 UI Agent 不再向 PM 请求补跑浏览器；默认禁用必须进入生成 Agent 本体。
                "Prototype verification MUST NOT invoke Computer Use or `/browser` by default",
                "explicit user request",
                "user-reported prototype failure",
            ),
            errors,
        )
    elif role == "xy-web":
        require_phrases(
            path,
            body,
            (
                "existing components, tokens, conventions",
                "Do not copy prototype-only mock data",
                "page dependency fingerprint",
            ),
            errors,
        )
    elif role == "xy-qa":
        require_phrases(
            path,
            body,
            (
                "Final QA outcome: PASS | FAIL",
                "to the PM only",
                "Do not edit production business code",
                "Do not command implementers",
                # QA 仍可按风险测试真实产品，但不能把原型合同审核重新变成浏览器自动化。
                "Prototype review MUST NOT invoke Computer Use or `/browser`",
                "only to the real production implementation",
                "rendered frame ephemerally in memory",
                "must not persist, save, write, attach, present",
            ),
            errors,
        )


def _managed_block_body(
    root: Path,
    resolved_root: Path,
    relative: Path,
    begin: str,
    end: str,
    errors: list[str],
) -> str | None:
    path = root / relative
    if not require_artifact_node(root, resolved_root, path, "file", errors):
        return None
    try:
        body = secure_read_text(root, relative, "Antigravity staged AGENTS block")
    except SecureReadError as exc:
        errors.append(str(exc))
        return None
    lines = body.splitlines()
    if (
        lines.count(begin) != 1
        or lines.count(end) != 1
        or not lines
        or lines[0] != begin
        or lines[-1] != end
    ):
        errors.append(
            f"staged AGENTS block must contain exact outer managed markers: {path}"
        )
        return None
    inner = "\n".join(lines[1:-1])
    for marker in MANAGED_BLOCK_MARKERS:
        if marker in inner:
            errors.append(f"managed marker injection inside staged AGENTS block: {path}")
    return inner


def validate_staged_blocks(
    pack: Path,
    root: Path,
    resolved_root: Path,
    errors: list[str],
) -> None:
    product = _managed_block_body(
        root,
        resolved_root,
        Path("AGENTS.product.block"),
        PRODUCT_BEGIN,
        PRODUCT_END,
        errors,
    )
    antigravity = _managed_block_body(
        root,
        resolved_root,
        Path("AGENTS.antigravity.block"),
        ANTIGRAVITY_BEGIN,
        ANTIGRAVITY_END,
        errors,
    )
    try:
        product_source = secure_read_text(
            pack,
            Path("platforms/shared/AGENTS.product.tpl"),
            "shared product template",
        ).rstrip("\n")
        antigravity_source = secure_read_text(
            pack,
            Path("platforms/antigravity/AGENTS.antigravity.tpl"),
            "Antigravity template",
        ).rstrip("\n")
    except SecureReadError as exc:
        errors.append(str(exc))
        return

    if product is not None:
        product_entry = product
        if product != product_source:
            errors.append(
                f"staged product block differs from the controlled shared source: "
                f"{root / 'AGENTS.product.block'}"
            )
        try:
            product = expand_bootstrap_contract(
                product, lambda reference: read_instruction_contract(pack, reference),
                BOOTSTRAP_TARGETS["platforms/shared/AGENTS.product.tpl"],
            )
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"invalid staged product bootstrap: {exc}")
            return
        if re.search(
            r"(?:\$|(?<![A-Za-z0-9])/)(?:xy-[a-z0-9-]+|ui-ux-pro-max)",
            product_entry,
        ):
            errors.append(
                f"staged product block contains a host-specific alias: "
                f"{root / 'AGENTS.product.block'}"
            )
        scan_common_semantics(root / "AGENTS.product.block", product, errors)
        require_phrases(
            root / "AGENTS.product.block",
            product,
            (
                "`xy-workflow`",
                "`xy-project-memory`",
                "requirements_approved",
                "visual_approved",
                "UI-Conformance",
                "design_authority_refs",
                "surface_kind: production_ui",
                "qa_scope: request",
                "resolved/fingerprinted",
                "Platform security prompts",
                "Final QA outcome: PASS | FAIL",
                "QA PASS",
                "final user report",
            ),
            errors,
        )
        require_order(
            root / "AGENTS.product.block",
            product,
            ("QA PASS", "`xy-project-memory` closeout", "final user report"),
            "QA PASS -> memory closeout -> final user report",
            errors,
        )

    if antigravity is not None:
        if antigravity != antigravity_source:
            errors.append(
                f"staged Antigravity block differs from its controlled template: "
                f"{root / 'AGENTS.antigravity.block'}"
            )
        try:
            antigravity = expand_bootstrap_contract(
                antigravity, lambda reference: read_instruction_contract(pack, reference),
                BOOTSTRAP_TARGETS["platforms/antigravity/AGENTS.antigravity.tpl"],
            )
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"invalid staged Antigravity bootstrap: {exc}")
            return
        if re.search(r"\$(?:xy-[a-z0-9-]+|ui-ux-pro-max)", antigravity):
            errors.append(
                f"staged Antigravity block retains the wrong host alias: "
                f"{root / 'AGENTS.antigravity.block'}"
            )
        scan_common_semantics(root / "AGENTS.antigravity.block", antigravity, errors)
        require_order(
            root / "AGENTS.antigravity.block",
            antigravity,
            ("QA PASS", "memory closeout", "final user report"),
            "QA PASS -> memory closeout -> final user report",
            errors,
        )

def validate_artifact_tree(
    pack: Path,
    root: Path,
    mode: str,
    errors: list[str],
    *,
    transaction_backups: frozenset[Path] = frozenset(),
) -> None:
    context = validate_sources(pack, errors)
    manifest_names = context.skill_names
    resolved_root = require_artifact_root(root, errors)
    if resolved_root is None:
        return
    if mode == "generated":
        platform_root = root / ".agents"
        agent_root = root / ".agents/agents"
        skill_root = root / ".agents/skills"
    else:
        platform_root = root
        agent_root = root / "agents"
        skill_root = root / "skills"
        validate_staged_blocks(pack, root, resolved_root, errors)
    if platform_root != root and not require_artifact_node(
        root, resolved_root, platform_root, "directory", errors
    ):
        return
    agent_root_valid = require_artifact_node(
        root, resolved_root, agent_root, "directory", errors
    )
    skill_root_valid = require_artifact_node(
        root, resolved_root, skill_root, "directory", errors
    )
    available_skills: set[str] = set()
    if not skill_root_valid:
        return
    if mode == "staging":
        try:
            staged_names = validate_staged_shared_core_skills(pack, skill_root)
            available_skills.update(staged_names)
        except (OSError, UnicodeError, SharedCoreSkillError) as exc:
            errors.append(f"invalid Antigravity staged Skill tree: {exc}")
    else:
        for name in manifest_names:
            directory = skill_root / name
            path = skill_root / name / "SKILL.md"
            if not require_artifact_node(
                root, resolved_root, directory, "directory", errors
            ):
                continue
            if not require_artifact_node(root, resolved_root, path, "file", errors):
                continue
            try:
                raw = secure_read_bytes(
                    root,
                    path.relative_to(root),
                    "Antigravity Skill artifact",
                )
                parse_managed_skill_bytes(raw, name, str(path))
            except (SecureReadError, SharedCoreSkillError) as exc:
                errors.append(f"invalid Antigravity Skill artifact {path}: {exc}")
                continue
            available_skills.add(name)
    if not agent_root_valid:
        return
    artifact_roles: list[str] = []
    try:
        with os.scandir(agent_root) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as exc:
        errors.append(f"cannot inspect Antigravity Agent inventory {agent_root}: {exc}")
        return
    for entry in entries:
        # 仅发布器已按原指纹核实的本轮备份可在提交前校验时排除；正常 CLI 没有排除项。
        # 不按隐藏文件前缀宽泛跳过，用户文件/遗留事务仍按原严格合同报错。
        if Path(entry.path) in transaction_backups:
            continue
        match = re.fullmatch(r"(xy-[a-z0-9]+(?:-[a-z0-9]+)*)\.md", entry.name)
        if match is None:
            errors.append(f"unexpected Antigravity Agent artifact: {entry.path}")
            continue
        role = match.group(1)
        if role not in ROLE_TOOLS:
            errors.append(f"unknown Antigravity Agent role: {entry.path}")
            continue
        artifact_roles.append(role)

    if mode == "generated":
        roles = discovered_roles(pack, root, errors)
        if set(artifact_roles) != set(roles):
            errors.append(
                "generated Antigravity Agent roster differs from the discovered "
                f"ProjectProfile: expected {sorted(roles)}, got {sorted(artifact_roles)}"
            )
    else:
        roles = sorted(artifact_roles)
        if "xy-qa" not in roles:
            errors.append("staged Antigravity Agent roster must include xy-qa")
        if any(role in {"xy-web", "xy-desktop", "xy-apple", "xy-android"} for role in roles) and "xy-uiux" not in roles:
            errors.append("staged UI implementation roles require xy-uiux")
    for role in roles:
        path = agent_root / f"{role}.md"
        if not require_artifact_node(root, resolved_root, path, "file", errors):
            continue
        try:
            body = secure_read_text(
                root,
                path.relative_to(root),
                "Antigravity Agent artifact",
            )
        except SecureReadError as exc:
            errors.append(str(exc))
            continue
        validate_agent(
            path,
            body,
            role,
            available_skills,
            errors,
            enforce_context_boundaries=True,
        )


def classify_owned_agents_root(project: Path) -> str:
    """Classify the native root without accepting mixed pack/user ownership."""
    require_real_root(project, "project root")
    root = project / ".agents"
    try:
        root_info = root.lstat()
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(root_info.st_mode):
        raise SecureReadError(f".agents symlink is forbidden: {root}")
    if not stat.S_ISDIR(root_info.st_mode):
        raise SecureReadError(f".agents must be a real directory: {root}")

    _validate_owned_native_root(root)
    return "managed"


def _scan_owned_native_tree(
    root: Path,
) -> tuple[list[str], dict[str, bytes]]:
    """Return the exact no-follow native directory and file inventory."""

    directories: list[str] = []
    files: dict[str, bytes] = {}
    nodes = 0

    def visit(directory: Path, prefix: Path) -> None:
        nonlocal nodes
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise SecureReadError(
                f"cannot inspect native managed root {directory}: {exc}"
            ) from exc
        for entry in entries:
            nodes += 1
            if nodes > 4096:
                raise SecureReadError("native managed root exceeds 4096 artifacts")
            path = Path(entry.path)
            relative = prefix / entry.name
            raw = relative.as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SecureReadError(
                    f"cannot inspect native managed artifact {path}: {exc}"
                ) from exc
            if stat.S_ISDIR(info.st_mode):
                directories.append(raw)
                visit(path, relative)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise SecureReadError(
                        f"hard link is forbidden in native managed root: {path}"
                    )
                files[raw] = secure_read_bytes(
                    root,
                    relative,
                    "native managed artifact",
                )
            else:
                raise SecureReadError(
                    f"symlink or special node is forbidden in native managed root: {path}"
                )

    require_real_root(root, "native managed root")
    visit(root, Path())
    return sorted(directories), dict(sorted(files.items()))


def _validate_owned_native_root(root: Path) -> None:
    directories, files = _scan_owned_native_tree(root)
    # hooks.json 是原生项目配置容器，可含用户条目；允许存在但绝不据此接管整个目录。
    # 安装器遇到该容器时使用按路径事务，不再整树 reset，用户配置保留在原位置。
    hook_bytes = files.pop("hooks.json", None)
    if hook_bytes is not None:
        try:
            from workflow_hook_install import json_object
            json_object(hook_bytes)
        except (ValueError, UnicodeError) as exc:
            raise SecureReadError(f"invalid native Hook configuration: {exc}") from exc
    top_level = {path for path in directories if "/" not in path}
    # 完全空的原生目录只有已知容器，没有用户文件或嵌套树，属于安全可初始化状态。
    # 不把部分存在、无清单证明的 Skill 树算作空目录，避免接管用户预建的同名目录。
    if not files and set(directories).issubset({"agents", "skills"}):
        return
    if "skills" not in top_level or not top_level.issubset({"agents", "skills"}):
        raise SecureReadError(
            ".agents must contain managed skills and may contain managed agents"
        )
    if any(path.startswith("agents/") for path in directories):
        raise SecureReadError("native Agent root must not contain subdirectories")
    if any("/" not in path for path in files):
        raise SecureReadError("native managed root must not contain files at its root")

    skill_names = {
        path.split("/", 1)[1]
        for path in directories
        if path.startswith("skills/") and path.count("/") == 1
    }
    if skill_names != CORE_SKILLS:
        raise SecureReadError("native managed root has an unexpected shared Skill set")
    audit_managed_skill_root(root / "skills", recover=False)
    for name in sorted(skill_names):
        validate_stale_managed_skill_directory(root / "skills" / name, name)

    agent_files = {
        path for path in files if path.startswith("agents/") and path.count("/") == 1
    }
    for raw in sorted(agent_files):
        name = Path(raw).name
        if not re.fullmatch(r"xy-[a-z0-9]+(?:-[a-z0-9]+)*\.md", name):
            raise SecureReadError(f"user-owned or unsafe Antigravity Agent: {root / raw}")
        role = Path(name).stem
        if role not in ROLE_TOOLS:
            raise SecureReadError(f"unknown Antigravity Agent role: {root / raw}")
        try:
            body = files[raw].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SecureReadError(
                f"pack-managed Antigravity Agent is not UTF-8: {root / raw}"
            ) from exc
        errors: list[str] = []
        validate_agent(
            root / raw,
            body,
            role,
            set(CORE_SKILLS),
            errors,
            ownership_only=True,
        )
        if errors:
            raise SecureReadError(
                f"invalid pack-managed Antigravity Agent {root / raw}: {errors[0]}"
            )
    # 受管 Skills 已独立通过清单/内容验证；旁边的空 agents 没有待覆盖数据，允许重建。
    unexpected_files = set(files) - agent_files - {
        path for path in files if path.startswith("skills/")
    }
    if unexpected_files:
        raise SecureReadError(
            f"unexpected native managed artifact: {root / sorted(unexpected_files)[0]}"
        )


def _native_tree_identity(root: Path) -> tuple[tuple[object, ...], ...]:
    directories, files = _scan_owned_native_tree(root)
    identities: list[tuple[object, ...]] = []
    for raw in ["", *directories, *files]:
        path = root if not raw else root / raw
        info = path.lstat()
        if raw in files:
            kind = "file"
            payload = hashlib.sha256(files[raw]).hexdigest()
        else:
            kind = "directory"
            payload = ""
        identities.append(
            (
                raw,
                kind,
                info.st_dev,
                info.st_ino,
                stat.S_IMODE(info.st_mode),
                info.st_nlink,
                payload,
            )
        )
    return tuple(identities)


def _validate_reset_backup_path(project: Path, backup: Path) -> None:
    if backup.parent != project or not re.fullmatch(
        r"\.agent-workflow-antigravity-reset\.[A-Za-z0-9]+", backup.name
    ):
        raise SecureReadError(f"unsafe native reset backup path: {backup}")


def reset_owned_agents_root(project: Path, backup: Path) -> str:
    """Validate, move, and identity-check the old root as one operation."""

    require_real_root(project, "project root")
    _validate_reset_backup_path(project, backup)
    try:
        backup.lstat()
    except FileNotFoundError:
        pass
    else:
        raise SecureReadError(f"native reset backup already exists: {backup}")

    ownership = classify_owned_agents_root(project)
    if ownership == "missing":
        return ownership
    root = project / ".agents"
    if (root / "hooks.json").exists():
        raise SecureReadError("native Hook configuration requires path-level publication, not whole-root reset")
    expected_identity = _native_tree_identity(root)
    os.replace(root, backup)
    if _native_tree_identity(backup) != expected_identity:
        if not root.exists() and not root.is_symlink():
            os.replace(backup, root)
        raise SecureReadError(
            "native root changed during reset; preserved the replacement"
        )
    return ownership


def restore_owned_agents_root(project: Path, backup: Path) -> None:
    """Restore a reset backup without ever deleting an unproven replacement root."""

    require_real_root(project, "project root")
    _validate_reset_backup_path(project, backup)
    backup_info = backup.lstat()
    if not (stat.S_ISDIR(backup_info.st_mode) or stat.S_ISLNK(backup_info.st_mode)):
        raise SecureReadError(f"native reset backup has an unsafe type: {backup}")

    root = project / ".agents"
    _validate_owned_native_root(root)
    expected_identity = _native_tree_identity(root)
    quarantine = project / f".agent-workflow-antigravity-failed.{secrets.token_hex(16)}"
    os.replace(root, quarantine)
    try:
        if _native_tree_identity(quarantine) != expected_identity:
            if not root.exists() and not root.is_symlink():
                os.replace(quarantine, root)
            raise SecureReadError(
                "native root changed during reset recovery; preserved the replacement and backup"
            )
        os.replace(backup, root)
        if _native_tree_identity(quarantine) != expected_identity:
            raise SecureReadError(
                "quarantined generated root changed during reset recovery; preserved it"
            )
        shutil.rmtree(quarantine)
    except Exception:
        if (
            (not root.exists() and not root.is_symlink())
            and (quarantine.exists() or quarantine.is_symlink())
        ):
            os.replace(quarantine, root)
        raise


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments or arguments[0] not in {
        "sources",
        "generated",
        "staging",
        "ownership",
        "reset",
        "restore",
    }:
        print(
            "usage: validate_antigravity_artifacts.py sources PACK_DIR | "
            "generated|staging PACK_DIR ROOT | ownership PROJECT_ROOT | "
            "reset|restore PROJECT_ROOT BACKUP",
            file=sys.stderr,
        )
        return 2
    mode = arguments[0]
    expected_length = 2 if mode in {"sources", "ownership"} else 3
    if len(arguments) != expected_length:
        print(
            "usage: validate_antigravity_artifacts.py sources PACK_DIR | "
            "generated|staging PACK_DIR ROOT | ownership PROJECT_ROOT | "
            "reset|restore PROJECT_ROOT BACKUP",
            file=sys.stderr,
        )
        return 2
    errors: list[str] = []
    try:
        if mode == "ownership":
            print(classify_owned_agents_root(Path(arguments[1])))
        elif mode == "reset":
            print(reset_owned_agents_root(Path(arguments[1]), Path(arguments[2])))
        elif mode == "restore":
            restore_owned_agents_root(Path(arguments[1]), Path(arguments[2]))
        else:
            pack = Path(arguments[1])
            require_real_root(pack, "workflow pack root")
            if mode == "sources":
                validate_sources(pack, errors)
            else:
                validate_artifact_tree(pack, Path(arguments[2]), mode, errors)
    except (SecureReadError, SharedCoreSkillError, OSError, UnicodeError) as exc:
        errors.append(str(exc))
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    if mode not in {"ownership", "reset", "restore"}:
        print(f"[OK] Antigravity {mode} contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
