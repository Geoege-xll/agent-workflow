"""Offline npm preparation tests. Only temporary fixtures; never run archive binaries."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile


PACK = Path(__file__).resolve().parents[1]


def npm_command():
    executable = shutil.which("npm")
    if os.name != "nt":
        return [executable]
    cli = Path(executable).parent / "node_modules/npm/bin/npm-cli.js"
    if not cli.is_file() or not shutil.which("node.exe"):
        raise AssertionError("native Node.js and npm-cli.js are required; no shell=True fallback")
    return [shutil.which("node.exe"), str(cli)]


spec = importlib.util.spec_from_file_location("build_npm_release", PACK / "packaging/build_npm_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class NpmPreparationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-npm-test-")
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        files, directories = release.installer_allowlist(PACK)
        for name in files:
            (self.source / name).write_text(f"fixture {name}\n")
        for name in directories:
            (self.source / name).mkdir()
        # A top-level exception must never execute while reading installer constants.
        (self.source / "lib/install_workflow.py").write_text(
            f"PACK_FILES = {files!r}\nPACK_DIRECTORIES = {directories!r}\nraise AssertionError('do not import')\n"
        )
        for name in release.RUNTIME_HELPERS:
            (self.source / "lib" / name).write_text("import os\nfrom pathlib import Path\n")
        for name in release.SCRIPTS:
            (self.source / "scripts" / name).write_text("#!/bin/bash\nprintf fixture\\n\n")
        for name in release.STARTUP_FILES:
            target = self.source / "npm" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PACK / "npm" / name, target)
        self.lock = json.loads((PACK / "packaging/windows/runtime.lock.json").read_text())
        self.members = {
            "python.exe": b"fixture: not executable",
            "python314.dll": b"fixture DLL",
            "python314.zip": b"fixture stdlib ZIP (never executed)",
            "python314._pth": b"python314.zip\r\n.\r\n\r\n#import site\r\n",
            "LICENSE.txt": b"fixture upstream license; retain exactly\r\n",
        }
        self.archive_dir = self.root / "download"
        self.archive_dir.mkdir()
        self.archive = self.archive_dir / self.lock["archive"]
        self.write_archive()

    def tearDown(self):
        self.temp.cleanup()

    def write_archive(self, extra=()):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
                for name, data in self.members.items():
                    stream.writestr(name, data)
                for name, data in extra:
                    stream.writestr(name, data)
        self.relock_archive()

    def relock_archive(self):
        self.lock["size"] = self.archive.stat().st_size
        self.lock["sha256"] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        target = self.source / "packaging/windows/runtime.lock.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.lock))

    def prepare(self, name="out"):
        return release.prepare(self.source, self.archive, self.root / name)

    def assert_rejected(self):
        with self.assertRaises((ValueError, OSError, zipfile.BadZipFile)):
            self.prepare()
        self.assertFalse((self.root / "out").exists())

    def test_reproducible_manifest_helpers_license_modes_and_ast_allowlist(self):
        first = self.prepare("first")
        os.utime(self.source / "project.yaml", (12345, 12345))
        second = self.prepare("second")
        inventory = lambda root: {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.assertEqual(inventory(first), inventory(second))
        document = json.loads((first / "runtime/manifest.json").read_text())
        self.assertEqual(set(document), {"schema_version", "version", "architecture", "files"})
        expected = {p.relative_to(first / "runtime").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (first / "runtime").rglob("*") if p.is_file() and p.name != "manifest.json"}
        self.assertEqual(document["files"], expected)
        self.assertEqual((first / "runtime/LICENSE.txt").read_bytes(), self.members["LICENSE.txt"])
        self.assertEqual((first / "runtime/python314._pth").read_bytes(), self.members["python314._pth"])
        for name in release.RUNTIME_HELPERS:
            self.assertEqual((first / "runtime" / name).read_bytes(), (first / "payload/lib" / name).read_bytes())
        self.assertTrue((first / "payload/lib/install_workflow.py").is_file())
        self.assertEqual(stat.S_IMODE((first / "bin/agent-workflow.cjs").stat().st_mode), 0o755)
        self.assertEqual((first / "bin/agent-workflow.cjs").stat().st_mtime, 0)

    def test_real_source_allowlist_and_dependency_closure_excludes_executable_test_helpers(self):
        actual = release.payload(PACK)
        for script in release.SCRIPTS:
            self.assertIn(f"scripts/{script}", actual)
        for name in actual:
            self.assertFalse(name.startswith(("manager/", "tests/", "npm/", "packaging/")), name)
            self.assertFalse(name.startswith("scripts/test_"), name)
        self.assertIn("lib/install_workflow.py", actual)
        self.assertIn("lib/windows_runtime.py", actual)
        for name in ("manager/tool.py", "tests/test_unsafe.py", "lib/__pycache__/cache.pyc",
                     "lib/saved.bak", "lib/test_fixture.py", "scripts/test_claude.sh", ".sync-backups/private"):
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("not runtime code")
        prepared = self.prepare()
        self.assertFalse(any(p.name in {"saved.bak", "test_fixture.py", "test_claude.sh", "cache.pyc"}
                             for p in prepared.rglob("*")))

    def test_hash_and_size_mismatch_reject_before_any_output(self):
        with self.archive.open("ab") as stream:
            stream.write(b"tampered")
        self.assert_rejected()
        self.archive.write_bytes(b"different ZIP")
        self.assert_rejected()

    def test_archive_path_traversal_aliases_devices_and_control_characters(self):
        for name in ("../outside", "/absolute", "C:/absolute", "safe\\escape", "a/../bad", "a//b", "./bad",
                     "CON", "nul.txt", "LPT1.log", "COM¹", "conout$", "trailing.", "trailing ",
                     "alternate:stream", "control\x01", "nul\x00suffix", "manifest.json", "WINDOWS_FS.PY"):
            with self.subTest(name=name):
                self.write_archive([(name, b"bad")])
                self.assert_rejected()
        self.assertFalse((self.root / "outside").exists())

    def test_zip_unsupported_compression_encryption_nul_and_bad_crc(self):
        entry = zipfile.ZipInfo("unsupported")
        entry.compress_type = zipfile.ZIP_BZIP2
        self.write_archive([(entry, b"unsupported compression")])
        self.assert_rejected()
        self.write_archive()
        data = bytearray(self.archive.read_bytes())
        local = data.index(b"PK\x03\x04")
        central = data.index(b"PK\x01\x02")
        data[local + 6] |= 1
        data[central + 8] |= 1
        self.archive.write_bytes(data)
        self.relock_archive()
        self.assert_rejected()
        self.write_archive([("safeXsuffix", b"bad")])
        self.archive.write_bytes(self.archive.read_bytes().replace(b"safeXsuffix", b"safe\x00suffix"))
        self.relock_archive()
        self.assert_rejected()
        # Stored data avoids zlib ambiguity and deterministically fails the CRC check.
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as stream:
            for name, body in self.members.items():
                stream.writestr(name, body)
        data = bytearray(self.archive.read_bytes())
        filename_size = int.from_bytes(data[26:28], "little")
        extra_size = int.from_bytes(data[28:30], "little")
        data[30 + filename_size + extra_size] ^= 1
        self.archive.write_bytes(data)
        self.relock_archive()
        self.assert_rejected()

    def test_zip_duplicate_case_alias_and_file_directory_conflicts(self):
        for extra in ([('python.exe', b'duplicate')], [('PYTHON.EXE', b'case alias')],
                      [('a', b'file'), ('a/b', b'child')], [('Dir/a', b'a'), ('dir/b', b'b')],
                      [('file/', b'not empty directory')]):
            with self.subTest(extra=extra):
                self.write_archive(extra)
                self.assert_rejected()

    def test_archive_links_special_types_reparse_attributes_and_limits(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
            entry = zipfile.ZipInfo("unsafe")
            entry.create_system = 3
            entry.external_attr = (kind | 0o777) << 16
            self.write_archive([(entry, b"target")])
            self.assert_rejected()
        entry = zipfile.ZipInfo("reparse")
        entry.external_attr = 0x400
        self.write_archive([(entry, b"bad")])
        self.assert_rejected()
        self.write_archive()
        for limit, value in (("MAX_FILES", 2), ("MAX_FILE_SIZE", 8), ("MAX_TOTAL_SIZE", 16)):
            with self.subTest(limit=limit), patch.object(release, limit, value):
                self.assert_rejected()
        self.write_archive([("bomb", b"0" * (2 * 1024 * 1024))])
        self.assert_rejected()

    def test_missing_runtime_files_and_unsafe_pth_are_rejected(self):
        for name in ("python.exe", "python314.dll", "python314.zip", "python314._pth", "LICENSE.txt"):
            original = self.members.pop(name)
            self.write_archive()
            self.assert_rejected()
            self.members[name] = original
        for value in (b"python314.zip\n.\nimport site\n", b"python314.zip\n..\n", b"python314.zip\nC:/foreign\n"):
            self.members["python314._pth"] = value
            self.write_archive()
            self.assert_rejected()

    def test_source_links_hardlinks_special_files_and_linked_ancestors_rejected(self):
        foreign = self.root / "foreign"
        foreign.write_text("foreign")
        target = self.source / "lib/unsafe"
        target.symlink_to(foreign)
        self.assert_rejected()
        target.unlink()
        os.link(foreign, target)
        self.assert_rejected()
        target.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(target)
            self.assert_rejected()
            target.unlink()
        original = self.source / "npm/bin"
        moved = self.root / "moved-bin"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        self.assert_rejected()

    def test_missing_and_dynamic_installer_constants_and_dependency_failures(self):
        installer = self.source / "lib/install_workflow.py"
        original = installer.read_bytes()
        installer.write_text("PACK_FILES = tuple(['setup_all.sh'])\nPACK_DIRECTORIES = ('lib', 'scripts')\n")
        self.assert_rejected()
        installer.write_bytes(original)
        script = self.source / "scripts/guard.sh"
        script.write_text('bash "${PACK_DIR}/scripts/test_claude.sh"\n')
        self.assert_rejected()
        script.write_text("#!/bin/bash\n")
        (self.source / "lib/windows_fs.py").write_text("import unbundled_vendor_library\n")
        self.assert_rejected()

    def test_existing_unsafe_output_and_metadata_preserved(self):
        output = self.prepare()
        before = (output / "package.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual((output / "package.json").read_bytes(), before)
        for target in (self.source, self.source / "dist/new", self.root, self.archive_dir):
            with self.subTest(target=target), self.assertRaises((ValueError, FileExistsError)):
                release.prepare(self.source, self.archive, target)
        parent = self.root / "linked-parent"
        parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            release.prepare(self.source, self.archive, parent / "new")
        package = self.source / "npm/package.json"
        data = json.loads(package.read_text())
        data["scripts"] = {"postinstall": "download something"}
        package.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.prepare("other")
        self.assertFalse((self.root / "other").exists())

    @unittest.skipUnless(shutil.which("npm"), "npm is required for offline packing checks")
    def test_offline_npm_pack_ignore_scripts_allowlist_and_repeatability(self):
        prepared = self.prepare()
        cache = self.root / "npm-cache"
        base = [*npm_command(), "pack", "--offline", "--ignore-scripts", "--json", "--cache", str(cache)]
        env = {**os.environ, "npm_config_update_notifier": "false"}
        dry = subprocess.run([*base, "--dry-run"], cwd=prepared, env=env, capture_output=True, text=True, timeout=45)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        listing = json.loads(dry.stdout)[0]
        names = {entry["path"] for entry in listing["files"]}
        self.assertIn("bin/agent-workflow.cjs", names)
        self.assertIn("runtime/LICENSE.txt", names)
        self.assertIn("payload/lib/install_workflow.py", names)
        self.assertFalse(any("test_" in name or "manager/" in name or "__pycache__" in name for name in names))
        archives = []
        for destination in (self.root / "pack-one", self.root / "pack-two"):
            destination.mkdir()
            result = subprocess.run([*base, "--pack-destination", str(destination)], cwd=prepared,
                                    env=env, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            tgz = destination / json.loads(result.stdout)[0]["filename"]
            archives.append(tgz.read_bytes())
        self.assertEqual(*archives)
        with tarfile.open(fileobj=io.BytesIO(archives[0]), mode="r:gz") as stream:
            self.assertEqual({member.name.removeprefix("package/") for member in stream if member.isfile()}, names)
        project = self.root / "invocation 项目 with spaces"
        project.mkdir()
        execute = [*npm_command(), "exec", "--offline", "--ignore-scripts", "--yes", "--cache", str(cache),
                   "--package", str(tgz), "--", "agent-workflow"]
        for arguments, expected in ((["--help"], "Usage: agent-workflow"), (["--version"], "0.1.0")):
            result = subprocess.run([*execute, *arguments], cwd=project, env=env,
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith(expected), result.stdout)
        if os.name != "nt":
            # The fake runtime must never execute; platform gating is earlier than dependency reads.
            result = subprocess.run([*execute, "init"], cwd=project, env=env,
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("Windows 10/11 x64 only", result.stderr)
        self.assertEqual(list(project.iterdir()), [])


def windows_module(name):
    """Load trusted source for focused tests, restoring any helper-added import path."""
    module_spec = importlib.util.spec_from_file_location(f"npm_test_{name}", PACK / "lib" / f"{name}.py")
    module = importlib.util.module_from_spec(module_spec)
    before = sys.path[:]
    try:
        module_spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    return module


class WindowsRuntimeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = windows_module("windows_runtime")

    def manifest(self):
        return {"schema_version": 1, "version": "3.14.10", "architecture": "x64",
                "files": {name: "0" * 64 for name in self.runtime.REQUIRED}}

    def test_manifest_roundtrip_canonical_digest_and_duplicate_rejection(self):
        document = self.manifest()
        self.assertEqual(self.runtime.parse_manifest(json.dumps(document).encode()), document)
        canonical = self.runtime.canonical(document)
        self.assertEqual(canonical, json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         hashlib.sha256(self.runtime.canonical(json.loads(json.dumps(document)))).hexdigest())
        for body in (b"{", b"[]", b'{"schema_version":1,"schema_version":1}',
                     json.dumps(document).replace('"files": {', '"files": {"python.exe": "' + "0" * 64 + '",', 1).encode()):
            with self.subTest(body=body[:80]), self.assertRaises(ValueError):
                self.runtime.parse_manifest(body)

    def test_manifest_rejects_invalid_schema_versions_required_files_paths_and_digests(self):
        for field, value in (("schema_version", True), ("schema_version", 2), ("version", "3.10.9"),
                             ("version", "3.14.10rc1"), ("architecture", "arm64"), ("files", []), ("extra", True)):
            document = self.manifest()
            document[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.runtime.parse_manifest(json.dumps(document).encode())
        for name in self.runtime.REQUIRED:
            document = self.manifest()
            del document["files"][name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                self.runtime.parse_manifest(json.dumps(document).encode())
        for name in ("", "../outside", "/outside", "a/../outside", "a//b", "./file", "C:/outside",
                     "a\\b", "manifest.json", "PYTHON.EXE"):
            document = self.manifest()
            document["files"][name] = "0" * 64
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.runtime.parse_manifest(json.dumps(document).encode())
        for digest in (None, 123, "0" * 63, "0" * 65, "g" * 64, "A" * 64):
            document = self.manifest()
            document["files"]["python.exe"] = digest
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.runtime.parse_manifest(json.dumps(document).encode())


class WindowsBootstrapPortableTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-bootstrap-test-")
        self.root = Path(self.temp.name).resolve()
        self.caller = self.root / "untrusted caller 项目"
        self.scripts = self.root / "explicit scripts with spaces"
        self.caller.mkdir()
        self.scripts.mkdir()
        # Neither a normal module name nor a stdlib shadow in cwd may be imported.
        (self.caller / "caller_only.py").write_text("raise AssertionError('cwd import')\n")
        (self.caller / "json.py").write_text("raise AssertionError('stdlib shadow from cwd')\n")
        (self.scripts / "safe_helper.py").write_text("VALUE = 42\n")
        self.bootstrap = PACK / "lib/windows_bootstrap.py"
        self.env = {**os.environ, "PYTHONPATH": str(self.caller)}
        self.env.pop("AGENT_WORKFLOW_PROJECT_RUNTIME", None)

    def tearDown(self):
        self.temp.cleanup()

    def run_bootstrap(self, args, source=None, env=None):
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(self.bootstrap), *args],
                                cwd=self.caller, env=self.env if env is None else env,
                                input=source, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_script_explicit_import_directory_unicode_argv_and_no_caller_cwd(self):
        script = self.scripts / "entry 中文.py"
        script.write_text("import importlib.util,json,os,sys\nfrom safe_helper import VALUE\n"
                          "print(json.dumps({'argv':sys.argv,'cwd':os.getcwd(),'helper':VALUE,"
                          "'caller':importlib.util.find_spec('caller_only') is not None,"
                          "'first_path':sys.path[0]}))\n")
        for prefix in ([], ["--script"], ["-B", "-X", "utf8"]):
            with self.subTest(prefix=prefix):
                actual = self.run_bootstrap([*prefix, str(script), "中文 (a)&", "--literal"])
                self.assertEqual(actual, {"argv": [str(script), "中文 (a)&", "--literal"],
                                         "cwd": str(self.caller), "helper": 42, "caller": False,
                                         "first_path": str(self.scripts)})
        self.assertFalse((self.scripts / "__pycache__").exists())
        self.assertFalse((self.caller / "__pycache__").exists())

    def test_c_and_stdin_modes_preserve_source_and_argv_without_cwd_imports(self):
        source = ("import importlib.util,json,sys\n"
                  "print(json.dumps({'argv':sys.argv,'caller':importlib.util.find_spec('caller_only') is not None,"
                  "'body':'/c/not-a-path JSON & 中文'}))\n")
        for args, stdin, expected in ((["-c", source, "literal /c/x"], None, ["-c", "literal /c/x"]),
                                      (["-", "arg 中文"], source, ["-", "arg 中文"]), ([], source, ["-"])):
            with self.subTest(mode=args[:1]):
                actual = self.run_bootstrap(args, stdin)
                self.assertEqual(actual["argv"], expected)
                self.assertFalse(actual["caller"])
                self.assertEqual(actual["body"], "/c/not-a-path JSON & 中文")

    def test_module_mode_uses_explicit_runtime_not_caller_directory(self):
        module = self.scripts / "safe_module.py"
        module.write_text("import importlib.util,json,sys\nfrom safe_helper import VALUE\n"
                          "print(json.dumps({'helper':VALUE,'argv':sys.argv,"
                          "'caller':importlib.util.find_spec('caller_only') is not None}))\n")
        actual = self.run_bootstrap(["-m", "safe_module", "中文"],
                                    env={**self.env, "AGENT_WORKFLOW_PROJECT_RUNTIME": str(self.scripts)})
        self.assertEqual(actual["helper"], 42)
        self.assertEqual(actual["argv"], [str(module), "中文"])
        self.assertFalse(actual["caller"])


@unittest.skipUnless(os.name == "nt", "requires native Windows NTFS; portable mocks do not verify Win32 safety")
class WindowsFilesystemNativeTest(unittest.TestCase):
    """Never weaken checks for missing Win32 permissions/durability capabilities."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="awf-win32-native-")
        self.root = Path(self.temp.name).resolve()
        self.fs = windows_module("windows_fs")
        self.addCleanup(self.temp.cleanup)
        # A capability refusal is a native validation failure, not a simulated pass.
        with self.fs.Directory(self.root):
            pass

    def test_directory_identity_case_alias_relative_names_and_pinned_rename(self):
        target = self.root / "PinnedCase"
        target.mkdir()
        with self.fs.Directory(target) as first, self.fs.Directory(str(target).swapcase()) as alias:
            self.assertEqual(first.identity, alias.identity)
            self.assertEqual(first.child("leaf"), target / "leaf")
            for name in ("", ".", "..", "../escape", "a/b", "a\\b", "a:b"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    first.child(name)
            with self.assertRaises(OSError):
                os.rename(target, self.root / "moved")
            self.assertTrue(target.is_dir())
        os.rename(target, self.root / "moved")

    def test_exhausted_or_context_closed_scandir_does_not_pin_directory(self):
        for exhausted in (False, True):
            with self.subTest(exhausted=exhausted):
                source = self.root / f"enumerated-{exhausted}"
                source.mkdir()
                (source / "leaf").write_bytes(b"fixture")
                iterator = self.fs.secure_os.scandir(source)
                if exhausted:
                    self.assertEqual([entry.name for entry in iterator], ["leaf"])
                else:
                    with iterator:
                        self.assertEqual(next(iterator).name, "leaf")
                moved = self.root / f"moved-{exhausted}"
                self.fs.secure_os.rename(source, moved)
                self.assertEqual((moved / "leaf").read_bytes(), b"fixture")
                iterator.close()

    def test_no_follow_hardlink_reads_and_truncation_refused_without_changes(self):
        original = self.root / "owned"
        alias = self.root / "hardlink"
        original.write_bytes(b"preserve")
        os.link(original, alias)
        for path in (original, alias):
            for flags in (os.O_RDONLY | self.fs.NOFOLLOW, os.O_WRONLY | os.O_TRUNC | self.fs.NOFOLLOW):
                with self.subTest(path=path, flags=flags), self.assertRaises(ValueError):
                    self.fs.secure_os.open(path, flags)
        self.assertEqual(original.read_bytes(), b"preserve")
        self.assertEqual(alias.read_bytes(), b"preserve")

    def test_junction_reparse_directory_and_descendant_reads_refused(self):
        target = self.root / "target"
        target.mkdir()
        (target / "file").write_bytes(b"preserve")
        junction = self.root / "junction"
        command = str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe")
        result = subprocess.run([command, "/d", "/c", "mklink", "/J", str(junction), str(target)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, "Native junction creation unavailable: " + result.stdout + result.stderr)
        try:
            with self.assertRaises(ValueError):
                self.fs.Directory(junction)
            self.assertTrue(stat.S_ISLNK(self.fs.secure_os.lstat(junction).st_mode))
            with self.assertRaises(ValueError):
                self.fs.secure_os.open(junction / "file", os.O_RDONLY | self.fs.NOFOLLOW)
            self.assertEqual((target / "file").read_bytes(), b"preserve")
        finally:
            os.rmdir(junction)

    def test_crt_tempfile_fchmod_pins_identity_and_file_flush(self):
        descriptor, name = tempfile.mkstemp(dir=self.root)
        try:
            os.write(descriptor, b"durable tempfile")
            before = self.fs.secure_os.fstat(descriptor)
            self.fs.secure_os.fchmod(descriptor, 0o600)
            self.fs.secure_os.fsync(descriptor)
            after = self.fs.secure_os.fstat(descriptor)
            self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))
            self.assertEqual(after.st_nlink, 1)
            with self.assertRaises(ValueError):
                self.fs.secure_os.fchmod(descriptor, 0o400)
        finally:
            self.fs.secure_os.close(descriptor)
        self.assertEqual(self.fs.read_file(Path(name)), b"durable tempfile")

    def test_sid_private_directory_dacl_and_foreign_principal_rejection(self):
        self.assertRegex(self.fs.current_sid(), r"^S-1-\d+(?:-\d+)+$")
        private = self.root / "private"
        self.fs.secure_os.mkdir(private, 0o700)
        self.fs.assert_private(private)
        # Deliberately broaden only this owned temporary directory to Everyone.
        api = self.fs._api()
        handle = self.fs._open_handle(private, 0x60080, directory=True)
        descriptor = self.fs.HANDLE()
        try:
            sddl = f"D:P(A;OICI;GA;;;{self.fs.current_sid()})(A;OICI;GA;;;WD)"
            self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None))
            error = api.security.SetSecurityInfo(handle, 1, 0x80000004,
                                                 None, None, self.fs._dacl(descriptor), None)
            self.assertEqual(error, 0, f"Cannot exercise native private DACL refusal: {error}")
        finally:
            if descriptor.value:
                api.kernel.LocalFree(descriptor)
            self.fs._close(handle)
        with self.assertRaises(ValueError):
            self.fs.assert_private(private)

    def test_directory_flush_capability_preflight_is_real_and_explicit(self):
        descriptor = self.fs.secure_os.open(self.root, os.O_RDONLY | self.fs.DIRECTORY | self.fs.NOFOLLOW)
        try:
            try:
                self.fs.secure_os.fsync(descriptor)
            except OSError as exc:
                self.fail(f"Native durable directory flush capability unavailable; Windows release blocked: {exc}")
        finally:
            self.fs.secure_os.close(descriptor)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_relative_nul_read_truncate_and_delete_preserve_real_leaf(self):
        victim = self.root / "victim"
        victim.write_bytes(b"user content")
        descriptor = self.fs.secure_os.open(self.root, self.fs.DIRECTORY | self.fs.NOFOLLOW)
        try:
            for flags in (os.O_RDONLY, os.O_WRONLY | os.O_TRUNC):
                with self.subTest(flags=flags), self.assertRaises(ValueError):
                    self.fs.secure_os.open("victim\0suffix", flags, dir_fd=descriptor)
            with self.assertRaises(ValueError):
                self.fs.secure_os.unlink("victim\0suffix", dir_fd=descriptor)
        finally:
            self.fs.secure_os.close(descriptor)
        self.assertEqual(victim.read_bytes(), b"user content")

    def test_conditional_cleanup_preserves_swapped_identity_and_busy_writer(self):
        victim = self.root / "owned"
        victim.write_bytes(b"owned")
        info = self.fs.secure_os.stat(victim)
        identity = (info.st_dev, info.st_ino)
        digest = hashlib.sha256(b"owned").hexdigest()
        replacement = self.root / "replacement"
        replacement.write_bytes(b"owned")
        opened = self.fs._open_handle
        def swap(path, *args, **kwargs):
            if path == victim:
                os.replace(replacement, victim)
            return opened(path, *args, **kwargs)
        with patch.object(self.fs, "_open_handle", side_effect=swap):
            self.assertFalse(self.fs.remove_file_if_unchanged(victim, digest, identity))
        self.assertEqual(victim.read_bytes(), b"owned")
        with victim.open("r+b"):
            with self.assertRaises(OSError):
                self.fs.remove_file_if_unchanged(victim, digest)
        victim.write_bytes(b"user edit")
        self.assertFalse(self.fs.remove_file_if_unchanged(victim, digest))
        self.assertEqual(victim.read_bytes(), b"user edit")
        self.assertTrue(self.fs.remove_file_if_unchanged(victim, hashlib.sha256(b"user edit").hexdigest()))
        self.assertFalse(victim.exists())

    def test_successful_backend_file_directory_rename_and_delete(self):
        source = self.root / "source"
        target = self.root / "target"
        source.write_bytes(b"owned")
        before = self.fs.secure_os.stat(source)
        self.fs.secure_os.rename(source, target)
        after = self.fs.secure_os.stat(target)
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        self.assertEqual(target.read_bytes(), b"owned")
        self.fs.secure_os.unlink(target)
        source.mkdir()
        self.fs.secure_os.rename(source, target)
        self.fs.secure_os.rmdir(target)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_replacement_preserves_acl_protection_and_future_parent_inheritance(self):
        api = self.fs._api()
        def set_dacl(path, sddl, *, directory=False):
            handle = self.fs._open_handle(path, 0x60080, directory=directory)
            descriptor = self.fs.HANDLE()
            try:
                self.assertTrue(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, ctypes.byref(descriptor), None))
                self.assertEqual(api.security.SetSecurityInfo(handle, 1, 0x80000004,
                    None, None, self.fs._dacl(descriptor), None), 0)
            finally:
                if descriptor.value:
                    api.kernel.LocalFree(descriptor)
                self.fs._close(handle)
        def policy(path):
            handle = self.fs._open_handle(path, self.fs.READ)
            descriptor, acl = self.fs.HANDLE(), self.fs.HANDLE()
            try:
                self.assertEqual(api.security.GetSecurityInfo(handle, 1, 4, None, None,
                    ctypes.byref(acl), None, ctypes.byref(descriptor)), 0)
                control, revision = ctypes.c_uint16(), self.fs.DWORD()
                self.assertTrue(api.security.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)))
                class Size(ctypes.Structure):
                    _fields_ = [("count", self.fs.DWORD), ("used", self.fs.DWORD), ("free", self.fs.DWORD)]
                size = Size()
                self.assertTrue(api.security.GetAclInformation(acl, ctypes.byref(size), ctypes.sizeof(size), 2))
                sids = set()
                for index in range(size.count):
                    ace, text = self.fs.HANDLE(), ctypes.c_wchar_p()
                    self.assertTrue(api.security.GetAce(acl, index, ctypes.byref(ace)))
                    self.assertTrue(api.security.ConvertSidToStringSidW(self.fs.HANDLE(ace.value + 8), ctypes.byref(text)))
                    try:
                        sids.add(text.value)
                    finally:
                        api.kernel.LocalFree(ctypes.cast(text, self.fs.HANDLE))
                return bool(control.value & 0x1000), sids
            finally:
                if descriptor.value:
                    api.kernel.LocalFree(descriptor)
                self.fs._close(handle)
        base_acl = f"D:P(A;OICI;GA;;;{self.fs.current_sid()})(A;OICI;GA;;;SY)"
        for protected in (False, True):
            with self.subTest(protected=protected):
                parent = self.root / str(protected)
                parent.mkdir()
                set_dacl(parent, base_acl, directory=True)
                target, temporary = parent / "target", parent / "temporary"
                target.write_bytes(b"old")
                temporary.write_bytes(b"new")
                if protected:
                    set_dacl(target, base_acl)
                self.assertEqual(policy(target)[0], protected)
                self.fs.copy_permissions(target, temporary)
                self.fs.secure_os.replace(temporary, target)
                self.assertEqual(policy(target)[0], protected)
                set_dacl(parent, base_acl + "(A;OICI;GR;;;WD)", directory=True)
                self.assertEqual("S-1-1-0" in policy(target)[1], not protected)

    def test_runtime_tree_missing_extra_and_changed_files_are_preserved_and_rejected(self):
        runtime = windows_module("windows_runtime")
        tree = self.root / "runtime"
        tree.mkdir()
        files = {name: f"inert fixture {name}".encode() for name in runtime.REQUIRED}
        manifest = {"schema_version": 1, "version": "3.14.10", "architecture": "x64",
                    "files": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}}
        for name, body in files.items():
            (tree / name).write_bytes(body)
        (tree / "manifest.json").write_text(json.dumps(manifest))
        runtime.verify_tree(tree, manifest)
        extra = tree / "unknown"
        extra.write_bytes(b"user content")
        with self.assertRaises(ValueError):
            runtime.verify_tree(tree, manifest)
        self.assertEqual(extra.read_bytes(), b"user content")
        extra.unlink()
        target = tree / "python.exe"
        target.write_bytes(b"user changed")
        with self.assertRaises(ValueError):
            runtime.verify_tree(tree, manifest)
        self.assertEqual(target.read_bytes(), b"user changed")
        target.unlink()
        with self.assertRaises(ValueError):
            runtime.verify_tree(tree, manifest)
        self.assertFalse(target.exists())


class NpmMetadataTest(unittest.TestCase):
    def test_pinned_official_runtime_and_no_lifecycle_or_invented_license(self):
        lock = release.runtime_lock(PACK)
        self.assertEqual(lock["version"], "3.14.10")
        self.assertEqual(lock["sha256"], "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159")
        self.assertIn("HTTPS", lock["provenance"]["method"])
        package = json.loads((PACK / "npm/package.json").read_text())
        self.assertTrue(package["private"])
        self.assertEqual(package["name"], "@geoege-xll/agent-workflow")
        self.assertEqual(package["version"], "0.1.0")
        self.assertNotIn("scripts", package)
        self.assertNotIn("license", package)
        self.assertNotIn("dependencies", package)

    @unittest.skipUnless(shutil.which("node"), "Node is required for CJS unit tests")
    def test_node_cli_unit_tests(self):
        result = subprocess.run([shutil.which("node"), "--test", str(PACK / "npm/agent-workflow.test.cjs")],
                                cwd=PACK, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
