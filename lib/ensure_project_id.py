#!/usr/bin/env python3
"""Initialize the workflow pack's project-scoped memory identifier."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import sys
import unicodedata
from pathlib import Path


PROJECT_ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PLACEHOLDERS = {"replace-with-unique-project-id"}
MAX_CONFIG_SIZE = 1024 * 1024


class InitializationError(ValueError):
    """A controlled project-ID initialization failure."""


def derive_project_id(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    if not slug:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        slug = f"project-{digest}"
    if PROJECT_ID_RE.fullmatch(slug) is None:
        raise ValueError("derived project ID is not a lowercase slug")
    return slug


def _read_config(path: Path) -> tuple[bytes, os.stat_result]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise InitializationError(f"project.yaml must be a real regular file: {path}")
        if info.st_nlink != 1:
            raise InitializationError(f"project.yaml must not be a hard link: {path}")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 64 * 1024):
            size += len(chunk)
            if size > MAX_CONFIG_SIZE:
                raise InitializationError(f"project.yaml exceeds the size limit: {path}")
            chunks.append(chunk)
        return b"".join(chunks), info
    except OSError as exc:
        raise InitializationError(f"cannot securely read project.yaml {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _project_id_line(lines: list[str]) -> tuple[int, str]:
    memory_start: int | None = None
    memory_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line == line.lstrip() and re.fullmatch(r"memory:\s*(?:#.*)?(?:\r?\n)?", line):
            if memory_start is not None:
                raise InitializationError("project.yaml declares memory more than once")
            memory_start = index
            continue
        if memory_start is not None and index > memory_start and line == line.lstrip():
            memory_end = index
            break
    if memory_start is None:
        raise InitializationError("project.yaml is missing the memory mapping")

    matches: list[tuple[int, str]] = []
    for index in range(memory_start + 1, memory_end):
        match = re.fullmatch(r"\s+project_id:\s*(.*?)\s*(?:\r?\n)?", lines[index])
        if match:
            matches.append((index, match.group(1)))
    if len(matches) != 1:
        raise InitializationError(
            f"project.yaml memory mapping must contain exactly one project_id; found {len(matches)}"
        )
    return matches[0]


def _controlled_scalar(raw: str) -> str:
    value = raw.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def _replace_placeholder(body: bytes, project_id: str) -> bytes | None:
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InitializationError(f"project.yaml must be valid UTF-8: {exc}") from exc
    lines = text.splitlines(keepends=True)
    index, raw_value = _project_id_line(lines)
    if _controlled_scalar(raw_value) not in PLACEHOLDERS:
        return None
    newline = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
    prefix = lines[index].split("project_id:", 1)[0] + "project_id: "
    lines[index] = f"{prefix}{project_id}{newline}"
    return "".join(lines).encode("utf-8")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def initialize_project_id(config: Path, project_root: Path) -> str | None:
    root_info = project_root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise InitializationError(f"project root must be a real directory: {project_root}")
    original, original_info = _read_config(config)
    project_id = derive_project_id(project_root.name)
    replacement = _replace_placeholder(original, project_id)
    if replacement is None:
        return None

    temporary = config.parent / (
        f".{config.name}.agent-workflow-project-id-{secrets.token_hex(8)}.tmp"
    )
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        os.fchmod(descriptor, stat.S_IMODE(original_info.st_mode))
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(replacement)
            output.flush()
            os.fsync(output.fileno())
        current, current_info = _read_config(config)
        if current != original or (
            current_info.st_dev,
            current_info.st_ino,
            current_info.st_nlink,
        ) != (
            original_info.st_dev,
            original_info.st_ino,
            original_info.st_nlink,
        ):
            raise InitializationError("project.yaml changed during project ID initialization")
        os.replace(temporary, config)
        _fsync_directory(config.parent)
    except OSError as exc:
        raise InitializationError(f"cannot atomically initialize project.yaml: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            info = temporary.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                temporary.unlink()
    return project_id


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: ensure_project_id.py PROJECT_YAML PROJECT_ROOT", file=sys.stderr)
        return 2
    try:
        initialized = initialize_project_id(Path(sys.argv[1]), Path(sys.argv[2]))
    except (InitializationError, OSError, UnicodeError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    if initialized is not None:
        print(f"[OK] memory.project_id initialized to {initialized}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
