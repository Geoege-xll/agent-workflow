"""真实远程安装验收的离线安全合同；这里不下载、不安装、不调用用户机官方客户端。"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("remote_install_smoke", ROOT / "scripts/test_remote_plugin_install.py")
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def sample_hashes(plugin_version, native_version):
    """使用三宿主共享的七包路径；两种产品分别指定版本，摘要只是离线合同样本。"""
    files = {f"workflow/xy-workflow-{host}-{plugin_version}{suffix}.zip": "e" * 64
             for host in ("codex", "claude", "antigravity") for suffix in ("", "-local-source")}
    files[f"native/native-agent-config-{native_version}.zip"] = "f" * 64
    return files


class RemoteInstallSmokeContractTest(unittest.TestCase):
    def test_fixed_official_vendor_versions_and_integrities(self):
        fixture = ROOT / "tests/fixtures/native-install"
        package = json.loads((fixture / "package.json").read_text())
        self.assertEqual({"@openai/codex": "0.167.0", "@anthropic-ai/claude-code": "2.1.311"},
                         package["dependencies"])
        lock = json.loads((fixture / "package-lock.json").read_text())
        self.assertEqual(package["dependencies"], lock["packages"][""]["dependencies"])
        for name, record in lock["packages"].items():
            if not name:
                continue
            self.assertTrue(record["resolved"].startswith("https://registry.npmjs.org/"), name)
            self.assertRegex(record["integrity"], r"^sha512-[A-Za-z0-9+/]+={0,2}$")
            self.assertTrue(name.startswith(("node_modules/@openai/codex", "node_modules/@anthropic-ai/claude-code")))
        agy = json.loads((fixture / "antigravity-linux-amd64.json").read_text())
        self.assertEqual("1.5.6", agy["version"])
        self.assertEqual("https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_amd64.json",
                         agy["manifest_url"])
        self.assertEqual("https://storage.googleapis.com/antigravity-public/antigravity-cli/1.5.6-6212266538958848/linux-x64/cli_linux_x64.tar.gz",
                         agy["url"])
        self.assertEqual("0c67824908caf9cc3156699802b8097f2fd02c4608ae9293c9aa7f17e1bcd342c4b9c2e158388253a37804ef6bd9c6b1d25cfaca3c07bbb7587378fc91839bb4",
                         agy["sha512"])

    def test_manual_workflow_is_read_only_and_uses_natural_runner(self):
        workflow = (ROOT / ".github/workflows/native-install-smoke.yml").read_text()
        for fragment in ("  workflow_dispatch:", "  contents: read", "runs-on: ubuntu-latest",
                         "github.ref == 'refs/heads/main'", "persist-credentials: false",
                         "ref: ${{ github.sha }}", "npm ci", "--registry https://registry.npmjs.org",
                         "scripts/test_remote_plugin_install.py", "if-no-files-found: error", "overwrite: false",
                         "      - name: Summarize installation evidence\n        if: always()",
                         "always() && steps.summary.outputs.has_receipt == 'true'"):
            self.assertIn(fragment, workflow)
        for forbidden in ("contents: write", "  push:", "  pull_request:", "inputs:", "CODEX_HOME",
                          "CLAUDE_CONFIG_DIR", "HOME:", "export HOME", "secrets.", "windows-latest"):
            self.assertNotIn(forbidden, workflow)

    def test_workflow_summarizes_skipped_and_missing_receipts(self):
        # 直接执行 CI 的汇总脚本，覆盖依赖安装失败、验收未生成回执和已有失败回执。
        # 安装客户端、联网及上传均由实际 CI 执行，离线测试只检查本地汇总行为。
        workflow = (ROOT / ".github/workflows/native-install-smoke.yml").read_text()
        step = workflow.split("      - name: Summarize installation evidence\n", 1)[1].split("\n      - ", 1)[0]
        self.assertIn("        run: |\n", step)
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for install, smoke, receipt, status, expected in (
                ("failure", "skipped", False, 0, "failure"),
                ("success", "failure", False, 1, "缺少"),
                ("success", "failure", True, 0, '{"status":"failed"}'),
            ):
                if receipt:
                    (root / "native-install-smoke.json").write_text('{"status":"failed"}')
                summary, output = root / "summary", root / "output"
                summary.write_text("")
                output.write_text("")
                env = {**SMOKE.os.environ, "RUNNER_TEMP": str(root), "GITHUB_STEP_SUMMARY": str(summary),
                       "GITHUB_OUTPUT": str(output), "CLIENT_OUTCOME": install, "SMOKE_OUTCOME": smoke}
                result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
                self.assertEqual(status, result.returncode, result.stderr)
                self.assertIn(expected, summary.read_text())
                self.assertEqual("has_receipt=" + str(receipt).lower(), output.read_text().strip())

    def test_runner_boundary_refuses_local_machine_redirected_home_and_credentials(self):
        good = {"HOME": "/home/runner", "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
                "GITHUB_SHA": "a" * 40}
        with patch.object(SMOKE.pwd, "getpwuid", return_value=types.SimpleNamespace(pw_dir="/home/runner")), \
                patch.object(SMOKE.platform, "system", return_value="Linux"), \
                patch.object(SMOKE.platform, "machine", return_value="x86_64"):
            self.assertEqual(Path("/home/runner").resolve(), SMOKE.require_fresh_runner(good))
            for change in ({"GITHUB_ACTIONS": "false"}, {"RUNNER_ENVIRONMENT": "self-hosted"},
                           {"HOME": "/tmp/fake-home"}, {"CODEX_HOME": "/tmp/fake-codex"},
                           {"OPENAI_API_KEY": "test-only-secret"}, {"GITHUB_SHA": "main"}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    SMOKE.require_fresh_runner({**good, **change})

    def test_cache_verification_uses_full_source_bound_file_closure(self):
        with tempfile.TemporaryDirectory(prefix="native-smoke-contract-") as temporary:
            root = Path(temporary)
            version, revision = "3.0.0-alpha.5", "a" * 40
            for host in ("codex", "claude", "antigravity"):
                with self.subTest(host=host):
                    plugin = root / host
                    plugin.mkdir()
                    (plugin / "sources.json").write_text(json.dumps({"host": host, "plugin_version": version}))
                    (plugin / "run.sh").write_text("#!/bin/sh\n# 中文夹具：仅核验字节与执行位，不执行。\n")
                    (plugin / "run.sh").chmod(0o755)
                    prefix = "" if host == "antigravity" else "plugins/xy-workflow/"
                    files = {prefix + path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                  "mode": "100755" if path.name == "run.sh" else "100644"}
                             for path in plugin.iterdir()}
                    record = {"schema_version": 1, "managed_by": "agent-workflow-plugin-source-v1",
                              "repository": "Geoege-xll/agent-workflow", "host": host, "channel": "alpha",
                              "ref": "refs/heads/plugins-" + host + "-alpha", "source_revision": revision,
                              "version": version, "files": files, "candidate_sha256": "c" * 64,
                              "source_tree_sha256": "d" * 64, "plugin_zip_sha256": "e" * 64,
                              "artifacts_sha256": sample_hashes(version, "0.1.0-alpha.2")}
                    if host != "antigravity":
                        record["files"][".marketplace/ignored.json"] = {"sha256": "0" * 64, "mode": "100644"}
                    report = SMOKE.verify_installed(plugin, record, host, revision, version)
                    self.assertEqual(2, report["files"])
                    # AGY 安装整个分发根；Codex/Claude 只复制插件子目录。只有前者的
                    # 普通缓存会带外层 distribution.json，后两者出现同名文件应计为额外项。
                    distribution = plugin / "distribution.json"
                    distribution.write_text(json.dumps(record))
                    if host == "antigravity":
                        SMOKE.verify_installed(plugin, record, host, revision, version)
                    else:
                        with self.assertRaises(SMOKE.FileClosureMismatch) as mismatch:
                            SMOKE.verify_installed(plugin, record, host, revision, version)
                        self.assertEqual(["distribution.json"], mismatch.exception.details["extra_files"])
                    distribution.unlink()
                    # 真实缓存不匹配时仍严拒；异常只报告精确相对名单，不忽略任何额外载荷。
                    modified = copy.deepcopy(record)
                    modified["files"][prefix + "missing.bin"] = {"sha256": "0" * 64, "mode": "100644"}
                    (plugin / "unexpected.bin").write_bytes(b"extra")
                    with self.assertRaises(SMOKE.FileClosureMismatch) as failure:
                        SMOKE.verify_installed(plugin, modified, host, revision, version)
                    self.assertEqual({"missing_files": ["missing.bin"], "extra_files": ["unexpected.bin"]},
                                     failure.exception.details)
                    (plugin / "unexpected.bin").unlink()
                    for field, wrong in (("schema_version", 2), ("managed_by", "other-publisher"),
                                         ("plugin_zip_sha256", "0" * 64), ("source_revision", "b" * 40), ("version", "3.0.0-alpha.4"),
                                         ("repository", "other/repo"), ("host", "wrong"),
                                         ("channel", "stable"), ("ref", "refs/heads/main")):
                        modified = copy.deepcopy(record)
                        modified[field] = wrong
                        with self.subTest(field=field), self.assertRaises(ValueError):
                            SMOKE.verify_installed(plugin, modified, host, revision, version)
                    (plugin / "run.sh").chmod(0o644)
                    with self.assertRaises(ValueError):
                        SMOKE.verify_installed(plugin, record, host, revision, version)
                    (plugin / "run.sh").chmod(0o755)
                    # 普通配置文件的组执行位也属于多出的权限，不能只验证所有者位。
                    (plugin / "sources.json").chmod(0o654)
                    with self.assertRaises(ValueError):
                        SMOKE.verify_installed(plugin, record, host, revision, version)
                    (plugin / "sources.json").chmod(0o644)
                    (plugin / "sources.json").write_text("changed")
                    with self.assertRaises(ValueError):
                        SMOKE.verify_installed(plugin, record, host, revision, version)

    def create_agy_git_fixture(self, root):
        # 夹具只在临时目录创建真实 Git 元数据，不联网、不运行宿主客户端或用户 hook。
        version, revision = "3.0.0-alpha.5", "a" * 40
        (root / "sources.json").write_text(json.dumps({"host": "antigravity", "plugin_version": version}))
        (root / "run.sh").write_text("#!/bin/sh\n# 中文夹具：只核验，不执行。\n")
        (root / "run.sh").chmod(0o755)
        files = {path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "mode": "100755" if path.name == "run.sh" else "100644"}
                 for path in root.iterdir()}
        record = {"schema_version": 1, "managed_by": "agent-workflow-plugin-source-v1",
                  "repository": "Geoege-xll/agent-workflow", "host": "antigravity", "channel": "alpha",
                  "ref": "refs/heads/plugins-antigravity-alpha", "source_revision": revision,
                  "version": version, "files": files, "candidate_sha256": "c" * 64,
                  "source_tree_sha256": "d" * 64, "plugin_zip_sha256": "e" * 64,
                  "artifacts_sha256": sample_hashes(version, "0.1.0-alpha.2")}
        SMOKE.command(["git", "init", "--quiet", "--initial-branch=plugins-antigravity-alpha"], root)
        SMOKE.command(["git", "add", "sources.json", "run.sh"], root)
        SMOKE.command(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                       "-c", "user.name=Smoke fixture", "-c", "user.email=smoke@example.invalid",
                       "commit", "--quiet", "-m", "Fixture only"], root)
        SMOKE.command(["git", "remote", "add", "origin", SMOKE.REMOTE], root)
        commit = SMOKE.command(["git", "rev-parse", "HEAD"], root)
        return record, revision, version, commit

    def test_agy_git_metadata_requires_identity_and_preserves_payload_checks(self):
        with tempfile.TemporaryDirectory(prefix="native-smoke-git-") as temporary:
            root = Path(temporary).resolve()
            record, revision, version, commit = self.create_agy_git_fixture(root)
            def verify(expected=commit):
                return SMOKE.verify_installed(root, record, "antigravity", revision, version,
                                              distribution_commit=expected)
            report = verify()
            self.assertEqual(2, report["files"])
            self.assertEqual(commit, report["verified_git_metadata"]["head"])
            self.assertEqual("plugins-antigravity-alpha", report["verified_git_metadata"]["branch"])
            self.assertEqual(SMOKE.REMOTE, report["verified_git_metadata"]["origin"])
            self.assertGreater(report["verified_git_metadata"]["files"], 0)
            # 普通未记录的空目录没有可枚举的文件，但仍属于安装根额外节点；
            # 已核实的 .git 内部目录保留宿主所有权，无需写入插件分发记录。
            extra_directory = root / "unused"
            extra_directory.mkdir()
            with self.assertRaises(SMOKE.FileClosureMismatch) as mismatch:
                verify()
            self.assertEqual(["unused"], mismatch.exception.details["extra_files"])
            extra_directory.rmdir()
            for other_host in ("codex", "claude"):
                self.assertEqual((set(), None), SMOKE.verified_git_metadata(root, other_host, commit))
            for expected in (None, "0" * 40):
                with self.subTest(expected=expected), self.assertRaises(ValueError):
                    verify(expected)
            SMOKE.command(["git", "remote", "set-url", "origin", "https://github.com/other/repository.git"], root)
            with self.assertRaises(ValueError):
                verify()
            SMOKE.command(["git", "remote", "set-url", "origin", SMOKE.REMOTE], root)
            SMOKE.command(["git", "branch", "-m", "unexpected"], root)
            with self.assertRaises(ValueError):
                verify()
            SMOKE.command(["git", "branch", "-m", "plugins-antigravity-alpha"], root)
            (root / "unexpected.bin").write_bytes(b"not Git metadata")
            with self.assertRaises(SMOKE.FileClosureMismatch) as failure:
                verify()
            self.assertEqual(["unexpected.bin"], failure.exception.details["extra_files"])
            (root / "unexpected.bin").unlink()
            (root / "run.sh").chmod(0o644)
            with self.assertRaises(ValueError):
                verify()
            (root / "run.sh").chmod(0o755)
            (root / "sources.json").write_text("changed payload")
            with self.assertRaises(ValueError):
                verify()

    def test_agy_git_metadata_rejects_symlinks_and_redirected_gitdir(self):
        with tempfile.TemporaryDirectory(prefix="native-smoke-git-") as temporary:
            root = Path(temporary).resolve()
            record, revision, version, commit = self.create_agy_git_fixture(root)
            def verify():
                return SMOKE.verify_installed(root, record, "antigravity", revision, version,
                                              distribution_commit=commit)
            link = root / ".git/redirected-file"
            link.symlink_to(root / "sources.json")
            with self.assertRaises(ValueError):
                verify()
            link.unlink()
            metadata = root / ".git"
            backup = root / ".git-backup"
            metadata.rename(backup)
            metadata.symlink_to(backup, target_is_directory=True)
            with self.assertRaises(ValueError):
                verify()
            metadata.unlink()
            metadata.write_text("gitdir: .git-backup\n")
            with self.assertRaises(ValueError):
                verify()

    def test_git_tree_binds_executable_mode_as_well_as_bytes(self):
        # 使用真实的临时 Git 索引固定正常脚本及分发记录。文件字节始终一致，
        # 仅更改声明的执行位即可检出只检查名称和内容时遗漏的合同差异。
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            record, _, _, _ = self.create_agy_git_fixture(root)
            descriptor = "plugins/maintenance/component.json"
            component = {"schema_version": 1, "product": "native-agent-config", "version": "0.1.0-alpha.2",
                         "channel": "alpha", "cli_protocol": 1, "service_protocol": 2,
                         "release_status": "unpublished", "artifact": {
                             "name": "native-agent-config-0.1.0-alpha.2.zip", "sha256": "f" * 64, "url": ""}}
            (root / descriptor).parent.mkdir(parents=True)
            (root / descriptor).write_text(json.dumps(component))
            record["files"][descriptor] = {"mode": "100644",
                "sha256": hashlib.sha256((root / descriptor).read_bytes()).hexdigest()}
            (root / "distribution.json").write_text(json.dumps(record))
            SMOKE.command(["git", "add", "distribution.json", descriptor], root)
            tree = SMOKE.command(["git", "write-tree"], root)
            SMOKE.verify_git_tree(root, tree, record, "antigravity")
            record["files"]["run.sh"]["mode"] = "100644"
            with self.assertRaisesRegex(ValueError, "模式"):
                SMOKE.verify_git_tree(root, tree, record, "antigravity")
            record["files"]["run.sh"]["mode"] = "100755"
            record["artifacts_sha256"]["native/native-agent-config-0.1.0-alpha.2.zip"] = "a" * 64
            with self.assertRaises(ValueError):
                SMOKE.verify_git_tree(root, tree, record, "antigravity")

            # 历史 alpha 的空字符串表示尚未冻结。对每种 JSON 类型重新生成真实 Git 树
            # 和对应文件摘要，确保拒绝来自描述合同，而非工作树改动或闭包失配。
            def verify_component(value):
                (root / descriptor).write_text(json.dumps(value))
                record["files"][descriptor]["sha256"] = hashlib.sha256((root / descriptor).read_bytes()).hexdigest()
                (root / "distribution.json").write_text(json.dumps(record))
                SMOKE.command(["git", "add", "distribution.json", descriptor], root)
                tree = SMOKE.command(["git", "write-tree"], root)
                SMOKE.verify_git_tree(root, tree, record, "antigravity")

            component["artifact"]["sha256"] = ""
            verify_component(component)
            for key, value in (("sha256", None), ("sha256", False), ("sha256", []), ("url", None)):
                modified = copy.deepcopy(component)
                modified["artifact"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    verify_component(modified)
            for key, value in (("product", "workflow-core"), ("cli_protocol", True),
                               ("schema_version", 1.0), ("release_status", "published")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    verify_component({**component, key: value})

            # 正式渠道要求先发布组件，再绑定核实的固定 GitHub 资产来源。
            record.update(channel="stable", artifacts_sha256=sample_hashes("3.0.1", "0.1.1"))
            component.update(version="0.1.1", channel="stable")
            component["artifact"].update(name="native-agent-config-0.1.1.zip", sha256="f" * 64)
            with self.assertRaisesRegex(ValueError, "发布"):
                verify_component(component)
            component["release_status"] = "published"
            component["artifact"]["url"] = "https://example.com/native-agent-config-0.1.1.zip"
            with self.assertRaisesRegex(ValueError, "来源"):
                verify_component(component)
            component["artifact"]["url"] = ("https://github.com/Geoege-xll/agent-workflow/releases/download/"
                                             "native-agent-config-v0.1.1/native-agent-config-0.1.1.zip")
            verify_component(component)

    def test_agy_download_failure_leaves_an_installation_receipt(self):
        # 用受控下载失败模拟 CI 网络中断，断言入口保留准确阶段且仍向 CI 传递失败。
        # 客户端准备发生在宿主命令之前，离线用例不会安装或运行任何真实客户端。
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "receipt.json"
            with patch.dict(SMOKE.os.environ, {"RUNNER_TEMP": str(root), "GITHUB_SHA": "a" * 40}), \
                 patch.object(SMOKE, "require_fresh_runner", return_value=root), \
                 patch.object(SMOKE, "install_agy", side_effect=OSError("下载中断")), \
                 self.assertRaisesRegex(OSError, "下载中断"):
                SMOKE.smoke(root, output)
            self.assertTrue(output.is_file(), "客户端下载失败也应留下本次安装验收回执")
            receipt = json.loads(output.read_text())
            self.assertEqual("INSTALL_DISCOVERY_BYTES_FAILED", receipt["status"])
            self.assertEqual("antigravity", receipt["failure"]["host"])
            self.assertEqual("client_preparation", receipt["failure"]["stage"])

    def test_failed_receipt_retains_completed_hosts_and_precise_safe_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix="native-smoke-receipt-") as temporary:
            output = Path(temporary) / "receipt.json"
            evidence = {"status": "INSTALL_DISCOVERY_BYTES_VERIFIED", "runtime_verified": False,
                        "model_sessions_started": 0, "hosts": {"codex": {"files": 3}},
                        "progress": {"host": "antigravity", "stage": "installed_file_closure_verification"}}
            with self.assertRaises(SMOKE.FileClosureMismatch):
                with SMOKE.evidence_receipt(output, evidence):
                    raise SMOKE.FileClosureMismatch("antigravity", ["missing.bin"], [".git/HEAD"])
            receipt = json.loads(output.read_text())
            self.assertEqual("INSTALL_DISCOVERY_BYTES_FAILED", receipt["status"])
            self.assertEqual({"codex": {"files": 3}}, receipt["hosts"])
            self.assertEqual("antigravity", receipt["failure"]["host"])
            self.assertEqual("installed_file_closure_verification", receipt["failure"]["stage"])
            self.assertEqual(["missing.bin"], receipt["failure"]["missing_files"])
            self.assertEqual([".git/HEAD"], receipt["failure"]["extra_files"])
            self.assertFalse(receipt["runtime_verified"])
            self.assertEqual(0, receipt["model_sessions_started"])
            self.assertNotIn("progress", receipt)

    def test_success_receipt_drops_progress_and_preserves_verified_status(self):
        with tempfile.TemporaryDirectory(prefix="native-smoke-receipt-") as temporary:
            output = Path(temporary) / "receipt.json"
            evidence = {"status": "INSTALL_DISCOVERY_BYTES_VERIFIED", "hosts": {},
                        "progress": {"host": "antigravity", "stage": "distribution_tip_recheck"}}
            with SMOKE.evidence_receipt(output, evidence):
                evidence["hosts"]["antigravity"] = {"files": 3}
            receipt = json.loads(output.read_text())
            self.assertEqual("INSTALL_DISCOVERY_BYTES_VERIFIED", receipt["status"])
            self.assertEqual({"antigravity": {"files": 3}}, receipt["hosts"])
            self.assertNotIn("progress", receipt)
            self.assertNotIn("failure", receipt)

    def test_git_tree_timeout_records_stage_and_keeps_smoke_failure(self):
        # 安装验收在回执范围内核验远程树。受控 ls-tree 超时应原样中止安装，
        # 且回执必须保留当前宿主和阶段，使 CI 可汇总实际故障。
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "receipt.json"
            evidence = {"progress": {"host": "antigravity", "stage": "distribution_source_verification"}}
            record = {"files": {"plugins/maintenance/component.json": {"mode": "100644"}}}
            with patch.object(subprocess, "check_output", side_effect=subprocess.TimeoutExpired("git ls-tree", 180)), \
                 self.assertRaises(subprocess.TimeoutExpired), SMOKE.evidence_receipt(output, evidence):
                SMOKE.verify_git_tree(root, "HEAD", record, "antigravity")
            report = json.loads(output.read_bytes())
            self.assertEqual("INSTALL_DISCOVERY_BYTES_FAILED", report["status"])
            self.assertEqual("TimeoutExpired", report["failure"]["type"])
            self.assertEqual("antigravity", report["failure"]["host"])
            self.assertEqual("distribution_source_verification", report["failure"]["stage"])

    def test_stable_distribution_and_git_metadata_require_exact_channel(self):
        # 使用同一真实 AGY Git 夹具转换正式版本／分支，既保留历史 alpha 用例，
        # 又验证默认源码版本推导和显式 stable 不会放宽来源、载荷或 Git 身份检查。
        with tempfile.TemporaryDirectory(prefix="native-smoke-stable-") as temporary:
            root = Path(temporary).resolve()
            record, revision, _, _ = self.create_agy_git_fixture(root)
            version = "3.0.1"
            (root / "sources.json").write_text(json.dumps({"host": "antigravity", "plugin_version": version}))
            SMOKE.command(["git", "branch", "-m", "plugins-antigravity-stable"], root)
            SMOKE.command(["git", "add", "sources.json"], root)
            SMOKE.command(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                           "-c", "user.name=Smoke fixture", "-c", "user.email=smoke@example.invalid",
                           "commit", "--quiet", "-m", "Stable fixture only"], root)
            commit = SMOKE.command(["git", "rev-parse", "HEAD"], root)
            record.update(version=version, channel="stable", ref="refs/heads/plugins-antigravity-stable")
            record["files"]["sources.json"]["sha256"] = hashlib.sha256((root / "sources.json").read_bytes()).hexdigest()
            record["artifacts_sha256"] = sample_hashes(version, "0.1.1")
            # 仍保留七个键及本宿主主包摘要，仅替换另一宿主的本地源或组件名；
            # 发布验收必须能区分错误版本、错误渠道和非候选文件。
            for original, replacement in (
                ("workflow/xy-workflow-codex-3.0.1-local-source.zip", "unrelated.zip"),
                ("native/native-agent-config-0.1.1.zip", "native/native-agent-config-0.1.1-alpha.1.zip"),
            ):
                changed = copy.deepcopy(record)
                changed["artifacts_sha256"][replacement] = changed["artifacts_sha256"].pop(original)
                with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                    SMOKE.validate_distribution(changed, "antigravity", revision, version)
            report = SMOKE.verify_installed(root, record, "antigravity", revision, version,
                                            distribution_commit=commit, channel="stable")
            self.assertEqual("plugins-antigravity-stable", report["verified_git_metadata"]["branch"])
            SMOKE.validate_distribution(record, "antigravity", revision, version)
            for channel in ("alpha", "beta"):
                with self.subTest(channel=channel), self.assertRaises(ValueError):
                    SMOKE.validate_distribution(record, "antigravity", revision, version, channel)
            with self.assertRaises(ValueError):
                SMOKE.verified_git_metadata(root, "antigravity", commit, "alpha")
            with self.assertRaises(ValueError):
                SMOKE.plugin_row("codex", {"installed": []}, "local")

    def test_native_list_discovery_requires_unique_plugin_identity(self):
        for channel, marketplace in (("stable", "xy-workflow"), ("alpha", "xy-workflow-alpha")):
            for host in ("codex", "claude", "antigravity"):
                row = {"pluginId": "xy-workflow@" + marketplace} if host == "codex" else \
                      {"id": "xy-workflow@" + marketplace} if host == "claude" else {"name": "xy-workflow"}
                payload = {"installed": [row]} if host == "codex" else [row]
                self.assertEqual(row, SMOKE.plugin_row(host, payload, channel))
                if channel == "stable":
                    self.assertEqual(row, SMOKE.plugin_row(host, payload), "默认仅发现正式市场")
                for rows in ([], [row, row]):
                    with self.subTest(host=host, channel=channel, rows=rows), self.assertRaises(ValueError):
                        SMOKE.plugin_row(host, {"installed": rows} if host == "codex" else rows, channel)


if __name__ == "__main__":
    unittest.main()
