#!/usr/bin/env python3
"""Prepare an offline Windows npm package from a local, pinned official CPython ZIP.

Run with Python -I. This tool never downloads, executes archive code, installs,
invokes npm, or publishes. Its output must be a new directory.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import unicodedata
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".sync-backups", "__pycache__", ".DS_Store", ".pytest_cache", "node_modules",
            "tests", "__tests__", "backups", ".cache", "manager", "tui"}
SCRIPTS = {"guard.sh", "lint_rules.sh", "scaffold_project_docs.sh"}
STARTUP_FILES = ("package.json", "bin/agent-workflow.cjs", "THIRD_PARTY_NOTICES.txt")
RUNTIME_HELPERS = ("windows_bootstrap.py", "windows_fs.py", "windows_runtime.py")
MAX_FILES = 4096
MAX_FILE_SIZE = 128 * 1024 * 1024
MAX_TOTAL_SIZE = 256 * 1024 * 1024
MAX_ARCHIVE_SIZE = 64 * 1024 * 1024
DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])", re.I)


def safe_name(name: str) -> str:
    """Use a conservative Win32 namespace even when preparing on POSIX."""
    if not name or len(name) > 240 or "\\" in name or name.startswith("/"):
        raise ValueError(f"Unsafe Windows payload path: {name!r}")
    parts = name.split("/")
    for part in parts:
        if (not part or part in {".", ".."} or len(part) > 255
                or part[-1:] in {".", " "} or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or DEVICE.fullmatch(part.split(".", 1)[0])):
            raise ValueError(f"Unsafe Windows payload path: {name!r}")
    return name


def namespace(paths: dict[str, bool]) -> None:
    """Reject aliases, duplicate names and file/directory prefix conflicts."""
    seen: dict[str, tuple[str, bool]] = {}
    for name, is_directory in sorted(paths.items()):
        safe_name(name)
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            component = "/".join(parts[:index])
            key = unicodedata.normalize("NFC", component).casefold()
            directory = index < len(parts) or is_directory
            previous = seen.get(key)
            if previous and (previous[0] != component or previous[1] != directory):
                raise ValueError(f"Conflicting Windows payload paths: {previous[0]!r}, {component!r}")
            seen[key] = (component, directory)


def regular_bytes(path: Path, limit: int = MAX_FILE_SIZE) -> bytes:
    real_ancestors(path.parent)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Source must be a single-link regular file: {path}")
    if info.st_size > limit:
        raise ValueError(f"Source file exceeds size limit: {path}")
    # O_NOFOLLOW plus identity comparison also rejects replacement with a link on POSIX.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_nlink, opened.st_size) != (
            info.st_dev, info.st_ino, 1, info.st_size
        ):
            raise ValueError(f"Source changed while opening: {path}")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(data) != info.st_size or len(data) > limit or (
        opened.st_mtime_ns, opened.st_ctime_ns
    ) != (after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError(f"Source changed while reading: {path}")
    return data


def real_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Expected a real directory, not a link or special file: {path}")


def real_ancestors(path: Path) -> None:
    for parent in reversed((path, *path.parents)):
        if parent.exists() or parent.is_symlink():
            real_directory(parent)


def installer_allowlist(source: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tree = ast.parse(regular_bytes(source / "lib/install_workflow.py"), filename="install_workflow.py")
    constants: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"PACK_FILES", "PACK_DIRECTORIES"}:
                if target.id in constants:
                    raise ValueError(f"Duplicate installer constant: {target.id}")
                value = ast.literal_eval(node.value)
                if not isinstance(value, tuple) or not value or not all(isinstance(x, str) for x in value):
                    raise ValueError(f"Installer allowlist must be a literal tuple: {target.id}")
                for name in value:
                    safe_name(name)
                    if "/" in name or name in {"manager", "tests", "npm", "packaging", "docs"}:
                        raise ValueError(f"Installer allowlist includes unsupported entry: {name}")
                constants[target.id] = value
    if set(constants) != {"PACK_FILES", "PACK_DIRECTORIES"}:
        raise ValueError("Installer must declare literal PACK_FILES and PACK_DIRECTORIES")
    names = constants["PACK_FILES"] + constants["PACK_DIRECTORIES"]
    if len(set(names)) != len(names) or not {"lib", "scripts"}.issubset(constants["PACK_DIRECTORIES"]):
        raise ValueError("Installer allowlist has duplicates or lacks lib/scripts")
    return constants["PACK_FILES"], constants["PACK_DIRECTORIES"]


def payload(source: Path) -> dict[str, bytes]:
    files, directories = installer_allowlist(source)
    result: dict[str, bytes] = {}
    entries: dict[str, bool] = {}

    def visit(path: Path) -> None:
        relative = path.relative_to(source).as_posix()
        if (EXCLUDED.intersection(PurePosixPath(relative).parts)
                or path.suffix in {".pyc", ".pyo", ".bak", ".backup", ".orig", ".rej", ".tmp"}
                or path.name.endswith("~") or path.name.startswith("test_")):
            return
        if relative.startswith("scripts/") and relative not in {f"scripts/{name}" for name in SCRIPTS}:
            return
        info = path.lstat()
        safe_name(relative)
        if stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400:
            entries[relative] = True
            for child in sorted(path.iterdir()):
                visit(child)
        else:
            result[relative] = regular_bytes(path)
            entries[relative] = False

    for name in files:
        result[name] = regular_bytes(source / name)
        entries[name] = False
    for name in directories:
        real_directory(source / name)
        visit(source / name)
    if "lib/install_workflow.py" not in result:
        raise ValueError("Installer itself must be included in the npm payload")
    for name in SCRIPTS:
        if f"scripts/{name}" not in result:
            raise ValueError(f"Required runtime script is missing: {name}")
    namespace(entries)
    check_dependencies(result)
    return dict(sorted(result.items()))


def check_dependencies(files: dict[str, bytes], *, runtime: bool = False) -> None:
    """Fail closed on missing local imports or shell script references, without imports."""
    modules = {PurePosixPath(name).stem for name in files if name.endswith(".py")}
    for name, data in files.items():
        if name.endswith(".py"):
            tree = ast.parse(data, filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [alias.name.split(".", 1)[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = ([node.module.split(".", 1)[0]] if node.module else
                               [alias.name.split(".", 1)[0] for alias in node.names])
                else:
                    continue
                for module in imports:
                    if module not in modules and module not in sys.stdlib_module_names:
                        raise ValueError(f"Unbundled Python dependency in {name}: {module}")
        if not runtime and name.endswith((".py", ".sh")):
            text = data.decode("utf-8")
            for script in re.findall(r"\bscripts/([A-Za-z0-9_.-]+\.sh)\b", text):
                if f"scripts/{script}" not in files:
                    raise ValueError(f"Unbundled shell dependency in {name}: scripts/{script}")


def runtime_lock(source: Path) -> dict:
    lock = json.loads(regular_bytes(source / "packaging/windows/runtime.lock.json", 1024 * 1024))
    if not isinstance(lock, dict):
        raise ValueError("Invalid official CPython runtime lock")
    version = lock.get("version", "")
    archive = f"python-{version}-embed-amd64.zip"
    if (type(lock.get("schema_version")) is not int or lock["schema_version"] != 1
            or lock.get("implementation") != "CPython" or lock.get("architecture") != "x64"
            or not isinstance(version, str) or not re.fullmatch(r"3\.\d+\.\d+", version)
            or tuple(map(int, version.split("."))) < (3, 11, 0)
            or lock.get("archive") != archive
            or lock.get("url") != f"https://www.python.org/ftp/python/{version}/{archive}"
            or not isinstance(lock.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", lock["sha256"])
            or type(lock.get("size")) is not int or not 0 < lock["size"] <= MAX_ARCHIVE_SIZE
            or not isinstance(lock.get("license"), dict) or lock["license"].get("path") != "LICENSE.txt"
            or not isinstance(lock.get("provenance"), dict) or not lock["provenance"].get("method")):
        raise ValueError("Invalid official CPython runtime lock")
    return lock


def runtime_files(archive: Path, lock: dict) -> dict[str, bytes]:
    data = regular_bytes(archive, MAX_ARCHIVE_SIZE)
    if len(data) != lock["size"] or hashlib.sha256(data).hexdigest() != lock["sha256"]:
        raise ValueError("CPython archive does not match runtime.lock.json size/SHA-256")
    files: dict[str, bytes] = {}
    entries: dict[str, bool] = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as stream:
        members = stream.infolist()
        if not members or len(members) > MAX_FILES:
            raise ValueError("CPython ZIP has an invalid entry count")
        for entry in members:
            if entry.orig_filename != entry.filename:
                raise ValueError("CPython ZIP contains an embedded NUL")
            directory = entry.is_dir()
            name = entry.filename[:-1] if directory else entry.filename
            safe_name(name)
            if name in entries:
                raise ValueError(f"Duplicate ZIP entry: {name}")
            mode = stat.S_IFMT(entry.external_attr >> 16)
            expected = stat.S_IFDIR if directory else stat.S_IFREG
            if (mode not in {0, expected} or entry.external_attr & 0x440
                    or entry.flag_bits & 1 or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or entry.file_size < 0 or entry.file_size > MAX_FILE_SIZE
                    or (directory and entry.file_size)
                    or entry.file_size > max(1, entry.compress_size) * 1000):
                raise ValueError(f"Unsupported, linked, encrypted or oversized ZIP entry: {name}")
            entries[name] = directory
            total += entry.file_size
            if total > MAX_TOTAL_SIZE:
                raise ValueError("CPython ZIP exceeds total expanded size limit")
        namespace(entries)
        reserved = {"manifest.json", *RUNTIME_HELPERS}
        if any(name.casefold() in reserved for name in entries):
            raise ValueError("Archive conflicts with trusted runtime helpers or manifest")
        for entry in members:
            if not entry.is_dir():
                content = stream.read(entry)  # Also checks CRC and truncated data before any output exists.
                if len(content) != entry.file_size:
                    raise ValueError(f"Truncated ZIP entry: {entry.filename}")
                files[entry.filename] = content
    digits = "".join(lock["version"].split(".")[:2])
    required = {"python.exe", f"python{digits}.dll", f"python{digits}.zip", f"python{digits}._pth", "LICENSE.txt"}
    if not required.issubset(files):
        raise ValueError(f"CPython archive is missing required runtime files: {sorted(required - files.keys())}")
    pth_lines = [line.strip() for line in files[f"python{digits}._pth"].decode("utf-8-sig").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
    if pth_lines != [f"python{digits}.zip", "."]:
        raise ValueError("Unexpected embedded Python _pth; require isolated stdlib ZIP plus runtime root")
    return files


def prepare(source: Path, archive: Path, output: Path) -> Path:
    source = Path(os.path.abspath(source.expanduser()))
    archive = Path(os.path.abspath(archive.expanduser()))
    output = Path(os.path.abspath(output.expanduser()))
    real_ancestors(source)
    real_ancestors(archive.parent)
    real_ancestors(output.parent)
    if (output == source or source.is_relative_to(output) or output.is_relative_to(source)
            or archive == output or archive.is_relative_to(output)):
        raise ValueError("Output must be separate from the source tree and archive location")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Existing output preserved; choose a new --output directory: {output}")
    lock = runtime_lock(source)
    bundled = runtime_files(archive, lock)
    workflow = payload(source)
    helpers = {name: regular_bytes(source / "lib" / name) for name in RUNTIME_HELPERS}
    check_dependencies(helpers, runtime=True)
    bundled.update(helpers)
    namespace({name: False for name in bundled})
    manifest = {
        "schema_version": 1,
        "version": lock["version"],
        "architecture": "x64",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(bundled.items())},
    }
    bundled["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    startup = {name: regular_bytes(source / "npm" / name) for name in STARTUP_FILES}
    package = json.loads(startup["package.json"])
    if (not isinstance(package, dict) or package.get("name") != "@geoege-xll/agent-workflow" or package.get("version") != "0.1.0"
            or package.get("bin") != {"agent-workflow": "bin/agent-workflow.cjs"}
            or package.get("private") is not True or package.get("scripts")
            or any(package.get(field) for field in ("dependencies", "optionalDependencies", "devDependencies"))):
        raise ValueError("npm metadata must be local/unpublished with the single offline CJS bin and no lifecycle scripts/dependencies")
    prepared = {**startup, **{f"payload/{name}": data for name, data in workflow.items()},
                **{f"runtime/{name}": data for name, data in bundled.items()}}
    if len(prepared) > MAX_FILES or sum(map(len, prepared.values())) > MAX_TOTAL_SIZE:
        raise ValueError("Prepared package exceeds size/count limits")
    namespace({name: False for name in prepared})
    # All validation and untrusted ZIP reads have completed. Never reuse an existing directory.
    output.mkdir(mode=0o700)
    for name, data in sorted(prepared.items()):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        target.chmod(0o755 if name == "bin/agent-workflow.cjs" or target.suffix in {".sh", ".exe"} else 0o644)
        os.utime(target, (0, 0))
    for directory in sorted((p for p in output.rglob("*") if p.is_dir()), reverse=True):
        directory.chmod(0o755)
        os.utime(directory, (0, 0))
    os.utime(output, (0, 0))
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-archive", type=Path, required=True, help="local official ZIP matching runtime.lock.json")
    parser.add_argument("--output", type=Path, required=True, help="new prepared package directory, outside the source tree")
    args = parser.parse_args(argv)
    try:
        print(prepare(ROOT, args.runtime_archive, args.output))
        return 0
    except (OSError, ValueError, SyntaxError, zipfile.BadZipFile, zlib.error, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
