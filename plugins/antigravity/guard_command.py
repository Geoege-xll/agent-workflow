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
                                 "--files", "--hidden", "--line-number", "--no-heading", "--count"},
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
                "lib/agent_continuation_cli.py", "lib/project/project_profile_cli.py", "lib/delivery/qa_handoff_cli.py"}
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


def read_command(words):
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
        if args[:1] == ["-C"]:
            args = args[2:]
        return bool(args and args[0] in GIT_FLAGS and flags_ok(args[1:], GIT_FLAGS[args[0]]))
    if cmd == "sed":
        # 仅接受查看行范围的标准写法。sed 脚本中的 w/e 具有真正写入/执行能力。
        return (len(args) >= 2 and args[0] == "-n" and re.fullmatch(r"\d+(?:,\d+)?p", args[1])
                and all(not path.startswith("-") for path in args[2:]))
    if cmd == "echo":
        return True
    if cmd == "printf":
        return bool(args and not args[0].startswith("-"))
    if cmd in READ_FLAGS:
        return flags_ok(args, READ_FLAGS[cmd])
    return False


def options(args, permitted):
    """拒绝 argparse 的缩写、重复及嵌套选项；核对的目标必须与下游实际读取的一致。"""
    values = {}
    i = 0
    while i < len(args):
        flag = args[i]
        if flag not in permitted or flag in values and flag not in ("--keep", "--select"):
            raise ValueError("不支持的参数")
        if flag in {"--register", "--dry-run", "--all"}:
            values[flag] = True
            i += 1
        else:
            if i + 1 >= len(args) or args[i + 1].startswith("-"):
                raise ValueError("缺少确定的参数值")
            values[flag] = args[i + 1]
            i += 2
    return values


def packaged_helper(words, access, plugin):
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
    if len(args) < 5 or args[:2] != ["helper", "--project"]:
        return False
    project = Path(args[2])
    if project not in access.roots:
        return False
    helper, action, *rest = args[3:]
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
        return (not access.parent and values.get("--root") == str(project)
                and values.get("--pm-id") == "antigravity:" + access.current
                and all(access.scratch_file(project / values[key]) for key in ("--record", "--receipt") if key in values))
    if helper == "lib/task_graph_cli.py":
        values = options(rest, GRAPH_FLAGS)
        if values.get("--root", str(project)) != str(project):
            return False
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
    return False


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
    raw_cwd = args.get("Cwd") or access.cwd
    if raw_cwd and not Path(raw_cwd).is_absolute():
        # 相对 Cwd 在宿主与 Hook 进程可能具有不同基准，不能用插件进程 cwd
        # 猜测业务写入落点。省略值仍使用上方核实的唯一工作区。
        return False
    cwd = Path(raw_cwd).resolve(strict=True) if raw_cwd else None
    if cwd and not any(cwd.is_relative_to(root) for root in access.roots):
        return False
    # 仅识别无二次解释的独立命令。保守地先排除变量/替换/多行/控制符，即使它们
    # 出现在引号中；需要复杂文本的任务包和计划用原生 write_file 保留原始字节。
    if not isinstance(line, str) or any(ch in line for ch in "\n\r\0$`;<(){}!~\\"):
        return False
    lexer = shlex.shlex(line, posix=True, punctuation_chars=">&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    words = list(lexer)
    if not words:
        return False
    # 区分字面的查询模式与真正由 shell 展开的文件名。前者可供 find/rg 或偏好
    # 查询使用，后者可能在命令执行时注入未核对的谓词、选项或多个输出文件。
    unquoted = re.sub("'[^']*'|\"[^\"]*\"", "", line)
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
        return all(part and read_command(part) for part in parts)
    redirect = next((i for i, word in enumerate(words) if ">" in word), None)
    if redirect is not None:
        if (redirect != len(words) - 2 or words[redirect] not in {">", ">>"} or redirect == 0
                or not access.can_write(words[-1], cwd)):
            return False
        words = words[:redirect]
    if words[:2] == ["bash", str(plugin / "plugins/maintenance/launcher.sh")]:
        return redirect is None and maintenance_allowed(words, access, plugin)
    if read_command(words) or packaged_helper(words, access, plugin):
        return True
    if words[0] in {"touch", "mkdir"}:
        paths = words[1:]
        if words[0] == "mkdir" and paths[:1] == ["-p"]:
            paths = paths[1:]
        permits = access.can_make_directory if words[0] == "mkdir" else access.can_write
        return bool(paths and all(not p.startswith("-") and permits(p, cwd) for p in paths))
    return bool(cwd and access.verification(words, cwd))
