"""模型配置准备、提交、备份与恢复；保留精确前像并保护并发修改。"""

from __future__ import annotations

import base64
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib
import uuid

from lib.hosts.claude_instructions import read_file
from lib.hosts.native_agents import native_settings
from lib import role_models
from lib.central import role_preferences
from lib import runtime_store
from lib.central.runtime_project import CONFIG, Node, Tree
from .catalog import Catalog, clean, discover
from . import runtime_service, state_files

LOCATIONS = {"codex": (".codex/agents", ".toml"), "claude": (".claude/agents", ".md"), "antigravity": (".agents/agents", ".md")}
MAX_RECORD_BYTES = 4 * 1024 * 1024
BACKUP_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


def validate_runtime(runtime: Path, *, state: Path | None = None) -> None:
    """只读验证实际中央绑定；旧自包含残留不能冒充当前中央安装。

    中央 core 不位于项目目录；项目身份始终由传入的 .agent-workflow 父目录
    得到，不能从固定 core.parent 推导。无本机记录的 clone 也不能借 locator
    自动获得启用权，缺失/损坏绑定必须直接拒绝，不回退到其他版本。
    """
    from lib.central.runtime_project import LOCATOR
    project = state_files.project_path(runtime.parent)
    status = runtime_service.status(state_files.state_root(state), project)
    if status["runtime_binding"] is not None:
        if status["conflicts"] or status["pending_transaction"]:
            raise ValueError("中央项目存在受管资源冲突或未完成事务，请先查看 status / repair")
        core = runtime_store.load_core(status["runtime_binding"], state_files.state_root(state))
        runtime_store.read_core_source(core, "lib/role_models.py")
        return
    if state_files.secure_path(project, LOCATOR).exists():
        raise ValueError("中央项目缺少当前状态目录的本机绑定，请显式启用；不能继承 clone 的启用状态")
    raise ValueError("项目尚无当前本机中央绑定；先处理旧受管残留，再普通启用")


def ensure_source(catalog: Catalog, project: Path) -> None:
    """锁内仅重查本地来源与身份失效信号，复用 native 快照，避免外部进程阻塞配置事务。"""
    if catalog.stamp and discover(catalog.host,project=project,_snapshot=catalog).stamp != catalog.stamp:
        raise ValueError("模型来源或能力已变化；草稿已保留，请刷新并重新选择后再应用")


def roles(project: Path, host: str, *, state: Path | None = None, native_context=None) -> list[str]:
    """角色可用性来自当前绑定宿主与已验证画像，稀疏角色不以文件存在判定。"""
    if host not in LOCATIONS:
        raise ValueError("未知宿主")
    state = state_files.state_root(state)
    _, record = runtime_service.read_binding_record(state, project)
    if not record or not record["enabled"] or host not in record["hosts"]:
        return []
    from lib.central.runtime_project import Resources, configuration, json_bytes
    core = runtime_store.load_core(record["runtime_binding"], state)
    with Tree(project) as tree:
        conflicts, links = runtime_service._ownership(tree, record, state, repair=False)
        if conflicts:
            raise ValueError("项目原生角色归属冲突：文件被修改、缺失或路径包含符号链接")
        config = tree.read(CONFIG)
    _, profile, _ = configuration(Resources(core.root, json_bytes(core.binding()), core.label, core),
                                   project, config, owned_links=links)
    global_ready = False
    if native_context is not None:
        from .native_agents import verified_hosts
        global_ready = host in verified_hosts(state, context=native_context)
    available = []
    for role in profile.enabled_roles:
        relative = role_path(project, host, role).relative_to(project).as_posix()
        local = record["managed"].get(relative)
        if local is not None and local["purpose"] == "role" or global_ready:
            available.append(role)
        elif role_path(project, host, role).exists():
            raise ValueError("项目同名原生角色缺少精确归属")
    return sorted(available)


def role_path(project: Path, host: str, role: str) -> Path:
    if host not in LOCATIONS or role not in role_models.ROLES:
        raise ValueError("未知宿主或角色")
    directory, suffix = LOCATIONS[host]
    return state_files.secure_path(project, f"{directory}/{role}{suffix}")


def role_settings(project: Path, host: str, role: str, *, state: Path | None = None, native_context=None) -> dict[str, str]:
    raw = read_file(role_path(project, host, role))
    if raw is not None:
        return native_settings(raw, host)
    state = state_files.state_root(state)
    if role not in roles(project, host, state=state, native_context=native_context):
        raise ValueError("角色不在当前启用宿主的已验证画像中")
    config = read_file(project / CONFIG)
    if config is None:
        raise ValueError("项目缺少角色偏好配置")
    return role_preferences.resolve(role_preferences.snapshot(state)[1], role_models.parse(config.decode()), host, role)[0]


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
    before: bytes | None
    after: bytes | None
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
        check_versions(project,self.versions)
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


def check_versions(project: Path,versions) -> None:
    """同时核验保留版本的内容和权限；旧 fd 的后续保存不能被恢复操作忽略。"""
    for version in versions:
        with state_files.AnchoredFile(project,version["path"]) as target:
            raw,mode=target.read()
        if raw is None or hashlib.sha256(raw).hexdigest() != version["expected_sha"] or mode != version["mode"]:
            raise state_files.PreservedEdit(project/version["path"])


def record_payload(record: dict) -> bytes:
    """把模型/偏好恢复记录序列化为有界 JSON；超限在发布前拒绝，不截断前像。"""
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
    record_payload({**record,"status":"rolled_back","previous_files":versions,"retained_files":retained})


def prepare(project: Path, host: str, choices: dict[str, dict], catalog: Catalog, expected: dict | None = None,
            *, state: Path | None = None, global_preferences: dict | None = None,
            persist: bool = True, native_context=None, metadata_roles: tuple = ()) -> list[Change]:
    runtime = state_files.secure_path(project, ".agent-workflow")
    config_path = state_files.secure_path(project, ".agent-workflow/project.yaml")
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
    defaults = role_preferences.snapshot(state_files.state_root(state))[1] if global_preferences is None else global_preferences
    changes = []
    effective = {}
    for role, raw_value in sorted(choices.items()):
        if role not in role_models.ROLES or not isinstance(raw_value, dict) or set(raw_value) - set(role_preferences.FIELDS):
            raise ValueError("角色编辑只接受已知角色的 model / effort 字段")
        fields = dict(all_choices.get(host, {}).get(role, {}))
        for field, selected in raw_value.items():
            if selected is None:
                fields.pop(field, None)
            else:
                fields[field] = selected
        fields = role_models.explicit(host, fields)
        if persist:
            if fields:
                all_choices.setdefault(host, {})[role] = fields
            else:
                all_choices.get(host, {}).pop(role, None)
            value, _ = role_preferences.resolve(defaults, all_choices, host, role)
        else:
            value = role_models.validate(host, raw_value)
        if role in metadata_roles:
            effective[role] = value
        elif catalog is None:
            raise ValueError("原生角色物化需要当前模型目录快照")
        else:
            effective[role] = validate_selection(host, value, catalog)
    updated_config = (role_models.update(config.decode(), all_choices).encode()
                      if persist and all_choices != original_choices else config)
    sparse = False
    if native_context is not None:
        from .native_agents import verified_hosts
        sparse = host in verified_hosts(state_files.state_root(state), context=native_context)
    from lib.hosts.claude_options import parse as parse_claude
    windows = parse_claude(updated_config.decode())["auto_compact_windows"]
    for role, value in effective.items():
        if role in metadata_roles:
            continue
        path = role_path(project, host, role)
        raw = read_file(path)
        mode = stat.S_IMODE(path.stat().st_mode) if raw is not None else 0o644
        needed = not sparse or bool(all_choices.get(host, {}).get(role)) or host == "claude" and role in windows
        if expected and (native_settings(raw, host) if raw is not None else role_settings(project, host, role, state=state,
                                                                                       native_context=native_context)) != expected[role]:
            raise ValueError(f"{role} 在编辑期间被其他操作修改，请丢弃该角色草稿后重新编辑")
        if not needed:
            updated = None
        elif raw is not None:
            updated = role_models.patch_artifact(raw, host, value)
        else:
            if role not in roles(project, host, state=state, native_context=native_context):
                raise ValueError("该角色不属于当前已验证画像")
            from lib.central.runtime_project import Resources, json_bytes, role_resource
            _, record = runtime_service.read_binding_record(state_files.state_root(state), project)
            core = runtime_store.load_core(record["runtime_binding"], state_files.state_root(state))
            updated = role_resource(Resources(core.root, json_bytes(core.binding()), core.label, core),
                                    updated_config, host, role, core.binding(), preferences=defaults)
        if updated != raw:
            changes.append(Change(path.relative_to(project).as_posix(), raw, updated, mode))
    if updated_config != config:
        changes.append(Change(CONFIG, config, updated_config, stat.S_IMODE(config_path.stat().st_mode)))
    return changes


def check(project: Path, host: str | None = None, *, state: Path | None = None) -> str:
    """只读验证当前中央受管资源，不执行 setup 或安装转换。

    这里证明项目原生文件与固定核心一致，不能证明宿主已加载配置或运行模型。
    未启用项目直接拒绝，查询不创建绑定或补装资源。
    """
    if host is not None and host not in LOCATIONS:
        raise ValueError("未知宿主")
    checked = runtime_service.status(state_files.state_root(state), project)
    if checked["runtime_binding"] is not None:
        validate_runtime(state_files.secure_path(project, ".agent-workflow"), state=state)
        if host is not None and host not in checked["hosts"]:
            raise ValueError("该宿主不在项目当前中央绑定中")
        binding = checked["runtime_binding"]["content_id"]
        return (f"中央项目只读校验通过；状态：{checked['state']}；固定内容 ID：{binding}；"
                "宿主原生资源已校验，宿主运行加载尚未验证。")
    raise ValueError("项目尚无本机中央绑定；旧安装仅作残留诊断，不执行兼容检查或升级")


def _backup_path(state: Path, project: Path) -> Path:
    return state_files.secure_path(state, "backups/"+hashlib.sha256(str(project).encode()).hexdigest()[:20])


def _expected(body: bytes | None, mode: int) -> tuple:
    return (body, mode) if body is not None else (None, None)


def _fingerprint(body: bytes | None) -> str | None:
    return hashlib.sha256(body).hexdigest() if body is not None else None


def _replace_optional(target, body: bytes | None, mode: int, expected: tuple) -> None:
    """普通发布复用既有原语；删除隔离精确旧 inode，绝不 unlink 后建用户文件。"""
    if body is not None:
        target.write(body, mode, expected)
        return
    if target.read() != expected:
        raise ValueError("删除前原生文件已变化")
    held = ".workflow-models-previous-" + uuid.uuid4().hex + ".tmp"
    try:
        os.rename(target.name, held, src_dir_fd=target.directory, dst_dir_fd=target.directory)
        if target.read(held) != expected:
            raise state_files.PreservedEdit(target.path.parent / held)
    finally:
        # rename可能已经移动inode后才被取消/报错。无论正向删除是否返回成功，
        # 都要登记真实旧inode，不能仅靠正文备份掩盖旧fd稍后保存的用户编辑。
        try:
            os.stat(held, dir_fd=target.directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if target.retainer is not None:
                target.retainer(target, held, expected)
            elif target.read(held) == expected:
                os.unlink(held, dir_fd=target.directory)
            else:
                raise state_files.PreservedEdit(target.path.parent / held)
    if target.read() != (None, None):
        raise ValueError("删除期间目标被外部重新创建，已保留新文件")


def commit(state: Path, project: Path, changes: list[Change] | RestorePlan, verify=None, before_write=None,
           *, native_context=None, global_preferences=None) -> str | None:
    """先备份再写入；失败只撤回仍等于本轮精确产物的文件，绝不覆盖并发修改。"""
    if not changes:
        return None
    # restore 与旧直接调用也必须参与同一全局协调，不能在跨项目计划最后核查
    # 后插入原生变更；外层偏好事务的同线程重入继续由原真实目录锁保护。
    with role_preferences.coordination(state), state_files.lock(state, str(project)), ExitStack() as stack:
        if before_write:before_write()
        if isinstance(changes,RestorePlan):changes.validate(project)
        receipt = None
        if runtime_service.status(state, project)["runtime_binding"] is not None:
            # 中央锁由唯一原生收据上下文持有；现有模型锁仍只保护备份/配置事务。
            # 收据在任何项目写入前校验声明范围，退出异常时在原事务撤回后恢复前像。
            receipt_options = ({"native_context": native_context, "global_preferences": global_preferences}
                               if native_context is not None else {})
            receipt = stack.enter_context(runtime_service.native_edit_receipt(state, project, changes, **receipt_options))
        for row in changes:
            state_files.writable_directory((project / row.relative).parent)
        targets={row.relative:stack.enter_context(state_files.AnchoredFile(project,row.relative)) for row in changes}
        for change in changes:
            if targets[change.relative].read() != _expected(change.before,change.mode):
                raise ValueError(f"文件在预览后发生变化，已停止：{change.relative}")
        directory = _backup_path(state, project)
        state_files.writable_directory(directory)
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8]
        backup_path = directory/(identifier+".json")
        record = {"schema":1,"project":str(project),"status":"prepared","files":[{
            "path":row.relative,"before":base64.b64encode(row.before).decode() if row.before is not None else None,
            "before_sha":_fingerprint(row.before),"after_sha":_fingerprint(row.after),"mode":row.mode
        } for row in changes]}
        versions_relative=f".agent-workflow-backup-models-{identifier}"
        versions_root=state_files.secure_path(project,versions_relative)
        # 容量拒绝发生在任何项目文件/版本目录发布之前，避免 prepared 成为唯一诊断。
        _reserve_backup_capacity(record,changes,project,versions_relative)
        state_files.writable_directory(versions_root)
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
                    archive=stack.enter_context(state_files.AnchoredFile(project,relative))
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
                    raise state_files.PreservedEdit(retained) from exc
                try:observed=archive.read()
                except BaseException as exc:raise state_files.PreservedEdit(archive.path) from exc
                if observed != expected:raise state_files.PreservedEdit(archive.path)
            targets[row.relative].retainer=retain
        def save():
            state_files.write_state(state,backup_path.relative_to(state).as_posix(),record_payload(record))
        save()
        written=[]
        try:
            for row in changes:
                target=targets[row.relative]
                if target.read() != _expected(row.before,row.mode):
                    raise ValueError(f"文件发生并发修改，停止写入：{row.relative}")
                written.append(row)
                _replace_optional(target,row.after,row.mode,_expected(row.before,row.mode))
            if receipt is not None:
                # check 读取中央 expected；先发布仅含模型白名单的收据，随后现有
                # 验证回调才会看到合法新产物。回调/备份失败仍走原精确回滚路径。
                receipt.publish()
            if verify:
                verify()
            # 宿主验收期间旧编辑器也可能保存；在成功记录前检查保留版本。
            check_versions(project,record["previous_files"])
            if isinstance(changes,RestorePlan):changes.validate(project,applied=True)
            record["status"]="applied"; save()
        except BaseException as failure:
            conflicts=[]
            retained=[]
            if isinstance(failure,state_files.PreservedEdit):retained.append(failure.retained_path)
            for row in reversed(written):
                # 一个文件被其他操作替换不能阻断剩余文件的独立撤回。
                try:
                    target=targets[row.relative]
                    current=target.read()
                    if current == _expected(row.after,row.mode):_replace_optional(target,row.before,row.mode,_expected(row.after,row.mode))
                    elif current != _expected(row.before,row.mode):conflicts.append(row.relative)
                except (OSError,ValueError) as exc:
                    conflicts.append(row.relative)
                    if isinstance(exc,state_files.PreservedEdit):retained.append(exc.retained_path)
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
        if (row.get("before") is not None and not isinstance(row.get("before"),str)
                or (row.get("before_sha") is not None and not fingerprint(row.get("before_sha")))
                or (row.get("after_sha") is not None and not fingerprint(row.get("after_sha")))
                or (row.get("before") is None) != (row.get("before_sha") is None)
                or not mode(row.get("mode"))):invalid()
        seen.add(relative)
    indexed=set()
    for row in versions:
        if not isinstance(row,dict) or not isinstance(row.get("path"),str) or not isinstance(row.get("source"),str) or row["source"] not in seen:invalid()
        if not fingerprint(row.get("expected_sha")) or not mode(row.get("mode")):invalid()
        state_files.secure_path(project,row["path"])
        if record["status"] == "applied":
            source=next(value for value in files if value["path"] == row["source"])
            if row["source"] in indexed or row["expected_sha"] != source["before_sha"] or row["mode"] != source["mode"]:invalid()
            if not row["path"].startswith(f".agent-workflow-backup-models-{path.stem}/"):invalid()
            indexed.add(row["source"])
    if record["status"] == "applied" and indexed != {row["path"] for row in files if row["before"] is not None}:invalid()
    return record


def backups(state: Path, project: Path) -> list[dict]:
    directory=_backup_path(state,project)
    if not directory.is_dir():
        return []
    result=[]
    for path in sorted(directory.glob("*.json"),reverse=True):
        try:record=_load_backup(state_files.secure_path(directory,path.name),project)
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
    path=state_files.secure_path(_backup_path(state,project),identifier+".json")
    record=_load_backup(path,project)
    if record["status"] != "applied":
        raise ValueError("只能恢复属于当前项目且成功应用的模型备份")
    # 旧编辑器可能在事务结束后继续通过旧 fd 保存。恢复前必须提示该可找回版本。
    check_versions(project,record["previous_files"])
    changes=[]
    for row in record["files"]:
        relative=row["path"]
        target=state_files.secure_path(project,relative); raw=read_file(target)
        restored=base64.b64decode(row["before"],validate=True) if row["before"] is not None else None
        if _fingerprint(raw) != row["after_sha"] or raw is not None and stat.S_IMODE(target.stat().st_mode) != row["mode"]:
            raise ValueError("应用后文件已有其他更改，已停止恢复："+relative)
        if _fingerprint(restored) != row["before_sha"]:
            raise ValueError("备份内容指纹不一致")
        changes.append(Change(relative,raw,restored,row["mode"]))
    state = state_files.state_root(state)
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
                for role in roles(project, host, state=state):
                    relative = role_path(project, host, role).relative_to(project).as_posix()
                    if relative not in restored_roles:
                        current = tree.read(relative)
                        if current.kind == "file":
                            restored_roles[relative] = current.payload
                        unchanged_roles.append((relative,current))
    for relative, after in restored_roles.items():
        host = next(host for host, (directory, suffix) in LOCATIONS.items()
                    if relative.startswith(directory + "/") and relative.endswith(suffix))
        role = Path(relative).stem
        if after is None:
            # 撤下local后由全局描述符承担值；最终收据还会核验全局七角色归属。
            continue
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
