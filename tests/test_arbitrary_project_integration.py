from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


PACK = Path(__file__).resolve().parents[1]


class ArbitraryProjectIntegrationMatrixTest(unittest.TestCase):
    """Task 14: the unchanged pack installs into representative repositories."""

    @staticmethod
    def write_files(project: Path, files: dict[str, str]) -> None:
        for relative, body in files.items():
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    @staticmethod
    def run_setup(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "agent_workflow/setup_all.sh", *arguments],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )

    @staticmethod
    def generated_roles(project: Path, host: str) -> set[str]:
        if host == "claude":
            root, suffix = project / ".claude/agents", ".md"
        elif host == "codex":
            root, suffix = project / ".codex/agents", ".toml"
        else:
            root, suffix = project / ".agents/agents", ".md"
        return {
            path.name.removesuffix(suffix)
            for path in root.glob(f"xy-*{suffix}")
            if path.is_file()
        }

    @staticmethod
    def fixture_cases() -> dict[str, tuple[dict[str, str], set[str], bytes | None]]:
        apple_project = (
            "// !$*UTF8*$!\n{\n  objects = {\n"
            "    A1 = {\n      isa = PBXNativeTarget;\n"
            '      productType = "com.apple.product-type.application";\n'
            "    };\n  };\n}\n"
        )
        android_build = (
            "plugins { alias(libs.plugins.android.application) }\n"
        )
        android_catalog = (
            '[versions]\nagp = "9.0.0"\n\n'
            '[plugins]\nandroid-application = { id = "com.android.application", version.ref = "agp" }\n'
        )
        electron_package = (
            '{"main":"src/main.js","dependencies":{"electron":"40"},'
            '"scripts":{"test":"node --test","package":"electron-forge package"}}'
        )
        tauri_cargo = (
            '[package]\nname="fixture"\nversion="0.1.0"\n'
            '[dependencies]\ntauri="2"\n'
        )
        java_contract = (
            b"# Engineering\n\n- Domain: engineering\n\n## Required project constraints\n\n"
            b"- `[eng-java-001] [hard]` Java 21 is required for compilation and runtime.\n"
        )
        qa_backend = {"xy-backend", "xy-qa"}
        return {
            "go-api": (
                {"go.mod": "module example.test/api\n\ngo 1.25\n"},
                qa_backend,
                None,
            ),
            "react-go-monorepo": (
                {
                    "apps/web/package.json": (
                        '{"dependencies":{"react":"19"},'
                        '"scripts":{"build":"vite build"}}'
                    ),
                    "services/api/go.mod": "module example.test/api\n",
                },
                {"xy-web", "xy-backend", "xy-uiux", "xy-qa"},
                None,
            ),
            "php-service": (
                {"composer.json": '{"name":"example/service","require":{"php":"^8.4"}}'},
                qa_backend,
                None,
            ),
            "cpp-service": (
                {
                    "CMakeLists.txt": (
                        "cmake_minimum_required(VERSION 3.30)\n"
                        "project(service)\nadd_executable(service main.cpp)\n"
                    ),
                    "main.cpp": "int main() { return 0; }\n",
                },
                qa_backend,
                None,
            ),
            "java21-over-observed-17": (
                {
                    "pom.xml": (
                        "<project><modelVersion>4.0.0</modelVersion>"
                        "<properties><maven.compiler.release>17</maven.compiler.release>"
                        "</properties></project>"
                    )
                },
                qa_backend,
                java_contract,
            ),
            "apple-app": (
                {"App.xcodeproj/project.pbxproj": apple_project},
                {"xy-apple", "xy-uiux", "xy-qa"},
                None,
            ),
            "android-app": (
                {
                    "build.gradle.kts": android_build,
                    "gradle/libs.versions.toml": android_catalog,
                    "src/main/AndroidManifest.xml": '<manifest package="example.app"/>\n',
                },
                {"xy-android", "xy-uiux", "xy-qa"},
                None,
            ),
            "electron-app": (
                {
                    "package.json": electron_package,
                    "src/main.js": "export {};\n",
                },
                {"xy-desktop", "xy-uiux", "xy-qa"},
                None,
            ),
            "tauri-app": (
                {
                    "package.json": '{"dependencies":{"react":"19"}}',
                    "src-tauri/tauri.conf.json": '{"productName":"Fixture"}',
                    "src-tauri/Cargo.toml": tauri_cargo,
                },
                {"xy-desktop", "xy-uiux", "xy-qa"},
                None,
            ),
            "electron-plus-web": (
                {
                    "desktop/package.json": electron_package,
                    "desktop/src/main.js": "export {};\n",
                    "apps/web/package.json": '{"dependencies":{"react":"19"}}',
                },
                {"xy-desktop", "xy-web", "xy-uiux", "xy-qa"},
                None,
            ),
            "language-neutral-openapi-service": (
                {
                    "openapi.json": (
                        '{"openapi":"3.1.0","info":{"title":"Service",'
                        '"version":"1"},"paths":{"/health":{"get":{}}}}'
                    ),
                    "Dockerfile": "FROM scratch\nCOPY service /service\n",
                },
                qa_backend,
                None,
            ),
        }

    def test_fresh_projects_preflight_install_twice_and_check(self) -> None:
        selected = os.environ.get("AGENT_WORKFLOW_INTEGRATION_CASE")
        for label, (files, expected_roles, engineering) in self.fixture_cases().items():
            if selected and label != selected:
                continue
            with self.subTest(project=label), tempfile.TemporaryDirectory(
                prefix=f"workflow-integration-{label}-"
            ) as temporary:
                project = Path(temporary) / "Project"
                pack = project / "agent_workflow"
                project.mkdir()
                shutil.copytree(
                    PACK,
                    pack,
                    ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
                    symlinks=True,
                )
                shutil.copy2(pack / "templates/project.yaml.example", pack / "project.yaml")
                config = pack / "project.yaml"
                config.write_text(
                    config.read_text(encoding="utf-8").replace(
                        "project_id: replace-with-unique-project-id",
                        f"project_id: integration-{uuid.uuid4().hex}",
                        1,
                    ),
                    encoding="utf-8",
                )
                self.write_files(project, files)
                sentinel = project / "USER_CONTENT.txt"
                sentinel_bytes = f"user-owned:{label}\n".encode()
                sentinel.write_bytes(sentinel_bytes)
                sentinel.chmod(0o640)
                if engineering is not None:
                    target = project / "docs/standards/GENERAL.md"
                    target.parent.mkdir(parents=True)
                    target.write_bytes(engineering)
                    target.chmod(0o640)

                preview = subprocess.run(
                    [
                        sys.executable,
                        str(pack / "lib/project_profile_cli.py"),
                        "json",
                        str(pack),
                        str(project),
                    ],
                    cwd=project,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
                self.assertEqual(expected_roles, set(json.loads(preview.stdout)["enabled_roles"]))

                preflight = self.run_setup(project, "--preflight")
                self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
                self.assertFalse((project / "AGENTS.md").exists())
                self.assertFalse((project / "CLAUDE.md").exists())
                self.assertEqual(sentinel_bytes, sentinel.read_bytes())

                for attempt in ("first", "second"):
                    installed = self.run_setup(project)
                    self.assertEqual(
                        installed.returncode,
                        0,
                        f"{label} {attempt}\n{installed.stdout}{installed.stderr}",
                    )
                checked = self.run_setup(project, "--check")
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

                for host in ("claude", "codex", "antigravity"):
                    self.assertEqual(expected_roles, self.generated_roles(project, host))
                self.assertTrue(
                    {"xy-python", "xy-rust", "xy-java"}.isdisjoint(expected_roles)
                )
                self.assertEqual(sentinel_bytes, sentinel.read_bytes())
                self.assertEqual(0o640, stat.S_IMODE(sentinel.stat().st_mode))
                if engineering is not None:
                    target = project / "docs/standards/GENERAL.md"
                    self.assertEqual(engineering, target.read_bytes())
                    self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))
                leftovers = [
                    path.relative_to(project).as_posix()
                    for path in project.iterdir()
                    if path.name.startswith(".agent-workflow-")
                ]
                self.assertEqual([], leftovers)


if __name__ == "__main__":
    unittest.main()
