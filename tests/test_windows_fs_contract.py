"""Portable Win32 call contracts, not native filesystem acceptance."""

from __future__ import annotations

from contextlib import nullcontext
import ctypes
import hashlib
import importlib.util
from pathlib import Path, PureWindowsPath
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PACK = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("windows_fs_contract", PACK / "lib/windows_fs.py")
fs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fs)


class WindowsComponentContractTest(unittest.TestCase):
    def test_raw_absolute_and_relative_names_share_strict_validation(self):
        directory = fs.Directory.__new__(fs.Directory)
        directory.path = PureWindowsPath("C:/project")
        invalid = ("", ".", "..", "a/b", "a\\b", "a:b", "victim\0suffix", "a\n",
                   "trailing.", "trailing ", "NUL", "con.txt", "COM1.log", "LPT².txt", "a?b")
        for name in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                directory.child(name)
        for name in (item for item in invalid[1:] if item not in {"a/b", "a\\b"}):
            with self.subTest(absolute=name), self.assertRaises(ValueError):
                fs.absolute_path("C:\\project\\" + name)
        self.assertEqual(directory.child("项目 & (x).md"), PureWindowsPath("C:/project/项目 & (x).md"))

    def test_invalid_relative_open_truncate_and_delete_never_reach_win32(self):
        directory = fs.Directory.__new__(fs.Directory)
        directory.path = PureWindowsPath("C:/project")
        backend = fs._WindowsOS()
        backend._directories[123] = directory
        with patch.object(fs, "_api", side_effect=AssertionError("must reject before Win32")):
            for method in (backend.unlink, backend.stat, backend.mkdir, backend.rmdir):
                with self.subTest(method=method), self.assertRaises(ValueError):
                    method("victim\0suffix", dir_fd=123)


class WindowsAclContractTest(unittest.TestCase):
    def test_permission_copy_preserves_protected_or_inheriting_policy(self):
        for protected, expected in ((False, 0x20000004), (True, 0x80000004)):
            calls = []
            def get_info(source, kind, flags, owner, group, acl, sacl, descriptor):
                ctypes.cast(acl, ctypes.POINTER(fs.HANDLE))[0] = fs.HANDLE(42)
                ctypes.cast(descriptor, ctypes.POINTER(fs.HANDLE))[0] = fs.HANDLE(43)
                return 0
            def get_control(descriptor, control, revision):
                ctypes.cast(control, ctypes.POINTER(ctypes.c_uint16))[0] = 0x1000 if protected else 0
                return True
            api = SimpleNamespace(security=SimpleNamespace(
                GetSecurityInfo=get_info, GetSecurityDescriptorControl=get_control,
                SetSecurityInfo=lambda *args: calls.append(args) or 0),
                kernel=SimpleNamespace(LocalFree=lambda value: calls.append(("free", value))))
            with self.subTest(protected=protected), patch.object(fs, "_api", return_value=api):
                fs._copy_permissions(1, 2)
            self.assertEqual(calls[0][2], expected)
            self.assertEqual(calls[-1][0], "free")


class WindowsConditionalDeleteContractTest(unittest.TestCase):
    def run_delete(self, body=b"owned", *, identity=(7, 9), expected_body=b"owned"):
        calls = []
        remaining = [body, b""]
        def read_file(handle, buffer, length, count, overlapped):
            chunk = remaining.pop(0)
            ctypes.memmove(buffer, chunk, len(chunk))
            ctypes.cast(count, ctypes.POINTER(fs.DWORD))[0] = len(chunk)
            calls.append("read")
            return True
        info = SimpleNamespace(volume=7, index_high=0, index_low=9, size_high=0, size_low=len(body))
        api = SimpleNamespace(kernel=SimpleNamespace(
            ReadFile=read_file,
            SetFileInformationByHandle=lambda *args: calls.append("delete") or True))
        with patch.object(fs, "absolute_path", side_effect=lambda value: Path(value)), \
                patch.object(fs, "Directory", side_effect=lambda path: nullcontext()), \
                patch.object(fs, "_open_handle", return_value=123) as opened, \
                patch.object(fs, "_information", return_value=info), \
                patch.object(fs, "_api", return_value=api), \
                patch.object(fs, "_close", side_effect=lambda handle: calls.append("close")), \
                patch.object(fs, "flush_directory", side_effect=lambda path: calls.append("flush")):
            result = fs.remove_file_if_unchanged(Path("/project/file"),
                hashlib.sha256(expected_body).hexdigest(), identity)
        opened.assert_called_once_with(Path("/project/file"), fs.READ | fs.DELETE, sharing=fs.SHARE_READ)
        return result, calls

    def test_same_handle_hash_identity_and_delete_exclude_writers(self):
        result, calls = self.run_delete()
        self.assertTrue(result)
        self.assertEqual(calls, ["read", "read", "delete", "close", "flush"])

    def test_replacement_identity_or_changed_content_survives(self):
        for options in ({"identity": (7, 10)}, {"body": b"user edit"}):
            with self.subTest(options=options):
                result, calls = self.run_delete(**options)
                self.assertFalse(result)
                self.assertNotIn("delete", calls)
                self.assertNotIn("flush", calls)
                self.assertEqual(calls[-1], "close")


class WindowsRenameDurabilityContractTest(unittest.TestCase):
    def test_namespace_barrier_is_after_publication_and_failure_propagates(self):
        for fail_after in (False, True):
            events = []
            def flush(path):
                events.append("flush")
                if fail_after and "rename" in events:
                    raise OSError("durability unavailable after rename")
            info = SimpleNamespace(volume=7, index_high=0, index_low=9)
            api = SimpleNamespace(kernel=SimpleNamespace(
                SetFileInformationByHandle=lambda *args: events.append("rename") or True))
            backend = fs._WindowsOS()
            with self.subTest(fail_after=fail_after), \
                    patch.object(fs, "Directory", side_effect=lambda path: nullcontext(SimpleNamespace(handle=10))), \
                    patch.object(fs, "flush_directory", side_effect=flush), \
                    patch.object(fs, "_open_handle", return_value=20), \
                    patch.object(fs, "_information", return_value=info), \
                    patch.object(fs, "_api", return_value=api), patch.object(fs, "_close"), \
                    patch.object(backend, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG)):
                if fail_after:
                    with self.assertRaises(OSError):
                        backend._rename(Path("/project/stage"), Path("/project/runtime"), False)
                else:
                    backend._rename(Path("/project/stage"), Path("/project/runtime"), False)
            self.assertEqual(events, ["flush", "rename", "flush"])


if __name__ == "__main__":
    unittest.main()
