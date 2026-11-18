from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.skill_contract_helpers import read_contract
from lib.skills.qa_review_policy import validate_pack_qa_review_policy


PACK = Path(__file__).resolve().parents[1]


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


LIGHTWEIGHT_SKILL_POLICY_SOURCES = (
    "product/WORKFLOW.md",
    "product/AGENT_SCHEMA.md",
    "platforms/shared/skills/xy-workflow/SKILL.md",
    "platforms/shared/skills/xy-qa-review/SKILL.md",
)


LIGHTWEIGHT_SKILL_POLICY_ANCHORS = (
    "external_workflow_policy:",
    "requirements_provider: xy-grilling",
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
        files: set[Path] = set(

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


class ControlledDocumentAccessContractTest(unittest.TestCase):
    """Controlled documents are selected per task instead of preloaded per role."""

    def test_project_adapter_has_no_static_role_read_list(self) -> None:
        for path in (PACK / "project.yaml", PACK / "templates/project.yaml.example"):
            with self.subTest(path=path):
                self.assertNotRegex(
                    path.read_text(encoding="utf-8"), r"(?m)^role_reads\s*:"
                )
        self.assertFalse((PACK / "lib/inject_role_reads.py").exists())
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
            "Each production-code Writer's baseline is built-in xy-code-standards/references/rules.md",
            "xy-uiux + design_ui selects only applicable design sources",
            "Bind the real SHA when the project index exists",
            "With no project leaves and a missing index, create no empty index",
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
                self.assertIn("currently applicable built-in sources", normalized)
                self.assertIn("applicable rule IDs, and applies_to", normalized)
                self.assertIn("return missing, skip, stale, or insufficient coverage to the PM", normalized)

    def test_roles_consume_only_the_pm_access_plan(self) -> None:
        for path in sorted((PACK / "roles").glob("xy-*.md")):
            body = path.read_text(encoding="utf-8")
            with self.subTest(role=path.stem):
                self.assertIn("controlled_document_access", body)
                self.assertIn("non-skip", body)
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


class LightweightSkillAndReviewPolicyContractTest(unittest.TestCase):
    """The pack owns orchestration; Grill Me and one reviewer remain bounded tools."""

    def test_v2_execution_contract_rejects_retired_grade_and_missing_identity_policy(self) -> None:
        """入口检查必须拒绝旧执行格式，不能靠保留旧文案让schema 2检查继续通过。"""
        from lib.skills.business_confirmation_policy import validate_execution_texts

        path = PACK / "product/WORKFLOW.md"
        current = path.read_text(encoding="utf-8")
        self.assertEqual([], validate_execution_texts(((path, current),)))
        for old, new in (("Light | Full", "Trivial | Light | Full"),
                         ("instance_policy: fresh", "instance_policy: reuse"),
                         ("context_policy: handoff_only", "context_policy: inherit_parent")):
            with self.subTest(field=old):
                self.assertIn(old, current)
                invalid = current.replace(old, new)
                self.assertTrue(validate_execution_texts(((path, invalid),)))

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
                PACK / "docs/usage.md",
                PACK / "docs/development.md",

                PACK / "project.yaml",


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

    def test_full_work_uses_bundled_grilling_and_draft_planning_before_approval(self) -> None:
        """Full 前置链必须跨事实源一致，且 QA 前不得污染正式项目真相。"""

        sources = (
            "product/WORKFLOW.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/claude/references/pm-integration.md",
            "platforms/antigravity/references/pm-integration.md",
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
            "product/WORKFLOW.md", "product/GLOBAL_CONSTRAINTS.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        ):
            with self.subTest(source=relative):
                self.assertIn("grilling", self._text(relative))
                self.assertNotIn("grill-me` is this pack's self-contained", self._text(relative))

    def test_planning_is_core_and_grilling_is_a_bundled_upstream_primitive(self) -> None:
        """内部规划与第三方原版分离，不能通过伪本地Grill Me隐藏二级primitive。"""
        from lib.skills.role_skills import CORE_SKILLS, PM_SKILLS, SELECTED_SKILLS
        self.assertNotIn("grill-me", CORE_SKILLS)
        self.assertEqual({"xy-grill-me", "xy-grilling", "xy-taste", "xy-playwright"}, set(SELECTED_SKILLS))
        self.assertEqual(("xy-grilling",), PM_SKILLS)
        self.assertIn("xy-plan", CORE_SKILLS)
        canonical = PACK / "third_party/selected-skills/grill-me/skills/productivity"
        entry = (canonical / "grill-me/SKILL.md").read_text(encoding="utf-8")
        primitive = (canonical / "grilling/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("disable-model-invocation: true", entry)
        self.assertIn("grilling", entry)
        self.assertIn("frontier", primitive)
        intake = self._text("platforms/shared/skills/xy-workflow/references/requirements-intake.md")
        self.assertIn("grill_result:", intake)
        self.assertIn("不是上游 Grill Me 的 schema", intake)
        self.assertNotIn("grill_result", entry + primitive)
        plan = self._text("platforms/shared/skills/xy-plan/SKILL.md")
        self.assertNotIn("subagent-driven-development", plan)
        self.assertNotIn("executing-plans", plan)
        self.assertIn("methodology_reference: superpowers-writing-plans", plan)
        self.assertIn("task_graph", plan)

    def test_internal_machine_records_are_not_user_facing_output(self) -> None:
        """内部结构继续驱动 PM，但不得把原始 YAML、JSON 或门禁令牌交给用户审阅。"""

        # 四个共享 Skill 分别产生需求覆盖、记忆、计划和运行时编排数据。这里锁定的只是
        # 展示边界：结构本身仍然存在，PM 对用户只投影自然语言结论，避免误删调度能力。
        skill_expectations = {
            "platforms/shared/skills/xy-workflow/references/requirements-intake.md": (
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
        self.assertIn("grill_result:", self._text("platforms/shared/skills/xy-workflow/references/requirements-intake.md"))
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
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/claude/references/pm-integration.md",
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
        # 现用规则以工作流、角色和宿主模板为准；历史执行计划只记录实施过程。
        # 已完成计划由 Git 历史保留，清理旧计划不应影响现用规则的禁用短语检查。
        active_sources = LIGHTWEIGHT_SKILL_POLICY_SOURCES + (
            "roles/xy-qa.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/claude/references/pm-integration.md",
            "platforms/codex/references/pm-integration.md",
            "platforms/antigravity/references/pm-integration.md",
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
                "Clear, reproducible Light bugs use `native_bug_fix` without Grill Me.",
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
            "For `change_type: removed`, mark the same source `removed`",
            workflow,
        )
        self.assertIn(
            "QA failure preserves original accepted facts.",
            workflow,
        )

    def test_pm_assesses_a_scoped_commit_after_qa_without_a_third_business_gate(self) -> None:
        """提交是 QA 后的 PM 收口动作；它不能抢跑、扩大暂存范围或变成第三次确认。"""

        lifecycle = (
            "QA PASS -> controlled-document projection -> PM commit assessment -> "
            "memory closeout -> final report"
        )
        # 手册给出中文操作归属，完整机器化生命周期仍由以下权威源保持。
        usage = self._text("docs/usage.md")
        self.assertIn("QA 通过后由 PM 接收结果", usage)
        self.assertIn("按当前事实评估并原位更新受控文档", usage)
        self.assertIn("docs/development.md", self._text("README.md"))
        for relative in (
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
            "platforms/shared/skills/xy-workflow/SKILL.md",
            "platforms/claude/references/pm-integration.md",
            "platforms/antigravity/references/pm-integration.md",
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
            "platforms/claude/references/pm-integration.md": (
                "host-native-review",
                "installed-code-review-skill",
                "internal-xy-qa-procedure",
            ),
            "platforms/codex/references/pm-integration.md": (
                "Codex native review",
                "installed-code-review-skill",
                "internal-xy-qa-procedure",
            ),
            "platforms/antigravity/references/pm-integration.md": (
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
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "platforms/claude/references/pm-integration.md",
                "platforms/codex/references/pm-integration.md",
                "platforms/antigravity/references/pm-integration.md",
            )
            for relative in authorities:
                target = fixture / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((PACK / relative).read_bytes())
                if target.name == "SKILL.md":
                    # 契约夹具必须携带入口指向的分支；只复制入口会人为制造缺失规则。
                    shutil.copytree((PACK / relative).parent / "references",
                                    target.parent / "references", dirs_exist_ok=True)
            # 打包检查使用实际宿主入口；只复制审查器会读取的文本和固定参考文件。
            for relative in ("plugins/main-session-context.md", "plugins/plugin-context.md",
                             "plugins/antigravity/plugin-context.md"):
                target = fixture / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((PACK / relative).read_bytes())
            self.assertEqual((), validate_pack_qa_review_policy(fixture))

            # 验收正文搬入按需引用后，入口存在不能掩盖规则丢失；真实源校验必须拒绝
            # 缺失分支，而不是只验证仍留在 SKILL.md 的方法顺序。内存保留原字节供同一
            # 夹具恢复，不创建源码备份树，后续负向场景继续复用这一个夹具。
            acceptance = fixture / "platforms/shared/skills/xy-qa-review/references/implementation-acceptance.md"
            acceptance_bytes = acceptance.read_bytes()
            acceptance.unlink()
            try:
                errors = validate_pack_qa_review_policy(fixture)
                self.assertTrue(errors)
                self.assertTrue(any("implementation-acceptance.md" in error for error in errors), errors)
            finally:
                acceptance.write_bytes(acceptance_bytes)

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

            setup = fixture / "lib/fixture.py"
            setup.parent.mkdir(exist_ok=True)
            for retired in RETIRED_QA_POLICY_TERMS:
                setup.write_text(f"# {retired}\n", encoding="utf-8")
                errors = validate_pack_qa_review_policy(fixture)
                self.assertTrue(
                    any(retired in error for error in errors),
                    f"runtime policy validator accepted retired term: {retired}",
                )


class BusinessConfirmationPolicyTest(unittest.TestCase):
    def make_fixture(self):
        """仅复制策略测试实际读取的源码；不依赖宿主安装、不遍历业务工作区。"""
        temporary = tempfile.TemporaryDirectory(prefix="confirmation-policy-")
        root = Path(temporary.name).resolve()
        pack = root / "package"
        for directory in ("lib", "platforms", "product", "roles"):
            shutil.copytree(PACK / directory, pack / directory, ignore=shutil.ignore_patterns("__pycache__"))
        for relative in ("plugins/main-session-context.md", "plugins/plugin-context.md",
                         "plugins/antigravity/plugin-context.md"):
            target = pack / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((PACK / relative).read_bytes())
        return temporary, root, pack

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
                        str(pack / "lib/skills/business_confirmation_policy.py"),
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
                        str(pack / "lib/skills/business_confirmation_policy.py"),
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
                str(pack / "lib/skills/business_confirmation_policy.py"),
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
                        str(pack / "lib/skills/business_confirmation_policy.py"),
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
                str(pack / "lib/skills/business_confirmation_policy.py"),
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
                    str(pack / "lib/skills/business_confirmation_policy.py"),
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
                str(pack / "lib/skills/business_confirmation_policy.py"),
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
                str(pack / "lib/skills/business_confirmation_policy.py"),
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
                            str(pack / "lib/skills/business_confirmation_policy.py"),
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
                        str(pack / "lib/skills/business_confirmation_policy.py"),
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
                str(pack / "lib/skills/business_confirmation_policy.py"),
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
                        str(pack / "lib/skills/business_confirmation_policy.py"),
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
                str(pack / "lib/skills/business_confirmation_policy.py"),
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
                str(pack / "lib/skills/business_confirmation_policy.py"),
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
