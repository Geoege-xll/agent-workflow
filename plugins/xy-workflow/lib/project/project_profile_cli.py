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


def check_roles(profile, project: Path, host: str, *, runtime_context=None) -> int:
    """只读核对当前宿主的角色资源，不安装、派发或自动修改任何项目文件。

    使用现有的有界项目发现器得到当前所需角色，避免沿用克隆源码之前的名单。
    这里只证明资源存在且不是链接；内容、所有权及宿主配置由原 setup --check 验证。
    """
    if runtime_context is not None or any(key in os.environ for key in CENTRAL_CONTEXT_KEYS):
        # 中央稀疏资源通过已验证画像+本机绑定+原生归属投影核对，不能要求
        # 每个角色都有同名local文件；旧固定core仍沿其原check逻辑正常拒绝稀疏。
        from lib.central.runtime_project import Tree
        from manager import native_agents, runtime_service
        # main沿用load刚验证的同一context；直接调用者则走同一桥校验，
        # 不能再次用默认state/HOME改变已验证项目所属的机器状态身份。
        context = runtime_context or _central_context(project / ".agent-workflow", project)
        state = context.state
        project = context.project_root
        _, record = runtime_service.read_binding_record(state, project)
        if not record or not record["enabled"] or host not in record["hosts"]:
            print(f"[ERROR] {host} is not enabled in the local project binding", file=sys.stderr)
            return 1
        sparse = []
        directory, suffix = ROLE_LOCATIONS[host]
        with Tree(project) as tree:
            conflicts, _ = runtime_service._ownership(tree, record, state, repair=False)
            if conflicts:
                raise ValueError("中央角色受管资源存在冲突")
            for role in profile.enabled_roles:
                path = f"{directory}/{role}{suffix}"
                node = tree.read(path)
                if node.kind == "missing":
                    sparse.append(role)
                elif path not in record["managed"] or record["managed"][path]["purpose"] != "role":
                    raise ValueError("项目同名角色缺少精确原生归属")
        if sparse:
            # 薄桥的state已有精确active/current原生根授权；宿主发现路径属于
            # 该授权，不能让调用进程的HOME/CODEX_HOME重新选择另一套全局资源。
            if native_agents.admission_issues(state, hosts=(host,)):
                raise ValueError("稀疏角色缺少当前状态目录的完整全局原生归属")
        print(f"[OK] {host} required roles match the validated profile and native ownership")
        return 0
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


CENTRAL_CONTEXT_KEYS = ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                        "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT")


def _central_context(pack: Path, project: Path):
    """只从完整薄桥上下文验证一次state/project/core，缺字段不回退HOME。"""
    if not any(key in os.environ for key in CENTRAL_CONTEXT_KEYS):
        return None
    from lib import runtime_bridge, runtime_store
    from lib.central import runtime_project
    if (not all(key in os.environ for key in CENTRAL_CONTEXT_KEYS)
            or not os.environ.get("AGENT_WORKFLOW_STATE_DIR")):
        raise ValueError("中央画像缺少完整任务上下文或显式状态目录")
    # 环境路径不是授权本身；显式state交给真实桥重验本机项目记录与任务pin。
    # 即便固定core的旧state_root(None)实现忽略环境，显式参数也不能落回HOME。
    state = runtime_store.state_root(os.environ["AGENT_WORKFLOW_STATE_DIR"])
    root = runtime_project.canonical_project(project)
    context = runtime_bridge.resolve_runtime(state, root)
    if (pack.absolute() != context.config_path.parent
            or Path(os.environ["AGENT_WORKFLOW_CONFIG_PATH"]) != context.config_path
            or Path(os.environ["AGENT_WORKFLOW_CORE_ROOT"]) != context.core.root
            or Path(__file__).resolve() != context.core.root / "lib/project/project_profile_cli.py"):
        raise ValueError("中央画像路径与已验证项目或固定核心不一致")
    return context


def load(pack: Path, project: Path):
    """保留公开profile返回合同；主入口另复用同一次加载取得的可信context。"""
    return _load_profile(pack, project)[0]


def _load_profile(pack: Path, project: Path):
    context = _central_context(pack, project)
    if context is not None:
        from lib.central import runtime_project
        from manager import runtime_service
        root, state = context.project_root, context.state
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
            return profile, context
    result = validate_with_profile(
        pack / "project.yaml", project, pack / "roles"
    )
    if result.errors or result.profile is None:
        for error in result.errors or ("ProjectProfile is missing",):
            print(f"[ERROR] {error}", file=sys.stderr)
        return None, None
    return result.profile, None


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
        profile, runtime_context = _load_profile(pack, project)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[ERROR] cannot load ProjectProfile: {exc}", file=sys.stderr)
        return 1
    if profile is None:
        return 1
    if mode == "check-roles":
        try:
            return check_roles(profile, project, host, runtime_context=runtime_context)
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"[ERROR] cannot check ProjectProfile roles: {exc}", file=sys.stderr)
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
