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
from lib.task_graph_cli import _execute
from lib.task_graph_init import initialize


PACK = Path(__file__).resolve().parents[1]
GENERAL = "docs/standards/GENERAL.md"
MINI = "docs/standards/MINI_PROGRAM.md"
ADAPTER = """docs:
  standards: docs/STANDARDS.md
  standards_root: docs/standards/
  project: docs/PROJECT.md
  features: docs/features/
  plans: docs/plans/
  notes: docs/notes/
"""


def decisions():
    """规则与授权来自 PM 输入；夹具不靠初始化自动选规范或确认需求。"""
    return {
        "request_id": "修复小程序接口", "capacity": 1,
        "standards": {
            "required_engineering_rule_ids": ["eng-common-005", "eng-mini-001"],
            "required_design_rule_ids": [],
            "leaves": [
                {"path": GENERAL, "domain": "engineering", "rule_ids": ["eng-common-005"]},
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
            "selected_standards": [GENERAL, MINI],
        }],
    }


class TaskGraphInitTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workflow-init-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "docs/standards").mkdir(parents=True)
        (self.root / "project.yaml").write_text(ADAPTER, encoding="utf-8")
        (self.root / "docs/STANDARDS.md").write_text("# 规范索引\n", encoding="utf-8")
        (self.root / GENERAL).write_text("- Domain: engineering\n[eng-common-005] [hard] 中文注释\n", encoding="utf-8")
        (self.root / MINI).write_text("- Domain: engineering\n[eng-mini-001] [hard] 小程序边界\n", encoding="utf-8")
        self.target = self.root / "task-graph.json"

    def invoke(self, *args, input=None):
        return subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8",
                               str(PACK / "lib/task_graph_cli.py"), *map(str, args)],
                              input=input, text=True, capture_output=True, check=False, timeout=15)

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
        self.assertEqual("DECLARED", json.loads(task.stdout)["state"])
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
        for selected in ([GENERAL], [MINI], []):
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
        original = (self.root / GENERAL).read_bytes()
        other = self.root / "outside.md"
        other.write_bytes(original)
        for kind in ("symlink", "hardlink"):
            leaf = self.root / GENERAL
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
            original_leaf = (self.root / GENERAL).read_bytes()
            changed_once = False

            def validate(command, graph):
                nonlocal changed_once
                result = _execute(command, graph)
                if not changed_once:
                    changed_once = True
                    if changed == "standard":
                        (self.root / GENERAL).write_bytes(original_leaf + b"changed\n")
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
            (self.root / GENERAL).write_bytes(original_leaf)
            self.assertFalse(list(self.root.glob(".task-graph.json.workflow-*")))

    def test_duplicate_adapter_docs_cannot_silently_select_an_authority(self):
        config = self.root / "project.yaml"
        for body in (ADAPTER + ADAPTER, ADAPTER.replace("  standards: docs/STANDARDS.md", "  standards: docs/STANDARDS.md\n  standards: docs/OTHER.md")):
            config.write_text(body, encoding="utf-8")
            with self.subTest(body=body):
                self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
