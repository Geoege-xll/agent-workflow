"""分级计划入口与浅层规范的回归：验证实际结构、权限和审计，不触及真实项目。"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from tests.skill_contract_helpers import read_contract

from lib.standard_paths import canonical_standard_path, standard_domain
from lib.validate_project_config import validate_docs
from lib.validate_project_docs import validate as validate_documents
from lib.validate_prototype_workspace import ValidationError, validate_workspace
from tests import test_design_standards_lifecycle as design_cases
from tests import test_prototype_workspace as prototype_cases
from tests import test_qa_handoff as qa_cases


PACK = Path(__file__).resolve().parents[1]


class PlanAndShallowDocsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="plan-shallow-docs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config = self.root / "project.yaml"
        self.config.write_text((PACK / "project.yaml").read_text(), encoding="utf-8")
        self.docs = self.root / "docs"
        self.standards = self.docs / "standards"
        self.standards.mkdir(parents=True)
        (self.docs / "features").mkdir()
        (self.docs / "PROJECT.md").write_text("# Project\n", encoding="utf-8")
        (self.docs / "STANDARDS.md").write_text(
            "# Standards\n\n[General](standards/GENERAL.md)\n"
            "[Design](standards/DESIGN_FOUNDATIONS.md)\n", encoding="utf-8",
        )
        (self.standards / "GENERAL.md").write_text(
            "# General\n- Domain: engineering\n- `[eng-example] [hard]` Keep contracts.\n",
            encoding="utf-8",
        )
        (self.standards / "DESIGN_FOUNDATIONS.md").write_text(
            "# Design\n- Domain: design\n- `[des-example] [hard]` Keep accessibility.\n",
            encoding="utf-8",
        )

    def test_current_config_uses_plans_without_creating_a_plan(self) -> None:
        errors: list[str] = []
        docs = validate_docs(self.config.read_text().splitlines(), self.root, errors)
        self.assertEqual([], errors)
        self.assertEqual("docs/plans/", docs["plans"])
        self.assertNotIn("adr", docs)
        self.assertFalse((self.docs / "plans").exists())
        self.assertEqual([], validate_documents(self.config, self.root))

    def test_old_adr_key_is_rejected_not_silently_aliased(self) -> None:
        lines = self.config.read_text().replace("plans: docs/plans/", "adr: docs/ADR/").splitlines()
        errors: list[str] = []
        validate_docs(lines, self.root, errors)
        self.assertTrue(any("unsupported docs key: adr" in error for error in errors))
        self.assertTrue(any("missing keys: plans" in error for error in errors))

    def test_shared_architecture_is_a_current_detail_not_a_second_adr(self) -> None:
        detail = self.docs / "features/architecture.md"
        detail.write_text(
            "# Shared architecture\n- Feature ID: ARCH-SHARED\n- Status: active\n"
            "## Current solution and rationale\nUse adapters to preserve upstream boundaries.\n",
            encoding="utf-8",
        )
        (self.docs / "PROJECT.md").write_text(
            "# Project\n[Architecture](features/architecture.md)\n", encoding="utf-8",
        )
        self.assertEqual([], validate_documents(self.config, self.root))

    def test_paused_plan_does_not_become_verified_feature_truth(self) -> None:
        plans = self.docs / "plans"
        plans.mkdir()
        plan = plans / "batch-approval.md"
        body = "# Batch approval\n- Status: paused\nBackend verified; UI not yet confirmed.\n"
        plan.write_text(body, encoding="utf-8")
        self.assertEqual([], validate_documents(self.config, self.root))
        self.assertEqual(body, plan.read_text())
        self.assertEqual([], list((self.docs / "features").iterdir()))
        self.assertNotIn("Batch", (self.docs / "PROJECT.md").read_text())

    def test_leaf_domain_cannot_be_relabelled(self) -> None:
        leaf = self.standards / "DESIGN_FOUNDATIONS.md"
        leaf.write_text(leaf.read_text().replace("Domain: design", "Domain: engineering"))
        self.assertTrue(any("Domain: design" in item for item in validate_documents(self.config, self.root)))

    def test_old_nested_standards_are_not_hidden_from_validation(self) -> None:
        (self.standards / "design/references").mkdir(parents=True)
        self.assertTrue(any("migrate nested directory" in item for item in validate_documents(self.config, self.root)))

    def test_path_classification_preserves_design_type_for_case_aliases(self) -> None:
        for path in ("docs/standards/design_foundations.md", "docs/STANDARDS/DESIGN_FOUNDATIONS.md"):
            with self.subTest(path=path):
                self.assertEqual("design", standard_domain(path, "docs/standards"))
                self.assertFalse(canonical_standard_path(path, "docs/standards"))

    def test_production_writer_cannot_edit_design_through_case_alias(self) -> None:
        helper = design_cases.DesignStandardsLifecycleTest()
        for path in ("docs/standards/design_foundations.md", "docs/STANDARDS/DESIGN_FOUNDATIONS.md"):
            with self.subTest(path=path):
                payload = helper.fixture(production=True)
                payload["tasks"][1]["owned_paths"] = [path]
                for document in payload["tasks"][1]["controlled_document_access"]["documents"]:
                    document["applies_to"] = [path]
                self.assertNotEqual(0, helper.invoke(payload).returncode)

    def test_ui_agent_cannot_write_engineering_leaf_in_flat_root(self) -> None:
        helper = design_cases.DesignStandardsLifecycleTest()
        payload = helper.fixture()
        payload["tasks"][0]["owned_paths"] = ["docs/standards/GENERAL.md"]
        self.assertIn("standards_only owns only exact", helper.invoke(payload).stderr)

    def test_all_selected_standards_must_be_registered_even_outside_required_domain(self) -> None:
        helper = design_cases.DesignStandardsLifecycleTest()
        for path in ("docs/standards/engineering/HIDDEN.md", "docs/standards/HIDDEN.md", "docs/standards/design/OLD.md"):
            with self.subTest(path=path):
                payload = helper.fixture()
                documents = payload["tasks"][0]["controlled_document_access"]["documents"]
                document = copy.deepcopy(documents[1])
                document.update(path=path, rule_ids=["rogue-rule"])
                documents.append(document)
                self.assertIn("absent from contract", helper.invoke(payload).stderr)

    def test_qa_rejects_domain_spoofing_and_case_alias(self) -> None:
        helper = qa_cases.QAHandoffValidationTest()
        helper.setUp()
        for path in ("docs/standards/DESIGN_FOUNDATIONS.md", "docs/standards/design_foundations.md", "docs/standards/engineering/GENERAL.md"):
            with self.subTest(path=path):
                payload = copy.deepcopy(helper.payload)
                payload["standards_policy_coverage"]["rule_checks"][0]["source_path"] = path
                self.assertNotEqual(0, helper.invoke(payload).returncode)

    def test_prototype_assets_cannot_hide_an_unreviewed_page_or_plan(self) -> None:
        for relative in ("ignored.HTML", "ignored.htm", "assets/ignored.HTML", "assets/task.MD"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                project = prototype_cases.write_valid_project(Path(temporary))
                prototype = project / prototype_cases.PROTOTYPE_RELATIVE
                target = prototype / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("unreviewed", encoding="utf-8")
                with self.assertRaises(ValidationError):
                    validate_workspace(project, prototype_cases.PROTOTYPE_RELATIVE.as_posix())

    def test_plan_lifecycle_reference_is_shipped_and_discoverable(self) -> None:
        # 这是分发连接测试，不假装用关键字匹配证明宿主实际执行了计划恢复。
        reference = "references/plan-lifecycle.md"
        workflow = PACK / "platforms/shared/skills/xy-workflow"
        self.assertTrue((workflow / reference).is_file())
        for relative in (
            "platforms/shared/skills/xy-workflow/SKILL.md", "platforms/shared/skills/xy-plan/SKILL.md",
            "platforms/shared/skills/xy-project-memory/SKILL.md", "platforms/shared/AGENTS.product.tpl",
            "platforms/codex/AGENTS.codex.tpl", "platforms/claude/AGENTS.claude.tpl", "platforms/antigravity/AGENTS.antigravity.tpl",
        ):
            self.assertIn(reference, read_contract(PACK / relative), relative)
        self.assertTrue((PACK / "templates/docs/PLAN.md").is_file())
