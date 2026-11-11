"""独立原生配置服务闭环：真实文件保存、批量前像保护及宿主能力负控。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
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

    def test_package_import_and_context_work_without_workflow_or_manager_package(self):
        isolated = self.root / "isolated"
        isolated.mkdir()
        source = Path(__file__).resolve().parents[1] / "native_config"
        shutil.copytree(source, isolated / "native_config")
        script = ("import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                  "from native_config import ModelService; "
                  "service=ModelService(Path(sys.argv[2]),Path(sys.argv[3])); "
                  "assert service.context('codex')['roles']==[]; "
                  "assert not any(key=='lib' or key.startswith('lib.') or key=='manager' or key.startswith('manager.') for key in sys.modules)")
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", script,
                                 str(isolated), str(self.data), str(self.home)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
