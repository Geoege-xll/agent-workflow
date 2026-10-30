"""项目角色的模型偏好合同；只处理配置字段，不改变权限、正文或任务编排。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

HOSTS = ("codex", "claude", "antigravity")
ROLES = frozenset({"xy-web", "xy-desktop", "xy-backend", "xy-apple", "xy-android", "xy-uiux", "xy-qa"})
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@\[\]-]{0,199}\Z")


def validate(host: str, value: dict) -> dict[str, str]:
    """限制可写字段并拒绝注入；未知能力由管理器按具体目录进一步核验。"""
    if host not in HOSTS or not isinstance(value, dict) or set(value) - {"model", "effort"}:
        raise ValueError("角色模型配置只接受已知平台及 model / effort 字段")
    model, effort = value.get("model", "inherit"), value.get("effort", "inherit")
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
        raise ValueError("模型标识必须是单行模型 ID 或 inherit")
    if not isinstance(effort, str) or effort not in (*EFFORTS, "inherit"):
        raise ValueError("无效推理级别；不提供会开启自动委派的 ultra")
    if host == "antigravity" and (model not in {"inherit", "flash", "pro"} or effort != "inherit"):
        raise ValueError("Antigravity 静态角色仅支持 inherit / flash / pro，推理级别继承")
    if host == "claude" and effort not in {"inherit", "low", "medium", "high", "xhigh", "max"}:
        raise ValueError("Claude 角色不支持该 effort 字段值")
    return {"model": model, "effort": effort}


def block_span(lines: list[str]) -> tuple[int, int] | None:
    """读取与替换共用边界：顶格注释不结束映射，末尾外部注释留给后续章节。"""
    starts = [i for i,line in enumerate(lines) if re.match(r"^role_models:",line)]
    if not starts:
        return None
    if len(starts) != 1:
        raise ValueError("role_models 不可重复")
    start = starts[0]
    end = start + 1
    for index in range(start + 1,len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ","\t")):
            break
        end = index + 1
    return start,end


def parse(text: str) -> dict[str, dict[str, dict[str, str]]]:
    """解析有界 YAML 子集：每个角色值为内联 JSON，避免引入额外 YAML 运行依赖。

    示例 role_models 下两空格为平台、四空格为角色，角色值使用 JSON 对象。
    JSON 本身是合法 YAML；拒绝重复键、未知平台及不完整区块，不能静默回退。
    """
    lines = text.splitlines()
    span = block_span(lines)
    if span is None:
        return {}
    start,end = span
    if lines[start].strip() == "role_models: {}":
        if end > start + 1:
            raise ValueError("空 role_models 映射后不能继续包含子条目")
        return {}
    if lines[start].strip() != "role_models:":
        raise ValueError("role_models 必须是映射区块")
    result: dict[str, dict] = {}
    host = None
    for line in lines[start + 1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            break
        match = re.fullmatch(r"  (codex|claude|antigravity):", line)
        if match:
            host = match[1]
            if host in result:
                raise ValueError(f"重复平台：{host}")
            result[host] = {}
            continue
        match = re.fullmatch(r"    (xy-[a-z-]+): (\{.*\})", line)
        if not match or host is None or match[1] not in ROLES:
            raise ValueError(f"不支持的 role_models 条目：{line.strip()}")
        role = match[1]
        if role in result[host]:
            raise ValueError(f"重复角色：{host}/{role}")
        def unique(pairs):
            obj = {}
            for name, value in pairs:
                if name in obj:
                    raise ValueError(f"重复模型字段：{name}")
                obj[name] = value
            return obj
        result[host][role] = validate(host, json.loads(match[2], object_pairs_hook=unique))
    return result


def load(pack: Path) -> dict:
    return parse((pack / "project.yaml").read_text(encoding="utf-8"))


def settings(pack: Path, host: str, role: str, default_effort: str = "inherit") -> dict[str, str]:
    if host not in HOSTS or role not in ROLES:
        raise ValueError("未知平台或角色")
    return load(pack).get(host, {}).get(role, {"model": "inherit", "effort": default_effort})


def update(text: str, choices: dict[str, dict[str, dict]]) -> str:
    """仅替换模型区块；其余项目文档、发现配置与编排参数保持原字节文本。"""
    parse(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = ["role_models:"]
    for host in HOSTS:
        if not choices.get(host):
            continue
        lines.append(f"  {host}:")
        for role, value in sorted(choices[host].items()):
            if role not in ROLES:
                raise ValueError(f"未知角色：{role}")
            lines.append(f"    {role}: {json.dumps(validate(host, value), ensure_ascii=False)}")
    block = newline.join(lines) + newline
    # 按保留换行的实际行定位，最后一行没有换行也必须完整替换，不能留下重复角色。
    original = text.splitlines(keepends=True)
    span = block_span(original)
    if span is not None:
        start,end = span
        # 保留区块内部说明，避免把平台间注释后面的旧平台再次留在新配置中。
        comments = [line.rstrip("\r\n") for line in original[start+1:end] if line.lstrip().startswith("#")]
        block = newline.join([lines[0],*comments,*lines[1:]]) + newline
        return "".join(original[:start]) + block + "".join(original[end:])
    return text + ("" if text.endswith(newline) else newline) + newline + block


def fields(host: str, value: dict) -> str:
    value = validate(host, value)
    result = []
    if host == "codex":
        if value["model"] != "inherit":
            result.append(f'model = {json.dumps(value["model"])}')
        if value["effort"] != "inherit":
            result.append(f'model_reasoning_effort = "{value["effort"]}"')
    else:
        result.append(f'model: {value["model"]}')
        if host == "claude" and value["effort"] != "inherit":
            result.append(f'effort: {value["effort"]}')
    return "\n".join(result)


def patch_artifact(raw: bytes, host: str, value: dict) -> bytes:
    """只修改模型字段；Codex 同步更新已有受管载荷指纹，正文及权限保持不变。"""
    text = raw.decode("utf-8")
    if host == "codex":
        header, payload = text.split("\n", 1)
        match = re.fullmatch(r"# (.+:v1 sha256=)([0-9a-f]{64})", header)
        if not match or hashlib.sha256(payload.encode()).hexdigest() != match[2]:
            raise ValueError("Codex 角色缺少有效的受管指纹")
        payload = re.sub(r"^(?:model|model_reasoning_effort) = [^\n]*\n", "", payload, flags=re.MULTILINE)
        lines = payload.splitlines(keepends=True)
        snippet = fields(host, value)
        if snippet:
            lines.insert(2, snippet + "\n")
        payload = "".join(lines)
        return f"# {match[1]}{hashlib.sha256(payload.encode()).hexdigest()}\n{payload}".encode()
    front, body = text.split("\n---\n", 1)
    if not front.startswith("---\n") or "agent-workflow" not in body.lower():
        raise ValueError("角色不是工作流受管产物")
    front, count = re.subn(r"^model: [^\n]+", fields(host, value), front, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError("角色缺少唯一 model 字段")
    # 已有 effort 先移除；新值通过 fields 一次插入，避免重复键。
    if host == "claude":
        front = re.sub(r"^effort: [^\n]+\n?", "", front, flags=re.MULTILINE)
        front = re.sub(r"^model: [^\n]+", fields(host, value), front, count=1, flags=re.MULTILINE)
    return (front + "\n---\n" + body).encode()


if __name__ == "__main__":
    try:
        pack, host, role, *default = sys.argv[1:]
        print(fields(host, settings(Path(pack), host, role, default[0] if default else "inherit")))
    except (ValueError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2)
