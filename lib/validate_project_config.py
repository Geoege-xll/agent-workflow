#!/usr/bin/env python3
"""Validate the portable project.yaml subset before setup writes anything."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from pathlib import PurePosixPath

# Validation and profile queries are read-only operations, including when invoked in
# a freshly copied pack that has no bytecode cache yet.
sys.dont_write_bytecode = True

try:
    from .workflow_hook_settings import hook_mode
    from .worktree_policy import WorktreePolicyError, settings as worktree_settings
    from .project_discovery import (
        DiscoveryError,
        DiscoveryOverrides,
        ModuleOverride,
        ProjectProfile,
        discover_project,
    )
except ImportError:
    from workflow_hook_settings import hook_mode
    from worktree_policy import WorktreePolicyError, settings as worktree_settings
    from project_discovery import (  # type: ignore[no-redef]
        DiscoveryError,
        DiscoveryOverrides,
        ModuleOverride,
        ProjectProfile,
        discover_project,
    )


POSITIVE_ORCHESTRATION_KEYS = {
    "max_concurrent_subagents",
    "max_parallel_writers",
    "max_writers_per_path",
    "max_depth",
}
MEMORY_KEYS = {
    "provider",
    "mode",
    "isolation",
    "project_id",
    "qa_requires_provider",
    "portable_checkpoint",
    "fallback_dir",
}
CANONICAL_DOC_FILE_KEYS = {
    "standards",
    "project",
}
UI_DOC_FILE_KEYS: set[str] = set()
CANONICAL_DOC_DIR_KEYS = {"standards_root", "features", "plans", "notes"}
DOC_FILE_KEYS = CANONICAL_DOC_FILE_KEYS | UI_DOC_FILE_KEYS
DOC_DIR_KEYS = CANONICAL_DOC_DIR_KEYS
DOC_KEYS = DOC_FILE_KEYS | DOC_DIR_KEYS
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$")
DOC_PATH_RE = re.compile(r"^docs/[A-Za-z0-9_./-]+$")
MANAGED_OUTPUT_PATHS = {
    Path("AGENTS.md"),
    Path(".codex/config.toml"),
    Path(".codex/agents"),
    Path(".agents/skills"),
}
ANTIGRAVITY_CORE_SKILLS = {
    "grill-me",
    "xy-build-verify",
    "xy-plan",
    "xy-project-memory",
    "xy-prototype-verify",
    "xy-qa-review",
    "xy-workflow",
}
MANAGED_OUTPUT_DIRECTORIES = {
    Path("docs"),
    Path(".codex"),
    Path(".codex/agents"),
    Path(".agents"),
    Path(".agents/skills"),
}
MANAGED_OUTPUT_FILES = {
    Path("AGENTS.md"),
    Path(".codex/config.toml"),
}
RETIRED_WORKSPACE_KEYS = frozenset(
    {"sandboxes", "enabled_roles", "commands", "role_reads"}
)


@dataclass(frozen=True)
class ValidationResult:
    """Validated configuration plus its immutable, read-only discovery profile."""

    errors: tuple[str, ...]
    profile: ProjectProfile | None


def strip_inline_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in {'"', "'"}:
            quote = None if quote == char else char if quote is None else quote
            continue
        if char == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.strip()


def parse_project_name(value: str) -> str:
    """按字符串读取项目显示名，供安装器和两条文档生成路径共同使用。

    安装器使用 JSON 双引号字符串（也是合法 YAML）保存目录名；这里必须解码
    引号和反斜杠，不能仅 strip 引号，否则名称中的特殊字符会在文档里失真。
    手工配置仍支持普通标量、YAML 单引号及行内注释，不推断或改写项目身份。
    """
    value = strip_inline_comment(value)
    if value.startswith('"'):
        return json.loads(value)
    if value.startswith("'"):
        match = re.fullmatch(r"'((?:[^']|'')*)'", value)
        if match is None:
            raise ValueError("project_name must be a valid single-quoted string")
        return match.group(1).replace("''", "'")
    return value


def section_lines(lines: list[str], name: str) -> list[str]:
    start: int | None = None
    for index, raw in enumerate(lines):
        if re.match(rf"^{re.escape(name)}:\s*(?:#.*)?$", raw):
            start = index + 1
            break
    if start is None:
        return []
    result: list[str] = []
    for raw in lines[start:]:
        if raw and not raw.startswith((" ", "#")):
            break
        result.append(raw)
    return result


def path_has_symlink(root: Path, relative: Path) -> bool:
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def validate_docs(lines: list[str], root: Path, errors: list[str]) -> dict[str, str]:
    docs: dict[str, str] = {}
    seen: set[str] = set()
    for raw in section_lines(lines, "docs"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = re.match(r"^  ([A-Za-z0-9_]+):\s*(.*?)\s*$", raw)
        if not match:
            errors.append(f"malformed docs entry: {raw.strip()}")
            continue
        key, value = match.group(1), strip_inline_comment(match.group(2)).strip('"\'')
        if key in seen:
            errors.append(f"duplicate docs key: {key}")
            continue
        seen.add(key)
        if key not in DOC_KEYS:
            errors.append(f"unsupported docs key: {key}")
            continue
        if not value:
            errors.append(f"docs.{key} must not be empty")
            continue
        docs[key] = value

    # PROJECT.md 与 STANDARDS.md 分别是“当前项目事实”和“当前项目规范”的唯一入口；
    # features/ 与 standards_root/ 保存可按需读取的详细叶文档。旧 engineering /
    # design_system 双入口不再接受，避免同一规则出现两份权威。
    required = CANONICAL_DOC_FILE_KEYS | {
        "standards_root",
        "features",
        "plans",
        "notes",
    }
    missing = sorted(required - docs.keys())
    if missing:
        errors.append(f"docs missing keys: {', '.join(missing)}")

    for key, value in sorted(docs.items()):
        relative = Path(value)
        resolved = (root / relative).resolve()
        unsafe = (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or len(relative.parts) < 2
            or relative.parts[0] != "docs"
            or not DOC_PATH_RE.fullmatch(value)
            or any(part.startswith(".") for part in relative.parts)
            or not resolved.is_relative_to(root)
            or path_has_symlink(root, relative)
        )
        if unsafe:
            errors.append(f"docs.{key} must be a non-hidden path under docs/: {value}")
            continue
        target = root / relative
        if key in DOC_FILE_KEYS:
            if relative.suffix != ".md":
                errors.append(f"docs.{key} must be a Markdown file: {value}")
            if target.exists() and not target.is_file():
                errors.append(f"docs.{key} must resolve to a regular file: {value}")
        else:
            if target.exists() and not target.is_dir():
                errors.append(f"docs.{key} must resolve to a directory: {value}")

    file_keys_by_path: dict[Path, set[str]] = {}
    for key in DOC_FILE_KEYS:
        if key in docs:
            file_keys_by_path.setdefault(Path(docs[key]), set()).add(key)
    for path, keys in sorted(file_keys_by_path.items(), key=lambda item: str(item[0])):
        if len(keys) > 1:
            errors.append(
                f"docs file path has conflicting keys {', '.join(sorted(keys))}: {path}"
            )

    directory_keys_by_path: dict[Path, set[str]] = {}
    for key in DOC_DIR_KEYS:
        if key in docs:
            directory_keys_by_path.setdefault(Path(docs[key]), set()).add(key)
    for path, keys in sorted(
        directory_keys_by_path.items(), key=lambda item: str(item[0])
    ):
        if len(keys) > 1:
            errors.append(
                f"docs directory path has conflicting keys {', '.join(sorted(keys))}: "
                f"{path}"
            )

    file_paths = set(file_keys_by_path)
    directory_paths = set(directory_keys_by_path)
    for directory in sorted(directory_paths, key=str):
        if directory in file_paths:
            errors.append(f"docs path cannot be both file and directory: {directory}")
        for file_path in sorted(file_paths, key=str):
            if file_path in directory.parents:
                errors.append(
                    f"docs file path cannot be an ancestor of a directory path: "
                    f"{file_path} -> {directory}"
                )
    ordered_directories = sorted(directory_paths, key=str)
    for index, first in enumerate(ordered_directories):
        for second in ordered_directories[index + 1 :]:
            if first in second.parents or second in first.parents:
                errors.append(
                    f"configured docs directories must not overlap: {first}, {second}"
                )
    return docs


def _top_level_entries(lines: list[str]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    pattern = re.compile(
        r"^(?:([A-Za-z_][A-Za-z0-9_]*)|['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]):"
        r"\s*(.*?)\s*$"
    )
    for raw in lines:
        match = pattern.match(raw)
        if match:
            entries.append((match.group(1) or match.group(2), match.group(3)))
    return entries


def _normalized_overlap(first: str, second: str) -> bool:
    first_path = PurePosixPath(first)
    second_path = PurePosixPath(second)
    return first_path in second_path.parents or second_path in first_path.parents


def _validate_nonoverlapping(paths: list[str], label: str, errors: list[str]) -> None:
    ordered = sorted(set(paths))
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if _normalized_overlap(first, second):
                errors.append(f"workspace_overrides.{label} roots must not overlap: {first}, {second}")


def validate_workspace(
    lines: list[str], errors: list[str]
) -> DiscoveryOverrides | None:
    """Parse only the intentionally tiny workspace configuration surface."""

    top_level = _top_level_entries(lines)
    for retired in sorted(RETIRED_WORKSPACE_KEYS):
        if any(key == retired for key, _ in top_level):
            errors.append(f"unsupported retired top-level key: {retired}")

    workspace_entries = [value for key, value in top_level if key == "workspace"]
    if len(workspace_entries) != 1:
        errors.append("workspace must appear exactly once as a top-level mapping")
    elif strip_inline_comment(workspace_entries[0]):
        errors.append("workspace must be a mapping containing discovery: auto")
    else:
        discovery_values: list[str] = []
        for raw in section_lines(lines, "workspace"):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"  ([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*", raw)
            if match is None:
                errors.append(f"malformed workspace entry: {raw.strip()}")
                continue
            key, value = match.group(1), strip_inline_comment(match.group(2)).strip('"\'')
            if key != "discovery":
                errors.append(f"unsupported workspace key: {key}")
            else:
                discovery_values.append(value)
        if len(discovery_values) != 1 or discovery_values[0] != "auto":
            errors.append("workspace.discovery must be auto")

    override_entries = [value for key, value in top_level if key == "workspace_overrides"]
    if len(override_entries) > 1:
        errors.append("workspace_overrides must appear at most once")
        return None
    if not override_entries:
        return DiscoveryOverrides()
    inline = strip_inline_comment(override_entries[0])
    if inline:
        if inline == "{}":
            return DiscoveryOverrides()
        errors.append("workspace_overrides must be a mapping")
        return None

    include_values: list[tuple[str, str]] = []
    exclude_values: list[str] = []
    seen_sections: set[str] = set()
    current: str | None = None
    for raw in section_lines(lines, "workspace_overrides"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        section = re.fullmatch(r"  (include|exclude):\s*(.*?)\s*", raw)
        if section:
            current = section.group(1)
            if current in seen_sections:
                errors.append(f"duplicate workspace_overrides key: {current}")
            seen_sections.add(current)
            value = strip_inline_comment(section.group(2))
            if value:
                expected = "mapping" if current == "include" else "block list"
                errors.append(f"workspace_overrides.{current} must be a {expected}")
            continue
        if current == "include":
            item = re.fullmatch(r"    ([^:#][^:]*?):\s*(.*?)\s*", raw)
            if item:
                path = item.group(1).strip().strip('"\'')
                role = strip_inline_comment(item.group(2)).strip('"\'')
                include_values.append((path, role))
                continue
        elif current == "exclude":
            item = re.fullmatch(r"    -\s+(.+?)\s*", raw)
            if item:
                exclude_values.append(
                    strip_inline_comment(item.group(1)).strip('"\'')
                )
                continue
        errors.append(f"malformed workspace_overrides entry: {raw.strip()}")

    normalized_roles: dict[str, str] = {}
    module_roles: list[ModuleOverride] = []
    for path, role in include_values:
        try:
            override = ModuleOverride(path, role)
        except (TypeError, ValueError, DiscoveryError) as exc:
            errors.append(str(exc))
            continue
        previous = normalized_roles.get(override.root)
        if previous is not None:
            if previous == override.primary_role:
                errors.append(f"duplicate normalized include root: {override.root}")
            else:
                errors.append(
                    "conflicting role assignments for normalized include root: "
                    f"{override.root}"
                )
            continue
        normalized_roles[override.root] = override.primary_role
        module_roles.append(override)

    normalized_excludes: list[str] = []
    for path in exclude_values:
        try:
            candidate = DiscoveryOverrides(exclude_roots=(path,)).exclude_roots[0]
        except (TypeError, ValueError, DiscoveryError) as exc:
            errors.append(str(exc))
            continue
        if candidate in normalized_excludes:
            errors.append(f"duplicate normalized exclude root: {candidate}")
            continue
        normalized_excludes.append(candidate)

    _validate_nonoverlapping(list(normalized_roles), "include", errors)
    _validate_nonoverlapping(normalized_excludes, "exclude", errors)
    try:
        return DiscoveryOverrides(tuple(module_roles), tuple(normalized_excludes))
    except (TypeError, ValueError, DiscoveryError) as exc:
        errors.append(str(exc))
        return None


def validate_with_profile(
    yaml_path: str | PathLike[str],
    project_root: str | PathLike[str],
    roles_dir: str | PathLike[str],
) -> ValidationResult:
    yaml_path = Path(yaml_path)
    project_root = Path(project_root)
    roles_dir = Path(roles_dir)
    text = yaml_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    errors: list[str] = []
    discovery_root = project_root
    root = project_root.resolve()
    profile: ProjectProfile | None = None
    # 共享配置只决定调度/交付策略，不在安装时创建 Git 分支或改写宿主全局设置。
    try:
        hook_mode(text)
    except ValueError as exc:
        errors.append(str(exc))
    try:
        worktree_settings(lines)
    except WorktreePolicyError as exc:
        errors.append(str(exc))
    # 模型偏好独立于编排参数；安装预检与管理器必须使用同一份字段合同。
    try:
        if __package__:
            from .role_models import parse as parse_role_models
        else:
            from role_models import parse as parse_role_models
        parse_role_models(text)
    except ValueError as exc:
        errors.append(str(exc))

    top_level_keys: dict[str, int] = {}
    for key, _ in _top_level_entries(lines):
        top_level_keys[key] = top_level_keys.get(key, 0) + 1
    for key, count in sorted(top_level_keys.items()):
        if count > 1:
            errors.append(f"duplicate top-level key: {key}")

    memory: dict[str, str] = {}
    seen_memory_keys: set[str] = set()
    for raw in section_lines(lines, "memory"):
        match = re.match(r"^\s{2}([A-Za-z0-9_]+):\s*(.*?)\s*$", raw)
        if not match:
            continue
        key, value = match.group(1), strip_inline_comment(match.group(2))
        if key in seen_memory_keys:
            errors.append(f"duplicate memory key: {key}")
            continue
        seen_memory_keys.add(key)
        if key not in MEMORY_KEYS:
            errors.append(f"unsupported memory key: {key}")
            continue
        memory[key] = value.strip('"\'')
    required_memory = set(MEMORY_KEYS)
    missing_memory = sorted(required_memory - memory.keys())
    if missing_memory:
        errors.append(f"memory missing keys: {', '.join(missing_memory)}")
    for key in sorted(required_memory & memory.keys()):
        if not memory[key]:
            errors.append(f"memory.{key} must not be empty")
    if memory.get("provider") not in (None, "agentmemory"):
        errors.append("memory.provider must be agentmemory")
    if memory.get("mode") not in (None, "preferred"):
        errors.append("memory.mode must be preferred")
    if memory.get("isolation") not in (None, "strict"):
        errors.append("memory.isolation must be strict")
    project_id = memory.get("project_id")
    if project_id and not PROJECT_ID_RE.fullmatch(project_id):
        errors.append("memory.project_id must be a stable lowercase slug")
    if memory.get("qa_requires_provider") not in (None, "false"):
        errors.append("memory.qa_requires_provider must be false")

    overrides = validate_workspace(lines, errors)
    if overrides is not None:
        try:
            profile = discover_project(discovery_root, overrides)
        except (DiscoveryError, OSError) as exc:
            errors.append(f"workspace discovery failed: {exc}")
    enabled_roles = profile.enabled_roles if profile is not None else ()
    for role in enabled_roles:
        if not (roles_dir / f"{role}.md").is_file():
            errors.append(f"discovered role has no canonical role file: {role}")
    docs = validate_docs(lines, root, errors)
    checkpoint = memory.get("portable_checkpoint")
    fallback_dir = memory.get("fallback_dir")
    for key, value in (
        ("portable_checkpoint", checkpoint),
        ("fallback_dir", fallback_dir),
    ):
        if value is None:
            continue
        relative = Path(value)
        resolved = (root / relative).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not resolved.is_relative_to(root)
        ):
            errors.append(f"memory.{key} must stay within project root: {value}")
    if checkpoint is not None and checkpoint != docs.get("project"):
        errors.append("memory.portable_checkpoint must match docs.project")
    if fallback_dir is not None and fallback_dir != docs.get("notes"):
        errors.append("memory.fallback_dir must match docs.notes")

    orchestration: dict[str, int] = {}
    for raw in section_lines(lines, "orchestration"):
        match = re.match(r"^\s{2}([A-Za-z0-9_]+):\s*(.*?)\s*$", raw)
        if not match:
            continue
        key, value = match.group(1), strip_inline_comment(match.group(2))
        if key not in POSITIVE_ORCHESTRATION_KEYS:
            continue
        if not re.fullmatch(r"[1-9][0-9]*", value):
            errors.append(f"orchestration.{key} must be an integer >= 1")
            continue
        orchestration[key] = int(value)
    if orchestration.get("max_writers_per_path", 1) != 1:
        errors.append("orchestration.max_writers_per_path must remain 1")
    if orchestration.get("max_depth", 1) != 1:
        errors.append("orchestration.max_depth must remain 1 (nested delegation is disabled)")
    writers = orchestration.get("max_parallel_writers")
    threads = orchestration.get("max_concurrent_subagents")
    if writers is not None and threads is not None and writers > threads:
        errors.append("max_parallel_writers cannot exceed max_concurrent_subagents")

    managed_directories = set(MANAGED_OUTPUT_DIRECTORIES)
    managed_files = set(MANAGED_OUTPUT_FILES)
    managed_directories.update(
        Path(value) for key, value in docs.items() if key in DOC_DIR_KEYS
    )
    managed_files.update(
        Path(value) for key, value in docs.items() if key in DOC_FILE_KEYS
    )
    managed_files.update(
        Path(".codex/agents") / f"{role_file.stem}.toml"
        for role_file in roles_dir.glob("xy-*.md")
    )
    managed_files.update(
        Path(".agents/agents") / f"{role}.md" for role in enabled_roles
    )
    managed_directories.add(Path(".agents/agents"))
    for skill in ANTIGRAVITY_CORE_SKILLS:
        managed_directories.add(Path(".agents/skills") / skill)
        managed_files.add(Path(".agents/skills") / skill / "SKILL.md")
    managed_paths = managed_directories | managed_files
    for relative in sorted(managed_paths):
        target = root / relative
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            errors.append(f"managed output resolves outside project root: {relative}")
        elif path_has_symlink(root, relative):
            errors.append(f"managed output must not use symlinks: {relative}")
        elif target.exists() and relative in managed_directories and not target.is_dir():
            errors.append(f"managed output must be a directory: {relative}")
        elif target.exists() and relative in managed_files and not target.is_file():
            errors.append(f"managed output must be a regular file: {relative}")
        elif target.exists() and relative in managed_files:
            try:
                if target.lstat().st_nlink != 1:
                    errors.append(
                        f"managed output must not be a hard link: {relative}"
                    )
            except OSError as exc:
                errors.append(f"cannot inspect managed output {relative}: {exc}")
    for match in re.finditer(r"docs/[A-Za-z0-9_./-]+\.md", text):
        relative = Path(match.group(0))
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            errors.append(f"document path escapes project root: {relative}")

    return ValidationResult(tuple(errors), profile)


def validate(
    yaml_path: str | PathLike[str],
    project_root: str | PathLike[str],
    roles_dir: str | PathLike[str],
) -> list[str]:
    """Compatibility for validation callers; retired config shapes are not supported."""

    return list(validate_with_profile(yaml_path, project_root, roles_dir).errors)


def main() -> int:
    arguments = sys.argv[1:]
    if len(arguments) != 3:
        print(
            "usage: validate_project_config.py PROJECT_YAML PROJECT_ROOT ROLES_DIR",
            file=sys.stderr,
        )
        return 2
    try:
        errors = validate(
            Path(arguments[0]),
            Path(arguments[1]),
            Path(arguments[2]),
        )
    except OSError as exc:
        print(f"[ERROR] cannot read project config: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
