"""Offline distribution checks; never invoke brew install, change PATH, or sync projects."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from urllib.parse import unquote, urlsplit


PACK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_release", PACK / "packaging/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


MANUAL_FILES = ("README.md", "docs/usage.md", "docs/development.md", "docs/homebrew.md")


def assert_offline_manual_links(test, documents, available_paths):
    """检查真实载荷的文档链接，避免源码可打开而离线发行包缺少目标。

    只读取本次归档／安装后的字节与成员集合，不借用源码目录补齐缺失文件；
    外部 URL 保持外部链接，内部目标必须在载荷中，Markdown 锚点必须命中标题。
    """
    for relative in MANUAL_FILES:
        body = documents[relative].decode("utf-8")
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)\s]+)\)", body):
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), unquote(url.path))) if url.path else relative
            with test.subTest(document=relative, target=target):
                test.assertFalse(resolved.startswith("../") or resolved.startswith("/"), target)
                test.assertIn(resolved, available_paths)
                if url.fragment and resolved.endswith(".md"):
                    headings = re.findall(r"(?m)^#{1,6} (.+)$", documents[resolved].decode("utf-8"))
                    anchors = {re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings}
                    test.assertIn(unquote(url.fragment), anchors)


class ReleaseArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-release-test-")
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        for name in release.RELEASE_FILES:
            # 手册是显式嵌套文件，夹具必须建立父目录，不能把 docs 改成递归载荷。
            (self.source / name).parent.mkdir(parents=True, exist_ok=True)
            (self.source / name).write_text(f"fixture: {name}\n", encoding="utf-8")
        for name in release.RELEASE_DIRECTORIES:
            (self.source / name).mkdir()
        (self.source / "workflow.sh").chmod(0o755)
        (self.source / "product/VERSION").write_text("0.1.0\n", encoding="ascii")
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
        self.assertIn('depends_on "node"', formula.read_text())
        self.assertIn("/releases/download/v0.1.0/agent-workflow-0.1.0.tar.gz", formula.read_text())
        self.assertNotIn("@VERSION@", formula.read_text())
        with tarfile.open(archive) as stream:
            for member in stream:
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
            self.assertEqual(stream.getmember("agent-workflow-0.1.0/workflow.sh").mode, 0o755)
            self.assertEqual(stream.getmember("agent-workflow-0.1.0/project.yaml").mode, 0o644)
            metadata=stream.extractfile("agent-workflow-0.1.0/manager/release.json").read()
            self.assertEqual(json.loads(metadata), {"schema_version": 1, "version": "0.1.0"})
            self.assertEqual(stream.getmember("agent-workflow-0.1.0/manager/release.json").mode, 0o644)
        self.assertFalse((self.source / "manager/release.json").exists())

    def test_source_release_metadata_is_rejected_without_output(self):
        # 不允许把源码中的旧发行标记当成可信输入，也不能静默覆盖它制造双重版本来源。
        metadata=self.source / "manager/release.json"
        metadata.write_text('{"schema_version":1,"version":"9.9.9"}',encoding="utf-8")
        original=metadata.read_bytes()
        with self.assertRaisesRegex(ValueError,"Generated release metadata"):
            release.build(self.source,"0.1.0",self.root / "out")
        self.assertFalse((self.root / "out").exists());self.assertEqual(metadata.read_bytes(),original)

    def test_payload_allowlist_excludes_backups_tooling_and_caches(self):
        for name in (".sync-backups/private", "dist/old", "docs/draft", "docs/plans/private.md",
                     "docs/standards/prototype/index.html", "docs/private/secret.md", "tests/private",
                     "lib/__pycache__/old.pyc", "lib/.DS_Store"):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not a release file")
        (self.source / "LICENSE").write_text("fixture license")
        archive, _, _ = release.build(self.source, "0.1.0", self.root / "out")
        with tarfile.open(archive) as stream:
            names = stream.getnames()
        self.assertIn("agent-workflow-0.1.0/LICENSE", names)
        self.assertIn("agent-workflow-0.1.0/lib", names)
        # 只准三份手册进入 docs，不能用“允许 docs”掩盖 plans／原型／私有资料泄漏。
        prefix = "agent-workflow-0.1.0/"
        self.assertEqual({prefix + name for name in MANUAL_FILES[1:]},
                         {name for name in names if name.startswith(prefix + "docs/")})
        for name in names:
            self.assertFalse(any(part in {".sync-backups", "dist", "tests", "packaging", "__pycache__", ".DS_Store"} for part in Path(name).parts), name)

    def test_real_archive_manual_links_resolve_without_private_docs(self):
        # 使用当前源码的真实归档，而非只有占位正文的最小夹具，覆盖离线导航合同。
        version = (PACK / "product/VERSION").read_text(encoding="ascii").strip()
        archive, _, _ = release.build(PACK, version, self.root / "real-output")
        prefix = f"agent-workflow-{version}/"
        with tarfile.open(archive) as stream:
            available = {member.name.removeprefix(prefix) for member in stream if member.name.startswith(prefix)}
            documents = {relative: stream.extractfile(prefix + relative).read()
                         for relative in available if relative.endswith(".md")}
            self.assertEqual(set(MANUAL_FILES[1:]), {name for name in available if name.startswith("docs/")})
            for relative in MANUAL_FILES:
                self.assertEqual(documents[relative], (PACK / relative).read_bytes())
            assert_offline_manual_links(self, documents, available)

    def test_manual_parent_symlink_is_rejected_without_output(self):
        # 文件本身是普通文件也不能沿 docs 父目录链接读取源包外材料。
        original = self.source / "docs"
        retained = self.root / "manuals"
        original.rename(retained)
        original.symlink_to(retained, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            release.build(self.source, "0.1.0", self.root / "out")
        self.assertFalse((self.root / "out").exists())
        self.assertTrue((retained / "usage.md").is_file())

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
        supplied = os.environ.get("AWF_TEST_SCRATCH")
        self.temp = None
        if supplied:
            self.root = Path(supplied) / "model-packaging" / self._testMethodName
            self.root.mkdir(parents=True, exist_ok=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="awf-cellar-test-")
            self.root = Path(self.temp.name).resolve()
        # 真实源码消费者跟随唯一版本源，旧版本的纯打包夹具仍独立保留。
        self.version = (PACK / "product/VERSION").read_text(encoding="ascii").strip()
        archive, _, self.formula = release.build(PACK, self.version, self.root / "dist")
        extracted = self.root / "extracted"
        extracted.mkdir()
        with tarfile.open(archive) as stream:
            stream.extractall(extracted, filter="data")
        self.prefix = self.root / "Homebrew Cellar/awf-cli" / self.version
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
            [shutil.which("ruby"), str(harness), str(self.formula), str(extracted / f"agent-workflow-{self.version}"), str(self.prefix), str(self.python_bin)],
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
        if self.temp is not None:
            self.temp.cleanup()

    def run_cli(self, *arguments):
        return subprocess.run([str(self.entry), *arguments], cwd=self.caller, env=self.env, capture_output=True, text=True, timeout=15)

    def test_version_reads_archive_metadata_after_formula_install(self):
        # 真实归档→Formula#install→短链接入口；不使用 README 或 Cellar 目录名推断版本。
        result=self.run_cli("--state-dir","state","--version")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.splitlines(),[f"awf-cli {self.version}",f"中央源根：{self.prefix / 'libexec'}"])
        self.assertFalse((self.caller / "state").exists())
        help_result = self.run_cli("--help")
        self.assertEqual(0, help_result.returncode, help_result.stderr)
        self.assertNotIn("projects", help_result.stdout)
        self.assertNotIn("--migrate-legacy", self.run_cli("open", "--help").stdout)
        # 同一真实载荷原地验证坏元数据及不匹配版本，避免再创建一套安装候选。
        metadata = self.prefix / "libexec/manager/release.json"
        for body in ('{"schema_version":1,"version":"PRIVATE-INVALID-METADATA"}',
                     '{"schema_version":1,"version":"2.0.1"}'):
            metadata.write_text(body, encoding="utf-8")
            invalid = self.run_cli("--version")
            self.assertEqual(2, invalid.returncode)
            self.assertIn("发行元数据", invalid.stderr)
            self.assertNotIn("PRIVATE-INVALID-METADATA", invalid.stdout + invalid.stderr)

    def test_invalid_packaged_metadata_reports_safe_error(self):
        metadata=self.prefix / "libexec/manager/release.json"
        metadata.write_text('{"schema_version":1,"version":"PRIVATE-INVALID-METADATA"}',encoding="utf-8")
        result=self.run_cli("--version")
        self.assertEqual(result.returncode,2);self.assertIn("发行元数据",result.stderr)
        self.assertNotIn("PRIVATE-INVALID-METADATA",result.stdout+result.stderr);self.assertNotIn("Traceback",result.stderr)

    def test_formula_syntax_payload_and_default_interpreter_without_duplicate_probe(self):
        syntax = subprocess.run([shutil.which("ruby"), "-c", str(self.formula)], capture_output=True, text=True, timeout=15)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        for name in (*release.RELEASE_FILES, *release.RELEASE_DIRECTORIES):
            self.assertTrue((self.prefix / "libexec" / name).exists(), name)
        # 真实归档与 Formula 安装后的消费者必须持有同一 helper、原样引擎和许可证。
        for relative in ("lib/documents/requirement_html.py", "lib/documents/plan_documents.py",
                         "lib/documents/prototype_navigation.py", "lib/documents/validate_prototype_workspace.py",
                         *("templates/prototype/" + name for name in ("index.html", "page.html", "prototype.css", "workspace.css", "workspace.js", "page-shell.js")),
                         "templates/docs/PLAN.md", "lib/vendor/answer-me-with-html/am.mjs",
                         "lib/vendor/answer-me-with-html/LICENSE", "lib/vendor/answer-me-with-html/OFL-Bangers.txt",
                         "platforms/shared/skills/xy-plan/references/requirement-html.md"):
            self.assertEqual((self.prefix / "libexec" / relative).read_bytes(), (PACK / relative).read_bytes())
        self.assertFalse((self.prefix / "libexec/templates/docs/FEATURE.md").exists())
        # Formula 也要保留同一离线手册；从实际安装载荷解析链接，不借用源包补目标。
        installed = self.prefix / "libexec"
        available = {path.relative_to(installed).as_posix() for path in installed.rglob("*")}
        documents = {relative: (installed / relative).read_bytes()
                     for relative in available if relative.endswith(".md") and (installed / relative).is_file()}
        for relative in MANUAL_FILES:
            self.assertEqual(documents[relative], (PACK / relative).read_bytes())
        assert_offline_manual_links(self, documents, available)
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
