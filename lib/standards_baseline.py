#!/usr/bin/env python3
"""规范迁移计划与限定于规范创建/删除快照的精确恢复原语。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import tempfile
from typing import Mapping
from urllib.parse import quote

try:
    from .project_discovery import ProjectProfile
    from .claude_instructions import read_file
    from .validate_project_config import parse_project_name
    from .platform_fs import os as fs, publish_exclusive
except ImportError:
    from project_discovery import ProjectProfile
    from claude_instructions import read_file
    from validate_project_config import parse_project_name
    from platform_fs import os as fs, publish_exclusive

COMMON_BEGIN = b"<!-- agent-workflow:general-common:begin -->"
COMMON_END = b"<!-- agent-workflow:general-common:end -->"
# 受管标记只能定位候选区，不能证明其内容仍属于工作流。只有四个已提交历史版本
# 的完整区块指纹可授权整区删除；正文、无 ID 注释、续段和表格改动都会使证明失效。
LEGACY_COMMON_BLOCK_HASHES = frozenset({
    "bbb132631f610df0278e82e70185c0d37c7692f4200a038626a3a77ad30b6b40",
    "6b95913ab30f370206303305c0c265d8cd29499c8c2f02f4a0cf3d93572b2e95",
    "060243dd76ceffde4bcdb2d759feba14bc14fb1a1fd33d26ee3e18b2d1a0c71e",
    "8fbef748d8b9218a988e644d49343721c5f657ce8213207ea84b20acfaaefb22",
})
# 已提交历史模板的指纹仅用于归属证明，不保留第二份规则正文；实际规则从 Skill 读取。
LEGACY_TEMPLATE_HASHES = {
    "GENERAL.md": frozenset({
        "9b6677a35d453eddbd7f0a7c26d810b47645ada418b3dceee0dfd4dffcb9df86",
        "bdc3f09082e94f5a0f8fb930dae8e628edb651645f5e97052d95293188ce02c6",
        "ae73f00772dfe6f7e1922145a8f0c99f6d308ecc2aa27ea44012ad5751ec36f9",
        "62b1527a50d7f2fd9883cd7022f3878d3c402c719eac9e371ed41fc584660b43",
    }),
    "UPSTREAM.md": frozenset({"5a52ff35788f790174eb79fb5775dea56870050da8142ebce02250fd8234067e"}),
    "DESIGN_FOUNDATIONS.md": frozenset({"9bdf9baaf72b396fd86107b95a5b0b85de4336aa5278768ccb65ea99ece59c87"}),
    "DESIGN_COMPONENTS.md": frozenset({"76759ac10ae0342e0de6bd162a422fa5c06b83aa7fbc85268794c64754dfdbf9"}),
    "STANDARDS.md": frozenset({
        "f56cf0044d17a7c60ec0c2815879ffda537492d590e387077824a6bf9ba53097",
        "f936d4cd96c46f737565b32ab9f612faa9a310ae3ad5c5ed46bc7a94ed2aef00",
    }),
}
# 只支持已有规范的顶层规则条目，不扩成通用 Markdown 解析器。空行后的缩进续段、
# 无缩进附表仍属于当前规则，直到同级条目或标题；项目扩展不能因首段相同而丢失 ID。
RULE_ITEM_RE = re.compile(
    rb"(?ms)^- `\[([a-z0-9][a-z0-9._-]*)\] \[(hard|advisory)\]`.*?(?=^- |^#{1,6} |\Z)"
)



def common_span(body: bytes) -> tuple[int, int] | None:
    """只认完整、唯一、独占行的受管标记；不凭标题猜测所有权。"""
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
    """兼容既有标记读取；迁移仅处理这对明确边界。"""
    span = common_span(body)
    return None if span is None else body[span[0]:span[1]]


def remove_created_standard(path: Path, expected: bytes, mode: int, identity: tuple[int, int]) -> None:
    """只撤回新建规范索引的已采样身份，不能 unlink 采样之后出现的用户替换。

    POSIX 先把当前名字移入本函数独占的临时名，再核对身份、权限和完整内容；若移动
    的已是用户替换，只能排他放回，不能覆盖间隙的新文件。Windows 复用已有按打开
    身份校验并删除的原语。临时名仅保护这一文件，失败保留的路径随错误交回调用方。
    """
    if fs.name == "nt":
        try:
            from .windows_fs import remove_file_if_unchanged
        except ImportError:
            from windows_fs import remove_file_if_unchanged
        info = fs.lstat(path)
        if stat.S_IMODE(info.st_mode) != mode or not remove_file_if_unchanged(
            path, hashlib.sha256(expected).hexdigest(), identity,
        ):
            raise ValueError(f"created standard changed during rollback; preserved: {path}")
        return

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.rollback-", dir=path.parent)
    temporary = Path(temporary_name)
    placeholder = fs.fstat(descriptor)
    placeholder_identity = (placeholder.st_dev, placeholder.st_ino)
    # 持有最初空临时文件的描述符直到 finally，防止其 inode 被复用后误认用户文件。
    try:
        fs.replace(path, temporary)
        moved = fs.lstat(temporary)
        if (not stat.S_ISREG(moved.st_mode) or moved.st_nlink != 1
                or (moved.st_dev, moved.st_ino) != identity
                or stat.S_IMODE(moved.st_mode) != mode or read_file(temporary) != expected):
            raise ValueError(f"created standard changed during rollback; preserved: {path}")
        fs.unlink(temporary)
        try:
            fs.lstat(path)
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"new user file appeared during rollback; preserved: {path}")
    finally:
        try:
            try:
                remaining = fs.lstat(temporary)
            except FileNotFoundError:
                remaining = None
            if remaining is not None:
                if (remaining.st_dev, remaining.st_ino) == placeholder_identity:
                    # rename 尚未发生时这里只能清理仍为本函数的空占位，不能误删新资料。
                    if read_file(temporary) != b"":
                        raise ValueError(f"rollback temporary changed; preserved: {temporary}")
                    fs.unlink(temporary)
                else:
                    try:
                        publish_exclusive(temporary, path)
                    except OSError as exc:
                        raise ValueError(
                            f"rollback conflict; preserved current file and displaced content: {path}; {temporary}"
                        ) from exc
        finally:
            fs.close(descriptor)


def _observed_baseline(profile: ProjectProfile) -> str:
    """仅为识别旧安装器精确生成的观察；不再向项目写入观察或规范占位。"""
    if not profile.modules:
        return "- No implementation module was discovered; add explicit rules only after verification."
    lines = []
    for module in profile.modules:
        stacks = ", ".join(module.stack_facts) if module.stack_facts else "unknown"
        lines.append(f"- `{module.root}` → role `{module.primary_role}`; stacks: {stacks}; "
                     f"evidence: {', '.join(module.evidence_paths) or 'none'}")
        if module.verification_commands:
            encoded = ", ".join(json.dumps(list(command.argv), ensure_ascii=False)
                                for command in module.verification_commands)
            lines.append(f"  - Discovered verification commands: {encoded}")
    return "\n".join(lines)


def _legacy_template(name: str, body: bytes, values: Mapping[str, str], profile: ProjectProfile) -> bool:
    """只归一化已知模板变量再比整文指纹；项目注释、规则差异和旧观察均会保留。"""
    text = body.decode("utf-8", errors="strict").replace("\r\n", "\n")
    title, separator, rest = text.partition("\n")
    suffix = " — " + values["PROJECT_NAME"]
    if title.endswith(suffix):
        title = title[:-len(suffix)] + " — {{PROJECT_NAME}}"
    text = title + separator + rest
    if name == "GENERAL.md":
        observed = re.search(
            r"(?s)(?<=## Observed repository baseline\n\n)(.*?)(?=\n\nThese observations guide routing and verification;)", text)
        if observed:
            allowed = {"{{OBSERVED_BASELINE}}", _observed_baseline(profile),
                       "- Not initialized. Setup replaces this exact template-only line with read-only repository observations."}
            if observed.group() not in allowed:
                return False
            text = text[:observed.start()] + "{{OBSERVED_BASELINE}}" + text[observed.end():]
    if name == "STANDARDS.md":
        base, parent = values["DOC_STANDARDS_ROOT"], posixpath.dirname(values["DOC_STANDARDS"])
        engineering = "\n".join(f"- [{label}]({posixpath.relpath(base + '/' + leaf, parent)})"
                                for label, leaf in (("General engineering rules", "GENERAL.md"),
                                                    ("Upstream and second-development boundaries", "UPSTREAM.md")))
        design = "\n".join(f"- [{label}]({posixpath.relpath(base + '/' + leaf, parent)})"
                           for label, leaf in (("Design foundations", "DESIGN_FOUNDATIONS.md"),
                                               ("Component and interaction standards", "DESIGN_COMPONENTS.md")))
        text = text.replace(engineering, "{{ENGINEERING_STANDARDS_INDEX}}")
        for content in (design, "- No design standards are configured for the discovered project profile."):
            text = text.replace(content, "{{DESIGN_STANDARDS_INDEX}}")
    for key in ("DOC_FEATURES_DIR", "DOC_PROJECT", "DOC_DESIGN_DIR"):
        # 只还原明确反引号引用，不抹掉用户普通正文中的路径子串。
        for slash in ("/", ""):
            text = text.replace(f"`{values[key]}{slash}`", f"`{{{{{key}}}}}{slash}`")
    text = text.replace(f"`{values['DOC_DESIGN_DIR']}/prototype/`", "`{{DOC_DESIGN_DIR}}/prototype/`")
    return hashlib.sha256(text.encode("utf-8")).hexdigest() in LEGACY_TEMPLATE_HASHES.get(name, ())


def _without_builtin_items(body: bytes, paragraphs: Mapping[bytes, bytes]) -> bytes:
    """完整规则条目相同才剥离；项目续段或附表变化保留并交冲突校验拒绝。"""
    removals = [(match.start(), match.start() + len(match.group().rstrip(b"\r\n")))
                for match in RULE_ITEM_RE.finditer(body)
                if paragraphs.get(match[1]) == match.group().replace(b"\r\n", b"\n").rstrip(b"\n")]
    for start, end in reversed(removals):
        body = body[:start] + body[end:]
    return body


def validate_planned_rule_ids(root: Path, updates: Mapping[Path, bytes | None], *, pack_root: Path) -> None:
    """用候选视图核对内置与项目 ID 唯一性；删除条目不能继续占据规则所有权。"""
    try:
        from .validate_project_docs import STANDARD_RULE_RE, collect_standard_leaves, read_builtin_standard_sources
    except ImportError:
        from validate_project_docs import STANDARD_RULE_RE, collect_standard_leaves, read_builtin_standard_sources
    errors = []
    leaves = collect_standard_leaves(root, errors) if root.exists() else {}
    for path, body in updates.items():
        if path.parent == root and path.suffix == ".md":
            if body is None:
                leaves.pop(path.resolve(), None)
            else:
                leaves[path.resolve()] = body.decode("utf-8", errors="strict")
    owners = {}
    for path, body in [*read_builtin_standard_sources(pack_root).items(), *leaves.items()]:
        for rule_id, _severity in STANDARD_RULE_RE.findall(body):
            if rule_id in owners:
                errors.append(f"duplicate standards rule ID {rule_id}: {owners[rule_id]} and {path}")
            else:
                owners[rule_id] = path
    if errors:
        raise ValueError("; ".join(errors))


def _remove_deleted_links(line: str, index: Path, deleted: set[Path], resolve) -> str:
    """纯默认链接行可去掉；混合项目说明只移除对应链接，保留其余原文。"""
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    matches = [match for match in pattern.finditer(line) if resolve(index, match[1]) in deleted]
    if len(matches) == 1 and re.fullmatch(r"[ \t]*[-*]?[ \t]*" + re.escape(matches[0].group()) + r"[ \t\r\n]*", line):
        return ""
    for match in reversed(matches):
        line = line[:match.start()] + line[match.end():]
    return line


def plan_standard_updates(pack: Path, project: Path, *, docs: Mapping[str, str],
                          profile: ProjectProfile,
                          expected_inputs: dict[Path, bytes | None] | None = None) -> dict[Path, bytes | None]:
    """三种安装入口共用只读迁移计划；None 为经过归属证明的精确删除。

    只处理四个旧默认叶及索引，不接管其他项目文件。含项目内容时保留原始字节，只移除
    受管区或完整相同的通用段落。发布器仍负责权限、身份复核、失败回滚与并发编辑保护。
    """
    try:
        from .validate_project_docs import STANDARD_RULE_RE, MARKDOWN_LINK_RE, collect_standard_leaves, normalized_link_target, read_builtin_standard_sources
    except ImportError:
        from validate_project_docs import STANDARD_RULE_RE, MARKDOWN_LINK_RE, collect_standard_leaves, normalized_link_target, read_builtin_standard_sources
    # 调用方已检查显式根目录。这里再次拒绝根本身的链接，再归一化 macOS 的
    # /var 等合法系统祖先别名；配置的内部相对路径仍由 read_file 逐级拒绝链接。
    for base in (pack, project):
        if not stat.S_ISDIR(base.lstat().st_mode):
            raise ValueError(f"standard migration root must be a real directory: {base}")
    pack, project = pack.resolve(), project.resolve()
    config = read_file(pack / "project.yaml")
    if config is None:
        raise ValueError("project.yaml is missing")
    name_match = re.search(r"(?m)^project_name:[ \t]*(.*)$", config.decode("utf-8"))
    if name_match is None:
        raise ValueError("project.yaml is missing project_name")
    values = {"PROJECT_NAME": parse_project_name(name_match[1]), "DOC_STANDARDS": docs["standards"],
              "DOC_STANDARDS_ROOT": docs["standards_root"].rstrip("/"), "DOC_PROJECT": docs["project"],
              "DOC_FEATURES_DIR": docs["features"].rstrip("/"), "DOC_DESIGN_DIR": docs["standards_root"].rstrip("/")}
    root, index = project / docs["standards_root"], project / docs["standards"]
    index_body = read_file(index)
    originals = {index: index_body}
    errors = []
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError(f"standards root must be a real directory: {root}")
    leaves = collect_standard_leaves(root, errors) if root.exists() else {}
    if errors:
        raise ValueError("; ".join(errors))
    paragraphs = {}
    for source in read_builtin_standard_sources(pack).values():
        for match in RULE_ITEM_RE.finditer(source.encode("utf-8")):
            if match[1] in paragraphs:
                raise ValueError(f"duplicate builtin paragraph: {match[1].decode()}")
            paragraphs[match[1]] = match.group().replace(b"\r\n", b"\n").rstrip(b"\n")
    updates = {}
    for leaf in ("GENERAL.md", "UPSTREAM.md", "DESIGN_FOUNDATIONS.md", "DESIGN_COMPONENTS.md"):
        target = root / leaf
        current = read_file(target)
        originals[target] = current
        if current is None or not current:
            continue
        span = common_span(current) if leaf == "GENERAL.md" else None
        if _legacy_template(leaf, current, values, profile):
            updates[target] = None
            continue
        body = current
        if span is not None:
            region = current[span[0]:span[1]]
            if hashlib.sha256(region.replace(b"\r\n", b"\n")).hexdigest() not in LEGACY_COMMON_BLOCK_HASHES:
                raise ValueError("GENERAL.md common managed region differs from known defaults; preserved unchanged")
            unknown = {rule.encode() for rule, _ in STANDARD_RULE_RE.findall(region.decode("utf-8"))} - paragraphs.keys()
            if unknown:
                raise ValueError("GENERAL.md common managed region contains unknown project rule IDs")
            body = body[:span[0]] + body[span[1]:]
        body = _without_builtin_items(body, paragraphs)
        if body != current:
            updates[target] = body
    remaining = {path: body for path, body in leaves.items() if updates.get(path, b"") is not None}
    for path, body in updates.items():
        if body is not None:
            remaining[path] = body.decode("utf-8")
    normative = {path: body for path, body in remaining.items() if STANDARD_RULE_RE.search(body)}
    deleted = {path.resolve() for path, body in updates.items() if body is None}
    if index_body is not None and _legacy_template("STANDARDS.md", index_body, values, profile):
        index_body = None
        if not normative:
            updates[index] = None
    if normative:
        if not index_body:
            source = read_file(pack / "templates/docs/STANDARDS.md")
            if source is None:
                raise ValueError("project standards index template is missing")
            lines = {"engineering": [], "design": []}
            for path in sorted(normative):
                domain = "design" if path.name.startswith("DESIGN_") else "engineering"
                link = quote(os.path.relpath(path, index.parent), safe="/")
                lines[domain].append(f"- [{path.stem}]({link})")
            substitutions = values | {"ENGINEERING_STANDARDS_INDEX": "\n".join(lines["engineering"]),
                                      "DESIGN_STANDARDS_INDEX": "\n".join(lines["design"])}
            text = re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: substitutions[match[1]], source.decode("utf-8"))
            updates[index] = text.encode("utf-8")
        else:
            text = index_body.decode("utf-8")
            text = re.sub(r"(?m)^.*\[[^\]]+\]\([^)]+\).*?(?:\r?\n|$)",
                          lambda line: _remove_deleted_links(line.group(), index, deleted, normalized_link_target), text)
            linked = {normalized_link_target(index, raw) for raw in MARKDOWN_LINK_RE.findall(text)}
            newline = "\r\n" if b"\r\n" in index_body else "\n"
            missing = [path for path in sorted(normative) if path.resolve() not in linked]
            if missing:
                text += ("" if text.endswith(newline * 2) else newline if text.endswith(newline) else newline * 2)
                text += newline.join(f"- [{path.stem}]({quote(os.path.relpath(path, index.parent), safe='/')})" for path in missing) + newline
            if text.encode("utf-8") != index_body:
                updates[index] = text.encode("utf-8")
    elif index_body:
        text = re.sub(r"(?m)^.*\[[^\]]+\]\([^)]+\).*?(?:\r?\n|$)",
                      lambda line: _remove_deleted_links(line.group(), index, deleted, normalized_link_target), index_body.decode("utf-8"))
        if text.encode("utf-8") != index_body:
            updates[index] = text.encode("utf-8")
    validate_planned_rule_ids(root, updates, pack_root=pack)
    if expected_inputs is not None:
        # 发布方必须绑定生成 after 时实际读取的 before；不能在计划后重新采样并
        # 把并发编辑追认为本轮输入。原字节只在当前内存事务保留，不创建副本文件。
        expected_inputs.update({path: originals[path] for path in updates})
    return updates
