#!/usr/bin/env python3
"""从已核验发行候选发布三个官方远程安装源；默认只预览。"""

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


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from product.command_identity import load_identity
from product.release_channels import CHANNELS, compare_versions, validate_channel
IDENTITY = load_identity(ROOT)

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
            if stat.S_IMODE(mode) not in {0o644, 0o755}:
                raise ValueError("ZIP 普通文件模式仅允许 0644 或 0755：" + name)
            files[name] = (package.read(entry), "100755" if mode & 0o111 else "100644")
    # 文件与父路径冲突也必须在产生工作树之前明确拒绝。
    if any(str(parent) in files for name in files for parent in PurePosixPath(name).parents
           if str(parent) != "."):
        raise ValueError("ZIP 文件路径与目录冲突")
    return files


def validate_local_source(plugin, local, host, channel="alpha"):
    """核对主包和本地源的唯一构建模式，返回保留主包执行位的官方分发投影。"""
    from build_plugin import archive_modes

    # 模式权威仍由唯一构建器负责，且读取主ZIP中的同一份锁，不能只允许两包
    # 彼此相等：攻击者同时去掉锁定执行位时，也必须拒绝。
    modes = archive_modes({name: value[0] for name, value in plugin.items()})
    if any(value[1] != f"{modes[name]:o}" for name, value in plugin.items()):
        raise ValueError("主插件包模式与唯一构建合同不一致：" + host)
    prefix = IDENTITY["plugin_name"] + "/" if host == "antigravity" else "plugins/" + IDENTITY["plugin_name"] + "/"
    projected = {prefix + name: value for name, value in plugin.items()}
    if host in MARKET:
        market_name = MARKET[host]
        original = {"name": IDENTITY["marketplaces"]["local"], "plugins": [{"name": IDENTITY["plugin_name"],
            "source": {"source": "local", "path": "./plugins/" + IDENTITY["plugin_name"]},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity"}]} if host == "codex" else {
                "name": IDENTITY["marketplaces"]["local"], "owner": {"name": "Agent Workflow"},
                "plugins": [{"name": IDENTITY["plugin_name"], "source": "./plugins/" + IDENTITY["plugin_name"]}]}
        projected[market_name] = (json_bytes(original), "100644")
    # 加前缀后，本地启动器按构建规则成为644；同包锁中的上游755仍应保留。
    # 直接复用模式函数，避免再次把这两种资源错误归为统一权限。
    modes = archive_modes({name: value[0] for name, value in projected.items()})
    expected_local = {name: (value[0], f"{modes[name]:o}") for name, value in projected.items()}
    if local != expected_local:
        raise ValueError("本地源与精确插件包不一致：" + host)
    if host in MARKET:
        original["name"] = IDENTITY["marketplaces"][channel]
        projected[market_name] = (json_bytes(original), "100644")
        return projected
    return dict(plugin)


def load_candidate(candidate_dir, source_revision, repository, channel="alpha"):
    """完整核对七包身份、哈希、ZIP 安全及来源闭包，不读取当前源码工作树。"""
    if repository != REPOSITORY or not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ValueError("发布仅接受指定仓库和完整 40 位源码修订")
    if candidate_dir.is_symlink():
        raise ValueError("候选根目录不能是链接")
    root = candidate_dir.resolve(strict=True)
    manifest_body = read_regular(root, "candidate-manifest.json")
    candidate = json.loads(manifest_body)
    source = candidate["source"]
    if (candidate["schema_version"] != 1 or candidate["channel"] != channel
            or candidate["status"] != "BUILD_VERIFIED" or source["dirty"] is not False
            or source["revision"] != source_revision
            or not re.fullmatch(r"[a-f0-9]{64}", source["tree_sha256"])):
        raise ValueError("候选来源、干净状态或核验状态不匹配")
    versions = candidate["versions"]
    if set(versions) != {"workflow", "native-config"}:
        raise ValueError("候选产品版本集合无效")
    # 两个独立版本都必须匹配显式发布渠道，不能靠候选 channel 字段冒充正式发行。
    for version in versions.values():
        validate_channel(version, channel)
    expected = {}
    for host in HOSTS:
        for kind, suffix in (("plugin", ""), ("local-source", "-local-source")):
            name = f"workflow/{IDENTITY['artifact_prefix']}-{host}-{versions['workflow']}{suffix}.zip"
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
    identity_body = native["product/command_identity.json"][0]
    if json.loads(identity_body) != IDENTITY:
        raise ValueError("候选命令身份不匹配固定产品合同")
    distributions = {}
    descriptors = set()
    for host in HOSTS:
        stem = f"workflow/{IDENTITY['artifact_prefix']}-{host}-{versions['workflow']}"
        plugin = archives[stem + ".zip"]
        if plugin["product/command_identity.json"][0] != identity_body:
            raise ValueError("两个独立产品的命令身份源字节不一致")
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
        if identity["name"] != IDENTITY["plugin_name"] or identity["version"] != versions["workflow"]:
            raise ValueError("插件清单身份不一致")
        descriptors.add(plugin["plugins/maintenance/component.json"][0])
        local = archives[stem + "-local-source.zip"]
        distributions[host] = validate_local_source(plugin, local, host, channel)
    if len(descriptors) != 1:
        raise ValueError("三个插件的组件描述符不同")
    # 复用候选构建器的组件 ABI 校验，不在发布器复制独立产品的安装规则。
    from build_candidates import validate_component_binding
    binding = validate_component_binding(next(iter(descriptors)),
        root / f"native/native-agent-config-{versions['native-config']}.zip", versions["native-config"])
    if binding != candidate["maintenance_component"]:
        raise ValueError("候选组件绑定记录不一致")
    # 首轮正式 CI 可产出 unpublished 候选供独立组件发行；Git 安装源只能消费
    # 后续已发布、下载核验并精确绑定同一原生 ZIP 的候选，避免先插件后组件。
    # 历史 alpha 的离线候选合同保持原样，不把新正式门禁追溯到旧渠道。
    if channel == "stable" and (binding["release_status"] != "published"
                                or binding["artifact_matches_candidate"] is not True):
        raise ValueError("正式插件发布前必须先发布并固定验证原生组件")
    if channel == "stable":
        # 下载地址的仓库／资产安全规则由组件仓唯一维护；不因 publisher 只读 ZIP
        # 就退化成接受任意 HTTPS。这里不重新下载，也不启动配置业务或读取用户根。
        from plugins.maintenance.component_store import ComponentError, release_url
        descriptor = json.loads(next(iter(descriptors)))
        try:
            release_url(descriptor["artifact"]["url"], descriptor["artifact"]["name"])
        except ComponentError as error:
            raise ValueError("正式组件固定发行来源无效") from error
    for host, files in distributions.items():
        if "distribution.json" in files:
            raise ValueError("插件不能占用外层分发记录路径")
        record = {"schema_version": 1, "managed_by": OWNER, "repository": repository,
            "host": host, "channel": channel, "ref": "refs/heads/plugins-" + host + "-" + channel,
            "version": versions["workflow"], "source_revision": source_revision,
            "source_tree_sha256": source["tree_sha256"], "candidate_sha256": digest(manifest_body),
            "artifacts_sha256": hashes,
            "plugin_zip_sha256": hashes[f"workflow/{IDENTITY['artifact_prefix']}-{host}-{versions['workflow']}.zip"],
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


def native_binding(record):
    """从已冻结七包记录取唯一配置组件绑定；兼容历史记录而不猜版本或来源。"""
    prefix = "native/native-agent-config-"
    artifacts = record["artifacts_sha256"]
    names = [name for name in artifacts if name.startswith(prefix) and name.endswith(".zip")]
    if len(names) != 1:
        raise ValueError("已有分发缺少唯一原生组件绑定")
    name = names[0]
    version = name[len(prefix):-4]
    validate_channel(version, record["channel"])
    return version, artifacts[name]


def publish(candidate_dir, source_revision, repository, remote, channel="alpha", apply=False):
    """预检三分支后一次原子快进；不使用 force，不创建 tag、Release 或远程配置。"""
    if channel not in CHANNELS or not remote or remote.startswith("-"):
        raise ValueError("仅支持正式／alpha 渠道和显式远程地址")
    distributions = load_candidate(Path(candidate_dir), source_revision, repository, channel)
    with tempfile.TemporaryDirectory(prefix="awf-plugin-publish-") as temporary:
        work = Path(temporary)
        git(work, "init", "--quiet")
        refs = ["refs/heads/plugins-" + host + "-" + channel for host in HOSTS]
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
                # 远端旧声明同样是不可信输入；先验证所属渠道，再按统一版本顺序拒绝降级。
                validate_channel(old["version"], channel)
                if compare_versions(old["version"], record["version"]) >= 0:
                    raise ValueError("发布版本必须向前递增")
                # 工作流与配置工具分别版本化：工作流前进不授权组件倒退，也不授权
                # 将同一组件版本重绑不同 ZIP。旧记录从原始 artifact 名提取已知身份，
                # 不向历史 schema 追加必需字段；alpha 记录仍可按其原合同验证。
                old_native, old_digest = native_binding(old)
                new_native, new_digest = native_binding(record)
                native_order = compare_versions(old_native, new_native)
                if native_order > 0:
                    raise ValueError("原生组件版本必须向前递增或保持原包")
                if native_order == 0 and old_digest != new_digest:
                    raise ValueError("同一组件版本已绑定不同候选字节")
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
    parser.add_argument("--channel", choices=CHANNELS, required=True)
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
