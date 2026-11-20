#!/usr/bin/env python3
"""离线装配三个官方宿主插件；唯一源保持原样，输出确定性的 ZIP。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
# 构建入口先给出可行动的版本诊断，不能等tomllib等依赖抛出误导性导入异常。
if sys.version_info < (3, 11):
    raise SystemExit("Python >= 3.11 is required; use bash lib/python_runtime.sh -B -X utf8 packaging/build_plugin.py")
sys.path.insert(0, str(ROOT))
from lib.skills.business_confirmation_policy import (
    validate_business_confirmation_pack, validate_business_confirmation_texts,
)
from lib.skills.qa_review_policy import validate_pack_qa_review_policy
from lib.skills.role_skills import CORE_SKILLS, IMPLEMENTER_ROLES, ROLE_SKILLS
from lib.documents.prototype_review import LIVE_TOOL_ASSETS as PROTOTYPE_LIVE_TOOL_ASSETS, V4_TOOL_ASSETS as PROTOTYPE_V4_TOOL_ASSETS
from product.command_identity import load_identity
from product.release_channels import version_channel
from lib.skills.selected_skills import (
    DESKTOP_SKILL_ROOT, LOCK as SELECTED_LOCK, VENDOR as SELECTED_VENDOR,
    skill_path as selected_skill_path, snapshot as selected_snapshot,
)


# 宿主原生角色的工具白名单随构建器一同校验摘要，避免交付已退役安装器的实现。
IMPLEMENTER_TOOLS = (
    "view_file",
    "list_dir",
    "find_by_name",
    "grep_search",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "run_command",
    "manage_task",
)
UIUX_TOOLS = (
    "view_file",
    "list_dir",
    "find_by_name",
    "grep_search",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "run_command",
    "manage_task",
    "search_web",
    "read_url_content",
    "generate_image",
)
QA_TOOLS = (
    "view_file",
    "list_dir",
    "find_by_name",
    "grep_search",
    "run_command",
    "manage_task",
    "search_web",
    "read_url_content",
)
ANTIGRAVITY_ROLE_TOOLS = {
    **{role: IMPLEMENTER_TOOLS for role in IMPLEMENTER_ROLES},
    "xy-uiux": UIUX_TOOLS,
    "xy-qa": QA_TOOLS,
}

HOSTS = ("codex", "claude", "antigravity")
IDENTITY = load_identity(ROOT)
PLUGIN_NAME = IDENTITY["plugin_name"]
CONFIG_SKILL = next(name for name, original in IDENTITY["skill_aliases"].items() if original == "agent-config")
PREFERENCE_SOURCE = "native_config/preference_contract.py"
PREFERENCE_PROJECTION = "plugins/dispatch_preferences.py"
# Codex 候选放在宿主不会自动发现的资源目录；显式准备组件消费此索引后，
# 才能创建用户或项目的原生定义。插件清单不因此增加未文档化的 agents 字段。
CODEX_NATIVE_CONTEXT = "plugins/codex/native-agent-context.md"
CODEX_NATIVE_INDEX = "native-agent-templates/codex/index.json"
CODEX_PLUGIN_ROOT_PLACEHOLDER = "__XY_WORKFLOW_PLUGIN_ROOT__"
# 官方 CLI 1.5.5 的真实严格校验确认：技能正文最多加载 24,000 个 UTF-8
# 字节。构建阶段按同一正文边界拒绝超限，避免分发后才发现末尾流程被截断。
ANTIGRAVITY_SKILL_BODY_LIMIT = 24_000
# CLI 0.167.0 的真实插件读取仅在纯兼容清单形态发现 Hook；即使同时提供
# portable 根清单和兼容清单也会丢失 Hook。使用官方仍支持的单一兼容入口，
# 不同时写 root plugin.json，确保安装后的 review/trust 能列出当前定义。
MANIFESTS = {"codex": ".codex-plugin/plugin.json", "claude": ".claude-plugin/plugin.json",
             "antigravity": ".antigravity-plugin/plugin.json"}
# 原有 helper 的源包依赖显式列出。不给插件夹入中央管理器、TUI、旧安装器、
# Windows 启动器、原生配置业务本体或任何模型服务/MCP装配入口。
# 产品合同只发布当前工作流和身份解析需要的文件。旧 checkout 即使遗留独立的
# product/VERSION，或向 product/ 放入其他未登记文件，也不能污染插件的版本权威。
PRODUCT_FILES = (
    "PLUGIN_VERSION", "WORKFLOW.md", "GLOBAL_CONSTRAINTS.md", "AGENT_SCHEMA.md", "ROLES.yaml",
    "__init__.py", "command_identity.json", "command_identity.py", "release_channels.py",
)
LIB_FILES = (
    "__init__.py", "safe_text.py", "agent_continuation.py", "agent_continuation_cli.py", "platform_fs.py", "plugin_resources.py",
    "python_runtime.sh", "task_sources.py", "standard_paths.py", "task_graph.py", "request_scope.py", "solution_confirmation.py", "shared_solution_records.py", "writer_prerequisites.py", "visual_authority.py",
    "dispatch_admission.py", "dispatch_admission_cli.py", "task_settlement.py", "foundation_qa.py", "qa_projection.py",
    # 三个宿主共用同一任务池。原图、准入与更新入口也会读取撤回和改版合同，
    # 因此任务意图模块属于包内运行依赖，即使调用者继续使用旧 CLI 也必须随包交付。
    "task_pool.py", "task_pool_cli.py", "task_intent.py", "verification_inputs.py",
    "task_graph_cli.py", "task_graph_init.py", "task_graph_records.py",
    "validate_project_docs.py", "worktree_policy.py",
)
HOST_LIB_FILES = ("__init__.py", "capabilities.py", "antigravity_dispatch.py")
# 维护入口单独封闭白名单：既不遍历维护目录，也不读取独立产品源码或网页。
# 新的薄模块必须经显式审查后加入；Skill 不属于九个业务核心或角色预载列表。
MAINTENANCE_FILES = ("launcher.sh", "launcher.py", "component_store.py", "component.json")
# 新交付服务与历史离线包分别消费各自冻结白名单；发行载荷取有序并集，不能用
# live 名单回验或扩写旧 V4 包。仍不遍历 templates 整树，未知文件不会借目录入包。
# file 入口四项由 live 权威名单提供；这里只按稳定顺序去重并集，避免装配层复制第二份名单。
PROTOTYPE_TOOL_ASSETS = tuple(dict.fromkeys((*PROTOTYPE_V4_TOOL_ASSETS, *PROTOTYPE_LIVE_TOOL_ASSETS)))
# 架构模板随插件分发，供 PM 在项目确有结构变化时选用。项目初始化只消费适配器模板，
# 不应因模板进入载荷就向空项目写入架构页或尚不可访问的目录链接。
TEMPLATE_FILES = ("project.yaml.example", "docs/STANDARDS.md", "docs/PLAN.md", "docs/PROJECT.md", "docs/ARCHITECTURE.md",
                  "prototype/page.html", "prototype/prototype.css",
                  *("prototype/" + name for name in PROTOTYPE_TOOL_ASSETS))
MAINTENANCE_SKILL = "plugins/maintenance/skills/" + CONFIG_SKILL + "/SKILL.md"
MAINTENANCE_CODEX_POLICY = "plugins/maintenance/skills/" + CONFIG_SKILL + "/agents/openai.yaml"
MAINTENANCE_INVOCATIONS = {"codex": "$" + PLUGIN_NAME + ":" + CONFIG_SKILL,
                          "claude": "/" + PLUGIN_NAME + ":" + CONFIG_SKILL, "antigravity": "/" + CONFIG_SKILL}
MANIFEST_FIELDS = {
    "codex": {"name", "version", "description", "author", "skills", "hooks"},
    "claude": {"name", "version", "description", "author"},
    "antigravity": {"$schema", "name", "displayName", "version", "description", "author"},
}


def json_bytes(value: object) -> bytes:
    """固定编码、键顺序与末尾换行，不把路径、时间或机器身份写入归档。"""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def validate_preference_reader(body: bytes, identity_body: bytes | None = None) -> None:
    """偏好只读源只允许一个明确本地依赖，且该身份源码闭包本身必须仅用stdlib。

    不把允许product根等同于允许任意产品模块；不允许动态import绕开静态闭包。
    身份三文件原样进入两个产品，避免偏好投影各维护一份解析/常量。
    """
    for node in ast.walk(ast.parse(body, filename=PREFERENCE_SOURCE)):
        if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) and node.func.id == "__import__" or isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"):
            raise ValueError("dispatch preference reader must not use dynamic imports")
        if isinstance(node, ast.Import):
            modules = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValueError("dispatch preference reader must not use relative imports")
            if node.module == "product.command_identity" and [item.name for item in node.names] == ["load_identity"]:
                if identity_body is None:
                    raise ValueError("dispatch identity dependency must be supplied for closure validation")
                # 同一检查器在第二层不再提供本地依赖，确保身份模块不能继续引入本地树。
                validate_preference_reader(identity_body)
                continue
            modules = [node.module or ""]
        else:
            continue
        if any(module.split(".")[0] not in sys.stdlib_module_names for module in modules):
            raise ValueError("dispatch preference reader must use only the standard library")


def validate_manifest(host: str, manifest: dict, version: str) -> None:
    """对本产品实际使用的官方字段做封闭校验，不默默保留未文档化扩展。"""
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS[host]:
        raise ValueError("manifest contains missing or undocumented product fields")
    if manifest["name"] != PLUGIN_NAME or manifest["version"] != version:
        raise ValueError("manifest identity/version must match this plugin build")
    if not isinstance(manifest["description"], str) or not manifest["description"].strip():
        raise ValueError("manifest description must be a nonempty string")
    if manifest["author"] != {"name": "Agent Workflow"}:
        raise ValueError("manifest author must match the product publisher")
    if host == "codex":
        if manifest["skills"] != "./skills/" or manifest["hooks"] != "./hooks/hooks.json":
            raise ValueError("Codex compatibility manifest must declare the packaged skills and hooks")
    if host == "antigravity":
        if manifest["$schema"] != "https://antigravity.google/schemas/v1/plugin.json":
            raise ValueError("Antigravity manifest must declare its official schema")
        if manifest["displayName"] != "XY Workflow":
            raise ValueError("Antigravity display name must match the product")


def read_source(source: Path, relative: str) -> bytes:
    """所有来源都是普通文件；即便链接目标在包内也拒绝，防止构建依赖隐式树。"""
    path = source / relative
    for node in (path, *path.parents):
        if node == source:
            break
        if node.is_symlink():
            raise ValueError("source must not use symlinks: " + relative)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("source must be a regular file: " + relative)
    return path.read_bytes()


def tree_files(source: Path, relative: str) -> list[str]:
    """目录遍历只用于声明过的载荷根；缓存、编译产物从不进入候选。"""
    root = source / relative
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source tree must be a physical directory: " + relative)
    files = []
    for node in sorted(root.rglob("*")):
        name = node.relative_to(source).as_posix()
        if node.is_symlink():
            raise ValueError("source must not use symlinks: " + name)
        if "__pycache__" in node.parts or node.suffix in {".pyc", ".pyo"}:
            continue
        if node.is_file():
            files.append(name)
    return files


def split_frontmatter(body: bytes) -> tuple[bytes, bytes]:
    """只切开已有 YAML 边界，不解析或重写唯一源的正文。"""
    match = re.match(rb"\A---\r?\n.*?\r?\n---\r?\n", body, re.S)
    if match is None:
        raise ValueError("skill/role must have complete frontmatter")
    return body[:match.end()], body[match.end():]


def with_preamble(body: bytes, preamble: bytes) -> bytes:
    """保留原始前置元数据和正文的字节，仅在二者之间加入指定入口说明。"""
    header, original_body = split_frontmatter(body)
    return header + b"\n" + preamble + b"\n" + original_body


def render_skill(body: bytes, adapter_source: str, *, conversation_entry: bool = False) -> bytes:
    """独立发现的核心 Skill 也能从自身位置找到同包适配，不依赖主会话初始化。

    此处只写相对链接。由实际加载 Skill 的实例判断当前来源和内容是否完整，
    不跨实例共享已读状态，也不把开发机的绝对路径固化到可搬移的插件包中。
    """
    locator = (
        f"从本 Skill 的物理目录向上两级确定插件根。使用同包的[宿主资源说明](../../{adapter_source})。"
        "当前实例已具备同一物理来源、同一版本的完整说明时直接复用；"
        "独立启动或内容缺失时补读，来源或版本变化时重新读取。\n"
    )
    if conversation_entry:
        # 三端发现入口共用这个前缀。先区分无需读盘的对话，再说明资源解析的先后：
        # 如果把宿主说明和业务引用列为同批读取，来源尚未获准就会触发多个额外弹窗。
        # 只有缺失说明时才串行等它返回；同源同版本已完整载入时仍直接复用。
        locator = ("用户仅想讨论、澄清或归纳且对话材料已足够时，直接在对话中回答，"
                   "跳过以下资源定位步骤，无须读取项目、适配器或插件文件。"
                   "已委托的工作需要访问资源、且当前缺少宿主资源说明时，"
                   "第一批只读取下方链接的宿主资源说明，等它成功返回后再选当前阶段所需材料。"
                   "不要把产品全文、阶段引用或项目文件并入这次读取。"
                   "读取被拒时暂停依赖它的操作，不得换工具绕过。\n" + locator)
    return with_preamble(body, locator.encode("utf-8"))


def render_maintenance_route(body: bytes, host: str) -> bytes:
    """主会话和维护 Skill 使用同一宿主调用名及允许动作；重绑仅在 Codex 入口可选。"""
    actions = b"open|status|doctor|rebind" if host == "codex" else b"open|status|doctor"
    return (body.replace(b"@HOST@", host.encode("ascii"))
            .replace(b"@INVOCATION@", MAINTENANCE_INVOCATIONS[host].encode("ascii"))
            .replace(b"@MAINTENANCE_ACTIONS@", actions))


def render_main_context(body: bytes, host: str, envelope_source: str) -> bytes:
    """主会话适配仅提供分支，不将业务适配注入维护 Skill 或 Worker。

    host 和调用名称来自构建枚举而非用户输入；项目路径留给真实 session/workspace，
    不在构建时写入开发机 cwd、源码路径或默认项目。业务适配在业务分支中延迟读取。
    """
    if host == "antigravity":
        # AGY 始终加载 rules/AGENTS.md。明确只有配置维护依赖显式调用，
        # 否则宿主容易把通用开头理解成业务开发必须先由用户手动调用 Skill。
        body = body.replace(b"Use the host's actual Skill invocation event or a complete command",
                            b"For maintenance, require the host's actual Skill invocation event or a complete command")
        body = body.replace(b"**Delegated work.**", (
            "用户用自然语言要求实现、制作设计交付物或独立 QA 时，主会话即进入 xy-workflow。"
            "同一当前范围内的明确授权继续有效。依照既有 Light/Full 门禁，只就缺失的实质决定提问，"
            "无需用户再次要求启动工作流或派发。需要交接原件时，先通过本包 task_graph_cli.py scratch "
            "取得当前项目 .awf/agy-requests 下的 scratch_dir，用原生 write_file 写完整包，再用本包 task_pool_cli.py "
            "claim --register 领取；把实际包路径交给工作者原生 read_file。PM 按职责调用原生 invoke_subagent，"
            "将本次领取的 dispatch_marker 单独放入初始 Prompt，并用真实子会话回执完成绑定。"
            "回执缺失或被拒时，保留占用并报告阻塞；PM 不得接手该实例的工作或宣称独立 QA 通过。"
            "用户明确点名 PM 本人实施当前范围时沿用原有实施者例外；独立 QA 仍须真实 Reviewer。"
            "保留宿主权限、纯讨论和显式维护分支。"
        ).encode("utf-8"))
    return render_maintenance_route(body, host).replace(b"@BUSINESS_ADAPTER@", envelope_source.encode("ascii"))


def render_maintenance_skill(body: bytes, host: str) -> bytes:
    """只应用宿主支持的显式调用元数据，正文不叠加 workflow envelope。"""
    header, original_body = split_frontmatter(body)
    if host in {"claude", "antigravity"}:
        # 两宿主官方插件 Skill 均支持此 frontmatter；不添加 fork 或宽泛工具批准。
        header = header.removesuffix(b"---\n") + b"disable-model-invocation: true\n---\n"
    return render_maintenance_route(header + original_body, host)


def validate_maintenance_descriptor(source: Path) -> None:
    """复用薄组件的只读描述符校验；插件构建始终不导入 native_config。

    仅加载已经过 read_source 普通文件/软链检查的固定白名单模块。该模块只依赖
    标准库；descriptor 不创建目录、不下载、不安装，因此独立业务源码缺席仍可构建。
    """
    spec = importlib.util.spec_from_file_location("awf_build_component_store", source / "plugins/maintenance/component_store.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.descriptor(source / "plugins/maintenance/component.json")
    except module.ComponentError as error:
        raise ValueError("maintenance component descriptor is invalid: " + str(error)) from None


def validate_antigravity_skill_body(relative: str, body: bytes) -> None:
    """按原生加载口径去掉 frontmatter 与边界空白，校验实际 UTF-8 字节预算。"""
    _, loaded_body = split_frontmatter(body)
    size = len(loaded_body.strip())
    if size > ANTIGRAVITY_SKILL_BODY_LIMIT:
        raise ValueError(f"Antigravity skill body exceeds {ANTIGRAVITY_SKILL_BODY_LIMIT} bytes: "
                         f"{relative} ({size} bytes); the native host would truncate it")


def render_agent(role: str, body: bytes, envelope: bytes, host: str) -> bytes:
    """宿主仅转换 frontmatter；完整角色正文与统一资源适配原样组合，不另写流程。"""
    header, original_body = split_frontmatter(body)
    match = re.search(rb"(?m)^description: (.+)$", header)
    if match is None:
        raise ValueError("role is missing canonical description: " + role)
    description = match.group(1).decode("utf-8").strip()
    lines = ["---", "name: " + role, "description: " + json.dumps(description)]
    if host == "claude":
        # Skill工具保留按需调用外部专长与QA方法的能力；不开放Agent工具，避免
        # Worker获得嵌套派发入口。仅预载方法不等于其余必要Skill已可调用。
        tools = "Read, Glob, Grep, Bash, Skill" if role == "xy-qa" else "Read, Glob, Grep, Bash, Edit, Write, Skill"
        lines.append("tools: " + tools)
        # 使用官方插件命名空间引用既有技能；不内联第二份方法论。
        lines.append("skills:")
        lines.extend("  - " + PLUGIN_NAME + ":" + skill for skill in ROLE_SKILLS[role])
    else:
        lines.extend(("model: inherit", "mainAgent: false", "subagent: true", "inheritMcp: true",
                      "inheritCustomizations: true"))
        # 沿用原AGY适配器的角色工具合同，避免继承全工具后意外获得嵌套派发，
        # 也不能把QA必要的只读命令验证能力从静态资源中裁掉。
        lines.append("tools:")
        lines.extend("  - " + tool for tool in ANTIGRAVITY_ROLE_TOOLS[role])
        lines.append("skills:")
        lines.extend("  - skills/" + skill for skill in ROLE_SKILLS[role])
    return ("\n".join(lines) + "\n---\n\n").encode("utf-8") + envelope + b"\n" + original_body


def render_codex_native_template(role: str, body: bytes, constraints: bytes,
                                 context: bytes, metadata: bytes) -> tuple[str, bytes]:
    """机械投影完整规范角色与 Codex 边界，不引入第二份流程或宿主设置。

    原生定义离开插件目录后无法按自身父目录定位资源，因此正文只保留固定的
    物理插件根占位符；准备组件解析 TOML 后替换该字符串并重新安全序列化。
    JSON 字符串转义属于 TOML basic string 的兼容子集，正文中的引号、反斜杠、
    换行均作为数据编码，绝不拼接可执行 shell 或用 eval 生成定义。
    """
    header, _ = split_frontmatter(body)
    match = re.search(rb"(?m)^description: (.+)$", header)
    if match is None:
        raise ValueError("role is missing canonical description: " + role)
    description = match.group(1).decode("utf-8").strip()
    # 记录准备时的规范指纹，使原生定义后续发现源缺失或变化时明确失败；
    # 当前缓存中的另一安装版本即使名称相同，也不能替代原始来源。
    provenance = {"roles/" + role + ".md": digest(body),
                  "platforms/codex/WORKER_CONSTRAINTS.md": digest(constraints),
                  "product/ROLES.yaml": digest(metadata), CODEX_NATIVE_CONTEXT: digest(context)}
    instructions = (context.decode("utf-8") + "\n\n准备时规范来源摘要：\n"
                    + json.dumps(provenance, ensure_ascii=False, sort_keys=True) + "\n\n"
                    + constraints.decode("utf-8") + "\n\n" + body.decode("utf-8"))
    fields = {"name": role, "description": description, "developer_instructions": instructions}
    return description, ("\n".join(key + " = " + json.dumps(value, ensure_ascii=False)
                                   for key, value in fields.items()) + "\n").encode("utf-8")


def payload(source: Path, host: str) -> dict[str, bytes]:
    if host not in HOSTS:
        raise ValueError("unsupported plugin host")
    source = source.resolve(strict=True)
    version = read_source(source, "product/PLUGIN_VERSION").decode("ascii").strip()
    # 正式版与历史alpha的语法/渠道由两个产品共用的唯一纯合同验证。
    version_channel(version)
    errors = validate_business_confirmation_pack(source, host)
    errors.extend(validate_pack_qa_review_policy(source, host))
    if errors:
        raise ValueError("source workflow contract failed: " + "; ".join(errors))
    result: dict[str, bytes] = {}
    source_files: dict[str, str] = {
        "packaging/build_plugin.py": digest(read_source(source, "packaging/build_plugin.py")),
    }
    projections = {}

    def copy(relative: str, target: str | None = None) -> None:
        body = read_source(source, relative)
        result[target or relative] = body
        source_files[relative] = digest(body)

    # documents 是唯一核心载荷白名单根，包含 prototype_review 及其安全读取、
    # 依赖校验闭包；模板在下方按明确文件白名单同源装配，不在宿主间维护副本。
    for name in PRODUCT_FILES:
        copy("product/" + name)
    for folder in ("roles", "platforms/shared", "platforms/" + host,
                   "lib/documents", "lib/delivery", "lib/project", "lib/skills"):
        for relative in tree_files(source, folder):
            copy(relative)
    for relative in TEMPLATE_FILES:
        copy("templates/" + relative)
    for name in LIB_FILES:
        copy("lib/" + name)
    for name in HOST_LIB_FILES:
        copy("lib/hosts/" + name)
    for name in ("plugins/__init__.py", "plugins/source_pack.py", "plugins/project_context.py", "plugins/plugin-context.md"):
        copy(name)
    # 第三方依赖在非发现vendor区原样装配；统一锁先拒绝缺失/额外/篡改/链接。
    # 构建消费同一批已验证字节，不执行上游脚本、不联网，也不套内部Skill envelope。
    selected_lock, selected_files = selected_snapshot(source)
    copy(SELECTED_LOCK)
    for relative, body in selected_files.items():
        result[relative] = body
        source_files[relative] = digest(body)
    # 桌面 Skill 由宿主直接发现官方原版。各端共用同一份已校验的原文、相对引用及
    # LICENSE，不注入工作流 envelope。程序仍位于按架构区分的 vendor 目录，CLI
    # 可以按上游约定在自身旁边找到同版本 helper。
    desktop_vendor = SELECTED_VENDOR + "/agent-desktop/"
    desktop_body = selected_files[desktop_vendor + DESKTOP_SKILL_ROOT + "/SKILL.md"]
    header, _ = split_frontmatter(desktop_body)
    if not re.search(rb"(?m)^name: agent-desktop$", header) or re.search(rb"(?m)^(hooks|allowed-tools)[ \t]*:", header):
        raise ValueError("official agent-desktop must retain its name without permission/hook metadata")
    for relative, body in selected_files.items():
        if relative.startswith(desktop_vendor + DESKTOP_SKILL_ROOT + "/"):
            target = relative.removeprefix(desktop_vendor)
        elif relative == desktop_vendor + "LICENSE":
            target = DESKTOP_SKILL_ROOT + "/LICENSE"
        else:
            continue
        result[target] = body
        projections[target] = {"source": relative, "transform": "identity"}
    if host == "antigravity":
        validate_antigravity_skill_body(DESKTOP_SKILL_ROOT + "/SKILL.md", desktop_body)
    # 其余精选上游技能仍由现有 xy 别名薄适配公开；原名、正文和元数据保留在 vendor。
    adapters = tree_files(source, "plugins/selected-skills")
    public = set(IDENTITY["skill_aliases"]) - {CONFIG_SKILL}
    if {path.split("/")[2] for path in adapters} != public:
        raise ValueError("selected adapters must match the unique public identity")
    for adapter in adapters:
        copy(adapter)
        target = adapter.replace("plugins/selected-skills/", "skills/", 1)
        result[target] = result[adapter]
        projections[target] = {"source": adapter, "transform": "identity"}
        if target.endswith("/SKILL.md"):
            header, _ = split_frontmatter(result[adapter])
            name = target.split("/")[1]
            if not re.search(rb"(?m)^name: " + name.encode("ascii") + rb"$", header) or re.search(rb"(?m)^(hooks|allowed-tools):", header):
                raise ValueError("selected adapter must use its public name without permission/hook metadata")
            canonical = IDENTITY["skill_aliases"][name]
            if canonical in ("grill-me", "grilling"):
                # 两份短访谈原文直接随宿主 Skill 交付。只追加同一批锁校验过的完整字节，
                # 外层 frontmatter 始终来自适配；更新 vendor 后重新构建就能同步所有宿主。
                upstream = selected_skill_path(canonical)
                result[target] += b"\n" + selected_files[upstream]
                projections[target] = {"source": adapter, "transform": "append_locked_skill",
                                       "dependencies": {upstream: source_files[upstream]}}
        if host == "antigravity" and target.endswith("/SKILL.md"):
            validate_antigravity_skill_body(target, result[target])
    # 唯一允许进入工作流插件的独立配置来源：只读合同按字节原样投影，包内不建
    # native_config 目录，也不复制业务服务。双摘要显式说明来源与投影的同源关系。
    preference_reader = read_source(source, PREFERENCE_SOURCE)
    validate_preference_reader(preference_reader, read_source(source, "product/command_identity.py"))
    result[PREFERENCE_PROJECTION] = preference_reader
    source_files[PREFERENCE_SOURCE] = digest(preference_reader)
    projections[PREFERENCE_PROJECTION] = {
        "source": PREFERENCE_SOURCE, "transform": "identity",
        "source_sha256": digest(preference_reader),
        "projection_sha256": digest(result[PREFERENCE_PROJECTION]),
        "dependencies": {"product/command_identity.py": digest(result["product/command_identity.py"]),
                         "product/command_identity.json": digest(result["product/command_identity.json"]),
                         "product/__init__.py": digest(result["product/__init__.py"])},
    }
    copy("plugins/PLUGIN.md", "PLUGIN.md")
    copy("plugins/INSTALL.md", "INSTALL.md")
    result["README.md"] = result["PLUGIN.md"]
    # 完整适配仍随包交付给独立实例，原生角色也保留其权限边界。核心 Skill
    # 只引用本宿主的适配文件；通过来源记录可核对链接实际指向的包内字节。
    envelope_source = ("plugins/antigravity/plugin-context.md" if host == "antigravity"
                       else "plugins/plugin-context.md")
    if envelope_source not in result:
        copy(envelope_source)
    envelope = result[envelope_source]
    copy("plugins/main-session-context.md")
    main_context = render_main_context(result["plugins/main-session-context.md"], host, envelope_source)
    # 规范源保留原样用于摘要；只对主会话实际加载的投影应用固定宿主适配。
    result["main-session-context.md"] = main_context
    projections["main-session-context.md"] = {"source": "plugins/main-session-context.md",
                                               "transform": host + "-main-session-route-v1"}
    for name in MAINTENANCE_FILES:
        copy("plugins/maintenance/" + name)
    validate_maintenance_descriptor(source)
    copy(MAINTENANCE_SKILL)
    target = "skills/" + CONFIG_SKILL + "/SKILL.md"
    result[target] = render_maintenance_skill(result[MAINTENANCE_SKILL], host)
    projections[target] = {"source": MAINTENANCE_SKILL,
                           "transform": host + "-maintenance-explicit-v1"}
    if host == "antigravity":
        validate_antigravity_skill_body(target, result[target])
    if host == "codex":
        copy(MAINTENANCE_CODEX_POLICY, "skills/" + CONFIG_SKILL + "/agents/openai.yaml")
        projections["skills/" + CONFIG_SKILL + "/agents/openai.yaml"] = {
            "source": MAINTENANCE_CODEX_POLICY, "transform": "identity"}
    skills = sorted(CORE_SKILLS)
    for relative in sorted(result.copy()):
        if not relative.startswith("platforms/shared/skills/"):
            continue
        target = relative.removeprefix("platforms/shared/")
        if relative.endswith("/SKILL.md"):
            result[target] = render_skill(result[relative], envelope_source,
                                          conversation_entry=relative == "platforms/shared/skills/xy-workflow/SKILL.md")
            if host == "antigravity":
                validate_antigravity_skill_body(target, result[target])
            transform = "skill-plugin-locator-v1"
        else:
            result[target] = result[relative]
            transform = "identity"
        projections[target] = {"source": relative, "transform": transform}
        if transform != "identity":
            projections[target]["adapter"] = envelope_source
    for role in sorted(ROLE_SKILLS):
        if host == "codex":
            continue
        relative, target = "roles/" + role + ".md", "agents/" + role + ".md"
        result[target] = render_agent(role, result[relative], envelope, host)
        projections[target] = {"source": relative, "transform": host + "-agent-frontmatter-envelope-v1",
                               "adapter": envelope_source}
    if host == "codex":
        copy(CODEX_NATIVE_CONTEXT)
        entries = []
        dependencies = {name: digest(result[name]) for name in
                        ("product/ROLES.yaml", "platforms/codex/WORKER_CONSTRAINTS.md", CODEX_NATIVE_CONTEXT)}
        for role in sorted(ROLE_SKILLS):
            relative = "roles/" + role + ".md"
            target = "native-agent-templates/codex/" + role + ".toml"
            description, result[target] = render_codex_native_template(
                role, result[relative], result["platforms/codex/WORKER_CONSTRAINTS.md"],
                result[CODEX_NATIVE_CONTEXT], result["product/ROLES.yaml"])
            entries.append({"name": role, "description": description,
                            "path": target, "sha256": digest(result[target])})
            projections[target] = {"source": relative, "transform": "codex-native-template-v1",
                                   "adapter": CODEX_NATIVE_CONTEXT, "dependencies": dependencies,
                                   "source_sha256": digest(result[relative]),
                                   "projection_sha256": digest(result[target])}
        result[CODEX_NATIVE_INDEX] = json_bytes({"schema_version": 1, "product": PLUGIN_NAME,
                                                "host": "codex", "version": version, "templates": entries})
        projections[CODEX_NATIVE_INDEX] = {
            "source": "product/ROLES.yaml", "transform": "codex-native-template-index-v1",
            "source_sha256": digest(result["product/ROLES.yaml"]),
            "projection_sha256": digest(result[CODEX_NATIVE_INDEX]),
            "dependencies": {item["path"]: item["sha256"] for item in entries}}
    if host == "claude":
        copy("plugins/claude/pm.md")
        copy("plugins/claude/settings.json", "settings.json")
        result["agents/pm.md"] = with_preamble(result["plugins/claude/pm.md"], main_context)
        projections["agents/pm.md"] = {"source": "plugins/claude/pm.md", "transform": "main-session-entry-route-v1",
                                      "adapter": "plugins/main-session-context.md"}
        projections["settings.json"] = {"source": "plugins/claude/settings.json", "transform": "identity"}
    if host == "codex":
        # 官方兼容清单明确指向 hooks/hooks.json；只装配资源，不写任何 trust。
        # 安装后必须由宿主原生 review/trust 确认当前定义及脚本才允许运行。
        copy("plugins/codex/hooks/hooks.json", "hooks/hooks.json")
        copy("plugins/codex/hooks/session_start.py", "hooks/session_start.py")
        for name in ("hooks.json", "session_start.py"):
            projections["hooks/" + name] = {"source": "plugins/codex/hooks/" + name, "transform": "identity"}
    if host == "antigravity":
        # AGY CLI 从插件根的 hooks.json 发现处理器，并以插件根作为工作目录。
        # 保留原始来源和投影，使离线候选与本地安装源能校验实际执行的字节。
        for name, target in (("hooks.json", "hooks.json"), ("write_guard.py", "hooks/write_guard.py"),
                             ("guard_command.py", "hooks/guard_command.py")):
            source_name = "plugins/antigravity/" + name
            copy(source_name, target)
            projections[target] = {"source": source_name, "transform": "identity"}
        # AGY官方默认发现的always-on入口属于插件rules目录，不修改项目AGENTS。
        # 只给主会话已有Skill的入口；角色正文继续约束Worker，不能把它变成PM。
        result["rules/AGENTS.md"] = main_context
        projections["rules/AGENTS.md"] = {"source": "plugins/main-session-context.md",
                                           "transform": "antigravity-main-session-route-v1"}
    template = "plugins/" + host + "/plugin.json.in"
    manifest = json.loads(read_source(source, template).decode("utf-8").replace("@PLUGIN_VERSION@", version).replace("@PLUGIN_NAME@", PLUGIN_NAME))
    validate_manifest(host, manifest, version)
    source_files[template] = digest(read_source(source, template))
    result[MANIFESTS[host]] = json_bytes(manifest)
    # workflow-sources只列原样存在于包内的规范路径。模板和重命名手册留在外层
    # provenance，避免resolver把源仓专用路径误当作可读取的安装资源。
    files = {relative: expected for relative, expected in source_files.items()
             if relative in result and digest(result[relative]) == expected}
    result["workflow-sources.json"] = json_bytes({"schema_version": 1, "files": files})
    loaded_errors = validate_business_confirmation_texts(
        [(Path("product/WORKFLOW.md"), result["product/WORKFLOW.md"].decode("utf-8")),
         *( (Path("skills") / skill / "SKILL.md", result["skills/" + skill + "/SKILL.md"].decode("utf-8"))
            for skill in skills )])
    if loaded_errors:
        raise ValueError("loaded workflow contract failed: " + "; ".join(loaded_errors))
    result["sources.json"] = json_bytes({
        "schema_version": 1, "plugin_version": version, "plugin_name": PLUGIN_NAME, "host": host,
        "product": "workflow-core",
        "hook_trust_required": host == "codex",
        "source_files": source_files, "projections": projections,
        "payload_sha256": {name: digest(body) for name, body in result.items()},
        "validation": {"business_confirmation_policy": "passed", "execution_contract": "passed",
                       "single_qa_policy": "passed", "loaded_confirmation_policy": "passed",
                       "selected_skills_integrity": "passed"},
        "selected_dependencies": {name: {"repository": item["repository"], "commit": item["commit"],
                                         "lock": SELECTED_LOCK, "canonical_root": SELECTED_VENDOR + "/" + name}
                                  for name, item in selected_lock["dependencies"].items()},
        "runtime_verified": False,
        "pending_acceptance": ["native dispatch and independent context", "native model and effort application",
                               "in-flight task resource retention across host plugin updates"],
    })
    return result


def archive_modes(files: dict[str, bytes]) -> dict[str, int]:
    """唯一归档模式权威：返回含普通文件类型位的100644或100755。

    官方包的可执行资源从同一锁读取，锁所在前缀同时用于local-source投影；
    自有三个启动入口只在主包根为可执行，带前缀二次封装保持原有默认644语义。
    producer与publisher必须共用本函数，不能各自猜测扩展名或复制可执行白名单。
    """
    locked_modes = {}
    for name, body in files.items():
        if name == SELECTED_LOCK or name.endswith("/" + SELECTED_LOCK):
            prefix = name.removesuffix(SELECTED_LOCK)
            for dependency, item in json.loads(body)["dependencies"].items():
                for relative, record in item["files"].items():
                    mode = record.get("mode", 0o644)
                    # 即使调用者尚未完成完整锁校验，也不能让归档或发行比较放宽权限。
                    if type(mode) is not int or mode not in {0o644, 0o755}:
                        raise ValueError("archive file mode must be 644 or 755")
                    locked_modes[prefix + SELECTED_VENDOR + "/" + dependency + "/" + relative] = mode
    executable = {"plugins/source_pack.py", "lib/python_runtime.sh", "plugins/maintenance/launcher.sh"}
    return {name: stat.S_IFREG | locked_modes.get(name, 0o755 if name in executable else 0o644)
            for name in files}


def write_archive(files: dict[str, bytes], target: Path) -> None:
    """插件ZIP和市场源ZIP共用固定顺序、时间、权限与压缩参数。"""
    modes = archive_modes(files)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, body in sorted(files.items()):
            entry = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = modes[relative] << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, body, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    target.with_suffix(".zip.sha256").write_text(digest(target.read_bytes()) + "  " + target.name + "\n", encoding="ascii")


def build(source: Path, output: Path, host: str) -> Path:
    """内容变化才改变摘要；独立配置产品仅共享经闭包检查的唯一只读合同。"""
    files = payload(source, host)
    version = json.loads(files["sources.json"])["plugin_version"]
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{IDENTITY['artifact_prefix']}-{host}-{version}.zip"
    write_archive(files, target)
    return target


def unpack_archive(archive: Path, destination: Path) -> None:
    """将构建产物展开到调用方准备的目录，保留 ZIP 的 Unix 文件模式。"""
    # ZipFile.extractall 只写正文，不能保留上游 CLI/helper 的执行位。本地源和
    # 包外消费测试共用这一条解包路径，避免测试夹具把完整发行误装成不可执行版本。
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            relative = Path(entry.filename)
            if relative.is_absolute() or ".." in relative.parts or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("local source ZIP must contain only in-root regular resources")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(entry))
            target.chmod((entry.external_attr >> 16) & 0o777)


def local_source(archive: Path, output: Path, host: str) -> Path:
    """把已经构建的精确ZIP展开为官方本地source，不指向源码仓或未发布远端。

    只创建全新的载荷目录；重复目标明确拒绝，避免覆盖用户已经检查或修改的安装源。
    市场索引与插件实体同根分发，每个相对source都能离线解析到实际文件。
    """
    market = output / "local" / host
    market.mkdir(parents=True, exist_ok=False)
    plugin = market / (PLUGIN_NAME if host == "antigravity" else "plugins/" + PLUGIN_NAME)
    plugin.mkdir(parents=True)
    unpack_archive(archive, plugin)
    if host == "codex":
        manifest = {"name": IDENTITY["marketplaces"]["local"], "plugins": [{
            "name": PLUGIN_NAME, "source": {"source": "local", "path": "./plugins/" + PLUGIN_NAME},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity",
        }]}
        target = market / ".agents/plugins/marketplace.json"
    elif host == "claude":
        manifest = {"name": IDENTITY["marketplaces"]["local"], "owner": {"name": "Agent Workflow"},
                    "plugins": [{"name": PLUGIN_NAME, "source": "./plugins/" + PLUGIN_NAME}]}
        target = market / ".claude-plugin/marketplace.json"
    else:
        write_archive({path.relative_to(market).as_posix(): path.read_bytes()
                       for path in sorted(market.rglob("*")) if path.is_file()},
                      archive.with_name(archive.stem + "-local-source.zip"))
        return plugin
    target.parent.mkdir(parents=True)
    target.write_bytes(json_bytes(manifest))
    write_archive({path.relative_to(market).as_posix(): path.read_bytes()
                   for path in sorted(market.rglob("*")) if path.is_file()},
                  archive.with_name(archive.stem + "-local-source.zip"))
    return market


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--host", choices=(*HOSTS, "all"), default="all")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--local-source", action="store_true", help="同时输出完整官方本地市场/目录载荷；输出目录须为新候选")
    args = parser.parse_args()
    try:
        if args.local_source:
            # 创建前一次性检查所有目标，避免重复候选目录导致新ZIP与旧市场源混杂。
            for host in HOSTS if args.host == "all" else (args.host,):
                existing = args.output_dir / "local" / host
                if existing.exists() or existing.is_symlink():
                    raise ValueError("local source output already exists; use a new candidate directory")
        for host in HOSTS if args.host == "all" else (args.host,):
            archive = build(args.source, args.output_dir, host)
            print(archive)
            if args.local_source:
                print(local_source(archive, args.output_dir, host))
                print(archive.with_name(archive.stem + "-local-source.zip"))
    except (ValueError, OSError) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
