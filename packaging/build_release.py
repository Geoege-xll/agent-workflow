#!/usr/bin/env python3
"""Build an offline release archive and its Homebrew formula; never publish or install."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
# 仅导入本构建器所属的受信源码解析器；待打包 source 只作为数据读取。
sys.path.insert(0, str(ROOT))
from manager.release import source_version
RELEASE_FILES = (
    "workflow.sh",
    # 原生 Windows 与 Bash 共用同一 manager 实现；发行包必须同时携带薄入口
    # 及已锁定的 TUI 依赖清单。纳入载荷只证明文件完整，不代替真机运行验收。
    "workflow.py", "workflow.ps1", "workflow.cmd", "requirements-windows.txt",
    "install.sh", "setup_all.sh", "setup_claude.sh",
    "setup_codex.sh", "setup_antigravity.sh", "project.yaml", "README.md",
    # 用户离线入口只需要这三份手册；历史计划、原型及私有文档不进入载荷。
    "docs/usage.md", "docs/development.md", "docs/homebrew.md",
)
RELEASE_DIRECTORIES = ("manager", "lib", "product", "roles", "platforms", "scripts", "templates")
OPTIONAL_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
EXCLUDED = {".git", ".sync-backups", "__pycache__", ".DS_Store", ".pytest_cache"}
RELEASE_METADATA = "manager/release.json"


def payload(source: Path) -> list[Path]:
    paths = []
    for name in (*RELEASE_FILES, *RELEASE_DIRECTORIES, *OPTIONAL_FILES):
        entry = source / name
        if name in OPTIONAL_FILES and not entry.exists() and not entry.is_symlink():
            continue
        # 嵌套白名单文件也必须核对父目录：否则 docs 被换成软链时，
        # 看似普通的手册会从源包外读入，绕过载荷的受信目录边界。
        if entry.is_symlink() or any((source / parent).is_symlink() for parent in Path(name).parents):
            raise ValueError(f"Release payload cannot contain symlinks: {entry}")
        expected = entry.is_dir() if name in RELEASE_DIRECTORIES else entry.is_file()
        if not expected:
            raise ValueError(f"Required release entry is missing or has the wrong type: {entry}")
        children = (entry, *sorted(entry.rglob("*"))) if entry.is_dir() else (entry,)
        for path in children:
            relative = path.relative_to(source)
            # 元数据只能在本次归档生成，拒绝源码遗留标记，防止旧版本被意外带进新发行包。
            if relative.as_posix() == RELEASE_METADATA:
                raise ValueError(f"Generated release metadata must not exist in source: {path}")
            if EXCLUDED.intersection(relative.parts) or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError(f"Release payload must contain only regular files/directories: {path}")
            paths.append(path)
    return sorted(paths)


def archive_bytes(source: Path, version: str) -> bytes:
    if source_version(source) != version:
        raise ValueError("Requested release version must match product/VERSION")
    stream = io.BytesIO()
    prefix = f"agent-workflow-{version}"
    # Stable ordering, gzip headers, ownership, modes and timestamps make rebuilds identical.
    with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            root = tarfile.TarInfo(prefix)
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            archive.addfile(root)
            for path in payload(source):
                info = tarfile.TarInfo(f"{prefix}/{path.relative_to(source).as_posix()}")
                if path.is_dir():
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    archive.addfile(info)
                else:
                    data = path.read_bytes()
                    info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            # 仅记录调用者明确构建的版本，不写入时间、绝对源码路径或未核实的发布状态。
            # 固定字节与权限保留可重复构建；manager 内的普通文件会随 Formula 安装进入 libexec。
            metadata = json.dumps({"schema_version": 1, "version": version}, sort_keys=True).encode("utf-8") + b"\n"
            info = tarfile.TarInfo(f"{prefix}/{RELEASE_METADATA}")
            info.mode = 0o644
            info.size = len(metadata)
            archive.addfile(info, io.BytesIO(metadata))
    return stream.getvalue()


def build(source: Path, version: str, output: Path) -> tuple[Path, Path, Path]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version, re.ASCII):
        raise ValueError("Version must be X.Y.Z without a leading v (for example 2.0.0)")
    source = source.resolve(strict=True)
    if source_version(source) != version:
        raise ValueError("Requested release version must match product/VERSION")
    output = output.expanduser().resolve()
    if output == source or any(
        output.is_relative_to(source / name)
        for name in (*RELEASE_FILES, *RELEASE_DIRECTORIES, *OPTIONAL_FILES, "packaging", "tests", "docs")
    ):
        raise ValueError("Output must not be inside the release payload or source/tooling directories")
    archive = output / f"agent-workflow-{version}.tar.gz"
    checksum = output / f"{archive.name}.sha256"
    formula = output / "Formula" / "awf-cli.rb"
    if formula.parent.is_symlink():
        raise ValueError(f"Formula output directory cannot be a symlink: {formula.parent}")
    for path in (archive, checksum, formula):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Existing output preserved; choose a new --output-dir: {path}")

    data = archive_bytes(source, version)
    digest = hashlib.sha256(data).hexdigest()
    template = (source / "packaging/homebrew/awf-cli.rb.in").read_text(encoding="utf-8")
    rendered = template.replace("@VERSION@", version).replace("@SHA256@", digest)
    if re.search(r"@[A-Z_]+@", rendered):
        raise ValueError("Homebrew formula contains an unresolved template field")
    output.mkdir(parents=True, exist_ok=True)
    formula.parent.mkdir(exist_ok=True)
    for path, content in (
        (archive, data),
        (checksum, f"{digest}  {archive.name}\n".encode()),
        (formula, rendered.encode("utf-8")),
    ):
        with path.open("xb") as stream:
            stream.write(content)
    return archive, checksum, formula


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="release version, for example 2.0.0")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    try:
        for path in build(ROOT, args.version, args.output_dir):
            print(path)
        return 0
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
