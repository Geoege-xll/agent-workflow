"""中央项目服务的真实文件系统、三宿主资源与独立 Python 桥验证。

整个测试类只导入一次真实核心并共享只读库；每例仅新建短命项目，物理根隔离
也是被验证的业务合同。第二份核心使用最小协议夹具提供版本差异，不复制整仓
候选，不碰真实业务项目、用户全局配置或宿主模型。
"""

from contextlib import ExitStack, contextmanager
import ast
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import shlex
import re
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch
import uuid

from lib import runtime_bridge as bridge
from lib.central import runtime_project as resources
from lib import runtime_store as store
from lib.hosts import workflow_hook_install as hook_install
from lib.hosts.claude_instructions import read_file
from manager import runtime_service as service
from manager import runtime_policy, project_service


PACK = Path(__file__).resolve().parents[1]


def make_alternate_source(root: Path) -> None:
    """两份测试共用最小固定版本来源，仅列出实际桥/资源 helper 的依赖。

    转换后的旧 pin helper 来自先前真实完整核心；本最小版本提供切版目标和
    必要桥协议，不复制完整 lib/产品/模板，也不构造每轮源码候选。
    """
    def put(relative, content):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for directory in store.CORE_DIRECTORIES:
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name in store.SETUP_FILES:
        put(name, b"#!/bin/sh\nexit 0\n")
    for name in ("lib/__init__.py", "lib/install/__init__.py", "lib/central/__init__.py", "lib/hosts/__init__.py", "lib/skills/__init__.py", "lib/documents/__init__.py", "lib/install/project_paths.py", "lib/install/install_process.py", "lib/install/windows_process.py", "lib/platform_fs.py", "lib/windows_fs.py", "lib/windows_bootstrap.py", "lib/runtime_store.py", "lib/central/runtime_project.py", "lib/runtime_bridge.py",
                 "lib/runtime_pins.py", "lib/standard_paths.py", "lib/hosts/claude_instructions.py", "lib/documents/context_read.py",
                 "lib/skills/shared_core_skills.py", "lib/role_models.py", "lib/central/role_preferences.py", "lib/hosts/claude_options.py", "lib/validate_antigravity_artifacts.py",
                 "lib/python_runtime.sh", "lib/hosts/workflow_hook_install.py", "lib/hosts/workflow_hook_settings.py",
                 "manager/runtime_policy.py", "manager/central_runtime.py", "manager/runtime_lifecycle.py",
                 "lib/workflow_hooks.py", "lib/hosts/windows_hook_command.py", "lib/hosts/merge_codex_config.py", "manager/project_service.py", "manager/state_files.py", "manager/runtime_service.py", "manager/runtime_state.py", "manager/__init__.py",
                 "templates/project.yaml.example", "templates/docs/PROJECT.md",
                 "roles/xy-qa.md", "roles/xy-uiux.md", "roles/xy-web.md", "roles/xy-desktop.md", "roles/xy-backend.md", "roles/xy-apple.md", "roles/xy-android.md", "platforms/shared/core-skills.txt"):
        put(name, (PACK / name).read_bytes())
    put("product/WORKFLOW.md", "# 第二个固定版本\n".encode())
    put("product/GLOBAL_CONSTRAINTS.md", b"# fixture constraints\n")
    # 切版夹具只补导航实际消费的最小资源，以区分新旧 pin，不复制第二份完整核心正文。
    for host in ("codex", "claude", "antigravity"):
        put(f"platforms/{host}/references/pm-integration.md", f"# Alternate {host} integration\n".encode())
    for name in (PACK / "platforms/shared/core-skills.txt").read_text().splitlines():
        if name and not name.startswith("#"):
            put(f"platforms/shared/skills/{name}/SKILL.md",
                f"---\nname: {name}\ndescription: fixture skill\n---\n<!-- agent-workflow-pack:managed-skill -->\n# {name}\n".encode())
    put("lib/probe.py", b'import json, os\nprint(json.dumps({key: os.environ[key] for key in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT", "AGENT_WORKFLOW_CORE_ROOT", "AGENT_WORKFLOW_CONFIG_PATH")}, sort_keys=True))\n')
    put("lib/wait_probe.py", b'import subprocess,sys,time\nfrom pathlib import Path\nchild=subprocess.Popen([sys.executable,"-c","import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print(1,flush=True); time.sleep(30)"],stdout=subprocess.PIPE,text=True)\nchild.stdout.readline()\nPath(sys.argv[1]).write_text(str(child.pid))\ntime.sleep(30)\n')


class CentralProjectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="central-project-")
        cls.workspace = Path(cls.temporary.name).resolve()
        cls.state = cls.workspace / "state"
        # 一次共享真实导入覆盖正式载荷、Skill 正文与真实桥的自举，不按用例复制源码。
        cls.core = store.import_core(PACK, cls.state)
        cls.source = cls.workspace / "minimal-source"
        make_alternate_source(cls.source)
        cls.alternate = store.import_core(cls.source, cls.state)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def put(root, relative, body):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    def setUp(self):
        self.project = self.workspace / ("project-" + uuid.uuid4().hex[:10])
        self.project.mkdir()
        # 薄入口的新任务检查由中央current控制桥负责。项目事务夹具保留完整local
        # 角色，但必须显式建立current，不能让旧测试借缺失中央记录绕过正式门。
        with runtime_policy.coordination(self.state), resources.Tree(self.state) as tree:
            from manager.runtime_state import read_state, write_control
            write_control(tree, runtime_policy.CURRENT, resources.json_bytes({"schema_version": 1,
                          "runtime_binding": self.core.binding(), "previous_binding": None,
                          "generation": uuid.uuid4().hex, "native_roots": []}), expected=read_state(self.state, runtime_policy.CURRENT))

    def enable(self, *, core=None):
        plan = service.preview(self.state, self.project, "enable", binding=(core or self.core).binding())
        self.assertTrue(plan.summary["can_apply"], plan.summary["conflicts"])
        result = service.apply(plan)
        self.assertTrue(result["enabled"], result)
        return result

    def invoke(self, *args, env=None, project=None):
        root = project or self.project
        environment = dict(os.environ)
        for name in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT", "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"):
            environment.pop(name, None)
        environment["AGENT_WORKFLOW_STATE_DIR"] = str(self.state)
        environment.update(env or {})
        return subprocess.run(["bash", str(root / resources.PYTHON_ENTRY), "-B", "-X", "utf8",
                               str(root / resources.LAUNCHER), *args], cwd=root,
                              env=environment, capture_output=True, text=True, timeout=40)

    def hook_invocation(self, *, prefix=(), env=None, profile=""):
        """经真实薄入口调用专用Hook；profile只由本测试提供，不改业务返回值。"""
        entry = self.project / resources.LAUNCHER
        arguments = [*prefix, "hook", "--host", "claude", "--event", "SessionStart", "--project", str(self.project),
                     "--owner", hook_install.OWNER, "--signature", "0" * 64]
        environment = {key: value for key, value in os.environ.items() if key not in {
            "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT", "AGENT_WORKFLOW_CONFIG_PATH",
            "AGENT_WORKFLOW_CORE_ROOT", "AGENT_WORKFLOW_HOOK_DEADLINE"}}
        environment.update({"AGENT_WORKFLOW_STATE_DIR": str(self.state), **(env or {})})
        command = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8"]
        command.extend(["-c", profile, str(entry), *arguments] if profile else [str(entry), *arguments])
        return subprocess.run(command, cwd=self.project, env=environment, capture_output=True, text=True, timeout=20,
                              input=json.dumps({"cwd": str(self.project), "hook_event_name": "SessionStart", "source": "resume"}))

    @contextmanager
    def preview_scope_fixture(self):
        """预览用独立state隔离本类其它故障记录；所有生产者仍走真实公开服务。"""
        from lib.hosts.native_context import HostPaths, NativeContext
        from manager import central_runtime
        with tempfile.TemporaryDirectory(prefix="preview-operation-", dir=self.workspace) as raw:
            root = Path(raw).resolve()
            state, project = root / "state", root / "项目"
            project.mkdir()
            (project / "pyproject.toml").write_text('[project]\nname="preview-operation"\nversion="0.1.0"\n')
            context = NativeContext(state, HostPaths.for_home(root / "home", environment={}))
            core = store.import_core(PACK, state)
            alternate_source = root / "explicit-source"
            make_alternate_source(alternate_source)
            alternate = store.import_core(alternate_source, state)
            central_runtime.apply(central_runtime.preview(state, binding=core.binding(), native_context=context))
            project_service.apply_project(project_service.preview_project(state, project, "add", enable=True, native_context=context))
            yield root, state, project, core, alternate, context, alternate_source

    @staticmethod
    def preview_mutable_snapshot(root):
        """只观察mutable状态；core由真实完整reader证明，source另有双inspect守卫。"""
        result = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if any(part in {"runtimes", "explicit-source"} for part in relative.parts):continue
            info = path.lstat()
            if path.is_symlink():value = ("link", str(path.readlink()), info.st_ino, info.st_mode, info.st_mtime_ns)
            elif path.is_file():value = ("file", hashlib.sha256(path.read_bytes()).hexdigest(), info.st_ino, info.st_mode, info.st_mtime_ns)
            else:value = ("dir", info.st_dev, info.st_ino, info.st_mode)
            result[relative.as_posix()] = value
        return result

    def assert_preview_has_no_reader(self, value, seen=None):
        """递归检查实际Plan；不以顶层类型或摘要形状代替句柄生命周期验证。"""
        from dataclasses import fields, is_dataclass
        seen = set() if seen is None else seen
        if id(value) in seen:return
        seen.add(id(value))
        self.assertNotIsInstance(value, (store.CoreReadSession, store.CoreReadOperation))
        if is_dataclass(value):
            for field in fields(value):self.assert_preview_has_no_reader(getattr(value, field.name), seen)
        elif isinstance(value, dict):
            for key, item in value.items():
                self.assert_preview_has_no_reader(key, seen);self.assert_preview_has_no_reader(item, seen)
        elif isinstance(value, (tuple, list, set, frozenset)):
            for item in value:self.assert_preview_has_no_reader(item, seen)

    def test_project_previews_share_read_operation_and_preserve_source_inspection(self):
        """public/direct纯入口共享一次完整证明；显式source仍双inspect且零导入。"""
        with self.preview_scope_fixture() as (root, state, project, core, alternate, context, source):
            project_service.apply_project(project_service.preview_project(state, project, "disable", native_context=context))
            before = self.preview_mutable_snapshot(root)
            summaries = []
            for entry in (lambda: project_service.preview_project(state, project, "enable", native_context=context),
                          lambda: service.preview(state, project, "enable", binding=core.binding(), native_context=context)):
                with patch.object(store, "_scan", wraps=store._scan) as scan, \
                        patch.object(store, "_verify_snapshot", wraps=store._verify_snapshot) as verify, \
                        patch.object(store, "import_core", side_effect=AssertionError("纯预览不能导入核心")):
                    plan = entry()
                self.assertEqual((1, 2), (scan.call_count, verify.call_count))
                self.assertTrue(plan.summary["can_apply"], plan.summary)
                self.assert_preview_has_no_reader(plan)
                self.assertIsNone(store._READ_OPERATION.get())
                self.assertEqual(before, self.preview_mutable_snapshot(root))
                summaries.append(plan.runtime_plan.summary if isinstance(plan, project_service.ProjectPlan) else plan.summary)
            self.assertEqual(summaries[0], summaries[1])
            with patch.object(store, "_scan", wraps=store._scan) as scan, \
                    patch.object(store, "_verify_snapshot", wraps=store._verify_snapshot) as verify:
                with store.core_read_operation() as parent:
                    reader = parent.reader(core.binding(), state)
                    plan = project_service.preview_project(state, project, "enable", native_context=context)
                    self.assertFalse(parent._closed)
                    self.assertIs(reader, parent.reader(core.binding(), state))
                    self.assert_preview_has_no_reader(plan)
                self.assertEqual((1, 2), (scan.call_count, verify.call_count))
            self.assertEqual(before, self.preview_mutable_snapshot(root))
            with patch.object(store, "inspect_core", wraps=store.inspect_core) as inspect, \
                    patch.object(store, "import_core", side_effect=AssertionError("source预览不能偷偷导入")), \
                    patch.object(store, "_scan", wraps=store._scan) as scan, \
                    patch.object(store, "_verify_snapshot", wraps=store._verify_snapshot) as verify:
                source_plan = project_service.preview_project(state, project, "enable", source_root=source, native_context=context)
            self.assertTrue(source_plan.summary["can_apply"], source_plan.summary)
            self.assertEqual((2, 3, 4), (inspect.call_count, scan.call_count, verify.call_count))
            self.assertEqual(before, self.preview_mutable_snapshot(root))
            self.assert_preview_has_no_reader(source_plan)
            original_inspect = store.inspect_core
            mutable_source = source / "product/WORKFLOW.md"
            source_before = mutable_source.read_bytes()
            inspected = []
            def inspect_then_change(path):
                result = original_inspect(path)
                inspected.append(True)
                if len(inspected) == 1:mutable_source.write_bytes(source_before + b"\nactual-source-change\n")
                return result
            try:
                with patch.object(store, "inspect_core", inspect_then_change), \
                        patch.object(store, "import_core", side_effect=AssertionError("坏source不能导入")), \
                        self.assertRaisesRegex(ValueError, "核心来源在预览期间变化"):
                    project_service.preview_project(state, project, "enable", source_root=source, native_context=context)
                self.assertEqual(2, len(inspected))
                self.assertEqual(before, self.preview_mutable_snapshot(root))
            finally:mutable_source.write_bytes(source_before)
            self.assertIsNone(store._READ_OPERATION.get())

    def test_central_preview_separates_pins_and_withholds_plan_on_exit_drift(self):
        """中央组合按实际pin各自证明；尾验失败不交Plan，apply不借旧预览许可。"""
        from manager import central_runtime
        with self.preview_scope_fixture() as (root, state, project, core, alternate, context, source):
            before = self.preview_mutable_snapshot(root)
            for selected, expected in ((core, (1, 2)), (alternate, (2, 4))):
                with patch.object(store, "_scan", wraps=store._scan) as scan, \
                        patch.object(store, "_verify_snapshot", wraps=store._verify_snapshot) as verify:
                    plan = central_runtime.preview(state, binding=selected.binding(), native_context=context)
                self.assertTrue(plan.summary["can_apply"], plan.summary)
                self.assertEqual(selected.binding(), plan.binding)
                self.assertEqual(expected, (scan.call_count, verify.call_count))
                self.assert_preview_has_no_reader(plan)
                self.assertEqual(before, self.preview_mutable_snapshot(root))
                self.assertIsNone(store._READ_OPERATION.get())
            ready = project_service.preview_project(state, project, "use", content_id=alternate.content_id, native_context=context)
            self.assertTrue(ready.summary["can_apply"], ready.summary)
            member = alternate.root / "roles/xy-backend.md"
            original_body, original_mode = member.read_bytes(), stat.S_IMODE(member.stat().st_mode)
            original_finish = store.CoreReadOperation.finish
            injected = []
            returned = []
            def change_before_tail(operation):
                if not injected:
                    member.chmod(original_mode | stat.S_IWUSR)
                    member.write_bytes(original_body + b"\nactual-core-tail-change\n")
                    injected.append(True)
                return original_finish(operation)
            try:
                with patch.object(store.CoreReadOperation, "finish", change_before_tail), \
                        self.assertRaises(store.RuntimeStoreError):
                    returned.append(central_runtime.preview(state, binding=alternate.binding(), native_context=context))
                self.assertEqual([True], injected)
                self.assertEqual([], returned, "尾验失败不能把未验证计划交给调用方")
                self.assertEqual(before, self.preview_mutable_snapshot(root))
                self.assertIsNone(store._READ_OPERATION.get())
                # 此计划是在Core真实变化以前生成的；apply必须独立fresh校验，
                # 不能凭Plan含有同一binding就使用此前预览的reader或字节缓存。
                with patch.object(store, "_scan", wraps=store._scan) as fresh_scan, self.assertRaises(ValueError):
                    project_service.apply_project(ready)
                self.assertGreaterEqual(fresh_scan.call_count, 1)
                self.assertEqual(before, self.preview_mutable_snapshot(root))
            finally:
                member.chmod(original_mode | stat.S_IWUSR)
                member.write_bytes(original_body)
                member.chmod(original_mode)
            registration = project_service.preview_project(state, project, "del", native_context=context)
            registry = state / "projects.json"
            old_registry = registry.read_bytes()
            registry.write_bytes(old_registry + b" ")
            changed = self.preview_mutable_snapshot(root)
            with self.assertRaisesRegex(ValueError, "项目登记表在预览后发生变化"):
                project_service.apply_project(registration)
            self.assertEqual(changed, self.preview_mutable_snapshot(root))
            self.assertIsNone(store._READ_OPERATION.get())

    def test_single_scope_hook_reuses_one_scan_and_rejects_invalid_readers_and_admission(self):
        self.enable()
        profile = '''import collections,json,runpy,sys
counts=collections.Counter()
def observe(frame,event,value):
    if event == "call" and frame.f_code.co_filename.replace("\\\\", "/").endswith("/lib/runtime_store.py"):
        if frame.f_code.co_name in {"_scan", "_verify_snapshot"}: counts[frame.f_code.co_name]+=1
sys.argv=sys.argv[1:]
sys.setprofile(observe)
try:
    runpy.run_path(sys.argv[0],run_name="__main__")
finally:
    sys.setprofile(None)
    print("HOOK_SCOPE_COUNTS "+json.dumps(dict(counts)),file=sys.stderr)
'''
        result = self.hook_invocation(profile=profile)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("SessionStart", json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"])
        counts = json.loads(result.stderr.split("HOOK_SCOPE_COUNTS ", 1)[1])
        self.assertEqual({"_scan": 1, "_verify_snapshot": 2}, counts)
        print("SINGLE_SCOPE_HOOK " + json.dumps(counts), flush=True)
        arguments = ["--host", "claude", "--event", "SessionStart", "--project", str(self.project),
                     "--owner", hook_install.OWNER, "--signature", "0" * 64]
        payload = json.dumps({"cwd": str(self.project), "hook_event_name": "SessionStart", "source": "resume"}).encode()
        with store.core_reader(self.alternate.binding(), self.state) as reader:
            with self.assertRaises(ValueError):
                bridge.hook_response(self.state, self.project, arguments, payload, binding=self.core.binding(), reader=reader)
        with self.assertRaises(ValueError):
            bridge.hook_response(self.state, self.project, arguments, payload, reader=reader)
        with self.assertRaises(ValueError):
            bridge.hook_response(self.state, self.project, arguments, payload, reader=object())
        from lib.install import install_process
        with store.core_reader(self.core.binding(), self.state) as reader:
            # 捕获器负责真实进程资源；这里只定向验证其有限超时/取消错误在
            # Hook桥被转换为安全业务错误，供薄入口统一中性，不能漏出异常栈。
            for failure in (subprocess.TimeoutExpired("fixture", 0.1), install_process.SetupRunError("private fixture")):
                with patch.object(install_process, "capture_process", side_effect=failure):
                    with self.assertRaisesRegex(ValueError, "固定目标Hook未完成"):
                        bridge.hook_response(self.state, self.project, arguments, payload,
                                             binding=self.core.binding(), reader=reader)
        # 显式未知pin、监督预算过期、环境关闭与停用项目均不产生提醒；不能
        # 为了减少扫描而绕开旧版本身份、截止时间或无pin的新任务门。
        unknown = dict(self.core.binding(), content_id="0" * 64, manifest_sha256="0" * 64)
        for prefix, environment in ((("--binding", json.dumps(unknown)), {}),
                                    ((), {"AGENT_WORKFLOW_HOOK_DEADLINE": "0"}),
                                    ((), {"AGENT_WORKFLOW_HOOKS": "off"})):
            refused = self.hook_invocation(prefix=prefix, env=environment)
            self.assertEqual(0, refused.returncode, refused.stderr)
            self.assertEqual({}, json.loads(refused.stdout))
        # current控制器与项目pinned版本不同仍分别完整校验；不能把外层的
        # current reader冒充目标版本，也不能把合法旧pin偷偷改绑到current。
        project_service.apply_project(project_service.preview_project(
            self.state, self.project, "use", content_id=self.alternate.content_id))
        pinned = self.hook_invocation()
        self.assertEqual(0, pinned.returncode, pinned.stderr)
        self.assertIn("hookSpecificOutput", json.loads(pinned.stdout))
        service.apply(service.preview(self.state, self.project, "disable"))
        disabled = self.hook_invocation()
        self.assertEqual(0, disabled.returncode, disabled.stderr)
        self.assertEqual({}, json.loads(disabled.stdout))
        disabled_pin = self.hook_invocation(prefix=("--binding", json.dumps(self.core.binding())))
        self.assertEqual(0, disabled_pin.returncode, disabled_pin.stderr)
        self.assertEqual({}, json.loads(disabled_pin.stdout))

    def test_fixed_graph_runner_validates_once_and_rejects_changed_sources_before_cas(self):
        """实际选版子进程运行原CLI/CAS；同字节消费与退出拒绝都不能靠假的成功回执。"""
        from tests.test_task_graph_records import graph, records
        self.enable()
        path = self.project / "graph.json"
        payload = graph()
        payload["runtime_binding"] = self.core.binding()
        path.write_text(json.dumps(payload), encoding="utf-8")
        arguments = ("update", "--input", str(path), "--expect-sha256", records.digest(path.read_bytes()), "--patch", "-")
        invocation = bridge.python_helper(self.state, self.project, "lib/task_graph_cli.py", arguments, binding=self.core.binding())
        self.assertIn(str(self.core.root / "lib/runtime_pins.py"), invocation.command)
        self.assertIn("--task-graph-operation", invocation.command)
        profile = '''import collections,json,os,runpy,stat,sys
counts=collections.Counter()
def observe(frame,event,value):
    if event == "call" and frame.f_code.co_filename.replace("\\\\", "/").endswith("/lib/runtime_store.py"):
        if frame.f_code.co_name in {"_scan", "_verify_snapshot"}: counts[frame.f_code.co_name]+=1
values=sys.argv[1:]
while values and values[0] in {"-I","-B","-X"}:
    del values[:2 if values[0] == "-X" else 1]
sys.argv=values
sys.setprofile(observe)
try:
    runpy.run_path(values[0],run_name="__main__")
finally:
    sys.setprofile(None)
    print("GRAPH_SCOPE_COUNTS "+json.dumps(dict(counts)),file=sys.stderr)
'''
        def run(selected=invocation, observe=profile, body='{"tasks":{"api":{"set":{"state":"RUNNING"}}}}'):
            # 只在测试解释器外层增加计数；原Windows bootstrap/脚本/参数仍完整
            # 进入runpy，不替换原main、业务guard、源读取或publish的返回值。
            command = [selected.command[0], "-I", "-B", "-X", "utf8", "-c", observe, *selected.command[1:]]
            return subprocess.run(command, cwd=selected.cwd, env=selected.environment, input=body,
                                  text=True, capture_output=True, timeout=40)
        result = run()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["updated"])
        self.assertEqual("RUNNING", json.loads(path.read_bytes())["tasks"][0]["state"])
        counts = json.loads(result.stderr.split("GRAPH_SCOPE_COUNTS ", 1)[1])
        self.assertEqual({"_scan": 1, "_verify_snapshot": 2}, counts)
        print("FIXED_GRAPH_RUNNER_ACTUAL " + json.dumps(counts), flush=True)

        arguments = ("update", "--input", str(path), "--expect-sha256", records.digest(path.read_bytes()), "--patch", "-")
        invocation = bridge.python_helper(self.state, self.project, "lib/task_graph_cli.py", arguments, binding=self.core.binding())
        before = path.read_bytes()
        # reader已取出原CLI字节后才改变磁盘。若消费者重新runpy打开CLI，会执行
        # 这个sentinel；正确消费者使用同字节运行，但必须在原CAS前尾检拒绝。
        mutate_profile = profile.replace('counts=collections.Counter()', '''counts=collections.Counter()
changed=False''').replace('def observe(frame,event,value):', '''def observe(frame,event,value):
    global changed
    if (event == "return" and frame.f_code.co_name == "_read_manifest_source"
            and frame.f_locals.get("relative") == "lib/task_graph_cli.py" and not changed):
        from pathlib import Path
        target=Path(os.environ["AGENT_WORKFLOW_CORE_ROOT"])/"lib/task_graph_cli.py"
        mode=stat.S_IMODE(target.stat().st_mode)
        target.chmod(mode | 0o600)
        target.write_bytes(target.read_bytes()+b"\\nraise RuntimeError('DISK BYTES EXECUTED')\\n")
        target.chmod(mode)
        changed=True''')
        source = self.core.root / "lib/task_graph_cli.py"
        original, mode = source.read_bytes(), stat.S_IMODE(source.stat().st_mode)
        try:
            result = run(invocation, mutate_profile, '{"tasks":{"api":{"set":{"agent_ref":{"host":"codex","agent_id":"fixture-runner"}}}}}')
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
            self.assertIn(b"DISK BYTES EXECUTED", source.read_bytes(), "必须实际触发读后漂移，而非更早的fixture错误")
            self.assertIn("快照", result.stderr)
            self.assertNotIn("DISK BYTES EXECUTED", result.stderr)
            self.assertEqual(before, path.read_bytes())

            self.assertFalse(list(self.project.glob(".*.workflow-*")))
        finally:
            source.chmod(mode | 0o600)
            source.write_bytes(original)
            source.chmod(mode)

        from dataclasses import replace
        wrong = {**invocation.environment, "AGENT_WORKFLOW_CORE_ROOT": str(self.alternate.root)}
        result = run(replace(invocation, environment=wrong))
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual(before, path.read_bytes())

        for alias in ("runtime_store", "lib.runtime_store", "lib"):
            # 即使谎称同一个__file__也不能借入预存模块，不只测路径明显不同
            # 的弱反例；独立runner必须从自己的已选解释器重新建立证明。
            collision = profile.replace("sys.setprofile(observe)", '''from types import ModuleType
from pathlib import Path
foreign=ModuleType(ALIAS)
foreign.__file__=str(Path(os.environ["AGENT_WORKFLOW_CORE_ROOT"])/RELATIVE)
sys.modules[ALIAS]=foreign
sys.setprofile(observe)'''.replace("ALIAS", repr(alias)).replace("RELATIVE", repr("lib/__init__.py" if alias == "lib" else "lib/runtime_store.py")))
            result = run(invocation, collision)
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
            self.assertIn("别名", result.stderr)
            self.assertEqual(before, path.read_bytes())

    def test_fixed_runner_windows_literal_root_guards_are_case_sensitive(self):
        """执行实际runner函数及既有pin守卫的Windows词法；不冒充Win32/NTFS。"""
        from types import SimpleNamespace
        from lib import runtime_pins as pins
        class WinLex(PureWindowsPath):
            def absolute(self):return self
            def expanduser(self):return self
            def resolve(self, **kwargs):return self
            def is_dir(self):return True
        state = WinLex("C:/case/State")
        other_state = WinLex("C:/case/state")
        project = WinLex("C:/case/project")
        other_project = WinLex("C:/case/Project")
        binding = {"protocol_version": 1, "content_id": "a" * 64, "manifest_sha256": "a" * 64}
        root = state / "runtimes" / ("a" * 64) / "core"
        other_root = other_state / "runtimes" / ("a" * 64) / "core"
        environment = {"AGENT_WORKFLOW_RUNTIME_BINDING": json.dumps(binding), "AGENT_WORKFLOW_STATE_DIR": str(state),
                       "AGENT_WORKFLOW_PROJECT_ROOT": str(project), "AGENT_WORKFLOW_CORE_ROOT": str(root),
                       "AGENT_WORKFLOW_CONFIG_PATH": str(project / ".agent-workflow/project.yaml")}
        source = ast.parse((PACK / "lib/runtime_pins.py").read_bytes())
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                     and node.name in {"_runner_preflight", "_runner_module_sources", "_run_fixed_graph"}]
        namespace = {"Path": WinLex, "json": json, "re": re, "os": SimpleNamespace(environ=dict(environment)),
                     "sys": SimpleNamespace(modules={}), "__file__": str(root / "lib/runtime_pins.py"),
                     "store": store, "RuntimePinError": pins.RuntimePinError}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "<actual fixed-runner root guards>", "exec"), namespace)
        self.assertEqual(str(root), str(namespace["_runner_preflight"]()[2]))
        for field, changed in (("AGENT_WORKFLOW_STATE_DIR", other_state), ("AGENT_WORKFLOW_CORE_ROOT", other_root),
                               ("AGENT_WORKFLOW_PROJECT_ROOT", other_project),
                               ("AGENT_WORKFLOW_CONFIG_PATH", other_project / ".agent-workflow/project.yaml")):
            namespace["os"].environ = {**environment, field: str(changed)}
            with self.subTest(boundary="preflight", field=field), self.assertRaisesRegex(ValueError, "三根"):
                namespace["_runner_preflight"]()
        namespace["os"].environ = dict(environment)
        for origin, expected in ((root, True), (other_root, False)):
            namespace["sys"].modules = {"lib.origin": SimpleNamespace(__file__=str(origin / "lib/origin.py"))}
            with self.subTest(boundary="post-import-origin", same_literal=expected):
                if expected:namespace["_runner_module_sources"](root)
                else:
                    with self.assertRaisesRegex(ValueError, "已加载模块"):
                        namespace["_runner_module_sources"](root)
        namespace["sys"].modules = {}
        @contextmanager
        def operation():
            reader = SimpleNamespace(core=store.FrozenCore("a" * 64, "a" * 64, other_root, "source"),
                                     read=lambda *args: self.fail("错根reader不能消费正文"))
            yield SimpleNamespace(reader=lambda *args: reader)
        namespace.update(_RUNNER_CONTEXT=(state, project, root, binding),
                         store=SimpleNamespace(core_read_operation=operation,
                                               absolute_path_key=getattr(store, "absolute_path_key", None)))
        with self.subTest(boundary="runner-reader-root"), self.assertRaisesRegex(ValueError, "物理核心"):
            namespace["_run_fixed_graph"](["validate"])
        # 旧CORE_ENV/CONFIG/project_root在新runner内也必须封闭，不能只修预检
        # 或把其它旧接口的更早失败当成此处守卫有效。
        reader = store.CoreReadSession(store.FrozenCore("a" * 64, "a" * 64, root, "source"), 123, {"files": []}, {})
        try:
            with patch.object(pins, "Path", WinLex), patch.object(store, "state_root", return_value=state), \
                    patch.dict(os.environ, environment):
                with self.subTest(boundary="explicit-project-root"), self.assertRaises(pins.RuntimePinError):
                    pins.project_root(other_project)
                for field, changed in ((pins.CORE_ENV, other_root),
                                       (pins.CONFIG_ENV, other_project / ".agent-workflow/project.yaml")):
                    with self.subTest(boundary="record-binding", field=field), \
                            patch.dict(os.environ, {field: str(changed)}), self.assertRaises(pins.RuntimePinError):
                        pins.record_binding({"runtime_binding": binding}, root=project, reader=reader)
        finally:
            reader._close()

    def test_fixed_graph_runner_keeps_old_pin_helper_path_and_target_provenance(self):
        """旧能力只走旧helper，实际运行原CLI；current与旧pin不能相互借代码/身份。"""
        from tests.test_task_graph_records import graph
        self.enable()
        source = self.workspace / ("old-graph-source-" + uuid.uuid4().hex)
        make_alternate_source(source)
        # 在已有最小版本上补原CLI实际import闭包和三份规范，不复制另一份候选。
        dependencies = ("lib/task_graph_cli.py", "lib/task_graph_records.py", "lib/task_graph.py",
                        "lib/task_settlement.py", "lib/agent_continuation.py", "lib/worktree_policy.py",
                        "lib/validate_project_docs.py", "lib/skills/business_confirmation_policy.py",
                        "lib/skills/skill_contracts.py", "lib/skills/role_skills.py", "lib/project/__init__.py",
                        "lib/project/validate_project_config.py", "lib/project/project_discovery.py",
                        "lib/documents/plan_documents.py")
        from lib.standard_paths import BUILTIN_STANDARD_SOURCES
        for relative in (*dependencies, *BUILTIN_STANDARD_SOURCES):
            self.put(source, relative, (PACK / relative).read_bytes())
        pins = source / "lib/runtime_pins.py"
        # Git的Windows检出可使用CRLF；按带结束符的完整声明行移除，不能用
        # 固定LF后缀替换却默默保留新能力。两种实际字节形式都进入真实消费者，
        # 其余行结束符保持，避免先全部转换LF掩盖原生失败的输入前提。
        lf_source = pins.read_bytes().replace(b"\r\n", b"\n")
        self.assertNotIn(b"\r", lf_source)
        declaration = b"CORE_READ_OPERATION_PROTOCOL = 1"
        for newline, supplied in (("LF", lf_source), ("CRLF", lf_source.replace(b"\n", b"\r\n"))):
            with self.subTest(line_ending=newline):
                lines = supplied.splitlines(keepends=True)
                selected = [index for index, line in enumerate(lines) if line.rstrip(b"\r\n") == declaration]
                self.assertEqual(1, len(selected), "旧能力fixture必须先有且只有一条预期声明，不能空替换")
                old_source = b"".join(line for index, line in enumerate(lines) if index != selected[0])
                self.assertNotEqual(supplied, old_source)
                crlf_count = old_source.count(b"\r\n")
                bare_lf_count = old_source.count(b"\n") - crlf_count
                self.assertGreater(crlf_count if newline == "CRLF" else bare_lf_count, 0)
                self.assertEqual(0, bare_lf_count if newline == "CRLF" else crlf_count)
                pins.write_bytes(old_source)
                old = store.import_core(source, self.state)
                # 先在真实固定core上消费原生产静态能力检查。只有明确旧能力0
                # 才继续回退断言；不能让新runner命令或其它更早失败冒充旧路径。
                with store.core_reader(old.binding(), self.state) as reader:
                    self.assertEqual(old_source, reader.read(old, "lib/runtime_pins.py"))
                    protocol = bridge._static_protocol(old, "CORE_READ_OPERATION_PROTOCOL", reader=reader,
                                                       logical_path="lib/runtime_pins.py")
                    self.assertEqual(0, protocol, "冻结后的旧pin必须真实缺少新runner能力")
                print("OLD_PIN_FALLBACK_SOURCE " + json.dumps({"line_ending": newline, "protocol": protocol,
                      "content_id": old.content_id, "source_sha256": hashlib.sha256(old_source).hexdigest(),
                      "crlf_lines": crlf_count, "bare_lf_lines": bare_lf_count}), flush=True)
                project_service.apply_project(project_service.preview_project(
                    self.state, self.project, "use", content_id=old.content_id))
                path = self.project / ("old-graph-" + newline + ".json")
                payload = graph()
                payload["runtime_binding"] = old.binding()
                path.write_text(json.dumps(payload), encoding="utf-8")
                before = path.read_bytes()
                arguments = ("validate", "--input", str(path))
                legacy = bridge.python_helper(self.state, self.project, "lib/task_graph_cli.py", arguments, binding=old.binding())
                self.assertIn(str(old.root / "lib/task_graph_cli.py"), legacy.command)
                self.assertNotIn("--task-graph-operation", legacy.command)
                result = subprocess.run(legacy.command, env=legacy.environment, cwd=legacy.cwd,
                                        capture_output=True, text=True, timeout=40)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual({"status": "valid"}, json.loads(result.stdout))
                self.assertEqual(before, path.read_bytes())
                # 同一项目实际已切到old，但完整原pin仍必须用自己的新runner；
                # 不接受另一版payload，不把旧任务自动改绑到current/new core。
                current = bridge.python_helper(self.state, self.project, "lib/task_graph_cli.py", arguments, binding=self.core.binding())
                self.assertIn(str(self.core.root / "lib/runtime_pins.py"), current.command)
                result = subprocess.run(current.command, env=current.environment, cwd=current.cwd,
                                        capture_output=True, text=True, timeout=40)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)
                self.assertIn("桥执行版本冲突", result.stderr)
                self.assertEqual(before, path.read_bytes())

    def test_single_scope_hook_keeps_old_core_without_command_capability_neutral(self):
        self.enable()
        source = self.source / "lib/workflow_hooks.py"
        body = source.read_bytes()
        try:
            # 复用同一最小来源生成一个缺少新响应接口的真实固定版本；只证明
            # 能力不足时安全中性，不复制完整core、不添加旧自包含兼容路径。
            source.write_bytes(b"def main():\n    raise RuntimeError('old callback must not execute')\n")
            old = store.import_core(self.source, self.state)
        finally:
            source.write_bytes(body)
        project_service.apply_project(project_service.preview_project(
            self.state, self.project, "use", content_id=old.content_id))
        self.assertTrue(service.status(self.state, self.project)["new_task_allowed"])
        for prefix in ((), ("--binding", json.dumps(old.binding()))):
            rejected = self.hook_invocation(prefix=prefix)
            self.assertEqual(0, rejected.returncode, rejected.stderr)
            self.assertEqual({}, json.loads(rejected.stdout))
            self.assertNotIn("old callback must not execute", rejected.stderr)

    def test_single_scope_hook_target_pin_keeps_its_own_callback_dependencies(self):
        self.enable()
        settings = self.source / "lib/hosts/workflow_hook_settings.py"
        body = settings.read_bytes()
        try:
            # 真实固定目标的解析器故意与current不同；若只校验旧Hook正文、
            # 却借当前已加载lib依赖执行，响应会错误地恢复为assist提醒。
            settings.write_bytes(b'def hook_mode(text):\n    return "off"\n')
            selected = store.import_core(self.source, self.state)
        finally:
            settings.write_bytes(body)
        project_service.apply_project(project_service.preview_project(
            self.state, self.project, "use", content_id=selected.content_id))
        self.assertTrue(service.status(self.state, self.project)["new_task_allowed"])
        result = self.hook_invocation()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({}, json.loads(result.stdout), "目标pin必须执行自己的固定Hook依赖，不能借current解析器")

    def test_single_scope_hook_withholds_response_on_exit_mutation_or_module_conflict(self):
        self.enable()
        conflict = '''import runpy,sys,types
sys.modules["lib.runtime_store"]=types.ModuleType("untrusted_store")
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name="__main__")
'''
        rejected = self.hook_invocation(profile=conflict)
        self.assertEqual(0, rejected.returncode, rejected.stderr)
        self.assertEqual({}, json.loads(rejected.stdout))
        target = self.core.root / "product/GLOBAL_CONSTRAINTS.md"
        before, mode = target.read_bytes(), target.stat().st_mode & 0o7777
        # 只在固定Hook已经算出响应后改动本例独占核心；最终整树复核必须
        # 拒绝发布整份提醒，不能先输出hookSpecificOutput再追加一个空对象。
        mutate = '''import os,runpy,sys
from pathlib import Path
target=Path(''' + repr(str(target)) + ''')
changed=False
def observe(frame,event,value):
    global changed
    if event == "return" and frame.f_code.co_name == "command_response" and not changed:
        changed=True
        target.chmod(0o600)
        target.write_bytes(b"fixture exit mutation")
sys.argv=sys.argv[1:]
sys.setprofile(observe)
try:
    runpy.run_path(sys.argv[0],run_name="__main__")
finally:
    sys.setprofile(None)
'''
        try:
            rejected = self.hook_invocation(profile=mutate)
            self.assertEqual(0, rejected.returncode, rejected.stderr)
            self.assertEqual({}, json.loads(rejected.stdout))
            self.assertEqual(b"fixture exit mutation", target.read_bytes())
        finally:
            target.chmod(0o600)
            target.write_bytes(before)
            target.chmod(mode)

    def test_profile_helper_uses_verified_project_and_pinned_core(self):
        self.enable()
        binding = json.dumps(self.core.binding())
        def profile(*args, env=None):
            return self.invoke("--binding", binding, "helper", "lib/project/project_profile_cli.py", *args, env=env)

        # 通过真正的自举薄桥调用各公开模式，并检查原始 JSON/角色合同。
        for args in (("context", ".agent-workflow", ".", "xy-qa"),
                     ("json", ".agent-workflow", "."), ("roles", ".agent-workflow", "."),
                     ("design-scaffold", ".agent-workflow", "."),
                     ("check-roles", "codex", ".agent-workflow", ".")):
            result = profile(*args)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            if args[0] == "json":
                self.assertIn("xy-qa", json.loads(result.stdout)["enabled_roles"])
        self.assertNotEqual(0, profile("roles", ".agent-workflow", str(self.workspace)).returncode)
        # 切版后仍从旧 pin 运行旧 helper，当前受管链接则由机器记录验证新核心。
        plan = service.preview(self.state, self.project, "use", binding=self.alternate.binding())
        self.assertTrue(plan.summary["can_apply"], plan.summary["conflicts"])
        service.apply(plan)
        result = profile("roles", ".agent-workflow", ".")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        bad = dict(self.core.binding(), content_id="0" * 64, manifest_sha256="0" * 64)
        result = self.invoke("--binding", json.dumps(bad), "helper", "lib/project/project_profile_cli.py", "roles", ".agent-workflow", ".")
        self.assertNotEqual(0, result.returncode)

    def test_profile_helper_rejects_replaced_managed_skill(self):
        self.enable()
        link = self.project / ".agents/skills/xy-workflow"
        target = os.readlink(link)
        # 先把原链接移到项目外的同一临时工作区保留，防止 Linux 在 unlink 后
        # 立即复用 inode，使同目标重建仍满足生产归属检查的 (dev, inode)。
        # lstat 只比较链接节点本身，确保下面的拒绝断言确实针对不同身份的链接。
        retained_link = self.workspace / (self.project.name + "-original-workflow-link")
        link.rename(retained_link)
        link.symlink_to(target)
        self.assertNotEqual(retained_link.lstat().st_ino, link.lstat().st_ino)
        result = self.invoke("--binding", json.dumps(self.core.binding()), "helper", "lib/project/project_profile_cli.py",
                             "roles", ".agent-workflow", ".")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stdout)

    def test_profile_helper_rejects_foreign_link_and_missing_role(self):
        for scenario in ("target", "foreign", "role"):
            with self.subTest(scenario=scenario):
                self.project = self.workspace / ("profile-" + uuid.uuid4().hex[:10])
                self.project.mkdir()
                self.enable()
                if scenario == "target":
                    link = self.project / ".agents/skills/xy-workflow"
                    link.unlink()
                    link.symlink_to(self.workspace)
                elif scenario == "foreign":
                    # 文档路径不是受管 Skill，不能因存在合法 Skill 而获得豁免。
                    (self.project / "docs/standards").symlink_to(self.workspace)
                else:
                    (self.project / ".codex/agents/xy-qa.toml").unlink()
                result = self.invoke("--binding", json.dumps(self.core.binding()), "helper",
                                     "lib/project/project_profile_cli.py", "roles", ".agent-workflow", ".")
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("", result.stdout)

    def test_explicit_read_sessions_bound_consumers_and_close_before_publication(self):
        """完整核心真实安装/薄入口消费；计数证明复用范围，不能替代 Windows 耗时。"""
        proposal = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        sessions, original_reader = [], store.core_reader
        original_write = service._write_private
        @contextmanager
        def observed_reader(*args, **kwargs):
            with original_reader(*args, **kwargs) as reader:
                sessions.append(reader)
                yield reader
        def assert_closed():
            self.assertTrue(all(reader._root is None for reader in sessions), "reader cannot cross publication/execution")
        def publish(*args, **kwargs):
            assert_closed()
            return original_write(*args, **kwargs)
        def measured(label, action):
            with ExitStack() as stack:
                counts = {name: stack.enter_context(patch.object(store, name, wraps=getattr(store, name)))
                          for name in ("_scan", "_verify_snapshot", "_read_regular", "_entry_identity",
                                       "_relative_parent", "_child_directory")}
                result = action()
            facts = {name: value.call_count for name, value in counts.items()}
            print("PORTABLE_EXPLICIT_SESSION_COUNTS " + json.dumps({"phase": label, "counts": facts}, sort_keys=True), flush=True)
            return result, facts
        with patch.object(store, "core_reader", side_effect=observed_reader), \
                patch.object(service, "_write_private", side_effect=publish):
            applied, apply_counts = measured("apply_after", lambda: service.apply(proposal))
        self.assertTrue(applied["enabled"], applied)
        self.assertEqual(4, apply_counts["_scan"])
        self.assertLess(apply_counts["_entry_identity"], 33386)
        assert_closed()
        checked, check_counts = measured("check_resolve_after", lambda: bridge.resolve_runtime(self.state, self.project, new_task=True))
        self.assertEqual(self.core.binding(), checked.runtime_binding)
        self.assertEqual(1, check_counts["_scan"])
        self.assertEqual(2, check_counts["_verify_snapshot"])
        self.assertLess(check_counts["_entry_identity"], 36562)
        again, again_counts = measured("check_next_operation", lambda: bridge.resolve_runtime(self.state, self.project, new_task=True))
        self.assertEqual(checked, again)
        self.assertEqual(1, again_counts["_scan"], "independent call must freshly scan again")
        from manager.central_runtime import new_task_gate
        gated, gate_counts = measured("default_commit_gate_fresh", lambda: new_task_gate(self.state, self.project))
        self.assertEqual(self.core.binding(), gated)
        self.assertEqual(2, gate_counts["_scan"], "default child/commit gate retains its fresh load boundary")
        baseline = service.status(self.state, self.project)
        with store.core_reader(self.core.binding(), self.state) as reader:
            self.assertEqual(baseline, service.status(self.state, self.project, reader=reader))
            material = resources.Resources(self.core.root, resources.json_bytes(self.core.binding()), self.core.label, self.core)
            with material.session_view(reader) as view:
                self.assertEqual((self.core.root / "product/WORKFLOW.md").read_bytes(), view.read("product/WORKFLOW.md"))
            with self.assertRaises(ValueError):
                view.read("product/WORKFLOW.md")
        with self.assertRaises(ValueError):
            service.status(self.state, self.project, reader=reader)
        with self.assertRaises(ValueError):
            service.status(self.state, self.project, reader=object())
        with store.core_reader(self.alternate.binding(), self.state) as reader:
            with self.assertRaises(ValueError):
                service.status(self.state, self.project, reader=reader)
        # 真实生成薄入口及选版 helper 都在自己的进程中重新验证，不用父进程
        # 打开的 reader，不改原40s/Hook预算；验证字节与三字段 pin 均保持。
        checked = self.invoke("check")
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertEqual(self.core.binding(), json.loads(checked.stdout)["runtime_binding"])
        logical, pin = "product/GLOBAL_CONSTRAINTS.md", json.dumps(self.core.binding())
        read = self.invoke("--binding", pin, "read", logical)
        self.assertEqual(0, read.returncode, read.stderr)
        self.assertEqual((self.core.root / logical).read_bytes(), read.stdout.encode())
        input_path = self.project / "fingerprints.json"
        input_path.write_text('["AGENTS.md"]', encoding="utf-8")
        helper = self.invoke("--binding", pin, "helper", "lib/task_graph_cli.py", "fingerprints",
                             "--root", str(self.project), "--input", str(input_path))
        self.assertEqual(0, helper.returncode, helper.stdout + helper.stderr)
        self.assertTrue(json.loads(helper.stdout)["matched"])
        self.assertEqual(1, json.loads(helper.stdout)["checked"])

    def test_init_scopes_pin_sources_and_keeps_fresh_publication_gate(self):
        """同原生组合的合法 init 决策与实际发布，计数不替代 Windows 时限证明。"""
        from lib import runtime_pins as pins, task_graph_cli, task_graph_init, task_graph_records
        from tests.test_task_graph_init import BUILTIN_ENGINEERING, decisions
        self.enable()
        selected = decisions()
        selected["standards"].update(required_engineering_rule_ids=["eng-common-005"],
            leaves=[{"path": BUILTIN_ENGINEERING, "domain": "engineering", "rule_ids": ["eng-common-005"]}])
        selected["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
        input_path, output = self.project / "init-decisions.json", self.project / "initialized.json"
        body = json.dumps(selected, ensure_ascii=False).encode()
        input_path.write_bytes(body)
        invocation = bridge.python_helper(self.state, self.project, "lib/task_graph_cli.py",
            ("init", "--root", str(self.project), "--input", str(input_path), "--output", str(output)), binding=self.core.binding())
        self.assertEqual(1, invocation.admission_protocol)
        sessions, waits = [], []
        original_reader, original_coordination, original_publish = pins._source_reader, runtime_policy.coordination, task_graph_records.publish
        def assert_closed():
            self.assertTrue(all(reader._root is None for reader in sessions), "source reader must close before commit")
        @contextmanager
        def observed_reader(*args):
            with original_reader(*args) as reader:
                sessions.append(reader)
                yield reader
        @contextmanager
        def coordination(*args, **kwargs):
            assert_closed()
            started = time.monotonic()
            with original_coordination(*args, **kwargs):
                waits.append(time.monotonic() - started)
                yield
        def publish(*args, **kwargs):
            assert_closed()
            return original_publish(*args, **kwargs)
        with patch.dict(os.environ, invocation.environment, clear=True), \
                patch.object(pins, "_source_reader", side_effect=observed_reader), \
                patch.object(runtime_policy, "coordination", side_effect=coordination), \
                patch.object(task_graph_records, "publish", side_effect=publish), ExitStack() as stack:
            counted = {name: stack.enter_context(patch.object(store, name, wraps=getattr(store, name)))
                       for name in ("_scan", "_verify_snapshot", "_read_regular", "_entry_identity", "_read_manifest_source")}
            result = task_graph_init.initialize(selected, self.project, output, task_graph_cli._execute,
                                                 input_path=input_path, input_body=body)
        facts = {name: value.call_count for name, value in counted.items()}
        print("PORTABLE_INIT_AFTER " + json.dumps({"counts": facts, "source_scopes": len(sessions),
              "coordination_entries": len(waits), "lock_wait_s": waits}, sort_keys=True), flush=True)
        self.assertEqual(11, facts["_scan"])
        self.assertEqual(22, facts["_verify_snapshot"])
        self.assertEqual(4, len(sessions), "initial/final fingerprints and both catalogs stay independently fresh")
        self.assertEqual(1, len(waits))
        assert_closed()
        self.assertTrue(result["initialized"])
        graph = json.loads(output.read_bytes())
        self.assertEqual(self.core.binding(), graph["runtime_binding"])
        self.assertEqual({"protocol_version", "content_id", "manifest_sha256"}, set(graph["runtime_binding"]))
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), result["sha256"])
        # 同一合法输入再经真实生成薄桥启动 core 的脚本入口，覆盖直接脚本
        # import 分支；不以当前进程的包导入成功冒充子 helper 可以真实执行。
        bridged_output = self.project / "bridge-initialized.json"
        bridged = self.invoke("--binding", json.dumps(self.core.binding()), "helper", "lib/task_graph_cli.py", "init",
                              "--root", str(self.project), "--input", str(input_path), "--output", str(bridged_output))
        self.assertEqual(0, bridged.returncode, bridged.stdout + bridged.stderr)
        self.assertEqual(output.read_bytes(), bridged_output.read_bytes())
        self.assertEqual(self.core.binding(), json.loads(bridged_output.read_bytes())["runtime_binding"])

    def test_pinned_source_scopes_keep_context_members_and_cross_call_tamper_guards(self):
        """源读取优化仍消费真实固定核心，错误桥三根和后置变化都不能获得正文。"""
        from lib import runtime_pins as pins, validate_project_docs as docs
        from lib.standard_paths import BUILTIN_STANDARD_SOURCES
        self.enable()
        invocation = bridge.python_helper(self.state, self.project, "lib/task_graph_cli.py", ("fingerprints",), binding=self.core.binding())
        expected = {path: (self.core.root / path).read_bytes() for path in BUILTIN_STANDARD_SOURCES}
        first = next(iter(expected))
        source_catalog = docs.builtin_standard_rule_catalog(PACK)
        with patch.dict(os.environ, invocation.environment, clear=True):
            for action, wanted in ((lambda: pins.read_source(self.core.binding(), first), expected[first]),
                                   (lambda: pins.read_builtin_sources(self.core.binding()), expected),
                                   (lambda: docs.builtin_standard_rule_catalog(PACK, binding=self.core.binding()), source_catalog)):
                with patch.object(store, "_scan", wraps=store._scan) as scans:
                    actual = action()
                self.assertEqual(1, scans.call_count)
                self.assertEqual(wanted, actual)
            with patch.object(store, "_SOURCE_BATCH_BYTES_LIMIT", 1), self.assertRaisesRegex(ValueError, "预算"):
                pins.read_builtin_sources(self.core.binding())
            with self.assertRaises(ValueError):
                pins.read_source(self.core.binding(), "roles/unregistered.md")
            with self.assertRaises(ValueError):
                pins.read_builtin_source(self.core.binding(), "roles/xy-backend.md")
            with self.assertRaises(ValueError):
                pins.record_binding({"runtime_binding": self.core.binding()}, reader=object())
            with store.core_reader(self.alternate.binding(), self.state) as reader:
                with self.assertRaises(ValueError):
                    pins.record_binding({"runtime_binding": self.core.binding()}, reader=reader)
            with self.assertRaises(ValueError):
                pins.record_binding({"runtime_binding": self.core.binding()}, reader=reader)
            for key, value in ((pins.BINDING_ENV, json.dumps(self.alternate.binding())),
                               (pins.CORE_ENV, str(self.source)),
                               (pins.CONFIG_ENV, str(self.project / "project.yaml")),
                               (pins.PROJECT_ENV, str(self.workspace / "missing-project"))):
                with self.subTest(context=key), patch.dict(os.environ, {key: value}), self.assertRaises((OSError, ValueError)):
                    pins.read_builtin_sources(self.core.binding())
            changed = self.core.root / "product/WORKFLOW.md"
            original, mode = changed.read_bytes(), changed.stat().st_mode & 0o777
            def write(body):
                changed.chmod(mode | 0o600)
                changed.write_bytes(body)
                changed.chmod(mode)
            try:
                write(original + b"tamper")
                with self.assertRaises(ValueError):
                    pins.read_builtin_sources(self.core.binding())
                write(original)
                original_read = store.CoreReadSession.read
                def drift(reader, core, path):
                    result = original_read(reader, core, path)
                    if path == list(BUILTIN_STANDARD_SOURCES)[-1]:
                        write(original + b"late unselected drift")
                    return result
                with patch.object(store.CoreReadSession, "read", drift), self.assertRaises(ValueError):
                    pins.read_builtin_sources(self.core.binding())
            finally:
                write(original)
            with patch.object(store, "_scan", wraps=store._scan) as scans:
                self.assertEqual(expected, pins.read_builtin_sources(self.core.binding()))
            self.assertEqual(1, scans.call_count, "next call freshly validates, never reuse earlier permission or bytes")

    def test_enable_native_resources_and_read_only_preview(self):
        before = sorted(str(path) for path in self.project.rglob("*"))
        binding_paths = sorted((self.state / "bindings").glob("*")) if (self.state / "bindings").exists() else []
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.assertEqual(before, sorted(str(path) for path in self.project.rglob("*")))
        self.assertEqual(binding_paths, sorted((self.state / "bindings").glob("*")) if (self.state / "bindings").exists() else [])
        self.assertNotIn("body", json.dumps(plan.summary))
        self.assertEqual(18, sum(row["kind"] == "link" for row in plan.summary["changes"]))
        result = service.apply(plan)
        self.assertTrue(result["enabled"])
        self.assertEqual([], result["conflicts"])
        locator = json.loads((self.project / resources.LOCATOR).read_bytes())
        self.assertEqual({"schema_version": 1, "kind": "central", "runtime_binding": self.core.binding()}, locator)
        for directory in ("product", "roles", "platforms", "templates", "manager"):
            self.assertFalse((self.project / ".agent-workflow" / directory).exists())
        self.assertEqual(["python_runtime.sh", "workflow_hooks.py"], sorted(path.name for path in (self.project / ".agent-workflow/lib").iterdir()))
        names = resources.skill_names(resources.Resources(self.core.root, resources.json_bytes(self.core.binding()), self.core.label, self.core))
        with resources.Tree(self.project) as tree:
            for root in (".agents/skills", ".claude/skills"):
                for name in names:
                    relative = root + "/" + name
                    self.assertTrue((self.project / relative).is_symlink())
                    node = tree.read(relative, skill_link=True)
                    resources.validate_skill_link(tree, relative, node, self.core)
        self.assertFalse((self.project / "docs/STANDARDS.md").exists())
        self.assertFalse((self.project / "docs/standards/GENERAL.md").exists())
        # 真实中央生成的根入口与三宿主全部角色都应为英文；该夹具没有用户中文正文，
        # 因而无需协议/围栏豁免。这里仍由后续原生解析器检查权限、工具与固定绑定。
        generated_instructions = [self.project / "AGENTS.md"]
        for directory in (".codex/agents", ".claude/agents", ".agents/agents"):
            generated_instructions.extend(sorted((self.project / directory).glob("xy-*.*")))
        self.assertGreater(len(generated_instructions), 3)
        for path in generated_instructions:
            with self.subTest(english_artifact=path.relative_to(self.project)):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"[\u4e00-\u9fff]")
        # 使用真实标准 TOML 消费器解析 Codex；其他宿主 frontmatter 是已生成的原生薄元数据。
        role = tomllib.loads((self.project / ".codex/agents/xy-qa.toml").read_text())
        self.assertEqual("xy-qa", role["name"])
        self.assertNotIn("sandbox_mode", role)
        self.assertIn("<task-three-field-JSON>", role["developer_instructions"])
        self.assertNotIn(self.core.content_id, role["developer_instructions"])
        self.assertTrue(tomllib.loads((self.project / ".codex/config.toml").read_text())["agents"]["enabled"])
        for path in (".claude/agents/xy-qa.md", ".agents/agents/xy-qa.md"):
            text = (self.project / path).read_text()
            self.assertTrue(text.startswith("---\nname: xy-qa\n"))
            self.assertIn("runtime_binding from that Task Pack", text)
            self.assertNotIn(self.core.content_id, text)
        parser_code = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib.hosts.validate_claude_artifacts import parse_frontmatter
from lib.validate_antigravity_artifacts import parse_agent_frontmatter
project = Path(sys.argv[2])
errors = []
qa, _ = parse_frontmatter(project / ".claude/agents/xy-qa.md", errors)
writer, _ = parse_frontmatter(project / ".claude/agents/xy-uiux.md", errors)
# 实际消费已发布的原生字段，不能以角色提示词或 permissionMode 冒充工具限制。
assert qa.get("tools") == "Read, Grep, Glob, Bash, Skill", qa
assert writer.get("tools") == "Read, Grep, Glob, Bash, Edit, Write, Skill", writer
assert qa.get("disallowedTools") == writer.get("disallowedTools") == "Agent"
assert qa.get("permissionMode") == writer.get("permissionMode") == "default"
path = project / ".agents/agents/xy-qa.md"
parse_agent_frontmatter(path.read_text(encoding="utf-8"), path, errors)
assert not errors, errors
print("native role parsers OK")
'''
        parsed = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", parser_code,
                                 str(self.core.root), str(self.project)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, parsed.returncode, parsed.stdout + parsed.stderr)
        self.assertIn("native role parsers OK", parsed.stdout)
        checked = self.invoke("check")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        self.assertEqual(self.core.binding(), json.loads(checked.stdout)["runtime_binding"])

    def test_minimal_frozen_core_loads_service_owners_without_reverse_dependencies(self):
        """最小核心独立导入所有新 owner，拒绝由源码 checkout 偶然补齐依赖。

        -I 排除工作目录及用户 Python 路径；只加入已冻结且经清单验证的核心。
        项目服务导入不能把模型事务或安装入口拉回来，否则抽取没有隔离边界。
        """
        program = r'''import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from lib.install import project_paths
from lib.install import install_process
from manager import project_service, state_files
for module in (project_paths, install_process, project_service, state_files):
    assert Path(module.__file__).is_relative_to(root), module.__file__
assert "lib.install.install_workflow" not in sys.modules
assert "manager.service" not in sys.modules
assert project_service.parse_registry(None) == {"schema": 1, "registered": [], "hidden": []}
assert project_paths.target_path(sys.argv[2], root) == Path(sys.argv[2])
print("最小冻结核心新 owner 独立加载成功")
'''
        loaded = subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                                 "-I", "-c", program, str(self.alternate.root), str(self.project)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, loaded.returncode, loaded.stdout + loaded.stderr)
        self.assertIn("最小冻结核心新 owner 独立加载成功", loaded.stdout)

    def test_workflow_navigation_reads_same_task_pin_across_switch_and_disable(self):
        # 用户外段逐字保全；导航从真正 enable/repair 产物取得，不能以手写提示代替生成入口。
        prefix = "# 用户规则\r\n中文沟通并保留尾部空格  \r\n".encode()
        suffix = "\r\n用户尾注不得翻译。  ".encode()
        self.put(self.project, "AGENTS.md", prefix)
        self.enable()
        agents = self.project / "AGENTS.md"
        agents.write_bytes(agents.read_bytes() + suffix)
        service.apply(service.preview(self.state, self.project, "repair"))
        before = agents.read_bytes()
        self.assertTrue(before.startswith(prefix))
        self.assertTrue(before.endswith(suffix))
        managed = before.decode().split(resources.CENTRAL_BEGIN, 1)[1].split(resources.CENTRAL_END, 1)[0]
        self.assertNotRegex(managed, r"[\u4e00-\u9fff]")
        self.assertIn("$xy-workflow", managed)
        self.assertIn("/xy-workflow", managed)
        self.assertIn("current host", managed)
        self.assertIn("only", managed)
        self.assertIn("runtime_binding", managed)
        self.assertIn("discovery symlinks", managed)
        # 从生成文案中提取两条真实桥命令，只代入已说明的 binding/宿主占位符；
        # shell 不参与替换/执行，防止夹具意外扩大为模型启动或任意命令测试。
        commands = re.findall(r"`(bash [^`]+ --binding '<task-three-field-JSON>' read [^`]+)`", managed)
        skill_path = "platforms/shared/skills/xy-workflow/SKILL.md"
        host_pattern = "platforms/<current-host>/references/pm-integration.md"
        routes = {shlex.split(command)[-1]: command for command in commands}
        self.assertIn(skill_path, routes)
        self.assertIn(host_pattern, routes)
        checked = self.invoke("check")
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertEqual(self.core.binding(), json.loads(checked.stdout)["runtime_binding"])

        def read_routes():
            for host, path in (("codex", skill_path), *((host, host_pattern) for host in ("codex", "claude", "antigravity"))):
                actual_path = path.replace("<current-host>", host)
                argv = shlex.split(routes[path].replace("<task-three-field-JSON>", json.dumps(self.core.binding(), separators=(",", ":")))
                                   .replace("<current-host>", host))
                environment = dict(os.environ)
                for key in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT", "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"):
                    environment.pop(key, None)
                environment["AGENT_WORKFLOW_STATE_DIR"] = str(self.state)
                read = subprocess.run(argv, cwd=self.project, env=environment, text=True,
                                      capture_output=True, timeout=40)
                self.assertEqual(0, read.returncode, read.stdout + read.stderr)
                self.assertEqual(store.read_core_source(self.core, actual_path).decode(), read.stdout)

        read_routes()
        # 当前项目换版及发现软链更新后，旧任务仍执行从其原入口取得的同 pin 读取命令。
        project_service.apply_project(project_service.preview_project(self.state, self.project, "use", content_id=self.alternate.content_id))
        self.assertEqual(self.alternate.binding(), bridge.resolve_runtime(self.state, self.project, new_task=True).runtime_binding)
        self.assertNotEqual(store.read_core_source(self.core, skill_path), store.read_core_source(self.alternate, skill_path))
        self.assertTrue(agents.read_bytes().startswith(prefix))
        self.assertTrue(agents.read_bytes().endswith(suffix))
        read_routes()
        # 保留受管块外后加内容的失败分支，并记录实际前后字节与机器归属前像，
        # 以区分夹具放错位置和真实停用数据丢失；原红例的外段保全断言继续保留。
        before_disable = agents.read_bytes()
        managed_record = service.read_binding_record(self.state, self.project)[1]["managed"]["AGENTS.md"]
        baseline = resources.Node.from_value(managed_record["baseline"]).payload
        expected = resources.Node.from_value(managed_record["expected"]).payload
        service.apply(service.preview(self.state, self.project, "disable"))
        self.assertNotEqual(0, self.invoke("check").returncode)
        read_routes()
        wanted = prefix + b"\n" + suffix
        self.assertEqual(wanted, agents.read_bytes(),
                         f"before_disable={before_disable!r}; baseline={baseline!r}; "
                         f"expected_equals_current={expected == before_disable}; "
                         f"suffix_is_outside_block={before_disable.endswith(suffix) and suffix not in resources.central_block(before_disable)}; "
                         f"wanted={wanted!r}; actual={agents.read_bytes()!r}")

    def test_claude_tools_reject_unknown_source_policy_before_writes(self):
        source = store.read_core_source(self.core, "roles/xy-qa.md")
        original_read = resources.Resources.read
        # 只替换本次只读资源的策略声明，复用已导入核心与项目，不复制核心候选；
        # 缺失、重复、未知及混合策略都不得触发旧 Shell 的默认 write 回退。
        invalid = (
            source.replace(b"toolsets: [read]", b"toolsets: [unknown-mcp]"),
            source.replace(b"toolsets: [read]", b"toolsets: [read, write]"),
            source.replace(b"toolsets: [read]", b"toolsets: [read]\ntoolsets: [write]"),
            source.replace(b"toolsets: [read]\n", b""),
        )
        for body in invalid:
            with self.subTest(policy=body.split(b"workspace:", 1)[0]):
                def replaced(reader, relative):
                    return body if relative == "roles/xy-qa.md" else original_read(reader, relative)
                with patch.object(resources.Resources, "read", new=replaced), self.assertRaisesRegex(ValueError, "角色.*toolsets"):
                    service.preview(self.state, self.project, "enable", binding=self.core.binding())
                self.assertEqual([], list(self.project.iterdir()))
                self.assertIsNone(service.read_binding_record(self.state, self.project)[1])

    def test_claude_model_commit_keeps_tools_and_rejects_tool_edits(self):
        from lib import role_models
        from manager.service import Change, commit
        self.enable()
        relative = ".claude/agents/xy-qa.md"
        path = self.project / relative
        before = path.read_bytes()
        tools = b"tools: Read, Grep, Glob, Bash, Skill\n"
        self.assertIn(tools, before)
        selected = {"model": "fixture-claude-model", "effort": "high"}
        after = role_models.patch_artifact(before, "claude", selected)
        config = (self.project / resources.CONFIG).read_bytes()
        updated = role_models.update(config.decode(), {"claude": {"xy-qa": selected}}).encode()
        # 使用唯一自动收据入口提交真实模型补丁；工具、权限和其余元数据保持。
        commit(self.state, self.project, [Change(relative, before, after, 0o644),
                                         Change(resources.CONFIG, config, updated, 0o644)])
        self.assertEqual(after, path.read_bytes())
        self.assertIn(tools, after)
        self.assertIn(b"permissionMode: default\n", after)
        self.assertIn(b"disallowedTools: Agent\n", after)
        self.assertTrue(service.status(self.state, self.project)["enabled"])

        # 工具变更即使夹带合法模型变化也不能登记为模型收据，更不能由 repair
        # 重新渲染后洗掉未知手改；未知 MCP 与 Edit/Write 均不属于 QA 的工具集。
        broadened = after.replace(tools, b"tools: Read, Grep, Glob, Bash, Edit, Write, Skill, mcp__unknown__tool\n")
        forged = role_models.patch_artifact(broadened, "claude", {"model": "forged-model", "effort": "low"})
        with self.assertRaisesRegex(ValueError, "模型字段以外"):
            commit(self.state, self.project, [Change(relative, after, forged, 0o644)])
        self.assertEqual(after, path.read_bytes())
        path.write_bytes(broadened)
        self.assertFalse(service.preview(self.state, self.project, "repair").summary["can_apply"])
        next_model = role_models.patch_artifact(broadened, "claude", {"model": "second-model", "effort": "low"})
        with self.assertRaisesRegex(ValueError, "未知编辑"):
            commit(self.state, self.project, [Change(relative, broadened, next_model, 0o644)])
        self.assertEqual(broadened, path.read_bytes())

    def test_config_models_permissions_mcp_memory_and_user_text_preserved(self):
        config = resources.initial_config(resources.Resources(self.core.root, resources.json_bytes(self.core.binding()), self.core.label, self.core), self.project)
        config += b'\nrole_models:\n  codex:\n    xy-qa: {"model":"custom-model","effort":"high"}\n'
        self.put(self.project, resources.CONFIG, config)
        originals = {".codex/config.toml": b'model = "private-model"\n[mcp_servers.private]\ncommand = "user command"\n',
                     ".claude/settings.json": b'{"permissions":{"allow":["Read"]},"mcpServers":{"private":{"token":"fixture-secret"}}}\n',
                     "AGENTS.md": "用户自己的中文规则，不得覆盖。\n".encode(),
                     "CLAUDE.md": "用户自己的 Claude 指令。\n".encode(),
                     "docs/PROJECT.md": "现有项目正文。\n".encode()}
        for relative, body in originals.items():
            self.put(self.project, relative, body)
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.assertNotIn("fixture-secret", json.dumps(plan.summary))
        service.apply(plan)
        self.assertEqual(config, (self.project / resources.CONFIG).read_bytes())
        shared = json.loads((self.project / ".claude/settings.json").read_bytes())
        shared.pop("hooks")
        self.assertEqual(json.loads(originals[".claude/settings.json"]), shared)
        self.assertEqual(originals["docs/PROJECT.md"], (self.project / "docs/PROJECT.md").read_bytes())
        self.assertTrue((self.project / "AGENTS.md").read_bytes().startswith(originals["AGENTS.md"]))
        self.assertEqual("custom-model", tomllib.loads((self.project / ".codex/agents/xy-qa.toml").read_text())["model"])
        native = tomllib.loads((self.project / ".codex/config.toml").read_text())
        self.assertEqual("private-model", native["model"])
        self.assertEqual("user command", native["mcp_servers"]["private"]["command"])
        service.apply(service.preview(self.state, self.project, "disable"))
        for relative in ("AGENTS.md", "CLAUDE.md", ".codex/config.toml"):
            self.assertEqual(originals[relative], (self.project / relative).read_bytes())

    def test_disable_preserves_pin_documents_config_and_core(self):
        # fingerprint查询应核验持续存在的用户工程文件。纯工作流AGENTS入口
        # 没有用户baseline，停用时应合法删除，不能把它当作只读helper的输入。
        user_file = self.project / "pyproject.toml"
        user_file.write_bytes(b'[project]\nname="disabled-user-fixture"\nversion="0.1.0"\n')
        user_before = user_file.read_bytes()
        user_sha = hashlib.sha256(user_before).hexdigest()
        fingerprints = self.project / "fingerprints.json"
        fingerprints.write_text(json.dumps({"pyproject.toml": user_sha}), encoding="utf-8")
        self.assertFalse((self.project / "AGENTS.md").exists())
        self.enable()
        self.assertTrue((self.project / "AGENTS.md").is_file())
        def check_user_fingerprint():
            self.assertEqual(user_before, user_file.read_bytes())
            self.assertEqual(user_sha, hashlib.sha256(user_file.read_bytes()).hexdigest())
            queried = self.invoke("--binding", json.dumps(self.core.binding()), "helper", "lib/task_graph_cli.py",
                                  "fingerprints", "--root", str(self.project), "--input", str(fingerprints))
            self.assertEqual(0, queried.returncode, queried.stderr)
            self.assertEqual({"matched": True, "checked": 1, "changed": []}, json.loads(queried.stdout))
        check_user_fingerprint()
        config = (self.project / resources.CONFIG).read_bytes()
        document = (self.project / "docs/PROJECT.md").read_bytes()
        result = service.apply(service.preview(self.state, self.project, "disable"))
        self.assertFalse(result["enabled"])
        self.assertEqual("disabled", result["state"])
        self.assertFalse((self.project / "AGENTS.md").exists())
        check_user_fingerprint()
        self.assertEqual(config, (self.project / resources.CONFIG).read_bytes())
        self.assertEqual(document, (self.project / "docs/PROJECT.md").read_bytes())
        self.assertFalse((self.project / ".agents/skills/xy-workflow").exists())
        self.assertFalse((self.project / ".claude/agents/xy-qa.md").exists())
        self.assertTrue((self.project / resources.LAUNCHER).is_file())
        self.assertTrue(self.core.root.exists())
        self.assertEqual(store.read_core_source(self.core, "roles/xy-qa.md"),
                         bridge.read_resource(self.state, self.project, "roles/xy-qa.md", binding=self.core.binding()))
        with self.assertRaisesRegex(ValueError, "不能创建新任务"):
            bridge.resolve_runtime(self.state, self.project, new_task=True)
        self.assertNotEqual(0, self.invoke("check").returncode)

    def test_use_rollback_old_pin_and_env_helper_survive_source_removal(self):
        self.enable()
        changed = service.apply(service.preview(self.state, self.project, "use", binding=self.alternate.binding()))
        self.assertEqual(self.core.binding(), changed["previous_binding"])
        self.assertEqual(self.alternate.binding(), changed["runtime_binding"])
        self.assertEqual(store.read_core_source(self.core, "product/WORKFLOW.md"),
                         bridge.read_resource(self.state, self.project, "product/WORKFLOW.md", binding=self.core.binding()))
        with patch.dict(os.environ, {"AGENT_WORKFLOW_RUNTIME_BINDING": json.dumps(self.core.binding())}):
            self.assertEqual(self.core.binding(), bridge.resolve_runtime(self.state, self.project).runtime_binding)
            self.assertEqual(self.alternate.binding(), bridge.resolve_runtime(self.state, self.project, binding=self.alternate.binding()).runtime_binding)
        # 移走最小来源模拟 Homebrew keg 删除；已安装桥及 Python helper 只依赖持久库。
        detached = self.workspace / "detached-source"
        self.source.rename(detached)
        try:
            ran = self.invoke("helper", "lib/probe.py", env={"AGENT_WORKFLOW_RUNTIME_BINDING": json.dumps(self.alternate.binding())})
            self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
            value = json.loads(ran.stdout)
            self.assertEqual(self.alternate.binding(), json.loads(value["AGENT_WORKFLOW_RUNTIME_BINDING"]))
            self.assertEqual(str(self.project), value["AGENT_WORKFLOW_PROJECT_ROOT"])
            self.assertEqual(str(self.project / resources.CONFIG), value["AGENT_WORKFLOW_CONFIG_PATH"])
            self.assertEqual(str(self.alternate.root), value["AGENT_WORKFLOW_CORE_ROOT"])
            read = self.invoke("--binding", json.dumps(self.core.binding()), "read", "product/WORKFLOW.md")
            self.assertEqual(0, read.returncode, read.stderr)
            self.assertEqual(store.read_core_source(self.core, "product/WORKFLOW.md").decode("utf-8"), read.stdout)
        finally:
            detached.rename(self.source)
        rolled = service.apply(service.preview(self.state, self.project, "rollback"))
        self.assertEqual(self.core.binding(), rolled["runtime_binding"])
        self.assertEqual(self.alternate.binding(), rolled["previous_binding"])

    def test_missing_pin_foreign_pin_clone_and_project_env_are_rejected(self):
        self.enable()
        with self.assertRaisesRegex(ValueError, "缺少 runtime_binding"):
            bridge.read_resource(self.state, self.project, "roles/xy-qa.md")
        with self.assertRaisesRegex(ValueError, "曾经使用"):
            bridge.read_resource(self.state, self.project, "roles/xy-qa.md", binding=self.alternate.binding())
        with patch.dict(os.environ, {"AGENT_WORKFLOW_RUNTIME_BINDING": '{"root":"/private"}'}):
            with self.assertRaises(ValueError):
                bridge.resolve_runtime(self.state, self.project)
        with patch.dict(os.environ, {"AGENT_WORKFLOW_RUNTIME_BINDING": "null"}):
            with self.assertRaises(ValueError):
                bridge.resolve_runtime(self.state, self.project, new_task=True)
        self.assertNotEqual(0, self.invoke("--binding", "null", "check").returncode)
        with patch.dict(os.environ, {"AGENT_WORKFLOW_PROJECT_ROOT": str(self.workspace)}):
            with self.assertRaisesRegex(ValueError, "项目根"):
                bridge.resolve_runtime(self.state, self.project, binding=self.core.binding())
        clone = self.workspace / ("clone-" + uuid.uuid4().hex[:10])
        shutil.copytree(self.project, clone, symlinks=True)
        checked = self.invoke("check", project=clone)
        self.assertNotEqual(0, checked.returncode)
        self.assertIn("尚未在本机启用", checked.stderr)
        self.assertEqual("unmanaged", service.status(self.state, clone)["state"])

    def test_preview_file_directory_and_source_changes_are_rejected(self):
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.put(self.project, "AGENTS.md", b"saved after preview\n")
        with self.assertRaisesRegex(ValueError, "预览后变化"):
            service.apply(plan)
        self.assertEqual(b"saved after preview\n", (self.project / "AGENTS.md").read_bytes())
        second = service.preview(self.state, self.project, "enable", source_root=self.source)
        original = (self.source / "product/WORKFLOW.md").read_bytes()
        self.put(self.source, "product/WORKFLOW.md", b"source changed after preview\n")
        try:
            with self.assertRaisesRegex(ValueError, "来源与预览版本不符"):
                service.apply(second)
        finally:
            self.put(self.source, "product/WORKFLOW.md", original)
        fresh = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        (self.project / ".codex").mkdir()
        with self.assertRaisesRegex(ValueError, "父目录身份"):
            service.apply(fresh)

    def test_generated_long_name_config_is_validated_before_publish(self):
        project = self.workspace / ("long-project-name-" * 7)
        project.mkdir()
        plan = service.preview(self.state, project, "enable", binding=self.core.binding())
        self.assertTrue(plan.summary["can_apply"])
        service.apply(plan)
        body = (project / resources.CONFIG).read_bytes()
        expected = "project-" + hashlib.sha256(project.name.encode()).hexdigest()[:12]
        self.assertIn(("project_id: " + expected).encode(), body)
        self.assertTrue(service.preview(self.state, project, "disable").summary["can_apply"])
        invalid = body.replace(expected.encode(), b"x" * 80)
        with patch.object(resources, "initial_config", return_value=invalid), self.assertRaisesRegex(ValueError, "项目配置需要先显式处理"):
            service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.assertEqual([], list(self.project.iterdir()))

    def test_source_repository_roots_are_protected_for_source_and_binding_enable(self):
        with self.assertRaises(ValueError):
            service.preview(self.state, self.source, "enable", source_root=self.source)
        with self.assertRaises(ValueError):
            service.preview(self.state, self.workspace, "enable", source_root=self.source)
        # 模拟已从不可变核心运行的程序位置，以最小来源夹具验证 binding 模式
        # 同样保护程序根；不需要读取、更不写真实仓库作为负控目标。
        with patch.object(service, "__file__", str(self.source / "manager/runtime_service.py")):
            with self.assertRaises(ValueError):
                service.preview(self.state, self.source, "enable", binding=self.core.binding())

    def test_collision_unknown_links_and_plain_readers_remain_closed(self):
        self.put(self.project, ".codex/agents/xy-qa.toml", b"user owned\n")
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.assertFalse(plan.summary["can_apply"])
        with self.assertRaisesRegex(ValueError, "预览含冲突"):
            service.apply(plan)
        self.assertEqual(b"user owned\n", (self.project / ".codex/agents/xy-qa.toml").read_bytes())
        outside = self.workspace / "outside-link-target"
        outside.mkdir(exist_ok=True)
        (self.project / ".agents/skills").mkdir(parents=True)
        (self.project / ".agents/skills/xy-workflow").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            service.preview(self.state, self.project, "enable", binding=self.core.binding())
        with self.assertRaises(ValueError):
            read_file(self.project / ".agents/skills/xy-workflow/SKILL.md")

    def test_repair_missing_owned_resource_and_reject_changed_role_or_link(self):
        self.enable()
        role = self.project / ".codex/agents/xy-qa.toml"
        role.unlink()
        repaired = service.apply(service.preview(self.state, self.project, "repair"))
        self.assertTrue(repaired["enabled"])
        self.assertTrue(role.is_file())
        link = self.project / ".agents/skills/xy-workflow"
        original = os.readlink(link)
        # repair 负控同样保活旧链接，避免 unlink 后立即重建被 Linux 分配原 inode。
        # 保留位置在项目外且仍属本例临时工作区；用 lstat 确认只替换链接身份，
        # 不把相同目标目录的身份当作变化，也不改变原有的拒绝修复合同。
        retained_link = self.workspace / (self.project.name + "-original-workflow-link")
        link.rename(retained_link)
        link.symlink_to(original, target_is_directory=True)
        self.assertNotEqual(retained_link.lstat().st_ino, link.lstat().st_ino)
        plan = service.preview(self.state, self.project, "repair")
        self.assertFalse(plan.summary["can_apply"])
        self.assertTrue(any("替换" in item["reason"] for item in plan.summary["conflicts"]))
        role.write_bytes(role.read_bytes() + b"# unknown handwritten edit\n")
        self.assertFalse(service.status(self.state, self.project)["enabled"])

    def test_shared_entry_preserves_later_user_text(self):
        # 直接停用与中间 repair/use 都应保留块外新增内容；后两条会更新 expected，
        # 必须验证它不能被当作“全部用户内容仍属于最初快照”的证明。
        for intermediate in (None, "repair", "use"):
            with self.subTest(intermediate=intermediate):
                self.project = self.workspace / ("entry-user-" + uuid.uuid4().hex[:10])
                self.project.mkdir()
                self.enable()
                path = self.project / "AGENTS.md"
                suffix = "\r\n启用后的用户新增规则。  ".encode()
                path.write_bytes(path.read_bytes() + suffix)
                path.chmod(0o600)
                if intermediate:
                    kwargs = {"binding": self.alternate.binding()} if intermediate == "use" else {}
                    service.apply(service.preview(self.state, self.project, intermediate, **kwargs))
                result = service.apply(service.preview(self.state, self.project, "disable"))
                self.assertFalse(result["enabled"])
                self.assertEqual(suffix, path.read_bytes())
                self.assertEqual(0o600, path.stat().st_mode & 0o7777)

    def test_shared_entry_without_external_text_restores_exact_original_state(self):
        # 新建入口、空用户文件、无末尾换行、CRLF/尾空格各有不同前像；经 repair/use
        # 后仍须精确恢复，不以保全外段为由统一留下空文件或安装器分隔换行。
        for original in (None, b"", b"user bytes without newline", "# 中文规则\r\n保留尾部空格  \r\n".encode()):
            with self.subTest(original=original):
                self.project = self.workspace / ("entry-baseline-" + uuid.uuid4().hex[:10])
                self.project.mkdir()
                path = self.project / "AGENTS.md"
                if original is not None:
                    path.write_bytes(original)
                    path.chmod(0o640)
                self.enable()
                service.apply(service.preview(self.state, self.project, "repair"))
                service.apply(service.preview(self.state, self.project, "use", binding=self.alternate.binding()))
                service.apply(service.preview(self.state, self.project, "disable"))
                if original is None:
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(original, path.read_bytes())
                    self.assertEqual(0o640, path.stat().st_mode & 0o7777)

    def test_shared_entry_preserves_changed_mode_without_text_delta(self):
        # 用户只收紧权限、正文仍为初始外段时，也不能因 repair/use 更新 expected
        # 而撤销 chmod；恢复原始字节与保留当前文件模式是同一受管块边界的两个维度。
        original = "# 用户规则\r\n正文和尾部空格保持  \r\n".encode()
        self.put(self.project, "AGENTS.md", original)
        path = self.project / "AGENTS.md"
        path.chmod(0o640)
        self.enable()
        path.chmod(0o600)
        service.apply(service.preview(self.state, self.project, "repair"))
        service.apply(service.preview(self.state, self.project, "use", binding=self.alternate.binding()))
        service.apply(service.preview(self.state, self.project, "disable"))
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(0o600, path.stat().st_mode & 0o7777)

    def test_failure_rolls_back_exact_outputs_and_never_enables(self):
        original = service._publish
        def fail(tree, row, core, save):
            if row["path"] == "AGENTS.md":
                raise OSError("fixture synchronous failure")
            return original(tree, row, core, save)
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        with patch.object(service, "_publish", side_effect=fail), self.assertRaises(OSError):
            service.apply(plan)
        self.assertFalse((self.project / resources.LOCATOR).exists())
        self.assertFalse((self.project / ".agents/skills/xy-workflow").exists())
        self.assertFalse(service.status(self.state, self.project)["enabled"])
        journal = service._journal(self.state, self.project)[1]
        self.assertEqual("rolled_back", journal["phase"])
        self.assertTrue(journal["retained_nodes"])

    def test_recovery_refuses_post_failure_edit(self):
        original = service._publish
        def fail(tree, row, core, save):
            if row["path"] == "AGENTS.md":
                raise OSError("fixture interrupted installation")
            return original(tree, row, core, save)
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        with patch.object(service, "_publish", side_effect=fail), patch.object(service, "_restore", return_value=([{"path": ".", "reason": "fixture leaves prepared state"}], [])):
            with self.assertRaises(service.ActivationError):
                service.apply(plan)
        changed = self.project / resources.LOCATOR
        changed.write_bytes(b"user saved after failure\n")
        recovery = service.preview(self.state, self.project, "repair")
        self.assertTrue(recovery.summary["recovery"])
        with self.assertRaisesRegex(ValueError, "恢复含后续手改"):
            service.apply(recovery)
        self.assertEqual(b"user saved after failure\n", changed.read_bytes())

    def test_old_inode_later_save_is_retained_and_blocks_overwrite(self):
        self.enable()
        # 角色bootstrap现在跨core保持稳定；locator才是换版必变且有原inode归属
        # 的资源，故旧fd负控使用真实被隔离的locator，不能误把当前角色当旧备份。
        path = self.project / resources.LOCATOR
        with path.open("r+b") as old_inode:
            service.apply(service.preview(self.state, self.project, "use", binding=self.alternate.binding()))
            old_inode.seek(0)
            old_inode.write(b"late save into old inode\n")
            old_inode.truncate()
            old_inode.flush()
            os.fsync(old_inode.fileno())
        plan = service.preview(self.state, self.project, "disable")
        self.assertFalse(plan.summary["can_apply"])
        self.assertTrue(any("旧 inode" in row["reason"] for row in plan.summary["conflicts"]))
        self.assertIn(self.alternate.content_id, path.read_text())

    def test_prepared_recovery_restores_machine_binding_after_process_exit(self):
        # 真实子进程在最终 enabled 已写、applied 日志未写时退出，验证跨 FS 协议
        # 的恢复责任；它不是成功模拟，也没有启动任何宿主/模型。
        code = '''import json, os, sys
from pathlib import Path
from manager import runtime_service as service
original = service._write_private
def interrupted(tree, relative, body):
    if relative.startswith("transactions/") and json.loads(body).get("phase") == "applied":
        os._exit(73)
    return original(tree, relative, body)
service._write_private = interrupted
service.apply(service.preview(Path(sys.argv[1]), Path(sys.argv[2]), "enable", binding=json.loads(sys.argv[3])))
'''
        interrupted = subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8", "-c", code,
                                      str(self.state), str(self.project), json.dumps(self.core.binding())],
                                     cwd=PACK, capture_output=True, text=True, timeout=40)
        self.assertEqual(73, interrupted.returncode, interrupted.stdout + interrupted.stderr)
        self.assertEqual("prepared", service.status(self.state, self.project)["state"])
        self.assertIsNotNone(service.read_binding_record(self.state, self.project)[1])
        result = service.apply(service.preview(self.state, self.project, "repair"))
        self.assertTrue(result["recovered"])
        self.assertFalse(result["enabled"])
        self.assertIsNone(service.read_binding_record(self.state, self.project)[1])
        self.assertFalse((self.project / resources.LOCATOR).exists())

    def test_old_pin_bootstraps_without_the_current_core(self):
        self.enable()
        service.apply(service.preview(self.state, self.project, "use", binding=self.alternate.binding()))
        version = self.alternate.root.parent
        unavailable = self.workspace / "unavailable-current-core"
        # macOS 移动只读目录需在夹具边界暂时开放该目录 owner 写位；没有修改
        # 核心正文，测试完成后按不可变库的 0555 合同恢复，不能泛化为生产修复。
        version.chmod(0o700)
        version.rename(unavailable)
        unavailable.chmod(0o555)
        try:
            read = self.invoke("--binding", json.dumps(self.core.binding()), "read", "roles/xy-qa.md")
            self.assertEqual(0, read.returncode, read.stderr)
            self.assertEqual(store.read_core_source(self.core, "roles/xy-qa.md").decode("utf-8"), read.stdout)
        finally:
            unavailable.chmod(0o700)
            unavailable.rename(version)
            version.chmod(0o555)

    def test_parent_directory_swap_never_writes_outside(self):
        outside = self.workspace / ("outside-" + uuid.uuid4().hex[:10])
        outside.mkdir()
        self.put(outside, "project.yaml", b"outside must survive\n")
        original = service._publish
        swapped = False
        def swap(tree, row, core, save):
            nonlocal swapped
            result = original(tree, row, core, save)
            if not swapped and row["path"].startswith(".agent-workflow/"):
                swapped = True
                (self.project / ".agent-workflow").rename(self.project / "retained-runtime-parent")
                (self.project / ".agent-workflow").symlink_to(outside, target_is_directory=True)
            return result
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        with patch.object(service, "_publish", side_effect=swap), self.assertRaises(ValueError):
            service.apply(plan)
        self.assertEqual(["project.yaml"], sorted(path.name for path in outside.iterdir()))
        self.assertEqual(b"outside must survive\n", (outside / "project.yaml").read_bytes())
        self.assertIsNone(service.read_binding_record(self.state, self.project)[1])

    def test_legacy_notes_are_not_silently_migrated(self):
        config = resources.initial_config(resources.Resources(self.core.root, resources.json_bytes(self.core.binding()), self.core.label, self.core), self.project)
        config = config.replace(b"  plans: docs/plans/", b"  plans: docs/plans/\n  notes: docs/notes/")
        self.put(self.project, resources.CONFIG, config)
        with self.assertRaisesRegex(ValueError, "已废弃的文档配置"):
            service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.assertEqual(config, (self.project / resources.CONFIG).read_bytes())
        self.assertIsNone(service.read_binding_record(self.state, self.project)[1])

    def test_old_runtime_residue_is_retained_and_not_switched(self):
        self.put(self.project, ".agent-workflow/product/WORKFLOW.md", b"legacy\n")
        self.put(self.project, ".agent-workflow/.install-manifest.json",
                 resources.json_bytes({"schema_version": 1, "managed_files": {"product/WORKFLOW.md": hashlib.sha256(b"legacy\n").hexdigest()}}))
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.assertFalse(plan.summary["can_apply"])
        self.assertIn("旧自包含安装残留", plan.summary["conflicts"][0]["reason"])
        self.assertEqual(b"legacy\n", (self.project / ".agent-workflow/product/WORKFLOW.md").read_bytes())
        self.assertFalse((self.project / resources.LOCATOR).exists())


    def test_helper_timeout_reaps_only_its_own_process(self):
        self.enable()
        service.apply(service.preview(self.state, self.project, "use", binding=self.alternate.binding()))
        pid_file = self.project / "owned-helper-child.pid"
        invocation = bridge.python_helper(self.state, self.project, "lib/wait_probe.py", [str(pid_file)], binding=self.alternate.binding())
        with self.assertRaisesRegex(ValueError, "超时并终止"):
            bridge.run_helper(invocation, timeout=1)
        child = int(pid_file.read_text())
        # 只观察本夹具子进程状态；父进程先退出也不能留下忽略 TERM 的孙进程。
        # kill(pid, 0) 仅探测本次已登记 PID，无须读取宿主进程清单，也不发送
        # 实际信号；父进程回收之后给系统短暂时间完成已终止孙进程的清理。
        deadline = time.monotonic() + 2
        while True:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            if time.monotonic() >= deadline:
                os.kill(child, 9)  # 测试失败也只回收已记录归属的夹具进程，避免泄漏。
                self.fail("helper 超时后仍有本次孙进程运行")
            time.sleep(0.02)
        self.assertTrue(service.status(self.state, self.project)["enabled"])

    def model_changes(self):
        from lib import role_models
        from manager.service import Change
        relative = ".codex/agents/xy-qa.toml"
        before = (self.project / relative).read_bytes()
        selected = {"model": "receipt-model", "effort": "high"}
        config = (self.project / resources.CONFIG).read_bytes()
        updated = role_models.update(config.decode(), {"codex": {"xy-qa": selected}}).encode()
        return [Change(relative, before, role_models.patch_artifact(before, "codex", selected), 0o644),
                Change(resources.CONFIG, config, updated, 0o644)]

    def test_model_commit_read_preparation_keeps_callback_boundary_and_single_scan(self):
        """纯准备真实借一次reader；普通callback不借scope，双合同在建锁前拒绝。"""
        from manager import service as models
        self.enable()
        changes = self.model_changes()
        def persisted(root):
            return {str(path): (path.read_bytes(), path.stat().st_mode, path.stat().st_ino, path.stat().st_mtime_ns)
                    for path in root.rglob("*") if path.is_file() and not path.is_symlink()}
        for other_pin in (False, True):
            with self.subTest(other_pin=other_pin):
                seen = []
                def capture():
                    self.assertIsNotNone(store._READ_OPERATION.get())
                    core = store.load_core(self.core.binding(), self.state)
                    store.read_core_source(core, "lib/role_models.py")
                    if other_pin:store.load_core(self.alternate.binding(), self.state)
                    return (self.project / changes[1].relative).read_bytes()
                def recheck(snapshot):
                    self.assertIsNone(store._READ_OPERATION.get())
                    self.assertEqual(snapshot, (self.project / changes[1].relative).read_bytes())
                    self.assertEqual((2, 4) if other_pin else (1, 2), (scan.call_count, verify.call_count))
                    seen.append(True)
                with patch.object(store, "_scan", wraps=store._scan) as scan, \
                        patch.object(store, "_verify_snapshot", wraps=store._verify_snapshot) as verify:
                    identifier = models.commit(self.state, self.project, changes,
                        read_preparation=models.CommitReadPreparation(capture, recheck))
                self.assertTrue(identifier)
                self.assertEqual([True], seen)
                self.assertEqual((3, 6) if other_pin else (2, 4), (scan.call_count, verify.call_count))
                models.commit(self.state, self.project, models.prepare_restore(self.state, self.project, identifier))
                self.assertIsNone(store._READ_OPERATION.get())
        before = persisted(self.project), persisted(self.state)
        called = []
        def old_callback():
            self.assertIsNone(store._READ_OPERATION.get())
            called.append(True)
            raise OSError("original-before-write-contract")
        with self.assertRaisesRegex(OSError, "original-before-write-contract"):
            models.commit(self.state, self.project, changes, before_write=old_callback)
        self.assertEqual([True], called)
        self.assertEqual(before, (persisted(self.project), persisted(self.state)))
        bad_state = self.workspace / ("never-created-" + uuid.uuid4().hex)
        preparation = models.CommitReadPreparation(lambda: self.fail("不得capture"), lambda value: self.fail("不得recheck"))
        with self.assertRaisesRegex(ValueError, "不能同时"):
            models.commit(bad_state, self.project, changes, before_write=lambda: self.fail("不得callback"),
                          read_preparation=preparation)
        with self.assertRaises(TypeError):models.commit(bad_state, self.project, changes, read_preparation=object())
        with self.assertRaises(TypeError):models.CommitReadPreparation(None, lambda value: None)
        with self.assertRaises(ValueError):service.capture_ownership_sources(self.state, self.project, extra_paths=("../escape",))
        with self.assertRaises(TypeError):service.capture_ownership_sources(self.state, self.project, extra_paths="ambiguous-string")
        self.assertFalse(bad_state.exists())
        self.assertEqual(before, (persisted(self.project), persisted(self.state)))
        with store.core_read_operation() as parent:
            reader = parent.reader(self.core.binding(), self.state)
            with self.assertRaisesRegex(ValueError, "读取操作"):
                models.commit(bad_state, self.project, changes, read_preparation=preparation)
            self.assertFalse(bad_state.exists())
            self.assertFalse(parent._closed)
            self.assertIs(reader, parent.reader(self.core.binding(), self.state))
            reader.core_for(self.core.binding(), self.state)
            self.assertEqual(before, (persisted(self.project), persisted(self.state)))
        with store.core_read_operation() as closed:
            closed.reader(self.core.binding(), self.state)
            closed.finish()
            with self.assertRaises(ValueError):
                models.commit(bad_state, self.project, changes, read_preparation=preparation)
        self.assertFalse(bad_state.exists())
        self.assertIsNone(store._READ_OPERATION.get())

    def test_model_commit_read_preparation_rejects_finish_and_mutable_drift_before_write(self):
        """真实尾验/封口窗口故障全部零模型发布；原生来源及pyproject画像也必检。"""
        from lib.hosts.native_context import HostPaths, NativeContext
        from manager import central_runtime, native_agents, model_preferences as preferences, service as models
        home = self.workspace / ("phase-native-home-" + uuid.uuid4().hex)
        (home / ".codex").mkdir(parents=True)
        (home / ".codex/config.toml").write_text('model_catalog_json="models.json"\n')
        (home / ".codex/models.json").write_text(json.dumps({"models": [
            {"id": "phase-model", "supported_reasoning_levels": ["high", "max"]}]}))
        context = NativeContext(self.state, HostPaths.for_home(home, environment={}))
        central_runtime.apply(central_runtime.preview(self.state, binding=self.core.binding(), native_context=context))
        original_prepare, original_finish = service._prepare_native_edit_receipt, store.CoreReadOperation.finish
        source = self.core.root / "roles/xy-backend.md"
        source_body, source_mode = source.read_bytes(), stat.S_IMODE(source.stat().st_mode)
        for fault in ("core_tail", "config", "binding", "journal_before_capture", "managed", "retained", "directory", "native", "catalog", "profile"):
            with self.subTest(fault=fault):
                project = self.workspace / ("phase-project-" + uuid.uuid4().hex)
                project.mkdir()
                (project / "pyproject.toml").write_text('[project]\nname="phase-project"\nversion="0.1.0"\n')
                self.put(project, ".codex/config.toml", b"# existing user config\n")
                project_service.apply_project(project_service.preview_project(self.state, project, "add", enable=True,
                                                                              native_context=context))
                self.assertTrue(service.status(self.state, project)["new_task_allowed"])
                catalogs = preferences.load_catalogs(self.state, project, "codex", native_context=context)
                plan = preferences.preview(self.state, project, "codex", {"xy-backend": {"model": "phase-model"}},
                                           catalogs, native_context=context)
                self.assertTrue(plan.summary["can_apply"], plan.summary)
                self.assertFalse((project / ".codex/agents/xy-backend.toml").exists())
                machine = self.state / service._state_relative(project, "bindings")
                machine_before = machine.read_bytes()
                journal = self.state / service._state_relative(project, "transactions")
                journal_before = journal.read_bytes()
                config = project / resources.CONFIG
                config_before = config.read_bytes()
                _, record = service.read_binding_record(self.state, project)
                natives_before = native_agents.observe_sources(self.state, context.host_paths, "codex")
                # 归属marker名字由正式低层producer提供，不能猜路径令负控空转。
                from lib.hosts import native_agents as native_files
                native_owner = context.host_paths.codex / native_files.OWNER
                owner_before = native_owner.read_bytes()
                catalog_file = context.host_paths.codex / "models.json"
                catalog_before = catalog_file.read_bytes()
                armed, injected, preserved_edits, directory_os_blocked = [], [], [], []
                directory = project / ".agent-workflow"
                directory_identity = (directory.stat().st_dev, directory.stat().st_ino)
                directory_bytes = {path.relative_to(directory).as_posix(): path.read_bytes()
                                   for path in directory.rglob("*") if path.is_file() and not path.is_symlink()}
                def prepare(*args, **kwargs):
                    if fault == "journal_before_capture":mutate()
                    result = original_prepare(*args, **kwargs)
                    armed.append(True)
                    return result
                def mutate():
                    if injected:return
                    injected.append(True)
                    if fault == "core_tail":
                        source.chmod(source_mode | stat.S_IWUSR)
                        source.write_bytes(source_body + b"\nphase-core-mutation\n")
                    elif fault == "config":config.write_bytes(config_before + b"\n# external-config\n")
                    elif fault == "binding":machine.write_bytes(machine_before + b" ")
                    elif fault == "journal_before_capture":journal.write_bytes(journal_before + b" ")
                    elif fault == "managed":
                        path = project / next(path for path, row in record["managed"].items() if row["purpose"] == "block")
                        path.write_bytes(path.read_bytes() + b"\nexternal-managed-node\n")
                        preserved_edits.append((path, path.read_bytes()))
                    elif fault == "retained":
                        self.assertTrue(record["retained_nodes"], "必须有真实保留inode，不能跳过负控")
                        path = project / record["retained_nodes"][0]["path"]
                        path.write_bytes(path.read_bytes() + b"\nexternal-retained-node\n")
                        preserved_edits.append((path, path.read_bytes()))
                    elif fault == "directory":
                        try:
                            directory.rename(project / ".agent-workflow-external-held")
                        except OSError as error:
                            # Windows的既有锚定HANDLE没有SHARE_DELETE；内核可能先
                            # 阻止rename。这不是fresh guard拒绝，只接受实际精确的
                            # sharing/access错误，其它平台/错误原样失败，不模拟成功。
                            if sys.platform != "win32" or getattr(error, "winerror", None) not in {5, 32}:
                                raise
                            directory_os_blocked.append(error.winerror)
                            raise
                        directory.mkdir()
                        config.write_bytes(config_before)
                    elif fault == "native":native_owner.write_bytes(owner_before + b" ")
                    elif fault == "catalog":catalog_file.write_bytes(catalog_before.replace(b"phase-model", b"other-model"))
                    else:(project / "pyproject.toml").unlink()
                def finish(operation):
                    if armed and fault == "core_tail":mutate()
                    result = original_finish(operation)
                    if armed and fault != "core_tail":mutate()
                    return result
                try:
                    with patch.object(service, "_prepare_native_edit_receipt", prepare), \
                            patch.object(store.CoreReadOperation, "finish", finish), \
                            patch("manager.codex_models.query", side_effect=AssertionError("封口复核不得查询宿主")), \
                            self.assertRaises((ValueError, OSError) if fault == "directory" and sys.platform == "win32" else ValueError) as rejected:
                        preferences.apply(plan)
                    self.assertEqual([True], injected)
                    self.assertFalse((project / ".codex/agents/xy-backend.toml").exists())
                    self.assertEqual([], models.backups(self.state, project))
                    self.assertEqual(machine_before + (b" " if fault == "binding" else b""), machine.read_bytes())
                    self.assertEqual(journal_before + (b" " if fault == "journal_before_capture" else b""), journal.read_bytes())
                    if fault != "config":self.assertEqual(config_before, config.read_bytes())
                    else:self.assertEqual(config_before + b"\n# external-config\n", config.read_bytes())
                    for path, expected_bytes in preserved_edits:
                        self.assertEqual(expected_bytes, path.read_bytes(), "拒绝不能撤回外部managed/retained编辑")
                    if fault == "directory":
                        held = project / ".agent-workflow-external-held"
                        if directory_os_blocked:
                            self.assertIsInstance(rejected.exception, OSError)
                            self.assertEqual(directory_os_blocked, [rejected.exception.winerror])
                            self.assertIn(rejected.exception.winerror, {5, 32})
                            self.assertFalse(held.exists())
                            self.assertEqual(directory_identity, (directory.stat().st_dev, directory.stat().st_ino))
                            self.assertEqual(directory_bytes, {path.relative_to(directory).as_posix(): path.read_bytes()
                                             for path in directory.rglob("*") if path.is_file() and not path.is_symlink()})
                            # 异常退出原receipt/锁上下文后，再用真实rename成功证明
                            # 本轮无SHARE_DELETE句柄已经结清；不更改生产sharing。
                            directory.rename(held)
                            held.rename(directory)
                            self.assertEqual(directory_identity, (directory.stat().st_dev, directory.stat().st_ino))
                            print("WINDOWS_DIRECTORY_OS_BLOCKED_ZERO_PUBLICATION_HANDLES_RELEASED winerror=" + str(rejected.exception.winerror))
                        else:
                            self.assertIsInstance(rejected.exception, ValueError)
                            self.assertTrue(held.exists())
                            print("DIRECTORY_REPLACED_THEN_FRESH_GUARD_REJECTED platform=" + sys.platform)
                    if fault == "native":
                        self.assertNotEqual(natives_before, native_agents.observe_sources(self.state, context.host_paths, "codex"))
                        self.assertEqual(owner_before + b" ", native_owner.read_bytes())
                    if fault == "catalog":self.assertEqual(catalog_before.replace(b"phase-model", b"other-model"), catalog_file.read_bytes())
                    if fault == "core_tail":self.assertEqual(source_body + b"\nphase-core-mutation\n", source.read_bytes())
                    if fault == "profile":self.assertFalse((project / "pyproject.toml").exists())
                finally:
                    if fault == "core_tail" and injected:
                        source.chmod(source_mode | stat.S_IWUSR)
                        source.write_bytes(source_body)
                        source.chmod(source_mode)
                    native_owner.write_bytes(owner_before)
                    catalog_file.write_bytes(catalog_before)
                self.assertIsNone(store._READ_OPERATION.get())

    def test_model_receipt_syncs_real_existing_commit(self):
        from manager.service import commit, prepare_restore
        self.enable()
        changes = self.model_changes()
        identifier = commit(self.state, self.project, changes)
        self.assertTrue(identifier)
        self.assertTrue(service.status(self.state, self.project)["enabled"])
        self.assertEqual("receipt-model", tomllib.loads((self.project / changes[0].relative).read_text())["model"])
        # 真实逆补丁还原最初没有 role_models 区块的配置，不能用空 YAML 结构
        # 或归一空白替代精确原字节；恢复仍经同一 commit 自动收据入口。
        commit(self.state, self.project, prepare_restore(self.state, self.project, identifier))
        self.assertEqual(changes[1].before, (self.project / resources.CONFIG).read_bytes())
        self.assertTrue(service.status(self.state, self.project)["enabled"])
        service.apply(service.preview(self.state, self.project, "disable"))
        self.assertEqual(changes[1].before, (self.project / resources.CONFIG).read_bytes())

    def test_model_receipt_rejects_body_edits_and_reverts_with_commit_failure(self):
        from manager.service import Change, commit
        self.enable()
        changes = self.model_changes()
        forged = [Change(changes[0].relative, changes[0].before, changes[0].after + b"# unowned body edit\n", 0o644)]
        with self.assertRaisesRegex(ValueError, "模型字段以外"):
            with service.native_edit_receipt(self.state, self.project, forged):
                self.fail("非法正文变化不能进入 commit")
        config = changes[1]
        forged_config = [Change(resources.CONFIG, config.before, config.after + b"\n# non-model private edit\n", config.mode)]
        with self.assertRaisesRegex(ValueError, "role_models"):
            with service.native_edit_receipt(self.state, self.project, forged_config):
                self.fail("逆变换也不能接受模型区块以外的字节变化")
        original = service.read_binding_record(self.state, self.project)[0].payload
        with self.assertRaises(OSError):
            def fail_after_publish():
                raise OSError("fixture model verification failure")
            commit(self.state, self.project, changes, verify=fail_after_publish)
        self.assertEqual(original, service.read_binding_record(self.state, self.project)[0].payload)
        self.assertEqual(changes[0].before, (self.project / changes[0].relative).read_bytes())
        self.assertTrue(service.status(self.state, self.project)["enabled"])

    def configure_claude_guard(self):
        selected = resources.Resources(self.core.root, resources.json_bytes(self.core.binding()), self.core.label, self.core)
        body = resources.initial_config(selected, self.project)
        body = body.replace(b"block_writes_outside_working_directories: inherit", b"block_writes_outside_working_directories: true")
        self.put(self.project, resources.CONFIG, body)
        return body

    def test_explicit_claude_guard_merges_one_key_and_survives_inherit_disable(self):
        config = self.configure_claude_guard()
        original = {"permissions": {"allow": ["Read"]}, "hooks": {"CustomEvent": [{"command": "user hook"}]},
                    "mcpServers": {"fixture": {"token": "fixture-private-value"}}, "trust": {"native": "preserve"}}
        before = (json.dumps(original, ensure_ascii=False, indent=4) + "\n").encode()
        self.put(self.project, ".claude/settings.json", before)
        self.put(self.project, ".claude/settings.local.json", b'{"permissions":{"blockWritesOutsideWorkingDirectories":true},"user":"local"}\n')
        settings = self.project / ".claude/settings.json"
        settings.chmod(0o640)
        local = (self.project / ".claude/settings.local.json").read_bytes()
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.assertEqual(before, settings.read_bytes())
        self.assertNotIn("fixture-private-value", json.dumps(plan.summary))
        self.assertTrue(any(row["path"] == ".claude/settings.json" and row["purpose"] == "guard" for row in plan.summary["changes"]))
        result = service.apply(plan)
        self.assertTrue(result["enabled"], result["conflicts"])
        checked = self.invoke("check")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        expected = json.loads(json.dumps(original))
        expected["permissions"]["blockWritesOutsideWorkingDirectories"] = True
        observed = json.loads(settings.read_bytes())
        expected["hooks"] = observed["hooks"]
        self.assertEqual(expected, observed)
        self.assertEqual(0o640, settings.stat().st_mode & 0o7777)
        self.assertEqual(local, (self.project / ".claude/settings.local.json").read_bytes())
        record = service.read_binding_record(self.state, self.project)[1]
        self.assertNotIn(".claude/settings.json", record["managed"])
        self.assertNotIn("legacy_archive", record)
        self.put(self.project, ".claude/settings.local.json", b'{"permissions":{"blockWritesOutsideWorkingDirectories":false}}\n')
        self.assertFalse(service.status(self.state, self.project)["enabled"])
        with self.assertRaisesRegex(ValueError, "不能创建新任务"):
            bridge.resolve_runtime(self.state, self.project, new_task=True)
        self.put(self.project, ".claude/settings.local.json", local)
        # 用户后续修改其他设置不被中央“整文件归属”阻止，也不会被 repair 清回旧值。
        expected["mcpServers"]["second"] = {"command": "user-added"}
        later_hook = {"hooks": [{"type": "command", "command": "echo later-user"}]}
        expected["hooks"]["UserPromptSubmit"].append(later_hook)
        settings.write_bytes((json.dumps(expected, indent=2) + "\n").encode())
        self.assertTrue(service.status(self.state, self.project)["enabled"])
        (self.project / resources.CONFIG).write_bytes(config.replace(b"block_writes_outside_working_directories: true", b"block_writes_outside_working_directories: inherit"))
        retained = settings.read_bytes()
        service.apply(service.preview(self.state, self.project, "repair"))
        self.assertEqual(retained, settings.read_bytes())
        service.apply(service.preview(self.state, self.project, "disable"))
        removed = hook_install.merge_json(json.loads(retained), self.project / ".agent-workflow", self.project, "claude", "off")
        self.assertEqual(removed, json.loads(settings.read_bytes()))
        self.assertEqual([later_hook], json.loads(settings.read_bytes())["hooks"]["UserPromptSubmit"])
        self.assertIs(json.loads(settings.read_bytes())["permissions"]["blockWritesOutsideWorkingDirectories"], True)

    def test_claude_guard_rejects_conflicts_and_local_after_preview_change(self):
        self.configure_claude_guard()
        key = "blockWritesOutsideWorkingDirectories"
        for project_data, local_data in (({"permissions": {key: False}}, {}), ({"permissions": []}, {}),
                                         ({}, {"permissions": {key: False}}), ({}, {"permissions": "invalid"})):
            with self.subTest(project=project_data, local=local_data):
                before = json.dumps(project_data).encode()
                local = json.dumps(local_data).encode()
                self.put(self.project, ".claude/settings.json", before)
                self.put(self.project, ".claude/settings.local.json", local)
                with self.assertRaises(ValueError):
                    service.preview(self.state, self.project, "enable", binding=self.core.binding())
                self.assertEqual(before, (self.project / ".claude/settings.json").read_bytes())
                self.assertEqual(local, (self.project / ".claude/settings.local.json").read_bytes())
        self.put(self.project, ".claude/settings.json", b'{"permissions":{"allow":["Read"]}}\n')
        self.put(self.project, ".claude/settings.local.json", b"{}\n")
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        before = (self.project / ".claude/settings.json").read_bytes()
        self.put(self.project, ".claude/settings.local.json", json.dumps({"permissions": {key: False}}).encode())
        with self.assertRaisesRegex(ValueError, "预览后变化"):
            service.apply(plan)
        self.assertEqual(before, (self.project / ".claude/settings.json").read_bytes())
        self.assertIsNone(service.read_binding_record(self.state, self.project)[1])

    def test_assist_refuses_invalid_shared_settings_without_writes(self):
        """Hooks 与权限共享容器；即使保护选项为 inherit 也不能覆盖无效用户 JSON。"""
        original = b"user-owned invalid JSON must survive\n"
        self.put(self.project, ".claude/settings.json", original)
        with self.assertRaises(ValueError):
            service.preview(self.state, self.project, "enable", binding=self.core.binding())
        self.assertEqual(original, (self.project / ".claude/settings.json").read_bytes())
        self.assertIsNone(service.read_binding_record(self.state, self.project)[1])

    def delayed_hook_check(self, seconds):
        """只延迟真实thin check；受管shim/core保持原字节，不制造check结果。"""
        native = ('# user native trust\n[features]\nhooks = false\n'
                  '[agents] # keep user table comment\nenabled = false\nuser_owned = true\n'
                  '[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n'
                  'type = "command"\ncommand = "echo user"\n').encode()
        self.put(self.project, ".codex/config.toml", native)
        self.enable()
        group = hook_install.managed_json(tomllib.loads((self.project / ".codex/config.toml").read_text()), "codex")["SessionStart"][0]
        command = shlex.split(group.get("hooks", [group])[0]["command"])
        shim = self.project / ".agent-workflow/lib/workflow_hooks.py"
        tail = command[command.index(str(shim)) + 1:]
        scratch = self.workspace / ("hook-check-" + uuid.uuid4().hex[:10])
        scratch.mkdir()
        home = scratch / "home"
        home.mkdir()
        observed = scratch / "check-process.json"
        binding_out = scratch / "checked-binding.json"
        entry = self.project / resources.LAUNCHER
        delayed = scratch / "delayed-python-check"
        # Python包装器先经同一解释器入口运行，仅实际runtime.py check延迟；
        # helper保持原样执行。exec不留下shell/睡眠子孙，timeout必须回收这个PID。
        delay_code = ("import json,os,sys,time; from pathlib import Path; "
                      "args=sys.argv[1:]; "
                      "delayed=args == " + repr(["-I", "-B", "-X", "utf8", str(entry), "check"]) + "; "
                      "Path(" + repr(str(observed)) + ").write_text(json.dumps({'pid':os.getpid(),'argv':args})) if delayed else None; "
                      "time.sleep(" + repr(seconds) + ") if delayed else None; "
                      "os.execv(sys.executable,[sys.executable,*args])")
        delayed.write_text("#!/usr/bin/env bash\nexec bash " + shlex.quote(str(PACK / "lib/python_runtime.sh"))
                           + " -B -X utf8 -c " + shlex.quote(delay_code) + ' "$@"\n')
        delayed.chmod(0o700)
        environment = {key: value for key, value in os.environ.items() if key not in {
            "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT", "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"}}
        environment.update({"HOME": str(home), "CODEX_HOME": str(home / ".codex"),
                            "CLAUDE_CONFIG_DIR": str(home / ".claude"), "AGENT_WORKFLOW_STATE_DIR": str(self.state),
                            "AGENT_WORKFLOW_PYTHON": sys.executable})
        # driver只替换shim用于check的解释器路径；finally观察shim实际从check
        # 输出取得的pin，不提前设置pin，也不替换run/subprocess或任何资格校验。
        driver = """import json,os,runpy,sys
from pathlib import Path
wrapper,shim,binding_out = sys.argv[1:4]
sys.executable = wrapper
sys.argv = [shim,*sys.argv[4:]]
try:
    runpy.run_path(shim,run_name='__main__')
finally:
    Path(binding_out).write_text(json.dumps(os.environ.get('AGENT_WORKFLOW_RUNTIME_BINDING')))
"""
        hook_command = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8", "-c", driver,
                        str(delayed), str(shim), str(binding_out), *tail]
        payload = json.dumps({"cwd": str(self.project), "hook_event_name": "SessionStart", "source": "resume"})
        return delayed, entry, shim, observed, binding_out, environment, hook_command, payload

    def test_fresh_hook_waits_for_slow_valid_unpinned_check(self):
        delayed, entry, shim, observed, binding_out, env, command, payload = self.delayed_hook_check(2.5)
        before = shim.read_bytes()
        started = time.monotonic()
        checked = subprocess.run([str(delayed), "-I", "-B", "-X", "utf8", str(entry), "check"],
                                 cwd=self.project, env=env, capture_output=True, text=True, timeout=20)
        print("SLOW_VALID_CHECK", json.dumps({"elapsed": time.monotonic() - started, "returncode": checked.returncode,
                                             "stdout": checked.stdout, "stderr": checked.stderr}), flush=True)
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        self.assertEqual(self.core.binding(), json.loads(checked.stdout)["runtime_binding"])
        self.assertGreaterEqual(time.monotonic() - started, 2.5)
        print("SLOW_VALID_HOOK_COMMAND", json.dumps(command), flush=True)
        started = time.monotonic()
        result = subprocess.run(command, input=payload, cwd=self.project, env=env, capture_output=True, text=True, timeout=22)
        print("SLOW_VALID_HOOK", json.dumps({"elapsed": time.monotonic() - started, "returncode": result.returncode,
                                            "stdout": result.stdout, "stderr": result.stderr}), flush=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stderr)
        self.assertTrue(json.loads(result.stdout), result.stdout)
        self.assertEqual("SessionStart", json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"])
        self.assertEqual(self.core.binding(), json.loads(json.loads(binding_out.read_bytes())))
        self.assertEqual(["-I", "-B", "-X", "utf8", str(entry), "check"], json.loads(observed.read_bytes())["argv"])
        self.assertEqual(before, shim.read_bytes())

    def test_fresh_hook_timeout_is_neutral_and_reaps_check_process(self):
        _, entry, shim, observed, binding_out, env, command, payload = self.delayed_hook_check(30)
        before = shim.read_bytes()
        print("TIMEOUT_HOOK_COMMAND", json.dumps(command), flush=True)
        started = time.monotonic()
        result = subprocess.run(command, input=payload, cwd=self.project, env=env, capture_output=True, text=True, timeout=22)
        elapsed = time.monotonic() - started
        print("TIMEOUT_HOOK", json.dumps({"elapsed": elapsed, "returncode": result.returncode,
                                         "stdout": result.stdout, "stderr": result.stderr}), flush=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({}, json.loads(result.stdout))
        self.assertEqual("", result.stderr)
        self.assertIsNone(json.loads(binding_out.read_bytes()))
        self.assertGreaterEqual(elapsed, 9.5)
        self.assertLess(elapsed, 20)
        process = json.loads(observed.read_bytes())
        self.assertEqual(["-I", "-B", "-X", "utf8", str(entry), "check"], process["argv"])
        with self.assertRaises(ProcessLookupError):
            os.kill(process["pid"], 0)
        self.assertEqual(before, shim.read_bytes())

    def test_fresh_hooks_preserve_user_fields_run_protocol_and_follow_off_disable(self):
        """补足 fresh 中央路径的真实 Hook 消费，用户后续设置与签名所有权分别验证。"""
        native = ('# user native trust\n[features]\nhooks = false\n'
                  '[agents] # keep user table comment\nenabled = false\nuser_owned = true\n'
                  '[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n'
                  'type = "command"\ncommand = "echo user"\n').encode()
        self.put(self.project, ".codex/config.toml", native)
        user_claude = {"permissions": {"allow": ["Read"]}, "mcpServers": {"own": {"command": "user"}},
                       "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo user"}]}]}}
        self.put(self.project, ".claude/settings.json", json.dumps(user_claude).encode())
        self.put(self.project, ".agents/hooks.json", b'{"user":{"enabled":false,"Stop":[{"command":"echo keep"}]}}\n')
        self.enable()
        codex = tomllib.loads((self.project / ".codex/config.toml").read_text())
        claude = json.loads((self.project / ".claude/settings.json").read_bytes())
        antigravity = json.loads((self.project / ".agents/hooks.json").read_bytes())
        self.assertFalse(codex["features"]["hooks"])
        groups = {"codex": hook_install.managed_json(codex, "codex"),
                  "claude": hook_install.managed_json(claude, "claude"),
                  "antigravity": hook_install.managed_json(antigravity, "antigravity")}
        self.assertEqual([2, 3, 1], [sum(map(len, value.values())) for value in groups.values()])
        # 无任务 pin 时只为辅助提醒检查当前启用版；不会生成或替换任务记录。
        for host, events in groups.items():
            for event, rows in events.items():
                group = rows[0]
                command = group.get("hooks", [group])[0]["command"]
                payload = {"cwd": str(self.project), "hook_event_name": event, "source": "resume",
                           "tool_name": "Agent", "tool_input": {"subagent_type": "Explore"},
                           "workspacePaths": [str(self.project)], "conversationId": "fixture-session"}
                env = {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(self.state)}
                env.pop("AGENT_WORKFLOW_RUNTIME_BINDING", None)
                started = time.monotonic()
                # 黑盒外层预算覆盖shim自己的十秒上限，不先于生产超时逻辑中断。
                result = subprocess.run(shlex.split(command), input=json.dumps(payload), text=True,
                                        capture_output=True, env=env, cwd=self.project, timeout=20)
                elapsed = time.monotonic() - started
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                response = json.loads(result.stdout)
                if not response:
                    # 只在原非空断言失败后做一次只读诊断，不预热或重试Hook。
                    # 输出仅fixture身份/耗时/返回码和许可binding，不转储环境、
                    # 凭据或任意check正文；原失败断言仍执行，诊断不能掩盖失败。
                    diagnostic = {"host": host, "event": event, "project": str(self.project), "hook_elapsed": elapsed}
                    try:
                        checked = subprocess.run(["bash", str(self.project / resources.PYTHON_ENTRY), "-B", "-X", "utf8",
                                                  str(self.project / resources.LAUNCHER), "check"], cwd=self.project, env=env,
                                                 capture_output=True, text=True, timeout=15)
                        diagnostic["check_returncode"] = checked.returncode
                        try:
                            data = json.loads(checked.stdout)
                            diagnostic["check_enabled"] = data.get("enabled") is True
                            binding = data.get("runtime_binding")
                            if isinstance(binding, dict):
                                diagnostic["runtime_binding"] = {key: binding.get(key) for key in
                                                                ("protocol_version", "content_id", "manifest_sha256")}
                        except (ValueError, AttributeError):
                            diagnostic["check_invalid_response"] = True
                    except subprocess.TimeoutExpired:
                        diagnostic["check_timeout"] = True
                    except OSError:
                        diagnostic["check_launch_failed"] = True
                    print("FRESH_HOOK_FAILURE_DIAGNOSTIC", json.dumps(diagnostic), flush=True)
                self.assertTrue(response, (host, event, result.stdout, result.stderr))
        # 新增用户配置继续生效；切版、repair 和 disable 不能回退整个原生容器。
        claude["mcpServers"]["later"] = {"command": "later-user"}
        self.put(self.project, ".claude/settings.json", json.dumps(claude).encode())
        antigravity[hook_install.OWNER]["enabled"] = False
        antigravity["later-user"] = {"enabled": False}
        self.put(self.project, ".agents/hooks.json", json.dumps(antigravity).encode())
        with (self.project / ".codex/config.toml").open("ab") as stream:
            stream.write(b'\n[user_later]\nkeep = true\n')
        self.assertTrue(service.status(self.state, self.project)["enabled"])
        service.apply(service.preview(self.state, self.project, "use", binding=self.alternate.binding()))
        service.apply(service.preview(self.state, self.project, "repair"))
        self.assertFalse(json.loads((self.project / ".agents/hooks.json").read_bytes())[hook_install.OWNER]["enabled"])
        config = self.project / resources.CONFIG
        config.write_bytes(config.read_bytes().replace(b"mode: assist", b"mode: off"))
        service.apply(service.preview(self.state, self.project, "repair"))
        self.assertEqual({}, hook_install.managed_json(json.loads((self.project / ".claude/settings.json").read_bytes()), "claude"))
        self.assertEqual(b"", hook_install.managed_inline((self.project / ".codex/config.toml").read_bytes()))
        config.write_bytes(config.read_bytes().replace(b"mode: off", b"mode: assist"))
        service.apply(service.preview(self.state, self.project, "repair"))
        service.apply(service.preview(self.state, self.project, "disable"))
        after = json.loads((self.project / ".claude/settings.json").read_bytes())
        self.assertEqual({"command": "later-user"}, after["mcpServers"]["later"])
        self.assertEqual(user_claude["hooks"], after["hooks"])
        self.assertEqual({"enabled": False}, json.loads((self.project / ".agents/hooks.json").read_bytes())["later-user"])
        restored_native = tomllib.loads((self.project / ".codex/config.toml").read_text())
        self.assertTrue(restored_native["user_later"]["keep"])
        self.assertTrue(restored_native["agents"]["user_owned"])
        self.assertFalse(restored_native["agents"]["enabled"])
        self.assertEqual(store.read_core_source(self.core, "product/WORKFLOW.md"),
                         bridge.read_resource(self.state, self.project, "product/WORKFLOW.md", binding=self.core.binding()))
        # fresh + off 不能先创建再撤回 JSON 容器；用户原权限配置保持原始字节。
        off_project = self.workspace / ("off-" + uuid.uuid4().hex[:10])
        off_project.mkdir()
        off_config = resources.initial_config(resources.Resources(self.core.root, resources.json_bytes(self.core.binding()),
                                                                 self.core.label, self.core), off_project)
        self.put(off_project, resources.CONFIG, off_config.replace(b"mode: assist", b"mode: off"))
        permission = b'{ "permissions": { "deny": ["Bash(rm *)"] }, "user": true }\n'
        self.put(off_project, ".claude/settings.json", permission)
        off_plan = service.preview(self.state, off_project, "enable", binding=self.core.binding())
        self.assertEqual(permission, (off_project / ".claude/settings.json").read_bytes())
        off_result = service.apply(off_plan)
        self.assertTrue(off_result["enabled"], off_result["conflicts"])
        self.assertEqual(permission, (off_project / ".claude/settings.json").read_bytes())
        for relative in (".codex/hooks.json", ".agents/hooks.json"):
            self.assertFalse((off_project / relative).exists())

    def test_failed_fresh_enable_keeps_later_user_settings_and_usable_neutral_hook_bridge(self):
        """共享配置后加字段必须保留；失败不能顺手移除其中签名命令依赖的薄桥。"""
        self.put(self.project, ".claude/settings.json", b'{"permissions":{"allow":["Read"]}}\n')
        publish = service._publish
        command = []
        def user_save_then_fail(tree, row, core, save):
            result = publish(tree, row, core, save)
            if row["path"] == ".claude/settings.json":
                target = self.project / row["path"]
                data = json.loads(target.read_bytes())
                command.extend(shlex.split(data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]))
                data["mcpServers"] = {"later-user": {"command": "preserve"}}
                target.write_bytes(json.dumps(data).encode())
                raise OSError("fixture failure after user shared settings save")
            return result
        plan = service.preview(self.state, self.project, "enable", binding=self.core.binding())
        with patch.object(service, "_publish", side_effect=user_save_then_fail), self.assertRaisesRegex(ValueError, "后续手改"):
            service.apply(plan)
        data = json.loads((self.project / ".claude/settings.json").read_bytes())
        self.assertEqual({"command": "preserve"}, data["mcpServers"]["later-user"])
        self.assertEqual(["Read"], data["permissions"]["allow"])
        self.assertIsNone(service.read_binding_record(self.state, self.project)[1])
        self.assertEqual("conflict", service.status(self.state, self.project)["state"])
        # 原生命令仍可真正启动；未启用的项目只给中性协议结果，不创建任务或猜 pin。
        environment = {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(self.state)}
        environment.pop("AGENT_WORKFLOW_RUNTIME_BINDING", None)
        result = subprocess.run(command, input="{}", text=True, env=environment, capture_output=True,
                                cwd=self.project, timeout=8)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({}, json.loads(result.stdout))

    def test_incompatible_fixed_bridge_is_rolled_back_before_enabled(self):
        source = self.source / "lib/runtime_bridge.py"
        original = source.read_bytes()
        source.write_bytes(original + b'\nraise ValueError("fixture incompatible bridge protocol")\n')
        try:
            incompatible = store.import_core(self.source, self.state)
        finally:
            source.write_bytes(original)
        plan = service.preview(self.state, self.project, "enable", binding=incompatible.binding())
        with self.assertRaisesRegex(ValueError, "无法消费本机项目协议"):
            service.apply(plan)
        self.assertFalse(service.status(self.state, self.project)["enabled"])
        self.assertIsNone(service.read_binding_record(self.state, self.project)[1])
        self.assertFalse((self.project / resources.LOCATOR).exists())
        self.assertEqual("rolled_back", service._journal(self.state, self.project)[1]["phase"])


if __name__ == "__main__":
    unittest.main()


class NativeBindingTransportContractTest(unittest.TestCase):
    """传输和初读闭包的可移植负控，原生消费者另由 Windows 节点执行。"""

    def test_encoded_pin_is_bounded_unique_canonical_and_normalized_before_admission(self):
        import base64
        from lib.runtime_pins import decode_binding_b64
        binding = {"protocol_version": 1, "content_id": "a" * 64, "manifest_sha256": "a" * 64}
        encoded = base64.b64encode(json.dumps(binding).encode()).decode()
        self.assertEqual(binding, decode_binding_b64(encoded))
        namespace = {"__name__": "_launcher_contract", "__file__": str(PACK / ".agent-workflow/runtime.py")}
        exec(compile(resources.launcher_source(), "<generated-launcher>", "exec"), namespace)
        argv = namespace["normalize_binding"](["--binding-b64", encoded, "helper", "lib/task_graph_cli.py", "--root", ".", "init"])
        self.assertEqual(binding, json.loads(argv[1]))
        self.assertTrue(namespace["helper_creates_task"](argv[2:]))
        invalid = [encoded + "\n", "eA==", base64.b64encode(b"x" * 4097).decode(),
                   base64.b64encode(b'{"protocol_version":1,"protocol_version":1}').decode(),
                   base64.b64encode(b"\xff").decode()]
        for value in invalid:
            with self.subTest(value_length=len(value)), self.assertRaises(ValueError):
                decode_binding_b64(value)
            with self.assertRaises(ValueError):
                namespace["normalize_binding"](["--binding-b64", value, "check"])
        for flags in (["--binding-b64"], ["--binding-b64", encoded, "--binding", json.dumps(binding), "check"]):
            with self.assertRaises(ValueError):
                namespace["normalize_binding"](flags)
        for flags in (["--binding", json.dumps(binding), "--binding", json.dumps(binding), "check"],
                      ["--binding-b64", encoded, "--binding-b64", encoded, "check"],
                      ["--binding-unknown", encoded, "check"]):
            with self.assertRaises(SystemExit) as rejected:
                bridge.main(flags, project=PACK, state=PACK / "unused-state")
            self.assertEqual(2, rejected.exception.code)

    def test_generated_windows_entries_reject_nonisolated_before_project_imports(self):
        with tempfile.TemporaryDirectory(prefix="central-isolation-") as raw:
            root = Path(raw).resolve()
            marker = root / "unexpected-import"
            for name in ("ctypes", "pathlib", "argparse", "hashlib"):
                (root / (name + ".py")).write_text("open('unexpected-import','w').write('executed')\nraise RuntimeError('project module executed')\n")
            sources = [resources.launcher_source(), resources.hook_bridge_source(),
                       resources.windows_bootstrap_source({"path": "C:/managed/windows_process.py", "sha256": "a" * 64})]
            for index, body in enumerate(sources):
                target = root / ("entry" + str(index) + ".py")
                target.write_bytes(body)
                # 将平台标识改为 win32 只用于证明最前置纯 guard，完全不运行原生 API。
                code = "import sys; sys.platform='win32'; exec(compile(open(sys.argv[1],'rb').read(),sys.argv[1],'exec'),{'__name__':'__main__','__file__':sys.argv[1]})"
                result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", code, str(target)],
                                        cwd=root, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("isolated", result.stderr)
                self.assertFalse(marker.exists(), "project import ran before isolated guard")


@unittest.skipUnless(os.name == "nt", "requires real native Windows; never count this skip as acceptance")
class WindowsCentralComposedNativeTest(unittest.TestCase):
    """真实核心/中央记录/项目薄桥/PS7 Hook 的组合；不模拟 Win32 成功。"""

    def test_source_install_detached_pin_helper_hooks_and_admission(self):
        import base64
        import time
        from lib.hosts.native_context import HostPaths, NativeContext
        from lib.windows_fs import assert_private
        from lib.hosts.windows_hook_command import validate_powershell
        from manager import central_runtime
        # 只观测真实组合入口：累计时间定位整体阶段，增量时间定位相邻调用；
        # 立即 flush 让中途异常或超时仍保留最后完成位置。时间不参与断言、
        # 重试或 deadline 计算，既有 Hook/子进程预算与业务步骤完全沿用。
        started = previous = time.monotonic()
        def mark_stage(name):
            nonlocal previous
            now = time.monotonic()
            print(f"NATIVE_CENTRAL_STAGE name={name} elapsed_s={now - started:.3f} delta_s={now - previous:.3f}", flush=True)
            previous = now
        mark_stage("begin")
        with tempfile.TemporaryDirectory(prefix="central-native-") as raw:
            workspace = Path(raw).resolve()
            state, source, project = workspace / "state", workspace / "source", workspace / "project 中文 space"
            source.mkdir(); project.mkdir()
            # 偏好组合验证针对真实后端工程；空目录画像只有通用 QA/UIUX 角色。
            # 明确清单让发现器按实际工程事实启用后端，绝不让全局角色安装或
            # 本次偏好请求反向补齐画像；空画像拒绝由偏好专项回归单独覆盖。
            user_file = project / "pyproject.toml"
            user_file.write_text('[project]\nname="native-central-fixture"\nversion="0.1.0"\n', encoding="utf-8")
            user_before = user_file.read_bytes()
            user_sha = hashlib.sha256(user_before).hexdigest()
            self.assertFalse((project / "AGENTS.md").exists())
            # 此唯一 source fixture 为验收“移除来源后仍可运行”而存在；不移动真实仓库，
            # 不复制 state/业务目录/个人 Skills，不按重试再造候选。只复制正式 core 边界。
            for directory in store.CORE_DIRECTORIES:
                shutil.copytree(PACK / directory, source / directory,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            for name in store.SETUP_FILES:
                shutil.copyfile(PACK / name, source / name)
            context = NativeContext.for_state(state, host_paths=HostPaths.for_home(workspace / "host-home", environment={}))
            validate_powershell()
            from manager.release import source_version, describe
            # 仅记录公开版本源的实际字节，回证原生 checkout 行尾，不改来源或断言。
            print("NATIVE_VERSION_BYTES=" + (source / "product/VERSION").read_bytes().hex())
            version = source_version(source)
            self.assertIn("awf-cli " + version, describe())
            # 真实模型目录只位于该request的显式host-home，不读取个人账户/provider。
            codex_home = context.host_paths.codex
            codex_home.mkdir(parents=True)
            (codex_home / "config.toml").write_text('model_catalog_json="models.json"\n', encoding="utf-8")
            (codex_home / "models.json").write_text(json.dumps({"models": [
                {"id": "fixture-model", "supported_reasoning_levels": ["high", "max"]},
                {"id": "project-model", "supported_reasoning_levels": ["high", "max"]}]}), encoding="utf-8")
            mark_stage("fixture_ready")
            core = store.import_core(source, state)
            self.assertEqual(version, core.label)
            mark_stage("import_complete")
            central_proposal = central_runtime.preview(state, binding=core.binding(), native_context=context)
            mark_stage("central_preview_complete")
            central_runtime.apply(central_proposal)
            mark_stage("central_apply_complete")
            proposal = project_service.preview_project(state, project, "add", enable=True,
                                                       source_root=source, native_context=context)
            self.assertTrue(proposal.summary["can_apply"], proposal.summary)
            mark_stage("project_preview_complete")
            from tests.test_windows_fs_native import native_skill_observation
            actual_stage, actual_installed = service._register_stage, service._register_installed
            stage_observation = {}
            observed_skills = 0
            def observe_stage(row, staged):
                nonlocal observed_skills
                result = actual_stage(row, staged)
                if staged.kind == "link":
                    # 仅观测真实完整安装中的当前 stage，叶名仍来自原受管路径。
                    # 原函数先执行、返回值原样交回；不伪造 native 成功或改变授权。
                    skill = Path(row["path"]).name
                    stage_observation.clear()
                    stage_observation["path"] = row["path"]
                    stage_observation["node"] = {"identity": staged.identity, "mode": staged.mode, "security": staged.security}
                    stage_observation["facts"] = native_skill_observation(project / row["stage"] / skill, skill)
                    observed_skills += 1
                    # 完整成功布局已有真实原始证据；本轮只打印首条与总数。
                    # 每条最新 before 事实仍保留，异常时与实际发布值完整输出。
                    if observed_skills == 1:
                        print("NATIVE_COMPOSED_SKILL_STAGE " + json.dumps(stage_observation, sort_keys=True), flush=True)
                return result
            def observe_installed(row, current):
                from manager.runtime_state import same_published_node
                expected_stage = resources.Node.from_value(row["after"])
                if current.kind == "link" and not same_published_node(current, expected_stage):
                    report = {"path": row["path"], "stage": stage_observation,
                              "expected_node": {"identity": expected_stage.identity, "mode": expected_stage.mode, "security": expected_stage.security},
                              "actual_node": {"identity": current.identity, "mode": current.mode, "security": current.security},
                              "actual_handle": native_skill_observation(project / row["path"], Path(row["path"]).name)}
                    print("NATIVE_COMPOSED_SKILL_MISMATCH " + json.dumps(report, sort_keys=True), flush=True)
                return actual_installed(row, current)
            with patch.object(service, "_register_stage", side_effect=observe_stage), \
                    patch.object(service, "_register_installed", side_effect=observe_installed):
                applied = project_service.apply_project(proposal)
            mark_stage("project_apply_complete")
            self.assertTrue((project / "AGENTS.md").is_file())
            self.assertEqual(user_before, user_file.read_bytes())
            self.assertEqual(user_sha, hashlib.sha256(user_file.read_bytes()).hexdigest())
            print("NATIVE_COMPOSED_SKILL_STAGE_COUNT " + str(observed_skills), flush=True)
            # 只投影真实fixture状态字段，不输出配置正文、模型目录、环境或凭据。
            # can_apply/未抛异常不等于启用健康；先留父状态再观察原薄桥的门禁。
            status_fields = ("state", "enabled", "declared_enabled", "resources_healthy", "new_task_allowed",
                             "management_write_allowed", "runtime_binding", "effective_binding", "policy",
                             "pending_transaction", "issues", "conflicts")
            def report_status(label, value):
                print("NATIVE_CENTRAL_STATUS " + json.dumps({"stage": label,
                      "status": {key: value.get(key) for key in status_fields}}, ensure_ascii=False, sort_keys=True), flush=True)
            report_status("apply_return", applied)
            parent_status = service.status(state, project)
            report_status("parent_after_apply", parent_status)
            binding_node, _ = service.read_binding_record(state, project)
            self.assertEqual(64, len(binding_node.security))
            assert_private(state / service._state_relative(project, "bindings"))
            pin = base64.b64encode(json.dumps(core.binding()).encode()).decode()
            environment = {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(state)}
            for name in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT", "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"):
                environment.pop(name, None)
            def invoke(*args, timeout=40):
                command = [sys.executable, "-I", "-B", "-X", "utf8", str(project / resources.LAUNCHER), *args]
                # 默认 check/read/helper 仍为40秒。仅下方实际写图 init 显式
                # 使用150秒外层验收预算：既有生产子预算120秒＋自举余量30秒。
                # 记录实际argv/耗时/退出，不重试、不吞超时，也不改生产预算。
                observed = timeout != 40
                started, outcome = time.monotonic(), "exception"
                if observed:
                    print("NATIVE_CENTRAL_INVOKE " + json.dumps({"command": command, "outer_timeout_s": timeout,
                          "helper_timeout_s": 120}, ensure_ascii=False, sort_keys=True), flush=True)
                try:
                    result = subprocess.run(command, cwd=project, env=environment, capture_output=True, timeout=timeout)
                    outcome = result.returncode
                    return result
                except subprocess.TimeoutExpired:
                    outcome = "outer_timeout"
                    raise
                finally:
                    if observed:
                        print("NATIVE_CENTRAL_INVOKE_RESULT " + json.dumps({"outer_timeout_s": timeout,
                              "elapsed_s": round(time.monotonic() - started, 3), "exit": outcome}, sort_keys=True), flush=True)
            checked = invoke("check")
            if checked.returncode:
                # 原调用与其FAIL必须保留。此额外只读进程仍经同一-I薄入口完整
                # 验核心，profile仅观察真实status正常返回，不改返回值或gate。
                # 先不import任何core；stdlib runpy保持同一__file__/argv语义。
                diagnostic_code = '''import json,runpy,sys
entry = sys.argv[1]
fields = ''' + repr(status_fields) + '''
def observe(frame, event, value):
    if (event == "return" and frame.f_code.co_name == "status"
            and frame.f_code.co_filename.replace("\\\\", "/").endswith("/manager/runtime_service.py")
            and isinstance(value, dict)):
        print("NATIVE_THIN_STATUS " + json.dumps({key: value.get(key) for key in fields},
              ensure_ascii=False, sort_keys=True), file=sys.stderr, flush=True)
sys.argv = [entry, "check"]
sys.setprofile(observe)
try:
    runpy.run_path(entry, run_name="__main__")
finally:
    sys.setprofile(None)
'''
                try:
                    diagnostic = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", diagnostic_code,
                                                 str(project / resources.LAUNCHER)], cwd=project, env=environment,
                                                capture_output=True, timeout=40)
                    print("NATIVE_THIN_STATUS_DIAGNOSTIC " + json.dumps({"returncode": diagnostic.returncode,
                          "stdout": diagnostic.stdout.decode("utf-8", errors="replace"),
                          "stderr": diagnostic.stderr.decode("utf-8", errors="replace")}, ensure_ascii=False, sort_keys=True), flush=True)
                except subprocess.TimeoutExpired:
                    print("NATIVE_THIN_STATUS_DIAGNOSTIC timeout_s=40; original check failure retained", flush=True)
            self.assertEqual(0, checked.returncode, checked.stderr.decode("utf-8", errors="replace"))
            self.assertTrue(applied["enabled"], applied)
            self.assertTrue(parent_status["enabled"], parent_status)
            self.assertTrue(parent_status["new_task_allowed"], parent_status)
            self.assertEqual(core.binding(), json.loads(checked.stdout)["runtime_binding"])
            mark_stage("thin_check_complete")
            expected = store.read_core_source(core, "product/GLOBAL_CONSTRAINTS.md")
            shutil.rmtree(source)
            self.assertFalse(source.exists())
            # 项目模块探针不得抢先覆盖 stdlib；仅已验证的 core helper 根允许导入。
            for name in ("ctypes", "pathlib", "argparse"):
                (project / (name + ".py")).write_text("raise RuntimeError('project module executed')\n", encoding="utf-8")
                (project / ".agent-workflow/lib" / (name + ".py")).write_text("raise RuntimeError('thin project module executed')\n", encoding="utf-8")
            read = invoke("--binding-b64", pin, "read", "product/GLOBAL_CONSTRAINTS.md")
            self.assertEqual((0, expected), (read.returncode, read.stdout), read.stderr)
            mark_stage("detached_read_complete")
            fingerprints = project / "fingerprints.json"
            # 此输入属于工程用户文件，停用后仍须逐字节保留。使用实际原像的
            # expected hash映射做核对，不能用列表模式只计算新的摘要后声称一致。
            fingerprints.write_text(json.dumps({"pyproject.toml": user_sha}), encoding="utf-8")
            queried = invoke("--binding-b64", pin, "helper", "lib/task_graph_cli.py", "fingerprints",
                             "--root", str(project), "--input", str(fingerprints))
            self.assertEqual(0, queried.returncode, queried.stderr)
            self.assertTrue(json.loads(queried.stdout)["matched"])
            self.assertEqual(1, json.loads(queried.stdout)["checked"])
            mark_stage("thin_fingerprints_complete")
            # 复用既有合法 Full 决策，只裁剪为内置工程规范；不补审批、不复制
            # 规范正文，也不替换新任务门。实际薄桥/Windows 协调锁和私有发布必须
            # 在来源已移除后真正生成新图，不能用 fingerprints 查询成功代替 init。
            from tests.test_task_graph_init import BUILTIN_ENGINEERING, decisions
            init_decisions = decisions()
            init_decisions["standards"].update(required_engineering_rule_ids=["eng-common-005"],
                leaves=[{"path": BUILTIN_ENGINEERING, "domain": "engineering", "rule_ids": ["eng-common-005"]}])
            init_decisions["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
            decision_path, graph_path = project / "native-init-decisions.json", project / "native-enabled-task.json"
            decision_path.write_text(json.dumps(init_decisions, ensure_ascii=False), encoding="utf-8")
            initialized = invoke("--binding-b64", pin, "helper", "lib/task_graph_cli.py", "init",
                                 "--root", str(project), "--input", str(decision_path), "--output", str(graph_path), timeout=150)
            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            self.assertTrue(graph_path.is_file())
            summary, graph_body = json.loads(initialized.stdout), graph_path.read_bytes()
            self.assertTrue(summary["initialized"])
            self.assertEqual(str(graph_path), summary["path"])
            self.assertEqual(hashlib.sha256(graph_body).hexdigest(), summary["sha256"])
            graph = json.loads(graph_body)
            self.assertEqual(2, graph["schema_version"])
            self.assertEqual({"protocol_version", "content_id", "manifest_sha256"}, set(graph["runtime_binding"]))
            self.assertEqual(core.binding(), store.validate_binding(graph["runtime_binding"]))
            self.assertEqual([], graph["approved_gates"])
            self.assertEqual("DECLARED", graph["tasks"][0]["state"])
            mark_stage("thin_init_complete")
            print("NATIVE_ENABLED_INIT: actual isolated thin bridge persisted schema2 graph with strict task pin and explicit approvals")
            # Full 必经消费者沿同一个已移除来源的项目/pin 调用，不直接导入
            # helper 替代薄桥。请求只属于本夹具；先证明保留项清理，再证明
            # 已暂停 HTML 不污染该请求，最后按新预览清理，不使用 --all。
            mark_stage("full_helpers_begin")
            request_id = "native-full-consumer"
            def scratch_call(command, *options):
                result = invoke("--binding-b64", pin, "helper", "lib/task_graph_cli.py", command,
                                "--root", str(project), "--request-id", request_id, *options)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                return json.loads(result.stdout)
            allocated = scratch_call("scratch")
            reused = scratch_call("scratch")
            self.assertFalse(allocated["reused"])
            self.assertTrue(reused["reused"])
            self.assertEqual(allocated["scratch_dir"], reused["scratch_dir"])
            scratch = Path(allocated["scratch_dir"])
            self.assertTrue(scratch.is_dir())
            mark_stage("scratch_reuse_complete")
            keep_body, build_body = b"native full evidence\n", b"native temporary build\n"
            (scratch / "keep.log").write_bytes(keep_body)
            (scratch / "build.tmp").write_bytes(build_body)
            preview = scratch_call("cleanup-scratch", "--dry-run", "--keep", "keep.log")
            self.assertEqual("metadata", preview["snapshot_kind"])
            self.assertEqual((1, 0, len(build_body)),
                             tuple(preview[key] for key in ("planned_files", "planned_directories", "planned_logical_bytes")))
            cleaned = scratch_call("cleanup-scratch", "--keep", "keep.log", "--expect-sha256", preview["snapshot_sha256"])
            self.assertEqual("applied", cleaned["status"])
            self.assertEqual((1, 0, len(build_body)),
                             tuple(cleaned[key] for key in ("removed_files", "removed_directories", "removed_logical_bytes")))
            self.assertEqual(keep_body, (scratch / "keep.log").read_bytes())
            self.assertEqual({"keep.log"}, {path.name for path in scratch.iterdir()})
            mark_stage("scratch_keep_cleanup_complete")
            plans = project / "docs/plans"
            plans.mkdir(parents=True, exist_ok=True)
            logical = "platforms/shared/skills/xy-code-standards/references/rules.md"
            markdown, html = plans / "native-full.md", plans / "native-full.html"
            markdown_body = ("# Native Full consumer\n\n[Rules](../../.agent-workflow/" + logical + ")\n").encode("utf-8")
            markdown.write_bytes(markdown_body)
            # 公开 render/check 已暂停，仍通过已移除来源后的真实固定薄桥调用。
            # 首轮证明不会生成新页面，第二轮放入历史页面证明不会覆盖；两轮均
            # 核对 Markdown、请求根与项目路径集合，不以一次错误码代替副作用验收。
            page = b"<!doctype html><title>retained historical plan</title>\n"
            for command in ("render", "check"):
                if command == "check":
                    html.write_bytes(page)
                before_paths = set(project.rglob("*"))
                options = ("--request-id", request_id) if command == "render" else ()
                paused = invoke("--binding-b64", pin, "helper", "lib/documents/requirement_html.py", command,
                                "--project", str(project), "--source", "docs/plans/native-full.md", *options)
                self.assertEqual(2, paused.returncode, paused.stdout + paused.stderr)
                self.assertEqual(b"", paused.stdout)
                self.assertIn("HTML 生成功能已暂停".encode("utf-8"), paused.stderr)
                self.assertEqual(markdown_body, markdown.read_bytes())
                self.assertEqual(before_paths, set(project.rglob("*")))
                self.assertEqual({"keep.log"}, {path.name for path in scratch.iterdir()})
                self.assertEqual(keep_body, (scratch / "keep.log").read_bytes())
                if command == "render":
                    self.assertFalse(html.exists())
                else:
                    self.assertEqual(page, html.read_bytes())
                mark_stage("html_" + command + "_suspended")
            self.assertEqual(keep_body, (scratch / "keep.log").read_bytes())
            final_preview = scratch_call("cleanup-scratch", "--dry-run")
            # keep 阶段为保留日志而留下请求根；最终不再指定 keep，快照中的
            # 相对路径空串（展示为“.”）也要删除，所以还包含一个请求根目录。
            # 这不是 HTML 生成的额外目录，不能把目录数误设为零或删掉保留日志。
            self.assertEqual((1, 1, len(keep_body)), tuple(final_preview[key] for key in (
                "planned_files", "planned_directories", "planned_logical_bytes")))
            final = scratch_call("cleanup-scratch", "--expect-sha256", final_preview["snapshot_sha256"])
            self.assertEqual("applied", final["status"])
            for metric in ("files", "directories", "logical_bytes"):
                self.assertEqual(final_preview["planned_" + metric], final["removed_" + metric])
            self.assertFalse(scratch.exists())
            self.assertEqual(markdown_body, markdown.read_bytes())
            self.assertEqual(page, html.read_bytes())
            mark_stage("scratch_final_cleanup_complete")
            settings = json.loads((project / ".claude/settings.json").read_bytes())
            group = hook_install.managed_json(settings, "claude")["SessionStart"][0]
            command = group["hooks"][0]["command"]
            mark_stage("hook_begin")
            hook_started = time.monotonic()
            hook = subprocess.run(command, shell=True, cwd=project, env=environment,
                                  input=json.dumps({"cwd": str(project), "hook_event_name": "SessionStart", "source": "resume"}).encode(),
                                  capture_output=True, timeout=20)
            mark_stage("hook_return")
            # 仅记录返回边界/协议字节数，区分以后失败在启动、监督还是业务响应；
            # 不转储payload、提醒正文、环境或用户配置，时间也不参与重试/预算。
            print("NATIVE_CENTRAL_HOOK_RESULT " + json.dumps({"elapsed_s": round(time.monotonic() - hook_started, 3),
                  "returncode": hook.returncode, "stdout_bytes": len(hook.stdout), "stderr_bytes": len(hook.stderr)},
                  sort_keys=True), flush=True)
            self.assertEqual(0, hook.returncode, hook.stderr)
            response = json.loads(hook.stdout)
            self.assertIn("hookSpecificOutput", response, "enabled real Hook must execute beyond the neutral timeout path")
            mark_stage("hook_complete")
            from manager import model_preferences, service as model_service
            self.assertIn("xy-backend", model_preferences.roles(state, project, "codex", native_context=context),
                          "组合夹具必须先证明后端角色来自实际工程画像")
            def save_preference(target, edits):
                catalogs = model_preferences.load_catalogs(state, target, "codex", native_context=context)
                plan = model_preferences.preview(state, target, "codex", edits, catalogs, native_context=context)
                self.assertTrue(plan.summary["can_apply"], plan.summary)
                result = model_preferences.apply(plan)
                self.assertTrue(result["applied"], result)
                self.assertIsNotNone(result["backup_id"], result)
                return result
            save_preference(None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
            save_preference(project, {"xy-backend": {"model": "project-model"}})
            local_role = project / ".codex/agents/xy-backend.toml"
            self.assertEqual("project-model", tomllib.loads(local_role.read_text(encoding="utf-8"))["model"])
            save_preference(None, {"xy-backend": {"effort": "max"}})
            mark_stage("preference_overrides_complete")
            reset = model_preferences.reset_platform(state, project, "codex", native_context=context)
            self.assertTrue(reset.summary["can_apply"], reset.summary)
            reset_result = model_preferences.apply(reset)
            self.assertFalse(local_role.exists())
            restored_model = model_service.prepare_restore(state, project, reset_result["backup_id"])
            model_service.commit(state, project, restored_model, native_context=context)
            self.assertEqual("project-model", tomllib.loads(local_role.read_text(encoding="utf-8"))["model"])
            mark_stage("preference_restore_complete")
            model_preferences.apply(model_preferences.reset_platform(state, project, "codex", native_context=context))
            self.assertFalse(local_role.exists())
            self.assertEqual({"model": "fixture-model", "effort": "max"},
                             model_service.role_settings(project, "codex", "xy-backend", state=state, native_context=context))
            mark_stage("preference_reset_complete")
            project_service.apply_project(project_service.preview_project(state, project, "disable", native_context=context))
            mark_stage("project_disable_complete")
            # 本夹具启用前无用户AGENTS，停用应撤下工作流独占入口；pyproject
            # 同时承担工程画像和固定pin只读消费的输入，必须保留原bytes/hash。
            self.assertFalse((project / "AGENTS.md").exists())
            self.assertEqual(user_before, user_file.read_bytes())
            self.assertEqual(user_sha, hashlib.sha256(user_file.read_bytes()).hexdigest())
            self.assertNotEqual(0, invoke("check").returncode)
            self.assertEqual((0, expected), (lambda result: (result.returncode, result.stdout))(
                invoke("--binding-b64", pin, "read", "product/GLOBAL_CONSTRAINTS.md")))
            old_query = invoke("--binding-b64", pin, "helper", "lib/task_graph_cli.py", "fingerprints",
                               "--root", str(project), "--input", str(fingerprints))
            self.assertEqual(0, old_query.returncode, old_query.stderr)
            self.assertTrue(json.loads(old_query.stdout)["matched"])
            self.assertEqual(1, json.loads(old_query.stdout)["checked"])
            self.assertNotEqual(0, invoke("--binding-b64", pin, "helper", "lib/task_graph_cli.py", "init").returncode)
            unknown = {"protocol_version": 1, "content_id": "f" * 64, "manifest_sha256": "f" * 64}
            self.assertNotEqual(0, invoke("--binding-b64", base64.b64encode(json.dumps(unknown).encode()).decode(),
                                        "read", "product/GLOBAL_CONSTRAINTS.md").returncode)
            mark_stage("disabled_admission_checks_complete")
            # 版本差异夹具仅作第二个切版目标；首次安装/薄桥/Hook/helper/偏好始终
            # 由上面的真实完整 core 证明，不能用最小夹具代替组合入口验收。
            alternate_source = workspace / "alternate-source"
            alternate_source.mkdir()
            make_alternate_source(alternate_source)
            alternate = store.import_core(alternate_source, state)
            project_service.apply_project(project_service.preview_project(state, project, "enable", native_context=context))
            pinned, disabled = workspace / "pinned-project", workspace / "disabled-project"
            for target in (pinned, disabled):
                target.mkdir()
                project_service.apply_project(project_service.preview_project(state, target, "add", enable=True, native_context=context))
            project_service.apply_project(project_service.preview_project(state, pinned, "use", content_id=core.content_id, native_context=context))
            project_service.apply_project(project_service.preview_project(state, disabled, "disable", native_context=context))
            central_runtime.apply(central_runtime.preview(state, binding=alternate.binding(), native_context=context))
            self.assertEqual(alternate.binding(), service.status(state, project)["runtime_binding"])
            self.assertEqual(core.binding(), service.status(state, pinned)["runtime_binding"])
            self.assertFalse(service.status(state, disabled)["declared_enabled"])
            project_service.apply_project(project_service.preview_project(state, pinned, "follow", native_context=context))
            project_service.apply_project(project_service.preview_project(state, disabled, "enable", native_context=context))
            self.assertEqual(alternate.binding(), service.status(state, pinned)["runtime_binding"])
            self.assertEqual(alternate.binding(), service.status(state, disabled)["runtime_binding"])
            mark_stage("follow_pin_activation_complete")
            # 只观测本次真实rollback预览的容量组成，原producer/serializer与
            # 4MiB拒绝原样执行。即使现场再次超限，也先留下有界字节/计数证据，
            # 不dump任何配置、正文、HOME或环境，不在异常后重试或绕过guard。
            actual_budget, actual_settlement = service.publication_budget, central_runtime._settlement_budget
            producer_facts = {}
            def observe_budget(plan):
                budget = actual_budget(plan)
                producer_facts[plan.project] = (plan, budget)
                return budget
            def observe_settlement(journal, *, receipt_increment=0):
                bound = central_runtime._settlement_value(journal)
                count_bytes = lambda value: len((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
                rows = []
                watched = {".codex/hooks.json", ".claude/settings.json", ".agents/hooks.json", resources.WINDOWS_BOOTSTRAP}
                for row in bound["projects"][:8]:
                    project_plan, producer = producer_facts[Path(row["project"])]
                    binding = resources.unique_json(resources.Node.from_value(row["binding_before"]).payload)
                    previous = resources.unique_json(resources.Node.from_value(row["journal_before"]).payload)
                    previous_changes = [{"path": item["path"], "bytes": {
                        key: len(base64.b64decode(item[key]["body"])) for key in ("before", "after", "installed") if key in item}}
                        for item in previous["changes"] if item["path"] in watched]
                    planned_changes = [{"path": item.relative, "before_bytes": len(item.before.payload), "after_bytes": len(item.after.payload)}
                                       for item in project_plan.changes if item.relative in watched]
                    rows.append({"project": Path(row["project"]).name,
                        "binding_before_bytes": len(resources.Node.from_value(row["binding_before"]).payload),
                        "journal_before_bytes": len(resources.Node.from_value(row["journal_before"]).payload),
                        "binding_after_producer_bytes": producer.binding_after_bytes,
                        "journal_after_producer_bytes": producer.journal_after_bytes,
                        "central_row_bytes": count_bytes(row), "after_is_guard": "sha256" in row["binding_after"],
                        "retained_count": len(binding["retained_nodes"]), "retained_bytes": count_bytes(binding["retained_nodes"]),
                        "previous_changes": previous_changes, "planned_changes": planned_changes})
                root_bytes = count_bytes(bound)
                print("NATIVE_CENTRAL_ROLLBACK_CAPACITY " + json.dumps({"projects": rows,
                    "project_count": len(bound["projects"]), "root_wire_before_receipt": root_bytes,
                    "native_receipt_increment": receipt_increment, "total_bound": root_bytes + receipt_increment,
                    "limit": resources.LIMIT}, sort_keys=True), flush=True)
                return actual_settlement(journal, receipt_increment=receipt_increment)
            with patch.object(service, "publication_budget", side_effect=observe_budget), \
                    patch.object(central_runtime, "_settlement_budget", side_effect=observe_settlement):
                rollback = central_runtime.preview(state, "rollback", native_context=context)
            central_runtime.apply(rollback)
            self.assertEqual(core.binding(), service.status(state, project)["runtime_binding"])
            mark_stage("central_rollback_complete")
            # 仅注入第二项目的业务失败点；所有第一项目发布/Job/ACL/原inode补偿都
            # 运行真实 Windows 后端。不能把 mocked native success 当作验收结果。
            proposal = central_runtime.preview(state, binding=alternate.binding(), native_context=context)
            first = next(capture for capture in proposal.captures if capture.runtime_plan)
            with resources.Tree(first.project) as tree:
                original = tree.read(resources.LOCATOR)
            actual_apply, calls = service.apply, []
            def fail_second(plan, **kwargs):
                calls.append(plan.project)
                if len(calls) == 2:
                    raise OSError("native fixture second project failure")
                return actual_apply(plan, **kwargs)
            with patch.object(service, "apply", side_effect=fail_second), self.assertRaisesRegex(OSError, "second project"):
                central_runtime.apply(proposal)
            with resources.Tree(first.project) as tree:
                restored = tree.read(resources.LOCATOR)
            self.assertEqual((original.payload, original.mode, original.identity[:2], original.security),
                             (restored.payload, restored.mode, restored.identity[:2], restored.security))
            self.assertIsNone(runtime_policy.pending(state))
            mark_stage("original_inode_compensation_complete")
            concurrent = central_runtime.preview(state, binding=alternate.binding(), native_context=context)
            first = next(capture for capture in concurrent.captures if capture.runtime_plan)
            calls.clear()
            user_saved = b'{"later-user-save":true}\n'
            def save_then_fail(plan, **kwargs):
                calls.append(plan.project)
                if len(calls) == 2:
                    (first.project / resources.LOCATOR).write_bytes(user_saved)
                    raise OSError("native fixture concurrent save before compensation")
                return actual_apply(plan, **kwargs)
            with patch.object(service, "apply", side_effect=save_then_fail), self.assertRaises((OSError, ValueError)):
                central_runtime.apply(concurrent)
            self.assertEqual(user_saved, (first.project / resources.LOCATOR).read_bytes())
            self.assertIsNotNone(runtime_policy.pending(state))
            mark_stage("concurrent_save_retained")
            # 已用旧 pin 的损坏核心直接拒绝；不会补最新版本或把源夹具当回退目录。
            corrupt = alternate.root / "product/GLOBAL_CONSTRAINTS.md"
            corrupt.write_bytes(b"damaged frozen constraints")
            alternate_pin = base64.b64encode(json.dumps(alternate.binding()).encode()).decode()
            self.assertNotEqual(0, invoke("--binding-b64", alternate_pin, "read", "product/GLOBAL_CONSTRAINTS.md").returncode)
            mark_stage("corrupt_pin_rejected")
            print("NATIVE_CENTRAL: full source/version/activate; detached isolated pin read/task_graph/PS7 Hook; Global/project override/reset; follow/pin/disable/rollback; second-project original-inode recovery/concurrent-save retention; unknown/corrupt/admission rejection executed")

    def test_project_junction_is_rejected_before_resolve_and_writes(self):
        with tempfile.TemporaryDirectory(prefix="central-junction-") as raw:
            root = Path(raw).resolve()
            target, junction = root / "real-project", root / "project-junction"
            target.mkdir()
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                                    capture_output=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            try:
                with self.assertRaises((OSError, ValueError)):
                    resources.canonical_project(junction)
                from manager.state_files import project_path
                with self.assertRaises((OSError, ValueError)):
                    project_path(junction)
                self.assertEqual([], list(target.iterdir()))
            finally:
                os.rmdir(junction)
