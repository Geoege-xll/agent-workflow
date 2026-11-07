"""按本机项目身份和任务 pin 读取中央资源、解析 Python helper。

桥只读取已验证固定内容库，既不调度模型也不运行安装器。运行中的任务必须
逐次提供 pin；项目换版不能通过环境缺省把旧任务带到新核心。没有 pin 的入口
仅允许启用检查或显式 new_task 门，且克隆项目不能借可提交 locator 自动启用。
"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import signal
import subprocess
import sys

from lib import runtime_store as store
from .platform_fs import os
from lib.central.runtime_project import (
    CONFIG, LOCATOR, ProjectRuntimeError, Tree, canonical_project,
    json_bytes, relative_path, unique_json,
)


class RuntimeBridgeError(ProjectRuntimeError):
    """项目未启用、任务缺 pin，或中央资源已损坏。"""


@dataclass(frozen=True)
class RuntimeContext:
    state: Path
    project_root: Path
    config_path: Path
    core: store.FrozenCore

    @property
    def runtime_binding(self) -> dict:
        return self.core.binding()


@dataclass(frozen=True)
class HelperInvocation:
    """只解析命令与环境；生产调用方决定何时执行，不在导入/预览时启动进程。"""

    command: tuple[str, ...]
    environment: dict[str, str]
    cwd: Path
    runtime_binding: dict


def resolve_runtime(state: Path, project: Path, *, binding: dict | None = None,
                    new_task: bool = False) -> RuntimeContext:
    """严格校验 pin 并加载该项目曾用版本；新任务额外验证本机 enabled。

    参数 binding 优先于 AGENT_WORKFLOW_RUNTIME_BINDING。环境中的 project root
    只能作为一致性守卫，core/config 路径一律由可信记录推导，绝不采纳 Task Pack
    或项目文件提供的任意外部核心根。禁用不妨碍已有任务显式 pin 的必要读取。
    """
    from manager.runtime_service import read_binding_record, status
    if type(new_task) is not bool:
        raise RuntimeBridgeError("new_task 必须是显式布尔值")
    state, project = store.state_root(state), canonical_project(project)
    supplied_project = os.environ.get("AGENT_WORKFLOW_PROJECT_ROOT")
    if supplied_project is not None:
        try:
            matched = canonical_project(Path(supplied_project)) == project
        except (OSError, ValueError):
            matched = False
        if not matched:
            raise RuntimeBridgeError("helper 环境中的项目根不属于当前物理项目")
    _, record = read_binding_record(state, project)
    if record is None:
        raise RuntimeBridgeError("本项目尚未在本机启用工作流")
    if binding is None and "AGENT_WORKFLOW_RUNTIME_BINDING" in os.environ:
        try:
            binding = store.validate_binding(unique_json(os.environ["AGENT_WORKFLOW_RUNTIME_BINDING"].encode("utf-8")))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeBridgeError("helper 环境中的 runtime_binding 无效") from exc
    if binding is None:
        if not new_task:
            raise RuntimeBridgeError("中央任务缺少 runtime_binding；拒绝猜测当前项目版本")
        binding = record["runtime_binding"]
    binding = store.validate_binding(binding)
    if binding not in record["used_bindings"]:
        raise RuntimeBridgeError("任务 pin 不是当前物理项目曾经使用的中央版本")
    if new_task:
        checked = status(state, project)
        if not checked["enabled"]:
            raise RuntimeBridgeError("本项目未在本机启用或资源存在冲突，不能创建新任务")
        with Tree(project) as tree:
            locator = tree.read(LOCATOR)
        value = unique_json(locator.payload) if locator.kind == "file" else None
        if value != {"schema_version": 1, "kind": "central", "runtime_binding": record["runtime_binding"]}:
            raise RuntimeBridgeError("中央项目标记与本机当前绑定不一致")
    core = store.load_core(binding, state)
    return RuntimeContext(state, project, project / CONFIG, core)


def read_resource(state: Path, project: Path, logical_path: str, *, binding: dict | None = None) -> bytes:
    """读取任务固定核心的清单文件；不把普通业务文件改成可跟随链接的读取器。"""
    context = resolve_runtime(state, project, binding=binding)
    return store.read_core_source(context.core, logical_path)


def helper_path(state: Path, project: Path, logical_path: str, *, binding: dict | None = None,
                new_task: bool = False) -> Path:
    """解析一个已验证 lib/*.py；helper 必须来自固定核心而非项目外部路径。"""
    context = resolve_runtime(state, project, binding=binding, new_task=new_task)
    relative = logical_path[len(".agent-workflow/"):] if logical_path.startswith(".agent-workflow/") else logical_path
    relative_path(relative)
    if not relative.startswith("lib/") or not relative.endswith(".py"):
        raise RuntimeBridgeError("Python helper 只接受固定核心中的 lib/*.py 逻辑路径")
    store.read_core_source(context.core, relative)
    return context.core.root / relative


def python_helper(state: Path, project: Path, logical_path: str, args: tuple | list = (), *,
                  binding: dict | None = None, new_task: bool = False) -> HelperInvocation:
    """使用调用桥时已选择的受支持 Python，并为独立 helper 导出明确三根与 pin。

    薄入口沿既有 python_runtime.sh 选择解释器；这里只沿用 sys.executable，不
    硬编码 system python3 或旧 Homebrew keg。环境 pin 在每次 helper 执行时
    都重新生成；用户全局 PATH、模型、权限、MCP 与凭据不被改写或投影输出。
    """
    if (not isinstance(args, (tuple, list)) or not all(isinstance(arg, str) for arg in args)
            or any("\x00" in arg for arg in args)):
        raise RuntimeBridgeError("helper 参数必须是无 NUL 的字符串序列")
    relative = logical_path.removeprefix(".agent-workflow/")
    # 即使调用方忘了声明 new_task，统一任务初始化入口也不能绕过 enabled 门。
    initializes = relative in {"lib/task_graph_cli.py", "lib/task_graph_init.py"} and "init" in args
    context = resolve_runtime(state, project, binding=binding, new_task=new_task or initializes)
    relative_path(relative)
    if not relative.startswith("lib/") or not relative.endswith(".py"):
        raise RuntimeBridgeError("Python helper 必须位于固定核心的 lib 目录")
    store.read_core_source(context.core, relative)
    if sys.version_info < (3, 11):
        raise RuntimeBridgeError("中央 helper 需要沿既有入口选择 Python >= 3.11")
    env = dict(os.environ)
    env.update({"PYTHONDONTWRITEBYTECODE": "1",
                "AGENT_WORKFLOW_RUNTIME_BINDING": json.dumps(context.runtime_binding, sort_keys=True, separators=(",", ":")),
                "AGENT_WORKFLOW_STATE_DIR": str(context.state),
                "AGENT_WORKFLOW_PROJECT_ROOT": str(context.project_root),
                "AGENT_WORKFLOW_CONFIG_PATH": str(context.config_path),
                "AGENT_WORKFLOW_CORE_ROOT": str(context.core.root)})
    return HelperInvocation((sys.executable, "-B", "-X", "utf8", str(context.core.root / relative), *args),
                            env, context.project_root, context.runtime_binding)


def run_helper(invocation: HelperInvocation, *, timeout: float = 120) -> int:
    """只运行显式选定的 Python helper，并负责超时/中断后的进程资源回收。

    独立进程组只包含本次 helper 及其后代；中断不会 stop/kill 既有会话。先
    TERM 并等待至多 5 秒，再 KILL 并等待至多 5 秒，原失败继续向调用方传播。
    不重试未知结果，不吞掉 KeyboardInterrupt，也不把超时写成成功。
    """
    if not isinstance(invocation, HelperInvocation) or type(timeout) not in {int, float} or not 0 < timeout <= 3600:
        raise RuntimeBridgeError("helper 需要有效调用值及 0..3600 秒的有限超时")
    if os.name == "nt":
        raise RuntimeBridgeError("当前中央 helper 缺少已验证的 Windows 进程组后端")
    child = subprocess.Popen(invocation.command, cwd=invocation.cwd, env=invocation.environment,
                             start_new_session=True)
    try:
        return child.wait(timeout=timeout)
    except BaseException as failure:
        try:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        finally:
            # shell/Python 父进程可先响应 TERM，而孙进程可能忽略它；即使父已退
            # 出也要回收本次独立进程组，不能以父进程 wait 成功冒充后代已停止。
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired as cleanup_error:
                raise RuntimeBridgeError("Python helper 已请求停止，但尚未确认回收") from cleanup_error
        if isinstance(failure, subprocess.TimeoutExpired):
            raise RuntimeBridgeError("Python helper 已超时并终止本次调用") from failure
        raise


def main(argv: list[str] | None = None, *, project: Path | None = None, state: Path | None = None) -> int:
    """供项目薄入口使用；所有核心选择仍走上方相同服务合同。"""
    parser = argparse.ArgumentParser(description="中央项目资源桥；不运行 Agent")
    parser.add_argument("--binding", help="任务固定的三字段 JSON；优先于环境 pin")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("check")
    reader = commands.add_parser("read")
    reader.add_argument("logical_path")
    helper = commands.add_parser("helper")
    helper.add_argument("logical_path")
    helper.add_argument("args", nargs=argparse.REMAINDER)
    selected = parser.parse_args(argv)
    project = canonical_project(project if project is not None else Path.cwd())
    state = store.state_root(state)
    try:
        binding = store.validate_binding(unique_json(selected.binding.encode())) if selected.binding is not None else None
        if selected.action == "check":
            context = resolve_runtime(state, project, binding=binding, new_task=True)
            sys.stdout.buffer.write(json_bytes({"enabled": True, "project": str(project), "runtime_binding": context.runtime_binding}))
            return 0
        if selected.action == "read":
            sys.stdout.buffer.write(read_resource(state, project, selected.logical_path, binding=binding))
            return 0
        args = selected.args[1:] if selected.args[:1] == ["--"] else selected.args
        invocation = python_helper(state, project, selected.logical_path, args, binding=binding)
        return run_helper(invocation)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
