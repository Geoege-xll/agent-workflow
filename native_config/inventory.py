"""发现真实原生定义并保留来源身份；磁盘清单不是当前会话加载收据。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import stat

from . import codecs, storage
from .contracts import (ConfigError, MAX_AGENTS, MAX_INVENTORY_BYTES, absolute_path,
                        host_name, json_bytes, unique_json)


@dataclass
class Agent:
    id: str
    host: str
    origin: str
    source_id: str
    path: Path
    relative: str
    document: codecs.AgentDocument
    snapshot: storage.Snapshot
    scope: str
    rank: int
    plugin: str | None = None
    enabled: bool | None = True
    invoke_name: str = ""
    definition_status: str = "candidate"
    shadowed_by: str | None = None
    invoke_name_verified: bool = True


@dataclass
class Inventory:
    host: str
    agents: list[Agent] = field(default_factory=list)
    snapshots: dict[Path, storage.Snapshot] = field(default_factory=dict)
    directories: list = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    total_bytes: int = 0
    visited: int = 0
    complete: bool = True

    def diagnostic(self, code, source=None):
        if code in {"unsafe_or_unreadable_directory", "symlink_rejected", "unsupported_format", "invalid_request",
                    "unsupported_claude_install_registry", "invalid_or_unsafe_plugin_install",
                    "external_discovery_manifest_not_supported", "discovery_depth_limit",
                    "invalid_or_unsafe_json_source", "invalid_ady_plugin_manifest",
                    "unsupported_plugin_enablement", "unsupported_claude_install_record"}:
            self.complete = False
        self.diagnostics.append({"code": code, "source": str(source) if source else None,
                                 "runtime_verified": False})

    def read(self, path: Path) -> storage.Snapshot:
        if path in self.snapshots:
            return self.snapshots[path]
        node = storage.read(path)
        self.total_bytes += len(node.body or b"")
        if self.total_bytes > MAX_INVENTORY_BYTES:
            raise ConfigError("原生清单总容量超过限制")
        self.snapshots[path] = node
        return node

    def revision(self) -> str:
        material = {"files": [(str(path), node.revision()) for path, node in sorted(self.snapshots.items(), key=lambda item: str(item[0]))],
                    "directories": self.directories,
                    "agents": [(agent.id, agent.definition_status, agent.enabled) for agent in self.agents],
                    "diagnostics": self.diagnostics}
        return hashlib.sha256(json_bytes(material, limit=MAX_INVENTORY_BYTES)).hexdigest()


def project_roots(project: Path | None) -> list[Path]:
    """按官方仓库边界查当前目录到根；未找到 Git 标记时只使用明确项目目录。"""
    if project is None:
        return []
    storage.project_identity(project)
    root = project
    for _ in range(64):
        with storage.directory(root) as handle:
            try:
                info = os.stat(".git", dir_fd=handle.fd, follow_symlinks=False)
            except FileNotFoundError:
                info = None
        if info is not None and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            result, cursor = [], project
            while True:
                result.append(cursor)
                if cursor == root:
                    return result
                cursor = cursor.parent
        if root == root.parent:
            break
        root = root.parent
    return [project]


def _entries(inventory: Inventory, root: Path):
    try:
        with storage.directory(root) as handle:
            info = os.fstat(handle.fd)
            with os.scandir(handle.fd) as stream:
                entries = []
                for entry in stream:
                    if re.fullmatch(r"\.native-config-[0-9a-f]{32}\.(?:new|backup|hold)", entry.name):
                        continue
                    inventory.visited += 1
                    if inventory.visited > MAX_AGENTS * 8:
                        raise ConfigError("原生发现总条目超过限制")
                    if len(entries) >= MAX_AGENTS * 4:
                        raise ConfigError("发现目录条目超过限制")
                    entries.append((entry.name, entry.stat(follow_symlinks=False).st_mode))
            entries.sort()
            inventory.directories.append((str(root), info.st_dev, info.st_ino, entries))
            return entries
    except FileNotFoundError:
        inventory.directories.append((str(root), None))
        return []
    except (OSError, ValueError):
        inventory.diagnostic("unsafe_or_unreadable_directory", root)
        return []


def _files(inventory: Inventory, root: Path, *, style: str, depth=0):
    """Claude 递归；AGY 只支持 <name>.md 和 <name>/agent.md；Codex 仅平面 TOML。"""
    if depth > 16:
        inventory.diagnostic("discovery_depth_limit", root)
        return
    for name, mode in _entries(inventory, root):
        path = root / name
        if stat.S_ISLNK(mode):
            inventory.diagnostic("symlink_rejected", path)
        elif stat.S_ISREG(mode):
            if (style == "codex" and name.endswith(".toml")) or (style != "codex" and name.endswith(".md")):
                if style != "antigravity" or depth == 0 or name == "agent.md":
                    yield path
        elif stat.S_ISDIR(mode):
            if style == "claude" or (style == "antigravity" and depth == 0):
                yield from _files(inventory, path, style=style, depth=depth + 1)


def _add(inventory, root, path, *, origin, scope, source_id, rank, plugin=None, enabled=True, logical=None, invoke_verified=True):
    if len(inventory.agents) >= MAX_AGENTS:
        raise ConfigError("原生 Agent 数量超过限制")
    try:
        node = inventory.read(path)
        if node.body is None:
            inventory.diagnostic("agent_missing", path)
            return
        document = codecs.parse(inventory.host, node.body)
        relative = path.relative_to(root).as_posix()
        material = [inventory.host, origin, source_id, relative, document.name]
        opaque = hashlib.sha256(json_bytes(material)).hexdigest()
        invoke_name = document.name
        if plugin and inventory.host == "claude":
            invoke_name = plugin + ":" + (logical or relative).removesuffix(".md").replace("/", ":")
        inventory.agents.append(Agent("agent_" + opaque, inventory.host, origin, source_id, path, relative,
                                      document, node, scope, rank, plugin, enabled, invoke_name,
                                      invoke_name_verified=invoke_verified))
    except (OSError, ValueError) as exc:
        inventory.diagnostic(getattr(exc, "code", "invalid_agent"), path)


def _json(inventory, path):
    try:
        node = inventory.read(path)
        return {} if node.body is None else unique_json(node.body)
    except (OSError, ValueError):
        inventory.diagnostic("invalid_or_unsafe_json_source", path)
        return None


def _relative(root: Path, raw) -> Path:
    if not isinstance(raw, str) or not raw or len(raw) > 4096 or "\\" in raw:
        raise ConfigError("插件资源路径无效")
    value = raw[2:] if raw.startswith("./") else raw
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or Path(value).is_absolute():
        raise ConfigError("插件资源必须是根内相对路径")
    return root.joinpath(*parts)


def _claude_plugins(inventory, directory, roots):
    registry = _json(inventory, directory / "plugins/installed_plugins.json")
    if registry == {} and inventory.snapshots.get(directory / "plugins/installed_plugins.json", storage.Snapshot()).body is None:
        return
    if (not isinstance(registry, dict) or type(registry.get("version")) is not int
            or registry.get("version") != 2 or not isinstance(registry.get("plugins"), dict)):
        inventory.diagnostic("unsupported_claude_install_registry", directory / "plugins/installed_plugins.json")
        return
    inventory.diagnostic("claude_registry_schema_is_observed_not_public_stable_contract")
    enabled = {}
    paths = [directory / "settings.json"]
    for root in reversed(roots):
        paths.extend((root / ".claude/settings.json", root / ".claude/settings.local.json"))
    for path in paths:
        setting = _json(inventory, path)
        if setting is None or not isinstance(setting, dict):
            inventory.diagnostic("unsupported_plugin_enablement", path)
            enabled = {name: None for name in enabled}
            continue
        mapping = setting.get("enabledPlugins", {})
        if not isinstance(mapping, dict) or any(type(value) is not bool for value in mapping.values()):
            inventory.diagnostic("unsupported_plugin_enablement", path)
            if not isinstance(mapping, dict):
                enabled = {name: None for name in enabled}
            else:
                # 高优先级的未知值必须覆盖低层的确定值，不能静默回落到 true。
                enabled.update({name: value if type(value) is bool else None for name, value in mapping.items()})
        else:
            enabled.update(mapping)
    if len(registry["plugins"]) > MAX_AGENTS:
        raise ConfigError("插件安装清单超过数量限制")
    for plugin_id, installs in sorted(registry["plugins"].items()):
        if (not isinstance(plugin_id, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}(?:@[A-Za-z0-9][A-Za-z0-9_.-]{0,127})?", plugin_id)
                or not isinstance(installs, list) or len(installs) > MAX_AGENTS):
            inventory.diagnostic("unsupported_claude_install_record")
            continue
        for entry in installs:
            try:
                if (not isinstance(entry, dict) or not isinstance(entry.get("scope"), str)
                        or entry.get("scope") not in {"user", "project", "local"}):
                    raise ConfigError("插件范围无效")
                scope = entry["scope"]
                if scope != "user":
                    installed_project = absolute_path(entry.get("projectPath"))
                    if installed_project not in roots:
                        continue
                root = absolute_path(entry.get("installPath"))
                storage.project_identity(root)
                manifest = _json(inventory, root / ".claude-plugin/plugin.json")
                if not isinstance(manifest, dict):
                    raise ConfigError("插件清单无效")
                name = manifest.get("name", plugin_id.split("@", 1)[0])
                if not isinstance(name, str) or not name or len(name) > 200 or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in name):
                    raise ConfigError("插件名称无效")
                source_id = plugin_id + "|" + scope + "|" + str(root) + "|" + str(entry.get("projectPath", ""))
                if "agents" in manifest:
                    declarations = manifest["agents"] if isinstance(manifest["agents"], list) else [manifest["agents"]]
                    if len(declarations) > MAX_AGENTS:
                        raise ConfigError("插件 Agent 条目过多")
                    files = []
                    for raw in declarations:
                        path = _relative(root, raw)
                        if path.suffix != ".md":
                            raise ConfigError("Claude 插件 agents 只允许 Markdown 文件")
                        within_default = path.is_relative_to(root / "agents")
                        files.append((path, path.relative_to(root / "agents").as_posix() if within_default else path.name, within_default))
                else:
                    files = [(path, path.relative_to(root / "agents").as_posix(), True)
                             for path in _files(inventory, root / "agents", style="claude")]
                for path, logical, verified in files:
                    _add(inventory, root, path, origin="plugin", scope=scope, source_id=source_id,
                         rank=1000, plugin=name, enabled=enabled.get(plugin_id), logical=logical, invoke_verified=verified)
            except (OSError, ValueError):
                inventory.diagnostic("invalid_or_unsafe_plugin_install", directory / "plugins/installed_plugins.json")


def _agy_plugins(inventory, root, scope):
    for name, mode in _entries(inventory, root):
        plugin_root = root / name
        if stat.S_ISLNK(mode):
            inventory.diagnostic("symlink_rejected", plugin_root)
            continue
        if not stat.S_ISDIR(mode):
            continue
        manifest = None
        for relative in (".antigravity-plugin/plugin.json", "plugin.json", ".gemini-plugin/plugin.json"):
            manifest_path = plugin_root / relative
            candidate = _json(inventory, manifest_path)
            if candidate is None:
                break
            if inventory.snapshots.get(manifest_path, storage.Snapshot()).body is not None:
                manifest = candidate
                break
        if (not isinstance(manifest, dict) or not isinstance(manifest.get("name"), str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", manifest["name"])):
            inventory.diagnostic("invalid_ady_plugin_manifest", plugin_root)
            continue
        # 官方目录证明资产已安装，不证明当前插件已启用；未知状态必须保留。
        inventory.diagnostic("plugin_enablement_unobserved", plugin_root)
        for path in _files(inventory, plugin_root / "agents", style="antigravity"):
            _add(inventory, plugin_root, path, origin="plugin", scope=scope,
                 source_id=str(plugin_root), rank=1000, plugin=manifest["name"], enabled=None)


def _precedence(inventory):
    groups = {}
    for agent in inventory.agents:
        groups.setdefault(agent.invoke_name, []).append(agent)
    for group in groups.values():
        active = [agent for agent in group if agent.enabled is not False]
        for agent in group:
            if agent.enabled is False:
                agent.definition_status = "disabled"
        if not active:
            continue
        if inventory.host == "codex" and len(active) > 1:
            for agent in active:
                agent.definition_status = "ambiguous"
            inventory.diagnostic("codex_cross_source_name_precedence_unverified")
            continue
        if inventory.host == "antigravity" and any(agent.origin == "plugin" for agent in active) and len(active) > 1:
            for agent in active:
                agent.definition_status = "ambiguous"
            inventory.diagnostic("agy_plugin_name_precedence_unverified")
            continue
        minimum = min(agent.rank for agent in active)
        winners = [agent for agent in active if agent.rank == minimum]
        for agent in active:
            if agent.rank > minimum:
                agent.definition_status = "shadowed"
                agent.shadowed_by = winners[0].id if len(winners) == 1 else None
            elif len(winners) > 1:
                agent.definition_status = "ambiguous"
            else:
                agent.definition_status = "installation_observed" if agent.origin == "plugin" and agent.enabled is None else "effective_in_discovered_sources"


def discover(host: str, home: Path, project: Path | None = None, *, host_roots: dict | None = None) -> Inventory:
    host_name(host)
    inventory = Inventory(host)
    roots = project_roots(project)
    directories = {"codex": home / ".codex", "claude": home / ".claude", "antigravity": home / ".gemini/config"}
    directories.update(host_roots or {})
    directory = directories[host]
    user_root = directory / "agents"
    for path in _files(inventory, user_root, style=host):
        _add(inventory, user_root, path, origin="user", scope="user", source_id=str(user_root), rank=100)
    for rank, root in enumerate(roots):
        agents = root / {"codex": ".codex/agents", "claude": ".claude/agents", "antigravity": ".agents/agents"}[host]
        for path in _files(inventory, agents, style=host):
            _add(inventory, agents, path, origin="project", scope="project", source_id=str(root), rank=rank)
    if host == "claude":
        _claude_plugins(inventory, directory, roots)
        inventory.diagnostic("managed_cli_add_dir_and_session_agents_unobserved")
    elif host == "codex":
        inventory.diagnostic("codex_plugin_agent_discovery_not_documented")
        inventory.diagnostic("parent_spawn_agents_defaults_and_managed_policy_unobserved")
    else:
        _agy_plugins(inventory, directory / "plugins", "user")
        for root in roots:
            _agy_plugins(inventory, root / ".agents/plugins", "project")
        for base in [directory, *(root / ".agents" for root in roots)]:
            for relative in ("agents.json", "plugins.json"):
                node = inventory.read(base / relative)
                if node.body is not None:
                    inventory.diagnostic("external_discovery_manifest_not_supported", base / relative)
        inventory.diagnostic("personal_repo_folders_and_session_agents_unobserved")
        inventory.diagnostic("agy_flash_lite_documented_in_build_plugins_not_subagents_table")
    _precedence(inventory)
    inventory.agents.sort(key=lambda agent: (agent.document.name, agent.origin, agent.source_id, agent.relative))
    return inventory
