"""运行时选择和宿主工作副本隔离的行为回归，只操作临时项目。"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.project_discovery import DiscoveryOverrides, ModuleOverride, discover_project


PACK = Path(__file__).resolve().parents[1]


class PythonRuntimeSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="workflow-python-runtime-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.environment = dict(os.environ)
        self.environment.pop("AGENT_WORKFLOW_PYTHON", None)
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
        self.environment["PATH"] = str(self.bin)

    def interpreter(self, name: str, *, supported: bool) -> Path:
        # 旧解释器桩明确拒绝版本探测；有效桩交给当前测试解释器执行真实 Python，
        # 因而这里验证选择结果及参数转发，而不是检查脚本是否包含某个版本字符串。
        target = self.bin / name
        body = ("exec " + shlex.quote(sys.executable) + ' "$@"\n') if supported else "exit 1\n"
        target.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        target.chmod(0o755)
        return target

    def run_runtime(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(PACK / "lib/python_runtime.sh"), *arguments],
            env=self.environment, text=True, capture_output=True, check=False,
        )

    def test_old_default_falls_back_to_supported_versioned_python(self) -> None:
        self.interpreter("python3", supported=False)
        self.interpreter("python3.11", supported=True)
        result = self.run_runtime("-c", "import sys; print(sys.argv[1])", "参数含 空格")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("参数含 空格\n", result.stdout)

    def test_supported_default_does_not_need_a_versioned_binary(self) -> None:
        self.interpreter("python3", supported=True)
        result = self.run_runtime("-c", "print('selected')")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("selected\n", result.stdout)

    def test_direct_cli_imports_do_not_create_bytecode_artifacts(self) -> None:
        self.interpreter("python3", supported=True)
        self.environment.pop("PYTHONDONTWRITEBYTECODE", None)
        (self.root / "local_dependency.py").write_text("value = 7\n")
        script = self.root / "inspect.py"
        script.write_text("import local_dependency\nprint(local_dependency.value)\n")
        result = self.run_runtime(str(script))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("7\n", result.stdout)
        self.assertFalse((self.root / "__pycache__").exists())

    def test_explicit_runtime_with_spaces_is_preserved(self) -> None:
        target = self.interpreter("python with spaces", supported=True)
        self.environment["AGENT_WORKFLOW_PYTHON"] = str(target)
        result = self.run_runtime("-c", "print('explicit')")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("explicit\n", result.stdout)

    def test_unsupported_explicit_runtime_does_not_silently_fall_back(self) -> None:
        self.environment["AGENT_WORKFLOW_PYTHON"] = str(self.interpreter("old", supported=False))
        self.interpreter("python3", supported=True)
        result = self.run_runtime("-c", "print('must not run')")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Python >= 3.11", result.stderr)
        self.assertNotIn("must not run", result.stdout)

    def test_relative_explicit_runtime_is_fixed_before_child_changes_directory(self) -> None:
        target = self.interpreter("relative-python", supported=True)
        self.environment["AGENT_WORKFLOW_PYTHON"] = os.path.relpath(target, PACK)
        result = subprocess.run(
            ["/bin/bash", "-c", 'source lib/common.sh && cd / && python3 -c "print(42)"'],
            cwd=PACK, env={**self.environment, "PATH": self.environment["PATH"] + ":/usr/bin:/bin"},
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("42\n", result.stdout)

    def test_no_supported_runtime_fails_without_executing_the_command(self) -> None:
        self.interpreter("python3", supported=False)
        result = self.run_runtime("-c", "print('must not run')")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Python >= 3.11", result.stderr)
        self.assertEqual("", result.stdout)

    def test_utf8_inline_helper_uses_supported_runtime_in_an_ascii_locale(self) -> None:
        self.interpreter("python3", supported=False)
        self.interpreter("python3.11", supported=True)
        # 故意关闭环境隐式 UTF-8：验证规则给出的进程级参数确实生效，
        # 中文内联源码、含空格路径与文件内容均能往返，且不修改父进程环境。
        self.environment.update(LC_ALL="C", PYTHONCOERCECLOCALE="0", PYTHONUTF8="0")
        parent_environment = dict(os.environ)
        output = self.root / "任务 graph.json"
        helper = (
            "import json, sys\nfrom pathlib import Path\n"
            "path = Path(sys.argv[1])\n"
            "path.write_text(json.dumps({'说明': '中文任务'}, ensure_ascii=False), encoding='utf-8')\n"
            "assert json.loads(path.read_text(encoding='utf-8'))['说明'] == '中文任务'\n"
            "print(sys.flags.utf8_mode)\n"
        )
        result = subprocess.run(
            ["/bin/bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8", "-", str(output)],
            input=helper.encode("utf-8"), env=self.environment, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"1\n", result.stdout)
        self.assertEqual({"说明": "中文任务"}, json.loads(output.read_text(encoding="utf-8")))
        self.assertEqual(parent_environment, dict(os.environ))

    def documented_scheduler(self, stage: str = "ready") -> str:
        # 直接执行派发文档中的示例，避免另写一份正确脚本、却漏掉文档示例回归。
        # 临时项目只通过符号链接读取源包；测试入口禁止生成源包字节码。
        runtime = self.root / ".agent-workflow"
        if not runtime.exists():
            runtime.symlink_to(PACK, target_is_directory=True)
        self.environment["PATH"] = str(self.bin) + ":/usr/bin:/bin"
        self.environment["workflow_graph"] = str(self.root / "当前 graph.json")
        body = (PACK / "platforms/shared/skills/xy-workflow/references/dispatch.md").read_text(
            encoding="utf-8"
        )
        examples = [block for block in re.findall(r"```bash\n(.*?)```", body, re.DOTALL)
                    if "task_graph_cli.py validate" in block]
        self.assertEqual(1, len(examples), "应有一个可复用的受保护调度示例")
        return examples[0].replace("task_graph_cli.py ready", f"task_graph_cli.py {stage}")

    def run_scheduler_example(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", "-c", command], cwd=self.root, env=self.environment,
            text=True, capture_output=True, check=False,
        )

    def test_failed_producer_does_not_validate_a_stale_snapshot(self) -> None:
        self.interpreter("python3", supported=True)
        command = self.documented_scheduler()
        graph = Path(self.environment["workflow_graph"])
        graph.write_text("stale snapshot", encoding="utf-8")
        # 文件存在不能替代生成成功；若校验误执行，会产生额外错误并覆盖退出码。
        producer = "bash .agent-workflow/lib/python_runtime.sh -X utf8 -c 'raise SystemExit(7)'"
        result = self.run_scheduler_example(producer + " &&\n" + command)
        self.assertEqual(7, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stdout + result.stderr)
        self.assertEqual("stale snapshot", graph.read_text(encoding="utf-8"))

    def test_missing_or_invalid_snapshot_never_runs_a_second_query(self) -> None:
        self.interpreter("python3", supported=True)
        for stage in ("ready", "qa-ready"):
            for content in (None, "{broken JSON"):
                with self.subTest(stage=stage, content=content):
                    command = self.documented_scheduler(stage)
                    graph = Path(self.environment["workflow_graph"])
                    if content is None:
                        graph.unlink(missing_ok=True)
                    else:
                        graph.write_text(content, encoding="utf-8")
                    result = self.run_scheduler_example(command)
                    self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                    self.assertEqual("", result.stdout)
                    self.assertEqual(1, result.stderr.count("cannot read task graph JSON"))

    def test_documented_chain_queries_only_the_current_stage_after_validation(self) -> None:
        self.interpreter("python3", supported=True)
        # 只读任务无需生产规范合同，用最小合法图隔离命令依赖语义；不伪造 Writer。
        # 禁用隐式 UTF-8，并让任务 ID 真的包含中文，覆盖 CLI 输出而非仅内联生成。
        self.environment.update(LC_ALL="C", PYTHONCOERCECLOCALE="0", PYTHONUTF8="0")
        payload = {
            "tasks": [{"id": "中文任务", "request_id": "req-helper", "task_type": "read_only",
                       "owned_paths": [], "state": "DECLARED", "depends_on": [], "blocks": [],
                       "gates": [], "semantic_locks": []}],
            "request_id": "req-helper", "capacity": 1, "approved_gates": [],
            "active_paths": [], "active_semantic_locks": [],
        }
        for stage in ("ready", "qa-ready"):
            with self.subTest(stage=stage):
                command = self.documented_scheduler(stage)
                graph = Path(self.environment["workflow_graph"])
                graph.write_text(json.dumps(payload), encoding="utf-8")
                result = self.run_scheduler_example(command)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                outputs = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(2, len(outputs), outputs)
                self.assertEqual({"status": "valid"}, outputs[0])
                expected = {"ready": ["中文任务"]} if stage == "ready" else {
                    "qa_ready": False, "request_id": "req-helper"}
                self.assertEqual(expected, outputs[1])

    def test_documented_diagnostic_resolves_an_existing_runtime_without_path_guesses(self) -> None:
        self.interpreter("python3", supported=False)
        self.interpreter("python3.11", supported=True)
        self.documented_scheduler()
        body = (PACK / "platforms/shared/skills/xy-workflow/references/dispatch.md").read_text(
            encoding="utf-8"
        )
        diagnostic = next(block for block in re.findall(r"```bash\n(.*?)```", body, re.DOTALL)
                          if "print(sys.executable)" in block)
        result = self.run_scheduler_example(diagnostic)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(str(Path(sys.executable)) + "\n", result.stdout)

    def test_setup_rejects_unsupported_explicit_runtime_before_project_writes(self) -> None:
        project = self.root / "Project"
        project.mkdir()
        shutil.copytree(PACK, project / "agent_workflow", ignore=shutil.ignore_patterns("__pycache__"))
        self.environment["AGENT_WORKFLOW_PYTHON"] = str(self.interpreter("old", supported=False))
        self.environment["PATH"] += os.pathsep + "/usr/bin:/bin"
        before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
        result = subprocess.run(
            ["/bin/bash", "agent_workflow/setup_all.sh"], cwd=project,
            env=self.environment, text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Python >= 3.11", result.stderr)
        after = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


class HostWorkspaceDiscoveryTest(unittest.TestCase):
    def test_explicit_role_override_remains_available_without_scanning_host_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-host-override-") as temporary:
            project = Path(temporary)
            exceptional = project / ".agents" / "intentional-module"
            exceptional.mkdir(parents=True)
            (exceptional / "package.json").write_text("not valid JSON")
            # 明确路由是用户给定的独立事实，不等于授权重新扫描宿主目录或推断命令。
            profile = discover_project(project, DiscoveryOverrides(module_roles=(
                ModuleOverride(".agents/intentional-module", "xy-backend"),
            )))
            self.assertEqual([".agents/intentional-module"], [module.root for module in profile.modules])
            self.assertEqual((), profile.modules[0].verification_commands)

    def test_root_and_nested_host_copies_are_not_business_modules(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-host-discovery-") as temporary:
            project = Path(temporary)
            (project / "app").mkdir()
            (project / "app/package.json").write_text('{"dependencies":{"react":"19"}}')
            # 每个副本都包含真实可识别的业务清单；无效 JSON 还验证扫描器确实没有
            # 进入宿主管理目录，而不是先读取文件、再从最终模块列表中过滤。
            for host in (".claude", ".codex", ".agents"):
                for prefix in (project, project / "app"):
                    copied = prefix / host / "worktrees" / "unfinished"
                    copied.mkdir(parents=True)
                    (copied / "go.mod").write_text("module example.test/copy\n")
                    (copied / "package.json").write_text("not valid JSON")
            profile = discover_project(project)
            self.assertEqual(["app"], [module.root for module in profile.modules])
