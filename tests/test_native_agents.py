"""只使用请求 scratch 验证全局归属、原生路径、固定预览与稀疏完整描述符。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib import role_models, runtime_store
from lib.central.runtime_project import CONFIG, Node, Resources, Tree, json_bytes, prepare
from lib.hosts.native_context import HostPaths, NativeContext
from lib.hosts import native_agents as native
from manager import native_agents
from tests import test_workflow_manager as fixtures


class NativeAgentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="native-agents-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        cls.root = Path(cls.temporary.name).resolve()
        cls.source = fixtures.CentralCliIntegrationTest.create_source(cls.root)
        cls.state = cls.root / "state"
        cls.core = runtime_store.import_core(cls.source, cls.state)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.case = self.root / self._testMethodName
        self.case.mkdir()
        self.home = self.case / "home"
        self.home.mkdir()
        self.paths = HostPaths.for_home(self.home, environment={})
        self.context = NativeContext(self.state, self.paths)

    def preview(self, **options):
        return native_agents.preview_global(self.state, self.core.binding(), context=self.context, **options)

    def install(self, **options):
        plan = self.preview(**options)
        self.assertTrue(plan.can_apply, plan.summary)
        return native_agents.apply_global(plan)

    def test_admission_uses_current_authority_not_historical_roots_and_detects_deleted_global(self):
        from manager import central_runtime
        older = HostPaths.for_home(self.case / "older-home", environment={})
        older_context = NativeContext(self.state, older)
        native_agents.apply_global(native_agents.preview_global(self.state, self.core.binding(), context=older_context))
        central_runtime.apply(central_runtime.preview(self.state, binding=self.core.binding(), native_context=self.context))
        with patch("pathlib.Path.home", side_effect=AssertionError("准入不得猜HOME")):
            self.assertEqual(native_agents.admission_issues(self.state, hosts=("codex",)), [])
            (self.paths.codex / "agents/xy-backend.toml").unlink()
            issues = native_agents.admission_issues(self.state, hosts=("codex",))
        self.assertTrue(any(row["code"] == "native_ownership_conflict" for row in issues), issues)
        self.assertEqual(native_agents.status(self.state, "codex", context=older_context)["roles"], sorted(role_models.ROLES))
        self.assertTrue(all(set(row) == {"code", "path", "reason"} for row in issues))

    def test_pending_lifecycle_refuses_global_native_and_preference_writes_without_project_targets(self):
        from manager import central_runtime, runtime_lifecycle, model_preferences
        from manager.catalog import Catalog, Model
        central_runtime.apply(central_runtime.preview(self.state, binding=self.core.binding(), native_context=self.context))
        native_plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "planned-model"}}})
        preference_plan = model_preferences.preview(self.state, None, "codex", {"xy-backend": {"effort": "high"}},
                                                     Catalog("codex", [Model("inherit", "inherit", "fixture")]),
                                                     native_context=self.context)
        self.assertTrue(preference_plan.summary["can_apply"], preference_plan.summary)
        archive = self.case / ".sync-backups/approved-archive"
        archive.mkdir(parents=True)
        (archive / "one.txt").write_text("owned archival bytes")
        lifecycle_plan = runtime_lifecycle.preview(self.state, approved_backup_roots=(archive,), include_cores=False)
        with patch.object(runtime_lifecycle, "_delete_snapshot", side_effect=KeyboardInterrupt("fixture lifecycle interruption")):
            with self.assertRaises(KeyboardInterrupt):
                runtime_lifecycle.apply(lifecycle_plan)
        self.assertEqual(json.loads((self.state / runtime_lifecycle.RELATIVE).read_bytes())["phase"], "prepared")
        native_before = (self.paths.codex / "agents/xy-backend.toml").read_bytes()
        prefs_before = native.read_node(self.state, "preferences/role-models.json")
        journals_before = tuple(sorted((self.state / "native-agents/transactions").glob("*.json")))
        pref_journals_before = tuple(sorted((self.state / "preferences/transactions").glob("*.json")))
        with self.assertRaisesRegex(ValueError, "生命周期事务尚未结算"):
            native_agents.apply_global(native_plan)
        with self.assertRaisesRegex(ValueError, "生命周期事务尚未结算"):
            model_preferences.apply(preference_plan)
        self.assertEqual((self.paths.codex / "agents/xy-backend.toml").read_bytes(), native_before)
        self.assertEqual(native.read_node(self.state, "preferences/role-models.json"), prefs_before)
        self.assertEqual(tuple(sorted((self.state / "native-agents/transactions").glob("*.json"))), journals_before)
        self.assertEqual(tuple(sorted((self.state / "preferences/transactions").glob("*.json"))), pref_journals_before)
        runtime_lifecycle.recover(self.state)

    def test_explicit_paths_ignore_ambient_environment_and_custom_state_requires_paths(self):
        with patch.dict(os.environ, {"CODEX_HOME": "/untrusted/codex", "CLAUDE_CONFIG_DIR": "/untrusted/claude"}):
            self.assertEqual(HostPaths.for_home(self.home), self.paths)
        self.assertEqual(self.paths.antigravity, self.home / ".gemini/config")
        self.assertEqual(HostPaths.for_home(self.home, environment={"CODEX_HOME": str(self.case / "custom")}).codex,
                         self.case / "custom")
        with self.assertRaises(ValueError):
            NativeContext.for_state(self.case / "custom-state")

    def test_preview_cancel_zero_write_apply_complete_roles_no_preload_and_noop_zero_write(self):
        before = tuple(self.case.rglob("*"))
        plan = self.preview()
        self.assertEqual(tuple(self.case.rglob("*")), before)
        self.assertEqual(plan.hosts, role_models.HOSTS)
        self.assertEqual(len(plan.summary["changes"]), 21)
        receipt = native_agents.apply_global(plan)
        self.assertEqual(native_agents.verify_global(plan.recovery_ref, context=self.context), [])
        self.assertTrue(receipt["applied"])
        self.assertEqual(native_agents.verified_hosts(self.state, context=self.context), role_models.HOSTS)
        for host in role_models.HOSTS:
            for role in role_models.ROLES:
                body = (self.paths.root(host) / native.role_relative(host, role)).read_bytes()
                native.validate_descriptor(body, host, role)
                self.assertIn(b"Before any project check", body)
                self.assertNotIn(b"skills:", body)
            self.assertFalse((self.paths.root(host) / "AGENTS.md").exists())
        next_plan = self.preview()
        state_before = {(str(path), path.stat().st_mtime_ns) for path in (self.state / "native-agents").rglob("*")}
        self.assertEqual(native_agents.apply_global(next_plan)["status"], "noop")
        self.assertEqual(state_before, {(str(path), path.stat().st_mtime_ns) for path in (self.state / "native-agents").rglob("*")})

    def test_marker_and_declared_name_alias_cannot_take_ownership(self):
        root = self.paths.codex / "agents"
        root.mkdir(parents=True)
        (root / "alias.toml").write_text('name="xy-backend"\ndeveloper_instructions="user"\n')
        plan = self.preview(hosts=("codex",))
        self.assertFalse(plan.can_apply)
        self.assertTrue(any("相同" in row["reason"] for row in plan.conflicts))
        (root / "alias.toml").unlink()
        (root / "xy-backend.toml").write_text('# agent-workflow-central-project\nname="xy-backend"\n')
        self.assertFalse(self.preview(hosts=("codex",)).can_apply)

    def test_managed_manual_delete_and_preview_drift_remain_conflicts(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        target.unlink()
        self.assertFalse(self.preview(hosts=("codex",)).can_apply)
        self.assertNotIn("codex", native_agents.verified_hosts(self.state, context=self.context))
        plan = self.preview(hosts=("claude",))
        root = self.paths.claude / "agents"
        root.mkdir(parents=True)
        (root / "unrelated.md").write_text('---\nname: user-role\n---\nuser\n')
        with self.assertRaises(ValueError):
            native_agents.apply_global(plan)
        self.assertFalse((root / "xy-backend.md").exists())

    def test_second_state_cannot_take_same_native_root(self):
        self.install(hosts=("codex",))
        state = self.case / "second-state"
        core = runtime_store.import_core(self.source, state)
        context = NativeContext(state, self.paths)
        plan = native_agents.preview_global(state, core.binding(), context=context, hosts=("codex",))
        self.assertFalse(plan.can_apply)
        self.assertFalse((state / "native-agents").exists())

    def test_concurrent_plans_publish_once_and_recovery_is_idempotent(self):
        plans = (self.preview(hosts=("codex",)), self.preview(hosts=("codex",)))
        def run(plan):
            try:
                return native_agents.apply_global(plan)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(executor.map(run, plans))
        self.assertEqual(sum(row is not None and row["applied"] for row in receipts), 1)
        receipt = next(row for row in receipts if row is not None)
        reference = receipt["recovery_ref"]
        result = native_agents.compensate_global(reference, context=self.context)
        self.assertEqual(result["status"], "compensated", result)
        self.assertEqual(native_agents.recover_global(reference, context=self.context)["status"], "compensated")
        self.assertFalse((self.paths.codex / "agents/xy-backend.toml").exists())

    def test_recovery_preserves_unknown_replacement_and_reports_exact_identity(self):
        receipt = self.install(hosts=("claude",))
        target = self.paths.claude / "agents/xy-backend.md"
        body = target.read_bytes()
        target.unlink()
        target.write_bytes(body)
        issues = native_agents.verify_global(receipt["recovery_ref"], context=self.context)
        self.assertTrue(issues)
        result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(target.read_bytes(), body)

    def _assert_compensation_window_keeps_replacement(self, *, before_file):
        receipt = self.install(hosts=("codex",))
        if before_file:
            receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                        preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
        target = self.paths.codex / "agents/xy-backend.toml"
        body = target.read_bytes()
        expected_inode = target.stat().st_ino
        original_rename = native_agents.os.rename
        replaced = []
        def replace_at_final_isolation(source, destination, **kwargs):
            # 钩住真实rename系统调用边界；既不替换补偿业务函数，也不根据新
            # 实现的辅助方法判断时机。旧二元CAS与完整Node方案都必须经历此窗口。
            if source == target.name and not replaced:
                replacement = target.with_name(".user-compensation-replacement")
                with replacement.open("xb") as stream:
                    stream.write(body)
                replacement.chmod(target.stat().st_mode & 0o7777)
                foreign = replacement.stat()
                self.assertNotEqual(foreign.st_ino, expected_inode)
                os.replace(replacement, target)
                replaced.append((foreign.st_dev, foreign.st_ino))
            return original_rename(source, destination, **kwargs)
        with patch.object(native_agents.os, "rename", side_effect=replace_at_final_isolation):
            result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        print("COMPENSATION_REPLACEMENT_WINDOW", "file" if before_file else "missing", result["status"], replaced)
        self.assertTrue(replaced)
        self.assertTrue(target.exists(), "补偿不得删除窗口中出现的未知同内容inode")
        self.assertEqual((target.stat().st_dev, target.stat().st_ino), replaced[0])
        self.assertEqual(target.read_bytes(), body)
        self.assertEqual(result["status"], "conflict")
        journal_path = self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")
        journal = json.loads(journal_path.read_bytes())
        self.assertTrue(any(row.get("path") == "agents/xy-backend.toml" for row in journal["conflicts"]))
        self.assertIn(str(replaced[0][1]), json.dumps(journal))
        self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "conflict")
        self.assertEqual((target.stat().st_dev, target.stat().st_ino), replaced[0])
        self.assertEqual(target.read_bytes(), body)

    def test_compensation_file_restore_rejects_same_content_inode_at_final_isolation(self):
        self._assert_compensation_window_keeps_replacement(before_file=True)

    def test_compensation_delete_rejects_same_content_inode_at_final_isolation(self):
        self._assert_compensation_window_keeps_replacement(before_file=False)

    def test_compensation_resumes_forward_interruption_before_publication(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        original_body = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        original_link = native_agents.os.link
        interrupted = []
        def stop_before_link(source, destination, **kwargs):
            if str(source).startswith(".awf-native-stage-") and destination == target.name and not interrupted:
                interrupted.append(True)
                raise OSError("fixture native publication interrupted")
            return original_link(source, destination, **kwargs)
        with patch.object(native_agents.os, "link", side_effect=stop_before_link):
            with self.assertRaisesRegex(OSError, "publication interrupted"):
                native_agents.apply_global(plan)
        self.assertTrue(interrupted)
        self.assertFalse(target.exists())
        result = native_agents.recover_global(plan.recovery_ref, context=self.context)
        self.assertEqual(result["status"], "compensated", result)
        self.assertEqual(target.read_bytes(), original_body)
        self.assertEqual(native_agents.verified_hosts(self.state, context=self.context), ("codex",))
        self.assertEqual(native_agents.recover_global(plan.recovery_ref, context=self.context)["status"], "compensated")

    def test_compensation_owner_reconciliation_rejects_same_content_inode(self):
        self.install(hosts=("codex",))
        receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                  preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
        owner = self.paths.codex / native.OWNER
        original_rename = native_agents.os.rename
        visits, replacement = [], []
        def replace_at_reconciliation(source, destination, **kwargs):
            if source == native.OWNER:
                visits.append(True)
                if len(visits) == 2:
                    body = owner.read_bytes()
                    alternate = owner.with_name(".user-owner-replacement")
                    with alternate.open("xb") as stream:
                        stream.write(body)
                    alternate.chmod(owner.stat().st_mode & 0o7777)
                    info = alternate.stat()
                    os.replace(alternate, owner)
                    replacement.append((info.st_dev, info.st_ino, body))
            return original_rename(source, destination, **kwargs)
        with patch.object(native_agents.os, "rename", side_effect=replace_at_reconciliation):
            result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(len(replacement), 1)
        self.assertEqual(result["status"], "conflict", result)
        self.assertEqual((owner.stat().st_dev, owner.stat().st_ino), replacement[0][:2])
        self.assertEqual(owner.read_bytes(), replacement[0][2])
        self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "conflict")
        self.assertEqual((owner.stat().st_dev, owner.stat().st_ino), replacement[0][:2])

    def test_compensation_preserves_forward_retained_fd_edits(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        descriptor = os.open(target, os.O_WRONLY | os.O_APPEND)
        try:
            receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                      preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
            published_body = target.read_bytes()
            os.write(descriptor, b"\n# late original fd save\n")
            result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        finally:
            os.close(descriptor)
        self.assertEqual(result["status"], "conflict", result)
        self.assertEqual(target.read_bytes(), published_body)
        journal = json.loads((self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")).read_bytes())
        row = next(row for row in journal["writes"] if row["path"] == "agents/xy-backend.toml")
        retained = self.paths.codex / row["retained"][0]["path"]
        self.assertIn(b"late original fd save", retained.read_bytes())
        self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "conflict")
        self.assertIn(b"late original fd save", retained.read_bytes())

    def test_compensation_resumes_persisted_exact_result_after_interruption(self):
        for before_file in (False, True):
            with self.subTest(before_file=before_file):
                self.paths = HostPaths.for_home(self.case / ("file-home" if before_file else "missing-home"), environment={})
                self.context = NativeContext(self.state, self.paths)
                receipt = self.install(hosts=("codex",))
                if before_file:
                    receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                              preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
                target = self.paths.codex / "agents/xy-backend.toml"
                original_save = native_agents._save
                interrupted = []
                def stop_after_exact_result(state, journal):
                    result = original_save(state, journal)
                    if not interrupted and any(step["path"] == "agents/xy-backend.toml" and step["result"] is not None
                                               for step in journal.get("compensations", [])):
                        interrupted.append(True)
                        raise KeyboardInterrupt("fixture compensation after exact result")
                    return result
                with patch.object(native_agents, "_save", side_effect=stop_after_exact_result):
                    with self.assertRaisesRegex(KeyboardInterrupt, "after exact result"):
                        native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
                self.assertTrue(interrupted)
                journal = json.loads((self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")).read_bytes())
                saved = next(step for step in reversed(journal["compensations"]) if step["path"] == "agents/xy-backend.toml")
                self.assertEqual(native.read_node(self.paths.codex, "agents/xy-backend.toml"), Node.from_value(saved["result"]))
                result = native_agents.recover_global(receipt["recovery_ref"], context=self.context)
                self.assertEqual(result["status"], "compensated", result)
                self.assertEqual(target.exists(), before_file)
                before_noop = native.read_node(self.paths.codex, "agents/xy-backend.toml")
                self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")
                self.assertEqual(native.read_node(self.paths.codex, "agents/xy-backend.toml"), before_noop)

    def test_compensation_log_rejects_foreign_paths_and_incomplete_node_identity(self):
        self.install(hosts=("codex",))
        receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                  preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
        self.assertEqual(native_agents.compensate_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")
        journal_path = self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")
        original = json.loads(journal_path.read_bytes())
        outside = self.case / "outside.txt"
        outside.write_bytes(b"preserve foreign bytes")
        before = native.read_node(self.paths.codex, "agents/xy-backend.toml")
        for invalid in ("path", "identity"):
            with self.subTest(invalid=invalid):
                journal = json.loads(json.dumps(original))
                step = next(step for step in journal["compensations"] if step["stage"] is not None)
                if invalid == "path":
                    step["stage"] = "../../outside.txt"
                else:
                    step["expected"]["identity"] = []
                journal_path.write_bytes(json_bytes(journal))
                with self.assertRaises(ValueError):
                    native_agents.recover_global(receipt["recovery_ref"], context=self.context)
                self.assertEqual(outside.read_bytes(), b"preserve foreign bytes")
                self.assertEqual(native.read_node(self.paths.codex, "agents/xy-backend.toml"), before)

    def test_update_compensation_restores_prior_ownership_and_preserves_applied_evidence(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        before = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        receipt = native_agents.apply_global(plan)
        self.assertNotEqual(target.read_bytes(), before)
        result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(result["status"], "compensated", result)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(native_agents.verified_hosts(self.state, context=self.context), ("codex",))
        self.assertEqual(native_agents.compensate_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")

    def test_noop_ref_witness_verifies_without_journal_and_rejects_replacement(self):
        self.install(hosts=("codex",))
        plan = self.preview(hosts=("codex",))
        receipt = native_agents.apply_global(plan)
        self.assertEqual(receipt["status"], "noop")
        reference = receipt["recovery_ref"]
        journal = self.state / "native-agents/transactions" / (plan.transaction_id + ".json")
        self.assertFalse(journal.exists())
        self.assertEqual(native_agents.verify_global(reference, context=self.context), [])
        target = self.paths.codex / "agents/xy-backend.toml"
        body = target.read_bytes()
        target.unlink()
        target.write_bytes(body)
        self.assertTrue(native_agents.verify_global(reference, context=self.context))
        self.assertEqual(native_agents.recover_global(reference, context=self.context)["status"], "conflict")
        self.assertEqual(target.read_bytes(), body)
        self.assertFalse(journal.exists())

    def test_publish_rejects_same_content_inode_replacement_after_stage(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        body = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        original = native_agents._save
        replaced = False
        def replace_after_stage(state, journal):
            nonlocal replaced
            original(state, journal)
            if not replaced and any(row["path"] == "agents/xy-backend.toml" and row.get("staged") is not None
                                    and row["published"] is None for row in journal["writes"]):
                replaced = True
                target.unlink()
                target.write_bytes(body)
        with patch.object(native_agents, "_save", side_effect=replace_after_stage):
            with self.assertRaisesRegex(ValueError, "最终隔离"):
                native_agents.apply_global(plan)
        self.assertTrue(replaced)
        self.assertEqual(target.read_bytes(), body)
        self.assertEqual(native_agents.compensate_global(plan.recovery_ref, context=self.context)["status"], "conflict")
        self.assertEqual(target.read_bytes(), body)

    def test_publish_rejects_same_content_replacement_between_guard_and_capture(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        body = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        original = native_agents._publish
        replaced = False
        def replace_before_capture(state, journal, root, relative, after, *, expected):
            nonlocal replaced
            if relative == "agents/xy-backend.toml" and not replaced:
                replaced = True
                target.unlink()
                target.write_bytes(body)
            return original(state, journal, root, relative, after, expected=expected)
        with patch.object(native_agents, "_publish", side_effect=replace_before_capture):
            with self.assertRaisesRegex(ValueError, "固定预览"):
                native_agents.apply_global(plan)
        self.assertTrue(replaced)
        self.assertEqual(target.read_bytes(), body)

    def test_declared_alias_with_yaml_comment_is_a_conflict(self):
        root = self.paths.claude / "agents"
        root.mkdir(parents=True)
        (root / "alias.md").write_text('---\nname: "xy-backend" # user comment\n---\nuser\n')
        self.assertFalse(self.preview(hosts=("claude",)).can_apply)

    def test_publish_rejects_native_root_replacement_after_guard(self):
        self.install(hosts=("codex",))
        root = self.paths.codex
        target = root / "agents/xy-backend.toml"
        body = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        original = native_agents._publish
        replaced = False
        def replace_root_before_capture(state, journal, native_root, relative, after, *, expected):
            nonlocal replaced
            if relative == "agents/xy-backend.toml" and not replaced:
                replaced = True
                moved = self.home / "moved-codex"
                root.rename(moved)
                root.mkdir()
                for child in moved.iterdir():
                    child.rename(root / child.name)
            return original(state, journal, native_root, relative, after, expected=expected)
        with patch.object(native_agents, "_publish", side_effect=replace_root_before_capture):
            with self.assertRaisesRegex(ValueError, "物理根"):
                native_agents.apply_global(plan)
        self.assertTrue(replaced)
        self.assertEqual(target.read_bytes(), body)

    def test_recovery_rejects_replaced_native_root_even_if_role_inodes_are_same(self):
        receipt = self.install(hosts=("codex",))
        original = self.paths.codex
        moved = self.home / "old-codex"
        original.rename(moved)
        original.mkdir()
        for child in moved.iterdir():
            child.rename(original / child.name)
        target = original / "agents/xy-backend.toml"
        before = target.read_bytes()
        result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(result["status"], "conflict")
        self.assertTrue(any(row.get("type") == "native_root_conflict" for row in result["conflicts"]))
        self.assertEqual(target.read_bytes(), before)

    def test_launcher_init_parser_distinguishes_command_from_option_value(self):
        from lib.central.runtime_project import launcher_source
        namespace = {"__name__": "launcher_contract"}
        exec(compile(launcher_source(), "<central-launcher>", "exec"), namespace)
        classify = namespace["helper_creates_task"]
        self.assertTrue(classify(["helper", "lib/task_graph_cli.py", "--input", "graph.json", "init"]))
        self.assertFalse(classify(["helper", "lib/task_graph_cli.py", "validate", "--task-id", "init"]))

    def test_native_descriptor_real_validators_accept_bootstrap_and_reject_permission_expansion(self):
        from lib.hosts.validate_claude_artifacts import validate_agent as validate_claude
        from lib.validate_antigravity_artifacts import parse_agent_frontmatter, validate_agent as validate_agy
        self.install()
        claude = self.paths.claude / "agents/xy-qa.md"
        errors = []
        validate_claude(claude, "xy-qa", self.case, errors)
        self.assertEqual(errors, [])
        agy = self.paths.antigravity / "agents/xy-qa.md"
        body = agy.read_text()
        fields, _ = parse_agent_frontmatter(body, agy, errors)
        self.assertNotIn("skills", fields)
        validate_agy(agy, body, "xy-qa", set(), errors)
        self.assertEqual(errors, [])
        unsafe = body.replace("  - view_file", "  - write_to_file", 1)
        with self.assertRaises(ValueError):
            native.validate_descriptor(unsafe.encode(), "antigravity", "xy-qa")
        with self.assertRaises(ValueError):
            native.validate_descriptor(body.replace("model: inherit", "model:").encode(), "antigravity", "xy-qa")
        errors = []
        parse_agent_frontmatter(unsafe, agy, errors)
        self.assertTrue(errors)
        # 旧/普通静态合同继续要求skills，不能靠移除marker将规则整体放宽。
        errors = []
        parse_agent_frontmatter(body.replace("agent-workflow-central-project", "user-agent"), agy, errors)
        self.assertTrue(any("skills" in item for item in errors))
        codex = (self.paths.codex / "agents/xy-qa.toml").read_bytes()
        self.assertNotIn(b"sandbox_mode", codex)
        self.assertIn(b"Parent native permissions still apply", codex)

    def test_project_sparse_only_after_verified_global_and_single_field_is_complete(self):
        project = self.case / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.1.0"\n')
        resources = Resources(self.core.root, json_bytes(self.core.binding()), self.core.label, self.core)
        desired, profile = prepare(resources, project, Node(), ("codex",), owned_links=set())
        self.assertIn(".codex/agents/xy-backend.toml", desired)
        self.install()
        desired, profile = prepare(resources, project, Node(), ("codex",), owned_links=set(), native_context=self.context)
        self.assertFalse(any(purpose == "role" for _, purpose in desired.values()))
        body = desired[CONFIG][0].payload
        body = role_models.update(body.decode(), {"codex": {"xy-backend": {"model": "project-model"}}}).encode()
        desired, _ = prepare(resources, project, Node("file", body, 0o644), ("codex",), owned_links=set(),
                             native_context=self.context, preferences={"codex": {"xy-backend": {"effort": "high"}}})
        node = desired[".codex/agents/xy-backend.toml"][0]
        native.validate_descriptor(node.payload, "codex", "xy-backend")
        self.assertIn(b'model = "project-model"', node.payload)
        self.assertIn(b'model_reasoning_effort = "high"', node.payload)
        desired, _ = prepare(resources, project, Node("file", body, 0o644), ("codex",), owned_links=set(),
                             native_context=self.context, preferences={"codex": {"xy-backend": {"effort": "max"}}})
        self.assertIn(b'model_reasoning_effort = "max"', desired[".codex/agents/xy-backend.toml"][0].payload)


class NativeProfileConsumerTest(unittest.TestCase):
    def test_sparse_profile_helper_uses_state_authority_over_ambient_host_paths(self):
        """真实薄桥读取显式state的稀疏角色，不能随进程HOME重选宿主根。"""
        from manager import central_runtime, runtime_service, runtime_policy
        from lib.central.runtime_project import LAUNCHER, PYTHON_ENTRY, project_key, identity
        pack = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="native-profile-", dir=os.environ.get("AWF_TEST_SCRATCH")) as raw:
            root = Path(raw).resolve()
            state = root / "custom-state"
            # 此消费者必须运行完整固定core中的真实profile依赖；不复制/补丁
            # 核心文件，也不以工作树的import替代真实薄入口执行。
            core = runtime_store.import_core(pack, state)
            context = NativeContext(state, HostPaths.for_home(root / "installed-host-home", environment={}))
            central_runtime.apply(central_runtime.preview(state, binding=core.binding(), native_context=context))
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.1.0"\n')
            runtime_service.apply(runtime_service.preview(state, project, "enable", binding=core.binding(),
                                                         hosts=("codex",), native_context=context))
            self.assertFalse((project / ".codex/agents/xy-qa.toml").exists())
            decoy = root / "ambient-home"
            decoy.mkdir()
            environment = dict(os.environ)
            for key in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                        "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"):
                environment.pop(key, None)
            environment.update({"HOME": str(decoy), "CODEX_HOME": str(decoy / "wrong-codex"),
                                "CLAUDE_CONFIG_DIR": str(decoy / "wrong-claude"),
                                "AGENT_WORKFLOW_STATE_DIR": str(state), "AGENT_WORKFLOW_PYTHON": sys.executable})
            def invoke(mode):
                command = ["bash", str(project / PYTHON_ENTRY), "-B", "-X", "utf8", str(project / LAUNCHER),
                           "--binding", json.dumps(core.binding()), "helper", "lib/project/project_profile_cli.py"]
                command.extend(("check-roles", "codex", ".agent-workflow", ".") if mode == "check-roles"
                               else (mode, ".agent-workflow", "."))
                result = subprocess.run(command, cwd=project, env=environment, capture_output=True, text=True, timeout=40)
                print("ISOLATED_PROFILE_HELPER", mode, "exit=" + str(result.returncode))
                print(result.stdout, end="")
                print(result.stderr, end="")
                return result
            paths = (runtime_policy.CURRENT, runtime_policy.ACTIVATION, "bindings/" + project_key(project) + ".json")
            state_before = tuple(native.read_node(state, path) for path in paths)
            role = context.host_paths.codex / "agents/xy-qa.toml"
            owner_before = native.read_node(context.host_paths.codex, native.OWNER)
            role_before = native.read_node(context.host_paths.codex, "agents/xy-qa.toml")
            # 普通读取允许系统更新atime；复用生产节点identity核对inode、mode、
            # size、mtime、ctime，既不误报读取，也不豁免实际文件/目录修改。
            project_before = {path.relative_to(project).as_posix(): identity(path.lstat()) for path in project.rglob("*")}
            result = invoke("check-roles")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("native ownership", result.stdout)
            self.assertEqual(tuple(native.read_node(state, path) for path in paths), state_before)
            self.assertEqual(native.read_node(context.host_paths.codex, native.OWNER), owner_before)
            self.assertEqual(native.read_node(context.host_paths.codex, "agents/xy-qa.toml"), role_before)
            self.assertEqual({path.relative_to(project).as_posix(): identity(path.lstat()) for path in project.rglob("*")}, project_before)
            self.assertEqual(list(decoy.iterdir()), [])
            # 全局手删仍是冲突，不退回ambient HOME补资源；普通旧pin画像读取
            # 保持只读可用，不把check-roles的健康要求扩散到roles读取路径。
            role.unlink()
            result = invoke("check-roles")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            result = invoke("roles")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("xy-qa", result.stdout.splitlines())
            self.assertFalse(role.exists())
            self.assertEqual(list(decoy.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
