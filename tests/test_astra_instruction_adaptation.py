"""Astra 适配的可执行边界：引用校验、真实三宿主主会话与渐进规则。

自然语言指令的最终执行判断仍需独立情境审查/真实宿主反馈；这里不以文本断言
冒充模型行为测试，也不调用模型或实际业务项目。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import Mock

from lib.skills.skill_contracts import expand_skill_contract, verification_scope_errors
from tests.skill_contract_helpers import read_contract


PACK = Path(__file__).resolve().parents[1]

class ProgressiveContractTest(unittest.TestCase):
    def test_native_main_session_instructions_are_english(self) -> None:
        # 三端实际分发的主会话路由来自同一源，Claude 还会附带 PM 源正文。
        # 中文维护界面、开发者注释及项目文件不是这些主会话指令的组成部分。
        for relative in ("plugins/main-session-context.md", "plugins/claude/pm.md"):
            with self.subTest(source=relative):
                body = (PACK / relative).read_text(encoding="utf-8")
                self.assertTrue(body.strip())
                self.assertNotRegex(body, r"[\u4e00-\u9fff]")

    def test_verification_policy_keeps_mandatory_evidence_and_rejects_inversions(self) -> None:
        body = read_contract(PACK / "platforms/shared/skills/xy-build-verify/SKILL.md")
        self.assertEqual([], verification_scope_errors(body))
        for inversion in ("QA may skip mandatory checks.", "Always run all discovered commands.",
                          "Reuse evidence without checking inputs."):
            with self.subTest(inversion=inversion):
                self.assertTrue(verification_scope_errors(body + "\n" + inversion))

    def test_expansion_preserves_sequence_and_ignores_auxiliary_links(self) -> None:
        reader = Mock(return_value="required approval\n")
        source = ("before\n[When dispatching](references/dispatch.md)\n"
                  "<!-- workflow-contract: references/dispatch.md -->\n"
                  "after\n[Optional history](references/history.md)\n")
        result = expand_skill_contract(source, reader)
        reader.assert_called_once_with("references/dispatch.md")
        self.assertLess(result.index("before"), result.index("required approval"))
        self.assertLess(result.index("required approval"), result.index("after"))
        self.assertIn("[Optional history](references/history.md)", result)

    def test_invalid_reference_is_rejected_before_reading(self) -> None:
        # 输入不合法时不得调用读取器，避免把 Markdown 指令升级为任意文件读取。
        for reference in ("../secret.md", "/private/secret.md", "references/../secret.md",
                          "references/nested/rule.md", "https://example.test/rule.md"):
            with self.subTest(reference=reference):
                reader = Mock()
                source = f"[Read]({reference})\n<!-- workflow-contract: {reference} -->\n"
                with self.assertRaisesRegex(ValueError, "malformed"):
                    expand_skill_contract(source, reader)
                reader.assert_not_called()

    def test_duplicate_unlinked_empty_and_recursive_references_fail(self) -> None:
        marker = "<!-- workflow-contract: references/rules.md -->"
        source = f"[Read when needed](references/rules.md)\n{marker}\n"
        for body, detail, expected in (
            (source + marker, "rule", "duplicate"),
            (marker, "rule", "routing link"),
            (source, " \n", "empty"),
            (source, marker, "nested"),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                expand_skill_contract(body, lambda _reference: detail)

    def test_entrypoints_are_smaller_and_all_relative_markdown_links_resolve(self) -> None:
        for skill in ("xy-workflow", "xy-plan", "xy-qa-review"):
            directory = PACK / "platforms/shared/skills" / skill
            entry = directory / "SKILL.md"
            self.assertLess(len(entry.read_bytes()), len(read_contract(entry).encode("utf-8")))
            for path in directory.rglob("*.md"):
                for target in re.findall(r"\[[^\]\n]+\]\(([^)]+\.md)(?:#[^)]*)?\)",
                                         path.read_text(encoding="utf-8")):
                    if "://" not in target:
                        self.assertTrue((path.parent / target).is_file(), (path, target))
