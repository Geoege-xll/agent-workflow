#!/usr/bin/env python3
"""解析主题生命周期与 PROJECT 基线索引；不从完成状态推断批准或当前事实。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit

try:
    from .claude_instructions import read_file
except ImportError:
    from claude_instructions import read_file


SECTIONS = (
    "目标与范围", "需求与验收", "方案与原型关联", "当前进展与恢复入口",
    "验收结果与当前已交付行为", "批准依据与必要证据",
)
FIELDS = ("主题 ID", "阶段", "模块", "任务等级", "已验收版本")
STAGES = frozenset({"draft", "active", "paused", "completed", "cancelled", "removed"})
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
EMPTY = frozenset({"", "none", "todo", "pending", "待确认", "无", "未验收"})


@dataclass(frozen=True)
class PlanDocument:
    """执行阶段与已验收版本是独立事实；后续迭代不会隐式撤销原有基线。"""

    topic_id: str
    stage: str
    modules: str
    task_level: str
    accepted_version: str
    sections: dict[str, str]
    approval_basis: str
    acceptance_evidence: str

    @property
    def has_current_baseline(self) -> bool:
        return self.accepted_version != "none" and self.stage != "removed"


def scalar(value: str) -> str:
    """只去掉一对行内代码符号；不能宽松吞掉损坏的元信息或占位值。"""
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    return value.strip()


def evidence_value(section: str, key: str, label: str) -> str:
    values = re.findall(r"(?m)^- " + re.escape(key) + r"[:：][ \t]*(.+)$", section)
    if len(values) != 1:
        raise ValueError(f"{label}: 已验收基线须有唯一的 {key} 引用")
    value = scalar(values[0])
    if value.casefold() in EMPTY or any(token in value for token in ("**TODO**", "{{", "<")):
        raise ValueError(f"{label}: {key} 不能是待定或模板占位")
    return value


def parse_plan(body: str, label: str, *, required: bool = False) -> PlanDocument | None:
    """只认明确的中文元信息合同；未索引旧稿不因标题或 completed 成为当前基线。

    Full 采用六节完整形状。Light 的无基线恢复稿可以少节；一旦 PROJECT 引用其
    已验收行为，仍须具备基线和证据两节。字段仅描述可恢复的既有事实，不授予批准。
    """
    header = re.split(r"(?m)^## ", body, maxsplit=1)[0]
    if not re.search(r"(?m)^- 主题 ID[:：]", header):
        if required:
            raise ValueError(f"{label}: PROJECT 不能把无生命周期元信息的历史计划作为当前基线")
        return None
    values = {}
    for field in FIELDS:
        matches = re.findall(r"(?m)^- " + re.escape(field) + r"[:：][ \t]*(.+)$", header)
        if len(matches) != 1:
            raise ValueError(f"{label}: 须有唯一的元信息 {field}")
        values[field] = scalar(matches[0])
    if body.startswith("---"):
        raise ValueError(f"{label}: 生命周期元信息须用普通 Markdown，不能使用 frontmatter")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", values["主题 ID"]):
        raise ValueError(f"{label}: 主题 ID 须为稳定 ASCII 标识")
    if values["阶段"] not in STAGES or values["任务等级"] not in {"Full", "Light"}:
        raise ValueError(f"{label}: 无效的阶段或任务等级")
    if not values["模块"] or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}|none", values["已验收版本"]):
        raise ValueError(f"{label}: 模块不能为空，已验收版本须为明确标识或 none")
    headings = list(re.finditer(r"(?m)^## (" + "|".join(map(re.escape, SECTIONS)) + r")[ \t]*$", body))
    names = [match[1] for match in headings]
    if len(names) != len(set(names)) or names != [name for name in SECTIONS if name in names]:
        raise ValueError(f"{label}: 六节生命周期标题不得重复或乱序")
    sections = {
        match[1]: body[match.end():headings[index + 1].start() if index + 1 < len(headings) else len(body)].strip()
        for index, match in enumerate(headings)
    }
    if values["任务等级"] == "Full" and names != list(SECTIONS):
        raise ValueError(f"{label}: Full 生命周期文档须包含六节中文标题")
    approval = evidence = ""
    if values["已验收版本"] != "none":
        if not sections.get(SECTIONS[4]) or not sections.get(SECTIONS[5]):
            raise ValueError(f"{label}: 已验收版本须保留已交付行为和必要证据两节")
        approval = evidence_value(sections[SECTIONS[5]], "批准依据", label)
        evidence = evidence_value(sections[SECTIONS[5]], "验收证据", label)
    return PlanDocument(values["主题 ID"], values["阶段"], values["模块"], values["任务等级"],
                        values["已验收版本"], sections, approval, evidence)


def local_target(root: Path, source: Path, raw: str) -> Path | None:
    """按项目根解析普通文件链接，拒绝歧义、外逃和链接祖先；不跟随系统外资料。"""
    split = urlsplit(raw)
    if ((split.scheme in {"https", "http"} and split.netloc)
            or (split.scheme == "mailto" and split.path)):
        return None
    if split.scheme or split.netloc or split.query or "\\" in raw or any(c.isspace() for c in raw):
        raise ValueError(f"不安全或不支持的文档链接：{source}: {raw!r}")
    if not split.path:
        return None
    decoded = unquote(split.path)
    if decoded.startswith("/") or "\\" in decoded or "\0" in decoded or any(c.isspace() for c in decoded):
        raise ValueError(f"文档链接须位于项目内：{raw!r}")
    parts = list(source.parent.relative_to(root).parts)
    for part in Path(decoded).parts:
        if part == "..":
            if not parts:
                raise ValueError(f"文档链接越出项目：{raw!r}")
            parts.pop()
        elif part not in {"", "."}:
            parts.append(part)
    target = root.joinpath(*parts)
    # 共用安全读取同时拒绝符号链接祖先与多硬链接文件；目录链接不充当基线。
    if target.suffix == ".md":
        read_file(target)
    else:
        current = root
        for part in parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"文档链接包含符号链接：{raw!r}")
    return target


def collect_plans(plans_root: Path) -> dict[Path, str]:
    """安全列出实际 Markdown；不存在的 plans 合法，历史原稿保持原字节。"""
    result: dict[Path, str] = {}
    try:
        info = plans_root.lstat()
    except FileNotFoundError:
        return result
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"plans root must be a real directory: {plans_root}")
    for path in sorted(plans_root.iterdir()):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"plans tree must not contain symlinks: {path}")
        if stat.S_ISDIR(info.st_mode):
            result.update(collect_plans(path))
        elif path.suffix == ".md":
            body = read_file(path)
            if body is None:
                raise ValueError(f"plan disappeared during read: {path}")
            result[path] = body.decode("utf-8")
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"plans entry must be a single-link regular file: {path}")
    return result


def validate_plan_index(root: Path, plans_root: Path, project_doc: Path, project_body: str) -> list[str]:
    """PROJECT 只链接明确基线；不要求将执行中、未验收或旧历史稿全部索引。"""
    errors: list[str] = []
    documents: dict[Path, PlanDocument | None] = {}
    topics: dict[str, Path] = {}
    try:
        for path, body in collect_plans(plans_root).items():
            document = parse_plan(body, str(path))
            documents[path] = document
            if document:
                key = document.topic_id.casefold()
                if key in topics:
                    raise ValueError(f"duplicate 主题 ID {document.topic_id}: {topics[key]} and {path}")
                topics[key] = path
                for raw in LINK.findall(document.approval_basis + "\n" + document.acceptance_evidence):
                    target = local_target(root, path, raw)
                    if target is not None and read_file(target) is None:
                        raise ValueError(f"基线批准／验收证据链接不存在：{path}: {raw}")
        for raw in LINK.findall(project_body):
            target = local_target(root, project_doc, raw)
            if target is not None and target.is_relative_to(root / "docs/features"):
                raise ValueError(f"PROJECT 不能引用旧 features 权威，请显式单次迁移：{target}")
            if target is None or target == plans_root or not target.is_relative_to(plans_root):
                continue
            if target.suffix != ".md" or target not in documents:
                raise ValueError(f"PROJECT links missing or non-Markdown baseline: {target}")
            document = documents[target]
            if document is None or not document.has_current_baseline:
                raise ValueError(f"PROJECT 只能链接明确的当前已验收基线：{target}")
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(str(exc))
    return errors
