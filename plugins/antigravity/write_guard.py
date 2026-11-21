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

DENY_COMMAND = ("xy-workflow 拒绝此命令形式。请使用已支持的只读查询、"
                "精确匹配任务原件的验证命令，或改用具备对应权限的原生文件工具。")
DENY_PATH = ("xy-workflow 无法确认目标路径的工作区归属或物理节点。"
             "请核对工作区、规范绝对路径及路径中是否存在链接。")
DENY_PM = ("xy-workflow 未找到 PM 亲自写入此业务目标的明确授权。"
           "请按当前任务包交给已验证的实现角色。")
DENY_CHILD = ("xy-workflow 无法核对当前子会话的可写派发。QA 只允许读取。"
              "实现任务请核对 claim、初始 Prompt 中的独立标记、原生创建回执和任务绑定。")
DENY_OWNERSHIP = ("xy-workflow 已核对实现派发，目标超出当前 Writer 的 owned_paths、"
                  "固定工作区或可写资源范围。")
AGENT_DIRS = {".git", ".agents", ".agent", ".antigravity", ".awf", ".gemini", ".codex", ".claude"}
EDIT_TOOLS = {"edit_file": "Path", "write_file": "Path", "write_to_file": "TargetFile",
              "replace_file_content": "TargetFile", "multi_replace_file_content": "TargetFile"}


class GuardRefusal(Exception):
    """仅携带固定脱敏原因，避免回显用户输入、完整工具参数或任何私有路径。"""


def physical(value, base):
    """写入以真实路径和节点类型为准；拒绝借符号链接、硬链接或设备改写另一个对象。"""
    if not isinstance(value, str) or not value or "\0" in value or ".." in Path(value).parts:
        raise GuardRefusal(DENY_PATH)
    path = base / value
    # macOS 的 /tmp、/var 是系统别名。调用方须传宿主报告的物理路径；
    # 不能先 resolve 再丢掉项目内符号链接这条关键信息。
    if not path.is_absolute() or any(node.is_symlink() for node in (path, *path.parents)):
        raise GuardRefusal(DENY_PATH)
    try:
        info = path.stat()
    except FileNotFoundError:
        return path
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
        raise GuardRefusal(DENY_PATH)
    return path


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


def dispatched(snapshot, project, parent, child, marker=None):
    task = snapshot.task
    claim = task.get("antigravity_claim", {})
    reference = task.get("agent_ref")
    if (claim.get("parent") != parent or not child or
            reference is not None and reference != {"host": "antigravity", "agent_id": child}):
        return False
    target = {"record": snapshot.record, "request_id": task["request_id"], "task_id": task["id"]}
    actual = native.dispatch_marker(project, target, task["claim_basis_sha256"], claim)
    if marker is not None and marker != actual:
        return False
    # 绑定前后均认原生创建回执。任务 JSON 中的角色、实例 ID 或登记状态不能单独证明派发。
    native.verify_creation(parent, child, snapshot.execution_root, actual, task["role"])
    return True


def child_task(roots, current, parent, marker):
    if not marker:
        return None
    for workspace in roots:
        for project in project_candidates(workspace):
            # 任务池已在锁内核对本 PM 的原件和执行根。释放池锁后才读取原生日志，
            # 保证 Hook 不持久化绑定，也不把耗时日志核验塞进任务池的临界区。
            for snapshot in task_pool.registered_tasks(project, "antigravity:" + parent):
                task = snapshot.task
                if (task.get("state") != "RUNNING" or task.get("agent_retired") or task.get("withdrawal")
                        or task.get("task_type") != "writer" or task.get("role") == "xy-qa"
                        or snapshot.execution_root != workspace):
                    continue
                try:
                    if dispatched(snapshot, project, parent, current, marker):
                        return workspace, task
                except TaskGraphError as exc:
                    raise GuardRefusal(DENY_CHILD) from exc
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
    def __init__(self, event, handoff):
        self.roots = [Path(path).resolve(strict=True) for path in event["workspacePaths"]]
        if not all(p.is_dir() for p in self.roots):
            raise ValueError("缺少项目根")
        self.handoff = handoff
        self.current, self.parent, self.marker = native.session_origin(event)
        self.message = event.get("lastUserInput")
        self.transcript = Path(event["transcriptPath"])
        # 原生适配器已核对当前会话和日志的绝对路径，Artifact 同属这个会话目录。
        self.artifacts = self.transcript.parents[2]
        # 实机顶层 cwd 是 Hook 自身的插件目录。工具省略 Cwd 时，单工作区才有
        # 可确定的相对路径基准；多工作区的绝对文件操作仍可正常核对。
        self.cwd = self.roots[0] if len(self.roots) == 1 else None
        self.refusal = DENY_COMMAND

    @cached_property
    def task(self):
        # 读取与核验不依赖绑定时序。只有要写入或执行任务登记的命令时，才进池
        # 核对角色、回执与所有权；QA 的正常只读取证不受忙锁或创建回执延迟影响。
        return child_task(self.roots, self.current, self.parent, self.marker) if self.parent else None

    def scratch_file(self, path, project=None):
        path = physical(str(path), Path("/"))
        for root in (project,) if project is not None else self.roots:
            # 新领取使用项目内交接槽，让原生工具在默认沙箱内可读写。已在途原件
            # 也可通过原系统临时槽完成交接；不枚举、不迁移、不修改原有任务池。
            for base in self.handoff.compatible_bases(root):
                if path.is_relative_to(base):
                    parts = path.relative_to(base).parts
                    return (len(parts) >= 2 and SCRATCH_SLOT_RE.fullmatch(parts[0])
                            and (base / parts[0]).is_dir() and not any(p.startswith(".") for p in parts)
                            and path.suffix in {".json", ".jsonl", ".md", ".txt", ".log", ".patch", ".diff"})
        return False

    def project_input(self, raw, project, *, scratch=False):
        # 只读 helper 也必须读当前调用选定的项目；明确登记的输入才可读取
        # 同项目请求临时槽。始终先检查物理路径，避免借链接重定向到别的工作区。
        path = physical(raw, project)
        if path.is_relative_to(project) or scratch and self.scratch_file(path, project):
            return True
        raise GuardRefusal(DENY_PATH)

    def design_actor(self, snapshot, project, action, pages):
        from lib.task_graph import delivery_complete
        task = snapshot.task
        execution = snapshot.execution_root
        if action == "prepare-delivery" and not self.parent:
            # prepare 会修改业务 HTML，普通 PM 委托不能代替用户当前明确的本人实施授权。
            return (not task.get("agent_retired") and task["state"] in {"DECLARED", "READY", "RUNNING"}
                    and all(explicit_scope(self.message, execution, execution / page,
                                           single_root=len(self.roots) == 1) for page in pages))
        if "task" in snapshot.source and (not snapshot.prototype_claim
                or snapshot.prototype_claim != task.get("claim_basis_sha256")):
            return False
        parent = self.parent or self.current
        child = self.current if self.parent else task.get("agent_ref", {}).get("agent_id")
        if not self.parent and delivery_complete("writer", task["state"]):
            # PM 接手已交付页面，只读同一父会话的原领取和已绑定实例。原生首绑已核实；
            # 交付后日志可能归档或增长，不能让同请求的服务因此永远无法收口。
            return bool(child and task.get("antigravity_claim", {}).get("parent") == parent)
        if task["state"] != "RUNNING" or task.get("agent_retired"):
            return False
        try:
            return dispatched(snapshot, project, parent, child, self.marker if self.parent else None)
        except TaskGraphError:
            # 该实例的创建回执不可核验，就不能用它授权。stop 按请求选服务，可以继续
            # 核对同请求的其他设计任务；任务池、原图、批准的异常仍由各自边界拒绝。
            return False

    def prototype_delivery(self, raw, action, values):
        from lib.task_graph_cli import pack_snapshot
        from lib.writer_prerequisites import writer_blockers

        if raw != values["--root"] or not Path(raw).is_absolute():
            return False
        execution = physical(raw, Path("/"))
        request = values.get("--request-id")
        pages = values.get("--pages", [])
        if self.parent and (execution not in self.roots or not self.marker):
            return False
        # 外层 --project 可指向此次设计任务的已登记 linked worktree。始终从宿主工作区找池，
        # 不从命令所指的另一个项目自行加载授权。子角色只能使用宿主给它的执行根。
        roots = dict.fromkeys(project for workspace in self.roots for project in project_candidates(workspace))
        parent = self.parent or self.current
        permitted = {}
        for project in roots:
            for snapshot in task_pool.registered_tasks(project, "antigravity:" + parent):
                task = snapshot.task
                if (snapshot.execution_root != execution or task["role"] != "xy-uiux"
                        or task["task_type"] != "writer" or task.get("design_mode", "prototype") != "prototype"
                        or request is not None and task["request_id"] != request
                        or task.get("withdrawal")
                        or task.get("task_revision") and not task.get("revision_ack")):
                    continue
                if action != "stop" and values["--adapter"] != task["controlled_document_access"]["adapter"]:
                    continue
                graph = pack_snapshot(snapshot.source) if "task" in snapshot.source else snapshot.source
                # 有页面的动作只向实际拥有其中页面的任务核对回执。不同 Writer 可分别
                # 贡献同请求的页面，整批目标仍须在下方得到完整覆盖。
                owned_pages = set()
                if action != "stop":
                    prototype, = graph["ui_contract"]["prototype_paths"]
                    for page in pages:
                        target = physical(page, execution)
                        if (not Path(page).is_absolute() and page == Path(page).as_posix()
                                and target.parent == execution / prototype and target.is_file()
                                and target.suffix == ".html" and target.name != "index.html"
                                and any(target.is_relative_to(execution / owned) for owned in task["owned_paths"])):
                            owned_pages.add(page)
                    if not owned_pages:
                        continue
                current = next(item for item in graph["tasks"] if item["id"] == task["id"])
                if writer_blockers(graph, current, project) or not self.design_actor(snapshot, project, action, pages):
                    continue
                if action == "stop":
                    return True  # helper 再按实际项目和这个精确 request_id 锁住对应实例。
                permitted.setdefault(task["request_id"], set()).update(owned_pages)
        # prepare 没有 request-id 参数，其整批目标也必须来自同一个明确获准的请求。
        return bool(pages) and sum(set(pages) == owned for owned in permitted.values()) == 1

    def project_root(self, raw, *, expected=None):
        # 缺参数仍由命令形态拒绝；显式选了其他根时报告工作区拒绝。内层
        # helper 的项目参数必须与已核对的外层选择完全相同。
        if raw is None:
            return None
        path = Path(raw)
        if path not in self.roots or expected is not None and raw != str(expected):
            raise GuardRefusal(DENY_PATH)
        return path

    def workspace_directory(self, raw, *, base=None):
        # 原生 Cwd 必须绝对；Git -C 的相对路径以已核对的终端 Cwd 为基准。
        # 核对解析后的真实目录，防止 ..、链接或多工作区下未知基准越界。
        try:
            path = Path(raw)
            if not path.is_absolute():
                if base is None:
                    raise GuardRefusal(DENY_PATH)
                path = base / path
            directory = path.resolve(strict=True)
            if directory.is_dir() and any(directory.is_relative_to(root) for root in self.roots):
                return directory
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise GuardRefusal(DENY_PATH) from exc
        raise GuardRefusal(DENY_PATH)

    def can_write(self, raw, cwd=None):
        base = cwd or self.cwd
        if base is None and not Path(raw).is_absolute():
            self.refusal = DENY_PATH
            return False
        path = physical(raw, base or Path("/"))
        if self.parent:
            if self.task is None:
                self.refusal = DENY_CHILD
                return False
            root, task = self.task
            self.refusal = DENY_OWNERSHIP
            if not path.is_relative_to(root) or managed_path(path.relative_to(root)):
                return False
            return (not path.is_relative_to(PLUGIN)
                    and any(path.is_relative_to(root / owned) for owned in task["owned_paths"]))
        if self.scratch_file(path):
            return True
        # 宿主自带计划/交接 Artifact 的正文可写；同目录下的原生会话日志不是交付物。
        if path.parent == self.artifacts and path.name in {"task.md", "implementation_plan.md", "walkthrough.md"}:
            return True
        self.refusal = DENY_PATH
        for root in self.roots:
            if not path.is_relative_to(root):
                continue
            relative = path.relative_to(root)
            if not relative.parts or managed_path(relative) or path.is_relative_to(PLUGIN):
                continue
            self.refusal = DENY_PM
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
            tasks = [(snapshot.execution_root, snapshot.task)
                     for root in self.roots if cwd.is_relative_to(root)
                     for project in project_candidates(root)
                     for snapshot in task_pool.registered_tasks(project, "antigravity:" + self.current)
                     if snapshot.task.get("state") not in ("CANCELLED", "WITHDRAWN", "STOP_REQUESTED")]
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


def decide(event, handoff):
    call = event["toolCall"]
    name, args = call["name"], call["args"]
    if name == "manage_task":
        return None if args.get("Action") in {"status", "list", "kill"} else DENY_COMMAND
    if name == "send_command_input":
        return None if args.get("Terminate") is True and not args.get("Input") else DENY_COMMAND
    access = Access(event, handoff)
    if name == "run_command":
        try:
            return None if command_allowed(args, access, PLUGIN) else access.refusal
        except ValueError:
            # 命令词、参数或重定向无法按受控 argv 解析。保留脱敏原因。
            return access.refusal
    return None if name in EDIT_TOOLS and access.can_write(args[EDIT_TOOLS[name]]) else access.refusal


if __name__ == "__main__":
    try:
        from lib.hosts.factory import handoff_policy, packaged_host

        # 在加载写入逻辑和宿主日志解释器前核对实体宿主和固定入口。
        # 原生 Hook 逐次同步运行，避免按整个载荷或第三方资源树全量扫描。
        host = packaged_host(PLUGIN, expected="antigravity", resources=(
            "hooks.json", "hooks/write_guard.py", "hooks/guard_command.py", "lib/python_runtime.sh",
            "lib/hosts/factory.py", "lib/hosts/dispatch_contract.py", "lib/hosts/handoff.py",
            "lib/hosts/antigravity_dispatch.py", "lib/hosts/antigravity_handoff.py", "lib/task_pool.py",
            "lib/writer_prerequisites.py", "lib/task_graph_cli.py",
            "workflow-sources.json", "lib/safe_text.py", "lib/qa_projection.py", "lib/validate_project_docs.py",
        ))
        from lib import task_pool
        from lib.hosts import antigravity_dispatch as native
        from lib.hosts.handoff import SCRATCH_SLOT_RE
        from lib.qa_projection import projection_kind
        from lib.safe_text import read_file
        from lib.task_graph import TaskGraphError
        from lib.validate_project_docs import project_docs_layout
        from guard_command import check_runner, command_allowed

        os.environ["AGENT_WORKFLOW_PLUGIN_ROOT"] = str(PLUGIN)
        reason = decide(json.load(sys.stdin), handoff_policy(host))
        result = {"decision": "deny", "reason": reason} if reason else {"decision": "allow"}
    except GuardRefusal as refusal:
        result = {"decision": "deny", "reason": str(refusal)}
    except Exception:
        # 宿主对失败进程的处理依版本不同。解析/身份/路径异常都输出有效 deny，
        # 不在输出中复制用户文本、任务包、私有路径或日志内容。
        result = {"decision": "deny", "reason": "xy-workflow 无法核对当前会话、任务或目标；请核对派发回执及物理路径。"}
    print(json.dumps(result, ensure_ascii=False))
