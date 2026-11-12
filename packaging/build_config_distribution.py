#!/usr/bin/env python3
"""用真实独立 ZIP 装配组件 descriptor；发布模式必须再次下载核对真实资产字节。"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("config_component_store", ROOT / "plugins/maintenance/component_store.py")
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


def assemble(artifact: Path, *, url="", downloader=None):
    """发行元数据只认文件内固定版本与完整 BUILD；不接受手工传入的摘要或猜测 URL。"""
    try:
        artifact = artifact.resolve(strict=True)
        if artifact.stat().st_size > store.MAX_ARCHIVE:
            raise store.ComponentError("archive_too_large")
        with zipfile.ZipFile(artifact) as package:
            if package.getinfo("native_config/VERSION").file_size > 100:
                raise store.ComponentError("invalid_distribution_version")
            version = package.read("native_config/VERSION").decode("ascii").strip()
        if not store.VERSION.fullmatch(version):
            raise store.ComponentError("invalid_distribution_version")
        name = f"{store.PRODUCT}-{version}.zip"
        if artifact.name != name:
            raise store.ComponentError("invalid_artifact_name")
        digest, _ = store.archive_payload(artifact, version)
        result = {"schema_version": 1, "product": store.PRODUCT, "version": version, "channel": "alpha",
                  "cli_protocol": 1, "service_protocol": 2, "release_status": "published" if url else "unpublished",
                  "artifact": {"name": name, "sha256": digest, "url": url}}
        if url:
            store.release_url(url, name)
            # 没有跳过在线核验开关：published 表示 URL 已可下载，且实际字节就是选定发行包。
            with tempfile.TemporaryDirectory(prefix="agent-config-release-") as temporary:
                downloaded = Path(temporary).resolve() / name
                (downloader or store.download)(result, downloaded)
                store.archive_payload(downloaded, version, digest)
        return result
    except (OSError, ValueError, KeyError, UnicodeError, zipfile.BadZipFile):
        raise store.ComponentError("invalid_distribution") from None


def main():
    parser = argparse.ArgumentParser(description="从真实独立配置包生成组件发行元数据")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--url", default="", help="已发布 GitHub 资产 URL；留空生成 unpublished 元数据")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = assemble(args.artifact, url=args.url)
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "DISTRIBUTION_VERIFIED", "release_status": data["release_status"],
                          "version": data["version"], "sha256": data["artifact"]["sha256"]}, ensure_ascii=False))
        return 0
    except store.ComponentError as error:
        print(json.dumps({"status": "DISTRIBUTION_REJECTED", "code": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
