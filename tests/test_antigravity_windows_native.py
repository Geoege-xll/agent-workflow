"""Windows stage 的实际调用侧；不导入 POSIX pty/curses、Node 或 shell 夹具。"""

from __future__ import annotations

import os
import hashlib
import json
import re
import shutil
import stat
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class AntigravityStageFixture:
    def setUp(self):
        from lib.hosts import apply_antigravity_setup as applier
        from lib import windows_fs
        self.applier, self.fs = applier, windows_fs
        temporary = tempfile.TemporaryDirectory(prefix="native-host-stage-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def snapshot(self, path, *, max_bytes=4 * 1024 * 1024):
        backend = self.fs.secure_os
        parent = backend.open(path.parent, backend.O_RDONLY | backend.O_DIRECTORY | backend.O_NOFOLLOW)
        try:
            return self.fs.node_snapshot(parent, path.name, max_bytes=max_bytes)
        finally:
            backend.close(parent)

    def document(self, root, *, private=False):
        root.mkdir()
        target = root / "docs" / "user.md"
        target.parent.mkdir()
        if private:
            backend = self.fs.secure_os
            descriptor = backend.open(target, backend.O_WRONLY | backend.O_CREAT | backend.O_EXCL, 0o600)
            with backend.fdopen(descriptor, "wb") as output:
                output.write(b"original user document\n")
        else:
            target.write_bytes(b"original user document\n")
        change = self.applier.FileChange(target, b"approved managed document\n",
            self.applier._fingerprint(target).mode, self.applier._fingerprint(target),
            io_max_bytes=self.applier.DOCUMENT_FILE_SIZE)
        plan = self.applier.Plan(root, root, root, "a" * 32, doc_changes=[change])
        return target, change, plan

    def system_program(self, name):
        path = Path(os.environ["SystemRoot"]) / "System32" / name
        self.assertTrue(path.is_file(), str(path))
        return str(path)


@unittest.skipUnless(os.name == "nt", "真实 Windows HANDLE/owner/DACL 消费者")
class AntigravityStageWindowsNativeTest(AntigravityStageFixture, unittest.TestCase):
    def test_existing_document_preserves_full_native_security_and_original_inode_restore(self):
        for private in (False, True):
            with self.subTest(private=private):
                target, change, plan = self.document(self.root / str(private), private=private)
                before = self.snapshot(target)
                self.applier._publish_file(change, plan, backup_directory=plan.project)
                published, backup = self.snapshot(target), self.snapshot(change.backup)
                self.assertEqual(change.body, published["payload"])
                self.assertEqual(before["security"], published["security"])
                self.assertEqual(before["mode"], published["mode"])
                self.assertEqual(before["identity"][:2], backup["identity"][:2])
                self.assertEqual(before["security"], backup["security"])
                self.applier._rollback(plan)
                restored = self.snapshot(target)
                self.assertEqual(before["payload"], restored["payload"])
                self.assertEqual(before["identity"][:2], restored["identity"][:2])
                self.assertEqual(before["security"], restored["security"])
        root = self.root / "missing"
        root.mkdir()
        target = root / "new-document.md"
        change = self.applier.FileChange(target, b"new private document\n", 0o644, self.applier.Fingerprint("missing"))
        plan, empty = self.applier.Plan(root, root, root, "c" * 32, doc_changes=[change]), []
        create = self.fs.create_regular_stage
        def capture_empty(*args, **kwargs):
            result = create(*args, **kwargs)
            empty.append(result[1])
            self.assertIsNone(kwargs["permission_source"])
            self.assertIsNone(kwargs["expected_source"])
            return result
        with patch.object(self.fs, "create_regular_stage", side_effect=capture_empty):
            self.applier._publish_file(change, plan, backup_directory=root)
        self.assertEqual(change.body, self.snapshot(target)["payload"])
        self.assertEqual(empty[0]["security"], self.snapshot(target)["security"])

    def test_stage_failures_and_close_window_edits_do_not_publish_or_adopt(self):
        for failure in ("fdopen", "seal", "close_window", "source_drift"):
            with self.subTest(failure=failure):
                target, change, plan = self.document(self.root / failure)
                before, descriptors = self.snapshot(target), []
                create, snapshot, write_temp = self.fs.create_regular_stage, self.fs.node_snapshot, self.applier._write_temp
                temporary = self.applier._temp_path(target, plan.nonce, "temp")
                def created(*args, **kwargs):
                    result = create(*args, **kwargs)
                    descriptors.append(result[0])
                    return result
                def close_edit(parent, name, **kwargs):
                    if name == temporary.name:
                        temporary.write_bytes(b"external close-window edit\n")
                    return snapshot(parent, name, **kwargs)
                def source_edit(*args, **kwargs):
                    result = write_temp(*args, **kwargs)
                    target.write_bytes(b"external source edit\n")
                    return result
                with patch.object(self.fs, "create_regular_stage", side_effect=created):
                    if failure == "fdopen":
                        injected = patch.object(self.applier.os, "fdopen", side_effect=OSError("fixture fdopen failure"))
                    elif failure == "seal":
                        injected = patch.object(self.fs, "seal_regular_stage", side_effect=OSError("fixture seal failure"))
                    elif failure == "close_window":
                        injected = patch.object(self.fs, "node_snapshot", side_effect=close_edit)
                    else:
                        injected = patch.object(self.applier, "_write_temp", side_effect=source_edit)
                    with injected, self.assertRaises((OSError, ValueError)):
                        self.applier._publish_file(change, plan, backup_directory=plan.project)
                with self.assertRaises(OSError):
                    self.fs.secure_os.fstat(descriptors[0])
                self.assertFalse(change.published)
                self.assertIsNone(change.backup)
                actual = self.snapshot(target)
                self.assertEqual(b"external source edit\n" if failure == "source_drift" else before["payload"], actual["payload"])
                self.assertEqual(before["identity"][:2], actual["identity"][:2])
                stage = self.snapshot(temporary)
                self.assertIsNotNone(stage, "未被证明的残留不得擅自清理")
                if failure == "close_window":
                    self.assertEqual(b"external close-window edit\n", stage["payload"])

    def test_document_collision_preserves_external_target_and_original_backup(self):
        target, change, plan = self.document(self.root / "collision")
        before, move = self.snapshot(target), self.fs.move_regular
        injected = []
        def collide(source, destination, **kwargs):
            if source.startswith(self.applier.TRANSACTION_PREFIX + "temp--"):
                injected.append(True)
                target.write_bytes(b"external target after original isolation\n")
            return move(source, destination, **kwargs)
        with patch.object(self.fs, "move_regular", side_effect=collide), self.assertRaises(OSError):
            self.applier._publish_file(change, plan, backup_directory=plan.project)
        self.assertTrue(injected)
        self.assertFalse(change.published)
        self.assertEqual(b"external target after original isolation\n", target.read_bytes())
        backup = self.snapshot(change.backup)
        self.assertEqual(before["identity"][:2], backup["identity"][:2])
        self.assertEqual(before["security"], backup["security"])
        with self.assertRaisesRegex(self.applier.ApplyError, "preserved current file and backup"):
            self.applier._rollback(plan)
        self.assertEqual(b"external target after original isolation\n", target.read_bytes())
        self.assertEqual(backup, self.snapshot(change.backup))

    def test_native_missing_compensation_preserves_real_retained_source_security(self):
        from lib.central import runtime_project as project
        from manager import native_agents
        root, state = self.root / "native", self.root / "state"
        root.mkdir()
        target = root / "agent.toml"
        target.write_bytes(b"original native role\n")
        with project.Tree(root) as tree:
            parent, name = tree.parent(target.name)
            before = project.read_at(parent, name)
        journal = {"transaction_id": "b" * 32, "writes": [], "root_identities": {}}
        # 真实生产者先保存路径、完整 stage、原 inode retained；注入仅截断最后
        # publish，绝不手写 retained 身份或把空创建像伪装成 ready。
        with patch.object(native_agents, "publish_at", side_effect=KeyboardInterrupt("fixture before native publish")):
            with self.assertRaises(KeyboardInterrupt):
                native_agents._publish(state, journal, root, target.name,
                                       project.Node("file", b"approved replacement\n", 0o644), expected=before)
        row = journal["writes"][0]
        self.assertFalse(target.exists())
        self.assertEqual(b"approved replacement\n", project.Node.from_value(row["staged"]).payload)
        retained = root / row["retained"][0]["path"]
        actual_source = self.snapshot(retained)
        self.assertEqual(before.identity[:2], actual_source["identity"][:2])
        restored = native_agents._compensate_node(state, journal, root, target.name, expected=project.Node(), after=before)
        self.assertEqual(before.payload, restored.payload)
        self.assertEqual(before.security, restored.security)
        self.assertEqual(actual_source, self.snapshot(retained), "创建和恢复均不能改动源 SD 或实体")
        step = journal["compensations"][0]
        self.assertEqual(before.payload, project.Node.from_value(step["staged"]).payload)
        self.assertEqual(restored.value(), step["result"])

    def test_rollback_and_cleanup_reject_acl_only_and_same_content_inode_drift(self):
        for operation in ("rollback", "cleanup"):
            for scope in ("doc", "hook"):
                for location in ("published", "backup"):
                    for mutation in ("acl", "inode", "body", "readonly"):
                        with self.subTest(operation=operation, scope=scope, location=location, mutation=mutation):
                            root = self.root / (operation + scope + location + mutation)
                            target, change, plan = self.document(root)
                            if scope == "hook":
                                plan.doc_changes.clear()
                                plan.hook_changes.append(change)
                            self.applier._publish_file(change, plan, backup_directory=root)
                            selected = target if location == "published" else change.backup
                            before = self.snapshot(selected)
                            if mutation == "acl":
                                # 只关闭继承并将原 ACE 转成显式；权限仍允许测试进程
                                # 正常读取。实际 OS 命令必须成功且完整 SD 必须变化。
                                result = subprocess.run([self.system_program("icacls.exe"), str(selected), "/inheritance:d"],
                                                        capture_output=True, timeout=10)
                                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                            elif mutation == "inode":
                                candidate = selected.with_name(selected.name + ".external")
                                candidate.write_bytes(before["payload"])
                                os.replace(candidate, selected)
                            elif mutation == "body":
                                selected.write_bytes(b"external body edit\n")
                            else:
                                os.chmod(selected, stat.S_IREAD)
                            changed = self.snapshot(selected)
                            if mutation == "acl":
                                self.assertNotEqual(before["security"], changed["security"])
                                self.assertEqual(before["payload"], changed["payload"])
                                self.assertEqual(before["mode"], changed["mode"])
                                self.assertEqual(before["identity"][:2], changed["identity"][:2])
                            if mutation == "inode":
                                self.assertNotEqual(before["identity"][:2], changed["identity"][:2])
                                self.assertEqual(before["payload"], changed["payload"])
                                self.assertEqual(before["mode"], changed["mode"])
                            target_before, backup_before = self.snapshot(target), self.snapshot(change.backup)
                            action = self.applier._rollback if operation == "rollback" else self.applier._cleanup_committed
                            with self.assertRaises(self.applier.ApplyError):
                                action(plan)
                            self.assertEqual(target_before, self.snapshot(target))
                            self.assertEqual(backup_before, self.snapshot(change.backup))


@unittest.skipUnless(os.name == "nt", "Server/elevated 独立 owner-only 夹具证明")
class AntigravityOwnerSecurityWindowsElevatedTest(AntigravityStageFixture, unittest.TestCase):
    """仅唯一 registry 的 elevated 组选择；不因当前 owner 相同自动 skip。"""

    def security_observation(self, path):
        executable = shutil.which("pwsh.exe")
        self.assertIsNotNone(executable, "owner 观测要求既有 PS7")
        command = ("$ErrorActionPreference='Stop'; $a=Get-Acl -LiteralPath $env:AWF_OWNER_TEST_TARGET; "
                   "[pscustomobject]@{owner=$a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value; "
                   "access=$a.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access)} "
                   "| ConvertTo-Json -Compress")
        result = subprocess.run([str(Path(executable).resolve()), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            env={**os.environ, "AWF_OWNER_TEST_TARGET": str(path)}, capture_output=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout.decode("utf-8-sig"))

    def test_owner_only_drift_preserves_published_and_backup_nodes_during_rollback_and_cleanup(self):
        identity = subprocess.run([self.system_program("whoami.exe"), "/user", "/fo", "csv", "/nh"],
                                  capture_output=True, timeout=10)
        self.assertEqual(0, identity.returncode, identity.stdout + identity.stderr)
        identifiers = re.findall(rb"S-1-[0-9]+(?:-[0-9]+)+", identity.stdout)
        self.assertEqual(1, len(identifiers))
        sid = identifiers[0].decode("ascii")
        for operation in ("rollback", "cleanup"):
            for location in ("published", "backup"):
                with self.subTest(operation=operation, location=location):
                    target, change, plan = self.document(self.root / (operation + location))
                    self.applier._publish_file(change, plan, backup_directory=plan.project)
                    selected = target if location == "published" else change.backup
                    before, access = self.snapshot(selected), self.security_observation(selected)
                    # Server 高权限默认创建应由 BA 持有，随后只设为当前合法用户。
                    # 无差异样本直接失败，不能以普通用户已有 LA 冒充 owner 负控。
                    self.assertEqual("S-1-5-32-544", access["owner"])
                    self.assertNotEqual(sid, access["owner"])
                    changed_owner = subprocess.run([self.system_program("icacls.exe"), str(selected), "/setowner", "*" + sid],
                                                   capture_output=True, timeout=10)
                    self.assertEqual(0, changed_owner.returncode, changed_owner.stdout + changed_owner.stderr)
                    after, after_access = self.snapshot(selected), self.security_observation(selected)
                    self.assertEqual(sid, after_access["owner"])
                    self.assertEqual(access["access"], after_access["access"], "owner-only 不能同时修改 DACL/control")
                    self.assertEqual(before["payload"], after["payload"])
                    self.assertEqual(before["mode"], after["mode"])
                    self.assertEqual(before["identity"][:6], after["identity"][:6])
                    self.assertNotEqual(before["security"], after["security"])
                    target_before, backup_before = self.snapshot(target), self.snapshot(change.backup)
                    action = self.applier._rollback if operation == "rollback" else self.applier._cleanup_committed
                    with self.assertRaises(self.applier.ApplyError):
                        action(plan)
                    self.assertEqual(target_before, self.snapshot(target))
                    self.assertEqual(backup_before, self.snapshot(change.backup))


class AntigravityFileBudgetTest(unittest.TestCase):
    """同一实际文件发布/恢复消费者可在 POSIX 和 Windows 精准运行，无平台替身。"""

    def setUp(self):
        from lib.hosts import apply_antigravity_setup as applier
        self.applier = applier
        temporary = tempfile.TemporaryDirectory(prefix="agy-file-budget-", dir=os.environ.get("AWF_TEST_SCRATCH"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.product = (applier.PRODUCT_BEGIN + "\nproduct\n" + applier.PRODUCT_END + "\n").encode()
        self.anti = (applier.ANTIGRAVITY_BEGIN + "\nanti\n" + applier.ANTIGRAVITY_END + "\n").encode()

    def compose(self, current, path):
        return self.applier._compose_agents_md(current, self.product, self.anti, path)

    def assert_bytes(self, expected, path):
        # 断言失败也只输出长度/摘要，不能把数 MiB 的真实测试正文转储到日志。
        actual = path.read_bytes()
        self.assertEqual(len(expected), len(actual))
        self.assertEqual(hashlib.sha256(expected).hexdigest(), hashlib.sha256(actual).hexdigest())

    def test_large_root_publication_restore_and_cleanup_keep_original_eight_mib_boundary(self):
        base = b"# original user text\n"
        overhead = len(self.compose(base, self.root / "AGENTS.md")) - len(base)
        for input_size in (self.applier.DOCUMENT_FILE_SIZE - 1, self.applier.DOCUMENT_FILE_SIZE + 1,
                           self.applier.MAX_FILE_SIZE - overhead):
            with self.subTest(input_bytes=input_size):
                root = self.root / str(input_size)
                root.mkdir()
                target = root / "AGENTS.md"
                original = base + b"u" * (input_size - len(base) - 1) + b"\n"
                target.write_bytes(original)
                before = self.applier._fingerprint(target)
                composed = self.compose(original, target)
                self.assertGreater(len(composed), self.applier.DOCUMENT_FILE_SIZE)
                self.assertLessEqual(len(composed), self.applier.MAX_FILE_SIZE)
                if input_size == self.applier.MAX_FILE_SIZE - overhead:
                    self.assertEqual(self.applier.MAX_FILE_SIZE, len(composed))
                for finish in ("restore", "cleanup"):
                    change = self.applier.FileChange(target, composed, before.mode, before)
                    plan = self.applier.Plan(root, root, root, ("d" if finish == "restore" else "e") * 32,
                                             agents_md=change)
                    self.applier._publish_file(change, plan)
                    self.assert_bytes(composed, target)
                    self.assert_bytes(original, change.backup)
                    if os.name == "nt":
                        self.assertEqual(change.native_backup["security"], change.native_published["security"])
                    if finish == "restore":
                        self.applier._rollback(plan)
                        self.assert_bytes(original, target)
                        self.assertEqual(before, self.applier._fingerprint(target))
                    else:
                        self.applier._cleanup_committed(plan)
                        self.assertFalse(change.backup.exists())

        # 真实 build_plan 必须保留旧 root 的 8MiB I/O，即便原 AGY 托管段较大而
        # rebuilt 已降到 Codex 32KiB 内。不能手造默认 FileChange 绕过生产者选择。
        from lib.hosts.render_antigravity_agent import render
        pack_source = Path(__file__).resolve().parents[1]
        project, staging = self.root / "legacy-project", self.root / "legacy-staging"
        pack = project / "agent_workflow"
        pack.mkdir(parents=True)
        staging.mkdir()
        shutil.copytree(pack_source / "roles", pack / "roles")
        shutil.copytree(pack_source / "templates/docs", pack / "templates/docs")
        from lib.standard_paths import BUILTIN_STANDARD_SOURCES
        for relative in (*BUILTIN_STANDARD_SOURCES, "product/ROLES.yaml"):
            destination = pack / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pack_source / relative, destination)
        config = (pack_source / "templates/project.yaml.example").read_text(encoding="utf-8")
        config = config.replace("project_id: replace-with-unique-project-id", "project_id: legacy-root-budget-fixture")
        config = config.replace("  mode: assist", "  mode: off")
        (pack / "project.yaml").write_text(config, encoding="utf-8")
        (project / "pyproject.toml").write_text('[project]\nname="legacy-root"\nversion="0.0.0"\n', encoding="utf-8")
        validation = self.applier.validate_with_profile(pack / "project.yaml", project, pack / "roles")
        self.assertFalse(validation.errors, validation.errors)
        (staging / "agents").mkdir()
        for role in validation.profile.enabled_roles:
            (staging / "agents" / (role + ".md")).write_text(render(pack, role), encoding="utf-8")
        (staging / "skills").mkdir()
        for skill in self.applier.CORE_SKILLS:
            shutil.copytree(pack_source / "platforms/shared/skills" / skill, staging / "skills" / skill)
        (staging / "AGENTS.product.block").write_bytes(self.product)
        (staging / "AGENTS.antigravity.block").write_bytes(self.anti)
        target = project / "AGENTS.md"
        original = (self.product + (self.applier.CODEX_BEGIN + "\nexisting codex\n" + self.applier.CODEX_END + "\n").encode()
            + (self.applier.ANTIGRAVITY_BEGIN + "\n" + "a" * 40000 + "\n" + self.applier.ANTIGRAVITY_END + "\n").encode())
        target.write_bytes(original)
        before = self.applier._fingerprint(target)
        self.assertGreater(len(original), self.applier.CODEX_ENTRY_SIZE)
        for finish in ("restore", "cleanup"):
            plan = self.applier.build_plan(pack, project, staging)
            change = plan.agents_md
            self.assertEqual(self.applier.MAX_FILE_SIZE, change.io_max_bytes)
            self.assertLessEqual(len(change.body), self.applier.CODEX_ENTRY_SIZE)
            self.applier._publish_file(change, plan)
            self.assert_bytes(change.body, target)
            self.assert_bytes(original, change.backup)
            if finish == "restore":
                self.applier._rollback(plan)
                self.assertEqual(before, self.applier._fingerprint(target))
            else:
                self.applier._cleanup_committed(plan)
                self.assertFalse(change.backup.exists())

    def test_merged_overflow_controlled_docs_and_codex_caps_reject_before_stage_or_backup(self):
        target = self.root / "AGENTS.md"
        original = b"u" * self.applier.MAX_FILE_SIZE
        target.write_bytes(original)
        before = self.applier._fingerprint(target)
        with self.assertRaisesRegex(self.applier.ApplyError, "8 MiB"):
            self.compose(original, target)
        self.assertEqual(before, self.applier._fingerprint(target))
        self.assertEqual([target], list(self.root.iterdir()))
        # 已安装 Codex 的合法共享入口必须先含 product 块；否则旧 marker 顺序
        # 守卫会更早拒绝，不能把那种样本当成真正触达 32KiB 上界的负控。
        codex = self.product + b"\n" + (self.applier.CODEX_BEGIN + "\n" + self.applier.CODEX_END + "\n").encode()
        with self.assertRaisesRegex(self.applier.ApplyError, "32 KiB"):
            self.compose(codex + b"u" * self.applier.CODEX_ENTRY_SIZE, target)
        plan = self.applier.Plan(self.root, self.root, self.root, "f" * 32,
            agents_md=self.applier.FileChange(target, original + b"x", before.mode, before))
        early = self.root / "must-not-appear.md"
        plan.doc_changes.append(self.applier.FileChange(early, b"earlier valid document\n", 0o644,
            self.applier.Fingerprint("missing"), io_max_bytes=self.applier.DOCUMENT_FILE_SIZE))
        with patch.object(self.applier, "_write_temp", wraps=self.applier._write_temp) as writes:
            with self.assertRaisesRegex(self.applier.ApplyError, "read boundary"):
                self.applier.apply_plan(plan)
            self.assertEqual(0, writes.call_count)
        with patch.object(self.applier, "_write_temp", wraps=self.applier._write_temp) as writes:
            with self.assertRaisesRegex(self.applier.ApplyError, "read boundary"):
                self.applier.publish_document_changes(self.root,
                    {early: b"valid\n", target: b"d" * (self.applier.DOCUMENT_FILE_SIZE + 1)},
                    {early: None, target: original}, lambda: None)
            self.assertEqual(0, writes.call_count)
        self.assertEqual(before, self.applier._fingerprint(target))
        self.assertEqual([target], list(self.root.iterdir()))
