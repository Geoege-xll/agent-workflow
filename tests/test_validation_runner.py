"""唯一验证入口的进程级合同；受控运行时只记录边界，测试仍由真实 unittest 执行。"""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


PACK = Path(__file__).resolve().parents[1]
CURRENT_PRODUCT_MODULES = {
    "plugin": ("plugin_delivery", "plugin_resources", "plugin_workflow_contract", "plugin_maintenance_contract", "continuous_intake_capabilities",
               "agent_continuation", "dispatch_admission", "task_settlement", "task_graph", "scheduler_boundaries"),
    "native-config": ("native_config", "native_inventory", "native_config_codecs", "native_config_commands", "native_config_server",
                      "native_config_mcp", "native_config_packaging", "plugin_console", "plugin_config_launcher", "config_distribution"),
}
CURRENT_RECORD_CLASSES = ("RecordUpdateTest", "RecordPublicationTest", "RecordCliTest", "ScratchWorkspaceTest")
PROTOTYPE_MODULES = ("document_safety", "prototype_adapters", "prototype_fingerprints", "prototype_workspace")


def current_product_targets():
    """测试固定声明真实产品范围，防止入口误删模块后由同一实现推导出假通过。"""
    plugin = ["tests.test_" + name for name in CURRENT_PRODUCT_MODULES["plugin"]]
    records = ["tests.test_task_graph_records." + name for name in CURRENT_RECORD_CLASSES]
    native = ["tests.test_" + name for name in CURRENT_PRODUCT_MODULES["native-config"]]
    return plugin + records + native


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
        for names in CURRENT_PRODUCT_MODULES.values():
            for module in names:
                self.write_case(module, ("test_ok",))
        for module in (*PROTOTYPE_MODULES, "validation_runner", "candidate_delivery"):
            self.write_case(module, ("test_ok",))
        # records 使用真实类节点作为范围边界；加入历史类诱饵，证明 current 不会
        # 因模块级收集而悄悄恢复旧安装器夹具，也不会把有效记录断言全部排除。
        records = self.source / "tests/test_task_graph_records.py"
        for name in (*CURRENT_RECORD_CLASSES, "RecordInstalledRuntimeTest"):
            self.write_case("record_class_fixture", ("test_ok",), class_name=name)
            with records.open("a", encoding="utf-8") as stream:
                stream.write((self.source / "tests/test_record_class_fixture.py").read_text(encoding="utf-8"))
        (self.source / "tests/test_record_class_fixture.py").unlink()
        self.write_case("runner_failure", ("test_failure",), failing=True)

    def write_case(self, module, methods, *, failing=False, class_name="ExampleTest"):
        body = '''import json
from pathlib import Path
import sys
import unittest

'''
        body += f'class {class_name}(unittest.TestCase):\n'
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
                self.assertIn("当前产品组：plugin、native-config", result.stdout)
                self.assertIn("legacy/通用", result.stdout)
                self.assertIn("不代表3.0全套", result.stdout)
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

    def test_current_product_groups_list_deduplicate_and_prevalidate_errors(self):
        expected = current_product_targets()
        selectors = ("plugin", "native-config", "plugin", "tests.test_plugin_delivery.ExampleTest.test_ok")
        listed = self.invoke("--list", *selectors)
        self.assertEqual(0, listed.returncode, listed.stdout + listed.stderr)
        self.assertEqual(expected, listed.stdout.splitlines())
        self.assertEqual([], self.recorded_cases())
        rejected = self.invoke("plugin", "native-config", "tests.test_native_config.ExampleTest.missing")
        self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertEqual([], self.recorded_cases())
        executed = self.invoke(*selectors)
        self.assertEqual(0, executed.returncode, executed.stdout + executed.stderr)
        cases = self.recorded_cases()
        self.assertEqual(len(expected), len(cases))
        self.assertEqual(len(cases), len({case["id"] for case in cases}))

    def test_real_current_product_groups_have_only_current_existing_targets(self):
        listed = self.invoke("--list", "plugin", "native-config", "plugin", entry=PACK / "scripts/test_workflow.sh")
        self.assertEqual(0, listed.returncode, listed.stdout + listed.stderr)
        expected = current_product_targets()
        self.assertEqual(expected, listed.stdout.splitlines())
        self.assertFalse(any("pty" in target.lower() or "manager_tui" in target for target in expected))
        self.assertEqual([], self.recorded_cases())

    def test_current_gate_consumes_both_products_retained_prototypes_and_delivery_once(self):
        expected = (["tests.test_validation_runner", "tests.test_candidate_delivery"]
                    + current_product_targets() + ["tests.test_" + name for name in PROTOTYPE_MODULES])
        selectors = ("current", "plugin", "native-config", "prototype", "current")
        for entry in (self.source / "scripts/test_workflow.sh", PACK / "scripts/test_workflow.sh"):
            with self.subTest(entry=entry):
                listed = self.invoke("--list", *selectors, entry=entry)
                self.assertEqual(0, listed.returncode, listed.stdout + listed.stderr)
                self.assertEqual(expected, listed.stdout.splitlines())
        rejected = self.invoke("current", "tests.test_task_graph_records.RecordUpdateTest.missing")
        self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertEqual([], self.recorded_cases())
        executed = self.invoke(*selectors)
        self.assertEqual(0, executed.returncode, executed.stdout + executed.stderr)
        cases = self.recorded_cases()
        self.assertEqual(len(expected), len(cases))
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertFalse(any("RecordInstalledRuntimeTest" in case["id"] for case in cases))

    def test_legacy_ci_alias_keeps_maintenance_scope_without_retired_html(self):
        legacy = self.invoke("--list", "legacy-ci", entry=PACK / "scripts/test_workflow.sh")
        alias = self.invoke("--list", "ci", entry=PACK / "scripts/test_workflow.sh")
        self.assertEqual(0, legacy.returncode, legacy.stdout + legacy.stderr)
        self.assertEqual(legacy.stdout, alias.stdout)
        self.assertNotIn("requirement_html", legacy.stdout)
        self.assertNotIn("tests.test_native_config", legacy.stdout)

    def test_selected_native_javascript_without_node_fails_before_any_case(self):
        # 提供入口真正需要的 Bash/dirname，但不提供 Node；解释器由受控
        # python_runtime 的绝对路径调用，避免测试依赖开发机 PATH 的偶然内容。
        binaries = self.root / "binaries-without-node"
        binaries.mkdir()
        for name in ("bash", "dirname"):
            (binaries / name).symlink_to(shutil.which(name))
        self.write_case("plugin_console", ("test_javascript",), class_name="ConsoleJavascriptTest")
        self.environment["PATH"] = str(binaries)
        result = self.invoke("tests.test_plugin_console")
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("需要已有 Node", result.stderr)
        self.assertEqual([], self.recorded_cases())

    def test_current_workflow_is_read_only_and_uses_current_gate_and_unique_candidates(self):
        # 只锁定产品和权限边界，不在测试里实现 YAML 解析器或一套发行系统。
        workflow = (PACK / ".github/workflows/release.yml").read_text(encoding="utf-8")
        for fragment in ("  pull_request:", "  push:", "branches: [main, 'codex/plugin-v3-*']",
                         "os: [ubuntu-latest, macos-latest]", "python-version: '3.11'",
                         "run: bash scripts/test_workflow.sh --list current",
                         "run: bash scripts/test_workflow.sh current", "    needs: validate",
                         "packaging/build_candidates.py", "command -v node", "overwrite: false",
                         "if-no-files-found: error", "candidate-manifest.json", "SHA256SUMS"):
            self.assertIn(fragment, workflow)
        for forbidden in ("contents: write", "pull_request_target", "workflow_dispatch", "GH_TOKEN",
                          "gh release", "packaging/build_release.py", "windows-latest", "test_workflow.sh ci"):
            self.assertNotIn(forbidden, workflow)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", workflow)

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
        self.assertEqual([str(self.source), "-B", "-X", "utf8", "-", target], invocation)
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
            "prototype": set(PROTOTYPE_MODULES),
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
        for selectors in (("ci",),("central","service","ci")):
            with self.subTest(selectors=selectors):
                result=self.invoke("--list",*selectors,entry=PACK/"scripts/test_workflow.sh")
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                targets=result.stdout.splitlines();self.assertEqual(len(targets),len(set(targets)))
                for name in ("runtime_state","central_runtime","runtime_lifecycle","native_agents","install_cli"):
                    self.assertEqual(1,targets.count("tests.test_"+name))
                self.assertIn("tests.test_manager_tui.TuiTest.test_platform_reset_is_independent_and_consumes_only_captured_keys",targets)
                self.assertIn("tests.test_manager_tui.ProjectTuiIntegrationTest.test_real_pty_registration_cancel_enable_disable_versions_conflict_and_resize",targets)

    def test_real_existing_node_runs_through_repository_entry(self):
        # 受控夹具只能证明调度边界；另经真实入口执行既有生产消费者，证明当前
        # 源根、真实 python_runtime.sh 和 unittest 节点能一起运行，而非仅录制 mock。
        target = "tests.test_claude_options.ClaudeOptionsTest.test_missing_options_inherit_and_model_edits_preserve_native_window"
        result = self.invoke(target, entry=PACK / "scripts/test_workflow.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Ran 1 test", result.stderr)
        self.assertIn("OK", result.stderr)


if __name__ == "__main__":
    unittest.main()
