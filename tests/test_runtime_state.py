"""中央私有记录的领域校验、真实发布中断及资源生命周期回归。

通过原 runtime_service 入口证明消费者合同；不导入尚不存在的新模块来制造红灯。
每例使用短命状态/项目目录，真实子进程只操作自己的夹具，不启动宿主或模型。
"""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lib.platform_fs import directory_lock
from lib.central.runtime_project import LIMIT, Node, ProjectRuntimeError, Tree, json_bytes, node_id
from manager import runtime_service as service


PACK = Path(__file__).resolve().parents[1]
NONCE = "a" * 32
BINDING = {"protocol_version": 1, "content_id": "b" * 64, "manifest_sha256": "b" * 64}


class RuntimeStateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p3-private-state-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.state = self.root / "state"
        (self.state / "bindings").mkdir(parents=True)
        (self.state / "transactions").mkdir()
        self.binding = {"schema_version": 1, "project_root": str(self.project),
                        "project_identity": list(node_id(self.project.stat())),
                        "runtime_binding": BINDING, "enabled": False, "hosts": ["codex"],
                        "previous_binding": None, "used_bindings": [BINDING], "managed": {},
                        "retained_nodes": [], "generation": NONCE}
        self.journal = {"schema_version": 1, "project_root": str(self.project), "id": NONCE,
                        "phase": "prepared", "action": "enable", "binding_before": Node().value(),
                        "changes": [], "conflicts": []}

    def put(self, kind, value):
        relative = service._state_relative(self.project, kind)
        target = self.state / relative
        target.write_bytes(json_bytes(value))
        target.chmod(0o600)
        return relative

    def large_control(self):
        from manager import runtime_state
        # 非敏感填充模拟已经合法落盘的3.3MB中央日志；第二次发布必须连同
        # 完整before见证可编码、可读取，不能把合法record写成无法再次更新。
        before_body = json_bytes({"schema_version": 1, "phase": "applying", "padding": "x" * 3_300_000})
        after_body = json_bytes({"schema_version": 1, "phase": "compensating", "padding": "x" * 3_300_000})
        relative = "central/activation.json"
        with Tree(self.state) as tree:
            runtime_state.write_control(tree, relative, before_body, expected=Node())
        return relative, runtime_state.read_state(self.state, relative), after_body

    def test_large_legal_record_can_be_republished(self):
        from manager import runtime_state
        relative, before, after_body = self.large_control()
        with Tree(self.state) as tree:
            runtime_state.write_control(tree, relative, after_body, expected=before)
        after = runtime_state.read_state(self.state, relative)
        # 仍比较真实完整内容，但失败时只显示静态诊断，不能dump数MiB正文。
        self.assertTrue(after.payload == after_body, "large record phase update must preserve exact bytes")
        self.assertEqual("compensating", json.loads(after.payload)["phase"])
        self.assertEqual(["activation.json"], [path.name for path in (self.state / "central").iterdir()])

    def test_large_marker_sync_failure_restores_inode_and_retry_is_idempotent(self):
        from manager import runtime_state
        relative, before, after_body = self.large_control()
        native_link = runtime_state.os.link
        failed = False
        def fail_once(source, target, **kwargs):
            nonlocal failed
            if not failed and str(source).startswith(".central-state-"):
                failed = True
                raise OSError("fixture large marker publish interruption")
            return native_link(source, target, **kwargs)
        with Tree(self.state) as tree, patch.object(runtime_state.os, "link", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "large marker"):
                runtime_state.write_control(tree, relative, after_body, expected=before)
        restored = runtime_state.read_state(self.state, relative)
        self.assertTrue(restored.same_content(before), "synchronous failure must preserve full large preimage")
        self.assertEqual(before.identity[:2], restored.identity[:2])
        for _ in range(2):
            with Tree(self.state) as tree:
                expected = runtime_state.read_state(self.state, relative)
                runtime_state.write_control(tree, relative, after_body, expected=expected)
            self.assertTrue(runtime_state.read_state(self.state, relative).payload == after_body)
        self.assertEqual(["activation.json"], [path.name for path in (self.state / "central").iterdir()])

    def test_large_marker_real_exit_preserves_full_witness_and_gate(self):
        from manager import runtime_state
        relative, before, _ = self.large_control()
        code = '''import json, os, sys
from pathlib import Path
from manager import runtime_state
from lib.central.runtime_project import Tree, json_bytes
state = Path(sys.argv[1])
relative = 'central/activation.json'
before = runtime_state.read_state(state, relative)
record = json.loads(before.payload)
record['phase'] = 'compensating'
native_open = runtime_state.os.open
def interrupt(path, *args, **kwargs):
    if str(path).startswith('.central-state-'):
        os._exit(73)
    return native_open(path, *args, **kwargs)
runtime_state.os.open = interrupt
with Tree(state) as tree:
    runtime_state.write_control(tree, relative, json_bytes(record), expected=before)
'''
        result = subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8", "-c", code, str(self.state)],
                                cwd=PACK, capture_output=True, text=True, timeout=15)
        self.assertEqual(73, result.returncode, result.stdout + result.stderr)
        with Tree(self.state) as tree:
            with self.assertRaises(ProjectRuntimeError):
                tree.read(relative + ".publish")
            marker = tree.read(relative + ".publish", max_bytes=runtime_state.PRIVATE_MARKER_LIMIT)
            value = json.loads(marker.payload)
            self.assertTrue(Node.from_value(value["before"]) == before, "crash witness must retain the full exact Node")
            self.assertGreater(len(marker.payload), LIMIT)
            self.assertLessEqual(len(marker.payload), runtime_state.PRIVATE_MARKER_LIMIT)
            for _ in range(2):
                with self.assertRaisesRegex(service.ActivationError, "私有记录发布中断"):
                    runtime_state.read_state(self.state, relative)
                self.assertTrue(tree.read(relative + ".publish", max_bytes=runtime_state.PRIVATE_MARKER_LIMIT) == marker)
        print(f"large_marker_exit exit={result.returncode} marker_bytes={len(marker.payload)} gate_closed=True")

    def test_record_marker_and_default_resource_limits_remain_distinct(self):
        from manager import runtime_state
        self.assertEqual(4 * 1024 * 1024, LIMIT)
        self.assertEqual(runtime_state.PRIVATE_MARKER_LIMIT,
                         runtime_state.publication_capacity(LIMIT))
        # 真正最大合法普通记录仍可更新；不能只修好3.3MB后在4MiB再次卡死。
        prefix, suffix = b'{"schema_version":1,"padding":"', b'"}'
        body = prefix + b"x" * (LIMIT - len(prefix) - len(suffix)) + suffix
        relative = "central/activation.json"
        with Tree(self.state) as tree:
            runtime_state.write_control(tree, relative, body, expected=Node())
            old = runtime_state.read_state(self.state, relative)
            runtime_state.write_control(tree, relative, json_bytes({"schema_version": 1}), expected=old)
            stable = runtime_state.read_state(self.state, relative)
            with self.assertRaises(service.ActivationError):
                runtime_state.write_control(tree, relative, body + b" ", expected=stable)
            self.assertTrue(runtime_state.read_state(self.state, relative) == stable)
            large = self.state / "explicit-envelope"
            large.write_bytes(b"x" * (LIMIT + 1))
            with self.assertRaises(ProjectRuntimeError):
                tree.read("explicit-envelope")
            explicit = tree.read("explicit-envelope", max_bytes=runtime_state.PRIVATE_MARKER_LIMIT)
            self.assertEqual(LIMIT + 1, len(explicit.payload))
            with self.assertRaises(ProjectRuntimeError):
                Node.from_value(explicit.value())
            marker = self.state / (relative + ".publish")
            marker.write_bytes(b"x" * (runtime_state.PRIVATE_MARKER_LIMIT + 1))
            with self.assertRaises(ProjectRuntimeError):
                tree.read(relative + ".publish", max_bytes=runtime_state.PRIVATE_MARKER_LIMIT)
            marker.write_bytes(b'{"malformed":')
            with self.assertRaisesRegex(service.ActivationError, "私有记录发布中断"):
                runtime_state.read_state(self.state, relative)
        for invalid in (True, 0, -1, 2 * LIMIT + 1):
            with self.subTest(limit=invalid), self.assertRaises(ProjectRuntimeError):
                json_bytes({}, max_bytes=invalid)

    def test_invalid_journal_rows_are_safe_domain_errors(self):
        # 原实现直接 row["path"]，坏项会穿出 TypeError/KeyError，后续恢复甚至
        # 尚未验证 conflicts/installed 等嵌套结构。诊断不得泄露坏记录正文。
        for malformed in (None, {}, {"path": "PRIVATE-BODY-MUST-NOT-LEAK"}):
            with self.subTest(row=malformed):
                record = copy.deepcopy(self.journal)
                record["changes"] = [malformed]
                self.put("transactions", record)
                with self.assertRaises(service.ActivationError) as raised:
                    service._journal(self.state, self.project)
                self.assertNotIn("PRIVATE-BODY-MUST-NOT-LEAK", str(raised.exception))

    def test_complete_nested_codecs_reject_bad_optional_and_embedded_values(self):
        stem = f".agent-workflow/.agent-workflow-central-{NONCE}-0"
        row = {"path": ".agent-workflow/runtime.json", "before": Node().value(),
               "after": Node("file", b"fixture", 0o600).value(),
               "backup": stem + ".previous", "stage": stem + ".stage", "rollback": stem + ".rollback"}
        changes = []
        for key, value in (("installed", None), ("stage_inode", [True, 1]), ("published_inode", [1]),
                           ("before", {"kind": []}), ("after", {"kind": "file", "body": [], "identity": [], "mode": 0})):
            broken = copy.deepcopy(row)
            broken[key] = value
            changes.append(("changes", [broken]))
        changes.extend((("conflicts", [None]), ("conflicts", [{"path": ".", "reason": []}]),
                        ("retained_nodes", [{}]), ("phase", []), ("schema_version", True),
                        ("binding_before", Node("file", b'{"PRIVATE-BODY-MUST-NOT-LEAK":true}', 0o600,
                                                (1, 2, 0, 1, 0, 0, 0)).value())))
        for key, value in changes:
            with self.subTest(field=key, value=value):
                journal = copy.deepcopy(self.journal)
                journal[key] = value
                self.put("transactions", journal)
                with self.assertRaises(service.ActivationError) as raised:
                    service._journal(self.state, self.project)
                self.assertNotIn("PRIVATE-BODY-MUST-NOT-LEAK", str(raised.exception))
        for key, value in (("hosts", [[]]), ("used_bindings", [None]), ("runtime_binding", {}),
                           ("managed", {"AGENTS.md": {"purpose": "block", "baseline": None, "expected": {}}})):
            with self.subTest(binding_field=key):
                record = copy.deepcopy(self.binding)
                record[key] = value
                self.put("bindings", record)
                with self.assertRaises(service.ActivationError):
                    service.read_binding_record(self.state, self.project)

    def test_invalid_retained_nodes_are_rejected_at_binding_read(self):
        for malformed in (None, {}, {"path": "PRIVATE-BODY-MUST-NOT-LEAK"}):
            with self.subTest(retained=malformed):
                record = copy.deepcopy(self.binding)
                record["retained_nodes"] = [malformed]
                self.put("bindings", record)
                with self.assertRaises(service.ActivationError) as raised:
                    service.read_binding_record(self.state, self.project)
                self.assertNotIn("PRIVATE-BODY-MUST-NOT-LEAK", str(raised.exception))

    def test_retained_conflicts_report_actual_difference_in_priority_order(self):
        cases = (
            ("unchanged", None),
            ("missing", "保留的旧 inode 路径已缺失"),
            ("missing_parent", "保留的旧 inode 路径已缺失"),
            ("content", "保留的旧 inode 内容或类型已变化"),
            ("type", "保留的旧 inode 内容或类型已变化"),
            ("permissions", "保留的旧 inode 权限已变化"),
            ("identity", "保留的旧 inode 身份已变化"),
            ("permissions_and_identity", "保留的旧 inode 权限已变化"),
            ("content_permissions_and_identity", "保留的旧 inode 内容或类型已变化"),
        )
        for difference, reason in cases:
            with self.subTest(difference=difference):
                relative = f"{difference}/.agent-workflow-central-{NONCE}-0.previous"
                target = self.project / relative
                target.parent.mkdir()
                target.write_bytes(b"retained-fixture")
                target.chmod(0o600)
                with Tree(self.project) as tree:
                    record = service._retained_record(relative, service._raw(tree, relative))
                record_before = copy.deepcopy(record)
                if difference in {"missing", "missing_parent", "type"}:
                    target.unlink()
                    if difference == "missing_parent":
                        target.parent.rmdir()
                    elif difference == "type":
                        # 链接正文与原文件字节相同，仍必须按类型变化阻断；
                        # reader 只取链接自身，不访问不存在的目标。
                        target.symlink_to("retained-fixture")
                elif difference == "content":
                    target.write_bytes(b"saved-after-record")
                elif difference == "permissions":
                    target.chmod(0o640)
                elif "identity" in difference:
                    # 新旧文件同时存在后再替换，保证真实 inode 不同；组合
                    # 差异约束诊断优先级，而非依赖系统碰巧复用 inode。
                    replacement = target.with_name("replacement")
                    replacement.write_bytes(b"saved-after-record" if "content" in difference else b"retained-fixture")
                    replacement.chmod(0o640 if "permissions" in difference else 0o600)
                    replacement.replace(target)
                    self.assertNotEqual(record["inode"], list(node_id(target.stat())))
                with Tree(self.project) as tree:
                    before = service._raw(tree, relative)
                    self.assertEqual([] if reason is None else [{"path": relative, "reason": reason}],
                                     service._retained(tree, [record]))
                    # 诊断不能修复缺失、改写记录或清理后续保存；核对完整真实
                    # 节点前后像，避免仅检查 reason 而漏掉数据保留合同。
                    self.assertEqual(before, service._raw(tree, relative))
                    self.assertEqual(record_before, record)

    def test_process_exit_during_private_publication_is_explicitly_rejected(self):
        # 真实磁盘调用完成后 os._exit，finally 不会运行。重启只通过旧 reader
        # 与 repair 入口判断：不得把隔离窗口读成从未管理或普通多硬链错误。
        for point in ("first_before_temporary", "after_previous_rename", "after_target_link", "after_temporary_unlink"):
            with self.subTest(point=point):
                if point != "first_before_temporary":
                    self.put("bindings", self.binding)
                code = '''import json, os, sys
from pathlib import Path
from lib.central.runtime_project import Tree, json_bytes
from manager import runtime_service as service
state, project, point = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
relative = service._state_relative(project, "bindings")
old = json.loads(sys.argv[4])
old["generation"] = "c" * 32
original_rename, original_link = service.os.rename, service.os.link
original_open, original_unlink = service.os.open, service.os.unlink
def open_file(path, *args, **kwargs):
    if point == "first_before_temporary" and str(path).startswith(".central-state-"):
        os._exit(73)
    return original_open(path, *args, **kwargs)
def rename(source, target, **kwargs):
    original_rename(source, target, **kwargs)
    if point == "after_previous_rename" and str(target).startswith(".central-state-previous-"):
        os._exit(73)
def link(source, target, **kwargs):
    original_link(source, target, **kwargs)
    if point == "after_target_link" and str(source).startswith(".central-state-"):
        os._exit(73)
def unlink(path, **kwargs):
    original_unlink(path, **kwargs)
    if point == "after_temporary_unlink" and str(path).startswith(".central-state-"):
        os._exit(73)
service.os.rename, service.os.link = rename, link
service.os.open, service.os.unlink = open_file, unlink
with Tree(state) as tree:
    service._write_private(tree, relative, json_bytes(old))
'''
                result = subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8", "-c", code,
                                         str(self.state), str(self.project), point, json.dumps(self.binding)], cwd=PACK,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(73, result.returncode, result.stdout + result.stderr)
                print(f"private_publication_exit point={point} exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}")
                with self.assertRaisesRegex(service.ActivationError, "私有记录发布中断"):
                    service.read_binding_record(self.state, self.project)
                with self.assertRaisesRegex(service.ActivationError, "私有记录发布中断"):
                    service.preview(self.state, self.project, "repair")
                # 每个子场景清理的都是本例独占目录；生产读取绝不扫描/删除随机残留。
                for child in (self.state / "bindings").iterdir():
                    child.unlink()

    def test_partial_or_unsafe_markers_fail_closed_without_cleanup(self):
        for kind in ("bindings", "transactions"):
            relative = service._state_relative(self.project, kind)
            marker = self.state / (relative + ".publish")
            unknown = self.state / kind / ".central-state-unknown-owner"
            unknown.write_bytes(b"unknown must survive")
            for marker_kind in ("partial", "link"):
                with self.subTest(kind=kind, marker=marker_kind):
                    if marker_kind == "partial":
                        marker.write_bytes(b'{"PRIVATE-BODY-MUST-NOT-LEAK":')
                    else:
                        marker.symlink_to(unknown)
                    reader = service.read_binding_record if kind == "bindings" else service._journal
                    with self.assertRaisesRegex(service.ActivationError, "私有记录发布中断") as raised:
                        reader(self.state, self.project)
                    self.assertIn(relative + ".publish", str(raised.exception))
                    self.assertNotIn("PRIVATE-BODY-MUST-NOT-LEAK", str(raised.exception))
                    self.assertEqual(b"unknown must survive", unknown.read_bytes())
                    self.assertTrue(marker.is_symlink() or marker.is_file())
                    marker.unlink()

    def test_private_publication_expected_rejects_external_save_before_capture(self):
        candidate = json_bytes({**self.binding, "generation": "c" * 32})
        external = json_bytes({**self.binding, "generation": "d" * 32})
        for operation, same_payload in (("save", True), ("save", False),
                                        ("replace", True), ("replace", False), ("chmod", True)):
            with self.subTest(operation=operation, same_payload=same_payload):
                relative = self.put("bindings", self.binding)
                target = self.state / relative
                expected = service.read_binding_record(self.state, self.project)[0]
                if operation == "replace":
                    # 新旧节点同时存在后再替换，确保同字节保存也确有不同 inode；
                    # 不依赖 unlink 后系统是否立即复用 inode。
                    replacement = target.with_name("external-replacement")
                    replacement.write_bytes(expected.payload if same_payload else external)
                    replacement.chmod(0o600)
                    replacement.replace(target)
                elif operation == "save":
                    target.write_bytes(expected.payload if same_payload else external)
                    if same_payload:
                        # 同字节、同权限、同 inode 的保存仍改变完整前像；显式推进
                        # mtime 保证夹具在不同文件系统时间精度下也构成真实变化。
                        info = target.stat()
                        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
                else:
                    target.chmod(0o640)
                with directory_lock(self.state / "bindings", "central-project-state"), Tree(self.state) as tree:
                    actual = service._raw(tree, relative)
                    self.assertNotEqual(expected, actual, "外部写入必须确实改变真实完整前像")
                    self.assertEqual(expected.payload if same_payload else external, actual.payload)
                    self.assertEqual(operation == "replace", expected.identity[:2] != actual.identity[:2])
                    with self.assertRaisesRegex(service.ActivationError, "预期前像不符"):
                        service._write_private(tree, relative, candidate, expected=expected)
                    # 拒绝发生在 marker/临时名发布之前；必须保留外部节点的完整
                    # 字节、权限及身份，不能把外部保存变成可自动清理的恢复资料。
                    self.assertEqual(actual, service._raw(tree, relative))
                self.assertEqual([target.name], [item.name for item in target.parent.iterdir()])

    def test_private_publication_accepts_matching_complete_expected(self):
        relative = service._state_relative(self.project, "bindings")
        candidate = {**self.binding, "generation": "c" * 32}
        with directory_lock(self.state / "bindings", "central-project-state"), Tree(self.state) as tree:
            # Node() 明确表示已核对的缺失，不能与省略 expected 的 None 混同。
            service._write_private(tree, relative, json_bytes(self.binding), expected=Node())
            expected = service._raw(tree, relative)
            service._write_private(tree, relative, json_bytes(candidate), expected=expected)
        self.assertEqual(candidate, service.read_binding_record(self.state, self.project)[1])
        self.assertEqual([Path(relative).name], [item.name for item in (self.state / "bindings").iterdir()])

    def test_private_publication_roundtrip_and_sync_failure_restore_exact_inode(self):
        from manager import runtime_state
        relative = self.put("bindings", self.binding)
        before = service.read_binding_record(self.state, self.project)[0]
        candidate = {**self.binding, "generation": "c" * 32}
        native_link = runtime_state.os.link
        failed = False
        def fail_once(source, target, **kwargs):
            nonlocal failed
            if not failed and str(source).startswith(".central-state-"):
                failed = True
                raise OSError("fixture private no-replace link failure")
            return native_link(source, target, **kwargs)
        descriptors = self._open_descriptors()
        with directory_lock(self.state / "bindings", "central-project-state"):
            with Tree(self.state) as tree, patch.object(runtime_state.os, "link", side_effect=fail_once):
                with self.assertRaisesRegex(OSError, "fixture private"):
                    service._write_private(tree, relative, json_bytes(candidate))
        after, record = service.read_binding_record(self.state, self.project)
        self.assertEqual(self.binding, record)
        self.assertTrue(after.same_content(before))
        self.assertEqual(before.identity[:2], after.identity[:2])
        self.assertEqual([Path(relative).name], [item.name for item in (self.state / "bindings").iterdir()])
        # 同一状态锁可被独立进程重新取得，fd 计数不依赖 /proc 或新增系统工具。
        code = '''from pathlib import Path
import sys
from lib.platform_fs import directory_lock
with directory_lock(Path(sys.argv[1]), "central-project-state"):
    print("lock released")
'''
        probe = subprocess.run(["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8", "-c", code,
                                str(self.state / "bindings")], cwd=PACK, capture_output=True, text=True, timeout=10)
        self.assertEqual((0, "lock released\n", ""), (probe.returncode, probe.stdout, probe.stderr))
        self.assertEqual(descriptors, self._open_descriptors())
        with Tree(self.state) as tree:
            service._write_private(tree, relative, json_bytes(candidate))
            service._write_private(tree, service._state_relative(self.project, "transactions"), json_bytes(self.journal))
        self.assertEqual(candidate, service.read_binding_record(self.state, self.project)[1])
        self.assertEqual(self.journal, service._journal(self.state, self.project)[1])

    @staticmethod
    def _open_descriptors():
        # 本测试仅打开少量 fd；逐个 fstat 避免枚举 /dev/fd 时把枚举句柄计入。
        opened = set()
        for descriptor in range(256):
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            opened.add(descriptor)
        return opened

    def test_external_save_during_private_publication_is_retained(self):
        from manager import runtime_state
        relative = self.put("bindings", self.binding)
        target = self.state / relative
        native_rename = runtime_state.os.rename
        old_inode = target.open("r+b")
        self.addCleanup(old_inode.close)
        saved = b"external save must survive\n"
        def save_after_rename(source, destination, **kwargs):
            native_rename(source, destination, **kwargs)
            if str(destination).startswith(".central-state-previous-"):
                old_inode.seek(0)
                old_inode.write(saved)
                old_inode.truncate()
                old_inode.flush()
                os.fsync(old_inode.fileno())
        with Tree(self.state) as tree, patch.object(runtime_state.os, "rename", side_effect=save_after_rename):
            with self.assertRaisesRegex(service.ActivationError, "隔离时被修改"):
                service._write_private(tree, relative, json_bytes({**self.binding, "generation": "c" * 32}))
        with self.assertRaisesRegex(service.ActivationError, "私有记录发布中断"):
            service.read_binding_record(self.state, self.project)
        retained = list((self.state / "bindings").glob(".central-state-previous-*"))
        self.assertEqual(1, len(retained))
        self.assertEqual(saved, retained[0].read_bytes())

    def test_private_publication_final_guard_retains_late_save(self):
        from manager import runtime_state
        relative = self.put("bindings", self.binding)
        target = self.state / relative
        native_fsync = runtime_state.os.fsync
        saved = b"late save before marker cleanup must survive\n"
        parent_syncs = 0
        with Tree(self.state) as tree:
            parent, _ = tree.parent(relative)
            def save_during_final_sync(descriptor):
                nonlocal parent_syncs
                native_fsync(descriptor)
                if descriptor == parent:
                    parent_syncs += 1
                    if parent_syncs == 3:
                        # 标记与临时发布已各同步一次；第三次是新节点完成检查后、
                        # 撤标记前。真实写入比单纯模拟 reader 返回更能约束数据保全。
                        target.write_bytes(saved)
            with patch.object(runtime_state.os, "fsync", side_effect=save_during_final_sync):
                with self.assertRaisesRegex(service.ActivationError, "后续保存"):
                    service._write_private(tree, relative, json_bytes({**self.binding, "generation": "c" * 32}))
        self.assertEqual(saved, target.read_bytes())
        with self.assertRaisesRegex(service.ActivationError, "私有记录发布中断"):
            service.read_binding_record(self.state, self.project)

    def test_private_publication_closes_descriptors_before_stream_transfer(self):
        from manager import runtime_state
        import errno
        relative = self.put("bindings", self.binding)
        target = self.state / relative
        marker = self.state / (relative + ".publish")
        before = service.read_binding_record(self.state, self.project)[0]
        candidate = json_bytes({**self.binding, "generation": "c" * 32})
        native_open, native_fstat, native_fdopen = os.open, os.fstat, os.fdopen
        for resource, operation in (("marker", "fstat"), ("marker", "fdopen"),
                                    ("temporary", "fstat"), ("temporary", "fdopen")):
            with self.subTest(resource=resource, operation=operation):
                acquired = {}
                injected = False
                failure = None
                descriptors = self._open_descriptors()
                def track_open(path, flags, *args, **kwargs):
                    descriptor = native_open(path, flags, *args, **kwargs)
                    # 跟踪真实 O_EXCL 创建返回的 fd；Tree/reader 的只读打开不纳入
                    # 故障目标，关闭断言直接 fstat 该 fd，不依赖 mock.close 调用次数。
                    if flags & os.O_CREAT:
                        if str(path).endswith(".publish"):
                            acquired["marker"] = descriptor
                        elif str(path).startswith(".central-state-"):
                            acquired["temporary"] = descriptor
                    return descriptor
                def fail_metadata(descriptor):
                    nonlocal injected
                    if operation == "fstat" and descriptor == acquired.get(resource) and not injected:
                        injected = True
                        raise OSError(errno.EIO, "fixture metadata failure before stream transfer")
                    return native_fstat(descriptor)
                def fail_transfer(descriptor, *args, **kwargs):
                    nonlocal injected
                    if operation == "fdopen" and descriptor == acquired.get(resource) and not injected:
                        injected = True
                        # BaseException 代表移交前取消；尚未成功的 fdopen 不拥有裸 fd。
                        raise KeyboardInterrupt("fixture cancellation before stream transfer")
                    return native_fdopen(descriptor, *args, **kwargs)
                try:
                    with directory_lock(self.state / "bindings", "central-project-state"), Tree(self.state) as tree:
                        with patch.object(runtime_state.os, "open", side_effect=track_open), \
                             patch.object(runtime_state.os, "fstat", side_effect=fail_metadata), \
                             patch.object(runtime_state.os, "fdopen", side_effect=fail_transfer):
                            try:
                                service._write_private(tree, relative, candidate)
                            except BaseException as exc:
                                failure = exc
                    self.assertTrue(injected, "必须到达真实 open 后的目标故障点")
                    self.assertIn(resource, acquired)
                    descriptor = acquired[resource]
                    try:
                        native_fstat(descriptor)
                    except OSError as exc:
                        self.assertEqual(errno.EBADF, exc.errno)
                        closed = True
                    else:
                        closed = False
                    print(f"private_fd_transfer_fault resource={resource} operation={operation} "
                          f"caught={type(failure).__name__} descriptor_closed={closed}")
                    self.assertTrue(closed, "open 成功后、stream 接管前故障必须关闭真实 fd")
                    self.assertIsInstance(failure, OSError if operation == "fstat" else KeyboardInterrupt)
                    self.assertEqual(descriptors, self._open_descriptors())
                    self.assertEqual(before.payload, target.read_bytes())
                    self.assertEqual(before.identity[:2], node_id(target.stat()))
                    temporary = list((self.state / "bindings").glob(".central-state-*"))
                    if resource == "marker" or operation == "fstat":
                        # 未取得 marker 身份/未完成内容，以及临时文件 fstat 失败时
                        # 都缺少精确清理依据；原文件保持，但未知节点和见证必须保留。
                        self.assertTrue(marker.is_file())
                        self.assertEqual(1 if resource == "temporary" else 0, len(temporary))
                        with self.assertRaisesRegex(service.ActivationError, "私有记录发布中断"):
                            service.read_binding_record(self.state, self.project)
                    else:
                        # 临时 inode 已确证而 fdopen 尚未接管时，精确清理该节点后
                        # 可以沿既有原前像恢复规则结算，不能把所有异常永久标冲突。
                        self.assertFalse(marker.exists())
                        self.assertFalse(temporary)
                        self.assertEqual(self.binding, service.read_binding_record(self.state, self.project)[1])
                finally:
                    # 红证也要关掉缺陷泄漏的测试 fd；只清理本用例独占目录中的
                    # 故障资料，避免测试自身把资源泄漏带到后续子场景或其它实例。
                    for descriptor in set(acquired.values()):
                        try:
                            native_fstat(descriptor)
                        except OSError as exc:
                            if exc.errno != errno.EBADF:
                                raise
                        else:
                            os.close(descriptor)
                    for child in (self.state / "bindings").iterdir():
                        if child != target:
                            child.unlink()


if __name__ == "__main__":
    unittest.main()
