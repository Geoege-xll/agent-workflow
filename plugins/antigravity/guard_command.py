"""AGY 终端策略只解释已核实的简单调用；Shell 展开、管道与复合程序交给原生实现角色。"""

from pathlib import Path
import re
import json
import shlex

from lib.safe_text import open_file


# 带任意输出参数、预处理器、解释器或执行子程序的命令不能只按第一个词放行。
# 逐项检查选项，保守检查 -- 后的字符串，避免上一个选项吃掉 -- 后裸露出危险参数。
READ_FLAGS = {
    "pwd": {"-P", "-L"}, "ls": {"-a", "-A", "-l", "-h", "-d", "-R", "-1", "-t"},
    "cat": {"-n", "-b", "-s"}, "wc": {"-l", "-w", "-c", "-m"},
    "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "shasum": {"-a", "-c"},
    "sha256sum": {"-c"}, "rg": {"-n", "-i", "-l", "-F", "-S", "-g", "-e", "-C", "-A", "-B",
                                 "--files", "--hidden", "--line-number", "--no-heading", "--count", "--no-ignore",
                                 "--max-depth", "--glob"},
    "grep": {"-r", "-R", "-n", "-i", "-F", "-E", "-l", "-e", "-C", "-A", "-B"},
    "git": set(),
}
GIT_FLAGS = {
    "status": {"--short", "--porcelain", "--porcelain=v1", "--porcelain=v2", "--branch", "-s", "-b"},
    "diff": {"--stat", "--name-only", "--name-status", "--cached", "--staged", "--check", "--no-ext-diff",
             "--no-textconv", "--no-color", "--", "-U0"},
    "log": {"--oneline", "--decorate", "--no-color", "-n", "--stat"},
    "ls-files": {"--stage", "--cached", "--others", "--exclude-standard", "-z"},
    "rev-parse": {"--show-toplevel", "--show-prefix", "--abbrev-ref", "--verify"},
}
READ_HELPERS = {"lib/documents/context_read.py", "lib/validate_project_docs.py", "lib/project/validate_project_config.py",
                "lib/agent_continuation_cli.py", "lib/project/project_profile_cli.py"}
GRAPH_READ = {"validate", "ready", "qa-ready", "capacity", "task", "fingerprints", "continuation",
              "verify-ui-scope", "verify-solution-scope"}
POOL_COMMANDS = {"view", "status", "register", "archive", "claim", "release", "bind"}
GRAPH_FLAGS = {"--root", "--request-id", "--input", "--output", "--source", "--patch", "--expect-sha256", "--task-id",
               "--pm-id", "--host", "--observed-state", "--select", "--check-command", "--dry-run", "--keep", "--all"}
POOL_FLAGS = {"--root", "--pm-id", "--record", "--receipt", "--request-id", "--task-id", "--host", "--agent-id",
              "--expect-sha256", "--configured-subagents", "--configured-writers", "--host-available-subagents",
              "--query", "--title", "--register", "--outcome"}


def flags_ok(args, flags):
    for word in args:
        if word == "--":
            continue
        if word.startswith("-") and word not in flags:
            # 接受 ls -la、rg -nF 等纯开关组合，以及 head -20 / git log -3。
            if not (re.fullmatch(r"-\d+", word)
                    or re.fullmatch(r"-[a-zA-Z]+", word) and all("-" + ch in flags for ch in word[1:])):
                return False
    return True


def read_command(words, access, cwd):
    cmd, *args = words
    if cmd == "find":
        # 查找入口先消费普通起点，再逐个核定只读谓词的参数个数。
        # 常用 -name 的通配模式只能以引号传入；执行、删除或写清单的谓词不在集合内。
        while args and not args[0].startswith("-"):
            args = args[1:]
        while args:
            predicate, *args = args
            if predicate in {"-print", "-print0", "-a", "-o"}:
                continue
            if predicate not in {"-name", "-iname", "-type", "-maxdepth", "-mindepth"} or not args:
                return False
            value, *args = args
            if ((predicate == "-type" and value not in {"f", "d", "l"})
                    or predicate.endswith("depth") and not value.isdecimal()):
                return False
        return True
    if cmd == "git":
        no_pager = args[:1] == ["--no-pager"]
        if no_pager:
            args = args[1:]
        no_lazy_fetch = args[:1] == ["--no-lazy-fetch"]
        if no_lazy_fetch:
            args = args[1:]
        if args[:1] == ["-C"]:
            if len(args) < 2:
                return False
            # 所有白名单 Git 子命令共用同一个 -C 边界。每个分段独立执行，
            # 只以宿主已核对的终端 Cwd 解释相对路径。
            access.workspace_directory(args[1], base=cwd)
            args = args[2:]
        if args[:1] == ["show"]:
            # partial clone 缺对象时，show 也可能抓取远程并写入对象库。
            # 要求调用者显式关闭抓取和展示外部程序；旧 Git 不识别此开关会直接报错。
            switches = {"--no-ext-diff", "--no-textconv"}
            before_separator = args[1:args.index("--")] if "--" in args else args[1:]
            return (no_pager and no_lazy_fetch and switches <= set(before_separator) and cwd is not None
                    and flags_ok(args[1:], switches | {"--stat", "--oneline", "--no-patch", "--no-color"}))
        return bool(args and args[0] in GIT_FLAGS and flags_ok(args[1:], GIT_FLAGS[args[0]]))
    if cmd == "sed":
        # 仅接受查看行范围的标准写法。sed 脚本中的 w/e 具有真正写入/执行能力。
        return (len(args) >= 2 and args[0] == "-n" and re.fullmatch(r"\d+(?:,\d+)?p", args[1])
                and all(not path.startswith("-") for path in args[2:]))
    if cmd == "echo":
        return True
    if cmd == "printf":
        return bool(args and not args[0].startswith("-"))
    if cmd == "rg":
        # 只新增已知搜索开关的等号形式。--glob 的值作为一个 argv 传入；
        # 命令扫描仍会拒绝未引用的 glob 和任何预处理器开关。
        for i, word in enumerate(args):
            if word == "--max-depth" and (i + 1 == len(args) or not args[i + 1].isascii()
                                         or not args[i + 1].isdecimal()):
                return False
            if word == "--glob" and (i + 1 == len(args) or args[i + 1].startswith("-")):
                return False
            if (re.fullmatch(r"--max-depth=[0-9]+", word) or word.startswith("--glob=") and len(word) > 7):
                continue
            if not flags_ok([word], READ_FLAGS[cmd]):
                return False
        return True
    if cmd in READ_FLAGS:
        return flags_ok(args, READ_FLAGS[cmd])
    return False


def options(args, permitted, *, switches=(), repeatable=(), lists=()):
    """拒绝 argparse 的缩写、重复及嵌套选项；核对的目标必须与下游实际读取的一致。"""
    values = {}
    i = 0
    while i < len(args):
        flag = args[i]
        if flag not in permitted or flag in values and flag not in ("--keep", "--select", *repeatable):
            raise ValueError("不支持的参数")
        if flag in ("--register", "--dry-run", "--all", *switches):
            values[flag] = True
            i += 1
        elif flag in lists:
            # argparse 的 nargs="+" 消费到下一个选项。保留整体值，不把页面
            # 误判为行动或把后续选项作为页面放行。
            start = i + 1
            i = start
            while i < len(args) and not args[i].startswith("-"):
                i += 1
            if i == start:
                raise ValueError("缺少确定的参数值")
            values[flag] = args[start:i]
        else:
            if i + 1 >= len(args) or args[i + 1].startswith("-"):
                raise ValueError("缺少确定的参数值")
            if flag in repeatable:
                values.setdefault(flag, []).append(args[i + 1])
            else:
                values[flag] = args[i + 1]
            i += 2
    return values


def additional_read_helper(helper, arguments, access, project):
    """逐动作固定下游的实际项目与显式输入；同一 CLI 的写动作不继承只读许可。"""
    if helper == "lib/hosts/capabilities.py":
        # 默认只读报告。--probe-version 会从 PATH 启动另一宿主，须另行走宿主授权。
        return (len(arguments) == 2 and arguments[0] == "--platform"
                and arguments[1] in {"codex", "claude", "antigravity"})
    if helper == "lib/delivery/native_usage.py":
        values = options(arguments, {"--host", "--input"}, repeatable=("--input",))
        return (values.get("--host") in {"codex", "claude", "antigravity"} and "--input" in values
                and all(access.project_input(path, project, scratch=True) for path in values["--input"]))
    if helper == "lib/delivery/qa_handoff_cli.py":
        # 原 CLI 的结果只走 stdout。支持固定的取证动作，不为此增加 --output
        # 或在 Reviewer 子会话放开外部文件/重定向写入。
        action, *rest = arguments
        if action == "schema":
            return not rest
        if action not in {"validate", "extract", "compose", "compare-target"}:
            return False
        flags = {"--input", "--task-pack"}
        if action == "extract":
            flags.add("--host")
        values = options(rest, flags)
        return ("--task-pack" in values
                and (action != "extract" or {"--input", "--host"} <= values.keys())
                and all(access.project_input(values[key], project, scratch=True) for key in flags - {"--host"}
                        if key in values))
    if helper == "lib/documents/validate_prototype_workspace.py":
        # CLI 从位置参数重新选工作区。精确核对这项，随后由原校验器逐个限制相对
        # 原型根、页面、适配器与依赖；此入口只读取指纹，不打开页面或准备交付。
        if len(arguments) < 2 or arguments[1].startswith("-"):
            return False
        access.project_root(arguments[0], expected=project)
        values = options(arguments[2:], {"--adapter", "--json", "--standalone", "--page", "--expect"},
                         switches=("--json", "--standalone"), repeatable=("--page", "--expect"))
        return (access.project_input(arguments[1], project)
                and ("--adapter" not in values or access.project_input(values["--adapter"], project)))
    if helper == "lib/documents/prototype_feedback_cli.py":
        action, *rest = arguments
        if action == "status":
            # status 只锁已存在的目录 inode，向固定 loopback 读取状态。自定义
            # 数据目录和写入、启动、停止动作不继承这项许可。
            values = options(rest, {"--root", "--request-id"})
            return bool(access.project_root(values.get("--root"), expected=project)) and "--request-id" in values
        if action == "validate":
            values = options(rest, {"--root", "--adapter", "--input"})
            return (access.project_root(values.get("--root"), expected=project)
                    and {"--adapter", "--input"} <= values.keys()
                    and access.project_input(values["--adapter"], project)
                    and access.project_input(values["--input"], project, scratch=True))
        if action == "migration-preview":
            # 默认预览只读两轮原稿与工具清单。确认无活动使用会生成后续迁移可
            # 消费的授权声明，这里不代表用户确认，也不放开 apply/recover。
            values = options(rest, {"--root", "--adapter", "--plan", "--request-id", "--pages"},
                             lists=("--pages",))
            return (access.project_root(values.get("--root"), expected=project)
                    and {"--adapter", "--plan", "--request-id"} <= values.keys()
                    and all(access.project_input(values[key], project) for key in ("--adapter", "--plan"))
                    and all(access.project_input(page, project) for page in values.get("--pages", ())))
        return False
    if helper == "lib/delivery/worktree_cli.py":
        action, *rest = arguments
        if action == "inspect":
            values = options(rest, {"--repo", "--base", "--head"})
            return (access.project_root(values.get("--repo"), expected=project)
                    and {"--base", "--head"} <= values.keys())
        if action == "target":
            values = options(rest, {"--repo", "--config"})
            return (access.project_root(values.get("--repo"), expected=project)
                    and ("--config" not in values or access.project_input(values["--config"], project)))
        return False
    return False


def packaged_helper(words, access, plugin, cwd, *, redirected=False):
    prefix = ["bash", str(plugin / "lib/python_runtime.sh"), "-B", "-X", "utf8", str(plugin / "plugins/source_pack.py")]
    if words[:len(prefix)] != prefix:
        return False
    args = words[len(prefix):]
    if not args:
        return False
    if args[0] in {"resource", "dispatch-preferences", "--help"}:
        return True
    if args[:2] == ["selected-skills", "read"]:
        return True
    if args[:2] == ["selected-skills", "query"]:
        # 只放行随包查询的固定形态。这里是宿主终端权限边界，程序另行绑定语料和摘要。
        return (not redirected and cwd is not None and len(args) in (4, 6)
                and args[2] in {"chart", "ux", "typography", "color", "style"}
                and bool(args[3].strip()) and args[3].isprintable() and len(args[3]) <= 512
                and not args[3].startswith("-")
                and (len(args) == 4 or args[4] == "--max-results" and re.fullmatch(r"[1-9]|1[0-9]|20", args[5])))
    if args == ["selected-skills", "check"]:
        return True
    if args[0] == "xy-web-guidance":
        # 固定包内适配器只允许本地语料读取，清除 Node 注入选项并禁用遥测；
        # 不透传上游任意命令。具体查询和语料指纹仍由原入口核对。
        query = args[2:] if args[1:2] == ["--"] else args[1:]
        return cwd is not None and (query in (["doctor"], ["list"])
                                    or len(query) == 2 and query[0] in {"search", "retrieve"}
                                    and not query[1].startswith("-"))
    if args[0] == "apple-skills":
        # 默认只经绝对系统命令解析当前选定的 Xcode 并读取其有界文档。显式另选
        # developer-dir 会扩大文件读取范围，守卫仅恢复选定 Xcode 的指导入口。
        if args == ["apple-skills", "check"]:
            return True
        if args[1:2] == ["read"]:
            return {"--skill", "--resource", "--expect-source-sha256"} <= options(
                args[2:], {"--skill", "--resource", "--expect-source-sha256", "--offset", "--length"}).keys()
        return False
    if len(args) < 5 or args[:2] != ["helper", "--project"]:
        return False
    helper, action, *rest = args[3:]
    if helper == "lib/documents/prototype_feedback_cli.py" and action in {"prepare-delivery", "open", "stop"}:
        required = ({"--root", "--request-id"} if action == "stop" else {"--root", "--adapter", "--pages"})
        if action == "open":
            required.update(("--plan", "--request-id"))
        values = options(rest, required | ({"--group"} if action == "prepare-delivery" else set()), lists=("--pages",))
        if redirected or not required <= values.keys():
            return False
        if "--plan" in values:
            plan = Path(values["--plan"])
            if plan.is_absolute() or ".." in plan.parts or values["--plan"] != plan.as_posix():
                return False
        return access.prototype_delivery(args[2], action, values)
    project = access.project_root(args[2])
    if helper == "lib/delivery/worktree_cli.py" and action in {"merge-ready", "merge"}:
        required = {"--repo", "--config", "--input", "--pm-id", "--expect-sha256"}
        values = options(rest, required)
        if (access.parent or redirected or values.keys() != required or
                values["--pm-id"] != "antigravity:" + access.current or
                not access.project_root(values["--repo"], expected=project)):
            return False
        access.project_input(values["--config"], project)
        from lib.hosts.antigravity_dispatch import delivery_input
        delivery_input(project, Path(values["--config"]), Path(values["--input"]),
                       values["--pm-id"], values["--expect-sha256"])
        return True
    if helper in READ_HELPERS:
        return True
    if helper == "plugins/project_context.py":
        if action == "inspect":
            return True
        if access.parent:
            return False
        values = options(rest, {"--adapter", "--input", "--output"})
        return (action == "apply" and values == {"--adapter": ".awf/project.yaml"}
                or action == "init" and access.scratch_file(project / values["--output"]))
    if helper == "lib/task_pool_cli.py" and action in POOL_COMMANDS:
        values = options(rest, POOL_FLAGS)
        return (access.project_root(values.get("--root"), expected=project) and not access.parent
                and values.get("--pm-id") == "antigravity:" + access.current
                and all(access.scratch_file(project / values[key]) for key in ("--record", "--receipt") if key in values))
    if helper == "lib/task_graph_cli.py":
        values = options(rest, GRAPH_FLAGS)
        access.project_root(values.get("--root"), expected=project)
        if "--pm-id" in values and (access.parent or values["--pm-id"] != "antigravity:" + access.current):
            return False
        if "--output" in values and (access.parent or not access.scratch_file(project / values["--output"])):
            return False
        if action in GRAPH_READ:
            return True
        if access.parent:
            return False
        if action in {"scratch", "cleanup-scratch"}:
            return "--all" not in values
        if action == "init":
            return "--output" in values
        return action == "update" and "--input" in values and access.scratch_file(project / values["--input"])
    return additional_read_helper(helper, (action, *rest), access, project)


def check_runner(words):
    # 构建/测试会运行项目代码。仅接受原件逐字登记的常规运行器形态，禁用解释器
    # 内联程序、任意脚本、命令替换与附加重定向；宿主自己的沙箱／许可仍然生效。
    cmd, *args = words
    if not args:
        return False
    if cmd in {"python", "python3"}:
        args = args[1:] if args[:1] == ["-B"] else args
        return (args[:2] in (["-m", "unittest"], ["-m", "pytest"]) or len(args) == 1 and
                bool(re.fullmatch(r"(?:[\w./-]+/)?(?:test[\w.-]*|[\w.-]+_test)\.py", args[0])))
    if cmd in {"npm", "pnpm", "yarn"}:
        return args[0] in {"test", "build", "lint", "typecheck"} or args[:1] == ["run"] and args[1:2] in (
            ["test"], ["build"], ["lint"], ["typecheck"])
    if cmd == "bash":
        return bool(re.fullmatch(r"(?:\./)?scripts/(?:test|check|build)[\w.-]*\.sh", args[0]))
    return (cmd, args[0]) in {("cargo", "test"), ("cargo", "check"), ("go", "test"), ("swift", "test"),
                               ("mvn", "test"), ("node", "--test"), ("make", "test")}


def maintenance_allowed(words, access, plugin):
    """仅接受本包固定启动器和当前用户显式维护入口；业务委托与角色交接不能代为激活。"""
    launcher = ["bash", str(plugin / "plugins/maintenance/launcher.sh")]
    if words[:2] != launcher or access.parent:
        return False
    action = words[2] if len(words) > 2 else ""
    if action not in {"open", "status", "doctor"}:
        return False
    expected = [*launcher, action, "--host", "antigravity"]
    if len(access.roots) == 1:
        expected.extend(["--project", str(access.roots[0])])
    message = (access.message or "").strip()
    if words == expected:
        return message == "/xy-config " + action or action == "open" and message == "/xy-config"
    if action != "open" or words[:len(expected) + 1] != [*expected, "--prepare"]:
        return False
    extra = words[len(expected) + 1:]
    if extra and not (len(extra) == 2 and extra[0] == "--artifact" and Path(extra[1]).is_absolute()
                      and extra[1] in message):
        return False
    if not re.fullmatch(r"(?:我)?(?:确认|同意|允许)(?:本次|这次)?(?:准备(?:配置)?组件|组件准备)?"
                        r"(?:[，, ]+(?:使用|离线包)\s*.+)?[。！!]?", message):
        return False
    # 用户同意的下一轮仍须对得上本会话上一条原生 open 及其 preparation_required
    # 回执。只读有界尾段，只认相邻原生工具事件；复制到聊天的同名文字没有效力。
    prior = ""
    pending = False
    required = False
    confirmed = False
    with open_file(access.transcript) as stream:
        if stream is None:
            return False
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 4 * 1024 * 1024))
        if stream.tell():
            stream.readline()
        for line in stream:
            event = json.loads(line)
            if event.get("source") == "USER_EXPLICIT" and event.get("type") == "USER_INPUT":
                match = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", event.get("content", ""), re.S)
                current = match[1] if match else ""
                confirmed = current == message and prior in {"/xy-config", "/xy-config open"} and required
                prior, required = current, False
            if pending and event.get("source") == "MODEL" and event.get("type") == "GENERIC":
                required = bool(re.search(r'"state"\s*:\s*"preparation_required"', event.get("content", "")))
            pending = False
            calls = event.get("tool_calls") or []
            if (prior in {"/xy-config", "/xy-config open"} and event.get("source") == "MODEL"
                    and event.get("type") == "PLANNER_RESPONSE" and len(calls) == 1 and calls[0]["name"] == "run_command"):
                raw = calls[0]["args"]["CommandLine"]
                if access.transcript.name == "transcript.jsonl":
                    raw = json.loads(raw)
                pending = shlex.split(raw) == expected
    return confirmed


def command_allowed(args, access, plugin):
    if args.get("RequestedTerminalID") or args.get("RunPersistent"):
        return False
    line = args.get("CommandLine")
    raw_cwd = args.get("Cwd")
    cwd = access.cwd if raw_cwd in (None, "") else access.workspace_directory(raw_cwd)
    # 仅识别无二次解释的独立命令。保守地先排除变量/替换/多行/控制符，即使它们
    # 出现在引号中；需要复杂文本的任务包和计划用原生 write_file 保留原始字节。
    if not isinstance(line, str) or any(ch in line for ch in "\n\r\0$`;<(){}!~"):
        return False
    # 只读查询可以在整个命令末尾原样丢弃 stderr。其它描述符、路径、前置
    # 或中间重定向不借该例外通过；移除尾部后仍对完整查询逐段核验。
    silent_stderr = re.search(r"[ \t]+2>/dev/null[ \t]*\Z", line)
    if silent_stderr:
        line = line[:silent_stderr.start()]
    # Shell 对单引号中的反斜线保留字面量，可直接传给 rg/grep；双引号内
    # 或未引用时存在转义歧义，不能用 shlex 的结果替代宿主实际执行语义。
    quoted = re.compile("'[^']*'|\"[^\"]*\"")
    unquoted = quoted.sub("", line)
    literal_backslash = "\\" in line
    if literal_backslash and ("\\" in unquoted or any(
            chunk[0].startswith('"') and "\\" in chunk[0] for chunk in quoted.finditer(line))):
        return False
    lexer = shlex.shlex(line, posix=True, punctuation_chars=">&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    words = list(lexer)
    if not words:
        return False
    # 区分字面的查询模式与真正由 shell 展开的文件名。前者可供 find/rg 或偏好
    # 查询使用，后者可能在命令执行时注入未核对的谓词、选项或多个输出文件。
    if any(ch in unquoted for ch in "*?[]"):
        return False
    if any(word in {"&&", "|", "&", "||", "|&"} for word in words):
        # AGY 会主动合并两个只读查询。只接受完全由已核实只读命令组成的链；
        # 逐段判定，禁止把输出重定向或执行型末段混进头一个只读命令。
        parts = [[]]
        for word in words:
            if word in {"&&", "|"}:
                parts.append([])
            elif any(ch in word for ch in ">&|"):
                return False
            else:
                parts[-1].append(word)
        return all(part and read_command(part, access, cwd) for part in parts)
    if silent_stderr or literal_backslash:
        # 例外只作用于已识别的只读命令，禁止组合 stdout 写入、执行器或 helper。
        return not any(ch in unquoted for ch in ">&|") and read_command(words, access, cwd)
    redirect = next((i for i, word in enumerate(words) if ">" in word), None)
    if redirect is not None:
        if (redirect != len(words) - 2 or words[redirect] not in {">", ">>"} or redirect == 0
                or not access.can_write(words[-1], cwd)):
            return False
        words = words[:redirect]
    if words[:2] == ["bash", str(plugin / "plugins/maintenance/launcher.sh")]:
        return redirect is None and maintenance_allowed(words, access, plugin)
    if read_command(words, access, cwd) or packaged_helper(words, access, plugin, cwd, redirected=redirect is not None):
        return True
    if words[0] in {"touch", "mkdir"}:
        paths = words[1:]
        if words[0] == "mkdir" and paths[:1] == ["-p"]:
            paths = paths[1:]
        permits = access.can_make_directory if words[0] == "mkdir" else access.can_write
        return bool(paths and all(not p.startswith("-") and permits(p, cwd) for p in paths))
    return bool(cwd and access.verification(words, cwd))
