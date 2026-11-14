"""真实远程安装验收的离线安全合同；这里不下载、不安装、不调用用户机官方客户端。"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("remote_install_smoke", ROOT / "scripts/test_remote_plugin_install.py")
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


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
                         "      - name: Upload the installation-only evidence\n        if: always()"):
            self.assertIn(fragment, workflow)
        for forbidden in ("contents: write", "  push:", "  pull_request:", "inputs:", "CODEX_HOME",
                          "CLAUDE_CONFIG_DIR", "HOME:", "export HOME", "secrets.", "windows-latest"):
            self.assertNotIn(forbidden, workflow)

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
                              "artifacts_sha256": {**{str(index): "f" * 64 for index in range(6)},
                                  "workflow/xy-workflow-" + host + "-" + version + ".zip": "e" * 64}}
                    if host != "antigravity":
                        record["files"][".marketplace/ignored.json"] = {"sha256": "0" * 64, "mode": "100644"}
                    report = SMOKE.verify_installed(plugin, record, host, revision, version)
                    self.assertEqual(2, report["files"])
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
                  "artifacts_sha256": {**{str(index): "f" * 64 for index in range(6)},
                      "workflow/xy-workflow-antigravity-" + version + ".zip": "e" * 64}}
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
            del record["artifacts_sha256"]["workflow/xy-workflow-antigravity-3.0.0-alpha.5.zip"]
            record["artifacts_sha256"]["workflow/xy-workflow-antigravity-3.0.1.zip"] = "e" * 64
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
