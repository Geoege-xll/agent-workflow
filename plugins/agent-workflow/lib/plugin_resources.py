"""官方插件安装中的精确只读来源，不参与中央 pin、项目发现或配置迁移。

插件根只能由当前模块自己的物理安装位置确认，环境变量只是调用模式声明，不能
授予任意目录读取权限。每次读取都重新校验来源清单与目标摘要，不扫描用户目录。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from lib.hosts.claude_instructions import read_file
from lib.standard_paths import builtin_source_path


PLUGIN_ENV = "AGENT_WORKFLOW_PLUGIN_ROOT"
MANIFEST = "workflow-sources.json"
# 保持旧中央上下文的原有定义；插件模式单独拒绝桥变量，不制造 runtime_binding。
BRIDGE_ENV = (
    "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
    "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT",
)
_SHA256 = re.compile(r"[a-f0-9]{64}", re.ASCII)
# 这些命名空间承载插件工作流、角色和宿主/共享规范权威。即使清单漏项，也不能
# 把相同逻辑路径降级为普通项目文档，否则项目诱饵会静默替代插件规则。
_AUTHORITY_DIRECTORIES = frozenset({"product", "roles", "platforms"})


class PluginResourceError(ValueError):
    """插件声明、来源清单或被读取资源违反固定安装的安全边界。"""


def _canonical(path: str) -> bool:
    """清单键只使用规范 POSIX 相对路径，拒绝别名、父跳转和特殊路径字符。"""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        return False
    parsed = PurePosixPath(path)
    return (bool(parsed.parts) and not parsed.is_absolute()
            and parsed.as_posix() == path and ".." not in parsed.parts
            and ":" not in path)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """重复 JSON 键不能靠后项覆盖，让损坏清单变成另一个有效授权集合。"""
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PluginResourceError("插件来源清单不得包含重复字段")
        value[key] = item
    return value


def _identity(info) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(path: Path) -> bytes:
    """复用单链接、无符号链接祖先与 4 MiB 上限，并检测读取期间的节点变化。

    来源文件都是 UTF-8 文本；read_file 仅验证编码，返回的仍是未改写原始字节，
    因而 CRLF、中文等参与摘要时不会发生归一化。
    """
    try:
        before = path.lstat()
        body = read_file(path)
        after = path.lstat()
        if body is None or _identity(before) != _identity(after) or len(body) != before.st_size:
            raise PluginResourceError("插件来源在读取期间发生变化")
        return body
    except PluginResourceError:
        raise
    except (OSError, ValueError) as exc:
        raise PluginResourceError("插件来源缺失或不符合安全读取要求") from exc


def _root() -> Path | None:
    """只接受当前模块所属的物理安装根，不把环境路径当成可信插件发现入口。"""
    supplied = os.environ.get(PLUGIN_ENV)
    if supplied is None:
        return None
    if any(name in os.environ for name in BRIDGE_ENV):
        raise PluginResourceError("插件环境不能与中央桥环境混用")
    try:
        selected = Path(supplied)
        physical = Path(__file__).resolve(strict=True).parents[1]
        if (not selected.is_absolute() or ".." in selected.parts
                or selected != selected.resolve(strict=True) or selected != physical
                or not selected.is_dir()):
            raise PluginResourceError("插件根必须与当前模块的物理安装根完全一致")
        # 根及其祖先也不能借符号链接进入其他安装；正文读取器再次检查父目录。
        if any(parent.is_symlink() for parent in (selected, *selected.parents)):
            raise PluginResourceError("插件安装根不得包含符号链接")
        return selected
    except (OSError, RuntimeError) as exc:
        raise PluginResourceError("插件根必须是存在的物理绝对目录") from exc


def _manifest(root: Path) -> dict[str, str]:
    """严格解析固定清单；只验证明确列出的键，不遍历安装目录或用户文件。"""
    try:
        value = json.loads(_read(root / MANIFEST), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError) as exc:
        raise PluginResourceError("插件来源清单损坏") from exc
    if (not isinstance(value, dict) or set(value) != {"schema_version", "files"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["files"], dict) or not value["files"]):
        raise PluginResourceError("插件来源清单必须使用 schema_version 1 和非空 files 对象")
    for relative, digest in value["files"].items():
        if (not _canonical(relative) or not isinstance(digest, str)
                or _SHA256.fullmatch(digest) is None):
            raise PluginResourceError("插件来源清单必须使用规范相对路径和小写 SHA-256")
    return value["files"]


def plugin_root() -> Path | None:
    """无插件变量时完全保留 2.x 行为；启用后根和来源清单均须有效。"""
    root = _root()
    if root is not None:
        _manifest(root)
    return root


def read_source(logical_path: str) -> bytes:
    """读取清单精确列管的 canonical 来源，绝不回退源码仓或业务项目同名文件。"""
    root = _root()
    if root is None:
        raise PluginResourceError("未声明插件安装上下文")
    sources = _manifest(root)
    if not _canonical(logical_path) or logical_path not in sources:
        raise PluginResourceError("资源不在插件来源清单中")
    # 项目配置属于项目所有者，即使坏装配误列入清单也不能作为插件资源消费。
    if logical_path in {"project.yaml", ".agent-workflow/project.yaml"}:
        raise PluginResourceError("项目适配器不能作为插件来源读取")
    body = _read(root / logical_path)
    if hashlib.sha256(body).hexdigest() != sources[logical_path]:
        raise PluginResourceError("插件来源 SHA-256 与清单不一致")
    return body


def read_builtin_source(path: str) -> bytes:
    """只有三份内置标准及既有精确别名获得跨项目根读取权限。"""
    relative = builtin_source_path(path)
    if relative is None:
        raise PluginResourceError("不是精确的内置规范来源")
    return read_source(relative)


def resource_path(path: Path, project_root: Path) -> str | None:
    """为分页器定位清单来源；其余文件仍交回实际项目的安全读取器。

    接受安装根中的物理路径及项目根下的只读逻辑路径；.agent-workflow 仅允许
    一次既有来源别名，project.yaml 始终留在项目中，不读取插件中的配置冒充。
    """
    root = _root()
    if root is None:
        return None
    sources = _manifest(root)
    if path.is_absolute():
        if path.is_relative_to(root):
            raw = path.relative_to(root).as_posix()
        elif path.is_relative_to(project_root):
            raw = path.relative_to(project_root).as_posix()
        else:
            return None
    else:
        raw = path.as_posix()
    if not _canonical(raw):
        raise PluginResourceError("插件资源必须是规范逻辑路径")
    if raw in {"project.yaml", ".agent-workflow/project.yaml"}:
        return None
    if raw.startswith(".agent-workflow/"):
        raw = raw[len(".agent-workflow/"):]
    if raw in sources:
        return raw
    if PurePosixPath(raw).parts[0] in _AUTHORITY_DIRECTORIES:
        raise PluginResourceError("插件权威资源不在插件来源清单中；拒绝项目同名替代")
    return None
