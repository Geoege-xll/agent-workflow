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
import signal
import stat
import subprocess
import sys
import tomllib
import uuid

from lib.claude_instructions import read_file
from lib.install_workflow import InstallError, _validate_existing
from lib import role_models
from .catalog import Catalog, clean, discover

LOCATIONS = {"codex": (".codex/agents", ".toml"), "claude": (".claude/agents", ".md"), "antigravity": (".agents/agents", ".md")}
SOURCE = Path(__file__).resolve().parents[1]
MAX_RECORD_BYTES = 4 * 1024 * 1024
BACKUP_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


class PreservedEdit(ValueError):
    """隔离文件含其他编辑，必须显式进入冲突日志，不能宣告应用成功。"""
    def __init__(self,path: Path):
        self.retained_path=str(path)
        super().__init__("检测到旧文件版本的后续保存或权限变化，保留版本："+str(path))


def validate_runtime(runtime: Path) -> None:
    """把安装器的正常拒绝统一为界面可展示的业务错误。"""
    try:_validate_existing(runtime)
    except InstallError as exc:raise ValueError(str(exc)) from exc


def ensure_source(catalog: Catalog, project: Path) -> None:
    """确认前仅重查本地来源，不调用模型，不重复执行宿主安装检查。"""
    if catalog.stamp and discover(catalog.host,project=project).stamp != catalog.stamp:
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
    return Path(raw or os.environ.get("AGENT_WORKFLOW_STATE_DIR", Path.home()/".config/agent-workflow")).expanduser().absolute()


def writable_directory(path: Path) -> None:
    """仅在实际保存时创建管理目录；列出项目和模型时不产生状态文件。"""
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"状态目录不可经过符号链接：{component}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def registry(state: Path) -> dict:
    path = secure_path(state, "projects.json")
    raw = read_file(path)
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
    writable_directory(state)
    with lock(state, "registry"):
        data=registry(state)
        rows=set(data["registered"]);hidden=set(data["hidden"])
        rows.discard(str(project)) if remove else rows.add(str(project))
        hidden.add(str(project)) if remove else hidden.discard(str(project))
        data.update(registered=sorted(rows),hidden=sorted(hidden))
        write_state(state,"projects.json",(json.dumps(data, ensure_ascii=False, indent=2)+"\n").encode())


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

    def __iter__(self):return iter(self.changes)
    def __len__(self):return len(self.changes)
    def __getitem__(self,index):return self.changes[index]

    def validate(self,project: Path) -> None:
        if project != self.project:raise ValueError("恢复计划不属于当前项目")
        _check_versions(project,self.versions)


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


def prepare(project: Path, host: str, choices: dict[str, dict], catalog: Catalog, expected: dict | None = None) -> list[Change]:
    runtime = secure_path(project, ".agent-workflow")
    if not (runtime/"lib/role_models.py").is_file():
        raise ValueError("当前项目尚未安装模型配置合同，请先通过管理入口升级工作流")
    validate_runtime(runtime)
    config_path = secure_path(project, ".agent-workflow/project.yaml")
    config = read_file(config_path)
    if config is None:
        raise ValueError("项目缺少工作流配置")
    all_choices = role_models.parse(config.decode())
    changes = []
    for role, raw_value in sorted(choices.items()):
        value = validate_selection(host, raw_value, catalog)
        path = role_path(project, host, role)
        raw = read_file(path)
        if raw is None:
            raise ValueError(f"尚未安装角色：{role}")
        if expected and native_settings(raw, host) != expected[role]:
            raise ValueError(f"{role} 在编辑期间被其他操作修改，请丢弃该角色草稿后重新编辑")
        updated = role_models.patch_artifact(raw, host, value)
        if updated != raw:
            changes.append(Change(path.relative_to(project).as_posix(), raw, updated, stat.S_IMODE(path.stat().st_mode)))
        all_choices.setdefault(host, {})[role] = value
    updated_config = role_models.update(config.decode(), all_choices).encode()
    if updated_config != config:
        changes.append(Change(".agent-workflow/project.yaml", config, updated_config, stat.S_IMODE(config_path.stat().st_mode)))
    return changes


def check(project: Path, host: str | None = None) -> str:
    name = f"setup_{host}.sh" if host else "setup_all.sh"
    script = secure_path(project, f".agent-workflow/{name}")
    if not script.is_file():
        raise ValueError("项目未安装工作流")
    result = subprocess.run(["bash", str(script), "--check"], cwd=project, capture_output=True, text=True,
                            env={**os.environ,"AGENT_WORKFLOW_PYTHON":sys.executable,"PYTHONDONTWRITEBYTECODE":"1"}, timeout=180)
    if result.returncode:
        raise ValueError("安装检查未通过：\n"+(result.stdout+result.stderr)[-6000:])
    return result.stdout[-6000:]


def _backup_path(state: Path, project: Path) -> Path:
    return secure_path(state, "backups/"+hashlib.sha256(str(project).encode()).hexdigest()[:20])


def commit(state: Path, project: Path, changes: list[Change] | RestorePlan, verify=None, before_write=None) -> str | None:
    """先备份再写入；失败只撤回仍等于本轮精确产物的文件，绝不覆盖并发修改。"""
    if not changes:
        return None
    with lock(state, str(project)), ExitStack() as stack:
        if before_write:before_write()
        if isinstance(changes,RestorePlan):changes.validate(project)
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
            if verify:
                verify()
            # 宿主验收期间旧编辑器也可能保存；在成功记录前检查保留版本。
            _check_versions(project,record["previous_files"])
            if isinstance(changes,RestorePlan):changes.validate(project)
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
    return RestorePlan(project,tuple(changes),tuple(dict(row) for row in record["previous_files"]))


def install_preview(project: Path) -> str:
    """只读说明安装范围；实际发布、备份和失败恢复仍交给唯一安装器。"""
    from lib.install_workflow import _target_path
    try:_target_path(str(project), SOURCE)
    except InstallError as exc:raise ValueError(str(exc)) from exc
    runtime=secure_path(project,".agent-workflow")
    if runtime.exists():
        validate_runtime(runtime)
    return (f"项目：{project}\n操作：{'升级' if runtime.exists() else '首次安装'}\n"
            "范围：项目内隐藏运行时、三平台受管入口、角色与核心技能。\n"
            "项目配置保留；文档仅补缺失及更新已标记通用区。\n"
            "升级前保存旧运行时；失败由现有安装器恢复。\n"
            "不修改业务代码、全局宿主配置、Git 分支或 worktree。")


def install(project: Path,cancel=None) -> str:
    install_preview(project)
    if cancel is not None and cancel.is_set():raise ValueError("安装已取消，尚未启动安装器")
    # 超时由安装器内部处理；外层等待恢复结束，不能用 timeout 强杀唯一事务进程。
    process=subprocess.Popen(["bash",str(SOURCE/"install.sh"),str(project),"--timeout","600"],cwd=project,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,
                             env={**os.environ,"AGENT_WORKFLOW_PYTHON":sys.executable,"PYTHONDONTWRITEBYTECODE":"1"})
    cancelled=False
    try:
        while True:
            # TUI 的 SIGINT 只到主线程；显式事件把取消请求传给实际持锁的安装线程。
            if cancel is not None and cancel.is_set() and not cancelled:
                cancelled=True
                try:process.send_signal(signal.SIGINT)
                except ProcessLookupError:pass
            try:
                output,error=process.communicate(timeout=.1 if cancel is not None else None)
                break
            except subprocess.TimeoutExpired:continue
    except KeyboardInterrupt:
        # CLI 取消时通知安装器做恢复，仍等待其退出后才让调用方释放项目锁。
        try:process.send_signal(signal.SIGINT)
        except ProcessLookupError:pass
        while True:
            try:process.communicate();break
            except KeyboardInterrupt:continue
        raise
    if cancelled:
        raise ValueError("安装取消请求已处理，已等待安装器退出；请核对安装器结果：\n"+(output+error)[-6000:])
    if process.returncode:
        raise ValueError("安装未完成，原安装器已报告状态：\n"+(output+error)[-6000:])
    return output[-6000:]
