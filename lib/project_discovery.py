#!/usr/bin/env python3
"""Strict, read-only repository discovery and native verification inference.

This module exposes only observed project facts and commands justified by checked-in
evidence. Host rendering and mutable configuration belong to later layers.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
if __package__:
    from .platform_fs import os
else:
    from platform_fs import os
import re
import stat
import tomllib
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


MAX_SCAN_DEPTH = 24
MAX_SCAN_ENTRIES = 50_000
MAX_MANIFEST_SIZE = 1024 * 1024
MAX_CANDIDATE_MANIFESTS = 4_096
MAX_CANDIDATE_BYTES = 64 * 1024 * 1024
MAX_MODULE_OVERRIDES = 256
MAX_EXCLUDED_ROOTS = 256
MAX_JSON_NESTING = 256

IMPLEMENTATION_ROLES = frozenset(
    {"xy-web", "xy-desktop", "xy-backend", "xy-apple", "xy-android"}
)
UI_ROLES = frozenset({"xy-web", "xy-desktop", "xy-apple", "xy-android"})
CANONICAL_ROLES = IMPLEMENTATION_ROLES | {"xy-uiux", "xy-qa"}

IGNORED_DIRECTORY_NAMES = frozenset(
    {
        "agent_workflow",
        ".agent-workflow",
        ".git",
        # 宿主目录可能保存完整 worktree 和缓存清单；必须在进入目录前排除，
        # 包括任意业务模块下的嵌套目录，避免将同一代码副本重新派发为业务模块。
        ".claude",
        ".codex",
        ".agents",
        ".hg",
        ".svn",
        ".bzr",
        "node_modules",
        "vendor",
        ".venv",
        "venv",
        "build",
        "dist",
        "out",
        "target",
        "coverage",
        ".idea",
        ".vscode",
        ".gradle",
        "DerivedData",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "__pycache__",
    }
)

JSON_MANIFESTS = frozenset(
    {
        "package.json",
        "composer.json",
        "openapi.json",
        "tauri.conf.json",
        "CMakePresets.json",
    }
)
TOML_MANIFESTS = frozenset(
    {"pyproject.toml", "Cargo.toml", "libs.versions.toml"}
)
XML_MANIFESTS = frozenset({"pom.xml", "AndroidManifest.xml"})
PLAIN_MANIFESTS = frozenset(
    {
        "go.mod",
        "Package.swift",
        "build.gradle",
        "build.gradle.kts",
        "CMakeLists.txt",
        "meson.build",
        "project.pbxproj",
    }
)
WEB_FRAMEWORKS = (
    ("@angular/core", "framework:angular"),
    ("next", "framework:next"),
    ("nuxt", "framework:nuxt"),
    ("preact", "framework:preact"),
    ("react", "framework:react"),
    ("solid-js", "framework:solid"),
    ("svelte", "framework:svelte"),
    ("vue", "framework:vue"),
)
NODE_BACKEND_FRAMEWORKS = (
    ("@adonisjs/core", "framework:adonis"),
    ("@hapi/hapi", "framework:hapi"),
    ("@nestjs/core", "framework:nestjs"),
    ("express", "framework:express"),
    ("fastify", "framework:fastify"),
    ("koa", "framework:koa"),
)
RUNTIME_PACKAGE_DEPENDENCY_SECTIONS = (
    "dependencies",
    "optionalDependencies",
)
ELECTRON_PACKAGE_DEPENDENCY_SECTIONS = (
    *RUNTIME_PACKAGE_DEPENDENCY_SECTIONS,
    "devDependencies",
)
ELECTRON_CONFIG_FILES = (
    "electron-builder.json",
    "electron-builder.yml",
    "electron-builder.yaml",
    "electron-forge.config.js",
    "electron-forge.config.cjs",
    "electron-forge.config.mjs",
    "electron-forge.config.ts",
    "electron.vite.config.js",
    "electron.vite.config.mjs",
    "electron.vite.config.ts",
    "forge.config.js",
    "forge.config.cjs",
    "forge.config.mjs",
    "forge.config.ts",
)
TAURI_CONFIG_KEYS = frozenset(
    {
        "$schema",
        "app",
        "build",
        "bundle",
        "identifier",
        "mainBinaryName",
        "plugins",
        "productName",
        "version",
    }
)
ANDROID_PLUGIN_IDS = frozenset(
    {
        "com.android.application",
        "com.android.dynamic-feature",
        "com.android.library",
    }
)

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", None)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", None)
_OPEN_SUPPORTS_DIR_FD = os.open in getattr(os, "supports_dir_fd", set())
_STAT_SUPPORTS_DIR_FD = os.stat in getattr(os, "supports_dir_fd", set())
_STAT_SUPPORTS_NOFOLLOW = os.stat in getattr(
    os, "supports_follow_symlinks", set()
)
_SCANDIR_SUPPORTS_FD = os.scandir in getattr(os, "supports_fd", set())
_BASE_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)


class DiscoveryError(ValueError):
    """A project cannot be discovered without weakening the safety contract."""


def _require_secure_capabilities() -> None:
    missing: list[str] = []
    if not isinstance(_O_NOFOLLOW, int) or _O_NOFOLLOW == 0:
        missing.append("O_NOFOLLOW")
    if not isinstance(_O_DIRECTORY, int) or _O_DIRECTORY == 0:
        missing.append("O_DIRECTORY")
    if not isinstance(_O_NONBLOCK, int) or _O_NONBLOCK == 0:
        missing.append("O_NONBLOCK")
    if not _OPEN_SUPPORTS_DIR_FD:
        missing.append("os.open(dir_fd)")
    if not _STAT_SUPPORTS_DIR_FD:
        missing.append("os.stat(dir_fd)")
    if not _STAT_SUPPORTS_NOFOLLOW:
        missing.append("os.stat(follow_symlinks=False)")
    if not _SCANDIR_SUPPORTS_FD:
        missing.append("os.scandir(fd)")
    if missing:
        raise DiscoveryError(
            "secure discovery capabilities are unavailable: " + ", ".join(missing)
        )


def _directory_flags() -> int:
    _require_secure_capabilities()
    assert isinstance(_O_NOFOLLOW, int)
    assert isinstance(_O_DIRECTORY, int)
    return _BASE_OPEN_FLAGS | _O_NOFOLLOW | _O_DIRECTORY


def _regular_flags() -> int:
    _require_secure_capabilities()
    assert isinstance(_O_NOFOLLOW, int)
    assert isinstance(_O_NONBLOCK, int)
    return _BASE_OPEN_FLAGS | _O_NOFOLLOW | _O_NONBLOCK


def _sequence_tuple(value: object, label: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{label} must be a non-string sequence")
    return tuple(value)


def _string_tuple(
    value: object,
    label: str,
    *,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    items = _sequence_tuple(value, label)
    if require_nonempty and not items:
        raise ValueError(f"{label} must not be empty")
    for item in items:
        if not isinstance(item, str) or not item.strip() or "\x00" in item:
            raise TypeError(f"{label} must contain non-empty strings")
    return items  # type: ignore[return-value]


def _typed_tuple(value: object, expected: type, label: str) -> tuple[Any, ...]:
    items = _sequence_tuple(value, label)
    if any(not isinstance(item, expected) for item in items):
        raise TypeError(f"{label} must contain only {expected.__name__} values")
    return items


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise TypeError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True)
class VerificationCommand:
    """One repository-native command justified by checked-in evidence."""

    purpose: str
    argv: tuple[str, ...]
    evidence_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        purpose = _require_string(self.purpose, "verification command purpose")
        argv = _string_tuple(
            self.argv, "verification command argv", require_nonempty=True
        )
        evidence = tuple(
            sorted(
                _normalize_relative(path, "command evidence path", allow_root=False)
                for path in _string_tuple(
                    self.evidence_paths, "command evidence paths"
                )
            )
        )
        if len(set(evidence)) != len(evidence):
            raise ValueError("command evidence paths must be unique")
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "evidence_paths", evidence)


@dataclass(frozen=True)
class ModuleProfile:
    """Observed facts and routing role for one normalized module root."""

    root: str
    primary_role: str
    evidence_paths: tuple[str, ...]
    stack_facts: tuple[str, ...]
    verification_commands: tuple[VerificationCommand, ...] = ()

    def __post_init__(self) -> None:
        root = _normalize_relative(self.root, "module root", allow_root=True)
        role = _require_string(self.primary_role, "module primary role")
        if role not in IMPLEMENTATION_ROLES:
            raise ValueError(f"unsupported module primary role: {role!r}")
        evidence = tuple(
            sorted(
                _normalize_relative(path, "module evidence path", allow_root=False)
                for path in _string_tuple(
                    self.evidence_paths, "module evidence paths"
                )
            )
        )
        facts = tuple(sorted(_string_tuple(self.stack_facts, "module stack facts")))
        commands = _typed_tuple(
            self.verification_commands,
            VerificationCommand,
            "module verification commands",
        )
        if len(set(evidence)) != len(evidence) or len(set(facts)) != len(facts):
            raise ValueError("module evidence paths and stack facts must be unique")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "primary_role", role)
        object.__setattr__(self, "evidence_paths", evidence)
        object.__setattr__(self, "stack_facts", facts)
        object.__setattr__(self, "verification_commands", commands)


@dataclass(frozen=True)
class ProjectProfile:
    """Stable immutable output shared by future host and validation layers."""

    modules: tuple[ModuleProfile, ...]
    enabled_roles: tuple[str, ...]
    diagnostics: tuple[str, ...]

    @property
    def design_scaffold_required(self) -> bool:
        """区分角色可用性与设计文档脚手架：基础 UI 角色不强制后端项目进入 UI。

        尚无实现模块的项目需要支持先需求、后原型；已发现的纯后端项目仍沿用工程
        文档脚手架。后续明确的设计任务可按现有规范维护流程建立所需设计叶文档。
        """
        return not self.modules or any(module.primary_role in UI_ROLES for module in self.modules)

    def __post_init__(self) -> None:
        modules = tuple(
            sorted(
                _typed_tuple(self.modules, ModuleProfile, "project modules"),
                key=lambda module: module.root,
            )
        )
        if len({module.root for module in modules}) != len(modules):
            raise ValueError("project module roots must be unique")
        enabled = tuple(
            sorted(_string_tuple(self.enabled_roles, "project enabled roles"))
        )
        if len(set(enabled)) != len(enabled):
            raise ValueError("project enabled roles must be unique")
        unsupported = set(enabled) - CANONICAL_ROLES
        if unsupported:
            raise ValueError(f"unsupported enabled roles: {sorted(unsupported)}")
        if "xy-qa" not in enabled:
            raise ValueError("project enabled roles must include xy-qa")
        missing_module_roles = {
            module.primary_role for module in modules
        } - set(enabled)
        if missing_module_roles:
            raise ValueError(
                "project enabled roles omit module roles: "
                f"{sorted(missing_module_roles)}"
            )
        if any(module.primary_role in UI_ROLES for module in modules) and "xy-uiux" not in enabled:
            raise ValueError("project UI modules require the xy-uiux role")
        diagnostics = _string_tuple(self.diagnostics, "project diagnostics")
        object.__setattr__(self, "modules", modules)
        object.__setattr__(self, "enabled_roles", enabled)
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def module_roots(self) -> tuple[str, ...]:
        return tuple(module.root for module in self.modules)

    @property
    def primary_roles(self) -> tuple[str, ...]:
        return tuple(module.primary_role for module in self.modules)

    @property
    def evidence_paths(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    evidence
                    for module in self.modules
                    for evidence in module.evidence_paths
                }
            )
        )

    @property
    def detected_stack_facts(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {fact for module in self.modules for fact in module.stack_facts}
            )
        )

    @property
    def verification_commands(self) -> tuple[VerificationCommand, ...]:
        return tuple(
            command
            for module in self.modules
            for command in module.verification_commands
        )


@dataclass(frozen=True)
class ModuleOverride:
    root: str
    primary_role: str

    def __post_init__(self) -> None:
        root = _normalize_relative(self.root, "module override root", allow_root=True)
        role = _require_string(self.primary_role, "module override role")
        if role not in IMPLEMENTATION_ROLES:
            raise ValueError(f"unsupported module override role: {role!r}")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "primary_role", role)


@dataclass(frozen=True)
class DiscoveryOverrides:
    module_roles: tuple[ModuleOverride, ...] = ()
    exclude_roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        roles = _typed_tuple(
            self.module_roles, ModuleOverride, "discovery module roles"
        )
        exclusions = tuple(
            _normalize_relative(path, "excluded root", allow_root=False)
            for path in _string_tuple(
                self.exclude_roots, "discovery excluded roots"
            )
        )
        roots = tuple(item.root for item in roles)
        if len(set(roots)) != len(roots):
            raise ValueError("discovery module override roots must be unique")
        if len(set(exclusions)) != len(exclusions):
            raise ValueError("discovery excluded roots must be unique")
        role_paths = tuple(PurePosixPath(root) for root in roots)
        excluded_paths = tuple(PurePosixPath(root) for root in exclusions)
        role_path_set = frozenset(role_paths)
        excluded_path_set = frozenset(excluded_paths)
        role_under_exclusion = any(
            path in excluded_path_set
            or any(parent in excluded_path_set for parent in path.parents)
            for path in role_paths
        )
        exclusion_under_role = any(
            any(parent in role_path_set for parent in path.parents)
            for path in excluded_paths
        )
        if role_under_exclusion or exclusion_under_role:
            raise ValueError("a discovery root cannot be both assigned and excluded")
        object.__setattr__(self, "module_roles", roles)
        object.__setattr__(self, "exclude_roots", exclusions)


@dataclass(frozen=True)
class _Candidate:
    path: str
    parsed: Any


@dataclass
class _ModuleFacts:
    roles: set[str]
    evidence: set[str]
    facts: set[str]


def _normalize_relative(value: str, label: str, *, allow_root: bool) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise DiscoveryError(f"{label} must be a non-empty relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise DiscoveryError(f"{label} must not be absolute or contain '..': {value!r}")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        if allow_root:
            return "."
        raise DiscoveryError(f"{label} must name a project subdirectory")
    return normalized


def _relative(parts: tuple[str, ...]) -> str:
    return "." if not parts else PurePosixPath(*parts).as_posix()


def _join(root: str, child: str) -> str:
    return child if root == "." else f"{root}/{child}"


def _parent(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "." if parent == "." else parent


def _is_under(path: str, ancestor: str) -> bool:
    if ancestor == ".":
        return True
    return path == ancestor or path.startswith(f"{ancestor}/")


def _is_candidate_name(name: str, parent_parts: tuple[str, ...]) -> bool:
    if name in JSON_MANIFESTS | TOML_MANIFESTS | XML_MANIFESTS | PLAIN_MANIFESTS:
        if name == "project.pbxproj":
            return bool(parent_parts and parent_parts[-1].endswith(".xcodeproj"))
        return True
    return name.endswith(".csproj")


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_size)


def _read_regular_at(
    directory_fd: int,
    name: str,
    label: str,
    expected: os.stat_result,
) -> bytes:
    try:
        descriptor = os.open(name, _regular_flags(), dir_fd=directory_fd)
    except OSError as exc:
        raise DiscoveryError(f"cannot securely read candidate manifest {label}: {exc}") from exc
    try:
        try:
            before = os.fstat(descriptor)
        except OSError as exc:
            raise DiscoveryError(
                f"cannot inspect candidate manifest {label}: {exc}"
            ) from exc
        if not stat.S_ISREG(before.st_mode):
            raise DiscoveryError(
                f"candidate manifest must be a real regular file: {label}"
            )
        if _identity(before) != _identity(expected):
            raise DiscoveryError(
                f"candidate manifest {label} identity changed before reading"
            )
        if before.st_size > MAX_MANIFEST_SIZE:
            raise DiscoveryError(f"candidate manifest exceeds size limit: {label}")
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                chunk = os.read(
                    descriptor,
                    min(64 * 1024, MAX_MANIFEST_SIZE + 1 - total),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_MANIFEST_SIZE:
                    raise DiscoveryError(
                        f"candidate manifest exceeds size limit: {label}"
                    )
            after = os.fstat(descriptor)
        except OSError as exc:
            raise DiscoveryError(
                f"cannot read candidate manifest {label}: {exc}"
            ) from exc
        if _identity(before) != _identity(after) or before.st_mtime_ns != after.st_mtime_ns:
            raise DiscoveryError(
                f"candidate manifest {label} identity changed while reading"
            )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _parse_candidate(path: str, body: bytes) -> Any:
    name = PurePosixPath(path).name
    try:
        text = body.decode("utf-8", errors="strict")
        if name in JSON_MANIFESTS:
            depth = 0
            in_string = False
            escaped = False
            for char in text:
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                    continue
                if char in "[{":
                    depth += 1
                    if depth > MAX_JSON_NESTING:
                        raise ValueError(
                            f"JSON nesting depth exceeds limit {MAX_JSON_NESTING}"
                        )
                elif char in "]}":
                    depth -= 1
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("top-level value must be an object")
            return parsed
        if name in TOML_MANIFESTS:
            parsed = tomllib.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("top-level value must be a table")
            return parsed
        if name in XML_MANIFESTS or name.endswith(".csproj"):
            markup = _xml_markup_for_security_check(text)
            declaration = re.search(
                r"<\s*!\s*(DOCTYPE|ENTITY)\b",
                markup,
                flags=re.IGNORECASE,
            )
            if declaration is not None:
                raise ValueError(
                    f"XML {declaration.group(1).upper()} declarations are forbidden"
                )
            return ElementTree.fromstring(text)
        _validate_plain_manifest(name, text)
        return text
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        tomllib.TOMLDecodeError,
        ElementTree.ParseError,
        ValueError,
    ) as exc:
        raise DiscoveryError(f"malformed manifest {path}: {exc}") from exc


def _xml_markup_for_security_check(text: str) -> str:
    """Blank comments and CDATA before checking XML declaration syntax."""
    cleaned: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("<!--", index):
            end = text.find("-->", index + 4)
            if end < 0:
                return text
            segment = text[index : end + 3]
            cleaned.extend("\n" if char in "\r\n" else " " for char in segment)
            index = end + 3
            continue
        if text.startswith("<![CDATA[", index):
            end = text.find("]]>", index + 9)
            if end < 0:
                return text
            segment = text[index : end + 3]
            cleaned.extend("\n" if char in "\r\n" else " " for char in segment)
            index = end + 3
            continue
        cleaned.append(text[index])
        index += 1
    return "".join(cleaned)


def _validate_plain_manifest(name: str, text: str) -> None:
    if name == "go.mod":
        module = re.search(
            r"(?m)^\s*module\s+(?:\"[^\"\r\n]+\"|`[^`\r\n]+`|\S+)\s*(?://.*)?$",
            text,
        )
        if module is None:
            raise ValueError("go.mod is missing a valid module directive")
        return
    if name == "Package.swift":
        if not (
            re.search(r"(?m)^\s*import\s+PackageDescription\s*$", text)
            and re.search(r"\blet\s+package\s*=\s*Package\s*\(", text)
        ):
            raise ValueError(
                "Package.swift lacks PackageDescription import or Package declaration"
            )
        return
    if name in {"build.gradle", "build.gradle.kts"}:
        clean = _clean_gradle(text)
        if not _balanced_braces(clean):
            raise ValueError("Gradle manifest has unbalanced build structure")
        if not _has_top_level_gradle_dsl(clean):
            raise ValueError("Gradle manifest lacks top-level build DSL structure")
        return
    if name == "CMakeLists.txt":
        if re.search(
            r"(?im)^\s*(?:project|add_executable|add_library)\s*\(\s*"
            r"(?:[A-Za-z0-9_.+:-]+|\"[^\"\r\n]+\")",
            text,
        ) is None:
            raise ValueError("CMakeLists.txt lacks a project or target declaration")
        return
    if name == "meson.build":
        if re.search(
            r"(?im)^\s*project\s*\(\s*(?:'[^'\r\n]+'|\"[^\"\r\n]+\")",
            text,
        ) is None:
            raise ValueError("meson.build lacks a project declaration")
        return
    if name == "project.pbxproj":
        if not (
            text.lstrip().startswith("// !$*UTF8*$!")
            and re.search(r"(?m)^\s*objects\s*=\s*\{", text)
            and re.search(r"(?m)^\s*};\s*$", text)
        ):
            raise ValueError("project.pbxproj lacks the standard header or objects table")
        return
    raise ValueError(f"no validator for plain manifest {name}")


def _clean_gradle(text: str) -> str:
    cleaned: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("//", index):
            cleaned.extend("  ")
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                cleaned.append(" ")
                index += 1
            continue
        if text.startswith("/*", index):
            cleaned.extend("  ")
            index += 2
            while index < len(text) and not text.startswith("*/", index):
                cleaned.append(text[index] if text[index] in "\r\n" else " ")
                index += 1
            if index >= len(text):
                raise ValueError("Gradle manifest has an unterminated block comment")
            cleaned.extend("  ")
            index += 2
            continue
        if text.startswith("$/", index):
            cleaned.extend("xx")
            index += 2
            while index < len(text) and not text.startswith("/$", index):
                cleaned.append(text[index] if text[index] in "\r\n" else "x")
                index += 1
            if index >= len(text):
                raise ValueError("Gradle manifest has an unterminated dollar-slashy string")
            cleaned.extend("xx")
            index += 2
            continue
        if (
            text[index] == "/"
            and not text.startswith("//", index)
            and not text.startswith("/*", index)
        ):
            previous = text[index - 1] if index else ""
            # A slash following an operand is division; otherwise Groovy permits
            # slashy regex literals. Keep division syntax intact for brace checks.
            if previous and (previous.isalnum() or previous in ")]}"):
                cleaned.append("/")
                index += 1
                continue
            cleaned.append("x")
            index += 1
            escaped = False
            while index < len(text):
                char = text[index]
                if escaped:
                    cleaned.append("x")
                    escaped = False
                    index += 1
                    continue
                if char == "\\":
                    cleaned.append("x")
                    escaped = True
                    index += 1
                    continue
                if char == "/":
                    cleaned.append("x")
                    index += 1
                    break
                cleaned.append(char if char in "\r\n" else "x")
                index += 1
            else:
                raise ValueError("Gradle manifest has an unterminated slashy string")
            continue
        quote = text[index] if text[index] in {'"', "'"} else None
        if quote is not None:
            delimiter = quote * 3 if text.startswith(quote * 3, index) else quote
            cleaned.extend(delimiter)
            index += len(delimiter)
            while index < len(text) and not text.startswith(delimiter, index):
                char = text[index]
                if len(delimiter) == 1 and char == "\\":
                    cleaned.append(" ")
                    index += 1
                    if index < len(text):
                        cleaned.append(" ")
                        index += 1
                    continue
                cleaned.append(char if char in "\r\n" else "x")
                index += 1
            if index >= len(text):
                raise ValueError("Gradle manifest has an unterminated string")
            cleaned.extend(delimiter)
            index += len(delimiter)
            continue
        cleaned.append(text[index])
        index += 1
    return "".join(cleaned)


def _balanced_braces(text: str) -> bool:
    depth = 0
    for char in text:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _matching_brace(text: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _has_top_level_gradle_dsl(text: str) -> bool:
    block_names = {
        "android",
        "application",
        "buildscript",
        "dependencies",
        "repositories",
    }
    plugin_declaration = re.compile(
        r"\bid\s*(?:\(\s*|\s+)['\"][^'\"]+['\"]"
        r"|\bkotlin\s*\(\s*['\"][^'\"]+['\"]"
        r"|\balias\s*\(\s*[A-Za-z_]"
        r"|\b(?:java|application)\b"
    )
    index = 0
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth -= 1
            index += 1
            continue
        if depth != 0 or not (char.isalpha() or char == "_"):
            index += 1
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[index:])
        assert match is not None
        name = match.group(0)
        cursor = index + len(name)
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if name in block_names and cursor < len(text) and text[cursor] == "{":
            return True
        if name == "plugins" and cursor < len(text) and text[cursor] == "{":
            closing = _matching_brace(text, cursor)
            if closing > cursor and plugin_declaration.search(text[cursor + 1 : closing]):
                return True
        if name == "apply" and re.match(
            r"plugin\s*:\s*['\"][^'\"]+['\"]", text[cursor:]
        ):
            return True
        if name in {"include", "includeBuild"} and re.match(
            r"(?:\(\s*)?['\"][^'\"]+['\"]", text[cursor:]
        ):
            return True
        index = cursor if cursor > index else index + 1
    return False


class _Scanner:
    def __init__(self, exclusions: frozenset[PurePosixPath]) -> None:
        self.exclusions = exclusions
        self.entry_count = 0
        self.candidate_count = 0
        self.candidate_bytes = 0
        self.candidates: list[_Candidate] = []
        self.regular_paths: set[str] = set()

    def _is_excluded(self, parts: tuple[str, ...]) -> bool:
        path = PurePosixPath(*parts)
        return any(ancestor in self.exclusions for ancestor in (path, *path.parents))

    def scan(self, root_fd: int) -> tuple[tuple[_Candidate, ...], frozenset[str]]:
        self._scan_directory(root_fd, (), 0)
        return tuple(sorted(self.candidates, key=lambda item: item.path)), frozenset(
            self.regular_paths
        )

    def _scan_directory(
        self, directory_fd: int, parent_parts: tuple[str, ...], depth: int
    ) -> None:
        if depth > MAX_SCAN_DEPTH:
            raise DiscoveryError(
                f"repository scan exceeds depth limit at {_relative(parent_parts)}"
            )
        try:
            names: list[str] = []
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    self.entry_count += 1
                    if self.entry_count > MAX_SCAN_ENTRIES:
                        raise DiscoveryError(
                            "repository scan exceeds entry limit "
                            f"{MAX_SCAN_ENTRIES} in directory {_relative(parent_parts)}"
                        )
                    names.append(entry.name)
        except OSError as exc:
            raise DiscoveryError(
                f"cannot scan directory {_relative(parent_parts)}: {exc}"
            ) from exc
        names.sort()
        for name in names:
            parts = (*parent_parts, name)
            relative = _relative(parts)
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise DiscoveryError(f"cannot inspect repository entry {relative}: {exc}") from exc

            candidate = _is_candidate_name(name, parent_parts)
            if stat.S_ISLNK(info.st_mode):
                if candidate:
                    raise DiscoveryError(f"candidate manifest must not be a symlink: {relative}")
                continue
            if stat.S_ISDIR(info.st_mode):
                if candidate:
                    raise DiscoveryError(
                        f"candidate manifest must be a real regular file: {relative}"
                    )
                # 安装器的暂存、备份与失败保留目录同样不能被识别为业务模块。
                if (
                    name in IGNORED_DIRECTORY_NAMES
                    or name.startswith(".agent-workflow-")
                    or self._is_excluded(parts)
                ):
                    continue
                try:
                    child_fd = os.open(
                        name, _directory_flags(), dir_fd=directory_fd
                    )
                except OSError as exc:
                    raise DiscoveryError(
                        f"cannot securely enter directory {relative}: {exc}"
                    ) from exc
                try:
                    try:
                        child_info = os.fstat(child_fd)
                    except OSError as exc:
                        raise DiscoveryError(
                            f"cannot inspect opened directory {relative}: {exc}"
                        ) from exc
                    if not stat.S_ISDIR(child_info.st_mode):
                        raise DiscoveryError(f"repository entry is not a real directory: {relative}")
                    if _identity(info) != _identity(child_info):
                        raise DiscoveryError(
                            f"repository entry {relative} identity changed while opening"
                        )
                    self._scan_directory(child_fd, parts, depth + 1)
                finally:
                    os.close(child_fd)
                continue
            if stat.S_ISREG(info.st_mode):
                self.regular_paths.add(relative)
                if candidate:
                    self.candidate_count += 1
                    if self.candidate_count > MAX_CANDIDATE_MANIFESTS:
                        raise DiscoveryError(
                            "repository scan exceeds manifest count limit "
                            f"{MAX_CANDIDATE_MANIFESTS} at {relative}"
                        )
                    self.candidate_bytes += info.st_size
                    if self.candidate_bytes > MAX_CANDIDATE_BYTES:
                        raise DiscoveryError(
                            "repository scan exceeds manifest byte limit "
                            f"{MAX_CANDIDATE_BYTES} at {relative}"
                        )
                    body = _read_regular_at(
                        directory_fd, name, relative, info
                    )
                    self.candidates.append(
                        _Candidate(relative, _parse_candidate(relative, body))
                    )
                continue
            if candidate:
                raise DiscoveryError(
                    f"candidate manifest must be a real regular file: {relative}"
                )


def _open_project_root(root: Path) -> int:
    try:
        info = root.lstat()
    except OSError as exc:
        raise DiscoveryError(f"cannot inspect project root {root}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise DiscoveryError(f"project root must not be a symlink: {root}")
    if not stat.S_ISDIR(info.st_mode):
        raise DiscoveryError(f"project root must be a real directory: {root}")
    try:
        descriptor = os.open(root, _directory_flags())
    except OSError as exc:
        raise DiscoveryError(f"cannot securely open project root {root}: {exc}") from exc
    try:
        try:
            opened = os.fstat(descriptor)
        except OSError as exc:
            raise DiscoveryError(
                f"cannot inspect opened project root {root}: {exc}"
            ) from exc
        if not stat.S_ISDIR(opened.st_mode):
            raise DiscoveryError(f"project root must be a real directory: {root}")
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise DiscoveryError(f"project root changed while opening: {root}")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _require_override_directory(root_fd: int, relative: str, label: str) -> None:
    if relative == ".":
        return
    descriptor = os.dup(root_fd)
    try:
        for component in PurePosixPath(relative).parts:
            try:
                child = os.open(
                    component, _directory_flags(), dir_fd=descriptor
                )
            except OSError as exc:
                raise DiscoveryError(
                    f"{label} must name a real non-symlink directory: {relative}: {exc}"
                ) from exc
            os.close(descriptor)
            descriptor = child
            try:
                opened = os.fstat(descriptor)
            except OSError as exc:
                raise DiscoveryError(
                    f"cannot inspect {label} {relative}: {exc}"
                ) from exc
            if not stat.S_ISDIR(opened.st_mode):
                raise DiscoveryError(
                    f"{label} must name a real non-symlink directory: {relative}"
                )
    finally:
        os.close(descriptor)


def _validated_overrides(
    root_fd: int, overrides: DiscoveryOverrides | None
) -> tuple[dict[str, str], frozenset[str]]:
    if overrides is None:
        overrides = DiscoveryOverrides()
    if not isinstance(overrides, DiscoveryOverrides):
        raise DiscoveryError("overrides must be a DiscoveryOverrides value")
    if len(overrides.module_roles) > MAX_MODULE_OVERRIDES:
        raise DiscoveryError(
            f"discovery exceeds module override limit {MAX_MODULE_OVERRIDES}"
        )
    if len(overrides.exclude_roots) > MAX_EXCLUDED_ROOTS:
        raise DiscoveryError(
            f"discovery exceeds excluded root limit {MAX_EXCLUDED_ROOTS}"
        )

    module_roles: dict[str, str] = {}
    for item in overrides.module_roles:
        if not isinstance(item, ModuleOverride):
            raise DiscoveryError("module_roles must contain ModuleOverride values")
        normalized = item.root
        if normalized in module_roles:
            if module_roles[normalized] != item.primary_role:
                raise DiscoveryError(
                    f"conflicting role assignments for normalized override root: {normalized}"
                )
            raise DiscoveryError(f"duplicate normalized override root: {normalized}")
        _require_override_directory(root_fd, normalized, "module override root")
        module_roles[normalized] = item.primary_role

    exclusions: set[PurePosixPath] = set()
    for raw in overrides.exclude_roots:
        excluded = PurePosixPath(raw)
        if excluded in exclusions:
            raise DiscoveryError(f"duplicate normalized excluded root: {raw}")
        _require_override_directory(root_fd, raw, "excluded root")
        exclusions.add(excluded)

    return module_roles, frozenset(exclusions)


def _module_facts(
    modules: dict[str, _ModuleFacts], root: str
) -> _ModuleFacts:
    return modules.setdefault(root, _ModuleFacts(set(), set(), set()))


def _add(
    modules: dict[str, _ModuleFacts],
    root: str,
    role: str,
    evidence: tuple[str, ...],
    facts: tuple[str, ...],
) -> None:
    module = _module_facts(modules, root)
    module.roles.add(role)
    module.evidence.update(evidence)
    module.facts.update(facts)


def _package_dependencies(
    parsed: dict[str, Any], sections: tuple[str, ...]
) -> set[str]:
    dependencies: set[str] = set()
    for key in sections:
        values = parsed.get(key, {})
        if isinstance(values, dict):
            dependencies.update(value for value in values if isinstance(value, str))
    return dependencies


def _cargo_dependencies(parsed: dict[str, Any]) -> set[str]:
    values = parsed.get("dependencies", {})
    return set(values) if isinstance(values, dict) else set()


def _electron_application_evidence(
    candidate: _Candidate, regular_paths: frozenset[str]
) -> tuple[str, ...]:
    parsed = candidate.parsed
    dependencies = _package_dependencies(
        parsed, ELECTRON_PACKAGE_DEPENDENCY_SECTIONS
    )
    if "electron" not in dependencies:
        return ()

    root = _parent(candidate.path)
    evidence = {candidate.path}
    main = parsed.get("main")
    if isinstance(main, str):
        try:
            normalized_main = _normalize_relative(
                main, "Electron package main", allow_root=False
            )
        except DiscoveryError:
            normalized_main = ""
        if normalized_main:
            entry_path = _join(root, normalized_main)
            if entry_path in regular_paths:
                evidence.add(entry_path)
                return tuple(sorted(evidence))

    config = parsed.get("config")
    forge = config.get("forge") if isinstance(config, dict) else None
    if (
        isinstance(forge, dict)
        and bool(forge)
        and (
            "@electron-forge/cli" in dependencies
            or "electron-forge" in dependencies
        )
    ):
        return tuple(sorted(evidence))

    build = parsed.get("build")
    if (
        isinstance(build, dict)
        and bool(build)
        and "electron-builder" in dependencies
    ):
        return tuple(sorted(evidence))

    for name in ELECTRON_CONFIG_FILES:
        config_path = _join(root, name)
        if config_path not in regular_paths:
            continue
        if "forge" in name and not (
            "@electron-forge/cli" in dependencies
            or "electron-forge" in dependencies
        ):
            continue
        if "builder" in name and "electron-builder" not in dependencies:
            continue
        if "electron.vite" in name and "electron-vite" not in dependencies:
            continue
        evidence.add(config_path)
        return tuple(sorted(evidence))
    return ()


def _is_tauri_config(parsed: Any) -> bool:
    return isinstance(parsed, dict) and bool(TAURI_CONFIG_KEYS & parsed.keys())


def _gradle_plugin_ids(text: str) -> frozenset[str]:
    """Return literal plugin IDs from executable top-level Gradle plugin syntax."""

    cleaned = _clean_gradle(text)
    plugin_ids: set[str] = set()
    index = 0
    depth = 0
    while index < len(cleaned):
        char = cleaned[index]
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth -= 1
            index += 1
            continue
        if depth != 0 or not (char.isalpha() or char == "_"):
            index += 1
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", cleaned[index:])
        assert match is not None
        name = match.group(0)
        cursor = index + len(name)
        while cursor < len(cleaned) and cleaned[cursor].isspace():
            cursor += 1
        if name == "plugins" and cursor < len(cleaned) and cleaned[cursor] == "{":
            closing = _matching_brace(cleaned, cursor)
            if closing < 0:
                return frozenset(plugin_ids)
            block = cleaned[cursor + 1 : closing]
            for declaration in re.finditer(r"\bid\s*(?:\(\s*|\s+)", block):
                absolute = cursor + 1 + declaration.start()
                source = text[absolute:closing]
                literal = re.match(
                    r"id\s*(?:\(\s*|\s+)(['\"])([^'\"]+)\1",
                    source,
                )
                if literal is not None:
                    plugin_ids.add(literal.group(2))
            index = closing + 1
            continue
        if name == "apply":
            source = text[index:]
            literal = re.match(
                r"apply\s+plugin\s*:\s*(['\"])([^'\"]+)\1",
                source,
            )
            if literal is not None:
                plugin_ids.add(literal.group(2))
        index = cursor if cursor > index else index + 1
    return frozenset(plugin_ids)


def _gradle_plugin_aliases(text: str) -> frozenset[str]:
    """Return executable ``libs.plugins.*`` accessors from a top-level plugins block."""

    cleaned = _clean_gradle(text)
    aliases: set[str] = set()
    index = 0
    depth = 0
    while index < len(cleaned):
        char = cleaned[index]
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth -= 1
            index += 1
            continue
        if depth != 0 or not (char.isalpha() or char == "_"):
            index += 1
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", cleaned[index:])
        assert match is not None
        name = match.group(0)
        cursor = index + len(name)
        while cursor < len(cleaned) and cleaned[cursor].isspace():
            cursor += 1
        if name == "plugins" and cursor < len(cleaned) and cleaned[cursor] == "{":
            closing = _matching_brace(cleaned, cursor)
            if closing < 0:
                return frozenset(aliases)
            block = cleaned[cursor + 1 : closing]
            aliases.update(
                match.group(1)
                for match in re.finditer(
                    r"\balias\s*\(\s*libs\.plugins\."
                    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
                    r"\s*\)",
                    block,
                )
            )
            index = closing + 1
            continue
        index = cursor if cursor > index else index + 1
    return frozenset(aliases)


def _catalog_accessor(alias: str) -> str:
    return re.sub(r"[._-]+", ".", alias).strip(".")


def _catalog_plugin_ids(parsed: Any, aliases: frozenset[str]) -> frozenset[str]:
    """Resolve only aliases backed by literal plugin IDs in a parsed version catalog."""

    plugins = parsed.get("plugins", {}) if isinstance(parsed, dict) else {}
    if not isinstance(plugins, dict):
        return frozenset()
    resolved: dict[str, set[str]] = {}
    for alias, declaration in plugins.items():
        if not isinstance(alias, str) or not isinstance(declaration, dict):
            continue
        plugin_id = declaration.get("id")
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            continue
        resolved.setdefault(_catalog_accessor(alias), set()).add(plugin_id)
    plugin_ids: set[str] = set()
    for alias in aliases:
        matches = resolved.get(alias, set())
        if len(matches) == 1:
            plugin_ids.update(matches)
    return frozenset(plugin_ids)


def _gradle_plugin_resolution(
    text: str,
    root: str,
    by_path: dict[str, _Candidate],
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Resolve literal IDs plus the nearest checked-in default version catalog."""

    plugin_ids = set(_gradle_plugin_ids(text))
    aliases = _gradle_plugin_aliases(text)
    if not aliases:
        return frozenset(plugin_ids), ()

    current = root
    while True:
        catalog_path = _join(current, "gradle/libs.versions.toml")
        catalog = by_path.get(catalog_path)
        if catalog is not None:
            catalog_ids = _catalog_plugin_ids(catalog.parsed, aliases)
            if catalog_ids:
                plugin_ids.update(catalog_ids)
                return frozenset(plugin_ids), (catalog_path,)
            return frozenset(plugin_ids), ()
        if current == ".":
            break
        current = _parent(current)
    return frozenset(plugin_ids), ()


def _pbx_without_comments(text: str) -> str:
    cleaned = list(text)
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(text):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            for cursor in range(index, end):
                if text[cursor] not in "\r\n":
                    cleaned[cursor] = " "
            index = end
            continue
        if text.startswith("//", index):
            end = index + 2
            while end < len(text) and text[end] not in "\r\n":
                end += 1
            for cursor in range(index, end):
                cleaned[cursor] = " "
            index = end
            continue
        index += 1
    return "".join(cleaned)


def _pbx_matching_brace(text: str, opening: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _pbx_has_application_target(text: str) -> bool:
    cleaned = _pbx_without_comments(text)
    objects = re.search(r"(?m)^\s*objects\s*=\s*\{", cleaned)
    if objects is None:
        return False
    objects_open = cleaned.find("{", objects.start(), objects.end())
    if objects_open < 0:
        return False
    objects_close = _pbx_matching_brace(cleaned, objects_open)
    if objects_close < 0:
        return False

    object_start = re.compile(r"(?m)^\s*[A-Za-z0-9_]+\s*=\s*\{")
    cursor = objects_open + 1
    while cursor < objects_close:
        match = object_start.search(cleaned, cursor, objects_close)
        if match is None:
            break
        opening = cleaned.find("{", match.start(), match.end())
        if opening < 0:
            return False
        closing = _pbx_matching_brace(cleaned, opening)
        if closing < 0 or closing > objects_close:
            return False
        block = cleaned[opening + 1 : closing]
        if (
            re.search(r"\bisa\s*=\s*PBXNativeTarget\s*;", block)
            and re.search(
                r"\bproductType\s*=\s*['\"]?"
                r"com\.apple\.product-type\.application"
                r"(?:\.[A-Za-z0-9.-]+)?['\"]?\s*;",
                block,
            )
        ):
            return True
        cursor = closing + 1
    return False


def _desktop_owner(
    module_root: str,
    owned_surfaces: dict[str, set[str]],
) -> str | None:
    if module_root in owned_surfaces:
        return module_root
    matches = {
        desktop_root
        for desktop_root, surfaces in owned_surfaces.items()
        if any(_is_under(module_root, surface) for surface in surfaces)
    }
    if not matches:
        return None
    return max(
        matches,
        key=lambda root: 0 if root == "." else len(PurePosixPath(root).parts),
    )


def _classify(
    candidates: tuple[_Candidate, ...], regular_paths: frozenset[str]
) -> dict[str, _ModuleFacts]:
    modules: dict[str, _ModuleFacts] = {}
    by_path = {candidate.path: candidate for candidate in candidates}
    desktop_surfaces: dict[str, set[str]] = {}

    for candidate in candidates:
        if PurePosixPath(candidate.path).name != "tauri.conf.json":
            continue
        config_parent = _parent(candidate.path)
        if PurePosixPath(config_parent).name != "src-tauri":
            continue
        if not _is_tauri_config(candidate.parsed):
            continue
        desktop_root = _parent(config_parent)
        cargo_path = _join(desktop_root, "src-tauri/Cargo.toml")
        cargo = by_path.get(cargo_path)
        if cargo is None or "tauri" not in _cargo_dependencies(cargo.parsed):
            continue
        _add(
            modules,
            desktop_root,
            "xy-desktop",
            (candidate.path, cargo.path),
            ("desktop:tauri", "language:rust"),
        )
        desktop_surfaces.setdefault(desktop_root, set()).update(
            {
                _join(desktop_root, "frontend"),
                _join(desktop_root, "src"),
                _join(desktop_root, "src-tauri"),
            }
        )

    for candidate in candidates:
        if PurePosixPath(candidate.path).name != "package.json":
            continue
        evidence = _electron_application_evidence(candidate, regular_paths)
        if not evidence:
            continue
        root = _parent(candidate.path)
        _add(
            modules,
            root,
            "xy-desktop",
            evidence,
            ("desktop:electron", "language:javascript", "runtime:node"),
        )
        owned = desktop_surfaces.setdefault(root, set())
        owned.update(
            _join(root, relative)
            for relative in (
                "electron",
                "main",
                "preload",
                "renderer",
                "src",
            )
        )
        for evidence_path in evidence:
            if evidence_path == candidate.path:
                continue
            evidence_parent = _parent(evidence_path)
            if evidence_parent != root:
                owned.add(evidence_parent)

    def add_classification(
        root: str,
        role: str,
        evidence: tuple[str, ...],
        facts: tuple[str, ...],
        *,
        collapse_into_desktop: bool = False,
    ) -> None:
        if collapse_into_desktop:
            desktop_root = _desktop_owner(root, desktop_surfaces)
            if desktop_root is not None:
                _add(modules, desktop_root, "xy-desktop", evidence, facts)
                return
        _add(modules, root, role, evidence, facts)

    android_manifests = {
        candidate.path
        for candidate in candidates
        if PurePosixPath(candidate.path).name == "AndroidManifest.xml"
        and isinstance(candidate.parsed, ElementTree.Element)
        and candidate.parsed.tag.rsplit("}", 1)[-1] == "manifest"
    }
    for candidate in candidates:
        path = PurePosixPath(candidate.path)
        name = path.name
        root = _parent(candidate.path)
        if name == "package.json":
            dependencies = _package_dependencies(
                candidate.parsed, RUNTIME_PACKAGE_DEPENDENCY_SECTIONS
            )
            web_facts = {
                fact for dependency, fact in WEB_FRAMEWORKS if dependency in dependencies
            }
            backend_facts = {
                fact
                for dependency, fact in NODE_BACKEND_FRAMEWORKS
                if dependency in dependencies
            }
            if web_facts:
                add_classification(
                    root,
                    "xy-web",
                    (candidate.path,),
                    tuple((*web_facts, "language:javascript")),
                    collapse_into_desktop=True,
                )
            if backend_facts:
                add_classification(
                    root,
                    "xy-backend",
                    (candidate.path,),
                    tuple(
                        (*backend_facts, "language:javascript", "runtime:node")
                    ),
                    collapse_into_desktop=True,
                )
        elif name == "pyproject.toml":
            add_classification(
                root,
                "xy-backend",
                (candidate.path,),
                ("language:python",),
                collapse_into_desktop=True,
            )
        elif name == "pom.xml":
            add_classification(
                root,
                "xy-backend",
                (candidate.path,),
                ("language:java",),
                collapse_into_desktop=True,
            )
        elif name == "Package.swift":
            add_classification(
                root,
                "xy-backend",
                (candidate.path,),
                ("language:swift",),
                collapse_into_desktop=True,
            )
        elif name in {"build.gradle", "build.gradle.kts"}:
            text = candidate.parsed
            manifest_path = _join(root, "src/main/AndroidManifest.xml")
            plugin_ids, catalog_evidence = _gradle_plugin_resolution(
                text, root, by_path
            )
            if (
                plugin_ids & ANDROID_PLUGIN_IDS
                and manifest_path in android_manifests
            ):
                add_classification(
                    root,
                    "xy-android",
                    (candidate.path, *catalog_evidence, manifest_path),
                    (
                        "platform:android",
                        "language:kotlin" if "kotlin" in text else "language:java",
                    ),
                    collapse_into_desktop=True,
                )
            else:
                language = (
                    "language:kotlin"
                    if "kotlin" in text or name.endswith(".kts")
                    else "language:java"
                )
                add_classification(
                    root,
                    "xy-backend",
                    (candidate.path, *catalog_evidence),
                    (language,),
                    collapse_into_desktop=True,
                )
        elif name == "go.mod":
            add_classification(
                root,
                "xy-backend",
                (candidate.path,),
                ("language:go",),
                collapse_into_desktop=True,
            )
        elif name == "Cargo.toml":
            add_classification(
                root,
                "xy-backend",
                (candidate.path,),
                ("language:rust",),
                collapse_into_desktop=True,
            )
        elif name == "composer.json":
            add_classification(
                root,
                "xy-backend",
                (candidate.path,),
                ("language:php",),
                collapse_into_desktop=True,
            )
        elif name == "openapi.json":
            document = candidate.parsed
            dockerfile = _join(root, "Dockerfile")
            if (
                isinstance(document, dict)
                and isinstance(document.get("openapi"), str)
                and re.fullmatch(r"3(?:\.\d+){1,2}", document["openapi"])
                and isinstance(document.get("info"), dict)
                and isinstance(document["info"].get("title"), str)
                and isinstance(document["info"].get("version"), str)
                and isinstance(document.get("paths"), dict)
                and bool(document["paths"])
                and dockerfile in regular_paths
            ):
                add_classification(
                    root,
                    "xy-backend",
                    (candidate.path, dockerfile),
                    ("contract:openapi", "service:language-neutral"),
                    collapse_into_desktop=True,
                )
        elif name in {"CMakeLists.txt", "meson.build"}:
            add_classification(
                root,
                "xy-backend",
                (candidate.path,),
                ("language:c-cpp",),
                collapse_into_desktop=True,
            )
        elif name.endswith(".csproj"):
            add_classification(
                root,
                "xy-backend",
                (candidate.path,),
                ("language:csharp",),
                collapse_into_desktop=True,
            )
        elif name == "project.pbxproj" and path.parent.name.endswith(".xcodeproj"):
            if _pbx_has_application_target(candidate.parsed):
                project_root = _parent(path.parent.as_posix())
                add_classification(
                    project_root,
                    "xy-apple",
                    (candidate.path,),
                    ("platform:apple",),
                    collapse_into_desktop=True,
                )

    return modules


def _primary_role(roles: set[str]) -> str:
    for role in ("xy-desktop", "xy-apple", "xy-android", "xy-web", "xy-backend"):
        if role in roles:
            return role
    raise DiscoveryError("module facts do not contain a supported primary role")


_SCRIPT_PURPOSES = {
    "lint": "lint",
    "typecheck": "typecheck",
    "type-check": "typecheck",
    "check": "typecheck",
    "test": "test",
    "build": "build",
    "package": "package",
    "make": "package",
    "dist": "package",
    "tauri:build": "package",
    "verify": "release-verification",
}
_SAFE_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]*$")


def _owning_module_root(
    path: str, modules: dict[str, _ModuleFacts]
) -> str | None:
    matches = tuple(root for root in modules if _is_under(path, root))
    if not matches:
        return None
    return max(
        matches,
        key=lambda root: 0 if root == "." else len(PurePosixPath(root).parts),
    )


def _relative_to_module(path: str, module_root: str) -> str:
    if module_root == ".":
        return path
    return PurePosixPath(path).relative_to(module_root).as_posix()


def _command(
    purpose: str, argv: tuple[str, ...], evidence: tuple[str, ...]
) -> VerificationCommand:
    return VerificationCommand(purpose, argv, evidence)


def _javascript_manager(
    root: str, parsed: dict[str, Any], regular_paths: frozenset[str]
) -> tuple[str, tuple[str, ...]]:
    declared = parsed.get("packageManager")
    manager = ""
    if isinstance(declared, str):
        match = re.match(r"^(npm|pnpm|yarn|bun)@", declared.strip())
        if match is not None:
            manager = match.group(1)

    lock_candidates = (
        ("bun", "bun.lock"),
        ("bun", "bun.lockb"),
        ("pnpm", "pnpm-lock.yaml"),
        ("yarn", "yarn.lock"),
        ("npm", "npm-shrinkwrap.json"),
        ("npm", "package-lock.json"),
    )
    lock_by_manager = {
        candidate_manager: _join(root, name)
        for candidate_manager, name in lock_candidates
        if _join(root, name) in regular_paths
    }
    if not manager:
        manager = next(
            (
                candidate_manager
                for candidate_manager, _ in lock_candidates
                if candidate_manager in lock_by_manager
            ),
            "npm",
        )
    evidence = [
        lock_by_manager[manager]
    ] if manager in lock_by_manager else []
    return manager, tuple(evidence)


def _javascript_argv(
    manager: str, script: str, package_root: str, module_root: str
) -> tuple[str, ...]:
    if package_root == module_root:
        return (manager, "run", script)
    relative = _relative_to_module(package_root, module_root)
    if manager == "pnpm":
        return (manager, "--dir", relative, "run", script)
    option = "--prefix" if manager == "npm" else "--cwd"
    return (manager, option, relative, "run", script)


def _nearest_wrapper(
    module_root: str,
    name: str,
    regular_paths: frozenset[str],
) -> tuple[str, str] | None:
    """Return an argv-safe relative wrapper and its checked-in evidence path."""

    module_path = PurePosixPath(module_root)
    ancestors = (module_path, *module_path.parents)
    for ancestor in ancestors:
        ancestor_root = ancestor.as_posix()
        candidate = _join(ancestor_root, name)
        if candidate not in regular_paths:
            continue
        distance = len(module_path.parts) - (
            0 if ancestor_root == "." else len(ancestor.parts)
        )
        executable = PurePosixPath(*(("..",) * distance), name).as_posix()
        if distance == 0:
            executable = f"./{executable}"
        return executable, candidate
    return None


def _wrapper_argv_from_owner(
    wrapper_path: str,
    owner_root: str,
) -> str:
    wrapper = PurePosixPath(wrapper_path)
    owner = PurePosixPath(owner_root)
    wrapper_parent = wrapper.parent
    owner_parts = () if owner_root == "." else owner.parts
    parent_parts = () if wrapper_parent.as_posix() == "." else wrapper_parent.parts
    common = 0
    while (
        common < len(owner_parts)
        and common < len(parent_parts)
        and owner_parts[common] == parent_parts[common]
    ):
        common += 1
    relative = PurePosixPath(
        *(("..",) * (len(owner_parts) - common)),
        *parent_parts[common:],
        wrapper.name,
    ).as_posix()
    return relative if relative.startswith("../") else f"./{relative}"


def _dependency_list_contains(values: Any, package: str) -> bool:
    if not isinstance(values, list):
        return False
    pattern = re.compile(
        rf"^\s*{re.escape(package)}(?:\[[^\]]+\])?(?:\s|[<>=!~^;@]|$)",
        flags=re.IGNORECASE,
    )
    return any(isinstance(value, str) and pattern.match(value) for value in values)


def _python_declares_pytest(parsed: dict[str, Any]) -> bool:
    project = parsed.get("project", {})
    if isinstance(project, dict):
        if _dependency_list_contains(project.get("dependencies"), "pytest"):
            return True
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict) and any(
            _dependency_list_contains(values, "pytest")
            for values in optional.values()
        ):
            return True

    poetry = parsed.get("tool", {}).get("poetry", {})
    if not isinstance(poetry, dict):
        return False
    dependencies = poetry.get("dependencies", {})
    if isinstance(dependencies, dict) and any(
        str(key).casefold() == "pytest" for key in dependencies
    ):
        return True
    groups = poetry.get("group", {})
    return isinstance(groups, dict) and any(
        isinstance(group, dict)
        and isinstance(group.get("dependencies"), dict)
        and any(
            str(key).casefold() == "pytest"
            for key in group["dependencies"]
        )
        for group in groups.values()
    )


def _composer_declares(parsed: dict[str, Any], package: str) -> bool:
    expected = package.casefold()
    for section in ("require", "require-dev"):
        dependencies = parsed.get(section, {})
        if isinstance(dependencies, dict) and any(
            str(key).casefold() == expected for key in dependencies
        ):
            return True
    return False


def _preset_names(parsed: Any, key: str) -> tuple[str, ...]:
    values = parsed.get(key, ()) if isinstance(parsed, dict) else ()
    if not isinstance(values, list):
        return ()
    return tuple(
        sorted(
            {
                name
                for value in values
                if isinstance(value, dict)
                and isinstance((name := value.get("name")), str)
                and name.strip()
                and "\x00" not in name
            }
        )
    )


def _discover_verification_commands(
    candidates: tuple[_Candidate, ...],
    regular_paths: frozenset[str],
    modules: dict[str, _ModuleFacts],
) -> dict[str, tuple[VerificationCommand, ...]]:
    commands: dict[str, set[VerificationCommand]] = {
        root: set() for root in modules
    }
    by_path = {candidate.path: candidate for candidate in candidates}

    def add(
        path: str,
        purpose: str,
        argv: tuple[str, ...],
        evidence: tuple[str, ...],
    ) -> None:
        owner = _owning_module_root(path, modules)
        if owner is not None:
            commands[owner].add(_command(purpose, argv, evidence))

    for candidate in candidates:
        path = PurePosixPath(candidate.path)
        name = path.name
        root = _parent(candidate.path)
        owner = _owning_module_root(root, modules)
        if owner is None:
            continue

        if name == "package.json":
            scripts = candidate.parsed.get("scripts", {})
            if not isinstance(scripts, dict):
                continue
            manager, manager_evidence = _javascript_manager(
                root, candidate.parsed, regular_paths
            )
            evidence = (candidate.path, *manager_evidence)
            for script, body in scripts.items():
                if (
                    not isinstance(script, str)
                    or not isinstance(body, str)
                    or not body.strip()
                    or _SAFE_SCRIPT_NAME.fullmatch(script) is None
                ):
                    continue
                purpose = _SCRIPT_PURPOSES.get(script)
                if purpose is None and script.startswith("test:"):
                    purpose = "test"
                if purpose is None:
                    continue
                add(
                    root,
                    purpose,
                    _javascript_argv(manager, script, root, owner),
                    evidence,
                )
            continue

        if name == "pom.xml":
            wrapper = _nearest_wrapper(root, "mvnw", regular_paths)
            executable = (
                _wrapper_argv_from_owner(wrapper[1], owner)
                if wrapper is not None
                else "mvn"
            )
            evidence = (
                (candidate.path, wrapper[1])
                if wrapper is not None
                else (candidate.path,)
            )
            selector = (
                ("-f", _relative_to_module(candidate.path, owner))
                if root != owner
                else ()
            )
            add(root, "test", (executable, *selector, "test"), evidence)
            add(root, "build", (executable, *selector, "package"), evidence)
            continue

        if name in {"build.gradle", "build.gradle.kts"}:
            plugin_ids, catalog_evidence = _gradle_plugin_resolution(
                candidate.parsed, root, by_path
            )
            wrapper = _nearest_wrapper(root, "gradlew", regular_paths)
            executable = (
                _wrapper_argv_from_owner(wrapper[1], owner)
                if wrapper is not None
                else "gradle"
            )
            evidence = (
                (candidate.path, *catalog_evidence, wrapper[1])
                if wrapper is not None
                else (candidate.path, *catalog_evidence)
            )
            selector = (
                ("--project-dir", _relative_to_module(root, owner))
                if root != owner
                else ()
            )
            android = bool(
                plugin_ids & ANDROID_PLUGIN_IDS
            )
            if android:
                add(
                    root,
                    "build",
                    (executable, *selector, "assembleDebug"),
                    evidence,
                )
                add(
                    root,
                    "test",
                    (executable, *selector, "testDebugUnitTest"),
                    evidence,
                )
            elif plugin_ids & {
                "java",
                "java-library",
                "application",
                "org.jetbrains.kotlin.jvm",
            }:
                add(root, "build", (executable, *selector, "build"), evidence)
                add(root, "test", (executable, *selector, "test"), evidence)
            continue

        if name == "pyproject.toml" and _python_declares_pytest(candidate.parsed):
            uv_lock = _join(root, "uv.lock")
            poetry_lock = _join(root, "poetry.lock")
            if uv_lock in regular_paths:
                add(
                    root,
                    "test",
                    ("uv", "run", "pytest"),
                    (candidate.path, uv_lock),
                )
            elif poetry_lock in regular_paths and isinstance(
                candidate.parsed.get("tool", {}).get("poetry"), dict
            ):
                add(
                    root,
                    "test",
                    ("poetry", "run", "pytest"),
                    (candidate.path, poetry_lock),
                )
            continue

        if name == "Cargo.toml" and isinstance(
            candidate.parsed.get("package"), dict
        ):
            if root == owner:
                suffix: tuple[str, ...] = ()
            else:
                suffix = (
                    "--manifest-path",
                    _relative_to_module(candidate.path, owner),
                )
            add(root, "build", ("cargo", "build", *suffix), (candidate.path,))
            add(root, "test", ("cargo", "test", *suffix), (candidate.path,))
            continue

        if name == "go.mod":
            add(root, "build", ("go", "build", "./..."), (candidate.path,))
            add(root, "test", ("go", "test", "./..."), (candidate.path,))
            continue

        if name == "composer.json":
            scripts = candidate.parsed.get("scripts", {})
            if (
                isinstance(scripts, dict)
                and isinstance(scripts.get("test"), str)
                and scripts["test"].strip()
            ):
                add(root, "test", ("composer", "run", "test"), (candidate.path,))
            else:
                configs = tuple(
                    config
                    for config in (
                        _join(root, "phpunit.xml"),
                        _join(root, "phpunit.xml.dist"),
                    )
                    if config in regular_paths
                )
                if configs and _composer_declares(
                    candidate.parsed, "phpunit/phpunit"
                ):
                    add(
                        root,
                        "test",
                        ("vendor/bin/phpunit",),
                        (candidate.path, *configs),
                    )
            continue

        if name.endswith(".csproj"):
            project_name = name
            add(
                root,
                "build",
                ("dotnet", "build", project_name),
                (candidate.path,),
            )
            if any(
                "Microsoft.NET.Test.Sdk" in value
                for value in candidate.parsed.itertext()
            ):
                add(
                    root,
                    "test",
                    ("dotnet", "test", project_name),
                    (candidate.path,),
                )
            continue

        if name == "CMakePresets.json":
            cmake_path = _join(root, "CMakeLists.txt")
            if cmake_path not in by_path:
                continue
            evidence = (cmake_path, candidate.path)
            for preset in _preset_names(candidate.parsed, "configurePresets"):
                add(root, "configure", ("cmake", "--preset", preset), evidence)
            for preset in _preset_names(candidate.parsed, "buildPresets"):
                add(
                    root,
                    "build",
                    ("cmake", "--build", "--preset", preset),
                    evidence,
                )
            for preset in _preset_names(candidate.parsed, "testPresets"):
                add(root, "test", ("ctest", "--preset", preset), evidence)
            continue

        if name == "meson.build":
            if re.search(r"(?m)^\s*test\s*\(", candidate.parsed):
                add(
                    root,
                    "configure",
                    ("meson", "setup", "builddir"),
                    (candidate.path,),
                )
                add(
                    root,
                    "test",
                    ("meson", "test", "-C", "builddir"),
                    (candidate.path,),
                )

    for module_root in modules:
        prefix = "" if module_root == "." else f"{module_root}/"
        project_paths = tuple(
            candidate.path
            for candidate in candidates
            if candidate.path.startswith(prefix)
            and PurePosixPath(candidate.path).name == "project.pbxproj"
            and _owning_module_root(_parent(candidate.path), modules) == module_root
        )
        for project_path in project_paths:
            project_dir = PurePosixPath(project_path).parent.as_posix()
            scheme_prefix = f"{project_dir}/xcshareddata/xcschemes/"
            for scheme_path in sorted(regular_paths):
                if not (
                    scheme_path.startswith(scheme_prefix)
                    and scheme_path.endswith(".xcscheme")
                ):
                    continue
                scheme = PurePosixPath(scheme_path).stem
                add(
                    module_root,
                    "build",
                    ("xcodebuild", "-scheme", scheme, "build"),
                    (project_path, scheme_path),
                )

    return {
        root: tuple(
            sorted(
                values,
                key=lambda item: (item.purpose, item.argv, item.evidence_paths),
            )
        )
        for root, values in commands.items()
    }


def discover_project(
    root: str | os.PathLike[str], overrides: DiscoveryOverrides | None = None
) -> ProjectProfile:
    """Discover a deterministic in-memory profile without modifying the project."""

    _require_secure_capabilities()
    project_root = Path(root)
    root_fd = _open_project_root(project_root)
    try:
        module_overrides, exclusions = _validated_overrides(root_fd, overrides)
        candidates, regular_paths = _Scanner(exclusions).scan(root_fd)
    finally:
        os.close(root_fd)

    modules = _classify(candidates, regular_paths)
    for module_root, role in module_overrides.items():
        facts = _module_facts(modules, module_root)
        facts.roles = {role}
        facts.facts.add("override:explicit-role")

    verification_commands = _discover_verification_commands(
        candidates, regular_paths, modules
    )
    profiles = tuple(
        ModuleProfile(
            root=module_root,
            primary_role=_primary_role(facts.roles),
            evidence_paths=tuple(sorted(facts.evidence)),
            stack_facts=tuple(sorted(facts.facts)),
            verification_commands=verification_commands[module_root],
        )
        for module_root, facts in sorted(modules.items())
    )
    # 需求/原型可先于生产清单出现；UI/UX 与 QA 属于通用工作角色，始终可用。
    # 实现角色仍严格来自模块事实；拥有角色文件不代表任务获批或必须派发该角色。
    enabled = {"xy-qa", "xy-uiux"}
    enabled.update(module.primary_role for module in profiles)
    diagnostics = () if profiles else ("no implementation modules detected",)
    return ProjectProfile(
        modules=profiles,
        enabled_roles=tuple(sorted(enabled)),
        diagnostics=diagnostics,
    )


__all__ = (
    "DiscoveryError",
    "DiscoveryOverrides",
    "ModuleOverride",
    "ModuleProfile",
    "ProjectProfile",
    "VerificationCommand",
    "discover_project",
)
