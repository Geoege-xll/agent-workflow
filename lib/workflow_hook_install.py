#!/usr/bin/env python3
"""合并三平台项目 Hooks：只拥有带内容签名的条目，保留用户设置和原生信任。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tomllib

sys.dont_write_bytecode = True
if __package__:
    from .claude_instructions import atomic_write, read_file
    from .workflow_hook_settings import hook_mode
    from .workflow_hooks import OWNER
else:
    from claude_instructions import atomic_write, read_file
    from workflow_hook_settings import hook_mode
    from workflow_hooks import OWNER

BEGIN = "# agent-workflow-pack:assist-hooks-begin"
END = "# agent-workflow-pack:assist-hooks-end"
SIGNATURE = "WORKFLOW_SIGNATURE_PLACEHOLDER"
EVENTS = {
    "codex": (("SessionStart", "startup|resume|clear|compact"), ("UserPromptSubmit", "")),
    "claude": (("SessionStart", "startup|resume|clear|compact"),
               ("UserPromptSubmit", ""), ("PreToolUse", "^Agent$")),
    "antigravity": (("PreInvocation", ""),),
}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def signed_group(pack: Path, project: Path, host: str, event: str, matcher: str) -> dict:
    """命令路径及项目路径均按 shell 参数引用；不会执行用户拖入的路径文本。"""
    command = shlex.join([sys.executable, "-B", str(pack / "lib/workflow_hooks.py"),
                          "--host", host, "--event", event, "--project", str(project),
                          "--owner", OWNER, "--signature", SIGNATURE])
    handler = {"type": "command", "command": command, "timeout": 3}
    if host == "codex":
        handler["additionalContextLimit"] = 512
    group = {"hooks": [handler]}
    if matcher:
        group["matcher"] = matcher
    if host == "antigravity":
        group = handler
    digest = hashlib.sha256(canonical(group)).hexdigest()
    handler["command"] = command[:-len(SIGNATURE)] + digest
    return group


def owned_group(group: object) -> bool:
    """标记不是充分证据：用户改过任何条目字段都必须停止覆盖。"""
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks", [group])
    if not isinstance(handlers, list):
        return False
    candidates = [item for item in handlers if isinstance(item, dict)
                  and isinstance(item.get("command"), str) and OWNER in item["command"]]
    if not candidates:
        return False
    if len(handlers) != 1 or len(candidates) != 1:
        raise ValueError("mixed or modified managed Hook group; preserve it and resolve explicitly")
    command = candidates[0]["command"]
    args = shlex.split(command)
    if (len(args) != 13 or args[1] != "-B" or not args[2].endswith("/lib/workflow_hooks.py")
            or args[3] != "--host" or args[4] not in EVENTS or args[5] != "--event"
            or args[7] != "--project" or args[9:12] != ["--owner", OWNER, "--signature"]
            or not re.fullmatch(r"[0-9a-f]{64}", args[12])):
        raise ValueError("unproven managed Hook command; preserve it and resolve explicitly")
    unsigned = copy.deepcopy(group)
    handler = unsigned.get("hooks", [unsigned])[0]
    # 只替换末尾参数而非任意路径中的同名内容，防止签名校验产生歧义。
    handler["command"] = command[:-64] + SIGNATURE
    if hashlib.sha256(canonical(unsigned)).hexdigest() != args[12]:
        raise ValueError("modified managed Hook signature; preserve it and resolve explicitly")
    return True


def json_object(raw: bytes | None) -> dict:
    """拒绝重复 JSON 键，避免解析时静默丢掉原来的用户权限或 Hook。"""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    data = {} if raw is None else json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(data, dict):
        raise ValueError("project Hook settings must be a JSON object")
    return data


def merge_json(data: dict, pack: Path, project: Path, host: str, mode: str) -> dict:
    """只替换可证明归属的条目；所有其他键、事件、匹配器及权限保持原语义。"""
    result = copy.deepcopy(data)
    if host == "antigravity":
        current = result.get(OWNER)
        enabled = True
        if current is not None:
            if not isinstance(current, dict) or set(current) - {"enabled", "PreInvocation"}:
                raise ValueError("user-owned Antigravity Hook name collision")
            groups = current.get("PreInvocation")
            if not isinstance(groups, list) or len(groups) != 1 or not owned_group(groups[0]):
                raise ValueError("unproven Antigravity Hook name collision")
            enabled = current.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ValueError("invalid Antigravity Hook enabled value")
            result.pop(OWNER)
        if mode == "assist":
            result[OWNER] = {"enabled": enabled, "PreInvocation": [
                signed_group(pack, project, host, "PreInvocation", "")]}
        return result
    hooks = result.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an event mapping")
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            raise ValueError(f"hooks.{event} must be a list")
        retained = [group for group in groups if not owned_group(group)]
        if retained:
            hooks[event] = retained
        elif retained != groups:
            hooks.pop(event)
    if mode == "assist":
        for event, matcher in EVENTS[host]:
            hooks.setdefault(event, []).append(signed_group(pack, project, host, event, matcher))
    if hooks:
        result["hooks"] = hooks
    else:
        result.pop("hooks", None)
    return result


def merge_inline(raw: bytes | None, pack: Path, project: Path, mode: str) -> bytes:
    """Codex 已使用 TOML Hooks 时沿用该来源，不再制造同层双配置。

    用户 TOML 字节不重排；受管块必须具有精确边界和字节签名。原生 features.hooks
    等开关不属于本模块，既不强制启用，也不迁移用户自己的旧设置。
    """
    original = (raw or b"").decode("utf-8")
    text = original
    if BEGIN in text or END in text:
        pattern = re.compile(re.escape(BEGIN) + r" sha256=([0-9a-f]{64})\n(.*?)"
                             + re.escape(END) + r"\n", re.S)
        matches = list(pattern.finditer(text))
        if len(matches) != 1 or text.count(BEGIN) != 1 or text.count(END) != 1:
            raise ValueError("malformed managed Codex Hook block")
        match = matches[0]
        if hashlib.sha256(match.group(2).encode()).hexdigest() != match.group(1):
            raise ValueError("modified managed Codex Hook block")
        text = text[:match.start()] + text[match.end():]
    tomllib.loads(text)
    if mode == "off":
        return text.encode()
    chunks = []
    for event, matcher in EVENTS["codex"]:
        group = signed_group(pack, project, "codex", event, matcher)
        chunks.append(f"[[hooks.{event}]]\n")
        if matcher:
            chunks.append(f"matcher = {json.dumps(matcher)}\n")
        chunks.append(f"[[hooks.{event}.hooks]]\n")
        for key, value in group["hooks"][0].items():
            chunks.append(f"{key} = {json.dumps(value, ensure_ascii=False)}\n")
    body = "".join(chunks)
    separator = "" if not text or text.endswith("\n") else "\n"
    rendered = (text + separator + BEGIN + " sha256="
                + hashlib.sha256(body.encode()).hexdigest() + "\n" + body + END + "\n")
    tomllib.loads(rendered)
    return rendered.encode()


def project_codex_config(config: bytes, before: bytes | None) -> bytes:
    """纯推演原生 agents 字段，供快照与原子发布共同使用。"""
    if __package__:
        from .merge_codex_config import render
        from .validate_project_config import section_lines
    else:
        from merge_codex_config import render
        from validate_project_config import section_lines
    matches = [re.fullmatch(r"  max_concurrent_subagents:\s*([1-9][0-9]*)\s*(?:#.*)?", line)
               for line in section_lines(config.decode().splitlines(), "orchestration")]
    limits = [int(match.group(1)) for match in matches if match is not None]
    return render((before or b"").decode(), limits[0] if limits else 8).encode()


def plan_hooks(pack: Path, project: Path, host: str, *, simulate_codex_setup: bool = False) -> tuple[Path, bytes | None, bytes]:
    """预检、发布、验收共用生成结果；预检不会创建项目目录或配置。"""
    # macOS /var、/tmp 等系统别名先解析为真实根；配置文件自身仍保持 no-follow 校验。
    pack, project = pack.resolve(strict=True), project.resolve(strict=True)
    config = read_file(pack / "project.yaml")
    if config is None:
        raise ValueError("missing project.yaml")
    mode = hook_mode(config.decode())
    if host == "codex":
        toml = project / ".codex/config.toml"
        original_toml = read_file(toml)
        parsed = tomllib.loads((original_toml or b"").decode())
        existing_json = read_file(project / ".codex/hooks.json")
        json_hooks = json_object(existing_json).get("hooks", {})
        if not isinstance(json_hooks, dict):
            raise ValueError("Codex JSON hooks must be an event mapping")
        has_owned_json = any(owned_group(group) for groups in json_hooks.values()
                             if isinstance(groups, list) for group in groups)
        if ("hooks" in parsed or BEGIN in (original_toml or b"").decode()) and not has_owned_json:
            projected = original_toml
            if simulate_codex_setup:
                # 同文件先由原生 agents 合并器更新，再合并 Hooks。快照需包含这两个
                # 受管步骤的真实结果，不能将合法并发数更新误认成用户并发修改。
                projected = project_codex_config(config, original_toml)
            return toml, original_toml, merge_inline(projected, pack, project, mode)
    relative = {"codex": ".codex/hooks.json", "claude": ".claude/settings.json",
                "antigravity": ".agents/hooks.json"}[host]
    path = project / relative
    before = read_file(path)
    data = json_object(before)
    merged = merge_json(data, pack, project, host, mode)
    # 没有语义变化时保留用户格式；off 且从未安装则不创建空宿主配置。
    after = before if data == merged and before is not None else (
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode()
    if before is None and mode == "off":
        after = b""
    return path, before, after


def process(pack: Path, project: Path, host: str, action: str) -> None:
    native_publish = action == "apply-codex-config"
    if native_publish and host != "codex":
        raise ValueError("apply-codex-config is Codex-only")
    path, before, after = plan_hooks(pack, project, host, simulate_codex_setup=native_publish)
    if native_publish and path.name != "config.toml":
        # JSON Hooks 与原生配置分属两个文件，没有共享容器的中间态覆盖风险。
        # 本步骤只发布原生配置；JSON Hook 仍在角色与 Skill 同步之后发布。
        path = project.resolve(strict=True) / ".codex/config.toml"
        before = read_file(path)
        config = read_file(pack.resolve(strict=True) / "project.yaml")
        if config is None:
            raise ValueError("missing project.yaml")
        after = project_codex_config(config, before)
    if action == "check":
        if before != after and not (before is None and not after):
            raise ValueError(f"managed {host} Hook configuration differs from source: {path}")
    elif action in {"apply", "apply-codex-config"} and before != after and not (before is None and not after):
        mode = stat.S_IMODE(path.stat().st_mode) if before is not None else 0o644
        path.parent.mkdir(parents=True, exist_ok=True)
        if read_file(path) != before:
            raise ValueError("Hook settings changed after preflight; preserve concurrent edit")
        atomic_write(path, after, mode)
    print(f"[OK] {host} assist Hooks {action} (no permission/trust changes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "apply", "check", "apply-codex-config"))
    parser.add_argument("pack", type=Path)
    parser.add_argument("project", type=Path)
    parser.add_argument("host", choices=tuple(EVENTS))
    args = parser.parse_args()
    try:
        process(args.pack, args.project, args.host, args.action)
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
