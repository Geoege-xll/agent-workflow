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


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", DWORD), ("descriptor", HANDLE), ("inherit", BOOL)]


class _Time(ctypes.Structure):
    _fields_ = [("low", DWORD), ("high", DWORD)]


class _Info(ctypes.Structure):
    _fields_ = [("attributes", DWORD), ("created", _Time), ("accessed", _Time),
               ("modified", _Time), ("volume", DWORD), ("size_high", DWORD),
               ("size_low", DWORD), ("links", DWORD), ("index_high", DWORD),
               ("index_low", DWORD)]


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
        "ConvertSidToStringSidW": (BOOL, [HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]),
        "ConvertStringSidToSidW": (BOOL, [ctypes.c_wchar_p, ctypes.POINTER(HANDLE)]),
        "EqualSid": (BOOL, [HANDLE, HANDLE]),
        "GetAclInformation": (BOOL, [HANDLE, HANDLE, DWORD, DWORD]),
        "GetAce": (BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
        "ConvertStringSecurityDescriptorToSecurityDescriptorW":
            (BOOL, [ctypes.c_wchar_p, DWORD, ctypes.POINTER(HANDLE), HANDLE]),
        "GetSecurityDescriptorDacl":
            (BOOL, [HANDLE, ctypes.POINTER(BOOL), ctypes.POINTER(HANDLE), ctypes.POINTER(BOOL)]),
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


def _stat_info(info):
    def ns(value):
        return ((value.high << 32 | value.low) - _EPOCH) * 100
    accessed, modified, created = (ns(info.accessed), ns(info.modified), ns(info.created))
    mode = _stat.S_IFDIR if info.attributes & ATTR_DIRECTORY else _stat.S_IFREG
    if info.attributes & ATTR_REPARSE:
        mode = _stat.S_IFLNK
    mode |= 0o444 if info.attributes & 1 else 0o666
    if _stat.S_ISDIR(mode):
        mode |= 0o111
    return _os.stat_result(
        (mode, info.index_high << 32 | info.index_low, info.volume, info.links,
         0, 0, info.size_high << 32 | info.size_low,
         accessed / 1e9, modified / 1e9, created / 1e9),
        {"st_atime_ns": accessed, "st_mtime_ns": modified, "st_ctime_ns": created,
         "st_file_attributes": info.attributes},
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
                self.handles.append(_open_handle(current, 0x81, directory=True))
            filesystem = ctypes.create_unicode_buffer(32)
            _check(_api().kernel.GetVolumeInformationByHandleW(
                self.handle, None, 0, None, None, None, filesystem, len(filesystem)))
            if filesystem.value != "NTFS":
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
    _check(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        f"D:P(A;OICI;GA;;;{current_sid()})(A;OICI;GA;;;SY)", 1, ctypes.byref(descriptor), None))
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


def restrict_handle(handle):
    with private_security() as descriptor:
        error = _api().security.SetSecurityInfo(handle, 1, 0x80000004,
                                               None, None, _dacl(descriptor), None)
        if error:
            raise ctypes.WinError(error)


def assert_private(path):
    """Verify owner and protected current-user/SYSTEM ACL, not an owner marker."""
    api = _api()
    with Directory(path):
        handle = _open_handle(path, 0x20080, directory=True)
        descriptor, owner, acl = HANDLE(), HANDLE(), HANDLE()
        user, system = HANDLE(), HANDLE()
        try:
            error = api.security.GetSecurityInfo(handle, 1, 1 | 4, ctypes.byref(owner), None,
                                                 ctypes.byref(acl), None, ctypes.byref(descriptor))
            if error:
                raise ctypes.WinError(error)
            _check(api.security.ConvertStringSidToSidW(current_sid(), ctypes.byref(user)))
            _check(api.security.ConvertStringSidToSidW("S-1-5-18", ctypes.byref(system)))
            if not api.security.EqualSid(owner, user) or not acl.value:
                raise ValueError("private Windows directory has an unknown owner or null DACL")
            control, revision = ctypes.c_uint16(), DWORD()
            _check(api.security.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)))
            if not control.value & 0x1000:  # SE_DACL_PROTECTED
                raise ValueError("private Windows directory allows inherited ACL changes")
            class AclSize(ctypes.Structure):
                _fields_ = [("count", DWORD), ("used", DWORD), ("free", DWORD)]
            size = AclSize()
            _check(api.security.GetAclInformation(acl, ctypes.byref(size), ctypes.sizeof(size), 2))
            if size.count != 2:
                raise ValueError("private Windows directory has unexpected access entries")
            found = set()
            for index in range(size.count):
                ace = HANDLE()
                _check(api.security.GetAce(acl, index, ctypes.byref(ace)))
                header = ctypes.string_at(ace, 8)
                if header[0] != 0 or header[1] & 0x18 or int.from_bytes(header[4:8], "little") not in (0x10000000, 0x1f01ff):
                    raise ValueError("private Windows directory has unsupported access rights")
                sid = HANDLE(ace.value + 8)
                if api.security.EqualSid(sid, user):
                    found.add("user")
                elif api.security.EqualSid(sid, system):
                    found.add("system")
                else:
                    raise ValueError("private Windows directory grants another principal access")
            if found != {"user", "system"}:
                raise ValueError("private Windows directory ACL is incomplete")
        finally:
            for allocation in (user, system, descriptor):
                if allocation.value:
                    api.kernel.LocalFree(allocation)
            _close(handle)


def _copy_permissions(source, destination):
    descriptor, acl = HANDLE(), HANDLE()
    api = _api()
    error = api.security.GetSecurityInfo(source, 1, 4, None, None,
                                         ctypes.byref(acl), None, ctypes.byref(descriptor))
    if error:
        raise ctypes.WinError(error)
    try:
        control, revision = ctypes.c_uint16(), DWORD()
        _check(api.security.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)))
        # Preserve the inheritance policy as well as the ACEs. For an inheriting
        # destination, SetSecurityInfo also applies its parent's inheritable ACEs.
        protection = 0x80000000 if control.value & 0x1000 else 0x20000000
        error = api.security.SetSecurityInfo(destination, 1, 4 | protection,
                                             None, None, acl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        api.kernel.LocalFree(descriptor)


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
        name = f"Local\\AgentWorkflow-{current_sid()}-{key}"
        with private_security() as descriptor:
            attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, 0)
            mutex = _api().kernel.CreateMutexW(ctypes.byref(attributes), False, name)
        _check(mutex)
        acquired = False
        try:
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
            if acquired:
                _check(_api().kernel.ReleaseMutex(mutex))
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
        import msvcrt
        handle = (self._directories[descriptor].handle if descriptor in self._directories
                  else msvcrt.get_osfhandle(descriptor))
        return _stat_info(_information(handle))

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        path = self._path(path, dir_fd)
        if path == Path(path.anchor):
            with Directory(path) as directory:
                return _stat_info(_information(directory.handle))
        with Directory(path.parent):
            handle = _api().kernel.CreateFileW(str(path), 0x80,
                                               SHARE_READ | SHARE_WRITE, None, 3,
                                               BACKUP_SEMANTICS | OPEN_REPARSE_POINT, None)
            if handle == INVALID_HANDLE:
                _check(False, path)
            try:
                info = _information(handle)
                if follow_symlinks and info.attributes & ATTR_REPARSE:
                    raise ValueError(f"following reparse points is forbidden: {path}")
                return _stat_info(info)
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
        import msvcrt
        handle = msvcrt.get_osfhandle(descriptor)
        if not mode & 0o077:
            # tempfile uses CRT handles without WRITE_DAC. Reopen under pinned
            # ancestors and compare file identity before changing permissions.
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
            writable = None
            try:
                writable = _open_handle(path, 0x60080)
                expected, actual = _information(handle), _information(writable)
                if (expected.volume, expected.index_high, expected.index_low) != (actual.volume, actual.index_high, actual.index_low):
                    raise ValueError("temporary file identity changed before ACL update")
                restrict_handle(writable)
                if descriptor not in self._files:
                    self._files[descriptor] = parent
                    parent = None
            finally:
                if writable is not None:
                    _close(writable)
                if parent is not None:
                    parent.close()
        # Broader POSIX modes cannot grant Windows access: inherit the parent's
        # DACL for new files; replacement copies the exact existing target DACL.
        if not mode & 0o200:
            raise ValueError("read-only POSIX mode needs explicit Windows ACL policy")

    def chmod(self, path, mode, *, dir_fd=None, follow_symlinks=True):
        path = self._path(path, dir_fd)
        with Directory(path.parent):
            info = self.lstat(path)
            directory = _stat.S_ISDIR(info.st_mode)
            handle = _open_handle(path, 0x60080, directory=directory)
            try:
                if not mode & 0o200:
                    raise ValueError("read-only POSIX mode needs explicit Windows ACL policy")
                if not mode & 0o077:
                    restrict_handle(handle)
                # Never widen a Windows DACL to approximate POSIX group/other bits.
                # Existing ACLs stay intact; replacements copy the target ACL.
            finally:
                _close(handle)

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
                # Rename the opened identity, not a checked-then-reopened source
                # pathname. Destination ancestry stays pinned throughout the call.
                encoded = target.name.encode("utf-16-le")
                buffer = ctypes.create_string_buffer(max(ctypes.sizeof(_RenameInfo),
                                                         _RenameInfo.name.offset + len(encoded)))
                rename = _RenameInfo.from_buffer(buffer)
                rename.flags, rename.root, rename.length = int(replace), destination.handle, len(encoded)
                ctypes.memmove(ctypes.addressof(buffer) + _RenameInfo.name.offset, encoded, len(encoded))
                _check(_api().kernel.SetFileInformationByHandle(handle, 3, buffer, len(buffer)), target)
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
    try:
        descriptor = secure_os.open(path, _os.O_RDONLY | NOFOLLOW)
    except FileNotFoundError:
        return None
    with secure_os.fdopen(descriptor, "rb") as stream:
        before = secure_os.fstat(stream.fileno())
        if before.st_size > limit:
            raise ValueError(f"file exceeds safe read limit: {path}")
        body = stream.read(limit + 1)
        after = secure_os.fstat(stream.fileno())
    if (len(body) > limit or (before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError(f"file changed during safe read: {path}")
    return body
