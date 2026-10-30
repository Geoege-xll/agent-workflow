"""设计规范维护与原型选择的行为回归，不依赖真实项目或浏览器。"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path


PACK = Path(__file__).resolve().parents[1]


class DesignStandardsLifecycleTest(unittest.TestCase):
    def fixture(self, *, production: bool = False) -> dict:
        """直接构造当前合同，保证纯规范任务的可用性不依赖旧格式迁移助手。"""
        def document(path, fingerprint, rules, owned):
            return {
                "path": path, "mode": "targeted", "reason": "读取本任务适用规范",
                "sections_or_queries": ["适用规则"], "content_fingerprint": fingerprint,
                "applies_to": owned, "rule_ids": rules,
            }

        design_path = "docs/standards/DESIGN_FOUNDATIONS.md"
        task = {
            "id": "standards", "request_id": "visual-refresh", "task_type": "writer",
            "role": "xy-uiux", "surface_kind": "design_ui", "design_mode": "standards_only",
            "qa_scope": "request", "depends_on": [], "blocks": [],
            "gates": ["requirements_approved"], "owned_paths": [design_path],
            "semantic_locks": ["design-tokens"], "state": "DECLARED",
            "audit_surfaces": ["ui", "accessibility", "standards-conformance"],
        }
        web = {
            **copy.deepcopy(task), "id": "web", "role": "xy-web", "surface_kind": "production_ui",
            "depends_on": ["standards"], "owned_paths": ["apps/web/theme.ts"],
            "ui_change": {
                "route": "UI-Flow", "design_delta": "changed", "prototype_policy": "waived_by_user",
                "prototype_decision": {
                    "source": "requirements_confirmation_user_choice",
                    "choice_ref": "user:visual-refresh/direct", "requirement_fingerprint": "a" * 64,
                    "affected_surfaces": ["admin"], "recommended_policy": "required",
                    "recommendation_reason": "整体换肤建议先确认，但用户选择直接实现",
                    "selected_policy": "waived_by_user",
                },
                "affected_surfaces": ["admin"], "design_authority_refs": [],
                "justification": "仅后台采用已确认的新视觉，不修改原型",
            },
        }
        web.pop("design_mode")
        tasks = [task, web] if production else [task]
        if production:
            task["blocks"] = ["web"]
            task["state"] = "BUILD_VERIFIED"
        for item in tasks:
            owned = item["owned_paths"]
            docs = [document("docs/STANDARDS.md", "c" * 64, [], owned),
                    document(design_path, "d" * 64, ["des-theme"], owned)]
            if item["surface_kind"] == "production_ui":
                docs.append(document("docs/standards/GENERAL.md", "e" * 64,
                                     ["eng-source"], owned))
            item["controlled_document_access"] = {"adapter": "project.yaml", "documents": docs}
        return {
            "tasks": tasks, "requirements_fingerprint": "a" * 64,
            "ui_contract": {"prototype_paths": ["docs/standards/prototype"]},
            "standards_contract": {
                "index_path": "docs/STANDARDS.md", "root": "docs/standards",
                "index_fingerprint": "c" * 64, "required_engineering_rule_ids": ["eng-source"],
                "required_design_rule_ids": ["des-theme"], "protected_paths": [],
                "leaves": [
                    {"path": design_path, "domain": "design", "content_fingerprint": "d" * 64,
                     "rule_ids": ["des-theme"]},
                    {"path": "docs/standards/GENERAL.md", "domain": "engineering",
                     "content_fingerprint": "e" * 64, "rule_ids": ["eng-source"]},
                ],
            },
            "approved_gates": ["requirements_approved"], "active_paths": [],
            "active_semantic_locks": [], "capacity": 2,
        }

    def invoke(self, payload, command="validate"):
        return subprocess.run(
            [sys.executable, str(PACK / "lib/task_graph_cli.py"), command],
            input=json.dumps(payload), text=True, capture_output=True, check=False,
        )

    def test_standards_only_is_ready_without_html_or_visual_gate(self):
        # 输入只是路径合同，未建立任何原型文件；不能因此强制补建原型。
        result = self.invoke(self.fixture(), "ready")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"ready": ["standards"]}, json.loads(result.stdout))

    def test_standards_only_still_waits_for_existing_requirements_approval(self):
        payload = self.fixture()
        payload["approved_gates"] = []
        result = self.invoke(payload, "ready")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"ready": []}, json.loads(result.stdout))
        payload["tasks"][0]["gates"] = []
        self.assertNotEqual(0, self.invoke(payload).returncode)

    def test_waived_production_can_wait_for_standards_without_prototype(self):
        payload = self.fixture(production=True)
        result = self.invoke(payload, "ready")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"ready": ["web"]}, json.loads(result.stdout))
        payload["tasks"][0]["state"] = "DECLARED"
        waiting = self.invoke(payload, "ready")
        self.assertEqual(0, waiting.returncode, waiting.stderr)
        self.assertEqual({"ready": ["standards"]}, json.loads(waiting.stdout))

    def test_standards_only_rejects_prototype_code_reference_and_broad_paths(self):
        for path in ("docs/standards/design", "docs/STANDARDS.md", "apps/web/theme.ts",
                     "docs/standards/prototype/index.html", "docs/standards/prototype.css",
                     "docs/standards/prototype/hidden.md", "docs/standards/design/references/spec.md"):
            with self.subTest(path=path):
                payload = self.fixture()
                payload["tasks"][0]["owned_paths"] = [path]
                result = self.invoke(payload)
                self.assertNotEqual(0, result.returncode)
                self.assertRegex(result.stderr, "standards_only owns only exact|standards writes require exact shallow")

    def test_standards_only_rejects_visual_gate(self):
        for gate in ("visual_approved", "visual_approved:admin@" + "f" * 64):
            with self.subTest(gate=gate):
                payload = self.fixture()
                payload["tasks"][0]["gates"].append(gate)
                self.assertIn("standards_only must not declare", self.invoke(payload).stderr)

    def test_mode_cannot_disguise_other_roles_or_unknown_mode(self):
        payload = self.fixture(production=True)
        payload["tasks"][1]["design_mode"] = "standards_only"
        self.assertIn("design_mode requires xy-uiux", self.invoke(payload).stderr)
        for mode in (None, "skip", {}, "STANDARDS_ONLY"):
            with self.subTest(mode=mode):
                payload = self.fixture()
                payload["tasks"][0]["design_mode"] = mode
                self.assertIn("design_mode is unsupported", self.invoke(payload).stderr)

    def test_required_prototype_cannot_be_satisfied_by_standards_only(self):
        payload = self.fixture(production=True)
        web = payload["tasks"][1]
        web["ui_change"]["prototype_policy"] = "required"
        web["ui_change"]["prototype_decision"]["selected_policy"] = "required"
        web["ui_change"]["design_authority_refs"] = [{
            "kind": "prototype_contract", "authority_id": "admin",
            "path": "docs/standards/prototype/admin.html",
            "anchor": "contract", "content_fingerprint": "f" * 64, "resolution_state": "resolved",
        }]
        web["gates"].append("visual_approved:admin@" + "f" * 64)
        self.assertIn("requires a matching xy-uiux design dependency", self.invoke(payload).stderr)

    def test_waived_rejects_prototype_hidden_behind_standards_dependency(self):
        payload = self.fixture(production=True)
        standards = payload["tasks"][0]
        prototype = copy.deepcopy(standards)
        prototype.update(id="prototype", design_mode="prototype", blocks=["standards"],
                         owned_paths=["docs/standards/prototype/admin.html"])
        for doc in prototype["controlled_document_access"]["documents"]:
            doc["applies_to"] = prototype["owned_paths"]
        standards["depends_on"] = ["prototype"]
        payload["tasks"].insert(0, prototype)
        self.assertIn("waived_by_user must not depend on xy-uiux", self.invoke(payload).stderr)

    def test_adopted_standards_require_explicit_consumer_fingerprint_refresh(self):
        payload = self.fixture(production=True)
        maintenance, consumer = payload["tasks"]
        # 历史输入及可恢复的变更前内容属于既有任务证据，不能用新快照冒充原阅读记录。
        # CLI 不读取这些历史内容；本测试只证明保存它们不妨碍当前合同正常交接。
        original_reads = copy.deepcopy(maintenance["controlled_document_access"])
        maintenance["input_contracts"] = [{
            "original_controlled_document_access": copy.deepcopy(original_reads),
            "before_content": "# 已批准的旧视觉规则\n\n保留以供 QA 核对差异。",
        }]
        payload["standards_contract"]["leaves"][0]["content_fingerprint"] = "f" * 64
        # 已完成任务也不能夹带过期的“当前快照”；不能简单放开所有 BUILD_VERIFIED。
        self.assertIn("tasks[0] design standards leaf fingerprint is stale", self.invoke(payload).stderr)
        maintenance["controlled_document_access"]["documents"][1]["content_fingerprint"] = "f" * 64
        self.assertIn("fingerprint is stale", self.invoke(payload).stderr)
        consumer["controlled_document_access"]["documents"][1]["content_fingerprint"] = "f" * 64
        result = self.invoke(payload, "ready")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"ready": ["web"]}, json.loads(result.stdout))
        self.assertEqual("BUILD_VERIFIED", maintenance["state"])
        self.assertEqual(original_reads, maintenance["input_contracts"][0]["original_controlled_document_access"])

    def test_design_standard_authority_must_match_adopted_leaf(self):
        for route in ("UI-Flow", "UI-Conformance"):
            with self.subTest(route=route):
                payload = self.fixture(production=True)
                payload["standards_contract"]["leaves"][0]["content_fingerprint"] = "f" * 64
                for task in payload["tasks"]:
                    task["controlled_document_access"]["documents"][1]["content_fingerprint"] = "f" * 64
                web = payload["tasks"][1]
                if route == "UI-Conformance":
                    # 一致性任务只沿用已经采用的规范，不能借维护依赖暗中改变依据。
                    payload["tasks"] = [web]
                    web["depends_on"] = []
                    web["ui_change"].update(route=route, design_delta="none",
                                            prototype_policy="not_applicable", prototype_decision=None)
                authority = {
                    "kind": "design_standard", "authority_id": "theme",
                    "path": "docs/standards/DESIGN_FOUNDATIONS.md", "anchor": "rules",
                    "content_fingerprint": "d" * 64, "resolution_state": "resolved",
                }
                web["ui_change"]["design_authority_refs"] = [authority]
                stale = self.invoke(payload, "ready")
                self.assertEqual(2, stale.returncode)
                self.assertIn("design_standard fingerprint must match", stale.stderr)
                authority["content_fingerprint"] = "f" * 64
                current = self.invoke(payload, "ready")
                self.assertEqual(0, current.returncode, current.stderr)
                self.assertEqual({"ready": ["web"]}, json.loads(current.stdout))

    def test_standards_only_still_requires_design_reads(self):
        payload = self.fixture()
        payload["tasks"][0]["controlled_document_access"]["documents"][1]["mode"] = "skip"
        self.assertIn("must not skip a selected design", self.invoke(payload).stderr)


if __name__ == "__main__":
    unittest.main()
