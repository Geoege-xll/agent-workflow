"""任务包内的验证命令及其显式文件输入。只核对字节变化，不执行项目命令或判定通过。"""

from pathlib import Path, PurePosixPath

from lib.task_graph import TaskGraphError


def validate_command(command, label):
    """原字符串及 run/expected 二字段对象保持兼容。inputs 只接受逐一核实的项目文件；
    没有可界定的依赖集合时，保留旧表达，由实现者和 QA 核实证据适用性。
    """
    if isinstance(command, str) and command.strip():
        return
    if (not isinstance(command, dict) or not {"run", "expected"} <= command.keys() <= {"run", "expected", "inputs"}
            or not all(isinstance(command[key], str) and command[key].strip() for key in ("run", "expected"))):
        raise TaskGraphError(f"{label} requires a command string or run and expected")
    if "inputs" in command:
        inputs = command["inputs"]
        if not isinstance(inputs, list) or not inputs:
            raise TaskGraphError(f"{label}.inputs must contain explicit project files")
        for name in inputs:
            if (not isinstance(name, str) or not name.strip() or "\\" in name
                    or not PurePosixPath(name).parts or PurePosixPath(name).is_absolute()
                    or PurePosixPath(name).as_posix() != name or ".." in PurePosixPath(name).parts):
                raise TaskGraphError(f"{label}.inputs requires normalized project-relative files")
        if len(set(inputs)) != len(inputs):
            raise TaskGraphError(f"{label}.inputs must not contain duplicate paths")


def command_fingerprints(root: Path, pack, run, previous):
    """以已校验的单包定位一个命令，使用现有文件读取器生成或复核对应的输入指纹。

    任务、命令、预期或文件集合变更时不能复用旧比对。其它命令、任务包序列化及
    无关文件不参与当前命令指纹；匹配仅表示列出的文件一致，仍需检查实际运行证据。
    """
    from lib.task_graph_records import fingerprints
    task = pack["task"]
    commands = [item for item in task.get("verification_commands", [])
                if (item.get("run") if isinstance(item, dict) else item) == run]
    if len(commands) != 1 or not isinstance(commands[0], dict) or not commands[0].get("inputs"):
        raise TaskGraphError("the selected command must occur once and declare explicit file inputs")
    command = commands[0]
    validate_command(command, "verification command")
    if "execution_workspace" in task:
        workspace = task["execution_workspace"]
        if (not isinstance(workspace, dict) or not isinstance(workspace.get("root"), str)
                or not Path(workspace["root"]).is_absolute()
                or Path(workspace["root"]).resolve(strict=True) != root.resolve(strict=True)):
            raise TaskGraphError("verification input root differs from the task's execution workspace")
    scope = {"root": str(root.resolve(strict=True)), "request_id": task["request_id"], "task_id": task["id"],
             "module": task["module"], "run": run, "expected": command["expected"]}
    if previous is None:
        return {"scope": scope, **fingerprints(root, command["inputs"], [])}
    # 只接受同一命令首次取证时的原映射。去掉失效文件、改命令或替换工作树都会
    # 使旧证据失去适用依据，不能把一次部分比对包装成整条命令仍然有效。
    if (not isinstance(previous, dict) or previous.get("scope") != scope
            or not isinstance(previous.get("fingerprints"), dict)
            or set(previous["fingerprints"]) != set(command["inputs"])):
        raise TaskGraphError("previous fingerprints differ in command, task, execution root or declared inputs")
    return {"scope": scope, **fingerprints(root, previous["fingerprints"], [])}
