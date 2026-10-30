"""从宿主本地配置提取模型目录；只投影白名单字段，绝不返回密钥或完整配置。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import hashlib
import os
from pathlib import Path
import tomllib

from lib.role_models import EFFORTS, MODEL_ID


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

    def as_dict(self) -> dict:
        return {"host":self.host,"models":[asdict(row) for row in self.models],
                "notes":self.notes,"inactive":self.inactive}


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
    value = tomllib.loads(text) if toml else json.loads(text)
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


def _codex(catalog: Catalog, home: Path, project: Path | None, env: dict) -> None:
    directory = Path(env.get("CODEX_HOME", home / ".codex")).expanduser()
    config = read_data(directory / "config.toml", toml=True)
    keys=("model","model_catalog_json","model_provider","model_reasoning_effort")
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
    # 默认缓存不作为模型证据，也不读取其正文触发无关失效或解析拒绝。
    # 独立 CPA/CC-Switch 目录不能因“文件存在”就混进当前提供方的可选模型。
    # 宿主真实 identity 是不透明字符串摘要，不是可直接读取 model_provider 的对象。
    # 不读取账户凭据来猜摘要；只有明确配置的目录才作为当前来源与能力证据。
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
        catalog.notes.append("默认缓存的身份摘要无法确认当前提供方/账户归属，仅提供继承与当前配置模型；显式模型目录按声明层读取。")
        if path.is_file():catalog.inactive.append(clean(str(path))+"（缓存归属未确认）")
    _append(catalog, config.get("model"), config.get("model"), "当前 Codex 配置；推理能力待确认")
    selected=next((row for row in catalog.models if row.id == config.get("model")),None)
    if selected:
        # 继承模型仍可指定角色 effort，但只提供当前模型有能力证据的档位。
        catalog.models[0]=Model("inherit","继承宿主配置",selected.source,selected.efforts)
    if directory.is_dir():
        for alternative in sorted(directory.glob("*model*catalog*.json"))[:20]:
            if alternative != path:
                catalog.inactive.append(clean(str(alternative)) + "（未被当前配置引用）")
    catalog.notes.append("目录可见不等于调用成功；不请求上游服务。ultra 涉及自动委派，不提供该选项。")


def _claude(catalog: Catalog, home: Path, project: Path | None, env: dict) -> None:
    directory = Path(env.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
    config = read_data(directory / "settings.json")
    layers={key:str((directory/"settings.json").absolute()) for key in ("model","modelPicker") if key in config}
    env_layers={key:str((directory/"settings.json").absolute()) for key in config.get("env",{})}
    effective_env = dict(config.get("env", {}))
    menu = config.get("modelPicker", {})
    # 只有提供方一致时才沿用已有菜单，防止项目或环境换代理后展示旧提供方模型。
    provider = effective_env.get("ANTHROPIC_BASE_URL")
    changed_provider = False
    current_model=config.get("model")
    if project:
        for name in ("settings.json", "settings.local.json"):
            local = read_data(project / ".claude" / name)
            updates = local.get("env", {})
            if "ANTHROPIC_BASE_URL" in updates and updates["ANTHROPIC_BASE_URL"] != provider:
                effective_env = {}; menu = {}; provider = updates["ANTHROPIC_BASE_URL"]; changed_provider = True
                current_model=None
                layers={};env_layers={}
            effective_env.update(updates)
            env_layers.update({key:str((project/".claude"/name).absolute()) for key in updates})
            if "modelPicker" in local:
                menu = local["modelPicker"]
                layers["modelPicker"]=str((project/".claude"/name).absolute())
            config.update(local)
            # 提供方切换只清继承的旧模型，同层或更高层明确指定的新模型必须保留。
            if "model" in local:current_model=local["model"];layers["model"]=str((project/".claude"/name).absolute())
    if env.get("ANTHROPIC_BASE_URL", provider) != provider:
        effective_env = {}; menu = {}; changed_provider = True
        current_model=None
        layers={};env_layers={}
        catalog.notes.append("环境变量切换了提供方，未沿用旧模型菜单。")
    for name, value in env.items():
        if name.startswith("ANTHROPIC_DEFAULT_") and name.endswith("_MODEL"):
            effective_env[name] = value
            env_layers[name]="environment"
    for alias in ("opus", "sonnet", "haiku", "fable"):
        target = effective_env.get(f"ANTHROPIC_DEFAULT_{alias.upper()}_MODEL")
        _append(catalog, alias, f"{alias} → {clean(target)}" if target else alias, "Claude 宿主别名 / 当前配置映射")
    options = menu.get("options", []) if isinstance(menu, dict) else []
    for row in options if isinstance(options, list) else []:
        if isinstance(row, str):
            _append(catalog, row, row, "Claude modelPicker 本地菜单")
        elif isinstance(row, dict):
            _append(catalog, row.get("value", row.get("model", row.get("id"))), row.get("label", row.get("name")), "Claude modelPicker 本地菜单")
    current_model=env.get("ANTHROPIC_MODEL",effective_env.get("ANTHROPIC_MODEL",current_model))
    if "ANTHROPIC_MODEL" in env:layers["model"]="environment"
    elif "ANTHROPIC_MODEL" in effective_env:layers["model"]=env_layers.get("ANTHROPIC_MODEL")
    selected_keys={f"ANTHROPIC_DEFAULT_{alias.upper()}_MODEL" for alias in ("opus","sonnet","haiku","fable")}
    # 使用原始映射摘要，避免超长目标被展示清理截断后无法发现真实模型切换。
    remember(catalog,{"directory":str(directory.absolute()),"provider":env.get("ANTHROPIC_BASE_URL",provider),
                      "provider_layer":"environment" if "ANTHROPIC_BASE_URL" in env else env_layers.get("ANTHROPIC_BASE_URL"),
                      "current":current_model,"layers":layers,
                      "mapping":{key:value for key,value in effective_env.items() if key in selected_keys},
                      "env_layers":{key:value for key,value in env_layers.items() if key in selected_keys},
                      "forced_model":env.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE")})
    _append(catalog, current_model, current_model, "当前 Claude 配置 / 显式环境模型")
    if changed_provider:
        catalog.notes.append("提供方已切换，旧 model 偏好不作为新目录的可用性证据。")
    catalog.notes.append("代理菜单及别名来自本地配置；modelSettings 中的偏好不能证明支持的推理档位，未知时保留继承。")
    if env.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE"):
        catalog.notes.append("检测到宿主子 Agent 模型强制选项，角色模型可能由主会话覆盖。")


def discover(host: str, home: Path | None = None, project: Path | None = None, env: dict | None = None) -> Catalog:
    home = home or Path.home()
    env = dict(os.environ) if env is None else env
    catalog = Catalog(host, [Model("inherit", "继承宿主配置", "宿主原生继承")])
    try:
        if host == "codex":
            _codex(catalog, home, project, env)
        elif host == "claude":
            _claude(catalog, home, project, env)
        elif host == "antigravity":
            _append(catalog, "flash", "Flash 档位", "Antigravity 官方静态角色合同")
            _append(catalog, "pro", "Pro 档位", "Antigravity 官方静态角色合同")
            catalog.notes.append("未发现可靠完整目录；静态角色只使用 inherit / flash / pro，推理级别继承。")
        else:
            raise ValueError("未知平台")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        catalog.notes.append("模型来源读取失败：" + clean(str(exc)))
    # 仅持有摘要，供预览和发布前检测提供方、目录、身份与能力是否变化。
    material=[host,catalog._inputs,[{"id":row.id,"efforts":row.efforts} for row in catalog.models]]
    catalog.stamp=hashlib.sha256(json.dumps(material,sort_keys=True,default=str).encode()).hexdigest()
    return catalog
