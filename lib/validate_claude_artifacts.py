#!/usr/bin/env python3
"""Validate Claude Code source and generated artifact contracts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from business_confirmation_policy import read_instruction_contract, validate_business_confirmation_pack
from claude_instructions import CLAUDE_IMPORT, read_file, process as check_instruction_entry
from qa_review_policy import validate_pack_qa_review_policy
from validate_project_config import validate_with_profile
from role_models import validate as validate_model_settings
from claude_options import parse as parse_claude_options, frontmatter_window


SKILL_MARKER = "<!-- agent-workflow-pack:managed-skill -->"
AGENT_MARKER = "<!-- agent-workflow-pack:managed-agent -->"
CLAUDE_BEGIN = "<!-- agent-workflow-pack:claude-begin -->"
CLAUDE_END = "<!-- agent-workflow-pack:claude-end -->"
CORE_SKILLS = (
    "grill-me",
    "xy-workflow",
    "xy-plan",
    "xy-project-memory",
    "xy-build-verify",
    "xy-qa-review",
    "xy-prototype-verify",
)
CANONICAL_ROLES = (
    "xy-web",
    "xy-desktop",
    "xy-backend",
    "xy-apple",
    "xy-android",
    "xy-uiux",
    "xy-qa",
)
ALLOWED_SKILL_KEYS = {
    "name",
    "description",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
}
ALLOWED_AGENT_KEYS = {
    "autoCompactWindow",
    "name",
    "description",
    "model",
    "tools",
    "disallowedTools",
    "permissionMode",
    "maxTurns",
    "color",
    "skills",
    "mcpServers",
    "hooks",
    "memory",
    "effort",
    "background",
    "isolation",
}
ALLOWED_AGENT_COLORS = {
    "red",
    "blue",
    "green",
    "yellow",
    "purple",
    "orange",
    "pink",
    "cyan",
}
ALLOWED_PERMISSION_MODES = {
    "default",
    "acceptEdits",
    "auto",
    "dontAsk",
    "bypassPermissions",
    "plan",
}
ALLOWED_MODELS = {"inherit", "sonnet", "opus", "haiku"}
ALLOWED_GENERATED_TOOLS = {
    "Read",
    "Grep",
    "Glob",
    "Bash",
    "Edit",
    "Write",
    "Skill",
    "Agent",
}
PRECEDENCE = (
    "Current controlled documents and explicit user approvals win over recalled memory."
)
STRICT_MEMORY_FIELDS = (
    "fallback_reason",
    "project_id",
    "filter_enforced",
    "capability_evidence",
    "query_scope",
    "memory_ids",
    "provenance_refs",
    "document_refs",
    "stale_or_conflicting",
)
AUTHORITY_INVERSION_PATTERNS = (
    re.compile(
        r"(?:recalled\s+memory|agentmemory|auto\s+memory|memory)"
        r".{0,100}(?:override(?:s)?|wins?\s+over|takes?\s+precedence\s+over)"
        r".{0,100}(?:controlled|current\s+(?:project\s+)?documents?|user\s+approvals?)",
        re.I | re.S,
    ),
    re.compile(
        r"(?:memory|agentmemory|auto\s+memory).{0,60}"
        r"(?:is|becomes?)\s+(?:the\s+)?(?:approved\s+)?(?:source\s+of\s+truth|authority)",
        re.I | re.S,
    ),
)
MEMORY_FALLBACK_BYPASS_PATTERNS = (
    re.compile(
        r"(?:project\s+)?(?:isolation|filter|provenance)"
        r".{0,120}(?:unavailable|missing|not\s+(?:available|enforced|verified))"
        r".{0,120}(?:still|continue|anyway|regardless|even\s+then)"
        r".{0,80}(?:memory_(?:recall|save)|\brecall\b|\bsave\b)",
        re.I | re.S,
    ),
)
OBSOLETE_UI_SEMANTIC_PATTERNS = (
    (
        re.compile(
            r"root\s+(?:prototype\s+)?index(?:(?!not\s+sufficient).){0,100}"
            r"\bis\s+sufficient\b",
            re.I | re.S,
        ),
        "root index cannot be the only visual-approval artifact",
    ),
    (
        re.compile(r"screenshots?.{0,40}(?:fallback|approval\s+evidence)", re.I | re.S),
        "screenshot fallback or approval evidence is forbidden",
    ),
    (
        re.compile(r"(?:task(?:-specific)?\s+)?(?:design\s+)?markdown.{0,40}\brequired\b", re.I | re.S),
        "task-specific design Markdown is forbidden",
    ),
    (
        re.compile(r"manifest.{0,40}\brequired\b", re.I | re.S),
        "a prototype Manifest is forbidden",
    ),
    (
        re.compile(r"prototypes?/\s*(?:<task|\{task|task[-_])", re.I),
        "task-isolated prototype directories are forbidden",
    ),
    (
        re.compile(r"copy.{0,80}prototype-only.{0,80}mock\s+data.{0,80}production", re.I | re.S),
        "prototype-only mock/runtime content cannot be copied into production",
    ),
    (
        re.compile(r"PASS\s*\|\s*(?:WARN|PARTIAL|NEEDS[- ]WORK)\s*\|\s*FAIL", re.I),
        "QA has only PASS or FAIL outcomes",
    ),
)
FORBIDDEN_GENERATED_AGENT_FRAGMENTS = (
    "## Global mandatory constraints",
    "qa_review_policy:",
    "## Discovered repository context (generated)",
    "## QA write scope (generated)",
)


def read_exact_utf8(path: Path, label: str, errors: list[str]) -> str | None:
    """Decode the exact on-disk bytes without universal-newline translation."""

    try:
        return path.read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read {label} as exact UTF-8 bytes: {path}: {exc}")
        return None


def skill_source(pack: Path, name: str) -> Path:
    return pack / "platforms/shared/skills" / name / "SKILL.md"


def claude_agent_name(role: str) -> str:
    return role


def path_has_symlink(root: Path, relative: Path) -> bool:
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def discovered_roles(pack: Path, discovery_root: Path, errors: list[str]) -> tuple[str, ...]:
    try:
        result = validate_with_profile(
            pack / "project.yaml", discovery_root, pack / "roles"
        )
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"cannot load Claude project profile: {exc}")
        return ()
    errors.extend(f"Claude project profile: {error}" for error in result.errors)
    if result.profile is None:
        return ()
    return result.profile.enabled_roles


def validate_managed_output_paths(
    project_root: Path, roles: tuple[str, ...], errors: list[str]
) -> None:
    root = project_root.resolve()
    directories = {
        Path(".claude"),
        Path(".claude/agents"),
        Path(".claude/skills"),
        *(Path(".claude/skills") / name for name in CORE_SKILLS),
    }
    files = {
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        *(
            Path(".claude/skills") / name / "SKILL.md"
            for name in CORE_SKILLS
        ),
        *(
            Path(".claude/agents") / f"{claude_agent_name(role)}.md"
            for role in roles
        ),
    }
    for relative, expected_type in (
        *((path, "directory") for path in directories),
        *((path, "file") for path in files),
    ):
        target = root / relative
        try:
            resolved = target.resolve()
        except OSError as exc:
            errors.append(f"cannot resolve Claude managed output {relative}: {exc}")
            continue
        if path_has_symlink(root, relative) or not resolved.is_relative_to(root):
            errors.append(
                f"Claude managed output must not use symlinks or leave the project: "
                f"{relative}"
            )
            continue
        if not target.exists():
            continue
        if expected_type == "directory" and not target.is_dir():
            errors.append(f"Claude managed output must be a directory: {relative}")
        if expected_type == "file" and not target.is_file():
            errors.append(f"Claude managed output must be a regular file: {relative}")


def parse_frontmatter(path: Path, errors: list[str]) -> tuple[dict[str, str], list[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"cannot read {path}: {exc}")
        return {}, []
    if not lines or lines[0] != "---":
        errors.append(f"missing opening frontmatter delimiter: {path}")
        return {}, lines
    try:
        end = lines.index("---", 1)
    except ValueError:
        errors.append(f"missing closing frontmatter delimiter: {path}")
        return {}, lines
    fields: dict[str, str] = {}
    active_list_key: str | None = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s*(.*))?$", line)
        if match:
            key = match.group(1)
            if key in fields:
                errors.append(f"duplicate frontmatter key {key}: {path}")
            fields[key] = (match.group(2) or "").strip()
            value = fields[key]
            if value.startswith('"'):
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    errors.append(
                        f"invalid quoted frontmatter scalar for {key}: {path}"
                    )
                else:
                    if not isinstance(decoded, str):
                        errors.append(
                            f"frontmatter scalar for {key} must be a string: {path}"
                        )
            elif value.startswith("'"):
                if len(value) < 2 or not value.endswith("'"):
                    errors.append(
                        f"invalid quoted frontmatter scalar for {key}: {path}"
                    )
            elif value.startswith("["):
                if not re.fullmatch(
                    r"\[(?:[A-Za-z0-9-]+(?:\s*,\s*[A-Za-z0-9-]+)*)?\]",
                    value,
                ):
                    errors.append(f"invalid frontmatter inline list for {key}: {path}")
            elif value.endswith(('"', "'")):
                errors.append(f"invalid quoted frontmatter scalar for {key}: {path}")
            elif value and (
                "\t" in value
                or ": " in value
                or " #" in value
                or value[0] in "-?:,[]{}#&*!|>'\"%@`"
            ):
                errors.append(
                    f"unsafe unquoted frontmatter scalar for {key}: {path}"
                )
            active_list_key = key if not fields[key] else None
            continue
        if active_list_key and re.match(r"^  -\s+\S", line):
            continue
        errors.append(f"malformed frontmatter line in {path}: {line!r}")
        active_list_key = None
    return fields, lines[end + 1 :]


def list_field(lines: list[str], key: str) -> list[str]:
    result: list[str] = []
    active = False
    for line in lines:
        if line == f"{key}:":
            active = True
            continue
        if active and line.startswith("  - "):
            result.append(line[4:].strip())
            continue
        if active:
            break
    return result


def validate_skill(path: Path, expected_name: str, errors: list[str]) -> None:
    fields, _ = parse_frontmatter(path, errors)
    if fields.get("name") != expected_name:
        errors.append(f"Skill name mismatch for {path}: {fields.get('name')!r}")
    if not fields.get("description"):
        errors.append(f"Skill description is empty: {path}")
    unsupported = sorted(set(fields) - ALLOWED_SKILL_KEYS)
    if unsupported:
        errors.append(f"unsupported Skill frontmatter in {path}: {', '.join(unsupported)}")
    if "disable-model-invocation" in fields and fields["disable-model-invocation"] not in {
        "true",
        "false",
    }:
        errors.append(f"invalid disable-model-invocation boolean: {path}")
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return
    if SKILL_MARKER not in body:
        errors.append(f"missing managed Skill marker: {path}")


def parse_roles_metadata(path: Path, errors: list[str]) -> dict[str, dict[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"cannot read Claude role metadata {path}: {exc}")
        return {}
    result: dict[str, dict[str, str]] = {}
    active = False
    current: str | None = None
    for raw in lines:
        if raw == "roles:":
            active = True
            continue
        if active and raw and not raw.startswith((" ", "#")):
            break
        role_match = re.match(r"^  (xy-[a-z0-9]+(?:-[a-z0-9]+)*):\s*$", raw)
        if role_match:
            current = role_match.group(1)
            if current in result:
                errors.append(f"duplicate Claude role metadata: {current}")
            result.setdefault(current, {})
            continue
        field_match = re.match(r"^    ([A-Za-z][A-Za-z0-9_]*):\s*(.*?)\s*$", raw)
        if active and current and field_match:
            key, value = field_match.groups()
            if key in result[current]:
                errors.append(f"duplicate {current}.{key} in {path}")
            result[current][key] = value.strip().strip('"\'')
    return result


def validate_role_sources(pack: Path, errors: list[str]) -> None:
    metadata = parse_roles_metadata(pack / "product/ROLES.yaml", errors)
    for role in CANONICAL_ROLES:
        values = metadata.get(role)
        if values is None:
            errors.append(f"missing Claude metadata for canonical role: {role}")
            continue
        if values.get("sandbox_key") != role:
            errors.append(f"Claude role sandbox_key must match {role}")
        if values.get("claude_color") not in ALLOWED_AGENT_COLORS:
            errors.append(f"unsupported claude_color for {role}")
        if not re.fullmatch(r"[1-9][0-9]*", values.get("claude_max_turns", "")):
            errors.append(f"claude_max_turns must be an integer >= 1 for {role}")
        skills = values.get("claude_skills", "")
        if not (skills.startswith("[") and skills.endswith("]")):
            errors.append(f"claude_skills must be an inline list for {role}")
        else:
            for skill in (item.strip() for item in skills[1:-1].split(",")):
                if skill and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill):
                    errors.append(f"invalid Claude Skill name for {role}: {skill}")
        description = values.get("description", "")
        if not description:
            errors.append(f"missing Claude description for {role}")
        if role == "xy-uiux" and "docs/design" in description:
            errors.append(
                "xy-uiux description must reference the configured docs.standards_root/DESIGN_*.md path"
            )

        role_path = pack / "roles" / f"{role}.md"
        if not role_path.is_file():
            errors.append(f"missing canonical role source: {role_path}")
            continue
        fields, _ = parse_frontmatter(role_path, errors)
        if fields.get("name") != role:
            errors.append(f"role source name mismatch for {role_path}")
        if not fields.get("toolsets"):
            errors.append(f"role source lacks toolsets: {role_path}")
        if fields.get("workspace") not in {"inherit", "worktree"}:
            errors.append(f"role source has unsupported workspace: {role_path}")
        scan_authority(role_path, errors)

    global_constraints = pack / "product/GLOBAL_CONSTRAINTS.md"
    if not global_constraints.is_file():
        errors.append(f"missing global constraints source: {global_constraints}")
    else:
        scan_authority(global_constraints, errors)


def scan_authority(path: Path, errors: list[str]) -> None:
    try:
        if path.name == "AGENTS.claude.tpl":
            body = read_instruction_contract(path.parents[2], "platforms/claude/AGENTS.claude.tpl")
        else:
            body = read_instruction_contract(path.parent, path.name)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"cannot scan authority source {path}: {exc}")
        return
    for pattern in AUTHORITY_INVERSION_PATTERNS:
        match = pattern.search(body)
        if match:
            excerpt = " ".join(match.group(0).split())[:180]
            errors.append(f"memory authority inversion in {path}: {excerpt}")
    for pattern in MEMORY_FALLBACK_BYPASS_PATTERNS:
        match = pattern.search(body)
        if match:
            excerpt = " ".join(match.group(0).split())[:180]
            errors.append(f"memory fallback bypass in {path}: {excerpt}")


def require_semantic_groups(
    path: Path,
    groups: tuple[tuple[str, tuple[str, ...]], ...],
    errors: list[str],
) -> None:
    """Validate concepts while allowing equivalent English wording."""

    try:
        # 目录入口与详细正文作为一个契约审计，不要求把全部规则塞回根提示。
        body = read_instruction_contract(path.parents[2], "platforms/claude/AGENTS.claude.tpl") if path.name == "AGENTS.claude.tpl" else path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"cannot scan Claude semantic contract {path}: {exc}")
        return
    for label, patterns in groups:
        if not any(re.search(pattern, body, re.I | re.S) for pattern in patterns):
            errors.append(f"{path} lacks Claude semantic contract: {label}")
    for pattern, message in OBSOLETE_UI_SEMANTIC_PATTERNS:
        if pattern.search(body):
            errors.append(f"obsolete Claude UI semantics in {path}: {message}")


def validate_latest_ui_semantics(pack: Path, errors: list[str]) -> None:
    template = pack / "platforms/claude/AGENTS.claude.tpl"
    uiux = pack / "roles/xy-uiux.md"
    web = pack / "roles/xy-web.md"
    qa = pack / "roles/xy-qa.md"
    require_semantic_groups(
        template,
        (
            ("single workflow entry", (r"/xy-workflow\b",)),
            ("native Agent routing", (r"Agent\(xy-\*\)", r"Agent\(xy-[a-z-]+\)")),
            ("prototype verification disclosure", (r"/xy-prototype-verify\b",)),
            ("UI design-change visual gate", (r"UI\s+design-change\s+work.{0,120}visual_approved",)),
            (
                "UI conformance route",
                (r"UI-Conformance.{0,180}design_delta:\s*none.{0,180}no\s+visual\s+gate",),
            ),
            (
                "UI conformance machine envelope",
                (r"surface_kind:\s*production_ui.{0,100}qa_scope:\s*request",),
            ),
            ("frozen UI authority", (r"resolved/fingerprinted.{0,80}design_authority_refs",)),
            ("dependency fingerprint", (r"dependency\s+fingerprint",)),
            # Claude 宿主具备浏览器能力时也不能自动运行；原型浏览器只接受用户来源的例外。
            ("prototype browser disabled by default", (r"prototype\s+verification.{0,100}must\s+not\s+invoke\s+Computer\s+Use.{0,100}browser\s+automation\s+by\s+default",)),
            (
                "requirements-confirmation prototype choice",
                (r"prototype_decision[\s\S]{0,350}waived_by_user[\s\S]{0,160}has\s+no[\s\S]{0,120}visual\s+gate",),
            ),
        ),
        errors,
    )
    require_semantic_groups(
        uiux,
        (
            ("one page contract", (r"exactly\s+one.{0,80}Page design and interaction contract",)),
            ("direct concrete-page links", (r"direct\s+link.{0,60}concrete\s+changed\s+page",)),
            ("root index is insufficient", (r"root\s+(?:prototype\s+)?index.{0,60}(?:not\s+sufficient|insufficient|do\s+not\s+ask)",)),
            ("dependency fingerprint", (r"dependency\s+fingerprint",)),
            ("prototype browser disabled by default", (r"prototype\s+verification.{0,100}must\s+not\s+invoke\s+Computer\s+Use.{0,100}browser\s+automation\s+by\s+default",)),
            ("requirements-contract semantic review", (r"PM.{0,180}reviews?.{0,100}five\s+contract\s+sections.{0,160}frozen\s+requirements",)),
            ("screenshots forbidden", (r"must\s+not.{0,80}screenshot",)),
        ),
        errors,
    )
    require_semantic_groups(
        web,
        (
            ("production UI classification", (r"surface_kind:\s*production_ui.{0,120}qa_scope:\s*request",)),
            ("frozen authority", (r"structured.{0,100}design_authority_refs",)),
            ("production component reuse", (r"(?:reuse|reusing).{0,80}production\s+components",)),
            ("production token reuse", (r"(?:reuse|reusing).{0,80}(?:production\s+)?tokens",)),
            ("prototype-only content rejection", (r"do\s+not\s+copy.{0,80}prototype-only",)),
            ("mock-data rejection", (r"mock\s+data",)),
            ("prototype policy", (r"prototype_policy",)),
            (
                "requirements-confirmation prototype choice",
                (
                    r"(?:waived_by_user[\s\S]{0,260}prototype_decision|"
                    r"prototype_decision[\s\S]{0,260}waived_by_user)",
                ),
            ),
        ),
        errors,
    )
    require_semantic_groups(
        qa,
        (
            ("binary QA result", (r"PASS\s*\|\s*FAIL",)),
            ("production UI classification", (r"surface_kind:\s*production_ui.{0,120}qa_scope:\s*request",)),
            ("page contract audit", (r"audit.{0,80}(?:complete\s+)?in-page\s+contract",)),
            ("fingerprint audit", (r"dependency\s+fingerprint",)),
            ("targeted prototype reading", (r"must\s+not\s+preload.{0,120}complete\s+prototype",)),
            ("no prototype browser automation", (r"must\s+not\s+invoke\s+Computer\s+Use.{0,100}browser\s+automation.{0,80}prototype",)),
            ("production browser testing remains available", (r"browser\s+inspection.{0,160}real\s+production\s+implementation",)),
            (
                "requirements-confirmation prototype choice",
                (
                    r"(?:waived_by_user[\s\S]{0,260}prototype_decision|"
                    r"prototype_decision[\s\S]{0,260}waived_by_user)",
                ),
            ),
            ("ephemeral rendered-frame boundary", (r"rendered\s+frame.{0,80}ephemeral",)),
            ("no persisted rendered frame", (r"must\s+not.{0,80}(?:persist|save|write).{0,80}(?:that\s+)?frame",)),
        ),
        errors,
    )


def read_semantic_contract(path: Path, errors: list[str]) -> str:
    """把无效引用变为可操作的校验错误，不让缺失分支以 traceback 中断检查。"""
    try:
        if path.name == "AGENTS.claude.tpl":
            return read_instruction_contract(path.parents[2], "platforms/claude/AGENTS.claude.tpl")
        return read_instruction_contract(path.parent, path.name)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"cannot read Claude Skill contract {path}: {exc}")
        return ""


def validate_sources(pack: Path, errors: list[str]) -> None:
    errors.extend(validate_business_confirmation_pack(pack, "claude"))
    errors.extend(validate_pack_qa_review_policy(pack))
    claude_dir = pack / "platforms/claude"
    for name in CORE_SKILLS:
        path = skill_source(pack, name)
        if not path.is_file():
            errors.append(f"missing Claude Skill source: {path}")
            continue
        validate_skill(path, name, errors)
        # 必读验证策略等新引用也参加权限/记忆语义审计，不只校验文件存在和 frontmatter。
        scan_authority(path, errors)

    validate_role_sources(pack, errors)

    workflow = skill_source(pack, "xy-workflow")
    if workflow.is_file():
        body = read_semantic_contract(workflow, errors)
        required = (
            PRECEDENCE,
            # 三宿主共享 Skill 必须保留同一条“辅助信息按需读取”语义，不能只修改 Claude 模板。
            "Project documents (`PROJECT.md`, feature details, and requirement plans) and agentmemory are",
            "Activate `xy-project-memory` in start mode only when bounded cross-session recall or historical",
            "When no start retrieval ran, omit `memory_context`",
            "Claude Auto Memory",
            "ui-ux-pro-max",
            "grill-me",
            "skill_policy",
            "required_skills",
            "audit_surfaces",
            "Build a DAG",
            "Dispatch all currently ready independent tasks",
            "Re-evaluate downstream readiness after each completion",
            "capacity delay",
            "independent branches continue.",
            "current request dependency closure",
            "exactly one integrated read-only `xy-qa` reviewer for this request",
            "`installed-code-review-skill` proven installed and capable",
            "`internal-xy-qa-procedure`",
            "unrelated project work.",
            "After QA PASS, activate `xy-project-memory` in closeout mode",
            "report to the user",
        ) + STRICT_MEMORY_FIELDS
        for phrase in required:
            if phrase not in body:
                errors.append(f"xy-workflow missing contract phrase: {phrase}")
        if "Agent(" in body:
            errors.append("shared xy-workflow must remain host-neutral")
        for pattern, message in (
            (r"Wait for all project work\b", "xy-workflow contains a project-wide QA barrier"),
            (r"module QA for every task\b", "xy-workflow requires default module-level QA"),
            (r"independent branches wait\b", "xy-workflow blocks unrelated branches"),
        ):
            if re.search(pattern, body, re.I):
                errors.append(message)
        qa = body.find("After QA PASS")
        closeout = body.find("xy-project-memory", qa + 1)
        report = body.find("report to the user", closeout + 1)
        if min(qa, closeout, report) < 0 or not qa < closeout < report:
            errors.append("xy-workflow must order QA PASS -> memory closeout -> user report")

    memory = skill_source(pack, "xy-project-memory")
    if memory.is_file():
        body = memory.read_text(encoding="utf-8")
        for phrase in (
            PRECEDENCE,
            "call neither recall nor save",
            # Skill 保留完整能力，但开始检索只能由真实缺失事实或历史查询触发。
            "auxiliary information sources at task intake",
            "If start retrieval was not needed, omit `memory_context` entirely",
        ) + STRICT_MEMORY_FIELDS:
            if phrase not in body:
                errors.append(f"xy-project-memory missing contract phrase: {phrase}")

    qa = skill_source(pack, "xy-qa-review")
    if qa.is_file():
        body = read_semantic_contract(qa, errors)
        for phrase in (
            PRECEDENCE,
            # QA 不得为了填充旧 schema 反向强制 PM 查询记忆。
            "When no start retrieval ran, omit `memory_context`",
            "skills_used",
            "unavailable_required_skills",
            "uncovered_audit_surfaces",
        ) + STRICT_MEMORY_FIELDS:
            if phrase not in body:
                errors.append(f"xy-qa-review missing contract phrase: {phrase}")

    template = claude_dir / "AGENTS.claude.tpl"
    if not template.is_file():
        errors.append(f"missing Claude template: {template}")
    else:
        try:
            body = read_instruction_contract(pack, "platforms/claude/AGENTS.claude.tpl")
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"cannot read Claude bootstrap contract: {exc}")
            body = ""
        # Claude 官方只建议入口保持具体、简洁和结构化，没有 650 词或 6KB 的硬限制。
        # 这里继续校验语义、结构和去重，不再用任意字数阻断必要规则。
        normalized = " ".join(body.split())
        for phrase in (
            PRECEDENCE,
            "Claude Auto Memory",
            "/xy-workflow",
            "READY DAG",
            "Claude native Agents",
            "background Agent execution for currently READY independent tasks",
            "Grill Me coverage check",
            "plan_state: draft",
            "post-QA controlled-document projection",
            "last QA-verified state until integrated QA PASS",
            "`PROJECT.md` is the current verified project directory",
            "`*.removed.md`",
            "Superpowers is disabled by default",
            "exactly one `xy-qa` reviewer",
            "installed-code-review-skill",
            "internal-xy-qa-procedure",
            "requesting-code-review/code-reviewer.md",
            "Findings or `FAIL` never switch review method or reviewer",
        ):
            if phrase not in normalized:
                errors.append(f"CLAUDE template missing phrase: {phrase}")
        if "Agent(xy_" in body:
            errors.append("CLAUDE template uses invalid underscore Agent names")
        for forbidden in ("{{SCOPE_TABLE}}", "## Generated role scopes"):
            if forbidden in body:
                errors.append(
                    f"CLAUDE template must keep ProjectProfile detail in PM task packs: {forbidden}"
                )

    validate_latest_ui_semantics(pack, errors)

    authority_paths = [
        template,
        skill_source(pack, "xy-workflow"),
        skill_source(pack, "xy-project-memory"),
        skill_source(pack, "xy-qa-review"),
        pack / "roles/xy-qa.md",
    ]
    for path in authority_paths:
        if path.is_file():
            scan_authority(path, errors)

    for path in (skill_source(pack, "xy-workflow"), memory, qa):
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        for hardcoded in (
            "docs/PROJECT.md",
            "docs/features/",
            "docs/STATUS.md",
            "docs/notes/",
            "docs/design/",
        ):
            if hardcoded in body:
                errors.append(f"Claude runtime hardcodes adapter path {hardcoded}: {path}")


def validate_agent(path: Path, role: str, project_root: Path, errors: list[str], expected_window: int | None = None) -> None:
    fields, all_after = parse_frontmatter(path, errors)
    expected_name = claude_agent_name(role)
    if fields.get("name") != expected_name:
        errors.append(f"Agent name mismatch for {path}: {fields.get('name')!r}")
    if not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", fields.get("name", "")):
        errors.append(f"Agent name must use lowercase letters and hyphens: {path}")
    if not fields.get("description"):
        errors.append(f"Agent description is empty: {path}")
    unsupported = sorted(set(fields) - ALLOWED_AGENT_KEYS)
    if unsupported:
        errors.append(f"unsupported Agent frontmatter in {path}: {', '.join(unsupported)}")
    if "Skill" not in fields.get("tools", ""):
        errors.append(f"Agent lacks Skill tool: {path}")
    if fields.get("disallowedTools") != "Agent":
        errors.append(f"Agent must disallow nested Agent delegation: {path}")
    if fields.get("color") not in ALLOWED_AGENT_COLORS:
        errors.append(f"Agent has unsupported Claude color: {path}")
    if fields.get("permissionMode") != "default":
        errors.append(f"Agent permissionMode must remain default: {path}")
    # Claude 的角色定义允许完整模型 ID；代理写入的自定义 ID 不应被别名白名单拒绝。
    try:
        validate_model_settings("claude", {"model": fields.get("model"), "effort": fields.get("effort", "inherit")})
    except ValueError:
        errors.append(f"Agent has unsupported model or effort: {path}")
    if not re.fullmatch(r"[1-9][0-9]*", fields.get("maxTurns", "")):
        errors.append(f"Agent maxTurns must be an integer >= 1: {path}")
    tools = {item.strip() for item in fields.get("tools", "").split(",") if item.strip()}
    if not tools or not tools.issubset(ALLOWED_GENERATED_TOOLS):
        errors.append(f"Agent has unsupported tools: {path}")
    body = read_exact_utf8(path, "generated Claude Agent", errors)
    if body is None:
        return
    # 复用安全读取后的正文，核对精确值；移除配置后遗留的窗口也必须报漂移。
    try:
        if frontmatter_window(body.encode("utf-8")) != expected_window:
            errors.append(f"Agent autoCompactWindow differs from project configuration: {path}")
    except ValueError:
        errors.append(f"Agent has invalid autoCompactWindow: {path}")
    if AGENT_MARKER not in body:
        errors.append(f"missing managed Agent marker: {path}")
    if body.count("## PM task-pack boundary (generated)") != 1:
        errors.append(f"Agent must contain exactly one PM task-pack boundary: {path}")
    for phrase in ("ProjectProfile routing evidence", "exact `owned_paths`"):
        if phrase not in body:
            errors.append(f"Agent task-pack boundary missing {phrase!r}: {path}")
    for fragment in FORBIDDEN_GENERATED_AGENT_FRAGMENTS:
        if fragment in body:
            errors.append(
                f"Agent embeds duplicated static context {fragment!r}: {path}"
            )
    frontmatter_lines = body.split("\n---\n", 1)[0].splitlines()[1:]
    for name in list_field(frontmatter_lines, "skills"):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            errors.append(f"Agent {role} has invalid Skill name: {name}")
        if name.startswith("xy-") and not (
            project_root / ".claude/skills" / name / "SKILL.md"
        ).is_file():
            errors.append(f"Agent {role} references missing project Skill: {name}")
    scan_authority(path, errors)


def validate_generated(
    pack: Path,
    project_root: Path,
    roles: tuple[str, ...],
    errors: list[str],
) -> None:
    validate_sources(pack, errors)
    # 独立 generated 校验也覆盖当前共享区块和宿主路由，不能只依赖外层安装脚本。
    # 复用只读 check：缺少共享边界、入口漂移或危险文件都会拒绝，绝不补写产物。
    try:
        # 和入口 CLI 一样先规范化 macOS /var → /private/var 这类系统路径别名。
        # 具体文件仍走入口生成器的链接、节点身份和所有权检查。
        check_instruction_entry(pack.resolve(), project_root.resolve(), "check")
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"generated shared/Claude bootstrap differs from current contract: {exc}")
    # 独立校验 CLI 同样要求精确的一行导入：缺失入口、普通文字指路、
    # 代码围栏或复制一份正文都不符合“唯一规则正文”的安装合同。
    entry = project_root.resolve() / "CLAUDE.md"
    try:
        # 与安装器复用同一安全读取：不能让独立校验接受安装器拒绝的
        # 硬链接、符号链接或特殊文件，也避免读取无界的伪入口。
        entry_body = read_file(entry)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"cannot read generated CLAUDE.md thin entry: {exc}")
    else:
        if entry_body is None:
            errors.append(f"missing generated CLAUDE.md thin entry: {entry}")
        elif entry_body != CLAUDE_IMPORT:
            errors.append("CLAUDE.md must contain exactly @AGENTS.md followed by a newline")
    claude_md = project_root / "AGENTS.md"
    if not claude_md.is_file():
        errors.append(f"missing generated AGENTS.md: {claude_md}")
    else:
        body = read_exact_utf8(claude_md, "generated AGENTS.md", errors)
        if body is None:
            body = ""
        if body.count(CLAUDE_BEGIN) != 1 or body.count(CLAUDE_END) != 1:
            errors.append("AGENTS.md must have exactly one Claude managed marker pair")
        elif body.index(CLAUDE_BEGIN) > body.index(CLAUDE_END):
            errors.append("AGENTS.md Claude managed markers are reversed")
        # 标记边界与源一致性才是安装正确性的硬条件；内容长度只做维护时的压缩目标。
        scan_authority(claude_md, errors)

    skill_root = project_root / ".claude/skills"
    expected = set(CORE_SKILLS)
    for name in CORE_SKILLS:
        src = skill_source(pack, name)
        dest = skill_root / name / "SKILL.md"
        if not dest.is_file():
            errors.append(f"missing generated Skill: {dest}")
            continue
        validate_skill(dest, name, errors)
        if dest.read_bytes() != src.read_bytes():
            errors.append(f"generated Skill differs from source: {dest}")
        scan_authority(dest, errors)
    if skill_root.is_dir():
        for dest in skill_root.glob("*/SKILL.md"):
            if dest.is_symlink() or dest.parent.is_symlink():
                continue
            body = dest.read_text(encoding="utf-8", errors="replace")
            if SKILL_MARKER in body and dest.parent.name not in expected:
                errors.append(f"stale managed Claude Skill: {dest}")
    agent_root = project_root / ".claude/agents"
    try:
        windows = parse_claude_options((pack / "project.yaml").read_text(encoding="utf-8"))["auto_compact_windows"]
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(str(exc))
        return
    for role in roles:
        path = agent_root / f"{claude_agent_name(role)}.md"
        if not path.is_file():
            errors.append(f"missing generated Agent: {path}")
            continue
        validate_agent(path, role, project_root, errors, windows.get(role))
    if agent_root.is_dir():
        paths = {*agent_root.glob("xy-*.md"), *agent_root.glob("xy_*.md")}
        enabled_names = {claude_agent_name(role) for role in roles}
        for path in paths:
            if path.is_symlink():
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            if AGENT_MARKER in body and path.stem not in enabled_names:
                errors.append(f"stale managed Claude Agent: {path}")


def main() -> int:
    if len(sys.argv) not in {4, 5} or sys.argv[1] not in {"sources", "generated"}:
        print(
            "usage: validate_claude_artifacts.py sources|generated "
            "PACK_DIR OUTPUT_ROOT [DISCOVERY_ROOT]",
            file=sys.stderr,
        )
        return 2
    mode, pack, project_root = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    discovery_root = Path(sys.argv[4]) if len(sys.argv) == 5 else project_root
    errors: list[str] = []
    roles = discovered_roles(pack, discovery_root, errors)
    validate_managed_output_paths(project_root, roles, errors)
    if mode == "sources":
        validate_sources(pack, errors)
    else:
        validate_generated(pack, project_root, roles, errors)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print(f"[OK] Claude {mode} contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
