#!/usr/bin/env python3
"""解析主题生命周期与 PROJECT 基线索引；不从完成状态推断批准或当前事实。"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

from dataclasses import dataclass
from itertools import tee
from functools import lru_cache
from lib.documents.document_links import body_link_errors, decoded_link, document_prose, target_anchors
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Iterator
from urllib.parse import unquote, urlsplit

# 保留既有计划消费者导入的标题常量与正文屏蔽入口；扫描和锚点规则由文档层共用。
from lib.documents.markdown_headings import (
    ATX_HEADING, atx_section_bounds, iter_visible_lines, markdown_anchors, visible_markdown_lines,
    without_fenced_code,
)
from lib.documents.markdown_links import line_links, prose_lines
from lib.safe_text import open_file, read_file


SECTIONS = (
    "目标与范围", "需求与验收", "方案与原型关联", "当前进展与恢复入口",
    "验收结果与当前已交付行为", "批准依据与必要证据",
)
FIELDS = ("主题 ID", "阶段", "模块", "任务等级", "已验收版本")
STAGES = frozenset({"draft", "active", "paused", "completed", "cancelled", "removed"})
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
EMPTY = frozenset({"", "none", "todo", "pending", "待确认", "无", "未验收"})
TOPIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
TOPIC_FIELD = re.compile(r"^\- 主题 ID[:：][ \t]*(.*)$")
REQ_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])REQ-[0-9]{3,}(?![A-Za-z0-9_-])")
REQUIREMENT_ENTRY = re.compile(
    r"^ {0,3}(?:(?:[-+*]|[0-9]{1,9}[.)]|#{4,6})[ \t]+|\|[ \t]*)?"
    r"(?:\*\*|__|`)?(" + REQ_PATTERN.pattern + r")"
)
# 定位仅识别页首元信息。前缀无法判定时报错，而不是因保护限额误报可新建同主题。
MAX_TOPIC_HEADER_BYTES = 64 * 1024


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
    placeholder_text = value
    if "<" in value:
        # Markdown 的尖括号目的地允许含空格。只豁免已解析链接的起始分隔符，
        # 正文、标签、标题及路径里的 <模板占位> 仍须拒绝。
        for link in line_links(value):
            placeholder_text = placeholder_text.replace("](<" + link.raw + ">", "](" + link.raw + ">", 1)
    if value.casefold() in EMPTY or any(token in placeholder_text for token in ("**TODO**", "{{", "<")):
        raise ValueError(f"{label}: {key} 不能是待定或模板占位")
    return value


def current_requirement_ids(markdown: str, label: str) -> list[str] | None:
    """仅在显式声明的当前段提取定义，未使用标记的计划继续由旧规则消费。"""
    parent = ""
    found = False
    in_current = False
    requirements: dict[str, None] = {}
    for line in visible_markdown_lines(markdown):
        heading = ATX_HEADING.fullmatch(line)
        if heading:
            level, title = len(heading[1]), heading[2] or ""
            if level <= 2:
                parent = title if level == 2 else ""
            if level <= 3:
                in_current = False
            if level == 3 and title == "当前有效需求":
                if found or parent != SECTIONS[1]:
                    raise ValueError(f"{label}: ### 当前有效需求 须唯一且直接属于 ## 需求与验收")
                found = in_current = True
        if in_current:
            # 只认行首定义（含列表、表首列和下级标题）。标签或说明里提到的既有
            # 需求是引用，即使 ID 真存在也不能成为本轮评审允许选择的需求。
            entry = REQUIREMENT_ENTRY.match(line)
            if entry:
                requirements[entry[1]] = None
    if found and not requirements:
        raise ValueError(f"{label}: 当前有效需求 须至少定义一个 REQ ID")
    return list(requirements) if found else None


def parse_plan(body: str, label: str, *, required: bool = False,
               selected: bool = False) -> PlanDocument | None:
    """只认明确的中文元信息合同；未索引旧稿不因标题或 completed 成为当前基线。

    Full 的核心是可验收的需求，其余章节可以按读者需要增减、前置。旧六节使用相同
    标题和证据键，仍能恢复原有基线；无基线的 Light 草稿允许只有页首元信息。
    """
    # 严格形状只用于显式选择的受管计划；旧入口仍保留未索引历史稿的识别合同。
    if selected:
        # 从原稿识别当前范围，避免过早按旧规则屏蔽注释内的伪围栏。
        current_requirement_ids(body, label)
    # 无论入口如何，隐藏示例不得提供身份、已交付事实或验收证据。保留 H2 的实际
    # 边界，防止无关自定义章节的内容被前面的“批准依据与必要证据”吞入。
    body = "\n".join(visible_markdown_lines(body))
    headings = list(re.finditer(r"(?m)^ {0,3}##(?:[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*|[ \t]*)$", body))
    header = body[:headings[0].start()] if headings else body
    if not re.search(r"(?m)^- 主题 ID[:：]", header):
        if selected:
            raise ValueError(f"{label}: 显式计划缺少生命周期元信息 主题 ID")
        if required:
            raise ValueError(f"{label}: PROJECT 不能把无生命周期元信息的历史计划作为当前基线")
        return None
    values = {}
    for field in FIELDS:
        matches = re.findall(r"(?m)^- " + re.escape(field) + r"[:：][ \t]*(.*)$" if selected else
                             r"(?m)^- " + re.escape(field) + r"[:：][ \t]*(.+)$", header)
        if len(matches) != 1:
            raise ValueError(f"{label}: 须有唯一的元信息 {field}")
        values[field] = scalar(matches[0])
    if body.startswith("---"):
        raise ValueError(f"{label}: 生命周期元信息须用普通 Markdown，不能使用 frontmatter")
    if not TOPIC_ID.fullmatch(values["主题 ID"]):
        raise ValueError(f"{label}: 主题 ID 须为稳定 ASCII 标识")
    if values["阶段"] not in STAGES or values["任务等级"] not in {"Full", "Light"}:
        raise ValueError(f"{label}: 无效的阶段或任务等级")
    if not values["模块"] or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}|none", values["已验收版本"]):
        raise ValueError(f"{label}: 模块不能为空，已验收版本须为明确标识或 none")
    names = [match[1] for match in headings if match[1] in SECTIONS]
    if len(names) != len(set(names)):
        raise ValueError(f"{label}: 生命周期 H2 标题不得重复")
    sections = {
        match[1]: body[match.end():headings[index + 1].start() if index + 1 < len(headings) else len(body)].strip()
        for index, match in enumerate(headings) if match[1] in SECTIONS
    }
    if values["任务等级"] == "Full" and not sections.get(SECTIONS[1]):
        raise ValueError(f"{label}: Full 主题须有非空的 ## 需求与验收")
    approval = evidence = ""
    if values["已验收版本"] != "none":
        if not sections.get(SECTIONS[4]) or not sections.get(SECTIONS[5]):
            raise ValueError(f"{label}: 已验收版本须保留已交付行为和必要证据两节")
        approval = evidence_value(sections[SECTIONS[5]], "批准依据", label)
        evidence = evidence_value(sections[SECTIONS[5]], "验收证据", label)
    return PlanDocument(values["主题 ID"], values["阶段"], values["模块"], values["任务等级"],
                        values["已验收版本"], sections, approval, evidence)


def inspect_local_target(target: Path) -> None:
    """只检查链接节点与存在性，不打开目标正文；目录可链接，特殊节点与软硬链不可。"""
    for parent in target.parents:
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f"文档路径包含不安全父目录：{parent}")
    info = target.lstat()
    if not (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
        raise ValueError(f"文档目标须为真实目录或单链接普通文件：{target}")


def _local_link_path(source: Path, raw: str, *, allow_spaces: bool) -> Path | None:
    """先辨认 URL 与项目内的相对写法，保留父跳转供后续安全核对。"""
    split = urlsplit(raw)
    if ((split.scheme in {"https", "http"} and split.netloc)
            or (split.scheme == "mailto" and split.path)):
        return None
    # 只有共享 Markdown 解析器已分清目的地与标题时才接受文件名中的普通空格；
    # 历史正文链接、原型等直接传入字符串的调用方维持原有空白规则。
    def unsafe_character(char: str) -> bool:
        return ord(char) < 32 or ord(char) == 127 or (char.isspace() and not (allow_spaces and char == " "))

    if split.scheme or split.netloc or split.query or "\\" in raw or any(map(unsafe_character, raw)):
        raise ValueError(f"不安全或不支持的文档链接：{source}: {raw!r}")
    if not split.path:
        return None
    decoded = unquote(split.path, errors="strict")
    if decoded.startswith("/") or "\\" in decoded or any(map(unsafe_character, decoded)):
        raise ValueError(f"文档链接须位于项目内：{raw!r}")
    return source.parent / decoded


def local_target(root: Path, source: Path, raw: str, *, inspect_only: bool = False,
                 allow_spaces: bool = False) -> Path | None:
    """按项目根解析实际目标，拒绝歧义、外逃和链接祖先；不跟随系统外资料。"""
    candidate = _local_link_path(source, raw, allow_spaces=allow_spaces)
    if candidate is None:
        return None
    target = project_path(root, candidate)
    # 显式计划只对目标做安全元数据检查，不能因链接而扩展正文读取范围；旧入口不变。
    if inspect_only:
        inspect_local_target(target)
    elif target.suffix == ".md":
        read_file(target)
    else:
        current = root
        for part in target.relative_to(root).parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"文档链接包含符号链接：{raw!r}")
    return target


def project_directory(root: Path) -> Path:
    """校验真实项目根后再消去路径别名，保持软链祖先拒绝。"""
    root = root.absolute()
    inspect_local_target(root)
    if not root.is_dir():
        raise ValueError(f"项目根须为真实目录：{root}")
    return root.resolve()


def project_path(root: Path, path: Path) -> Path:
    """逐段消去父跳转，在折叠之前检查即将跨过的真实节点。"""
    path = path if path.is_absolute() else root / path
    if not path.is_relative_to(root):
        raise ValueError(f"路径须位于项目根内：{path}")
    parts: list[str] = []
    for part in path.relative_to(root).parts:
        if part == "..":
            if not parts:
                raise ValueError(f"路径越出项目根：{path}")
            # 父跳转须能在真实目录上执行。若先把 file.md/.. 折叠掉，本来
            # 无法遍历的文档链接会在同级恰有目标时被错误接受。
            crossed = root.joinpath(*parts)
            inspect_local_target(crossed)
            if not crossed.is_dir():
                raise ValueError(f"父跳转前的路径须为目录：{crossed}")
            parts.pop()
        elif part != ".":
            parts.append(part)
    return root.joinpath(*parts)


def validate_selected_plans(root: Path, plans: list[Path], *, docs: dict[str, str] | None = None) -> list[str]:
    """校验指定主题；显式提供 adapter 布局才核对 PROJECT 到这些主题的引用。"""
    errors: list[str] = []
    try:
        root = project_directory(root)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    seen: set[Path] = set()
    topics: dict[str, Path] = {}
    documents: dict[Path, tuple[PlanDocument | None, str]] = {}
    read_anchors = lru_cache(maxsize=32)(target_anchors)
    for selected_path in plans:
        path = selected_path
        try:
            path = project_path(root, selected_path)
            if path in seen:
                continue
            seen.add(path)
            if path.suffix != ".md":
                raise ValueError("计划须为 Markdown .md 文件")
            if docs is not None and not path.is_relative_to(root / docs["plans"]):
                raise ValueError("所选主题须位于实际 docs.plans")
            data = read_file(path)
            if data is None:
                raise ValueError("计划文件不存在")
            body = data.decode("utf-8")
            document = parse_plan(body, str(path), required=True, selected=True)
            key = document.topic_id.casefold()
            if key in topics and not path.samefile(topics[key]):
                raise ValueError(f"duplicate 主题 ID {document.topic_id}：{topics[key]} 和 {path}")
            topics[key] = path
            # 链接和图片只消费实际正文。列表/引用中的资源仍参与核对，围栏、行内
            # 代码和缩进代码中的字面示例不构成文件访问。普通路径只核对节点元信息。
            for line in document_prose(body):
                for link in line_links(line, include_images=True):
                    local_target(root, path, decoded_link(link.raw), inspect_only=True, allow_spaces=True)
            # 只有显式 HTML 状态片段读取目的页；链接定义与代码屏蔽沿用 --document 的逻辑。
            errors.extend(body_link_errors(root, path, body, read_anchors, html_only=True))
            if docs is not None:
                documents[path] = (document, body)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    if docs is not None and not errors:
        try:
            project = root / docs["project"]
            data = read_file(project)
            if data is None:
                raise ValueError(f"PROJECT 不存在：{project}")
            _validate_project_links(root, root / docs["plans"], project, data.decode("utf-8"),
                                    documents, selected_only=True)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(str(exc))
    return errors


def _topic_header(path: Path, *, required: bool) -> str | None:
    """安全流读取计划页首，遇到首个真实 H2 即停；历史正文与链接目标不参与定位。"""
    with open_file(path) as stream:
        if stream is None:
            if required:
                raise ValueError(f"选定候选计划不存在：{path}")
            # 索引里仍追踪、已从工作树移除的路径不代表当前可编辑的计划来源。
            return None

        def read_header_lines() -> Iterator[str]:
            remaining = MAX_TOPIC_HEADER_BYTES
            while raw := stream.readline(remaining + 1):
                remaining -= len(raw)
                if remaining < 0:
                    raise ValueError(f"无法在安全读取限额内定位主题页首：{path}")
                yield raw.decode("utf-8", errors="strict").rstrip("\r\n")

        values = []
        for line in iter_visible_lines(read_header_lines(), hide_comments=True):
            heading = ATX_HEADING.fullmatch(line)
            if heading and heading[1] == "##":
                break
            field = TOPIC_FIELD.fullmatch(line)
            if field:
                values.append(scalar(field[1]))
    if not values:
        return None
    if len(values) != 1 or not TOPIC_ID.fullmatch(values[0]):
        raise ValueError(f"计划须有唯一的稳定 ASCII 主题 ID：{path}")
    return values[0]


def locate_plan(root: Path, plans: Path, topic: str, candidates: list[Path]) -> Path | None:
    """核对实际 plans 中已跟踪与显式候选的主题头，返回唯一可编辑来源。"""
    if not TOPIC_ID.fullmatch(topic):
        raise ValueError("主题 ID 须为稳定 ASCII 标识")
    explicit = set(project_path(root, path) for path in candidates)
    paths = set(explicit)
    if os.path.lexists(root / ".git"):
        relative_plans = plans.relative_to(root)
        # 仅采用选中项目的 Git 索引路径，不接受宿主环境重定向，也不枚举私有草稿。
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        try:
            result = subprocess.run(["git", "--literal-pathspecs", "-C", str(root), "ls-files", "-z",
                                     "--", relative_plans.as_posix() + "/"],
                                    env=environment, capture_output=True, check=False, timeout=20)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("读取此项目的 Git 计划索引超时，主题定位未完成") from exc
        if result.returncode:
            raise ValueError("无法读取此项目的 Git 计划索引：" + os.fsdecode(result.stderr).strip())
        for name in result.stdout.split(b"\0"):
            relative = Path(os.fsdecode(name))
            if (relative.suffix == ".md" and relative.is_relative_to(relative_plans)
                    and not any(part.startswith(".") for part in relative.parts)):
                paths.add(root / relative)
    elif not explicit:
        raise ValueError("此项目根没有 Git 工作树；请用 --plan 明确指定既有候选计划")

    match = None
    for path in sorted(paths):
        if (path.suffix != ".md" or not path.is_relative_to(plans)
                or any(part.startswith(".") for part in path.relative_to(root).parts)):
            raise ValueError(f"候选计划须为实际 docs.plans 下的非隐藏 Markdown：{path}")
        value = _topic_header(path, required=path in explicit)
        if value is not None and value.casefold() == topic.casefold():
            if match is not None and not path.samefile(match):
                raise ValueError(f"duplicate 主题 ID {topic}：{match} 和 {path}")
            match = path
    return match


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


def _project_links(body: str) -> Iterator[tuple[str, str, bool]]:
    """区分目录导航、显式验收条目和原有正文；标题或说明里的举例不能授予验收。"""
    section = ""
    original, for_catalog = tee(visible_markdown_lines(body))
    for legacy_line, line in zip(original, prose_lines(for_catalog)):
        heading = ATX_HEADING.fullmatch(line)
        if heading and len(heading[1]) <= 2:
            section = heading[2] if heading[1] == "##" else ""
        context = section if not heading or len(heading[1]) > 2 else ""
        if context != "主题目录":
            # 旧索引曾把围栏和注释以外的正文链接（包括引用块内的链接）作为基线声明。
            # 只有新目录明确放宽导航资格；不可因别处写成块引用就绕开已有验收保护。
            for link in LINK.finditer(legacy_line):
                yield link[1], context, False
            continue
        # 只认行首声明，避免将“尚未验收”“待检查已验收行为”等主题文字误作证明。
        claim = bool(re.match(r"^ {0,3}(?:(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)?已验收[ \t]*[:：]", line))
        for link in line_links(line):
            yield link.raw, context, claim


def _validate_project_links(root: Path, plans_root: Path, project: Path, body: str,
                            documents: dict[Path, tuple[PlanDocument | None, str]], *,
                            selected_only: bool = False) -> None:
    """在选中范围或完整索引上执行相同的目录、基线与锚点语义。"""
    indexed: set[tuple[str, str]] = set()
    for raw, section, claim in _project_links(body):
        catalog = section == "主题目录"
        if selected_only:
            # 仅用词法路径选择本次核对的引用，不访问无关目标（可含未选历史坏稿）。
            # 命中后重新走真实节点安全检查，词法折叠不得让软链或越界父路径过关。
            path = urlsplit(raw)
            if path.scheme or path.netloc or not path.path:
                continue
            candidate = Path(os.path.normpath(project.parent / unquote(path.path)))
            if candidate not in documents:
                continue
        target = local_target(root, project, raw, inspect_only=selected_only, allow_spaces=catalog)
        if target is not None and target.is_relative_to(root / "docs/features"):
            raise ValueError(f"PROJECT 不能引用旧 features 权威，请显式单次迁移：{target}")
        if target is None or target == plans_root or not target.is_relative_to(plans_root):
            if catalog:
                raise ValueError(f"PROJECT 主题目录只收录实际 docs.plans 内的主题：{raw}")
            continue
        if target.suffix != ".md" or target not in documents:
            raise ValueError(f"PROJECT links missing or non-Markdown plan: {target}")
        document, content = documents[target]
        if catalog and not claim:
            if document is None or not (document.has_current_baseline or document.stage in {"draft", "active", "paused"}):
                raise ValueError(f"PROJECT 主题目录只收录有稳定 ID 的进行中或已验收主题：{target}")
        elif document is None or not document.has_current_baseline:
            raise ValueError(f"PROJECT 只能链接明确的当前已验收基线：{target}")
        if catalog or section == "当前已验收基线":
            # 同一目录按稳定主题去重；正文说明或独立的验收索引可有意交叉引用。
            key = section, document.topic_id.casefold()
            if key in indexed:
                raise ValueError(f"PROJECT {section}重复索引同一计划：{target}")
            indexed.add(key)
        if catalog:
            fragment = unquote(urlsplit(raw).fragment)
            if fragment and fragment not in markdown_anchors(content):
                raise ValueError(f"PROJECT 主题目录锚点不存在：{raw}")


def validate_plan_index(root: Path, plans_root: Path, project_doc: Path, project_body: str) -> list[str]:
    """完整维护检查保留全树重复主题与证据验证，目录按导航和验收语义分别核对。"""
    errors: list[str] = []
    documents: dict[Path, tuple[PlanDocument | None, str]] = {}
    topics: dict[str, Path] = {}
    try:
        for path, body in collect_plans(plans_root).items():
            document = parse_plan(body, str(path))
            documents[path] = document, body
            if document:
                key = document.topic_id.casefold()
                if key in topics:
                    raise ValueError(f"duplicate 主题 ID {document.topic_id}: {topics[key]} and {path}")
                topics[key] = path
                for proof in (document.approval_basis, document.acceptance_evidence):
                    for link in line_links(proof):
                        target = local_target(root, path, link.raw, allow_spaces=True)
                        if target is not None and read_file(target) is None:
                            raise ValueError(f"基线批准／验收证据链接不存在：{path}: {link.raw}")
        _validate_project_links(root, plans_root, project_doc, project_body, documents)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(str(exc))
    return errors
