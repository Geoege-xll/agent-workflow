"""Handle-anchored Windows I/O for the project runtime (no global os patches).

Directory handles deny delete sharing for their entire lifetime: every ancestor
stays pinned while a path-based Win32 operation runs. Reparse points, remote
volumes and multi-link files are refused, not treated as POSIX no-follow support.
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import os as _os
from pathlib import Path, PureWindowsPath
import re
import stat as _stat
from types import SimpleNamespace


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


def _policy_is_private(policy, *, object_type=1):
    if policy.owner != _sid_bytes(current_sid()) or not policy.control & 0x1000:
        return False
    data = policy.acl_bytes
    if int.from_bytes(data[4:6], "little") != 2:
        return False
    wanted = {_sid_bytes(current_sid()), _sid_bytes("S-1-5-18")}
    offset, found = 8, set()
    for _ in range(2):
        size = int.from_bytes(data[offset + 2:offset + 4], "little")
        ace = data[offset:offset + size]
        rights = int.from_bytes(ace[4:8], "little")
        all_access = 0x1F01FF if object_type == 1 else 0x1F0001
        if (len(ace) < 16 or ace[0] != 0 or ace[1] & ~0x07
                or rights not in (0x10000000, all_access) or ace[8:] not in wanted):
            return False
        found.add(ace[8:])
        offset += size
    return found == wanted


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
def private_security():
    api = _api()
    descriptor = HANDLE()
    sid = current_sid()
    _check(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        f"O:{sid}D:P(A;OICI;GA;;;{sid})(A;OICI;GA;;;SY)", 1, ctypes.byref(descriptor), None))
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
    都不调用它，只有调用者明确请求私有 chmod/fchmod 才能进入该策略。
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


def _copy_permissions(source, destination):
    """复制并核实真实 DACL；不同 stage 父继承带来的重写不能当作成功。"""
    with _security_policy(source) as before:
        protection = 0x80000000 if before.control & 0x1000 else 0x20000000
        error = _api().security.SetSecurityInfo(destination, 1, 4 | protection,
                                                None, None, before.acl, None)
        if error:
            raise ctypes.WinError(error)
        with _security_policy(destination) as after, _security_policy(source) as current:
            if after.dacl_key != before.dacl_key or current.dacl_key != before.dacl_key:
                raise ValueError("Windows DACL copy changed inheritance or raced with a permission update")


def copy_permissions(source: Path, destination: Path) -> None:
    """Preserve a known ordinary file's DACL without following either path."""
    source, destination = absolute_path(source), absolute_path(destination)
    with Directory(source.parent), Directory(destination.parent):
        old = _open_handle(source, READ)
        try:
            new = _open_handle(destination, READ | WRITE | 0x40000)
            try:
                _copy_permissions(old, new)
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

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        import msvcrt
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
                                          exclusive=bool(flags & _os.O_EXCL), security=ctypes.byref(attributes))
            else:
                handle = _open_handle(path, access, create=bool(flags & _os.O_CREAT),
                                      exclusive=bool(flags & _os.O_EXCL))
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
        # DACL for new files; replacement copies the exact existing target DACL.
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
            # 普通模式不放宽 ACL，也不自动修 owner；替换仍复制并复核原 DACL。

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
                            old = _open_handle(target, READ)
                            try:
                                _copy_permissions(old, handle)
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


def _move_node(source, target, *, src_dir_fd, dst_dir_fd, expected, skill_name=None):
    _check_expected(expected, "link" if skill_name is not None else "file")
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


def move_regular(source, target, *, src_dir_fd=None, dst_dir_fd=None, expected: dict) -> None:
    """排他消费一个完整快照相符的普通文件；失败后不清除已移动的恢复见证。"""
    _move_node(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, expected=expected)


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


def read_initial_regular(path, limit=4 * 1024 * 1024) -> bytes:
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
    if type(limit) is not int or not 0 < limit <= 8 * 1024 * 1024:
        raise ValueError("invalid bounded initial read budget")
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

    def permissions(handle):
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
            return _canonical_security(ctypes.string_at(owner, sid_length), control.value,
                                       ctypes.string_at(acl, acl_length))
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
                info.modified.high << 32 | info.modified.low, basic.changed, permissions(handle))

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
    helpers = inspect.getsource(validate_component) + "\n" + inspect.getsource(_canonical_security)
    return header + "\n" + textwrap.indent(helpers, "    ") + body
