"""验证源树与插件任务的来源边界，拒绝退役的中央绑定。"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import json
import os
from pathlib import Path
from typing import Any

from lib import plugin_resources
from lib.plugin_resources import PLUGIN_ENV, read_builtin_source
from lib.safe_text import read_file


PROJECT_ENV = "AGENT_WORKFLOW_PROJECT_ROOT"
CENTRAL_MARKER = ".agent-workflow/runtime.json"


class TaskSourceError(ValueError):
    """项目或记录携带不受支持的来源。"""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TaskSourceError("runtime_binding JSON 不得包含重复字段")
        result[key] = value
    return result


def project_root(root: Path | None = None) -> Path:
    """根据调用方指定的项目目录或当前工作目录获取物理根。"""
    selected = (Path.cwd() if root is None else Path(root)).resolve(strict=True)
    if not selected.is_dir():
        raise TaskSourceError("项目根必须是实际存在的目录")
    return selected


def validate_task_source(record: dict[str, Any], *, root: Path | None = None) -> None:
    """所有入口统一拒绝旧任务／桥环境，包括悬空的项目标记；禁止回退到当前资源。"""
    plugin_resources.plugin_root()
    marker = project_root(root) / CENTRAL_MARKER
    if ("runtime_binding" in record or marker.exists() or marker.is_symlink()
            or any(name in os.environ for name in plugin_resources.BRIDGE_ENV)):
        raise TaskSourceError("插件不能接管已有 runtime_binding、中央项目根或旧桥环境")


def validate_pack_source(path: Path, *, root: Path | None = None) -> None:
    """受限读取当前任务包，验证 schema 2 与无旧来源绑定后允许分页。"""
    body = read_file(Path(path).absolute())
    if body is None:
        raise TaskSourceError("当前 task-pack 不存在")
    pack = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
    if (not isinstance(pack, dict) or type(pack.get("schema_version")) is not int
            or pack["schema_version"] != 2 or not isinstance(pack.get("task"), dict)):
        raise TaskSourceError("task-pack 必须是 schema_version 2 的当前自包含包")
    return validate_task_source(pack, root=root)
