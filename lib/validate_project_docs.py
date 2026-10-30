#!/usr/bin/env python3
"""Validate the PROJECT/features current truth and STANDARDS directory model."""

from __future__ import annotations

import re
import os
import stat
import sys
from pathlib import Path
from urllib.parse import unquote

sys.dont_write_bytecode = True

try:
    from .standards_baseline import common_block
    from .standard_paths import canonical_standard_path, standard_domain
    from .validate_project_config import section_lines, strip_inline_comment
except ImportError:
    from standards_baseline import common_block
    from standard_paths import canonical_standard_path, standard_domain
    from validate_project_config import section_lines, strip_inline_comment  # type: ignore[no-redef]


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
FEATURE_ID_RE = re.compile(
    r"(?im)^\s*-\s*(?:Feature ID|功能 ID)\s*[:：]\s*`?([A-Za-z0-9._-]+)`?\s*$"
)
ACTIVE_STATUS_RE = re.compile(
    r"(?im)^\s*-\s*(?:Status|状态)\s*[:：]\s*`?active`?\s*$"
)
REMOVED_STATUS_RE = re.compile(
    r"(?im)^\s*-\s*(?:Status|状态)\s*[:：]\s*`?removed`?\s*$"
)
REMOVAL_DATE_RE = re.compile(r"(?im)^\s*-\s*(?:Removal date|删除日期)\s*[:：]\s*\S+")
REMOVAL_REASON_RE = re.compile(r"(?im)^\s*-\s*(?:Removal reason|删除原因)\s*[:：]\s*\S+")
STANDARD_RULE_RE = re.compile(r"\[([a-z0-9][a-z0-9._-]*)\]\s*\[(hard|advisory)\]")


def parse_docs(config: Path) -> dict[str, str]:
    """只解析受控 docs 段；完整路径安全性仍由 validate_project_config 负责。"""

    lines = config.read_text(encoding="utf-8").splitlines()
    result: dict[str, str] = {}
    for raw in section_lines(lines, "docs"):
        match = re.match(r"^  ([A-Za-z0-9_]+):\s*(.*?)\s*$", raw)
        if match:
            result[match.group(1)] = strip_inline_comment(match.group(2)).strip("\"'")
    return result


def read_single_link_regular(path: Path, label: str, errors: list[str]) -> str | None:
    """拒绝符号链接和硬链接，避免校验时把项目外内容当成权威文档。"""

    try:
        info = path.lstat()
    except FileNotFoundError:
        errors.append(f"missing {label}: {path}")
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        errors.append(f"{label} must be a single-link regular file: {path}")
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read UTF-8 {label} {path}: {exc}")
        return None


def normalized_link_target(project_doc: Path, raw: str) -> Path | None:
    """解析普通 Markdown 文件链接；外部 URL、页内锚点和带标题写法不进入功能校验。"""

    candidate = raw.strip()
    if candidate.startswith("<") and ">" in candidate:
        candidate = candidate[1 : candidate.index(">")]
    else:
        candidate = candidate.split(maxsplit=1)[0]
    candidate = unquote(candidate.split("#", 1)[0].split("?", 1)[0])
    if not candidate or candidate.startswith("#") or "://" in candidate:
        return None
    path = Path(candidate)
    if path.is_absolute():
        return path.resolve()
    return (project_doc.parent / path).resolve()


def collect_standard_leaves(root: Path, errors: list[str]) -> dict[Path, str]:
    """安全遍历规范目录，并返回所有 Markdown 叶文档。

    规范是所有实现 Agent 与 QA 的强制输入，所以目录中任何符号链接、特殊节点或
    多硬链接文件都可能把项目外内容伪装成规则权威；这里逐层 ``lstat``，不跟随它们。
    ``prototype`` 是 HTML/CSS 设计证据，不是规范叶；完整节点与依赖安全由
    ``validate_prototype_workspace.py`` 独立负责。功能方案归 plans/features，
    不再以 references 子目录混入规范树。
    """

    leaves: dict[Path, str] = {}
    prototype_root = root / "prototype"

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            errors.append(f"cannot inspect standards directory {directory}: {exc}")
            return
        for entry in entries:
            path = Path(entry.path)
            try:
                info = path.lstat()
            except OSError as exc:
                errors.append(f"cannot inspect standards entry {path}: {exc}")
                continue
            if stat.S_ISLNK(info.st_mode):
                errors.append(f"standards tree must not contain symlinks: {path}")
            elif stat.S_ISDIR(info.st_mode):
                if path != prototype_root:
                    errors.append(f"standards leaves must be shallow; migrate nested directory: {path}")
            elif stat.S_ISREG(info.st_mode) and path.suffix == ".md":
                body = read_single_link_regular(path, "standards leaf", errors)
                if body is not None:
                    leaves[path.resolve()] = body
            else:
                errors.append(f"standards tree contains unsupported entry: {path}")

    visit(root)
    return leaves


def validate(config: Path, project_root: Path) -> list[str]:
    """检查语义边界，不对 PROJECT.md 设置行数或字节数限制。"""

    errors: list[str] = []
    docs = parse_docs(config)
    standards_value = docs.get("standards")
    standards_root_value = docs.get("standards_root")
    project_value = docs.get("project")
    features_value = docs.get("features")
    if not standards_value or not standards_root_value or not project_value or not features_value:
        return ["docs.standards, docs.standards_root, docs.project and docs.features are required"]

    root = project_root.resolve()
    standards_path = root / standards_value
    standards_root_path = root / standards_root_value
    project_path = root / project_value
    features_path = root / features_value
    standards_doc = standards_path.resolve()
    standards_root = standards_root_path.resolve()
    project_doc = project_path.resolve()
    features_root = features_path.resolve()
    if not all(
        path.is_relative_to(root)
        for path in (standards_doc, standards_root, project_doc, features_root)
    ):
        return ["controlled document paths must stay within project root"]
    if standards_doc.is_relative_to(standards_root):
        errors.append("docs.standards must stay outside docs.standards_root")

    # 本次升级明确不保留旧 STATUS/SPEC 权威层。这里检查的是固定遗留位置，
    # 即使 PROJECT.md 没有链接它们，也必须移除，防止 Agent 或人工搜索时继续
    # 把旧文件误当成第二份当前事实。历史内容由 Git 和迁移后的 feature 文档保留。
    for legacy_name in ("STATUS.md", "SPEC.md", "ENGINEERING.md", "DESIGN_SYSTEM.md"):
        legacy_path = root / "docs" / legacy_name
        try:
            legacy_path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"cannot inspect unsupported legacy authority {legacy_path}: {exc}")
        else:
            errors.append(
                f"unsupported legacy authority must be removed after direct upgrade: {legacy_path}"
            )

    # 使用未 resolve 的配置路径做 lstat，才能真正识别最后一级符号链接，而不是在
    # 跟随链接后把项目外文件误判为普通受控文档。
    standards_body = read_single_link_regular(standards_path, "standards index", errors)
    project_body = read_single_link_regular(project_path, "project index", errors)
    try:
        standards_root_info = standards_root_path.lstat()
    except FileNotFoundError:
        errors.append(f"missing standards directory: {standards_root}")
        return errors
    if stat.S_ISLNK(standards_root_info.st_mode) or not stat.S_ISDIR(
        standards_root_info.st_mode
    ):
        errors.append(f"standards root must be a real directory: {standards_root}")
        return errors
    standards_leaves = collect_standard_leaves(standards_root_path, errors)
    if not standards_leaves:
        errors.append("standards directory requires at least one normative Markdown leaf")
    rule_owners: dict[str, Path] = {}
    for path, body in standards_leaves.items():
        if path == standards_root / "GENERAL.md":
            # 无标记的项目文件不自动接管；受管文件则必须有完整边界，且 --check
            # 能发现通用区未随当前运行时更新。专项区不参与源包字节一致性比较。
            try:
                installed = common_block(body.encode("utf-8"))
                template = config.parent / "templates/docs/standards/GENERAL.md"
                if installed is not None and template.is_file():
                    expected = common_block(template.read_bytes())
                    if expected is None or installed != expected:
                        errors.append("GENERAL.md managed common region differs from source; run setup to refresh")
            except ValueError as exc:
                errors.append(str(exc))
        # 显式类型与路径类型一致，避免在扁平目录中偷换工程/设计权限。
        declared_domains = re.findall(r"(?im)^- Domain: (engineering|design)\s*$", body)
        expected_domain = standard_domain(str(path), str(standards_root))
        if not canonical_standard_path(str(path), str(standards_root)) or declared_domains != [expected_domain]:
            errors.append(f"standards leaf must declare Domain: {expected_domain}: {path}")
        matches = STANDARD_RULE_RE.findall(body)
        if not matches:
            errors.append(f"standards leaf has no stable severity-tagged rule: {path}")
            continue
        for rule_id, _severity in matches:
            previous = rule_owners.get(rule_id)
            if previous is not None:
                errors.append(f"duplicate standards rule ID {rule_id}: {previous} and {path}")
            else:
                rule_owners[rule_id] = path

    if standards_body is not None:
        if STANDARD_RULE_RE.search(standards_body):
            errors.append("STANDARDS.md is an index and must not define leaf rules")
        linked_leaves: set[Path] = set()
        for raw in MARKDOWN_LINK_RE.findall(standards_body):
            target = normalized_link_target(standards_doc, raw)
            if target is None or not target.is_relative_to(standards_root):
                continue
            if target == standards_root / "prototype" or target.is_relative_to(standards_root / "prototype"):
                # 原型目录/页面是证据链接，不要求有 Markdown 规则 ID。
                if not target.exists():
                    errors.append(f"STANDARDS.md links missing prototype evidence: {target}")
                continue
            if target not in standards_leaves:
                errors.append(f"STANDARDS.md links missing or non-regular standards leaf: {target}")
            else:
                linked_leaves.add(target)
        for path in sorted(set(standards_leaves) - linked_leaves):
            errors.append(f"standards leaf is not linked from STANDARDS.md: {path}")
    try:
        features_info = features_path.lstat()
    except FileNotFoundError:
        errors.append(f"missing feature document directory: {features_root}")
        return errors
    if stat.S_ISLNK(features_info.st_mode) or not stat.S_ISDIR(features_info.st_mode):
        errors.append(f"feature document root must be a real directory: {features_root}")
        return errors
    if project_body is None:
        return errors

    # 直接升级后，旧文件名也不得以文字或链接重新进入唯一入口，否则会恢复双重真相。
    for legacy in ("STATUS.md", "SPEC.md", "ENGINEERING.md", "DESIGN_SYSTEM.md"):
        if legacy in project_body:
            errors.append(f"PROJECT.md must not reference legacy authority {legacy}")

    active_docs: set[Path] = set()
    removed_docs: set[Path] = set()
    feature_ids: dict[str, Path] = {}
    for path in sorted(features_root.rglob("*.md")):
        body = read_single_link_regular(path, "feature document", errors)
        if body is None:
            continue
        is_removed = path.name.endswith(".removed.md")
        (removed_docs if is_removed else active_docs).add(path.resolve())

        feature_id_match = FEATURE_ID_RE.search(body)
        if feature_id_match is None:
            errors.append(f"feature document missing stable Feature ID: {path}")
        else:
            feature_id = feature_id_match.group(1).casefold()
            previous = feature_ids.get(feature_id)
            if previous is not None:
                errors.append(f"duplicate Feature ID {feature_id}: {previous} and {path}")
            else:
                feature_ids[feature_id] = path

        if is_removed:
            if REMOVED_STATUS_RE.search(body) is None:
                errors.append(f"removed feature must declare Status: removed: {path}")
            if REMOVAL_DATE_RE.search(body) is None:
                errors.append(f"removed feature missing removal date: {path}")
            if REMOVAL_REASON_RE.search(body) is None:
                errors.append(f"removed feature missing removal reason: {path}")
            if "historical" not in body.casefold() and "历史" not in body:
                errors.append(f"removed feature must label former requirements as historical: {path}")
        elif ACTIVE_STATUS_RE.search(body) is None:
            errors.append(f"active feature must declare Status: active: {path}")

    linked_active: set[Path] = set()
    for raw in MARKDOWN_LINK_RE.findall(project_body):
        target = normalized_link_target(project_doc, raw)
        if target is None or not target.is_relative_to(features_root):
            continue
        if target in removed_docs or target.name.endswith(".removed.md"):
            errors.append(f"PROJECT.md must not link removed feature: {target}")
        elif target not in active_docs:
            errors.append(f"PROJECT.md links missing or non-regular active feature: {target}")
        else:
            linked_active.add(target)

    for path in sorted(active_docs - linked_active):
        errors.append(f"active feature is not linked from PROJECT.md: {path}")
    return errors


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate_project_docs.py PROJECT_YAML PROJECT_ROOT", file=sys.stderr)
        return 2
    errors = validate(Path(sys.argv[1]), Path(sys.argv[2]))
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print("[OK] PROJECT/features and STANDARDS directory contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
