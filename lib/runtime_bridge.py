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
from contextlib import contextmanager, nullcontext
import ast
from dataclasses import dataclass
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import time

from lib import runtime_store as store
from .platform_fs import os
from lib.central.runtime_project import (
    CONFIG, LOCATOR, ProjectRuntimeError, Tree, canonical_project,
    json_bytes, relative_path, unique_json,
)


# current控制器负责全局待结算门和初始化协调；该资格与选版helper是否自行持
# 发布锁完全独立。旧core仍可作为任务pin读取，但不能凭旧enabled检查接管current。
CENTRAL_CONTROL_PROTOCOL = 1
# 该能力只声明固定reader能消费中央after条件守卫，不授予执行/新任务权限。
CENTRAL_AFTER_GUARD_PROTOCOL = 1


class RuntimeBridgeError(ProjectRuntimeError):
    """项目未启用、任务缺 pin，或中央资源已损坏。"""


def controller_protocol(core: store.FrozenCore, *, reader=None) -> int:
    """静态读取已验证core的控制资格，不import或执行候选bridge探测能力。

    清单验证只证明字节身份，不能证明旧bridge具有新中央门禁。声明必须是唯一
    顶层字面整数；缺失或0表示无资格，1支持，其余值/动态/重复赋值失败关闭。
    连嵌套或删除写入也计入，不能在一个表面合法声明后偷偷重赋协议常量。
    """
    return _static_protocol(core, "CENTRAL_CONTROL_PROTOCOL", reader=reader)


def after_guard_protocol(core: store.FrozenCore, *, reader=None) -> int:
    """从已验证固定core读取after格式能力；未知/动态声明不能降级成旧能力。"""
    return _static_protocol(core, "CENTRAL_AFTER_GUARD_PROTOCOL", reader=reader)


def _static_protocol(core: store.FrozenCore, name: str, *, reader=None, logical_path="lib/runtime_bridge.py") -> int:
    # 两项独立协议共用原静态语法边界；不执行候选模块、不读版本号或用户环境。
    if reader is not None and not isinstance(reader, store.CoreReadSession):
        raise RuntimeBridgeError("控制协议拒绝未知核心 reader")
    if reader is not None and not reader.contains(logical_path):
        return 0
    body = reader.read(core, logical_path) if reader is not None else store.read_core_source(core, logical_path)
    try:
        module = ast.parse(body)
    except (SyntaxError, ValueError) as exc:
        raise RuntimeBridgeError("所选核心中央控制协议无效") from exc
    declarations = []
    writes = [node for node in ast.walk(module) if isinstance(node, ast.Name)
              and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))]
    # Python的def/class/import及异常/模式绑定把名字保存在节点字段，未必产生
    # Name(Store)。这些明确重绑定同样破坏“唯一字面声明”，不能漏成合法资格。
    # 此处只校验协议声明语法；真正加载桥后仍由薄入口核验实际module值。
    other_writes = [node for node in ast.walk(module)
                    if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler,
                                         ast.MatchAs, ast.MatchStar)) and node.name == name)
                    or (isinstance(node, ast.MatchMapping) and node.rest == name)
                    or (isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name)]
    for statement in module.body:
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            declarations.append(statement.value)
    if not declarations and not writes and not other_writes:
        return 0
    if (other_writes or len(writes) != 1 or len(declarations) != 1 or not isinstance(declarations[0], ast.Constant)
            or type(declarations[0].value) is not int or declarations[0].value not in {0, 1}):
        raise RuntimeBridgeError("所选核心声明了未知、动态或重复的中央控制协议")
    return declarations[0].value


def helper_creates_task(logical_path: str, args: tuple | list) -> bool:
    """识别实际CLI command，不把参数值init误当初始化，也不漏掉前置选项。

    这份自举语法与task_graph_cli._parser的已发布参数合同相同；薄launcher在
    核心验证前无法import parser，使用相同静态协议。未知/歧义选项失败关闭，
    唯一前缀沿argparse默认行为解析；正式参数验证仍由选版helper自身完成。
    """
    relative = logical_path.removeprefix(".agent-workflow/")
    if relative == "lib/task_graph_init.py":
        return True
    if relative != "lib/task_graph_cli.py":
        return False
    return _task_graph_command(args) == "init"


def _task_graph_command(args):
    """沿原helper静态参数协议选command；不能把选项值当作runner能力。"""
    class AdmissionParser(argparse.ArgumentParser):
        def error(self, message):
            # 参数可能含私有路径或payload，不回显argparse原始诊断。
            raise RuntimeBridgeError("任务图helper参数无效或存在歧义")
    parser = AdmissionParser(add_help=False)
    parser.add_argument("command", nargs="?", choices=("validate", "ready", "qa-ready", "capacity", "init", "update", "task", "fingerprints", "scratch", "cleanup-scratch", "continuation"))
    for option in ("--input", "--patch", "--expect-sha256", "--task-id", "--host", "--observed-state",
                   "--output", "--root", "--select", "--request-id", "--keep"):
        parser.add_argument(option)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    selected = parser.parse_args(args)
    if selected.help:
        return None
    if selected.command is None:
        raise RuntimeBridgeError("任务图helper缺少command")
    return selected.command


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
    initializes: bool = False
    admission_protocol: int | None = None


@contextmanager
def _runtime_context(state: Path, project: Path, *, binding: dict | None = None,
                     new_task: bool = False, reader=None):
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
    # 只读解析与成员消费共用显式 reader；离开调用栈即关闭，不能随
    # RuntimeContext/HelperInvocation 返回，执行或发布阶段必须另行 fresh。
    if reader is not None and not isinstance(reader, store.CoreReadSession):
        raise RuntimeBridgeError("运行时拒绝未知核心 reader")
    with (store.core_reader(binding, state) if reader is None else nullcontext(reader)) as reader:
        # 只能复用本调用栈显式传入且属于同state/pin的活跃证明；关闭、错误
        # state/pin或伪造对象一律拒绝，不把复用失败悄悄降级成另一版本读取。
        reader.core_for(binding, state)
        if new_task:
            from manager.central_runtime import new_task_gate
            binding = new_task_gate(state, project, binding, reader=reader)
            checked = status(state, project, reader=reader)
            if not checked["enabled"]:
                raise RuntimeBridgeError("本项目未在本机启用或资源存在冲突，不能创建新任务")
            with Tree(project) as tree:
                locator = tree.read(LOCATOR)
            value = unique_json(locator.payload) if locator.kind == "file" else None
            if value != {"schema_version": 1, "kind": "central", "runtime_binding": record["runtime_binding"]}:
                raise RuntimeBridgeError("中央项目标记与本机当前绑定不一致")
        yield RuntimeContext(state, project, project / CONFIG, reader.core), reader


def hook_response(state: Path, project: Path, arguments, payload: bytes, *,
                  binding: dict | None = None, reader=None) -> dict:
    """在一次中央只读调用栈内执行固定 Hook；失败由薄入口转换为中性响应。

    无pin仍走原新任务准入/状态/locator检查，有pin保持原used_bindings约束。
    仅消费固定lib/workflow_hooks.py，不能成为任意helper的进程内执行开关。
    返回值尚未发布；调用方须等最外层reader结束整树重验后再打印JSON。
    """
    from manager.runtime_service import read_binding_record
    supplied_deadline = os.environ.get("AGENT_WORKFLOW_HOOK_DEADLINE")
    deadline = time.monotonic() + 3 if supplied_deadline is None else float(supplied_deadline)
    if not math.isfinite(deadline) or deadline <= time.monotonic():
        raise RuntimeBridgeError("Hook 截止时间无效或已过期")
    state, project = store.state_root(state), canonical_project(project)
    if not isinstance(arguments, (tuple, list)) or any(not isinstance(value, str) or "\0" in value for value in arguments):
        raise RuntimeBridgeError("Hook 参数必须是无NUL的字符串序列")
    if binding is None and "AGENT_WORKFLOW_RUNTIME_BINDING" in os.environ:
        binding = store.validate_binding(unique_json(os.environ["AGENT_WORKFLOW_RUNTIME_BINDING"].encode("utf-8")))
    unpinned = binding is None
    _, record = read_binding_record(state, project)
    if record is None:
        raise RuntimeBridgeError("本项目尚未在本机启用工作流")
    if not record["enabled"]:
        # 停用不影响旧任务普通read/helper；辅助Hook本身已退出宿主注册，
        # 即使旧进程仍持有曾用pin也不继续注入提醒，更不因此重新启用项目。
        raise RuntimeBridgeError("停用项目不执行辅助Hook")
    selected = store.validate_binding(record["runtime_binding"] if unpinned else binding)
    scoped_reader = None
    if reader is not None:
        if not isinstance(reader, store.CoreReadSession):
            raise RuntimeBridgeError("Hook 拒绝未知核心 reader")
        reader.core_for(reader.core.binding(), state)
        if reader.core.binding() == selected:
            scoped_reader = reader
        else:
            from manager.runtime_policy import current_snapshot
            _, current = current_snapshot(state)
            if not unpinned or current is None:
                raise RuntimeBridgeError("Hook reader 不属于目标固定版本")
            # 只有真实current控制器与项目固定旧版本不同才允许双会话；任意
            # 其他版本的reader仍明确拒绝，不能借这个分支静默fallback。
            reader.core_for(current["runtime_binding"], state)
        # current控制器与项目固定旧版本可能不同；这时明确为目标版本建立新
        # 会话，current会话继续由外层持有。绝不把外层对象冒充旧pin的证明。
    with _runtime_context(state, project, binding=selected, new_task=unpinned,
                          reader=scoped_reader) as (context, source):
        relative = "lib/workflow_hooks.py"
        body = source.read(context.core, relative)
        # 新接口只接受明确声明数据响应入口的固定Hook；旧自包含脚本缺能力
        # 时安全拒绝，不先执行它的顶层代码，更不猜一个current替代其版本。
        if not any(isinstance(node, ast.FunctionDef) and node.name == "command_response"
                   for node in ast.parse(body).body):
            raise RuntimeBridgeError("固定核心不支持单调用栈Hook")
        if context.core.root != Path(__file__).resolve().parents[1]:
            # 控制器和目标pin不同，进程内lib已属于控制器，不能让旧Hook借用
            # 新解析器/平台依赖。复用既有精确helper与Job/进程组启动目标解释器，
            # 父会话继续持有并在结束时重验；不向child传reader或跳验标记。
            from lib.install.install_process import capture_process, SetupRunError
            invocation = python_helper(state, project, relative, arguments, binding=selected, reader=source)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeBridgeError("Hook 预算已耗尽，未启动目标版本")
            try:
                captured = capture_process(list(invocation.command), env=invocation.environment,
                                           body=payload, timeout=remaining)
            except (OSError, subprocess.SubprocessError, SetupRunError) as exc:
                # 进程拥有者已按原合同回收子树；这里只把有限捕获失败交给最外
                # Hook边界转中性，不吞中断、不回显目标脚本或payload的错误原文。
                raise RuntimeBridgeError("固定目标Hook未完成") from exc
            if captured.returncode != 0:
                raise RuntimeBridgeError("固定目标Hook执行失败")
            result = unique_json(captured.stdout)
            if not isinstance(result, dict):
                raise RuntimeBridgeError("固定Hook返回了未知响应类型")
            return result
        namespace = {"__name__": "_workflow_hook_response", "__file__": str(context.core.root / relative),
                     "__package__": "lib"}
        exec(compile(body, namespace["__file__"], "exec"), namespace)
        command_response = namespace.get("command_response")
        if not callable(command_response):
            raise RuntimeBridgeError("固定核心不支持单调用栈Hook")
        result = command_response(arguments, payload, project=context.project_root)
        if not isinstance(result, dict):
            raise RuntimeBridgeError("固定Hook返回了未知响应类型")
        return result


def resolve_runtime(state: Path, project: Path, *, binding: dict | None = None,
                    new_task: bool = False) -> RuntimeContext:
    """公开解析返回不可变定位值；不泄漏或持久保留活跃权限证明。"""
    with _runtime_context(state, project, binding=binding, new_task=new_task) as (context, reader):
        return context


def read_resource(state: Path, project: Path, logical_path: str, *, binding: dict | None = None) -> bytes:
    """读取任务固定核心的清单文件；不把普通业务文件改成可跟随链接的读取器。"""
    with _runtime_context(state, project, binding=binding) as (context, reader):
        return reader.read(context.core, logical_path)


def helper_path(state: Path, project: Path, logical_path: str, *, binding: dict | None = None,
                new_task: bool = False) -> Path:
    """解析一个已验证 lib/*.py；helper 必须来自固定核心而非项目外部路径。"""
    with _runtime_context(state, project, binding=binding, new_task=new_task) as (context, reader):
        relative = logical_path[len(".agent-workflow/"):] if logical_path.startswith(".agent-workflow/") else logical_path
        relative_path(relative)
        if not relative.startswith("lib/") or not relative.endswith(".py"):
            raise RuntimeBridgeError("Python helper 只接受固定核心中的 lib/*.py 逻辑路径")
        reader.read(context.core, relative)
        return context.core.root / relative


def python_helper(state: Path, project: Path, logical_path: str, args: tuple | list = (), *,
                  binding: dict | None = None, new_task: bool = False, reader=None) -> HelperInvocation:
    """使用调用桥时已选择的受支持 Python，并为独立 helper 导出明确三根与 pin。

    薄入口沿既有 python_runtime.sh 选择解释器；这里只沿用 sys.executable，不
    硬编码 system python3 或旧 Homebrew keg。环境 pin 在每次 helper 执行时
    都重新生成；用户全局 PATH、模型、权限、MCP 与凭据不被改写或投影输出。
    reader仅供同一父调用栈的只读准备复用，默认仍新建会话；返回值不携带
    reader，也不向child传跳验标志，目标解释器仍经过既有精确脚本启动边界。
    """
    if (not isinstance(args, (tuple, list)) or not all(isinstance(arg, str) for arg in args)
            or any("\x00" in arg for arg in args)):
        raise RuntimeBridgeError("helper 参数必须是无 NUL 的字符串序列")
    relative = logical_path.removeprefix(".agent-workflow/")
    # 即使调用方忘了声明 new_task，统一任务初始化入口也不能绕过 enabled 门。
    initializes = helper_creates_task(relative, args)
    with _runtime_context(state, project, binding=binding, new_task=new_task or initializes,
                          reader=reader) as (context, reader):
        relative_path(relative)
        if not relative.startswith("lib/") or not relative.endswith(".py"):
            raise RuntimeBridgeError("Python helper 必须位于固定核心的 lib 目录")
        reader.read(context.core, relative)
        if sys.version_info < (3, 11):
            raise RuntimeBridgeError("中央 helper 需要沿既有入口选择 Python >= 3.11")
        env = dict(os.environ)
        env.update({"PYTHONDONTWRITEBYTECODE": "1",
                    "AGENT_WORKFLOW_RUNTIME_BINDING": json.dumps(context.runtime_binding, sort_keys=True, separators=(",", ":")),
                    "AGENT_WORKFLOW_STATE_DIR": str(context.state),
                    "AGENT_WORKFLOW_PROJECT_ROOT": str(context.project_root),
                    "AGENT_WORKFLOW_CONFIG_PATH": str(context.config_path),
                    "AGENT_WORKFLOW_CORE_ROOT": str(context.core.root)})
        protocol = _admission_protocol(context.core, reader=reader) if initializes else None
        selected_relative, selected_args = relative, args
        if (relative == "lib/task_graph_cli.py" and _task_graph_command(args) in {"validate", "ready", "update"}
                and _static_protocol(context.core, "CORE_READ_OPERATION_PROTOCOL", reader=reader,
                                     logical_path="lib/runtime_pins.py") == 1):
            # 只选择目标原core明确声明的固定runner。父方逐份消费原启动闭包，
            # child仍独立验证整树，不传reader/validated标志或任意代码字符串。
            closure = ["lib/runtime_pins.py", "lib/runtime_store.py", "lib/platform_fs.py", "lib/__init__.py"]
            if os.name == "nt":
                closure.append("lib/windows_fs.py")
            for member in closure:
                reader.read(context.core, member)
            selected_relative, selected_args = "lib/runtime_pins.py", ("--task-graph-operation", *args)
        if os.name == "nt":
            # 通用 bootstrap 只为已经 load_core 验证的固定 helper 增加其 core/lib。
            # 项目薄 Hook 使用另一份不插目录的小入口；二者不能混用搜索路径合同。
            reader.read(context.core, "lib/windows_bootstrap.py")
            command = (sys.executable, "-I", "-B", "-X", "utf8", str(context.core.root / "lib/windows_bootstrap.py"),
                       "--script", str(context.core.root / selected_relative), *selected_args)
        else:
            command = (sys.executable, "-B", "-X", "utf8", str(context.core.root / selected_relative), *selected_args)
        return HelperInvocation(command, env, context.project_root, context.runtime_binding, initializes, protocol)


def _admission_protocol(core: store.FrozenCore, *, reader=None) -> int:
    """只从清单校验过的 init 源码取静态能力，绝不执行代码探测或信任环境旗标。"""
    if reader is not None and not isinstance(reader, store.CoreReadSession):
        raise RuntimeBridgeError("准入协议拒绝未知核心 reader")
    body = reader.read(core, "lib/task_graph_init.py") if reader is not None else store.read_core_source(core, "lib/task_graph_init.py")
    try:
        module = ast.parse(body)
    except (SyntaxError, ValueError) as exc:
        raise RuntimeBridgeError("所选核心任务初始化协议无效") from exc
    declarations = []
    writes = [node for node in ast.walk(module) if isinstance(node, ast.Name)
              and node.id == "CENTRAL_ADMISSION_PROTOCOL" and isinstance(node.ctx, (ast.Store, ast.Del))]
    for statement in module.body:
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == "CENTRAL_ADMISSION_PROTOCOL" for target in targets):
            declarations.append(statement.value)
    if not declarations and not writes:
        return 0
    if (len(writes) != 1 or len(declarations) != 1 or not isinstance(declarations[0], ast.Constant)
            or type(declarations[0].value) is not int or declarations[0].value != 1):
        raise RuntimeBridgeError("所选核心声明了未知或重复的任务初始化协议")
    return 1


def run_helper(invocation: HelperInvocation, *, timeout: float = 120) -> int:
    """只运行显式选定的 Python helper，并负责超时/中断后的进程资源回收。

    Windows 在首条指令前加入自有 Job，停止后确认后代归零；POSIX 沿用独立
    进程组的 TERM/KILL 收尾。中断不影响既有会话，不重试未知结果，不吞掉
    KeyboardInterrupt，也不把超时写成成功。
    """
    if not isinstance(invocation, HelperInvocation) or type(timeout) not in {int, float} or not 0 < timeout <= 3600:
        raise RuntimeBridgeError("helper 需要有效调用值及 0..3600 秒的有限超时")
    # Hook 监督者设定的同机单调截止时间覆盖整个薄桥链。控制/准入判断仍在
    # 原位置完成，只有最终执行等待取剩余量，不放宽旧 pin 或跨进程锁协议。
    supplied_deadline = invocation.environment.get("AGENT_WORKFLOW_HOOK_DEADLINE")
    if supplied_deadline is not None:
        try:
            deadline = float(supplied_deadline)
        except (ValueError, TypeError) as exc:
            raise RuntimeBridgeError("Hook 截止时间无效") from exc
        if not math.isfinite(deadline):
            raise RuntimeBridgeError("Hook 截止时间无效")
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            raise RuntimeBridgeError("Python helper 已超时，未启动下一阶段")
    if invocation.initializes and invocation.admission_protocol == 0:
        from manager import runtime_policy
        from manager.central_runtime import new_task_gate
        state = Path(invocation.environment["AGENT_WORKFLOW_STATE_DIR"])
        # 旧核心没有 child 发布锁，当前控制桥在相同短协调域内重验并执行其原
        # helper。只涵盖机械 init，不执行模型；新协议 child 自持锁，parent
        # 不能跨进程重入，否则会把合法初始化锁成死锁。
        with runtime_policy.coordination(state):
            new_task_gate(state, invocation.cwd, invocation.runtime_binding)
            return _execute_helper(invocation, timeout)
    if invocation.initializes and invocation.admission_protocol != 1:
        raise RuntimeBridgeError("初始化 helper 缺少明确的协调锁协议")
    return _execute_helper(invocation, timeout)


def _execute_helper(invocation: HelperInvocation, timeout: float) -> int:
    """执行已通过门禁的固定 helper，超时清理沿用原进程组所有权边界。"""
    if os.name == "nt":
        deadline = time.monotonic() + timeout
        from lib.install.windows_process import WindowsJobProcess, _defer_interrupts
        child = None
        try:
            with _defer_interrupts():
                child = WindowsJobProcess(invocation.command, cwd=invocation.cwd, env=invocation.environment)
            return child.wait(timeout=max(0, deadline - time.monotonic()))
        except BaseException as failure:
            if child is not None:
                child.stop()
            if isinstance(failure, subprocess.TimeoutExpired):
                raise RuntimeBridgeError("Python helper 已超时并终止本次调用") from failure
            raise
        finally:
            if child is not None:
                child.close()
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
    parser = argparse.ArgumentParser(description="中央项目资源桥；不运行 Agent", allow_abbrev=False)
    class UniquePin(argparse.Action):
        def __call__(self, parser, namespace, value, option_string=None):
            if getattr(namespace, self.dest, None) is not None:
                raise argparse.ArgumentError(self, "duplicate runtime binding")
            setattr(namespace, self.dest, value)
    pins = parser.add_mutually_exclusive_group()
    pins.add_argument("--binding", action=UniquePin, help="任务固定的三字段 JSON；优先于环境 pin")
    pins.add_argument("--binding-b64", action=UniquePin, help="规范 base64 三字段 JSON，解码正文最多4KiB")
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
        from lib.runtime_pins import decode_binding_b64
        binding = (decode_binding_b64(selected.binding_b64) if selected.binding_b64 is not None else
                   store.validate_binding(unique_json(selected.binding.encode())) if selected.binding is not None else None)
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
