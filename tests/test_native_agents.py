"""只使用请求 scratch 验证全局归属、原生路径、固定预览与稀疏完整描述符。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
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


if __name__ == "__main__":
    unittest.main()
