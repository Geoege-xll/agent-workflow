"""Enforce managed-project ownership at the official Codex PreToolUse boundary."""

from functools import cached_property
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN), str(Path(__file__).resolve().parent)]

from guard_command import (check_runner, options, packaged_helper, shell_allowed,
                           GRAPH_FLAGS, POOL_FLAGS)
from native_event import current_user_message, origin, previous_launcher_result
from lib import task_pool, task_graph_records as records
from lib.hosts.factory import packaged_host
from lib.hosts.handoff import SCRATCH_SLOT_RE, project_scratch_base
from lib.plugin_resources import PLUGIN_ENV
from lib.qa_projection import projection_kind
from lib.safe_text import read_file
from lib.validate_project_docs import project_docs_layout


DENIED = ("xy-workflow: managed project write needs the current claimed and bound Writer "
          "with approved owned_paths. PM should claim, launch and bind the native Writer. "
          "QA is read-only. For a direct PM exception the current user must name the exact target.")
UNVERIFIED = "xy-workflow: could not verify the native Codex event, task record, or physical target."
ADAPTERS = ("project.yaml", ".awf/project.yaml")
PROTECTED = {".git", ".agents", ".agent", ".antigravity", ".awf", ".gemini", ".codex", ".claude"}
MAX_EVENT = 4 * 1024 * 1024


def physical(value, base):
    path = base / value
    if (not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in str(path))
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise ValueError("ambiguous write target")
    try:
        info = path.stat()
    except FileNotFoundError:
        return path
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
        raise ValueError("unsafe write target")
    return path


def managed(root):
    # 先识别既有实际任务池；已损坏或刚改动的适配器不能解除已登记项目的防护。
    if (project_scratch_base(root) / "task-pools").is_dir():
        return True
    for adapter in ADAPTERS:
        if not (root / adapter).is_file():
            continue
        try:
            project_docs_layout(root, Path(adapter))
            return True
        except (ValueError, OSError):
            continue
    return False


def project_for(path):
    """识别当前物理项目及 linked worktree 的真实 Git 共同项目。"""
    for base in (path, *path.parents):
        if not base.is_dir():
            continue
        marker = base / ".git"
        if marker.is_file() and not marker.is_symlink():
            pointer = (read_file(marker) or b"").decode().strip()
            if pointer.startswith("gitdir: "):
                slot = (base / pointer[8:]).resolve(strict=True)
                if slot.parent.name == "worktrees" and slot.parent.parent.name == ".git":
                    back = (read_file(slot / "gitdir") or b"").decode().strip()
                    main = slot.parent.parent.parent
                    if (slot / back).resolve(strict=True) == marker and managed(main):
                        return base, main
        if managed(base):
            return base, base
        # 在无适配器的独立仓库边界停止，避免父目录的另一个项目接管它。
        if marker.exists() or marker.is_symlink():
            return None
    return None


def patch_paths(command):
    lines = command.strip("\n").split("\n")
    if len(lines) < 3 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise ValueError("unsupported apply_patch form")
    paths = []
    update = False
    for line in lines[1:-1]:
        match = re.fullmatch(r"\*\*\* (Add File|Update File|Delete File): (.+)", line)
        if match:
            update = match[1] == "Update File"
            paths.append(match[2])
        elif update and line.startswith("*** Move to: "):
            paths.append(line[len("*** Move to: "):])
            update = False
        elif not line.startswith(("+", "-", " ", "@@", "*** End of File")) and line:
            raise ValueError("unsupported apply_patch record")
    if not paths:
        raise ValueError("apply_patch has no file targets")
    return paths


def explicit_files(message):
    """只接受用户当前直陈且精确列名的授权，禁止从上下文或无路径续句扩大范围。"""
    if not isinstance(message, str):
        return ()
    first = message.strip().split("\n", 1)[0]
    if (re.search(r"如果|假如|仅当|除非|不要|禁止|取消|示例|例如|[？?]", message)
            or re.search(r"\b(?:if|unless|example|cancel|don't|do not)\b", message, re.I)):
        return ()
    match = re.fullmatch(
        r"(?:(?:本次|本轮|这次)?\s*(?:请|让|由)?\s*(?:Codex\s*)?(?:主会话|主代理|PM)"
        r"\s*(?:自己|亲自|本人)\s*(?:直接)?\s*(?:修改|改|编辑|写入|实现|修复)\s*"
        r"|(?:please\s+)?(?:have\s+the\s+)?(?:main\s+session|(?:main\s+)?PM)\s+"
        r"(?:(?:directly|personally)\s+)?(?:edit|implement|fix|write)\s+)"
        r"(?P<files>(?:`[^`\r\n]+`|[\w@+=./-]+)(?:\s*[,、，]\s*(?:`[^`\r\n]+`|[\w@+=./-]+))*)[。!！]?",
        first.strip(), re.I,
    )
    if not match:
        return ()
    return tuple(word.strip().strip("`") for word in re.split(r"[,、，](?=(?:[^`]*`[^`]*`)*[^`]*$)", match["files"]))


class Access:
    def __init__(self, cwd, projects, owner):
        self.cwd = cwd
        self.projects = projects
        self.roots = set(projects)
        self.owner = owner
        self.parent = owner.parent if owner else None
        self.current = owner.thread if owner else None

    @cached_property
    def writer(self):
        if self.owner is None or self.parent is None:
            return None
        ids = {self.current, self.owner.agent_path} - {None}
        return task_pool.bound_writer(
            self.projects, "codex:" + self.parent, "codex", ids, self.cwd)

    @cached_property
    def records(self):
        return {record for root in self.roots for record in task_pool.registered_record_paths(root)}

    def allows_unregistered_write(self, target):
        return all(record != target and not (record.exists() and target.exists() and record.samefile(target))
                   for record in self.records)

    def scratch_file(self, path, project=None):
        path = physical(path, Path("/"))
        for root in (project,) if project else self.roots:
            base = project_scratch_base(root)
            if path.is_relative_to(base):
                parts = path.relative_to(base).parts
                return (len(parts) >= 2 and SCRATCH_SLOT_RE.fullmatch(parts[0])
                        and (base / parts[0]).is_dir()
                        and not any(part.startswith(".") for part in parts)
                        and path.suffix in {".json", ".jsonl", ".md", ".txt", ".log", ".patch", ".diff"})
        return False

    def project_root(self, raw, *, expected=None):
        if raw is None:
            return None
        path = Path(raw)
        if path in self.roots and (expected is None or path == expected):
            return path
        raise ValueError("unverified project")

    def project_input(self, raw, project, *, scratch=False):
        path = physical(raw, project)
        return path.is_relative_to(project) or scratch and self.scratch_file(path, project)

    def workspace_directory(self, raw, *, base=None):
        path = physical(raw, base or Path("/"))
        if path.is_dir() and any(path.is_relative_to(root) for root in self.roots):
            return path
        raise ValueError("unverified working directory")

    @cached_property
    def exception(self):
        return explicit_files(current_user_message(self.owner)) if self.owner else ()

    def _document_layout(self, root):
        main = self.projects[root]
        adapters = [name for name in ADAPTERS if (main / name).is_file()]
        if len(adapters) == 1:
            return project_docs_layout(main, Path(adapters[0]))[1]
        return None

    def can_write(self, raw, cwd):
        target = physical(raw, cwd)
        if not self.owner or target.is_relative_to(PLUGIN) or not self.allows_unregistered_write(target):
            return False
        if self.parent:
            if not self.writer:
                return False
            root, task = self.writer.execution_root, self.writer.task
            relative = target.relative_to(root) if target.is_relative_to(root) else None
            if not relative or not relative.parts:
                return False
            if relative.as_posix().casefold() in ADAPTERS:
                return relative.as_posix() in task["owned_paths"]
            return (not (PROTECTED & {p.casefold() for p in relative.parts})
                    and any(target.is_relative_to(physical(path, root)) for path in task["owned_paths"]))
        if self.scratch_file(target):
            return True
        primary = project_for(self.owner.cwd)
        for root in self.roots:
            if target == root or not target.is_relative_to(root):
                continue
            relative = target.relative_to(root)
            if PROTECTED & {p.casefold() for p in relative.parts} or relative.as_posix().casefold() == "project.yaml":
                continue
            if primary and root == primary[0] and any(physical(name, root) == target for name in self.exception):
                return True
            docs = self._document_layout(root)
            if docs and projection_kind(relative.as_posix(), docs):
                return True
        return False

    def can_make_directory(self, raw, cwd):
        if self.can_write(raw, cwd):
            return True
        target = physical(raw, cwd)
        if self.owner and not self.parent:
            for root in self.roots:
                docs = self._document_layout(root)
                if docs and target in {root / docs["plans"], (root / docs["project"]).parent}:
                    return True
        return False

    def verification(self, argv, cwd):
        if not self.owner or not (check_runner(argv) or self.python_compile(argv, cwd)):
            return False
        if self.parent:
            candidates = [self.writer] if self.writer else []
        else:
            candidates = [task for root in self.roots
                          for task in task_pool.registered_tasks(root, "codex:" + self.current)]
        for candidate in candidates:
            task = candidate.task
            if (task["task_type"] != "writer" or task["state"] not in {"RUNNING", "BUILD_VERIFIED", "QA_SCOPE_READY"}
                    or task.get("withdrawal") or cwd not in {candidate.execution_root,
                                                               candidate.execution_root / task["module"]}):
                continue
            for item in task["verification_commands"]:
                command = item["run"] if isinstance(item, dict) else item
                if shlex.split(command) == argv:
                    return True
        return False

    def python_compile(self, argv, cwd):
        # 仅常规单模块编译。项目指定的精确验证命令仍由原件核对，拒绝路径穿越和解释器选项。
        if argv[0] not in {"python", "python3"} or argv[1:3] != ["-m", "py_compile"] or not argv[3:]:
            return False
        return all(not path.startswith("-") and (source := physical(path, cwd)).is_relative_to(cwd)
                   and source.suffix == ".py" and source.is_file() for path in argv[3:])


def helper(words, access, plugin, cwd, *, redirected=False):
    prefix = ["bash", str(plugin / "lib/python_runtime.sh"), "-B", "-X", "utf8", str(plugin / "plugins/source_pack.py")]
    args = words[len(prefix):]
    if words[:len(prefix)] != prefix:
        return False
    if args[:2] != ["helper", "--project"] or len(args) < 5:
        return packaged_helper(words, access, plugin, cwd, redirected=redirected)
    raw_root, name, action, *rest = args[2:]
    project = access.project_root(raw_root)
    pm = access.current is not None and not access.parent
    identity = "codex:" + access.current if pm else None
    if name == "lib/task_pool_cli.py":
        flags = POOL_FLAGS | {"--request-id", "--evidence", "--preservation"}
        values = options(rest, flags)
        return (pm and action in {"view", "status", "register", "archive", "claim", "release", "bind",
                                 "closeout", "finish-closeout"}
                and values.get("--pm-id") == identity and values.get("--root") == str(project)
                and all(access.scratch_file(project / values[key], project)
                        for key in ("--record", "--receipt", "--evidence", "--preservation") if key in values))
    if name == "lib/task_graph_cli.py":
        values = options(rest, GRAPH_FLAGS)
        if values.get("--pm-id") and (not pm or values["--pm-id"] != identity):
            return False
        if "--root" in values:
            access.project_root(values["--root"], expected=project)
        if "--all" in values:
            return False
        if "--output" in values and not (pm and access.scratch_file(project / values["--output"], project)
                                         and access.can_write(values["--output"], project)):
            return False
        if action in {"validate", "ready", "qa-ready", "capacity", "task", "fingerprints", "continuation",
                      "verify-ui-scope", "verify-solution-scope"}:
            return True
        return pm and (action == "scratch" or action == "cleanup-scratch" and values.get("--pm-id") == identity
                       or action == "init" and "--output" in values
                       or action == "update" and "--input" in values
                       and access.scratch_file(project / values["--input"], project))
    if name == "lib/delivery/worktree_cli.py" and action in {"create", "merge-ready", "merge"}:
        if not pm or redirected:
            return False
        values = options(rest, {"--repo", "--config", "--input", "--path", "--base"})
        if values.get("--repo") != str(project):
            return False
        if action == "create":
            return values.keys() == {"--repo", "--path", "--base"}
        return (values.keys() == {"--repo", "--config", "--input"}
                and access.project_input(values["--config"], project)
                and access.scratch_file(project / values["--input"], project))
    if name == "lib/dispatch_admission_cli.py" and action == "view":
        values = options(rest, {"--input"})
        return "--input" in values and access.project_input(values["--input"], project, scratch=True)
    return packaged_helper(words, access, plugin, cwd, redirected=redirected)


def maintenance(words, access, plugin):
    if not access.owner or access.parent:
        return False
    action = words[2] if len(words) > 2 else ""
    if action not in {"open", "status", "doctor", "rebind"}:
        return False
    base = ["bash", str(plugin / "plugins/maintenance/launcher.sh"), action, "--host", "codex",
            "--project", str(access.owner.cwd)]
    if words[:len(base)] != base:
        return False
    args = words[len(base):]
    invocations = {"$xy-workflow:xy-config " + action, "$xy-config " + action}
    if action == "open":
        invocations.update({"$xy-workflow:xy-config", "$xy-config"})
    message = current_user_message(access.owner)
    if not isinstance(message, str):
        return False
    message = message.strip()
    if not args:
        return message in invocations
    if not re.fullmatch(r"(?:(?:我)?(?:确认|同意|允许)(?:本次|这次)?(?:准备(?:配置)?组件|组件准备|重绑|应用)?"
                        r"(?:[，, ]+(?:使用|离线包)\s*.+)?[。！!]?|(?:yes|confirm|approved)[.!]?)",
                        message, re.I):
        return False
    preview = previous_launcher_result(access.owner, base, invocations)
    if not isinstance(preview, dict):
        return False
    if action == "open" and preview.get("state") == "preparation_required" and args[:1] == ["--prepare"]:
        artifact = args[1:]
        return not artifact or (len(artifact) == 2 and artifact[0] == "--artifact"
                                and Path(artifact[1]).is_absolute() and artifact[1] in message)
    rebound = preview.get("native_rebind")
    return (action == "rebind" and isinstance(rebound, dict) and rebound.get("status") == "preview"
            and isinstance(rebound.get("revision"), str) and len(args) == 2 and args[0] == "--confirm"
            and re.fullmatch(r"[a-f0-9]{64}", args[1]) is not None and args[1] == rebound["revision"])


def bash_allowed(command, access):
    # 标准字面 heredoc 用于任务包、计划或已获准源文件，不运行替换或附加命令。
    heredoc = re.fullmatch(
        r"cat[ \t]+(?P<mode>>>?)[ \t]*(?P<path>[^\r\n]+?)[ \t]+<<[ \t]*'(?P<tag>[A-Za-z0-9_]+)'[ \t]*\n"
        r"(?P<body>.*)\n(?P=tag)\n?", command, re.S)
    if not heredoc:
        heredoc = re.fullmatch(
            r"cat[ \t]+<<[ \t]*'(?P<tag>[A-Za-z0-9_]+)'[ \t]+(?P<mode>>>?)[ \t]*(?P<path>[^\r\n]+)\n"
            r"(?P<body>.*)\n(?P=tag)\n?", command, re.S)
    if heredoc:
        path = heredoc["path"].strip()
        if (not re.fullmatch(r"(?:[\w./+-]+|'[^'\r\n]+')", path)
                or heredoc["tag"] in heredoc["body"].split("\n")):
            return False
        return access.can_write(shlex.split(path)[0], access.cwd)
    command = command.strip()
    if "\n" in command:
        # 命令逐行解释，仅在每一行都能单独核对为只读时保留常见查询批次。
        return all(shell_allowed(line, access.cwd, access, PLUGIN, read_only=True)
                   for line in command.split("\n") if line.strip())
    return shell_allowed(command, access.cwd, access, PLUGIN, helper=helper, maintenance=maintenance)


def decide(event):
    if not isinstance(event, dict):
        raise ValueError("invalid native event")
    if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") not in {"Bash", "apply_patch"}:
        return {}
    cwd = Path(event["cwd"])
    if not cwd.is_absolute():
        return {}  # Native remote path URIs have no local policy or ownership.
    cwd = cwd.resolve(strict=True)
    owner = None
    try:
        owner = origin(event)
    except (ValueError, TypeError, KeyError, OSError):
        # 仍从工具的物理 cwd 识别项目。无法读取 rollout 时，读取照常，写入无授权。
        pass
    command = event["tool_input"]["command"]
    if not isinstance(command, str):
        raise ValueError("invalid command")
    is_patch = event["tool_name"] == "apply_patch"
    targets = patch_paths(command) if is_patch else []
    checks = [cwd, *(cwd / p for p in targets)]
    if owner:
        checks.append(owner.cwd)
    if not is_patch and not any(project_for(path) for path in checks):
        # 外部终端的常规绝对目标也可能指向启用了适配器的项目。
        checks.extend(Path(p) for p in shlex.split(command) if p.startswith("/") and "\n" not in p)
    projects = dict(candidate for path in checks if (candidate := project_for(path)))
    if not projects:
        return {}
    for main in list(projects.values()):
        projects.setdefault(main, main)
    access = Access(cwd, projects, owner)
    allowed = (all(access.can_write(target, cwd) for target in targets) if is_patch
               else bash_allowed(command, access))
    return {} if allowed else deny(DENIED)


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def main():
    try:
        packaged_host(PLUGIN, expected="codex", resources=(
            "hooks/hooks.json", "hooks/write_guard.py", "hooks/native_event.py", "hooks/guard_command.py",
            "lib/task_pool.py", "lib/writer_prerequisites.py", "lib/task_graph_cli.py",
        ))
        os.environ[PLUGIN_ENV] = str(PLUGIN)
        body = sys.stdin.buffer.read(MAX_EVENT + 1)
        if len(body) > MAX_EVENT:
            raise ValueError("event too large")
        result = decide(records.decode(body))
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        result = deny(UNVERIFIED)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
