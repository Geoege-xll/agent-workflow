"""真实 Win32 文件系统闭包；可移植测试与本模块通过证据分别记录。"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib import windows_fs as fs


PACK = Path(__file__).resolve().parents[1]


class CloseObservedStream:
    """只观察真实流正常退出后的时点，保留生产同一变量的完整文件接口。

    write/flush/fileno 等操作全部交给真实流；关闭责任仍只有底层流的
    __exit__。关闭或写入失败时直接传播原异常，不注入额外竞态；正常关闭
    完成后才执行观察器，观察器自身的失败同样传播，不伪造成功或再次清理。
    """

    def __init__(self, stream, after_close):
        self.stream = stream
        self.after_close = after_close

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        result = self.stream.__exit__(exc_type, exc, traceback)
        if exc_type is None:
            self.after_close()
        return result


def native_policy_observation(policy):
    """测试日志只公开控制位/ACE mask 与摘要，不输出任何 SID 正文。"""
    acl, entries, offset = policy.acl_bytes, [], 8
    count = int.from_bytes(acl[4:6], "little")
    for _ in range(count):
        size = int.from_bytes(acl[offset + 2:offset + 4], "little")
        if size < 8 or offset + size > len(acl):
            raise ValueError("native observation encountered an invalid ACE bound")
        ace = acl[offset:offset + size]
        item = {"type": ace[0], "flags": ace[1], "mask": int.from_bytes(ace[4:8], "little"),
                "ace_sha256": hashlib.sha256(ace).hexdigest()}
        if ace[0] in {0, 1}:
            item["sid_sha256"] = hashlib.sha256(ace[8:]).hexdigest()
        entries.append(item)
        offset += size
    return {"control": policy.control, "ace_count": count, "aces": entries,
            "owner_sid_sha256": hashlib.sha256(policy.owner).hexdigest(), "security_sha256": policy.fingerprint}


def _native_clone_observation(handle, *, label):
    """只读同一真实 HANDLE 的权限、SDDL 与元数据，不改变 ACL 或文件游标。

    SDDL 由当前 GetSecurityInfo 返回的 SD 转换，绝不写死预期权限。动态 SID
    仅在显示串中稳定标记，原 SDDL/ACL/有序 ACE 的摘要仍来自未改写原字节，
    因而不同主体、ACE 顺序和继承 flags 都不会被显示脱敏误当成相等。
    """
    before, security = fs._metadata(handle)
    information, basic = fs._information(handle), fs._basic_information(handle)
    api = fs._api()
    convert = api.security.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.restype = fs.BOOL
    convert.argtypes = [fs.HANDLE, fs.DWORD, fs.DWORD, ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(fs.DWORD)]
    with fs._security_policy(handle) as policy:
        pointer = ctypes.c_wchar_p()
        try:
            fs._check(convert(policy.descriptor, 1, 5, ctypes.byref(pointer), None))
            if pointer.value is None:
                raise ValueError("native SDDL conversion returned no descriptor")
            sddl = pointer.value
        finally:
            if pointer:
                api.kernel.LocalFree(ctypes.cast(pointer, fs.HANDLE))
        result = native_policy_observation(policy)
        result.update(label=label, identity=list(before), file_attributes=int(information.attributes),
                      basic={name: int(getattr(basic, name)) for name in ("created", "accessed", "modified", "changed", "attributes")},
                      dacl_key_sha256=hashlib.sha256(policy.dacl_key).hexdigest(),
                      acl_sha256=hashlib.sha256(policy.acl_bytes).hexdigest(),
                      sddl_sha256=hashlib.sha256(sddl.encode("utf-8")).hexdigest(),
                      sddl_sid_marked=re.sub(r"S-\d+(?:-\d+)+", lambda match:
                                             "<SID-SHA256:" + hashlib.sha256(match.group().encode()).hexdigest() + ">", sddl),
                      control_flags={name: bool(policy.control & mask) for name, mask in
                                     (("PROTECTED", 0x1000), ("AUTO_INHERITED", 0x400), ("AUTO_REQ", 0x100))})
    after, after_security = fs._metadata(handle)
    if (before != after or security != after_security or result["security_sha256"] != security
            or fs._information(handle).attributes != information.attributes):
        raise ValueError("native clone observation changed while reading its handle: " + label)
    return result


def native_skill_observation(path, skill_name):
    """沿真实 no-follow 句柄观测 Skill 的七标量、raw basic 属性及安全事实。"""
    with fs.Directory(Path(path).parent):
        handle = fs._open_skill_handle(path)
        try:
            node = fs._opened_snapshot(handle, max_bytes=fs._LIMIT, skill_name=skill_name)
            basic = fs._basic_information(handle)
            with fs._security_policy(handle) as policy:
                result = native_policy_observation(policy)
            result.update(identity=list(node["identity"]), mode=node["mode"],
                          snapshot_security_sha256=node["security"],
                          payload_sha256=hashlib.sha256(node["payload"]).hexdigest(),
                          file_attributes=int(fs._information(handle).attributes),
                          basic={name: int(getattr(basic, name)) for name in ("created", "accessed", "modified", "changed", "attributes")})
            return result
        finally:
            fs._close(handle)


@unittest.skipUnless(os.name == "nt", "requires actual native Windows local NTFS")
class WindowsSafePrimitivesNativeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-native-fs-")
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.parent = fs.secure_os.open(self.root, fs.DIRECTORY | fs.NOFOLLOW)
        self.addCleanup(fs.secure_os.close, self.parent)

    def private_file(self, name, body=b"owned"):
        descriptor = fs.secure_os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR,
                                       0o600, dir_fd=self.parent)
        try:
            os.write(descriptor, body)
            fs.secure_os.fsync(descriptor)
        finally:
            fs.secure_os.close(descriptor)
        return self.root / name

    def add_world_read_dacl(self, path):
        """只改自有夹具的真实 DACL，用独立权限事实制造源/目的端变化。"""
        handle = fs._open_handle(path, 0x60080)
        descriptor = fs.HANDLE()
        try:
            api = fs._api()
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(
                handle, 1, 0x80000004, None, None, fs._dacl(descriptor), None))
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)

    def test_same_parent_external_config_permission_copy_preserves_exact_security(self):
        """最小真实证明：默认外部配置与同父 stage 的 DACL 克隆必须精确保留。"""
        api = fs._api()
        original_copy, original_set = fs._copy_permissions, api.security.SetSecurityInfo
        points = {}
        def emit(event, value):
            # 每个时点立即输出并 flush；原生调用/精确断言失败后，stdout 与
            # unittest 的原始 stderr 都由诊断 job 保留，报告生成本身不算通过。
            print("NATIVE_SAME_PARENT_ACL_TRACE " + json.dumps({"event": event, "value": value}, sort_keys=True), flush=True)
        def record(label, observe, original_error=None):
            try:
                value = observe()
                emit(label, value)
                return value
            except BaseException as observation_error:
                emit(label + ".observation_error", {"type": type(observation_error).__name__, "message": str(observation_error)})
                if original_error is None:
                    raise
                # 诊断读取也可能失败：保留原复制异常及其 traceback，不用日志
                # 采样失败覆盖第一故障；附注仍明确暴露缺失的诊断证据。
                original_error.add_note(label + " observation failed: " + repr(observation_error))
                return None
        workspace = fs.secure_os._directories[self.parent]
        record("T0.workspace-before-project", lambda: _native_clone_observation(workspace.handle, label="workspace"))
        project = self.root / "external-project"
        project.mkdir()
        host = project / ".codex"
        host.mkdir()
        source, stage_name = host / "config.toml", ".agent-workflow-central-" + "f" * 32 + "-26.stage"
        target = host / stage_name
        parent = fs.secure_os.open(host, fs.DIRECTORY | fs.NOFOLLOW)
        try:
            directory = fs.secure_os._directories[parent]
            with fs.Directory(project) as root:
                def file_observation(name):
                    try:
                        handle = fs._open_handle(directory.child(name), fs.READ, sharing=fs.SHARE_READ)
                    except FileNotFoundError:
                        return None
                    try:
                        value = _native_clone_observation(handle, label=name)
                        node = fs._opened_snapshot(handle, max_bytes=fs._LIMIT)
                        self.assertEqual(value["identity"], list(node["identity"]))
                        self.assertEqual(value["security_sha256"], node["security"])
                        value["payload_sha256"] = hashlib.sha256(node["payload"]).hexdigest()
                        return value
                    finally:
                        fs._close(handle)
                def phase():
                    return {"workspace": _native_clone_observation(workspace.handle, label="workspace"),
                            "root": _native_clone_observation(root.handle, label="root"),
                            "parent": _native_clone_observation(directory.handle, label="parent"),
                            "source": file_observation(source.name), "target": file_observation(stage_name)}
                points["T0"] = record("T0.before-source", phase)
                # 与失败准备步骤一致：root/.codex/config 完全走 stdlib 默认
                # 创建，不提前设私有 DACL，也不主动重写任何祖先的继承策略。
                source.write_bytes(b"# existing user config\n")
                points["T1"] = record("T1.external-source-created", phase)
                source_mode = stat.S_IMODE(points["T1"]["source"]["identity"][2])
                descriptor = fs.secure_os.open(stage_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | fs.NOFOLLOW,
                                                0o600, dir_fd=parent)
                with fs.secure_os.fdopen(descriptor, "wb") as stream:
                    stream.write(b"# existing user config\n# approved staged update\n")
                    stream.flush()
                    fs.secure_os.fchmod(stream.fileno(), source_mode)
                    fs.secure_os.fsync(stream.fileno())
                points["T2"] = record("T2.private-stage-written-and-closed", phase)
                def traced_set(*args):
                    emit("SetSecurityInfo.request", {"object_type": int(args[1]), "security_information": int(args[2])})
                    # 原始 ctypes 函数执行真实系统调用；只记录实际返回码，
                    # 不改参数、不模拟成功、不补一次不同 flags 的重试。
                    result = original_set(*args)
                    emit("SetSecurityInfo.result", {"return_code": int(result)})
                    return result
                def traced_copy(source_handle, target_handle, **kwargs):
                    record("copy.same-handle.before", lambda: {
                        "source": _native_clone_observation(source_handle, label="copy-source"),
                        "target": _native_clone_observation(target_handle, label="copy-target"),
                        "parent": _native_clone_observation(directory.handle, label="copy-parent")})
                    error = None
                    try:
                        return original_copy(source_handle, target_handle, **kwargs)
                    except BaseException as exc:
                        error = exc
                        emit("copy.original-error", {"type": type(exc).__name__, "message": str(exc)})
                        raise
                    finally:
                        record("copy.same-handle.after", lambda: {
                            "source": _native_clone_observation(source_handle, label="copy-source"),
                            "target": _native_clone_observation(target_handle, label="copy-target"),
                            "parent": _native_clone_observation(directory.handle, label="copy-parent")}, error)
                failure = None
                try:
                    with patch.object(fs, "_copy_permissions", new=traced_copy), \
                            patch.object(api.security, "SetSecurityInfo", new=traced_set):
                        fs.copy_permissions(source, target)
                except BaseException as exc:
                    failure = exc
                finally:
                    points["T3"] = record("T3.after-real-copy-including-failure", phase, failure)
                    emit("copy.outcome", {"original_error": type(failure).__name__ if failure else None})
                try:
                    self.assertIsNotNone(points["T3"], "失败后的真实权限证据不可缺失")
                    source_fields = ("identity", "file_attributes", "security_sha256", "control", "dacl_key_sha256",
                                     "owner_sid_sha256", "aces", "payload_sha256")
                    for point in ("T2", "T3"):
                        for key in source_fields:
                            self.assertEqual(points["T1"]["source"][key], points[point]["source"][key], "source." + key)
                    for point in ("T1", "T2", "T3"):
                        for label in ("workspace", "root", "parent"):
                            # 自己创建 config/stage 必然可能更新目录时间；记录
                            # 全部原值，但只以目录原身份和真实安全事实判稳定。
                            self.assertEqual(points["T0"][label]["identity"][:2], points[point][label]["identity"][:2])
                            self.assertEqual(points["T0"][label]["security_sha256"], points[point][label]["security_sha256"])
                    before, after = points["T2"]["target"], points["T3"]["target"]
                    self.assertEqual(before["identity"][:2], after["identity"][:2])
                    self.assertEqual(before["identity"][3:6], after["identity"][3:6])
                    for key in ("payload_sha256", "file_attributes", "owner_sid_sha256"):
                        self.assertEqual(before[key], after[key], "stage." + key)
                except BaseException as invariant_error:
                    if failure is not None:
                        failure.add_note("post-copy preservation assertion failed: " + repr(invariant_error))
                        raise failure from invariant_error
                    raise
                if failure is not None:
                    raise failure
                # 不能把“生成了诊断日志”当作复制成功；正常返回也必须逐项
                # 证明有序 ACE 原字节、控制位与 DACL 语义摘要完全等于原源。
                for key in ("control", "dacl_key_sha256", "aces"):
                    self.assertEqual(points["T1"]["source"][key], after[key], "exact-clone." + key)
        finally:
            fs.secure_os.close(parent)

    def test_same_parent_external_config_creation_security_is_exact_before_write(self):
        """只验证 initial SD 的真实可行性；未通过精确权限证明前不写批准正文。"""
        import msvcrt
        def emit(event, value):
            print("NATIVE_INITIAL_SD_TRACE " + json.dumps({"event": event, "value": value}, sort_keys=True), flush=True)
        project = self.root / "initial-sd-project"
        project.mkdir()
        host = project / ".codex"
        host.mkdir()
        source, target = host / "config.toml", host / (".agent-workflow-central-" + "e" * 32 + "-26.stage")
        source.write_bytes(b"# existing user config\n")
        approved = b"# existing user config\n# approved initial-SD stage\n"
        parent = fs.secure_os.open(host, fs.DIRECTORY | fs.NOFOLLOW)
        source_handle = None
        try:
            directory = fs.secure_os._directories[parent]
            source_handle = fs._open_handle(source, fs.READ, sharing=fs.SHARE_READ)
            source_snapshot = fs._opened_snapshot(source_handle, max_bytes=fs._LIMIT)
            source_before = _native_clone_observation(source_handle, label="initial-source")
            parent_before = _native_clone_observation(directory.handle, label="initial-parent")
            self.assertEqual(list(source_snapshot["identity"]), source_before["identity"])
            self.assertEqual(source_snapshot["security"], source_before["security_sha256"])
            emit("before-create", {"source": source_before, "parent": parent_before,
                                   "source_payload_sha256": hashlib.sha256(source_snapshot["payload"]).hexdigest()})
            raw_handle, descriptor, failure = None, None, None
            try:
                with fs._security_policy(source_handle) as policy:
                    # 只借用固定源 HANDLE 当前的 owner+DACL/control 描述符；
                    # sharing 不阻止 WRITE_DAC，所以在实际创建前仍精确核源。
                    self.assertEqual((source_snapshot["identity"], source_snapshot["security"]), fs._metadata(source_handle))
                    self.assertEqual(source_snapshot["security"], policy.fingerprint)
                    attributes = fs._SecurityAttributes(ctypes.sizeof(fs._SecurityAttributes), policy.descriptor, 0)
                    emit("CreateFileW.request", {"access": fs.READ | fs.WRITE, "sharing": 0, "disposition": 1,
                                                 "flags": fs.OPEN_REPARSE_POINT | fs.BACKUP_SEMANTICS,
                                                 "inherit_handle": False, "source_security": policy.fingerprint})
                    # 复用真实 no-follow/单链接检查原语。它在 exclusive=True 时
                    # 走 CREATE_NEW，hTemplateFile=NULL，不做 restrict/SetSI。
                    raw_handle = fs._open_handle(target, fs.READ | fs.WRITE, create=True, exclusive=True,
                                                  security=ctypes.byref(attributes), sharing=0)
                    emit("CreateFileW.returned", {"success": True})
                empty = _native_clone_observation(raw_handle, label="initial-empty-stage")
                emit("created-same-handle-empty", empty)
                self.assertTrue(stat.S_ISREG(empty["identity"][2]))
                self.assertEqual(1, empty["identity"][3])
                self.assertEqual(0, empty["identity"][4])
                self.assertEqual(source_snapshot["mode"], stat.S_IMODE(empty["identity"][2]))
                self.assertEqual(source_before["file_attributes"], empty["file_attributes"])
                for key in ("owner_sid_sha256", "control", "dacl_key_sha256", "aces", "security_sha256"):
                    self.assertEqual(source_before[key], empty[key], "initial-SD." + key)
                # CRT 接管原 HANDLE 后仅由真实流关闭；不 dup、不再调用原生
                # CloseHandle，也不在关闭前重开 stage 取得另一份“当前归属”。
                descriptor = msvcrt.open_osfhandle(raw_handle, os.O_RDWR | os.O_BINARY | os.O_NOINHERIT)
                raw_handle = None
                stream = os.fdopen(descriptor, "w+b")
                descriptor = None
                with stream:
                    owned_handle = msvcrt.get_osfhandle(stream.fileno())
                    self.assertEqual(8, stream.write(approved[:8]))
                    stream.flush()
                    # 刻意在只有部分正文且尚未 seal 时发起真实叶子重开，
                    # 只接受共享冲突32；普通权限拒绝5不能冒充 share0 保护。
                    for label, access in (("READ", fs.READ), ("WRITE", fs.WRITE), ("DELETE", fs.DELETE)):
                        try:
                            extra = fs._open_handle(target, access, sharing=fs.SHARE_READ | fs.SHARE_WRITE | fs.SHARE_DELETE)
                        except OSError as exc:
                            emit("partial-stage-reopen", {"access": label, "winerror": exc.winerror})
                            self.assertEqual(32, exc.winerror, "必须实际命中 ERROR_SHARING_VIOLATION")
                        else:
                            fs._close(extra)
                            self.fail("share0 未拒绝部分 stage 的 " + label + " 重开")
                    self.assertEqual(len(approved) - 8, stream.write(approved[8:]))
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.seek(0)
                    self.assertEqual(approved, stream.read())
                    sealed = _native_clone_observation(owned_handle, label="initial-sealed-stage")
                    emit("sealed-same-handle-before-close", {**sealed, "payload_sha256": hashlib.sha256(approved).hexdigest()})
                    self.assertEqual(empty["identity"][:4], sealed["identity"][:4])
                    self.assertEqual(len(approved), sealed["identity"][4])
                    self.assertEqual(empty["file_attributes"], sealed["file_attributes"])
                    self.assertEqual(source_snapshot["security"], sealed["security_sha256"])
                # 关闭前已固定 creator 身份/批准正文/精确安全事实；首读只验证
                # 这些事实，绝不把新路径状态直接追认为本轮 stage。
                closed_handle = fs._open_handle(target, fs.READ, sharing=fs.SHARE_READ)
                try:
                    closed = _native_clone_observation(closed_handle, label="initial-closed-stage")
                    actual = fs._opened_snapshot(closed_handle, max_bytes=fs._LIMIT)
                    emit("closed-first-read", {**closed, "payload_sha256": hashlib.sha256(actual["payload"]).hexdigest()})
                    self.assertEqual(list(actual["identity"]), closed["identity"])
                    self.assertEqual(approved, actual["payload"])
                    self.assertEqual(sealed["identity"][:5], closed["identity"][:5])
                    # 沿既有关闭合同只容许 LastWriteTime 结算，ctime 不豁免。
                    self.assertEqual(sealed["identity"][6:], closed["identity"][6:])
                    self.assertEqual(source_snapshot["mode"], actual["mode"])
                    self.assertEqual(source_snapshot["security"], actual["security"])
                    self.assertEqual(empty["file_attributes"], closed["file_attributes"])
                    for key in ("owner_sid_sha256", "control", "dacl_key_sha256", "aces", "security_sha256"):
                        self.assertEqual(source_before[key], closed[key], "closed-SD." + key)
                finally:
                    fs._close(closed_handle)
            except BaseException as exc:
                failure = exc
                emit("original-error", {"type": type(exc).__name__, "winerror": getattr(exc, "winerror", None), "message": str(exc)})
                raise
            finally:
                try:
                    source_after = _native_clone_observation(source_handle, label="final-source")
                    parent_after = _native_clone_observation(directory.handle, label="final-parent")
                    emit("finally-source-parent", {"source": source_after, "parent": parent_after})
                    self.assertEqual(source_snapshot, fs.node_snapshot(parent, source.name))
                    self.assertEqual((source_snapshot["identity"], source_snapshot["security"]), fs._metadata(source_handle))
                    # 自己创建子文件改变目录时间合法；原目录实体与完整安全
                    # 摘要必须保持，不能把自己的 mtime 更新误判为外来竞态。
                    self.assertEqual(parent_before["identity"][:2], parent_after["identity"][:2])
                    self.assertEqual(parent_before["security_sha256"], parent_after["security_sha256"])
                except BaseException as observation_error:
                    if failure is None:
                        raise
                    failure.add_note("final source/parent proof failed: " + repr(observation_error))
                    emit("finally-observation-error", {"type": type(observation_error).__name__, "message": str(observation_error)})
                finally:
                    # fdopen 失败前仍归当前栈；成功后流已负责关闭，避免双重
                    # CloseHandle 误关后来复用的对象。创建失败不认领同名路径。
                    if descriptor is not None:
                        os.close(descriptor)
                    if raw_handle is not None:
                        fs._close(raw_handle)
        finally:
            if source_handle is not None:
                fs._close(source_handle)
            fs.secure_os.close(parent)

    def test_anchored_state_stage_close_races_preserve_foreign_nodes(self):
        """真实 write_state 在写句柄关闭处遭遇改写/换 inode/ACL 源变化均保全现场。"""
        from manager import state_files
        approved = b"APPROVED"
        for existing, race in ((False, "normal"), (True, "normal"),
                               (False, "same-inode-content"), (True, "same-inode-content"),
                               (False, "same-content-replacement"), (True, "same-content-replacement"),
                               (True, "acl-source")):
            with self.subTest(existing=existing, race=race):
                state = self.root / (race + ("-existing" if existing else "-missing"))
                state.mkdir()
                if existing:
                    state_files.write_state(state, "control.json", b"OLD")
                parent = fs.secure_os.open(state, fs.DIRECTORY | fs.NOFOLLOW)
                before = fs.node_snapshot(parent, "control.json")
                captured = {}
                native_fdopen = fs.secure_os.fdopen
                def inject_after_close():
                    stages = list(state.glob(".workflow-models-*.tmp"))
                    self.assertEqual(1, len(stages))
                    stage = stages[0]
                    captured["name"] = stage.name
                    captured["created"] = fs.node_snapshot(parent, stage.name)
                    if race == "same-inode-content":
                        stage.write_bytes(b"UNAPPROVED")
                    elif race == "same-content-replacement":
                        stage.rename(state / "owned-created-stage")
                        replacement = fs.secure_os.open(stage, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                        try:
                            os.write(replacement, approved)
                            fs.secure_os.fsync(replacement)
                        finally:
                            fs.secure_os.close(replacement)
                    elif race == "acl-source":
                        self.add_world_read_dacl(state / "control.json")
                    captured["stage"] = fs.node_snapshot(parent, stage.name)
                    captured["attributes"] = fs.secure_os.stat(stage).st_file_attributes
                    captured["source"] = fs.node_snapshot(parent, "control.json")
                def close_then_race(descriptor, *args, **kwargs):
                    # 生产先 stream=fdopen，再 with stream: 并继续用 stream.write；
                    # 因此必须透明代理真实文件接口，不能仅返回 contextmanager。
                    # 创建/写入/关闭/快照/移动/删除仍全部走实际 Win32。
                    return CloseObservedStream(native_fdopen(descriptor, *args, **kwargs), inject_after_close)
                try:
                    with patch.object(fs.secure_os, "fdopen", side_effect=close_then_race):
                        if race == "normal":
                            state_files.write_state(state, "control.json", approved)
                        else:
                            with self.assertRaises(ValueError):
                                state_files.write_state(state, "control.json", approved)
                    current = fs.node_snapshot(parent, "control.json")
                    if race == "normal":
                        self.assertEqual(approved, current["payload"])
                        self.assertEqual(captured["created"]["identity"][:6], current["identity"][:6])
                        self.assertEqual(captured["created"]["security"], current["security"])
                        self.assertIsNone(fs.node_snapshot(parent, captured["name"]))
                    elif race == "acl-source":
                        self.assertEqual(captured["source"], current)
                        self.assertEqual(before["payload"], current["payload"])
                        self.assertNotEqual(before["security"], current["security"])
                        self.assertIsNone(fs.node_snapshot(parent, captured["name"]), "本轮仍自有的 stage 可以条件清理")
                    else:
                        self.assertEqual(before, current)
                        self.assertEqual(captured["stage"], fs.node_snapshot(parent, captured["name"]))
                        self.assertEqual(captured["attributes"], fs.secure_os.stat(state / captured["name"]).st_file_attributes)
                        if race == "same-inode-content":
                            self.assertEqual(captured["created"]["identity"][:2], captured["stage"]["identity"][:2])
                            self.assertEqual(b"UNAPPROVED", captured["stage"]["payload"])
                        else:
                            self.assertNotEqual(captured["created"]["identity"][:2], captured["stage"]["identity"][:2])
                            self.assertEqual(approved, captured["stage"]["payload"])
                    print("NATIVE_ANCHORED_STAGE " + json.dumps(
                        {"existing": existing, "race": race, "created_identity": captured["created"]["identity"],
                         "observed_identity": captured["stage"]["identity"], "security": captured["stage"]["security"],
                         "attributes": captured["attributes"], "foreign_preserved": race not in {"normal", "acl-source"}},
                        sort_keys=True), flush=True)
                finally:
                    fs.secure_os.close(parent)

    def test_conditional_permission_copy_preserves_original_stage_and_rejects_stale_source(self):
        """实际 DACL 变换保留 stage inode/正文/属性，并在原源变化时拒绝任何复制。"""
        source, target = self.private_file("conditional-source"), self.private_file("conditional-stage", b"APPROVED")
        self.add_world_read_dacl(source)
        expected_source = fs.node_snapshot(self.parent, source.name)
        expected_target = fs.node_snapshot(self.parent, target.name)
        attributes = fs.secure_os.stat(target).st_file_attributes
        result = fs.copy_permissions_if_unchanged(source, target, expected_source=expected_source,
                                                  expected_destination=expected_target)
        self.assertEqual(result, fs.node_snapshot(self.parent, target.name))
        self.assertEqual(expected_source, fs.node_snapshot(self.parent, source.name))
        self.assertEqual(expected_target["payload"], result["payload"])
        self.assertEqual(expected_target["identity"][:2], result["identity"][:2])
        self.assertEqual(expected_target["identity"][3:6], result["identity"][3:6])
        self.assertEqual(attributes, fs.secure_os.stat(target).st_file_attributes)
        self.assertNotEqual(expected_target["security"], result["security"])
        old, new = fs._open_handle(source, fs.READ), fs._open_handle(target, fs.READ)
        try:
            with fs._security_policy(old) as source_policy, fs._security_policy(new) as target_policy:
                self.assertEqual(source_policy.dacl_key, target_policy.dacl_key)
                self.assertEqual(source_policy.owner, target_policy.owner)
        finally:
            fs._close(new)
            fs._close(old)
        stale_source = self.private_file("stale-source")
        stale_expected = fs.node_snapshot(self.parent, stale_source.name)
        self.add_world_read_dacl(stale_source)
        current_source = fs.node_snapshot(self.parent, stale_source.name)
        with self.assertRaises(ValueError):
            fs.copy_permissions_if_unchanged(stale_source, target, expected_source=stale_expected,
                                             expected_destination=result)
        self.assertEqual(current_source, fs.node_snapshot(self.parent, stale_source.name))
        self.assertEqual(result, fs.node_snapshot(self.parent, target.name))
        print("NATIVE_CONDITIONAL_PERMISSION_COPY: exact DACL, original identity/body/attributes and stale-source preservation", flush=True)

    def test_independent_embedded_reader_real_read_hardlink_and_live_writer(self):
        from lib.hosts.claude_instructions import read_file as shared_read
        path = self.private_file("fixture", "中文 fixture".encode())
        namespace = {}
        exec(compile(fs.bootstrap_reader_source(), "<trusted-reader>", "exec"), namespace)
        read = namespace["read_initial_regular"]
        self.assertEqual(read(path), path.read_bytes())
        self.assertEqual(shared_read(path), path.read_bytes())
        self.assertIsNone(shared_read(self.root / "missing"))
        with self.assertRaises(ValueError):
            shared_read(self.root)
        with path.open("r+b"), self.assertRaises(OSError):
            read(path)
        alias = self.root / "alias"
        os.link(path, alias)
        for target in (path, alias):
            with self.subTest(target=target), self.assertRaises(ValueError):
                read(target)
            with self.subTest(shared_consumer=target), self.assertRaises(ValueError):
                shared_read(target)

    def test_managed_skill_stage_publication_preserves_frozen_witness(self):
        """只定位真实 staged→目标父目录边界；完整核心安装仍由组合方法验收。"""
        core = self.root / "runtimes" / ("a" * 64) / "core"
        target = core / "platforms/shared/skills/grill-me"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_bytes(b"owned backend target; not a full imported core")
        def target_permissions():
            # 不跟随链接取证明，而是分别锚定真实 core 目录和普通 SKILL.md。
            # 三个时点均保完整 owner/control/有序 ACE 摘要，避免仅看 mask
            # 相同而漏掉 link 权限写入意外传播给 target 的副作用。
            result = {}
            with fs.Directory(target) as directory:
                with fs._security_policy(directory.handle) as policy:
                    result["directory"] = native_policy_observation(policy)
                handle = fs._open_handle(target / "SKILL.md", fs.READ_CONTROL | 0x80)
                try:
                    with fs._security_policy(handle) as policy:
                        result["skill_file"] = native_policy_observation(policy)
                finally:
                    fs._close(handle)
            return result
        target_before = target_permissions()
        print("NATIVE_SKILL_TARGET_BEFORE " + json.dumps(target_before, sort_keys=True), flush=True)
        destination = self.root / "project/.agents/skills"
        destination.mkdir(parents=True)
        parent = fs.secure_os.open(destination, fs.DIRECTORY | fs.NOFOLLOW)
        stage_name = ".agent-workflow-central-" + "e" * 32 + "-0.stage"
        stage = None
        try:
            fs.secure_os.mkdir(stage_name, 0o700, dir_fd=parent)
            stage = fs.secure_os.open(stage_name, fs.DIRECTORY | fs.NOFOLLOW, dir_fd=parent)
            policies = {}
            for label, descriptor in (("stage_parent", stage), ("destination_parent", parent)):
                with fs._security_policy(fs.secure_os._directories[descriptor].handle) as policy:
                    policies[label] = native_policy_observation(policy)
            print("NATIVE_SKILL_STAGE_PARENTS " + json.dumps(policies, sort_keys=True), flush=True)
            fs.create_skill_symlink(stage, "grill-me", target, core_root=core)
            expected = fs.read_skill_symlink(stage, "grill-me", skill_name="grill-me")
            before = {"frozen": {"identity": expected["identity"], "mode": expected["mode"], "security": expected["security"]},
                      "handle": native_skill_observation(destination / stage_name / "grill-me", "grill-me")}
            print("NATIVE_SKILL_STAGE_BEFORE " + json.dumps(before, sort_keys=True), flush=True)
            target_created = target_permissions()
            print("NATIVE_SKILL_TARGET_CREATED " + json.dumps(target_created, sort_keys=True), flush=True)
            self.assertEqual(target_before, target_created)
            self.assertEqual(before["handle"]["owner_sid_sha256"], hashlib.sha256(fs._sid_bytes(fs.current_sid())).hexdigest())
            self.assertTrue(before["handle"]["control"] & 0x1000)
            self.assertEqual(before["handle"]["ace_count"], 2)
            self.assertEqual([ace["flags"] for ace in before["handle"]["aces"]], [0, 0])
            handle = fs._open_skill_handle(destination / stage_name / "grill-me")
            try:
                with fs._security_policy(handle) as policy:
                    self.assertTrue(fs._policy_is_private(policy))
            finally:
                fs._close(handle)
            fs.move_skill_symlink("grill-me", "grill-me", src_dir_fd=stage, dst_dir_fd=parent,
                                  skill_name="grill-me", expected=expected)
            actual = fs.read_skill_symlink(parent, "grill-me", skill_name="grill-me")
            after = {"frozen": {"identity": actual["identity"], "mode": actual["mode"], "security": actual["security"]},
                     "handle": native_skill_observation(destination / "grill-me", "grill-me")}
            print("NATIVE_SKILL_STAGE_AFTER " + json.dumps(after, sort_keys=True), flush=True)
            target_moved = target_permissions()
            print("NATIVE_SKILL_TARGET_MOVED " + json.dumps(target_moved, sort_keys=True), flush=True)
            self.assertEqual(target_before, target_moved)
            # 所有事实已即时落日志，随后仍核冻结守卫；不把当前实际值追认成
            # 新授权，也不对 ACL/mode/metadata 归零来取得一个表面的 PASS。
            self.assertEqual(expected["payload"], actual["payload"])
            self.assertEqual(expected["identity"][:6], actual["identity"][:6])
            self.assertEqual(expected["mode"], actual["mode"])
            self.assertEqual(expected["security"], actual["security"])
        finally:
            if stage is not None:
                fs.secure_os.close(stage)
            fs.secure_os.close(parent)

    def test_exact_dacl_copy_is_idempotent_and_private_state_republishes(self):
        """同策略真实复制不重写权限，并消费实际中央私有记录二次发布。"""
        from manager import state_files
        source, target = self.private_file("copy-source"), self.private_file("copy-target", b"target")
        before_source = fs.node_snapshot(self.parent, source.name)
        before_target = fs.node_snapshot(self.parent, target.name)
        self.assertEqual(before_source["security"], before_target["security"])
        for _ in range(2):
            fs.copy_permissions(source, target)
            self.assertEqual(before_source, fs.node_snapshot(self.parent, source.name))
            self.assertEqual(before_target, fs.node_snapshot(self.parent, target.name))
        fs.secure_os.mkdir("owned-state", 0o700, dir_fd=self.parent)
        state = self.root / "owned-state"
        state_files.write_state(state, "control.json", b'{"phase":"prepared"}\n')
        descriptor = fs.secure_os.open(state, fs.DIRECTORY | fs.NOFOLLOW)
        try:
            first = fs.node_snapshot(descriptor, "control.json")
            state_files.write_state(state, "control.json", b'{"phase":"applied"}\n')
            final = fs.node_snapshot(descriptor, "control.json")
            self.assertEqual(b'{"phase":"applied"}\n', final["payload"])
            self.assertEqual(first["security"], final["security"])
            fs.assert_private(state / "control.json")
        finally:
            fs.secure_os.close(descriptor)
        print("NATIVE_EXACT_DACL_COPY: stable two-handle copies and real private state republication preserved ACL", flush=True)

    def test_private_directory_chmod_is_idempotent_and_preserves_security(self):
        """新私有目录重复请求 0700 必须保留真实 owner/ACL 与目录身份。"""
        name = "private-directory"
        fs.secure_os.mkdir(name, 0o700, dir_fd=self.parent)
        path = self.root / name
        fs.assert_private(path)
        descriptor = fs.secure_os.open(name, fs.DIRECTORY | fs.NOFOLLOW, dir_fd=self.parent)
        try:
            before = fs.secure_os.fstat(descriptor)
            security = fs.security_fingerprint(descriptor)
            for _ in range(2):
                # 与 scratch_workspace 使用同一相对父句柄 chmod 路径；不改
                # 临时根、不跳过证明，也不通过模拟 SetSecurityInfo 制造成功。
                fs.secure_os.chmod(name, 0o700, dir_fd=self.parent, follow_symlinks=False)
                fs.assert_private(path)
                after = fs.secure_os.fstat(descriptor)
                self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
                self.assertEqual(0o700, stat.S_IMODE(after.st_mode))
                self.assertEqual(security, fs.security_fingerprint(descriptor))
        finally:
            fs.secure_os.close(descriptor)
        print("NATIVE_PRIVATE_DIRECTORY_CHMOD: repeated requests preserved private owner/protected DACL and identity/security", flush=True)

    def test_private_file_acl_projection_and_real_change_time(self):
        path = self.private_file("private")
        fs.assert_private(path)
        self.assertEqual(stat.S_IMODE(fs.secure_os.stat(path).st_mode), 0o600)
        before = fs.node_snapshot(self.parent, path.name)
        self.assertRegex(before["security"], r"^[0-9a-f]{64}$")
        handle = fs._open_handle(path, fs.READ)
        try:
            self.assertEqual(before["identity"][6], (fs._basic_information(handle).changed - fs._EPOCH) * 100)
        finally:
            fs._close(handle)
        handle = fs._open_handle(path, 0x60080)
        descriptor = fs.HANDLE()
        try:
            api = fs._api()
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None), 0)
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        after = fs.node_snapshot(self.parent, path.name)
        self.assertEqual(after["payload"], before["payload"])
        self.assertNotEqual(after["security"], before["security"])
        # ChangeTime 是否变化由系统决定；真实 DACL 变化始终由独立摘要捕获。
        with self.assertRaises(ValueError):
            fs.assert_private(path)
        with self.assertRaises(ValueError):
            fs.move_regular(path.name, "backup", src_dir_fd=self.parent,
                            dst_dir_fd=self.parent, expected=before)
        self.assertTrue(path.exists())
        self.assertFalse((self.root / "backup").exists())

    def test_consuming_regular_move_preserves_identity_and_excludes_existing_target(self):
        source = self.private_file("source")
        expected = fs.node_snapshot(self.parent, source.name)
        self.private_file("occupied", b"user")
        with self.assertRaises(OSError):
            fs.move_regular("source", "occupied", src_dir_fd=self.parent,
                            dst_dir_fd=self.parent, expected=expected)
        self.assertEqual((self.root / "occupied").read_bytes(), b"user")
        fs.move_regular("source", "backup", src_dir_fd=self.parent,
                        dst_dir_fd=self.parent, expected=expected)
        self.assertFalse(source.exists())
        after = fs.node_snapshot(self.parent, "backup")
        self.assertEqual(after["identity"][:2], expected["identity"][:2])
        self.assertEqual(after["security"], expected["security"])

    def test_managed_skill_exact_create_read_move_delete_and_stale_refusal(self):
        core = self.root / "runtimes" / ("a" * 64) / "core"
        target = core / "platforms/shared/skills/xy-workflow"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_bytes(b"central-owned-body")
        fs.create_skill_symlink(self.parent, "xy-workflow", target, core_root=core)
        from lib.hosts.claude_instructions import read_file as shared_read
        with self.assertRaises(ValueError):
            shared_read(self.root / "xy-workflow/SKILL.md")
        first = fs.read_skill_symlink(self.parent, "xy-workflow", skill_name="xy-workflow")
        self.assertEqual(first["payload"], os.fsencode(target))
        self.assertEqual(first["kind"], "link")
        with self.assertRaises(OSError):
            fs.create_skill_symlink(self.parent, "xy-workflow", target, core_root=core)
        stale = {**first, "security": "0" * 64}
        with self.assertRaises(ValueError):
            fs.delete_skill_symlink(self.parent, "xy-workflow", skill_name="xy-workflow", expected=stale)
        fs.move_skill_symlink("xy-workflow", ".owned-recovery", src_dir_fd=self.parent,
                              dst_dir_fd=self.parent, skill_name="xy-workflow", expected=first)
        moved = fs.read_skill_symlink(self.parent, ".owned-recovery", skill_name="xy-workflow")
        self.assertEqual(moved["identity"][:2], first["identity"][:2])
        fs.delete_skill_symlink(self.parent, ".owned-recovery", skill_name="xy-workflow", expected=moved)
        self.assertIsNone(fs.read_skill_symlink(self.parent, ".owned-recovery", skill_name="xy-workflow"))
        self.assertEqual((target / "SKILL.md").read_bytes(), b"central-owned-body")

    def test_complete_regular_delete_preserves_acl_writer_replacement_and_deletes_owned(self):
        path = self.private_file("delete-owned")
        before = fs.node_snapshot(self.parent, path.name)
        def compact(snapshot):
            return {"identity": snapshot["identity"], "security": snapshot["security"],
                    "sha256": hashlib.sha256(snapshot["payload"]).hexdigest()}
        with path.open("r+b"), self.assertRaises(OSError):
            fs.delete_regular(self.parent, path.name, expected=compact(before))
        self.assertEqual(b"owned", path.read_bytes())
        replacement = self.private_file("replacement", b"later-user-save")
        os.replace(replacement, path)
        with self.assertRaises(ValueError):
            fs.delete_regular(self.parent, path.name, expected=compact(before))
        self.assertEqual(b"later-user-save", path.read_bytes())
        current = fs.node_snapshot(self.parent, path.name)
        fs.delete_regular(self.parent, path.name, expected=compact(current))
        self.assertFalse(path.exists())
        acl_path = self.private_file("delete-acl")
        original = fs.node_snapshot(self.parent, acl_path.name)
        descriptor, handle = fs.HANDLE(), fs._open_handle(acl_path, 0x60080)
        try:
            api = fs._api()
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None))
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        changed = fs.node_snapshot(self.parent, acl_path.name)
        self.assertNotEqual(original["security"], changed["security"])
        # 使用真实当前 metadata 与过期 ACL 构造负控，使任何 ChangeTime 行为都不能
        # 替独立 ACL 做决定；portable 同时覆盖七标量完全相同的前后 ACL 竞态。
        stale_acl = {**compact(changed), "security": original["security"]}
        with self.assertRaises(ValueError):
            fs.delete_regular(self.parent, acl_path.name, expected=stale_acl)
        self.assertEqual(b"owned", acl_path.read_bytes())
        print("NATIVE_DELETE_CAS: writer blocked; replacement retained; real ACL change retained; owned node deleted; dacl_change_time_equal="
              + str(original["identity"][6] == changed["identity"][6]))

    def test_conditional_empty_directory_and_streaming_read_exclude_changes(self):
        from lib import runtime_store
        from manager import runtime_lifecycle
        stream = self.private_file("stream-owned")
        with stream.open("r+b"):
            with self.assertRaises(OSError):
                runtime_store._read_regular(self.parent, stream.name)
            with self.assertRaises(OSError):
                runtime_lifecycle._file_metadata(self.parent, stream.name)
        fs.secure_os.mkdir("stage-dir", 0o700, dir_fd=self.parent)
        child = fs.secure_os.open("stage-dir", fs.DIRECTORY | fs.NOFOLLOW, dir_fd=self.parent)
        info = fs.secure_os.fstat(child)
        expected = {"identity": (info.st_dev, info.st_ino), "security": fs.security_fingerprint(child)}
        fs.secure_os.close(child)
        directory = self.root / "stage-dir"
        (directory / "user-save").write_bytes(b"must survive nonempty rejection")
        with self.assertRaises(OSError):
            fs.delete_directory(self.parent, directory.name, expected=expected)
        self.assertEqual(b"must survive nonempty rejection", (directory / "user-save").read_bytes())
        (directory / "user-save").unlink()
        fs.delete_directory(self.parent, directory.name, expected=expected)
        self.assertFalse(directory.exists())
        fs.secure_os.mkdir("replace-dir", 0o700, dir_fd=self.parent)
        child = fs.secure_os.open("replace-dir", fs.DIRECTORY | fs.NOFOLLOW, dir_fd=self.parent)
        info = fs.secure_os.fstat(child)
        stale = {"identity": (info.st_dev, info.st_ino), "security": fs.security_fingerprint(child)}
        fs.secure_os.close(child)
        (self.root / "replace-dir").rename(self.root / "original-dir")
        fs.secure_os.mkdir("replace-dir", 0o700, dir_fd=self.parent)
        with self.assertRaises(ValueError):
            fs.delete_directory(self.parent, "replace-dir", expected=stale)
        self.assertTrue((self.root / "replace-dir").is_dir())
        descriptor, handle = fs.HANDLE(), fs._open_handle(self.root / "replace-dir", 0x60080, directory=True)
        try:
            api = fs._api()
            current = fs._metadata(handle)
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None))
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        with self.assertRaises(ValueError):
            fs.delete_directory(self.parent, "replace-dir", expected={"identity": current[0][:2], "security": current[1]})
        self.assertTrue((self.root / "replace-dir").is_dir())
        print("NATIVE_DIRECTORY_CAS: empty deleted, nonempty and replacement retained; both128MiB stream consumers reject live writer")

    def test_independent_initial_private_gate_rejects_public_acl_before_core(self):
        private = self.private_file("initial-private")
        namespace = {}
        exec(compile(fs.bootstrap_reader_source(), "<private-native-initial>", "exec"), namespace)
        embedded = namespace["read_initial_regular"]
        self.assertEqual(b"owned", embedded(private, require_private=True))
        self.assertEqual(b"owned", fs.read_initial_regular(private, require_private=True))
        descriptor, handle = fs.HANDLE(), fs._open_handle(private, 0x60080)
        try:
            api = fs._api()
            sddl = f"O:{fs.current_sid()}D:P(A;;GA;;;{fs.current_sid()})(A;;GA;;;SY)(A;;GR;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            self.assertEqual(0, api.security.SetSecurityInfo(handle, 1, 0x80000004,
                None, None, fs._dacl(descriptor), None))
        finally:
            if descriptor.value:
                fs._api().kernel.LocalFree(descriptor)
            fs._close(handle)
        # 同一个公开文档仍可沿默认reader读取；只有控制/预执行材料要求私有信任门。
        self.assertEqual(b"owned", embedded(private))
        for read in (embedded, fs.read_initial_regular):
            with self.assertRaisesRegex(ValueError, "private"):
                read(private, require_private=True)
        print("NATIVE_INITIAL_PRIVATE: real private owner/protectedDACL accepted; public ACL rejected by embedded/backend; default public read retained")

    def test_global_mutex_real_second_process_contends_on_same_directory(self):
        source = ("import sys; sys.path.insert(0, sys.argv[1]); "
                  "from pathlib import Path; from lib.windows_fs import directory_lock\n"
                  "try:\n with directory_lock(Path(sys.argv[2]), 'native-contract'): pass\n"
                  "except ValueError as error:\n"
                  " if 'busy' not in str(error): raise\n"
                  " print('busy')\n"
                  "else: raise AssertionError('second process acquired held mutex')\n")
        with fs.directory_lock(self.root, "native-contract"):
            result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", source,
                                     str(PACK), str(self.root)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "busy")

    def test_cross_stage_parent_acl_inheritance_mismatch_is_a_real_failure(self):
        api = fs._api()
        def set_parent(path, everyone):
            path.mkdir()
            handle = fs._open_handle(path, 0x60080, directory=True)
            descriptor = fs.HANDLE()
            try:
                sddl = f"O:{fs.current_sid()}D:P(A;OICI;GA;;;{fs.current_sid()})(A;OICI;GA;;;SY)"
                if everyone:
                    sddl += "(A;OICI;GR;;;WD)"
                self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, ctypes.byref(descriptor), None))
                self.assertEqual(api.security.SetSecurityInfo(handle, 1, 0x80000004,
                    None, None, fs._dacl(descriptor), None), 0)
            finally:
                if descriptor.value:
                    api.kernel.LocalFree(descriptor)
                fs._close(handle)
        target_parent, stage_parent = self.root / "target-parent", self.root / "stage-parent"
        set_parent(target_parent, False)
        set_parent(stage_parent, True)
        target, stage = target_parent / "target", stage_parent / "stage"
        target.write_bytes(b"original")
        stage.write_bytes(b"candidate")
        with self.assertRaisesRegex(ValueError, "inheritance"):
            fs.copy_permissions(target, stage)
        self.assertEqual(target.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
