from __future__ import annotations

import shutil
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.skill_contract_helpers import read_contract, contract_file_containing


# 子进程沿用当前受支持的测试解释器，不重新落回系统自带的旧 python3。
PACK = Path(__file__).resolve().parents[1]
MANAGED_SKILL_MARKER = "<!-- agent-workflow-pack:managed-skill -->"
MANAGED_AGENT_MARKER = "<!-- agent-workflow-pack:managed-agent -->"
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
def claude_agent_name(role: str) -> str:
    return role.replace("_", "-")


def managed_claude_block(body: str) -> str:
    start = body.index(CLAUDE_BEGIN)
    end = body.index(CLAUDE_END, start) + len(CLAUDE_END)
    return body[start:end]


class ClaudeFixtureMixin:
    @staticmethod
    def write_project_files(project: Path, files: dict[str, str]) -> None:
        for relative, body in files.items():
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    def make_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temp = tempfile.TemporaryDirectory(prefix="agent-workflow-claude-")
        project = Path(temp.name) / "Project"
        pack = project / "agent_workflow"
        project.mkdir()
        shutil.copytree(
            PACK,
            pack,
            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
            symlinks=True,
        )
        shutil.copy2(pack / "templates/project.yaml.example", pack / "project.yaml")
        self.replace_config(
            pack,
            "project_id: replace-with-unique-project-id",
            "project_id: claude-workflow-fixture",
        )
        self.write_project_files(
            project,
            {
                "apps/web/package.json": (
                    '{"dependencies":{"react":"19"},'
                    '"scripts":{"test":"vitest","build":"vite build"}}'
                ),
                "apps/desktop/package.json": (
                    '{"main":"main.js","dependencies":{"electron":"40"},'
                    '"scripts":{"test":"vitest","package":"electron-builder"}}'
                ),
                "apps/desktop/main.js": "export {};\n",
                "services/api/pyproject.toml": (
                    '[project]\nname="api"\nversion="1"\n'
                    'dependencies=["pytest"]\n'
                ),
                "services/api/uv.lock": "version = 1\n",
                "apps/apple/App.xcodeproj/project.pbxproj": (
                    "// !$*UTF8*$!\n{\nobjects = {\n"
                    "A1 = { isa = PBXNativeTarget; "
                    'productType = "com.apple.product-type.application"; };\n'
                    "};\n}\n"
                ),
                "apps/android/build.gradle.kts": (
                    'plugins { id("com.android.application") version "9.0.0" }\n'
                ),
                "apps/android/src/main/AndroidManifest.xml": (
                    '<manifest package="example.fixture"/>\n'
                ),
            },
        )
        return temp, project, pack

    def replace_config(self, pack: Path, old: str, new: str) -> None:
        config = pack / "project.yaml"
        body = config.read_text(encoding="utf-8")
        self.assertIn(old, body)
        config.write_text(body.replace(old, new, 1), encoding="utf-8")

    def run_setup(
        self, project: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "agent_workflow/setup_claude.sh", *args],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_validator(
        self, project: Path, pack: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "agent_workflow/lib/validate_claude_artifacts.py",
                "generated",
                str(pack),
                str(project),
            ],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )


class ClaudePrewriteValidationTest(ClaudeFixtureMixin, unittest.TestCase):
    def test_preflight_uses_shared_project_profile_preview_without_project_writes(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)

        result = self.run_setup(project, "--preflight")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ProjectProfile preview", result.stdout)
        self.assertIn("apps/desktop -> xy-desktop", result.stdout)
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_setup_rejects_a_hardcoded_routine_extra_confirmation_before_writes(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        workflow = pack / "product/WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            + "\nThe PM must obtain document approval from the user before implementation.\n",
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_setup_initializes_placeholder_project_id_before_project_outputs(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        self.replace_config(
            pack,
            "project_id: claude-workflow-fixture",
            "project_id: replace-with-unique-project-id",
        )

        result = self.run_setup(project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "project_id: project",
            (pack / "project.yaml").read_text(encoding="utf-8"),
        )
        self.assertTrue((project / "AGENTS.md").is_file())
        self.assertTrue((project / ".claude").is_dir())
        self.assertTrue((project / "docs").is_dir())

    def test_setup_rejects_escaping_role_read_before_any_project_write(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        config = pack / "project.yaml"
        config.write_text(
            config.read_text(encoding="utf-8")
            + "\nrole_reads:\n  xy-web:\n    - ../outside.md\n",
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "unsupported retired top-level key: role_reads",
            result.stdout + result.stderr,
        )
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / ".claude").exists())
        self.assertFalse((project / "docs").exists())

    def test_check_revalidates_project_config(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        setup = self.run_setup(project)
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        self.replace_config(
            pack,
            "project_id: claude-workflow-fixture",
            "project_id: Invalid Project ID",
        )

        result = self.run_setup(project, "--check")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("project_id must be a stable lowercase slug", result.stdout + result.stderr)

    def test_setup_rejects_claude_output_symlink_before_any_write(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        outside = Path(temp.name) / "outside-claude"
        outside.mkdir()
        (project / ".claude").symlink_to(outside, target_is_directory=True)

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("managed output", (result.stdout + result.stderr).lower())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_setup_rejects_agent_target_directory_before_any_write(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        collision = project / ".claude/agents/xy-web.md"
        collision.mkdir(parents=True)
        sentinel = collision / "keep.txt"
        sentinel.write_text("user owned\n", encoding="utf-8")

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("managed output", (result.stdout + result.stderr).lower())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user owned\n")
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())


class ClaudeSourceContractTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return read_contract(PACK / relative)

    def test_seven_core_skills_exist_with_managed_frontmatter(self) -> None:
        for name in CORE_SKILLS:
            with self.subTest(skill=name):
                path = PACK / "platforms/shared/skills" / name / "SKILL.md"
                self.assertTrue(path.is_file(), path)
                body = path.read_text(encoding="utf-8")
                self.assertTrue(body.startswith("---\n"))
                self.assertGreaterEqual(body.count("\n---\n"), 1)
                self.assertIn(f"name: {name}", body)
                self.assertIn(MANAGED_SKILL_MARKER, body)
                self.assertFalse(
                    (PACK / "platforms/claude/skills" / name / "SKILL.md").exists()
                )

    def test_canonical_role_ids_use_hyphens_for_both_hosts(self) -> None:
        expected = set(CANONICAL_ROLES)
        role_dir = PACK / "roles"
        self.assertEqual({path.stem for path in role_dir.glob("xy-*.md")}, expected)
        self.assertEqual(list(role_dir.glob("xy_*.md")), [])
        for role in expected:
            with self.subTest(role=role):
                body = (role_dir / f"{role}.md").read_text(encoding="utf-8")
                self.assertIn(f"name: {role}\n", body)
        for relative in (
            "project.yaml",
            "templates/project.yaml.example",
            "product/ROLES.yaml",
            "platforms/shared/AGENTS.product.tpl",
            "platforms/shared/skills/xy-workflow/SKILL.md",
        ):
            body = self.read(relative)
            for legacy in expected:
                with self.subTest(file=relative, legacy=legacy):
                    self.assertNotIn(legacy.replace("-", "_"), body)

    def test_workflow_uses_strict_memory_and_native_skill_contracts(self) -> None:
        body = self.read("platforms/shared/skills/xy-workflow/SKILL.md")
        for token in (
            "xy-project-memory",
            "fallback_reason",
            "project_id",
            "filter_enforced",
            "capability_evidence",
            "provenance_refs",
            "skill_policy",
            "required_skills",
            "audit_surfaces",
            "grill-me",
            "ui-ux-pro-max",
            "xy-prototype-verify",
            "xy-build-verify",
            "xy-qa-review",
            "Claude Auto Memory",
        ):
            with self.subTest(token=token):
                self.assertIn(token, body)
        self.assertNotIn("Agent(", body)

    def test_workflow_assesses_commit_and_closes_memory_before_final_user_report(self) -> None:
        body = self.read("platforms/shared/skills/xy-workflow/SKILL.md")
        qa = body.find("QA PASS")
        closeout = body.find("xy-project-memory", qa + 1)
        commit = body.find("perform the PM commit assessment above", closeout + 1)
        report = body.find("report to the user", commit + 1)
        self.assertNotEqual(qa, -1)
        self.assertNotEqual(closeout, -1)
        self.assertNotEqual(commit, -1)
        self.assertNotEqual(report, -1)
        self.assertLess(qa, closeout)
        self.assertLess(closeout, commit)
        self.assertLess(commit, report)

    def test_shared_workflow_uses_dynamic_ready_queue_and_request_level_qa(self) -> None:
        body = " ".join(self.read("platforms/shared/skills/xy-workflow/SKILL.md").lower().split())
        for phrase in (
            "build a dag",
            "dispatch all currently ready independent tasks",
            "re-evaluate downstream readiness after each completion",
            "capacity delay",
            "request dependency closure",
            "unrelated project work",
            "exactly one integrated read-only `xy-qa` reviewer",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_claude_sources_use_two_default_business_confirmation_stages(self) -> None:
        workflow = self.read("product/WORKFLOW.md")
        schema = self.read("product/AGENT_SCHEMA.md")
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
        active_sources = "\n".join(
            (
                self.read("platforms/shared/AGENTS.product.tpl"),
                self.read("platforms/shared/skills/xy-workflow/SKILL.md"),
                self.read("platforms/shared/skills/xy-prototype-verify/SKILL.md"),
                self.read("platforms/claude/AGENTS.claude.tpl"),
                self.read("roles/xy-uiux.md"),
            )
        )
        self.assertIn("additional_business_confirmation:", workflow + schema + active_sources)
        for phrase in ("requirements_approved", "visual_approved", "Platform security prompts"):
            self.assertIn(phrase, active_sources)
        for forbidden in ("Baseline Proceed", "IA Proceed", "Plan Proceed"):
            self.assertNotIn(forbidden, active_sources)

    def test_claude_template_is_thin_and_uses_only_the_main_entry(self) -> None:
        body = self.read("platforms/claude/AGENTS.claude.tpl")
        self.assertIn("/xy-workflow", body)
        self.assertIn("READY DAG", body)
        self.assertIn("Superpowers is disabled by default", body)
        self.assertIn("exactly one `xy-qa` reviewer", body)
        self.assertIn("installed-code-review-skill", body)
        self.assertIn("internal-xy-qa-procedure", body)
        self.assertIn("requesting-code-review/code-reviewer.md", body)
        self.assertNotIn("{{SCOPE_TABLE}}", body)
        self.assertNotIn("## Generated role scopes", body)

    def test_claude_template_treats_auto_memory_as_untrusted(self) -> None:
        body = self.read("platforms/claude/AGENTS.claude.tpl")
        normalized = " ".join(body.split())
        for token in (
            "Claude Auto Memory",
            "untrusted",
            "Current controlled documents and explicit user approvals win over recalled memory.",
        ):
            with self.subTest(token=token):
                self.assertIn(token, normalized)

    def test_claude_runtime_consumes_project_profile_without_manual_workspace_keys(self) -> None:
        setup = self.read("setup_claude.sh")
        validator = self.read("lib/validate_claude_artifacts.py")
        self.assertIn("project_profile_cli.py", setup)
        self.assertNotIn("from validate_project_config import validate_with_profile", setup)
        self.assertIn("validate_with_profile", validator)
        for body in (setup, validator):
            self.assertNotIn("project_sandboxes", body)
            self.assertNotRegex(body, r"py_yaml .*enabled_roles")
        self.assertNotIn("def enabled_roles(", validator)
        template = self.read("platforms/claude/AGENTS.claude.tpl")
        self.assertIn("ProjectProfile", template)
        self.assertIn("task pack", template)
        self.assertNotIn("generated ProjectProfile context", template)

    def test_claude_runtime_has_no_named_retirement_compatibility(self) -> None:
        runtime = "\n".join(
            (
                self.read("setup_claude.sh"),
                self.read("lib/validate_claude_artifacts.py"),
            )
        )
        self.assertNotIn("RETIRED_", runtime)
        self.assertNotIn("retired_claude", runtime.lower())

    def test_claude_native_policy_keeps_external_workflows_bounded(self) -> None:
        body = " ".join(self.read("platforms/claude/AGENTS.claude.tpl").split())
        for phrase in (
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
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)


class ClaudeGeneratedAgentTest(ClaudeFixtureMixin, unittest.TestCase):
    def generated_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temp, project, pack = self.make_fixture()
        result = self.run_setup(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return temp, project, pack

    def read_agent(self, project: Path, role: str) -> str:
        return (
            project / ".claude/agents" / f"{claude_agent_name(role)}.md"
        ).read_text(encoding="utf-8")

    def test_fresh_project_installs_exactly_the_seven_shared_core_skills(self) -> None:
        temp, project, _ = self.generated_fixture()
        self.addCleanup(temp.cleanup)
        installed = {
            path.parent.name
            for path in (project / ".claude/skills").glob("*/SKILL.md")
        }
        self.assertEqual(installed, set(CORE_SKILLS))

    def test_setup_generates_only_roles_enabled_by_the_discovered_profile(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        for path in (
            project / "apps/web",
            project / "apps/desktop",
            project / "apps/apple",
            project / "apps/android",
        ):
            shutil.rmtree(path)
        result = self.run_setup(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        generated = {path.stem for path in (project / ".claude/agents").glob("xy-*.md")}
        self.assertEqual(generated, {"xy-backend", "xy-qa", "xy-uiux"})
    def test_workspace_override_enables_backend_without_a_language_manifest(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        for path in (project / "apps", project / "services"):
            shutil.rmtree(path)
        (project / "engine").mkdir()
        config = pack / "project.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "workspace_overrides: {}",
                "workspace_overrides:\n  include:\n    engine: xy-backend",
                1,
            ),
            encoding="utf-8",
        )
        result = self.run_setup(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        generated = {path.stem for path in (project / ".claude/agents").glob("xy-*.md")}
        self.assertEqual(generated, {"xy-backend", "xy-qa", "xy-uiux"})
        backend = self.read_agent(project, "xy-backend")
        self.assertIn("## PM task-pack boundary (generated)", backend)
        self.assertNotIn("`engine`", backend)
        self.assertNotIn("override:explicit-role", backend)

    def test_generated_agents_keep_discovery_in_the_pm_task_pack(self) -> None:
        temp, project, _ = self.generated_fixture()
        self.addCleanup(temp.cleanup)
        for role in CANONICAL_ROLES:
            body = self.read_agent(project, role)
            with self.subTest(role=role):
                self.assertIn("## PM task-pack boundary (generated)", body)
                self.assertIn("ProjectProfile routing evidence", body)
                self.assertIn("exact `owned_paths`", body)
                self.assertIn("controlled_document_access", body)
                self.assertNotIn("## Required reads (generated)", body)
                self.assertNotIn("## Discovered repository context (generated)", body)
                self.assertNotIn("## Global mandatory constraints", body)
                self.assertNotIn("qa_review_policy:", body)
        combined = "\n".join(self.read_agent(project, role) for role in CANONICAL_ROLES)
        for duplicated_fact in (
            "framework:react",
            "desktop:electron",
            "language:python",
            "npm run package",
            "uv run pytest",
        ):
            self.assertNotIn(duplicated_fact, combined)

    def test_validator_has_no_arbitrary_word_or_byte_budget(self) -> None:
        # 官方建议是具体、简洁、结构化，而不是 650 词/6KB 之类的安装硬门槛。
        validator = (PACK / "lib/validate_claude_artifacts.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("CLAUDE_MANAGED_LIMITS", validator)
        self.assertNotIn("CLAUDE_AGENT_LIMITS", validator)
        self.assertNotIn("word budget", validator)
        self.assertNotIn("byte budget", validator)

    def test_many_modules_do_not_expand_static_claude_context(self) -> None:
        temp, project, pack = self.generated_fixture()
        self.addCleanup(temp.cleanup)
        baseline_agent = self.read_agent(project, "xy-web")
        baseline_block = managed_claude_block(
            (project / "AGENTS.md").read_text(encoding="utf-8")
        )
        for index in range(24):
            module = project / f"packages/site-{index:02d}"
            module.mkdir(parents=True)
            (module / "package.json").write_text(
                '{"dependencies":{"react":"19"},"scripts":{"build":"vite build"}}',
                encoding="utf-8",
            )

        result = self.run_setup(project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_agent(project, "xy-web"), baseline_agent)
        self.assertEqual(
            managed_claude_block((project / "AGENTS.md").read_text(encoding="utf-8")),
            baseline_block,
        )

    def test_generated_roster_is_the_six_discoverable_workers_plus_qa(self) -> None:
        temp, project, _ = self.generated_fixture()
        self.addCleanup(temp.cleanup)
        generated = {path.stem for path in (project / ".claude/agents").glob("xy-*.md")}
        self.assertEqual(generated, set(CANONICAL_ROLES))

    def test_generated_host_artifacts_expose_the_latest_ui_contract(self) -> None:
        temp, project, _ = self.generated_fixture()
        self.addCleanup(temp.cleanup)
        # 原型细则已按需加载；断言完整契约，不要求宿主入口重复整份正文。
        from tests.skill_contract_helpers import read_bootstrap_contract
        bootstrap = read_bootstrap_contract(project / "AGENTS.md", project / "agent_workflow")
        uiux = self.read_agent(project, "xy-uiux")
        web = self.read_agent(project, "xy-web")
        qa = self.read_agent(project, "xy-qa")

        for token in (
            "/xy-workflow",
            "Agent(xy-*)",
            "/xy-prototype-verify",
            "visual_approved",
        ):
            with self.subTest(artifact="AGENTS.md", token=token):
                self.assertIn(token, bootstrap)
        for token in (
            "Page design and interaction contract",
            "direct link to each concrete changed page",
            "dependency fingerprint",
            # Claude 生成物也必须保持与 Codex 相同的原型浏览器边界和合同审核责任。
            "Prototype verification MUST NOT invoke Computer Use or browser automation by default",
            # 换行属于 Markdown 排版细节；分别验证“冻结状态”和“批准需求”才能锁定真正语义。
            "frozen",
            "approved requirements and acceptance criteria",
            "semantic conformance review, not browser automation",
        ):
            with self.subTest(artifact="xy-uiux", token=token):
                self.assertIn(token, uiux)
        for token in ("production components", "mock data", "prototype-only"):
            with self.subTest(artifact="xy-web", token=token):
                self.assertIn(token, web)
        self.assertIn("PASS | FAIL", qa)
        self.assertIn("MUST NOT invoke Computer Use or browser automation", qa)
        self.assertIn("real production implementation", qa)

        combined = "\n".join((bootstrap, uiux, web, qa)).lower()
        for forbidden in (
            "screenshot fallback",
            "screenshot approval",
            "manifest is required",
            "task design markdown is required",
            "copy prototype-only mock data into production",
            "pass | warn | fail",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)

    def test_agents_have_managed_valid_frontmatter_and_skill_tool(self) -> None:
        temp, project, pack = self.generated_fixture()
        self.addCleanup(temp.cleanup)
        roles = CANONICAL_ROLES
        for role in roles:
            with self.subTest(role=role):
                body = self.read_agent(project, role)
                self.assertTrue(body.startswith("---\n"))
                self.assertGreaterEqual(body.count("\n---\n"), 1)
                self.assertIn(f"name: {claude_agent_name(role)}\n", body)
                self.assertIn(MANAGED_AGENT_MARKER, body)
                tools = next(line for line in body.splitlines() if line.startswith("tools:"))
                self.assertIn("Skill", tools)
                self.assertIn("disallowedTools: Agent", body)
                self.assertIn("permissionMode: default", body)
                self.assertNotIn("permissionMode: acceptEdits", body)
                color = next(
                    line.split(":", 1)[1].strip()
                    for line in body.splitlines()
                    if line.startswith("color:")
                )
                self.assertIn(
                    color,
                    {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"},
                )

    def test_role_hard_skills_are_preloaded_and_invoked(self) -> None:
        temp, project, _ = self.generated_fixture()
        self.addCleanup(temp.cleanup)

        web = self.read_agent(project, "xy-web")
        self.assertIn("  - xy-build-verify", web)
        self.assertIn("/xy-build-verify", web)

        uiux = self.read_agent(project, "xy-uiux")
        self.assertIn("  - ui-ux-pro-max", uiux)
        self.assertIn("  - xy-prototype-verify", uiux)
        self.assertIn("/xy-prototype-verify", uiux)

        qa = self.read_agent(project, "xy-qa")
        self.assertIn("  - xy-qa-review", qa)
        self.assertIn("/xy-qa-review", qa)
        self.assertIn("audit_surfaces", qa)
        self.assertNotIn("let Codex match", qa)

    def test_generated_project_skill_references_resolve(self) -> None:
        temp, project, _ = self.generated_fixture()
        self.addCleanup(temp.cleanup)
        for path in sorted((project / ".claude/agents").glob("xy-*.md")):
            body = path.read_text(encoding="utf-8")
            in_skills = False
            for line in body.splitlines():
                if line == "skills:":
                    in_skills = True
                    continue
                if in_skills and line.startswith("  - "):
                    name = line[4:]
                    if name.startswith("xy-"):
                        self.assertTrue(
                            (project / ".claude/skills" / name / "SKILL.md").is_file(),
                            f"{path.name} has unresolved project Skill {name}",
                        )
                    continue
                if in_skills:
                    in_skills = False

    def test_required_read_inline_comment_is_not_injected(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        self.replace_config(
            pack,
            "  standards_root: docs/standards/",
            "  standards_root: docs/standards/ # current rules root",
        )
        result = self.run_setup(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        body = self.read_agent(project, "xy-web")
        # docs.* 只是 PM 构造 task-scoped 读取计划的索引，不能重新注入静态角色正文。
        self.assertNotIn("`docs/standards/`", body)
        self.assertNotIn("docs/standards/ #", body)

    def test_ui_agent_uses_configured_design_path_contract(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        config = pack / "project.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "docs/standards/", "docs/product-standards/"
            ),
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        body = self.read_agent(project, "xy-uiux")
        self.assertIn("`docs.standards_root/DESIGN_*.md`", body)
        self.assertIn("standards_only", body)
        self.assertIn("## PM task-pack boundary (generated)", body)
        self.assertIn("exact `owned_paths`", body)
        self.assertNotIn("`docs/product-standards/`", body)


class ClaudeOwnershipTest(ClaudeFixtureMixin, unittest.TestCase):
    def test_setup_creates_only_assist_hooks_when_settings_absent(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)

        result = self.run_setup(project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        settings = json.loads((project / ".claude/settings.json").read_text())
        self.assertEqual({"hooks"}, set(settings))
        self.assertEqual({"SessionStart", "UserPromptSubmit", "PreToolUse"}, set(settings["hooks"]))

    def test_setup_preserves_user_setting_values_and_custom_hook_bytes(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        settings = project / ".claude/settings.json"
        hook = project / ".claude/hooks/custom-check.sh"
        hook.parent.mkdir(parents=True)
        settings.write_bytes(b'{"autoMemoryEnabled":true,"custom":"keep"}\n')
        hook.write_bytes(b"#!/usr/bin/env bash\nprintf 'keep-me\\n'\n")
        before_settings = settings.read_bytes()
        before_hook = hook.read_bytes()

        result = self.run_setup(project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        generated = json.loads(settings.read_bytes())
        generated.pop("hooks")
        self.assertEqual(generated, json.loads(before_settings))
        self.assertEqual(hook.read_bytes(), before_hook)

    def test_setup_preserves_existing_agents_md_mode(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        target = project / "AGENTS.md"
        target.write_text("user-owned preface\n", encoding="utf-8")
        target.chmod(0o640)

        result = self.run_setup(project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)

    def test_unknown_symlinked_skill_is_never_scanned_or_deleted(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        outside = Path(temp.name) / "outside-skill"
        outside.mkdir()
        external_skill = outside / "SKILL.md"
        original = MANAGED_SKILL_MARKER + "\nexternal user content\n"
        external_skill.write_text(original, encoding="utf-8")
        skill_root = project / ".claude/skills"
        skill_root.mkdir(parents=True)
        link = skill_root / "xy-obsolete"
        link.symlink_to(outside, target_is_directory=True)

        result = self.run_setup(project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertEqual(external_skill.read_text(encoding="utf-8"), original)
        check = self.run_setup(project, "--check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_user_owned_same_name_skill_blocks_without_overwrite(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        target = project / ".claude/skills/xy-workflow/SKILL.md"
        target.parent.mkdir(parents=True)
        original = b"---\nname: xy-workflow\ndescription: user workflow\n---\nuser owned\n"
        target.write_bytes(original)

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("xy-workflow", result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse((project / "AGENTS.md").exists())

    def test_user_owned_same_name_agent_blocks_without_overwrite(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        target = project / ".claude/agents/xy-web.md"
        target.parent.mkdir(parents=True)
        original = (
            b"---\nname: xy-web\ndescription: user agent\n---\n"
            b"## Global mandatory constraints\ndeveloper instructions by user\n"
        )
        target.write_bytes(original)

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("xy-web", result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse((project / "AGENTS.md").exists())

    def test_user_owned_underscore_agent_blocks_hyphen_migration(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        legacy_path = project / ".claude/agents/xy_web.md"
        legacy_path.parent.mkdir(parents=True)
        original = b"---\nname: xy_web\ndescription: user legacy agent\n---\nuser owned\n"
        legacy_path.write_bytes(original)

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("xy_web.md", result.stdout + result.stderr)
        self.assertEqual(legacy_path.read_bytes(), original)
        self.assertFalse((project / ".claude/agents/xy-web.md").exists())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_noncanonical_underscore_agent_fails_without_compatibility_migration(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        legacy = project / ".claude/agents/xy_web.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(
            "---\nname: xy_web\ndescription: legacy pack agent\n---\n\n"
            + MANAGED_AGENT_MARKER
            + "\n",
            encoding="utf-8",
        )

        original = legacy.read_bytes()
        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(legacy.read_bytes(), original)
        self.assertFalse((project / ".claude/agents/xy-web.md").exists())
        self.assertFalse((project / "AGENTS.md").exists())

    def test_markerless_exact_pack_outputs_fail_fast_without_compatibility_adoption(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        first = self.run_setup(project)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        skill = project / ".claude/skills/xy-workflow/SKILL.md"
        agent = project / ".claude/agents/xy-web.md"
        skill.write_text(
            skill.read_text(encoding="utf-8").replace(MANAGED_SKILL_MARKER + "\n\n", "", 1),
            encoding="utf-8",
        )
        agent.write_text(
            agent.read_text(encoding="utf-8").replace(MANAGED_AGENT_MARKER + "\n\n", "", 1),
            encoding="utf-8",
        )
        skill_before = skill.read_bytes()
        agent_before = agent.read_bytes()

        second = self.run_setup(project)

        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(skill.read_bytes(), skill_before)
        self.assertEqual(agent.read_bytes(), agent_before)

    def test_stale_managed_outputs_are_removed_but_user_files_remain(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        first = self.run_setup(project)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        stale_agent = project / ".claude/agents/xy-obsolete.md"
        user_skill = project / ".claude/skills/user-helper/SKILL.md"
        user_skill.parent.mkdir(parents=True)
        stale_agent.write_text(
            "---\n"
            "name: xy-obsolete\n"
            "description: Strictly managed stale Agent.\n"
            "---\n\n"
            + MANAGED_AGENT_MARKER
            + "\n",
            encoding="utf-8",
        )
        user_skill.write_text("user owned\n", encoding="utf-8")

        second = self.run_setup(project)

        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertFalse(stale_agent.exists())
        self.assertTrue(user_skill.exists())

    def test_malformed_claude_markers_fail_without_truncation(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        target = project / "AGENTS.md"
        original = f"user-before\n{CLAUDE_END}\n{CLAUDE_BEGIN}\nuser-after\n"
        target.write_text(original, encoding="utf-8")

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertFalse((project / ".claude").exists())


class ClaudeThinEntryTest(ClaudeFixtureMixin, unittest.TestCase):
    def test_direct_validator_and_check_reject_missing_shared_bootstrap_without_writes(self) -> None:
        """共享边界必须实际存在于入口，详细源契约完整不能掩盖生成物遗漏。"""
        from lib.claude_instructions import replace_block
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        installed = self.run_setup(project)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        agents = project / "AGENTS.md"
        broken = replace_block(agents.read_bytes(), "<!-- pack:product-begin -->", b"")
        agents.write_bytes(broken)
        for result in (self.run_validator(project, pack), self.run_setup(project, "--check")):
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(agents.read_bytes(), broken)

    def test_direct_validator_rejects_a_remaining_legacy_entry(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        installed = self.run_setup(project)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        legacy = f"{CLAUDE_BEGIN}\nold\n{CLAUDE_END}\n"
        (project / "CLAUDE.md").write_text(legacy)
        result = self.run_validator(project, pack)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLAUDE.md must contain exactly @AGENTS.md", result.stdout + result.stderr)
        self.assertEqual((project / "CLAUDE.md").read_text(), legacy)

    def test_real_setup_rejects_old_managed_entry_without_migration(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        legacy = f"{CLAUDE_BEGIN}\n# Previous workflow\n{CLAUDE_END}\n".encode()
        (project / "CLAUDE.md").write_bytes(legacy)
        (project / "AGENTS.md").write_bytes("用户项目约束\n".encode())

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unsupported", result.stdout + result.stderr)
        self.assertEqual((project / "CLAUDE.md").read_bytes(), legacy)
        self.assertEqual((project / "AGENTS.md").read_bytes(), "用户项目约束\n".encode())
        self.assertFalse((project / ".claude").exists())

    def test_direct_validator_and_check_reject_missing_or_ineffective_import(self) -> None:
        """导入必须是实际指令，不接受空文件、普通提示、代码示例或重复正文。"""
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        installed = self.run_setup(project)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        entry = project / "CLAUDE.md"
        agents = (project / "AGENTS.md").read_bytes()
        for body in (None, b"", b"Read AGENTS.md\n", b"`@AGENTS.md`\n",
                     b"```\n@AGENTS.md\n```\n", b"@other/AGENTS.md\n", agents):
            with self.subTest(body=body):
                if body is None:
                    entry.unlink()
                else:
                    entry.write_bytes(body)
                for result in (self.run_validator(project, pack), self.run_setup(project, "--check")):
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(entry.read_bytes() if entry.exists() else None, body)
                self.assertEqual((project / "AGENTS.md").read_bytes(), agents)

    def test_user_legacy_content_stops_real_setup_before_docs_or_agents(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        original = f"用户自定义约束\n{CLAUDE_BEGIN}\nold\n{CLAUDE_END}\n".encode()
        (project / "CLAUDE.md").write_bytes(original)
        for arguments in (("--preflight",), ()):
            with self.subTest(arguments=arguments):
                result = self.run_setup(project, *arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("user-owned instructions", result.stdout + result.stderr)
                self.assertEqual((project / "CLAUDE.md").read_bytes(), original)
                for path in ("AGENTS.md", "docs", ".claude"):
                    self.assertFalse((project / path).exists())

    def test_direct_validator_rejects_linked_thin_entry(self) -> None:
        """独立校验和安装器保持同一文件安全边界，即使链接目标内容完全正确。"""
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        installed = self.run_setup(project)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        entry = project / "CLAUDE.md"
        outside = project.parent / "user-claude-entry.md"
        outside.write_bytes(b"@AGENTS.md\n")
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                entry.unlink()
                if kind == "symlink":
                    entry.symlink_to(outside)
                else:
                    entry.hardlink_to(outside)
                result = self.run_validator(project, pack)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("single-link regular file", result.stdout + result.stderr)
                self.assertEqual(outside.read_bytes(), b"@AGENTS.md\n")


class ClaudeCheckMutationTest(ClaudeFixtureMixin, unittest.TestCase):
    def setup_valid(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temp, project, pack = self.make_fixture()
        result = self.run_setup(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        check = self.run_setup(project, "--check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        return temp, project, pack

    def assert_check_rejects(self, project: Path) -> None:
        result = self.run_setup(project, "--check")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_rejects_skill_content_drift(self) -> None:
        temp, project, _ = self.setup_valid()
        self.addCleanup(temp.cleanup)
        target = project / ".claude/skills/xy-workflow/SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nextra drift\n", encoding="utf-8")
        self.assert_check_rejects(project)

    def test_shared_skill_auxiliary_tree_is_copied_and_checked(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        source = pack / "platforms/shared/skills/xy-workflow/references/guide.md"
        # 工作流已自带生命周期 reference；测试资源与正式资源共存。
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("shared auxiliary guide\n", encoding="utf-8")

        setup = self.run_setup(project)
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        target = project / ".claude/skills/xy-workflow/references/guide.md"
        self.assertEqual(source.read_bytes(), target.read_bytes())
        check = self.run_setup(project, "--check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

        target.write_text("tampered auxiliary guide\n", encoding="utf-8")
        self.assert_check_rejects(project)

    def test_check_rejects_agent_tool_drift(self) -> None:
        temp, project, _ = self.setup_valid()
        self.addCleanup(temp.cleanup)
        target = project / ".claude/agents/xy-web.md"
        body = target.read_text(encoding="utf-8")
        target.write_text(body.replace(", Skill", "", 1), encoding="utf-8")
        self.assert_check_rejects(project)

    def test_check_rejects_broken_skill_frontmatter(self) -> None:
        temp, project, _ = self.setup_valid()
        self.addCleanup(temp.cleanup)
        target = project / ".claude/skills/xy-qa-review/SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8").replace("\n---\n", "\n--broken--\n", 1),
            encoding="utf-8",
        )
        self.assert_check_rejects(project)

    def test_check_rejects_stale_managed_skill(self) -> None:
        temp, project, _ = self.setup_valid()
        self.addCleanup(temp.cleanup)
        target = project / ".claude/skills/xy-obsolete/SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text(MANAGED_SKILL_MARKER + "\nstale\n", encoding="utf-8")
        self.assert_check_rejects(project)

    def test_check_rejects_synchronized_obsolete_ui_semantics(self) -> None:
        mutations = (
            (
                "roles/xy-uiux.md",
                "The PM MUST provide a direct link to each concrete changed page;",
                "The PM may provide only the root index; it is sufficient for approval.",
            ),
            (
                "roles/xy-uiux.md",
                "The visual workflow MUST NOT generate, persist, attach, or present screenshots.",
                "Use a screenshot fallback when the concrete page cannot be linked.",
            ),
            (
                "roles/xy-uiux.md",
                "The role must not create a Manifest and must not create companion design, mapping, QA, baseline,",
                "- task design Markdown is required for every prototype;",
            ),
            (
                "roles/xy-web.md",
                "Do not copy prototype-only mock data, fake APIs",
                "Copy prototype-only mock data, fake APIs",
            ),
            (
                "roles/xy-qa.md",
                "[Audit result] PASS | FAIL",
                "[Audit result] PASS | WARN | FAIL",
            ),
        )
        for relative, old, new in mutations:
            with self.subTest(relative=relative, mutation=new):
                temp, project, pack = self.setup_valid()
                self.addCleanup(temp.cleanup)
                source = pack / relative
                source_body = source.read_text(encoding="utf-8")
                self.assertIn(old, source_body)
                source.write_text(source_body.replace(old, new, 1), encoding="utf-8")

                role = source.stem
                generated = project / ".claude/agents" / f"{role}.md"
                generated_body = generated.read_text(encoding="utf-8")
                self.assertIn(old, generated_body)
                generated.write_text(
                    generated_body.replace(old, new, 1), encoding="utf-8"
                )

                self.assert_check_rejects(project)

    def test_check_rejects_a_synchronized_missing_prototype_verifier(self) -> None:
        temp, project, pack = self.setup_valid()
        self.addCleanup(temp.cleanup)
        # 原生原型调用属于按需细则；受管运行时即是安装后使用的唯一源。
        source = pack / "platforms/claude/references/pm-integration.md"
        old = "/xy-prototype-verify"
        new = "/xy-workflow"
        self.assertIn(old, source.read_text(encoding="utf-8"))
        source.write_text(
            source.read_text(encoding="utf-8").replace(old, new, 1),
            encoding="utf-8",
        )

        self.assert_check_rejects(project)

    def test_setup_rejects_source_authority_inversion_before_writes(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        source = pack / "platforms/shared/skills/xy-workflow/SKILL.md"
        source.write_text(
            source.read_text(encoding="utf-8")
            + "\nRecalled memory overrides current controlled documents.\n",
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("memory", (result.stdout + result.stderr).lower())
        self.assertFalse((project / "AGENTS.md").exists())

    def test_setup_rejects_dynamic_scheduler_contract_drift_before_writes(self) -> None:
        mutations = (
            ("Dispatch all currently ready independent tasks", "Dispatch one task at a time"),
            ("Do not wait for unrelated tasks", "Wait for all project work"),
            ("independent branches continue.", "independent branches wait."),
            (
                "dispatch exactly one integrated read-only `xy-qa` reviewer",
                "dispatch module QA for every task",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                temp, project, pack = self.make_fixture()
                self.addCleanup(temp.cleanup)
                source = pack / "platforms/shared/skills/xy-workflow/SKILL.md"
                source = contract_file_containing(source, old)
                body = source.read_text(encoding="utf-8")
                self.assertIn(old, body)
                source.write_text(body.replace(old, new, 1), encoding="utf-8")

                result = self.run_setup(project)

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((project / "AGENTS.md").exists())

    def test_setup_rejects_invalid_skill_frontmatter_before_writes(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        source = pack / "platforms/shared/skills/xy-project-memory/SKILL.md"
        body = source.read_text(encoding="utf-8")
        description = next(
            line for line in body.splitlines() if line.startswith("description: ")
        )
        source.write_text(
            body.replace(
                description,
                f"this is not valid yaml\n{description}",
                1,
            ),
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("frontmatter", (result.stdout + result.stderr).lower())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_setup_rejects_unterminated_frontmatter_quote_before_writes(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        source = pack / "platforms/shared/skills/xy-project-memory/SKILL.md"
        body = source.read_text(encoding="utf-8")
        description = next(
            line for line in body.splitlines() if line.startswith("description: ")
        )
        source.write_text(
            body.replace(
                description,
                'description: "unterminated project memory description',
                1,
            ),
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("description scalar", (result.stdout + result.stderr).lower())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_setup_rejects_invalid_plain_frontmatter_scalar_before_writes(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        source = pack / "platforms/shared/skills/xy-project-memory/SKILL.md"
        body = source.read_text(encoding="utf-8")
        description = next(
            line for line in body.splitlines() if line.startswith("description: ")
        )
        source.write_text(
            body.replace(
                description,
                "description: Run: real project memory workflow",
                1,
            ),
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("description scalar", (result.stdout + result.stderr).lower())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_setup_rejects_invalid_role_color_before_writes(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        metadata = pack / "product/ROLES.yaml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace(
                "claude_color: cyan", "claude_color: chartreuse", 1
            ),
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("claude_color", result.stdout + result.stderr)
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_setup_rejects_global_authority_inversion_before_writes(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        constraints = pack / "product/GLOBAL_CONSTRAINTS.md"
        constraints.write_text(
            constraints.read_text(encoding="utf-8")
            + "\nRecalled memory overrides current controlled documents.\n",
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("memory", (result.stdout + result.stderr).lower())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_setup_rejects_memory_fallback_bypass_before_writes(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        source = pack / "platforms/shared/skills/xy-project-memory/SKILL.md"
        source.write_text(
            source.read_text(encoding="utf-8")
            + "\nIf project isolation is unavailable, still call memory_recall and memory_save.\n",
            encoding="utf-8",
        )

        result = self.run_setup(project)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("memory", (result.stdout + result.stderr).lower())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / "docs").exists())

    def test_check_rejects_closeout_order_drift(self) -> None:
        temp, project, _ = self.setup_valid()
        self.addCleanup(temp.cleanup)
        target = project / ".claude/skills/xy-workflow/SKILL.md"
        target = contract_file_containing(target, "After QA PASS, activate `xy-project-memory` in closeout mode")
        body = target.read_text(encoding="utf-8")
        body = body.replace(
            "After QA PASS, activate `xy-project-memory` in closeout mode",
            "After QA PASS, report to the user, then activate `xy-project-memory` in closeout mode",
            1,
        )
        target.write_text(body, encoding="utf-8")
        self.assert_check_rejects(project)

    def test_setup_all_remains_cross_host_checkable(self) -> None:
        temp, project, _ = self.make_fixture()
        self.addCleanup(temp.cleanup)
        setup = subprocess.run(
            ["bash", "agent_workflow/setup_all.sh"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)

        check = subprocess.run(
            ["bash", "agent_workflow/setup_all.sh", "--check"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_setup_all_rejects_invalid_role_before_any_project_write(self) -> None:
        temp, project, pack = self.make_fixture()
        self.addCleanup(temp.cleanup)
        role = pack / "roles/xy-web.md"
        role.write_text(
            role.read_text(encoding="utf-8").replace("toolsets: [write]\n", "", 1),
            encoding="utf-8",
        )

        result = subprocess.run(
            ["bash", "agent_workflow/setup_all.sh"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((project / "CLAUDE.md").exists())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertFalse((project / ".claude").exists())
        self.assertFalse((project / ".codex").exists())
        self.assertFalse((project / ".agents").exists())
        self.assertFalse((project / "docs").exists())


class ClaudeDocumentationTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return read_contract(PACK / relative)

    def test_readme_documents_the_claude_native_runtime_contract(self) -> None:
        body = self.read("README.md")
        for phrase in (
            "Claude-native generated layout",
            "xy-project-memory",
            "agentmemory is optional",
            "Claude Auto Memory",
            "merges only signed assist Hook entries in `.claude/settings.json`",
            "`ui-ux-pro-max`",
            "matched on demand",
            "`claude doctor`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_hook_notes_keep_settings_and_auto_memory_user_owned(self) -> None:
        body = self.read("platforms/claude/hooks/README.md")
        for phrase in (
            "没有默认硬性写入禁令",
            ".claude/settings.json",
            "Claude Auto Memory",
            "非本包 Hook 都由用户管理",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_agent_schema_names_claude_hard_skill_contracts(self) -> None:
        body = self.read("product/AGENT_SCHEMA.md")
        for phrase in (
            "Skill tool",
            "xy-build-verify",
            "ui-ux-pro-max",
            "xy-prototype-verify",
            "xy-qa-review",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

if __name__ == "__main__":
    unittest.main()
