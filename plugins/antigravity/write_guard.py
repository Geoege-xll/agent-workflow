"""AGY PreToolUse 在默认权限检查之前核对主会话与原生实现者的写入分工。"""

import json
import os
from functools import cached_property
from pathlib import Path
import re
import shlex
import stat
import sys


# -I 排除项目 cwd/PYTHONPATH；运行时只从这份已安装插件导入共用的任务池及协议。
PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import task_graph_records as records, task_pool
from lib.hosts import antigravity_dispatch as native
from lib.qa_projection import projection_kind
from lib.safe_text import open_file, read_file
from lib.validate_project_docs import project_docs_layout
from guard_command import check_runner, command_allowed


DENY = ("xy-workflow：请从当前插件 skills/xy-workflow/references/dispatch.md 的完整任务包开始，"
        "用包内 lib/task_pool_cli.py claim --register 领取，把回执的 dispatch_marker 独占一行放进 "
        "invoke_subagent 的初始 Prompt，取得 conversationId 后用同一回执 pool bind。"
        "PM 可用原生 read_file、受控计划和请求 scratch 继续准备或验证。")
AGENT_DIRS = {".git", ".agents", ".agent", ".antigravity", ".awf", ".gemini", ".codex", ".claude"}
EDIT_TOOLS = {"edit_file": "Path", "write_file": "Path", "write_to_file": "TargetFile",
              "replace_file_content": "TargetFile", "multi_replace_file_content": "TargetFile"}


def physical(value, base):
    """写入以真实路径和节点类型为准；拒绝借符号链接、硬链接或设备改写另一个对象。"""
    if not isinstance(value, str) or not value or "\0" in value or ".." in Path(value).parts:
        raise ValueError("无法识别写入路径")
    path = base / value
    # macOS 的 /tmp、/var 是系统别名。调用方须传宿主报告的物理路径；
    # 不能先 resolve 再丢掉项目内符号链接这条关键信息。
    if not path.is_absolute() or any(node.is_symlink() for node in (path, *path.parents)):
        raise ValueError("需要无链接的物理路径")
    try:
        info = path.stat()
    except FileNotFoundError:
        return path
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
        raise ValueError("写入目标不是独立普通文件或目录")
    return path


def session_origin(event):
    """身份只读宿主指定会话的首条原生事件，首条工具输出或普通聊天均不能充当派发。"""
    current = event["conversationId"]
    native.parent_id("antigravity:" + current)
    directory = native._brain() / current / ".system_generated/logs"
    path = Path(event["transcriptPath"])
    if path not in (directory / "transcript_full.jsonl", directory / "transcript.jsonl"):
        raise ValueError("缺少当前 AGY CLI 会话来源")
    with open_file(path) as stream:
        if stream is None:
            raise ValueError("宿主尚未写入会话来源")
        first = json.loads(stream.readline(8 * 1024 * 1024))
    if first.get("step_index") != 0 or first.get("status") != "DONE":
        raise ValueError("缺少原生首条消息")
    if (first.get("type"), first.get("source")) == ("USER_INPUT", "USER_EXPLICIT"):
        return current, None, None
    if (first.get("type"), first.get("source")) != ("SYSTEM_MESSAGE", "SYSTEM"):
        raise ValueError("无法识别原生派发身份")
    header = re.search(r"\n<SYSTEM_MESSAGE>\n\[Message\] timestamp=\S+ sender=(\S+) priority=\S+ content=", first["content"])
    if not header:
        raise ValueError("缺少原生派发来源")
    parent = native.parent_id("antigravity:" + header[1])
    native.validate_child_id(parent, current)
    lines = first["content"][header.end():].splitlines()
    markers = [line for line in lines if line.startswith("XY-WORKFLOW-CLAIM ")]
    return current, parent, markers[0] if len(markers) == 1 else None


def inventory(root, parent):
    # 沿用当前 PM 的唯一索引、原件和绑定校验。只读现存槽，绝不靠目录扫描猜任务，
    # 也不在 Hook 内首次领取/绑定。释放池锁后才去核对较长的原生派发日志。
    with task_pool._index(root, "antigravity:" + parent, create=False) as (_, data):
        snapshots, errors = task_pool._read_pool(root, data["records"])
        if errors:
            raise ValueError("已登记任务原件需要核对")
    return snapshots


def project_candidates(workspace):
    yield workspace
    # Git 的 linked worktree 在主 checkout 的任务池登记。只认相互指回的 Git 元数据，
    # 随后还要核对池内固定的执行根、当前领取以及原生回执里的 workspace URI。
    gitfile = workspace / ".git"
    if not gitfile.is_file():
        return
    text = (read_file(gitfile) or b"").decode().strip()
    if not text.startswith("gitdir: "):
        return
    slot = (workspace / text[8:]).resolve(strict=True)
    if slot.parent.name == "worktrees" and slot.parent.parent.name == ".git":
        back = (read_file(slot / "gitdir") or b"").decode().strip()
        if (slot / back).resolve(strict=True) == gitfile:
            yield slot.parent.parent.parent


def child_task(roots, current, parent, marker):
    if not marker:
        return None
    for workspace in roots:
        for project in project_candidates(workspace):
            for snap in inventory(project, parent):
                for task in snap.tasks:
                    if (task.get("state") != "RUNNING" or task.get("agent_retired") or task.get("withdrawal")
                            or task.get("task_type") != "writer" or task.get("role") == "xy-qa"
                            or snap.descriptor["execution_roots"][task["id"]] != str(workspace)):
                        continue
                    claim = task.get("antigravity_claim", {})
                    if claim.get("parent") != parent:
                        continue
                    target = {"record": snap.descriptor["path"], "request_id": task["request_id"], "task_id": task["id"]}
                    if native.dispatch_marker(project, target, task["claim_basis_sha256"], claim) != marker:
                        continue
                    reference = task.get("agent_ref")
                    if reference is not None and reference != {"host": "antigravity", "agent_id": current}:
                        continue
                    # 原件可以由 PM 的本地文件工具写入，其中的 ID 本身不能证明角色。
                    # 绑定前后都复核原生创建来源；既有绑定只进一步排除其他实例。
                    native.verify_creation(parent, current, workspace, marker, task["role"])
                    return workspace, task
    return None


def managed_path(relative):
    # 常见 macOS 卷不区分大小写；.GIT / .Agents 等大小写变体指向同一实体。
    return any(part.casefold() in AGENT_DIRS for part in relative.parts)


# 只匹配用户当前直陈的指令句首。代码块、引用、否定、条件和反问不能变成
# “亲自改”的授权；没有点名文件的独立续句仅在当前轮、单工作区内生效。
PM_DIRECTIVE = re.compile(
    r"^(?:本次|本轮|这次|这一轮|这次任务)?\s*(?:请|要求|允许|授权|指定)?\s*(?:由|让)?\s*"
    r"(?:当前)?(?:AGY\s*)?(?:主会话|主代理|PM)\s*(?:本人|自己|亲自)\s*(?:来|直接|亲自)?\s*"
    r"(?:修改|改动|改|实现|实施|修复|编辑|写入|完成)(?P<scope>.*)$", re.I)
# 一个目标可以没有扩展名，也可以是中文名；英文引号或反引号可包住有空格的路径。
# 所有结果仍须与本次工具调用的具体物理目标相等，不能把无法解析的正文当作整项目授权。
TARGET_NAME = re.compile(r"[\w@+=./-]+(?: [\w@+=./-]+)*")
WHOLE_TASK = {"", "这个任务", "本次任务", "当前任务", "这项任务", "这次改动"}


def pm_directive(message):
    if not isinstance(message, str) or not message.strip():
        return None
    lines = message.strip().splitlines()
    first = lines[0].strip()
    # 首行必须是用户直接指定执行者。引用、条件和问句都不生成授权；把换行当成
    # 后续说明的边界，这样正常的测试步骤、示例输出中的引号不影响肯定的首句。
    if re.search(r"如果|假如|例如|举例|示例|这句话|这句指令|禁止|是否|能否|吗|的话|前提|除外|[？?]", first):
        return None
    if re.search(r"不要(?:让|由|改|修|编|执)|不(?:许|准|得|允许|授权|是)|禁止(?:修改|执行)|"
                 r"(?m:^[ \t]*(?:仅当|仅在|前提是|除非|这只是示例|取消(?:授权|修改)))", message):
        return None
    # 后面的测试说明也可能限定本次修改的生效条件。只有条件指向修改动作时
    # 才阻止执行；“如果测试失败，请报告结果”仍是对测试反馈的正常要求。
    if re.search(r"(?:如果|假如|若|只有|仅当|仅在|除非|前提是)[^。！？!?]*"
                 r"(?:修改|改动|编辑|写入|实施|动手|(?:再|才)改)|"
                 r"(?:才|方可)(?:能|可以|开始)?(?:改|编辑|写入|实施|动手)",
                 "\n".join(lines[1:])):
        return None
    return PM_DIRECTIVE.fullmatch(first)


def explicit_scope(message, root, target, *, single_root):
    match = pm_directive(message)
    if not match:
        return False
    # 只采动词直接指向的一组文件。诸如“参考 b.py”和第二行测试命令不会变成业务写目标。
    scope = re.sub(r"^\s*(?:目标文件|目标|文件)\s*[:：]\s*", "", match["scope"])
    subject = re.split(r"[，,。！!；;：:]|(?:并且|并|再|然后|同时)\s*(?:运行|执行|验证|测试|跑)"
                       r"|\s+(?:参考|参照|将)", scope, maxsplit=1)[0].strip()
    lines = message.strip().splitlines()
    if not subject and len(lines) > 1:
        # “文件：”是标签，“文件管理.py”则是完整文件名。缺少明确分隔时
        # 原样核对，尤其不能把前缀去掉后授权另一个文件。
        subject = re.sub(r"^(?:目标文件|目标|仅修改|只修改|文件)\s*[:：]\s*", "", lines[1].strip()).strip("。")
    if subject in WHOLE_TASK:
        # 无目标的独立续句仍可执行；含额外范围说明时不能把未解析内容放大到整个工作区。
        return single_root and match["scope"].strip(" 。！!，,") in WHOLE_TASK and len(message.strip().splitlines()) == 1
    names = []
    # 仅以明确的列举标点分项。和、与、以及或“文件”均可出现在合法文件名中，
    # 不将它们当分隔符，也不截去中文前缀。
    for raw in subject.split("、"):
        name = raw.strip()
        if len(name) >= 2 and (name[0], name[-1]) in {("`", "`"), ('"', '"'), ("'", "'"), ("“", "”")}:
            name = name[1:-1]
        if not TARGET_NAME.fullmatch(name) or name in {".", ".."} or ".." in Path(name).parts:
            return False
        names.append(name)
    return any(root / name == target for name in names)


class Access:
    def __init__(self, event):
        self.roots = [Path(path).resolve(strict=True) for path in event["workspacePaths"]]
        if not all(p.is_dir() for p in self.roots):
            raise ValueError("缺少项目根")
        self.current, self.parent, self.marker = session_origin(event)
        self.message = event.get("lastUserInput")
        self.transcript = Path(event["transcriptPath"])
        self.artifacts = native._brain() / self.current
        # 实机顶层 cwd 是 Hook 自身的插件目录。工具省略 Cwd 时，单工作区才有
        # 可确定的相对路径基准；多工作区的绝对文件操作仍可正常核对。
        self.cwd = self.roots[0] if len(self.roots) == 1 else None

    @cached_property
    def task(self):
        # 读取与核验不依赖绑定时序。只有要写入或执行任务登记的命令时，才进池
        # 核对角色、回执与所有权；QA 的正常只读取证不受忙锁或创建回执延迟影响。
        return child_task(self.roots, self.current, self.parent, self.marker) if self.parent else None

    def scratch_file(self, path):
        path = physical(str(path), Path("/"))
        for root in self.roots:
            # 新领取使用项目内交接槽，让原生工具在默认沙箱内可读写。已在途原件
            # 也可通过原系统临时槽完成交接；不枚举、不迁移、不修改原有任务池。
            for base in (root / records.AGY_HANDOFF, records._project_scratch_base(root)):
                if path.is_relative_to(base):
                    parts = path.relative_to(base).parts
                    return (len(parts) >= 2 and records.SCRATCH_SLOT_RE.fullmatch(parts[0])
                            and (base / parts[0]).is_dir() and not any(p.startswith(".") for p in parts)
                            and path.suffix in {".json", ".jsonl", ".md", ".txt", ".log", ".patch", ".diff"})
        return False

    def can_write(self, raw, cwd=None):
        base = cwd or self.cwd
        if base is None and not Path(raw).is_absolute():
            return False
        path = physical(raw, base or Path("/"))
        if self.parent:
            if self.task is None:
                return False
            root, task = self.task
            if not path.is_relative_to(root) or managed_path(path.relative_to(root)):
                return False
            return (not path.is_relative_to(PLUGIN)
                    and any(path.is_relative_to(root / owned) for owned in task["owned_paths"]))
        if self.scratch_file(path):
            return True
        # 宿主自带计划/交接 Artifact 的正文可写；同目录下的原生会话日志不是交付物。
        if path.parent == self.artifacts and path.name in {"task.md", "implementation_plan.md", "walkthrough.md"}:
            return True
        for root in self.roots:
            if not path.is_relative_to(root):
                continue
            relative = path.relative_to(root)
            if not relative.parts or managed_path(relative) or path.is_relative_to(PLUGIN):
                continue
            if explicit_scope(self.message, root, path, single_root=len(self.roots) == 1):
                return True
            if path.suffix != ".md" or any(part.startswith(".") for part in relative.parts):
                continue
            adapters = [name for name in ("project.yaml", ".awf/project.yaml") if (root / name).is_file()]
            if len(adapters) == 1:
                _, docs = project_docs_layout(root, Path(adapters[0]))
                if projection_kind(relative.as_posix(), docs):
                    return True
        return False

    def can_make_directory(self, raw, cwd):
        if self.can_write(raw, cwd):
            return True
        if self.parent or not cwd and not Path(raw).is_absolute():
            return False
        path = physical(raw, cwd or Path("/"))
        for root in self.roots:
            if not path.is_relative_to(root) or path == root:
                continue
            adapters = [name for name in ("project.yaml", ".awf/project.yaml") if (root / name).is_file()]
            if len(adapters) == 1:
                _, docs = project_docs_layout(root, Path(adapters[0]))
                # 允许 PM 准备受控文档目录和计划的目录层级；文件修改仍逐个核所有权。
                plans = root / docs["plans"]
                if (path in {plans, root / docs["standards_root"], (root / docs["project"]).parent}
                        or path in plans.parents or path.is_relative_to(plans)):
                    return True
        return False

    def verification(self, argv, cwd):
        # 只从当前父会话的原任务读验证命令。工作者验自己的任务；QA 的验收由只读工具
        # 和包内 validate/extract 等承接，不能用任意项目脚本获取写入能力。
        basic_runner = check_runner(argv)
        if (basic_runner and not self.parent and len(self.roots) == 1 and cwd == self.roots[0]
                and pm_directive(self.message)):
            # Light 明确例外可以在本轮原话中直接点名测试，不必为此新建任务包。
            # 命令已经过运行器形态核对。仅接受逐字点出的整条命令，或单一测试脚本。
            choices = [shlex.join(argv)]
            if len(argv) == 2 and argv[0] in {"python", "python3"}:
                script = physical(argv[1], cwd)
                if script.is_relative_to(cwd) and not managed_path(script.relative_to(cwd)):
                    choices.append(argv[1])
            if any(re.search(r"(?:运行|执行|跑一下|跑)\s*`?" + re.escape(choice) + r"`?(?:[\s，。；,;！!]|$)",
                             self.message) for choice in choices):
                return True
        if self.parent:
            tasks = [self.task] if self.task else []
        else:
            tasks = [(Path(snap.descriptor["execution_roots"][task["id"]]), task)
                     for root in self.roots if cwd.is_relative_to(root)
                     for project in project_candidates(root) for snap in inventory(project, self.current)
                     for task in snap.tasks if task.get("state") not in ("CANCELLED", "WITHDRAWN", "STOP_REQUESTED")]
        def invocation(words):
            # AGY 默认环境可能只有 python3，既有任务原件可能登记 python。归一化仅限
            # 这两个无路径命令名和禁止写字节码的 -B，所有脚本路径及测试参数逐字保留。
            if words[:1] in (["python"], ["python3"]):
                return ["python3", *(words[2:] if words[1:2] == ["-B"] else words[1:])]
            return words

        requested = invocation(argv)
        for execution, task in tasks:
            module = execution / task["module"]
            if cwd != execution and not cwd.is_relative_to(module):
                continue
            for entry in task.get("verification_commands", ()):
                line = entry.get("run") if isinstance(entry, dict) else entry
                if isinstance(line, str):
                    try:
                        matches = requested == invocation(shlex.split(line))
                    except ValueError:
                        continue  # 原件可能还含自然语言验收说明；不把无法解析的说明当作命令。
                    if matches:
                        if basic_runner and cwd in {execution, module}:
                            return True
                        # 命令已登在原任务内。对平台化构建命令直接复用生成建议的同一
                        # 发现器和实际适配器，核准模块目录与完整 argv；无需复制 Gradle、
                        # Xcode、uv、Poetry、CMake 等平台矩阵或放行任意解释器。
                        adapter = task.get("controlled_document_access", {}).get("adapter")
                        if adapter and (execution / adapter).is_file():
                            from lib.project.validate_project_config import validate_with_profile
                            profile = validate_with_profile(execution / adapter, execution, PLUGIN / "roles").profile
                        else:
                            from lib.project.project_discovery import discover_project
                            profile = discover_project(execution)
                        if profile and any(cwd == execution / item.root and tuple(argv) == cmd.argv
                                           for item in profile.modules for cmd in item.verification_commands):
                            return True
        return False


def decide(event):
    call = event["toolCall"]
    name, args = call["name"], call["args"]
    if name == "manage_task":
        return args.get("Action") in {"status", "list", "kill"}
    if name == "send_command_input":
        return args.get("Terminate") is True and not args.get("Input")
    access = Access(event)
    if name == "run_command":
        return command_allowed(args, access, PLUGIN)
    return name in EDIT_TOOLS and access.can_write(args[EDIT_TOOLS[name]])


if __name__ == "__main__":
    try:
        os.environ["AGENT_WORKFLOW_PLUGIN_ROOT"] = str(PLUGIN)
        allowed = decide(json.load(sys.stdin))
        result = {"decision": "allow"} if allowed else {"decision": "deny", "reason": DENY}
    except Exception:
        # 宿主对失败进程的处理依版本不同。解析/身份/路径异常都输出有效 deny，
        # 不在输出中复制用户文本、任务包、私有路径或日志内容。
        result = {"decision": "deny", "reason": "xy-workflow 无法核对当前会话、任务或目标；请核对派发回执及物理路径。"}
    print(json.dumps(result, ensure_ascii=False))
