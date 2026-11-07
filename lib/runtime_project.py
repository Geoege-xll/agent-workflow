"""准备中央项目的薄入口、三宿主角色和固定版本 Skill 软链。

这里只描述资源及其安全前后像，不登记项目或执行 Agent。项目根、配置路径和
核心根始终显式传递；核心的父目录绝不被当作业务项目。普通读取拒绝所有链接，
仅精确宿主 Skill 叶节点另有受管分支，供服务在验证归属和核心后使用。
"""

from __future__ import annotations

import base64
import ast
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
import tomllib

from .platform_fs import os
from . import runtime_store as store


LOCATOR = ".agent-workflow/runtime.json"
LAUNCHER = ".agent-workflow/runtime.py"
PYTHON_ENTRY = ".agent-workflow/lib/python_runtime.sh"
WINDOWS_ENTRY = ".agent-workflow/lib/python_runtime.cjs"
WINDOWS_PATHS = ".agent-workflow/lib/windows-runtime.paths"
CONFIG = ".agent-workflow/project.yaml"
CENTRAL_BEGIN = "<!-- agent-workflow-pack:central-begin -->"
CENTRAL_END = "<!-- agent-workflow-pack:central-end -->"
MARKER = "agent-workflow-central-project"
HOSTS = ("codex", "claude", "antigravity")
ROLE_PATHS = {"codex": (".codex/agents", ".toml"),
              "claude": (".claude/agents", ".md"),
              "antigravity": (".agents/agents", ".md")}
SKILL_NAME = re.compile(r"(?:xy-[a-z0-9]+(?:-[a-z0-9]+)*|grill-me)\Z")
LIMIT = 4 * 1024 * 1024
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)


class ProjectRuntimeError(ValueError):
    """项目资源不合法、发生并发变化或跨越了受管边界。"""


def json_bytes(value: object) -> bytes:
    body = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(body) > LIMIT:
        raise ProjectRuntimeError("中央项目记录超过有界读取范围")
    return body


def unique_json(body: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProjectRuntimeError("中央项目 JSON 含重复字段")
            result[key] = value
        return result
    try:
        return json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProjectRuntimeError("中央项目记录不是有效的 UTF-8 唯一字段 JSON") from exc


def relative_path(raw: str) -> str:
    """采用规范 POSIX 逻辑路径，拒绝别名、Windows ADS 和目录跳转。"""
    if (not isinstance(raw, str) or not raw or "\\" in raw or ":" in raw
            or any(ord(char) < 32 for char in raw)
            or any(part in {"", ".", ".."} or part.rstrip(" .") != part for part in raw.split("/"))):
        raise ProjectRuntimeError("受管路径必须是规范的根内相对路径")
    return raw


def canonical_project(project: Path) -> Path:
    path = Path(project).expanduser().absolute()
    if os.name == "nt":
        from .windows_fs import Directory
        # resolve 可能擦掉 junction/祖先重解析点，必须先按原路径逐段拒绝。
        with Directory(path):
            pass
    if path.is_symlink() or not path.is_dir():
        raise ProjectRuntimeError("项目必须是已存在的真实目录")
    # 物理根是机器隔离键；memory.project_id 仍只是项目的可移植记忆身份。
    return path.resolve(strict=True)


def project_key(project: Path) -> str:
    return hashlib.sha256(str(project).encode("utf-8")).hexdigest()


def node_id(info) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_at(parent: int, name: str, *, allow_link: bool = False) -> Node:
    """读取已锚定父目录中的节点；链接开关仅供精确受管叶或已登记恢复资料。

    对外普通项目读取仍由 Tree.read 约束路径，不能借本内部事务原语读取任意
    链接目标。链接只取 readlink 字节，从不打开它指向的文件。
    """
    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return Node()
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISLNK(before.st_mode) and allow_link:
        body = os.fsencode(os.readlink(name, dir_fd=parent))
    elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= LIMIT:
        descriptor = os.open(name, READ_FLAGS, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            if identity(os.fstat(stream.fileno())) != identity(before):
                raise ProjectRuntimeError("节点在打开时变化")
            body = stream.read(LIMIT + 1)
            after = os.fstat(stream.fileno())
        if len(body) > LIMIT or identity(after) != identity(before):
            raise ProjectRuntimeError("节点在读取期间变化")
    else:
        raise ProjectRuntimeError("节点必须是有界单链接普通文件")
    if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(before):
        raise ProjectRuntimeError("节点在读取期间被替换")
    return Node("link" if stat.S_ISLNK(before.st_mode) else "file", body, mode, identity(before))


@dataclass(frozen=True)
class Node:
    """一个真实节点的有界快照；identity 用于预览条件，payload 用于精确恢复。"""

    kind: str = "missing"
    payload: bytes = b""
    mode: int = 0
    identity: tuple = ()

    def value(self) -> dict:
        return {"kind": self.kind, "body": base64.b64encode(self.payload).decode("ascii"),
                "mode": self.mode, "identity": list(self.identity)}

    @classmethod
    def from_value(cls, raw: dict) -> Node:
        if (not isinstance(raw, dict) or set(raw) != {"kind", "body", "mode", "identity"}
                or raw["kind"] not in {"missing", "file", "link"}
                or type(raw["mode"]) is not int or not 0 <= raw["mode"] <= 0o7777
                or not isinstance(raw["identity"], list)
                or not all(type(item) is int for item in raw["identity"])):
            raise ProjectRuntimeError("中央项目节点快照无效")
        try:
            body = base64.b64decode(raw["body"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ProjectRuntimeError("中央项目节点恢复正文无效") from exc
        if len(body) > LIMIT or len(raw["identity"]) not in {0, 7}:
            raise ProjectRuntimeError("中央项目节点快照超过边界")
        return cls(raw["kind"], body, raw["mode"], tuple(raw["identity"]))

    def same_content(self, other: Node) -> bool:
        # macOS 的新软链模式受 umask 影响，Linux 通常固定 0777；链接模式不
        # 决定目标访问权限，期望资源只比较目标。真实前像仍保存并比较完整 mode/
        # inode，归属与恢复另显式检查已经发布节点的实际模式，不能豁免换链。
        # Windows 普通文件只按正文匹配期望资源；其 mode 是只读属性投影，
        # 私有性另核真实 DACL，发布/补偿仍保留完整前像身份与原叶权限。
        if self.kind == other.kind == "link" or (os.name == "nt" and self.kind == other.kind == "file"):
            return self.payload == other.payload
        return (self.kind, self.payload, self.mode) == (other.kind, other.payload, other.mode)


@contextmanager
def absolute_directory(path: Path, *, create: bool = False):
    """逐段锚定祖先，不沿任何链接创建目录；退出时核对路径仍指向原目录。"""
    path = Path(path).expanduser().absolute()
    if ".." in path.parts:
        raise ProjectRuntimeError("机器状态路径不能含上级跳转")
    descriptors, chain = [], []
    try:
        parent = os.open(path.anchor, DIR_FLAGS)
        descriptors.append(parent)
        for name in path.parts[1:]:
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent)
                    os.fsync(parent)
                except FileExistsError:
                    pass
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise ProjectRuntimeError("目录路径包含链接或特殊节点")
            child = os.open(name, DIR_FLAGS, dir_fd=parent)
            descriptors.append(child)
            if node_id(os.fstat(child)) != node_id(before):
                raise ProjectRuntimeError("目录在打开时被替换")
            chain.append((parent, name, node_id(before)))
            parent = child
        if create and os.name == "nt":
            from .windows_fs import assert_private
            assert_private(path)
        yield parent
        for parent, name, expected in chain:
            if node_id(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected:
                raise ProjectRuntimeError("目录在操作期间被替换，已保留原目录中的事务资料")
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


class Tree:
    """同一事务内保留项目父目录描述符，防止目录换链把写入带到项目外。"""

    def __init__(self, root: Path):
        self.root = root
        self._context = absolute_directory(root)
        self.directories = {}
        self.links = []

    def __enter__(self):
        self.directories[""] = self._context.__enter__()
        return self

    def __exit__(self, *failure):
        try:
            if not failure[0]:
                self.check()
        finally:
            for relative, descriptor in reversed(list(self.directories.items())):
                if relative:
                    os.close(descriptor)
            self._context.__exit__(*failure)

    def check(self):
        for parent, name, expected in self.links:
            try:
                actual = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise ProjectRuntimeError("受管父目录在事务中消失") from exc
            if node_id(actual) != expected or not stat.S_ISDIR(actual.st_mode):
                raise ProjectRuntimeError("受管父目录在事务中被替换，保留原目录中的恢复资料")

    def directory(self, relative: str, *, create: bool = False, created: list | None = None) -> int:
        if relative in self.directories:
            return self.directories[relative]
        relative_path(relative)
        prefix = ""
        parent = self.directories[""]
        for name in relative.split("/"):
            prefix = f"{prefix}/{name}" if prefix else name
            if prefix in self.directories:
                parent = self.directories[prefix]
                continue
            if create:
                try:
                    os.mkdir(name, 0o700 if prefix.startswith(".agent-workflow") else 0o755, dir_fd=parent)
                    os.fsync(parent)
                    if created is not None:
                        created.append(prefix)
                except FileExistsError:
                    pass
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise ProjectRuntimeError(f"受管父目录不能是链接或特殊节点：{prefix}")
            child = os.open(name, DIR_FLAGS, dir_fd=parent)
            if node_id(os.fstat(child)) != node_id(before):
                os.close(child)
                raise ProjectRuntimeError(f"受管父目录在打开时变化：{prefix}")
            self.links.append((parent, name, node_id(before)))
            self.directories[prefix] = child
            parent = child
        return parent

    def parent(self, relative: str, *, create: bool = False, created: list | None = None):
        relative_path(relative)
        parent, _, name = relative.rpartition("/")
        return self.directory(parent, create=create, created=created), name

    def read(self, relative: str, *, skill_link: bool = False) -> Node:
        try:
            parent, name = self.parent(relative)
        except FileNotFoundError:
            return Node()
        return read_at(parent, name, allow_link=bool(skill_link and skill_parts(relative)))

    def directory_facts(self, paths: list[str]) -> tuple:
        facts = {"": (*node_id(os.fstat(self.directories[""])), stat.S_IMODE(os.fstat(self.directories[""]).st_mode))}
        for relative in paths:
            prefix = ""
            for name in relative_path(relative).split("/")[:-1]:
                prefix = f"{prefix}/{name}" if prefix else name
                try:
                    descriptor = self.directory(prefix)
                except FileNotFoundError:
                    facts[prefix] = None
                else:
                    info = os.fstat(descriptor)
                    facts[prefix] = (*node_id(info), stat.S_IMODE(info.st_mode))
        return tuple(sorted(facts.items()))


def skill_parts(relative: str) -> tuple[str, str] | None:
    parts = relative.split("/")
    if len(parts) == 3 and parts[:2] in ([".agents", "skills"], [".claude", "skills"]) and SKILL_NAME.fullmatch(parts[2]):
        return parts[0], parts[2]
    return None


def managed_path(relative: str, purpose: str) -> bool:
    """机器记录也视为外部数据，只能授权协议列出的精确原生/薄桥路径。"""
    relative_path(relative)
    if purpose == "skill":
        return skill_parts(relative) is not None
    fixed = {"locator": {LOCATOR}, "bridge": {LAUNCHER, PYTHON_ENTRY, WINDOWS_ENTRY, WINDOWS_PATHS, ".agent-workflow/lib/workflow_hooks.py"},
             "block": {"AGENTS.md", "CLAUDE.md"}, "native-config": {".codex/config.toml"}}
    if purpose in fixed:
        return relative in fixed[purpose]
    if purpose == "role":
        from .role_models import ROLES
        return any(relative == f"{directory}/{role}{suffix}" for directory, suffix in ROLE_PATHS.values() for role in ROLES)
    return False


def hook_bridge_source() -> bytes:
    """当前受管 Hook 的固定版本薄入口；不加载项目代码或猜已有任务的 pin。"""
    return '''"""当前受管 Hook 的薄入口；不改宿主命令/信任，不猜进行中任务版本。"""
import os
import sys
if os.name == "nt":
    _capabilities = {key: globals().get(key) for key in
                     ("__agent_workflow_windows_fs__", "__agent_workflow_trusted_path__")}
    if _capabilities["__agent_workflow_windows_fs__"] is None:
        print("{}")
        raise SystemExit(0)
    sys.path[:] = _capabilities["__agent_workflow_trusted_path__"]
else:
    _capabilities = {}
from pathlib import Path
import runpy
import json
import subprocess
import sys

entry = Path(__file__).absolute().parent.parent / "runtime.py"
if not os.environ.get("AGENT_WORKFLOW_RUNTIME_BINDING"):
    # 无任务 pin 时只选择已启用项目的当前提醒脚本，不创建或改写任何任务 pin。
    # 真实 check 拒绝未知/损坏版本和停用项目；辅助层失败始终保持宿主协议中性。
    try:
        prefix = [sys.executable, "-B", "-X", "utf8"]
        if os.name == "nt":
            prefix = [sys.executable, "-I", "-B", "-X", "utf8", os.environ["AGENT_WORKFLOW_BOOTSTRAP"], "--script"]
        checked = subprocess.run([*prefix, str(entry), "check"],
                                 capture_output=True, timeout=2, check=False)
        if checked.returncode != 0:
            raise ValueError("inactive workflow")
        os.environ["AGENT_WORKFLOW_RUNTIME_BINDING"] = json.dumps(json.loads(checked.stdout)["runtime_binding"])
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print("{}")
        raise SystemExit(0)
sys.argv = [str(entry), "helper", "lib/workflow_hooks.py", *sys.argv[1:]]
runpy.run_path(str(entry), run_name="__main__", init_globals=_capabilities)
'''.encode("utf-8")


def native_projection(body: bytes) -> tuple:
    """Codex 只拥有三个 agents 默认键及有签名 Hook 区；其他字段可由用户继续编辑。"""
    from .workflow_hook_install import managed_inline
    data = tomllib.loads(body.decode("utf-8"))
    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        raise ProjectRuntimeError("Codex agents 必须为配置表")
    keys = ("enabled", "max_concurrent_threads_per_session", "interrupt_message")
    return tuple((key, key in agents, agents.get(key)) for key in keys), managed_inline(body)


def restore_native(current: Node, baseline: Node, expected: Node) -> Node:
    """停用时仅撤回工作流 agents 键和签名 Hook；保留后来添加的用户字段和权限。"""
    from .merge_codex_config import AGENTS_BEGIN, AGENTS_END, TABLE_RE, render
    from .workflow_hook_install import managed_inline, merge_inline
    if current.kind == "missing":
        return current  # 已停用且缺失的原生容器保持幂等，不能补出一个空配置。
    expected_agents = tomllib.loads(expected.payload.decode("utf-8")).get("agents", {})
    threads = expected_agents.get("max_concurrent_threads_per_session", 8)
    rebuilt = render(baseline.payload.decode("utf-8"), threads).encode()
    block = managed_inline(expected.payload)
    if block:
        rebuilt += block + b"\n"
    # expected 会在 repair/use 后刷新，不能据“当前等于 expected”还原整个最初
    # baseline，否则会吞掉已经纳入 expected 的后加用户字段。只有最初用户
    # 字节经过当前生成器能精确重建现状时，才允许恢复其原格式或缺失状态。
    if current.payload == rebuilt:
        return Node("file", baseline.payload, current.mode) if baseline.kind == "file" else baseline
    original = tomllib.loads(baseline.payload.decode("utf-8")) if baseline.kind == "file" else {}
    prior = original.get("agents", {})
    keys = {"enabled", "max_concurrent_threads_per_session", "interrupt_message"}
    text = merge_inline(current.payload, Path("/"), Path("/"), "off").decode("utf-8")
    lines = []
    in_agents = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped in {AGENTS_BEGIN, AGENTS_END}:
            continue
        if stripped.startswith("["):
            table = TABLE_RE.match(line)
            in_agents = bool(table and table[1].strip() == "agents")
        match = re.match(r"\s*([a-z_]+)\s*=", line) if in_agents else None
        if match and match[1] in keys:
            if match[1] in prior:
                lines.append(match[1] + " = " + json.dumps(prior[match[1]]) + "\n")
            continue
        lines.append(line)
    restored = "".join(lines)
    # 空表可保留，避免删除同一表下用户注释；语义与 TOML 有效性在发布前复核。
    tomllib.loads(restored)
    return Node("file", restored.encode("utf-8"), current.mode or 0o644)


def hook_resources(project: Path, config: bytes, hosts: tuple[str, ...], *,
                   enabled: bool = True, check_only: bool = False,
                   codex_after: Node | None = None) -> dict[str, tuple[Node, str]]:
    """内存配置驱动的当前 Hook 资源计划；仅签名条目归工作流，原生容器始终共享。

    guard 行由普通条件事务发布但不登记整文件独占；后续 repair/use/disable
    每次重新合并当前用户设置。watch 行绑定只读输入，防止预览后本地层变化。
    """
    from .workflow_hook_install import (BEGIN, json_object, managed_inline, managed_json,
                                        merge_inline, merge_json)
    from .workflow_hook_settings import hook_mode
    from .claude_options import parse
    mode = hook_mode(config.decode("utf-8")) if enabled else "off"
    options = parse(config.decode("utf-8"))
    desired = {}
    pack = project / ".agent-workflow"
    with Tree(project) as tree:
        for host in hosts:
            if host == "codex":
                native = tree.read(".codex/config.toml")
                existing = tree.read(".codex/hooks.json")
                data = json_object(existing.payload if existing.kind == "file" else None)
                parsed = tomllib.loads(native.payload.decode("utf-8"))
                signed = managed_json(data, host)
                if ("hooks" in parsed or BEGIN.encode() in native.payload) and not signed:
                    source = codex_after if codex_after is not None else native
                    after = merge_inline(source.payload, pack, project, mode)
                    if check_only:
                        if managed_inline(native.payload) != managed_inline(after):
                            raise ProjectRuntimeError("Codex 受管 Hook 缺失或偏离当前配置")
                    else:
                        desired[".codex/config.toml"] = (Node("file", after, native.mode or 0o644), "native-config")
                    desired[".codex/hooks.json"] = (existing, "watch")
                    continue
                relative = ".codex/hooks.json"
            else:
                relative = ".claude/settings.json" if host == "claude" else ".agents/hooks.json"
                existing = tree.read(relative)
                data = json_object(existing.payload if existing.kind == "file" else None)
            local = None
            if host == "claude" and options["block_writes_outside_working_directories"] is True:
                local_node = tree.read(".claude/settings.local.json")
                local = json_object(local_node.payload if local_node.kind == "file" else None)
                desired[".claude/settings.local.json"] = (local_node, "watch")
            merged = merge_json(data, pack, project, host, mode, claude_options=options if host == "claude" else None,
                                local_settings=local)
            if check_only:
                guard_missing = (host == "claude" and local is not None
                                 and data.get("permissions", {}).get("blockWritesOutsideWorkingDirectories") is not True)
                if managed_json(data, host) != managed_json(merged, host) or guard_missing:
                    raise ProjectRuntimeError(host + " 受管 Hook 或显式写入保护缺失")
                continue
            after = existing if merged == data else Node("file", (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode(), existing.mode or 0o644, existing.identity)
            # off 且从未创建容器时保持真正无操作；不制造空的 JSON 文件。
            desired[relative] = (after, "guard")
    return desired


def claude_write_guard(project: Path, config: bytes, *, check_only: bool = False) -> dict[str, tuple[Node, str]]:
    """仅为显式 true 准备单键条件收紧；inherit 不读取/改写宿主设置。

    settings 的其余内容始终由用户/宿主所有，不能登记为整文件独占资源。
    local 只有前像观察行，绝不发布；状态检查复用同一纯合并函数但不写入。
    """
    from .claude_options import parse
    if parse(config.decode("utf-8"))["block_writes_outside_working_directories"] is not True:
        return {}
    from .workflow_hook_install import json_object, merge_claude_write_guard
    with Tree(project) as tree:
        settings = tree.read(".claude/settings.json")
        local = tree.read(".claude/settings.local.json")
    data = json_object(settings.payload if settings.kind == "file" else None)
    merged = merge_claude_write_guard(data, json_object(local.payload if local.kind == "file" else None))
    if check_only:
        if merged != data:
            raise ProjectRuntimeError("已配置的 Claude 项目写入保护尚未落地；请先预览 repair")
        return {}
    after = settings.payload if merged == data and settings.kind == "file" else (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode()
    return {".claude/settings.json": (Node("file", after, settings.mode or 0o600, settings.identity), "guard"),
            ".claude/settings.local.json": (local, "watch")}


@dataclass(frozen=True)
class Resources:
    root: Path
    binding_json: bytes
    label: str
    frozen: store.FrozenCore | None = None

    @property
    def binding(self) -> dict:
        return store.validate_binding(unique_json(self.binding_json))

    def read(self, relative: str) -> bytes:
        if self.frozen is not None:
            return store.read_core_source(self.frozen, relative)
        # 源码读取仅供显式 source_root 的无写入预览。前后 inspect_core 守卫
        # 由业务服务负责，不能把这个分支暴露成项目/Task Pack 的外部核心读取器。
        with Tree(self.root) as tree:
            value = tree.read(relative)
        if value.kind != "file":
            raise ProjectRuntimeError(f"核心来源缺少必要文件：{relative}")
        return value.payload


def skill_names(resources: Resources) -> tuple[str, ...]:
    names = []
    for raw in resources.read("platforms/shared/core-skills.txt").decode("utf-8").splitlines():
        name = raw.strip()
        if not name or name.startswith("#"):
            continue
        if not SKILL_NAME.fullmatch(name) or name in names:
            raise ProjectRuntimeError("共享 Skill 清单含无效或重复名称")
        body = resources.read(f"platforms/shared/skills/{name}/SKILL.md")
        from .shared_core_skills import parse_managed_skill_bytes
        parse_managed_skill_bytes(body, name)
        names.append(name)
    if not names:
        raise ProjectRuntimeError("共享 Skill 清单不能为空")
    return tuple(names)


def validate_skill_link(tree: Tree, relative: str, node: Node, core: store.FrozenCore) -> None:
    """只对机器记录已证明归属的精确 Skill 叶验证固定目标，绝不跟随未知链接。"""
    parts = skill_parts(relative)
    if parts is None or node.kind != "link":
        raise ProjectRuntimeError(f"受管 Skill 不是精确宿主软链：{relative}")
    expected = core.root / "platforms/shared/skills" / parts[1]
    if node.payload != os.fsencode(expected):
        raise ProjectRuntimeError(f"受管 Skill 链接目标已被替换：{relative}")
    # read_core_source 会验证完整清单、ID、普通文件集合和目标文件，不把 exists()
    # 或 resolve() 的成功当作链接安全证明；死链与损坏核心均在此正常失败。
    body = store.read_core_source(core, f"platforms/shared/skills/{parts[1]}/SKILL.md")
    from .shared_core_skills import parse_managed_skill_bytes
    parse_managed_skill_bytes(body, parts[1])
    if tree.read(relative, skill_link=True) != node:
        raise ProjectRuntimeError(f"受管 Skill 在验证期间换链：{relative}")


def central_block(body: bytes) -> bytes | None:
    text = body.decode("utf-8", errors="strict")
    begin, end = text.count(CENTRAL_BEGIN), text.count(CENTRAL_END)
    if not begin and not end:
        return None
    if begin != 1 or end != 1:
        raise ProjectRuntimeError("中央入口标记重复或缺失")
    pattern = re.compile(r"(?m)^" + re.escape(CENTRAL_BEGIN) + r"\r?\n[\s\S]*?^" + re.escape(CENTRAL_END) + r"(?:\r?\n|$)")
    match = pattern.search(text)
    if match is None:
        raise ProjectRuntimeError("中央入口标记不是独立完整行")
    return match[0].encode()


def merge_central_block(body: bytes, block: bytes) -> bytes:
    old = central_block(body)
    if old is not None:
        return body.replace(old, block, 1)
    if not block:
        return body
    separator = b"" if not body or body.endswith(b"\n\n") else b"\n" if body.endswith(b"\n") else b"\n\n"
    return body + separator + block


def initial_config(resources: Resources, project: Path) -> bytes:
    from .ensure_project_id import derive_project_id, _replace_placeholder
    from .validate_project_config import PROJECT_ID_RE
    body = resources.read("templates/project.yaml.example")
    body = re.sub(rb"(?m)^project_name:[^\r\n]*", ("project_name: " + json.dumps(project.name, ensure_ascii=False)).encode(), body, count=1)
    project_id = derive_project_id(project.name)
    if not PROJECT_ID_RE.fullmatch(project_id):
        # 只处理新建适配器。沿既有非 ASCII 名称的稳定哈希惯例约束长度，避免
        # 长名称/单字母名称第一次成功写入、下一次启停才被同一验证器拒绝。
        project_id = "project-" + hashlib.sha256(project.name.encode("utf-8")).hexdigest()[:12]
    return _replace_placeholder(body, project_id) or body


def configuration(resources: Resources, project: Path, config: Node, *, owned_links: set[str]) -> tuple[bytes, object, dict]:
    """复用原适配器验证/发现，不让中央默认值覆盖已有项目配置。

    原验证器的普通输出安全检查仍拒绝全部链接。只有服务预先证明归属并调用
    validate_skill_link 验证成功的精确 Skill 路径，才在此剔除对应旧输出诊断；
    文档、角色、父目录以及未知链接的诊断仍完整保留。
    """
    from .validate_project_config import validate_with_profile, validate_docs, section_lines, strip_inline_comment
    body = config.payload if config.kind == "file" else initial_config(resources, project)
    config_path = project / CONFIG
    result = validate_with_profile(config_path, project, resources.root / "roles", config_bytes=body)
    allowed = {path for relative in owned_links for path in (relative, relative + "/SKILL.md")}
    errors = []
    for error in result.errors:
        if any(error == prefix + path for path in allowed for prefix in (
                "managed output resolves outside project root: ", "managed output must not use symlinks: ")):
            continue
        errors.append(error)
    if errors or result.profile is None:
        # 原验证器的部分错误含用户原始标量（例如错误模型 JSON），不能直接转发
        # 给 CLI/TUI 或预览日志。这里只投影安全类别；原文仍留在项目适配器中。
        if any("unsupported docs key: notes" in error or "unsupported memory key: fallback_dir" in error for error in errors):
            raise ProjectRuntimeError("已废弃的文档配置必须先明确处理，enable 不会静默删除用户配置")
        raise ProjectRuntimeError(f"项目配置需要先显式处理：{len(errors)} 项校验错误；未显示适配器正文")
    lines = body.decode("utf-8", errors="strict").splitlines()
    docs_errors = []
    docs = validate_docs(lines, project, docs_errors)
    if docs_errors:
        raise ProjectRuntimeError("项目文档路径配置无效：" + "; ".join(docs_errors))
    name = project.name
    from .validate_project_config import parse_project_name
    for line in lines:
        if line.startswith("project_name:"):
            name = parse_project_name(line.split(":", 1)[1])
    memory = {match[1]: strip_inline_comment(match[2]).strip("\"'")
              for line in section_lines(lines, "memory")
              if (match := re.match(r"  ([a-z_]+):\s*(.*)", line))}
    return body, result.profile, {"docs": docs, "project_name": name, "memory": memory}


def role_resource(resources: Resources, config: bytes, host: str, role: str, binding: dict,
                  *, preferences: dict | None = None) -> bytes:
    from .role_models import parse as parse_models
    from .role_preferences import resolve
    from .claude_options import parse as parse_claude
    from .role_skills import ROLE_SKILLS
    source = resources.read(f"roles/{role}.md").decode("utf-8", errors="strict")
    match = re.search(r"(?m)^description:\s*(.+)$", source)
    description = match[1].strip().strip('"') if match else role
    models = parse_models(config.decode())
    # 全局默认属于可变用户状态，不写回项目适配器，更不写入固定核心。这里仅
    # 物化按字段解析后的模型/推理值；原有正文、工具白名单和任务 pin 继续原样生成。
    settings, _ = resolve(preferences or {}, models, host, role)
    selected = json.dumps(binding, sort_keys=True, separators=(",", ":"))
    command = f"bash {PYTHON_ENTRY} -B -X utf8 {LAUNCHER}"
    instructions = (
        f"Central project role {role}. Execute only the PM's current task pack; do not launch other Agents.\n"
        f"Without a local activation record, stop and report inactive; first run `{command} check` for new tasks.\n"
        f"This entry pins runtime_binding={selected}. Existing tasks must prioritize their task pack's runtime_binding, "
        "without reading the current project version after a switch; stop if a central task lacks a pin.\n"
        f"Use `{command} --binding '<selected-three-field-JSON>' read roles/{role}.md` to read the complete role source, "
        "and the same binding to read product/WORKFLOW.md, product/GLOBAL_CONSTRAINTS.md, and required Skills.\n"
        f"The configuration path is explicitly {CONFIG}, and the business root is the current project; only the local bridge resolves the core root.\n"
        "Role fields do not prove parent-session permission, provider, or MCP isolation; respect native boundaries without fabricating isolation.\n"
    )
    if host == "codex":
        fields = [f'name = {json.dumps(role)}', f'description = {json.dumps(description, ensure_ascii=False)}']
        if settings.get("model", "inherit") != "inherit":
            fields.append(f'model = {json.dumps(settings["model"])}')
        if settings.get("effort", "inherit") != "inherit":
            fields.append(f'model_reasoning_effort = {json.dumps(settings["effort"])}')
        fields.append("developer_instructions = " + json.dumps(instructions, ensure_ascii=False))
        payload = ("\n".join(fields) + "\n").encode()
        # 沿现有 role_models.patch_artifact 的受管载荷摘要合同，让合法模型修改
        # 继续复用原补丁器；摘要仅证明正文完整，不伪造原生权限隔离。
        header = "# " + MARKER + ":v1 sha256=" + hashlib.sha256(payload).hexdigest() + "\n"
        return header.encode() + payload
    fields = ["---", f"name: {role}", "description: " + json.dumps(description, ensure_ascii=False)]
    if host == "claude":
        # 当前静态角色原文只声明 [read] 或 [write]。明确沿用旧 setup_claude
        # 的对应工具列表，不能省略 tools 后让 QA 继承父会话的 Edit/Write/MCP。
        # 只解析已读取原文的 frontmatter，不执行来源脚本，也不新增核心依赖；
        # 缺失、重复、混合或未知策略失败关闭，不能沿旧 Shell 的兜底扩大为 write。
        front, separator, _ = source.partition("\n---\n")
        declared = re.findall(r"(?m)^toolsets:[ \t]*(.*)$", front)
        toolset = re.fullmatch(r"\[\s*(read|write)\s*\]", declared[0]) if len(declared) == 1 else None
        if not source.startswith("---\n") or not separator or toolset is None:
            raise ProjectRuntimeError("Claude 角色缺少唯一受支持的 toolsets 声明")
        tools = "Read, Grep, Glob, Bash, Skill" if toolset[1] == "read" else "Read, Grep, Glob, Bash, Edit, Write, Skill"
        fields.extend(["model: " + json.dumps(settings.get("model", "inherit")), "tools: " + tools,
                       "permissionMode: default", "disallowedTools: Agent"])
        if settings.get("effort", "inherit") != "inherit":
            fields.append("effort: " + settings["effort"])
        window = parse_claude(config.decode())["auto_compact_windows"].get(role)
        if window is not None:
            fields.append(f"autoCompactWindow: {window}")
    else:
        # 工具白名单仍由既有原生验证器维护；只解析其受管常量，不执行来源脚本，
        # 也不在这里复制另一套工具策略或扩张静态角色的委派能力。
        constant = "QA_TOOLS" if role == "xy-qa" else "UIUX_TOOLS" if role == "xy-uiux" else "IMPLEMENTER_TOOLS"
        syntax = ast.parse(resources.read("lib/validate_antigravity_artifacts.py"))
        tools = None
        for statement in syntax.body:
            if isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name) and target.id == constant for target in statement.targets):
                tools = ast.literal_eval(statement.value)
        if not isinstance(tools, tuple) or not tools or not all(isinstance(tool, str) for tool in tools):
            raise ProjectRuntimeError("核心缺少可验证的原生角色工具白名单")
        fields.extend(["tools:", *("  - " + tool for tool in tools), "mainAgent: false", "subagent: true",
                       "model: " + settings.get("model", "inherit"), "commandExecutionPolicy: sandbox"])
    fields.append("skills:")
    fields.extend("  - " + ("skills/" if host == "antigravity" else "") + skill for skill in ROLE_SKILLS[role])
    fields.extend(["---", "", "<!-- " + MARKER + " -->", "", instructions])
    return "\n".join(fields).encode()


def launcher_source() -> bytes:
    """自举只加载已固定且哈希匹配的存储校验器，再由它验证整个核心。

    项目中无机器路径；克隆后的薄入口即使还在，也必须先找到当前物理根的
    私有机器 binding。自举代码不 import 项目代码，不运行 setup 或模型进程。
    """
    return '''#!/usr/bin/env python3
"""中央项目薄入口；通过 lib/python_runtime.sh 选择已有受支持解释器。"""
import os
import sys
if os.name == "nt":
    _safe_fs = globals().get("__agent_workflow_windows_fs__")
    _trusted = globals().get("__agent_workflow_trusted_path__")
    if _safe_fs is None or not isinstance(_trusted, tuple):
        raise ValueError("Windows 薄入口必须通过持久私有 Python bootstrap 执行")
    sys.path[:] = _trusted
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat

sys.dont_write_bytecode = True

def read_regular(path):
    if os.name == "nt":
        # 不从项目导入后端，不依赖 Windows stdlib 缺失的 dir_fd/O_NOFOLLOW。
        body = _safe_fs.read_file(path)
        if body is None:
            raise FileNotFoundError(str(path))
        return body
    # 自举尚不能加载核心模块，先逐段 no-follow 读取有界普通文件；完整核心验证随后进行。
    opened = []
    chain = []
    try:
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(descriptor)
        for name in path.parts[1:-1]:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            opened.append(child)
            if (before.st_dev, before.st_ino) != (os.fstat(child).st_dev, os.fstat(child).st_ino):
                raise ValueError("薄入口父目录在打开时变化")
            chain.append((descriptor, name, before.st_dev, before.st_ino))
            descriptor = child
        before = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 4194304:
            raise ValueError("薄入口只接受有界单链接普通文件")
        handle = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(handle, "rb") as stream:
            actual = os.fstat(stream.fileno())
            body = stream.read(4194305)
            after = os.fstat(stream.fileno())
        stamp = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                              info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if (stamp(actual) != stamp(before) or stamp(actual) != stamp(after) or len(body) != before.st_size
                or stamp(os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)) != stamp(before)):
            raise ValueError("薄入口文件在读取期间变化")
        for parent, name, device, inode in chain:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (device, inode):
                raise ValueError("薄入口父目录在读取期间变化")
        return body
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)

def start():
    project = Path(__file__).absolute().parent.parent.resolve(strict=True)
    state = Path(os.environ.get("AGENT_WORKFLOW_STATE_DIR", Path.home() / ".config/agent-workflow")).expanduser().absolute()
    key = hashlib.sha256(str(project).encode("utf-8")).hexdigest()
    try:
        record = json.loads(read_regular(state / "bindings" / (key + ".json")))
    except FileNotFoundError:
        raise ValueError("本项目尚未在本机启用工作流") from None
    if record.get("project_root") != str(project) or record.get("schema_version") != 1:
        raise ValueError("本机项目绑定不属于当前物理根")
    binding = record.get("runtime_binding")
    # 旧任务在当前项目换版或当前核心损坏后，仍须从自身已用 pin 自举读取。
    # 参数优先于环境；任何显式 pin 都先限制到当前物理项目的 used_bindings。
    requested = None
    has_requested = False
    if len(sys.argv) > 2 and sys.argv[1] == "--binding":
        has_requested = True
        requested = json.loads(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1].startswith("--binding="):
        has_requested = True
        requested = json.loads(sys.argv[1].split("=", 1)[1])
    elif "AGENT_WORKFLOW_RUNTIME_BINDING" in os.environ:
        has_requested = True
        requested = json.loads(os.environ["AGENT_WORKFLOW_RUNTIME_BINDING"])
    if has_requested:
        if requested not in record.get("used_bindings", []):
            raise ValueError("任务 pin 不是当前物理项目曾用版本")
        binding = requested
    if (not isinstance(binding, dict) or set(binding) != {"protocol_version", "content_id", "manifest_sha256"}
            or type(binding.get("protocol_version")) is not int or binding["protocol_version"] != 1
            or not isinstance(binding.get("content_id"), str) or not re.fullmatch("[0-9a-f]{64}", binding["content_id"])
            or binding["content_id"] != binding.get("manifest_sha256")):
        raise ValueError("本机核心绑定无效")
    version = state / "runtimes" / binding["content_id"]
    manifest = read_regular(version / "manifest.json")
    if hashlib.sha256(manifest).hexdigest() != binding["manifest_sha256"]:
        raise ValueError("中央核心清单已损坏")
    files = {row["path"]: row for row in json.loads(manifest)["files"]}
    root = version / "core"
    # 完整 load_core 前执行的模块先逐个核对清单字节；Windows 从已核字节
    # 编译，不在校验后重新读取路径；后端以独立名称隔离于私有 bootstrap 版。
    bootstrap_files = ("lib/platform_fs.py", "lib/runtime_store.py")
    if os.name == "nt":
        _safe_fs.assert_private(state)
        _safe_fs.assert_private(state / "bindings")
        _safe_fs.assert_private(state / "bindings" / (key + ".json"), directory=False)
        bootstrap_files += ("lib/windows_fs.py",)
    verified = {}
    for relative in bootstrap_files:
        if os.name == "nt":
            _safe_fs.assert_private(root / relative, directory=False)
        body = read_regular(root / relative)
        if relative not in files or hashlib.sha256(body).hexdigest() != files[relative]["sha256"]:
            raise ValueError("中央自举校验器已损坏")
        verified[relative] = body
    sys.path.insert(0, str(root / "lib"))
    if os.name == "nt":
        for relative in ("lib/windows_fs.py", "lib/platform_fs.py"):
            name = Path(relative).stem
            dependency_spec = importlib.util.spec_from_file_location(name, root / relative)
            dependency = importlib.util.module_from_spec(dependency_spec)
            sys.modules[name] = dependency
            exec(compile(verified[relative], str(root / relative), "exec"), dependency.__dict__)
    spec = importlib.util.spec_from_file_location("_agent_workflow_store", root / "lib/runtime_store.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(verified["lib/runtime_store.py"], str(root / "lib/runtime_store.py"), "exec"), module.__dict__)
    module.load_core(binding, state)
    sys.path.insert(0, str(root))
    from lib.runtime_bridge import main
    return main(project=project, state=state)

if __name__ == "__main__":
    try:
        raise SystemExit(start())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        raise SystemExit(1)
'''.encode()


def prepare(resources: Resources, project: Path, config: Node, hosts: tuple[str, ...], *, owned_links: set[str],
            preferences: dict | None = None) -> tuple[dict[str, tuple[Node, str]], object]:
    """纯读取生成资源；返回 desired 节点及用途，不创建任何目录或正文副本。"""
    body, profile, settings = configuration(resources, project, config, owned_links=owned_links)
    # 通用 store 协议也可保存不含中央项目能力的旧来源，不能只因有内容 ID 就
    # 宣称其可激活。必要自举文件缺失时在 preview 提前拒绝，实际 schema 消费
    # 仍由业务事务的真实桥检查负责，失败绝不 fallback 最新核心。
    for path in ("lib/runtime_bridge.py", "lib/runtime_store.py", "lib/platform_fs.py", "manager/runtime_service.py"):
        resources.read(path)
    selected = resources.binding
    desired = {
        LOCATOR: (Node("file", json_bytes({"schema_version": 1, "kind": "central", "runtime_binding": selected}), 0o644), "locator"),
        LAUNCHER: (Node("file", launcher_source(), 0o644), "bridge"),
        PYTHON_ENTRY: (Node("file", resources.read("lib/python_runtime.sh"), 0o755), "bridge"),
        ".agent-workflow/lib/workflow_hooks.py": (Node("file", hook_bridge_source(), 0o644), "bridge"),
    }
    if os.name == "nt":
        from .windows_hook_command import runtime_paths
        python, bootstrap = runtime_paths()
        if any(char in python + bootstrap for char in "\r\n"):
            raise ProjectRuntimeError("Windows 持久运行时路径不能含换行")
        # 项目只保存两个持久路径和既有薄入口，不复制 CPython 或中央实现。
        desired[WINDOWS_ENTRY] = (Node("file", resources.read("lib/python_runtime.cjs"), 0o644), "bridge")
        desired[WINDOWS_PATHS] = (Node("file", (python + "\n" + bootstrap + "\n").encode("utf-8"), 0o644), "bridge")
    if config.kind == "missing":
        desired[CONFIG] = (Node("file", body, 0o644), "persistent")
    command = f"bash {PYTHON_ENTRY} -B -X utf8 {LAUNCHER}"
    # 中央薄入口必须保留自包含安装既有的实施 Skill/宿主细则导航，但真实正文始终
    # 经同一任务 pin 由桥读取。宿主发现软链会随项目换版变化，不能作为旧任务权威；
    # 这里仅声明当前操作的按需入口，不执行模型、不改 startup 事件或默认触发范围。
    pinned_read = command + " --binding '<task-three-field-JSON>' read "
    block = (CENTRAL_BEGIN + "\n" +
             "This project uses the central workflow. For every new task, first run `" + command + " check`; stop and report inactive if not enabled locally.\n" +
             "Project version switches do not change existing tasks' runtime_binding; stop if a central task lacks a fixed binding rather than guessing the current version.\n" +
             "For an existing task, use runtime_binding from its complete current Task Pack; for a new task, freeze the binding verified by check. Use that same binding for every read below rather than following mutable project Skill discovery symlinks.\n" +
             "For Light/Full implementation, activate the current host's workflow entry: Codex `$xy-workflow`; Claude Code/Antigravity `/xy-workflow`. Read its complete instructions with `" + pinned_read + "platforms/shared/skills/xy-workflow/SKILL.md`. Read-only discussion and audit retain the existing workflow branches.\n" +
             "Read only the current host's integration with `" + pinned_read + "platforms/<current-host>/references/pm-integration.md`, replacing <current-host> with codex, claude, or antigravity for the actual host; do not preload the other hosts' details.\n" +
             "Read the shared core with `" + pinned_read + "product/WORKFLOW.md`; project configuration is `" + CONFIG + "`.\n" +
             "Keep business, configuration, and core roots separate; role permission fields do not imply parent-session provider/MCP isolation.\n" + CENTRAL_END + "\n").encode()
    desired["AGENTS.md"] = (Node("file", block, 0o644), "block")
    if "claude" in hosts:
        desired["CLAUDE.md"] = (Node("file", (CENTRAL_BEGIN + "\n@AGENTS.md\n" + CENTRAL_END + "\n").encode(), 0o644), "block")
        desired.update(claude_write_guard(project, body))
    if "codex" in hosts:
        from .merge_codex_config import render as render_codex_config
        with Tree(project) as tree:
            native = tree.read(".codex/config.toml")
        threads = re.search(rb"(?m)^  max_concurrent_subagents:\s*([1-9][0-9]*)", body)
        rendered = render_codex_config(native.payload.decode("utf-8"), int(threads[1]) if threads else 8).encode()
        desired[".codex/config.toml"] = (Node("file", rendered, native.mode or 0o644), "native-config")
    # 配置尚未落盘也能生成 fresh Hooks；JSON 容器不成为整文件独占资源。
    desired.update(hook_resources(project, body, hosts,
                                  codex_after=desired.get(".codex/config.toml", (None,))[0]))
    for host in hosts:
        directory, suffix = ROLE_PATHS[host]
        for role in profile.enabled_roles:
            desired[f"{directory}/{role}{suffix}"] = (Node("file", role_resource(resources, body, host, role, selected, preferences=preferences), 0o644), "role")
    # Resources.root 在来源预览中仍是下载源；实际链接目标由服务明确注入中央定位，
    # 所以此处只返回角色/普通资源，Skill 目标不得猜测为源码根。
    docs = settings["docs"]
    with Tree(project) as tree:
        if tree.read(docs["project"]).kind == "missing":
            template = resources.read("templates/docs/PROJECT.md").decode("utf-8")
            values = {"PROJECT_NAME": settings["project_name"], "DOC_PLANS_DIR": docs["plans"].rstrip("/"),
                      "DOC_STANDARDS": docs["standards"], "DOC_DESIGN_DIR": docs["standards_root"].rstrip("/")}
            unknown = set(re.findall(r"\{\{([A-Z_]+)\}\}", template)) - values.keys()
            if unknown:
                raise ProjectRuntimeError("项目模板包含未知占位符")
            rendered = re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match[1]], template).encode()
            desired[docs["project"]] = (Node("file", rendered, 0o644), "persistent")
    return desired, profile
