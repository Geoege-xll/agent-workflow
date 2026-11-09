"""在真实临时文件系统验证中央内容库，不触碰任何真实项目或全局宿主资源。"""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lib import runtime_store as store


PACK = Path(__file__).resolve().parents[1]
PYTHON = ["bash", str(PACK / "lib/python_runtime.sh"), "-B", "-X", "utf8"]


class RuntimeStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runtime-store-")
        self.addCleanup(self.temporary.cleanup)
        # macOS 的系统 /var 别名先在夹具所有者边界解析，测试传给库的都是实际目录。
        self.workspace = Path(self.temporary.name).resolve()
        self.source = self.workspace / "旧 keg 源包"
        self.state = self.workspace / "machine-state"
        self.make_source(self.source)

    def write(self, relative, body=b"fixture\n", *, source=None, executable=False):
        target = (source or self.source) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        target.chmod(0o755 if executable else 0o644)
        return target

    def make_source(self, root):
        # 仅生成独立最小核心，而不 clone/复制整份候选源码。通用模板与真实配置故意不同。
        for name in store.CORE_DIRECTORIES:
            (root / name).mkdir(parents=True, exist_ok=True)
        for name in store.SETUP_FILES:
            self.write(name, b"#!/bin/sh\nexit 0\n", source=root, executable=True)
        self.write("product/WORKFLOW.md", "# 通用工作流\n".encode(), source=root)
        self.write("product/ROLES.yaml", b"roles: {}\n", source=root)
        self.write("roles/xy-backend.md", b"# backend\n", source=root)
        self.write("platforms/shared/core-skills.txt", b"xy-code-standards\n", source=root)
        self.write("lib/probe.py", b'print("frozen core runs")\n', source=root)
        self.write("lib/python_runtime.sh", (PACK / "lib/python_runtime.sh").read_bytes(),
                   source=root, executable=True)
        self.write("scripts/scaffold_project_docs.sh", b"#!/bin/sh\nexit 0\n", source=root, executable=True)
        self.write("templates/project.yaml.example", b"project_name: Template\n", source=root)
        self.write("templates/docs/PROJECT.md", b"# {{PROJECT_NAME}}\n", source=root)
        self.write("manager/__init__.py", b'"""minimal manager"""\n', source=root)

    def imported(self):
        return store.import_core(self.source, self.state)

    def rewrite_readonly(self, path, body):
        # 这里只主动篡改夹具，用于证明只读防误写不等于同用户攻击防护。
        path.chmod(0o600)
        path.write_bytes(body)
        path.chmod(0o444)

    def test_import_load_list_binding_and_detached_runtime(self):
        core = self.imported()
        self.assertIsInstance(core, store.FrozenCore)
        self.assertEqual("source", core.label)
        self.assertEqual(self.state / "runtimes" / core.content_id / "core", core.root)
        self.assertEqual({"protocol_version": 1, "content_id": core.content_id,
                          "manifest_sha256": core.content_id}, core.binding())
        raw = (core.root.parent / "manifest.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), core.content_id)
        manifest = json.loads(raw)
        self.assertEqual(sorted(row["path"] for row in manifest["files"]),
                         [row["path"] for row in manifest["files"]])
        self.assertEqual({"path", "size", "sha256", "executable"}, set(manifest["files"][0]))
        self.assertNotIn(str(self.source).encode(), raw)
        with self.assertRaises(FrozenInstanceError):
            core.label = "changed"
        # 删除模拟旧 Homebrew keg 后，读取与真正的 Python 入口仍只依赖中央快照。
        shutil.rmtree(self.source)
        self.assertEqual(core, store.load_core(core.binding(), self.state))
        expected = "# 通用工作流\n".encode()
        self.assertEqual(expected, store.read_core_source(core, "product/WORKFLOW.md"))
        self.assertEqual(expected, store.read_core_source(core, ".agent-workflow/product/WORKFLOW.md"))
        self.assertEqual([{**core.binding(), "root": str(core.root), "label": "source"}],
                         store.list_cores(self.state))
        result = subprocess.run(["bash", str(core.root / "lib/python_runtime.sh"),
                                 "-B", "-X", "utf8", str(core.root / "lib/probe.py")],
                                cwd=self.workspace, capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("frozen core runs\n", result.stdout)

    def test_reproducible_content_ignores_source_root_and_unmanaged_settings(self):
        self.write("project.yaml", b"role_models: secret project setting\n")
        self.write("docs/PROJECT.md", b"private project document\n")
        self.write("tests/test_private.py", b"private test\n")
        self.write(".git/config", b"private git configuration\n")
        self.write(".claude/settings.json", b"private permissions and MCP\n")
        self.write("lib/windows-runtime.paths", b"private local interpreter\n")
        self.write("lib/__pycache__/probe.pyc", b"cache\n")
        self.write("scripts/test_codex.sh", b"private test launcher\n")
        original = self.imported()
        other_source = self.workspace / "another physical source"
        self.make_source(other_source)
        second = store.import_core(other_source, self.state)
        self.assertEqual(original, second)
        for relative in ("project.yaml", "docs/PROJECT.md", "tests/test_private.py", ".git/config",
                         ".claude/settings.json", "lib/windows-runtime.paths",
                         "lib/__pycache__/probe.pyc", "scripts/test_codex.sh"):
            self.assertFalse((original.root / relative).exists(), relative)
            with self.assertRaises(store.RuntimeStoreError):
                store.read_core_source(original, relative)
        self.assertEqual(b"project_name: Template\n",
                         store.read_core_source(original, "templates/project.yaml.example"))

    def test_multiple_versions_retained_and_unknown_pin_never_falls_back(self):
        original = self.imported()
        self.write("product/WORKFLOW.md", b"new workflow\n")
        new = self.imported()
        self.assertNotEqual(original.content_id, new.content_id)
        self.assertEqual({original.content_id, new.content_id},
                         {row["content_id"] for row in store.list_cores(self.state)})
        self.assertEqual("# 通用工作流\n".encode(), store.read_core_source(original, "product/WORKFLOW.md"))
        self.assertEqual(b"new workflow\n", store.read_core_source(new, "product/WORKFLOW.md"))
        missing = {"protocol_version": 1, "content_id": "0" * 64, "manifest_sha256": "0" * 64}
        with self.assertRaisesRegex(store.RuntimeStoreError, "缺失"):
            store.load_core(missing, self.state)
        self.assertTrue(original.root.is_dir())

    def test_release_label_only_comes_from_frozen_release_metadata(self):
        self.write("manager/release.json", b'{"schema_version":1,"version":"2.3.4"}\n')
        core = self.imported()
        self.assertEqual("2.3.4", core.label)
        self.assertEqual("2.3.4", store.load_core(core.binding(), self.state).label)
        self.write("manager/release.json", b'{"schema_version":1,"version":"not-a-release"}\n')
        with self.assertRaisesRegex(store.RuntimeStoreError, "发行标签"):
            self.imported()
        self.assertEqual(1, len(store.list_cores(self.state)))

    def test_product_version_is_authority_and_old_frozen_labels_remain_valid(self):
        """新核心以 VERSION 为唯一版本源；既有缺 VERSION 的 pin 标签不能被重标。"""
        old = self.imported()
        self.write("product/VERSION", b"2.1.0\n")
        current = self.imported()
        self.assertEqual("2.1.0", current.label)
        self.assertEqual("source", store.load_core(old.binding(), self.state).label)
        self.write("manager/release.json", b'{"schema_version":1,"version":"2.1.0"}\n')
        release = self.imported()
        self.assertEqual("2.1.0", release.label)
        self.write("manager/release.json", b'{"schema_version":1,"version":"2.0.1"}\n')
        with self.assertRaisesRegex(store.RuntimeStoreError, "发行标签"):
            self.imported()
        self.assertEqual("2.1.0", store.load_core(current.binding(), self.state).label)
        self.write("product/VERSION", b"02.1.0\n")
        with self.assertRaisesRegex(store.RuntimeStoreError, "product/VERSION"):
            self.imported()

    def test_version_line_endings_preserve_raw_identity_and_reject_extra_text(self):
        """版本标量容忍一次 Git 文本行尾转换，清单仍固定原字节而非规范化副本。"""
        from manager.release import source_version
        ids = set()
        for raw in (b"2.1.3", b"2.1.3\n", b"2.1.3\r\n"):
            self.write("product/VERSION", raw)
            with self.subTest(reader="release", raw=raw):
                self.assertEqual("2.1.3", source_version(self.source))
            with self.subTest(reader="store", raw=raw):
                core = self.imported()
                self.assertEqual("2.1.3", core.label)
                self.assertEqual("2.1.3", store.load_core(core.binding(), self.state).label)
                self.assertEqual(raw, store.read_core_source(core, "product/VERSION"))
                manifest = json.loads((core.root.parent / "manifest.json").read_bytes())
                row = next(row for row in manifest["files"] if row["path"] == "product/VERSION")
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (row["size"], row["sha256"]))
                ids.add(core.content_id)
        self.assertEqual(3, len(ids), "label normalization must not normalize frozen source bytes")
        # 只能移除一个合法行结束符，不能用 strip/rstrip 接受空白、空行或多行，
        # 也不能把 BOM、bare CR、前导零变成看似有效的发行标签。
        for raw in (b" 2.1.3\n", b"2.1.3 \r\n", b"2.1.3\n\n", b"2.1.3\r\n\r\n",
                    b"2.1.3\n\r\n", b"2.1.3\n2.1.4\n", b"2.1.3\r", b"02.1.3\r\n",
                    b"\xef\xbb\xbf2.1.3\r\n"):
            self.write("product/VERSION", raw)
            with self.subTest(reader="release rejects", raw=raw), self.assertRaises(ValueError):
                source_version(self.source)
            with self.subTest(reader="store rejects", raw=raw), self.assertRaises(store.RuntimeStoreError):
                store.inspect_core(self.source)

    def test_state_resolution_and_empty_listing_are_read_only(self):
        expected = self.workspace / "missing" / "state"
        with patch.dict(os.environ, {"AGENT_WORKFLOW_STATE_DIR": str(expected)}):
            self.assertEqual(expected, store.state_root())
            self.assertEqual([], store.list_cores())
        self.assertFalse(expected.parent.exists())
        self.assertEqual(self.state, store.state_root(self.state))
        for raw in ("", 2):
            with self.subTest(raw=raw), self.assertRaises(store.RuntimeStoreError):
                store.state_root(raw)

    def test_inspection_is_read_only_and_matches_expected_import(self):
        before = sorted(str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*"))
        with patch.dict(os.environ, {"AGENT_WORKFLOW_STATE_DIR": str(self.state)}):
            # 预览即便配置了状态路径也只读源；真实文件读取及摘要计算仍照常执行。
            with patch.object(store.os, "mkdir", side_effect=AssertionError("预览不能创建目录")):
                preview = store.inspect_core(self.source)
        self.assertEqual({"protocol_version", "content_id", "manifest_sha256", "label"}, set(preview))
        self.assertEqual("source", preview["label"])
        self.assertFalse(self.state.exists())
        self.assertEqual(before, sorted(str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*")))
        expected = {key: preview[key] for key in ("protocol_version", "content_id", "manifest_sha256")}
        core = store.import_core(self.source, self.state, expected_binding=expected)
        self.assertEqual(core.binding(), expected)
        self.assertEqual(core.label, preview["label"])

    def test_preview_source_drift_is_rejected_before_creating_state(self):
        preview = store.inspect_core(self.source)
        expected = {key: preview[key] for key in ("protocol_version", "content_id", "manifest_sha256")}
        self.write("product/WORKFLOW.md", b"changed after preview\n")
        with self.assertRaisesRegex(store.RuntimeStoreError, "预览绑定不符"):
            store.import_core(self.source, self.state, expected_binding=expected)
        self.assertFalse(self.state.exists())

    def test_mismatched_preview_does_not_publish_an_unexpected_version(self):
        original = self.imported()
        self.write("lib/probe.py", b'print("unapproved new source")\n')
        with self.assertRaisesRegex(store.RuntimeStoreError, "预览绑定不符"):
            store.import_core(self.source, self.state, expected_binding=original.binding())
        self.assertEqual([original.content_id], [row["content_id"] for row in store.list_cores(self.state)])
        self.assertEqual([], list((self.state / "runtimes").glob(".import-*")))

    def test_binding_is_strict_and_copied(self):
        binding = {"protocol_version": 1, "content_id": "a" * 64, "manifest_sha256": "a" * 64}
        copied = store.validate_binding(binding)
        copied["protocol_version"] = 2
        self.assertEqual(1, binding["protocol_version"])
        invalid = [None, {}, {**binding, "root": "/outside"}, {**binding, "protocol_version": True},
                   {**binding, "protocol_version": 2}, {**binding, "content_id": "../other"},
                   {**binding, "content_id": "A" * 64}, {**binding, "manifest_sha256": "b" * 64}]
        for candidate in invalid:
            with self.subTest(binding=candidate), self.assertRaises(store.RuntimeStoreError):
                store.load_core(candidate, self.state)
        self.assertFalse(self.state.exists())

    def test_logical_paths_cannot_escape_or_use_approximate_aliases(self):
        core = self.imported()
        self.write("outside.txt", b"outside\n", source=self.workspace)
        paths = ["", ".", "..", "../outside.txt", "/etc/passwd", "product//WORKFLOW.md",
                 "product/./WORKFLOW.md", "product/../roles/xy-backend.md", "product/WORKFLOW.md/",
                 r"product\WORKFLOW.md", "C:/outside.txt", "product/WORKFLOW.md\x00",
                 ".agent-workflow-other/product/WORKFLOW.md",
                 ".agent-workflow/.agent-workflow/product/WORKFLOW.md", "project.yaml"]
        for relative in paths:
            with self.subTest(relative=relative), self.assertRaises(store.RuntimeStoreError):
                store.read_core_source(core, relative)
        with self.assertRaises(store.RuntimeStoreError):
            store.read_core_source(replace(core, root=self.workspace), "product/WORKFLOW.md")

    def test_corrupt_existing_id_is_not_rewritten_or_hidden_by_listing(self):
        core = self.imported()
        target = core.root / "product/WORKFLOW.md"
        self.rewrite_readonly(target, b"damaged content\n")
        before = target.read_bytes()
        inode = target.stat().st_ino
        for action in (lambda: store.load_core(core.binding(), self.state),
                       lambda: store.read_core_source(core, "roles/xy-backend.md"),
                       lambda: store.list_cores(self.state), self.imported):
            with self.assertRaises(store.RuntimeStoreError):
                action()
        self.assertEqual(before, target.read_bytes())
        self.assertEqual(inode, target.stat().st_ino)
        self.assertEqual([], list((self.state / "runtimes").glob(".import-*")))

    def test_missing_manifest_does_not_repair_existing_version(self):
        core = self.imported()
        core.root.parent.chmod(0o755)
        (core.root.parent / "manifest.json").unlink()
        core.root.parent.chmod(0o555)
        with self.assertRaises(store.RuntimeStoreError):
            self.imported()
        self.assertFalse((core.root.parent / "manifest.json").exists())

    def test_manifest_digest_and_canonical_bytes_are_both_enforced(self):
        core = self.imported()
        manifest_path = core.root.parent / "manifest.json"
        data = json.loads(manifest_path.read_bytes())
        changed = (json.dumps(data, indent=2) + "\n").encode()
        self.rewrite_readonly(manifest_path, changed)
        with self.assertRaisesRegex(store.RuntimeStoreError, "摘要"):
            store.load_core(core.binding(), self.state)
        # 即使绑定了新原字节摘要，也必须拒绝非协议规定的 JSON 编码。
        identifier = hashlib.sha256(changed).hexdigest()
        new_path = core.root.parent.parent / identifier
        core.root.parent.rename(new_path)
        with self.assertRaisesRegex(store.RuntimeStoreError, "规范排序"):
            store.load_core({"protocol_version": 1, "content_id": identifier,
                             "manifest_sha256": identifier}, self.state)

    def test_extra_empty_directory_is_detected(self):
        core = self.imported()
        core.root.chmod(0o755)
        extra = core.root / "unexpected"
        extra.mkdir(mode=0o555)
        core.root.chmod(0o555)
        with self.assertRaisesRegex(store.RuntimeStoreError, "集合"):
            store.load_core(core.binding(), self.state)

    @unittest.skipIf(os.name == "nt", "POSIX 只读位合同，不把 Windows ACL 冒充 POSIX 模式")
    def test_readonly_and_executable_modes_are_strict(self):
        core = self.imported()
        self.assertEqual(0o444, stat.S_IMODE((core.root / "product/WORKFLOW.md").stat().st_mode))
        self.assertEqual(0o555, stat.S_IMODE((core.root / "setup_all.sh").stat().st_mode))
        self.assertEqual(0o555, stat.S_IMODE(core.root.stat().st_mode))
        (core.root / "product/WORKFLOW.md").chmod(0o644)
        with self.assertRaisesRegex(store.RuntimeStoreError, "模式"):
            store.load_core(core.binding(), self.state)

    @unittest.skipIf(os.name == "nt", "此夹具使用 POSIX 符号链接/硬链接/FIFO，Windows 由既有安全门面负责")
    def test_source_links_hardlinks_and_special_nodes_are_rejected(self):
        target = self.source / "lib/probe.py"
        original = target.read_bytes()
        outside = self.workspace / "external.py"
        outside.write_bytes(b"outside\n")
        for kind in ("symlink", "hardlink", "fifo"):
            with self.subTest(kind=kind):
                target.unlink()
                if kind == "symlink":
                    target.symlink_to(outside)
                elif kind == "hardlink":
                    os.link(outside, target)
                else:
                    os.mkfifo(target)
                with self.assertRaises(store.RuntimeStoreError):
                    self.imported()
                target.unlink()
                target.write_bytes(original)
        self.assertFalse(self.state.exists())
        self.assertEqual(b"outside\n", outside.read_bytes())

    @unittest.skipIf(os.name == "nt", "此夹具使用 POSIX 符号链接，生产入口仍走平台安全门面")
    def test_source_and_state_ancestors_cannot_be_links(self):
        alias = self.workspace / "alias"
        alias.symlink_to(self.workspace, target_is_directory=True)
        with self.assertRaises(store.RuntimeStoreError):
            store.import_core(alias / self.source.name, self.state)
        with self.assertRaises(store.RuntimeStoreError):
            store.import_core(self.source, alias / "escaped-state")
        self.assertFalse((self.workspace / "escaped-state").exists())
        (self.source / "lib/__pycache__").symlink_to(self.workspace, target_is_directory=True)
        with self.assertRaises(store.RuntimeStoreError):
            self.imported()

    @unittest.skipIf(os.name == "nt", "此夹具使用 POSIX 链接，Windows 重解析点由安全门面拒绝")
    def test_published_file_link_and_directory_escape_are_rejected(self):
        core = self.imported()
        target = core.root / "lib/probe.py"
        target.parent.chmod(0o755)
        target.unlink()
        target.symlink_to(self.source / "lib/probe.py")
        target.parent.chmod(0o555)
        with self.assertRaises(store.RuntimeStoreError):
            store.read_core_source(core, "product/WORKFLOW.md")
        target.parent.chmod(0o755)
        target.unlink()
        os.link(self.source / "lib/probe.py", target)
        target.parent.chmod(0o555)
        with self.assertRaises(store.RuntimeStoreError):
            store.load_core(core.binding(), self.state)

    def test_source_change_after_copy_is_rejected_and_stage_is_cleaned(self):
        copier = store._copy_snapshot

        def change_after_copy(*args):
            copier(*args)
            # 写回相同字节也改变节点时间，不能把并发重写当成稳定输入。
            target = self.source / "lib/probe.py"
            target.write_bytes(target.read_bytes())

        with patch.object(store, "_copy_snapshot", side_effect=change_after_copy):
            with self.assertRaisesRegex(store.RuntimeStoreError, "变化"):
                self.imported()
        self.assertEqual([], list((self.state / "runtimes").iterdir()))
        # 失败没有永久占用同 ID；恢复稳定输入后可以正常重新导入。
        self.assertEqual("source", self.imported().label)

    def test_source_set_change_after_copy_is_rejected(self):
        copier = store._copy_snapshot

        def add_after_copy(*args):
            copier(*args)
            self.write("lib/late.py", b"late addition\n")

        with patch.object(store, "_copy_snapshot", side_effect=add_after_copy):
            with self.assertRaisesRegex(store.RuntimeStoreError, "变化"):
                self.imported()
        self.assertEqual([], store.list_cores(self.state))

    def test_cross_process_same_id_publication_is_idempotent(self):
        program = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
            "from lib.runtime_store import import_core; "
            "print(import_core(Path(sys.argv[2]), Path(sys.argv[3])).content_id)"
        )
        processes = [subprocess.Popen([*PYTHON, "-c", program, str(PACK), str(self.source), str(self.state)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(4)]
        identifiers = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(0, process.returncode, stdout + stderr)
                identifiers.append(stdout.strip())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertEqual(1, len(set(identifiers)))
        self.assertEqual(identifiers[0], store.list_cores(self.state)[0]["content_id"])
        self.assertEqual(1, len(list((self.state / "runtimes").iterdir())))
        core = self.imported()
        inode = core.root.stat().st_ino
        self.assertEqual(core, self.imported())
        self.assertEqual(inode, core.root.stat().st_ino)

    def test_publication_failure_cleans_only_this_import_stage(self):
        with patch.object(store, "publish_exclusive", side_effect=OSError("injected publication failure")):
            with self.assertRaisesRegex(OSError, "publication failure"):
                self.imported()
        self.assertEqual([], list((self.state / "runtimes").iterdir()))
        core = self.imported()
        retained = self.state / "runtimes" / (".import-" + "a" * 32)
        retained.mkdir()
        (retained / "retained-evidence").write_bytes(b"interrupted import evidence")
        self.assertEqual(1, len(store.list_cores(self.state)))
        self.assertEqual(core, self.imported())
        self.assertEqual(b"interrupted import evidence", (retained / "retained-evidence").read_bytes())

    def test_listing_does_not_lose_versions_when_an_import_stage_disappears(self):
        core = self.imported()
        temporary_name = ".import-" + "b" * 32
        temporary = self.state / "runtimes" / temporary_name
        temporary.mkdir()
        original_stat = store.os.stat

        def remove_before_stat(path, *args, **kwargs):
            if path == temporary_name:
                temporary.rmdir()
            return original_stat(path, *args, **kwargs)

        # 只控制枚举和 stat 之间的时序；实际删除、加载和摘要验证仍操作真实磁盘。
        with patch.object(store.os, "stat", side_effect=remove_before_stat):
            self.assertEqual([core.content_id], [row["content_id"] for row in store.list_cores(self.state)])

    def test_existing_empty_id_directory_is_not_replaced(self):
        core = self.imported()
        version = core.root.parent
        # 临时目录夹具主动移走快照，模拟中断/损坏留下同名空目录。
        retained = self.state / "preserved-version"
        # macOS 跨父目录移动需要修改目录的 .. 项，故先在夹具边界解除只读位。
        version.chmod(0o755)
        version.rename(retained)
        retained.chmod(0o555)
        version.mkdir(mode=0o555)
        inode = version.stat().st_ino
        with self.assertRaises(store.RuntimeStoreError):
            self.imported()
        self.assertEqual(inode, version.stat().st_ino)
        self.assertEqual([], list(version.iterdir()))
        self.assertTrue((retained / "manifest.json").is_file())

    def test_manifest_cannot_authorize_an_outside_payload_path(self):
        core = self.imported()
        path = core.root.parent / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["files"][0]["path"] = "../outside"
        raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.rewrite_readonly(path, raw)
        identifier = hashlib.sha256(raw).hexdigest()
        core.root.parent.rename(core.root.parent.parent / identifier)
        with self.assertRaisesRegex(store.RuntimeStoreError, "不规范"):
            store.load_core({"protocol_version": 1, "content_id": identifier,
                             "manifest_sha256": identifier}, self.state)

    def test_source_cannot_contain_destination(self):
        with self.assertRaisesRegex(store.RuntimeStoreError, "互相包含"):
            store.import_core(self.source, self.source / "machine-state")
        self.assertFalse((self.source / "machine-state").exists())


if __name__ == "__main__":
    unittest.main()
