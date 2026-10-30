#!/usr/bin/env python3
"""Load and validate the shared core Skill manifest and its source directories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


MANAGED_SKILL_MARKER = "agent-workflow-pack:managed-skill"
MANAGED_STATE_MARKER = "agent-workflow-pack:managed-skill-state"
MANAGED_JOURNAL_MARKER = "agent-workflow-pack:managed-skill-transaction"
STATE_FILE = ".agent-workflow-pack-state.json"
JOURNAL_PREFIX = ".agent-workflow-pack-journal--"
STAGE_PREFIX = ".agent-workflow-pack-stage--"
BACKUP_PREFIX = ".agent-workflow-pack-backup--"
TOMBSTONE_PREFIX = ".agent-workflow-pack-tombstone--"
TEMP_PREFIX = ".agent-workflow-pack-temp--"
# 共享核心 Skill 通常使用 xy- 前缀；Grill Me 是既有用户入口名，因此仅为它保留
# 一个精确例外，避免把校验规则放宽成任意无前缀目录都可进入受管安装事务。
SKILL_NAME_RE = re.compile(r"^(?:xy-[a-z0-9]+(?:-[a-z0-9]+)*|grill-me)$")
TRANSACTION_NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
YAML_IMPLICIT_WORDS = {
    "false",
    "no",
    "null",
    "off",
    "on",
    "true",
    "yes",
    "~",
}


class SharedCoreSkillError(ValueError):
    """The shared core Skill manifest or source tree is invalid."""


@dataclass(frozen=True)
class SharedCoreSkillSnapshot:
    """One descriptor-anchored, immutable view of a complete Skill source tree."""

    name: str
    nodes: tuple[tuple[str, str], ...]
    files: tuple[tuple[str, bytes, int], ...]


DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_DIRECTORY", 0)
)
REGULAR_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


def _open_real_directory(path: Path, label: str) -> int:
    try:
        descriptor = os.open(path, DIRECTORY_OPEN_FLAGS)
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot securely open {label} as a real directory: {path}: {exc}"
        ) from exc
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise SharedCoreSkillError(f"{label} must be a real directory: {path}")
    return descriptor


def _open_real_directory_at(
    parent_descriptor: int,
    name: str,
    path: Path,
    label: str,
) -> int:
    try:
        descriptor = os.open(name, DIRECTORY_OPEN_FLAGS, dir_fd=parent_descriptor)
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot securely open {label} as a real directory: {path}: {exc}"
        ) from exc
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise SharedCoreSkillError(f"{label} must be a real directory: {path}")
    return descriptor


def _open_regular_at(
    parent_descriptor: int,
    name: str,
    path: Path,
    label: str,
) -> int:
    try:
        descriptor = os.open(name, REGULAR_OPEN_FLAGS, dir_fd=parent_descriptor)
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot securely open {label}: {path}: {exc}"
        ) from exc
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise SharedCoreSkillError(f"{label} must be a real regular file: {path}")
    if info.st_nlink != 1:
        os.close(descriptor)
        raise SharedCoreSkillError(f"hard link is forbidden for {label}: {path}")
    return descriptor


def _read_descriptor(descriptor: int, path: Path, label: str) -> bytes:
    chunks: list[bytes] = []
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
    except OSError as exc:
        raise SharedCoreSkillError(f"cannot read {label} {path}: {exc}") from exc
    return b"".join(chunks)


def _read_regular_at(
    parent_descriptor: int,
    name: str,
    path: Path,
    label: str,
) -> bytes:
    descriptor = _open_regular_at(parent_descriptor, name, path, label)
    try:
        return _read_descriptor(descriptor, path, label)
    finally:
        os.close(descriptor)


def _read_regular_path(path: Path, label: str) -> bytes:
    try:
        descriptor = os.open(path, REGULAR_OPEN_FLAGS)
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot securely open {label}: {path}: {exc}"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SharedCoreSkillError(f"{label} must be a real regular file: {path}")
        if info.st_nlink != 1:
            raise SharedCoreSkillError(f"hard link is forbidden for {label}: {path}")
        return _read_descriptor(descriptor, path, label)
    finally:
        os.close(descriptor)


def _lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise SharedCoreSkillError(f"cannot inspect shared core Skill path: {path}: {exc}") from exc


def _require_regular_file(path: Path, label: str) -> os.stat_result:
    info = _lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise SharedCoreSkillError(f"{label} must be a real regular file: {path}")
    if info.st_nlink != 1:
        raise SharedCoreSkillError(f"hard link is forbidden for {label}: {path}")
    return info


def _require_real_directory(path: Path, label: str) -> None:
    mode = _lstat(path).st_mode
    if not stat.S_ISDIR(mode):
        raise SharedCoreSkillError(f"{label} must be a real directory: {path}")


def _controlled_scalar(raw: str, *, field: str, skill: str) -> str:
    value = raw.strip()
    if not value:
        raise SharedCoreSkillError(f"{field} must not be empty for {skill}")
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SharedCoreSkillError(
                f"invalid quoted {field} scalar for {skill}"
            ) from exc
        if not isinstance(parsed, str) or not parsed.strip():
            raise SharedCoreSkillError(f"{field} must be a non-empty string for {skill}")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise SharedCoreSkillError(f"invalid quoted {field} scalar for {skill}")
        inner = value[1:-1]
        parsed_parts: list[str] = []
        index = 0
        while index < len(inner):
            if inner[index] != "'":
                parsed_parts.append(inner[index])
                index += 1
                continue
            if index + 1 >= len(inner) or inner[index + 1] != "'":
                raise SharedCoreSkillError(
                    f"invalid quoted {field} scalar for {skill}"
                )
            parsed_parts.append("'")
            index += 2
        parsed = "".join(parsed_parts)
        if not parsed.strip():
            raise SharedCoreSkillError(f"{field} must be a non-empty string for {skill}")
        return parsed
    if value[0] in "-?:,[]{}#&*!|>'%@`" or re.search(r":\s|\s#", value):
        raise SharedCoreSkillError(f"unsafe plain {field} scalar for {skill}")
    if field == "description" and (
        value.casefold() in YAML_IMPLICIT_WORDS
        or not re.match(r"[A-Za-z]", value)
    ):
        raise SharedCoreSkillError(
            f"plain description must begin with an ASCII letter for {skill}; "
            "quote values that resemble YAML implicit types"
        )
    return value


def parse_managed_skill_text(
    body: str,
    expected_name: str,
    label: str = "Skill source",
) -> dict[str, str]:
    """Parse an already-secured managed Skill body.

    Callers that enforce stronger path or descriptor policy can reuse the exact
    controlled frontmatter/marker grammar without reopening the path.
    """

    lines = body.splitlines()
    if not lines or lines[0] != "---":
        raise SharedCoreSkillError(
            f"missing opening frontmatter delimiter for {expected_name} in {label}"
        )
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise SharedCoreSkillError(
            f"missing closing frontmatter delimiter for {expected_name} in {label}"
        ) from exc

    metadata: dict[str, str] = {}
    for raw in lines[1:closing]:
        match = re.fullmatch(r"([a-z][a-z0-9_-]*):[ \t]*(.*)", raw)
        if not match:
            raise SharedCoreSkillError(
                f"invalid frontmatter line for {expected_name}: {raw}"
            )
        key, scalar = match.groups()
        if key in metadata:
            raise SharedCoreSkillError(
                f"duplicate frontmatter key for {expected_name}: {key}"
            )
        metadata[key] = _controlled_scalar(
            scalar,
            field=key,
            skill=expected_name,
        )
    if set(metadata) != {"name", "description"}:
        unsupported = sorted(set(metadata) - {"name", "description"})
        if unsupported:
            raise SharedCoreSkillError(
                f"unsupported frontmatter key for {expected_name}: {unsupported[0]}"
            )
        missing = sorted({"name", "description"} - set(metadata))
        raise SharedCoreSkillError(
            f"missing frontmatter key for {expected_name}: {missing[0]}"
        )
    if metadata["name"] != expected_name:
        raise SharedCoreSkillError(f"skill name mismatch for {expected_name}")
    if sum(line == f"<!-- {MANAGED_SKILL_MARKER} -->" for line in lines) != 1:
        raise SharedCoreSkillError(f"managed marker missing for {expected_name}")
    return metadata


def parse_managed_skill_bytes(
    body: bytes,
    expected_name: str,
    label: str = "Skill source",
) -> dict[str, str]:
    try:
        decoded = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SharedCoreSkillError(f"{label} is not valid UTF-8: {exc}") from exc
    return parse_managed_skill_text(decoded, expected_name, label)


def parse_managed_skill(path: Path, expected_name: str) -> dict[str, str]:
    body = _read_regular_path(path, "Skill source")
    return parse_managed_skill_bytes(body, expected_name, str(path))


def is_pack_managed_skill(path: Path, expected_name: str) -> bool:
    try:
        parse_managed_skill(path, expected_name)
    except (OSError, UnicodeError, SharedCoreSkillError):
        return False
    return True


def _scan_tree(path: Path, label: str) -> dict[Path, str]:
    _require_real_directory(path, label)
    nodes: dict[Path, str] = {}

    def visit(directory: Path, prefix: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise SharedCoreSkillError(
                f"cannot inspect {label}: {directory}: {exc}"
            ) from exc
        for entry in entries:
            node = Path(entry.path)
            relative = prefix / entry.name
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SharedCoreSkillError(
                    f"cannot inspect {label}: {node}: {exc}"
                ) from exc
            if stat.S_ISLNK(info.st_mode):
                raise SharedCoreSkillError(f"symlink is forbidden in {label}: {node}")
            if stat.S_ISDIR(info.st_mode):
                nodes[relative] = "directory"
                visit(node, relative)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise SharedCoreSkillError(
                        f"hard link is forbidden in {label}: {node}"
                    )
                nodes[relative] = "file"
            else:
                raise SharedCoreSkillError(
                    f"special file is forbidden in {label}; expected a regular file "
                    f"or directory: {node}"
                )

    visit(path, Path())
    return nodes


def _validated_source_tree_descriptor(
    descriptor: int,
    path: Path,
    skill: str,
    captured_files: dict[Path, tuple[bytes, int]] | None = None,
) -> dict[Path, str]:
    label = f"shared core Skill source {skill}"
    nodes: dict[Path, str] = {}
    skill_body: bytes | None = None
    # 引用正文从同一批已打开的安全描述符捕获，既检查缺失引用，也不在校验后
    # 再通过路径重读可能被替换的文件。未被入口引用的辅助文件不参与语义展开。
    contract_details: dict[str, bytes] = {}

    def visit(directory_descriptor: int, prefix: Path) -> None:
        nonlocal skill_body
        try:
            with os.scandir(directory_descriptor) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise SharedCoreSkillError(f"cannot inspect {label}: {path}: {exc}") from exc

        for entry in entries:
            relative = prefix / entry.name
            node = path / relative
            canonical = _inventory_path(relative.as_posix(), skill=skill)
            if canonical != relative:
                raise SharedCoreSkillError(
                    f"non-canonical shared core Skill path for {skill}: {relative}"
                )
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SharedCoreSkillError(
                    f"cannot inspect {label}: {node}: {exc}"
                ) from exc
            if stat.S_ISLNK(info.st_mode):
                raise SharedCoreSkillError(f"symlink is forbidden in {label}: {node}")
            if stat.S_ISDIR(info.st_mode):
                child_descriptor = _open_real_directory_at(
                    directory_descriptor,
                    entry.name,
                    node,
                    label,
                )
                nodes[relative] = "directory"
                try:
                    visit(child_descriptor, relative)
                finally:
                    os.close(child_descriptor)
                continue
            if stat.S_ISREG(info.st_mode):
                file_descriptor = _open_regular_at(
                    directory_descriptor,
                    entry.name,
                    node,
                    label,
                )
                nodes[relative] = "file"
                try:
                    is_reference = relative.parts[0] == "references" and relative.suffix == ".md"
                    if relative == Path("SKILL.md") or captured_files is not None or is_reference:
                        body = _read_descriptor(file_descriptor, node, label)
                        if relative == Path("SKILL.md"):
                            skill_body = body
                        if is_reference:
                            contract_details[relative.as_posix()] = body
                        if captured_files is not None:
                            file_info = os.fstat(file_descriptor)
                            captured_files[relative] = (
                                body,
                                stat.S_IMODE(file_info.st_mode) & 0o777,
                            )
                finally:
                    os.close(file_descriptor)
                continue
            raise SharedCoreSkillError(f"special file is forbidden in {label}: {node}")

    visit(descriptor, Path())
    if skill_body is None:
        raise SharedCoreSkillError(f"missing Skill source for {skill}: {path / 'SKILL.md'}")
    parse_managed_skill_bytes(skill_body, skill, str(path / "SKILL.md"))
    if __package__:
        from .skill_contracts import expand_skill_contract
    else:
        from skill_contracts import expand_skill_contract
    try:
        expand_skill_contract(
            skill_body.decode("utf-8"),
            lambda reference: contract_details[reference].decode("utf-8"),
        )
    except (KeyError, UnicodeError, ValueError) as exc:
        raise SharedCoreSkillError(f"invalid progressive Skill contract for {skill}: {exc}") from exc
    for relative in nodes:
        if _inventory_path(relative.as_posix(), skill=skill) != relative:
            raise SharedCoreSkillError(
                f"non-canonical shared core Skill path for {skill}: {relative}"
            )
    return nodes


def _validated_source_tree(path: Path, skill: str) -> dict[Path, str]:
    descriptor = _open_real_directory(
        path,
        f"shared core Skill source {skill}",
    )
    try:
        return _validated_source_tree_descriptor(descriptor, path, skill)
    finally:
        os.close(descriptor)


def _path_exists_without_following(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise SharedCoreSkillError(f"cannot inspect Skill target {path}: {exc}") from exc
    return True


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SharedCoreSkillError(
                f"managed Skill file must be a single-link regular file: {path}"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SharedCoreSkillError(f"cannot hash managed Skill file {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError as exc:
        raise SharedCoreSkillError(f"cannot fsync managed Skill directory {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_transaction_nonce(nonce: object, skill: str) -> str:
    if not isinstance(nonce, str) or not TRANSACTION_NONCE_RE.fullmatch(nonce):
        raise SharedCoreSkillError(
            f"invalid managed Skill transaction nonce for {skill}"
        )
    return nonce


def _managed_temp_relative(relative: Path, nonce: str, kind: str) -> Path:
    if kind not in {"copy", "journal", "state"}:
        raise SharedCoreSkillError(f"invalid managed Skill temporary kind: {kind}")
    if not TRANSACTION_NONCE_RE.fullmatch(nonce):
        raise SharedCoreSkillError("invalid managed Skill temporary nonce")
    identity = f"{kind}\0{relative.as_posix()}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    name = f"{TEMP_PREFIX}{kind}--{nonce}--{digest}"
    return relative.parent / name


def _open_atomic_temporary(path: Path, mode: int) -> int:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, mode)
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot create managed Skill temporary file {path}: {exc}"
        ) from exc
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(descriptor)
        raise SharedCoreSkillError(
            f"managed Skill temporary file is not single-link: {path}"
        )
    return descriptor


def _atomic_copy_file(source: Path, target: Path, temporary: Path) -> None:
    source_descriptor = -1
    target_descriptor = -1
    temporary_exists = False
    try:
        if temporary.parent != target.parent:
            raise SharedCoreSkillError(
                f"managed Skill copy temporary is outside target directory: {temporary}"
            )
        source_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        source_descriptor = os.open(source, source_flags)
        source_info = os.fstat(source_descriptor)
        if not stat.S_ISREG(source_info.st_mode) or source_info.st_nlink != 1:
            raise SharedCoreSkillError(
                f"copy source must be a single-link regular file: {source}"
            )
        target_descriptor = _open_atomic_temporary(temporary, 0o600)
        temporary_exists = True
        os.fchmod(target_descriptor, stat.S_IMODE(source_info.st_mode) & 0o777)
        if (
            os.environ.get("AGENT_WORKFLOW_PACK_TEST_FAILPOINT")
            == "update-after-copy-temp-created"
        ):
            _fsync_directory(target.parent)
            os._exit(97)
        with os.fdopen(source_descriptor, "rb") as source_file:
            source_descriptor = -1
            with os.fdopen(target_descriptor, "wb") as target_file:
                target_descriptor = -1
                shutil.copyfileobj(source_file, target_file, 1024 * 1024)
                target_file.flush()
                os.fsync(target_file.fileno())
                temporary_info = os.fstat(target_file.fileno())
                source_after = os.fstat(source_file.fileno())
                if not stat.S_ISREG(temporary_info.st_mode) or temporary_info.st_nlink != 1:
                    raise SharedCoreSkillError(
                        f"temporary managed Skill file is not single-link: {temporary}"
                    )
                if (
                    not stat.S_ISREG(source_after.st_mode)
                    or source_after.st_nlink != 1
                    or source_after.st_dev != source_info.st_dev
                    or source_after.st_ino != source_info.st_ino
                ):
                    raise SharedCoreSkillError(
                        f"copy source changed during managed Skill synchronization: {source}"
                    )
        os.replace(temporary, target)
        temporary_exists = False
        _fsync_directory(target.parent)
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot atomically copy managed Skill file {source} to {target}: {exc}"
        ) from exc
    finally:
        if source_descriptor >= 0:
            os.close(source_descriptor)
        if target_descriptor >= 0:
            os.close(target_descriptor)
        if temporary_exists and _path_exists_without_following(temporary):
            temporary.unlink()


def _atomic_write_bytes(
    target: Path,
    body: bytes,
    temporary: Path,
    mode: int = 0o644,
) -> None:
    descriptor = -1
    temporary_exists = False
    try:
        if temporary.parent != target.parent:
            raise SharedCoreSkillError(
                f"managed Skill state temporary is outside target directory: {temporary}"
            )
        descriptor = _open_atomic_temporary(temporary, 0o600)
        temporary_exists = True
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
            info = os.fstat(output.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SharedCoreSkillError(
                    f"temporary managed Skill state is not single-link: {temporary}"
                )
        os.replace(temporary, target)
        temporary_exists = False
        _fsync_directory(target.parent)
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot atomically write managed Skill state {target}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_exists and _path_exists_without_following(temporary):
            temporary.unlink()


def _inventory_path(raw: object, *, skill: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise SharedCoreSkillError(f"invalid managed Skill inventory path for {skill}")
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute()
        or pure.as_posix() != raw
        or not pure.parts
        or "\\" in raw
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(part == STATE_FILE for part in pure.parts)
        or any(part.startswith(TEMP_PREFIX) for part in pure.parts)
        or any(part != part.strip() for part in pure.parts)
        or raw != unicodedata.normalize("NFC", raw)
        or any(
            unicodedata.category(character).startswith("C")
            for character in raw
        )
    ):
        raise SharedCoreSkillError(
            f"unsafe managed Skill inventory path for {skill}: {raw}"
        )
    return Path(*pure.parts)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SharedCoreSkillError(f"duplicate managed Skill state key: {key}")
        result[key] = value
    return result


def _source_inventory(
    source: Path,
    nodes: dict[Path, str],
    skill: str,
) -> dict[str, object]:
    directories = sorted(
        _inventory_path(relative.as_posix(), skill=skill).as_posix()
        for relative, node_type in nodes.items()
        if node_type == "directory"
    )
    files = {
        _inventory_path(relative.as_posix(), skill=skill).as_posix():
        _file_sha256(source / relative)
        for relative, node_type in sorted(nodes.items(), key=lambda item: str(item[0]))
        if node_type == "file"
    }
    return {
        "marker": MANAGED_STATE_MARKER,
        "version": 1,
        "skill": skill,
        "directories": directories,
        "files": files,
    }


def _validate_inventory_object(
    state: object,
    skill: str,
) -> tuple[dict[str, object], dict[Path, str]]:
    if not isinstance(state, dict) or set(state) != {
        "marker",
        "version",
        "skill",
        "directories",
        "files",
    }:
        raise SharedCoreSkillError(f"invalid managed Skill state schema for {skill}")
    if state["marker"] != MANAGED_STATE_MARKER:
        raise SharedCoreSkillError(f"invalid managed Skill state marker for {skill}")
    if type(state["version"]) is not int or state["version"] != 1:
        raise SharedCoreSkillError(f"unsupported managed Skill state version for {skill}")
    if state["skill"] != skill:
        raise SharedCoreSkillError(f"managed Skill state name mismatch for {skill}")
    directories = state["directories"]
    files = state["files"]
    if not isinstance(directories, list) or not isinstance(files, dict):
        raise SharedCoreSkillError(f"invalid managed Skill state inventory for {skill}")

    nodes: dict[Path, str] = {}
    for raw in directories:
        relative = _inventory_path(raw, skill=skill)
        if relative in nodes:
            raise SharedCoreSkillError(
                f"duplicate managed Skill inventory path for {skill}: {relative}"
            )
        nodes[relative] = "directory"
    for raw, digest in files.items():
        relative = _inventory_path(raw, skill=skill)
        if relative in nodes:
            raise SharedCoreSkillError(
                f"conflicting managed Skill inventory path for {skill}: {relative}"
            )
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SharedCoreSkillError(
                f"invalid managed Skill inventory hash for {skill}: {raw}"
            )
        nodes[relative] = "file"
    if nodes.get(Path("SKILL.md")) != "file":
        raise SharedCoreSkillError(f"managed Skill state omits SKILL.md for {skill}")
    for relative in nodes:
        parent = relative.parent
        while parent != Path("."):
            if nodes.get(parent) != "directory":
                raise SharedCoreSkillError(
                    f"managed Skill state omits parent directory for {skill}: {parent}"
                )
            parent = parent.parent
    return state, nodes


def _read_inventory(path: Path, skill: str) -> tuple[dict[str, object], dict[Path, str]]:
    _require_regular_file(path, "Managed Skill state")
    try:
        state = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise SharedCoreSkillError(f"invalid managed Skill state for {skill}: {exc}") from exc
    return _validate_inventory_object(state, skill)


def _validated_installed_tree(
    target: Path,
    skill: str,
) -> tuple[dict[Path, str], dict[str, object]]:
    target_nodes = _scan_tree(target, f"generated Skill target {skill}")
    if not is_pack_managed_skill(target / "SKILL.md", skill):
        raise SharedCoreSkillError(
            f"generated Skill target is not pack-managed: {target / 'SKILL.md'}"
        )
    state_path = target / STATE_FILE
    if Path(STATE_FILE) not in target_nodes:
        raise SharedCoreSkillError(
            f"generated Skill target has no managed state: {target}"
        )

    state, inventory_nodes = _read_inventory(state_path, skill)
    expected_nodes = dict(inventory_nodes)
    expected_nodes[Path(STATE_FILE)] = "file"
    missing = sorted(expected_nodes.keys() - target_nodes.keys(), key=str)
    if missing:
        raise SharedCoreSkillError(
            f"generated Skill target is missing managed content: {target / missing[0]}"
        )
    extra = sorted(target_nodes.keys() - expected_nodes.keys(), key=str)
    if extra:
        raise SharedCoreSkillError(
            f"generated Skill target contains untracked user content: {target / extra[0]}"
        )
    for relative, expected_type in expected_nodes.items():
        if target_nodes[relative] != expected_type:
            raise SharedCoreSkillError(
                f"generated Skill target type conflicts with managed state: "
                f"{target / relative}"
            )
    state_files = state["files"]
    assert isinstance(state_files, dict)
    for relative, node_type in inventory_nodes.items():
        if node_type != "file":
            continue
        expected_hash = state_files[relative.as_posix()]
        if _file_sha256(target / relative) != expected_hash:
            raise SharedCoreSkillError(
                f"generated Skill target was modified after generation: {target / relative}"
            )
    return inventory_nodes, state


def _artifact_paths(root: Path, skill: str) -> dict[str, Path]:
    return {
        "journal": root / f"{JOURNAL_PREFIX}{skill}.json",
        "stage": root / f"{STAGE_PREFIX}{skill}",
        "backup": root / f"{BACKUP_PREFIX}{skill}",
        "tombstone": root / f"{TOMBSTONE_PREFIX}{skill}",
    }


def _transaction_body(
    operation: str,
    skill: str,
    nonce: str,
    old_inventory: dict[str, object] | None,
    new_inventory: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "marker": MANAGED_JOURNAL_MARKER,
        "version": 3,
        "operation": operation,
        "skill": skill,
        "nonce": nonce,
        "old_inventory": old_inventory,
        "new_inventory": new_inventory,
    }


def _validate_transaction_object(
    transaction: object,
    expected_skill: str,
) -> dict[str, object]:
    if not isinstance(transaction, dict) or set(transaction) != {
        "marker",
        "version",
        "operation",
        "skill",
        "nonce",
        "old_inventory",
        "new_inventory",
    }:
        raise SharedCoreSkillError(
            f"invalid managed Skill transaction schema for {expected_skill}"
        )
    if transaction["marker"] != MANAGED_JOURNAL_MARKER:
        raise SharedCoreSkillError(
            f"invalid managed Skill transaction marker for {expected_skill}"
        )
    if type(transaction["version"]) is not int or transaction["version"] != 3:
        raise SharedCoreSkillError(
            f"unsupported managed Skill transaction version for {expected_skill}"
        )
    if transaction["skill"] != expected_skill:
        raise SharedCoreSkillError(
            f"managed Skill transaction name mismatch for {expected_skill}"
        )
    _validate_transaction_nonce(transaction["nonce"], expected_skill)
    operation = transaction["operation"]
    old_inventory = transaction["old_inventory"]
    new_inventory = transaction["new_inventory"]
    if old_inventory is not None:
        _validate_inventory_object(old_inventory, expected_skill)
    if operation == "update":
        if new_inventory is None:
            raise SharedCoreSkillError(
                f"update transaction omits new inventory for {expected_skill}"
            )
        _validate_inventory_object(new_inventory, expected_skill)
    elif operation == "stale":
        if old_inventory is None or new_inventory is not None:
            raise SharedCoreSkillError(
                f"invalid stale transaction inventory for {expected_skill}"
            )
    else:
        raise SharedCoreSkillError(
            f"invalid managed Skill transaction operation for {expected_skill}"
        )
    return transaction


def _read_transaction(path: Path, expected_skill: str) -> dict[str, object]:
    _require_regular_file(path, "Managed Skill transaction")
    try:
        transaction = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise SharedCoreSkillError(
            f"invalid managed Skill transaction for {expected_skill}: {exc}"
        ) from exc
    return _validate_transaction_object(transaction, expected_skill)


def _write_json_atomically(
    path: Path,
    value: dict[str, object],
    temporary: Path,
) -> None:
    body = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_write_bytes(path, body, temporary)


def _validate_tree_against_inventory(
    target: Path,
    skill: str,
    inventory: dict[str, object],
) -> None:
    _nodes, state = _validated_installed_tree(target, skill)
    if state != inventory:
        raise SharedCoreSkillError(
            f"managed Skill tree differs from transaction inventory: {target}"
        )


def _validate_partial_tree(
    target: Path,
    skill: str,
    inventory: dict[str, object],
    nonce: str | None = None,
) -> dict[Path, str]:
    _, inventory_nodes = _validate_inventory_object(inventory, skill)
    actual_nodes = _scan_tree(target, f"partial managed Skill transaction {skill}")
    expected_nodes = dict(inventory_nodes)
    expected_nodes[Path(STATE_FILE)] = "file"
    allowed_temporaries: dict[Path, str] = {}
    if nonce is not None:
        _validate_transaction_nonce(nonce, skill)
        for relative, node_type in inventory_nodes.items():
            if node_type == "file":
                allowed_temporaries[
                    _managed_temp_relative(relative, nonce, "copy")
                ] = "file"
        allowed_temporaries[
            _managed_temp_relative(Path(STATE_FILE), nonce, "state")
        ] = "file"
    extra = sorted(actual_nodes.keys() - expected_nodes.keys(), key=str)
    extra = [relative for relative in extra if relative not in allowed_temporaries]
    if extra:
        raise SharedCoreSkillError(
            f"partial managed Skill transaction contains unknown content: "
            f"{target / extra[0]}"
        )
    inventory_files = inventory["files"]
    assert isinstance(inventory_files, dict)
    for relative, actual_type in actual_nodes.items():
        if relative in allowed_temporaries:
            if actual_type != "file":
                raise SharedCoreSkillError(
                    f"partial managed Skill transaction temporary type mismatch: "
                    f"{target / relative}"
                )
            continue
        if expected_nodes[relative] != actual_type:
            raise SharedCoreSkillError(
                f"partial managed Skill transaction type mismatch: {target / relative}"
            )
        if actual_type != "file":
            continue
        if relative == Path(STATE_FILE):
            state, _ = _read_inventory(target / relative, skill)
            if state != inventory:
                raise SharedCoreSkillError(
                    f"partial managed Skill transaction has wrong state: {target}"
                )
            continue
        expected_hash = inventory_files[relative.as_posix()]
        if _file_sha256(target / relative) != expected_hash:
            raise SharedCoreSkillError(
                f"partial managed Skill transaction file changed: {target / relative}"
            )
    return actual_nodes


def _remove_partial_tree(
    target: Path,
    skill: str,
    inventory: dict[str, object],
    nonce: str | None = None,
) -> None:
    nodes = _validate_partial_tree(target, skill, inventory, nonce)
    for relative, node_type in sorted(
        nodes.items(), key=lambda item: (-len(item[0].parts), str(item[0]))
    ):
        if node_type == "file":
            (target / relative).unlink()
    for relative, node_type in sorted(
        nodes.items(), key=lambda item: (-len(item[0].parts), str(item[0]))
    ):
        if node_type == "directory":
            (target / relative).rmdir()
    target.rmdir()


def _unlink_transaction(path: Path) -> None:
    _require_regular_file(path, "Managed Skill transaction")
    path.unlink()
    _fsync_directory(path.parent)


def validate_target_skill_tree_for_update(
    source: Path,
    target: Path,
    skill: str,
) -> dict[Path, str]:
    source_nodes = _validated_source_tree(source, skill)
    if not _path_exists_without_following(target):
        return source_nodes
    _validated_installed_tree(target, skill)
    return source_nodes


def sync_skill_tree(source: Path, target: Path, skill: str) -> None:
    source_nodes = _validated_source_tree(source, skill)
    new_inventory = _source_inventory(source, source_nodes, skill)
    old_inventory: dict[str, object] | None = None
    if _path_exists_without_following(target):
        _old_nodes, old_inventory = _validated_installed_tree(target, skill)
        if old_inventory == new_inventory:
            return

    root = target.parent
    paths = _artifact_paths(root, skill)
    for artifact in paths.values():
        if _path_exists_without_following(artifact):
            raise SharedCoreSkillError(
                f"managed Skill transaction artifact already exists: {artifact}"
            )
    nonce = secrets.token_hex(16)
    transaction = _transaction_body(
        "update",
        skill,
        nonce,
        old_inventory,
        new_inventory,
    )
    journal_relative = paths["journal"].relative_to(root)
    _write_json_atomically(
        paths["journal"],
        transaction,
        root / _managed_temp_relative(journal_relative, nonce, "journal"),
    )
    paths["stage"].mkdir()
    _fsync_directory(root)

    for relative, node_type in sorted(
        source_nodes.items(),
        key=lambda item: (len(item[0].parts), str(item[0])),
    ):
        if node_type == "directory":
            (paths["stage"] / relative).mkdir(exist_ok=True)
    files = [relative for relative, kind in source_nodes.items() if kind == "file"]
    files.sort(key=lambda relative: (relative != Path("SKILL.md"), str(relative)))
    for index, relative in enumerate(files):
        _require_regular_file(source / relative, "Shared core Skill source file")
        _atomic_copy_file(
            source / relative,
            paths["stage"] / relative,
            paths["stage"] / _managed_temp_relative(relative, nonce, "copy"),
        )
        if (
            index == 0
            and os.environ.get("AGENT_WORKFLOW_PACK_TEST_FAILPOINT")
            == "update-after-first-stage-file"
        ):
            raise SharedCoreSkillError("injected update transaction interruption")
    _write_json_atomically(
        paths["stage"] / STATE_FILE,
        new_inventory,
        paths["stage"]
        / _managed_temp_relative(Path(STATE_FILE), nonce, "state"),
    )
    _validate_tree_against_inventory(paths["stage"], skill, new_inventory)
    if old_inventory is not None:
        _validate_tree_against_inventory(target, skill, old_inventory)
        os.replace(target, paths["backup"])
        _fsync_directory(root)
    os.replace(paths["stage"], target)
    _fsync_directory(root)
    if old_inventory is not None:
        _remove_partial_tree(paths["backup"], skill, old_inventory)
    _unlink_transaction(paths["journal"])


def compare_skill_trees(source: Path, target: Path, skill: str) -> None:
    source_nodes = _validated_source_tree(source, skill)
    _, installed_state = _validated_installed_tree(target, skill)
    if installed_state != _source_inventory(source, source_nodes, skill):
        raise SharedCoreSkillError(
            f"generated Skill target inventory differs from source: {target}"
        )


def validate_stale_managed_skill_directory(path: Path, expected_name: str) -> None:
    _validated_installed_tree(path, expected_name)


def remove_installed_skill_tree(path: Path, expected_name: str) -> None:
    nodes, _state = _validated_installed_tree(path, expected_name)
    for relative, node_type in sorted(
        nodes.items(), key=lambda item: (-len(item[0].parts), str(item[0]))
    ):
        if node_type == "file":
            (path / relative).unlink()
    (path / STATE_FILE).unlink()
    for relative, node_type in sorted(
        nodes.items(), key=lambda item: (-len(item[0].parts), str(item[0]))
    ):
        if node_type == "directory":
            (path / relative).rmdir()
    path.rmdir()


def remove_stale_skill_tree_transactionally(path: Path, expected_name: str) -> None:
    _nodes, inventory = _validated_installed_tree(path, expected_name)
    root = path.parent
    paths = _artifact_paths(root, expected_name)
    for artifact in paths.values():
        if _path_exists_without_following(artifact):
            raise SharedCoreSkillError(
                f"managed stale transaction artifact already exists: {artifact}"
            )
    transaction = _transaction_body(
        "stale",
        expected_name,
        secrets.token_hex(16),
        inventory,
        None,
    )
    nonce = transaction["nonce"]
    assert isinstance(nonce, str)
    journal_relative = paths["journal"].relative_to(root)
    _write_json_atomically(
        paths["journal"],
        transaction,
        root / _managed_temp_relative(journal_relative, nonce, "journal"),
    )
    _validate_tree_against_inventory(path, expected_name, inventory)
    os.replace(path, paths["tombstone"])
    _fsync_directory(root)
    if (
        os.environ.get("AGENT_WORKFLOW_PACK_TEST_FAILPOINT")
        == "stale-after-rename"
    ):
        raise SharedCoreSkillError("injected stale transaction interruption")
    _remove_partial_tree(paths["tombstone"], expected_name, inventory)
    _unlink_transaction(paths["journal"])


def _tree_matches_inventory(
    path: Path,
    skill: str,
    inventory: dict[str, object],
) -> bool:
    try:
        _validate_tree_against_inventory(path, skill, inventory)
    except SharedCoreSkillError:
        return False
    return True


def _recover_update_transaction(
    root: Path,
    skill: str,
    transaction: dict[str, object],
) -> None:
    paths = _artifact_paths(root, skill)
    old_inventory = transaction["old_inventory"]
    new_inventory = transaction["new_inventory"]
    nonce = transaction["nonce"]
    assert old_inventory is None or isinstance(old_inventory, dict)
    assert isinstance(new_inventory, dict)
    assert isinstance(nonce, str)
    target = root / skill
    target_exists = _path_exists_without_following(target)
    stage_exists = _path_exists_without_following(paths["stage"])
    backup_exists = _path_exists_without_following(paths["backup"])
    if _path_exists_without_following(paths["tombstone"]):
        raise SharedCoreSkillError(
            f"update transaction has an unexpected tombstone: {paths['tombstone']}"
        )

    if backup_exists:
        if old_inventory is None:
            raise SharedCoreSkillError(
                f"new install transaction has an unexpected backup: {paths['backup']}"
            )
        if target_exists:
            if stage_exists:
                raise SharedCoreSkillError(
                    f"completed update transaction still has a stage: {paths['stage']}"
                )
            if not _tree_matches_inventory(target, skill, new_inventory):
                _remove_partial_tree(target, skill, new_inventory)
                os.replace(paths["backup"], target)
                _fsync_directory(root)
                _unlink_transaction(paths["journal"])
                return
            _remove_partial_tree(paths["backup"], skill, old_inventory)
            _unlink_transaction(paths["journal"])
            return
        _validate_tree_against_inventory(paths["backup"], skill, old_inventory)
        if stage_exists:
            _remove_partial_tree(paths["stage"], skill, new_inventory, nonce)
        os.replace(paths["backup"], target)
        _fsync_directory(root)
        _unlink_transaction(paths["journal"])
        return

    if target_exists:
        if old_inventory is not None and _tree_matches_inventory(
            target, skill, old_inventory
        ):
            if stage_exists:
                _remove_partial_tree(paths["stage"], skill, new_inventory, nonce)
            _unlink_transaction(paths["journal"])
            return
        if _tree_matches_inventory(target, skill, new_inventory):
            if stage_exists:
                raise SharedCoreSkillError(
                    f"completed update transaction still has a stage: {paths['stage']}"
                )
            _unlink_transaction(paths["journal"])
            return
        if old_inventory is None and not stage_exists:
            _remove_partial_tree(target, skill, new_inventory)
            _unlink_transaction(paths["journal"])
            return
        raise SharedCoreSkillError(
            f"update transaction target matches neither old nor new inventory: {target}"
        )

    if old_inventory is not None:
        raise SharedCoreSkillError(
            f"update transaction lost both target and backup for {skill}"
        )
    if stage_exists:
        _remove_partial_tree(paths["stage"], skill, new_inventory, nonce)
    _unlink_transaction(paths["journal"])


def _recover_stale_transaction(
    root: Path,
    skill: str,
    transaction: dict[str, object],
) -> None:
    paths = _artifact_paths(root, skill)
    old_inventory = transaction["old_inventory"]
    assert isinstance(old_inventory, dict)
    target = root / skill
    target_exists = _path_exists_without_following(target)
    tombstone_exists = _path_exists_without_following(paths["tombstone"])
    if (
        _path_exists_without_following(paths["stage"])
        or _path_exists_without_following(paths["backup"])
    ):
        raise SharedCoreSkillError(
            f"stale transaction has unexpected update artifacts for {skill}"
        )
    if target_exists and tombstone_exists:
        raise SharedCoreSkillError(
            f"stale transaction has both target and tombstone for {skill}"
        )
    if target_exists:
        _validate_tree_against_inventory(target, skill, old_inventory)
        _unlink_transaction(paths["journal"])
        return
    if tombstone_exists:
        _remove_partial_tree(paths["tombstone"], skill, old_inventory)
    _unlink_transaction(paths["journal"])


def _transaction_artifact_name(name: str) -> bool:
    return name.startswith(
        (
            JOURNAL_PREFIX,
            STAGE_PREFIX,
            BACKUP_PREFIX,
            TOMBSTONE_PREFIX,
            TEMP_PREFIX,
        )
    )


def _journal_skill(path: Path) -> str:
    name = path.name
    if not name.startswith(JOURNAL_PREFIX) or not name.endswith(".json"):
        raise SharedCoreSkillError(f"invalid managed Skill journal name: {path}")
    skill = name[len(JOURNAL_PREFIX) : -len(".json")]
    if not SKILL_NAME_RE.fullmatch(skill):
        raise SharedCoreSkillError(f"invalid managed Skill journal name: {path}")
    if _artifact_paths(path.parent, skill)["journal"] != path:
        raise SharedCoreSkillError(f"non-canonical managed Skill journal name: {path}")
    return skill


def audit_managed_skill_root(root: Path, *, recover: bool) -> None:
    if not _path_exists_without_following(root):
        return
    _require_real_directory(root, "Managed Skill root")
    with os.scandir(root) as iterator:
        entries = sorted(iterator, key=lambda entry: entry.name)
    artifact_entries = [
        Path(entry.path)
        for entry in entries
        if _transaction_artifact_name(entry.name)
    ]
    if artifact_entries and not recover:
        raise SharedCoreSkillError(
            f"incomplete managed Skill transaction: {artifact_entries[0]}"
        )
    if recover:
        root_temporaries = [
            path for path in artifact_entries if path.name.startswith(TEMP_PREFIX)
        ]
        if root_temporaries:
            raise SharedCoreSkillError(
                f"unowned managed Skill transaction temporary: {root_temporaries[0]}"
            )
        journals = [
            path for path in artifact_entries if path.name.startswith(JOURNAL_PREFIX)
        ]
        for journal in journals:
            skill = _journal_skill(journal)
            transaction = _read_transaction(journal, skill)
            if transaction["operation"] == "update":
                _recover_update_transaction(root, skill, transaction)
            else:
                _recover_stale_transaction(root, skill, transaction)

    with os.scandir(root) as iterator:
        remaining = sorted(iterator, key=lambda entry: entry.name)
    for entry in remaining:
        path = Path(entry.path)
        if _transaction_artifact_name(entry.name):
            raise SharedCoreSkillError(
                f"unknown managed Skill transaction artifact: {path}"
            )
        info = entry.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            continue
        state_path = path / STATE_FILE
        skill_path = path / "SKILL.md"
        if not _path_exists_without_following(state_path):
            continue
        if not _path_exists_without_following(skill_path):
            raise SharedCoreSkillError(
                f"orphan managed Skill state without SKILL.md: {state_path}"
            )
        if not SKILL_NAME_RE.fullmatch(entry.name):
            raise SharedCoreSkillError(
                f"managed Skill state is under a non-canonical directory: {path}"
            )
        _validated_installed_tree(path, entry.name)


def _load_shared_core_skills(
    pack_root: Path,
    *,
    capture: bool,
) -> tuple[tuple[str, ...], tuple[SharedCoreSkillSnapshot, ...]]:
    manifest = pack_root / "platforms/shared/core-skills.txt"
    source_root = pack_root / "platforms/shared/skills"
    pack_descriptor = _open_real_directory(pack_root, "workflow pack root")
    platforms_descriptor = -1
    shared_descriptor = -1
    source_descriptor = -1
    snapshots: list[SharedCoreSkillSnapshot] = []
    try:
        platforms_descriptor = _open_real_directory_at(
            pack_descriptor,
            "platforms",
            pack_root / "platforms",
            "platforms directory",
        )
        shared_descriptor = _open_real_directory_at(
            platforms_descriptor,
            "shared",
            pack_root / "platforms/shared",
            "shared platform directory",
        )
        manifest_body = _read_regular_at(
            shared_descriptor,
            "core-skills.txt",
            manifest,
            "Shared core Skill manifest",
        )
        try:
            manifest_text = manifest_body.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SharedCoreSkillError(
                f"Shared core Skill manifest is not valid UTF-8: {manifest}: {exc}"
            ) from exc

        names: list[str] = []
        seen: set[str] = set()
        for raw in manifest_text.splitlines():
            name = raw.strip()
            if not name or name.startswith("#"):
                continue
            if not SKILL_NAME_RE.fullmatch(name):
                raise SharedCoreSkillError(
                    f"invalid shared core Skill name in manifest: {name}"
                )
            if name in seen:
                raise SharedCoreSkillError(
                    f"duplicate shared core Skill in manifest: {name}"
                )
            names.append(name)
            seen.add(name)
        if not names:
            raise SharedCoreSkillError("shared core Skill manifest must not be empty")

        source_descriptor = _open_real_directory_at(
            shared_descriptor,
            "skills",
            source_root,
            "Shared core Skill source root",
        )
        source_names: set[str] = set()
        try:
            with os.scandir(source_descriptor) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise SharedCoreSkillError(
                f"cannot inspect Shared core Skill source root {source_root}: {exc}"
            ) from exc
        for entry in entries:
            node = source_root / entry.name
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise SharedCoreSkillError(
                    f"cannot inspect shared core Skill source {node}: {exc}"
                ) from exc
            if entry.name == ".DS_Store" and stat.S_ISREG(mode):
                descriptor = _open_regular_at(
                    source_descriptor,
                    entry.name,
                    node,
                    "shared core Skill source metadata",
                )
                os.close(descriptor)
                continue
            if not stat.S_ISDIR(mode):
                raise SharedCoreSkillError(
                    f"unexpected node in shared core Skill source root: {entry.name}"
                )
            source_names.add(entry.name)
        for name in sorted(seen - source_names):
            raise SharedCoreSkillError(f"missing shared core Skill source: {name}")
        for name in sorted(source_names - seen):
            raise SharedCoreSkillError(f"unexpected shared core Skill source: {name}")
        for name in names:
            source_dir = source_root / name
            skill_descriptor = _open_real_directory_at(
                source_descriptor,
                name,
                source_dir,
                f"shared core Skill source {name}",
            )
            try:
                captured_files: dict[Path, tuple[bytes, int]] | None = (
                    {} if capture else None
                )
                nodes = _validated_source_tree_descriptor(
                    skill_descriptor,
                    source_dir,
                    name,
                    captured_files,
                )
                if captured_files is not None:
                    snapshots.append(
                        SharedCoreSkillSnapshot(
                            name=name,
                            nodes=tuple(
                                sorted(
                                    (
                                        relative.as_posix(),
                                        node_type,
                                    )
                                    for relative, node_type in nodes.items()
                                )
                            ),
                            files=tuple(
                                sorted(
                                    (
                                        relative.as_posix(),
                                        body,
                                        mode,
                                    )
                                    for relative, (body, mode) in captured_files.items()
                                )
                            ),
                        )
                    )
            finally:
                os.close(skill_descriptor)
        return tuple(names), tuple(snapshots)
    finally:
        if source_descriptor >= 0:
            os.close(source_descriptor)
        if shared_descriptor >= 0:
            os.close(shared_descriptor)
        if platforms_descriptor >= 0:
            os.close(platforms_descriptor)
        os.close(pack_descriptor)


def load_shared_core_skills(pack_root: Path) -> tuple[str, ...]:
    names, _ = _load_shared_core_skills(pack_root, capture=False)
    return names


def _require_empty_staging_root(path: Path) -> None:
    _require_real_directory(path, "Antigravity Skill staging root")
    try:
        with os.scandir(path) as iterator:
            first = next(iterator, None)
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot inspect Antigravity Skill staging root {path}: {exc}"
        ) from exc
    if first is not None:
        raise SharedCoreSkillError(
            f"Antigravity Skill staging root must be empty: {path}"
        )


def _create_snapshot_file(path: Path, body: bytes, mode: int) -> None:
    descriptor = -1
    try:
        descriptor = _open_atomic_temporary(path, 0o600)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise SharedCoreSkillError(
            f"cannot stage descriptor-anchored Skill file {path}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def stage_shared_core_skills(pack_root: Path, staging_root: Path) -> tuple[str, ...]:
    """Copy complete Skill trees from one fd-anchored source snapshot, without state."""

    names, snapshots = _load_shared_core_skills(pack_root, capture=True)
    _require_empty_staging_root(staging_root)
    for snapshot in snapshots:
        skill_root = staging_root / snapshot.name
        skill_root.mkdir(mode=0o755)
        for raw, node_type in sorted(
            snapshot.nodes,
            key=lambda item: (len(Path(item[0]).parts), item[0]),
        ):
            if node_type == "directory":
                (skill_root / Path(raw)).mkdir(mode=0o755)
        for raw, body, mode in snapshot.files:
            _create_snapshot_file(skill_root / Path(raw), body, mode)
    return names


def validate_staged_shared_core_skills(
    pack_root: Path,
    staging_root: Path,
) -> tuple[str, ...]:
    """Require a staged tree to have exactly the captured source paths and bytes."""

    names, snapshots = _load_shared_core_skills(pack_root, capture=True)
    actual = _scan_tree(staging_root, "Antigravity staged shared Skills")
    expected: dict[Path, str] = {}
    expected_bytes: dict[Path, bytes] = {}
    for snapshot in snapshots:
        skill_prefix = Path(snapshot.name)
        expected[skill_prefix] = "directory"
        for raw, node_type in snapshot.nodes:
            expected[skill_prefix / Path(raw)] = node_type
        for raw, body, _mode in snapshot.files:
            expected_bytes[skill_prefix / Path(raw)] = body
    if actual != expected:
        missing = sorted(expected.keys() - actual.keys(), key=str)
        extra = sorted(actual.keys() - expected.keys(), key=str)
        wrong = sorted(
            (
                relative
                for relative in expected.keys() & actual.keys()
                if expected[relative] != actual[relative]
            ),
            key=str,
        )
        if missing:
            detail = f"missing path: {staging_root / missing[0]}"
        elif extra:
            detail = f"extra path: {staging_root / extra[0]}"
        else:
            expected_type = expected[wrong[0]]
            expected_label = (
                "regular file" if expected_type == "file" else expected_type
            )
            detail = (
                f"type mismatch; expected {expected_label} at: "
                f"{staging_root / wrong[0]}"
            )
        raise SharedCoreSkillError(
            f"Antigravity staged Skill tree differs from source snapshot; {detail}"
        )
    for relative, expected_body in expected_bytes.items():
        actual_body = _read_regular_path(
            staging_root / relative,
            "Antigravity staged Skill file",
        )
        if relative.name == "SKILL.md":
            parse_managed_skill_bytes(
                actual_body,
                relative.parts[0],
                str(staging_root / relative),
            )
        if actual_body != expected_body:
            raise SharedCoreSkillError(
                f"Antigravity staged Skill bytes differ from source snapshot: "
                f"{staging_root / relative}"
            )
    return names


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: shared_core_skills.py list PACK_ROOT | "
            "is-managed SKILL_FILE EXPECTED_NAME | "
            "stale-safe SKILL_DIR EXPECTED_NAME | "
            "remove-installed SKILL_DIR EXPECTED_NAME | "
            "recover-root SKILLS_ROOT | audit-root SKILLS_ROOT | "
            "stage-copy PACK_ROOT EMPTY_TARGET_ROOT | "
            "target-safe SOURCE_DIR TARGET_DIR EXPECTED_NAME | "
            "sync-tree SOURCE_DIR TARGET_DIR EXPECTED_NAME | "
            "tree-match SOURCE_DIR TARGET_DIR EXPECTED_NAME",
            file=sys.stderr,
        )
        return 2
    try:
        command = sys.argv[1]
        if command == "list" and len(sys.argv) == 3:
            print("\n".join(load_shared_core_skills(Path(sys.argv[2]))))
            return 0
        if command == "is-managed" and len(sys.argv) == 4:
            return 0 if is_pack_managed_skill(Path(sys.argv[2]), sys.argv[3]) else 1
        if command == "stale-safe" and len(sys.argv) == 4:
            validate_stale_managed_skill_directory(Path(sys.argv[2]), sys.argv[3])
            return 0
        if command == "remove-installed" and len(sys.argv) == 4:
            remove_stale_skill_tree_transactionally(Path(sys.argv[2]), sys.argv[3])
            return 0
        if command == "recover-root" and len(sys.argv) == 3:
            audit_managed_skill_root(Path(sys.argv[2]), recover=True)
            return 0
        if command == "audit-root" and len(sys.argv) == 3:
            audit_managed_skill_root(Path(sys.argv[2]), recover=False)
            return 0
        if command == "stage-copy" and len(sys.argv) == 4:
            stage_shared_core_skills(Path(sys.argv[2]), Path(sys.argv[3]))
            return 0
        if command == "target-safe" and len(sys.argv) == 5:
            validate_target_skill_tree_for_update(
                Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
            )
            return 0
        if command == "sync-tree" and len(sys.argv) == 5:
            sync_skill_tree(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
            return 0
        if command == "tree-match" and len(sys.argv) == 5:
            compare_skill_trees(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
            return 0
        print("invalid shared_core_skills.py arguments", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, SharedCoreSkillError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
