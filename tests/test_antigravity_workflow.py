from __future__ import annotations

import json
import importlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock
from tests.skill_contract_helpers import read_contract, read_bootstrap_contract, contract_file_containing


PACK = Path(__file__).resolve().parents[1]
SHARED_CORE_SKILLS = {
    "grill-me",
    "xy-build-verify",
    "xy-plan",
    "xy-project-memory",
    "xy-prototype-verify",
    "xy-qa-review",
    "xy-workflow",
}

PRODUCT_BEGIN = "<!-- pack:product-begin -->"
PRODUCT_END = "<!-- pack:product-end -->"
ANTIGRAVITY_BEGIN = "<!-- pack:antigravity-begin -->"
ANTIGRAVITY_END = "<!-- pack:antigravity-end -->"


def antigravity_managed_contribution(body: str) -> str:
    lines = body.splitlines(keepends=True)
    selected: list[str] = []
    active_end: str | None = None
    pairs = {
        PRODUCT_BEGIN: PRODUCT_END,
        ANTIGRAVITY_BEGIN: ANTIGRAVITY_END,
    }
    for line in lines:
        stripped = line.rstrip("\r\n")
        if active_end is None and stripped in pairs:
            active_end = pairs[stripped]
        if active_end is not None:
            selected.append(line)
            if stripped == active_end:
                active_end = None
    if active_end is not None:
        raise AssertionError("unterminated managed block in fixture")
    return "".join(selected)


class AntigravityFixtureMixin:
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="agent-workflow-antigravity-"
        )
        self.addCleanup(self.temporary.cleanup)

        self.project = Path(self.temporary.name) / "Project"
        self.pack = self.project / "agent_workflow"
        self.project.mkdir()
        shutil.copytree(
            PACK,
            self.pack,
            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
            symlinks=True,
        )
        shutil.copy2(
            self.pack / "templates/project.yaml.example",
            self.pack / "project.yaml",
        )
        self.project_id = f"antigravity-fixture-{uuid.uuid4().hex}"
        config = self.pack / "project.yaml"
        body = config.read_text(encoding="utf-8")
        placeholder = "project_id: replace-with-unique-project-id"
        self.assertEqual(body.count(placeholder), 1)
        config.write_text(
            body.replace(placeholder, f"project_id: {self.project_id}", 1),
            encoding="utf-8",
        )
        self.write_project_files(
            {
                "apps/web/package.json": (
                    '{"dependencies":{"react":"19"},'
                    '"scripts":{"build":"vite build","test":"vitest"}}'
                ),
                "apps/web/package-lock.json": "{}\n",
                "apps/desktop/package.json": (
                    '{"main":"main.js","devDependencies":{"electron":"40"},'
                    '"scripts":{"package":"electron-forge package"}}'
                ),
                "apps/desktop/main.js": "export {};\n",
                "apps/desktop/package-lock.json": "{}\n",
                "services/api/go.mod": "module example.test/api\n",
                "apps/apple/App.xcodeproj/project.pbxproj": (
                    "// !$*UTF8*$!\n"
                    "{\n"
                    "  objects = {\n"
                    "    A1 = {\n"
                    "      isa = PBXNativeTarget;\n"
                    '      productType = "com.apple.product-type.application";\n'
                    "    };\n"
                    "  };\n"
                    "}\n"
                ),
                "apps/apple/App.xcodeproj/xcshareddata/xcschemes/App.xcscheme": (
                    '<Scheme version="1.7"><BuildAction/></Scheme>\n'
                ),
                "apps/android/build.gradle.kts": (
                    'plugins { id("com.android.application") version "9.0.0" }\n'
                ),
                "apps/android/src/main/AndroidManifest.xml": (
                    '<manifest package="example.fixture"/>\n'
                ),
            }
        )

    def write_project_files(self, files: dict[str, str]) -> None:
        for relative, content in files.items():
            target = self.project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def invoke_setup(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "agent_workflow/setup_antigravity.sh", *arguments],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )

    def run_setup(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        result = self.invoke_setup(*arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def read(self, relative: str) -> str:
        return (self.project / relative).read_text(encoding="utf-8")

    def assert_not_symlink(self, relative: str) -> None:
        path = self.project / relative
        self.assertFalse(
            path.is_symlink(),
            f"managed path must not be a symlink: {path}",
        )

    def project_tree_snapshot(self) -> dict[str, tuple[str, int, bytes | str]]:
        snapshot: dict[str, tuple[str, int, bytes | str]] = {}
        for path in sorted(self.project.rglob("*")):
            relative = path.relative_to(self.project).as_posix()
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                snapshot[relative] = ("symlink", mode, os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                snapshot[relative] = ("directory", mode, "")
            elif stat.S_ISREG(info.st_mode):
                snapshot[relative] = ("file", mode, path.read_bytes())
            elif stat.S_ISFIFO(info.st_mode):
                snapshot[relative] = ("fifo", mode, "")
            else:
                snapshot[relative] = ("special", mode, "")
        return snapshot


class AntigravityGeneratedArtifactTest(
    AntigravityFixtureMixin, unittest.TestCase
):
    IMPLEMENTERS = {
        "xy-web",
        "xy-desktop",
        "xy-backend",
        "xy-apple",
        "xy-android",
    }
    NESTED_TOOLS = {"invoke_subagent", "define_subagent", "send_message"}
    QA_WRITE_TOOLS = {
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
        "generate_image",
    }

    @staticmethod
    def tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
        snapshot: dict[str, tuple[str, bytes | str]] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            elif path.is_dir():
                snapshot[relative] = ("directory", "")
            else:
                snapshot[relative] = ("file", path.read_bytes())
        return snapshot

    @staticmethod
    def parse_frontmatter(body: str) -> tuple[list[str], dict[str, object], str]:
        lines = body.splitlines()
        if not lines or lines[0] != "---":
            raise AssertionError("agent must start with frontmatter")
        try:
            closing = lines.index("---", 1)
        except ValueError as exc:
            raise AssertionError("agent frontmatter must have a closing delimiter") from exc
        keys: list[str] = []
        fields: dict[str, object] = {}
        index = 1
        while index < closing:
            match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*):(?:\s+(.*))?", lines[index])
            if match is None:
                raise AssertionError(f"malformed generated frontmatter: {lines[index]!r}")
            key, scalar = match.groups()
            keys.append(key)
            if scalar is None:
                values: list[str] = []
                index += 1
                while index < closing and lines[index].startswith("  - "):
                    values.append(lines[index][4:])
                    index += 1
                fields[key] = values
                continue
            if key == "description":
                fields[key] = json.loads(scalar)
            elif key in {"mainAgent", "subagent"}:
                fields[key] = scalar == "true"
            else:
                fields[key] = scalar
            index += 1
        return keys, fields, "\n".join(lines[closing + 1 :])

    def discovered_roles(self) -> list[str]:
        command = (
            "import json,sys;"
            f"sys.path.insert(0,{str(self.pack / 'lib')!r});"
            "from validate_project_config import validate_with_profile;"
            f"r=validate_with_profile({str(self.pack / 'project.yaml')!r},"
            f"{str(self.project)!r},{str(self.pack / 'roles')!r});"
            "assert not r.errors,r.errors;"
            "assert r.profile is not None;"
            "print(json.dumps(r.profile.enabled_roles))"
        )
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=self.project,
            # 发现查询必须保持只读，不能在被审计的工作流包中遗留字节码缓存。
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        roles = json.loads(result.stdout)
        self.assertIsInstance(roles, list)
        return roles

    def test_discovery_drives_the_exact_canonical_antigravity_roster(self) -> None:
        self.assertEqual(
            [
                "xy-android",
                "xy-apple",
                "xy-backend",
                "xy-desktop",
                "xy-qa",
                "xy-uiux",
                "xy-web",
            ],
            self.discovered_roles(),
        )
        config = (self.pack / "project.yaml").read_text(encoding="utf-8")
        for retired in ("enabled_roles:", "sandboxes:", "commands:"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, config)

        self.run_setup()
        generated = {
            path.stem
            for path in (self.project / ".agents/agents").glob("xy-*.md")
        }
        self.assertEqual(set(self.discovered_roles()), generated)
        self.assertTrue(
            {"xy-python", "xy-rust", "xy-java"}.isdisjoint(generated)
        )

    def test_validator_has_no_arbitrary_word_or_byte_budget(self) -> None:
        # Antigravity 依靠按需 Skill 减少常驻上下文；必要规则不能被 900 词/7KB 阈值拒绝。
        validator = self.read("agent_workflow/lib/validate_antigravity_artifacts.py")
        self.assertNotIn("PM_CONTEXT_BUDGET", validator)
        self.assertNotIn("AGENT_CONTEXT_BUDGET", validator)
        self.assertNotIn("context budget exceeds", validator)

    def test_static_agents_do_not_copy_global_or_unbounded_project_context(self) -> None:
        self.run_setup()
        for role in self.discovered_roles():
            with self.subTest(role=role):
                body = self.read(f".agents/agents/{role}.md")
                self.assertNotIn("# Global Mandatory Constraints", body)
                self.assertNotIn("## Discovered project modules", body)
                self.assertNotIn("## Project required reads (from project.yaml)", body)
                self.assertNotIn("Repository-native verification commands:", body)

    def test_managed_pm_contribution_excludes_user_and_foreign_content(self) -> None:
        user_prefix = "# User project instructions\n\n" + ("user-owned-context " * 1500)
        # 继续以大体积真实保留行为证明没有人为 Antigravity 上限。
        # 外部区块改用同样无此上限的 Claude；Codex 的既有总入口保护另有组合回归，
        # 不再把原本就不能通过 Codex --check 的约 68 KiB 输入当成成功安装样本。
        claude_block = (
            "\n\n<!-- agent-workflow-pack:claude-begin -->\n"
            + ("claude-owned-context " * 1500)
            + "\n<!-- agent-workflow-pack:claude-end -->\n"
        )
        root = self.project / "AGENTS.md"
        root.write_text(user_prefix, encoding="utf-8")
        self.run_setup()
        installed = root.read_text(encoding="utf-8")
        insert_at = installed.index(ANTIGRAVITY_BEGIN)
        root.write_text(
            installed[:insert_at] + claude_block + "\n" + installed[insert_at:],
            encoding="utf-8",
        )

        self.run_setup()

        installed = root.read_text(encoding="utf-8")
        self.assertTrue(installed.startswith(user_prefix))
        self.assertIn(claude_block.strip(), installed)
        managed = antigravity_managed_contribution(installed)
        self.assertNotIn("user-owned-context", managed)
        self.assertNotIn("claude-owned-context", managed)
        self.assertIn(PRODUCT_BEGIN, managed)
        self.assertIn(ANTIGRAVITY_BEGIN, managed)

    def test_generated_agents_receive_dynamic_project_facts_through_task_packs(
        self,
    ) -> None:
        self.run_setup()
        module_roots = (
            "apps/web",
            "apps/desktop",
            "services/api",
            "apps/apple",
            "apps/android",
        )
        for role in self.discovered_roles():
            with self.subTest(role=role):
                body = self.read(f".agents/agents/{role}.md")
                self.assertIn("Execute only the PM task pack", body)
                self.assertIn("discovered facts", body)
                self.assertIn("exact owned paths", body)
                self.assertIn("controlled_document_access", body)
                self.assertNotIn("Project required reads", body)
                self.assertIn("native verification commands", body)
                self.assertIn("ProjectProfile is routing only", body)
                for module_root in module_roots:
                    self.assertNotIn(module_root, body)
                self.assertNotRegex(body, r'\["(?:npm|go|xcodebuild|\./gradlew)"')

    def test_antigravity_runtime_has_no_retired_manual_scope_parser(self) -> None:
        sources = "\n".join(
            (self.pack / relative).read_text(encoding="utf-8")
            for relative in (
                "setup_antigravity.sh",
                "lib/apply_antigravity_setup.py",
                "lib/render_antigravity_agent.py",
                "lib/validate_antigravity_artifacts.py",
            )
        )
        for retired in (
            "project_sandboxes",
            "parse_sandboxes",
            'py_yaml "${PROJECT_YAML}" enabled_roles',
            "def enabled_roles(",
            "AGENT_STATE",
            "agent-workflow-pack-agents-state",
        ):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, sources)

    def test_antigravity_initializes_only_an_unowned_engineering_leaf(self) -> None:
        self.run_setup()
        engineering = self.read("docs/standards/GENERAL.md")
        self.assertIn("## Observed repository baseline", engineering)
        for anchor in (
            "`apps/web`",
            "`apps/desktop`",
            "`services/api`",
            "`apps/apple`",
            "`apps/android`",
            "not upgrade targets",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, engineering)

        with tempfile.TemporaryDirectory(
            prefix="antigravity-empty-engineering-"
        ) as temp:
            project = Path(temp) / "Project"
            pack = project / "agent_workflow"
            project.mkdir()
            shutil.copytree(self.pack, pack, symlinks=True)
            target = project / "docs/standards/GENERAL.md"
            target.parent.mkdir(parents=True)
            target.touch(mode=0o604)
            result = subprocess.run(
                ["bash", "agent_workflow/setup_antigravity.sh"],
                cwd=project,
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "## Observed repository baseline",
                target.read_text(encoding="utf-8"),
            )
            self.assertEqual(0o604, stat.S_IMODE(target.stat().st_mode))

        template = (self.pack / "templates/docs/standards/GENERAL.md").read_text(
            encoding="utf-8"
        )
        neutral_values = {
            "PROJECT_NAME": "MyProject",
            "DOC_PROJECT": "docs/PROJECT.md",
            "DOC_FEATURES_DIR": "docs/features",
            "OBSERVED_BASELINE": (
                "- Not initialized. Setup replaces this exact template-only line with "
                "read-only repository observations."
            ),
        }
        neutral = re.sub(
            r"\{\{([A-Z_]+)\}\}",
            lambda match: neutral_values[match.group(1)],
            template,
        ).encode("utf-8")
        fixtures = (
            ("raw-template", template.encode("utf-8"), 0o604),
            ("old-neutral-baseline", neutral, 0o640),
            (
                "project-contract",
                b"# Engineering\n\n- Domain: engineering\n\n## Required project constraints\n\n- `[eng-java-001] [hard]` Java 21.\n",
                0o600,
            ),
        )
        for state, original, mode in fixtures:
            with self.subTest(state=state), tempfile.TemporaryDirectory(
                prefix="antigravity-owned-engineering-"
            ) as temp:
                project = Path(temp) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(self.pack, pack, symlinks=True)
                target = project / "docs/standards/GENERAL.md"
                target.parent.mkdir(parents=True)
                target.write_bytes(original)
                target.chmod(mode)
                result = subprocess.run(
                    ["bash", "agent_workflow/setup_antigravity.sh"],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(original, target.read_bytes())
                self.assertEqual(mode, stat.S_IMODE(target.stat().st_mode))

    def expected_descriptions(self, roles: list[str]) -> dict[str, str]:
        body = (self.pack / "product/ROLES.yaml").read_text(encoding="utf-8")
        descriptions: dict[str, str] = {}
        for role in roles:
            block = re.search(
                rf"^  {re.escape(role)}:\s*$\n(?P<body>.*?)(?=^  xy-[a-z0-9-]+:\s*$|\Z)",
                body,
                re.MULTILINE | re.DOTALL,
            )
            self.assertIsNotNone(block, role)
            assert block is not None
            description = re.search(
                r"^    description:\s*(.+?)\s*$",
                block.group("body"),
                re.MULTILINE,
            )
            self.assertIsNotNone(description, role)
            assert description is not None
            descriptions[role] = description.group(1)
        return descriptions

    def render_role(self, role: str) -> str:
        result = subprocess.run(
            [
                sys.executable,
                str(self.pack / "lib/render_antigravity_agent.py"),
                str(self.pack),
                role,
            ],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_latest_native_pm_and_role_contracts_render_without_legacy_ui_semantics(
        self,
    ) -> None:
        pm = "\n".join(
            (
                read_contract(self.pack / "platforms/shared/AGENTS.product.tpl"),
                read_contract(self.pack / "platforms/antigravity/AGENTS.antigravity.tpl"),
            )
        )
        pm_entry = "\n".join(
            (self.pack / relative).read_text(encoding="utf-8")
            for relative in ("platforms/shared/AGENTS.product.tpl", "platforms/antigravity/AGENTS.antigravity.tpl")
        )
        uiux = self.render_role("xy-uiux")
        web = self.render_role("xy-web")
        qa = self.render_role("xy-qa")
        normalized_uiux = " ".join(uiux.split())
        normalized_qa = " ".join(qa.split())

        for name, body in {
            "pm": pm,
            "xy-uiux": uiux,
            "xy-web": web,
            "xy-qa": qa,
        }.items():
            with self.subTest(artifact=name):
                # 共用 Skill 必须说明三宿主的原生别名；常驻入口和宿主产物才禁止串用。
                self.assertNotRegex(pm_entry if name == "pm" else body, r"\$(?:xy-|ui-ux-pro-max)")
                self.assertNotIn("PASS_WITH_NITS", body)
                self.assertNotIn("Return the prototype path, screenshots, current revision", body)

        self.assertIn("`/xy-workflow`", pm)
        self.assertIn("`.agents/agents/xy-*.md`", pm)
        self.assertIn("stable prototype workspace", pm)
        self.assertIn("Page design and interaction contract", pm)
        self.assertIn("direct link to each concrete changed page", pm)
        self.assertIn("root prototype index alone is not sufficient", pm.lower())
        self.assertIn("page dependency fingerprint", pm)
        self.assertIn("Final QA outcome: PASS | FAIL", pm)

        self.assertRegex(uiux, r"(?m)^name: xy-uiux$")
        self.assertIn("/ui-ux-pro-max", uiux)
        self.assertIn("/xy-prototype-verify", uiux)
        self.assertIn("purpose", uiux)
        self.assertIn("navigation", uiux)
        self.assertIn("interactions", uiux)
        self.assertIn("states", uiux)
        self.assertIn("exceptions", uiux)
        self.assertIn("direct links for every concrete changed HTML page", normalized_uiux)
        self.assertIn("verified page dependency fingerprint", normalized_uiux)

        self.assertRegex(web, r"(?m)^name: xy-web$")
        self.assertIn("Reuse production components and tokens", web)
        self.assertIn("Do not copy prototype-only mock data", web)

        self.assertRegex(qa, r"(?m)^name: xy-qa$")
        self.assertIn("Final QA outcome: PASS | FAIL", qa)
        self.assertIn("Prototype review MUST NOT invoke Computer Use or `/browser`", qa)
        self.assertIn("only to the real production implementation", qa)
        self.assertIn("rendered frame ephemerally in memory", normalized_qa)
        self.assertIn("must not persist, save, write, attach, present", normalized_qa)

    def test_runtime_has_no_static_role_read_injector(self) -> None:
        self.assertFalse((self.pack / "lib/inject_role_reads.py").exists())
        self.assertNotIn(
            "role_reads",
            (self.pack / "project.yaml").read_text(encoding="utf-8"),
        )

    def test_renderer_ui_handoff_is_concrete_and_fingerprint_bound(self) -> None:
        body = self.render_role("xy-uiux")
        normalized = " ".join(body.split())
        self.assertIn("Return direct links for every concrete changed HTML page", normalized)
        self.assertIn("its verified page dependency fingerprint", normalized)
        self.assertIn("The root prototype index alone is not sufficient", normalized)
        self.assertNotIn("screenshots, current revision", body)
        self.assertNotRegex(body, r"(?i)manual\s+(?:prototype\s+)?revision")

    def test_setup_generates_native_agents_and_shared_skills(self) -> None:
        pack_before = self.tree_snapshot(self.pack)
        self.run_setup()

        roles = self.discovered_roles()
        descriptions = self.expected_descriptions(roles)
        shared_skill = self.project / ".agents/skills/xy-workflow/SKILL.md"
        self.assertTrue(
            shared_skill.is_file(),
            f"missing shared workflow Skill: {shared_skill}",
        )
        for relative in (".agents", ".agents/agents", ".agents/skills"):
            with self.subTest(path=relative):
                self.assert_not_symlink(relative)
        self.assertFalse(
            shared_skill.is_symlink(),
            f"shared workflow Skill must not be a symlink: {shared_skill}",
        )
        self.assertEqual(self.tree_snapshot(self.pack), pack_before)
        root_agents = self.read("AGENTS.md")
        self.assertNotRegex(root_agents, r"\$(?:xy-|ui-ux-pro-max)")
        self.assertIn("`/xy-workflow`", root_agents)
        self.assertIn("pm-integration.md", root_agents)
        self.assertIn("`/xy-project-memory`", read_contract(
            self.pack / "platforms/antigravity/AGENTS.antigravity.tpl"))
        shared_product = (
            self.pack / "platforms/shared/AGENTS.product.tpl"
        ).read_text(encoding="utf-8")
        self.assertIn("`xy-workflow`", shared_product)
        self.assertNotIn("`$xy-workflow`", shared_product)
        self.assertNotIn("`/xy-workflow`", shared_product)

        validator = subprocess.run(
            [
                sys.executable,
                str(self.pack / "lib/validate_antigravity_artifacts.py"),
                "generated",
                str(self.pack),
                str(self.project),
            ],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(validator.returncode, 0, validator.stdout + validator.stderr)

        expected_keys = [
            "name",
            "description",
            "tools",
            "mainAgent",
            "subagent",
            "model",
            "commandExecutionPolicy",
            "skills",
        ]
        for role in roles:
            with self.subTest(role=role):
                relative = f".agents/agents/{role}.md"
                agent_path = self.project / relative
                self.assertTrue(agent_path.is_file(), f"missing native Agent: {agent_path}")
                self.assert_not_symlink(relative)
                raw = agent_path.read_text(encoding="utf-8")
                keys, fields, agent_body = self.parse_frontmatter(raw)
                self.assertEqual(keys, expected_keys)
                self.assertEqual(fields["name"], role)
                self.assertEqual(fields["description"], descriptions[role])
                self.assertIn(
                    f"description: {json.dumps(descriptions[role], ensure_ascii=False)}",
                    raw,
                )
                self.assertEqual(fields["mainAgent"], False)
                self.assertEqual(fields["subagent"], True)
                self.assertEqual(fields["model"], "inherit")
                self.assertEqual(fields["commandExecutionPolicy"], "sandbox")
                tools = set(fields["tools"])
                self.assertFalse(tools & self.NESTED_TOOLS)
                self.assertEqual(
                    agent_body.splitlines().count(
                        "<!-- agent-workflow-pack:managed-antigravity-agent -->"
                    ),
                    1,
                )
                self.assertIn("Return the result to the PM only", agent_body)
                self.assertIn("Do not report completion directly to the user", agent_body)
                self.assertNotRegex(agent_body, r"\$(?:xy-|ui-ux-pro-max)")
                self.assertNotIn("Project required reads", agent_body)
                role_heading = next(
                    line
                    for line in (self.pack / f"roles/{role}.md")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line.startswith(f"# {role}")
                )
                self.assertNotIn("# Global Mandatory Constraints", agent_body)
                self.assertLess(
                    agent_body.index("## Antigravity execution contract"),
                    agent_body.index(role_heading),
                )
                if role in self.IMPLEMENTERS:
                    self.assertEqual(fields["skills"], ["skills/xy-build-verify"])
                    self.assertIn("exact `owned_paths`", agent_body)
                    self.assertIn("/xy-build-verify", agent_body)
                elif role == "xy-uiux":
                    self.assertEqual(fields["skills"], ["skills/xy-prototype-verify"])
                    self.assertIn("/ui-ux-pro-max", agent_body)
                    self.assertIn("docs.standards_root/DESIGN_*.md", agent_body)
                    self.assertIn("docs.standards_root/DESIGN_*.md", agent_body)
                    # 原型是用户确认材料；Antigravity 即使暴露 /browser，也不能把它升级成
                    # 静态校验之后的默认第二道自动化门禁。
                    self.assertIn(
                        "Prototype verification MUST NOT invoke Computer Use or `/browser` by default",
                        agent_body,
                    )
                    self.assertIn("explicit user request", agent_body)
                    self.assertIn("user-reported prototype failure", agent_body)
                else:
                    self.assertEqual(role, "xy-qa")
                    self.assertEqual(fields["skills"], ["skills/xy-qa-review"])
                    self.assertFalse(tools & self.QA_WRITE_TOOLS)
                    self.assertIn("Do not edit production business code", agent_body)
                    self.assertIn("Do not command implementers", agent_body)
                    for forbidden in (
                        "let Codex match",
                        "let the current host match",
                        "optionally **add tests**",
                        "Write access is for **tests only**",
                        "Optional tests",
                    ):
                        self.assertNotIn(forbidden, agent_body)

    def test_preflight_validates_staging_without_project_writes(self) -> None:
        before = self.project_tree_snapshot()
        result = self.run_setup("--preflight")
        self.assertEqual(self.project_tree_snapshot(), before)
        for anchor in (
            "ProjectProfile preview",
            "roles: xy-android, xy-apple, xy-backend, xy-desktop, xy-qa, xy-uiux, xy-web",
            "module apps/desktop -> xy-desktop",
            "module services/api -> xy-backend",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, result.stdout)
        for relative in ("AGENTS.md", ".agents", "docs"):
            with self.subTest(path=relative):
                self.assertFalse((self.project / relative).exists())

    def test_generated_validator_rejects_reintroduced_legacy_role_semantics(
        self,
    ) -> None:
        self.run_setup()
        mutations = {
            "optional-screenshot": (
                "xy-uiux",
                "The designer may attach screenshots as optional visual approval evidence.",
            ),
            "task-markdown": (
                "xy-uiux",
                "The designer should create a task-specific Markdown companion for each prototype.",
            ),
            "root-only-confirmation": (
                "xy-uiux",
                "The root prototype index is sufficient for visual confirmation.",
            ),
            "copy-prototype-runtime": (
                "xy-web",
                "Web implementers may copy prototype mock data and runtime into production.",
            ),
            "third-qa-outcome": (
                "xy-qa",
                "Final QA outcome: PASS_WITH_NITS.",
            ),
            "persist-browser-frame": (
                "xy-qa",
                "QA may save the rendered frame as approval evidence.",
            ),
        }
        for name, (role, statement) in mutations.items():
            with self.subTest(mutation=name):
                path = self.project / f".agents/agents/{role}.md"
                original = path.read_text(encoding="utf-8")
                try:
                    path.write_text(original + "\n" + statement + "\n", encoding="utf-8")
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(self.pack / "lib/validate_antigravity_artifacts.py"),
                            "generated",
                            str(self.pack),
                            str(self.project),
                        ],
                        cwd=self.project,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=20,
                    )
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("legacy UI artifact model", result.stderr)
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_generated_validator_requires_latest_role_contract_structure(self) -> None:
        self.run_setup()
        mutations = {
            "xy-uiux": (
                "root index alone is insufficient",
                "Use the prototype index for navigation.",
            ),
            "xy-web": (
                "Do not copy prototype-only mock data",
                "Do not copy unrelated implementation into production",
            ),
            "xy-qa": (
                "Final QA outcome: PASS | FAIL; report to the PM only.",
                "Return the audit result.",
            ),
        }
        for role, (old, new) in mutations.items():
            with self.subTest(role=role):
                path = self.project / f".agents/agents/{role}.md"
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                try:
                    path.write_text(original.replace(old, new), encoding="utf-8")
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(self.pack / "lib/validate_antigravity_artifacts.py"),
                            "generated",
                            str(self.pack),
                            str(self.project),
                        ],
                        cwd=self.project,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=20,
                    )
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertRegex(result.stderr, r"missing required contract phrase")
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_check_rejects_old_ui_semantics_in_a_managed_generated_block(self) -> None:
        self.run_setup()
        root_agents = self.project / "AGENTS.md"
        body = root_agents.read_text(encoding="utf-8")
        current = "only required prototypes add `visual_approved`."
        self.assertEqual(body.count(current), 1)
        root_agents.write_text(
            body.replace(
                current,
                current
                + " The root prototype index is sufficient for visual confirmation.",
                1,
            ),
            encoding="utf-8",
        )
        result = self.invoke_setup("--check")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[ERROR]", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_check_validates_without_project_or_pack_writes(self) -> None:
        self.run_setup()
        for cache in self.pack.rglob("__pycache__"):
            shutil.rmtree(cache)
        before = self.project_tree_snapshot()
        self.run_setup("--check")
        self.assertEqual(self.project_tree_snapshot(), before)

    def test_product_source_failure_is_controlled_and_precedes_project_writes(
        self,
    ) -> None:
        product = self.pack / "platforms/shared/AGENTS.product.tpl"
        backup = product.with_name("AGENTS.product.real.tpl")
        product.rename(backup)
        product.symlink_to(backup)
        before = self.project_tree_snapshot()
        result = self.invoke_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.project_tree_snapshot(), before)
        self.assertIn("[ERROR]", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_invalid_role_description_and_utf8_fail_before_project_writes(self) -> None:
        roles_yaml = self.pack / "product/ROLES.yaml"
        original = roles_yaml.read_text(encoding="utf-8")
        roles_yaml.write_text(
            re.sub(
                r"(?m)^    description: Repository-driven Web engineer\..*$",
                "    description: 'bad'quote'",
                original,
                count=1,
            ),
            encoding="utf-8",
        )
        before = self.project_tree_snapshot()
        result = self.invoke_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.project_tree_snapshot(), before)
        self.assertRegex(result.stdout + result.stderr, r"(?i)(description|single.quote)")
        self.assertNotIn("Traceback", result.stdout + result.stderr)

        roles_yaml.write_text(original, encoding="utf-8")
        role = self.pack / "roles/xy-web.md"
        role.write_bytes(role.read_bytes() + b"\n\xff\xfeinvalid-role\n")
        before = self.project_tree_snapshot()
        raw = subprocess.run(
            ["bash", "agent_workflow/setup_antigravity.sh", "--preflight"],
            cwd=self.project,
            capture_output=True,
            check=False,
            timeout=60,
        )
        self.assertNotEqual(raw.returncode, 0)
        self.assertEqual(self.project_tree_snapshot(), before)
        combined = raw.stdout + raw.stderr
        combined.decode("ascii")
        self.assertIn(b"[ERROR]", combined)
        self.assertNotIn(b"Traceback", combined)

    def test_role_description_scalar_boundaries_are_controlled_and_prewrite(
        self,
    ) -> None:
        roles_yaml = self.pack / "product/ROLES.yaml"
        original = roles_yaml.read_text(encoding="utf-8")
        description_line = re.compile(
            r"(?m)^    description: Repository-driven Web engineer\..*$"
        )
        self.assertEqual(len(description_line.findall(original)), 1)
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        def install(raw_scalar: str) -> None:
            roles_yaml.write_text(
                description_line.sub(
                    lambda _match: f"    description: {raw_scalar}",
                    original,
                    count=1,
                ),
                encoding="utf-8",
            )

        invalid_scalars = {
            "bool-true": "true",
            "bool-false": "false",
            "bool-yes": "yes",
            "bool-no": "no",
            "bool-on": "on",
            "bool-off": "off",
            "null-word": "null",
            "null-tilde": "~",
            "integer": "42",
            "signed-integer": "-7",
            "float": "3.14",
            "exponent": "1.2e+6",
            "date": "2026-08-10",
            "time": "12:34:56",
            "empty-flow-list": "[]",
            "empty-flow-map": "{}",
            "sequence-start": "- item",
            "mapping-key-start": "? key",
            "mapping-value-start": ": value",
            "flow-sequence-start": "[item]",
            "flow-map-start": "{key: value}",
            "comment-start": "# comment",
            "anchor-start": "&anchor text",
            "alias-start": "*alias",
            "tag-start": "!tag text",
            "literal-block-start": "|",
            "folded-block-start": ">",
            "directive-start": "%directive",
            "reserved-at-start": "@reserved",
            "reserved-backtick-start": "`reserved",
            "mapping-delimiter": "plain: ambiguous",
            "mapping-delimiter-at-end": "plain:",
            "inline-comment": "plain # inline comment",
        }
        for case, raw_scalar in invalid_scalars.items():
            with self.subTest(invalid=case):
                install(raw_scalar)
                try:
                    before = self.project_tree_snapshot()
                    sources = subprocess.run(
                        [
                            sys.executable,
                            str(
                                self.pack
                                / "lib/validate_antigravity_artifacts.py"
                            ),
                            "sources",
                            str(self.pack),
                        ],
                        cwd=self.project,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=20,
                    )
                    renderer = subprocess.run(
                        [
                            sys.executable,
                            str(self.pack / "lib/render_antigravity_agent.py"),
                            str(self.pack),
                            "xy-web",
                        ],
                        cwd=self.project,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=20,
                    )
                    preflight = self.invoke_setup("--preflight")

                    self.assertEqual(sources.returncode, 1)
                    self.assertEqual(renderer.returncode, 1)
                    self.assertEqual(renderer.stdout, "")
                    self.assertNotEqual(preflight.returncode, 0)
                    self.assertEqual(self.project_tree_snapshot(), before)
                    for result in (sources, renderer, preflight):
                        diagnostic = result.stdout + result.stderr
                        self.assertIn("[ERROR]", diagnostic)
                        self.assertNotIn("Traceback", diagnostic)
                finally:
                    roles_yaml.write_text(original, encoding="utf-8")

        valid_scalars = {
            "plain": (
                "Web engineer for controlled projects.",
                "Web engineer for controlled projects.",
            ),
            "json-double-quoted": (
                '"JSON quoted: true, # literal"',
                "JSON quoted: true, # literal",
            ),
            "yaml-single-quoted": (
                "'YAML single ''quoted'' string: true # literal'",
                "YAML single 'quoted' string: true # literal",
            ),
        }
        for case, (raw_scalar, expected) in valid_scalars.items():
            with self.subTest(valid=case):
                install(raw_scalar)
                try:
                    before = self.project_tree_snapshot()
                    sources = subprocess.run(
                        [
                            sys.executable,
                            str(
                                self.pack
                                / "lib/validate_antigravity_artifacts.py"
                            ),
                            "sources",
                            str(self.pack),
                        ],
                        cwd=self.project,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=20,
                    )
                    renderer = subprocess.run(
                        [
                            sys.executable,
                            str(self.pack / "lib/render_antigravity_agent.py"),
                            str(self.pack),
                            "xy-web",
                        ],
                        cwd=self.project,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=20,
                    )
                    preflight = self.invoke_setup("--preflight")

                    self.assertEqual(
                        sources.returncode,
                        0,
                        sources.stdout + sources.stderr,
                    )
                    self.assertEqual(
                        renderer.returncode,
                        0,
                        renderer.stdout + renderer.stderr,
                    )
                    self.assertIn(
                        f"description: {json.dumps(expected, ensure_ascii=False)}",
                        renderer.stdout,
                    )
                    self.assertEqual(
                        preflight.returncode,
                        0,
                        preflight.stdout + preflight.stderr,
                    )
                    self.assertEqual(self.project_tree_snapshot(), before)
                finally:
                    roles_yaml.write_text(original, encoding="utf-8")

    def test_generated_agent_uses_official_frontmatter(self) -> None:
        self.run_setup()

        qa_agent = self.project / ".agents/agents/xy-qa.md"
        self.assertTrue(
            qa_agent.is_file(),
            f"missing native Antigravity agent: {qa_agent}",
        )
        body = self.read(".agents/agents/xy-qa.md")
        self.assertTrue(body.startswith("---\n"), "agent must start with frontmatter")
        closing = body.find("\n---\n", len("---\n"))
        self.assertNotEqual(closing, -1, "agent frontmatter must have a closing delimiter")
        frontmatter = body[len("---\n") : closing]
        for anchor in (
            "name: xy-qa",
            "mainAgent: false",
            "subagent: true",
            "model: inherit",
            "commandExecutionPolicy: sandbox",
            "skills/xy-qa-review",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, frontmatter)


class AntigravityOwnershipMigrationTest(
    AntigravityFixtureMixin, unittest.TestCase
):
    AGENT_MARKER = "<!-- agent-workflow-pack:managed-antigravity-agent -->"
    SKILL_MARKER = "<!-- agent-workflow-pack:managed-skill -->"

    @staticmethod
    def external_snapshot(
        root: Path,
    ) -> dict[str, tuple[str, int, bytes | str]]:
        snapshot: dict[str, tuple[str, int, bytes | str]] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                snapshot[relative] = ("symlink", mode, os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                snapshot[relative] = ("directory", mode, "")
            elif stat.S_ISREG(info.st_mode):
                snapshot[relative] = ("file", mode, path.read_bytes())
            elif stat.S_ISFIFO(info.st_mode):
                snapshot[relative] = ("fifo", mode, "")
            else:
                snapshot[relative] = ("special", mode, "")
        return snapshot

    def invoke_with_failpoint(
        self,
        failpoint: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["AGENT_WORKFLOW_PACK_TEST_FAILPOINT"] = failpoint
        return subprocess.run(
            ["bash", "agent_workflow/setup_antigravity.sh"],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
            env=environment,
        )

    def assert_controlled_failure(
        self,
        result: subprocess.CompletedProcess[str],
    ) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("[ERROR]", combined)
        self.assertNotIn("Traceback", combined)

    def test_fresh_real_directories_and_repeat_setup_are_idempotent(self) -> None:
        self.run_setup()
        before = self.project_tree_snapshot()
        self.run_setup()
        self.assertEqual(before, self.project_tree_snapshot())
        for relative in (".agents", ".agents/agents", ".agents/skills"):
            target = self.project / relative
            self.assertTrue(target.is_dir(), relative)
            self.assertFalse(target.is_symlink(), relative)

    def test_user_owned_content_under_agents_fails_before_any_project_write(self) -> None:
        user_agent = self.project / ".agents/agents/user-reviewer.md"
        user_skill = self.project / ".agents/skills/user-notes/SKILL.md"
        user_agent.parent.mkdir(parents=True)
        user_skill.parent.mkdir(parents=True)
        user_agent.write_text("user agent\n", encoding="utf-8")
        user_skill.write_text("user skill\n", encoding="utf-8")
        user_agent.chmod(0o640)
        user_skill.chmod(0o600)
        before = self.project_tree_snapshot()

        result = self.invoke_setup()

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_retired_compat_link_fails_before_any_project_write(self) -> None:
        (self.project / ".agents").symlink_to("agent_workflow/compat_agents")
        before = self.project_tree_snapshot()

        result = self.invoke_setup()

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_unknown_internal_and_external_agents_symlinks_fail_prewrite(self) -> None:
        for name, target in {
            "internal": self.project / "user-agents",
            "external": Path(self.temporary.name) / "outside-agents",
        }.items():
            with self.subTest(name=name):
                target.mkdir()
                link = self.project / ".agents"
                link.symlink_to(target, target_is_directory=True)
                before = self.project_tree_snapshot()
                result = self.invoke_setup()
                self.assert_controlled_failure(result)
                self.assertEqual(before, self.project_tree_snapshot())
                link.unlink()

    def test_native_directory_file_collisions_fail_prewrite(self) -> None:
        for relative in (".agents", ".agents/agents", ".agents/skills"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory(
                prefix="antigravity-dir-collision-"
            ) as temp:
                project = Path(temp) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(self.pack, pack, symlinks=True)
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("user collision\n", encoding="utf-8")
                before = self.external_snapshot(project)
                result = subprocess.run(
                    ["bash", "agent_workflow/setup_antigravity.sh"],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.external_snapshot(project))

    def test_user_owned_same_name_agent_and_skill_fail_prewrite(self) -> None:
        for relative in (
            ".agents/agents/xy-web.md",
            ".agents/skills/xy-workflow/SKILL.md",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory(
                prefix="antigravity-user-collision-"
            ) as temp:
                project = Path(temp) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(self.pack, pack, symlinks=True)
                target = project / relative
                target.parent.mkdir(parents=True)
                target.write_text("user same-name artifact\n", encoding="utf-8")
                before = self.external_snapshot(project)
                result = subprocess.run(
                    ["bash", "agent_workflow/setup_antigravity.sh"],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.external_snapshot(project))

    def test_managed_same_name_agent_and_skill_are_updated(self) -> None:
        self.run_setup()
        agent = self.project / ".agents/agents/xy-web.md"
        skill = self.project / ".agents/skills/xy-workflow/SKILL.md"
        role_source = self.pack / "roles/xy-web.md"
        skill_source = (
            self.pack / "platforms/shared/skills/xy-workflow/SKILL.md"
        )
        role_source.write_text(role_source.read_text() + "\nPack Agent upgrade.\n")
        skill_source.write_text(skill_source.read_text() + "\nPack Skill upgrade.\n")

        self.run_setup()

        self.assertIn("Pack Agent upgrade.", agent.read_text())
        self.assertIn("Pack Skill upgrade.", skill.read_text())

    def test_marker_only_agent_cannot_transfer_whole_root_ownership(self) -> None:
        self.run_setup()
        agent = self.project / ".agents/agents/xy-web.md"
        agent.write_text(
            self.AGENT_MARKER + "\nUser-owned content.\n",
            encoding="utf-8",
        )
        before = self.project_tree_snapshot()

        result = self.invoke_setup()

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_structurally_invalid_marked_agent_cannot_transfer_root_ownership(
        self,
    ) -> None:
        self.run_setup()
        agent = self.project / ".agents/agents/xy-web.md"
        body = agent.read_text(encoding="utf-8")
        self.assertEqual(body.count("mainAgent: false"), 1)
        agent.write_text(
            body.replace("mainAgent: false", "mainAgent: true", 1),
            encoding="utf-8",
        )
        before = self.project_tree_snapshot()

        result = self.invoke_setup()

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_agent_only_root_cannot_transfer_native_root_ownership(self) -> None:
        self.run_setup()
        shutil.rmtree(self.project / ".agents/skills")
        before = self.project_tree_snapshot()

        result = self.invoke_setup()

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_reset_fingerprint_mismatch_preserves_concurrent_replacement(
        self,
    ) -> None:
        self.run_setup()
        # Hooks 容器必须走路径级更新；该用例单独验证“不含 Hooks”的整树 reset 原语。
        (self.project / ".agents/hooks.json").unlink()
        lib_path = str(PACK / "lib")
        sys.path.insert(0, lib_path)
        try:
            validator = importlib.import_module("validate_antigravity_artifacts")
        finally:
            sys.path.remove(lib_path)

        root = self.project / ".agents"
        displaced = self.project / ".concurrent-original-agents"
        backup = self.project / ".agent-workflow-antigravity-reset.RACE123"
        original_replace = validator.os.replace
        raced = False

        def replace_after_concurrent_swap(source: object, target: object) -> None:
            nonlocal raced
            if Path(source) == root and Path(target) == backup and not raced:
                raced = True
                root.rename(displaced)
                shutil.copytree(displaced, root)
                agent = root / "agents/xy-web.md"
                agent.write_text(
                    agent.read_text(encoding="utf-8")
                    + "\nConcurrent replacement bytes.\n",
                    encoding="utf-8",
                )
            original_replace(source, target)

        with mock.patch.object(
            validator.os,
            "replace",
            side_effect=replace_after_concurrent_swap,
        ):
            with self.assertRaisesRegex(
                validator.SecureReadError,
                "changed during reset",
            ):
                validator.reset_owned_agents_root(self.project, backup)

        self.assertTrue(raced)
        self.assertIn(
            "Concurrent replacement bytes.",
            (root / "agents/xy-web.md").read_text(encoding="utf-8"),
        )
        self.assertTrue((displaced / "agents/xy-web.md").is_file())
        self.assertFalse(backup.exists())

    def test_duplicate_agent_marker_fails_before_project_write(self) -> None:
        self.run_setup()
        agent = self.project / ".agents/agents/xy-web.md"
        agent.write_text(
            agent.read_text(encoding="utf-8") + f"\n{self.AGENT_MARKER}\n",
            encoding="utf-8",
        )
        before = self.project_tree_snapshot()

        result = self.invoke_setup()

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_obsolete_agent_semantics_fail_before_native_root_reset(
        self,
    ) -> None:
        self.run_setup()
        qa = self.project / ".agents/agents/xy-qa.md"
        body = qa.read_text(encoding="utf-8")
        self.assertEqual(body.count(self.AGENT_MARKER), 1)
        qa.write_text(
            body + "\nFinal QA outcome: PASS_WITH_NITS.\n",
            encoding="utf-8",
        )
        before = self.project_tree_snapshot()

        result = self.invoke_setup()

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_native_path_update_preserves_existing_modes_with_hooks_container(self) -> None:
        self.run_setup()
        agent = self.project / ".agents/agents/xy-web.md"
        skill = self.project / ".agents/skills/xy-workflow/SKILL.md"
        root_agents = self.project / "AGENTS.md"
        project_index = self.project / "docs/PROJECT.md"
        role_source = self.pack / "roles/xy-web.md"
        skill_source = self.pack / "platforms/shared/skills/xy-workflow/SKILL.md"

        role_source.write_text(
            role_source.read_text(encoding="utf-8") + "\nstaged Agent bytes fixture\n",
            encoding="utf-8",
        )
        skill_source.write_text(
            skill_source.read_text(encoding="utf-8") + "\nstaged Skill bytes fixture\n",
            encoding="utf-8",
        )
        agent.chmod(0o640)
        skill.chmod(0o600)
        root_agents.chmod(0o604)
        project_index.write_bytes(b"")
        project_index.chmod(0o620)
        expected_agent = subprocess.run(
            [
                sys.executable,
                str(self.pack / "lib/render_antigravity_agent.py"),
                str(self.pack),
                "xy-web",
            ],
            cwd=self.project,
            capture_output=True,
            check=True,
            timeout=20,
        ).stdout

        self.run_setup()

        self.assertEqual(expected_agent, agent.read_bytes())
        self.assertEqual(skill_source.read_bytes(), skill.read_bytes())
        # 有 Hooks 的项目不再整树 reset；仍更新受管内容，但保留现有路径权限。
        self.assertEqual(0o640, stat.S_IMODE(agent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(skill.stat().st_mode))
        self.assertEqual(0o604, stat.S_IMODE(root_agents.stat().st_mode))
        # PROJECT 是唯一入口；空文件不是有意关闭记忆，而是需要按当前模板恢复。
        self.assertTrue(project_index.read_bytes())
        self.assertEqual(0o620, stat.S_IMODE(project_index.stat().st_mode))

    def test_reverse_enumeration_removes_only_proven_stale_managed(self) -> None:
        self.run_setup()
        stale_agent = self.project / ".agents/agents/xy-web.md"
        config = self.pack / "project.yaml"
        body = config.read_text()
        self.assertEqual(body.count("workspace_overrides: {}"), 1)
        config.write_text(
            body.replace(
                "workspace_overrides: {}",
                "workspace_overrides:\n  exclude:\n    - apps/web/",
                1,
            )
        )
        self.assertTrue(stale_agent.is_file())
        user_agent = self.project / ".agents/agents/xy-user.md"
        user_agent.write_text("user Agent\n")
        stale_skill = self.project / ".agents/skills/xy-retired"
        stale_skill.mkdir()
        (stale_skill / "SKILL.md").write_text(
            "---\nname: xy-retired\ndescription: Retired fixture.\n---\n\n"
            f"{self.SKILL_MARKER}\n"
        )
        user_skill = self.project / ".agents/skills/xy-user/SKILL.md"
        user_skill.parent.mkdir()
        user_skill.write_text("user Skill\n")
        before = self.project_tree_snapshot()

        result = self.invoke_setup()

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_root_managed_markers_are_validated_as_one_global_structure(self) -> None:
        product_begin = "<!-- pack:product-begin -->"
        product_end = "<!-- pack:product-end -->"
        codex_begin = "<!-- pack:codex-begin -->"
        codex_end = "<!-- pack:codex-end -->"
        anti_begin = "<!-- pack:antigravity-begin -->"
        anti_end = "<!-- pack:antigravity-end -->"
        for name, lines in {
            "crossed": [product_begin, anti_begin, product_end, anti_end],
            "nested": [product_begin, anti_begin, anti_end, product_end],
            "reverse": [anti_begin, anti_end, product_begin, product_end],
            "duplicate": [product_begin, product_end, product_begin, product_end],
            "orphan": [product_begin, product_end, anti_begin],
            "foreign-crossed": [
                product_begin,
                product_end,
                codex_begin,
                anti_begin,
                codex_end,
                anti_end,
            ],
            "foreign-nested": [product_begin, codex_begin, codex_end, product_end],
            "foreign-duplicate": [
                product_begin,
                product_end,
                codex_begin,
                codex_end,
                codex_begin,
                codex_end,
            ],
            "foreign-orphan": [product_begin, product_end, codex_begin],
        }.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="antigravity-markers-"
            ) as temp:
                project = Path(temp) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(self.pack, pack, symlinks=True)
                (project / "AGENTS.md").write_text("\n".join(lines) + "\n")
                before = self.external_snapshot(project)
                result = subprocess.run(
                    ["bash", "agent_workflow/setup_antigravity.sh"],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.external_snapshot(project))

    def test_setup_recognizes_but_does_not_modify_the_codex_managed_block(self) -> None:
        codex = subprocess.run(
            ["bash", "agent_workflow/setup_codex.sh"],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(codex.returncode, 0, codex.stdout + codex.stderr)
        root = self.project / "AGENTS.md"
        before = root.read_bytes()
        begin = b"<!-- pack:codex-begin -->"
        end = b"<!-- pack:codex-end -->"
        codex_block = begin + before.split(begin, 1)[1].split(end, 1)[0] + end

        self.run_setup()

        after = root.read_bytes()
        self.assertEqual(1, after.count(begin))
        self.assertEqual(1, after.count(end))
        self.assertIn(codex_block, after)

    def test_managed_target_hardlinks_fail_without_touching_external_inode(self) -> None:
        for relative in (
            "docs/standards/GENERAL.md",
            ".agents/agents/xy-web.md",
            ".agents/skills/xy-workflow/SKILL.md",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory(
                prefix="antigravity-hardlink-"
            ) as temp:
                project = Path(temp) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(self.pack, pack, symlinks=True)
                outside = Path(temp) / "outside.txt"
                outside.write_text("outside sentinel\n")
                target = project / relative
                target.parent.mkdir(parents=True)
                os.link(outside, target)
                inode = outside.stat().st_ino
                before = self.external_snapshot(project)
                result = subprocess.run(
                    ["bash", "agent_workflow/setup_antigravity.sh"],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.external_snapshot(project))
                self.assertEqual(inode, outside.stat().st_ino)
                self.assertEqual("outside sentinel\n", outside.read_text())

    def test_publish_rechecks_target_after_same_directory_temp_write(self) -> None:
        lib_path = str(PACK / "lib")
        sys.path.insert(0, lib_path)
        try:
            applier = importlib.import_module("apply_antigravity_setup")
        finally:
            sys.path.remove(lib_path)

        target = self.project / "managed-target.md"
        target.write_bytes(b"trusted old bytes\n")
        before = applier._fingerprint(target)
        change = applier.FileChange(target, b"staged replacement bytes\n", 0o640, before)
        plan = applier.Plan(
            self.pack,
            self.project,
            self.project,
            "0123456789abcdef0123456789abcdef",
        )
        original_write_temp = applier._write_temp

        def replace_after_temp_write(
            output: Path,
            body: bytes,
            mode: int,
            nonce: str,
        ) -> Path:
            temporary = original_write_temp(output, body, mode, nonce)
            self.assertEqual(output.parent, temporary.parent)
            target.write_bytes(b"concurrent replacement\n")
            return temporary

        with mock.patch.object(
            applier,
            "_write_temp",
            side_effect=replace_after_temp_write,
        ):
            with self.assertRaisesRegex(applier.ApplyError, "changed during publish"):
                applier._publish_file(change, plan)

        self.assertEqual(b"concurrent replacement\n", target.read_bytes())
        self.assertFalse(
            any(
                path.name.startswith(".agent-workflow-pack-antigravity--")
                for path in self.project.iterdir()
            )
        )

    def test_injected_publish_failure_rolls_back_all_outputs(self) -> None:
        before = self.project_tree_snapshot()
        result = self.invoke_with_failpoint("antigravity-after-agents-publish")
        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())

    def test_generated_validator_failure_restores_exact_previous_native_root(
        self,
    ) -> None:
        self.run_setup()
        root = self.project / ".agents"
        root_identity = (root.lstat().st_dev, root.lstat().st_ino)
        before = self.project_tree_snapshot()

        result = self.invoke_with_failpoint(
            "antigravity-generated-validator-failure"
        )

        self.assert_controlled_failure(result)
        self.assertEqual(before, self.project_tree_snapshot())
        self.assertEqual(root_identity, (root.lstat().st_dev, root.lstat().st_ino))
        self.assertFalse(
            any(
                path.name.startswith(".agent-workflow-antigravity-reset.")
                for path in self.project.iterdir()
            )
        )

    def test_successful_native_reinstall_does_not_restore_the_old_root(self) -> None:
        self.run_setup()
        source = self.pack / "roles/xy-web.md"
        source.write_text(
            source.read_text(encoding="utf-8") + "\ncleanup commit fixture update\n",
            encoding="utf-8",
        )
        result = self.invoke_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "cleanup commit fixture update",
            (self.project / ".agents/agents/xy-web.md").read_text(encoding="utf-8"),
        )
        self.assertFalse(
            any(
                path.name.startswith(".agent-workflow-antigravity-reset.")
                for path in self.project.iterdir()
            )
        )
        self.run_setup()


class AntigravityValidatorTest(AntigravityFixtureMixin, unittest.TestCase):
    COMPLIANT_TEMPLATE = (
        PACK / "platforms/antigravity/AGENTS.antigravity.tpl"
    ).read_text(encoding="utf-8")
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
    IMPLEMENTERS = (
        "xy-web",
        "xy-desktop",
        "xy-backend",
        "xy-apple",
        "xy-android",
    )
    SEMANTIC_DIAGNOSTICS = {
        "ui-starts-before-gate": r"UI gate bypass",
        "ui-begins-before-gate": r"UI gate bypass",
        "memory-authority-inversion": r"memory authority inversion",
        "memory-isolation-fallback-bypass": r"memory isolation fallback bypass",
        "ui-production-before-gates": r"UI gate bypass",
        "final-report-before-qa-closeout": r"final user report before closeout",
        "qa-edits-production": r"QA production edit authority",
        "qa-modifies-production": r"QA production edit authority",
        "qa-fixes-production": r"QA production edit authority",
        "qa-pronoun-edits-production": r"QA production edit authority",
        "qa-commands-implementers": r"QA commands implementers",
        "qa-dispatches-implementers": r"QA commands implementers",
        "qa-assigns-implementers": r"QA commands implementers",
        "qa-directs-implementer": r"QA commands implementers",
        "nested-delegation": r"nested delegation authority",
        "qa-nested-delegation": r"nested delegation authority",
        "subagents-delegate": r"nested delegation authority",
        "subagents-invoke": r"nested delegation authority",
        "subagents-message": r"nested delegation authority",
        "subagent-delegates": r"nested delegation authority",
        "role-agents-define-subagent": r"nested delegation authority",
        "role-agent-defines-subagent": r"nested delegation authority",
        "qa-sends-messages": r"nested delegation authority",
        "static-role-agents-delegate": r"nested delegation authority",
        "implementer-invokes-subagent": r"nested delegation authority",
        "named-role-invokes-subagent": r"nested delegation authority",
        "memory-priority": r"memory authority inversion",
        "memory-authority": r"memory authority inversion",
        "fallback-recall-performed": r"memory isolation fallback bypass",
        "fallback-save-performed": r"memory isolation fallback bypass",
        "fallback-condition-negation": r"memory isolation fallback bypass",
        "condition-not-available-does-not-negate-recall": (
            r"memory isolation fallback bypass"
        ),
        "condition-not-enforced-does-not-negate-save": (
            r"memory isolation fallback bypass"
        ),
        "semicolon-keeps-fallback-condition": r"memory isolation fallback bypass",
        "unrelated-negation-does-not-mask-violation": (
            r"QA production edit authority"
        ),
        "same-clause-negation-before-new-qa-does-not-mask": (
            r"QA production edit authority"
        ),
        "qa-action-followed-by-unrelated-negation": (
            r"QA production edit authority"
        ),
        "qa-new-subject-after-negation": r"QA production edit authority",
        "ui-action-followed-by-unrelated-negation": r"UI gate bypass",
        "ui-action-then-unrelated-negation": r"UI gate bypass",
        "final-report-followed-by-unrelated-negation": (
            r"final user report before closeout"
        ),
        "passive-ui-implemented-before-gate": r"UI gate bypass",
        "antigravity-template-memory-inversion": r"memory authority inversion",
        "antigravity-template-early-report": r"final user report before closeout",
        "antigravity-template-role-nested-delegation": (
            r"nested delegation authority"
        ),
    }

    def run_validator(
        self,
        mode: str,
        root: Path | None = None,
        *,
        timeout: float = 20,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(PACK / "lib/validate_antigravity_artifacts.py"),
            mode,
            str(self.pack),
        ]
        if root is not None:
            command.append(str(root))
        return subprocess.run(
            command,
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )

    @staticmethod
    def replace_scalar(body: str, key: str, value: str) -> str:
        updated, count = re.subn(
            rf"^{re.escape(key)}:.*$",
            f"{key}: {value}",
            body,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise AssertionError(f"missing scalar field {key}")
        return updated

    @staticmethod
    def replace_list(body: str, key: str, values: tuple[str, ...]) -> str:
        replacement = f"{key}:\n" + "".join(f"  - {item}\n" for item in values)
        updated, count = re.subn(
            rf"(?m)^{re.escape(key)}:\n(?:  - [^\n]+\n)+",
            replacement,
            body,
            count=1,
        )
        if count != 1:
            raise AssertionError(f"missing list field {key}")
        return updated

    def agent_body(self, role: str) -> str:
        if role in self.IMPLEMENTERS:
            tools = self.IMPLEMENTER_TOOLS
            skills = ("skills/xy-build-verify",)
        elif role == "xy-uiux":
            tools = self.UIUX_TOOLS
            skills = ("skills/xy-prototype-verify",)
        elif role == "xy-qa":
            tools = self.QA_TOOLS
            skills = ("skills/xy-qa-review",)
        else:
            raise AssertionError(f"unexpected role fixture: {role}")
        tool_lines = "".join(f"  - {tool}\n" for tool in tools)
        skill_lines = "".join(f"  - {skill}\n" for skill in skills)
        boundary = ""
        if role == "xy-uiux":
            boundary = (
                "\nKeep prototypes stable, build-free, framework-independent and use one Page design and interaction contract.\n"
                "The contract contains purpose, navigation, interactions, states, and exceptions.\n"
                "Return concrete changed-page links and verified dependency fingerprints.\n"
                "The root index alone is insufficient.\n"
                "Prototype verification MUST NOT invoke Computer Use or `/browser` by default.\n"
                "Only an explicit user request or diagnosis of a user-reported prototype failure permits it.\n"
            )
        elif role == "xy-web":
            boundary = (
                "\nReuse existing components, tokens, conventions.\n"
                "Do not copy prototype-only mock data into production.\n"
                "Verify the page dependency fingerprint.\n"
            )
        elif role == "xy-qa":
            boundary = (
                "\nFinal QA outcome: PASS | FAIL. Report to the PM only.\n"
                "Do not edit production business code.\n"
                "Do not command implementers; the PM owns bounded rework.\n"
                "Prototype review MUST NOT invoke Computer Use or `/browser`.\n"
                "Risk-based browser inspection applies only to the real production implementation.\n"
                "Inspect a rendered frame ephemerally in memory only for that production check.\n"
                "QA must not persist, save, write, attach, present, or use it as approval evidence.\n"
            )
        return (
            "---\n"
            f"name: {role}\n"
            f"description: \"Strict fixture for {role}.\"\n"
            "tools:\n"
            f"{tool_lines}"
            "mainAgent: false\n"
            "subagent: true\n"
            "model: inherit\n"
            "commandExecutionPolicy: sandbox\n"
            "skills:\n"
            f"{skill_lines}"
            "---\n\n"
            "<!-- agent-workflow-pack:managed-antigravity-agent -->\n"
            f"# {role}\n"
            "Never use nested delegation. Return evidence to the PM.\n"
            f"{boundary}"
        )

    def make_artifact_tree(self, mode: str, name: str) -> Path:
        root = self.project / f"{mode}-{name}"
        if mode == "generated":
            fixture_files = {
                "apps/web/package.json": '{"dependencies":{"react":"19"}}',
                "apps/desktop/package.json": (
                    '{"main":"main.js","dependencies":{"electron":"40"}}'
                ),
                "apps/desktop/main.js": "export {};\n",
                "services/api/go.mod": "module example.test/api\n",
                "apps/apple/App.xcodeproj/project.pbxproj": (
                    "// !$*UTF8*$!\n"
                    "{\n"
                    "  objects = {\n"
                    "    A1 = {\n"
                    "      isa = PBXNativeTarget;\n"
                    '      productType = "com.apple.product-type.application";\n'
                    "    };\n"
                    "  };\n"
                    "}\n"
                ),
                "apps/android/build.gradle.kts": (
                    'plugins { id("com.android.application") }\n'
                ),
                "apps/android/src/main/AndroidManifest.xml": "<manifest/>\n",
            }
            for relative, content in fixture_files.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        if mode == "generated":
            agent_root = root / ".agents/agents"
            skill_root = root / ".agents/skills"
        elif mode == "staging":
            agent_root = root / "agents"
            skill_root = root / "skills"
        else:
            raise AssertionError(f"unexpected fixture mode: {mode}")
        agent_root.mkdir(parents=True)
        skill_root.mkdir(parents=True)
        for skill in SHARED_CORE_SKILLS:
            shutil.copytree(
                self.pack / "platforms/shared/skills" / skill,
                skill_root / skill,
            )
        for role in (*self.IMPLEMENTERS, "xy-uiux", "xy-qa"):
            (agent_root / f"{role}.md").write_text(
                self.agent_body(role),
                encoding="utf-8",
            )
        if mode == "staging":
            product = (
                self.pack / "platforms/shared/AGENTS.product.tpl"
            ).read_text(encoding="utf-8")
            (root / "AGENTS.product.block").write_text(
                "<!-- pack:product-begin -->\n"
                + product.rstrip("\n")
                + "\n<!-- pack:product-end -->\n",
                encoding="utf-8",
            )
            antigravity = (
                self.pack / "platforms/antigravity/AGENTS.antigravity.tpl"
            ).read_text(encoding="utf-8")
            (root / "AGENTS.antigravity.block").write_text(
                "<!-- pack:antigravity-begin -->\n"
                + antigravity.rstrip("\n")
                + "\n<!-- pack:antigravity-end -->\n",
                encoding="utf-8",
            )
        return root

    @staticmethod
    def artifact_agent(root: Path, mode: str, role: str) -> Path:
        prefix = Path(".agents/agents") if mode == "generated" else Path("agents")
        return root / prefix / f"{role}.md"

    def assert_rejected(
        self,
        result: subprocess.CompletedProcess[str],
        mutation: str,
    ) -> None:
        self.assertEqual(
            result.returncode,
            1,
            f"mutation must be a validator rejection (exit 1): {mutation}\n"
            f"{result.stdout}{result.stderr}",
        )
        self.assertTrue(
            result.stderr.strip(),
            f"mutation must produce a clear stderr diagnostic: {mutation}",
        )
        self.assertIn(
            "[ERROR]",
            result.stderr,
            f"mutation must use the validator error protocol: {mutation}",
        )
        self.assertNotIn(
            "Traceback",
            result.stderr,
            f"mutation must not leak a Python traceback: {mutation}",
        )

    def install_compliant_source_template(self) -> None:
        (self.pack / "platforms/antigravity/AGENTS.antigravity.tpl").write_text(
            self.COMPLIANT_TEMPLATE,
            encoding="utf-8",
        )

    def test_sources_mode_accepts_the_current_native_template(self) -> None:
        result = self.run_validator("sources")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sources_mode_rejects_every_reintroduced_legacy_ui_artifact_rule(
        self,
    ) -> None:
        template = self.pack / "platforms/antigravity/AGENTS.antigravity.tpl"
        original = template.read_text(encoding="utf-8")
        mutations = {
            "optional-screenshot": (
                "The PM may attach screenshots as optional visual approval evidence."
            ),
            "task-markdown": (
                "The designer should create a task-specific Markdown companion for each prototype."
            ),
            "manifest": "The designer should create a Manifest for prototype approval.",
            "isolated-task-prototype": "Create each UI task under prototypes/<task>/.",
            "root-only-confirmation": (
                "The root prototype index is sufficient for visual confirmation."
            ),
            "copy-prototype-runtime": (
                "Web implementers may copy prototype mock data and runtime into production."
            ),
            "third-qa-outcome": "Final QA outcome: PASS_WITH_NITS.",
            "persist-browser-frame": (
                "QA may save the rendered frame as approval evidence."
            ),
        }
        for name, statement in mutations.items():
            with self.subTest(mutation=name):
                try:
                    template.write_text(
                        original + "\n" + statement + "\n",
                        encoding="utf-8",
                    )
                    result = self.run_validator("sources")
                    self.assert_rejected(result, f"legacy-ui-source:{name}")
                    self.assertRegex(result.stderr, r"legacy UI artifact model")
                finally:
                    template.write_text(original, encoding="utf-8")

    def test_sources_mode_rejects_dynamic_scheduler_contract_drift(self) -> None:
        entry = self.pack / "platforms/shared/skills/xy-workflow/SKILL.md"
        mutations = (
            ("Dispatch all currently ready independent tasks", "Dispatch one task at a time"),
            ("Do not wait for\n   unrelated project work.", "Wait for all project work."),
            ("independent branches continue.", "independent branches wait."),
            (
                "dispatch exactly one integrated read-only `xy-qa` reviewer for this request",
                "dispatch module QA for every task",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                source = contract_file_containing(entry, old)
                original = source.read_text(encoding="utf-8")
                self.assertIn(old, original)
                try:
                    source.write_text(original.replace(old, new, 1), encoding="utf-8")
                    result = self.run_validator("sources")
                    self.assert_rejected(result, f"workflow-contract:{old}")
                finally:
                    source.write_text(original, encoding="utf-8")

    def test_sources_mode_rejects_a_hardcoded_routine_extra_confirmation(self) -> None:
        source = self.pack / "product/WORKFLOW.md"
        original = source.read_text(encoding="utf-8")
        try:
            source.write_text(
                original
                + "\nThe PM must obtain document approval from the user before implementation.\n",
                encoding="utf-8",
            )
            result = self.run_validator("sources")
            self.assert_rejected(result, "third-business-confirmation")
        finally:
            source.write_text(original, encoding="utf-8")

    def test_product_template_is_a_secure_semantic_source(self) -> None:
        product = self.pack / "platforms/shared/AGENTS.product.tpl"
        expected = {
            "symlink": r"(?i)(symlink|securely read)",
            "hardlink": r"(?i)hard link",
            "fifo": r"(?i)regular file",
            "duplicate-marker": r"(?i)(marker|managed block)",
            "authority-inversion": r"memory authority inversion",
            "wrong-host-alias": r"(?i)(host.*alias|\$xy|/xy)",
        }
        for mutation, diagnostic in expected.items():
            with self.subTest(mutation=mutation):
                backup: Path | None = None
                second_link: Path | None = None
                original: bytes | None = None
                try:
                    if mutation == "symlink":
                        backup = product.with_name("AGENTS.product.real.tpl")
                        product.rename(backup)
                        product.symlink_to(backup)
                    elif mutation == "hardlink":
                        second_link = product.with_name("AGENTS.product.second.tpl")
                        os.link(product, second_link)
                    elif mutation == "fifo":
                        backup = product.with_name("AGENTS.product.real.tpl")
                        product.rename(backup)
                        os.mkfifo(product)
                    else:
                        original = product.read_bytes()
                        text = original.decode("utf-8")
                        if mutation == "duplicate-marker":
                            text += "\n<!-- pack:product-begin -->\n"
                        elif mutation == "authority-inversion":
                            text += "\nMemory overrides current controlled documents and user approvals.\n"
                        else:
                            text += "\nUse /xy-workflow directly.\n"
                        product.write_text(text, encoding="utf-8")
                    result = self.run_validator("sources", timeout=2)
                    self.assert_rejected(result, f"product-source:{mutation}")
                    self.assertRegex(result.stderr, diagnostic)
                finally:
                    if second_link is not None and second_link.exists():
                        second_link.unlink()
                    if backup is not None:
                        if product.is_symlink() or product.is_fifo():
                            product.unlink()
                        backup.rename(product)
                    if original is not None:
                        product.write_bytes(original)

    def test_staging_blocks_are_secure_and_host_specific(self) -> None:
        mutations = (
            "product-symlink",
            "product-hardlink",
            "product-fifo",
            "product-duplicate-marker",
            "product-wrong-alias",
            "product-authority-inversion",
            "antigravity-wrong-alias",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                root = self.make_artifact_tree("staging", mutation)
                product = root / "AGENTS.product.block"
                antigravity = root / "AGENTS.antigravity.block"
                target = antigravity if mutation.startswith("antigravity") else product
                if mutation.endswith("symlink"):
                    real = target.with_suffix(".real")
                    target.rename(real)
                    target.symlink_to(real)
                elif mutation.endswith("hardlink"):
                    os.link(target, target.with_suffix(".second"))
                elif mutation.endswith("fifo"):
                    target.unlink()
                    os.mkfifo(target)
                else:
                    body = target.read_text(encoding="utf-8")
                    if mutation.endswith("duplicate-marker"):
                        body += "\n<!-- pack:product-begin -->\n"
                    elif mutation.endswith("wrong-alias"):
                        if mutation.startswith("antigravity"):
                            body = body.replace("/xy-workflow", "$xy-workflow", 1)
                        else:
                            body = body.replace("`xy-workflow`", "`/xy-workflow`", 1)
                    else:
                        body += "\nMemory overrides current controlled documents and user approvals.\n"
                    target.write_text(body, encoding="utf-8")
                result = self.run_validator("staging", root, timeout=2)
                self.assert_rejected(result, f"staging-block:{mutation}")

    def test_staging_skill_tree_exactly_matches_the_secure_source_snapshot(self) -> None:
        source_auxiliary = (
            self.pack
            / "platforms/shared/skills/xy-workflow/references/detail.md"
        )
        source_auxiliary.parent.mkdir(parents=True, exist_ok=True)
        source_auxiliary.write_text("trusted auxiliary bytes\n", encoding="utf-8")
        for mutation in (
            "changed-bytes",
            "extra-file",
            "symlink",
            "hardlink",
            "fifo",
            "wrong-type",
        ):
            with self.subTest(mutation=mutation):
                root = self.make_artifact_tree("staging", f"skill-{mutation}")
                auxiliary = root / "skills/xy-workflow/references/detail.md"
                if mutation == "changed-bytes":
                    auxiliary.write_text("tampered\n", encoding="utf-8")
                elif mutation == "extra-file":
                    auxiliary.with_name("extra.md").write_text("extra\n", encoding="utf-8")
                elif mutation == "symlink":
                    auxiliary.unlink()
                    auxiliary.symlink_to(source_auxiliary)
                elif mutation == "hardlink":
                    os.link(auxiliary, auxiliary.with_name("second.md"))
                elif mutation == "fifo":
                    auxiliary.unlink()
                    os.mkfifo(auxiliary)
                else:
                    auxiliary.unlink()
                    auxiliary.mkdir()
                result = self.run_validator("staging", root, timeout=2)
                self.assert_rejected(result, f"staging-skill:{mutation}")

    def test_sources_and_renderer_reject_malformed_single_quoted_description(
        self,
    ) -> None:
        roles_yaml = self.pack / "product/ROLES.yaml"
        original = roles_yaml.read_text(encoding="utf-8")
        roles_yaml.write_text(
            re.sub(
                r"(?m)^    description: Repository-driven Web engineer\..*$",
                "    description: 'bad'quote'",
                original,
                count=1,
            ),
            encoding="utf-8",
        )
        source_result = self.run_validator("sources")
        self.assert_rejected(source_result, "single-quoted-description")
        self.assertRegex(source_result.stderr, r"(?i)(description|single.quote)")
        renderer = subprocess.run(
            [
                sys.executable,
                str(self.pack / "lib/render_antigravity_agent.py"),
                str(self.pack),
                "xy-web",
            ],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(renderer.returncode, 1, renderer.stdout + renderer.stderr)
        self.assertEqual(renderer.stdout, "")
        self.assertIn("[ERROR]", renderer.stderr)
        self.assertNotIn("Traceback", renderer.stderr)

    def test_sources_mode_accepts_a_compliant_native_template(self) -> None:
        self.install_compliant_source_template()
        result = self.run_validator("sources")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_and_staging_modes_accept_strict_artifacts(self) -> None:
        self.install_compliant_source_template()
        for mode in ("generated", "staging"):
            with self.subTest(mode=mode):
                root = self.make_artifact_tree(mode, "valid")
                result = self.run_validator(mode, root)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_frontmatter_and_role_policy_mutations_are_rejected_by_cli(self) -> None:
        self.install_compliant_source_template()

        def add_tool(tool: str):
            return lambda body: self.replace_list(
                body,
                "tools",
                self.IMPLEMENTER_TOOLS + (tool,),
            )

        mutations = {
            "missing-opening-delimiter": (
                "xy-web",
                lambda body: body.removeprefix("---\n"),
            ),
            "missing-closing-delimiter": (
                "xy-web",
                lambda body: body.replace("\n---\n", "\n", 1),
            ),
            "malformed-silently-ignored-line": (
                "xy-web",
                lambda body: body.replace(
                    "description: \"Strict fixture for xy-web.\"\n",
                    "description: \"Strict fixture for xy-web.\"\nnot yaml\n",
                    1,
                ),
            ),
            "indented-fake-field": (
                "xy-web",
                lambda body: body.replace(
                    "description: \"Strict fixture for xy-web.\"\n",
                    "description: \"Strict fixture for xy-web.\"\n  fake: value\n",
                    1,
                ),
            ),
            "duplicate-key": (
                "xy-web",
                lambda body: body.replace(
                    "name: xy-web\n",
                    "name: xy-web\nname: xy-web\n",
                    1,
                ),
            ),
            "unknown-key": (
                "xy-web",
                lambda body: body.replace(
                    "model: inherit\n",
                    "model: inherit\nversion: 1\n",
                    1,
                ),
            ),
            "unclosed-description-quote": (
                "xy-web",
                lambda body: self.replace_scalar(
                    body,
                    "description",
                    '"unclosed',
                ),
            ),
            "unsafe-unquoted-description": (
                "xy-web",
                lambda body: self.replace_scalar(
                    body,
                    "description",
                    "unsafe: value # comment",
                ),
            ),
            "description-list": (
                "xy-web",
                lambda body: re.sub(
                    r"(?m)^description:.*$",
                    "description:\n  - disguised-list",
                    body,
                    count=1,
                ),
            ),
            "description-whitespace-only": (
                "xy-web",
                lambda body: self.replace_scalar(body, "description", '"   "'),
            ),
            "tools-not-list": (
                "xy-web",
                lambda body: re.sub(
                    r"(?m)^tools:\n(?:  - [^\n]+\n)+",
                    "tools: view_file\n",
                    body,
                    count=1,
                ),
            ),
            "skills-not-list": (
                "xy-web",
                lambda body: re.sub(
                    r"(?m)^skills:\n(?:  - [^\n]+\n)+",
                    "skills: skills/xy-build-verify\n",
                    body,
                    count=1,
                ),
            ),
            "invalid-list-item": (
                "xy-web",
                lambda body: self.replace_list(
                    body,
                    "tools",
                    self.IMPLEMENTER_TOOLS[:-1] + ("manage task",),
                ),
            ),
            "duplicate-list-item": (
                "xy-web",
                lambda body: self.replace_list(
                    body,
                    "tools",
                    self.IMPLEMENTER_TOOLS + ("view_file",),
                ),
            ),
            "invalid-skill-list-item": (
                "xy-web",
                lambda body: self.replace_list(
                    body,
                    "skills",
                    ("skills/xy build-verify",),
                ),
            ),
            "duplicate-skill-list-item": (
                "xy-web",
                lambda body: self.replace_list(
                    body,
                    "skills",
                    (
                        "skills/xy-build-verify",
                        "skills/xy-build-verify",
                    ),
                ),
            ),
            "boolean-string": (
                "xy-web",
                lambda body: self.replace_scalar(body, "mainAgent", '"false"'),
            ),
            "boolean-number": (
                "xy-web",
                lambda body: self.replace_scalar(body, "subagent", "1"),
            ),
            "name-file-mismatch": (
                "xy-web",
                lambda body: self.replace_scalar(body, "name", "xy-retired"),
            ),
            "underscore-name": (
                "xy-web",
                lambda body: self.replace_scalar(body, "name", "xy_web"),
            ),
            "unsupported-model": (
                "xy-web",
                lambda body: self.replace_scalar(body, "model", "unknown-tier"),
            ),
            "unsupported-policy": (
                "xy-web",
                lambda body: self.replace_scalar(
                    body,
                    "commandExecutionPolicy",
                    "eager",
                ),
            ),
            "unknown-tool": ("xy-web", add_tool("typo_tool")),
            "nested-invoke-subagent": ("xy-web", add_tool("invoke_subagent")),
            "nested-define-subagent": ("xy-web", add_tool("define_subagent")),
            "nested-send-message": ("xy-web", add_tool("send_message")),
            "qa-write-tool": (
                "xy-qa",
                lambda body: self.replace_list(
                    body,
                    "tools",
                    self.QA_TOOLS + ("write_to_file",),
                ),
            ),
            "missing-role-required-skill": (
                "xy-web",
                lambda body: self.replace_list(
                    body,
                    "skills",
                    ("skills/xy-qa-review",),
                ),
            ),
            "unresolved-skill-ref": (
                "xy-web",
                lambda body: self.replace_list(
                    body,
                    "skills",
                    ("skills/xy-does-not-exist",),
                ),
            ),
            "absolute-skill-ref": (
                "xy-web",
                lambda body: self.replace_list(
                    body,
                    "skills",
                    ("/skills/xy-build-verify",),
                ),
            ),
            "parent-skill-ref": (
                "xy-web",
                lambda body: self.replace_list(
                    body,
                    "skills",
                    ("skills/../xy-build-verify",),
                ),
            ),
        }
        expected_diagnostics = {
            "missing-opening-delimiter": r"missing opening Agent frontmatter",
            "missing-closing-delimiter": r"missing closing Agent frontmatter",
            "malformed-silently-ignored-line": r"malformed Agent frontmatter line",
            "indented-fake-field": r"malformed Agent frontmatter line",
            "duplicate-key": r"duplicate Agent frontmatter key",
            "unknown-key": r"unknown Agent frontmatter keys",
            "unclosed-description-quote": r"description must be a valid",
            "unsafe-unquoted-description": r"description must be a valid",
            "description-list": r"description must be a non-empty quoted string",
            "description-whitespace-only": r"description.*non-empty",
            "tools-not-list": r"tools must be a block list",
            "skills-not-list": r"skills must be a block list",
            "invalid-list-item": r"invalid tools list item",
            "duplicate-list-item": r"tools list contains duplicates",
            "invalid-skill-list-item": r"invalid skills list item",
            "duplicate-skill-list-item": r"skills list contains duplicates",
            "boolean-string": r"mainAgent must be a real boolean",
            "boolean-number": r"subagent must be a real boolean",
            "name-file-mismatch": r"name/file mismatch",
            "underscore-name": r"name must use lowercase hyphens",
            "unsupported-model": r"model must be inherit",
            "unsupported-policy": r"commandExecutionPolicy must be sandbox",
            "unknown-tool": r"unknown tools",
            "nested-invoke-subagent": r"nested delegation tools",
            "nested-define-subagent": r"nested delegation tools",
            "nested-send-message": r"nested delegation tools",
            "qa-write-tool": r"QA Agent must remain read-only",
            "missing-role-required-skill": r"skills must exactly match approved policy",
            "unresolved-skill-ref": r"unresolved Skill",
            "absolute-skill-ref": r"unsafe Skill reference",
            "parent-skill-ref": r"unsafe Skill reference",
        }
        self.assertEqual(set(mutations), set(expected_diagnostics))
        for mode in ("generated", "staging"):
            for name, (role, mutate) in mutations.items():
                with self.subTest(mode=mode, mutation=name):
                    root = self.make_artifact_tree(mode, name)
                    path = self.artifact_agent(root, mode, role)
                    path.write_text(
                        mutate(path.read_text(encoding="utf-8")),
                        encoding="utf-8",
                    )
                    result = self.run_validator(mode, root)
                    self.assert_rejected(result, f"{mode}:{name}")
                    self.assertRegex(result.stderr, expected_diagnostics[name])

    def test_semantic_source_mutations_are_rejected_with_positive_text_retained(
        self,
    ) -> None:
        self.install_compliant_source_template()
        mutations = {
            "memory-authority-inversion": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "\nRecalled memory overrides current controlled documents and user approvals.\n",
            ),
            "memory-isolation-fallback-bypass": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "\nWhen project isolation is unavailable, still call memory_recall and memory_save.\n",
            ),
            "ui-production-before-gates": (
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "\nProduction UI implementation may start before visual_approved.\n",
            ),
            "final-report-before-qa-closeout": (
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "\nReport the final result to the user before QA and memory closeout.\n",
            ),
            "qa-edits-production": (
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "\nQA should edit production business code directly after review.\n",
            ),
            "qa-commands-implementers": (
                "roles/xy-qa.md",
                "\nQA should command implementers directly and bypass PM routing.\n",
            ),
            "nested-delegation": (
                "product/GLOBAL_CONSTRAINTS.md",
                "\nSubagents may invoke_subagent, define_subagent, and send_message.\n",
            ),
            "antigravity-template-memory-inversion": (
                "platforms/antigravity/AGENTS.antigravity.tpl",
                "\nAgentmemory wins over current controlled documents and user approvals.\n",
            ),
            "antigravity-template-early-report": (
                "platforms/antigravity/AGENTS.antigravity.tpl",
                "\nSend the final user report before QA and memory closeout.\n",
            ),
            "antigravity-template-role-nested-delegation": (
                "platforms/antigravity/AGENTS.antigravity.tpl",
                "\nStatic role Agents may invoke_subagent and send_message.\n",
            ),
        }
        for name, (relative, appended) in mutations.items():
            with self.subTest(mutation=name):
                path = self.pack / relative
                original = path.read_text(encoding="utf-8")
                try:
                    path.write_text(original + appended, encoding="utf-8")
                    result = self.run_validator("sources")
                    self.assert_rejected(result, f"sources:{name}")
                    self.assertRegex(
                        result.stderr,
                        self.SEMANTIC_DIAGNOSTICS[name],
                    )
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_generated_qa_body_semantic_mutations_are_rejected(self) -> None:
        self.install_compliant_source_template()
        mutations = {
            "qa-edits-production": (
                "\nQA should edit production business code directly.\n"
            ),
            "qa-commands-implementers": (
                "\nQA should command implementers and bypass the PM.\n"
            ),
            "qa-nested-delegation": (
                "\nQA may invoke_subagent, define_subagent, and send_message.\n"
            ),
        }
        for mode in ("generated", "staging"):
            for name, appended in mutations.items():
                with self.subTest(mode=mode, mutation=name):
                    root = self.make_artifact_tree(mode, name)
                    qa = self.artifact_agent(root, mode, "xy-qa")
                    qa.write_text(
                        qa.read_text(encoding="utf-8") + appended,
                        encoding="utf-8",
                    )
                    result = self.run_validator(mode, root)
                    self.assert_rejected(result, f"{mode}:{name}")
                    self.assertRegex(
                        result.stderr,
                        self.SEMANTIC_DIAGNOSTICS[name],
                    )

    def test_agent_body_may_contain_markdown_frontmatter_delimiters(self) -> None:
        self.install_compliant_source_template()
        fenced_yaml = """

```yaml
---
task_id: example
---
```
"""
        for mode in ("generated", "staging"):
            with self.subTest(mode=mode):
                root = self.make_artifact_tree(mode, "body-delimiters")
                agent = self.artifact_agent(root, mode, "xy-uiux")
                agent.write_text(
                    agent.read_text(encoding="utf-8") + fenced_yaml,
                    encoding="utf-8",
                )
                result = self.run_validator(mode, root)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_direct_semantic_source_violations_are_rejected(self) -> None:
        self.install_compliant_source_template()
        mutations = {
            "ui-starts-before-gate": (
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "Production UI starts before visual_approved.",
            ),
            "ui-begins-before-gate": (
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "Production UI begins before visual_approved.",
            ),
            "qa-edits-production": (
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "QA edits production business code.",
            ),
            "qa-modifies-production": (
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "QA modifies production business code.",
            ),
            "qa-fixes-production": (
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "QA fixes production business code.",
            ),
            "qa-commands-implementers": (
                "roles/xy-qa.md",
                "QA commands implementers.",
            ),
            "qa-dispatches-implementers": (
                "roles/xy-qa.md",
                "QA dispatches implementers.",
            ),
            "qa-assigns-implementers": (
                "roles/xy-qa.md",
                "QA assigns implementers.",
            ),
            "subagents-delegate": (
                "product/GLOBAL_CONSTRAINTS.md",
                "Subagents delegate to another Agent.",
            ),
            "subagents-invoke": (
                "product/GLOBAL_CONSTRAINTS.md",
                "Subagents invoke_subagent for follow-up work.",
            ),
            "subagents-message": (
                "product/GLOBAL_CONSTRAINTS.md",
                "Subagents send_message to child roles.",
            ),
            "memory-priority": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "Memory has priority over current controlled documents.",
            ),
            "memory-authority": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "Memory has authority over controlled docs.",
            ),
            "fallback-recall-performed": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "When project isolation is unavailable, memory_recall is performed.",
            ),
            "fallback-save-performed": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "When project isolation is unavailable, memory_save is performed.",
            ),
            "unrelated-negation-does-not-mask-violation": (
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "QA must not ignore logs, but QA edits production business code.",
            ),
            "same-clause-negation-before-new-qa-does-not-mask": (
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "QA must not ignore logs and QA edits production business code.",
            ),
            "qa-action-followed-by-unrelated-negation": (
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "QA edits production business code and does not report it.",
            ),
            "ui-action-followed-by-unrelated-negation": (
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "Production UI starts before visual_approved and must not skip tests.",
            ),
            "final-report-followed-by-unrelated-negation": (
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "The final user report occurs before QA and should not omit evidence.",
            ),
            "condition-not-available-does-not-negate-recall": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "When project isolation is not available, memory_recall is performed.",
            ),
            "condition-not-enforced-does-not-negate-save": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "When project filtering is not enforced, memory_save is used.",
            ),
            "semicolon-keeps-fallback-condition": (
                "platforms/shared/skills/xy-project-memory/SKILL.md",
                "Project isolation is unavailable; memory_recall is performed.",
            ),
            "qa-pronoun-edits-production": (
                "platforms/shared/skills/xy-qa-review/SKILL.md",
                "QA is the auditor; it edits production business code.",
            ),
            "role-agents-define-subagent": (
                "product/GLOBAL_CONSTRAINTS.md",
                "Role Agents may define_subagent.",
            ),
            "qa-sends-messages": (
                "roles/xy-qa.md",
                "QA sends messages to child roles.",
            ),
            "static-role-agents-delegate": (
                "product/GLOBAL_CONSTRAINTS.md",
                "Static role Agents delegate follow-up work.",
            ),
            "implementer-invokes-subagent": (
                "product/GLOBAL_CONSTRAINTS.md",
                "The implementer may invoke_subagent for follow-up work.",
            ),
            "named-role-invokes-subagent": (
                "product/GLOBAL_CONSTRAINTS.md",
                "xy-web may invoke_subagent for follow-up work.",
            ),
            "qa-directs-implementer": (
                "roles/xy-qa.md",
                "QA directs the implementer to patch production code.",
            ),
            "passive-ui-implemented-before-gate": (
                "platforms/shared/skills/xy-workflow/SKILL.md",
                "Production UI may be implemented before visual_approved.",
            ),
        }
        for name, (relative, statement) in mutations.items():
            with self.subTest(mutation=name):
                path = self.pack / relative
                original = path.read_text(encoding="utf-8")
                try:
                    path.write_text(original + "\n" + statement + "\n", encoding="utf-8")
                    result = self.run_validator("sources")
                    self.assert_rejected(result, f"sources:{name}")
                    self.assertRegex(
                        result.stderr,
                        self.SEMANTIC_DIAGNOSTICS[name],
                    )
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_direct_semantic_artifact_violations_are_rejected(self) -> None:
        self.install_compliant_source_template()
        mutations = {
            "ui-starts-before-gate": (
                "xy-uiux",
                "Production UI starts before visual_approved.",
            ),
            "qa-edits-production": (
                "xy-qa",
                "QA edits production business code.",
            ),
            "qa-commands-implementers": (
                "xy-qa",
                "QA commands implementers.",
            ),
            "subagent-delegates": (
                "xy-web",
                "Subagents delegate to another Agent.",
            ),
            "memory-priority": (
                "xy-web",
                "Memory has priority over controlled documents.",
            ),
            "fallback-recall-performed": (
                "xy-web",
                "When project isolation is unavailable, memory_recall is performed.",
            ),
            "qa-new-subject-after-negation": (
                "xy-qa",
                "QA must not ignore logs and QA edits production business code.",
            ),
            "ui-action-then-unrelated-negation": (
                "xy-uiux",
                "Production UI starts before visual_approved and must not skip tests.",
            ),
            "fallback-condition-negation": (
                "xy-web",
                "When project filtering is not enforced, memory_save is used.",
            ),
            "role-agent-defines-subagent": (
                "xy-web",
                "Role Agents may define_subagent.",
            ),
            "qa-sends-messages": (
                "xy-qa",
                "QA sends messages to child roles.",
            ),
            "implementer-invokes-subagent": (
                "xy-web",
                "The implementer may invoke_subagent for follow-up work.",
            ),
            "named-role-invokes-subagent": (
                "xy-web",
                "xy-web may invoke_subagent for follow-up work.",
            ),
            "qa-directs-implementer": (
                "xy-qa",
                "QA directs the implementer to patch production code.",
            ),
            "passive-ui-implemented-before-gate": (
                "xy-uiux",
                "Production UI may be implemented before visual_approved.",
            ),
        }
        for mode in ("generated", "staging"):
            for name, (role, statement) in mutations.items():
                with self.subTest(mode=mode, mutation=name):
                    root = self.make_artifact_tree(mode, name)
                    agent = self.artifact_agent(root, mode, role)
                    agent.write_text(
                        agent.read_text(encoding="utf-8") + "\n" + statement + "\n",
                        encoding="utf-8",
                    )
                    result = self.run_validator(mode, root)
                    self.assert_rejected(result, f"{mode}:{name}")
                    self.assertRegex(
                        result.stderr,
                        self.SEMANTIC_DIAGNOSTICS[name],
                    )

    def test_explicit_semantic_negations_are_accepted(self) -> None:
        self.install_compliant_source_template()
        safe_source_rules = {
            "platforms/shared/skills/xy-workflow/SKILL.md": (
                "Production UI must not start before visual_approved.\n"
            ),
            "platforms/shared/skills/xy-qa-review/SKILL.md": (
                "QA must never edit, modify, or fix production business code.\n"
            ),
            "roles/xy-qa.md": (
                "QA does not command, dispatch, or assign implementers.\n"
            ),
            "product/GLOBAL_CONSTRAINTS.md": (
                "Subagents are forbidden to delegate, invoke_subagent, or send_message.\n"
            ),
            "platforms/shared/skills/xy-project-memory/SKILL.md": (
                "Memory must not have priority or authority over controlled documents.\n"
                "When project isolation is unavailable, recall and save must not be performed.\n"
            ),
        }
        for relative, appended in safe_source_rules.items():
            path = self.pack / relative
            path.write_text(
                path.read_text(encoding="utf-8") + "\n" + appended,
                encoding="utf-8",
            )
        result = self.run_validator("sources")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        safe_agent_rules = (
            "Production UI must not begin before visual_approved.\n"
            "QA is prohibited from editing or fixing production business code.\n"
            "QA must not command or dispatch implementers.\n"
            "Subagents never delegate, invoke_subagent, define_subagent, or send_message.\n"
            "Memory must not have authority over controlled documents.\n"
            "When project isolation is unavailable, memory_recall and memory_save must not be performed.\n"
            "Static role Agents receive work when the PM calls invoke_subagent.\n"
            "Role Agents are invoked by the PM through invoke_subagent.\n"
            "QA receives bounded rework when the PM uses send_message.\n"
            "The PM may use define_subagent; static roles must never delegate.\n"
            "The PM tells subagents not to delegate.\n"
            "Subagents are instructed not to invoke_subagent.\n"
            "Production UI shouldn't start before visual_approved.\n"
            "Memory doesn't override controlled documents.\n"
        )
        for mode in ("generated", "staging"):
            with self.subTest(mode=mode):
                root = self.make_artifact_tree(mode, "safe-negations")
                qa = self.artifact_agent(root, mode, "xy-qa")
                qa.write_text(
                    qa.read_text(encoding="utf-8") + "\n" + safe_agent_rules,
                    encoding="utf-8",
                )
                result = self.run_validator(mode, root)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pm_owned_nested_tool_sentences_are_accepted_in_sources(self) -> None:
        self.install_compliant_source_template()
        template = self.pack / "platforms/antigravity/AGENTS.antigravity.tpl"
        body = read_contract(template)
        # PM 的完整细则从入口真实引用读取；角色不得委派的语义仍按原规则检查。
        self.assertIn("Only the PM may use", body)
        self.assertIn("`invoke_subagent`; role Agents never delegate", body)
        result = self.run_validator("sources")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def artifact_nodes(self, root: Path, mode: str) -> dict[str, Path]:
        if mode == "generated":
            agent_root = root / ".agents/agents"
            skill_root = root / ".agents/skills"
        else:
            agent_root = root / "agents"
            skill_root = root / "skills"
        return {
            "artifact-root": root,
            "agent-root": agent_root,
            "agent-file": agent_root / "xy-web.md",
            "skills-root": skill_root,
            "skill-dir": skill_root / "xy-build-verify",
            "skill-file": skill_root / "xy-build-verify/SKILL.md",
        }

    def replace_with_symlink(
        self,
        root: Path,
        path: Path,
        scope: str,
        identity: str,
    ) -> None:
        is_directory = path.is_dir()
        if scope == "internal" and path != root:
            target = root / ".validator-link-targets" / identity
        elif scope == "internal":
            target = self.project / f"contained-{identity}"
        else:
            target = Path(self.temporary.name) / "Outside" / identity
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)
        path.symlink_to(target, target_is_directory=is_directory)

    def test_artifact_symlink_components_are_rejected_inside_and_outside_root(
        self,
    ) -> None:
        self.install_compliant_source_template()
        node_names = (
            "artifact-root",
            "agent-root",
            "agent-file",
            "skills-root",
            "skill-dir",
            "skill-file",
        )
        for mode in ("generated", "staging"):
            for scope in ("internal", "external"):
                for node_name in node_names:
                    with self.subTest(mode=mode, scope=scope, node=node_name):
                        identity = f"{mode}-{scope}-{node_name}"
                        root = self.make_artifact_tree(mode, identity)
                        path = self.artifact_nodes(root, mode)[node_name]
                        self.replace_with_symlink(root, path, scope, identity)
                        result = self.run_validator(mode, root)
                        self.assert_rejected(result, identity)
                        self.assertRegex(
                            result.stderr,
                            r"(?i)(symlink|real directory|no-follow|outside project root)",
                        )

    def test_artifact_file_types_links_and_markers_are_strict(self) -> None:
        self.install_compliant_source_template()
        expected_diagnostics = {
            "hardlink": r"(?i)hard link",
            "special": r"(?i)regular file",
            "directory": r"(?i)regular file",
            "marker-substring": r"(?i)managed marker",
            "marker-duplicate": r"(?i)managed marker",
        }
        for mode in ("generated", "staging"):
            for artifact in ("agent", "skill"):
                for mutation in (
                    "hardlink",
                    "special",
                    "directory",
                    "marker-substring",
                    "marker-duplicate",
                ):
                    with self.subTest(mode=mode, artifact=artifact, mutation=mutation):
                        identity = f"{mode}-{artifact}-{mutation}"
                        root = self.make_artifact_tree(mode, identity)
                        nodes = self.artifact_nodes(root, mode)
                        path = nodes["agent-file" if artifact == "agent" else "skill-file"]
                        marker = (
                            "<!-- agent-workflow-pack:managed-antigravity-agent -->"
                            if artifact == "agent"
                            else "<!-- agent-workflow-pack:managed-skill -->"
                        )
                        if mutation == "hardlink":
                            os.link(path, path.with_name(path.name + ".second-link"))
                        elif mutation == "special":
                            path.unlink()
                            os.mkfifo(path)
                        elif mutation == "directory":
                            path.unlink()
                            path.mkdir()
                        elif mutation == "marker-substring":
                            path.write_text(
                                path.read_text(encoding="utf-8").replace(
                                    marker,
                                    f"prefix {marker} suffix",
                                    1,
                                ),
                                encoding="utf-8",
                            )
                        else:
                            path.write_text(
                                path.read_text(encoding="utf-8") + "\n" + marker + "\n",
                                encoding="utf-8",
                            )
                        result = self.run_validator(mode, root)
                        self.assert_rejected(result, identity)
                        self.assertRegex(
                            result.stderr,
                            expected_diagnostics[mutation],
                        )

    def test_shared_source_skill_paths_links_and_markers_are_strict(self) -> None:
        self.install_compliant_source_template()
        source_root = self.pack / "platforms/shared/skills"
        source_dir = source_root / "xy-build-verify"
        source_file = source_dir / "SKILL.md"
        marker = "<!-- agent-workflow-pack:managed-skill -->"
        expected_diagnostics = {
            "root-symlink": r"(?i)(source root|real directory|securely open)",
            "directory-symlink": r"(?i)(unexpected node|real directory|securely open)",
            "file-symlink": r"(?i)symlink",
            "file-hardlink": r"(?i)hard link",
            "file-special": r"(?i)special file",
            "marker-substring": r"(?i)managed marker",
            "marker-duplicate": r"(?i)managed marker",
        }

        for mutation in (
            "root-symlink",
            "directory-symlink",
            "file-symlink",
            "file-hardlink",
            "file-special",
            "marker-substring",
            "marker-duplicate",
        ):
            with self.subTest(mutation=mutation):
                restore: tuple[Path, Path] | None = None
                restore_text: tuple[Path, str] | None = None
                second_link: Path | None = None
                try:
                    if mutation == "root-symlink":
                        backup = source_root.with_name("skills-real")
                        source_root.rename(backup)
                        source_root.symlink_to(backup, target_is_directory=True)
                        restore = (source_root, backup)
                    elif mutation == "directory-symlink":
                        backup = source_dir.with_name("xy-build-verify-real")
                        source_dir.rename(backup)
                        source_dir.symlink_to(backup, target_is_directory=True)
                        restore = (source_dir, backup)
                    elif mutation == "file-symlink":
                        backup = source_file.with_name("SKILL.real.md")
                        source_file.rename(backup)
                        source_file.symlink_to(backup)
                        restore = (source_file, backup)
                    elif mutation == "file-hardlink":
                        second_link = source_file.with_name("SKILL.second.md")
                        os.link(source_file, second_link)
                    elif mutation == "file-special":
                        backup = source_file.with_name("SKILL.real.md")
                        source_file.rename(backup)
                        os.mkfifo(source_file)
                        restore = (source_file, backup)
                    elif mutation == "marker-substring":
                        original = source_file.read_text(encoding="utf-8")
                        source_file.write_text(
                            original.replace(marker, f"prefix {marker} suffix", 1),
                            encoding="utf-8",
                        )
                        restore_text = (source_file, original)
                    else:
                        original = source_file.read_text(encoding="utf-8")
                        source_file.write_text(
                            original + "\n" + marker + "\n",
                            encoding="utf-8",
                        )
                        restore_text = (source_file, original)
                    result = self.run_validator("sources")
                    self.assert_rejected(result, f"source:{mutation}")
                    self.assertRegex(
                        result.stderr,
                        expected_diagnostics[mutation],
                    )
                finally:
                    if second_link is not None and second_link.exists():
                        second_link.unlink()
                    if restore is not None:
                        link, backup = restore
                        if link.is_symlink() or link.exists():
                            link.unlink()
                        backup.rename(link)
                    if restore_text is not None:
                        path, original = restore_text
                        path.write_text(original, encoding="utf-8")

    def test_pack_root_must_be_a_real_directory(self) -> None:
        self.install_compliant_source_template()
        backup = self.pack.with_name("agent_workflow-real")
        self.pack.rename(backup)
        self.pack.symlink_to(backup, target_is_directory=True)
        try:
            result = self.run_validator("sources")
            self.assert_rejected(result, "source:pack-root-symlink")
            self.assertRegex(result.stderr, r"(?i)(pack root|symlink|real directory)")
        finally:
            self.pack.unlink()
            backup.rename(self.pack)

    def test_semantic_source_paths_are_secure_and_nonblocking(self) -> None:
        self.install_compliant_source_template()
        source = self.pack / "roles/xy-qa.md"
        mutations = (
            "internal-symlink",
            "external-symlink",
            "hardlink",
            "fifo",
            "directory",
        )
        expected_diagnostics = {
            "internal-symlink": r"(?i)(symlink|securely read)",
            "external-symlink": r"(?i)(symlink|securely read)",
            "hardlink": r"(?i)hard link",
            "fifo": r"(?i)regular file",
            "directory": r"(?i)regular file",
        }
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                backup: Path | None = None
                second_link: Path | None = None
                try:
                    if mutation == "internal-symlink":
                        backup = source.with_name("xy-qa-real.md")
                        source.rename(backup)
                        source.symlink_to(backup)
                    elif mutation == "external-symlink":
                        external = Path(self.temporary.name) / "Outside" / "xy-qa.md"
                        external.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, external)
                        backup = source.with_name("xy-qa-real.md")
                        source.rename(backup)
                        source.symlink_to(external)
                    elif mutation == "hardlink":
                        second_link = source.with_name("xy-qa-second.md")
                        os.link(source, second_link)
                    elif mutation == "fifo":
                        backup = source.with_name("xy-qa-real.md")
                        source.rename(backup)
                        os.mkfifo(source)
                    else:
                        backup = source.with_name("xy-qa-real.md")
                        source.rename(backup)
                        source.mkdir()

                    result = self.run_validator("sources", timeout=2)
                    self.assert_rejected(result, f"semantic-source:{mutation}")
                    self.assertRegex(
                        result.stderr,
                        expected_diagnostics[mutation],
                    )
                finally:
                    if second_link is not None and second_link.exists():
                        second_link.unlink()
                    if backup is not None:
                        if source.is_symlink() or source.is_fifo() or source.is_file():
                            source.unlink()
                        elif source.is_dir():
                            source.rmdir()
                        backup.rename(source)

    def test_invalid_utf8_inputs_are_controlled_rejections(self) -> None:
        self.install_compliant_source_template()

        semantic_source = self.pack / "roles/xy-qa.md"
        semantic_original = semantic_source.read_bytes()
        try:
            semantic_source.write_bytes(b"\xff\xfeinvalid semantic source")
            result = self.run_validator("sources")
            self.assert_rejected(result, "semantic-source:invalid-utf8")
            self.assertRegex(result.stderr, r"(?i)UTF-8")
        finally:
            semantic_source.write_bytes(semantic_original)

        for mode in ("generated", "staging"):
            for artifact in ("agent", "skill"):
                with self.subTest(mode=mode, artifact=artifact):
                    root = self.make_artifact_tree(mode, f"invalid-utf8-{artifact}")
                    nodes = self.artifact_nodes(root, mode)
                    path = nodes[
                        "agent-file" if artifact == "agent" else "skill-file"
                    ]
                    path.write_bytes(b"\xff\xfeinvalid artifact")
                    result = self.run_validator(mode, root)
                    self.assert_rejected(result, f"{mode}:{artifact}:invalid-utf8")
                    self.assertRegex(result.stderr, r"(?i)UTF-8")


class SharedCoreSkillTest(AntigravityFixtureMixin, unittest.TestCase):
    def shared_skills_root(self) -> Path:
        return PACK / "platforms/shared/skills"

    def run_codex(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "agent_workflow/setup_codex.sh", *arguments],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )

    def run_codex_with_failpoint(
        self,
        failpoint: str,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["AGENT_WORKFLOW_PACK_TEST_FAILPOINT"] = failpoint
        return subprocess.run(
            ["bash", "agent_workflow/setup_codex.sh", *arguments],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
            env=environment,
        )

    def add_workflow_resource(self, relative: str, body: str) -> Path:
        source = (
            self.pack
            / "platforms/shared/skills/xy-workflow"
            / relative
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(body, encoding="utf-8")
        return source

    def assert_no_codex_project_writes(self) -> None:
        self.assertFalse((self.project / "AGENTS.md").exists())
        self.assertFalse((self.project / ".codex").exists())
        self.assertFalse((self.project / "docs").exists())

    @staticmethod
    def managed_skill_fixture(name: str) -> str:
        return f"""---
name: {name}
description: Managed stale Skill fixture.
---

<!-- agent-workflow-pack:managed-skill -->
"""

    def test_shared_source_contains_exactly_the_seven_core_skills(self) -> None:
        root = self.shared_skills_root()
        self.assertTrue(root.is_dir(), f"missing shared Skill source: {root}")
        discovered = {
            path.parent.name for path in root.glob("*/SKILL.md") if path.is_file()
        }
        self.assertEqual(SHARED_CORE_SKILLS, discovered)

    def test_antigravity_stage_copy_uses_one_descriptor_anchored_snapshot(
        self,
    ) -> None:
        from lib import shared_core_skills

        self.assertTrue(
            hasattr(shared_core_skills, "stage_shared_core_skills"),
            "shared loader must expose descriptor-anchored staging",
        )
        auxiliary = (
            self.pack
            / "platforms/shared/skills/xy-workflow/references/anchored.md"
        )
        auxiliary.parent.mkdir(parents=True, exist_ok=True)
        trusted = b"trusted descriptor bytes\n"
        auxiliary.write_bytes(trusted)
        staged = self.project / "descriptor-staged-skills"
        staged.mkdir()
        original_read = shared_core_skills._read_descriptor
        swapped = False

        def read_then_swap(
            descriptor: int,
            path: Path,
            label: str,
        ) -> bytes:
            nonlocal swapped
            body = original_read(descriptor, path, label)
            if path == auxiliary and not swapped:
                replacement = auxiliary.with_name("anchored.replacement.md")
                replacement.write_bytes(b"path replacement after descriptor read\n")
                os.replace(replacement, auxiliary)
                swapped = True
            return body

        with mock.patch.object(
            shared_core_skills,
            "_read_descriptor",
            side_effect=read_then_swap,
        ):
            shared_core_skills.stage_shared_core_skills(self.pack, staged)

        self.assertTrue(swapped)
        self.assertEqual(
            (staged / "xy-workflow/references/anchored.md").read_bytes(),
            trusted,
        )
        self.assertEqual(
            auxiliary.read_bytes(),
            b"path replacement after descriptor read\n",
        )
        self.assertFalse(
            any(
                path.name == ".agent-workflow-pack-state.json"
                for path in staged.rglob("*")
            )
        )

    def test_antigravity_stage_copy_cli_copies_complete_tree_without_state(self) -> None:
        auxiliary = (
            self.pack
            / "platforms/shared/skills/xy-workflow/references/complete.md"
        )
        auxiliary.parent.mkdir(parents=True, exist_ok=True)
        auxiliary.write_text("complete tree\n", encoding="utf-8")
        staged = self.project / "cli-staged-skills"
        staged.mkdir()
        result = subprocess.run(
            [
                sys.executable,
                str(self.pack / "lib/shared_core_skills.py"),
                "stage-copy",
                str(self.pack),
                str(staged),
            ],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (staged / "xy-workflow/references/complete.md").read_bytes(),
            auxiliary.read_bytes(),
        )
        self.assertFalse(
            any(
                path.name == ".agent-workflow-pack-state.json"
                for path in staged.rglob("*")
            )
        )

    def test_codex_bootstrap_keeps_dollar_skill_aliases(self) -> None:
        shared = (
            self.pack / "platforms/shared/AGENTS.product.tpl"
        ).read_text(encoding="utf-8")
        result = self.run_codex()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        generated = self.read("AGENTS.md")
        self.assertNotRegex(shared, r"(?<![A-Za-z0-9._-])(?:\$|/)xy-[a-z0-9-]+\b(?!/)")
        self.assertIn("`$xy-workflow`", generated)
        self.assertIn("`$xy-project-memory`", read_bootstrap_contract(self.project / "AGENTS.md", self.pack))
        self.assertNotIn("`/xy-workflow`", generated)

    def test_manifest_is_the_single_shared_core_skill_name_authority(self) -> None:
        manifest = PACK / "platforms/shared/core-skills.txt"
        self.assertTrue(manifest.is_file(), f"missing core Skill manifest: {manifest}")
        names = {
            line.strip()
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(SHARED_CORE_SKILLS, names)

    def test_loader_does_not_reopen_skill_after_validation(self) -> None:
        """A checked inode cannot be replaced before its frontmatter is read."""

        from lib import shared_core_skills

        source = (
            self.pack
            / "platforms/shared/skills/xy-build-verify/SKILL.md"
        )
        outside = self.project / "outside-valid-xy-build-verify.md"
        outside.write_bytes(source.read_bytes())
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                "name: xy-build-verify",
                "name: xy-malicious",
                1,
            ),
            encoding="utf-8",
        )
        hidden = source.with_name("SKILL.malicious.md")
        original_require = shared_core_skills._require_regular_file
        original_read_bytes = Path.read_bytes
        swapped = False

        def swap_after_check(path: Path, label: str):
            nonlocal swapped
            info = original_require(path, label)
            if path == source:
                source.rename(hidden)
                source.symlink_to(outside)
                swapped = True
            return info

        def restore_after_reopen(path: Path) -> bytes:
            nonlocal swapped
            body = original_read_bytes(path)
            if path == source and swapped:
                source.unlink()
                hidden.rename(source)
                swapped = False
            return body

        try:
            with mock.patch.object(
                shared_core_skills,
                "_require_regular_file",
                side_effect=swap_after_check,
            ), mock.patch.object(Path, "read_bytes", new=restore_after_reopen):
                with self.assertRaisesRegex(
                    shared_core_skills.SharedCoreSkillError,
                    r"skill name mismatch for xy-build-verify",
                ):
                    shared_core_skills.load_shared_core_skills(self.pack)
        finally:
            if source.is_symlink():
                source.unlink()
            if hidden.exists():
                hidden.rename(source)

    def test_setup_codex_uses_only_the_shared_core_skill_source(self) -> None:
        legacy = "platforms/codex" + "/skills"
        setup_body = (PACK / "setup_codex.sh").read_text(encoding="utf-8")
        validator_body = (PACK / "lib/validate_project_config.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'CODEX_SKILLS_SRC="${PLATFORMS_DIR}/shared/skills"',
            setup_body,
        )
        self.assertIn('shared_core_skills.py" list', setup_body)
        for relative, body in (
            ("setup_codex.sh", setup_body),
            ("lib/validate_project_config.py", validator_body),
        ):
            with self.subTest(relative=relative):
                self.assertNotIn(legacy, body)

    def test_every_shared_core_skill_has_the_managed_marker(self) -> None:
        root = self.shared_skills_root()
        self.assertTrue(root.is_dir(), f"missing shared Skill source: {root}")
        for skill in sorted(SHARED_CORE_SKILLS):
            with self.subTest(skill=skill):
                source = root / skill / "SKILL.md"
                self.assertTrue(source.is_file(), f"missing shared Skill: {source}")
                self.assertIn(
                    "<!-- agent-workflow-pack:managed-skill -->",
                    source.read_text(encoding="utf-8"),
                )
                self.assertEqual(
                    1,
                    sum(
                        line == "<!-- agent-workflow-pack:managed-skill -->"
                        for line in source.read_text(encoding="utf-8").splitlines()
                    ),
                )

    def test_codex_generated_core_skills_match_shared_sources_byte_for_byte(
        self,
    ) -> None:
        root = self.pack / "platforms/shared/skills"
        self.assertTrue(root.is_dir(), f"missing shared Skill source: {root}")
        result = self.run_codex()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for skill in sorted(SHARED_CORE_SKILLS):
            with self.subTest(skill=skill):
                source = root / skill / "SKILL.md"
                generated = self.project / ".agents/skills" / skill / "SKILL.md"
                self.assertTrue(
                    generated.is_file(), f"missing generated Skill: {generated}"
                )
                self.assertEqual(source.read_bytes(), generated.read_bytes())

    def test_codex_setup_rejects_invalid_skill_listed_in_the_manifest(self) -> None:
        manifest = self.pack / "platforms/shared/core-skills.txt"
        self.assertTrue(manifest.is_file(), f"missing core Skill manifest: {manifest}")
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + "xy-invalid\n",
            encoding="utf-8",
        )
        extra = self.pack / "platforms/shared/skills/xy-invalid/SKILL.md"
        extra.parent.mkdir(parents=True)
        extra.write_text(
            """---
name: wrong-name
description: Deliberately invalid shared source fixture.
---

<!-- agent-workflow-pack:managed-skill -->
""",
            encoding="utf-8",
        )
        result = self.run_codex()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skill name mismatch for xy-invalid", result.stdout + result.stderr)
        self.assert_no_codex_project_writes()

    def test_codex_preflight_rejects_an_unlisted_shared_skill_source(self) -> None:
        extra = self.pack / "platforms/shared/skills/xy-unlisted/SKILL.md"
        extra.parent.mkdir(parents=True)
        extra.write_text(
            """---
name: xy-unlisted
description: Unlisted shared source fixture.
---

<!-- agent-workflow-pack:managed-skill -->
""",
            encoding="utf-8",
        )
        result = self.run_codex("--preflight")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "unexpected shared core Skill source: xy-unlisted",
            result.stdout + result.stderr,
        )
        self.assertFalse((self.project / ".agents").exists())

    def test_codex_preflight_rejects_a_missing_manifest_skill_source(self) -> None:
        shutil.rmtree(self.pack / "platforms/shared/skills/xy-build-verify")
        result = self.run_codex("--preflight")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "missing shared core Skill source: xy-build-verify",
            result.stdout + result.stderr,
        )
        self.assertFalse((self.project / ".agents").exists())

    def test_marker_substring_does_not_transfer_user_skill_ownership(self) -> None:
        skill_dir = self.project / ".agents/skills/xy-workflow"
        skill_dir.mkdir(parents=True)
        user_body = """---
name: xy-workflow
description: User-owned workflow.
---

This user note mentions agent-workflow-pack:managed-skill as plain text.
"""
        skill_file = skill_dir / "SKILL.md"
        sentinel = skill_dir / "USER-NOTES.md"
        skill_file.write_text(user_body, encoding="utf-8")
        sentinel.write_text("preserve me\n", encoding="utf-8")

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(user_body, skill_file.read_text(encoding="utf-8"))
        self.assertEqual("preserve me\n", sentinel.read_text(encoding="utf-8"))
        self.assert_no_codex_project_writes()

    def test_stale_managed_skill_with_user_content_fails_without_deleting(self) -> None:
        skill_dir = self.project / ".agents/skills/xy-obsolete"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        sentinel = skill_dir / "USER-NOTES.md"
        managed_body = self.managed_skill_fixture("xy-obsolete")
        skill_file.write_text(managed_body, encoding="utf-8")
        sentinel.write_text("preserve me\n", encoding="utf-8")

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(managed_body, skill_file.read_text(encoding="utf-8"))
        self.assertEqual("preserve me\n", sentinel.read_text(encoding="utf-8"))
        self.assert_no_codex_project_writes()

    def test_marker_only_stale_skill_without_current_state_is_preserved(self) -> None:
        skill_dir = self.project / ".agents/skills/xy-obsolete"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            self.managed_skill_fixture("xy-obsolete"),
            encoding="utf-8",
        )
        skill_file.chmod(0o640)
        body_before = skill_file.read_bytes()
        file_before = skill_file.stat(follow_symlinks=False)
        directory_before = skill_dir.stat(follow_symlinks=False)

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("has no managed state", result.stdout + result.stderr)
        self.assertEqual(body_before, skill_file.read_bytes())
        file_after = skill_file.stat(follow_symlinks=False)
        directory_after = skill_dir.stat(follow_symlinks=False)
        self.assertEqual(
            (file_before.st_dev, file_before.st_ino, file_before.st_mode),
            (file_after.st_dev, file_after.st_ino, file_after.st_mode),
        )
        self.assertEqual(
            (directory_before.st_dev, directory_before.st_ino, directory_before.st_mode),
            (directory_after.st_dev, directory_after.st_ino, directory_after.st_mode),
        )
        self.assertEqual([skill_file], list(skill_dir.iterdir()))
        self.assertFalse((self.project / "AGENTS.md").exists())
        self.assertFalse((self.project / ".codex").exists())
        self.assertFalse((self.project / "docs").exists())

    def test_existing_named_directory_without_skill_is_a_user_collision(self) -> None:
        skill_dir = self.project / ".agents/skills/xy-workflow"
        skill_dir.mkdir(parents=True)
        sentinel = skill_dir / "USER-NOTES.md"
        sentinel.write_text("preserve me\n", encoding="utf-8")

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual("preserve me\n", sentinel.read_text(encoding="utf-8"))
        self.assert_no_codex_project_writes()

    def test_manifest_whitespace_comments_and_blank_lines_are_normalized_once(self) -> None:
        manifest = self.pack / "platforms/shared/core-skills.txt"
        manifest.write_text(
            """# Shared core Skills

  grill-me
  xy-build-verify  
xy-project-memory
  xy-prototype-verify

xy-qa-review  
xy-plan
xy-workflow
""",
            encoding="utf-8",
        )

        first = self.run_codex()
        second = self.run_codex()
        check = self.run_codex("--check")

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        for skill in SHARED_CORE_SKILLS:
            self.assertTrue(
                (self.project / ".agents/skills" / skill / "SKILL.md").is_file()
            )

    def test_duplicate_manifest_entry_fails_before_project_writes(self) -> None:
        manifest = self.pack / "platforms/shared/core-skills.txt"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + "xy-workflow\n",
            encoding="utf-8",
        )

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "duplicate shared core Skill in manifest: xy-workflow",
            result.stdout + result.stderr,
        )
        self.assert_no_codex_project_writes()

    def test_manifest_loader_failure_is_not_swallowed(self) -> None:
        loader = self.pack / "lib/shared_core_skills.py"
        loader.write_text("raise SystemExit(23)\n", encoding="utf-8")

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_no_codex_project_writes()

    def test_setup_reuses_one_cached_normalized_manifest_collection(self) -> None:
        body = (PACK / "setup_codex.sh").read_text(encoding="utf-8")
        self.assertIn("CORE_SKILLS=()", body)
        self.assertIn("load_core_skills_once", body)
        self.assertNotIn("core_skill_is_listed", body)
        self.assertNotIn("< <(core_skill_names)", body)

    def test_source_tree_symlink_is_rejected_before_project_writes(self) -> None:
        outside = self.project / "outside-source.txt"
        outside.write_text("outside\n", encoding="utf-8")
        resources = self.pack / "platforms/shared/skills/xy-workflow/resources"
        resources.mkdir()
        (resources / "escape").symlink_to(outside)

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual("outside\n", outside.read_text(encoding="utf-8"))
        self.assert_no_codex_project_writes()

    def test_source_tree_fifo_is_rejected_by_preflight(self) -> None:
        fifo = self.pack / "platforms/shared/skills/xy-workflow/source.pipe"
        os.mkfifo(fifo)

        result = self.run_codex("--preflight")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_no_codex_project_writes()

    def test_unexpected_regular_file_in_source_root_is_rejected(self) -> None:
        unexpected = self.pack / "platforms/shared/skills/README.txt"
        unexpected.write_text("not a Skill directory\n", encoding="utf-8")

        result = self.run_codex("--preflight")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "unexpected node in shared core Skill source root: README.txt",
            result.stdout + result.stderr,
        )
        self.assert_no_codex_project_writes()

    def test_source_root_allows_a_regular_ds_store_file(self) -> None:
        metadata = self.pack / "platforms/shared/skills/.DS_Store"
        metadata.write_bytes(b"fixture metadata")

        setup = self.run_codex()
        check = self.run_codex("--check")

        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_target_skill_symlink_is_rejected_before_project_writes(self) -> None:
        skill_dir = self.project / ".agents/skills/xy-workflow"
        skill_dir.mkdir(parents=True)
        target = self.pack / "platforms/shared/skills/xy-workflow/SKILL.md"
        (skill_dir / "SKILL.md").symlink_to(target)

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((skill_dir / "SKILL.md").is_symlink())
        self.assert_no_codex_project_writes()

    def test_check_rejects_a_matching_target_skill_symlink(self) -> None:
        setup = self.run_codex()
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        target = self.project / ".agents/skills/xy-workflow/SKILL.md"
        target.unlink()
        target.symlink_to(
            self.pack / "platforms/shared/skills/xy-workflow/SKILL.md"
        )

        check = self.run_codex("--check")

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertTrue(target.is_symlink())

    def test_target_skill_type_collision_is_rejected_before_project_writes(self) -> None:
        target = self.project / ".agents/skills/xy-workflow/SKILL.md"
        target.mkdir(parents=True)

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(target.is_dir())
        self.assert_no_codex_project_writes()

    def test_auxiliary_skill_tree_is_copied_and_checked(self) -> None:
        resources = {
            "references/guide.md": "# Shared guide\n",
            "references/nested/checklist.txt": "verify nested resources\n",
            "scripts/verify.sh": "#!/usr/bin/env bash\nexit 0\n",
        }
        for relative, body in resources.items():
            self.add_workflow_resource(relative, body)

        setup = self.run_codex()
        check = self.run_codex("--check")

        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        for relative, body in resources.items():
            with self.subTest(relative=relative):
                generated = (
                    self.project
                    / ".agents/skills/xy-workflow"
                    / relative
                )
                self.assertTrue(generated.is_file())
                self.assertFalse(generated.is_symlink())
                self.assertEqual(body, generated.read_text(encoding="utf-8"))

    def test_managed_auxiliary_file_can_upgrade_from_v1_to_v2(self) -> None:
        source = self.add_workflow_resource(
            "references/guide.md",
            "pack version one\n",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        generated = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        source.write_text("pack version two\n", encoding="utf-8")

        second = self.run_codex()
        check = self.run_codex("--check")

        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertEqual("pack version two\n", generated.read_text(encoding="utf-8"))

    def test_user_modified_managed_auxiliary_file_blocks_upgrade(self) -> None:
        source = self.add_workflow_resource(
            "references/guide.md",
            "pack version one\n",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        generated = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        generated.write_text("user mutation\n", encoding="utf-8")
        source.write_text("pack version two\n", encoding="utf-8")
        agents_before = (self.project / "AGENTS.md").read_bytes()

        second = self.run_codex()

        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual("user mutation\n", generated.read_text(encoding="utf-8"))
        self.assertEqual(agents_before, (self.project / "AGENTS.md").read_bytes())

    def test_removed_managed_auxiliary_file_is_cleaned_during_upgrade(self) -> None:
        # 只清理本测试新增的资源目录；正式生命周期 reference 仍应保留。
        source = self.add_workflow_resource(
            "references/upgrade-only/guide.md",
            "pack version one\n",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        generated = (
            self.project
            / ".agents/skills/xy-workflow/references/upgrade-only/guide.md"
        )
        self.assertTrue(generated.is_file())
        source.unlink()
        source.parent.rmdir()

        second = self.run_codex()
        check = self.run_codex("--check")

        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertFalse(generated.exists())
        self.assertFalse(generated.parent.exists())

    def test_marker_only_skill_without_current_state_is_a_user_collision(self) -> None:
        skill_dir = self.project / ".agents/skills/xy-workflow"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        shutil.copy2(
            self.pack / "platforms/shared/skills/xy-workflow/SKILL.md",
            skill_file,
        )
        skill_file.chmod(0o640)
        body_before = skill_file.read_bytes()
        file_before = skill_file.stat(follow_symlinks=False)
        directory_before = skill_dir.stat(follow_symlinks=False)

        setup = self.run_codex()

        self.assertNotEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        self.assertIn("has no managed state", setup.stdout + setup.stderr)
        self.assertEqual(body_before, skill_file.read_bytes())
        file_after = skill_file.stat(follow_symlinks=False)
        directory_after = skill_dir.stat(follow_symlinks=False)
        self.assertEqual(
            (file_before.st_dev, file_before.st_ino, file_before.st_mode),
            (file_after.st_dev, file_after.st_ino, file_after.st_mode),
        )
        self.assertEqual(
            (directory_before.st_dev, directory_before.st_ino, directory_before.st_mode),
            (directory_after.st_dev, directory_after.st_ino, directory_after.st_mode),
        )
        self.assertEqual([skill_file], list(skill_dir.iterdir()))
        self.assertFalse((self.project / "AGENTS.md").exists())
        self.assertFalse((self.project / ".codex").exists())
        self.assertFalse((self.project / "docs").exists())

    def test_inventory_owned_stale_skill_tree_is_removed_safely(self) -> None:
        obsolete = self.pack / "platforms/shared/skills/xy-obsolete"
        obsolete.mkdir()
        (obsolete / "SKILL.md").write_text(
            self.managed_skill_fixture("xy-obsolete"),
            encoding="utf-8",
        )
        resource = obsolete / "references/guide.md"
        resource.parent.mkdir()
        resource.write_text("# Shared guide\n", encoding="utf-8")
        manifest = self.pack / "platforms/shared/core-skills.txt"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + "xy-obsolete\n",
            encoding="utf-8",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        skill_dir = self.project / ".agents/skills/xy-obsolete"
        self.assertTrue((skill_dir / "references/guide.md").is_file())
        manifest.write_text(
            "\n".join(
                line
                for line in manifest.read_text(encoding="utf-8").splitlines()
                if line.strip() != "xy-obsolete"
            )
            + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(obsolete)

        second = self.run_codex()

        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertFalse(skill_dir.exists())

    def test_inventory_stale_tree_with_user_extra_fails_and_is_preserved(self) -> None:
        obsolete = self.pack / "platforms/shared/skills/xy-obsolete"
        obsolete.mkdir()
        (obsolete / "SKILL.md").write_text(
            self.managed_skill_fixture("xy-obsolete"),
            encoding="utf-8",
        )
        resource = obsolete / "references/guide.md"
        resource.parent.mkdir()
        resource.write_text("# Shared guide\n", encoding="utf-8")
        manifest = self.pack / "platforms/shared/core-skills.txt"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + "xy-obsolete\n",
            encoding="utf-8",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        skill_dir = self.project / ".agents/skills/xy-obsolete"
        sentinel = skill_dir / "USER-NOTES.md"
        sentinel.write_text("preserve me\n", encoding="utf-8")
        manifest.write_text(
            "\n".join(
                line
                for line in manifest.read_text(encoding="utf-8").splitlines()
                if line.strip() != "xy-obsolete"
            )
            + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(obsolete)

        second = self.run_codex()

        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual("preserve me\n", sentinel.read_text(encoding="utf-8"))
        self.assertTrue((skill_dir / "references/guide.md").is_file())
        self.assertTrue(
            (skill_dir / ".agent-workflow-pack-state.json").is_file()
        )

    def test_check_rejects_a_missing_auxiliary_skill_file(self) -> None:
        self.add_workflow_resource("references/guide.md", "# Shared guide\n")
        setup = self.run_codex()
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        generated = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        if generated.exists():
            generated.unlink()

        check = self.run_codex("--check")

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_check_rejects_a_tampered_auxiliary_skill_file(self) -> None:
        self.add_workflow_resource("references/guide.md", "# Shared guide\n")
        setup = self.run_codex()
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        generated = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("user mutation\n", encoding="utf-8")

        check = self.run_codex("--check")

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_check_rejects_an_extra_auxiliary_skill_file(self) -> None:
        setup = self.run_codex()
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        extra = (
            self.project
            / ".agents/skills/xy-workflow/references/local-note.md"
        )
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("user extra\n", encoding="utf-8")

        check = self.run_codex("--check")

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_existing_auxiliary_file_collision_fails_before_project_writes(self) -> None:
        source = self.add_workflow_resource(
            "references/guide.md",
            "# Pack guide\n",
        )
        skill_dir = self.project / ".agents/skills/xy-workflow"
        guide = skill_dir / "references/guide.md"
        guide.parent.mkdir(parents=True)
        shutil.copy2(
            self.pack / "platforms/shared/skills/xy-workflow/SKILL.md",
            skill_dir / "SKILL.md",
        )
        guide.write_text("user-owned guide\n", encoding="utf-8")
        sentinel = skill_dir / "zz-user-sentinel.md"
        sentinel.write_text("preserve me\n", encoding="utf-8")

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual("# Pack guide\n", source.read_text(encoding="utf-8"))
        self.assertEqual("user-owned guide\n", guide.read_text(encoding="utf-8"))
        self.assertEqual("preserve me\n", sentinel.read_text(encoding="utf-8"))
        self.assert_no_codex_project_writes()

    def test_target_auxiliary_symlink_fails_before_project_writes(self) -> None:
        self.add_workflow_resource("references/guide.md", "# Shared guide\n")
        outside = self.project / "outside-target.txt"
        outside.write_text("outside\n", encoding="utf-8")
        skill_dir = self.project / ".agents/skills/xy-workflow"
        target = skill_dir / "references/guide.md"
        target.parent.mkdir(parents=True)
        shutil.copy2(
            self.pack / "platforms/shared/skills/xy-workflow/SKILL.md",
            skill_dir / "SKILL.md",
        )
        target.symlink_to(outside)

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(target.is_symlink())
        self.assertEqual("outside\n", outside.read_text(encoding="utf-8"))
        self.assert_no_codex_project_writes()

    def test_check_rejects_a_matching_auxiliary_symlink(self) -> None:
        source = self.add_workflow_resource(
            "references/guide.md",
            "# Shared guide\n",
        )
        setup = self.run_codex()
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        target = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        if target.exists():
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)

        check = self.run_codex("--check")

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertTrue(target.is_symlink())

    def test_check_rejects_an_auxiliary_special_file(self) -> None:
        self.add_workflow_resource("references/guide.md", "# Shared guide\n")
        setup = self.run_codex()
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        target = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        if target.exists():
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(target)

        check = self.run_codex("--check")

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_source_auxiliary_hard_link_fails_before_project_writes(self) -> None:
        outside = Path(self.temporary.name) / "USER-OUTSIDE.txt"
        outside.write_text("outside source\n", encoding="utf-8")
        source = (
            self.pack
            / "platforms/shared/skills/xy-workflow/references/guide.md"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        os.link(outside, source)

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual("outside source\n", outside.read_text(encoding="utf-8"))
        self.assert_no_codex_project_writes()

    def test_source_skill_hard_link_fails_before_project_writes(self) -> None:
        source = self.pack / "platforms/shared/skills/xy-workflow/SKILL.md"
        outside = Path(self.temporary.name) / "USER-SOURCE-SKILL.md"
        shutil.copy2(source, outside)
        source.unlink()
        os.link(outside, source)

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(source.read_bytes(), outside.read_bytes())
        self.assert_no_codex_project_writes()

    def test_external_target_auxiliary_hard_link_cannot_be_overwritten(self) -> None:
        source = self.add_workflow_resource(
            "references/guide.md",
            "pack version one\n",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        target = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        outside = Path(self.temporary.name) / "USER-OUTSIDE.txt"
        outside.write_text("pack version one\n", encoding="utf-8")
        target.unlink()
        os.link(outside, target)
        outside_inode = outside.stat().st_ino

        check = self.run_codex("--check")
        source.write_text("pack version two\n", encoding="utf-8")
        second = self.run_codex()

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual("pack version one\n", outside.read_text(encoding="utf-8"))
        self.assertEqual(outside_inode, outside.stat().st_ino)

    def test_project_internal_target_auxiliary_hard_link_is_rejected(self) -> None:
        self.add_workflow_resource("references/guide.md", "pack version one\n")
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        target = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        sentinel = self.project / "USER-INTERNAL.txt"
        sentinel.write_text("pack version one\n", encoding="utf-8")
        target.unlink()
        os.link(sentinel, target)

        check = self.run_codex("--check")
        second = self.run_codex()

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual("pack version one\n", sentinel.read_text(encoding="utf-8"))

    def test_target_skill_hard_link_cannot_modify_external_inode(self) -> None:
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        target = self.project / ".agents/skills/xy-workflow/SKILL.md"
        outside = Path(self.temporary.name) / "USER-OUTSIDE-SKILL.md"
        shutil.copy2(target, outside)
        target.unlink()
        os.link(outside, target)
        outside_before = outside.read_bytes()

        check = self.run_codex("--check")
        source = self.pack / "platforms/shared/skills/xy-workflow/SKILL.md"
        source.write_text(
            source.read_text(encoding="utf-8") + "\nPack upgrade fixture.\n",
            encoding="utf-8",
        )
        second = self.run_codex()

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(outside_before, outside.read_bytes())

    def test_target_state_hard_link_is_rejected(self) -> None:
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        state = (
            self.project
            / ".agents/skills/xy-workflow/.agent-workflow-pack-state.json"
        )
        outside = Path(self.temporary.name) / "USER-OUTSIDE-STATE.json"
        shutil.copy2(state, outside)
        state.unlink()
        os.link(outside, state)
        outside_before = outside.read_bytes()

        check = self.run_codex("--check")
        second = self.run_codex()

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(outside_before, outside.read_bytes())

    def test_noncanonical_source_paths_fail_before_any_write(self) -> None:
        invalid_paths = {
            "backslash": "references/bad\\name.md",
            "zero-width": "references/bad\u200bname.md",
            "trailing-space": "references/bad-name.md ",
        }
        for name, relative in invalid_paths.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix=f"agent-workflow-source-path-{name}-"
            ) as temp:
                project = Path(temp) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(
                    PACK,
                    pack,
                    ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
                    symlinks=True,
                )
                shutil.copy2(
                    pack / "templates/project.yaml.example",
                    pack / "project.yaml",
                )
                config = pack / "project.yaml"
                config.write_text(
                    config.read_text(encoding="utf-8").replace(
                        "replace-with-unique-project-id",
                        f"invalid-source-path-{name}",
                    ),
                    encoding="utf-8",
                )
                source = pack / "platforms/shared/skills/xy-workflow" / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("invalid path fixture\n", encoding="utf-8")

                result = subprocess.run(
                    ["bash", "agent_workflow/setup_codex.sh"],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )

                self.assertNotEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )
                self.assertFalse((project / "AGENTS.md").exists())
                self.assertFalse((project / ".agents").exists())
                self.assertFalse((project / ".codex").exists())
                self.assertFalse((project / "docs").exists())

    def test_interrupted_update_recovers_from_managed_journal(self) -> None:
        source = self.add_workflow_resource(
            "references/guide.md",
            "pack version one\n",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source.write_text("pack version two\n", encoding="utf-8")

        interrupted = self.run_codex_with_failpoint(
            "update-after-first-stage-file"
        )
        incomplete_check = self.run_codex("--check")
        recovered = self.run_codex()
        final_check = self.run_codex("--check")

        self.assertNotEqual(
            interrupted.returncode,
            0,
            interrupted.stdout + interrupted.stderr,
        )
        self.assertNotEqual(
            incomplete_check.returncode,
            0,
            incomplete_check.stdout + incomplete_check.stderr,
        )
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertEqual(final_check.returncode, 0, final_check.stdout + final_check.stderr)
        generated = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        self.assertEqual("pack version two\n", generated.read_text(encoding="utf-8"))

    def test_interrupted_copy_temp_is_recovered_from_its_transaction(self) -> None:
        source = self.add_workflow_resource(
            "references/guide.md",
            "pack version one\n",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source.write_text("pack version two\n", encoding="utf-8")

        interrupted = self.run_codex_with_failpoint(
            "update-after-copy-temp-created"
        )
        self.assertNotEqual(
            interrupted.returncode,
            0,
            interrupted.stdout + interrupted.stderr,
        )
        stage = (
            self.project
            / ".agents/skills/.agent-workflow-pack-stage--xy-workflow"
        )
        managed_temps = list(
            stage.rglob(".agent-workflow-pack-temp--copy--*")
        )
        self.assertEqual(1, len(managed_temps), managed_temps)

        incomplete_check = self.run_codex("--check")
        recovered = self.run_codex()
        final_check = self.run_codex("--check")

        self.assertNotEqual(
            incomplete_check.returncode,
            0,
            incomplete_check.stdout + incomplete_check.stderr,
        )
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertEqual(final_check.returncode, 0, final_check.stdout + final_check.stderr)
        generated = (
            self.project
            / ".agents/skills/xy-workflow/references/guide.md"
        )
        self.assertEqual("pack version two\n", generated.read_text(encoding="utf-8"))
        artifacts = list(
            (self.project / ".agents/skills").rglob(".agent-workflow-pack-*--*")
        )
        self.assertEqual([], artifacts)

    def test_forged_copy_temp_is_preserved_and_blocks_recovery(self) -> None:
        source = self.add_workflow_resource(
            "references/guide.md",
            "pack version one\n",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source.write_text("pack version two\n", encoding="utf-8")

        interrupted = self.run_codex_with_failpoint(
            "update-after-copy-temp-created"
        )
        self.assertNotEqual(
            interrupted.returncode,
            0,
            interrupted.stdout + interrupted.stderr,
        )
        stage = (
            self.project
            / ".agents/skills/.agent-workflow-pack-stage--xy-workflow"
        )
        managed_temps = list(
            stage.rglob(".agent-workflow-pack-temp--copy--*")
        )
        self.assertEqual(1, len(managed_temps), managed_temps)
        nonce = managed_temps[0].name.split("--")[2]
        forged = (
            stage
            / "references"
            / f".agent-workflow-pack-temp--copy--{nonce}--{'f' * 64}"
        )
        sentinel = b"user sentinel must survive\n"
        forged.write_bytes(sentinel)

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sentinel, forged.read_bytes())
        self.assertTrue(managed_temps[0].is_file())

    def test_interrupted_stale_rename_is_resumed_safely(self) -> None:
        obsolete = self.pack / "platforms/shared/skills/xy-obsolete"
        obsolete.mkdir()
        (obsolete / "SKILL.md").write_text(
            self.managed_skill_fixture("xy-obsolete"),
            encoding="utf-8",
        )
        resource = obsolete / "references/guide.md"
        resource.parent.mkdir()
        resource.write_text("obsolete managed resource\n", encoding="utf-8")
        manifest = self.pack / "platforms/shared/core-skills.txt"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + "xy-obsolete\n",
            encoding="utf-8",
        )
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        manifest.write_text(
            "\n".join(
                line
                for line in manifest.read_text(encoding="utf-8").splitlines()
                if line.strip() != "xy-obsolete"
            )
            + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(obsolete)

        interrupted = self.run_codex_with_failpoint("stale-after-rename")
        incomplete_check = self.run_codex("--check")
        recovered = self.run_codex()
        final_check = self.run_codex("--check")

        self.assertNotEqual(
            interrupted.returncode,
            0,
            interrupted.stdout + interrupted.stderr,
        )
        self.assertNotEqual(
            incomplete_check.returncode,
            0,
            incomplete_check.stdout + incomplete_check.stderr,
        )
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertEqual(final_check.returncode, 0, final_check.stdout + final_check.stderr)
        self.assertFalse((self.project / ".agents/skills/xy-obsolete").exists())
        artifacts = list(
            (self.project / ".agents/skills").glob(
                ".agent-workflow-pack-*--xy-obsolete*"
            )
        )
        self.assertEqual([], artifacts)

    def test_orphan_state_without_skill_is_rejected_by_check(self) -> None:
        first = self.run_codex()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        workflow = self.project / ".agents/skills/xy-workflow"
        orphan = self.project / ".agents/skills/xy-orphan"
        orphan.mkdir()
        shutil.copy2(
            workflow / ".agent-workflow-pack-state.json",
            orphan / ".agent-workflow-pack-state.json",
        )

        check = self.run_codex("--check")

        self.assertNotEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertTrue((orphan / ".agent-workflow-pack-state.json").is_file())

    def test_unknown_journal_and_tombstone_fail_without_deleting_user_content(self) -> None:
        skills_root = self.project / ".agents/skills"
        skills_root.mkdir(parents=True)
        journal = skills_root / ".agent-workflow-pack-journal--xy-workflow.json"
        tombstone = skills_root / ".agent-workflow-pack-tombstone--xy-workflow"
        journal.write_text('{"user": "owned"}\n', encoding="utf-8")
        tombstone.mkdir()
        sentinel = tombstone / "USER-NOTES.md"
        sentinel.write_text("preserve me\n", encoding="utf-8")

        result = self.run_codex()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual('{"user": "owned"}\n', journal.read_text(encoding="utf-8"))
        self.assertEqual("preserve me\n", sentinel.read_text(encoding="utf-8"))
        self.assert_no_codex_project_writes()

    def test_implicit_description_scalars_fail_before_any_write(self) -> None:
        invalid_scalars = {
            "true": "true",
            "false": "false",
            "null": "null",
            "tilde-null": "~",
            "integer": "123",
            "negative-integer": "-42",
            "float": "1.25",
            "exponent": "6.02e23",
            "date": "2026-08-10",
            "time": "12:34:56",
            "timestamp": "2026-08-10T12:34:56Z",
            "invalid-single-quote": "'bad'quote'",
        }
        for name, scalar in invalid_scalars.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix=f"agent-workflow-description-{name}-"
            ) as temp:
                project = Path(temp) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(
                    PACK,
                    pack,
                    ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
                    symlinks=True,
                )
                shutil.copy2(
                    pack / "templates/project.yaml.example",
                    pack / "project.yaml",
                )
                config = pack / "project.yaml"
                config.write_text(
                    config.read_text(encoding="utf-8").replace(
                        "replace-with-unique-project-id",
                        f"invalid-description-{name}",
                    ),
                    encoding="utf-8",
                )
                source = pack / "platforms/shared/skills/xy-workflow/SKILL.md"
                source.write_text(
                    re.sub(
                        r"^description:.*$",
                        f"description: {scalar}",
                        source.read_text(encoding="utf-8"),
                        count=1,
                        flags=re.MULTILINE,
                    ),
                    encoding="utf-8",
                )

                result = subprocess.run(
                    ["bash", "agent_workflow/setup_codex.sh"],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )

                self.assertNotEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )
                self.assertFalse((project / "AGENTS.md").exists())
                self.assertFalse((project / ".agents").exists())
                self.assertFalse((project / ".codex").exists())
                self.assertFalse((project / "docs").exists())

    def test_invalid_shared_skill_frontmatter_is_rejected_before_any_write(self) -> None:
        mutations = {
            "duplicate-name": lambda body: body.replace(
                "name: xy-workflow\n",
                "name: xy-workflow\nname: xy-workflow\n",
                1,
            ),
            "duplicate-description": lambda body: re.sub(
                r"^(description:.*)$",
                r"\1\ndescription: duplicate",
                body,
                count=1,
                flags=re.MULTILINE,
            ),
            "missing-opening": lambda body: body.removeprefix("---\n"),
            "missing-closing": lambda body: body.replace("\n---\n", "\n", 1),
            "unknown-field": lambda body: body.replace(
                "name: xy-workflow\n",
                "name: xy-workflow\nversion: 1\n",
                1,
            ),
            "empty-description": lambda body: re.sub(
                r"^description:.*$",
                "description:",
                body,
                count=1,
                flags=re.MULTILINE,
            ),
            "wrong-name": lambda body: body.replace(
                "name: xy-workflow\n",
                "name: xy-wrong\n",
                1,
            ),
            "invalid-line": lambda body: body.replace(
                "name: xy-workflow\n",
                "name: xy-workflow\nnot valid frontmatter\n",
                1,
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix=f"agent-workflow-shared-frontmatter-{name}-"
            ) as temp:
                project = Path(temp) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(
                    PACK,
                    pack,
                    ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
                    symlinks=True,
                )
                shutil.copy2(
                    pack / "templates/project.yaml.example",
                    pack / "project.yaml",
                )
                config = pack / "project.yaml"
                config.write_text(
                    config.read_text(encoding="utf-8").replace(
                        "replace-with-unique-project-id",
                        f"shared-frontmatter-{name}",
                    ),
                    encoding="utf-8",
                )
                source = pack / "platforms/shared/skills/xy-workflow/SKILL.md"
                source.write_text(
                    mutate(source.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )

                result = subprocess.run(
                    ["bash", "agent_workflow/setup_codex.sh"],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )

                self.assertNotEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )
                self.assertFalse((project / "AGENTS.md").exists())
                self.assertFalse((project / ".agents").exists())
                self.assertFalse((project / ".codex").exists())
                self.assertFalse((project / "docs").exists())

    def test_shared_core_skills_use_host_neutral_dispatch_language(self) -> None:
        root = self.shared_skills_root()
        self.assertTrue(root.is_dir(), f"missing shared Skill source: {root}")
        bodies = {
            skill: read_contract(root / skill / "SKILL.md")
            for skill in SHARED_CORE_SKILLS
        }
        combined = "\n".join(bodies.values())
        for forbidden in (
            "let Codex match",
            "spawn_agent",
            "wait_agent",
            "send_message",
            "Codex dispatch",
            "Codex tool",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)

        workflow = bodies["xy-workflow"]
        self.assertIn("Activate `xy-project-memory`", workflow)
        self.assertIn("Activate `xy-build-verify`", workflow)
        self.assertIn("Codex: `$xy-project-memory`", workflow)
        self.assertIn(
            "Antigravity CLI: `/xy-project-memory`",
            workflow,
        )
        self.assertNotIn("Run `$xy-project-memory`", workflow)
        self.assertNotIn("returns `$xy-build-verify`", workflow)


if __name__ == "__main__":
    unittest.main()
