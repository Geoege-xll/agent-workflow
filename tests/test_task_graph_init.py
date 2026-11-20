"""真实 CLI 与文件边界回归：初始化只组装显式 PM 决定，不授予隐含权限。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from lib import task_graph_records as records
from lib.task_graph_cli import _execute, export_task_pack
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
"""


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
        index, builtin, project = task["controlled_document_access"]["documents"]
        self.assertEqual(("docs/STANDARDS.md", "full", []), (index["path"], index["mode"], index["rule_ids"]))
        for document, rule_id in ((builtin, "eng-common-005"), (project, "eng-mini-001")):
            self.assertEqual("targeted", document["mode"])
            self.assertEqual([rule_id], document["rule_ids"])
            self.assertEqual([rule_id], document["sections_or_queries"])
        # 使用独立 CLI 查询证明生成物被原入口消费；缺需求批准时不会 READY。
        for command, expected in (("validate", {"status": "valid"}), ("ready", {"ready": []})):
            checked = self.invoke(command, "--input", self.target)
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertEqual(expected, json.loads(checked.stdout))
        checked = self.invoke("qa-ready", "--input", self.target)
        self.assertFalse(json.loads(checked.stdout)["qa_ready"])

    def test_explicit_read_scopes_survive_real_task_pack_export(self):
        source = decisions()
        source["approved_gates"] = ["requirements_approved"]
        reason = "接口改动涉及多个互相约束的项目条款，需通读项目叶核对其例外。"
        heading = "Configuration, errors and maintenance"
        source["tasks"][0]["selected_standards"] = [
            {"path": BUILTIN_ENGINEERING, "mode": "targeted", "reason": "核对工程条款及其适用条件。",
             "sections_or_queries": [heading, "eng-common-005"]},
            {"path": MINI, "mode": "full", "reason": reason},
        ]
        # 走真实 init → task --output，验证 PM 的全文理由、附加定位、SHA 与写范围
        # 均进入独立 Worker 包；有针对性的查询也不能把已选规则替换成另一段正文。
        initialized = self.init(source)
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        target = self.root / "worker-pack.json"
        exported = self.invoke("task", "--input", self.target, "--task-id", "api",
                               "--output", target, "--expect-sha256", "missing")
        self.assertEqual(0, exported.returncode, exported.stderr)
        graph = json.loads(self.target.read_bytes())
        pack = json.loads(target.read_bytes())
        access = pack["task"]["controlled_document_access"]
        self.assertEqual(graph["tasks"][0]["controlled_document_access"], access)
        _, builtin, project = access["documents"]
        self.assertEqual(["eng-common-005", heading], builtin["sections_or_queries"])
        self.assertEqual("targeted", builtin["mode"])
        self.assertEqual(("full", reason, []), (project["mode"], project["reason"], project["sections_or_queries"]))
        self.assertEqual(["eng-mini-001"], project["rule_ids"])
        self.assertEqual(records.file_digest(self.root, MINI), project["content_fingerprint"])
        self.assertEqual(["src/api.py"], project["applies_to"])

    def test_solution_approval_is_reused_only_for_current_request_and_content(self):
        request = decisions()
        request.update(capacity=4, approved_gates=["requirements_approved"])
        decision = {"id": "retry-policy", "content": "失败后只允许手动重试。"}
        writers = request["tasks"]
        for task_id in ("client", "independent"):
            writers.append({**copy.deepcopy(writers[0]), "id": task_id, "owned_paths": [f"src/{task_id}.py"]})
        for writer in writers[:2]:
            writer["solution_decisions"] = [decision]
        writers.append({"id": "facts", "role": "xy-backend", "surface_kind": "non_ui", "solution_consultation": True,
                        "task_type": "read_only", "gates": [], "owned_paths": []})
        v2_graph(request)
        writers[-1].pop("qa_scope")  # init 根据既有角色合同生成此字段，精简输入只给决定。
        initialized = self.init(request)
        self.assertEqual(0, initialized.returncode, initialized.stderr)

        def patch(change):
            return self.invoke("update", "--input", self.target, "--expect-sha256",
                               records.digest(self.target.read_bytes()), "--patch", "-", input=json.dumps(change))

        def ready():
            result = self.invoke("ready", "--input", self.target)
            self.assertEqual(0, result.returncode, result.stderr)
            return set(json.loads(result.stdout)["ready"])

        self.assertEqual({"facts", "independent"}, ready())
        refused = self.invoke("task", "--input", self.target, "--task-id", "api")
        self.assertEqual(2, refused.returncode)
        self.assertIn("solution_approved", refused.stderr)
        approved = {"request_id": request["request_id"], "task_id": "api", **decision}
        before = self.target.read_bytes()
        for choice in ({**approved, "request_id": "另一请求"}, {**approved, "content": "允许自动重试。"}):
            denied = patch({"approve_solutions": [choice]})
            self.assertEqual(2, denied.returncode, denied.stderr)
            self.assertEqual(before, self.target.read_bytes())
        result = patch({"approve_solutions": [approved]})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"api", "client", "facts", "independent"}, ready())
        pack = self.invoke("task", "--input", self.target, "--task-id", "client")
        self.assertEqual(0, pack.returncode, pack.stderr)
        data = json.loads(pack.stdout)
        self.assertEqual([decision], data["task"]["solution_decisions"])
        gate, = [gate for gate in data["approved_gates"] if gate.startswith("solution_approved:")]
        self.assertRegex(gate, r"^solution_approved:retry-policy@[a-f0-9]{64}$")
        revoked = patch({"revoke_solutions": [approved]})
        self.assertEqual(0, revoked.returncode, revoked.stderr)
        self.assertEqual({"facts", "independent"}, ready())
        current = json.loads(self.target.read_bytes())["tasks"][0]
        self.assertEqual([decision], current["solution_decisions"])
        self.assertIn(gate, current["gates"])
        confirmed = patch({"approve_solutions": [approved]})
        self.assertEqual(0, confirmed.returncode, confirmed.stderr)
        # 已经交出的执行权限不能靠改批准数组冒称已经实际停止；同门其他 Writer
        # 也受此保护。协调并据实停回待派后，PM 才能修订或撤回。
        started = patch({"tasks": {"client": {"set": {"state": "RUNNING"}}}})
        self.assertEqual(0, started.returncode, started.stderr)
        before = self.target.read_bytes()
        self.assertIn("running or delivered", patch({"revoke_solutions": [approved]}).stderr)
        self.assertEqual(before, self.target.read_bytes())
        stopped = patch({"tasks": {"client": {"set": {"state": "DECLARED"}}}})
        self.assertEqual(0, stopped.returncode, stopped.stderr)
        facts = self.invoke("task", "--input", self.target, "--task-id", "facts")
        self.assertEqual(0, facts.returncode, facts.stderr)
        consult = json.loads(facts.stdout)
        for kind in ("read_only", "evidence"):
            revised_task = {**consult["task"], "task_type": kind, "owned_paths": ["src/api.py"]}
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "solution_consultation"):
                _execute("validate", {**consult, "task": revised_task})

        # 同请求同 ID 必须一次更新全部使用者。冲突拒绝后原图仍有效；
        # 真正换版本只撤下旧方案批准，原需求批准仍然可用。
        revised = {"set": {"solution_decisions": [{**decision, "content": "失败后自动重试一次。"}]}}
        before = self.target.read_bytes()
        conflict = patch({"tasks": {"api": revised}})
        self.assertEqual(2, conflict.returncode)
        self.assertIn("conflicting solution_decisions", conflict.stderr)
        self.assertEqual(before, self.target.read_bytes())
        changed = patch({"tasks": {"api": revised, "client": revised}})
        self.assertEqual(0, changed.returncode, changed.stderr)
        self.assertEqual(["requirements_approved"], json.loads(self.target.read_bytes())["approved_gates"])
        self.assertEqual({"facts", "independent"}, ready())
        self.assertEqual(2, patch({"approve_solutions": [approved]}).returncode)

    def test_design_consultation_can_be_claimed_while_the_prototype_waits(self):
        from lib.dispatch_admission_cli import admission

        source = decisions()
        source.update(request_scope="implementation", approved_gates=["requirements_approved"])
        design = "platforms/shared/skills/xy-ui-design/references/foundations-rules.md"
        (self.root / design).parent.mkdir(parents=True)
        (self.root / design).write_bytes((PACK / design).read_bytes())
        source["standards"]["required_design_rule_ids"] = ["des-baseline-001"]
        source["standards"]["leaves"].append({"path": design, "domain": "design", "rule_ids": ["des-baseline-001"]})
        prototype = source["tasks"][0]
        prototype.update(id="prototype", role="xy-uiux", surface_kind="design_ui",
                         owned_paths=["docs/standards/prototype/checkout.html"], selected_standards=[design],
                         audit_surfaces=["ui", "accessibility"], solution_decisions=[
                             {"id": "checkout", "content": "提交前显示订单确认步骤。"}])
        source["tasks"].append({**prototype, "id": "consult", "task_type": "read_only", "solution_consultation": True,
                                "goal": "只读核实现有订单确认表现", "owned_paths": [], "gates": []})
        source["tasks"][-1].pop("solution_decisions")
        initialized = self.init(source)
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        result = self.invoke("ready", "--input", self.target)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["consult"], json.loads(result.stdout)["ready"])
        handoff = self.invoke("task", "--input", self.target, "--task-id", "consult")
        self.assertEqual(0, handoff.returncode, handoff.stderr)
        pack = json.loads(handoff.stdout)
        self.assertEqual([design], [leaf["path"] for leaf in pack["standards_contract"]["leaves"]])
        descriptor = {"path": str(self.target), "sha256": records.digest(self.target.read_bytes()),
                      "execution_roots": {task["id"]: str(self.root) for task in source["tasks"]}}
        manifest = {"schema_version": 1, "project_root": str(self.root), "records": [descriptor],
                    "capacity": {"configured_subagents": 2, "configured_writers": 1, "host_available_subagents": 2}}
        target = {"record": str(self.target), "request_id": source["request_id"], "task_id": "consult"}
        self.assertEqual("claimed", admission("claim", manifest, target)["status"])
        claimed = json.loads(self.target.read_bytes())
        self.assertEqual("RUNNING", claimed["tasks"][1]["state"])
        self.assertEqual([], claimed["active_paths"])

        # 只读咨询没有原型或生产写范围，不能转成 Light 设计；原包即使合法，
        # 改用只讨论/仅原型范围时也必须按原权限拒绝派发。
        for fields in ({"owned_paths": ["src/checkout.py"]}, {"design_mode": "prototype"},
                       {"surface_kind": "production_ui"}, {"workflow_level": "Light"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                _execute("validate", {**pack, "task": {**pack["task"], **fields}}, root=self.root)
        for scope in ("discussion_only", "prototype_only"):
            with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, scope):
                _execute("validate", {**pack, "request_scope": scope}, root=self.root)

    def test_invalid_read_decisions_cannot_hide_or_redefine_selected_rules(self):
        selection = {"path": MINI, "mode": "targeted", "reason": "按已选接口条款核对。"}
        for entry in (dict(selection, mode="skip"), dict(selection, mode="full", reason=" "),
                      dict(selection, sections_or_queries=[None]), dict(selection, rule_ids=[]),
                      dict(selection, path="docs/standards/unselected.md")):
            source = decisions()
            source["tasks"][0]["selected_standards"] = [BUILTIN_ENGINEERING, entry]
            with self.subTest(entry=entry):
                self.assert_rejected(source)
        source = decisions()
        source["tasks"][0]["selected_standards"].append(selection)
        self.assert_rejected(source, contains="duplicate paths")

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
        installed = self.root / ".awf"
        installed.mkdir()
        (self.root / "project.yaml").rename(installed / "project.yaml")
        self.assert_rejected(contains="project.yaml")
        source = decisions()
        source["adapter_path"] = ".agent-workflow/project.yaml"
        self.assert_rejected(source, contains="adapter_path")
        source["adapter_path"] = ".awf/project.yaml"
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
        # 用户同意本任务的技术方案，不代表同意修改受保护的上游文件。就绪和正式
        # Writer 导出都必须继续等待原来的例外，且批准只针对具体决定的当前正文。
        choice = {"id": "repair", "content": "采用兼容现有协议的修复。"}
        graph = records.update(graph, {"tasks": {"api": {"set": {"solution_decisions": [choice]}}}},
                               self.root, _execute)
        graph = records.update(graph, {"approve_solutions": [
            {"request_id": source["request_id"], "task_id": "api", **choice}]}, self.root, _execute)
        self.assertEqual([], _execute("ready", graph)["ready"])
        with self.assertRaisesRegex(ValueError, "exceptional:upstream-fix"):
            export_task_pack(graph, "api")
        self.target.unlink()
        source["standards"]["protected_paths"][0]["direct_edit"] = False
        self.assert_rejected(source, contains="forbidden_without_exception")

    def test_business_exception_is_bound_to_its_gate_on_init_export_and_qa(self):
        from lib.task_graph_cli import _execute, export_task_pack, _verify_solution_scope
        from tests.test_scheduler_boundaries import v2_task
        source = decisions()
        task = source["tasks"][0]
        gate = "exceptional:rollback-window"
        task["gates"].append(gate)
        source["approved_gates"] = ["requirements_approved", gate]
        self.assert_rejected(source, contains="additional_business_confirmation")
        record = {"name": "rollback-window", "reason": "用户明确要求单独选择回滚窗口",
                  "decision_scope": "数据回滚保留时间", "options": ["两天", "一周"],
                  "evidence": ["user:request/retain-week"], "resume_condition": "明确选择保留一周"}
        for field, value in (("name", "another"), ("reason", " "), ("decision_scope", []),
                             ("options", []), ("evidence", [None]), ("resume_condition", "TBD")):
            task["additional_business_confirmation"] = {**record, field: value}
            self.assert_rejected(source, contains="additional_business_confirmation")
        task["additional_business_confirmation"] = record
        out = self.init(source)
        self.assertEqual(0, out.returncode, out.stderr)
        stored = json.loads(self.target.read_bytes())
        self.assertEqual(record, export_task_pack(stored, task["id"])["task"]["additional_business_confirmation"])
        stored["tasks"][0].update(state="BUILD_VERIFIED", blocks=["qa"])
        stored["tasks"].append(v2_task({"id": "qa", "request_id": source["request_id"], "task_type": "qa",
                                        "state": "DECLARED", "depends_on": [task["id"]], "blocks": [],
                                        "gates": [], "owned_paths": [], "semantic_locks": []}))
        qa = export_task_pack(stored, "qa", root=self.root)
        self.assertEqual(record, qa["reviewed_business_confirmations"][0]["additional_business_confirmation"])
        self.assertEqual({"status": "valid"}, _execute("validate", qa))
        changed = copy.deepcopy(qa)
        changed["reviewed_business_confirmations"][0]["additional_business_confirmation"]["options"] = ["错误内容"]
        with self.assertRaisesRegex(ValueError, "business confirmations differ"):
            _verify_solution_scope(changed, stored)

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
