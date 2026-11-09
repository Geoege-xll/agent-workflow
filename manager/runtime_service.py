"""中央项目启停、固定版本切换与条件恢复的唯一业务服务。

preview 完全只读，apply 在项目目录锁和机器状态锁内重查前像。项目与机器
状态可能位于不同文件系统，因此采用 prepared 日志和精确补偿，明确不承诺
断电时的跨文件系统原子性。所有旧 inode 都有可找回路径，恢复拒绝后续手改。
CLI/TUI 应共享此模块，不各自复制安装或恢复业务规则。
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import copy
from dataclasses import dataclass
from pathlib import Path
import re
import stat
import sys
import tomllib
import time
import uuid

from lib.central import runtime_project as project_files
from lib import runtime_store as store
from lib.central import role_preferences
from lib.platform_fs import directory_lock, os, publish_skill_symlink, require_skill_symlinks
from lib.central.runtime_project import (
    CAPACITY_IDENTITY, CONFIG, HOSTS, LOCATOR, Node, Resources, Tree, capacity_node_value,
    absolute_directory, canonical_project, central_block, identity, json_bytes,
    managed_path, merge_central_block, node_id, read_at, relative_path, skill_parts,
    unique_json, validate_skill_link, move_at, publish_at, clone_file_permissions, content_mode, delete_at,
    native_snapshot,
)


ACTIONS = frozenset({"enable", "disable", "use", "rollback", "repair"})


# 私有记录只有一个权威边界；重导出原入口和同一错误类型，保留现有桥、CLI、
# TUI 及故障注入消费者。事务编排、锁序和不同业务补偿仍由本模块负责。
from .runtime_state import (
    ActivationError, read_binding_record, read_journal as _journal,
    read_state as _read_state, retained_conflicts as _retained,
    retained_record as _retained_record, state_relative as _state_relative,
    write_private as _write_private,
    CONFLICT_REASON_LIMIT, bounded_conflicts, publication_capacity,
    same_published_node,
)


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
    native_context: object | None = None
    required_global_hosts: tuple[str, ...] = ()

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


@dataclass(frozen=True)
class PublicationBudget:
    """仅容量数字，不携带可误用为真实binding/Node的未来占位。"""
    binding_after_bytes: int
    journal_after_bytes: int


def _raw(tree: Tree, relative: str, *, skill_name: str | None = None) -> Node:
    try:
        directory, name = tree.parent(relative)
    except FileNotFoundError:
        return Node()
    return read_at(directory, name, allow_link=True, skill_name=skill_name)


def _history_writes(tree: Tree, records: list[dict]) -> list[dict]:
    """历史缺失只降低恢复能力，仍存在但被修改的旧 inode 才阻止管理覆盖。"""
    return [{"path": row["path"], "reason": row["reason"]}
            for row in _retained(tree, records, typed=True) if row["code"] == "history_modified"]


def _ownership(tree: Tree, record: dict, state: Path, *, repair: bool,
               include_history: bool = True) -> tuple[list[dict], set[str]]:
    conflicts = _history_writes(tree, record["retained_nodes"]) if include_history else []
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
    from lib.install.project_paths import InstallError, target_path
    sources = [Path(__file__).resolve().parents[1]]
    if source_root is not None:
        sources.append(Path(source_root).expanduser().resolve())
    try:
        for source in sources:
            target_path(str(project), source)
    except InstallError as exc:
        raise ActivationError(str(exc)) from exc
    with Tree(project) as tree:
        old_setup = tree.read("agent_workflow/setup_all.sh")
        if old_setup.kind == "file" and tree.read("agent_workflow/product/WORKFLOW.md").kind == "file":
            raise ActivationError("发现旧工作流目录 agent_workflow；先显式处理原安装，保留该目录")


def preview(state: Path, project: Path, action: str, *, source_root: Path | None = None,
            binding: dict | None = None, hosts: tuple | None = None,
            native_context=None, native_ready_hosts: tuple = ()) -> ActivationPlan:
    """生成无写入条件预览；可预见冲突进入 summary，参数/损坏记录正常抛错。

    use 仅接受已验证内容 ID；source_root 只用于 enable 的显式导入。
    旧自包含残留始终只读拒绝，必须由有明确授权的安装管理任务先移除受管范围。
    """
    state, project = store.state_root(state), canonical_project(project)
    from . import runtime_policy
    runtime_policy.ensure_management_settled(state)
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
    ready_hosts = set(native_ready_hosts) & set(chosen_hosts)
    if native_context is not None:
        from . import native_agents
        ready_hosts.update(set(native_agents.verified_hosts(state, context=native_context)) & set(chosen_hosts))
    required_global_hosts = tuple(host for host in chosen_hosts if host in ready_hosts)
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
        resources = Resources(source, json_bytes(selected), inspected["label"], destination=state / "runtimes" / selected["content_id"] / "core")
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
            conflicts.extend(_history_writes(tree, journal.get("retained_nodes", [])))
        if record:
            found, owned_links = _ownership(tree, record, state, repair=action == "repair")
            conflicts.extend(found)
        config = tree.read(CONFIG)
        desired = {}
        if after_enabled and resources:
            require_skill_symlinks()
            if not conflicts:
                context_args = {"native_context": native_context, "native_ready_hosts": required_global_hosts} if native_context is not None else {}
                desired, _ = project_files.prepare(resources, project, config, chosen_hosts, owned_links=owned_links,
                                                  preferences=preferences, **context_args)
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
                          preferences_before=preferences_before, native_context=native_context,
                          required_global_hosts=required_global_hosts)


def _same_moved(actual: Node, expected: Node) -> bool:
    return (actual.same_content(expected) and actual.mode == expected.mode
            and actual.identity[:2] == expected.identity[:2] and actual.security == expected.security)


def _application_budget() -> None:
    """沿已有安装器预算/取消通道，只在正向发布边界检查，恢复不继承过期预算。"""
    from lib.install.install_process import ACTIVE_RUNNER, SetupRunError
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
    from lib.install.install_process import capture_process
    expected = store.read_core_source(core, "product/GLOBAL_CONSTRAINTS.md")
    if len(expected) > project_files.LIMIT:
        raise ActivationError("中央公共约束超过桥接有界读取范围")
    env = {**os.environ, "AGENT_WORKFLOW_STATE_DIR": str(state),
           "AGENT_WORKFLOW_PROJECT_ROOT": str(project), "PYTHONDONTWRITEBYTECODE": "1"}
    result = capture_process([sys.executable, "-I", "-B", "-X", "utf8", str(project / project_files.LAUNCHER),
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
    if os.name == "nt" and stat.S_ISREG(before.st_mode):
        # Windows 普通文件在目标同父目录暂存，避免子目录继承改变用户 DACL。
        staged = read_at(parent, name)
        expected = Node.from_value(row["after"])
        if (not staged.same_content(expected) or list(staged.identity[:2]) != row.get("stage_inode")
                or list(staged.identity[:2]) != row.get("published_inode")):
            raise ActivationError("stage 文件归属不明，保留恢复资料")
        if staged != Node.from_value(row["after"]):
            raise ActivationError("stage 文件完整身份或 ACL 已变化")
        delete_at(parent, name, expected=staged)
        os.fsync(parent)
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
            delete_at(descriptor, leaf, expected=staged,
                      skill_name=skill_parts(row["path"])[1] if skill_parts(row["path"]) else None)
            os.fsync(descriptor)
        if node_id(os.stat(name, dir_fd=parent, follow_symlinks=False)) != node_id(before):
            raise ActivationError("stage 目录在清理时被替换")
        if os.name != "nt":
            os.rmdir(name, dir_fd=parent)
            os.fsync(parent)
    finally:
        os.close(descriptor)
    if os.name == "nt":
        from lib.windows_fs import delete_directory
        delete_directory(parent, name, expected={"identity": tuple(row["stage_inode"]),
                                                 "security": row["stage_security"]})


def _register_stage(row: dict, staged: Node) -> Node:
    """file/Skill 共用登记边界；在隔离原件前把已验证 stage 见证写入原 after 字段。"""
    expected = Node.from_value(row["after"])
    if not staged.same_content(expected):
        raise ActivationError("stage 产物与计划内容不符：" + row["path"])
    if os.name == "nt":
        native_snapshot(staged)  # 拒绝 planned/缺失 ACL，不能以 inode 二元组代替实际事实。
        if staged.kind == "file":
            before = Node.from_value(row["before"])
            if (list(staged.identity[:2]) != row.get("stage_inode")
                    or before.kind == "file" and staged.security != before.security):
                raise ActivationError("stage 文件身份或原权限见证不符：" + row["path"])
        row["after"] = staged.value()
    elif staged.kind == "link":
        # POSIX 保持原记录形状及软链实际 mode 投影，不引入 Windows 身份字段。
        row["after"] = Node("link", expected.payload, staged.mode).value()
    row["published_inode"] = list(staged.identity[:2])
    return Node.from_value(row["after"])


def _register_installed(row: dict, current: Node) -> None:
    """验证已登记 stage 的发布后事实，成功前不污染可恢复 journal。"""
    after = Node.from_value(row["after"])
    if not current.same_content(after):
        raise ActivationError("发布产物与计划不一致：" + row["path"])
    if os.name == "nt" and current.kind != "missing" and not same_published_node(current, after):
        # ACL/身份漂移不能被当前快照追认成授权，也不能先把坏 installed
        # 放入 journal，使补偿完成后连冲突日志自身都无法持久化。
        fields = []
        if len(current.identity) != 7 or len(after.identity) != 7:
            fields.append("identity.shape")
        else:
            names = ("device", "inode", "mode", "nlink", "size", "mtime")
            fields.extend("identity." + name for name, old, new in zip(names, after.identity[:6], current.identity[:6]) if old != new)
        if current.mode != after.mode:
            fields.append("mode")
        if current.security != after.security:
            fields.append("security")
        # CLI/TUI 只报告路径和字段类别；完整 inode/时间戳/权限摘要留给原生
        # 验收的即时观测日志，不把内部机器元数据塞进产品用户提示。
        raise ActivationError("发布节点与已登记 stage 不一致：" + row["path"]
                              + "（字段：" + ", ".join(fields or ["actual_witness"]) + "）")
    row["installed"] = current.value()


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
    file_stage = os.name == "nt" and after.kind == "file"
    if file_stage:
        # 普通文件必须与 target 同父目录。先私有写入，再精确克隆旧 DACL；
        # 任何克隆/继承复核失败均发生于隔离原件之前，不降级为权限近似。
        descriptor = os.open(stage_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as stream:
            row["stage_inode"] = list(node_id(os.fstat(stream.fileno())))
            save()
            stream.write(after.payload); stream.flush()
            os.fchmod(stream.fileno(), after.mode); os.fsync(stream.fileno())
        if before.kind == "file":
            clone_file_permissions(parent, name, stage_name)
        staged = read_at(parent, stage_name)
        if list(staged.identity[:2]) != row["stage_inode"]:
            raise ActivationError("stage 文件在读取前已被替换")
        after = _register_stage(row, staged)
        os.fsync(parent)
        save()
        if read_at(parent, name) != before:
            raise ActivationError("节点在 stage 准备期间变化：" + row["path"])
    elif after.kind != "missing":
        os.mkdir(stage_name, 0o700, dir_fd=parent)
        stage = os.open(stage_name, project_files.DIR_FLAGS, dir_fd=parent)
        try:
            row["stage_inode"] = list(node_id(os.fstat(stage)))
            if os.name == "nt":
                from lib.windows_fs import security_fingerprint
                row["stage_security"] = security_fingerprint(stage)
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
            after = _register_stage(row, staged)
            os.fsync(stage)
            save()  # 崩溃后只撤回这个 inode，不凭相同字节删除别人的后来保存。
            if read_at(parent, name, allow_link=bool(skill_parts(row["path"]))) != before:
                raise ActivationError("节点在 stage 准备期间变化：" + row["path"])
        except BaseException:
            os.close(stage)
            raise
    try:
        if before.kind != "missing":
            if read_at(parent, backup, allow_link=True, skill_name=skill_parts(row["path"])[1] if skill_parts(row["path"]) else None).kind != "missing":
                raise ActivationError("旧 inode 保留位置发生碰撞")
            move_at(name, backup, src_dir_fd=parent, dst_dir_fd=parent, expected=before)
            moved = read_at(parent, backup, allow_link=True, skill_name=skill_parts(row["path"])[1] if skill_parts(row["path"]) else None)
            if not _same_moved(moved, before):
                raise ActivationError("旧 inode 在隔离时发生保存，已保留：" + row["backup"])
        if after.kind != "missing":
            publish_at(stage_name if file_stage else name, name,
                       src_dir_fd=parent if file_stage else stage, dst_dir_fd=parent, expected=staged)
        os.fsync(parent)
        current = read_at(parent, name, allow_link=bool(skill_parts(row["path"])))
        _register_installed(row, current)
        save()
        tree.check()
    finally:
        if stage is not None:
            os.close(stage)
            # 空 stage 只有身份仍匹配才可移除。包含未知/失败内容时保留给恢复。
            info = os.stat(stage_name, dir_fd=parent, follow_symlinks=False)
            if list(node_id(info)) == row["stage_inode"]:
                try:
                    if os.name == "nt":
                        from lib.windows_fs import delete_directory
                        delete_directory(parent, stage_name, expected={"identity": tuple(row["stage_inode"]),
                                                                       "security": row["stage_security"]})
                    else:
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
    from lib.hosts.workflow_hook_install import json_object, managed_inline, managed_json
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
            backup = _raw(tree, row["backup"], skill_name=skill_parts(row["path"])[1] if skill_parts(row["path"]) else None)
            if backup.kind == "missing" and not any(key in row for key in ("stage_inode", "published_inode", "installed")):
                _cleanup_stage(tree, row)
                continue  # 从未触碰的行无需补偿，尤其不能把尚未归档的旧目录当成新文件。
            parent, name = tree.parent(row["path"])
            actual = read_at(parent, name, allow_link=bool(skill_parts(row["path"])))
            if backup.kind != "missing" and not _same_moved(backup, before):
                raise ActivationError("旧 inode 已有后续保存，拒绝恢复")
            if actual.kind == "missing":
                if backup.kind != "missing":
                    publish_at(Path(row["backup"]).name, name, src_dir_fd=parent, dst_dir_fd=parent, expected=backup)
                elif before.kind != "missing":
                    raise ActivationError("原文件和旧 inode 均缺失")
            elif _same_moved(actual, before) and backup.kind == "missing":
                pass
            elif (list(actual.identity[:2]) == row.get("published_inode")
                  and (same_published_node(actual, after) if os.name == "nt" else
                       actual.same_content(after) and content_mode(actual.mode) == content_mode(after.mode))):
                rolled = Path(row["rollback"]).name
                if _raw(tree, row["rollback"]).kind != "missing":
                    raise ActivationError("回滚 inode 保留位置发生碰撞")
                move_at(name, rolled, src_dir_fd=parent, dst_dir_fd=parent, expected=actual)
                moved = read_at(parent, rolled, allow_link=True, skill_name=skill_parts(row["path"])[1] if skill_parts(row["path"]) else None)
                retained.append(_retained_record(row["rollback"], moved, skill_name=skill_parts(row["path"])[1] if skill_parts(row["path"]) else None))
                if not _same_moved(moved, actual):
                    raise ActivationError("撤下产物时检测到后续保存，已保留")
                if before.kind != "missing":
                    if backup.kind == "missing":
                        raise ActivationError("原 inode 缺失，拒绝用正文副本冒充恢复")
                    publish_at(Path(row["backup"]).name, name, src_dir_fd=parent, dst_dir_fd=parent, expected=backup)
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
    if _history_writes(tree, old.get("retained_nodes", []) + previous_journal.get("retained_nodes", [])):
        raise ActivationError("保留的旧 inode 在预览后发生保存")

def _journal_value(plan: ActivationPlan, identifier: str) -> dict:
    """真实执行与容量证明共用初始journal格式，避免两个wire实现逐渐分叉。"""
    journal = {"schema_version": 1, "project_root": str(plan.project), "id": identifier,
               "phase": "prepared", "action": plan.action,
               "binding_before": plan.machine_before.value(), "changes": [], "conflicts": []}
    for index, change in enumerate(plan.changes):
        # journal 保存规范逻辑路径，不是宿主文件系统路径。与唯一 decoder
        # 按同一 '/' 边界取父前缀，避免 Windows Path 把父目录序列化成 '\\'；
        # backup/stage/rollback 的 nonce、序号和后缀仍由严格 codec 逐项核对。
        parent, _, _ = change.relative.rpartition("/")
        prefix = parent + "/" if parent else ""
        stem = prefix + f".agent-workflow-central-{identifier}-{index}"
        journal["changes"].append({"path": change.relative, "before": change.before.value(),
                                   "after": change.after.value(), "backup": stem + ".previous",
                                   "stage": stem + ".stage", "rollback": stem + ".rollback"})
    return journal


def _retained_base(old: dict | None, previous_journal: dict) -> list[dict]:
    return list({item["path"]: item for item in (old["retained_nodes"] if old else [])
                 + previous_journal.get("retained_nodes", [])}.values())


def _binding_value(plan: ActivationPlan, identifier: str, managed: dict, retained: list, project_identity: list) -> dict:
    old = unique_json(plan.machine_before.payload) if plan.machine_before.kind == "file" else None
    selected = store.validate_binding(unique_json(plan.binding_json))
    used = list(old["used_bindings"]) if old else []
    if selected not in used:
        used.append(selected)
    previous = old["previous_binding"] if old else None
    if old and old["runtime_binding"] != selected:
        previous = old["runtime_binding"]
    return {"schema_version": 1, "project_root": str(plan.project), "project_identity": project_identity,
            "runtime_binding": selected, "enabled": plan.enabled_after, "hosts": list(plan.hosts),
            "previous_binding": previous, "used_bindings": used, "managed": managed,
            "retained_nodes": retained, "generation": identifier}


def _journal_bytes(journal: dict) -> bytes:
    return json_bytes({**journal, "conflicts": bounded_conflicts(journal["conflicts"])})


def publication_budget(plan: ActivationPlan) -> PublicationBudget:
    """从固定资源正文、原像和真实builder证明项目所有发布阶段的容量。

    成功后像将被中央嵌入；失败journal只在本项目持久化，不会假装成中央的
    成功后像。future身份仅为字节上界，永不交给ownership/admission消费。
    """
    if not isinstance(plan, ActivationPlan) or plan.recovery or plan.binding_json is None:
        raise ActivationError("项目提案缺少可证明的容量预算")
    identifier = "f" * 32
    journal = _journal_value(plan, identifier)
    old = unique_json(plan.machine_before.payload) if plan.machine_before.kind == "file" else None
    previous = unique_json(plan.journal_before.payload) if plan.journal_before.kind == "file" else {}
    retained = _retained_base(old, previous)
    for row, change in zip(journal["changes"], plan.changes):
        if change.after.kind != "missing":
            row["stage_inode"] = list(CAPACITY_IDENTITY[:2])
            row["published_inode"] = list(CAPACITY_IDENTITY[:2])
            if os.name == "nt":
                row["after"] = capacity_node_value(change.after)
            if change.after.kind == "link":
                if os.name == "nt":
                    row["stage_security"] = "f" * 64
                row["after"]["mode"] = 0o7777
        row["installed"] = capacity_node_value(change.after)
        if change.before.kind != "missing":
            retained.append(_retained_record(row["backup"], change.before, skill_name=skill_parts(change.relative)[1] if skill_parts(change.relative) else None))
    managed = unique_json(plan.managed_json)
    for item in managed.values():
        item["expected"] = capacity_node_value(Node.from_value(item["expected"]))
    identity = list(dict(plan.directories)[""][:2])
    binding = _binding_value(plan, identifier, managed, retained, identity)
    # enabled=False候选比True多一个字节，真实桥验证阶段也须纳入容量证明。
    binding_size = len(json_bytes({**binding, "enabled": False}))
    journal["phase"] = "applied"
    journal_size = len(json_bytes(journal))
    rollback = copy.deepcopy(journal)
    rollback["phase"] = "rolled_back"
    rollback["retained_nodes"] = [
        _retained_record(row["rollback"], Node(change.after.kind, change.after.payload, 0o7777, CAPACITY_IDENTITY, "f" * 64 if os.name == "nt" else ""),
                         skill_name=skill_parts(change.relative)[1] if skill_parts(change.relative) else None)
        for row, change in zip(journal["changes"], plan.changes) if change.after.kind != "missing"]
    # _restore最多按既有retained、目标行、stage各产生一条冲突，另有Tree.check。
    # 新诊断实际执行相同UTF-8上限；全控制字符覆盖JSON的最坏六倍转义膨胀。
    paths = [row["path"] for row in rollback["retained_nodes"]]
    paths.extend(path for row in journal["changes"] for path in (row["path"], row["stage"]))
    rollback["conflicts"] = [{"path": path, "reason": "\x00" * CONFLICT_REASON_LIMIT} for path in (*paths, ".")]
    for size in (len(plan.machine_before.payload), len(plan.journal_before.payload), binding_size,
                 journal_size, len(json_bytes(rollback))):
        publication_capacity(size)
    return PublicationBudget(binding_size, journal_size)


def apply(plan: ActivationPlan, *, transaction_id: str | None = None) -> dict:
    """应用已预览计划；返回 status 字段及 transaction_id，绝不自动运行 Agent。"""
    if not isinstance(plan, ActivationPlan) or plan.conflicts:
        raise ActivationError("预览含冲突，不能应用", plan.conflicts if isinstance(plan, ActivationPlan) else ())
    if transaction_id is not None and (not isinstance(transaction_id, str) or not re.fullmatch(r"[0-9a-f]{32}", transaction_id)):
        raise ActivationError("项目事务 ID 必须是预分配的完整 nonce")
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
        from . import runtime_policy
        runtime_policy.ensure_management_settled(plan.state)
        if plan.required_global_hosts:
            from . import native_agents
            verified = native_agents.verified_hosts(plan.state, context=plan.native_context)
            if not set(plan.required_global_hosts) <= set(verified):
                raise ActivationError("全局原生角色尚未完整归属，拒绝撤下项目角色")
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
                    delete_at(parent, name, expected=current_node)
                    os.fsync(parent)
            journal["phase"] = "conflict" if conflicts else "rolled_back"
            journal["conflicts"] = conflicts
            journal["retained_nodes"] = retained
            _write_private(machine_tree, _state_relative(plan.project, "transactions"), _journal_bytes(journal))
            if conflicts:
                raise ActivationError("事务恢复含后续手改，已保留现状", conflicts)
            result = status(plan.state, plan.project)
            return {**result, "transaction_id": journal["id"], "recovered": True}
        _check_plan(plan, tree)
        old = unique_json(plan.machine_before.payload) if plan.machine_before.kind == "file" else None
        if plan.binding_json is None:
            return status(plan.state, plan.project)  # 从未启用项目的 disable 为真正幂等空操作。
        identifier = transaction_id or uuid.uuid4().hex
        managed = unique_json(plan.managed_json)
        journal = _journal_value(plan, identifier)
        # 预先检查记录容量，避免改完项目后才发现日志无法持久化。
        json_bytes(journal)
        def save():
            _write_private(machine_tree, _state_relative(plan.project, "transactions"), _journal_bytes(journal))
        save()
        try:
            for row in journal["changes"]:
                _publish(tree, row, core, save)
            tree.check()
            previous_journal = unique_json(plan.journal_before.payload) if plan.journal_before.kind == "file" else {}
            retained = _retained_base(old, previous_journal)
            for row in journal["changes"]:
                prior = _raw(tree, row["backup"], skill_name=skill_parts(row["path"])[1] if skill_parts(row["path"]) else None)
                if prior.kind != "missing":
                    before = Node.from_value(row["before"])
                    if not _same_moved(prior, before):
                        raise ActivationError("保留的旧 inode 在安装检查期间变化")
                    retained.append(_retained_record(row["backup"], prior, skill_name=skill_parts(row["path"])[1] if skill_parts(row["path"]) else None))
            conflicts = _history_writes(tree, retained)
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
            record = _binding_value(plan, identifier, managed, retained, list(node_id(os.fstat(tree.directories[""]))))
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
                    delete_at(parent, name, expected=current)
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


def compensate(state: Path, project: Path, transaction_id: str, binding_before: Node,
               journal_before: Node) -> dict:
    """条件撤销一个已知项目子事务，绝不把 rollback 换版冒充全局补偿。

    全局 prepared 在子事务开始前记录 ID，因此应用返回前中断也能定位原 inode。
    只认同一事务的 journal 与 binding generation；后续管理或手工保存均保留。
    repeated recovery 使用 rolled_back 终态，既不二次安装也不扩大覆盖范围。
    """
    if not isinstance(transaction_id, str) or not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise ActivationError("补偿需要精确项目事务 ID")
    state, project = store.state_root(state), canonical_project(project)
    with ExitStack() as stack:
        stack.enter_context(role_preferences.coordination(state))
        tree = stack.enter_context(Tree(project))
        stack.enter_context(directory_lock(project, "install"))
        stack.enter_context(directory_lock(state / "bindings", "central-project-state"))
        machine_tree = stack.enter_context(Tree(state))
        current, record = read_binding_record(state, project)
        journal_node, journal = _journal(state, project)
        if current == binding_before and journal_node == journal_before:
            return {"compensated": True, "untouched": True, "transaction_id": transaction_id}
        if journal is None or journal["id"] != transaction_id:
            raise ActivationError("项目事务已被后续记录取代，拒绝补偿")
        original_matches = current.same_content(binding_before) and current.mode == binding_before.mode
        own_generation = bool(record and record["generation"] == transaction_id)
        if not own_generation and not original_matches:
            raise ActivationError("项目绑定含后续变更，拒绝补偿")
        if journal["phase"] == "rolled_back" and original_matches:
            return {"compensated": True, "untouched": False, "transaction_id": transaction_id}
        conflicts, retained = _restore(tree, journal)
        tree.check()
        if not conflicts and own_generation:
            if binding_before.kind == "file":
                _write_private(machine_tree, _state_relative(project, "bindings"), binding_before.payload, expected=current)
            else:
                parent, name = machine_tree.parent(_state_relative(project, "bindings"))
                if read_at(parent, name) != current:
                    raise ActivationError("项目绑定在撤回前变化")
                delete_at(parent, name, expected=current)
                os.fsync(parent)
        journal.update(phase="conflict" if conflicts else "rolled_back", conflicts=conflicts, retained_nodes=retained)
        _write_private(machine_tree, _state_relative(project, "transactions"), _journal_bytes(journal), expected=journal_node)
        if conflicts:
            raise ActivationError("项目条件补偿遇到后续手改，已保留恢复资料", conflicts)
        return {"compensated": True, "untouched": False, "transaction_id": transaction_id}


def status(state: Path, project: Path) -> dict:
    """只读本机状态与资源一致性；不会导入来源、创建目录或自动修复。"""
    state, project = store.state_root(state), canonical_project(project)
    _, record = read_binding_record(state, project)
    _, journal = _journal(state, project)
    conflicts, history, recovery_conflicts, native_issues = [], [], [], []
    phase = "unmanaged" if record is None else "enabled" if record["enabled"] else "disabled"
    if journal and journal["phase"] in {"prepared", "conflict"}:
        phase = journal["phase"]
        recovery_conflicts.extend(journal.get("conflicts", []))
    if record:
        core = None
        try:
            core = store.load_core(record["runtime_binding"], state)
        except (OSError, ValueError) as exc:
            conflicts.append({"path": "runtime_binding", "reason": str(exc)})
        with Tree(project) as tree:
            found, owned_links = _ownership(tree, record, state, repair=False, include_history=False)
            conflicts.extend(found)
            history_records = record["retained_nodes"] + (journal.get("retained_nodes", []) if journal else [])
            history = _retained(tree, history_records, typed=True)
            from .runtime_lifecycle import retired_history
            retired = retired_history(state, project)
            active_records = {row["path"]: row for row in history_records}
            history = [row for row in history if not (row["code"] == "history_missing" and retired.get(row["path"]) == active_records.get(row["path"]))]
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
                                             enabled=record["enabled"], check_only=True,
                                             resources=Resources(core.root, json_bytes(core.binding()), core.label, core) if core else None)
            except (OSError, ValueError) as exc:
                conflicts.append({"path": "workflow_hooks", "reason": str(exc)})
            if record["enabled"] and core is not None:
                try:
                    config = tree.read(CONFIG)
                    resources = Resources(core.root, json_bytes(core.binding()), core.label, core)
                    _, profile, _ = project_files.configuration(resources, project, config, owned_links=owned_links)
                    required_hosts = []
                    for host in record["hosts"]:
                        directory, suffix = project_files.ROLE_PATHS[host]
                        for role in profile.enabled_roles:
                            relative = f"{directory}/{role}{suffix}"
                            managed = record["managed"].get(relative)
                            actual = tree.read(relative)
                            if (managed is None or managed["purpose"] != "role"
                                    or Node.from_value(managed["expected"]).kind != "file" or actual.kind != "file"):
                                required_hosts.append(host)
                                break
                    if required_hosts:
                        # 私有global引用由native owner按current generation或本批
                        # activation_scope精确解析；这里绝不猜HOME，也不任取同host
                        # 的历史root。完整local投影不额外依赖全局角色的健康。
                        from . import native_agents
                        native_issues = native_agents.admission_issues(state, hosts=tuple(required_hosts))
                except (OSError, ValueError) as exc:
                    conflicts.append({"path": CONFIG, "reason": "当前角色投影或项目Profile无法验证：" + str(exc)})
    elif _has_install_residue(project):
        phase = "legacy"
    from . import runtime_policy
    global_pending = runtime_policy.pending(state)
    _, policy = runtime_policy.snapshot(state, project)
    controller_issue = None
    try:
        _, current_control = runtime_policy.current_snapshot(state)
        if current_control is not None:
            from lib.runtime_bridge import controller_protocol
            controller = store.load_core(current_control["runtime_binding"], state)
            if controller_protocol(controller) != 1:
                raise ActivationError("中央current缺少受支持的控制协议")
        else:
            controller_issue = {"path": runtime_policy.CURRENT, "reason": "尚无中央current，请先导入并激活版本",
                                "code": "current_missing", "layer": "admission"}
    except (OSError, ValueError):
        current_control = None
        controller_issue = {"path": runtime_policy.CURRENT, "reason": "中央current或控制核心无效",
                            "code": "current_control_invalid", "layer": "admission"}
    # fallback仅作迁移展示；缺失或无资格current不能成为可新建任务的权威。
    # 控制问题只进入admission层，不污染项目资源/历史，也不阻止用合格新core
    # 修复中央current；显式旧pin读取和helper协议0父锁不受候选资格限制。
    effective = policy["runtime_binding"] if policy["mode"] == "pinned" else current_control["runtime_binding"] if current_control else record["runtime_binding"] if record else None
    # 当前资源、历史恢复和发布许可分别计算，禁止从“历史丢失”推断项目停用，
    # 也不让资源仍可用掩盖全局 prepared 门。所有机器分支使用稳定 code/layer。
    issues = [{**row, "code": "current_resource_invalid", "layer": "current"} for row in conflicts]
    issues.extend({**row, "layer": "current"} for row in native_issues)
    issues.extend({**row, "code": "project_recovery_conflict", "layer": "recovery"} for row in recovery_conflicts)
    project_pending = bool(journal and journal["phase"] in {"prepared", "conflict"})
    if project_pending:
        issues.append({"path": _state_relative(project, "transactions"), "reason": "项目事务尚未结算",
                       "code": "project_transaction_pending", "layer": "recovery"})
    issues.extend(history)
    from .runtime_lifecycle import _read_lifecycle
    _, lifecycle = _read_lifecycle(state)
    lifecycle_pending = bool(lifecycle and lifecycle["phase"] in {"prepared", "conflict"})
    if lifecycle_pending:
        issues.append({"path": "central/lifecycle.json", "reason": "生命周期清理尚未结算",
                       "code": "lifecycle_pending", "layer": "management"})
    if controller_issue:
        issues.append(controller_issue)
    if global_pending:
        issues.append({"path": runtime_policy.ACTIVATION, "reason": "中央激活尚未结算",
                       "code": "activation_pending", "layer": "admission"})
    drift = bool(record and effective is not None and record["runtime_binding"] != effective)
    if drift:
        issues.append({"path": "runtime_binding", "reason": "项目实际绑定与有效策略版本不一致",
                       "code": "policy_drift", "layer": "admission"})
    resources_healthy = bool(record and not conflicts and not native_issues)
    new_task_allowed = bool(record and record["enabled"] and resources_healthy and current_control and not global_pending and not project_pending and not drift)
    return {"schema_version": 1, "project": str(project), "state": phase,
            "enabled": bool(record and record["enabled"] and resources_healthy and phase == "enabled"),
            "declared_enabled": bool(record and record["enabled"]),
            "resources_healthy": resources_healthy,
            "history_recoverable": not history,
            "new_task_allowed": new_task_allowed,
            "management_write_allowed": not conflicts and not native_issues and not global_pending and not project_pending and not lifecycle_pending and not any(row["code"] == "history_modified" for row in history),
            "policy": policy["mode"], "effective_binding": effective, "issues": issues,
            "runtime_binding": record["runtime_binding"] if record else None,
            "previous_binding": record["previous_binding"] if record else None,
            "hosts": list(record["hosts"]) if record else [],
            "managed_paths": sorted(record["managed"]) if record else [],
            "conflicts": conflicts + recovery_conflicts + native_issues,
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
                 before: Node, record: dict, changes: tuple, native_context=None):
        self.state, self.project = state, project
        self.tree, self.machine_tree = tree, machine_tree
        self.before, self.record, self.changes = before, record, changes
        self.generation = uuid.uuid4().hex
        self.published = False
        self.native_context = native_context

    def publish(self) -> dict:
        """放在现有 manager.service.commit 的 verify 回调内调用，失败由原事务撤回。

        先验证真实项目产物等于授权 after，再更新中央 expected；任务核心 pin、
        enabled、模型来源与权限不变。上下文持有统一项目锁，中央换版/启停不能
        与这个收据交错，后续机器写入也必须通过 generation 条件才可撤回。
        """
        record = unique_json(json_bytes(self.record))
        deleting_hosts = {host for change in self.changes if change.after is None
                          for host, (directory, suffix) in project_files.ROLE_PATHS.items()
                          if change.relative.startswith(directory + "/") and change.relative.endswith(suffix)}
        if deleting_hosts:
            from . import native_agents
            if self.native_context is None or not deleting_hosts <= set(native_agents.verified_hosts(self.state, context=self.native_context)):
                # 本地文件已由原commit修改但机器收据尚未发布；此处失败交回原
                # 事务精确恢复local。不能仅靠入口时的全局快照承诺仍可发现角色。
                raise ActivationError("稀疏角色删除后全局归属已变化，拒绝发布模型收据")
        for change in self.changes:
            current = self.tree.read(change.relative)
            expected = Node() if change.after is None else Node("file", change.after, change.mode)
            if not current.same_content(expected) or content_mode(current.mode) != content_mode(expected.mode):
                raise ActivationError("模型事务产物与已声明 after 不符：" + change.relative)
            if change.after is None:
                record["managed"].pop(change.relative, None)
            elif change.before is None:
                record["managed"][change.relative] = {"purpose": "role", "baseline": Node().value(), "expected": current.value()}
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
def native_edit_receipt(state: Path, project: Path, changes, *, native_context=None, global_preferences=None):
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
        stack.enter_context(role_preferences.coordination(state))
        from . import runtime_policy
        runtime_policy.ensure_management_settled(state)
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
        config_change = next((change for change in changes if change.relative == CONFIG), None)
        config_before = tree.read(CONFIG)
        if config_before.kind != "file" or (config_change is not None and config_change.after is None):
            raise ActivationError("模型收据必须保留有效项目配置")
        config_after = config_change.after if config_change is not None else config_before.payload
        preferences = role_preferences.snapshot(state)[1] if global_preferences is None else global_preferences
        role_preferences.payload(preferences)
        core = store.load_core(record["runtime_binding"], state)
        resources = Resources(core.root, json_bytes(core.binding()), core.label, core)
        profile = None
        verified = ()
        if native_context is not None:
            from . import native_agents
            verified = native_agents.verified_hosts(state, context=native_context)
        seen = set()
        for change in changes:
            relative = relative_path(change.relative)
            if (relative in seen or change.before is not None and not isinstance(change.before, bytes)
                    or change.after is not None and not isinstance(change.after, bytes)
                    or change.before is None and change.after is None
                    or type(change.mode) is not int):
                raise ActivationError("模型收据变化列表无效或重复")
            seen.add(relative)
            current = tree.read(relative)
            expected_before = Node() if change.before is None else Node("file", change.before, change.mode)
            if not current.same_content(expected_before) or content_mode(current.mode) != content_mode(expected_before.mode):
                raise ActivationError("模型收据前像与当前文件不符：" + relative)
            if relative == CONFIG:
                if change.before is None or change.after is None:
                    raise ActivationError("模型收据不能创建或删除项目配置")
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
            selected_role = next(((host, role) for host, (directory, suffix) in project_files.ROLE_PATHS.items()
                                  for role in role_models.ROLES if relative == f"{directory}/{role}{suffix}"), None)
            if selected_role is None:
                raise ActivationError("模型收据只能修改精确的原生角色路径")
            host, role = selected_role
            if change.before is None or change.after is None:
                # 稀疏投影的增删不是普通 model 补丁：必须由固定核心编译结果
                # 证明完整正文、权限与角色策略；删除还要求宿主全部七角色归属，
                # 不能因单个同名全局文件存在就撤掉唯一可发现的项目角色。
                if profile is None:
                    _, profile, _ = project_files.configuration(resources, project, Node("file", config_after, config_before.mode),
                                                                owned_links={path for path, entry in record["managed"].items() if entry["purpose"] == "skill"})
                if host not in record["hosts"] or role not in profile.enabled_roles or not record["enabled"]:
                    raise ActivationError("稀疏角色不属于项目已启用的宿主和角色")
                if change.before is None:
                    compiled = project_files.role_resource(resources, config_after, host, role, record["runtime_binding"], preferences=preferences)
                    if managed is not None or change.mode != 0o644 or change.after != compiled:
                        raise ActivationError("稀疏角色创建必须等于固定核心完整编译结果")
                else:
                    from lib.hosts import claude_options
                    overrides = role_models.parse(config_after.decode()).get(host, {})
                    claude_override = host == "claude" and role in claude_options.parse(config_after.decode())["auto_compact_windows"]
                    compiled_before = project_files.role_resource(resources, config_before.payload, host, role, record["runtime_binding"],
                                                                  preferences=role_preferences.snapshot(state)[1])
                    if (not managed or managed["purpose"] != "role" or Node.from_value(managed["baseline"]).kind != "missing"
                            or host not in verified or role in overrides or claude_override or change.before != compiled_before):
                        raise ActivationError("稀疏角色删除缺少完整全局归属或仍有项目覆盖")
                continue
            if not managed or managed["purpose"] != "role":
                raise ActivationError("模型收据只能修改已登记的原生角色")
            selected = _model_fields(change.after, host)
            if role_models.patch_artifact(change.before, host, selected) != change.after:
                raise ActivationError("模型收据包含模型字段以外的变化")
        receipt = NativeEditReceipt(state, project, tree, machine_tree, before, record, changes, native_context)
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
                    expected_before = Node() if change.before is None else Node("file", change.before, change.mode)
                    if not tree.read(change.relative).same_content(expected_before):
                        raise ActivationError("模型事务失败且项目仍有后续变化，已保留收据")
                _write_private(machine_tree, _state_relative(project, "bindings"), before.payload)
            raise
