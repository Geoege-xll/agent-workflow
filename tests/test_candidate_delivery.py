"""候选编排合同：真实子进程复用构建器协议，不复制两个产品的载荷规则。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CandidateDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="candidate-delivery-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source with spaces"
        for name in ("packaging", "product", "native_config"):
            (self.source / name).mkdir(parents=True)
        shutil.copyfile(ROOT / "packaging/build_candidates.py", self.source / "packaging/build_candidates.py")
        (self.source / "product/PLUGIN_VERSION").write_text("3.0.0-alpha.2\n", encoding="ascii")
        (self.source / "native_config/VERSION").write_text("0.1.0-alpha.2\n", encoding="ascii")
        self.calls = self.root / "builder-calls.jsonl"
        self.environment = {**os.environ, "AWF_TEST_CALLS": str(self.calls)}
        # 夹具只实现既有 CLI/归档元数据协议。真实产品白名单、离线加载和可复现
        # 由各自的 delivery/packaging 测试负责，此处检查顺序、同源和失败传播。
        common = '''import argparse, json, os, sys, zipfile
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--host")
parser.add_argument("--local-source", action="store_true")
args = parser.parse_args()
args.output_dir.mkdir(parents=True)
with Path(os.environ["AWF_TEST_CALLS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"builder": Path(__file__).name, "source": str(args.source),
                             "host": args.host, "local_source": args.local_source,
                             "python": sys.executable, "no_bytecode": sys.dont_write_bytecode}) + "\\n")
def archive(name, files):
    with zipfile.ZipFile(args.output_dir / name, "w") as package:
        for path, body in files.items():
            package.writestr(path, body)
'''
        plugin = '''version = (args.source / "product/PLUGIN_VERSION").read_text().strip()
for host in ("codex", "claude", "antigravity"):
    record = json.dumps({"plugin_version": version, "host": host})
    stem = "agent-workflow-" + host + "-" + version
    archive(stem + ".zip", {"sources.json": record})
    local = "{}" if os.environ.get("AWF_CASE") == "local-mismatch" else record
    archive(stem + "-local-source.zip", {"plugins/plugin/sources.json": local})
'''
        native = '''version = (args.source / "native_config/VERSION").read_text().strip()
mode = os.environ.get("AWF_CASE")
if mode == "fail":
    print("构建器真实拒绝", file=sys.stderr)
    raise SystemExit(7)
if mode == "drift":
    (args.source / "native_config/VERSION").write_text(version + "\\n\\n")
record_version = "0.1.0-alpha.999" if mode == "wrong-version" else version
archive("native-agent-config-" + version + ".zip", {"BUILD.json": json.dumps({"version": record_version})})
if mode == "extra":
    archive("unexpected.zip", {"extra": "unexpected"})
'''
        (self.source / "packaging/build_plugin.py").write_text(common + plugin, encoding="utf-8")
        (self.source / "packaging/build_agent_config.py").write_text(common + native, encoding="utf-8")
        self.git("init", "--quiet")
        self.git("add", ".")
        self.git("-c", "user.name=候选测试", "-c", "user.email=candidate@example.invalid",
                 "commit", "--quiet", "-m", "fixture")

    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.source), *arguments], stderr=subprocess.PIPE).decode().strip()

    def invoke(self, output, *, mode=None):
        environment = dict(self.environment)
        if mode:
            environment["AWF_CASE"] = mode
        return subprocess.run([sys.executable, "-B", str(self.source / "packaging/build_candidates.py"),
                               "--source", str(self.source), "--output-dir", str(output)],
                              cwd=self.root, env=environment, capture_output=True, text=True, timeout=15)

    def test_seven_independent_candidates_bind_source_versions_and_exact_checksums(self):
        for dirty in (False, True):
            with self.subTest(dirty=dirty):
                if dirty:
                    (self.source / "uncommitted.txt").write_text("未提交的真实源码字节\n", encoding="utf-8")
                self.calls.unlink(missing_ok=True)
                output = self.root / ("dirty-candidate" if dirty else "clean-candidate")
                result = self.invoke(output)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                manifest = json.loads((output / "candidate-manifest.json").read_text())
                self.assertEqual(manifest, json.loads(result.stdout))
                self.assertEqual(self.git("rev-parse", "HEAD"), manifest["source"]["revision"])
                self.assertEqual(dirty, manifest["source"]["dirty"])
                self.assertRegex(manifest["source"]["tree_sha256"], r"^[a-f0-9]{64}$")
                self.assertEqual({"workflow": "3.0.0-alpha.2", "native-config": "0.1.0-alpha.2"}, manifest["versions"])
                self.assertEqual("alpha", manifest["channel"])
                self.assertEqual("BUILD_VERIFIED", manifest["status"])
                self.assertFalse(manifest["runtime_verified"])
                self.assertEqual({"products_are_independent": True, "mcp_required": False}, manifest["installation"])
                self.assertEqual(7, len(manifest["artifacts"]))
                self.assertEqual(6, sum(row["product"] == "workflow" for row in manifest["artifacts"]))
                for row in manifest["artifacts"]:
                    path = output / row["path"]
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])
                    self.assertEqual(row["sha256"] + "  " + path.name + "\n", path.with_suffix(".zip.sha256").read_text())
                self.assertEqual(7, len((output / "SHA256SUMS").read_text().splitlines()))
                summary = (output / "CANDIDATE.md").read_text()
                self.assertIn("runtime_verified=false", summary)
                self.assertIn("3.0.0-alpha.2", summary)
                self.assertIn("0.1.0-alpha.2", summary)
                calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
                self.assertEqual(["build_plugin.py", "build_agent_config.py"], [row["builder"] for row in calls])
                self.assertEqual(["all", None], [row["host"] for row in calls])
                self.assertEqual([True, False], [row["local_source"] for row in calls])
                self.assertTrue(all(row["source"] == str(self.source) and row["python"] == sys.executable
                                    and row["no_bytecode"] for row in calls))
                self.assertEqual([], list(self.source.rglob("*.pyc")))

    def test_stable_beta_or_missing_versions_fail_before_building(self):
        for relative, version in (("product/PLUGIN_VERSION", "3.0.0"),
                                  ("native_config/VERSION", "0.1.0-beta.1"),
                                  ("native_config/VERSION", None)):
            with self.subTest(relative=relative, version=version):
                path = self.source / relative
                saved = path.read_bytes()
                if version is None:
                    path.unlink()
                else:
                    path.write_text(version, encoding="ascii")
                output = self.root / "rejected-version"
                result = self.invoke(output)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertFalse(output.exists())
                self.assertFalse(self.calls.exists())
                path.write_bytes(saved)

    def test_existing_or_in_source_output_is_never_overwritten(self):
        existing = self.root / "existing"
        existing.mkdir()
        sentinel = existing / "checked.zip"
        sentinel.write_bytes(b"preserve reviewed candidate")
        for output in (existing, self.source / "new-output"):
            with self.subTest(output=output):
                result = self.invoke(output)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertFalse(self.calls.exists())
                self.assertEqual(b"preserve reviewed candidate", sentinel.read_bytes())
        self.assertFalse((self.source / "new-output").exists())

    def test_builder_failures_source_drift_and_mixed_artifacts_do_not_emit_manifest(self):
        for mode in ("fail", "drift", "wrong-version", "local-mismatch", "extra"):
            with self.subTest(mode=mode):
                output = self.root / mode
                result = self.invoke(output, mode=mode)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertFalse((output / "candidate-manifest.json").exists())
                self.assertFalse((output / "CANDIDATE.md").exists())
                if mode == "fail":
                    self.assertIn("构建器真实拒绝", result.stderr)
                # 恢复的是本例自己的临时夹具；不接触共享工作树或其他作者的源码。
                (self.source / "native_config/VERSION").write_text("0.1.0-alpha.2\n", encoding="ascii")


if __name__ == "__main__":
    unittest.main()
