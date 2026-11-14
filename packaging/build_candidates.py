#!/usr/bin/env python3
"""复用两个唯一构建器，汇总同一源码的七个独立发行候选及精确摘要。"""

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
sys.path.insert(0, str(ROOT))
from product.command_identity import load_identity
from product.release_channels import validate_channel, version_channel
IDENTITY = load_identity(ROOT)


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


def validate_component_binding(descriptor, archive, version):
    """交付层只核对两个独立产品的绑定，不下载组件或读取原生源码。

    未发布描述符允许尚未冻结摘要；一旦有摘要，即使仍为离线 unpublished，也必须
    与本次真实独立 ZIP 字节一致。published 则必须同时具备真实发行 URL 与摘要。
    描述符的完整安全解析由薄启动器负责，此处只检查候选装配需要的稳定 ABI。
    """
    component = json.loads(descriptor)
    artifact = component["artifact"]
    if (component["schema_version"] != 1 or component["product"] != "native-agent-config"
            or component["version"] != version or component["channel"] != version_channel(version)
            or component["cli_protocol"] != 1 or component["service_protocol"] != 2
            or artifact["name"] != archive.name):
        raise ValueError("插件组件描述符与独立候选身份或协议不一致")
    if component["release_status"] not in {"unpublished", "published"}:
        raise ValueError("组件描述符发行状态无效")
    expected = artifact["sha256"]
    url = artifact["url"]
    if not isinstance(expected, str) or not isinstance(url, str):
        raise ValueError("组件描述符摘要和 URL 必须为字符串")
    if component["release_status"] == "unpublished" and url:
        raise ValueError("未发布组件描述符不能声明下载 URL")
    if component["release_status"] == "published" and (not expected or not url.startswith("https://")):
        raise ValueError("已发布组件描述符缺少冻结摘要或 HTTPS 发行 URL")
    if expected and (not re.fullmatch(r"[a-f0-9]{64}", expected) or expected != digest(archive.read_bytes())):
        raise ValueError("插件组件描述符摘要与独立 ZIP 不一致")
    return {"version": version, "release_status": component["release_status"],
            "descriptor_sha256": digest(descriptor), "artifact_sha256": expected,
            "artifact_matches_candidate": bool(expected)}


def build(source, output):
    """只编排构建及交付元数据；载荷、白名单和宿主转换规则仍由原构建器唯一负责。"""
    source = source.resolve(strict=True)
    output = output.absolute()
    # 输出必须新建且在源码树外，既不覆写候选，也不让自身产物污染同源码摘要。
    if output.is_symlink() or output.exists() or output.resolve().is_relative_to(source):
        raise ValueError("请使用源码树外尚不存在的候选输出目录")
    versions = {"workflow": (source / "product/PLUGIN_VERSION").read_text(encoding="ascii").strip(),
                "native-config": (source / "native_config/VERSION").read_text(encoding="ascii").strip()}
    # 两个产品独立版本化，但同一次候选的发行渠道必须一致；不能把未发布 alpha
    # 组件与正式工作流混装后交给发布消费者决定如何解释。
    channel = version_channel(versions["workflow"])
    validate_channel(versions["native-config"], channel)
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
    component_descriptor = None
    identity_body = (source / "product/command_identity.json").read_bytes()
    for host in ("codex", "claude", "antigravity"):
        primary = output / "workflow" / f"{IDENTITY['artifact_prefix']}-{host}-{versions['workflow']}.zip"
        with zipfile.ZipFile(primary) as archive:
            if archive.read("product/command_identity.json") != identity_body:
                raise ValueError("插件包命令身份与唯一源不一致")
            provenance = archive.read("sources.json")
            record = json.loads(provenance)
            if record["plugin_version"] != versions["workflow"] or record["host"] != host:
                raise ValueError("工作流包身份与候选版本源不一致")
            descriptor = archive.read("plugins/maintenance/component.json")
            if component_descriptor is not None and descriptor != component_descriptor:
                raise ValueError("三个宿主插件必须携带相同组件描述符")
            component_descriptor = descriptor
        local = primary.with_name(primary.stem + "-local-source.zip")
        with zipfile.ZipFile(local) as archive:
            matches = [name for name in archive.namelist() if name.endswith("/sources.json")]
            if len(matches) != 1 or archive.read(matches[0]) != provenance:
                raise ValueError("本地安装源与对应插件包不一致")
            component_matches = [name for name in archive.namelist()
                                 if name.endswith("/plugins/maintenance/component.json")]
            if len(component_matches) != 1 or archive.read(component_matches[0]) != descriptor:
                raise ValueError("本地安装源组件描述符与对应插件包不一致")
        for path, kind in ((primary, "plugin"), (local, "local-source")):
            artifacts.append({"path": path.relative_to(output).as_posix(), "product": "workflow",
                              "host": host, "kind": kind, "version": versions["workflow"]})
    native = output / "native" / f"native-agent-config-{versions['native-config']}.zip"
    with zipfile.ZipFile(native) as archive:
        if archive.read("product/command_identity.json") != identity_body:
            raise ValueError("独立包命令身份与插件唯一源不一致")
        if json.loads(archive.read("BUILD.json"))["version"] != versions["native-config"]:
            raise ValueError("原生配置独立包与候选版本源不一致")
    component_binding = validate_component_binding(component_descriptor, native, versions["native-config"])
    artifacts.append({"path": native.relative_to(output).as_posix(), "product": "native-config",
                      "kind": "standalone", "version": versions["native-config"]})
    if set(output.rglob("*.zip")) != {output / row["path"] for row in artifacts}:
        raise ValueError("候选必须恰有六个工作流 ZIP 与一个原生配置 ZIP")
    for row in artifacts:
        path = output / row["path"]
        row["sha256"] = digest(path.read_bytes())
        path.with_suffix(".zip.sha256").write_text(row["sha256"] + "  " + path.name + "\n", encoding="ascii")
    manifest = {"schema_version": 1, "channel": channel, "status": "BUILD_VERIFIED",
                "runtime_verified": False, "source": before, "versions": versions,
                "version_sources": {"workflow": "product/PLUGIN_VERSION", "native-config": "native_config/VERSION"},
                "builders_sha256": builders, "artifacts": artifacts,
                "maintenance_component": component_binding,
                "pending_acceptance": ["official host loading, dispatch, model and effort behavior",
                                       "in-flight task resource retention across plugin updates"],
                "installation": {"products_are_independent": True, "mcp_required": False}}
    (output / "candidate-manifest.json").write_bytes(json_bytes(manifest))
    (output / "SHA256SUMS").write_text("".join(row["sha256"] + "  " + row["path"] + "\n"
                                               for row in artifacts), encoding="ascii")
    summary = ("# " + ("正式" if channel == "stable" else "Alpha") + "候选\n\n" + f"源码：`{before['revision']}`；工作树有改动：`{str(before['dirty']).lower()}`。\n\n"
               + f"源码文件摘要：`{before['tree_sha256']}`。\n\n"
               + f"工作流：`{versions['workflow']}`；独立原生配置：`{versions['native-config']}`。\n\n"
               + "状态：`BUILD_VERIFIED`，`runtime_verified=false`。官方宿主实际加载、派发、模型/推理及跨更新保留仍待验收。\n\n"
               + "两个产品分别安装；工作流不需要配置网页、HTTP 服务或 MCP。此流程仅生成候选附件，不创建 tag 或 Release。\n\n"
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
