"""唯一验证入口的进程级合同；受控运行时只记录边界，测试仍由真实 unittest 执行。"""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile


PACK = Path(__file__).resolve().parents[1]
# 这些模块由各产品与交付合同独立确定。plugin 的完整范围由仓库清单扣除其它组的
# 专属模块得到；这样既能识别关键用例误分组，又不用维护两份随核心模块增长的清单。
NATIVE_CONFIG_MODULES = {
    "native_config", "native_preparation", "native_preferences", "native_inventory",
    "native_config_codecs", "native_config_commands", "native_config_server", "browser_sessions",
    "native_config_mcp", "native_config_packaging", "plugin_console", "plugin_config_launcher",
    "config_distribution",
}
PROTOTYPE_MODULES = {
    "document_safety", "prototype_adapters", "prototype_fingerprints", "prototype_workspace",
    "prototype_workspace_runtime", "prototype_feedback", "prototype_review", "prototype_live",
    "prototype_server", "prototype_file_entry",
}
PACKAGING_MODULES = {
    "plugin_delivery", "native_config_packaging", "candidate_delivery", "plugin_config_launcher",
    "config_distribution", "plugin_source_publication", "remote_install_smoke",
}
PLAN_MODULES = {"plan_and_shallow_docs", "document_relations", "document_links"}


def repository_targets():
    """独立使用磁盘上的模块作对照，即使入口与夹具一起漏掉某个组也能发现。"""
    return {"tests." + path.stem for path in (PACK / "tests").glob("test_*.py")}


def targets_for(modules):
    return {"tests.test_" + module for module in modules}


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
        for name in ("workflow", "prototype"):
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
        # 每个真实模块分配一个可记录的轻量用例，避免验证调度器时再次启动真实
        # 组件或读取项目数据；完整仓库入口的 --list 另行核对实际可导入的用例。
        for target in repository_targets():
            self.write_case(target.removeprefix("tests.test_"), ("test_ok",))

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

    def test_repository_tests_take_precedence_over_installed_tests_package(self):
        # 用普通空包模拟解释器环境中同名 tests 依赖。仓库入口必须从本仓加载
        # 测试模块，即使外部包自带 __init__.py，也不能影响 current 的目标解析。
        external = self.root / "external"
        (external / "tests").mkdir(parents=True)
        (external / "tests/__init__.py").write_text("", encoding="utf-8")
        self.environment["PYTHONPATH"] = str(external)
        target = "tests.test_validation_runner.ValidationRunnerTest.test_no_arguments_and_help_do_not_run_tests"
        result = self.invoke("--list", target, entry=PACK / "scripts/test_workflow.sh")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([target], result.stdout.splitlines())

    def test_no_arguments_and_help_do_not_run_tests(self):
        for arguments in ((), ("--help",)):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("full", result.stdout)
                self.assertIn("--list", result.stdout)
                self.assertIn("plugin、native-config、prototype、plans、packaging", result.stdout)
                self.assertIn("3.x", result.stdout)
                self.assertEqual([], self.recorded_cases())

    def test_unknown_arguments_groups_and_nodes_reject_before_any_case(self):
        invalid = (
            "--unknown", "typo", "tests.test_missing", "tests.test_plugin_delivery.Missing",
            "tests.test_plugin_delivery.ExampleTest.missing",
            "tests.test_plugin_delivery.ExampleTest.setUp", "../tests/test_plugin_delivery.py",
        )
        for argument in invalid:
            with self.subTest(argument=argument):
                self.case_calls.unlink(missing_ok=True)
                result = self.invoke("plugin", argument)
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                self.assertIn("error:", result.stderr)
                self.assertEqual([], self.recorded_cases())

    def test_groups_deduplicate_shared_targets_in_list_and_execution(self):
        selectors = ("packaging", "native-config", "packaging")
        expected = targets_for(PACKAGING_MODULES | NATIVE_CONFIG_MODULES)
        result = self.invoke("--list", *selectors)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertCountEqual(expected, result.stdout.splitlines())
        self.assertEqual([], self.recorded_cases())
        result = self.invoke(*selectors)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertCountEqual({target + ".ExampleTest.test_ok" for target in expected},
                              [row["id"] for row in self.recorded_cases()])

    def test_parent_target_suppresses_child_nodes_in_either_order(self):
        self.write_case("plugin_delivery", ("test_one", "test_two"))
        parent = "tests.test_plugin_delivery"
        child = parent + ".ExampleTest.test_one"
        for targets in ((parent, child), (child, parent)):
            with self.subTest(targets=targets):
                result = self.invoke("--list", *targets)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([parent], result.stdout.splitlines())
        result = self.invoke(child, parent)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(self.recorded_cases()))

    def test_real_product_groups_collect_their_maintained_modules(self):
        # plugin_delivery 同时受 plugin 与 packaging 使用，配置产品同样有安装器/交付
        # 交集。按各组真实职责核对名单，再由组合测试证明这些交集只执行一次。
        outside_plugin = ((NATIVE_CONFIG_MODULES | PROTOTYPE_MODULES | PLAN_MODULES | PACKAGING_MODULES)
                          - {"plugin_delivery"}) | {"validation_runner"}
        groups = {
            "plugin": repository_targets() - targets_for(outside_plugin),
            "native-config": targets_for(NATIVE_CONFIG_MODULES),
            "prototype": targets_for(PROTOTYPE_MODULES),
            "plans": targets_for(PLAN_MODULES),
            "packaging": targets_for(PACKAGING_MODULES),
        }
        for group, expected in groups.items():
            with self.subTest(group=group):
                result = self.invoke("--list", group, entry=PACK / "scripts/test_workflow.sh")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertCountEqual(expected, result.stdout.splitlines())

    def test_current_gate_collects_every_repository_module_and_runs_each_case_once(self):
        selectors = ("current", "plugin", "native-config", "prototype", "plans", "packaging", "current")
        expected = repository_targets()
        for entry in (self.source / "scripts/test_workflow.sh", PACK / "scripts/test_workflow.sh"):
            with self.subTest(entry=entry):
                # 单独校验 CI 实际传入的 current；同时传入所有产品组会掩盖 current 遗漏的模块。
                listed = self.invoke("--list", "current", entry=entry)
                self.assertEqual(0, listed.returncode, listed.stderr)
                self.assertCountEqual(expected, listed.stdout.splitlines())
        # 在执行任何夹具前拒绝被有效父模块覆盖的错误子节点。
        rejected = self.invoke("current", "tests.test_task_graph_records.ExampleTest.missing")
        self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertEqual([], self.recorded_cases())
        executed = self.invoke(*selectors)
        self.assertEqual(0, executed.returncode, executed.stdout + executed.stderr)
        self.assertCountEqual({target + ".ExampleTest.test_ok" for target in expected},
                              [case["id"] for case in self.recorded_cases()])

    def test_retired_groups_are_rejected_before_collecting_cases(self):
        for group in ("codex", "claude", "antigravity", "hosts", "central", "service", "tui",
                      "pty", "ci", "legacy-ci"):
            with self.subTest(group=group):
                result = self.invoke(group)
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                self.assertIn("未知测试组或节点", result.stderr)
        self.assertEqual([], self.recorded_cases())

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

    def test_plugin_publication_is_manual_main_only_and_writes_in_one_job(self):
        # 自动验证继续只读；发布必须显式触发、绑定 main 当前 SHA 与成功 push 附件。
        # 静态合同锁定权限/来源边界，publisher 的真实 Git 原子发布另有行为测试。
        workflow = (PACK / ".github/workflows/publish-plugins.yml").read_text(encoding="utf-8")
        for fragment in ("  workflow_dispatch:", "  contents: read", "  actions: read",
                         "cancel-in-progress: false", "    needs: verify-candidate",
                         "ref: ${{ github.sha }}", "persist-credentials: false",
                         'actions/workflows/release.yml/runs', '-f event=push -f status=success',
                         '-f head_sha="$GITHUB_SHA"', 'run["head_branch"] == "main"',
                         'run["conclusion"] == "success"',
                         'run["path"] == ".github/workflows/release.yml"',
                         'run["head_repository"]["full_name"] == repository',
                         '"product-candidate-" + os.environ["GITHUB_SHA"]',
                         'len(matches) != 1', 'matches[0]["expired"]',
                         'artifact.get("digest", "")', 'hashlib.sha256(body).hexdigest()',
                         "packaging/publish_plugin_sources.py", '--source-revision "$GITHUB_SHA"',
                         "--repository Geoege-xll/agent-workflow", "--channel stable --apply"):
            self.assertIn(fragment, workflow)
        self.assertEqual(2, workflow.count("github.ref == 'refs/heads/main'"))
        self.assertEqual(2, workflow.count("github.event_name == 'workflow_dispatch'"))
        self.assertEqual(1, workflow.count("contents: write"))
        before_publish, publish = workflow.split("\n  publish:\n", 1)
        self.assertNotIn("contents: write", before_publish)
        self.assertIn("contents: write", publish)
        for forbidden in ("  push:", "  pull_request:", "pull_request_target", "workflow_run:",
                          "inputs:", "github.event.inputs", "--force", "gh release", "tags: write",
                          "windows-latest", "git push", "packaging/build_candidates.py"):
            self.assertNotIn(forbidden, workflow)

    def publication_python_blocks(self):
        # 直接执行工作流中实际使用的校验块，避免测试复制过滤逻辑后两边一起假绿。
        workflow = (PACK / ".github/workflows/publish-plugins.yml").read_text(encoding="utf-8")
        blocks = re.findall(r"(?ms)^          python3 - <<'PY'\n(.*?)^          PY$", workflow)
        self.assertEqual(3, len(blocks))
        return [textwrap.dedent(block) for block in blocks]

    def invoke_publication_block(self, block, extra_environment=None):
        output = self.root / "publication-output"
        output.unlink(missing_ok=True)
        result = subprocess.run(
            [sys.executable, "-B", "-c", block], cwd=self.root,
            env={**self.environment, "RUNNER_TEMP": str(self.root), "GITHUB_OUTPUT": str(output),
                 "GITHUB_SHA": "a" * 40, "GITHUB_REPOSITORY": "Geoege-xll/agent-workflow",
                 **(extra_environment or {})},
            capture_output=True, text=True, timeout=10,
        )
        return result, output.read_text() if output.exists() else ""

    def test_publication_gate_rejects_unverified_runs_and_selects_latest_exact_source(self):
        block = self.publication_python_blocks()[0]
        valid = {"id": 21, "head_sha": "a" * 40, "head_branch": "main", "event": "push",
                 "status": "completed", "conclusion": "success", "path": ".github/workflows/release.yml",
                 "head_repository": {"full_name": "Geoege-xll/agent-workflow"}}
        path = self.root / "candidate-runs.json"
        # GitHub API 会分页；混入更新但非当前来源的 run 不能越过任何一个来源条件。
        path.write_text(json.dumps([{"workflow_runs": [valid]},
                                    {"workflow_runs": [{**valid, "id": 22},
                                                       {**valid, "id": 99, "event": "pull_request"}]}]))
        result, output = self.invoke_publication_block(block)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("run-id=22\n", output)
        changes = ({"head_sha": "b" * 40}, {"head_branch": "feature"}, {"event": "pull_request"},
                   {"status": "in_progress"}, {"conclusion": "failure"},
                   {"path": ".github/workflows/other.yml"},
                   {"head_repository": {"full_name": "other/repository"}})
        for change in changes:
            with self.subTest(change=change):
                path.write_text(json.dumps([{"workflow_runs": [{**valid, **change}]}]))
                result, output = self.invoke_publication_block(block)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", output)

    def test_publication_gate_requires_unique_live_artifact_and_server_digest(self):
        block = self.publication_python_blocks()[1]
        valid = {"id": 123, "name": "product-candidate-" + "a" * 40,
                 "expired": False, "size_in_bytes": 10, "digest": "sha256:" + "c" * 64}
        path = self.root / "candidate-artifacts.json"
        path.write_text(json.dumps([{"artifacts": [valid]}]))
        result, output = self.invoke_publication_block(block)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("artifact-id=123\nartifact-digest=sha256:" + "c" * 64 + "\n", output)
        invalid = ([], [valid, valid], [{**valid, "name": "product-candidate-other"}],
                   [{**valid, "expired": True}], [{**valid, "size_in_bytes": 0}],
                   [{**valid, "digest": ""}], [{**valid, "digest": "sha256:invalid"}])
        for artifacts in invalid:
            with self.subTest(artifacts=artifacts):
                path.write_text(json.dumps([{"artifacts": artifacts}]))
                result, output = self.invoke_publication_block(block)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", output)

    def test_publication_download_verifies_server_digest_before_safe_extraction(self):
        block = self.publication_python_blocks()[2]
        archive = self.root / "candidate.zip"
        extracted = self.root / "awf-verified-candidate"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("workflow/package.zip", b"candidate")
        digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
        result, _ = self.invoke_publication_block(block, {"ARTIFACT_DIGEST": digest})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"candidate", (extracted / "workflow/package.zip").read_bytes())
        shutil.rmtree(extracted)
        result, _ = self.invoke_publication_block(block, {"ARTIFACT_DIGEST": "sha256:" + "0" * 64})
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(extracted.exists())
        # 外层 artifact 即使服务端摘要正确，也不能在 publisher 校验前写出目标目录。
        for name in ("../escaped", "/absolute", "nested/../../escaped", "nested\\escaped"):
            with self.subTest(name=name):
                with zipfile.ZipFile(archive, "w") as stream:
                    stream.writestr(name, b"unsafe")
                digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
                result, _ = self.invoke_publication_block(block, {"ARTIFACT_DIGEST": digest})
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(extracted.exists())
                self.assertFalse((self.root / "escaped").exists())
        with zipfile.ZipFile(archive, "w") as stream:
            link = zipfile.ZipInfo("symlink")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            stream.writestr(link, "../escaped")
        digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
        result, _ = self.invoke_publication_block(block, {"ARTIFACT_DIGEST": digest})
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(extracted.exists())

    def test_packaging_group_covers_remote_publication_contract(self):
        listed = self.invoke("--list", "packaging", entry=PACK / "scripts/test_workflow.sh")
        self.assertEqual(0, listed.returncode, listed.stdout + listed.stderr)
        self.assertEqual(1, listed.stdout.splitlines().count("tests.test_plugin_source_publication"))

    def test_explicit_method_runs_only_that_case(self):
        self.write_case("plugin_delivery", ("test_one", "test_two"))
        target = "tests.test_plugin_delivery.ExampleTest.test_two"
        result = self.invoke(target)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual([target], [row["id"] for row in self.recorded_cases()])

    def test_physical_source_root_and_existing_runtime_flags_from_other_cwd(self):
        alias = self.root / "source alias"
        alias.symlink_to(self.source, target_is_directory=True)
        target = "tests.test_plugin_delivery.ExampleTest.test_ok"
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
        self.write_case("runner_failure", ("test_failure",), failing=True)
        result = self.invoke("tests.test_runner_failure")
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("FAILED (failures=1)", result.stderr)
        self.assertIn("受控 unittest 失败", result.stderr)
        self.assertEqual(1, len(self.recorded_cases()))

    def test_runtime_failure_exit_status_is_preserved(self):
        (self.source / "lib/python_runtime.sh").write_text("exit 23\n", encoding="utf-8")
        result = self.invoke("plugin")
        self.assertEqual(23, result.returncode, result.stdout + result.stderr)
        self.assertEqual([], self.recorded_cases())

    def test_full_is_explicit_and_lists_each_existing_module_once(self):
        # 新增但尚未登记的模块也必须出现在 full 的发现结果中。
        self.write_case("new_module", ("test_ok",))
        result = self.invoke("--list", "full", "plugin")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        expected = ["tests." + path.stem for path in sorted((self.source / "tests").glob("test_*.py"))]
        self.assertEqual(expected, result.stdout.splitlines())
        self.assertEqual([], self.recorded_cases())

    def test_prototype_entry_runs_the_prototype_group(self):
        result = self.invoke(entry=self.source / "scripts/test_prototype.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        targets = [row["id"].rsplit(".", 2)[0] for row in self.recorded_cases()]
        self.assertCountEqual(targets_for(PROTOTYPE_MODULES), targets)

    def test_real_existing_node_runs_through_repository_entry(self):
        # 受控夹具只能证明调度边界；另经真实入口执行既有生产消费者，证明当前
        # 源根、真实 python_runtime.sh 和 unittest 节点能一起运行，而非仅录制 mock。
        target = "tests.test_light_ui_copy.LightUICopyContractTest.test_light_ui_uses_real_conformance_contract_without_full_graph_or_approval"
        result = self.invoke(target, entry=PACK / "scripts/test_workflow.sh")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Ran 1 test", result.stderr)
        self.assertIn("OK", result.stderr)


if __name__ == "__main__":
    unittest.main()
