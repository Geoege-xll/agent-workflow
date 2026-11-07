"""中央协调的真实文件系统测试，原生宿主边界由独立native测试覆盖。

这里用显式native替身控制失败点；核心导入、项目产物、固定桥消费、全局记录
及条件补偿均运行生产代码，不把替身成功当作宿主真实模型执行证据。
"""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from lib import runtime_bridge, runtime_pins, runtime_store as store
from lib.central.runtime_project import Tree, json_bytes
from lib.hosts.native_context import HostPaths, NativeContext
import manager
from manager import central_runtime as central, project_service, runtime_policy as policy, runtime_service as projects
from manager.runtime_state import ActivationError, read_state, write_control
from tests.test_central_project import make_alternate_source

PACK = Path(__file__).resolve().parents[1]


class RuntimeFixture:
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="central-212-")
        cls.workspace = Path(cls.temporary.name).resolve()
        cls.state = cls.workspace / "state"
        cls.core = store.import_core(PACK, cls.state)
        cls.source = cls.workspace / "alternate-source"
        make_alternate_source(cls.source)
        # 最小版本也声明当前child持锁能力，完整角色/Skill/桥继续来自真实源码。
        (cls.source / "lib/task_graph_init.py").write_text("CENTRAL_ADMISSION_PROTOCOL = 1\n")
        cls.alternate = store.import_core(cls.source, cls.state)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        for name in ("bindings", "transactions", "central", "policies", "preferences", "native-agents", "locks"):
            shutil.rmtree(self.state / name, ignore_errors=True)
        (self.state / "projects.json").unlink(missing_ok=True)
        self.project = self.workspace / ("project-" + uuid.uuid4().hex[:10])
        self.project.mkdir()
        self.context = NativeContext.for_state(self.state, host_paths=HostPaths.for_home(self.workspace / ("test-home-" + self.project.name)))
        self.set_current(self.core.binding())

    def set_current(self, binding):
        with policy.coordination(self.state), Tree(self.state) as tree:
            write_control(tree, policy.CURRENT, json_bytes({"schema_version": 1, "runtime_binding": binding,
                          "previous_binding": None, "generation": uuid.uuid4().hex}),
                          expected=read_state(self.state, policy.CURRENT))

    def enable(self, project=None, core=None):
        project = project or self.project
        return projects.apply(projects.preview(self.state, project, "enable", binding=(core or self.core).binding()))

    def register(self, *paths):
        self.state.mkdir(exist_ok=True)
        target = self.state / "projects.json"
        target.write_bytes(json_bytes({"schema": 1, "registered": [str(path) for path in paths], "hidden": []}))
        target.chmod(0o600)


class CentralRuntimeTest(RuntimeFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.native_events = []
        def native_preview(state, binding, *, context):
            identifier = uuid.uuid4().hex
            return SimpleNamespace(summary={"can_apply": True, "conflicts": []}, hosts=(),
                                   recovery_ref={"schema_version": 1, "state": str(state), "transaction_id": identifier, "targets": []})
        def native_compensate(reference, **kwargs):
            self.native_events.append(reference["transaction_id"])
            return {"status": "compensated", "conflicts": []}
        self.native = SimpleNamespace(preview_global=native_preview,
            apply_global=lambda plan: {"transaction_id": plan.recovery_ref["transaction_id"]},
            compensate_global=native_compensate,
            verify_global=lambda reference, **kwargs: [], verified_hosts=lambda state, **kwargs: ())
        self.enterContext(patch.dict(sys.modules, {"manager.native_agents": self.native}))
        self.enterContext(patch.object(manager, "native_agents", self.native, create=True))

    def plan(self, binding=None):
        return central.preview(self.state, binding=binding or self.alternate.binding(), native_context=self.context)

    def test_mixed_follow_pinned_disabled_and_follow_reenable(self):
        self.enable()
        pinned = self.workspace / ("pinned-" + uuid.uuid4().hex[:8]); pinned.mkdir()
        disabled = self.workspace / ("disabled-" + uuid.uuid4().hex[:8]); disabled.mkdir()
        self.enable(pinned); self.enable(disabled)
        self.register(self.project, pinned, disabled)
        project_service.apply_project(project_service.preview_project(self.state, pinned, "use", content_id=self.core.content_id))
        projects.apply(projects.preview(self.state, disabled, "disable"))
        plan = self.plan()
        self.assertEqual(1, sum(row["affected"] for row in plan.summary["projects"]))
        result = central.apply(plan)
        self.assertEqual(self.alternate.binding(), result["runtime_binding"])
        self.assertEqual(self.alternate.binding(), projects.status(self.state, self.project)["runtime_binding"])
        self.assertEqual(self.core.binding(), projects.status(self.state, pinned)["runtime_binding"])
        self.assertFalse(projects.status(self.state, disabled)["declared_enabled"])
        project_service.apply_project(project_service.preview_project(self.state, pinned, "follow"))
        self.assertEqual("follow", projects.status(self.state, pinned)["policy"])
        self.assertEqual(self.alternate.binding(), projects.status(self.state, pinned)["runtime_binding"])
        project_service.apply_project(project_service.preview_project(self.state, disabled, "enable"))
        self.assertEqual(self.alternate.binding(), projects.status(self.state, disabled)["runtime_binding"])

    def test_preview_cancel_and_registry_drift_are_zero_project_writes(self):
        self.enable(); self.register(self.project)
        machine = projects.read_binding_record(self.state, self.project)[0]
        plan = self.plan()
        self.assertEqual(machine, projects.read_binding_record(self.state, self.project)[0])
        self.assertEqual("missing", read_state(self.state, policy.ACTIVATION).kind)
        cancelled = Event(); cancelled.set()
        with self.assertRaisesRegex(ValueError, "取消"):
            central.apply(plan, cancel=cancelled)
        self.assertEqual("missing", read_state(self.state, policy.ACTIVATION).kind)
        self.register()
        with self.assertRaisesRegex(ValueError, "登记表"):
            central.apply(plan)
        self.assertEqual(machine, projects.read_binding_record(self.state, self.project)[0])

    def test_second_project_failure_restores_first_by_original_inode(self):
        self.enable()
        second = self.workspace / ("second-" + uuid.uuid4().hex[:8]); second.mkdir(); self.enable(second)
        self.register(self.project, second)
        plan = self.plan()
        first = next(capture for capture in plan.captures if capture.runtime_plan)
        role = first.project / ".codex/agents/xy-qa.toml"
        original = role.read_bytes(), role.stat().st_ino
        before = projects.read_binding_record(self.state, first.project)[0]
        applied = projects.apply
        calls = []
        def fail_second(project_plan, **kwargs):
            calls.append(project_plan.project)
            if len(calls) == 2:
                raise OSError("fixture second project failure")
            return applied(project_plan, **kwargs)
        with patch.object(projects, "apply", side_effect=fail_second), self.assertRaisesRegex(OSError, "second"):
            central.apply(plan)
        self.assertEqual(original, (role.read_bytes(), role.stat().st_ino))
        self.assertEqual(before.payload, projects.read_binding_record(self.state, first.project)[0].payload)
        self.assertEqual(self.core.binding(), central.status(self.state)["runtime_binding"])
        self.assertIsNone(policy.pending(self.state))
        self.assertTrue(self.native_events)

    def test_published_current_interruption_blocks_then_completes(self):
        self.enable(); self.register(self.project)
        plan = self.plan()
        save = central._save
        def interrupted(state, journal, expected):
            if journal["phase"] == "applied":
                raise OSError("fixture after current publication")
            return save(state, journal, expected)
        with patch.object(central, "_save", side_effect=interrupted), self.assertRaisesRegex(ValueError, "已发布"):
            central.apply(plan)
        with self.assertRaisesRegex(ValueError, "尚未结算"):
            central.new_task_gate(self.state, self.project)
        result = central.recover(central.preview_recovery(self.state, native_context=self.context))
        self.assertTrue(result["recovered"])
        self.assertEqual(self.alternate.binding(), central.new_task_gate(self.state, self.project))

    def test_old_pin_read_and_helper_survive_current_corruption_but_new_init_rejects(self):
        self.enable(); self.register(self.project)
        central.apply(self.plan())
        # 历史任务仅依赖曾用binding与其清单，current损坏不应连带破坏必要读取。
        (self.state / policy.CURRENT).write_bytes(b"invalid-current\n")
        self.assertEqual(store.read_core_source(self.core, "product/WORKFLOW.md"),
                         runtime_bridge.read_resource(self.state, self.project, "product/WORKFLOW.md", binding=self.core.binding()))
        invocation = runtime_bridge.python_helper(self.state, self.project, "lib/probe.py", binding=self.alternate.binding())
        self.assertEqual(0, runtime_bridge.run_helper(invocation))
        with self.assertRaises(ValueError):
            runtime_bridge.resolve_runtime(self.state, self.project, binding=self.core.binding(), new_task=True)

    def test_explicit_old_pin_and_init_final_recheck_cannot_bypass_policy(self):
        self.enable(); self.register(self.project)
        selected = central.new_task_gate(self.state, self.project)
        central.apply(self.plan())
        with self.assertRaisesRegex(ValueError, "有效策略"):
            central.new_task_gate(self.state, self.project, selected)
        with patch.dict(os.environ, {"AGENT_WORKFLOW_STATE_DIR": str(self.state)}):
            with self.assertRaisesRegex(ValueError, "有效策略"):
                with runtime_pins.new_task_publication(self.project, selected):
                    self.fail("最终发布不应进入")
            import subprocess
            command = "from pathlib import Path; import sys; from lib.central.role_preferences import coordination\ntry:\n with coordination(Path(sys.argv[1])): raise SystemExit(9)\nexcept ValueError:\n print('publication coordination blocked competing process'); raise SystemExit(3)"
            with runtime_pins.new_task_publication(self.project, self.alternate.binding()):
                competing = subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8", "-c", command, str(self.state)],
                                           cwd=PACK, capture_output=True, text=True, timeout=10)
            self.assertEqual(3, competing.returncode, competing.stdout + competing.stderr)
            self.assertIn("blocked competing process", competing.stdout)

    def test_missing_current_blocks_gate_and_real_launcher_but_old_read_survives(self):
        import subprocess
        self.enable()
        (self.state / policy.CURRENT).unlink()
        checked = projects.status(self.state, self.project)
        self.assertFalse(checked["new_task_allowed"])
        self.assertIn("current_missing", {row["code"] for row in checked["issues"]})
        with self.assertRaisesRegex(ValueError, "不能创建新任务"):
            central.new_task_gate(self.state, self.project)
        env = {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(self.state)}
        result = subprocess.run(["bash", str(self.project / ".agent-workflow/lib/python_runtime.sh"), "-B", "-X", "utf8",
                                 str(self.project / ".agent-workflow/runtime.py"), "check"], env=env, cwd=self.project,
                                capture_output=True, text=True, timeout=40)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(store.read_core_source(self.core, "product/WORKFLOW.md"),
                         runtime_bridge.read_resource(self.state, self.project, "product/WORKFLOW.md", binding=self.core.binding()))

    def test_helper_admission_uses_command_not_option_value(self):
        for args in (("init",), ("--input", "graph.json", "init"), ("--input=graph.json", "init"), ("--in", "graph.json", "init"), ("--", "init")):
            with self.subTest(args=args):
                self.assertTrue(runtime_bridge.helper_creates_task("lib/task_graph_cli.py", args))
        for args in (("validate", "--task-id", "init"), ("--input=init", "validate"), ("task", "--request-id", "init")):
            with self.subTest(args=args):
                self.assertFalse(runtime_bridge.helper_creates_task("lib/task_graph_cli.py", args))
        for args in (("--unknown", "init"), ("--r", "x", "init"), ("--input",)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                runtime_bridge.helper_creates_task("lib/task_graph_cli.py", args)

    def test_capability_rejects_dynamic_duplicate_and_unknown_declarations(self):
        for body, expected in ((b"# historical init without publication protocol\n", 0),
                               (b"CENTRAL_ADMISSION_PROTOCOL = 1\n", 1)):
            with patch.object(store, "read_core_source", return_value=body):
                self.assertEqual(expected, runtime_bridge._admission_protocol(self.core))
        for body in (b"CENTRAL_ADMISSION_PROTOCOL = 2\n", b"CENTRAL_ADMISSION_PROTOCOL = True\n",
                     b"CENTRAL_ADMISSION_PROTOCOL = 1\nCENTRAL_ADMISSION_PROTOCOL += 1\n",
                     b"if True:\n CENTRAL_ADMISSION_PROTOCOL = 1\n",
                     b"CENTRAL_ADMISSION_PROTOCOL = int('1')\n"):
            with self.subTest(body=body), patch.object(store, "read_core_source", return_value=body), self.assertRaises(ValueError):
                runtime_bridge._admission_protocol(self.core)

    def test_legacy_init_parent_holds_lock_and_keeps_selected_pin(self):
        # 机械旧init夹具只证明协议0的parent锁与pin透传；不冒称完整历史CLI的
        # 所有业务行为。真实旧pin普通resource/helper另由既有项目回归覆盖。
        initializer = self.source / "lib/task_graph_init.py"
        original = initializer.read_bytes()
        helper = self.source / "lib/task_graph_cli.py"
        helper.write_text("""import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.central.role_preferences import coordination
blocked = False
try:
    with coordination(Path(os.environ['AGENT_WORKFLOW_STATE_DIR'])):
        pass
except ValueError:
    blocked = True
target = Path(sys.argv[sys.argv.index('--output') + 1])
target.write_text(json.dumps({'blocked': blocked, 'binding': json.loads(os.environ['AGENT_WORKFLOW_RUNTIME_BINDING'])}))
""")
        initializer.write_bytes(b"# Historical mechanical initialization, no child publication lock.\n")
        try:
            legacy = store.import_core(self.source, self.state)
        finally:
            initializer.write_bytes(original)
            helper.unlink()
        project_service.apply_project(project_service.preview_project(self.state, self.project, "enable", content_id=legacy.content_id))
        output = self.project / "legacy-init.json"
        invocation = runtime_bridge.python_helper(self.state, self.project, "lib/task_graph_cli.py", ("--output", str(output), "init"), binding=legacy.binding())
        self.assertEqual(0, invocation.admission_protocol)
        self.assertEqual(0, runtime_bridge.run_helper(invocation))
        value = json.loads(output.read_bytes())
        self.assertTrue(value["blocked"])
        self.assertEqual(legacy.binding(), value["binding"])

    def test_settled_history_of_removed_project_does_not_block_other_projects(self):
        self.enable()
        other = self.workspace / ("removed-" + uuid.uuid4().hex[:8]); other.mkdir(); self.enable(other)
        self.register(self.project, other)
        central.apply(self.plan())
        # 保留历史raw journal；模拟已完成业务项目的物理根后来移走，不认领新根。
        other.rename(other.with_name(other.name + "-moved"))
        self.assertIsNone(policy.pending(self.state))
        self.assertEqual(self.alternate.binding(), central.new_task_gate(self.state, self.project))

    def test_history_missing_modified_and_current_corruption_have_distinct_permissions(self):
        self.enable()
        projects.apply(projects.preview(self.state, self.project, "use", binding=self.alternate.binding()))
        # 此例直接项目换版后同步current，避免policy drift掩盖历史分层断言。
        self.set_current(self.alternate.binding())
        _, record = projects.read_binding_record(self.state, self.project)
        retained = next(row for row in record["retained_nodes"] if row["kind"] == "file")
        target = self.project / retained["path"]
        original = target.read_bytes()
        target.write_bytes(original + b"later-save")
        status = projects.status(self.state, self.project)
        self.assertTrue(status["new_task_allowed"])
        self.assertFalse(status["management_write_allowed"])
        self.assertIn("history_modified", {row["code"] for row in status["issues"]})
        target.unlink()
        status = projects.status(self.state, self.project)
        self.assertTrue(status["declared_enabled"])
        self.assertTrue(status["new_task_allowed"])
        self.assertTrue(status["management_write_allowed"])
        self.assertFalse(status["history_recoverable"])
        role = self.project / ".codex/agents/xy-qa.toml"
        role.write_bytes(role.read_bytes() + b"unknown edit\n")
        status = projects.status(self.state, self.project)
        self.assertFalse(status["new_task_allowed"])
        self.assertIn("current_resource_invalid", {row["code"] for row in status["issues"]})


class CentralNativeIntegrationTest(RuntimeFixture, unittest.TestCase):
    """真实宿主根仅位于本请求scratch，核验native receipt返回值与父事务边界。"""

    def pair(self):
        self.enable()
        second = self.workspace / ("second-" + uuid.uuid4().hex[:8]); second.mkdir(); self.enable(second)
        self.register(self.project, second)
        return central.preview(self.state, binding=self.alternate.binding(), native_context=self.context)

    def test_native_conflict_receipt_keeps_global_pending_gate(self):
        from manager import native_agents
        plan = self.pair()
        applied, calls = projects.apply, []
        def fail_second(runtime_plan, **kwargs):
            calls.append(runtime_plan.project)
            if len(calls) == 2:
                target = self.context.host_paths.codex / "agents/xy-qa.toml"
                target.write_bytes(target.read_bytes() + b"# later native edit\n")
                raise OSError("fixture second project failure after native edit")
            return applied(runtime_plan, **kwargs)
        with patch.object(projects, "apply", side_effect=fail_second), self.assertRaisesRegex(ValueError, "冲突"):
            central.apply(plan)
        pending = policy.pending(self.state)
        self.assertEqual("conflict", pending["phase"])
        self.assertIn("native_compensation_conflict", {row["code"] for row in pending["conflicts"]})
        # 真实B服务返回conflict receipt且不抛错，父事务必须解释此业务终态。
        receipt = native_agents.compensate_global(pending["native_ref"], context=self.context)
        self.assertEqual("conflict", receipt["status"])
        self.assertTrue(receipt["conflicts"])
        with self.assertRaisesRegex(ValueError, "尚未结算"):
            central.new_task_gate(self.state, self.project)

    def test_later_project_cannot_hide_edits_to_earlier_applied_project(self):
        plan = self.pair()
        first = next(capture.project for capture in plan.captures if capture.runtime_plan)
        applied, calls = projects.apply, []
        def edit_earlier(runtime_plan, **kwargs):
            result = applied(runtime_plan, **kwargs)
            calls.append(runtime_plan.project)
            if len(calls) == 2:
                locator = first / ".agent-workflow/runtime.json"
                locator.write_bytes(locator.read_bytes() + b" \n")
            return result
        with patch.object(projects, "apply", side_effect=edit_earlier), self.assertRaisesRegex(ValueError, "冲突"):
            central.apply(plan)
        self.assertEqual(self.core.binding(), central.status(self.state)["runtime_binding"])
        self.assertEqual("conflict", policy.pending(self.state)["phase"])
        self.assertTrue((first / ".agent-workflow/runtime.json").read_bytes().endswith(b" \n"))
