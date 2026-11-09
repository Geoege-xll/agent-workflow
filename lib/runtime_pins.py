"""任务固定核心的共用读取边界，不从项目 locator 猜测旧任务所用版本。

任务只持有内容库的三字段 pin；机器路径来自本机状态和可信桥环境。普通项目文件
继续由原消费者安全读取，只有明确的内置来源／受管逻辑资源可以进入中央内容库。
"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import base64
import json
from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
from typing import Any

if __package__:
    from lib import runtime_store as store
    from .standard_paths import BUILTIN_STANDARD_SOURCES, builtin_source_path
    from lib.hosts.claude_instructions import read_file
else:
    import runtime_store as store
    from standard_paths import BUILTIN_STANDARD_SOURCES, builtin_source_path
    from lib.hosts.claude_instructions import read_file


BINDING_ENV = "AGENT_WORKFLOW_RUNTIME_BINDING"
PROJECT_ENV = "AGENT_WORKFLOW_PROJECT_ROOT"
CONFIG_ENV = "AGENT_WORKFLOW_CONFIG_PATH"
CORE_ENV = "AGENT_WORKFLOW_CORE_ROOT"
CENTRAL_ADAPTER = ".agent-workflow/project.yaml"
CENTRAL_MARKER = ".agent-workflow/runtime.json"


class RuntimePinError(ValueError):
    """任务 pin 缺失、冲突或桥上下文不属于当前项目。"""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimePinError("runtime_binding JSON 不得包含重复字段")
        result[key] = value
    return result


def decode_binding_b64(value: str) -> dict:
    """Windows Shell 只传规范 base64；解码正文硬限 4KiB，pin 仍严格三字段。"""
    if not isinstance(value, str) or len(value) > 5464:
        raise RuntimePinError("编码 runtime_binding 超过传输上限")
    try:
        body = base64.b64decode(value, validate=True)
        if len(body) > 4096 or base64.b64encode(body).decode("ascii") != value:
            raise ValueError("noncanonical binding")
        return store.validate_binding(json.loads(body.decode("utf-8", errors="strict"),
                                                 object_pairs_hook=_unique_object))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise RuntimePinError("编码 runtime_binding 无效") from exc


def environment_binding() -> dict | None:
    """每个进程重新解析桥 pin；拒绝空值和额外路径字段，不依赖 shell 的持久状态。"""
    raw = os.environ.get(BINDING_ENV)
    if raw is None:
        return None
    try:
        return store.validate_binding(json.loads(raw, object_pairs_hook=_unique_object))
    except (ValueError, TypeError) as exc:
        raise RuntimePinError("桥环境中的 runtime_binding 无效") from exc


def project_root(root: Path | None = None) -> Path:
    """显式根与桥根必须是同一物理项目；绝不从 core.parent 推导项目位置。"""
    supplied = os.environ.get(PROJECT_ENV)
    selected = Path(root) if root is not None else Path(supplied) if supplied else Path.cwd()
    selected = selected.resolve(strict=True)
    if supplied is not None and Path(supplied).resolve(strict=True) != selected:
        raise RuntimePinError("显式项目根与桥环境项目根不一致")
    if not selected.is_dir():
        raise RuntimePinError("项目根必须是实际存在的目录")
    return selected


def _central_context(root: Path) -> bool:
    # 只把标记的存在用于要求显式 pin；绝不读取其中的当前版本补全旧包。
    # 损坏／链接标记同样不能触发 source 降级，安全读取仍由项目服务负责。
    marker = root / CENTRAL_MARKER
    return (any(name in os.environ for name in (BINDING_ENV, PROJECT_ENV, CONFIG_ENV, CORE_ENV))
            or marker.exists() or marker.is_symlink())


def record_binding(record: dict[str, Any], *, root: Path | None = None,
                   initialize: bool = False, reader=None) -> dict | None:
    """解析 schema 2 图／单包的固定版本；仅新建时允许从桥环境投影 pin。

    既有记录缺 pin 时不能采用环境当前版。已有 pin 与桥执行版必须相同，未知／损坏
    版本直接由内容库拒绝。源包和旧自包含安装在没有中央上下文时保持无 pin 行为。
    """
    if reader is not None and not isinstance(reader, store.CoreReadSession):
        raise RuntimePinError("任务 pin 拒绝未知核心 reader")
    selected_root = project_root(root)
    environment = environment_binding()
    if "runtime_binding" in record:
        binding = store.validate_binding(record["runtime_binding"])
    elif initialize and environment is not None:
        binding = environment
    elif _central_context(selected_root):
        raise RuntimePinError("中央任务缺少 runtime_binding；拒绝回退当前项目版本")
    else:
        return None
    if environment is not None and binding != environment:
        raise RuntimePinError("任务 runtime_binding 与桥执行版本冲突")
    # 默认调用仍完整 fresh load；只有本次源读取显式持有的活跃 reader 可
    # 复用其已锚定证明。错误版本/state/已关闭对象不能静默回退或接受环境根。
    core = reader.core_for(binding) if reader is not None else store.load_core(binding)
    supplied_core = os.environ.get(CORE_ENV)
    if supplied_core is not None and Path(supplied_core).absolute() != core.root:
        raise RuntimePinError("桥核心根与任务固定内容库版本不一致")
    supplied_config = os.environ.get(CONFIG_ENV)
    if supplied_config is not None and Path(supplied_config).absolute() != selected_root / CENTRAL_ADAPTER:
        raise RuntimePinError("桥配置路径不是当前项目的中央适配器")
    return binding


@contextmanager
def new_task_publication(root: Path, binding: dict | None):
    """最终有效版重验到新图发布共用中央短锁，不持锁执行模型。

    早期预览允许与激活并行；最终绑定发生漂移时拒绝发布。此锁的实际 owner
    是新核心 child；旧核心没有此协议时由当前控制桥 parent 持锁执行旧 helper。
    不接受环境字符串跳过锁，也不从业务 Task Pack 接收任意状态路径。
    """
    if binding is None:
        yield
        return
    from manager import runtime_policy
    from manager.central_runtime import new_task_gate
    state = store.state_root()
    with runtime_policy.coordination(state):
        new_task_gate(state, project_root(root), binding)
        yield


def adapter_path(root: Path, requested: str | None, binding: dict | None) -> str:
    """中央模式只用项目适配器；源包保留 project.yaml 与显式旧安装路径。"""
    project_root(root)
    if binding is not None:
        if requested is not None and requested != CENTRAL_ADAPTER:
            raise RuntimePinError("中央初始化只能读取本项目 .agent-workflow/project.yaml")
        return CENTRAL_ADAPTER
    return requested if requested is not None else "project.yaml"


def task_pack_binding(path: Path, *, root: Path | None = None) -> dict | None:
    """安全读取当前单包的 pin；分页器无需加载调度器或信任结果回执自报的路径。

    此处只校验读取所需的 schema／单任务容器和版本身份，完整派发合同仍由原图入口
    负责；重复 JSON 字段、链接文件、缺 pin 或损坏版本均不进入正文读取。
    """
    body = read_file(Path(path).absolute())
    if body is None:
        raise RuntimePinError("当前 task-pack 不存在")
    pack = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
    if (not isinstance(pack, dict) or type(pack.get("schema_version")) is not int
            or pack["schema_version"] != 2 or not isinstance(pack.get("task"), dict)):
        raise RuntimePinError("task-pack 必须是 schema_version 2 的当前自包含包")
    return record_binding(pack, root=root)


@contextmanager
def _source_reader(binding: dict):
    """单次读取校验 pin/桥三根并锚定核心；不跨 catalog、指纹或提交阶段复用。"""
    with store.core_reader(store.validate_binding(binding)) as reader:
        # 仍走同一 pin、项目根、CORE_ENV/CONFIG_ENV 守卫；只消除原函数中
        # record_binding→load_core→read_core_source 三次验证同一核心的重复。
        record_binding({"runtime_binding": binding}, reader=reader)
        yield reader


def read_source(binding: dict, logical_path: str) -> bytes:
    """由严格 pin 读取清单内资源；不接受 Task Pack 自报的 core_root 或任意机器路径。"""
    with _source_reader(binding) as reader:
        return reader.read(reader.core, logical_path)


def read_builtin_source(binding: dict, path: str) -> bytes:
    """仅三份内置规范及其既有安装别名使用此分支，不能扩大普通 file_digest 权限。"""
    relative = builtin_source_path(path)
    if relative is None:
        raise RuntimePinError("不是精确的内置规范来源")
    return read_source(binding, relative)


def read_builtin_sources(binding: dict) -> dict[str, bytes]:
    """只读既有三份内置权威，不接受第二名单、任意 paths 或可调 CLI 预算。

    同一 catalog 内逐份核对原 manifest/hash/大小/mode/identity/security，
    最后整快照复核成功才返回。返回正文是本次消费者的原数据，不作跨调用
    缓存；validate/ready 两份 catalog 及初末指纹仍各自建立新鲜读取边界。
    """
    with _source_reader(binding) as reader:
        sources, total = {}, 0
        for path in BUILTIN_STANDARD_SOURCES:
            body = reader.read(reader.core, path)
            total += len(body)
            # 单份仍沿原128MiB读取限制；新增聚合返回值复用 store 既有批读
            # 总预算，不因固定三份就把一轮内存正文上限扩大成三倍。
            if total > store._SOURCE_BATCH_BYTES_LIMIT:
                raise RuntimePinError("固定内置源总正文超过核心批读预算")
            sources[path] = body
        return sources


def resource_path(path: Path, root: Path) -> str | None:
    """分类有界阅读的中央逻辑资源；配置、locator 和业务文件继续落在项目安全读取器。"""
    raw = path.as_posix()
    if path.is_absolute():
        try:
            raw = path.relative_to(root).as_posix()
        except ValueError:
            return None
    if raw.startswith(".agent-workflow/"):
        raw = raw[len(".agent-workflow/"):]
    parts = PurePosixPath(raw).parts
    if (not parts or raw != PurePosixPath(raw).as_posix() or "\\" in raw
            or ".." in parts or PurePosixPath(raw).is_absolute()):
        raise RuntimePinError("核心资源必须是规范逻辑路径")
    # 清单负责最终的精确资源授权；这里只接受受管命名空间，适配器永远不走核心。
    if parts[0] in store.CORE_DIRECTORIES or raw in store.SETUP_FILES:
        return raw
    return None
