"""中央项目启停、固定版本切换与条件恢复的唯一业务服务。

preview 完全只读，apply 在项目目录锁和机器状态锁内重查前像。项目与机器
状态可能位于不同文件系统，因此采用 prepared 日志和精确补偿，明确不承诺
断电时的跨文件系统原子性。所有旧 inode 都有可找回路径，恢复拒绝后续手改。
CLI/TUI 应共享此模块，不各自复制安装或恢复业务规则。
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import stat
import sys
import tomllib
import time
import uuid

from lib import runtime_project as project_files
from lib import runtime_store as store
from lib import role_preferences
from lib.platform_fs import directory_lock, os, publish_skill_symlink, require_skill_symlinks
from lib.runtime_project import (
    CONFIG, HOSTS, LOCATOR, Node, ProjectRuntimeError, Resources, Tree,
    absolute_directory, canonical_project, central_block, identity, json_bytes,
    managed_path, merge_central_block, node_id, project_key, read_at, relative_path, skill_parts,
    unique_json, validate_skill_link,
)


ACTIONS = frozenset({"enable", "disable", "use", "rollback", "repair"})
_NONCE = re.compile(r"[0-9a-f]{32}\Z")


class ActivationError(ProjectRuntimeError):
    """预览不能应用，或事务需要人工核对；conflicts 仅包含路径和安全诊断。"""

    def __init__(self, message: str, conflicts=()):
        self.conflicts = tuple(conflicts)
        super().__init__(message)


@dataclass(frozen=True)
class ResourceChange:
    relative: str
    before: Node
    after: Node
    purpose: str


@dataclass(frozen=True)
class ActivationPlan:
    """同一进程持有的条件计划；summary 可直接交给 JSON CLI 或 curses TUI。

    原始正文仅存在私有前后像，不进入 summary。计划不能作为可移植授权票据：
    apply 总会重新验证来源、机器记录、目录身份及全部文件/链接前像。
    """

    state: Path
    project: Path
    action: str
    source_root: Path | None
    binding_json: bytes | None
    label: str | None
    hosts: tuple[str, ...]
    enabled_before: bool
    enabled_after: bool
    changes: tuple[ResourceChange, ...]
    observed: tuple[tuple[str, Node], ...]
    directories: tuple
    machine_before: Node
    journal_before: Node
    managed_json: bytes
    conflicts: tuple[dict, ...] = ()
    warnings: tuple[str, ...] = ()
    recovery: bool = False
    preferences_before: Node | None = None

    @property
    def summary(self) -> dict:
        record = unique_json(self.machine_before.payload) if self.machine_before.kind == "file" else {}
        return {"schema_version": 1, "action": self.action, "project": str(self.project),
                "state": str(self.state), "enabled_before": self.enabled_before,
                "enabled_after": self.enabled_after,
                "runtime_binding": unique_json(self.binding_json) if self.binding_json else None,
                "previous_binding": record.get("runtime_binding") if self.binding_json and record.get("runtime_binding") != unique_json(self.binding_json) else record.get("previous_binding"),
                "label": self.label, "hosts": list(self.hosts),
                "changes": [{"path": row.relative, "operation": "remove" if row.after.kind == "missing" else "create" if row.before.kind == "missing" else "update",
                             "kind": row.after.kind, "purpose": row.purpose} for row in self.changes],
                "conflicts": list(self.conflicts), "warnings": list(self.warnings),
                "can_apply": not self.conflicts, "recovery": self.recovery}


def _state_relative(project: Path, kind: str) -> str:
    return f"{kind}/{project_key(project)}.json"


def _read_state(state: Path, relative: str) -> Node:
    try:
        with Tree(state) as tree:
            return tree.read(relative)
    except FileNotFoundError:
        return Node()


def read_binding_record(state: Path, project: Path) -> tuple[Node, dict | None]:
    """桥也使用同一机器记录校验，物理根复制后不能继承另一项目的启用权。"""
    snapshot = _read_state(state, _state_relative(project, "bindings"))
    if snapshot.kind == "missing":
        return snapshot, None
    record = unique_json(snapshot.payload)
    required = {"schema_version", "project_root", "project_identity", "runtime_binding", "enabled",
                "hosts", "previous_binding", "used_bindings", "managed", "retained_nodes", "generation"}
    if (not isinstance(record, dict) or set(record) != required
            or type(record["schema_version"]) is not int or record["schema_version"] != 1
            or record["project_root"] != str(project)
            or record["project_identity"] != list(node_id(project.stat()))
            or type(record["enabled"]) is not bool
            or not isinstance(record["hosts"], list) or not record["hosts"]
            or any(host not in HOSTS for host in record["hosts"])
            or len(set(record["hosts"])) != len(record["hosts"])
            or not isinstance(record["managed"], dict)
            or not isinstance(record["used_bindings"], list)
            or not isinstance(record["retained_nodes"], list)
            or not isinstance(record["generation"], str) or not _NONCE.fullmatch(record["generation"])):
        raise ActivationError("本机项目绑定结构或物理目录身份无效")
    if os.name != "nt" and snapshot.mode != 0o600:
        raise ActivationError("本机项目绑定必须保持私有 0600 权限")
    binding = store.validate_binding(record["runtime_binding"])
    if record["previous_binding"] is not None:
        store.validate_binding(record["previous_binding"])
    used = [store.validate_binding(item) for item in record["used_bindings"]]
    if binding not in used or (record["previous_binding"] is not None and record["previous_binding"] not in used):
        raise ActivationError("本机当前或前次绑定不在项目已用版本历史中")
    for relative, managed in record["managed"].items():
        relative_path(relative)
        if (not isinstance(managed, dict) or set(managed) != {"purpose", "baseline", "expected"}
                or not isinstance(managed["purpose"], str) or not managed_path(relative, managed["purpose"])):
            raise ActivationError("受管项目资源记录无效")
        for key in ("baseline", "expected"):
            value = Node.from_value(managed[key])
            if value.kind == "link" and not skill_parts(relative):
                raise ActivationError("机器记录不能授权精确 Skill 以外的链接")
    return snapshot, record


def _journal(state: Path, project: Path) -> tuple[Node, dict | None]:
    snapshot = _read_state(state, _state_relative(project, "transactions"))
    if snapshot.kind == "missing":
        return snapshot, None
    if os.name != "nt" and snapshot.mode != 0o600:
        raise ActivationError("中央恢复记录必须保持私有 0600 权限")
    record = unique_json(snapshot.payload)
    if (not isinstance(record, dict) or record.get("schema_version") != 1
            or record.get("project_root") != str(project)
            or not isinstance(record.get("id"), str) or not _NONCE.fullmatch(record["id"])
            or record.get("phase") not in {"prepared", "applied", "rolled_back", "conflict"}
            or not isinstance(record.get("changes"), list)):
        raise ActivationError("中央项目事务恢复记录无效")
    for index, row in enumerate(record["changes"]):
        relative = relative_path(row["path"])
        parent, _, name = relative.rpartition("/")
        prefix = f"{parent}/" if parent else ""
        expected = prefix + f".agent-workflow-central-{record['id']}-{index}"
        if (row.get("backup") != expected + ".previous"
                or row.get("stage") != expected + ".stage"
                or row.get("rollback") != expected + ".rollback"):
            raise ActivationError("事务恢复路径不属于本次精确节点")
        Node.from_value(row["before"])
        after = Node.from_value(row["after"])
        if after.kind == "link" and not skill_parts(relative):
            raise ActivationError("事务恢复不能授权普通路径链接")
    Node.from_value(record["binding_before"])
    if "legacy" in record:
        raise ActivationError("不支持旧安装转换恢复记录；请先处理原安装残留")
    return snapshot, record


def _raw(tree: Tree, relative: str) -> Node:
    try:
        directory, name = tree.parent(relative)
    except FileNotFoundError:
        return Node()
    return read_at(directory, name, allow_link=True)


def _retained(tree: Tree, records: list[dict]) -> list[dict]:
    conflicts = []
    for item in records:
        relative = relative_path(item["path"])
        if not re.search(r"/\.agent-workflow-central-[0-9a-f]{32}-[0-9]+\.(?:previous|rollback)$", "/" + relative):
            raise ActivationError("保留 inode 路径不属于中央事务")
        node = _raw(tree, relative)
        if (node.kind != item["kind"] or node.mode != item["mode"]
                or hashlib.sha256(node.payload).hexdigest() != item["sha256"]
                or list(node.identity[:2]) != item["inode"]):
            conflicts.append({"path": relative, "reason": "保留的旧 inode 已有后续保存或身份变化"})
    return conflicts


def _ownership(tree: Tree, record: dict, state: Path, *, repair: bool) -> tuple[list[dict], set[str]]:
    conflicts = _retained(tree, record["retained_nodes"])
    links = set()
    core = None
    for relative, managed in record["managed"].items():
        expected = Node.from_value(managed["expected"])
        try:
            actual = tree.read(relative, skill_link=managed["purpose"] == "skill")
            if managed["purpose"] == "block":
                same = central_block(actual.payload) == central_block(expected.payload)
            elif managed["purpose"] == "native-config":
                # 只对工作流实际拥有的键/签名区作归属判断，新增用户字段不能
                # 因整文件比较而被吞掉，也不能授权覆盖已修改的受管默认键。
                same = project_files.native_projection(actual.payload) == project_files.native_projection(expected.payload)
            else:
                same = actual.same_content(expected)
            if actual.kind == "missing" and expected.kind != "missing" and repair:
                continue  # 只有已经登记的缺失资源可由 repair 重建，未知内容永不覆盖。
            if not same:
                raise ActivationError("受管资源含未知手改")
            if actual.kind == "link":
                if actual.identity[:2] != expected.identity[:2] or actual.mode != expected.mode:
                    raise ActivationError("受管 Skill 链接节点已被替换")
                if core is None:
                    core = store.load_core(record["runtime_binding"], state)
                validate_skill_link(tree, relative, actual, core)
                links.add(relative)
        except (OSError, ValueError) as exc:
            conflicts.append({"path": relative, "reason": "受管资源验证失败：" + str(exc)})
    return conflicts, links


def _has_install_residue(project: Path) -> bool:
    with Tree(project) as tree:
        return tree.read(".agent-workflow/.install-manifest.json").kind != "missing"


def _protect_project(project: Path, source_root: Path | None) -> None:
    """统一复用原安装器的源码根/子树/包含关系拒绝，binding 启用也不能绕过。"""
    from lib.install_workflow import InstallError, _target_path
    sources = [Path(__file__).resolve().parents[1]]
    if source_root is not None:
        sources.append(Path(source_root).expanduser().resolve())
    try:
        for source in sources:
            _target_path(str(project), source)
    except InstallError as exc:
        raise ActivationError(str(exc)) from exc
    with Tree(project) as tree:
        old_setup = tree.read("agent_workflow/setup_all.sh")
        if old_setup.kind == "file" and tree.read("agent_workflow/product/WORKFLOW.md").kind == "file":
            raise ActivationError("发现旧工作流目录 agent_workflow；先显式处理原安装，保留该目录")


def preview(state: Path, project: Path, action: str, *, source_root: Path | None = None,
            binding: dict | None = None, hosts: tuple | None = None) -> ActivationPlan:
    """生成无写入条件预览；可预见冲突进入 summary，参数/损坏记录正常抛错。

    use 仅接受已验证内容 ID；source_root 只用于 enable 的显式导入。
    旧自包含残留始终只读拒绝，必须由有明确授权的安装管理任务先移除受管范围。
    """
    state, project = store.state_root(state), canonical_project(project)
    preferences_before, preferences = role_preferences.snapshot(state)
    _protect_project(project, source_root)
    if action not in ACTIONS:
        raise ActivationError("未知项目动作")
    if source_root is not None and (action != "enable" or binding is not None):
        raise ActivationError("来源导入仅供 enable 使用，不能同时传入 binding")
    if action in {"disable", "rollback", "repair"} and binding is not None:
        raise ActivationError("该动作不能接受外部版本绑定")
    machine, record = read_binding_record(state, project)
    journal_node, journal = _journal(state, project)
    chosen_hosts = tuple(hosts) if hosts is not None else tuple(record["hosts"]) if record else HOSTS
    if (not chosen_hosts or len(set(chosen_hosts)) != len(chosen_hosts)
            or any(host not in HOSTS for host in chosen_hosts)):
        raise ActivationError("hosts 必须为非空且不重复的三宿主子集")
    chosen_hosts = tuple(host for host in HOSTS if host in chosen_hosts)
    conflicts, warnings = [], []
    before_enabled = bool(record and record["enabled"])
    after_enabled = action != "disable" if action in {"enable", "disable"} else before_enabled
    pending = journal and journal["phase"] in {"prepared", "conflict"}
    if pending:
        if action != "repair":
            conflicts.append({"path": _state_relative(project, "transactions"), "reason": "存在未完成事务，先预览 repair 恢复"})
        else:
            return ActivationPlan(state, project, action, None, json_bytes(record["runtime_binding"]) if record else None,
                                  None, chosen_hosts, before_enabled, before_enabled, (), (), (), machine,
                                  journal_node, json_bytes(record["managed"] if record else {}), recovery=True)
    if _has_install_residue(project):
        conflicts.append({"path": ".agent-workflow/.install-manifest.json",
                          "reason": "发现旧自包含安装残留；保留原配置和文档，先明确移除旧受管工作流后再普通启用"})
        return ActivationPlan(state, project, action, None, None, None, chosen_hosts, before_enabled,
                              before_enabled, (), (), (), machine, journal_node, json_bytes({}),
                              tuple(conflicts), tuple(warnings))
    resources = None
    selected = None
    source = None
    if source_root is not None:
        source = Path(source_root).expanduser().absolute()
        inspected = store.inspect_core(source)
        selected = {key: inspected[key] for key in ("protocol_version", "content_id", "manifest_sha256")}
        resources = Resources(source, json_bytes(selected), inspected["label"])
    else:
        if action == "use":
            if binding is None:
                raise ActivationError("use 必须显式选择已验证的固定 binding")
            selected = store.validate_binding(binding)
        elif action == "rollback":
            if not record or record["previous_binding"] is None:
                raise ActivationError("本项目没有已验证的前次中央版本")
            selected = record["previous_binding"]
        elif binding is not None:
            selected = store.validate_binding(binding)
        elif record:
            selected = record["runtime_binding"]
        elif action != "disable":
            raise ActivationError("首次 enable 必须提供 source_root 或已验证 binding")
        if selected is not None:
            core = store.load_core(selected, state)
            resources = Resources(core.root, json_bytes(core.binding()), core.label, core)
    if action in {"use", "rollback", "repair"} and record is None:
        raise ActivationError("项目尚无本机中央绑定，先 enable")
    with Tree(project) as tree:
        owned_links = set()
        if journal:
            conflicts.extend(_retained(tree, journal.get("retained_nodes", [])))
        if record:
            found, owned_links = _ownership(tree, record, state, repair=action == "repair")
            conflicts.extend(found)
        config = tree.read(CONFIG)
        desired = {}
        if after_enabled and resources:
            require_skill_symlinks()
            if not conflicts:
                desired, _ = project_files.prepare(resources, project, config, chosen_hosts, owned_links=owned_links,
                                                  preferences=preferences)
                names = project_files.skill_names(resources)
                fixed_root = state / "runtimes" / selected["content_id"] / "core"
                skill_roots = set()
                for host in chosen_hosts:
                    skill_roots.add(".claude/skills" if host == "claude" else ".agents/skills")
                for root in sorted(skill_roots):
                    for name in names:
                        relative = root + "/" + name
                        desired[relative] = (Node("link", os.fsencode(fixed_root / "platforms/shared/skills" / name), 0o777), "skill")
        elif record:
            # 禁用只撤下新任务入口/角色/Skill，locator 与必要薄桥保留给已有 pin。
            for relative, managed in record["managed"].items():
                expected = Node.from_value(managed["expected"])
                desired[relative] = ((expected if managed["purpose"] in {"bridge", "locator"}
                                      else Node.from_value(managed["baseline"])), managed["purpose"])
            if config.kind != "file":
                raise ActivationError("项目配置缺失，不能安全撤下当前受管 Hooks")
            desired.update(project_files.hook_resources(project, config.payload, chosen_hosts, enabled=False))
        managed_next = dict(record["managed"]) if record else {}
        changes = []
        observed = {CONFIG: config}
        all_paths = [] if conflicts and after_enabled else sorted(set(desired) | set(managed_next))
        for relative in all_paths:
            old = managed_next.get(relative)
            try:
                current = tree.read(relative, skill_link=bool(skill_parts(relative)))
            except (OSError, ValueError) as exc:
                conflicts.append({"path": relative, "reason": "目标边界冲突：" + str(exc)})
                continue
            observed[relative] = current
            if relative in desired:
                after, purpose = desired[relative]
            else:
                after, purpose = Node.from_value(old["baseline"]), old["purpose"]
            if purpose == "watch":
                if current != after:
                    conflicts.append({"path": relative, "reason": "本地原生设置在预览读取期间变化"})
                continue
            if purpose == "guard" and current.identity != after.identity:
                conflicts.append({"path": relative, "reason": "项目原生设置在保护预览读取期间变化"})
                continue
            if old is None and current.kind != "missing" and purpose not in {"block", "persistent", "native-config", "guard"}:
                conflicts.append({"path": relative, "reason": "已存在未归属本机中央记录的资源，停止覆盖"})
                continue
            if purpose == "block":
                if old is None and central_block(current.payload) is not None:
                    conflicts.append({"path": relative, "reason": "已有中央标记但无本机归属，停止认领"})
                    continue
                if after_enabled:
                    base = current
                    after = Node("file", merge_central_block(base.payload, after.payload), current.mode or 0o644)
                else:
                    baseline = Node.from_value(old["baseline"]) if old else Node()
                    # repair/use 会把块外新增用户内容写进最新 expected，因此整文件等于
                    # expected 只能证明最近生成结果，不能证明可用最初 baseline 覆盖。
                    # 只在“最初用户字节 + 当前已归属块”能精确重建现文件时还原原字节/
                    # 缺失状态；已有文件沿用当前权限，避免撤销用户后续 chmod。
                    rebuilt = Node("file", merge_central_block(baseline.payload, central_block(current.payload) or b""), current.mode)
                    if old and current.same_content(rebuilt):
                        after = Node("file", baseline.payload, current.mode) if baseline.kind == "file" else baseline
                    else:
                        # 无法证明块外仍为最初内容时，只删除已归属块，保留完整外段与模式。
                        remaining = merge_central_block(current.payload, b"")
                        after = Node("file", remaining, current.mode or 0o644) if remaining else Node()
            if purpose == "native-config" and not after_enabled and old:
                after = project_files.restore_native(current, Node.from_value(old["baseline"]),
                                                     Node.from_value(old["expected"]))
            if purpose == "persistent" and current.kind != "missing":
                continue
            if purpose not in {"persistent", "guard"}:
                baseline = current
                managed_next[relative] = {"purpose": purpose,
                                          "baseline": old["baseline"] if old else baseline.value(),
                                          "expected": after.value()}
            if not current.same_content(after):
                changes.append(ResourceChange(relative, current, after, purpose))
        directories = tree.directory_facts(list(observed))
    if source and store.inspect_core(source) != {**selected, "label": resources.label}:
        raise ActivationError("核心来源在预览期间变化")
    return ActivationPlan(state, project, action, source, json_bytes(selected) if selected else None,
                          resources.label if resources else None, chosen_hosts, before_enabled, after_enabled,
                          tuple(changes), tuple(sorted(observed.items())), directories, machine,
                          journal_node, json_bytes(managed_next), tuple(conflicts), tuple(warnings),
                          preferences_before=preferences_before)


def _write_private(tree: Tree, relative: str, body: bytes) -> None:
    """机器私有日志在状态锁内条件发布；不接受链接/硬链或并发替换。"""
    parent, name = tree.parent(relative, create=True)
    before = read_at(parent, name)
    temporary = ".central-state-" + uuid.uuid4().hex
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    held = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.fsync(stream.fileno())
        if read_at(parent, name) != before:
            raise ActivationError("机器记录在发布前被修改")
        if before.kind != "missing":
            held = ".central-state-previous-" + uuid.uuid4().hex
            os.rename(name, held, src_dir_fd=parent, dst_dir_fd=parent)
            if not read_at(parent, held).same_content(before):
                raise ActivationError("机器记录在隔离时被修改，保留旧记录")
        os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)
        if held is not None:
            # 此处仅移除服务自有状态记录旧 inode；项目正文的 inode 始终另外保留。
            if not read_at(parent, held).same_content(before):
                raise ActivationError("机器旧记录发生后续保存，已保留")
            os.unlink(held, dir_fd=parent)
            held = None
    except BaseException:
        if held is not None:
            try:
                os.link(held, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                os.unlink(held, dir_fd=parent)
            except FileExistsError:
                pass
        raise
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def _retained_record(path: str, node: Node) -> dict:
    return {"path": path, "kind": node.kind, "mode": node.mode,
            "sha256": hashlib.sha256(node.payload).hexdigest(), "inode": list(node.identity[:2])}


def _same_moved(actual: Node, expected: Node) -> bool:
    return (actual.same_content(expected) and actual.mode == expected.mode
            and actual.identity[:2] == expected.identity[:2])


def _application_budget() -> None:
    """沿已有安装器预算/取消通道，只在正向发布边界检查，恢复不继承过期预算。"""
    from lib.install_process import ACTIVE_RUNNER, SetupRunError
    runner = ACTIVE_RUNNER.get()
    if runner is None or runner.recovering:
        return
    if runner.deadline is not None and time.monotonic() >= runner.deadline:
        raise SetupRunError("中央安装预算已耗尽，停止下一次发布并恢复已写入节点")
    if runner.cancel_file and os.path.lexists(runner.cancel_file):
        raise SetupRunError("中央安装已取消，停止下一次发布并恢复已写入节点")


def _verify_installed_bridge(state: Path, project: Path, core: store.FrozenCore) -> None:
    """以真实选版代码消费 prepared 机器记录；不兼容选版在 enabled 前条件恢复。

    固定 read 动作只读取公共约束，既不初始化任务也不启动 Agent。这里验证的是
    真实旧/新核心 reader 对同一机器 schema 的消费，不能仅由当前进程的解析器
    代替；stdout 与清单正文逐字节比较，错误不回显项目私有载荷。
    """
    from lib.install_workflow import capture_process
    expected = store.read_core_source(core, "product/GLOBAL_CONSTRAINTS.md")
    if len(expected) > project_files.LIMIT:
        raise ActivationError("中央公共约束超过桥接有界读取范围")
    env = {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(state),
           "AGENT_WORKFLOW_PROJECT_ROOT": str(project), "PYTHONDONTWRITEBYTECODE": "1"}
    result = capture_process([sys.executable, "-B", "-X", "utf8", str(project / project_files.LAUNCHER),
                              "--binding", json_bytes(core.binding()).decode(), "read", "product/GLOBAL_CONSTRAINTS.md"], env=env)
    if result.returncode or result.stdout != expected:
        raise ActivationError("所选固定核心无法消费本机项目协议，已停止启用；不回退其他版本")


def _cleanup_stage(tree: Tree, row: dict) -> None:
    """只回收已登记且未被换掉的本事务 stage，不递归删除未知内容。"""
    try:
        parent, name = tree.parent(row["stage"])
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(before.st_mode) or list(node_id(before)) != row.get("stage_inode"):
        raise ActivationError("stage 目录归属不明，保留恢复资料")
    descriptor = os.open(name, project_files.DIR_FLAGS, dir_fd=parent)
    try:
        if node_id(os.fstat(descriptor)) != node_id(before):
            raise ActivationError("stage 目录在恢复时被替换")
        names = os.listdir(descriptor)
        leaf = Path(row["path"]).name
        if names:
            if names != [leaf]:
                raise ActivationError("stage 中存在未知后续内容，保留现状")
            staged = read_at(descriptor, leaf, allow_link=True)
            expected = Node.from_value(row["after"])
            if (not staged.same_content(expected) or list(staged.identity[:2]) != row.get("published_inode")
                    or staged.mode != expected.mode):
                raise ActivationError("stage 文件不是已登记产物，保留现状")
            os.unlink(leaf, dir_fd=descriptor)
            os.fsync(descriptor)
        if node_id(os.stat(name, dir_fd=parent, follow_symlinks=False)) != node_id(before):
            raise ActivationError("stage 目录在清理时被替换")
        os.rmdir(name, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(descriptor)


def _publish(tree: Tree, row: dict, core: store.FrozenCore | None, save) -> None:
    """先登记 stage inode，后隔离旧节点，再以 no-replace link 发布完整产物。"""
    _application_budget()
    before, after = Node.from_value(row["before"]), Node.from_value(row["after"])
    parent, name = tree.parent(row["path"], create=True)
    tree.check()
    if read_at(parent, name, allow_link=bool(skill_parts(row["path"]))) != before:
        raise ActivationError("项目节点在应用前发生变化：" + row["path"])
    backup = Path(row["backup"]).name
    stage_name = Path(row["stage"]).name
    stage = None
    if after.kind != "missing":
        os.mkdir(stage_name, 0o700, dir_fd=parent)
        stage = os.open(stage_name, project_files.DIR_FLAGS, dir_fd=parent)
        try:
            row["stage_inode"] = list(node_id(os.fstat(stage)))
            save()
            if after.kind == "file":
                descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=stage)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(after.payload)
                    stream.flush()
                    os.fchmod(stream.fileno(), after.mode)
                    os.fsync(stream.fileno())
            else:
                if core is None:
                    raise ActivationError("发布 Skill 缺少已验证固定核心")
                publish_skill_symlink(stage, name, Path(os.fsdecode(after.payload)), core_root=core.root)
            staged = read_at(stage, name, allow_link=after.kind == "link")
            if after.kind == "link":
                after = Node("link", after.payload, staged.mode)
                row["after"] = after.value()
            row["published_inode"] = list(staged.identity[:2])
            os.fsync(stage)
            save()  # 崩溃后只撤回这个 inode，不凭相同字节删除别人的后来保存。
            if read_at(parent, name, allow_link=bool(skill_parts(row["path"]))) != before:
                raise ActivationError("节点在 stage 准备期间变化：" + row["path"])
        except BaseException:
            os.close(stage)
            raise
    try:
        if before.kind != "missing":
            if read_at(parent, backup, allow_link=True).kind != "missing":
                raise ActivationError("旧 inode 保留位置发生碰撞")
            os.rename(name, backup, src_dir_fd=parent, dst_dir_fd=parent)
            moved = read_at(parent, backup, allow_link=True)
            if not _same_moved(moved, before):
                raise ActivationError("旧 inode 在隔离时发生保存，已保留：" + row["backup"])
        if after.kind != "missing":
            os.link(name, name, src_dir_fd=stage, dst_dir_fd=parent, follow_symlinks=False)
            os.unlink(name, dir_fd=stage)
        os.fsync(parent)
        current = read_at(parent, name, allow_link=bool(skill_parts(row["path"])))
        if not current.same_content(after):
            raise ActivationError("发布产物与计划不一致：" + row["path"])
        row["installed"] = current.value()
        save()
        tree.check()
    finally:
        if stage is not None:
            os.close(stage)
            # 空 stage 只有身份仍匹配才可移除。包含未知/失败内容时保留给恢复。
            info = os.stat(stage_name, dir_fd=parent, follow_symlinks=False)
            if list(node_id(info)) == row["stage_inode"]:
                try:
                    os.rmdir(stage_name, dir_fd=parent)
                except OSError:
                    pass


def _restore(tree: Tree, journal: dict) -> tuple[list[dict], list[dict]]:
    """逐项补偿，不覆盖后来写入；每个被撤下的产物 inode 也保留可找回位置。"""
    retained = list(journal.get("retained_nodes", []))
    conflicts = _retained(tree, retained)
    keep_hook_bridge = False
    # 首次启用失败时，共享 Hook 容器可能已收到用户后续保存。普通补偿必须
    # 保留该 inode，不能用最初整文件前像吞掉新权限/MCP/用户 Hook。若其中仍
    # 有可验签的当前命令，同步保留无本机 binding 时只返回中性结果的薄桥，
    # 避免恢复流程把用户保留的命令变成缺文件错误；现状仍明确标为 conflict。
    from lib.workflow_hook_install import json_object, managed_inline, managed_json
    shared = {".codex/hooks.json": "codex", ".claude/settings.json": "claude", ".agents/hooks.json": "antigravity"}
    for row in journal["changes"]:
        if row["path"] not in shared and row["path"] != ".codex/config.toml":
            continue
        try:
            actual = tree.read(row["path"])
            after = Node.from_value(row["after"])
            if actual.kind == "file" and not actual.same_content(after):
                owned = (managed_inline(actual.payload) if row["path"] == ".codex/config.toml"
                         else managed_json(json_object(actual.payload), shared[row["path"]]))
                keep_hook_bridge = keep_hook_bridge or bool(owned)
        except (OSError, ValueError):
            pass  # 普通逐行补偿负责报告该容器冲突，不凭解析失败扩大删除权。
    for row in reversed(journal["changes"]):
        before, after = Node.from_value(row["before"]), Node.from_value(row["after"])
        if keep_hook_bridge and before.kind == "missing" and managed_path(row["path"], "bridge"):
            continue
        try:
            backup = _raw(tree, row["backup"])
            if backup.kind == "missing" and not any(key in row for key in ("stage_inode", "published_inode", "installed")):
                _cleanup_stage(tree, row)
                continue  # 从未触碰的行无需补偿，尤其不能把尚未归档的旧目录当成新文件。
            parent, name = tree.parent(row["path"])
            actual = read_at(parent, name, allow_link=bool(skill_parts(row["path"])))
            if backup.kind != "missing" and not _same_moved(backup, before):
                raise ActivationError("旧 inode 已有后续保存，拒绝恢复")
            if actual.kind == "missing":
                if backup.kind != "missing":
                    os.link(Path(row["backup"]).name, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    os.unlink(Path(row["backup"]).name, dir_fd=parent)
                elif before.kind != "missing":
                    raise ActivationError("原文件和旧 inode 均缺失")
            elif _same_moved(actual, before) and backup.kind == "missing":
                pass
            elif (actual.same_content(after) and actual.mode == after.mode
                  and list(actual.identity[:2]) == row.get("published_inode")):
                rolled = Path(row["rollback"]).name
                if _raw(tree, row["rollback"]).kind != "missing":
                    raise ActivationError("回滚 inode 保留位置发生碰撞")
                os.rename(name, rolled, src_dir_fd=parent, dst_dir_fd=parent)
                moved = read_at(parent, rolled, allow_link=True)
                retained.append(_retained_record(row["rollback"], moved))
                if not _same_moved(moved, actual):
                    raise ActivationError("撤下产物时检测到后续保存，已保留")
                if before.kind != "missing":
                    if backup.kind == "missing":
                        raise ActivationError("原 inode 缺失，拒绝用正文副本冒充恢复")
                    os.link(Path(row["backup"]).name, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    os.unlink(Path(row["backup"]).name, dir_fd=parent)
            else:
                raise ActivationError("目标已有后续手改或 inode 已替换，拒绝恢复")
            os.fsync(parent)
        except FileNotFoundError:
            if before.kind != "missing":
                conflicts.append({"path": row["path"], "reason": "原父目录或节点缺失，保留恢复资料"})
        except (OSError, ValueError) as exc:
            conflicts.append({"path": row["path"], "reason": str(exc)})
        try:
            _cleanup_stage(tree, row)
        except (OSError, ValueError) as exc:
            conflicts.append({"path": row["stage"], "reason": str(exc)})
    return conflicts, retained


def _check_plan(plan: ActivationPlan, tree: Tree) -> None:
    # enable/use/rollback 必须拒绝预览之后变化的全局默认，不能把旧物化值发布为
    # 当前设置。只读快照不会运行模型目录进程，也不触碰运行任务的固定绑定。
    if plan.preferences_before is not None and role_preferences.snapshot(plan.state)[0] != plan.preferences_before:
        raise ActivationError("全局角色偏好在预览后变化，请重新预览项目操作")
    if canonical_project(plan.project) != plan.project:
        raise ActivationError("项目物理根在预览后变化")
    _protect_project(plan.project, plan.source_root)
    if tree.directory_facts([path for path, _ in plan.observed]) != plan.directories:
        raise ActivationError("项目父目录身份在预览后变化")
    for relative, before in plan.observed:
        if tree.read(relative, skill_link=bool(skill_parts(relative))) != before:
            raise ActivationError("项目文件或链接在预览后变化：" + relative)
    if _read_state(plan.state, _state_relative(plan.project, "bindings")) != plan.machine_before:
        raise ActivationError("本机项目绑定在预览后变化")
    if _read_state(plan.state, _state_relative(plan.project, "transactions")) != plan.journal_before:
        raise ActivationError("项目事务记录在预览后变化")
    old = unique_json(plan.machine_before.payload) if plan.machine_before.kind == "file" else {}
    previous_journal = unique_json(plan.journal_before.payload) if plan.journal_before.kind == "file" else {}
    if _retained(tree, old.get("retained_nodes", []) + previous_journal.get("retained_nodes", [])):
        raise ActivationError("保留的旧 inode 在预览后发生保存")

def apply(plan: ActivationPlan) -> dict:
    """应用已预览计划；返回 status 字段及 transaction_id，绝不自动运行 Agent。"""
    if not isinstance(plan, ActivationPlan) or plan.conflicts:
        raise ActivationError("预览含冲突，不能应用", plan.conflicts if isinstance(plan, ActivationPlan) else ())
    core = None
    if plan.binding_json and not plan.recovery:
        selected = store.validate_binding(unique_json(plan.binding_json))
        if plan.source_root is not None:
            # 来源漂移先于任何机器/项目创建拒绝。import 的 expected_binding 同时守卫
            # 检查与导入之间的变动，不把预览外的新版本偷偷发布为确认版本。
            inspected = store.inspect_core(plan.source_root)
            if {key: inspected[key] for key in selected} != selected:
                raise ActivationError("核心来源与预览版本不符")
        else:
            core = store.load_core(selected, plan.state)
    with ExitStack() as stack:
        stack.enter_context(role_preferences.coordination(plan.state))
        tree = stack.enter_context(Tree(plan.project))
        stack.enter_context(directory_lock(plan.project, "install"))
        if not plan.recovery:
            _check_plan(plan, tree)
        if plan.source_root is not None:
            core = store.import_core(plan.source_root, plan.state, expected_binding=selected)
        if plan.binding_json is None and not plan.recovery:
            return status(plan.state, plan.project)
        # 状态创建仅在 apply，私有文件和新状态目录分别为 0600 / 0700。
        stack.enter_context(absolute_directory(plan.state, create=True))
        stack.enter_context(absolute_directory(plan.state / "bindings", create=True))
        stack.enter_context(absolute_directory(plan.state / "transactions", create=True))
        machine_tree = stack.enter_context(Tree(plan.state))
        machine_tree.directory("bindings")
        machine_tree.directory("transactions")
        stack.enter_context(directory_lock(plan.state / "bindings", "central-project-state"))
        if plan.recovery:
            if (_read_state(plan.state, _state_relative(plan.project, "bindings")) != plan.machine_before
                    or _read_state(plan.state, _state_relative(plan.project, "transactions")) != plan.journal_before):
                raise ActivationError("恢复资料在预览后变化")
            _, journal = _journal(plan.state, plan.project)
            binding_before = Node.from_value(journal["binding_before"])
            current_node, current_record = read_binding_record(plan.state, plan.project)
            own_generation = bool(current_record and current_record["generation"] == journal["id"])
            if not own_generation and not current_node.same_content(binding_before):
                raise ActivationError("机器绑定已有后续修改，拒绝用旧事务覆盖")
            conflicts, retained = _restore(tree, journal)
            try:
                tree.check()
            except (OSError, ValueError) as exc:
                conflicts.append({"path": ".", "reason": str(exc)})
            if not conflicts and own_generation:
                # 断电可能发生在 enabled 发布后、applied 日志前；恢复项目还必须
                # 同步撤回仍属于本事务的机器绑定，不能留下虚假的启用成功。
                if binding_before.kind == "file":
                    _write_private(machine_tree, _state_relative(plan.project, "bindings"), binding_before.payload)
                else:
                    parent, name = machine_tree.parent(_state_relative(plan.project, "bindings"))
                    os.unlink(name, dir_fd=parent)
                    os.fsync(parent)
            journal["phase"] = "conflict" if conflicts else "rolled_back"
            journal["conflicts"] = conflicts
            journal["retained_nodes"] = retained
            _write_private(machine_tree, _state_relative(plan.project, "transactions"), json_bytes(journal))
            if conflicts:
                raise ActivationError("事务恢复含后续手改，已保留现状", conflicts)
            result = status(plan.state, plan.project)
            return {**result, "transaction_id": journal["id"], "recovered": True}
        _check_plan(plan, tree)
        old = unique_json(plan.machine_before.payload) if plan.machine_before.kind == "file" else None
        if plan.binding_json is None:
            return status(plan.state, plan.project)  # 从未启用项目的 disable 为真正幂等空操作。
        identifier = uuid.uuid4().hex
        managed = unique_json(plan.managed_json)
        journal = {"schema_version": 1, "project_root": str(plan.project), "id": identifier,
                   "phase": "prepared", "action": plan.action,
                   "binding_before": plan.machine_before.value(), "changes": [], "conflicts": []}
        for index, change in enumerate(plan.changes):
            parent = str(Path(change.relative).parent)
            prefix = (parent + "/") if parent != "." else ""
            stem = prefix + f".agent-workflow-central-{identifier}-{index}"
            journal["changes"].append({"path": change.relative, "before": change.before.value(),
                                       "after": change.after.value(), "backup": stem + ".previous",
                                       "stage": stem + ".stage", "rollback": stem + ".rollback"})
        # 预先检查记录容量，避免改完项目后才发现日志无法持久化。
        json_bytes(journal)
        def save():
            _write_private(machine_tree, _state_relative(plan.project, "transactions"), json_bytes(journal))
        save()
        try:
            for row in journal["changes"]:
                _publish(tree, row, core, save)
            tree.check()
            previous_journal = unique_json(plan.journal_before.payload) if plan.journal_before.kind == "file" else {}
            retained_by_path = {item["path"]: item for item in (old["retained_nodes"] if old else []) + previous_journal.get("retained_nodes", [])}
            retained = list(retained_by_path.values())
            for row in journal["changes"]:
                prior = _raw(tree, row["backup"])
                if prior.kind != "missing":
                    before = Node.from_value(row["before"])
                    if not _same_moved(prior, before):
                        raise ActivationError("保留的旧 inode 在安装检查期间变化")
                    retained.append(_retained_record(row["backup"], prior))
            conflicts = _retained(tree, retained)
            if conflicts:
                raise ActivationError("旧 inode 已有后续保存", conflicts)
            for relative, row in managed.items():
                node = tree.read(relative, skill_link=row["purpose"] == "skill")
                expected = Node.from_value(row["expected"])
                if not node.same_content(expected):
                    raise ActivationError("安装检查未得到计划资源：" + relative)
                if node.kind == "link":
                    validate_skill_link(tree, relative, node, core)
                row["expected"] = node.value()
            used = list(old["used_bindings"]) if old else []
            if selected not in used:
                used.append(selected)
            previous = old["previous_binding"] if old else None
            if old and old["runtime_binding"] != selected:
                previous = old["runtime_binding"]
            record = {"schema_version": 1, "project_root": str(plan.project),
                      "project_identity": list(node_id(os.fstat(tree.directories[""]))),
                      "runtime_binding": selected, "enabled": plan.enabled_after,
                      "hosts": list(plan.hosts), "previous_binding": previous,
                      "used_bindings": used, "managed": managed,
                      "retained_nodes": retained, "generation": identifier}
            # 普通项目省略可空扩展键，保持已用首版 reader 的原封闭字段集合。
            # 先发布 enabled=False 的 prepared 候选，由真实选版桥消费；若实际
            # reader 不兼容字段/入口，则回滚候选和项目，不能假报启用成功。
            candidate = {**record, "enabled": False}
            _write_private(machine_tree, _state_relative(plan.project, "bindings"), json_bytes(candidate))
            _verify_installed_bridge(plan.state, plan.project, core)
            # 全部安装、核心和真实桥消费检查成功后，唯一 enabled 才切换。
            _write_private(machine_tree, _state_relative(plan.project, "bindings"), json_bytes(record))
            journal["phase"] = "applied"
            save()
        except BaseException as failure:
            conflicts, retained = _restore(tree, journal)
            try:
                tree.check()
            except (OSError, ValueError) as exc:
                conflicts.append({"path": ".", "reason": str(exc)})
            # 若最终日志失败发生在机器 binding 发布后，也必须恢复旧绑定；只有
            # 仍属于本次 generation 的记录才能撤回，不覆盖后来的机器状态。
            current, current_record = read_binding_record(plan.state, plan.project)
            if current_record and current_record["generation"] == identifier:
                if plan.machine_before.kind == "file":
                    _write_private(machine_tree, _state_relative(plan.project, "bindings"), plan.machine_before.payload)
                else:
                    parent, name = machine_tree.parent(_state_relative(plan.project, "bindings"))
                    os.unlink(name, dir_fd=parent)
                    os.fsync(parent)
            journal["phase"] = "conflict" if conflicts else "rolled_back"
            journal["conflicts"] = conflicts
            journal["retained_nodes"] = retained
            try:
                save()
            except BaseException as log_failure:
                raise ActivationError("项目应用失败且恢复日志未能保存；保留 prepared 资料：" + _state_relative(plan.project, "transactions")) from log_failure
            if conflicts:
                raise ActivationError("应用失败并遇后续手改，已保留节点及恢复资料", conflicts) from failure
            raise
        result = status(plan.state, plan.project)
        return {**result, "transaction_id": identifier, "recovered": False}


def status(state: Path, project: Path) -> dict:
    """只读本机状态与资源一致性；不会导入来源、创建目录或自动修复。"""
    state, project = store.state_root(state), canonical_project(project)
    _, record = read_binding_record(state, project)
    _, journal = _journal(state, project)
    conflicts = []
    phase = "unmanaged" if record is None else "enabled" if record["enabled"] else "disabled"
    if journal and journal["phase"] in {"prepared", "conflict"}:
        phase = journal["phase"]
        conflicts.extend(journal.get("conflicts", []))
    if record:
        try:
            store.load_core(record["runtime_binding"], state)
        except (OSError, ValueError) as exc:
            conflicts.append({"path": "runtime_binding", "reason": str(exc)})
        with Tree(project) as tree:
            found, _ = _ownership(tree, record, state, repair=False)
            conflicts.extend(found)
            if record["enabled"] and "claude" in record["hosts"]:
                try:
                    config = tree.read(CONFIG)
                    if config.kind != "file":
                        raise ActivationError("项目配置缺失，不能核验显式 Claude 保护")
                    project_files.claude_write_guard(project, config.payload, check_only=True)
                except (OSError, ValueError) as exc:
                    conflicts.append({"path": ".claude/settings.json", "reason": str(exc)})
            try:
                config = tree.read(CONFIG)
                if config.kind != "file":
                    raise ActivationError("项目配置缺失，不能核验当前受管 Hooks")
                project_files.hook_resources(project, config.payload, tuple(record["hosts"]),
                                             enabled=record["enabled"], check_only=True)
            except (OSError, ValueError) as exc:
                conflicts.append({"path": "workflow_hooks", "reason": str(exc)})
    elif _has_install_residue(project):
        phase = "legacy"
    return {"schema_version": 1, "project": str(project), "state": phase,
            "enabled": bool(record and record["enabled"] and not conflicts and phase == "enabled"),
            "runtime_binding": record["runtime_binding"] if record else None,
            "previous_binding": record["previous_binding"] if record else None,
            "hosts": list(record["hosts"]) if record else [],
            "managed_paths": sorted(record["managed"]) if record else [],
            "conflicts": conflicts,
            "pending_transaction": journal["id"] if journal and journal["phase"] in {"prepared", "conflict"} else None}


def _model_fields(body: bytes, host: str) -> dict:
    """仅投影既有模型补丁器的白名单字段，不读取 provider/MCP/权限。"""
    from lib.role_models import validate
    if host == "codex":
        parsed = tomllib.loads(body.decode("utf-8"))
        value = {"model": parsed.get("model", "inherit"), "effort": parsed.get("model_reasoning_effort", "inherit")}
    else:
        front = body.decode("utf-8").split("\n---\n", 1)[0]
        model = re.findall(r"(?m)^model: ([^\n]+)$", front)
        effort = re.findall(r"(?m)^effort: ([^\n]+)$", front)
        if len(model) != 1 or len(effort) > 1:
            raise ActivationError("原生角色模型字段不唯一")
        value = {"model": model[0].strip('"'), "effort": effort[0].strip('"') if effort else "inherit"}
    return validate(host, value)


class NativeEditReceipt:
    """合法模型事务的条件收据；由 native_edit_receipt 上下文管理其生命周期。"""

    def __init__(self, state: Path, project: Path, tree: Tree, machine_tree: Tree,
                 before: Node, record: dict, changes: tuple):
        self.state, self.project = state, project
        self.tree, self.machine_tree = tree, machine_tree
        self.before, self.record, self.changes = before, record, changes
        self.generation = uuid.uuid4().hex
        self.published = False

    def publish(self) -> dict:
        """放在现有 manager.service.commit 的 verify 回调内调用，失败由原事务撤回。

        先验证真实项目产物等于授权 after，再更新中央 expected；任务核心 pin、
        enabled、模型来源与权限不变。上下文持有统一项目锁，中央换版/启停不能
        与这个收据交错，后续机器写入也必须通过 generation 条件才可撤回。
        """
        record = unique_json(json_bytes(self.record))
        for change in self.changes:
            current = self.tree.read(change.relative)
            if not current.same_content(Node("file", change.after, change.mode)):
                raise ActivationError("模型事务产物与已声明 after 不符：" + change.relative)
            if change.relative in record["managed"]:
                record["managed"][change.relative]["expected"] = current.value()
        conflicts, _ = _ownership(self.tree, record, self.state, repair=False)
        if conflicts:
            raise ActivationError("模型收据验证发现其他资源冲突", conflicts)
        self.tree.check()
        if not self.published:
            if _read_state(self.state, _state_relative(self.project, "bindings")) != self.before:
                raise ActivationError("机器绑定在模型事务期间变化")
            record["generation"] = self.generation
            _write_private(self.machine_tree, _state_relative(self.project, "bindings"), json_bytes(record))
            self.published = True
        return {"schema_version": 1, "project": str(self.project), "runtime_binding": record["runtime_binding"],
                "generation": self.generation, "updated_paths": [change.relative for change in self.changes]}


@contextmanager
def native_edit_receipt(state: Path, project: Path, changes):
    """桥接既有模型 commit 与中央受管前像，不引入第二份模型业务规则。

    由 manager.service.commit 唯一自动包裹；外部调用方直接调用 commit，不能
    再套第二个收据上下文。publish 放在 commit 已写完文件后的 verify 阶段。
    仅 CONFIG 的 role_models 精确补丁和已登记角色的 model/effort 补丁合法；
    任何正文、权限、MCP、provider 或额外路径变化都在写入前拒绝。原 commit
    继续拥有项目文件备份与回滚，本上下文只同步并条件撤回机器收据。
    """
    from lib import role_models
    state, project = store.state_root(state), canonical_project(project)
    changes = tuple(changes)
    with ExitStack() as stack:
        tree = stack.enter_context(Tree(project))
        stack.enter_context(directory_lock(project, "install"))
        before, record = read_binding_record(state, project)
        if record is None:
            raise ActivationError("模型收据仅适用于本机已有中央绑定的项目")
        _, journal = _journal(state, project)
        if journal and journal["phase"] in {"prepared", "conflict"}:
            raise ActivationError("中央项目存在未完成事务，先恢复")
        machine_tree = stack.enter_context(Tree(state))
        stack.enter_context(directory_lock(state / "bindings", "central-project-state"))
        conflicts, _ = _ownership(tree, record, state, repair=False)
        if conflicts:
            raise ActivationError("当前资源含未知编辑，不能登记模型收据", conflicts)
        seen = set()
        for change in changes:
            relative = relative_path(change.relative)
            if (relative in seen or not isinstance(change.before, bytes) or not isinstance(change.after, bytes)
                    or type(change.mode) is not int):
                raise ActivationError("模型收据变化列表无效或重复")
            seen.add(relative)
            current = tree.read(relative)
            if not current.same_content(Node("file", change.before, change.mode)):
                raise ActivationError("模型收据前像与当前文件不符：" + relative)
            if relative == CONFIG:
                parsed = role_models.parse(change.after.decode("utf-8"))
                forward = role_models.update(change.before.decode("utf-8"), parsed).encode() == change.after
                # 精确恢复到原先没有 role_models 的模板时，空 update 会保留映射
                # 头及空行。只允许同一权威补丁器可严格证明的逆变换；不去空行、
                # 不比较宽松 YAML 结构，非模型正文或记忆/权限字节仍必须完全相同。
                inverse = role_models.update(change.after.decode("utf-8"), role_models.parse(change.before.decode("utf-8"))).encode() == change.before
                if not forward and not inverse:
                    raise ActivationError("模型收据只能修改项目 role_models 区块")
                continue
            managed = record["managed"].get(relative)
            if not managed or managed["purpose"] != "role":
                raise ActivationError("模型收据只能修改已登记的原生角色")
            host = next((host for host, (directory, suffix) in project_files.ROLE_PATHS.items()
                         if relative.startswith(directory + "/") and relative.endswith(suffix)), None)
            selected = _model_fields(change.after, host)
            if role_models.patch_artifact(change.before, host, selected) != change.after:
                raise ActivationError("模型收据包含模型字段以外的变化")
        receipt = NativeEditReceipt(state, project, tree, machine_tree, before, record, changes)
        try:
            yield receipt
            if changes and not receipt.published:
                raise ActivationError("模型事务缺少 verify 阶段的 receipt.publish 调用")
        except BaseException:
            if receipt.published:
                _, current_record = read_binding_record(state, project)
                if not current_record or current_record["generation"] != receipt.generation:
                    raise ActivationError("模型事务失败且机器收据已有后续修改，已保留现状")
                # 原 commit 应先撤回项目文件再抛错；若文件已有第三方保存，则保留
                # 新收据使 status 显示冲突，不用旧快照掩盖未能安全撤回的事实。
                for change in changes:
                    if not tree.read(change.relative).same_content(Node("file", change.before, change.mode)):
                        raise ActivationError("模型事务失败且项目仍有后续变化，已保留收据")
                _write_private(machine_tree, _state_relative(project, "bindings"), before.payload)
            raise
