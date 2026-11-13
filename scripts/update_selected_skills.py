#!/usr/bin/env python3
"""显式生成精选依赖审阅候选；来源/锁/归档校验统一复用selected_skills。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib.skills.selected_skills import LOCK, VENDOR, SPECS, read_regular, snapshot, validate_lock, unique_object, load_git_archive, load_playwright_archives


def candidate(dependency: str, ref: str, archive: Path | list[Path], output: Path, runtime_manifest: Path | None = None) -> dict:
    """本脚本只拥有候选写入与差异报告；不复制一套来源/路径/闭包校验。

    40位ref是期望标签，本地manifest与摘要不是签名；完整来源仍须审阅。全部校验
    先于新输出目录创建，不覆盖生产依赖、不联网或执行任何npm生命周期/上游脚本。
    """
    if dependency not in SPECS or not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError("dependency and full lowercase 40-hex ref are required")
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("output must be a new physical candidate directory")
    destination = output.absolute()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("candidate output must be outside the source checkout")
    lock, files = snapshot(ROOT)
    archives = [archive] if isinstance(archive, Path) else archive
    ignored = 0
    if dependency == "playwright-cli":
        if runtime_manifest is None:
            raise ValueError("Playwright update requires the reviewed --runtime-manifest and three --archive arguments")
        manifest = json.loads(read_regular(runtime_manifest.parent, runtime_manifest.name), object_pairs_hook=unique_object)
        item, selected = load_playwright_archives(manifest, archives)
        if item["commit"] != ref:
            raise ValueError("requested ref must match the CLI package gitHead")
        archive_digest = {p["name"]: p["tarball_sha256"] for p in item["packages"]}
    else:
        if len(archives) != 1 or runtime_manifest is not None:
            raise ValueError("Git dependency update requires exactly one archive and no npm manifest")
        item, selected, archive_digest, ignored = load_git_archive(dependency, ref, archives[0])
    old = lock["dependencies"][dependency]
    lock["dependencies"][dependency] = item
    validate_lock(lock)
    inventory = item["files"]
    prefix = VENDOR + "/" + dependency + "/"
    files = {path: data for path, data in files.items() if not path.startswith(prefix)}
    files.update({prefix + path: data for path, data in selected.items()})
    files[LOCK] = (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report = {"dependency": dependency, "repository": item["repository"], "requested_ref": ref, "archive_sha256": archive_digest,
              "source_authenticity": "unverified_local_archive", "review_required": True,
              "ignored_nonclosure_links_or_special_entries": ignored,
              "previous_commit": old["commit"], "added": sorted(set(inventory) - set(old["files"])),
              "removed": sorted(set(old["files"]) - set(inventory)),
              "changed": sorted(p for p in set(inventory) & set(old["files"]) if inventory[p] != old["files"][p]),
              "upstream_scripts_executed": False}
    # 文件模式来自同一已验证锁；保留原版可执行辅助文件而不授予额外权限。
    modes = {VENDOR + "/" + name + "/" + relative: record.get("mode", 0o644)
             for name, entry in lock["dependencies"].items() for relative, record in entry["files"].items()}
    output.mkdir(parents=True, exist_ok=False)
    for path, data in files.items():
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(modes.get(path, 0o644))
    (output / "selected-skills-update-review.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency", choices=sorted(SPECS), required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(candidate(args.dependency, args.ref, args.archive, args.output, args.runtime_manifest), sort_keys=True))
        return 0
    except (ValueError, OSError, tarfile.TarError) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
