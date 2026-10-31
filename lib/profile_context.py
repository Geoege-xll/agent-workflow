"""把现有项目发现事实无损压缩为 Codex 角色使用的只读上下文。"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
import shlex
import unicodedata

if __package__:
    from .project_discovery import ModuleProfile, ProjectProfile, UI_ROLES
else:
    from project_discovery import ModuleProfile, ProjectProfile, UI_ROLES


def _json(value: object) -> str:
    """保留中文可读性，同时阻止仓库字符串插入控制行或双向显示指令。

    JSON 已转义引号、反斜杠和 C0 控制符；这里补齐 C1、格式控制符、孤立代理项
    及 Unicode 行分隔符。反引号也编码为 JSON 转义，使整组数据可安全放入单个
    Markdown 代码跨度，仓库值不能闭合代码跨度并变成指令或 HTML。
    """
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    result = []
    for character in encoded:
        if unicodedata.category(character).startswith("C") or character in "`\u2028\u2029":
            codepoint = ord(character)
            if codepoint <= 0xFFFF:
                result.append(f"\\u{codepoint:04x}")
            else:
                # JSON 的非 BMP 转义由一对 UTF-16 代理项组成，不能输出无效的六位 \u。
                codepoint -= 0x10000
                result.append(f"\\u{0xD800 + (codepoint >> 10):04x}\\u{0xDC00 + (codepoint & 0x3FF):04x}")
        else:
            result.append(character)
    return "".join(result)


def _root_label(root: str) -> str:
    """模块标签使用 JSON 字符串内容，避免反引号或空白破坏 Markdown 行边界。"""
    body = _json(root)[1:-1].replace(" ", "\\u0020")
    return f"`{body}`"


def _evidence(paths: tuple[str, ...], root: str) -> list[list[str]]:
    """仅把模块内部证据改为相对后缀，模块外证据始终保留项目相对路径。

    显式基点使同名 pom.xml 可共享模板，而根目录包装器、跨模块配置等不同证据
    不会被误当作当前模块的文件；不使用字符串替换或可越界的 ../ 模板。
    """
    module_root = PurePosixPath(root)
    references = []
    for path in paths:
        evidence = PurePosixPath(path)
        if evidence.is_relative_to(module_root):
            references.append(["module", evidence.relative_to(module_root).as_posix()])
        else:
            references.append(["project", path])
    return references


def _grouped_context(modules: tuple[ModuleProfile, ...]) -> str:
    """重复模块共享完整模板；模块专属 cwd 与路径基点仍在引用时分别展开。

    组编号按已排序模块的首次出现顺序生成。同一组必须具有完全相同的角色、栈、
    证据模板或完整命令序列；argv 参数顺序、purpose 和证据基点均参与去重。
    """
    lines = [
        "F=fact templates; V=command templates. Module rows give root, F, V.",
        "Root labels contain JSON string contents without quotes; group values are JSON. "
        "Evidence [\"module\",p] resolves under that module root, [\"project\",p] under "
        "the project root; command cwd is the module root.",
        "run encodes argv with POSIX shell quoting (shlex.split reverses it). Commands are "
        "candidates. Empty V means none discovered; do not invent a command.",
    ]
    facts: dict[str, str] = {}
    commands: dict[str, str] = {}
    module_lines = []
    for module in modules:
        fact = _json({
            "primary_role": module.primary_role,
            "stack": list(module.stack_facts),
            "evidence": _evidence(module.evidence_paths, module.root),
        })
        command = _json([
            {
                "purpose": item.purpose,
                "run": shlex.join(item.argv),
                "evidence": _evidence(item.evidence_paths, module.root),
            }
            for item in module.verification_commands
        ])
        if fact not in facts:
            facts[fact] = f"F{len(facts) + 1}"
        if command not in commands:
            commands[command] = f"V{len(commands) + 1}"
        module_lines.append(f"- Module {_root_label(module.root)} {facts[fact]} {commands[command]}")
    lines.extend(f"- {identifier} `{value}`" for value, identifier in facts.items())
    lines.extend(f"- {identifier} `{value}`" for value, identifier in commands.items())
    lines.extend(module_lines)
    return "\n".join(lines) + "\n"


def _flat_context(modules: tuple[ModuleProfile, ...]) -> str:
    """小角色使用逐模块记录，避免不重复的事实承担全局分组说明成本。

    证据表先放模块证据，再按命令原顺序追加尚未出现的命令证据；前 n 项因此能
    完整恢复模块证据，命令索引保留自己的证据顺序。模块外路径显式标记项目基点，
    不能因名称相同或 cwd 不同而借用另一个模块的证据。
    """
    lines = [
        "Flat=[role,stack,paths,n,[purpose,indexes,POSIX-quoted argv[]][]]; "
        "evidence=paths[:n]; paths/cwd=root."
    ]
    # 普通路径无需承担特殊情况的说明成本；特殊情况出现时仍完整声明还原规则。
    if any(_root_label(module.root)[1:-1] != module.root for module in modules):
        lines.append("Root labels use JSON string escapes.")
    if any(not module.verification_commands for module in modules):
        lines.append("Empty commands: none discovered; do not invent a command.")
    external_paths = False
    for module in modules:
        paths = list(dict.fromkeys((
            *module.evidence_paths,
            *(path for command in module.verification_commands for path in command.evidence_paths),
        )))
        indexes = {path: index for index, path in enumerate(paths)}
        references = [
            path if base == "module" else "/" + path
            for base, path in _evidence(tuple(paths), module.root)
        ]
        external_paths = external_paths or any(path.startswith("/") for path in references)
        commands = []
        for command in module.verification_commands:
            evidence = [indexes[path] for path in command.evidence_paths]
            # 只合并相邻且 purpose/证据索引相同的命令，保持原始命令序列和差异映射；
            # 每个 run 仍是一条独立候选，不能把分组合并当作跨 cwd 执行或聚合命令。
            if commands and commands[-1][:2] == [command.purpose, evidence]:
                commands[-1][2].append(shlex.join(command.argv))
            else:
                commands.append([command.purpose, evidence, [shlex.join(command.argv)]])
        row = [module.primary_role, list(module.stack_facts), references,
               len(module.evidence_paths), commands]
        lines.append(f"- Module {_root_label(module.root)} `{_json(row)}`")
    if external_paths:
        # 正规项目相对路径不会以 / 开头；这里的前缀是基点标记，绝不是磁盘绝对路径。
        lines.insert(1, "Leading / in paths means project-relative.")
    return "\n".join(lines) + "\n"


def render_context(profile: ProjectProfile, role: str) -> str:
    """保持原角色可见范围，在两种完整、安全的表达中确定性选择字符较少者。

    两种表达都保留完整命令证据；不能把未输出命令证据的旧渲染当成无损后备。
    长度相同时固定选 flat，不依赖运行环境、集合遍历或持久化缓存做决策。
    """
    if role not in profile.enabled_roles:
        raise ValueError(f"role is not enabled in ProjectProfile: {role}")
    modules = tuple(
        module for module in profile.modules
        if module.primary_role == role
        or role == "xy-qa"
        or role == "xy-uiux" and module.primary_role in UI_ROLES
    )
    lines = [
        "## Discovered project context",
        "",
        "Exact owned_paths govern writes; commands are candidates",
    ]
    if not modules:
        lines.append("- No implementation module is assigned to this supporting role.")
        return "\n".join(lines) + "\n"
    return "\n".join(lines) + "\n" + min(
        (_flat_context(modules), _grouped_context(modules)), key=len
    )
