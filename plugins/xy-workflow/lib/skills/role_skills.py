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

# 历史集合仅作为磁盘所有权证明，允许安装器在不覆盖未知用户内容的前提下替换资源。
# 它不是 2.0 运行合同；当前源、staging 和 --check 始终要求全部技能齐全，不能接受旧绑定。
LEGACY_CORE_SKILLS = frozenset({
    "grill-me", "xy-build-verify", "xy-project-memory", "xy-plan",
    "xy-prototype-verify", "xy-qa-review", "xy-workflow",
})
# 外部原版与内部受管Skill分开，历史集合只证明旧磁盘所有权。
CORE_SKILLS = (LEGACY_CORE_SKILLS - {"grill-me"}) | {"xy-code-standards", "xy-ui-design"}
COMMAND_IDENTITY = load_identity(Path(__file__).resolve().parents[2])
SELECTED_SKILL_ALIASES = {public: canonical for public, canonical in COMMAND_IDENTITY["skill_aliases"].items()
                          if canonical != "agent-config"}
SELECTED_SKILLS = frozenset(SELECTED_SKILL_ALIASES)


def selected_alias(canonical: str) -> str:
    """角色与构建器共用唯一产品声明的公开名称，不改上游canonical名称。"""
    return next(public for public, original in SELECTED_SKILL_ALIASES.items() if original == canonical)


PM_SKILLS = (selected_alias("grilling"),)

ROLE_SKILLS = {
    **{role: ("xy-code-standards", "xy-build-verify") for role in IMPLEMENTER_ROLES},
    "xy-web": ("xy-code-standards", "xy-build-verify", selected_alias("playwright-cli")),
    "xy-uiux": ("xy-ui-design", selected_alias("design-taste-frontend"), "xy-prototype-verify"),
    # QA 保持唯一审查入口，代码/UI 方法由实际审查面选择，不能无条件预载全文。
    "xy-qa": ("xy-qa-review",),
}
CLAUDE_ROLE_SKILLS = dict(ROLE_SKILLS)
ANTIGRAVITY_ROLE_SKILLS = {
    role: tuple(f"skills/{skill}" for skill in skills)
    for role, skills in ROLE_SKILLS.items()
}
LEGACY_ANTIGRAVITY_ROLE_SKILLS = {
    **{role: ("skills/xy-build-verify",) for role in IMPLEMENTER_ROLES},
    "xy-uiux": ("skills/xy-prototype-verify",),
    "xy-qa": ("skills/xy-qa-review",),
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
