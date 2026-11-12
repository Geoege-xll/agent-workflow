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
                         "scripts/test_remote_plugin_install.py", "if-no-files-found: error", "overwrite: false"):
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
                    prefix = "" if host == "antigravity" else "plugins/agent-workflow/"
                    files = {prefix + path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                  "mode": "100755" if path.name == "run.sh" else "100644"}
                             for path in plugin.iterdir()}
                    record = {"schema_version": 1, "managed_by": "agent-workflow-plugin-source-v1",
                              "repository": "Geoege-xll/agent-workflow", "host": host, "channel": "alpha",
                              "ref": "refs/heads/plugins-" + host + "-alpha", "source_revision": revision,
                              "version": version, "files": files, "candidate_sha256": "c" * 64,
                              "source_tree_sha256": "d" * 64, "plugin_zip_sha256": "e" * 64,
                              "artifacts_sha256": {**{str(index): "f" * 64 for index in range(6)},
                                  "workflow/agent-workflow-" + host + "-" + version + ".zip": "e" * 64}}
                    if host != "antigravity":
                        record["files"][".marketplace/ignored.json"] = {"sha256": "0" * 64, "mode": "100644"}
                    report = SMOKE.verify_installed(plugin, record, host, revision, version)
                    self.assertEqual(2, report["files"])
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

    def test_native_list_discovery_requires_unique_plugin_identity(self):
        for host in ("codex", "claude", "antigravity"):
            row = {"pluginId": "agent-workflow@agent-workflow-alpha"} if host == "codex" else \
                  {"id": "agent-workflow@agent-workflow-alpha"} if host == "claude" else {"name": "agent-workflow"}
            payload = {"installed": [row]} if host == "codex" else [row]
            self.assertEqual(row, SMOKE.plugin_row(host, payload))
            for rows in ([], [row, row]):
                with self.subTest(host=host, rows=rows), self.assertRaises(ValueError):
                    SMOKE.plugin_row(host, {"installed": rows} if host == "codex" else rows)


if __name__ == "__main__":
    unittest.main()
