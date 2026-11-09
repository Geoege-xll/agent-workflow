"""显式原记录的跨请求准入入口；不扫描会话、不创建 Agent、不维护持久资源表。

v1 输入：schema_version=1、project_root、records、capacity。records 每项严格包含
path、sha256、execution_roots（精确 task-id→实际绝对执行根）。Full 必须提供权威图，
Light 提供原单包。view 零写；claim/release 仅在项目 scratch 的短协作锁内读写原记录。
RUNNING 表示已领取；PM 随后在锁外调用原生宿主并通过原 update 绑定 agent_ref。
没有原生幂等键时本入口不承诺 exactly-once。未知结果必须核实，不能自动重试或释放。
单一 PM 必须显式提供完整活动记录并刷新原生容量；共用互斥锁不能发现另一个 PM
省略的记录，不能据此宣称跨 PM/跨会话全局调度。Git common-dir 只作锁域身份，
锁目录始终分配在既有系统 scratch，不向 .git 写入新状态。
"""

from __future__ import annotations

if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import argparse
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any
import unicodedata

from lib import task_graph_records as records
from lib.agent_continuation import active
from lib.dispatch_admission import RecordView, ResourceIdentity, select_candidates, task_key
from lib.platform_fs import directory_lock
from lib.runtime_pins import PROJECT_ENV, project_root
from lib.task_graph import TaskGraphError


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _object(value: Any, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise TaskGraphError(f"{label} requires exactly {', '.join(sorted(fields))}")
    return value


def _absolute(value: Any, *, directory: bool = False) -> Path:
    """显式物理身份不能借软链或 .. 把新执行根伪装成原根。"""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise TaskGraphError("path must be a canonical absolute path")
    path = Path(value)
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise TaskGraphError("path must be a canonical existing absolute path")
    if directory and not path.is_dir():
        raise TaskGraphError("root must be an existing directory")
    return path


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise TaskGraphError("sha256 must be a lowercase byte SHA256")
    return value


def _git_identity(root: Path, *, required: bool = True) -> str:
    """核实 worktree 归属；普通非 Git 项目仍以物理根作协调身份。

    协调域允许项目根位于仓库内，执行 worktree 则必须精确为其 Git 顶层。
    清除可覆盖 -C 语义的 GIT_* 环境，不能由调用者环境把其他仓库当成本项目。
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    has_marker = any((parent / ".git").exists() or (parent / ".git").is_symlink()
                     for parent in (root, *root.parents))
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute",
                                 "--show-toplevel", "--git-common-dir"],
                                env=environment, capture_output=True, text=True, timeout=10, check=False)
    except FileNotFoundError as exc:
        if not required and not has_marker:
            return str(root)
        raise TaskGraphError("Git is required to verify the project coordination identity") from exc
    rows = result.stdout.splitlines()
    if result.returncode and not required and not has_marker:
        return str(root)
    if result.returncode or len(rows) != 2 or (required and Path(rows[0]).resolve(strict=True) != root):
        raise TaskGraphError("execution root must be a verified Git worktree root")
    return str(Path(rows[1]).resolve(strict=True))


def _directory_case_sensitive(directory: Path) -> bool | None:
    """只读核实目录的名称比较规则；未知不能自动当作大小写敏感。

    Darwin SDK 的 sys/unistd.h 将 _PC_CASE_SENSITIVE 定义为 11；Python 未
    暴露该名字，但原生 pathconf 接受相同整数。其他后端用目录内实际 ASCII
    名称及其换大小写查找来核实当前目录，兼容逐目录大小写规则。空目录、
    无可判定名称或权限不足返回未知，后续不存在资源保守锁住最近存在目录。
    不创建探针文件，因此 view 仍然零写；结果只在本次 _load 内按节点身份复用。
    """
    if sys.platform == "darwin":
        try:
            value = os.pathconf(directory, 11)
            if value in (0, 1):
                return bool(value)
        except (OSError, ValueError):
            pass
    try:
        with os.scandir(directory) as entries:
            for position, entry in enumerate(entries):
                if position >= 128:
                    break
                if not entry.name.isascii() or not any(character.isalpha() for character in entry.name):
                    continue
                before = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
                    continue
                try:
                    alias = (directory / entry.name.swapcase()).lstat()
                except FileNotFoundError:
                    return True
                return (before.st_dev, before.st_ino) != (alias.st_dev, alias.st_ino)
    except OSError:
        pass
    return None


def _resource_identity(path: Path, directory_modes: dict[tuple[int, int], bool | None]) -> ResourceIdentity:
    """在文件边界投影真实节点和名称语义，覆盖不存在叶及不存在中间目录。

    每级现有节点都保留 dev/inode 锚点，不能只比较叶或 resolve 的保留大小写
    字符串。名称后缀按各自父目录的已核实规则转换；大小写敏感目录保留大小写。
    现有名称规范等价采用保守 NFD，实际节点仍由 inode 证明。未创建的非 ASCII
    名称涉及尚未核实的卷 Unicode 规则，或目录大小写规则未知时，直接扩大为
    最近现有目录的资源锁，而不猜测一个可能放行的名称比较规则。
    """
    if os.name == "nt":
        # 复用原 Windows owner 的组件合同，拒绝尾点/尾空格、设备名及 ADS，
        # 不能先让 Win32 隐式归一化，再为不存在的资源生成不同锁键。
        from lib.windows_fs import absolute_path
        path = absolute_path(path)
    current = Path(path.anchor)
    root_info = current.lstat()
    nodes = [(0, (root_info.st_dev, root_info.st_ino))]
    names: list[str] = []
    parts = path.parts[1:]
    for position, part in enumerate(parts):
        parent_node = nodes[-1][1]
        if parent_node not in directory_modes:
            directory_modes[parent_node] = _directory_case_sensitive(current)
        sensitive = directory_modes[parent_node]
        child = current / part
        try:
            info = child.lstat()
        except FileNotFoundError:
            remaining_parts = parts[position:]
            if sensitive is not None and all(remaining.isascii() for remaining in remaining_parts):
                for remaining in remaining_parts:
                    name = unicodedata.normalize("NFD", remaining)
                    names.append(name if sensitive else name.casefold())
            # 名称规则未知时不追加剩余段，当前实际目录空后缀即保守子树锁。
            break
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise TaskGraphError("resource path must not traverse symlinks or reparse points")
        name = unicodedata.normalize("NFD", part)
        names.append(name if sensitive else name.casefold())
        nodes.append((len(names), (info.st_dev, info.st_ino)))
        current = child
    return ResourceIdentity(tuple((node, tuple(names[offset:])) for offset, node in nodes))


def _invocation(payload: dict, root: Path, arguments: list[str]) -> tuple[list[str], dict[str, str]]:
    """每条 pin 各自选择已验证核心，不在 B 环境中直接执行 A 的校验器。

    python_helper 的显式 binding 优先于当前环境，并重建 child 的三根与 pin；
    used_bindings、清单完整性和 helper 路径授权仍全部走原桥。源包无中央上下文
    才允许无 pin，不能通过抹去环境把中央缺 pin 任务降级成源码任务。
    """
    binding = payload.get("runtime_binding")
    if binding is not None:
        from lib import runtime_bridge, runtime_store
        call = runtime_bridge.python_helper(runtime_store.state_root(), root,
                                             "lib/task_graph_cli.py", arguments, binding=binding)
        return list(call.command), call.environment
    if any(name in os.environ for name in ("AGENT_WORKFLOW_RUNTIME_BINDING", PROJECT_ENV,
                                          "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT")) or (
            root / ".agent-workflow/runtime.json").exists():
        raise TaskGraphError("central record requires its own runtime_binding")
    core = Path(__file__).resolve().parents[1]
    if os.name == "nt":
        command = [sys.executable, "-I", "-B", "-X", "utf8", str(core / "lib/windows_bootstrap.py"),
                   "--script", str(core / "lib/task_graph_cli.py"), *arguments]
    else:
        command = [sys.executable, "-B", "-X", "utf8", str(core / "lib/task_graph_cli.py"), *arguments]
    return command, dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def _helper(payload: dict, root: Path, arguments: list[str], body: bytes) -> dict:
    command, environment = _invocation(payload, root, arguments)
    try:
        result = subprocess.run(command, input=body, capture_output=True, cwd=root,
                                env=environment, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        # update 可能已发布；不得根据超时推断没有副作用，更不能自动补发或释放。
        raise TaskGraphError("record helper timed out; inspect original record before any retry or release") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise TaskGraphError(f"record helper rejected input (exit {result.returncode}): {detail}")
    value = records.decode(result.stdout)
    if not isinstance(value, dict):
        raise TaskGraphError("record helper returned a non-object result")
    return value


def _query(payload: dict, root: Path, command: str) -> dict:
    result = _helper(payload, root, [command], json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    # 版本已验证不代表任意 helper 输出都满足当前协议；未知/旧能力失败关闭，
    # 不能把随意的 {validated:true} 或缺失结果当成原校验器提供的正向证据。
    if command == "validate" and result != {"status": "valid"}:
        raise TaskGraphError("pinned validator does not implement the required validation result")
    if command == "ready" and (set(result) != {"ready"} or not isinstance(result["ready"], list)
                                or any(not isinstance(item, str) for item in result["ready"])):
        raise TaskGraphError("pinned validator returned an invalid ready result")
    if command == "qa-ready" and (set(result) != {"qa_ready", "request_id"}
                                   or type(result["qa_ready"]) is not bool
                                   or result["request_id"] != payload.get("request_id")):
        raise TaskGraphError("pinned validator returned an invalid QA barrier result")
    return result


def _load(manifest: dict) -> tuple[Path, tuple[RecordView, ...], dict[str, dict]]:
    """安全读全部指定 SHA 后，逐记录调用原 validate/ready/qa-ready；不接受验证旗标。"""
    _object(manifest, {"schema_version", "project_root", "records", "capacity"}, "admission manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise TaskGraphError("admission schema_version must be integer 1")
    root = _absolute(manifest["project_root"], directory=True)
    project_root(root)
    semantic_scope = _git_identity(root, required=False)
    descriptors = manifest["records"]
    if not isinstance(descriptors, list) or not descriptors or len(descriptors) > 128:
        raise TaskGraphError("records must contain 1..128 explicit authoritative records")
    views, sources, identities = [], {}, set()
    directory_modes: dict[tuple[int, int], bool | None] = {}
    total = 0
    for descriptor in descriptors:
        _object(descriptor, {"path", "sha256", "execution_roots"}, "record descriptor")
        path = _absolute(descriptor["path"])
        identity = str(path)
        if identity in identities:
            raise TaskGraphError("duplicate authoritative record source")
        identities.add(identity)
        body = records.read_record(path)
        total += len(body)
        if total > 16 * 1024 * 1024:
            raise TaskGraphError("aggregate record bodies exceed 16MiB")
        if records.digest(body) != _sha(descriptor["sha256"]):
            raise TaskGraphError(f"record fingerprint changed: {path}")
        payload = records.decode(body)
        if not isinstance(payload, dict):
            raise TaskGraphError("authoritative record must be a JSON object")
        if "task" in payload:
            if not isinstance(payload["task"], dict) or payload["task"].get("workflow_level") != "Light":
                raise TaskGraphError("Full handoff packs cannot replace an authoritative graph")
            tasks = [payload["task"]]
        else:
            tasks = payload.get("tasks")
        _query(payload, root, "validate")
        # 原 validate 已核实 tasks/身份/规范/需求/QA/worktree 结构；本层只核实
        # 聚合所需的实际执行位置，绝不把 manifest.execution_roots 变成换根授权。
        roots = descriptor["execution_roots"]
        if not isinstance(roots, dict) or set(roots) != {task["id"] for task in tasks}:
            raise TaskGraphError("execution_roots must exactly cover authoritative task IDs")
        checked_roots, resource_paths = {}, {}
        for task in tasks:
            execution = _absolute(roots[task["id"]], directory=True)
            workspace = task.get("execution_workspace")
            integration = (payload.get("worktree_integrations", {}).get(task["request_id"])
                           if task["task_type"] == "qa" else None)
            # execution_workspace 属于 Writer，QA 的审查树由其原请求集成记录
            # 决定；不得要求 QA 伪造 Writer 字段，也不能借 manifest 改绑根。
            binding = integration or workspace
            expected = _absolute(binding["root"], directory=True) if binding else root
            if execution != expected:
                raise TaskGraphError("execution root differs from original task binding")
            if execution != root and _git_identity(execution) != _git_identity(root):
                raise TaskGraphError("execution worktree does not belong to the actual project")
            resource_paths[task["id"]] = tuple(_resource_identity(execution / owned, directory_modes)
                                                for owned in task.get("owned_paths", ()))
            checked_roots[task["id"]] = str(execution)
        # capacity 属于本次全局投影；原 record 的历史数值不能截断局部候选。
        candidate = copy.deepcopy(payload)
        if "task" not in candidate:
            candidate["capacity"] = len(tasks)
        eligible = set(_query(candidate, root, "ready")["ready"])
        for task in tasks:
            if task["task_type"] != "qa" or task["state"] not in {"DECLARED", "BLOCKED", "READY"}:
                continue
            if "task" not in payload:
                qa_input = copy.deepcopy(payload)
                qa_input["request_id"] = task["request_id"]
                if not _query(qa_input, root, "qa-ready")["qa_ready"]:
                    continue
            qa_candidate = copy.deepcopy(candidate)
            selected = (qa_candidate["task"] if "task" in qa_candidate else next(
                item for item in qa_candidate["tasks"] if item["id"] == task["id"]))
            # 与原 update 的 QA 准入完全同义：仅临时作为 read_only 复用门禁/锁，
            # 发布仍使用原 QA 合同，由原 update 再做一次 request QA barrier。
            selected["task_type"] = "read_only"
            if task["id"] in _query(qa_candidate, root, "ready")["ready"]:
                eligible.add(task["id"])
        known_paths = {item for task in tasks if active(task) for item in task.get("owned_paths", ())}
        known_locks = {item for task in tasks if active(task) for item in task.get("semantic_locks", ())}
        external_paths = tuple(set(payload.get("active_paths", ())) - known_paths)
        views.append(RecordView(identity, descriptor["sha256"], str(root), tuple(tasks), checked_roots,
                                frozenset(eligible), semantic_scope=semantic_scope,
                                external_paths=external_paths,
                                external_semantic_locks=tuple(set(payload.get("active_semantic_locks", ())) - known_locks),
                                resource_paths=resource_paths,
                                external_resources=tuple(_resource_identity(root / owned, directory_modes)
                                                         for owned in external_paths)))
        sources[identity] = payload
    return root, tuple(views), sources


@contextmanager
def _project_lock(root: Path):
    """项目统一 scratch 中的固定目录锁，避免与原记录父目录发布锁相互重入。

    只在 claim/release 分配；不存资源台账。目录永久保留到项目 scratch 的协调清理，
    不在退出时 unlink，避免另一进程打开新 inode 绕过旧锁。持锁仅做机械 helper，
    原生宿主工具、模型等待和用户交互必须位于本临界区外。
    """
    scope = Path(_git_identity(root, required=False))
    info = records.scratch_workspace(scope)
    base = Path(info["project_scratch_root"])
    with records._scratch_base_directory(base) as parent:
        with records._scratch_directory("admission-lock", parent=parent, create=True):
            with directory_lock(base / "admission-lock", "dispatch-admission"):
                yield str(scope)


def _recheck(views: tuple[RecordView, ...]) -> None:
    for record in views:
        if records.digest(records.read_record(Path(record.path))) != record.sha256:
            raise TaskGraphError("record fingerprint changed during admission; no claim may be retried blindly")


def admission(command: str, manifest: dict, target: dict | None = None,
              receipt: dict | None = None, outcome: str | None = None) -> dict:
    """执行 view/claim/release；错误抛 TaskGraphError，CLI 映射为 JSON stderr/退出2。

    claim 成功返回的 receipt 只关联原字节和原任务，不是宿主启动凭据。release 要求
    PM 明确确认 definitely_not_created；unknown 原样保留。释放后重复事件因原 SHA
    或 RUNNING 前提不符而拒绝。非协作手工编辑应暂停；原 CAS 不承诺跨文件事务。
    """
    _object(manifest, {"schema_version", "project_root", "records", "capacity"}, "admission manifest")
    if command not in {"view", "claim", "release"}:
        raise TaskGraphError("unknown admission command")
    if command == "view":
        if target is not None or receipt is not None or outcome is not None:
            raise TaskGraphError("view accepts only manifest")
        _, views, _ = _load(manifest)
        result = select_candidates(views, manifest["capacity"])
        _recheck(views)
        return result
    root = _absolute(manifest.get("project_root"), directory=True)
    project_root(root)
    with _project_lock(root) as locked_scope:
        _, views, sources = _load(manifest)
        if any(view.semantic_scope != locked_scope for view in views):
            raise TaskGraphError("project Git coordination identity changed during admission")
        projection = select_candidates(views, manifest["capacity"])
        if command == "release":
            if target is not None or outcome not in {"definitely_not_created", "unknown"}:
                raise TaskGraphError("release requires receipt and explicit native creation outcome")
            _object(receipt, {"schema_version", "status", "target", "prior_state", "previous_sha256", "claimed_sha256"}, "claim receipt")
            if type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1 or receipt["status"] != "claimed":
                raise TaskGraphError("release requires a v1 claimed receipt")
            _sha(receipt["previous_sha256"])
            _sha(receipt["claimed_sha256"])
            if not isinstance(receipt["prior_state"], str) or receipt["prior_state"] not in {"DECLARED", "BLOCKED", "READY"}:
                raise TaskGraphError("claim receipt has invalid prior_state")
            target = receipt["target"]
        elif receipt is not None or outcome is not None:
            raise TaskGraphError("claim accepts only target")
        _object(target, {"record", "request_id", "task_id"}, "target")
        matches = [(view, task) for view in views for task in view.tasks if task_key(view, task) == target]
        if len(matches) != 1:
            raise TaskGraphError("target must identify exactly one authoritative task")
        view, task = matches[0]
        if command == "claim":
            if target not in projection["candidates"]:
                raise TaskGraphError("target is not an admitted spawn candidate")
            state = "RUNNING"
        else:
            if (view.sha256 != receipt["claimed_sha256"] or task["state"] != "RUNNING"
                    or "agent_ref" in task or task.get("agent_retired")):
                raise TaskGraphError("release requires unchanged, unbound, non-retired RUNNING claim")
            if outcome == "unknown":
                _recheck(views)
                return {"schema_version": 1, "status": "retained", "target": target,
                        "sha256": view.sha256, "reason": "native_creation_unknown; verify before further action"}
            state = receipt["prior_state"]
        _recheck(views)
        patch = {"tasks": {task["id"]: {"set": {"state": state}}}}
        updated = _helper(sources[view.path], root,
                          ["update", "--input", view.path, "--root", str(root), "--patch", "-",
                           "--expect-sha256", view.sha256],
                          json.dumps(patch, ensure_ascii=False).encode("utf-8"))
        if set(updated) != {"updated", "sha256"} or updated.get("updated") is not True:
            raise TaskGraphError("record helper did not publish the state transition; inspect original record")
        _sha(updated["sha256"])
        if command == "claim":
            return {"schema_version": 1, "status": "claimed", "target": target,
                    "prior_state": task["state"], "previous_sha256": view.sha256,
                    "claimed_sha256": updated["sha256"]}
        return {"schema_version": 1, "status": "released", "target": target,
                "sha256": updated["sha256"], "state": state}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("view", "claim", "release"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--record")
    parser.add_argument("--request-id")
    parser.add_argument("--task-id")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--outcome", choices=("definitely_not_created", "unknown"))
    args = parser.parse_args(argv)
    try:
        manifest = records.decode(records.read_record(args.input))
        supplied_target = (args.record, args.request_id, args.task_id)
        if any(value is not None for value in supplied_target) and not all(supplied_target):
            raise TaskGraphError("target requires --record/--request-id/--task-id together")
        target = dict(zip(("record", "request_id", "task_id"), supplied_target)) if all(supplied_target) else None
        receipt = records.decode(records.read_record(args.receipt)) if args.receipt else None
        result = admission(args.command, manifest, target, receipt, args.outcome)
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
