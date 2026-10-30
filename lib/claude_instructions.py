#!/usr/bin/env python3
"""生成当前 Claude 项目入口；保留用户自定义指令，不改变宿主设置。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import tempfile


BEGIN = "<!-- agent-workflow-pack:claude-begin -->"
END = "<!-- agent-workflow-pack:claude-end -->"
# 使用 Claude 官方导入语法，只加载共享正文，不在宿主入口复制规则。
# 安装和校验共用此常量，防止入口退化为不会自动展开的普通文字或代码块。
CLAUDE_IMPORT = b"@AGENTS.md\n"
PAIRS = (
    (BEGIN, END),
    *((f"<!-- pack:{host}-begin -->", f"<!-- pack:{host}-end -->")
      for host in ("product", "codex", "antigravity")),
)


def read_file(path: Path) -> bytes | None:
    """入口必须是单链接普通文件；拒绝链接、特殊节点及危险父目录。"""
    for parent in path.parents:
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f"unsafe instruction parent: {parent}")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"instruction must be a single-link regular file: {path}")
    # 沿用包内安全读取方式：支持的平台使用内核 no-follow，其余仍核对节点身份。
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError(f"instruction changed while opening: {path}")
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError(f"instruction exceeds safe read size: {path}")
    data.decode("utf-8", errors="strict")
    return data


def intervals(body: bytes) -> dict[str, tuple[int, int]]:
    """逐行识别精确标记，并拒绝孤立、重复、交叉或嵌套的宿主区块。"""
    text = body.decode("utf-8", errors="strict")
    result = {}
    for begin, end in PAIRS:
        found = []
        for marker in (begin, end):
            offset = 0
            matches = []
            for line in text.splitlines(keepends=True):
                if line.rstrip("\n") == marker:
                    matches.append((offset, offset + len(line)))
                offset += len(line)
            if text.count(marker) != len(matches) or len(matches) > 1:
                raise ValueError(f"malformed managed marker: {marker}")
            found.extend(matches)
        if not found:
            continue
        if len(found) != 2 or found[0][0] >= found[1][0]:
            raise ValueError(f"malformed managed markers: {begin}")
        result[begin] = (found[0][0], found[1][1])
    ordered = sorted(result.values())
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("managed instruction blocks cross or nest")
    return result


def replace_block(body: bytes, begin: str, replacement: bytes) -> bytes:
    """保留非受管字节；偏移基于解码文本，避免中文多字节内容被截断。"""
    spans = intervals(body)
    if begin in spans:
        start, stop = spans[begin]
        text = body.decode("utf-8")
        return text[:start].encode() + replacement + text[stop:].encode()
    if not replacement:
        return body
    separator = b"" if not body else (b"\n" if body.endswith(b"\n") else b"\n\n")
    return body + separator + replacement


def render(pack: Path, root: Path):
    """正文只写入 AGENTS.md，CLAUDE.md 固定为官方一行导入，无版本分支。"""
    agents = read_file(root / "AGENTS.md")
    claude = read_file(root / "CLAUDE.md")
    # 全新安装只接受缺失入口或精确的一行官方导入；不再识别、备份并迁移旧版正文。
    # 拒绝并不等于删除：用户内容、空文件、旧受管正文均原样保留，由用户明确处置。
    if claude not in (None, CLAUDE_IMPORT):
        raise ValueError("CLAUDE.md contains unsupported or user-owned instructions; resolve them explicitly before setup")
    next_claude = CLAUDE_IMPORT
    next_agents = agents or b""
    # Claude 也支持单独安装，因此共享基础边界不能依赖 setup_all 或其他宿主补写。
    # 每个区块使用固定所有权标记更新；保留区块之外的用户字节及其他宿主区块。
    for begin, end, relative in (
        ("<!-- pack:product-begin -->", "<!-- pack:product-end -->", "shared/AGENTS.product.tpl"),
        (BEGIN, END, "claude/AGENTS.claude.tpl"),
    ):
        template = read_file(pack / "platforms" / relative)
        if template is None:
            raise ValueError(f"missing instruction template: {relative}")
        if intervals(template):
            raise ValueError(f"managed marker injection inside instruction template: {relative}")
        block = begin.encode() + b"\n" + template.rstrip(b"\n") + b"\n" + end.encode() + b"\n"
        spans = intervals(next_agents)
        if begin == "<!-- pack:product-begin -->" and begin not in spans and BEGIN in spans:
            # 缺少共享区块但已存在 Claude 区块时，在其前方补齐共享边界。
            # 不把新块追加到用户尾注之后，从而保持原有前缀、尾部字节和相对位置。
            offset = spans[BEGIN][0]
            text = next_agents.decode("utf-8")
            next_agents = text[:offset].encode() + block + text[offset:].encode()
        else:
            next_agents = replace_block(next_agents, begin, block)
    intervals(next_agents)
    # 安装 Codex 的项目沿用其现有总入口保护值，不把它误当 Claude 官方限制。
    if "<!-- pack:codex-begin -->" in next_agents.decode() and len(next_agents) > 32768:
        raise ValueError("combined AGENTS.md would exceed the existing Codex 32 KiB guard")
    return agents, claude, next_agents, next_claude


def atomic_write(path: Path, data: bytes | None, mode: int) -> None:
    """同目录原子发布；None 仅用于失败回滚，撤回本轮新建的入口。"""
    if data is None:
        path.unlink(missing_ok=True)
        return
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.workflow-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def process(pack: Path, root: Path, action: str) -> None:
    agents, claude, next_agents, next_claude = render(pack, root)
    if action == "preflight-all":
        # 聚合安装必须看最终合成结果，而非分别拿旧入口预检后才在中途发现溢出。
        # 这里只计算字节，不发布文件；各宿主仍执行自己的完整契约和所有权预检。
        combined = next_agents
        for host, relative in (
            ("product", "shared/AGENTS.product.tpl"),
            ("codex", "codex/AGENTS.codex.tpl"),
            ("antigravity", "antigravity/AGENTS.antigravity.tpl"),
        ):
            template = read_file(pack / "platforms" / relative)
            if template is None:
                raise ValueError(f"missing instruction template: {relative}")
            begin, end = f"<!-- pack:{host}-begin -->", f"<!-- pack:{host}-end -->"
            block = begin.encode() + b"\n" + template.rstrip(b"\n") + b"\n" + end.encode() + b"\n"
            combined = replace_block(combined, begin, block)
        if len(combined) > 32768:
            raise ValueError("combined AGENTS.md would exceed the existing Codex 32 KiB guard")
    targets = (root / "AGENTS.md", root / "CLAUDE.md")
    before, after = (agents, claude), (next_agents, next_claude)
    if action == "check":
        if before != after:
            raise ValueError("managed Claude instructions differ from source; run setup_claude.sh")
        return
    if action in ("preflight", "preflight-all"):
        return
    modes = [stat.S_IMODE(p.stat().st_mode) if old is not None else 0o644
             for p, old in zip(targets, before)]
    # 已有精确导入而共享入口尚缺失时继承其权限，避免新正文变成全员可读。
    # 若已有 AGENTS.md，则以它自己的权限为准，保持其他宿主和用户的设置。
    if agents is None and claude is not None:
        modes[0] = modes[1]
    changed = []
    try:
        for path, old, new, mode in zip(targets, before, after, modes):
            if old == new:
                continue
            if read_file(path) != old:
                raise ValueError(f"instruction changed since preflight: {path}")
            atomic_write(path, new, mode)
            changed.append((path, old, new, mode))
    except (OSError, ValueError):
        # 若第二个文件发布失败，回滚本轮已发布的第一个；不覆盖并发用户修改。
        for path, old, new, mode in reversed(changed):
            if read_file(path) == new:
                atomic_write(path, old, mode)
        raise
    # 薄入口本身就是加载路径，不再报告“CLAUDE.md 遮蔽 AGENTS.md”的误导告警。
    # 这里只验证磁盘产物，不能替宿主证明会话加载，也不能绕过组织策略或用户设置。
    print("[INFO] CLAUDE.md 通过 @AGENTS.md 导入共享规则；请在 Claude 会话用 /context 确认实际加载，入口生成器不修改宿主设置")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "preflight-all", "apply", "check"))
    parser.add_argument("pack", type=Path)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        process(args.pack.resolve(), args.root.resolve(), args.action)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
