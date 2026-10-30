#!/usr/bin/env python3
"""Merge agent_workflow defaults into a user-owned Codex TOML config."""

from __future__ import annotations

import re
import os
import sys
import tempfile
import tomllib
from pathlib import Path


AGENTS_BEGIN = "# agent-workflow-pack:agents-defaults-begin"
AGENTS_END = "# agent-workflow-pack:agents-defaults-end"
UNSUPPORTED_LEGACY_MARKERS = (
    "# agent-workflow-pack:codex-begin",
    "# agent-workflow-pack:codex-end",
)

TABLE_RE = re.compile(r"^\s*\[([^\[\]]+)]\s*(?:#.*)?$")
ASSIGNMENT_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>"
    r"enabled|max_concurrent_threads_per_session|max_depth|interrupt_message|"
    r"max_threads|job_max_runtime_seconds"
    r")\s*=.*$"
)


def remove_marked_block(lines: list[str], begin: str, end: str) -> list[str]:
    result: list[str] = []
    inside = False
    found_begin = False
    for line in lines:
        stripped = line.strip()
        if stripped == begin:
            if inside:
                raise ValueError(f"nested managed marker: {begin}")
            inside = True
            found_begin = True
            continue
        if stripped == end:
            if not inside:
                raise ValueError(f"orphan managed marker: {end}")
            inside = False
            continue
        if not inside:
            result.append(line)
    if inside or (found_begin and any(line.strip() == begin for line in result)):
        raise ValueError(f"unterminated managed marker: {begin}")
    return result


def find_table(lines: list[str], name: str) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        match = TABLE_RE.match(line)
        if not match or match.group(1).strip() != name:
            continue
        end = len(lines)
        for candidate in range(index + 1, len(lines)):
            if lines[candidate].lstrip().startswith("["):
                end = candidate
                break
        return index, end
    return None


def merge_agents_table(lines: list[str], max_threads: int) -> list[str]:
    desired = {
        "enabled": "enabled = true",
        "max_concurrent_threads_per_session": (
            f"max_concurrent_threads_per_session = {max_threads}"
        ),
        "interrupt_message": "interrupt_message = true",
    }
    legacy = {"max_depth", "max_threads", "job_max_runtime_seconds"}
    bounds = find_table(lines, "agents")
    if bounds is None:
        separator = [""] if lines and lines[-1] else []
        return [
            *lines,
            *separator,
            AGENTS_BEGIN,
            "[agents]",
            *desired.values(),
            AGENTS_END,
        ]

    start, end = bounds
    found: set[str] = set()
    section: list[str] = []
    for line in lines[start + 1 : end]:
        match = ASSIGNMENT_RE.match(line)
        if not match:
            section.append(line)
            continue
        key = match.group("key")
        if key in legacy:
            raise ValueError(
                f"user-owned agents.{key} conflicts with managed Codex agent limits; "
                "remove or migrate it explicitly"
            )
        section.append(match.group("indent") + desired[key])
        found.add(key)

    missing = [value for key, value in desired.items() if key not in found]
    if missing:
        while section and section[-1] == "":
            section.pop()
        section.extend([AGENTS_BEGIN, *missing, AGENTS_END, ""])

    return [*lines[: start + 1], *section, *lines[end:]]


def render(original: str, max_threads: int) -> str:
    """只推演本轮原生 agents 配置；快照与实际发布必须调用同一生成逻辑。"""
    lines = original.splitlines()
    for marker in UNSUPPORTED_LEGACY_MARKERS:
        if any(line.strip() == marker for line in lines):
            raise ValueError(
                f"unsupported legacy Codex config marker: {marker}; "
                "remove the obsolete managed block explicitly"
            )
    # 验证现有标记，但不删除再搬动整块。[agents] 的当前受管值可就地合并，
    # 否则与辅助 Hooks 块交替追加会累计空白，并破坏升级前推演的配置快照。
    remove_marked_block(lines, AGENTS_BEGIN, AGENTS_END)

    stripped = "\n".join(lines).strip()
    try:
        parsed = tomllib.loads(stripped) if stripped else {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"existing Codex config is invalid: {exc}") from exc

    if not lines:
        lines = ["#:schema https://developers.openai.com/codex/config-schema.json", ""]
    lines = merge_agents_table(lines, max_threads)

    rendered = "\n".join(lines).rstrip() + "\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"merged Codex config would be invalid: {exc}") from exc
    return rendered


def merge(path: Path, max_threads: int) -> None:
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    rendered = render(original, max_threads)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: merge_codex_config.py PATH MAX_THREADS",
            file=sys.stderr,
        )
        return 2
    path = Path(sys.argv[1])
    try:
        merge(path, int(sys.argv[2]))
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
