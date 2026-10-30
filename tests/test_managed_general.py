"""默认通用规范的受管更新回归；全部使用临时项目，不触碰实际项目或全局设置。"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib import install_workflow
from lib.standards_baseline import COMMON_BEGIN, COMMON_END, common_block, merge_general, ensure_general_link
from lib.validate_project_docs import validate as validate_documents
from tests import test_unified_host_workflow as host_cases

PACK = host_cases.PACK


class GeneralOwnershipTest(unittest.TestCase):
    def test_update_preserves_exact_outside_bytes_and_is_idempotent(self):
        prefix = "# 项目专项\r\n\r\n".encode()
        suffix = "\r\n\r\n## Project-specific rules\r\n- 保留尾部 空格  ".encode()
        old = prefix + COMMON_BEGIN + b"\nold\n" + COMMON_END + suffix
        source = b"source header\n" + COMMON_BEGIN + b"\nnew\n" + COMMON_END + b"\nsource footer"
        merged = merge_general(old, source)
        self.assertEqual(prefix + common_block(source) + suffix, merged)
        self.assertEqual(merged, merge_general(merged, source))

    def test_unmarked_document_is_preserved_and_ambiguous_markers_are_rejected(self):
        source = COMMON_BEGIN + b"\nnew\n" + COMMON_END
        original = "# 自定义规范\n## 共通开发规范\n项目自己的条款\n".encode()
        self.assertEqual(original, merge_general(original, source))
        for damaged in (COMMON_BEGIN, COMMON_END, source + COMMON_BEGIN,
                        COMMON_END + b"\n" + COMMON_BEGIN, b"inline " + source):
            with self.subTest(damaged=damaged), self.assertRaisesRegex(ValueError, "markers"):
                merge_general(damaged, source)

    def test_project_rule_id_collision_fails_before_merging(self):
        rule = b"- `[eng-common-001] [hard]` rule\n"
        source = COMMON_BEGIN + b"\n" + rule + COMMON_END
        with self.assertRaisesRegex(ValueError, "duplicate rule IDs"):
            merge_general(source + b"\n## Project-specific rules\n" + rule, source)

    def test_index_link_resolves_custom_paths_and_preserves_existing_text(self):
        with tempfile.TemporaryDirectory() as raw:
            index = Path(raw) / "docs/规范索引.md"
            general = Path(raw) / "project rules/GENERAL.md"
            original = "# 自定义目录\r\n\r\n保留项目说明。\r\n".encode()
            result = ensure_general_link(original, index, general)
            self.assertTrue(result.startswith(original))
            self.assertIn(b"../project%20rules/GENERAL.md", result)
            self.assertEqual(result, ensure_general_link(result, index, general))


class GeneralPublisherTest(host_cases.UnifiedHostFixture, unittest.TestCase):
    def fixture(self):
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        (project / "go.mod").write_text("module example.test/general\n", encoding="utf-8")
        return project, pack

    def scaffold(self, project):
        result = self.run_script(project, "scripts/scaffold_project_docs.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_shared_update_preserves_project_sections_modes_and_unchanged_inodes(self):
        project, pack = self.fixture()
        self.scaffold(project)
        general = project / "docs/standards/GENERAL.md"
        original = general.read_bytes() + "\n- `[eng-project-local] [hard]` 项目约束。\n".encode()
        general.write_bytes(original)
        general.chmod(0o600)
        template = pack / "templates/docs/standards/GENERAL.md"
        template.write_bytes(template.read_bytes().replace(COMMON_END, b"<!-- revision 2 -->\n" + COMMON_END))
        others = {p.relative_to(project): p.read_bytes() for p in (project / "docs").rglob("*")
                  if p.is_file() and p != general}
        self.assertTrue(any("managed common region differs" in e
                            for e in validate_documents(pack / "project.yaml", project)))
        self.scaffold(project)
        expected = merge_general(original, template.read_bytes())
        self.assertEqual(expected, general.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(general.stat().st_mode))
        self.assertEqual(others, {p.relative_to(project): p.read_bytes()
                                 for p in (project / "docs").rglob("*") if p.is_file() and p != general})
        before = {p: (p.stat().st_ino, p.stat().st_mtime_ns) for p in (general, project / "docs/STANDARDS.md")}
        self.scaffold(project)
        self.assertEqual(before, {p: (p.stat().st_ino, p.stat().st_mtime_ns) for p in before})
        self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_custom_index_gets_only_missing_general_link_and_unmarked_general_is_preserved(self):
        project, pack = self.fixture()
        root = project / "docs/standards"
        root.mkdir(parents=True)
        general = root / "GENERAL.md"
        original = b"# Project General\n- Domain: engineering\n- `[eng-project-only] [hard]` Keep project rules.\n"
        general.write_bytes(original)
        index = project / "docs/STANDARDS.md"
        index.write_bytes(b"# Custom standards\n\nProject index text.\n")
        result = self.run_script(project, "scripts/scaffold_project_docs.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("unmarked", result.stdout)
        self.assertEqual(original, general.read_bytes())
        self.assertTrue(index.read_bytes().startswith(b"# Custom standards\n\nProject index text.\n"))
        self.assertIn(b"standards/GENERAL.md", index.read_bytes())
        self.assertFalse((root / "UPSTREAM.md").exists())
        self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_antigravity_preserves_unmarked_general_and_only_completes_its_index(self):
        project, pack = self.fixture()
        general = project / "docs/standards/GENERAL.md"
        general.parent.mkdir(parents=True)
        original = b"# Project General\n- Domain: engineering\n- `[eng-local-only] [hard]` Project rule.\n"
        general.write_bytes(original)
        index = project / "docs/STANDARDS.md"
        index_before = b"# Custom standards\n\nProject index text.\n"
        index.write_bytes(index_before)
        result = host_cases.UnifiedSetupContractTest.run_antigravity_applier(self, project, pack)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("unmarked", result.stdout)
        self.assertEqual(original, general.read_bytes())
        self.assertEqual(ensure_general_link(index_before, index, general), index.read_bytes())
        self.assertFalse((general.parent / "UPSTREAM.md").exists())
        self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_bad_markers_stop_before_any_project_document_write(self):
        project, _ = self.fixture()
        general = project / "docs/standards/GENERAL.md"
        general.parent.mkdir(parents=True)
        general.write_bytes(COMMON_BEGIN)
        result = self.run_script(project, "scripts/scaffold_project_docs.sh")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("markers", result.stdout + result.stderr)
        self.assertEqual(COMMON_BEGIN, general.read_bytes())
        self.assertFalse((project / "docs/STANDARDS.md").exists())
        self.assertFalse((project / "docs/PROJECT.md").exists())

    def test_cross_leaf_rule_collision_stops_both_publishers_before_document_writes(self):
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                self.scaffold(project)
                extra = project / "docs/standards/EXTRA.md"
                rule = b"- `[eng-next-rule] [hard]` Existing project rule.\n"
                extra.write_bytes(b"# Project engineering\n- Domain: engineering\n" + rule)
                index = project / "docs/STANDARDS.md"
                index.write_bytes(index.read_bytes() + b"\n- [Extra rules](standards/EXTRA.md)\n")
                before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (project / "docs").rglob("*.md")}
                template = pack / "templates/docs/standards/GENERAL.md"
                template.write_bytes(template.read_bytes().replace(COMMON_END, rule + COMMON_END))
                result = (self.run_script(project, "scripts/scaffold_project_docs.sh") if host == "shared"
                          else host_cases.UnifiedSetupContractTest.run_antigravity_applier(self, project, pack))
                self.assertNotEqual(0, result.returncode)
                self.assertIn("duplicate standards rule ID", result.stdout + result.stderr)
                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_same_size_concurrent_edit_is_restored_instead_of_overwritten(self):
        project, pack = self.fixture()
        self.scaffold(project)
        general = project / "docs/standards/GENERAL.md"
        original_size = general.stat().st_size
        template = pack / "templates/docs/standards/GENERAL.md"
        template.write_bytes(template.read_bytes().replace(COMMON_END, b"<!-- new -->\n" + COMMON_END))
        result = subprocess.run(
            ["bash", "agent_workflow/scripts/scaffold_project_docs.sh"], cwd=project,
            env={**os.environ, "AGENT_WORKFLOW_PACK_TEST_SCAFFOLD_RACE": "managed:docs/standards/GENERAL.md"},
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("changed during publish", result.stdout + result.stderr)
        self.assertEqual(b"X" * original_size, general.read_bytes())

    def test_antigravity_uses_same_update_and_rolls_it_back_on_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                project, pack = self.fixture()
                self.scaffold(project)
                general = project / "docs/standards/GENERAL.md"
                original = general.read_bytes() + "\n项目专项尾注。\n".encode()
                general.write_bytes(original)
                general.chmod(0o640)
                template = pack / "templates/docs/standards/GENERAL.md"
                template.write_bytes(template.read_bytes().replace(COMMON_END, b"<!-- new -->\n" + COMMON_END))
                environment = {"AGENT_WORKFLOW_PACK_TEST_FAILPOINT": "antigravity-after-agents-publish"} if fail else {}
                with patch.dict(os.environ, environment):
                    result = host_cases.UnifiedSetupContractTest.run_antigravity_applier(self, project, pack)
                self.assertEqual(1 if fail else 0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(original if fail else merge_general(original, template.read_bytes()), general.read_bytes(),
                                 result.stdout + result.stderr)
                self.assertEqual(0o640, stat.S_IMODE(general.stat().st_mode))


class GeneralAtomicPublicationTest(unittest.TestCase):
    @staticmethod
    def applier():
        # 发布器也是直接脚本入口，按它实际使用的 lib 搜索路径加载，不修改全局环境。
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            return importlib.import_module("apply_antigravity_setup")

    def test_antigravity_document_publication_and_rollback_preserve_concurrent_content(self):
        applier = self.applier()
        for moment in ("gap", "after"):
            with self.subTest(moment=moment), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "GENERAL.md"
                target.write_bytes(b"original project rules\n")
                change = applier.FileChange(target, b"new common rules\n", 0o600, applier._fingerprint(target))
                plan = applier.Plan(PACK, project, project, "general-publication-test")
                plan.doc_changes.append(change)
                concurrent = b"concurrent project-specific note\n"
                replace = os.replace

                def publish_gap(source, destination):
                    replace(source, destination)
                    if Path(source) == target:
                        target.write_bytes(concurrent)

                if moment == "gap":
                    with patch.object(applier.os, "replace", side_effect=publish_gap):
                        with self.assertRaisesRegex(applier.ApplyError, "cannot atomically replace"):
                            applier._publish_file(change, plan)
                else:
                    applier._publish_file(change, plan)
                    target.write_bytes(concurrent)
                with self.assertRaisesRegex(applier.ApplyError, "Document.*preserved current file and backup"):
                    applier._rollback(plan)
                self.assertEqual(concurrent, target.read_bytes())
                self.assertEqual(b"original project rules\n", change.backup.read_bytes())

    def test_antigravity_keeps_late_modified_document_backup(self):
        applier = self.applier()
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            target = project / "GENERAL.md"
            target.write_bytes(b"original project rules\n")
            change = applier.FileChange(target, b"new common rules\n", 0o600, applier._fingerprint(target))
            plan = applier.Plan(PACK, project, project, "general-backup-test")
            plan.doc_changes.append(change)
            applier._publish_file(change, plan)
            # 模拟编辑器仍持有原 inode，在文件已移入事务备份后继续保存专项。
            change.backup.write_bytes(b"late project-specific change\n")
            with self.assertRaisesRegex(applier.ApplyError, "preserve changed document backup"):
                applier._cleanup_committed(plan)
            self.assertEqual(b"late project-specific change\n", change.backup.read_bytes())
            self.assertEqual(change.body, target.read_bytes())


class GeneralInstallerRecoveryTest(unittest.TestCase):
    def test_real_three_host_install_and_upgrade_preserve_project_content(self):
        """真实调用两次安装器；只验证安装生成物，不运行模拟项目的业务构建。"""

        with tempfile.TemporaryDirectory(prefix="workflow-general-install-") as raw:
            root = Path(raw).resolve()
            source = root / "source"
            project = root / "中文 Project"
            project.mkdir()
            shutil.copytree(PACK, source, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
            business = project / "go.mod"
            business.write_bytes(b"module example.test/general\n")

            def install():
                result = subprocess.run(
                    ["bash", str(source / "install.sh"), str(project)], cwd=root,
                    text=True, capture_output=True, check=False, timeout=120,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                # 安装器自身会执行三宿主 --check，不在这里重复验证同一批生成物。
                for host in ("Claude", "Codex", "Antigravity"):
                    self.assertIn(f"{host} --check", result.stdout)

            install()
            general = project / "docs/standards/GENERAL.md"
            index = project / "docs/STANDARDS.md"
            general_before = general.read_bytes() + "\n- `[eng-project-only] [hard]` 项目专项不得被更新。\n".encode()
            general.write_bytes(general_before)
            general.chmod(0o600)
            # 模拟项目已有自定义目录，但尚未将通用规范挂载进去；不得重排现有条目。
            index_before = b"\n".join(line for line in index.read_bytes().split(b"\n") if b"standards/GENERAL.md" not in line)
            index.write_bytes(index_before)
            protected = (business, project / "docs/PROJECT.md", project / "docs/standards/UPSTREAM.md")
            protected_before = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in protected}
            config_before = (project / ".agent-workflow/project.yaml").read_bytes()
            template = source / "templates/docs/standards/GENERAL.md"
            template.write_bytes(template.read_bytes().replace(COMMON_END, b"<!-- next common revision -->\n" + COMMON_END))
            install()
            self.assertEqual(merge_general(general_before, template.read_bytes()), general.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(general.stat().st_mode))
            self.assertEqual(ensure_general_link(index_before, index, general), index.read_bytes())
            self.assertEqual(config_before, (project / ".agent-workflow/project.yaml").read_bytes())
            self.assertEqual(protected_before, {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in protected})

    def test_recovery_preserves_a_concurrent_permission_change(self):
        """只有内容和权限都仍为本轮产物，恢复器才有权撤回整个文档。"""

        with tempfile.TemporaryDirectory() as raw:
            general = Path(raw).resolve() / "GENERAL.md"
            general.write_bytes(b"published common rules\n")
            general.chmod(0o640)
            with self.assertRaisesRegex(install_workflow.InstallError, "发生其他变更"):
                install_workflow._restore_standard_updates([
                    (general, b"previous rules\n", general.read_bytes(), 0o600),
                ])
            self.assertEqual(b"published common rules\n", general.read_bytes())
            self.assertEqual(0o640, stat.S_IMODE(general.stat().st_mode))

    def test_recovery_continues_other_safe_documents_after_a_conflict(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            general = root / "GENERAL.md"
            index = root / "STANDARDS.md"
            general.write_bytes(b"new common rules\n")
            index.write_bytes(b"concurrent project index\n")
            general.chmod(0o600)
            index.chmod(0o600)
            with self.assertRaisesRegex(install_workflow.InstallError, "发生其他变更"):
                install_workflow._restore_standard_updates([
                    (general, b"old common rules\n", general.read_bytes(), 0o600),
                    (index, b"old index\n", b"new index\n", 0o600),
                ])
            self.assertEqual(b"old common rules\n", general.read_bytes())
            self.assertEqual(b"concurrent project index\n", index.read_bytes())

    def test_failed_upgrade_restores_general_and_missing_index_link_before_old_setup(self):
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                source = root / "source"
                project = root / "project"
                project.mkdir()
                shutil.copytree(PACK, source, ignore=shutil.ignore_patterns("__pycache__"))
                old_template = source / "templates/docs/standards/GENERAL.md"
                old_template.write_bytes(old_template.read_bytes().replace(COMMON_END, b"<!-- old -->\n" + COMMON_END))
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, source)
                general = project / "docs/standards/GENERAL.md"
                general.parent.mkdir(parents=True)
                original = b"# Custom General\n- Domain: engineering\n" + common_block(old_template.read_bytes()) + b"\n## Project-specific rules\nProject note.\n"
                general.write_bytes(original)
                general.chmod(0o600)
                index = project / "docs/STANDARDS.md"
                index_before = b"# Custom index\n\nProject links.\n"
                index.write_bytes(index_before)
                calls = []
                published = None

                def setup(runtime, target, *options):
                    nonlocal published
                    calls.append(options)
                    if len(calls) == 2:
                        for path, _before, after, _mode in install_workflow._standard_update_snapshots(runtime, target):
                            path.write_bytes(after)
                        published = general.read_bytes()
                        if concurrent:
                            general.write_bytes(published + b"concurrent project note\n")
                        raise subprocess.CalledProcessError(7, "setup_all.sh")
                    if len(calls) >= 3:
                        self.assertEqual(original, general.read_bytes())
                        self.assertEqual(index_before, index.read_bytes())

                with patch.object(install_workflow, "_run_setup", side_effect=setup):
                    with self.assertRaises(install_workflow.InstallError):
                        install_workflow._install(project, PACK)
                self.assertEqual(0o600, stat.S_IMODE(general.stat().st_mode))
                self.assertEqual(published + b"concurrent project note\n" if concurrent else original, general.read_bytes())
                self.assertEqual(2 if concurrent else 4, len(calls))


if __name__ == "__main__":
    unittest.main()
