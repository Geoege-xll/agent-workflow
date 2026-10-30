#!/usr/bin/env python3
"""Ownership-safe, rollback-capable Antigravity project publisher.

The shell orchestrator renders and validates immutable inputs in a temporary staging
root first.  This helper then makes one ownership plan from that staged snapshot,
rechecks every target immediately before mutation, and rolls back synchronous
failures.  It never treats an ``xy-*`` filename as proof of pack ownership.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import secrets
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

from standards_baseline import (
    common_span, ensure_general_link, merge_general, validate_planned_rule_ids,
    render_template as render_standards_baseline,
)
from project_discovery import ProjectProfile
from shared_core_skills import (
    SharedCoreSkillError,
    audit_managed_skill_root,
    sync_skill_tree,
    validate_stale_managed_skill_directory,
    validate_target_skill_tree_for_update,
)
from validate_antigravity_artifacts import (
    AGENT_MARKER,
    ANTIGRAVITY_BEGIN,
    ANTIGRAVITY_END,
    CODEX_BEGIN,
    CODEX_END,
    CLAUDE_BEGIN,
    CLAUDE_END,
    CORE_SKILLS,
    PRODUCT_BEGIN,
    PRODUCT_END,
    ROLE_TOOLS,
    validate_agent,
    validate_artifact_tree,
)
from validate_project_config import parse_project_name, validate_with_profile
from validate_project_docs import MARKDOWN_LINK_RE, normalized_link_target
from workflow_hook_install import plan_hooks


TRANSACTION_PREFIX = ".agent-workflow-pack-antigravity--"
MAX_FILE_SIZE = 8 * 1024 * 1024


class ApplyError(ValueError):
    """A controlled ownership, topology, or publication failure."""


@dataclass(frozen=True)
class Fingerprint:
    kind: str
    mode: int = 0
    device: int = 0
    inode: int = 0
    nlink: int = 0
    payload: str = ""


@dataclass
class FileChange:
    target: Path
    body: bytes
    mode: int
    before: Fingerprint
    backup: Path | None = None
    published: bool = False


@dataclass
class DirectoryChange:
    target: Path
    candidate: Path
    before: Fingerprint
    tree_before: tuple[tuple[str, Fingerprint], ...] | None
    backup: Path | None = None


@dataclass(frozen=True)
class PrototypeScaffold:
    root: Path
    root_before: Fingerprint


@dataclass
class Plan:
    pack: Path
    project: Path
    staging: Path
    nonce: str
    root_fingerprints: dict[Path, Fingerprint] = field(default_factory=dict)
    agent_changes: list[FileChange] = field(default_factory=list)
    skill_changes: list[DirectoryChange] = field(default_factory=list)
    doc_changes: list[FileChange] = field(default_factory=list)
    hook_changes: list[FileChange] = field(default_factory=list)
    feature_docs_root: tuple[Path, Fingerprint] | None = None
    prototype_scaffold: PrototypeScaffold | None = None
    agents_md: FileChange | None = None
    stale_agents: list[tuple[Path, Fingerprint]] = field(default_factory=list)
    stale_skills: list[
        tuple[Path, Fingerprint, tuple[tuple[str, Fingerprint], ...]]
    ] = field(default_factory=list)
    created_directories: list[Path] = field(default_factory=list)
    moved_stale: list[tuple[Path, Path, str]] = field(default_factory=list)


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ApplyError(f"cannot inspect target {path}: {exc}") from exc


def _read_regular(path: Path, label: str) -> bytes:
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
            raise ApplyError(f"{label} must be a real regular file: {path}")
        if info.st_nlink != 1:
            raise ApplyError(f"hard link is forbidden for {label}: {path}")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise ApplyError(f"{label} exceeds the size limit: {path}")
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise ApplyError(f"cannot securely read {label} {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fingerprint(path: Path, *, read_file: bool = True) -> Fingerprint:
    info = _lstat(path)
    if info is None:
        return Fingerprint("missing")
    mode = stat.S_IMODE(info.st_mode)
    common = dict(
        mode=mode,
        device=info.st_dev,
        inode=info.st_ino,
        nlink=info.st_nlink,
    )
    if stat.S_ISLNK(info.st_mode):
        try:
            return Fingerprint("symlink", payload=os.readlink(path), **common)
        except OSError as exc:
            raise ApplyError(f"cannot read symlink target {path}: {exc}") from exc
    if stat.S_ISDIR(info.st_mode):
        return Fingerprint("directory", **common)
    if stat.S_ISREG(info.st_mode):
        payload = ""
        if read_file:
            payload = hashlib.sha256(_read_regular(path, "managed target")).hexdigest()
        return Fingerprint("file", payload=payload, **common)
    if stat.S_ISFIFO(info.st_mode):
        return Fingerprint("fifo", **common)
    if stat.S_ISSOCK(info.st_mode):
        return Fingerprint("socket", **common)
    return Fingerprint("special", **common)


def _assert_unchanged(path: Path, expected: Fingerprint) -> None:
    actual = _fingerprint(path, read_file=expected.kind == "file")
    if actual != expected:
        raise ApplyError(f"target changed after preflight: {path}")


def _tree_fingerprint(root: Path) -> tuple[tuple[str, Fingerprint], ...]:
    root_info = _fingerprint(root, read_file=False)
    if root_info.kind != "directory":
        raise ApplyError(f"managed tree must be a real directory: {root}")
    result: list[tuple[str, Fingerprint]] = []

    def visit(directory: Path, prefix: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise ApplyError(f"cannot inspect managed tree {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = prefix / entry.name
            node = _fingerprint(path)
            if node.kind not in {"directory", "file"}:
                raise ApplyError(
                    f"managed tree contains a symlink or special node: {path}"
                )
            if node.kind == "file" and node.nlink != 1:
                raise ApplyError(f"hard link is forbidden in managed tree: {path}")
            result.append((relative.as_posix(), node))
            if node.kind == "directory":
                visit(path, relative)

    visit(root, Path())
    return tuple(result)


def _require_real_directory(path: Path, label: str) -> Fingerprint:
    node = _fingerprint(path, read_file=False)
    if node.kind != "directory":
        raise ApplyError(f"{label} must be a real directory: {path}")
    return node


def _classify_agents_root(project: Path) -> dict[Path, Fingerprint]:
    root = project / ".agents"
    node = _fingerprint(root, read_file=False)
    roots: dict[Path, Fingerprint] = {root: node}
    if node.kind == "missing":
        return roots
    if node.kind == "symlink":
        raise ApplyError(f".agents symlink is forbidden: {root}")
    if node.kind != "directory":
        raise ApplyError(f".agents must be a real directory: {root}")
    for child in (root / "agents", root / "skills"):
        child_node = _fingerprint(child, read_file=False)
        roots[child] = child_node
        if child_node.kind not in {"missing", "directory"}:
            raise ApplyError(f"native managed root must be a real directory: {child}")
    return roots


def _parse_project_values(config: Path) -> dict[str, str]:
    try:
        lines = _read_regular(config, "project configuration").decode(
            "utf-8", errors="strict"
        ).splitlines()
    except UnicodeDecodeError as exc:
        raise ApplyError(f"project configuration is not UTF-8: {config}") from exc
    values: dict[str, str] = {}
    section: str | None = None
    for raw in lines:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*:\s*(?:#.*)?", raw):
            section = raw.split(":", 1)[0]
            continue
        if section == "docs":
            match = re.fullmatch(r"  ([A-Za-z0-9_]+):\s*(.*?)\s*", raw)
            if match:
                value = re.sub(r"\s+#.*$", "", match.group(2)).strip("\"'")
                values[f"docs.{match.group(1)}"] = value
        match = re.fullmatch(r"project_name:\s*(.*?)\s*", raw)
        if match:
            # 使用共享解码规则，保证自动目录名及手工名称在三个宿主中一致。
            values["project_name"] = parse_project_name(match.group(1))
    return values


def _render_doc_candidates(
    pack: Path,
    project: Path,
    *,
    ui_enabled: bool,
    profile: ProjectProfile,
) -> list[tuple[Path, bytes]]:
    values = _parse_project_values(pack / "project.yaml")
    project_name = values.get("project_name", "MyProject")
    docs = {
        key.removeprefix("docs."): value
        for key, value in values.items()
        if key.startswith("docs.")
    }
    # 先计算索引相对路径，既避免嵌套格式化字符串难以审阅，也确保自定义 docs
    # 位置仍能生成正确链接。
    standards_root = docs["standards_root"].rstrip("/")
    standards_index_parent = posixpath.dirname(docs["standards"])
    engineering_general_link = posixpath.relpath(
        f"{standards_root}/GENERAL.md", standards_index_parent
    )
    engineering_upstream_link = posixpath.relpath(
        f"{standards_root}/UPSTREAM.md", standards_index_parent
    )
    design_foundations_link = posixpath.relpath(
        f"{standards_root}/DESIGN_FOUNDATIONS.md", standards_index_parent
    )
    design_components_link = posixpath.relpath(
        f"{standards_root}/DESIGN_COMPONENTS.md", standards_index_parent
    )
    substitutions = {
        "PROJECT_NAME": project_name,
        "DATE": __import__("datetime").date.today().isoformat(),
        "DOC_STANDARDS": docs["standards"],
        "DOC_STANDARDS_ROOT": docs["standards_root"].rstrip("/"),
        "DOC_PROJECT": docs["project"],
        "DOC_FEATURES_DIR": docs["features"].rstrip("/"),
        # 规范使用根目录直接叶；原型单独保留 prototype/ 一层。
        "DOC_DESIGN_DIR": standards_root,
        "DOC_PLANS_DIR": docs["plans"].rstrip("/"),
        "DOC_NOTES_DIR": docs["notes"].rstrip("/"),
        # Markdown 链接相对 STANDARDS.md 自身生成；直接写项目根相对路径会在
        # docs/ 下形成错误的 docs/docs/... 链接。
        "ENGINEERING_STANDARDS_INDEX": (
            f"- [General engineering rules]({engineering_general_link})\n"
            f"- [Upstream and second-development boundaries]({engineering_upstream_link})"
        ),
        # Antigravity 的事务发布器与共享脚手架必须生成同一份目录内容，避免三宿主
        # 因 UI 角色发现结果不同而得到不一致的规范索引。
        "DESIGN_STANDARDS_INDEX": (
            f"- [Design foundations]({design_foundations_link})\n"
            f"- [Component and interaction standards]({design_components_link})"
            if ui_enabled
            else "- No design standards are configured for the discovered project profile."
        ),
    }
    candidates: list[tuple[Path, bytes]] = []
    template_root = pack / "templates/docs"
    # 统一入口和工程叶文档始终存在；设计叶文档仅在发现 UI 角色时生成。
    document_specs = [
        (docs["standards"], Path("STANDARDS.md"), False),
        (
            f"{docs['standards_root'].rstrip('/')}/GENERAL.md",
            Path("standards/GENERAL.md"),
            True,
        ),
        (
            f"{docs['standards_root'].rstrip('/')}/UPSTREAM.md",
            Path("standards/UPSTREAM.md"),
            False,
        ),
        (docs["project"], Path("PROJECT.md"), False),
    ]
    if ui_enabled:
        document_specs.extend(
            [
                (
                    f"{docs['standards_root'].rstrip('/')}/DESIGN_FOUNDATIONS.md",
                    Path("standards/DESIGN_FOUNDATIONS.md"),
                    False,
                ),
                (
                    f"{docs['standards_root'].rstrip('/')}/DESIGN_COMPONENTS.md",
                    Path("standards/DESIGN_COMPONENTS.md"),
                    False,
                ),
            ]
        )
    # 与共享脚手架一致：GENERAL 必须挂入目录，其余可选工程/设计叶不擅自注入。
    index_path = project / docs["standards"]
    if index_path.exists():
        index_body = _read_regular(index_path, "standards index").decode("utf-8")
        if index_body.strip():
            indexed = {normalized_link_target(index_path, raw)
                       for raw in MARKDOWN_LINK_RE.findall(index_body)}
            document_specs = [spec for spec in document_specs
                              if (not spec[1].name.startswith("DESIGN_")
                                  and spec[1].name != "UPSTREAM.md")
                              or (project / spec[0]).resolve() in indexed]
    for target_relative, template_relative, uses_baseline in document_specs:
        source = _read_regular(template_root / template_relative, "document template")
        text = source.decode("utf-8", errors="strict")
        placeholders = set(re.findall(r"\{\{([A-Z_]+)\}\}", text))
        allowed = set(substitutions)
        if uses_baseline:
            allowed.add("OBSERVED_BASELINE")
        unknown = sorted(placeholders - allowed)
        if unknown:
            raise ApplyError(
                f"unknown document template placeholders: {', '.join(unknown)}"
            )
        if uses_baseline:
            try:
                rendered = render_standards_baseline(
                    text, substitutions, profile=profile
                ).encode("utf-8")
            except ValueError as exc:
                raise ApplyError(str(exc)) from exc
        else:
            rendered = re.sub(
                r"\{\{([A-Z_]+)\}\}",
                lambda match: substitutions[match.group(1)],
                text,
            ).encode("utf-8")
        candidates.append((project / target_relative, rendered))
    return candidates


def _prototype_candidates(
    pack: Path, project: Path, *, ui_enabled: bool
) -> tuple[PrototypeScaffold | None, list[tuple[Path, bytes]]]:
    values = _parse_project_values(pack / "project.yaml")
    if not ui_enabled:
        return None, []
    standards_root = values.get("docs.standards_root", "").rstrip("/")
    if not standards_root:
        raise ApplyError("UI project configuration is missing docs.standards_root")
    root = project / standards_root / "prototype"
    root_before = _fingerprint(root, read_file=False)
    if root_before.kind == "directory":
        try:
            with os.scandir(root) as entries:
                if next(entries, None) is not None:
                    return None, []
        except OSError as exc:
            raise ApplyError(f"cannot inspect prototype workspace {root}: {exc}") from exc
    elif root_before.kind != "missing":
        raise ApplyError(f"prototype workspace must be a real directory: {root}")
    return (
        PrototypeScaffold(root, root_before),
        [
            (
                root / "index.html",
                _read_regular(
                    pack / "templates/prototype/index.html", "prototype index template"
                ),
            ),
            (
                root / "prototype.css",
                _read_regular(
                    pack / "templates/prototype/prototype.css",
                    "prototype CSS template",
                ),
            ),
        ],
    )


def _marker_positions(body: str) -> dict[str, list[int]]:
    positions = {
        CLAUDE_BEGIN: [],
        CLAUDE_END: [],
        PRODUCT_BEGIN: [],
        PRODUCT_END: [],
        CODEX_BEGIN: [],
        CODEX_END: [],
        ANTIGRAVITY_BEGIN: [],
        ANTIGRAVITY_END: [],
    }
    for index, line in enumerate(body.splitlines()):
        if line in positions:
            positions[line].append(index)
    return positions


def _validate_global_markers(body: str, path: Path) -> dict[str, tuple[int, int] | None]:
    positions = _marker_positions(body)
    for marker, matches in positions.items():
        if len(matches) > 1:
            raise ApplyError(f"duplicate managed marker in {path}: {marker}")
    pairs = {
        "claude": (CLAUDE_BEGIN, CLAUDE_END, "Claude"),
        "product": (PRODUCT_BEGIN, PRODUCT_END, "product"),
        "codex": (CODEX_BEGIN, CODEX_END, "Codex"),
        "anti": (ANTIGRAVITY_BEGIN, ANTIGRAVITY_END, "Antigravity"),
    }
    result: dict[str, tuple[int, int] | None] = {
        name: None for name in pairs
    }
    for name, (begin, end, label) in pairs.items():
        if not (positions[begin] or positions[end]):
            continue
        if len(positions[begin]) != 1 or len(positions[end]) != 1:
            raise ApplyError(f"orphan {label} managed marker in {path}")
        interval = (positions[begin][0], positions[end][0])
        if interval[0] >= interval[1]:
            raise ApplyError(f"reversed {label} managed markers in {path}")
        result[name] = interval

    product = result["product"]
    host_intervals = tuple(
        interval for name in ("codex", "anti") if (interval := result[name]) is not None
    )
    if product is not None and any(product[1] >= interval[0] for interval in host_intervals):
        raise ApplyError(f"managed marker blocks cross, nest, or are reversed in {path}")
    intervals = sorted(interval for interval in result.values() if interval is not None)
    if any(left[1] >= right[0] for left, right in zip(intervals, intervals[1:])):
        raise ApplyError(f"managed marker blocks cross, nest, or are reversed in {path}")
    return result


def _compose_agents_md(current: bytes, product_block: bytes, anti_block: bytes, path: Path) -> bytes:
    try:
        text = current.decode("utf-8", errors="strict")
        product = product_block.decode("utf-8", errors="strict").rstrip("\n") + "\n"
        anti = anti_block.decode("utf-8", errors="strict").rstrip("\n") + "\n"
    except UnicodeDecodeError as exc:
        raise ApplyError(f"AGENTS managed inputs must be UTF-8: {exc}") from exc
    intervals = _validate_global_markers(text, path)
    lines = text.splitlines(keepends=True)

    def replace(interval: tuple[int, int], block: str) -> None:
        lines[interval[0] : interval[1] + 1] = [block]

    anti_interval = intervals["anti"]
    product_interval = intervals["product"]
    if anti_interval is not None:
        replace(anti_interval, anti)
    if product_interval is not None:
        replace(product_interval, product)
    rebuilt = "".join(lines)
    if product_interval is None:
        if anti_interval is not None:
            anti_index = rebuilt.find(ANTIGRAVITY_BEGIN)
            rebuilt = rebuilt[:anti_index] + product + "\n" + rebuilt[anti_index:]
        else:
            if rebuilt and not rebuilt.endswith("\n"):
                rebuilt += "\n"
            if rebuilt:
                rebuilt += "\n"
            rebuilt += product
    if anti_interval is None:
        if rebuilt and not rebuilt.endswith("\n"):
            rebuilt += "\n"
        if rebuilt:
            rebuilt += "\n"
        rebuilt += anti
    _validate_global_markers(rebuilt, path)
    # 三宿主共用入口后，最后安装的 Antigravity 也要保护已安装 Codex 的既有限额。
    # 这是 Codex 入口保护值，不是 Antigravity/Claude 的官方上下文限制。
    if CODEX_BEGIN in rebuilt and len(rebuilt.encode("utf-8")) > 32768:
        raise ApplyError("combined AGENTS.md would exceed the existing Codex 32 KiB guard")
    return rebuilt.encode("utf-8")


def _copy_managed_tree(source: Path, target: Path) -> None:
    source_tree = _tree_fingerprint(source)
    target.mkdir(mode=stat.S_IMODE(source.lstat().st_mode))
    for raw, node in source_tree:
        source_path = source / raw
        target_path = target / raw
        if node.kind == "directory":
            target_path.mkdir(mode=node.mode)
        else:
            target_path.write_bytes(_read_regular(source_path, "managed Skill target"))
            target_path.chmod(node.mode)


def _agent_is_managed(path: Path, role: str, *, stale: bool) -> bool:
    node = _fingerprint(path)
    if node.kind != "file":
        return False
    body_bytes = _read_regular(path, "Antigravity Agent target")
    try:
        body = body_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ApplyError(f"Antigravity Agent target is not UTF-8: {path}") from exc
    marker_count = body.splitlines().count(AGENT_MARKER)
    if marker_count == 0:
        return False
    if marker_count != 1:
        raise ApplyError(f"ambiguous managed Agent marker count: {path}")
    errors: list[str] = []
    # 旧目标只须证明受管归属和执行安全；新版语义由发布前 staging 与发布后 generated 验证。
    # 否则一次新增必含短语就会使正常旧版本失去升级资格。
    validate_agent(path, body, role, set(CORE_SKILLS), errors, ownership_only=True)
    if errors:
        label = "stale" if stale else "current"
        raise ApplyError(f"invalid {label} managed Agent {path}: {errors[0]}")
    return True


def build_plan(pack: Path, project: Path, staging: Path) -> Plan:
    _require_real_directory(pack, "workflow pack")
    _require_real_directory(project, "project root")
    _require_real_directory(staging, "Antigravity staging root")
    _require_real_directory(staging / "agents", "staged Agent root")
    _require_real_directory(staging / "skills", "staged Skill root")
    roots = _classify_agents_root(project)
    plan = Plan(pack, project, staging, secrets.token_hex(16))
    plan.root_fingerprints.update(roots)
    # 原生 Hook 配置与角色、Skill 使用同一事务发布/回滚，避免生成失败后留下半套安装。
    hook_target, hook_before, hook_body = plan_hooks(pack, project, "antigravity")
    if hook_before != hook_body and not (hook_before is None and not hook_body):
        before = _fingerprint(hook_target)
        plan.hook_changes.append(FileChange(
            hook_target, hook_body, before.mode if before.kind == "file" else 0o644, before,
        ))

    agents_root = project / ".agents/agents"
    skills_root = project / ".agents/skills"
    if roots.get(skills_root, Fingerprint("missing")).kind == "directory":
        try:
            audit_managed_skill_root(skills_root, recover=False)
        except SharedCoreSkillError as exc:
            raise ApplyError(str(exc)) from exc

    staged_agents = sorted((staging / "agents").glob("*.md"))
    expected_roles = {path.stem for path in staged_agents}
    validation = validate_with_profile(
        pack / "project.yaml", project, pack / "roles"
    )
    if validation.errors or validation.profile is None:
        raise ApplyError(
            "cannot apply invalid discovered project profile: "
            + "; ".join(validation.errors or ("profile is missing",))
        )
    profile = validation.profile
    # 与共享脚手架使用同一决策，基础设计角色不会给纯后端项目强加 UI 文档。
    ui_enabled = profile.design_scaffold_required
    if expected_roles != set(profile.enabled_roles):
        raise ApplyError(
            "staged Agent roster differs from discovered ProjectProfile: "
            f"expected {sorted(profile.enabled_roles)}, got {sorted(expected_roles)}"
        )
    expected_skills = {
        path.name for path in (staging / "skills").iterdir() if path.is_dir()
    }
    if expected_skills != set(CORE_SKILLS):
        raise ApplyError("staged shared Skill set is incomplete")

    for source in staged_agents:
        source_node = _fingerprint(source)
        if source_node.kind != "file" or source_node.nlink != 1:
            raise ApplyError(f"staged Agent must be a single-link regular file: {source}")
        target = agents_root / source.name
        before = _fingerprint(target)
        if before.kind != "missing":
            if before.kind != "file" or before.nlink != 1:
                raise ApplyError(f"same-name Antigravity Agent collision: {target}")
            if not _agent_is_managed(target, source.stem, stale=False):
                raise ApplyError(f"user-owned same-name Antigravity Agent: {target}")
        plan.agent_changes.append(
            FileChange(
                target,
                _read_regular(source, "staged Agent"),
                before.mode if before.kind == "file" else source_node.mode,
                before,
            )
        )

    if roots.get(agents_root, Fingerprint("missing")).kind == "directory":
        for entry in sorted(os.scandir(agents_root), key=lambda item: item.name):
            if entry.name in {f"{role}.md" for role in expected_roles}:
                continue
            path = Path(entry.path)
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                continue
            if info.st_nlink != 1:
                continue
            role = path.stem
            if role not in ROLE_TOOLS:
                body = _read_regular(path, "stale Agent candidate")
                try:
                    marker_count = body.decode("utf-8", errors="strict").splitlines().count(AGENT_MARKER)
                except UnicodeDecodeError:
                    marker_count = 0
                if marker_count:
                    raise ApplyError(f"cannot prove ownership of unknown stale Agent: {path}")
                continue
            if _agent_is_managed(path, role, stale=True):
                plan.stale_agents.append((path, _fingerprint(path)))

    candidate_root = staging / f"{TRANSACTION_PREFIX}candidate--{plan.nonce}"
    candidate_skills = candidate_root / "skills"
    candidate_skills.mkdir(parents=True)
    for name in sorted(expected_skills):
        source = staging / "skills" / name
        target = skills_root / name
        before = _fingerprint(target, read_file=False)
        tree_before: tuple[tuple[str, Fingerprint], ...] | None = None
        candidate = candidate_skills / name
        if before.kind != "missing":
            if before.kind != "directory":
                raise ApplyError(f"same-name shared Skill collision: {target}")
            try:
                validate_target_skill_tree_for_update(source, target, name)
            except SharedCoreSkillError as exc:
                raise ApplyError(str(exc)) from exc
            tree_before = _tree_fingerprint(target)
            _copy_managed_tree(target, candidate)
        try:
            sync_skill_tree(source, candidate, name)
        except SharedCoreSkillError as exc:
            raise ApplyError(str(exc)) from exc
        if tree_before is not None:
            for raw, previous in tree_before:
                candidate_path = candidate / raw
                if _fingerprint(candidate_path, read_file=False).kind == previous.kind:
                    os.chmod(candidate_path, previous.mode, follow_symlinks=False)
        plan.skill_changes.append(
            DirectoryChange(target, candidate, before, tree_before)
        )

    if roots.get(skills_root, Fingerprint("missing")).kind == "directory":
        for entry in sorted(os.scandir(skills_root), key=lambda item: item.name):
            if entry.name in expected_skills:
                continue
            path = Path(entry.path)
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                continue
            skill_file = path / "SKILL.md"
            skill_node = _fingerprint(skill_file)
            if skill_node.kind != "file" or skill_node.nlink != 1:
                continue
            try:
                body = _read_regular(skill_file, "stale Skill candidate").decode(
                    "utf-8", errors="strict"
                )
            except UnicodeDecodeError:
                continue
            if body.splitlines().count("<!-- agent-workflow-pack:managed-skill -->") != 1:
                continue
            try:
                validate_stale_managed_skill_directory(path, entry.name)
            except SharedCoreSkillError as exc:
                raise ApplyError(str(exc)) from exc
            plan.stale_skills.append(
                (path, _fingerprint(path, read_file=False), _tree_fingerprint(path))
            )

    root_agents = project / "AGENTS.md"
    agents_before = _fingerprint(root_agents)
    if agents_before.kind not in {"missing", "file"}:
        raise ApplyError(f"root AGENTS.md must be a real regular file: {root_agents}")
    if agents_before.kind == "file" and agents_before.nlink != 1:
        raise ApplyError(f"hard link is forbidden for root AGENTS.md: {root_agents}")
    current = b"" if agents_before.kind == "missing" else _read_regular(root_agents, "root AGENTS.md")
    composed = _compose_agents_md(
        current,
        _read_regular(staging / "AGENTS.product.block", "staged product block"),
        _read_regular(staging / "AGENTS.antigravity.block", "staged Antigravity block"),
        root_agents,
    )
    plan.agents_md = FileChange(
        root_agents,
        composed,
        agents_before.mode if agents_before.kind == "file" else 0o644,
        agents_before,
    )

    prototype_scaffold, prototype_candidates = _prototype_candidates(
        pack, project, ui_enabled=ui_enabled
    )
    plan.prototype_scaffold = prototype_scaffold
    document_candidates = [
        *_render_doc_candidates(
            pack, project, ui_enabled=ui_enabled, profile=profile
        ),
        *prototype_candidates,
    ]
    # features/ 是受控目录但不包含安装器制造的 README/.gitkeep。单独记录目录快照，
    # 既能在直接 Antigravity 安装中创建它，也不会把占位文件误认为真实功能文档。
    feature_value = _parse_project_values(pack / "project.yaml").get(
        "docs.features", "docs/features/"
    )
    feature_target = project / feature_value
    feature_before = _fingerprint(feature_target, read_file=False)
    if feature_before.kind not in {"missing", "directory"}:
        raise ApplyError(
            f"feature document root must be a real directory: {feature_target}"
        )
    plan.feature_docs_root = (feature_target, feature_before)
    docs = _parse_project_values(pack / "project.yaml")
    general_target = project / docs["docs.standards_root"] / "GENERAL.md"
    index_target = project / docs["docs.standards"]
    for target, body in document_candidates:
        before = _fingerprint(target)
        if before.kind not in {"missing", "file"}:
            raise ApplyError(f"managed document must be a real regular file: {target}")
        if before.kind == "file" and before.nlink != 1:
            raise ApplyError(f"hard link is forbidden for managed document: {target}")
        current_body = (
            b"" if before.kind == "missing" else _read_regular(target, "managed document")
        )
        # 复用共享的所有权规则；FileChange 保留原完整指纹，由现有事务发布器
        # 负责竞态复核及失败回滚，不再另写一套按标题替换的实现。
        if current_body and target == general_target:
            body = merge_general(current_body, body)
            if common_span(current_body) is None:
                print(f"[WARN] {target}: common region is unmarked; preserved unchanged; controlled adoption required")
        elif current_body and target == index_target:
            body = ensure_general_link(current_body, index_target, general_target)
        elif current_body:
            body = current_body
        if before.kind == "missing" or body != current_body:
            plan.doc_changes.append(
                FileChange(
                    target,
                    body,
                    before.mode if before.kind == "file" else 0o644,
                    before,
                )
            )
    validate_planned_rule_ids(general_target.parent, {
        change.target: change.body for change in plan.doc_changes
    })
    return plan


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


def _ensure_directories(plan: Plan, path: Path) -> None:
    missing: list[Path] = []
    current = path
    while current != plan.project and _fingerprint(current, read_file=False).kind == "missing":
        missing.append(current)
        current = current.parent
    if current == plan.project:
        _require_real_directory(current, "project root")
    else:
        _require_real_directory(current, "managed target parent")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o755)
        except FileExistsError as exc:
            raise ApplyError(f"target appeared after preflight: {directory}") from exc
        plan.created_directories.append(directory)
        _fsync_directory(directory.parent)


def _prepare_prototype_scaffold(plan: Plan) -> None:
    scaffold = plan.prototype_scaffold
    if scaffold is None:
        return
    _assert_unchanged(scaffold.root, scaffold.root_before)
    if (
        scaffold.root_before.kind == "directory"
        and _tree_fingerprint(scaffold.root)
    ):
        raise ApplyError(
            f"prototype workspace became active after preflight: {scaffold.root}"
        )
    _ensure_directories(plan, scaffold.root)
    with os.scandir(scaffold.root) as entries:
        root_entries = sorted(entry.name for entry in entries)
    if root_entries:
        raise ApplyError(
            f"prototype workspace changed during directory publication: {scaffold.root}"
        )


def _prepare_feature_docs_root(plan: Plan) -> None:
    """创建空的 features/ 权威目录，同时拒绝预检后发生的类型替换。"""

    if plan.feature_docs_root is None:
        return
    target, before = plan.feature_docs_root
    _assert_unchanged(target, before)
    _ensure_directories(plan, target)


def _temp_path(target: Path, nonce: str, kind: str) -> Path:
    digest = hashlib.sha256(f"{kind}\0{target}".encode()).hexdigest()
    return target.parent / f"{TRANSACTION_PREFIX}{kind}--{nonce}--{digest}"


def _write_temp(target: Path, body: bytes, mode: int, nonce: str) -> Path:
    temporary = _temp_path(target, nonce, "temp")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ApplyError(f"atomic temporary is not a single-link regular file: {temporary}")
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(target.parent)
        return temporary
    except OSError as exc:
        raise ApplyError(f"cannot create atomic temporary for {target}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publish_file(change: FileChange, plan: Plan) -> None:
    _assert_unchanged(change.target, change.before)
    _ensure_directories(plan, change.target.parent)
    temporary = _write_temp(change.target, change.body, change.mode, plan.nonce)
    if change.before.kind == "missing":
        try:
            os.link(temporary, change.target, follow_symlinks=False)
            temporary.unlink()
            change.published = True
            _fsync_directory(change.target.parent)
        except OSError as exc:
            if temporary.exists():
                temporary.unlink()
            raise ApplyError(f"cannot atomically create managed file {change.target}: {exc}") from exc
        return
    backup = _temp_path(change.target, plan.nonce, "backup")
    if _fingerprint(backup, read_file=False).kind != "missing":
        temporary.unlink()
        raise ApplyError(f"owned backup path already exists: {backup}")
    os.replace(change.target, backup)
    if _fingerprint(backup) != change.before:
        if _fingerprint(change.target, read_file=False).kind == "missing":
            os.replace(backup, change.target)
        temporary.unlink(missing_ok=True)
        raise ApplyError(f"managed file changed during publish: {change.target}")
    change.backup = backup
    if change in plan.doc_changes:
        # 原文件移入备份后，编辑器可能立即重建同名文档；排他创建避免覆盖这个
        # 间隙产生的项目内容。失败时交由事务回滚保留并发文档及原始备份。
        try:
            os.link(temporary, change.target, follow_symlinks=False)
            change.published = True
        except OSError as exc:
            raise ApplyError(f"cannot atomically replace managed document {change.target}: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)
    else:
        os.replace(temporary, change.target)
        change.published = True
    _fsync_directory(change.target.parent)


def _publish_directory(change: DirectoryChange, plan: Plan) -> None:
    _assert_unchanged(change.target, change.before)
    if change.tree_before is not None and _tree_fingerprint(change.target) != change.tree_before:
        raise ApplyError(f"managed directory changed after preflight: {change.target}")
    _ensure_directories(plan, change.target.parent)
    if change.before.kind == "missing":
        try:
            change.candidate.rename(change.target)
        except OSError as exc:
            raise ApplyError(f"cannot publish managed Skill {change.target}: {exc}") from exc
        _fsync_directory(change.target.parent)
        return
    backup = _temp_path(change.target, plan.nonce, "backup-tree")
    if _fingerprint(backup, read_file=False).kind != "missing":
        raise ApplyError(f"owned Skill backup already exists: {backup}")
    os.replace(change.target, backup)
    if _tree_fingerprint(backup) != change.tree_before:
        if _fingerprint(change.target, read_file=False).kind == "missing":
            os.replace(backup, change.target)
        raise ApplyError(f"managed Skill changed during publish: {change.target}")
    change.backup = backup
    os.replace(change.candidate, change.target)
    _fsync_directory(change.target.parent)


def _move_stale(plan: Plan, path: Path, before: Fingerprint, kind: str) -> None:
    _assert_unchanged(path, before)
    tombstone = _temp_path(path, plan.nonce, f"stale-{kind}")
    if _fingerprint(tombstone, read_file=False).kind != "missing":
        raise ApplyError(f"owned stale tombstone already exists: {tombstone}")
    os.replace(path, tombstone)
    plan.moved_stale.append((path, tombstone, kind))
    _fsync_directory(path.parent)


def _rollback(plan: Plan) -> None:
    errors: list[str] = []
    for original, moved, _kind in reversed(plan.moved_stale):
        try:
            if _fingerprint(original, read_file=False).kind == "missing" and _fingerprint(moved, read_file=False).kind != "missing":
                os.replace(moved, original)
        except Exception as exc:  # rollback must aggregate every exact failure
            errors.append(f"restore {original}: {exc}")
    changes: list[FileChange | DirectoryChange] = []
    changes.extend(plan.doc_changes)
    changes.extend(plan.hook_changes)
    if plan.agents_md is not None:
        changes.append(plan.agents_md)
    changes.extend(plan.skill_changes)
    changes.extend(plan.agent_changes)
    for change in reversed(changes):
        try:
            current = _fingerprint(change.target, read_file=False)
            if isinstance(change, FileChange) and (
                change in plan.hook_changes or change in plan.doc_changes
            ):
                # 回滚不能凭“事务曾拥有这个路径”就撤销后来的用户修改。未发布且无
                # 备份的条目没有可撤销动作；已发布条目须仍是本轮精确配置和权限。
                if not change.published and change.backup is None:
                    continue
                if change.published or current.kind != "missing":
                    if change in plan.doc_changes:
                        # 文档沿用本发布器的安全读取与既有路径快照，避免把 macOS
                        # 合法的 /var 临时目录别名误当成另一个宿主的入口路径碰撞。
                        actual = _read_regular(change.target, "published document")
                    else:
                        from claude_instructions import read_file
                        actual = read_file(change.target)
                    if actual != change.body or current.mode != change.mode:
                        raise ApplyError(
                            f"{'Hook settings' if change in plan.hook_changes else 'Document'} changed after publication; preserved current file and backup: {change.target}"
                        )
                if change.backup is not None:
                    _assert_unchanged(change.backup, change.before)
            if change.backup is not None and _fingerprint(change.backup, read_file=False).kind != "missing":
                if current.kind != "missing":
                    if current.kind == "directory":
                        shutil.rmtree(change.target)
                    else:
                        change.target.unlink()
                os.replace(change.backup, change.target)
            elif change.before.kind == "missing" and current.kind != "missing":
                if current.kind == "directory":
                    shutil.rmtree(change.target)
                else:
                    change.target.unlink()
        except Exception as exc:
            errors.append(f"restore {change.target}: {exc}")
    for directory in reversed(plan.created_directories):
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    if errors:
        raise ApplyError("rollback failed: " + "; ".join(errors))


def _cleanup_committed(plan: Plan) -> None:
    removed = 0
    errors: list[str] = []

    def note_removal() -> None:
        nonlocal removed
        removed += 1
        if (
            removed == 1
            and os.environ.get("AGENT_WORKFLOW_PACK_TEST_FAILPOINT")
            == "antigravity-cleanup-after-first-backup"
        ):
            errors.append("injected cleanup failure after committed publication")

    def remove(path: Path, *, tree: bool, label: str) -> None:
        try:
            if tree:
                shutil.rmtree(path)
            else:
                path.unlink()
            note_removal()
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    for change in [*plan.agent_changes, *plan.skill_changes, *plan.doc_changes, *plan.hook_changes]:
        if change.backup is None:
            continue
        if change in plan.doc_changes:
            # 已打开旧文档的进程仍可能写入备份 inode；不可把这些迟到修改清掉。
            try:
                _assert_unchanged(change.backup, change.before)
            except ApplyError as exc:
                errors.append(f"preserve changed document backup {change.backup}: {exc}")
                continue
        remove(
            change.backup,
            tree=change.backup.is_dir(),
            label=f"remove committed backup {change.backup}",
        )
    if plan.agents_md is not None and plan.agents_md.backup is not None:
        remove(
            plan.agents_md.backup,
            tree=False,
            label=f"remove committed backup {plan.agents_md.backup}",
        )
    for _original, moved, kind in plan.moved_stale:
        remove(
            moved,
            tree=kind == "skill",
            label=f"remove committed stale artifact {moved}",
        )
    if errors:
        raise ApplyError("; ".join(errors))


def apply_plan(plan: Plan) -> None:
    for path, expected in plan.root_fingerprints.items():
        _assert_unchanged(path, expected)
    try:
        _prepare_feature_docs_root(plan)
        _prepare_prototype_scaffold(plan)
        for change in plan.doc_changes:
            _publish_file(change, plan)
        for change in plan.hook_changes:
            _publish_file(change, plan)
        for change in plan.agent_changes:
            _publish_file(change, plan)
        if os.environ.get("AGENT_WORKFLOW_PACK_TEST_FAILPOINT") == "antigravity-after-agents-publish":
            raise ApplyError("injected failure after native Agent publication")
        for change in plan.skill_changes:
            _publish_directory(change, plan)
        for path, before in plan.stale_agents:
            _move_stale(plan, path, before, "agent")
        for path, before, tree_before in plan.stale_skills:
            if _tree_fingerprint(path) != tree_before:
                raise ApplyError(f"stale managed Skill changed after preflight: {path}")
            _move_stale(plan, path, before, "skill")
        assert plan.agents_md is not None
        _publish_file(plan.agents_md, plan)
        # 在仍可回滚的事务内检验最终产物；含用户 Hook 的目录不能靠整树 reset 恢复。
        errors: list[str] = []
        backups = set()
        for change in plan.agent_changes:
            if change.backup is not None:
                _assert_unchanged(change.backup, change.before)
                backups.add(change.backup)
        for change in plan.doc_changes:
            if change.backup is not None:
                _assert_unchanged(change.backup, change.before)
        for _path, moved, kind in plan.moved_stale:
            if kind == "agent":
                backups.add(moved)
        validate_artifact_tree(plan.pack, plan.project, "generated", errors,
                               transaction_backups=frozenset(backups))
        if os.environ.get("AGENT_WORKFLOW_PACK_TEST_FAILPOINT") == "antigravity-generated-validator-failure":
            errors.append("injected Antigravity generated validator failure")
        if errors:
            raise ApplyError("; ".join(errors))
    except Exception as exc:
        try:
            _rollback(plan)
        except ApplyError as rollback_exc:
            raise ApplyError(f"{exc}; {rollback_exc}") from exc
        if isinstance(exc, ApplyError):
            raise
        raise ApplyError(str(exc)) from exc
    try:
        _cleanup_committed(plan)
    except Exception as exc:
        print(f"[WARN] Antigravity cleanup deferred after commit: {exc}", file=sys.stderr)


def _content_signature(
    tree: tuple[tuple[str, Fingerprint], ...]
) -> tuple[tuple[str, str, int, str], ...]:
    """Return the portable bytes/type/mode view of a managed tree."""

    return tuple((path, node.kind, node.mode, node.payload) for path, node in tree)


def check_plan(plan: Plan) -> None:
    """Require the installed project to exactly match the validated staging plan."""

    if plan.doc_changes:
        raise ApplyError("controlled project documents are missing, empty, or need a managed common/index update")
    if plan.hook_changes:
        raise ApplyError("managed Antigravity assist Hooks drift from source")
    if plan.feature_docs_root is None or _fingerprint(
        plan.feature_docs_root[0], read_file=False
    ).kind != "directory":
        raise ApplyError("controlled feature document directory is missing")
    if plan.stale_agents or plan.stale_skills:
        raise ApplyError("stale managed Antigravity artifacts are present")

    for change in plan.agent_changes:
        current = _fingerprint(change.target)
        expected_hash = hashlib.sha256(change.body).hexdigest()
        if (
            current.kind != "file"
            or current.nlink != 1
            or current.mode != change.mode
            or current.payload != expected_hash
        ):
            raise ApplyError(f"managed Antigravity Agent drift: {change.target}")

    for change in plan.skill_changes:
        if _fingerprint(change.target, read_file=False).kind != "directory":
            raise ApplyError(f"missing managed shared Skill: {change.target}")
        if _content_signature(_tree_fingerprint(change.target)) != _content_signature(
            _tree_fingerprint(change.candidate)
        ):
            raise ApplyError(f"managed shared Skill drift: {change.target}")

    if plan.agents_md is None:
        raise ApplyError("root AGENTS.md comparison was not planned")
    current_root = _fingerprint(plan.agents_md.target)
    if (
        current_root.kind != "file"
        or current_root.nlink != 1
        or current_root.mode != plan.agents_md.mode
        or current_root.payload != hashlib.sha256(plan.agents_md.body).hexdigest()
    ):
        raise ApplyError("root AGENTS.md managed blocks drift from staged contracts")


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[1] not in {"preflight", "apply", "check"}:
        print(
            "usage: apply_antigravity_setup.py preflight|apply|check PACK PROJECT STAGING",
            file=sys.stderr,
        )
        return 2
    mode, pack, project, staging = (
        sys.argv[1],
        Path(sys.argv[2]),
        Path(sys.argv[3]),
        Path(sys.argv[4]),
    )
    try:
        plan = build_plan(pack, project, staging)
        if mode == "apply":
            apply_plan(plan)
        elif mode == "check":
            check_plan(plan)
    except (ApplyError, OSError, UnicodeError, SharedCoreSkillError, KeyError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
