"""验证2.0轻量文案的实际交接、标准覆盖、Full门禁与三宿主分发。

CLI通过仅证明确定性合同与安装产物，不冒充模型已判断低风险、读取真实页面或执行
原生实例隔离；这些语义继续由当前任务证据与唯一独立QA核对。
"""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.task_graph_cli import export_task_pack
from tests import test_design_standards_lifecycle as lifecycle
from tests.test_unified_host_workflow import UnifiedHostFixture


PACK = Path(__file__).resolve().parents[1]


def invoke_light_pack(pack: dict) -> subprocess.CompletedProcess[str]:
    """真实task出口要求已存在的--input文件，不能用stdin解析失败冒充合同拒绝。"""
    with tempfile.TemporaryDirectory(prefix="workflow-light-copy-") as temporary:
        # macOS的TMPDIR可经/var符号链接进入/private/var；安全读取器保留其拒绝规则，
        # 测试把自己创建的临时根先规范化，不把合法正例建立在不安全父路径上。
        source = Path(temporary).resolve() / "current-task-pack.json"
        source.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            ["bash", str(PACK / "lib/python_runtime.sh"), "-X", "utf8",
             str(PACK / "lib/task_graph_cli.py"), "task", "--input", str(source)],
            text=True, capture_output=True, check=False, timeout=20,
        )


def light_copy_pack() -> dict:
    """以当前生产UI规范夹具表达一项已确定的保存按钮文案纠正。

    先形成有效Full来源合同再取单任务投影，沿用实际工程／设计规则；只把当前已明确的
    零设计差量交付转为Light，不复用设计任务、批准、完整DAG或兄弟任务历史。
    """
    fixture = lifecycle.DesignStandardsLifecycleTest()
    payload = fixture.fixture(production=True)
    task = payload["tasks"][1]
    task.update(depends_on=[], blocks=[], goal="纠正已确认的保存按钮文案",
                input_contracts=["user:copy-fixture，仅按当前已确定的文字纠正，不变更业务或设计"],
                output_contracts=["当前按钮文字按已确定需求纠正，布局、行为和可访问性语义不变"],
                acceptance_evidence=["准确替换、占位符、真实资源加载与必要构建冒烟"],
                verification_commands=["project-scoped-build-and-resource-smoke"])
    task["ui_change"].update(
        route="UI-Conformance", design_delta="none", prototype_policy="not_applicable",
        prototype_decision=None,
        design_authority_refs=[{
            "kind": "design_standard", "authority_id": "current-theme",
            "path": "docs/standards/DESIGN_FOUNDATIONS.md", "anchor": "rules",
            "content_fingerprint": "d" * 64, "resolution_state": "resolved",
        }],
        affected_surfaces=["admin-save-button"], justification="当前已解析设计权威完全确定外观与行为",
    )
    payload["tasks"] = [task]
    pack = export_task_pack(payload, task["id"])
    pack["task"]["workflow_level"] = "Light"
    for field in ("depends_on", "blocks", "gates", "semantic_locks"):
        pack["task"].pop(field, None)
    pack["approved_gates"] = []
    return pack


class LightUICopyContractTest(UnifiedHostFixture, unittest.TestCase):
    def test_all_hosts_install_current_shared_modes_without_old_direct_pm_route(self):
        temporary, project, pack = self.install_all()
        self.addCleanup(temporary.cleanup)
        self.assertEqual((project / "CLAUDE.md").read_bytes(), b"@AGENTS.md\n")
        body = (project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("General Trivial early exit", body)
        self.assertIn(".agent-workflow/product/WORKFLOW.md", body)
        # 按字节核对实际分发的共用Skill和完整参考树；这证明没有宿主分叉或遗漏模式，
        # 不以某一句提示文案代替运行时或模型行为验证。
        for skill in ("xy-workflow", "xy-build-verify", "xy-qa-review", "xy-project-memory"):
            source = pack / "platforms/shared/skills" / skill
            expected = {str(path.relative_to(source)): path.read_bytes()
                        for path in source.rglob("*") if path.is_file()}
            for root in (".agents/skills", ".claude/skills"):
                actual_root = project / root / skill
                actual = {str(path.relative_to(actual_root)): path.read_bytes()
                          for path in actual_root.rglob("*") if path.is_file()}
                with self.subTest(skill=skill, root=root):
                    # 安装器自己的隐藏管理记录不是Skill正文；所有源文件仍逐个完整比较。
                    self.assertTrue(set(expected).issubset(actual))
                    for relative, content in expected.items():
                        self.assertEqual(content, actual[relative], relative)
        checked = self.run_script(project, "setup_all.sh", "--check")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_light_ui_uses_real_conformance_contract_without_full_graph_or_approval(self):
        pack = light_copy_pack()
        accepted = invoke_light_pack(pack)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        returned = json.loads(accepted.stdout)
        self.assertEqual(pack, returned)
        self.assertNotIn("tasks", returned)
        self.assertEqual([], returned["approved_gates"])
        self.assertEqual("production_ui", returned["task"]["surface_kind"])
        self.assertNotIn("gates", returned["task"])
        self.assertNotIn("handoff_assessment", returned["task"])

        # 轻量不等于省略生产UI权威、设计覆盖或最小验证；每个反例从已通过的同一包
        # 独立构造，保证失败来自目标边界，而非旧格式或无关前置错误。
        for case in ("missing-design", "unresolved-authority", "design-change", "missing-verification", "non-ui-disguise"):
            rejected_pack = copy.deepcopy(pack)
            task = rejected_pack["task"]
            if case == "missing-design":
                task["controlled_document_access"]["documents"] = [
                    doc for doc in task["controlled_document_access"]["documents"]
                    if "xy-ui-design/" not in doc["path"]]
            elif case == "unresolved-authority":
                task["ui_change"]["design_authority_refs"][0]["resolution_state"] = "pending"
            elif case == "design-change":
                task["ui_change"].update(route="UI-Flow", design_delta="changed")
            elif case == "missing-verification":
                task["verification_commands"] = []
            else:
                task["surface_kind"] = "non_ui"
            with self.subTest(case=case):
                result = invoke_light_pack(rejected_pack)
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)

    def test_full_ui_cannot_self_declare_old_level_or_qa_approval_bypass(self):
        fixture = lifecycle.DesignStandardsLifecycleTest()
        for field, value in (("skip_qa", True), ("classification", "Trivial"),
                             ("workflow_level", "Trivial")):
            payload = fixture.fixture(production=True)
            payload["tasks"][1][field] = value
            with self.subTest(field=field):
                rejected = fixture.invoke(payload, "ready")
                self.assertEqual(2, rejected.returncode)
                self.assertRegex(rejected.stderr, "unsupported field|workflow_level")

        # Full原型豁免只改变原型依赖，不能免去需求确认或唯一独立QA。
        payload = fixture.fixture(production=True)
        payload["approved_gates"] = []
        waiting = fixture.invoke(payload, "ready")
        self.assertEqual(0, waiting.returncode, waiting.stderr)
        self.assertEqual({"ready": []}, json.loads(waiting.stdout))
        payload["tasks"][1]["handoff_assessment"] = {
            "independent_qa": "not_required", "documentation": "not_required", "reason": "试图跳过Full审计",
        }
        rejected = fixture.invoke(payload)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("cannot waive independent QA", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
