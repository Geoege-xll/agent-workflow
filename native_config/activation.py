"""工作流原生启停业务：观察来源、继承与恢复资料，不代管宿主安装或运行。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import shlex

from . import activation_codecs as codec, inventory, storage
from .contracts import ConfigError, MAX_INVENTORY_BYTES, absolute_path, json_bytes, unique_json


PLUGIN_IDS = ("agent-workflow@agent-workflow-alpha", "agent-workflow@agent-workflow-local")
DOCUMENTATION = {"codex": "https://learn.chatgpt.com/docs/config-file/config-reference",
                 "claude": "https://code.claude.com/docs/en/plugins/cli-reference",
                 "antigravity": "https://antigravity.google/docs/plugins?tab=cli"}


@dataclass
class Activation:
    public: dict
    target: Path | None
    snapshots: dict = field(default_factory=dict)
    directories: dict = field(default_factory=dict)
    parent_stamp: tuple = ()

    @property
    def total_bytes(self):
        return sum(len(node.body or b"") for node in self.snapshots.values())

    def revision(self, *, include_target_parent=True):
        material = [[str(path), node.revision()] for path, node in sorted(self.snapshots.items(), key=lambda pair: str(pair[0]))]
        directories = [[str(path), stamp] for path, stamp in sorted(self.directories.items(), key=lambda pair: str(pair[0]))
                       if include_target_parent or self.target is None or path != self.target.parent]
        return hashlib.sha256(json_bytes([material, directories, self.public], limit=MAX_INVENTORY_BYTES)).hexdigest()


def _recovery(host, scope, project, plugin_id, *, data_dir, home, environment):
    # __file__ 定位源码与离开源码后的独立包；绝不依赖被停用 Skill 的路径。
    script = Path(__file__).resolve().parents[1] / "scripts/agent_config.sh"
    arguments = ["bash", str(script), "open", "--host", host, "--data-dir", str(data_dir)]
    if home is not None:
        arguments.extend(("--home", str(home)))
    else:
        # 环境选根的实例不能重开成 --home 模式。只给新命令的子进程固定
        # 当前已解析的 HOME 和两个宿主根，不修改调用 shell，也不复制任何
        # token/凭证等完整环境；即使之后换终端，仍回到原配置和状态根。
        selected = [name + "=" + environment[name] for name in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR")]
        arguments = ["env", *selected, *arguments]
    if project is not None:
        arguments.extend(("--project", str(project)))
    command = shlex.join(arguments)
    if host == "claude":
        native_scope = "local" if scope == "project" else "user"
        steps = ["在官方 Claude 插件管理界面确认来源后重新启用；或在对应目录执行：claude plugin enable "
                 + shlex.quote(plugin_id or PLUGIN_IDS[0]) + " --scope " + native_scope]
    elif host == "codex":
        steps = ["在 Codex 官方 /plugins 或桌面插件管理中确认来源并启用；也可将本页目标配置中 plugins."
                 + (plugin_id or PLUGIN_IDS[0]) + ".enabled 设为 true。Codex 没有本工具假设的 plugin enable 命令。"]
    else:
        steps = ["使用 Antigravity 官方插件管理界面确认实际范围并启用；本工具不写未经核实的启停配置键。"]
    steps.append("保存仅改变磁盘配置；请启动新会话核实加载与实际工作流行为，当前会话已加载上下文不会因此清除。")
    return {"open_command": command, "official_steps": steps, "documentation_url": DOCUMENTATION[host]}


def capture(host, scope, project, host_root, *, data_dir, home, environment):
    target = ((project / (".codex/config.toml" if host == "codex" else ".claude/settings.local.json"))
              if scope == "project" else host_root / ("config.toml" if host == "codex" else "settings.json"))
    public = {"supported": host != "antigravity", "writable": False, "state": "unknown", "plugin_id": None,
              "scope": scope, "source_path": str(target) if host != "antigravity" else None,
              "inherited_state": "unknown", "inherited_source": None, "effective_state": "unknown",
              "diagnostics": [], "read_only_reason": None, "runtime_verified": False}
    found = Activation(public, target if host != "antigravity" else None)

    def diagnostic(code, message):
        public["diagnostics"].append({"code": code, "message": message})

    def read(path):
        if path not in found.snapshots:
            found.directories[path.parent] = storage.directory_stamp(path.parent)
            found.snapshots[path] = storage.read(path)
            if found.total_bytes > MAX_INVENTORY_BYTES:
                raise ConfigError("启停来源总容量超过限制")
        return found.snapshots[path]

    def read_config(path):
        return codec.parse(host, read(path).body)

    plugin_id = None
    try:
        if host == "antigravity":
            raise ConfigError("尚无可证明的 Antigravity 用户／项目启停文件合同")
        user = host_root / ("config.toml" if host == "codex" else "settings.json")
        # 目标始终由服务端固定，不接受客户端传入文件或插件 ID。
        read(target)
        if host == "codex":
            config = read_config(user)
            plugins = config.get("plugins", {})
            markets = config.get("marketplaces", {})
            if not isinstance(plugins, dict) or not isinstance(markets, dict):
                raise ConfigError("Codex 插件或市场配置映射无效")
            if any(key.startswith("agent-workflow@") and key not in PLUGIN_IDS for key in plugins):
                raise ConfigError("存在其他同名工作流市场来源，不能猜测所选身份")
            candidates = [key for key in PLUGIN_IDS if key in plugins]
            if len(candidates) != 1:
                raise ConfigError("工作流来源未配置或同时存在 alpha/local，不能确定唯一插件身份")
            plugin_id = candidates[0]
            market_name = plugin_id.split("@", 1)[1]
            source = markets.get(market_name)
            if not isinstance(source, dict):
                raise ConfigError("缺少所选工作流的实际市场来源配置")
            if market_name == "agent-workflow-alpha":
                if (source.get("source_type") != "git"
                        or source.get("source", "").removesuffix(".git").removesuffix("/") != "https://github.com/Geoege-xll/agent-workflow"
                        or source.get("ref") != "plugins-codex-alpha"):
                    raise ConfigError("alpha 市场来源不匹配已知官方分发分支")
            else:
                if source.get("source_type") != "local":
                    raise ConfigError("local 市场必须有明确本地来源")
                root = absolute_path(source.get("source"))
                manifest = unique_json(read(root / ".agents/plugins/marketplace.json").body or b"{}")
                if not isinstance(manifest, dict) or manifest.get("name") != market_name:
                    raise ConfigError("local 市场清单身份未确认")
                declarations = manifest.get("plugins")
                if not isinstance(declarations, list):
                    raise ConfigError("local 市场插件声明未确认")
                entries = [entry for entry in declarations if isinstance(entry, dict) and entry.get("name") == "agent-workflow"]
                if len(entries) != 1 or not isinstance(entries[0].get("source"), dict) or entries[0]["source"].get("source") != "local":
                    raise ConfigError("local 市场必须包含唯一的本地工作流插件")
                plugin_root = inventory._relative(root, entries[0]["source"].get("path"))
                plugin_manifest = unique_json(read(plugin_root / ".codex-plugin/plugin.json").body or b"{}")
                if not isinstance(plugin_manifest, dict) or plugin_manifest.get("name") != "agent-workflow":
                    raise ConfigError("local 工作流插件清单身份未确认")
            diagnostic("configured_identity_observed", "已观察原生插件键及对应市场来源；未据此声称实际安装、信任或运行成功。")
        else:
            registry = unique_json(read(host_root / "plugins/installed_plugins.json").body or b"{}")
            if (not isinstance(registry, dict) or registry.get("version") != 2
                    or not isinstance(registry.get("plugins"), dict)):
                raise ConfigError("未观察到可识别的 Claude 安装记录")
            if any(key.startswith("agent-workflow@") and key not in PLUGIN_IDS for key in registry["plugins"]):
                raise ConfigError("存在其他同名工作流市场安装来源")
            candidates = []
            for key in PLUGIN_IDS:
                installs = registry["plugins"].get(key, [])
                if not isinstance(installs, list) or len(installs) > 512:
                    raise ConfigError("Claude 安装记录无效")
                applicable = []
                for entry in installs:
                    if not isinstance(entry, dict):
                        raise ConfigError("Claude 安装记录无效")
                    install_scope = entry.get("scope")
                    if install_scope == "user" or (scope == "project" and install_scope in {"project", "local"}
                                                    and entry.get("projectPath") == str(project)):
                        root = absolute_path(entry.get("installPath"))
                        manifest = unique_json(read(root / ".claude-plugin/plugin.json").body or b"{}")
                        if not isinstance(manifest, dict) or manifest.get("name") != "agent-workflow":
                            raise ConfigError("Claude 插件安装清单身份无效")
                        applicable.append(entry)
                if applicable:
                    candidates.append(key)
            if len(candidates) != 1:
                raise ConfigError("未观察到唯一的当前范围工作流安装来源")
            plugin_id = candidates[0]
            diagnostic("observed_install_registry", "已观察 Claude v2 安装记录与插件清单；该内部记录格式不等于稳定公共 API 或运行收据。")
        public["plugin_id"] = plugin_id
        public["state"] = codec.state(host, read(target).body, plugin_id)
        sources = []
        if scope == "project":
            sources.append(user)
            roots = inventory.project_roots(project)
            for root in reversed(roots):
                if host == "codex":
                    path = root / ".codex/config.toml"
                    if path != target:
                        sources.append(path)
                else:
                    sources.append(root / ".claude/settings.json")
                    path = root / ".claude/settings.local.json"
                    if path != target:
                        sources.append(path)
        inherited, inherited_source = "unknown", None
        for path in sources:
            value = codec.state(host, read(path).body, plugin_id)
            if value != "inherit":
                inherited, inherited_source = value, str(path)
        public.update(inherited_state=inherited, inherited_source=inherited_source,
                      effective_state=inherited if public["state"] == "inherit" else public["state"])
        found.parent_stamp = found.directories[target.parent]
        missing = [item for item in found.parent_stamp if item[1] is None]
        if len(missing) > 1:
            raise ConfigError("固定配置路径缺少多级父目录，需先通过宿主创建配置根")
        node = read(target)
        if node.identity and not node.identity[2] & 0o200:
            raise ConfigError("目标配置没有属主写权限")
        parent = target.parent if not missing else target.parent.parent
        with storage.directory(parent) as handle:
            info = os.fstat(handle.fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o300 != 0o300:
                raise ConfigError("配置父目录属主或写入权限不允许安全保存")
        # 用实际目标语法做一次无副作用试编译，复杂内联表等只读显示。
        codec.patch(host, node.body, plugin_id, "disabled" if public["state"] != "disabled" else "enabled")
        public["writable"] = True
        diagnostic("host_precedence_unobserved", "展示本地可观察配置；宿主托管策略、启动参数、profile、项目信任及当前会话加载仍由宿主决定。")
    except (OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
        # 仅显示本模块/codec 定义的固定业务提示；底层 OSError 可能携带
        # 私有文件名，不能直接拼进网页或日志。
        reason = str(exc) if isinstance(exc, ConfigError) else "无法确认唯一安全来源、原生格式或写入权限；请使用官方插件管理核对。"
        public["read_only_reason"] = reason if host != "antigravity" else "该平台尚不支持配置文件启停。"
        diagnostic("activation_unavailable" if host != "antigravity" else "unsupported_platform", public["read_only_reason"])
    public["recovery"] = _recovery(host, scope, project, plugin_id, data_dir=data_dir,
                                   home=home, environment=environment)
    return found


def preview(found, request):
    if (not isinstance(request, dict) or set(request) != {"state"} or not isinstance(request["state"], str)
            or request["state"] not in {"inherit", "enabled", "disabled"}):
        raise ConfigError("启停请求只接受 state: inherit/enabled/disabled")
    public, target = found.public, found.target
    if not public["supported"] or not public["writable"]:
        raise ConfigError("当前工作流启停来源只读或不支持")
    before = found.snapshots[target]
    after = codec.patch("codex" if target.suffix == ".toml" else "claude", before.body, public["plugin_id"], request["state"])
    writes, changes = [], []
    if public["state"] != request["state"]:
        writes.append(storage.Write("workflow_activation", target, before, after, found.parent_stamp))
        changes.append({"kind": "workflow_activation", "field": "enabled", "scope": public["scope"],
                        "source_path": str(target), "plugin_id": public["plugin_id"], "before": public["state"],
                        "after": request["state"], "effective_before": public["effective_state"],
                        "effective_after": public["inherited_state"] if request["state"] == "inherit" else request["state"]})
    warnings = ["保存只改变原生配置；新会话加载与实际工作流运行仍未验证。",
                "停用后请保留独立配置工具的重新打开命令及官方恢复步骤；当前会话已经加载的上下文不会被清除。"]
    return writes, changes, warnings
