"""唯一验证入口的进程级合同；受控运行时只记录边界，测试仍由真实 unittest 执行。"""

import base64
import json
import importlib.util
import io
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import patch


PACK = Path(__file__).resolve().parents[1]


class ValidationRunnerTest(unittest.TestCase):
    def setUp(self):
        # 入口必须能离开仓根执行。每例仅创建短命的最小协议夹具，不复制产品源码、
        # 运行时或依赖缓存；TemporaryDirectory 统一拥有并回收本例全部文件。
        self.temporary = tempfile.TemporaryDirectory(prefix="validation-runner-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source with spaces"
        self.source.mkdir()
        self.caller = self.root / "caller"
        self.caller.mkdir()
        (self.source / "scripts").mkdir()
        (self.source / "lib").mkdir()
        (self.source / "tests").mkdir()
        (self.source / "tests/__init__.py").write_text("", encoding="utf-8")
        for name in ("workflow", "codex", "claude", "antigravity", "prototype"):
            shutil.copyfile(PACK / f"scripts/test_{name}.sh", self.source / f"scripts/test_{name}.sh")
        shutil.copyfile(PACK / "scripts/test_workflow.py", self.source / "scripts/test_workflow.py")
        self.runtime_calls = self.source / "runtime.calls"
        self.case_calls = self.source / "case.calls"
        runtime = (
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            'printf "%s\\0" "$PWD" "$@" >> ' + shlex.quote(str(self.runtime_calls)) + '\n'
            'exec ' + shlex.quote(sys.executable) + ' "$@"\n'
        )
        (self.source / "lib/python_runtime.sh").write_text(runtime, encoding="utf-8")
        self.environment = {**os.environ, "AGENT_WORKFLOW_PYTHON": sys.executable}
        for module in ("codex_workflow", "claude_workflow", "claude_instructions",
                       "antigravity_workflow", "prototype_workspace", "shared_memory_contract"):
            methods = ("test_one", "test_two") if module == "shared_memory_contract" else ("test_ok",)
            self.write_case(module, methods)
        self.write_case("runner_failure", ("test_failure",), failing=True)

    def write_case(self, module, methods, *, failing=False):
        body = '''import json
from pathlib import Path
import sys
import unittest

class ExampleTest(unittest.TestCase):
'''
        for method in methods:
            body += f'''    def {method}(self):
        with Path({str(self.case_calls)!r}).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({{"id": self.id(), "cwd": str(Path.cwd()),
                                     "python": sys.executable, "no_bytecode": sys.dont_write_bytecode,
                                     "utf8": sys.flags.utf8_mode}}) + "\\n")
'''
            if failing:
                body += '        self.fail("受控 unittest 失败，必须传回入口且不得重试")\n'
        (self.source / f"tests/test_{module}.py").write_text(body, encoding="utf-8")

    def invoke(self, *arguments, entry=None):
        # 所有子进程均有总时限；失败输出由断言保留，父测试不重试或吞掉退出状态。
        return subprocess.run(
            ["bash", str(entry or self.source / "scripts/test_workflow.sh"), *arguments],
            cwd=self.caller, env=self.environment, capture_output=True, text=True, timeout=40,
        )

    def recorded_cases(self):
        if not self.case_calls.exists():
            return []
        return [json.loads(line) for line in self.case_calls.read_text(encoding="utf-8").splitlines()]

    def test_no_arguments_and_help_do_not_run_tests(self):
        for arguments in ((), ("--help",)):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("full", result.stdout)
                self.assertIn("--list", result.stdout)
                self.assertEqual([], self.recorded_cases())

    def test_unknown_arguments_groups_and_nodes_reject_before_any_case(self):
        invalid = (
            "--unknown", "typo", "tests.test_missing", "tests.test_codex_workflow.Missing",
            "tests.test_codex_workflow.ExampleTest.missing",
            "tests.test_codex_workflow.ExampleTest.setUp", "../tests/test_codex_workflow.py",
        )
        for argument in invalid:
            with self.subTest(argument=argument):
                self.case_calls.unlink(missing_ok=True)
                result = self.invoke("codex", argument)
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                self.assertIn("error:", result.stderr)
                self.assertEqual([], self.recorded_cases())

    def test_groups_deduplicate_shared_targets_in_list_and_execution(self):
        result = self.invoke("--list", "codex", "claude", "codex")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([
            "tests.test_codex_workflow", "tests.test_shared_memory_contract",
            "tests.test_claude_workflow", "tests.test_claude_instructions",
        ], result.stdout.splitlines())
        self.assertEqual([], self.recorded_cases())
        result = self.invoke("codex", "claude", "codex")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        cases = self.recorded_cases()
        self.assertEqual(5, len(cases))
        self.assertEqual(5, len({row["id"] for row in cases}))

    def test_parent_target_suppresses_child_nodes_in_either_order(self):
        parent = "tests.test_shared_memory_contract"
        child = parent + ".ExampleTest.test_one"
        for targets in ((parent, child), (child, parent)):
            with self.subTest(targets=targets):
                result = self.invoke("--list", *targets)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([parent], result.stdout.splitlines())
        result = self.invoke(child, parent)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(self.recorded_cases()))

    def test_explicit_method_runs_only_that_case(self):
        target = "tests.test_shared_memory_contract.ExampleTest.test_two"
        result = self.invoke(target)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual([target], [row["id"] for row in self.recorded_cases()])

    def test_physical_source_root_and_existing_runtime_flags_from_other_cwd(self):
        alias = self.root / "source alias"
        alias.symlink_to(self.source, target_is_directory=True)
        target = "tests.test_codex_workflow.ExampleTest.test_ok"
        result = self.invoke(target, entry=alias / "scripts/test_workflow.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        invocation = self.runtime_calls.read_bytes().decode().split("\0")[:-1]
        self.assertEqual([str(self.source), "-B", "-X", "utf8",
                          str(self.source / "scripts/test_workflow.py"), target], invocation)
        [case] = self.recorded_cases()
        self.assertEqual(str(self.source), case["cwd"])
        self.assertEqual(sys.executable, case["python"])
        self.assertTrue(case["no_bytecode"])
        self.assertEqual(1, case["utf8"])
        self.assertEqual([], list(self.source.rglob("*.pyc")))

    def test_unittest_failure_is_nonzero_and_runs_once(self):
        result = self.invoke("tests.test_runner_failure")
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("FAILED (failures=1)", result.stderr)
        self.assertIn("受控 unittest 失败", result.stderr)
        self.assertEqual(1, len(self.recorded_cases()))

    def test_runtime_failure_exit_status_is_preserved(self):
        (self.source / "lib/python_runtime.sh").write_text("exit 23\n", encoding="utf-8")
        result = self.invoke("codex")
        self.assertEqual(23, result.returncode, result.stdout + result.stderr)
        self.assertEqual([], self.recorded_cases())

    def test_full_is_explicit_and_lists_each_existing_module_once(self):
        result = self.invoke("--list", "full", "codex")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        expected = ["tests." + path.stem for path in sorted((self.source / "tests").glob("test_*.py"))]
        self.assertEqual(expected, result.stdout.splitlines())
        self.assertEqual([], self.recorded_cases())

    def test_legacy_entries_keep_original_module_scope(self):
        expected = {
            "codex": {"codex_workflow", "shared_memory_contract"},
            "claude": {"claude_workflow", "claude_instructions", "shared_memory_contract"},
            "antigravity": {"antigravity_workflow"},
            "prototype": {"prototype_workspace"},
        }
        for host, modules in expected.items():
            with self.subTest(host=host):
                self.case_calls.unlink(missing_ok=True)
                result = self.invoke(entry=self.source / f"scripts/test_{host}.sh")
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                actual = {row["id"].split(".")[1].removeprefix("test_") for row in self.recorded_cases()}
                self.assertEqual(modules, actual)

    def test_real_central_service_ci_include_212_consumers_without_duplicates(self):
        # 单独核对真实ci，避免central组已含runtime_state而掩盖ci漏纳该模块；
        # 再核对组合计划去重，确保重叠组不会重复执行有状态的容量/恢复测试。
        spec = importlib.util.spec_from_file_location("validation_shared_ci_contract", PACK / "scripts/test_workflow.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        read_preparation = tuple("tests.test_central_project.CentralProjectTest." + name for name in (
            "test_model_commit_read_preparation_keeps_callback_boundary_and_single_scan",
            "test_model_commit_read_preparation_rejects_finish_and_mutable_drift_before_write",
        ))
        central_preview = tuple("tests.test_central_project.CentralProjectTest." + name for name in (
            "test_project_previews_share_read_operation_and_preserve_source_inspection",
            "test_central_preview_separates_pins_and_withholds_plan_on_exit_drift",
        ))
        role_final_read = tuple("tests.test_role_preferences.RolePreferencesTest." + name for name in (
            "test_native_global_unchanged_projects_batch_final_read_phase",
            "test_native_global_unchanged_projects_recheck_original_observation_and_compensate",
        ))
        # 中央保存/预览边界必须实际进入 ordinary 原生组；RolePrefs 仍含 POSIX 前置，
        # 只核对精准 ci，不能因方法带 native 字样就混入 Windows 清单。
        boundaries = runner.NATIVE_COMPONENTS["windows-native-central-boundaries"]
        self.assertEqual("ordinary", boundaries["qualification"])
        self.assertTrue(set(read_preparation + central_preview).issubset(runner.component_targets(boundaries)))
        self.assertIn("tests.test_central_project.WindowsStageConsumerNativeTest", runner.component_targets(boundaries))
        libraries = runner.NATIVE_COMPONENTS["windows-native-libraries"]
        self.assertIn("tests.test_antigravity_windows_native.AntigravityStageWindowsNativeTest", runner.component_targets(libraries))
        budget = tuple("tests.test_antigravity_windows_native.AntigravityFileBudgetTest." + name for name in (
            "test_large_root_publication_restore_and_cleanup_keep_original_eight_mib_boundary",
            "test_merged_overflow_controlled_docs_and_codex_caps_reject_before_stage_or_backup",
        ))
        self.assertTrue(set(budget).issubset(libraries["portable_ci_targets"]))
        ownership = runner.NATIVE_COMPONENTS["windows-native-security-ownership"]
        self.assertEqual("elevated", ownership["qualification"])
        self.assertFalse(ownership["node_required"] or ownership["curses_required"])
        self.assertTrue(set(role_final_read).isdisjoint(runner.GROUPS["windows-native"]))
        for selectors in (("ci",),("central","service","ci")):
            with self.subTest(selectors=selectors):
                result=self.invoke("--list",*selectors,entry=PACK/"scripts/test_workflow.sh")
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                targets=result.stdout.splitlines();self.assertEqual(len(targets),len(set(targets)))
                for name in ("runtime_state","central_runtime","runtime_lifecycle","native_agents","install_cli"):
                    self.assertEqual(1,targets.count("tests.test_"+name))
                self.assertIn("tests.test_manager_tui.TuiTest.test_platform_reset_is_independent_and_consumes_only_captured_keys",targets)
                # 新保存预览的真实 App 回归必须经唯一 ci 清单运行，且组合选择不能重复。
                self.assertEqual(1, targets.count("tests.test_manager_tui.TuiTest.test_save_preview_blocked_validation_keeps_ui_responsive_and_drafts"))
                self.assertIn("tests.test_manager_tui.ProjectTuiIntegrationTest.test_real_pty_registration_cancel_enable_disable_versions_conflict_and_resize",targets)
                # AGY 只精确共享 budget；整个模块还含 Windows/提升 TestCase，
                # 不能为满足便携回归而重复运行预算节点或误把平台 skip 当证据。
                self.assertNotIn("tests.test_antigravity_windows_native", targets)
                for target in read_preparation + central_preview + role_final_read:
                    self.assertEqual(1, sum(target == parent or target.startswith(parent + ".") for parent in targets))
                for component in runner.NATIVE_COMPONENTS.values():
                    for target in component.get("portable_ci_targets", ()):
                        # 父模块覆盖精确节点也是一次有效选择；组合 central 时不能
                        # 为满足文本计数而再次执行其子方法，亦不能漏掉共享回归。
                        self.assertEqual(1, sum(target == parent or target.startswith(parent + ".") for parent in targets))
                    if selectors == ("ci",) and component["qualification"] == "elevated":
                        for target in runner.component_targets(component):
                            self.assertFalse(any(target == parent or target.startswith(parent + ".") for parent in targets))

    def test_real_existing_node_runs_through_repository_entry(self):
        # 受控夹具只能证明调度边界；另经真实入口执行既有生产消费者，证明当前
        # 源根、真实 python_runtime.sh 和 unittest 节点能一起运行，而非仅录制 mock。
        target = "tests.test_claude_options.ClaudeOptionsTest.test_missing_options_inherit_and_model_edits_preserve_native_window"
        result = self.invoke(target, entry=PACK / "scripts/test_workflow.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Ran 1 test", result.stderr)
        self.assertIn("OK", result.stderr)

    def test_delivery_registry_collects_real_exact_consumers_once_with_owned_dependencies(self):
        spec = importlib.util.spec_from_file_location("validation_delivery_registry", PACK / "scripts/test_workflow.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        from tests import test_windows_delivery as delivery
        component = runner.NATIVE_COMPONENTS["windows-native-delivery"]
        self.assertEqual("ordinary", component["qualification"])
        self.assertTrue(component["node_required"])
        # runner 只用 stdlib，真实 pip/curses 安装和 TUI 消费归交付的最终私有
        # venv；若此处预装 curses，就不能区分安装器是否准备了用户环境。
        self.assertFalse(component["curses_required"])
        loader = unittest.TestLoader()
        native_ids = {case.id() for case in loader.loadTestsFromTestCase(delivery.WindowsDeliveryNativeTest)}
        portable_ids = {case.id() for case in loader.loadTestsFromTestCase(delivery.ReleaseWorkflowPortableTest)}
        self.assertTrue(native_ids)
        self.assertEqual(native_ids, set(component["targets"]))
        self.assertEqual(portable_ids, set(component["portable_ci_targets"]))
        for target in runner.component_targets(component):
            # 每条注册必须是可解析的精确 caseID；只收集不执行 Windows 用例，
            # 不能把本机 skip、测试夹具或整个模块误记成真实安装验收。
            self.assertEqual([target], [case.id() for case in runner.load_target(target, runner.make_parser())])
            self.assertEqual(1, runner.GROUPS["windows-native"].count(target))
            self.assertEqual(1, runner.GROUPS["windows-native-desktop"].count(target))
        for target in portable_ids:
            self.assertEqual(1, runner.GROUPS["ci"].count(target))
        self.assertTrue(native_ids.isdisjoint(runner.GROUPS["ci"]))

    def test_native_python_entry_from_other_cwd_preserves_selection_and_rejection(self):
        # 同一 Python 文件是真正无 Bash 的入口；-I 下从带空格源码根和其他 cwd
        # 启动仍使用同一清单，验证错误子节点不会因父模块覆盖而被忽略。
        entry = self.source / "scripts/test_workflow.py"
        target = "tests.test_shared_memory_contract.ExampleTest.test_two"
        command = [sys.executable, "-I", "-B", "-X", "utf8", str(entry)]
        result = subprocess.run(command + [target], cwd=self.caller, env=self.environment,
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        [case] = self.recorded_cases()
        self.assertEqual(target, case["id"])
        self.assertEqual(str(self.source), case["cwd"])
        self.assertTrue(case["no_bytecode"])
        self.case_calls.unlink()
        for prefix in ([], ["--list"]):
            result = subprocess.run(command + prefix + ["tests.test_shared_memory_contract", target + "_typo"],
                                    cwd=self.caller, env=self.environment, capture_output=True, text=True, timeout=40)
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertEqual([], self.recorded_cases())

    def test_required_native_cases_cannot_succeed_when_skipped_or_unexecuted(self):
        # 这里只核对 runner 的拒绝合同，不把夹具执行当成 Win32 能力证据。
        spec = importlib.util.spec_from_file_location("validation_runner_contract", PACK / "scripts/test_workflow.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)

        class RequiredCase(unittest.TestCase):
            def test_ok(self):
                pass

            @unittest.skip("受控 skip：必须导致原生必验拒绝")
            def test_skip(self):
                pass

            def test_subtest_skip(self):
                with self.subTest(stage="required-native-scenario"):
                    self.skipTest("受控子场景 skip：父方法启动不能代表必验完整执行")

        with redirect_stderr(io.StringIO()):
            skipped = RequiredCase("test_skip")
            self.assertEqual(1, runner.run_cases([skipped], {skipped.id()}))
            actual = RequiredCase("test_ok")
            self.assertEqual(1, runner.run_cases([actual], {actual.id(), "required.but.not.executed"}))
            skipped_child = RequiredCase("test_subtest_skip")
            self.assertEqual(1, runner.run_cases([skipped_child], {skipped_child.id()}))
            # 普通组仍遵循 unittest 的 skip 语义；只在原生必验集合加严，不改变
            # 原 ci 或既有 portable 组的行为。
            self.assertEqual(0, runner.run_cases([RequiredCase("test_subtest_skip")]))

    def test_native_matrix_counts_collected_cases_and_rejects_empty_or_overlapping_partitions(self):
        # 这些 TestCase 只提供 unittest 的真实 id，不执行方法；本例验证新公开 JSON
        # 协议，而不以受控夹具声称任何 Win32/宿主能力已通过。
        spec = importlib.util.spec_from_file_location("validation_matrix_contract", PACK / "scripts/test_workflow.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)

        class MatrixCase(unittest.TestCase):
            def test_one(self):
                self.fail("矩阵收集不能运行 TestCase")

            def test_two(self):
                self.fail("矩阵收集不能运行 TestCase")

            def test_unregistered(self):
                self.fail("未登记方法不能被完整矩阵遗漏")

        first, second = MatrixCase("test_one"), MatrixCase("test_two")
        components = {
            "first": {"targets": ("one",), "qualification": "ordinary", "node_required": False, "curses_required": False},
            "second": {"targets": ("two",), "qualification": "elevated", "node_required": False, "curses_required": True},
        }
        parser = runner.make_parser()
        with patch.object(runner, "NATIVE_COMPONENTS", components):
            self.assertEqual({"include": [
                {"group": "first", "methods": 1, "qualification": "ordinary", "node_required": False, "curses_required": False},
                {"group": "second", "methods": 1, "qualification": "elevated", "node_required": False, "curses_required": True},
            ]}, runner.native_matrix({"one": [first, first], "two": [second]}, parser))
            for resolved in ({"one": [], "two": [second]}, {"one": [first], "two": [first]},
                             {"one": [first], "two": [second], "extra": [MatrixCase("test_unregistered")]}):
                with self.subTest(resolved=resolved), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    runner.native_matrix(resolved, parser)
                self.assertEqual(2, error.exception.code)
            components["second"]["curses_required"] = "true"
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runner.native_matrix({"one": [first], "two": [second]}, parser)
            self.assertEqual(2, error.exception.code)
        with patch.object(runner, "NATIVE_COMPONENTS", {}), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            runner.native_matrix({}, parser)
        self.assertEqual(2, error.exception.code)

    def test_matrix_cli_accepts_only_full_scope_and_never_executes_cases(self):
        spec = importlib.util.spec_from_file_location("validation_matrix_cli_contract", PACK / "scripts/test_workflow.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        # 缺范围、局部范围、组合范围与 --list 混用都在导入/执行前拒绝，防止调用方
        # 将一次窄诊断伪装成完整发行 gate；不会为兼容旧 repair 名称退回 discovery。
        for arguments in (("--matrix",), ("--matrix", "codex"), ("--matrix", "windows-native-libraries"),
                          ("--matrix", "windows-native-desktop"), ("--matrix", "windows-native", "codex"),
                          ("--matrix", "--list", "windows-native"), ("--matrix", "--describe", "windows-native"),
                          ("--describe",), ("--describe", "windows-native-libraries"),
                          ("--describe", "windows-native", "codex"), ("--describe", "--list", "windows-native")):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), \
                    patch.object(sys, "argv", ["test_workflow.py", *arguments]), \
                    patch.object(runner, "load_target") as collect, patch.object(runner, "run_cases") as execute, \
                    self.assertRaises(SystemExit) as error:
                runner.main()
            self.assertEqual(2, error.exception.code)
            collect.assert_not_called()
            execute.assert_not_called()
        component = {"targets": ("tests.test_protocol",), "qualification": "ordinary", "node_required": False, "curses_required": False}
        with patch.object(runner, "NATIVE_COMPONENTS", {"native-protocol": component}), \
                patch.object(runner, "GROUPS", {"windows-native": component["targets"]}), \
                patch.object(runner, "load_target", return_value=[self]), \
                patch.object(runner, "run_cases") as execute, \
                patch.object(sys, "argv", ["test_workflow.py", "--matrix", "windows-native"]), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, runner.main())
        execute.assert_not_called()
        self.assertEqual({"include": [{"group": "native-protocol", "methods": 1,
                                      "qualification": "ordinary", "node_required": False, "curses_required": False}]}, json.loads(output.getvalue()))
        # describe 也只收集完整登记；桌面描述明确是范围事实，即使当前夹具没有
        # 提升组件，也不能将 collection-only 转写为 full native 执行成功。
        with patch.object(runner, "NATIVE_COMPONENTS", {"native-protocol": component}), \
                patch.object(runner, "GROUPS", {"windows-native": component["targets"]}), \
                patch.object(runner, "load_target", return_value=[self]), \
                patch.object(runner, "run_cases") as execute, \
                patch.object(sys, "argv", ["test_workflow.py", "--describe", "windows-native-desktop"]), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, runner.main())
        execute.assert_not_called()
        description = json.loads(output.getvalue())
        self.assertEqual("windows-native-desktop", description["scope"])
        self.assertTrue(description["collection_only"])
        self.assertFalse(description["scope_is_full"])
        self.assertEqual([self.id()], description["selected"]["ids"])
        self.assertEqual([], description["excluded"]["ids"])
        with patch.object(runner, "GROUPS", {"windows-native-desktop": ()}), \
                patch.object(runner, "load_target") as collect, patch.object(runner, "run_cases") as execute, \
                patch.object(sys, "argv", ["test_workflow.py", "windows-native-desktop"]), \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            runner.main()
        self.assertEqual(2, error.exception.code)
        collect.assert_not_called()
        execute.assert_not_called()

    def test_native_description_uses_one_registry_and_rejects_unknown_qualification(self):
        spec = importlib.util.spec_from_file_location("validation_scope_contract", PACK / "scripts/test_workflow.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        ordinary, elevated = SimpleNamespace(id=lambda: "ordinary.case"), SimpleNamespace(id=lambda: "elevated.case")
        components = {
            "ordinary": {"targets": ("one",), "qualification": "ordinary", "node_required": False, "curses_required": False},
            "elevated": {"targets": ("two",), "qualification": "elevated", "node_required": False, "curses_required": False},
        }
        parser, resolved = runner.make_parser(), {"one": [ordinary], "two": [elevated]}
        with patch.object(runner, "NATIVE_COMPONENTS", components):
            full = runner.native_description("windows-native", resolved, parser)
            desktop = runner.native_description("windows-native-desktop", resolved, parser)
            self.assertEqual(full["registry"]["ids"], full["selected"]["ids"])
            self.assertEqual([], full["excluded"]["ids"])
            self.assertEqual(full["registry"], desktop["registry"])
            self.assertEqual([ordinary.id()], desktop["selected"]["ids"])
            self.assertEqual([elevated.id()], desktop["excluded"]["ids"])
            self.assertEqual(2, desktop["registry"]["count"])
            self.assertEqual(1, desktop["selected"]["count"])
            self.assertEqual(1, desktop["excluded"]["count"])
            self.assertEqual("requires-elevated-test-fixture", desktop["excluded"]["components"][0]["reason"])
            # 选择桌面不是权限探测：没有 token/mock 参与决定；资格缺失、未知或
            # 把现有 ordinary 全改成 elevated 导致空桌面，均在任何执行之前失败。
            for qualification in (None, "admin", True):
                components["elevated"]["qualification"] = qualification
                with self.subTest(qualification=qualification), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    runner.native_description("windows-native-desktop", resolved, parser)
                self.assertEqual(2, error.exception.code)
            del components["elevated"]["qualification"]
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runner.native_matrix(resolved, parser)
            self.assertEqual(2, error.exception.code)
            components["elevated"]["qualification"] = "elevated"
            components["ordinary"]["qualification"] = "elevated"
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runner.native_description("windows-native-desktop", resolved, parser)
            self.assertEqual(2, error.exception.code)

    def test_each_native_stage_rejects_non_windows_before_execution(self):
        # 本例仅验证阶段选择不能绕过平台守卫，实际 Win32 能力由组合 Windows CI
        # 验证。模拟的是 runner 的平台边界，不实例化平台后端或伪造原生成功。
        spec = importlib.util.spec_from_file_location("validation_native_stage_contract", PACK / "scripts/test_workflow.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        for group in runner.NATIVE_GROUPS:
            with self.subTest(group=group), redirect_stderr(io.StringIO()), \
                    patch.object(runner, "os", SimpleNamespace(name="posix", chdir=lambda _: None)), \
                    patch.object(sys, "argv", ["test_workflow.py", group]), \
                    patch.object(runner, "load_target", return_value=[self]), \
                    patch.object(runner, "run_cases") as execute:
                self.assertEqual(1, runner.main())
                execute.assert_not_called()

    def test_desktop_execution_requires_only_selected_cases_without_permission_fallback(self):
        # 模拟的仅是 runner 平台边界与短小 TestCase id；验证普通执行不收集提升
        # 方法、仍将全部所选 id 交给 zeroSkip 守卫，不冒充任何原生权限或桌面通过。
        spec = importlib.util.spec_from_file_location("validation_desktop_execution", PACK / "scripts/test_workflow.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        ordinary = SimpleNamespace(id=lambda: "ordinary.case")
        components = {
            "ordinary": {"targets": ("one",), "qualification": "ordinary", "node_required": False, "curses_required": False},
            "elevated": {"targets": ("two",), "qualification": "elevated", "node_required": False, "curses_required": False},
        }
        with patch.object(runner, "NATIVE_COMPONENTS", components), \
                patch.object(runner, "GROUPS", {"windows-native": ("one", "two"), "windows-native-desktop": ("one",)}), \
                patch.object(runner, "os", SimpleNamespace(name="nt", chdir=lambda _: None)), \
                patch.object(runner, "load_target", return_value=[ordinary]) as collect, \
                patch.object(runner, "run_cases", return_value=0) as execute, \
                patch.object(sys, "argv", ["test_workflow.py", "windows-native-desktop"]):
            self.assertEqual(0, runner.main())
        self.assertEqual(1, collect.call_count)
        self.assertEqual("one", collect.call_args.args[0])
        self.assertEqual([ordinary.id()], [case.id() for case in execute.call_args.args[0]])
        self.assertEqual({ordinary.id()}, execute.call_args.args[1])


class SupervisedPortableBatchTest(unittest.TestCase):
    """真实短命 child 核对原 CLI 协议；不以便携夹具冒充真实 App/Win32 通过。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="validation-supervision-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source with spaces"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "tests").mkdir()
        (self.source / "tests/__init__.py").write_text("", encoding="utf-8")
        shutil.copyfile(PACK / "scripts/test_workflow.py", self.source / "scripts/test_workflow.py")
        spec = importlib.util.spec_from_file_location("validation_supervised_contract", PACK / "scripts/test_workflow.py")
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.identifiers = self.runner._supervised_portable_ids()
        self.calls = self.root / "actual-calls.jsonl"
        self.evidence = self.root / "evidence.jsonl"

    def fixture(self, bodies, *, cleanup=""):
        # 方法身份取自唯一真实登记，不另维护 App ID 表；夹具只实现短小 unittest
        # 生命周期与原字节写入，child 仍由原 loader、runner 和 process owner 执行。
        self.calls.unlink(missing_ok=True)
        parts = [identifier.split(".") for identifier in self.identifiers]
        self.assertEqual(1, len({tuple(value[:3]) for value in parts}))
        module_name, class_name = parts[0][1:3]
        source = "import json,os,time,unittest\nfrom pathlib import Path\n"
        source += f"class {class_name}(unittest.TestCase):\n"
        for identifier, body in zip(self.identifiers, bodies, strict=True):
            source += f"    def {identifier.rsplit('.', 1)[1]}(self):\n"
            source += f"        with Path({str(self.calls)!r}).open('a',encoding='utf-8') as stream:\n"
            source += "            stream.write(json.dumps(self.id())+'\\n')\n"
            source += "".join("        " + line + "\n" for line in body.splitlines())
        if cleanup:
            source += "    @classmethod\n    def tearDownClass(cls):\n"
            source += "".join("        " + line + "\n" for line in cleanup.splitlines())
        (self.source / "tests" / (module_name + ".py")).write_text(source, encoding="utf-8")

    def invoke_child(self, *, timeout=10, fault=None):
        # 每例独占 evidence/scratch；真实 raw 走 binary buffer，断言任意字节
        # 没被文本 codec 改写。测试期限仅缩短此夹具，不改变生产 600s 常量。
        output, error = io.BytesIO(), io.BytesIO()
        out_text = io.TextIOWrapper(output, encoding="utf-8", write_through=True)
        err_text = io.TextIOWrapper(error, encoding="utf-8", write_through=True)
        console = {"stdout": out_text, "stderr": err_text}
        if fault is not None:
            channel, operation = fault

            def write(raw):
                if operation == "write":
                    raise BrokenPipeError("controlled binary write failure")
                return len(raw)

            def flush():
                if operation == "flush":
                    raise OSError("controlled binary flush failure")

            # 仅故障 binary 输出层；文本摘要仍可写，分别定位真实 raw 的
            # write/flush 故障，不把其它 I/O 失败混同为四个目标负控。
            console[channel] = SimpleNamespace(buffer=SimpleNamespace(write=write, flush=flush),
                                               flush=lambda: None, write=lambda text: len(text))
        try:
            with patch.object(self.runner, "PACK", self.source), \
                    patch.object(self.runner, "SUPERVISED_EXECUTION_SECONDS", timeout), \
                    patch.dict(os.environ, {"AWF_TEST_EVIDENCE_LOG": str(self.evidence),
                                            "AGENT_WORKFLOW_TEST_SCRATCH": str(self.root)}), \
                    redirect_stdout(console["stdout"]), redirect_stderr(console["stderr"]):
                code = self.runner._run_supervised_cases(self.identifiers)
            out_text.flush()
            err_text.flush()
            record = json.loads(self.evidence.read_text().splitlines()[-1]) if self.evidence.exists() else None
            return code, output.getvalue(), error.getvalue(), record
        finally:
            out_text.detach()
            err_text.detach()

    def test_selected_registry_cases_run_once_with_required_ids_and_raw_evidence(self):
        self.fixture(("os.write(1,b'raw-out-\\xff\\n'); os.write(2,b'raw-err-\\xfe\\n')", "pass"))
        code, output, error, record = self.invoke_child()
        self.assertEqual(0, code, error)
        self.assertIn(b"raw-out-\xff\n", output)
        self.assertIn(b"raw-err-\xfe\n", error)
        self.assertEqual([*self.identifiers], [json.loads(line) for line in self.calls.read_text().splitlines()])
        self.assertEqual(output, base64.b64decode(record["stdout_b64"]))
        self.assertIn(base64.b64decode(record["stderr_b64"]), error)
        events = [json.loads(line) for line in base64.b64decode(record["events_b64"]).splitlines()]
        self.assertEqual(sorted(self.identifiers), events[-1]["expected_ids"])
        self.assertEqual(len(self.identifiers), events[-1]["tests_run"])
        self.assertTrue(record["protocol_valid"] and record["owner_quiescent"])
        self.assertFalse(Path(record["scene"]).exists())

    def test_failure_skip_and_class_cleanup_cannot_be_reported_as_success(self):
        scenarios = (
            (("self.fail('real failure')", "pass"), "", "failures"),
            (("with self.subTest(part='required'):\n    self.skipTest('real subtest skip')", "pass"), "", "skips"),
            (("pass", "pass"), "raise RuntimeError('class cleanup failure')", "errors"),
        )
        for bodies, cleanup, key in scenarios:
            with self.subTest(key=key):
                self.fixture(bodies, cleanup=cleanup)
                code, _, error, record = self.invoke_child()
                self.assertEqual(1, code, error)
                self.assertEqual(1, record["child_exit"])
                self.assertFalse(record["protocol_valid"])
                events = [json.loads(line) for line in base64.b64decode(record["events_b64"]).splitlines()]
                # 所有方法都 stop 仍可能类清理失败；结果必须取完整 runner 终态。
                self.assertEqual(len(self.identifiers), sum(event["kind"] == "stop" for event in events))
                self.assertEqual(1, events[-1][key])
                self.assertFalse(Path(record["scene"]).exists())

    def test_timeout_preserves_partial_raw_and_real_started_events(self):
        self.fixture(("os.write(1,b'partial-out-\\xff'); os.write(2,b'partial-err-\\xfe'); time.sleep(3600)", "pass"))
        code, output, error, record = self.invoke_child(timeout=3)
        self.assertEqual(1, code, error)
        self.assertEqual("TimeoutExpired", record["outcome"])
        self.assertTrue(record["owner_quiescent"])
        self.assertFalse(record["raw_complete"])
        self.assertIn(b"partial-out-\xff", output)
        self.assertIn(b"partial-err-\xfe", error)
        events = [json.loads(line) for line in base64.b64decode(record["events_b64"]).splitlines()]
        self.assertEqual([{"kind": "start", "id": self.identifiers[0]}], events)
        self.assertFalse(Path(record["scene"]).exists())

    def test_missing_or_forged_terminal_record_is_rejected(self):
        self.fixture(("os._exit(0)", "pass"))
        code, _, error, record = self.invoke_child()
        self.assertEqual(1, code, error)
        self.assertEqual(0, record["child_exit"])
        self.assertFalse(record["protocol_valid"])
        self.fixture(("pass", "pass"))
        code, _, error, record = self.invoke_child()
        self.assertEqual(0, code, error)
        events = [json.loads(line) for line in base64.b64decode(record["events_b64"]).splitlines()]
        # 在一次真实 child 输出上变更协议字段；不用另造成功事件串替代真实执行。
        for changes in ({"successful": False}, {"expected_ids": []}, {"tests_run": True},
                        {"exit_code": False}, {"skips": 1}, {"stopped_ids": []}):
            with self.subTest(changes=changes):
                altered = events[:-1] + [{**events[-1], **changes}]
                raw = ("\n".join(json.dumps(event) for event in altered) + "\n").encode()
                self.assertFalse(self.runner._validate_supervised_events(raw, self.identifiers, 0))
        raw = base64.b64decode(record["events_b64"])
        self.assertFalse(self.runner._validate_supervised_events(raw[:-1], self.identifiers, 0))
        self.assertFalse(self.runner._validate_supervised_events(raw, self.identifiers, 27))

    def test_unknown_cleanup_retains_private_scene_without_replaying_live_raw(self):
        from lib.install.install_process import ACTIVE_RUNNER
        from lib.install.windows_process import WindowsJobCleanupError

        for kind in ("WindowsJobCleanupError", "KeyboardInterrupt", "prelaunch-budget-refusal"):
            with self.subTest(kind=kind), ExitStack() as stack:
                if kind == "prelaunch-budget-refusal":
                    # 实际原 capture_process 在 Popen/WindowsJobProcess 之前拒绝
                    # 预算；N1 无对应启动收据，宁可 unknown 也不伪造实际 Job 0。
                    token = ACTIVE_RUNNER.set(SimpleNamespace(deadline=0, cancel_file=None, recovering=False))
                    stack.callback(ACTIVE_RUNNER.reset, token)
                    popen = stack.enter_context(patch("lib.install.install_process.subprocess.Popen"))
                    job = stack.enter_context(patch("lib.install.install_process.WindowsJobProcess"))
                else:
                    def unknown_owner(command, *, body, timeout):
                        # 只注入错误分类，不制造真实失控 Job/启动 race；保留文件
                        # 是可证结果，非已运行 Windows race 或实际归零证明。
                        directory = Path(json.loads(body)["directory"])
                        (directory / "stdout.raw").write_bytes(b"unconfirmed-live-writer")
                        if kind == "KeyboardInterrupt":
                            raise KeyboardInterrupt("controlled launch seam interruption")
                        raise WindowsJobCleanupError("controlled unknown quiescence")
                    stack.enter_context(patch("lib.install.install_process.capture_process", side_effect=unknown_owner))
                read = stack.enter_context(patch.object(Path, "read_bytes"))
                remove = stack.enter_context(patch.object(shutil, "rmtree", wraps=shutil.rmtree))
                code, output, error, record = self.invoke_child()
                self.assertEqual(1, code, error)
                self.assertFalse(record["owner_quiescent"] or record["raw_complete"] or record["windows_job_zero_proved"])
                self.assertEqual("unconfirmed", record["ownership_evidence"])
                self.assertTrue(record["scene_retained"])
                self.assertNotIn("stdout_b64", record)
                self.assertNotIn(b"unconfirmed-live-writer", output + error)
                read.assert_not_called()
                remove.assert_not_called()
                self.assertTrue((Path(record["scene"]) / "stdout.raw").is_file())
                if kind == "prelaunch-budget-refusal":
                    popen.assert_not_called()
                    job.assert_not_called()

    def test_raw_forward_failures_preserve_durable_evidence_and_fail_closed(self):
        bodies = ("os.write(1,b'durable-out-\\xff'); os.write(2,b'durable-err-\\xfe')", "pass")
        for channel in ("stdout", "stderr"):
            for operation in ("write", "flush"):
                with self.subTest(channel=channel, operation=operation):
                    self.fixture(bodies)
                    code, _, error, record = self.invoke_child(fault=(channel, operation))
                    self.assertEqual(1, code, error)
                    self.assertEqual(0, record["child_exit"])
                    self.assertEqual(1, record["exit_code"])
                    self.assertEqual("final", record["phase"])
                    self.assertTrue(record["scene_retained"])
                    self.assertTrue(Path(record["scene"]).is_dir())
                    self.assertEqual(channel, record["forward_errors"][0]["stream"])
                    self.assertIn(b"durable-out-\xff", base64.b64decode(record["stdout_b64"]))
                    self.assertIn(b"durable-err-\xfe", base64.b64decode(record["stderr_b64"]))
                    events = base64.b64decode(record["events_b64"])
                    self.assertTrue(self.runner._validate_supervised_events(events, self.identifiers, 0))
                    snapshots = [json.loads(line) for line in self.evidence.read_text().splitlines()]
                    self.assertEqual("captured-before-forward", snapshots[-2]["phase"])
                    self.assertIsNone(snapshots[-2]["exit_code"])

        for failed_phase in ("captured-before-forward", "final"):
            with self.subTest(evidence_failure=failed_phase):
                self.fixture(bodies)
                self.evidence.unlink(missing_ok=True)
                publish = self.runner._publish_supervised_evidence
                attempts = []

                def fail_publication(record):
                    attempts.append(json.loads(json.dumps(record)))
                    if record["phase"] == failed_phase:
                        raise OSError("controlled persistent evidence failure")
                    publish(record)

                with patch.object(self.runner, "_publish_supervised_evidence", side_effect=fail_publication):
                    code, _, error, record = self.invoke_child()
                self.assertEqual(1, code, error)
                self.assertTrue(Path(attempts[-1]["scene"]).is_dir())
                self.assertTrue(attempts[-1]["scene_retained"])
                if record is not None:
                    # 后置出口失败时，先前快照仍保存完整 raw，且从未宣称最终 0。
                    self.assertIsNone(record["exit_code"])
                    self.assertIn(b"durable-out-\xff", base64.b64decode(record["stdout_b64"]))
                self.assertNotEqual(0, attempts[-1]["exit_code"])

    def test_parent_partitions_only_registry_portable_cases_without_rerun(self):
        ordinary = "tests.test_controlled.ExampleTest.test_ordinary"
        selectors = [*self.identifiers, ordinary, self.identifiers[0]]
        # 原 main 真实解析/去重后，只将登记交集交给 child；普通 case 仍消费
        # 原 run_cases。这里只 mock 测试执行边界，不加载不存在的新 TUI 方法。
        with patch.object(sys, "argv", ["test_workflow.py", *selectors]), \
                patch.object(self.runner, "os", SimpleNamespace(name=os.name, chdir=lambda _: None)), \
                patch.object(self.runner, "load_target", side_effect=lambda target, _: [SimpleNamespace(id=lambda: target)]), \
                patch.object(self.runner, "run_cases", return_value=0) as ordinary_run, \
                patch.object(self.runner, "_run_supervised_cases", return_value=27) as child_run:
            self.assertEqual(27, self.runner.main())
        child_run.assert_called_once_with(self.identifiers)
        ordinary_run.assert_called_once()
        self.assertEqual([ordinary], [case.id() for case in ordinary_run.call_args.args[0]])
        self.assertEqual(set(), ordinary_run.call_args.args[1])


@unittest.skipUnless(os.name == "nt", "PowerShell scope 消费合同必须由真实 Windows 执行")
class WindowsAcceptanceScopeNativeTest(unittest.TestCase):
    def test_native_script_consumes_desktop_description_and_rejects_full_scope(self):
        # 真实生产函数直接消费当前唯一 runner；只加载函数以避免在 Server 上绕过
        # Win11/普通用户 root 守卫或递归执行全部原生组。本例不是桌面入口通过证据。
        from lib.install.install_process import capture_process
        from lib.hosts.windows_hook_command import validate_powershell
        from tests.test_windows_native_integration import isolated_environment
        with tempfile.TemporaryDirectory(prefix="awf-scope-consumer-", dir=os.environ.get("AGENT_WORKFLOW_TEST_SCRATCH")) as raw:
            root = Path(raw).resolve()
            home = root / "private-home"
            home.mkdir()
            bad = root / "fake-full-producer.py"
            bad.write_text("import json\nprint(json.dumps({'schema_version':1,'scope':'windows-native','full_registry_scope':'windows-native','collection_only':True,'scope_is_full':True}))\n", encoding="utf-8")
            environment = isolated_environment(home)
            environment.update(AWF_SCOPE_TEST_ROOT=str(root), AWF_SCOPE_TEST_PYTHON=sys.executable,
                               AWF_SCOPE_TEST_SCRIPT=str(PACK / "scripts/windows_acceptance.ps1"),
                               AWF_SCOPE_TEST_ENTRY=str(PACK / "scripts/test_workflow.py"), AWF_SCOPE_TEST_BAD=str(bad))
            script = r'''
$ErrorActionPreference = 'Stop'
$PSNativeCommandArgumentPassing = 'Legacy'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:AWF_SCOPE_TEST_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw ($errors | Out-String) }
foreach ($name in @('Write-AcceptanceLog', 'Get-AcceptanceScope')) {
    $definitions = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name
    }, $true))
    if ($definitions.Count -ne 1) { throw "Expected one actual production function: $name" }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}
$interpreter = Get-Item -LiteralPath $env:AWF_SCOPE_TEST_PYTHON
$log = Join-Path $env:AWF_SCOPE_TEST_ROOT 'scope-consumer.log'
$destination = Join-Path $env:AWF_SCOPE_TEST_ROOT 'scope.json'
$description = Get-AcceptanceScope -Entry $env:AWF_SCOPE_TEST_ENTRY -Destination $destination
if ($description.scope -cne 'windows-native-desktop' -or $description.scope_is_full) { throw 'The real scope consumer widened desktop acceptance.' }
$badDestination = Join-Path $env:AWF_SCOPE_TEST_ROOT 'rejected.json'
$refused = $false
try { Get-AcceptanceScope -Entry $env:AWF_SCOPE_TEST_BAD -Destination $badDestination | Out-Null } catch {
    if ($_.Exception.Message -notlike '*ordinary-user scope*') { throw }
    $refused = $true
}
if (-not $refused -or (Test-Path -LiteralPath $badDestination)) { throw 'The real scope consumer accepted or published a fake full description.' }
Write-Output 'DESKTOP_SCOPE_REAL_CONSUMER_OK'
'''
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            argv = [validate_powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
            result = capture_process(argv, env=environment, timeout=60)
            log = root / "scope-consumer.log"
            descriptor = root / "scope.json"
            evidence = {"kind": "desktop-scope-consumer", "argv": argv, "exit": result.returncode,
                        "stdout_base64": base64.b64encode(result.stdout).decode("ascii"),
                        "stderr_base64": base64.b64encode(result.stderr).decode("ascii"),
                        "log_base64": base64.b64encode(log.read_bytes() if log.exists() else b"").decode("ascii"),
                        "description": json.loads(descriptor.read_bytes()) if descriptor.exists() else None}
            line = json.dumps(evidence, ensure_ascii=True)
            print("\n[native scope evidence] " + line, flush=True)
            if target := os.environ.get("AWF_TEST_EVIDENCE_LOG"):
                with open(target, "a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(b"DESKTOP_SCOPE_REAL_CONSUMER_OK", result.stdout)
            description = evidence["description"]
            self.assertEqual("windows-native-desktop", description["scope"])
            selected, excluded = set(description["selected"]["ids"]), set(description["excluded"]["ids"])
            self.assertFalse(selected.intersection(excluded))
            self.assertEqual(set(description["registry"]["ids"]), selected | excluded)
            # 实际 PowerShell 消费应随唯一 registry 排除所有提升专项，不能
            # 固定旧 NTFS 数量。这里复用原 loader 只收集提升节点，不执行夹具。
            spec = importlib.util.spec_from_file_location("validation_scope_elevated_registry", PACK / "scripts/test_workflow.py")
            runner = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runner)
            expected = {case.id() for component in runner.NATIVE_COMPONENTS.values()
                        if component["qualification"] == "elevated"
                        for target in runner.component_targets(component)
                        for case in runner.load_target(target, runner.make_parser())}
            self.assertEqual(expected, excluded)


if __name__ == "__main__":
    unittest.main()
