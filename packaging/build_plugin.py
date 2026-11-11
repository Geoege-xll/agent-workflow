#!/usr/bin/env python3
"""离线装配三个官方宿主插件；唯一源保持原样，输出确定性的 ZIP。"""

from __future__ import annotations

import argparse
import hashlib
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
from lib.skills.role_skills import CORE_SKILLS, ROLE_SKILLS
from lib.validate_antigravity_artifacts import ROLE_TOOLS as ANTIGRAVITY_ROLE_TOOLS


HOSTS = ("codex", "claude", "antigravity")
MANIFESTS = {"codex": "plugin.json", "claude": ".claude-plugin/plugin.json",
             "antigravity": ".antigravity-plugin/plugin.json"}
# 原有 helper 的源包依赖显式列出。不给插件夹入中央管理器、TUI、旧安装器、
# Windows 启动器、原生Agent配置产品或任何模型服务/MCP装配入口。
LIB_FILES = (
    "__init__.py", "agent_continuation.py", "agent_continuation_cli.py", "platform_fs.py", "plugin_resources.py", "role_models.py",
    "python_runtime.sh", "runtime_pins.py", "runtime_store.py", "standard_paths.py", "task_graph.py",
    "dispatch_admission.py", "dispatch_admission_cli.py", "task_settlement.py",
    "task_graph_cli.py", "task_graph_init.py", "task_graph_records.py",
    "validate_project_docs.py", "worktree_policy.py",
)
HOST_LIB_FILES = ("__init__.py", "claude_instructions.py", "claude_options.py",
                  "workflow_hook_settings.py")
VERSION_RE = re.compile(r"3\.0\.0-alpha\.[1-9][0-9]*\Z")
MANIFEST_FIELDS = {
    "codex": {"$schema", "name", "version", "description", "author", "extensions"},
    "claude": {"name", "version", "description", "author"},
    "antigravity": {"$schema", "name", "displayName", "version", "description", "author"},
}


def json_bytes(value: object) -> bytes:
    """固定编码、键顺序与末尾换行，不把路径、时间或机器身份写入归档。"""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def validate_manifest(host: str, manifest: dict, version: str) -> None:
    """对本产品实际使用的官方字段做封闭校验，不默默保留未文档化扩展。"""
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS[host]:
        raise ValueError("manifest contains missing or undocumented product fields")
    if manifest["name"] != "agent-workflow" or manifest["version"] != version:
        raise ValueError("manifest identity/version must match this plugin build")
    if not isinstance(manifest["description"], str) or not manifest["description"].strip():
        raise ValueError("manifest description must be a nonempty string")
    if manifest["author"] != {"name": "Agent Workflow"}:
        raise ValueError("manifest author must match the product publisher")
    if host == "codex":
        if manifest["$schema"] != "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json":
            raise ValueError("Codex manifest must declare the portable Agent Plugins schema")
        if manifest["extensions"] != {"com.openai": {"requires_local_executor": True, "hooks": "./hooks/hooks.json"}}:
            raise ValueError("Codex manifest must declare only the documented local executor extension")
    if host == "antigravity":
        if manifest["$schema"] != "https://antigravity.google/schemas/v1/plugin.json":
            raise ValueError("Antigravity manifest must declare its official schema")
        if manifest["displayName"] != "Agent Workflow":
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


def render_skill(body: bytes, envelope: bytes) -> bytes:
    header, original_body = split_frontmatter(body)
    return header + b"\n" + envelope + b"\n" + original_body


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
        lines.extend("  - agent-workflow:" + skill for skill in ROLE_SKILLS[role])
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


def payload(source: Path, host: str) -> dict[str, bytes]:
    if host not in HOSTS:
        raise ValueError("unsupported plugin host")
    source = source.resolve(strict=True)
    version = read_source(source, "product/PLUGIN_VERSION").decode("ascii").strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError("PLUGIN_VERSION must be an explicit 3.0.0-alpha.N version")
    errors = validate_business_confirmation_pack(source, host)
    errors.extend(validate_pack_qa_review_policy(source))
    if errors:
        raise ValueError("source workflow contract failed: " + "; ".join(errors))
    result: dict[str, bytes] = {}
    source_files: dict[str, str] = {
        "packaging/build_plugin.py": digest(read_source(source, "packaging/build_plugin.py")),
        "lib/validate_antigravity_artifacts.py": digest(read_source(source, "lib/validate_antigravity_artifacts.py")),
    }
    projections = {}

    def copy(relative: str, target: str | None = None) -> None:
        body = read_source(source, relative)
        result[target or relative] = body
        source_files[relative] = digest(body)

    for folder in ("product", "roles", "platforms/shared", "platforms/" + host,
                   "templates", "lib/documents", "lib/delivery", "lib/project", "lib/skills",
                   "lib/vendor/answer-me-with-html"):
        for relative in tree_files(source, folder):
            copy(relative)
    for name in LIB_FILES:
        copy("lib/" + name)
    for name in HOST_LIB_FILES:
        copy("lib/hosts/" + name)
    for name in ("plugins/__init__.py", "plugins/source_pack.py", "plugins/project_context.py", "plugins/plugin-context.md"):
        copy(name)
    copy("plugins/PLUGIN.md", "PLUGIN.md")
    copy("plugins/INSTALL.md", "INSTALL.md")
    result["README.md"] = result["PLUGIN.md"]
    envelope = result["plugins/plugin-context.md"]
    skills = sorted(CORE_SKILLS)
    for relative in sorted(result.copy()):
        if not relative.startswith("platforms/shared/skills/"):
            continue
        target = relative.removeprefix("platforms/shared/")
        if relative.endswith("/SKILL.md"):
            result[target] = render_skill(result[relative], envelope)
            transform = "skill-plugin-envelope-v1"
        else:
            result[target] = result[relative]
            transform = "identity"
        projections[target] = {"source": relative, "transform": transform}
    for role in sorted(ROLE_SKILLS):
        if host == "codex":
            continue
        relative, target = "roles/" + role + ".md", "agents/" + role + ".md"
        result[target] = render_agent(role, result[relative], envelope, host)
        projections[target] = {"source": relative, "transform": host + "-agent-frontmatter-envelope-v1"}
    if host == "claude":
        copy("plugins/claude/pm.md")
        copy("plugins/claude/settings.json", "settings.json")
        result["agents/pm.md"] = render_skill(result["plugins/claude/pm.md"], envelope)
        projections["agents/pm.md"] = {"source": "plugins/claude/pm.md", "transform": "main-session-entry-envelope-v1"}
        projections["settings.json"] = {"source": "plugins/claude/settings.json", "transform": "identity"}
    if host == "codex":
        # 官方扩展明确指向hooks/hooks.json；本包不写trust，宿主必须先完成原生信任。
        copy("plugins/codex/hooks/hooks.json", "hooks/hooks.json")
        copy("plugins/codex/hooks/session_start.py", "hooks/session_start.py")
        for name in ("hooks.json", "session_start.py"):
            projections["hooks/" + name] = {"source": "plugins/codex/hooks/" + name, "transform": "identity"}
    if host == "antigravity":
        # AGY官方默认发现的always-on入口属于插件rules目录，不修改项目AGENTS。
        # 只给主会话已有Skill的入口；角色正文继续约束Worker，不能把它变成PM。
        result["rules/AGENTS.md"] = (
            b"# Agent Workflow main-session entry\n\n"
            b"At main-session task intake, apply the packaged skills/xy-workflow/SKILL.md "
            b"and its unchanged product authority. The main session remains PM; worker "
            b"roles execute only their current fresh task pack.\n\n" + envelope)
    template = "plugins/" + host + "/plugin.json.in"
    manifest = json.loads(read_source(source, template).decode("utf-8").replace("@PLUGIN_VERSION@", version))
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
        "schema_version": 1, "plugin_version": version, "host": host,
        "product": "workflow-core",
        "hook_trust_required": host == "codex",
        "source_files": source_files, "projections": projections,
        "payload_sha256": {name: digest(body) for name, body in result.items()},
        "validation": {"business_confirmation_policy": "passed", "execution_contract": "passed",
                       "single_qa_policy": "passed", "loaded_confirmation_policy": "passed"},
        "runtime_verified": False,
        "pending_acceptance": ["native dispatch and independent context", "native model and effort application",
                               "in-flight task resource retention across host plugin updates"],
    })
    return result


def write_archive(files: dict[str, bytes], target: Path) -> None:
    """插件ZIP和市场源ZIP共用固定顺序、时间、权限与压缩参数。"""
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, body in sorted(files.items()):
            entry = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            executable = relative in {"plugins/source_pack.py", "lib/python_runtime.sh"}
            entry.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, body, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    target.with_suffix(".zip.sha256").write_text(digest(target.read_bytes()) + "  " + target.name + "\n", encoding="ascii")


def build(source: Path, output: Path, host: str) -> Path:
    """内容变化才改变归档摘要；工作流交付不读取独立配置产品的任何源目录。"""
    files = payload(source, host)
    version = json.loads(files["sources.json"])["plugin_version"]
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"agent-workflow-{host}-{version}.zip"
    write_archive(files, target)
    return target


def local_source(archive: Path, output: Path, host: str) -> Path:
    """把已经构建的精确ZIP展开为官方本地source，不指向源码仓或未发布远端。

    只创建全新的载荷目录；重复目标明确拒绝，避免覆盖用户已经检查或修改的安装源。
    市场索引与插件实体同根分发，每个相对source都能离线解析到实际文件。
    """
    market = output / "local" / host
    market.mkdir(parents=True, exist_ok=False)
    plugin = market / ("agent-workflow" if host == "antigravity" else "plugins/agent-workflow")
    plugin.mkdir(parents=True)
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            relative = Path(entry.filename)
            if relative.is_absolute() or ".." in relative.parts or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("local source ZIP must contain only in-root regular resources")
            target = plugin / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(entry))
            target.chmod((entry.external_attr >> 16) & 0o777)
    if host == "codex":
        manifest = {"name": "agent-workflow-local", "plugins": [{
            "name": "agent-workflow", "source": {"source": "local", "path": "./plugins/agent-workflow"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity",
        }]}
        target = market / ".agents/plugins/marketplace.json"
    elif host == "claude":
        manifest = {"name": "agent-workflow-local", "owner": {"name": "Agent Workflow"},
                    "plugins": [{"name": "agent-workflow", "source": "./plugins/agent-workflow"}]}
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
