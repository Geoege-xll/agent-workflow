#!/usr/bin/env python3
"""复用两个唯一构建器，汇总同一源码的七个独立 alpha 候选及精确摘要。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(body):
    return hashlib.sha256(body).hexdigest()


def git(source, *arguments):
    return subprocess.check_output(["git", "-C", str(source), *arguments], stderr=subprocess.PIPE)


def source_state(source):
    """绑定 Git 修订及当前实际文件字节；未提交候选也不能伪称只来自 HEAD。

    只读取 Git 已跟踪及非忽略的新文件，已删除文件仍进入摘要。构建前后比较同一
    状态，防止两个顺序构建器碰到不同源码；不创建暂存区、快照目录或修改用户配置。
    """
    top = Path(git(source, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != source:
        raise ValueError("候选来源必须是 Git 工作树物理根")
    files = {}
    for raw in git(source, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = source / name
        if path.is_symlink():
            raise ValueError("候选源码不能含符号链接：" + name)
        files[name] = digest(path.read_bytes()) if path.is_file() else None
    return {"revision": git(source, "rev-parse", "HEAD").decode().strip(),
            "tree_sha256": digest(json_bytes(files)), "files": len(files),
            "dirty": bool(git(source, "status", "--porcelain", "--untracked-files=normal"))}


def build(source, output):
    """只编排构建及交付元数据；载荷、白名单和宿主转换规则仍由原构建器唯一负责。"""
    source = source.resolve(strict=True)
    output = output.absolute()
    # 输出必须新建且在源码树外，既不覆写候选，也不让自身产物污染同源码摘要。
    if output.is_symlink() or output.exists() or output.resolve().is_relative_to(source):
        raise ValueError("请使用源码树外尚不存在的候选输出目录")
    versions = {"workflow": (source / "product/PLUGIN_VERSION").read_text(encoding="ascii").strip(),
                "native-config": (source / "native_config/VERSION").read_text(encoding="ascii").strip()}
    if any(not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-alpha\.[1-9][0-9]*", value)
           for value in versions.values()):
        raise ValueError("候选交付只接受两个版本源中的显式 alpha.N，不发布稳定版本")
    before = source_state(source)
    builders = {name: digest((source / "packaging" / name).read_bytes()) for name in
                ("build_candidates.py", "build_plugin.py", "build_agent_config.py")}
    output.mkdir(parents=True, exist_ok=False)
    commands = (
        ("build_plugin.py", "workflow", ("--host", "all", "--local-source")),
        ("build_agent_config.py", "native", ()),
    )
    for builder, destination, extra in commands:
        subprocess.run([sys.executable, "-B", "-X", "utf8", str(source / "packaging" / builder),
                        "--source", str(source), "--output-dir", str(output / destination), *extra],
                       cwd=source, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if source_state(source) != before:
        raise ValueError("构建期间源码发生变化；本目录不构成同源码候选，请冻结来源后换新目录")
    artifacts = []
    for host in ("codex", "claude", "antigravity"):
        primary = output / "workflow" / f"agent-workflow-{host}-{versions['workflow']}.zip"
        with zipfile.ZipFile(primary) as archive:
            provenance = archive.read("sources.json")
            record = json.loads(provenance)
            if record["plugin_version"] != versions["workflow"] or record["host"] != host:
                raise ValueError("工作流包身份与候选版本源不一致")
        local = primary.with_name(primary.stem + "-local-source.zip")
        with zipfile.ZipFile(local) as archive:
            matches = [name for name in archive.namelist() if name.endswith("/sources.json")]
            if len(matches) != 1 or archive.read(matches[0]) != provenance:
                raise ValueError("本地安装源与对应插件包不一致")
        for path, kind in ((primary, "plugin"), (local, "local-source")):
            artifacts.append({"path": path.relative_to(output).as_posix(), "product": "workflow",
                              "host": host, "kind": kind, "version": versions["workflow"]})
    native = output / "native" / f"native-agent-config-{versions['native-config']}.zip"
    with zipfile.ZipFile(native) as archive:
        if json.loads(archive.read("BUILD.json"))["version"] != versions["native-config"]:
            raise ValueError("原生配置独立包与候选版本源不一致")
    artifacts.append({"path": native.relative_to(output).as_posix(), "product": "native-config",
                      "kind": "standalone", "version": versions["native-config"]})
    if set(output.rglob("*.zip")) != {output / row["path"] for row in artifacts}:
        raise ValueError("候选必须恰有六个工作流 ZIP 与一个原生配置 ZIP")
    for row in artifacts:
        path = output / row["path"]
        row["sha256"] = digest(path.read_bytes())
        path.with_suffix(".zip.sha256").write_text(row["sha256"] + "  " + path.name + "\n", encoding="ascii")
    manifest = {"schema_version": 1, "channel": "alpha", "status": "BUILD_VERIFIED",
                "runtime_verified": False, "source": before, "versions": versions,
                "version_sources": {"workflow": "product/PLUGIN_VERSION", "native-config": "native_config/VERSION"},
                "builders_sha256": builders, "artifacts": artifacts,
                "pending_acceptance": ["official host loading, dispatch, model and effort behavior",
                                       "in-flight task resource retention across plugin updates"],
                "installation": {"products_are_independent": True, "mcp_required": False}}
    (output / "candidate-manifest.json").write_bytes(json_bytes(manifest))
    (output / "SHA256SUMS").write_text("".join(row["sha256"] + "  " + row["path"] + "\n"
                                               for row in artifacts), encoding="ascii")
    summary = ("# Alpha 候选\n\n" + f"源码：`{before['revision']}`；工作树有改动：`{str(before['dirty']).lower()}`。\n\n"
               + f"源码文件摘要：`{before['tree_sha256']}`。\n\n"
               + f"工作流：`{versions['workflow']}`；独立原生配置：`{versions['native-config']}`。\n\n"
               + "状态：`BUILD_VERIFIED`，`runtime_verified=false`。官方宿主实际加载、派发、模型/推理及跨更新保留仍待验收。\n\n"
               + "两个产品分别安装；工作流不需要配置网页、HTTP 服务或 MCP。此流程仅生成 alpha 附件，不创建 tag 或 Release。\n\n"
               + "| 产物 | SHA-256 |\n| --- | --- |\n"
               + "".join(f"| `{row['path']}` | `{row['sha256']}` |\n" for row in artifacts))
    (output / "CANDIDATE.md").write_text(summary, encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build(args.source, args.output_dir)
    except (ValueError, OSError, UnicodeError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print("候选构建失败：" + str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            sys.stderr.write(error.stderr.decode("utf-8", errors="replace"))
        return 1
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
