#!/usr/bin/env python3
"""当前规范索引计划与文档发布所用的精确恢复原语。"""
from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Mapping
from urllib.parse import quote

try:
    from lib.project.project_discovery import ProjectProfile
    from lib.hosts.claude_instructions import read_file
    from lib.project.validate_project_config import parse_project_name
    from lib.platform_fs import os as fs, publish_exclusive
except ImportError:
    from lib.project.project_discovery import ProjectProfile
    from lib.hosts.claude_instructions import read_file
    from lib.project.validate_project_config import parse_project_name
    from lib.platform_fs import os as fs, publish_exclusive

def remove_created_standard(path: Path, expected: bytes, mode: int, identity: tuple[int, int]) -> None:
    """只撤回新建规范索引的已采样身份，不能 unlink 采样之后出现的用户替换。

    POSIX 先把当前名字移入本函数独占的临时名，再核对身份、权限和完整内容；若移动
    的已是用户替换，只能排他放回，不能覆盖间隙的新文件。Windows 复用已有按打开
    身份校验并删除的原语。临时名仅保护这一文件，失败保留的路径随错误交回调用方。
    """
    if fs.name == "nt":
        try:
            from lib.windows_fs import remove_file_if_unchanged
        except ImportError:
            from lib.windows_fs import remove_file_if_unchanged
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


def validate_planned_rule_ids(root: Path, updates: Mapping[Path, bytes | None], *, pack_root: Path) -> None:
    """用候选视图核对内置与项目 ID 唯一性；删除条目不能继续占据规则所有权。"""
    try:
        from lib.validate_project_docs import STANDARD_RULE_RE, collect_standard_leaves, read_builtin_standard_sources
    except ImportError:
        from lib.validate_project_docs import STANDARD_RULE_RE, collect_standard_leaves, read_builtin_standard_sources
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


def plan_standard_updates(pack: Path, project: Path, *, docs: Mapping[str, str],
                          profile: ProjectProfile,
                          expected_inputs: dict[Path, bytes | None] | None = None) -> dict[Path, bytes | None]:
    """当前 source setup 共用只读规范索引补齐；绝不剥离或删除既有规则正文。

    只在存在真实项目规则时创建/补齐索引。规范叶、说明、历史原件与模板归属
    均由项目维护；此处仅验证现有 ID/领域并把未列出的叶链接到当前索引。
    发布器仍负责权限、身份复核、失败恢复与并发编辑保护。
    """
    try:
        from lib.validate_project_docs import STANDARD_RULE_RE, MARKDOWN_LINK_RE, collect_standard_leaves, normalized_link_target
    except ImportError:
        from lib.validate_project_docs import STANDARD_RULE_RE, MARKDOWN_LINK_RE, collect_standard_leaves, normalized_link_target
    # 调用方已检查显式根目录。这里再次拒绝根本身的链接，再归一化 macOS 的
    # /var 等合法系统祖先别名；配置的内部相对路径仍由 read_file 逐级拒绝链接。
    for base in (pack, project):
        if not stat.S_ISDIR(base.lstat().st_mode):
            raise ValueError(f"standard source root must be a real directory: {base}")
    pack, project = pack.resolve(), project.resolve()
    config = read_file(pack / "project.yaml")
    if config is None:
        raise ValueError("project.yaml is missing")
    name_match = re.search(r"(?m)^project_name:[ \t]*(.*)$", config.decode("utf-8"))
    if name_match is None:
        raise ValueError("project.yaml is missing project_name")
    values = {"PROJECT_NAME": parse_project_name(name_match[1]), "DOC_STANDARDS": docs["standards"],
              "DOC_STANDARDS_ROOT": docs["standards_root"].rstrip("/"), "DOC_PROJECT": docs["project"],
              "DOC_DESIGN_DIR": docs["standards_root"].rstrip("/")}
    root, index = project / docs["standards_root"], project / docs["standards"]
    index_body = read_file(index)
    originals = {index: index_body}
    errors = []
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError(f"standards root must be a real directory: {root}")
    leaves = collect_standard_leaves(root, errors) if root.exists() else {}
    if errors:
        raise ValueError("; ".join(errors))
    updates = {}
    normative = {path: body for path, body in leaves.items() if STANDARD_RULE_RE.search(body)}
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
            linked = {normalized_link_target(index, raw) for raw in MARKDOWN_LINK_RE.findall(text)}
            newline = "\r\n" if b"\r\n" in index_body else "\n"
            missing = [path for path in sorted(normative) if path.resolve() not in linked]
            if missing:
                text += ("" if text.endswith(newline * 2) else newline if text.endswith(newline) else newline * 2)
                text += newline.join(f"- [{path.stem}]({quote(os.path.relpath(path, index.parent), safe='/')})" for path in missing) + newline
            if text.encode("utf-8") != index_body:
                updates[index] = text.encode("utf-8")
    validate_planned_rule_ids(root, updates, pack_root=pack)
    if expected_inputs is not None:
        # 发布方必须绑定生成 after 时实际读取的 before；不能在计划后重新采样并
        # 把并发编辑追认为本轮输入。原字节只在当前内存事务保留，不创建副本文件。
        expected_inputs.update({path: originals[path] for path in updates})
    return updates
