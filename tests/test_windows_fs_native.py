"""真实 Win32 文件系统闭包；可移植测试与本模块通过证据分别记录。"""

from __future__ import annotations

import ctypes
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
