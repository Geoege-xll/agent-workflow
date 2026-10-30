#!/usr/bin/env python3
"""Build an offline release archive and its Homebrew formula; never publish or install."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
from pathlib import Path
import re
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILES = (
    "workflow.sh", "install.sh", "setup_all.sh", "setup_claude.sh",
    "setup_codex.sh", "setup_antigravity.sh", "project.yaml", "README.md",
)
RELEASE_DIRECTORIES = ("manager", "lib", "product", "roles", "platforms", "scripts", "templates")
OPTIONAL_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
EXCLUDED = {".git", ".sync-backups", "__pycache__", ".DS_Store", ".pytest_cache"}


def payload(source: Path) -> list[Path]:
    paths = []
    for name in (*RELEASE_FILES, *RELEASE_DIRECTORIES, *OPTIONAL_FILES):
        entry = source / name
        if name in OPTIONAL_FILES and not entry.exists() and not entry.is_symlink():
            continue
        if entry.is_symlink():
            raise ValueError(f"Release payload cannot contain symlinks: {entry}")
        expected = entry.is_dir() if name in RELEASE_DIRECTORIES else entry.is_file()
        if not expected:
            raise ValueError(f"Required release entry is missing or has the wrong type: {entry}")
        children = (entry, *sorted(entry.rglob("*"))) if entry.is_dir() else (entry,)
        for path in children:
            relative = path.relative_to(source)
            if EXCLUDED.intersection(relative.parts) or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError(f"Release payload must contain only regular files/directories: {path}")
            paths.append(path)
    return sorted(paths)


def archive_bytes(source: Path, version: str) -> bytes:
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
    return stream.getvalue()


def build(source: Path, version: str, output: Path) -> tuple[Path, Path, Path]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version, re.ASCII):
        raise ValueError("Version must be X.Y.Z without a leading v (for example 0.1.0)")
    source = source.resolve(strict=True)
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
    parser.add_argument("version", help="release version, for example 0.1.0")
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
