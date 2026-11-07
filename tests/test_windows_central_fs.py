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


@unittest.skipUnless(os.name == "nt", "能力结论必须来自原生 Windows")
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", required=True,
                        choices=("host-directory", "ordinary-denied", "ordinary-allowed",
                                 "ordinary-denied-only", "ordinary-restored"))
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    PROBE_ROOT, PROBE_MODE = Path(args.root).resolve(strict=True), args.probe
    # 新负向 fixture 只补缺失的软链拒绝与恢复事实，复用已经通过的目录
    # fsync，不能为了共享测试分组重复整轮已绿矩阵。
    methods = ([] if PROBE_MODE in {"ordinary-denied-only", "ordinary-restored"}
               else ["test_directory_durability_uses_real_backend"])
    if PROBE_MODE != "host-directory":
        methods.append("test_ordinary_token_and_directory_symlink_capability")
    suite = unittest.TestSuite(WindowsCapabilityProbe(name) for name in methods)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
