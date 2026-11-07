"""从宿主本地配置提取模型目录；只投影白名单字段，绝不返回密钥或完整配置。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import hashlib
import os
from pathlib import Path
import re
import tomllib

from lib.role_models import EFFORTS, MODEL_ID
from .claude_execution import project_controls, project_environment, project_write_scope_guard
from . import codex_models


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    source: str
    efforts: tuple[str, ...] = ()


@dataclass
class Catalog:
    host: str
    models: list[Model] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    inactive: list[str] = field(default_factory=list)
    stamp: str = ""
    _inputs: list = field(default_factory=list, repr=False)
    execution: dict = field(default_factory=dict)
    _native: codex_models.NativeModels | None = field(default=None, repr=False)
    _native_scope: tuple[str, str | None] | None = field(default=None, repr=False)
    _native_cache: str | None = field(default=None, repr=False)
    # 只由真实查询填写的前后来源收据；偏好服务以它证明同一批次内的缓存刷新链。
    # 已发布目录的校验不消费此收据，更不能用它自动续期旧草稿授权。
    _native_query: tuple[tuple[str, str | None], tuple[str, str | None]] | None = field(default=None, repr=False)
    # stamp 只证明来源投影，不证明目录读取成功。此内部状态供交互入口决定是否
    # 需要重新获取，不能由提示文案推断，也不改变 as_dict 的公开输出合同。
    _status: str = field(default="ready", repr=False)

    def as_dict(self) -> dict:
        return {"host":self.host,"models":[asdict(row) for row in self.models],
                "notes":self.notes,"inactive":self.inactive,"execution":self.execution}


def clean(value: object, limit: int = 180) -> str:
    """配置中的标签不可信，移除终端控制符并限制展示长度。"""
    return "".join(char for char in str(value) if char.isprintable())[:limit]


def read_data(path: Path, *, toml: bool = False) -> dict:
    if not path.exists():
        return {}
    # 缓存可能是异常特殊文件；有界且只读，禁止读取 FIFO 或无限大的目录文件。
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError(f"模型来源不是有界普通文件：{path}")
    text = path.read_text(encoding="utf-8")
    try:
        value = tomllib.loads(text) if toml else json.loads(text)
    except RecursionError as exc:
        # Python 3.11 会在 JSON 解码阶段拒绝过深输入；在来源边界转为正常失败合同，
        # 让 discover、CLI 和 TUI 共用诊断并保留草稿，不展示解析器消息或来源正文。
        raise ValueError(f"模型来源嵌套过深，无法解析：{path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"模型来源必须是对象：{path}")
    return value


def remember(catalog: Catalog,value) -> None:
    """只摘要影响选择的有效投影，不把权限、Hooks、废弃配置或凭据当成门禁。"""
    digest=hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
    catalog._inputs.append(digest)


def _append(catalog: Catalog, identifier: object, label: object, source: str, levels=()) -> None:
    if not isinstance(identifier, str) or not MODEL_ID.fullmatch(identifier):
        return
    if any(row.id == identifier for row in catalog.models):
        return
    supported = tuple(dict.fromkeys(item for item in levels if item in EFFORTS))
    catalog.models.append(Model(identifier, clean(label or identifier), clean(source), supported))


def _stat_signal(path: Path) -> tuple | None:
    """身份文件只取元数据，连同链接目标变化一起守卫，绝不读取 auth 正文或凭据。"""
    try:
        link, target = path.lstat(), path.stat()
        return tuple((item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
                     for item in (link, target))
    except OSError:
        return None


def _codex_native_scope(catalog: Catalog, directory: Path, cwd: Path, command: str | None) -> tuple[str, str | None]:
    # 默认缓存只提供不透明身份的失效信号，不能贡献候选；损坏/缺失也不能覆盖 native 成功结果。
    identity = None
    try:
        value = read_data(directory / "models_cache.json").get("identity")
        if isinstance(value, str) and value:
            identity = hashlib.sha256(value.encode()).hexdigest()
    except (OSError, ValueError, TypeError):
        pass
    material = {"inputs": catalog._inputs, "cwd": str(cwd.absolute()), "executable": command,
                "binary": _stat_signal(Path(command)) if command else None,
                "auth_metadata": _stat_signal(directory / "auth.json")}
    # 身份/有效来源必须跨查询稳定；cache identity 则允许由本次宿主查询自行刷新。
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest(), identity


def _codex(catalog: Catalog, home: Path, project: Path | None, env: dict, snapshot: Catalog | None) -> None:
    directory = Path(env.get("CODEX_HOME", home / ".codex")).expanduser()
    config = read_data(directory / "config.toml", toml=True)
    keys=("model","model_catalog_json","model_provider","model_reasoning_effort","cli_auth_credentials_store")
    layers={key:str((directory/"config.toml").absolute()) for key in keys if key in config}
    local={}
    catalog_directory=directory
    # 当前宿主不再读取旧的 profile / [profiles.*]，管理器也不能把失效层当成当前来源。
    if "profile" in config or "profiles" in config:
        catalog.notes.append("忽略已废弃的 profile / [profiles.*]；独立 profile 会话必须明确其目录来源，不能自动推断。")
    # 项目可以覆盖模型，但不允许项目配置把提供方或私密全局配置带入输出。
    if project:
        local = read_data(project / ".codex/config.toml", toml=True)
        for name in keys:
            if name in local:
                config[name] = local[name]
                layers[name]=str((project/".codex/config.toml").absolute())
                if name == "model_catalog_json":catalog_directory=project/".codex"
    explicit = config.get("model_catalog_json")
    path = Path(explicit).expanduser() if isinstance(explicit, str) else directory / "models_cache.json"
    if not path.is_absolute():
        path = catalog_directory / path
    # 默认缓存不作为模型证据；只有不透明身份摘要可在 native 快照建立后充当失效信号。
    # 独立 CPA/CC-Switch 目录不能因“文件存在”就混进当前提供方的可选模型。
    # 宿主真实 identity 是不透明字符串摘要，不是可直接读取 model_provider 的对象。
    # 不读取账户凭据来猜摘要；显式目录沿原有声明层优先，其他目录由原生宿主确认。
    matches = isinstance(explicit,str) and bool(explicit)
    endpoint={};endpoint_layers={}
    # 仅投影当前提供方的有效字段，项目层同名字段覆盖全局，未使用的提供方不参与摘要。
    for source,layer in ((config,directory/"config.toml"),(local,project/".codex/config.toml" if project else directory/"config.toml")):
        providers=source.get("model_providers",{})
        provider=providers.get(config.get("model_provider"),{}) if isinstance(providers,dict) else {}
        for key in ("base_url","wire_api","env_key","requires_openai_auth"):
            if isinstance(provider,dict) and key in provider:
                endpoint[key]=provider[key];endpoint_layers[key]=str(layer.absolute())
    remember(catalog,{"directory":str(directory.absolute()),"effective":{key:config[key] for key in keys if key in config},
                      "layers":layers,"provider":endpoint,"provider_layers":endpoint_layers,"base_url_override":env.get("OPENAI_BASE_URL"),
                      "catalog":str(path.absolute()) if matches else None})
    if matches:
        cache=read_data(path)
        remember(catalog,{"identity":cache.get("identity")})
        rows = cache.get("models", [])
        if not isinstance(rows, list):
            raise ValueError("Codex 模型缓存的 models 必须为数组")
        for row in rows:
            if not isinstance(row, dict) or row.get("visibility", "list") not in {"list", "visible"}:
                continue
            levels = row.get("supported_reasoning_levels", [])
            _append(catalog, row.get("slug", row.get("id")), row.get("display_name"), str(path),
                    [item.get("effort") if isinstance(item, dict) else item for item in levels] if isinstance(levels, list) else [])
    else:
        cwd = project or Path.cwd()
        command = codex_models.executable(env)
        scope = _codex_native_scope(catalog, directory, cwd, command)
        catalog._native_cache = str((directory / "models_cache.json").absolute())
        if snapshot is None:
            # 只在首次发现或显式刷新时启动进程；保留真实 HOME/配置/提供方与项目信任边界。
            native_env = dict(env)
            native_env.setdefault("HOME", str(home))
            native_env["CODEX_HOME"] = str(directory.absolute())
            result = codex_models.query(command, cwd, native_env)
            # 复用已有 _snapshot 路径重新读取有效配置/身份/可执行文件，不启动第二次查询。
            # 不能把查询期间的新身份绑定给此前返回的旧结果；变化时连配置后备项也保守丢弃。
            checked = discover("codex", home, project, env, _snapshot=catalog)
            if checked._native_scope is None or checked._native_scope[0] != scope[0]:
                raise ValueError("原生目录查询期间身份或有效来源已变化；本次结果已丢弃，请按 r 刷新")
            catalog._native_query = (scope, checked._native_scope)
            # 只有稳定守卫一致，才采用宿主自己更新后的 cache identity，防止快照立即误失效。
            scope = checked._native_scope
        elif snapshot.host == "codex" and snapshot._native_scope == scope:
            result = snapshot._native
        else:
            result = None
        catalog._native, catalog._native_scope = result, scope
        remember(catalog, {"native_scope": scope})
        if result is None:
            catalog._status = "stale"
            catalog.notes.append("原生目录来源已变化；重新进入编辑或按 r 刷新后重选，当前仅保留明确配置。")
        elif result.failure:
            catalog._status = "failed"
            catalog.notes.append("Codex 原生目录获取失败：" + result.failure + "；已回退到继承与当前明确配置。")
        else:
            remember(catalog, {"native_models": [{"model": row.model, "efforts": row.efforts,
                                                  "default_effort": row.default_effort} for row in result.models]})
            for row in result.models:
                _append(catalog, row.model, row.label, "当前 Codex 原生 app-server model/list", row.efforts)
            catalog.notes.append("目录来自当前 Codex 原生 model/list；按 r 重新获取，默认缓存不提供候选模型。")
        if path.is_file():catalog.inactive.append(clean(str(path))+"（缓存归属未确认）")
    _append(catalog, config.get("model"), config.get("model"), "当前 Codex 配置；推理能力待确认")
    selected=next((row for row in catalog.models if row.id == config.get("model")),None)
    if selected:
        # 继承项只携带当前模型已有的能力证据；未知能力由选择器提供宿主标准档位，
        # 不能把可写入的后备值填进 efforts，伪装成模型已证实的能力。
        catalog.models[0]=Model("inherit","继承宿主配置",selected.source,selected.efforts)
    if directory.is_dir():
        for alternative in sorted(directory.glob("*model*catalog*.json"))[:20]:
            if alternative != path:
                catalog.inactive.append(clean(str(alternative)) + "（未被当前配置引用）")
    catalog.notes.append("目录可见不等于推理调用成功；未启动推理会话。ultra 涉及自动委派，不提供该选项。")


CLAUDE_PROVIDER_ROUTES = {
    "CLAUDE_CODE_USE_BEDROCK": ("ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_BEDROCK_REGION_PREFIX"),
    "CLAUDE_CODE_USE_MANTLE": ("ANTHROPIC_BEDROCK_MANTLE_BASE_URL",),
    "CLAUDE_CODE_USE_VERTEX": ("ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION"),
    "CLAUDE_CODE_USE_FOUNDRY": ("ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_FOUNDRY_RESOURCE"),
    "CLAUDE_CODE_USE_ANTHROPIC_AWS": ("ANTHROPIC_AWS_BASE_URL", "ANTHROPIC_AWS_WORKSPACE_ID"),
}
CLAUDE_BEDROCK_SDK_ENDPOINTS = (
    "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_BEDROCK", "AWS_ENDPOINT_URL_BEDROCK_RUNTIME",
    "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS",
)


def _claude_route_inputs(effective: dict) -> dict:
    """摘要明确的非敏感路由输入；关闭的提供方专属字段不参与当前授权。

    只读取白名单值和来源，不读取 AWS/GCP/Azure 凭据文件或 token；显式 region、
    endpoint、project/workspace/resource 改动需要重选，但不能宣称已验证实际账户可用。
    多提供方也可能按模型分流（例如 Bedrock + Mantle），因此不猜一个互斥的提供方。
    """
    # 0/false/空串都表示关闭；只改变关闭的拼写不改变提供方。仍保留来源层，
    # 以区分文件明确禁用 shell 开关与没有文件覆盖这两种授权前像。
    routes = {key: (isinstance(effective[key][0], str)
                    and effective[key][0].lower() in {"1", "true", "yes", "on"}, effective[key][1])
              for key in CLAUDE_PROVIDER_ROUTES if key in effective}
    enabled = {key for key, (active, _) in routes.items() if active}
    keys = {"ANTHROPIC_BASE_URL"}
    for selector in enabled:
        keys.update(CLAUDE_PROVIDER_ROUTES[selector])
    if "CLAUDE_CODE_USE_BEDROCK" in enabled:
        # Claude 的显式 Bedrock client 端点也用于 token counting/profile listing，
        # 并非仅运行面（官方 changelog 2.0.71）。它优先于 SDK 端点，且不受
        # AWS_IGNORE_CONFIGURED_ENDPOINT_URLS 影响；空串则继续向 SDK 层回退。
        keys.discard("ANTHROPIC_BEDROCK_BASE_URL")
        explicit = effective.get("ANTHROPIC_BEDROCK_BASE_URL", (None,))
        if isinstance(explicit[0], str) and explicit[0]:
            routes["bedrock_endpoints"] = {"client": explicit}
        else:
            ignored = effective.get("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", ("false", "sdk_default"))
            ignore_value = isinstance(ignored[0], str) and ignored[0].lower() == "true"
            endpoints = {"ignore_configured": (ignore_value, ignored[1])}
            if not ignore_value:
                # SDK 的两个 service 分别消费控制面与运行面端点。仅当两个都
                # 覆盖 global 时，global 才完全不生效；不能把三者当作一条覆盖链。
                # 此处只选择已读 env，不读取 SDK profile/config 或凭据正文。
                for client, service_key in (("control", "AWS_ENDPOINT_URL_BEDROCK"),
                                            ("runtime", "AWS_ENDPOINT_URL_BEDROCK_RUNTIME")):
                    for key in (service_key, "AWS_ENDPOINT_URL"):
                        value = effective.get(key, (None,))
                        if isinstance(value[0], str) and value[0]:
                            endpoints[client] = {key: value}
                            break
            routes["bedrock_endpoints"] = endpoints
    if enabled & {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_ANTHROPIC_AWS"}:
        keys.add("AWS_PROFILE")
        # 宿主忽略形状非法的 region，再按 AWS_REGION → AWS_DEFAULT_REGION
        # 查找；只纳入首个有效显式值。SDK profile/凭据文件的实际 region 未读取，
        # 不冒充已解析，也不读取凭据正文来猜账户可见性。
        for key in ("AWS_REGION", "AWS_DEFAULT_REGION"):
            region = effective.get(key, (None,))[0]
            if isinstance(region, str) and re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+", region):
                keys.add(key)
                break
    # Bedrock 未明确选用 Haiku 时，背景请求使用主会话/默认 Sonnet 的 region，
    # small-fast region 不生效。SMALL_FAST_MODEL 虽已弃用，当前宿主仍承认它，
    # 这里只遵守现行原生谓词，不增加 AWF 的旧版兼容分支。官方 env-vars 对
    # Mantle 单独允许 Haiku region；Anthropic AWS 不消费这一变量。
    has_small_model = any(isinstance(effective.get(key, (None,))[0], str) and effective[key][0]
                          for key in ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL"))
    if "CLAUDE_CODE_USE_MANTLE" in enabled or "CLAUDE_CODE_USE_BEDROCK" in enabled and has_small_model:
        keys.add("ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION")
    if "CLAUDE_CODE_USE_VERTEX" in enabled:
        # Vertex 接受 global、eu/us 等多区域和 us-east5 等区域形状；斜杠、点、
        # 空格等非法值按 unset，不因两个不同非法拼写废弃草稿。每模型非法值
        # 回退 CLOUD_ML_REGION，再回退宿主 us-east5；只摘要真实有效的显式层。
        keys.discard("CLOUD_ML_REGION")
        for key in ("CLOUD_ML_REGION", *(key for key in effective if key.startswith("VERTEX_REGION_CLAUDE_"))):
            value = effective.get(key, (None,))[0]
            if isinstance(value, str) and re.fullmatch(r"[a-z0-9-]+", value):
                keys.add(key)
    if "CLAUDE_CODE_USE_FOUNDRY" in enabled and effective.get("ANTHROPIC_FOUNDRY_BASE_URL", (None,))[0]:
        keys.discard("ANTHROPIC_FOUNDRY_RESOURCE")
    routes.update({key: effective[key] for key in keys if key in effective})
    return routes


def _claude(catalog: Catalog, home: Path, project: Path | None, env: dict) -> None:
    directory = Path(env.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
    user_path = directory / "settings.json"
    config = read_data(user_path)
    sources = [(str(user_path.absolute()), config)]
    if project:
        for name in ("settings.json", "settings.local.json"):
            path = project / ".claude" / name
            sources.append((str(path.absolute()), read_data(path)))
    aliases = ("opus", "sonnet", "haiku", "fable")
    mapping_keys = tuple(f"ANTHROPIC_DEFAULT_{alias.upper()}_MODEL" for alias in aliases)
    route_keys = tuple(dict.fromkeys(key for keys in CLAUDE_PROVIDER_ROUTES.values() for key in keys))
    # Vertex 文档为每模型 region 定义了这一专用变量族；只枚举它的变量名，
    # 不把任意 ANTHROPIC_/CLAUDE_CODE_ 或完整 shell/env 纳入来源摘要。
    vertex_regions = {key for key in env if key.startswith("VERTEX_REGION_CLAUDE_")}
    for _, settings in sources:
        entries = settings.get("env", {})
        if not isinstance(entries, dict):
            raise ValueError("Claude env 必须为对象")
        vertex_regions.update(key for key in entries if key.startswith("VERTEX_REGION_CLAUDE_"))
    keys = ("ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
            "ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION", "ANTHROPIC_SMALL_FAST_MODEL", *CLAUDE_BEDROCK_SDK_ENDPOINTS,
            *mapping_keys, *CLAUDE_PROVIDER_ROUTES,
            *route_keys, *sorted(vertex_regions))
    effective = project_environment(sources, env, keys)
    current_model = None
    model_source = None
    for source, settings in sources:
        if "model" in settings:
            current_model, model_source = settings["model"], source
    if "ANTHROPIC_MODEL" in effective:
        current_model, model_source = effective["ANTHROPIC_MODEL"]
    # modelPicker 是原生 user/--settings/managed 专用字段，项目/local 即使合法也
    # 必须忽略。本工具只读取 user；当前显式菜单/模型不是旧缓存，换路由也不清空。
    # 路由变化由 stamp 使已发布授权失效，不能靠删除有效配置来代替来源守卫。
    menu = config.get("modelPicker", {})
    for alias in ("opus", "sonnet", "haiku", "fable"):
        target = effective.get(f"ANTHROPIC_DEFAULT_{alias.upper()}_MODEL", (None,))[0]
        _append(catalog, alias, f"{alias} → {clean(target)}" if target else alias, "Claude 宿主别名 / 当前配置映射")
    options = menu.get("options", []) if isinstance(menu, dict) else []
    for row in options if isinstance(options, list) else []:
        if isinstance(row, str):
            _append(catalog, row, row, "Claude modelPicker 本地菜单")
        elif isinstance(row, dict):
            _append(catalog, row.get("value", row.get("model", row.get("id"))), row.get("label", row.get("name")), "Claude modelPicker 本地菜单")
    # 使用原始映射摘要，避免超长目标被展示清理截断后无法发现真实模型切换。
    remember(catalog, {"directory": str(directory.absolute()), "routes": _claude_route_inputs(effective),
                       "current": current_model, "model_source": model_source,
                       "menu_source": str(user_path.absolute()) if "modelPicker" in config else None,
                       "mapping": {key: effective[key] for key in mapping_keys if key in effective}})
    _append(catalog, current_model, current_model, "当前 Claude 配置 / 显式环境模型")
    catalog.notes.append("代理菜单及别名来自本地配置；modelSettings 中的偏好不能证明模型支持的推理档位。")
    controls = project_controls(sources, env)
    catalog.execution = {"status": "projected", "controls": controls, "write_scope_guard": project_write_scope_guard(sources),
                         "runtime_verified": False}
    # 只有模型/effort 覆盖变化影响来源校验；窗口、权限、fork/后台模式不会废弃模型草稿。
    remember(catalog, {key: value for key, value in controls.items()
                       if key in {"CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
                                  "CLAUDE_CODE_EFFORT_LEVEL"}})
    for key, entry in controls.items():
        display = entry["value"] if entry["status"] == "configured" else "无效值（已隐藏）"
        catalog.notes.append(f"{key} = {display} · {clean(entry['source'])}")
    catalog.notes.append("以上为普通本地设置投影；组织策略、调用时覆盖及运行中会话值未核验。角色 model: inherit 高于普通子 Agent 默认模型。")


def discover(host: str, home: Path | None = None, project: Path | None = None, env: dict | None = None,
             *, _snapshot: Catalog | None = None) -> Catalog:
    home = home or Path.home()
    env = dict(os.environ) if env is None else env
    catalog = Catalog(host, [Model("inherit", "继承宿主配置", "宿主原生继承")])
    try:
        if host == "codex":
            _codex(catalog, home, project, env, _snapshot)
        elif host == "claude":
            _claude(catalog, home, project, env)
        elif host == "antigravity":
            _append(catalog, "flash", "Flash 档位", "Antigravity 官方静态角色合同")
            _append(catalog, "pro", "Pro 档位", "Antigravity 官方静态角色合同")
            catalog.notes.append("未发现可靠完整目录；静态角色只使用 inherit / flash / pro，推理级别继承。")
        else:
            raise ValueError("未知平台")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        catalog._status = "failed"
        catalog.notes.append("模型来源读取失败：" + clean(str(exc)))
        if host == "claude":
            # 读取失败与“没有覆盖”是不同状态；不保留部分层结果以免输出确定的有效值。
            catalog.execution = {"status": "unavailable", "controls": {}, "runtime_verified": False,
                                 "write_scope_guard": {"status": "unknown", "value": None,
                                                       "source": None, "runtime_verified": False}}
    if host in {"codex","claude"}:
        catalog.notes.append("推理档位可独立修改；模型能力未知时可写入宿主标准值，但不代表模型已支持或 API 调用已验收。")
    # 仅持有摘要，供预览和发布前检测提供方、目录、身份与能力是否变化。
    material=[host,catalog._inputs,[{"id":row.id,"efforts":row.efforts} for row in catalog.models]]
    catalog.stamp=hashlib.sha256(json.dumps(material,sort_keys=True,default=str).encode()).hexdigest()
    return catalog
