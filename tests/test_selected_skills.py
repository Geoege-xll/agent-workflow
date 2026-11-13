"""精选依赖的独立来源、锁定、危险路径和显式更新边界。"""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from lib.skills import selected_skills as selected
from lib.skills.role_skills import CORE_SKILLS, LEGACY_CORE_SKILLS, PM_SKILLS, ROLE_SKILLS, SELECTED_SKILLS, SELECTED_SKILL_ALIASES
from lib.skills import playwright_runtime as runtime

PACK = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("selected_update", PACK / "scripts/update_selected_skills.py")
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


class SelectedSkillsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_lock, cls.original_files = selected.snapshot(PACK)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="awf-selected-skills-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.fixture = self.root / "fixture"
        self.lock = {"schema_version": 1, "dependencies": {}}
        # 最小来源夹具只服务拒绝合同；真实原版身份另由独立的固定闭包摘要断言。
        for name, spec in selected.SPECS.items():
            if name == "playwright-cli":
                # npm边界必须使用完整且合法的三包闭包，不能沿用Git技能的两文件伪装。
                self.lock["dependencies"][name] = copy.deepcopy(self.original_lock["dependencies"][name])
                prefix = selected.VENDOR + "/" + name + "/"
                for relative, body in self.original_files.items():
                    if relative.startswith(prefix):
                        path = self.fixture / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(body)
                continue
            files = {}
            for relative in {spec["license"], *spec["skills"].values()}:
                body = (name + ":" + relative + "\n中文\n").encode("utf-8")
                path = self.fixture / selected.VENDOR / name / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
                files[relative] = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
            self.lock["dependencies"][name] = {**copy.deepcopy(spec), "commit": "a" * 40, "files": files}
        self.write_lock()

    def write_lock(self):
        (self.fixture / selected.LOCK).write_text(json.dumps(self.lock), encoding="utf-8")

    def test_fixed_original_inventory_and_license_are_independently_identified(self):
        lock, files = selected.snapshot(PACK)
        # 期望由上游tree/blob核对调查得到，不从被测锁反推，防止删资产后同步改锁假绿。
        identities = {
            "grill-me": ("5863806dd4e15c63174bee4e7515a4256792ecfa", 4, 2484, "ef8ba82c13ec166f6d3a0793f80f2fc504d3248865a3cf2e0f9327e7d481f899", "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"),
            "taste": ("f6b76575f949707b4e3c37cd86cb44b0b98643e8", 1631, 36601022, "262d67d4b9ce4e8b0bf95d2f9ae9eda34d149a0b5348006b38b74cadd17c85d4", "4575a543ab88dad12ccea7d97e563d0bce5b448b06072e65d3264497dad326df"),
        }
        for name, (commit, count, size, digest, license_digest) in identities.items():
            item = lock["dependencies"][name]
            self.assertEqual(commit, item["commit"])
            inventory = {p: r for p, r in item["files"].items() if p != "LICENSE"}
            self.assertEqual(count, len(inventory))
            self.assertEqual(size, sum(r["size"] for r in inventory.values()))
            serialized = "".join(r["sha256"] + "  " + p + "\n" for p, r in sorted(inventory.items())).encode()
            self.assertEqual(digest, hashlib.sha256(serialized).hexdigest())
            self.assertEqual(license_digest, item["files"]["LICENSE"]["sha256"])
        explicit = files[selected.skill_path("grill-me")]
        self.assertIn(b"disable-model-invocation: true", explicit)
        self.assertNotIn("grill-me", CORE_SKILLS)
        self.assertIn("grill-me", LEGACY_CORE_SKILLS)
        self.assertEqual({"xy-grill-me", "xy-grilling", "xy-taste", "xy-playwright"}, set(SELECTED_SKILLS))
        self.assertEqual(("xy-grilling",), PM_SKILLS)
        self.assertIn("xy-taste", ROLE_SKILLS["xy-uiux"])
        self.assertIn("xy-playwright", ROLE_SKILLS["xy-web"])
        playwright = lock["dependencies"]["playwright-cli"]
        self.assertEqual("261206400b18cd0629a8b45dd14ea5488fcf261f", playwright["commit"])
        self.assertEqual(192, len(playwright["files"]))
        self.assertEqual(19174557, sum(record["size"] for record in playwright["files"].values()))
        serialized = "".join(record["sha256"] + "  " + path.removeprefix("runtime/") + "\n"
                             for path, record in sorted(playwright["files"].items())).encode()
        self.assertEqual("db2563118ab78a9bd1263d8add4db28c775a78dd512789acf9cccda1148782bf", hashlib.sha256(serialized).hexdigest())
        for alias, canonical in SELECTED_SKILL_ALIASES.items():
            self.assertEqual(selected.skill_path(canonical), selected.skill_path(alias))

    def test_missing_extra_tampered_symlink_hardlink_and_special_files_fail_closed(self):
        selected.snapshot(self.fixture)
        target = self.fixture / selected.skill_path("grilling")
        original = target.read_bytes()
        target.unlink()
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            selected.snapshot(self.fixture)
        target.write_bytes(original + b"tampered")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            selected.snapshot(self.fixture)
        target.unlink()
        external = self.root / "outside"
        external.write_bytes(original)
        target.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "links/special"):
            selected.snapshot(self.fixture)
        target.unlink()
        target.hardlink_to(external)
        with self.assertRaisesRegex(ValueError, "links/special"):
            selected.snapshot(self.fixture)
        target.unlink()
        target.write_bytes(original)
        extra = self.fixture / selected.VENDOR / "extra"
        extra.write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            selected.snapshot(self.fixture)
        extra.unlink()
        import os
        os.mkfifo(extra)
        with self.assertRaisesRegex(ValueError, "links/special"):
            selected.snapshot(self.fixture)

    def test_lock_rejects_wrong_dependency_sources_paths_and_digest_shapes(self):
        for change in (lambda x: x.update(schema_version=True),
                       lambda x: x["dependencies"].pop("taste"),
                       lambda x: x["dependencies"]["taste"].update(repository="https://evil.invalid"),
                       lambda x: x["dependencies"]["taste"].update(commit="main"),
                       lambda x: x["dependencies"]["taste"].update(roots=["other"]),
                       lambda x: x["dependencies"]["taste"]["files"].update({"../outside": {"size": 0, "sha256": "a" * 64}}),
                       lambda x: x["dependencies"]["taste"]["files"].update({"skills/taste-skill/x": {"size": True, "sha256": "a" * 64}})):
            lock = copy.deepcopy(self.lock)
            change(lock)
            with self.assertRaises(ValueError):
                selected.validate_lock(lock)
        for path in ("../x", "/x", "a//b", "a/./b", "a\\b", "C:/x", "a/../b", "a\x00b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                selected.canonical(path)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            json.loads('{"schema_version":1,"schema_version":1}', object_pairs_hook=selected.unique_object)

    def test_chunked_read_preserves_utf8_full_coverage_and_rejects_bad_ranges(self):
        _, files = selected.snapshot(self.fixture)
        body = files[selected.skill_path("design-taste-frontend")]
        offset, chunks = 0, []
        while True:
            page = selected.read_chunk(files, "design-taste-frontend", offset, 4)
            self.assertEqual(offset, page["offset"])
            chunks.append(page["content"].encode())
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
            if page["eof"]:
                break
        self.assertEqual(body, b"".join(chunks))
        page = selected.read_chunk(files, "design-taste-frontend", len(body), 4)
        self.assertTrue(page["eof"])
        self.assertEqual("", page["content"])
        for offset, length in ((-1, 12000), (len(body) + 1, 12000), (0, 0), (0, 16001), (body.index("中".encode()) + 1, 4)):
            with self.subTest(offset=offset, length=length), self.assertRaises(ValueError):
                selected.read_chunk(files, "design-taste-frontend", offset, length)

    def test_playwright_archives_require_exact_graph_integrity_and_full_inventory(self):
        expected_item = copy.deepcopy(self.original_lock["dependencies"]["playwright-cli"])
        prefix = selected.VENDOR + "/playwright-cli/"
        expected_files = {path.removeprefix(prefix): body for path, body in self.original_files.items()
                          if path.startswith(prefix)}
        archives = []
        # clean checkout 只消费已提交的完整 vendor/lock。这里重新封装的是本地合成
        # tarball，不能冒充官方 npm 原始归档；仅将归档层的摘要/大小替换为合成值，
        # 原版文件字节、mode、包版本、精确依赖图及完整清单仍须全部通过生产验证器。
        for package in expected_item["packages"]:
            package_prefix = "runtime/node_modules/" + package["name"] + "/"
            archive = self.root / (package["name"].replace("/", "-") + ".tgz")
            with tarfile.open(archive, "w:gz") as stream:
                for path, record in sorted(expected_item["files"].items()):
                    if path.startswith(package_prefix):
                        entry = tarfile.TarInfo("package/" + path.removeprefix(package_prefix))
                        entry.size, entry.mode = record["size"], record["mode"]
                        stream.addfile(entry, io.BytesIO(expected_files[path]))
            raw = archive.read_bytes()
            package.update(compressed_bytes=len(raw), tarball_sha256=hashlib.sha256(raw).hexdigest(),
                           integrity="sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii"))
            archives.append(archive)
        manifest = {"packages": expected_item["packages"], "files": [
            {"path": path.removeprefix("runtime/"), "sha256": record["sha256"], "bytes": record["size"]}
            for path, record in sorted(expected_item["files"].items())]}
        manifest_path = self.root / "synthetic-runtime-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        item, files = selected.load_playwright_archives(manifest, archives)
        self.assertEqual(expected_item, item)
        self.assertEqual(expected_files, files)
        self.assertEqual(192, len(files))
        output = self.root / "playwright-update-candidate"
        report = update.candidate("playwright-cli", item["commit"], archives, output, manifest_path)
        self.assertEqual([], report["changed"])
        self.assertEqual("unverified_local_archive", report["source_authenticity"])
        self.assertTrue(report["review_required"])
        self.assertFalse(report["upstream_scripts_executed"])
        expected_lock = copy.deepcopy(self.original_lock)
        expected_lock["dependencies"]["playwright-cli"] = expected_item
        self.assertEqual((expected_lock, self.original_files), selected.snapshot(output))
        for change in (lambda value: value["packages"][0].update(integrity="sha512-AAAA"),
                       lambda value: value["packages"][0].update(dependencies={"playwright": "latest"}),
                       lambda value: value["files"].pop(),
                       lambda value: value["files"][0].update(path="../outside")):
            invalid = copy.deepcopy(manifest)
            change(invalid)
            with self.assertRaises(ValueError):
                selected.load_playwright_archives(invalid, archives)
        with self.assertRaises(ValueError):
            selected.load_playwright_archives(manifest, [archives[0]] * 3)

    def test_playwright_launcher_forwards_only_fixed_entry_and_environment(self):
        import os
        current = Path.cwd()
        with mock.patch.object(runtime, "snapshot", return_value=(self.original_lock, {})), \
             mock.patch.object(runtime, "node_runtime", return_value=("/existing/node", "v22.0.0", True)), \
             mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "/existing/cache"}), \
             mock.patch.object(runtime.os, "execve") as execute:
            self.assertEqual(0, runtime.run(["--", "-s=owned-session", "open", "--browser=chromium", "http://127.0.0.1:1234"], PACK))
            node, arguments, environment = execute.call_args.args
            self.assertEqual("/existing/node", node)
            self.assertEqual([node, str(PACK / runtime.ENTRY), "-s=owned-session", "open", "--browser=chromium", "http://127.0.0.1:1234"], arguments)
            self.assertEqual("1", environment["NO_UPDATE_NOTIFIER"])
            self.assertEqual("1", environment["PLAYWRIGHT_SKIP_BROWSER_GC"])
            self.assertEqual("/existing/cache", environment["PLAYWRIGHT_BROWSERS_PATH"])
            self.assertEqual(current, Path.cwd())
        with mock.patch.object(runtime, "snapshot", return_value=(self.original_lock, {})), \
             mock.patch.object(runtime, "node_runtime", return_value=(None, None, False)), \
             mock.patch.object(runtime.os, "execve") as execute:
            with self.assertRaisesRegex(ValueError, "existing Node >=20"):
                runtime.run(["--version"], PACK)
            execute.assert_not_called()


    def archive(self, entries):
        path = self.root / "input.tar.gz"
        with tarfile.open(path, "w:gz") as stream:
            for name, data, kind in entries:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                if kind == tarfile.REGTYPE:
                    entry.size = len(data)
                    stream.addfile(entry, io.BytesIO(data))
                else:
                    entry.linkname = "../outside"
                    stream.addfile(entry)
        return path

    def test_explicit_update_preserves_bytes_reports_unverified_origin_and_never_overwrites(self):
        lock, files = selected.snapshot(PACK)
        item = lock["dependencies"]["grill-me"]
        ref = item["commit"]
        prefix = selected.VENDOR + "/grill-me/"
        entries = [("skills-" + ref + "/" + path.removeprefix(prefix), body, tarfile.REGTYPE) for path, body in files.items() if path.startswith(prefix)]
        # 上游原始tar含闭包外AGENTS软链：只记录忽略，绝不解析或提取其目标。
        entries.append(("skills-" + ref + "/AGENTS.md", b"", tarfile.SYMTYPE))
        archive = self.archive(entries)
        output = self.root / "candidate"
        report = update.candidate("grill-me", ref, archive, output)
        self.assertEqual("unverified_local_archive", report["source_authenticity"])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), report["archive_sha256"])
        self.assertTrue(report["review_required"])
        self.assertEqual(1, report["ignored_nonclosure_links_or_special_entries"])
        self.assertFalse((output / "AGENTS.md").exists())
        self.assertFalse((self.root / "outside").exists())
        self.assertFalse(report["upstream_scripts_executed"])
        self.assertEqual([], report["changed"])
        candidate_lock, candidate_files = selected.snapshot(output)
        self.assertEqual(lock, candidate_lock)
        self.assertEqual(files, candidate_files)
        with self.assertRaisesRegex(ValueError, "new physical"):
            update.candidate("grill-me", ref, archive, output)

    def test_update_rejects_traversal_links_duplicate_paths_and_wrong_ref_before_output(self):
        ref = "a" * 40
        good = "skills-" + ref + "/LICENSE"
        for entries in ([('../outside', b'bad', tarfile.REGTYPE)],
                        [(good, b'bad', tarfile.SYMTYPE)],
                        [(good, b'bad', tarfile.LNKTYPE)],
                        [(good, b'bad', tarfile.FIFOTYPE)],
                        [(good, b'one', tarfile.REGTYPE), (good, b'two', tarfile.REGTYPE)],
                        [("skills-" + "b" * 40 + "/LICENSE", b'bad', tarfile.REGTYPE)]):
            archive = self.archive(entries)
            output = self.root / "rejected"
            with self.assertRaises(ValueError):
                update.candidate("grill-me", ref, archive, output)
            self.assertFalse(output.exists())
            self.assertFalse((self.root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
