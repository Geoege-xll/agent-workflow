"""只使用请求 scratch 验证全局归属、原生路径、固定预览与稀疏完整描述符。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import copy
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lib import role_models, runtime_store
from lib.central.runtime_project import CONFIG, Node, Resources, Tree, json_bytes, prepare
from lib.hosts.native_context import HostPaths, NativeContext
from lib.hosts import native_agents as native, native_journal
from manager import native_agents
from tests import test_workflow_manager as fixtures


class NativeJournalCodecTest(unittest.TestCase):
    def test_lossless_deterministic_shared_body_and_independent_containers(self):
        for security in (None, "a" * 64):
            node = Node("file", b"exact bytes\x00\xff", 0o600, (1, 2, 3, 1, 13, 5, 6)).value()
            if security is not None:
                node["security"] = security
            logical = {"schema_version": 1, "first": node, "second": node}
            with self.subTest(security=security):
                encoded = native_journal.encode(logical)
                wire = json.loads(encoded)
                self.assertEqual(2, wire["schema_version"])
                self.assertEqual(1, len(wire["bodies"]))
                reordered = {key: (dict(reversed(list(value.items()))) if isinstance(value, dict) else value)
                             for key, value in reversed(list(logical.items()))}
                self.assertEqual(encoded, native_journal.encode(reordered))
                restored = native_journal.decode(encoded)
                self.assertEqual(logical, restored)
                self.assertIs(restored["first"]["body"], restored["second"]["body"])
                self.assertIsNot(restored["first"], restored["second"])
                self.assertIsNot(restored["first"]["identity"], restored["second"]["identity"])
                self.assertEqual(encoded, native_journal.encode(restored))
                self.assertEqual(1, logical["schema_version"])
                self.assertNotIn("body_ref", logical["first"])

    def test_physical_limit_and_repeated_body_logical_limit_are_separate(self):
        from lib.central.runtime_project import LIMIT
        node = Node("file", b"x" * 600000, 0o600).value()
        logical = {"schema_version": 1, "nodes": [node] * 9}
        with self.assertRaises(ValueError):
            json_bytes(logical)
        encoded = native_journal.encode(logical)
        self.assertLess(len(encoded), LIMIT)
        self.assertEqual(logical, native_journal.decode(encoded))
        # 物理表仍只有一份正文，扩大引用次数必须被独立的 RAM 展开界拒绝。
        wire = json.loads(encoded)
        wire["nodes"] *= 2
        with self.assertRaises(ValueError):
            native_journal.decode(json_bytes(wire))
        with self.assertRaises(ValueError):
            native_journal.encode({"schema_version": 1, "nodes": [node] * 18})
        with self.assertRaises(ValueError):
            native_journal.decode(b" " * (LIMIT + 1))
        legacy = {"schema_version": 1, "legacy": {"body_ref": "not a v2 reference"}}
        self.assertEqual(legacy, native_journal.decode(json_bytes(legacy)))

    def test_malformed_references_tables_cycles_and_unknown_schema_fail_closed(self):
        wire = json.loads(native_journal.encode({"schema_version": 1, "node": Node("file", b"one", 0o600).value()}))
        candidates = []
        for reference in (True, -1, 1, "0", None):
            bad = copy.deepcopy(wire)
            bad["node"]["body_ref"] = reference
            candidates.append(bad)
        for body in (wire["bodies"][0], base64.b64encode(b"unused").decode()):
            candidates.append({**copy.deepcopy(wire), "bodies": [*wire["bodies"], body]})
        candidates += [{**copy.deepcopy(wire), "bodies": ["not base64!"]},
                       {**copy.deepcopy(wire), "bodies": [{}]},
                       {**copy.deepcopy(wire), "schema_version": 3},
                       {**copy.deepcopy(wire), "node": {**wire["node"], "unknown": True}},
                       {**copy.deepcopy(wire), "node": Node("file", b"one", 0o600).value()}]
        for index, bad in enumerate(candidates):
            with self.subTest(index=index), self.assertRaises(ValueError):
                native_journal.decode(json_bytes(bad))
        with self.assertRaises(ValueError):
            native_journal.decode(b'{"schema_version":2,"schema_version":2,"bodies":[]}')
        logical = {"schema_version": 1}
        logical["cycle"] = logical
        with self.assertRaises(ValueError):
            native_journal.encode(logical)


class NativeAgentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="native-agents-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        cls.root = Path(cls.temporary.name).resolve()
        cls.source = fixtures.CentralCliIntegrationTest.create_source(cls.root)
        cls.state = cls.root / "state"
        cls.core = runtime_store.import_core(cls.source, cls.state)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.case = self.root / self._testMethodName
        self.case.mkdir()
        self.home = self.case / "home"
        self.home.mkdir()
        self.paths = HostPaths.for_home(self.home, environment={})
        self.context = NativeContext(self.state, self.paths)

    def preview(self, **options):
        return native_agents.preview_global(self.state, self.core.binding(), context=self.context, **options)

    def install(self, **options):
        plan = self.preview(**options)
        self.assertTrue(plan.can_apply, plan.summary)
        return native_agents.apply_global(plan)

    def interrupted_missing_compensation(self):
        """由真实全局发布器留下已隔离原 inode、尚未发布的新 stage。"""
        self.install(hosts=("codex",))
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        publish = native_agents.publish_at
        interrupted = []
        def stop_before_publish(source, target, **kwargs):
            if target == "xy-backend.toml" and not interrupted:
                interrupted.append(True)
                raise KeyboardInterrupt("fixture original inode retained before publish")
            return publish(source, target, **kwargs)
        with patch.object(native_agents, "publish_at", side_effect=stop_before_publish):
            with self.assertRaisesRegex(KeyboardInterrupt, "original inode retained"):
                native_agents.apply_global(plan)
        self.assertTrue(interrupted)
        _, journal = native_agents._load_ref(plan.recovery_ref, self.context)
        row = next(row for row in journal["writes"] if row["path"] == "agents/xy-backend.toml")
        self.assertEqual("missing", native.read_node(self.paths.codex, row["path"]).kind)
        return plan, journal, row

    def test_owned_full_windows_refresh_budget_and_recovery(self):
        from lib.central import runtime_project
        from lib.central.runtime_project import LIMIT
        compile_role = native.compile_role
        prefix = r"C:\Users\runneradmin\AppData\Local\awf-delivery-test-" + "a" * 32 + "\\程序 空格\\versions\\2.1.4-"

        def windows_compiler(version):
            def compile_current(*args, **kwargs):
                # 只在已预载的纯角色编译器内使用 Windows 正文分支；所有权、
                # 发布、补偿和日志均走本机真实生产路径，不宣称 Win32/ACL 取证。
                with patch.object(runtime_project, "os", SimpleNamespace(name="nt")), patch.object(
                        runtime_project.sys, "executable", prefix + version * 64 + r"\venv\Scripts\python.exe"):
                    return compile_role(*args, **kwargs)
            return compile_current

        with patch.object(native, "compile_role", side_effect=windows_compiler("a")):
            self.install()
        originals = {(host, path): native.read_node(self.paths.root(host), path).payload
                     for host, path, _ in self.preview().desired}
        with patch.object(native, "compile_role", side_effect=windows_compiler("b")):
            plan = self.preview()
        self.assertTrue(plan.can_apply, plan.summary)
        self.assertEqual([], plan.conflicts)
        self.assertEqual(21, len(plan.summary["changes"]))
        encode = native_journal.encode
        projection_sizes = []

        def observe_projection(journal):
            encoded = encode(journal)
            projection_sizes.append((len(json.dumps(journal, ensure_ascii=False, sort_keys=True, indent=2).encode()) + 1,
                                     len(encoded)))
            return encoded

        with patch.object(native_journal, "encode", side_effect=observe_projection):
            bound = native_agents.receipt_budget(plan)
        self.assertGreater(max(logical for logical, _ in projection_sizes), LIMIT)
        self.assertLessEqual(max(wire for _, wire in projection_sizes), LIMIT)
        save, saved_sizes = native_agents._save, []
        interruption = ["staged", "result"]

        def observe_save(state, journal):
            save(state, journal)
            payload = native.read_node(state, native_agents._journal_relative(journal["transaction_id"])).payload
            saved_sizes.append(len(payload))
            self.assertEqual(2, json.loads(payload)["schema_version"])
            self.assertEqual(journal, native_journal.decode(payload))
            steps = journal.get("compensations", [])
            if steps and interruption:
                latest = steps[-1]
                ready = (latest["staged"] is not None if interruption[0] == "staged" else latest["result"] is not None)
                if ready:
                    raise KeyboardInterrupt("fixture durable compensation " + interruption.pop(0))

        with patch.object(native_agents, "_save", side_effect=observe_save):
            receipt = native_agents.apply_global(plan)
            actual = len(json_bytes({"native_receipt": receipt})) - len(json_bytes({"native_receipt": None}))
            self.assertLessEqual(actual, bound)
            self.assertEqual([], native_agents.verify_global(plan.recovery_ref, context=self.context))
            # 同一真实逆操作先在 stage、再在 result 已持久后中断；恢复不得
            # 追加另一份授权或吞掉隔离资料，第三次才完成全部条件清理。
            for _ in range(2):
                with self.assertRaises(KeyboardInterrupt):
                    native_agents.recover_global(plan.recovery_ref, context=self.context)
            recovered = native_agents.recover_global(plan.recovery_ref, context=self.context)
        self.assertEqual("compensated", recovered["status"], recovered["conflicts"])
        self.assertEqual("compensated", native_agents.recover_global(plan.recovery_ref, context=self.context)["status"])
        self.assertLessEqual(max(saved_sizes), max(wire for _, wire in projection_sizes))
        self.assertEqual(3, len(native_agents.verified_hosts(self.state, context=self.context)))
        for (host, path), body in originals.items():
            self.assertEqual(body, native.read_node(self.paths.root(host), path).payload)
        print("native_full_windows_shape", {"largest_logical_projection": max(logical for logical, _ in projection_sizes),
                                            "largest_wire_projection": max(wire for _, wire in projection_sizes),
                                            "largest_real_wire": max(saved_sizes), "receipt_bound": bound})

    def test_recovers_real_prepared_wire1_with_original_inode_evidence(self):
        plan, journal, row = self.interrupted_missing_compensation()
        path = self.state / native_agents._journal_relative(plan.transaction_id)
        # 只把真实 prepared 日志转为旧 producer 的原 JSON 格式；宿主文件、
        # retained/stage inode、ACL 与全部授权前像不作任何伪造或替换。
        path.write_bytes(json_bytes(journal))
        self.assertEqual(1, json.loads(path.read_bytes())["schema_version"])
        recovered = native_agents.recover_global(plan.recovery_ref, context=self.context)
        self.assertEqual("compensated", recovered["status"], recovered["conflicts"])
        actual = native.read_node(self.paths.codex, row["path"])
        self.assertEqual(Node.from_value(row["before"]).payload, actual.payload)
        self.assertEqual(Node.from_value(row["before"]).security, actual.security)
        self.assertEqual(2, json.loads(path.read_bytes())["schema_version"])

    def test_missing_compensation_retained_source_binds_original_write_and_restores(self):
        plan, journal, row = self.interrupted_missing_compensation()
        before = Node.from_value(row["before"])
        step = native_agents._compensation_value(plan.transaction_id, "a" * 32, self.paths.codex,
                                                row["path"], Node(), before)
        with Tree(self.paths.codex) as tree:
            parent, _ = tree.parent(row["path"])
            source, actual = native_agents._retained_permission_source(journal, step, parent)
            self.assertEqual(Path(row["retained"][0]["path"]).name, source)
            self.assertEqual(before.identity[:2], actual.identity[:2])
            self.assertEqual(before.payload, actual.payload)
            # 每个负控使用独立内存副本，不把先前拒绝后的 noop 当成另一根因。
            for defect in ("no_source", "ambiguous", "wrong_after"):
                bad, bad_step = copy.deepcopy(journal), copy.deepcopy(step)
                bad_row = next(item for item in bad["writes"] if item["path"] == row["path"])
                if defect == "no_source":
                    bad_row["retained"] = []
                elif defect == "ambiguous":
                    bad_row["retained"] *= 2
                else:
                    bad_step["after"] = Node("file", b"unauthorized", before.mode).value()
                with self.subTest(defect=defect), self.assertRaises(ValueError):
                    native_agents._retained_permission_source(bad, bad_step, parent)
            self.assertEqual(actual, native.read_node(self.paths.codex, row["retained"][0]["path"]))
        restored = native_agents.recover_global(plan.recovery_ref, context=self.context)
        self.assertEqual("compensated", restored["status"], restored["conflicts"])
        actual = native.read_node(self.paths.codex, row["path"])
        self.assertEqual(before.payload, actual.payload)
        self.assertEqual(before.security, actual.security)

    def test_missing_compensation_rejects_replaced_retained_inode_and_preserves_edit(self):
        plan, journal, row = self.interrupted_missing_compensation()
        held = self.paths.codex / row["retained"][0]["path"]
        old = native.read_node(self.paths.codex, row["retained"][0]["path"])
        # 原件仍存活时先独占创建另一个实体，再原子替换。先 unlink 再创建
        # 会在 Linux 上复用刚释放的 inode，使测试没有真正构造身份漂移。
        candidate = held.with_name(held.name + ".external")
        with candidate.open("xb") as stream:
            stream.write(old.payload)
        candidate_info = candidate.stat()
        candidate_identity = (candidate_info.st_dev, candidate_info.st_ino)
        self.assertNotEqual(old.identity[:2], candidate_identity)
        os.replace(candidate, held)
        replacement = native.read_node(self.paths.codex, row["retained"][0]["path"])
        self.assertNotEqual(old.identity[:2], replacement.identity[:2])
        self.assertEqual(candidate_identity, replacement.identity[:2])
        self.assertEqual(old.payload, replacement.payload)
        result = native_agents.recover_global(plan.recovery_ref, context=self.context)
        self.assertEqual("conflict", result["status"])
        self.assertEqual(replacement, native.read_node(self.paths.codex, row["retained"][0]["path"]))
        self.assertFalse((self.paths.codex / row["path"]).exists())

    def test_preview_batches_verified_sources_without_changing_role_artifacts(self):
        """实际读取固定核心；每轮角色预览只留加载与批读两次完整 entry 验证。"""
        with patch.object(runtime_store, "_validated_entry", wraps=runtime_store._validated_entry) as validated:
            plan = self.preview()
        self.assertTrue(plan.can_apply, plan.summary)
        self.assertEqual(2, validated.call_count, "one load plus one verified batch per preview; no per-role full scan")
        direct = Resources(self.core.root, json_bytes(self.core.binding()), self.core.label, self.core)
        expected = tuple((host, native.role_relative(host, role), native.compile_role(direct, host, role, {}))
                         for host in role_models.HOSTS for role in sorted(role_models.ROLES))
        self.assertEqual(expected, plan.desired)
        paths = tuple(f"roles/{role}.md" for role in sorted(role_models.ROLES)) + ("lib/validate_antigravity_artifacts.py",)
        body = runtime_store.read_core_source(self.core, paths[0])
        with direct.read_view(paths) as view:
            with patch.object(runtime_store, "read_core_source", side_effect=AssertionError("known view member needs no new full read")):
                self.assertEqual(body, view.read(paths[0]))
                self.assertEqual(body, view.read(paths[0]))
            with patch.object(runtime_store, "read_core_source", wraps=runtime_store.read_core_source) as single:
                self.assertTrue(view.read("product/WORKFLOW.md"))
                with self.assertRaises(runtime_store.RuntimeStoreError):
                    view.read("roles/missing.md")
            self.assertEqual(2, single.call_count, "unknown view paths must use the original strict reader")
        with patch.object(runtime_store, "read_core_source", wraps=runtime_store.read_core_source) as single:
            self.assertEqual(body, view.read(paths[0]))
        self.assertEqual(1, single.call_count, "an escaped view must stop reusing bytes after scope exit")
        with patch.object(runtime_store, "_validated_entry", wraps=runtime_store._validated_entry) as repeated:
            again = self.preview()
        self.assertEqual(2, repeated.call_count, "a new preview always repeats full load and batch verification")
        self.assertEqual(plan.desired, again.desired)
        path = self.core.root / paths[0]
        mode = path.stat().st_mode & 0o7777
        try:
            path.chmod(mode | 0o600)
            path.write_bytes(body + b"\ntampered after preview\n")
            path.chmod(mode)
            for action in (lambda: view.read(paths[0]), self.preview, lambda: native_agents.apply_global(plan)):
                with self.assertRaises(runtime_store.RuntimeStoreError):
                    action()
        finally:
            path.chmod(mode | 0o600)
            path.write_bytes(body)
            path.chmod(mode)
        print(f"PORTABLE_PREVIEW_ENTRY_COUNTS: preview={validated.call_count} repeated={repeated.call_count} identical_artifacts={len(expected)}", flush=True)

    def test_admission_uses_current_authority_not_historical_roots_and_detects_deleted_global(self):
        from manager import central_runtime
        older = HostPaths.for_home(self.case / "older-home", environment={})
        older_context = NativeContext(self.state, older)
        native_agents.apply_global(native_agents.preview_global(self.state, self.core.binding(), context=older_context))
        central_runtime.apply(central_runtime.preview(self.state, binding=self.core.binding(), native_context=self.context))
        with patch("pathlib.Path.home", side_effect=AssertionError("准入不得猜HOME")):
            self.assertEqual(native_agents.admission_issues(self.state, hosts=("codex",)), [])
            (self.paths.codex / "agents/xy-backend.toml").unlink()
            issues = native_agents.admission_issues(self.state, hosts=("codex",))
        self.assertTrue(any(row["code"] == "native_ownership_conflict" for row in issues), issues)
        self.assertEqual(native_agents.status(self.state, "codex", context=older_context)["roles"], sorted(role_models.ROLES))
        self.assertTrue(all(set(row) == {"code", "path", "reason"} for row in issues))

    def test_settled_admission_keeps_current_roots_after_failed_activation(self):
        from manager import central_runtime, runtime_policy
        central_runtime.apply(central_runtime.preview(self.state, binding=self.core.binding(), native_context=self.context))
        current_node, current = runtime_policy.current_snapshot(self.state)
        expected_roots = [{"host": host, "native_root": str(self.paths.root(host))} for host in role_models.HOSTS]
        self.assertEqual(current["native_roots"], expected_roots)
        plan = central_runtime.preview(self.state, binding=self.core.binding(), native_context=self.context)
        # 真正运行prepared/native noop/compensate，只在current发布前注入失败；
        # 不替换codec、current_snapshot、native收据或准入查询来模拟组合成功。
        with patch.object(central_runtime, "_verify_applied", side_effect=OSError("fixture before current publication")):
            with self.assertRaisesRegex(OSError, "before current publication"):
                central_runtime.apply(plan)
        authority = json.loads((self.state / runtime_policy.ACTIVATION).read_bytes())
        self.assertEqual(authority["phase"], "compensated")
        self.assertNotEqual(authority["id"], current["generation"])
        self.assertEqual(runtime_policy.current_snapshot(self.state)[0], current_node)
        with patch("pathlib.Path.home", side_effect=AssertionError("准入不得猜HOME")):
            self.assertEqual(native_agents.admission_issues(self.state, hosts=("codex", "claude", "antigravity")), [])
        (self.paths.codex / "agents/xy-backend.toml").unlink()
        self.assertTrue(native_agents.admission_issues(self.state, hosts=("codex",)))

    def test_pending_lifecycle_refuses_global_native_and_preference_writes_without_project_targets(self):
        from manager import central_runtime, runtime_lifecycle, model_preferences
        from manager.catalog import Catalog, Model
        central_runtime.apply(central_runtime.preview(self.state, binding=self.core.binding(), native_context=self.context))
        native_plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "planned-model"}}})
        preference_plan = model_preferences.preview(self.state, None, "codex", {"xy-backend": {"effort": "high"}},
                                                     Catalog("codex", [Model("inherit", "inherit", "fixture")]),
                                                     native_context=self.context)
        self.assertTrue(preference_plan.summary["can_apply"], preference_plan.summary)
        archive = self.case / ".sync-backups/approved-archive"
        archive.mkdir(parents=True)
        (archive / "one.txt").write_text("owned archival bytes")
        lifecycle_plan = runtime_lifecycle.preview(self.state, approved_backup_roots=(archive,), include_cores=False)
        with patch.object(runtime_lifecycle, "_delete_snapshot", side_effect=KeyboardInterrupt("fixture lifecycle interruption")):
            with self.assertRaises(KeyboardInterrupt):
                runtime_lifecycle.apply(lifecycle_plan)
        self.assertEqual(json.loads((self.state / runtime_lifecycle.RELATIVE).read_bytes())["phase"], "prepared")
        native_before = (self.paths.codex / "agents/xy-backend.toml").read_bytes()
        prefs_before = native.read_node(self.state, "preferences/role-models.json")
        journals_before = tuple(sorted((self.state / "native-agents/transactions").glob("*.json")))
        pref_journals_before = tuple(sorted((self.state / "preferences/transactions").glob("*.json")))
        with self.assertRaisesRegex(ValueError, "生命周期事务尚未结算"):
            native_agents.apply_global(native_plan)
        with self.assertRaisesRegex(ValueError, "生命周期事务尚未结算"):
            model_preferences.apply(preference_plan)
        self.assertEqual((self.paths.codex / "agents/xy-backend.toml").read_bytes(), native_before)
        self.assertEqual(native.read_node(self.state, "preferences/role-models.json"), prefs_before)
        self.assertEqual(tuple(sorted((self.state / "native-agents/transactions").glob("*.json"))), journals_before)
        self.assertEqual(tuple(sorted((self.state / "preferences/transactions").glob("*.json"))), pref_journals_before)
        runtime_lifecycle.recover(self.state)

    def test_explicit_paths_ignore_ambient_environment_and_custom_state_requires_paths(self):
        with patch.dict(os.environ, {"CODEX_HOME": "/untrusted/codex", "CLAUDE_CONFIG_DIR": "/untrusted/claude"}):
            self.assertEqual(HostPaths.for_home(self.home), self.paths)
        self.assertEqual(self.paths.antigravity, self.home / ".gemini/config")
        self.assertEqual(HostPaths.for_home(self.home, environment={"CODEX_HOME": str(self.case / "custom")}).codex,
                         self.case / "custom")
        with self.assertRaises(ValueError):
            NativeContext.for_state(self.case / "custom-state")

    def test_preview_cancel_zero_write_apply_complete_roles_no_preload_and_noop_zero_write(self):
        before = tuple(self.case.rglob("*"))
        plan = self.preview()
        self.assertEqual(tuple(self.case.rglob("*")), before)
        self.assertEqual(plan.hosts, role_models.HOSTS)
        self.assertEqual(len(plan.summary["changes"]), 21)
        receipt = native_agents.apply_global(plan)
        self.assertEqual(native_agents.verify_global(plan.recovery_ref, context=self.context), [])
        self.assertTrue(receipt["applied"])
        self.assertEqual(native_agents.verified_hosts(self.state, context=self.context), role_models.HOSTS)
        for host in role_models.HOSTS:
            for role in role_models.ROLES:
                body = (self.paths.root(host) / native.role_relative(host, role)).read_bytes()
                native.validate_descriptor(body, host, role)
                self.assertIn(b"Before any project check", body)
                self.assertNotIn(b"skills:", body)
            self.assertFalse((self.paths.root(host) / "AGENTS.md").exists())
        next_plan = self.preview()
        state_before = {(str(path), path.stat().st_mtime_ns) for path in (self.state / "native-agents").rglob("*")}
        self.assertEqual(native_agents.apply_global(next_plan)["status"], "noop")
        self.assertEqual(state_before, {(str(path), path.stat().st_mtime_ns) for path in (self.state / "native-agents").rglob("*")})

    def test_marker_and_declared_name_alias_cannot_take_ownership(self):
        root = self.paths.codex / "agents"
        root.mkdir(parents=True)
        (root / "alias.toml").write_text('name="xy-backend"\ndeveloper_instructions="user"\n')
        plan = self.preview(hosts=("codex",))
        self.assertFalse(plan.can_apply)
        self.assertTrue(any("相同" in row["reason"] for row in plan.conflicts))
        (root / "alias.toml").unlink()
        (root / "xy-backend.toml").write_text('# agent-workflow-central-project\nname="xy-backend"\n')
        self.assertFalse(self.preview(hosts=("codex",)).can_apply)

    def test_managed_manual_delete_and_preview_drift_remain_conflicts(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        target.unlink()
        self.assertFalse(self.preview(hosts=("codex",)).can_apply)
        self.assertNotIn("codex", native_agents.verified_hosts(self.state, context=self.context))
        plan = self.preview(hosts=("claude",))
        root = self.paths.claude / "agents"
        root.mkdir(parents=True)
        (root / "unrelated.md").write_text('---\nname: user-role\n---\nuser\n')
        with self.assertRaises(ValueError):
            native_agents.apply_global(plan)
        self.assertFalse((root / "xy-backend.md").exists())

    def test_second_state_cannot_take_same_native_root(self):
        self.install(hosts=("codex",))
        state = self.case / "second-state"
        core = runtime_store.import_core(self.source, state)
        context = NativeContext(state, self.paths)
        plan = native_agents.preview_global(state, core.binding(), context=context, hosts=("codex",))
        self.assertFalse(plan.can_apply)
        self.assertFalse((state / "native-agents").exists())

    def test_concurrent_plans_publish_once_and_recovery_is_idempotent(self):
        plans = (self.preview(hosts=("codex",)), self.preview(hosts=("codex",)))
        def run(plan):
            try:
                return native_agents.apply_global(plan)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(executor.map(run, plans))
        self.assertEqual(sum(row is not None and row["applied"] for row in receipts), 1)
        receipt = next(row for row in receipts if row is not None)
        reference = receipt["recovery_ref"]
        result = native_agents.compensate_global(reference, context=self.context)
        self.assertEqual(result["status"], "compensated", result)
        self.assertEqual(native_agents.recover_global(reference, context=self.context)["status"], "compensated")
        self.assertFalse((self.paths.codex / "agents/xy-backend.toml").exists())

    def test_recovery_preserves_unknown_replacement_and_reports_exact_identity(self):
        receipt = self.install(hosts=("claude",))
        target = self.paths.claude / "agents/xy-backend.md"
        body = target.read_bytes()
        target.unlink()
        target.write_bytes(body)
        issues = native_agents.verify_global(receipt["recovery_ref"], context=self.context)
        self.assertTrue(issues)
        result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(target.read_bytes(), body)

    def _assert_compensation_window_keeps_replacement(self, *, before_file):
        receipt = self.install(hosts=("codex",))
        if before_file:
            receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                        preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
        target = self.paths.codex / "agents/xy-backend.toml"
        body = target.read_bytes()
        expected_inode = target.stat().st_ino
        original_rename = native_agents.os.rename
        replaced = []
        def replace_at_final_isolation(source, destination, **kwargs):
            # 钩住真实rename系统调用边界；既不替换补偿业务函数，也不根据新
            # 实现的辅助方法判断时机。旧二元CAS与完整Node方案都必须经历此窗口。
            if source == target.name and not replaced:
                replacement = target.with_name(".user-compensation-replacement")
                with replacement.open("xb") as stream:
                    stream.write(body)
                replacement.chmod(target.stat().st_mode & 0o7777)
                foreign = replacement.stat()
                self.assertNotEqual(foreign.st_ino, expected_inode)
                os.replace(replacement, target)
                replaced.append((foreign.st_dev, foreign.st_ino))
            return original_rename(source, destination, **kwargs)
        with patch.object(native_agents.os, "rename", side_effect=replace_at_final_isolation):
            result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        print("COMPENSATION_REPLACEMENT_WINDOW", "file" if before_file else "missing", result["status"], replaced)
        self.assertTrue(replaced)
        self.assertTrue(target.exists(), "补偿不得删除窗口中出现的未知同内容inode")
        self.assertEqual((target.stat().st_dev, target.stat().st_ino), replaced[0])
        self.assertEqual(target.read_bytes(), body)
        self.assertEqual(result["status"], "conflict")
        journal_path = self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")
        journal = native_journal.decode(journal_path.read_bytes())
        self.assertTrue(any(row.get("path") == "agents/xy-backend.toml" for row in journal["conflicts"]))
        self.assertIn(str(replaced[0][1]), json.dumps(journal))
        self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "conflict")
        self.assertEqual((target.stat().st_dev, target.stat().st_ino), replaced[0])
        self.assertEqual(target.read_bytes(), body)

    def test_compensation_file_restore_rejects_same_content_inode_at_final_isolation(self):
        self._assert_compensation_window_keeps_replacement(before_file=True)

    def test_compensation_delete_rejects_same_content_inode_at_final_isolation(self):
        self._assert_compensation_window_keeps_replacement(before_file=False)

    def test_compensation_resumes_forward_interruption_before_publication(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        original_body = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        original_link = native_agents.os.link
        interrupted = []
        def stop_before_link(source, destination, **kwargs):
            if str(source).startswith(".awf-native-stage-") and destination == target.name and not interrupted:
                interrupted.append(True)
                raise OSError("fixture native publication interrupted")
            return original_link(source, destination, **kwargs)
        with patch.object(native_agents.os, "link", side_effect=stop_before_link):
            with self.assertRaisesRegex(OSError, "publication interrupted"):
                native_agents.apply_global(plan)
        self.assertTrue(interrupted)
        self.assertFalse(target.exists())
        result = native_agents.recover_global(plan.recovery_ref, context=self.context)
        self.assertEqual(result["status"], "compensated", result)
        self.assertEqual(target.read_bytes(), original_body)
        self.assertEqual(native_agents.verified_hosts(self.state, context=self.context), ("codex",))
        self.assertEqual(native_agents.recover_global(plan.recovery_ref, context=self.context)["status"], "compensated")

    def test_compensation_owner_reconciliation_rejects_same_content_inode(self):
        self.install(hosts=("codex",))
        receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                  preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
        owner = self.paths.codex / native.OWNER
        original_rename = native_agents.os.rename
        visits, replacement = [], []
        def replace_at_reconciliation(source, destination, **kwargs):
            if source == native.OWNER:
                visits.append(True)
                if len(visits) == 2:
                    body = owner.read_bytes()
                    alternate = owner.with_name(".user-owner-replacement")
                    with alternate.open("xb") as stream:
                        stream.write(body)
                    alternate.chmod(owner.stat().st_mode & 0o7777)
                    info = alternate.stat()
                    os.replace(alternate, owner)
                    replacement.append((info.st_dev, info.st_ino, body))
            return original_rename(source, destination, **kwargs)
        with patch.object(native_agents.os, "rename", side_effect=replace_at_reconciliation):
            result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(len(replacement), 1)
        self.assertEqual(result["status"], "conflict", result)
        self.assertEqual((owner.stat().st_dev, owner.stat().st_ino), replacement[0][:2])
        self.assertEqual(owner.read_bytes(), replacement[0][2])
        self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "conflict")
        self.assertEqual((owner.stat().st_dev, owner.stat().st_ino), replacement[0][:2])

    def test_compensation_preserves_forward_retained_fd_edits(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        descriptor = os.open(target, os.O_WRONLY | os.O_APPEND)
        try:
            receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                      preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
            published_body = target.read_bytes()
            os.write(descriptor, b"\n# late original fd save\n")
            result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        finally:
            os.close(descriptor)
        self.assertEqual(result["status"], "conflict", result)
        self.assertEqual(target.read_bytes(), published_body)
        journal = native_journal.decode((self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")).read_bytes())
        row = next(row for row in journal["writes"] if row["path"] == "agents/xy-backend.toml")
        retained = self.paths.codex / row["retained"][0]["path"]
        self.assertIn(b"late original fd save", retained.read_bytes())
        self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "conflict")
        self.assertIn(b"late original fd save", retained.read_bytes())

    def test_compensation_resumes_persisted_exact_result_after_interruption(self):
        for before_file in (False, True):
            with self.subTest(before_file=before_file):
                self.paths = HostPaths.for_home(self.case / ("file-home" if before_file else "missing-home"), environment={})
                self.context = NativeContext(self.state, self.paths)
                receipt = self.install(hosts=("codex",))
                if before_file:
                    receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                              preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
                target = self.paths.codex / "agents/xy-backend.toml"
                original_save = native_agents._save
                interrupted = []
                def stop_after_exact_result(state, journal):
                    result = original_save(state, journal)
                    if not interrupted and any(step["path"] == "agents/xy-backend.toml" and step["result"] is not None
                                               for step in journal.get("compensations", [])):
                        interrupted.append(True)
                        raise KeyboardInterrupt("fixture compensation after exact result")
                    return result
                with patch.object(native_agents, "_save", side_effect=stop_after_exact_result):
                    with self.assertRaisesRegex(KeyboardInterrupt, "after exact result"):
                        native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
                self.assertTrue(interrupted)
                journal = native_journal.decode((self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")).read_bytes())
                saved = next(step for step in reversed(journal["compensations"]) if step["path"] == "agents/xy-backend.toml")
                self.assertEqual(native.read_node(self.paths.codex, "agents/xy-backend.toml"), Node.from_value(saved["result"]))
                result = native_agents.recover_global(receipt["recovery_ref"], context=self.context)
                self.assertEqual(result["status"], "compensated", result["conflicts"])
                self.assertEqual(target.exists(), before_file)
                before_noop = native.read_node(self.paths.codex, "agents/xy-backend.toml")
                self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")
                self.assertEqual(native.read_node(self.paths.codex, "agents/xy-backend.toml"), before_noop)

    def test_compensation_resumes_owned_filesystem_boundaries_without_new_steps(self):
        # 在实际系统调用完成后中断，保留磁盘中真实的隔离/双链接/发布状态。
        # missing没有stage，分别验证隔离未落记录与隔离已落记录两条边界。
        for before_file, boundary in ((False, "isolated"), (False, "isolated_saved"),
                                      (True, "isolated"), (True, "linked"), (True, "stage_removed")):
            with self.subTest(before_file=before_file, boundary=boundary):
                self.paths = HostPaths.for_home(self.case / (str(before_file) + "-" + boundary), environment={})
                self.context = NativeContext(self.state, self.paths)
                receipt = self.install(hosts=("codex",))
                original_body = (self.paths.codex / "agents/xy-backend.toml").read_bytes()
                if before_file:
                    receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                              preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
                target = self.paths.codex / "agents/xy-backend.toml"
                interrupted = []
                real_rename, real_link, real_unlink, real_save = native_agents.os.rename, native_agents.os.link, native_agents.os.unlink, native_agents._save
                def stop(point):
                    if point == boundary and not interrupted:
                        interrupted.append(point)
                        raise KeyboardInterrupt("fixture owned boundary " + point)
                def rename(source, destination, **kwargs):
                    result = real_rename(source, destination, **kwargs)
                    if source == target.name and str(destination).startswith(".native-rollback-"):
                        stop("isolated")
                    return result
                def link(source, destination, **kwargs):
                    result = real_link(source, destination, **kwargs)
                    if str(source).startswith(".awf-native-restore-") and destination == target.name:
                        stop("linked")
                    return result
                def unlink(path, **kwargs):
                    result = real_unlink(path, **kwargs)
                    if str(path).startswith(".awf-native-restore-"):
                        # 其他metadata也会使用stage；只在backend已恢复时中断。
                        if target.exists() and target.read_bytes() == original_body:
                            stop("stage_removed")
                    return result
                def save(state, journal):
                    result = real_save(state, journal)
                    if any(step["path"] == "agents/xy-backend.toml" and step["isolated"] is not None
                           and step["result"] is None for step in journal.get("compensations", [])):
                        stop("isolated_saved")
                    return result
                with patch.object(native_agents.os, "rename", side_effect=rename), patch.object(native_agents.os, "link", side_effect=link), patch.object(native_agents.os, "unlink", side_effect=unlink), patch.object(native_agents, "_save", side_effect=save):
                    with self.assertRaisesRegex(KeyboardInterrupt, "owned boundary"):
                        native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
                self.assertEqual(interrupted, [boundary])
                journal_path = self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")
                before = native_journal.decode(journal_path.read_bytes())
                backend_steps = [step for step in before["compensations"] if step["path"] == "agents/xy-backend.toml"]
                self.assertEqual(len(backend_steps), 1)
                self.assertIsNone(backend_steps[0]["result"])
                result = native_agents.recover_global(receipt["recovery_ref"], context=self.context)
                print("COMPENSATION_OWNED_BOUNDARY", before_file, boundary, result["status"])
                self.assertEqual(result["status"], "compensated", result["conflicts"])
                self.assertEqual(target.exists(), before_file)
                if before_file:
                    self.assertEqual(target.read_bytes(), original_body)
                    self.assertEqual(native_agents.verified_hosts(self.state, context=self.context), ("codex",))
                after = native_journal.decode(journal_path.read_bytes())
                self.assertEqual(len([step for step in after["compensations"] if step["path"] == "agents/xy-backend.toml"]), 1)
                stable = native.read_node(self.paths.codex, "agents/xy-backend.toml")
                self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")
                self.assertEqual(native.read_node(self.paths.codex, "agents/xy-backend.toml"), stable)

    def test_compensation_recovery_preserves_unrecorded_stage_and_unknown_links(self):
        for boundary in ("unrecorded_stage", "third_link", "replaced_result"):
            with self.subTest(boundary=boundary):
                self.paths = HostPaths.for_home(self.case / boundary, environment={})
                self.context = NativeContext(self.state, self.paths)
                self.install(hosts=("codex",))
                receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                          preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
                target = self.paths.codex / "agents/xy-backend.toml"
                real_link, real_unlink, real_save = native_agents.os.link, native_agents.os.unlink, native_agents._save
                stopped = []
                def stop():
                    stopped.append(True)
                    raise KeyboardInterrupt("fixture unowned boundary")
                def save(state, journal):
                    if boundary == "unrecorded_stage" and any(step["path"] == "agents/xy-backend.toml" and step["staged"] is not None
                                                               for step in journal.get("compensations", [])):
                        stop()  # stage已创建，但其完整Node尚未写进journal。
                    return real_save(state, journal)
                def link(source, destination, **kwargs):
                    result = real_link(source, destination, **kwargs)
                    if boundary == "third_link" and str(source).startswith(".awf-native-restore-") and destination == target.name:
                        stop()
                    return result
                def unlink(path, **kwargs):
                    result = real_unlink(path, **kwargs)
                    if boundary == "replaced_result" and str(path).startswith(".awf-native-restore-") and target.exists() and b'new-model' not in target.read_bytes():
                        stop()
                    return result
                with patch.object(native_agents, "_save", side_effect=save), patch.object(native_agents.os, "link", side_effect=link), patch.object(native_agents.os, "unlink", side_effect=unlink):
                    with self.assertRaisesRegex(KeyboardInterrupt, "unowned boundary"):
                        native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
                self.assertEqual(stopped, [True])
                journal = native_journal.decode((self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")).read_bytes())
                step = next(step for step in journal["compensations"] if step["path"] == "agents/xy-backend.toml")
                if boundary == "unrecorded_stage":
                    self.assertIsNone(step["staged"])
                    protected = self.paths.codex / step["stage"]
                elif boundary == "third_link":
                    protected = self.case / "foreign-hardlink"
                    os.link(target, protected)
                    self.assertEqual(target.stat().st_nlink, 3)
                else:
                    replacement = target.with_name(".foreign-result")
                    replacement.write_bytes(target.read_bytes())
                    replacement.chmod(target.stat().st_mode & 0o7777)
                    os.replace(replacement, target)
                    protected = target
                identity = (protected.stat().st_dev, protected.stat().st_ino, protected.stat().st_nlink)
                body = protected.read_bytes()
                for attempt in range(2):
                    result = native_agents.recover_global(receipt["recovery_ref"], context=self.context)
                    print("COMPENSATION_UNOWNED_BOUNDARY", boundary, attempt, result["status"])
                    self.assertEqual(result["status"], "conflict", result["conflicts"])
                    self.assertEqual((protected.stat().st_dev, protected.stat().st_ino, protected.stat().st_nlink), identity)
                    self.assertEqual(protected.read_bytes(), body)

    def test_compensation_resumes_owner_projection_isolation_before_result(self):
        self.install(hosts=("codex",))
        receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                  preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
        real_rename = native_agents.os.rename
        visits = []
        def rename(source, destination, **kwargs):
            result = real_rename(source, destination, **kwargs)
            if source == native.OWNER:
                visits.append(True)
                if len(visits) == 2:
                    # 第一轮恢复旧owner，第二轮重建恢复后角色inode的身份投影。
                    raise KeyboardInterrupt("fixture owner projection isolated")
            return result
        with patch.object(native_agents.os, "rename", side_effect=rename):
            with self.assertRaisesRegex(KeyboardInterrupt, "owner projection isolated"):
                native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(len(visits), 2)
        self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")
        self.assertEqual(native_agents.verified_hosts(self.state, context=self.context), ("codex",))
        self.assertEqual(native_agents.recover_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")

    def test_compensation_log_rejects_foreign_paths_and_incomplete_node_identity(self):
        self.install(hosts=("codex",))
        receipt = native_agents.apply_global(self.preview(hosts=("codex",),
                  preferences={"codex": {"xy-backend": {"model": "new-model"}}}))
        self.assertEqual(native_agents.compensate_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")
        journal_path = self.state / "native-agents/transactions" / (receipt["transaction_id"] + ".json")
        original = native_journal.decode(journal_path.read_bytes())
        outside = self.case / "outside.txt"
        outside.write_bytes(b"preserve foreign bytes")
        before = native.read_node(self.paths.codex, "agents/xy-backend.toml")
        for invalid in ("path", "identity"):
            with self.subTest(invalid=invalid):
                journal = json.loads(json.dumps(original))
                step = next(step for step in journal["compensations"] if step["stage"] is not None)
                if invalid == "path":
                    step["stage"] = "../../outside.txt"
                else:
                    step["expected"]["identity"] = []
                journal_path.write_bytes(json_bytes(journal))
                with self.assertRaises(ValueError):
                    native_agents.recover_global(receipt["recovery_ref"], context=self.context)
                self.assertEqual(outside.read_bytes(), b"preserve foreign bytes")
                self.assertEqual(native.read_node(self.paths.codex, "agents/xy-backend.toml"), before)

    def test_update_compensation_restores_prior_ownership_and_preserves_applied_evidence(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        before = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        receipt = native_agents.apply_global(plan)
        self.assertNotEqual(target.read_bytes(), before)
        result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(result["status"], "compensated", result)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(native_agents.verified_hosts(self.state, context=self.context), ("codex",))
        self.assertEqual(native_agents.compensate_global(receipt["recovery_ref"], context=self.context)["status"], "compensated")

    def test_noop_ref_witness_verifies_without_journal_and_rejects_replacement(self):
        self.install(hosts=("codex",))
        plan = self.preview(hosts=("codex",))
        receipt = native_agents.apply_global(plan)
        self.assertEqual(receipt["status"], "noop")
        reference = receipt["recovery_ref"]
        journal = self.state / "native-agents/transactions" / (plan.transaction_id + ".json")
        self.assertFalse(journal.exists())
        self.assertEqual(native_agents.verify_global(reference, context=self.context), [])
        target = self.paths.codex / "agents/xy-backend.toml"
        body = target.read_bytes()
        target.unlink()
        target.write_bytes(body)
        self.assertTrue(native_agents.verify_global(reference, context=self.context))
        self.assertEqual(native_agents.recover_global(reference, context=self.context)["status"], "conflict")
        self.assertEqual(target.read_bytes(), body)
        self.assertFalse(journal.exists())

    def test_publish_rejects_same_content_inode_replacement_after_stage(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        body = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        original = native_agents._save
        replaced = False
        def replace_after_stage(state, journal):
            nonlocal replaced
            original(state, journal)
            if not replaced and any(row["path"] == "agents/xy-backend.toml" and row.get("staged") is not None
                                    and row["published"] is None for row in journal["writes"]):
                replaced = True
                target.unlink()
                target.write_bytes(body)
        with patch.object(native_agents, "_save", side_effect=replace_after_stage):
            with self.assertRaisesRegex(ValueError, "最终隔离"):
                native_agents.apply_global(plan)
        self.assertTrue(replaced)
        self.assertEqual(target.read_bytes(), body)
        self.assertEqual(native_agents.compensate_global(plan.recovery_ref, context=self.context)["status"], "conflict")
        self.assertEqual(target.read_bytes(), body)

    def test_publish_rejects_same_content_replacement_between_guard_and_capture(self):
        self.install(hosts=("codex",))
        target = self.paths.codex / "agents/xy-backend.toml"
        body = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        original = native_agents._publish
        replaced = False
        def replace_before_capture(state, journal, root, relative, after, *, expected):
            nonlocal replaced
            if relative == "agents/xy-backend.toml" and not replaced:
                replaced = True
                target.unlink()
                target.write_bytes(body)
            return original(state, journal, root, relative, after, expected=expected)
        with patch.object(native_agents, "_publish", side_effect=replace_before_capture):
            with self.assertRaisesRegex(ValueError, "固定预览"):
                native_agents.apply_global(plan)
        self.assertTrue(replaced)
        self.assertEqual(target.read_bytes(), body)

    def test_declared_alias_with_yaml_comment_is_a_conflict(self):
        root = self.paths.claude / "agents"
        root.mkdir(parents=True)
        (root / "alias.md").write_text('---\nname: "xy-backend" # user comment\n---\nuser\n')
        self.assertFalse(self.preview(hosts=("claude",)).can_apply)

    def test_publish_rejects_native_root_replacement_after_guard(self):
        self.install(hosts=("codex",))
        root = self.paths.codex
        target = root / "agents/xy-backend.toml"
        body = target.read_bytes()
        plan = self.preview(hosts=("codex",), preferences={"codex": {"xy-backend": {"model": "new-model"}}})
        original = native_agents._publish
        replaced = False
        def replace_root_before_capture(state, journal, native_root, relative, after, *, expected):
            nonlocal replaced
            if relative == "agents/xy-backend.toml" and not replaced:
                replaced = True
                moved = self.home / "moved-codex"
                root.rename(moved)
                root.mkdir()
                for child in moved.iterdir():
                    child.rename(root / child.name)
            return original(state, journal, native_root, relative, after, expected=expected)
        with patch.object(native_agents, "_publish", side_effect=replace_root_before_capture):
            with self.assertRaisesRegex(ValueError, "物理根"):
                native_agents.apply_global(plan)
        self.assertTrue(replaced)
        self.assertEqual(target.read_bytes(), body)

    def test_recovery_rejects_replaced_native_root_even_if_role_inodes_are_same(self):
        receipt = self.install(hosts=("codex",))
        original = self.paths.codex
        moved = self.home / "old-codex"
        original.rename(moved)
        original.mkdir()
        for child in moved.iterdir():
            child.rename(original / child.name)
        target = original / "agents/xy-backend.toml"
        before = target.read_bytes()
        result = native_agents.compensate_global(receipt["recovery_ref"], context=self.context)
        self.assertEqual(result["status"], "conflict")
        self.assertTrue(any(row.get("type") == "native_root_conflict" for row in result["conflicts"]))
        self.assertEqual(target.read_bytes(), before)

    def test_launcher_init_parser_distinguishes_command_from_option_value(self):
        from lib.central.runtime_project import launcher_source
        namespace = {"__name__": "launcher_contract"}
        exec(compile(launcher_source(), "<central-launcher>", "exec"), namespace)
        classify = namespace["helper_creates_task"]
        self.assertTrue(classify(["helper", "lib/task_graph_cli.py", "--input", "graph.json", "init"]))
        self.assertFalse(classify(["helper", "lib/task_graph_cli.py", "validate", "--task-id", "init"]))

    def test_role_frontmatter_crlf_preserves_frozen_bytes_and_strict_permissions(self):
        """实际导入 CRLF 来源并运行三宿主消费者；坏策略不能借正文或换行扩大权限。"""
        baseline = self.preview()
        originals = {role: (self.source / f"roles/{role}.md").read_bytes() for role in role_models.ROLES}
        try:
            crlf = {role: body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                    for role, body in originals.items()}
            for role, body in crlf.items():
                (self.source / f"roles/{role}.md").write_bytes(body)
            candidate = runtime_store.import_core(self.source, self.state)
            self.assertNotEqual(self.core.content_id, candidate.content_id)
            manifest = json.loads((candidate.root.parent / "manifest.json").read_bytes())
            for role, body in crlf.items():
                path = f"roles/{role}.md"
                self.assertEqual(body, runtime_store.read_core_source(candidate, path))
                row = next(row for row in manifest["files"] if row["path"] == path)
                self.assertEqual(hashlib.sha256(body).hexdigest(), row["sha256"])
            plan = native_agents.preview_global(self.state, candidate.binding(), context=self.context)
            self.assertTrue(plan.can_apply, plan.summary)
            self.assertEqual(baseline.desired, plan.desired,
                             "LF/CRLF must compile identical existing host permissions and bootstrap text")
            native_agents.apply_global(plan)
            for host, path, expected in plan.desired:
                actual = native.read_node(self.paths.root(host), path)
                self.assertEqual(expected, actual.payload)
                native.validate_descriptor(actual.payload, host, Path(path).stem)
        finally:
            for role, body in originals.items():
                (self.source / f"roles/{role}.md").write_bytes(body)
        role = "xy-qa"
        original = originals[role].replace(b"\r\n", b"\n")
        absent = original.replace(b"toolsets: [read]\n", b"")
        invalid = (absent, absent + b"\ntoolsets: [write]\n",
                   original.replace(b"toolsets: [read]", b"toolsets: [read]\ntoolsets: [read]"),
                   original.replace(b"toolsets: [read]", b"toolsets: [read, write]"),
                   original.replace(b"toolsets: [read]", b"toolsets: [unknown-mcp]"),
                   original.replace(b"\n---\n", b"\n--\n", 1),
                   original.replace(b"---\n", b"---\r", 1))
        preview = Resources(self.source, json_bytes(self.core.binding()), self.core.label)
        try:
            for body in invalid:
                for line_end in (body, body.replace(b"\n", b"\r\n")):
                    (self.source / f"roles/{role}.md").write_bytes(line_end)
                    for host in role_models.HOSTS:
                        with self.subTest(host=host, policy_sha=hashlib.sha256(line_end).hexdigest()), \
                                self.assertRaisesRegex(ValueError, "角色.*toolsets"):
                            native.compile_role(preview, host, role, {})
        finally:
            (self.source / f"roles/{role}.md").write_bytes(originals[role])

    def test_native_descriptor_real_validators_accept_bootstrap_and_reject_permission_expansion(self):
        from lib.hosts.validate_claude_artifacts import validate_agent as validate_claude
        from lib.validate_antigravity_artifacts import parse_agent_frontmatter, validate_agent as validate_agy
        self.install()
        claude = self.paths.claude / "agents/xy-qa.md"
        errors = []
        validate_claude(claude, "xy-qa", self.case, errors)
        self.assertEqual(errors, [])
        agy = self.paths.antigravity / "agents/xy-qa.md"
        body = agy.read_text()
        fields, _ = parse_agent_frontmatter(body, agy, errors)
        self.assertNotIn("skills", fields)
        validate_agy(agy, body, "xy-qa", set(), errors)
        self.assertEqual(errors, [])
        unsafe = body.replace("  - view_file", "  - write_to_file", 1)
        with self.assertRaises(ValueError):
            native.validate_descriptor(unsafe.encode(), "antigravity", "xy-qa")
        with self.assertRaises(ValueError):
            native.validate_descriptor(body.replace("model: inherit", "model:").encode(), "antigravity", "xy-qa")
        errors = []
        parse_agent_frontmatter(unsafe, agy, errors)
        self.assertTrue(errors)
        # 旧/普通静态合同继续要求skills，不能靠移除marker将规则整体放宽。
        errors = []
        parse_agent_frontmatter(body.replace("agent-workflow-central-project", "user-agent"), agy, errors)
        self.assertTrue(any("skills" in item for item in errors))
        codex = (self.paths.codex / "agents/xy-qa.toml").read_bytes()
        self.assertNotIn(b"sandbox_mode", codex)
        self.assertIn(b"Parent native permissions still apply", codex)

    def test_project_sparse_only_after_verified_global_and_single_field_is_complete(self):
        project = self.case / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.1.0"\n')
        resources = Resources(self.core.root, json_bytes(self.core.binding()), self.core.label, self.core)
        desired, profile = prepare(resources, project, Node(), ("codex",), owned_links=set())
        self.assertIn(".codex/agents/xy-backend.toml", desired)
        self.install()
        desired, profile = prepare(resources, project, Node(), ("codex",), owned_links=set(), native_context=self.context)
        self.assertFalse(any(purpose == "role" for _, purpose in desired.values()))
        body = desired[CONFIG][0].payload
        body = role_models.update(body.decode(), {"codex": {"xy-backend": {"model": "project-model"}}}).encode()
        desired, _ = prepare(resources, project, Node("file", body, 0o644), ("codex",), owned_links=set(),
                             native_context=self.context, preferences={"codex": {"xy-backend": {"effort": "high"}}})
        node = desired[".codex/agents/xy-backend.toml"][0]
        native.validate_descriptor(node.payload, "codex", "xy-backend")
        self.assertIn(b'model = "project-model"', node.payload)
        self.assertIn(b'model_reasoning_effort = "high"', node.payload)
        desired, _ = prepare(resources, project, Node("file", body, 0o644), ("codex",), owned_links=set(),
                             native_context=self.context, preferences={"codex": {"xy-backend": {"effort": "max"}}})
        self.assertIn(b'model_reasoning_effort = "max"', desired[".codex/agents/xy-backend.toml"][0].payload)


class NativeControllerBoundaryTest(unittest.TestCase):
    """通过真实清单导入和生成launcher验证调用边界，不伪造load_core结果。"""

    def bridge_fixture(self, root, declaration):
        from lib.central.runtime_project import LAUNCHER, launcher_source, project_key
        source = fixtures.CentralCliIntegrationTest.create_source(root)
        # 最小无gate桥故意会在main入口和init里写标记；若薄入口缺少资格门，
        # 黑盒就会观察到越过调用边界。只改导入前source，不修改固定core/manifest。
        body = (declaration + "\n" if declaration else "") + """from pathlib import Path
import runpy
import sys

def main(*, project, state):
    args = list(sys.argv[1:])
    if args[:1] == ['--binding']:
        args = args[2:]
    core = Path(__file__).resolve().parents[1]
    (project / 'bridge-main-called').write_text('called')
    if args[:1] == ['read']:
        print((core / args[1]).read_text(), end='')
    elif args[:1] == ['helper']:
        runpy.run_path(str(core / args[1]), run_name='__main__')
    else:
        print('fixture control called')
    return 0
"""
        (source / "lib/runtime_bridge.py").write_text(body)
        (source / "lib/task_graph_init.py").write_text("from pathlib import Path\nPath('fixture-init-called').write_text('called')\n")
        (source / "lib/fixture_read.py").write_text("print('fixture ordinary helper read')\n")
        state = root / "state"
        core = runtime_store.import_core(source, state)
        project = root / "project"
        (project / ".agent-workflow").mkdir(parents=True)
        (project / LAUNCHER).write_bytes(launcher_source())
        (state / "bindings").mkdir()
        (state / "bindings" / (project_key(project) + ".json")).write_bytes(json_bytes({
            "schema_version": 1, "project_root": str(project), "runtime_binding": core.binding(),
            "used_bindings": [core.binding()]}))
        (state / "central").mkdir()
        current = state / "central/current.json"
        current.write_bytes(json_bytes({"schema_version": 1, "runtime_binding": core.binding(),
                                      "previous_binding": None, "generation": "a" * 32, "native_roots": []}))
        current.chmod(0o600)
        environment = {key: value for key, value in os.environ.items() if key not in {
            "PYTHONPATH", "PYTHONHOME", "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
            "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"}}
        environment.update({"HOME": str(root / "home"), "AGENT_WORKFLOW_STATE_DIR": str(state),
                            "AGENT_WORKFLOW_PYTHON": sys.executable})
        def invoke(*arguments):
            result = subprocess.run(["bash", str(Path(__file__).resolve().parents[1] / "lib/python_runtime.sh"), "-B", "-X", "utf8",
                                     str(project / LAUNCHER), *arguments], cwd=project, env=environment,
                                    capture_output=True, text=True, timeout=30)
            print("CONTROLLER_BOUNDARY", repr(declaration), arguments[0], "exit=" + str(result.returncode))
            print(result.stdout, end="")
            print(result.stderr, end="")
            return result
        return project, core, current, invoke

    def test_thin_control_refuses_unqualified_bridge_before_main_and_keeps_old_reads(self):
        with tempfile.TemporaryDirectory(prefix="native-controller-", dir=os.environ.get("AWF_TEST_SCRATCH")) as raw:
            for number, declaration in enumerate(("", "CENTRAL_CONTROL_PROTOCOL = 0", "CENTRAL_CONTROL_PROTOCOL = 2",
                                                "CENTRAL_CONTROL_PROTOCOL = True", 'CENTRAL_CONTROL_PROTOCOL = "1"')):
                with self.subTest(declaration=declaration):
                    root = Path(raw).resolve() / str(number)
                    root.mkdir()
                    project, core, current, invoke = self.bridge_fixture(root, declaration)
                    explicit = ("--binding", json.dumps(core.binding()))
                    # 即使手工合法current指向无gate桥，check/new_task和两种init
                    # 都必须在其main之前拒绝，不让旧桥执行任何任务创建逻辑。
                    for arguments in (("check",), ("new_task",),
                                      explicit + ("helper", "lib/task_graph_init.py"),
                                      explicit + ("helper", "lib/task_graph_cli.py", "--input", "graph.json", "init")):
                        result = invoke(*arguments)
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("控制协议", result.stderr)
                        self.assertFalse((project / "bridge-main-called").exists())
                        self.assertFalse((project / "fixture-init-called").exists())
                    # 普通显式旧pin读与非init helper不依赖current/控制资格；
                    # 损坏current也不能使这两个只读入口失去原pin可用性。
                    current.write_bytes(b"broken current")
                    result = invoke(*explicit, "read", "product/WORKFLOW.md")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("固定版本一", result.stdout)
                    result = invoke(*explicit, "helper", "lib/fixture_read.py")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("fixture ordinary helper read", result.stdout)
                    self.assertFalse((project / "fixture-init-called").exists())

    def test_thin_control_protocol_one_fixture_allows_main_and_init(self):
        with tempfile.TemporaryDirectory(prefix="native-controller-one-", dir=os.environ.get("AWF_TEST_SCRATCH")) as raw:
            project, core, _, invoke = self.bridge_fixture(Path(raw).resolve(), "CENTRAL_CONTROL_PROTOCOL = 1")
            result = invoke("check")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((project / "bridge-main-called").exists())
            result = invoke("--binding", json.dumps(core.binding()), "helper", "lib/task_graph_init.py")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((project / "fixture-init-called").read_text(), "called")


class NativeProfileConsumerTest(unittest.TestCase):
    def test_sparse_profile_helper_uses_state_authority_over_ambient_host_paths(self):
        """真实薄桥读取显式state的稀疏角色，不能随进程HOME重选宿主根。"""
        from manager import central_runtime, runtime_service, runtime_policy
        from lib.central.runtime_project import LAUNCHER, PYTHON_ENTRY, project_key, identity
        pack = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="native-profile-", dir=os.environ.get("AWF_TEST_SCRATCH")) as raw:
            root = Path(raw).resolve()
            state = root / "custom-state"
            # 此消费者必须运行完整固定core中的真实profile依赖；不复制/补丁
            # 核心文件，也不以工作树的import替代真实薄入口执行。
            core = runtime_store.import_core(pack, state)
            context = NativeContext(state, HostPaths.for_home(root / "installed-host-home", environment={}))
            central_runtime.apply(central_runtime.preview(state, binding=core.binding(), native_context=context))
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.1.0"\n')
            runtime_service.apply(runtime_service.preview(state, project, "enable", binding=core.binding(),
                                                         hosts=("codex",), native_context=context))
            self.assertFalse((project / ".codex/agents/xy-qa.toml").exists())
            decoy = root / "ambient-home"
            decoy.mkdir()
            environment = dict(os.environ)
            for key in ("AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
                        "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT"):
                environment.pop(key, None)
            environment.update({"HOME": str(decoy), "CODEX_HOME": str(decoy / "wrong-codex"),
                                "CLAUDE_CONFIG_DIR": str(decoy / "wrong-claude"),
                                "AGENT_WORKFLOW_STATE_DIR": str(state), "AGENT_WORKFLOW_PYTHON": sys.executable})
            def invoke(mode):
                command = ["bash", str(project / PYTHON_ENTRY), "-B", "-X", "utf8", str(project / LAUNCHER),
                           "--binding", json.dumps(core.binding()), "helper", "lib/project/project_profile_cli.py"]
                command.extend(("check-roles", "codex", ".agent-workflow", ".") if mode == "check-roles"
                               else (mode, ".agent-workflow", "."))
                result = subprocess.run(command, cwd=project, env=environment, capture_output=True, text=True, timeout=40)
                print("ISOLATED_PROFILE_HELPER", mode, "exit=" + str(result.returncode))
                print(result.stdout, end="")
                print(result.stderr, end="")
                return result
            paths = (runtime_policy.CURRENT, runtime_policy.ACTIVATION, "bindings/" + project_key(project) + ".json")
            state_before = tuple(native.read_node(state, path) for path in paths)
            role = context.host_paths.codex / "agents/xy-qa.toml"
            owner_before = native.read_node(context.host_paths.codex, native.OWNER)
            role_before = native.read_node(context.host_paths.codex, "agents/xy-qa.toml")
            # 普通读取允许系统更新atime；复用生产节点identity核对inode、mode、
            # size、mtime、ctime，既不误报读取，也不豁免实际文件/目录修改。
            project_before = {path.relative_to(project).as_posix(): identity(path.lstat()) for path in project.rglob("*")}
            result = invoke("check-roles")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("native ownership", result.stdout)
            self.assertEqual(tuple(native.read_node(state, path) for path in paths), state_before)
            self.assertEqual(native.read_node(context.host_paths.codex, native.OWNER), owner_before)
            self.assertEqual(native.read_node(context.host_paths.codex, "agents/xy-qa.toml"), role_before)
            self.assertEqual({path.relative_to(project).as_posix(): identity(path.lstat()) for path in project.rglob("*")}, project_before)
            self.assertEqual(list(decoy.iterdir()), [])
            # 全局手删仍是冲突，不退回ambient HOME补资源；普通旧pin画像读取
            # 保持只读可用，不把check-roles的健康要求扩散到roles读取路径。
            role.unlink()
            result = invoke("check-roles")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            result = invoke("roles")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("xy-qa", result.stdout.splitlines())
            self.assertFalse(role.exists())
            self.assertEqual(list(decoy.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
