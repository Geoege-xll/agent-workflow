"""通过实际入口检查任意选中 Markdown 的可点击引用、坏锚定位和读取范围。"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PACK = Path(__file__).resolve().parents[1]


class DocumentLinksTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="document-links-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def write(self, relative, body):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def cli(self, *sources):
        args = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                str(PACK / "lib/validate_project_docs.py"), "--root", str(self.root)]
        for source in sources:
            args.extend(("--document", str(source)))
        return subprocess.run(args, cwd=self.root, text=True, capture_output=True, timeout=20)

    def test_any_source_and_references_follow_actual_relative_destinations(self):
        page = self.write("产品/详情 (旧).MD", "# 简介\n## 上线 时间\n## 上线 时间\n<a name='Stable'></a>\n")
        entry = self.write(".github/说明.md", """# 自身 标题
[同页](#自身-标题) · [重复标题](<../产品/详情 (旧).MD#上线-时间-1> "直达")
[引用][章 节] · [章节简称][] · [短引] · [源代码](../程序.py#L100)
[多行定义][路径说明] · [名字中的符号](../历史&copy.md)
> 使用[明确锚点](../产品/详情%20(旧).MD#Stable)

[章   节]: <../产品/详情 (旧).MD#上线-时间>
[章节简称]: ../产品/详情%20(旧).MD#%E4%B8%8A%E7%BA%BF-%E6%97%B6%E9%97%B4
[短引]: <../产品/详情 (旧).MD#Stable> '保持大小写'
[短引]: missing-duplicate.md
[未用]: missing-unused.md
[路径说明]:
  ../产品/详情%20(旧).MD#Stable
  "标题示例 [假链接](missing-in-title.md)"
""")
        (self.root / "程序.py").write_bytes(b"\xff")
        self.write("历史&copy.md", "# 历史\n")
        original = entry.read_bytes()
        checked = self.cli(".github/说明.md", page, entry)
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertEqual(original, entry.read_bytes())

    def test_renamed_target_and_broken_anchors_report_each_citing_file_and_line(self):
        target = self.write("移动.md", "# 标题\n")
        target.rename(self.root / "新址.md")
        self.write("上游.md", """# 起点
[文件](移动.md)
[本页](#消失)
[异页](新址.md#错)
[完整][doc] · [doc][] · [doc]

[DOC]: 移动.md
""")
        self.write("其它/README.md", "> [另一个引用](../移动.md)\n")
        result = self.cli("上游.md", "其它/README.md", "上游.md")
        self.assertEqual(1, result.returncode)
        errors = result.stderr.splitlines()
        self.assertEqual(7, len(errors), errors)
        for number, fragment in [(2, "移动.md"), (3, "#消失"), (4, "#错")]:
            self.assertTrue(any(f"上游.md:{number}:" in error and fragment in error for error in errors), errors)
        self.assertEqual(3, sum("上游.md:5:" in error and "移动.md" in error for error in errors))
        self.assertTrue(any("其它/README.md:1:" in error for error in errors))

    def test_examples_network_and_unselected_bodies_do_not_expand_the_check(self):
        self.write("README.md", """# 起点
记录 old.md、`src.py`、[普通方括号] 和 `[示例](missing.md)`。

~~~md
[围栏](missing.md)
~~~
<!-- [注释](missing.md) -->
> ```
> [引用块围栏](missing.md)
> ```

    [缩进代码](missing.md)

![插图](missing.png) · [远端](https://invalid.invalid/missing.md#no)
[下一页](无须读取.md) · [源码](证据.bin#L20) · [后续](后续.md#有效)
""")
        (self.root / "无须读取.md").write_bytes(b"\xff")
        (self.root / "证据.bin").write_bytes(b"\xff")
        self.write("后续.md", "## 有效\n[该页自己的下游](missing.md)\n")
        self.write("无关.md", "[坏引用](missing.md)\n")
        result = self.cli("README.md")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_plan_html_fragments_use_static_nodes_in_both_commands(self):
        from tests.test_plan_and_shallow_docs import PlanAndShallowDocsTest
        page = self.write("docs/模型 & 状态.html", """<main id="正常">正常</main>
<a name='Legacy'></a><article id='A&amp;B'></article>
<!-- <div id='注释'></div> --><script>const demo = '<b id="示例">';</script>
<textarea><p id="文本"></p></textarea><template><div id="未实例化"></div></template>
<span name="非锚点"></span>""")
        raw = "../模型%20%26%20状态.html"
        plan = self.write("docs/plans/流程.md", PlanAndShallowDocsTest.lifecycle() + f"""
[正常]({raw}#%E6%AD%A3%E5%B8%B8) [实体]({raw}#A%26B) [历史][状态]
[状态]: {raw}#Legacy

`[Markdown 样例]({raw}#示例)`

    [缩进示例](不存在.html#状态)
""")
        def check(option):
            return subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                                   str(PACK / "lib/validate_project_docs.py"), "--root", str(self.root),
                                   option, str(plan)], text=True, capture_output=True)
        for option in ("--document", "--plan"):
            valid = check(option)
            self.assertEqual(0, valid.returncode, valid.stderr)
        with plan.open("a", encoding="utf-8") as out:
            out.write("\n".join(f"[失效]({raw}#{key})" for key in
                                ("legacy", "示例", "注释", "文本", "未实例化", "非锚点")))
        for option in ("--document", "--plan"):
            result = check(option)
            self.assertEqual(1, result.returncode)
            self.assertEqual(6, result.stderr.count("HTML id"), result.stderr)
        page.write_bytes(b"\xff")
        for option in ("--document", "--plan"):
            self.assertIn("utf-8", check(option).stderr)

    def test_list_continuations_use_item_indent_but_code_remains_hidden(self):
        self.write("清单.md", """10. 发布步骤
    先按文档操作。

    ```md
    - [围栏里的标记](missing.md)
    ```

    当前[执行边界](#改名)。

        [额外四格是缩进代码](missing.md)

    - 子项

      [嵌套续段](#下级改名)。

          [子项内的缩进代码](missing.md)

下一段离开列表。

    [普通缩进代码](missing.md)

<pre>
- [HTML 中的列表样例](missing.md)
</pre>
""")
        result = self.cli("清单.md")
        self.assertEqual(1, result.returncode)
        errors = result.stderr.splitlines()
        self.assertEqual(2, len(errors), errors)
        self.assertIn("清单.md:8:", errors[0])
        self.assertIn("#改名", errors[0])
        self.assertIn("清单.md:14:", errors[1])
        self.assertIn("#下级改名", errors[1])

    def test_local_paths_preserve_project_node_checks_including_parent_jumps(self):
        self.write("有效.md", "# 实际\n")
        (self.root / "软链.md").symlink_to(self.root / "有效.md")
        self.write("目标.md", "# 实际\n")
        os.link(self.root / "目标.md", self.root / "硬链.md")
        self.write("README.md", "[越界](../escape.md)\n[软链](软链.md#实际)\n"
                                "[硬链](硬链.md)\n[不可遍历](有效.md/../有效.md)\n")
        checked = self.cli("README.md", "不存在.md", "../外部.md")
        self.assertEqual(1, checked.returncode)
        for number in range(1, 5):
            self.assertIn(f"README.md:{number}:", checked.stderr)
        self.assertIn("不存在.md", checked.stderr)
        self.assertIn("外部.md", checked.stderr)
