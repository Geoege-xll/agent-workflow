"""远程来源发布合同：临时真实 bare 仓库证明闭包、幂等和原子快进边界。"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
spec = importlib.util.spec_from_file_location("publish_plugin_sources", ROOT / "packaging/publish_plugin_sources.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
from build_candidates import validate_component_binding


def zip_bytes(files):
    """夹具只模拟既有 ZIP 协议；不复制产品载荷或业务规则。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, (body, mode) in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | (0o755 if mode == "100755" else 0o644)) << 16
            archive.writestr(entry, body)
    return buffer.getvalue()


class PluginSourcePublicationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="plugin-source-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(self.remote)], check=True)
        self.revision = "a" * 40
        self.candidate = self.make_candidate("one")

    def git(self, *arguments):
        return publisher.git(self.remote, *arguments).decode().strip()

    def refs(self):
        return self.git("for-each-ref", "--format=%(refname) %(objectname)")

    def make_candidate(self, name, version="3.0.0-alpha.5", payload=b"payload\n", native_version="0.1.0-alpha.2", channel="alpha",
                       component_published=None, native_build_suffix=b"", component_url=None):
        directory = self.root / name
        directory.mkdir()
        identity_body = (ROOT / "product/command_identity.json").read_bytes()
        native_files = {"BUILD.json": (publisher.json_bytes({"name": "native-agent-config",
            "version": native_version, "files": {"product/command_identity.json": publisher.digest(identity_body)}})
            + native_build_suffix, "100644"), "product/command_identity.json": (identity_body, "100644")}
        published = channel == "stable" if component_published is None else component_published
        # 此 URL 仅是临时协议夹具；生产 descriptor 继续由真实下载装配器生成。
        # 夹具先计算真实临时 ZIP 字节，让正式发布门禁核对同一组件摘要。
        url = (f"https://github.com/{publisher.REPOSITORY}/releases/download/native-v{native_version}/"
               f"native-agent-config-{native_version}.zip") if published else ""
        if component_url is not None:
            url = component_url
        descriptor = publisher.json_bytes({"schema_version": 1, "product": "native-agent-config",
            "version": native_version, "channel": channel, "cli_protocol": 1, "service_protocol": 2,
            "release_status": "published" if published else "unpublished", "artifact": {
                "name": f"native-agent-config-{native_version}.zip",
                "sha256": publisher.digest(zip_bytes(native_files)) if published or channel == "stable" else "",
                "url": url}})
        rows = []

        def artifact(path, files, metadata):
            target = directory / path
            target.parent.mkdir(exist_ok=True, parents=True)
            target.write_bytes(zip_bytes(files))
            rows.append({"path": path, "sha256": publisher.digest(target.read_bytes()), **metadata})

        for host in publisher.HOSTS:
            files = {"README.md": (payload, "100644"), "lib/python_runtime.sh": (b"#!/bin/sh\n", "100755"),
                "plugins/maintenance/component.json": (descriptor, "100644"),
                "product/command_identity.json": ((ROOT / "product/command_identity.json").read_bytes(), "100644"),
                publisher.MANIFEST[host]: (publisher.json_bytes({"name": "xy-workflow", "version": version}), "100644")}
            # 最小锁定资源保留真实三提供者包的关键差异：带市场前缀后，官方
            # runtime 可执行文件仍为755，本地启动器则按构建器规则投影为644。
            executable = "runtime/tool.sh"
            locked_file = "third_party/selected-skills/playwright-cli/" + executable
            files[locked_file] = (b"#!/bin/sh\nexit 0\n", "100755")
            files["third_party/selected-skills.lock.json"] = (publisher.json_bytes({"dependencies": {
                "playwright-cli": {"files": {executable: {"mode": 0o755}}}}}), "100644")
            provenance = {"schema_version": 1, "host": host, "plugin_version": version,
                "product": "workflow-core", "source_files": {},
                "payload_sha256": {key: publisher.digest(value[0]) for key, value in files.items()}}
            files["sources.json"] = (publisher.json_bytes(provenance), "100644")
            stem = f"workflow/xy-workflow-{host}-{version}"
            metadata = {"host": host, "version": version, "product": "workflow"}
            artifact(stem + ".zip", files, {**metadata, "kind": "plugin"})
            prefix = "xy-workflow/" if host == "antigravity" else "plugins/xy-workflow/"
            local = {prefix + key: (value[0], "100755" if key == locked_file else "100644")
                     for key, value in files.items()}
            if host == "codex":
                market = {"name": "xy-workflow-local", "plugins": [{"name": "xy-workflow",
                    "source": {"source": "local", "path": "./plugins/xy-workflow"},
                    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}]}
            elif host == "claude":
                market = {"name": "xy-workflow-local", "owner": {"name": "Agent Workflow"},
                    "plugins": [{"name": "xy-workflow", "source": "./plugins/xy-workflow"}]}
            if host in publisher.MARKET:
                local[publisher.MARKET[host]] = (publisher.json_bytes(market), "100644")
            artifact(stem + "-local-source.zip", local, {**metadata, "kind": "local-source"})
        native_name = f"native/native-agent-config-{native_version}.zip"
        artifact(native_name, native_files, {"product": "native-config", "kind": "standalone", "version": native_version})
        candidate = {"schema_version": 1, "channel": channel, "status": "BUILD_VERIFIED",
            "source": {"dirty": False, "revision": self.revision, "tree_sha256": "b" * 64},
            "versions": {"workflow": version, "native-config": native_version}, "artifacts": rows,
            "maintenance_component": validate_component_binding(descriptor, directory / native_name, native_version)}
        (directory / "candidate-manifest.json").write_bytes(publisher.json_bytes(candidate))
        return directory

    def publish(self, candidate=None, **kwargs):
        return publisher.publish(candidate or self.candidate, self.revision, publisher.REPOSITORY,
                                 str(self.remote), **kwargs)

    def change_manifest(self, callback):
        path = self.candidate / "candidate-manifest.json"
        value = json.loads(path.read_bytes())
        callback(value)
        path.write_bytes(publisher.json_bytes(value))

    def remote_commit(self, host, extra):
        """直接构造测试远端竞争提交，保证发布器实际经历非快进拒绝。"""
        ref = "refs/heads/plugins-" + host + "-alpha"
        old = self.git("rev-parse", ref)
        files = publisher.tree_files(self.remote, old)
        files.update(extra)
        self.git("read-tree", "--empty")
        for name, (body, mode) in files.items():
            sha = publisher.git(self.remote, "hash-object", "-w", "--stdin", input=body).decode().strip()
            self.git("update-index", "--add", "--cacheinfo", mode, sha, name)
        tree = self.git("write-tree")
        commit = self.git("commit-tree", tree, "-p", old, "-m", "External test update")
        self.git("update-ref", ref, commit, old)
        return commit

    def test_initial_three_refs_layout_exact_plugin_bytes_and_default_preview(self):
        preview = self.publish()
        self.assertFalse(preview["applied"])
        self.assertEqual("", self.refs())
        result = self.publish(apply=True)
        self.assertEqual(3, len(self.refs().splitlines()))
        self.assertEqual(["create"] * 3, [row["action"] for row in result["branches"]])
        for host in publisher.HOSTS:
            files = publisher.tree_files(self.remote, "plugins-" + host + "-alpha")
            prefix = "" if host == "antigravity" else "plugins/xy-workflow/"
            primary = self.candidate / f"workflow/xy-workflow-{host}-3.0.0-alpha.5.zip"
            for name, value in publisher.archive_files(primary.read_bytes()).items():
                self.assertEqual(value, files[prefix + name])
            record = json.loads(files["distribution.json"][0])
            self.assertEqual(self.revision, record["source_revision"])
            if host in publisher.MARKET:
                self.assertEqual("xy-workflow-alpha", json.loads(files[publisher.MARKET[host]][0])["name"])
            else:
                self.assertIn(".antigravity-plugin/plugin.json", files)

    def test_stable_refs_keep_alpha_history_and_reject_same_version_payload_and_downgrade(self):
        # 真实 bare 远端先保留已发布 alpha，再通过同一发布器产生独立 stable 引用。
        self.publish(apply=True)
        alpha_refs = self.refs()
        stable = self.make_candidate("stable", "3.0.1", native_version="0.1.1", channel="stable")
        result = self.publish(stable, channel="stable", apply=True)
        self.assertEqual(6, len(self.refs().splitlines()))
        for line in alpha_refs.splitlines():
            self.assertIn(line, self.refs().splitlines())
        for row in result["branches"]:
            self.assertTrue(row["ref"].endswith("-stable"))
            files = publisher.tree_files(self.remote, row["ref"])
            record = json.loads(files["distribution.json"][0])
            self.assertEqual(("stable", "3.0.1"), (record["channel"], record["version"]))
            if row["host"] in publisher.MARKET:
                self.assertEqual("xy-workflow", json.loads(files[publisher.MARKET[row["host"]]][0])["name"])
        before = self.refs()
        self.assertEqual(["unchanged"] * 3,
                         [row["action"] for row in self.publish(stable, channel="stable", apply=True)["branches"]])
        altered = self.make_candidate("stable-altered", "3.0.1", b"changed", "0.1.1", "stable")
        with self.assertRaisesRegex(ValueError, "同一版本"):
            self.publish(altered, channel="stable", apply=True)
        older = self.make_candidate("stable-older", "3.0.0", native_version="0.1.1", channel="stable")
        with self.assertRaisesRegex(ValueError, "向前递增"):
            self.publish(older, channel="stable", apply=True)
        with self.assertRaises(ValueError):
            self.publish(stable, channel="alpha", apply=True)
        with self.assertRaises(ValueError):
            self.publish(stable, channel="beta", apply=True)
        self.assertEqual(before, self.refs())

    def test_workflow_upgrade_cannot_downgrade_or_rebind_same_native_version(self):
        stable = self.make_candidate("stable", "3.0.1", native_version="0.1.1", channel="stable")
        self.publish(stable, channel="stable", apply=True)
        before = self.refs()
        older = self.make_candidate("older-component", "3.0.2", native_version="0.1.0", channel="stable")
        with self.assertRaisesRegex(ValueError, "组件版本必须向前"):
            self.publish(older, channel="stable", apply=True)
        # 仅改变合法 BUILD JSON 空白，让内部闭包、descriptor 与 ZIP 摘要都一致；
        # 失败必须来自跨工作流同版组件改绑，不能只证明普通哈希损坏能被拒绝。
        altered = self.make_candidate("rebound-component", "3.0.2", native_version="0.1.1", channel="stable",
                                      native_build_suffix=b"\n")
        with self.assertRaisesRegex(ValueError, "同一组件版本"):
            self.publish(altered, channel="stable", apply=True)
        self.assertEqual(before, self.refs())

    def test_stable_unpublished_candidate_cannot_become_git_install_source(self):
        unpublished = self.make_candidate("unpublished-stable", "3.0.1", native_version="0.1.1", channel="stable",
                                          component_published=False)
        with self.assertRaisesRegex(ValueError, "必须先发布并固定验证原生组件"):
            self.publish(unpublished, channel="stable", apply=True)
        self.assertEqual("", self.refs())
        foreign = self.make_candidate("foreign-published", "3.0.1", native_version="0.1.1", channel="stable",
                                      component_url="https://example.com/native-agent-config-0.1.1.zip")
        with self.assertRaisesRegex(ValueError, "固定发行来源无效"):
            self.publish(foreign, channel="stable", apply=True)
        self.assertEqual("", self.refs())

    def test_mixed_product_and_declared_channels_are_rejected_before_remote_mutation(self):
        path = self.candidate / "candidate-manifest.json"
        original = path.read_bytes()
        for change in (lambda item: item.update(channel="stable"),
                       lambda item: item["versions"].update(workflow="3.0.1"),
                       lambda item: item["versions"].update(**{"native-config": "0.1.0-beta.1"})):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.change_manifest(change)
                self.publish(apply=True)
            self.assertEqual("", self.refs())
            path.write_bytes(original)

    def test_same_version_is_idempotent_and_candidate_document_only_change_is_ignored(self):
        self.publish(apply=True)
        before = self.refs()
        self.change_manifest(lambda value: value.update({"unrelated_note": "仅候选外层说明变化"}))
        result = self.publish(apply=True)
        self.assertEqual(["unchanged"] * 3, [row["action"] for row in result["branches"]])
        self.assertEqual(before, self.refs())

    def test_same_version_different_payload_is_rejected(self):
        self.publish(apply=True)
        before = self.refs()
        other = self.make_candidate("other", payload=b"changed")
        with self.assertRaisesRegex(ValueError, "同一版本"):
            self.publish(other, apply=True)
        self.assertEqual(before, self.refs())

    def test_second_version_uses_existing_tip_as_parent(self):
        initial = self.publish(apply=True)
        second = self.make_candidate("second", version="3.0.0-alpha.6", payload=b"next")
        result = self.publish(second, apply=True)
        for old, new in zip(initial["branches"], result["branches"]):
            self.assertEqual(old["commit"], self.git("rev-parse", new["commit"] + "^"))
        with self.assertRaisesRegex(ValueError, "向前递增"):
            self.publish(apply=True)

    def test_unknown_branch_and_additional_user_file_are_not_overwritten(self):
        # 先创建缺少受管标记的真实同名远程分支。
        tree = publisher.git(self.remote, "mktree", input=b"").decode().strip()
        commit = self.git("commit-tree", tree, "-m", "User branch")
        self.git("update-ref", "refs/heads/plugins-codex-alpha", commit)
        with self.assertRaisesRegex(ValueError, "标记"):
            self.publish(apply=True)
        self.git("update-ref", "-d", "refs/heads/plugins-codex-alpha")
        self.publish(apply=True)
        self.remote_commit("claude", {"user.txt": (b"user data", "100644")})
        before = self.refs()
        with self.assertRaisesRegex(ValueError, "未知文件"):
            self.publish(apply=True)
        self.assertEqual(before, self.refs())

    def test_wrong_hash_dirty_revision_identity_and_extra_artifact_are_rejected(self):
        path = self.candidate / "candidate-manifest.json"
        original = path.read_bytes()
        changes = [lambda value: value["source"].update(dirty=True),
                   lambda value: value["source"].update(revision="c" * 40),
                   lambda value: value["artifacts"][0].update(sha256="0" * 64),
                   lambda value: value["artifacts"][0].update(host="wrong"),
                   lambda value: value["artifacts"].pop()]
        for change in changes:
            with self.subTest(change=change):
                self.change_manifest(change)
                with self.assertRaises(ValueError):
                    self.publish(apply=True)
                self.assertEqual("", self.refs())
                path.write_bytes(original)
        with self.assertRaises(ValueError):
            publisher.publish(self.candidate, self.revision[:8], publisher.REPOSITORY, str(self.remote))
        with self.assertRaises(ValueError):
            publisher.publish(self.candidate, self.revision, "someone/else", str(self.remote))

    def test_zip_traversal_and_symlink_are_rejected_even_with_updated_candidate_hash(self):
        manifest_path = self.candidate / "candidate-manifest.json"
        original_manifest = manifest_path.read_bytes()
        row = json.loads(original_manifest)["artifacts"][0]
        archive = self.candidate / row["path"]
        original_archive = archive.read_bytes()
        for name, mode in (("../escape", stat.S_IFREG | 0o644), ("link", stat.S_IFLNK | 0o777)):
            with self.subTest(name=name):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as package:
                    entry = zipfile.ZipInfo(name)
                    entry.external_attr = mode << 16
                    package.writestr(entry, b"target")
                archive.write_bytes(buffer.getvalue())
                self.change_manifest(lambda value: value["artifacts"][0].update(sha256=publisher.digest(buffer.getvalue())))
                with self.assertRaises(ValueError):
                    self.publish(apply=True)
                archive.write_bytes(original_archive)
                manifest_path.write_bytes(original_manifest)

    def test_locked_and_local_projection_modes_reject_tampering_and_unsafe_permissions(self):
        """主包与本地源同时改成同一错误模式也必须拒绝，不能只比较两包相等。"""
        for permission in (0o600, 0o777, 0o4755):
            with self.subTest(permission=oct(permission)):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as package:
                    entry = zipfile.ZipInfo("ordinary-file")
                    entry.external_attr = (stat.S_IFREG | permission) << 16
                    package.writestr(entry, b"content")
                with self.assertRaisesRegex(ValueError, "模式"):
                    publisher.archive_files(buffer.getvalue())

        manifest_path = self.candidate / "candidate-manifest.json"
        original_manifest = manifest_path.read_bytes()
        for host in publisher.HOSTS:
            stem = f"workflow/xy-workflow-{host}-3.0.0-alpha.5"
            primary = self.candidate / (stem + ".zip")
            local = self.candidate / (stem + "-local-source.zip")
            original_primary, original_local = primary.read_bytes(), local.read_bytes()
            prefix = "xy-workflow/" if host == "antigravity" else "plugins/xy-workflow/"
            executable = "third_party/selected-skills/playwright-cli/runtime/tool.sh"
            for change in ("local_drop_execute", "local_add_execute", "primary_drop_execute", "both_drop_execute"):
                with self.subTest(host=host, change=change):
                    files = publisher.archive_files(original_primary)
                    projected = publisher.archive_files(original_local)
                    if change in {"primary_drop_execute", "both_drop_execute"}:
                        files[executable] = (files[executable][0], "100644")
                    if change in {"local_drop_execute", "both_drop_execute"}:
                        projected[prefix + executable] = (projected[prefix + executable][0], "100644")
                    if change == "local_add_execute":
                        projected[prefix + "README.md"] = (projected[prefix + "README.md"][0], "100755")
                    primary.write_bytes(zip_bytes(files))
                    local.write_bytes(zip_bytes(projected))
                    # 重新绑定ZIP摘要以直达模式边界，避免仅证明外层摘要能拒绝篡改。
                    manifest = json.loads(original_manifest)
                    for row in manifest["artifacts"]:
                        if row["path"] in {stem + ".zip", stem + "-local-source.zip"}:
                            row["sha256"] = publisher.digest((self.candidate / row["path"]).read_bytes())
                    manifest_path.write_bytes(publisher.json_bytes(manifest))
                    with self.assertRaisesRegex(ValueError, "模式|精确插件包"):
                        publisher.load_candidate(self.candidate, self.revision, publisher.REPOSITORY)
                    primary.write_bytes(original_primary)
                    local.write_bytes(original_local)
                    manifest_path.write_bytes(original_manifest)
        self.assertEqual("", self.refs())

    def test_non_fast_forward_race_fails_atomically(self):
        initial = self.publish(apply=True)
        second = self.make_candidate("race", version="3.0.0-alpha.6")
        original_git = publisher.git
        raced = []

        def race(directory, *arguments, **kwargs):
            if arguments[0] == "push" and not raced:
                # 避免测试自身构造竞争提交时再次进入拦截器。
                with patch.object(publisher, "git", original_git):
                    raced.append(self.remote_commit("claude", {"raced.txt": (b"race", "100644")}))
            return original_git(directory, *arguments, **kwargs)

        with patch.object(publisher, "git", side_effect=race):
            with self.assertRaises(subprocess.CalledProcessError):
                self.publish(second, apply=True)
        for row in initial["branches"]:
            expected = raced[0] if row["host"] == "claude" else row["commit"]
            self.assertEqual(expected, self.git("rev-parse", row["ref"]))

    def test_atomic_server_rejection_leaves_all_three_refs_absent(self):
        hook = self.remote / "hooks/update"
        hook.write_text('#!/bin/sh\n[ "$1" != "refs/heads/plugins-claude-alpha" ]\n')
        hook.chmod(0o755)
        # 本地传输服务端需独立指定 Hook 路径；发布器禁用的是临时客户端 Hook。
        subprocess.run(["git", "-C", str(self.remote), "config", "core.hooksPath", str(self.remote / "hooks")], check=True)
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish(apply=True)
        self.assertEqual("", self.refs())


if __name__ == "__main__":
    unittest.main()
