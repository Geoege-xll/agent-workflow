#!/usr/bin/env python3
"""本机选定Xcode官方SwiftUI资料的只读发现与绑定读取，不启动或修改Xcode。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.skills.selected_skills import canonical, read_bytes_chunk, read_regular

SKILLS = ("swiftui-specialist", "swiftui-whats-new-27")
RESOURCE_DIRECTORY = "PlugIns/IDEIntelligenceChat.framework/Versions/A/Resources"
MAX_RESOURCE_BYTES = 2 * 1024 * 1024


class SourceError(ValueError):
    """状态属于读取边界；缺资料、未知布局与损坏不能伪装为可用。"""
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def physical(path: Path, *, directory: bool = False) -> os.stat_result:
    """在规范绝对路径逐级拒绝软链，最终节点拒绝硬链、设备、FIFO与过大资源。"""
    if not path.is_absolute() or ".." in path.parts or path != Path(os.path.normpath(path)):
        raise SourceError("unsupported", "Xcode source must be a canonical absolute physical path")
    for parent in (*reversed(path.parents), path):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise SourceError("damaged", "Xcode source links are forbidden: " + str(parent))
        if parent != path and not stat.S_ISDIR(info.st_mode):
            raise SourceError("damaged", "Xcode source ancestor is not a directory")
    if directory:
        valid = stat.S_ISDIR(info.st_mode)
    else:
        valid = stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_RESOURCE_BYTES
    if not valid:
        raise SourceError("damaged", "Xcode resource must be a bounded single-link regular file: " + str(path))
    return info


def file_identity(path: Path) -> dict:
    """check只检查引用元数据，不预读无关正文；ctime防止仅恢复mtime后混读旧来源。"""
    info = physical(path)
    return {"path": str(path), "size": info.st_size, "device": info.st_dev, "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def read_bound(path: Path, identity: dict) -> bytes:
    """从根描述符逐级不跟随链接，并将打开inode与check的身份原子核对。

    不能仅在lstat后用完整绝对路径open：祖先目录在两次操作间可能被替换为软链。
    复用共用reader从/向下打开所有目录，版本文件、模板和按需引用遵循同一边界。
    """
    expected = tuple(identity[key] for key in ("device", "inode", "size", "mtime_ns", "ctime_ns"))
    return read_regular(Path("/"), path.relative_to("/").as_posix(), max_bytes=MAX_RESOURCE_BYTES,
                        expected_stat=expected)


def source_snapshot(developer_dir: Path | None = None) -> tuple[dict, dict[str, dict[str, str]], dict[str, bytes]]:
    """仅支持实际观察的Xcode27模板布局；此本机实现不是Apple稳定导出API。

    不调用agent skills export或xcodebuild。选择来自显式目录或xcode-select，
    plist和两个模板才是本次必读正文；引用按需读取，闭包缺失立即拒绝。
    """
    if developer_dir is None:
        if sys.platform != "darwin":
            raise SourceError("unsupported", "Apple guidance requires a local selected Xcode on macOS")
        selection = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True, text=True,
                                   timeout=5, check=False)
        if selection.returncode:
            raise SourceError("missing", "xcode-select has no usable developer directory")
        developer_dir = Path(selection.stdout.strip())
    physical(developer_dir, directory=True)
    if developer_dir.name != "Developer" or developer_dir.parent.name != "Contents" or developer_dir.parent.parent.suffix != ".app":
        raise SourceError("unsupported", "expected an Xcode.app/Contents/Developer directory")
    contents = developer_dir.parent
    version_path = contents / "version.plist"
    raw_version = read_bound(version_path, file_identity(version_path))
    try:
        version = plistlib.loads(raw_version)
    except (plistlib.InvalidFileException, ValueError) as exc:
        raise SourceError("damaged", "invalid local Xcode version.plist") from exc
    if not isinstance(version, dict):
        raise SourceError("damaged", "local Xcode version.plist must be a dictionary")
    number, build = version.get("CFBundleShortVersionString"), version.get("ProductBuildVersion")
    if not isinstance(number, str) or not re.fullmatch(r"27\.[0-9]+(?:\.[0-9]+)?", number) or not isinstance(build, str) or not build:
        raise SourceError("unsupported", "local Xcode version is outside the observed 27.x resource layout")
    resources = contents / RESOURCE_DIRECTORY
    physical(resources, directory=True)
    manifests, templates, identities = {}, {}, {}
    for skill in SKILLS:
        filename = skill + ".idechatprompttemplate"
        path = resources / filename
        template_identity = file_identity(path)
        body = read_bound(path, template_identity)
        text = body.decode("utf-8")
        if not text.startswith("---\nname: " + skill + "\n"):
            raise SourceError("damaged", "Xcode template native name or Markdown format changed: " + skill)
        names = sorted(set(re.findall(r"references/([a-z0-9-]+\.md)", text)))
        if not names:
            raise SourceError("damaged", "Xcode template has no supported reference closure: " + skill)
        mapping = {"SKILL.md": filename}
        records = {"SKILL.md": {**template_identity, "sha256": hashlib.sha256(body).hexdigest()}}
        for name in names:
            native = skill + "-ref-" + name + ".packaged"
            mapping["references/" + name] = native
            records["references/" + name] = file_identity(resources / native)
        manifests[skill], templates[skill], identities[skill] = mapping, body, records
    source = {"source_kind": "local_xcode_original_markdown", "developer_root": str(developer_dir),
              "resource_root": str(resources), "xcode_version": number, "xcode_build": build,
              "version_sha256": hashlib.sha256(raw_version).hexdigest(), "skills": identities}
    source_sha = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"status": "available", **source, "source_sha256": source_sha,
            "xcode_launched": False, "export_performed": False, "host_adoption_verified": False}, manifests, templates


def read(developer_dir: Path | None, skill: str, resource: str, expected: str, offset: int, length: int) -> dict:
    """每段先绑定相同来源，再读取唯一闭包资源；读取期间变化也拒绝，不能拼接不同版本。"""
    if skill not in SKILLS or not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise ValueError("fixed native skill and --expect-source-sha256 are required")
    canonical(resource)
    source, manifests, templates = source_snapshot(developer_dir)
    if source["source_sha256"] != expected:
        raise SourceError("changed", "Xcode source identity changed; check and restart the complete read")
    if resource not in manifests[skill]:
        raise ValueError("resource is outside the selected native skill reference closure")
    body = templates[skill] if resource == "SKILL.md" else read_bound(
        Path(source["resource_root"]) / manifests[skill][resource], source["skills"][skill][resource])
    latest, _, _ = source_snapshot(Path(source["developer_root"]))
    if latest["source_sha256"] != expected:
        raise SourceError("changed", "Xcode source changed during read; discard partial content")
    return {**read_bytes_chunk(body, resource, offset, length), "skill": skill,
            "source_sha256": expected, "source_kind": source["source_kind"],
            "developer_root": source["developer_root"], "xcode_version": source["xcode_version"],
            "xcode_build": source["xcode_build"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    reader = commands.add_parser("read")
    for command in (check, reader):
        command.add_argument("--developer-dir", type=Path)
    reader.add_argument("--skill", choices=SKILLS, required=True)
    reader.add_argument("--resource", required=True)
    reader.add_argument("--expect-source-sha256", required=True)
    reader.add_argument("--offset", type=int, default=0)
    reader.add_argument("--length", type=int, default=12000)
    args = parser.parse_args(argv)
    try:
        result = source_snapshot(args.developer_dir)[0] if args.command == "check" else read(
            args.developer_dir, args.skill, args.resource, args.expect_source_sha256, args.offset, args.length)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        status = exc.status if isinstance(exc, SourceError) else "missing" if isinstance(exc, FileNotFoundError) else "damaged"
        print(json.dumps({"status": status, "diagnostic": str(exc), "xcode_launched": False,
                          "export_performed": False}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
