"""中央协调的真实文件系统测试，原生宿主边界由独立native测试覆盖。

这里用显式native替身控制失败点；核心导入、项目产物、固定桥消费、全局记录
及条件补偿均运行生产代码，不把替身成功当作宿主真实模型执行证据。
"""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
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


class CurrentRecordCodecTest(unittest.TestCase):
    def test_native_roots_are_required_closed_canonical_and_readonly(self):
        binding = {"protocol_version": 1, "content_id": "a" * 64, "manifest_sha256": "a" * 64}
        value = {"schema_version": 1, "runtime_binding": binding, "previous_binding": None,
                 "generation": "b" * 32, "native_roots": []}
        self.assertEqual(value, policy.validate_current(value))
        roots = [{"host": host, "native_root": "/uncreated-contract-root/" + host}
                 for host in ("codex", "claude", "antigravity")]
        with patch.object(Path, "stat", side_effect=AssertionError("current codec must not inspect host roots")):
            self.assertEqual(roots, policy.validate_current({**value, "native_roots": roots})["native_roots"])
        copied = policy.validate_native_roots(roots)
        copied[0]["native_root"] = "/another-root"
        self.assertEqual("/uncreated-contract-root/codex", roots[0]["native_root"])
        missing = dict(value); missing.pop("native_roots")
        for candidate in (missing, {**value, "native_ref": {}}, {**value, "native_roots": None},
                          {**value, "native_roots": {}}, {**value, "native_roots": [{"host": "codex"}]},
                          {**value, "native_roots": [{"host": "unknown", "native_root": "/unknown"}]},
                          {**value, "native_roots": [roots[0], {"host": "codex", "native_root": "/other"}]},
                          {**value, "native_roots": [roots[0], {"host": "claude", "native_root": roots[0]["native_root"]}]},
                          {**value, "native_roots": [{**roots[0], "witness": {}}]}):
            with self.subTest(candidate=candidate), self.assertRaises(ActivationError):
                policy.validate_current(candidate)
        for root in ("relative/root", "/absolute/../root", "/absolute/./root", "/absolute//root", "//absolute/root", "/absolute/root\n", None):
            with self.subTest(root=root), self.assertRaises(ActivationError):
                policy.validate_current({**value, "native_roots": [{"host": "codex", "native_root": root}]})


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
                          "previous_binding": None, "generation": uuid.uuid4().hex, "native_roots": []}),
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

    def test_controller_protocol_is_static_closed_and_independent_of_helper(self):
        self.assertIs(type(runtime_bridge.CENTRAL_CONTROL_PROTOCOL), int)
        self.assertEqual(1, runtime_bridge.CENTRAL_CONTROL_PROTOCOL)
        for body, expected in ((b"# historical bridge without control capability\n", 0),
                               (b"CENTRAL_CONTROL_PROTOCOL = 0\nCENTRAL_ADMISSION_PROTOCOL = 1\n", 0),
                               (b"CENTRAL_CONTROL_PROTOCOL = 1\nCENTRAL_ADMISSION_PROTOCOL = 0\n", 1),
                               (b"raise AssertionError('candidate code must not execute')\nCENTRAL_CONTROL_PROTOCOL: int = 1\n", 1)):
            with self.subTest(body=body), patch.object(store, "read_core_source", return_value=body) as read:
                self.assertEqual(expected, runtime_bridge.controller_protocol(self.core))
                read.assert_called_once_with(self.core, "lib/runtime_bridge.py")
        for body in (b"CENTRAL_CONTROL_PROTOCOL = True\n", b"CENTRAL_CONTROL_PROTOCOL = 2\n",
                     b"CENTRAL_CONTROL_PROTOCOL = -1\n", b"CENTRAL_CONTROL_PROTOCOL = int('1')\n",
                     b"CENTRAL_CONTROL_PROTOCOL = 1\nCENTRAL_CONTROL_PROTOCOL = 1\n",
                     b"CENTRAL_CONTROL_PROTOCOL = 1\nCENTRAL_CONTROL_PROTOCOL += 0\n",
                     b"if True:\n CENTRAL_CONTROL_PROTOCOL = 1\n",
                     b"CENTRAL_CONTROL_PROTOCOL = 1\ndel CENTRAL_CONTROL_PROTOCOL\n",
                     b"CENTRAL_CONTROL_PROTOCOL = 1\ndef CENTRAL_CONTROL_PROTOCOL(): pass\n",
                     b"CENTRAL_CONTROL_PROTOCOL = 1\nclass CENTRAL_CONTROL_PROTOCOL: pass\n",
                     b"CENTRAL_CONTROL_PROTOCOL = 1\nimport sys as CENTRAL_CONTROL_PROTOCOL\n",
                     b"from sys import version as CENTRAL_CONTROL_PROTOCOL\n",
                     b"CENTRAL_CONTROL_PROTOCOL = 1\ntry: pass\nexcept Exception as CENTRAL_CONTROL_PROTOCOL: pass\n",
                     b"CENTRAL_CONTROL_PROTOCOL = 1\nmatch 1:\n case CENTRAL_CONTROL_PROTOCOL: pass\n",
                     b"CENTRAL_CONTROL_PROTOCOL = (\n"):
            with self.subTest(body=body), patch.object(store, "read_core_source", return_value=body), self.assertRaises(ValueError):
                runtime_bridge.controller_protocol(self.core)

    def test_unqualified_controller_is_rejected_before_native_preview_but_pin_remains_readable(self):
        # 从现有有限来源精确去掉控制声明，再通过正式import建立无资格core。
        # 该夹具验证缺声明的准入合同，不冒称真实历史安装；实际2.1.1复现证据
        # 由独立QA保留，CI/解包源码不依赖历史Git对象，也不因此skip此负控。
        source = self.source / "lib/runtime_bridge.py"
        original = source.read_bytes()
        declaration = b"\nCENTRAL_CONTROL_PROTOCOL = 1\n"
        self.assertEqual(1, original.count(declaration))
        old_body = original.replace(declaration, b"\n# Fixture controller without a control declaration.\n", 1)
        source.write_bytes(old_body)
        try:
            legacy = store.import_core(self.source, self.state)
        finally:
            source.write_bytes(original)
        self.assertEqual(old_body, store.read_core_source(legacy, "lib/runtime_bridge.py"))
        self.assertEqual(0, runtime_bridge.controller_protocol(legacy))
        self.enable(); self.register(self.project)
        current_node, current = policy.current_snapshot(self.state)
        with Tree(self.state) as tree:
            write_control(tree, policy.CURRENT, json_bytes({**current, "previous_binding": legacy.binding()}), expected=current_node)
        before = (read_state(self.state, policy.CURRENT), read_state(self.state, policy.ACTIVATION),
                  projects.read_binding_record(self.state, self.project)[0], projects._journal(self.state, self.project)[0])
        with patch.object(self.native, "preview_global", side_effect=AssertionError("unsupported controller reached native preview")) as native:
            for action, binding in (("activate", legacy.binding()), ("rollback", None)):
                with self.subTest(action=action), self.assertRaisesRegex(ValueError, "CENTRAL_CONTROL_PROTOCOL=1"):
                    central.preview(self.state, action, binding=binding, native_context=self.context)
            native.assert_not_called()
        self.assertEqual(before, (read_state(self.state, policy.CURRENT), read_state(self.state, policy.ACTIVATION),
                                 projects.read_binding_record(self.state, self.project)[0], projects._journal(self.state, self.project)[0]))
        # 资格只约束current控制器。由合格控制器管理的显式无控制资格项目pin
        # 仍可读取/新建；强写它为current只阻准入，保留资源和修复许可。
        project_service.apply_project(project_service.preview_project(self.state, self.project, "use", content_id=legacy.content_id))
        self.assertEqual(legacy.binding(), central.new_task_gate(self.state, self.project))
        self.set_current(legacy.binding())
        checked = projects.status(self.state, self.project)
        self.assertTrue(checked["resources_healthy"], checked["issues"])
        self.assertTrue(checked["management_write_allowed"], checked["issues"])
        self.assertFalse(checked["new_task_allowed"])
        self.assertIn("current_control_invalid", {row["code"] for row in checked["issues"]})
        self.assertNotIn("policy_drift", {row["code"] for row in checked["issues"]})
        controller = central.status(self.state)
        self.assertFalse(controller["new_task_allowed"])
        self.assertTrue(controller["management_write_allowed"])
        self.assertIn("current_control_invalid", {row["code"] for row in controller["issues"]})
        with self.assertRaisesRegex(ValueError, "不能创建新任务"):
            central.new_task_gate(self.state, self.project)
        self.assertEqual(store.read_core_source(legacy, "product/WORKFLOW.md"),
                         runtime_bridge.read_resource(self.state, self.project, "product/WORKFLOW.md", binding=legacy.binding()))
        # 旧current无资格不能把修复操作也堵住：真实激活新控制器之后，旧pin的
        # 有效策略重新获得准入，且没有偷偷把它换成新core任务语义。
        central.apply(central.preview(self.state, binding=self.core.binding(), native_context=self.context))
        self.assertEqual(legacy.binding(), central.new_task_gate(self.state, self.project))

    def test_unknown_controller_metadata_rejects_before_native_preview(self):
        source = self.source / "lib/runtime_bridge.py"
        original = source.read_bytes()
        # 真正导入未知协议core；getter应静态拒绝，不能通过执行这个候选模块
        # 的副作用探测能力，也不能等到native预检/持久事务开始后才拒绝。
        source.write_bytes(b"CENTRAL_CONTROL_PROTOCOL = 2\nraise AssertionError('candidate must not execute')\n")
        try:
            unknown = store.import_core(self.source, self.state)
        finally:
            source.write_bytes(original)
        before = read_state(self.state, policy.CURRENT), read_state(self.state, policy.ACTIVATION)
        with patch.object(self.native, "preview_global", side_effect=AssertionError("unknown controller reached native preview")) as native, \
                self.assertRaisesRegex(ValueError, "中央控制协议"):
            central.preview(self.state, binding=unknown.binding(), native_context=self.context)
        native.assert_not_called()
        self.assertEqual(before, (read_state(self.state, policy.CURRENT), read_state(self.state, policy.ACTIVATION)))

    def test_supported_controllers_activate_and_rollback(self):
        self.enable(); self.register(self.project)
        self.assertEqual(1, runtime_bridge.controller_protocol(self.alternate))
        central.apply(self.plan())
        result = central.apply(central.preview(self.state, "rollback", native_context=self.context))
        self.assertEqual(self.core.binding(), result["runtime_binding"])
        self.assertTrue(result["new_task_allowed"])
        self.assertEqual(self.core.binding(), central.new_task_gate(self.state, self.project))

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

    def test_first_enable_requires_explicit_install_and_activation_without_writes(self):
        empty_state = self.workspace / ("empty-state-" + uuid.uuid4().hex)
        before = sorted(self.project.iterdir())
        for action, enable in (("enable", False), ("add", True)):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "runtime install.*runtime activate"):
                project_service.preview_project(empty_state, self.project, action, enable=enable)
            self.assertFalse(empty_state.exists())
            self.assertEqual(before, sorted(self.project.iterdir()))
        # 用户明确选择来源仍是受支持的独立合同；仅预览，不隐式创建state或导入。
        explicit = project_service.preview_project(empty_state, self.project, "enable", source_root=self.source)
        self.assertEqual(self.source, explicit.runtime_plan.source_root)
        self.assertFalse(empty_state.exists())
        self.assertEqual(before, sorted(self.project.iterdir()))

    def test_summary_freezes_dispositions_and_effective_bindings(self):
        self.enable()
        pinned = self.workspace / ("pinned-summary-" + uuid.uuid4().hex[:8]); pinned.mkdir(); self.enable(pinned)
        disabled = self.workspace / ("disabled-summary-" + uuid.uuid4().hex[:8]); disabled.mkdir(); self.enable(disabled)
        unbound = self.workspace / ("unbound-summary-" + uuid.uuid4().hex[:8]); unbound.mkdir()
        project_service.apply_project(project_service.preview_project(self.state, pinned, "use", content_id=self.core.content_id))
        projects.apply(projects.preview(self.state, disabled, "disable"))
        self.register(self.project, pinned, disabled, unbound)
        plan = self.plan()
        frozen = plan.summary
        rows = {row["project"]: row for row in frozen["projects"]}
        expected = ((self.project, "apply", True, self.core.binding(), self.alternate.binding()),
                    (pinned, "skipped_pinned", True, self.core.binding(), self.core.binding()),
                    (disabled, "on_enable", False, self.core.binding(), self.alternate.binding()),
                    (unbound, "not_enabled", False, None, self.alternate.binding()))
        for project, disposition, enabled, applied, effective in expected:
            with self.subTest(project=project):
                row = rows[str(project)]
                self.assertEqual(disposition, row["disposition"])
                self.assertEqual(enabled, row["declared_enabled"])
                self.assertEqual(applied, row["applied_binding"])
                self.assertEqual(effective, row["effective_after"])
                self.assertTrue(row["reason"])
        self.assertEqual("missing", read_state(self.state, policy.ACTIVATION).kind)
        # 模拟确认前策略/current漂移；预览展示仍只反映本提案捕获的前像，真正
        # apply的原有CAS会独立拒绝漂移。不得因重绘预览而混入另一时刻的数据。
        path = self.state / policy.policy_relative(pinned)
        path.write_bytes(json_bytes(policy.policy_value(pinned, "pinned", self.alternate.binding())))
        self.set_current(self.alternate.binding())
        with patch.object(projects, "status", side_effect=AssertionError("summary must not read live status")), \
                patch.object(policy, "snapshot", side_effect=AssertionError("summary must not read live policy")):
            self.assertEqual(frozen, plan.summary)
        rows[str(self.project)]["effective_after"]["content_id"] = "0" * 64
        self.assertEqual(self.alternate.binding(), plan.binding)
        self.assertEqual(self.alternate.binding(), next(row for row in plan.summary["projects"] if row["project"] == str(self.project))["effective_after"])

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

    def test_project_pending_is_a_recovery_issue_even_when_current_resources_match(self):
        self.enable()
        _, journal = projects._journal(self.state, self.project)
        journal["phase"] = "prepared"
        target = self.state / projects._state_relative(self.project, "transactions")
        target.write_bytes(json_bytes(journal))
        checked = projects.status(self.state, self.project)
        self.assertTrue(checked["resources_healthy"])
        self.assertFalse(checked["new_task_allowed"])
        self.assertFalse(checked["management_write_allowed"])
        self.assertIn("project_transaction_pending", {row["code"] for row in checked["issues"]})

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

    def test_current_publishes_only_verified_exact_native_roots(self):
        from manager import native_agents
        plan = central.preview(self.state, binding=self.core.binding(), native_context=self.context)
        central.apply(plan)
        _, current = policy.current_snapshot(self.state)
        self.assertEqual({"schema_version", "runtime_binding", "previous_binding", "generation", "native_roots"}, set(current))
        self.assertEqual(plan.native_plan.recovery_ref["targets"], current["native_roots"])
        self.assertTrue(current["native_roots"])
        self.assertTrue(all(set(row) == {"host", "native_root"} for row in current["native_roots"]))
        self.assertEqual([], native_agents.verify_global(plan.native_plan.recovery_ref, context=self.context))

    def interrupt_after_current_publication(self):
        """真实发布项目和原生产物，只在current成功后切断父事务终态保存。"""
        self.enable()
        self.register(self.project)
        plan = central.preview(self.state, binding=self.core.binding(), native_context=self.context)
        save = central._save
        def interrupted(state, journal, expected):
            if journal["phase"] == "applied":
                raise OSError("fixture interrupted after real current publication")
            return save(state, journal, expected)
        with patch.object(central, "_save", side_effect=interrupted), self.assertRaisesRegex(ValueError, "已发布"):
            central.apply(plan)
        self.assertEqual("publishing", policy.pending(self.state)["phase"])
        self.assertEqual(plan.native_plan.recovery_ref["targets"], policy.current_snapshot(self.state)[1]["native_roots"])
        return plan

    def assert_published_root_drift_rejected(self, roots):
        self.interrupt_after_current_publication()
        node, current = policy.current_snapshot(self.state)
        altered = {**current, "native_roots": roots}
        policy.validate_current(altered)  # 负控是合法格式的授权漂移，不能只靠坏schema拒绝。
        with Tree(self.state) as tree:
            write_control(tree, policy.CURRENT, json_bytes(altered), expected=node)
        external = policy.current_snapshot(self.state)[0]
        pending = read_state(self.state, policy.ACTIVATION)
        with self.assertRaisesRegex(ValueError, "已发布 current.*不一致"):
            central.recover(central.preview_recovery(self.state, native_context=self.context))
        self.assertEqual(external, policy.current_snapshot(self.state)[0])
        self.assertEqual(pending, read_state(self.state, policy.ACTIVATION))
        self.assertIsNotNone(policy.pending(self.state))
        with self.assertRaisesRegex(ValueError, "尚未结算"):
            central.new_task_gate(self.state, self.project)

    def test_published_recovery_rejects_empty_native_root_authorization(self):
        self.assert_published_root_drift_rejected([])

    def test_published_recovery_rejects_changed_native_root_authorization(self):
        other = [{"host": host, "native_root": str(self.workspace / ("external-root-" + host))}
                 for host in ("codex", "claude", "antigravity")]
        self.assert_published_root_drift_rejected(other)

    def test_published_recovery_rejects_current_inode_drift_during_verification(self):
        self.interrupt_after_current_publication()
        original = policy.current_snapshot(self.state)[0]
        pending = read_state(self.state, policy.ACTIVATION)
        verify = central._verify_applied
        external = []
        def save_current_after_real_verification(state, journal, context):
            verify(state, journal, context)
            # 模拟编辑器在资源核验窗口内同字节重存；字段比较看不到该变化，
            # 必须保留并比较current完整Node，不能把新的inode认作旧核验结果。
            with Tree(state) as tree:
                write_control(tree, policy.CURRENT, original.payload, expected=original)
            saved = policy.current_snapshot(state)[0]
            self.assertTrue(saved.same_content(original))
            self.assertNotEqual(original.identity[:2], saved.identity[:2])
            external.append(saved)
        with patch.object(central, "_verify_applied", side_effect=save_current_after_real_verification), \
                self.assertRaisesRegex(ValueError, "current.*变化"):
            central.recover(central.preview_recovery(self.state, native_context=self.context))
        self.assertEqual(external[0], policy.current_snapshot(self.state)[0])
        self.assertEqual(pending, read_state(self.state, policy.ACTIVATION))
        with self.assertRaisesRegex(ValueError, "尚未结算"):
            central.new_task_gate(self.state, self.project)
        # 新一轮明确恢复会捕获这个仍与本批字段一致的新Node；稳定核验后才可
        # 结算，且成功也不能为“修复”而重写编辑器留下的current。
        result = central.recover(central.preview_recovery(self.state, native_context=self.context))
        self.assertTrue(result["recovered"])
        self.assertEqual(external[0], policy.current_snapshot(self.state)[0])
        self.assertIsNone(policy.pending(self.state))
        self.assertEqual(self.core.binding(), central.new_task_gate(self.state, self.project))

    def sparse_pair(self):
        """先完成真实中央激活，让两个项目原本已经依赖明确全局根。

        这与完整local项目失败不同：后续noop/换版失败时，原current的根授权
        必须继续有效，不能因为最后一条activation变成compensated就撤销准入。
        """
        self.enable()
        second = self.workspace / ("sparse-second-" + uuid.uuid4().hex[:8]); second.mkdir(); self.enable(second)
        self.register(self.project, second)
        central.apply(central.preview(self.state, binding=self.core.binding(), native_context=self.context))
        for project in (self.project, second):
            for relative in (".codex/agents/xy-qa.toml", ".claude/agents/xy-qa.md", ".agents/agents/xy-qa.md"):
                self.assertFalse((project / relative).exists())
            self.assertTrue(projects.status(self.state, project)["resources_healthy"])
            self.assertEqual(self.core.binding(), central.new_task_gate(self.state, project))
        # 两个core的全局bootstrap相同，项目locator/Skill目标却会换版；确保既
        # 真实使用native noop，又有需要按原inode补偿的项目资源，而非仅改日志。
        plan = central.preview(self.state, binding=self.alternate.binding(), native_context=self.context)
        self.assertEqual([], plan.native_plan.summary["changes"])
        self.assertIn("witness", plan.native_plan.recovery_ref)
        self.assertTrue(all(capture.runtime_plan.changes for capture in plan.captures))
        return plan

    def assert_sparse_recovered(self, plan):
        self.assertIsNone(policy.pending(self.state))
        self.assertEqual(plan.current_before, policy.current_snapshot(self.state)[0])
        for capture in plan.captures:
            self.assertEqual(capture.binding_before.payload, projects.read_binding_record(self.state, capture.project)[0].payload)
            self.assertFalse((capture.project / ".codex/agents/xy-qa.toml").exists())
            checked = projects.status(self.state, capture.project)
            self.assertTrue(checked["resources_healthy"], checked["issues"])
            self.assertEqual(self.core.binding(), central.new_task_gate(self.state, capture.project))
        # 从项目真实thin入口走新任务init，覆盖controller选择、固定pin及最终发布
        # 锁；配置检查/原生文件存在本身不能替代可实际恢复的新任务许可。
        from tests.test_task_graph_init import BUILTIN_ENGINEERING, decisions
        value = decisions()
        value["standards"].update(required_engineering_rule_ids=["eng-common-005"],
                                   leaves=[{"path": BUILTIN_ENGINEERING, "domain": "engineering", "rule_ids": ["eng-common-005"]}])
        value["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
        output = self.project / "recovered-sparse-task.json"
        environment = dict(os.environ)
        for field in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT", "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"):
            environment.pop(field, None)
        environment["AGENT_WORKFLOW_STATE_DIR"] = str(self.state)
        initialized = subprocess.run(["bash", str(self.project / ".agent-workflow/lib/python_runtime.sh"), "-B", "-X", "utf8",
                                      str(self.project / ".agent-workflow/runtime.py"), "helper", "lib/task_graph_cli.py", "init",
                                      "--root", str(self.project), "--output", str(output)], input=json.dumps(value),
                                     env=environment, cwd=self.project, capture_output=True, text=True, timeout=40)
        self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
        self.assertEqual(self.core.binding(), json.loads(output.read_bytes())["runtime_binding"])

    def test_existing_sparse_projects_keep_admission_after_failed_activation(self):
        plan = self.sparse_pair()
        applied, calls = projects.apply, []
        def fail_second(runtime_plan, **kwargs):
            calls.append(runtime_plan.project)
            if len(calls) == 2:
                raise OSError("fixture existing sparse second project failure")
            return applied(runtime_plan, **kwargs)
        with patch.object(projects, "apply", side_effect=fail_second), self.assertRaisesRegex(OSError, "second project"):
            central.apply(plan)
        self.assert_sparse_recovered(plan)

    def test_existing_sparse_projects_keep_admission_after_interrupted_recovery(self):
        plan = self.sparse_pair()
        applied, calls = projects.apply, []
        def fail_second(runtime_plan, **kwargs):
            calls.append(runtime_plan.project)
            if len(calls) == 2:
                raise OSError("fixture existing sparse failure before recovery")
            return applied(runtime_plan, **kwargs)
        with patch.object(projects, "apply", side_effect=fail_second), \
                patch.object(central, "_compensate", side_effect=KeyboardInterrupt("fixture existing sparse recovery interrupted")), \
                self.assertRaises(KeyboardInterrupt):
            central.apply(plan)
        with self.assertRaisesRegex(ValueError, "尚未结算"):
            central.new_task_gate(self.state, self.project)
        result = central.recover(central.preview_recovery(self.state, native_context=self.context))
        self.assertTrue(result["compensated"])
        self.assert_sparse_recovered(plan)

    def test_sparse_projects_reject_empty_or_unknown_current_root_authorization(self):
        self.sparse_pair()
        node, current = policy.current_snapshot(self.state)
        unknown = copy.deepcopy(current["native_roots"])
        unknown[0]["native_root"] = str(self.workspace / "unowned-native-root")
        for roots in ([], unknown):
            with self.subTest(roots=roots):
                altered = {**current, "native_roots": roots}
                policy.validate_current(altered)
                with Tree(self.state) as tree:
                    write_control(tree, policy.CURRENT, json_bytes(altered), expected=node)
                node = read_state(self.state, policy.CURRENT)
                self.assertFalse(projects.status(self.state, self.project)["resources_healthy"])
                with self.assertRaisesRegex(ValueError, "不能创建新任务"):
                    central.new_task_gate(self.state, self.project)

    def noop_pair(self):
        """以完整核心和真实原生归属构造noop，不伪造原生服务返回的收据。

        项目先保留完整local投影，预先安装的七角色全局产物来自同一完整核心。
        后续中央激活不需改原生产物，但仍会撤下项目local角色；第二项目失败
        因而必须真实补偿第一项目，不能仅用空项目计划掩盖跨资源结算。
        """
        from manager import native_agents
        self.enable()
        second = self.workspace / ("noop-second-" + uuid.uuid4().hex[:8]); second.mkdir(); self.enable(second)
        self.register(self.project, second)
        installed = native_agents.apply_global(native_agents.preview_global(self.state, self.core.binding(), context=self.context))
        self.assertEqual("applied", installed["status"])
        plan = central.preview(self.state, binding=self.core.binding(), native_context=self.context)
        self.assertEqual([], plan.native_plan.summary["changes"])
        self.assertIn("witness", plan.native_plan.recovery_ref)
        self.assertTrue(all(capture.runtime_plan.changes for capture in plan.captures))
        receipt = native_agents.compensate_global(plan.native_plan.recovery_ref, context=self.context)
        self.assertEqual("noop", receipt["status"])
        self.assertEqual([], receipt["conflicts"])
        return plan

    def test_native_noop_after_project_failure_settles_compensation(self):
        from manager import native_agents
        plan = self.noop_pair()
        before = {capture.project: capture.binding_before.payload for capture in plan.captures}
        applied, calls = projects.apply, []
        def fail_second(runtime_plan, **kwargs):
            calls.append(runtime_plan.project)
            if len(calls) == 2:
                raise OSError("fixture second project failed after native noop")
            return applied(runtime_plan, **kwargs)
        with patch.object(projects, "apply", side_effect=fail_second), self.assertRaisesRegex(OSError, "second project"):
            central.apply(plan)
        journal = json.loads(read_state(self.state, policy.ACTIVATION).payload)
        self.assertEqual("noop", journal["native_receipt"]["status"])
        self.assertEqual("compensated", journal["phase"])
        self.assertEqual([], journal["conflicts"])
        self.assertIsNone(policy.pending(self.state))
        self.assertEqual(plan.current_before, policy.current_snapshot(self.state)[0])
        self.assertTrue(central.status(self.state)["management_write_allowed"])
        for project, payload in before.items():
            self.assertEqual(payload, projects.read_binding_record(self.state, project)[0].payload)
            self.assertTrue(projects.status(self.state, project)["resources_healthy"])
        self.assertEqual([], native_agents.verify_global(journal["native_ref"], context=self.context))

    def test_native_noop_pending_recovery_settles_after_project_failure(self):
        from manager import native_agents
        plan = self.noop_pair()
        before = {capture.project: capture.binding_before.payload for capture in plan.captures}
        applied, calls = projects.apply, []
        def fail_second(runtime_plan, **kwargs):
            calls.append(runtime_plan.project)
            if len(calls) == 2:
                raise OSError("fixture second project failed before recovery")
            return applied(runtime_plan, **kwargs)
        # 只在父事务进入补偿前模拟中断；原生apply/noop、首项目apply以及后面的
        # recover均运行真实服务，让持久native_ref与witness接受相同恢复合同。
        with patch.object(projects, "apply", side_effect=fail_second), \
                patch.object(central, "_compensate", side_effect=KeyboardInterrupt("fixture interrupted before compensation")), \
                self.assertRaises(KeyboardInterrupt):
            central.apply(plan)
        pending = policy.pending(self.state)
        self.assertEqual("noop", pending["native_receipt"]["status"])
        with self.assertRaisesRegex(ValueError, "尚未结算"):
            central.new_task_gate(self.state, self.project)
        result = central.recover(central.preview_recovery(self.state, native_context=self.context))
        self.assertTrue(result["compensated"])
        self.assertIsNone(policy.pending(self.state))
        self.assertEqual(plan.current_before, policy.current_snapshot(self.state)[0])
        self.assertTrue(central.status(self.state)["management_write_allowed"])
        for project, payload in before.items():
            self.assertEqual(payload, projects.read_binding_record(self.state, project)[0].payload)
            self.assertTrue(projects.status(self.state, project)["resources_healthy"])
        self.assertEqual([], native_agents.verify_global(pending["native_ref"], context=self.context))

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

    def test_sparse_delete_rechecks_global_before_receipt_and_commit_restores_local(self):
        from lib import role_models
        from manager import native_agents
        from manager.service import Change, commit
        self.enable()
        native_agents.apply_global(native_agents.preview_global(self.state, self.core.binding(), context=self.context))
        relative = ".codex/agents/xy-qa.toml"
        target = self.project / relative
        config = self.project / ".agent-workflow/project.yaml"
        selected = {"codex": {"xy-qa": {"model": "fixture-local-model", "effort": "high"}}}
        original_config = config.read_bytes()
        after_config = role_models.update(original_config.decode(), selected).encode()
        commit(self.state, self.project,
               [Change(relative, target.read_bytes(), role_models.patch_artifact(target.read_bytes(), "codex", selected["codex"]["xy-qa"]), 0o644),
                Change(".agent-workflow/project.yaml", original_config, after_config, 0o644)], native_context=self.context)
        before_role, before_config = target.read_bytes(), config.read_bytes()
        before_binding = projects.read_binding_record(self.state, self.project)[0].payload
        changes = [Change(relative, before_role, None, 0o644),
                   Change(".agent-workflow/project.yaml", before_config, role_models.update(before_config.decode(), {}).encode(), 0o644)]
        publish = projects.NativeEditReceipt.publish
        def remove_global_before_receipt(receipt):
            (self.context.host_paths.codex / "agents/xy-qa.toml").unlink()
            return publish(receipt)
        with patch.object(projects.NativeEditReceipt, "publish", new=remove_global_before_receipt), self.assertRaisesRegex(ValueError, "全局归属"):
            commit(self.state, self.project, changes, native_context=self.context)
        self.assertEqual(before_role, target.read_bytes())
        self.assertEqual(before_config, config.read_bytes())
        self.assertEqual(before_binding, projects.read_binding_record(self.state, self.project)[0].payload)

    def test_installed_sparse_project_rejects_new_tasks_after_global_role_removed(self):
        plan = self.pair()
        central.apply(plan)
        self.assertFalse((self.project / ".codex/agents/xy-qa.toml").exists())
        self.assertTrue(projects.status(self.state, self.project)["new_task_allowed"])
        (self.context.host_paths.codex / "agents/xy-qa.toml").unlink()
        checked = projects.status(self.state, self.project)
        self.assertFalse(checked["resources_healthy"])
        self.assertFalse(checked["new_task_allowed"])
        self.assertFalse(checked["management_write_allowed"])
        with self.assertRaisesRegex(ValueError, "不能创建新任务"):
            central.new_task_gate(self.state, self.project)
        self.assertEqual(store.read_core_source(self.core, "product/WORKFLOW.md"),
                         runtime_bridge.read_resource(self.state, self.project, "product/WORKFLOW.md", binding=self.core.binding()))
