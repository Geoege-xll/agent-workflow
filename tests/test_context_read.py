from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib.documents import context_read


PACK = Path(__file__).resolve().parents[1]
HELPER = PACK / "lib/documents/context_read.py"


class ContextReadTest(unittest.TestCase):
    def setUp(self) -> None:
        # macOS 的 /var、/tmp 可能是系统符号链接；测试自身使用真实临时根，
        # 不为让普通用例通过而削弱生产工具对符号链接父目录的拒绝合同。
        self.temporary = tempfile.TemporaryDirectory(
            prefix="context-read-", dir=Path(tempfile.gettempdir()).resolve()
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "中文 文档.md"

    def write(self, body: bytes) -> str:
        self.path.write_bytes(body)
        return hashlib.sha256(body).hexdigest()

    def run_cli(self, *args: str, path: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(HELPER), str(path or self.path), *args],
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=10,
        )

    def test_real_package_and_cli_ignore_a_project_owned_lib_package(self) -> None:
        """项目普通 lib 包不能覆盖可信核心；同时验证 API 消费与直接 helper 的真实进程。"""
        digest = self.write("真实项目正文\n".encode())
        foreign = self.root / "lib"
        foreign.mkdir()
        sentinel = self.root / "foreign-lib-executed"
        # 若误选项目包，先留下可观察副作用再失败；仅检查 exit=0 不足以证明它未执行。
        (foreign / "__init__.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('foreign project lib executed')\n"
            "raise RuntimeError('FOREIGN_PROJECT_LIB_EXECUTED')\n", encoding="utf-8",
        )
        env = dict(os.environ, PYTHONPATH="")
        python = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8"]
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from lib.project import project_discovery; print(project_discovery.__file__)")
        commands = (
            ("package", [*python, "-c", code, str(PACK)]),
            ("direct-helper", [*python, str(HELPER), str(self.path), "--root", str(self.root)]),
        )
        for mode, command in commands:
            with self.subTest(mode=mode):
                result = subprocess.run(command, cwd=self.root, env=env, capture_output=True,
                                        text=True, encoding="utf-8", timeout=15)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse(sentinel.exists(), "项目的同名 lib 包被错误执行")
                if mode == "package":
                    self.assertEqual(str(PACK / "lib/project/project_discovery.py"), result.stdout.strip())
                else:
                    self.assertEqual(digest, json.loads(result.stdout)["sha256"])

    def test_chinese_crlf_and_long_lines_reassemble_exact_original_bytes(self) -> None:
        # 同时覆盖中文、四字节字符、CRLF、独立 CR 与跨越多页的单行。
        original = ("首行中文\r\n" + "超长🙂行" * 31 + "\r\n结尾\r终点").encode("utf-8")
        digest = self.write(original)
        offset = 0
        fragments = []
        while True:
            page = context_read.read_page(
                self.path, offset=offset, limit=7,
                expect_sha256=digest if offset else None,
            )
            self.assertEqual(digest, page["sha256"])
            self.assertEqual(offset, page["offset"])
            self.assertEqual("unicode_characters", page["position_unit"])
            self.assertEqual(len(original), page["total_bytes"])
            self.assertLessEqual(len(page["text"]), 7)
            self.assertEqual(offset + len(page["text"]), page["end_offset"])
            fragments.append(page["text"])
            if page["eof"]:
                self.assertIsNone(page["next_offset"])
                self.assertEqual(page["total_chars"], page["end_offset"])
                break
            self.assertEqual(page["end_offset"], page["next_offset"])
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        self.assertEqual(original, "".join(fragments).encode("utf-8"))

    def test_empty_file_and_explicit_eof_have_unambiguous_empty_final_page(self) -> None:
        digest = self.write(b"")
        page = context_read.read_page(self.path)
        self.assertEqual(("", 0, 0, None, True), (
            page["text"], page["offset"], page["end_offset"], page["next_offset"], page["eof"]
        ))
        self.assertEqual(digest, page["sha256"])
        digest = self.write("完成".encode("utf-8"))
        page = context_read.read_page(self.path, offset=2, expect_sha256=digest)
        self.assertEqual(("", None, True), (page["text"], page["next_offset"], page["eof"]))

    def test_invalid_positions_budgets_and_digest_are_rejected(self) -> None:
        digest = self.write("中文".encode("utf-8"))
        cases = [
            {"offset": -1}, {"offset": True}, {"offset": 1.5},
            {"limit": 0}, {"limit": -1}, {"limit": True}, {"limit": 1.5},
            {"limit": context_read.MAX_LIMIT + 1}, {"offset": 1},
            {"offset": 3, "expect_sha256": digest},
            {"expect_sha256": "A" * 64}, {"expect_sha256": "a" * 63},
            {"expect_sha256": 123},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(context_read.ContextReadError):
                context_read.read_page(self.path, **kwargs)

    def test_changed_file_cannot_be_combined_with_an_earlier_page(self) -> None:
        self.write("版本一中文正文".encode("utf-8"))
        first = context_read.read_page(self.path, limit=3)
        self.write("版本二中文正文".encode("utf-8"))
        with self.assertRaisesRegex(context_read.ContextReadError, "SHA-256 已变化"):
            context_read.read_page(self.path, offset=first["next_offset"],
                                   expect_sha256=first["sha256"])
        with self.assertRaisesRegex(context_read.ContextReadError, "SHA-256 已变化"):
            context_read.read_page(self.path, expect_sha256=first["sha256"])

    def test_mutation_during_reading_and_incomplete_reader_are_rejected(self) -> None:
        self.write(b"stable original bytes")
        safe_read = context_read.read_file

        def changed_after_read(path):
            body = safe_read(path)
            path.write_bytes(b"changed original bytes")
            return body

        with patch.object(context_read, "read_file", side_effect=changed_after_read):
            with self.assertRaisesRegex(context_read.ContextReadError, "读取期间发生变化"):
                context_read.read_page(self.path)
        # 若底层读取未返回完整字节，即使元数据没有变化也不能把前缀误报为 EOF。
        with patch.object(context_read, "read_file", return_value=b"changed"):
            with self.assertRaisesRegex(context_read.ContextReadError, "读取期间发生变化"):
                context_read.read_page(self.path)

    def test_invalid_utf8_and_oversized_input_fail_without_body_leak(self) -> None:
        for body in (b"private-body-\xff", b"x" * (4 * 1024 * 1024 + 1)):
            with self.subTest(size=len(body)):
                self.write(body)
                result = self.run_cli()
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("[ERROR]", result.stderr)
                self.assertNotIn("private-body", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_unsafe_nodes_parents_and_parent_traversal_are_rejected(self) -> None:
        self.write(b"do not reveal this body")
        link = self.root / "symlink.md"
        link.symlink_to(self.path)
        hardlink = self.root / "hardlink.md"
        os.link(self.path, hardlink)
        directory = self.root / "directory.md"
        directory.mkdir()
        fifo = self.root / "fifo.md"
        if hasattr(os, "mkfifo"):
            os.mkfifo(fifo)
        real = self.root / "real"
        real.mkdir()
        (real / "document.md").write_bytes(b"safe bytes")
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        cases = [link, hardlink, self.path, directory, alias / "document.md",
                 real / ".." / "中文 文档.md", self.root / "missing.md"]
        if fifo.exists():
            cases.append(fifo)
        for path in cases:
            with self.subTest(path=path), self.assertRaises(context_read.ContextReadError):
                context_read.read_page(path)
        # 所有拒绝操作保持原始字节与链接，不删除或“修复”外部节点。
        self.assertEqual(b"do not reveal this body", self.path.read_bytes())
        self.assertTrue(link.is_symlink())
        self.assertEqual(2, self.path.stat().st_nlink)

    def test_cli_returns_only_a_page_and_requires_bound_continuation(self) -> None:
        body = "甲乙\r\n丙丁🙂尾".encode("utf-8")
        self.write(body)
        first = self.run_cli("--limit", "3")
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual("", first.stderr)
        first_page = json.loads(first.stdout)
        self.assertEqual("甲乙\r", first_page["text"])
        second = self.run_cli("--offset", str(first_page["next_offset"]),
                              "--limit", "100", "--expect-sha256", first_page["sha256"])
        self.assertEqual(0, second.returncode, second.stderr)
        second_page = json.loads(second.stdout)
        self.assertTrue(second_page["eof"])
        self.assertEqual(body, (first_page["text"] + second_page["text"]).encode("utf-8"))
        invalid = self.run_cli("--offset", "3")
        self.assertEqual(2, invalid.returncode)
        self.assertEqual("", invalid.stdout)
        self.assertIn("expect-sha256", invalid.stderr)
        self.assertNotIn("甲乙", invalid.stderr)

    def test_reading_creates_no_cache_or_state_files(self) -> None:
        self.write(b"bounded text")
        names = sorted(self.root.iterdir())
        context_read.read_page(self.path, limit=3)
        self.assertEqual(names, sorted(self.root.iterdir()))

    def test_symbol_lookup_and_exact_line_pages_preserve_full_source(self) -> None:
        # 先定位带中文的符号，再读完整函数的行段。让函数里的单行大于字符预算，
        # 同时混用三种行尾；最后一页须恰好停在调用方之前，拼接后须保留原字节。
        selected = "def 检查():\r\n\r    return '" + "🙂" * 175 + "'\n"
        prefix, suffix = "# 上文\r", "def 调用方(): return 检查()"
        full = (prefix + selected + suffix).encode("utf-8")
        digest = self.write(full)
        found = json.loads(self.run_cli("--find", "def 检查(", "--limit", "12", "--max-matches", "2").stdout)
        self.assertEqual((2, digest), (found["matches"][0]["line"], found["sha256"]))
        offset, fragments = 0, []
        while True:
            result = self.run_cli("--lines", "2:4", "--limit", "80", "--offset", str(offset),
                                  "--expect-sha256", digest)
            self.assertEqual(0, result.returncode, result.stderr)
            page = json.loads(result.stdout)
            self.assertEqual((2, 4, len(prefix), len(prefix + selected), len(full)),
                             (page["first_line"], page["last_line"], page["lines_start_offset"],
                              page["lines_end_offset"], page["total_bytes"]))
            self.assertLessEqual(len(page["text"]), 80)
            fragments.append(page["text"])
            if page["eof"]:
                self.assertIsNone(page["next_offset"])
                break
            offset = page["next_offset"]
        self.assertEqual(selected, "".join(fragments))
        self.assertEqual(suffix, context_read.read_page(self.path, lines="5:5")["text"])
        self.assertEqual(full, self.path.read_bytes())
        self.assertEqual([self.path], list(self.root.iterdir()))

    def test_line_pages_reject_missing_lines_mixed_selectors_and_wrong_snapshot(self) -> None:
        # 入选的最后一个真实行可以是空白行；尾部换行之后没有新的源码行。
        # 缺失行号或指纹错误应返回非零、零正文，不能悄悄裁剪成“已读完”。
        digest = self.write("隐藏上文\n\n末行\r\n".encode())
        self.assertEqual("\n", context_read.read_page(self.path, lines="2:2")["text"])
        for args in (
            ("--lines", "3:4"), ("--lines", "0:1"), ("--lines", "3:2"), ("--lines", "2"),
            ("--lines", "1:1", "--find", "上文"), ("--lines", "1:1", "--section", "上文"),
            ("--lines", "2:2", "--offset", "1", "--expect-sha256", digest),
            ("--lines", "2:2", "--offset", "5"),
        ):
            with self.subTest(args=args):
                rejected = self.run_cli(*args)
                self.assertEqual((2, ""), (rejected.returncode, rejected.stdout))
                self.assertNotIn("隐藏上文", rejected.stderr)
        self.write("新版上文\n\n末行\r\n".encode())
        changed = self.run_cli("--lines", "2:2", "--expect-sha256", digest)
        self.assertEqual((2, ""), (changed.returncode, changed.stdout))
        self.assertIn("SHA-256 已变化", changed.stderr)
        self.write(b"")
        with self.assertRaisesRegex(context_read.ContextReadError, "实际文件行数"):
            context_read.read_page(self.path, lines="1:1")

    def test_section_cli_keeps_nested_text_and_never_pages_into_siblings(self) -> None:
        # 模拟长计划中很窄的当前章节，左右各放一段超过普通单页上限的历史材料。
        # 同时让围栏和 HTML 注释出现同名或上级标题，均不能参与定位。
        prefix = "# 项目\r\n" + "旧稿" * 13000 + "\r\n~~~md\n## 当期验收\n~~~\n"
        selected = ("  ## 当期验收 ##\r\n须保留完整🙂。\r### 范围\r\n"
                    "~~~md\n# 围栏内示例\n~~~\n<!--\n## 注释内示例\n-->\n"
                    "### 例外\n" + "跨页正文" * 42 + "\r\n")
        suffix = "## 下一主题\n" + "别的主题" * 8500
        digest = self.write((prefix + selected + suffix).encode())
        args = ("--section", "当期验收")
        first = self.run_cli(*args, "--limit", "31")
        self.assertEqual(0, first.returncode, first.stderr)
        page = json.loads(first.stdout)
        fragments = [page["text"]]
        self.assertEqual((len(prefix), len(prefix), len(prefix + selected), digest),
                         (page["offset"], page["section_start_offset"], page["section_end_offset"], page["sha256"]))
        while not page["eof"]:
            offset = page["next_offset"]
            result = self.run_cli(*args, "--offset", str(offset), "--expect-sha256", digest)
            self.assertEqual(0, result.returncode, result.stderr)
            page = json.loads(result.stdout)
            self.assertEqual(offset, page["offset"])
            fragments.append(page["text"])
        self.assertEqual(selected, "".join(fragments))
        self.assertEqual((len(prefix + selected), None, len(prefix + selected + suffix)),
                         (page["end_offset"], page["next_offset"], page["total_chars"]))
        # 下级标题止于下个同级标题，上级标题也会结束最后一个子节。
        child = context_read.read_page(self.path, section="例外")
        self.assertEqual(selected[selected.index("### 例外"):], child["text"])
        self.assertTrue(child["eof"])

    def test_section_refuses_ambiguous_missing_and_stale_input_without_body(self) -> None:
        prefix = "# 项目\n"
        text = prefix + "## 重名\n### 重名\n## 唯一\n正文\n## 后文\n私有内容"
        digest = self.write(text.encode())
        for args in (
            ["--section", "重名"], ["--section", "不存在"], ["--section", ""],
            ["--section", "唯一", "--find", "正文"], ["--section", "唯一", "--offset", "9"],
            ["--section", "唯一", "--offset", "1", "--expect-sha256", digest],
            ["--section", "唯一", "--offset", str(len(text)), "--expect-sha256", digest],
        ):
            with self.subTest(args=args):
                rejected = self.run_cli(*args)
                self.assertEqual(2, rejected.returncode)
                self.assertEqual("", rejected.stdout)
                self.assertNotIn("私有内容", rejected.stderr)
        # 同长度替换章节前的文字，仍会改变整文件 SHA，不能拼接旧版的续页。
        self.write(text.replace("项目", "工程").encode())
        rejected = self.run_cli("--section", "唯一", "--offset", str(text.index("正文")),
                                "--expect-sha256", digest)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("SHA-256 已变化", rejected.stderr)
        self.assertEqual("", rejected.stdout)

    def test_outline_and_heading_follow_actual_branches_without_expanding_child_bodies(self) -> None:
        # 普通项目文档可以从 H2 开始，跳过 H3。两个父节点里的同名标题可定位，
        # 标题自己的斜线不作为层级分隔符。大段历史正文、围栏和注释均不入目录。
        first = "## 研发/发布 ##\r\n"
        my_body = "本轮说明。\r\n"
        child = "#### 验收\r\n"
        expansion = child + "研发验收正文\r\n##### 日志\r\n日志内容\n"
        sample = first + my_body + expansion + "#### 附录\n" + "旧版" * 14000 + "\r"
        sample += "## 运维\n~~~md\n## 研发/发布\n~~~\n<!--\n#### 验收\n-->\n#### 验收\n运维正文\n"
        self.write(sample.encode())
        cases = (
            (["--outline"], first + "## 运维\n"),
            (["--outline", "--heading", "研发/发布"], child + "#### 附录\n"),
            (["--heading", "研发/发布"], first + my_body + child + "#### 附录\n"),
            (["--heading", "研发/发布", "--heading", "验收"], child + "研发验收正文\r\n##### 日志\r\n"),
            (["--heading", "研发/发布", "--heading", "验收", "--subtree"], expansion),
            (["--heading", "运维", "--heading", "验收"], "#### 验收\n运维正文\n"),
            (["--outline", "--heading", "运维", "--heading", "验收"], ""),
        )
        for args, expected in cases:
            with self.subTest(args=args):
                response = self.run_cli(*args)
                self.assertEqual(0, response.returncode, response.stderr)
                page = json.loads(response.stdout)
                self.assertEqual((expected, True, None), (page["text"], page["eof"], page["next_offset"]))
        # 原有按标题定位仍要求整份文件唯一，不因新入口支持分支消歧而放宽。
        self.assertEqual(2, self.run_cli("--section", "验收").returncode)
        self.write(b"ordinary file without a heading\n")
        self.assertEqual("", context_read.read_page(self.path, outline=True)["text"])
        skill = PACK / "platforms/shared/skills/xy-workflow/SKILL.md"
        # 宿主 Skill 页的平面元数据位于文件开头，目录仍应定位到正文里的标题。
        self.assertEqual("# xy-workflow\n", context_read.read_page(skill, outline=True)["text"])

    def test_navigation_masks_list_fences_and_recovers_the_next_real_heading(self) -> None:
        # 两空格续行、十号有序项、列表项首围栏和子列表共存。子项的未闭合
        # 围栏在退出该项时结束，不能吞掉父项后面的标题。短结束符不能提早闭合。
        sample = ("# 入口\r\n## 示例\r\n- 第一项\r\n\r\n"
                  "  ~~~~md\r\n  # 伪一级\r\n  ~~~\r\n  ## 伪二级\r\n  ~~~~\r\n"
                  "10. 第二项\n    ```bash\n    # 有序列表命令\n    ```\n"
                  "    - ```md\n      # 子列表代码\n"
                  "    ~~~\n    ## 父列表代码\n    ~~~\n"
                  "## 目标\n正文\n### 子项\n独立内容\n")
        self.write(sample.encode())
        self.assertEqual("# 入口\r\n", context_read.read_page(self.path, outline=True)["text"])
        self.assertEqual("## 示例\r\n## 目标\n",
                         context_read.read_page(self.path, heading=["入口"], outline=True)["text"])
        chosen = context_read.read_page(self.path, heading=["入口", "目标"])
        self.assertEqual("## 目标\n正文\n### 子项\n", chosen["text"])
        # 旧接口按唯一全局标题选择，对有复杂容器的文档仍保持原拒绝行为。
        with self.assertRaisesRegex(context_read.ContextReadError, "--find"):
            context_read.read_page(self.path, section="目标")

    def test_sparse_navigation_pages_keep_budgets_offsets_and_version(self) -> None:
        # 预算恰好到达首段末尾时，续页应跳过不可见正文；也允许从超长标题
        # 的中间续读。换行、中文和四字节字符以原文字符坐标重建。
        root, first, second = "# 根\n", "## 甲\r\n", "## 乙🙂🙂🙂🙂\r"
        own = "本节\r"
        sample = root + own + first + "须跳过的正文\n" + second + "再次跳过\r# 末\n"
        digest = self.write(sample.encode())
        for outline, expected in ((True, first + second), (False, root + own + first + second)):
            offset, collected = 0, []
            while True:
                page = context_read.read_page(
                    self.path, heading=["根"], outline=outline, offset=offset,
                    expect_sha256=digest if offset else None, limit=len(first),
                )
                self.assertLessEqual(len(page["text"]), len(first))
                self.assertEqual(digest, page["sha256"])
                collected.append(page["text"])
                if page["eof"]:
                    self.assertIsNone(page["next_offset"])
                    break
                self.assertGreater(page["next_offset"], offset)
                offset = page["next_offset"]
            self.assertEqual(expected, "".join(collected))
        start = context_read.read_page(self.path, heading=["根"], outline=True, limit=len(first))
        self.assertEqual(sample.index(second), start["next_offset"])
        with self.assertRaisesRegex(context_read.ContextReadError, "未选中"):
            context_read.read_page(self.path, heading=["根"], outline=True,
                                   offset=sample.index("须跳过"), expect_sha256=digest)
        with self.assertRaisesRegex(context_read.ContextReadError, "expect-sha256"):
            context_read.read_page(self.path, heading=["根"], outline=True, offset=start["next_offset"])
        self.write(sample.replace("本节", "更新").encode())
        with self.assertRaisesRegex(context_read.ContextReadError, "SHA-256 已变化"):
            context_read.read_page(self.path, heading=["根"], outline=True,
                                   offset=start["next_offset"], expect_sha256=digest)

    def test_navigation_fails_closed_on_ambiguity_and_mixed_selectors(self) -> None:
        # 预算只够第一页也须核对整个路径，包括末尾的重名父节点。
        self.write("# 根\n## 组\n### 唯一\n秘密正文\n## 组\n### 另一项\n".encode())
        for args in (
            ["--heading", "根", "--heading", "组", "--outline", "--limit", "1"],
            ["--heading", "根", "--heading", "组", "--heading", "唯一"],
            ["--heading", "组"], ["--heading", "根", "--find", "根"],
            ["--outline", "--lines", "1:1"], ["--outline", "--section", "根"],
            ["--outline", "--subtree", "--heading", "根"], ["--subtree"],
        ):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual((2, ""), (result.returncode, result.stdout))
                self.assertNotIn("秘密正文", result.stderr)
        for sample in ("# 根\n正文\n副标题\n===\n", "# 根\n<pre>\n# 假冒\n</pre>\n"):
            self.write(sample.encode())
            result = self.run_cli("--outline")
            self.assertEqual((2, ""), (result.returncode, result.stdout))
            self.assertIn("--find", result.stderr)

    def test_section_declines_uncertain_setext_boundaries_and_retains_literal_lookup(self) -> None:
        # 混合标题形状时，不能仅因下个 ATX 较远就把中间的 Setext 章节都带回。
        self.write("## 本轮\n正文\n另一节\n===\n其他内容\n".encode())
        for title in ("本轮", "另一节"):
            rejected = self.run_cli("--section", title)
            self.assertEqual(2, rejected.returncode, rejected.stderr)
            self.assertEqual("", rejected.stdout)
            self.assertIn("--find", rejected.stderr)
        located = context_read.read_page(self.path, find="另一节", limit=3)
        self.assertEqual("另一节", located["matches"][0]["snippet"])

    def test_section_refuses_unproven_html_and_container_boundaries(self) -> None:
        # 区内假标题不能截掉有效条款；区前或区后同名示例也不能冒充唯一正文。
        section = "## 范围\n仍然有效的验收条款\n"
        for block in (
            "<pre>\n## 示例\n</pre>", "<SCRIPT>\n## 示例\n</SCRIPT>",
            "<style>\n## 示例\n</style>", "<textarea>\n## 示例\n</textarea>",
            "<div>\n## 示例\n</div>", "<widget>\n## 示例\n</widget>",
            "<?处理\n## 示例\n?>", "<![CDATA[\n## 示例\n]]>",
            "> 嵌套引用\n> ## 示例", "- 条款\n  ## 示例",
            "- 条款\n  ~~~md\n  ## 示例\n  ~~~",
        ):
            with self.subTest(block=block):
                self.write(("## 范围\n" + block + "\n仍然有效的验收条款\n## 邻节\n").encode())
                result = self.run_cli("--section", "范围")
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("--find", result.stderr)
        for body in ("<pre>\n## 范围\n</pre>\n" + section,
                     section + "## 邻节\n<pre>\n## 范围\n</pre>\n"):
            self.write(body.encode())
            result = self.run_cli("--section", "范围")
            self.assertEqual(2, result.returncode)
            self.assertEqual("", result.stdout)
            self.assertIn("--find", result.stderr)
        # 真实受控资料常含顶层列表、导航锚点以及用围栏展示的 HTML。此时
        # Markdown 的边界确定，允许按同一份原文读完，保留全部示例和条款。
        selected = ('## 范围\n<a id="条款"></a>\n- 普通条款\n'
                    '~~~html\n<pre>\n## 示例\n</pre>\n~~~\n仍然有效的验收条款\n')
        self.write((selected + "## 邻节\n").encode())
        self.assertEqual(selected, context_read.read_page(self.path, section="范围")["text"])

    def test_section_cli_reads_real_templates_and_the_six_plan_sections(self) -> None:
        from lib.documents.plan_documents import SECTIONS

        # 从当前三个模板和既有六节计划取读真实章节，对照原文范围；既覆盖新目录，
        # 也确认旧计划仍然可以按标题直接取读。
        cases = [
            (PACK / "templates/docs/PLAN.md", "需求与验收"),
            (PACK / "templates/docs/PROJECT.md", "主题目录"),
            (PACK / "templates/docs/STANDARDS.md", "工程规范"),
            *((PACK / "docs/plans/role-skill-routing.md", title) for title in SECTIONS),
        ]
        for path, title in cases:
            with self.subTest(path=path, title=title):
                page = self.run_cli("--section", title, path=path)
                self.assertEqual(0, page.returncode, page.stderr)
                source = path.read_text(encoding="utf-8")
                start = source.index(f"## {title}\n")
                stop = source.find("\n## ", start)
                self.assertEqual(source[start:stop + 1 if stop >= 0 else len(source)],
                                 json.loads(page.stdout)["text"])

    def test_cli_find_returns_reusable_unicode_positions_and_bounded_snippets(self) -> None:
        # 长行中的元字符按字面处理。使用 CRLF、独立 CR 和 emoji 检查原文行列与展开位置。
        prefix = "甲\r\n🙂\r" + "字" * 12000
        literal = "标记[.]"
        text = prefix + literal + "后" * 200 + "\n" + literal
        digest = self.write(text.encode())
        first = self.run_cli("--find", literal, "--max-matches", "1")
        self.assertEqual(0, first.returncode, first.stderr)
        page = json.loads(first.stdout)
        self.assertNotIn("text", page)
        hit, = page["matches"]
        self.assertEqual((len(prefix), len(prefix) + len(literal), 3, 12001),
                         (hit["offset"], hit["end_offset"], hit["line"], hit["column"]))
        self.assertEqual(text[hit["offset"]:hit["snippet_end_offset"]], hit["snippet"])
        self.assertLessEqual(len(hit["snippet"]), context_read.SNIPPET_CHARS)
        self.assertFalse(page["eof"])
        self.assertEqual(text.rindex(literal), page["next_offset"])
        second = self.run_cli("--find", literal, "--offset", str(page["next_offset"]),
                              "--expect-sha256", page["sha256"])
        self.assertEqual(0, second.returncode, second.stderr)
        tail = json.loads(second.stdout)
        self.assertEqual((True, None, 4, 1), (tail["eof"], tail["next_offset"],
                         tail["matches"][0]["line"], tail["matches"][0]["column"]))
        expanded = self.run_cli("--offset", str(hit["offset"]), "--limit", str(len(literal)),
                                "--expect-sha256", digest)
        self.assertEqual(0, expanded.returncode, expanded.stderr)
        self.assertEqual(literal, json.loads(expanded.stdout)["text"])

    def test_find_budget_continuation_keeps_overlapping_and_long_matches(self) -> None:
        literal = "甲" * (context_read.SNIPPET_CHARS + 3)
        digest = self.write((literal + "甲甲").encode())
        # 预算比字面量更小，单条片段可以不完整，命中终点始终是完整的真实位置。
        for offset in range(3):
            page = context_read.read_page(self.path, find=literal, offset=offset, limit=2,
                                          expect_sha256=digest)
            hit, = page["matches"]
            self.assertEqual((offset, offset + len(literal), "甲甲", offset + 2),
                             (hit["offset"], hit["end_offset"], hit["snippet"], hit["snippet_end_offset"]))
            self.assertEqual(offset == 2, page["eof"])
            self.assertEqual(None if offset == 2 else offset + 1, page["next_offset"])
        # 无命中或空文件必须明确结束，不会把全文作为降级结果返回。
        for body in (b"", b"private unmatched text"):
            self.write(body)
            result = self.run_cli("--find", literal)
            self.assertEqual(0, result.returncode, result.stderr)
            page = json.loads(result.stdout)
            self.assertEqual(([], None, True), (page["matches"], page["next_offset"], page["eof"]))
            self.assertNotIn("private unmatched text", result.stdout)

    def test_cli_find_rejects_unsafe_sources_unbound_or_changed_offsets_and_invalid_limits(self) -> None:
        digest = self.write(b"private body")
        self.write(b"private edit")
        symlink = self.root / "alias.md"
        symlink.symlink_to(self.path)
        for path, args in [
            (symlink, ["--find", "private"]),
            (self.path, ["--find", "private", "--offset", "1"]),
            (self.path, ["--find", "private", "--offset", "1", "--expect-sha256", digest]),
            (self.path, ["--find", ""]),
            (self.path, ["--find", "x", "--max-matches", "0"]),
            (self.path, ["--find", "x", "--max-matches", str(context_read.MAX_MATCHES + 1)]),
            (self.path, ["--max-matches", "1"]),
        ]:
            with self.subTest(args=args, path=path):
                result = self.run_cli(*args, path=path)
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertNotIn("private edit", result.stderr)

    def test_find_shares_task_pack_validation_and_limits_combined_snippets(self) -> None:
        unit = "证据" + "甲" * 120
        self.write((unit * 3).encode())
        pack = self.root / "task-pack.json"
        pack.write_text('{"schema_version": 2, "task": {}}')
        budget = context_read.SNIPPET_CHARS + 3
        args = ("--task-pack", str(pack), "--root", str(self.root),
                "--find", "证据", "--limit", str(budget))
        result = self.run_cli(*args)
        self.assertEqual(0, result.returncode, result.stderr)
        page = json.loads(result.stdout)
        self.assertEqual([context_read.SNIPPET_CHARS, 3], [len(hit["snippet"]) for hit in page["matches"]])
        self.assertEqual((False, 2 * len(unit)), (page["eof"], page["next_offset"]))
        # 正文和字面量保持不变，仅替换任务包；查找必须在当前来源校验处失败。
        pack.write_text('{"schema_version": 1, "task": {}}')
        rejected = self.run_cli(*args)
        self.assertEqual(2, rejected.returncode)
        self.assertEqual("", rejected.stdout)
        self.assertIn("schema_version 2", rejected.stderr)

    def test_four_selected_entries_resume_after_one_truncated_response(self) -> None:
        # 四个同名入口各自有独立物理来源；前两份甚至字节完全相同，不能单凭 SHA 区分。
        paths = [self.root / name / "SKILL.md" for name in ("甲", "乙", "丙", "丁")]
        originals = ["同一正文", "同一正文", "丙前缀🙂\r\n丙后半部", "丁旧版"]
        for path, original in zip(paths, originals):
            path.parent.mkdir()
            path.write_bytes(original.encode())

        def fetch(path, limit, previous=None):
            args = ("--offset", str(previous["next_offset"]),
                    "--expect-sha256", previous["sha256"]) if previous else ()
            result = self.run_cli("--limit", str(limit), *args, path=path)
            self.assertEqual(0, result.returncode, result.stderr)
            return result.stdout

        confirmed = [json.loads(fetch(path, 4)) for path in paths[:3]]
        self.assertEqual(paths[:3], [Path(page["path"]) for page in confirmed])
        self.assertEqual([True, True, False], [page["eof"] for page in confirmed])
        self.assertEqual([None, None, 4], [page["next_offset"] for page in confirmed])

        # 模拟第三份的续页在到达读者前被宿主截掉，只有上一完整回包的字符位置可信。
        lost = fetch(paths[2], 100, confirmed[2])
        with self.assertRaises(json.JSONDecodeError):
            json.loads(lost[:lost.index(originals[2][-3:])])
        page = confirmed[2]
        text = page["text"]
        while not page["eof"]:
            page = json.loads(fetch(paths[2], 3, page))
            self.assertEqual(str(paths[2]), page["path"])
            self.assertEqual(len(text), page["offset"])
            self.assertEqual(confirmed[2]["sha256"], page["sha256"])
            text += page["text"]
            self.assertEqual(len(text), page["end_offset"])
        self.assertIsNone(page["next_offset"])
        self.assertEqual(originals[:3], [confirmed[0]["text"], confirmed[1]["text"], text])

        # 第四份在两页间被同长度新版替换，续页必须拒绝旧摘要；仅该文件需要重新开始。
        old = json.loads(fetch(paths[3], 1))
        paths[3].write_text("丁新版", encoding="utf-8")
        rejected = self.run_cli("--offset", str(old["next_offset"]), "--expect-sha256",
                                old["sha256"], path=paths[3])
        self.assertEqual(2, rejected.returncode)
        self.assertEqual("", rejected.stdout)
        self.assertIn("SHA-256 已变化", rejected.stderr)
        fresh = json.loads(fetch(paths[3], 10))
        self.assertEqual(("丁新版", True), (fresh["text"], fresh["eof"]))

    def test_plugin_entry_uses_physical_discovery_body_and_payload_digest(self) -> None:
        from lib import plugin_resources

        install = self.root / "plugin"
        project = self.root / "project"
        project.mkdir()
        relative = Path("skills/xy-code-standards/SKILL.md")
        entry = install / relative
        entry.parent.mkdir(parents=True)
        entry.write_bytes(b"host adapter\nshared body")
        digest = hashlib.sha256(entry.read_bytes()).hexdigest()
        # 核验与发行包一致的清单分工。共享原文、项目同名诱饵和宿主发现正文可观察地区分。
        canonical = Path("platforms/shared") / relative
        (install / canonical).parent.mkdir(parents=True)
        (install / canonical).write_bytes(b"shared body")
        (project / relative).parent.mkdir(parents=True)
        (project / relative).write_bytes(b"project decoy")
        (install / "workflow-sources.json").write_text(json.dumps({
            "schema_version": 1, "files": {canonical.as_posix(): hashlib.sha256(b"shared body").hexdigest()},
        }))
        neighbor = entry.with_name("notes.md")
        neighbor.write_bytes(b"unrelated payload")
        (install / "sources.json").write_text(json.dumps({"payload_sha256": {
            relative.as_posix(): digest,
            neighbor.relative_to(install).as_posix(): hashlib.sha256(neighbor.read_bytes()).hexdigest(),
        }}))
        # 安装根解析由专门的真实安装集成测试覆盖；此处只隔离根，实际运行分页、两份清单、
        # 文件节点与摘要校验，以免为每个拒绝分支重建整套三端包。
        with patch.dict(os.environ, {plugin_resources.PLUGIN_ENV: str(install)}), \
                patch.object(plugin_resources, "_root", return_value=install):
            page = context_read.read_page(entry, root=project)
            self.assertEqual((str(entry), digest, "host adapter\nshared body"),
                             (page["path"], page["sha256"], page["text"]))
            located = context_read.read_page(entry, root=project, find="adapter")
            self.assertEqual((str(entry), digest, 5), (located["path"], located["sha256"],
                             located["matches"][0]["offset"]))
            shared = context_read.read_page(project / canonical, root=project)
            self.assertEqual((str(install / canonical), "shared body"), (shared["path"], shared["text"]))
            unknown = entry.parent.parent / "unknown" / "SKILL.md"
            unknown.parent.mkdir()
            unknown.write_bytes(entry.read_bytes())
            for path in (unknown, neighbor):
                with self.subTest(path=path), self.assertRaises(context_read.ContextReadError):
                    context_read.read_page(path, root=project)
            entry.write_bytes(b"tampered bytes")
            with self.assertRaisesRegex(context_read.ContextReadError, "与发行载荷不一致"):
                context_read.read_page(entry, root=project)
            entry.unlink()
            entry.symlink_to(project / relative)
            with self.assertRaisesRegex(context_read.ContextReadError, "安全读取要求"):
                context_read.read_page(entry, root=project)


if __name__ == "__main__":
    unittest.main()
