"""Portable Win32 call contracts, not native filesystem acceptance."""

from __future__ import annotations

from contextlib import nullcontext
import ctypes
import ast
import hashlib
import importlib.util
from pathlib import Path, PureWindowsPath
import stat
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch, Mock


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
    def test_private_restriction_is_idempotent_only_for_complete_policy(self):
        """真实纯策略决定幂等路径；调用替身只证明写入/后置检查，不冒充原生 ACL。"""
        user = bytes.fromhex("010100000000000515000000")
        system = bytes.fromhex("010100000000000512000000")
        def policy(*, protected=True, rights=0x1F01FF, extra=False, owner=user):
            sids = (user, system, user) if extra else (user, system)
            entries = b"".join(bytes((0, 3)) + (8 + len(sid)).to_bytes(2, "little")
                               + rights.to_bytes(4, "little") + sid for sid in sids)
            acl = (bytes((2, 0)) + (8 + len(entries)).to_bytes(2, "little")
                   + len(sids).to_bytes(2, "little") + b"\0\0" + entries)
            return SimpleNamespace(owner=owner, control=0x1004 if protected else 4, acl_bytes=acl)
        private = policy()
        with patch.object(fs, "current_sid", return_value="user"), \
                patch.object(fs, "_sid_bytes", return_value=user):
            # 已满足全部 owner/protected/精确 ACE 条件时，不应生成新 SD 或
            # 调权限写 API。纯判定未被替换，且前像必须从同一个 handle 取得。
            inspected = Mock(side_effect=lambda handle: nullcontext(private))
            with patch.object(fs, "_security_policy", inspected), \
                    patch.object(fs, "private_security", side_effect=AssertionError("verified policy must not be rewritten")), \
                    patch.object(fs, "_api", side_effect=AssertionError("verified policy must not reach a write API")):
                fs.restrict_handle(123)
            inspected.assert_called_once_with(123)
            for label, before in (("unprotected", policy(protected=False)),
                                  ("extra-ace", policy(extra=True)), ("insufficient-rights", policy(rights=0x120089))):
                for repaired in (True, False):
                    with self.subTest(policy=label, repaired=repaired):
                        inspected = Mock(side_effect=lambda handle, values=iter((before, private if repaired else before)):
                                         nullcontext(next(values)))
                        written = Mock(return_value=0)
                        api = SimpleNamespace(security=SimpleNamespace(SetSecurityInfo=written))
                        with patch.object(fs, "_security_policy", inspected), \
                                patch.object(fs, "private_security", return_value=nullcontext(77)), \
                                patch.object(fs, "_dacl", return_value=88), patch.object(fs, "_api", return_value=api):
                            if repaired:
                                fs.restrict_handle(123)
                            else:
                                with self.assertRaisesRegex(ValueError, "postcondition"):
                                    fs.restrict_handle(123)
                        written.assert_called_once_with(123, 1, 0x80000004, None, None, 88, None)
                        self.assertEqual([((123,), {}), ((123,), {})], inspected.call_args_list)
            # 即使请求私有，未知 owner 仍须在任何权限写入前拒绝。
            with patch.object(fs, "_security_policy", return_value=nullcontext(policy(owner=b"foreign"))), \
                    patch.object(fs, "private_security", side_effect=AssertionError("foreign owner must not be mutated")), \
                    self.assertRaisesRegex(ValueError, "foreign owner"):
                fs.restrict_handle(123)

    def test_private_owner_assignment_only_accepts_current_user_or_elevated_default_admin(self):
        sids = {"user": b"user", "S-1-5-32-544": b"admins"}
        with patch.object(fs, "current_sid", return_value="user"), \
                patch.object(fs, "_sid_bytes", side_effect=sids.__getitem__):
            with patch.object(fs, "_token_elevated", side_effect=AssertionError("user owner needs no elevation query")):
                self.assertFalse(fs._private_owner_action(SimpleNamespace(owner=b"user")))
            for elevated in (False, True):
                with self.subTest(elevated=elevated), patch.object(fs, "_token_elevated", return_value=elevated):
                    if elevated:
                        self.assertTrue(fs._private_owner_action(SimpleNamespace(owner=b"admins")))
                    else:
                        with self.assertRaises(ValueError):
                            fs._private_owner_action(SimpleNamespace(owner=b"admins"))
            with patch.object(fs, "_token_elevated", return_value=True), self.assertRaises(ValueError):
                fs._private_owner_action(SimpleNamespace(owner=b"foreign"))

    def test_permission_copy_preserves_protected_or_inheriting_policy(self):
        for protected, expected in ((False, 0x20000004), (True, 0x80000004)):
            calls = []
            api = SimpleNamespace(security=SimpleNamespace(
                SetSecurityInfo=lambda *args: calls.append(args) or 0))
            policy = SimpleNamespace(control=0x1000 if protected else 0, acl=42, dacl_key=b"same")
            with self.subTest(protected=protected), patch.object(fs, "_api", return_value=api), \
                    patch.object(fs, "_security_policy", side_effect=lambda handle: nullcontext(policy)):
                fs._copy_permissions(1, 2)
            self.assertEqual(calls[0][2], expected)

    def test_permission_copy_refuses_stage_parent_inheritance_changes(self):
        policies = [SimpleNamespace(control=0, acl=42, dacl_key=b"target"),
                    SimpleNamespace(dacl_key=b"stage-parent"), SimpleNamespace(dacl_key=b"target")]
        api = SimpleNamespace(security=SimpleNamespace(SetSecurityInfo=lambda *args: 0))
        with patch.object(fs, "_api", return_value=api), \
                patch.object(fs, "_security_policy", side_effect=lambda handle: nullcontext(policies.pop(0))), \
                self.assertRaisesRegex(ValueError, "inheritance"):
            fs._copy_permissions(1, 2)

    def test_security_fingerprint_ignores_unused_acl_tail_but_keeps_order_owner_and_control(self):
        owner = bytes.fromhex("010100000000000512000000")
        other = bytes.fromhex("010100000000000513000000")
        def ace(sid):
            return b"\0\0" + (8 + len(sid)).to_bytes(2, "little") + (0x1F01FF).to_bytes(4, "little") + sid
        def acl(entries, tail=b""):
            data = b"".join(entries) + tail
            return b"\2\0" + (8 + len(data)).to_bytes(2, "little") + len(entries).to_bytes(2, "little") + b"\0\0" + data
        before = fs._canonical_security(owner, 0x1004, acl([ace(owner), ace(other)]))
        self.assertEqual(before, fs._canonical_security(owner, 0x1004, acl([ace(owner), ace(other)], b"padding!")))
        for changed in (fs._canonical_security(other, 0x1004, acl([ace(owner), ace(other)])),
                        fs._canonical_security(owner, 4, acl([ace(owner), ace(other)])),
                        fs._canonical_security(owner, 0x1004, acl([ace(other), ace(owner)]))):
            self.assertNotEqual(before, changed)

    def test_change_time_remains_real_and_acl_is_not_encoded_into_mode_or_time(self):
        info = fs._Info()
        info.links, info.attributes, info.created.low, info.modified.low = 1, 0, 11, 22
        basic = fs._BasicInfo()
        basic.changed = fs._EPOCH + 123
        regular = fs._stat_info(info, basic)
        private = fs._stat_info(info, basic, private=True)
        self.assertEqual(regular.st_ctime_ns, 12300)
        self.assertEqual(private.st_ctime_ns, regular.st_ctime_ns)
        self.assertEqual(stat.S_IMODE(regular.st_mode), 0o666)
        self.assertEqual(stat.S_IMODE(private.st_mode), 0o600)

    def test_mode_projection_is_explicit_and_readonly_requests_refuse(self):
        self.assertEqual(fs.project_mode(0o644), 0o666)
        self.assertEqual(fs.project_mode(0o600), 0o600)
        self.assertEqual(fs.project_mode(0o755, directory=True), 0o777)
        self.assertEqual(fs.project_mode(0o700, directory=True), 0o700)
        with self.assertRaises(ValueError):
            fs.project_mode(0o400)


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
            def final_path(handle, buffer, size, flags):
                buffer.value = "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\project"
                return len(buffer.value)
            info = SimpleNamespace(volume=7, index_high=0, index_low=9, links=1, attributes=0)
            api = SimpleNamespace(kernel=SimpleNamespace(
                SetFileInformationByHandle=lambda *args: events.append("rename") or True,
                GetFinalPathNameByHandleW=final_path, CreateFileW=lambda *args: 21))
            backend = fs._WindowsOS()
            with self.subTest(fail_after=fail_after), \
                    patch.object(fs, "Directory", side_effect=lambda path: nullcontext(SimpleNamespace(
                        handle=10, child=lambda name: Path("/project") / name))), \
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


class WindowsRenameAbiContractTest(unittest.TestCase):
    GUID_PARENT = "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\real\\父目录"

    def api(self, *, final_path=None, actual=None):
        captured = []
        def get_final(handle, buffer, size, flags):
            self.assertEqual((handle, flags), (456, 1))
            buffer.value = final_path if final_path is not None else self.GUID_PARENT
            return len(buffer.value)
        def rename(handle, kind, buffer, length):
            value = fs._RenameInfo.from_buffer(buffer)
            start = fs._RenameInfo.name.offset
            raw = bytes(buffer)
            captured.append((handle, kind, value.flags, value.root, value.length,
                             raw[start:start + value.length], raw[start + value.length:start + value.length + 2], length))
            return True
        kernel = SimpleNamespace(GetFinalPathNameByHandleW=get_final, SetFileInformationByHandle=Mock(side_effect=rename),
                                 CreateFileW=Mock(return_value=789))
        before = SimpleNamespace(volume=7, index_high=0, index_low=9, links=1, attributes=0)
        after = actual if actual is not None else before
        return SimpleNamespace(kernel=kernel), captured, [before, after]

    def test_x64_payload_uses_null_root_handle_guid_absolute_name_and_explicit_utf16_nul(self):
        self.assertEqual((ctypes.sizeof(fs.HANDLE), ctypes.sizeof(fs._RenameInfo),
                          fs._RenameInfo.root.offset, fs._RenameInfo.length.offset, fs._RenameInfo.name.offset),
                         (8, 24, 8, 16, 20))
        name = "新🙂.md"
        destination = SimpleNamespace(handle=456, child=lambda leaf: PureWindowsPath("Z:/mutable-alias") / leaf)
        target = self.GUID_PARENT + "\\" + name
        encoded = target.encode("utf-16-le")
        for replacing in (False, True):
            api, captured, information = self.api()
            with self.subTest(replacing=replacing), patch.object(fs, "_api", return_value=api), \
                    patch.object(fs, "_information", side_effect=information), patch.object(fs, "_close") as close:
                fs._rename_handle(123, destination, name, replace=replacing)
            self.assertEqual(captured[0][:7], (123, 3, int(replacing), None, len(encoded), encoded, b"\0\0"))
            self.assertGreaterEqual(captured[0][7], ctypes.sizeof(fs._RenameInfo) + len(encoded) + 2)
            api.kernel.CreateFileW.assert_called_once_with(target, 0x80,
                fs.SHARE_READ | fs.SHARE_WRITE | fs.SHARE_DELETE, None, 3,
                fs.BACKUP_SEMANTICS | fs.OPEN_REPARSE_POINT, None)
            close.assert_called_once_with(789)

    def test_unsupported_final_path_never_falls_back_to_cwd_or_drive_alias(self):
        destination = SimpleNamespace(handle=456)
        for final_path in ("C:\\project", "\\\\?\\UNC\\server\\project"):
            api, _, _ = self.api(final_path=final_path)
            with self.subTest(final_path=final_path), patch.object(fs, "_api", return_value=api), \
                    self.assertRaisesRegex(ValueError, "local volume GUID"):
                fs._rename_handle(123, destination, "target")
            api.kernel.SetFileInformationByHandle.assert_not_called()
            api.kernel.CreateFileW.assert_not_called()

    def test_post_rename_identity_mismatch_propagates_and_only_closes_verification_handle(self):
        actual = SimpleNamespace(volume=7, index_high=0, index_low=10, links=1, attributes=0)
        api, _, information = self.api(actual=actual)
        destination = SimpleNamespace(handle=456, child=lambda name: PureWindowsPath("Z:/alias") / name)
        with patch.object(fs, "_api", return_value=api), patch.object(fs, "_information", side_effect=information), \
                patch.object(fs, "_close") as close, self.assertRaisesRegex(ValueError, "identity"):
            fs._rename_handle(123, destination, "target")
        close.assert_called_once_with(789)


class WindowsSnapshotContractTest(unittest.TestCase):
    def test_acl_change_is_detected_even_when_all_seven_stat_scalars_are_identical(self):
        identity = (7, 9, stat.S_IFREG | 0o666, 1, 4, 11, 12)
        with patch.object(fs, "_metadata", side_effect=[(identity, "a" * 64), (identity, "b" * 64)]), \
                patch.object(fs, "_read_handle", return_value=b"same"), \
                self.assertRaisesRegex(ValueError, "changed"):
            fs._opened_snapshot(123, max_bytes=4)

    def test_invalid_budget_never_reaches_native_io(self):
        with patch.object(fs, "_api", side_effect=AssertionError("must reject before native I/O")):
            for limit in (0, -1, True, 8 * 1024 * 1024 + 1):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    fs.node_snapshot(123, "file", max_bytes=limit)

    def test_bootstrap_source_is_one_closed_stdlib_function(self):
        source = fs.bootstrap_reader_source()
        tree = ast.parse(source)
        self.assertEqual(len(tree.body), 1)
        self.assertIsInstance(tree.body[0], ast.FunctionDef)
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertEqual({node.module for node in imports if isinstance(node, ast.ImportFrom)}, {"pathlib"})
        self.assertEqual({alias.name for node in imports if isinstance(node, ast.Import) for alias in node.names},
                         {"ctypes", "os"})
        namespace = {}
        exec(compile(source, "<embedded-trusted-reader>", "exec"), namespace)
        # 本检查只证明闭包独立可装载；真正原生读成功由 native 节点单独执行。
        with patch.object(fs._os, "name", "posix"), self.assertRaisesRegex(OSError, "native Windows"):
            namespace["read_initial_regular"]("C:/fixture")

    def test_conditional_move_never_renames_a_changed_snapshot(self):
        expected = {"kind": "file", "payload": b"same", "mode": 0o666,
                    "identity": (7, 9, stat.S_IFREG | 0o666, 1, 4, 11, 12), "security": "a" * 64}
        actual = {**expected, "security": "b" * 64}
        backend = fs.secure_os
        with patch.object(backend, "_path", side_effect=lambda name, descriptor: Path("/project") / name), \
                patch.object(fs, "Directory", side_effect=lambda path: nullcontext(SimpleNamespace(handle=10))), \
                patch.object(fs, "flush_directory"), patch.object(fs, "_open_handle", return_value=123), \
                patch.object(fs, "_opened_snapshot", return_value=actual), patch.object(fs, "_close"), \
                patch.object(fs, "_rename_handle") as rename, self.assertRaisesRegex(ValueError, "changed"):
            fs.move_regular("file", "backup", src_dir_fd=1, dst_dir_fd=2, expected=expected)
        rename.assert_not_called()


class WindowsSkillReparseContractTest(unittest.TestCase):
    def reparse(self, *, tag=0xA000000C, flags=0):
        target = "C:\\runtimes\\" + "a" * 64 + "\\core\\platforms\\shared\\skills\\xy-workflow"
        substitute, display = ("\\??\\" + target).encode("utf-16-le"), target.encode("utf-16-le")
        names = substitute + display
        body = (b"\0\0" + len(substitute).to_bytes(2, "little") + len(substitute).to_bytes(2, "little")
                + len(display).to_bytes(2, "little") + flags.to_bytes(4, "little") + names)
        return tag.to_bytes(4, "little") + len(body).to_bytes(2, "little") + b"\0\0" + body, target

    def read(self, raw):
        def device(handle, code, incoming, incoming_size, buffer, size, returned, overlapped):
            ctypes.memmove(buffer, raw, len(raw))
            ctypes.cast(returned, ctypes.POINTER(fs.DWORD))[0] = len(raw)
            return True
        api = SimpleNamespace(kernel=SimpleNamespace(DeviceIoControl=device))
        info = SimpleNamespace(attributes=fs.ATTR_REPARSE | fs.ATTR_DIRECTORY, links=1)
        with patch.object(fs, "_api", return_value=api), patch.object(fs, "_information", return_value=info), \
                patch.object(fs, "_skill_target", side_effect=lambda target, name: PureWindowsPath(target)):
            return fs._read_skill_handle(123, "xy-workflow")

    def test_exact_directory_symlink_is_read_without_following_target(self):
        raw, target = self.reparse()
        self.assertEqual(self.read(raw), target.encode())

    def test_junction_relative_and_truncated_reparse_buffers_are_rejected(self):
        for options in ({"tag": 0xA0000003}, {"flags": 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.read(self.reparse(**options)[0])
        with self.assertRaises(ValueError):
            self.read(self.reparse()[0][:-2])


class WindowsLockAndCapabilityContractTest(unittest.TestCase):
    def test_global_abandoned_mutex_fails_releases_and_does_not_poison_explicit_retry(self):
        events, names, waits = [], [], [0x80, 0]
        kernel = SimpleNamespace(
            CreateMutexW=lambda attributes, initial, name: names.append(name) or 42,
            WaitForSingleObject=lambda handle, timeout: waits.pop(0),
            ReleaseMutex=lambda handle: events.append("release") or True)
        with patch.object(fs, "Directory", side_effect=lambda path: nullcontext(SimpleNamespace(identity=(7, 9)))), \
                patch.object(fs, "_api", return_value=SimpleNamespace(kernel=kernel)), \
                patch.object(fs, "current_sid", return_value="S-1-5-21-42"), \
                patch.object(fs, "private_security", side_effect=lambda: nullcontext(123)), \
                patch.object(fs, "_security_policy", side_effect=lambda handle, **kwargs: nullcontext(None)), \
                patch.object(fs, "_policy_is_private", return_value=True), \
                patch.object(fs, "_close", side_effect=lambda handle: events.append("close")):
            with self.assertRaisesRegex(ValueError, "abandoned"):
                with fs.directory_lock(Path("/fixture")):
                    self.fail("abandoned writer must not enter")
            with fs.directory_lock(Path("/fixture")):
                events.append("entered")
        self.assertEqual(events, ["release", "close", "entered", "release", "close"])
        self.assertEqual(names[0], names[1])
        self.assertTrue(names[0].startswith("Global\\AgentWorkflow-S-1-5-21-42-"))

    def test_developer_mode_capability_preflight_performs_no_link_creation(self):
        create = Mock(side_effect=AssertionError("preview must not create a link"))
        registry = SimpleNamespace(HKEY_LOCAL_MACHINE=1, KEY_READ=1, KEY_WOW64_64KEY=2, REG_DWORD=4,
                                   OpenKey=lambda *args: nullcontext(123), QueryValueEx=lambda *args: (1, 4))
        with patch.dict(sys.modules, {"winreg": registry}), \
                patch.object(fs, "_api", return_value=SimpleNamespace(kernel=SimpleNamespace(CreateSymbolicLinkW=create))):
            fs.require_skill_symlinks()
        create.assert_not_called()

    def test_missing_developer_mode_and_no_enabled_privilege_refuse_without_probe(self):
        def open_token(process, rights, token):
            ctypes.cast(token, ctypes.POINTER(fs.HANDLE))[0] = fs.HANDLE(42)
            return True
        def privileges(token, kind, data, size, required):
            ctypes.cast(required, ctypes.POINTER(fs.DWORD))[0] = 4
            return data is not None
        registry = SimpleNamespace(HKEY_LOCAL_MACHINE=1, KEY_READ=1, KEY_WOW64_64KEY=2,
                                   OpenKey=Mock(side_effect=FileNotFoundError()))
        create = Mock(side_effect=AssertionError("preview must not create a link"))
        api = SimpleNamespace(kernel=SimpleNamespace(CreateSymbolicLinkW=create, GetCurrentProcess=lambda: 1),
                              security=SimpleNamespace(OpenProcessToken=open_token, GetTokenInformation=privileges,
                                                       LookupPrivilegeValueW=lambda *args: True))
        with patch.dict(sys.modules, {"winreg": registry}), patch.object(fs, "_api", return_value=api), \
                patch.object(fs, "_close") as close, self.assertRaisesRegex(ValueError, "Developer Mode"):
            fs.require_skill_symlinks()
        create.assert_not_called()
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class WindowsCompleteDeleteContractTest(unittest.TestCase):
    """完整条件删除只模拟原生调用边界，实际文件删除由 native 方法证明。"""

    def run_delete(self, *, before_security="a" * 64, after_security="a" * 64,
                   body=b"owned", expected_body=b"owned", reject=False):
        calls, chunks = [], [body, b""]
        identity = (7, 9, stat.S_IFREG | 0o600, 1, len(body), 11, 12)
        def read(handle, buffer, size, count, overlapped):
            self.assertEqual(123, handle)
            chunk = chunks.pop(0)
            ctypes.memmove(buffer, chunk, len(chunk))
            ctypes.cast(count, ctypes.POINTER(fs.DWORD))[0] = len(chunk)
            calls.append("read")
            return True
        api = SimpleNamespace(kernel=SimpleNamespace(ReadFile=read,
            SetFileInformationByHandle=lambda handle, *args: calls.append("delete") or True))
        with patch.object(fs.secure_os, "_path", return_value=Path("/project/file")), \
                patch.object(fs, "Directory", side_effect=lambda path: nullcontext()), \
                patch.object(fs, "_open_handle", return_value=123) as opened, \
                patch.object(fs, "_metadata", side_effect=[(identity, before_security), (identity, after_security)]), \
                patch.object(fs, "_api", return_value=api), \
                patch.object(fs, "_close", side_effect=lambda handle: calls.append("close")), \
                patch.object(fs, "flush_directory", side_effect=lambda path: calls.append("flush")):
            expected = {"identity": identity, "security": "a" * 64,
                        "sha256": hashlib.sha256(expected_body).hexdigest()}
            if reject:
                with self.assertRaises(ValueError):
                    fs.delete_regular(1, "file", expected=expected)
            else:
                fs.delete_regular(1, "file", expected=expected)
        opened.assert_called_once_with(Path("/project/file"), fs.READ | fs.DELETE, sharing=fs.SHARE_READ)
        return calls

    def test_same_handle_full_metadata_acl_digest_delete_and_flush(self):
        self.assertEqual(["flush", "read", "read", "delete", "close", "flush"], self.run_delete())

    def test_acl_change_with_identical_stat_or_digest_change_never_deletes(self):
        for options in ({"before_security": "b" * 64}, {"after_security": "b" * 64},
                        {"body": b"saved", "expected_body": b"owned"}):
            with self.subTest(options=options):
                calls = self.run_delete(**options, reject=True)
                self.assertNotIn("delete", calls)
                self.assertEqual("close", calls[-1])

    def test_closed_expected_and_fixed_stream_budget_reject_before_native_io(self):
        expected = {"identity": (1,) * 7, "security": "a" * 64, "sha256": "b" * 64}
        with patch.object(fs, "_api", side_effect=AssertionError("must reject before native I/O")):
            for invalid in ({**expected, "path": "escape"}, {**expected, "security": ""},
                            {**expected, "identity": list(expected["identity"])}):
                with self.assertRaises(ValueError):
                    fs.delete_regular(1, "file", expected=invalid)
            for limit in (0, True, 128 * 1024 * 1024 + 1):
                with self.assertRaises(ValueError):
                    fs.delete_regular(1, "file", expected=expected, max_bytes=limit)


class WindowsDirectoryDeleteContractTest(unittest.TestCase):
    """目录身份/ACL守卫与内核非空拒绝的窄调用合同，不递归或猜测路径归属。"""

    def run_delete(self, *, security="a" * 64, nonempty=False, reject=False):
        calls = []
        metadata = ((7, 9, stat.S_IFDIR | 0o700, 1, 0, 11, 12), security)
        def disposition(*args):
            calls.append("disposition")
            if nonempty:
                raise OSError("native directory is not empty")
            return True
        with patch.object(fs.secure_os, "_path", return_value=Path("/project/stage")), \
                patch.object(fs, "Directory", side_effect=lambda path: nullcontext()), \
                patch.object(fs, "_open_handle", return_value=123) as opened, \
                patch.object(fs, "_metadata", return_value=metadata), \
                patch.object(fs, "_api", return_value=SimpleNamespace(kernel=SimpleNamespace(SetFileInformationByHandle=disposition))), \
                patch.object(fs, "_close", side_effect=lambda handle: calls.append("close")), \
                patch.object(fs, "flush_directory", side_effect=lambda path: calls.append("flush")):
            expected = {"identity": (7, 9), "security": "a" * 64}
            if reject:
                with self.assertRaises((OSError, ValueError)):
                    fs.delete_directory(1, "stage", expected=expected)
            else:
                fs.delete_directory(1, "stage", expected=expected)
        opened.assert_called_once_with(Path("/project/stage"), fs.READ_CONTROL | 0x81 | fs.DELETE,
                                       directory=True, sharing=fs.SHARE_READ)
        return calls

    def test_registered_empty_directory_deletes_then_flushes(self):
        self.assertEqual(["flush", "disposition", "close", "flush"], self.run_delete())

    def test_acl_change_or_nonempty_kernel_rejection_preserves_directory(self):
        self.assertEqual(["flush", "close"], self.run_delete(security="b" * 64, reject=True))
        self.assertEqual(["flush", "disposition", "close"], self.run_delete(nonempty=True, reject=True))


class WindowsInitialPrivateContractTest(unittest.TestCase):
    def test_embedded_and_backend_share_exact_private_owner_and_acl_policy(self):
        user = bytes.fromhex("010100000000000515000000")
        system = bytes.fromhex("010100000000000512000000")
        def ace(sid):
            return bytes((0, 3)) + (8 + len(sid)).to_bytes(2, "little") + (0x1F01FF).to_bytes(4, "little") + sid
        entries = ace(user) + ace(system)
        acl = bytes((2, 0)) + (8 + len(entries)).to_bytes(2, "little") + (2).to_bytes(2, "little") + b"\0\0" + entries
        self.assertTrue(fs._private_policy_bytes(user, 0x1004, acl, user))
        self.assertFalse(fs._private_policy_bytes(system, 0x1004, acl, user))
        self.assertFalse(fs._private_policy_bytes(user, 4, acl, user))
        changed = bytearray(acl); changed[4:6] = (3).to_bytes(2, "little")
        self.assertFalse(fs._private_policy_bytes(user, 0x1004, bytes(changed), user))
        policy = SimpleNamespace(owner=user, control=0x1004, acl_bytes=acl)
        with patch.object(fs, "current_sid", return_value="user"), patch.object(fs, "_sid_bytes", return_value=user):
            self.assertTrue(fs._policy_is_private(policy))
        source = fs.bootstrap_reader_source()
        self.assertIn("def _private_policy_bytes", source)
        self.assertIn("require_private=False", source)
        self.assertIn("permissions(handle, require_private and not directory)", source)
        namespace = {}
        exec(compile(source, "<private-initial-closure>", "exec"), namespace)
        self.assertEqual(False, namespace["read_initial_regular"].__kwdefaults__["require_private"])
