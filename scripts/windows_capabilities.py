"""独立 Win32 能力探针：只使用标准库，不导入待适配的生产文件系统。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import platform
import secrets
import struct
import sys


# 常量来自 Windows SDK。目录权限逐项保留数值，避免 generic mask 的展开掩盖实际错误。
READ = 0x80000000
WRITE = 0x40000000
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
READ_ATTRIBUTES = 0x80
BACKUP_SEMANTICS = 0x02000000
OPEN_REPARSE_POINT = 0x00200000
SYMLINK_TAG = 0xA000000C
DIRECTORY_MASKS = (
    ("production_generic_read_write", READ | WRITE),
    ("generic_read", READ),
    ("read_attributes_read_control", READ_ATTRIBUTES | READ_CONTROL),
    ("directory_list_read_attributes_sync", 0x00120081),
    # 使用目录对应的 LIST_DIRECTORY、READ/WRITE_EA、TRAVERSE、DELETE_CHILD、
    # READ/WRITE_ATTRIBUTES 与标准权限；不请求 FILE_WRITE_DATA / FILE_APPEND_DATA。
    ("directory_metadata_specific", 0x001201F9),
)


class BasicInfo(C.Structure):
    _fields_ = [(name, C.c_int64) for name in
                ("creation_time", "access_time", "write_time", "change_time")] + [("attributes", W.DWORD)]


class SecurityAttributes(C.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", W.LPVOID), ("inherit", W.BOOL)]


class AclSizeInfo(C.Structure):
    _fields_ = [("ace_count", W.DWORD), ("bytes_in_use", W.DWORD), ("bytes_free", W.DWORD)]


class IoStatusValue(C.Union):
    _fields_ = [("status", C.c_int32), ("pointer", W.LPVOID)]


class IoStatusBlock(C.Structure):
    _fields_ = [("value", IoStatusValue), ("information", C.c_size_t)]


def error_record(error):
    """保留 API 原始错误码，避免把权限不足或不支持改写成成功。"""
    return {"ok": False, "error_type": type(error).__name__,
            "winerror": getattr(error, "winerror", None),
            "errno": getattr(error, "errno", None), "message": str(error)}


def attempt(operation):
    try:
        return {"ok": True, **operation()}
    except (OSError, ValueError) as error:
        return error_record(error)


class Win32:
    """此类只声明本探针实际调用的 ABI；所有句柄与 LocalAlloc 输出均在本层释放。"""
    def __init__(self):
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.security = C.WinDLL("advapi32", use_last_error=True)
        signatures = (
            (self.kernel, "CreateFileW", W.HANDLE, [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]),
            (self.kernel, "CloseHandle", W.BOOL, [W.HANDLE]),
            (self.kernel, "FlushFileBuffers", W.BOOL, [W.HANDLE]),
            (self.kernel, "WriteFile", W.BOOL, [W.HANDLE, W.LPCVOID, W.DWORD, C.POINTER(W.DWORD), W.LPVOID]),
            (self.kernel, "GetFileInformationByHandleEx", W.BOOL, [W.HANDLE, C.c_int, W.LPVOID, W.DWORD]),
            (self.kernel, "DeviceIoControl", W.BOOL, [W.HANDLE, W.DWORD, W.LPVOID, W.DWORD, W.LPVOID, W.DWORD, C.POINTER(W.DWORD), W.LPVOID]),
            (self.kernel, "CreateSymbolicLinkW", C.c_ubyte, [W.LPCWSTR, W.LPCWSTR, W.DWORD]),
            (self.kernel, "CreateDirectoryW", W.BOOL, [W.LPCWSTR, C.POINTER(SecurityAttributes)]),
            (self.kernel, "GetCurrentProcess", W.HANDLE, []),
            (self.kernel, "GetVolumePathNameW", W.BOOL, [W.LPCWSTR, W.LPWSTR, W.DWORD]),
            (self.kernel, "GetVolumeInformationW", W.BOOL, [W.LPCWSTR, W.LPWSTR, W.DWORD, C.POINTER(W.DWORD), C.POINTER(W.DWORD), C.POINTER(W.DWORD), W.LPWSTR, W.DWORD]),
            (self.kernel, "GetDriveTypeW", W.UINT, [W.LPCWSTR]),
            (self.kernel, "LocalFree", W.HLOCAL, [W.HLOCAL]),
            (self.security, "OpenProcessToken", W.BOOL, [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]),
            (self.security, "GetTokenInformation", W.BOOL, [W.HANDLE, C.c_int, W.LPVOID, W.DWORD, C.POINTER(W.DWORD)]),
            (self.security, "ConvertSidToStringSidW", W.BOOL, [W.LPVOID, C.POINTER(W.LPWSTR)]),
            (self.security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", W.BOOL, [W.LPCWSTR, W.DWORD, C.POINTER(W.LPVOID), C.POINTER(W.DWORD)]),
            (self.security, "GetSecurityInfo", W.DWORD, [W.HANDLE, C.c_int, W.DWORD, C.POINTER(W.LPVOID), W.LPVOID, C.POINTER(W.LPVOID), W.LPVOID, C.POINTER(W.LPVOID)]),
            (self.security, "SetSecurityInfo", W.DWORD, [W.HANDLE, C.c_int, W.DWORD, W.LPVOID, W.LPVOID, W.LPVOID, W.LPVOID]),
            (self.security, "GetSecurityDescriptorControl", W.BOOL, [W.LPVOID, C.POINTER(W.WORD), C.POINTER(W.DWORD)]),
            (self.security, "GetSecurityDescriptorDacl", W.BOOL, [W.LPVOID, C.POINTER(W.BOOL), C.POINTER(W.LPVOID), C.POINTER(W.BOOL)]),
            (self.security, "GetAclInformation", W.BOOL, [W.LPVOID, W.LPVOID, W.DWORD, C.c_int]),
            (self.security, "EqualSid", W.BOOL, [W.LPVOID, W.LPVOID]),
        )
        for library, name, result, arguments in signatures:
            function = getattr(library, name)
            function.restype, function.argtypes = result, arguments
        self.ntdll = C.WinDLL("ntdll", use_last_error=True)
        self.nt_flush = getattr(self.ntdll, "NtFlushBuffersFileEx", None)
        if self.nt_flush is not None:
            self.nt_flush.restype = C.c_int32
            self.nt_flush.argtypes = [W.HANDLE, W.ULONG, W.LPVOID, W.ULONG, C.POINTER(IoStatusBlock)]
        self.token = W.HANDLE()
        self.check(self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x8, C.byref(self.token)))
        try:
            self.user = self.token_information(1)
        except BaseException:
            self.kernel.CloseHandle(self.token)
            raise

    @staticmethod
    def check(result):
        if not result:
            raise C.WinError(C.get_last_error())
        return result

    def close(self):
        self.check(self.kernel.CloseHandle(self.token))

    def token_information(self, kind):
        length = W.DWORD()
        self.security.GetTokenInformation(self.token, kind, None, 0, C.byref(length))
        if not length.value:
            raise C.WinError(C.get_last_error())
        output = C.create_string_buffer(length.value)
        self.check(self.security.GetTokenInformation(self.token, kind, output, length, C.byref(length)))
        return output

    def elevation(self):
        value = self.token_information(20)  # TokenElevation，仅输出 Boolean，不记录 token/SID。
        return {"elevated": bool(C.cast(value, C.POINTER(W.DWORD))[0])}

    @property
    def user_sid(self):
        return C.cast(self.user, C.POINTER(W.LPVOID))[0]

    @contextmanager
    def handle(self, path, access, *, directory=False, disposition=3, extra_flags=0):
        flags = OPEN_REPARSE_POINT | (BACKUP_SEMANTICS if directory else 0) | extra_flags
        handle = self.kernel.CreateFileW(str(path), access, 7, None, disposition, flags, None)
        if handle == W.HANDLE(-1).value:
            raise C.WinError(C.get_last_error())
        try:
            yield handle
        finally:
            self.check(self.kernel.CloseHandle(handle))

    @contextmanager
    def private_descriptor(self, *, include_admins=True):
        # 安全描述符在 CreateDirectory 时一起生效；不先创建继承 Everyone 的目录再收紧。
        # 只准当前 token 用户、SYSTEM 与 Administrators，且阻断父目录 DACL 继承。
        sid_text = W.LPWSTR()
        descriptor = W.LPVOID()
        self.check(self.security.ConvertSidToStringSidW(self.user_sid, C.byref(sid_text)))
        try:
            # 提升 token 的默认 owner 可能是 Administrators；这里显式指定当前用户，
            # 使“owner 与 token user 一致”的检查在普通/提升会话中含义相同。
            sddl = "O:" + sid_text.value + "D:P(A;OICI;FA;;;" + sid_text.value + ")(A;OICI;FA;;;SY)"
            if include_admins:
                sddl += "(A;OICI;FA;;;BA)"
            self.check(self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None))
            yield descriptor
        finally:
            if descriptor.value:
                self.kernel.LocalFree(descriptor)
            self.kernel.LocalFree(C.cast(sid_text, W.HLOCAL))

    def private_workspace(self, parent):
        with self.private_descriptor() as descriptor:
            attributes = SecurityAttributes(C.sizeof(SecurityAttributes), descriptor, False)
            # 高熵名 + CreateDirectory 排他创建；碰撞明确失败，不复用其他人的目录。
            root = parent / ("awf-windows-capabilities-" + secrets.token_hex(16))
            self.check(self.kernel.CreateDirectoryW(str(root), C.byref(attributes)))
            return root

    def volume(self, path):
        root = C.create_unicode_buffer(32768)
        self.check(self.kernel.GetVolumePathNameW(str(path), root, len(root)))
        filesystem = C.create_unicode_buffer(256)
        flags, serial, maximum = W.DWORD(), W.DWORD(), W.DWORD()
        self.check(self.kernel.GetVolumeInformationW(root.value, None, 0, C.byref(serial), C.byref(maximum), C.byref(flags), filesystem, len(filesystem)))
        drive_type = self.kernel.GetDriveTypeW(root.value)
        return {"filesystem": filesystem.value, "drive_type": drive_type,
                "local_ntfs": filesystem.value.upper() == "NTFS" and drive_type == 3,
                "filesystem_flags": f"0x{flags.value:08x}"}

    def flush_directory(self, path, mask, *, write_through=False):
        extra_flags = 0x80000000 if write_through else 0
        row = {"access_mask": f"0x{mask:08x}", "write_through": write_through,
               "create_flags": f"0x{OPEN_REPARSE_POINT | BACKUP_SEMANTICS | extra_flags:08x}",
               "open": {"ok": False}, "flush": {"executed": False},
               "nt_flush_ex": {"executed": False, "symbol_available": self.nt_flush is not None}}
        try:
            with self.handle(path, mask, directory=True, extra_flags=extra_flags) as handle:
                row["open"] = {"ok": True}
                row["flush"] = {"executed": True, **attempt(lambda: {"api_return": bool(self.check(self.kernel.FlushFileBuffers(handle)))})}
                if self.nt_flush is not None:
                    # 只记录同一自有目录 handle 的原始 NTSTATUS/IO_STATUS_BLOCK；不把未承诺的
                    # 用户态 NT 调用当作产品屏障替代，也不请求卷句柄、提权或驱动。
                    status_block = IoStatusBlock()
                    status_block.value.status = 0x103
                    status = self.nt_flush(handle, 0, None, 0, C.byref(status_block))
                    row["nt_flush_ex"] = {"executed": True, "symbol_available": True,
                        "flags": 0, "ntstatus": f"0x{status & 0xffffffff:08x}",
                        "io_status": f"0x{status_block.value.status & 0xffffffff:08x}",
                        "io_information": str(status_block.information),
                        "returned_status_success": status == 0,
                        "supported_user_mode_durability_contract_proven": False}
        except OSError as error:
            # 打开失败和 flush 失败是不同证据，不能只留下一个笼统的 unsupported。
            row["handle_close_error" if row["open"].get("ok") else "open"] = error_record(error)
        return row

    def basic_info(self, path, *, directory=False):
        with self.handle(path, READ_ATTRIBUTES, directory=directory) as handle:
            info = BasicInfo()
            self.check(self.kernel.GetFileInformationByHandleEx(handle, 0, C.byref(info), C.sizeof(info)))
            return {"change_time_100ns": str(info.change_time), "write_time_100ns": str(info.write_time),
                    "attributes": f"0x{info.attributes:08x}"}

    def write_and_flush(self, path, *, create=False):
        with self.handle(path, READ | WRITE, disposition=1 if create else 3) as handle:
            body = b"awf capability fixture\r\n"
            written = W.DWORD()
            self.check(self.kernel.WriteFile(handle, body, len(body), C.byref(written), None))
            if written.value != len(body):
                raise ValueError("WriteFile returned a short write")
            self.check(self.kernel.FlushFileBuffers(handle))
            return {"bytes_written": written.value, "flush_api_return": True}

    def acl(self, path, *, rewrite=False):
        with self.handle(path, READ_CONTROL | READ_ATTRIBUTES | (WRITE_DAC if rewrite else 0), directory=True) as handle:
            owner, dacl, descriptor = W.LPVOID(), W.LPVOID(), W.LPVOID()
            error = self.security.GetSecurityInfo(handle, 1, 0x5, C.byref(owner), None, C.byref(dacl), None, C.byref(descriptor))
            if error:
                raise C.WinError(error)
            try:
                if not dacl.value:
                    raise ValueError("NULL DACL does not establish private access")
                control, revision, size = W.WORD(), W.DWORD(), AclSizeInfo()
                self.check(self.security.GetSecurityDescriptorControl(descriptor, C.byref(control), C.byref(revision)))
                self.check(self.security.GetAclInformation(dacl, C.byref(size), C.sizeof(size), 2))
                if rewrite:
                    # 只把本夹具的原 DACL 原样写回并保留 protected 状态；不动用户对象。
                    flags = 0x80000004 if control.value & 0x1000 else 0x20000004
                    error = self.security.SetSecurityInfo(handle, 1, flags, None, None, dacl, None)
                    if error:
                        raise C.WinError(error)
                return {"owner_matches_token_user": bool(self.security.EqualSid(owner, self.user_sid)),
                        "dacl_present": True, "dacl_protected": bool(control.value & 0x1000),
                        "ace_count": size.ace_count, "same_dacl_write": rewrite}
            finally:
                self.kernel.LocalFree(descriptor)

    def acl_change_time(self, path):
        # 对独立空夹具实际收窄 DACL（移除 Administrators ACE，并保护继承），然后
        # 恢复原 DACL/继承状态。根目录权限不变，当前用户的 full access 始终保留。
        # ChangeTime 是否变化只记实测；不把 API 成功或原样写回当作时间合同证明。
        with self.handle(path, READ_CONTROL | WRITE_DAC | READ_ATTRIBUTES, directory=True) as handle:
            original, original_dacl = W.LPVOID(), W.LPVOID()
            error = self.security.GetSecurityInfo(handle, 1, 0x4, None, None, C.byref(original_dacl), None, C.byref(original))
            if error:
                raise C.WinError(error)
            changed = False
            try:
                control, revision = W.WORD(), W.DWORD()
                self.check(self.security.GetSecurityDescriptorControl(original, C.byref(control), C.byref(revision)))
                before, before_acl = self.basic_info(path, directory=True), self.acl(path)
                with self.private_descriptor(include_admins=False) as replacement:
                    present, defaulted, replacement_dacl = W.BOOL(), W.BOOL(), W.LPVOID()
                    self.check(self.security.GetSecurityDescriptorDacl(replacement, C.byref(present), C.byref(replacement_dacl), C.byref(defaulted)))
                    if not present.value or not replacement_dacl.value:
                        raise ValueError("replacement private DACL is absent")
                    error = self.security.SetSecurityInfo(handle, 1, 0x80000004, None, None, replacement_dacl, None)
                    if error:
                        raise C.WinError(error)
                    changed = True
                    after, after_acl = self.basic_info(path, directory=True), self.acl(path)
            finally:
                try:
                    if changed:
                        restore_flags = 0x80000004 if control.value & 0x1000 else 0x20000004
                        error = self.security.SetSecurityInfo(handle, 1, restore_flags, None, None, original_dacl, None)
                        if error:
                            raise C.WinError(error)
                finally:
                    self.kernel.LocalFree(original)
        return {"mutation": "remove Administrators ACE and protect owned directory DACL",
                "before": before, "after": after, "before_acl": before_acl, "after_acl": after_acl,
                "change_time_changed": before["change_time_100ns"] != after["change_time_100ns"],
                "original_dacl_restored": True, "restored_acl": self.acl(path)}

    def symlink(self, link, target, flags):
        self.check(self.kernel.CreateSymbolicLinkW(str(link), str(target), flags))
        with self.handle(link, 0, directory=True) as handle:
            output, returned = C.create_string_buffer(16384), W.DWORD()
            self.check(self.kernel.DeviceIoControl(handle, 0x000900A8, None, 0, output, len(output), C.byref(returned), None))
            raw = output.raw[:returned.value]
        if len(raw) < 20:
            raise ValueError("reparse buffer is shorter than symbolic-link header")
        tag, data_length, _ = struct.unpack_from("<IHH", raw)
        if tag != SYMLINK_TAG or data_length + 8 > len(raw):
            raise ValueError(f"unexpected reparse tag/length: 0x{tag:08x}/{data_length}")
        sub_offset, sub_length, print_offset, print_length, link_flags = struct.unpack_from("<HHHHI", raw, 8)
        path_bytes = raw[20:8 + data_length]
        names = {}
        for key, offset, length in (("substitute_name", sub_offset, sub_length), ("print_name", print_offset, print_length)):
            if offset % 2 or length % 2 or offset + length > len(path_bytes):
                raise ValueError("invalid reparse name boundary")
            names[key] = path_bytes[offset:offset + length].decode("utf-16-le")
        return {"create_flags": f"0x{flags:08x}", "tag": f"0x{tag:08x}",
                "reparse_flags": link_flags, **names, "os_readlink_target": os.readlink(link),
                "requested_target": str(target)}


def collect(api, fixtures):
    report = {"directory_flush": [], "file_flush": {}, "change_time": {}, "acl": {}, "directory_symlink": []}
    report["acl"] = attempt(lambda: api.acl(fixtures, rewrite=True))
    acl_target = fixtures / "acl-target"
    acl_target.mkdir()
    report["dacl_change_time"] = attempt(lambda: api.acl_change_time(acl_target))
    for name, mask in DIRECTORY_MASKS:
        for write_through in (False, True):
            report["directory_flush"].append({"name": name, **api.flush_directory(fixtures, mask, write_through=write_through)})
    leaf = fixtures / "flush-file"
    report["file_flush"] = attempt(lambda: api.write_and_flush(leaf, create=True))
    if report["file_flush"]["ok"]:
        def change_time():
            before = api.basic_info(leaf)
            api.write_and_flush(leaf)
            after = api.basic_info(leaf)
            return {"before": before, "after": after,
                    "changed": before["change_time_100ns"] != after["change_time_100ns"]}
        report["change_time"] = attempt(change_time)
    else:
        report["change_time"] = {"executed": False, "reason": "file creation/flush failed"}
    target = fixtures / "symlink-target"
    target.mkdir()
    for name, flags in (("directory", 1), ("directory_allow_unprivileged", 3)):
        link = fixtures / ("link-" + name)
        try:
            report["directory_symlink"].append({"name": name, "create_flags": f"0x{flags:08x}",
                                                **attempt(lambda: api.symlink(link, target, flags))})
        finally:
            # 目标仅为本探针创建的空目录。删除的是链接自身，绝不递归追随它。
            if os.path.lexists(link):
                os.rmdir(link)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="在自建私有临时目录探测真实 Win32 能力；report-produced 不代表支持 PASS。")
    parser.add_argument("--output-parent", type=Path,
                        help="已有绝对父目录（默认 TEMP/TMP）；其下排他新建私有报告目录和独立 fixtures")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11) or os.name != "nt":
        print(json.dumps({"status": "not-run", "support_status": "NOT_EVALUATED",
                          "reason": "requires native Windows and an explicitly selected Python >= 3.11"}))
        return 2
    report = {"schema_version": 1, "status": "report-failed", "support_status": "NOT_EVALUATED",
              "scope": "capabilities-only", "power_loss_durability_proven": False,
              "environment": {"os": platform.system(), "release": platform.release(),
                              "version": platform.version(), "machine": platform.machine(),
                              "python": platform.python_version(), "pointer_bits": C.sizeof(W.HANDLE) * 8,
                              "windows_product_type": sys.getwindowsversion().product_type}}
    api, root, fixtures = None, None, None
    exit_code = 1
    try:
        api = Win32()
        report["environment"]["token_elevation"] = attempt(api.elevation)
        # 不调用 tempfile.gettempdir() 的外部可写探测；帮助/平台拒绝都不创建文件。
        # 父目录仅定位本次独占根，绝不在它本身测试写入或调整 ACL。
        parent_value = args.output_parent or os.environ.get("TEMP") or os.environ.get("TMP")
        if parent_value is None:
            raise ValueError("pass --output-parent or configure an existing TEMP/TMP directory")
        parent = Path(parent_value)
        if not parent.is_absolute() or not parent.is_dir():
            raise ValueError("output-parent must be an existing absolute directory")
        report["volume"] = attempt(lambda: api.volume(parent))
        if not report["volume"].get("local_ntfs"):
            # UNC/远程/未知卷不创建夹具；仍在 stdout 留下明确负结果。
            raise ValueError("probe writes require a verified fixed local NTFS volume")
        root = api.private_workspace(parent)
        report["workspace"] = str(root)
        report["report_file"] = str(root / "capabilities.json")
        report["workspace_acl"] = attempt(lambda: api.acl(root))
        if not (report["workspace_acl"].get("owner_matches_token_user") and report["workspace_acl"].get("dacl_protected")):
            raise ValueError("private workspace owner/protected DACL could not be verified")
        fixtures = root / "fixtures"
        fixtures.mkdir()
        report["capabilities"] = collect(api, fixtures)
        report["status"], exit_code = "report-produced", 0
    except (OSError, ValueError) as error:
        report["fatal_error"] = error_record(error)
    finally:
        if fixtures is not None:
            # 只清理固定名且由本脚本创建的空夹具，不用 rmtree 扫描未知内容。
            # 清理失败会保留路径和原因，避免静默丢失证据或扩大删除范围。
            def cleanup():
                for name in ("link-directory", "link-directory_allow_unprivileged"):
                    path = fixtures / name
                    if os.path.lexists(path):
                        os.rmdir(path)
                (fixtures / "flush-file").unlink(missing_ok=True)
                target = fixtures / "symlink-target"
                if target.exists():
                    target.rmdir()
                acl_target = fixtures / "acl-target"
                if acl_target.exists():
                    acl_target.rmdir()
                fixtures.rmdir()
                return {"fixtures_removed": True}
            report["cleanup"] = attempt(cleanup)
            if not report["cleanup"]["ok"]:
                report["status"], exit_code = "report-failed", 1
        if api is not None:
            report["handle_cleanup"] = attempt(lambda: (api.close() or {}))
            if not report["handle_cleanup"]["ok"]:
                report["status"], exit_code = "report-failed", 1
    body = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if root is not None:
        # 用 x 模式拒绝覆盖同名报告；完整 stdout 是报告写入失败时仍可回收的证据。
        try:
            with (root / "capabilities.json").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(body)
        except OSError as error:
            report["report_write_error"] = error_record(error)
            report["status"], exit_code = "report-failed", 1
            body = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(body, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
