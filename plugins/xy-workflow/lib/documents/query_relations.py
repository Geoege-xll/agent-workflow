"""从指定页面及有限候选的 Markdown 原文读取单跳引用，返回可定位的双向关系。"""

from __future__ import annotations

from itertools import tee
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit

from lib.documents.markdown_links import line_links, prose_lines
from lib.documents.plan_documents import (
    ATX_HEADING, inspect_local_target, parse_plan, project_path, visible_markdown_lines,
)
from lib.documents.safe_documents import snapshot


# 单页沿用安全读取器的 4 MiB 上限。目录很大时调用者可用 --source 分批核对；
# 读入或输出超过预算必须显式报告，空结果只能解释为本次选定范围内没有命中。
MAX_SOURCES = 64
MAX_RESULTS = 100
MAX_BYTES = 16 * 1024 * 1024
MAX_LINKS = 4096
_BAD_PERCENT = re.compile(r"%(?![0-9a-fA-F]{2})")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _page(root: Path, path: Path) -> Path:
    """检查用户选中的页面；只允许真实项目里的普通非隐藏文件，不接受目录别名。"""
    supplied = path if path.is_absolute() else root / path
    path = project_path(root, supplied)
    relative = path.relative_to(root)
    if (not relative.parts or any(part.startswith(".") for part in relative.parts)
            or any("\\" in part or _CONTROL.search(part) for part in relative.parts)):
        raise ValueError("关系页面须为项目内非隐藏文件")
    # 按真实路径检查中间节点；file.md/../page.md 在 POSIX 中不可遍历，不能仅因
    # 消去 .. 后落在存在的文档上就承认该坏引用。先核对项目根，防止越界探测。
    inspect_local_target(supplied)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("关系页面须为普通文件")
    return path


def _destination(root: Path, source: Path, raw: str) -> tuple[Path, str] | None:
    """外部 URL、页内锚点及不确定的目的地不产生关系；绝不读取链接目标正文。"""
    if len(raw) > 4096 or _BAD_PERCENT.search(raw) or _CONTROL.search(raw) or "\\" in raw:
        return None
    # urlsplit 会清理部分控制字符，故先查原字节字符，再严格解码恰好一次。二次编码
    # 仍含 %HH 的路径可能有多个解释，不能把其中某个解释误记作项目资料来源。
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc or parsed.query or not parsed.path:
        return None
    decoded = unquote(parsed.path, errors="strict")
    fragment = unquote(parsed.fragment, errors="strict")
    if (decoded.startswith("/") or "\\" in decoded or _CONTROL.search(decoded)
            or _CONTROL.search(fragment) or re.search(r"%[a-fA-F0-9]{2}", decoded)):
        return None
    return _page(root, source.parent / decoded), fragment


def _kind(path: Path, layout: dict[str, Path]) -> str:
    """类型仅标识适配器确定的文件归属；普通 Markdown 证据不会被推断为正式决定。"""
    if path == layout["project"]:
        return "project_index"
    if path == layout["standards"]:
        return "standards_index"
    if path.is_relative_to(layout["standards_root"] / "prototype") and path.suffix.lower() == ".html":
        return "prototype"
    if path.suffix.lower() == ".md":
        if path.is_relative_to(layout["plans"]):
            return "plan_file"
        if path.parent == layout["standards_root"]:
            return "standard_file"
        return "document"
    return "file"


def query_relations(
    root: Path, docs: dict[str, str], target: Path, sources: list[Path], limit: int = 32,
) -> dict:
    """由现有 CLI 传入已校验的根和适配器。返回命中、实际读取范围、截断与未解析计数。

    用户显式选页时只读这些候选及目标；默认只展开两个实际目录直接列出的受管候选，
    没有递归、文件树扫描或落盘索引。原型和其他证据文件只作为可反查的目的地。
    """
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"limit 必须为 1..{MAX_RESULTS} 之间的整数")
    if len(sources) > MAX_SOURCES:
        raise ValueError(f"最多可指定 {MAX_SOURCES} 个候选，请用 --source 分批查询")
    target = _page(root, target)
    layout = {name: root / docs[name] for name in ("project", "standards", "standards_root", "plans")}
    indexed = not sources
    indexes = (layout["project"], layout["standards"])
    pending: dict[Path, None] = {}
    if indexed:
        # 缺少项目规范或尚未投影 PROJECT 时仍可读指定目标。显式候选即使不存在也报错。
        for index in indexes:
            if index.exists() or index.is_symlink():
                pending[_page(root, index)] = None
    else:
        for candidate in sources:
            source = _page(root, candidate)
            if source.suffix.lower() != ".md":
                raise ValueError("--source 只接受作为链接来源的 Markdown 文件")
            pending[source] = None
    if target.suffix.lower() == ".md":
        pending[target] = None

    # 为反查保留内容入链优先级。例如一份列有几十条参考资料的规范，在较小的
    # limit 下仍应先回答「哪个主题引用它」。每组只保留 limit 个，不累计整张图。
    incoming = []
    navigation = []
    outgoing = []
    examined = []
    scope_limited = False
    skipped = used_bytes = examined_links = total_hits = 0
    # 目录读取中可以增加一层候选，绝不沿内容来源再扩展。单次查询中每页只打开一次。
    queue = list(pending)
    for source in queue:
        data, _ = snapshot(source)
        used_bytes += len(data)
        if used_bytes > MAX_BYTES:
            raise ValueError("关系查询达到总读取预算，请用 --source 缩小范围")
        text = data.decode("utf-8")
        rel_source = source.relative_to(root).as_posix()
        examined.append(rel_source)
        source_kind = _kind(source, layout)
        directory = source in indexes
        section = ""
        originals, for_prose = tee(visible_markdown_lines(text))
        for number, (original, line) in enumerate(zip(originals, prose_lines(for_prose)), 1):
            heading = ATX_HEADING.fullmatch(original) if ATX_HEADING.fullmatch(line) else None
            if heading:
                section = (heading[2] or "")[:160]
            for link in line_links(line, original):
                examined_links += 1
                if examined_links > MAX_LINKS:
                    raise ValueError("关系查询达到链接读取预算，请用 --source 缩小范围")
                try:
                    destination = _destination(root, source, link.raw)
                except (OSError, ValueError):
                    # 坏链接不能变成证据，也不能阻止查询同页其它有效引用。仅反馈计数，
                    # 不回显未经验证的外部地址或尝试打开这些路径；显式来源读取错误则上抛。
                    skipped += 1
                    continue
                if destination is None:
                    continue
                linked, fragment = destination
                target_kind = _kind(linked, layout)
                if indexed and directory and target_kind in {"standard_file", "plan_file"} and linked not in pending:
                    if len(queue) >= MAX_SOURCES:
                        scope_limited = True
                    else:
                        pending[linked] = None
                        queue.append(linked)
                if source != target and linked != target:
                    continue
                total_hits += 1
                if source == target:
                    bucket = outgoing
                elif directory:
                    bucket = navigation
                else:
                    bucket = incoming
                if len(bucket) >= limit:
                    continue
                if source_kind == "plan_file":
                    # 历史 Markdown 也可作为真实文本来源。只在需要报告命中时识别生命周期；
                    # 旧稿、坏头或示例都不能因其位于 plans 下就被呈现为已验收主题。
                    try:
                        document = parse_plan("\n".join(visible_markdown_lines(text)), rel_source)
                    except ValueError:
                        source_kind = "unvalidated_plan"
                    else:
                        source_kind = "topic" if document is not None else "historical_plan"
                bucket.append({
                    "direction": "outgoing" if source == target else "incoming",
                    "kind": "navigation" if directory else "reference",
                    "source": rel_source, "source_kind": source_kind, "section": section, "line": number,
                    "label": link.label[:160], "target": linked.relative_to(root).as_posix(),
                    "target_kind": target_kind, "fragment": fragment[:160],
                })
    return {
        "target": target.relative_to(root).as_posix(), "scope": "indexed" if indexed else "explicit",
        "sources_read": examined, "relations": (incoming + navigation + outgoing)[:limit],
        "results_truncated": total_hits > limit,
        "scope_truncated": scope_limited, "unresolved_links": skipped,
    }
