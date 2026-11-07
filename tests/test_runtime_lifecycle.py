"""生命周期的真实inode、原始journal保全、中断恢复及引用保活测试。"""

import json
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch
import uuid

from lib import runtime_store as store
from lib.central.runtime_project import json_bytes
from manager import runtime_lifecycle as lifecycle, runtime_service as projects
from manager.runtime_state import read_state
from tests.test_central_runtime import RuntimeFixture


class RuntimeLifecycleTest(RuntimeFixture, unittest.TestCase):
    def cycle(self):
        self.enable()
        projects.apply(projects.preview(self.state, self.project, "use", binding=self.alternate.binding()))
        projects.apply(projects.preview(self.state, self.project, "use", binding=self.core.binding()))
        self.set_current(self.core.binding())

    def test_prune_old_batches_keeps_latest_raw_journal_and_current_resources(self):
        self.cycle()
        journal = projects._journal(self.state, self.project)[0]
        _, value = projects._journal(self.state, self.project)
        latest = {row["backup"] for row in value["changes"]}
        plan = lifecycle.preview(self.state)
        self.assertTrue(plan.backups)
        self.assertFalse(latest & {row["record"]["path"] for row in plan.backups})
        self.assertEqual("missing", read_state(self.state, lifecycle.RELATIVE).kind)
        result = lifecycle.apply(plan)
        self.assertGreater(result["backups_removed"], 0)
        self.assertEqual(journal, projects._journal(self.state, self.project)[0])
        status = projects.status(self.state, self.project)
        self.assertTrue(status["new_task_allowed"], status)
        self.assertTrue(status["history_recoverable"], status["issues"])
        self.assertEqual([], list(lifecycle.preview(self.state).backups))

    def test_unknown_edited_old_inode_is_preserved_and_cancel_writes_nothing(self):
        self.cycle()
        plan = lifecycle.preview(self.state)
        cancelled = Event(); cancelled.set()
        with self.assertRaisesRegex(ValueError, "取消"):
            lifecycle.apply(plan, cancel=cancelled)
        self.assertEqual("missing", read_state(self.state, lifecycle.RELATIVE).kind)
        selected = plan.backups[0]
        path = Path(selected["project"]) / selected["record"]["path"]
        path.write_bytes(path.read_bytes() + b"external save")
        with self.assertRaisesRegex(ValueError, "冲突"):
            lifecycle.apply(plan)
        self.assertTrue(path.exists())
        self.assertTrue(path.read_bytes().endswith(b"external save"))

    def unused_core(self):
        path = self.source / "product/WORKFLOW.md"
        original = path.read_bytes()
        path.write_bytes(original + uuid.uuid4().hex.encode())
        try:
            return store.import_core(self.source, self.state)
        finally:
            path.write_bytes(original)

    def test_gc_keeps_all_used_bindings_task_pins_and_unknown_references(self):
        self.cycle()
        unused = self.unused_core()
        pin = self.workspace / ("pin-" + uuid.uuid4().hex + ".json")
        pin.write_bytes(json_bytes({"schema_version": 2, "runtime_binding": unused.binding()}))
        protected = lifecycle.preview(self.state, task_records=(pin,))
        self.assertNotIn(unused.content_id, {row["content_id"] for row in protected.cores})
        pin.write_bytes(b'{"runtime_binding":{"content_id":"unknown"}}')
        unknown = lifecycle.preview(self.state, task_records=(pin,))
        self.assertFalse(unknown.cores)
        plan = lifecycle.preview(self.state)
        self.assertEqual({unused.content_id}, {row["content_id"] for row in plan.cores})
        lifecycle.apply(plan)
        self.assertFalse((self.state / "runtimes" / unused.content_id).exists())
        self.assertTrue(store.load_core(self.core.binding(), self.state))
        self.assertTrue(store.load_core(self.alternate.binding(), self.state))

    def test_explicit_archive_inventory_drift_and_interruption_resume(self):
        root = self.workspace / ".sync-backups" / ("old-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        (root / "old.txt").write_bytes(b"unique historical bytes")
        newer = root.with_name("latest-" + uuid.uuid4().hex); newer.mkdir(); (newer / "new.txt").write_bytes(b"keep latest")
        inventory = lifecycle.preview(self.state, backup_roots=(root,), include_cores=False)
        self.assertFalse(inventory.archives)
        self.assertIn("unknown_ownership", {row["code"] for row in inventory.retained})
        plan = lifecycle.preview(self.state, approved_backup_roots=(root,), include_cores=False)
        (root / "later.txt").write_bytes(b"later external content")
        with self.assertRaisesRegex(ValueError, "冲突"):
            lifecycle.apply(plan)
        self.assertTrue((root / "old.txt").exists())
        self.assertTrue((root / "later.txt").exists())
        # 失败计划必须先结算；此例用另一精确归档验证真实删除中断，不把未知
        # 新文件移走或认领为原授权快照。旧冲突资料仍留在本例独占state中。
        (self.state / lifecycle.RELATIVE).unlink()
        other = root.with_name("approved-" + uuid.uuid4().hex); other.mkdir(); (other / "one.txt").write_bytes(b"one")
        plan = lifecycle.preview(self.state, approved_backup_roots=(other,), include_cores=False)
        delete = lifecycle._delete_snapshot
        def interrupted(path, snapshot):
            (path / "one.txt").unlink()
            raise KeyboardInterrupt("fixture abrupt interruption")
        with patch.object(lifecycle, "_delete_snapshot", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            lifecycle.apply(plan)
        self.assertEqual("prepared", json.loads((self.state / lifecycle.RELATIVE).read_bytes())["phase"])
        with self.assertRaisesRegex(ValueError, "生命周期事务尚未结算"):
            projects.preview(self.state, self.project, "enable", binding=self.core.binding())
        lifecycle.recover(self.state)
        self.assertFalse(other.exists())
        self.assertTrue(newer.exists())
        self.assertTrue(root.exists())

    def test_reference_change_after_preview_rejects_before_deletion(self):
        self.cycle()
        plan = lifecycle.preview(self.state)
        binding = projects.read_binding_record(self.state, self.project)[0]
        path = self.state / projects._state_relative(self.project, "bindings")
        path.write_bytes(binding.payload + b"\n")
        with self.assertRaisesRegex(ValueError, "引用记录"):
            lifecycle.apply(plan)
        self.assertEqual("missing", read_state(self.state, lifecycle.RELATIVE).kind)
        self.assertTrue(all((Path(row["project"]) / row["record"]["path"]).exists() for row in plan.backups))

    def test_failed_later_transaction_keeps_last_complete_applied_backup_batch(self):
        self.cycle()
        _, applied = projects._journal(self.state, self.project)
        last_complete = {row["backup"] for row in applied["changes"]}
        original = projects._publish
        calls = []
        def fail_after_one(tree, row, core, save):
            result = original(tree, row, core, save)
            calls.append(row["path"])
            if len(calls) == 1:
                raise OSError("fixture later project transaction failed")
            return result
        plan = projects.preview(self.state, self.project, "use", binding=self.alternate.binding())
        with patch.object(projects, "_publish", side_effect=fail_after_one), self.assertRaises(OSError):
            projects.apply(plan)
        self.assertEqual("rolled_back", projects._journal(self.state, self.project)[1]["phase"])
        cleanup = lifecycle.preview(self.state)
        self.assertTrue(last_complete)
        self.assertFalse(last_complete & {row["record"]["path"] for row in cleanup.backups})
        self.assertTrue(all((self.project / path).exists() for path in last_complete))
