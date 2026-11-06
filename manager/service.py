"""项目列表与模型配置事务；限制写入范围，保留精确备份并保护并发修改。"""

from __future__ import annotations

import base64
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib
import uuid

from lib.claude_instructions import read_file
from lib import role_models, role_preferences, runtime_store
from lib.runtime_project import CONFIG, Node, Tree
from .catalog import Catalog, clean, discover
from . import runtime_service

LOCATIONS = {"codex": (".codex/agents", ".toml"), "claude": (".claude/agents", ".md"), "antigravity": (".agents/agents", ".md")}
SOURCE = Path(__file__).resolve().parents[1]
MAX_RECORD_BYTES = 4 * 1024 * 1024
BACKUP_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


class PreservedEdit(ValueError):
    """隔离文件含其他编辑，必须显式进入冲突日志，不能宣告应用成功。"""
    def __init__(self,path: Path):
        self.retained_path=str(path)
        super().__init__("检测到旧文件版本的后续保存或权限变化，保留版本："+str(path))


def validate_runtime(runtime: Path, *, state: Path | None = None) -> None:
    """只读验证实际中央绑定；旧自包含残留不能冒充当前中央安装。

    中央 core 不位于项目目录；项目身份始终由传入的 .agent-workflow 父目录
    得到，不能从固定 core.parent 推导。无本机记录的 clone 也不能借 locator
    自动获得启用权，缺失/损坏绑定必须直接拒绝，不回退到其他版本。
    """
    from lib.runtime_project import LOCATOR
    project = project_path(runtime.parent)
    status = runtime_service.status(state_root(state), project)
    if status["runtime_binding"] is not None:
        if status["conflicts"] or status["pending_transaction"]:
            raise ValueError("中央项目存在受管资源冲突或未完成事务，请先查看 status / repair")
        core = runtime_store.load_core(status["runtime_binding"], state_root(state))
        runtime_store.read_core_source(core, "lib/role_models.py")
        return
    if secure_path(project, LOCATOR).exists():
        raise ValueError("中央项目缺少当前状态目录的本机绑定，请显式启用；不能继承 clone 的启用状态")
    raise ValueError("项目尚无当前本机中央绑定；先处理旧受管残留，再普通启用")


def ensure_source(catalog: Catalog, project: Path) -> None:
    """锁内仅重查本地来源与身份失效信号，复用 native 快照，避免外部进程阻塞配置事务。"""
    if catalog.stamp and discover(catalog.host,project=project,_snapshot=catalog).stamp != catalog.stamp:
        raise ValueError("模型来源或能力已变化；草稿已保留，请刷新并重新选择后再应用")


class AnchoredFile:
    """固定父目录描述符发布文件，关闭检查路径后目录被换成链接的写出边界。

    所有目录逐段 O_NOFOLLOW 打开；后续读取、临时文件及 replace 都使用同一个
    dir_fd。即使路径在事务中被重命名，也不会沿新链接覆盖项目外的同名文件。
    事务期间保留描述符，回滚仍可定位本轮实际修改的原文件。
    """
    def __init__(self, root: Path, relative: str):
        secure_path(root,relative)
        absolute=root/relative
        self.path=absolute
        self.retainer=None
        descriptor=os.open("/",os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
        try:
            for part in absolute.parent.parts[1:]:
                following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=descriptor)
                os.close(descriptor);descriptor=following
        except BaseException:
            os.close(descriptor);raise
        self.directory=descriptor;self.name=absolute.name

    def __enter__(self):return self
    def __exit__(self,*_):os.close(self.directory)

    def read(self,name=None):
        try:
            descriptor=os.open(name or self.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=self.directory)
        except FileNotFoundError:return None,None
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size>4*1024*1024:
                raise ValueError("管理目标不是有界独占普通文件")
            with os.fdopen(descriptor,"rb",closefd=False) as stream:data=stream.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise ValueError("管理目标超过读取范围")
            return data,stat.S_IMODE(info.st_mode)
        finally:os.close(descriptor)

    def write(self,data: bytes,mode: int,expected=None):
        temporary=".workflow-models-"+uuid.uuid4().hex+".tmp"
        previous=None
        if expected is None:expected=self.read()
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self.directory)
        try:
            with os.fdopen(descriptor,"wb") as stream:
                stream.write(data);stream.flush();os.fchmod(stream.fileno(),mode);os.fsync(stream.fileno())
            # 临时文件完全就绪后再核对，避免磁盘写入期间的编辑被最后一次 replace 吞掉。
            if expected is not None and self.read() != expected:
                raise ValueError("文件在发布前发生其他修改，停止覆盖")
            if expected[0] is not None:
                # 隔离旧目标后重新核验：最后一次检查与移动之间保存的内容也会被发现。
                previous=".workflow-models-previous-"+uuid.uuid4().hex+".tmp"
                os.rename(self.name,previous,src_dir_fd=self.directory,dst_dir_fd=self.directory)
                if self.read(previous) != expected:
                    raise ValueError("文件在最终发布时发生其他修改，停止覆盖")
            # link 是排他创建：目标在隔离后被其他编辑器重新保存时，绝不替换新文件。
            os.link(temporary,self.name,src_dir_fd=self.directory,dst_dir_fd=self.directory,follow_symlinks=False)
        except BaseException:
            if previous is not None:
                try:
                    os.link(previous,self.name,src_dir_fd=self.directory,dst_dir_fd=self.directory,follow_symlinks=False)
                    # 恢复成功后立即去掉临时硬链接，保持目标 nlink=1 的受管读取合同。
                    os.unlink(previous,dir_fd=self.directory)
                    previous=None
                except FileExistsError:
                    # 对方已经新建目标，保留它；若隔离文件也有新增内容则保留供人工核对。
                    if self.read(previous) != expected:
                        raise PreservedEdit(self.path.parent/previous)
                except FileNotFoundError:
                    previous=None
            raise
        finally:
            try:os.unlink(temporary,dir_fd=self.directory)
            except FileNotFoundError:pass
            if previous is not None and self.retainer is not None:
                # 永久保留旧 inode；持有旧 fd 的编辑器即便稍后保存也仍有可找回路径。
                self.retainer(self,previous,expected)
                previous=None
            if previous is not None:
                # 出现双侧新内容时必须保留隔离文件，不能为清理临时文件而丢编辑。
                try:
                    prior=self.read(previous)
                    if prior == expected or self.read(self.name) == prior:
                        os.unlink(previous,dir_fd=self.directory)
                    else:
                        raise PreservedEdit(self.path.parent/previous)
                except PreservedEdit:raise
                except (OSError,ValueError) as exc:
                    raise PreservedEdit(self.path.parent/previous) from exc


def write_state(root: Path,relative: str,data: bytes) -> None:
    with AnchoredFile(root,relative) as target:
        previous=target.read()  # 同样拒绝已有链接、硬链接或特殊文件。
        target.write(data,0o600,previous)


def secure_path(root: Path, relative: str) -> Path:
    """项目内所有读写逐段拒绝链接，避免借管理操作修改另一个项目。"""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise ValueError("管理路径必须是项目内相对路径")
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"管理路径不接受符号链接：{current}")
    return current


def project_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError("项目必须是已存在的普通目录")
    return path.resolve(strict=True)


def state_root(raw: str | Path | None = None) -> Path:
    """沿用中央库唯一状态目录解析；只解析，查询和预览不会创建状态。"""
    return runtime_store.state_root(raw)


def writable_directory(path: Path) -> None:
    """仅在实际保存时创建管理目录；列出项目和模型时不产生状态文件。"""
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"状态目录不可经过符号链接：{component}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def registry(state: Path) -> dict:
    path = secure_path(state, "projects.json")
    return _registry_data(read_file(path))


def _registry_data(raw: bytes | None) -> dict:
    """登记快照与列表共用形状校验，避免计划校验和实际写入各解一份合同。"""
    data=json.loads(raw) if raw else {"schema":1,"registered":[],"hidden":[]}
    if not isinstance(data,dict) or data.get("schema") != 1 or any(not isinstance(data.get(key),list) or not all(isinstance(value,str) for value in data[key]) for key in ("registered","hidden")):
        raise ValueError("项目列表格式无效")
    return data


def projects(state: Path, scan: Path | None = None) -> list[Path]:
    data=registry(state)
    rows=data["registered"]
    hidden=set(data["hidden"])
    result = set()
    for value in rows:
        path = Path(value)
        if path.is_dir() and not path.is_symlink():
            result.add(path.resolve())
    if scan and scan.is_dir():
        # 仅扫描指定目录的直接子目录，不递归业务代码、worktree 或历史会话。
        for child in scan.iterdir():
            if not child.name.startswith(".") and not child.is_symlink() and (child/".agent-workflow/project.yaml").is_file():
                result.add(child.resolve())
    return sorted((row for row in result if str(row) not in hidden), key=lambda row: (row.name.casefold(), str(row)))


def register(state: Path, project: Path, remove: bool = False) -> None:
    # 旧公开签名保留；登记/删除与新入口消费相同计划和条件发布规则。
    apply_project(preview_project(state, project, "del" if remove else "add"))


class ProjectResolutionError(ValueError):
    """短名称拒绝携带明确路径候选，JSON 出口不必展示其他底层错误原文。"""
    def __init__(self, message: str, candidates):
        self.candidates = tuple(str(value) for value in candidates)
        super().__init__(message)


def resolve_project(state: Path, raw: str | Path) -> Path:
    """接受已存在路径或唯一登记短名称；重名和未知名称都明确拒绝。

    短名称只来自显式登记表，不把扫描到的同名目录自动视为用户目标。
    路径存在时仍沿原 project_path 解析，保留调用目录和物理根身份语义。
    """
    candidate = Path(raw).expanduser()
    # 单段裸名称可能同时是 cwd 中的目录和登记名称；先解决登记歧义，不能因为
    # 当前目录偶然存在同名项就绕过重名拒绝。./name 等显式路径仍沿旧路径语义。
    named = not candidate.is_absolute() and "/" not in str(raw) and str(raw) not in {".", ".."}
    if not named:
        return project_path(candidate)
    registered = registry(state)["registered"]
    matches = sorted({project_path(value) for value in registered
                      if Path(value).name == str(raw) and Path(value).is_dir()})
    if len(matches) == 1:
        return matches[0]
    if not matches and (candidate.exists() or candidate.is_symlink()):
        return project_path(candidate)
    candidates = matches or sorted({Path(value) for value in registered})
    detail = "、".join(clean(value, 1000) for value in candidates) or "无登记项目"
    raise ProjectResolutionError(("项目名称重名，请使用完整路径。候选：" if matches else "未知项目名称。已登记候选：") + detail,
                                 candidates)


def project_status(state: Path, project: Path) -> dict:
    """CLI 与 TUI 共用只读状态；state 字段沿原生合同表示业务状态。"""
    return runtime_service.status(state_root(state), project_path(project))


def project_summaries(state: Path, scan: Path | None = None) -> list[dict]:
    """每行展示本机实际版本、前次版、宿主和冲突；单个坏项目不隐藏其余项目。"""
    registered = set(registry(state)["registered"])
    result = []
    for project in projects(state, scan):
        try:
            row = project_status(state, project)
        except (OSError, ValueError):
            # 坏配置可能包含秘密；列表只给固定诊断，单项目操作仍从原生边界拒绝。
            row = {"schema_version": 1, "project": str(project), "state": "conflict", "enabled": False,
                   "runtime_binding": None, "previous_binding": None, "hosts": [], "managed_paths": [],
                   "conflicts": [{"path": ".", "reason": "状态读取失败，请单独检查项目绑定和受管资源"}],
                   "pending_transaction": None}
        result.append({**row, "registered": str(project) in registered})
    return result


def runtime_binding(state: Path, content_id: str) -> dict:
    """内容 ID 必须完整匹配已验证核心；不接受前缀、版本标签或 latest 回退。"""
    binding = runtime_store.validate_binding({"protocol_version": runtime_store.PROTOCOL_VERSION,
                                              "content_id": content_id, "manifest_sha256": content_id})
    return runtime_store.load_core(binding, state_root(state)).binding()


@dataclass(frozen=True)
class ProjectPlan:
    """项目登记组合计划；原生启停/换版仍只有 runtime_service 一份实现。

    registry_before 仅在当前进程用于条件发布，不进入 summary。apply 持登记锁
    并核对原始字节，避免手改或并发登记被覆盖；原生计划自行重查项目和核心。
    """
    state: Path
    project: Path
    action: str
    registry_before: bytes | None
    registered_before: bool
    registered_after: bool
    runtime_plan: runtime_service.ActivationPlan | None
    status_before: dict

    @property
    def summary(self) -> dict:
        native = self.runtime_plan.summary if self.runtime_plan else None
        return {"schema_version": 1, "action": self.action, "project": str(self.project),
                "state_dir": str(self.state), "registered_before": self.registered_before,
                "registered_after": self.registered_after, "runtime_action": native["action"] if native else None,
                "runtime": native, "status_before": self.status_before,
                "can_apply": native["can_apply"] if native else True,
                "conflicts": native["conflicts"] if native else [],
                "changes": native["changes"] if native else []}


def preview_project(state: Path, project: Path, action: str, *, enable: bool = False,
                    source_root: Path | None = None, content_id: str | None = None,
                    hosts=None) -> ProjectPlan:
    """只读生成 add/del/启停/版本计划；首次启用默认使用当前 SOURCE。

    重开已绑定项目默认沿用其精确版本；显式 source_root 才导入指定来源，
    content_id 只选择已存在且验证成功的中央版本。所有原生业务限制交给所有者。
    """
    state, project = state_root(state), project_path(project)
    if action not in {"add", "del", "enable", "disable", "use", "rollback", "repair"}:
        raise ValueError("未知项目管理动作")
    if (type(enable) is not bool or (enable and action != "add")
            or (source_root is not None and content_id is not None)
            or (action == "use" and content_id is None)
            or (content_id is not None and action not in {"add", "enable", "use"})
            or (source_root is not None and action not in {"add", "enable"})
            or (action == "add" and not enable and (source_root is not None or content_id is not None))):
        raise ValueError("项目管理动作与启用/来源/固定版本参数不匹配")
    snapshot = read_file(secure_path(state, "projects.json"))
    data = _registry_data(snapshot)
    registered = str(project) in data["registered"]
    before = project_status(state, project)
    native_action = "enable" if action == "add" and enable else "disable" if action == "del" else action
    native = None
    if native_action != "add":
        selected = runtime_binding(state, content_id) if content_id is not None else None
        source = source_root
        if native_action == "enable" and source is None and selected is None and before["runtime_binding"] is None:
            source = SOURCE
        native = runtime_service.preview(state, project, native_action, source_root=source,
                                         binding=selected, hosts=hosts)
    return ProjectPlan(state, project, action, snapshot, registered,
                       True if action == "add" else False if action == "del" else registered, native, before)


def apply_project(plan: ProjectPlan, *, cancel=None) -> dict:
    """应用同一条件计划；删除先停用成功才解除登记，任何失败都正常抛出。

    登记与项目是跨资源操作，不能宣称原子提交：原生操作已成功而登记写失败时
    保留真实状态并报错，status 仍可查看。取消在开始前无副作用；同步原生事务
    开始后等待结算，并用 cancel_requested 报告迟到请求，不把成功伪报取消。
    """
    if not isinstance(plan, ProjectPlan):
        raise ValueError("需要同一进程生成的项目管理计划")
    if not plan.summary["can_apply"]:
        raise runtime_service.ActivationError("项目预览含冲突，不能应用", plan.summary["conflicts"])
    if cancel is not None and cancel.is_set():
        raise ValueError("操作已取消，尚未应用项目计划")
    registration = plan.action in {"add", "del"}
    with ExitStack() as stack:
        # 组合登记入口也先取偏好协调锁，再取 registry / install / central-state。
        # 仅登记项目同样会改变全局计划的影响集合，不能绕过全局来源守卫。
        stack.enter_context(role_preferences.coordination(plan.state))
        if registration:
            stack.enter_context(lock(plan.state, "registry"))
            if read_file(secure_path(plan.state, "projects.json")) != plan.registry_before:
                raise ValueError("项目登记表在预览后发生变化，请刷新后重试")
        result = runtime_service.apply(plan.runtime_plan) if plan.runtime_plan else project_status(plan.state, plan.project)
        if registration:
            # 持锁不等于可覆盖外部编辑器的保存；发布前仍比较精确前像。
            if read_file(secure_path(plan.state, "projects.json")) != plan.registry_before:
                raise ValueError("原生项目操作已结算，但登记表已有其他修改；未覆盖登记，请查看 status")
            data = _registry_data(plan.registry_before)
            rows, hidden = set(data["registered"]), set(data["hidden"])
            if plan.action == "add":
                rows.add(str(plan.project)); hidden.discard(str(plan.project))
            else:
                rows.discard(str(plan.project)); hidden.add(str(plan.project))
            data.update(registered=sorted(rows), hidden=sorted(hidden))
            payload = (json.dumps(data, ensure_ascii=False, indent=2)+"\n").encode()
            with AnchoredFile(plan.state, "projects.json") as target:
                previous = target.read()
                if previous[0] != plan.registry_before:
                    raise ValueError("原生项目操作已结算，但登记表在发布前变化；已停止覆盖，请查看 status")
                target.write(payload, 0o600, previous)
        return {**result, "action": plan.action, "registered": plan.registered_after,
                "cancel_requested": bool(cancel is not None and cancel.is_set())}


@contextmanager
def lock(state: Path, identifier: str):
    directory = state/"locks"
    writable_directory(directory)
    path = secure_path(directory, hashlib.sha256(identifier.encode()).hexdigest()+".lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("管理锁不是独占普通文件")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("该项目正在由另一管理操作更新，请稍后重试") from exc
        yield
    finally:
        os.close(descriptor)


def roles(project: Path, host: str) -> list[str]:
    directory, suffix = LOCATIONS[host]
    path = secure_path(project, directory)
    return sorted(row.stem for row in path.glob("xy-*"+suffix) if row.stem in role_models.ROLES and row.is_file() and not row.is_symlink()) if path.is_dir() else []


def role_path(project: Path, host: str, role: str) -> Path:
    if host not in LOCATIONS or role not in role_models.ROLES:
        raise ValueError("未知宿主或角色")
    directory, suffix = LOCATIONS[host]
    return secure_path(project, f"{directory}/{role}{suffix}")


def native_settings(raw: bytes, host: str) -> dict[str, str]:
    if host == "codex":
        data = tomllib.loads(raw.decode())
        return role_models.validate(host, {"model": data.get("model", "inherit"), "effort": data.get("model_reasoning_effort", "inherit")})
    front = raw.decode().split("\n---\n", 1)[0]
    model = re.findall(r"^model: (.+)$", front, re.MULTILINE)
    effort = re.findall(r"^effort: (.+)$", front, re.MULTILINE)
    if len(model) != 1 or len(effort) > 1:
        raise ValueError("角色模型字段缺失或重复")
    return role_models.validate(host, {"model":model[0].strip('"\''), "effort":effort[0] if effort else "inherit"})


def role_settings(project: Path, host: str, role: str) -> dict[str, str]:
    raw = read_file(role_path(project, host, role))
    if raw is None:
        raise ValueError("角色尚未安装，请先安装或升级工作流")
    return native_settings(raw, host)


def validate_selection(host: str, value: dict, catalog: Catalog) -> dict:
    # 先由宿主合同校验标准值（其中不含 ultra）。只有目录给出明确能力时才收窄；
    # 空 efforts 表示未知，允许独立设置宿主档位，但不会据此补写模型能力证据。
    value = role_models.validate(host, value)
    model = next((row for row in catalog.models if row.id == value["model"]), None)
    if model is None:
        raise ValueError("所选模型不在当前宿主本地目录中，请刷新来源后重选")
    if model.efforts and value["effort"] != "inherit" and value["effort"] not in model.efforts:
        raise ValueError("该模型缺少所选推理档位的能力证据，请使用继承或受支持档位")
    return value


@dataclass(frozen=True)
class Change:
    relative: str
    before: bytes
    after: bytes
    mode: int


@dataclass(frozen=True)
class RestorePlan:
    """恢复范围与原保留版本一起传递，避免界面确认时丢失并发保护。

    这里只保存预览时已核验的指纹；提交在项目锁内使用同一组指纹复核，
    不重复读取备份 JSON 或重建计划，也不将后来变化的版本自动视为已批准。
    """
    project: Path
    changes: tuple[Change, ...]
    versions: tuple[dict, ...]
    state: Path
    global_before: Node
    config_before: Node
    unchanged_roles: tuple[tuple[str, Node], ...]

    def __iter__(self):return iter(self.changes)
    def __len__(self):return len(self.changes)
    def __getitem__(self,index):return self.changes[index]

    def validate(self,project: Path, *, applied: bool = False) -> None:
        if project != self.project:raise ValueError("恢复计划不属于当前项目")
        _check_versions(project,self.versions)
        # 原生备份只是物化产物，不能独立于逻辑来源恢复。确认前固定全局和项目
        # 配置前像；验收后，配置若在恢复目标中则核对授权 after，否则仍核对原
        # Node 身份，避免另一保存/换文件被当作原先已确认的来源。
        if role_preferences.snapshot(self.state)[0] != self.global_before:
            raise ValueError("全局角色偏好来源在恢复预览后变化，已停止恢复")
        with Tree(project) as tree:
            config = tree.read(CONFIG)
        config_change = next((row for row in self.changes if row.relative == CONFIG), None)
        if applied and config_change is not None:
            unchanged = config.same_content(Node("file", config_change.after, config_change.mode))
        else:
            unchanged = config == self.config_before
        if not unchanged:
            raise ValueError("项目角色偏好来源在恢复预览后变化，已停止恢复")
        with Tree(project) as tree:
            for relative, before in self.unchanged_roles:
                if tree.read(relative) != before:
                    raise ValueError("项目未恢复角色在预览后变化，已停止恢复：" + relative)


def _check_versions(project: Path,versions) -> None:
    """同时核验保留版本的内容和权限；旧 fd 的后续保存不能被恢复操作忽略。"""
    for version in versions:
        with AnchoredFile(project,version["path"]) as target:
            raw,mode=target.read()
        if raw is None or hashlib.sha256(raw).hexdigest() != version["expected_sha"] or mode != version["mode"]:
            raise PreservedEdit(project/version["path"])


def _record_payload(record: dict) -> bytes:
    payload=(json.dumps(record,ensure_ascii=False,indent=2)+"\n").encode()
    if len(payload)>MAX_RECORD_BYTES:
        raise ValueError("本次模型配置备份超出有界读取范围，已停止写入")
    return payload


def _reserve_backup_capacity(record: dict,changes,project: Path,versions_relative: str) -> None:
    """发布前预留正向写入、回滚及冲突索引空间，不能等改完文件才发现日志超限。

    每个目标最多正向和回滚各归档一次。采用两种实际路径中较长者估算，
    并预留相同数量的绝对保留路径及一次额外失败路径；快照正文不另存副本。
    """
    versions=[];retained=[]
    for row in changes:
        paths=[versions_relative+"/"+"0"*32+"-"+Path(row.relative).name,
               str(Path(row.relative).parent/(".workflow-models-previous-"+"0"*32+".tmp"))]
        relative=max(paths,key=lambda value:len(json.dumps(value,ensure_ascii=False).encode()))
        entry={"source":row.relative,"path":relative,"expected_sha":"0"*64,"mode":0o7777}
        versions.extend([entry,entry]);retained.extend([str(project/relative)]*2)
    if retained:retained.append(max(retained,key=lambda value:len(value.encode())))
    _record_payload({**record,"status":"rolled_back","previous_files":versions,"retained_files":retained})


def prepare(project: Path, host: str, choices: dict[str, dict], catalog: Catalog, expected: dict | None = None,
            *, state: Path | None = None, global_preferences: dict | None = None,
            persist: bool = True) -> list[Change]:
    runtime = secure_path(project, ".agent-workflow")
    config_path = secure_path(project, ".agent-workflow/project.yaml")
    config = read_file(config_path)
    if config is None:
        raise ValueError("项目缺少工作流配置")
    try:
        all_choices = role_models.parse(config.decode())
        original_choices = json.loads(json.dumps(all_choices))
    except (ValueError, UnicodeError) as exc:
        # 旧解析器的部分诊断携带不合法整行；管理入口不能把适配器中的秘密回显。
        raise ValueError("项目 role_models 配置无效，请先显式修复；未显示配置原文") from exc
    # 先经模型合同的安全错误出口解析适配器；随后验证当前中央归属。不存在旧
    # lib 文件探测或兼容升级分支，任意本地 helper 都不能替代本机有效绑定。
    validate_runtime(runtime, state=state)
    defaults = role_preferences.snapshot(state_root(state))[1] if global_preferences is None else global_preferences
    changes = []
    for role, raw_value in sorted(choices.items()):
        if not isinstance(raw_value,dict) or set(raw_value)-set(role_preferences.FIELDS):
            raise ValueError("角色编辑只接受 model / effort 字段")
        # 只修改传入字段；None 表示清除此范围的覆盖。全局批量物化 persist=False
        # 时传入的完整有效值只用于原生补丁，绝不把它扩写进项目 role_models。
        fields = dict(all_choices.get(host,{}).get(role,{}))
        for field, selected in raw_value.items():
            if selected is None:fields.pop(field,None)
            else:fields[field]=selected
        fields = role_models.explicit(host,fields)
        if persist:
            if fields:all_choices.setdefault(host,{})[role]=fields
            else:all_choices.get(host,{}).pop(role,None)
            value,_ = role_preferences.resolve(defaults,all_choices,host,role)
        else:
            value = role_models.validate(host,raw_value)
        value = validate_selection(host,value,catalog)
        path = role_path(project, host, role)
        raw = read_file(path)
        if raw is None:
            raise ValueError(f"尚未安装角色：{role}")
        if expected and native_settings(raw, host) != expected[role]:
            raise ValueError(f"{role} 在编辑期间被其他操作修改，请丢弃该角色草稿后重新编辑")
        updated = role_models.patch_artifact(raw, host, value)
        if updated != raw:
            changes.append(Change(path.relative_to(project).as_posix(), raw, updated, stat.S_IMODE(path.stat().st_mode)))
    updated_config = (role_models.update(config.decode(), all_choices).encode()
                      if persist and all_choices != original_choices else config)
    if updated_config != config:
        changes.append(Change(".agent-workflow/project.yaml", config, updated_config, stat.S_IMODE(config_path.stat().st_mode)))
    return changes


def check(project: Path, host: str | None = None, *, state: Path | None = None) -> str:
    """只读验证当前中央受管资源，不执行 setup 或安装转换。

    这里证明项目原生文件与固定核心一致，不能证明宿主已加载配置或运行模型。
    未启用项目直接拒绝，查询不创建绑定或补装资源。
    """
    if host is not None and host not in LOCATIONS:
        raise ValueError("未知宿主")
    checked = project_status(state_root(state), project)
    if checked["runtime_binding"] is not None:
        validate_runtime(secure_path(project, ".agent-workflow"), state=state)
        if host is not None and host not in checked["hosts"]:
            raise ValueError("该宿主不在项目当前中央绑定中")
        binding = checked["runtime_binding"]["content_id"]
        return (f"中央项目只读校验通过；状态：{checked['state']}；固定内容 ID：{binding}；"
                "宿主原生资源已校验，宿主运行加载尚未验证。")
    raise ValueError("项目尚无本机中央绑定；旧安装仅作残留诊断，不执行兼容检查或升级")


def _backup_path(state: Path, project: Path) -> Path:
    return secure_path(state, "backups/"+hashlib.sha256(str(project).encode()).hexdigest()[:20])


def commit(state: Path, project: Path, changes: list[Change] | RestorePlan, verify=None, before_write=None) -> str | None:
    """先备份再写入；失败只撤回仍等于本轮精确产物的文件，绝不覆盖并发修改。"""
    if not changes:
        return None
    # restore 与旧直接调用也必须参与同一全局协调，不能在跨项目计划最后核查
    # 后插入原生变更；外层偏好事务的同线程重入继续由原真实目录锁保护。
    with role_preferences.coordination(state), lock(state, str(project)), ExitStack() as stack:
        if before_write:before_write()
        if isinstance(changes,RestorePlan):changes.validate(project)
        receipt = None
        if project_status(state, project)["runtime_binding"] is not None:
            # 中央锁由唯一原生收据上下文持有；现有模型锁仍只保护备份/配置事务。
            # 收据在任何项目写入前校验声明范围，退出异常时在原事务撤回后恢复前像。
            receipt = stack.enter_context(runtime_service.native_edit_receipt(state, project, changes))
        targets={row.relative:stack.enter_context(AnchoredFile(project,row.relative)) for row in changes}
        for change in changes:
            if targets[change.relative].read() != (change.before,change.mode):
                raise ValueError(f"文件在预览后发生变化，已停止：{change.relative}")
        directory = _backup_path(state, project)
        writable_directory(directory)
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8]
        backup_path = directory/(identifier+".json")
        record = {"schema":1,"project":str(project),"status":"prepared","files":[{
            "path":row.relative,"before":base64.b64encode(row.before).decode(),
            "before_sha":hashlib.sha256(row.before).hexdigest(),"after_sha":hashlib.sha256(row.after).hexdigest(),"mode":row.mode
        } for row in changes]}
        versions_relative=f".agent-workflow-backup-models-{identifier}"
        versions_root=secure_path(project,versions_relative)
        # 容量拒绝发生在任何项目文件/版本目录发布之前，避免 prepared 成为唯一诊断。
        _reserve_backup_capacity(record,changes,project,versions_relative)
        writable_directory(versions_root)
        record["previous_files"]=[]
        for row in changes:
            def retain(target,previous,expected,row=row):
                relative=versions_relative+"/"+uuid.uuid4().hex+"-"+Path(row.relative).name
                archive=None
                version={"source":row.relative,"path":str(Path(row.relative).parent/previous),
                         "expected_sha":hashlib.sha256(expected[0]).hexdigest(),"mode":expected[1]}
                # 先登记可找回位置，再移动 inode；取消发生于 rename 返回边界也不会漏索引。
                record["previous_files"].append(version)
                try:
                    archive=stack.enter_context(AnchoredFile(project,relative))
                    # 目录位于项目同一文件系统；rename 保留 inode，不复制后删除旧版本。
                    os.rename(previous,archive.name,src_dir_fd=target.directory,dst_dir_fd=archive.directory)
                    version["path"]=relative
                except BaseException as exc:
                    # 搬运失败也要记录旧 inode；兼顾 rename 已成功后才报告异常的情况。
                    retained=target.path.parent/previous
                    if archive is not None:
                        try:
                            os.stat(archive.name,dir_fd=archive.directory,follow_symlinks=False)
                            retained=archive.path
                        except FileNotFoundError:pass
                    version["path"]=retained.relative_to(project).as_posix()
                    raise PreservedEdit(retained) from exc
                try:observed=archive.read()
                except BaseException as exc:raise PreservedEdit(archive.path) from exc
                if observed != expected:raise PreservedEdit(archive.path)
            targets[row.relative].retainer=retain
        def save():
            write_state(state,backup_path.relative_to(state).as_posix(),_record_payload(record))
        save()
        written=[]
        try:
            for row in changes:
                target=targets[row.relative]
                if target.read() != (row.before,row.mode):
                    raise ValueError(f"文件发生并发修改，停止写入：{row.relative}")
                written.append(row)
                target.write(row.after,row.mode,(row.before,row.mode))
            if receipt is not None:
                # check 读取中央 expected；先发布仅含模型白名单的收据，随后现有
                # 验证回调才会看到合法新产物。回调/备份失败仍走原精确回滚路径。
                receipt.publish()
            if verify:
                verify()
            # 宿主验收期间旧编辑器也可能保存；在成功记录前检查保留版本。
            _check_versions(project,record["previous_files"])
            if isinstance(changes,RestorePlan):changes.validate(project,applied=True)
            record["status"]="applied"; save()
        except BaseException as failure:
            conflicts=[]
            retained=[]
            if isinstance(failure,PreservedEdit):retained.append(failure.retained_path)
            for row in reversed(written):
                # 一个文件被其他操作替换不能阻断剩余文件的独立撤回。
                try:
                    target=targets[row.relative]
                    current=target.read()
                    if current == (row.after,row.mode):target.write(row.before,row.mode,(row.after,row.mode))
                    elif current != (row.before,row.mode):conflicts.append(row.relative)
                except (OSError,ValueError) as exc:
                    conflicts.append(row.relative)
                    if isinstance(exc,PreservedEdit):retained.append(exc.retained_path)
            record["status"]="conflict" if conflicts or retained else "rolled_back"
            if retained:record["retained_files"]=list(dict.fromkeys(retained))
            try:save()
            except BaseException as logging_failure:
                # 磁盘/索引故障不能吞掉原失败和已经保留的版本位置；让用户仍能找回内容。
                paths=list(dict.fromkeys(retained+[str(project/row["path"]) for row in record["previous_files"]]))
                raise ValueError(f"更新未完成：{failure}；备份 {identifier}；日志保存失败：{logging_failure}；"
                                 "请核对保留版本："+", ".join(paths)) from failure
            if conflicts or retained:
                details=", ".join(conflicts)
                if retained:details+="；保留版本："+", ".join(retained)
                raise ValueError("更新失败且存在并发修改，已保留现状；备份 "+identifier+"，请核对："+details) from failure
            raise
        return identifier


def _load_backup(path: Path,project: Path) -> dict:
    """在备份读入口验证数据形状，避免坏记录触发属性错误并退出整个 TUI。"""
    def invalid():raise ValueError("备份记录格式无效："+path.name)
    try:record=json.loads(read_file(path) or b"{}")
    except RecursionError as exc:
        # 很小的文件也可通过深层数组触发解析器递归上限；仍按单条坏备份隔离。
        raise ValueError("备份记录格式无效："+path.name+"（嵌套过深）") from exc
    if not isinstance(record,dict) or type(record.get("schema")) is not int or record["schema"] != 1 or record.get("project") != str(project):invalid()
    if not BACKUP_ID.fullmatch(path.stem):invalid()
    if not isinstance(record.get("status"),str) or record["status"] not in {"prepared","applied","rolled_back","conflict"}:invalid()
    files=record.get("files");versions=record.get("previous_files");retained=record.get("retained_files",[])
    if not isinstance(files,list) or not files or not isinstance(versions,list):invalid()
    if not isinstance(retained,list) or any(not isinstance(value,str) for value in retained):invalid()
    def fingerprint(value):return isinstance(value,str) and re.fullmatch(r"[0-9a-f]{64}",value)
    def mode(value):return type(value) is int and 0<=value<=0o7777
    seen=set()
    for row in files:
        if not isinstance(row,dict):invalid()
        relative=row.get("path")
        allowed=relative == ".agent-workflow/project.yaml" or any(relative == f"{directory}/{role}{suffix}" for directory,suffix in LOCATIONS.values() for role in role_models.ROLES)
        if not isinstance(relative,str) or not allowed or relative in seen:invalid()
        if not isinstance(row.get("before"),str) or not fingerprint(row.get("before_sha")) or not fingerprint(row.get("after_sha")) or not mode(row.get("mode")):invalid()
        seen.add(relative)
    indexed=set()
    for row in versions:
        if not isinstance(row,dict) or not isinstance(row.get("path"),str) or not isinstance(row.get("source"),str) or row["source"] not in seen:invalid()
        if not fingerprint(row.get("expected_sha")) or not mode(row.get("mode")):invalid()
        secure_path(project,row["path"])
        if record["status"] == "applied":
            source=next(value for value in files if value["path"] == row["source"])
            if row["source"] in indexed or row["expected_sha"] != source["before_sha"] or row["mode"] != source["mode"]:invalid()
            if not row["path"].startswith(f".agent-workflow-backup-models-{path.stem}/"):invalid()
            indexed.add(row["source"])
    if record["status"] == "applied" and indexed != seen:invalid()
    return record


def backups(state: Path, project: Path) -> list[dict]:
    directory=_backup_path(state,project)
    if not directory.is_dir():
        return []
    result=[]
    for path in sorted(directory.glob("*.json"),reverse=True):
        try:record=_load_backup(secure_path(directory,path.name),project)
        except (OSError,ValueError) as exc:
            # 单个损坏备份仍占一条可见记录；保留其他正常备份的查看和恢复入口。
            result.append({"id":path.stem,"status":"invalid","files":[],"error":str(exc)})
            continue
        result.append({"id":path.stem,"status":record.get("status"),"files":[row["path"] for row in record["files"]],
                       "retained_files":record.get("retained_files",[]),"previous_files":record.get("previous_files",[])})
    return result


def backup_summary(project: Path, identifier: str | None) -> str:
    if identifier is None:return "无变更"
    # 保留摘要自身换行，只清理不可信路径/标识；终端不得执行文件名中的 ESC/OSC。
    return (f"备份：{clean(identifier,100)}\n旧文件版本目录：{clean(project,8192)}/.agent-workflow-backup-models-{clean(identifier,100)}\n"
            "旧编辑器若继续保存，可在该版本目录中找回；恢复前会核对后续修改。")


def prepare_restore(state: Path, project: Path, identifier: str) -> RestorePlan:
    if not BACKUP_ID.fullmatch(identifier):
        raise ValueError("无效备份标识")
    path=secure_path(_backup_path(state,project),identifier+".json")
    record=_load_backup(path,project)
    if record["status"] != "applied":
        raise ValueError("只能恢复属于当前项目且成功应用的模型备份")
    # 旧编辑器可能在事务结束后继续通过旧 fd 保存。恢复前必须提示该可找回版本。
    _check_versions(project,record["previous_files"])
    changes=[]
    for row in record["files"]:
        relative=row["path"]
        target=secure_path(project,relative); raw=read_file(target)
        restored=base64.b64decode(row["before"],validate=True)
        if raw is None or hashlib.sha256(raw).hexdigest() != row["after_sha"] or stat.S_IMODE(target.stat().st_mode) != row["mode"]:
            raise ValueError("应用后文件已有其他更改，已停止恢复："+relative)
        if hashlib.sha256(restored).hexdigest() != row["before_sha"]:
            raise ValueError("备份内容指纹不一致")
        changes.append(Change(relative,raw,restored,row["mode"]))
    state = state_root(state)
    global_before, defaults = role_preferences.snapshot(state)
    with Tree(project) as tree:
        config_before = tree.read(CONFIG)
    if config_before.kind != "file":
        raise ValueError("项目缺少有效角色偏好来源，不能恢复模型备份")
    config_change = next((row for row in changes if row.relative == CONFIG), None)
    if config_change is not None and not config_before.same_content(Node("file", config_change.before, config_change.mode)):
        raise ValueError("项目配置在准备恢复期间变化，已停止恢复")
    # 含适配器的项目备份以其拟恢复 after 为权威；仅 native 的全局物化备份
    # 则必须继续服从当前项目覆盖和全局默认。不能为迁就旧产物擅自创建覆盖、
    # 改全局，或只更新 expected 收据后把来源分歧伪报为合法恢复。
    prospective = config_change.after if config_change is not None else config_before.payload
    try:
        choices = role_models.parse(prospective.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("项目角色偏好来源无效，不能核对恢复；未显示配置原文") from exc
    restored_roles = {}
    for change in changes:
        if change.relative == CONFIG:
            continue
        restored_roles[change.relative] = change.after
    unchanged_roles = []
    if config_change is not None:
        # 项目覆盖变化有时不改变当时的有效值，因此其备份可能只有 CONFIG。
        # 后续全局默认已变化时恢复该配置仍会影响现存角色：未列入备份的原生
        # 文件也必须与 prospective 来源相符，且保留其前像，不能漏出第二条
        # “只恢复配置、原生仍是另一有效值”的旁路。这里只读当前已安装角色。
        with Tree(project) as tree:
            for host in LOCATIONS:
                for role in roles(project, host):
                    relative = role_path(project, host, role).relative_to(project).as_posix()
                    if relative not in restored_roles:
                        current = tree.read(relative)
                        restored_roles[relative] = current.payload
                        unchanged_roles.append((relative,current))
    for relative, after in restored_roles.items():
        host = next(host for host, (directory, suffix) in LOCATIONS.items()
                    if relative.startswith(directory + "/") and relative.endswith(suffix))
        role = Path(relative).stem
        try:
            restored = native_settings(after, host)
        except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
            raise ValueError("备份角色模型字段无效，已停止恢复；未显示角色正文") from exc
        effective, _ = role_preferences.resolve(defaults, choices, host, role)
        if restored != effective:
            raise ValueError("备份角色模型与当前全局/项目偏好来源不一致，已停止恢复：" + host + "/" + role)
    plan = RestorePlan(project,tuple(changes),tuple(dict(row) for row in record["previous_files"]),
                       state,global_before,config_before,tuple(unchanged_roles))
    # 解析/比对期间也可能出现外部编辑；返回弹层前再次核对刚才绑定的来源，
    # 后续 commit 会在协调锁内和验收结束前分别复用同一份计划守卫。
    plan.validate(project)
    return plan
