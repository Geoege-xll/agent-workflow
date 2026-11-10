"""Portable Win32 call contracts, not native filesystem acceptance."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager, nullcontext
import ctypes
import ast
import hashlib
import importlib.util
import os
from pathlib import Path, PureWindowsPath
import stat
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock


PACK = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("windows_fs_contract", PACK / "lib/windows_fs.py")
fs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fs)


class WindowsNativeObserverStreamContractTest(unittest.TestCase):
    def test_actual_observer_supports_production_stream_shape_and_real_post_close_io(self):
        """消费原生节点使用的同一代理与真实文件，直接证明接口及关闭后注入。"""
        from tests.test_windows_fs_native import CloseObservedStream
        for scenario in ("normal", "body-error", "callback-error"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix="awf-stream-observer-") as temporary:
                path = Path(temporary) / "owned-stage"
                raw = path.open("wb")
                observed = []
                def inject_after_close():
                    self.assertTrue(raw.closed)
                    self.assertEqual(b"APPROVED", path.read_bytes())
                    observed.append("real-close-before-injection")
                    # 真正重新打开同一自有文件写外来正文；不以 callback 次数
                    # 或镜像流替身代替实际关闭之后的文件系统边界。
                    path.write_bytes(b"FOREIGN")
                    if scenario == "callback-error":
                        raise LookupError("fixture callback error")
                stream = CloseObservedStream(raw, inject_after_close)
                def consume_as_production():
                    # 保持 production 的精确形状：没有 as 绑定，进入上下文后
                    # 仍通过原 stream 变量调用真实 write/flush/fileno。
                    with stream:
                        self.assertEqual(len(b"APPROVED"), stream.write(b"APPROVED"))
                        stream.flush()
                        self.assertEqual(len(b"APPROVED"), os.fstat(stream.fileno()).st_size)
                        os.fsync(stream.fileno())
                        self.assertEqual([], observed)
                        if scenario == "body-error":
                            raise ValueError("fixture body error")
                if scenario == "body-error":
                    with self.assertRaisesRegex(ValueError, "body error"):
                        consume_as_production()
                    self.assertEqual([], observed)
                    self.assertEqual(b"APPROVED", path.read_bytes())
                elif scenario == "callback-error":
                    with self.assertRaisesRegex(LookupError, "callback error"):
                        consume_as_production()
                else:
                    consume_as_production()
                self.assertTrue(raw.closed)
                if scenario != "body-error":
                    self.assertEqual(["real-close-before-injection"], observed)
                    self.assertEqual(b"FOREIGN", path.read_bytes())


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

    def test_permission_copy_skips_equal_policy_only_with_stable_source_and_target(self):
        """同策略免写仍复核两端；owner/ACL 竞态不能被免写分支吞掉。"""
        def policy(fingerprint, key=b"same"):
            return SimpleNamespace(control=0x1004, acl=42, dacl_key=key, owner=b"owner",
                                   fingerprint=fingerprint, acl_bytes=b"\2\0\10\0\2\0\0\0")
        source, target = policy("source"), policy("target")
        for label, current, after in (("stable", source, target),
                                      ("source-owner-race", policy("changed-source"), target),
                                      ("target-owner-race", source, policy("changed-target")),
                                      ("target-acl-race", source, policy("changed-target", b"other"))):
            observed = Mock(side_effect=lambda handle, values=iter((source, target, after, current)):
                            nullcontext(next(values)))
            with self.subTest(race=label), patch.object(fs, "_security_policy", observed), \
                    patch.object(fs, "_api", side_effect=AssertionError("equal DACL policy must not be rewritten")):
                if label == "stable":
                    fs._copy_permissions(1, 2)
                else:
                    with self.assertRaisesRegex(ValueError, "raced"):
                        fs._copy_permissions(1, 2)
            self.assertEqual([((1,), {}), ((2,), {}), ((2,), {}), ((1,), {})], observed.call_args_list)

    def test_permission_copy_preserves_protected_or_inheriting_policy(self):
        for protected, expected in ((False, 0x20000004), (True, 0x80000004)):
            calls = []
            api = SimpleNamespace(security=SimpleNamespace(
                SetSecurityInfo=lambda *args: calls.append(args) or 0))
            policy = SimpleNamespace(control=0x1000 if protected else 0, acl=42, dacl_key=b"same",
                                     owner=b"owner", fingerprint=b"same", acl_bytes=b"\2\0\10\0\2\0\0\0")
            original = SimpleNamespace(dacl_key=b"different", owner=b"owner", fingerprint=b"stage")
            policies = iter((policy, original, policy, policy))
            with self.subTest(protected=protected), patch.object(fs, "_api", return_value=api), \
                    patch.object(fs, "_security_policy", side_effect=lambda handle: nullcontext(next(policies))):
                fs._copy_permissions(1, 2)
            self.assertEqual(calls[0][2], expected)

    def test_permission_copy_checks_authorized_policy_at_actual_read_before_any_write(self):
        """外层已核快照后，helper 首次取策略仍不能重新认领后来的 ACL。"""
        source = SimpleNamespace(fingerprint="a" * 64)
        destination = SimpleNamespace(fingerprint="b" * 64)
        for source_expected, destination_expected in (("c" * 64, "b" * 64), ("a" * 64, "c" * 64)):
            with self.subTest(source_changed=source_expected != source.fingerprint), \
                    patch.object(fs, "_security_policy", side_effect=[nullcontext(source), nullcontext(destination)]), \
                    patch.object(fs, "_api", side_effect=AssertionError("未授权策略不能进入 SetSecurityInfo")), \
                    self.assertRaisesRegex(ValueError, "authorized copy"):
                fs._copy_permissions(10, 20, expected_source_security=source_expected,
                                     expected_destination_security=destination_expected)

    def test_permission_copy_refuses_stage_parent_inheritance_changes(self):
        source = SimpleNamespace(control=0, acl=42, dacl_key=b"target", owner=b"owner",
                                 fingerprint=b"target", acl_bytes=b"\2\0\10\0\2\0\0\0")
        stage = SimpleNamespace(control=0, dacl_key=b"stage-parent", owner=b"owner",
                                fingerprint=b"stage", acl_bytes=b"\2\0\10\0\3\0\0\0")
        policies = [source, stage, stage, source]
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


class WindowsConditionalPermissionCopyContractTest(unittest.TestCase):
    """仅验证 Win32 调用契约与闭集，不把替身结果扩大为真实 NTFS 证据。"""

    def fixture(self):
        source = {"kind": "file", "payload": b"old", "mode": 0o666,
                  "identity": (7, 101, stat.S_IFREG | 0o666, 1, 3, 11, 12), "security": "a" * 64}
        destination = {"kind": "file", "payload": b"approved", "mode": 0o600,
                       "identity": (7, 202, stat.S_IFREG | 0o600, 1, 8, 21, 22), "security": "b" * 64}
        return source, destination

    def execute(self, *, actual_source=None, actual_destination=None, source_after=None,
                destination_after=None, copied_security=None, attributes=(0x20, 0x20, 0x20, 0x20)):
        source, destination = self.fixture()
        copied_security = copied_security or destination["security"]
        with ExitStack() as scope:
            scope.enter_context(patch.object(fs, "absolute_path", side_effect=Path))
            scope.enter_context(patch.object(fs, "Directory", side_effect=lambda path: nullcontext()))
            opening = scope.enter_context(patch.object(fs, "_open_handle", side_effect=[10, 20]))
            closing = scope.enter_context(patch.object(fs, "_close"))
            scope.enter_context(patch.object(fs, "_opened_snapshot", side_effect=[actual_source or source, actual_destination or destination]))
            copying = scope.enter_context(patch.object(fs, "_copy_permissions", return_value=copied_security))
            scope.enter_context(patch.object(fs, "_metadata", side_effect=[source_after or (source["identity"], source["security"]),
                                                                          destination_after or (destination["identity"], copied_security)]))
            scope.enter_context(patch.object(fs, "_information", side_effect=[SimpleNamespace(attributes=value) for value in attributes]))
            result, failure = None, None
            try:
                result = fs.copy_permissions_if_unchanged(Path("/source"), Path("/destination"),
                                                         expected_source=source, expected_destination=destination)
            except ValueError as exc:
                failure = exc
            self.assertEqual([((20,), {}), ((10,), {})], closing.call_args_list)
            self.assertEqual(fs.SHARE_READ, opening.call_args_list[0].kwargs["sharing"])
            self.assertEqual(fs.SHARE_READ, opening.call_args_list[1].kwargs["sharing"])
            # 目标 HANDLE 仅加 WRITE_DAC，不能重新引入数据 WRITE 权限。
            self.assertEqual(fs.READ | 0x40000, opening.call_args_list[1].args[1])
            return result, failure, copying

    def test_full_source_and_destination_are_checked_before_permission_mutation(self):
        source, destination = self.fixture()
        for actual_source, actual_destination in (({**source, "security": "c" * 64}, destination),
                                                  (source, {**destination, "payload": b"foreign!"}),
                                                  (source, {**destination, "identity": (7, 999, *destination["identity"][2:])})):
            with self.subTest(source_changed=actual_source != source):
                _, failure, copying = self.execute(actual_source=actual_source, actual_destination=actual_destination)
                self.assertIsInstance(failure, ValueError)
                copying.assert_not_called()

    def test_only_real_acl_change_allows_projected_mode_and_change_time(self):
        source, destination = self.fixture()
        result, failure, copying = self.execute()
        self.assertIsNone(failure)
        self.assertEqual(destination, result)
        copying.assert_called_once_with(10, 20, expected_source_security=source["security"],
                                        expected_destination_security=destination["security"])
        original = destination["identity"]
        changed = (*original[:2], stat.S_IFREG | 0o666, *original[3:6], original[6] + 1)
        result, failure, _ = self.execute(copied_security="c" * 64, destination_after=(changed, "c" * 64))
        self.assertIsNone(failure)
        self.assertEqual(changed, result["identity"])
        self.assertEqual(0o666, result["mode"])
        for after in (changed, (*original[:5], 999, original[6]), (7, 999, *original[2:])):
            with self.subTest(unauthorized_metadata=after):
                _, failure, _ = self.execute(destination_after=(after, destination["security"]))
                self.assertIsInstance(failure, ValueError)
        for updates in ({"source_after": (source["identity"], "c" * 64)},
                        {"attributes": (0x20, 0x20, 0x20, 0x22)},
                        {"copied_security": "c" * 64, "destination_after": (changed, "d" * 64)},
                        {"copied_security": "c" * 64,
                         "destination_after": ((*original[:5], 999, original[6]), "c" * 64)}):
            with self.subTest(unauthorized_change=updates):
                _, failure, _ = self.execute(**updates)
                self.assertIsInstance(failure, ValueError)


class WindowsStageCreationContractTest(unittest.TestCase):
    """执行真实负责层函数，仅替换 Win32 边界；不把此层成功冒称 NTFS 成功。"""

    def create(self, *, with_source=True, source_body=b"old", source_payload=None, source_policy=None,
               source_after=None, collision=False, conversion_failure=False, max_bytes=fs._LIMIT):
        source = {"kind": "file", "payload": source_body, "mode": 0o666,
                  "identity": (7, 101, stat.S_IFREG | 0o666, 1, len(source_body), 10, 20), "security": "a" * 64}
        mode, security = (0o666, "a" * 64) if with_source else (0o600, "b" * 64)
        empty = {"kind": "file", "payload": b"", "mode": mode,
                 "identity": (7, 202, stat.S_IFREG | mode, 1, 0, 30, 40), "security": security}
        parent = SimpleNamespace(path=Path("/owned"), child=lambda name: Path("/owned") / name, close=Mock())
        opening, raw_closes, fd_closes = [], [], []
        def opened(path, access, **kwargs):
            opening.append((Path(path).name, access, kwargs))
            if Path(path).name == "source":
                return 101
            if collision:
                raise FileExistsError("fixture collision")
            return 202
        def snapshot(handle, **kwargs):
            return {**source, "payload": source_body if source_payload is None else source_payload} if handle == 101 else dict(empty)
        def metadata(handle):
            return source_after or (source["identity"], source["security"]) if handle == 101 else (empty["identity"], empty["security"])
        def convert(handle, flags):
            if conversion_failure:
                raise OSError("fixture CRT transfer failure")
            return 9
        native = SimpleNamespace(open_osfhandle=convert, get_osfhandle=lambda descriptor: 202)
        with ExitStack() as scope:
            scope.enter_context(patch.dict(sys.modules, {"msvcrt": native}))
            scope.enter_context(patch.dict(fs.secure_os._directories, {77: parent}, clear=True))
            scope.enter_context(patch.dict(fs.secure_os._files, {}, clear=True))
            scope.enter_context(patch.object(fs, "Directory", return_value=parent))
            scope.enter_context(patch.object(fs, "_open_handle", side_effect=opened))
            scope.enter_context(patch.object(fs, "_opened_snapshot", side_effect=snapshot))
            scope.enter_context(patch.object(fs, "_metadata", side_effect=metadata))
            scope.enter_context(patch.object(fs, "_information", return_value=SimpleNamespace(attributes=32)))
            scope.enter_context(patch.object(fs, "_security_policy", side_effect=lambda handle:
                                             nullcontext(SimpleNamespace(descriptor=fs.HANDLE(42), fingerprint=source_policy or security))))
            scope.enter_context(patch.object(fs, "private_security", side_effect=lambda: nullcontext(fs.HANDLE(42))))
            scope.enter_context(patch.object(fs, "_policy_is_private", return_value=True))
            scope.enter_context(patch.object(fs, "_close", side_effect=raw_closes.append))
            scope.enter_context(patch.object(fs._os, "close", side_effect=fd_closes.append))
            scope.enter_context(patch.object(fs._os, "O_BINARY", 0, create=True))
            scope.enter_context(patch.object(fs._os, "O_NOINHERIT", 0, create=True))
            removal = scope.enter_context(patch.object(fs, "delete_regular", side_effect=AssertionError("constructor must not adopt a cleanup path")))
            result, failure = None, None
            try:
                result = fs.create_regular_stage(77, "stage", permission_source="source" if with_source else None,
                                                 expected_source=source if with_source else None, max_bytes=max_bytes)
                entry = fs.secure_os._files[result[0]]
                self.assertIsInstance(entry, fs._CreatedStageFile)
                self.assertEqual(empty, entry.empty)
                self.assertEqual(max_bytes, entry.max_bytes)
                self.assertIsNot(result[1], entry.empty)
                with self.assertRaises(TypeError):
                    entry.empty["mode"] = 0o777
                result[1]["mode"] = 0o777
                self.assertEqual(mode, entry.empty["mode"], "调用方修改返回dict不能改内部授权")
                result[1]["mode"] = mode
                fs.secure_os.close(result[0])
                self.assertNotIn(9, fs.secure_os._files)
            except (ValueError, OSError) as exc:
                failure = exc
            removal.assert_not_called()
        return result, failure, opening, raw_closes, fd_closes, parent.close.call_count

    def test_default_and_private_creation_transfer_sole_handle_and_immutable_witness(self):
        for with_source in (True, False):
            with self.subTest(with_source=with_source):
                result, failure, opening, raw_closes, fd_closes, parent_closes = self.create(with_source=with_source)
                self.assertIsNone(failure)
                self.assertEqual(b"", result[1]["payload"])
                self.assertEqual([9], fd_closes)
                self.assertEqual([101] if with_source else [], raw_closes)
                self.assertEqual(1, parent_closes)
                self.assertEqual(fs.READ | fs.WRITE, opening[-1][1])
                self.assertEqual(0, opening[-1][2]["sharing"])
                self.assertTrue(opening[-1][2]["exclusive"])
                if with_source:
                    self.assertEqual(fs.SHARE_READ, opening[0][2]["sharing"])

    def test_source_drift_collision_and_transfer_failure_preserve_unproved_stage(self):
        for options, raw, attempted in (({"source_payload": b"new"}, [101], 1),
                                        ({"source_policy": "c" * 64}, [101], 1),
                                        ({"with_source": False, "source_policy": "c" * 64}, [202], 1),
                                        ({"source_after": ((7, 101, stat.S_IFREG | 0o666, 1, 3, 10, 20), "c" * 64)}, [101, 202], 2),
                                        ({"collision": True}, [101], 2),
                                        ({"conversion_failure": True}, [101, 202], 2)):
            with self.subTest(options=options):
                result, failure, opening, raw_closes, fd_closes, parent_closes = self.create(**options)
                self.assertIsNone(result)
                self.assertIsInstance(failure, (ValueError, OSError))
                self.assertEqual(raw, raw_closes)
                self.assertEqual([], fd_closes)
                self.assertEqual(attempted, len(opening))
                self.assertEqual(1, parent_closes)

    def test_closed_arguments_are_rejected_before_native_io(self):
        with patch.dict(fs.secure_os._directories, {77: object()}, clear=True), \
                patch.object(fs, "Directory", side_effect=AssertionError("invalid contract must reject before I/O")):
            for directory, name, kwargs in ((True, "stage", {}), (88, "stage", {}), (77, "CON", {}),
                                            (77, "stage", {"permission_source": "source"}),
                                            (77, "stage", {"permission_source": "stage", "expected_source": {}})):
                with self.subTest(directory=directory, name=name), self.assertRaises(ValueError):
                    fs.create_regular_stage(directory, name, **kwargs)

    def test_explicit_host_budget_does_not_change_default_or_admit_invalid_limits(self):
        body = b"x" * (fs._LIMIT + 1)
        _, failure, opening, _, _, parent_closes = self.create(source_body=body)
        self.assertIsInstance(failure, ValueError)
        self.assertEqual([], opening, "默认4MiB必须在创建/打开源之前拒绝超额前像")
        self.assertEqual(0, parent_closes)
        result, failure, _, _, _, _ = self.create(source_body=body, max_bytes=2 * fs._LIMIT)
        self.assertIsNone(failure)
        self.assertEqual(b"", result[1]["payload"], "显式file预算不能变更现五字段空见证")
        for limit in (0, -1, True, 2 * fs._LIMIT + 1):
            with self.subTest(limit=limit):
                _, failure, opening, _, _, _ = self.create(max_bytes=limit)
                self.assertIsInstance(failure, ValueError)
                self.assertEqual([], opening)


class WindowsStageSealContractTest(unittest.TestCase):
    def seal(self, *, entry_kind="creator", expected_change=None, actual_change=None,
             metadata_security=None, handle=202, attributes=(32, 32), mode=0o644,
             read_failure=False, fsync_failure=False, payload=b"APPROVED",
             creator_budget=fs._LIMIT, seal_budget=fs._LIMIT):
        empty = {"kind": "file", "payload": b"", "mode": 0o600,
                 "identity": (7, 202, stat.S_IFREG | 0o600, 1, 0, 30, 40), "security": "b" * 64}
        actual = {**empty, "payload": payload, "identity": (*empty["identity"][:4], len(payload), 51, 52)}
        actual.update(actual_change or {})
        expected = {**empty, **(expected_change or {})}
        entry = fs._CreatedStageFile(SimpleNamespace(path=Path("/owned"), close=Mock()), 202,
                                     fs.MappingProxyType(dict(empty)), 32, creator_budget) if entry_kind == "creator" else object()
        with ExitStack() as scope:
            scope.enter_context(patch.dict(fs.secure_os._files, {} if entry_kind == "closed" else {9: entry}, clear=True))
            scope.enter_context(patch.object(fs, "_handle_for_descriptor", return_value=handle))
            scope.enter_context(patch.object(fs, "_metadata", return_value=(actual["identity"], metadata_security or empty["security"])))
            scope.enter_context(patch.object(fs, "_information", side_effect=[SimpleNamespace(attributes=value) for value in attributes]))
            reading = scope.enter_context(patch.object(fs, "_opened_snapshot", side_effect=OSError("fixture native read failure") if read_failure else None,
                                                       return_value=actual))
            syncing = scope.enter_context(patch.object(fs.secure_os, "fsync", side_effect=OSError("fixture fsync failure") if fsync_failure else None))
            seeking = scope.enter_context(patch.object(fs._os, "lseek", side_effect=lambda descriptor, offset, whence: 11 if whence == fs._os.SEEK_CUR else offset))
            closing = scope.enter_context(patch.object(fs.secure_os, "close", side_effect=AssertionError("seal is not the close owner")))
            result, failure = None, None
            try:
                result = fs.seal_regular_stage(9, expected_created=expected, payload=payload, mode=mode, max_bytes=seal_budget)
            except (ValueError, OSError) as exc:
                failure = exc
            closing.assert_not_called()
            return result, failure, reading, syncing, seeking

    def test_same_handle_approved_data_and_cursor_restore_without_closing(self):
        result, failure, reading, syncing, seeking = self.seal()
        self.assertIsNone(failure)
        self.assertEqual(b"APPROVED", result["payload"])
        self.assertEqual(0o600, result["mode"], "逻辑0644不能放宽原私有ACL物理mode")
        syncing.assert_called_once_with(9)
        self.assertEqual([((9, 0, fs._os.SEEK_CUR), {}), ((9, 0, fs._os.SEEK_SET), {}),
                          ((9, 11, fs._os.SEEK_SET), {})], seeking.call_args_list)
        reading.assert_called_once_with(202, max_bytes=8)

    def test_forged_creator_reused_fd_mode_acl_attributes_and_payload_are_rejected(self):
        variants = ({"entry_kind": "ordinary"}, {"entry_kind": "closed"}, {"handle": 303},
                    {"expected_change": {"mode": 0o666}}, {"mode": 0o444},
                    {"metadata_security": "c" * 64}, {"attributes": (2, 2)}, {"attributes": (32, 2)},
                    {"actual_change": {"payload": b"FOREIGN!"}},
                    {"actual_change": {"mode": 0o666}},
                    {"actual_change": {"security": "c" * 64}},
                    {"actual_change": {"identity": (7, 999, stat.S_IFREG | 0o600, 1, 8, 51, 52)}})
        for options in variants:
            with self.subTest(options=options):
                result, failure, _, _, _ = self.seal(**options)
                self.assertIsNone(result)
                self.assertIsInstance(failure, ValueError)

    def test_read_failure_restores_cursor_and_fsync_failure_keeps_caller_ownership(self):
        for options in ({"read_failure": True}, {"fsync_failure": True}):
            with self.subTest(options=options):
                _, failure, _, _, seeking = self.seal(**options)
                self.assertIsInstance(failure, OSError)
                if options.get("read_failure"):
                    self.assertEqual((9, 11, fs._os.SEEK_SET), seeking.call_args_list[-1].args)
                else:
                    seeking.assert_not_called()

    def test_seal_budget_is_explicit_and_cannot_upgrade_the_creator(self):
        body = b"x" * (fs._LIMIT + 1)
        _, failure, reading, syncing, _ = self.seal(payload=body, creator_budget=2 * fs._LIMIT)
        self.assertIsInstance(failure, ValueError)
        reading.assert_not_called()
        syncing.assert_not_called()
        result, failure, reading, _, _ = self.seal(payload=body, creator_budget=2 * fs._LIMIT, seal_budget=2 * fs._LIMIT)
        self.assertIsNone(failure)
        self.assertEqual(len(body), len(result["payload"]))
        reading.assert_called_once_with(202, max_bytes=len(body))
        for limit in (2 * fs._LIMIT, 0, -1, True, 2 * fs._LIMIT + 1):
            with self.subTest(requested_seal_budget=limit):
                _, failure, reading, syncing, _ = self.seal(seal_budget=limit)
                self.assertIsInstance(failure, ValueError)
                reading.assert_not_called()
                syncing.assert_not_called()



class WindowsClosedWriterContractTest(unittest.TestCase):
    """调用真实统一发布器，替换仅限原生边界；不将此层作为 NTFS 成功。"""

    def publish(self, *, missing=False, fault=None):
        empty = {"kind": "file", "payload": b"", "mode": 0o600,
                 "identity": (7, 202, stat.S_IFREG | 0o600, 1, 0, 30, 40), "security": "b" * 64}
        ready = {**empty, "payload": b"APPROVED", "identity": (*empty["identity"][:4], 8, 50, 60)}
        before = None if missing else {**empty, "payload": b"old", "identity": (7, 101, stat.S_IFREG | 0o600, 1, 3, 10, 20)}
        foreign = {**ready, "payload": b"FOREIGN!"}
        events, moved = [], False
        parent = SimpleNamespace(path=Path("/owned"), child=lambda name: Path("/owned") / name)
        target_reads = 0
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): events.append("stream-close"); fs.secure_os._files.pop(9, None)
            def fileno(self): return 9
            def write(self, data):
                events.append(("write", data))
                if fault == "write": raise OSError("actual stream write boundary")
            def flush(self): events.append("flush")
        def creation(*args, **kwargs):
            events.append("create")
            fs.secure_os._files[9] = SimpleNamespace(attributes=32)
            return 9, dict(empty)
        def opened_stream(*args):
            if fault in ("fdopen", "fdopen-close"): raise OSError("fdopen boundary")
            return Stream()
        def snapshot(directory, name, **kwargs):
            nonlocal target_reads
            if name == "target":
                target_reads += 1
                return foreign if fault == "target" and target_reads == 2 else before
            return foreign if fault == "close" else dict(ready)
        def rename(*args, **kwargs):
            nonlocal moved
            moved = True; events.append("rename")
        def metadata(handle):
            return ((*ready["identity"][:6], 61) if moved else ready["identity"], ready["security"])
        with ExitStack() as scope:
            scope.enter_context(patch.dict(fs.secure_os._directories, {77: parent}, clear=True))
            scope.enter_context(patch.dict(fs.secure_os._files, {}, clear=True))
            scope.enter_context(patch.object(fs, "Directory", side_effect=lambda path: nullcontext(parent)))
            scope.enter_context(patch.object(fs, "node_snapshot", side_effect=snapshot))
            creating = scope.enter_context(patch.object(fs, "create_regular_stage", side_effect=creation))
            scope.enter_context(patch.object(fs.secure_os, "fdopen", side_effect=opened_stream))
            sealing = scope.enter_context(patch.object(fs, "seal_regular_stage", return_value=ready,
                side_effect=OSError("fsync boundary") if fault == "seal" else None))
            scope.enter_context(patch.object(fs, "flush_directory"))
            scope.enter_context(patch.object(fs, "_open_handle", return_value=202))
            reading = scope.enter_context(patch.object(fs, "_opened_snapshot", return_value=foreign if fault == "ready" else ready))
            scope.enter_context(patch.object(fs, "_metadata", side_effect=metadata))
            scope.enter_context(patch.object(fs, "_information", return_value=SimpleNamespace(attributes=2 if fault == "attributes" else 32)))
            moving = scope.enter_context(patch.object(fs, "_rename_handle", side_effect=rename))
            cleanup = scope.enter_context(patch.object(fs, "_discard_created_stage"))
            close_fd = scope.enter_context(patch.object(fs.secure_os, "close",
                side_effect=OSError("close boundary") if fault == "fdopen-close" else None))
            close_handle = scope.enter_context(patch.object(fs, "_close"))
            scope.enter_context(patch.object(fs.secure_os, "replace_owned", side_effect=AssertionError("identity-only publication is forbidden")))
            result = failure = None
            try:
                result = fs.write_regular_if_unchanged(77, "target", "stage", expected=before,
                    payload=b"APPROVED", mode=0o644)
            except (ValueError, OSError) as exc:
                failure = exc
        return SimpleNamespace(**locals())

    def test_existing_and_missing_use_full_ready_handle_and_return_only_own_rename_facts(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                result = self.publish(missing=missing)
                self.assertIsNone(result.failure)
                self.assertEqual((7, 202), result.result["identity"][:2])
                self.assertEqual(61, result.result["identity"][6])
                self.assertEqual(b"APPROVED", result.result["payload"])
                self.assertEqual(1, result.events.count("stream-close"))
                result.close_fd.assert_not_called()
                result.close_handle.assert_called_once_with(202)
                result.reading.assert_called_once_with(202, max_bytes=fs._LIMIT)
                result.moving.assert_called_once_with(202, result.parent, "target", replace=not missing)
                result.cleanup.assert_not_called()
                self.assertEqual(result.before, result.creating.call_args.kwargs["expected_source"])

    def test_closed_ready_target_and_raw_attribute_drift_never_publish_or_adopt_foreign(self):
        for fault in ("close", "ready", "target", "attributes"):
            with self.subTest(fault=fault):
                result = self.publish(fault=fault)
                self.assertIsInstance(result.failure, ValueError)
                result.moving.assert_not_called()
                self.assertEqual(result.ready, result.cleanup.call_args.args[2], "清理只能持有批准原像，不能追认foreign")
                self.assertEqual(1, result.events.count("stream-close"))

    def test_fdopen_write_and_barrier_failure_keep_single_close_and_known_creation_cleanup(self):
        for fault in ("fdopen", "fdopen-close", "write", "seal"):
            with self.subTest(fault=fault):
                result = self.publish(fault=fault)
                self.assertIsInstance(result.failure, OSError)
                result.moving.assert_not_called()
                self.assertEqual(result.empty, result.cleanup.call_args.args[2])
                if fault in ("fdopen", "fdopen-close"):
                    result.close_fd.assert_called_once_with(9)
                    self.assertNotIn("stream-close", result.events)
                    self.assertEqual("fdopen boundary", str(result.failure), "关闭错误不能覆盖原始构造异常")
                    if fault == "fdopen-close":
                        self.assertTrue(any("close failed" in note for note in result.failure.__notes__))
                else:
                    result.close_fd.assert_not_called()
                    self.assertEqual(1, result.events.count("stream-close"))
                result.close_handle.assert_not_called()

    def test_invalid_budget_readonly_and_missing_authorization_reject_before_creating(self):
        with patch.dict(fs.secure_os._directories, {77: object()}, clear=True), \
                patch.object(fs, "Directory", side_effect=AssertionError("validation must precede native I/O")):
            for kwargs in ({"mode": 0o444}, {"max_bytes": True}, {"payload": b"x" * (fs._LIMIT + 1)}):
                values = dict(expected=None, payload=b"new", mode=0o644)
                values.update(kwargs)
                with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError):
                    fs.write_regular_if_unchanged(77, "target", "stage", **values)


    def test_cleanup_preserves_changed_raw_attributes_even_when_all_five_fields_match(self):
        expected = {"kind": "file", "payload": b"APPROVED", "mode": 0o600,
                    "identity": (7, 202, stat.S_IFREG | 0o600, 1, 8, 50, 60), "security": "b" * 64}
        api = SimpleNamespace(kernel=SimpleNamespace(SetFileInformationByHandle=Mock(return_value=1)))
        with patch.object(fs.secure_os, "_path", return_value=Path("/owned/stage")), \
                patch.object(fs, "_open_handle", return_value=202), patch.object(fs, "_opened_snapshot", return_value=expected), \
                patch.object(fs, "_information", return_value=SimpleNamespace(attributes=34)), \
                patch.object(fs, "_api", return_value=api), patch.object(fs, "_close") as closing:
            with self.assertRaisesRegex(ValueError, "external edit"):
                fs._discard_created_stage(77, "stage", expected, 32, fs._LIMIT)
            api.kernel.SetFileInformationByHandle.assert_not_called()
            closing.assert_called_once_with(202)


class WindowsExplicitMoveBudgetContractTest(unittest.TestCase):
    def test_large_expected_move_needs_explicit_budget_before_namespace_effects(self):
        body = b"x" * (fs._LIMIT + 1)
        expected = {"kind": "file", "payload": body, "mode": 0o600,
                    "identity": (7, 202, stat.S_IFREG | 0o600, 1, len(body), 10, 20), "security": "a" * 64}
        destination = SimpleNamespace(handle=10, child=lambda name: Path("/owned") / name)
        with patch.object(fs.secure_os, "_path", side_effect=lambda name, descriptor: Path("/owned") / name), \
                patch.object(fs, "Directory", side_effect=lambda path: nullcontext(destination)), \
                patch.object(fs, "flush_directory") as flushing, patch.object(fs, "_open_handle", return_value=202) as opening, \
                patch.object(fs, "_opened_snapshot", return_value=expected) as reading, \
                patch.object(fs, "_close"), patch.object(fs, "_rename_handle") as moving:
            with self.assertRaises(ValueError):
                fs.move_regular("stage", "target", src_dir_fd=1, dst_dir_fd=1, expected=expected)
            opening.assert_not_called()
            flushing.assert_not_called()
            moving.assert_not_called()
            fs.move_regular("stage", "target", src_dir_fd=1, dst_dir_fd=1, expected=expected, max_bytes=2 * fs._LIMIT)
            reading.assert_called_once_with(202, max_bytes=len(body), skill_name=None)
            moving.assert_called_once_with(202, destination, "target")


class WindowsReplacementOwnerContractTest(unittest.TestCase):
    def test_same_dacl_but_different_owner_never_mutates_or_replaces_candidate(self):
        source, target = Path("/owned/stage"), Path("/owned/target")
        destination = SimpleNamespace(handle=1, child=lambda name: target.parent / name)
        metadata = lambda handle: ((7, handle, stat.S_IFREG | 0o600, 1, 8, 10, 20),
                                   ("a" if handle == 101 else "b") * 64)
        with patch.object(fs, "Directory", side_effect=lambda path: nullcontext(destination)), \
                patch.object(fs, "flush_directory"), \
                patch.object(fs.secure_os, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1)), \
                patch.object(fs, "_open_handle", side_effect=[202, 101]), \
                patch.object(fs, "_information", return_value=SimpleNamespace()), \
                patch.object(fs, "_metadata", side_effect=metadata), patch.object(fs, "_close") as closing, \
                patch.object(fs, "_copy_permissions") as copying, patch.object(fs, "_rename_handle") as moving:
            with self.assertRaisesRegex(ValueError, "owner"):
                fs.secure_os._rename(source, target, True)
            copying.assert_not_called()
            moving.assert_not_called()
            self.assertEqual([((101,), {}), ((202,), {})], closing.call_args_list)

    def test_already_exact_security_is_renamed_without_any_permission_copy(self):
        destination = SimpleNamespace(handle=1, child=lambda name: Path("/owned") / name)
        metadata = lambda handle: ((7, handle, stat.S_IFREG | 0o666, 1, 8, 10, 20), "a" * 64)
        with patch.object(fs, "Directory", side_effect=lambda path: nullcontext(destination)), \
                patch.object(fs, "flush_directory"), \
                patch.object(fs.secure_os, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_nlink=1)), \
                patch.object(fs, "_open_handle", side_effect=[202, 101]), \
                patch.object(fs, "_information", return_value=SimpleNamespace()), \
                patch.object(fs, "_metadata", side_effect=metadata), patch.object(fs, "_close"), \
                patch.object(fs, "_copy_permissions", side_effect=AssertionError("exact initial SD must not be reset")), \
                patch.object(fs, "_rename_handle") as moving:
            fs.secure_os._rename(Path("/owned/stage"), Path("/owned/target"), True)
            moving.assert_called_once_with(202, destination, "target", replace=True)


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


class WindowsCreatedSkillPolicyContractTest(unittest.TestCase):
    """仅证明新链接的权限写入顺序/拒绝边界；真实 ACL 结果另由原生两布局核对。"""

    USER = bytes.fromhex("010100000000000515000000")
    SYSTEM = bytes.fromhex("010100000000000512000000")
    ADMINS = bytes.fromhex("01020000000000052000000020020000")

    def policy(self, *, owner=None, protected=False, flags=0x13):
        entries = b"".join(bytes((0, flags)) + (8 + len(sid)).to_bytes(2, "little")
                           + (0x1F01FF).to_bytes(4, "little") + sid for sid in (self.USER, self.SYSTEM))
        acl = (bytes((2, 0)) + (8 + len(entries)).to_bytes(2, "little") + b"\2\0\0\0" + entries)
        return SimpleNamespace(owner=owner or self.USER, control=0x1004 if protected else 4,
                               acl_bytes=acl, fingerprint="a" * 64 if not protected else "b" * 64)

    @contextmanager
    def creation(self, *, owner=None, elevated=False, snapshots=None, policies=None):
        """不模拟成功的文件系统：替身只捕获真实创建函数将提交的 Win32 调用。"""
        core = PureWindowsPath("C:/owned/runtimes/" + "a" * 64 + "/core")
        target, path = core / "platforms/shared/skills/grill-me", PureWindowsPath("C:/owned/stage/grill-me")
        expected = {"kind": "link", "payload": fs._os.fsencode(target), "mode": 0o777,
                    "identity": (1, 2, stat.S_IFLNK | 0o777, 1, 0, 5, 6), "security": "a" * 64}
        after = dict(expected, identity=expected["identity"][:6] + (7,), security="b" * 64)
        assign = owner == self.ADMINS and elevated
        observed = Mock(side_effect=snapshots if snapshots is not None else [expected] * (2 if assign else 1) + [after])
        values = iter(policies if policies is not None else [self.policy(owner=owner), self.policy(protected=True, flags=0)])
        def owner_pointer(descriptor, pointer, defaulted):
            ctypes.cast(pointer, ctypes.POINTER(fs.HANDLE))[0] = fs.HANDLE(66)
            return True
        written, opened, closed = Mock(return_value=0), Mock(return_value=123), Mock()
        kernel = SimpleNamespace(CreateSymbolicLinkW=Mock(return_value=1))
        api = SimpleNamespace(kernel=kernel, security=SimpleNamespace(
            SetSecurityInfo=written, GetSecurityDescriptorOwner=Mock(side_effect=owner_pointer)))
        with ExitStack() as stack:
            replacements = {"_api": Mock(return_value=api), "_skill_target": Mock(return_value=target),
                            "absolute_path": Mock(return_value=core),
                            "Directory": Mock(side_effect=lambda value: nullcontext()),
                            "flush_directory": Mock(), "read_skill_symlink": Mock(return_value=expected),
                            "_open_skill_handle": opened, "_opened_snapshot": observed, "_close": closed,
                            "_security_policy": Mock(side_effect=lambda handle: nullcontext(next(values))),
                            "current_sid": Mock(return_value="user"),
                            "_sid_bytes": Mock(side_effect=lambda sid: self.USER if sid == "user" else self.ADMINS),
                            "_token_elevated": Mock(return_value=elevated),
                            "private_security": Mock(side_effect=lambda **kwargs: nullcontext(88)),
                            "_dacl": Mock(return_value=99)}
            for name, replacement in replacements.items():
                stack.enter_context(patch.object(fs, name, replacement))
            stack.enter_context(patch.object(fs.secure_os, "_path", return_value=path))
            yield SimpleNamespace(core=core, target=target, path=path, expected=expected, after=after,
                                  written=written, opened=opened, closed=closed, observed=observed,
                                  api=api, replacements=replacements)

    def test_creation_fixes_only_new_link_before_return_and_refuses_existing_collision(self):
        with self.creation() as fixture:
            fs.create_skill_symlink(11, "grill-me", fixture.target, core_root=fixture.core)
            fixture.written.assert_called_once_with(123, 1, 0x80000004, None, None, 99, None)
            fixture.opened.assert_called_once_with(fixture.path, 0x60080)
            fixture.replacements["private_security"].assert_called_once_with(inherit=False)
            self.assertEqual(fixture.observed.call_count, 2)
            fixture.closed.assert_called_once_with(123)
        with self.creation() as fixture:
            fixture.api.kernel.CreateSymbolicLinkW.side_effect = FileExistsError("owned collision")
            with self.assertRaises(FileExistsError):
                fs.create_skill_symlink(11, "grill-me", fixture.target, core_root=fixture.core)
            fixture.written.assert_not_called()
            fixture.opened.assert_not_called()
            fixture.replacements["read_skill_symlink"].assert_not_called()

    def test_creation_checks_owner_and_full_snapshot_before_any_permission_write(self):
        for owner, elevated in ((b"unknown-owner", True), (self.ADMINS, False)):
            with self.subTest(owner=owner, elevated=elevated), self.creation(owner=owner, elevated=elevated) as fixture:
                with self.assertRaisesRegex(ValueError, "unknown or non-elevated foreign owner"):
                    fs.create_skill_symlink(11, "grill-me", fixture.target, core_root=fixture.core)
                fixture.written.assert_not_called()
                fixture.opened.assert_called_once_with(fixture.path, 0x60080)
                fixture.closed.assert_called_once_with(123)
        with self.creation(owner=self.ADMINS, elevated=True) as fixture:
            fs.create_skill_symlink(11, "grill-me", fixture.target, core_root=fixture.core)
            self.assertEqual(fixture.opened.call_args_list,
                             [((fixture.path, 0x60080), {}), ((fixture.path, 0xE0080), {})])
            self.assertEqual(fixture.written.call_count, 1)
            args = fixture.written.call_args.args
            self.assertEqual(args[:3], (123, 1, 0x80000005))
            self.assertEqual(args[3].value, 66)
            self.assertEqual(args[4:], (None, 99, None))
            self.assertEqual(fixture.observed.call_count, 3)
            self.assertEqual(fixture.closed.call_count, 2)
        # 首次开句柄或提权重开后，inode/目标/mode/ACL 任一变化都不能写。
        for reopened in (False, True):
            for field in ("identity", "payload", "mode", "security"):
                options = {"owner": self.ADMINS, "elevated": True} if reopened else {}
                with self.subTest(reopened=reopened, field=field), self.creation(**options) as fixture:
                    changed = dict(fixture.expected)
                    changed[field] = {"identity": (1, 99) + fixture.expected["identity"][2:],
                                      "payload": b"another-central-target", "mode": 0o555,
                                      "security": "c" * 64}[field]
                    fixture.observed.side_effect = [fixture.expected, changed] if reopened else [changed]
                    with self.assertRaisesRegex(ValueError, "changed"):
                        fs.create_skill_symlink(11, "grill-me", fixture.target, core_root=fixture.core)
                    fixture.written.assert_not_called()
        with self.creation(policies=[SimpleNamespace(owner=self.USER, fingerprint="c" * 64)]) as fixture:
            with self.assertRaisesRegex(ValueError, "permissions changed"):
                fs.create_skill_symlink(11, "grill-me", fixture.target, core_root=fixture.core)
            fixture.written.assert_not_called()

    def test_leaf_descriptor_and_postcondition_keep_owner_protection_flags_and_target_strict(self):
        # 执行实际 SDDL 生成器，明确默认目录仍 OI/CI、链接精确 flags=0。
        texts = []
        def convert(text, revision, pointer, size):
            texts.append(text)
            ctypes.cast(pointer, ctypes.POINTER(fs.HANDLE))[0] = fs.HANDLE(88)
            return True
        api = SimpleNamespace(security=SimpleNamespace(ConvertStringSecurityDescriptorToSecurityDescriptorW=convert),
                              kernel=SimpleNamespace(LocalFree=Mock()))
        with patch.object(fs, "_api", return_value=api), patch.object(fs, "current_sid", return_value="user"):
            with fs.private_security():
                pass
            with fs.private_security(inherit=False):
                pass
        self.assertEqual(texts, ["O:userD:P(A;OICI;GA;;;user)(A;OICI;GA;;;SY)",
                                 "O:userD:P(A;;GA;;;user)(A;;GA;;;SY)"])
        self.assertEqual(api.kernel.LocalFree.call_count, 2)
        for label, policy in (("wrong-owner", self.policy(owner=self.ADMINS, protected=True, flags=0)),
                              ("unprotected", self.policy(flags=0)),
                              ("inheritable", self.policy(protected=True, flags=3)),
                              ("inherited", self.policy(protected=True, flags=0x13))):
            with self.subTest(post=label), self.creation(policies=[self.policy(), policy]) as fixture:
                with self.assertRaisesRegex(ValueError, "postcondition|inheritable"):
                    fs.create_skill_symlink(11, "grill-me", fixture.target, core_root=fixture.core)
                self.assertEqual(fixture.written.call_count, 1)
                fixture.closed.assert_called_once_with(123)
        for field in ("identity", "payload", "mode", "security"):
            with self.subTest(after_write=field), self.creation() as fixture:
                changed = dict(fixture.after)
                changed[field] = {"identity": (1, 99) + fixture.after["identity"][2:],
                                  "payload": b"another-central-target", "mode": 0o555,
                                  "security": "c" * 64}[field]
                fixture.observed.side_effect = [fixture.expected, changed]
                with self.assertRaisesRegex(ValueError, "changed during initialization"):
                    fs.create_skill_symlink(11, "grill-me", fixture.target, core_root=fixture.core)
                fixture.closed.assert_called_once_with(123)


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
