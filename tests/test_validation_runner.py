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
        result=self.invoke("--list","central","service","ci",entry=PACK/"scripts/test_workflow.sh")
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        targets=result.stdout.splitlines();self.assertEqual(len(targets),len(set(targets)))
        for name in ("central_runtime","runtime_lifecycle","native_agents","install_cli"):
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
