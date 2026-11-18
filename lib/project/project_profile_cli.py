#!/usr/bin/env python3
"""渲染经过校验的项目画像与角色上下文，不写入宿主配置。"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from lib.project.validate_project_config import validate_with_profile
from lib.project.profile_context import render_context


def load(pack: Path, project: Path):
    """插件按项目实际选择适配器；源树直接调用沿用指定配置目录。"""
    from lib.task_sources import validate_task_source
    from lib.plugin_resources import plugin_root
    validate_task_source({}, root=project)
    installation = plugin_root()
    if installation is not None:
        from plugins.project_context import resolve_adapter
        if project.resolve() != Path.cwd() or pack.resolve() != installation:
            raise ValueError("画像项目与插件根须匹配当前 helper 调用")
        # 复用引导器已验证的同一项目快照，不再扫描一次或读取另一配置。
        _, _, profile = resolve_adapter()
        return profile
    result = validate_with_profile(pack / "project.yaml", project, pack / "roles")
    if result.errors or result.profile is None:
        for error in result.errors or ("ProjectProfile is missing",):
            print(f"[ERROR] {error}", file=sys.stderr)
        return None
    return result.profile


def render_preview(profile) -> str:
    lines = [
        "ProjectProfile preview",
        "roles: " + ", ".join(profile.enabled_roles),
    ]
    if not profile.modules:
        lines.append("modules: none")
    for module in profile.modules:
        lines.append(f"module {module.root} -> {module.primary_role}")
        lines.append(
            "  stack: " + (", ".join(module.stack_facts) or "none")
        )
        lines.append(
            "  evidence: " + (", ".join(module.evidence_paths) or "none")
        )
        if not module.verification_commands:
            lines.append("  command: none")
        for command in module.verification_commands:
            lines.append(
                "  command: "
                + json.dumps(list(command.argv), ensure_ascii=False)
                + f" purpose={command.purpose} evidence="
                + ",".join(command.evidence_paths)
            )
    for diagnostic in profile.diagnostics:
        lines.append(f"diagnostic: {diagnostic}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    role = None
    if len(arguments) == 4 and arguments[0] == "context":
        # context 与其他查询共用相同的包目录和项目根参数顺序。
        # 此入口只复用发现结果并渲染，不执行候选命令，也不刷新任何宿主产物。
        mode, pack_raw, project_raw, role = arguments
    elif len(arguments) == 3 and arguments[0] in {"preview", "roles", "json", "design-scaffold"}:
        mode, pack_raw, project_raw = arguments
    else:
        print(
            "usage: project_profile_cli.py preview|roles|json|design-scaffold PACK_DIR PROJECT_ROOT\n"
            "       project_profile_cli.py context PACK_DIR PROJECT_ROOT ROLE",
            file=sys.stderr,
        )
        return 2
    pack = Path(pack_raw)
    project = Path(project_raw)
    try:
        profile = load(pack, project)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[ERROR] cannot load ProjectProfile: {exc}", file=sys.stderr)
        return 1
    if profile is None:
        return 1
    if mode == "context":
        try:
            sys.stdout.write(render_context(profile, role))
        except ValueError as exc:
            print(f"[ERROR] cannot render ProjectProfile context: {exc}", file=sys.stderr)
            return 1
    elif mode == "preview":
        sys.stdout.write(render_preview(profile))
    elif mode == "roles":
        for role in profile.enabled_roles:
            print(role)
    elif mode == "design-scaffold":
        # 基础 UI 角色只表示可派发；聚合验收必须复用脚手架的实际需求判断。
        # 输出单个布尔值，避免为这项检查向 Agent 上下文返回完整模块和命令预览。
        print("1" if profile.design_scaffold_required else "0")
    else:
        payload = {
            "enabled_roles": list(profile.enabled_roles),
            "diagnostics": list(profile.diagnostics),
            "modules": [
                {
                    "root": module.root,
                    "primary_role": module.primary_role,
                    "stack_facts": list(module.stack_facts),
                    "evidence_paths": list(module.evidence_paths),
                    "verification_commands": [
                        {
                            "purpose": command.purpose,
                            "argv": list(command.argv),
                            "evidence_paths": list(command.evidence_paths),
                        }
                        for command in module.verification_commands
                    ],
                }
                for module in profile.modules
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
