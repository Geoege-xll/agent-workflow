#!/usr/bin/env python3
"""精选第三方技能的固定来源、离线完整性与只读消费入口。"""
from __future__ import annotations

import argparse
import base64
from collections.abc import Callable
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
VENDOR = "third_party/selected-skills"
LOCK = "third_party/selected-skills.lock.json"
DESKTOP_SKILL_ROOT = "skills/agent-desktop"
DESKTOP_BINARIES = ("agent-desktop", "agent-desktop-macos-helper")
DESKTOP_MACOS_TARGETS = {"arm64": "aarch64-apple-darwin", "x86_64": "x86_64-apple-darwin"}
DESKTOP_REFERENCES = ("commands-interaction.md", "commands-observation.md", "commands-system.md", "workflows.md")
SPECS = {
    "agent-desktop": {"repository": "https://github.com/vercel-labs/agent-desktop", "roots": [DESKTOP_SKILL_ROOT, "runtime/macos"], "license": "LICENSE", "skills": {"agent-desktop": DESKTOP_SKILL_ROOT + "/SKILL.md"}},
    "modern-web-guidance": {"repository": "https://github.com/GoogleChrome/modern-web-guidance-src", "roots": ["runtime"], "license": "runtime/LICENSE", "skills": {"modern-web-guidance": "runtime/skills/modern-web-guidance/SKILL.md"}},
    "grill-me": {"repository": "https://github.com/mattpocock/skills", "roots": ["skills/productivity/grill-me", "skills/productivity/grilling"], "license": "LICENSE", "skills": {"grill-me": "skills/productivity/grill-me/SKILL.md", "grilling": "skills/productivity/grilling/SKILL.md"}},
    "taste": {"repository": "https://github.com/Leonxlnx/taste-skill", "roots": ["skills/taste-skill"], "license": "LICENSE", "skills": {"design-taste-frontend": "skills/taste-skill/SKILL.md"}},
    "playwright-cli": {"repository": "https://github.com/microsoft/playwright-cli", "roots": ["runtime/node_modules/@playwright/cli", "runtime/node_modules/playwright", "runtime/node_modules/playwright-core"], "license": "runtime/node_modules/@playwright/cli/LICENSE", "skills": {"playwright-cli": "runtime/node_modules/@playwright/cli/skills/playwright-cli/SKILL.md"}},
}


def canonical(value: str) -> str:
    """锁和归档都只接受单一POSIX表示，防止路径穿越、跨平台分隔符与空段歧义。"""
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("unsafe selected skill path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(p in {"..", "."} or ":" in p for p in path.parts):
        raise ValueError("unsafe selected skill path: " + value)
    return value


def read_regular(root: Path, relative: str, *, max_bytes: int | None = None,
                 expected_stat: tuple[int, ...] | None = None, expected_mode: int | None = None) -> bytes:
    """逐级使用不跟随链接的目录描述符，避免校验后路径被换成软链的时间窗口。

    不执行上游代码。硬链接亦拒绝，确保依赖闭包不能借外部共享inode改变内容。
    """
    parts = PurePosixPath(canonical(relative)).parts
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, directory_flags)
    try:
        for name in parts[:-1]:
            next_descriptor = os.open(name, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        file_descriptor = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=descriptor)
        try:
            info = os.fstat(file_descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("selected skill resource must be a single-link regular file: " + relative)
            # 发行锁中的执行位与正文必须指向同一打开文件，避免另从路径检查到替换后的文件。
            if expected_mode is not None and stat.S_IMODE(info.st_mode) != expected_mode:
                raise ValueError("selected skill mode mismatch: " + relative)
            identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if expected_stat is not None and identity(info) != expected_stat:
                raise ValueError("resource identity changed before read: " + relative)
            if max_bytes is not None and info.st_size > max_bytes:
                raise ValueError("resource exceeds read budget: " + relative)
            chunks = []
            total = 0
            while chunk := os.read(file_descriptor, 1024 * 1024):
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise ValueError("resource exceeds read budget: " + relative)
                chunks.append(chunk)
            if expected_stat is not None or expected_mode is not None:
                final_info = os.fstat(file_descriptor)
                # Apple 按需引用仍验证原 inode；桌面程序另拒绝读取期间丢失锁定执行位。
                if expected_stat is not None and identity(final_info) != expected_stat:
                    raise ValueError("resource identity changed during read: " + relative)
                if expected_mode is not None and stat.S_IMODE(final_info.st_mode) != expected_mode:
                    raise ValueError("selected skill mode mismatch: " + relative)
            return b"".join(chunks)
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)


def scan(root: Path) -> set[str]:
    """完整扫描受管vendor，额外文件和特殊节点不能躲在未引用目录。"""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("selected skill root must be a physical directory")
    files = set()
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            relative = canonical(path.relative_to(root).as_posix())
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("selected skill links/special files are forbidden: " + relative)
            files.add(relative)
    return files


def _lock_dependencies(lock: dict) -> dict:
    """全量核验与分段读取共用同一个锁版本和依赖集合。"""
    if not isinstance(lock, dict) or set(lock) != {"schema_version", "dependencies"} or type(lock["schema_version"]) is not int or lock["schema_version"] != 1:
        raise ValueError("unsupported selected skill lock")
    dependencies = lock["dependencies"]
    if not isinstance(dependencies, dict) or set(dependencies) != set(SPECS):
        raise ValueError("selected dependencies must match the fixed source registry")
    return dependencies


def _dependency_files(name: str, item: dict) -> dict:
    spec = SPECS[name]
    provenance = {"playwright-cli": {"packages"}, "modern-web-guidance": {"package"}, "agent-desktop": {"release"}}
    fields = set(spec) | {"commit", "files"} | provenance.get(name, set())
    if not isinstance(item, dict) or set(item) != fields:
        raise ValueError("invalid dependency contract: " + name)
    if any(item[k] != v for k, v in spec.items()) or not isinstance(item["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", item["commit"]):
        raise ValueError("invalid fixed source or dependency closure: " + name)
    files = item["files"]
    if not isinstance(files, dict) or not {spec["license"], *spec["skills"].values()} <= files.keys():
        raise ValueError("selected dependency is missing required entries: " + name)
    return files


def _validate_file_record(name: str, relative: str, record: dict) -> None:
    spec = SPECS[name]
    canonical(relative)
    if relative != spec["license"] and not any(relative.startswith(p + "/") for p in spec["roots"]):
        raise ValueError("file is outside selected upstream closure: " + relative)
    if (not isinstance(record, dict) or set(record) not in ({"sha256", "size"}, {"sha256", "size", "mode"})
            or not isinstance(record["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
            or type(record["size"]) is not int or record["size"] < 0):
        raise ValueError("invalid selected file digest: " + relative)
    if "mode" in record and (name not in {"playwright-cli", "modern-web-guidance", "agent-desktop"}
                             or type(record["mode"]) is not int or record["mode"] not in {0o644, 0o755}):
        raise ValueError("invalid selected resource mode: " + relative)
    if name == "playwright-cli" and "mode" not in record:
        raise ValueError("Playwright file modes must be locked")


def validate_lock(lock: dict) -> dict:
    """来源与闭包形状封闭校验；更新commit仍须显式维护，不接受任意依赖或destination。"""
    for name, item in _lock_dependencies(lock).items():
        files = _dependency_files(name, item)
        for relative, record in files.items():
            _validate_file_record(name, relative, record)
        if name == "playwright-cli":
            validate_playwright_packages(item)
        elif name == "modern-web-guidance":
            validate_modern_web_package(item)
        elif name == "agent-desktop":
            _validate_desktop_release(item["commit"], item["release"])
            runtime = {f"runtime/macos/{arch}/{binary}" for arch in DESKTOP_MACOS_TARGETS for binary in DESKTOP_BINARIES}
            docs = {"LICENSE", SPECS[name]["skills"][name],
                    *(f"{DESKTOP_SKILL_ROOT}/references/{reference}" for reference in DESKTOP_REFERENCES)}
            if (files.keys() != runtime | docs or any(files[path].get("mode") != 0o755 for path in runtime)
                    or any(files[path].get("mode", 0o644) != 0o644 for path in docs)):
                raise ValueError("agent-desktop requires the original Skill, four references, license and both executable pairs")
    return lock


def _validate_desktop_release(commit: str, release: dict) -> None:
    """显式维护使用完整提交和固定发行资产，拒绝替换仓库、架构或下载名称。"""
    if not isinstance(release, dict) or set(release) != {"tag", "url", "source_archive", "assets"}:
        raise ValueError("invalid agent-desktop release provenance")
    tag, assets = release["tag"], release["assets"]
    repository = SPECS["agent-desktop"]["repository"]
    if (not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)
            or release["url"] != repository + "/releases/tag/" + tag
            or not isinstance(assets, dict) or assets.keys() != DESKTOP_MACOS_TARGETS.keys()):
        raise ValueError("agent-desktop requires one exact official release and both macOS architectures")
    expected = [(release["source_archive"], "https://codeload.github.com/vercel-labs/agent-desktop/tar.gz/" + commit)]
    for arch, target in DESKTOP_MACOS_TARGETS.items():
        expected.append((assets[arch], f"{repository}/releases/download/{tag}/agent-desktop-{tag}-{target}.tar.gz"))
    for record, url in expected:
        if (not isinstance(record, dict) or set(record) != {"url", "sha256", "compressed_bytes"}
                or record["url"] != url or not isinstance(record["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                or type(record["compressed_bytes"]) is not int or record["compressed_bytes"] <= 0):
            raise ValueError("invalid agent-desktop official archive metadata")
    if len({record["sha256"] for record, _ in expected}) != len(expected):
        raise ValueError("agent-desktop source and architecture archives must be distinct")


def validate_playwright_packages(item: dict) -> None:
    """npm闭包只准三个官方包，版本必须精确且实际依赖方向彼此闭合。"""
    packages = item["packages"]
    names = {"@playwright/cli", "playwright", "playwright-core"}
    if not isinstance(packages, list) or len(packages) != 3 or any(not isinstance(p, dict) or not isinstance(p.get("name"), str) for p in packages):
        raise ValueError("invalid Playwright package inventory")
    indexed = {p.get("name"): p for p in packages}
    if set(indexed) != names:
        raise ValueError("Playwright package names must match the closed official dependency graph")
    for name, package in indexed.items():
        fields = {"name", "version", "gitHead", "tarball", "integrity", "compressed_bytes", "tarball_sha256", "file_count", "unpacked_bytes", "engines", "dependencies", "optionalDependencies", "scripts", "license"}
        if set(package) != fields or any(not isinstance(package.get(k), str) for k in ("name", "version", "gitHead", "tarball", "integrity", "tarball_sha256", "license")):
            raise ValueError("invalid Playwright package provenance fields")
        if any(type(package.get(k)) is not int or package[k] <= 0 for k in ("compressed_bytes", "file_count", "unpacked_bytes")):
            raise ValueError("invalid Playwright package size metadata")
        if not isinstance(package.get("version"), str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", package["version"]):
            raise ValueError("Playwright versions must be exact")
        dependencies = ({"playwright": indexed["playwright"]["version"], "playwright-core": indexed["playwright-core"]["version"]} if name == "@playwright/cli" else {"playwright-core": indexed["playwright-core"]["version"]} if name == "playwright" else {})
        if package.get("dependencies") != dependencies or package.get("optionalDependencies") != {}:
            raise ValueError("Playwright package dependencies must be complete and exact")
        if not re.fullmatch(r"[0-9a-f]{40}", package.get("gitHead", "")) or not re.fullmatch(r"[0-9a-f]{64}", package.get("tarball_sha256", "")):
            raise ValueError("Playwright package provenance is missing")
        if not isinstance(package.get("integrity"), str) or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", package["integrity"]):
            raise ValueError("Playwright package integrity must use registry SHA512")
        url = "https://registry.npmjs.org/" + name + "/-/" + name.rsplit("/", 1)[-1] + "-" + package["version"] + ".tgz"
        if package["tarball"] != url or package["license"] != "Apache-2.0" or not isinstance(package["scripts"], dict):
            raise ValueError("Playwright package must preserve the official registry source and license")
        inventory = {p: r for p, r in item["files"].items() if p.startswith("runtime/node_modules/" + name + "/")}
        required = {"runtime/node_modules/" + name + "/" + p for p in ("package.json", "LICENSE")}
        if name != "@playwright/cli":
            required |= {"runtime/node_modules/" + name + "/NOTICE", "runtime/node_modules/" + name + "/ThirdPartyNotices.txt"}
        if not required <= set(inventory):
            raise ValueError("Playwright package license/provenance closure is incomplete")
        if len(inventory) != package.get("file_count") or sum(r["size"] for r in inventory.values()) != package.get("unpacked_bytes"):
            raise ValueError("Playwright package counts or bytes mismatch")
    if indexed["@playwright/cli"]["gitHead"] != item["commit"]:
        raise ValueError("Playwright CLI commit must match its published package gitHead")


def validate_modern_web_package(item: dict) -> None:
    """官方单包已捆绑查询模型，无外部运行依赖；许可、完整文件数和字节数同时锁定。"""
    package = item["package"]
    fields = {"name", "version", "gitHead", "tarball", "integrity", "compressed_bytes", "tarball_sha256", "file_count", "unpacked_bytes"}
    if not isinstance(package, dict) or set(package) != fields:
        raise ValueError("invalid modern Web package provenance")
    if (any(not isinstance(package[k], str) for k in ("name", "version", "gitHead", "tarball", "integrity", "tarball_sha256"))
            or not re.fullmatch(r"[0-9a-f]{40}", package["gitHead"])):
        raise ValueError("invalid modern Web package identity fields")
    if (package["name"] != "modern-web-guidance" or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", package.get("version", ""))
            or package["gitHead"] != item["commit"]
            or not re.fullmatch(r"[0-9a-f]{64}", package.get("tarball_sha256", ""))
            or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", package.get("integrity", ""))):
        raise ValueError("modern Web requires exact official package identity and integrity")
    if package["tarball"] != "https://registry.npmjs.org/modern-web-guidance/-/modern-web-guidance-" + package["version"] + ".tgz":
        raise ValueError("modern Web package must use its official registry tarball")
    if any(type(package[k]) is not int or package[k] <= 0 for k in ("compressed_bytes", "file_count", "unpacked_bytes")):
        raise ValueError("invalid modern Web package sizes")
    required = {"runtime/" + p for p in ("LICENSE", "README.md", "THIRD_PARTY_NOTICES", "package.json")}
    required |= {"runtime/skills/modern-web-guidance/" + p for p in (
        "SKILL.md", "modern-web.mjs", "search.mjs", "skill-version.txt", "gen/guides.json",
        "gen/guide-chunks.json.gz", "gen/guide-chunks.i8", "gen/guide-chunks.scale.f32",
        "gen/query-words.json", "gen/query-words.i8", "gen/query-words.scale.f32")}
    if (not isinstance(item.get("files"), dict) or not required <= set(item["files"]) or len(item["files"]) != package["file_count"]
            or sum(r["size"] for r in item["files"].values()) != package["unpacked_bytes"]
            or any("mode" not in r for r in item["files"].values())):
        raise ValueError("modern Web complete package/license/model closure is missing")


def load_modern_web_archive(manifest: dict, archive: Path) -> tuple[dict, dict[str, bytes]]:
    """只读取显式审阅的官方发布tar；不执行npm、构建器、安装器或归档内脚本。"""
    try:
        return _load_modern_web_archive(manifest, archive)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("invalid modern Web archive manifest") from exc


def _load_modern_web_archive(manifest: dict, archive: Path) -> tuple[dict, dict[str, bytes]]:
    """与既有Playwright入口一致，将不可信manifest结构错误统一为明确拒绝。"""
    if (not isinstance(manifest, dict) or set(manifest) != {"package", "files"}
            or not isinstance(manifest["package"], dict)):
        raise ValueError("modern Web manifest requires package and complete files")
    item = {**SPECS["modern-web-guidance"], "commit": manifest.get("package", {}).get("gitHead"), **manifest}
    # 完整单依赖校验在读取任何成员前执行；它不会信任归档自己的包版本声明。
    validate_modern_web_package(item)
    raw = read_regular(archive.parent, archive.name, max_bytes=30 * 1024 * 1024)
    package = item["package"]
    if (len(raw) != package["compressed_bytes"] or hashlib.sha256(raw).hexdigest() != package["tarball_sha256"]
            or "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii") != package["integrity"]):
        raise ValueError("modern Web archive integrity mismatch")
    files, records, expanded = {}, {}, 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as stream:
        for entry in stream:
            name = canonical(entry.name)
            if not name.startswith("package/") or not entry.isfile() or entry.mode not in {0o644, 0o755}:
                raise ValueError("modern Web archive requires canonical regular files and safe modes")
            relative = "runtime/" + name.removeprefix("package/")
            if relative in files:
                raise ValueError("duplicate modern Web archive entry")
            expanded += entry.size
            if expanded > 60 * 1024 * 1024:
                raise ValueError("modern Web expanded package exceeds review budget")
            body = stream.extractfile(entry).read()
            files[relative] = body
            records[relative] = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body), "mode": entry.mode}
    if records != item["files"]:
        raise ValueError("modern Web archive complete inventory mismatch")
    return item, files


def load_playwright_archives(manifest: dict, archives: list[Path]) -> tuple[dict, dict[str, bytes]]:
    """将不可信manifest形状错误统一转换为可诊断拒绝，不漏出解析器异常。"""
    try:
        return _load_playwright_archives(manifest, archives)
    except (KeyError, TypeError, StopIteration) as exc:
        raise ValueError("invalid Playwright archive manifest") from exc


def _load_playwright_archives(manifest: dict, archives: list[Path]) -> tuple[dict, dict[str, bytes]]:
    """只消费显式本地发布快照，先核registry SHA512/摘要再检查完整文件闭包。

    manifest与archive都需要来源审阅；这里的完整性匹配不是签名认证。所有成员以
    手工普通文件写入候选，绝不执行npm生命周期、tar提取器或包内脚本。
    """
    if not isinstance(manifest, dict) or len(archives) != 3 or not isinstance(manifest.get("packages"), list) or len(manifest["packages"]) != 3:
        raise ValueError("exactly three reviewed Playwright archives are required")
    raw_by_digest = {}
    for archive in archives:
        raw = read_regular(archive.parent, archive.name)
        if len(raw) > 200 * 1024 * 1024:
            raise ValueError("Playwright archive exceeds review budget")
        digest = hashlib.sha256(raw).hexdigest()
        if digest in raw_by_digest:
            raise ValueError("duplicate Playwright archive")
        raw_by_digest[digest] = raw
    files, records = {}, {}
    for package in manifest["packages"]:
        if not isinstance(package, dict) or package.get("name") not in {"@playwright/cli", "playwright", "playwright-core"}:
            raise ValueError("unexpected Playwright package")
        raw = raw_by_digest.pop(package.get("tarball_sha256"), None)
        if raw is None or len(raw) != package.get("compressed_bytes") or "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii") != package.get("integrity"):
            raise ValueError("Playwright archive integrity mismatch")
        expanded = 0
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as stream:
            for entry in stream:
                name = canonical(entry.name)
                if not name.startswith("package/") or not entry.isfile() or entry.mode not in {0o644, 0o755}:
                    raise ValueError("Playwright archives require canonical regular files and safe modes")
                relative = "runtime/node_modules/" + package["name"] + "/" + name.removeprefix("package/")
                if relative in files:
                    raise ValueError("duplicate Playwright archive entry")
                expanded += entry.size
                if expanded > 500 * 1024 * 1024:
                    raise ValueError("expanded Playwright archive exceeds review budget")
                body = stream.extractfile(entry).read()
                files[relative] = body
                records[relative] = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body), "mode": entry.mode}
    expected = {"runtime/" + canonical(r["path"]): {"sha256": r["sha256"], "size": r["bytes"]} for r in manifest["files"]}
    if len(expected) != len(manifest["files"]) or expected != {p: {"sha256": r["sha256"], "size": r["size"]} for p, r in records.items()}:
        raise ValueError("Playwright archive file inventory mismatch")
    commit = next(p["gitHead"] for p in manifest["packages"] if p["name"] == "@playwright/cli")
    item = {**SPECS["playwright-cli"], "commit": commit, "packages": manifest["packages"], "files": records}
    validate_playwright_packages(item)
    return item, files


def load_git_archive(dependency: str, ref: str, archive: Path, *, archive_record: dict | None = None) -> tuple[dict, dict[str, bytes], str, int]:
    """Git子树选择与npm完整图各有格式责任，共享规范路径/普通文件/锁校验owner。

    整个归档均拒绝危险或重复路径；闭包外链接不解析/不提取，避免把上游仓库的
    AGENTS别名当依赖。选中闭包的链接和特殊节点仍明确失败。
    """
    archive_prefixes = {"grill-me": "skills-", "taste": "taste-skill-", "agent-desktop": "agent-desktop-"}
    if dependency not in archive_prefixes:
        raise ValueError("Git archive supports only the selected Git dependencies")
    body = read_regular(archive.parent, archive.name, max_bytes=200 * 1024 * 1024)
    digest = hashlib.sha256(body).hexdigest()
    if archive_record is not None and (len(body) != archive_record["compressed_bytes"] or digest != archive_record["sha256"]):
        raise ValueError("selected Git source archive integrity mismatch")
    spec, files, seen = SPECS[dependency], {}, set()
    archive_root = archive_prefixes[dependency] + ref
    # agent-desktop 的运行文件只能来自发行包；同名 Git 子树不能替换官方二进制。
    selected_roots = [DESKTOP_SKILL_ROOT] if dependency == "agent-desktop" else spec["roots"]
    expanded, ignored = 0, 0
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as stream:
        for entry in stream:
            name = canonical(entry.name.rstrip("/") if entry.isdir() else entry.name)
            if name in seen:
                raise ValueError("duplicate archive path: " + name)
            seen.add(name)
            if name.split("/")[0] != archive_root:
                raise ValueError("archive root does not match requested ref label")
            if entry.isdir():
                continue
            relative = name.removeprefix(archive_root + "/")
            included = relative == spec["license"] or any(relative.startswith(root + "/") for root in selected_roots)
            if not entry.isfile():
                if included:
                    raise ValueError("selected archive links and special entries are forbidden")
                ignored += 1
                continue
            expanded += entry.size
            if expanded > 500 * 1024 * 1024:
                raise ValueError("expanded archive exceeds review budget")
            if included:
                files[relative] = stream.extractfile(entry).read()
    inventory = {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(files.items())}
    return {**spec, "commit": ref, "files": inventory}, files, digest, ignored


def load_agent_desktop_archives(ref: str, release: dict, archives: list[Path]) -> tuple[dict, dict[str, bytes], int]:
    """从按源码、arm64、x86_64 排列的三个审阅归档读取原字节，不解压到磁盘或执行程序。"""
    if len(archives) != 1 + len(DESKTOP_MACOS_TARGETS):
        raise ValueError("agent-desktop update requires source, arm64 and x86_64 archives in that order")
    _validate_desktop_release(ref, release)
    item, files, _, ignored = load_git_archive("agent-desktop", ref, archives[0], archive_record=release["source_archive"])
    records = item["files"]
    for arch, archive in zip(DESKTOP_MACOS_TARGETS, archives[1:], strict=True):
        asset = release["assets"][arch]
        raw = read_regular(archive.parent, archive.name, max_bytes=30 * 1024 * 1024)
        if len(raw) != asset["compressed_bytes"] or hashlib.sha256(raw).hexdigest() != asset["sha256"]:
            raise ValueError("agent-desktop release archive integrity mismatch: " + arch)
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as stream:
            for entry in stream:
                # 两个同目录的普通可执行文件构成完整运行闭包，不能引入链接或安装脚本。
                if (entry.name not in DESKTOP_BINARIES or entry.name in seen or not entry.isfile()
                        or entry.mode != 0o755 or not 0 < entry.size <= 30 * 1024 * 1024):
                    raise ValueError("unexpected agent-desktop archive entry: " + entry.name)
                seen.add(entry.name)
                relative = f"runtime/macos/{arch}/{entry.name}"
                body = stream.extractfile(entry).read()
                files[relative] = body
                records[relative] = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body), "mode": entry.mode}
        if seen != set(DESKTOP_BINARIES):
            raise ValueError("agent-desktop archive is missing the CLI or helper: " + arch)
    return {**item, "release": release}, files, ignored


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    """清单中的重复键明确失败，不能靠JSON后项覆盖改变来源或文件权限判断。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate selected skill lock key: " + key)
        result[key] = value
    return result


def snapshot(root: Path = ROOT) -> tuple[dict, dict[str, bytes]]:
    """在同一批已验证字节上构建或读取，避免校验成功后再重新打开不受验证内容。"""
    lock = validate_lock(json.loads(read_regular(root, LOCK), object_pairs_hook=unique_object))
    expected = {name + "/" + relative for name, item in lock["dependencies"].items() for relative in item["files"]}
    if scan(root / VENDOR) != expected:
        raise ValueError("selected skill inventory mismatch (missing or extra files)")
    result = {}
    for name, item in lock["dependencies"].items():
        for relative, record in item["files"].items():
            path = VENDOR + "/" + name + "/" + relative
            # 锁已限制 agent-desktop 的 0755 只属于两套 CLI/helper；其余依赖仍按原规则读取。
            expected_mode = 0o755 if name == "agent-desktop" and record.get("mode") == 0o755 else None
            body = read_regular(root, path, expected_mode=expected_mode)
            if len(body) != record["size"] or hashlib.sha256(body).hexdigest() != record["sha256"]:
                raise ValueError("selected skill digest mismatch: " + path)
            result[path] = body
    for package in lock["dependencies"]["playwright-cli"]["packages"]:
        relative = VENDOR + "/playwright-cli/runtime/node_modules/" + package["name"] + "/package.json"
        actual = json.loads(result[relative], object_pairs_hook=unique_object)
        if (actual.get("name") != package["name"] or actual.get("version") != package["version"]
                or actual.get("dependencies", {}) != package["dependencies"] or actual.get("optionalDependencies", {}) != {}
                or actual.get("engines", {}) != package["engines"]):
            raise ValueError("Playwright package metadata disagrees with locked dependency graph")
    package = lock["dependencies"]["modern-web-guidance"]["package"]
    metadata = json.loads(result[VENDOR + "/modern-web-guidance/runtime/package.json"], object_pairs_hook=unique_object)
    if (not isinstance(metadata, dict) or metadata.get("name") != "modern-web-guidance" or metadata.get("version") != package["version"]
            or not isinstance(metadata.get("engines"), dict) or metadata["engines"].get("node") != ">=22.0.0"
            or metadata.get("dependencies", {}) or metadata.get("optionalDependencies", {})):
        raise ValueError("modern Web package metadata disagrees with the fixed local closure")
    return lock, result


def skill_path(name: str) -> str:
    # 别名由统一角色映射读取，canonical原name始终保留，未知全局Skill不作回退。
    if __package__:
        from .role_skills import SELECTED_SKILL_ALIASES
    else:
        from role_skills import SELECTED_SKILL_ALIASES
    name = SELECTED_SKILL_ALIASES.get(name, name)
    for dependency, spec in SPECS.items():
        if name in spec["skills"]:
            return VENDOR + "/" + dependency + "/" + spec["skills"][name]
    raise ValueError("unknown selected skill")


def read_selected_chunk(root: Path, name: str, offset: int, length: int, *,
                        verify_source: Callable[[str, str], None] | None = None) -> dict:
    """读取指定上游正文的一页；锁、正文各读取一次，包内调用同时校验发行清单摘要。

    条目归属固定在 SPECS，每页重新绑定原文摘要。调用者只有在各页摘要相同、
    offset 与上一页 next_offset 相接时才能拼接，显式 check 仍检查完整依赖闭包。
    """
    path = skill_path(name)
    dependency, relative = path.removeprefix(VENDOR + "/").split("/", 1)
    raw_lock = read_regular(root, LOCK, max_bytes=16 * 1024 * 1024)
    if verify_source is not None:
        verify_source(LOCK, hashlib.sha256(raw_lock).hexdigest())
    item = _lock_dependencies(json.loads(raw_lock, object_pairs_hook=unique_object))[dependency]
    record = _dependency_files(dependency, item)[relative]
    _validate_file_record(dependency, relative, record)
    body = read_regular(root, path, max_bytes=record["size"])
    digest = hashlib.sha256(body).hexdigest()
    if len(body) != record["size"] or digest != record["sha256"]:
        raise ValueError("selected skill digest mismatch: " + path)
    if verify_source is not None:
        verify_source(path, digest)
    return read_bytes_chunk(body, path, offset, length, digest=digest)


def read_bytes_chunk(body: bytes, path: str, offset: int, length: int, *, digest: str | None = None) -> dict:
    """已绑定来源的原文字节共用同一个连续UTF-8读取合同。"""
    body.decode("utf-8")
    if offset < 0 or offset > len(body) or length < 4 or length > 16000:
        raise ValueError("offset out of range or length must be 4..16000")
    try:
        body[:offset].decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("offset must be a UTF-8 character boundary") from None
    end = min(offset + length, len(body))
    content = ""
    while end > offset:
        try:
            content = body[offset:end].decode("utf-8")
            break
        except UnicodeDecodeError:
            end -= 1
    return {"path": path, "sha256": digest if digest is not None else hashlib.sha256(body).hexdigest(), "total_bytes": len(body), "offset": offset,
            "next_offset": end, "content": content, "eof": end == len(body)}


def diagnose() -> dict:
    """环境探测只执行已有Node的版本查询，不安装浏览器或执行任何上游脚本。"""
    node = shutil.which("node")
    version = None
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version or "")
    browser = os.environ.get("CHROME_PATH")
    if not browser or not Path(browser).is_file():
        browser = next((p for p in [shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")] + ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"] if p and Path(p).is_file()), None)
    return {"node": {"path": node, "version": version, "ready": bool(match and int(match[1]) >= 22)}, "browser": {"path": browser, "ready": bool(browser)}, "ffmpeg_optional": shutil.which("ffmpeg"), "upstream_scripts_executed": False, "host_invocation_verified": False}


def main(argv: list[str] | None = None, *, root: Path = ROOT,
         verify_source: Callable[[str, str], None] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("diagnose")
    read = commands.add_parser("read")
    read.add_argument("skill", help="public alias or canonical upstream skill name")
    read.add_argument("--offset", type=int, default=0)
    read.add_argument("--length", type=int, default=12000)
    args = parser.parse_args(argv)
    try:
        if args.command == "read":
            result = read_selected_chunk(root, args.skill, args.offset, args.length, verify_source=verify_source)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        lock, _ = snapshot(root)
        result = {"integrity": "verified", "dependencies": {name: {"commit": item["commit"], "file_count": len(item["files"])} for name, item in lock["dependencies"].items()}, "upstream_scripts_executed": False}
        if args.command == "diagnose":
            if __package__:
                from .playwright_runtime import doctor
            else:
                from playwright_runtime import doctor
            result["environment"] = diagnose()
            result["playwright"] = doctor(root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
