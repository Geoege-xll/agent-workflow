"""定向验证文档查询的真实命令入口、Markdown 来源定位与只读边界。"""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lib.documents import query_relations as relations


PACK = Path(__file__).resolve().parents[1]


class DocumentRelationsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="document-relations-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.docs = {"project": "docs/atlas.md", "standards": "docs/rules.md",
                     "standards_root": "docs/rules", "plans": "docs/topics"}
        self.adapter = self.write("project.yaml", "docs:\n" + "".join(
            f"  {key}: {value}\n" for key, value in self.docs.items()))
        self.topic = self.write("docs/topics/order.md",
                                "# 订单\n- 主题 ID：order\n- 阶段：active\n- 模块：订单\n"
                                "- 任务等级：Light\n- 已验收版本：none\n\n## 目标与范围\n"
                                "遵循[金额精度](../rules/%E9%87%91%E9%A2%9D.md#精度)。\n"
                                "[交互](../rules/prototype/pay.html#pay)。\n"
                                "决定见[原文](<../decisions/order (v2).md> \"确定依据\")。\n")
        self.standard = self.write("docs/rules/金额.md", "# 金额\n\n## 精度\n")
        self.write("docs/rules/prototype/pay.html", "页面内容不作为查询来源")
        self.write("docs/decisions/order (v2).md", "决定来源\n")
        self.write("docs/atlas.md", "## 主题目录\n- [订购](topics/order.md)\n")
        self.write("docs/rules.md", "# 规范\n- [金额](rules/金额.md)\n")
        self.history = self.write("docs/topics/draft.md", "# 旧稿\n- [金额](../rules/金额.md)\n")

    def write(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def cli(self, target, *options):
        result = subprocess.run(
            ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
             str(PACK / "lib/validate_project_docs.py"), "--root", str(self.root),
             "--adapter", "project.yaml", "--relations", str(target), *map(str, options)],
            cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_cli_returns_index_navigation_and_citing_topic_from_actual_adapter(self):
        report = self.cli(self.standard)
        self.assertEqual("indexed", report["scope"])
        self.assertFalse(report["scope_truncated"] or report["results_truncated"])
        self.assertNotIn("docs/topics/draft.md", report["sources_read"])
        self.assertNotIn("docs/decisions/order (v2).md", report["sources_read"])
        self.assertEqual([("reference", "docs/topics/order.md", "目标与范围", 9, "topic"),
                          ("navigation", "docs/rules.md", "规范", 2, "standards_index")],
                         [(row["kind"], row["source"], row["section"], row["line"], row["source_kind"])
                          for row in report["relations"]])
        self.assertEqual({"incoming"}, {row["direction"] for row in report["relations"]})
        self.assertEqual("精度", report["relations"][0]["fragment"])

    def test_links_to_prototype_and_decision_avoid_recursive_body_reads(self):
        # HTML 即便不是 UTF-8，作为已存在的链接目的地也不应该被内容读取器打开。
        prototype = self.root / "docs/rules/prototype/pay.html"
        prototype.write_bytes(b"\xff")
        report = self.cli(self.topic, "--source", self.topic)
        self.assertEqual([("standard_file", "docs/rules/金额.md"), ("prototype", "docs/rules/prototype/pay.html"),
                          ("document", "docs/decisions/order (v2).md")],
                         [(item["target_kind"], item["target"]) for item in report["relations"]])
        self.assertEqual(["docs/topics/order.md"], report["sources_read"])
        reverse = self.cli(prototype, "--source", self.topic)
        self.assertEqual("pay", reverse["relations"][0]["fragment"])
        history = self.cli(self.standard, "--source", self.history)
        self.assertEqual(["historical_plan"], [row["source_kind"] for row in history["relations"]])

    def test_fenced_commented_inline_escaped_and_unsafe_links_do_not_become_evidence(self):
        line = "[示例](../rules/金额.md)"
        fake = self.write("docs/topics/examples.md", "\n".join((
            "# 例子", "```", line, "```", "<!--", line, "-->", f"演示 `{line}`。",
            "段落开始 ``跨行代码", line, "到此为止``", "", "    " + line, "> " + line,
            "\\" + line, "!" + line, "<pre>", line, "</pre>", "[危险](../../../../金额.md)",
            "[转义](%2fetc/passwd)", "[错码](%FF.md)", "[缺失](不存在.md)",
            "[外部](https://example.org/金额.md)", "[片段](#精度)", f"真实 {line}。")))
        (self.root / "docs/topics/软链.md").symlink_to(self.standard)
        with fake.open("a", encoding="utf-8") as stream:
            stream.write(f'\n[软链](软链.md)\nHTML 属性 <i title="{line}">。\n'
                         f'正文 <code>{line}</code> 结束。\n'
                         '[无效父目录](../rules/金额.md/../金额.md)\n'
                         f'- ```md\n  {line}\n  ```\n\n[实际依据](../rules/金额.md)\n')
        result = self.cli(self.standard, "--source", fake)
        self.assertEqual([(26, "示例"), (35, "实际依据")],
                         [(r["line"], r["label"]) for r in result["relations"]])
        self.assertGreaterEqual(result["unresolved_links"], 3)

    def test_explicit_selected_paths_and_budgets_are_enforced(self):
        linked = self.root / "docs/topics/linked.md"
        linked.symlink_to(self.history)
        for target in (linked, self.root.parent, self.root / "docs", self.root / "../secret.md"):
            with self.subTest(target=target), self.assertRaises((OSError, ValueError)):
                relations.query_relations(self.root, self.docs, target, [], 4)
        for limit in (0, 101):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "limit"):
                relations.query_relations(self.root, self.docs, self.topic, [], limit)
        shown = self.cli(self.standard, "--limit", 1)
        self.assertEqual(1, len(shown["relations"]))
        self.assertEqual("topic", shown["relations"][0]["source_kind"])
        self.assertTrue(shown["results_truncated"])
        with patch.object(relations, "MAX_SOURCES", 3):
            partial = relations.query_relations(self.root, self.docs, self.standard, [], 10)
        self.assertTrue(partial["scope_truncated"])
        self.assertNotIn("docs/topics/order.md", partial["sources_read"])


if __name__ == "__main__":
    unittest.main()
