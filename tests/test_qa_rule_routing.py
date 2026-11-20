"""沿 QA 入口核对只读审查分支能定位权威条款；不把文档导航测试当成真实模型验收。"""

import re
import unittest
from pathlib import Path

from lib.documents.context_read import read_page


PACK = Path(__file__).resolve().parents[1]
QA_ENTRY = PACK / "platforms/shared/skills/xy-qa-review/SKILL.md"


class QaRuleRoutingTest(unittest.TestCase):
    def test_read_only_routes_reach_original_applicable_rules(self) -> None:
        # 用实际入口中的链接找 Skill、章节与规则源，不另建规则目录。
        # 两种验收对象分别落到工程与设计域，其中弹窗焦点规则跨多行。
        cases = (
            ("工程规范入口", "工程条款", "eng-common-017"),
            ("设计规范入口", "组件与交互规则", "des-dialog-004"),
        )
        entry = QA_ENTRY.read_text(encoding="utf-8")
        for label, rule_link_label, rule_id in cases:
            with self.subTest(rule=rule_id):
                link = re.search(r"\[" + label + r"\]\(([^)#]+)#([^)]+)\)", entry)
                self.assertIsNotNone(link)
                skill = (QA_ENTRY.parent / link[1]).resolve(strict=True)
                sections = re.split(r"^## (.+)$", skill.read_text(encoding="utf-8"), flags=re.M)
                heading_to_body = dict(zip(sections[1::2], sections[2::2]))
                review = next(
                    body for heading, body in heading_to_body.items()
                    if heading.lower().replace(" ", "-") == link[2]
                )
                rule_link = re.search(r"\[" + rule_link_label + r"\]\(([^)]+)\)", review)
                self.assertIsNotNone(rule_link)
                self.assertNotIn("prototype-canvas.md", review)
                self.assertNotIn("prototype-feedback.md", review)

                # 先查一个带严重性的原文标识，再在同一指纹上展开整条规则。
                # 命中片段不足以覆盖多行条件，断言核对的是完整、同版的原文。
                source = (skill.parent / rule_link[1]).resolve(strict=True)
                marker = f"- `[{rule_id}] [hard]`"
                found = read_page(source, find=marker, max_matches=1, limit=32)
                self.assertEqual(1, len(found["matches"]))
                rule_text = source.read_text(encoding="utf-8").split(marker, 1)[1].split("\n-", 1)[0]
                expected = (marker + rule_text).rstrip()
                page = read_page(source, offset=found["matches"][0]["offset"],
                                 expect_sha256=found["sha256"], limit=len(expected))
                self.assertEqual(expected, page["text"])
                self.assertGreater(len(expected), len(found["matches"][0]["snippet"]))
