#!/usr/bin/env python3
"""根据不可变 ProjectProfile 渲染精简的工程规范基线。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import quote

try:
    from .project_discovery import ProjectProfile
except ImportError:
    from project_discovery import ProjectProfile  # type: ignore[no-redef]


COMMON_BEGIN = b"<!-- agent-workflow:general-common:begin -->"
COMMON_END = b"<!-- agent-workflow:general-common:end -->"


def common_span(body: bytes) -> tuple[int, int] | None:
    """只认完整、唯一、独占行的受管标记；不凭标题或历史措辞猜测所有权。"""

    if COMMON_BEGIN not in body and COMMON_END not in body:
        return None
    intervals = []
    for marker in (COMMON_BEGIN, COMMON_END):
        matches = list(re.finditer(rb"(?m)^" + re.escape(marker) + rb"\r?$", body))
        if body.count(marker) != 1 or len(matches) != 1:
            raise ValueError("GENERAL.md has malformed or duplicate common managed markers")
        intervals.append((matches[0].start(), matches[0].start() + len(marker)))
    if intervals[0][0] >= intervals[1][0]:
        raise ValueError("GENERAL.md has reversed common managed markers")
    return intervals[0][0], intervals[1][1]


def common_block(body: bytes) -> bytes | None:
    """保留区块外的原始换行、字节和项目内容；源包只管理这一对标记之间的内容。"""

    span = common_span(body)
    return None if span is None else body[span[0]:span[1]]


def merge_general(current: bytes, rendered: bytes) -> bytes:
    """新文档使用完整模板；已有文档仅替换明确受管区，无标记时原样保留。"""

    replacement = common_block(rendered)
    if replacement is None:
        raise ValueError("GENERAL.md template is missing common managed markers")
    if not current:
        return rendered
    span = common_span(current)
    if span is None:
        return current
    merged = current[:span[0]] + replacement + current[span[1]:]
    # 项目专项不允许与新版通用区复用规则 ID；先拒绝，不能写出多义规范再补救。
    rules = re.findall(rb"\[([a-z0-9][a-z0-9._-]*)\]\s*\[(?:hard|advisory)\]", merged)
    if len(rules) != len(set(rules)):
        raise ValueError("GENERAL.md has duplicate rule IDs across common and project sections")
    return merged


def ensure_general_link(current: bytes, index: Path, general: Path) -> bytes:
    """已有索引只补缺失的 GENERAL 链接，不重排、替换或删除项目的其他入口。"""

    # 延迟导入以复用规范校验器的同一套链接解析，避免与其受管区校验形成循环导入。
    try:
        from .validate_project_docs import MARKDOWN_LINK_RE, normalized_link_target
    except ImportError:
        from validate_project_docs import MARKDOWN_LINK_RE, normalized_link_target
    text = current.decode("utf-8", errors="strict")
    if any(normalized_link_target(index, raw) == general.resolve()
           for raw in MARKDOWN_LINK_RE.findall(text)):
        return current
    relative = Path(os.path.relpath(general, index.parent)).as_posix()
    target = quote(relative, safe="/")
    newline = b"\r\n" if b"\r\n" in current else b"\n"
    separator = b"" if current.endswith(newline * 2) else newline if current.endswith(newline) else newline * 2
    addition = f"## Common engineering baseline\n\n- [General engineering rules]({target})\n"
    return current + separator + addition.encode("utf-8").replace(b"\n", newline)


def validate_planned_rule_ids(root: Path, updates: Mapping[Path, bytes]) -> None:
    """发布前以候选内容覆盖既有规范视图，拒绝通用区与其他专项叶的 ID 冲突。

    这里只检查规范目录和规则唯一性，不创建文件，也不读取功能/计划/原型正文。
    与最终目录验收复用同一个安全遍历器和规则解析式，避免两套规则产生偏差。
    """

    try:
        from .validate_project_docs import STANDARD_RULE_RE, collect_standard_leaves
    except ImportError:
        from validate_project_docs import STANDARD_RULE_RE, collect_standard_leaves
    errors: list[str] = []
    leaves = collect_standard_leaves(root, errors) if root.exists() else {}
    for path, body in updates.items():
        if path.parent == root and path.suffix == ".md":
            leaves[path.resolve()] = body.decode("utf-8", errors="strict")
    owners: dict[str, Path] = {}
    for path, body in leaves.items():
        for rule_id, _severity in STANDARD_RULE_RE.findall(body):
            previous = owners.get(rule_id)
            if previous is not None:
                errors.append(f"duplicate standards rule ID {rule_id}: {previous} and {path}")
            else:
                owners[rule_id] = path
    if errors:
        raise ValueError("; ".join(errors))


def _observed_baseline(profile: ProjectProfile) -> str:
    """只投影仓库可验证事实；不得把观察结果升级为项目硬规则。"""

    if not profile.modules:
        return "- No implementation module was discovered; add explicit rules only after verification."
    lines: list[str] = []
    for module in profile.modules:
        stacks = ", ".join(module.stack_facts) if module.stack_facts else "unknown"
        lines.append(
            f"- `{module.root}` → role `{module.primary_role}`; stacks: {stacks}; "
            f"evidence: {', '.join(module.evidence_paths) or 'none'}"
        )
        if module.verification_commands:
            encoded = ", ".join(
                json.dumps(list(command.argv), ensure_ascii=False)
                for command in module.verification_commands
            )
            lines.append(f"  - Discovered verification commands: {encoded}")
    return "\n".join(lines)


def render_template(
    source: str,
    substitutions: Mapping[str, str],
    *,
    profile: ProjectProfile,
) -> str:
    """渲染 GENERAL.md，并拒绝未知占位符以防模板漂移。"""

    # 新装也必须预先证明源模板边界有效，不能等文件写入项目后才发现半个受管区。
    if common_block(source.encode("utf-8")) is None:
        raise ValueError("GENERAL.md template is missing common managed markers")
    values = dict(substitutions)
    values["OBSERVED_BASELINE"] = _observed_baseline(profile)
    pattern = re.compile(r"\{\{([A-Z_]+)\}\}")
    unknown = sorted(set(pattern.findall(source)) - values.keys())
    if unknown:
        raise ValueError(
            "unknown standards baseline template placeholders: " + ", ".join(unknown)
        )
    return pattern.sub(lambda match: values[match.group(1)], source)
