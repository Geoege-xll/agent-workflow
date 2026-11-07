"""三宿主共用的静态技能绑定；这里只描述资源，不改变任务或执行权限。"""

from __future__ import annotations

import sys


IMPLEMENTER_ROLES = frozenset({
    "xy-web", "xy-desktop", "xy-backend", "xy-apple", "xy-android",
})

# 历史集合仅作为磁盘所有权证明，允许安装器在不覆盖未知用户内容的前提下替换资源。
# 它不是 2.0 运行合同；当前源、staging 和 --check 始终要求全部技能齐全，不能接受旧绑定。
LEGACY_CORE_SKILLS = frozenset({
    "grill-me", "xy-build-verify", "xy-project-memory", "xy-plan",
    "xy-prototype-verify", "xy-qa-review", "xy-workflow",
})
CORE_SKILLS = LEGACY_CORE_SKILLS | {"xy-code-standards", "xy-ui-design"}

ROLE_SKILLS = {
    **{role: ("xy-code-standards", "xy-build-verify") for role in IMPLEMENTER_ROLES},
    "xy-uiux": ("xy-ui-design", "xy-prototype-verify"),
    # QA 保持唯一审查入口，代码/UI 方法由实际审查面选择，不能无条件预载全文。
    "xy-qa": ("xy-qa-review",),
}
CLAUDE_ROLE_SKILLS = {
    **ROLE_SKILLS,
    "xy-uiux": ("xy-ui-design", "ui-ux-pro-max", "xy-prototype-verify"),
}
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
