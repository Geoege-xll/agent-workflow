"""通用规范单一来源迁移：只操作临时项目，保留项目字节与原事务安全边界。"""
from __future__ import annotations

from functools import lru_cache
import importlib
import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch

from lib import install_workflow
from lib.validate_project_config import validate_with_profile
from lib.validate_project_docs import validate as validate_documents
from tests import test_unified_host_workflow as host_cases

PACK = host_cases.PACK


class GeneralPublisherTest(host_cases.UnifiedHostFixture, unittest.TestCase):
    def fixture(self):
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        (project / "go.mod").write_text("module example.test/general\n", encoding="utf-8")
        return project, pack

    def publish(self, project, pack, host="shared", *, success=True):
        result = (self.run_script(project, "scripts/scaffold_project_docs.sh") if host == "shared"
                  else host_cases.UnifiedSetupContractTest.run_antigravity_applier(self, project, pack))
        self.assertEqual(0 if success else 1, 0 if result.returncode == 0 else 1,
                         result.stdout + result.stderr)
        return result


    def test_new_install_creates_no_generic_leaves_or_empty_index(self):
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                self.publish(project, pack, host)
                self.assertFalse((project / "docs/STANDARDS.md").exists())
                self.assertFalse((project / "docs/standards").exists())
                self.assertTrue((project / "docs/PROJECT.md").is_file())
                self.assertEqual([], validate_documents(pack / "project.yaml", project))


    def test_unmarked_project_file_is_preserved_and_index_only_gains_missing_link(self):
        project, pack = self.fixture()
        general = project / "docs/standards/GENERAL.md"
        general.parent.mkdir(parents=True)
        original = b"# Project General\n- Domain: engineering\n- `[eng-local-only] [hard]` Project rule.\n"
        general.write_bytes(original)
        index = project / "docs/STANDARDS.md"
        before = b"# Custom index\r\n\r\nProject index text.\r\n"
        index.write_bytes(before)
        self.publish(project, pack)
        self.assertEqual(original, general.read_bytes())
        self.assertTrue(index.read_bytes().startswith(before))
        self.assertEqual(1, index.read_bytes().count(b"standards/GENERAL.md"))


    def test_antigravity_failure_removes_only_the_created_project_index(self):
        """由真实规划器标记新建薄索引，并在宿主失败后安全撤回，避免只测手工标记。"""
        project, pack = self.fixture()
        leaf = project / "docs/standards/LOCAL.md"
        leaf.parent.mkdir(parents=True)
        original = b"# Local project rules\n- Domain: engineering\n- `[eng-project-local] [hard]` Keep project constraint.\n"
        leaf.write_bytes(original)
        with patch.dict(os.environ, {"AGENT_WORKFLOW_PACK_TEST_FAILPOINT": "antigravity-after-agents-publish"}):
            self.publish(project, pack, "antigravity", success=False)
        self.assertEqual(original, leaf.read_bytes())
        self.assertFalse((project / "docs/STANDARDS.md").exists())


class GeneralAtomicPublicationTest(unittest.TestCase):
    def test_current_index_plan_keeps_rule_bytes_and_publishes_missing_links(self):
        """当前 source setup 仍消费规范规划器；只补索引，规则正文没有自动剥离权限。"""
        from lib.project_discovery import discover_project
        from lib.standards_baseline import plan_standard_updates
        with tempfile.TemporaryDirectory(prefix="current-standard-index-") as raw:
            project = Path(raw).resolve()
            leaf = project / "docs/standards/LOCAL.md"
            leaf.parent.mkdir(parents=True)
            body = b"# Local rules\n- Domain: engineering\n- `[eng-local-current] [hard]` Preserve local behavior.\n"
            leaf.write_bytes(body); leaf.chmod(0o640)
            docs = {"standards": "docs/STANDARDS.md", "standards_root": "docs/standards/",
                    "project": "docs/PROJECT.md", "plans": "docs/plans/"}
            inputs = {}
            updates = plan_standard_updates(PACK, project, docs=docs, profile=discover_project(project), expected_inputs=inputs)
            index = project / docs["standards"]
            self.assertEqual({index}, set(updates)); self.assertEqual({index: None}, inputs)
            def verify():
                self.assertEqual(body, leaf.read_bytes())
                self.assertIn(b"standards/LOCAL.md", index.read_bytes())
            self.applier().publish_document_changes(project, updates, inputs, verify)
            self.assertIn(b"standards/LOCAL.md", index.read_bytes())
            self.assertEqual(body, leaf.read_bytes()); self.assertEqual(0o640, stat.S_IMODE(leaf.stat().st_mode))
            self.assertEqual({}, plan_standard_updates(PACK, project, docs=docs, profile=discover_project(project)))
            leaf.write_bytes(body.replace(b"eng-local-current", b"eng-common-005"))
            with self.assertRaisesRegex(ValueError, "duplicate standards rule ID"):
                plan_standard_updates(PACK, project, docs=docs, profile=discover_project(project))

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

    def test_deleted_document_restore_preserves_recreation_after_missing_sample(self):
        applier = self.applier()
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            target = project / "GENERAL.md"
            target.write_bytes(b"original default\n")
            change = applier.FileChange(target, None, 0o600, applier._fingerprint(target))
            plan = applier.Plan(PACK, project, project, "restore-missing-race")
            plan.doc_changes.append(change)
            applier._publish_file(change, plan)
            check = applier._assert_unchanged
            concurrent = b"USER-RECREATED-AFTER-SAMPLE\n"
            injected = False

            def inject_after_missing_sample(path, expected):
                nonlocal injected
                check(path, expected)
                if Path(path) == change.backup and not injected:
                    injected = True
                    target.write_bytes(concurrent)

            with patch.object(applier, "_assert_unchanged", side_effect=inject_after_missing_sample):
                with self.assertRaises(applier.ApplyError):
                    applier._rollback(plan)
            self.assertTrue(injected)
            self.assertEqual(concurrent, target.read_bytes())
            self.assertEqual(b"original default\n", change.backup.read_bytes())

    def test_created_index_rollback_preserves_replacement_after_sampling(self):
        applier = self.applier()
        published = b"# Published project standards index\n"
        for replacement in (None, b"USER-REPLACED-INDEX\n", published):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "STANDARDS.md"
                change = applier.FileChange(target, published, 0o600, applier._fingerprint(target), created_standard_index=True)
                plan = applier.Plan(PACK, project, project, "remove-created-race")
                plan.doc_changes.append(change)
                applier._publish_file(change, plan)
                if replacement is None:
                    applier._rollback(plan)
                    self.assertFalse(target.exists())
                    continue
                read = applier._read_regular
                injected = False

                def inject_after_sampling(path, label):
                    nonlocal injected
                    body = read(path, label)
                    if Path(path) == target and not injected:
                        injected = True
                        candidate = project / "user-index-replacement"
                        candidate.write_bytes(replacement)
                        candidate.chmod(0o600)
                        os.replace(candidate, target)
                    return body

                with patch.object(applier, "_read_regular", side_effect=inject_after_sampling):
                    with self.assertRaises(applier.ApplyError):
                        applier._rollback(plan)
                self.assertTrue(injected)
                self.assertEqual(replacement, target.read_bytes())


class GeneralDeletionTransactionTest(unittest.TestCase):
    def test_deletion_rollback_restores_original_and_preserves_concurrent_recreation(self):
        applier = GeneralAtomicPublicationTest.applier()
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "GENERAL.md"
                target.write_bytes(b"original managed default\n")
                target.chmod(0o640)
                change = applier.FileChange(target, None, 0o640, applier._fingerprint(target))
                plan = applier.Plan(PACK, project, project, "deletion-test")
                plan.doc_changes.append(change)
                applier._publish_file(change, plan)
                self.assertFalse(target.exists())
                if concurrent:
                    target.write_bytes(b"concurrent project rule\n")
                    with self.assertRaisesRegex(applier.ApplyError, "changed after deletion"):
                        applier._rollback(plan)
                    self.assertEqual(b"concurrent project rule\n", target.read_bytes())
                    self.assertEqual(b"original managed default\n", change.backup.read_bytes())
                else:
                    applier._rollback(plan)
                    self.assertEqual(b"original managed default\n", target.read_bytes())
                    self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))


if __name__ == "__main__":
    unittest.main()
