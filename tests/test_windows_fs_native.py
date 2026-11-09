"""真实 Win32 文件系统闭包；可移植测试与本模块通过证据分别记录。"""

from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

from lib import windows_fs as fs


PACK = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "requires actual native Windows local NTFS")
class WindowsSafePrimitivesNativeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-native-fs-")
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.parent = fs.secure_os.open(self.root, fs.DIRECTORY | fs.NOFOLLOW)
        self.addCleanup(fs.secure_os.close, self.parent)

    def private_file(self, name, body=b"owned"):
        descriptor = fs.secure_os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR,
                                       0o600, dir_fd=self.parent)
        try:
            os.write(descriptor, body)
            fs.secure_os.fsync(descriptor)
        finally:
            fs.secure_os.close(descriptor)
        return self.root / name

    def test_independent_embedded_reader_real_read_hardlink_and_live_writer(self):
        from lib.hosts.claude_instructions import read_file as shared_read
        path = self.private_file("fixture", "中文 fixture".encode())
        namespace = {}
        exec(compile(fs.bootstrap_reader_source(), "<trusted-reader>", "exec"), namespace)
        read = namespace["read_initial_regular"]
        self.assertEqual(read(path), path.read_bytes())
        self.assertEqual(shared_read(path), path.read_bytes())
        self.assertIsNone(shared_read(self.root / "missing"))
        with self.assertRaises(ValueError):
            shared_read(self.root)
        with path.open("r+b"), self.assertRaises(OSError):
            read(path)
        alias = self.root / "alias"
        os.link(path, alias)
        for target in (path, alias):
            with self.subTest(target=target), self.assertRaises(ValueError):
                read(target)
            with self.subTest(shared_consumer=target), self.assertRaises(ValueError):
                shared_read(target)

    def test_private_file_acl_projection_and_real_change_time(self):
        path = self.private_file("private")
        fs.assert_private(path)
        self.assertEqual(stat.S_IMODE(fs.secure_os.stat(path).st_mode), 0o600)
        before = fs.node_snapshot(self.parent, path.name)
        self.assertRegex(before["security"], r"^[0-9a-f]{64}$")
        handle = fs._open_handle(path, fs.READ)
        try:
            self.assertEqual(before["identity"][6], (fs._basic_information(handle).changed - fs._EPOCH) * 100)
        finally:
            fs._close(handle)
        handle = fs._open_handle(path, 0x60080)
        descriptor = fs.HANDLE()
        try:
            api = fs._api()
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None), 0)
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        after = fs.node_snapshot(self.parent, path.name)
        self.assertEqual(after["payload"], before["payload"])
        self.assertNotEqual(after["security"], before["security"])
        # ChangeTime 是否变化由系统决定；真实 DACL 变化始终由独立摘要捕获。
        with self.assertRaises(ValueError):
            fs.assert_private(path)
        with self.assertRaises(ValueError):
            fs.move_regular(path.name, "backup", src_dir_fd=self.parent,
                            dst_dir_fd=self.parent, expected=before)
        self.assertTrue(path.exists())
        self.assertFalse((self.root / "backup").exists())

    def test_consuming_regular_move_preserves_identity_and_excludes_existing_target(self):
        source = self.private_file("source")
        expected = fs.node_snapshot(self.parent, source.name)
        self.private_file("occupied", b"user")
        with self.assertRaises(OSError):
            fs.move_regular("source", "occupied", src_dir_fd=self.parent,
                            dst_dir_fd=self.parent, expected=expected)
        self.assertEqual((self.root / "occupied").read_bytes(), b"user")
        fs.move_regular("source", "backup", src_dir_fd=self.parent,
                        dst_dir_fd=self.parent, expected=expected)
        self.assertFalse(source.exists())
        after = fs.node_snapshot(self.parent, "backup")
        self.assertEqual(after["identity"][:2], expected["identity"][:2])
        self.assertEqual(after["security"], expected["security"])

    def test_managed_skill_exact_create_read_move_delete_and_stale_refusal(self):
        core = self.root / "runtimes" / ("a" * 64) / "core"
        target = core / "platforms/shared/skills/xy-workflow"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_bytes(b"central-owned-body")
        fs.create_skill_symlink(self.parent, "xy-workflow", target, core_root=core)
        from lib.hosts.claude_instructions import read_file as shared_read
        with self.assertRaises(ValueError):
            shared_read(self.root / "xy-workflow/SKILL.md")
        first = fs.read_skill_symlink(self.parent, "xy-workflow", skill_name="xy-workflow")
        self.assertEqual(first["payload"], os.fsencode(target))
        self.assertEqual(first["kind"], "link")
        with self.assertRaises(OSError):
            fs.create_skill_symlink(self.parent, "xy-workflow", target, core_root=core)
        stale = {**first, "security": "0" * 64}
        with self.assertRaises(ValueError):
            fs.delete_skill_symlink(self.parent, "xy-workflow", skill_name="xy-workflow", expected=stale)
        fs.move_skill_symlink("xy-workflow", ".owned-recovery", src_dir_fd=self.parent,
                              dst_dir_fd=self.parent, skill_name="xy-workflow", expected=first)
        moved = fs.read_skill_symlink(self.parent, ".owned-recovery", skill_name="xy-workflow")
        self.assertEqual(moved["identity"][:2], first["identity"][:2])
        fs.delete_skill_symlink(self.parent, ".owned-recovery", skill_name="xy-workflow", expected=moved)
        self.assertIsNone(fs.read_skill_symlink(self.parent, ".owned-recovery", skill_name="xy-workflow"))
        self.assertEqual((target / "SKILL.md").read_bytes(), b"central-owned-body")

    def test_complete_regular_delete_preserves_acl_writer_replacement_and_deletes_owned(self):
        path = self.private_file("delete-owned")
        before = fs.node_snapshot(self.parent, path.name)
        def compact(snapshot):
            return {"identity": snapshot["identity"], "security": snapshot["security"],
                    "sha256": hashlib.sha256(snapshot["payload"]).hexdigest()}
        with path.open("r+b"), self.assertRaises(OSError):
            fs.delete_regular(self.parent, path.name, expected=compact(before))
        self.assertEqual(b"owned", path.read_bytes())
        replacement = self.private_file("replacement", b"later-user-save")
        os.replace(replacement, path)
        with self.assertRaises(ValueError):
            fs.delete_regular(self.parent, path.name, expected=compact(before))
        self.assertEqual(b"later-user-save", path.read_bytes())
        current = fs.node_snapshot(self.parent, path.name)
        fs.delete_regular(self.parent, path.name, expected=compact(current))
        self.assertFalse(path.exists())
        acl_path = self.private_file("delete-acl")
        original = fs.node_snapshot(self.parent, acl_path.name)
        descriptor, handle = fs.HANDLE(), fs._open_handle(acl_path, 0x60080)
        try:
            api = fs._api()
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None))
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        changed = fs.node_snapshot(self.parent, acl_path.name)
        self.assertNotEqual(original["security"], changed["security"])
        # 使用真实当前 metadata 与过期 ACL 构造负控，使任何 ChangeTime 行为都不能
        # 替独立 ACL 做决定；portable 同时覆盖七标量完全相同的前后 ACL 竞态。
        stale_acl = {**compact(changed), "security": original["security"]}
        with self.assertRaises(ValueError):
            fs.delete_regular(self.parent, acl_path.name, expected=stale_acl)
        self.assertEqual(b"owned", acl_path.read_bytes())
        print("NATIVE_DELETE_CAS: writer blocked; replacement retained; real ACL change retained; owned node deleted; dacl_change_time_equal="
              + str(original["identity"][6] == changed["identity"][6]))

    def test_conditional_empty_directory_and_streaming_read_exclude_changes(self):
        from lib import runtime_store
        from manager import runtime_lifecycle
        stream = self.private_file("stream-owned")
        with stream.open("r+b"):
            with self.assertRaises(OSError):
                runtime_store._read_regular(self.parent, stream.name)
            with self.assertRaises(OSError):
                runtime_lifecycle._file_metadata(self.parent, stream.name)
        fs.secure_os.mkdir("stage-dir", 0o700, dir_fd=self.parent)
        child = fs.secure_os.open("stage-dir", fs.DIRECTORY | fs.NOFOLLOW, dir_fd=self.parent)
        info = fs.secure_os.fstat(child)
        expected = {"identity": (info.st_dev, info.st_ino), "security": fs.security_fingerprint(child)}
        fs.secure_os.close(child)
        directory = self.root / "stage-dir"
        (directory / "user-save").write_bytes(b"must survive nonempty rejection")
        with self.assertRaises(OSError):
            fs.delete_directory(self.parent, directory.name, expected=expected)
        self.assertEqual(b"must survive nonempty rejection", (directory / "user-save").read_bytes())
        (directory / "user-save").unlink()
        fs.delete_directory(self.parent, directory.name, expected=expected)
        self.assertFalse(directory.exists())
        fs.secure_os.mkdir("replace-dir", 0o700, dir_fd=self.parent)
        child = fs.secure_os.open("replace-dir", fs.DIRECTORY | fs.NOFOLLOW, dir_fd=self.parent)
        info = fs.secure_os.fstat(child)
        stale = {"identity": (info.st_dev, info.st_ino), "security": fs.security_fingerprint(child)}
        fs.secure_os.close(child)
        (self.root / "replace-dir").rename(self.root / "original-dir")
        fs.secure_os.mkdir("replace-dir", 0o700, dir_fd=self.parent)
        with self.assertRaises(ValueError):
            fs.delete_directory(self.parent, "replace-dir", expected=stale)
        self.assertTrue((self.root / "replace-dir").is_dir())
        descriptor, handle = fs.HANDLE(), fs._open_handle(self.root / "replace-dir", 0x60080, directory=True)
        try:
            api = fs._api()
            current = fs._metadata(handle)
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None))
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        with self.assertRaises(ValueError):
            fs.delete_directory(self.parent, "replace-dir", expected={"identity": current[0][:2], "security": current[1]})
        self.assertTrue((self.root / "replace-dir").is_dir())
        print("NATIVE_DIRECTORY_CAS: empty deleted, nonempty and replacement retained; both128MiB stream consumers reject live writer")

    def test_independent_initial_private_gate_rejects_public_acl_before_core(self):
        private = self.private_file("initial-private")
        namespace = {}
        exec(compile(fs.bootstrap_reader_source(), "<private-native-initial>", "exec"), namespace)
        embedded = namespace["read_initial_regular"]
        self.assertEqual(b"owned", embedded(private, require_private=True))
        self.assertEqual(b"owned", fs.read_initial_regular(private, require_private=True))
        descriptor, handle = fs.HANDLE(), fs._open_handle(private, 0x60080)
        try:
            api = fs._api()
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None))
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        # 同一个公开文档仍可沿默认reader读取；只有控制/预执行材料要求私有信任门。
        self.assertEqual(b"owned", embedded(private))
        for read in (embedded, fs.read_initial_regular):
            with self.assertRaisesRegex(ValueError, "private"):
                read(private, require_private=True)
        print("NATIVE_INITIAL_PRIVATE: real private owner/protectedDACL accepted; public ACL rejected by embedded/backend; default public read retained")

    def test_global_mutex_real_second_process_contends_on_same_directory(self):
        source = ("import sys; sys.path.insert(0, sys.argv[1]); "
                  "from pathlib import Path; from lib.windows_fs import directory_lock\n"
                  "try:\n with directory_lock(Path(sys.argv[2]), 'native-contract'): pass\n"
                  "except ValueError as error:\n"
                  " if 'busy' not in str(error): raise\n"
                  " print('busy')\n"
                  "else: raise AssertionError('second process acquired held mutex')\n")
        with fs.directory_lock(self.root, "native-contract"):
            result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", source,
                                     str(PACK), str(self.root)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "busy")

    def test_cross_stage_parent_acl_inheritance_mismatch_is_a_real_failure(self):
        api = fs._api()
        def set_parent(path, everyone):
            path.mkdir()
            handle = fs._open_handle(path, 0x60080, directory=True)
            descriptor = fs.HANDLE()
            try:
                sddl = f"O:{fs.current_sid()}D:P(A;OICI;GA;;;{fs.current_sid()})(A;OICI;GA;;;SY)"
                if everyone:
                    sddl += "(A;OICI;GR;;;WD)"
                self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, ctypes.byref(descriptor), None))
                self.assertEqual(api.security.SetSecurityInfo(handle, 1, 0x80000004,
                    None, None, fs._dacl(descriptor), None), 0)
            finally:
                if descriptor.value:
                    api.kernel.LocalFree(descriptor)
                fs._close(handle)
        target_parent, stage_parent = self.root / "target-parent", self.root / "stage-parent"
        set_parent(target_parent, False)
        set_parent(stage_parent, True)
        target, stage = target_parent / "target", stage_parent / "stage"
        target.write_bytes(b"original")
        stage.write_bytes(b"candidate")
        with self.assertRaisesRegex(ValueError, "inheritance"):
            fs.copy_permissions(target, stage)
        self.assertEqual(target.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
