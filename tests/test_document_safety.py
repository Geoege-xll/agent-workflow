"""通用文档读取边界与计划 HTML 退役的负控，不依赖 Node 或旧渲染器。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lib.documents import safe_documents as safety
from plugins import source_pack


PACK = Path(__file__).resolve().parents[1]


class DocumentSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="awf-document-safety-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "plan.md"
        self.path.write_bytes("# 中文原稿\r\n".encode("utf-8"))

    def test_snapshot_preserves_bytes_and_fixed_identity(self) -> None:
        body, identity = safety.snapshot(self.path)
        self.assertEqual(self.path.read_bytes(), body)
        self.assertEqual(safety.identity(self.path.lstat()), identity)
        self.assertEqual(hashlib.sha256(body).hexdigest(), safety.digest(body))
        missing = self.root / "missing.md"
        self.assertEqual((None, None), safety.snapshot(missing, required=False))
        with self.assertRaisesRegex(safety.DocumentSafetyError, "文件不存在"):
            safety.snapshot(missing)

    def test_file_types_and_linked_ancestors_are_rejected(self) -> None:
        original = self.path.read_bytes()
        other = self.root / "original.md"
        other.write_bytes(original)
        for kind in ("symlink", "hardlink", "fifo", "directory", "invalid_utf8"):
            with self.subTest(kind=kind):
                self.path.unlink()
                if kind == "symlink":
                    self.path.symlink_to(other)
                elif kind == "hardlink":
                    os.link(other, self.path)
                elif kind == "fifo":
                    os.mkfifo(self.path)
                elif kind == "directory":
                    self.path.mkdir()
                else:
                    self.path.write_bytes(b"\xff")
                try:
                    with self.assertRaises((ValueError, OSError)):
                        safety.snapshot(self.path)
                finally:
                    if kind == "directory":
                        self.path.rmdir()
                    else:
                        self.path.unlink()
                    self.path.write_bytes(original)
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            safety.snapshot(alias / "absent.md", required=False)

    def test_modification_and_replacement_during_read_are_rejected(self) -> None:
        read_file = safety.read_file
        for replace in (False, True):
            def changing_read(path: Path) -> bytes:
                body = read_file(path)
                if replace:
                    replacement = path.with_suffix(".new")
                    replacement.write_bytes(body)
                    replacement.replace(path)
                else:
                    path.write_bytes(body + b"changed")
                return body

            with self.subTest(replace=replace), mock.patch.object(safety, "read_file", changing_read):
                with self.assertRaisesRegex(safety.DocumentSafetyError, "读取期间文件变化"):
                    safety.snapshot(self.path)

    def test_relative_paths_have_one_canonical_spelling(self) -> None:
        self.assertEqual(Path("custom/plans/需求.md"), safety.normalized_relative("custom/plans/需求.md"))
        for raw in ("", ".", "./plan.md", "a//plan.md", "a/../plan.md", "/plan.md", "a\\plan.md", "a\0.md"):
            with self.subTest(raw=raw), self.assertRaises(safety.DocumentSafetyError):
                safety.normalized_relative(raw)

    def test_retired_generator_has_no_source_vendor_or_helper_entry(self) -> None:
        self.assertFalse((PACK / "lib/documents/requirement_html.py").exists())
        self.assertFalse((PACK / "lib/vendor/answer-me-with-html").exists())
        self.assertNotIn("lib/documents/requirement_html.py", source_pack.HELPERS)
        # 历史页面与原型仍然属于资料，不以生成器退役为由删除实际内容。
        self.assertTrue(any((PACK / "docs/plans").glob("*.html")))
        self.assertTrue((PACK / "templates/prototype/page.html").is_file())
        self.assertTrue((PACK / "lib/documents/prototype_navigation.py").is_file())
