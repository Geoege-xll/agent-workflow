"""Offline distribution checks; never invoke brew install, change PATH, or sync projects."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


PACK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_release", PACK / "packaging/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-release-test-")
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        for name in release.RELEASE_FILES:
            (self.source / name).write_text(f"fixture: {name}\n", encoding="utf-8")
        for name in release.RELEASE_DIRECTORIES:
            (self.source / name).mkdir()
        (self.source / "workflow.sh").chmod(0o755)
        template = self.source / "packaging/homebrew/awf-cli.rb.in"
        template.parent.mkdir(parents=True)
        shutil.copyfile(PACK / "packaging/homebrew/awf-cli.rb.in", template)

    def tearDown(self):
        self.temp.cleanup()

    def test_reproducible_archive_checksum_formula_and_modes(self):
        first = release.build(self.source, "0.1.0", self.root / "first")
        os.utime(self.source / "workflow.sh", (123456789, 123456789))
        second = release.build(self.source, "0.1.0", self.root / "second")
        for before, after in zip(first, second):
            self.assertEqual(before.read_bytes(), after.read_bytes())
        archive, checksum, formula = first
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(checksum.read_text(), f"{digest}  {archive.name}\n")
        self.assertIn(f'sha256 "{digest}"', formula.read_text())
        self.assertIn("/releases/download/v0.1.0/agent-workflow-0.1.0.tar.gz", formula.read_text())
        self.assertNotIn("@VERSION@", formula.read_text())
        with tarfile.open(archive) as stream:
            for member in stream:
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
            self.assertEqual(stream.getmember("agent-workflow-0.1.0/workflow.sh").mode, 0o755)
            self.assertEqual(stream.getmember("agent-workflow-0.1.0/project.yaml").mode, 0o644)

    def test_payload_allowlist_excludes_backups_tooling_and_caches(self):
        for name in (".sync-backups/private", "dist/old", "docs/draft", "tests/private", "lib/__pycache__/old.pyc", "lib/.DS_Store"):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not a release file")
        (self.source / "LICENSE").write_text("fixture license")
        archive, _, _ = release.build(self.source, "0.1.0", self.root / "out")
        with tarfile.open(archive) as stream:
            names = stream.getnames()
        self.assertIn("agent-workflow-0.1.0/LICENSE", names)
        self.assertIn("agent-workflow-0.1.0/lib", names)
        for name in names:
            self.assertFalse(any(part in {".sync-backups", "dist", "docs", "tests", "packaging", "__pycache__", ".DS_Store"} for part in Path(name).parts), name)

    def test_invalid_versions_and_unsafe_output_do_not_write(self):
        output = self.root / "out"
        for version in ("v0.1.0", "../1.0.0", "1.2", "01.2.3", "1.2.3\n"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.build(self.source, version, output)
        self.assertFalse(output.exists())
        for output in (self.source, self.source / "lib/out", self.source / "packaging/out"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                release.build(self.source, "0.1.0", output)

    def test_existing_outputs_and_foreign_formula_directory_are_preserved(self):
        output = self.root / "out"
        files = release.build(self.source, "0.1.0", output)
        before = [path.read_bytes() for path in files]
        with self.assertRaises(FileExistsError):
            release.build(self.source, "0.1.0", output)
        self.assertEqual(before, [path.read_bytes() for path in files])
        other = self.root / "other"
        other.mkdir()
        (other / "Formula").symlink_to(output / "Formula", target_is_directory=True)
        with self.assertRaises(ValueError):
            release.build(self.source, "0.2.0", other)
        self.assertFalse((other / "agent-workflow-0.2.0.tar.gz").exists())
        self.assertEqual(before, [path.read_bytes() for path in files])

    def test_missing_entries_and_payload_symlinks_are_rejected(self):
        script = self.source / "workflow.sh"
        script.unlink()
        with self.assertRaises(ValueError):
            release.build(self.source, "0.1.0", self.root / "out")
        script.write_text("fixture")
        (self.source / "lib/foreign").symlink_to(PACK / "README.md")
        with self.assertRaises(ValueError):
            release.build(self.source, "0.1.0", self.root / "out")
        self.assertFalse((self.root / "out").exists())


# This small DSL harness exercises the actual generated Formula#install in a temporary
# Cellar layout. It is not a substitute for Homebrew's own install/test after publication.
FORMULA_HARNESS = r'''
require "pathname"
require "fileutils"
class Pathname
  def install(sources)
    mkpath
    sources.each { |source| FileUtils.cp_r(source, to_s) }
  end
end
class Formula
  def self.desc(*args); end
  def self.homepage(*args); end
  def self.url(*args); end
  def self.version(*args); end
  def self.sha256(*args); end
  def self.depends_on(*args); end
  def self.test; end
  def self.[](name)
    raise "Unexpected dependency: #{name}" unless name == "python@3.14"
    Struct.new(:opt_bin).new(Pathname.new(ARGV.fetch(3)))
  end
  def libexec; Pathname.new(ARGV.fetch(2))/"libexec"; end
  def bin; Pathname.new(ARGV.fetch(2))/"bin"; end
end
load ARGV.fetch(0)
Dir.chdir(ARGV.fetch(1)) { AwfCli.new.install }
'''


@unittest.skipUnless(shutil.which("ruby"), "Ruby is required for the Formula install simulation")
class HomebrewLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-cellar-test-")
        self.root = Path(self.temp.name).resolve()
        archive, _, self.formula = release.build(PACK, "0.1.0", self.root / "dist")
        extracted = self.root / "extracted"
        extracted.mkdir()
        with tarfile.open(archive) as stream:
            stream.extractall(extracted, filter="data")
        self.prefix = self.root / "Homebrew Cellar/awf-cli/0.1.0"
        self.python_bin = self.root / "Python opt/bin"
        self.python_bin.mkdir(parents=True)
        self.log = self.root / "python-calls"
        self.python = self.python_bin / "python3.14"
        self.python.write_text(
            '#!/bin/sh\nprintf "%s\\n%s\\n%s\\n" "$PATH" "${CDPATH-}" "$1" >> '
            + shlex.quote(str(self.log)) + "\nexec " + shlex.quote(sys.executable) + ' "$@"\n'
        )
        self.python.chmod(0o755)
        harness = self.root / "formula_harness.rb"
        harness.write_text(FORMULA_HARNESS)
        result = subprocess.run(
            [shutil.which("ruby"), str(harness), str(self.formula), str(extracted / "agent-workflow-0.1.0"), str(self.prefix), str(self.python_bin)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.root / "Homebrew bin"
        commands.mkdir()
        self.entry = commands / "awf-cli"
        self.entry.symlink_to(os.path.relpath(self.prefix / "bin/awf-cli", commands))
        self.caller = self.root / "caller"
        self.caller.mkdir()
        (self.caller / "project").mkdir()
        self.env = {**os.environ, "CDPATH": str(self.root)}
        self.env.pop("AGENT_WORKFLOW_PYTHON", None)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *arguments):
        return subprocess.run([str(self.entry), *arguments], cwd=self.caller, env=self.env, capture_output=True, text=True, timeout=15)

    def test_formula_syntax_payload_and_default_interpreter_without_duplicate_probe(self):
        syntax = subprocess.run([shutil.which("ruby"), "-c", str(self.formula)], capture_output=True, text=True, timeout=15)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        for name in (*release.RELEASE_FILES, *release.RELEASE_DIRECTORIES):
            self.assertTrue((self.prefix / "libexec" / name).exists(), name)
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("usage: awf-cli"))
        self.assertEqual(self.log.read_text().splitlines(), [self.env["PATH"], self.env["CDPATH"], "-c", self.env["PATH"], self.env["CDPATH"], "-B"])
        self.assertFalse((self.prefix / "libexec/manager/__pycache__").exists())

    def test_relative_project_is_resolved_in_caller_and_read_only_command_leaves_no_state(self):
        result = self.run_cli("--state-dir", "state", "roles", "--project", "project", "--platform", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertFalse((self.caller / "state").exists())
        self.assertEqual(list((self.caller / "project").iterdir()), [])

    def test_explicit_relative_interpreter_is_preserved(self):
        tools = self.caller / "tools with spaces"
        tools.mkdir()
        (tools / "python").symlink_to(self.python)
        self.env["AGENT_WORKFLOW_PYTHON"] = "tools with spaces/python"
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines()[2::3], ["-c", "-B"])

    def test_invalid_explicit_interpreter_is_not_replaced_by_homebrew_default(self):
        self.env["AGENT_WORKFLOW_PYTHON"] = "missing/python"
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Python >= 3.11", result.stderr)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
