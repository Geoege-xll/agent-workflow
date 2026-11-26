from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

import lib.project.project_discovery as project_discovery
from lib.project.project_discovery import (
    DiscoveryError,
    DiscoveryOverrides,
    ModuleOverride,
    ModuleProfile,
    ProjectProfile,
    VerificationCommand,
    discover_project,
)
from lib.validate_project_docs import validate as validate_project_docs


PACK = Path(__file__).resolve().parents[1]


class ProjectDocumentModelContractTest(unittest.TestCase):
    """PROJECT 只索引当前功能；删除墓碑可检索但不得继续成为当前真相。"""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-doc-model-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.docs = self.root / "docs"
        self.plans = self.docs / "plans"
        self.plans.mkdir(parents=True)
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
            "  plans: docs/plans/\n",
            encoding="utf-8",
        )

    @staticmethod
    def active_feature(feature_id: str) -> str:
        # 当前事实必须有明确基线和已有证据；completed 不能代替验收。
        return (f"# 主题\n- 主题 ID: `{feature_id}`\n- 阶段: `active`\n- 模块: `.`\n"
                "- 任务等级: `Full`\n- 已验收版本: `v1`\n\n"
                "## 目标与范围\n当前目标。\n## 需求与验收\n明确验收。\n"
                "## 方案与原型关联\n现有方案。\n## 当前进展与恢复入口\n无剩余工作。\n"
                "## 验收结果与当前已交付行为\n已有查询行为。\n"
                "## 批准依据与必要证据\n- 批准依据: 既有用户批准记录\n- 验收证据: 既有验收记录\n")

    @classmethod
    def removed_feature(cls, feature_id: str) -> str:
        return cls.active_feature(feature_id).replace("阶段: `active`", "阶段: `removed`").replace(
            "已有查询行为。", "历史查询行为；2026-08-15已验收删除，替代为新查询。")

    def test_active_links_and_unlinked_removed_tombstones_are_valid(self) -> None:
        (self.plans / "open-chat.md").write_text(
            self.active_feature("FEATURE-OPENCHAT"), encoding="utf-8"
        )
        (self.plans / "legacy-search.md").write_text(
            self.removed_feature("FEATURE-LEGACY-SEARCH"), encoding="utf-8"
        )
        (self.docs / "PROJECT.md").write_text(
            "# Project\n\n[OpenChat](plans/open-chat.md)\n", encoding="utf-8"
        )

        self.assertEqual([], validate_project_docs(self.config, self.root))

    def test_unlinked_topic_is_allowed_but_linked_removed_baseline_fails(self) -> None:
        (self.plans / "open-chat.md").write_text(
            self.active_feature("FEATURE-OPENCHAT"), encoding="utf-8"
        )
        (self.plans / "legacy.md").write_text(
            self.removed_feature("FEATURE-LEGACY"), encoding="utf-8"
        )
        (self.docs / "PROJECT.md").write_text(
            "# Project\n\n[Legacy](plans/legacy.md)\n", encoding="utf-8"
        )

        errors = validate_project_docs(self.config, self.root)
        self.assertTrue(any("只能链接明确的当前已验收基线" in item for item in errors))

    def test_project_size_is_not_a_validation_rule(self) -> None:
        (self.plans / "open-chat.md").write_text(
            self.active_feature("FEATURE-OPENCHAT"), encoding="utf-8"
        )
        body = "# Project\n\n[OpenChat](plans/open-chat.md)\n" + (
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
            "  plans: docs/plans/\n"
        )

    def _invoke(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(PACK / "lib/project/validate_project_config.py"),
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
            f"sys.path.insert(0, {str(PACK)!r}); "
            "from lib.project import validate_project_config as config; "
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
            "features": "docs/features/",
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
            f"sys.path.insert(0, {str(PACK)!r}); "
            "from lib.project import validate_project_config as config; "
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

    def test_wechat_miniprogram_requires_config_manifest_and_entry(self) -> None:
        files = {
            "client/project.config.json": '{"compileType":"miniprogram","miniprogramRoot":"miniprogram/"}',
            "client/miniprogram/app.json": '{}',
            "client/miniprogram/app.ts": 'App({});',
        }
        # 原生模板不依赖 npm；使用 npm 的同一模板仍保留真实包清单作为补充证据。
        package = {"client/package.json": '{"devDependencies":{"typescript":"5"}}'}
        for source in (files, files | package):
            with self.subTest(npm=source is not files):
                profile = self._discover_files(source)
                self.assertEqual((("client", "xy-web"),), self._module_pairs(profile))
                module = profile.modules[0]
                self.assertIn("platform:wechat-miniprogram", module.stack_facts)
                self.assertIn("language:typescript", module.stack_facts)
                self.assertEqual(set(source), set(module.evidence_paths))
                self.assertEqual((), module.verification_commands)

        # 不完整示例、普通 TS 包及越界入口都不能冒充原生小程序。
        for missing in files:
            with self.subTest(missing=missing):
                self.assertEqual((), self._discover_files(
                    {path: body for path, body in files.items() if path != missing} | package
                ).modules)
        for config in (
            '{"miniprogramRoot":"miniprogram/"}',
            '{"compileType":"game","miniprogramRoot":"miniprogram/"}',
            '{"compileType":"plugin","miniprogramRoot":"miniprogram/"}',
            '{"compileType":"gamePlugin","miniprogramRoot":"miniprogram/"}',
            '{"compileType":"miniprogram","miniprogramRoot":"wrong-root/"}',
            '{"compileType":"miniprogram","miniprogramRoot":"../outside"}',
            '{"compileType":"miniprogram","miniprogramRoot":"/outside"}',
            '{"compileType":"miniprogram","miniprogramRoot":null}',
            '{"compileType":"miniprogram","miniprogramRoot":["miniprogram"]}',
        ):
            with self.subTest(config=config):
                self.assertEqual((), self._discover_files(
                    files | {"client/project.config.json": config}
                    | {"outside/app.json": '{}', "outside/app.js": 'App({});'}
                ).modules)
        root_app = {
            "project.config.json": '{"compileType":"miniprogram"}',
            "app.json": '{"pages":["pages/index/index"]}',
            "app.js": 'App({});',
        }
        js_profile = self._discover_files(root_app)
        self.assertEqual(((".", "xy-web"),), self._module_pairs(js_profile))
        self.assertIn("language:javascript", js_profile.modules[0].stack_facts)
        self.assertEqual(set(root_app), set(js_profile.evidence_paths))
        self.assertEqual((), js_profile.verification_commands)
        # 生成的 JS 与 TS 源码并存时，应保留两个入口证据并识别源语言。
        both = self._discover_files(dict(root_app, **{"app.ts": "App({});"})).modules[0]
        self.assertIn("language:typescript", both.stack_facts)
        self.assertNotIn("language:javascript", both.stack_facts)
        self.assertIn("app.js", both.evidence_paths)
        self.assertIn("app.ts", both.evidence_paths)

    def test_wechat_miniprogram_does_not_follow_linked_entry_or_source_root(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-wechat-linked-entry-")
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)
        root = parent / "project"
        outside = parent / "outside"
        self._write_tree(outside, {"app.json": '{}', "app.js": 'App({});'})
        self._write_tree(root, {
            "project.config.json": '{"compileType":"miniprogram","miniprogramRoot":"app/"}',
        })
        app = root / "app"
        # 配置文本即使看似在模块内，也不能通过链接借用外部源码目录或入口。
        app.symlink_to(outside, target_is_directory=True)
        self.assertEqual((), discover_project(root).modules)
        app.unlink()
        self._write_tree(app, {"app.json": '{}'})
        (app / "app.js").symlink_to(outside / "app.js")
        self.assertEqual((), discover_project(root).modules)
        (app / "app.js").unlink()
        (app / "app.js").mkdir()
        self.assertEqual((), discover_project(root).modules)
        (app / "app.js").rmdir()
        (app / "app.js").write_text("App({});", encoding="utf-8")
        (app / "app.json").unlink()
        (app / "app.json").symlink_to(outside / "app.json")
        self.assertEqual((), discover_project(root).modules)

    def test_optional_same_name_config_does_not_break_other_projects(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="project-optional-config-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        root.mkdir()
        (root / "package.json").write_text(
            '{"dependencies":{"react":"19"}}', encoding="utf-8"
        )
        (root / "app.json").write_text('{}', encoding="utf-8")
        (root / "app.js").write_text('App({});', encoding="utf-8")
        config = root / "project.config.json"
        # 同名文件即使存在原生入口，也不能让损坏或超限配置中断普通画像。
        cases = {
            "other-tool": '{"tool":"web"}',
            "malformed": "{invalid",
            "oversized": " " * (1024 * 1024 + 1),
        }
        for kind, body in cases.items():
            with self.subTest(kind=kind):
                config.write_text(body, encoding="utf-8")
                module = discover_project(root).modules[0]
                self.assertEqual((".", "xy-web"), (module.root, module.primary_role))
                self.assertNotIn("platform:wechat-miniprogram", module.stack_facts)
        config.unlink()
        outside = Path(temporary.name) / "outside.json"
        outside.write_text('{"compileType":"miniprogram"}', encoding="utf-8")
        config.symlink_to(outside)
        # 即使链接目标恰为有效小程序配置，也不得跟随它或据此分类。
        module = discover_project(root).modules[0]
        self.assertNotIn("platform:wechat-miniprogram", module.stack_facts)

        # 普通桌面的脚本和 app.json 文件与微信入口同名，也不能改变已观察到的桌面角色。
        desktop = self._discover_files({
            "package.json": '{"main":"app.js","dependencies":{"electron":"40"}}',
            "app.js": "export {};",
            "app.json": '{}',
            "project.config.json": '{"tool":"desktop"}',
        })
        self.assertEqual(((".", "xy-desktop"),), self._module_pairs(desktop))
        self.assertNotIn("platform:wechat-miniprogram", desktop.detected_stack_facts)

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

    def test_miniprogram_commands_use_real_scripts_at_module_root(self) -> None:
        files = {
            "client/package.json": '{"scripts":{"typecheck":"tsc --noEmit","build":"tsc","test":"node --test"}}',
            "client/pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
            "client/project.config.json": '{"compileType":"miniprogram","miniprogramRoot":"miniprogram/"}',
            "client/miniprogram/app.json": '{}',
            "client/miniprogram/app.ts": 'App({});',
        }
        profile = self._discover_files(files)
        self.assertEqual("client", profile.modules[0].root)
        self.assertEqual(
            {("pnpm", "run", "typecheck"), ("pnpm", "run", "build"), ("pnpm", "run", "test")},
            {argv for _, argv, _ in self._commands(profile, "client")},
        )
        # 缺少脚本时仍可识别应用，但不得凭常见约定编造验证命令。
        files["client/package.json"] = '{"scripts":{"test":"node --test","build":""}}'
        self.assertEqual(
            {("pnpm", "run", "test")},
            {argv for _, argv, _ in self._commands(self._discover_files(files), "client")},
        )

    def test_kotlin_jvm_and_maven_same_module_with_inactive_negatives(self):
        # 同一物理模块的两个构建系统各自保留工作目录和真实证据。
        files = {"service/pom.xml": "<project><modelVersion>4.0.0</modelVersion></project>",
                 "service/build.gradle.kts": 'plugins { kotlin("jvm") version "2.2.0" }\n',
                 "service/gradlew": "#!/bin/sh\n", "service/mvnw": "#!/bin/sh\n"}
        profile = self._discover_files(files)
        module = next(item for item in profile.modules if item.root == "service")
        commands = module.verification_commands
        self.assertEqual({("./gradlew", "build"), ("./gradlew", "test"),
                          ("./mvnw", "package"), ("./mvnw", "test")},
                         {command.argv for command in commands})
        # 画像合同以模块根作为所有候选命令的工作目录。
        self.assertEqual("service", module.root)
        self.assertTrue(all("service/build.gradle.kts" in command.evidence_paths
                            for command in commands if command.argv[0] == "./gradlew"))
        for body in ('plugins { // kotlin("jvm")\n id("other") }',
                     'plugins { val sample = "kotlin(\\"jvm\\")"; id("other") }',
                     'plugins { nested { kotlin("jvm") }; id("other") }',
                     'plugins { kotlin("jvm") version "2.2.0" apply false }',
                     'plugins { kotlin("jvm").version("2.2.0").apply(false) }'):
            with self.subTest(body=body):
                negative = dict(files, **{"service/build.gradle.kts": body})
                commands = self._commands(self._discover_files(negative), "service")
                self.assertFalse(any(argv[0] == "./gradlew" for _, argv, _ in commands))

    def test_android_aggregate_deferred_plugins_do_not_create_backend(self):
        # settings 只作为聚合线索，不假称已解析 include；子模块继续使用根 wrapper。
        files = {
            "client/settings.gradle.kts": 'include(":app")\n',
            "client/build.gradle.kts": (
                '// alias(libs.plugins.java)\nplugins {\n'
                ' alias(libs.plugins.android.application) apply false\n'
                ' alias(libs.plugins.kotlin.jvm).apply(false)\n'
                ' id("java") apply false\n}\n'
            ),
            "client/gradle/libs.versions.toml": (
                '[plugins]\nandroid-application = { id = "com.android.application", version = "9" }\n'
                'kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version = "2" }\n'
            ),
            "client/gradlew": "#!/bin/sh\n",
            "client/app/build.gradle.kts": 'plugins { alias(libs.plugins.android.application) }\n',
            "client/app/src/main/AndroidManifest.xml": '<manifest package="example.fixture"/>',
            "server/build.gradle.kts": 'plugins { kotlin("jvm") version "2" }\n',
            "java/build.gradle": "plugins { id 'java' }\n",
        }
        profile = self._discover_files(files)
        modules = {module.root: module for module in profile.modules}
        self.assertNotIn("client", modules)
        self.assertEqual("xy-android", modules["client/app"].primary_role)
        self.assertEqual("xy-backend", modules["server"].primary_role)
        self.assertEqual("xy-backend", modules["java"].primary_role)
        self.assertEqual({("../gradlew", "assembleDebug"), ("../gradlew", "testDebugUnitTest")},
                         {command.argv for command in modules["client/app"].verification_commands})
        for body in (
            'plugins { alias(libs.plugins.android.application) apply false; id("java") }',
            'plugins { alias(libs.plugins.kotlin.jvm); id("com.android.application") apply false }',
            'plugins { id("java") apply false }\nval text = "ordinary build logic"',
        ):
            with self.subTest(body=body):
                changed = dict(files, **{"client/build.gradle.kts": body})
                roots = {module.root: module for module in self._discover_files(changed).modules}
                self.assertEqual("xy-backend", roots["client"].primary_role)
                self.assertFalse(any("assembleDebug" in command.argv
                                     for command in roots["client"].verification_commands))
        # 伪造的注释、字符串和嵌套声明不能让带 manifest 的 JVM 模块变成 Android。
        for body in (
            '// alias(libs.plugins.android.application)\nplugins { id("java") }',
            'plugins { val fake = "alias(libs.plugins.android.application)"; id("java") }',
            'plugins { nested { alias(libs.plugins.android.application) }; id("java") }',
            'plugins { alias(libs.plugins.android.application) apply false; id("java") }',
        ):
            with self.subTest(fake_android=body):
                changed = dict(files, **{"client/app/build.gradle.kts": body})
                app = next(module for module in self._discover_files(changed).modules
                           if module.root == "client/app")
                self.assertEqual("xy-backend", app.primary_role)
                self.assertEqual({("../gradlew", "build"), ("../gradlew", "test")},
                                 {command.argv for command in app.verification_commands})
        # 即使插件都是延迟声明，只要根含自身主源码便不能判成纯聚合根。
        with_source = dict(files, **{"client/src/main/kotlin/Server.kt": "class Server\n"})
        self.assertIn("client", {module.root for module in self._discover_files(with_source).modules})

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

    def test_xcode_candidates_use_owned_workspace_and_shared_schemes(self) -> None:
        project = """// !$*UTF8*$!
{
 objects = {
  A1 = {
   isa = PBXNativeTarget;
   productType = "com.apple.product-type.application";
  };
  A2 = {
   isa = XCBuildConfiguration;
   buildSettings = {
    SDKROOT = iphoneos;
   };
  };
 };
}
"""
        workspace = "ios/New O2O.xcworkspace"
        pods = "ios/Pods/Pods.xcodeproj/project.pbxproj"
        ignored_project = "ios/vendor/Toolkit.xcodeproj/project.pbxproj"
        def workspace_file(*secondary):
            references = ("App.xcodeproj", *secondary)
            return "<Workspace>" + "".join(f'<FileRef location="group:{ref}"/>' for ref in references) + "</Workspace>"

        with tempfile.TemporaryDirectory(prefix="xcode-workspaces-") as temporary:
            root = Path(temporary)
            self._write_tree(root, {
                "ios/App.xcodeproj/project.pbxproj": project,
                "ios/App.xcodeproj/xcshareddata/xcschemes/App.xcscheme": "<Scheme/>",
                "ios/App.xcodeproj/xcuserdata/user/xcschemes/Private.xcscheme": "<Scheme/>",
                pods: project.replace(".application", ".library.static"),
                ignored_project: project,
                f"{workspace}/contents.xcworkspacedata": workspace_file("Pods/Pods.xcodeproj", "vendor/Toolkit.xcodeproj"),
                f"{workspace}/xcshareddata/xcschemes/Workspace.xcscheme": "<Scheme/>",
                "ios/Stale.xcworkspace/contents.xcworkspacedata": "<Workspace><Broken",
                "ios/Outside.xcworkspace/contents.xcworkspacedata": workspace_file("../outside/Other.xcodeproj"),
                "ios/Dangling.xcworkspace/contents.xcworkspacedata": workspace_file("Missing.xcodeproj"),
                "ios/Alias.xcworkspace/contents.xcworkspacedata": workspace_file("Alias.xcodeproj"),
                "ios/AliasManifest.xcworkspace/contents.xcworkspacedata": workspace_file("vendor/Alias.xcodeproj"),
                "ios/CrossModule.xcworkspace/contents.xcworkspacedata": workspace_file("nested/Other.xcodeproj"),
                "ios/nested/Other.xcodeproj/project.pbxproj": project,
            })
            (root / "ios/Alias.xcodeproj").symlink_to(root / "ios/App.xcodeproj")
            alias_manifest = root / "ios/vendor/Alias.xcodeproj/project.pbxproj"
            alias_manifest.parent.mkdir()
            alias_manifest.symlink_to(root / pods)
            profile = discover_project(root)
        commands = {argv: paths for _, argv, paths in self._commands(profile, "ios")}
        for selector, bundle, schemes in (
            ("-project", "App.xcodeproj", ("App",)),
            ("-workspace", "New O2O.xcworkspace", ("App", "Workspace")),
        ):
            for scheme in schemes:
                prefix = ("xcodebuild", selector, bundle, "-scheme", scheme)
                self.assertIn((*prefix, "build"), commands)
                for destination in ("generic/platform=iOS", "generic/platform=iOS Simulator"):
                    evidence = commands[(*prefix, "-destination", destination, "CODE_SIGNING_ALLOWED=NO", "build")]
                    self.assertIn("ios/App.xcodeproj/project.pbxproj", evidence)
                    if selector == "-workspace":
                        self.assertIn(f"{workspace}/contents.xcworkspacedata", evidence)
                        self.assertIn(pods, evidence)
                        self.assertIn(ignored_project, evidence)
                self.assertIn((*prefix, "-destination", "generic/platform=iOS Simulator", "build"), commands)
        self.assertEqual(13, len(commands))

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
