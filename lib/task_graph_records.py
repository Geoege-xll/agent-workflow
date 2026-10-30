"""任务图的显式记录操作；不派发、不运行测试、不生成批准或 QA 结论。

只处理 PM 已决定的局部变更，复用现有图校验器。文件指纹是字节身份，不是行为
正确性的证据；固定机械操作集中在这里，避免每次任务再生成一组临时 Python。
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
if __package__:
    from .platform_fs import os
else:
    from platform_fs import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Callable

try:
    from .claude_instructions import read_file
    from .task_graph import TaskGraphError
except ImportError:
    from claude_instructions import read_file
    from task_graph import TaskGraphError


SET_FIELDS = frozenset({
    "state", "owned_paths", "semantic_locks", "input_contracts", "output_contracts",
    "acceptance_evidence", "verification_commands", "controlled_document_access",
})
APPEND_FIELDS = SET_FIELDS - {"state", "controlled_document_access"}
COMPLETED_STATES = {"BUILD_VERIFIED", "QA_SCOPE_READY", "QA", "QA_PASSED"}


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """变更输入不接受重复键，避免旧值被 JSON 解析静默覆盖。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TaskGraphError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(body: bytes) -> Any:
    return json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)


def read_record(path: Path) -> bytes:
    body = read_file(path.absolute())
    if body is None:
        raise TaskGraphError(f"missing record: {path}")
    return body


def _identity(path: Path) -> tuple[int, ...]:
    info = path.lstat()
    return (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


@contextmanager
def _publication_lock(path: Path):
    """同目录的协作写者互斥，不创建锁文件；无法取得锁时拒写而不是降级裸写。

    目录 fd 不随目标文件替换而失效，进程退出时锁自动释放。此锁仅约束使用本工具
    的协作写者，不宣称能阻止外部编辑器对旧 inode 或目标路径的非协作写入。
    """
    if os.name == "nt":
        try:
            from .platform_fs import directory_lock
        except ImportError:
            from platform_fs import directory_lock
        with directory_lock(path.parent, "taskgraph"):
            yield
        return
    try:
        import fcntl
    except ImportError as exc:
        raise TaskGraphError("record publication requires supported directory advisory locking") from exc
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                         | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise TaskGraphError("record directory is busy or advisory locking is unavailable; do not retry blindly") from exc
        yield
    finally:
        os.close(descriptor)


def publish(path: Path, body: bytes, expected: str) -> bool:
    """持协作锁核对旧指纹，再以原子替换发布；读者只见完整旧文件或新文件。

    不移走正式文件、不创建硬链接或常驻锁文件。PM 是该记录的单一写入者；
    手工编辑应暂停此文件的自动更新。已检测冲突拒写，但非协作写者在最后检查
    与替换间的竞态不在保证范围内，也不承诺文件系统断电后的事务持久性。
    """
    path = path.absolute()
    read_file(path)  # 取得目录锁之前也先拒绝危险父目录、符号链接和硬链接目标。
    with _publication_lock(path):
        before = read_file(path)
        actual = "missing" if before is None else digest(before)
        if expected != actual:
            raise TaskGraphError(f"record fingerprint changed: {path}; expected {expected}, got {actual}")
        if before == body:
            return False
        identity = _identity(path) if before is not None else None
        mode = identity[2] if identity else 0o600
        descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.workflow-", dir=path.parent)
        temporary = Path(raw)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(body)
                os.fchmod(output.fileno(), mode)
                output.flush()
                os.fsync(output.fileno())
            if read_file(path) != before or (identity is not None and _identity(path) != identity):
                raise TaskGraphError(f"record changed before publication: {path}")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskGraphError(f"{label} must be an object")
    return value


def _append(target: dict[str, Any], field: str, values: Any) -> None:
    """有序去重追加，不截断其他已批准内容，也不默认新建缺失的合同字段。"""
    if not isinstance(values, list) or not isinstance(target.get(field), list):
        raise TaskGraphError(f"append {field} requires an existing array and array values")
    for value in values:
        if value not in target[field]:
            target[field].append(copy.deepcopy(value))


def _relative_file(root: Path, relative: str) -> Path:
    """指纹只读取明确列出的根内普通文件，不递归扫描依赖、worktree 或证据目录。"""
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or Path(relative).is_absolute() or Path(relative).as_posix() != relative
            or ".." in Path(relative).parts):
        raise TaskGraphError(f"fingerprint path must be a normalized root-relative file: {relative!r}")
    path = root / relative
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise TaskGraphError(f"fingerprint parent is a symlink: {parent}")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise TaskGraphError(f"fingerprint target must be a single-link regular file: {path}")
    return path


def file_digest(root: Path, relative: str) -> str:
    path = _relative_file(root, relative)
    info = path.stat()
    hasher = hashlib.sha256()
    # 构建产物可以很大，流式读取；不解析或执行文件内容。
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_nlink) != (info.st_dev, info.st_ino, 1):
            raise TaskGraphError(f"fingerprint target changed while opening: {path}")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    current = path.lstat()
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode, 1) != (
            current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_mode, current.st_nlink):
        raise TaskGraphError(f"fingerprint target changed while reading: {path}")
    return hasher.hexdigest()


def fingerprints(root: Path, manifest: Any, selected: list[str]) -> dict[str, Any]:
    """列表生成指纹，已有映射核对指纹；可直接选择既有回执字段而无需改写回执。"""
    root = root.resolve(strict=True)
    if selected:
        document = _object(manifest, "fingerprint receipt")
        manifest = {}
        for field in selected:
            for path, expected in _object(document.get(field), f"receipt.{field}").items():
                if path in manifest and manifest[path] != expected:
                    raise TaskGraphError(f"conflicting expected fingerprints: {path}")
                manifest[path] = expected
    if not isinstance(manifest, (list, dict)) or not manifest:
        raise TaskGraphError("fingerprint input must be a non-empty path array or expected SHA-256 map")
    if isinstance(manifest, dict) and any(
            not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in manifest.values()):
        raise TaskGraphError("expected fingerprints must be lowercase SHA-256 values")
    values = {name: file_digest(root, name) for name in manifest}
    changed = [name for name, value in values.items() if isinstance(manifest, dict) and manifest[name] != value]
    # 核对现有回执只返回摘要，避免把上千条已有指纹再送回模型；新建清单才输出映射。
    result = {"matched": not changed, "checked": len(values), "changed": changed}
    if isinstance(manifest, list):
        result["fingerprints"] = values
    return result


def _documents(task: dict[str, Any]) -> list[dict[str, Any]]:
    """在做局部文档操作前检查容器，坏补丁按输入错误报告而不是抛出内部异常。"""
    access = _object(task.get("controlled_document_access", {}), "controlled_document_access")
    documents = access.get("documents", [])
    if not isinstance(documents, list) or any(not isinstance(doc, dict) or not isinstance(doc.get("path"), str) for doc in documents):
        raise TaskGraphError("controlled_document_access.documents must contain document objects")
    return documents


def _document_contract(task: dict[str, Any]) -> Any:
    """读取说明不是功能合同；仅忽略 reason，仍比较范围、规则、指纹和读取方式。

    新需求必须落在真实输入／输出等合同中，不能藏在 reason 里取得完成态豁免。
    查询定位、文档增删等其他变化仍按原有合同变更处理，不扩大本次例外。
    """
    access = task.get("controlled_document_access")
    if access is None:
        return None
    result = copy.deepcopy(_object(access, "controlled_document_access"))
    result["documents"] = [{key: value for key, value in document.items() if key != "reason"}
                           for document in _documents(task)]
    return result


def _running(task: dict[str, Any]) -> bool:
    """QA 的两个既有运行态共用就绪与锁规则；不新增状态或自动派发。"""
    return task["state"] == "RUNNING" or (task["task_type"] == "qa" and task["state"] == "QA")


def _completed(task: dict[str, Any]) -> bool:
    # 显式 QA 节点的 QA 是正在审查，不是已完成；重审可回到 QA／RUNNING。
    return task["state"] in COMPLETED_STATES and not _running(task)


def update(payload: dict[str, Any], patch: Any, root: Path | None,
           validate: Callable[[str, dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """只更新明确选定的现有任务；批准、依赖、角色和 QA 策略不由本工具改写。"""
    patch = _object(patch, "update patch")
    if set(patch) - {"tasks", "capacity", "refresh_documents", "integrations"}:
        raise TaskGraphError("update patch supports only tasks, capacity, refresh_documents and integrations")
    result = copy.deepcopy(payload)
    indexed = {task["id"]: task for task in result["tasks"]}
    old = {task["id"]: task for task in payload["tasks"]}
    changes = _object(patch.get("tasks", {}), "patch.tasks")
    changed_contracts = set()
    for task_id, operations in changes.items():
        if task_id not in indexed:
            raise TaskGraphError(f"unknown task ID: {task_id}")
        operations = _object(operations, f"patch.tasks.{task_id}")
        if set(operations) - {"set", "append", "documents", "checkpoint"}:
            raise TaskGraphError(f"unsupported task update operation: {task_id}")
        task = indexed[task_id]
        fields = _object(operations.get("set", {}), "task.set")
        additions = _object(operations.get("append", {}), "task.append")
        if set(fields) - SET_FIELDS or set(additions) - APPEND_FIELDS:
            raise TaskGraphError("task update attempts to modify a protected or unsupported field")
        for field, value in fields.items():
            if field in APPEND_FIELDS and not isinstance(value, list):
                raise TaskGraphError(f"set {field} requires an array")
        task.update(copy.deepcopy(fields))
        for field, values in additions.items():
            _append(task, field, values)
        documents = _object(operations.get("documents", {}), "task.documents")
        for name, values in documents.items():
            matches = [doc for doc in _documents(task) if doc["path"] == name]
            if len(matches) != 1:
                raise TaskGraphError(f"document update requires one existing task reference: {name}")
            _append(matches[0], "applies_to", values)
        if "checkpoint" in operations:
            # 仅记录 PM 已核实的现有隔离单元 head；禁止替换根目录、基线或创建隔离身份。
            workspace = _object(task.get("execution_workspace"), "checkpoint requires existing execution_workspace")
            workspace["head_revision"] = copy.deepcopy(operations["checkpoint"])
        # 记录实际证据可以追加；实现输入、输出和规范合同变更则不能沿用旧完成态。
        # 此处先比较，再做单纯指纹刷新，使恢复检查点更新不会废弃无关构建证据。
        contract_fields = SET_FIELDS - {"state", "acceptance_evidence", "controlled_document_access"}
        if (any(task.get(key) != old[task_id].get(key) for key in contract_fields)
                or _document_contract(task) != _document_contract(old[task_id])):
            changed_contracts.add(task_id)
    integrations = _object(patch.get("integrations", {}), "patch.integrations")
    for request_id, values in integrations.items():
        existing = _object(result.get("worktree_integrations", {}), "worktree_integrations")
        if request_id not in existing:
            raise TaskGraphError(f"integration update requires an existing request: {request_id}")
        values = _object(values, f"integrations.{request_id}")
        if set(values) - {"head_revision", "verification"}:
            raise TaskGraphError("integration update supports only head_revision and verification; identity is protected")
        # 不改集成位置、目标分支／基线，也不把旧验证回执自动改绑到新 head。
        # 保留失败或旧 head 的证据，原 qa-ready 会据此继续阻止进入集成 QA。
        _object(existing[request_id], "existing integration").update(copy.deepcopy(values))
    refresh = patch.get("refresh_documents", [])
    if not isinstance(refresh, list) or any(not isinstance(name, str) for name in refresh):
        raise TaskGraphError("refresh_documents must be an array of existing document paths")
    if refresh and root is None:
        raise TaskGraphError("refresh_documents requires --root")
    for name in dict.fromkeys(refresh):
        matches = [doc for task in result["tasks"] for doc in _documents(task) if doc["path"] == name]
        if not matches:
            raise TaskGraphError(f"no existing controlled-document reference: {name}")
        value = file_digest(root.resolve(strict=True), name)
        for doc in matches:
            doc["content_fingerprint"] = value
    if "capacity" in patch:
        capacity = patch["capacity"]
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
            raise TaskGraphError("capacity must be an integer >= 0")
        result["capacity"] = capacity
    # 先校验字段类型与完整合同，再派生锁，避免错误补丁在集合操作中抛出 TypeError。
    validate("validate", result)
    for task_id in changed_contracts:
        if _completed(old[task_id]) and _completed(indexed[task_id]):
            raise TaskGraphError(f"changed completed task scope/contract requires an explicit pending state: {task_id}")
    # 仅重建已知运行任务拥有的锁，含显式 QA 节点；保留外部锁，不推算宿主容量。
    for key, field in (("active_paths", "owned_paths"), ("active_semantic_locks", "semantic_locks")):
        previous = {value for task in payload["tasks"] if _running(task) for value in task[field]}
        current = {value for task in result["tasks"] if _running(task) for value in task[field]}
        result[key] = sorted((set(payload.get(key, [])) - previous) | current)
    # 新执行和运行中换锁都重用既有就绪规则；外部锁从原图扣除旧自有锁，不能被
    # 新增的 claim 吞掉。每次排除当前待查任务，仍保留其他运行中任务的真实锁。
    checking = [key for key in changes if _running(indexed[key]) and (
        old[key]["state"] != indexed[key]["state"] or any(old[key][field] != indexed[key][field]
                                            for field in ("owned_paths", "semantic_locks")))]
    for task_id in checking:
        candidate = copy.deepcopy(result)
        for task in candidate["tasks"]:
            if task["id"] == task_id:
                task["state"] = "DECLARED"
                if task["task_type"] == "qa":
                    # QA 先过原请求级 barrier，再在仅供就绪检查的副本中按只读任务
                    # 核对依赖/批准/锁；正式记录仍是 QA，不更改其角色或调度流程。
                    candidate["request_id"] = task["request_id"]
                    if not validate("qa-ready", candidate)["qa_ready"]:
                        raise TaskGraphError("QA running-state update is blocked by the existing request QA barrier")
                    task["task_type"] = "read_only"
        for key, field in (("active_paths", "owned_paths"), ("active_semantic_locks", "semantic_locks")):
            candidate[key] = sorted((set(payload.get(key, [])) - {
                value for task in payload["tasks"] if _running(task) for value in task[field]
            }) | {value for task in candidate["tasks"] if _running(task) for value in task[field]})
        candidate["capacity"] = len(candidate["tasks"])
        if task_id not in validate("ready", candidate)["ready"]:
            raise TaskGraphError("RUNNING update is blocked by existing dependencies, gates or locks")
    return result
