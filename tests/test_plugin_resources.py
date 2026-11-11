"""在独立物理安装与真实子进程中验证插件来源边界，不借源码 sys.path 补资源。"""

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

from lib.standard_paths import BUILTIN_STANDARD_SOURCES


PACK = Path(__file__).resolve().parents[1]
ENGINEERING = next(iter(BUILTIN_STANDARD_SOURCES))
PLUGIN_ENV = "AGENT_WORKFLOW_PLUGIN_ROOT"
BRIDGE_ENV = (
    "AGENT_WORKFLOW_RUNTIME_BINDING", "AGENT_WORKFLOW_PROJECT_ROOT",
    "AGENT_WORKFLOW_CONFIG_PATH", "AGENT_WORKFLOW_CORE_ROOT",
)


class PluginResourcesTest(unittest.TestCase):
    def setUp(self):
        # /tmp 在 macOS 上是系统链接；夹具使用其物理位置，生产边界无需为测试放宽。
        temporary = tempfile.TemporaryDirectory(
            prefix="awf-plugin-resources-", dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.install = self.root / "installed"
        self.project = self.root / "project"
        self.project.mkdir()
        # 复制生产模块只用于创建独立安装夹具；子进程仅导入这个安装，不导入源码仓。
        shutil.copytree(PACK / "lib", self.install / "lib",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        originals = {
            relative: (PACK / relative).read_bytes() for relative in BUILTIN_STANDARD_SOURCES
        }
        originals[ENGINEERING] += "\n<!-- 本次独立插件安装的规范字节 -->\n".encode()
        originals.update({
            "product/WORKFLOW.md": "插件工作流正文\r\n".encode(),
            "roles/xy-qa.md": "插件 QA 角色正文\n".encode(),
            "lib/plugin_resources.py": (self.install / "lib/plugin_resources.py").read_bytes(),
            "lib/documents/context_read.py": (self.install / "lib/documents/context_read.py").read_bytes(),
        })
        for relative, body in originals.items():
            target = self.install / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        self.originals = originals
        self.manifest = {
            "schema_version": 1,
            "files": {relative: hashlib.sha256(body).hexdigest() for relative, body in originals.items()},
        }
        self.manifest_path = self.install / "workflow-sources.json"
        self.write_manifest(self.manifest)
        # 项目中的同名来源与源码仓内容都故意不同，成功必须证明使用了插件字节。
        decoy = self.project / ENGINEERING
        decoy.parent.mkdir(parents=True)
        decoy.write_bytes(b"project-owned builtin decoy\n")
        (self.project / "project.yaml").write_bytes(b"actual project adapter\n")
        (self.install / "project.yaml").write_bytes(b"plugin adapter must never be used\n")
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("AGENT_WORKFLOW_") and key != "PYTHONPATH"
        }
        self.environment.update({PLUGIN_ENV: str(self.install), "PYTHONDONTWRITEBYTECODE": "1"})

    def write_manifest(self, value):
        self.manifest_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def invoke(self, code, *, environment=None):
        # -I 隔离用户site和PYTHONPATH；显式加入的只有独立安装根。cwd是实际项目，
        # 因此源码仓的当前目录、模块缓存或同名lib包均不能让测试偶然通过。
        script = ("import sys\nfrom pathlib import Path\nimport json, hashlib\n"
                  "sys.path.insert(0, sys.argv[1])\n"
                  "from lib import plugin_resources as resources\n" + code)
        return subprocess.run(
            [sys.executable, "-I", "-B", "-X", "utf8", "-c", script, str(self.install)],
            cwd=self.project, env=self.environment if environment is None else environment,
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )

    def assert_success(self, code, *, environment=None):
        result = self.invoke(code, environment=environment)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result

    def assert_rejected(self, code, message, *, environment=None):
        result = self.invoke(code, environment=environment)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        return result

    def test_no_environment_preserves_source_digests_catalog_and_unbounded_legacy_reader(self):
        environment = {key: value for key, value in self.environment.items() if key != PLUGIN_ENV}
        external = self.root / "legacy-explicit.md"
        external.write_bytes(b"legacy explicit path\n")
        self.assert_success(
            "from lib import runtime_pins, task_graph_records as records\n"
            "from lib.validate_project_docs import builtin_standard_rule_catalog\n"
            "from lib.documents.context_read import read_page\n"
            "assert resources.plugin_root() is None\n"
            "assert runtime_pins.record_binding({}) is None\n"
            f"assert records.document_digest(Path.cwd(), {ENGINEERING!r}) == "
            f"hashlib.sha256((Path.cwd() / {ENGINEERING!r}).read_bytes()).hexdigest()\n"
            f"catalog = builtin_standard_rule_catalog(Path({str(PACK)!r}))\n"
            f"assert catalog[{ENGINEERING!r}]['content_fingerprint'] == "
            f"hashlib.sha256((Path({str(PACK)!r}) / {ENGINEERING!r}).read_bytes()).hexdigest()\n"
            f"assert read_page(Path({str(external)!r}))['text'] == 'legacy explicit path\\n'\n"
            # 旧source分页器在显式root下的绝对路径语义也不由插件修复顺带改写。
            f"assert read_page(Path({str(external)!r}), root=Path.cwd())['text'] == 'legacy explicit path\\n'\n",
            environment=environment,
        )

    def test_builtin_digest_and_catalog_only_accept_current_installation_bytes(self):
        expected = self.manifest["files"][ENGINEERING]
        self.assert_success(
            "from lib import runtime_pins, task_graph_records as records\n"
            "from lib.validate_project_docs import builtin_standard_rule_catalog\n"
            "assert resources.plugin_root() == Path(sys.argv[1])\n"
            "assert runtime_pins.record_binding({}, initialize=True) is None\n"
            f"assert records.document_digest(Path.cwd(), {ENGINEERING!r}) == {expected!r}\n"
            f"assert records.document_digest(Path.cwd(), {'.agent-workflow/' + ENGINEERING!r}) == {expected!r}\n"
            f"assert records.file_digest(Path.cwd(), {ENGINEERING!r}) != {expected!r}\n"
            # 故意传源码根：插件模式不能据此读取源码中的同名内置规则。
            f"catalog = builtin_standard_rule_catalog(Path({str(PACK)!r}))\n"
            f"assert catalog[{ENGINEERING!r}]['content_fingerprint'] == {expected!r}\n"
            f"assert resources.read_builtin_source({ENGINEERING!r}) == "
            f"resources.read_builtin_source({'.agent-workflow/' + ENGINEERING!r})\n",
        )

    def test_context_reader_resolves_manifest_sources_and_keeps_project_adapter_local(self):
        self.assert_success(
            "from lib.documents.context_read import read_page\n"
            f"expected = resources.read_builtin_source({ENGINEERING!r}).decode()\n"
            f"for path in (Path({ENGINEERING!r}), Path({'.agent-workflow/' + ENGINEERING!r}), "
            f"Path.cwd() / {ENGINEERING!r}, Path(sys.argv[1]) / {ENGINEERING!r}):\n"
            "    page = read_page(path, root=Path.cwd())\n"
            "    assert page['text'] == expected[:6000]\n"
            "    assert page['sha256'] == hashlib.sha256(expected.encode()).hexdigest()\n"
            "page = read_page(Path('product/WORKFLOW.md'), root=Path.cwd(), limit=3)\n"
            "assert page['text'] == '插件工'\n"
            "assert page['sha256'] == hashlib.sha256(resources.read_source('product/WORKFLOW.md')).hexdigest()\n"
            "assert read_page(Path('project.yaml'), root=Path.cwd())['text'] == 'actual project adapter\\n'\n"
            "assert resources.resource_path(Path('project.yaml'), Path.cwd()) is None\n",
        )

    def test_arbitrary_relative_missing_and_symlink_environment_roots_are_rejected(self):
        decoy = self.root / "other-install"
        decoy.mkdir()
        (decoy / "workflow-sources.json").write_bytes(self.manifest_path.read_bytes())
        alias = self.root / "installation-link"
        alias.symlink_to(self.install, target_is_directory=True)
        cases = (str(decoy), ".", "", str(self.root / "missing"), str(alias),
                 str(self.install / ".." / self.install.name), str(PACK))
        for supplied in cases:
            with self.subTest(root=supplied):
                self.assert_rejected("resources.plugin_root()\n", "插件根",
                                     environment={**self.environment, PLUGIN_ENV: supplied})

    def test_every_bridge_environment_key_is_rejected_even_when_empty(self):
        for key in BRIDGE_ENV:
            with self.subTest(key=key):
                self.assert_rejected("resources.plugin_root()\n", "不能与中央桥环境混用",
                                     environment={**self.environment, key: ""})

    def test_existing_pin_and_central_marker_never_enter_plugin_source_mode(self):
        self.assert_rejected(
            "from lib.runtime_pins import record_binding\n"
            "record_binding({'runtime_binding': {}}, root=Path.cwd())\n",
            "不能接管已有 runtime_binding",
        )
        marker = self.project / ".agent-workflow/runtime.json"
        marker.parent.mkdir()
        for linked in (False, True):
            with self.subTest(linked=linked):
                if linked:
                    marker.symlink_to(self.root / "missing-central-marker")
                else:
                    marker.write_bytes(b"{}\n")
                self.assert_rejected(
                    "from lib.runtime_pins import record_binding\n"
                    "record_binding({}, root=Path.cwd())\n",
                    "不能接管已有 runtime_binding",
                )
                marker.unlink()

    def test_manifest_shape_paths_and_digest_formats_are_strict(self):
        cases = [
            [], {}, {"schema_version": True, "files": self.manifest["files"]},
            {**self.manifest, "extra": "ignored"}, {"schema_version": 1, "files": []},
            {"schema_version": 1, "files": {}}, {"schema_version": 2, "files": {"file": "a" * 64}},
        ]
        cases.extend({"schema_version": 1, "files": {path: digest}} for path, digest in (
            ("../outside.md", "a" * 64), ("/outside.md", "a" * 64),
            ("product//WORKFLOW.md", "a" * 64), ("product/./WORKFLOW.md", "a" * 64),
            ("product\\WORKFLOW.md", "a" * 64), ("C:/outside.md", "a" * 64),
            ("product/WORKFLOW.md", "A" * 64), ("product/WORKFLOW.md", "a" * 63),
            ("product/WORKFLOW.md", 1), ("product/WORKFLOW.md\x00", "a" * 64),
        ))
        for value in cases:
            with self.subTest(value=value):
                self.write_manifest(value)
                self.assert_rejected("resources.plugin_root()\n", "插件来源清单")
        for invalid in ('{"schema_version":1,"schema_version":1,"files":{"x":"' + "a" * 64 + '"}}',
                        '{"schema_version":1,"files":{"x":"' + "a" * 64 + '","x":"' + "a" * 64 + '"}}',
                        '{broken'):
            with self.subTest(invalid=invalid):
                self.manifest_path.write_text(invalid, encoding="utf-8")
                self.assert_rejected("resources.plugin_root()\n", "插件来源清单损坏")

    def test_missing_manifest_symlink_and_hardlink_are_rejected(self):
        original = self.manifest_path.read_bytes()
        self.manifest_path.unlink()
        self.assert_rejected("resources.plugin_root()\n", "插件来源缺失或不符合安全读取要求")
        target = self.root / "manifest-copy.json"
        target.write_bytes(original)
        for linked in ("symbolic", "hard"):
            with self.subTest(linked=linked):
                if linked == "symbolic":
                    self.manifest_path.symlink_to(target)
                else:
                    os.link(target, self.manifest_path)
                self.assert_rejected("resources.plugin_root()\n", "插件来源清单损坏")
                self.manifest_path.unlink()

    def test_mutated_manifest_digest_and_mutated_file_never_fall_back_to_project(self):
        self.manifest["files"][ENGINEERING] = "0" * 64
        self.write_manifest(self.manifest)
        self.assert_rejected(f"resources.read_builtin_source({ENGINEERING!r})\n", "SHA-256 与清单不一致")
        self.manifest["files"][ENGINEERING] = hashlib.sha256(self.originals[ENGINEERING]).hexdigest()
        self.write_manifest(self.manifest)
        (self.install / ENGINEERING).write_bytes(b"damaged installed builtin\n")
        self.assert_rejected(
            "from lib.task_graph_records import document_digest\n"
            f"document_digest(Path.cwd(), {ENGINEERING!r})\n", "SHA-256 与清单不一致",
        )

    def test_missing_manifest_builtin_cannot_be_replaced_by_same_project_path(self):
        del self.manifest["files"][ENGINEERING]
        self.write_manifest(self.manifest)
        self.assert_rejected(
            "from lib.task_graph_records import document_digest\n"
            f"document_digest(Path.cwd(), {ENGINEERING!r})\n", "不在插件来源清单中",
        )
        self.assert_rejected(
            "from lib.documents.context_read import read_page\n"
            f"read_page(Path({ENGINEERING!r}), root=Path.cwd())\n", "拒绝项目同名替代",
        )

    def test_missing_manifest_authority_cannot_be_replaced_by_project_decoys(self):
        # 不能只保护三份builtin：工作流、角色以及其余platforms来源同样是插件权威。
        # 每个逻辑路径和既有别名都创建真实项目诱饵，防止测试只因文件缺失而通过。
        paths = ("product/WORKFLOW.md", "roles/xy-qa.md", "platforms/shared/AGENTS.product.tpl")
        for relative in paths:
            self.manifest["files"].pop(relative, None)
            installed = self.install / relative
            installed.parent.mkdir(parents=True, exist_ok=True)
            if not installed.exists():
                installed.write_bytes(b"installed authority omitted from manifest\n")
            for alias in (relative, ".agent-workflow/" + relative):
                decoy = self.project / alias
                decoy.parent.mkdir(parents=True, exist_ok=True)
                decoy.write_bytes(b"PROJECT DECOY AUTHORITY\n")
        self.write_manifest(self.manifest)
        for relative in paths:
            for path in (relative, ".agent-workflow/" + relative,
                         str(self.project / relative), str(self.install / relative)):
                with self.subTest(path=path):
                    result = self.assert_rejected(
                        "from lib.documents.context_read import read_page\n"
                        f"print(read_page(Path({path!r}), root=Path.cwd())['text'])\n",
                        "插件权威资源不在插件来源清单中；拒绝项目同名替代",
                    )
                    self.assertNotIn("PROJECT DECOY AUTHORITY", result.stdout)
        # 无插件声明的旧source模式不使用插件清单，也不新增命名空间保留规则。
        environment = {key: value for key, value in self.environment.items() if key != PLUGIN_ENV}
        self.assert_success(
            "from lib.documents.context_read import read_page\n"
            f"for relative in {paths!r}:\n"
            "    assert read_page(Path(relative), root=Path.cwd())['text'] == 'PROJECT DECOY AUTHORITY\\n'\n",
            environment=environment,
        )

    def test_missing_symlink_hardlink_and_symlink_parent_resources_are_rejected(self):
        target = self.install / ENGINEERING
        original = target.read_bytes()
        target.unlink()
        self.assert_rejected(f"resources.read_builtin_source({ENGINEERING!r})\n", "插件来源缺失")
        outside = self.root / "external-rule.md"
        outside.write_bytes(original)
        for linked in ("symbolic", "hard"):
            with self.subTest(linked=linked):
                if linked == "symbolic":
                    target.symlink_to(outside)
                else:
                    os.link(outside, target)
                self.assert_rejected(f"resources.read_builtin_source({ENGINEERING!r})\n", "安全读取要求")
                target.unlink()
        target.write_bytes(original)
        actual = target.parent.with_name("actual-references")
        target.parent.rename(actual)
        target.parent.symlink_to(actual, target_is_directory=True)
        self.assert_rejected(f"resources.read_builtin_source({ENGINEERING!r})\n", "安全读取要求")

    def test_source_path_is_exact_and_project_adapter_stays_project_owned_even_if_mislisted(self):
        self.manifest["files"]["project.yaml"] = hashlib.sha256(
            (self.install / "project.yaml").read_bytes()).hexdigest()
        self.write_manifest(self.manifest)
        self.assert_rejected("resources.read_source('project.yaml')\n", "项目适配器不能作为插件来源读取")
        for path in ("../project.yaml", ".agent-workflow/product/WORKFLOW.md", "roles/unknown.md"):
            with self.subTest(path=path):
                self.assert_rejected(f"resources.read_source({path!r})\n", "不在插件来源清单中")
        self.assert_rejected("resources.read_builtin_source('product/WORKFLOW.md')\n", "不是精确的内置规范")
        self.assert_success(
            "from lib.documents.context_read import read_page\n"
            "assert read_page(Path('project.yaml'), root=Path.cwd())['text'] == 'actual project adapter\\n'\n",
        )
        self.assert_success(
            "from lib.validate_project_docs import validate\n"
            "errors = validate(Path(sys.argv[1]) / 'project.yaml', Path.cwd())\n"
            "assert len(errors) == 1 and '实际项目中的适配器' in errors[0], errors\n",
        )

    def test_project_leaf_requires_actual_project_boundary_and_rejects_links(self):
        leaf = self.project / "docs/standards/local.md"
        leaf.parent.mkdir(parents=True)
        leaf.write_bytes("项目工程规则\n".encode())
        outside = self.root / "outside-leaf.md"
        outside.write_bytes(b"private outside project\n")
        self.assert_success(
            "from lib.task_graph_records import document_digest\n"
            "from lib.documents.context_read import read_page\n"
            "assert resources.resource_path(Path('docs/standards/local.md'), Path.cwd()) is None\n"
            "assert document_digest(Path.cwd(), 'docs/standards/local.md') == "
            "hashlib.sha256(Path('docs/standards/local.md').read_bytes()).hexdigest()\n"
            "assert read_page(Path('docs/standards/local.md'))['text'] == '项目工程规则\\n'\n",
        )
        self.assert_rejected(
            "from lib.documents.context_read import read_page\n"
            f"read_page(Path({str(outside)!r}), root=Path.cwd())\n", "必须位于实际项目根内",
        )
        self.assert_rejected(
            "from lib.task_graph_records import document_digest\n"
            "document_digest(Path.cwd(), '../outside-leaf.md')\n", "root-relative",
        )
        (self.project / "linked-leaf.md").symlink_to(outside)
        self.assert_rejected(
            "from lib.documents.context_read import read_page\n"
            "read_page(Path('linked-leaf.md'), root=Path.cwd())\n", "安全读取要求",
        )


if __name__ == "__main__":
    unittest.main()
