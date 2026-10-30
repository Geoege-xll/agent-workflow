#!/usr/bin/env python3
"""Render one enabled role as an official static Antigravity Agent.

The renderer writes only to stdout.  Callers can therefore stage the complete output
and publish it only after the strict Antigravity validator accepts the staging tree.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from project_discovery import ProjectProfile
from validate_project_config import validate_with_profile
from role_models import settings as model_settings

from validate_antigravity_artifacts import (
    AGENT_MARKER,
    IMPLEMENTER_ROLES,
    ROLE_SKILLS,
    ROLE_TOOLS,
    SecureReadError,
    render_antigravity_host_aliases,
    require_real_root,
    role_descriptions,
    secure_read_text,
)


ROLE_NAME_RE = re.compile(r"^xy-[a-z0-9]+(?:-[a-z0-9]+)*$")


class RenderError(ValueError):
    """A controlled role source cannot be rendered safely."""


def role_description(pack: Path, role: str) -> str:
    errors: list[str] = []
    descriptions = role_descriptions(pack, [role], errors)
    if errors or role not in descriptions:
        raise RenderError("; ".join(errors) or f"missing role description for {role}")
    return descriptions[role]


def role_markdown_body(pack: Path, role: str) -> str:
    relative = Path("roles") / f"{role}.md"
    body = secure_read_text(pack, relative, f"role source {role}")
    lines = body.splitlines()
    if not lines or lines[0] != "---":
        raise RenderError(f"missing opening role frontmatter delimiter: {relative}")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise RenderError(f"missing closing role frontmatter delimiter: {relative}") from exc
    rendered = "\n".join(lines[closing + 1 :]).strip()
    if not rendered:
        raise RenderError(f"empty role body: {relative}")
    return render_antigravity_host_aliases(rendered)


def project_profile(pack: Path) -> ProjectProfile:
    result = validate_with_profile(pack / "project.yaml", pack.parent, pack / "roles")
    if result.errors or result.profile is None:
        raise RenderError(
            "cannot render invalid discovered project profile: "
            + "; ".join(result.errors or ("profile is missing",))
        )
    return result.profile


def execution_contract(role: str) -> str:
    # Antigravity 会把本段与完整角色正文一起注入静态上下文，因此这里必须只保留宿主边界，
    # 不能重复角色文件已经定义的执行流程。压缩的是重复措辞，不削弱 PM 权威、禁止嵌套委派、
    # 只向 PM 回传以及缺少权威/证据/Gate 时阻塞这四项安全约束。
    common = f"""## Antigravity execution contract
You are `{role}`; PM owns routing.
Execute only the PM task pack. Its `controlled_document_access`, discovered facts, exact owned paths,
gates, and native verification commands are authoritative; ProjectProfile is routing only. Never delegate or contact Agents.
Return the result to the PM only. Do not report completion directly to the user.
Block on missing authority/evidence/gates.
When execution_workspace is present, verify the actual root/base and keep edits and commands there.
Never independently commit, merge, or remove worktrees; PM owns transport checkpoints and delivery.
QA uses its assigned integration root read-only.
"""
    return common.strip()


def role_boundary(role: str) -> str:
    if role in IMPLEMENTER_ROLES:
        return """## Antigravity handoff

Read the Task Pack's STANDARDS index and selected applicable leaves before editing. Return
`/xy-build-verify` evidence to the PM; if it is not green, report IN_PROGRESS or BLOCKED.
""".strip()
    if role == "xy-uiux":
        return """## Antigravity UIUX boundary

- Write only task-owned paths in `docs.standards_root/prototype`; other design-standard
  leaves require explicit authority,
  never production UI. Invoke `ui-ux-pro-max`, or block if it is unavailable.
- Return direct links for every concrete changed HTML page and its verified page
  dependency fingerprint, scope, interactions, shared impact, and pending `visual_approved`.
- These prototype deliverables apply only to prototype mode. With `design_mode: standards_only`,
  write only authorized normative Markdown leaves and return rule-delta/document evidence; do not
  invoke `xy-prototype-verify`, write prototype files, or request a visual gate.
- The root prototype index alone is not sufficient. Prototype verification MUST NOT invoke Computer Use or `/browser` by default; only an explicit user request or diagnosis of a user-reported prototype failure permits the smallest scoped operation.
- MUST NOT generate, persist, attach, or present screenshots.
""".strip()
    if role == "xy-qa":
        return """## Antigravity read-only QA boundary
- Final QA outcome: PASS | FAIL; report to the PM only. Do not edit production business code/files.
  Do not command implementers; return rework to PM.
- Apply required Skills/surfaces; missing Skills block PASS. Never scan/save Skill inventories.
- Prototype review MUST NOT invoke Computer Use or `/browser`. Risk-based browser inspection applies
  only to the real production implementation. A rendered frame ephemerally in memory is
  inspection-only; QA must not persist, save, write, attach, present, or use it as approval evidence.
""".strip()
    raise RenderError(f"no Antigravity body boundary for {role}")


def render(pack: Path, role: str) -> str:
    if not ROLE_NAME_RE.fullmatch(role):
        raise RenderError(f"role must use lowercase hyphens: {role!r}")
    profile = project_profile(pack)
    roles = profile.enabled_roles
    if role not in roles:
        raise RenderError(f"role is not selected by the discovered ProjectProfile: {role}")
    if role not in ROLE_TOOLS or role not in ROLE_SKILLS:
        raise RenderError(f"no approved Antigravity policy for role: {role}")

    description = role_description(pack, role)
    tools = ROLE_TOOLS[role]
    skills = ROLE_SKILLS[role]
    role_body = role_markdown_body(pack, role)

    tool_lines = "".join(f"  - {tool}\n" for tool in tools)
    skill_lines = "".join(f"  - {skill}\n" for skill in skills)
    frontmatter = (
        "---\n"
        f"name: {role}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "tools:\n"
        f"{tool_lines}"
        "mainAgent: false\n"
        "subagent: true\n"
        f"model: {model_settings(pack, 'antigravity', role)['model']}\n"
        "commandExecutionPolicy: sandbox\n"
        "skills:\n"
        f"{skill_lines}"
        "---"
    )
    sections = (
        frontmatter,
        AGENT_MARKER,
        execution_contract(role),
        role_body,
        role_boundary(role),
    )
    return "\n\n".join(sections) + "\n"


def render_product_template(pack: Path) -> str:
    return secure_read_text(
        pack,
        Path("platforms/shared/AGENTS.product.tpl"),
        "shared product template",
    )


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) == 2 and arguments[0] == "--roles":
        pack = Path(arguments[1])
        try:
            require_real_root(pack, "workflow pack root")
            profile = project_profile(pack)
        except (OSError, UnicodeError, SecureReadError, RenderError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        for role in profile.enabled_roles:
            print(role)
        return 0
    if len(arguments) == 2 and arguments[0] == "--product-template":
        pack = Path(arguments[1])
        try:
            require_real_root(pack, "workflow pack root")
            output = render_product_template(pack)
        except (OSError, UnicodeError, SecureReadError, RenderError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        sys.stdout.write(output)
        return 0
    if len(arguments) != 2:
        print(
            "usage: render_antigravity_agent.py PACK_DIR ROLE | --roles PACK_DIR | "
            "--product-template PACK_DIR",
            file=sys.stderr,
        )
        return 2
    pack = Path(arguments[0])
    try:
        require_real_root(pack, "workflow pack root")
        output = render(pack, arguments[1])
    except (OSError, UnicodeError, SecureReadError, RenderError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
