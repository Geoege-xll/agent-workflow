"""校验器按入口中的显式引用展开完整契约；Agent 仍按场景渐进读取。

此模块只组织待校验文本，不改变插件产物，也不替 Agent 预载引用。各宿主继续
提供自己的安全读取函数，保留已有的目录、符号链接、硬链接和文件身份检查。
普通 Markdown 链接不会自动展开，避免把辅助资料或外部内容升级成契约入口。
"""

from __future__ import annotations

import re
from collections.abc import Callable


INCLUDE = re.compile(r"(?m)^<!-- workflow-contract: (references/[a-z0-9-]+\.md) -->$")

def expand_skill_contract(body: str, read_reference: Callable[[str], str]) -> str:
    """按原位置展开显式分支，防止缩短入口后漏检原有规则或生命周期顺序。

    引用仅允许当前 Skill 下的一层 references Markdown；不接受绝对路径、
    父目录、重复引用或递归包含。每个标记必须配有用户可读的 Markdown 路由链接，
    不能让机器校验了规则、Agent 却没有可发现的入口。读取失败由调用方报告。
    """
    matches = list(INCLUDE.finditer(body))
    if body.count("<!-- workflow-contract:") != len(matches):
        raise ValueError("malformed workflow contract reference")
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        relative = match.group(1)
        if relative in seen:
            raise ValueError(f"duplicate workflow contract reference: {relative}")
        seen.add(relative)
        if not re.search(r"\[[^\]\n]+\]\(" + re.escape(relative) + r"\)", body):
            raise ValueError(f"workflow contract reference has no routing link: {relative}")
        detail = read_reference(relative)
        if not detail.strip():
            raise ValueError(f"empty workflow contract reference: {relative}")
        if "<!-- workflow-contract:" in detail:
            raise ValueError(f"nested workflow contract reference is unsupported: {relative}")
        return detail.rstrip()

    return INCLUDE.sub(replace, body)


def verification_scope_errors(body: str) -> list[str]:
    """保护本包新增的验证语义，不把任意 Skill 的格式检查升级为测试政策。

    这是源契约回归守卫而非自然语言执行器：确认关键约束未遗漏，并拦截明确的
    反向指令；真实 Agent 是否正确选择验证范围仍由独立审查与宿主反馈检验。
    """
    text = " ".join(body.split()).casefold()
    required = {
        "candidate commands": "repository-discovered commands are candidates",
        "mandatory checks": "keep explicitly required checks",
        "independent QA": "qa independently inspects the actual diff/source",
        "evidence validity": "dependencies and relevant environment still match",
        "test stop condition": "broaden or repeat only for",
        "missing evidence blocks success": "mandatory evidence prevents build_verified or qa pass",
    }
    errors = [f"verification scope missing {label}" for label, phrase in required.items()
              if phrase not in text]
    for pattern in (
        r"\bqa (?:may|can|should) (?:skip|waive) (?:mandatory|required) checks\b",
        r"\b(?:always|must) run (?:all|every) (?:discovered|available) (?:commands?|tests?|suites?)\b",
        r"\breuse (?:implementer )?evidence without (?:checking|confirming|validating)\b",
    ):
        if re.search(pattern, text):
            errors.append("verification scope contains an explicit policy inversion")
    return errors
