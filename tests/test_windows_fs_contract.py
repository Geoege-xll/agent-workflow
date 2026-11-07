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




    def test_absolute_rename_buffer_uses_null_root_and_utf16_byte_length(self):
        target = Path("/project/目标🙂")
        encoded = str(target).encode("utf-16-le")
        captured = []
        def rename(handle, kind, buffer, size):
            data = fs._RenameInfo.from_buffer(buffer)
            captured.append((kind, data.flags, data.root, data.length,
                             ctypes.string_at(ctypes.addressof(buffer) + fs._RenameInfo.name.offset,
                                              data.length + 2), size))
            return True
        api = SimpleNamespace(kernel=SimpleNamespace(SetFileInformationByHandle=rename))
        backend = fs._WindowsOS()
        with patch.object(fs, "Directory", side_effect=lambda p: nullcontext(SimpleNamespace(handle=10))), \
                patch.object(fs, "flush_directory"), patch.object(fs, "_open_handle", return_value=20), \
                patch.object(fs, "_information", return_value=SimpleNamespace(volume=7,index_high=0,index_low=9)), \
                patch.object(fs, "_api", return_value=api), patch.object(fs, "_close"), \
                patch.object(backend, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG)):
            backend._rename(Path("/project/stage"), target, False)
        self.assertEqual(captured[0][:4], (3, 0, None, len(encoded)))
        self.assertEqual(captured[0][4], encoded + b"\0\0")
        self.assertGreaterEqual(captured[0][5], fs._RenameInfo.name.offset + len(encoded) + 2)



class WindowsSymlinkReparseContractTest(unittest.TestCase):
    def payload(self, substitute=r"\??\C:\core\xy-workflow", shown=r"C:\core\xy-workflow",
                *, tag=0xA000000C, flags=0):
        import struct
        substitute, shown = substitute.encode("utf-16-le"), shown.encode("utf-16-le")
        return struct.pack("<IHHHHHHI", tag, 12 + len(substitute) + len(shown), 0,
                           0, len(substitute), len(substitute), len(shown), flags) + substitute + shown

    def test_real_substitute_target_is_authoritative_and_empty_display_is_allowed(self):
        self.assertEqual(fs._decode_symlink_reparse(self.payload()), r"C:\core\xy-workflow")
        self.assertEqual(fs._decode_symlink_reparse(self.payload(shown="")), r"C:\core\xy-workflow")

    def test_other_tags_relative_targets_aliases_and_malformed_bounds_are_rejected(self):
        import struct
        odd = bytearray(self.payload())
        struct.pack_into("<H", odd, 8, 1)
        invalid = [self.payload(tag=0xA0000003), self.payload(flags=1),
                   self.payload(shown=r"C:\other"), self.payload(substitute=r"\??\UNC\server\share"),
                   self.payload(substitute=r"\??\C:\core\..\outside"), bytes(odd), self.payload()[:19],
                   self.payload()[:-1]]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                fs._decode_symlink_reparse(data)


class WindowsMkdirExistingContractTest(unittest.TestCase):
    """只验证无变更分支与原API顺序；普通用户NTFS结果由native-central另验。"""

    def test_existing_nodes_raise_eexist_before_any_flush_or_write(self):
        import errno
        for mode in (stat.S_IFDIR | 0o700, stat.S_IFREG | 0o600, stat.S_IFLNK | 0o777):
            with self.subTest(mode=mode):
                backend = fs._WindowsOS()
                path = PureWindowsPath("C:/existing")
                with patch.object(backend, "_path", return_value=path), \
                        patch.object(fs, "Directory", return_value=nullcontext()), \
                        patch.object(backend, "stat", return_value=SimpleNamespace(st_mode=mode)) as lookup, \
                        patch.object(fs, "flush_directory", side_effect=PermissionError("no volume-root write")) as flush, \
                        patch.object(fs, "_api", side_effect=AssertionError("no create API for existing node")) as api, \
                        patch.object(fs, "private_security", side_effect=AssertionError("no ACL writes")) as security:
                    with self.assertRaises(FileExistsError) as caught:
                        backend.mkdir(path, 0o700)
                self.assertEqual(caught.exception.errno, errno.EEXIST)
                lookup.assert_called_once_with(path, follow_symlinks=False)
                flush.assert_not_called()
                api.assert_not_called()
                security.assert_not_called()

    def test_missing_directory_keeps_parent_create_acl_and_both_flushes(self):
        for mode in (0o700, 0o755):
            with self.subTest(mode=mode):
                calls = []
                backend = fs._WindowsOS()
                path = PureWindowsPath("C:/owned/new")
                def missing(*args, **kwargs):
                    calls.append("lookup-no-follow")
                    raise FileNotFoundError()
                def create(name, security):
                    calls.append("create-private" if security is not None else "create")
                    self.assertEqual(name, str(path))
                    return 1
                api = SimpleNamespace(kernel=SimpleNamespace(CreateDirectoryW=create))
                with patch.object(backend, "_path", return_value=path), \
                        patch.object(fs, "Directory", return_value=nullcontext()), \
                        patch.object(backend, "stat", side_effect=missing), \
                        patch.object(fs, "flush_directory", side_effect=lambda item: calls.append(("flush", item))), \
                        patch.object(fs, "_api", return_value=api), \
                        patch.object(fs, "private_security", return_value=nullcontext(42)), \
                        patch.object(fs, "assert_private", side_effect=lambda item: calls.append(("acl", item))):
                    backend.mkdir(path, mode)
                expected = ["lookup-no-follow", ("flush", path.parent),
                            "create-private" if mode == 0o700 else "create"]
                if mode == 0o700:
                    expected.append(("acl", path))
                self.assertEqual(calls, [*expected, ("flush", path), ("flush", path.parent)])

    def test_missing_directory_parent_flush_failure_cannot_create(self):
        backend = fs._WindowsOS()
        path = PureWindowsPath("C:/owned/new")
        failure = PermissionError("fixture parent flush refused")
        with patch.object(backend, "_path", return_value=path), \
                patch.object(fs, "Directory", return_value=nullcontext()), \
                patch.object(backend, "stat", side_effect=FileNotFoundError()), \
                patch.object(fs, "flush_directory", side_effect=failure), \
                patch.object(fs, "_api", side_effect=AssertionError("must not create after failed flush")) as api:
            with self.assertRaises(PermissionError) as caught:
                backend.mkdir(path, 0o700)
        self.assertIs(caught.exception, failure)
        api.assert_not_called()

    def test_racing_creation_preserves_exclusive_api_failure(self):
        backend = fs._WindowsOS()
        path = PureWindowsPath("C:/owned/new")
        collision = FileExistsError("fixture concurrent creator")
        calls = []
        api = SimpleNamespace(kernel=SimpleNamespace(CreateDirectoryW=lambda *args: 0))
        def check(result, path=None):
            if not result:
                raise collision
            return result
        with patch.object(backend, "_path", return_value=path), \
                patch.object(fs, "Directory", return_value=nullcontext()), \
                patch.object(backend, "stat", side_effect=FileNotFoundError()), \
                patch.object(fs, "flush_directory", side_effect=lambda item: calls.append(item)), \
                patch.object(fs, "_api", return_value=api), patch.object(fs, "_check", side_effect=check), \
                patch.object(fs, "assert_private", side_effect=AssertionError("cannot own concurrent directory")):
            with self.assertRaises(FileExistsError) as caught:
                backend.mkdir(path, 0o755)
        self.assertIs(caught.exception, collision)
        self.assertEqual(calls, [path.parent])


if __name__ == "__main__":
    unittest.main()
