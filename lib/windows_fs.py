"""Handle-anchored Windows I/O for the project runtime (no global os patches).

Directory handles deny delete sharing for their entire lifetime: every ancestor
stays pinned while a path-based Win32 operation runs. Reparse points, remote
volumes and multi-link files are refused, not treated as POSIX no-follow support.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections import namedtuple
import ctypes
import hashlib
import os as _os
from pathlib import Path, PureWindowsPath
import re
import stat as _stat
from types import MappingProxyType, SimpleNamespace


DWORD = ctypes.c_uint32
HANDLE = ctypes.c_void_p
BOOL = ctypes.c_int32
INVALID_HANDLE = ctypes.c_void_p(-1).value
READ, WRITE, DELETE = 0x80000000, 0x40000000, 0x10000
SHARE_READ, SHARE_WRITE, SHARE_DELETE = 1, 2, 4
ATTR_DIRECTORY, ATTR_REPARSE = 0x10, 0x400
BACKUP_SEMANTICS, OPEN_REPARSE_POINT = 0x02000000, 0x00200000
NOFOLLOW, DIRECTORY, NONBLOCK = 0x10000000, 0x20000000, 0x40000000
_EPOCH = 116444736000000000
READ_CONTROL = 0x20000
_LIMIT = 4 * 1024 * 1024


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", DWORD), ("descriptor", HANDLE), ("inherit", BOOL)]


class _Time(ctypes.Structure):
    _fields_ = [("low", DWORD), ("high", DWORD)]


class _Info(ctypes.Structure):
    _fields_ = [("attributes", DWORD), ("created", _Time), ("accessed", _Time),
               ("modified", _Time), ("volume", DWORD), ("size_high", DWORD),
               ("size_low", DWORD), ("links", DWORD), ("index_high", DWORD),
               ("index_low", DWORD)]


class _BasicInfo(ctypes.Structure):
    _fields_ = [("created", ctypes.c_int64), ("accessed", ctypes.c_int64),
               ("modified", ctypes.c_int64), ("changed", ctypes.c_int64),
               ("attributes", DWORD)]


class _RenameInfo(ctypes.Structure):
    _fields_ = [("flags", DWORD), ("root", HANDLE), ("length", DWORD),
                ("name", ctypes.c_uint16 * 1)]


class _DirectoryInfo(ctypes.Structure):
    _fields_ = [("next", DWORD), ("index", DWORD), ("created", ctypes.c_int64),
               ("accessed", ctypes.c_int64), ("modified", ctypes.c_int64),
               ("changed", ctypes.c_int64), ("size", ctypes.c_int64),
               ("allocation", ctypes.c_int64), ("attributes", DWORD),
               ("name_length", DWORD), ("ea_size", DWORD),
               ("short_length", ctypes.c_uint8), ("short_name", ctypes.c_uint16 * 12),
               ("file_id", ctypes.c_int64), ("name", ctypes.c_uint16 * 1)]


_api_value = None


def _api():
    global _api_value
    if _api_value is not None:
        return _api_value
    if _os.name != "nt":
        raise OSError("Windows handle I/O requires native Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    prototypes = {
        "CreateFileW": (HANDLE, [ctypes.c_wchar_p, DWORD, DWORD, HANDLE, DWORD, DWORD, HANDLE]),
        "CloseHandle": (BOOL, [HANDLE]),
        "CreateDirectoryW": (BOOL, [ctypes.c_wchar_p, HANDLE]),
        "GetFileInformationByHandle": (BOOL, [HANDLE, ctypes.POINTER(_Info)]),
        "GetFileInformationByHandleEx": (BOOL, [HANDLE, ctypes.c_int, HANDLE, DWORD]),
        "GetVolumeInformationByHandleW": (BOOL, [HANDLE, ctypes.c_wchar_p, DWORD, HANDLE,
                                                HANDLE, HANDLE, ctypes.c_wchar_p, DWORD]),
        "GetDriveTypeW": (DWORD, [ctypes.c_wchar_p]),
        "DeviceIoControl": (BOOL, [HANDLE, DWORD, HANDLE, DWORD, HANDLE, DWORD,
                                  ctypes.POINTER(DWORD), HANDLE]),
        "CreateSymbolicLinkW": (ctypes.c_uint8, [ctypes.c_wchar_p, ctypes.c_wchar_p, DWORD]),
        "FlushFileBuffers": (BOOL, [HANDLE]),
        "ReadFile": (BOOL, [HANDLE, HANDLE, DWORD, ctypes.POINTER(DWORD), HANDLE]),
        "SetFileInformationByHandle": (BOOL, [HANDLE, ctypes.c_int, HANDLE, DWORD]),
        "CreateMutexW": (HANDLE, [HANDLE, BOOL, ctypes.c_wchar_p]),
        "WaitForSingleObject": (DWORD, [HANDLE, DWORD]),
        "ReleaseMutex": (BOOL, [HANDLE]),
        "GetCurrentProcess": (HANDLE, []),
        "GetFinalPathNameByHandleW": (DWORD, [HANDLE, ctypes.c_wchar_p, DWORD, DWORD]),
        "LocalFree": (HANDLE, [HANDLE]),
    }
    for name, (result, arguments) in prototypes.items():
        method = getattr(kernel, name)
        method.restype, method.argtypes = result, arguments
    security_prototypes = {
        "OpenProcessToken": (BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
        "GetTokenInformation": (BOOL, [HANDLE, DWORD, HANDLE, DWORD, ctypes.POINTER(DWORD)]),
        "LookupPrivilegeValueW": (BOOL, [ctypes.c_wchar_p, ctypes.c_wchar_p, HANDLE]),
        "ConvertSidToStringSidW": (BOOL, [HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]),
        "ConvertStringSidToSidW": (BOOL, [ctypes.c_wchar_p, ctypes.POINTER(HANDLE)]),
        "EqualSid": (BOOL, [HANDLE, HANDLE]),
        "IsValidSid": (BOOL, [HANDLE]),
        "GetLengthSid": (DWORD, [HANDLE]),
        "IsValidAcl": (BOOL, [HANDLE]),
        "GetAclInformation": (BOOL, [HANDLE, HANDLE, DWORD, DWORD]),
        "GetAce": (BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
        "ConvertStringSecurityDescriptorToSecurityDescriptorW":
            (BOOL, [ctypes.c_wchar_p, DWORD, ctypes.POINTER(HANDLE), HANDLE]),
        "GetSecurityDescriptorDacl":
            (BOOL, [HANDLE, ctypes.POINTER(BOOL), ctypes.POINTER(HANDLE), ctypes.POINTER(BOOL)]),
        "GetSecurityDescriptorOwner": (BOOL, [HANDLE, ctypes.POINTER(HANDLE), ctypes.POINTER(BOOL)]),
        "GetSecurityDescriptorControl": (BOOL, [HANDLE, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(DWORD)]),
        "SetSecurityInfo": (DWORD, [HANDLE, DWORD, DWORD, HANDLE, HANDLE, HANDLE, HANDLE]),
        "GetSecurityInfo": (DWORD, [HANDLE, DWORD, DWORD, HANDLE, HANDLE,
                                    ctypes.POINTER(HANDLE), HANDLE, ctypes.POINTER(HANDLE)]),
    }
    for name, (result, arguments) in security_prototypes.items():
        method = getattr(security, name)
        method.restype, method.argtypes = result, arguments
    _api_value = SimpleNamespace(kernel=kernel, security=security)
    return _api_value


def _check(result, path=None):
    if not result:
        error = ctypes.WinError(ctypes.get_last_error())
        if path is not None:
            error.filename = str(path)
        raise error
    return result


def _close(handle):
    _check(_api().kernel.CloseHandle(handle))


def validate_component(name: str) -> str:
    """Reject raw names before Win32 can truncate or normalize them."""
    if not isinstance(name, str):
        raise ValueError("Windows path components must be text")
    stem = name.split(".", 1)[0].upper()
    if (not name or name in {".", ".."} or name.rstrip(" .") != name
            or any(ord(char) < 32 or char in '/\\:<>"|?*' for char in name)
            or stem in {"CON", "PRN", "AUX", "NUL"}
            or (len(stem) == 4 and stem[:3] in {"COM", "LPT"}
                and stem[3] in "123456789¹²³")):
        raise ValueError(f"ambiguous Windows path component: {name!r}")
    return name


def absolute_path(path) -> Path:
    raw = _os.fspath(path)
    if not isinstance(raw, str):
        raise ValueError("Windows anchored paths must be text")
    windows = PureWindowsPath(raw)
    if ("\x00" in raw or windows.drive.startswith("\\\\")
            or raw.startswith(("\\\\?\\", "\\\\.\\"))):
        raise ValueError("only local Windows drive paths are supported")
    # PureWindowsPath/abspath normalize dot components. Check the raw spelling
    # first so directory-relative and absolute operations have one contract.
    for part in raw[len(windows.drive):].replace("\\", "/").split("/"):
        if part:
            validate_component(part)
    result = Path(_os.path.abspath(raw))
    for part in result.parts[1:]:
        validate_component(part)
    return result


def _open_handle(path, access=0x80, *, directory=False, create=False, exclusive=False,
                 security=None, sharing=SHARE_READ | SHARE_WRITE):
    path = absolute_path(path)
    disposition = 1 if exclusive else (4 if create else 3)
    handle = _api().kernel.CreateFileW(
        str(path), access, sharing, security, disposition,
        OPEN_REPARSE_POINT | BACKUP_SEMANTICS, None,
    )
    if handle == INVALID_HANDLE:
        _check(False, path)
    try:
        info = _information(handle)
        if info.attributes & ATTR_REPARSE:
            raise ValueError(f"reparse point is forbidden: {path}")
        if bool(info.attributes & ATTR_DIRECTORY) != directory:
            raise ValueError(f"unexpected Windows file type: {path}")
        if not directory and info.links != 1:
            raise ValueError(f"single-link regular file required: {path}")
    except BaseException:
        _close(handle)
        raise
    return handle


def _information(handle):
    info = _Info()
    _check(_api().kernel.GetFileInformationByHandle(handle, ctypes.byref(info)))
    return info


def _basic_information(handle):
    basic = _BasicInfo()
    _check(_api().kernel.GetFileInformationByHandleEx(
        handle, 0, ctypes.byref(basic), ctypes.sizeof(basic)))
    return basic


def project_mode(mode: int, *, directory=False) -> int:
    """将请求权限投影到后端能够实际证明的模式，不把 POSIX 位当作 ACL。

    私有权限由精确 user/SYSTEM DACL 证明；普通模式只说明读写属性，不能据此
    推断任意组或其他用户具备访问权。所有安全决定仍调用真实 ACL 私有断言。
    """
    if type(mode) is not int or not 0 <= mode <= 0o7777 or not mode & 0o200:
        raise ValueError("read-only POSIX mode needs explicit Windows ACL policy")
    return (0o700 if directory else 0o600) if not mode & 0o077 else (0o777 if directory else 0o666)


def _canonical_security(owner: bytes, control: int, acl: bytes) -> bytes:
    """以固定版本、长度和原始 ACE 顺序描述权限，排除 SD 地址与空闲尾部。

    ACE 顺序参与 Windows 访问判断，不能排序或合并。ACL 的未使用尾部、头部
    padding 和 SD 内部偏移不代表权限变化，不进入摘要；边界错误一律拒绝。
    本纯函数也随独立初读闭包嵌入，避免两条可信读取链采用不同规范。
    """
    if (not isinstance(owner, bytes) or not 8 <= len(owner) <= 68
            or owner[0] != 1 or owner[1] > 15 or len(owner) != 8 + owner[1] * 4
            or len(acl) < 8 or len(acl) > 65535 or acl[0] not in (2, 4)
            or not control & 4):
        raise ValueError("invalid bounded Windows owner or DACL")
    size, count = int.from_bytes(acl[2:4], "little"), int.from_bytes(acl[4:6], "little")
    if size != len(acl):
        raise ValueError("invalid Windows ACL size")
    result = bytearray(b"AWF-SECURITY-1\0")
    result.extend((control & 0x150D).to_bytes(2, "little"))
    result.extend(len(owner).to_bytes(2, "little"))
    result.extend(owner)
    result.extend(bytes((acl[0],)))
    result.extend(count.to_bytes(2, "little"))
    offset = 8
    for _ in range(count):
        if offset + 4 > size:
            raise ValueError("truncated Windows ACE header")
        length = int.from_bytes(acl[offset + 2:offset + 4], "little")
        if length < 4 or length % 4 or offset + length > size:
            raise ValueError("invalid bounded Windows ACE")
        result.extend(length.to_bytes(2, "little"))
        result.extend(acl[offset:offset + length])
        offset += length
    return bytes(result)


def _sid_bytes(text):
    pointer = HANDLE()
    api = _api()
    _check(api.security.ConvertStringSidToSidW(text, ctypes.byref(pointer)))
    try:
        return ctypes.string_at(pointer, api.security.GetLengthSid(pointer))
    finally:
        api.kernel.LocalFree(pointer)


@contextmanager
def _security_policy(handle, *, object_type=1):
    """只在已打开句柄内拥有原 SD；持久记录仅保存独立 64 字符 hex 摘要。"""
    api = _api()
    descriptor, owner, acl = HANDLE(), HANDLE(), HANDLE()
    error = api.security.GetSecurityInfo(handle, object_type, 5, ctypes.byref(owner), None,
                                         ctypes.byref(acl), None, ctypes.byref(descriptor))
    if error:
        raise ctypes.WinError(error)
    try:
        if not owner.value or not api.security.IsValidSid(owner) or not acl.value:
            raise ValueError("Windows owner and non-null DACL are required")
        length = api.security.GetLengthSid(owner)
        if not 8 <= length <= 68 or not api.security.IsValidAcl(acl):
            raise ValueError("invalid bounded Windows owner or DACL")
        control, revision = ctypes.c_uint16(), DWORD()
        _check(api.security.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)))
        header = ctypes.string_at(acl, 8)
        size = int.from_bytes(header[2:4], "little")
        if not 8 <= size <= 65535:
            raise ValueError("invalid bounded Windows ACL size")
        owner_bytes, acl_bytes = ctypes.string_at(owner, length), ctypes.string_at(acl, size)
        canonical = _canonical_security(owner_bytes, control.value, acl_bytes)
        yield SimpleNamespace(descriptor=descriptor, acl=acl, owner=owner_bytes,
                              control=control.value, acl_bytes=acl_bytes,
                              fingerprint=hashlib.sha256(canonical).hexdigest(),
                              dacl_key=_canonical_security(b"\1\0" + b"\0" * 6,
                                                           control.value & ~1, acl_bytes))
    finally:
        api.kernel.LocalFree(descriptor)


def _private_policy_bytes(owner: bytes, control: int, acl: bytes, user: bytes, *, object_type=1) -> bool:
    """唯一纯私有策略：当前用户 owner、protected DACL、用户/SYSTEM 两条全权 ACE。

    既有句柄后端与未加载 core 的初读闭包共用这份代码。ACE 顺序不影响此
    权限集合的准入，但完整安全摘要仍保留顺序/flags，不能据此免除 ACL CAS。
    """
    if owner != user or not control & 0x1000 or len(acl) < 8:
        return False
    if int.from_bytes(acl[4:6], "little") != 2:
        return False
    wanted = {user, bytes.fromhex("010100000000000512000000")}
    offset, found = 8, set()
    for _ in range(2):
        if offset + 4 > len(acl):
            return False
        size = int.from_bytes(acl[offset + 2:offset + 4], "little")
        ace = acl[offset:offset + size]
        rights = int.from_bytes(ace[4:8], "little")
        all_access = 0x1F01FF if object_type == 1 else 0x1F0001
        if (size < 16 or offset + size > len(acl) or ace[0] != 0 or ace[1] & ~0x07
                or rights not in (0x10000000, all_access) or ace[8:] not in wanted):
            return False
        found.add(ace[8:])
        offset += size
    return found == wanted


def _policy_is_private(policy, *, object_type=1):
    return _private_policy_bytes(policy.owner, policy.control, policy.acl_bytes,
                                 _sid_bytes(current_sid()), object_type=object_type)


def _stat_info(info, basic, *, private=False):
    def ns(value):
        return ((value.high << 32 | value.low) - _EPOCH) * 100
    accessed, modified = ns(info.accessed), ns(info.modified)
    changed = (basic.changed - _EPOCH) * 100
    mode = _stat.S_IFDIR if info.attributes & ATTR_DIRECTORY else _stat.S_IFREG
    if info.attributes & ATTR_REPARSE:
        mode = _stat.S_IFLNK
    mode |= (0o400 if info.attributes & 1 else 0o600) if private else (0o444 if info.attributes & 1 else 0o666)
    if _stat.S_ISDIR(mode):
        mode = _stat.S_IFDIR | (0o700 if private else 0o777)
    extra = {"st_atime_ns": accessed, "st_mtime_ns": modified, "st_ctime_ns": changed}
    # stat_result 的平台附加字段由宿主 Python 固定；可移植合同检查不能向
    # macOS 的该类型塞入 Windows 专属字段。原生 Windows 始终保留真实属性。
    if hasattr(_os.stat_result, "st_file_attributes"):
        extra["st_file_attributes"] = info.attributes
    return _os.stat_result(
        (mode, info.index_high << 32 | info.index_low, info.volume, info.links,
         0, 0, info.size_high << 32 | info.size_low,
         accessed / 1e9, modified / 1e9, changed / 1e9),
        extra,
    )


class Directory:
    """Pin all ancestors, including this directory, against rename/replacement."""

    def __init__(self, path):
        self.path = absolute_path(path)
        self.handles = []
        try:
            current = Path(self.path.anchor)
            for part in (None, *self.path.parts[1:]):
                if part is not None:
                    current /= part
                self.handles.append(_open_handle(current, READ_CONTROL | 0x81, directory=True))
            filesystem = ctypes.create_unicode_buffer(32)
            _check(_api().kernel.GetVolumeInformationByHandleW(
                self.handle, None, 0, None, None, None, filesystem, len(filesystem)))
            final_path = ctypes.create_unicode_buffer(32768)
            count = _check(_api().kernel.GetFinalPathNameByHandleW(self.handle, final_path, len(final_path), 0))
            if (count >= len(final_path) or not final_path.value.startswith("\\\\?\\")
                    or len(final_path.value) < 7 or final_path.value[5:7] != ":\\"
                    or filesystem.value != "NTFS" or _api().kernel.GetDriveTypeW(self.path.anchor) != 3):
                raise ValueError("Windows project writes require local NTFS")
        except BaseException:
            self.close()
            raise

    @property
    def handle(self):
        return self.handles[-1]

    @property
    def identity(self):
        info = _information(self.handle)
        return (info.volume, info.index_high << 32 | info.index_low)

    def child(self, name):
        return self.path / validate_component(name)

    def close(self):
        while self.handles:
            _close(self.handles.pop())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def current_sid() -> str:
    api = _api()
    token = HANDLE()
    _check(api.security.OpenProcessToken(api.kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
    try:
        required = DWORD()
        api.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        data = ctypes.create_string_buffer(required.value)
        _check(api.security.GetTokenInformation(token, 1, data, len(data), ctypes.byref(required)))
        sid = ctypes.cast(data, ctypes.POINTER(HANDLE)).contents
        text = ctypes.c_wchar_p()
        _check(api.security.ConvertSidToStringSidW(sid, ctypes.byref(text)))
        try:
            return text.value
        finally:
            api.kernel.LocalFree(ctypes.cast(text, HANDLE))
    finally:
        _close(token)


@contextmanager
def private_security(*, inherit=True):
    # 普通私有目录仍给后代继承 OI/CI；新建 Skill 软链只保护链接这个对象，
    # 不给 target 传播权限。该可选项只改变新 SD 的 ACE flags，默认合同不变。
    api = _api()
    descriptor = HANDLE()
    sid = current_sid()
    flags = "OICI" if inherit else ""
    _check(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        f"O:{sid}D:P(A;{flags};GA;;;{sid})(A;{flags};GA;;;SY)", 1, ctypes.byref(descriptor), None))
    try:
        yield descriptor
    finally:
        api.kernel.LocalFree(descriptor)


def _dacl(descriptor):
    present, defaulted, acl = BOOL(), BOOL(), HANDLE()
    _check(_api().security.GetSecurityDescriptorDacl(
        descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)))
    if not present.value or not acl.value:
        raise ValueError("a non-null Windows DACL is required")
    return acl


def _token_elevated():
    api, token = _api(), HANDLE()
    _check(api.security.OpenProcessToken(api.kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
    try:
        elevated, required = DWORD(), DWORD()
        _check(api.security.GetTokenInformation(token, 20, ctypes.byref(elevated),
                                                ctypes.sizeof(elevated), ctypes.byref(required)))
        if required.value != ctypes.sizeof(elevated):
            raise ValueError("invalid Windows token elevation record")
        return bool(elevated.value)
    finally:
        _close(token)


def _private_owner_action(policy):
    """只接受本人，或确实提升时 CRT 默认 Administrators owner 的受限迁移。

    本边界不启用 SeTakeOwnership、不接管任意 SID；普通读取、权限复制和改名
    都不调用它，只有私有 chmod/fchmod 或排他新建 Skill 的初始化使用该策略。
    """
    if policy.owner == _sid_bytes(current_sid()):
        return False
    if policy.owner == _sid_bytes("S-1-5-32-544") and _token_elevated():
        return True
    raise ValueError("private Windows permissions refuse an unknown or non-elevated foreign owner")


@contextmanager
def _private_writable_handle(path, *, directory=False, expected=None):
    handle = _open_handle(path, 0x60080, directory=directory)
    try:
        before = _metadata(handle)
        if expected is not None and before != expected:
            raise ValueError("private permission target changed while reopening its descriptor")
        with _security_policy(handle) as policy:
            assign_owner = _private_owner_action(policy)
        if assign_owner:
            # WRITE_OWNER 仅在已证明默认 Administrators owner 且当前令牌提升时
            # 请求。重开后再核对同一完整 metadata/ACL 身份，不依靠路径预检。
            _close(handle)
            handle = None
            handle = _open_handle(path, 0xE0080, directory=directory)
            if _metadata(handle) != before:
                raise ValueError("private permission identity changed before owner assignment")
        yield handle, assign_owner
    finally:
        if handle is not None:
            _close(handle)


def restrict_handle(handle, *, assign_owner=False):
    # 创建路径也可能使用 OPEN_ALWAYS 命中已有文件，不能先改未知 owner 的
    # DACL 再以最终断言失败作为拒绝。只有受限 chmod/fchmod 显式允许的情况
    # 才能迁移默认 Administrators owner，其余必须在第一处权限写入前拒绝。
    with _security_policy(handle) as before:
        if assign_owner:
            _private_owner_action(before)
        elif before.owner != _sid_bytes(current_sid()):
            raise ValueError("private Windows creation refuses an existing foreign owner")
        # 同一句柄已完整证明 owner、protected DACL 和精确 user/SYSTEM 权限
        # 满足私有策略时，重复 chmod 不再重写已合格的 ACL。不能凭 mode 或
        # 创建成功早退；不满足者仍沿原受限变更和严格后置证明，保留失败关闭。
        if _policy_is_private(before):
            return
    with private_security() as descriptor:
        owner, defaulted = HANDLE(), BOOL()
        if assign_owner:
            _check(_api().security.GetSecurityDescriptorOwner(
                descriptor, ctypes.byref(owner), ctypes.byref(defaulted)))
        error = _api().security.SetSecurityInfo(handle, 1, 0x80000004 | int(assign_owner),
                                               owner if assign_owner else None, None, _dacl(descriptor), None)
        if error:
            raise ctypes.WinError(error)
    with _security_policy(handle) as policy:
        if not _policy_is_private(policy):
            raise ValueError("private Windows owner or DACL postcondition failed")


def assert_private(path):
    """文件和目录均检查真实 owner 与受保护 DACL，不信任 POSIX mode 投影。"""
    path = absolute_path(path)
    with Directory(path.parent):
        info = secure_os.lstat(path)
        handle = _open_handle(path, READ_CONTROL | 0x80, directory=_stat.S_ISDIR(info.st_mode))
        try:
            with _security_policy(handle) as policy:
                if not _policy_is_private(policy):
                    raise ValueError("private Windows node requires current-user/SYSTEM protected DACL")
        finally:
            _close(handle)


def _handle_for_descriptor(descriptor, backend):
    if descriptor in backend._directories:
        return backend._directories[descriptor].handle
    import msvcrt
    return msvcrt.get_osfhandle(descriptor)


def security_fingerprint(descriptor: int) -> str:
    """只读已锚定 fd 的权限事实；中央消费者不接触或持久化原生 HANDLE。"""
    if type(descriptor) is not int or (descriptor not in secure_os._directories and descriptor not in secure_os._files):
        raise ValueError("Windows security fingerprint requires an anchored backend descriptor")
    with _security_policy(_handle_for_descriptor(descriptor, secure_os)) as policy:
        return policy.fingerprint


def _copy_permissions(source, destination, *, expected_source_security=None, expected_destination_security=None):
    """复制并核实真实 DACL；不同 stage 父继承带来的重写不能当作成功。"""
    with _security_policy(source) as before, _security_policy(destination) as original:
        # 条件消费者的授权来自创建/前像句柄，不能在 helper 的首次策略读取时
        # 重新认领权限变化。兼容旧调用：未提供 expected 时保持原双端策略合同。
        if ((expected_source_security is not None and before.fingerprint != expected_source_security)
                or (expected_destination_security is not None and original.fingerprint != expected_destination_security)):
            raise ValueError("Windows permission source or destination changed before its authorized copy")
        # dacl_key 保留 protection/control、ACE 顺序/flags/mask，只排除 owner。
        # 两端已是同一完整 DACL 时不冗余 SetSecurityInfo，避免已正确策略被
        # 系统重新加工；免写仍须复核两句柄，不能以一次相等观察吞掉权限竞态。
        unchanged = original.dacl_key == before.dacl_key
        if not unchanged:
            protection = 0x80000000 if before.control & 0x1000 else 0x20000000
            error = _api().security.SetSecurityInfo(destination, 1, 4 | protection,
                                                    None, None, before.acl, None)
            if error:
                raise ctypes.WinError(error)
        with _security_policy(destination) as after, _security_policy(source) as current:
            source_stable = current.fingerprint == before.fingerprint
            target_stable = after.owner == original.owner and (not unchanged or after.fingerprint == original.fingerprint)
            if after.dacl_key != before.dacl_key or not source_stable or not target_stable:
                # 仅给控制位与 ACE 数量/稳定性定位，不输出 SID、完整 DACL 或正文；
                # 这些事实用于下一次原生诊断，不能预先归因某种 generic 映射。
                raise ValueError("Windows DACL copy changed inheritance or raced with a permission update "
                                 f"(source_control={before.control:#x}, target_control={after.control:#x}, "
                                 f"source_aces={int.from_bytes(before.acl_bytes[4:6], 'little')}, "
                                 f"target_aces={int.from_bytes(after.acl_bytes[4:6], 'little')}, "
                                 f"source_stable={source_stable}, target_stable={target_stable})")
            return after.fingerprint


def copy_permissions(source: Path, destination: Path) -> None:
    """Preserve a known ordinary file's DACL without following either path."""
    source, destination = absolute_path(source), absolute_path(destination)
    with Directory(source.parent), Directory(destination.parent):
        old = _open_handle(source, READ)
        try:
            new = _open_handle(destination, READ | WRITE | 0x40000)
            try:
                try:
                    _copy_permissions(old, new)
                except ValueError as exc:
                    raise ValueError(f"Windows permission copy {source.name} -> {destination.name}: {exc}") from exc
            finally:
                _close(new)
        finally:
            _close(old)


def copy_permissions_if_unchanged(source: Path, destination: Path, *, expected_source: dict,
                                  expected_destination: dict) -> dict:
    """对两个完整授权前像执行精确 DACL 复制，返回仍属原 stage 的新快照。

    两个打开句柄均拒绝 WRITE/DELETE sharing；正文只读一次，复制过程没有数据
    写入能力。目标只允许实际 DACL 改变所导致的权限投影 mode 与 ChangeTime
    变化；未写权限的幂等分支仍要求七标量完全相同。失败不移动或清理任何路径。
    """
    _check_expected(expected_source, "file")
    _check_expected(expected_destination, "file")
    source, destination = absolute_path(source), absolute_path(destination)
    with Directory(source.parent), Directory(destination.parent):
        old = _open_handle(source, READ, sharing=SHARE_READ)
        try:
            # WRITE_DAC 不需要 GENERIC_WRITE；避免本 helper 重新引入数据写句柄
            # 关闭后的 LastWriteTime 结算，也不放宽既定共享来兼容其他写者。
            new = _open_handle(destination, READ | 0x40000, sharing=SHARE_READ)
            try:
                source_before = _opened_snapshot(old, max_bytes=_budget(max(len(expected_source["payload"]), 1)))
                destination_before = _opened_snapshot(new, max_bytes=_budget(max(len(expected_destination["payload"]), 1)))
                if source_before != expected_source or destination_before != expected_destination:
                    raise ValueError("Windows permission copy nodes changed since their expected snapshots")
                source_attributes = _information(old).attributes
                destination_attributes = _information(new).attributes
                copied_security = _copy_permissions(
                    old, new, expected_source_security=expected_source["security"],
                    expected_destination_security=expected_destination["security"],
                )
                source_after, source_security = _metadata(old)
                destination_after, destination_security = _metadata(new)
                original = expected_destination["identity"]
                # DACL 的真实私有性参与 _stat_info 的 mode 投影；只在安全摘要
                # 确实改变时允许这一已验证权限变换，文件属性/类型及数据元信息
                # 均不许变化。相同 DACL 的免写路径不能豁免 mode 或 ChangeTime。
                changed = copied_security != expected_destination["security"]
                destination_stable = (destination_after == original if not changed else
                                      (destination_after[:2] == original[:2]
                                       and _stat.S_IFMT(destination_after[2]) == _stat.S_IFMT(original[2])
                                       and destination_after[3:6] == original[3:6]))
                if (source_after != expected_source["identity"] or source_security != expected_source["security"]
                        or destination_security != copied_security or not destination_stable
                        or _information(old).attributes != source_attributes
                        or _information(new).attributes != destination_attributes):
                    raise ValueError("Windows permission copy changed data, identity, attributes or authorized security")
                # 拒绝数据写共享的同一 HANDLE 保证正文未被外来写者改变；ACL 的
                # owner 保全及精确 DACL 由 _copy_permissions 在实际策略读取处证明。
                return {"kind": "file", "payload": destination_before["payload"],
                        "mode": _stat.S_IMODE(destination_after[2]), "identity": destination_after,
                        "security": destination_security}
            finally:
                _close(new)
        finally:
            _close(old)


@contextmanager
def directory_lock(path, purpose="publication", *, blocking=False):
    with Directory(path) as directory:
        key = hashlib.sha256(repr((purpose, directory.identity)).encode()).hexdigest()
        name = f"Global\\AgentWorkflow-{current_sid()}-{key}"
        with private_security() as descriptor:
            attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, 0)
            mutex = _api().kernel.CreateMutexW(ctypes.byref(attributes), False, name)
        _check(mutex)
        acquired = False
        try:
            # Global 命名对象跨登录 session 共享。已有对象不会采用本次传入的
            # SECURITY_ATTRIBUTES，必须读取其真实 owner/DACL，防止先创建者
            # 用可被外部主体操作的对象冒充互斥锁；同用户的 case 别名共用目录 ID。
            with _security_policy(mutex, object_type=6) as policy:
                if not _policy_is_private(policy, object_type=6):
                    raise ValueError("Windows directory mutex has an unsafe owner or DACL")
            result = _api().kernel.WaitForSingleObject(mutex, 0xFFFFFFFF if blocking else 0)
            acquired = result in (0, 0x80)
            if result == 0x80:
                raise ValueError("previous Windows writer was abandoned; inspect transaction journals before retrying")
            if result == 0x102:
                raise ValueError("directory is busy; do not retry blindly")
            if result != 0:
                raise ctypes.WinError(ctypes.get_last_error())
            yield directory
        finally:
            try:
                if acquired:
                    _check(_api().kernel.ReleaseMutex(mutex))
            finally:
                # ReleaseMutex 自身失败也不能泄露句柄；abandoned 已取得所有权，
                # 当次拒绝写入后同样必须释放，后续显式恢复才能重新取得此锁。
                _close(mutex)


class _Stream:
    def __init__(self, stream, release):
        self.stream, self.release = stream, release

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __iter__(self):
        return iter(self.stream)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        try:
            self.stream.close()
        finally:
            if self.release is not None:
                release, self.release = self.release, None
                release()


class _Entries:
    def __init__(self, entries, directory=None):
        self.entries, self.directory = iter(entries), directory

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self.entries)
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def close(self):
        self.entries = iter(())
        if self.directory is not None:
            directory, self.directory = self.directory, None
            directory.close()

    def __exit__(self, *args):
        self.close()


class _Entry:
    def __init__(self, directory, name):
        self.name, self.path = name, str(directory.child(name))

    def stat(self, *, follow_symlinks=True):
        return secure_os.stat(self.path, follow_symlinks=follow_symlinks)

    def is_dir(self, *, follow_symlinks=True):
        return _stat.S_ISDIR(self.stat(follow_symlinks=follow_symlinks).st_mode)

    def is_file(self, *, follow_symlinks=True):
        return _stat.S_ISREG(self.stat(follow_symlinks=follow_symlinks).st_mode)

    def is_symlink(self):
        return _stat.S_ISLNK(self.stat(follow_symlinks=False).st_mode)


def _names(directory):
    buffer = ctypes.create_string_buffer(65536)
    first = True
    names = []
    while True:
        success = _api().kernel.GetFileInformationByHandleEx(
            directory.handle, 11 if first else 10, buffer, len(buffer))
        first = False
        if not success:
            if ctypes.get_last_error() == 18:
                return names
            _check(False, directory.path)
        offset = 0
        while True:
            entry = _DirectoryInfo.from_buffer(buffer, offset)
            start = offset + _DirectoryInfo.name.offset
            stop = start + entry.name_length
            if stop > len(buffer) or entry.name_length % 2:
                raise ValueError("invalid native directory enumeration")
            name = buffer.raw[start:stop].decode("utf-16-le", errors="strict")
            if name not in {".", ".."}:
                names.append(name)
            if not entry.next:
                break
            if entry.next < _DirectoryInfo.name.offset or offset + entry.next >= len(buffer):
                raise ValueError("invalid native directory entry offset")
            offset += entry.next


class _WindowsOS:
    """An explicitly imported per-module facade, never a mutation of stdlib os."""

    O_NOFOLLOW, O_DIRECTORY, O_NONBLOCK = NOFOLLOW, DIRECTORY, NONBLOCK
    O_CLOEXEC = getattr(_os, "O_NOINHERIT", 0x80)

    def __init__(self):
        self._directories = {}
        self._files = {}
        self._next = 1 << 30
        self.supports_dir_fd = {self.open, self.stat, self.unlink, self.mkdir, self.replace, self.rename}
        self.supports_follow_symlinks = {self.stat}
        self.supports_fd = {self.scandir, self.listdir}

    def __getattr__(self, name):
        return getattr(_os, name)

    def _path(self, path, descriptor):
        return self._directories[descriptor].child(_os.fspath(path)) if descriptor is not None else absolute_path(path)

    def open(self, path, flags, mode=0o777, *, dir_fd=None, sharing=SHARE_READ | SHARE_WRITE):
        import msvcrt
        if type(sharing) is not int or sharing < 0 or sharing & ~(SHARE_READ | SHARE_WRITE | SHARE_DELETE):
            raise ValueError("invalid Windows file sharing mask")
        path = self._path(path, dir_fd)
        if flags & DIRECTORY:
            directory = Directory(path)
            self._next += 1
            self._directories[self._next] = directory
            return self._next
        parent = Directory(path.parent)
        try:
            if flags & _os.O_CREAT:
                project_mode(mode)
            writing = bool(flags & (_os.O_WRONLY | _os.O_RDWR))
            access = READ | (WRITE if writing else 0)
            if flags & _os.O_CREAT:
                access |= 0x40000  # WRITE_DAC for the new file's permissions.
            if flags & _os.O_CREAT and not mode & 0o077:
                with private_security() as descriptor:
                    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, 0)
                    handle = _open_handle(path, access, create=True,
                                          exclusive=bool(flags & _os.O_EXCL), security=ctypes.byref(attributes), sharing=sharing)
            else:
                handle = _open_handle(path, access, create=bool(flags & _os.O_CREAT),
                                      exclusive=bool(flags & _os.O_EXCL), sharing=sharing)
            try:
                if flags & _os.O_CREAT and not mode & 0o077:
                    restrict_handle(handle)
                native_flags = flags & (_os.O_RDONLY | _os.O_WRONLY | _os.O_RDWR | _os.O_APPEND)
                descriptor = msvcrt.open_osfhandle(handle, native_flags | _os.O_BINARY | _os.O_NOINHERIT)
            except BaseException:
                _close(handle)
                raise
            self._files[descriptor] = parent
            if flags & _os.O_TRUNC:
                try:
                    _os.ftruncate(descriptor, 0)
                except BaseException:
                    self.close(descriptor)
                    raise
            return descriptor
        except BaseException:
            parent.close()
            raise

    def _release(self, descriptor):
        parent = self._files.pop(descriptor, None)
        if parent is not None:
            parent.close()

    def close(self, descriptor):
        directory = self._directories.pop(descriptor, None)
        if directory is not None:
            directory.close()
        else:
            try:
                _os.close(descriptor)
            finally:
                self._release(descriptor)

    def dup(self, descriptor):
        if descriptor in self._directories:
            return self.open(self._directories[descriptor].path, DIRECTORY)
        duplicate = _os.dup(descriptor)
        if descriptor in self._files:
            self._files[duplicate] = Directory(self._files[descriptor].path)
        return duplicate

    def fdopen(self, descriptor, *args, **kwargs):
        stream = _os.fdopen(descriptor, *args, **kwargs)
        return _Stream(stream, lambda: self._release(descriptor))

    def fstat(self, descriptor):
        handle = _handle_for_descriptor(descriptor, self)
        with _security_policy(handle) as policy:
            return _stat_info(_information(handle), _basic_information(handle),
                              private=_policy_is_private(policy))

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        path = self._path(path, dir_fd)
        if path == Path(path.anchor):
            with Directory(path) as directory:
                with _security_policy(directory.handle) as policy:
                    return _stat_info(_information(directory.handle), _basic_information(directory.handle),
                                      private=_policy_is_private(policy))
        with Directory(path.parent):
            handle = _api().kernel.CreateFileW(str(path), READ_CONTROL | 0x80,
                                               SHARE_READ | SHARE_WRITE, None, 3,
                                               BACKUP_SEMANTICS | OPEN_REPARSE_POINT, None)
            if handle == INVALID_HANDLE:
                _check(False, path)
            try:
                info = _information(handle)
                if follow_symlinks and info.attributes & ATTR_REPARSE:
                    raise ValueError(f"following reparse points is forbidden: {path}")
                with _security_policy(handle) as policy:
                    return _stat_info(info, _basic_information(handle), private=_policy_is_private(policy))
            finally:
                _close(handle)

    def lstat(self, path, *, dir_fd=None):
        return self.stat(path, dir_fd=dir_fd, follow_symlinks=False)

    def scandir(self, path):
        own = not isinstance(path, int)
        directory = Directory(path) if own else self._directories[path]
        try:
            return _Entries([_Entry(directory, name) for name in _names(directory)], directory if own else None)
        except BaseException:
            if own:
                directory.close()
            raise

    def listdir(self, path):
        with self.scandir(path) as entries:
            return [entry.name for entry in entries]

    def fchmod(self, descriptor, mode):
        project_mode(mode)
        import msvcrt
        handle = msvcrt.get_osfhandle(descriptor)
        if not mode & 0o077:
            # CRT 临时 fd 没有 WRITE_DAC；祖先锚定后重开，再用完整 metadata 与
            # 独立权限摘要核对原 fd。提升令牌默认 owner 的修正只走受限私有策略。
            buffer = ctypes.create_unicode_buffer(32768)
            count = _api().kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
            _check(count)
            if count >= len(buffer):
                raise ValueError("temporary file path is too long")
            raw = buffer.value
            if raw.startswith("\\\\?\\"):
                raw = raw[4:]
            path = absolute_path(raw)
            parent = Directory(path.parent)
            try:
                expected = _metadata(handle)
                with _private_writable_handle(path, expected=expected) as (writable, assign_owner):
                    restrict_handle(writable, assign_owner=assign_owner)
                if descriptor not in self._files:
                    self._files[descriptor] = parent
                    parent = None
            finally:
                if parent is not None:
                    parent.close()
        # Broader POSIX modes cannot grant Windows access: inherit the parent's
        # DACL for new files; replacement requires an already exact owner and DACL.
        if not mode & 0o200:
            raise ValueError("read-only POSIX mode needs explicit Windows ACL policy")

    def chmod(self, path, mode, *, dir_fd=None, follow_symlinks=True):
        project_mode(mode)
        path = self._path(path, dir_fd)
        with Directory(path.parent):
            info = self.lstat(path)
            directory = _stat.S_ISDIR(info.st_mode)
            if not mode & 0o077:
                with _private_writable_handle(path, directory=directory) as (handle, assign_owner):
                    restrict_handle(handle, assign_owner=assign_owner)
            # 普通模式不放宽 ACL，也不自动修 owner；替换须保有已匹配的完整 SD。

    def fsync(self, descriptor):
        if descriptor not in self._directories:
            return _os.fsync(descriptor)
        # No silent fsync fallback. Refuse a volume/account that cannot supply
        # the required metadata flush rather than claiming crash durability.
        flush_directory(self._directories[descriptor].path)

    def _rename(self, source, target, replace, identity=None):
        with Directory(source.parent), Directory(target.parent) as destination:
            parents = (source.parent,) if source.parent == target.parent else (source.parent, target.parent)
            for parent in parents:
                flush_directory(parent)
            info = self.lstat(source)
            directory = _stat.S_ISDIR(info.st_mode)
            handle = _open_handle(source, DELETE | READ | (0 if directory else 0x40000),
                                  directory=directory,
                                  sharing=SHARE_READ | (SHARE_WRITE if directory else 0))
            try:
                opened = _information(handle)
                if identity is not None and identity != (opened.volume, opened.index_high << 32 | opened.index_low):
                    raise ValueError(f"publication source identity changed: {source}")
                if replace:
                    try:
                        target_info = self.lstat(target)
                    except FileNotFoundError:
                        target_info = None
                    if target_info is not None:
                        if (_stat.S_ISLNK(target_info.st_mode)
                                or (not _stat.S_ISDIR(target_info.st_mode) and target_info.st_nlink != 1)):
                            raise ValueError(f"unsafe publication target: {target}")
                        if not directory and _stat.S_ISREG(target_info.st_mode):
                            old = _open_handle(target, READ, sharing=SHARE_READ)
                            try:
                                # 替换不能只保住 DACL 而把旧目标 owner 换成新
                                # stage 的默认 owner。创建者须在创建时准备正确
                                # SD；这里不能为修权限偷偷重建已登记的候选 inode。
                                prior, prior_security = _metadata(old)
                                candidate, candidate_security = _metadata(handle)
                                if (prior_security != candidate_security
                                        or _stat.S_IMODE(prior[2]) != _stat.S_IMODE(candidate[2])):
                                    raise ValueError("Windows replacement candidate owner, mode or security differs from its target")
                                # 已精确匹配的 SD 原样保留，绝不重复 UNPROTECTED
                                # SetSecurityInfo 再引发 CO/AI 重算；不匹配则在
                                # 命名空间变化前拒绝，不能改owner或追认另一inode。
                                if (_metadata(old) != (prior, prior_security)
                                        or _metadata(handle) != (candidate, candidate_security)):
                                    raise ValueError("Windows replacement security or metadata changed before publication")
                            finally:
                                _close(old)
                # 普通发布与窄条件移动必须使用同一 Win32 请求构造。源句柄及
                # 目标全部祖先仍固定，不能退化为重新按源路径执行的 rename。
                _rename_handle(handle, destination, target.name, replace=replace)
            finally:
                _close(handle)
            # A preflight flush cannot make this later namespace mutation durable.
            # A failure here is a transaction failure, not a committed publication.
            for parent in parents:
                flush_directory(parent)

    def replace(self, source, target, *, src_dir_fd=None, dst_dir_fd=None):
        self._rename(self._path(source, src_dir_fd), self._path(target, dst_dir_fd), True)

    def rename(self, source, target, *, src_dir_fd=None, dst_dir_fd=None):
        self._rename(self._path(source, src_dir_fd), self._path(target, dst_dir_fd), False)

    def replace_owned(self, source, target, identity):
        self._rename(absolute_path(source), absolute_path(target), True, identity)

    def _remove(self, path, *, directory=False):
        with Directory(path.parent):
            flush_directory(path.parent)
            handle = _open_handle(path, DELETE | 0x80, directory=directory)
            try:
                disposition = BOOL(True)
                _check(_api().kernel.SetFileInformationByHandle(
                    handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)), path)
            finally:
                _close(handle)
            flush_directory(path.parent)

    def unlink(self, path, *, dir_fd=None):
        self._remove(self._path(path, dir_fd))

    def mkdir(self, path, mode=0o777, *, dir_fd=None):
        project_mode(mode, directory=True)
        path = self._path(path, dir_fd)
        with Directory(path.parent):
            flush_directory(path.parent)
            if not mode & 0o077:
                with private_security() as descriptor:
                    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, 0)
                    _check(_api().kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)), path)
                assert_private(path)
            else:
                _check(_api().kernel.CreateDirectoryW(str(path), None), path)
            flush_directory(path)
            flush_directory(path.parent)

    def rmdir(self, path, *, dir_fd=None):
        self._remove(self._path(path, dir_fd), directory=True)


secure_os = _WindowsOS()


def _budget(limit):
    if type(limit) is not int or not 0 < limit <= 2 * _LIMIT:
        raise ValueError("invalid bounded Windows read budget")
    return limit


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_handle(handle, limit):
    data = bytearray()
    buffer = ctypes.create_string_buffer(min(limit + 1, 1024 * 1024))
    while True:
        count = DWORD()
        _check(_api().kernel.ReadFile(handle, buffer, min(len(buffer), limit + 1 - len(data)),
                                      ctypes.byref(count), None))
        if not count.value:
            return bytes(data)
        data.extend(buffer.raw[:count.value])
        if len(data) > limit:
            raise ValueError("Windows node exceeds bounded read budget")


def _metadata(handle, *, link=False):
    info, basic = _information(handle), _basic_information(handle)
    with _security_policy(handle) as policy:
        result = _stat_info(info, basic, private=_policy_is_private(policy))
        identity = _identity(result)
        if link:
            identity = (*identity[:2], _stat.S_IFLNK | 0o777, *identity[3:])
        return identity, policy.fingerprint


def _skill_target(target, skill_name):
    if not isinstance(skill_name, str) or not re.fullmatch(r"(?:xy-[a-z0-9]+(?:-[a-z0-9]+)*|grill-me)", skill_name):
        raise ValueError("invalid managed Skill name")
    target = absolute_path(target)
    parts = target.parts
    if (len(parts) < 7 or target.name != skill_name or parts[-4:-1] != ("platforms", "shared", "skills")
            or parts[-5] != "core" or not re.fullmatch(r"[0-9a-f]{64}", parts[-6])
            or parts[-7] != "runtimes"):
        raise ValueError("managed Skill must target the same named verified central core Skill")
    return target


def _read_skill_handle(handle, skill_name):
    """只解释目录 SYMLINK 的绝对目标；不跟随目标，也不接受 junction 等 tag。"""
    info = _information(handle)
    if (info.attributes & (ATTR_REPARSE | ATTR_DIRECTORY) != ATTR_REPARSE | ATTR_DIRECTORY
            or info.links != 1):
        raise ValueError("managed Skill requires a single-link directory symbolic link")
    buffer, count = ctypes.create_string_buffer(16 * 1024), DWORD()
    _check(_api().kernel.DeviceIoControl(handle, 0x900A8, None, 0, buffer, len(buffer),
                                         ctypes.byref(count), None))
    raw = buffer.raw[:count.value]
    if len(raw) < 20 or int.from_bytes(raw[:4], "little") != 0xA000000C:
        raise ValueError("unknown managed Skill reparse tag")
    if int.from_bytes(raw[4:6], "little") + 8 != len(raw) or int.from_bytes(raw[16:20], "little"):
        raise ValueError("managed Skill symbolic link must be absolute")
    names = []
    for offset in (8, 12):
        start = int.from_bytes(raw[offset:offset + 2], "little")
        size = int.from_bytes(raw[offset + 2:offset + 4], "little")
        if start % 2 or size % 2 or not size or 20 + start + size > len(raw):
            raise ValueError("invalid managed Skill reparse target bounds")
        names.append(raw[20 + start:20 + start + size].decode("utf-16-le", errors="strict"))
    substitute, display = names
    if not substitute.startswith("\\??\\"):
        raise ValueError("managed Skill target must be an absolute local path")
    target = _skill_target(substitute[4:], skill_name)
    if substitute != "\\??\\" + str(target) or display != str(target):
        raise ValueError("managed Skill substitute and display targets must agree exactly")
    return _os.fsencode(target)


def _opened_snapshot(handle, *, max_bytes, skill_name=None):
    before, security = _metadata(handle, link=skill_name is not None)
    if skill_name is None:
        if not _stat.S_ISREG(before[2]) or before[3] != 1 or before[4] > max_bytes:
            raise ValueError("Windows node must be a bounded single-link regular file")
        body = _read_handle(handle, max_bytes)
    else:
        body = _read_skill_handle(handle, skill_name)
    after, after_security = _metadata(handle, link=skill_name is not None)
    if len(body) > max_bytes or before != after or security != after_security:
        raise ValueError("Windows node changed during bounded snapshot")
    return {"kind": "link" if skill_name else "file", "payload": body,
            "mode": _stat.S_IMODE(before[2]), "identity": before, "security": security}


def _open_skill_handle(path, access=READ_CONTROL | 0x80):
    handle = _api().kernel.CreateFileW(str(path), access, SHARE_READ, None, 3,
                                      BACKUP_SEMANTICS | OPEN_REPARSE_POINT, None)
    if handle == INVALID_HANDLE:
        _check(False, path)
    return handle


def node_snapshot(directory: int, name: str, *, max_bytes=_LIMIT, skill_name=None):
    """同一句柄读取当前完整可观察状态；不声称追溯已结束且状态相同的历史写。

    SHARE_READ 排除普通数据写者与换名者；WRITE_DAC 不属于数据写共享判断，
    因此权限在前后独立采样，绝不能只依赖可能不变的 ChangeTime。
    """
    _budget(max_bytes)
    path = secure_os._path(name, directory)
    try:
        handle = (_open_skill_handle(path) if skill_name is not None else
                  _open_handle(path, READ, sharing=SHARE_READ))
    except FileNotFoundError:
        return None
    try:
        return _opened_snapshot(handle, max_bytes=max_bytes, skill_name=skill_name)
    finally:
        _close(handle)


def _rename_handle(handle, destination, name, *, replace=False):
    """以稳定源 HANDLE 和目标目录的真实卷 GUID 路径执行 Win32 重命名。

    原生 CI 已证明旧的非空 RootDirectory/相对名请求返回 87，但错误码本身
    不足以唯一定位字段。这里采用 Win32 的完整绝对目标形态；完整路径来自
    已锚定目录 HANDLE，祖先持续拒绝 DELETE sharing，因此不依赖 cwd 或可变
    盘符别名。未知/远程形式不回退到调用者路径，也不调用普通 Path.rename。
    """
    name = validate_component(name)
    api = _api()
    final_path = ctypes.create_unicode_buffer(32768)
    count = _check(api.kernel.GetFinalPathNameByHandleW(
        destination.handle, final_path, len(final_path), 1))  # VOLUME_NAME_GUID
    if (count >= len(final_path)
            or not re.match(r"^\\\\\?\\Volume\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}\\", final_path.value)):
        raise ValueError("Windows rename requires the anchored local volume GUID path")
    target = final_path.value.rstrip("\\") + "\\" + name
    encoded = target.encode("utf-16-le")
    # FILE_RENAME_INFO 的 WCHAR[1] 属于结构体；额外空间包括完整正文、明确的
    # UTF-16 NUL 与 SDK 尾部对齐。FileNameLength 仅计正文，不计终止符或 padding。
    buffer = ctypes.create_string_buffer(ctypes.sizeof(_RenameInfo) + len(encoded) + 2)
    rename = _RenameInfo.from_buffer(buffer)
    rename.flags, rename.root, rename.length = int(replace), None, len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + _RenameInfo.name.offset, encoded, len(encoded))
    before = _information(handle)
    _check(api.kernel.SetFileInformationByHandle(handle, 3, buffer, len(buffer)), destination.child(name))
    # 原源句柄仍拒绝 DELETE sharing，成功后新叶也不能被普通换名者替换。
    # 用同一 GUID 目标 no-follow 打开并复核身份，不能把 API 成功误认为发布了
    # 另一个对象；复核失败正常传播，保留已发布节点供事务恢复，不自动清除。
    published = api.kernel.CreateFileW(target, 0x80, SHARE_READ | SHARE_WRITE | SHARE_DELETE,
                                      None, 3, BACKUP_SEMANTICS | OPEN_REPARSE_POINT, None)
    if published == INVALID_HANDLE:
        _check(False, destination.child(name))
    try:
        after = _information(published)
        if ((before.volume, before.index_high, before.index_low, before.links,
             before.attributes & (ATTR_DIRECTORY | ATTR_REPARSE))
                != (after.volume, after.index_high, after.index_low, after.links,
                    after.attributes & (ATTR_DIRECTORY | ATTR_REPARSE))):
            raise ValueError("Windows rename destination identity does not match its opened source")
    finally:
        _close(published)


def _check_expected(expected, kind):
    if (not isinstance(expected, dict) or set(expected) != {"kind", "payload", "mode", "identity", "security"}
            or expected["kind"] != kind or not isinstance(expected["payload"], bytes)
            or len(expected["payload"]) > 2 * _LIMIT or type(expected["mode"]) is not int
            or not 0 <= expected["mode"] <= 0o7777 or not isinstance(expected["identity"], tuple)
            or len(expected["identity"]) != 7 or any(type(value) is not int for value in expected["identity"])
            or not isinstance(expected["security"], str) or not re.fullmatch(r"[0-9a-f]{64}", expected["security"])):
        raise ValueError("conditional Windows operation requires a complete node snapshot")


class _CreatedStageFile(namedtuple("_CreatedStageFileFacts", "parent handle empty attributes max_bytes")):
    """复用 fd 的现有资源登记，仅保存本轮创建事实，不新增持久状态或 fd 池。"""

    __slots__ = ()

    @property
    def path(self):
        return self.parent.path

    def close(self):
        # 文件 HANDLE 已归 CRT/stream；登记只释放自己的目录锚，绝不双关文件。
        self.parent.close()


def create_regular_stage(directory: int, name: str, *, permission_source: str | None = None,
                         expected_source: dict[str, object] | None = None,
                         max_bytes: int = _LIMIT) -> tuple[int, dict[str, object]]:
    """在创建时精确取得源 SD 或新私有策略，返回唯一写者 fd 与空创建见证。

    源必须是同一活目录中的单叶，完整前像由上层已授权 Node 投影传入；库不
    认识 manager/Node。源句柄只在同步创建及前后复核期间拥有 SD，返回前释放。
    新文件持续 share0，未完成正文不能被另一数据读者/写者或换名者打开；ACL
    不受数据共享位全面封锁，故创建时及 seal 时仍独立核验真实安全事实。
    """
    _budget(max_bytes)
    if type(directory) is not int or directory not in secure_os._directories:
        raise ValueError("stage creation requires a live anchored directory descriptor")
    name = validate_component(name)
    if (permission_source is None) != (expected_source is None):
        raise ValueError("stage permission source and complete expected snapshot must be paired")
    if permission_source is not None:
        permission_source = validate_component(permission_source)
        if permission_source == name:
            raise ValueError("stage and permission source must be distinct single leaves")
        _check_expected(expected_source, "file")
        # 五字段值均已校验为不可变标量/bytes/tuple；私有副本固定本调用授权，
        # 避免持有调用方可修改的dict并在后续权限采样时改变比较基线。
        expected_source = dict(expected_source)
        if len(expected_source["payload"]) > max_bytes:
            raise ValueError("stage permission source exceeds its explicit file-I/O budget")
        project_mode(expected_source["mode"])
    import msvcrt
    path = secure_os._path(name, directory)
    parent = Directory(path.parent)
    handle = descriptor = None
    try:
        if permission_source is not None:
            source = _open_handle(parent.child(permission_source), READ, sharing=SHARE_READ)
            try:
                actual = _opened_snapshot(source, max_bytes=max(len(expected_source["payload"]), 1))
                if actual != expected_source:
                    raise ValueError("stage permission source changed since its complete expected snapshot")
                source_attributes = _information(source).attributes
                with _security_policy(source) as policy:
                    # 不能在真正取得 SD 时把后来的 ACL 追认为新授权，也不能
                    # 先私有化再解除保护：后者会按不同 owner 重算 CO 继承。
                    if policy.fingerprint != expected_source["security"]:
                        raise ValueError("stage permission source changed before initial security assignment")
                    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), policy.descriptor, 0)
                    handle = _open_handle(path, READ | WRITE, create=True, exclusive=True,
                                          security=ctypes.byref(attributes), sharing=0)
                    initial_attributes = _information(handle).attributes
                    empty = _opened_snapshot(handle, max_bytes=1)
                    if (empty["mode"] != expected_source["mode"] or empty["security"] != policy.fingerprint):
                        raise ValueError("new stage did not preserve its exact initial source security")
                if (_metadata(source) != (expected_source["identity"], expected_source["security"])
                        or _information(source).attributes != source_attributes):
                    raise ValueError("stage permission source changed during initial security assignment")
            finally:
                _close(source)
        else:
            with private_security() as security:
                attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), security, 0)
                handle = _open_handle(path, READ | WRITE, create=True, exclusive=True,
                                      security=ctypes.byref(attributes), sharing=0)
            initial_attributes = _information(handle).attributes
            # 无源的新文件沿原私有策略；不把普通既有源改成私有来绕过差异。
            with _security_policy(handle) as policy:
                if not _policy_is_private(policy):
                    raise ValueError("new private stage did not preserve its initial owner and DACL")
                private_fingerprint = policy.fingerprint
            empty = _opened_snapshot(handle, max_bytes=1)
            if empty["mode"] != 0o600 or empty["security"] != private_fingerprint:
                raise ValueError("new private stage changed its exact private mode or security")
        if (empty["payload"] or not _stat.S_ISREG(empty["identity"][2])
                or empty["identity"][3:5] != (1, 0)):
            raise ValueError("new stage is not an empty single-link regular file")
        if (_metadata(handle) != (empty["identity"], empty["security"])
                or _information(handle).attributes != initial_attributes):
            raise ValueError("new stage changed before its creator descriptor was registered")
        descriptor = msvcrt.open_osfhandle(handle, _os.O_RDWR | _os.O_BINARY | _os.O_NOINHERIT)
        handle = None  # 仅 CRT fd 此后拥有原 HANDLE；转换失败时仍由上方原 HANDLE 收口。
        entry = _CreatedStageFile(parent, msvcrt.get_osfhandle(descriptor),
                                  MappingProxyType(dict(empty)), initial_attributes, max_bytes)
        secure_os._files[descriptor] = entry
        parent = None
        return descriptor, dict(empty)
    except BaseException as exc:
        # 尚未返回见证的失败不认领路径，不为清理而删除碰撞或未知 stage。
        exc.add_note("unproved stage was not adopted or removed: " + str(path))
        try:
            if descriptor is not None:
                secure_os.close(descriptor)
            elif handle is not None:
                _close(handle)
        finally:
            if parent is not None:
                parent.close()
        raise


def seal_regular_stage(descriptor: int, *, expected_created: dict[str, object], payload: bytes,
                       mode: int, max_bytes: int = _LIMIT) -> dict[str, object]:
    """调用者 flush 后，同原 creator HANDLE 核准实际正文与完整权限并封口。

    本函数不关闭、不改权限、不发布。创建后合法数据写入可以改变时间和长度，
    但 inode/type/nlink、精确物理 mode、安全摘要和原生属性仍须为创建事实。
    fd 登记的私有副本是授权源，普通 fd 或调用方手造空 dict 不能声明创建归属。
    """
    _budget(max_bytes)
    entry = secure_os._files.get(descriptor) if type(descriptor) is int else None
    if not isinstance(entry, _CreatedStageFile):
        raise ValueError("stage seal requires its still-live original creator descriptor")
    if max_bytes > entry.max_bytes:
        raise ValueError("stage seal cannot increase its registered creator file-I/O budget")
    _check_expected(expected_created, "file")
    if expected_created != entry.empty or expected_created["payload"] or expected_created["identity"][4] != 0:
        raise ValueError("stage seal creation witness does not match its registered creator")
    if not isinstance(payload, bytes) or len(payload) > max_bytes:
        raise ValueError("stage seal requires approved bytes within its explicit file-I/O budget")
    # 沿现 Windows content_mode：可写逻辑模式仍须有效，真实 ACL/mode 由
    # 已验证 SD 决定；不把 POSIX 0644 等位投影成另一套 Windows 权限。
    project_mode(mode)
    handle = _handle_for_descriptor(descriptor, secure_os)
    if handle != entry.handle:
        raise ValueError("stage creator descriptor no longer owns its original native handle")
    before, security = _metadata(handle)
    if (before[:4] != entry.empty["identity"][:4] or security != entry.empty["security"]
            or _information(handle).attributes != entry.attributes):
        raise ValueError("stage creator identity, mode, security or attributes changed before seal")
    secure_os.fsync(descriptor)
    position = _os.lseek(descriptor, 0, _os.SEEK_CUR)
    try:
        _os.lseek(descriptor, 0, _os.SEEK_SET)
        actual = _opened_snapshot(handle, max_bytes=max(len(payload), 1))
        if (actual["payload"] != payload or actual["identity"][:4] != entry.empty["identity"][:4]
                or actual["identity"][4] != len(payload) or actual["mode"] != entry.empty["mode"]
                or actual["security"] != entry.empty["security"]
                or _information(handle).attributes != entry.attributes):
            raise ValueError("stage bytes, identity, mode, security or attributes do not match the approved seal")
        return actual
    finally:
        # 仅借用同一流的游标，错误也复位；调用者仍是唯一 stream/fd 关闭者。
        _os.lseek(descriptor, position, _os.SEEK_SET)


def _discard_created_stage(directory, name, expected, attributes, max_bytes):
    """只收口本轮已证实的 stage，额外保留五字段以外的原生属性守护。

    普通 delete_regular 的独立 GC 流式合同不改；这里的正文受 creator 的
    原调用方固定字节界限约束，并须包括初始 rawattrs，不能删除被改为隐藏等属性的
    同 inode。核验和 disposition 始终使用同一拒绝数据写入/换名的 HANDLE。
    """
    path = secure_os._path(name, directory)
    try:
        handle = _open_handle(path, READ | DELETE, sharing=SHARE_READ)
    except FileNotFoundError:
        return
    try:
        actual = _opened_snapshot(handle, max_bytes=max_bytes)
        if (actual != expected or _information(handle).attributes != attributes
                or _metadata(handle) != (expected["identity"], expected["security"])
                or _information(handle).attributes != attributes):
            raise ValueError("created stage has an external edit; preserved: " + str(path))
        disposition = BOOL(True)
        _check(_api().kernel.SetFileInformationByHandle(
            handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)), path)
    finally:
        _close(handle)
    flush_directory(path.parent)


def write_regular_if_unchanged(directory: int, name: str, temporary: str, *,
                               expected: dict[str, object] | None, payload: bytes,
                               mode: int, max_bytes: int = _LIMIT) -> dict[str, object]:
    """为简单公共字节写者封闭创建、批准、关闭及原子替换的完整生命周期。

    expected 来自原始业务读取；None 仅授权缺失，绝不是任意当前内容。调用方的
    hash/CAS/结算/业务预检仍在进入本函数之前，不以本函数内的新读替代批准。
    本层不认识 manager/Node，不创建持久协议，也不承诺最后目标检查与 Win32
    rename 是一个内核 CAS。需要保留原 inode 的事务仍使用原独立移动/补偿链。
    """
    _budget(max_bytes)
    project_mode(mode)
    if (type(directory) is not int or directory not in secure_os._directories
            or not isinstance(payload, bytes) or len(payload) > max_bytes):
        raise ValueError("conditional Windows write requires a live parent and approved bytes within its file-I/O budget")
    name, temporary = validate_component(name), validate_component(temporary)
    if name == temporary:
        raise ValueError("publication target and creator stage must be distinct single leaves")
    if expected is not None:
        _check_expected(expected, "file")
        expected = dict(expected)
        project_mode(expected["mode"])
        if len(expected["payload"]) > max_bytes:
            raise ValueError("conditional Windows write source exceeds its file-I/O budget")
    # 独立目录锚覆盖 stream 关闭后的发布时段；借用的调用方 directory 不关闭。
    with Directory(secure_os._path(name, directory).parent) as parent:
        if node_snapshot(directory, name, max_bytes=max_bytes) != expected:
            raise ValueError("Windows publication target changed before stage creation")
        descriptor = handle = None
        staged = attributes = None
        try:
            descriptor, empty = create_regular_stage(directory, temporary,
                permission_source=name if expected is not None else None,
                expected_source=expected, max_bytes=max_bytes)
            staged = empty
            attributes = secure_os._files[descriptor].attributes
            # fdopen 构造前 fd 唯一归当前栈；构造成功后仅由正常后端 stream 关闭。
            stream = secure_os.fdopen(descriptor, "wb")
            descriptor = None
            with stream:
                stream.write(payload)
                stream.flush()
                sealed = seal_regular_stage(stream.fileno(), expected_created=empty,
                    payload=payload, mode=mode, max_bytes=max_bytes)
                staged = sealed
            observed = node_snapshot(directory, temporary, max_bytes=max_bytes)
            if (observed is None or any(observed[key] != sealed[key] for key in ("kind", "payload", "mode", "security"))
                    or observed["identity"][:5] != sealed["identity"][:5]
                    or observed["identity"][6:] != sealed["identity"][6:]):
                raise ValueError("Windows creator stage changed after close; preserved")
            staged = observed  # 仅已批准的 LastWriteTime 关闭结算可成为清理见证。
            flush_directory(parent.path)
            handle = _open_handle(parent.child(temporary), READ | DELETE, sharing=SHARE_READ)
            if (_opened_snapshot(handle, max_bytes=max_bytes) != staged
                    or _information(handle).attributes != attributes):
                raise ValueError("Windows approved stage changed before publication; preserved")
            # 候选 HANDLE 持续拒绝其他数据写者/换名者，核验完整正文后不再用
            # identity-only replace_owned 重开路径。旧目标必须仍是最初完整前像。
            # 旧目标 READ 句柄需在 rename 前关闭，否则其 no-DELETE sharing 会
            # 阻挡本轮原子替换；这个检查间隔不被包装成内核 CAS 的保证。
            if node_snapshot(directory, name, max_bytes=max_bytes) != expected:
                raise ValueError("Windows publication target changed before atomic replacement")
            if (_metadata(handle) != (staged["identity"], staged["security"])
                    or _information(handle).attributes != attributes):
                raise ValueError("Windows approved stage metadata or security changed before publication")
            _rename_handle(handle, parent, name, replace=expected is not None)
            after, security = _metadata(handle)
            if (after[:6] != staged["identity"][:6] or security != staged["security"]
                    or _information(handle).attributes != attributes
                    or _metadata(handle) != (after, security)):
                raise ValueError("Windows published node changed during its own rename; preserved")
            # 正文来自仍持有的稳定 HANDLE，只有本轮 rename 的 ctime 可结算；
            # 不在发布后把某个新的路径对象追认为成功结果。
            result = {**staged, "identity": after}
            flush_directory(parent.path)
            if (_metadata(handle) != (after, security) or _information(handle).attributes != attributes):
                raise ValueError("Windows published node changed during the final durability barrier; preserved")
            return result
        except BaseException as exc:
            # 先释放本函数的所有数据句柄，再做条件清理；未知/部分写/外来替换
            # 始终保留。清理异常只附注，不覆盖原始业务或 I/O 错误原因。
            if descriptor is not None:
                owned_descriptor, descriptor = descriptor, None
                try:
                    secure_os.close(owned_descriptor)
                except BaseException as close_error:
                    exc.add_note("creator fd close failed: " + str(close_error))
            if handle is not None:
                owned_handle, handle = handle, None
                try:
                    _close(owned_handle)
                except BaseException as close_error:
                    exc.add_note("publication handle close failed: " + str(close_error))
            if staged is not None:
                try:
                    _discard_created_stage(directory, temporary, staged, attributes, max_bytes)
                except BaseException as cleanup_error:
                    exc.add_note("stage preserved at " + str(parent.child(temporary)) + ": " + str(cleanup_error))
            raise
        finally:
            if descriptor is not None:
                secure_os.close(descriptor)
            if handle is not None:
                _close(handle)


def _move_node(source, target, *, src_dir_fd, dst_dir_fd, expected, skill_name=None, max_bytes=None):
    _check_expected(expected, "link" if skill_name is not None else "file")
    # 公共普通文件移动必须显式遵守调用方预算；既有受管链接等内部路径
    # 仍沿原独立边界，不把此次普通默认4MiB改成内部原语的全局收窄。
    if max_bytes is not None and len(expected["payload"]) > _budget(max_bytes):
        raise ValueError("Windows move source exceeds its explicit file-I/O budget")
    source, target = secure_os._path(source, src_dir_fd), secure_os._path(target, dst_dir_fd)
    with Directory(source.parent), Directory(target.parent) as destination:
        parents = tuple(dict.fromkeys((source.parent, target.parent)))
        for parent in parents:
            flush_directory(parent)
        handle = (_open_skill_handle(source, READ | DELETE) if skill_name is not None else
                  _open_handle(source, READ | DELETE, sharing=SHARE_READ))
        try:
            actual = _opened_snapshot(handle, max_bytes=_budget(max(len(expected["payload"]), 1)), skill_name=skill_name)
            if actual != expected:
                raise ValueError("Windows move source changed since its expected snapshot")
            # 只移动已经验证的打开身份，目标存在由内核排他拒绝，不执行覆盖式 CAS。
            _rename_handle(handle, destination, target.name)
        finally:
            _close(handle)
        for parent in parents:
            flush_directory(parent)


def move_regular(source, target, *, src_dir_fd=None, dst_dir_fd=None, expected: dict, max_bytes=_LIMIT) -> None:
    """排他消费一个完整快照相符的普通文件；失败后不清除已移动的恢复见证。"""
    _budget(max_bytes)
    _move_node(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, expected=expected, max_bytes=max_bytes)


def _secure_created_skill(path, skill_name, expected):
    """只在排他创建成功后固定新 owned link 的权限，随后调用者才冻结 stage。

    不能用普通 chmod：普通句柄拒绝 reparse，跟随路径则会碰到核心 target。
    始终使用 OPEN_REPARSE_POINT 句柄核对同名中央目标及完整创建见证；设置
    不继承的两条 ACE，避免 SetSecurityInfo 向已有子对象传播可继承权限。
    这里不提供既有用户链接的权限迁移入口，任何失败均保留对象而不盲删。
    """
    _check_expected(expected, "link")
    handle = _open_skill_handle(path, 0x60080)  # READ_CONTROL | WRITE_DAC | READ_ATTRIBUTES
    try:
        if _opened_snapshot(handle, max_bytes=_LIMIT, skill_name=skill_name) != expected:
            raise ValueError("new managed Skill changed before private permission initialization")
        with _security_policy(handle) as before:
            if before.fingerprint != expected["security"]:
                raise ValueError("new managed Skill permissions changed before owner validation")
            assign_owner = _private_owner_action(before)
        if assign_owner:
            # 普通用户 owner 不请求 WRITE_OWNER。仅确实提升时的默认 Admins
            # owner 可转为本人；重开期间仍逐项比较创建时的完整 Node，不能
            # 把后来替换的 inode、目标或 ACL 追认成本次新建的自有链接。
            _close(handle)
            handle = None
            handle = _open_skill_handle(path, 0xE0080)
            if _opened_snapshot(handle, max_bytes=_LIMIT, skill_name=skill_name) != expected:
                raise ValueError("new managed Skill changed while reopening for owner assignment")
        with private_security(inherit=False) as descriptor:
            owner, defaulted = HANDLE(), BOOL()
            if assign_owner:
                _check(_api().security.GetSecurityDescriptorOwner(
                    descriptor, ctypes.byref(owner), ctypes.byref(defaulted)))
            error = _api().security.SetSecurityInfo(
                handle, 1, 0x80000004 | int(assign_owner),
                owner if assign_owner else None, None, _dacl(descriptor), None)
            if error:
                raise ctypes.WinError(error)
        with _security_policy(handle) as policy:
            if not _policy_is_private(policy):
                raise ValueError("new managed Skill private owner or DACL postcondition failed")
            # 通用私有策略允许 OI/CI；链接必须更窄，精确两条 ACE 均 flags=0。
            # 不能仅凭 access mask 等价忽略 inherited/protected 等策略变化。
            offset = 8
            for _ in range(2):
                if policy.acl_bytes[offset + 1] != 0:
                    raise ValueError("new managed Skill DACL must not contain inheritable ACEs")
                offset += int.from_bytes(policy.acl_bytes[offset + 2:offset + 4], "little")
            security = policy.fingerprint
        after = _opened_snapshot(handle, max_bytes=_LIMIT, skill_name=skill_name)
        if (after["identity"][:6] != expected["identity"][:6] or after["mode"] != expected["mode"]
                or after["payload"] != expected["payload"] or after["security"] != security):
            raise ValueError("new managed Skill identity, target or permissions changed during initialization")
    finally:
        if handle is not None:
            _close(handle)


def create_skill_symlink(directory: int, name: str, target: Path, *, core_root: Path) -> None:
    target = _skill_target(target, name)
    if target != absolute_path(core_root) / "platforms/shared/skills" / name:
        raise ValueError("managed Skill target does not belong to the selected core")
    path = secure_os._path(name, directory)
    with Directory(target), Directory(path.parent):
        flush_directory(path.parent)
        _check(_api().kernel.CreateSymbolicLinkW(str(path), str(target), 3), path)
        created = read_skill_symlink(directory, name, skill_name=name)
        if created is None or created["payload"] != _os.fsencode(target):
            raise ValueError("managed Skill link changed immediately after creation")
        # CreateSymbolicLinkW 不接受创建 SD。仅成功创建的新链接在此通过真实
        # no-follow 句柄固定私有 owner/protected DACL，避免把 inherited ACL
        # 冻结成 stage 后在跨父目录发布时继承策略改变而触发安全拒绝。
        _secure_created_skill(path, name, created)
        flush_directory(path.parent)


def require_skill_symlinks() -> None:
    """预览能力门仅做只读检查；不创建测试链接、不改权限，也不保证后续必成功。

    Win11 Developer Mode 与已启用的 SeCreateSymbolicLinkPrivilege 任一成立
    才允许进入事务。真正创建仍受目录 ACL、卷与系统策略约束，错误正常传播。
    """
    api = _api()
    if not callable(getattr(api.kernel, "CreateSymbolicLinkW", None)):
        raise ValueError("native Windows symbolic-link API is unavailable")
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            enabled, kind = winreg.QueryValueEx(key, "AllowDevelopmentWithoutDevLicense")
            if kind == winreg.REG_DWORD and enabled == 1:
                return
    except OSError:
        # 缺失或无权读取 Developer Mode 不构成允许；仍可由当前令牌权限证明能力。
        pass
    token = HANDLE()
    _check(api.security.OpenProcessToken(api.kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
    try:
        required, luid = DWORD(), ctypes.create_string_buffer(8)
        _check(api.security.LookupPrivilegeValueW(None, "SeCreateSymbolicLinkPrivilege", luid))
        api.security.GetTokenInformation(token, 3, None, 0, ctypes.byref(required))
        if not 4 <= required.value <= 65536:
            raise ValueError("invalid bounded Windows token privileges")
        data = ctypes.create_string_buffer(required.value)
        _check(api.security.GetTokenInformation(token, 3, data, len(data), ctypes.byref(required)))
        raw = data.raw[:required.value]
        count = int.from_bytes(raw[:4], "little")
        if 4 + count * 12 > len(raw):
            raise ValueError("invalid Windows token privilege array")
        for index in range(count):
            offset = 4 + index * 12
            if raw[offset:offset + 8] == luid.raw and int.from_bytes(raw[offset + 8:offset + 12], "little") & 2:
                return
        raise ValueError("managed Skill links require Developer Mode or enabled symbolic-link privilege")
    finally:
        _close(token)


def read_skill_symlink(directory: int, name: str, *, skill_name: str):
    return node_snapshot(directory, name, skill_name=skill_name)


def move_skill_symlink(source, target, *, src_dir_fd, dst_dir_fd, skill_name: str, expected: dict) -> None:
    _move_node(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd,
               skill_name=skill_name, expected=expected)


def delete_skill_symlink(directory: int, name: str, *, skill_name: str, expected: dict) -> None:
    _check_expected(expected, "link")
    path = secure_os._path(name, directory)
    with Directory(path.parent):
        flush_directory(path.parent)
        handle = _open_skill_handle(path, READ | DELETE)
        try:
            if _opened_snapshot(handle, max_bytes=_LIMIT, skill_name=skill_name) != expected:
                raise ValueError("managed Skill changed before conditional deletion")
            disposition = BOOL(True)
            _check(_api().kernel.SetFileInformationByHandle(
                handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)), path)
        finally:
            _close(handle)
        flush_directory(path.parent)


def flush_directory(path: Path) -> None:
    """Real namespace durability barrier; unsupported accounts/filesystems fail."""
    with Directory(path) as directory:
        handle = _open_handle(directory.path, READ | WRITE, directory=True)
        try:
            _check(_api().kernel.FlushFileBuffers(handle), directory.path)
        finally:
            _close(handle)


def flush_tree(root: Path) -> None:
    """Flush a prepared tree's directory entries bottom-up before publication."""
    with Directory(root):
        with secure_os.scandir(root) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if _stat.S_ISDIR(info.st_mode):
                    flush_tree(Path(entry.path))
                elif not _stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError(f"unsafe prepared tree entry: {entry.path}")
        flush_directory(root)


def delete_directory(directory: int, name: str, *, expected: dict) -> None:
    """只条件删除已登记的普通空目录，绝不递归清理未知内容。

    调用方先释放自己对该子目录的 no-delete 句柄，但保留父目录锚定；这里
    重新取得 DELETE 句柄后核对原创建/登记的 dirID 与独立 ACL。内核的普通
    FileDispositionInformation 必须原子拒绝非空目录，不用先列目录再裸 rmdir。
    """
    if (not isinstance(expected, dict) or set(expected) != {"identity", "security"}
            or not isinstance(expected["identity"], tuple) or len(expected["identity"]) != 2
            or any(type(item) is not int or item < 0 for item in expected["identity"])
            or not isinstance(expected["security"], str) or not re.fullmatch(r"[0-9a-f]{64}", expected["security"])):
        raise ValueError("conditional directory deletion requires registered identity and ACL")
    path = secure_os._path(validate_component(name), directory)
    with Directory(path.parent):
        flush_directory(path.parent)
        handle = _open_handle(path, READ_CONTROL | 0x81 | DELETE, directory=True, sharing=SHARE_READ)
        try:
            before, security = _metadata(handle)
            if (before[:2] != expected["identity"] or not _stat.S_ISDIR(before[2])
                    or security != expected["security"]):
                raise ValueError("Windows directory changed since its registered snapshot")
            after, after_security = _metadata(handle)
            if before != after or security != after_security:
                raise ValueError("Windows directory changed during conditional deletion")
            disposition = BOOL(True)
            _check(_api().kernel.SetFileInformationByHandle(
                handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)), path)
        finally:
            _close(handle)
        flush_directory(path.parent)


def delete_regular(directory: int, name: str, *, expected: dict, max_bytes=_LIMIT) -> None:
    """在一个拒绝 WRITE/DELETE sharing 的句柄上验证并删除明确普通文件。

    expected 只接受完整七标量身份、独立 ACL 摘要和正文 SHA256；不持久化正文，
    因而可信 core GC 可保留原 128MiB 流式合同。普通调用仍默认 4MiB，marker
    明确给独立预算；上限仅为内部可信调用参数，绝不从项目 JSON/CLI 推导。
    失败不 unlink 路径、不重试、不删除碰撞的新 inode；目录 flush 失败正常传播。
    """
    if (not isinstance(expected, dict) or set(expected) != {"identity", "security", "sha256"}
            or not isinstance(expected["identity"], tuple) or len(expected["identity"]) != 7
            or any(type(item) is not int for item in expected["identity"])
            or any(not isinstance(expected[key], str) or not re.fullmatch(r"[0-9a-f]{64}", expected[key])
                   for key in ("security", "sha256"))
            or type(max_bytes) is not int or not 0 < max_bytes <= 128 * 1024 * 1024):
        raise ValueError("conditional deletion requires complete metadata, ACL and bounded digest")
    path = secure_os._path(validate_component(name), directory)
    with Directory(path.parent):
        flush_directory(path.parent)
        handle = _open_handle(path, READ | DELETE, sharing=SHARE_READ)
        try:
            before, security = _metadata(handle)
            if (before != expected["identity"] or security != expected["security"]
                    or not _stat.S_ISREG(before[2]) or before[3] != 1 or not 0 <= before[4] <= max_bytes):
                raise ValueError("Windows deletion source changed since its expected snapshot")
            digest, total = hashlib.sha256(), 0
            buffer = ctypes.create_string_buffer(min(max_bytes + 1, 1024 * 1024))
            while True:
                count = DWORD()
                _check(_api().kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None), path)
                if not count.value:
                    break
                total += count.value
                if total > max_bytes:
                    raise ValueError("Windows deletion source exceeds bounded stream budget")
                digest.update(buffer.raw[:count.value])
            after, after_security = _metadata(handle)
            if (after != before or after_security != security or total != before[4]
                    or digest.hexdigest() != expected["sha256"]):
                raise ValueError("Windows deletion source changed during its bounded verification")
            disposition = BOOL(True)
            _check(_api().kernel.SetFileInformationByHandle(
                handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)), path)
        finally:
            _close(handle)
        flush_directory(path.parent)


def remove_file_if_unchanged(path: Path, digest: str, identity=None, *, limit=128 * 1024 * 1024) -> bool:
    """Validate and delete one opened identity, excluding ordinary writers/swaps."""
    path = absolute_path(path)
    with Directory(path.parent):
        handle = _open_handle(path, READ | DELETE, sharing=SHARE_READ)
        removed = False
        try:
            info = _information(handle)
            actual = (info.volume, info.index_high << 32 | info.index_low)
            if identity is not None and actual != identity:
                return False
            size = info.size_high << 32 | info.size_low
            if size > limit:
                return False
            hasher = hashlib.sha256()
            buffer = ctypes.create_string_buffer(1024 * 1024)
            total = 0
            while True:
                count = DWORD()
                _check(_api().kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None), path)
                if not count.value:
                    break
                total += count.value
                if total > limit:
                    return False
                hasher.update(buffer.raw[:count.value])
            if total != size or hasher.hexdigest() != digest:
                return False
            disposition = BOOL(True)
            _check(_api().kernel.SetFileInformationByHandle(
                handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)), path)
            removed = True
        finally:
            _close(handle)
        if removed:
            flush_directory(path.parent)
        return removed


def read_file(path: Path, limit=4 * 1024 * 1024) -> bytes | None:
    """宿主读取与薄启动器共用可信初读边界；只有不存在映射为 None。"""
    try:
        # 共享 bytes 读取入口维持原本可接收相对路径的合同，先严格校验原拼写再
        # 锚定为绝对路径。可嵌入的初读闭包自身仍只接收明确绝对机器路径。
        return read_initial_regular(absolute_path(path), limit)
    except FileNotFoundError:
        return None


def read_initial_regular(path, limit=4 * 1024 * 1024, *, require_private=False) -> bytes:
    """尚未信任 core 模块时的独立只读闭包，供生成阶段嵌入薄启动器。

    所有原生对象、长度和 ACL 都来自当前句柄；祖先拒绝 delete sharing，叶子
    拒绝 write/delete sharing。DACL 可独立变化，故前后按真实权限规范复核。
    这只证明当前可观察状态稳定，不追溯状态完全相同的历史写，不创建文件。
    """
    import ctypes
    import os
    from pathlib import Path, PureWindowsPath

    if os.name != "nt":
        raise OSError("initial Windows reader requires native Windows")
    if type(limit) is not int or not 0 < limit <= 8 * 1024 * 1024 or type(require_private) is not bool:
        raise ValueError("invalid bounded initial read budget or privacy flag")
    raw = os.fspath(path)
    windows = PureWindowsPath(raw)
    if (not isinstance(raw, str) or not windows.is_absolute() or windows.drive.startswith("\\\\")
            or raw.startswith(("\\\\?\\", "\\\\.\\")) or "\0" in raw):
        raise ValueError("initial reader requires an absolute local drive path")
    for component in raw[len(windows.drive):].replace("\\", "/").split("/"):
        if component:
            validate_component(component)
    path = Path(raw)
    if path == Path(path.anchor):
        raise ValueError("initial reader requires a regular file")
    D, H, B = ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int32
    kernel, security = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("advapi32", use_last_error=True)

    class Time(ctypes.Structure):
        _fields_ = [("low", D), ("high", D)]

    class Info(ctypes.Structure):
        _fields_ = [("attributes", D), ("created", Time), ("accessed", Time), ("modified", Time),
                   ("volume", D), ("size_high", D), ("size_low", D), ("links", D),
                   ("index_high", D), ("index_low", D)]

    class Basic(ctypes.Structure):
        _fields_ = [("created", ctypes.c_int64), ("accessed", ctypes.c_int64),
                   ("modified", ctypes.c_int64), ("changed", ctypes.c_int64), ("attributes", D)]

    prototypes = (
        (kernel, "CreateFileW", H, [ctypes.c_wchar_p, D, D, H, D, D, H]),
        (kernel, "CloseHandle", B, [H]),
        (kernel, "GetFileInformationByHandle", B, [H, ctypes.POINTER(Info)]),
        (kernel, "GetFileInformationByHandleEx", B, [H, ctypes.c_int, H, D]),
        (kernel, "GetDriveTypeW", D, [ctypes.c_wchar_p]),
        (kernel, "GetVolumeInformationByHandleW", B, [H, ctypes.c_wchar_p, D, H, H, H, ctypes.c_wchar_p, D]),
        (kernel, "GetFinalPathNameByHandleW", D, [H, ctypes.c_wchar_p, D, D]),
        (kernel, "ReadFile", B, [H, H, D, ctypes.POINTER(D), H]),
        (kernel, "LocalFree", H, [H]),
        (kernel, "GetCurrentProcess", H, []),
        (security, "OpenProcessToken", B, [H, D, ctypes.POINTER(H)]),
        (security, "GetTokenInformation", B, [H, ctypes.c_int, H, D, ctypes.POINTER(D)]),
        (security, "GetSecurityInfo", D, [H, ctypes.c_int, D, H, H, H, H, ctypes.POINTER(H)]),
        (security, "GetSecurityDescriptorControl", B, [H, H, H]),
        (security, "GetSecurityDescriptorOwner", B, [H, ctypes.POINTER(H), ctypes.POINTER(B)]),
        (security, "GetSecurityDescriptorDacl", B, [H, ctypes.POINTER(B), ctypes.POINTER(H), ctypes.POINTER(B)]),
        (security, "GetLengthSid", D, [H]),
        (security, "IsValidSid", B, [H]),
        (security, "IsValidAcl", B, [H]),
    )
    for library, name, result, arguments in prototypes:
        function = getattr(library, name)
        function.restype, function.argtypes = result, arguments

    def check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def token_user():
        token, required = H(), D()
        check(security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
        try:
            security.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
            if not ctypes.sizeof(H) + 8 <= required.value <= 65536:
                raise ValueError("initial reader token user exceeds bounded size")
            data = ctypes.create_string_buffer(required.value)
            check(security.GetTokenInformation(token, 1, data, len(data), ctypes.byref(required)))
            sid = ctypes.cast(data, ctypes.POINTER(H)).contents.value
            if not sid or not security.IsValidSid(sid):
                raise ValueError("initial reader requires valid current user SID")
            length = security.GetLengthSid(sid)
            if (not 8 <= length <= 68 or sid < ctypes.addressof(data)
                    or sid + length > ctypes.addressof(data) + len(data)):
                raise ValueError("initial reader token SID is outside bounded buffer")
            return ctypes.string_at(sid, length)
        finally:
            check(kernel.CloseHandle(token))

    user = token_user() if require_private else None

    def permissions(handle, private=False):
        descriptor, owner, acl = H(), H(), H()
        error = security.GetSecurityInfo(handle, 1, 5, None, None, None, None, ctypes.byref(descriptor))
        if error:
            raise ctypes.WinError(error)
        try:
            defaulted, present, control, revision = B(), B(), ctypes.c_uint16(), D()
            check(security.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted)))
            check(security.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)))
            check(security.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)))
            if (not present.value or not owner.value or not acl.value
                    or not security.IsValidSid(owner) or not security.IsValidAcl(acl)):
                raise ValueError("initial reader requires a valid owner and non-null DACL")
            sid_length = security.GetLengthSid(owner)
            if not 8 <= sid_length <= 68:
                raise ValueError("initial reader owner exceeds bounded SID size")
            acl_length = int.from_bytes(ctypes.string_at(acl, 8)[2:4], "little")
            if not 8 <= acl_length <= 65535:
                raise ValueError("initial reader ACL exceeds bounded size")
            owner_bytes, acl_bytes = ctypes.string_at(owner, sid_length), ctypes.string_at(acl, acl_length)
            if private and not _private_policy_bytes(owner_bytes, control.value, acl_bytes, user):
                raise ValueError("initial private reader requires current-user/SYSTEM protected owner and DACL")
            return _canonical_security(owner_bytes, control.value, acl_bytes)
        finally:
            kernel.LocalFree(descriptor)

    def facts(handle, directory):
        info, basic = Info(), Basic()
        check(kernel.GetFileInformationByHandle(handle, ctypes.byref(info)))
        check(kernel.GetFileInformationByHandleEx(handle, 0, ctypes.byref(basic), ctypes.sizeof(basic)))
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise ValueError("initial reader refuses reparse points and unexpected file types")
        if not directory and info.links != 1:
            raise ValueError("initial reader requires a single-link regular file")
        return (info.volume, info.index_high << 32 | info.index_low, info.attributes,
                info.links, info.size_high << 32 | info.size_low,
                info.modified.high << 32 | info.modified.low, basic.changed,
                permissions(handle, require_private and not directory))

    handles, ancestors = [], []
    try:
        current = Path(path.anchor)
        for component in (None, *path.parent.parts[1:]):
            if component is not None:
                current /= component
            handle = kernel.CreateFileW(str(current), 0x20081, 3, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value:
                check(False)
            handles.append(handle)
            state = facts(handle, True)
            ancestors.append((handle, (state[0], state[1], state[-1])))
        filesystem, final_path = ctypes.create_unicode_buffer(32), ctypes.create_unicode_buffer(32768)
        check(kernel.GetVolumeInformationByHandleW(handles[-1], None, 0, None, None, None, filesystem, len(filesystem)))
        count = check(kernel.GetFinalPathNameByHandleW(handles[-1], final_path, len(final_path), 0))
        if (count >= len(final_path) or not final_path.value.startswith("\\\\?\\")
                or len(final_path.value) < 7 or final_path.value[5:7] != ":\\"
                or filesystem.value != "NTFS" or kernel.GetDriveTypeW(path.anchor) != 3):
            raise ValueError("initial reader requires an actual local NTFS handle")
        handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            check(False)
        handles.append(handle)
        before = facts(handle, False)
        if before[4] > limit:
            raise ValueError("initial file exceeds bounded read budget")
        body, buffer = bytearray(), ctypes.create_string_buffer(min(limit + 1, 1024 * 1024))
        while True:
            received = D()
            check(kernel.ReadFile(handle, buffer, min(len(buffer), limit + 1 - len(body)), ctypes.byref(received), None))
            if not received.value:
                break
            body.extend(buffer.raw[:received.value])
            if len(body) > limit:
                raise ValueError("initial file exceeds bounded read budget")
        if len(body) != before[4] or facts(handle, False) != before:
            raise ValueError("initial file changed during trusted read")
        for ancestor, expected in ancestors:
            state = facts(ancestor, True)
            if (state[0], state[1], state[-1]) != expected:
                raise ValueError("initial file ancestry or permissions changed during trusted read")
        return bytes(body)
    finally:
        close_error = None
        for handle in reversed(handles):
            if not kernel.CloseHandle(handle) and close_error is None:
                close_error = ctypes.WinError(ctypes.get_last_error())
        if close_error is not None:
            raise close_error


def bootstrap_reader_source() -> str:
    """可信生成时把同一纯规范嵌入单函数闭包；运行时不读取未验 core 源码。"""
    import inspect
    import textwrap
    source = inspect.getsource(read_initial_regular)
    header, body = source.split("\n", 1)
    helpers = (inspect.getsource(validate_component) + "\n" + inspect.getsource(_canonical_security)
               + "\n" + inspect.getsource(_private_policy_bytes))
    return header + "\n" + textwrap.indent(helpers, "    ") + body
