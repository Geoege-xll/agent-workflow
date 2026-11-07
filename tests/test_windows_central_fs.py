"""原生 Windows 能力探针：只验证调用账户能力，不宣称中央安装已经可用。"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


PACK = Path(__file__).resolve().parents[1]
PROBE_ROOT = None
PROBE_MODE = None


def native_fs():
    spec = importlib.util.spec_from_file_location("awf_native_capability_fs", PACK / "lib/windows_fs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 能力 fixture 只能经显式 CLI 准备账户后执行；通常 unittest discovery
# 只发现下面独立的后端消费者，不能把宿主管理员当无权限普通用户夹具。
@unittest.skipUnless(os.name == "nt" and __name__ == "__main__", "能力探针需要显式原生 CLI")
class WindowsCapabilityProbe(unittest.TestCase):
    """由受控 CI runner 分别用宿主令牌和两个真实标准用户登录令牌执行。"""

    def setUp(self):
        self.fs = native_fs()
        self.temp = tempfile.TemporaryDirectory(prefix="capability-", dir=PROBE_ROOT)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def test_directory_durability_uses_real_backend(self):
        # 直接消费现有生产目录描述符与 fsync；不 mock、不跳过错误、不以文件
        # flush 替代命名空间屏障。任何 Win32 错误都保留原始 winerror/调用栈。
        descriptor = self.fs.secure_os.open(
            self.root, self.fs.secure_os.O_RDONLY | self.fs.DIRECTORY | self.fs.NOFOLLOW)
        try:
            self.fs.secure_os.fsync(descriptor)
        finally:
            self.fs.secure_os.close(descriptor)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_ordinary_token_and_directory_symlink_capability(self):
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.IsUserAnAdmin.restype = ctypes.c_int32
        self.assertFalse(shell.IsUserAnAdmin(), "此节点必须由真实非管理员账户执行")
        print(f"普通用户 SID: {self.fs.current_sid()}", flush=True)
        self._set_symlink_privilege(PROBE_MODE == "ordinary-allowed")
        target, link = self.root / "真实目标", self.root / "目录软链接"
        target.mkdir()
        target_sentinel = target / "保留.txt"
        user_sentinel = self.root / "user-owned.txt"
        target_sentinel.write_bytes(b"target sentinel")
        user_sentinel.write_bytes(b"user sentinel")
        target_identity = (target.stat().st_dev, target.stat().st_ino)
        kernel = self.fs._api().kernel
        create = kernel.CreateSymbolicLinkW
        create.restype = ctypes.c_uint8
        create.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, self.fs.DWORD]
        # 与拟实现的产品一致：目录 + ALLOW_UNPRIVILEGED_CREATE。该调用
        # 不改变 Developer Mode；独立 CI runner 按授权准备/恢复负向环境，
        # 但注册表值本身不能代替这里真实 API 的拒绝或成功结果。
        succeeded = bool(create(str(link), str(target), 0x1 | 0x2))
        error = ctypes.get_last_error()
        try:
            if PROBE_MODE in {"ordinary-denied", "ordinary-denied-only"}:
                self.assertFalse(succeeded, "当前机器已有未提权软链能力，缺能力 fixture 不成立")
                self.assertEqual(error, 1314, f"需要真实 ERROR_PRIVILEGE_NOT_HELD，实际 {error}")
                self.assertFalse(os.path.lexists(link))
                self.assertCountEqual(list(self.root.iterdir()), [target, user_sentinel])
            else:
                self.assertTrue(succeeded, f"标准用户目录软链能力未成立，Win32 error={error}")
                info = os.lstat(link)
                self.assertEqual(info.st_reparse_tag, 0xA000000C, "必须是真正 SYMLINK，不能是 junction")
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(strict=True), target)
            # 负向失败或恢复调用都必须保持既有目标与用户文件；只看 API
            # 返回值不能替代没有误写/替换数据的事实。
            self.assertEqual(target_sentinel.read_bytes(), b"target sentinel")
            self.assertEqual(user_sentinel.read_bytes(), b"user sentinel")
            self.assertEqual((target.stat().st_dev, target.stat().st_ino), target_identity)
        finally:
            # 只收回本 fixture 创建、并已确认是目录软链的节点；目标目录由
            # TemporaryDirectory 在测试结束后回收，不能通过链接递归删除目标。
            if succeeded:
                os.rmdir(link)

    def _set_symlink_privilege(self, expected_present):
        api = self.fs._api()
        token = self.fs.HANDLE()
        self.fs._check(api.security.OpenProcessToken(
            api.kernel.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(token)))
        class Luid(ctypes.Structure):
            _fields_ = [("low", self.fs.DWORD), ("high", ctypes.c_int32)]
        class Entry(ctypes.Structure):
            _fields_ = [("luid", Luid), ("attributes", self.fs.DWORD)]
        class Privileges(ctypes.Structure):
            _fields_ = [("count", self.fs.DWORD), ("privilege", Entry)]
        lookup = api.security.LookupPrivilegeValueW
        lookup.restype, lookup.argtypes = self.fs.BOOL, [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.POINTER(Luid)]
        adjust = api.security.AdjustTokenPrivileges
        adjust.restype = self.fs.BOOL
        adjust.argtypes = [self.fs.HANDLE, self.fs.BOOL, ctypes.POINTER(Privileges),
                           self.fs.DWORD, self.fs.HANDLE, self.fs.HANDLE]
        try:
            luid = Luid()
            self.fs._check(lookup(None, "SeCreateSymbolicLinkPrivilege", ctypes.byref(luid)))
            privileges = Privileges(1, Entry(luid, 0x2))
            ctypes.set_last_error(0)
            self.fs._check(adjust(token, False, ctypes.byref(privileges), 0, None, None))
            error = ctypes.get_last_error()
            # AdjustTokenPrivileges 可返回 TRUE 同时设置 NOT_ALL_ASSIGNED；必须
            # 检查该错误。此处只启用测试账户已经被赋予的能力，不给产品提权。
            self.assertEqual(error, 0 if expected_present else 1300,
                             f"真实令牌的软链权限与测试阶段不符：{error}")
        finally:
            self.fs._close(token)



@unittest.skipUnless(os.name == "nt", "需要原生 Windows NTFS 后端消费者")
class WindowsBackendNativeTest(unittest.TestCase):
    """只验新后端行为；正常 discovery 不依赖能力探针的管理员/权限 fixture。"""

    def setUp(self):
        if str(PACK) not in sys.path:
            sys.path.insert(0, str(PACK))
        from lib import platform_fs, windows_fs
        self.platform, self.fs = platform_fs, windows_fs
        self.backend = platform_fs.os
        self.assertIs(self.backend, windows_fs.secure_os)
        if PROBE_MODE in {"backend-native", "backend-rename"}:
            shell = ctypes.WinDLL("shell32", use_last_error=True)
            shell.IsUserAnAdmin.restype = ctypes.c_int32
            self.assertFalse(shell.IsUserAnAdmin(), "显式后端 CI 必须使用真实标准用户")
        self.temp = tempfile.TemporaryDirectory(prefix="backend-", dir=PROBE_ROOT)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.parent = self.backend.open(self.root, self.fs.DIRECTORY | self.fs.NOFOLLOW)
        self.addCleanup(self.backend.close, self.parent)

    def test_directory_symlink_read_rename_unlink_never_follows_target(self):
        target = self.root / "真实目标"
        target.mkdir()
        (target / "sentinel").write_bytes(b"preserve target")
        self.backend.symlink(target, "xy-workflow", dir_fd=self.parent, target_is_directory=True)
        before = self.backend.stat("xy-workflow", dir_fd=self.parent, follow_symlinks=False)
        self.assertEqual(self.backend.readlink("xy-workflow", dir_fd=self.parent), str(target))
        with self.assertRaises(ValueError):
            self.backend.open("xy-workflow", self.fs.DIRECTORY, dir_fd=self.parent)
        with self.assertRaises(ValueError):
            self.backend.open(target.parent / "xy-workflow" / "sentinel", os.O_RDONLY)
        self.backend.rename("xy-workflow", "held", src_dir_fd=self.parent, dst_dir_fd=self.parent)
        after = self.backend.stat("held", dir_fd=self.parent, follow_symlinks=False)
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        (self.root / "collision").write_bytes(b"preserve collision")
        with self.assertRaises(FileExistsError):
            self.backend.rename("held", "collision", src_dir_fd=self.parent, dst_dir_fd=self.parent)
        self.assertEqual(self.backend.readlink("held", dir_fd=self.parent), str(target))
        self.backend.unlink("held", dir_fd=self.parent)
        self.assertEqual((target / "sentinel").read_bytes(), b"preserve target")
        self.assertEqual((self.root / "collision").read_bytes(), b"preserve collision")

    def test_hardlink_is_real_and_ordinary_reads_writes_and_deletes_remain_guarded(self):
        source = self.root / "source"
        source.write_bytes(b"preserve hardlink")
        self.backend.link("source", "alias", src_dir_fd=self.parent, dst_dir_fd=self.parent,
                          follow_symlinks=False)
        left, right = (self.backend.stat(name, dir_fd=self.parent) for name in ("source", "alias"))
        self.assertEqual((left.st_dev, left.st_ino), (right.st_dev, right.st_ino))
        self.assertEqual((left.st_nlink, right.st_nlink), (2, 2))
        for name in ("source", "alias"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.backend.open(name, os.O_RDONLY, dir_fd=self.parent)
                with self.assertRaises(ValueError):
                    self.backend.open(name, os.O_WRONLY | os.O_TRUNC, dir_fd=self.parent)
                with self.assertRaises(ValueError):
                    self.backend.unlink(name, dir_fd=self.parent)
        self.assertEqual(source.read_bytes(), b"preserve hardlink")
        # 原生 fixture 自己拆除硬链；生产普通文件删除不能为此放宽多硬链守卫。
        os.unlink(self.root / "alias")
        descriptor = self.backend.open("source", os.O_RDONLY, dir_fd=self.parent)
        with self.backend.fdopen(descriptor, "rb") as stream:
            self.assertEqual(stream.read(), b"preserve hardlink")

    def test_exclusive_publication_moves_one_identity_without_hardlink_window(self):
        (self.root / "candidate").write_bytes(b"complete file")
        before = self.backend.stat("candidate", dir_fd=self.parent)
        self.platform.publish_exclusive_at("candidate", "published",
                                          src_dir_fd=self.parent, dst_dir_fd=self.parent)
        after = self.backend.stat("published", dir_fd=self.parent)
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        self.assertEqual(after.st_nlink, 1)
        self.assertFalse((self.root / "candidate").exists())
        (self.root / "candidate").write_bytes(b"later candidate")
        with self.assertRaises(FileExistsError):
            self.platform.publish_exclusive_at("candidate", "published",
                                              src_dir_fd=self.parent, dst_dir_fd=self.parent)
        self.assertEqual((self.root / "candidate").read_bytes(), b"later candidate")
        self.assertEqual((self.root / "published").read_bytes(), b"complete file")

    def test_junction_cannot_enter_symbolic_link_operations(self):
        import subprocess
        target = self.root / "junction-target"
        target.mkdir()
        (target / "sentinel").write_bytes(b"preserve junction target")
        junction = self.root / "junction"
        result = subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe"),
                                 "/d", "/c", "mklink", "/J", str(junction), str(target)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        try:
            for action in (lambda: self.backend.readlink("junction", dir_fd=self.parent),
                           lambda: self.backend.unlink("junction", dir_fd=self.parent),
                           lambda: self.backend.rename("junction", "moved",
                                                       src_dir_fd=self.parent, dst_dir_fd=self.parent)):
                with self.assertRaises(ValueError):
                    action()
            self.assertEqual((target / "sentinel").read_bytes(), b"preserve junction target")
        finally:
            os.rmdir(junction)


@unittest.skipUnless(os.name == "nt" and __name__ == "__main__", "中央普通用户消费者需要显式 CLI")
class WindowsCentralInstallTest(unittest.TestCase):
    """在全新真实普通用户中走产品安装和项目薄桥，不重复底层能力矩阵。"""

    def test_real_install_prepared_bridge_and_pinned_helper(self):
        import json
        import shutil
        import subprocess
        from unittest.mock import patch
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.IsUserAnAdmin.restype = ctypes.c_int32
        self.assertFalse(shell.IsUserAnAdmin(), "中央消费者必须是真实普通用户")
        # 该小切片采用 setup-python + 源 bootstrap；完整离线 tgz E2E 另验真正
        # 部署的私有 embedded Python，不能以此节点替代 npm 最终安装验收。
        sys.path.insert(0, str(PACK))
        from lib.install_workflow import install_central
        from lib import runtime_project as project_files, runtime_store
        from lib.windows_fs import assert_private
        from manager import runtime_service
        with tempfile.TemporaryDirectory(prefix="central-native-", dir=PROBE_ROOT) as temporary:
            root = Path(temporary)
            project, state = root / "真实项目", root / "private-state"
            project.mkdir()
            sentinel = project / "user-owned.txt"
            sentinel.write_bytes(b"preserve ordinary user data")
            before = sentinel.stat()
            bootstrap = PACK / "lib/windows_bootstrap.py"
            clean = {key: value for key, value in os.environ.items() if key not in {
                "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                "AGENT_WORKFLOW_CORE_ROOT", "AGENT_WORKFLOW_CONFIG_PATH"}}
            clean.update({"AGENT_WORKFLOW_BOOTSTRAP": str(bootstrap),
                          "AGENT_WORKFLOW_STATE_DIR": str(state)})
            from lib import install_workflow
            real_capture = install_workflow.capture_process
            def observed_capture(*arguments, **options):
                # 仅记录本轮自有 fixture 的真实子进程失败输出，保留生产执行/
                # 字节比较/预算，不 mock 成功结果。便于首次 native 失败定位。
                actual = real_capture(*arguments, **options)
                print(f"prepared桥 exit={actual.returncode} stdout_bytes={len(actual.stdout)} stderr_bytes={len(actual.stderr)}", flush=True)
                if actual.returncode:
                    print(actual.stderr.decode("utf-8", errors="backslashreplace"), flush=True)
                return actual
            with patch.dict(os.environ, clean, clear=True), patch.object(install_workflow, "capture_process", observed_capture):
                result = install_central(project, PACK, state=state, timeout=600)
                self.assertTrue(result["enabled"], result)
                self.assertFalse(result["conflicts"], result)
                assert_private(state)
                assert_private(state / "bindings")
                _, record = runtime_service.read_binding_record(state, project)
                self.assertTrue(record["enabled"])
                pin = record["runtime_binding"]
                self.assertEqual(set(pin), {"protocol_version", "content_id", "manifest_sha256"})
                core = runtime_store.load_core(pin, state)
                assert_private(state / "bindings" / (project_files.project_key(project) + ".json"), directory=False)
                for directory in ("lib", "product", "roles", "platforms", "templates", "manager"):
                    if directory == "lib":
                        self.assertEqual(sorted(path.name for path in (project / ".agent-workflow/lib").iterdir()),
                                         ["python_runtime.cjs", "python_runtime.sh", "windows-runtime.paths", "workflow_hooks.py"])
                    else:
                        self.assertFalse((project / ".agent-workflow" / directory).exists())
                names = project_files.skill_names(project_files.Resources(
                    core.root, project_files.json_bytes(pin), core.label, core))
                with project_files.Tree(project) as tree:
                    for host in (".agents/skills", ".claude/skills"):
                        for name in names:
                            relative = host + "/" + name
                            self.assertEqual(os.lstat(project / relative).st_reparse_tag, 0xA000000C)
                            project_files.validate_skill_link(tree, relative, tree.read(relative, skill_link=True), core)
                node = shutil.which("node.exe")
                self.assertIsNotNone(node)
                def invoke(*arguments):
                    return subprocess.run([node, str(project / project_files.WINDOWS_ENTRY),
                                           str(project / project_files.LAUNCHER), *arguments],
                                          cwd=project, env=clean, capture_output=True, timeout=120)
                checked = invoke("check")
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertEqual(json.loads(checked.stdout)["runtime_binding"], pin)
                read = invoke("--binding", json.dumps(pin), "read", "product/GLOBAL_CONSTRAINTS.md")
                self.assertEqual(read.returncode, 0, read.stdout + read.stderr)
                self.assertEqual(read.stdout, runtime_store.read_core_source(core, "product/GLOBAL_CONSTRAINTS.md"))
                helper = invoke("--binding", json.dumps(pin), "helper", "lib/project_profile_cli.py",
                                "roles", ".agent-workflow", ".")
                self.assertEqual(helper.returncode, 0, helper.stdout + helper.stderr)
                self.assertIn(b"xy-qa", helper.stdout)
                # 再次真实安装消费私有记录、既有软链和同内容核心，不只是首次新建。
                repeated = install_central(project, PACK, state=state, timeout=600)
                self.assertTrue(repeated["enabled"], repeated)
                self.assertEqual(repeated["runtime_binding"], pin)
            self.assertEqual(sentinel.read_bytes(), b"preserve ordinary user data")
            self.assertEqual((sentinel.stat().st_dev, sentinel.stat().st_ino), (before.st_dev, before.st_ino))
            print("真实中央 install/prepared桥/check/固定pin读取/Job helper/重复安装通过", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", required=True,
                        choices=("host-directory", "ordinary-denied", "ordinary-allowed",
                                 "ordinary-denied-only", "ordinary-restored", "backend-native", "backend-rename", "central-install"))
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    PROBE_ROOT, PROBE_MODE = Path(args.root).resolve(strict=True), args.probe
    # 新负向 fixture 只补缺失的软链拒绝与恢复事实，复用已经通过的目录
    # fsync，不能为了共享测试分组重复整轮已绿矩阵。
    methods = ([] if PROBE_MODE in {"ordinary-denied-only", "ordinary-restored"}
               else ["test_directory_durability_uses_real_backend"])
    if PROBE_MODE != "host-directory":
        methods.append("test_ordinary_token_and_directory_symlink_capability")
    backend_names = (("test_directory_symlink_read_rename_unlink_never_follows_target",
                      "test_exclusive_publication_moves_one_identity_without_hardlink_window")
                     if PROBE_MODE == "backend-rename" else
                     unittest.defaultTestLoader.getTestCaseNames(WindowsBackendNativeTest))
    suite = (unittest.TestSuite(WindowsBackendNativeTest(name) for name in backend_names)
             if PROBE_MODE in {"backend-native", "backend-rename"} else
             unittest.TestSuite(WindowsCapabilityProbe(name) for name in methods))
    if PROBE_MODE == "central-install":
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(WindowsCentralInstallTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
