#!/usr/bin/env python3
"""从已核验 alpha 候选发布三个官方远程安装源；默认只预览。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile


HOSTS = ("codex", "claude", "antigravity")
REPOSITORY = "Geoege-xll/agent-workflow"
OWNER = "agent-workflow-plugin-source-v1"
MARKET = {"codex": ".agents/plugins/marketplace.json", "claude": ".claude-plugin/marketplace.json"}
MANIFEST = {"codex": ".codex-plugin/plugin.json", "claude": ".claude-plugin/plugin.json",
            "antigravity": ".antigravity-plugin/plugin.json"}


def json_bytes(value):
    """分发记录与市场索引采用固定 JSON 字节，排除机器路径和当前时间。"""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(body):
    return hashlib.sha256(body).hexdigest()


def safe_name(name):
    """同时拒绝 ZIP/Git 的路径穿越、Windows 分隔符、Git 元目录和别名路径。"""
    path = PurePosixPath(name)
    if (not name or "\\" in name or "\0" in name or path.is_absolute()
            or any(part in {".", "..", ".git"} for part in path.parts)
            or path.as_posix() != name or ":" in name):
        raise ValueError("分发资源路径无效：" + name)
    return name


def read_regular(root, name):
    """候选必须为真实普通文件；父目录链接同样不能改变候选读取边界。"""
    path = root / safe_name(name)
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("候选不能含链接：" + name)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("候选必须为普通文件：" + name)
    return path.read_bytes()


def archive_files(body):
    """仅在内存展开普通资源，并保存执行位；绝不调用 extractall。"""
    files = {}
    with zipfile.ZipFile(io.BytesIO(body)) as package:
        for entry in package.infolist():
            name = safe_name(entry.filename)
            mode = entry.external_attr >> 16
            if (name in files or entry.is_dir() or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                    or entry.flag_bits & 1):
                raise ValueError("ZIP 只能包含不重复的普通文件：" + name)
            files[name] = (package.read(entry), "100755" if mode & 0o111 else "100644")
    # 文件与父路径冲突也必须在产生工作树之前明确拒绝。
    if any(str(parent) in files for name in files for parent in PurePosixPath(name).parents
           if str(parent) != "."):
        raise ValueError("ZIP 文件路径与目录冲突")
    return files


def load_candidate(candidate_dir, source_revision, repository):
    """完整核对七包身份、哈希、ZIP 安全及来源闭包，不读取当前源码工作树。"""
    if repository != REPOSITORY or not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ValueError("发布仅接受指定仓库和完整 40 位源码修订")
    if candidate_dir.is_symlink():
        raise ValueError("候选根目录不能是链接")
    root = candidate_dir.resolve(strict=True)
    manifest_body = read_regular(root, "candidate-manifest.json")
    candidate = json.loads(manifest_body)
    source = candidate["source"]
    if (candidate["schema_version"] != 1 or candidate["channel"] != "alpha"
            or candidate["status"] != "BUILD_VERIFIED" or source["dirty"] is not False
            or source["revision"] != source_revision
            or not re.fullmatch(r"[a-f0-9]{64}", source["tree_sha256"])):
        raise ValueError("候选来源、干净状态或核验状态不匹配")
    versions = candidate["versions"]
    if (set(versions) != {"workflow", "native-config"}
            or not re.fullmatch(r"3\.0\.0-alpha\.[1-9][0-9]*", versions["workflow"])
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-alpha\.[1-9][0-9]*", versions["native-config"])):
        raise ValueError("候选仅支持显式 alpha 版本")
    expected = {}
    for host in HOSTS:
        for kind, suffix in (("plugin", ""), ("local-source", "-local-source")):
            name = f"workflow/agent-workflow-{host}-{versions['workflow']}{suffix}.zip"
            expected[name] = {"product": "workflow", "host": host, "kind": kind, "version": versions["workflow"]}
    expected[f"native/native-agent-config-{versions['native-config']}.zip"] = {
        "product": "native-config", "kind": "standalone", "version": versions["native-config"]}
    rows = candidate["artifacts"]
    if len(rows) != 7 or {row["path"] for row in rows} != set(expected):
        raise ValueError("候选必须恰好绑定既有七包")
    if {path.relative_to(root).as_posix() for path in root.rglob("*.zip")} != set(expected):
        raise ValueError("候选包含额外 ZIP 或缺少 ZIP")
    archives, hashes = {}, {}
    for row in rows:
        name = row["path"]
        if any(row.get(key) != value for key, value in expected[name].items()):
            raise ValueError("候选宿主或产品身份不一致")
        body = read_regular(root, name)
        if digest(body) != row["sha256"]:
            raise ValueError("候选 ZIP 摘要不匹配：" + name)
        hashes[name] = row["sha256"]
        archives[name] = archive_files(body)
    native = archives[f"native/native-agent-config-{versions['native-config']}.zip"]
    build = json.loads(native["BUILD.json"][0])
    if (build["version"] != versions["native-config"] or build["name"] != "native-agent-config"
            or build["files"] != {name: digest(value[0]) for name, value in native.items()
                                  if name != "BUILD.json"}):
        raise ValueError("独立配置包身份或来源闭包不一致")
    distributions = {}
    descriptors = set()
    for host in HOSTS:
        stem = f"workflow/agent-workflow-{host}-{versions['workflow']}"
        plugin = archives[stem + ".zip"]
        provenance = json.loads(plugin["sources.json"][0])
        if (provenance["schema_version"] != 1 or provenance["host"] != host
                or provenance["plugin_version"] != versions["workflow"]
                or provenance["product"] != "workflow-core"):
            raise ValueError("插件来源身份不一致")
        closure = {name: digest(value[0]) for name, value in plugin.items() if name != "sources.json"}
        if provenance["payload_sha256"] != closure:
            raise ValueError("插件来源载荷闭包不一致")
        for name, sha in provenance["source_files"].items():
            safe_name(name)
            if name in plugin and digest(plugin[name][0]) != sha:
                raise ValueError("插件规范源摘要不一致：" + name)
        identity = json.loads(plugin[MANIFEST[host]][0])
        if identity["name"] != "agent-workflow" or identity["version"] != versions["workflow"]:
            raise ValueError("插件清单身份不一致")
        descriptors.add(plugin["plugins/maintenance/component.json"][0])
        local = archives[stem + "-local-source.zip"]
        prefix = "agent-workflow/" if host == "antigravity" else "plugins/agent-workflow/"
        projected = {prefix + name: value for name, value in plugin.items()}
        # 既有源 ZIP 构建器按完整相对路径设置执行位；加前缀后的资源均为 644。
        # 逐字节验证原源包这一既有合同，远程 Git 树则保留主插件 ZIP 的真实执行位。
        # 不为远程安装修改构建器，也不悄悄重打已核验 ZIP。
        expected_local = {name: (value[0], "100644") for name, value in projected.items()}
        if host in MARKET:
            market_name = MARKET[host]
            # 只允许构建器现有的单一市场记录，再仅替换发布市场名称。
            original = {"name": "agent-workflow-local", "plugins": [{"name": "agent-workflow",
                "source": {"source": "local", "path": "./plugins/agent-workflow"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity"}]} if host == "codex" else {
                    "name": "agent-workflow-local", "owner": {"name": "Agent Workflow"},
                    "plugins": [{"name": "agent-workflow", "source": "./plugins/agent-workflow"}]}
            projected[market_name] = (json_bytes(original), "100644")
            expected_local[market_name] = projected[market_name]
            if local != expected_local:
                raise ValueError("本地市场源与精确插件包不一致：" + host)
            original["name"] = "agent-workflow-alpha"
            projected[market_name] = (json_bytes(original), "100644")
            distributions[host] = projected
        else:
            if local != expected_local:
                raise ValueError("AGY 本地源与精确插件包不一致")
            distributions[host] = dict(plugin)
    if len(descriptors) != 1:
        raise ValueError("三个插件的组件描述符不同")
    # 复用候选构建器的组件 ABI 校验，不在发布器复制独立产品的安装规则。
    from build_candidates import validate_component_binding
    binding = validate_component_binding(next(iter(descriptors)),
        root / f"native/native-agent-config-{versions['native-config']}.zip", versions["native-config"])
    if binding != candidate["maintenance_component"]:
        raise ValueError("候选组件绑定记录不一致")
    for host, files in distributions.items():
        if "distribution.json" in files:
            raise ValueError("插件不能占用外层分发记录路径")
        record = {"schema_version": 1, "managed_by": OWNER, "repository": repository,
            "host": host, "channel": "alpha", "ref": "refs/heads/plugins-" + host + "-alpha",
            "version": versions["workflow"], "source_revision": source_revision,
            "source_tree_sha256": source["tree_sha256"], "candidate_sha256": digest(manifest_body),
            "artifacts_sha256": hashes,
            "plugin_zip_sha256": hashes[f"workflow/agent-workflow-{host}-{versions['workflow']}.zip"],
            "files": file_closure(files)}
        files["distribution.json"] = (json_bytes(record), "100644")
    return distributions


def file_closure(files):
    """外层记录不摘要自身，剩余每个文件都绑定原始字节与 Git 执行位。"""
    return {name: {"sha256": digest(body), "mode": mode} for name, (body, mode) in files.items()}


def git(directory, *args, input=None):
    """Git 仅操作临时仓库；固定作者与时间，不借用用户配置或运行用户 Hook。"""
    environment = {**os.environ, "GIT_AUTHOR_NAME": "Agent Workflow", "GIT_COMMITTER_NAME": "Agent Workflow",
        "GIT_AUTHOR_EMAIL": "plugins@agent-workflow.invalid", "GIT_COMMITTER_EMAIL": "plugins@agent-workflow.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000"}
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(directory), *args],
        input=input, stderr=subprocess.PIPE, env=environment)


def tree_files(repository, revision):
    """读取远程提交的完整文件闭包，任何链接、子模块或额外文件均会被核验拒绝。"""
    result = {}
    for entry in git(repository, "ls-tree", "-r", "-z", revision).split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, sha = metadata.decode().split()
        name = safe_name(raw_name.decode("utf-8"))
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("已有分支含非普通文件：" + name)
        result[name] = (git(repository, "cat-file", "blob", sha), mode)
    return result


def validate_owned(files, expected):
    """首次可创建空分支；更新仅接受同发布器拥有且完整闭包未变的分发树。"""
    if "distribution.json" not in files:
        raise ValueError("已有分支缺少受管发布标记")
    record = json.loads(files["distribution.json"][0])
    for key in ("schema_version", "managed_by", "repository", "host", "channel", "ref"):
        if record.get(key) != expected[key]:
            raise ValueError("已有分支的发布所有权不匹配")
    if (files["distribution.json"][1] != "100644"
            or record["files"] != file_closure({name: value for name, value in files.items()
                                               if name != "distribution.json"})):
        raise ValueError("已有分支含未知文件或闭包被修改")
    return record


def publish(candidate_dir, source_revision, repository, remote, channel="alpha", apply=False):
    """预检三分支后一次原子快进；不使用 force，不创建 tag、Release 或远程配置。"""
    if channel != "alpha" or not remote or remote.startswith("-"):
        raise ValueError("仅支持 alpha 和显式远程地址")
    distributions = load_candidate(Path(candidate_dir), source_revision, repository)
    with tempfile.TemporaryDirectory(prefix="awf-plugin-publish-") as temporary:
        work = Path(temporary)
        git(work, "init", "--quiet")
        refs = ["refs/heads/plugins-" + host + "-alpha" for host in HOSTS]
        advertised = git(work, "ls-remote", "--refs", remote, *refs).decode().splitlines()
        tips = {line.split()[1]: line.split()[0] for line in advertised}
        if tips:
            git(work, "fetch", "--quiet", "--no-tags", remote, *tips.values())
        plans, pushes = [], []
        for host, files in distributions.items():
            record = json.loads(files["distribution.json"][0])
            ref, parent = record["ref"], tips.get(record["ref"])
            if parent:
                old_files = tree_files(work, parent)
                old = validate_owned(old_files, record)
                if old["version"] == record["version"]:
                    # 同版仅当七个原始 ZIP 和完整安装树完全相同才幂等；候选外层文档
                    # 或源码提交变化不单独产生提交，保留首次发布的来源记录。
                    if (old["artifacts_sha256"] != record["artifacts_sha256"]
                            or old["files"] != record["files"]):
                        raise ValueError("同一版本已绑定不同候选字节：" + host)
                    # 混合幂等与更新时也把未变 ref 加入同一推送；若它在预检后被其他
                    # 提交推进，普通非快进检查会阻止整个原子批次，不留下混合版本。
                    pushes.append(parent + ":" + ref)
                    plans.append({"host": host, "ref": ref, "action": "unchanged", "commit": parent})
                    continue
                if (not re.fullmatch(r"3\.0\.0-alpha\.[1-9][0-9]*", old["version"])
                        or int(old["version"].rsplit(".", 1)[1]) >= int(record["version"].rsplit(".", 1)[1])):
                    raise ValueError("发布版本必须向前递增")
            # 使用独立临时 index 直接写对象；不 checkout 或覆盖任何本地安装树。
            git(work, "read-tree", "--empty")
            entries = []
            for name, (body, mode) in sorted(files.items()):
                sha = git(work, "hash-object", "-w", "--stdin", input=body).decode().strip()
                entries.append(f"{mode} {sha}\t{name}".encode() + b"\0")
            git(work, "update-index", "-z", "--index-info", input=b"".join(entries))
            tree = git(work, "write-tree").decode().strip()
            arguments = ["commit-tree", tree, *( ["-p", parent] if parent else [] ),
                         "-m", f"Publish {host} {record['version']}"]
            commit = git(work, *arguments).decode().strip()
            pushes.append(commit + ":" + ref)
            plans.append({"host": host, "ref": ref, "action": "update" if parent else "create", "commit": commit})
        if apply and any(plan["action"] != "unchanged" for plan in plans):
            # 服务端无 atomic 能力或任意分支发生竞争都会整体失败，不回退为逐分支推送。
            git(work, "push", "--atomic", remote, *pushes)
        return {"repository": repository, "channel": channel, "applied": apply,
                "source_revision": source_revision, "branches": plans}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--channel", choices=("alpha",), required=True)
    parser.add_argument("--apply", action="store_true", help="实际原子推送；省略时仅核验和预览")
    args = parser.parse_args()
    try:
        result = publish(**vars(args))
    except (ValueError, OSError, UnicodeError, KeyError, TypeError, zipfile.BadZipFile,
            subprocess.CalledProcessError) as error:
        print("插件来源发布失败：" + str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            sys.stderr.write(error.stderr.decode("utf-8", errors="replace"))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
