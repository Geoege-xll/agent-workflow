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

python3 "${PACK_DIR}/lib/validate_project_config.py" \
  "${PROJECT_YAML}" "${PROJECT_ROOT}" "${ROLES_DIR}"

DOC_STANDARDS=$(py_yaml "${PROJECT_YAML}" docs standards)
DOC_STANDARDS_ROOT=$(py_yaml "${PROJECT_YAML}" docs standards_root)
DOC_PROJECT=$(py_yaml "${PROJECT_YAML}" docs project)
DOC_FEATURES_DIR=$(py_yaml "${PROJECT_YAML}" docs features)
DOC_PLANS_DIR=$(py_yaml "${PROJECT_YAML}" docs plans)
DOC_NOTES_DIR=$(py_yaml "${PROJECT_YAML}" docs notes)
# 规范直接放在 standards_root，原型仅保留一层子目录。
DOC_DESIGN_DIR="${DOC_STANDARDS_ROOT%/}"

log_info "Scaffold reduced project documents"
log_info "Project: ${PROJECT_NAME}  root: ${PROJECT_ROOT}"

python3 - \
  "${PROJECT_ROOT}" "${PACK_DIR}" "${TEMPLATES}" \
  "${PROJECT_NAME}" "${DATE_STR}" \
  "${DOC_STANDARDS}" "${DOC_STANDARDS_ROOT%/}" "${DOC_PROJECT}" "${DOC_FEATURES_DIR%/}" \
  "${DOC_PLANS_DIR%/}" "${DOC_NOTES_DIR%/}" \
  "${DOC_DESIGN_DIR%/}" <<'PY'
from __future__ import annotations

import os
import posixpath
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
    doc_features_dir,
    doc_plans_dir,
    doc_notes_dir,
    doc_design_dir,
) = sys.argv[1:]

project_root = Path(project_root_raw).resolve()
pack_root = Path(pack_root_raw).resolve()
template_root = Path(template_root_raw).resolve()
sys.path.insert(0, str(pack_root / "lib"))
from standards_baseline import (
    common_span, ensure_general_link, merge_general, validate_planned_rule_ids,
    render_template as render_standards_baseline,
)
from validate_project_config import validate_with_profile
from validate_project_docs import MARKDOWN_LINK_RE, normalized_link_target

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
            info = current.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SystemExit(f"scaffold parent must be a real directory: {current}")


def inspect_target(target: Path) -> tuple[str, int, int, int, int, int]:
    inspect_parent(target)
    try:
        info = target.lstat()
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
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o755)
            info = current.lstat()
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


def publish(
    target: Path,
    body: bytes,
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
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode, follow_symlinks=False)
        temporary_inode = temporary.stat(follow_symlinks=False).st_ino
        if not same_snapshot(target, before) or not original_matches(target):
            raise SystemExit(f"scaffold target changed before publish: {target}")
        inject_test_race(target, before)
        if before[0] == "missing":
            try:
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError as exc:
                raise SystemExit(
                    f"scaffold target appeared during atomic create: {target}"
                ) from exc
            temporary.unlink()
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
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError as exc:
            raise SystemExit(
                f"scaffold target appeared during atomic replace: {target}"
            ) from exc
        temporary.unlink()
        fsync_parent(target)
        if inspect_target(backup) != before or not original_matches(backup):
            published = inspect_target(target)
            if published[0] == "file" and published[2] == temporary_inode:
                os.replace(backup, target)
                fsync_parent(target)
            raise SystemExit(f"scaffold target changed during atomic replace: {target}")
        backup.unlink()
        fsync_parent(target)
    finally:
        if temporary.exists():
            temporary.unlink()
        backup_candidate = Path(f"{temporary}.backup")
        if backup_candidate.exists():
            current = inspect_target(target)
            if current[0] == "missing":
                os.replace(backup_candidate, target)
                fsync_parent(target)
            elif inspect_target(backup_candidate) == before and original_matches(backup_candidate):
                backup_candidate.unlink()
                fsync_parent(target)
    return "updated" if original is not None else "created"


values = {
    "PROJECT_NAME": project_name,
    "DATE": date,
    "DOC_STANDARDS": doc_standards,
    "DOC_STANDARDS_ROOT": doc_standards_root,
    "DOC_PROJECT": doc_project,
    "DOC_FEATURES_DIR": doc_features_dir,
    "DOC_PLANS_DIR": doc_plans_dir,
    "DOC_NOTES_DIR": doc_notes_dir,
    "DOC_DESIGN_DIR": doc_design_dir,
    # Markdown 链接必须相对 STANDARDS.md 自身计算，不能直接复用项目根相对路径；
    # 否则位于 docs/ 下的索引会错误解析成 docs/docs/standards/。
    "ENGINEERING_STANDARDS_INDEX": (
        f"- [General engineering rules]({posixpath.relpath(f'{doc_standards_root}/GENERAL.md', posixpath.dirname(doc_standards))})\n"
        f"- [Upstream and second-development boundaries]({posixpath.relpath(f'{doc_standards_root}/UPSTREAM.md', posixpath.dirname(doc_standards))})"
    ),
    # 索引只链接当前项目实际启用的设计规范叶文档，非 UI 项目不生成空设计权威。
    "DESIGN_STANDARDS_INDEX": (
        f"- [Design foundations]({posixpath.relpath(f'{doc_standards_root}/DESIGN_FOUNDATIONS.md', posixpath.dirname(doc_standards))})\n"
        f"- [Component and interaction standards]({posixpath.relpath(f'{doc_standards_root}/DESIGN_COMPONENTS.md', posixpath.dirname(doc_standards))})"
        if ui_enabled
        else "- No design standards are configured for the discovered project profile."
    ),
}

try:
    general_engineering_text = regular_source(
        template_root / "standards/GENERAL.md"
    ).decode(
        "utf-8", errors="strict"
    )
except UnicodeDecodeError as exc:
    raise SystemExit("general engineering standards template must be UTF-8") from exc
try:
    general_engineering_body = render_standards_baseline(
        general_engineering_text, values, profile=profile
    ).encode("utf-8")
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

candidates: list[tuple[Path, bytes]] = [
    (within_project(doc_standards), render(template_root / "STANDARDS.md", values)),
    (
        within_project(f"{doc_standards_root}/GENERAL.md"),
        general_engineering_body,
    ),
    (
        within_project(f"{doc_standards_root}/UPSTREAM.md"),
        render(template_root / "standards/UPSTREAM.md", values),
    ),
    (within_project(doc_project), render(template_root / "PROJECT.md", values)),
]
# GENERAL 是默认基础规范；其他工程叶仍由项目目录决定，不能在自定义索引旁
# 补出一个未被收录的 UPSTREAM.md，导致仅补通用入口也无法通过目录校验。
standards_index = within_project(doc_standards)
if inspect_target(standards_index)[0] == "file":
    index_body = regular_source(standards_index).decode("utf-8")
    if index_body.strip():
        indexed = {normalized_link_target(standards_index, raw)
                   for raw in MARKDOWN_LINK_RE.findall(index_body)}
        upstream_target = within_project(f"{doc_standards_root}/UPSTREAM.md")
        candidates = [(path, body) for path, body in candidates
                      if path != upstream_target or path.resolve() in indexed]
if ui_enabled:
    # 仅设计模板受自定义设计索引限制；项目入口等核心候选保留在独立列表中。
    # 不能用目标文件名的 DESIGN_ 前缀推断类型，否则合法的自定义入口会被漏生成。
    design_candidates = [
        (
            within_project(f"{doc_standards_root}/DESIGN_FOUNDATIONS.md"),
            render(template_root / "standards/DESIGN_FOUNDATIONS.md", values),
        ),
        (
            within_project(f"{doc_standards_root}/DESIGN_COMPONENTS.md"),
            render(template_root / "standards/DESIGN_COMPONENTS.md", values),
        ),
    ]
    # 既有自定义索引是项目的规范目录；新增角色/模块不能自动注入未被目录收录的
    # 设计模板。首次安装或空索引由上面的完整模板负责，仍会补齐默认设计规范。
    standards_index = within_project(doc_standards)
    if inspect_target(standards_index)[0] == "file":
        index_body = regular_source(standards_index).decode("utf-8")
        if index_body.strip():
            indexed = {normalized_link_target(standards_index, raw)
                       for raw in MARKDOWN_LINK_RE.findall(index_body)}
            design_candidates = [(path, body) for path, body in design_candidates
                                 if path.resolve() in indexed]
    candidates.extend(design_candidates)

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
        candidates.append(
            (
                prototype_root / "index.html",
                regular_source(pack_root / "templates/prototype/index.html"),
            )
        )
        candidates.append(
            (
                prototype_root / "prototype.css",
                regular_source(pack_root / "templates/prototype/prototype.css"),
            )
        )

snapshots: dict[Path, tuple[str, int, int, int, int, int]] = {}
for target, _body in candidates:
    snapshots[target] = inspect_target(target)

# 只有 GENERAL 的明确受管区与索引补链可更新非空文件。先规划所有变化，
# 标记损坏或规则冲突时尚未发布任何文档；无法识别的项目规范仅保留并提示。
originals: dict[Path, bytes] = {}
planned: list[tuple[Path, bytes]] = []
general_target = within_project(f"{doc_standards_root}/GENERAL.md")
index_target = within_project(doc_standards)
for target, body in candidates:
    before = snapshots[target]
    if target in (general_target, index_target) and before[0] == "file" and before[4] > 0:
        current = regular_source(target)
        try:
            if target == general_target:
                body = merge_general(current, body)
                if common_span(current) is None:
                    print(f"[WARN] {target}: common region is unmarked; preserved unchanged; controlled adoption required")
            else:
                body = ensure_general_link(current, index_target, general_target)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if body != current:
            originals[target] = current
    planned.append((target, body))
candidates = planned
try:
    validate_planned_rule_ids(within_project(doc_standards_root), {
        target: body for target, body in candidates
        if snapshots[target][0] == "missing" or snapshots[target][4] == 0 or target in originals
    })
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

# features/ 只保存真实功能文档，不用 README 或 .gitkeep 伪造一个功能条目。这里先验证
# 该路径不是符号链接或普通文件，全部受控文件发布成功后再创建空目录。
features_root = within_project(doc_features_dir)
inspect_parent(features_root)
try:
    features_info = features_root.lstat()
except FileNotFoundError:
    pass
else:
    if stat.S_ISLNK(features_info.st_mode) or not stat.S_ISDIR(features_info.st_mode):
        raise SystemExit(f"feature document root must be a real directory: {features_root}")
for target, body in candidates:
    result = publish(target, body, snapshots[target], originals.get(target))
    print(f"{result}: {target.relative_to(project_root)}")

ensure_directory(features_root)
print(f"ready: {features_root.relative_to(project_root)}/")
PY

python3 "${PACK_DIR}/lib/validate_project_docs.py" "${PROJECT_YAML}" "${PROJECT_ROOT}"

log_info "Document scaffold complete; managed common rules refreshed, project sections preserved."
