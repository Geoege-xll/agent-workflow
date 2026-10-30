"""轻量 Hooks 的单一开关；不引入任务状态或旧版配置适配。"""

from __future__ import annotations

import re


def hook_mode(text: str) -> str:
    """只接受 assist/off；缺省启用辅助提醒，但不改变宿主原生禁用设置。"""
    sections = re.findall(r"^workflow_hooks:\s*(?:#.*)?$", text, re.M)
    if len(sections) > 1:
        raise ValueError("duplicate workflow_hooks section")
    if not sections:
        if re.search(r"^workflow_hooks:", text, re.M):
            raise ValueError("workflow_hooks must be a mapping")
        return "assist"
    tail = re.split(r"^workflow_hooks:\s*(?:#.*)?$", text, flags=re.M)[1]
    mode = "assist"
    seen = False
    for line in tail.splitlines():
        if line and not line.startswith((" ", "#")):
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"  mode:\s*(assist|off)\s*(?:#.*)?", line)
        if not match or seen:
            raise ValueError("workflow_hooks supports only one mode: assist | off")
        mode, seen = match.group(1), True
    return mode
