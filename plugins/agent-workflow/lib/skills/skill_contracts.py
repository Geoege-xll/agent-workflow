"""校验器按入口中的显式引用展开完整契约；Agent 仍按场景渐进读取。

此模块只组织待校验文本，不改变安装产物，也不替 Agent 预载引用。各宿主继续
提供自己的安全读取函数，保留已有的目录、符号链接、硬链接和文件身份检查。
普通 Markdown 链接不会自动展开，避免把辅助资料或外部内容升级成契约入口。
"""

from __future__ import annotations

import re
from collections.abc import Callable


INCLUDE = re.compile(r"(?m)^<!-- workflow-contract: (references/[a-z0-9-]+\.md) -->$")

# 根入口只允许引用已知的本包契约，不能把目录化升级变成任意文件包含机制。
# 这些注释仅供安装器完整审计；宿主看到普通 Markdown 导航，仍按当前任务读取。
BOOTSTRAP_TARGETS = {
    "platforms/shared/AGENTS.product.tpl": "platforms/shared/skills/xy-workflow/SKILL.md",
    **{f"platforms/{host}/AGENTS.{host}.tpl": f"platforms/{host}/references/pm-integration.md"
       for host in ("codex", "claude", "antigravity")},
}
BOOTSTRAP_INCLUDE = re.compile(
    r"(?m)^<!-- bootstrap-contract: ("
    + "|".join(re.escape(path) for path in BOOTSTRAP_TARGETS.values())
    + r") -->$"
)


def expand_bootstrap_contract(
    body: str, read_reference: Callable[[str], str], expected_reference: str,
) -> str:
    """审计短入口及唯一声明的详细契约，不替宿主预载任何文件。

    限定目标、唯一标记及可发现的导航链接；错配宿主、缺失、空文件、递归包含
    都拒绝安装。回调继续使用调用方的安全读取，保留链接与目录逃逸保护。
    """
    matches = list(BOOTSTRAP_INCLUDE.finditer(body))
    if body.count("<!-- bootstrap-contract:") != len(matches):
        raise ValueError("malformed bootstrap contract reference")
    if len(matches) != 1 or matches[0].group(1) != expected_reference:
        raise ValueError(f"bootstrap must route exactly once to {expected_reference}")
    relative = matches[0].group(1)
    link = r"\[[^\]\n]+\]\(\.agent-workflow/" + re.escape(relative) + r"\)"
    if not re.search(link, body):
        raise ValueError(f"bootstrap contract reference has no routing link: {relative}")
    detail = read_reference(relative)
    if not detail.strip():
        raise ValueError(f"empty bootstrap contract reference: {relative}")
    if "<!-- bootstrap-contract:" in detail:
        raise ValueError(f"nested bootstrap contract reference is unsupported: {relative}")
    return BOOTSTRAP_INCLUDE.sub(lambda _match: detail.rstrip(), body)


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
