"""在真实临时文件系统验证中央内容库，不触碰任何真实项目或全局宿主资源。"""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
from contextlib import contextmanager
import shutil
import stat
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
import unittest
from unittest.mock import patch

from lib import runtime_store as store


PACK = Path(__file__).resolve().parents[1]
PYTHON = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8"]


class RuntimeStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runtime-store-")
        self.addCleanup(self.temporary.cleanup)
        # macOS 的系统 /var 别名先在夹具所有者边界解析，测试传给库的都是实际目录。
        self.workspace = Path(self.temporary.name).resolve()
        self.source = self.workspace / "旧 keg 源包"
        self.state = self.workspace / "machine-state"
        self.make_source(self.source)

    def write(self, relative, body=b"fixture\n", *, source=None, executable=False):
        target = (source or self.source) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        target.chmod(0o755 if executable else 0o644)
        return target

    def make_source(self, root):
        # 仅生成独立最小核心，而不 clone/复制整份候选源码。通用模板与真实配置故意不同。
        for name in store.CORE_DIRECTORIES:
            (root / name).mkdir(parents=True, exist_ok=True)
        for name in store.SETUP_FILES:
            self.write(name, b"#!/bin/sh\nexit 0\n", source=root, executable=True)
        self.write("product/WORKFLOW.md", "# 通用工作流\n".encode(), source=root)
        self.write("product/ROLES.yaml", b"roles: {}\n", source=root)
        self.write("roles/xy-backend.md", b"# backend\n", source=root)
        self.write("platforms/shared/core-skills.txt", b"xy-code-standards\n", source=root)
        self.write("lib/probe.py", b'print("frozen core runs")\n', source=root)
        self.write("lib/python_runtime.sh", (PACK / "lib/python_runtime.sh").read_bytes(),
                   source=root, executable=True)
        self.write("scripts/scaffold_project_docs.sh", b"#!/bin/sh\nexit 0\n", source=root, executable=True)
        self.write("templates/project.yaml.example", b"project_name: Template\n", source=root)
        self.write("templates/docs/PROJECT.md", b"# {{PROJECT_NAME}}\n", source=root)
        self.write("manager/__init__.py", b'"""minimal manager"""\n', source=root)

    def imported(self):
        return store.import_core(self.source, self.state)

    def rewrite_readonly(self, path, body):
        # 这里只主动篡改夹具，用于证明只读防误写不等于同用户攻击防护。
        path.chmod(0o600)
        path.write_bytes(body)
        path.chmod(0o444)

    def test_operation_unifies_load_batch_and_builtin_catalog_then_expires(self):
        """真实catalog也借同一次完整证明；租约不把正文或活跃reader带入下一次调用。"""
        from lib import runtime_pins
        for relative in runtime_pins.BUILTIN_STANDARD_SOURCES:
            self.write(relative, b"# builtin fixture\n")
        core = self.imported()
        project = self.workspace / "project"
        project.mkdir()
        environment = {"AGENT_WORKFLOW_STATE_DIR": str(self.state),
                       "AGENT_WORKFLOW_PROJECT_ROOT": str(project),
                       "AGENT_WORKFLOW_CORE_ROOT": str(core.root),
                       "AGENT_WORKFLOW_CONFIG_PATH": str(project / ".agent-workflow/project.yaml")}
        with patch.dict(os.environ, environment), \
                patch.object(store, "_scan", wraps=store._scan) as scan, \
                patch.object(store, "_verify_snapshot", wraps=store._verify_snapshot) as verify:
            with store.core_read_operation() as operation:
                self.assertEqual(core, store.load_core(core.binding(), self.state))
                with store.core_reader(core.binding(), self.state) as reader:
                    self.assertEqual(core, reader.core)
                    expected = reader.read(core, "roles/xy-backend.md")
                self.assertEqual(expected, store.read_core_source(core, "roles/xy-backend.md"))
                self.assertEqual(expected, store.read_core_sources(core, ("roles/xy-backend.md",))["roles/xy-backend.md"])
                self.assertEqual(set(runtime_pins.BUILTIN_STANDARD_SOURCES), set(runtime_pins.read_builtin_sources(core.binding())))
            self.assertEqual((1, 2), (scan.call_count, verify.call_count))
            with self.assertRaises(store.RuntimeStoreError):
                reader.read(core, "roles/xy-backend.md")
            with self.assertRaises(store.RuntimeStoreError):
                operation.checkpoint()
            store.load_core(core.binding(), self.state)
            self.assertEqual(2, scan.call_count, "下一次调用必须完整fresh，不能借已关闭的证明")

    def test_windows_literal_roots_do_not_alias_operation_or_core_locators(self):
        """执行实际租约/单批读方法的Windows词法分支；不是NTFS/ACL原生证据。"""
        class WinLex(PureWindowsPath):
            def absolute(self):return self
            def expanduser(self):return self
        roots = (WinLex("C:/case/State"), WinLex("C:/case/state"))
        binding = {"protocol_version": 1, "content_id": "a" * 64, "manifest_sha256": "a" * 64}
        cores = tuple(store.FrozenCore("a" * 64, "a" * 64, root / "runtimes" / ("a" * 64) / "core", "source")
                      for root in roots)
        # 默认dataclass/WindowsPath相等仍存在，授权方法必须自行拒绝错根。
        self.assertEqual(roots[0], roots[1])
        self.assertEqual(cores[0], cores[1])
        opened = []
        @contextmanager
        def independent(selected, root):
            opened.append(str(root))
            index = 0 if str(root) == str(roots[0]) else 1
            reader = store.CoreReadSession(cores[index], index + 100, {"files": [{"path": "roles/a.md", "size": 1}]},
                                           {"roles/a.md": ()})
            try:yield reader
            finally:reader._close()
        def member(root, *args, **kwargs):
            return b"A" if root == 100 else b"B"
        with patch.object(store, "Path", WinLex), \
                patch.object(store, "state_root", side_effect=lambda root=None: root), \
                patch.object(store, "_independent_core_reader", side_effect=independent), \
                patch.object(store, "_read_manifest_source", side_effect=member) as members:
            with store.core_read_operation() as operation:
                first = operation.reader(binding, roots[0])
                second = operation.reader(binding, roots[1])
                with self.subTest(boundary="operation-key"):
                    self.assertIsNot(first, second)
                    self.assertEqual(list(map(str, roots)), opened)
                with self.subTest(boundary="correct-second-reader"):
                    self.assertEqual(b"B", second.read(cores[1], "roles/a.md"))
                with self.subTest(boundary="session-core-for"), self.assertRaises(store.RuntimeStoreError):
                    first.core_for(binding, roots[1])
                with self.subTest(boundary="session-read"), self.assertRaises(store.RuntimeStoreError):
                    first.read(cores[1], "roles/a.md")
                # 独立验证成员/批读的定位守卫：即使上层错误交来第一reader，
                # 仍不可依赖FrozenCore折叠相等消费它，且不得先读正文再拒绝。
                consumed = members.call_count
                with patch.object(operation, "reader", return_value=first):
                    with self.subTest(boundary="single-read"), self.assertRaises(store.RuntimeStoreError):
                        store.read_core_source(cores[1], "roles/a.md")
                    with self.subTest(boundary="batch-read"), self.assertRaises(store.RuntimeStoreError):
                        store.read_core_sources(cores[1], ("roles/a.md",))
                with self.subTest(boundary="no-foreign-consumption"):
                    self.assertEqual(consumed, members.call_count)
                self.assertIs(first, operation.reader(binding, roots[0]))
                self.assertIs(second, operation.reader(binding, roots[1]))
                with self.subTest(boundary="same-literal-reuse"):
                    self.assertEqual(2, len(opened))

    def test_operation_checkpoint_rejects_unread_member_and_ancestor_drift(self):
        """checkpoint包含整树与祖先路径见证，不能只检查已读成员或打开的旧fd。"""
        core = self.imported()
        target = core.root / "product/ROLES.yaml"
        body, mode = target.read_bytes(), stat.S_IMODE(target.stat().st_mode)
        try:
            with self.assertRaises(store.RuntimeStoreError), store.core_read_operation() as operation:
                store.read_core_source(core, "roles/xy-backend.md")
                target.chmod(mode | 0o600)
                target.write_bytes(body + b"changed\n")
                target.chmod(mode)
                operation.checkpoint()
        finally:
            target.chmod(mode | 0o600)
            target.write_bytes(body)
            target.chmod(mode)
        moved = self.workspace / "moved-state"
        if store.os.name == "nt":
            # Windows祖先句柄不共享DELETE，实际换名会先被内核阻止。先在无
            # reader时完成换名正控，证明不是fixture本来无权移动；持租约时
            # 必须出现sharing/access拒绝，并保持原树可完整checkpoint。
            self.state.rename(moved)
            moved.rename(self.state)
            with store.core_read_operation() as operation:
                store.load_core(core.binding(), self.state)
                with self.assertRaises(OSError) as failure:
                    self.state.rename(moved)
                self.assertIn(failure.exception.winerror, (5, 32))
                self.assertFalse(moved.exists())
                operation.checkpoint()
            return
        try:
            with self.assertRaises(store.RuntimeStoreError), store.core_read_operation() as operation:
                store.load_core(core.binding(), self.state)
                self.state.rename(moved)
                self.state.mkdir()
                operation.checkpoint()
        finally:
            if moved.exists():
                self.state.rmdir()
                moved.rename(self.state)

    def test_operation_isolates_roots_pins_threads_processes_and_module_aliases(self):
        """同一pin不能跨机器根借证明；错误归属拒绝，封口之后不能静默fresh回退。"""
        core = self.imported()
        second_state = self.workspace / "second-state"
        same_pin_other_root = store.import_core(self.source, second_state)
        self.write("roles/xy-backend.md", b"# different version\n")
        other_pin = self.imported()
        with patch.object(store, "_scan", wraps=store._scan) as scan:
            with store.core_read_operation() as operation:
                with store.core_reader(core.binding(), self.state) as reader:
                    store.load_core(same_pin_other_root.binding(), second_state)
                    store.load_core(other_pin.binding(), self.state)
                    self.assertEqual(3, scan.call_count)
                    for binding, root in ((core.binding(), second_state), (other_pin.binding(), self.state)):
                        with self.assertRaises(store.RuntimeStoreError):
                            reader.core_for(binding, root)
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with self.assertRaises(store.RuntimeStoreError):
                            pool.submit(operation.checkpoint).result()
                        with self.assertRaises(store.RuntimeStoreError):
                            pool.submit(reader.read, core, "roles/xy-backend.md").result()
                    actual_pid = store.os.getpid()
                    with patch.object(store.os, "getpid", return_value=actual_pid + 1):
                        with self.assertRaises(store.RuntimeStoreError):
                            operation.checkpoint()
                        with self.assertRaises(store.RuntimeStoreError):
                            reader.read(core, "roles/xy-backend.md")
                    with patch.dict(sys.modules, {"runtime_store": ModuleType("conflicting_store")}):
                        with self.assertRaisesRegex(store.RuntimeStoreError, "别名"):
                            store.load_core(core.binding(), self.state)
                    with patch.dict(sys.modules, {"lib.runtime_store": ModuleType("canonical_replacement")}):
                        with self.assertRaisesRegex(store.RuntimeStoreError, "别名"):
                            store.load_core(core.binding(), self.state)
                        with self.assertRaisesRegex(store.RuntimeStoreError, "别名"):
                            reader.read(core, "roles/xy-backend.md")
                operation.finish()
                with self.assertRaises(store.RuntimeStoreError):
                    store.load_core(core.binding(), self.state)
            self.assertEqual(3, scan.call_count, "拒绝案例和封口后的读取不能重新打开其它证明")

    def test_operation_checkpoint_keeps_manifest_version_mode_and_member_guards(self):
        """逐个真实变更后独立开新基线，不以mock校验器或同字节缓存当安全证据。"""
        core = self.imported()
        for relative, directory in (("manifest.json", False), ("core/product/ROLES.yaml", False), ("core/roles", True)):
            if directory and store.os.name == "nt":
                # Win32目录没有可用的POSIX可写位反例；下面独立改变真实ACL，
                # 不能把chmod无效果或Mac上的mode检查冒充Windows权限证据。
                continue
            path = core.root.parent / relative
            mode = stat.S_IMODE(path.stat().st_mode)
            body = None if directory else path.read_bytes()
            try:
                with self.subTest(path=relative), self.assertRaises(store.RuntimeStoreError), store.core_read_operation() as operation:
                    store.load_core(core.binding(), self.state)
                    if directory:
                        path.chmod(mode ^ 0o200)
                    else:
                        path.chmod(mode | 0o600)
                        path.write_bytes(body + b" ")
                        path.chmod(mode)
                    operation.checkpoint()
            finally:
                path.chmod(mode | 0o600)
                if body is not None:
                    path.write_bytes(body)
                path.chmod(mode)
        version = core.root.parent
        mode = stat.S_IMODE(version.stat().st_mode)
        extra = version / "unexpected"
        try:
            with self.assertRaises(store.RuntimeStoreError), store.core_read_operation() as operation:
                store.load_core(core.binding(), self.state)
                version.chmod(mode | 0o200)
                extra.write_bytes(b"unknown node")
                version.chmod(mode)
                operation.checkpoint()
        finally:
            version.chmod(mode | 0o200)
            extra.unlink(missing_ok=True)
            version.chmod(mode)

        if store.os.name == "nt":
            from lib import windows_fs as fs
            path = core.root / "product/ROLES.yaml"
            # 这次不读取所改成员，只由完整checkpoint发现ACL变化。
            with self.assertRaises(store.RuntimeStoreError), store.core_read_operation() as operation:
                store.load_core(core.binding(), self.state)
                handle = fs._open_handle(path, 0x60080)
                try:
                    with fs._security_policy(handle) as before:
                        try:
                            with fs.private_security(inherit=not bool(before.acl_bytes[9] & 3)) as descriptor:
                                self.assertEqual(0, fs._api().security.SetSecurityInfo(
                                    handle, 1, 0x80000004, None, None, fs._dacl(descriptor), None))
                            with fs._security_policy(handle) as after:
                                self.assertNotEqual(before.fingerprint, after.fingerprint)
                            operation.checkpoint()
                        finally:
                            self.assertEqual(0, fs._api().security.SetSecurityInfo(
                                handle, 1, 0x80000004, None, None, before.acl, None))
                finally:
                    fs._close(handle)

    def test_batch_core_sources_preserves_members_source_and_complete_snapshot_guards(self):
        """实际批读仍是完整核心/成员合同，不能靠已加载定位值或上一轮字节缓存。"""
        core = self.imported()
        paths = ("roles/xy-backend.md", "product/WORKFLOW.md")
        expected = {path: store.read_core_source(core, path) for path in paths}
        with patch.object(store, "_validated_entry", wraps=store._validated_entry) as validated:
            self.assertEqual(expected, store.read_core_sources(core, paths))
        self.assertEqual(1, validated.call_count)
        for invalid in ((), list(paths), paths * 5, ("../roles/xy-backend.md",),
                        (paths[0], ".agent-workflow/" + paths[0]), ("roles/missing.md",)):
            with self.subTest(paths=invalid), self.assertRaises(store.RuntimeStoreError):
                store.read_core_sources(core, invalid)
        for wrong in (self.source, replace(core, root=self.source), replace(core, label="wrong-label")):
            with self.subTest(source=type(wrong).__name__), self.assertRaises(store.RuntimeStoreError):
                store.read_core_sources(wrong, paths)
        with patch.object(store, "_SOURCE_BATCH_BYTES_LIMIT", 1), self.assertRaisesRegex(store.RuntimeStoreError, "总正文"):
            store.read_core_sources(core, paths)
        def write_owned(path, body, mode):
            # 仅为自有核心负控制造篡改；还原实际原 mode，兼容私有 Windows
            # 与 POSIX 只读冻结文件，不通过生产 API 放宽或修复任何 ACL。
            path.chmod(mode | 0o600)
            path.write_bytes(body)
            path.chmod(mode)
        for relative in (paths[0], "product/ROLES.yaml"):
            path = core.root / relative
            body, mode = path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
            try:
                write_owned(path, body + b"tampered", mode)
                with self.subTest(tampered=relative), self.assertRaises(store.RuntimeStoreError):
                    store.read_core_sources(core, paths)
            finally:
                write_owned(path, body, mode)
        other = core.root / "product/ROLES.yaml"
        body, mode = other.read_bytes(), stat.S_IMODE(other.stat().st_mode)
        original_read, changed = store._read_regular, False
        def change_after_selected_read(parent, name, **options):
            nonlocal changed
            result = original_read(parent, name, **options)
            if name == "xy-backend.md" and options.get("expected") is None and not changed:
                changed = True
                write_owned(other, body + b"late mutation", mode)
            return result
        try:
            with patch.object(store, "_read_regular", side_effect=change_after_selected_read), \
                    self.assertRaisesRegex(store.RuntimeStoreError, "快照"):
                store.read_core_sources(core, paths)
            self.assertTrue(changed, "must mutate after selected read, before final whole-core snapshot check")
        finally:
            write_owned(other, body, mode)

    def test_explicit_core_reader_is_scoped_fresh_and_rejects_wrong_core_or_member(self):
        """真实源/冻结树上核对活跃范围、每次成员读取及独立调用；不是正文缓存。"""
        core = self.imported()
        logical = "roles/xy-backend.md"
        expected = (core.root / logical).read_bytes()
        with patch.object(store, "_scan", wraps=store._scan) as scans, \
                patch.object(store, "_read_manifest_source", wraps=store._read_manifest_source) as members:
            with store.core_reader(core.binding(), self.state) as reader:
                self.assertEqual(core, reader.core_for(core.binding(), self.state))
                self.assertEqual(expected, reader.read(core, logical))
                self.assertEqual(expected, reader.read(core, ".agent-workflow/" + logical))
                self.assertEqual(2, members.call_count, "each member must reopen and verify, never reuse cached bytes")
                for wrong in (replace(core, label="foreign"), replace(core, root=self.source)):
                    with self.subTest(core=wrong.root), self.assertRaises(store.RuntimeStoreError):
                        reader.read(wrong, logical)
                for unknown in ("roles/unknown.md", "../roles/xy-backend.md"):
                    with self.subTest(path=unknown), self.assertRaises(store.RuntimeStoreError):
                        reader.read(core, unknown)
                with self.assertRaises(store.RuntimeStoreError):
                    reader.core_for(core.binding(), self.workspace / "other-state")
            self.assertEqual(1, scans.call_count)
            with self.assertRaisesRegex(store.RuntimeStoreError, "关闭"):
                reader.read(core, logical)
            with store.core_reader(core.binding(), self.state) as next_reader:
                self.assertEqual(expected, next_reader.read(core, logical))
            self.assertEqual(2, scans.call_count, "a new operation must perform a new complete scan")
        # 同字节重写、所选/未选正文变动都不能在同一会话中追认成新见证。
        for relative, same_bytes in ((logical, True), (logical, False), ("product/ROLES.yaml", False)):
            path = core.root / relative
            original, mode = path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
            try:
                with self.subTest(changed=relative, same_bytes=same_bytes), self.assertRaises(store.RuntimeStoreError):
                    with store.core_reader(core.binding(), self.state) as active:
                        path.chmod(mode | 0o600)
                        path.write_bytes(original if same_bytes else original + b"tamper")
                        path.chmod(mode)
                        active.read(core, logical)
            finally:
                path.chmod(mode | 0o600)
                path.write_bytes(original)
                path.chmod(mode)
        # manifest 也属于本次权限/身份闭包；不能在进入reader后同字节重写，
        # 或在版本目录加清单外叶子，再靠正常core成员读取获得成功。
        manifest = core.root.parent / "manifest.json"
        raw, mode = manifest.read_bytes(), stat.S_IMODE(manifest.stat().st_mode)
        try:
            with self.assertRaises(store.RuntimeStoreError):
                with store.core_reader(core.binding(), self.state) as active:
                    manifest.chmod(mode | 0o600)
                    manifest.write_bytes(raw)
                    manifest.chmod(mode)
                    active.read(core, logical)
        finally:
            manifest.chmod(mode | 0o600)
            manifest.write_bytes(raw)
            manifest.chmod(mode)
        parent = core.root.parent
        mode = stat.S_IMODE(parent.stat().st_mode)
        extra = parent / ".unknown"
        try:
            with self.assertRaisesRegex(store.RuntimeStoreError, "节点集合"):
                with store.core_reader(core.binding(), self.state) as active:
                    stamp = parent.stat()
                    parent.chmod(mode | 0o700)
                    extra.write_bytes(b"unregistered")
                    os.utime(parent, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    active.read(core, logical)
        finally:
            extra.unlink(missing_ok=True)
            parent.chmod(mode)
        if store.os.name == "nt":
            # Windows 的独立 ACL 见证必须参与即时成员拒绝；同用户仅改自有
            # fixture 文件的 ACE flags，再用原 SD 恢复，不依赖 ChangeTime。
            from lib import windows_fs as fs
            path = core.root / logical
            with self.assertRaises(store.RuntimeStoreError):
                with store.core_reader(core.binding(), self.state) as active:
                    handle = fs._open_handle(path, 0x60080)
                    try:
                        with fs._security_policy(handle) as before:
                            try:
                                with fs.private_security(inherit=not bool(before.acl_bytes[9] & 3)) as descriptor:
                                    error = fs._api().security.SetSecurityInfo(handle, 1, 0x80000004,
                                                                             None, None, fs._dacl(descriptor), None)
                                    self.assertEqual(0, error)
                                with fs._security_policy(handle) as after:
                                    self.assertNotEqual(before.fingerprint, after.fingerprint)
                                with self.assertRaises(store.RuntimeStoreError):
                                    active.read(core, logical)
                            finally:
                                error = fs._api().security.SetSecurityInfo(handle, 1, 0x80000004,
                                                                         None, None, before.acl, None)
                                self.assertEqual(0, error)
                    finally:
                        fs._close(handle)

    def test_recursive_snapshot_rejects_unknown_members_and_directory_exchange(self):
        """目录句柄复用仍逐成员核验，未知节点不靠可重置mtime判断，源过滤不扩张。"""
        core = self.imported()
        with store._absolute_directory(core.root) as root:
            _, _, snapshot = store._scan(root, source=False)
            parent = core.root / "product"
            mode, stamp = stat.S_IMODE(parent.stat().st_mode), parent.stat()
            extra = parent / ".unknown"
            try:
                parent.chmod(mode | 0o700)
                extra.write_bytes(b"unregistered")
                os.utime(parent, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                with self.assertRaisesRegex(store.RuntimeStoreError, "成员集合"):
                    store._verify_snapshot(root, snapshot)
            finally:
                extra.unlink()
                parent.chmod(mode)
        # 源允许未管理正文，但既有 source 忽略规则不能允许链接或换过的祖先。
        self.write("lib/__pycache__/owned.pyc", b"ignored owned cache")
        with store._absolute_directory(self.source) as root:
            _, _, snapshot = store._scan(root, source=True)
            store._verify_snapshot(root, snapshot, source=True)
            original_open, changed = store.os.open, False
            def exchange(name, flags, *args, **options):
                nonlocal changed
                if name == "roles" and not changed:
                    changed = True
                    os.rename(self.source / "roles", self.source / "owned-previous-roles")
                    shutil.copytree(self.source / "owned-previous-roles", self.source / "roles")
                return original_open(name, flags, *args, **options)
            with patch.object(store.os, "open", side_effect=exchange), self.assertRaises((OSError, store.RuntimeStoreError)):
                store._verify_snapshot(root, snapshot, source=True)
            self.assertTrue(changed)

    def test_import_load_list_binding_and_detached_runtime(self):
        core = self.imported()
        self.assertIsInstance(core, store.FrozenCore)
        self.assertEqual("source", core.label)
        self.assertEqual(self.state / "runtimes" / core.content_id / "core", core.root)
        self.assertEqual({"protocol_version": 1, "content_id": core.content_id,
                          "manifest_sha256": core.content_id}, core.binding())
        raw = (core.root.parent / "manifest.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), core.content_id)
        manifest = json.loads(raw)
        self.assertEqual(sorted(row["path"] for row in manifest["files"]),
                         [row["path"] for row in manifest["files"]])
        self.assertEqual({"path", "size", "sha256", "executable"}, set(manifest["files"][0]))
        self.assertNotIn(str(self.source).encode(), raw)
        with self.assertRaises(FrozenInstanceError):
            core.label = "changed"
        # 删除模拟旧 Homebrew keg 后，读取与真正的 Python 入口仍只依赖中央快照。
        shutil.rmtree(self.source)
        self.assertEqual(core, store.load_core(core.binding(), self.state))
        expected = "# 通用工作流\n".encode()
        self.assertEqual(expected, store.read_core_source(core, "product/WORKFLOW.md"))
        self.assertEqual(expected, store.read_core_source(core, ".agent-workflow/product/WORKFLOW.md"))
        self.assertEqual([{**core.binding(), "root": str(core.root), "label": "source"}],
                         store.list_cores(self.state))
        result = subprocess.run(["bash", str(core.root / "lib/python_runtime.sh"),
                                 "-B", "-X", "utf8", str(core.root / "lib/probe.py")],
                                cwd=self.workspace, capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("frozen core runs\n", result.stdout)

    def test_reproducible_content_ignores_source_root_and_unmanaged_settings(self):
        self.write("project.yaml", b"role_models: secret project setting\n")
        self.write("docs/PROJECT.md", b"private project document\n")
        self.write("tests/test_private.py", b"private test\n")
        self.write(".git/config", b"private git configuration\n")
        self.write(".claude/settings.json", b"private permissions and MCP\n")
        self.write("lib/windows-runtime.paths", b"private local interpreter\n")
        self.write("lib/__pycache__/probe.pyc", b"cache\n")
        self.write("scripts/test_codex.sh", b"private test launcher\n")
        original = self.imported()
        other_source = self.workspace / "another physical source"
        self.make_source(other_source)
        second = store.import_core(other_source, self.state)
        self.assertEqual(original, second)
        for relative in ("project.yaml", "docs/PROJECT.md", "tests/test_private.py", ".git/config",
                         ".claude/settings.json", "lib/windows-runtime.paths",
                         "lib/__pycache__/probe.pyc", "scripts/test_codex.sh"):
            self.assertFalse((original.root / relative).exists(), relative)
            with self.assertRaises(store.RuntimeStoreError):
                store.read_core_source(original, relative)
        self.assertEqual(b"project_name: Template\n",
                         store.read_core_source(original, "templates/project.yaml.example"))

    def test_multiple_versions_retained_and_unknown_pin_never_falls_back(self):
        original = self.imported()
        self.write("product/WORKFLOW.md", b"new workflow\n")
        new = self.imported()
        self.assertNotEqual(original.content_id, new.content_id)
        self.assertEqual({original.content_id, new.content_id},
                         {row["content_id"] for row in store.list_cores(self.state)})
        self.assertEqual("# 通用工作流\n".encode(), store.read_core_source(original, "product/WORKFLOW.md"))
        self.assertEqual(b"new workflow\n", store.read_core_source(new, "product/WORKFLOW.md"))
        missing = {"protocol_version": 1, "content_id": "0" * 64, "manifest_sha256": "0" * 64}
        with self.assertRaisesRegex(store.RuntimeStoreError, "缺失"):
            store.load_core(missing, self.state)
        self.assertTrue(original.root.is_dir())

    def test_release_label_only_comes_from_frozen_release_metadata(self):
        self.write("manager/release.json", b'{"schema_version":1,"version":"2.3.4"}\n')
        core = self.imported()
        self.assertEqual("2.3.4", core.label)
        self.assertEqual("2.3.4", store.load_core(core.binding(), self.state).label)
        self.write("manager/release.json", b'{"schema_version":1,"version":"not-a-release"}\n')
        with self.assertRaisesRegex(store.RuntimeStoreError, "发行标签"):
            self.imported()
        self.assertEqual(1, len(store.list_cores(self.state)))

    def test_product_version_is_authority_and_old_frozen_labels_remain_valid(self):
        """新核心以 VERSION 为唯一版本源；既有缺 VERSION 的 pin 标签不能被重标。"""
        old = self.imported()
        self.write("product/VERSION", b"2.1.0\n")
        current = self.imported()
        self.assertEqual("2.1.0", current.label)
        self.assertEqual("source", store.load_core(old.binding(), self.state).label)
        self.write("manager/release.json", b'{"schema_version":1,"version":"2.1.0"}\n')
        release = self.imported()
        self.assertEqual("2.1.0", release.label)
        self.write("manager/release.json", b'{"schema_version":1,"version":"2.0.1"}\n')
        with self.assertRaisesRegex(store.RuntimeStoreError, "发行标签"):
            self.imported()
        self.assertEqual("2.1.0", store.load_core(current.binding(), self.state).label)
        self.write("product/VERSION", b"02.1.0\n")
        with self.assertRaisesRegex(store.RuntimeStoreError, "product/VERSION"):
            self.imported()

    def test_version_line_endings_preserve_raw_identity_and_reject_extra_text(self):
        """版本标量容忍一次 Git 文本行尾转换，清单仍固定原字节而非规范化副本。"""
        from manager.release import source_version
        ids = set()
        for raw in (b"2.1.3", b"2.1.3\n", b"2.1.3\r\n"):
            self.write("product/VERSION", raw)
            with self.subTest(reader="release", raw=raw):
                self.assertEqual("2.1.3", source_version(self.source))
            with self.subTest(reader="store", raw=raw):
                core = self.imported()
                self.assertEqual("2.1.3", core.label)
                self.assertEqual("2.1.3", store.load_core(core.binding(), self.state).label)
                self.assertEqual(raw, store.read_core_source(core, "product/VERSION"))
                manifest = json.loads((core.root.parent / "manifest.json").read_bytes())
                row = next(row for row in manifest["files"] if row["path"] == "product/VERSION")
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (row["size"], row["sha256"]))
                ids.add(core.content_id)
        self.assertEqual(3, len(ids), "label normalization must not normalize frozen source bytes")
        # 只能移除一个合法行结束符，不能用 strip/rstrip 接受空白、空行或多行，
        # 也不能把 BOM、bare CR、前导零变成看似有效的发行标签。
        for raw in (b" 2.1.3\n", b"2.1.3 \r\n", b"2.1.3\n\n", b"2.1.3\r\n\r\n",
                    b"2.1.3\n\r\n", b"2.1.3\n2.1.4\n", b"2.1.3\r", b"02.1.3\r\n",
                    b"\xef\xbb\xbf2.1.3\r\n"):
            self.write("product/VERSION", raw)
            with self.subTest(reader="release rejects", raw=raw), self.assertRaises(ValueError):
                source_version(self.source)
            with self.subTest(reader="store rejects", raw=raw), self.assertRaises(store.RuntimeStoreError):
                store.inspect_core(self.source)

    def test_state_resolution_and_empty_listing_are_read_only(self):
        expected = self.workspace / "missing" / "state"
        with patch.dict(os.environ, {"AGENT_WORKFLOW_STATE_DIR": str(expected)}):
            self.assertEqual(expected, store.state_root())
            self.assertEqual([], store.list_cores())
        self.assertFalse(expected.parent.exists())
        self.assertEqual(self.state, store.state_root(self.state))
        for raw in ("", 2):
            with self.subTest(raw=raw), self.assertRaises(store.RuntimeStoreError):
                store.state_root(raw)

    def test_inspection_is_read_only_and_matches_expected_import(self):
        before = sorted(str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*"))
        with patch.dict(os.environ, {"AGENT_WORKFLOW_STATE_DIR": str(self.state)}):
            # 预览即便配置了状态路径也只读源；真实文件读取及摘要计算仍照常执行。
            with patch.object(store.os, "mkdir", side_effect=AssertionError("预览不能创建目录")):
                preview = store.inspect_core(self.source)
        self.assertEqual({"protocol_version", "content_id", "manifest_sha256", "label"}, set(preview))
        self.assertEqual("source", preview["label"])
        self.assertFalse(self.state.exists())
        self.assertEqual(before, sorted(str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*")))
        expected = {key: preview[key] for key in ("protocol_version", "content_id", "manifest_sha256")}
        core = store.import_core(self.source, self.state, expected_binding=expected)
        self.assertEqual(core.binding(), expected)
        self.assertEqual(core.label, preview["label"])

    def test_preview_source_drift_is_rejected_before_creating_state(self):
        preview = store.inspect_core(self.source)
        expected = {key: preview[key] for key in ("protocol_version", "content_id", "manifest_sha256")}
        self.write("product/WORKFLOW.md", b"changed after preview\n")
        with self.assertRaisesRegex(store.RuntimeStoreError, "预览绑定不符"):
            store.import_core(self.source, self.state, expected_binding=expected)
        self.assertFalse(self.state.exists())

    def test_mismatched_preview_does_not_publish_an_unexpected_version(self):
        original = self.imported()
        self.write("lib/probe.py", b'print("unapproved new source")\n')
        with self.assertRaisesRegex(store.RuntimeStoreError, "预览绑定不符"):
            store.import_core(self.source, self.state, expected_binding=original.binding())
        self.assertEqual([original.content_id], [row["content_id"] for row in store.list_cores(self.state)])
        self.assertEqual([], list((self.state / "runtimes").glob(".import-*")))

    def test_binding_is_strict_and_copied(self):
        binding = {"protocol_version": 1, "content_id": "a" * 64, "manifest_sha256": "a" * 64}
        copied = store.validate_binding(binding)
        copied["protocol_version"] = 2
        self.assertEqual(1, binding["protocol_version"])
        invalid = [None, {}, {**binding, "root": "/outside"}, {**binding, "protocol_version": True},
                   {**binding, "protocol_version": 2}, {**binding, "content_id": "../other"},
                   {**binding, "content_id": "A" * 64}, {**binding, "manifest_sha256": "b" * 64}]
        for candidate in invalid:
            with self.subTest(binding=candidate), self.assertRaises(store.RuntimeStoreError):
                store.load_core(candidate, self.state)
        self.assertFalse(self.state.exists())

    def test_logical_paths_cannot_escape_or_use_approximate_aliases(self):
        core = self.imported()
        self.write("outside.txt", b"outside\n", source=self.workspace)
        paths = ["", ".", "..", "../outside.txt", "/etc/passwd", "product//WORKFLOW.md",
                 "product/./WORKFLOW.md", "product/../roles/xy-backend.md", "product/WORKFLOW.md/",
                 r"product\WORKFLOW.md", "C:/outside.txt", "product/WORKFLOW.md\x00",
                 ".agent-workflow-other/product/WORKFLOW.md",
                 ".agent-workflow/.agent-workflow/product/WORKFLOW.md", "project.yaml"]
        for relative in paths:
            with self.subTest(relative=relative), self.assertRaises(store.RuntimeStoreError):
                store.read_core_source(core, relative)
        with self.assertRaises(store.RuntimeStoreError):
            store.read_core_source(replace(core, root=self.workspace), "product/WORKFLOW.md")

    def test_corrupt_existing_id_is_not_rewritten_or_hidden_by_listing(self):
        core = self.imported()
        target = core.root / "product/WORKFLOW.md"
        self.rewrite_readonly(target, b"damaged content\n")
        before = target.read_bytes()
        inode = target.stat().st_ino
        for action in (lambda: store.load_core(core.binding(), self.state),
                       lambda: store.read_core_source(core, "roles/xy-backend.md"),
                       lambda: store.list_cores(self.state), self.imported):
            with self.assertRaises(store.RuntimeStoreError):
                action()
        self.assertEqual(before, target.read_bytes())
        self.assertEqual(inode, target.stat().st_ino)
        self.assertEqual([], list((self.state / "runtimes").glob(".import-*")))

    def test_missing_manifest_does_not_repair_existing_version(self):
        core = self.imported()
        core.root.parent.chmod(0o755)
        (core.root.parent / "manifest.json").unlink()
        core.root.parent.chmod(0o555)
        with self.assertRaises(store.RuntimeStoreError):
            self.imported()
        self.assertFalse((core.root.parent / "manifest.json").exists())

    def test_manifest_digest_and_canonical_bytes_are_both_enforced(self):
        core = self.imported()
        manifest_path = core.root.parent / "manifest.json"
        data = json.loads(manifest_path.read_bytes())
        changed = (json.dumps(data, indent=2) + "\n").encode()
        self.rewrite_readonly(manifest_path, changed)
        with self.assertRaisesRegex(store.RuntimeStoreError, "摘要"):
            store.load_core(core.binding(), self.state)
        # 即使绑定了新原字节摘要，也必须拒绝非协议规定的 JSON 编码。
        identifier = hashlib.sha256(changed).hexdigest()
        new_path = core.root.parent.parent / identifier
        core.root.parent.rename(new_path)
        with self.assertRaisesRegex(store.RuntimeStoreError, "规范排序"):
            store.load_core({"protocol_version": 1, "content_id": identifier,
                             "manifest_sha256": identifier}, self.state)

    def test_extra_empty_directory_is_detected(self):
        core = self.imported()
        core.root.chmod(0o755)
        extra = core.root / "unexpected"
        extra.mkdir(mode=0o555)
        core.root.chmod(0o555)
        with self.assertRaisesRegex(store.RuntimeStoreError, "集合"):
            store.load_core(core.binding(), self.state)

    @unittest.skipIf(os.name == "nt", "POSIX 只读位合同，不把 Windows ACL 冒充 POSIX 模式")
    def test_readonly_and_executable_modes_are_strict(self):
        core = self.imported()
        self.assertEqual(0o444, stat.S_IMODE((core.root / "product/WORKFLOW.md").stat().st_mode))
        self.assertEqual(0o555, stat.S_IMODE((core.root / "setup_all.sh").stat().st_mode))
        self.assertEqual(0o555, stat.S_IMODE(core.root.stat().st_mode))
        (core.root / "product/WORKFLOW.md").chmod(0o644)
        with self.assertRaisesRegex(store.RuntimeStoreError, "模式"):
            store.load_core(core.binding(), self.state)

    @unittest.skipIf(os.name == "nt", "此夹具使用 POSIX 符号链接/硬链接/FIFO，Windows 由既有安全门面负责")
    def test_source_links_hardlinks_and_special_nodes_are_rejected(self):
        target = self.source / "lib/probe.py"
        original = target.read_bytes()
        outside = self.workspace / "external.py"
        outside.write_bytes(b"outside\n")
        for kind in ("symlink", "hardlink", "fifo"):
            with self.subTest(kind=kind):
                target.unlink()
                if kind == "symlink":
                    target.symlink_to(outside)
                elif kind == "hardlink":
                    os.link(outside, target)
                else:
                    os.mkfifo(target)
                with self.assertRaises(store.RuntimeStoreError):
                    self.imported()
                target.unlink()
                target.write_bytes(original)
        self.assertFalse(self.state.exists())
        self.assertEqual(b"outside\n", outside.read_bytes())

    @unittest.skipIf(os.name == "nt", "此夹具使用 POSIX 符号链接，生产入口仍走平台安全门面")
    def test_source_and_state_ancestors_cannot_be_links(self):
        alias = self.workspace / "alias"
        alias.symlink_to(self.workspace, target_is_directory=True)
        with self.assertRaises(store.RuntimeStoreError):
            store.import_core(alias / self.source.name, self.state)
        with self.assertRaises(store.RuntimeStoreError):
            store.import_core(self.source, alias / "escaped-state")
        self.assertFalse((self.workspace / "escaped-state").exists())
        (self.source / "lib/__pycache__").symlink_to(self.workspace, target_is_directory=True)
        with self.assertRaises(store.RuntimeStoreError):
            self.imported()

    @unittest.skipIf(os.name == "nt", "此夹具使用 POSIX 链接，Windows 重解析点由安全门面拒绝")
    def test_published_file_link_and_directory_escape_are_rejected(self):
        core = self.imported()
        target = core.root / "lib/probe.py"
        target.parent.chmod(0o755)
        target.unlink()
        target.symlink_to(self.source / "lib/probe.py")
        target.parent.chmod(0o555)
        with self.assertRaises(store.RuntimeStoreError):
            store.read_core_source(core, "product/WORKFLOW.md")
        target.parent.chmod(0o755)
        target.unlink()
        os.link(self.source / "lib/probe.py", target)
        target.parent.chmod(0o555)
        with self.assertRaises(store.RuntimeStoreError):
            store.load_core(core.binding(), self.state)

    def test_source_change_after_copy_is_rejected_and_stage_is_cleaned(self):
        copier = store._copy_snapshot

        def change_after_copy(*args):
            copier(*args)
            # 写回相同字节也改变节点时间，不能把并发重写当成稳定输入。
            target = self.source / "lib/probe.py"
            target.write_bytes(target.read_bytes())

        with patch.object(store, "_copy_snapshot", side_effect=change_after_copy):
            with self.assertRaisesRegex(store.RuntimeStoreError, "变化"):
                self.imported()
        self.assertEqual([], list((self.state / "runtimes").iterdir()))
        # 失败没有永久占用同 ID；恢复稳定输入后可以正常重新导入。
        self.assertEqual("source", self.imported().label)

    def test_source_set_change_after_copy_is_rejected(self):
        copier = store._copy_snapshot

        def add_after_copy(*args):
            copier(*args)
            self.write("lib/late.py", b"late addition\n")

        with patch.object(store, "_copy_snapshot", side_effect=add_after_copy):
            with self.assertRaisesRegex(store.RuntimeStoreError, "变化"):
                self.imported()
        self.assertEqual([], store.list_cores(self.state))

    def test_cross_process_same_id_publication_is_idempotent(self):
        program = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
            "from lib.runtime_store import import_core; "
            "print(import_core(Path(sys.argv[2]), Path(sys.argv[3])).content_id)"
        )
        processes = [subprocess.Popen([*PYTHON, "-c", program, str(PACK), str(self.source), str(self.state)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(4)]
        identifiers = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(0, process.returncode, stdout + stderr)
                identifiers.append(stdout.strip())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertEqual(1, len(set(identifiers)))
        self.assertEqual(identifiers[0], store.list_cores(self.state)[0]["content_id"])
        self.assertEqual(1, len(list((self.state / "runtimes").iterdir())))
        core = self.imported()
        inode = core.root.stat().st_ino
        self.assertEqual(core, self.imported())
        self.assertEqual(inode, core.root.stat().st_ino)

    def test_publication_failure_cleans_only_this_import_stage(self):
        with patch.object(store, "publish_exclusive", side_effect=OSError("injected publication failure")):
            with self.assertRaisesRegex(OSError, "publication failure"):
                self.imported()
        self.assertEqual([], list((self.state / "runtimes").iterdir()))
        core = self.imported()
        retained = self.state / "runtimes" / (".import-" + "a" * 32)
        retained.mkdir()
        (retained / "retained-evidence").write_bytes(b"interrupted import evidence")
        self.assertEqual(1, len(store.list_cores(self.state)))
        self.assertEqual(core, self.imported())
        self.assertEqual(b"interrupted import evidence", (retained / "retained-evidence").read_bytes())

    def test_listing_does_not_lose_versions_when_an_import_stage_disappears(self):
        core = self.imported()
        temporary_name = ".import-" + "b" * 32
        temporary = self.state / "runtimes" / temporary_name
        temporary.mkdir()
        original_stat = store.os.stat

        def remove_before_stat(path, *args, **kwargs):
            if path == temporary_name:
                temporary.rmdir()
            return original_stat(path, *args, **kwargs)

        # 只控制枚举和 stat 之间的时序；实际删除、加载和摘要验证仍操作真实磁盘。
        with patch.object(store.os, "stat", side_effect=remove_before_stat):
            self.assertEqual([core.content_id], [row["content_id"] for row in store.list_cores(self.state)])

    def test_existing_empty_id_directory_is_not_replaced(self):
        core = self.imported()
        version = core.root.parent
        # 临时目录夹具主动移走快照，模拟中断/损坏留下同名空目录。
        retained = self.state / "preserved-version"
        # macOS 跨父目录移动需要修改目录的 .. 项，故先在夹具边界解除只读位。
        version.chmod(0o755)
        version.rename(retained)
        retained.chmod(0o555)
        version.mkdir(mode=0o555)
        inode = version.stat().st_ino
        with self.assertRaises(store.RuntimeStoreError):
            self.imported()
        self.assertEqual(inode, version.stat().st_ino)
        self.assertEqual([], list(version.iterdir()))
        self.assertTrue((retained / "manifest.json").is_file())

    def test_manifest_cannot_authorize_an_outside_payload_path(self):
        core = self.imported()
        path = core.root.parent / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["files"][0]["path"] = "../outside"
        raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.rewrite_readonly(path, raw)
        identifier = hashlib.sha256(raw).hexdigest()
        core.root.parent.rename(core.root.parent.parent / identifier)
        with self.assertRaisesRegex(store.RuntimeStoreError, "不规范"):
            store.load_core({"protocol_version": 1, "content_id": identifier,
                             "manifest_sha256": identifier}, self.state)

    def test_source_cannot_contain_destination(self):
        with self.assertRaisesRegex(store.RuntimeStoreError, "互相包含"):
            store.import_core(self.source, self.source / "machine-state")
        self.assertFalse((self.source / "machine-state").exists())


@unittest.skipUnless(os.name == "nt", "仅Server/elevated原生Windows的NTFS大小写目录安全证明")
class WindowsCaseSensitiveCoreNativeTest(unittest.TestCase):
    """独立于普通store类收集；产品不设置flag，也不要求普通用户提升。

    唯一native registry为本类声明Server/elevated资格。Windows中若fsutil或
    NTFS能力不足直接失败，不能skip/降级；POSIX不调用这两个原生节点。
    """

    def setUp(self):
        # 仅复用最小来源构造器和cleanup，不继承带tests的TestCase造成重复收集。
        self.fixture = RuntimeStoreTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.workspace = self.fixture.workspace
        parent = self.workspace / "case-sensitive"
        parent.mkdir()
        fsutil = Path(os.environ["SystemRoot"]) / "System32/fsutil.exe"
        command = [str(fsutil), "file", "setCaseSensitiveInfo", str(parent), "enable"]
        # 系统工具输出可能使用本地代码页；不解析本地化文案，资格由exit及
        # 后面真正创建的不同inode证明，诊断解码不能掩盖实际能力结果。
        enabled = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(0, enabled.returncode,
                         "Server/elevated测试资格不足：需要本地NTFS/管理员及自有目录属性权限；"
                         "未降级或skip。\n" + (enabled.stdout + enabled.stderr).decode("utf-8", errors="replace"))
        query = subprocess.run([str(fsutil), "file", "queryCaseSensitiveInfo", str(parent)],
                               capture_output=True, timeout=10)
        self.assertEqual(0, query.returncode, (query.stdout + query.stderr).decode("utf-8", errors="replace"))
        self.states = (parent / "State", parent / "state")
        for state in self.states:
            state.mkdir()
        identities = [store._node_identity(store.os.stat(path, follow_symlinks=False)) for path in self.states]
        self.assertEqual(self.states[0], self.states[1], "必须实际覆盖WindowsPath折叠语义")
        self.assertNotEqual(identities[0], identities[1], "必须真建两个实体，不能只有不同路径字符串")
        print("NTFS_CASE_SENSITIVE_CAPABILITY " + json.dumps({"fsutil_exit": enabled.returncode,
              "query_exit": query.returncode, "states": list(map(str, self.states)),
              "identities": identities, "qualification": "Server/elevated"}), flush=True)

    def pair(self, source):
        cores = tuple(store.import_core(source, state) for state in self.states)
        self.assertEqual(cores[0].binding(), cores[1].binding())
        return cores

    @staticmethod
    def overwrite_owned(path, body, mode):
        # 仅主动改变本例冻结文件；恢复原attributes，不修改生产ACL或codec。
        path.chmod(mode | 0o600)
        path.write_bytes(body)
        path.chmod(mode)

    def test_case_sensitive_ntfs_roots_get_independent_readers_and_guards(self):
        """真实两根分别fresh/尾检；缺失、正文损坏和第二根ACL变化不得借第一证明。"""
        first, second = self.pair(self.fixture.source)
        with patch.object(store, "_scan", wraps=store._scan) as scans, \
                patch.object(store, "_verify_snapshot", wraps=store._verify_snapshot) as checks:
            with store.core_read_operation() as operation:
                left = operation.reader(first.binding(), self.states[0])
                right = operation.reader(second.binding(), self.states[1])
                self.assertIsNot(left, right)
                self.assertNotEqual(store._node_identity(store.os.fstat(left._root)),
                                    store._node_identity(store.os.fstat(right._root)))
                self.assertIs(left, operation.reader(first.binding(), self.states[0]))
                self.assertEqual((second.root / "roles/xy-backend.md").read_bytes(),
                                 store.read_core_sources(second, ("roles/xy-backend.md",))["roles/xy-backend.md"])
                with self.assertRaises(store.RuntimeStoreError):
                    left.core_for(second.binding(), self.states[1])
                with self.assertRaises(store.RuntimeStoreError):
                    left.read(second, "roles/xy-backend.md")
                # 第三个拼写与两个已开根都折叠相等，但实际不存在，必须拒绝。
                with self.assertRaises(store.RuntimeStoreError):
                    store.load_core(first.binding(), self.states[0].parent / "STATE")
            self.assertEqual((2, 4), (scans.call_count, checks.call_count))
        damaged = second.root / "product/ROLES.yaml"
        original, mode = damaged.read_bytes(), stat.S_IMODE(damaged.stat().st_mode)
        try:
            with self.assertRaises(store.RuntimeStoreError), store.core_read_operation():
                store.load_core(first.binding(), self.states[0])
                self.overwrite_owned(damaged, original + b"different second root\n", mode)
                self.assertEqual(original, (first.root / "product/ROLES.yaml").read_bytes())
                store.load_core(second.binding(), self.states[1])
        finally:
            self.overwrite_owned(damaged, original, mode)
        from lib import windows_fs as fs
        with self.assertRaises(store.RuntimeStoreError), store.core_read_operation() as operation:
            operation.reader(first.binding(), self.states[0])
            operation.reader(second.binding(), self.states[1])
            handle = fs._open_handle(damaged, 0x60080)
            try:
                with fs._security_policy(handle) as before:
                    try:
                        with fs.private_security(inherit=not bool(before.acl_bytes[9] & 3)) as descriptor:
                            self.assertEqual(0, fs._api().security.SetSecurityInfo(
                                handle, 1, 0x80000004, None, None, fs._dacl(descriptor), None))
                        with fs._security_policy(handle) as after:
                            self.assertNotEqual(before.fingerprint, after.fingerprint)
                        operation.checkpoint()
                    finally:
                        self.assertEqual(0, fs._api().security.SetSecurityInfo(
                            handle, 1, 0x80000004, None, None, before.acl, None))
            finally:
                fs._close(handle)

    def test_case_sensitive_ntfs_fixed_runner_rejects_cross_root_before_cas(self):
        """原helper子进程启动边界真实正向更新，再证明case-distinct错根零CAS。"""
        from tests.test_task_graph_records import graph, records
        from lib.central.runtime_project import Tree
        first, second = self.pair(PACK)
        project = self.states[0].parent / "project"
        foreign_project = self.states[0].parent / "Project"
        project.mkdir()
        foreign_project.mkdir()
        self.assertNotEqual(store._node_identity(store.os.stat(project, follow_symlinks=False)),
                            store._node_identity(store.os.stat(foreign_project, follow_symlinks=False)))
        environment = {key: value for key, value in os.environ.items() if not key.startswith("AGENT_WORKFLOW_")}
        with patch.dict(os.environ, environment, clear=True):
            payload = graph()
        payload["runtime_binding"] = first.binding()
        record = project / "graph.json"
        record.write_text(json.dumps(payload), encoding="utf-8")
        environment.update({"AGENT_WORKFLOW_STATE_DIR": str(self.states[0]),
                            "AGENT_WORKFLOW_CORE_ROOT": str(first.root),
                            "AGENT_WORKFLOW_RUNTIME_BINDING": json.dumps(first.binding()),
                            "AGENT_WORKFLOW_PROJECT_ROOT": str(project),
                            "AGENT_WORKFLOW_CONFIG_PATH": str(project / ".agent-workflow/project.yaml"),
                            "PYTHONDONTWRITEBYTECODE": "1"})
        # 此节点直接验证固定helper child，不伪造本机绑定或上层init准入；上层
        # python_helper的实际绑定合同仍由已有central_project两个消费者覆盖。
        members = ("lib/runtime_pins.py", "lib/task_graph_cli.py", "lib/runtime_store.py", "lib/platform_fs.py",
                   "lib/__init__.py", "lib/windows_fs.py", "lib/windows_bootstrap.py")
        with store.core_reader(first.binding(), self.states[0]) as reader:
            for member in members:
                reader.read(first, member)
        command = [sys.executable, "-I", "-B", "-X", "utf8", str(first.root / "lib/windows_bootstrap.py"),
                   "--script", str(first.root / "lib/runtime_pins.py"), "--task-graph-operation"]
        def update(environment, patch_body, *, profile=None):
            arguments = ["update", "--input", str(record), "--expect-sha256", records.digest(record.read_bytes()), "--patch", "-"]
            selected = command if profile is None else [sys.executable, "-I", "-B", "-X", "utf8", "-c", profile, *command[1:]]
            return subprocess.run([*selected, *arguments], env=environment, cwd=project, input=patch_body,
                                  capture_output=True, text=True, timeout=40)
        positive = update(environment, '{"tasks":{"api":{"set":{"state":"RUNNING"}}}}')
        self.assertEqual(0, positive.returncode, positive.stderr)
        self.assertTrue(json.loads(positive.stdout)["updated"])
        self.assertEqual("RUNNING", json.loads(record.read_bytes())["tasks"][0]["state"])
        with Tree(project) as tree:
            before = tree.read("graph.json")
        body = '{"tasks":{"api":{"set":{"agent_ref":{"host":"codex","agent_id":"case-root-fixture"}}}}}'
        for field, value in (("AGENT_WORKFLOW_STATE_DIR", self.states[1]),
                             ("AGENT_WORKFLOW_CORE_ROOT", second.root),
                             ("AGENT_WORKFLOW_CONFIG_PATH", foreign_project / ".agent-workflow/project.yaml")):
            with self.subTest(field=field):
                denied = update({**environment, field: str(value)}, body)
                self.assertEqual(2, denied.returncode, denied.stderr)
                self.assertEqual("", denied.stdout)
                self.assertIn("三根", denied.stderr)
                with Tree(project) as tree:
                    self.assertEqual(before, tree.read("graph.json"))
                self.assertFalse(list(project.glob(".*.workflow-*")))
        # 这是导入之后的来源谓词故障注入，不是绕过预存lib拒绝。两个来源
        # 路径实际位于不同NTFS根；改__file__只能让来源检查拒绝，不能续用CAS。
        profile = '''import os,runpy,sys
def observe(frame,event,value):
    if event == "call" and frame.f_code.co_name == "_runner_module_sources" and "lib.runtime_store" in sys.modules:
        sys.modules["lib.runtime_store"].__file__=ORIGIN
values=sys.argv[1:]
while values and values[0] in {"-I","-B","-X"}:
    del values[:2 if values[0] == "-X" else 1]
sys.argv=values
sys.setprofile(observe)
runpy.run_path(values[0],run_name="__main__")
'''.replace("ORIGIN", repr(str(second.root / "lib/runtime_store.py")))
        denied = update(environment, body, profile=profile)
        self.assertEqual(2, denied.returncode, denied.stderr)
        self.assertEqual("", denied.stdout)
        self.assertIn("已加载模块", denied.stderr)
        with Tree(project) as tree:
            self.assertEqual(before, tree.read("graph.json"))
        self.assertFalse(list(project.glob(".*.workflow-*")))


if __name__ == "__main__":
    unittest.main()
