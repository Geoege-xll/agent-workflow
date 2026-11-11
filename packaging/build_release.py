#!/usr/bin/env python3
"""构建离线归档、Homebrew Formula 与 Windows 固定交付资产；不发布或安装。"""

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
import zipfile


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
RELEASE_BASE_URL = "https://github.com/Geoege-xll/agent-workflow/releases/download"
# 安装器只携带已确认的同源 SDK；不得把整个 manager/lib 业务树装入可执行自举包。
# 新依赖应在此处显式评审，并由真实 pyz 消费验证证明，而非靠源码目录补齐导入。
WINDOWS_INSTALLER_FILES = (
    "lib/__init__.py", "lib/windows_fs.py", "lib/platform_fs.py", "lib/runtime_store.py",
    "lib/central/__init__.py", "lib/central/runtime_project.py",
    "lib/install/__init__.py", "lib/install/install_process.py", "lib/install/windows_process.py",
    "lib/install/windows_installer.py", "manager/__init__.py", "manager/state_files.py",
)
WINDOWS_TEMPLATE = "packaging/windows/install.ps1.in"
WINDOWS_LOADER = "packaging/windows/pyz_loader.py.in"


def release_identity(version: str, release_tag: str | None = None) -> str:
    """产品版本与发布标签分开校验；候选标签不能修改 product/VERSION 的语义。"""
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version, re.ASCII):
        raise ValueError("Version must be X.Y.Z without a leading v (for example 2.0.0)")
    tag = release_tag if release_tag is not None else f"v{version}"
    if not re.fullmatch(rf"v{re.escape(version)}(?:-rc\.(?:0|[1-9]\d*))?", tag, re.ASCII):
        raise ValueError("Release tag must match the product version: vX.Y.Z or vX.Y.Z-rc.N")
    return tag


def release_paths(output: Path, version: str, release_tag: str | None = None) -> tuple[Path, ...]:
    """统一六项资产名称与顺序；构建和 CLI 报告都消费此清单，避免新增资产被静默遗漏。

    只组合路径、不写文件；前面三项继续对应 build 的既有三元组返回合同。
    输出目录的解析和写入安全边界仍由 build 统一负责。
    """
    tag = release_identity(version, release_tag)
    archive = output / f"agent-workflow-{version}.tar.gz"
    return (
        archive, output / f"{archive.name}.sha256", output / "Formula" / "awf-cli.rb",
        output / f"agent-workflow-windows-{tag}.pyz",
        output / f"install-agent-workflow-{tag}.ps1",
        output / f"agent-workflow-{tag}-manifest.json",
    )


def source_file(source: Path, relative: str) -> bytes:
    """读取白名单普通文件，拒绝源包外的父目录软链和缺失模块。"""
    path = source / relative
    if path.is_symlink() or any((source / parent).is_symlink() for parent in Path(relative).parents):
        raise ValueError(f"Release input cannot contain symlinks: {path}")
    if not path.is_file():
        raise ValueError(f"Required release input is missing or has the wrong type: {path}")
    return path.read_bytes()


def installer_bytes(archive_data: bytes, version: str, archive_sha256: str) -> bytes:
    """固定 zip 顺序、时间、权限和压缩方法，且让 pyz 绑定本次 tar 身份。"""
    entry = f'''"""固定发行资产入口；独立安装引擎只接收显式 argv。"""
import argparse
import sys
from lib.install.windows_installer import main

# 版本与归档摘要属于交付身份；manager/release.json 继续只描述原有产品版本。
if sys.argv[1:] not in (["--help"], ["-h"]):
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--version", required=True)
    identity, _ = parser.parse_known_args()
    if identity.version != {version!r} or identity.archive_sha256 != {archive_sha256!r}:
        parser.error("固定发行版本或归档摘要不匹配")
raise SystemExit(main(sys.argv[1:]))
'''.encode("utf-8")
    # SDK 直接取自刚生成且已绑定摘要的 tar 内存快照，避免源码在两次读取之间变化，
    # 造成“同源”pyz 与将实际部署的 tar 含有不同版本安装器/文件系统边界。
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as payload_archive:
        for name in WINDOWS_INSTALLER_FILES:
            try:
                member = payload_archive.getmember(f"agent-workflow-{version}/{name}")
            except KeyError as exc:
                raise ValueError(f"Required release input is missing: {name}") from exc
            if not member.isfile() or member.size > 4 * 1024 * 1024:
                raise ValueError(f"Installer module must be a bounded regular file: {name}")
            contents[name] = payload_archive.extractfile(member).read()
    contents["__main__.py"] = entry
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    data = stream.getvalue()
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Windows installer exceeds its fixed memory budget")
    return data


def render_windows_installer(source: Path, fields: dict[str, str], *, test_ca_path: str | None = None) -> bytes:
    """模板只接收构建器已校验的固定身份；不提供任意下载源或执行代码参数。"""
    loader = source_file(source, WINDOWS_LOADER).decode("ascii")
    loader = loader.replace("@PYZ_SHA256@", fields["PYZ_SHA256"])
    loader = loader.replace("@MODULE_FILES@", repr((*WINDOWS_INSTALLER_FILES, "__main__.py")))
    if re.search(r"@[A-Z_]+@", loader):
        raise ValueError("Windows loader contains an unresolved template field")
    rendered = source_file(source, WINDOWS_TEMPLATE).decode("utf-8").replace("@LOADER@", loader.rstrip())
    # 仅原生集成测试可在构建阶段注入 fixture CA，不能依赖 Schannel 忽略的环境变量。
    # 正式 build 不传此值，PS 无运行时镜像/CA/跳过 TLS 参数，也不修改系统证书库。
    ca_argument = ""
    if test_ca_path is not None:
        if not test_ca_path or any(ord(char) < 32 for char in test_ca_path):
            raise ValueError("Test CA path must be nonempty and contain no control characters")
        ca_argument = "--cacert '" + test_ca_path.replace("'", "''") + "'"
    rendered = rendered.replace("@CURL_CA_ARGUMENT@", ca_argument)
    for name, value in fields.items():
        rendered = rendered.replace(f"@{name}@", value)
    if re.search(r"@[A-Z_]+@", rendered):
        raise ValueError("Windows installer contains an unresolved template field")
    return rendered.encode("utf-8")


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


def build(source: Path, version: str, output: Path, release_tag: str | None = None) -> tuple[Path, Path, Path]:
    # 原有调用者仍收到 archive/checksum/formula 三元组；新增固定名称资产写入同一 output。
    tag = release_identity(version, release_tag)
    source = source.resolve(strict=True)
    if source_version(source) != version:
        raise ValueError("Requested release version must match product/VERSION")
    output = output.expanduser().resolve()
    if output == source or any(
        output.is_relative_to(source / name)
        for name in (*RELEASE_FILES, *RELEASE_DIRECTORIES, *OPTIONAL_FILES, "packaging", "tests", "docs")
    ):
        raise ValueError("Output must not be inside the release payload or source/tooling directories")
    paths = release_paths(output, version, tag)
    archive, checksum, formula, installer, bootstrap, manifest = paths
    if formula.parent.is_symlink():
        raise ValueError(f"Formula output directory cannot be a symlink: {formula.parent}")
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Existing output preserved; choose a new --output-dir: {path}")

    data = archive_bytes(source, version)
    digest = hashlib.sha256(data).hexdigest()
    template = source_file(source, "packaging/homebrew/awf-cli.rb.in").decode("utf-8")
    rendered = template.replace("@VERSION@", version).replace("@SHA256@", digest)
    rendered = rendered.replace(f"/releases/download/v{version}/", f"/releases/download/{tag}/")
    if re.search(r"@[A-Z_]+@", rendered):
        raise ValueError("Homebrew formula contains an unresolved template field")
    # 单向内容依赖：tar → pyz → PS → 外部 manifest。manifest 不记录自身摘要，
    # 也不向 manager/release.json 塞入标签/交付哈希，避免循环与已有元数据合同漂移。
    pyz = installer_bytes(data, version, digest)
    pyz_digest = hashlib.sha256(pyz).hexdigest()
    base_url = f"{RELEASE_BASE_URL}/{tag}"
    powershell = render_windows_installer(source, {
        "VERSION": version, "RELEASE_TAG": tag,
        "ARCHIVE_NAME": archive.name, "ARCHIVE_SHA256": digest,
        "PYZ_NAME": installer.name, "PYZ_SHA256": pyz_digest, "BASE_URL": base_url,
    })
    asset_contents = ((archive, data), (installer, pyz), (bootstrap, powershell))
    delivery = {
        "schema_version": 1, "product_version": version, "release_tag": tag,
        "assets": [
            {"filename": path.name, "sha256": hashlib.sha256(content).hexdigest(),
             "size": len(content), "url": f"{base_url}/{path.name}"}
            for path, content in asset_contents
        ],
    }
    manifest_data = (json.dumps(delivery, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    formula.parent.mkdir(exist_ok=True)
    for path, content in (
        (archive, data),
        (checksum, f"{digest}  {archive.name}\n".encode()),
        (formula, rendered.encode("utf-8")),
        (installer, pyz), (bootstrap, powershell), (manifest, manifest_data),
    ):
        with path.open("xb") as stream:
            stream.write(content)
    return archive, checksum, formula


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="release version, for example 2.0.0")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--release-tag", help="fixed release tag, vX.Y.Z or vX.Y.Z-rc.N")
    args = parser.parse_args(argv)
    try:
        archive, _, _ = build(ROOT, args.version, args.output_dir, release_tag=args.release_tag)
        # build 保持原三元组 API，CLI 则显示本次真正写出的全部资产；只有构建完成才报告。
        for path in release_paths(archive.parent, args.version, args.release_tag):
            print(path)
        return 0
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
