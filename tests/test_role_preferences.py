"""独立全局偏好/统一 CLI 合同；只使用请求 scratch 内最小中央 fixture。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from lib import role_models
from lib.central import role_preferences
from lib import runtime_store
from manager import model_preferences as preferences, project_service, runtime_service, service, state_files
from tests import test_workflow_manager as fixtures

PACK = fixtures.PACK


class RolePreferencesTest(unittest.TestCase):
    """复用既有最小来源构造器和一份 core，独占状态/项目在关闭时整体回收。"""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="role-preferences-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        cls.root = Path(cls.temporary.name).resolve()
        cls.source = fixtures.CentralCliIntegrationTest.create_source(cls.root)
        cls.state = cls.root / "state"
        cls.core = runtime_store.import_core(cls.source, cls.state)

    @classmethod
    def tearDownClass(cls):
        location = cls.root
        cls.temporary.cleanup()
        print("已关闭全局偏好独占 fixture：" + str(location) + "；存在=" + str(location.exists()))

    def setUp(self):
        self.case = self.root / self._testMethodName
        self.case.mkdir()
        self.home = self.case / "home"
        (self.home / ".codex").mkdir(parents=True)
        (self.home / ".codex/config.toml").write_text('model_catalog_json="models.json"\n')
        self.models = self.home / ".codex/models.json"
        self.models.write_text(json.dumps({"models": [
            {"id": "fixture-model", "supported_reasoning_levels": ["high", "max"]},
            {"id": "project-model", "supported_reasoning_levels": ["high", "max"]}]}))
        (self.home / ".claude").mkdir()
        (self.home / ".claude/settings.json").write_text(json.dumps({"modelPicker": {"options": [
            {"model": "fixture-model"}, {"model": "project-model"}]}}))
        # 本例验证各平台自身的来源层，剔除父进程实际账户/提供方覆盖，避免把
        # 用户 ANTHROPIC_* 环境解释成 fixture 的菜单换源；不读取或输出其值。
        inherited = {key: value for key, value in os.environ.items()
                     if not key.startswith(("ANTHROPIC_", "CLAUDE_CODE_"))}
        self.environment = {**inherited, "HOME": str(self.home), "CODEX_HOME": str(self.home / ".codex"),
                            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"), "AGENT_WORKFLOW_PYTHON": sys.executable,
                            "AGENT_WORKFLOW_STATE_DIR": str(self.state), "PYTHONDONTWRITEBYTECODE": "1"}
        self.environment_patch = patch.dict(os.environ, self.environment, clear=True)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)
        # 核心与状态目录在本类复用；每例只清理自己上一例的全局偏好/登记入口。
        # 项目/收据仍在该独占 fixture 内，绝不探测或清理用户根及业务目录。
        (self.state / role_preferences.RELATIVE).unlink(missing_ok=True)
        (self.state / "projects.json").unlink(missing_ok=True)
        directory = self.state / "preferences/transactions"
        self.transactions_before = set(directory.glob("*.json")) if directory.exists() else set()

    def recovery_records(self):
        """只检查本例新产生事务，不依赖共享目录的文件枚举/UUID排序。"""
        records = [json.loads(path.read_bytes()) for path in (self.state / "preferences/transactions").glob("*.json")
                   if path not in self.transactions_before and service.BACKUP_ID.fullmatch(path.stem)]
        return [record for record in records if "id" in record]

    def project(self, name, *, enabled=True, config=None, backend=True):
        project = self.case / name
        project.mkdir()
        # 空工程是有效画像：实现角色必须由工程事实产生，不能由全局已安装
        # 角色或本次偏好请求反向补齐；正常后端用例仍明确提供最小清单。
        if backend:
            (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.1.0"\n')
        if config is not None:
            (project / ".agent-workflow").mkdir()
            (project / ".agent-workflow/project.yaml").write_text(config)
        plan = project_service.preview_project(self.state, project, "add", enable=enabled,
                                       content_id=self.core.content_id if enabled else None)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        project_service.apply_project(plan)
        return project

    def plan(self, project, changes, host="codex", *, expected=None):
        catalogs = preferences.load_catalogs(self.state, project, host)
        return preferences.preview(self.state, project, host, changes, catalogs, expected)

    def test_preview_proves_each_pin_once_and_never_retains_live_reader(self):
        """真实项目/全局预览同根共用证明，第二实际pin必须另扫；Plan不能持活reader。"""
        first = self.project("first")
        second = self.project("second")
        choices = {"xy-backend": {"model": "fixture-model", "effort": "max"}}
        for project in (first, None):
            catalogs = preferences.load_catalogs(self.state, project, "codex")
            before = {str(path): (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                      for root in (first, second, self.home) for path in root.rglob("*")
                      if path.is_file() and not path.is_symlink()}
            with patch.object(runtime_store, "_scan", wraps=runtime_store._scan) as scan, \
                    patch.object(runtime_store, "_verify_snapshot", wraps=runtime_store._verify_snapshot) as verify:
                plan = preferences.preview(self.state, project, "codex", choices, catalogs)
            self.assertTrue(plan.summary["can_apply"], plan.summary)
            self.assertEqual((1, 2), (scan.call_count, verify.call_count))
            self.assertIsNone(runtime_store._READ_OPERATION.get())
            self.assertEqual(before, {str(path): (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                                     for root in (first, second, self.home) for path in root.rglob("*")
                                     if path.is_file() and not path.is_symlink()})
        # 第二版仍由真实import/use生产者发布，不手写binding或用mock假装跨pin。
        alternate_root = self.case / "alternate"
        alternate_root.mkdir()
        source = fixtures.CentralCliIntegrationTest.create_source(alternate_root)
        (source / "product/WORKFLOW.md").write_bytes(b"# alternate operation fixture\n")
        alternate = runtime_store.import_core(source, self.state)
        project_service.apply_project(project_service.preview_project(
            self.state, second, "use", content_id=alternate.content_id))
        catalogs = preferences.load_catalogs(self.state, None, "codex")
        with patch.object(runtime_store, "_scan", wraps=runtime_store._scan) as scan, \
                patch.object(runtime_store, "_verify_snapshot", wraps=runtime_store._verify_snapshot) as verify:
            plan = preferences.preview(self.state, None, "codex", choices, catalogs)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        self.assertEqual((2, 4), (scan.call_count, verify.call_count))
        self.assertIsNone(runtime_store._READ_OPERATION.get())

    def save(self, project, changes, host="codex"):
        plan = self.plan(project, changes, host)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        return preferences.apply(plan)

    def native(self, project, host="codex"):
        return service.role_settings(project, host, "xy-backend")

    def cli(self, *arguments, expected=0):
        # 独立 state 的宿主操作必须显式绑定同一临时 HOME；仅修改环境不能
        # 替代 CLI 的隔离授权，也不能让安全拒绝测试误中“缺少宿主目录”。
        command = ["bash", str(PACK / "workflow.sh"), "--state-dir", str(self.state),
                   "--host-home", str(self.home), "--json", *map(str, arguments)]
        result = subprocess.run(command, cwd=self.case, env=self.environment,
                                text=True, capture_output=True, timeout=35)
        print("真实 CLI：" + " ".join(command) + "\n" + result.stdout + result.stderr + "退出=" + str(result.returncode))
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def native_scope(self):
        """本例独占state与HOME；全局归属不会污染本类其他旧消费者的共享fixture。"""
        from lib.hosts.native_context import HostPaths, NativeContext
        from manager import native_agents, central_runtime
        self.state = self.case / "native-state"
        self.core = runtime_store.import_core(self.source, self.state)
        os.environ["AGENT_WORKFLOW_STATE_DIR"] = str(self.state)
        context = NativeContext(self.state, HostPaths.for_home(self.home, environment={}))
        central_runtime.apply(central_runtime.preview(self.state, binding=self.core.binding(), native_context=context))
        return context

    def native_save(self, context, project, edits, host="codex"):
        catalogs = preferences.load_catalogs(self.state, project, host, native_context=context)
        plan = preferences.preview(self.state, project, host, edits, catalogs, native_context=context)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        return preferences.apply(plan)

    def sparse_project(self, context, name, *, backend=True):
        project = self.project(name, enabled=False, backend=backend)
        plan = runtime_service.preview(self.state, project, "enable", binding=self.core.binding(), hosts=("codex",),
                                       native_context=context)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        runtime_service.apply(plan)
        self.assertFalse((project / ".codex/agents/xy-backend.toml").exists())
        return project

    def separate_ambient_environment(self):
        """准备第二个临时宿主根，使进程默认路径不再巧合等于NativeContext。"""
        home = self.case / "ambient-home"
        codex = home / ".codex"
        codex.mkdir(parents=True)
        (codex / "config.toml").write_text('model_catalog_json="models.json"\n')
        # 两边候选完全一致，差异仅在显式来源根，避免把缺模型误当成范围回归。
        (codex / "models.json").write_bytes(self.models.read_bytes())
        return {"HOME": str(home), "USERPROFILE": str(home), "CODEX_HOME": str(codex),
                "CLAUDE_CONFIG_DIR": str(home / ".claude")}

    def test_native_lazy_project_and_global_reset_keep_explicit_source_scope(self):
        context = self.native_scope()
        project = self.sparse_project(context, "separate-reset-scope")
        with patch.dict(os.environ, self.separate_ambient_environment()), \
                patch("manager.codex_models.query", side_effect=AssertionError("恢复及守卫不能隐式刷新原生目录")):
            self.native_save(context, None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
            self.native_save(context, project, {"xy-backend": {"model": "project-model"}})
            local = project / ".codex/agents/xy-backend.toml"
            project_reset = preferences.reset_platform(self.state, project, "codex", native_context=context)
            self.assertTrue(project_reset.summary["can_apply"], project_reset.summary)
            self.assertIsNone(project_reset.catalog, "本例必须覆盖恢复时惰性获取目录的分支")
            self.assertIsNotNone(project_reset.targets[0].catalog)
            self.assertTrue(preferences.apply(project_reset)["applied"])
            self.assertFalse(local.exists())
            self.assertEqual({"model": "fixture-model", "effort": "high"},
                             service.role_settings(project, "codex", "xy-backend", state=self.state, native_context=context))
            global_reset = preferences.reset_platform(self.state, None, "codex", native_context=context)
            self.assertTrue(global_reset.summary["can_apply"], global_reset.summary)
            self.assertIsNone(global_reset.catalog)
            self.assertIsNotNone(global_reset.targets[0].catalog)
            self.assertTrue(preferences.apply(global_reset)["applied"])
            self.assertFalse(role_preferences.snapshot(self.state)[1].get("codex"))
            self.assertFalse(local.exists(), "全局恢复不能补装稀疏项目角色")
            self.assertEqual({"model": "inherit", "effort": "inherit"},
                             service.role_settings(project, "codex", "xy-backend", state=self.state, native_context=context))

    def test_native_lazy_reset_rejects_real_context_source_change_without_writes(self):
        context = self.native_scope()
        project = self.sparse_project(context, "changed-reset-source")
        with patch.dict(os.environ, self.separate_ambient_environment()), \
                patch("manager.codex_models.query", side_effect=AssertionError("来源失效不能隐式刷新")):
            self.native_save(context, None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
            self.native_save(context, project, {"xy-backend": {"model": "project-model"}})
            original = self.models.read_bytes()
            for scope in (project, None):
                with self.subTest(scope="project" if scope is not None else "global"):
                    plan = preferences.reset_platform(self.state, scope, "codex", native_context=context)
                    self.assertTrue(plan.summary["can_apply"], plan.summary)
                    self.assertIsNone(plan.catalog)
                    self.assertIsNotNone(plan.targets[0].catalog)
                    changed = json.loads(original)
                    changed["models"].append({"id": "changed-context-model", "supported_reasoning_levels": ["high"]})
                    self.models.write_text(json.dumps(changed))
                    def persisted_files():
                        # 来源变更是本例主动输入；在其之后取前像，证明拒绝apply
                        # 不改项目、全局原生产物、偏好、备份或恢复日志，连mtime也不变。
                        return {str(path): (path.read_bytes(), path.stat().st_mode, path.stat().st_ino, path.stat().st_mtime_ns)
                                for root in (self.state, project, self.home) for path in root.rglob("*")
                                if path.is_file() and not path.is_symlink()}
                    before = persisted_files()
                    try:
                        with self.assertRaisesRegex(ValueError, "来源"):
                            preferences.apply(plan)
                        self.assertEqual(before, persisted_files())
                    finally:
                        self.models.write_bytes(original)

    def test_empty_profile_rejects_explicit_role_edit_without_partial_save_or_global_install(self):
        context = self.native_scope()
        project = self.sparse_project(context, "empty-profile", backend=False)
        self.assertEqual(["xy-qa", "xy-uiux"], preferences.roles(self.state, project, "codex", native_context=context))
        config = project / ".agent-workflow/project.yaml"
        before_config = config.read_bytes()
        # 全局默认仍可保存给未来工程使用；它不能把空画像中的后端角色补装
        # 到项目，也不能为后续项目显式请求提供伪造的角色资格。
        result = self.native_save(context, None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
        self.assertTrue(result["applied"])
        self.assertEqual(before_config, config.read_bytes())
        self.assertFalse((project / ".codex/agents/xy-backend.toml").exists())
        self.assertFalse(result["backups"])
        catalogs = preferences.load_catalogs(self.state, project, "codex", native_context=context)
        before_paths, before_backups = set(project.rglob("*")), service.backups(self.state, project)
        edits = {"xy-backend": {"model": "project-model"}, "xy-qa": {"effort": "high"}}
        plan = preferences.preview(self.state, project, "codex", edits, catalogs, native_context=context)
        self.assertFalse(plan.summary["can_apply"], plan.summary)
        self.assertEqual([], plan.changed_paths, "混合请求必须整批拒绝，不能仅保存其中可用角色")
        with self.assertRaises(ValueError):
            preferences.apply(plan)
        # 直接模型服务调用也遵守同一已验证画像，避免旁路偏好计划后补装角色。
        with self.assertRaisesRegex(ValueError, "画像"):
            service.prepare(project, "codex", edits, catalogs.catalog, state=self.state, native_context=context)
        with self.assertRaisesRegex(ValueError, "只允许清理"):
            service.prepare(project, "codex", {"xy-backend": {"model": "project-model"}}, catalogs.catalog,
                            state=self.state, native_context=context, metadata_roles=("xy-backend",))
        self.assertEqual(before_config, config.read_bytes())
        self.assertEqual(before_paths, set(project.rglob("*")))
        self.assertEqual(before_backups, service.backups(self.state, project))

    def test_active_empty_profile_reset_cleans_legacy_metadata_without_installing_role(self):
        context = self.native_scope()
        project = self.sparse_project(context, "empty-reset", backend=False)
        config = project / ".agent-workflow/project.yaml"
        # 合法旧覆盖可能在工程类型改变后遗留；恢复平台必须允许删除这些元数据，
        # 即使普通编辑已不具备该角色资格，也不能为了清理而安装原生角色。
        config.write_text(role_models.update(config.read_text(), {"codex": {"xy-backend": {"model": "project-model"}}}))
        plan = preferences.reset_platform(self.state, project, "codex", native_context=context)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        self.assertEqual([".agent-workflow/project.yaml"], plan.changed_paths)
        self.assertTrue(preferences.apply(plan)["applied"])
        self.assertFalse(role_models.parse(config.read_text()).get("codex"))
        self.assertFalse((project / ".codex/agents/xy-backend.toml").exists())
        self.assertFalse(preferences.apply(preferences.reset_platform(self.state, project, "codex", native_context=context))["applied"])

    def test_native_sparse_create_single_field_global_following_explicit_inherit_and_final_reset(self):
        context = self.native_scope()
        self.native_save(context, None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
        project = self.sparse_project(context, "native-sparse")
        self.assertIn("xy-backend", preferences.roles(self.state, project, "codex", native_context=context))
        self.native_save(context, project, {"xy-backend": {"model": "project-model"}})
        local = project / ".codex/agents/xy-backend.toml"
        self.assertEqual(service.native_settings(local.read_bytes(), "codex"), {"model": "project-model", "effort": "high"})
        self.assertIn(b"Before any project check", local.read_bytes())
        self.native_save(context, None, {"xy-backend": {"effort": "max"}})
        from manager import native_agents, central_runtime
        self.assertEqual(native_agents.admission_issues(self.state, hosts=("codex",)), [])
        self.assertTrue(runtime_service.status(self.state, project)["new_task_allowed"])
        self.assertEqual(central_runtime.new_task_gate(self.state, project), self.core.binding())
        self.assertEqual(service.native_settings(local.read_bytes(), "codex"), {"model": "project-model", "effort": "max"})
        self.native_save(context, project, {"xy-backend": {"model": "inherit"}})
        self.assertEqual(preferences.view(self.state, project, "codex", "xy-backend")["sources"],
                         {"model": "host", "effort": "global"})
        self.native_save(context, None, {"xy-backend": {"model": "project-model"}})
        self.assertEqual(service.native_settings(local.read_bytes(), "codex")["model"], "inherit")
        plan = preferences.reset_platform(self.state, project, "codex", native_context=context)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        self.assertIn(".codex/agents/xy-backend.toml", plan.changed_paths)
        preferences.apply(plan)
        self.assertFalse(local.exists())
        self.assertEqual(service.role_settings(project, "codex", "xy-backend", state=self.state, native_context=context),
                         {"model": "project-model", "effort": "max"})
        backups = service.backups(self.state, project)
        self.assertFalse(preferences.apply(preferences.reset_platform(self.state, project, "codex", native_context=context))["applied"])
        self.assertEqual(service.backups(self.state, project), backups)
        self.native_save(context, None, {"xy-backend": {"effort": "high"}})
        self.assertFalse(local.exists())
        self.assertEqual(preferences.view(self.state, project, "codex", "xy-backend")["effort"], "high")

    def test_native_platform_reset_disabled_host_is_metadata_only_and_contextless_write_refuses(self):
        context = self.native_scope()
        project = self.sparse_project(context, "disabled-host")
        config = project / ".agent-workflow/project.yaml"
        choices = {"claude": {"xy-apple": {"model": "project-model", "effort": "high"}}}
        config.write_text(role_models.update(config.read_text(), choices))
        plan = preferences.reset_platform(self.state, project, "claude", native_context=context)
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        self.assertEqual(plan.changed_paths, [".agent-workflow/project.yaml"])
        preferences.apply(plan)
        self.assertFalse(role_models.parse(config.read_text()).get("claude"))
        self.assertFalse((project / ".claude/agents").exists())
        self.assertEqual(runtime_service.read_binding_record(self.state, project)[1]["hosts"], ["codex"])
        with self.assertRaisesRegex(ValueError, "NativeContext"):
            preferences.preview(self.state, None, "codex", {"xy-backend": {"effort": "high"}},
                                fixtures.Catalog("codex", [fixtures.Model("inherit", "inherit", "fixture")]))

    def test_native_sparse_reset_restore_keeps_compilation_and_exact_mode_contract(self):
        from dataclasses import replace
        from lib.central import runtime_project as resources
        from lib.windows_fs import project_mode as windows_project_mode
        context = self.native_scope()
        self.native_save(context, None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
        project = self.sparse_project(context, "sparse-reset-restore")
        self.native_save(context, project, {"xy-backend": {"model": "project-model"}})
        self.native_save(context, None, {"xy-backend": {"effort": "max"}})
        relative = ".codex/agents/xy-backend.toml"
        local = project / relative
        with resources.Tree(project) as tree:
            original = tree.read(relative)
        original_mode = stat.S_IMODE(local.stat().st_mode)
        global_before = role_preferences.snapshot(self.state)[0]
        result = preferences.apply(preferences.reset_platform(self.state, project, "codex", native_context=context))
        self.assertFalse(local.exists())
        restored = service.prepare_restore(self.state, project, result["backup_id"])
        role_change = next(row for row in restored if row.relative == relative)
        config_change = next(row for row in restored if row.relative == resources.CONFIG)
        self.assertIsNone(role_change.before)
        self.assertEqual(original_mode, role_change.mode, "恢复必须沿用实际备份mode，不能改写成0644掩盖断点")
        self.assertEqual(original.payload, role_change.after)
        self.assertNotIn(relative, runtime_service.read_binding_record(self.state, project)[1]["managed"])
        material = resources.Resources(self.core.root, resources.json_bytes(self.core.binding()), self.core.label, self.core)
        compiled = resources.role_resource(material, config_change.after, "codex", "xy-backend", self.core.binding(),
                                           preferences=role_preferences.snapshot(self.state)[1])
        self.assertEqual(compiled, role_change.after, "恢复正文必须逐字节等于固定core按拟恢复CONFIG及当前global编译的完整产物")
        def persisted_files():
            return {str(path): (path.read_bytes(), path.stat().st_mode, path.stat().st_ino, path.stat().st_mtime_ns)
                    for root in (self.state, project, self.home) for path in root.rglob("*")
                    if path.is_file() and not path.is_symlink()}
        before = persisted_files()
        class AdmissionObserved(Exception):
            pass
        # 仅把既有纯Windows模式映射交给真实receipt准入边界，不模拟Win32或
        # ACL成功。准入后立即以测试异常退出，不发布文件或伪造实际收据。
        with patch.object(runtime_service, "project_mode", windows_project_mode):
            self.assertEqual(0o666, windows_project_mode(0o644))
            for mode in (0o666, 0o644):
                changes = tuple(replace(row, mode=mode) if row.relative == relative else row for row in restored)
                with self.subTest(accepted=oct(mode)), self.assertRaises(AdmissionObserved):
                    with runtime_service.native_edit_receipt(self.state, project, changes, native_context=context):
                        raise AdmissionObserved()
                self.assertEqual(before, persisted_files())
            for mode, body in ((0o600, role_change.after), (0o444, role_change.after), (0o777, role_change.after),
                               (0o666, role_change.after + b"# unknown body change\n")):
                changes = tuple(replace(row, mode=mode, after=body) if row.relative == relative else row for row in restored)
                with self.subTest(rejected=oct(mode), changed_body=body != role_change.after), \
                        self.assertRaisesRegex(ValueError, "稀疏角色创建必须等于固定核心完整编译结果"):
                    with runtime_service.native_edit_receipt(self.state, project, changes, native_context=context):
                        self.fail("非规范mode或正文改变不能进入发布阶段")
                self.assertEqual(before, persisted_files())
        # 使用本平台真实备份mode完成实际commit；归档身份/ACL验证、来源守卫及
        # 新节点观察均走生产路径，回执必须登记真实产物而不是请求mode的占位。
        self.assertIsNotNone(service.commit(self.state, project, restored, native_context=context))
        with resources.Tree(project) as tree:
            actual = tree.read(relative)
        managed = runtime_service.read_binding_record(self.state, project)[1]["managed"][relative]
        self.assertEqual(actual, resources.Node.from_value(managed["expected"]))
        self.assertEqual((original.payload, original.mode, original.security), (actual.payload, actual.mode, actual.security))
        self.assertEqual(global_before, role_preferences.snapshot(self.state)[0])
        self.assertEqual({"model": "project-model", "effort": "max"},
                         service.role_settings(project, "codex", "xy-backend", state=self.state, native_context=context))
        self.assertTrue(runtime_service.status(self.state, project)["new_task_allowed"])
        print("SPARSE_RESTORE_MODE requested=" + oct(role_change.mode) + " actual=" + oct(actual.mode) +
              " receipt=" + oct(resources.Node.from_value(managed["expected"]).mode) + "; full_compilation_equal=True")

    def test_sparse_delete_rename_failure_retains_old_inode_and_index(self):
        context = self.native_scope()
        project = self.sparse_project(context, "delete-rename-failure")
        self.native_save(context, project, {"xy-backend": {"model": "project-model"}})
        local = project / ".codex/agents/xy-backend.toml"
        original_body = local.read_bytes()
        descriptor = os.open(local, os.O_WRONLY | os.O_APPEND)
        self.addCleanup(os.close, descriptor)
        plan = preferences.reset_platform(self.state, project, "codex", native_context=context)
        original_rename = service.os.rename
        failed = False
        def fail_after_rename(source, target, **kwargs):
            nonlocal failed
            result = original_rename(source, target, **kwargs)
            if source == "xy-backend.toml" and str(target).startswith(".workflow-models-previous-") and not failed:
                failed = True
                raise OSError("fixture after-delete-rename")
            return result
        with patch.object(service.os, "rename", side_effect=fail_after_rename):
            with self.assertRaisesRegex(OSError, "after-delete-rename"):
                preferences.apply(plan)
        self.assertTrue(failed)
        self.assertEqual(local.read_bytes(), original_body)
        record = next(row for row in service.backups(self.state, project) if row["status"] == "rolled_back")
        self.assertTrue(record["previous_files"])
        version = next(row for row in record["previous_files"] if row["source"].endswith("xy-backend.toml"))
        retained = project / version["path"]
        self.assertEqual(retained.read_bytes(), original_body)
        os.write(descriptor, b"\n# late old fd edit\n")
        self.assertIn(b"late old fd edit", retained.read_bytes())
        with self.assertRaises(ValueError):
            service.check_versions(project, record["previous_files"])
        self.assertEqual(local.read_bytes(), original_body)

    def test_sparse_delete_rechecks_global_ownership_before_publishing_receipt(self):
        context = self.native_scope()
        project = self.sparse_project(context, "delete-global-race")
        self.native_save(context, project, {"xy-backend": {"model": "project-model"}})
        local = project / ".codex/agents/xy-backend.toml"
        original_body = local.read_bytes()
        original_config = (project / ".agent-workflow/project.yaml").read_bytes()
        global_role = context.host_paths.codex / "agents/xy-backend.toml"
        plan = preferences.reset_platform(self.state, project, "codex", native_context=context)
        original_replace = service._replace_optional
        removed = False
        def remove_global_after_local(target, body, mode, expected):
            nonlocal removed
            result = original_replace(target, body, mode, expected)
            if target.path == local and body is None and not removed:
                removed = True
                global_role.unlink()
            return result
        with patch.object(service, "_replace_optional", side_effect=remove_global_after_local):
            with self.assertRaises(ValueError):
                preferences.apply(plan)
        self.assertTrue(removed)
        self.assertFalse(global_role.exists())
        self.assertEqual(local.read_bytes(), original_body)
        self.assertEqual((project / ".agent-workflow/project.yaml").read_bytes(), original_config)

    def test_native_platform_reset_preserves_managed_manual_delete_conflict(self):
        context = self.native_scope()
        project = self.sparse_project(context, "manual-delete")
        self.native_save(context, project, {"xy-backend": {"model": "project-model"}})
        local = project / ".codex/agents/xy-backend.toml"
        local.unlink()
        plan = preferences.reset_platform(self.state, project, "codex", native_context=context)
        self.assertFalse(plan.summary["can_apply"])
        with self.assertRaises(ValueError):
            preferences.apply(plan)
        self.assertFalse(local.exists())
        self.assertEqual(role_models.parse((project / ".agent-workflow/project.yaml").read_text())["codex"]["xy-backend"],
                         {"model": "project-model"})

    def test_reset_platform_cleans_disabled_host_and_uninstalled_roles_without_native_install(self):
        config = ('project_name: reset\nworkflow_hooks:\n  mode: off\nrole_models:\n'
                  '  codex:\n    xy-apple: {"model":"project-model","effort":"max"}\n'
                  '    xy-backend: {"model":"inherit"}\n'
                  '  claude:\n    xy-backend: {"model":"project-model"}\n')
        project = self.project("reset-disabled", enabled=False, config=config)
        before = set(project.rglob("*"))
        plan = preferences.reset_platform(self.state, project, "codex")
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        self.assertEqual(set(project.rglob("*")), before)
        self.assertEqual(plan.changed_paths, [".agent-workflow/project.yaml"])
        result = preferences.apply(plan)
        self.assertTrue(result["applied"])
        choices = role_models.parse((project / ".agent-workflow/project.yaml").read_text())
        self.assertFalse(choices.get("codex"))
        self.assertEqual(choices["claude"]["xy-backend"], {"model": "project-model"})
        self.assertFalse((project / ".codex").exists())
        self.assertFalse(runtime_service.read_binding_record(self.state, project)[1])
        backups = service.backups(self.state, project)
        noop = preferences.reset_platform(self.state, project, "codex")
        self.assertFalse(preferences.apply(noop)["applied"])
        self.assertEqual(service.backups(self.state, project), backups)

    def test_reset_platform_global_cleans_all_fields_and_noop_does_not_write(self):
        self.save(None, {"xy-apple": {"model": "project-model", "effort": "max"},
                         "xy-backend": {"model": "inherit"}})
        plan = preferences.reset_platform(self.state, None, "codex")
        self.assertTrue(plan.summary["can_apply"], plan.summary)
        self.assertEqual(len(plan.summary["changes"]), 3)
        preferences.apply(plan)
        self.assertFalse(role_preferences.snapshot(self.state)[1].get("codex"))
        before = {(str(path), path.stat().st_mtime_ns) for path in (self.state / "preferences").rglob("*")}
        self.assertFalse(preferences.apply(preferences.reset_platform(self.state, None, "codex"))["applied"])
        self.assertEqual(before, {(str(path), path.stat().st_mtime_ns) for path in (self.state / "preferences").rglob("*")})

    def test_reset_platform_concurrent_fixed_plans_cleanup_once(self):
        self.save(None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
        plans = [preferences.reset_platform(self.state, None, "codex") for _ in range(2)]
        before = len(self.recovery_records())
        def apply(plan):
            try:
                return preferences.apply(plan)["applied"]
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(executor.map(apply, plans)), 1)
        self.assertFalse(role_preferences.snapshot(self.state)[1].get("codex"))
        self.assertEqual(len(self.recovery_records()), before + 1)

    def test_reset_platform_rejects_unknown_schema_and_stale_preview(self):
        self.save(None, {"xy-backend": {"model": "fixture-model"}})
        plan = preferences.reset_platform(self.state, None, "codex")
        self.save(None, {"xy-backend": {"effort": "high"}})
        with self.assertRaises(ValueError):
            preferences.apply(plan)
        (self.state / role_preferences.RELATIVE).write_text('{"schema_version":99,"role_models":{}}')
        with self.assertRaises(ValueError):
            preferences.reset_platform(self.state, None, "codex")

    def test_empty_reads_create_no_state_and_private_global_save(self):
        empty = self.case / "empty-state"
        with patch("manager.codex_models.query", side_effect=AssertionError("只读查询不应启动原生目录")):
            value = preferences.view(empty, None, "codex", "xy-backend")
            self.assertEqual(value["sources"], {"model": "host", "effort": "host"})
            catalogs = preferences.load_catalogs(empty, None, "codex")
            plan = preferences.preview(empty, None, "codex", {"xy-backend": {"model": "fixture-model"}}, catalogs)
            self.assertTrue(preferences.check_catalogs(empty, None, "codex", catalogs))
            self.assertFalse(empty.exists())
            result = preferences.apply(plan)
        self.assertTrue(result["applied"])
        self.assertEqual(stat.S_IMODE((empty / role_preferences.RELATIVE).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((empty / "preferences").stat().st_mode), 0o700)
        self.assertEqual(role_preferences.snapshot(empty)[1], {"codex": {"xy-backend": {"model": "fixture-model"}}})
        self.assertTrue((empty / "preferences/transactions" / (result["backup_id"] + ".json")).is_file())

    def test_global_updates_two_projects_without_config_or_pin_changes(self):
        first, second = self.project("first"), self.project("second")
        configs = {project: (project / ".agent-workflow/project.yaml").read_bytes() for project in (first, second)}
        bindings = {project: project_service.project_status(self.state, project)["runtime_binding"] for project in (first, second)}
        plan = self.plan(None, {"xy-backend": {"model": "fixture-model", "effort": "max"}})
        self.assertEqual({row["project"] for row in plan.summary["affected_projects"]}, {str(first), str(second)})
        self.assertFalse((self.state / role_preferences.RELATIVE).exists())
        with patch("manager.codex_models.query", side_effect=AssertionError("普通预览/守卫不得启动原生查询")):
            self.assertTrue(preferences.check_catalogs(self.state, None, "codex", plan.catalog))
            result = preferences.apply(plan)
        self.assertEqual(len(result["backups"]), 2)
        for project in (first, second):
            self.assertEqual(self.native(project), {"model": "fixture-model", "effort": "max"})
            self.assertEqual((project / ".agent-workflow/project.yaml").read_bytes(), configs[project])
            self.assertEqual(project_service.project_status(self.state, project)["runtime_binding"], bindings[project])
            self.assertFalse(project_service.project_status(self.state, project)["conflicts"])
            self.assertEqual(preferences.view(self.state, project, "codex", "xy-backend")["sources"], {"model": "global", "effort": "global"})

    def test_native_batch_scope_refresh_keeps_global_save_and_readonly_guards(self):
        """真实原生宿主逐 cwd 刷新共享提示时，同一批次仍能保存到两个项目。"""
        first, second = self.project("first"), self.project("second")
        (self.home / ".codex/config.toml").write_text('model="fixture-model"\n')
        fixture = fixtures.CatalogTest()
        fixture.home = self.home
        native_env = fixture.native_fixture(
            [{"data": [fixture.native_row("fixture-model")], "nextCursor": None}],
            mode="scope", cache_identity="opaque-scope")
        with patch.dict(os.environ, native_env):
            catalogs = preferences.load_catalogs(self.state, None, "codex")
            self.assertTrue(preferences.check_catalogs(self.state, None, "codex", catalogs))
            calls = (self.home / "native-calls").read_bytes()
            with patch("manager.codex_models.query", side_effect=AssertionError("预览/守卫不得启动 native")):
                plan = preferences.preview(self.state, None, "codex", {"xy-backend": {"model": "fixture-model", "effort": "max"}}, catalogs)
                self.assertTrue(plan.summary["can_apply"], plan.summary)
                result = preferences.apply(plan)
            self.assertTrue(result["applied"])
            self.assertEqual(len(result["backups"]), 2)
            self.assertEqual((self.home / "native-calls").read_bytes(), calls)
            self.assertEqual(sum(json.loads(line)["method"] == "model/list" for line in calls.splitlines()), 3)
            for project in (first, second):
                self.assertEqual(self.native(project), {"model": "fixture-model", "effort": "max"})
            self.assertNotIn("stale-cache-only", [row.id for row in catalogs.catalog.models])
            # 发布后的身份变化仍须拒绝；已经交付的原目录不获得新的授权。
            (self.home / ".codex/models_cache.json").write_text('{"identity":"external-after-publication"}')
            self.assertFalse(preferences.check_catalogs(self.state, None, "codex", catalogs))

    def test_native_batch_rejects_chain_source_capability_and_registry_changes(self):
        """保留真实 stdio，仅在相邻查询间或后序查询时注入确切的外部来源写入。"""
        project = self.project("project")
        config = self.home / ".codex/config.toml"
        auth = self.home / ".codex/auth.json"
        cache = self.home / ".codex/models_cache.json"
        fixture = fixtures.CatalogTest()
        fixture.home = self.home
        native_env = fixture.native_fixture(
            [{"data": [fixture.native_row("fixture-model")], "nextCursor": None}],
            mode="scope", cache_identity="opaque-scope")
        executable = self.home / "bin/codex"
        original_binary = executable.read_bytes()
        registry = self.state / "projects.json"
        original_registry = registry.read_bytes()
        explicit = self.home / ".codex/models.json"
        original_models = explicit.read_bytes()
        original_discover = preferences.discover
        for change in ("identity", "provider", "auth", "binary", "registry", "capability"):
            with self.subTest(change=change):
                config.write_text('model_catalog_json="models.json"\n' if change == "capability" else 'model="fixture-model"\n')
                auth.write_text("PRIVATE-AUTH-NEVER-READ")
                cache.write_text('{"identity":"initial"}')
                calls = []
                def acquire(host, *, project=None, _snapshot=None):
                    result = original_discover(host, project=project, _snapshot=_snapshot)
                    if _snapshot is None:
                        calls.append(project)
                        # identity 在前次返回后改动，应与下次 before 不连续；其余在
                        # 后序查询后改变全局基底，证明不能结束时盲绑旧结果。
                        if (change == "identity" and len(calls) == 1 or
                                change != "identity" and len(calls) == 2):
                            if change == "identity":cache.write_text('{"identity":"external-between-queries"}')
                            elif change == "provider":config.write_text('model_provider="external-provider"\n')
                            elif change == "auth":auth.write_text("CHANGED-PRIVATE-AUTH")
                            elif change == "binary":executable.write_bytes(original_binary + b"\n# changed\n")
                            elif change == "registry":registry.write_bytes(original_registry + b" ")
                            else:explicit.write_text('{"models":[{"id":"fixture-model","supported_reasoning_levels":["high"]}]}')
                    return result
                read_text = Path.read_text
                def safe_read(path, *args, **kwargs):
                    if path == auth:raise AssertionError("禁止读取 auth 正文")
                    return read_text(path, *args, **kwargs)
                try:
                    with patch.dict(os.environ, native_env), patch.object(Path, "read_text", safe_read), \
                            patch("manager.model_preferences.discover", side_effect=acquire):
                        with self.assertRaisesRegex(ValueError, "变化|丢弃"):
                            preferences.load_catalogs(self.state, None, "codex")
                    self.assertEqual(calls, [None, project])
                    self.assertFalse((self.state / role_preferences.RELATIVE).exists())
                    self.assertEqual(self.native(project)["model"], "inherit")
                finally:
                    executable.write_bytes(original_binary)
                    registry.write_bytes(original_registry)
                    explicit.write_bytes(original_models)

    def test_context_is_readonly_stable_and_preserves_old_authorization(self):
        project = self.project("context")
        self.save(None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
        self.save(project, {"xy-backend": {"model": "project-model", "effort": "inherit"}})
        catalogs = preferences.load_catalogs(self.state, project, "codex")
        with patch("manager.codex_models.query", side_effect=AssertionError("上下文不得启动 native")):
            context = preferences.load_context(self.state, project, "codex", catalogs=catalogs)
            self.assertIs(context.catalogs, catalogs)
            self.assertIsNone(preferences.load_context(self.state, None, "codex").catalogs)
        baseline = context.role_values
        self.assertEqual(baseline["xy-backend"], preferences.view(self.state, project, "codex", "xy-backend"))
        self.assertEqual(context.following_values["xy-backend"],
                         {"model": "fixture-model", "effort": "high", "sources": {"model": "global", "effort": "global"}})
        copy = context.role_values
        copy["xy-backend"]["sources"]["model"] = "mutated"
        following = context.following_values
        following["xy-backend"]["model"] = "mutated"
        self.assertEqual(context.role_values, baseline)
        self.assertEqual(context.following_values["xy-backend"]["model"], "fixture-model")
        with self.assertRaisesRegex(ValueError, "范围"):
            preferences.load_context(self.state, None, "codex", catalogs=catalogs)
        self.save(None, {"xy-backend": {"effort": "max"}})
        refreshed = preferences.load_context(self.state, project, "codex")
        self.assertEqual(refreshed.following_values["xy-backend"]["effort"], "max")
        self.assertEqual(context.role_values, baseline)
        with self.assertRaisesRegex(ValueError, "来源或配置"):
            preferences.preview(self.state, project, "codex", {"xy-backend": {"model": "fixture-model"}},
                                catalogs, expected=baseline)

    def test_context_refuses_global_changes_during_role_projection(self):
        project = self.project("torn-context")
        original_roles = preferences.roles
        reads = []
        def change_during_read(*args, **kwargs):
            result = original_roles(*args, **kwargs)
            reads.append(True)
            if len(reads) == 1:
                path = self.state / role_preferences.RELATIVE
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(role_preferences.payload({"codex": {"xy-backend": {"effort": "high"}}}))
            return result
        with patch("manager.model_preferences.roles", side_effect=change_during_read), \
                patch("manager.codex_models.query", side_effect=AssertionError("上下文不得启动 native")):
            with self.assertRaisesRegex(ValueError, "上下文期间变化"):
                preferences.load_context(self.state, project, "codex")

    def test_partial_project_override_reset_and_explicit_host_inherit(self):
        project = self.project("partial")
        self.save(None, {"xy-backend": {"model": "fixture-model", "effort": "high"}})
        self.save(project, {"xy-backend": {"model": "project-model"}})
        config_path = project / ".agent-workflow/project.yaml"
        self.assertEqual(role_models.parse(config_path.read_text())["codex"]["xy-backend"], {"model": "project-model"})
        self.save(None, {"xy-backend": {"effort": "max"}})
        self.assertEqual(self.native(project), {"model": "project-model", "effort": "max"})
        value = preferences.view(self.state, project, "codex", "xy-backend")
        self.assertEqual(value["sources"], {"model": "project", "effort": "global"})
        self.save(project, {"xy-backend": {"model": None}})
        self.assertEqual(preferences.view(self.state, project, "codex", "xy-backend")["overrides"], {})
        self.assertEqual(self.native(project)["model"], "fixture-model")
        self.save(project, {"xy-backend": {"effort": "inherit"}})
        self.save(None, {"xy-backend": {"effort": "high"}})
        self.assertEqual(self.native(project)["effort"], "inherit")
        value = preferences.view(self.state, project, "codex", "xy-backend")
        self.assertEqual(value["overrides"], {"effort": "inherit"})
        self.assertEqual(value["sources"]["effort"], "host")
        self.save(None, {"xy-backend": {"model": None}})
        self.assertEqual(self.native(project), {"model": "inherit", "effort": "inherit"})

    def test_existing_explicit_fields_and_other_hosts_are_preserved(self):
        # 启用消费者需要完整适配器合同；复用现有模板补一个明确字段，不能用
        # 缺少 memory/workspace/docs 的局部 YAML 误报偏好功能失败。
        config = role_models.update((PACK / "templates/project.yaml.example").read_text().replace(
            "replace-with-unique-project-id", "fixture-existing"), {"codex": {"xy-backend": {"model": "inherit"}}})
        project = self.project("existing", config=config)
        self.save(None, {"xy-backend": {"model": "fixture-model", "effort": "max"}})
        self.assertEqual(self.native(project), {"model": "inherit", "effort": "max"})
        codex = service.role_path(project, "codex", "xy-backend").read_bytes()
        self.save(None, {"xy-backend": {"model": "project-model", "effort": "high"}}, "claude")
        self.assertEqual(self.native(project, "claude"), {"model": "project-model", "effort": "high"})
        self.assertEqual(service.role_path(project, "codex", "xy-backend").read_bytes(), codex)
        self.save(None, {"xy-backend": {"model": "pro"}}, "antigravity")
        self.assertEqual(self.native(project, "antigravity")["model"], "pro")
        with self.assertRaises(ValueError):
            self.plan(None, {"xy-backend": {"effort": "high"}}, "antigravity")

    def test_disabled_unmanaged_and_later_enable_use_rollback_materialize_defaults(self):
        disabled = self.project("disabled")
        project_service.apply_project(project_service.preview_project(self.state, disabled, "disable"))
        unmanaged = self.project("unmanaged", enabled=False)
        plan = self.plan(None, {"xy-backend": {"model": "fixture-model", "effort": "max"}})
        self.assertEqual(len(plan.summary["affected_projects"]), 2)
        self.assertTrue(all(not row["changed_paths"] for row in plan.summary["affected_projects"]))
        preferences.apply(plan)
        self.assertFalse(service.role_path(disabled, "codex", "xy-backend").exists())
        self.assertFalse((unmanaged / ".agent-workflow").exists())
        for project in (disabled, unmanaged):
            project_service.apply_project(project_service.preview_project(self.state, project, "enable", content_id=self.core.content_id))
            self.assertEqual(self.native(project), {"model": "fixture-model", "effort": "max"})
        # 同一最小来源只改一个产品正文产生第二个真实固定版本，检查 use/rollback
        # 仍消费当前默认，同时保留旧任务可读取的原内容 ID。
        workflow = self.source / "product/WORKFLOW.md"
        workflow.write_text("# 固定版本二\n")
        second = runtime_store.import_core(self.source, self.state)
        project_service.apply_project(project_service.preview_project(self.state, disabled, "use", content_id=second.content_id))
        self.assertEqual(self.native(disabled)["model"], "fixture-model")
        project_service.apply_project(project_service.preview_project(self.state, disabled, "rollback"))
        self.assertEqual(self.native(disabled)["effort"], "max")
        self.assertEqual(project_service.project_status(self.state, disabled)["runtime_binding"], self.core.binding())

    def test_stale_plan_config_registry_native_and_catalog_are_rejected(self):
        project = self.project("stale")
        cases = ("global", "config", "registry", "native", "catalog")
        for kind in cases:
            with self.subTest(kind=kind):
                plan = self.plan(None, {"xy-backend": {"model": "fixture-model"}})
                if kind == "global":
                    path = self.state / role_preferences.RELATIVE
                    path.write_bytes(role_preferences.payload({"codex": {"xy-qa": {"model": "inherit"}}}))
                elif kind == "config":
                    path = project / ".agent-workflow/project.yaml"
                elif kind == "registry":
                    path = self.state / "projects.json"
                elif kind == "native":
                    path = service.role_path(project, "codex", "xy-backend")
                else:
                    path = self.models
                before = path.read_bytes()
                changed = before
                if kind == "catalog":
                    data = json.loads(before)
                    data["models"].append({"id": "new-model"})
                    changed = json.dumps(data).encode()
                elif kind != "global":
                    changed = before + (b" " if kind == "registry" else b"\n# concurrent\n")
                if kind != "global":path.write_bytes(changed)
                with self.assertRaisesRegex(ValueError, "变化"):
                    preferences.apply(plan)
                self.assertEqual(path.read_bytes(), changed)
                if kind == "global":path.unlink()
                else:path.write_bytes(before)
        # 完整 view 的来源身份也绑定草稿；原生值即使相同，全局来源前像变化也拒绝。
        expected = {"xy-backend": preferences.view(self.state, project, "codex", "xy-backend")}
        self.save(None, {"xy-qa": {"effort": "high"}})
        with self.assertRaisesRegex(ValueError, "来源或配置"):
            self.plan(project, {"xy-backend": {"model": "fixture-model"}}, expected=expected)

    def test_global_per_project_provider_capability_refusal_and_no_native_guard(self):
        project = self.project("provider")
        local = project / ".codex/limited.json"
        local.write_text('{"models":[{"id":"project-model","supported_reasoning_levels":["high"]}]}')
        native_config = project / ".codex/config.toml"
        native_config.write_text('model_catalog_json="limited.json"\n' + native_config.read_text())
        catalogs = preferences.load_catalogs(self.state, None, "codex")
        with patch("manager.codex_models.query", side_effect=AssertionError("预览不应获取原生目录")):
            plan = preferences.preview(self.state, None, "codex", {"xy-backend": {"model": "fixture-model"}}, catalogs)
            self.assertFalse(plan.summary["can_apply"])
            self.assertTrue(plan.summary["conflicts"])
            with self.assertRaises(ValueError):preferences.apply(plan)
        self.assertFalse((self.state / role_preferences.RELATIVE).exists())
        self.assertEqual(self.native(project)["model"], "inherit")

    def test_global_failure_compensates_projects_and_records_recovery(self):
        first, second = self.project("first"), self.project("second")
        originals = {project: service.role_path(project, "codex", "xy-backend").read_bytes() for project in (first, second)}
        plan = self.plan(None, {"xy-backend": {"model": "fixture-model"}})
        original_check = service.check
        def fail_second(project, host=None, *, state=None):
            if project == second:raise ValueError("fixture validation failure")
            return original_check(project, host, state=state)
        with patch.object(service, "check", fail_second), self.assertRaisesRegex(ValueError, "已条件撤回"):
            preferences.apply(plan)
        self.assertFalse((self.state / role_preferences.RELATIVE).exists())
        for project in (first, second):
            self.assertEqual(service.role_path(project, "codex", "xy-backend").read_bytes(), originals[project])
            self.assertFalse(project_service.project_status(self.state, project)["conflicts"])
        records = self.recovery_records()
        self.assertEqual(records[-1]["status"], "rolled_back")
        self.assertTrue(any(row.get("rollback_backup_id") for row in records[-1]["projects"]))

    def test_failure_retains_concurrent_project_edit_and_reports_conflict(self):
        first, second = self.project("first"), self.project("second")
        plan = self.plan(None, {"xy-backend": {"model": "fixture-model"}})
        original_check = service.check
        changed = []
        def fail_with_edit(project, host=None, *, state=None):
            if project == second:
                path = service.role_path(first, "codex", "xy-backend")
                path.write_bytes(path.read_bytes() + b"# external PRIVATE-MARKER\n")
                changed.append(path.read_bytes())
                raise ValueError("fixture failure")
            return original_check(project, host, state=state)
        with patch.object(service, "check", fail_with_edit), self.assertRaisesRegex(ValueError, "存在恢复冲突") as refused:
            preferences.apply(plan)
        self.assertNotIn("PRIVATE-MARKER", str(refused.exception))
        self.assertEqual(service.role_path(first, "codex", "xy-backend").read_bytes(), changed[-1])
        self.assertFalse((self.state / role_preferences.RELATIVE).exists())
        records = self.recovery_records()
        self.assertEqual(records[-1]["status"], "conflict")
        self.assertTrue(records[-1]["conflicts"])

    def test_global_publication_log_failure_restores_missing_state(self):
        project = self.project("publication")
        original = service.role_path(project, "codex", "xy-backend").read_bytes()
        plan = self.plan(None, {"xy-backend": {"model": "fixture-model"}})
        write_state = state_files.write_state
        failed = []
        def fail_applied(root, relative, data):
            if relative.startswith("preferences/transactions/") and json.loads(data)["status"] == "applied" and not failed:
                failed.append(True)
                raise OSError("fixture log publication failure")
            return write_state(root, relative, data)
        with patch.object(state_files, "write_state", fail_applied), self.assertRaisesRegex(ValueError, "已条件撤回"):
            preferences.apply(plan)
        self.assertTrue(failed)
        self.assertFalse((self.state / role_preferences.RELATIVE).exists())
        self.assertEqual(service.role_path(project, "codex", "xy-backend").read_bytes(), original)
        self.assertFalse(project_service.project_status(self.state, project)["conflicts"])

    def test_global_native_backup_restore_is_refused_when_sources_disagree(self):
        """全局物化与配置单独恢复均不得让当前权威和实际原生字段分歧。"""
        project = self.project("restore-sources")
        global_result = self.save(None, {"xy-backend": {"model": "fixture-model", "effort": "max"}})
        native_backup = next(row["backup_id"] for row in global_result["backups"] if row["project"] == str(project))
        config = project / ".agent-workflow/project.yaml"
        native = service.role_path(project, "codex", "xy-backend")
        global_path = self.state / role_preferences.RELATIVE
        before = {path: path.read_bytes() for path in (config, native, global_path)}
        binding = runtime_service.read_binding_record(self.state, project)[0]
        count = len(service.backups(self.state, project))
        with self.assertRaisesRegex(ValueError, "偏好来源不一致"):
            service.prepare_restore(self.state, project, native_backup)
        self.cli("restore", "--project", project, native_backup, "--apply", expected=2)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(runtime_service.read_binding_record(self.state, project)[0], binding)
        self.assertEqual(len(service.backups(self.state, project)), count)

        # 正常项目备份含适配器：按拟恢复适配器解析后仍等于备份原生字段，
        # 即使当前存在全局默认也能恢复，不能把安全拒绝扩成禁用所有 restore。
        changed = self.save(project, {"xy-backend": {"model": "project-model", "effort": "high"}})
        restore = service.prepare_restore(self.state, project, changed["backup_id"])
        service.commit(self.state, project, restore, lambda: service.check(project, "codex", state=self.state))
        self.assertEqual(config.read_bytes(), before[config])
        self.assertEqual(native.read_bytes(), before[native])
        self.assertEqual(global_path.read_bytes(), before[global_path])
        self.assertFalse(project_service.project_status(self.state, project)["conflicts"])

        # 明确覆盖的值恰好等于当时全局值时，项目保存只产生 CONFIG 备份。
        # 全局后来变化后恢复这个 CONFIG 会移除覆盖；没有 native 行也必须
        # 检查受影响角色，安全拒绝而非制造“来源新值、文件旧值”的反向旁路。
        same = self.save(project, {"xy-backend": {"model": "fixture-model", "effort": "max"}})
        record = next(row for row in service.backups(self.state, project) if row["id"] == same["backup_id"])
        self.assertEqual(record["files"], [".agent-workflow/project.yaml"])
        self.save(None, {"xy-backend": {"model": "project-model"}})
        after = {path: path.read_bytes() for path in (config, native, global_path)}
        with self.assertRaisesRegex(ValueError, "偏好来源不一致"):
            service.prepare_restore(self.state, project, same["backup_id"])
        self.assertEqual({path: path.read_bytes() for path in after}, after)
        self.assertEqual(preferences.view(self.state, project, "codex", "xy-backend")["model"], self.native(project)["model"])

    def test_restore_preview_rejects_changed_preference_sources(self):
        """确认前/验收期都检查来源，包含不在恢复目标列表中的项目配置。"""
        for source, phase in (("global", "before"), ("global", "verify"),
                              ("project-target", "before"), ("project-target", "verify"),
                              ("project-unrestored", "before"), ("project-unrestored", "verify")):
            with self.subTest(source=source, phase=phase):
                project = self.project(source + "-" + phase)
                config = project / ".agent-workflow/project.yaml"
                native = service.role_path(project, "codex", "xy-backend")
                if source == "project-unrestored":
                    # 复用真实全局事务使用的低层 native-only 物化器，截取其尚未
                    # 发布全局权威的中间状态；其备份 before 与当前宿主继承权威
                    # 相符，可以安全恢复。没有修改/伪造备份结构或旧版本兼容。
                    catalog = preferences.load_catalogs(self.state, project, "codex").catalog
                    changes = service.prepare(project, "codex", {"xy-backend": {"model": "fixture-model", "effort": "high"}},
                                              catalog, state=self.state, global_preferences={}, persist=False)
                    identifier = service.commit(self.state, project, changes)
                    self.assertTrue(all(row.relative != ".agent-workflow/project.yaml" for row in changes))
                else:
                    identifier = self.save(project, {"xy-backend": {"model": "fixture-model", "effort": "high"}})["backup_id"]
                plan = service.prepare_restore(self.state, project, identifier)
                count = len(service.backups(self.state, project))
                native_before = native.read_bytes()
                external = []
                global_path = self.state / role_preferences.RELATIVE
                def edit_source():
                    if source == "global":
                        # 不改变当前后端角色值，也必须使原先固定的全局来源身份
                        # 失效；fixture 写入的是测试全局文件，不触及用户配置。
                        state_files.write_state(self.state, role_preferences.RELATIVE,
                                            role_preferences.payload({"codex": {"xy-qa": {"effort": "high"}}}))
                        external.append((global_path, global_path.read_bytes()))
                    else:
                        config.write_bytes(config.read_bytes() + b"\n# concurrent preference source\n")
                        external.append((config, config.read_bytes()))
                if phase == "before":edit_source()
                with self.assertRaises(ValueError):
                    service.commit(self.state, project, plan, edit_source if phase == "verify" else None)
                self.assertEqual(native.read_bytes(), native_before)
                self.assertEqual(external[0][0].read_bytes(), external[0][1])
                backups = service.backups(self.state, project)
                if phase == "before":
                    self.assertEqual(len(backups), count)
                else:
                    self.assertEqual(len(backups), count + 1)
                    self.assertTrue(any(row["status"] in {"rolled_back", "conflict"} for row in backups))
                if global_path.exists():global_path.unlink()

    def test_activation_plan_rejects_changed_global_and_unsafe_private_paths(self):
        project = self.project("activation", enabled=False)
        activation = project_service.preview_project(self.state, project, "enable", content_id=self.core.content_id)
        self.save(None, {"xy-backend": {"model": "fixture-model"}})
        with self.assertRaisesRegex(ValueError, "全局角色偏好"):
            project_service.apply_project(activation)
        self.assertFalse((project / ".agent-workflow").exists())
        path = self.state / role_preferences.RELATIVE
        path.unlink()
        outside = self.case / "outside"
        outside.write_bytes(b"PRIVATE-CONFIG")
        path.symlink_to(outside)
        with self.assertRaises(ValueError):preferences.view(self.state, None, "codex", "xy-backend")
        self.assertEqual(outside.read_bytes(), b"PRIVATE-CONFIG")
        path.unlink()
        os.link(outside, path)
        with self.assertRaises(ValueError):preferences.view(self.state, None, "codex", "xy-backend")
        path.unlink()

    def test_global_old_descriptor_save_is_retained_and_refused(self):
        self.save(None, {"xy-backend": {"model": "fixture-model"}})
        path = self.state / role_preferences.RELATIVE
        original = path.read_bytes()
        plan = self.plan(None, {"xy-backend": {"effort": "max"}})
        write = state_files.AnchoredFile.write
        triggered = []
        with path.open("r+b") as old:
            def edit_after_publication(target, data, mode, expected=None):
                result = write(target, data, mode, expected)
                if target.path == path and data == plan.global_after and not triggered:
                    triggered.append(True)
                    old.seek(0);old.write(b"PRIVATE-LATE-GLOBAL-SAVE");old.truncate();old.flush()
                return result
            with patch.object(state_files.AnchoredFile, "write", edit_after_publication), self.assertRaisesRegex(ValueError, "存在恢复冲突") as rejected:
                preferences.apply(plan)
        self.assertTrue(triggered)
        self.assertNotIn("PRIVATE-LATE", str(rejected.exception))
        self.assertEqual(path.read_bytes(), original)
        records = [record for record in self.recovery_records() if record["status"] == "conflict"]
        self.assertEqual(len(records), 1)
        retained = Path(records[0]["conflicts"][0]["retained_path"])
        self.assertEqual(retained.read_bytes(), b"PRIVATE-LATE-GLOBAL-SAVE")

    def test_direct_commit_shares_cross_thread_coordination(self):
        project = self.project("coordination")
        catalog = preferences.load_catalogs(self.state, project, "codex").catalog
        changes = service.prepare(project, "codex", {"xy-backend": {"model": "fixture-model"}}, catalog, state=self.state)
        original = service.role_path(project, "codex", "xy-backend").read_bytes()
        registered = self.case / "registered-only"
        registered.mkdir()
        registration = project_service.preview_project(self.state, registered, "add")
        registry_before = (self.state / "projects.json").read_bytes()
        with role_preferences.coordination(self.state):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(service.commit, self.state, project, changes)
                with self.assertRaisesRegex(ValueError, "正在由另一管理操作"):
                    future.result(timeout=5)
                # 仅登记同样会改变全局影响集合，必须先取 preferences 再取 registry；
                # 拒绝后既不能写登记表，也不能创建目标项目工作流目录。
                registration_future = executor.submit(project_service.apply_project, registration)
                with self.assertRaisesRegex(ValueError, "正在由另一管理操作"):
                    registration_future.result(timeout=5)
            self.assertEqual((self.state / "projects.json").read_bytes(), registry_before)
            self.assertFalse((registered / ".agent-workflow").exists())
            self.assertEqual(service.role_path(project, "codex", "xy-backend").read_bytes(), original)
            # 当前线程同栈重入允许全局事务复用原提交器，且仍持有跨进程目录锁。
            self.assertIsNotNone(service.commit(self.state, project, changes))
            self.assertTrue(project_service.apply_project(registration)["registered"])
        self.assertEqual(self.native(project)["model"], "fixture-model")

    @unittest.skipUnless(hasattr(os, "fork"), "当前平台没有 fork 进程语义")
    def test_fork_cannot_reenter_parent_coordination(self):
        """真实子进程不能把复制到的线程局部集合当作父进程的重入凭据。"""
        with role_preferences.coordination(self.state):
            reader, writer = os.pipe()
            child = os.fork()
            if child == 0:
                os.close(reader)
                status = 1
                try:
                    with role_preferences.coordination(self.state):
                        message = b"entered"
                except ValueError:
                    status, message = 0, b"refused"
                except BaseException:
                    status, message = 2, b"unexpected"
                os.write(writer, message);os.close(writer)
                os._exit(status)
            os.close(writer)
            try:
                message = os.read(reader, 32)
                waited, status = os.waitpid(child, 0)
            finally:
                os.close(reader)
            self.assertEqual(waited, child)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            self.assertEqual(message, b"refused")

    def test_native_global_app_edit_previews_and_saves_without_self_invalidation(self):
        """最终组合走真实 App/executor/stdio；只用屏幕适配器替代终端设备。"""
        from tests.test_manager_tui import RecordingScreen

        first, second = self.project("first"), self.project("second")
        native_config = self.home / ".codex/config.toml"
        native_config.write_text('model="fixture-model"\n')
        fixture = fixtures.CatalogTest()
        fixture.home = self.home
        native_env = fixture.native_fixture(
            [{"data": [fixture.native_row("fixture-model"), fixture.native_row("project-model")],
              "nextCursor": None}], mode="scope", cache_identity="opaque-app-scope")
        calls_path = self.home / "native-calls"
        processes = []
        original_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            # 记录真实句柄而非替换查询结果；native 的生产 close/wait 必须结算，
            # 即使后续断言失败，executor 上下文仍负责等待已提交的实际作业。
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process

        def calls():
            return calls_path.read_bytes() if calls_path.exists() else b""

        with patch.dict(os.environ, native_env), \
                patch("manager.codex_models.subprocess.Popen", side_effect=spawn), \
                ThreadPoolExecutor(max_workers=1) as executor:
            app = fixtures.App(self.state, self.case, first)
            app.executor = executor
            app.screen = RecordingScreen()

            def settle():
                self.assertIsNotNone(app.future, app.toast)
                result = app.future.result(timeout=20)
                app.poll_job()
                self.assertIsNone(app.future)
                self.assertNotEqual(app.modal, "error", app.text)
                return result

            def draw_without_native():
                before = calls()
                with patch("manager.tui.curses.curs_set"):
                    app.draw()
                    app.draw()
                self.assertEqual(calls(), before, "普通绘制不得启动或补跑原生目录")

            def refused_preview():
                # 新UI沿真实executor预览：本地stamp失效抛来源错误，服务来源
                # 失效形成明确model-catalog冲突。二者都必须结算且不可应用，
                # 不能把仍在busy或任意其它error当成原授权守卫已通过。
                self.assertIsNotNone(app.future, app.toast)
                try:
                    plan = app.future.result(timeout=20)
                except ValueError as failure:
                    self.assertIn("来源", str(failure))
                    app.poll_job()
                    self.assertEqual(app.modal, "error", app.text)
                    self.assertIn("来源", app.text)
                else:
                    app.poll_job()
                    self.assertEqual(app.modal, "preview", app.toast)
                    self.assertFalse(plan.summary["can_apply"])
                    self.assertTrue(any(row["path"] == "model-catalog" and "来源" in row["reason"]
                                        for row in plan.summary["conflicts"]), plan.summary)
                self.assertIsNone(app.future)
                app.dispatch("esc")
                self.assertIsNone(app.modal)

            def choose(value):
                options = app.options()
                position = next(index for index, (_, item) in enumerate(options) if item == value)
                app.dispatch("home")
                for _ in range(position):
                    app.dispatch("down")
                app.dispatch("enter")

            # 通过用户真实导航进入全局，触发受控 load_display；禁止直接改索引
            # 绕过 P2 的显示上下文，角色与选择器同样使用实际键盘动作定位。
            app.dispatch("left")
            app.dispatch("home")
            app.dispatch("right")
            self.assertTrue(app.global_scope)
            self.assertIsNone(app.project)
            app.dispatch("home")
            for _ in range(app.role_list().index("xy-backend")):
                app.dispatch("down")
            self.assertEqual(app.role, "xy-backend")
            draw_without_native()
            self.assertEqual(calls(), b"")

            app.dispatch("m")
            settle()
            self.assertEqual(app.modal, "model", app.toast)
            bundle = app.catalogs[(app.scope_id, app.host)]
            self.assertTrue(preferences.check_catalogs(self.state, None, "codex", bundle))
            acquired = calls()
            self.assertEqual(sum(json.loads(line)["method"] == "model/list" for line in acquired.splitlines()), 3)
            self.assertNotIn("stale-cache-only", [row.id for row in app.catalog().models])
            draw_without_native()
            choose("fixture-model")
            self.assertEqual(app.modal, "effort")
            choose("max")
            self.assertIsNone(app.modal)
            self.assertEqual(app.pending(), {"xy-backend": {"model": "fixture-model", "effort": "max"}})
            draw_without_native()
            app.dispatch("s")
            settle()
            self.assertEqual(app.modal, "preview", app.toast)
            self.assertTrue(app.preference_plan.summary["can_apply"], app.text)
            self.assertEqual({row["project"] for row in app.preference_plan.summary["affected_projects"]},
                             {str(first), str(second)})
            draw_without_native()
            app.dispatch("enter")
            result = settle()
            self.assertTrue(result["applied"])
            self.assertEqual(len(result["backups"]), 2)
            self.assertEqual(app.modal, "result", app.text)
            self.assertFalse(app.pending())
            self.assertEqual(calls(), acquired, "暂存、预览、应用守卫及保存后刷新不得补跑 native")
            for project in (first, second):
                self.assertEqual(self.native(project), {"model": "fixture-model", "effort": "max"})
            draw_without_native()
            app.dispatch("esc")

            # 保存后另起真实草稿，再改变已经发布的提供方来源。显示刷新与显式
            # 重取新目录均不能给旧草稿续期，s 必须保留原 expected/stamp 拒绝。
            app.dispatch("e")
            settle()
            choose("high")
            key = app.scope()
            original_expected = json.loads(json.dumps(app.expected[key]))
            original_stamp = app.source_stamps[key]
            original_draft = dict(app.drafts[key])
            saved_global = (self.state / role_preferences.RELATIVE).read_bytes()
            native_config.write_text('model="fixture-model"\nmodel_provider="external-provider"\n')
            before_refusal = calls()
            app.dispatch("s")
            refused_preview()
            self.assertIsNone(app.modal)
            draw_without_native()
            app.dispatch("r")
            settle()
            self.assertEqual(calls(), before_refusal, "失效拒绝及显示刷新不得补跑 native")
            app.dispatch("e")
            settle()
            self.assertEqual(app.modal, "effort")
            self.assertNotEqual(app.catalog().stamp, original_stamp)
            draw_without_native()
            app.dispatch("esc")
            after_explicit_reload = calls()
            app.dispatch("s")
            refused_preview()
            self.assertIsNone(app.modal)
            self.assertEqual(calls(), after_explicit_reload)
            self.assertEqual(app.expected[key], original_expected)
            self.assertEqual(app.source_stamps[key], original_stamp)
            self.assertEqual(app.drafts[key], original_draft)
            self.assertEqual((self.state / role_preferences.RELATIVE).read_bytes(), saved_global)
            for project in (first, second):
                self.assertEqual(self.native(project), {"model": "fixture-model", "effort": "max"})
            self.assertEqual(sum(json.loads(line)["method"] == "model/list" for line in calls().splitlines()), 9)
            self.assertTrue(processes)
            self.assertTrue(all(process.returncode is not None for process in processes))
            self.assertIsNone(app.future)
            print("App原生全局组合：实际导航/双项目保存/零隐式native/换源拒绝/旧授权保留；"
                  "已结算子进程=" + str([(process.pid, process.returncode) for process in processes]))
        print("App原生全局组合：真实executor已shutdown/wait，独占fixture随后由tearDownClass清理。")

    def test_claude_app_save_and_source_conflicts_keep_original_authorization(self):
        """真实 App/executor/文件服务验证来源链；只替换屏幕与 curses 设备适配。"""
        from tests.test_manager_tui import RecordingScreen

        first, second = self.project("first"), self.project("second")
        config_path = self.home / ".claude/settings.json"
        settings = {"model": "masked-top-model", "env": {
            "ANTHROPIC_MODEL": "fixture-model", "ANTHROPIC_BASE_URL": "file-endpoint",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "file-opus", "CLAUDE_CODE_USE_VERTEX": "",
            "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1",
            "AWS_ENDPOINT_URL": "https://sdk-first.example.com"},
            "modelPicker": {"options": [{"model": "fixture-model"}, {"model": "project-model"}]}}
        config_path.write_text(json.dumps(settings))
        for project in (first, second):
            # 安装器已在此共享文件放入受管 Hooks。测试只追加菜单，保留原 Hook
            # 前像，避免把“破坏已安装资源”的 fixture 冲突误判为模型来源问题。
            project_settings_path = project / ".claude/settings.json"
            project_settings = json.loads(project_settings_path.read_text())
            project_settings["modelPicker"] = {"options": [{"model": "ignored-project-menu"}]}
            project_settings_path.write_text(json.dumps(project_settings))
        # 复用原生可执行 fixture 作为零调用哨兵。它只会在真实 Popen 时生成 pid，
        # 无需 mock 目录或业务函数；若错误调用，也由现有 query 的 close/wait 结算。
        fixture = fixtures.CatalogTest()
        fixture.home = self.home
        environment = fixture.native_fixture([{"data": [], "nextCursor": None}])
        environment.update(ANTHROPIC_MODEL="shell-model", ANTHROPIC_BASE_URL="shell-endpoint",
                           ANTHROPIC_DEFAULT_OPUS_MODEL="shell-opus", CLAUDE_CODE_USE_VERTEX="1")
        with patch.dict(os.environ, environment), ThreadPoolExecutor(max_workers=1) as executor:
            app = fixtures.App(self.state, self.case, first)
            app.executor = executor
            app.screen = RecordingScreen()

            def settle():
                self.assertIsNotNone(app.future, app.toast)
                result = app.future.result(timeout=20)
                app.poll_job()
                self.assertIsNone(app.future)
                self.assertNotEqual(app.modal, "error", app.text)
                return result

            def draw_without_native():
                with patch("manager.tui.curses.curs_set"):
                    app.draw()
                    app.draw()
                self.assertFalse((self.home / "native-pid").exists(), "Claude 本地绘制/预览/守卫不得调用 native")

            def refused_preview():
                # 与正式异步入口同一future/回调结算，仍严格要求对应的来源或
                # model-catalog冲突，随后保持原草稿、来源stamp和落盘字节断言。
                self.assertIsNotNone(app.future, app.toast)
                try:
                    plan = app.future.result(timeout=20)
                except ValueError as failure:
                    self.assertIn("来源", str(failure))
                    app.poll_job()
                    self.assertEqual(app.modal, "error", app.text)
                    self.assertIn("来源", app.text)
                else:
                    app.poll_job()
                    self.assertEqual(app.modal, "preview", app.toast)
                    self.assertFalse(plan.summary["can_apply"])
                    self.assertTrue(any(row["path"] == "model-catalog" and "来源" in row["reason"]
                                        for row in plan.summary["conflicts"]), plan.summary)
                self.assertIsNone(app.future)
                app.dispatch("esc")
                self.assertIsNone(app.modal)

            def choose(value):
                position = next(index for index, (_, item) in enumerate(app.options()) if item == value)
                app.dispatch("home")
                for _ in range(position):
                    app.dispatch("down")
                app.dispatch("enter")

            def scope(project):
                app.dispatch("left")
                app.dispatch("home")
                if project is not None:
                    for _ in range(1 + app.projects.index(project)):
                        app.dispatch("down")
                app.dispatch("right")
                self.assertEqual(app.project, project)
                app.dispatch("home")
                for _ in range(app.role_list().index("xy-backend")):
                    app.dispatch("down")

            def save_pending():
                app.dispatch("s")
                settle()
                self.assertEqual(app.modal, "preview", app.toast)
                self.assertTrue(app.preference_plan.summary["can_apply"], app.text)
                draw_without_native()
                app.dispatch("enter")
                result = settle()
                self.assertTrue(result["applied"])
                self.assertFalse(app.pending())
                app.dispatch("esc")
                return result

            app.dispatch("2")
            self.assertEqual(app.host, "claude")
            scope(None)
            draw_without_native()
            app.dispatch("m")
            settle()
            self.assertIn("fixture-model", [row.id for row in app.catalog().models])
            self.assertNotIn("shell-model", [row.id for row in app.catalog().models])
            self.assertNotIn("ignored-project-menu", [row.id for row in app.catalog().models])
            choose("fixture-model")
            choose("max")
            global_path = self.state / role_preferences.RELATIVE
            before = {project: service.role_path(project, "claude", "xy-backend").read_bytes()
                      for project in (first, second)}
            app.dispatch("s")
            settle()
            self.assertEqual(app.modal, "preview", app.toast)
            self.assertTrue(app.preference_plan.summary["can_apply"], app.preference_plan.summary)
            self.assertEqual({row["project"] for row in app.preference_plan.summary["affected_projects"]},
                             {str(first), str(second)})
            draw_without_native()
            app.dispatch("esc")
            self.assertFalse(global_path.exists(), "取消预览不得发布全局偏好")
            self.assertEqual(before, {project: service.role_path(project, "claude", "xy-backend").read_bytes()
                                      for project in (first, second)})
            result = save_pending()
            self.assertEqual(len(result["backups"]), 2)
            for project in (first, second):
                self.assertEqual(self.native(project, "claude"), {"model": "fixture-model", "effort": "max"})

            # 项目覆盖、明确 inherit、reset 都消费同一真实目录与偏好服务；未编辑
            # 的 effort 仍跟随全局，另一个项目不受项目范围的保存影响。
            scope(first)
            for model in ("project-model", "inherit"):
                app.dispatch("m")
                settle()
                choose(model)
                choose(None)
                save_pending()
                view = preferences.view(self.state, first, "claude", "xy-backend")
                self.assertEqual(view["overrides"], {"model": model})
                self.assertEqual(view["sources"]["model"], "host" if model == "inherit" else "project")
                self.assertEqual(self.native(second, "claude"), {"model": "fixture-model", "effort": "max"})
            app.manage_action("reset-model")
            if app.future is not None:
                settle()
            save_pending()
            self.assertEqual(preferences.view(self.state, first, "claude", "xy-backend")["sources"],
                             {"model": "global", "effort": "global"})

            scope(None)
            app.dispatch("e")
            settle()
            choose("high")
            key = app.scope()
            original_expected = json.loads(json.dumps(app.expected[key]))
            original_stamp = app.source_stamps[key]
            original_draft = dict(app.drafts[key])
            persisted = {global_path: global_path.read_bytes(), **{
                service.role_path(project, "claude", "xy-backend"):
                service.role_path(project, "claude", "xy-backend").read_bytes() for project in (first, second)}}
            os.environ.update(ANTHROPIC_MODEL="masked-shell-changed", ANTHROPIC_BASE_URL="masked-shell-endpoint",
                              ANTHROPIC_DEFAULT_OPUS_MODEL="masked-shell-opus", CLAUDE_CODE_USE_VERTEX="0")
            app.dispatch("s")
            settle()
            self.assertEqual(app.modal, "preview", app.toast)
            self.assertTrue(app.preference_plan.summary["can_apply"], app.text)
            app.dispatch("esc")
            for changed_source in ("file-model", "provider-route", "sdk-endpoint"):
                with self.subTest(changed_source=changed_source):
                    if changed_source == "sdk-endpoint":
                        # 上一分支结束已恢复文件，但缓存仍持有换源后的目录；显式
                        # 重开编辑只刷新显示，不续期原草稿，再用原来源形成真实预览。
                        # 异步来源错误会清除显示资格；先沿真实r入口重新读取角色，
                        # 不得把“角色已移除”的更早拒绝冒充后续SDK来源守卫。
                        app.dispatch("r")
                        settle()
                        app.dispatch("e")
                        settle()
                        app.dispatch("esc")
                    if changed_source in {"file-model", "sdk-endpoint"}:
                        # 先形成可应用的真实预览，再换源并确认，直接覆盖 apply 的
                        # 二次守卫；只在预览入口拒绝不足以证明这一竞态不会落盘。
                        app.dispatch("s")
                        settle()
                        self.assertEqual(app.modal, "preview", app.toast)
                        self.assertTrue(app.preference_plan.summary["can_apply"], app.text)
                    changed = json.loads(json.dumps(settings))
                    if changed_source == "file-model":
                        changed["env"]["ANTHROPIC_MODEL"] = "project-model"
                    elif changed_source == "sdk-endpoint":
                        changed["env"]["AWS_ENDPOINT_URL"] = "https://sdk-second.example.com"
                    else:
                        changed["env"]["CLAUDE_CODE_USE_BEDROCK"] = ""
                        changed["env"]["CLAUDE_CODE_USE_VERTEX"] = "1"
                    config_path.write_text(json.dumps(changed))
                    if changed_source in {"file-model", "sdk-endpoint"}:
                        app.dispatch("enter")
                        self.assertIsNotNone(app.future)
                        with self.assertRaisesRegex(ValueError, "来源"):
                            app.future.result(timeout=20)
                        app.poll_job()
                        self.assertIsNone(app.future)
                        self.assertEqual(app.modal, "error")
                        self.assertIn("来源", app.text)
                        self.assertEqual({path: path.read_bytes() for path in persisted}, persisted)
                        app.dispatch("esc")
                        self.assertIsNone(app.modal, "失败不得复活已失效的确认页")
                    app.dispatch("s")
                    refused_preview()
                    self.assertIsNone(app.modal)
                    draw_without_native()
                    app.dispatch("r")
                    settle()
                    app.dispatch("e")
                    settle()
                    self.assertEqual(app.modal, "effort")
                    self.assertNotEqual(app.catalog().stamp, original_stamp)
                    app.dispatch("esc")
                    app.dispatch("s")
                    refused_preview()
                    self.assertIsNone(app.modal)
                    self.assertEqual(app.expected[key], original_expected)
                    self.assertEqual(app.source_stamps[key], original_stamp)
                    self.assertEqual(app.drafts[key], original_draft)
                    self.assertEqual({path: path.read_bytes() for path in persisted}, persisted)
                    config_path.write_text(json.dumps(settings))
            draw_without_native()
            self.assertIsNone(app.future)
            print("Claude真实App：全局取消不写/确认双落盘/项目覆盖-inherit-reset/遮住shell不误伤/"
                  "文件env与路由换源拒绝/预览后文件env及SDK端点换源apply拒绝/刷新不续期；native启动数=0。")
        print("Claude真实App：executor已shutdown/wait，无自有native进程；fixture由tearDownClass关闭清理。")

    def test_real_cli_global_project_single_fields_resets_and_safe_refusals(self):
        project = self.project("cli")
        args = ("set", "--global", "--platform", "codex", "--role", "xy-backend")
        result = self.cli(*args, "--model", "fixture-model")["result"]
        self.assertFalse(result["applied"])
        self.assertEqual((result["model"], result["effort"]), ("fixture-model", "inherit"))
        self.assertFalse((self.state / role_preferences.RELATIVE).exists())
        self.cli(*args, "--model", "fixture-model", "--apply")
        self.cli("set", "--project", project, "--platform", "codex", "--role", "xy-backend", "--effort", "max", "--apply")
        values = self.cli("roles", "--project", project, "--platform", "codex")
        self.assertEqual(values["xy-backend"]["overrides"], {"effort": "max"})
        self.cli("set", "--project", project, "--platform", "codex", "--role", "xy-backend", "--reset", "all", "--apply")
        self.assertEqual(self.native(project), {"model": "fixture-model", "effort": "inherit"})
        self.cli(*args, "--reset", "model", "--apply")
        self.assertEqual(self.native(project)["model"], "inherit")
        self.cli(*args, expected=2)
        self.cli(*args, "--model", "fixture-model", "--reset", "model", expected=2)
        self.cli(*args, "--project", project, "--effort", "max", expected=2)
        path = self.state / role_preferences.RELATIVE
        path.write_text('{"private":"DO-NOT-ECHO"}')
        refused = self.cli("roles", "--global", "--platform", "codex", expected=2)
        self.assertNotIn("DO-NOT-ECHO", json.dumps(refused))


if __name__ == "__main__":
    unittest.main()


class WindowsModelArchiveContractTest(unittest.TestCase):
    """只覆盖计划 mode 投影与历史 ACL 的区别；真实归档走 Windows 组合节点。"""

    def test_planned_content_projection_does_not_relax_archive_identity_or_acl(self):
        from contextlib import nullcontext
        import hashlib
        from types import SimpleNamespace
        from lib.central import runtime_project
        node = runtime_project.Node("file", b"archived", 0o600,
                                   (1, 2, stat.S_IFREG | 0o600, 1, 8, 5, 6), "a" * 64)
        version = {"path": "archive", "expected_sha": hashlib.sha256(node.payload).hexdigest(),
                   "mode": node.mode, "identity": list(node.identity), "security": node.security}
        project = Path("/owned-project")
        with patch.object(runtime_project, "os", SimpleNamespace(name="nt")):
            self.assertTrue(state_files.same_file_state((b"same", 0o600), (b"same", 0o644)))
            self.assertFalse(state_files.same_file_state((b"same", 0o444), (b"same", 0o600)))
        with patch.object(service, "os", SimpleNamespace(name="nt")), \
                patch.object(state_files, "AnchoredFile", side_effect=lambda *args: nullcontext(SimpleNamespace(directory=1, name="archive"))):
            with patch.object(service, "read_at", return_value=node):
                service.check_versions(project, [version])
            for changed in (runtime_project.Node(node.kind, node.payload, node.mode, node.identity, "b" * 64),
                            runtime_project.Node(node.kind, node.payload, node.mode, (1, 99, *node.identity[2:]), node.security),
                            runtime_project.Node(node.kind, node.payload, 0o666, node.identity, node.security)):
                with self.subTest(changed_mode=changed.mode), patch.object(service, "read_at", return_value=changed), \
                        self.assertRaises(state_files.PreservedEdit):
                    service.check_versions(project, [version])
            for invalid in ({key: value for key, value in version.items() if key != "security"},
                            {**version, "identity": []}, {**version, "unknown": True}):
                with self.assertRaises(ValueError):
                    service.check_versions(project, [invalid])
        with patch.object(runtime_project, "os", SimpleNamespace(name="posix")):
            self.assertFalse(state_files.same_file_state((b"same", 0o600), (b"same", 0o644)))
