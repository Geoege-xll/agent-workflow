"""真实 CLI 与文件边界回归：初始化只组装显式 PM 决定，不授予隐含权限。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

from lib import task_graph_records as records
from lib import runtime_store
from lib.standard_paths import BUILTIN_STANDARD_SOURCES
from lib.task_graph_cli import _execute
from lib.task_graph_init import initialize
from tests.test_scheduler_boundaries import v2_graph


PACK = Path(__file__).resolve().parents[1]
BUILTIN_ENGINEERING = "platforms/shared/skills/xy-code-standards/references/rules.md"
MINI = "docs/standards/MINI_PROGRAM.md"
ADAPTER = """docs:
  standards: docs/STANDARDS.md
  standards_root: docs/standards/
  project: docs/PROJECT.md
  plans: docs/plans/
workflow_hooks:
  mode: off
"""


def activate_fixture_pin(root: Path, state: Path, core, *, used=()):
    """为最小规则库建立真实本机启用前置，不再只靠伪造桥环境猜测新任务许可。

    此夹具通过正式role_resource建立Codex两角色完整local投影和locator，
    避免把缺少全局角色的稀疏目录冒充可用项目。完整安装/原生宿主消费者由
    central_project测试承担，本文件只验证规则图初始化与固定来源读取。
    """
    from lib.central import runtime_project as project_files
    from lib.central.runtime_project import Node, Tree, absolute_directory, json_bytes, node_id
    from manager import runtime_policy
    from manager.runtime_state import read_state, state_relative, write_control, write_private
    with runtime_policy.coordination(state), absolute_directory(state / "bindings", create=True), Tree(root) as project, Tree(state) as machine:
        marker = project.read(".agent-workflow/runtime.json")
        binding = core.binding()
        resources = project_files.Resources(core.root, json_bytes(binding), core.label, core)
        config = project_files.initial_config(resources, root).replace(b"mode: assist", b"mode: off")
        (root / ".agent-workflow/project.yaml").write_bytes(config)
        managed = {".agent-workflow/runtime.json": {"purpose": "locator", "baseline": Node().value(), "expected": marker.value()}}
        for role in ("xy-qa", "xy-uiux"):
            relative = f".codex/agents/{role}.toml"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(project_files.role_resource(resources, config, "codex", role, binding))
            target.chmod(0o644)
            managed[relative] = {"purpose": "role", "baseline": Node().value(), "expected": project.read(relative).value()}
        history = list(used)
        if binding not in history:
            history.append(binding)
        record = {"schema_version": 1, "project_root": str(root), "project_identity": list(node_id(root.stat())),
                  "runtime_binding": binding, "enabled": True, "hosts": ["codex"], "previous_binding": None,
                  "used_bindings": history, "managed": managed,
                  "retained_nodes": [], "generation": uuid.uuid4().hex}
        write_private(machine, state_relative(root, "bindings"), json_bytes(record))
        write_control(machine, runtime_policy.CURRENT, json_bytes({"schema_version": 1, "runtime_binding": binding,
                      "previous_binding": None, "generation": uuid.uuid4().hex, "native_roots": []}), expected=read_state(state, runtime_policy.CURRENT))


def pinned_fixture(workspace: Path, *, engineering_body: bytes | None = None):
    """复用当前短命目录创建最小真实内容库；不复制整仓或建立第二业务环境。

    三份规则使用真实来源，分页入口及其六个直接／传递依赖也用生产源码。这样固定
    版本的字节、规则严重性和可运行读取均由真实 import_core／load_core 验证。
    """
    source, state = workspace / "pin-source", workspace / "pin-state"
    for name in runtime_store.CORE_DIRECTORIES:
        (source / name).mkdir(parents=True, exist_ok=True)
    for name in runtime_store.SETUP_FILES:
        (source / name).write_bytes(b"#!/bin/sh\nexit 0\n")
    for relative in BUILTIN_STANDARD_SOURCES:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        body = (engineering_body if relative == BUILTIN_ENGINEERING and engineering_body is not None
                else (PACK / relative).read_bytes())
        target.write_bytes(body)
    # 冻结真正运行的所属模块和纯文档包标识，不能再用旧平铺名称拼出不存在的路径。
    for relative in ("lib/__init__.py", "lib/documents/__init__.py", "lib/documents/context_read.py",
                     "lib/runtime_pins.py", "lib/runtime_store.py", "lib/standard_paths.py",
                     "lib/hosts/__init__.py", "lib/hosts/claude_instructions.py", "lib/platform_fs.py",
                     "templates/project.yaml.example", "roles/xy-qa.md", "roles/xy-uiux.md"):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PACK / relative).read_bytes())
    (source / "product/WORKFLOW.md").write_bytes("固定旧版工作流正文\n".encode())
    return source, state, runtime_store.import_core(source, state)


def pinned_environment(root: Path, state: Path, core) -> dict[str, str]:
    """只向本次子进程投影冻结桥合同，不更改宿主环境或全局安装。"""
    return {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(state),
            "AGENT_WORKFLOW_RUNTIME_BINDING": json.dumps(core.binding()),
            "AGENT_WORKFLOW_PROJECT_ROOT": str(root),
            "AGENT_WORKFLOW_CONFIG_PATH": str(root / ".agent-workflow/project.yaml"),
            "AGENT_WORKFLOW_CORE_ROOT": str(core.root)}


def decisions():
    """规则与授权来自 PM 输入；夹具不靠初始化自动选规范或确认需求。"""
    return v2_graph({
        "request_id": "修复小程序接口", "capacity": 1,
        "standards": {
            "required_engineering_rule_ids": ["eng-common-005", "eng-mini-001"],
            "required_design_rule_ids": [],
            "leaves": [
                {"path": BUILTIN_ENGINEERING, "domain": "engineering", "rule_ids": ["eng-common-005"]},
                {"path": MINI, "domain": "engineering", "rule_ids": ["eng-mini-001"]},
            ],
            "protected_paths": [],
        },
        "tasks": [{
            "id": "api", "task_type": "writer", "role": "xy-backend", "surface_kind": "non_ui",
            "gates": ["requirements_approved"], "owned_paths": ["src/api.py"],
            "goal": "修复已确认接口", "input_contracts": ["需求与错误合同由 PM 明示"],
            "output_contracts": ["保留既有接口"], "acceptance_evidence": ["正常与失败边界"],
            "verification_commands": [{"run": "项目已存在的定向构建和运行命令", "expected": "退出 0"}],
            "selected_standards": [BUILTIN_ENGINEERING, MINI],
        }],
    })


class TaskGraphInitTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workflow-init-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "docs/standards").mkdir(parents=True)
        (self.root / "project.yaml").write_text(ADAPTER, encoding="utf-8")
        (self.root / "docs/STANDARDS.md").write_text("# 规范索引\n", encoding="utf-8")
        # 只提供真实规则资源，不复制旧源码包；init必须读取实际字节并生成当前指纹。
        builtin = self.root / BUILTIN_ENGINEERING
        builtin.parent.mkdir(parents=True)
        builtin.write_bytes((PACK / BUILTIN_ENGINEERING).read_bytes())
        (self.root / MINI).write_text("- Domain: engineering\n[eng-mini-001] [hard] 小程序边界\n", encoding="utf-8")
        self.target = self.root / "task-graph.json"

    def invoke(self, *args, input=None, env=None):
        return subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8",
                               str(PACK / "lib/task_graph_cli.py"), *map(str, args)],
                              input=input, text=True, capture_output=True, check=False, timeout=15, env=env)

    def test_central_init_export_refresh_and_old_pin_survive_project_upgrade(self):
        old_body = (PACK / BUILTIN_ENGINEERING).read_bytes() + "\n旧版中央规则正文\n".encode()
        source, state, old = pinned_fixture(self.root, engineering_body=old_body)
        installed = self.root / ".agent-workflow"
        installed.mkdir()
        (installed / "project.yaml").write_text(ADAPTER, encoding="utf-8")
        # 根适配器故意无效，证明中央初始化只使用桥计算的项目适配器。
        (self.root / "project.yaml").write_text("not the central adapter\n", encoding="utf-8")
        marker = installed / "runtime.json"
        marker.write_text(json.dumps({"schema_version": 1, "kind": "central", "runtime_binding": old.binding()}))
        activate_fixture_pin(self.root, state, old)
        (self.root / BUILTIN_ENGINEERING).unlink()
        (self.root / MINI).unlink()
        (self.root / "docs/STANDARDS.md").unlink()
        value = decisions()
        alias = ".agent-workflow/" + BUILTIN_ENGINEERING
        value["standards"].update(required_engineering_rule_ids=["eng-common-005"],
                                  leaves=[{"path": alias, "domain": "engineering", "rule_ids": ["eng-common-005"]}])
        value["tasks"][0]["selected_standards"] = [alias]
        env = pinned_environment(self.root, state, old)
        result = self.invoke("init", "--root", self.root, "--output", self.target,
                             input=json.dumps(value), env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        graph = json.loads(self.target.read_bytes())
        self.assertEqual(old.binding(), graph["runtime_binding"])
        self.assertIsNone(graph["standards_contract"]["index_fingerprint"])
        self.assertEqual(records.digest(old_body), graph["standards_contract"]["leaves"][0]["content_fingerprint"])
        self.assertFalse((self.root / "docs/STANDARDS.md").exists())
        self.assertFalse((self.root / "docs/standards/GENERAL.md").exists())
        exported = self.invoke("task", "--input", self.target, "--task-id", "api", env=env)
        self.assertEqual(0, exported.returncode, exported.stderr)
        self.assertEqual(old.binding(), json.loads(exported.stdout)["runtime_binding"])
        # 在同一最小来源原地换版并真实导入；项目的当前 marker／Skill 目录改到新版。
        (source / BUILTIN_ENGINEERING).write_bytes(old_body.replace("旧版".encode(), "新版".encode()))
        new = runtime_store.import_core(source, state)
        self.assertNotEqual(old.binding(), new.binding())
        marker.write_text(json.dumps({"schema_version": 1, "kind": "central", "runtime_binding": new.binding()}))
        (installed / "platforms").symlink_to(new.root / "platforms", target_is_directory=True)
        refreshed = self.invoke("update", "--input", self.target, "--root", self.root,
                                "--expect-sha256", records.digest(self.target.read_bytes()), "--patch", "-",
                                input=json.dumps({"refresh_documents": [alias]}), env=env)
        self.assertEqual(0, refreshed.returncode, refreshed.stderr)
        self.assertEqual(old.binding(), json.loads(self.target.read_bytes())["runtime_binding"])
        checked = self.invoke("validate", "--input", self.target, env=env)
        self.assertEqual(0, checked.returncode, checked.stderr)
        (self.root / "docs/PROJECT.md").write_text("# 当前项目\n", encoding="utf-8")
        (self.root / "docs/plans").mkdir()
        documents = subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                                    str(PACK / "lib/validate_project_docs.py"), str(installed / "project.yaml"),
                                    str(self.root)], env=env, capture_output=True, text=True,
                                   encoding="utf-8", timeout=15, check=False)
        self.assertEqual(0, documents.returncode, documents.stdout + documents.stderr)
        # 普通文件指纹没有获得跟随 Skill／目录链接读取外部核心的权限。
        with self.assertRaisesRegex(ValueError, "symlink"):
            records.file_digest(self.root, alias)
        conflict = self.invoke("validate", "--input", self.target,
                               env=pinned_environment(self.root, state, new))
        self.assertEqual(2, conflict.returncode)
        self.assertIn("冲突", conflict.stderr)
        # update 不能用任意层级的补丁把运行记录切到新核心。
        changed = self.invoke("update", "--input", self.target, "--expect-sha256",
                              records.digest(self.target.read_bytes()), "--patch", "-",
                              input=json.dumps({"runtime_binding": new.binding()}), env=env)
        self.assertEqual(2, changed.returncode)
        self.assertIn("supports only", changed.stderr)
        # 中央上下文缺 pin、跨项目显式根、伪造 core/config 根均拒绝，不创建新图。
        no_pin = dict(env)
        no_pin.pop("AGENT_WORKFLOW_RUNTIME_BINDING")
        for bad_env, bad_root in ((no_pin, self.root), (env, source),
                                  ({**env, "AGENT_WORKFLOW_CORE_ROOT": str(new.root)}, self.root),
                                  ({**env, "AGENT_WORKFLOW_CONFIG_PATH": str(self.root / "project.yaml")}, self.root)):
            with self.subTest(bad_root=bad_root, env_keys=sorted(bad_env)):
                rejected = self.invoke("init", "--root", bad_root, "--output", self.root / "never-created.json",
                                       input=json.dumps(value), env=bad_env)
                self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
                self.assertFalse((self.root / "never-created.json").exists())
        wrong_adapter = copy.deepcopy(value)
        wrong_adapter["standards"].update(index_path="other/STANDARDS.md", root="other/standards")
        # 新任务必须使用有效策略版；旧图的refresh/read已在上方证明继续固定旧pin。
        activate_fixture_pin(self.root, state, new, used=(old.binding(),))
        rejected = self.invoke("init", "--root", self.root, "--output", self.root / "never-created.json",
                               input=json.dumps(wrong_adapter), env=pinned_environment(self.root, state, new))
        self.assertEqual(2, rejected.returncode)
        self.assertIn("verified project adapter", rejected.stderr)

    def test_central_binding_is_closed_and_missing_or_corrupt_pin_has_no_fallback(self):
        _source, state, core = pinned_fixture(self.root)
        value = decisions()
        env = {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(state)}
        for binding in (None, {**core.binding(), "core_root": str(core.root)},
                        {**core.binding(), "protocol_version": True},
                        {"protocol_version": 1, "content_id": "0" * 64, "manifest_sha256": "0" * 64}):
            candidate = {**value, "runtime_binding": binding}
            rejected = self.invoke("init", "--root", self.root, "--output", self.target,
                                   input=json.dumps(candidate), env=env)
            self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
            self.assertFalse(self.target.exists())
        # 先验证存在的 pin，再篡改真实只读快照；本机源码仍完好也不能兜底。
        damaged = core.root / BUILTIN_ENGINEERING
        damaged.chmod(0o600)
        damaged.write_bytes(b"broken frozen rules\n")
        damaged.chmod(0o444)
        rejected = self.invoke("init", "--root", self.root, "--output", self.target,
                               input=json.dumps({**value, "runtime_binding": core.binding()}), env=env)
        self.assertEqual(2, rejected.returncode)
        self.assertFalse(self.target.exists())
        config = self.root / ".agent-workflow/project.yaml"
        config.parent.mkdir()
        config.write_text(ADAPTER)
        documents = subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                                    str(PACK / "lib/validate_project_docs.py"), str(config), str(self.root)],
                                   env=pinned_environment(self.root, state, core), capture_output=True,
                                   text=True, encoding="utf-8", timeout=15, check=False)
        self.assertEqual(1, documents.returncode)
        self.assertIn("invalid runtime binding", documents.stderr)

    def init(self, value=None, *, raw=None, extra=()):
        return self.invoke("init", "--root", self.root, "--output", self.target, *extra,
                           input=raw if raw is not None else json.dumps(value or decisions(), ensure_ascii=False))

    def assert_rejected(self, value=None, *, raw=None, contains=None, extra=()):
        result = self.init(value, raw=raw, extra=extra)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        error = json.loads(result.stderr)["error"]
        if contains:
            self.assertIn(contains, error)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.root.glob(".task-graph.json.workflow-*")))
        return error

    def test_real_cli_initializes_valid_graph_and_keeps_approval_explicit(self):
        source = decisions()
        result = self.init(source)
        self.assertEqual(0, result.returncode, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual({"initialized", "path", "sha256", "task_count"}, set(summary))
        self.assertEqual(str(self.target), summary["path"])
        self.assertEqual(records.digest(self.target.read_bytes()), summary["sha256"])
        graph = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual([], graph["approved_gates"])
        self.assertEqual([], graph["active_paths"])
        self.assertEqual([], graph["active_semantic_locks"])
        task = graph["tasks"][0]
        self.assertEqual("DECLARED", task["state"])
        self.assertEqual(source["tasks"][0]["gates"], task["gates"])
        self.assertEqual(source["tasks"][0]["verification_commands"], task["verification_commands"])
        self.assertEqual("project.yaml", task["controlled_document_access"]["adapter"])
        for document in task["controlled_document_access"]["documents"]:
            self.assertEqual(records.file_digest(self.root, document["path"]), document["content_fingerprint"])
            self.assertEqual(["src/api.py"], document["applies_to"])
        # 使用独立 CLI 查询证明生成物被原入口消费；缺需求批准时不会 READY。
        for command, expected in (("validate", {"status": "valid"}), ("ready", {"ready": []})):
            checked = self.invoke(command, "--input", self.target)
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertEqual(expected, json.loads(checked.stdout))
        checked = self.invoke("qa-ready", "--input", self.target)
        self.assertFalse(json.loads(checked.stdout)["qa_ready"])

    def test_builtin_only_init_has_no_project_general_or_phantom_index(self):
        source = decisions()
        source["standards"]["leaves"] = source["standards"]["leaves"][:1]
        source["standards"]["required_engineering_rule_ids"] = ["eng-common-005"]
        source["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
        (self.root / MINI).unlink()
        (self.root / "docs/standards").rmdir()
        (self.root / "docs/STANDARDS.md").unlink()
        result = self.init(source)
        self.assertEqual(0, result.returncode, result.stderr)
        graph = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertIsNone(graph["standards_contract"]["index_fingerprint"])
        self.assertEqual([BUILTIN_ENGINEERING], [item["path"] for item in graph["tasks"][0]["controlled_document_access"]["documents"]])
        self.assertFalse((self.root / "docs/STANDARDS.md").exists())
        self.assertFalse((self.root / "docs/standards").exists())
        self.assertEqual(0, self.invoke("validate", "--input", self.target).returncode)

    def test_new_init_rejects_legacy_only_and_hidden_project_rules(self):
        legacy = decisions()
        old_path = "docs/standards/GENERAL.md"
        (self.root / old_path).write_bytes((self.root / BUILTIN_ENGINEERING).read_bytes())
        legacy["standards"]["leaves"][0]["path"] = old_path
        legacy["tasks"][0]["selected_standards"][0] = old_path
        self.assert_rejected(legacy, contains="new init requires a selected builtin engineering")
        # 不能从声明中藏起真实项目叶，再用null指纹假称没有项目规范。
        (self.root / old_path).unlink()
        (self.root / "docs/STANDARDS.md").unlink()
        source = decisions()
        source["standards"]["leaves"] = source["standards"]["leaves"][:1]
        source["standards"]["required_engineering_rule_ids"] = ["eng-common-005"]
        source["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
        self.assert_rejected(source, contains="existing project standards rules")

    def test_absent_index_appearing_before_publication_is_preserved(self):
        source = decisions()
        source["standards"]["leaves"] = source["standards"]["leaves"][:1]
        source["standards"]["required_engineering_rule_ids"] = ["eng-common-005"]
        source["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING]
        (self.root / MINI).unlink()
        index = self.root / "docs/STANDARDS.md"
        index.unlink()

        def validate(command, graph):
            result = _execute(command, graph)
            if not index.exists():
                index.write_bytes(b"external index writer\n")
            return result

        with self.assertRaisesRegex(ValueError, "absent standards index changed"):
            initialize(source, self.root, self.target, validate)
        self.assertEqual(b"external index writer\n", index.read_bytes())
        self.assertFalse(self.target.exists())

    def test_standards_only_init_uses_builtin_design_without_project_index_or_prototype(self):
        source = decisions()
        design = "platforms/shared/skills/xy-ui-design/references/foundations-rules.md"
        target = self.root / design
        target.parent.mkdir(parents=True)
        target.write_bytes((PACK / design).read_bytes())
        source["standards"].update(required_engineering_rule_ids=[], required_design_rule_ids=["des-baseline-001"],
                                   leaves=[{"path": design, "domain": "design", "rule_ids": ["des-baseline-001"]}])
        source["tasks"][0].update(role="xy-uiux", surface_kind="design_ui", design_mode="standards_only",
                                   owned_paths=["docs/standards/DESIGN_PROJECT.md"], selected_standards=[design])
        source["tasks"][0]["audit_surfaces"] = ["ui", "accessibility", "standards-conformance"]
        (self.root / MINI).unlink()
        (self.root / "docs/STANDARDS.md").unlink()
        result = self.init(source)
        self.assertEqual(0, result.returncode, result.stderr)
        graph = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertIsNone(graph["standards_contract"]["index_fingerprint"])
        self.assertEqual([design], [doc["path"] for doc in graph["tasks"][0]["controlled_document_access"]["documents"]])
        self.assertNotIn("visual_approved", graph["tasks"][0]["gates"])
        self.assertFalse((self.root / "docs/standards/prototype").exists())

    def test_explicit_approval_input_file_and_existing_task_update_interfaces(self):
        source = decisions()
        source["approved_gates"] = ["requirements_approved"]
        source["requirements_fingerprint"] = "a" * 64
        decision_path = self.root / "pm-decisions.json"
        decision_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        result = self.invoke("init", "--root", self.root, "--input", decision_path, "--output", self.target)
        self.assertEqual(0, result.returncode, result.stderr)
        ready = self.invoke("ready", "--input", self.target)
        self.assertEqual({"ready": ["api"]}, json.loads(ready.stdout))
        task = self.invoke("task", "--input", self.target, "--task-id", "api")
        self.assertEqual("DECLARED", json.loads(task.stdout)["task"]["state"])
        result = self.invoke("update", "--input", self.target, "--expect-sha256", records.digest(self.target.read_bytes()),
                             "--patch", "-", input='{"tasks":{"api":{"set":{"state":"RUNNING"}}}}')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("RUNNING", json.loads(self.target.read_text(encoding="utf-8"))["tasks"][0]["state"])

    def test_adapter_selection_is_explicit_and_source_override_requires_both_paths(self):
        installed = self.root / ".agent-workflow"
        installed.mkdir()
        (self.root / "project.yaml").rename(installed / "project.yaml")
        self.assert_rejected(contains="project.yaml")
        source = decisions()
        source["adapter_path"] = ".agent-workflow/project.yaml"
        result = self.init(source)
        self.assertEqual(0, result.returncode, result.stderr)
        self.target.unlink()
        source.pop("adapter_path")
        source["standards"].update(index_path="docs/STANDARDS.md", root="docs/standards")
        result = self.init(source)
        self.assertEqual(0, result.returncode, result.stderr)
        self.target.unlink()
        source["standards"].pop("root")
        self.assert_rejected(source, contains="together")

    def test_missing_required_mini_program_rules_and_baseline_are_not_inferred(self):
        for selected in ([BUILTIN_ENGINEERING], [MINI], []):
            source = decisions()
            source["tasks"][0]["selected_standards"] = selected
            with self.subTest(selected=selected):
                self.assert_rejected(source)
        source = decisions()
        source["standards"]["required_engineering_rule_ids"] = []
        self.assert_rejected(source, contains="non-empty applicable")
        source = decisions()
        source["tasks"][0]["gates"] = []
        self.assert_rejected(source, contains="requires requirements_approved")

    def test_protected_paths_keep_fixed_direct_edit_and_exception_approval_gate(self):
        source = decisions()
        source["approved_gates"] = ["requirements_approved"]
        source["standards"]["protected_paths"] = [
            {"path": "src", "rule_id": "eng-mini-001", "allowed_paths": []},
        ]
        self.assert_rejected(source, contains="without an approved standards exception")
        source["tasks"][0]["gates"].append("exceptional:upstream-fix")
        source["tasks"][0]["standards_exceptions"] = [{
            "rule_id": "eng-mini-001", "gate": "exceptional:upstream-fix", "reason": "PM 已核实需修改此边界",
            "patch_surface": ["src/api.py"], "rollback_plan": "按现有可恢复版本回退", "verification_commands": ["项目定向检查"],
        }]
        result = self.init(source)
        self.assertEqual(0, result.returncode, result.stderr)
        graph = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual("forbidden_without_exception", graph["standards_contract"]["protected_paths"][0]["direct_edit"])
        self.assertEqual([], _execute("ready", graph)["ready"])
        self.target.unlink()
        source["standards"]["protected_paths"][0]["direct_edit"] = False
        self.assert_rejected(source, contains="forbidden_without_exception")

    def test_invalid_values_old_graphs_and_completion_containers_are_rejected(self):
        cases = []
        for field, value in (("capacity", True), ("capacity", -1), ("requirements_fingerprint", "bad"),
                             ("worktree_integrations", {}), ("approved_gates", ["requirements_approved", "requirements_approved"])):
            source = decisions()
            source[field] = value
            cases.append(source)
        for field, value in (("state", "BUILD_VERIFIED"), ("state", "DECLARED"), ("request_id", "other"),
                             ("agent_ref", {"host": "codex", "agent_id": "fixture-agent"}),
                             ("qa_scope", "request"), ("controlled_document_access", {}),
                             ("execution_workspace", {}), ("role", []), ("owned_paths", ["../private"]),
                             ("verification_commands", []), ("gates", ["auto_approved"])):
            source = decisions()
            source["tasks"][0][field] = value
            cases.append(source)
        for source in cases:
            with self.subTest(source=source):
                self.assert_rejected(source)
        self.assertEqual(0, self.init().returncode)
        old_graph = json.loads(self.target.read_text(encoding="utf-8"))
        self.target.unlink()
        self.assert_rejected(old_graph, contains="unsupported")
        self.assert_rejected(raw=json.dumps(decisions()).replace('"capacity": 1', '"capacity": NaN'))

    def test_duplicate_json_keys_and_invalid_paths_fail_without_publication(self):
        source = json.dumps(decisions())
        self.assert_rejected(raw=source.replace('"capacity": 1', '"capacity": 1, "capacity": 9'), contains="duplicate JSON key")
        self.assert_rejected(raw=source.replace('"id": "api"', '"id": "api", "id": "other"'), contains="duplicate JSON key")
        for path in ("../GENERAL.md", "/tmp/GENERAL.md", "docs/standards/../GENERAL.md", "docs\\GENERAL.md", []):
            value = decisions()
            value["standards"]["leaves"][0]["path"] = path
            with self.subTest(path=path):
                self.assert_rejected(value)

    def test_unsafe_input_documents_adapter_and_output_links_are_rejected(self):
        original = (self.root / BUILTIN_ENGINEERING).read_bytes()
        other = self.root / "outside.md"
        other.write_bytes(original)
        for kind in ("symlink", "hardlink"):
            leaf = self.root / BUILTIN_ENGINEERING
            leaf.unlink()
            if kind == "symlink":
                leaf.symlink_to(other)
            else:
                os.link(other, leaf)
            with self.subTest(kind=kind):
                self.assert_rejected()
            leaf.unlink()
            leaf.write_bytes(original)
        config = self.root / "project.yaml"
        config.rename(self.root / "real-config.yaml")
        config.symlink_to(self.root / "real-config.yaml")
        self.assert_rejected()
        config.unlink()
        (self.root / "real-config.yaml").rename(config)
        decision_path = self.root / "decision.json"
        decision_path.write_text(json.dumps(decisions()), encoding="utf-8")
        linked = self.root / "linked-decision.json"
        linked.symlink_to(decision_path)
        self.assert_rejected(extra=("--input", linked))
        parent = self.root / "linked-output"
        parent.symlink_to(self.root / "docs", target_is_directory=True)
        result = self.invoke("init", "--root", self.root, "--output", parent / "new.json", input=json.dumps(decisions()))
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertFalse((self.root / "docs/new.json").exists())

    def test_new_output_is_required_and_existing_empty_or_linked_files_stay_unchanged(self):
        result = self.invoke("init", "--root", self.root, input=json.dumps(decisions()))
        self.assertEqual(2, result.returncode)
        self.assertFalse(self.target.exists())
        self.assert_rejected(extra=("--expect-sha256", "missing"))
        self.target.write_bytes(b"")
        rejected = self.init()
        self.assertEqual(2, rejected.returncode)
        self.assertEqual(b"", self.target.read_bytes())
        self.target.unlink()
        self.target.symlink_to(self.root / "does-not-exist")
        rejected = self.init()
        self.assertEqual(2, rejected.returncode)
        self.assertTrue(self.target.is_symlink())

    def test_changed_sources_or_output_race_fail_without_replacing_any_record(self):
        for changed in ("standard", "decision", "output"):
            source = decisions()
            decision_path = self.root / "decisions.json"
            body = json.dumps(source).encode("utf-8")
            decision_path.write_bytes(body)
            original_leaf = (self.root / BUILTIN_ENGINEERING).read_bytes()
            changed_once = False

            def validate(command, graph):
                nonlocal changed_once
                result = _execute(command, graph)
                if not changed_once:
                    changed_once = True
                    if changed == "standard":
                        (self.root / BUILTIN_ENGINEERING).write_bytes(original_leaf + b"changed\n")
                    elif changed == "decision":
                        decision_path.write_bytes(body + b"\n")
                    else:
                        self.target.write_bytes(b"external writer")
                return result

            with self.subTest(changed=changed), self.assertRaises(ValueError):
                initialize(copy.deepcopy(source), self.root, self.target, validate,
                           input_path=decision_path, input_body=body)
            if changed == "output":
                self.assertEqual(b"external writer", self.target.read_bytes())
                self.target.unlink()
            else:
                self.assertFalse(self.target.exists())
            (self.root / BUILTIN_ENGINEERING).write_bytes(original_leaf)
            self.assertFalse(list(self.root.glob(".task-graph.json.workflow-*")))

    def test_duplicate_adapter_docs_cannot_silently_select_an_authority(self):
        config = self.root / "project.yaml"
        for body in (ADAPTER + ADAPTER, ADAPTER.replace("  standards: docs/STANDARDS.md", "  standards: docs/STANDARDS.md\n  standards: docs/OTHER.md")):
            config.write_text(body, encoding="utf-8")
            with self.subTest(body=body):
                self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
