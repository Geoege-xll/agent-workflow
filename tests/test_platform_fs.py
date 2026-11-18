"""Portable contract checks; native Windows behavior is tested separately."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import unittest

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))
import lib.platform_fs as platform_fs
class ExclusivePublicationTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX hard-link publication contract")
    def test_exclusive_publish_and_concurrent_target(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, target = root / "source", root / "target"
            source.write_bytes(b"owned")
            target.write_bytes(b"user")
            with self.assertRaises(FileExistsError):
                platform_fs.publish_exclusive(source, target)
            self.assertEqual(source.read_bytes(), b"owned")
            self.assertEqual(target.read_bytes(), b"user")
            target.unlink()
            platform_fs.publish_exclusive(source, target)
            self.assertFalse(source.exists())
            self.assertEqual(target.read_bytes(), b"owned")
            self.assertEqual(target.stat().st_nlink, 1)
