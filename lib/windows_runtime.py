"""Offline immutable CPython deployment for the npx entry; stdout is JSON only."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import uuid

# Embedded Python's _pth contains '.', not this script's directory. The directory
# is part of the tool payload, never the caller cwd or an arbitrary PYTHONPATH.
sys.path.insert(0, str(Path(__file__).absolute().parent))
if __package__:
    from .windows_fs import (Directory, directory_lock, secure_os, read_file, assert_private,
                             flush_directory, flush_tree, remove_file_if_unchanged)
else:
    from windows_fs import (Directory, directory_lock, secure_os, read_file, assert_private,
                            flush_directory, flush_tree, remove_file_if_unchanged)


OWNER = b'{"owner":"agent-workflow:npx-runtime","schema_version":1}\n'
REQUIRED = {"python.exe", "windows_bootstrap.py", "windows_fs.py", "windows_runtime.py"}


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def parse_manifest(body: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate runtime manifest key: {key}")
            result[key] = value
        return result
    document = json.loads(body, object_pairs_hook=pairs)
    if (not isinstance(document, dict) or set(document) != {"schema_version", "version", "architecture", "files"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or document["architecture"] != "x64"
            or not isinstance(document["version"], str)
            or not re.fullmatch(r"3\.(?:1[1-9]|[2-9][0-9])\.[0-9]+", document["version"])
            or not isinstance(document["files"], dict) or not 4 <= len(document["files"]) <= 4096):
        raise ValueError("unsupported runtime manifest")
    seen = set()
    for name, digest in document["files"].items():
        path = PurePosixPath(name)
        if (not name or "\\" in name or ":" in name or path.is_absolute()
                or path.as_posix() != name or any(part in {".", ".."} for part in path.parts)
                or name.casefold() in seen or name.casefold() == "manifest.json"
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError(f"unsafe runtime manifest entry: {name!r}")
        seen.add(name.casefold())
    if not REQUIRED <= document["files"].keys():
        raise ValueError("runtime is missing its executable or trusted helpers")
    return document


def local_appdata() -> Path:
    # Use the OS known-folder API rather than trusting a caller's LOCALAPPDATA.
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    folder = ctypes.create_string_buffer(uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
    result = ctypes.c_wchar_p()
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_int32
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    status = shell.SHGetKnownFolderPath(folder, 0, None, ctypes.byref(result))
    if status:
        raise OSError(f"cannot locate private LocalAppData: HRESULT {status & 0xffffffff:08x}")
    try:
        return Path(result.value)
    finally:
        ole.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))


def _write(path, body):
    descriptor = secure_os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with secure_os.fdopen(descriptor, "wb") as output:
        output.write(body)
        output.flush()
        secure_os.fsync(output.fileno())
        info = secure_os.fstat(output.fileno())
        identity = (info.st_dev, info.st_ino)
    flush_directory(path.parent)
    return identity


def _ensure_owned_base() -> Path:
    parent = local_appdata()
    base = parent / "AgentWorkflow"
    with directory_lock(parent, "runtime-base", blocking=True):
        # LocalAppData can be on a different volume from the project. Probe its
        # real metadata durability before creating any private runtime namespace.
        flush_directory(parent)
        try:
            with Directory(base):
                assert_private(base)
                if read_file(base / ".npx-owner.json") != OWNER:
                    raise ValueError(f"unknown runtime directory; nothing overwritten: {base}")
        except FileNotFoundError:
            # An existing unowned directory is never adopted after missing marker.
            try:
                secure_os.lstat(base)
            except FileNotFoundError:
                secure_os.mkdir(base, 0o700)
                _write(base / ".npx-owner.json", OWNER)
            else:
                raise ValueError(f"unowned runtime directory: {base}")
        for name in ("runtimes", "control"):
            child = base / name
            try:
                with Directory(child):
                    assert_private(child)
            except FileNotFoundError:
                secure_os.mkdir(child, 0o700)
            flush_directory(child)
        flush_directory(base)
        flush_directory(parent)
    return base


def _files(root: Path) -> set[str]:
    result = set()
    def visit(directory, depth):
        if depth > 16:
            raise ValueError("runtime directory exceeds depth limit")
        with secure_os.scandir(directory) as entries:
            for entry in entries:
                if len(result) > 4096:
                    raise ValueError("runtime directory exceeds file limit")
                if entry.is_symlink():
                    raise ValueError("runtime contains a reparse point")
                if entry.is_dir(follow_symlinks=False):
                    visit(Path(entry.path), depth + 1)
                elif entry.is_file(follow_symlinks=False):
                    result.add(Path(entry.path).relative_to(root).as_posix())
                else:
                    raise ValueError("runtime contains a special file")
    visit(root, 0)
    return result


def verify_tree(root: Path, document: dict) -> None:
    with Directory(root):
        if _files(root) != set(document["files"]) | {"manifest.json"}:
            raise ValueError(f"runtime file inventory differs; preserved without repair: {root}")
        for name, expected in document["files"].items():
            body = read_file(root / name, 128 * 1024 * 1024)
            if body is None or hashlib.sha256(body).hexdigest() != expected:
                raise ValueError(f"runtime checksum differs: {name}")
        body = read_file(root / "manifest.json", 1024 * 1024)
        if body is None or parse_manifest(body) != document:
            raise ValueError("runtime manifest differs")


def self_check(root: Path, document: dict) -> None:
    source = ("import json,sys,tomllib,ctypes,hashlib; "
              "print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),"
              "'bits':64 if sys.maxsize>2**32 else 32}))")
    result = subprocess.run(
        [str(root / "python.exe"), "-I", "-B", "-X", "utf8",
         str(root / "windows_bootstrap.py"), "-c", source],
        cwd=root.parent, capture_output=True, text=True, encoding="utf-8", timeout=20,
        check=True,
    )
    if json.loads(result.stdout) != {"version": document["version"], "bits": 64}:
        raise ValueError("private Python runtime self-check failed")


def deploy(source: Path, manifest: Path) -> dict:
    if os.name != "nt" or sys.maxsize <= 2**32:
        raise ValueError("the bundled runtime requires native Windows x64")
    if manifest.absolute() != source.absolute() / "manifest.json":
        raise ValueError("runtime manifest must be inside its source directory")
    body = read_file(manifest, 1024 * 1024)
    if body is None:
        raise ValueError("runtime manifest is missing")
    document = parse_manifest(body)
    verify_tree(source, document)
    digest = hashlib.sha256(canonical(document)).hexdigest()
    base = _ensure_owned_base()
    parent = base / "runtimes"
    target = parent / f"cpython-{document['version']}-x64-{digest}"
    with directory_lock(parent, "runtime-deploy", blocking=True):
        flush_directory(parent)
        try:
            with Directory(target):
                assert_private(target)
                verify_tree(target, document)
        except FileNotFoundError:
            # A partial/unknown published version must not be overwritten.
            try:
                secure_os.lstat(target)
            except FileNotFoundError:
                stage = parent / (".stage-" + uuid.uuid4().hex)
                secure_os.mkdir(stage, 0o700)
                written = []
                try:
                    for name, expected in document["files"].items():
                        destination = stage / name
                        for directory in reversed(destination.parent.relative_to(stage).parents):
                            if directory != Path("."):
                                try:
                                    secure_os.mkdir(stage / directory, 0o700)
                                except FileExistsError:
                                    pass
                        if destination.parent != stage:
                            try:
                                secure_os.mkdir(destination.parent, 0o700)
                            except FileExistsError:
                                pass
                        data = read_file(source / name, 128 * 1024 * 1024)
                        if data is None or hashlib.sha256(data).hexdigest() != expected:
                            raise ValueError(f"runtime source changed: {name}")
                        identity = _write(destination, data)
                        written.append((destination, expected, identity))
                    identity = _write(stage / "manifest.json", canonical(document))
                    written.append((stage / "manifest.json", hashlib.sha256(canonical(document)).hexdigest(), identity))
                    verify_tree(stage, document)
                    self_check(stage, document)
                    flush_tree(stage)
                    secure_os.rename(stage, target)
                except BaseException:
                    # Only exact files created by this invocation may be removed.
                    for path, expected, identity in reversed(written):
                        try:
                            remove_file_if_unchanged(path, expected, identity)
                        except (OSError, ValueError):
                            pass
                    # Leave non-empty or changed staging trees for inspection.
                    try:
                        secure_os.rmdir(stage)
                    except OSError:
                        pass
                    raise
            else:
                raise ValueError(f"damaged or unknown runtime; preserved: {target}")
    with Directory(target):
        verify_tree(target, document)
        self_check(target, document)
        flush_tree(target)
        flush_directory(parent)
    control = base / "control" / uuid.uuid4().hex
    secure_os.mkdir(control, 0o700)
    _write(control / ".owner", OWNER)
    return {"python": str(target / "python.exe"),
            "bootstrap": str(target / "windows_bootstrap.py"), "runtime": str(target),
            "cancel_file": str(control / "cancel")}


@contextmanager
def cancellation_guard(raw: str):
    """Pin the helper-owned channel until all setup writers/recovery have stopped."""
    path = Path(raw).absolute()
    base = local_appdata() / "AgentWorkflow"
    if (path.name != "cancel" or path.parent.parent != base / "control"
            or not re.fullmatch(r"[0-9a-f]{32}", path.parent.name)):
        raise ValueError("not an owned cancellation path")
    with Directory(path.parent):
        assert_private(base)
        assert_private(path.parent.parent)
        assert_private(path.parent)
        if read_file(base / ".npx-owner.json") != OWNER or read_file(path.parent / ".owner") != OWNER:
            raise ValueError("unowned cancellation channel")
        if _files(path.parent) - {".owner", "cancel"}:
            raise ValueError("modified cancellation channel")
        # A preexisting empty request is valid: Ctrl+C can arrive before Python.
        if read_file(path, 0) not in (None, b""):
            raise ValueError("invalid cancellation request")
        yield


def cleanup_control(raw: str) -> None:
    path = Path(raw).absolute()
    base = local_appdata() / "AgentWorkflow"
    if (path.name != "cancel" or path.parent.parent != base / "control"
            or not re.fullmatch(r"[0-9a-f]{32}", path.parent.name)):
        raise ValueError("not an owned cancellation path")
    with Directory(path.parent):
        assert_private(base)
        assert_private(path.parent.parent)
        assert_private(path.parent)
        if read_file(path.parent / ".owner") != OWNER:
            raise ValueError("unowned cancellation directory")
        if _files(path.parent) - {".owner", "cancel"}:
            raise ValueError("cancellation directory was modified; preserved")
        try:
            if not remove_file_if_unchanged(path, hashlib.sha256(b"").hexdigest(), limit=0):
                raise ValueError("cancellation request changed; preserved")
        except FileNotFoundError:
            pass
        if not remove_file_if_unchanged(path.parent / ".owner", hashlib.sha256(OWNER).hexdigest()):
            raise ValueError("cancellation owner changed; preserved")
    secure_os.rmdir(path.parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--cleanup-control")
    args = parser.parse_args()
    try:
        if args.cleanup_control:
            if args.source or args.manifest:
                raise ValueError("cleanup cannot be combined with deployment")
            cleanup_control(args.cleanup_control)
        else:
            if args.source is None or args.manifest is None:
                raise ValueError("--source and --manifest are required")
            print(json.dumps(deploy(args.source, args.manifest)))
    except (OSError, ValueError, KeyboardInterrupt, subprocess.SubprocessError) as exc:
        print(f"[ERROR] private runtime: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
