"""薄启动器的确认边界、只读合同、发行验证和独立目录准备负控。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
from product.release_channels import version_channel


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load("plugin_config_launcher", ROOT / "plugins/maintenance/launcher.py")
store = load("plugin_component_store_test", ROOT / "plugins/maintenance/component_store.py")
builder = load("plugin_component_builder_test", ROOT / "packaging/build_agent_config.py")


class PluginConfigLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "component user root"
        self.home = self.base / "native home"
        self.project = self.base / "project with spaces; harmless"
        self.home.mkdir()
        self.project.mkdir()
        self.descriptor = self.base / "component.json"
        self.version, self.bodies = builder.payload(ROOT)
        self.artifact = self.write_package(self.bodies)
        self.write_descriptor(self.artifact)
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def write_package(self, bodies, extras=()):
        path = self.base / "component.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
                for name, body in (*bodies.items(), *extras):
                    entry = zipfile.ZipInfo(name)
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFREG | 0o600) << 16
                    package.writestr(entry, body)
        return path

    def write_descriptor(self, artifact=None, *, version=None):
        self.data = {"schema_version": 1, "product": "native-agent-config", "version": version or self.version,
                     "channel": version_channel(version or self.version), "cli_protocol": 1, "service_protocol": 2, "release_status": "unpublished",
                     "artifact": {"name": f"native-agent-config-{version or self.version}.zip",
                                  "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest() if artifact else "", "url": ""}}
        self.descriptor.write_text(json.dumps(self.data))

    def fake_command(self, command, **options):
        self.calls.append((command, options))
        action = command[2]
        args = launcher.arguments([action, "--host", "codex", "--project", str(self.project), "--home", str(self.home)])
        response = launcher.receipt(args, self.data, "ready", "ready" if action == "open" else "stopped")
        response["service"] = {"state": "ready" if action == "open" else "stopped"}
        return SimpleNamespace(stdout=json.dumps(response), stderr="", returncode=0)

    def run_launcher(self, *args, invoke=None):
        return launcher.run([*args, "--host", "codex", "--project", str(self.project), "--home", str(self.home)],
                            component_root=self.root, descriptor_path=self.descriptor,
                            invoke=invoke or self.fake_command)

    def prepare(self):
        response, code = self.run_launcher("open", "--prepare", "--artifact", str(self.artifact), "--no-browser")
        self.assertEqual(code, 0, response)
        return store.installed(self.root, self.data)

    def snapshot(self):
        return {str(path.relative_to(self.base)): (path.stat().st_mode, path.read_bytes() if path.is_file() else None)
                for path in self.base.rglob("*")}

    def test_unconfirmed_missing_component_and_readonly_actions_never_write_or_invoke(self):
        before = self.snapshot()
        for action in ("open", "status", "doctor"):
            response, code = self.run_launcher(action)
            self.assertEqual((code, response["state"]), (2, "preparation_required"))
        self.assertFalse(self.calls)
        self.assertEqual(self.snapshot(), before)
        response, code = self.run_launcher("open", "--artifact", str(self.artifact))
        self.assertEqual((code, response["code"]), (2, "preparation_confirmation_required"))
        self.assertFalse(self.root.exists())

    def test_unpublished_empty_digest_cannot_download_even_after_confirmation(self):
        self.write_descriptor()
        with patch.object(launcher, "prepare", wraps=launcher.prepare) as prepare:
            response, code = self.run_launcher("open", "--prepare")
        self.assertEqual((code, response["code"]), (1, "artifact_unavailable"))
        self.assertTrue(prepare.called)
        self.assertFalse(self.root.exists())

    def test_fixed_arguments_and_private_installation_preserve_environment_and_business_project(self):
        environment = {key: os.environ.get(key) for key in ("HOME", "CODEX_HOME", "PATH")}
        target = self.prepare()
        command, options = self.calls[0]
        self.assertEqual(command[:3], ["bash", str(target / "scripts/agent_config.sh"), "open"])
        self.assertIn(str(self.project), command)
        self.assertIn("--no-browser", command)
        self.assertFalse(options.get("shell", False))
        self.assertEqual({key: os.environ.get(key) for key in environment}, environment)
        self.assertEqual(list(self.project.iterdir()), [])
        for path in (self.root, self.root / "versions", target, self.root / "registry.json"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
        before = self.snapshot()
        for action in ("status", "doctor"):
            response, code = self.run_launcher(action)
            self.assertEqual((code, response["state"]), (0, "stopped"))
        self.assertEqual(self.snapshot(), before, "只读调用不得创建锁、目录或修权限")

    def test_readonly_rejects_prepare_browser_and_untrusted_argument_injection(self):
        for args in (("status", "--prepare"), ("doctor", "--no-browser"),
                     ("open", "--host=codex;touch /tmp/injected"), ("console",)):
            response, code = launcher.run(list(args), component_root=self.root, descriptor_path=self.descriptor)
            self.assertEqual(code, 2, response)
        self.assertFalse(self.root.exists())

    def test_hash_mismatch_leaves_no_active_or_version(self):
        self.artifact.write_bytes(self.artifact.read_bytes() + b"changed")
        response, code = self.run_launcher("open", "--prepare", "--artifact", str(self.artifact))
        self.assertEqual((code, response["code"]), (1, "artifact_digest_mismatch"))
        self.assertFalse((self.root / "registry.json").exists())
        self.assertEqual(list((self.root / "versions").iterdir()), [])

    def test_zip_slip_duplicate_build_tamper_and_version_tamper_are_rejected(self):
        cases = [({**self.bodies, "../outside": b"bad"}, ()),
                 (self.bodies, (("scripts/agent_config.sh", b"duplicate"),)),
                 ({**self.bodies, "native_config/cli.py": b"tampered"}, ()),
                 ({**self.bodies, "native_config/VERSION": b"99.0.0-alpha.1"}, ())]
        for bodies, extras in cases:
            with self.subTest(extras=bool(extras), names=set(bodies) - set(self.bodies)):
                artifact = self.write_package(bodies, extras)
                self.write_descriptor(artifact)
                response, code = self.run_launcher("open", "--prepare", "--artifact", str(artifact))
                self.assertEqual(code, 1, response)
                self.assertFalse((self.root / "registry.json").exists())
                self.assertFalse((self.base / "outside").exists())
        self.assertFalse(self.calls)

    def test_symlink_zip_entry_rejected(self):
        with zipfile.ZipFile(self.artifact, "a") as package:
            entry = zipfile.ZipInfo("native_config/linked.py")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(entry, "../../outside")
        self.write_descriptor(self.artifact)
        response, code = self.run_launcher("open", "--prepare", "--artifact", str(self.artifact))
        self.assertEqual((code, response["code"]), (1, "unsafe_archive_entry"))

    def test_registry_traversal_symlink_and_installed_tamper_are_readonly_failures(self):
        target = self.prepare()
        registry = self.root / "registry.json"
        original = registry.read_bytes()
        record = json.loads(original)
        record["directory"] = "../outside"
        registry.write_text(json.dumps(record))
        before = self.snapshot()
        response, code = self.run_launcher("doctor")
        self.assertEqual((code, response["code"]), (1, "invalid_registry"))
        self.assertEqual(self.snapshot(), before)
        registry.write_bytes(original)
        (target / "native_config/cli.py").write_text("tampered")
        before = self.snapshot()
        response, code = self.run_launcher("status")
        self.assertEqual((code, response["code"]), (1, "build_digest_mismatch"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.calls), 1)

    def test_component_root_symlink_is_never_followed(self):
        actual = self.base / "actual"
        actual.mkdir(mode=0o700)
        self.root.symlink_to(actual, target_is_directory=True)
        response, code = self.run_launcher("open", "--prepare", "--artifact", str(self.artifact))
        self.assertEqual((code, response["code"]), (1, "unsafe_component_path"))
        self.assertEqual(list(actual.iterdir()), [])

    def test_rewriting_build_with_installed_files_cannot_replace_pinned_artifact_proof(self):
        target = self.prepare()
        changed = target / "native_config/cli.py"
        changed.write_text("# 同时伪造文件和本地 BUILD，仍不能替换外层固定摘要证明。\n")
        manifest_path = target / "BUILD.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["native_config/cli.py"] = hashlib.sha256(changed.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        before = self.snapshot()
        response, code = self.run_launcher("doctor")
        self.assertEqual((code, response["code"]), (1, "installed_payload_mismatch"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.calls), 1)

    def real_release(self):
        """使用真实独立构建器和全部原生源文件，不以缩小载荷或模拟准备过程代替发行 ZIP。"""
        report = builder.build(ROOT, self.base / "real-current-release")
        return Path(report["artifact"]), report["version"]

    def retain_historical_release(self):
        """重建真实 alpha4 的 30 成员／29 BUILD 项形态，模拟旧安装器已经发布的库存。

        当前构建器已强制加入身份合同，不能再用当前 prepare 安装旧形态来布置前置状态。
        这里仅保留当时封闭的文件集合、原始 ZIP 和登记；旧源码不会作为运行入口执行，
        因此回归不依赖开发者本机库存、历史下载或 CI 工作区之外的文件。
        """
        version = "0.1.0-alpha.4"
        bodies = {name: body for name, body in self.bodies.items()
                  if name != "BUILD.json" and not name.startswith("product/")}
        bodies["native_config/VERSION"] = (version + "\n").encode("ascii")
        manifest = {"name": store.PRODUCT, "version": version, "third_party_dependencies": [],
                    "files": {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()}}
        bodies["BUILD.json"] = json.dumps(manifest, sort_keys=True).encode()
        self.assertEqual((len(bodies), len(manifest["files"])), (30, 29))
        artifact = self.write_package(bodies)
        self.write_descriptor(artifact, version=version)
        self.root.mkdir(mode=0o700)
        versions = self.root / "versions"
        versions.mkdir(mode=0o700)
        artifacts = self.root / "artifacts"
        artifacts.mkdir(mode=0o700)
        digest = self.data["artifact"]["sha256"]
        cached = artifacts / (digest + ".zip")
        cached.write_bytes(artifact.read_bytes())
        cached.chmod(0o600)
        target = versions / store.directory_name(self.data)
        target.mkdir(mode=0o700)
        for name, body in bodies.items():
            destination = target / name
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(body)
            destination.chmod(0o700 if name.endswith(".sh") else 0o600)
        registry = self.root / "registry.json"
        registry.write_text(json.dumps({"schema_version": 1, "product": store.PRODUCT,
                                       "version": version, "sha256": digest,
                                       "directory": "versions/" + target.name}))
        registry.chmod(0o600)
        return target

    def fail_registry_publish_once(self, artifact):
        """故障只发生在最后一次原子登记；ZIP、解包、目录发布和重试均走真实文件系统实现。"""
        replace = store.os.replace
        failures = []
        def fail_once(source, destination):
            if Path(destination) == self.root / "registry.json" and not failures:
                failures.append(True)
                raise OSError(errno.ENOSPC, "injected registry publish failure")
            return replace(source, destination)
        with patch.object(store.os, "replace", side_effect=fail_once):
            with self.assertRaises(OSError):
                store.prepare(self.root, self.data, artifact)
        self.assertEqual(failures, [True])
        return self.root / "versions" / store.directory_name(self.data)

    def version_snapshot(self, target):
        return {str(path.relative_to(target)): (path.stat().st_ino, path.stat().st_mode,
                    path.read_bytes() if path.is_file() else None) for path in (target, *target.rglob("*"))}

    def test_real_zip_first_registry_publish_failure_can_retry_without_overwriting_version(self):
        artifact, version = self.real_release()
        self.write_descriptor(artifact, version=version)
        target = self.fail_registry_publish_once(artifact)
        self.assertTrue(target.is_dir())
        self.assertFalse((self.root / "registry.json").exists())
        before = self.version_snapshot(target)
        retried = store.prepare(self.root, self.data, artifact)
        self.assertEqual(retried, target)
        self.assertEqual(store.installed(self.root, self.data), target)
        self.assertEqual(self.version_snapshot(target), before, "重试只能补登记，不能覆盖已发布版本文件")
        self.assertEqual(len(list((self.root / "versions").iterdir())), 1)
        self.assertFalse(list(self.root.glob(".preparing-*")))

    def test_real_zip_upgrade_registry_publish_failure_keeps_old_active_and_retries(self):
        old_target = self.retain_historical_release()
        old_data = self.data
        old_files = self.version_snapshot(old_target)
        old_registry = (self.root / "registry.json").read_bytes()
        artifact, version = self.real_release()
        # 升级重试测试使用真实构建 ZIP；仓库 descriptor 只有真实资产发布下载后才
        # 允许更新，不能把当前源码版本尚未发布的时段误判为库存准备回归。固定发行
        # 的摘要绑定由候选／发行装配消费者独立验证。
        self.assertEqual(version_channel(version), "stable")
        self.write_descriptor(artifact, version=version)
        self.assertNotEqual(self.data["version"], old_data["version"])
        target = self.fail_registry_publish_once(artifact)
        self.assertEqual((self.root / "registry.json").read_bytes(), old_registry)
        # 旧库存可认证和保留，但不能因为登记中的版本/摘要自洽就充当当前 ABI。
        self.assertIsNone(store.installed(self.root, self.data))
        self.assertEqual(self.version_snapshot(old_target), old_files)
        new_files = self.version_snapshot(target)
        retried = store.prepare(self.root, self.data, artifact)
        self.assertEqual(retried, target)
        self.assertEqual(store.installed(self.root, self.data), target)
        self.assertEqual(self.version_snapshot(target), new_files)
        self.assertEqual(self.version_snapshot(old_target), old_files)
        self.assertEqual(len(list((self.root / "versions").iterdir())), 2)
        response, code = self.run_launcher("open", "--no-browser")
        self.assertEqual(code, 0, response)
        self.assertEqual(self.calls[0][0][1], str(target / "scripts/agent_config.sh"))

    def test_current_release_missing_identity_is_rejected_with_consistent_manifest(self):
        # 重算 BUILD 与外层摘要，确保拒绝原因是当前 ABI 缺失，而不是普通摘要损坏。
        for missing in ("product/__init__.py", "product/command_identity.py", "product/command_identity.json", "product/release_channels.py"):
            with self.subTest(missing=missing):
                bodies = {name: body for name, body in self.bodies.items() if name != missing}
                manifest = json.loads(bodies["BUILD.json"])
                del manifest["files"][missing]
                bodies["BUILD.json"] = json.dumps(manifest, sort_keys=True).encode()
                artifact = self.write_package(bodies)
                self.write_descriptor(artifact)
                with self.assertRaises(store.ComponentError) as error:
                    store.archive_payload(artifact, self.version, self.data["artifact"]["sha256"])
                self.assertEqual(str(error.exception), "invalid_build_manifest")
                response, code = self.run_launcher("open", "--prepare", "--artifact", str(artifact))
                self.assertEqual((code, response["code"]), (1, "invalid_build_manifest"))
                self.assertFalse((self.root / "registry.json").exists())
                self.assertEqual(list((self.root / "versions").iterdir()), [])
        self.assertFalse(self.calls)

    def test_historical_inventory_cannot_bypass_current_abi_on_selection_or_retry(self):
        target = self.retain_historical_release()
        # 同一个已认证旧库存若被显式选为当前发行，仍不得返回运行路径。
        before = self.snapshot()
        with self.assertRaises(store.ComponentError) as error:
            store.installed(self.root, self.data)
        self.assertEqual(str(error.exception), "invalid_build_manifest")
        self.assertEqual(self.snapshot(), before)
        # 模拟版本已发布、最后登记未成功的状态；重试也不能借历史认证补成当前版本。
        (self.root / "registry.json").unlink()
        with store.preparation_lock(self.root):
            pass
        before = self.snapshot()
        with self.assertRaises(store.ComponentError) as error:
            store.prepare(self.root, self.data, self.artifact)
        self.assertEqual(str(error.exception), "invalid_build_manifest")
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(target.is_dir())

    def test_registry_retry_rejects_tampered_retained_real_zip_version(self):
        artifact, version = self.real_release()
        self.write_descriptor(artifact, version=version)
        target = self.fail_registry_publish_once(artifact)
        (target / "native_config/cli.py").write_text("# 已发布但尚未登记的版本被外部篡改。\n")
        before = self.version_snapshot(target)
        with self.assertRaises(store.ComponentError) as error:
            store.prepare(self.root, self.data, artifact)
        self.assertEqual(str(error.exception), "build_digest_mismatch")
        self.assertFalse((self.root / "registry.json").exists())
        self.assertEqual(self.version_snapshot(target), before)

    def test_installed_stable_rejects_downgrade_and_same_version_rebinding(self):
        self.prepare()
        before = self.snapshot()
        # 旧库存认证仍走自身原包；拒绝发生在选择新目标阶段，不覆盖任何活动版本。
        for version, digest, code in (("0.1.0-alpha.5", "a" * 64, "component_downgrade"),
                                      (self.version, "b" * 64, "component_version_conflict")):
            data = {**self.data, "version": version, "channel": version_channel(version),
                    "artifact": {**self.data["artifact"], "sha256": digest,
                                 "name": f"native-agent-config-{version}.zip"}}
            with self.subTest(version=version), self.assertRaises(store.ComponentError) as error:
                store.prepare(self.root, data, self.artifact)
            self.assertEqual(code, str(error.exception))
            self.assertEqual(before, self.snapshot())

    def test_concurrent_preparation_registers_one_immutable_version(self):
        def prepare(_):
            return self.run_launcher("open", "--prepare", "--artifact", str(self.artifact))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(prepare, range(4)))
        self.assertTrue(all(code == 0 for _, code in results), results)
        self.assertEqual(len(list((self.root / "versions").iterdir())), 1)
        self.assertFalse(list(self.root.glob(".preparing-*")))
        store.installed(self.root, self.data)

    def test_failure_after_old_install_preserves_active_bytes_and_version(self):
        target = self.prepare()
        old_registry = (self.root / "registry.json").read_bytes()
        old_script = (target / "scripts/agent_config.sh").read_bytes()
        self.write_descriptor(self.artifact, version="99.0.0-alpha.1")
        response, code = self.run_launcher("open", "--prepare", "--artifact", str(self.artifact))
        self.assertEqual(code, 1, response)
        self.assertEqual((self.root / "registry.json").read_bytes(), old_registry)
        self.assertEqual((target / "scripts/agent_config.sh").read_bytes(), old_script)
        self.assertEqual(len(list((self.root / "versions").iterdir())), 1)

    def test_browser_failure_ready_receipt_and_private_launch_file_are_preserved(self):
        self.prepare()
        def browser_failed(command, **options):
            result = self.fake_command(command, **options)
            report = json.loads(result.stdout)
            report.update(code="browser_failed", launch_file=str(self.root / "state/private-launch.html"),
                          console_url="http://127.0.0.1:12345/")
            report["browser"] = {"state": "failed"}
            return SimpleNamespace(stdout=json.dumps(report), stderr="secret", returncode=3)
        response, code = self.run_launcher("open", invoke=browser_failed)
        self.assertEqual((code, response["state"], response["code"]), (3, "ready", "browser_failed"))
        self.assertTrue(response["launch_file"])

    def test_legacy_token_url_and_raw_exception_never_escape(self):
        self.prepare()
        def legacy(command, **options):
            result = self.fake_command(command, **options)
            response = json.loads(result.stdout)
            response["console_url"] = "http://127.0.0.1:1234/#token=highly-private"
            return SimpleNamespace(stdout=json.dumps(response), stderr="highly-private", returncode=0)
        response, code = self.run_launcher("open", invoke=legacy)
        self.assertEqual((code, response["code"]), (1, "invalid_component_response"))
        self.assertNotIn("highly-private", json.dumps(response))


if __name__ == "__main__":
    unittest.main()
