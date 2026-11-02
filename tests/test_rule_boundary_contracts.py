"""保护文本规则的分支边界；实际 Agent 判断另外由独立情境审查验证。

这些检查不声称能执行自然语言规则，只防止已经清理的无条件指令和旧路径回流。
调度、运行时和原型的可执行语义由各自的行为测试负责。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from tests.skill_contract_helpers import read_contract


PACK = Path(__file__).resolve().parents[1]


class RuleBoundaryContractTest(unittest.TestCase):
    def test_standalone_audit_exits_before_implementation_acceptance(self) -> None:
        # 只保护新增分支的早退与防绕过边界，不把文本合同冒充模型行为测试。
        for relative, start_anchor, following in (
            ("platforms/shared/skills/xy-workflow/SKILL.md", "## Standalone read-only audit", "## Light 与 Full"),
            ("platforms/shared/skills/xy-qa-review/SKILL.md", "- For an audit-only request", "## Implementation acceptance"),
        ):
            with self.subTest(source=relative):
                body = (PACK / relative).read_text()
                start = body.index(start_anchor)
                end = body.index(following)
                self.assertLess(start, end)
                branch = " ".join(body[start:end].split())
                self.assertIn("stop", branch)
                self.assertIn("BUILD_VERIFIED", branch)
                self.assertIn("implementation QA PASS", branch)
                self.assertIn("Full", branch)
                # QA 已把独立审查并入任务分支；全局范围合同仍适用，不能只靠旧标题定位。
                self.assertIn("scope", " ".join(body[:end].split()))
                self.assertIn("standards", branch)
                if "xy-qa-review" in relative:
                    self.assertIn("qa_handoff_cli.py validate", body[end:])
                else:
                    self.assertIn("handoff", branch)

        workflow = (PACK / "product/WORKFLOW.md").read_text()
        branch = workflow.split("### Standalone read-only audit", 1)[1].split("### ", 1)[0]
        branch = " ".join(branch.split())
        self.assertIn("Do not audit the audit report again", branch)
        self.assertIn("Honor explicitly requested independent review, full re-review", branch)
        self.assertIn("mandatory project checks", branch)
        self.assertIn("Full implementation", branch)
        self.assertIn("independent QA barrier", branch)

    def test_workflow_python_examples_use_the_shared_runtime_selector(self) -> None:
        # 搜索真正被加载的角色/规则/Skill，避免安装脚本修好后某个低频模式仍
        # 指示 Agent 直接调用系统旧解释器。允许跨行空白，不依赖特定换行排版。
        sources = [* (PACK / "roles").glob("*.md"), * (PACK / "product").glob("*.md"),
                   * (PACK / "platforms/shared/skills").rglob("*.md")]
        for source in sources:
            with self.subTest(source=source.relative_to(PACK)):
                self.assertNotRegex(source.read_text(), r"\bpython3\s+(?:-B\s+)?agent_workflow/lib/\S+\.py")

    def test_native_bug_steps_do_not_unconditionally_dispatch_qa(self) -> None:
        for relative in ("product/WORKFLOW.md", "platforms/shared/skills/xy-workflow/SKILL.md"):
            with self.subTest(source=relative):
                body = (PACK / relative).read_text()
                match = re.search(r"native_bug_fix:\n(?P<steps>.*?)```", body, re.DOTALL)
                self.assertIsNotNone(match)
                steps = re.findall(r"^\s+- (\S+)$", match["steps"], re.MULTILINE)
                self.assertNotIn("request_unified_qa", steps)
                self.assertEqual("assess_task_level_closeout", steps[-1])
                # 仍保留按等级进入既有 QA 的明确指令，不能为了省步骤整体取消 QA。
                after = " ".join(body[match.end():match.end() + 600].split())
                self.assertIn("Light", after)
                self.assertIn("Full", after)
                self.assertIn("`request_unified_qa`", after)

    def test_role_standards_paths_are_shallow_and_design_is_surface_scoped(self) -> None:
        backend = (PACK / "roles/xy-backend.md").read_text()
        self.assertNotIn("docs.standards_root/engineering", backend)
        self.assertIn("工程基线使用 xy-code-standards/references/rules.md", backend)
        for role in ("xy-web", "xy-apple", "xy-android", "xy-desktop"):
            with self.subTest(role=role):
                body = " ".join((PACK / "roles" / f"{role}.md").read_text().split())
                self.assertIn("production_ui", body)
                self.assertIn("non_ui 不预载设计规则", body)
                self.assertIn("xy-code-standards/references/rules.md", body)

    def test_document_noop_depends_on_unchanged_recorded_facts(self) -> None:
        for relative in ("product/WORKFLOW.md", "product/AGENT_SCHEMA.md",
                         "platforms/shared/skills/xy-workflow/SKILL.md"):
            with self.subTest(source=relative):
                body = " ".join(read_contract(PACK / relative).split())
                # 在依赖升级类别对应的同一句规则内要求条件，避免别处虽然提到评估，
                # 具体分支却仍无条件覆盖评估结果。
                match = re.search(r"dependency upgrades,.*?`change_type: none`(?P<condition>[^.]+)\.", body)
                self.assertIsNotNone(match)
                self.assertIn("only when", match["condition"])
                self.assertIn("unchanged", match["condition"])

    def test_fingerprint_refresh_does_not_itself_grant_or_revoke_user_intent(self) -> None:
        workflow = " ".join((PACK / "product/WORKFLOW.md").read_text().split())
        self.assertIn("not automatically another user confirmation", workflow)
        self.assertIn("retain the original user approval and scope", workflow)
        self.assertIn("The verifier never grants approval or judges semantic equivalence", workflow)
        self.assertIn("uncertain equivalence or material changes require", workflow)
