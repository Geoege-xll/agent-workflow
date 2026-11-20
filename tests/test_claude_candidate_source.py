"""Claude 候选的独立来源边界；使用真实文件、ZIP 与宿主登记 JSON 协议。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


if os.name != "posix":
    raise unittest.SkipTest("本机 Claude 核验器使用 POSIX 文件描述符与账户目录")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_claude_candidate.py"
spec = importlib.util.spec_from_file_location("candidate_verifier", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


# 保留系统进程入口供 macOS 的真实元数据测试使用；普通回归只替换账户、登记和内核计数。
REAL_RUN = subprocess.run


class ClaudeCandidateSourceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.trust = self.home / verifier.TRUST_DIR
        self.trust.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.trust / SCRIPT.name)
        self.version = "3.0.8"
        self.market = self.home / "独立 候选市场"
        self.folder = self.market / "plugins/xy-workflow"
        self.cache = self.home / ".claude/plugins/cache/xy-workflow-local/xy-workflow" / self.version
        self.zip = self.trust / "claude-plugin.zip"
        self.manifest = {"name": verifier.MARKET, "owner": {"name": "Agent Workflow"},
                         "plugins": [{"name": "xy-workflow", "source": "./plugins/xy-workflow"}]}
        self.manifest_path = self.market / ".claude-plugin/marketplace.json"
        self.manifest_path.parent.mkdir(parents=True)
        self.manifest_path.write_text(json.dumps(self.manifest))
        # 主插件 ZIP 包含普通正文与必须保留三个执行位的入口；两份载荷均单独落盘以捕获混装。
        payload = {
            ".claude-plugin/plugin.json": (json.dumps({"name": "xy-workflow", "version": self.version}), 0o644),
            "sources.json": (json.dumps({"host": "claude", "plugin_name": "xy-workflow",
                                         "plugin_version": self.version}), 0o644),
            "bin/helper": ("#!/bin/sh\nexit 0\n", 0o755),
            "skills/xy-workflow/SKILL.md": ("当前测试候选的原生 Skill", 0o644),
        }
        with zipfile.ZipFile(self.zip, "w") as archive:
            for name, (body, mode) in payload.items():
                entry = zipfile.ZipInfo(name)
                entry.external_attr = (stat.S_IFREG | mode) << 16
                archive.writestr(entry, body)
                for root in (self.folder, self.cache):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body.encode())
                    path.chmod(mode)
        self.pin = {"version": self.version, "marketplace_path": str(self.market),
                    "sha256": hashlib.sha256(self.zip.read_bytes()).hexdigest(), "source_revision": "b" * 40}
        self.pin_path = self.trust / "pin.json"
        self.pin_path.write_text(json.dumps(self.pin))
        self.market_row = {"name": verifier.MARKET, "path": str(self.market), "source": "directory",
                           "installLocation": str(self.market)}
        self.local = {"id": verifier.LOCAL_ID, "version": self.version, "folderVersion": self.version,
                      "scope": "user", "enabled": True, "projectEnabled": False,
                      "readFromFolder": str(self.folder), "installPath": str(self.cache)}
        self.stable = {"id": verifier.STABLE_ID, "version": "3.0.7", "scope": "user",
                       "enabled": False, "projectEnabled": False}
        self.markets = [self.market_row]
        self.plugins = [self.stable, self.local]
        self.deadline = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.native = False

        # 只替换账户与宿主 CLI 回包；摘要、遍历、权限检查与最终核验入口均执行生产代码。
        for replacement in (
            patch.object(verifier.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(self.home))),
            patch.object(verifier, "__file__", str(self.trust / SCRIPT.name)),
            patch.object(verifier, "sys", SimpleNamespace(platform="darwin", flags=SimpleNamespace(isolated=1),
                                                         dont_write_bytecode=True)),
            patch.dict(os.environ, {"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}),
            patch.object(verifier.subprocess, "run", side_effect=self.official),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def official(self, args, **options):
        if args[0] != verifier.CLAUDE:
            if self.native:
                return REAL_RUN(args, **options)
            if args[:2] == [verifier.APFS, "-S"]:
                data = b"gen-count: 123\n"
            elif args[0] == "/usr/sbin/sysctl":
                data = b"12345678-1234-1234-1234-123456789ABC\n"
            elif args[:2] == [verifier.APFS, "-M"] or args[0] in (verifier.MTREE, "/bin/ls"):
                data = b"sample"
            else:
                self.fail("意外的系统工具")
            return SimpleNamespace(stdout=data, stderr=b"")
        self.assertEqual(args[:2], ["/opt/homebrew/bin/claude", "plugin"])
        self.assertEqual(options["env"]["HOME"], str(self.home))
        if args[2:] == ["marketplace", "list", "--json"]:
            rows = self.markets
        elif args[2:] == ["list", "--json"]:
            rows = self.plugins
        else:
            self.fail("核验器尝试了未授权的 Claude 命令")
        return SimpleNamespace(stdout=json.dumps(rows).encode())

    def attest(self):
        return verifier.attest(self.deadline)

    def test_each_registered_root_and_shared_copy(self):
        receipt = self.attest()
        self.assertEqual(receipt["pin"], self.pin)
        self.assertEqual([receipt["roots"][label]["path"] for label in verifier.ROOT_LABELS],
                         [str(self.folder), str(self.cache)])
        self.local["installPath"] = str(self.folder)
        receipt = self.attest()
        self.assertEqual(receipt["roots"]["read_from_folder"], receipt["roots"]["install_path"])
        self.assertEqual(receipt, json.loads((self.trust / verifier.RECEIPT).read_bytes()))

    def test_ambiguous_or_wrong_registrations(self):
        for row, changes in (
            (self.stable, {"enabled": True}), (self.stable, {"projectEnabled": True}),
            (self.local, {"id": "xy-workflow@unknown"}), (self.local, {"scope": "project"}),
            (self.local, {"enabled": False}), (self.local, {"folderVersion": "3.0.7"}),
            (self.local, {"version": "3.0.7"}), (self.local, {"readFromFolder": str(self.cache)}),
            (self.local, {"installPath": str(self.market)}), (self.market_row, {"source": "git"}),
            (self.market_row, {"path": str(self.home)}), (self.market_row, {"installLocation": str(self.home)}),
        ):
            with self.subTest(changes=changes), patch.dict(row, changes), self.assertRaises(ValueError):
                self.attest()
        for rows, extra in ((self.plugins, self.local), (self.markets, self.market_row),
                            (self.markets, dict(self.market_row, name="other"))):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                rows.append(extra)
                try:
                    self.attest()
                finally:
                    rows.pop()
        self.manifest["plugins"][0]["source"] = "./elsewhere"
        self.manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, "市场索引"):
            self.attest()

    def test_foreign_or_linked_loaded_root_and_nondefault_config(self):
        alias = self.home / "别名"
        alias.symlink_to(self.folder, target_is_directory=True)
        for root in (str(alias), str(self.market), str(self.folder) + "/../xy-workflow"):
            with self.subTest(root=root), patch.dict(self.local, {"readFromFolder": root}), self.assertRaises(ValueError):
                self.attest()
        # 即使命令行上提供了正确的固定根，当前宿主若在另一个配置目录运行也不能采用默认登记。
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home / "other")}), self.assertRaises(ValueError):
            self.attest()

    def test_inactive_copy_cannot_hide_mixed_bytes_extra_resources_or_mode(self):
        for changed in (self.cache, self.folder):
            helper = changed / "bin/helper"
            original = helper.read_bytes()
            with self.subTest(changed=changed):
                helper.write_bytes(b"x" * len(original))
                with self.assertRaisesRegex(ValueError, "内容不符"):
                    self.attest()
                helper.write_bytes(original)
                helper.chmod(0o754)
                with self.assertRaisesRegex(ValueError, "执行位"):
                    self.attest()
                helper.chmod(0o755)
                extra = changed / "bin/.extra"
                extra.write_text("额外脚本")
                extra.chmod(0o755)
                with self.assertRaisesRegex(ValueError, "ZIP 外资源"):
                    self.attest()
                extra.unlink()
                helper.unlink()
                with self.assertRaisesRegex(ValueError, "缺少 ZIP"):
                    self.attest()
                helper.write_bytes(original)
                helper.chmod(0o755)

    def test_file_and_directory_links_to_identical_payload_fail(self):
        for rel in ("bin/helper", "bin"):
            item = self.cache / rel
            backup = self.home / "未登记副本"
            item.rename(backup)
            item.symlink_to(self.folder / rel, target_is_directory=backup.is_dir())
            try:
                with self.subTest(rel=rel), self.assertRaises((ValueError, OSError)):
                    self.attest()
            finally:
                item.unlink()
                backup.rename(item)

    def test_trust_material_write_acl_is_rejected(self):
        with patch.object(verifier, "system_read", return_value=b" 0: foreign allow read,write,append\n"), self.assertRaisesRegex(ValueError, "ACL"):
            self.attest()

    def test_pin_and_verifier_are_independent_fixed_inputs(self):
        with patch.object(verifier, "__file__", str(SCRIPT)), self.assertRaisesRegex(ValueError, "固定用户目录"):
            self.attest()
        self.pin_path.chmod(0o666)
        with self.assertRaisesRegex(ValueError, "写权限"):
            self.attest()
        self.pin_path.chmod(0o600)
        self.pin_path.write_text(json.dumps(dict(self.pin, sha256="a" * 64)))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.attest()
        self.pin_path.unlink()
        candidate_pin = self.folder / "pin.json"
        candidate_pin.write_text(json.dumps(self.pin))
        self.pin_path.symlink_to(candidate_pin)
        with self.assertRaisesRegex(ValueError, "链接"):
            self.attest()

    def test_failed_refresh_and_change_during_proof_invalidate_previous_receipt(self):
        previous = self.attest()
        saved = self.trust / verifier.RECEIPT
        with self.assertRaisesRegex(ValueError, "到期"):
            verifier.attest("2001-01-01T00:00:00Z")
        self.assertFalse(saved.exists())
        self.assertNotEqual(self.attest()["id"], previous["id"])
        with patch.object(verifier, "metadata", side_effect=[b"old", b"new"]), self.assertRaisesRegex(ValueError, "变化"):
            self.attest()
        self.assertFalse(saved.exists())
        with patch.object(verifier, "generation", side_effect=[{"generation": 1}, {"generation": 2}]), self.assertRaisesRegex(ValueError, "变化"):
            self.attest()
        self.assertFalse(saved.exists())

    @unittest.skipUnless(sys.platform == "darwin", "真实 APFS 证明需要 macOS")
    def test_real_apfs_and_metadata_detect_same_size_replacement_and_mode_change(self):
        # 真实系统工具只操作临时测试树；账户目录和两条 Claude 登记仍由夹具隔离。
        self.native = True
        receipt = self.attest()
        for label, root in zip(verifier.ROOT_LABELS, (self.folder, self.cache)):
            spec = self.trust / (label + ".mtree")
            command = [verifier.MTREE, "-P", "-x", "-f", str(spec), "-p", str(root)]
            result = REAL_RUN(command, capture_output=True)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
            before = receipt["roots"][label]
            self.assertEqual(verifier.generation(root), {key: before[key] for key in ("path", "device", "inode", "generation")})
            self.assertEqual(before["metadata_sha256"], hashlib.sha256(spec.read_bytes()).hexdigest())
            current = root / "bin/helper"
            current.chmod(0o700)
            self.assertNotEqual(REAL_RUN(command, capture_output=True).returncode, 0)
            current.chmod(0o755)
            current.write_bytes(b"X" * current.stat().st_size)
            self.assertNotEqual(verifier.generation(root)["generation"], before["generation"])



class CandidateCLIArgumentsTest(unittest.TestCase):
    def test_packaged_business_adapter_uses_the_read_only_os_operations(self):
        # 核对实际随 Claude 插件装配的文档与系统命令；该检查本身不能证明模型完成了派发。
        refs = SCRIPT.parents[1] / "platforms/claude/references"
        entry = (refs / "pm-integration.md").read_text()
        self.assertIn("candidate-receipt.md#read-the-current-candidate-receipt", entry)
        contract = (refs / "candidate-receipt.md").read_text().partition("## 安装或更新候选")[0]
        for fact in ("system.init.plugins[]", "readFromFolder", "installPath", "expires_at", "metadata_sha256",
                     "kern.bootsessionuuid", "receipt id", "mtree -P -x -f", "apfs.util -S"):
            self.assertIn(fact, contract)
        self.assertNotIn("--loaded-root", contract)
        self.assertNotIn("/usr/bin/python", contract)
        self.assertNotIn("apfs.util -M", contract)

    def test_business_session_loaded_root_and_pin_overrides_are_rejected(self):
        for args in ([], ["--plugin-dir", "/tmp/other"], ["--pin", "/tmp/pin", "--loaded-root", "/tmp"],
                     ["--loaded-root", "/tmp", "--loaded-root", "/tmp"]):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), *args],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)


if __name__ == "__main__":
    unittest.main()
