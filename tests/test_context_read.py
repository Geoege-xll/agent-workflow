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

from lib import context_read


PACK = Path(__file__).resolve().parents[1]
HELPER = PACK / "lib/context_read.py"


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

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(HELPER), str(self.path), *args],
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=10,
        )

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


if __name__ == "__main__":
    unittest.main()
