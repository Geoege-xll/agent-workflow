"""实现阶段切换为仅修改产品的回归，不执行 Agent 或真实业务写入。

行为测试证明既有调度字段支持正确替换后的任务、保留未受影响门禁，并拒绝
遗留原型依赖；安装测试证明完整规则抵达三端。自然语言输出顺序与用户意图
解释另由独立情境审查验证，不用字符串断言冒充宿主实际行为。
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tests import test_design_standards_lifecycle as design_cases
from tests.test_unified_host_workflow import UnifiedHostFixture


PACK = Path(__file__).resolve().parents[1]


class ProductionOnlyRevisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = design_cases.DesignStandardsLifecycleTest()

    def graph(self, *, required: bool = False) -> dict:
        """复用正式规范合同；不为直接产品修正虚构额外规范维护任务。"""
        payload = self.helper.fixture(production=True)
        payload["request_id"] = "visual-refresh"
        designer, writer = payload["tasks"]
        writer["depends_on"] = []
        writer["semantic_locks"] = []
        payload["tasks"] = [writer]
        writer["goal"] = "按用户明确要求修改实际界面，不同步原型"
        writer["input_contracts"] = ["当前用户明确选择直接修改产品；原型仅为历史参考"]
        if not required:
            return payload
        designer.update(id="prototype", design_mode="prototype", state="BUILD_VERIFIED",
                        owned_paths=["docs/standards/prototype/admin.html"], blocks=["web"])
        for document in designer["controlled_document_access"]["documents"]:
            document["applies_to"] = designer["owned_paths"]
        writer["depends_on"] = ["prototype"]
        writer["ui_change"]["prototype_policy"] = "required"
        writer["ui_change"]["prototype_decision"]["selected_policy"] = "required"
        writer["ui_change"]["design_authority_refs"] = [{
            "kind": "prototype_contract", "authority_id": "admin",
            "path": "docs/standards/prototype/admin.html", "anchor": "contract",
            "content_fingerprint": "f" * 64, "resolution_state": "resolved",
        }]
        writer["gates"].append("visual_approved:admin@" + "f" * 64)
        payload["tasks"] = [designer, writer]
        return payload

    def test_replacement_is_ready_and_keeps_historical_policy_separate(self) -> None:
        previous = self.graph(required=True)
        historical = copy.deepcopy(previous)
        previous["approved_gates"].append("visual_approved:admin@" + "f" * 64)
        before = self.helper.invoke(previous, "ready")
        self.assertEqual({"ready": ["web"]}, json.loads(before.stdout), before.stderr)

        replacement = self.graph()
        replacement["requirements_fingerprint"] = "b" * 64
        decision = replacement["tasks"][0]["ui_change"]["prototype_decision"]
        decision.update(choice_ref="user:visual-refresh/production-only-revision",
                        requirement_fingerprint="b" * 64)
        current = self.helper.invoke(replacement, "ready")
        self.assertEqual(0, current.returncode, current.stderr)
        self.assertEqual({"ready": ["web"]}, json.loads(current.stdout))

        # 历史快照没有被伪造为新的用户批准；当前修正只需当前范围的生产 Writer。
        self.assertEqual("required", historical["tasks"][1]["ui_change"]["prototype_policy"])
        self.assertEqual(["web"], [task["id"] for task in replacement["tasks"]])
        waiting = self.helper.invoke(replacement, "qa-ready")
        self.assertEqual(0, waiting.returncode, waiting.stderr)
        self.assertFalse(json.loads(waiting.stdout)["qa_ready"])
        replacement["tasks"][0]["state"] = "BUILD_VERIFIED"
        ready = self.helper.invoke(replacement, "qa-ready")
        self.assertEqual(0, ready.returncode, ready.stderr)
        self.assertTrue(json.loads(ready.stdout)["qa_ready"], ready.stderr)

    def test_cutover_rejects_old_visual_authority_or_design_dependency(self) -> None:
        for defect in ("authority", "gate", "dependency"):
            with self.subTest(defect=defect):
                payload = self.graph()
                original = self.graph(required=True)
                writer = payload["tasks"][0]
                if defect == "authority":
                    writer["ui_change"]["design_authority_refs"] = original["tasks"][1]["ui_change"]["design_authority_refs"]
                elif defect == "gate":
                    writer["gates"] = original["tasks"][1]["gates"]
                else:
                    designer = original["tasks"][0]
                    writer["depends_on"] = [designer["id"]]
                    payload["tasks"].insert(0, designer)
                rejected = self.helper.invoke(payload, "ready")
                self.assertNotEqual(0, rejected.returncode)
                self.assertIn("waived_by_user", rejected.stderr)

    def test_production_only_does_not_waive_other_required_surface(self) -> None:
        payload = self.graph(required=True)
        unrelated = self.graph()["tasks"][0]
        unrelated.update(id="settings-fix", owned_paths=["apps/web/settings.ts"])
        unrelated["ui_change"]["affected_surfaces"] = ["settings"]
        unrelated["ui_change"]["prototype_decision"]["affected_surfaces"] = ["settings"]
        for document in unrelated["controlled_document_access"]["documents"]:
            document["applies_to"] = unrelated["owned_paths"]
        payload["tasks"].append(unrelated)
        # 同一快照内，明确跳过的独立表面可运行；没有批准的原型表面仍等待。
        result = self.helper.invoke(payload, "ready")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"ready": ["settings-fix"]}, json.loads(result.stdout))
        payload["approved_gates"].append("visual_approved:admin@" + "f" * 64)
        result = self.helper.invoke(payload, "ready")
        self.assertEqual({"ready": ["settings-fix", "web"]}, json.loads(result.stdout))

    def test_current_user_choice_scope_and_required_checks_remain_mandatory(self) -> None:
        for defect in ("missing-choice", "stale-requirement", "expanded-scope", "missing-ui-audit"):
            with self.subTest(defect=defect):
                payload = self.graph()
                writer = payload["tasks"][0]
                if defect == "missing-choice":
                    writer["ui_change"]["prototype_decision"] = None
                elif defect == "stale-requirement":
                    payload["requirements_fingerprint"] = "b" * 64
                elif defect == "expanded-scope":
                    writer["ui_change"]["affected_surfaces"].append("billing")
                else:
                    writer["audit_surfaces"].remove("accessibility")
                self.assertNotEqual(0, self.helper.invoke(payload).returncode)
        payload = self.graph()
        payload["approved_gates"] = []
        result = self.helper.invoke(payload, "ready")
        self.assertEqual({"ready": []}, json.loads(result.stdout))


class RevisionRuleInstallationTest(UnifiedHostFixture, unittest.TestCase):
    def test_full_revision_contract_is_installed_on_each_host(self) -> None:
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        # 角色按真实项目模块发现生成；提供最小 Web 模块才能验证设计角色的三端分发。
        web = project / "apps/web"
        web.mkdir(parents=True)
        (web / "package.json").write_text(
            '{"dependencies":{"react":"19"},"scripts":{"build":"vite build"}}',
            encoding="utf-8",
        )
        installed = self.run_script(project, "setup_all.sh")
        self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
        files = ("xy-workflow/SKILL.md", "xy-workflow/references/plan-lifecycle.md",
                 "xy-plan/SKILL.md", "xy-qa-review/SKILL.md")
        for root in (".agents/skills", ".claude/skills"):
            for relative in files:
                with self.subTest(root=root, relative=relative):
                    self.assertEqual((pack / "platforms/shared/skills" / relative).read_bytes(),
                                     (project / root / relative).read_bytes())
        for root in (".agents/agents", ".claude/agents", ".codex/agents"):
            for role in ("xy-uiux", "xy-qa"):
                with self.subTest(root=root, role=role):
                    suffix = ".toml" if root == ".codex/agents" else ".md"
                    self.assertTrue((project / root / (role + suffix)).is_file())
        # --check 会核对生成角色语义/来源与受管入口；不是只检查源码目录存在。
        checked = self.run_script(project, "setup_all.sh", "--check")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
