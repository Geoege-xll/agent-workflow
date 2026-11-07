"""通用 Windows 启动器与文件系统合同；可移植实进程和原生平台验收分开选择。"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PACK = Path(__file__).resolve().parents[1]


def windows_module(name):
    """从固定源码加载通用 Windows 后端，导入后恢复测试调用者的搜索路径。"""
    module_spec = importlib.util.spec_from_file_location(f"windows_runtime_test_{name}", PACK / "lib" / f"{name}.py")
    module = importlib.util.module_from_spec(module_spec)
    before = sys.path[:]
    try:
        module_spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    return module



class WindowsBootstrapPortableTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-bootstrap-test-")
        self.root = Path(self.temp.name).resolve()
        self.caller = self.root / "untrusted caller 项目"
        self.scripts = self.root / "explicit scripts with spaces"
        self.caller.mkdir()
        self.scripts.mkdir()
        # Neither a normal module name nor a stdlib shadow in cwd may be imported.
        (self.caller / "caller_only.py").write_text("raise AssertionError('cwd import')\n")
        (self.caller / "json.py").write_text("raise AssertionError('stdlib shadow from cwd')\n")
        (self.scripts / "safe_helper.py").write_text("VALUE = 42\n")
        self.bootstrap = PACK / "lib/windows_bootstrap.py"
        self.env = {**os.environ, "PYTHONPATH": str(self.caller)}
        self.env.pop("AGENT_WORKFLOW_PROJECT_RUNTIME", None)

    def tearDown(self):
        self.temp.cleanup()

    def run_bootstrap(self, args, source=None, env=None):
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(self.bootstrap), *args],
                                cwd=self.caller, env=self.env if env is None else env,
                                input=source, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_script_explicit_import_directory_unicode_argv_and_no_caller_cwd(self):
        script = self.scripts / "entry 中文.py"
        script.write_text("import importlib.util,json,os,sys\nfrom safe_helper import VALUE\n"
                          "print(json.dumps({'argv':sys.argv,'cwd':os.getcwd(),'helper':VALUE,"
                          "'caller':importlib.util.find_spec('caller_only') is not None,"
                          "'first_path':sys.path[0]}))\n")
        for prefix in ([], ["--script"], ["-B", "-X", "utf8"]):
            with self.subTest(prefix=prefix):
                actual = self.run_bootstrap([*prefix, str(script), "中文 (a)&", "--literal"])
                self.assertEqual(actual, {"argv": [str(script), "中文 (a)&", "--literal"],
                                         "cwd": str(self.caller), "helper": 42, "caller": False,
                                         "first_path": str(self.scripts)})
        self.assertFalse((self.scripts / "__pycache__").exists())
        self.assertFalse((self.caller / "__pycache__").exists())

    def test_c_and_stdin_modes_preserve_source_and_argv_without_cwd_imports(self):
        source = ("import importlib.util,json,sys\n"
                  "print(json.dumps({'argv':sys.argv,'caller':importlib.util.find_spec('caller_only') is not None,"
                  "'body':'/c/not-a-path JSON & 中文'}))\n")
        for args, stdin, expected in ((["-c", source, "literal /c/x"], None, ["-c", "literal /c/x"]),
                                      (["-", "arg 中文"], source, ["-", "arg 中文"]), ([], source, ["-"])):
            with self.subTest(mode=args[:1]):
                actual = self.run_bootstrap(args, stdin)
                self.assertEqual(actual["argv"], expected)
                self.assertFalse(actual["caller"])
                self.assertEqual(actual["body"], "/c/not-a-path JSON & 中文")

    def test_module_mode_uses_explicit_runtime_not_caller_directory(self):
        module = self.scripts / "safe_module.py"
        module.write_text("import importlib.util,json,sys\nfrom safe_helper import VALUE\n"
                          "print(json.dumps({'helper':VALUE,'argv':sys.argv,"
                          "'caller':importlib.util.find_spec('caller_only') is not None}))\n")
        actual = self.run_bootstrap(["-m", "safe_module", "中文"],
                                    env={**self.env, "AGENT_WORKFLOW_PROJECT_RUNTIME": str(self.scripts)})
        self.assertEqual(actual["helper"], 42)
        self.assertEqual(actual["argv"], [str(module), "中文"])
        self.assertFalse(actual["caller"])



@unittest.skipUnless(os.name == "nt", "requires native Windows NTFS; portable mocks do not verify Win32 safety")
class WindowsFilesystemNativeTest(unittest.TestCase):
    """保留真实 Win32 安全合同；缺权限或持久化能力必须失败，不能当作模拟成功。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-win32-native-")
        self.root = Path(self.temp.name).resolve()
        self.fs = windows_module("windows_fs")
        self.addCleanup(self.temp.cleanup)
        # A capability refusal is a native validation failure, not a simulated pass.
        with self.fs.Directory(self.root):
            pass

    def test_directory_identity_case_alias_relative_names_and_pinned_rename(self):
        target = self.root / "PinnedCase"
        target.mkdir()
        with self.fs.Directory(target) as first, self.fs.Directory(str(target).swapcase()) as alias:
            self.assertEqual(first.identity, alias.identity)
            self.assertEqual(first.child("leaf"), target / "leaf")
            for name in ("", ".", "..", "../escape", "a/b", "a\\b", "a:b"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    first.child(name)
            with self.assertRaises(OSError):
                os.rename(target, self.root / "moved")
            self.assertTrue(target.is_dir())
        os.rename(target, self.root / "moved")

    def test_exhausted_or_context_closed_scandir_does_not_pin_directory(self):
        for exhausted in (False, True):
            with self.subTest(exhausted=exhausted):
                source = self.root / f"enumerated-{exhausted}"
                source.mkdir()
                (source / "leaf").write_bytes(b"fixture")
                iterator = self.fs.secure_os.scandir(source)
                if exhausted:
                    self.assertEqual([entry.name for entry in iterator], ["leaf"])
                else:
                    with iterator:
                        self.assertEqual(next(iterator).name, "leaf")
                moved = self.root / f"moved-{exhausted}"
                self.fs.secure_os.rename(source, moved)
                self.assertEqual((moved / "leaf").read_bytes(), b"fixture")
                iterator.close()

    def test_no_follow_hardlink_reads_and_truncation_refused_without_changes(self):
        original = self.root / "owned"
        alias = self.root / "hardlink"
        original.write_bytes(b"preserve")
        os.link(original, alias)
        for path in (original, alias):
            for flags in (os.O_RDONLY | self.fs.NOFOLLOW, os.O_WRONLY | os.O_TRUNC | self.fs.NOFOLLOW):
                with self.subTest(path=path, flags=flags), self.assertRaises(ValueError):
                    self.fs.secure_os.open(path, flags)
        self.assertEqual(original.read_bytes(), b"preserve")
        self.assertEqual(alias.read_bytes(), b"preserve")

    def test_junction_reparse_directory_and_descendant_reads_refused(self):
        target = self.root / "target"
        target.mkdir()
        (target / "file").write_bytes(b"preserve")
        junction = self.root / "junction"
        command = str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe")
        result = subprocess.run([command, "/d", "/c", "mklink", "/J", str(junction), str(target)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, "Native junction creation unavailable: " + result.stdout + result.stderr)
        try:
            with self.assertRaises(ValueError):
                self.fs.Directory(junction)
            self.assertTrue(stat.S_ISLNK(self.fs.secure_os.lstat(junction).st_mode))
            with self.assertRaises(ValueError):
                self.fs.secure_os.open(junction / "file", os.O_RDONLY | self.fs.NOFOLLOW)
            self.assertEqual((target / "file").read_bytes(), b"preserve")
        finally:
            os.rmdir(junction)

    def test_crt_tempfile_fchmod_pins_identity_and_file_flush(self):
        descriptor, name = tempfile.mkstemp(dir=self.root)
        try:
            os.write(descriptor, b"durable tempfile")
            before = self.fs.secure_os.fstat(descriptor)
            self.fs.secure_os.fchmod(descriptor, 0o600)
            self.fs.secure_os.fsync(descriptor)
            after = self.fs.secure_os.fstat(descriptor)
            self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))
            self.assertEqual(after.st_nlink, 1)
            with self.assertRaises(ValueError):
                self.fs.secure_os.fchmod(descriptor, 0o400)
        finally:
            self.fs.secure_os.close(descriptor)
        self.assertEqual(self.fs.read_file(Path(name)), b"durable tempfile")

    def test_sid_private_directory_dacl_and_foreign_principal_rejection(self):
        self.assertRegex(self.fs.current_sid(), r"^S-1-\d+(?:-\d+)+$")
        private = self.root / "private"
        self.fs.secure_os.mkdir(private, 0o700)
        self.fs.assert_private(private)
        # Deliberately broaden only this owned temporary directory to Everyone.
        api = self.fs._api()
        handle = self.fs._open_handle(private, 0x60080, directory=True)
        descriptor = self.fs.HANDLE()
        try:
            sddl = f"D:P(A;OICI;GA;;;{self.fs.current_sid()})(A;OICI;GA;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            error = api.security.SetSecurityInfo(handle, 1, 0x80000004,
                                                 None, None, self.fs._dacl(descriptor), None)
            self.assertEqual(error, 0, f"Cannot exercise native private DACL refusal: {error}")
        finally:
            if descriptor.value:
                api.kernel.LocalFree(descriptor)
            self.fs._close(handle)
        with self.assertRaises(ValueError):
            self.fs.assert_private(private)

    def test_directory_flush_capability_preflight_is_real_and_explicit(self):
        descriptor = self.fs.secure_os.open(self.root, os.O_RDONLY | self.fs.DIRECTORY | self.fs.NOFOLLOW)
        try:
            try:
                self.fs.secure_os.fsync(descriptor)
            except OSError as exc:
                self.fail(f"Native durable directory flush capability unavailable; Windows release blocked: {exc}")
        finally:
            self.fs.secure_os.close(descriptor)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_relative_nul_read_truncate_and_delete_preserve_real_leaf(self):
        victim = self.root / "victim"
        victim.write_bytes(b"user content")
        descriptor = self.fs.secure_os.open(self.root, self.fs.DIRECTORY | self.fs.NOFOLLOW)
        try:
            for flags in (os.O_RDONLY, os.O_WRONLY | os.O_TRUNC):
                with self.subTest(flags=flags), self.assertRaises(ValueError):
                    self.fs.secure_os.open("victim\0suffix", flags, dir_fd=descriptor)
            with self.assertRaises(ValueError):
                self.fs.secure_os.unlink("victim\0suffix", dir_fd=descriptor)
        finally:
            self.fs.secure_os.close(descriptor)
        self.assertEqual(victim.read_bytes(), b"user content")

    def test_conditional_cleanup_preserves_swapped_identity_and_busy_writer(self):
        victim = self.root / "owned"
        victim.write_bytes(b"owned")
        info = self.fs.secure_os.stat(victim)
        identity = (info.st_dev, info.st_ino)
        digest = hashlib.sha256(b"owned").hexdigest()
        replacement = self.root / "replacement"
        replacement.write_bytes(b"owned")
        opened = self.fs._open_handle
        def swap(path, *args, **kwargs):
            if path == victim:
                os.replace(replacement, victim)
            return opened(path, *args, **kwargs)
        with patch.object(self.fs, "_open_handle", side_effect=swap):
            self.assertFalse(self.fs.remove_file_if_unchanged(victim, digest, identity))
        self.assertEqual(victim.read_bytes(), b"owned")
        with victim.open("r+b"):
            with self.assertRaises(OSError):
                self.fs.remove_file_if_unchanged(victim, digest)
        victim.write_bytes(b"user edit")
        self.assertFalse(self.fs.remove_file_if_unchanged(victim, digest))
        self.assertEqual(victim.read_bytes(), b"user edit")
        self.assertTrue(self.fs.remove_file_if_unchanged(victim, hashlib.sha256(b"user edit").hexdigest()))
        self.assertFalse(victim.exists())

    def test_successful_backend_file_directory_rename_and_delete(self):
        source = self.root / "source"
        target = self.root / "target"
        source.write_bytes(b"owned")
        before = self.fs.secure_os.stat(source)
        self.fs.secure_os.rename(source, target)
        after = self.fs.secure_os.stat(target)
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        self.assertEqual(target.read_bytes(), b"owned")
        self.fs.secure_os.unlink(target)
        source.mkdir()
        self.fs.secure_os.rename(source, target)
        self.fs.secure_os.rmdir(target)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_replacement_preserves_acl_protection_and_future_parent_inheritance(self):
        api = self.fs._api()
        def set_dacl(path, sddl, *, directory=False):
            handle = self.fs._open_handle(path, 0x60080, directory=directory)
            descriptor = self.fs.HANDLE()
            try:
                self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, ctypes.byref(descriptor), None))
                self.assertEqual(api.security.SetSecurityInfo(handle, 1, 0x80000004,
                    None, None, self.fs._dacl(descriptor), None), 0)
            finally:
                if descriptor.value:
                    api.kernel.LocalFree(descriptor)
                self.fs._close(handle)
        def policy(path):
            handle = self.fs._open_handle(path, self.fs.READ)
            descriptor, acl = self.fs.HANDLE(), self.fs.HANDLE()
            try:
                self.assertEqual(api.security.GetSecurityInfo(handle, 1, 4, None, None,
                    ctypes.byref(acl), None, ctypes.byref(descriptor)), 0)
                control, revision = ctypes.c_uint16(), self.fs.DWORD()
                self.assertTrue(api.security.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)))
                class Size(ctypes.Structure):
                    _fields_ = [("count", self.fs.DWORD), ("used", self.fs.DWORD), ("free", self.fs.DWORD)]
                size = Size()
                self.assertTrue(api.security.GetAclInformation(acl, ctypes.byref(size), ctypes.sizeof(size), 2))
                sids = set()
                for index in range(size.count):
                    ace, text = self.fs.HANDLE(), ctypes.c_wchar_p()
                    self.assertTrue(api.security.GetAce(acl, index, ctypes.byref(ace)))
                    self.assertTrue(api.security.ConvertSidToStringSidW(self.fs.HANDLE(ace.value + 8), ctypes.byref(text)))
                    try:
                        sids.add(text.value)
                    finally:
                        api.kernel.LocalFree(ctypes.cast(text, self.fs.HANDLE))
                return bool(control.value & 0x1000), sids
            finally:
                if descriptor.value:
                    api.kernel.LocalFree(descriptor)
                self.fs._close(handle)
        base_acl = f"D:P(A;OICI;GA;;;{self.fs.current_sid()})(A;OICI;GA;;;SY)"
        for protected in (False, True):
            with self.subTest(protected=protected):
                parent = self.root / str(protected)
                parent.mkdir()
                set_dacl(parent, base_acl, directory=True)
                target, temporary = parent / "target", parent / "temporary"
                target.write_bytes(b"old")
                temporary.write_bytes(b"new")
                if protected:
                    set_dacl(target, base_acl)
                self.assertEqual(policy(target)[0], protected)
                self.fs.copy_permissions(target, temporary)
                self.fs.secure_os.replace(temporary, target)
                self.assertEqual(policy(target)[0], protected)
                set_dacl(parent, base_acl + "(A;OICI;GR;;;WD)", directory=True)
                self.assertEqual("S-1-1-0" in policy(target)[1], not protected)


if __name__ == "__main__":
    unittest.main()
