#!/usr/bin/env bash
# Scaffold the reduced portable document set without overwriting project content.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

TEMPLATES="${PACK_DIR}/templates/docs"
PROJECT_YAML="${PACK_DIR}/project.yaml"
PROJECT_NAME=$(py_yaml "${PROJECT_YAML}" project_name 2>/dev/null || echo "MyProject")
DATE_STR=$(date +%Y-%m-%d)

python3 "${PACK_DIR}/lib/project/validate_project_config.py" \
  "${PROJECT_YAML}" "${PROJECT_ROOT}" "${ROLES_DIR}"

DOC_STANDARDS=$(py_yaml "${PROJECT_YAML}" docs standards)
DOC_STANDARDS_ROOT=$(py_yaml "${PROJECT_YAML}" docs standards_root)
DOC_PROJECT=$(py_yaml "${PROJECT_YAML}" docs project)
DOC_PLANS_DIR=$(py_yaml "${PROJECT_YAML}" docs plans)
# 规范直接放在 standards_root，原型仅保留一层子目录。
DOC_DESIGN_DIR="${DOC_STANDARDS_ROOT%/}"

log_info "Scaffold reduced project documents"
log_info "Project: ${PROJECT_NAME}  root: ${PROJECT_ROOT}"

python3 --workflow-paths=1,2,3 - \
  "${PROJECT_ROOT}" "${PACK_DIR}" "${TEMPLATES}" \
  "${PROJECT_NAME}" "${DATE_STR}" \
  "${DOC_STANDARDS}" "${DOC_STANDARDS_ROOT%/}" "${DOC_PROJECT}" \
  "${DOC_PLANS_DIR%/}" \
  "${DOC_DESIGN_DIR%/}" <<'PY'
from __future__ import annotations

import os
import re
import stat
import sys
import tempfile
from pathlib import Path

(
    project_root_raw,
    pack_root_raw,
    template_root_raw,
    project_name,
    date,
    doc_standards,
    doc_standards_root,
    doc_project,
    doc_plans_dir,
    doc_design_dir,
) = sys.argv[1:]

project_root = Path(project_root_raw).resolve()
pack_root = Path(pack_root_raw).resolve()
template_root = Path(template_root_raw).resolve()
# 所属模块统一从可信包根导入；不能把 lib 本身当搜索根，也不能借用业务项目的同名包。
sys.path.insert(0, str(pack_root))
from lib.platform_fs import os, publish_exclusive
from lib.documents.standards_baseline import plan_standard_updates
from lib.project.validate_project_config import validate_with_profile

validation = validate_with_profile(
    pack_root / "project.yaml", project_root, pack_root / "roles"
)
if validation.errors or validation.profile is None:
    raise SystemExit(
        "cannot scaffold from invalid discovered project profile: "
        + "; ".join(validation.errors or ("profile is missing",))
    )
profile = validation.profile
# UI/UX 是基础可用角色；是否初始化设计文档仍由当前项目形态决定。
ui_enabled = profile.design_scaffold_required


def regular_source(path: Path) -> bytes:
    if os.name == "nt":
        from lib.windows_fs import read_file
        body = read_file(path)
        if body is None:
            raise SystemExit(f"template is missing: {path}")
        return body
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SystemExit(f"template must be a single-link regular file: {path}")
    return path.read_bytes()


def render(path: Path, values: dict[str, str]) -> bytes:
    try:
        source = regular_source(path).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"template must be UTF-8: {path}") from exc
    pattern = re.compile(r"\{\{([A-Z_]+)\}\}")
    unknown = sorted(set(pattern.findall(source)) - values.keys())
    if unknown:
        raise SystemExit(
            f"unknown template placeholders in {path}: {', '.join(unknown)}"
        )
    return pattern.sub(lambda match: values[match.group(1)], source).encode("utf-8")


def within_project(relative: str) -> Path:
    target = project_root / relative
    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise SystemExit(f"scaffold target escapes project root: {relative}") from exc
    return target


def inspect_parent(target: Path) -> None:
    relative = target.parent.relative_to(project_root)
    current = project_root
    for part in relative.parts:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SystemExit(f"scaffold parent must be a real directory: {current}")


def inspect_target(target: Path) -> tuple[str, int, int, int, int, int]:
    inspect_parent(target)
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        return ("missing", 0, 0, 0, 0, 0)
    if not stat.S_ISREG(info.st_mode):
        raise SystemExit(f"scaffold target must be a real regular file: {target}")
    if info.st_nlink != 1:
        raise SystemExit(f"hard link is forbidden for scaffold target: {target}")
    return (
        "file",
        info.st_dev,
        info.st_ino,
        info.st_nlink,
        info.st_size,
        stat.S_IMODE(info.st_mode),
    )


def ensure_directory(path: Path) -> None:
    relative = path.relative_to(project_root)
    current = project_root
    for part in relative.parts:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            os.mkdir(current, 0o755)
            info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SystemExit(f"scaffold directory must be real: {current}")


def same_snapshot(
    target: Path, expected: tuple[str, int, int, int, int, int]
) -> bool:
    return inspect_target(target) == expected


def fsync_parent(target: Path) -> None:
    directory_fd = os.open(
        target.parent,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def inject_test_race(
    target: Path, before: tuple[str, int, int, int, int, int]
) -> None:
    raw = os.environ.get("AGENT_WORKFLOW_PACK_TEST_SCAFFOLD_RACE", "")
    if not raw:
        return
    expected_kind = "missing" if before[0] == "missing" else "empty" if before[4] == 0 else "managed"
    expected = f"{expected_kind}:{target.relative_to(project_root).as_posix()}"
    if raw != expected:
        return
    flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if before[0] == "missing":
        flags |= os.O_CREAT | os.O_EXCL
    else:
        flags |= os.O_TRUNC
    descriptor = os.open(target, flags, 0o600)
    try:
        payload = (b"X" * before[4] if expected_kind == "managed"
                   else b"concurrent user content\n")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_parent(target)


def publish(target: Path, body: bytes | None, before: tuple, original: bytes | None = None) -> str:
    if os.name != "nt":
        return _publish(target, body, before, original)
    from lib.windows_fs import Directory
    ensure_directory(target.parent)
    with Directory(target.parent):
        return _publish(target, body, before, original)


def _publish(
    target: Path,
    body: bytes | None,
    before: tuple[str, int, int, int, int, int],
    original: bytes | None = None,
) -> str:
    if before[0] == "file" and before[4] > 0 and original is None:
        return "preserved"
    # 非空文档只有明确规划的通用区更新/索引补链能进入替换；逐字节复核，
    # 防止同长度的并发项目编辑逃过 inode、大小与权限快照检查。
    def original_matches(path: Path) -> bool:
        return original is None or regular_source(path) == original

    ensure_directory(target.parent)
    if not same_snapshot(target, before) or not original_matches(target):
        raise SystemExit(f"scaffold target changed after preflight: {target}")
    mode = before[5] if before[0] == "file" else 0o644
    descriptor, temporary_raw = tempfile.mkstemp(
        prefix=f".{target.name}.agent-workflow.", dir=target.parent
    )
    temporary = Path(temporary_raw)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body or b"")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode, follow_symlinks=False)
        temporary_inode = os.stat(temporary, follow_symlinks=False).st_ino
        if not same_snapshot(target, before) or not original_matches(target):
            raise SystemExit(f"scaffold target changed before publish: {target}")
        inject_test_race(target, before)
        if before[0] == "missing":
            try:
                publish_exclusive(temporary, target)
            except FileExistsError as exc:
                raise SystemExit(
                    f"scaffold target appeared during atomic create: {target}"
                ) from exc
            fsync_parent(target)
            return "created"

        backup = Path(f"{temporary}.backup")
        if backup.exists() or backup.is_symlink():
            raise SystemExit(f"scaffold backup path already exists: {backup}")
        os.replace(target, backup)
        fsync_parent(target)
        if inspect_target(backup) != before or not original_matches(backup):
            if inspect_target(target)[0] == "missing":
                os.replace(backup, target)
                fsync_parent(target)
            raise SystemExit(f"scaffold target changed during publish: {target}")
        if body is None:
            # 只有迁移计划证明为纯默认副本才可删除。先移到本次事务的精确备份，
            # 再核对原始字节，避免同大小并发编辑被删除；用户重建同名文件时保留它。
            if inspect_target(target)[0] != "missing":
                raise SystemExit(f"scaffold target appeared during delete: {target}")
            if inspect_target(backup) != before or not original_matches(backup):
                raise SystemExit(f"scaffold target changed during delete: {target}")
            os.unlink(backup)
            fsync_parent(target)
            return "deleted"
        if os.name == "nt":
            from lib.windows_fs import copy_permissions
            copy_permissions(backup, temporary)
        try:
            publish_exclusive(temporary, target)
        except FileExistsError as exc:
            raise SystemExit(
                f"scaffold target appeared during atomic replace: {target}"
            ) from exc
        fsync_parent(target)
        if inspect_target(backup) != before or not original_matches(backup):
            published = inspect_target(target)
            if published[0] == "file" and published[2] == temporary_inode:
                os.replace(backup, target)
                fsync_parent(target)
            raise SystemExit(f"scaffold target changed during atomic replace: {target}")
        os.unlink(backup)
        fsync_parent(target)
    finally:
        if temporary.exists():
            os.unlink(temporary)
        backup_candidate = Path(f"{temporary}.backup")
        if backup_candidate.exists():
            current = inspect_target(target)
            if current[0] == "missing":
                os.replace(backup_candidate, target)
                fsync_parent(target)
            elif inspect_target(backup_candidate) == before and original_matches(backup_candidate):
                os.unlink(backup_candidate)
                fsync_parent(target)
    return "updated" if original is not None else "created"


values = {
    "PROJECT_NAME": project_name,
    "DATE": date,
    "DOC_STANDARDS": doc_standards,
    "DOC_STANDARDS_ROOT": doc_standards_root,
    "DOC_PROJECT": doc_project,
    "DOC_PLANS_DIR": doc_plans_dir,
    "DOC_DESIGN_DIR": doc_design_dir,
}

# 规则正文只在内置 Skill 维护。先得到全部规范候选再发布任何文档，重复 ID、损坏
# 标记或未知差异会在此失败，不把项目材料变成占位规则或按文件名删除。
try:
    standard_inputs: dict[Path, bytes | None] = {}
    standard_updates = plan_standard_updates(
        pack_root, project_root,
        docs={"standards": doc_standards, "standards_root": doc_standards_root,
              "project": doc_project, "plans": doc_plans_dir},
        profile=profile,
        expected_inputs=standard_inputs,
    )
except ValueError as exc:
    raise SystemExit(str(exc)) from exc
candidates: list[tuple[Path, bytes | None]] = [
    *standard_updates.items(),
    (within_project(doc_project), render(template_root / "PROJECT.md", values)),
]

if ui_enabled:
    prototype_root = within_project(f"{doc_design_dir}/prototype")
    inspect_parent(prototype_root)
    try:
        prototype_info = prototype_root.lstat()
    except FileNotFoundError:
        prototype_active = False
    else:
        if stat.S_ISLNK(prototype_info.st_mode) or not stat.S_ISDIR(
            prototype_info.st_mode
        ):
            raise SystemExit(
                f"prototype workspace must be a real directory: {prototype_root}"
            )
        prototype_active = any(prototype_root.iterdir())
    if not prototype_active:
        # 初始化时完整发布同版本工作区、反馈辅助资源与页面桥接，避免入口引用
        # 尚未复制的反馈文件。非空旧项目仍保留原索引、样式和业务页，不补写
        # 新资产或覆盖既有活跃原型；升级仍须取得该项目当前明确写入授权。
        for name in ("index.html", "prototype.css", "workspace.css", "workspace.js", "page-shell.js",
                     "feedback.css", "feedback.js"):
            candidates.append((prototype_root / name, regular_source(pack_root / "templates/prototype" / name)))

snapshots: dict[Path, tuple[str, int, int, int, int, int]] = {}
for target, _body in candidates:
    snapshots[target] = inspect_target(target)

# 规范候选已经由共享计划完成归属检查；非空项目入口继续原样保留。
originals = {}
for target, expected in standard_inputs.items():
    actual = regular_source(target) if snapshots[target][0] == "file" else None
    if actual != expected:
        raise SystemExit(f"scaffold target changed after document planning: {target}")
    if actual is not None:
        originals[target] = actual

# plans 按真实主题惰性创建，安装不制造空目录或需求占位。
for target, body in candidates:
    result = publish(target, body, snapshots[target], originals.get(target))
    print(f"{result}: {target.relative_to(project_root)}")

PY

python3 "${PACK_DIR}/lib/validate_project_docs.py" "${PROJECT_YAML}" "${PROJECT_ROOT}"

log_info "Document scaffold complete; builtin rules remain in Skills, project-specific content preserved."
