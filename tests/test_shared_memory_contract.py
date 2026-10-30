from __future__ import annotations

import unittest
from pathlib import Path
import shutil
import subprocess
import tempfile
from tests.skill_contract_helpers import read_contract


PACK = Path(__file__).resolve().parents[1]
PRECEDENCE = "Current controlled documents and explicit user approvals win over recalled memory."
FIELDS = (
    "memory_context",
    "provider",
    "query_scope",
    "memory_ids",
    "document_refs",
    "stale_or_conflicting",
    "memory_projection",
    "prototype_refs",
)

SHARED_AUTHORITY_SOURCES = (
    "platforms/shared/skills/xy-project-memory/SKILL.md",
    "platforms/shared/skills/xy-qa-review/SKILL.md",
    "platforms/shared/skills/xy-workflow/SKILL.md",
)


def assert_current_authority_wins(test: unittest.TestCase, body: str) -> None:
    normalized = " ".join(body.split()).casefold()
    test.assertIn(PRECEDENCE.casefold(), normalized)
    for inversion in (
        "recalled memory overrides the page contract",
        "recalled memory overrides controlled documents",
        "memory wins over controlled documents",
        "memory may change approval state",
    ):
        test.assertNotIn(inversion, normalized)


class SharedMemoryContractTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return read_contract(PACK / relative)

    def test_shared_sources_define_one_memory_contract(self) -> None:
        paths = (
            "platforms/shared/skills/xy-project-memory/SKILL.md",
            "platforms/shared/skills/xy-qa-review/SKILL.md",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        )
        body = "\n".join(self.read(relative) for relative in paths)
        self.assertIn(PRECEDENCE, body)
        for field in FIELDS:
            self.assertIn(field, body)
        self.assertNotIn("localhost:3111", body)
        self.assertNotIn("/Users/", body)

    def test_shared_skills_do_not_treat_memory_as_an_equal_authority_layer(self) -> None:
        body = "\n".join(
            self.read(relative)
            for relative in (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "platforms/shared/skills/xy-workflow/SKILL.md",
            )
        ).lower()
        for stale in (
            "three-layer memory",
            "three layers",
            "independent equal layers",
            "semantic memory stub",
        ):
            self.assertNotIn(stale, body)
        self.assertIn("docs-fallback", body)
        self.assertIn("memory_smart_search", body)
        self.assertIn("memory_save", body)

    def test_claude_check_has_no_hidden_traceback_in_a_temp_fixture(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-workflow-claude-check-") as temp:
            project = Path(temp) / "Project"
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
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "project_id: replace-with-unique-project-id",
                    "project_id: claudecontractfixture",
                ),
                encoding="utf-8",
            )
            setup = subprocess.run(
                ["bash", "agent_workflow/setup_claude.sh"],
                cwd=project,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
            check = subprocess.run(
                ["bash", "agent_workflow/setup_claude.sh", "--check"],
                cwd=project,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertNotIn("Traceback", check.stdout + check.stderr)

    def test_shared_skills_keep_memory_below_pages_and_controlled_docs(self) -> None:
        for relative in SHARED_AUTHORITY_SOURCES:
            with self.subTest(relative=relative):
                assert_current_authority_wins(self, self.read(relative))

    def test_authority_inversion_mutations_are_rejected(self) -> None:
        body = self.read("platforms/shared/skills/xy-project-memory/SKILL.md")
        mutations = (
            body
            + "\nRecalled memory overrides the page contract when it is newer.\n",
            body
            + "\nRecalled memory overrides controlled documents under time pressure.\n",
            body + "\nMemory wins over controlled documents during closeout.\n",
            body + "\nMemory may change approval state after QA.\n",
            body.replace(
                PRECEDENCE,
                "Recalled memory overrides controlled documents and explicit user approvals.",
                1,
            ),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                with self.assertRaises(AssertionError):
                    assert_current_authority_wins(self, mutation)

    def test_memory_closeout_projects_page_references_without_approval_authority(self) -> None:
        body = self.read("platforms/shared/skills/xy-project-memory/SKILL.md")
        normalized = " ".join(body.split())
        self.assertIn("prototype_refs:", normalized)
        self.assertIn("only when concrete page references actually changed", normalized)
        self.assertIn("approval remains in workflow task state", normalized.casefold())
        # 新模型必须把 PROJECT/feature 当成 QA 后的当前事实，不能退回 STATUS 流水账。
        self.assertIn("`docs.project` and active feature documents", normalized)
        self.assertIn("integrated QA returns PASS", normalized)
        self.assertIn("<feature>.removed.md", normalized)
        projection = body.split("memory_projection:", 1)[1].split("```", 1)[0]
        fields = {
            line.strip().split(":", 1)[0]
            for line in projection.splitlines()
            if line.startswith("    ") and ":" in line
        }
        self.assertEqual(
            {
                "memories_saved",
                "project_updated",
                "features_updated",
                "features_removed",
                "plans_updated",
                "prototype_refs",
                "fallback_note",
            },
            fields,
        )


if __name__ == "__main__":
    unittest.main()
