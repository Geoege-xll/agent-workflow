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
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Iterable, Iterator
from urllib.parse import unquote, urlsplit

from lib.safe_text import open_file, read_file


SECTIONS = (
    "目标与范围", "需求与验收", "方案与原型关联", "当前进展与恢复入口",
    "验收结果与当前已交付行为", "批准依据与必要证据",
)
FIELDS = ("主题 ID", "阶段", "模块", "任务等级", "已验收版本")
STAGES = frozenset({"draft", "active", "paused", "completed", "cancelled", "removed"})
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
# 选中计划中的图片同样携带本地路径，必须检查节点；旧索引链接识别保持原合同。
SELECTED_LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
EMPTY = frozenset({"", "none", "todo", "pending", "待确认", "无", "未验收"})
TOPIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
TOPIC_FIELD = re.compile(r"^\- 主题 ID[:：][ \t]*(.*)$")
ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*)?$")
REQ_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])REQ-[0-9]{3,}(?![A-Za-z0-9_-])")
REQUIREMENT_ENTRY = re.compile(
    r"^ {0,3}(?:(?:[-+*]|[0-9]{1,9}[.)]|#{4,6})[ \t]+|\|[ \t]*)?"
    r"(?:\*\*|__|`)?(" + REQ_PATTERN.pattern + r")"
)
COMMENT_OR_INLINE_CODE = re.compile(r"<!--|-->|`+|\\[\\<`]")
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
    if value.casefold() in EMPTY or any(token in value for token in ("**TODO**", "{{", "<")):
        raise ValueError(f"{label}: {key} 不能是待定或模板占位")
    return value


def _mask_comment_line(line: str, in_comment: bool) -> tuple[str, bool]:
    """在一行内屏蔽 HTML 注释，向下一行携带尚未闭合的注释状态。"""
    if not in_comment and "<!--" not in line:
        return line, False
    tokens = list(COMMENT_OR_INLINE_CODE.finditer(line))
    inline_ends: dict[int, int] = {}
    next_tick: dict[int, int] = {}
    # 行内代码可展示 `<!--` 示例。一次逆序查找同宽结束符，避免对每个反引号
    # 从头重扫长行；未配对的反引号只是文字，不能隐藏其后的真实注释。
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index][0]
        if token.startswith("`"):
            width = len(token)
            if width in next_tick:
                inline_ends[index] = next_tick[width]
            next_tick[width] = index

    output: list[str] = []
    visible_from = 0
    comment_from = 0 if in_comment else None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if comment_from is not None:
            if token[0] == "-->":
                output.append(line[visible_from:comment_from])
                output.append(" " * (token.end() - comment_from))
                visible_from = token.end()
                comment_from = None
        elif token[0] == "<!--":
            comment_from = token.start()
        elif index in inline_ends:
            index = inline_ends[index]
        index += 1
    if comment_from is not None:
        output.append(line[visible_from:comment_from])
        output.append(re.sub(r"[^\r\n]", " ", line[comment_from:]))
    else:
        output.append(line[visible_from:])
    return "".join(output), comment_from is not None


def _visible_lines(lines: Iterable[str], *, hide_comments: bool = False) -> Iterator[str]:
    """保留原行和偏移，支持在首个真实章节停读；旧目录仍使用原围栏语义。"""
    fence = ""
    width = 0
    in_comment = False
    for line in lines:
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            closing = marker and marker[1][0] == fence and len(marker[1]) >= width and not marker[2].strip()
            yield re.sub(r"[^\r\n]", " ", line)
            if closing:
                fence = ""
        elif not in_comment and marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence, width = marker[1][0], len(marker[1])
            yield re.sub(r"[^\r\n]", " ", line)
        elif hide_comments:
            # 围栏内的注释标记只是示例，注释里的围栏也不能吞掉之后的真实章节。
            visible, in_comment = _mask_comment_line(line, in_comment)
            yield visible
        else:
            yield line


def without_fenced_code(body: str) -> str:
    """保留旧的仅围栏屏蔽语义，供已有评审的原字节合同使用。"""
    return "".join(_visible_lines(body.splitlines(keepends=True)))


def current_requirement_ids(markdown: str, label: str) -> list[str] | None:
    """仅在显式声明的当前段提取定义，未使用标记的计划继续由旧规则消费。"""
    parent = ""
    found = False
    in_current = False
    requirements: dict[str, None] = {}
    for line in _visible_lines(markdown.splitlines(), hide_comments=True):
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

    Full 采用六节完整形状。Light 的无基线恢复稿可以少节；一旦 PROJECT 引用其
    已验收行为，仍须具备基线和证据两节。字段仅描述可恢复的既有事实，不授予批准。
    """
    # 严格形状只用于显式选择的受管计划；旧入口仍保留未索引历史稿的识别合同。
    if selected:
        # 从原稿识别当前范围，避免过早按旧规则屏蔽注释内的伪围栏。
        current_requirement_ids(body, label)
        body = without_fenced_code(body)
    header = re.split(r"(?m)^ {0,3}##(?:[ \t]|$)" if selected else r"(?m)^## ", body, maxsplit=1)[0]
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
    headings = list(re.finditer(r"(?m)^ {0,3}##(?:[ \t]+(.*?)[ \t]*|[ \t]*)$" if selected else
                               r"(?m)^## (" + "|".join(map(re.escape, SECTIONS)) + r")[ \t]*$", body))
    names = [match[1] for match in headings]
    if selected and any(name not in SECTIONS for name in names):
        raise ValueError(f"{label}: 额外 H2 标题须改用 H3；只允许六节生命周期标题")
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


def inspect_local_target(target: Path) -> None:
    """只检查链接节点与存在性，不打开目标正文；目录可链接，特殊节点与软硬链不可。"""
    for parent in target.parents:
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f"文档路径包含不安全父目录：{parent}")
    info = target.lstat()
    if not (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
        raise ValueError(f"文档目标须为真实目录或单链接普通文件：{target}")


def local_target(root: Path, source: Path, raw: str, *, inspect_only: bool = False) -> Path | None:
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
            if inspect_only:
                inspect_local_target(root.joinpath(*parts))
            parts.pop()
        elif part not in {"", "."}:
            parts.append(part)
    target = root.joinpath(*parts)
    # 显式计划只对目标做安全元数据检查，不能因链接而扩展正文读取范围；旧入口不变。
    if inspect_only:
        inspect_local_target(target)
    elif target.suffix == ".md":
        read_file(target)
    else:
        current = root
        for part in parts:
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
            inspect_local_target(root.joinpath(*parts))
            parts.pop()
        elif part != ".":
            parts.append(part)
    return root.joinpath(*parts)


def validate_selected_plans(root: Path, plans: list[Path]) -> list[str]:
    """独立校验指定计划，不需要配置/PROJECT，不枚举目录，不修改任何受验文件。"""
    errors: list[str] = []
    try:
        root = project_directory(root)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    seen: set[Path] = set()
    topics: dict[str, Path] = {}
    for selected_path in plans:
        path = selected_path
        try:
            path = project_path(root, selected_path)
            if path in seen:
                continue
            seen.add(path)
            if path.suffix != ".md":
                raise ValueError("计划须为 Markdown .md 文件")
            data = read_file(path)
            if data is None:
                raise ValueError("计划文件不存在")
            body = data.decode("utf-8")
            document = parse_plan(body, str(path), required=True, selected=True)
            key = document.topic_id.casefold()
            if key in topics and not path.samefile(topics[key]):
                raise ValueError(f"duplicate 主题 ID {document.topic_id}：{topics[key]} 和 {path}")
            topics[key] = path
            for raw in SELECTED_LINK.findall(without_fenced_code(body)):
                local_target(root, path, raw, inspect_only=True)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
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
        for line in _visible_lines(read_header_lines(), hide_comments=True):
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


def _project_links(body: str) -> Iterator[tuple[str, bool]]:
    """标记专用 H2 内的实际链接，其他可见说明仍由原有链接合同处理。"""
    active = False
    for line in _visible_lines(body.splitlines(), hide_comments=True):
        heading = ATX_HEADING.fullmatch(line)
        index_item = active
        if heading and len(heading[1]) <= 2:
            active = heading[1] == "##" and heading[2] == "当前已验收基线"
            index_item = False
        for link in LINK.finditer(line):
            yield link[1], index_item


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
        indexed: set[Path] = set()
        for raw, index_item in _project_links(project_body):
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
            if index_item:
                # 锚点、相对别名和编码不改变同一基线来源，去重基于已验证目标。
                if target in indexed:
                    raise ValueError(f"PROJECT 当前已验收基线重复索引同一计划：{target}")
                indexed.add(target)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(str(exc))
    return errors
