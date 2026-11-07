#!/usr/bin/env python3
"""Stable read-only ProjectProfile renderer shared by every host preflight."""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from lib.project.validate_project_config import validate_with_profile
from lib.project.profile_context import render_context


ROLE_LOCATIONS = {
    "codex": (".codex/agents", ".toml"),
    "claude": (".claude/agents", ".md"),
    "antigravity": (".agents/agents", ".md"),
}


def check_roles(profile, project: Path, host: str) -> int:
    """只读核对当前宿主的角色资源，不安装、派发或自动修改任何项目文件。

    使用现有的有界项目发现器得到当前所需角色，避免沿用克隆源码之前的名单。
    这里只证明资源存在且不是链接；内容、所有权及宿主配置由原 setup --check 验证。
    """
    directory, suffix = ROLE_LOCATIONS[host]
    root = project / directory
    # .codex/.claude/.agents 父目录也属于资源路径，不能经链接借用另一个项目的角色。
    linked_root = root.is_symlink() or root.parent.is_symlink()
    missing = [role for role in profile.enabled_roles
               if linked_root or not (root / f"{role}{suffix}").is_file()
               or (root / f"{role}{suffix}").is_symlink()]
    if missing:
        print(f"[ERROR] {host} missing role resources: {', '.join(missing)}", file=sys.stderr)
        print(f"Refresh with bash .agent-workflow/setup_{host}.sh, then --check.", file=sys.stderr)
        return 1
    print(f"[OK] {host} required role resources are present")
    return 0


def load(pack: Path, project: Path):
    # 薄桥传入的是项目适配器目录，不是核心目录；只要出现中央上下文就必须
    # 完整验证，不能因缺字段或伪造路径而退回宽松的源码包分支。
    central_keys = ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                    "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT")
    if any(key in os.environ for key in central_keys):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from lib import runtime_bridge
        from lib.central import runtime_project
        from lib import runtime_store
        from manager import runtime_service

        if not all(key in os.environ for key in central_keys):
            raise ValueError("中央画像缺少完整任务上下文")
        root = runtime_project.canonical_project(project)
        state = runtime_store.state_root(None)
        context = runtime_bridge.resolve_runtime(state, root)
        # 环境只作为一致性检查；核心、配置和项目身份均由机器记录及 pin 推导。
        if (pack.absolute() != context.config_path.parent
                or Path(os.environ["AGENT_WORKFLOW_CONFIG_PATH"]) != context.config_path
                or Path(os.environ["AGENT_WORKFLOW_CORE_ROOT"]) != context.core.root
                or Path(__file__).resolve() != context.core.root / "lib/project/project_profile_cli.py"):
            raise ValueError("中央画像路径与已验证项目或固定核心不一致")
        _, record = runtime_service.read_binding_record(state, root)
        if record is None or not record["enabled"]:
            raise ValueError("中央项目未启用")
        with runtime_project.Tree(root) as tree:
            conflicts, owned_links = runtime_service._ownership(tree, record, state, repair=False)
            if conflicts:
                raise ValueError("中央项目受管资源验证失败")
            config = tree.read(runtime_project.CONFIG)
            if config.kind != "file":
                raise ValueError("中央项目配置缺失")
            resources = runtime_project.Resources(context.core.root, runtime_project.json_bytes(context.runtime_binding),
                                                  context.core.label, context.core)
            _, profile, _ = runtime_project.configuration(resources, root, config, owned_links=owned_links)
            # 画像扫描期间若资源或配置被替换，不能继续使用先前批准的链接集合。
            conflicts_after, links_after = runtime_service._ownership(tree, record, state, repair=False)
            if conflicts_after or links_after != owned_links or tree.read(runtime_project.CONFIG) != config:
                raise ValueError("中央画像读取期间项目资源发生变化")
            return profile
    result = validate_with_profile(
        pack / "project.yaml", project, pack / "roles"
    )
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
    host = None
    role = None
    if len(arguments) == 4 and arguments[0] == "check-roles" and arguments[1] in ROLE_LOCATIONS:
        mode, host, pack_raw, project_raw = arguments
    elif len(arguments) == 4 and arguments[0] == "context":
        # 沿用普通查询的路径参数位置，兼容 Windows 现有的显式路径转换合同。
        # 此入口只复用发现结果并渲染，不执行候选命令，也不刷新任何宿主产物。
        mode, pack_raw, project_raw, role = arguments
    elif len(arguments) == 3 and arguments[0] in {"preview", "roles", "json", "design-scaffold"}:
        mode, pack_raw, project_raw = arguments
    else:
        print(
            "usage: project_profile_cli.py preview|roles|json|design-scaffold PACK_DIR PROJECT_ROOT\n"
            "       project_profile_cli.py context PACK_DIR PROJECT_ROOT ROLE\n"
            "       project_profile_cli.py check-roles codex|claude|antigravity PACK_DIR PROJECT_ROOT",
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
    if mode == "check-roles":
        return check_roles(profile, project, host)
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
