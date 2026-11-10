#!/usr/bin/env python3
"""Ownership-safe, rollback-capable Antigravity project publisher.

The shell orchestrator renders and validates immutable inputs in a temporary staging
root first.  This helper then makes one ownership plan from that staged snapshot,
rechecks every target immediately before mutation, and rolls back synchronous
failures.  It never treats an ``xy-*`` filename as proof of pack ownership.
"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import hashlib
import json
if __package__:
    from lib.platform_fs import os, publish_exclusive
else:
    from lib.platform_fs import os, publish_exclusive
import re
import secrets
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lib.documents.standards_baseline import plan_standard_updates, remove_created_standard
from lib.project.project_discovery import ProjectProfile
from lib.skills.shared_core_skills import (
    SharedCoreSkillError,
    audit_managed_skill_root,
    sync_skill_tree,
    validate_stale_managed_skill_directory,
    validate_target_skill_tree_for_update,
)
from lib.validate_antigravity_artifacts import (
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
from lib.project.validate_project_config import parse_project_name, validate_with_profile
from lib.hosts.workflow_hook_install import plan_hooks


TRANSACTION_PREFIX = ".agent-workflow-pack-antigravity--"
MAX_FILE_SIZE = 8 * 1024 * 1024
DOCUMENT_FILE_SIZE = 4 * 1024 * 1024
CODEX_ENTRY_SIZE = 32768


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
    body: bytes | None
    mode: int
    before: Fingerprint
    backup: Path | None = None
    published: bool = False
    # 仅本次新建薄索引使用条件撤回，不改变既有入口/原型等历史文件恢复机制。
    created_standard_index: bool = False
    # 仅此内存事务持有已按原 fixed source/ready 验证的实际移动后像；恢复和
    # 清理必须继续消费这些事实，不能在失败后以当前同名文件重新建立基准。
    native_published: dict | None = field(default=None, repr=False)
    native_backup: dict | None = field(default=None, repr=False)
    # 文件 I/O 的原入口上界与中央持久 wire 无关：AGY root 的旧源/备份始终
    # 8MiB，受控文档/Hook 4MiB。Codex 32KiB 只在 compose 约束批准的新输出，
    # 不能拿它拒绝可合法缩小的旧源。此字段不进入 wire。
    io_max_bytes: int = MAX_FILE_SIZE


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
        return os.lstat(path)
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
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
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
    # 仅生成项目事实入口；通用工程和设计规则不再投影为项目文档。
    substitutions = {
        "PROJECT_NAME": project_name,
        "DOC_PROJECT": docs["project"],
        "DOC_STANDARDS": docs["standards"],
        "DOC_STANDARDS_ROOT": docs["standards_root"].rstrip("/"),
        "DOC_DESIGN_DIR": docs["standards_root"].rstrip("/"),
        "DOC_PLANS_DIR": docs["plans"].rstrip("/"),
    }
    text = _read_regular(pack / "templates/docs/PROJECT.md", "project template").decode("utf-8")
    unknown = set(re.findall(r"\{\{([A-Z_]+)\}\}", text)) - substitutions.keys()
    if unknown:
        raise ApplyError("unknown document template placeholders: " + ", ".join(sorted(unknown)))
    rendered = re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: substitutions[match[1]], text).encode("utf-8")
    return [(project / docs["project"], rendered)]


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
        # 仅初始化缺失/空工作区，五个运行资产随同一候选事务发布；已有业务工作区原样保留。
        [(root / name, _read_regular(pack / "templates/prototype" / name, f"prototype {name} template"))
         for name in ("index.html", "prototype.css", "workspace.css", "workspace.js", "page-shell.js")],
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
    body = rebuilt.encode("utf-8")
    if CODEX_BEGIN in rebuilt and len(body) > CODEX_ENTRY_SIZE:
        raise ApplyError("combined AGENTS.md would exceed the existing Codex 32 KiB guard")
    if len(body) > MAX_FILE_SIZE:
        raise ApplyError("combined AGENTS.md would exceed its existing 8 MiB read boundary")
    return body


def _copy_managed_tree(source: Path, target: Path) -> None:
    source_root = _require_real_directory(source, "managed Skill source")
    source_tree = _tree_fingerprint(source)
    os.mkdir(target, mode=source_root.mode)
    for raw, node in source_tree:
        source_path = source / raw
        target_path = target / raw
        if node.kind == "directory":
            os.mkdir(target_path, mode=node.mode)
        else:
            body = _read_regular(source_path, "managed Skill target")
            if hashlib.sha256(body).hexdigest() != node.payload:
                raise ApplyError(f"managed Skill source changed during copy: {source_path}")
            descriptor = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, "O_NOFOLLOW", 0)
                                 | getattr(os, "O_CLOEXEC", 0), 0o600)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ApplyError(f"managed Skill copy is not a single-link file: {target_path}")
                os.fchmod(descriptor, node.mode)
                with os.fdopen(descriptor, "wb") as output:
                    descriptor = -1
                    output.write(body)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
    _assert_unchanged(source, source_root)
    if _tree_fingerprint(source) != source_tree:
        raise ApplyError(f"managed Skill source changed during copy: {source}")
    copied = _tree_fingerprint(target)
    expected = tuple((raw, node.kind, node.mode, node.payload) for raw, node in source_tree)
    actual = tuple((raw, node.kind, node.mode, node.payload) for raw, node in copied)
    if actual != expected:
        raise ApplyError(f"managed Skill candidate differs from its source: {target}")


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
            io_max_bytes=DOCUMENT_FILE_SIZE,
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
        with os.scandir(agents_root) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
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
    os.mkdir(candidate_root)
    os.mkdir(candidate_skills)
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
        with os.scandir(skills_root) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
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
        io_max_bytes=MAX_FILE_SIZE,
    )

    prototype_scaffold, prototype_candidates = _prototype_candidates(
        pack, project, ui_enabled=ui_enabled
    )
    plan.prototype_scaffold = prototype_scaffold
    configured_docs = {key.removeprefix("docs."): value
                       for key, value in _parse_project_values(pack / "project.yaml").items()
                       if key.startswith("docs.")}
    standard_inputs: dict[Path, bytes | None] = {}
    standard_updates = plan_standard_updates(
        pack, project, docs=configured_docs, profile=profile, expected_inputs=standard_inputs)
    document_candidates = [
        *standard_updates.items(),
        *_render_doc_candidates(
            pack, project, ui_enabled=ui_enabled, profile=profile
        ),
        *prototype_candidates,
    ]
    # 主题文档只在实际保存时创建；安装不建立空需求目录。
    for target, body in document_candidates:
        before = _fingerprint(target)
        if before.kind not in {"missing", "file"}:
            raise ApplyError(f"managed document must be a real regular file: {target}")
        if before.kind == "file" and before.nlink != 1:
            raise ApplyError(f"hard link is forbidden for managed document: {target}")
        current_body = (
            b"" if before.kind == "missing" else _read_regular(target, "managed document")
        )
        if target in standard_inputs:
            actual = None if before.kind == "missing" else current_body
            if actual != standard_inputs[target]:
                raise ApplyError(f"managed document changed after document planning: {target}")
        # 规范计划已经证明归属；其他非空文档仍按原合同保留，不因升级被接管。
        if current_body and target not in standard_updates:
            body = current_body
        if before.kind == "missing" or body != current_body:
            plan.doc_changes.append(
                FileChange(
                    target,
                    body,
                    before.mode if before.kind == "file" else 0o644,
                    before,
                    created_standard_index=target in standard_updates and before.kind == "missing",
                    io_max_bytes=DOCUMENT_FILE_SIZE,
                )
            )
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
            os.mkdir(directory, mode=0o755)
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


def _temp_path(target: Path, nonce: str, kind: str) -> Path:
    digest = hashlib.sha256(f"{kind}\0{target}".encode()).hexdigest()
    return target.parent / f"{TRANSACTION_PREFIX}{kind}--{nonce}--{digest}"


def _write_temp(target: Path, body: bytes, mode: int, nonce: str, *,
                identity_out: list[tuple[int, int]] | None = None,
                native_parent: int | None = None, native_source: dict | None = None,
                native_ready_out: list[dict] | None = None, max_bytes: int = MAX_FILE_SIZE) -> Path:
    _check_file_budget(body, max_bytes)
    temporary = _temp_path(target, nonce, "temp")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    owned_parent = None
    try:
        if os.name == "nt":
            from lib.windows_fs import create_regular_stage, seal_regular_stage, node_snapshot
            if native_parent is None:
                owned_parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                native_parent = owned_parent
            # 唯一 canonical 后端负责完整源 SD 与 creator HANDLE；本层不从
            # Fingerprint 的摘要重建安全描述符，也不在关闭后再修改权限。
            descriptor, empty = create_regular_stage(native_parent, temporary.name,
                permission_source=target.name if native_source is not None else None,
                expected_source=native_source, max_bytes=max_bytes)
        else:
            descriptor = os.open(temporary, flags, 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ApplyError(f"atomic temporary is not a single-link regular file: {temporary}")
        if os.name != "nt":
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(body)
            output.flush()
            if os.name == "nt":
                sealed = seal_regular_stage(output.fileno(), expected_created=empty, payload=body, mode=mode,
                                            max_bytes=max_bytes)
            else:
                os.fsync(output.fileno())
            if identity_out is not None:
                # 只在仍持有本轮创建 fd 时交出身份，不能关闭后再按路径采样，
                # 否则并发替换成相同字节/权限的文件会被误认成可撤回的原 temp。
                identity_out.append((info.st_dev, info.st_ino))
        if os.name == "nt":
            # 只允许已知 LastWriteTime 关闭结算；其余身份、正文、物理 mode 与
            # owner/DACL 必须等于同 HANDLE seal，绝不追认关闭窗口中的替换。
            ready = node_snapshot(native_parent, temporary.name, max_bytes=max_bytes)
            if (ready is None or any(ready[key] != sealed[key] for key in ("kind", "payload", "mode", "security"))
                    or ready["identity"][:5] != sealed["identity"][:5]
                    or ready["identity"][6:] != sealed["identity"][6:]):
                raise ApplyError(f"atomic temporary changed after its creator closed; preserved: {temporary}")
            if native_ready_out is not None:
                native_ready_out.append(ready)
        _fsync_directory(target.parent)
        return temporary
    except OSError as exc:
        raise ApplyError(f"cannot create atomic temporary for {target}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if owned_parent is not None:
            os.close(owned_parent)


def _check_file_budget(body: bytes | None, max_bytes: int) -> None:
    """纯准备检查：不把原入口 I/O 预算误作可任意扩大中央记录的许可。"""
    if type(max_bytes) is not int or max_bytes not in {DOCUMENT_FILE_SIZE, MAX_FILE_SIZE}:
        raise ApplyError("managed file has an unknown I/O boundary")
    if body is not None and (not isinstance(body, bytes) or len(body) > max_bytes):
        raise ApplyError("managed file output exceeds its existing read boundary")


def _native_path_snapshot(path: Path, *, max_bytes: int) -> dict | None:
    from lib.windows_fs import node_snapshot
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return node_snapshot(parent, path.name, max_bytes=max_bytes)
    finally:
        os.close(parent)


def _native_source_snapshot(parent: int, name: str, before: Fingerprint, *, max_bytes: int) -> dict:
    """将实际完整源像绑定原计划的实体和正文，Fingerprint 不承担 ACL 职责。"""
    from lib.windows_fs import node_snapshot
    source = node_snapshot(parent, name, max_bytes=max_bytes)
    if (source is None or source["kind"] != "file" or before.kind != "file"
            or source["mode"] != before.mode
            or (source["identity"][0], source["identity"][1], source["identity"][3])
               != (before.device, before.inode, before.nlink)
            or hashlib.sha256(source["payload"]).hexdigest() != before.payload):
        raise ApplyError(f"managed file changed before native stage creation: {name}")
    return source


def _check_native_source(path: Path, expected: dict, *, moved: bool = False, max_bytes: int) -> dict:
    """再次读取固定源；已知备份移动只允许原 rename 的 ctime 结算。"""
    actual = _native_path_snapshot(path, max_bytes=max_bytes)
    unchanged = actual == expected
    if moved and actual is not None:
        unchanged = (all(actual[key] == expected[key] for key in ("kind", "payload", "mode", "security"))
                     and actual["identity"][:6] == expected["identity"][:6])
    if not unchanged:
        raise ApplyError(f"managed file native source changed; preserved: {path}")
    return actual


def _discard_native_temp(temporary: Path, ready: dict, *, max_bytes: int, allow_missing: bool = True) -> None:
    """只撤回本次完整 ready 实体；未知或关闭后被编辑的同名文件原样保留。"""
    from lib.windows_fs import delete_regular, node_snapshot
    parent = os.open(temporary.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        actual = node_snapshot(parent, temporary.name, max_bytes=max_bytes)
        if actual is None and not allow_missing:
            raise ApplyError(f"native backup disappeared; preserved transaction evidence: {temporary}")
        if actual is not None:
            if actual != ready:
                raise ApplyError(f"atomic temporary has an external edit; preserved: {temporary}")
            delete_regular(parent, temporary.name, expected={"identity": ready["identity"],
                "security": ready["security"], "sha256": hashlib.sha256(ready["payload"]).hexdigest()}, max_bytes=max_bytes)
    finally:
        os.close(parent)


def _publish_file(change: FileChange, plan: Plan, *, backup_directory: Path | None = None) -> None:
    _check_file_budget(change.body, change.io_max_bytes)
    _assert_unchanged(change.target, change.before)
    # 删除同样参与原事务，不把缺失文件当成空文档发布，也不绕过回滚和归属复核。
    deleting = change.body is None
    if deleting and change.before.kind == "missing":
        return
    _ensure_directories(plan, change.target.parent)
    if os.name == "nt":
        # 保持父目录锚定到 stage 创建、源隔离与最终排他发布结束；不扩大核心
        # readonly scope，也不让 Plan 或恢复记录持有 live reader/句柄。
        parent = os.open(change.target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _publish_file_ready(change, plan, deleting=deleting, backup_directory=backup_directory, native_parent=parent)
        finally:
            os.close(parent)
    else:
        _publish_file_ready(change, plan, deleting=deleting, backup_directory=backup_directory)


def _publish_file_ready(change: FileChange, plan: Plan, *, deleting: bool,
                        backup_directory: Path | None, native_parent: int | None = None) -> None:
    native_source = None
    native_ready: list[dict] = []
    if os.name == "nt" and change.before.kind == "file":
        native_source = _native_source_snapshot(native_parent, change.target.name, change.before, max_bytes=change.io_max_bytes)
    temporary_identity: list[tuple[int, int]] = []
    temporary = None
    if not deleting:
        if os.name == "nt":
            temporary = _write_temp(change.target, change.body, change.mode, plan.nonce,
                identity_out=temporary_identity if backup_directory is not None else None,
                native_parent=native_parent, native_source=native_source, native_ready_out=native_ready,
                max_bytes=change.io_max_bytes)
        elif backup_directory is None:
            temporary = _write_temp(change.target, change.body, change.mode, plan.nonce)
        else:
            temporary = _write_temp(change.target, change.body, change.mode, plan.nonce,
                                    identity_out=temporary_identity)
    if change.before.kind == "missing":
        try:
            if os.name == "nt":
                from lib.windows_fs import move_regular
                move_regular(temporary.name, change.target.name, src_dir_fd=native_parent,
                             dst_dir_fd=native_parent, expected=native_ready[0], max_bytes=change.io_max_bytes)
            else:
                publish_exclusive(temporary, change.target)
            change.published = True
            if os.name == "nt":
                change.native_published = _check_native_source(change.target, native_ready[0], moved=True,
                                                                max_bytes=change.io_max_bytes)
            _fsync_directory(change.target.parent)
        except OSError as exc:
            if temporary.exists():
                if os.name == "nt":
                    _discard_native_temp(temporary, native_ready[0], max_bytes=change.io_max_bytes)
                else:
                    temporary.unlink()
            raise ApplyError(f"cannot atomically create managed file {change.target}: {exc}") from exc
        return
    backup = _temp_path(change.target, plan.nonce, "backup")
    if backup_directory is not None:
        # 仅显式文档事务选择已预检的同卷目录；名称仍绑定原目标和本轮 nonce，
        # 回滚继续持有原 inode，不把备份改写成正文副本或放松消费者的目录校验。
        backup = backup_directory / backup.name
    if _fingerprint(backup, read_file=False).kind != "missing":
        if temporary is not None:
            if os.name == "nt":
                _discard_native_temp(temporary, native_ready[0], max_bytes=change.io_max_bytes)
            else:
                temporary.unlink()
        raise ApplyError(f"owned backup path already exists: {backup}")
    if os.name == "nt":
        from lib.windows_fs import move_regular
        _check_native_source(change.target, native_source, max_bytes=change.io_max_bytes)
        move_regular(change.target.name, backup, src_dir_fd=native_parent, expected=native_source,
                     max_bytes=change.io_max_bytes)
        change.backup = backup
        # 只在这一次已证明的原件移动中容许 ctime 结算，立即固定实际 backup。
        # 后面的发布、rollback 和 cleanup 都必须全等，不能再次放宽或晚采样。
        change.native_backup = _check_native_source(backup, native_source, moved=True, max_bytes=change.io_max_bytes)
    else:
        os.replace(change.target, backup)
        if _fingerprint(backup) != change.before:
            if _fingerprint(change.target, read_file=False).kind == "missing":
                os.replace(backup, change.target)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise ApplyError(f"managed file changed during publish: {change.target}")
        change.backup = backup
    if backup.parent != change.target.parent:
        # 跨目录移动仍在同一文件系统；先登记回滚归属再刷新新目录，刷新失败也能
        # 按 change.backup 恢复原件，不能留下已移走原件但事务尚不知情的窗口。
        try:
            _fsync_directory(backup.parent)
        except BaseException as exc:
            if temporary is not None:
                try:
                    # 正文尚未发布，外层只会按备份恢复旧文；这里复用既有条件撤回
                    # 原语收口本轮 temp。它先排他移名再核对 inode/字节/权限，避免
                    # “先检查再 unlink”误删间隙替换；已变文件原样保留并报告路径。
                    if os.name == "nt":
                        _discard_native_temp(temporary, native_ready[0], max_bytes=change.io_max_bytes)
                    else:
                        remove_created_standard(temporary, change.body, change.mode, temporary_identity[0])
                except BaseException as cleanup_exc:
                    raise ApplyError(
                        f"{exc}; document temporary preserved at {temporary}: {cleanup_exc}"
                    ) from exc
            raise
    if deleting:
        # 备份保留到生成物验收结束；同名新文件属于并发用户，失败回滚不得覆盖。
        if _fingerprint(change.target, read_file=False).kind != "missing":
            raise ApplyError(f"managed document appeared during deletion: {change.target}")
        change.published = True
        _fsync_directory(change.target.parent)
        return
    if os.name == "nt":
        # backup 可以位于项目根；它仍须是创建前已授权的原 inode/SD，不能从
        # 一个同正文备份重新选择权限模板。排他发布消费固定 ready，不再重采样。
        from lib.windows_fs import move_regular
        _check_native_source(backup, change.native_backup, max_bytes=change.io_max_bytes)
        try:
            move_regular(temporary.name, change.target.name, src_dir_fd=native_parent,
                         dst_dir_fd=native_parent, expected=native_ready[0], max_bytes=change.io_max_bytes)
            change.published = True
            change.native_published = _check_native_source(change.target, native_ready[0], moved=True,
                                                            max_bytes=change.io_max_bytes)
        finally:
            _discard_native_temp(temporary, native_ready[0], max_bytes=change.io_max_bytes)
        _fsync_directory(change.target.parent)
        return
    if change in plan.doc_changes:
        # 原文件移入备份后，编辑器可能立即重建同名文档；排他创建避免覆盖这个
        # 间隙产生的项目内容。失败时交由事务回滚保留并发文档及原始备份。
        try:
            publish_exclusive(temporary, change.target)
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
    if os.name == "nt":
        # System temp and the project may be on different volumes. Only the
        # verified, flushed project-volume copy participates in atomic publication.
        from lib.windows_fs import flush_tree
        candidate = _temp_path(change.target, plan.nonce, "candidate-tree")
        _copy_managed_tree(change.candidate, candidate)
        flush_tree(candidate)
        change.candidate = candidate
        _assert_unchanged(change.target, change.before)
        if change.tree_before is not None and _tree_fingerprint(change.target) != change.tree_before:
            raise ApplyError(f"managed directory changed while preparing candidate: {change.target}")
    if change.before.kind == "missing":
        try:
            os.rename(change.candidate, change.target)
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
    if os.name == "nt":
        os.rename(change.candidate, change.target)
    else:
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


def _guard_native_file_change(change: FileChange) -> None:
    """恢复/清理前沿当场已固定的发布像与备份像复核，拒绝权限或实体漂移。"""
    if change.published and change.body is not None:
        if change.native_published is None:
            raise ApplyError(f"native published file lacks its fixed witness; preserved: {change.target}")
        _check_native_source(change.target, change.native_published, max_bytes=change.io_max_bytes)
    elif change.published or change.backup is not None:
        if _native_path_snapshot(change.target, max_bytes=change.io_max_bytes) is not None:
            raise ApplyError(f"native target appeared after isolation; preserved current file and backup: {change.target}")
    if change.backup is not None:
        if change.native_backup is None:
            raise ApplyError(f"native backup lacks its fixed witness; preserved: {change.backup}")
        _check_native_source(change.backup, change.native_backup, max_bytes=change.io_max_bytes)


def _rollback_native_file(change: FileChange) -> None:
    """只撤回本轮已验证产物，再排他回接原 inode；外部更改绝不被覆盖。"""
    from lib.windows_fs import delete_regular, move_regular
    _guard_native_file_change(change)
    if change.published and change.body is not None:
        parent = os.open(change.target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            expected = change.native_published
            delete_regular(parent, change.target.name, expected={"identity": expected["identity"],
                "security": expected["security"], "sha256": hashlib.sha256(expected["payload"]).hexdigest()},
                max_bytes=change.io_max_bytes)
        finally:
            os.close(parent)
    if change.backup is not None:
        # 条件 move 在自己的 source HANDLE 内再核原完整像；target 若被重建，
        # no-replace 使恢复停止，保留原 backup 和并发目标，不做覆盖式 replace。
        source = os.open(change.backup.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            destination = os.open(change.target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                move_regular(change.backup.name, change.target.name, src_dir_fd=source,
                             dst_dir_fd=destination, expected=change.native_backup, max_bytes=change.io_max_bytes)
            finally:
                os.close(destination)
        finally:
            os.close(source)
        if change.backup.parent != change.target.parent:
            _fsync_directory(change.backup.parent)
    _fsync_directory(change.target.parent)


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
            if os.name == "nt" and isinstance(change, FileChange):
                if change.published or change.backup is not None:
                    _rollback_native_file(change)
                continue
            current = _fingerprint(change.target, read_file=False)
            if isinstance(change, FileChange) and (
                change in plan.hook_changes or change in plan.doc_changes
            ):
                # 回滚不能凭“事务曾拥有这个路径”就撤销后来的用户修改。未发布且无
                # 备份的条目没有可撤销动作；已发布条目须仍是本轮精确配置和权限。
                if not change.published and change.backup is None:
                    continue
                if change.body is None:
                    if current.kind != "missing":
                        raise ApplyError(f"Document changed after deletion; preserved current file and backup: {change.target}")
                elif change.published or current.kind != "missing":
                    if change in plan.doc_changes:
                        # 文档沿用本发布器的安全读取与既有路径快照，避免把 macOS
                        # 合法的 /var 临时目录别名误当成另一个宿主的入口路径碰撞。
                        actual = _read_regular(change.target, "published document")
                    else:
                        from lib.hosts.claude_instructions import read_file
                        actual = read_file(change.target)
                    if actual != change.body or current.mode != change.mode:
                        raise ApplyError(
                            f"{'Hook settings' if change in plan.hook_changes else 'Document'} changed after publication; preserved current file and backup: {change.target}"
                        )
                if change.backup is not None:
                    _assert_unchanged(change.backup, change.before)
                if change in plan.doc_changes and change.body is None and change.backup is not None:
                    # current 的 missing 只是先前采样。排他发布把“仍缺失”保留到
                    # 真正恢复动作，间隙用户重建时保留当前文件和原始备份并报冲突。
                    try:
                        publish_exclusive(change.backup, change.target)
                    except OSError as exc:
                        raise ApplyError(
                            f"Document changed after deletion; preserved current file and backup: {change.target}"
                        ) from exc
                    _fsync_directory(change.target.parent)
                    continue
                if change in plan.doc_changes and change.created_standard_index:
                    remove_created_standard(change.target, change.body, change.mode,
                                            (current.device, current.inode))
                    _fsync_directory(change.target.parent)
                    continue
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

    changes = [*plan.agent_changes, *plan.skill_changes, *plan.doc_changes, *plan.hook_changes]
    if os.name == "nt" and plan.agents_md is not None:
        changes.append(plan.agents_md)
    for change in changes:
        if os.name == "nt" and isinstance(change, FileChange):
            try:
                _guard_native_file_change(change)
                if change.backup is not None:
                    _discard_native_temp(change.backup, change.native_backup, max_bytes=change.io_max_bytes,
                                         allow_missing=False)
                    note_removal()
            except Exception as exc:
                errors.append(f"preserve native file or backup {change.target}: {exc}")
            continue
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
    if os.name != "nt" and plan.agents_md is not None and plan.agents_md.backup is not None:
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
    # 全部已批准输出在首个项目目录/文件创建前检查；不能写了前几个目标才发现
    # 最后合并入口超出可重读边界，再依靠补偿将一次本可纯拒绝的操作兜回来。
    for change in [*plan.agent_changes, *plan.doc_changes, *plan.hook_changes,
                   *([plan.agents_md] if plan.agents_md is not None else [])]:
        _check_file_budget(change.body, change.io_max_bytes)
    for path, expected in plan.root_fingerprints.items():
        _assert_unchanged(path, expected)
    try:
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


def publish_document_changes(project: Path, updates: dict[Path, bytes | None],
                             expected_inputs: dict[Path, bytes | None], validate_after,
                             *, desired_modes: dict[Path, int] | None = None) -> None:
    """受控文档发布复用现有事务，不建立另一套文件发布／回滚原语。

    调用方持有项目安装锁并提供规划时原字节；这里沿用单链接检查、条件发布、
    精确备份及并发内容保全。同步失败回滚，跨文件断电原子性不在既有保证范围内。
    """
    from lib.hosts.claude_instructions import read_file
    for body in updates.values():
        _check_file_budget(body, DOCUMENT_FILE_SIZE)
    plan = Plan(Path(__file__).resolve().parents[2], project, project, secrets.token_hex(12))
    backup_root = _require_real_directory(project, "document transaction backup root")
    for path, body in updates.items():
        if not path.is_relative_to(project) or read_file(path) != expected_inputs[path]:
            raise ApplyError(f"document input changed: {path}")
        before = _fingerprint(path)
        if before.kind == "file":
            # 严格规范目录只能包含合法叶文档，验收期间的原件备份统一留在项目根。
            # 必须在任何目标写入前确认同卷和空闲落点；跨卷不能退化为复制/删除，
            # 否则无法沿用既有原 inode 备份和精确回滚保证。
            if before.device != backup_root.device:
                raise ApplyError(f"document backup must stay on the project filesystem: {path}")
            backup = project / _temp_path(path, plan.nonce, "backup").name
            if _fingerprint(backup, read_file=False).kind != "missing":
                raise ApplyError(f"owned backup path already exists: {backup}")
        mode = (desired_modes or {}).get(path, before.mode if before.kind == "file" else 0o644)
        plan.doc_changes.append(FileChange(path, body, mode, before,
            created_standard_index=before.kind == "missing", io_max_bytes=DOCUMENT_FILE_SIZE))
    try:
        _assert_unchanged(project, backup_root)
        for change in plan.doc_changes:
            _publish_file(change, plan, backup_directory=project)
        validate_after()
        # 外部编辑器也可能继续写原 inode；清理备份前再核实，冲突保持可诊断原件。
        for change in plan.doc_changes:
            if change.backup is not None:
                _assert_unchanged(change.backup, change.before)
    except BaseException:
        _rollback(plan)
        raise
    _cleanup_committed(plan)


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
