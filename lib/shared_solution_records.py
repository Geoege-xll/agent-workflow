"""显式清单登记的共享方案成员关系。业务状态、正文和批准始终来自各原记录。"""

from __future__ import annotations

from collections import defaultdict
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile

from lib.safe_text import read_file
from lib.solution_confirmation import EXECUTING_OR_DELIVERED, decision_gates
from lib.task_graph import TaskGraphError


def _tasks(value):
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        return []
    tasks = [value["task"]] if isinstance(value.get("task"), dict) else value.get("tasks", [])
    if not isinstance(tasks, list) or any(not isinstance(task, dict) or not isinstance(task.get("id"), str) for task in tasks):
        return []
    return tasks


def decision_keys(task):
    return {(task["request_id"], key): gate for key, gate in decision_gates(task).items()}


def _filename(key):
    # 正文修改后仍使用同一成员关系。请求和 ID 使用数组编码，避免分隔符歧义。
    encoded = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode()
    return ".xy-solution-members-" + hashlib.sha256(encoded).hexdigest() + ".json"


def _private_record_directory(directory):
    # 共享 /tmp 等可被其他用户写入的公共祖先不能提供成员权威，也不能在那里建立登记。
    info = directory.stat()
    return info.st_uid == os.getuid() and not info.st_mode & 0o022


def _read_groups(file, key):
    from lib.task_graph_records import decode
    body = read_file(file)
    if body is None:
        return []
    info = file.lstat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise TaskGraphError(f"unsafe shared solution membership permissions: {file}")
    data = decode(body)
    if (not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("decision") != list(key)
            or not isinstance(data.get("groups"), list)):
        raise TaskGraphError(f"invalid shared solution membership: {file}")
    # 路径必须是清单登记时所在公共目录下的实际记录；篡改会员文件不能越过该目录读取。
    for group in data["groups"]:
        if (not isinstance(group, list) or not 2 <= len(group) <= 128
                or any(not isinstance(name, str) or not Path(name).is_relative_to(file.parent)
                       or ".." in Path(name).parts for name in group)):
            raise TaskGraphError(f"invalid shared solution members: {file}")
    return data["groups"]


def _same_record(path, name):
    if str(path) == name:
        return True
    try:
        return path.samefile(name)
    except FileNotFoundError:
        return False


def members(path, key):
    """只探测输入记录祖先中该请求/事项的固定文件名，无目录枚举或项目发现。"""
    found = set()
    name = _filename(key)
    for directory in path.absolute().parents:
        file = directory / name
        # 不打开任意同目录资料；遇到损坏链接由安全读取器明确拒绝。
        if not file.exists() and not file.is_symlink():
            continue
        if not _private_record_directory(directory):
            # 系统公共临时目录可能出现其他用户的同名文件。曾由本用户登记的文件若
            # 已失去目录保护，则拒绝把它静默降级为未登记的单包。
            if file.lstat().st_uid == os.getuid():
                raise TaskGraphError(f"shared solution membership directory permissions changed: {directory}")
            continue
        for group in _read_groups(file, key):
            if any(_same_record(path, entry) for entry in group):
                found.update(map(Path, group))
    return found


@contextmanager
def _locked_directories(directories):
    from lib.task_graph_records import _publication_lock
    # 和普通 CAS 共用原记录父目录的 inode 锁，去重名称别名，固定顺序且不等待。
    unique = {}
    for directory in directories:
        st = directory.stat()
        unique[st.st_dev, st.st_ino] = directory
    with ExitStack() as stack:
        for _, directory in sorted(unique.items()):
            stack.enter_context(_publication_lock(directory / ".xy-directory-lock-target"))
        yield


def bind(views, selected=None):
    """给同决定的显式成员登记合作边界；一次替换只登记一项完整关系。

    首次登记和扩员都会在所有原记录目录锁内重新检查输入 SHA。成员文件只含路径，
    因此中途失败最多保留已完整登记的事项，不会部分撤回批准或写入 RUNNING。
    """
    from lib.task_graph_records import digest, read_record
    by_key = defaultdict(set)
    for view in views:
        for task in view.tasks:
            for key in decision_keys(task):
                if selected is None or key in selected:
                    by_key[key].add(Path(view.path))
    manifest_paths = {Path(view.path) for view in views}
    count = 0
    for key, paths in sorted(by_key.items()):
        known = set().union(*(members(path, key) for path in paths))
        if any(not any(_same_record(path, str(other)) for other in manifest_paths) for path in known):
            raise TaskGraphError("shared solution requires every registered record in the manifest")
        # 已登记副本可以合法移除本任务的依赖；其原件仍随清单核实，不能让其它
        # 仍采用该决定的任务永久无法领取，也不能通过这次修订悄悄缩小合作边界。
        paths.update(known)
        if len(paths) < 2:
            continue
        directory = Path(os.path.commonpath([path.parent for path in paths]))
        if directory == Path(directory.anchor) or not _private_record_directory(directory):
            raise TaskGraphError("shared solution records require a user-owned common record directory without group/world write access")
        file = directory / _filename(key)
        with _locked_directories({directory, *(path.parent for path in paths)}):
            for view in views:
                if Path(view.path) in paths and digest(read_record(Path(view.path))) != view.sha256:
                    raise TaskGraphError("record fingerprint changed during shared solution binding")
            groups = _read_groups(file, key)
            chosen = sorted(map(str, paths))
            intersecting = [group for group in groups if any(_same_record(path, entry)
                                                            for path in paths for entry in group)]
            if any(not all(any(_same_record(path, name) for path in paths) for name in group)
                   for group in intersecting):
                raise TaskGraphError("shared solution binding cannot omit existing members")
            if intersecting == [chosen]:
                continue
            groups = [group for group in groups if group not in intersecting] + [chosen]
            body = json.dumps({"schema_version": 1, "decision": key, "groups": groups}, ensure_ascii=False).encode()
            fd, raw = tempfile.mkstemp(prefix=".xy-solution-publish-", dir=directory)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(body)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(raw, file)
            finally:
                Path(raw).unlink(missing_ok=True)
            count += 1
    return count


def _peer_facts(path, membership):
    from lib.task_graph_records import decode, read_record
    registered = {peer for peers in membership.values() for peer in peers if not _same_record(path, str(peer))}
    if len(registered) > 128:
        raise TaskGraphError("shared solution record count exceeds the admission limit")
    facts = defaultdict(list)
    total = 0
    for peer in registered:
        affected = {key for key, group in membership.items() if peer in group}
        try:
            if total > 16 * 1024 * 1024:
                raise TaskGraphError("shared solution peer bodies exceed 16MiB")
            body = read_record(peer)
            total += len(body)
            if total > 16 * 1024 * 1024:
                raise TaskGraphError("shared solution peer bodies exceed 16MiB")
            payload = decode(body)
            tasks = _tasks(payload)
            if not tasks or ("task" in payload and tasks[0].get("workflow_level") != "Light"):
                raise TaskGraphError("shared solution requires an authoritative peer")
            if any(key[0] not in {task.get("request_id") for task in tasks} for key in affected):
                raise TaskGraphError("registered record no longer belongs to its original request")
            for task in tasks:
                for key, gate in decision_keys(task).items():
                    if key in affected:
                        facts[key].append((gate, gate in payload.get("approved_gates", []),
                                           task["state"] in EXECUTING_OR_DELIVERED))
        except (ValueError, OSError, KeyError, TypeError):
            # PM 保留的旧成员可能暂时离线或损坏。缺失不能证明批准或已停机；只把真正
            # 引用该成员的事项标成不可消费/不可撤回，其他决定和任务继续按自己的依据运行。
            for key in affected:
                facts[key].append((None, False, True))
    return facts


def _pending(facts, task):
    return any(other != gate or not approved for key, gate in decision_keys(task).items()
               for other, approved, _ in facts.get(key, ()))


def filter_ready(path, tasks, eligible):
    selected = set(eligible)
    chosen = [task for task in tasks if task["id"] in selected and task.get("solution_decisions")]
    if not chosen:
        return list(eligible)
    membership = {}
    unknown = set()
    for key in {key for task in chosen for key in decision_keys(task)}:
        try:
            membership[key] = members(path, key)
        except (ValueError, OSError):
            unknown.add(key)
    facts = _peer_facts(path, membership)
    unavailable = {task["id"] for task in chosen if unknown.intersection(decision_keys(task)) or _pending(facts, task)}
    return [task_id for task_id in eligible if task_id not in unavailable]


@contextmanager
def publication(path, before, after):
    """登记/发布共享原目录锁。先定位锁集合，再在锁内重查，拒绝预读后出现的成员。"""
    from lib.task_graph_records import decode
    try:
        old, new = decode(before) if before else {}, decode(after)
    except ValueError:
        old = new = {}
    previous_tasks = {task["id"]: task for task in _tasks(old)}
    old_approvals = old.get("approved_gates", []) if previous_tasks else []
    new_tasks = _tasks(new)
    new_approvals = new.get("approved_gates", []) if new_tasks else []
    withdrawn = set()
    transitions = []
    keys = set()
    for task in new_tasks:
        previous = previous_tasks.get(task["id"], {})
        was, now = decision_keys(previous), decision_keys(task)
        for key in was.keys() | now.keys():
            old_gate, new_gate = was.get(key), now.get(key)
            if old_gate != new_gate or (old_gate in old_approvals) != (new_gate in new_approvals):
                keys.add(key)
                if old_gate and (old_gate != new_gate or old_gate in old_approvals and old_gate not in new_approvals):
                    withdrawn.add(key)
        if (now and task.get("state") in EXECUTING_OR_DELIVERED and
                (previous.get("state") != task["state"] or was != now or previous.get("agent_ref") != task.get("agent_ref"))):
            keys.update(now)
            transitions.append(task)
    # 不修改/不消费共享决定的更新只持本记录的旧锁。即使同图另有离线的共享事项，
    # 一个独立 Writer 的领取也不因此依赖邻居的文件或目录。
    mapping = {key: members(path, key) for key in keys}
    peers = {peer for group in mapping.values() for peer in group}
    with _locked_directories({path.parent, *(peer.parent for peer in peers)}):
        if mapping != {key: members(path, key) for key in keys}:
            raise TaskGraphError("shared solution membership changed during publication; refresh and retry")
        if peers:
            facts = _peer_facts(path, mapping)
            if any(_pending(facts, task) for task in transitions):
                raise TaskGraphError("writer requires current shared solution approval in every registered record")
            if any(active for key in withdrawn for _, _, active in facts.get(key, ())):
                raise TaskGraphError("shared solution revision or revocation requires coordination with running or delivered writers")
        yield
