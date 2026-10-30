from __future__ import annotations

import itertools
import os
import re
import stat
import shutil
import subprocess
import sys
# 子进程使用 sys.executable，保持与统一运行时入口选择的解释器一致。
import tempfile
import tomllib
import unittest
import uuid
from dataclasses import FrozenInstanceError
from pathlib import Path
from tests.skill_contract_helpers import read_bootstrap_contract, read_contract
from unittest import mock

import lib.project_discovery as project_discovery

from lib.project_discovery import (
    DiscoveryError,
    DiscoveryOverrides,
    ModuleOverride,
    ModuleProfile,
    ProjectProfile,
    VerificationCommand,
    discover_project,
)
from lib.qa_review_policy import validate_pack_qa_review_policy
from lib.validate_project_docs import validate as validate_project_docs


PACK = Path(__file__).resolve().parents[1]
HOSTS = ("claude", "codex", "antigravity")

PORTABLE_WORKER_ROLE_IDS = frozenset(
    {
        "xy-web",
        "xy-desktop",
        "xy-backend",
        "xy-apple",
        "xy-android",
        "xy-uiux",
        "xy-qa",
    }
)
RETIRED_LANGUAGE_ROLE_IDS = frozenset({"xy-python", "xy-rust", "xy-java"})

TASK5_CANONICAL_ROLE_IDS = (
    "xy-web",
    "xy-desktop",
    "xy-backend",
    "xy-apple",
    "xy-android",
    "xy-uiux",
    "xy-qa",
)
TASK5_ROLE_H2S = (
    "## 1. Identity and Professional Character",
    "## 2. Core Mission",
    "## 3. Repository-Driven Expertise",
    "## 4. Critical Operating Rules",
    "## 5. Task Intake Contract",
    "## 6. Execution Workflow",
    "## 7. Technical Deliverables",
    "## 8. Verification and Evidence",
    "## 9. Communication Style",
    "## 10. Memory Contract",
    "## 11. Success Criteria",
    "## 12. Routing",
)

# These locations are the live inputs used to validate, route, render, or install
# worker roles. Deliberately exclude historical plans and tests: a migration note or
# a negative assertion about a retired role is not an active routing reference.
ACTIVE_ROLE_AUTHORITY_ROOTS = (
    "product",
    "roles",
    "platforms",
    "lib",
    "scripts",
    "templates",
)
ACTIVE_ROLE_AUTHORITY_SUFFIXES = frozenset(
    {".md", ".yaml", ".yml", ".tpl", ".py", ".sh", ".toml"}
)
# Keep this list explicit.  These are the canonical and host-facing sources that can
# independently retain a stale UI workflow contract even when another source is fixed.
ACTIVE_UI_CONTRACT_SOURCES = (
    "product/WORKFLOW.md",
    "product/AGENT_SCHEMA.md",
    "product/GLOBAL_CONSTRAINTS.md",
    "product/ROLES.yaml",
    "roles/xy-uiux.md",
    "roles/xy-web.md",
    "roles/xy-qa.md",
    "platforms/shared/AGENTS.product.tpl",
    "platforms/shared/skills/xy-workflow/SKILL.md",
    "platforms/shared/skills/xy-prototype-verify/SKILL.md",
    "platforms/shared/skills/xy-project-memory/SKILL.md",
    "platforms/shared/skills/xy-qa-review/SKILL.md",
    "platforms/codex/AGENTS.codex.tpl",
    "platforms/claude/AGENTS.claude.tpl",
    "platforms/antigravity/AGENTS.antigravity.tpl",
    "setup_codex.sh",
    "setup_claude.sh",
    "setup_antigravity.sh",
    "lib/render_antigravity_agent.py",
)

# Task 2 owns only the canonical product and role layer. Keep this checkpoint separate
# from ACTIVE_UI_CONTRACT_SOURCES, which remains the final Task 9 integration union.
TASK2_CANONICAL_SOURCES = (
    "product/WORKFLOW.md",
    "product/AGENT_SCHEMA.md",
    "product/GLOBAL_CONSTRAINTS.md",
    "product/ROLES.yaml",
    "roles/xy-uiux.md",
    "roles/xy-web.md",
    "roles/xy-qa.md",
)

TASK2_CANONICAL_MATRIX = {
    "product/WORKFLOW.md": (
        "page dependency fingerprint",
        "$xy-prototype-verify",
        "safe local transitive dependency closure",
        "length-delimited path bytes and content bytes",
        "not a manual `rN`",
        "creates no Manifest or metadata file",
        "Web implementation and QA recompute it",
        "ui_only_gates:",
        '"visual_approved:<page-id>@<dependency-fingerprint>"',
        "`docs.standards_root/DESIGN_*.md`; it never modifies",
    ),
    "product/AGENT_SCHEMA.md": (
        "dependency_fingerprint:",
        "product/WORKFLOW.md",
        "PM metadata is outside the ordinary role schema",
    ),
    "product/GLOBAL_CONSTRAINTS.md": (
        "task pack",
        "ui_only_gates:",
    ),
    "product/ROLES.yaml": (
        "xy-uiux:",
        "xy-web:",
        "xy-qa:",
        "toolsets: read",
    ),
    "roles/xy-uiux.md": (
        "dependency fingerprints",
        "shared rule justified by multiple pages",
        "$xy-prototype-verify",
    ),
    "roles/xy-web.md": (
        "page dependency fingerprint",
        "$xy-build-verify",
    ),
    "roles/xy-qa.md": (
        "page dependency fingerprint",
        "rendered frame ephemerally",
    ),
}

# This source is intentionally retired by the new contract.  Include it while it still
# exists so its stale language cannot be hidden merely by fixing the primary role file.
RETIRED_UI_CONTRACT_SOURCES = ("templates/docs/design/README.md",)

WORKSPACE_CONTRACT_MATRIX = {
    "product/WORKFLOW.md": (
        "docs/standards/prototype/index.html",
        "docs/standards/prototype/prototype.css",
        "Page design and interaction contract",
    ),
    "product/AGENT_SCHEMA.md": (
        "docs/standards/prototype/index.html",
        "dependency_fingerprint:",
    ),
    "roles/xy-uiux.md": (
        "index.html",
        "prototype.css",
        "Page design and interaction contract",
    ),
    "roles/xy-web.md": ("Page design and interaction contract",),
    "roles/xy-qa.md": ("in-page contract",),
    "platforms/shared/skills/xy-workflow/SKILL.md": (
        "Page design and interaction contract",
    ),
    "platforms/shared/skills/xy-prototype-verify/SKILL.md": (
        "docs/standards/prototype/index.html",
        "docs/standards/prototype/prototype.css",
        "Page design and interaction contract",
    ),
    "platforms/shared/skills/xy-qa-review/SKILL.md": (
        "Page design and interaction contract",
    ),
}

SECTION_CONTRACT_SOURCES = (
    "roles/xy-uiux.md",
    "platforms/shared/skills/xy-prototype-verify/SKILL.md",
)

CANONICAL_SCREENSHOT_PROHIBITION = (
    "MUST NOT generate, persist, attach, or present screenshots"
)
SCREENSHOT_PROHIBITION_SOURCES = (
    "product/WORKFLOW.md",
    "product/GLOBAL_CONSTRAINTS.md",
    "roles/xy-uiux.md",
    "platforms/shared/AGENTS.product.tpl",
    "platforms/shared/skills/xy-workflow/SKILL.md",
    "platforms/shared/skills/xy-prototype-verify/SKILL.md",
    "platforms/shared/skills/xy-project-memory/SKILL.md",
    "platforms/shared/skills/xy-qa-review/SKILL.md",
)

DIRECT_PAGE_HANDOFF_SENTENCE = (
    "The PM MUST provide a direct link to each concrete changed page."
)
ROOT_INDEX_HANDOFF_SENTENCE = (
    "The root prototype index alone is not sufficient."
)
STANDARD_VISUAL_HANDOFF_SENTENCES = (
    DIRECT_PAGE_HANDOFF_SENTENCE,
    ROOT_INDEX_HANDOFF_SENTENCE,
)

VISUAL_HANDOFF_MATRIX = {
    "product/WORKFLOW.md": STANDARD_VISUAL_HANDOFF_SENTENCES,
    "roles/xy-uiux.md": (
        "direct link to each concrete changed page",
        "root index alone is insufficient",
    ),
    "platforms/shared/AGENTS.product.tpl": STANDARD_VISUAL_HANDOFF_SENTENCES,
    "platforms/shared/skills/xy-workflow/SKILL.md": STANDARD_VISUAL_HANDOFF_SENTENCES,
    "platforms/shared/skills/xy-prototype-verify/SKILL.md": (
        STANDARD_VISUAL_HANDOFF_SENTENCES
    ),
}

# Host wrappers compose the shared role and bootstrap sources.  Task 6 validates the
# resulting generated artifacts; these structural anchors avoid requiring wrappers to
# duplicate the full portable contract in host-native source code.
HOST_RENDERER_COMPOSITION_MATRIX = {
    "setup_codex.sh": (
        'src="${ROLES_DIR}/${role}.md"',
        'codex_role_body "${src}"',
        'cat "${PRODUCT_TPL}"',
        'cat "${CODEX_TPL}"',
    ),
    "setup_claude.sh": (
        'src="${ROLES_DIR}/${role}.md"',
        'render_claude_role_body "${src}"',
        'template = Path(os.environ["TPL"]).read_text',
    ),
    "lib/render_antigravity_agent.py": (
        "role_body = role_markdown_body(pack, role)",
        "role_body,",
        'Path("platforms/shared/AGENTS.product.tpl")',
    ),
    "setup_antigravity.sh": (
        'python3 "${RENDERER}" "${PACK_DIR}" "${role}"',
        'cat "${PLATFORMS_DIR}/shared/AGENTS.product.tpl"',
        'cat "${ANTI_TPL}"',
    ),
}

TASK5_SHARED_SKILL_MATRIX = {
    "platforms/shared/skills/xy-workflow/SKILL.md": (
        "The active concrete page and its in-page `Page design and interaction contract` are the design evidence.",
        DIRECT_PAGE_HANDOFF_SENTENCE,
        ROOT_INDEX_HANDOFF_SENTENCE,
        "QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report",
    ),
    "platforms/shared/skills/xy-prototype-verify/SKILL.md": (
        "bash .agent-workflow/lib/python_runtime.sh .agent-workflow/lib/validate_prototype_workspace.py",
        "docs/standards/prototype/index.html",
        "docs/standards/prototype/prototype.css",
        "Page design and interaction contract",
        'data-contract-section="purpose"',
        'data-contract-section="navigation"',
        'data-contract-section="interactions"',
        'data-contract-section="states"',
        'data-contract-section="exceptions"',
        DIRECT_PAGE_HANDOFF_SENTENCE,
        ROOT_INDEX_HANDOFF_SENTENCE,
        "page dependency fingerprint",
    ),
    "platforms/shared/skills/xy-project-memory/SKILL.md": (
        "stable concrete page references",
        "approval remains in workflow task state",
        "prototype_refs:",
        "`docs.project` and active feature documents",
    ),
    "platforms/shared/skills/xy-qa-review/SKILL.md": (
        "Page design and interaction contract",
        "page dependency fingerprint",
        "rendered frame ephemerally",
        "no screenshot artifact on disk",
        "Final QA outcome: PASS | FAIL",
        "concise task handoff",
    ),
    "platforms/shared/skills/xy-build-verify/SKILL.md": (
        "QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report",
    ),
}

TASK5_NO_COMPANION_ARTIFACT_MATRIX = {
    "platforms/shared/skills/xy-workflow/SKILL.md": (
        "Do not create companion design, mapping, or baseline Markdown",
        "a Manifest",
        "a screenshot directory",
    ),
    "platforms/shared/skills/xy-prototype-verify/SKILL.md": (
        "Do not create companion design, mapping, QA, or baseline Markdown",
        "a Manifest",
        "a screenshot directory",
        "any other companion metadata",
    ),
    "platforms/shared/skills/xy-project-memory/SKILL.md": (
        "Do not create companion design, mapping, QA, or baseline Markdown",
        "a Manifest",
        "empty memory/document entry",
    ),
    "platforms/shared/skills/xy-qa-review/SKILL.md": (
        "no companion QA, baseline, mapping, or design Markdown",
        "no Manifest",
        "no visual-capture directory",
    ),
    "platforms/shared/skills/xy-build-verify/SKILL.md": (
        "creates no QA report, design artifact, approval record, or metadata file",
    ),
}

TASK6_CONTRACT_SECTION_ANCHORS = (
    'data-contract-section="purpose"',
    'data-contract-section="navigation"',
    'data-contract-section="interactions"',
    'data-contract-section="states"',
    'data-contract-section="exceptions"',
)
TASK6_PRODUCTION_BOUNDARY_SENTENCE = (
    "Production MUST NOT copy prototype-only mock data, fake APIs, demo timers, runtime, "
    "persistence, routing, debug controls, state controls, `data-prototype-*`, or in-page "
    "design-contract markup."
)
TASK6_PROTOTYPE_ONLY_TARGETS = (
    "mock data",
    "fake apis",
    "demo timers",
    "runtime",
    "persistence",
    "routing",
    "debug controls",
    "state controls",
    "data-prototype-*",
    "in-page design-contract markup",
)

TASK6_SHARED_BOOTSTRAP_ANCHORS = (
    "The PM is the sole orchestrator.",
    "For non-trivial work, activate `xy-workflow` before editing production paths.",
    "READY independent tasks",
    "no nested Agent delegation",
    "ProjectProfile is soft routing context, never write authority.",
    "requirements_approved",
    "visual_approved:<page-id>@<dependency-fingerprint>",
    "Grill Me",
    "Superpowers",
    "`project.yaml` → `docs.standards_root/prototype/` is the stable prototype workspace.",
    "Page design and interaction contract",
    DIRECT_PAGE_HANDOFF_SENTENCE,
    ROOT_INDEX_HANDOFF_SENTENCE,
    CANONICAL_SCREENSHOT_PROHIBITION,
    "Do not create a Manifest",
    "exactly one `xy-qa`",
    "Final QA outcome: PASS | FAIL",
    "QA PASS → controlled-document projection → PM commit assessment → `xy-project-memory` closeout → final user report",
)

TASK6_DETAILED_SKILL_MATRIX = {
    "platforms/shared/skills/grill-me/SKILL.md": (
        "coverage_check",
        "full_interview",
        "ready_for_planning",
        "must not plan, edit PROJECT/feature truth, dispatch Agents, or approve requirements",
    ),
    "platforms/shared/skills/xy-plan/SKILL.md": (
        "Superpowers writing-plans",
        "exact owned paths",
        "semantic_locks",
        "expected output",
        "plan_state: draft",
        "requirements_fingerprint",
        "must not edit files, dispatch Agents, update PROJECT/feature truth, or request approval",
    ),
    "platforms/shared/skills/xy-workflow/SKILL.md": (
        "Build a DAG",
        "Dispatch all currently ready independent tasks",
        "Re-evaluate downstream readiness after each completion",
        "filter_enforced:",
    ),
    "platforms/shared/skills/xy-prototype-verify/SKILL.md": (
        *TASK6_CONTRACT_SECTION_ANCHORS,
        "safe local transitive dependency closure",
    ),
    "platforms/shared/skills/xy-qa-review/SKILL.md": (
        "host-native-review",
        "installed-code-review-skill",
        "internal-xy-qa-procedure",
        "prototype-only mock data, fake APIs, demo timers",
    ),
    "platforms/shared/skills/xy-project-memory/SKILL.md": (
        "filter_enforced:",
        "provenance_refs:",
        "QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report",
    ),
}

TASK6_BOOTSTRAP_PROCEDURE_DETAILS = (
    *TASK6_CONTRACT_SECTION_ANCHORS,
    "host-native-review",
    "installed-code-review-skill",
    "internal-xy-qa-procedure",
    "filter_enforced:",
    "provenance_refs:",
    TASK6_PRODUCTION_BOUNDARY_SENTENCE,
)

LIGHTWEIGHT_SKILL_POLICY_SOURCES = (
    "product/WORKFLOW.md",
    "product/AGENT_SCHEMA.md",
    "platforms/shared/skills/xy-workflow/SKILL.md",
    "platforms/shared/skills/xy-qa-review/SKILL.md",
)

LIGHTWEIGHT_SKILL_POLICY_ANCHORS = (
    "external_workflow_policy:",
    "requirements_provider: grill-me",
    "planning_provider: xy-plan",
    "planning_methodology: superpowers-writing-plans-adapted",
    "superpowers_default: disabled",
    "parallel_scheduler: deterministic-pm-ready-dag",
    "parallel_provider: host-native-agents",
)

QA_REVIEW_METHOD_POLICY_ANCHORS = (
    "qa_review_policy:",
    "owner: xy-qa",
    "max_active_reviewers: 1",
    "method_selection_order:",
    "host-native-review",
    "installed-code-review-skill",
    "internal-xy-qa-procedure",
    "external_skill_selection: installed-and-capable-only",
    "requesting-code-review/code-reviewer.md",
    "fallback_on_technical_unavailability_only: true",
    "findings_or_fail_do_not_trigger_fallback: true",
)

QA_REVIEW_METHODS = (
    "host-native-review",
    "installed-code-review-skill",
    "internal-xy-qa-procedure",
)

QA_REVIEW_POLICY_BLOCK = """qa_review_policy:
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

QA_REVIEW_METHOD_CLAUSE = (
    "`host-native-review`, then one `installed-code-review-skill` proven installed and capable, "
    "then `internal-xy-qa-procedure`, moving forward only on technical unavailability."
)

QA_REVIEW_POLICY_DUPLICATE_SUFFIXES = {
    "double-quoted-key": '\n"qa_review_policy": {}\n',
    "single-quoted-key": "\n'qa_review_policy': {}\n",
    "spaced-key": "\nqa_review_policy : {}\n",
    "inline-map-key": "\nmetadata: {qa_review_policy: {owner: xy-qa}}\n",
    "inline-comment-key": "\nqa_review_policy: {} # duplicate\n",
    "quoted-flow-map-key": '\nmetadata: {"qa_review_policy" : {owner: xy-qa}}\n',
    "commented-key": "\n# qa_review_policy: disabled\n",
}

RETIRED_QA_POLICY_TERMS = (
    "xy-qa-" + "direct-review",
    "superpowers-" + "requesting-code-review",
    "review_" + "provider",
    "max_active_" + "providers",
    "fallback_on_" + "provider_failure_only",
)

NATIVE_BUG_FIX_ANCHORS = (
    "native_bug_fix:",
    "reproduce_exact_symptom",
    "minimize_reproduction",
    "identify_root_cause",
    "add_regression_evidence",
    "implement_minimal_fix",
    "run_selected_repository_verification",
    "request_unified_qa",
)

TASK6_HOST_NEUTRAL_INVOCATIONS = (
    "`xy-workflow`",
    "`xy-uiux`",
    "`xy-prototype-verify`",
    "`xy-web`",
    "`xy-build-verify`",
    "`xy-qa`",
    "`xy-project-memory`",
)


def normalized_contract_text(text: str) -> str:
    return " ".join(text.split())


def is_canonical_screenshot_prohibition(text: str) -> bool:
    normalized = normalized_contract_text(text)
    if CANONICAL_SCREENSHOT_PROHIBITION not in normalized:
        return False
    lowered = normalized.casefold()
    return re.search(
        r"\bscreen[- ]?shots?\b[^.]{0,120}\b(?:except|unless|optional|fallback)\b",
        lowered,
    ) is None


def is_screenshot_allowance_or_fallback(text: str) -> bool:
    normalized = normalized_contract_text(text).casefold()
    if not re.search(r"\bscreen[- ]?shots?\b|\bscreen captures?\b", normalized):
        return False
    inverted_omission = re.search(
        r"\bmust not omit\b[^.]{0,80}\bscreen[- ]?shots?\b|"
        r"\bscreen[- ]?shots?\b[^.]{0,80}\b(?:must not|cannot) be omitted\b",
        normalized,
    )
    conditional_exception = re.search(
        r"\bscreen[- ]?shots?\b[^.]{0,120}\b(?:except|unless|optional|fallback)\b",
        normalized,
    )
    if inverted_omission or conditional_exception:
        return True
    if is_canonical_screenshot_prohibition(text):
        return False
    alternative_prohibition = re.search(
        r"\bscreen[- ]?shot(?: output| capture| generation)? is disallowed\b|"
        r"\bavoid all screen[- ]?shots?\b|"
        r"\bscreen[- ]?shot capture is disabled\b|"
        r"\bmust not\b[^.]{0,120}\bscreen[- ]?shots?\b|"
        r"\bscreen[- ]?shots?\b[^.]{0,120}\bmust not\b",
        normalized,
    )
    if alternative_prohibition:
        return False
    if re.search(r"\bvalidate without screen[- ]?shots?\b", normalized):
        return False
    explicit_requirement_or_inversion = re.search(
        r"\bcannot be omitted\b|\bnot (?:forbidden|prohibited)\b|"
        r"\bcontinue without\b.*\bwhen possible\b",
        normalized,
    )
    if explicit_requirement_or_inversion:
        return True
    explicit_allowance = re.search(
        r"\b(?:optional|may|can|unless|except|only when|fallback)\b|"
        r"\bonly if\b",
        normalized,
    )
    evidence_allowance = re.search(
        r"\bscreen[- ]?shots?\b[^.]{0,80}\b(?:evidence|fallback)\b",
        normalized,
    )
    capture_action = re.search(
        r"\b(?:generate|capture|persist|save|write|attach|present|provide|return|supply|use)\b"
        r"[^.]{0,120}\bscreen[- ]?shots?\b|"
        r"\bscreen[- ]?shots?\b[^.]{0,120}"
        r"\b(?:generate|capture|persist|save|write|attach|present|provide|return|supply|use)\b",
        normalized,
    )
    return bool(explicit_allowance and (capture_action or evidence_allowance))


def has_standard_visual_handoff(text: str) -> bool:
    normalized = normalized_contract_text(text)
    if not all(sentence in normalized for sentence in STANDARD_VISUAL_HANDOFF_SENTENCES):
        return False
    lowered = normalized.casefold()
    contradictions = (
        r"direct link to each concrete changed page (?:is )?(?:optional|unnecessary|not required)",
        r"\bdirect link (?:is )?not required\b",
        r"\bchanged-page links may be omitted\b",
        r"\blinks to concrete changed pages may be omitted\b",
        r"root prototype index alone is sufficient",
        r"\bonly the root prototype index (?:is )?(?:required|needed|enough)\b",
        r"\bthe pm may provide only the root prototype index\b",
    )
    return not any(re.search(pattern, lowered) for pattern in contradictions)


def task6_shared_bootstrap_violations(text: str) -> list[str]:
    normalized = normalized_contract_text(text)
    lowered = normalized.casefold()
    violations = [
        f"missing {anchor}"
        for anchor in TASK6_SHARED_BOOTSTRAP_ANCHORS
        if normalized_contract_text(anchor).casefold() not in lowered
    ]

    for detail in TASK6_BOOTSTRAP_PROCEDURE_DETAILS:
        if normalized_contract_text(detail).casefold() in lowered:
            violations.append(f"procedure detail belongs in a Skill: {detail}")

    production_adoption = re.compile(
        r"\bproduction\b[^.]{0,160}\b(?:may|can|should|must|will|is allowed to)\b"
        r"[^.]{0,80}\b(?:copy|adopt|reuse|use|ship|implement)\b",
        flags=re.IGNORECASE,
    )
    production_prohibition = re.compile(
        r"\b(?:must not|do not|never|cannot)\b", flags=re.IGNORECASE
    )
    for line_number, line in enumerate(text.splitlines(), start=1):
        normalized_line = normalized_contract_text(line).casefold()
        if production_prohibition.search(normalized_line):
            continue
        if production_adoption.search(normalized_line) and any(
            target in normalized_line for target in TASK6_PROTOTYPE_ONLY_TARGETS
        ):
            violations.append(
                f"line {line_number}: production adopts prototype-only implementation"
            )

    if not is_canonical_screenshot_prohibition(text):
        violations.append("screenshot prohibition is missing or conditional")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if is_screenshot_allowance_or_fallback(line):
            violations.append(f"line {line_number}: screenshot allowance or fallback")

    if not has_standard_visual_handoff(text):
        violations.append("concrete-page handoff is missing or contradicted")

    artifact_nouns = (
        r"\btask(?:-scoped)?\s+(?:design\s+)?(?:record|markdown(?:\s+file)?)\b",
        r"\b(?:prototype\s+)?manifest\b",
        r"\bcompanion\s+(?:design|mapping|qa|baseline|approval)\s+markdown\b",
    )
    artifact_allowance = re.compile(
        r"\b(?:create|write|generate|produce|save|attach|persist)\b|"
        r"\b(?:optional|required|allowed|fallback)\b|"
        r"\b(?:may|can|should|must|will)\b",
        flags=re.IGNORECASE,
    )
    artifact_prohibition = re.compile(
        r"\b(?:do not|must not|never)\b", flags=re.IGNORECASE
    )
    for line_number, line in enumerate(text.splitlines(), start=1):
        if artifact_prohibition.search(line) or not artifact_allowance.search(line):
            continue
        if any(re.search(noun, line, flags=re.IGNORECASE) for noun in artifact_nouns):
            violations.append(
                f"line {line_number}: legacy companion artifact allowance"
            )

    for invocation in TASK6_HOST_NEUTRAL_INVOCATIONS:
        if invocation not in normalized:
            violations.append(f"missing host-neutral invocation {invocation}")
    for host_specific in ("$xy-", "/xy-", "Agent(xy-"):
        if host_specific in text:
            violations.append(f"host-specific invocation in shared bootstrap: {host_specific}")

    try:
        assert_closed_qa_outcomes(text)
    except ValueError as error:
        violations.append(str(error))
    return violations


def parse_ui_tier_flows(text: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for line in text.splitlines():
        # UI-Conformance 是“实现符合现有设计”的受约束快速路由，而 Patch/Page/Flow
        # 仍是会产生设计增量的原型路由。统一解析四种类型，防止文档只更新其中一处。
        match = re.match(r"^\| `(UI-(?:Conformance|Patch|Page|Flow))` \| (.+) \|$", line)
        if not match:
            continue
        result[match.group(1)] = tuple(
            token.strip().replace("`", "")
            for token in match.group(2).split("->")
        )
    return result


def is_valid_ui_tier_flow(tier: str, tokens: tuple[str, ...]) -> bool:
    if tier == "UI-Conformance":
        # 一致性修复不能偷偷携带原型、设计 Agent 或视觉确认；它必须先解析现有设计
        # 依据，再进入实现与统一 QA。任何设计增量都应升级到下面三个原型路由。
        return tokens == (
            "design_delta: none",
            "design_authority_resolved",
            "implementation",
            "unified QA",
        )
    required_suffix = (
        "prototype_verified",
        "visual_review_ready",
        "visual_approved",
    )
    if tokens[-3:] != required_suffix:
        return False
    if tokens.count("visual_approved") != 1:
        return False
    for token in tokens:
        lowered = token.casefold()
        if re.search(r"\bmust not\b|\bskip\b|\bomit\b", lowered):
            return False
        if token.endswith("_approved") and token not in {
            "requirements_approved",
            "visual_approved",
        }:
            return False
    if tier in {"UI-Page", "UI-Flow"}:
        if tokens.count("ia_ready") != 1:
            return False
        prototype_positions = [
            index
            for index, token in enumerate(tokens)
            if "prototype" in token.casefold() and token != "prototype_verified"
        ]
        if not prototype_positions or tokens.index("ia_ready") >= prototype_positions[0]:
            return False
    return True


FINAL_QA_OUTCOMES = {"PASS", "FAIL"}


def normalize_qa_outcome(value: str) -> str | None:
    value = value.strip()
    if re.fullmatch(r"[A-Z]+(?:[ _-][A-Z]+)*", value) is None:
        return None
    return re.sub(r"[ -]+", "_", value)


def qa_outcome_declarations(text: str) -> list[tuple[str, ...]]:
    declarations: list[tuple[str, ...]] = []
    for line in text.splitlines():
        match = re.match(
            r"^(?:Final QA outcome:|\[Audit result\])\s*(.+?)\s*$", line
        )
        if not match:
            continue
        normalized = tuple(
            outcome
            for part in match.group(1).split("|")
            if (outcome := normalize_qa_outcome(part)) is not None
        )
        declarations.append(normalized)
    return declarations


def extract_qa_outcome_identifiers(text: str) -> set[str]:
    return {outcome for declaration in qa_outcome_declarations(text) for outcome in declaration}


def qa_context_outcome_identifiers(text: str) -> set[str]:
    value = r"(?P<value>[A-Z]+(?:[ _-][A-Z]+)*)"
    patterns = (
        re.compile(
            rf"^\s*(?:QA|PM)\s+(?:final\s+)?(?:report|result|outcome)\s*:\s*{value}\s*$"
        ),
        re.compile(
            rf"^\s*(?:QA|PM)\s+returns?\s+{value}(?:\s+to\s+(?:QA|PM))?[.!]?\s*$"
        ),
        re.compile(
            rf"^\s*(?:QA|PM)\s+records?\s+(?:QA\s+)?(?:final\s+)?"
            rf"(?:report|result|outcome)\s*:\s*{value}\s*$"
        ),
        re.compile(
            rf"^\s*(?:Report|Return)\s+{value}\s+to\s+(?:the\s+)?PM\b.*$"
        ),
        re.compile(
            rf"^\s*The\s+(?:QA|PM)\s+(?:final\s+)?(?:report|result|outcome)"
            rf"\s+is\s+{value}[.!]?\s*$"
        ),
    )
    outcomes: set[str] = set()
    for line in text.splitlines():
        for pattern in patterns:
            match = pattern.match(line)
            if match and (outcome := normalize_qa_outcome(match.group("value"))):
                outcomes.add(outcome)
                break
    return outcomes


def parse_pipe_outcome_allowlist(text: str, label: str) -> tuple[str, ...]:
    matches = re.findall(
        rf"^{re.escape(label)}\s*(.+?)\s*$", text, flags=re.MULTILINE
    )
    if len(matches) != 1:
        return ()
    outcomes = tuple(normalize_qa_outcome(part) for part in matches[0].split("|"))
    if not outcomes or any(outcome is None for outcome in outcomes):
        return ()
    return tuple(outcome for outcome in outcomes if outcome is not None)


def assert_closed_qa_outcomes(text: str) -> None:
    declarations = qa_outcome_declarations(text)
    if len(declarations) != 1:
        raise ValueError(f"invalid QA outcome declarations: count={len(declarations)}")
    actual = extract_qa_outcome_identifiers(text)
    if actual != FINAL_QA_OUTCOMES:
        extras = sorted(actual - FINAL_QA_OUTCOMES)
        missing = sorted(FINAL_QA_OUTCOMES - actual)
        raise ValueError(f"invalid QA outcomes: extras={extras}, missing={missing}")
    contextual = qa_context_outcome_identifiers(text)
    extras = contextual - FINAL_QA_OUTCOMES
    if extras:
        raise ValueError(f"invalid contextual QA outcomes: extras={sorted(extras)}")


class UnifiedHostFixture:
    def make_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory(prefix="agent-workflow-unified-")
        project = Path(temporary.name) / "Project"
        pack = project / "agent_workflow"
        project.mkdir()
        shutil.copytree(
            PACK,
            pack,
            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
            symlinks=True,
        )
        shutil.copy2(pack / "templates/project.yaml.example", pack / "project.yaml")
        config = pack / "project.yaml"
        body = config.read_text(encoding="utf-8")
        placeholder = "project_id: replace-with-unique-project-id"
        self.assertEqual(body.count(placeholder), 1)
        config.write_text(
            body.replace(
                placeholder,
                f"project_id: unified-{uuid.uuid4().hex}",
                1,
            ),
            encoding="utf-8",
        )
        return temporary, project, pack

    @staticmethod
    def run_script(
        project: Path, script: str, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", f"agent_workflow/{script}", *arguments],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )

    def assert_no_project_outputs(self, project: Path) -> None:
        self.assertEqual(["agent_workflow"], sorted(path.name for path in project.iterdir()))

    def install_all(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary, project, pack = self.make_fixture()
        result = self.run_script(project, "setup_all.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return temporary, project, pack

    def active_workflow_sources(self) -> dict[str, str]:
        sources: dict[str, str] = {}
        for relative in ACTIVE_UI_CONTRACT_SOURCES:
            path = PACK / relative
            self.assertTrue(path.is_file(), f"missing active contract source: {relative}")
            sources[relative] = read_contract(path)
        for relative in RETIRED_UI_CONTRACT_SOURCES:
            path = PACK / relative
            if path.exists():
                self.assertTrue(path.is_file(), f"contract source is not a file: {relative}")
                sources[relative] = read_contract(path)
        return sources


class PortableSourcePackConfigContractTest(UnifiedHostFixture, unittest.TestCase):
    """The source pack must remain directly copyable into an arbitrary project."""

    def test_root_project_config_is_the_portable_template(self) -> None:
        root_config = (PACK / "project.yaml").read_text(encoding="utf-8")
        portable_template = (PACK / "templates/project.yaml.example").read_text(
            encoding="utf-8"
        )

        self.assertEqual(portable_template, root_config)
        self.assertIn("project_name: MyProject", root_config)
        self.assertIn("project_id: replace-with-unique-project-id", root_config)
        self.assertNotIn("OmniMind", root_config)

    def test_preflight_accepts_the_placeholder_without_mutating_it(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="portable-placeholder-")
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "Portable Example"
        pack = project / "agent_workflow"
        project.mkdir()
        shutil.copytree(
            PACK,
            pack,
            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
            symlinks=True,
        )
        (project / "go.mod").write_text(
            "module example.invalid/portable\n\ngo 1.24\n", encoding="utf-8"
        )
        config = pack / "project.yaml"
        before = config.read_bytes()

        result = self.run_script(project, "setup_all.sh", "--preflight")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, config.read_bytes())
        self.assertEqual(
            ["agent_workflow", "go.mod"], sorted(path.name for path in project.iterdir())
        )


class EngineeringBaselineContractTest(UnifiedHostFixture, unittest.TestCase):
    """初始化统一规范目录中尚未被项目拥有的工程基线叶文档。"""

    @staticmethod
    def add_observed_modules(project: Path) -> None:
        files = {
            "apps/web/package.json": (
                '{"dependencies":{"react":"19"},'
                '"scripts":{"build":"vite build","test":"vitest"}}'
            ),
            "apps/web/package-lock.json": "{}\n",
            "services/api/go.mod": "module example.test/api\n",
        }
        for relative, body in files.items():
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    @staticmethod
    def neutral_engineering(pack: Path) -> bytes:
        body = (
            pack / "templates/docs/standards/GENERAL.md"
        ).read_text(encoding="utf-8")
        values = {
            "PROJECT_NAME": "MyProject",
            "DOC_PROJECT": "docs/PROJECT.md",
            "DOC_FEATURES_DIR": "docs/features",
            "OBSERVED_BASELINE": (
                "- Not initialized. Setup replaces this exact template-only line with "
                "read-only repository observations."
            ),
        }
        return re.sub(
            r"\{\{([A-Z_]+)\}\}",
            lambda match: values[match.group(1)],
            body,
        ).encode("utf-8")

    def assert_observational_baseline(self, body: str) -> None:
        self.assertIn("## Observed repository baseline", body)
        self.assertIn("`apps/web`", body)
        self.assertIn("`services/api`", body)
        self.assertIn("`xy-web`", body)
        self.assertIn("`xy-backend`", body)
        self.assertIn("framework:react", body)
        self.assertIn('["npm", "run", "build"]', body)
        self.assertIn('["go", "test", "./..."]', body)
        self.assertIn("not upgrade targets", body.lower())
        self.assertIn("## Required project constraints", body)
        required = body.split("## Required project constraints", 1)[1].split(
            "## Observed repository baseline", 1
        )[0]
        observed = body.split("## Observed repository baseline", 1)[1].split(
            "## Verification policy", 1
        )[0]
        self.assertNotIn("Java 21", required)
        self.assertNotIn("Java 21", observed)
        self.assertNotRegex(body, r"(?i)manifest")

    def test_missing_and_empty_engineering_receive_observations(self) -> None:
        for state in ("missing", "empty"):
            with self.subTest(state=state):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                self.add_observed_modules(project)
                target = project / "docs/standards/GENERAL.md"
                if state != "missing":
                    target.parent.mkdir(parents=True)
                    target.write_bytes(b"")
                result = self.run_script(project, "scripts/scaffold_project_docs.sh")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                generated = target.read_text(encoding="utf-8")
                self.assert_observational_baseline(generated)
                # 通过真实脚手架检查整段规范无损落位，避免只更新源模板却遗漏
                # 最终交给实现者/QA 的新条款。已有非空文档仍由下面的测试保护。
                def common_section(body: str) -> str:
                    return body.split("## 共通开发规范", 1)[1].split(
                        "## Project-specific rules", 1
                    )[0]

                source = (pack / "templates/docs/standards/GENERAL.md").read_text(encoding="utf-8")
                self.assertEqual(common_section(source), common_section(generated))
                common_rules = re.findall(
                    r"\[(eng-common-\d{3})\] \[(hard|advisory)\]", common_section(generated)
                )
                expected_rules = {
                    f"eng-common-{number:03d}": "advisory" if number in (12, 18) else "hard"
                    for number in range(1, 30)
                }
                # 同时检查稳定编号、严重性和重复规则；验证器再核对实际目录与索引。
                self.assertEqual(len(expected_rules), len(common_rules))
                self.assertEqual(expected_rules, dict(common_rules))
                self.assertEqual([], validate_project_docs(pack / "project.yaml", project))
                # 在真实脚手架产物中保护职责审查的边界，而非只检查源模板：
                # 禁止按行数验收的规则保留为 hard；维护性建议不再提供长度或数值提示。
                review_rules = {
                    rule_id: (severity, text)
                    for rule_id, severity, text in re.findall(
                        r"^- `\[(eng-common-01[12])\] \[(hard|advisory)\]` (.+)$",
                        generated, re.MULTILINE,
                    )
                }
                self.assertEqual("hard", review_rules["eng-common-011"][0])
                self.assertIn("不得以代码行数或文件／函数长度", review_rules["eng-common-011"][1])
                self.assertIn("QA 验收依据", review_rules["eng-common-011"][1])
                severity, review = review_rules["eng-common-012"]
                self.assertEqual("advisory", severity)
                self.assertNotRegex(review, r"行数|长度|提示值|阈值|\d")
                self.assertIn("具体代码问题及实际影响", review)

    def test_nonempty_template_bodies_are_byte_for_byte_preserved(self) -> None:
        for state, original, mode in (
            (
                "raw-template",
                (PACK / "templates/docs/standards/GENERAL.md").read_bytes(),
                0o640,
            ),
            ("old-neutral-baseline", self.neutral_engineering(PACK), 0o604),
        ):
            with self.subTest(state=state):
                temporary, project, _pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                self.add_observed_modules(project)
                target = project / "docs/standards/GENERAL.md"
                target.parent.mkdir(parents=True)
                target.write_bytes(original)
                target.chmod(mode)

                result = self.run_script(project, "scripts/scaffold_project_docs.sh")

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(original, target.read_bytes())
                self.assertEqual(mode, stat.S_IMODE(target.stat().st_mode))

    def test_nonempty_user_engineering_contract_is_byte_for_byte_preserved(self) -> None:
        temporary, project, _pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        self.add_observed_modules(project)
        target = project / "docs/standards/GENERAL.md"
        target.parent.mkdir(parents=True)
        original = (
            b"# Engineering\n\n- Domain: engineering\n\n## Required project constraints\n\n"
            b"- `[eng-java-001] [hard]` Java 21 is required by the project owner.\n"
        )
        target.write_bytes(original)
        target.chmod(0o640)

        result = self.run_script(project, "scripts/scaffold_project_docs.sh")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(original, target.read_bytes())
        self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))


class ProjectProfilePreviewContractTest(UnifiedHostFixture, unittest.TestCase):
    """Task 11: all host preflights share one stable read-only preview."""

    @staticmethod
    def tree_snapshot(
        root: Path,
    ) -> dict[str, tuple[str, int, int, int, int, bytes | str]]:
        snapshot: dict[str, tuple[str, int, int, int, int, bytes | str]] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                snapshot[relative] = (
                    "symlink", mode, info.st_ino, info.st_nlink, info.st_mtime_ns,
                    os.readlink(path),
                )
            elif stat.S_ISDIR(info.st_mode):
                snapshot[relative] = (
                    "directory", mode, info.st_ino, info.st_nlink, info.st_mtime_ns, b"",
                )
            elif stat.S_ISREG(info.st_mode):
                snapshot[relative] = (
                    "file", mode, info.st_ino, info.st_nlink, info.st_mtime_ns,
                    path.read_bytes(),
                )
            else:
                snapshot[relative] = (
                    "special", mode, info.st_ino, info.st_nlink, info.st_mtime_ns, b"",
                )
        return snapshot

    def test_shared_preview_is_stable_complete_and_read_only(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        EngineeringBaselineContractTest.add_observed_modules(project)
        command = [
            sys.executable,
            str(pack / "lib/project_profile_cli.py"),
            "preview",
            str(pack),
            str(project),
        ]
        before = self.tree_snapshot(project)
        first = subprocess.run(
            command,
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        second = subprocess.run(
            command,
            cwd=Path(self.temporary_directory_for_cwd()),
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(before, self.tree_snapshot(project))
        for anchor in (
            "ProjectProfile preview",
            "roles: xy-backend, xy-qa, xy-uiux, xy-web",
            "module apps/web -> xy-web",
            "evidence: apps/web/package.json",
            'command: ["npm", "run", "build"]',
            "module services/api -> xy-backend",
            'command: ["go", "test", "./..."]',
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, first.stdout)

    def test_aggregate_check_consumes_the_shared_profile_cli(self) -> None:
        aggregate = (PACK / "setup_all.sh").read_text(encoding="utf-8")
        self.assertIn("lib/project_profile_cli.py", aggregate)
        # 聚合验收消费脚手架需求，不再以基础 UI 角色的存在推断是否需要原型。
        self.assertRegex(aggregate, r"project_profile_cli\.py\" design-scaffold")
        self.assertNotRegex(aggregate, r"project_profile_cli\.py\" roles")
        self.assertNotRegex(aggregate, r"py_yaml .* enabled_roles")

    def test_design_scaffold_query_is_compact_read_only_and_fails_closed(self) -> None:
        """实际 CLI 对空项目/后端返回精简布尔值，配置错误不得伪装成不需要设计。"""
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        def query() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(pack / "lib/project_profile_cli.py"),
                 "design-scaffold", str(pack), str(project)],
                cwd=project, capture_output=True, text=True, check=False, timeout=20,
            )

        for backend, expected in ((False, "1\n"), (True, "0\n")):
            with self.subTest(backend=backend):
                if backend:
                    (project / "go.mod").write_text("module example.test/backend\n\ngo 1.24\n",
                                                    encoding="utf-8")
                before = self.tree_snapshot(project)
                result = query()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(expected, result.stdout)
                self.assertEqual(before, self.tree_snapshot(project))
        config = pack / "project.yaml"
        body = config.read_text(encoding="utf-8")
        self.assertIn("discovery: auto", body)
        config.write_text(body.replace("discovery: auto", "discovery: unsupported-mode"),
                          encoding="utf-8")
        before = self.tree_snapshot(project)
        result = query()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("[ERROR]", result.stderr)
        self.assertEqual(before, self.tree_snapshot(project))

    def test_aggregate_preflight_is_read_only_and_surfaces_the_profile(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        EngineeringBaselineContractTest.add_observed_modules(project)
        before = self.tree_snapshot(project)
        result = subprocess.run(
            ["bash", str(pack / "setup_all.sh"), "--preflight"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ProjectProfile preview", result.stdout)
        self.assertIn("module apps/web -> xy-web", result.stdout)
        self.assertIn("module services/api -> xy-backend", result.stdout)
        self.assertEqual(before, self.tree_snapshot(project))
        for relative in ("AGENTS.md", "CLAUDE.md", ".agents", ".claude", ".codex", "docs"):
            with self.subTest(relative=relative):
                self.assertFalse((project / relative).exists())

    def test_aggregate_rejects_check_plus_preflight_before_writes(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        before = self.tree_snapshot(project)
        result = subprocess.run(
            ["bash", str(pack / "setup_all.sh"), "--check", "--preflight"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("mutually exclusive", result.stdout + result.stderr)
        self.assertEqual(before, self.tree_snapshot(project))

    def temporary_directory_for_cwd(self) -> str:
        directory = tempfile.mkdtemp(prefix="profile-preview-cwd-")
        self.addCleanup(shutil.rmtree, directory)
        return directory


class RetiredRuntimeCleanupContractTest(unittest.TestCase):
    """Task 12 keeps only the discovery-era runtime and operator guidance."""

    def test_manual_sandbox_runtime_and_superseded_plans_are_deleted(self) -> None:
        self.assertFalse((PACK / "lib/project_sandboxes.py").exists())
        for name in (
            "2026-08-12-multi-sandbox-role-scopes-design.md",
            "2026-08-12-multi-sandbox-role-scopes.md",
            "2026-08-11-lightweight-interactive-prototype-design.md",
            "2026-08-11-lightweight-interactive-prototype-implementation.md",
        ):
            with self.subTest(name=name):
                self.assertFalse((PACK / "docs/plans" / name).exists())

    def test_readme_uses_discovery_preflight_without_manual_adapter_edits(self) -> None:
        readme = (PACK / "README.md").read_text(encoding="utf-8")
        self.assertIn("bash /path/to/agent_workflow/install.sh", readme)
        self.assertIn("ProjectProfile preview", readme)
        self.assertIn("workspace.discovery: auto", readme)
        self.assertNotIn("Soft sandboxes", readme)
        self.assertNotIn("adapt paths + commands", readme)
        self.assertNotRegex(readme, r"(?i)edit .*role scope|manual .*role assignment")

    def test_runtime_does_not_name_or_special_case_retired_roles_or_skills(self) -> None:
        sources = [*PACK.glob("setup_*.sh"), *sorted((PACK / "lib").glob("*.py"))]
        retired = (
            "xy-python",
            "xy-rust",
            "xy-java",
            "xy-ios",
            "xy_ios",
            "phase1-align",
            "phase2-contract",
            "phase3-dispatch",
            "phase4-accept",
            "phase5-archive",
            "phase-closeout",
            "adr_generator",
            "component_audit",
            "conflict_detector",
            "contract_validator",
            "project-conventions",
            "review_checklist",
        )
        findings: list[str] = []
        for path in sources:
            body = path.read_text(encoding="utf-8")
            for token in retired:
                if token in body:
                    findings.append(f"{path.relative_to(PACK)}: {token}")
        self.assertEqual([], findings)

class PortableRoleDiscoveryContractTest(unittest.TestCase):
    maxDiff = None

    @staticmethod
    def _catalog_worker_role_ids_from_text(text: str) -> set[str]:
        lines = text.splitlines()
        supported_section = re.compile(r"^roles:\s*(?:#.*)?$")
        roles_like_section = re.compile(
            r'''^(?:roles|["']roles["'])\s*:''', re.IGNORECASE
        )
        section_starts: list[int] = []
        for line_number, line in enumerate(lines, start=1):
            if line[:1].isspace() or not roles_like_section.match(line):
                continue
            if supported_section.fullmatch(line) is None:
                raise AssertionError(
                    "unsupported top-level roles syntax at "
                    f"line {line_number}: {line.strip()}"
                )
            section_starts.append(line_number)
        if len(section_starts) != 1:
            raise AssertionError(
                "product/ROLES.yaml must contain exactly one top-level roles section; "
                f"found {len(section_starts)} at lines {section_starts}"
            )
        section_start = section_starts[0]
        section_lines: list[str] = []
        for line in lines[section_start:]:
            if line and not line[0].isspace() and not line.lstrip().startswith("#"):
                break
            section_lines.append(line)
        direct_worker_key = re.compile(
            r"^  (?P<role>[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*):"
            r"(?:\s+.*)?$"
        )
        worker_roles: set[str] = set()
        for line_number, line in enumerate(
            section_lines, start=section_start + 1
        ):
            if not line.startswith("  ") or line.startswith("   "):
                continue
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = direct_worker_key.fullmatch(line)
            if match is None:
                raise AssertionError(
                    "unsupported direct worker role key at "
                    f"line {line_number}: {line.strip()}"
                )
            role = match.group("role")
            if role in worker_roles:
                raise AssertionError(
                    "duplicate direct worker role key at "
                    f"line {line_number}: {role}"
                )
            worker_roles.add(role)
        return worker_roles

    @classmethod
    def _catalog_worker_role_ids(cls) -> set[str]:
        return cls._catalog_worker_role_ids_from_text(
            (PACK / "product/ROLES.yaml").read_text(encoding="utf-8")
        )

    @staticmethod
    def _active_role_authority_files() -> list[Path]:
        files: set[Path] = {
            path
            for pattern in ("setup_*.sh",)
            for path in PACK.glob(pattern)
            if path.is_file()
        }
        files.update(
            path
            for path in (PACK / "project.yaml", PACK / "templates/project.yaml.example")
            if path.is_file()
        )
        for relative_root in ACTIVE_ROLE_AUTHORITY_ROOTS:
            root = PACK / relative_root
            files.update(
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix in ACTIVE_ROLE_AUTHORITY_SUFFIXES
                and path.name not in {f"{role}.md" for role in RETIRED_LANGUAGE_ROLE_IDS}
            )
        return sorted(files)

    @staticmethod
    def _yaml_key_entries(text: str, indent: int) -> list[tuple[int, str, str]]:
        prefix = " " * indent
        pattern = re.compile(
            rf"^{re.escape(prefix)}(?P<key>[a-z][a-z0-9_]*)\s*:"
            rf"(?P<value>.*)$"
        )
        entries: list[tuple[int, str, str]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = pattern.match(line)
            if match is None:
                continue
            value = match.group("value").split("#", 1)[0].strip()
            entries.append((line_number, match.group("key"), value))
        return entries

    @classmethod
    def _portable_workspace_structure_violations(cls, text: str) -> list[str]:
        lines = text.splitlines()
        top_level = cls._yaml_key_entries(text, indent=0)
        violations: list[str] = []
        for line_number, line in enumerate(lines, start=1):
            quoted = re.match(
                r'''^(?P<quote>["'])(?P<key>[a-z][a-z0-9_]*)'''
                r'''(?P=quote)\s*:''',
                line,
            )
            if quoted is not None:
                violations.append(
                    f"quoted top-level key is unsupported at line {line_number}: "
                    f"{quoted.group('key')}"
                )
        counts: dict[str, int] = {}
        for _, key, _ in top_level:
            counts[key] = counts.get(key, 0) + 1
        for key, count in sorted(counts.items()):
            if count > 1:
                violations.append(f"duplicate top-level key: {key} ({count})")

        workspace_entries = [entry for entry in top_level if entry[1] == "workspace"]
        if len(workspace_entries) != 1:
            violations.append(
                f"workspace must appear exactly once as a top-level mapping; "
                f"found {len(workspace_entries)}"
            )
        else:
            workspace_line, _, workspace_value = workspace_entries[0]
            if workspace_value:
                violations.append("workspace must be a block mapping")
            else:
                end_line = len(lines) + 1
                for line_number, _, _ in top_level:
                    if line_number > workspace_line:
                        end_line = line_number
                        break
                workspace_body = "\n".join(lines[workspace_line:end_line - 1])
                discovery_entries = [
                    entry
                    for entry in cls._yaml_key_entries(workspace_body, indent=2)
                    if entry[1] == "discovery"
                ]
                if len(discovery_entries) != 1:
                    violations.append(
                        "workspace.discovery must appear exactly once; "
                        f"found {len(discovery_entries)}"
                    )
                elif discovery_entries[0][2] != "auto":
                    violations.append("workspace.discovery must equal auto")

        override_entries = [
            entry for entry in top_level if entry[1] == "workspace_overrides"
        ]
        if len(override_entries) != 1:
            violations.append(
                "workspace_overrides must appear exactly once as a top-level mapping; "
                f"found {len(override_entries)}"
            )
        else:
            override_line, _, override_value = override_entries[0]
            if override_value:
                if override_value != "{}":
                    violations.append(
                        "inline workspace_overrides must be the supported empty mapping {}"
                    )
            else:
                end_line = len(lines) + 1
                for line_number, _, _ in top_level:
                    if line_number > override_line:
                        end_line = line_number
                        break
                override_body = "\n".join(lines[override_line:end_line - 1])
                if not cls._yaml_key_entries(override_body, indent=2):
                    violations.append(
                        "empty workspace_overrides must use an explicit mapping such as {}"
                    )
        return violations

    @staticmethod
    def _is_pure_negative_retired_reference(path: Path, line: str) -> bool:
        stripped = line.strip()
        # Remove only presentation wrappers, never an inline code/config prefix.
        sentence = re.sub(r"^(?:#|//|/\*|\*|<!--|>)+\s*", "", stripped)
        sentence = re.sub(r"(?:\*/|-->)\s*$", "", sentence).strip()
        sentence = sentence.replace("`", "")
        sentence = re.sub(r"\s+", " ", sentence).casefold()

        role_union = "|".join(
            re.escape(role) for role in sorted(RETIRED_LANGUAGE_ROLE_IDS)
        )
        finite_negative_sentences = (
            rf"^(?:the )?(?:retired|removed) (?:role )?(?:{role_union})"
            rf"(?: role)?(?: must not be (?:used|routed|called|referenced)|"
            rf" must be absent)?[.!]?$",
            rf"^(?:the )?(?:{role_union})(?: role)? "
            rf"(?:must not be (?:used|routed|called|referenced)|must be absent|"
            rf"is (?:retired|removed)|was removed|has been (?:retired|removed))"
            rf"[.!]?$",
        )
        return any(re.fullmatch(pattern, sentence) for pattern in finite_negative_sentences)

    def _assert_exact_worker_roles(
        self, actual: set[str], *, authority: str
    ) -> None:
        missing = sorted(PORTABLE_WORKER_ROLE_IDS - actual)
        unexpected = sorted(actual - PORTABLE_WORKER_ROLE_IDS)
        self.assertFalse(
            missing or unexpected,
            f"{authority} worker roles mismatch: "
            f"missing={missing}, unexpected={unexpected}",
        )

    @classmethod
    def _retired_positive_reference_findings(
        cls, paths: list[Path]
    ) -> list[str]:
        findings: list[str] = []
        for path in paths:
            try:
                relative = path.relative_to(PACK)
            except ValueError:
                relative = Path(path.name)
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                folded = line.casefold()
                referenced = sorted(
                    role
                    for role in RETIRED_LANGUAGE_ROLE_IDS
                    if re.search(
                        rf"(?<![a-z0-9-]){re.escape(role)}(?![a-z0-9-])",
                        folded,
                    )
                )
                if not referenced or cls._is_pure_negative_retired_reference(path, line):
                    continue
                findings.append(
                    f"{relative}:{line_number}: active reference to "
                    f"{', '.join(referenced)}: {line.strip()}"
                )
        return findings

    def test_canonical_role_source_files_are_exactly_the_seven_workers(self) -> None:
        for retired_role in sorted(RETIRED_LANGUAGE_ROLE_IDS):
            with self.subTest(retired_source=retired_role):
                self.assertFalse(
                    (PACK / "roles" / f"{retired_role}.md").exists(),
                    f"retired role source still exists: roles/{retired_role}.md",
                )
        actual = {path.stem for path in (PACK / "roles").glob("xy-*.md")}
        self._assert_exact_worker_roles(actual, authority="roles/xy-*.md")

    def test_role_catalog_contains_exactly_the_seven_workers(self) -> None:
        # PM is a top-level orchestrator entry and intentionally is not counted as a
        # worker under the catalog's `roles:` mapping.
        actual = self._catalog_worker_role_ids()
        for retired_role in sorted(RETIRED_LANGUAGE_ROLE_IDS):
            with self.subTest(retired_metadata=retired_role):
                self.assertNotIn(retired_role, actual)
        self._assert_exact_worker_roles(actual, authority="product/ROLES.yaml roles")

    def test_role_catalog_parser_exposes_noncanonical_direct_worker_keys(self) -> None:
        mutated = (
            "pm:\n"
            "  name: PM\n"
            "roles:\n"
            "  xy-web:\n"
            "    description: Web\n"
            "  custom_worker:\n"
            "    description: Must not be hidden by an xy-only parser\n"
            "  rogue-role: {description: Rogue}\n"
        )
        self.assertEqual(
            {"xy-web", "custom_worker", "rogue-role"},
            self._catalog_worker_role_ids_from_text(mutated),
        )
        self.assertEqual(
            {"xy-web"},
            self._catalog_worker_role_ids_from_text(
                "roles: # workers\n  xy-web: {description: Web}\n"
            ),
        )

        unsupported_direct_keys = {
            "quoted": "  'rogue-role': {description: Rogue}\n",
            "uppercase": "  RogueRole: {description: Rogue}\n",
            "duplicate": "  xy-web: {description: Duplicate}\n",
        }
        for label, extra_role in unsupported_direct_keys.items():
            with self.subTest(unsupported_direct_key=label):
                with self.assertRaisesRegex(
                    AssertionError,
                    "(?:unsupported|duplicate) direct worker role key",
                ):
                    self._catalog_worker_role_ids_from_text(
                        "roles:\n  xy-web: {description: Web}\n" + extra_role
                    )

        unsupported_sections = {
            "quoted": (
                '"roles":\n  rogue-role: {description: Rogue}\n',
                "unsupported top-level roles syntax",
            ),
            "duplicate-with-comment": (
                "roles:\n  xy-web: {description: Web}\n"
                "roles: # duplicate\n  rogue-role: {description: Rogue}\n",
                "exactly one top-level roles section",
            ),
        }
        for label, (source, error_pattern) in unsupported_sections.items():
            with self.subTest(unsupported_roles_section=label):
                with self.assertRaisesRegex(AssertionError, error_pattern):
                    self._catalog_worker_role_ids_from_text(source)

    def test_retired_language_roles_have_no_active_positive_reference(self) -> None:
        self.assertEqual(
            [],
            self._retired_positive_reference_findings(
                self._active_role_authority_files()
            ),
        )

    def test_retired_reference_filter_only_exempts_pure_negative_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="retired-role-reference-") as temporary:
            code = Path(temporary) / "routing.py"
            code.write_text(
                "# retired xy-java must not be routed\n"
                'ROUTES = {"xy-java": "xy-backend"}  # retired compatibility\n'
                'ALIASES = ["xy-rust"]  # retired compatibility\n',
                encoding="utf-8",
            )
            documentation = Path(temporary) / "contract.md"
            documentation.write_text(
                "The retired `xy-python` role must not be used.\n",
                encoding="utf-8",
            )
            ambiguous = Path(temporary) / "ambiguous.md"
            ambiguous.write_text(
                "Use xy-java for compatibility; compatibility is not forbidden.\n"
                "PM routes xy-rust to xy-backend; prohibited only in new projects.\n",
                encoding="utf-8",
            )

            findings = self._retired_positive_reference_findings(
                [code, documentation, ambiguous]
            )

        self.assertEqual(4, len(findings))
        combined = "\n".join(findings)
        self.assertIn("ROUTES", combined)
        self.assertIn("ALIASES", combined)
        self.assertIn("Use xy-java", combined)
        self.assertIn("PM routes xy-rust", combined)
        self.assertNotIn("xy-python", "\n".join(findings))

    def test_portable_project_template_uses_auto_workspace_discovery(self) -> None:
        template = (PACK / "templates/project.yaml.example").read_text(
            encoding="utf-8"
        )
        top_level_keys = {key for _, key, _ in self._yaml_key_entries(template, 0)}

        for forbidden in ("sandboxes", "enabled_roles", "commands"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, top_level_keys)
        self.assertEqual([], self._portable_workspace_structure_violations(template))

    def test_workspace_structure_parser_rejects_false_green_mutations(self) -> None:
        valid = "workspace:\n  discovery: auto\nworkspace_overrides: {}\n"
        self.assertEqual([], self._portable_workspace_structure_violations(valid))

        mutations = {
            "discovery-in-wrong-section": (
                "settings:\n  discovery: auto\nworkspace: {}\n"
                "workspace_overrides: {}\n"
            ),
            "workspace-is-not-a-mapping": (
                "workspace: auto\nworkspace_overrides: {}\n"
            ),
            "duplicate-workspace-discovery": (
                "workspace:\n  discovery: auto\n  discovery: auto\n"
                "workspace_overrides: {}\n"
            ),
            "workspace-overrides-is-not-a-mapping": (
                "workspace:\n  discovery: auto\nworkspace_overrides: []\n"
            ),
            "duplicate-top-level-key": (
                "workspace:\n  discovery: auto\nworkspace_overrides: {}\n"
                "workspace_overrides: {}\n"
            ),
            "quoted-forbidden-top-level-key": (
                '"sandboxes": {}\nworkspace:\n  discovery: auto\n'
                "workspace_overrides: {}\n"
            ),
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                self.assertTrue(
                    self._portable_workspace_structure_violations(mutation),
                    f"mutation unexpectedly satisfied workspace structure: {label}",
                )


class LightweightSkillAndReviewPolicyContractTest(unittest.TestCase):
    """The pack owns orchestration; Grill Me and one reviewer remain bounded tools."""

    @staticmethod
    def _text(relative: str) -> str:
        return read_contract(PACK / relative)

    @staticmethod
    def _machine_policy_violations(text: str) -> list[str]:
        if len(
            re.findall(
                r"(?<![A-Za-z0-9_])qa_review_policy(?![A-Za-z0-9_])",
                text,
            )
        ) != 1:
            return ["expected exactly one qa_review_policy token"]
        if len(re.findall(r"(?m)^[ \t]*qa_review_policy:[ \t]*$", text)) != 1:
            return ["expected exactly one qa_review_policy header"]
        blocks = [
            match.group(0).rstrip()
            for match in re.finditer(r"(?m)^qa_review_policy:\n(?:(?:  .*)\n?)+", text)
        ]
        if blocks != [QA_REVIEW_POLICY_BLOCK]:
            return ["expected exactly one canonical qa_review_policy block"]
        return []

    @staticmethod
    def _host_policy_violations(text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text)
        violations: list[str] = []
        if normalized.count(QA_REVIEW_METHOD_CLAUSE) != 1:
            violations.append("expected exactly one canonical review-method clause")
        for method in QA_REVIEW_METHODS:
            if normalized.count(method) != 1:
                violations.append(f"expected exactly one host method token: {method}")
        return violations

    @staticmethod
    def _active_policy_files() -> tuple[Path, ...]:
        roots = tuple(
            path
            for root in ("lib", "platforms", "product", "roles", "scripts", "templates")
            for path in (PACK / root).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
        root_files = tuple(
            path
            for path in (
                PACK / "README.md",
                PACK / "project.yaml",
                PACK / "setup_all.sh",
                PACK / "setup_codex.sh",
                PACK / "setup_claude.sh",
                PACK / "setup_antigravity.sh",
            )
            if path.is_file()
        )
        return tuple(sorted(set(roots + root_files)))

    def test_canonical_sources_define_the_lightweight_external_skill_policy(self) -> None:
        for relative in (
            "product/WORKFLOW.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        ):
            text = self._text(relative)
            for anchor in LIGHTWEIGHT_SKILL_POLICY_ANCHORS:
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor, text)

        schema = self._text("product/AGENT_SCHEMA.md")
        self.assertIn("review_method:", schema)
        self.assertIn("selected:", schema)
        self.assertIn("capability_evidence:", schema)

    def test_full_work_uses_self_contained_grill_and_draft_planning_before_approval(self) -> None:
        """Full 前置链必须跨事实源一致，且 QA 前不得污染正式项目真相。"""

        sources = (
            "product/WORKFLOW.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/shared/AGENTS.product.tpl",
            "platforms/claude/AGENTS.claude.tpl",
            "platforms/antigravity/AGENTS.antigravity.tpl",
        )
        anchors = (
            "Full",
            "Grill Me coverage check",
            "xy-plan",
            "plan_state: draft",
            "requirements_approved",
            "post-QA controlled-document projection",
            "QA PASS",
        )
        for relative in sources:
            body = re.sub(r"\s+", " ", self._text(relative))
            for anchor in anchors:
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor, body)

        for relative in (
            "product/WORKFLOW.md",
            "product/GLOBAL_CONSTRAINTS.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/shared/skills/grill-me/SKILL.md",
        ):
            with self.subTest(source=relative):
                self.assertNotIn("/grilling", self._text(relative))

    def test_planning_and_grilling_skills_are_self_contained_core_sources(self) -> None:
        """运行时不能再次依赖用户机器上的 Superpowers 或缺失二级原语。"""

        manifest = {
            line.strip()
            for line in self._text("platforms/shared/core-skills.txt").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("grill-me", manifest)
        self.assertIn("xy-plan", manifest)

        grill = self._text("platforms/shared/skills/grill-me/SKILL.md")
        plan = self._text("platforms/shared/skills/xy-plan/SKILL.md")
        self.assertNotIn("/grilling", grill)
        self.assertNotIn("subagent-driven-development", plan)
        self.assertNotIn("executing-plans", plan)
        self.assertIn("methodology_reference: superpowers-writing-plans", plan)
        self.assertIn("task_graph", plan)

    def test_internal_machine_records_are_not_user_facing_output(self) -> None:
        """内部结构继续驱动 PM，但不得把原始 YAML、JSON 或门禁令牌交给用户审阅。"""

        # 四个共享 Skill 分别产生需求覆盖、记忆、计划和运行时编排数据。这里锁定的只是
        # 展示边界：结构本身仍然存在，PM 对用户只投影自然语言结论，避免误删调度能力。
        skill_expectations = {
            "platforms/shared/skills/grill-me/SKILL.md": (
                "Internal PM record",
                "must not emit the raw `grill_result` YAML",
            ),
            "platforms/shared/skills/xy-project-memory/SKILL.md": (
                "internal PM and task-handoff record",
                "must not emit raw `memory_context` YAML",
                "must not emit raw `memory_projection` YAML",
            ),
            "platforms/shared/skills/xy-plan/SKILL.md": (
                "Internal planning record",
                "Never present the raw `task_graph` JSON",
                "Concise user approval brief",
            ),
            "platforms/shared/skills/xy-workflow/SKILL.md": (
                "Internal orchestration records are not user-facing output.",
                "Never paste raw workflow YAML or DAG JSON into user messages.",
                "`commit_decision`",
                "Do not require the user to type `requirements_approved`",
            ),
        }
        for relative, anchors in skill_expectations.items():
            body = self._text(relative)
            for anchor in anchors:
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor, body)

        # 输出优化不能删除内部真值；这些字段和 CLI 仍然必须存在并保持可调度。
        self.assertIn("grill_result:", self._text("platforms/shared/skills/grill-me/SKILL.md"))
        self.assertIn(
            "memory_context:",
            self._text("platforms/shared/skills/xy-project-memory/SKILL.md"),
        )
        plan = self._text("platforms/shared/skills/xy-plan/SKILL.md")
        self.assertIn('"task_graph"', plan)
        workflow = self._text("platforms/shared/skills/xy-workflow/SKILL.md")
        for command in (
            "task_graph_cli.py validate",
            "task_graph_cli.py ready",
            "task_graph_cli.py qa-ready",
        ):
            self.assertIn(command, workflow)

    def test_product_and_host_bootstraps_define_concise_natural_language_feedback(self) -> None:
        """三宿主入口和产品真值必须共享同一条自然语言反馈原则。"""

        sources = (
            "product/WORKFLOW.md",
            "product/GLOBAL_CONSTRAINTS.md",
            "platforms/shared/AGENTS.product.tpl",
            "platforms/claude/AGENTS.claude.tpl",
        )
        for relative in sources:
            body = self._text(relative)
            for anchor in (
                "Internal orchestration records are not user-facing output.",
                "Never paste raw workflow YAML or DAG JSON into user messages.",
            ):
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor, body)

        for relative in (
            "product/WORKFLOW.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        ):
            body = self._text(relative)
            self.assertIn(
                "Accept any explicit affirmative reply in natural language",
                body,
            )
            self.assertIn(
                "Do not require the user to type `requirements_approved`",
                body,
            )

    def test_pm_dispatch_contract_invokes_the_deterministic_task_graph_cli(self) -> None:
        """DAG 不得只停留在提示词；派发与 QA 前都要有确定性计算入口。"""

        for relative in (
            "product/WORKFLOW.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        ):
            body = self._text(relative)
            for command in (
                "task_graph_cli.py validate",
                "task_graph_cli.py ready",
                "task_graph_cli.py qa-ready",
            ):
                with self.subTest(source=relative, command=command):
                    self.assertIn(command, body)

    def test_superpowers_does_not_reenter_as_a_default_workflow(self) -> None:
        forbidden = (
            "superpowers:brainstorming",
            "superpowers:writing-plans",
            "superpowers:executing-plans",
            "superpowers:subagent-driven-development",
            "superpowers:test-driven-development",
            "superpowers:receiving-code-review",
            "superpowers:verification-before-completion",
            "superpowers:finishing-a-development-branch",
            "superpowers:code-reviewer",
        )
        active_sources = LIGHTWEIGHT_SKILL_POLICY_SOURCES + (
            "roles/xy-qa.md",
            "platforms/shared/AGENTS.product.tpl",
            "platforms/claude/AGENTS.claude.tpl",
            "platforms/codex/AGENTS.codex.tpl",
            "platforms/antigravity/AGENTS.antigravity.tpl",
            "docs/plans/2026-08-12-portable-role-convergence-auto-discovery.md",
        )
        for relative in active_sources:
            text = self._text(relative)
            for phrase in forbidden:
                with self.subTest(source=relative, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_full_bugs_use_coverage_and_light_bugs_keep_the_native_path(self) -> None:
        """Full 缺陷不能绕过澄清与计划；清晰的小缺陷仍保持轻量修复路径。"""

        for relative in (
            "product/WORKFLOW.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        ):
            text = self._text(relative)
            normalized = re.sub(r"\s+", " ", text)
            for anchor in NATIVE_BUG_FIX_ANCHORS:
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor, text)
            self.assertIn(
                "Clear, reproducible Trivial or Light bugs use `native_bug_fix` without Grill Me.",
                normalized,
            )
            self.assertIn(
                "A `Full` bug still runs the Grill Me coverage check and `xy-plan`",
                normalized,
            )

    def test_project_projection_records_only_qa_verified_current_truth(self) -> None:
        sources = (
            "product/WORKFLOW.md",
            "product/AGENT_SCHEMA.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        )
        required_anchors = (
            "controlled_document_projection:",
            "project_docs_update: required | not_required",
            "affected_features: []",
            "project_index_update: required | not_required",
            "reimplemented",
            "routine refactors",
            "pure visual styling",
            "PROJECT.md",
            "QA PASS",
            "removed",
            "Git",
        )
        for relative in sources:
            text = self._text(relative)
            normalized = re.sub(r"\s+", " ", text).casefold()
            for anchor in required_anchors:
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor.casefold(), normalized)
            self.assertNotIn("spec_update", normalized)
            self.assertNotIn("spec.md", normalized)
            self.assertNotIn("status.md", normalized)

        workflow = re.sub(r"\s+", " ", self._text("product/WORKFLOW.md"))
        self.assertIn(
            "For `change_type: removed`, closeout removes the active PROJECT row, renames the "
            "feature detail to `<feature>.removed.md`",
            workflow,
        )
        self.assertIn(
            "QA failure leaves the canonical documents unchanged.",
            workflow,
        )

    def test_pm_assesses_a_scoped_commit_after_qa_without_a_third_business_gate(self) -> None:
        """提交是 QA 后的 PM 收口动作；它不能抢跑、扩大暂存范围或变成第三次确认。"""

        lifecycle = (
            "QA PASS -> controlled-document projection -> PM commit assessment -> "
            "memory closeout -> final report"
        )
        for relative in (
            "README.md",
            "product/WORKFLOW.md",
            "product/AGENT_SCHEMA.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/shared/skills/xy-project-memory/SKILL.md",
        ):
            body = re.sub(r"\s+", " ", self._text(relative))
            with self.subTest(source=relative, contract="lifecycle"):
                self.assertIn(lifecycle, body)

        for relative in (
            "product/WORKFLOW.md",
            "product/AGENT_SCHEMA.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        ):
            body = self._text(relative)
            for anchor in (
                "commit_decision:",
                "must not stage unrelated or unverified changes",
                "must not use `git add -A` or `git add .`",
                "does not create a third business-confirmation stage",
            ):
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor, body)

        for relative in (
            "platforms/shared/AGENTS.product.tpl",
            "platforms/claude/AGENTS.claude.tpl",
            "platforms/antigravity/AGENTS.antigravity.tpl",
        ):
            with self.subTest(host=relative):
                self.assertIn("PM commit assessment", self._text(relative))

    def test_qa_uses_one_reviewer_and_falls_back_only_on_technical_unavailability(self) -> None:
        for relative in (
            "product/WORKFLOW.md",
            "product/AGENT_SCHEMA.md",
            "platforms/shared/skills/xy-qa-review/SKILL.md",
        ):
            text = self._text(relative)
            for anchor in QA_REVIEW_METHOD_POLICY_ANCHORS:
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor, text)

        role = self._text("roles/xy-qa.md")
        self.assertIn("exactly one reviewer", role)
        self.assertIn("review method findings are advisory evidence", role)
        self.assertIn("must not dispatch a nested reviewer", role)

    def test_retired_review_provider_machine_terms_have_no_active_references(self) -> None:
        offenders: list[str] = []
        for path in self._active_policy_files():
            body = path.read_text(encoding="utf-8", errors="ignore")
            for retired in RETIRED_QA_POLICY_TERMS:
                if retired in body:
                    offenders.append(f"{path.relative_to(PACK)}:{retired}")
        self.assertEqual([], offenders)

    def test_review_policy_helpers_reject_duplicate_or_reordered_policy(self) -> None:
        self.assertEqual([], self._machine_policy_violations(QA_REVIEW_POLICY_BLOCK + "\n"))
        self.assertTrue(
            self._machine_policy_violations(
                QA_REVIEW_POLICY_BLOCK + "\n\n" + QA_REVIEW_POLICY_BLOCK + "\n"
            )
        )
        self.assertTrue(
            self._machine_policy_violations(QA_REVIEW_POLICY_BLOCK + "\n\nqa_review_policy:\n")
        )
        self.assertTrue(
            self._machine_policy_violations(
                QA_REVIEW_POLICY_BLOCK + "\n\n\tqa_review_policy:\n\towner: xy-qa\n"
            )
        )
        for label, suffix in QA_REVIEW_POLICY_DUPLICATE_SUFFIXES.items():
            with self.subTest(duplicate_token=label):
                self.assertTrue(
                    self._machine_policy_violations(QA_REVIEW_POLICY_BLOCK + suffix)
                )
        reordered = QA_REVIEW_POLICY_BLOCK.replace(
            "    - host-native-review\n    - installed-code-review-skill\n    - internal-xy-qa-procedure",
            "    - internal-xy-qa-procedure\n    - installed-code-review-skill\n    - host-native-review",
        )
        self.assertTrue(self._machine_policy_violations(reordered + "\n"))

        host = QA_REVIEW_METHOD_CLAUSE
        self.assertEqual([], self._host_policy_violations(host))
        glossary = " -> ".join(QA_REVIEW_METHODS)
        reordered_host = (
            "`internal-xy-qa-procedure`, then one `installed-code-review-skill` proven installed "
            "and capable, then `host-native-review`, moving forward only on technical unavailability."
        )
        self.assertTrue(self._host_policy_violations(glossary + "\n" + reordered_host))

    def test_review_escalations_are_explicit_and_not_ordinary_fallbacks(self) -> None:
        for relative in (
            "product/WORKFLOW.md",
            "platforms/shared/skills/xy-qa-review/SKILL.md",
        ):
            text = self._text(relative)
            self.assertIn("review-swarm", text)
            self.assertIn("explicit high-risk escalation", text)
            self.assertIn("review-and-simplify-changes", text)
            self.assertIn("review-only", text)
            self.assertIn("must not enter the ordinary fallback chain", text)

    def test_host_bootstraps_use_the_same_ordered_review_methods(self) -> None:
        matrix = {
            "platforms/claude/AGENTS.claude.tpl": (
                "host-native-review",
                "installed-code-review-skill",
                "internal-xy-qa-procedure",
            ),
            "platforms/codex/AGENTS.codex.tpl": (
                "Codex native review",
                "installed-code-review-skill",
                "internal-xy-qa-procedure",
            ),
            "platforms/antigravity/AGENTS.antigravity.tpl": (
                "host-native-review",
                "installed-code-review-skill",
                "internal-xy-qa-procedure",
            ),
        }
        for relative, anchors in matrix.items():
            text = self._text(relative)
            for anchor in anchors:
                with self.subTest(source=relative, anchor=anchor):
                    self.assertIn(anchor, text)

        for relative in matrix:
            text = self._text(relative)
            with self.subTest(source=relative, property="unique-method-policy"):
                self.assertEqual([], self._host_policy_violations(text))
            normalized = re.sub(r"\s+", " ", text)
            with self.subTest(source=relative, property="no-reviewer-shopping"):
                self.assertIn("Findings or `FAIL` never switch review method or reviewer", normalized)

    def test_machine_authorities_have_one_exact_review_policy_block(self) -> None:
        for relative in (
            "product/WORKFLOW.md",
            "product/AGENT_SCHEMA.md",
            "platforms/shared/skills/xy-qa-review/SKILL.md",
        ):
            with self.subTest(source=relative):
                self.assertEqual([], self._machine_policy_violations(self._text(relative)))

    def test_runtime_policy_validator_rejects_reordering_and_every_retired_term(self) -> None:
        with tempfile.TemporaryDirectory(prefix="qa-review-policy-") as temporary:
            fixture = Path(temporary) / "pack"
            authorities = (
                "product/WORKFLOW.md",
                "product/AGENT_SCHEMA.md",
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "platforms/shared/AGENTS.product.tpl",
                "platforms/claude/AGENTS.claude.tpl",
                "platforms/codex/AGENTS.codex.tpl",
                "platforms/antigravity/AGENTS.antigravity.tpl",
            )
            for relative in authorities:
                target = fixture / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((PACK / relative).read_bytes())
                if target.name == "SKILL.md":
                    # 契约夹具必须携带入口指向的分支；只复制入口会人为制造缺失规则。
                    shutil.copytree((PACK / relative).parent / "references",
                                    target.parent / "references", dirs_exist_ok=True)
                elif target.suffix == ".tpl" and target.parent.name != "shared":
                    # 根模板只做路由，夹具必须带上当前平台真实的完整细则。
                    shutil.copytree((PACK / relative).parent / "references",
                                    target.parent / "references", dirs_exist_ok=True)
            self.assertEqual((), validate_pack_qa_review_policy(fixture))

            host = fixture / "platforms/codex/references/pm-integration.md"
            original = host.read_text(encoding="utf-8")
            glossary = " -> ".join(QA_REVIEW_METHODS)
            clause_pattern = re.compile(
                r"\s+".join(re.escape(part) for part in QA_REVIEW_METHOD_CLAUSE.split())
            )
            reordered, replacements = clause_pattern.subn(
                "`internal-xy-qa-procedure`, then one `installed-code-review-skill` proven installed "
                "and capable, then `host-native-review`, moving forward only on technical unavailability.",
                original,
                count=1,
            )
            self.assertEqual(1, replacements)
            host.write_text(glossary + "\n" + reordered, encoding="utf-8")
            self.assertTrue(validate_pack_qa_review_policy(fixture))
            host.write_text(original, encoding="utf-8")

            duplicate_suffixes = {
                "bare-key": "\nqa_review_policy:\n",
                "tab-indented-key": "\n\tqa_review_policy:\n\towner: xy-qa\n",
                **QA_REVIEW_POLICY_DUPLICATE_SUFFIXES,
            }
            for machine_relative in (
                "product/WORKFLOW.md",
                "product/AGENT_SCHEMA.md",
                "platforms/shared/skills/xy-qa-review/SKILL.md",
            ):
                machine = fixture / machine_relative
                machine_original = machine.read_text(encoding="utf-8")
                for label, appended in duplicate_suffixes.items():
                    with self.subTest(
                        runtime_authority=machine_relative,
                        runtime_duplicate_token=label,
                    ):
                        machine.write_text(
                            machine_original + appended,
                            encoding="utf-8",
                        )
                        errors = validate_pack_qa_review_policy(fixture)
                        self.assertTrue(errors)
                        self.assertTrue(
                            any(
                                machine_relative in error
                                and "qa_review_policy" in error
                                for error in errors
                            ),
                            errors,
                        )
                machine.write_text(machine_original, encoding="utf-8")

            setup = fixture / "setup_all.sh"
            for retired in RETIRED_QA_POLICY_TERMS:
                setup.write_text(f"# {retired}\n", encoding="utf-8")
                errors = validate_pack_qa_review_policy(fixture)
                self.assertTrue(
                    any(retired in error for error in errors),
                    f"runtime policy validator accepted retired term: {retired}",
                )

    def test_all_host_source_checkers_call_the_shared_review_policy_validator(self) -> None:
        for relative in (
            "setup_codex.sh",
            "lib/validate_claude_artifacts.py",
            "lib/validate_antigravity_artifacts.py",
        ):
            body = self._text(relative)
            with self.subTest(source=relative):
                self.assertIn("from qa_review_policy import validate_pack_qa_review_policy", body)
                self.assertIn("validate_pack_qa_review_policy(", body)


class ControlledDocumentAccessContractTest(unittest.TestCase):
    """Controlled documents are selected per task instead of preloaded per role."""

    def test_project_adapter_has_no_static_role_read_list(self) -> None:
        for path in (PACK / "project.yaml", PACK / "templates/project.yaml.example"):
            with self.subTest(path=path):
                self.assertNotRegex(
                    path.read_text(encoding="utf-8"), r"(?m)^role_reads\s*:"
                )
        self.assertFalse((PACK / "lib/inject_role_reads.py").exists())
        for path in (PACK / "setup_codex.sh", PACK / "setup_claude.sh"):
            self.assertNotIn("inject_role_reads", path.read_text(encoding="utf-8"))

    def test_task_pack_declares_on_demand_progressive_document_access(self) -> None:
        authorities = (
            PACK / "product/WORKFLOW.md",
            PACK / "product/AGENT_SCHEMA.md",
            PACK / "platforms/shared/skills/xy-workflow/SKILL.md",
        )
        for path in authorities:
            body = read_contract(path)
            normalized = " ".join(body.split())
            with self.subTest(path=path):
                self.assertIn("controlled_document_access:", body)
                self.assertIn("adapter: project.yaml", body)
                self.assertIn("mode: targeted | full | skip", body)
                self.assertIn("sections_or_queries: []", body)
                self.assertIn("content_fingerprint", body)
                self.assertIn("applies_to", body)
                self.assertIn("rule_ids", body)
                # 固定读取只保留工作流适配器；三层文档正文必须由任务相关性触发。
                self.assertIn("fixed workflow-adapter read", normalized)
                self.assertIn("not a static", normalized)
                self.assertIn("docs.project", normalized)

    def test_standards_are_selected_by_writer_surface(self) -> None:
        workflow = read_contract(PACK / "platforms/shared/skills/xy-workflow/SKILL.md")
        normalized = " ".join(workflow.split())
        for anchor in (
            "`docs.project` (`PROJECT.md`) is needed",
            "Read design standards only for UI work",
            "shared architecture details or plans only for a relevant missing fact",
            "Every Writer receives the current fingerprinted STANDARDS",
            "`xy-uiux + design_ui` uses design leaves",
            "standards-conformance",
            "`skip` means do not open the body",
        ):
            self.assertIn(anchor, normalized)

    def test_qa_requires_fixed_scope_and_rule_level_standards_coverage(self) -> None:
        qa_skill = read_contract(PACK / "platforms/shared/skills/xy-qa-review/SKILL.md")
        qa_role = (PACK / "roles/xy-qa.md").read_text(encoding="utf-8")
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        for body in (qa_skill, qa_role):
            with self.subTest(source=body[:40]):
                self.assertIn("standards_policy_coverage", body)
                self.assertIn("base/head", body)
                self.assertIn("hard", body)
        self.assertIn("qa_handoff_cli.py validate", qa_skill)
        self.assertIn("qa_handoff_cli.py validate", workflow)

    def test_implementation_roles_reject_missing_standards_authority(self) -> None:
        for role in ("xy-web", "xy-desktop", "xy-backend", "xy-apple", "xy-android"):
            body = (PACK / "roles" / f"{role}.md").read_text(encoding="utf-8")
            normalized = " ".join(body.split())
            with self.subTest(role=role):
                self.assertIn("standards-conformance", body)
                self.assertIn("applicable hard-rule ID", normalized)
                self.assertIn("missing, stale, skipped, or incomplete", normalized)

    def test_roles_consume_only_the_pm_access_plan(self) -> None:
        for path in sorted((PACK / "roles").glob("xy-*.md")):
            body = path.read_text(encoding="utf-8")
            with self.subTest(role=path.stem):
                self.assertIn("controlled_document_access", body)
                self.assertIn("non-`skip`", body)
        active = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                PACK / "product/WORKFLOW.md",
                PACK / "product/AGENT_SCHEMA.md",
                PACK / "platforms/shared/skills/xy-workflow/SKILL.md",
                PACK / "platforms/shared/skills/xy-project-memory/SKILL.md",
                PACK / "platforms/shared/skills/xy-qa-review/SKILL.md",
            )
        )
        self.assertNotIn("role_reads", active)


class ProjectDocumentModelContractTest(unittest.TestCase):
    """PROJECT 只索引当前功能；删除墓碑可检索但不得继续成为当前真相。"""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-doc-model-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.docs = self.root / "docs"
        self.features = self.docs / "features"
        self.features.mkdir(parents=True)
        standards_engineering = self.docs / "standards"
        standards_engineering.mkdir(parents=True)
        (self.docs / "STANDARDS.md").write_text(
            "# Standards\n\n[General](standards/GENERAL.md)\n",
            encoding="utf-8",
        )
        (standards_engineering / "GENERAL.md").write_text(
            "# General\n\n- Domain: engineering\n- `[eng-test-001] [hard]` Test rule.\n",
            encoding="utf-8",
        )
        self.config = self.root / "project.yaml"
        self.config.write_text(
            "docs:\n"
            "  standards: docs/STANDARDS.md\n"
            "  standards_root: docs/standards/\n"
            "  project: docs/PROJECT.md\n"
            "  features: docs/features/\n",
            encoding="utf-8",
        )

    @staticmethod
    def active_feature(feature_id: str) -> str:
        return (
            f"# Active\n\n- Feature ID: `{feature_id}`\n"
            "- Status: `active`\n\n## Current requirements\n\n- Verified behavior.\n"
        )

    @staticmethod
    def removed_feature(feature_id: str) -> str:
        return (
            f"# Removed\n\n- Feature ID: `{feature_id}`\n"
            "- Status: `removed`\n"
            "- Removal date: 2026-08-15\n"
            "- Removal reason: Replaced by the active feature.\n\n"
            "## Historical requirements\n\nHistorical only; do not reimplement.\n"
        )

    def test_active_links_and_unlinked_removed_tombstones_are_valid(self) -> None:
        (self.features / "open-chat.md").write_text(
            self.active_feature("FEATURE-OPENCHAT"), encoding="utf-8"
        )
        (self.features / "legacy-search.removed.md").write_text(
            self.removed_feature("FEATURE-LEGACY-SEARCH"), encoding="utf-8"
        )
        (self.docs / "PROJECT.md").write_text(
            "# Project\n\n[OpenChat](features/open-chat.md)\n", encoding="utf-8"
        )

        self.assertEqual([], validate_project_docs(self.config, self.root))

    def test_unlinked_active_or_linked_removed_feature_fails(self) -> None:
        (self.features / "open-chat.md").write_text(
            self.active_feature("FEATURE-OPENCHAT"), encoding="utf-8"
        )
        (self.features / "legacy.removed.md").write_text(
            self.removed_feature("FEATURE-LEGACY"), encoding="utf-8"
        )
        (self.docs / "PROJECT.md").write_text(
            "# Project\n\n[Legacy](features/legacy.removed.md)\n", encoding="utf-8"
        )

        errors = validate_project_docs(self.config, self.root)
        self.assertTrue(any("must not link removed feature" in item for item in errors))
        self.assertTrue(any("active feature is not linked" in item for item in errors))

    def test_project_size_is_not_a_validation_rule(self) -> None:
        (self.features / "open-chat.md").write_text(
            self.active_feature("FEATURE-OPENCHAT"), encoding="utf-8"
        )
        body = "# Project\n\n[OpenChat](features/open-chat.md)\n" + (
            "\nCurrent verified project fact.\n" * 5000
        )
        (self.docs / "PROJECT.md").write_text(body, encoding="utf-8")

        self.assertEqual([], validate_project_docs(self.config, self.root))

    def test_legacy_authority_reference_fails_direct_upgrade(self) -> None:
        (self.docs / "PROJECT.md").write_text(
            "# Project\n\nLegacy: docs/SPEC.md\n", encoding="utf-8"
        )

        errors = validate_project_docs(self.config, self.root)
        self.assertTrue(any("legacy authority SPEC.md" in item for item in errors))

    def test_physical_legacy_authority_fails_even_when_project_does_not_link_it(self) -> None:
        """直接升级不允许把未链接的旧文件留在仓库中形成隐性双重真相。"""

        (self.docs / "PROJECT.md").write_text("# Project\n", encoding="utf-8")
        (self.docs / "STATUS.md").write_text("# Legacy status\n", encoding="utf-8")

        errors = validate_project_docs(self.config, self.root)
        self.assertTrue(
            any("unsupported legacy authority must be removed" in item for item in errors)
        )

    def test_standards_index_requires_complete_links_and_unique_rule_ids(self) -> None:
        """索引遗漏叶文档或不同叶复用同一规则 ID 时，不得形成多义规范权威。"""

        (self.docs / "PROJECT.md").write_text("# Project\n", encoding="utf-8")
        upstream = self.docs / "standards/UPSTREAM.md"
        upstream.write_text(
            "# Upstream\n\n- `[eng-upstream-test] [hard]` Protect upstream.\n",
            encoding="utf-8",
        )
        errors = validate_project_docs(self.config, self.root)
        self.assertTrue(any("not linked from STANDARDS.md" in item for item in errors))

        (self.docs / "STANDARDS.md").write_text(
            "# Standards\n\n"
            "[General](standards/GENERAL.md)\n"
            "[Upstream](standards/UPSTREAM.md)\n",
            encoding="utf-8",
        )
        upstream.write_text(
            "# Upstream\n\n- `[eng-test-001] [hard]` Duplicate owner.\n",
            encoding="utf-8",
        )
        errors = validate_project_docs(self.config, self.root)
        self.assertTrue(any("duplicate standards rule ID" in item for item in errors))


class ProjectConfigDiscoveryContractTest(unittest.TestCase):
    """Task 6: config validation delegates all workspace facts to discovery."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-config-discovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "project"
        self.root.mkdir()
        self.config = self.root / "project.yaml"

    @staticmethod
    def _base_config(workspace: str) -> str:
        return (
            "project_name: Fixture\n\n"
            "memory:\n"
            "  provider: agentmemory\n"
            "  mode: preferred\n"
            "  isolation: strict\n"
            "  project_id: fixture-project\n"
            "  qa_requires_provider: false\n"
            "  portable_checkpoint: docs/PROJECT.md\n"
            "  fallback_dir: docs/notes/\n\n"
            "orchestration:\n"
            "  max_concurrent_subagents: 2\n"
            "  max_parallel_writers: 2\n"
            "  max_writers_per_path: 1\n"
            "  max_depth: 1\n\n"
            f"{workspace.rstrip()}\n\n"
            "docs:\n"
            "  standards: docs/STANDARDS.md\n"
            "  standards_root: docs/standards/\n"
            "  project: docs/PROJECT.md\n"
            "  features: docs/features/\n"
            "  plans: docs/plans/\n"
            "  notes: docs/notes/\n"
        )

    def _invoke(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(PACK / "lib/validate_project_config.py"),
                str(self.config),
                str(self.root),
                str(PACK / "roles"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def _run(self, workspace: str) -> subprocess.CompletedProcess[str]:
        self.config.write_text(self._base_config(workspace), encoding="utf-8")
        return self._invoke()

    def _assert_rejected(self, workspace: str, pattern: str) -> None:
        result = self._run(workspace)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stderr, pattern)

    def test_minimal_auto_discovery_config_validates_and_exposes_profile(self) -> None:
        result = self._run("workspace:\n  discovery: auto")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        code = (
            "import sys; "
            f"sys.path.insert(0, {str(PACK / 'lib')!r}); "
            "import validate_project_config as config; "
            f"result=config.validate_with_profile({str(self.config)!r}, "
            f"{str(self.root)!r}, {str(PACK / 'roles')!r}); "
            "assert result.errors == (); "
            "assert result.profile.enabled_roles == ('xy-qa', 'xy-uiux')"
        )
        api = subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(api.returncode, 0, api.stdout + api.stderr)

    def test_retired_manual_workspace_sections_fail_closed(self) -> None:
        retired = {
            "sandboxes": "sandboxes:\n  xy-web: web/",
            "enabled_roles": "enabled_roles:\n  - xy-web",
            "commands": "commands:\n  test: pytest",
            "role_reads": "role_reads:\n  xy-web:\n    - docs/ENGINEERING.md",
        }
        for key, section in retired.items():
            with self.subTest(key=key):
                self._assert_rejected(
                    "workspace:\n  discovery: auto\nworkspace_overrides: {}\n"
                    + section,
                    rf"unsupported retired top-level key: {key}",
                )

    def test_retired_document_aliases_fail_closed(self) -> None:
        aliases = {
            "dev_rules": "docs/ENGINEERING.md",
            "design": "docs/design/",
            "project_status": "docs/PROJECT.md",
            "contracts": "docs/LEGACY-SPEC.md",
            "progress": "docs/LEGACY-STATUS.md",
            "ops": "docs/OPERATIONS.md",
        }
        for key, value in aliases.items():
            with self.subTest(key=key):
                body = self._base_config("workspace:\n  discovery: auto")
                body = body.replace(
                    "  standards: docs/STANDARDS.md\n",
                    f"  standards: docs/STANDARDS.md\n  {key}: {value}\n",
                    1,
                )
                self.config.write_text(body, encoding="utf-8")
                result = self._invoke()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"unsupported docs key: {key}", result.stderr)

    def test_safe_include_exclude_and_role_assignments_reach_discovery(self) -> None:
        (self.root / "service").mkdir()
        (self.root / "vendor").mkdir()
        (self.root / "service/package.json").write_text(
            '{"dependencies":{"react":"19"}}', encoding="utf-8"
        )
        result = self._run(
            "workspace:\n"
            "  discovery: auto\n"
            "workspace_overrides:\n"
            "  include:\n"
            "    service/: xy-backend\n"
            "  exclude:\n"
            "    - vendor/"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_overrides_reject_unsafe_paths_roles_and_types(self) -> None:
        (self.root / "service").mkdir()
        (self.root / "service/nested").mkdir()
        (self.root / "ordinary.txt").write_text("file\n", encoding="utf-8")
        (self.root / "alias").symlink_to("service", target_is_directory=True)
        os.mkfifo(self.root / "pipe")
        cases = {
            "escape": (
                "  include:\n    ../outside: xy-backend",
                r"must not be absolute or contain|relative POSIX path",
            ),
            "noncanonical-role": (
                "  include:\n    service: xy-python",
                r"unsupported module override role",
            ),
            "file": (
                "  include:\n    ordinary.txt: xy-backend",
                r"real non-symlink directory",
            ),
            "symlink": (
                "  include:\n    alias: xy-backend",
                r"real non-symlink directory",
            ),
            "special": (
                "  include:\n    pipe: xy-backend",
                r"real non-symlink directory",
            ),
            "exclude-not-list": (
                "  exclude: service",
                r"workspace_overrides.exclude must be a block list",
            ),
        }
        for label, (body, pattern) in cases.items():
            with self.subTest(label=label):
                self._assert_rejected(
                    "workspace:\n  discovery: auto\nworkspace_overrides:\n" + body,
                    pattern,
                )

    def test_overrides_reject_duplicates_conflicts_and_ancestor_overlaps(self) -> None:
        (self.root / "service/nested").mkdir(parents=True)
        (self.root / "vendor/generated").mkdir(parents=True)
        cases = {
            "duplicate-normalized-include": (
                "  include:\n"
                "    service: xy-backend\n"
                "    service/: xy-backend",
                r"duplicate normalized include root",
            ),
            "conflicting-normalized-include": (
                "  include:\n"
                "    service: xy-backend\n"
                "    service/: xy-web",
                r"conflicting role assignments",
            ),
            "include-ancestor": (
                "  include:\n"
                "    service: xy-backend\n"
                "    service/nested: xy-backend",
                r"include roots must not overlap",
            ),
            "exclude-ancestor": (
                "  exclude:\n"
                "    - vendor\n"
                "    - vendor/generated",
                r"exclude roots must not overlap",
            ),
            "include-exclude-collision": (
                "  include:\n"
                "    service: xy-backend\n"
                "  exclude:\n"
                "    - service/nested",
                r"cannot be both assigned and excluded",
            ),
        }
        for label, (body, pattern) in cases.items():
            with self.subTest(label=label):
                self._assert_rejected(
                    "workspace:\n  discovery: auto\nworkspace_overrides:\n" + body,
                    pattern,
                )

    def test_validation_is_read_only_even_when_discovery_rejects(self) -> None:
        (self.root / "service").mkdir()
        self.config.write_text(
            self._base_config(
                "workspace:\n  discovery: manual\nworkspace_overrides: {}"
            ),
            encoding="utf-8",
        )
        before = tuple(
            sorted(
                (
                    path.relative_to(self.root).as_posix(),
                    stat.S_IFMT(path.lstat().st_mode),
                    path.lstat().st_mode & 0o777,
                    path.read_bytes() if path.is_file() else None,
                )
                for path in self.root.rglob("*")
            )
        )
        result = self._invoke()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stderr, r"workspace.discovery must be auto")
        after = tuple(
            sorted(
                (
                    path.relative_to(self.root).as_posix(),
                    stat.S_IFMT(path.lstat().st_mode),
                    path.lstat().st_mode & 0o777,
                    path.read_bytes() if path.is_file() else None,
                )
                for path in self.root.rglob("*")
            )
        )
        self.assertEqual(before, after)
        self.assertFalse(any(path.name == "__pycache__" for path in self.root.rglob("*")))

    def test_validation_rejects_a_symlinked_project_root_without_writes(self) -> None:
        alias = self.root.parent / "project-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.config.write_text(
            self._base_config("workspace:\n  discovery: auto"), encoding="utf-8"
        )
        before = tuple(
            sorted(
                (
                    path.relative_to(self.root).as_posix(),
                    stat.S_IFMT(path.lstat().st_mode),
                    path.lstat().st_mode & 0o777,
                    path.read_bytes() if path.is_file() else None,
                )
                for path in self.root.rglob("*")
            )
        )

        code = (
            "import sys; "
            f"sys.path.insert(0, {str(PACK / 'lib')!r}); "
            "import validate_project_config as config; "
            f"result=config.validate_with_profile({str(self.config)!r}, "
            f"{str(alias)!r}, {str(PACK / 'roles')!r}); "
            "assert result.profile is None; "
            "assert any('project root' in error and 'symlink' in error "
            "for error in result.errors)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = tuple(
            sorted(
                (
                    path.relative_to(self.root).as_posix(),
                    stat.S_IFMT(path.lstat().st_mode),
                    path.lstat().st_mode & 0o777,
                    path.read_bytes() if path.is_file() else None,
                )
                for path in self.root.rglob("*")
            )
        )
        self.assertEqual(before, after)
        self.assertFalse(any(path.name == "__pycache__" for path in self.root.rglob("*")))

    def test_common_and_guard_consume_discovered_profile_not_retired_yaml(self) -> None:
        common = (PACK / "lib/common.sh").read_text(encoding="utf-8")
        guard = (PACK / "scripts/guard.sh").read_text(encoding="utf-8")
        for source, body in (("common", common), ("guard", guard)):
            with self.subTest(source=source):
                self.assertIn("validate_with_profile", body)
                self.assertIn("profile.modules", body)
                self.assertNotIn("project_sandboxes.py", body)
                self.assertNotRegex(body, r"py_yaml .* (?:enabled_roles|commands)")

    def test_guard_attributes_changes_to_the_most_specific_discovered_module(self) -> None:
        installed = self.root / "agent_workflow"
        (installed / "lib").mkdir(parents=True)
        (installed / "scripts").mkdir()
        (installed / "roles").mkdir()
        for name in ("validate_project_config.py", "project_discovery.py", "worktree_policy.py", "workflow_hook_settings.py", "python_runtime.sh"):
            shutil.copy2(PACK / "lib" / name, installed / "lib" / name)
        shutil.copy2(PACK / "scripts/guard.sh", installed / "scripts/guard.sh")
        for role in (PACK / "roles").glob("xy-*.md"):
            shutil.copy2(role, installed / "roles" / role.name)

        (self.root / "apps/web").mkdir(parents=True)
        (self.root / "package.json").write_text(
            '{"main":"main.js","dependencies":{"electron":"40"}}',
            encoding="utf-8",
        )
        (self.root / "main.js").write_text("export const root = 1;\n", encoding="utf-8")
        (self.root / "apps/web/package.json").write_text(
            '{"dependencies":{"react":"19"}}', encoding="utf-8"
        )
        (self.root / "apps/web/src.js").write_text(
            "export const nested = 1;\n", encoding="utf-8"
        )
        (installed / "project.yaml").write_text(
            self._base_config(
                "workspace:\n  discovery: auto\nworkspace_overrides: {}"
            ),
            encoding="utf-8",
        )

        git = ["git", "-C", str(self.root)]
        for command in (
            (*git, "init", "-q"),
            (*git, "config", "user.email", "guard-test@example.invalid"),
            (*git, "config", "user.name", "Guard Test"),
            (*git, "add", "."),
            (*git, "commit", "-qm", "baseline"),
        ):
            subprocess.run(command, check=True, capture_output=True, text=True)
        (self.root / "main.js").write_text("export const root = 2;\n", encoding="utf-8")
        (self.root / "apps/web/src.js").write_text(
            "export const nested = 2;\n", encoding="utf-8"
        )
        subprocess.run(
            (*git, "status", "--porcelain"),
            check=True,
            capture_output=True,
            text=True,
        )
        before = tuple(
            entry
            for entry in ProjectDiscoveryContractTest._tree_snapshot(self.root)
            if entry[0] != ".git" and not str(entry[0]).startswith(".git/")
        )

        result = subprocess.run(
            ["bash", str(installed / "scripts/guard.sh")],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"\[xy-web\]\s+apps/web/src\.js")
        self.assertRegex(result.stdout, r"\[xy-desktop\]\s+main\.js")
        after = tuple(
            entry
            for entry in ProjectDiscoveryContractTest._tree_snapshot(self.root)
            if entry[0] != ".git" and not str(entry[0]).startswith(".git/")
        )
        self.assertEqual(before, after)


class CanonicalRoleConvergenceContractTest(unittest.TestCase):
    """Task 5: seven lean, repository-driven canonical role sources."""

    @staticmethod
    def _role_text(role: str) -> str:
        return (PACK / "roles" / f"{role}.md").read_text(encoding="utf-8")

    @staticmethod
    def _section(text: str, heading: str) -> str:
        start = text.index(heading) + len(heading)
        match = re.search(r"(?m)^## ", text[start:])
        return text[start:] if match is None else text[start : start + match.start()]

    def test_role_bodies_have_exactly_the_canonical_ordered_sections(self) -> None:
        for role in TASK5_CANONICAL_ROLE_IDS:
            with self.subTest(role=role):
                text = self._role_text(role)
                headings = tuple(re.findall(r"(?m)^## .+$", text))
                self.assertEqual(TASK5_ROLE_H2S, headings)
                self.assertIn(f"name: {role}\n", text)
                self.assertIn("workspace: inherit\n", text)

    def test_role_sources_do_not_embed_generated_or_global_context(self) -> None:
        # 角色源保持职责化和按需读取，不使用任意字数/字节阈值阻断必要规则。
        for role in TASK5_CANONICAL_ROLE_IDS:
            with self.subTest(role=role):
                body = self._role_text(role)
                self.assertNotIn("# Global Mandatory Constraints", body)
                self.assertNotIn("## Discovered project modules", body)
                self.assertNotIn("Repository-native verification commands:", body)

    def test_all_roles_enforce_common_task_authority_evidence_and_pm_boundaries(self) -> None:
        required = (
            "controlled_document_access",
            "owned_paths",
            "exact commands",
            "exit codes",
            "complete-log",
            "Communicate only with the PM",
            "no nested Agent delegation",
            "Only the PM performs project memory closeout",
            "current",
            "repository",
        )
        forbidden = (
            "Contact the user directly for decisions.",
            "Report completion directly to the user.",
            "Delegate implementation to another Agent.",
            "Save memory even when project isolation is unavailable.",
        )
        for role in TASK5_CANONICAL_ROLE_IDS:
            with self.subTest(role=role):
                text = self._role_text(role)
                folded = text.casefold()
                for phrase in required:
                    self.assertIn(phrase.casefold(), folded)
                for phrase in forbidden:
                    self.assertNotIn(phrase.casefold(), folded)
                success = self._section(text, "## 11. Success Criteria")
                self.assertIn("approved", success.casefold())
                self.assertIn("repository", success.casefold())

    def test_implementation_roles_are_repository_driven_direct_implementers(self) -> None:
        role_specific = {
            "xy-web": (
                "actual repository stack",
                "production implementation",
                "desktop renderer",
                "prototype-only mock",
            ),
            "xy-backend": (
                "regardless of their programming language",
                "server applications",
                "systems implementation diff",
                "no preferred language",
            ),
            "xy-desktop": (
                "Electron",
                "Tauri",
                "renderer",
                "main process",
                "preload",
                "IPC",
                "capabilities",
                "sidecar",
                "OS integration",
                "signing",
                "notarization",
                "updates",
                "per-platform",
            ),
            "xy-apple": (
                "repository-derived",
                "Xcode",
                "minimum OS",
                "Apple-platform source changes",
            ),
            "xy-android": (
                "repository-derived",
                "Gradle",
                "Android source changes",
                "minimum SDK",
            ),
        }
        forbidden_defaults = (
            "Use microservices by default",
            "Cloud deployment is required",
            "SLO: 99.9%",
            "Use the universal version lock",
        )
        for role, phrases in role_specific.items():
            with self.subTest(role=role):
                text = self._role_text(role)
                folded = text.casefold()
                for phrase in phrases:
                    self.assertIn(phrase.casefold(), folded)
                for forbidden in forbidden_defaults:
                    self.assertNotIn(forbidden.casefold(), folded)

    def test_desktop_role_enforces_security_release_and_no_migration_claims(self) -> None:
        text = self._role_text("xy-desktop")
        for phrase in (
            "least privilege",
            "renderer",
            "main process",
            "preload",
            "native command",
            "sidecar",
            "package",
            "signing",
            "notarization",
            "updater",
            "honest per-platform evidence",
            "must not migrate Electron to Tauri",
            "must not migrate Tauri to Electron",
            "must not generate screenshots",
        ):
            self.assertIn(phrase.casefold(), text.casefold())

    def test_desktop_renderer_consumes_the_approved_page_contract_and_fingerprint(self) -> None:
        text = self._role_text("xy-desktop")
        intake = self._section(text, "## 5. Task Intake Contract").casefold()
        workflow = self._section(text, "## 6. Execution Workflow").casefold()
        rules = self._section(text, "## 4. Critical Operating Rules").casefold()
        verification = self._section(text, "## 8. Verification and Evidence").casefold()
        success = self._section(text, "## 11. Success Criteria").casefold()

        missing: list[str] = []
        for phrase in ("approved concrete html page path", "dependency fingerprint"):
            if phrase not in intake:
                missing.append(f"intake:{phrase}")
        for phrase in (
            "full five-section",
            "page design and interaction contract",
            "recompute",
            "before implementation",
        ):
            if phrase not in workflow:
                missing.append(f"workflow:{phrase}")
        for phrase in (
            "prototype-only mock data",
            "fake apis",
            "demo timers",
            "prototype routing",
            "debug or state controls",
            "data-prototype-*",
            "in-page design-contract markup",
        ):
            if phrase not in rules:
                missing.append(f"rules:{phrase}")
        for section_name, section in (("verification", verification), ("success", success)):
            for phrase in ("recompute", "dependency fingerprint", "match the approved value"):
                if phrase not in section:
                    missing.append(f"{section_name}:{phrase}")
        self.assertEqual([], missing)

    def test_desktop_remote_content_and_renderer_never_receive_generic_local_privileges(self) -> None:
        rules = self._section(
            self._role_text("xy-desktop"), "## 4. Critical Operating Rules"
        ).casefold()
        required = (
            "remote content never inherits local privileges",
            "renderer code never receives generic filesystem, shell, node, or equivalent unrestricted local capabilities",
        )
        self.assertEqual([], [phrase for phrase in required if phrase not in rules])

    def test_uiux_metadata_has_no_wait_decision_deliverable(self) -> None:
        catalog = (PACK / "product/ROLES.yaml").read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^  xy-uiux:\s*$(?P<body>.*?)(?=^  xy-[a-z0-9-]+:\s*$|\Z)",
            catalog,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertNotIn("wait-decision", match.group("body"))

    def test_backend_routes_every_desktop_surface_to_xy_desktop(self) -> None:
        routing = self._section(
            self._role_text("xy-backend"), "## 12. Routing"
        ).casefold()
        required = (
            "electron",
            "tauri",
            "renderer",
            "main process",
            "preload",
            "rust core",
            "native commands",
            "sidecars",
            "packaging",
            "release",
            "xy-desktop",
        )
        self.assertEqual([], [phrase for phrase in required if phrase not in routing])

    def test_uiux_and_qa_preserve_visual_and_read_only_contracts(self) -> None:
        uiux = self._role_text("xy-uiux")
        for phrase in (
            "build-free",
            'data-contract-section="purpose"',
            'data-contract-section="navigation"',
            'data-contract-section="interactions"',
            'data-contract-section="states"',
            'data-contract-section="exceptions"',
            "direct link to each concrete changed page",
            "MUST NOT generate, persist, attach, or present screenshots",
            "must not create a Manifest",
            "must not create companion",
        ):
            self.assertIn(phrase.casefold(), uiux.casefold())

        qa = self._role_text("xy-qa")
        for phrase in (
            "read-only",
            "PASS | FAIL",
            "desktop renderer",
            "IPC",
            "signing",
            "notarization",
            "updater",
            "ephemerally in memory",
            "must not persist, save, write, attach, or present",
        ):
            self.assertIn(phrase.casefold(), qa.casefold())

    def test_qa_machine_handoff_uses_only_the_exact_pass_fail_label(self) -> None:
        qa = self._role_text("xy-qa")
        self.assertIn("[Audit result] PASS | FAIL", qa)
        communication = self._section(qa, "## 9. Communication Style")
        self.assertIn("[Audit result] PASS | FAIL", communication)

    def test_catalog_and_schema_name_the_exact_roster_with_pm_separate(self) -> None:
        catalog = (PACK / "product/ROLES.yaml").read_text(encoding="utf-8")
        actual = PortableRoleDiscoveryContractTest._catalog_worker_role_ids_from_text(
            catalog
        )
        self.assertEqual(set(TASK5_CANONICAL_ROLE_IDS), actual)
        self.assertRegex(catalog, r"(?m)^pm:\s*$")
        self.assertNotRegex(catalog, r"(?m)^  pm:\s*$")

        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        for role in TASK5_CANONICAL_ROLE_IDS:
            self.assertIn(f"| {role} |", schema)
        self.assertIn("PM metadata is outside the ordinary role schema", schema)
        self.assertIn("automatically discovered", schema)
        for retired in RETIRED_LANGUAGE_ROLE_IDS:
            self.assertNotIn(f"| {retired} |", schema)

    def test_named_roster_lines_do_not_change_workflow_business_invariants(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        constraints = (PACK / "product/GLOBAL_CONSTRAINTS.md").read_text(
            encoding="utf-8"
        )
        for role in TASK5_CANONICAL_ROLE_IDS:
            self.assertIn(role, workflow)
        for phrase in (
            "requirements_approved",
            "visual_approved",
            "dependency closure",
            "PASS",
            "agentmemory",
            "Page design and interaction contract",
        ):
            self.assertIn(phrase, workflow)
        self.assertIn("requirements_approved", constraints)
        self.assertIn("visual_approved", constraints)
        self.assertIn("PM", constraints)


class ProjectClassificationContractTest(unittest.TestCase):
    """Task 3: deterministic role classification above the safe scanner."""

    @staticmethod
    def _write_tree(root: Path, files: dict[str, str]) -> None:
        for relative, body in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    def _discover_files(self, files: dict[str, str]) -> ProjectProfile:
        temporary = tempfile.TemporaryDirectory(prefix="project-classification-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        self._write_tree(root, files)
        return discover_project(root)

    @staticmethod
    def _module_pairs(profile: ProjectProfile) -> tuple[tuple[str, str], ...]:
        return tuple(
            (module.root, module.primary_role) for module in profile.modules
        )

    def test_browser_node_and_tooling_packages_require_positive_runtime_evidence(
        self,
    ) -> None:
        profile = self._discover_files(
            {
                "apps/browser/package.json": (
                    '{"dependencies":{"react":"19.0.0"}}'
                ),
                "services/api/package.json": (
                    '{"dependencies":{"express":"5.0.0"}}'
                ),
                "packages/tooling/package.json": (
                    '{"devDependencies":{"typescript":"6.0.0"}}'
                ),
                "packages/library/package.json": (
                    '{"main":"index.js","files":["index.js"]}'
                ),
                "packages/library/index.js": "export const value = 1;\n",
            }
        )

        self.assertEqual(
            (
                ("apps/browser", "xy-web"),
                ("services/api", "xy-backend"),
            ),
            self._module_pairs(profile),
        )
        api = next(module for module in profile.modules if module.root == "services/api")
        self.assertIn("runtime:node", api.stack_facts)
        self.assertIn("framework:express", api.stack_facts)

    def test_language_neutral_openapi_service_requires_checked_in_runtime_evidence(
        self,
    ) -> None:
        valid = self._discover_files(
            {
                "services/unknown/openapi.json": (
                    '{"openapi":"3.1.0","info":{"title":"Unknown service",'
                    '"version":"1"},"paths":{"/health":{"get":{}}}}'
                ),
                "services/unknown/Dockerfile": "FROM scratch\nCOPY service /service\n",
            }
        )
        self.assertEqual(
            (("services/unknown", "xy-backend"),), self._module_pairs(valid)
        )
        module = valid.modules[0]
        self.assertIn("contract:openapi", module.stack_facts)
        self.assertIn("service:language-neutral", module.stack_facts)
        self.assertEqual(
            (
                "services/unknown/Dockerfile",
                "services/unknown/openapi.json",
            ),
            module.evidence_paths,
        )

        for label, files in {
            "contract-only": {
                "openapi.json": (
                    '{"openapi":"3.1.0","info":{"title":"API","version":"1"},'
                    '"paths":{"/health":{"get":{}}}}'
                )
            },
            "container-only": {"Dockerfile": "FROM scratch\n"},
            "empty-paths": {
                "openapi.json": (
                    '{"openapi":"3.1.0","info":{"title":"API","version":"1"},'
                    '"paths":{}}'
                ),
                "Dockerfile": "FROM scratch\n",
            },
        }.items():
            with self.subTest(label=label):
                self.assertEqual((), self._discover_files(files).modules)

    def test_electron_requires_application_evidence_beyond_a_dependency(self) -> None:
        valid_cases = {
            "real-main-entry": {
                "package.json": (
                    '{"main":"src/main.js","dependencies":{"electron":"40"}}'
                ),
                "src/main.js": "export {};\n",
            },
            "forge-package-config": {
                "package.json": (
                    '{"devDependencies":{"electron":"40",'
                    '"@electron-forge/cli":"7"},'
                    '"config":{"forge":{"packagerConfig":{}}}}'
                ),
            },
            "builder-package-config": {
                "package.json": (
                    '{"devDependencies":{"electron":"40",'
                    '"electron-builder":"26"},'
                    '"build":{"appId":"example.desktop"}}'
                ),
            },
        }
        for label, files in valid_cases.items():
            with self.subTest(valid=label):
                profile = self._discover_files(files)
                self.assertEqual(((".", "xy-desktop"),), self._module_pairs(profile))
                self.assertIn("desktop:electron", profile.detected_stack_facts)

        false_positive_cases = {
            "dependency-only": {
                "package.json": '{"devDependencies":{"electron":"40"}}'
            },
            "browser-with-electron-api-only": {
                "package.json": (
                    '{"dependencies":{"react":"19",'
                    '"@electron/remote":"2"}}'
                )
            },
            "escaping-main-entry": {
                "package.json": (
                    '{"main":"../outside.js",'
                    '"dependencies":{"electron":"40"}}'
                )
            },
        }
        for label, files in false_positive_cases.items():
            with self.subTest(false_positive=label):
                profile = self._discover_files(files)
                self.assertNotIn("xy-desktop", profile.primary_roles)

    def test_tauri_requires_recognizable_config_and_src_tauri_cargo_evidence(
        self,
    ) -> None:
        valid = self._discover_files(
            {
                "package.json": '{"dependencies":{"react":"19"}}',
                "src-tauri/tauri.conf.json": (
                    '{"productName":"Fixture","identifier":"example.fixture"}'
                ),
                "src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                    '[dependencies]\ntauri="2"\n'
                ),
            }
        )
        self.assertEqual(((".", "xy-desktop"),), self._module_pairs(valid))
        self.assertIn("desktop:tauri", valid.detected_stack_facts)

        cases = {
            "config-without-tauri-cargo": {
                "package.json": '{"dependencies":{"react":"19"}}',
                "src-tauri/tauri.conf.json": '{"productName":"Fixture"}',
                "src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                ),
            },
            "tauri-cargo-without-config": {
                "package.json": '{"dependencies":{"react":"19"}}',
                "src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                    '[dependencies]\ntauri="2"\n'
                ),
            },
            "empty-config-is-not-application-evidence": {
                "package.json": '{"dependencies":{"react":"19"}}',
                "src-tauri/tauri.conf.json": "{}",
                "src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                    '[dependencies]\ntauri="2"\n'
                ),
            },
            "npm-api-dependency-only": {
                "package.json": (
                    '{"dependencies":{"react":"19",'
                    '"@tauri-apps/api":"2"}}'
                )
            },
        }
        for label, files in cases.items():
            with self.subTest(false_positive=label):
                profile = self._discover_files(files)
                self.assertNotIn("xy-desktop", profile.primary_roles)

    def test_electron_renderer_main_and_preload_are_one_desktop_module(self) -> None:
        profile = self._discover_files(
            {
                "apps/shell/package.json": (
                    '{"main":"main/index.js",'
                    '"dependencies":{"electron":"40"}}'
                ),
                "apps/shell/main/index.js": "export {};\n",
                "apps/shell/main/package.json": (
                    '{"dependencies":{"express":"5"}}'
                ),
                "apps/shell/preload/Cargo.toml": (
                    '[package]\nname="preload-native"\nversion="0.1.0"\n'
                ),
                "apps/shell/renderer/package.json": (
                    '{"dependencies":{"react":"19"}}'
                ),
            }
        )

        self.assertEqual(
            (("apps/shell", "xy-desktop"),), self._module_pairs(profile)
        )
        module = profile.modules[0]
        self.assertIn("desktop:electron", module.stack_facts)
        self.assertIn("framework:react", module.stack_facts)
        self.assertIn("runtime:node", module.stack_facts)
        self.assertIn("language:rust", module.stack_facts)
        self.assertIn("apps/shell/renderer/package.json", module.evidence_paths)

    def test_tauri_frontend_and_src_tauri_are_one_desktop_module(self) -> None:
        profile = self._discover_files(
            {
                "tools/desktop/frontend/package.json": (
                    '{"dependencies":{"vue":"3"}}'
                ),
                "tools/desktop/src-tauri/tauri.conf.json": (
                    '{"productName":"Fixture","identifier":"example.fixture"}'
                ),
                "tools/desktop/src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                    '[dependencies]\ntauri="2"\n'
                ),
            }
        )

        self.assertEqual(
            (("tools/desktop", "xy-desktop"),), self._module_pairs(profile)
        )
        module = profile.modules[0]
        self.assertIn("desktop:tauri", module.stack_facts)
        self.assertIn("framework:vue", module.stack_facts)
        self.assertIn(
            "tools/desktop/frontend/package.json", module.evidence_paths
        )

    def test_apple_application_and_server_swift_package_are_distinct(self) -> None:
        application_project = (
            "// !$*UTF8*$!\n"
            "{\n"
            "  objects = {\n"
            "    A1 = {\n"
            "      isa = PBXNativeTarget;\n"
            '      productType = "com.apple.product-type.application";\n'
            "    };\n"
            "  };\n"
            "}\n"
        )
        non_application_project = (
            "// !$*UTF8*$!\n"
            "{\n"
            "  objects = {\n"
            "    F1 = {\n"
            "      isa = PBXNativeTarget;\n"
            '      productType = "com.apple.product-type.framework";\n'
            "    };\n"
            "  };\n"
            "}\n"
        )
        profile = self._discover_files(
            {
                "apps/ios/Fixture.xcodeproj/project.pbxproj": application_project,
                "libraries/apple/Framework.xcodeproj/project.pbxproj": (
                    non_application_project
                ),
                "services/swift/Package.swift": (
                    "// swift-tools-version: 6.0\n"
                    "import PackageDescription\n"
                    "let package = Package(\n"
                    '  name: "Server",\n'
                    "  products: [.executable(name: \"server\", targets: [\"Server\"])],\n"
                    "  targets: [.executableTarget(name: \"Server\")]\n"
                    ")\n"
                ),
            }
        )

        self.assertEqual(
            (
                ("apps/ios", "xy-apple"),
                ("services/swift", "xy-backend"),
            ),
            self._module_pairs(profile),
        )
        swift = next(
            module for module in profile.modules if module.root == "services/swift"
        )
        self.assertIn("language:swift", swift.stack_facts)

    def test_android_requires_real_plugin_and_manifest_while_kotlin_server_is_backend(
        self,
    ) -> None:
        profile = self._discover_files(
            {
                "apps/android/build.gradle.kts": (
                    'plugins { id("com.android.application") version "9.0.0" }\n'
                ),
                "apps/android/src/main/AndroidManifest.xml": (
                    '<manifest package="example.fixture"/>'
                ),
                "services/kotlin/build.gradle.kts": (
                    'plugins { kotlin("jvm") version "2.2.0"; application }\n'
                    'application { mainClass.set("example.ServerKt") }\n'
                ),
                "services/comment-only/build.gradle.kts": (
                    '// id("com.android.application")\n'
                    'plugins { kotlin("jvm") version "2.2.0" }\n'
                ),
                "services/comment-only/src/main/AndroidManifest.xml": (
                    '<manifest package="example.notandroid"/>'
                ),
            }
        )

        self.assertEqual(
            (
                ("apps/android", "xy-android"),
                ("services/comment-only", "xy-backend"),
                ("services/kotlin", "xy-backend"),
            ),
            self._module_pairs(profile),
        )

    def test_android_version_catalog_alias_resolves_checked_in_plugin_id(self) -> None:
        profile = self._discover_files(
            {
                "apps/android/build.gradle.kts": (
                    "plugins { alias(libs.plugins.android.application) }\n"
                ),
                "gradle/libs.versions.toml": (
                    '[versions]\nagp = "9.0.0"\n'
                    '[plugins]\nandroid-application = '
                    '{ id = "com.android.application", version.ref = "agp" }\n'
                    'android-fake = { id = "java" }\n'
                ),
                "apps/android/gradlew": "#!/bin/sh\n",
                "apps/android/src/main/AndroidManifest.xml": (
                    '<manifest package="example.catalog"/>'
                ),
                "services/not-android/build.gradle.kts": (
                    "plugins { alias(libs.plugins.android.fake) }\n"
                ),
                "services/not-android/src/main/AndroidManifest.xml": (
                    '<manifest package="example.backend"/>'
                ),
            }
        )

        self.assertEqual(
            (
                ("apps/android", "xy-android"),
                ("services/not-android", "xy-backend"),
            ),
            self._module_pairs(profile),
        )
        android = next(module for module in profile.modules if module.root == "apps/android")
        self.assertEqual(
            (
                "apps/android/build.gradle.kts",
                "apps/android/src/main/AndroidManifest.xml",
                "gradle/libs.versions.toml",
            ),
            android.evidence_paths,
        )
        self.assertEqual(
            {
                ("build", ("./gradlew", "assembleDebug")),
                ("test", ("./gradlew", "testDebugUnitTest")),
            },
            {
                (command.purpose, command.argv)
                for command in android.verification_commands
            },
        )
        self.assertTrue(
            all(
                "gradle/libs.versions.toml" in command.evidence_paths
                for command in android.verification_commands
            )
        )

    def test_nested_monorepo_keeps_desktop_beside_independent_web_and_backend(
        self,
    ) -> None:
        profile = self._discover_files(
            {
                "package.json": (
                    '{"private":true,"workspaces":["products/*","services/*"]}'
                ),
                "products/browser/package.json": (
                    '{"dependencies":{"svelte":"5"}}'
                ),
                "products/desktop/package.json": (
                    '{"main":"electron/main.js",'
                    '"dependencies":{"electron":"40"}}'
                ),
                "products/desktop/electron/main.js": "export {};\n",
                "products/desktop/renderer/package.json": (
                    '{"dependencies":{"react":"19"}}'
                ),
                "services/nested/api/package.json": (
                    '{"dependencies":{"fastify":"5"}}'
                ),
            }
        )

        self.assertEqual(
            (
                ("products/browser", "xy-web"),
                ("products/desktop", "xy-desktop"),
                ("services/nested/api", "xy-backend"),
            ),
            self._module_pairs(profile),
        )

    def test_root_desktop_apps_do_not_absorb_independent_manifested_modules(
        self,
    ) -> None:
        desktop_roots = {
            "electron": {
                "package.json": (
                    '{"main":"main.js","dependencies":{"electron":"40"}}'
                ),
                "main.js": "export {};\n",
            },
            "tauri": {
                "package.json": '{"dependencies":{"react":"19"}}',
                "src-tauri/tauri.conf.json": (
                    '{"productName":"Fixture","identifier":"example.fixture"}'
                ),
                "src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                    '[dependencies]\ntauri="2"\n'
                ),
            },
        }
        independent_modules = {
            "apps/browser/package.json": (
                '{"dependencies":{"react":"19"}}'
            ),
            "services/api/package.json": (
                '{"dependencies":{"fastify":"5"}}'
            ),
        }

        for label, desktop_files in desktop_roots.items():
            with self.subTest(desktop=label):
                profile = self._discover_files(
                    {**desktop_files, **independent_modules}
                )
                self.assertEqual(
                    (
                        (".", "xy-desktop"),
                        ("apps/browser", "xy-web"),
                        ("services/api", "xy-backend"),
                    ),
                    self._module_pairs(profile),
                )

    def test_electron_owned_surfaces_absorb_generic_nested_manifests(self) -> None:
        profile = self._discover_files(
            {
                "apps/shell/package.json": (
                    '{"main":"main/index.js",'
                    '"dependencies":{"electron":"40"}}'
                ),
                "apps/shell/main/index.js": "export {};\n",
                "apps/shell/main/pyproject.toml": (
                    '[project]\nname="main-helper"\nversion="1"\n'
                ),
                "apps/shell/preload/go.mod": (
                    "module example.test/preload-helper\n"
                ),
                "apps/shell/renderer/native/build.gradle.kts": (
                    'plugins { kotlin("jvm") version "2.2.0" }\n'
                ),
            }
        )

        self.assertEqual(
            (("apps/shell", "xy-desktop"),), self._module_pairs(profile)
        )
        module = profile.modules[0]
        self.assertIn("language:python", module.stack_facts)
        self.assertIn("language:go", module.stack_facts)
        self.assertIn("language:kotlin", module.stack_facts)
        self.assertIn(
            "apps/shell/main/pyproject.toml", module.evidence_paths
        )
        self.assertIn("apps/shell/preload/go.mod", module.evidence_paths)
        self.assertIn(
            "apps/shell/renderer/native/build.gradle.kts",
            module.evidence_paths,
        )

    def test_tauri_owned_surfaces_absorb_generic_nested_manifests(self) -> None:
        profile = self._discover_files(
            {
                "tools/desktop/frontend/package.json": (
                    '{"dependencies":{"vue":"3"}}'
                ),
                "tools/desktop/frontend/tooling/pyproject.toml": (
                    '[project]\nname="frontend-tooling"\nversion="1"\n'
                ),
                "tools/desktop/src-tauri/tauri.conf.json": (
                    '{"productName":"Fixture","identifier":"example.fixture"}'
                ),
                "tools/desktop/src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                    '[dependencies]\ntauri="2"\n'
                ),
                "tools/desktop/src-tauri/helpers/go.mod": (
                    "module example.test/tauri-helper\n"
                ),
            }
        )

        self.assertEqual(
            (("tools/desktop", "xy-desktop"),), self._module_pairs(profile)
        )
        module = profile.modules[0]
        self.assertIn("framework:vue", module.stack_facts)
        self.assertIn("language:python", module.stack_facts)
        self.assertIn("language:go", module.stack_facts)
        self.assertIn(
            "tools/desktop/frontend/tooling/pyproject.toml",
            module.evidence_paths,
        )
        self.assertIn(
            "tools/desktop/src-tauri/helpers/go.mod", module.evidence_paths
        )

    def test_javascript_runtime_detection_ignores_peer_and_dev_only_frameworks(
        self,
    ) -> None:
        profile = self._discover_files(
            {
                "apps/browser/package.json": (
                    '{"dependencies":{"react":"19"}}'
                ),
                "services/api/package.json": (
                    '{"dependencies":{"fastify":"5"}}'
                ),
                "packages/react-library/package.json": (
                    '{"peerDependencies":{"react":"19"}}'
                ),
                "tools/server-test/package.json": (
                    '{"devDependencies":{"express":"5"}}'
                ),
            }
        )

        self.assertEqual(
            (
                ("apps/browser", "xy-web"),
                ("services/api", "xy-backend"),
            ),
            self._module_pairs(profile),
        )

    def test_classification_remains_deterministic_and_read_only(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-classification-ro-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        self._write_tree(
            root,
            {
                "apps/desktop/package.json": (
                    '{"main":"main.js","dependencies":{'
                    '"electron":"40","react":"19"}}'
                ),
                "apps/desktop/main.js": "export {};\n",
                "apps/desktop/renderer/package.json": (
                    '{"dependencies":{"vue":"3"}}'
                ),
                "services/api/package.json": (
                    '{"dependencies":{"express":"5"}}'
                ),
            },
        )
        before = ProjectDiscoveryContractTest._tree_snapshot(root)
        first = discover_project(root)
        middle = ProjectDiscoveryContractTest._tree_snapshot(root)
        second = discover_project(root)
        after = ProjectDiscoveryContractTest._tree_snapshot(root)

        self.assertEqual(first, second)
        self.assertEqual(before, middle)
        self.assertEqual(before, after)

    def test_electron_package_config_is_nonempty_and_owned_by_its_tool(self) -> None:
        cases = {
            "empty-forge-config": {
                "package.json": (
                    '{"devDependencies":{"electron":"40",'
                    '"@electron-forge/cli":"7"},"config":{"forge":{}}}'
                )
            },
            "forge-config-without-forge-tool": {
                "package.json": (
                    '{"devDependencies":{"electron":"40"},'
                    '"config":{"forge":{"packagerConfig":{}}}}'
                )
            },
            "empty-builder-config": {
                "package.json": (
                    '{"devDependencies":{"electron":"40",'
                    '"electron-builder":"26"},"build":{}}'
                )
            },
            "builder-config-without-builder-tool": {
                "package.json": (
                    '{"devDependencies":{"electron":"40"},'
                    '"build":{"appId":"example.desktop"}}'
                )
            },
        }
        for label, files in cases.items():
            with self.subTest(false_positive=label):
                profile = self._discover_files(files)
                self.assertNotIn("xy-desktop", profile.primary_roles)

    def test_tauri_dependency_must_be_a_direct_runtime_dependency(self) -> None:
        profile = self._discover_files(
            {
                "package.json": '{"dependencies":{"react":"19"}}',
                "src-tauri/tauri.conf.json": (
                    '{"productName":"Fixture","identifier":"example.fixture"}'
                ),
                "src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                    '[dev-dependencies]\ntauri="2"\n'
                ),
            }
        )
        self.assertNotIn("xy-desktop", profile.primary_roles)

    def test_xcode_product_type_text_without_a_native_target_is_not_an_app(self) -> None:
        profile = self._discover_files(
            {
                "Fixture.xcodeproj/project.pbxproj": (
                    "// !$*UTF8*$!\n"
                    "{\n"
                    "  objects = {\n"
                    "    C1 = {\n"
                    "      isa = XCBuildConfiguration;\n"
                    '      productType = "com.apple.product-type.application";\n'
                    "    };\n"
                    "  };\n"
                    "}\n"
                )
            }
        )
        self.assertNotIn("xy-apple", profile.primary_roles)

    def test_xcode_application_product_type_must_share_its_native_target_object(
        self,
    ) -> None:
        profile = self._discover_files(
            {
                "Fixture.xcodeproj/project.pbxproj": (
                    "// !$*UTF8*$!\n"
                    "{\n"
                    "  objects = {\n"
                    "    F1 = {\n"
                    "      isa = PBXNativeTarget;\n"
                    '      productType = "com.apple.product-type.framework";\n'
                    "    };\n"
                    "    C1 = {\n"
                    "      isa = XCBuildConfiguration;\n"
                    '      productType = "com.apple.product-type.application";\n'
                    "    };\n"
                    "  };\n"
                    "}\n"
                )
            }
        )
        self.assertNotIn("xy-apple", profile.primary_roles)

class ProjectVerificationCommandContractTest(unittest.TestCase):
    """Task 4: repository-native verification commands from direct evidence."""

    @staticmethod
    def _write_tree(root: Path, files: dict[str, str]) -> None:
        for relative, body in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    def _discover_files(self, files: dict[str, str]) -> ProjectProfile:
        temporary = tempfile.TemporaryDirectory(prefix="project-commands-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        self._write_tree(root, files)
        return discover_project(root)

    @staticmethod
    def _commands(
        profile: ProjectProfile, module_root: str
    ) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
        module = next(item for item in profile.modules if item.root == module_root)
        return tuple(
            (command.purpose, command.argv, command.evidence_paths)
            for command in module.verification_commands
        )

    def test_javascript_managers_expose_only_real_named_scripts(self) -> None:
        profile = self._discover_files(
            {
                "apps/npm/package.json": (
                    '{"dependencies":{"react":"19"},"scripts":'
                    '{"lint":"eslint .","test":"vitest","empty":"",'
                    '"test;danger":"echo no"}}'
                ),
                "apps/npm/package-lock.json": "{}",
                "apps/pnpm/package.json": (
                    '{"packageManager":"pnpm@10.0.0",'
                    '"dependencies":{"vue":"3"},'
                    '"scripts":{"typecheck":"vue-tsc","build":"vite build"}}'
                ),
                "apps/pnpm/pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
                "apps/yarn/package.json": (
                    '{"dependencies":{"svelte":"5"},'
                    '"scripts":{"check":"svelte-check","test:unit":"vitest"}}'
                ),
                "apps/yarn/yarn.lock": "# yarn lockfile v1\n",
                "apps/bun/package.json": (
                    '{"dependencies":{"preact":"10"},'
                    '"scripts":{"test":"bun test","build":"vite build"}}'
                ),
                "apps/bun/bun.lock": "lockfileVersion = 1\n",
            }
        )

        self.assertEqual(
            (
                (
                    "build",
                    ("bun", "run", "build"),
                    ("apps/bun/bun.lock", "apps/bun/package.json"),
                ),
                (
                    "test",
                    ("bun", "run", "test"),
                    ("apps/bun/bun.lock", "apps/bun/package.json"),
                ),
            ),
            self._commands(profile, "apps/bun"),
        )
        self.assertEqual(
            (
                (
                    "lint",
                    ("npm", "run", "lint"),
                    ("apps/npm/package-lock.json", "apps/npm/package.json"),
                ),
                (
                    "test",
                    ("npm", "run", "test"),
                    ("apps/npm/package-lock.json", "apps/npm/package.json"),
                ),
            ),
            self._commands(profile, "apps/npm"),
        )
        self.assertEqual(
            (
                (
                    "build",
                    ("pnpm", "run", "build"),
                    ("apps/pnpm/package.json", "apps/pnpm/pnpm-lock.yaml"),
                ),
                (
                    "typecheck",
                    ("pnpm", "run", "typecheck"),
                    ("apps/pnpm/package.json", "apps/pnpm/pnpm-lock.yaml"),
                ),
            ),
            self._commands(profile, "apps/pnpm"),
        )
        self.assertEqual(
            (
                (
                    "test",
                    ("yarn", "run", "test:unit"),
                    ("apps/yarn/package.json", "apps/yarn/yarn.lock"),
                ),
                (
                    "typecheck",
                    ("yarn", "run", "check"),
                    ("apps/yarn/package.json", "apps/yarn/yarn.lock"),
                ),
            ),
            self._commands(profile, "apps/yarn"),
        )
        all_argv = {command.argv for command in profile.verification_commands}
        self.assertNotIn(("npm", "run", "empty"), all_argv)
        self.assertNotIn(("npm", "run", "test;danger"), all_argv)
        self.assertNotIn(("npm", "run", "build"), all_argv)

    def test_electron_and_tauri_keep_commands_scoped_to_desktop_module(self) -> None:
        profile = self._discover_files(
            {
                "apps/electron/package.json": (
                    '{"main":"main.js","devDependencies":'
                    '{"electron":"40","@electron-forge/cli":"7",'
                    '"electron-builder":"26"},'
                    '"scripts":{"make":"electron-forge make",'
                    '"package":"electron-forge package",'
                    '"dist":"electron-builder"}}'
                ),
                "apps/electron/main.js": "export {};\n",
                "apps/electron/package-lock.json": "{}",
                "apps/electron/renderer/package.json": (
                    '{"dependencies":{"react":"19"},'
                    '"scripts":{"test":"vitest"}}'
                ),
                "apps/electron/renderer/pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
                "apps/tauri/package.json": (
                    '{"packageManager":"pnpm@10",'
                    '"dependencies":{"vue":"3","@tauri-apps/cli":"2"},'
                    '"scripts":{"tauri:build":"tauri build"}}'
                ),
                "apps/tauri/pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
                "apps/tauri/src-tauri/tauri.conf.json": (
                    '{"productName":"Fixture","identifier":"example.fixture"}'
                ),
                "apps/tauri/src-tauri/Cargo.toml": (
                    '[package]\nname="fixture"\nversion="0.1.0"\n'
                    '[dependencies]\ntauri="2"\n'
                ),
            }
        )

        electron = self._commands(profile, "apps/electron")
        self.assertIn(
            (
                "package",
                ("npm", "run", "make"),
                (
                    "apps/electron/package-lock.json",
                    "apps/electron/package.json",
                ),
            ),
            electron,
        )
        self.assertIn(
            (
                "package",
                ("npm", "run", "dist"),
                (
                    "apps/electron/package-lock.json",
                    "apps/electron/package.json",
                ),
            ),
            electron,
        )
        self.assertIn(
            (
                "test",
                ("pnpm", "--dir", "renderer", "run", "test"),
                (
                    "apps/electron/renderer/package.json",
                    "apps/electron/renderer/pnpm-lock.yaml",
                ),
            ),
            electron,
        )
        tauri = self._commands(profile, "apps/tauri")
        self.assertIn(
            (
                "package",
                ("pnpm", "run", "tauri:build"),
                ("apps/tauri/package.json", "apps/tauri/pnpm-lock.yaml"),
            ),
            tauri,
        )
        self.assertIn(
            (
                "test",
                (
                    "cargo",
                    "test",
                    "--manifest-path",
                    "src-tauri/Cargo.toml",
                ),
                ("apps/tauri/src-tauri/Cargo.toml",),
            ),
            tauri,
        )

    def test_wrappers_language_managers_and_native_build_systems(self) -> None:
        xcode_project = (
            "// !$*UTF8*$!\n"
            "{\n"
            "  objects = {\n"
            "    A1 = {\n"
            "      isa = PBXNativeTarget;\n"
            '      productType = "com.apple.product-type.application";\n'
            "    };\n"
            "  };\n"
            "}\n"
        )
        profile = self._discover_files(
            {
                "services/maven/pom.xml": (
                    "<project><modelVersion>4.0.0</modelVersion></project>"
                ),
                "services/maven/mvnw": "#!/bin/sh\n",
                "services/gradle/build.gradle.kts": (
                    'plugins { id("java") }\n'
                ),
                "services/gradle/gradlew": "#!/bin/sh\n",
                "apps/android/build.gradle.kts": (
                    'plugins { id("com.android.application") version "9.0.0" }\n'
                ),
                "apps/android/gradlew": "#!/bin/sh\n",
                "apps/android/src/main/AndroidManifest.xml": (
                    '<manifest package="example.fixture"/>'
                ),
                "services/uv/pyproject.toml": (
                    '[project]\nname="uv-service"\nversion="1"\n'
                    'dependencies=["pytest>=9"]\n'
                ),
                "services/uv/uv.lock": "version = 1\n",
                "services/poetry/pyproject.toml": (
                    '[tool.poetry]\nname="poetry-service"\nversion="1"\n'
                    '[tool.poetry.group.dev.dependencies]\npytest="^9"\n'
                ),
                "services/poetry/poetry.lock": "package = []\n",
                "services/rust/Cargo.toml": (
                    '[package]\nname="rust-service"\nversion="0.1.0"\n'
                ),
                "services/go/go.mod": "module example.test/service\n",
                "services/php/composer.json": (
                    '{"name":"example/service","require":{"php":"^8.4"},'
                    '"require-dev":{"phpunit/phpunit":"^12"}}'
                ),
                "services/php/phpunit.xml": "<phpunit/>",
                "services/dotnet/Service.csproj": (
                    '<Project Sdk="Microsoft.NET.Sdk"></Project>'
                ),
                "native/cmake/CMakeLists.txt": (
                    "cmake_minimum_required(VERSION 3.30)\nproject(fixture)\n"
                ),
                "native/cmake/CMakePresets.json": (
                    '{"version":6,"configurePresets":[{"name":"ci"}],'
                    '"buildPresets":[{"name":"ci"}],'
                    '"testPresets":[{"name":"ci"}]}'
                ),
                "native/meson/meson.build": (
                    "project('fixture', 'cpp')\n"
                    "unit = executable('unit', 'unit.cpp')\n"
                    "test('unit', unit)\n"
                ),
                "apps/apple/Fixture.xcodeproj/project.pbxproj": xcode_project,
                "apps/apple/Fixture.xcodeproj/xcshareddata/xcschemes/App.xcscheme": (
                    '<Scheme version="1.7"><BuildAction/></Scheme>'
                ),
            }
        )

        expected_argv = {
            "services/maven": {("./mvnw", "test"), ("./mvnw", "package")},
            "services/gradle": {("./gradlew", "test"), ("./gradlew", "build")},
            "apps/android": {
                ("./gradlew", "assembleDebug"),
                ("./gradlew", "testDebugUnitTest"),
            },
            "services/uv": {("uv", "run", "pytest")},
            "services/poetry": {("poetry", "run", "pytest")},
            "services/rust": {("cargo", "test"), ("cargo", "build")},
            "services/go": {("go", "test", "./..."), ("go", "build", "./...")},
            "services/php": {("vendor/bin/phpunit",)},
            "services/dotnet": {("dotnet", "build", "Service.csproj")},
            "native/cmake": {
                ("cmake", "--preset", "ci"),
                ("cmake", "--build", "--preset", "ci"),
                ("ctest", "--preset", "ci"),
            },
            "native/meson": {
                ("meson", "setup", "builddir"),
                ("meson", "test", "-C", "builddir"),
            },
            "apps/apple": {("xcodebuild", "-scheme", "App", "build")},
        }
        for module_root, expected in expected_argv.items():
            with self.subTest(module=module_root):
                commands = self._commands(profile, module_root)
                self.assertEqual(expected, {argv for _, argv, _ in commands})
                self.assertEqual(
                    tuple(sorted(commands, key=lambda item: (item[0], item[1], item[2]))),
                    commands,
                )

    def test_nearest_checked_in_ancestor_wrapper_wins_for_nested_modules(self) -> None:
        profile = self._discover_files(
            {
                "gradlew": "#!/bin/sh\n",
                "apps/android/build.gradle.kts": (
                    'plugins { id("com.android.application") version "9.0.0" }\n'
                ),
                "apps/android/src/main/AndroidManifest.xml": (
                    '<manifest package="example.fixture"/>'
                ),
                "mvnw": "#!/bin/sh\n",
                "services/api/pom.xml": (
                    "<project><modelVersion>4.0.0</modelVersion></project>"
                ),
                "services/local/pom.xml": (
                    "<project><modelVersion>4.0.0</modelVersion></project>"
                ),
                "services/local/mvnw": "#!/bin/sh\n",
            }
        )

        android = self._commands(profile, "apps/android")
        self.assertEqual(
            {
                ("../../gradlew", "assembleDebug"),
                ("../../gradlew", "testDebugUnitTest"),
            },
            {argv for _, argv, _ in android},
        )
        self.assertTrue(
            all("gradlew" in evidence for _, _, evidence in android)
        )

        api = self._commands(profile, "services/api")
        self.assertEqual(
            {("../../mvnw", "package"), ("../../mvnw", "test")},
            {argv for _, argv, _ in api},
        )
        self.assertTrue(all("mvnw" in evidence for _, _, evidence in api))

        local = self._commands(profile, "services/local")
        self.assertEqual(
            {("./mvnw", "package"), ("./mvnw", "test")},
            {argv for _, argv, _ in local},
        )
        self.assertTrue(
            all(
                "services/local/mvnw" in evidence and "mvnw" not in evidence
                for _, _, evidence in local
            )
        )

    def test_desktop_owned_nested_build_commands_use_owner_relative_paths(self) -> None:
        profile = self._discover_files(
            {
                "desktop/package.json": (
                    '{"main":"main.js","dependencies":{"electron":"40"}}'
                ),
                "desktop/main.js": "export {};\n",
                "desktop/mvnw": "#!/bin/sh\n",
                "desktop/gradlew": "#!/bin/sh\n",
                "desktop/renderer/java/pom.xml": (
                    "<project><modelVersion>4.0.0</modelVersion></project>"
                ),
                "desktop/renderer/kotlin/build.gradle.kts": (
                    'plugins { id("java") }\n'
                ),
            }
        )

        commands = self._commands(profile, "desktop")
        actual = {argv for _, argv, _ in commands}
        self.assertIn(
            ("./mvnw", "-f", "renderer/java/pom.xml", "test"),
            actual,
        )
        self.assertIn(
            ("./mvnw", "-f", "renderer/java/pom.xml", "package"),
            actual,
        )
        self.assertIn(
            ("./gradlew", "--project-dir", "renderer/kotlin", "test"),
            actual,
        )
        self.assertIn(
            ("./gradlew", "--project-dir", "renderer/kotlin", "build"),
            actual,
        )
        self.assertTrue(
            all(
                not argv[0].startswith("../")
                for _, argv, evidence in commands
                if "desktop/mvnw" in evidence or "desktop/gradlew" in evidence
            )
        )

    def test_global_fallbacks_need_manifest_evidence_and_discovery_stays_read_only(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-command-safety-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        self._write_tree(
            root,
            {
                "maven/pom.xml": (
                    "<project><modelVersion>4.0.0</modelVersion></project>"
                ),
                "gradle/build.gradle": "plugins { id 'java' }\n",
                "web/package.json": (
                    '{"dependencies":{"react":"19"},"scripts":{"lint":"x"}}'
                ),
                "python/pyproject.toml": (
                    '[project]\nname="docs-only"\nversion="1"\n'
                    'description="pytest is mentioned but not declared"\n'
                ),
                "python/uv.lock": "version = 1\n",
                "php/composer.json": (
                    '{"name":"example/docs","description":'
                    '"phpunit/phpunit is not installed","require":{"php":"^8.4"},'
                    '"scripts":{"test":""}}'
                ),
                "php/phpunit.xml": "<phpunit/>",
                "notes/mvnw": "not attached to a Maven module\n",
            },
        )
        before = ProjectDiscoveryContractTest._tree_snapshot(root)

        first = discover_project(root)
        second = discover_project(root)

        self.assertEqual(first, second)
        self.assertEqual(before, ProjectDiscoveryContractTest._tree_snapshot(root))
        self.assertEqual(
            {("mvn", "test"), ("mvn", "package")},
            {argv for _, argv, _ in self._commands(first, "maven")},
        )
        self.assertEqual(
            {("gradle", "test"), ("gradle", "build")},
            {argv for _, argv, _ in self._commands(first, "gradle")},
        )
        self.assertEqual(
            {("npm", "run", "lint")},
            {argv for _, argv, _ in self._commands(first, "web")},
        )
        self.assertEqual((), self._commands(first, "python"))
        self.assertEqual((), self._commands(first, "php"))
        self.assertEqual(
            len(first.verification_commands),
            len(set(first.verification_commands)),
        )
        self.assertFalse(any("notes/mvnw" in command.evidence_paths for command in first.verification_commands))


class ProjectDiscoveryContractTest(unittest.TestCase):
    maxDiff = None

    @staticmethod
    def _write_tree(root: Path, files: dict[str, str]) -> None:
        for relative, body in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    @staticmethod
    def _tree_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
        entries: list[tuple[object, ...]] = []
        for path in sorted((root, *root.rglob("*")), key=lambda item: item.as_posix()):
            info = path.lstat()
            relative = "." if path == root else path.relative_to(root).as_posix()
            kind = stat.S_IFMT(info.st_mode)
            payload: bytes | str | None = None
            if stat.S_ISREG(info.st_mode):
                payload = path.read_bytes()
            elif stat.S_ISLNK(info.st_mode):
                payload = os.readlink(path)
            entries.append(
                (
                    relative,
                    kind,
                    stat.S_IMODE(info.st_mode),
                    info.st_size,
                    info.st_mtime_ns,
                    payload,
                )
            )
        return tuple(entries)

    def _discover_files(self, files: dict[str, str]) -> ProjectProfile:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        self._write_tree(root, files)
        return discover_project(root)

    def test_table_driven_repository_manifests_produce_typed_profiles(self) -> None:
        cases = {
            "react": (
                {"package.json": '{"dependencies":{"react":"19.0.0"}}'},
                "xy-web",
                "framework:react",
            ),
            "vue": (
                {"package.json": '{"dependencies":{"vue":"3.0.0"}}'},
                "xy-web",
                "framework:vue",
            ),
            "angular": (
                {"package.json": '{"dependencies":{"@angular/core":"20.0.0"}}'},
                "xy-web",
                "framework:angular",
            ),
            "svelte": (
                {"package.json": '{"dependencies":{"svelte":"5.0.0"}}'},
                "xy-web",
                "framework:svelte",
            ),
            "electron": (
                {
                    "package.json": (
                        '{"main":"src/main.js","dependencies":'
                        '{"electron":"40.0.0","react":"19.0.0"}}'
                    ),
                    "src/main.js": "export {};\n",
                },
                "xy-desktop",
                "desktop:electron",
            ),
            "tauri": (
                {
                    "package.json": '{"dependencies":{"react":"19.0.0"}}',
                    "src-tauri/tauri.conf.json": '{"productName":"Fixture"}',
                    "src-tauri/Cargo.toml": (
                        '[package]\nname = "fixture"\nversion = "0.1.0"\n'
                        '[dependencies]\ntauri = "2"\n'
                    ),
                },
                "xy-desktop",
                "desktop:tauri",
            ),
            "python": (
                {"pyproject.toml": '[project]\nname = "fixture"\nversion = "0.1.0"\n'},
                "xy-backend",
                "language:python",
            ),
            "java": (
                {"pom.xml": '<project><modelVersion>4.0.0</modelVersion></project>'},
                "xy-backend",
                "language:java",
            ),
            "kotlin-server": (
                {
                    "build.gradle.kts": (
                        'plugins { kotlin("jvm") version "2.2.0" }\n'
                        'application { mainClass.set("example.ServerKt") }\n'
                    )
                },
                "xy-backend",
                "language:kotlin",
            ),
            "go": (
                {"go.mod": "module example.test/fixture\n\ngo 1.25\n"},
                "xy-backend",
                "language:go",
            ),
            "rust": (
                {"Cargo.toml": '[package]\nname = "fixture"\nversion = "0.1.0"\n'},
                "xy-backend",
                "language:rust",
            ),
            "php": (
                {"composer.json": '{"name":"example/fixture","require":{"php":"^8.4"}}'},
                "xy-backend",
                "language:php",
            ),
            "c-cpp": (
                {"CMakeLists.txt": "cmake_minimum_required(VERSION 3.30)\nproject(fixture)\n"},
                "xy-backend",
                "language:c-cpp",
            ),
            "csharp": (
                {"Fixture.csproj": '<Project Sdk="Microsoft.NET.Sdk"></Project>'},
                "xy-backend",
                "language:csharp",
            ),
            "apple": (
                {
                    "Fixture.xcodeproj/project.pbxproj": (
                        "// !$*UTF8*$!\n"
                        "{\n"
                        "\tobjects = {\n"
                        "\t\tA1 = {\n"
                        "\t\t\tisa = PBXNativeTarget;\n"
                        "\t\t\tproductType = "
                        '"com.apple.product-type.application";\n'
                        "\t\t};\n"
                        "\t};\n"
                        "}\n"
                    )
                },
                "xy-apple",
                "platform:apple",
            ),
            "android": (
                {
                    "build.gradle.kts": (
                        'plugins { id("com.android.application") version "9.0.0" }\n'
                    ),
                    "src/main/AndroidManifest.xml": '<manifest package="example.fixture"/>',
                },
                "xy-android",
                "platform:android",
            ),
        }

        for label, (files, expected_role, expected_fact) in cases.items():
            with self.subTest(stack=label):
                profile = self._discover_files(files)
                self.assertIsInstance(profile, ProjectProfile)
                self.assertEqual((".",), profile.module_roots)
                self.assertEqual((expected_role,), profile.primary_roles)
                self.assertIn(expected_fact, profile.detected_stack_facts)
                self.assertIsInstance(profile.verification_commands, tuple)
                self.assertTrue(
                    all(
                        isinstance(command, VerificationCommand)
                        for command in profile.verification_commands
                    )
                )
                expected_enabled = {expected_role, "xy-qa", "xy-uiux"}
                self.assertEqual(tuple(sorted(expected_enabled)), profile.enabled_roles)
                self.assertTrue(profile.evidence_paths)

    def test_monorepos_keep_multiple_same_role_and_mixed_modules(self) -> None:
        cases = {
            "multiple-web-and-backend-roots": (
                {
                    "apps/alpha/package.json": '{"dependencies":{"react":"19"}}',
                    "apps/beta/package.json": '{"dependencies":{"vue":"3"}}',
                    "services/api/pyproject.toml": '[project]\nname="api"\nversion="1"\n',
                    "services/jobs/go.mod": "module example.test/jobs\n",
                },
                (
                    ("apps/alpha", "xy-web"),
                    ("apps/beta", "xy-web"),
                    ("services/api", "xy-backend"),
                    ("services/jobs", "xy-backend"),
                ),
            ),
            "desktop-beside-browser-and-backend": (
                {
                    "apps/browser/package.json": '{"dependencies":{"svelte":"5"}}',
                    "apps/desktop/package.json": (
                        '{"main":"main.js","devDependencies":{"electron":"40"}}'
                    ),
                    "apps/desktop/main.js": "export {};\n",
                    "services/api/Cargo.toml": (
                        '[package]\nname="api"\nversion="0.1.0"\n'
                    ),
                },
                (
                    ("apps/browser", "xy-web"),
                    ("apps/desktop", "xy-desktop"),
                    ("services/api", "xy-backend"),
                ),
            ),
        }
        for label, (files, expected_modules) in cases.items():
            with self.subTest(layout=label):
                profile = self._discover_files(files)
                actual = tuple((module.root, module.primary_role) for module in profile.modules)
                self.assertEqual(expected_modules, actual)
                self.assertEqual(tuple(sorted(profile.modules, key=lambda item: item.root)), profile.modules)

    def test_profile_and_every_nested_collection_are_immutable(self) -> None:
        profile = self._discover_files(
            {"package.json": '{"dependencies":{"react":"19"}}'}
        )
        self.assertIsInstance(profile.modules, tuple)
        self.assertIsInstance(profile.modules[0].evidence_paths, tuple)
        self.assertIsInstance(profile.modules[0].stack_facts, tuple)
        self.assertIsInstance(profile.modules[0].verification_commands, tuple)
        self.assertIsInstance(profile.enabled_roles, tuple)
        self.assertIsInstance(profile.diagnostics, tuple)
        with self.assertRaises(FrozenInstanceError):
            profile.enabled_roles = ("xy-qa",)  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            profile.modules[0].root = "changed"  # type: ignore[misc]

        command = VerificationCommand(
            purpose="test",
            argv=("tool", "test"),
            evidence_paths=("tool.toml",),
        )
        self.assertEqual(("tool", "test"), command.argv)
        with self.assertRaises(FrozenInstanceError):
            command.purpose = "build"  # type: ignore[misc]

    def test_public_profile_types_validate_and_copy_nested_sequences(self) -> None:
        argv = ["tool", "test"]
        command_evidence = ["tool.toml"]
        command = VerificationCommand("test", argv, command_evidence)  # type: ignore[arg-type]
        argv.append("changed")
        command_evidence.append("changed.toml")
        self.assertEqual(("tool", "test"), command.argv)
        self.assertEqual(("tool.toml",), command.evidence_paths)

        evidence = ["package.json"]
        facts = ["framework:react"]
        commands = [command]
        module = ModuleProfile(  # type: ignore[arg-type]
            ".", "xy-web", evidence, facts, commands
        )
        evidence.append("changed.json")
        facts.append("changed:fact")
        commands.clear()
        self.assertEqual(("package.json",), module.evidence_paths)
        self.assertEqual(("framework:react",), module.stack_facts)
        self.assertEqual((command,), module.verification_commands)

        modules = [module]
        enabled = ["xy-qa", "xy-uiux", "xy-web"]
        diagnostics = ["observed"]
        profile = ProjectProfile(modules, enabled, diagnostics)  # type: ignore[arg-type]
        modules.clear()
        enabled.clear()
        diagnostics.clear()
        self.assertEqual((module,), profile.modules)
        self.assertEqual(("xy-qa", "xy-uiux", "xy-web"), profile.enabled_roles)
        self.assertEqual(("observed",), profile.diagnostics)

        override_items = [ModuleOverride("service", "xy-backend")]
        excluded_items = ["vendor"]
        overrides = DiscoveryOverrides(override_items, excluded_items)  # type: ignore[arg-type]
        override_items.clear()
        excluded_items.clear()
        self.assertEqual((ModuleOverride("service", "xy-backend"),), overrides.module_roles)
        self.assertEqual(("vendor",), overrides.exclude_roots)

        malformed = (
            lambda: VerificationCommand("test", "pytest", ()),
            lambda: VerificationCommand("test", ("pytest", 1), ()),
            lambda: VerificationCommand("", ("pytest",), ()),
            lambda: ModuleProfile(".", "xy-web", "package.json", (), ()),
            lambda: ModuleProfile(".", "unknown", (), (), ()),
            lambda: ModuleProfile(".", "xy-web", (), (1,), ()),
            lambda: ProjectProfile(("not-a-module",), ("xy-qa",), ()),
            lambda: ProjectProfile((), "xy-qa", ()),
            lambda: ProjectProfile((), ("unknown",), ()),
            lambda: ProjectProfile((), ("xy-qa",), (1,)),
            lambda: ProjectProfile((module,), ("xy-web", "xy-uiux"), ()),
            lambda: ProjectProfile((module,), ("xy-qa", "xy-uiux"), ()),
            lambda: ModuleOverride("../escape", "xy-backend"),
            lambda: DiscoveryOverrides(module_roles=("bad",)),
            lambda: DiscoveryOverrides(exclude_roots="vendor"),
            lambda: DiscoveryOverrides(
                module_roles=(
                    ModuleOverride("service", "xy-backend"),
                    ModuleOverride("service/.", "xy-backend"),
                )
            ),
            lambda: DiscoveryOverrides(exclude_roots=("vendor", "vendor/.")),
            lambda: DiscoveryOverrides(
                module_roles=(ModuleOverride("service", "xy-backend"),),
                exclude_roots=("service/generated",),
            ),
        )
        for build in malformed:
            with self.subTest(factory=build):
                with self.assertRaises((TypeError, ValueError)):
                    build()

    def test_discovery_is_deterministic_and_does_not_write_the_fixture(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-readonly-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        self._write_tree(
            root,
            {
                "zeta/go.mod": "module example.test/zeta\n",
                "alpha/package.json": '{"dependencies":{"react":"19"}}',
                "notes/readme.txt": "not a module\n",
            },
        )
        before = self._tree_snapshot(root)

        first = discover_project(root)
        second = discover_project(root)

        self.assertEqual(first, second)
        self.assertEqual(tuple(sorted(first.module_roots)), first.module_roots)
        self.assertEqual(before, self._tree_snapshot(root))
        self.assertFalse(any(path.name == "__pycache__" for path in root.rglob("*")))

    def test_unknown_and_ignored_trees_are_not_assigned_or_parsed(self) -> None:
        ignored = (
            "agent_workflow",
            ".git",
            ".hg",
            ".svn",
            "node_modules",
            "vendor",
            ".venv",
            "venv",
            "build",
            "dist",
            "out",
            "target",
            "coverage",
            ".idea",
            ".vscode",
            ".gradle",
            "DerivedData",
            ".mypy_cache",
            ".pytest_cache",
            "__pycache__",
        )
        files = {
            f"{directory}/package.json": "{malformed ignored manifest"
            for directory in ignored
        }
        files["ordinary/source/main.py"] = "print('no manifest')\n"
        profile = self._discover_files(files)
        self.assertEqual((), profile.modules)
        self.assertEqual(("xy-qa", "xy-uiux"), profile.enabled_roles)
        self.assertEqual(("no implementation modules detected",), profile.diagnostics)

    def test_root_and_override_paths_fail_closed(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-paths-")
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)
        root = parent / "project"
        root.mkdir()
        (root / "service").mkdir()
        (root / "alias").symlink_to(root / "service", target_is_directory=True)
        root_alias = parent / "project-alias"
        root_alias.symlink_to(root, target_is_directory=True)

        with self.assertRaisesRegex(DiscoveryError, "project root.*symlink"):
            discover_project(root_alias)

        invalid_override_builders = (
            lambda: DiscoveryOverrides(
                module_roles=(ModuleOverride("../escape", "xy-backend"),)
            ),
            lambda: DiscoveryOverrides(
                module_roles=(ModuleOverride(str(root / "service"), "xy-backend"),)
            ),
            lambda: DiscoveryOverrides(exclude_roots=("../escape",)),
        )
        for build_override in invalid_override_builders:
            with self.subTest(build_override=build_override):
                with self.assertRaises(DiscoveryError):
                    build_override()

        unsafe_overrides = (
            DiscoveryOverrides(
                module_roles=(ModuleOverride("alias", "xy-backend"),)
            ),
        )
        for override in unsafe_overrides:
            with self.subTest(override=override):
                with self.assertRaises(DiscoveryError):
                    discover_project(root, overrides=override)

    def test_duplicate_and_conflicting_explicit_overrides_fail_closed(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-overrides-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        (root / "service").mkdir(parents=True)

        with self.assertRaisesRegex(ValueError, "override roots must be unique"):
            DiscoveryOverrides(
                module_roles=(
                    ModuleOverride("service", "xy-backend"),
                    ModuleOverride("service/.", "xy-backend"),
                )
            )

        with self.assertRaisesRegex(ValueError, "override roots must be unique"):
            DiscoveryOverrides(
                module_roles=(
                    ModuleOverride("service", "xy-backend"),
                    ModuleOverride("service", "xy-web"),
                )
            )

        with self.assertRaisesRegex(ValueError, "both assigned and excluded"):
            DiscoveryOverrides(
                module_roles=(ModuleOverride("service", "xy-backend"),),
                exclude_roots=("service",),
            )

    def test_candidate_symlinks_special_files_and_malformed_manifests_fail_closed(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-unsafe-")
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)

        symlink_root = parent / "symlink-project"
        symlink_root.mkdir()
        outside = parent / "outside.json"
        outside.write_text('{"dependencies":{"react":"19"}}', encoding="utf-8")
        (symlink_root / "package.json").symlink_to(outside)
        with self.assertRaisesRegex(DiscoveryError, "candidate.*symlink"):
            discover_project(symlink_root)

        special_root = parent / "special-project"
        special_root.mkdir()
        os.mkfifo(special_root / "package.json")
        with self.assertRaisesRegex(DiscoveryError, "candidate.*regular file"):
            discover_project(special_root)

        malformed_cases = {
            "package.json": "{not json",
            "pyproject.toml": "[project\nname='broken'",
            "pom.xml": "<project>",
            "Broken.csproj": "<Project>",
        }
        for index, (name, body) in enumerate(malformed_cases.items()):
            malformed_root = parent / f"malformed-{index}"
            malformed_root.mkdir()
            (malformed_root / name).write_text(body, encoding="utf-8")
            with self.subTest(manifest=name):
                with self.assertRaisesRegex(DiscoveryError, "malformed manifest"):
                    discover_project(malformed_root)

    def test_plain_manifest_garbage_fails_closed(self) -> None:
        malformed_cases = (
            ("go-prose", "go.mod", "this is not a module declaration\n"),
            ("gradle-prose", "build.gradle", "ordinary prose without Gradle structure\n"),
            ("gradle-empty-plugins", "build.gradle", "plugins { }\n"),
            (
                "gradle-kts-prose",
                "build.gradle.kts",
                "ordinary prose without Gradle structure\n",
            ),
            ("cmake-prose", "CMakeLists.txt", "ordinary prose without CMake commands\n"),
            (
                "cmake-version-only",
                "CMakeLists.txt",
                "cmake_minimum_required(VERSION 3.30)\n",
            ),
            ("meson-prose", "meson.build", "ordinary prose without a Meson project\n"),
            ("meson-empty-project", "meson.build", "project()\n"),
            (
                "pbx-header-only",
                "Fixture.xcodeproj/project.pbxproj",
                "// !$*UTF8*$!\n",
            ),
        )
        for label, name, body in malformed_cases:
            with self.subTest(manifest=label):
                temporary = tempfile.TemporaryDirectory(
                    prefix="project-discovery-plain-malformed-"
                )
                self.addCleanup(temporary.cleanup)
                root = Path(temporary.name) / "project"
                root.mkdir()
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
                with self.assertRaisesRegex(DiscoveryError, "malformed manifest"):
                    discover_project(root)

    def test_xml_manifests_reject_doctype_and_entity_before_xml_parsing(self) -> None:
        cases = {
            "pom.xml": (
                '<!DOCTYPE project [<!ENTITY payload "expanded">]>'
                "<project>&payload;</project>"
            ),
            "src/main/AndroidManifest.xml": (
                '<! doctype manifest [<! entity payload "expanded">]>'
                "<manifest>&payload;</manifest>"
            ),
            "Fixture.csproj": (
                '<!DoCtYpE Project [<!EnTiTy payload "expanded">]>'
                "<Project>&payload;</Project>"
            ),
        }
        for name, body in cases.items():
            with self.subTest(manifest=name):
                temporary = tempfile.TemporaryDirectory(
                    prefix="project-discovery-xml-entity-"
                )
                self.addCleanup(temporary.cleanup)
                root = Path(temporary.name) / "project"
                root.mkdir()
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
                with self.assertRaisesRegex(
                    DiscoveryError, "DOCTYPE|ENTITY|entity"
                ):
                    discover_project(root)

    def test_relevant_manifest_size_is_bounded(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-bounded-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        (root / "package.json").write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaisesRegex(DiscoveryError, "size limit"):
            discover_project(root)

    def test_scan_depth_is_bounded_and_directory_symlinks_are_not_followed(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-depth-")
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)

        linked_root = parent / "linked-project"
        linked_root.mkdir()
        outside = parent / "outside"
        outside.mkdir()
        (outside / "package.json").write_text("{malformed", encoding="utf-8")
        (linked_root / "external").symlink_to(outside, target_is_directory=True)
        self.assertEqual((), discover_project(linked_root).modules)

        deep_root = parent / "deep-project"
        deep_root.mkdir()
        cursor = deep_root
        for index in range(26):
            cursor /= f"level-{index:02d}"
            cursor.mkdir()
        with self.assertRaisesRegex(DiscoveryError, "depth limit"):
            discover_project(deep_root)

    def test_directory_entry_limit_stops_at_limit_plus_one_before_processing(self) -> None:
        class CountingEntries:
            def __init__(self, count: int) -> None:
                self.count = count
                self.yielded = 0

            def __enter__(self) -> CountingEntries:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def __iter__(self) -> CountingEntries:
                return self

            def __next__(self) -> object:
                if self.yielded >= self.count:
                    raise StopIteration
                name = f"entry-{self.yielded:02d}"
                self.yielded += 1
                return type("Entry", (), {"name": name})()

        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-entries-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        entries = CountingEntries(count=10)
        # Python 3.12 的 Path.lstat 经由 os.stat，而较新版本可直接用 os.lstat。
        # 固定根目录元信息，只统计目录条目的 stat，避免 mock 截获根目录读取。
        root_info = root.lstat()
        with (
            mock.patch.object(project_discovery, "MAX_SCAN_ENTRIES", 3),
            mock.patch.object(project_discovery.os, "scandir", return_value=entries),
            mock.patch.object(project_discovery.os, "stat") as stat_call,
            mock.patch.object(Path, "lstat", return_value=root_info),
        ):
            with self.assertRaisesRegex(
                DiscoveryError,
                r"entry limit 3.*directory \."
            ):
                discover_project(root)

        self.assertEqual(4, entries.yielded)
        stat_call.assert_not_called()

    def test_candidate_count_and_cumulative_byte_budgets_stop_before_read(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-budget-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        self._write_tree(
            root,
            {
                "a/package.json": '{"dependencies":{"react":"19"}}',
                "b/package.json": '{"dependencies":{"vue":"3"}}',
            },
        )
        real_read = project_discovery._read_regular_at
        with (
            mock.patch.object(project_discovery, "MAX_CANDIDATE_MANIFESTS", 1),
            mock.patch.object(
                project_discovery, "_read_regular_at", wraps=real_read
            ) as read_call,
        ):
            with self.assertRaisesRegex(
                DiscoveryError, r"manifest count limit 1.*b/package\.json"
            ):
                discover_project(root)
        self.assertEqual(1, read_call.call_count)

        first_size = (root / "a/package.json").stat().st_size
        with (
            mock.patch.object(
                project_discovery, "MAX_CANDIDATE_BYTES", first_size
            ),
            mock.patch.object(
                project_discovery, "_read_regular_at", wraps=real_read
            ) as read_call,
        ):
            with self.assertRaisesRegex(
                DiscoveryError,
                rf"manifest byte limit {first_size}.*b/package\.json",
            ):
                discover_project(root)
        self.assertEqual(1, read_call.call_count)

    def test_override_and_exclusion_limits_and_ancestor_exclusion(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-override-limit-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        self._write_tree(
            root,
            {
                "assigned-a/source.txt": "a\n",
                "assigned-b/source.txt": "b\n",
                "ignored/nested/package.json": "{malformed ignored manifest",
                "other/package.json": '{"dependencies":{"react":"19"}}',
            },
        )
        with mock.patch.object(project_discovery, "MAX_MODULE_OVERRIDES", 1):
            with self.assertRaisesRegex(DiscoveryError, "module override limit 1"):
                discover_project(
                    root,
                    DiscoveryOverrides(
                        module_roles=(
                            ModuleOverride("assigned-a", "xy-backend"),
                            ModuleOverride("assigned-b", "xy-backend"),
                        )
                    ),
                )

        with mock.patch.object(project_discovery, "MAX_EXCLUDED_ROOTS", 1):
            with self.assertRaisesRegex(DiscoveryError, "excluded root limit 1"):
                discover_project(
                    root,
                    DiscoveryOverrides(
                        exclude_roots=("ignored", "assigned-a")
                    ),
                )

        profile = discover_project(
            root, DiscoveryOverrides(exclude_roots=("ignored",))
        )
        self.assertEqual(("other",), profile.module_roots)

        with self.assertRaisesRegex(ValueError, "both assigned and excluded"):
            DiscoveryOverrides(
                module_roles=(ModuleOverride("ignored", "xy-backend"),),
                exclude_roots=("ignored/nested",),
            )

    def test_missing_no_follow_capability_rejects_before_open_or_scan(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-capability-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        with (
            mock.patch.object(project_discovery, "_O_NOFOLLOW", None),
            mock.patch.object(project_discovery.os, "open") as open_call,
            mock.patch.object(project_discovery.os, "scandir") as scandir_call,
        ):
            with self.assertRaisesRegex(DiscoveryError, "O_NOFOLLOW"):
                discover_project(root)

        open_call.assert_not_called()
        scandir_call.assert_not_called()

    def test_gradle_lexing_ignores_comments_and_strings_but_requires_real_dsl(self) -> None:
        valid = {
            "plugin-with-string-brace": (
                'plugins { id("application") }\nprintln("{")\n'
            ),
            "comment-braces": (
                "// unmatched } ignored\n"
                "/* unmatched { ignored */\n"
                "dependencies { implementation(project(\":core\")) }\n"
            ),
            "triple-string-braces": (
                'dependencies {\n  val sample = """{ }"""\n}\n'
            ),
            "apply-plugin": "apply plugin: 'java'\n",
            "include-build": 'includeBuild("build-logic")\n',
            "groovy-include": "include ':app'\n",
            "android-block": 'android { namespace = "example.app" }\n',
            "plugin-alias": "plugins { alias(libs.plugins.kotlin.jvm) }\n",
            "groovy-slashy-string": (
                'def pattern = /plugins { id("fake") }/\n'
                'dependencies { implementation("real") }\n'
            ),
            "groovy-dollar-slashy-string": (
                'def pattern = $/plugins { id("fake") }/$\n'
                'dependencies { implementation("real") }\n'
            ),
            "groovy-division-and-escaped-slashy": (
                'dependencies { implementation("real") }\n'
                'val ratio = 1/2\n'
                'def pattern = /a\\/b{2}/\n'
            ),
        }
        for label, body in valid.items():
            with self.subTest(valid=label):
                profile = self._discover_files({"build.gradle.kts": body})
                self.assertEqual(("xy-backend",), profile.primary_roles)

        malicious = {
            "dsl-only-in-comment": "// plugins { id(\"java\") }\n",
            "dsl-only-in-string": 'println("plugins { id(java) }")\n',
            "unbalanced-real-brace": "dependencies { implementation('x')\n",
            "unterminated-comment": "dependencies { } /* never closed",
            "unterminated-string": 'dependencies { println("never closed) }',
            "nested-dsl-only": "custom { dependencies { implementation('x') } }\n",
            "dsl-only-in-slashy-string": 'def pattern = /plugins { id("fake") }/\n',
            "dsl-only-in-dollar-slashy-string": 'def pattern = $/plugins { id("fake") }/$\n',
        }
        for label, body in malicious.items():
            with self.subTest(malicious=label):
                with self.assertRaisesRegex(DiscoveryError, "malformed manifest"):
                    self._discover_files({"build.gradle": body})

    @staticmethod
    def _assert_descriptors_closed(descriptors: list[int]) -> None:
        for descriptor in descriptors:
            with unittest.TestCase().assertRaises(OSError):
                os.fstat(descriptor)

    def test_root_descriptor_errors_and_identity_races_fail_closed_without_leaks(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-root-fd-")
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)
        root = parent / "project"
        other = parent / "other"
        root.mkdir()
        other.mkdir()
        real_open = os.open
        real_fstat = os.fstat

        opened: list[int] = []

        def tracking_open(*args: object, **kwargs: object) -> int:
            descriptor = real_open(*args, **kwargs)  # type: ignore[arg-type]
            opened.append(descriptor)
            return descriptor

        with (
            mock.patch.object(project_discovery.os, "open", side_effect=tracking_open),
            mock.patch.object(
                project_discovery.os,
                "fstat",
                side_effect=OSError("root fstat failed"),
            ),
        ):
            with self.assertRaisesRegex(DiscoveryError, "project root.*fstat failed"):
                discover_project(root)
        self.assertEqual(1, len(opened))
        self._assert_descriptors_closed(opened)

        opened.clear()
        with (
            mock.patch.object(project_discovery.os, "open", side_effect=tracking_open),
            mock.patch.object(
                project_discovery.os, "fstat", return_value=other.lstat()
            ),
        ):
            with self.assertRaisesRegex(DiscoveryError, "project root.*changed"):
                discover_project(root)
        self.assertEqual(1, len(opened))
        self._assert_descriptors_closed(opened)
        self.assertTrue(callable(real_fstat))

    def test_manifest_identity_and_io_errors_are_wrapped_and_close_fds(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-manifest-fd-")
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)
        root = parent / "project"
        root.mkdir()
        manifest = root / "package.json"
        manifest.write_text('{"dependencies":{"react":"19"}}', encoding="utf-8")
        replacement = parent / "replacement.json"
        replacement.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
        real_open = os.open
        real_fstat = os.fstat

        def run_with_fstat(side_effect: object, pattern: str) -> None:
            opened: list[int] = []

            def tracking_open(*args: object, **kwargs: object) -> int:
                descriptor = real_open(*args, **kwargs)  # type: ignore[arg-type]
                opened.append(descriptor)
                return descriptor

            with (
                mock.patch.object(
                    project_discovery.os, "open", side_effect=tracking_open
                ),
                mock.patch.object(
                    project_discovery.os, "fstat", side_effect=side_effect
                ),
            ):
                with self.assertRaisesRegex(DiscoveryError, pattern):
                    discover_project(root)
            self.assertGreaterEqual(len(opened), 2)
            self._assert_descriptors_closed(opened)

        fstat_calls = 0

        def mismatched_fstat(descriptor: int) -> os.stat_result:
            nonlocal fstat_calls
            fstat_calls += 1
            if fstat_calls == 1:
                return real_fstat(descriptor)
            return replacement.lstat()

        run_with_fstat(mismatched_fstat, "package.json.*identity")

        fstat_calls = 0

        def failing_fstat(descriptor: int) -> os.stat_result:
            nonlocal fstat_calls
            fstat_calls += 1
            if fstat_calls == 1:
                return real_fstat(descriptor)
            raise OSError("manifest fstat failed")

        run_with_fstat(failing_fstat, "package.json.*fstat failed")

        opened: list[int] = []

        def tracking_open(*args: object, **kwargs: object) -> int:
            descriptor = real_open(*args, **kwargs)  # type: ignore[arg-type]
            opened.append(descriptor)
            return descriptor

        with (
            mock.patch.object(project_discovery.os, "open", side_effect=tracking_open),
            mock.patch.object(
                project_discovery.os,
                "read",
                side_effect=OSError("manifest read failed"),
            ),
        ):
            with self.assertRaisesRegex(
                DiscoveryError, "package.json.*read failed"
            ):
                discover_project(root)
        self.assertGreaterEqual(len(opened), 2)
        self._assert_descriptors_closed(opened)

    def test_child_directory_identity_and_fstat_errors_fail_closed(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-discovery-child-fd-")
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)
        root = parent / "project"
        root.mkdir()
        (root / "nested").mkdir()
        other = parent / "other"
        other.mkdir()
        real_open = os.open
        real_fstat = os.fstat

        def run_with_fstat(side_effect: object, pattern: str) -> None:
            opened: list[int] = []

            def tracking_open(*args: object, **kwargs: object) -> int:
                descriptor = real_open(*args, **kwargs)  # type: ignore[arg-type]
                opened.append(descriptor)
                return descriptor

            with (
                mock.patch.object(
                    project_discovery.os, "open", side_effect=tracking_open
                ),
                mock.patch.object(
                    project_discovery.os, "fstat", side_effect=side_effect
                ),
            ):
                with self.assertRaisesRegex(DiscoveryError, pattern):
                    discover_project(root)
            self.assertEqual(2, len(opened))
            self._assert_descriptors_closed(opened)

        fstat_calls = 0

        def mismatched_fstat(descriptor: int) -> os.stat_result:
            nonlocal fstat_calls
            fstat_calls += 1
            if fstat_calls == 1:
                return real_fstat(descriptor)
            return other.lstat()

        run_with_fstat(mismatched_fstat, r"nested.*identity")

        fstat_calls = 0

        def failing_fstat(descriptor: int) -> os.stat_result:
            nonlocal fstat_calls
            fstat_calls += 1
            if fstat_calls == 1:
                return real_fstat(descriptor)
            raise OSError("child directory fstat failed")

        run_with_fstat(failing_fstat, r"nested.*fstat failed")

    def test_deep_json_recursion_is_bounded_and_wrapped(self) -> None:
        depth = 300
        body = '{"nested":' + ("[" * depth) + "0" + ("]" * depth) + "}"
        with self.assertRaisesRegex(
            DiscoveryError, r"malformed manifest package\.json.*JSON.*depth"
        ):
            self._discover_files({"package.json": body})

    def test_json_depth_bound_ignores_brackets_inside_strings(self) -> None:
        body = '{"description":"' + ("[{" * 300) + '"}'
        profile = self._discover_files({"package.json": body})
        self.assertEqual((), profile.modules)

    def test_xml_comments_and_cdata_may_contain_forbidden_words(self) -> None:
        valid = {
            "pom.xml": (
                "<project><!-- DOCTYPE ENTITY -->"
                "<description><![CDATA[ <!DOCTYPE ENTITY > ]]></description>"
                "</project>"
            ),
            "Fixture.csproj": (
                "<Project><!-- ENTITY -->"
                "<PropertyGroup><![CDATA[ <!DOCTYPE ENTITY > ]]></PropertyGroup>"
                "</Project>"
            ),
        }
        for name, body in valid.items():
            with self.subTest(valid=name):
                profile = self._discover_files({name: body})
                self.assertEqual(("xy-backend",), profile.primary_roles)

        malicious = {
            "pom.xml": "<! doctype project><project />",
            "Fixture.csproj": "< ! ENTITY payload><Project />",
        }
        for name, body in malicious.items():
            with self.subTest(malicious=name):
                with self.assertRaisesRegex(DiscoveryError, r"DOCTYPE|ENTITY|entity"):
                    self._discover_files({name: body})


class UnifiedSetupContractTest(UnifiedHostFixture, unittest.TestCase):
    def make_docs_profile_fixture(
        self, *, ui_enabled: bool
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary, project, pack = self.make_fixture()
        if ui_enabled:
            (project / "package.json").write_text(
                '{"dependencies":{"react":"19.0.0"}}\n', encoding="utf-8"
            )
        else:
            (project / "go.mod").write_text(
                "module example.invalid/project\n\ngo 1.24\n", encoding="utf-8"
            )
        return temporary, project, pack

    @staticmethod
    def docs_inventory(project: Path) -> tuple[set[Path], set[Path]]:
        docs = project / "docs"
        files = {
            path.relative_to(project)
            for path in docs.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        directories = {
            path.relative_to(project) for path in docs.rglob("*") if path.is_dir()
        }
        if docs.is_dir():
            directories.add(Path("docs"))
        return files, directories

    def run_antigravity_applier(
        self, project: Path, pack: Path
    ) -> subprocess.CompletedProcess[str]:
        staging = project / "antigravity-test-staging"
        (staging / "agents").mkdir(parents=True)
        shutil.copytree(pack / "platforms/shared/skills", staging / "skills")
        renderer = pack / "lib/render_antigravity_agent.py"
        role_result = subprocess.run(
            [sys.executable, str(renderer), "--roles", str(pack)],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(
            role_result.returncode, 0, role_result.stdout + role_result.stderr
        )
        for role in role_result.stdout.splitlines():
            rendered = subprocess.run(
                [sys.executable, str(renderer), str(pack), role],
                cwd=project,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(
                rendered.returncode, 0, rendered.stdout + rendered.stderr
            )
            (staging / "agents" / f"{role}.md").write_text(
                rendered.stdout, encoding="utf-8"
            )
        product = (pack / "platforms/shared/AGENTS.product.tpl").read_text(
            encoding="utf-8"
        )
        anti = (pack / "platforms/antigravity/AGENTS.antigravity.tpl").read_text(
            encoding="utf-8"
        )
        (staging / "AGENTS.product.block").write_text(
            "<!-- pack:product-begin -->\n"
            + product.rstrip("\n")
            + "\n<!-- pack:product-end -->\n",
            encoding="utf-8",
        )
        (staging / "AGENTS.antigravity.block").write_text(
            "<!-- pack:antigravity-begin -->\n"
            + anti.rstrip("\n")
            + "\n<!-- pack:antigravity-end -->\n",
            encoding="utf-8",
        )
        return subprocess.run(
            [
                sys.executable,
                str(pack / "lib/apply_antigravity_setup.py"),
                "apply",
                str(pack),
                str(project),
                str(staging),
            ],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )

    def test_active_runtime_instruction_sources_are_english(self) -> None:
        roots = (
            PACK / "product/WORKFLOW.md",
            PACK / "product/AGENT_SCHEMA.md",
            PACK / "product/GLOBAL_CONSTRAINTS.md",
        )
        files = list(roots)
        # 按需安装/诊断说明面向中文维护者，不是预载的角色/Skill 编排契约。
        # 仅排除这两份明确的操作文档，仍检查所有实际运行时入口和规则正文。
        operator_docs = {PACK / "platforms/shared/HOOKS.md", PACK / "platforms/claude/hooks/README.md"}
        for directory in (
            PACK / "roles",
            PACK / "platforms/shared",
            PACK / "platforms/codex",
            PACK / "platforms/claude",
            PACK / "platforms/antigravity",
        ):
            # 项目文档模板是交给中文项目维护者填写的内容，不属于宿主指令源；
            # 宿主运行时仍单独保持英文，避免把文档语言限制误施加到工程规范。
            files.extend(
                path
                for path in directory.rglob("*")
                if path.is_file() and path.suffix in {".md", ".tpl"} and path not in operator_docs
            )
        cjk = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
        findings = []
        for path in sorted(set(files)):
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if cjk.search(line):
                    findings.append(f"{path.relative_to(PACK)}:{line_number}: {line}")
        self.assertEqual([], findings)

    def test_shared_pm_bootstrap_keeps_detailed_procedures_in_skills(self) -> None:
        body = (PACK / "platforms/shared/AGENTS.product.tpl").read_text(
            encoding="utf-8"
        )
        # 启动入口只保留路由和关键边界；详细执行步骤由按需 Skill 承载。
        for skill_only_heading in (
            "## Required checks",
            "## Execution Workflow",
            "## Browser and artifact boundary",
        ):
            self.assertNotIn(skill_only_heading, body)
        self.assertNotIn("{{SCOPE_TABLE}}", body)

    def test_generated_machine_instructions_are_english(self) -> None:
        temporary, project, _ = self.install_all()
        self.addCleanup(temporary.cleanup)
        candidates = [project / "AGENTS.md", project / "CLAUDE.md"]
        self.assertEqual((project / "CLAUDE.md").read_bytes(), b"@AGENTS.md\n")
        for directory in (
            project / ".agents/agents",
            project / ".agents/skills",
            project / ".claude/agents",
            project / ".claude/skills",
            project / ".codex/agents",
        ):
            if directory.is_dir():
                candidates.extend(path for path in directory.rglob("*") if path.is_file())
        cjk = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
        findings = []
        for path in candidates:
            try:
                body = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if cjk.search(body):
                findings.append(str(path.relative_to(project)))
        self.assertEqual([], sorted(findings))

    def test_all_hosts_generate_core_skills_from_one_shared_source(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        result = self.run_script(project, "setup_all.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        names = tuple(
            line.strip()
            for line in (pack / "platforms/shared/core-skills.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        self.assertEqual(7, len(names))
        for name in names:
            with self.subTest(skill=name):
                source = (pack / "platforms/shared/skills" / name / "SKILL.md").read_bytes()
                self.assertEqual(
                    source,
                    (project / ".agents/skills" / name / "SKILL.md").read_bytes(),
                )
                self.assertEqual(
                    source,
                    (project / ".claude/skills" / name / "SKILL.md").read_bytes(),
                )
                self.assertFalse(
                    (pack / "platforms/claude/skills" / name / "SKILL.md").exists(),
                    f"duplicate Claude core Skill source: {name}",
                )
        # 新的按需生命周期说明必须完整安装到两种 Skill 目录；Codex/Antigravity
        # 共享 .agents，Claude 使用 .claude，不能只同步 SKILL.md 而遗漏引用内容。
        for reference in ("design-standards.md", "plan-lifecycle.md"):
            lifecycle = Path("xy-workflow/references") / reference
            original = (pack / "platforms/shared/skills" / lifecycle).read_bytes()
            for skill_root in (".agents/skills", ".claude/skills"):
                self.assertEqual(original, (project / skill_root / lifecycle).read_bytes())

    def test_generated_hosts_keep_internal_records_out_of_user_feedback(self) -> None:
        """安装后三宿主继续共享内部结构，但根级 PM 入口必须禁止原样展示。"""

        temporary, project, _ = self.install_all()
        self.addCleanup(temporary.cleanup)

        for relative in (
            ".agents/skills/xy-workflow/SKILL.md",
            ".claude/skills/xy-workflow/SKILL.md",
        ):
            # 展开实际安装的显式引用，既检查入口的反馈边界，也检查内部 DAG 未丢失。
            body = read_contract(project / relative)
            self.assertIn(
                "Internal orchestration records are not user-facing output.",
                body,
            )
            self.assertIn(
                "Never paste raw workflow YAML or DAG JSON into user messages.",
                body,
            )
            self.assertIn("task_graph_cli.py validate", body)

        for relative in ("AGENTS.md",):
            body = (project / relative).read_text(encoding="utf-8")
            self.assertIn(
                "Internal orchestration records are not user-facing output.",
                body,
            )
            self.assertIn(
                "Never paste raw workflow YAML or DAG JSON into user messages.",
                body,
            )

    def test_every_install_order_keeps_all_hosts_checkable(self) -> None:
        for order in itertools.permutations(HOSTS):
            with self.subTest(order=order):
                temporary, project, _ = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                for host in order:
                    result = self.run_script(project, f"setup_{host}.sh")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for host in HOSTS:
                    check = self.run_script(project, f"setup_{host}.sh", "--check")
                    self.assertEqual(
                        check.returncode,
                        0,
                        f"order={order}, host={host}\n{check.stdout}{check.stderr}",
                    )

    def test_setup_all_is_repeatable_and_all_hosts_remain_checkable(self) -> None:
        temporary, project, _ = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        for attempt in ("first", "second"):
            with self.subTest(attempt=attempt):
                result = self.run_script(project, "setup_all.sh")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.run_script(project, "setup_all.sh", "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_antigravity_keeps_shared_product_block_byte_stable(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        for host in ("codex", "antigravity"):
            result = self.run_script(project, f"setup_{host}.sh")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        root = (project / "AGENTS.md").read_text(encoding="utf-8")
        begin = "<!-- pack:product-begin -->\n"
        end = "\n<!-- pack:product-end -->"
        managed = root.split(begin, 1)[1].split(end, 1)[0]
        source = (pack / "platforms/shared/AGENTS.product.tpl").read_text(
            encoding="utf-8"
        ).rstrip("\n")
        self.assertEqual(source, managed)

    def test_setup_entrypoints_reject_unknown_arguments_before_writes(self) -> None:
        scripts = tuple(f"setup_{host}.sh" for host in HOSTS) + ("setup_all.sh",)
        for script in scripts:
            with self.subTest(script=script):
                temporary, project, _ = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                result = self.run_script(project, script, "--unknown")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assert_no_project_outputs(project)

    def test_host_setup_rejects_check_with_preflight_before_writes(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                temporary, project, _ = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                result = self.run_script(
                    project,
                    f"setup_{host}.sh",
                    "--check",
                    "--preflight",
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assert_no_project_outputs(project)

    def test_setup_all_rejects_an_unknown_host_selector_before_writes(self) -> None:
        temporary, project, _ = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        result = self.run_script(project, "setup_all.sh", "--only=unknown")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assert_no_project_outputs(project)

    def test_setup_all_rejects_empty_or_conflicting_host_selectors_before_writes(self) -> None:
        for arguments in (("--only=",), ("--only=claude", "--only=codex")):
            with self.subTest(arguments=arguments):
                temporary, project, _ = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                result = self.run_script(project, "setup_all.sh", *arguments)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assert_no_project_outputs(project)

    def test_all_setup_entrypoints_disable_python_bytecode_writes(self) -> None:
        scripts = tuple(f"setup_{host}.sh" for host in HOSTS) + ("setup_all.sh",)
        for script in scripts:
            with self.subTest(script=script):
                body = (PACK / script).read_text(encoding="utf-8")
                self.assertIn("export PYTHONDONTWRITEBYTECODE=1", body)

    def test_host_setup_rejects_nested_delegation_depth_before_writes(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                config = pack / "project.yaml"
                config.write_text(
                    config.read_text(encoding="utf-8").replace(
                        "  max_depth: 1\n", "  max_depth: 2\n", 1
                    ),
                    encoding="utf-8",
                )
                result = self.run_script(project, f"setup_{host}.sh", "--preflight")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_no_project_outputs(project)

    def test_setup_all_check_does_not_require_a_legacy_operations_document(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        scaffold = self.run_script(project, "scripts/scaffold_project_docs.sh")
        self.assertEqual(scaffold.returncode, 0, scaffold.stdout + scaffold.stderr)
        for host in HOSTS:
            (pack / f"setup_{host}.sh").write_text(
                "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
            )
        self.assertFalse((project / "docs/OPERATIONS.md").exists())
        result = self.run_script(project, "setup_all.sh", "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_host_setup_does_not_mutate_pack_script_modes(self) -> None:
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                paths = (pack / "scripts/guard.sh", pack / "scripts/lint_rules.sh")
                before = {path: stat.S_IMODE(path.stat().st_mode) for path in paths}
                result = self.run_script(project, f"setup_{host}.sh")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                after = {path: stat.S_IMODE(path.stat().st_mode) for path in paths}
                self.assertEqual(before, after)

    def test_antigravity_check_rejects_source_skill_drift(self) -> None:
        temporary, project, pack = self.install_all()
        self.addCleanup(temporary.cleanup)
        source = pack / "platforms/shared/skills/xy-workflow/SKILL.md"
        source.write_text(source.read_text(encoding="utf-8") + "\nsource drift\n", encoding="utf-8")
        result = self.run_script(project, "setup_antigravity.sh", "--check")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_antigravity_check_rejects_managed_block_drift(self) -> None:
        temporary, project, _ = self.install_all()
        self.addCleanup(temporary.cleanup)
        target = project / "AGENTS.md"
        body = target.read_text(encoding="utf-8")
        marker = "<!-- pack:antigravity-begin -->"
        index = body.index(marker)
        body = body[:index] + body[index:].replace("\n", "\nmanaged drift\n", 1)
        target.write_text(body, encoding="utf-8")
        result = self.run_script(project, "setup_antigravity.sh", "--check")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_hosts_expose_the_same_ordered_pm_lifecycle(self) -> None:
        temporary, project, _ = self.install_all()
        self.addCleanup(temporary.cleanup)
        workflows = {
            "codex": project / ".agents/skills/xy-workflow/SKILL.md",
            "claude": project / ".claude/skills/xy-workflow/SKILL.md",
            "antigravity": project / ".agents/skills/xy-workflow/SKILL.md",
        }
        # 三个宿主必须共同验证新的展示边界：用户只收到自然语言确认请求，肯定答复
        # 由 PM 转换成内部 requirements_approved 状态。将两个动作分别作为有序锚点，
        # 可以同时防止审批被跳过，以及防止内部 gate token 再次泄露为用户输入要求。
        anchors = (
            "Classify production scope from the current request and available facts",
            # start retrieval 仍可用，但它必须位于按需分支，不能成为所有请求的固定前置门禁。
            "Activate `xy-project-memory` in start mode only when bounded cross-session recall or historical",
            "Every `Full` request performs a **Grill Me coverage check**",
            "After Full coverage is complete, activate `xy-plan`",
            "The PM then gives the concise natural-language approval brief and requests confirmation",
            "explicit affirmative reply records `requirements_approved` internally",
            "task_graph_cli.py validate",
            "Dispatch all currently ready independent tasks",
            "Re-evaluate downstream readiness after each completion",
            "## Default business confirmations and exceptions",
            "Activate `xy-build-verify`",
            "Run `task_graph_cli.py qa-ready` for the request",
            "exactly one integrated read-only `xy-qa` reviewer for this request",
            "After QA PASS, activate `xy-project-memory` in closeout mode",
            # Full 规划阶段会先记录“投影决定”，真正写入只发生在 QA PASS 后。
            # 使用应用动作作为锚点，避免 `str.index` 错把前置决定当成提前写文档。
            "apply the frozen",
            "perform the PM commit assessment above",
            "report to the user",
        )
        for host, path in workflows.items():
            with self.subTest(host=host):
                # 生命周期允许按需拆分；顺序断言仍覆盖完整契约，而不是只覆盖入口。
                body = read_contract(path)
                positions = [body.index(anchor) for anchor in anchors]
                self.assertEqual(sorted(positions), positions)
                self.assertIn("When no start retrieval ran, omit `memory_context`", body)

        root = (project / "AGENTS.md").read_text(encoding="utf-8")
        codex = root.split("<!-- pack:codex-begin -->", 1)[1].split(
            "<!-- pack:codex-end -->", 1
        )[0]
        antigravity = root.split("<!-- pack:antigravity-begin -->", 1)[1].split(
            "<!-- pack:antigravity-end -->", 1
        )[0]
        self.assertIn("$xy-workflow", codex)
        self.assertIn("/xy-workflow", (project / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("/xy-workflow", antigravity)

    def test_generated_roles_enforce_native_boundaries_and_capability_mapping(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        EngineeringBaselineContractTest.add_observed_modules(project)
        desktop = project / "apps/desktop"
        desktop.mkdir(parents=True)
        (desktop / "package.json").write_text(
            '{"main":"main.js","dependencies":{"electron":"40"}}',
            encoding="utf-8",
        )
        (desktop / "main.js").write_text("export {};\n", encoding="utf-8")
        apple = project / "apps/apple/App.xcodeproj/project.pbxproj"
        apple.parent.mkdir(parents=True)
        apple.write_text(
            "// !$*UTF8*$!\n{\n  objects = {\n"
            "    A1 = {\n      isa = PBXNativeTarget;\n"
            '      productType = "com.apple.product-type.application";\n'
            "    };\n  };\n}\n",
            encoding="utf-8",
        )
        android = project / "apps/android"
        (android / "src/main").mkdir(parents=True)
        (android / "build.gradle.kts").write_text(
            'plugins { id("com.android.application") version "9.0.0" }\n',
            encoding="utf-8",
        )
        (android / "src/main/AndroidManifest.xml").write_text(
            '<manifest package="example.fixture"/>\n', encoding="utf-8"
        )
        result = self.run_script(project, "setup_all.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        roles = (
            "xy-web",
            "xy-desktop",
            "xy-backend",
            "xy-apple",
            "xy-android",
            "xy-uiux",
            "xy-qa",
        )
        preview = subprocess.run(
            [
                sys.executable,
                str(pack / "lib/project_profile_cli.py"),
                "roles",
                str(pack),
                str(project),
            ],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        self.assertEqual(set(roles), set(preview.stdout.splitlines()))

        codex_config = tomllib.loads(
            (project / ".codex/config.toml").read_text(encoding="utf-8")
        )
        self.assertNotIn("max_depth", codex_config["agents"])
        for role in roles:
            with self.subTest(host="codex", role=role):
                agent = tomllib.loads(
                    (project / ".codex/agents" / f"{role}.toml").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(role, agent["name"])
        codex_qa = tomllib.loads(
            (project / ".codex/agents/xy-qa.toml").read_text(encoding="utf-8")
        )
        self.assertEqual("read-only", codex_qa["sandbox_mode"])
        self.assertIn("do not edit production", codex_qa["description"].lower())

        for role in roles:
            with self.subTest(host="claude", role=role):
                body = (project / ".claude/agents" / f"{role}.md").read_text(
                    encoding="utf-8"
                )
                frontmatter = body.split("---", 2)[1]
                self.assertIn(f"name: {role}", frontmatter)
                self.assertIn("Skill", frontmatter)
                self.assertIn("disallowedTools: Agent", frontmatter)
        claude_qa = (project / ".claude/agents/xy-qa.md").read_text(encoding="utf-8")
        normalized_claude_qa = " ".join(claude_qa.split()).lower()
        self.assertIn("never edit project files, add tests", normalized_claude_qa)

        nested_tools = ("invoke_subagent", "define_subagent", "send_message")
        qa_write_tools = (
            "write_to_file",
            "replace_file_content",
            "multi_replace_file_content",
            "generate_image",
        )
        for role in roles:
            with self.subTest(host="antigravity", role=role):
                body = (project / ".agents/agents" / f"{role}.md").read_text(
                    encoding="utf-8"
                )
                frontmatter = body.split("---", 2)[1]
                self.assertIn(f"name: {role}", frontmatter)
                self.assertIn("mainAgent: false", frontmatter)
                self.assertIn("subagent: true", frontmatter)
                for tool in nested_tools:
                    self.assertNotIn(tool, frontmatter)
        for retired in ("xy-python", "xy-rust", "xy-java"):
            for relative in (
                f".codex/agents/{retired}.toml",
                f".claude/agents/{retired}.md",
                f".agents/agents/{retired}.md",
            ):
                with self.subTest(retired=relative):
                    self.assertFalse((project / relative).exists())
        anti_qa = (project / ".agents/agents/xy-qa.md").read_text(encoding="utf-8")
        anti_qa_frontmatter = anti_qa.split("---", 2)[1]
        for tool in qa_write_tools:
            self.assertNotIn(tool, anti_qa_frontmatter)
        self.assertIn("Do not edit production business code", anti_qa)

        root = read_bootstrap_contract(project / "AGENTS.md", pack)
        antigravity = root.split("<!-- pack:antigravity-begin -->", 1)[1].split(
            "<!-- pack:antigravity-end -->", 1
        )[0]
        self.assertIn("/browser", antigravity)
        self.assertIn("Artifact review", antigravity)

    def test_documentation_defines_the_unified_three_host_contract(self) -> None:
        readme = (PACK / "README.md").read_text(encoding="utf-8")
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        for phrase in (
            "platforms/shared/skills/",
            "one shared source",
            ".agents/agents/xy-*.md",
            "task dependency graph",
            "all currently `READY` tasks",
            "request dependency closure",
            "one integrated QA",
            "QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report",
            "bash .agent-workflow/setup_antigravity.sh --check",
            "--only=claude",
            "--only=codex",
            "--only=antigravity",
        ):
            self.assertIn(phrase, readme)
        for phrase in (
            "platforms/shared/skills/",
            ".codex/agents/xy-*.toml",
            ".claude/agents/xy-*.md",
            ".agents/agents/xy-*.md",
            "QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report",
            "Codex",
            "Claude Code",
            "Antigravity",
        ):
            self.assertIn(phrase, schema)

    def test_shared_product_docs_define_the_dynamic_task_graph_contract(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        normalized_workflow = " ".join(workflow.lower().split())
        normalized_schema = " ".join(schema.lower().split())
        for field in ("depends_on", "gates", "blocks", "qa_scope"):
            with self.subTest(field=field):
                self.assertIn(field, workflow)
                self.assertIn(field, schema)
        for state in ("READY", "RUNNING", "BUILD_VERIFIED", "QA"):
            with self.subTest(state=state):
                self.assertIn(state, workflow)
                self.assertIn(state, schema)
        for phrase in (
            "dispatches all currently ready independent tasks",
            "re-evaluates downstream readiness after each completion",
            "current request dependency closure",
            "not all project work",
            "unrelated branches continue",
            "failures block only downstream dependents",
            "semantic dependency",
            "capacity delay",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), normalized_workflow)
                self.assertIn(phrase.lower(), normalized_schema)
        self.assertIn("qa_scope: request", normalized_schema)
        self.assertIn("ui gates only block tasks that declare a dependency", normalized_schema)
        self.assertNotIn("设计完成后释放线程", workflow)

    def test_shared_sources_default_to_requirements_and_final_visual_confirmation(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        active_sources = "\n".join(
            (
                workflow,
                schema,
                (PACK / "platforms/shared/AGENTS.product.tpl").read_text(encoding="utf-8"),
                (PACK / "platforms/shared/skills/xy-workflow/SKILL.md").read_text(encoding="utf-8"),
                (PACK / "platforms/shared/skills/xy-prototype-verify/SKILL.md").read_text(encoding="utf-8"),
                (PACK / "platforms/antigravity/AGENTS.antigravity.tpl").read_text(encoding="utf-8"),
                (PACK / "platforms/claude/AGENTS.claude.tpl").read_text(encoding="utf-8"),
                (PACK / "roles/xy-uiux.md").read_text(encoding="utf-8"),
            )
        )
        policy = (
            "business_confirmation_policy:\n"
            "  default_gates:\n"
            "    - requirements_approved\n"
            "  ui_only_gates:\n"
            "    - visual_approved\n"
            "  additional_gates: exceptional"
        )
        self.assertIn(policy, workflow)
        self.assertIn(policy, schema)
        for phrase in (
            "baseline_ready",
            "ia_ready",
            "prototype_verified",
            "visual_review_ready",
            "`UI-Conformance` and non-UI requests have no business confirmation after",
            "Platform security prompts",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, active_sources)
        for forbidden in ("Baseline Proceed", "IA Proceed", "Plan Proceed"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, active_sources)

    def test_each_ui_tier_reaches_visual_review_ready_before_approval(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        tier_rows = parse_ui_tier_flows(workflow)
        self.assertEqual(
            {"UI-Conformance", "UI-Patch", "UI-Page", "UI-Flow"},
            set(tier_rows),
        )
        for tier, flow in tier_rows.items():
            with self.subTest(tier=tier):
                self.assertTrue(is_valid_ui_tier_flow(tier, flow), flow)

    def test_ui_conformance_skips_design_only_for_a_proven_zero_design_delta(self) -> None:
        """锁定受约束快速路由，避免把“可跳过设计”退化成任意 UI 门禁绕过。"""

        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        workflow_skill = (
            PACK / "platforms/shared/skills/xy-workflow/SKILL.md"
        ).read_text(encoding="utf-8")
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        qa_skill = (
            PACK / "platforms/shared/skills/xy-qa-review/SKILL.md"
        ).read_text(encoding="utf-8")
        active_contract = " ".join(
            "\n".join((workflow, workflow_skill, schema, qa_skill)).split()
        )

        for phrase in (
            "UI-Conformance",
            "design_delta: none",
            "design_authority_refs",
            "does not dispatch `xy-uiux`",
            "does not require `visual_approved`",
            "must not edit `docs.standards_root/DESIGN_*.md`",
            "missing, stale, contradictory",
            "reclassify the request as `UI-Patch`, `UI-Page`, or `UI-Flow`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, active_contract)

        # UI-Conformance 仍然是 Full 工作：需求确认、构建证据和统一 QA 都不能省略。
        for phrase in (
            "requirements_approved",
            "xy-build-verify",
            "integrated read-only `xy-qa`",
        ):
            with self.subTest(required_full_evidence=phrase):
                self.assertIn(phrase, active_contract)

    def test_requirements_confirmation_captures_user_prototype_choice(self) -> None:
        """PM 只能推荐，设计变更的两条原型路径都必须由用户在需求确认时选择。"""

        sources = {
            relative: " ".join(read_contract(PACK / relative).split())
            for relative in (
                "product/WORKFLOW.md",
                "product/AGENT_SCHEMA.md",
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "platforms/shared/skills/xy-plan/SKILL.md",
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "platforms/shared/AGENTS.product.tpl",
                "platforms/claude/AGENTS.claude.tpl",
                "platforms/antigravity/AGENTS.antigravity.tpl",
                "roles/xy-web.md",
                "roles/xy-desktop.md",
                "roles/xy-apple.md",
                "roles/xy-android.md",
                "roles/xy-qa.md",
            )
        }

        for relative, body in sources.items():
            with self.subTest(relative=relative):
                self.assertIn("waived_by_user", body)
                self.assertIn("prototype_policy", body)
                self.assertIn("prototype_decision", body)

        combined = " ".join(sources.values())
        for phrase in (
            "requirements_confirmation_user_choice",
            "recommended_policy",
            "selected_policy",
            "must not invent",
            "no `xy-uiux` dependency",
            "no prototype write",
            "no visual gate",
            "requirements_approved",
            "ui and accessibility",
            "QA PASS",
            "PM commit assessment",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_qa_reuses_frozen_prototype_evidence_without_browser_reaudit(self) -> None:
        """原型完整字节扫描属于确定性工具；QA 不得对原型启动浏览器自动化。"""

        qa_skill = (
            PACK / "platforms/shared/skills/xy-qa-review/SKILL.md"
        ).read_text(encoding="utf-8")
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        qa_role = (PACK / "roles/xy-qa.md").read_text(encoding="utf-8")
        combined = " ".join("\n".join((qa_skill, workflow, qa_role)).split())

        for phrase in (
            "machine reads the complete dependency bytes",
            "must not preload or manually read the complete prototype dependency tree",
            "exact in-page contract",
            "smallest relevant source slice",
            "does not open or automate the prototype",
            "return FAIL to the PM for `xy-uiux` rework",
            "production implementation",
            "risk-based browser testing of the real production implementation",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

        self.assertNotIn("Re-run `xy-prototype-verify`", qa_skill)

    def test_ui_machine_contract_is_complete_at_each_execution_layer(self) -> None:
        """关键 UI 门禁必须分别存在于计划、运行时、宿主与执行角色，不能只在全局某处出现。"""

        sources = {
            relative: " ".join(read_contract(PACK / relative).split())
            for relative in (
                "product/WORKFLOW.md",
                "product/AGENT_SCHEMA.md",
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "platforms/shared/skills/xy-plan/SKILL.md",
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "platforms/shared/AGENTS.product.tpl",
                "platforms/claude/AGENTS.claude.tpl",
                "platforms/antigravity/AGENTS.antigravity.tpl",
                "roles/xy-web.md",
                "roles/xy-desktop.md",
                "roles/xy-apple.md",
                "roles/xy-android.md",
                "roles/xy-qa.md",
            )
        }

        # 规范、计划与 QA 各自必须拥有机器字段；拼接后“总能搜到”不能算覆盖。
        for relative in (
            "product/WORKFLOW.md",
            "product/AGENT_SCHEMA.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/shared/skills/xy-plan/SKILL.md",
            "platforms/shared/skills/xy-qa-review/SKILL.md",
        ):
            with self.subTest(relative=relative):
                body = sources[relative]
                for anchor in (
                    "UI-Conformance",
                    "UI-Patch",
                    "UI-Page",
                    "UI-Flow",
                    "surface_kind",
                    "qa_scope",
                    "content_fingerprint",
                    "resolution_state",
                    "prototype_paths",
                    "standards_contract",
                ):
                    self.assertIn(anchor, body, f"{relative}: missing {anchor}")

        # 三个宿主入口必须独立说明：一致性路由无视觉 Gate，设计变更路由有精确页面 Gate。
        for relative in (
            "platforms/shared/AGENTS.product.tpl",
            "platforms/claude/AGENTS.claude.tpl",
            "platforms/antigravity/AGENTS.antigravity.tpl",
        ):
            with self.subTest(host=relative):
                body = sources[relative]
                for anchor in (
                    "UI-Conformance",
                    "surface_kind",
                    "qa_scope",
                    "resolved/fingerprinted",
                    "xy-uiux",
                    "Gate",
                ):
                    self.assertIn(anchor, body, f"{relative}: missing {anchor}")

        # 每个生产角色和最终 QA 都必须识别机器分类与冻结依据，避免只靠 PM 提示词兜底。
        for relative in (
            "roles/xy-web.md",
            "roles/xy-desktop.md",
            "roles/xy-apple.md",
            "roles/xy-android.md",
            "roles/xy-qa.md",
        ):
            with self.subTest(role=relative):
                body = sources[relative]
                for anchor in (
                    "UI-Conformance",
                    "surface_kind: production_ui",
                    "qa_scope: request",
                    "fingerprint",
                    "accessibility",
                ):
                    self.assertIn(anchor, body, f"{relative}: missing {anchor}")

    def test_prototype_verification_is_static_and_contract_review_is_semantic(self) -> None:
        # 原型是用户确认材料：机器默认只验证静态结构与指纹，PM 另行核对页面合同是否忠于
        # 冻结需求。即使宿主具备浏览器能力，也不能因此自动生成 Computer Use 门禁。
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        workflow_skill = read_contract(
            PACK / "platforms/shared/skills/xy-workflow/SKILL.md"
        )
        prototype_skill = (
            PACK / "platforms/shared/skills/xy-prototype-verify/SKILL.md"
        ).read_text(encoding="utf-8")
        uiux = (PACK / "roles/xy-uiux.md").read_text(encoding="utf-8")
        product_bootstrap = read_contract(PACK / "platforms/shared/AGENTS.product.tpl")
        antigravity = read_contract(PACK / "platforms/antigravity/AGENTS.antigravity.tpl")
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")

        for relative, body in (
            ("product/WORKFLOW.md", workflow),
            ("platforms/shared/skills/xy-workflow/SKILL.md", workflow_skill),
            ("platforms/shared/AGENTS.product.tpl", product_bootstrap),
        ):
            with self.subTest(relative=relative):
                self.assertIn(
                    "Prototype verification MUST NOT invoke Computer Use or browser automation by default",
                    " ".join(body.split()),
                )
                self.assertIn(
                    "frozen approved requirements and acceptance criteria",
                    " ".join(body.split()),
                )

        self.assertIn(
            "owns the deterministic static prototype-verification coverage",
            " ".join(uiux.split()),
        )
        self.assertIn(
            "semantic text review and does not require rendering the page",
            " ".join(prototype_skill.split()),
        )
        self.assertIn(
            "Prototype verification MUST NOT invoke Computer Use or `/browser` by default",
            " ".join(antigravity.split()),
        )
        self.assertIn(
            "`prototype_verified` means deterministic structure, local-dependency, contract, and fingerprint validation",
            " ".join(schema.split()),
        )
        self.assertIn("does not claim Computer Use", schema)
        combined = "\n".join((workflow, workflow_skill, prototype_skill, uiux, antigravity))
        for retired in (
            "Open each concrete changed page directly in the browser",
            "host-only browser checks",
            "only the missing browser checks",
        ):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, combined)

    def test_ui_tier_helper_rejects_duplicate_trailing_and_misordered_gates(self) -> None:
        invalid = {
            "duplicate visual approval": (
                "UI-Patch",
                ("prototype_verified", "visual_review_ready", "visual_approved", "visual_approved"),
            ),
            "approval is not last": (
                "UI-Patch",
                ("prototype_verified", "visual_review_ready", "visual_approved", "implementation"),
            ),
            "review after approval": (
                "UI-Patch",
                ("prototype_verified", "visual_approved", "visual_review_ready"),
            ),
            "page IA after prototype": (
                "UI-Page",
                ("prototype", "ia_ready", "prototype_verified", "visual_review_ready", "visual_approved"),
            ),
            "flow IA after prototype": (
                "UI-Flow",
                ("connected prototype", "ia_ready", "prototype_verified", "visual_review_ready", "visual_approved"),
            ),
            "extra approval stage": (
                "UI-Page",
                ("ia_ready", "prototype_approved", "prototype_verified", "visual_review_ready", "visual_approved"),
            ),
            "prohibited fake stage": (
                "UI-Patch",
                ("MUST NOT skip prototype", "prototype_verified", "visual_review_ready", "visual_approved"),
            ),
            "omitted fake stage": (
                "UI-Patch",
                ("omit design review", "prototype_verified", "visual_review_ready", "visual_approved"),
            ),
        }
        for case, (tier, tokens) in invalid.items():
            with self.subTest(case=case):
                self.assertFalse(is_valid_ui_tier_flow(tier, tokens))

    def test_qa_outcome_contract_is_closed_to_pass_or_fail(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        qa_role = (PACK / "roles/xy-qa.md").read_text(encoding="utf-8")

        self.assertEqual(
            ("PASS", "FAIL"),
            parse_pipe_outcome_allowlist(workflow, "Final QA outcome:"),
        )
        self.assertEqual(
            ("PASS", "FAIL"),
            parse_pipe_outcome_allowlist(qa_role, "[Audit result]"),
        )
        for relative, body in (
            ("product/WORKFLOW.md", workflow),
            ("roles/xy-qa.md", qa_role),
        ):
            with self.subTest(relative=relative):
                self.assertEqual(FINAL_QA_OUTCOMES, extract_qa_outcome_identifiers(body))
                assert_closed_qa_outcomes(body)

    def test_qa_outcome_helper_rejects_every_unknown_pass_variant(self) -> None:
        for extra in (
            "PASS_WITH_NITS",
            "PASS-WITH-NITS",
            "PASS WITH NITS",
            "PASS_WITH_WARNINGS",
            "CONDITIONAL_PASS",
            "PARTIAL_PASS",
            "INCONCLUSIVE",
            "WARNING",
            "NEEDS_WORK",
            "BLOCKED",
        ):
            with self.subTest(extra=extra):
                fixture = f"Final QA outcome: PASS | FAIL | {extra}"
                with self.assertRaises(ValueError):
                    assert_closed_qa_outcomes(fixture)

    def test_qa_outcome_helper_ignores_non_outcome_technical_terms(self) -> None:
        fixture = (
            "Final QA outcome: PASS | FAIL\n"
            "The parser is FAIL_CLOSED and FAIL_SAFE. A gateway may PASS_THROUGH "
            "while TEST_FAIL remains a test name."
        )
        self.assertEqual(FINAL_QA_OUTCOMES, extract_qa_outcome_identifiers(fixture))
        assert_closed_qa_outcomes(fixture)

    def test_qa_outcome_helper_rejects_contextual_third_results(self) -> None:
        declarations = (
            "QA report: PASS_WITH_NITS",
            "QA returns PASS-WITH-NITS to PM.",
            "PM result: PASS WITH NITS",
            "QA outcome: INCONCLUSIVE",
            "QA final result: WARNING",
            "PM records QA result: NEEDS_WORK",
            "QA report: BLOCKED",
            "Report PASS_WITH_NITS to the PM for minor issues.",
            "Return INCONCLUSIVE to the PM.",
            "The QA result is NEEDS_WORK.",
        )
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                fixture = f"Final QA outcome: PASS | FAIL\n{declaration}"
                with self.assertRaises(ValueError):
                    assert_closed_qa_outcomes(fixture)

    def test_task2_canonical_checkpoint_is_self_contained(self) -> None:
        violations: list[str] = []
        for relative, anchors in TASK2_CANONICAL_MATRIX.items():
            body = read_contract(PACK / relative)
            normalized = normalized_contract_text(body)
            for anchor in anchors:
                if normalized_contract_text(anchor) not in normalized:
                    violations.append(f"{relative}: missing {anchor}")
        if violations:
            self.fail("Task 2 canonical checkpoint failed:\n- " + "\n- ".join(violations))

    def test_task2_gate_policy_is_typed_and_ui_conditional(self) -> None:
        for relative in (
            "product/WORKFLOW.md",
            "product/AGENT_SCHEMA.md",
            "product/GLOBAL_CONSTRAINTS.md",
        ):
            body = read_contract(PACK / relative)
            policy = (
                "business_confirmation_policy:\n"
                "  default_gates:\n"
                "    - requirements_approved\n"
                "  ui_only_gates:\n"
                "    - visual_approved\n"
                "  additional_gates: exceptional"
            )
            with self.subTest(relative=relative):
                self.assertIn(policy, body)
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        self.assertIn(
            '  - "visual_approved:<page-id>@<dependency-fingerprint>"', workflow
        )
        self.assertNotRegex(workflow, r"(?m)^\s*- visual_approved:\s+")

        scheduling = re.search(
            r"Scheduling fields use this machine-readable shape.*?```yaml\n(.*?)\n```",
            workflow,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(scheduling)
        gate_lines = re.findall(
            r'^\s+-\s+("[^"]+")\s*$', scheduling.group(1), flags=re.MULTILINE
        )
        self.assertEqual(
            ['"visual_approved:<page-id>@<dependency-fingerprint>"'], gate_lines
        )

    def test_page_dependency_fingerprint_replaces_manual_revision_state(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        uiux = (PACK / "roles/xy-uiux.md").read_text(encoding="utf-8")
        web = (PACK / "roles/xy-web.md").read_text(encoding="utf-8")
        qa = (PACK / "roles/xy-qa.md").read_text(encoding="utf-8")

        for phrase in (
            "safe local transitive dependency closure",
            "length-delimited path bytes and content bytes",
            "not a manual `rN`",
            "creates no Manifest or metadata file",
            "PM writes the verified value",
            "Web implementation and QA recompute it",
            "mismatch invalidates",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized_contract_text(workflow))
        self.assertIn("once per unchanged page scope", workflow)
        self.assertIn("existing workflow task state", workflow)
        self.assertIn("$xy-prototype-verify", uiux)
        self.assertIn("dependency fingerprints", normalized_contract_text(uiux))
        self.assertIn("verify each approved concrete page dependency fingerprint", web)
        self.assertIn("recompute approved page dependency fingerprints", qa.casefold())

        active = "\n".join((workflow, uiux, web, qa))
        for retired in (
            "current-page-revision",
            "visual_approved:<page-id>@<revision>",
            "manual page revision",
        ):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, active)

    def test_fingerprint_contract_covers_safe_transitive_dependency_graph(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        uiux = (PACK / "roles/xy-uiux.md").read_text(encoding="utf-8")
        web = (PACK / "roles/xy-web.md").read_text(encoding="utf-8")
        qa = (PACK / "roles/xy-qa.md").read_text(encoding="utf-8")
        normalized_workflow = normalized_contract_text(workflow)
        for anchor in (
            "safe local transitive dependency closure",
            "`link[href]`, `script[src]`, media `src`, and every `srcset` candidate",
            "CSS `@import` and `url(...)` references",
            "supported static local JavaScript `import` declarations",
            "safe, normalized workspace-relative path",
            "sort nodes by normalized path",
            "length-delimited path bytes and content bytes",
            "external, workspace-escaping, missing, or unsupported references make verification FAIL",
            "visited set",
            "creates no Manifest or metadata file",
            "Task 3/5 own the verifier calculation",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor.casefold(), normalized_workflow.casefold())
        for relative, body in (
            ("roles/xy-uiux.md", uiux),
            ("roles/xy-web.md", web),
            ("roles/xy-qa.md", qa),
        ):
            with self.subTest(relative=relative):
                normalized = normalized_contract_text(body)
                if relative == "roles/xy-uiux.md":
                    self.assertIn("dependency fingerprints", normalized)
                    self.assertIn("$xy-prototype-verify", body)
                elif relative == "roles/xy-web.md":
                    self.assertIn("page dependency fingerprint", normalized)
                else:
                    self.assertIn("dependency closure", normalized)

    def test_ready_is_derived_from_one_runtime_state_source(self) -> None:
        """调度状态可以包含 BLOCKED/FAILED，但不能再维护 completed/failed 旁路集合。"""

        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        for relative, body in (
            ("product/WORKFLOW.md", workflow),
            ("product/AGENT_SCHEMA.md", schema),
        ):
            with self.subTest(relative=relative):
                self.assertIn("READY", body)
                self.assertIn("derived", body.casefold())
                self.assertIn("single", body.casefold())
        self.assertIn("`BLOCKED`", workflow)
        self.assertNotRegex(workflow + schema, r"(?m)^(?:completed|failed):")

    def test_task2_minimal_authority_and_optional_script_contract(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        uiux = (PACK / "roles/xy-uiux.md").read_text(encoding="utf-8")
        web = (PACK / "roles/xy-web.md").read_text(encoding="utf-8")
        qa = (PACK / "roles/xy-qa.md").read_text(encoding="utf-8")

        self.assertNotIn("├── prototype.js", workflow)
        self.assertNotIn("docs/standards/prototype/prototype.js", schema)
        self.assertNotIn("├── prototype.js", uiux)
        self.assertIn("shared rule justified by multiple pages", uiux)
        self.assertIn("$xy-build-verify", web)
        self.assertNotIn("skill **`build-verify`**", web)
        self.assertIn("rendered frame ephemerally", normalized_contract_text(qa))
        self.assertIn("free of persisted visual evidence", qa.casefold())
        self.assertIn("See `product/WORKFLOW.md`", schema)
        self.assertNotIn("The index is only a thin page-link directory", schema)

    def test_task_graph_schema_carries_the_single_scheduler_runtime_state(self) -> None:
        """计划草案给出 DECLARED 初态，运行时快照沿用同一字段而不是另建 PM 清单。"""

        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        workflow_shape = re.search(
            r"Scheduling fields use this machine-readable shape.*?```yaml\n(.*?)\n```",
            workflow,
            flags=re.DOTALL,
        )
        schema_shape = re.search(
            r"Every task pack that requires scheduling declares these fields:.*?```yaml\n(.*?)\n```",
            schema,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(workflow_shape)
        self.assertIsNotNone(schema_shape)
        for relative, shape, body in (
            ("product/WORKFLOW.md", workflow_shape.group(1), workflow),
            ("product/AGENT_SCHEMA.md", schema_shape.group(1), schema),
        ):
            with self.subTest(relative=relative):
                self.assertRegex(shape, r"(?m)^state:\s*DECLARED")
                self.assertIn("scheduler runtime facts", body)
                self.assertIn("not independently maintained", body)

    def test_agent_schema_uses_real_uiux_routing_tags(self) -> None:
        schema = (PACK / "product/AGENT_SCHEMA.md").read_text(encoding="utf-8")
        self.assertIn(
            "| xy-uiux | design | ui, ux, wireframe, prototype, design-system |",
            schema,
        )
        self.assertNotIn("ui, ux, design-doc", schema)

    def test_task5_shared_skills_use_html_pages_as_design_evidence(self) -> None:
        violations: list[str] = []
        bodies: dict[str, str] = {}
        for relative, anchors in TASK5_SHARED_SKILL_MATRIX.items():
            body = read_contract(PACK / relative)
            bodies[relative] = body
            normalized = normalized_contract_text(body)
            for anchor in anchors:
                if normalized_contract_text(anchor).casefold() not in normalized.casefold():
                    violations.append(f"{relative}: missing {anchor}")

        for relative in (
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/shared/skills/xy-prototype-verify/SKILL.md",
            "platforms/shared/skills/xy-project-memory/SKILL.md",
        ):
            if not is_canonical_screenshot_prohibition(bodies[relative]):
                violations.append(
                    f"{relative}: missing {CANONICAL_SCREENSHOT_PROHIBITION}"
                )

        qa = normalized_contract_text(
            bodies["platforms/shared/skills/xy-qa-review/SKILL.md"]
        )
        for anchor in (
            # 原型是用户确认材料，默认不再要求浏览器自动化；只有生产实现按风险检查。
            "Prototype review MUST NOT invoke Computer Use or browser automation",
            "real production implementation requires browser inspection",
            "rendered frame ephemerally",
            "must not persist, save, write, attach, present, or use",
            "approval evidence",
            "no screenshot artifact on disk",
        ):
            if anchor.casefold() not in qa.casefold():
                violations.append(f"xy-qa-review: missing {anchor}")

        if violations:
            self.fail("Task 5 shared Skill contract is incomplete:\n- " + "\n- ".join(violations))

    def test_task5_shared_skills_create_no_companion_artifacts(self) -> None:
        violations: list[str] = []
        for relative, anchors in TASK5_NO_COMPANION_ARTIFACT_MATRIX.items():
            body = read_contract(PACK / relative)
            normalized = normalized_contract_text(body)
            for anchor in anchors:
                if normalized_contract_text(anchor).casefold() not in normalized.casefold():
                    violations.append(f"{relative}: missing {anchor}")
            for line_number, line in enumerate(body.splitlines(), start=1):
                if is_screenshot_allowance_or_fallback(line):
                    violations.append(
                        f"{relative}:{line_number}: screenshot fallback/allowance"
                    )
        if violations:
            self.fail("shared Skills permit companion artifacts:\n- " + "\n- ".join(violations))

    def test_task6_shared_pm_bootstrap_uses_latest_contract_only(self) -> None:
        bootstrap = (PACK / "platforms/shared/AGENTS.product.tpl").read_text(
            encoding="utf-8"
        )

        # 根入口承担常驻边界和路由；详细规则由真实引用审计，不再强制全量重复。
        for anchor in ("The PM is the sole orchestrator", "requirements_approved",
                       "visual_approved", "STANDARDS", "UI-Conformance",
                       "exactly one `xy-qa`", "Final QA outcome: PASS | FAIL"):
            self.assertIn(anchor, bootstrap)
        contract = read_contract(PACK / "platforms/shared/AGENTS.product.tpl")
        for anchor in ("frozen approved requirements and acceptance criteria",
                       "Prototype verification MUST NOT invoke Computer Use or browser automation by default",
                       "plan_state: draft", "task_graph_cli.py validate",
                       "qa_handoff_cli.py validate"):
            self.assertIn(anchor, " ".join(contract.split()))
        self.assertLess(len(bootstrap.encode()), len(contract.encode()))

    def test_task6_detailed_procedures_remain_in_existing_skills(self) -> None:
        violations: list[str] = []
        for relative, anchors in TASK6_DETAILED_SKILL_MATRIX.items():
            body = read_contract(PACK / relative)
            normalized = normalized_contract_text(body).casefold()
            for anchor in anchors:
                if normalized_contract_text(anchor).casefold() not in normalized:
                    violations.append(f"{relative}: missing {anchor}")
        self.assertEqual([], violations)

    def test_task6_shared_bootstrap_helper_rejects_legacy_union(self) -> None:
        canonical = "\n".join(
            (*TASK6_SHARED_BOOTSTRAP_ANCHORS, *TASK6_HOST_NEUTRAL_INVOCATIONS)
        )
        self.assertEqual([], task6_shared_bootstrap_violations(canonical))

        mutations = {
            "optional screenshot": "Optional screenshot evidence.",
            "screenshot fallback": "Screenshots are fallback evidence.",
            "root only": "The PM may provide only the root prototype index.",
            "root sufficient": "The root prototype index alone is sufficient.",
            "task design record": "Create a task design record.",
            "task design markdown": "Write a task design Markdown file.",
            "optional task design markdown": "Task design Markdown is optional.",
            "PM task design markdown": "The PM may write a task design Markdown file.",
            "manifest": "Generate a prototype Manifest.",
            "required manifest": "A prototype Manifest is required.",
            "companion markdown": "Create companion design Markdown.",
            "allowed companion markdown": "Companion design Markdown may be created.",
            "third QA outcome": "Final QA outcome: PASS | FAIL | PASS_WITH_NITS",
            "Codex alias": "$xy-workflow",
            "CLI alias": "/xy-workflow",
            "Claude Agent alias": "Agent(xy-web)",
        }
        for case, mutation in mutations.items():
            with self.subTest(case=case):
                self.assertTrue(
                    task6_shared_bootstrap_violations(canonical + "\n" + mutation),
                    mutation,
                )

    def test_task6_shared_bootstrap_keeps_detailed_procedure_in_skills(self) -> None:
        canonical = "\n".join(
            (*TASK6_SHARED_BOOTSTRAP_ANCHORS, *TASK6_HOST_NEUTRAL_INVOCATIONS)
        )
        for detail in TASK6_BOOTSTRAP_PROCEDURE_DETAILS:
            with self.subTest(detail=detail):
                self.assertTrue(
                    task6_shared_bootstrap_violations(canonical + "\n" + detail)
                )

    def test_task6_shared_bootstrap_rejects_production_prototype_adoption(self) -> None:
        canonical = "\n".join(
            (*TASK6_SHARED_BOOTSTRAP_ANCHORS, *TASK6_HOST_NEUTRAL_INVOCATIONS)
        )
        for target in TASK6_PROTOTYPE_ONLY_TARGETS:
            with self.subTest(target=target):
                mutation = f"Production may copy prototype-only {target}."
                self.assertTrue(
                    task6_shared_bootstrap_violations(canonical + "\n" + mutation),
                    mutation,
                )

    def test_task9_final_union_uses_stable_self_describing_pages(self) -> None:
        sources = self.active_workflow_sources()
        violations: list[str] = []
        for relative, anchors in WORKSPACE_CONTRACT_MATRIX.items():
            body = sources[relative]
            for anchor in anchors:
                if anchor not in body:
                    violations.append(f"{relative}: missing {anchor}")

        section_anchors = (
            'data-contract-section="purpose"',
            'data-contract-section="navigation"',
            'data-contract-section="interactions"',
            'data-contract-section="states"',
            'data-contract-section="exceptions"',
        )
        for relative in SECTION_CONTRACT_SOURCES:
            body = sources[relative]
            for anchor in section_anchors:
                if anchor not in body:
                    violations.append(f"{relative}: missing {anchor}")

        if violations:
            self.fail("incomplete per-source prototype contract:\n- " + "\n- ".join(violations))

    def test_task9_final_union_forbids_duplicate_task_artifacts(self) -> None:
        forbidden = (
            "<docs.standards_root>/prototypes/<task>/index.html",
            "YYYY-MM-DD-<task>.md",
            "Optional screenshot evidence",
            "provide an optional screenshot",
            "task design record",
            "prototype manifest",
        )
        violations: list[str] = []
        sources = self.active_workflow_sources()
        for relative in SCREENSHOT_PROHIBITION_SOURCES:
            if not is_canonical_screenshot_prohibition(sources[relative]):
                violations.append(
                    f"{relative}: missing {CANONICAL_SCREENSHOT_PROHIBITION}"
                )

        for relative, body in sources.items():
            normalized = body.casefold()
            for phrase in forbidden:
                if phrase.casefold() in normalized:
                    violations.append(f"{relative}: {phrase}")

            for line_number, line in enumerate(body.splitlines(), start=1):
                if is_screenshot_allowance_or_fallback(line):
                    violations.append(
                        f"{relative}:{line_number}: screenshot fallback/allowance: "
                        f"{normalized_contract_text(line)}"
                    )

        if violations:
            self.fail(
                "stale UI artifact or screenshot contract remains:\n- "
                + "\n- ".join(violations)
            )

    def test_screenshot_semantic_helpers_reject_inverted_or_optional_language(self) -> None:
        strict = (
            "The workflow MUST NOT generate, persist, attach, or present screenshots."
        )
        self.assertTrue(is_canonical_screenshot_prohibition(strict))
        self.assertFalse(is_screenshot_allowance_or_fallback(strict))

        inverted_or_allowed = (
            "Screenshots cannot be omitted.",
            "Screenshots are not forbidden.",
            "Screenshots are not prohibited.",
            "Continue without screenshots when possible.",
            "Screenshots are optional evidence.",
            "The PM may attach screenshots.",
            "The PM can present screenshots.",
            "Do not persist screenshots unless review is difficult.",
            "Do not attach screenshots except for fixed viewports.",
            "Attach screenshots only when the HTML is unavailable.",
            "Screenshots are fallback evidence.",
            "The workflow MUST NOT generate, persist, attach, or present screenshots except for QA fallback.",
            "The workflow MUST NOT generate, persist, attach, or present screenshots unless HTML inspection fails.",
            "The workflow MUST NOT generate, persist, attach, or present screenshots; screenshots are optional fallback evidence.",
            "QA must not omit screenshots.",
        )
        for sentence in inverted_or_allowed:
            with self.subTest(sentence=sentence):
                self.assertFalse(is_canonical_screenshot_prohibition(sentence))
                self.assertTrue(is_screenshot_allowance_or_fallback(sentence))

        alternative_non_authority_prohibitions = (
            "Screenshot output is disallowed.",
            "Avoid all screenshots.",
            "Screenshot capture is disabled.",
        )
        for sentence in alternative_non_authority_prohibitions:
            with self.subTest(sentence=sentence):
                self.assertFalse(is_canonical_screenshot_prohibition(sentence))
                self.assertFalse(is_screenshot_allowance_or_fallback(sentence))

        non_capture_capability = (
            "QA can validate without screenshots by inspecting the DOM.",
            "QA may inspect rendered frames ephemerally through a browser tool.",
        )
        for sentence in non_capture_capability:
            with self.subTest(sentence=sentence):
                self.assertFalse(is_screenshot_allowance_or_fallback(sentence))

    def test_qa_uses_ephemeral_rendered_frames_without_screenshot_artifacts(self) -> None:
        workflow = (PACK / "product/WORKFLOW.md").read_text(encoding="utf-8")
        qa = (PACK / "roles/xy-qa.md").read_text(encoding="utf-8")
        qa_workflow = workflow.split("## 10. QA and Failure Recovery", 1)[1].split(
            "## 11. Engineering Discipline", 1
        )[0]
        for relative, body in (
            ("product/WORKFLOW.md QA section", qa_workflow),
            ("roles/xy-qa.md", qa),
        ):
            with self.subTest(relative=relative):
                self.assertNotIn("MUST NOT generate", body)
                self.assertRegex(body, r"(?i)browser (?:tool )?inspection")
                self.assertIn("rendered frame", body)
                self.assertIn("ephemerally", body)
                self.assertIn("persist", body)
                self.assertIn("save", body)
                self.assertIn("write", body)
                self.assertIn("attach", body)
                self.assertIn("present", body)
                self.assertIn("use", body)
                self.assertIn("approval evidence", body)
                self.assertRegex(
                    body.casefold(),
                    r"no screenshot artifact on disk|free of persisted visual evidence",
                )
        for relative in (
            "product/WORKFLOW.md",
            "product/GLOBAL_CONSTRAINTS.md",
            "roles/xy-uiux.md",
        ):
            with self.subTest(visual_confirmation=relative):
                body = read_contract(PACK / relative)
                self.assertIn(CANONICAL_SCREENSHOT_PROHIBITION, body)

    def test_task9_final_union_requires_concrete_page_links(self) -> None:
        sources = self.active_workflow_sources()
        violations: list[str] = []
        for relative, anchors in VISUAL_HANDOFF_MATRIX.items():
            body = normalized_contract_text(sources[relative])
            for anchor in anchors:
                if anchor not in body:
                    violations.append(f"{relative}: missing {anchor}")

        for relative, anchors in HOST_RENDERER_COMPOSITION_MATRIX.items():
            body = sources[relative]
            for anchor in anchors:
                if anchor not in body:
                    violations.append(
                        f"{relative}: missing shared-source composition {anchor}"
                    )

        if violations:
            self.fail(
                "visual handoff or host source composition is incomplete:\n- "
                + "\n- ".join(violations)
            )

    def test_visual_handoff_helper_rejects_inverted_sentences(self) -> None:
        canonical = " ".join(STANDARD_VISUAL_HANDOFF_SENTENCES)
        self.assertTrue(has_standard_visual_handoff(canonical))
        for inverted in (
            "A direct link to each concrete changed page is unnecessary. "
            + ROOT_INDEX_HANDOFF_SENTENCE,
            DIRECT_PAGE_HANDOFF_SENTENCE
            + " The root prototype index alone is sufficient.",
            canonical + " A direct link to each concrete changed page is optional.",
            canonical + " The root prototype index alone is sufficient.",
            canonical + " Changed-page links may be omitted.",
            canonical + " A direct link is not required.",
            canonical + " Only the root prototype index is required.",
            canonical + " The PM may provide only the root prototype index.",
            canonical + " Links to concrete changed pages may be omitted.",
        ):
            with self.subTest(inverted=inverted):
                self.assertFalse(has_standard_visual_handoff(inverted))

    def test_fresh_non_ui_profile_scaffolds_only_core_documents(self) -> None:
        temporary, project, _ = self.make_docs_profile_fixture(ui_enabled=False)
        self.addCleanup(temporary.cleanup)

        result = self.run_script(project, "scripts/scaffold_project_docs.sh")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        files, directories = self.docs_inventory(project)
        self.assertEqual(
            {
                Path("docs/STANDARDS.md"),
                Path("docs/standards/GENERAL.md"),
                Path("docs/standards/UPSTREAM.md"),
                Path("docs/PROJECT.md"),
            },
            files,
        )
        self.assertEqual(
            {
                Path("docs"),
                Path("docs/features"),
                Path("docs/standards"),
            },
            directories,
        )
        for forbidden in (
            "docs/OPERATIONS.md",
            "docs/DESIGN_SYSTEM.md",
            "docs/design/README.md",
            "docs/ADR",
            "docs/notes",
        ):
            with self.subTest(path=forbidden):
                self.assertFalse((project / forbidden).exists(), forbidden)

    def test_fresh_ui_profile_adds_only_the_minimal_prototype_workspace(self) -> None:
        temporary, project, pack = self.make_docs_profile_fixture(ui_enabled=True)
        self.addCleanup(temporary.cleanup)

        result = self.run_script(project, "scripts/scaffold_project_docs.sh")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        files, directories = self.docs_inventory(project)
        self.assertEqual(
            {
                Path("docs/STANDARDS.md"),
                Path("docs/standards/GENERAL.md"),
                Path("docs/standards/UPSTREAM.md"),
                Path("docs/standards/DESIGN_FOUNDATIONS.md"),
                Path("docs/standards/DESIGN_COMPONENTS.md"),
                Path("docs/PROJECT.md"),
                Path("docs/standards/prototype/index.html"),
                Path("docs/standards/prototype/prototype.css"),
            },
            files,
        )
        self.assertEqual(
            {
                Path("docs"),
                Path("docs/features"),
                Path("docs/standards"),
                Path("docs/standards/prototype"),
            },
            directories,
        )
        self.assertEqual(
            (pack / "templates/prototype/index.html").read_bytes(),
            (project / "docs/standards/prototype/index.html").read_bytes(),
        )
        self.assertEqual(
            (pack / "templates/prototype/prototype.css").read_bytes(),
            (project / "docs/standards/prototype/prototype.css").read_bytes(),
        )
        index = (project / "docs/standards/prototype/index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('aria-label="Prototype pages"', index)
        for forbidden in (
            "prototype-contract",
            "manifest",
            "screenshot",
            "<iframe",
            "<script",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, index.casefold())
        for forbidden in (
            "docs/OPERATIONS.md",
            "docs/design/README.md",
            "docs/ADR",
            "docs/notes",
            "docs/standards/prototype/prototype.js",
            "docs/standards/prototype/manifest.json",
            "docs/standards/prototype/screenshots",
            "docs/standards/prototype/evidence",
        ):
            with self.subTest(path=forbidden):
                self.assertFalse((project / forbidden).exists(), forbidden)

    def test_new_project_templates_use_only_the_reduced_docs_schema(self) -> None:
        for relative in ("templates/project.yaml.example", "project.yaml"):
            with self.subTest(relative=relative):
                body = read_contract(PACK / relative)
                # 直接升级不接受 STATUS/SPEC 对应的旧键，也不提供别名兼容。
                for legacy_key in ("dev_rules", "project_status", "contracts", "progress", "ops"):
                    self.assertNotRegex(body, rf"(?m)^  {legacy_key}:")
                for canonical_key in (
                    "standards",
                    "standards_root",
                    "project",
                    "features",
                    "plans",
                    "notes",
                ):
                    self.assertRegex(body, rf"(?m)^  {canonical_key}:")
                self.assertIn("portable_checkpoint: docs/PROJECT.md", body)
                self.assertIn("fallback_dir: docs/notes/", body)

        self.assertFalse((PACK / "templates/docs/OPERATIONS.md").exists())
        self.assertFalse((PACK / "templates/docs/SPEC.md").exists())
        self.assertFalse((PACK / "templates/docs/STATUS.md").exists())
        self.assertTrue((PACK / "templates/docs/PROJECT.md").is_file())
        self.assertTrue((PACK / "templates/docs/FEATURE.md").is_file())
        self.assertTrue((PACK / "templates/docs/STANDARDS.md").is_file())
        self.assertTrue(
            (PACK / "templates/docs/standards/GENERAL.md").is_file()
        )
        self.assertFalse((PACK / "templates/docs/ENGINEERING.md").exists())
        self.assertFalse((PACK / "templates/docs/DESIGN_SYSTEM.md").exists())
        self.assertFalse((PACK / "templates/docs/design/README.md").exists())

        aggregate = (PACK / "setup_all.sh").read_text(encoding="utf-8")
        self.assertNotIn("for key in design adr notes", aggregate)
        self.assertNotIn("for key in design_system dev_rules progress contracts ops", aggregate)

    def test_scaffold_preserves_populated_legacy_and_lazy_document_trees(self) -> None:
        temporary, project, _ = self.make_docs_profile_fixture(ui_enabled=True)
        self.addCleanup(temporary.cleanup)

        fixtures = {
            "docs/OPERATIONS.md": b"legacy operations\n",
            "docs/design/README.md": b"legacy design readme\n",
            "docs/design/baseline/current-ui-audit.md": b"baseline bytes\x00\xff",
            "docs/plans/architecture.md": b"adr bytes\x00\xfe",
            "docs/notes/recall.md": b"notes bytes\x00\xfd",
            "docs/plans/current-ui.md": b"# Current UI proposal\n",
            "docs/standards/prototype/index.html": b"<p>legacy prototype</p>\n",
            "docs/standards/prototype/assets/custom.bin": b"\x00\x01\xff",
        }
        for relative, body in fixtures.items():
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        before = {
            path.relative_to(project): path.read_bytes()
            for path in sorted((project / "docs").rglob("*"))
            if path.is_file()
        }

        result = self.run_script(project, "scripts/scaffold_project_docs.sh")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = {
            path.relative_to(project): path.read_bytes()
            for path in sorted((project / "docs").rglob("*"))
            if path.is_file()
        }
        for relative, body in before.items():
            self.assertIn(relative, after)
            self.assertEqual(body, after[relative], relative)
        legacy_prototype_files = {
            path for path in after if Path("docs/standards/prototype") in path.parents
        }
        self.assertEqual(
            {
                Path("docs/standards/prototype/index.html"),
                Path("docs/standards/prototype/assets/custom.bin"),
            },
            legacy_prototype_files,
        )
        for forbidden in (
            Path("docs/plans/.gitkeep"),
            Path("docs/notes/.gitkeep"),
            Path("docs/design/.gitkeep"),
        ):
            self.assertNotIn(forbidden, after)

    def test_scaffold_replaces_an_empty_core_target_atomically(self) -> None:
        temporary, project, _ = self.make_docs_profile_fixture(ui_enabled=False)
        self.addCleanup(temporary.cleanup)
        target = project / "docs/standards/GENERAL.md"
        target.parent.mkdir(parents=True)
        target.touch(mode=0o640)
        before_inode = target.stat().st_ino

        result = self.run_script(project, "scripts/scaffold_project_docs.sh")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(target.read_bytes())
        self.assertNotEqual(before_inode, target.stat().st_ino)
        self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual(1, target.stat().st_nlink)

    def test_scaffold_restores_an_empty_project_index(self) -> None:
        temporary, project, _ = self.make_docs_profile_fixture(ui_enabled=False)
        self.addCleanup(temporary.cleanup)
        target = project / "docs/PROJECT.md"
        target.parent.mkdir(parents=True)
        target.touch(mode=0o640)
        before_inode = target.stat().st_ino

        result = self.run_script(project, "scripts/scaffold_project_docs.sh")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 唯一入口为空时必须恢复模板，不能沿用旧 STATUS 的“空文件即保留”特例。
        self.assertTrue(target.read_bytes())
        self.assertNotEqual(before_inode, target.stat().st_ino)
        self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual(1, target.stat().st_nlink)

    def test_direct_antigravity_restores_an_empty_project_index(self) -> None:
        temporary, project, pack = self.make_docs_profile_fixture(ui_enabled=False)
        self.addCleanup(temporary.cleanup)
        target = project / "docs/PROJECT.md"
        target.parent.mkdir(parents=True)
        target.touch(mode=0o640)
        before_inode = target.stat().st_ino

        result = self.run_antigravity_applier(project, pack)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(target.read_bytes())
        self.assertNotEqual(before_inode, target.stat().st_ino)
        self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual(1, target.stat().st_nlink)

    def test_scaffold_rejects_a_hard_linked_document_without_mutating_either_link(self) -> None:
        temporary, project, _ = self.make_docs_profile_fixture(ui_enabled=False)
        self.addCleanup(temporary.cleanup)
        target = project / "docs/standards/GENERAL.md"
        peer = project / "user-owned-engineering.md"
        target.parent.mkdir(parents=True)
        peer.write_bytes(b"user-owned hard-linked bytes\n")
        target.hardlink_to(peer)

        result = self.run_script(project, "scripts/scaffold_project_docs.sh")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("hard link", (result.stdout + result.stderr).casefold())
        self.assertEqual(b"user-owned hard-linked bytes\n", target.read_bytes())
        self.assertEqual(b"user-owned hard-linked bytes\n", peer.read_bytes())
        self.assertFalse((project / "docs/PROJECT.md").exists())

    def test_scaffold_does_not_replace_a_user_file_that_appears_at_missing_publish(self) -> None:
        temporary, project, _ = self.make_docs_profile_fixture(ui_enabled=False)
        self.addCleanup(temporary.cleanup)
        environment = os.environ.copy()
        environment["AGENT_WORKFLOW_PACK_TEST_SCAFFOLD_RACE"] = (
            "missing:docs/standards/GENERAL.md"
        )

        result = subprocess.run(
            ["bash", "agent_workflow/scripts/scaffold_project_docs.sh"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
            env=environment,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            b"concurrent user content\n",
            (project / "docs/standards/GENERAL.md").read_bytes(),
        )
        self.assertFalse((project / "docs/PROJECT.md").exists())

    def test_scaffold_restores_an_empty_target_modified_at_publish(self) -> None:
        temporary, project, _ = self.make_docs_profile_fixture(ui_enabled=False)
        self.addCleanup(temporary.cleanup)
        target = project / "docs/standards/GENERAL.md"
        target.parent.mkdir(parents=True)
        target.touch(mode=0o640)
        environment = os.environ.copy()
        environment["AGENT_WORKFLOW_PACK_TEST_SCAFFOLD_RACE"] = (
            "empty:docs/standards/GENERAL.md"
        )

        result = subprocess.run(
            ["bash", "agent_workflow/scripts/scaffold_project_docs.sh"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
            env=environment,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(b"concurrent user content\n", target.read_bytes())
        self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual(1, target.stat().st_nlink)
        self.assertFalse((project / "docs/PROJECT.md").exists())

    def test_direct_antigravity_ui_setup_scaffolds_exact_minimal_docs_inventory(self) -> None:
        temporary, project, pack = self.make_docs_profile_fixture(ui_enabled=True)
        self.addCleanup(temporary.cleanup)

        result = self.run_antigravity_applier(project, pack)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        files, directories = self.docs_inventory(project)
        self.assertEqual(
            {
                Path("docs/STANDARDS.md"),
                Path("docs/standards/GENERAL.md"),
                Path("docs/standards/UPSTREAM.md"),
                Path("docs/standards/DESIGN_FOUNDATIONS.md"),
                Path("docs/standards/DESIGN_COMPONENTS.md"),
                Path("docs/PROJECT.md"),
                Path("docs/standards/prototype/index.html"),
                Path("docs/standards/prototype/prototype.css"),
            },
            files,
        )
        self.assertEqual(
            {
                Path("docs"),
                Path("docs/features"),
                Path("docs/standards"),
                Path("docs/standards/prototype"),
            },
            directories,
        )
        self.assertEqual(
            (pack / "templates/prototype/index.html").read_bytes(),
            (project / "docs/standards/prototype/index.html").read_bytes(),
        )
        self.assertEqual(
            (pack / "templates/prototype/prototype.css").read_bytes(),
            (project / "docs/standards/prototype/prototype.css").read_bytes(),
        )

    def test_role_refresh_preserves_custom_design_index_without_injecting_unlinked_leaf(self) -> None:
        """重现 kf：已有设计基础及自定义目录，不因角色刷新新增未索引的组件规范。"""
        temporary, project, pack = self.make_docs_profile_fixture(ui_enabled=True)
        self.addCleanup(temporary.cleanup)
        result = self.run_script(project, "scripts/scaffold_project_docs.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        index = project / "docs/STANDARDS.md"
        body = "".join(line for line in index.read_text().splitlines(keepends=True)
                       if "DESIGN_COMPONENTS.md" not in line)
        index.write_text(body)
        component = project / "docs/standards/DESIGN_COMPONENTS.md"
        component.unlink()
        expected = {p.relative_to(project): p.read_bytes()
                    for p in (project / "docs").rglob("*") if p.is_file()}
        for run in (lambda: self.run_script(project, "scripts/scaffold_project_docs.sh"),
                    lambda: self.run_antigravity_applier(project, pack)):
            result = run()
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(component.exists())
            self.assertEqual(expected, {p.relative_to(project): p.read_bytes()
                                       for p in (project / "docs").rglob("*") if p.is_file()})

    def test_custom_design_prefixed_project_index_is_not_filtered_as_design_leaf(self) -> None:
        """两套发布器均须补齐合法自定义入口，并保留自定义索引及已存在的项目资料。"""
        for publisher in ("shared", "antigravity"):
            for initially_empty in (False, True):
                with self.subTest(publisher=publisher, initially_empty=initially_empty):
                    temporary, project, pack = self.make_docs_profile_fixture(ui_enabled=True)
                    self.addCleanup(temporary.cleanup)
                    initial = self.run_script(project, "scripts/scaffold_project_docs.sh")
                    self.assertEqual(0, initial.returncode, initial.stdout + initial.stderr)
                    # 真实的非空自定义目录不收录组件规范；刷新不得再注入该设计叶。
                    index = project / "docs/STANDARDS.md"
                    index.write_text("".join(line for line in index.read_text().splitlines(keepends=True)
                                             if "DESIGN_COMPONENTS.md" not in line), encoding="utf-8")
                    component = project / "docs/standards/DESIGN_COMPONENTS.md"
                    component.unlink()
                    config = pack / "project.yaml"
                    config.write_text(config.read_text().replace("docs/PROJECT.md", "docs/DESIGN_PROJECT.md"),
                                      encoding="utf-8")
                    target = project / "docs/DESIGN_PROJECT.md"
                    if initially_empty:
                        target.touch(mode=0o640)
                    before = {p.relative_to(project): p.read_bytes()
                              for p in (project / "docs").rglob("*") if p.is_file() and p != target}
                    result = (self.run_script(project, "scripts/scaffold_project_docs.sh")
                              if publisher == "shared" else self.run_antigravity_applier(project, pack))
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertTrue(target.read_bytes())
                    self.assertFalse(component.exists())
                    self.assertEqual([], validate_project_docs(config, project))
                    after = {p.relative_to(project): p.read_bytes()
                             for p in (project / "docs").rglob("*") if p.is_file() and p != target}
                    self.assertEqual(before, after)
                    if initially_empty:
                        self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))

    def test_direct_antigravity_non_ui_setup_scaffolds_exact_core_inventory(self) -> None:
        temporary, project, pack = self.make_docs_profile_fixture(ui_enabled=False)
        self.addCleanup(temporary.cleanup)

        result = self.run_antigravity_applier(project, pack)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        files, directories = self.docs_inventory(project)
        self.assertEqual(
            {
                Path("docs/STANDARDS.md"),
                Path("docs/standards/GENERAL.md"),
                Path("docs/standards/UPSTREAM.md"),
                Path("docs/PROJECT.md"),
            },
            files,
        )
        self.assertEqual(
            {
                Path("docs"),
                Path("docs/features"),
                Path("docs/standards"),
            },
            directories,
        )

    def test_direct_antigravity_preserves_active_prototype_and_legacy_doc_bytes(self) -> None:
        temporary, project, pack = self.make_docs_profile_fixture(ui_enabled=True)
        self.addCleanup(temporary.cleanup)
        fixtures = {
            "docs/OPERATIONS.md": b"project operations\n",
            "docs/design/README.md": b"project design readme\n",
            "docs/design/baseline/audit.md": b"audit\x00\xff",
            "docs/plans/decision.md": b"decision\x00\xfe",
            "docs/notes/context.md": b"notes\x00\xfd",
            "docs/standards/prototype/index.html": b"<p>active prototype</p>\n",
            "docs/standards/prototype/assets/custom.bin": b"\x00\x01\xff",
        }
        for relative, body in fixtures.items():
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        before = {
            path.relative_to(project): path.read_bytes()
            for path in sorted((project / "docs").rglob("*"))
            if path.is_file()
        }

        result = self.run_antigravity_applier(project, pack)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = {
            path.relative_to(project): path.read_bytes()
            for path in sorted((project / "docs").rglob("*"))
            if path.is_file()
        }
        for relative, body in before.items():
            self.assertEqual(body, after.get(relative), relative)
        prototype_files = {
            path for path in after if Path("docs/standards/prototype") in path.parents
        }
        self.assertEqual(
            {
                Path("docs/standards/prototype/index.html"),
                Path("docs/standards/prototype/assets/custom.bin"),
            },
            prototype_files,
        )

    def test_setup_all_check_accepts_missing_lazy_directories_and_legacy_files(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        scaffold = self.run_script(project, "scripts/scaffold_project_docs.sh")
        self.assertEqual(scaffold.returncode, 0, scaffold.stdout + scaffold.stderr)
        for host in HOSTS:
            (pack / f"setup_{host}.sh").write_text(
                "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
            )
        for relative in (
            "docs/OPERATIONS.md",
            "docs/design/README.md",
            "docs/ADR",
            "docs/notes",
        ):
            target = project / relative
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()

        result = self.run_script(project, "setup_all.sh", "--check")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_business_confirmation_validator_rejects_routine_extra_default_stages(self) -> None:
        mutations = (
            "The PM must obtain Baseline Proceed from the user.",
            "The PM must obtain IA Proceed from the user.",
            "The PM must obtain Plan Proceed from the user.",
            "The PM must obtain document approval from the user.",
            "The PM must obtain contract approval from the user.",
            "The PM must obtain plan approval from the user.",
            "The PM must obtain HTML preview approval from the user.",
            "The PM must obtain build approval from the user.",
            "The PM must obtain QA approval from the user.",
            "The PM must obtain rework approval from the user.",
            "The PM must obtain closeout approval from the user.",
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=mutation):
                temporary, _, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                workflow = pack / "product/WORKFLOW.md"
                workflow.write_text(
                    workflow.read_text(encoding="utf-8") + "\n" + mutation + "\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        str(pack / "lib/business_confirmation_policy.py"),
                        str(pack),
                        "all",
                    ],
                    cwd=pack.parent,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(
                    1,
                    result.returncode,
                    f"mutation accepted: {mutation}\n{result.stdout}{result.stderr}",
                )
                self.assertIn("[ERROR]", result.stderr)

    def test_business_confirmation_policy_rejects_duplicate_or_legacy_machine_policy(self) -> None:
        current_policy = (
            "business_confirmation_policy:\n"
            "  default_gates:\n"
            "    - requirements_approved\n"
            "  ui_only_gates:\n"
            "    - visual_approved\n"
            "  additional_gates: exceptional"
        )
        legacy_policy = (
            "business_confirmation_policy:\n"
            "  default_gates:\n"
            "    - requirements_approved\n"
            "    - visual_approved\n"
            "  additional_gates: exceptional"
        )
        for label, mutation in (
            ("duplicate", current_policy),
            ("legacy unconditional UI gate", legacy_policy),
        ):
            with self.subTest(label=label):
                temporary, _, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                for relative in ("product/WORKFLOW.md", "product/AGENT_SCHEMA.md"):
                    path = pack / relative
                    path.write_text(
                        path.read_text(encoding="utf-8") + "\n\n" + mutation + "\n",
                        encoding="utf-8",
                    )
                result = subprocess.run(
                    [
                        sys.executable,
                        str(pack / "lib/business_confirmation_policy.py"),
                        str(pack),
                        "all",
                    ],
                    cwd=pack.parent,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(
                    1,
                    result.returncode,
                    f"{label} policy accepted\n{result.stdout}{result.stderr}",
                )
                self.assertIn("[ERROR]", result.stderr)

    def test_business_confirmation_policy_requires_all_three_canonical_policy_sources(self) -> None:
        temporary, _, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        constraints = pack / "product/GLOBAL_CONSTRAINTS.md"
        canonical = (
            "business_confirmation_policy:\n"
            "  default_gates:\n"
            "    - requirements_approved\n"
            "  ui_only_gates:\n"
            "    - visual_approved\n"
            "  additional_gates: exceptional"
        )
        self.assertIn(canonical, constraints.read_text(encoding="utf-8"))
        constraints.write_text(
            constraints.read_text(encoding="utf-8").replace(
                canonical,
                canonical.replace("ui_only_gates", "legacy_ui_gates"),
                1,
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(pack / "lib/business_confirmation_policy.py"),
                str(pack),
                "all",
            ],
            cwd=pack.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("product/GLOBAL_CONSTRAINTS.md", result.stderr)

    def test_business_confirmation_policy_rejects_unparsed_or_scoped_gate_values(self) -> None:
        invalid_gate_blocks = (
            'gates: [""]',
            "gates: [42]",
            "gates:\n  - visual_approved:\n      page: checkout",
            'gates: ["platform_security_prompt:anything"]',
            'gates: ["architecture-decision:scope"]',
        )
        for gate_block in invalid_gate_blocks:
            with self.subTest(gate_block=gate_block):
                temporary, _, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                workflow = pack / "product/WORKFLOW.md"
                workflow.write_text(
                    workflow.read_text(encoding="utf-8")
                    + f"\n\n```yaml\n{gate_block}\n```\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        str(pack / "lib/business_confirmation_policy.py"),
                        str(pack),
                        "all",
                    ],
                    cwd=pack.parent,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(
                    1,
                    result.returncode,
                    f"invalid gate accepted: {gate_block}\n{result.stdout}{result.stderr}",
                )
                self.assertIn("[ERROR]", result.stderr)

    def test_business_confirmation_policy_accepts_supported_gates_and_block_lists(self) -> None:
        temporary, _, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        workflow = pack / "product/WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + """

```yaml
gates:
  - platform_security_prompt
  - "visual_approved:checkout@sha256-deadbeef"
  - architecture-decision
additional_business_confirmation:
  name: architecture-decision
  reason: This decision cannot safely be folded into an existing confirmation.
  decision_scope: Select the migration architecture.
  options:
    - in-place
    - side-by-side
  evidence:
    - docs/plans/architecture-options.md
  resume_condition: The user selects one named option.
```
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(pack / "lib/business_confirmation_policy.py"),
                str(pack),
                "all",
            ],
            cwd=pack.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_business_confirmation_policy_ignores_negated_confirmation_prose(self) -> None:
        def validate(sentence: str) -> subprocess.CompletedProcess[str]:
            temporary, _, pack = self.make_fixture()
            self.addCleanup(temporary.cleanup)
            workflow = pack / "product/WORKFLOW.md"
            workflow.write_text(
                workflow.read_text(encoding="utf-8") + f"\n{sentence}\n",
                encoding="utf-8",
            )
            return subprocess.run(
                [
                    sys.executable,
                    str(pack / "lib/business_confirmation_policy.py"),
                    str(pack),
                    "all",
                ],
                cwd=pack.parent,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )

        for sentence in (
            "QA approval is not required; QA is an automatic evidence state.",
            "The PM must not request QA approval.",
        ):
            with self.subTest(sentence=sentence):
                result = validate(sentence)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        positive = validate("The PM must request QA approval.")
        self.assertEqual(1, positive.returncode, positive.stdout + positive.stderr)
        self.assertIn("[ERROR]", positive.stderr)

    def test_business_confirmation_policy_allows_a_reasoned_task_scoped_exception(self) -> None:
        temporary, _, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        workflow = pack / "product/WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + """

The PM must obtain architecture approval for this material migration decision.

```yaml
gates: [architecture-decision]
additional_business_confirmation:
  name: architecture-decision
  reason: This material migration decision cannot safely be folded into an existing confirmation.
  decision_scope: Select the migration architecture.
  options: [in-place, side-by-side]
  evidence: [docs/plans/architecture-options.md]
  resume_condition: The user selects one named option.
```
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(pack / "lib/business_confirmation_policy.py"),
                str(pack),
                "all",
            ],
            cwd=pack.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        policy_sources = "\n".join(
            read_contract(PACK / relative)
            for relative in ("product/WORKFLOW.md", "product/AGENT_SCHEMA.md")
        )
        for field in (
            "additional_business_confirmation:",
            "name:",
            "reason:",
            "decision_scope:",
            "options:",
            "evidence:",
            "resume_condition:",
        ):
            self.assertIn(field, policy_sources)

    def test_business_confirmation_policy_rejects_an_unstructured_third_gate(self) -> None:
        temporary, _, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        workflow = pack / "product/WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + "\nThe PM must obtain architecture approval before implementation.\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(pack / "lib/business_confirmation_policy.py"),
                str(pack),
                "all",
            ],
            cwd=pack.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("unstructured additional business confirmation", result.stderr)

    def test_business_confirmation_policy_rejects_common_unstructured_gate_phrasings(self) -> None:
        mutations = (
            "Architecture approval is required before implementation.",
            "The user must approve the architecture before implementation.",
            "Do not proceed until the user approves the architecture.",
            "Architecture approval must be obtained before implementation.",
            "Proceed only after the user approves the architecture.",
            "Implementation is blocked pending architecture approval.",
            "The PM cannot continue without architecture approval.",
        )
        for relative in ("product/WORKFLOW.md", "product/GLOBAL_CONSTRAINTS.md"):
            for mutation in mutations:
                with self.subTest(relative=relative, mutation=mutation):
                    temporary, _, pack = self.make_fixture()
                    self.addCleanup(temporary.cleanup)
                    target = pack / relative
                    target.write_text(
                        target.read_text(encoding="utf-8") + "\n" + mutation + "\n",
                        encoding="utf-8",
                    )
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(pack / "lib/business_confirmation_policy.py"),
                            str(pack),
                            "all",
                        ],
                        cwd=pack.parent,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=30,
                    )
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    self.assertIn(
                        "unstructured additional business confirmation",
                        result.stderr,
                    )

    def test_business_confirmation_policy_rejects_nonconcrete_or_unqualified_exception(self) -> None:
        records = (
            """additional_business_confirmation:
  name: architecture-decision
  reason: []
  decision_scope: []
  options: []
  evidence: []
  resume_condition: []""",
            """additional_business_confirmation:
  name: architecture-decision
  reason: The PM wants another checkpoint.
  decision_scope: Select the architecture.
  options: [in-place, side-by-side]
  evidence: [docs/plans/options.md]
  resume_condition: The user selects one named option.""",
        )
        for record in records:
            with self.subTest(record=record):
                temporary, _, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                workflow = pack / "product/WORKFLOW.md"
                workflow.write_text(
                    workflow.read_text(encoding="utf-8")
                    + "\nArchitecture approval is required before implementation.\n\n"
                    + "```yaml\n"
                    + record
                    + "\n```\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        str(pack / "lib/business_confirmation_policy.py"),
                        str(pack),
                        "all",
                    ],
                    cwd=pack.parent,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("additional_business_confirmation", result.stderr)

    def test_business_confirmation_policy_validates_machine_gate_records_without_prose(self) -> None:
        temporary, _, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        workflow = pack / "product/WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + """

```yaml
gates: [architecture-decision]
additional_business_confirmation:
  name: architecture-decision
  reason: Missing the remaining fields.
```
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(pack / "lib/business_confirmation_policy.py"),
                str(pack),
                "all",
            ],
            cwd=pack.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("incomplete additional_business_confirmation", result.stderr)

    def test_business_confirmation_policy_rejects_structural_gate_bypasses(self) -> None:
        mutations = (
            'gates: ["architecture-decision"]',
            'gates:\n  - "architecture-decision"',
            """additional_business_confirmation:
  name:
  reason:
  decision_scope:
  options:
  evidence:
  resume_condition:""",
            "gates: [external_architecture_approval]",
            """gates: [architecture-decision]
additional_business_confirmation:
  name: architecture-decision
  reason: This decision cannot safely be folded into an existing confirmation.
  decision_scope: Select architecture A.
  options: [a, b]
  evidence: [a.md]
  resume_condition: User selects one.
additional_business_confirmation:
  name: architecture-decision
  reason: This decision cannot safely be folded into an existing confirmation.
  decision_scope: Select architecture B.
  options: [c, d]
  evidence: [b.md]
  resume_condition: User selects one.""",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                temporary, _, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                workflow = pack / "product/WORKFLOW.md"
                workflow.write_text(
                    workflow.read_text(encoding="utf-8")
                    + "\n```yaml\n"
                    + mutation
                    + "\n```\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        str(pack / "lib/business_confirmation_policy.py"),
                        str(pack),
                        "all",
                    ],
                    cwd=pack.parent,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("[ERROR]", result.stderr)

    def test_business_confirmation_policy_allows_architecture_clarification_without_a_gate(self) -> None:
        temporary, _, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        workflow = pack / "product/WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + "\nThe PM may ask an architecture question and present options as clarification.\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(pack / "lib/business_confirmation_policy.py"),
                str(pack),
                "all",
            ],
            cwd=pack.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_business_confirmation_policy_rejects_an_incomplete_exception_record(self) -> None:
        temporary, _, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        workflow = pack / "product/WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + """

The PM must obtain architecture approval before implementation.

```yaml
additional_business_confirmation:
  name: architecture-decision
  reason: Migration boundary is unresolved.
```
""",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(pack / "lib/business_confirmation_policy.py"),
                str(pack),
                "all",
            ],
            cwd=pack.parent,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("incomplete additional_business_confirmation", result.stderr)


if __name__ == "__main__":
    unittest.main()
