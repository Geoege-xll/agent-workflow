"""独立原生配置服务闭环：真实文件保存、批量前像保护及宿主能力负控。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from native_config import ModelService, codex_models, storage
from native_config.contracts import ConflictError
from tests.test_native_inventory import claude_plugin, write_agent


class NativeConfigServiceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-config-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.data = self.root / "data"
        self.service = ModelService(self.data, self.home)

    def make(self, name="audit-scout", host="codex", fields=None, *, project=False):
        root = (self.project / {"codex": ".codex/agents", "claude": ".claude/agents", "antigravity": ".agents/agents"}[host]) if project else (
            self.home / {"codex": ".codex/agents", "claude": ".claude/agents", "antigravity": ".gemini/config/agents"}[host])
        return write_agent(root, host, name, fields)

    def context(self, host="codex", *, project=False):
        return self.service.context(host, "project" if project else "global", self.project if project else None)

    def preview(self, edits=None, *, host="codex", project=False, reset=False, context=None, service=None):
        service = service or self.service
        context = context or service.context(host, "project" if project else "global", self.project if project else None)
        return service.preview({"host": host, "scope": context["scope"], "project": context["project"],
                                "revision": context["revision"], "edits": edits or {}, "reset": reset})

    def test_no_workflow_required_real_native_file_save_and_cancel_zero_write(self):
        path = self.make(fields={"model": "unknown-native-model"})
        original = path.read_bytes()
        with patch("native_config.version_probe.subprocess.Popen", side_effect=AssertionError("context must not start host")):
            context = self.context()
            opaque = context["roles"][0]["role"]
            preview = self.preview({opaque: {"effort": "ultra"}}, context=context)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(self.data.exists())
            saved = self.service.apply(preview["preview_id"])
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["results"], [{"role": opaque, "status": "saved"}])
        self.assertTrue(saved["effect"]["pending_reload"])
        self.assertFalse(saved["effect"]["runtime_verified"])
        self.assertFalse(saved["effect"]["cross_filesystem_crash_atomic"])
        self.assertIn(b'model_reasoning_effort = "ultra"', path.read_bytes())
        self.assertIn(b'model = "fake-body"', path.read_bytes())
        self.assertFalse((self.project / ".awf").exists())
        self.assertFalse(self.data.exists())
        self.assertEqual(saved["context"]["roles"][0]["role"], opaque)

    def test_project_is_complete_definition_and_null_does_not_merge_user_fields(self):
        self.make(host="claude", fields={"model": "opus", "effort": "high"})
        path = self.make(host="claude", fields={"model": "haiku"}, project=True)
        context = self.context("claude", project=True)
        project = next(row for row in context["roles"] if row["origin"] == "project")
        preview = self.preview({project["role"]: {"model": None}}, host="claude", project=True, context=context)
        saved = self.service.apply(preview["preview_id"])
        row = next(row for row in saved["context"]["roles"] if row["origin"] == "project")
        self.assertEqual(row["effective"], {"model": "inherit", "effort": "inherit"})
        self.assertEqual(row["sources"], {"model": "host_unresolved", "effort": "host_unresolved"})
        self.assertNotIn(b"model: ", path.read_bytes().split(b"---\n")[1])

    def test_inherit_edit_is_translated_to_official_field_deletion_for_codex(self):
        path = self.make(fields={"model": "custom", "effort": "ultra"})
        opaque = self.context()["roles"][0]["role"]
        saved = self.service.apply(self.preview({opaque: {"model": "inherit", "effort": "inherit"}})["preview_id"])
        self.assertEqual(saved["context"]["roles"][0]["overrides"], {})
        self.assertNotIn(b'"inherit"', path.read_bytes())

    def test_reset_preserves_body_comments_and_only_selected_scope(self):
        user = self.make(host="claude", fields={"model": "sonnet", "effort": "high"})
        project = self.make(host="claude", fields={"model": "opus", "effort": "medium"}, project=True)
        before = user.read_bytes()
        body = project.read_bytes().split(b"---\n", 2)[-1]
        saved = self.service.apply(self.preview(host="claude", project=True, reset=True)["preview_id"])
        self.assertTrue(saved["saved"])
        self.assertEqual(user.read_bytes(), before)
        self.assertEqual(project.read_bytes().split(b"---\n", 2)[-1], body)
        self.assertEqual(next(row for row in saved["context"]["roles"] if row["origin"] == "project")["overrides"], {})

    def test_two_preview_cas_and_inventory_change_reject_whole_batch(self):
        first = self.make("first-native")
        second = self.make("second-native")
        context = self.context()
        edits = {row["role"]: {"model": "future"} for row in context["roles"]}
        one, two = self.preview(edits, context=context), self.preview(edits, context=context)
        self.service.apply(one["preview_id"])
        after = (first.read_bytes(), second.read_bytes())
        with self.assertRaises(ConflictError):
            self.service.apply(two["preview_id"])
        self.assertEqual((first.read_bytes(), second.read_bytes()), after)
        preview = self.preview(edits)
        self.make("added-after-preview")
        with self.assertRaises(ConflictError):
            self.service.apply(preview["preview_id"])
        self.assertEqual((first.read_bytes(), second.read_bytes()), after)

    def test_batch_prevalidation_and_invalid_ids_paths_or_fields_write_nothing(self):
        first = self.make("first-native")
        self.make("second-native")
        context = self.context()
        one, two = [row["role"] for row in context["roles"]]
        requests = [{one: {"model": "future"}, two: {"command": "execute"}},
                    {"../../private": {"model": "future"}},
                    {one: {"model": "x\npermissions: all"}},
                    {one: {"effort": "too long with spaces"}}]
        before = first.read_bytes()
        for edits in requests:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                self.preview(edits, context=context)
            self.assertEqual(first.read_bytes(), before)
        self.assertEqual(list(self.home.rglob(".native-config-*")), [])
        with self.assertRaises(ValueError):
            self.service.resolve_subagent("codex", "first-native")

    def test_plugin_is_read_only_and_no_own_json_can_fake_native_update(self):
        _, path = claude_plugin(self.home)
        context = self.context("claude")
        row = context["roles"][0]
        before = path.read_bytes()
        self.assertFalse(row["writable"])
        with self.assertRaises(ValueError):
            self.preview({row["role"]: {"model": "sonnet"}}, host="claude", context=context)
        saved = self.service.apply(self.preview(host="claude", reset=True)["preview_id"])
        self.assertFalse(saved["saved"])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.data.exists())

    def test_symlink_replacement_after_preview_is_conflict_not_followed(self):
        path = self.make(fields={"model": "original"})
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        outside = self.root / "outside.toml"
        outside.write_bytes(path.read_bytes())
        original = outside.read_bytes()
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(ConflictError):
            self.service.apply(preview["preview_id"])
        self.assertEqual(outside.read_bytes(), original)

    def test_partial_batch_failure_restores_preimages_and_reports_each_target(self):
        paths = [self.make("first-native"), self.make("second-native")]
        originals = {path: path.read_bytes() for path in paths}
        context = self.context()
        preview = self.preview({row["role"]: {"model": "new"} for row in context["roles"]}, context=context)
        real_link = storage.os.link
        count = 0
        def fail_second_publish(source, *args, **kwargs):
            nonlocal count
            if source.endswith(".new"):
                count += 1
                if count == 2:
                    raise OSError("fixture publication failure")
            return real_link(source, *args, **kwargs)
        with patch.object(storage.os, "link", side_effect=fail_second_publish):
            result = self.service.apply(preview["preview_id"])
        self.assertGreaterEqual(count, 2)
        self.assertFalse(result["saved"])
        self.assertTrue(result["partial_failure"])
        self.assertEqual({item["status"] for item in result["results"]}, {"rolled_back"})
        preview_copies = [item for item in result["recovery"] if item["kind"] == "preview_preimage"]
        self.assertEqual(len(preview_copies), 2)
        self.assertTrue(all(Path(item["backup"]).read_bytes() == originals[Path(item["target"])] for item in preview_copies))
        self.assertTrue(result["effect"]["pending_reload"])
        self.assertEqual({path: path.read_bytes() for path in paths}, originals)
        self.assertNotIn("cleanup_pending", result)
        self.assertEqual(list(self.home.rglob("*.new")), [])

    def test_success_keeps_real_original_inode_written_by_old_fd_after_actual_publish(self):
        path = self.make(fields={"model": "before"})
        original = path.read_bytes()
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
        identity = (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        real_link = storage.os.link
        actual_publications = []

        def write_original_fd_after_real_link(source, destination, **kwargs):
            value = real_link(source, destination, **kwargs)
            if source == "candidate.new":
                actual_publications.append(True)
                os.write(descriptor, b"# EXTERNAL OLD FD AFTER PUBLISH\n")
                os.fsync(descriptor)
            return value

        try:
            with patch.object(storage.os, "link", side_effect=write_original_fd_after_real_link):
                result = self.service.apply(preview["preview_id"])
        finally:
            os.close(descriptor)
        self.assertEqual(len(actual_publications), 1, "必须先执行真实发布 syscall 再写旧 fd")
        self.assertTrue(result["saved"])
        self.assertFalse(result["partial_failure"])
        self.assertNotIn("error", result)
        self.assertNotIn("cleanup_pending", result)
        live = next(item for item in result["recovery"] if item["kind"] == "isolated_object"
                    and tuple(item["observed_identity"][:2]) == identity)
        retained = Path(live["backup"])
        self.assertEqual((retained.stat().st_dev, retained.stat().st_ino), identity)
        self.assertIn(b"EXTERNAL OLD FD AFTER PUBLISH", retained.read_bytes())
        self.assertEqual(retained.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(retained.stat().st_mode & 0o777, 0o600)
        self.assertTrue(live["content_may_change"])
        self.assertEqual(live["sha256_semantics"], "observed_at_isolation_not_current")
        self.assertEqual(live["sha256"], hashlib.sha256(original).hexdigest())
        self.assertNotEqual(live["sha256"], hashlib.sha256(retained.read_bytes()).hexdigest())
        fixed = next(item for item in result["recovery"] if item["kind"] == "preview_preimage")
        self.assertEqual(Path(fixed["backup"]).read_bytes(), original)
        self.assertEqual(fixed["sha256"], hashlib.sha256(original).hexdigest())
        self.assertFalse(fixed["content_may_change"])
        self.assertEqual(fixed["sha256_semantics"], "immutable_preview_bytes")
        self.assertNotIn(b"EXTERNAL OLD FD", path.read_bytes())

    def test_success_receipt_keeps_old_fd_writes_that_happen_after_apply_returns(self):
        path = self.make(fields={"model": "before"})
        original = path.read_bytes()
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
        identity = (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        real_link = storage.os.link
        publications = []

        def observe_real_publication(source, destination, **kwargs):
            value = real_link(source, destination, **kwargs)
            if source == "candidate.new":
                publications.append(True)
            return value

        try:
            with patch.object(storage.os, "link", side_effect=observe_real_publication):
                result = self.service.apply(preview["preview_id"])
            self.assertTrue(result["saved"])
            self.assertEqual(len(publications), 1)
            os.write(descriptor, b"# EXTERNAL OLD FD AFTER NORMAL RETURN\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        live = next(item for item in result["recovery"] if item["kind"] == "isolated_object"
                    and tuple(item["observed_identity"][:2]) == identity)
        self.assertIn(b"EXTERNAL OLD FD AFTER NORMAL RETURN", Path(live["backup"]).read_bytes())
        fixed = next(item for item in result["recovery"] if item["kind"] == "preview_preimage")
        self.assertEqual(Path(fixed["backup"]).read_bytes(), original)
        self.assertEqual(fixed["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(result["retention_policy"], "until_explicit_safe_cleanup_contract")
        self.assertFalse(result["partial_failure"])
        self.assertNotIn("cleanup_pending", result)

    def test_rollback_keeps_original_and_published_inodes_for_held_fd_writes(self):
        paths = [self.make("first-native"), self.make("second-native")]
        originals = {path.name: path.read_bytes() for path in paths}
        descriptors = {path.name: os.open(path, os.O_WRONLY | os.O_APPEND) for path in paths}
        original_identities = {name: (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
                               for name, descriptor in descriptors.items()}
        preview = self.preview({row["role"]: {"model": "new"} for row in self.context()["roles"]})
        real_link = storage.os.link
        attempts, published, restores = [], [], []

        def hold_published_fd_and_write_after_real_restore(source, destination, **kwargs):
            if source == "candidate.new":
                attempts.append(destination)
                if len(attempts) == 2:
                    raise OSError("fixture forces rollback")
            value = real_link(source, destination, **kwargs)
            if source == "candidate.new":
                descriptor = os.open(paths[0].parent / destination, os.O_WRONLY | os.O_APPEND)
                published.append((destination, descriptor, (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)))
            if source == "restore.new" and published and destination == published[0][0]:
                restores.append(True)
                os.write(published[0][1], b"# EXTERNAL PUBLISHED FD AFTER ROLLBACK LINK\n")
                os.fsync(published[0][1])
            return value

        try:
            with patch.object(storage.os, "link", side_effect=hold_published_fd_and_write_after_real_restore):
                result = self.service.apply(preview["preview_id"])
            self.assertEqual((len(attempts), len(published), len(restores)), (2, 1, 1))
            name, descriptor, published_identity = published[0]
            os.write(descriptor, b"# EXTERNAL PUBLISHED FD AFTER RETURN\n")
            os.fsync(descriptor)
            os.write(descriptors[name], b"# EXTERNAL ORIGINAL FD AFTER ROLLBACK RETURN\n")
            os.fsync(descriptors[name])
        finally:
            for descriptor in descriptors.values():
                os.close(descriptor)
            for _, descriptor, _ in published:
                os.close(descriptor)
        self.assertFalse(result["saved"])
        self.assertTrue(result["partial_failure"], "失败来自强制第二次发布失败，不是正常保留资料")
        self.assertNotIn("cleanup_pending", result)
        live = [item for item in result["recovery"] if item["kind"] == "isolated_object"]
        rollback = next(item for item in live if tuple(item["observed_identity"][:2]) == published_identity)
        self.assertEqual(rollback["object_role"], "target_at_rollback_isolation")
        self.assertIn(b"EXTERNAL PUBLISHED FD AFTER ROLLBACK LINK", Path(rollback["backup"]).read_bytes())
        self.assertIn(b"EXTERNAL PUBLISHED FD AFTER RETURN", Path(rollback["backup"]).read_bytes())
        before = next(item for item in live if tuple(item["observed_identity"][:2]) == original_identities[name])
        self.assertIn(b"EXTERNAL ORIGINAL FD AFTER ROLLBACK RETURN", Path(before["backup"]).read_bytes())
        for item in result["recovery"]:
            if item["kind"] == "preview_preimage":
                expected = originals[Path(item["target"]).name]
                self.assertEqual(Path(item["backup"]).read_bytes(), expected)
                self.assertEqual(item["sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual((paths[0].parent / name).read_bytes(), originals[name])

    def test_last_window_before_isolation_preserves_actual_external_inode_and_content(self):
        path = self.make(fields={"model": "before"})
        original = path.read_bytes()
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        real_rename, real_replace = storage.os.rename, storage.os.replace
        captured = []

        def replace_target_at_real_isolation(source, destination, **kwargs):
            if source == path.name and destination == "before" and not captured:
                replacement = path.with_name("external-before-isolation.tmp")
                replacement.write_bytes(original + b"# EXTERNAL BEFORE ISOLATION\n")
                identity = (replacement.stat().st_dev, replacement.stat().st_ino)
                real_replace(replacement, path)
                captured.append(identity)
            return real_rename(source, destination, **kwargs)

        with patch.object(storage.os, "rename", side_effect=replace_target_at_real_isolation):
            result = self.service.apply(preview["preview_id"])
        self.assertEqual(len(captured), 1, "负控必须进入真实隔离 rename 窗口")
        self.assertFalse(result["saved"])
        self.assertEqual(path.read_bytes(), original + b"# EXTERNAL BEFORE ISOLATION\n")
        isolated = [Path(item["backup"]) for item in result["recovery"] if item["kind"] == "isolated_object"]
        self.assertTrue(any((item.stat().st_dev, item.stat().st_ino) == captured[0] for item in isolated))
        self.assertTrue(result["temporary_visibility_gap"])
        self.assertTrue(result["effect"]["pending_reload"])

    def test_last_window_exclusive_link_really_rejects_external_target_after_isolation(self):
        path = self.make(fields={"model": "before"})
        original = path.read_bytes()
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        real_link, real_replace = storage.os.link, storage.os.replace
        attempts, rejected = [], []

        def create_target_at_real_publication(source, destination, **kwargs):
            if source == "candidate.new" and destination == path.name:
                self.assertFalse(path.exists(), "必须已隔离旧目标，而不是跳过新发布系统调用")
                replacement = path.with_name("external-after-isolation.tmp")
                replacement.write_bytes(original + b"# EXTERNAL AFTER ISOLATION\n")
                real_replace(replacement, path)
                attempts.append(True)
                try:
                    return real_link(source, destination, **kwargs)
                except FileExistsError:
                    rejected.append(True)
                    raise
            return real_link(source, destination, **kwargs)

        with patch.object(storage.os, "link", side_effect=create_target_at_real_publication):
            result = self.service.apply(preview["preview_id"])
        self.assertEqual((len(attempts), len(rejected)), (1, 1), "新 link syscall 必须实际返回 EEXIST")
        self.assertFalse(result["saved"])
        self.assertEqual(path.read_bytes(), original + b"# EXTERNAL AFTER ISOLATION\n")
        self.assertTrue(any(Path(item["backup"]).read_bytes() == original for item in result["recovery"]))
        self.assertEqual(result["results"], [{"role": opaque, "status": "rollback_conflict"}])

    def test_last_window_before_rollback_isolation_keeps_external_save(self):
        paths = [self.make("first-native"), self.make("second-native")]
        originals = {path.name: path.read_bytes() for path in paths}
        preview = self.preview({row["role"]: {"model": "new"} for row in self.context()["roles"]})
        real_link, real_rename, real_replace = storage.os.link, storage.os.rename, storage.os.replace
        publications, injected = [], []

        def fail_second_publish(source, destination, **kwargs):
            if source == "candidate.new":
                publications.append(destination)
                if len(publications) == 2:
                    raise OSError("fixture second publication failure")
            return real_link(source, destination, **kwargs)

        def edit_before_rollback_capture(source, destination, **kwargs):
            if destination == "rollback" and publications and source == publications[0] and not injected:
                target = paths[0].parent / source
                replacement = target.with_name("external-before-rollback.tmp")
                replacement.write_bytes(originals[source] + b"# EXTERNAL BEFORE ROLLBACK\n")
                identity = (replacement.stat().st_dev, replacement.stat().st_ino)
                real_replace(replacement, target)
                injected.append((target, identity))
            return real_rename(source, destination, **kwargs)

        with patch.object(storage.os, "link", side_effect=fail_second_publish), \
                patch.object(storage.os, "rename", side_effect=edit_before_rollback_capture):
            result = self.service.apply(preview["preview_id"])
        self.assertEqual(len(injected), 1)
        target, identity = injected[0]
        self.assertEqual(target.read_bytes(), originals[target.name] + b"# EXTERNAL BEFORE ROLLBACK\n")
        self.assertFalse(result["saved"])
        self.assertTrue(any((Path(item["backup"]).stat().st_dev, Path(item["backup"]).stat().st_ino) == identity
                            for item in result["recovery"] if item["kind"] == "isolated_object"))

    def test_last_window_rollback_link_really_rejects_external_target(self):
        paths = [self.make("first-native"), self.make("second-native")]
        originals = {path.name: path.read_bytes() for path in paths}
        preview = self.preview({row["role"]: {"model": "new"} for row in self.context()["roles"]})
        real_link, real_replace = storage.os.link, storage.os.replace
        publications, attempts, rejected = [], [], []

        def edit_at_real_restore_link(source, destination, **kwargs):
            if source == "candidate.new":
                publications.append(destination)
                if len(publications) == 2:
                    raise OSError("fixture second publication failure")
            if source == "restore.new" and publications and destination == publications[0] and not attempts:
                target = paths[0].parent / destination
                self.assertFalse(target.exists(), "必须先隔离本服务发布的真实目标")
                replacement = target.with_name("external-after-rollback-isolation.tmp")
                replacement.write_bytes(originals[destination] + b"# EXTERNAL AT RESTORE LINK\n")
                real_replace(replacement, target)
                attempts.append(target)
                try:
                    return real_link(source, destination, **kwargs)
                except FileExistsError:
                    rejected.append(True)
                    raise
            return real_link(source, destination, **kwargs)

        with patch.object(storage.os, "link", side_effect=edit_at_real_restore_link):
            result = self.service.apply(preview["preview_id"])
        self.assertEqual((len(attempts), len(rejected)), (1, 1), "恢复 link syscall 必须实际返回 EEXIST")
        target = attempts[0]
        self.assertEqual(target.read_bytes(), originals[target.name] + b"# EXTERNAL AT RESTORE LINK\n")
        self.assertFalse(result["saved"])
        self.assertTrue(result["recovery"])
        self.assertTrue(all(Path(item["backup"]).stat().st_mode & 0o777 == 0o600 for item in result["recovery"]))

    def test_context_refresh_failure_keeps_partial_save_and_recovery_results(self):
        self.make()
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        with patch.object(self.service, "context", side_effect=ValueError("PRIVATE RAW")):
            result = self.service.apply(preview["preview_id"])
        self.assertTrue(result["saved"])
        self.assertEqual(result["results"], [{"role": opaque, "status": "saved"}])
        self.assertTrue(result["context_unavailable"])
        self.assertNotIn("context", result)
        self.assertNotIn("PRIVATE RAW", json.dumps(result))

    def test_final_directory_exit_conflict_keeps_published_receipt_and_unknown_recovery_locations(self):
        """真实发布和权限收尾后再移动父目录，不能丢收据或猜测恢复资料新路径。"""
        path = self.make(fields={"model": "before"})
        original = path.read_bytes()
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
        identity = (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        moved = path.parent.with_name("agents-moved")
        real_fchmod = storage.os.fchmod
        renamed = []

        def move_parent_after_real_retention_chmod(fd, mode):
            real_fchmod(fd, mode)
            observed = os.fstat(fd)
            if (observed.st_dev, observed.st_ino) == identity and mode == 0o600 and not renamed:
                # 该 fd 是已隔离的原文件；到这里真实 link 和最后一次显式目录检查均已完成。
                path.parent.rename(moved)
                renamed.append(True)

        try:
            with patch.object(storage.os, "fchmod", side_effect=move_parent_after_real_retention_chmod):
                result = self.service.apply(preview["preview_id"])
            os.write(descriptor, b"# OLD FD AFTER FINALIZATION RECEIPT\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.assertEqual(renamed, [True])
        self.assertFalse(path.exists())
        self.assertIn(b'model = "new"', (moved / path.name).read_bytes())
        self.assertFalse(result["saved"])
        self.assertTrue(result["partial_failure"])
        self.assertTrue(result["published"])
        self.assertTrue(result["namespace_touched"])
        self.assertTrue(result["temporary_visibility_gap"])
        self.assertTrue(result["finalization_failed"])
        self.assertEqual(result["error_type"], "ConflictError")
        self.assertEqual(result["results"], [{"role": opaque, "status": "published_location_unknown"}])
        self.assertTrue(result["effect"]["pending_reload"])
        self.assertFalse(result["effect"]["runtime_verified"])
        self.assertEqual(len(result["recovery"]), 2)
        for entry in result["recovery"]:
            self.assertIsNone(entry["backup"])
            self.assertEqual(entry["location_status"], "unknown")
            self.assertTrue(entry["declared_backup"].startswith(str(path.parent) + "/"))
            # 新位置只由测试持有的 rename 夹具确定；产品不得扫描用户目录找回。
            retained = moved / Path(entry["declared_backup"]).relative_to(path.parent)
            self.assertEqual((retained.stat().st_dev, retained.stat().st_ino), tuple(entry["observed_identity"][:2]))
            self.assertEqual((retained.parent.stat().st_dev, retained.parent.stat().st_ino), tuple(entry["container_identity"]))
            if entry["kind"] == "preview_preimage":
                self.assertEqual(retained.read_bytes(), original)
                self.assertEqual(entry["sha256"], hashlib.sha256(original).hexdigest())
            else:
                self.assertEqual(tuple(entry["observed_identity"][:2]), identity)
                self.assertIn(b"OLD FD AFTER FINALIZATION RECEIPT", retained.read_bytes())
        self.assertNotIn("cleanup_pending", result)
        with self.assertRaises(ConflictError):
            self.service.apply(preview["preview_id"])

    def test_parent_move_before_namespace_change_still_rejects_without_publication(self):
        """尚未隔离目标的目录冲突仍直接拒绝；新收据不能掩盖未执行的保存。"""
        path = self.make(fields={"model": "before"})
        original = path.read_bytes()
        preview = self.preview({self.context()["roles"][0]["role"]: {"model": "new"}})
        moved = path.parent.with_name("agents-moved-before-publish")
        real_fchmod = storage.os.fchmod
        renamed = []

        def move_during_staging(fd, mode):
            real_fchmod(fd, mode)
            if not renamed:
                path.parent.rename(moved)
                renamed.append(True)

        with patch.object(storage.os, "fchmod", side_effect=move_during_staging):
            with self.assertRaises(ConflictError):
                self.service.apply(preview["preview_id"])
        self.assertEqual(renamed, [True])
        self.assertEqual((moved / path.name).read_bytes(), original)
        self.assertEqual(list(moved.glob(".native-config-*")), [])

    def test_retention_names_moved_or_replaced_after_publish_are_not_claimed_locatable(self):
        """只动保留名称、保持父目录及目标不变，也不能把旧路径伪报为当前可定位。"""
        for index, (name, replace) in enumerate((name, replace) for name in (None, "before", "before.backup") for replace in (False, True)):
            with self.subTest(retained_name=name or "container", same_bytes_replacement=replace):
                path = self.make("retention-names-" + str(index), fields={"model": "before"})
                original = path.read_bytes()
                parent_identity = (path.parent.stat().st_dev, path.parent.stat().st_ino)
                descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
                observed = os.fstat(descriptor)
                original_identity = (observed.st_dev, observed.st_ino)
                opaque = next(row["role"] for row in self.context()["roles"] if row["source_path"] == str(path))
                preview = self.preview({opaque: {"model": "new"}})
                real_mkdir, real_fchmod = storage.os.mkdir, storage.os.fchmod
                containers, moves = [], []

                def observe_real_container_creation(value, *args, **kwargs):
                    result = real_mkdir(value, *args, **kwargs)
                    if isinstance(value, str) and value.startswith(".native-config-") and value.endswith(".hold"):
                        containers.append(path.parent / value)
                    return result

                def rename_after_real_retention_chmod(fd, mode):
                    real_fchmod(fd, mode)
                    info = os.fstat(fd)
                    if (info.st_dev, info.st_ino) != original_identity or mode != 0o600 or moves:
                        return
                    # 只使用夹具捕获的真实创建名称；产品没有扫描目录找回的权限。
                    container = containers[0]
                    target = container / name if name is not None else container
                    moved = target.with_name(target.name + ".moved")
                    target.rename(moved)
                    moves.append((target, moved))
                    if replace:
                        # 同字节、同节点类型的替身也不能冒充持有 fd 的原 inode。
                        if name is None:
                            target.mkdir(mode=0o700)
                            for child in ("before", "before.backup"):
                                (target / child).write_bytes(original)
                        else:
                            target.write_bytes(original)

                try:
                    with patch.object(storage.os, "mkdir", side_effect=observe_real_container_creation), \
                            patch.object(storage.os, "fchmod", side_effect=rename_after_real_retention_chmod):
                        result = self.service.apply(preview["preview_id"])
                    os.write(descriptor, b"# OLD FD AFTER RETENTION NAME CHANGE\n")
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self.assertEqual(len(containers), 1)
                self.assertEqual(len(moves), 1, "必须先真实发布/fchmod，再真实移动所声明的保留名称")
                self.assertEqual((path.parent.stat().st_dev, path.parent.stat().st_ino), parent_identity)
                self.assertIn(b'model = "new"', path.read_bytes())
                self.assertTrue(result["saved"], "目标保存成功与保留资料位置未知是两个独立事实")
                self.assertTrue(result["published"])
                self.assertFalse(result["partial_failure"])
                self.assertEqual(result["results"], [{"role": opaque, "status": "saved"}])
                self.assertEqual(len(result["recovery"]), 2)
                self.assertNotIn("cleanup_pending", result)
                for entry in result["recovery"]:
                    declared = Path(entry["declared_backup"])
                    affected = name is None or declared.name == name
                    if affected:
                        self.assertIsNone(entry["backup"])
                        self.assertEqual(entry["location_status"], "unknown")
                        actual = moves[0][1] / declared.name if name is None else moves[0][1]
                    else:
                        self.assertEqual(entry["backup"], str(declared))
                        self.assertEqual(entry["location_status"], "verified_at_finalization")
                        actual = declared
                    self.assertEqual((actual.stat().st_dev, actual.stat().st_ino), tuple(entry["observed_identity"][:2]))
                    if entry["kind"] == "preview_preimage":
                        self.assertEqual(actual.read_bytes(), original)
                        self.assertEqual(entry["sha256"], hashlib.sha256(original).hexdigest())
                    else:
                        self.assertEqual(tuple(entry["observed_identity"][:2]), original_identity)
                        self.assertIn(b"OLD FD AFTER RETENTION NAME CHANGE", actual.read_bytes())
                with self.assertRaises(ConflictError):
                    self.service.apply(preview["preview_id"])

    def test_missing_parent_at_storage_entry_preserves_every_not_written_result(self):
        """目录尚未成功打开时没有 handle，最终结算仍需保留明确的未写入结果。"""
        path = self.make(fields={"model": "before"})
        before = storage.read(path)
        opaque = self.context()["roles"][0]["role"]
        change = storage.Write(opaque, path, before, before.body.replace(b'"before"', b'"new"'))
        moved = path.parent.with_name("agents-moved-before-open")
        path.parent.rename(moved)
        result = storage.write_batch((change,), lambda: None)
        self.assertFalse(result["saved"])
        self.assertFalse(result["namespace_touched"])
        self.assertEqual(result["results"], [{"role": opaque, "status": "not_written"}])
        self.assertEqual(result["recovery"], [])
        self.assertEqual(result["error_type"], "FileNotFoundError")
        self.assertEqual((moved / path.name).read_bytes(), before.body)

    def test_real_descriptor_close_failure_is_settled_without_hiding_the_published_objects(self):
        """已真实关闭隔离目录 fd 后再报错，仍返回发布事实与可人工核对的保留身份。"""
        path = self.make(fields={"model": "before"})
        original = path.read_bytes()
        inode = path.stat().st_ino
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        real_fchmod, real_close = storage.os.fchmod, storage.os.close
        armed, failures = [], []

        def arm_after_retention(fd, mode):
            real_fchmod(fd, mode)
            if os.fstat(fd).st_ino == inode:
                armed.append(True)

        def fail_after_real_close(fd):
            real_close(fd)
            if armed and not failures:
                failures.append(True)
                raise OSError("fixture close failed after real close")

        with patch.object(storage.os, "fchmod", side_effect=arm_after_retention), \
                patch.object(storage.os, "close", side_effect=fail_after_real_close), \
                patch.object(self.service, "context", side_effect=ValueError("fixture reread unavailable")):
            result = self.service.apply(preview["preview_id"])
        self.assertEqual(failures, [True])
        self.assertFalse(result["saved"])
        self.assertTrue(result["published"])
        self.assertTrue(result["partial_failure"])
        self.assertTrue(result["finalization_failed"])
        self.assertEqual(result["finalization_error_type"], "OSError")
        self.assertTrue(result["context_unavailable"])
        self.assertEqual(result["results"], [{"role": opaque, "status": "published_location_unknown"}])
        self.assertIn(b'model = "new"', path.read_bytes())
        self.assertEqual(len(result["recovery"]), 2)
        for entry in result["recovery"]:
            self.assertIsNone(entry["backup"], "目录退出验证被异常打断，即使测试知道位置也不能伪报核实")
            retained = Path(entry["declared_backup"])
            self.assertEqual(retained.stat().st_ino, entry["observed_identity"][1])
            self.assertEqual(retained.read_bytes(), original)

    def test_external_edit_during_staging_rejects_whole_batch_before_publication(self):
        first = self.make("first-native")
        second = self.make("second-native")
        before = first.read_bytes()
        preview = self.preview({row["role"]: {"model": "new"} for row in self.context()["roles"]})
        real_fsync = storage.os.fsync
        changed = False
        def alter_source_after_stage(descriptor):
            nonlocal changed
            real_fsync(descriptor)
            if not changed:
                changed = True
                second.write_bytes(second.read_bytes() + b"# EXTERNAL\n")
        with patch.object(storage.os, "fsync", side_effect=alter_source_after_stage):
            with self.assertRaises(ConflictError):
                self.service.apply(preview["preview_id"])
        self.assertEqual(first.read_bytes(), before)
        self.assertIn(b"# EXTERNAL", second.read_bytes())
        self.assertEqual(list(self.home.rglob(".native-config-*")), [])

    def test_post_publication_directory_sync_failure_restores_visible_original(self):
        path = self.make()
        before = path.read_bytes()
        opaque = self.context()["roles"][0]["role"]
        preview = self.preview({opaque: {"model": "new"}})
        real_fsync = storage.os.fsync
        failed = False
        def fail_directory_once(descriptor):
            nonlocal failed
            if stat.S_ISDIR(os.fstat(descriptor).st_mode) and not failed:
                failed = True
                raise OSError("fixture directory failure")
            real_fsync(descriptor)
        with patch.object(storage.os, "fsync", side_effect=fail_directory_once):
            result = self.service.apply(preview["preview_id"])
        self.assertFalse(result["saved"])
        self.assertEqual(result["results"], [{"role": opaque, "status": "rolled_back"}])
        self.assertEqual(path.read_bytes(), before)

    def test_concurrent_services_have_one_cas_winner(self):
        self.make()
        context = self.context()
        opaque = context["roles"][0]["role"]
        other = ModelService(self.data, self.home)
        plans = [(self.service, self.preview({opaque: {"model": "one"}}, context=context)),
                 (other, self.preview({opaque: {"model": "two"}}, context=context, service=other))]
        def apply_one(item):
            try:
                return item[0].apply(item[1]["preview_id"])["saved"]
            except ConflictError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(apply_one, plans)), [False, True])


    def test_persistent_batch_failure_keeps_private_recoverable_original(self):
        paths = [self.make("first-native"), self.make("second-native")]
        originals = {str(path): path.read_bytes() for path in paths}
        preview = self.preview({row["role"]: {"model": "new"} for row in self.context()["roles"]})
        real_link = storage.os.link
        count = 0
        def fail_second_and_restore(source, *args, **kwargs):
            nonlocal count
            count += 1
            if count >= 2:
                raise OSError("fixture persistent failure")
            return real_link(source, *args, **kwargs)
        with patch.object(storage.os, "link", side_effect=fail_second_and_restore):
            result = self.service.apply(preview["preview_id"])
        self.assertFalse(result["saved"])
        self.assertTrue(result["recovery"])
        for recovery in result["recovery"]:
            backup = Path(recovery["backup"])
            if recovery["kind"] == "preview_preimage":
                self.assertEqual(backup.read_bytes(), originals[recovery["target"]])
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_claude_definition_full_model_and_effort_save_without_version_but_overrides_are_separate(self):
        path = self.make(host="claude")
        opaque = self.context("claude")["roles"][0]["role"]
        saved = self.service.apply(self.preview({opaque: {"model": "claude-custom-full-id", "effort": "high"}}, host="claude")["preview_id"])
        resolved = self.service.resolve_subagent("claude", opaque)
        self.assertTrue(saved["saved"])
        self.assertIn(b'"claude-custom-full-id"', path.read_bytes())
        self.assertEqual(resolved["configuration_fields"], {"model": "claude-custom-full-id", "effort": "high"})
        self.assertEqual(resolved["dispatch"], {"subagent_type": "audit-scout"})
        self.assertTrue(resolved["dispatch_ready"])
        self.assertFalse(resolved["per_invocation"]["ready"])
        self.assertNotIn("model", resolved["per_invocation"]["parameters"])
        self.assertNotIn("effort", resolved["per_invocation"]["parameters"])
        self.assertFalse(resolved["runtime_verified"])

    def test_codex_catalog_real_efforts_include_ultra_and_enforce_observed_negative_capability(self):
        self.make(fields={"model": "fixture-model"})
        directory = self.home / ".codex"
        (directory / "config.toml").write_text('model_catalog_json="models.json"\n')
        (directory / "models.json").write_text(json.dumps({"models": [{"id": "fixture-model", "supported_reasoning_levels": [{"effort": "ultra"}, {"effort": "high"}]}]}))
        found = self.service.catalog("codex")
        self.assertEqual(found["models"][0]["efforts"], ["ultra", "high"])
        opaque = self.context()["roles"][0]["role"]
        found["models"][0]["efforts"].append("low")
        with self.assertRaises(ValueError):
            self.preview({opaque: {"effort": "low"}})
        preview = self.preview({opaque: {"effort": "ultra"}})
        self.service.apply(preview["preview_id"])
        resolved = self.service.resolve_subagent("codex", opaque)
        self.assertEqual(resolved["per_invocation"]["parameters"]["reasoning_effort"], "ultra")
        self.assertIn("model_reasoning_effort", resolved["configuration_fields"])

    def test_agy_effort_rejected_and_model_save_does_not_invent_invocation_parameter(self):
        path = self.make(host="antigravity", fields={"model": "flash"})
        opaque = self.context("antigravity")["roles"][0]["role"]
        with self.assertRaises(ValueError):
            self.preview({opaque: {"effort": "high"}}, host="antigravity")
        self.service.apply(self.preview({opaque: {"model": "pro"}}, host="antigravity")["preview_id"])
        resolved = self.service.resolve_subagent("antigravity", opaque)
        self.assertEqual(resolved["configuration_fields"], {"model": "pro"})
        self.assertEqual(resolved["dispatch"], {})
        self.assertFalse(resolved["invoke_ready"])
        self.assertIn(b'model: "pro"', path.read_bytes())

    def test_official_model_list_preserves_returned_ultra_and_future_safe_effort_metadata(self):
        models, cursor = codex_models._models({"data": [{"id": "opaque-id", "model": "future-model", "displayName": "Future",
                                                        "supportedReasoningEfforts": [{"reasoningEffort": "ultra"}, {"reasoningEffort": "nextlevel"}],
                                                        "defaultReasoningEffort": "ultra"}], "nextCursor": None})
        self.assertIsNone(cursor)
        self.assertEqual(models[0].efforts, ("ultra", "nextlevel"))
        self.assertEqual(models[0].default_effort, "ultra")

    def test_explicit_catalog_home_visibility_labels_dedup_and_empty_fallback(self):
        directory = self.home / ".codex"
        directory.mkdir()
        config = directory / "config.toml"
        config.write_text('model_catalog_json="~/explicit-models.json"\n')
        (self.home / "explicit-models.json").write_text(json.dumps({"models": [
            {"id": "visible", "display_name": "Readable Model", "supported_reasoning_levels": ["ultra", "nextlevel", "ultra"]},
            {"id": "visible", "display_name": "Duplicate"}, {"id": "secret-hidden", "visibility": "hidden"}]}))
        result = self.service.catalog("codex")
        self.assertEqual([(row["id"], row["label"]) for row in result["models"]], [("visible", "Readable Model")])
        self.assertEqual(result["models"][0]["efforts"], ["ultra", "nextlevel"])
        config.write_text('model_catalog_json=""\n')
        native = codex_models.NativeModels((codex_models.NativeModel("native", "Native", ("high",), "high"),))
        with patch.object(codex_models, "query", return_value=native):
            result = self.service.catalog("codex")
        self.assertEqual(result["models"][0]["id"], "native")

    def test_catalog_query_guard_identity_provider_binary_and_apply_source_conflict(self):
        directory = self.home / ".codex"
        directory.mkdir()
        config = directory / "config.toml"
        config.write_text('model_provider="first"\n')
        auth = directory / "auth.json"
        auth.write_text("do-not-read-credentials")
        native = codex_models.NativeModels((codex_models.NativeModel("observed", "Observed", ("high",), "high"),))
        original_read = storage.read
        def forbid_auth(path):
            self.assertNotEqual(path, auth, "auth body must never be read")
            return original_read(path)
        def change_provider(*_args):
            config.write_text('model_provider="second"\n')
            return native
        with patch.object(storage, "read", side_effect=forbid_auth), patch.object(codex_models, "query", side_effect=change_provider):
            discarded = self.service.catalog("codex")
        self.assertEqual(discarded["status"], "failed")
        self.assertEqual(discarded["models"], [])
        with patch.object(codex_models, "query", return_value=native):
            self.assertEqual(self.service.catalog("codex")["status"], "ready")
        context = self.context()
        plan = self.service.preview({"host": "codex", "revision": context["revision"],
                                     "dispatch_preferences": {"edits": {"*": {"model": "observed", "effort": "high"}}}})
        auth.write_text("identity-changed-without-reading")
        with self.assertRaises(ConflictError):
            self.service.apply(plan["preview_id"])
        with self.assertRaises(ConflictError):
            self.service.preview({"host": "codex", "revision": self.context()["revision"],
                                  "dispatch_preferences": {"edits": {"*": {"model": "observed", "effort": "high"}}}})
        # 可执行文件身份同样参与失效，不依赖路径字符串是否变化。
        from native_config import catalog
        binary = self.root / "codex-fixture"
        binary.write_text("binary-one")
        with patch.object(codex_models, "executable", return_value=str(binary)):
            first = catalog.source_stamp(directory, None, self.service.environment)
            binary.write_text("binary-two")
            self.assertNotEqual(first, catalog.source_stamp(directory, None, self.service.environment))

    def test_context_catalog_source_changes_without_changing_config_revision_or_querying_cli(self):
        directory = self.home / ".codex"
        directory.mkdir()
        auth = directory / "auth.json"
        auth.write_text("fixture-credentials-never-read")
        real_read = storage.read
        def forbid_credentials(path):
            self.assertNotEqual(path, auth)
            return real_read(path)
        with patch.object(storage, "read", side_effect=forbid_credentials), \
                patch.object(codex_models, "query", side_effect=AssertionError("context must not query a native CLI")):
            first = self.context()
            self.service.environment["OPENAI_BASE_URL"] = "https://provider-fixture.invalid"
            provider_changed = self.context()
            auth.write_text("fixture-account-metadata-changed")
            identity_changed = self.context()
        self.assertEqual(first["revision"], provider_changed["revision"])
        self.assertEqual(first["revision"], identity_changed["revision"])
        self.assertNotEqual(first["catalog_source_stamp"], provider_changed["catalog_source_stamp"])
        self.assertNotEqual(provider_changed["catalog_source_stamp"], identity_changed["catalog_source_stamp"])
        self.assertRegex(identity_changed["catalog_source_stamp"], r"^[0-9a-f]{64}$")
        from native_config import catalog
        self.assertEqual(identity_changed["catalog_source_stamp"], catalog.source_stamp(directory, None, self.service.environment))

    def test_context_unavailable_catalog_source_is_null_without_disabling_preferences(self):
        directory = self.home / ".codex"
        directory.mkdir()
        (directory / "config.toml").write_text('model_catalog_json="models.json"\n')
        explicit = directory / "models.json"
        explicit.write_text(json.dumps({"models": [{"id": "old-candidate", "supported_reasoning_levels": ["high"]}]}))
        found = self.service.catalog("codex")
        self.assertEqual(found["status"], "ready")
        first = self.context()
        self.assertEqual(first["catalog_source_stamp"], found["source_stamp"])
        explicit.unlink()
        external = self.root / "unsafe-model-source"
        external.write_text("must-not-be-read")
        explicit.symlink_to(external)
        with patch.object(codex_models, "query", side_effect=AssertionError("context must not query a native CLI")):
            unavailable = self.context()
        self.assertEqual(first["revision"], unavailable["revision"])
        self.assertIsNone(unavailable["catalog_source_stamp"])
        diagnostics = [row for row in unavailable["diagnostics"] if row["code"] == "catalog_source_unavailable"]
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("无法安全读取", diagnostics[0]["message"])
        self.assertNotIn("must-not-be-read", json.dumps(unavailable))
        self.assertTrue(unavailable["dispatch_preferences"]["targets"][0]["writable"])
        self.assertEqual(self.service._catalogs[("codex", "None")]["source_stamp"], found["source_stamp"])
        # 来源不可得不把旧目录更新为新目录，也不阻断独立偏好的正常编辑保存。
        plan = self.service.preview({"host": "codex", "revision": unavailable["revision"],
                                     "dispatch_preferences": {"edits": {"*": {"model": "manual-unverified"}}}})
        # 该预览没有采用旧目录能力，因此保存不绑定已不可得的目录摘要。
        self.assertEqual(plan["changes"][0]["after"], "manual-unverified")
        saved = self.service.apply(plan["preview_id"])
        self.assertTrue(saved["saved"])
        self.assertIsNone(saved["context"]["catalog_source_stamp"])
        self.assertEqual(saved["context"]["dispatch_preferences"]["targets"][0]["effective"], {"model": "manual-unverified"})

    def test_catalog_final_stamp_window_rejects_new_identity_on_old_models(self):
        from native_config import catalog
        directory = self.home / ".codex"
        directory.mkdir()
        config = directory / "config.toml"
        config.write_text('model_provider="first"\n')
        native = codex_models.NativeModels((codex_models.NativeModel("old-account-model", "Old", ("high",), "high"),))
        original = catalog.source_stamp
        def switch_at_binding(*args, **kwargs):
            if kwargs.get("include_cache", True):
                config.write_text('model_provider="new-account"\n')
            return original(*args, **kwargs)
        with patch.object(codex_models, "query", return_value=native), patch.object(catalog, "source_stamp", side_effect=switch_at_binding):
            result = self.service.catalog("codex")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["models"], [])
        self.assertNotIn("source_stamp", result)

    def test_query_cache_identity_refresh_is_adopted_only_after_stable_source(self):
        directory = self.home / ".codex"
        directory.mkdir()
        cache = directory / "models_cache.json"
        cache.write_text(json.dumps({"identity": "old", "models": [{"id": "untrusted-cache-only"}]}))
        native = codex_models.NativeModels((codex_models.NativeModel("official", "Official", ("high",), "high"),))
        def refresh(*_args):
            cache.write_text(json.dumps({"identity": "new"}))
            return native
        with patch.object(codex_models, "query", side_effect=refresh):
            found = self.service.catalog("codex")
        self.assertEqual([row["id"] for row in found["models"]], ["official"])
        from native_config import catalog
        self.assertEqual(found["source_stamp"], catalog.source_stamp(directory, None, self.service.environment))
        cache.write_text(json.dumps({"identity": "another-account"}))
        self.assertNotEqual(found["source_stamp"], catalog.source_stamp(directory, None, self.service.environment))

    def test_claude_local_menu_current_and_mapping_do_not_claim_effort_or_account(self):
        directory = self.home / ".claude"
        directory.mkdir()
        (directory / "settings.json").write_text(json.dumps({"model": "user-current", "env": {"ANTHROPIC_DEFAULT_OPUS_MODEL": "mapped-opus"},
            "modelPicker": {"options": [{"value": "menu-id", "label": "Local menu"}]}, "modelSettings": {"menu-id": {"effort": "high"}}}))
        local = self.project / ".claude"
        local.mkdir()
        (local / "settings.json").write_text(json.dumps({"model": "project-current", "modelPicker": {"options": ["must-ignore-project-menu"]}}))
        (local / "settings.local.json").write_text(json.dumps({"env": {"ANTHROPIC_MODEL": "local-current", "ANTHROPIC_DEFAULT_OPUS_MODEL": "mapped-local-opus"}}))
        with patch("native_config.service.observe_claude_version", return_value={"status": "probe_failed", "version": None}):
            result = self.service.catalog("claude", self.project)
        by_id = {row["id"]: row for row in result["models"]}
        self.assertIn("mapped-local-opus", by_id["opus"]["label"])
        self.assertIn("menu-id", by_id)
        self.assertIn("local-current", by_id)
        self.assertNotIn("must-ignore-project-menu", by_id)
        self.assertFalse(any(row["efforts_verified"] for row in by_id.values()))
        self.assertEqual(by_id["menu-id"]["usage"], "native_definition_only")

    def test_agy_known_text_protocol_session_scope_and_invalid_mixed_output(self):
        from native_config import agy_models
        body = b"gemini-4-argon-medium Gemini 4 Argon (Medium)\nclaude-opus-5-5-low Claude Opus 5.5 (Low)\n"
        parsed = agy_models.parse_output(body)
        self.assertEqual(parsed[0]["label"], "Gemini 4 Argon (Medium)")
        self.assertTrue(all(row["usage"] == "session_only" for row in parsed))
        for value in (b"", body + b"Warning: internal diagnostic\n", b"bad/id Label\n"):
            with self.assertRaises(ValueError):
                agy_models.parse_output(value)
        with patch.object(agy_models, "query", return_value={"status": "ready", "models": parsed, "notes": []}):
            result = self.service.catalog("antigravity")
        self.assertEqual([row["id"] for row in result["subagent_models"]], ["inherit", "flash", "pro"])
        self.assertTrue(all(row["usage"] == "session_only" for row in result["models"]))

    def test_agy_real_fixture_cli_bounded_output_timeout_and_process_cleanup(self):
        from native_config import agy_models
        binary = self.root / "agy-fixture"
        marker = self.root / "agy-pid"
        binary.write_text("#!" + sys.executable + "\n" +
            "import os,sys,time\n" +
            "from pathlib import Path\n" +
            "Path(os.environ['AGY_PID']).write_text(str(os.getpid()))\n" +
            "mode=os.environ.get('AGY_MODE','normal')\n" +
            "if mode=='slow': time.sleep(10)\n" +
            "print('gemini-4-argon-medium Gemini 4 Argon (Medium)' if mode=='normal' else 'x'*2048,flush=True)\n")
        binary.chmod(0o700)
        env = {**self.service.environment, "AGY_PID": str(marker)}
        normal = agy_models.query(str(binary), self.root, env)
        self.assertEqual(normal["status"], "ready")
        for mode in ("slow", "large"):
            with patch.object(agy_models, "TIMEOUT_SECONDS", 0.15), patch.object(agy_models, "MAX_OUTPUT_BYTES", 512):
                failed = agy_models.query(str(binary), self.root, {**env, "AGY_MODE": mode})
            self.assertEqual(failed["status"], "failed")
            pid = int(marker.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_package_import_and_context_work_without_workflow_or_manager_package(self):
        isolated = self.root / "isolated"
        isolated.mkdir()
        source = Path(__file__).resolve().parents[1]
        shutil.copytree(source / "native_config", isolated / "native_config")
        # 独立发布包合法携带这三个仅依赖标准库的身份合同文件。按确切清单补齐
        # 最小载荷，禁止复制整个 product/工作流或用源码路径回退掩盖漏打包依赖。
        identity_files = {"__init__.py", "command_identity.py", "command_identity.json"}
        (isolated / "product").mkdir()
        for name in identity_files:
            shutil.copyfile(source / "product" / name, isolated / "product" / name)
        self.assertEqual({"native_config", "product"}, {path.name for path in isolated.iterdir()})
        self.assertEqual(identity_files, {path.name for path in (isolated / "product").iterdir()})
        script = ("import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                  "import native_config; from product import command_identity; "
                  "assert all(Path(module.__file__).resolve().is_relative_to(Path(sys.argv[1])) for module in (native_config,command_identity)); "
                  "from native_config import ModelService; "
                  "service=ModelService(Path(sys.argv[2]),Path(sys.argv[3])); "
                  "assert service.context('codex')['roles']==[]; "
                  "assert not any(key=='lib' or key.startswith('lib.') or key=='manager' or key.startswith('manager.') for key in sys.modules)")
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", script,
                                 str(isolated), str(self.data), str(self.home)], cwd=isolated,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class WorkflowActivationTest(unittest.TestCase):
    """在隔离 HOME 和项目中验证真正原生路径、首次发布及来源冲突。"""
    setUp = NativeConfigServiceTest.setUp

    def codex(self, *, second=False):
        target = self.home / ".codex/config.toml"
        target.parent.mkdir(exist_ok=True)
        target.write_text('[marketplaces."agent-workflow-alpha"]\nsource_type="git"\n'
                          'source="https://github.com/Geoege-xll/agent-workflow.git"\nref="plugins-codex-alpha"\n'
                          '[plugins."agent-workflow@agent-workflow-alpha"]\nenabled=true\n'
                          + ('[plugins."agent-workflow@agent-workflow-local"]\nenabled=false\n' if second else ''))
        return target

    def claude(self):
        root, _ = claude_plugin(self.home, name="agent-workflow")
        registry = self.home / ".claude/plugins/installed_plugins.json"
        raw = json.loads(registry.read_bytes())
        raw["plugins"]["agent-workflow@agent-workflow-alpha"] = raw["plugins"].pop("agent-workflow@market")
        registry.write_text(json.dumps(raw))
        target = self.home / ".claude/settings.json"
        target.write_text('{"enabledPlugins":{"agent-workflow@agent-workflow-alpha":true},"other":42}\n')
        return target, root

    def preview(self, host="codex", *, state="disabled", project=False, context=None):
        context = context or self.service.context(host, "project" if project else "global", self.project if project else None)
        return self.service.preview({"host": host, "scope": context["scope"], "project": context["project"],
                                     "revision": context["revision"], "workflow_activation": {"state": state}})

    def test_codex_project_first_create_preview_zero_write_inherit_and_recovery_command(self):
        user = self.codex()
        before = user.read_bytes()
        context = self.service.context("codex", "project", self.project)
        row = context["workflow_activation"]
        self.assertTrue(row["writable"])
        self.assertEqual((row["state"], row["inherited_state"], row["effective_state"]), ("inherit", "enabled", "enabled"))
        self.assertEqual(row["inherited_source"], str(user))
        preview = self.preview(project=True, context=context)
        target = self.project / ".codex/config.toml"
        self.assertFalse(target.parent.exists())
        self.assertEqual(preview["changes"][0]["kind"], "workflow_activation")
        self.assertEqual(preview["changes"][0]["before"], "inherit")
        result = self.service.apply(preview["preview_id"])
        self.assertTrue(result["saved"], result)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        self.assertIn(b'enabled = false', target.read_bytes())
        self.assertEqual(user.read_bytes(), before)
        self.assertTrue(result["effect"]["pending_reload"])
        self.assertFalse(result["context"]["workflow_activation"]["runtime_verified"])
        self.assertTrue(Path(__file__).resolve().parents[1].as_posix() in row["recovery"]["open_command"])
        result = self.service.apply(self.preview(project=True, state="inherit")["preview_id"])
        self.assertTrue(result["saved"])
        self.assertEqual(result["context"]["workflow_activation"]["effective_state"], "enabled")
        self.assertNotIn(b'enabled', target.read_bytes())
        with self.assertRaises(ConflictError):
            self.service.apply(preview["preview_id"])

    def test_recovery_command_preserves_explicit_and_environment_roots(self):
        """用真实 CLI parser 重建服务参数，识别缺参及环境根被 --home 屏蔽的回归。"""
        from native_config.cli import parser
        from native_config.server import configuration_identity
        selected_home = self.root / "home with space ' $(untrusted)"
        selected_home.mkdir()
        selected_data = self.root / "state with space ' $(untrusted)"
        environment = {"HOME": str(selected_home),
                       "CODEX_HOME": str(self.root / "custom codex ' $(untrusted)"),
                       "CLAUDE_CONFIG_DIR": str(self.root / "custom claude ' $(untrusted)"),
                       "UNRELATED_SECRET_TOKEN": "must-not-appear-in-recovery"}
        for explicit in (True, False):
            with self.subTest(explicit_home=explicit), patch.dict(os.environ, environment):
                before_environment = dict(os.environ)
                service = ModelService(selected_data, selected_home if explicit else None)
                for host in ("codex", "claude"):
                    for scope in ("global", "project"):
                        context = service.context(host, scope, self.project if scope == "project" else None)
                        command = context["workflow_activation"]["recovery"]["open_command"]
                        self.assertNotIn(environment["UNRELATED_SECRET_TOKEN"], command)
                        parts = shlex.split(command)
                        recovered_environment = {**os.environ, "HOME": str(self.home),
                                                 "CODEX_HOME": str(self.home / "wrong-codex"),
                                                 "CLAUDE_CONFIG_DIR": str(self.home / "wrong-claude")}
                        if not explicit:
                            self.assertEqual(parts.pop(0), "env")
                            assignments = [parts.pop(0) for _ in range(3)]
                            self.assertEqual({entry.split("=", 1)[0] for entry in assignments},
                                             {"HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR"})
                            recovered_environment.update(dict(entry.split("=", 1) for entry in assignments))
                        self.assertEqual(parts[0], "bash")
                        self.assertEqual(Path(parts[1]), Path(__file__).resolve().parents[1] / "scripts/agent_config.sh")
                        args = parser().parse_args(parts[2:])
                        self.assertEqual(args.command, "open")
                        self.assertEqual(args.host, host)
                        self.assertEqual(args.data_dir, selected_data)
                        self.assertEqual(args.home, selected_home if explicit else None)
                        self.assertEqual(args.project, str(self.project) if scope == "project" else None)
                        with patch.dict(os.environ, recovered_environment, clear=True):
                            reopened = ModelService(args.data_dir, args.home)
                        self.assertEqual(reopened.host_roots, service.host_roots)
                        self.assertEqual(reopened.home, service.home)
                        self.assertEqual(configuration_identity(reopened), configuration_identity(service))
                self.assertEqual(dict(os.environ), before_environment, "生成恢复命令不能改写服务进程环境")

    def test_claude_local_inherits_shared_before_user_and_install_change_invalidates_preview(self):
        user, root = self.claude()
        shared = self.project / ".claude/settings.json"
        shared.parent.mkdir()
        shared.write_text('{"enabledPlugins":{"agent-workflow@agent-workflow-alpha":false},"shared":true}\n')
        context = self.service.context("claude", "project", self.project)
        row = context["workflow_activation"]
        self.assertEqual(row["source_path"], str(shared.with_name("settings.local.json")))
        self.assertEqual((row["state"], row["inherited_state"]), ("inherit", "disabled"))
        self.assertEqual(row["inherited_source"], str(shared))
        self.assertIn("--scope local", row["recovery"]["official_steps"][0])
        before = (user.read_bytes(), shared.read_bytes())
        result = self.service.apply(self.preview("claude", project=True, state="enabled", context=context)["preview_id"])
        self.assertTrue(result["saved"], result)
        self.assertEqual(result["context"]["workflow_activation"]["effective_state"], "enabled")
        self.assertEqual((user.read_bytes(), shared.read_bytes()), before)
        result = self.service.apply(self.preview("claude", project=True, state="inherit")["preview_id"])
        self.assertEqual(result["context"]["workflow_activation"]["effective_state"], "disabled")
        preview = self.preview("claude", state="disabled")
        (root / ".claude-plugin/plugin.json").write_text('{"name":"agent-workflow","version":"external"}')
        with self.assertRaises(ConflictError):
            self.service.apply(preview["preview_id"])
        self.assertEqual(user.read_bytes(), before[0])

    def test_source_ambiguity_unknown_and_unsupported_do_not_write(self):
        for host in ("codex", "claude", "antigravity"):
            context = self.service.context(host)
            row = context["workflow_activation"]
            self.assertFalse(row["writable"])
            self.assertEqual(row["effective_state"], "unknown")
            with self.assertRaises(ValueError):
                self.preview(host, context=context)
        self.codex(second=True)
        self.assertFalse(self.service.context("codex")["workflow_activation"]["writable"])
        self.codex()
        context = self.service.context("codex")
        base = {"host": "codex", "revision": context["revision"], "workflow_activation": {"state": "disabled"}}
        for extra in ({"edits": {}}, {"reset": False}, {"source_path": "/tmp/injected"},
                      {"workflow_activation": {"state": []}}, {"workflow_activation": {"state": "unknown"}},
                      {"workflow_activation": {"state": "enabled", "plugin_id": "bad"}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.service.preview({**base, **extra})

    def test_first_create_external_file_parent_swap_and_inherited_source_change_reject_old_plan(self):
        user = self.codex()
        for kind in ("new_file", "new_parent", "source", "symlink"):
            with self.subTest(kind=kind):
                parent = self.project / ".codex"
                if parent.exists():
                    shutil.rmtree(parent)
                context = self.service.context("codex", "project", self.project)
                preview = self.preview(project=True, context=context)
                target = parent / "config.toml"
                if kind in {"new_file", "new_parent"}:
                    parent.mkdir()
                    if kind == "new_file":
                        target.write_text('# external\n')
                elif kind == "source":
                    user.write_bytes(user.read_bytes() + b'# external source\n')
                else:
                    parent.symlink_to(user.parent, target_is_directory=True)
                with self.assertRaises(ConflictError):
                    self.service.apply(preview["preview_id"])
                if kind == "new_file":
                    self.assertEqual(target.read_bytes(), b'# external\n')
                if kind == "symlink":
                    parent.unlink()

    def test_first_create_link_race_and_post_publish_failure_preserve_actual_files(self):
        self.codex()
        parent = self.project / ".codex"
        parent.mkdir()
        target = parent / "config.toml"
        real_link = storage.os.link
        preview = self.preview(project=True)
        def external_creation(source, destination, **kwargs):
            if source == "candidate.new":
                target.write_bytes(b'# external winner\n')
            return real_link(source, destination, **kwargs)
        with patch.object(storage.os, "link", side_effect=external_creation):
            result = self.service.apply(preview["preview_id"])
        self.assertFalse(result["saved"])
        self.assertFalse(result["published"])
        self.assertEqual(target.read_bytes(), b'# external winner\n')
        target.unlink()
        preview = self.preview(project=True)
        real_fsync = storage.os.fsync
        published = []
        def publish(source, destination, **kwargs):
            result = real_link(source, destination, **kwargs)
            if source == "candidate.new":
                published.append(True)
            return result
        def fail_sync(descriptor):
            if published and stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("fixture post publication sync failure")
            return real_fsync(descriptor)
        with patch.object(storage.os, "link", side_effect=publish), patch.object(storage.os, "fsync", side_effect=fail_sync):
            result = self.service.apply(preview["preview_id"])
        self.assertFalse(result["saved"])
        self.assertTrue(result["published"])
        self.assertTrue(result["partial_failure"])
        self.assertEqual(result["results"][0]["status"], "recovery_required")
        self.assertTrue(result["created_files"][0]["before_absent"])
        self.assertIn(b'enabled = false', target.read_bytes())

    def test_first_parent_exclusive_publication_rejects_external_directory_and_detects_move(self):
        self.codex()
        parent = self.project / ".codex"
        real_publish = storage._rename_directory_exclusive
        for race in ("external_directory", "move_after_publication"):
            with self.subTest(race=race):
                preview = self.preview(project=True)
                def publish(descriptor, source, destination):
                    if race == "external_directory":
                        parent.mkdir()
                        (parent / "external").write_text("preserve")
                        return real_publish(descriptor, source, destination)
                    real_publish(descriptor, source, destination)
                    parent.rename(self.project / "moved-own-config")
                    parent.mkdir()
                    (parent / "external").write_text("preserve")
                with patch.object(storage, "_rename_directory_exclusive", side_effect=publish):
                    if race == "external_directory":
                        with self.assertRaises(ConflictError):
                            self.service.apply(preview["preview_id"])
                    else:
                        result = self.service.apply(preview["preview_id"])
                        self.assertFalse(result["saved"])
                        self.assertFalse(result["published"])
                        self.assertTrue(result["namespace_touched"])
                self.assertEqual((parent / "external").read_text(), "preserve")
                self.assertFalse((parent / "config.toml").exists())
                shutil.rmtree(parent)

    def test_local_codex_identity_and_marketplace_manifest_changes_are_bound_to_revision(self):
        config = self.codex()
        market = self.root / "market"
        manifest = market / ".agents/plugins/marketplace.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "agent-workflow-local", "plugins": [{"name": "agent-workflow", "source": {"source": "local", "path": "./plugins/agent-workflow"}}]}))
        plugin = market / "plugins/agent-workflow/.codex-plugin/plugin.json"
        plugin.parent.mkdir(parents=True)
        plugin.write_text('{"name":"agent-workflow"}')
        config.write_text('[marketplaces."agent-workflow-local"]\nsource_type="local"\nsource=' + json.dumps(str(market))
                          + '\n[plugins."agent-workflow@agent-workflow-local"]\nenabled=true\n')
        context = self.service.context("codex")
        self.assertTrue(context["workflow_activation"]["writable"])
        self.assertEqual(context["workflow_activation"]["plugin_id"], "agent-workflow@agent-workflow-local")
        preview = self.preview(context=context)
        plugin.write_text('{"name":"agent-workflow","version":"external-change"}')
        with self.assertRaises(ConflictError):
            self.service.apply(preview["preview_id"])

    def test_activation_existing_file_keeps_old_handle_and_rejects_readonly_permissions(self):
        target = self.codex()
        original = target.read_bytes()
        descriptor = os.open(target, os.O_WRONLY | os.O_APPEND)
        try:
            result = self.service.apply(self.preview()["preview_id"])
            self.assertTrue(result["saved"], result)
            os.write(descriptor, b'# external old handle\n')
        finally:
            os.close(descriptor)
        retained = next(item for item in result["recovery"] if item["kind"] == "isolated_object")
        self.assertEqual(Path(retained["backup"]).read_bytes(), original + b'# external old handle\n')
        self.assertNotIn(b'old handle', target.read_bytes())
        target.chmod(0o400)
        self.assertFalse(self.service.context("codex")["workflow_activation"]["writable"])
        with self.assertRaises(ValueError):
            self.preview(state="enabled")

    def test_first_creation_concurrent_services_have_only_one_publication(self):
        self.codex()
        other = ModelService(self.data, self.home)
        context = self.service.context("codex", "project", self.project)
        one = self.preview(project=True, context=context)
        two = other.preview({"host": "codex", "scope": "project", "project": str(self.project),
                             "revision": context["revision"], "workflow_activation": {"state": "enabled"}})
        def save(pair):
            try:
                return pair[0].apply(pair[1]["preview_id"])["saved"]
            except ConflictError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(save, ((self.service, one), (other, two)))), [False, True])
        self.assertTrue((self.project / ".codex/config.toml").is_file())


if __name__ == "__main__":
    unittest.main()
