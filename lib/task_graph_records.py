"""任务图的显式记录操作；不派发、不运行测试、不生成批准或 QA 结论。

只处理 PM 已决定的局部变更，复用现有图校验器。文件指纹是字节身份，不是行为
正确性的证据；固定机械操作集中在这里，避免每次任务再生成一组临时 Python。
"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import copy
from contextlib import ExitStack, contextmanager
import hashlib
import json
if __package__:
    from .platform_fs import os
else:
    from platform_fs import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import tempfile
from typing import Any, Callable
import unicodedata

try:
    from .agent_continuation import active as _running, check_binding
    from lib.hosts.claude_instructions import read_file
    from .task_graph import TaskGraphError, SATISFIED_DEPENDENCY_STATES
    from .runtime_pins import PLUGIN_ENV, project_root, read_builtin_source, record_binding
    from .standard_paths import builtin_source_path
except ImportError:
    from agent_continuation import active as _running, check_binding
    from lib.hosts.claude_instructions import read_file
    from task_graph import TaskGraphError, SATISFIED_DEPENDENCY_STATES
    from runtime_pins import PLUGIN_ENV, project_root, read_builtin_source, record_binding
    from standard_paths import builtin_source_path


SET_FIELDS = frozenset({
    "agent_ref", "agent_retired", "handoff_assessment",
    "state", "owned_paths", "semantic_locks", "input_contracts", "output_contracts",
    "acceptance_evidence", "verification_commands", "controlled_document_access",
})
APPEND_FIELDS = SET_FIELDS - {"state", "controlled_document_access", "agent_ref", "agent_retired", "handoff_assessment"}
COMPLETED_STATES = {"BUILD_VERIFIED", "QA_SCOPE_READY", "QA", "QA_PASSED", "RESULT_VERIFIED"}


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
        # 发布锁内复核本轮新结算的独立证据，拒绝把待覆盖记录用作自己的完成证据。
        # 普通发布与历史收据不新增扫描；纯 update 仍不持有隐式输出路径。
        if __package__:
            from .task_settlement import validate_new_settlement_sources
        else:
            from task_settlement import validate_new_settlement_sources
        validate_new_settlement_sources(path, before, body, read=read_record, decode=decode)
        from lib.foundation_qa import validate_publication
        validate_publication(path, before, body)
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


def document_digest(root: Path, relative: str, *, binding: dict | None = None) -> str:
    """受控文档才可读取固定内置源，普通指纹 API 保持项目根和链接拒绝边界。

    判断顺序必须先做精确内置来源分类；不能凭 .agent-workflow 前缀、项目软链或
    外部 core_root 获得读取权限。项目索引、专项叶及其他文档仍使用 file_digest。
    """
    project_root(root)
    if PLUGIN_ENV in os.environ:
        # 插件只改变精确内置来源的定位；普通项目指纹仍使用下方原有根内读取器。
        record_binding({"runtime_binding": binding} if binding is not None else {}, root=root)
    if (binding is not None or PLUGIN_ENV in os.environ) and builtin_source_path(relative) is not None:
        return digest(read_builtin_source(binding, relative))
    return file_digest(root, relative)


def fingerprints(root: Path, manifest: Any, selected: list[str]) -> dict[str, Any]:
    """列表生成指纹，已有映射核对指纹；可直接选择既有回执字段而无需改写回执。"""
    root = project_root(root)
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


def _completed(task: dict[str, Any]) -> bool:
    # 显式 QA 节点的 QA 是正在审查，不是已完成；重审可回到 QA／RUNNING。
    return task["state"] in COMPLETED_STATES and not _running(task)


def update(payload: dict[str, Any], patch: Any, root: Path | None,
           validate: Callable[[str, dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """只更新明确选定的现有任务；批准、依赖、角色和 QA 策略不由本工具改写。"""
    patch = _object(patch, "update patch")
    changes = patch.get("tasks", {})
    if isinstance(changes, dict) and any(isinstance(operation, dict) and "settle" in operation
                                         for operation in changes.values()):
        selected_root = project_root(root)
        marker = selected_root / ".agent-workflow/runtime.json"
        if ("runtime_binding" in payload or marker.exists() or marker.is_symlink()
                or any(name in os.environ for name in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                                                       "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"))):
            raise TaskGraphError("3.0 settlement rejects central runtime_binding and bridge context")
    # update 从原记录读取 pin，补丁白名单不允许添加／替换它；刷新也不能偷用项目当前版。
    binding = record_binding(payload, root=root)
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
        if set(operations) - {"set", "append", "documents", "checkpoint", "settle", "accept_foundation", "accept_request"}:
            raise TaskGraphError(f"unsupported task update operation: {task_id}")
        task = indexed[task_id]
        acceptance = set(operations) & {"accept_foundation", "accept_request"}
        if acceptance:
            if len(acceptance) != 1 or set(operations) != acceptance or set(patch) != {"tasks"} or len(changes) != 1:
                raise TaskGraphError("QA checkpoint acceptance must be the only operation for one task")
            from lib.foundation_qa import accept
            operation = next(iter(acceptance))
            task.update(accept(payload, old[task_id], operations[operation], root=root,
                               kind="foundation" if operation == "accept_foundation" else "request"))
        if "settle" in operations:
            # 结果态、证据引用与可选退休必须作为同一事实原子发布；拒绝同补丁
            # 修改范围或其他任务，避免先改约定再拿旧结果结算。CAS仍由原CLI统一发布。
            if set(operations) != {"settle"} or set(patch) != {"tasks"} or len(changes) != 1:
                raise TaskGraphError("settle must be the only operation for exactly one task")
            if __package__:
                from .task_settlement import settle_task
            else:
                from task_settlement import settle_task
            task.update(settle_task(payload, old[task_id], operations["settle"],
                                    read=read_record, decode=decode))
        fields = _object(operations.get("set", {}), "task.set")
        additions = _object(operations.get("append", {}), "task.append")
        if set(fields) - SET_FIELDS or set(additions) - APPEND_FIELDS:
            raise TaskGraphError("task update attempts to modify a protected or unsupported field")
        if old[task_id].get("foundation_task_id") and fields.get("state") == "QA_PASSED":
            raise TaskGraphError("Foundation request QA_PASSED requires accept_request")
        if fields.get("state") == "RESULT_VERIFIED":
            raise TaskGraphError("RESULT_VERIFIED requires the evidence-bound settle operation")
        if (task["task_type"] in {"read_only", "evidence"} and "state" in fields
                and fields["state"] != old[task_id]["state"]
                and isinstance(fields["state"], str) and fields["state"] in SATISFIED_DEPENDENCY_STATES):
            # 只读/证据任务不能借 Writer 的成功值绕开本轮证据结算。
            raise TaskGraphError("new read_only/evidence completion requires settle")
        for field, value in fields.items():
            if field == "agent_ref":
                # 在套用状态变更之前检查旧记录，身份不是新派发或完成态的凭据。
                check_binding(old[task_id], value)
            if field in APPEND_FIELDS and not isinstance(value, list):
                raise TaskGraphError(f"set {field} requires an array")
        task.update(copy.deepcopy(fields))
        # 退役只使身份不可再次执行，不证明底层已经停止；保留当前活动态与锁。
        # 拒绝复活和true→false，不能靠同补丁改状态绕过不可逆约束。
        if old[task_id].get("agent_retired") and not task.get("agent_retired"):
            raise TaskGraphError("agent_retired cannot be cleared")
        if (task.get("agent_retired") and _running(task)
                and task["state"] != old[task_id]["state"]):
            raise TaskGraphError("retired task cannot re-enter execution")
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
        contract_fields = SET_FIELDS - {"state", "acceptance_evidence", "controlled_document_access", "agent_ref", "agent_retired", "handoff_assessment"}
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
        value = document_digest(project_root(root), name, binding=binding)
        for doc in matches:
            doc["content_fingerprint"] = value
    if "capacity" in patch:
        capacity = patch["capacity"]
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
            raise TaskGraphError("capacity must be an integer >= 0")
        result["capacity"] = capacity
    from lib.foundation_qa import valid_receipt
    for qa in result["tasks"]:
        if qa.get("foundation_receipt") and not valid_receipt(result, qa, root=root):
            qa.pop("foundation_receipt", None)
            qa.pop("request_receipt", None)
            # 已完成的最终QA不能在Foundation返工后复活；活跃Reviewer仍保留原状态
            # 与占用，PM必须先核实实际原生完成，再按同一节点恢复本轮审查。
            if qa["state"] == "QA_PASSED":
                qa["state"] = "DECLARED"
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
                    # 只有 Full 图能证明请求内 Writer 已完成；Light 独立 QA 的完整单包
                    # 不携带兄弟任务，不能用该 barrier 逼它虚构 Full 图或手工改状态。
                    # 两分支仍先校验原合同/身份/退役，再在临时副本中复用 ready 的
                    # 依赖、批准和锁检查；正式记录始终保持 QA，发布仍由原 CAS 保护。
                    if task["workflow_level"] == "Full":
                        candidate["request_id"] = task["request_id"]
                        if not validate("qa-ready", candidate)["qa_ready"]:
                            raise TaskGraphError("QA running-state update is blocked by the existing request QA barrier")
                    task["task_type"] = "read_only"
                    task.pop("foundation_task_id", None)
                    task.pop("foundation_receipt", None)
                    task.pop("request_receipt", None)
        for key, field in (("active_paths", "owned_paths"), ("active_semantic_locks", "semantic_locks")):
            candidate[key] = sorted((set(payload.get(key, [])) - {
                value for task in payload["tasks"] if _running(task) for value in task[field]
            }) | {value for task in candidate["tasks"] if _running(task) for value in task[field]})
        candidate["capacity"] = len(candidate["tasks"])
        if task_id not in validate("ready", candidate)["ready"]:
            raise TaskGraphError("RUNNING update is blocked by existing dependencies, gates or locks")
    return result


# 使用独立容器完成命名升级：旧版原始 ID 也可能恰好长得像哈希名，不能靠正则区分归属。
# 旧 agent-workflow-scratch 容器整体留待原任务或人工核对，不参与新版分配和清理。
SCRATCH_ROOT_NAME = "agent-workflow-request-scratch"
SCRATCH_SLOT_RE = re.compile(r"request-[0-9a-f]{64}\Z")


def _project_scratch_base(root: Path) -> Path:
    """按真实项目根路径派生唯一确定性的临时根目录，避免每个任务自造 /tmp 目录。"""
    if root.is_symlink():
        raise TaskGraphError(f"scratch project root must not be a symlink: {root}")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise TaskGraphError(f"scratch project root must be an existing directory: {root}")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved.name).strip("-._") or "project"
    slug = slug[:48]
    project_hash = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    container = temp_root / SCRATCH_ROOT_NAME
    if container.is_symlink():
        raise TaskGraphError(f"scratch container must not be a symlink: {container}")
    base = container / f"{slug}-{project_hash}"
    if base.is_symlink():
        raise TaskGraphError(f"project scratch root must not be a symlink: {base}")
    return base


def _validated_scratch_slot(request_id: str | None) -> str:
    """逻辑 ID 沿用任务图的非空字符串合同，磁盘名称只使用其完整字节摘要。"""
    logical_id = "shared" if request_id is None else request_id
    if not isinstance(logical_id, str) or not logical_id.strip():
        raise TaskGraphError(f"invalid scratch request_id: {request_id!r}")
    # 不把用户 ID 当路径片段；中文、斜杠、设备保留名及长 ID 均可安全映射。
    # 摘要保留大小写差异，避免 macOS/Windows 上两个逻辑请求共用同一目录。
    return "request-" + hashlib.sha256(logical_id.encode("utf-8")).hexdigest()


@contextmanager
def _scratch_directory(name, *, parent: int | None = None, create: bool = False):
    """相对已打开的父目录创建/打开子目录；不提供跟随链接的降级路径。"""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    descriptor = os.open(name, flags, dir_fd=parent)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _scratch_base_directory(base: Path, *, create: bool = False):
    """从文件系统根逐层固定临时根及受管目录，避免父路径被替换后越界。"""
    temp_root = base.parent.parent
    with ExitStack() as stack:
        descriptor = stack.enter_context(_scratch_directory(temp_root.anchor))
        for part in temp_root.parts[1:]:
            descriptor = stack.enter_context(_scratch_directory(part, parent=descriptor))
        descriptor = stack.enter_context(_scratch_directory(base.parent.name, parent=descriptor, create=create))
        descriptor = stack.enter_context(_scratch_directory(base.name, parent=descriptor, create=create))
        yield descriptor


def scratch_workspace(root: Path, request_id: str | None = None) -> dict[str, Any]:
    """返回并按需创建项目的固定任务临时目录，同一请求重试与 QA 原地复用。"""
    base = _project_scratch_base(root)
    slot = _validated_scratch_slot(request_id)
    target = base / slot
    with _scratch_base_directory(base, create=True) as parent:
        try:
            os.mkdir(slot, 0o700, dir_fd=parent)
            existed = False
        except FileExistsError:
            existed = True
        with _scratch_directory(slot, parent=parent) as descriptor:
            # POSIX 只修改已打开的目录身份；Windows 复用固定祖先句柄的显式后端。
            if os.name == "nt":
                os.chmod(slot, 0o700, dir_fd=parent, follow_symlinks=False)
            else:
                os.fchmod(descriptor, 0o700)
    return {
        "project_scratch_root": str(base),
        "request_id": "shared" if request_id is None else request_id,
        "reused": existed,
        "scratch_dir": str(target),
    }


SCRATCH_SAMPLE_LIMIT = 20


class ScratchCleanupError(TaskGraphError):
    """保留原始失败原因及实际成功计数；递归删除失败不能伪报整批未发生。"""

    def __init__(self, cause: Exception, report: dict[str, Any]):
        super().__init__(str(cause))
        self.report = {**report, "status": "failed", "cleaned": False, "error": str(cause)}


def _scratch_keep_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    """仅接受精确的跨宿主相对文件名，不把用户保留项解释为 glob 或目录授权。"""
    for value in paths:
        if (not isinstance(value, str) or not value.strip() or value != PurePosixPath(value).as_posix()
                or PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive
                or value == "." or ".." in value.split("/") or "\\" in value
                or any(char in value for char in "*?[]")
                or any(unicodedata.category(char).startswith("C") for char in value)):
            raise TaskGraphError(f"scratch keep path must be a normalized relative file: {value!r}")
    return tuple(sorted(set(paths)))


def _scratch_metadata(info) -> tuple[int, ...]:
    """只描述元数据身份，不读取内容，也不把摘要称为文件内容 SHA。

    Windows 后端的 ctime 是创建时间；它只是快照中的一个字段，不能充当 NTFS
    changeTime。双方均依赖调用者先停止写者；保留时间戳的非协作写入不在保证内。
    """
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, getattr(info, "st_file_attributes", 0))


def _scratch_snapshot(parent: int, name: str, relative: str,
                      entries: dict[str, dict[str, Any]]) -> None:
    """只在已固定父目录中扫描当前请求，预览不创建目录、不改权限、不跟随链接。"""
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    metadata = _scratch_metadata(info)
    entry: dict[str, Any] = {"metadata": metadata}
    entries[relative] = entry
    if not stat.S_ISDIR(info.st_mode):
        return
    with _scratch_directory(name, parent=parent) as descriptor:
        if _scratch_metadata(os.fstat(descriptor)) != metadata:
            raise TaskGraphError(f"scratch directory changed while opening: {relative or '.'}")
        names = sorted(os.listdir(descriptor))
        entry["children"] = names
        for child in names:
            _scratch_snapshot(descriptor, child, f"{relative}/{child}" if relative else child, entries)
        # 扫描不是事务；扫描中可见的新增、替换或写入应让预览失败，不能生成混合快照。
        if (sorted(os.listdir(descriptor)) != names
                or _scratch_metadata(os.fstat(descriptor)) != metadata
                or _scratch_metadata(os.stat(name, dir_fd=parent, follow_symlinks=False)) != metadata):
            raise TaskGraphError(f"scratch directory changed while scanning: {relative or '.'}")


def _check_scratch_entry(info, expected: tuple[int, ...], relative: str,
                         removed_links: dict[tuple[int, int], int]) -> None:
    actual = _scratch_metadata(info)
    removed = removed_links.get(expected[:2], 0)
    if removed:
        # 同一 inode 在本槽内可能有多个硬链接。我们已成功 unlink 的别名会改变
        # 剩余别名的 nlink/ctime；只豁免这两个可解释的自身效果，仍核对身份、大小、
        # 权限、mtime 等字段。普通文件绝不为删除而 chmod 或改写内容。
        expected = (*expected[:3], expected[3] - removed, *expected[4:6], actual[6], expected[7])
    if actual != expected:
        raise TaskGraphError(f"scratch entry changed before removal: {relative or '.'}")


def _check_scratch_names(descriptor: int, expected: set[str], relative: str) -> None:
    if set(os.listdir(descriptor)) != expected:
        raise TaskGraphError(f"scratch directory entries changed while cleaning: {relative or '.'}")


def _remove_scratch_item(parent: int, name: str, info, report: dict[str, Any], *, directory: bool = False) -> None:
    """成功后立即记账；Windows 后置 flush 失败时也核对名字是否已真正消失。"""
    def count() -> None:
        if directory:
            report["removed_directories"] += 1
        else:
            report["removed_files"] += 1
            if stat.S_ISREG(info.st_mode):
                report["removed_logical_bytes"] += info.st_size

    try:
        (os.rmdir if directory else os.unlink)(name, dir_fd=parent)
    except (OSError, ValueError):
        # 不把删除后的持久化错误说成没有删除。这里只确认精确名字缺失，不能改用
        # 路径递归补救，也不尝试删除任何同名替换项。
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            count()
        raise
    count()


def _remove_scratch_tree(parent: int, name: str, relative: str,
                         entries: dict[str, dict[str, Any]], keep: set[str],
                         report: dict[str, Any], removed_links: dict[tuple[int, int], int]) -> bool:
    """按预览的固定集合删除，并返回此名字是否已移除；不吸收执行中新增的项。

    目录描述符固定遍历身份，逐项核对只能检测可见竞态，不提供原子的 POSIX
    compare-and-unlink。调用者必须先停止本任务写者；非协作恶意竞争不在保证内。
    """
    entry = entries[relative]
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    _check_scratch_entry(info, entry["metadata"], relative, removed_links)
    if not stat.S_ISDIR(info.st_mode):
        if relative in keep:
            return False
        # POSIX 只 unlink 符号链接本项；Windows 继续由原安全后端拒绝重解析点／硬链接。
        _remove_scratch_item(parent, name, info, report)
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            identity = (info.st_dev, info.st_ino)
            removed_links[identity] = removed_links.get(identity, 0) + 1
        return True
    with _scratch_directory(name, parent=parent) as descriptor:
        opened = os.fstat(descriptor)
        _check_scratch_entry(opened, entry["metadata"], relative, removed_links)
        original_mode = stat.S_IMODE(opened.st_mode)
        widened = False
        remaining = set(entry["children"])
        try:
            if os.name != "nt" and (original_mode & 0o700) != 0o700:
                os.fchmod(descriptor, original_mode | 0o700)
                widened = True
            # 每个目录只在遍历前后枚举集合，避免 N 个文件触发 N 次全目录扫描。
            # 遍历仅消费快照里的名字，逐项仍核对元数据；中途新增项始终不被删除，
            # 结束核对发现后报部分失败。静默前提并不变成可任意并发写入的许可。
            _check_scratch_names(descriptor, remaining, relative)
            for child in entry["children"]:
                child_path = f"{relative}/{child}" if relative else child
                if _remove_scratch_tree(descriptor, child, child_path, entries, keep, report, removed_links):
                    remaining.remove(child)
            _check_scratch_names(descriptor, remaining, relative)
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise TaskGraphError(f"scratch directory changed while cleaning: {relative or '.'}")
        finally:
            # 保留祖先和失败后仍存在的目录都恢复原权限；只对已打开身份操作，不能
            # 用路径 chmod 恢复权限而误伤替换目录或链接指向的外部资源。
            if widened:
                os.fchmod(descriptor, original_mode)
    if remaining:
        return False
    # Windows 目录句柄不共享删除权限，先关闭子句柄，再相对仍固定的父目录删除。
    _remove_scratch_item(parent, name, info, report, directory=True)
    return True


def cleanup_scratch(root: Path, request_id: str | None = None, *, remove_all: bool = False,
                    dry_run: bool = False, keep: tuple[str, ...] = (), expected: str | None = None) -> dict[str, Any]:
    """预览／清理明确归属且已静默的请求；摘要绑定元数据，不承诺物理磁盘回收。

    --all 只供已核实全部归属及静默的显式人工管理；普通任务收口必须使用自己的
    request_id。该工具不从目录名推导授权，不更新图、QA 或实例生命周期状态。
    """
    if remove_all and request_id is not None:
        raise TaskGraphError("cleanup-scratch accepts either --request-id or --all, not both")
    if not remove_all and request_id is None:
        raise TaskGraphError("cleanup-scratch requires --request-id <id> or --all")
    if remove_all and keep:
        raise TaskGraphError("cleanup-scratch --all cannot be combined with --keep")
    if dry_run and expected is not None:
        raise TaskGraphError("cleanup-scratch --dry-run cannot be combined with --expect-sha256")
    if not dry_run and (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
        raise TaskGraphError("cleanup-scratch deletion requires --expect-sha256 from a prior --dry-run")
    kept = _scratch_keep_paths(keep)
    base = _project_scratch_base(root)
    target = base if remove_all else base / _validated_scratch_slot(request_id)
    report: dict[str, Any] = {
        "target": str(target), "dry_run": dry_run, "snapshot_kind": "metadata",
        "kept_files": list(kept), "cleaned": False,
        "removed_files": 0, "removed_directories": 0, "removed_logical_bytes": 0,
        "planned_files": 0, "planned_directories": 0, "planned_logical_bytes": 0,
        "candidate_sample": [], "candidate_sample_truncated": False,
    }
    try:
        with ExitStack() as stack:
            entries: dict[str, dict[str, Any]] = {}
            names: list[str] = []
            exists = False
            # 只有初始目标不存在才是幂等空操作；扫描中丢失文件必须作为冲突失败。
            try:
                parent = stack.enter_context(_scratch_base_directory(base))
                info = os.fstat(parent) if remove_all else os.stat(target.name, dir_fd=parent, follow_symlinks=False)
                exists = True
            except FileNotFoundError:
                parent = None
            if exists:
                if not stat.S_ISDIR(info.st_mode):
                    raise TaskGraphError(f"scratch cleanup target must be a directory, not a link: {target}")
                if remove_all:
                    names = sorted(os.listdir(parent))
                    entries[""] = {"metadata": _scratch_metadata(info), "children": names}
                    selected = [name for name in names if SCRATCH_SLOT_RE.fullmatch(name)]
                    for name in selected:
                        _scratch_snapshot(parent, name, name, entries)
                    if (sorted(os.listdir(parent)) != names
                            or _scratch_metadata(os.fstat(parent)) != entries[""]["metadata"]):
                        raise TaskGraphError("project scratch root changed while scanning")
                else:
                    selected = [target.name]
                    _scratch_snapshot(parent, target.name, "", entries)
            else:
                selected = []
            for relative in kept:
                entry = entries.get(relative)
                if entry is None or not stat.S_ISREG(entry["metadata"][2]):
                    raise TaskGraphError(f"scratch keep path must be an existing regular file without linked ancestors: {relative}")
            retained = set(kept)
            for relative in kept:
                retained.update(str(path) if str(path) != "." else "" for path in PurePosixPath(relative).parents)
            candidates = [path for path in sorted(entries) if path not in retained and not (remove_all and path == "")]
            for path in candidates:
                metadata = entries[path]["metadata"]
                if stat.S_ISDIR(metadata[2]):
                    report["planned_directories"] += 1
                else:
                    report["planned_files"] += 1
                    if stat.S_ISREG(metadata[2]):
                        report["planned_logical_bytes"] += metadata[4]
            report["candidate_sample"] = [path or "." for path in candidates[:SCRATCH_SAMPLE_LIMIT]]
            report["candidate_sample_truncated"] = len(candidates) > SCRATCH_SAMPLE_LIMIT
            snapshot = {"target": str(target), "request_id": request_id, "all": remove_all,
                        "keep": kept, "exists": exists, "entries": entries}
            report["exists"] = exists
            report["snapshot_sha256"] = digest(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                                         separators=(",", ":")).encode("utf-8"))
            if dry_run:
                return {**report, "status": "preview"}
            if report["snapshot_sha256"] != expected:
                raise TaskGraphError("scratch metadata snapshot changed; run --dry-run again before deletion")
            removed_links: dict[tuple[int, int], int] = {}
            remaining = set(names)
            if remove_all and exists:
                _check_scratch_names(parent, remaining, "")
            for name in selected:
                if _remove_scratch_tree(parent, name, name if remove_all else "", entries,
                                        set(kept), report, removed_links) and remove_all:
                    remaining.remove(name)
            if remove_all and exists:
                _check_scratch_names(parent, remaining, "")
            # 项目根始终保留；不在释放最后一个固定句柄后再按路径删除它。
            return {**report, "status": "applied", "cleaned": exists}
    except (OSError, ValueError) as exc:
        raise ScratchCleanupError(exc, report) from exc

