"""三宿主共用的静态技能绑定；这里只描述资源，不改变任务或执行权限。"""

from __future__ import annotations

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from product.command_identity import load_identity


IMPLEMENTER_ROLES = frozenset({
    "xy-web", "xy-desktop", "xy-backend", "xy-apple", "xy-android",
})

# 此集合只决定随包发现的共享资源。平台指导按任务选用，角色的固定预载仍由 ROLE_SKILLS 决定。
CORE_SKILLS = frozenset({
    "xy-build-verify", "xy-project-memory", "xy-plan", "xy-prototype-verify", "xy-qa-review",
    "xy-workflow", "xy-code-standards", "xy-ui-design", "xy-web-guidance", "xy-apple-guidance",
    "xy-mobile-ui",
})
COMMAND_IDENTITY = load_identity(Path(__file__).resolve().parents[2])
SELECTED_SKILL_ALIASES = {public: canonical for public, canonical in COMMAND_IDENTITY["skill_aliases"].items()
                          if canonical != "agent-config"}
SELECTED_SKILLS = frozenset(SELECTED_SKILL_ALIASES)


def selected_alias(canonical: str) -> str:
    """角色与构建器共用唯一产品声明的公开名称，不改上游canonical名称。"""
    return next(public for public, original in SELECTED_SKILL_ALIASES.items() if original == canonical)


PM_SKILLS = (selected_alias("grilling"),)

ROLE_SKILLS = {
    # 浏览器项目和微信小程序共用 xy-web。只有项目测试留下生产浏览器交互缺口时，
    # 才按验证规则读取 Playwright，因此 Web 角色沿用五个实现角色共同的启动技能。
    **{role: ("xy-code-standards", "xy-build-verify") for role in IMPLEMENTER_ROLES},
    # 设计规范维护与原型交付共用设计方法；具体 HTML 页交付时由设计角色执行静态验收。
    "xy-uiux": ("xy-ui-design",),
    # QA 保持唯一审查入口，代码/UI 方法由实际审查面选择，不能无条件预载全文。
    "xy-qa": ("xy-qa-review",),
}
CLAUDE_ROLE_SKILLS = dict(ROLE_SKILLS)
ANTIGRAVITY_ROLE_SKILLS = {
    role: tuple(f"skills/{skill}" for skill in skills)
    for role, skills in ROLE_SKILLS.items()
}
def main(arguments: list[str] | None = None) -> int:
    """Codex 的 Shell 生成器只读取名称；所有激活与模式仍由原角色合同决定。"""
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 1 or arguments[0] not in ROLE_SKILLS:
        print("usage: role_skills.py ROLE", file=sys.stderr)
        return 2
    print("\n".join(ROLE_SKILLS[arguments[0]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
