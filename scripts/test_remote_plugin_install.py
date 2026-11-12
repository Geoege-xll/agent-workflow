#!/usr/bin/env python3
"""仅在自然 HOME 的 GitHub 临时 runner 验证官方 Git 安装；不启动模型或会话。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import pwd
import re
import subprocess
import tarfile
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Geoege-xll/agent-workflow"
REMOTE = "https://github.com/" + REPOSITORY + ".git"
MARKETPLACE = "agent-workflow-alpha"
PLUGIN = "agent-workflow"
FIXTURES = ROOT / "tests/fixtures/native-install"
VERSIONS = {"codex": "0.167.0", "claude": "2.1.311", "antigravity": "1.5.6"}


def require_fresh_runner(environment):
    """先验证自然账号边界；绝不在开发机伪造 HOME、借用凭证或覆盖已有同名插件。"""
    home = Path(environment.get("HOME", "")).resolve()
    natural = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    if (environment.get("GITHUB_ACTIONS") != "true"
            or environment.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or platform.system() != "Linux" or platform.machine() != "x86_64"
            or home != natural or environment.get("HOME") != "/home/runner"):
        raise ValueError("真实安装验收只允许自然 /home/runner 的 GitHub Linux x64 临时 runner")
    forbidden = ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "GEMINI_CLI_HOME", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GOOGLE_API_KEY", "GEMINI_API_KEY")
    if any(environment.get(key) for key in forbidden):
        raise ValueError("临时安装验收不能使用自定义宿主目录或模型认证环境变量")
    if any((home / name).exists() for name in (".codex/auth.json", ".claude/.credentials.json",
                                               ".gemini/oauth_creds.json")):
        raise ValueError("临时安装验收不接受已有模型登录记录")
    if not re.fullmatch(r"[0-9a-f]{40}", environment.get("GITHUB_SHA", "")):
        raise ValueError("验收必须绑定当前 main 的完整 SHA")
    return home


def command(arguments, cwd, *, as_json=False, raw=False):
    """所有外部命令设定时限；不执行 shell，也不把宿主列表/配置原文写入最终证据。"""
    completed = subprocess.run([str(argument) for argument in arguments], cwd=cwd,
                               capture_output=True, text=not raw, timeout=180, check=True)
    if raw:
        return completed.stdout
    return json.loads(completed.stdout) if as_json else completed.stdout.strip()


def install_agy(vendor):
    """使用已只读核实的官方固定归档与 SHA512；不调用会追随 latest 的安装脚本。"""
    record = json.loads((FIXTURES / "antigravity-linux-amd64.json").read_text())
    with urllib.request.urlopen(record["url"], timeout=60) as response:
        body = response.read()
    if hashlib.sha512(body).hexdigest() != record["sha512"]:
        raise ValueError("官方 Antigravity 归档与固定 SHA512 不一致")
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
        member = archive.getmember("antigravity")
        if not member.isfile():
            raise ValueError("官方 Antigravity 归档中的预期二进制不是普通文件")
        # 只读目标成员并自行写出固定文件名，避免 tar 路径、链接或权限元数据影响 runner。
        executable = vendor / "agy"
        with archive.extractfile(member) as source:
            executable.write_bytes(source.read())
        executable.chmod(0o755)
    return executable


def installed_rows(host, payload):
    return payload["installed"] if host == "codex" else payload


def plugin_row(host, payload):
    rows = installed_rows(host, payload)
    matches = [row for row in rows if (row.get("name") == PLUGIN if host == "antigravity"
               else row.get("pluginId", row.get("id")) == PLUGIN + "@" + MARKETPLACE)]
    if len(matches) != 1:
        raise ValueError("官方列表没有唯一发现当前插件：" + host)
    return matches[0]


def validate_distribution(record, host, expected_revision, expected_version):
    """安装前先拒绝错误宿主、来源和版本，避免先安装再发现分发记录不属于本次验收。"""
    branch = "refs/heads/plugins-" + host + "-alpha"
    if (record["schema_version"] != 1 or record["managed_by"] != "agent-workflow-plugin-source-v1"
            or record["repository"] != REPOSITORY or record["host"] != host
            or record["channel"] != "alpha" or record["ref"] != branch
            or record["source_revision"] != expected_revision or record["version"] != expected_version):
        raise ValueError("Git 分发记录与本次来源/版本/宿主不一致")
    primary = "workflow/agent-workflow-" + host + "-" + expected_version + ".zip"
    if (not re.fullmatch(r"[0-9a-f]{64}", record["candidate_sha256"])
            or not re.fullmatch(r"[0-9a-f]{64}", record["source_tree_sha256"])
            or len(record["artifacts_sha256"]) != 7
            or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in record["artifacts_sha256"].values())
            or record["plugin_zip_sha256"] != record["artifacts_sha256"][primary]):
        raise ValueError("Git 分发记录缺少七候选摘要或宿主主 ZIP 摘要绑定")


def verify_installed(root, record, host, expected_revision, expected_version):
    """以分发提交的完整文件摘要核对真实安装缓存；不修补、重打包或写入缓存。"""
    validate_distribution(record, host, expected_revision, expected_version)
    prefix = "" if host == "antigravity" else "plugins/agent-workflow/"
    files = {name[len(prefix):]: row for name, row in record["files"].items()
             if name.startswith(prefix) and name != "distribution.json"}
    if not files or "sources.json" not in files:
        raise ValueError("Git 分发记录缺少插件来源闭包")
    actual = {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}
    # AGY 从整个分发根安装，可能保留额外的只读分发记录；不把它误计入原始插件 ZIP。
    actual.pop("distribution.json", None)
    if set(actual) != set(files):
        raise ValueError("官方安装缓存文件集合与分发记录不一致：" + host)
    for name, item in files.items():
        path = actual[name]
        if (path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
                or bool(path.stat().st_mode & 0o111) != (item["mode"] == "100755")):
            raise ValueError("官方安装缓存字节与分发记录不一致：" + host + "/" + name)
    sources = json.loads((root / "sources.json").read_text())
    if sources["host"] != host or sources["plugin_version"] != expected_version:
        raise ValueError("已安装 sources.json 宿主/版本不一致")
    return {"files": len(files), "source_revision": expected_revision, "version": expected_version,
            "sources_sha256": hashlib.sha256((root / "sources.json").read_bytes()).hexdigest()}


def smoke(vendor, output):
    home = require_fresh_runner(os.environ)
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    vendor = vendor.resolve(strict=True)
    output = output.absolute()
    if not vendor.is_relative_to(runner_temp) or not output.is_relative_to(runner_temp):
        raise ValueError("官方客户端与证据必须位于本次 runner 临时目录")
    version = (ROOT / "product/PLUGIN_VERSION").read_text().strip()
    revision = os.environ["GITHUB_SHA"]
    clients = {"codex": vendor / "node_modules/.bin/codex", "claude": vendor / "node_modules/.bin/claude",
               "antigravity": install_agy(vendor)}
    evidence = {"status": "INSTALL_DISCOVERY_BYTES_VERIFIED", "verification_revision": revision,
                "version": version, "runtime_verified": False, "model_sessions_started": 0, "hosts": {}}
    published_revision = None
    candidate_binding = None
    with tempfile.TemporaryDirectory(prefix="awf-official-install-", dir=runner_temp) as temporary:
        work = Path(temporary)
        for host, client in clients.items():
            cli_version = command([client, "--version"], work)
            if not re.search(r"(?<![0-9.])" + re.escape(VERSIONS[host]) + r"(?![0-9.])", cli_version):
                raise ValueError("官方客户端版本与固定测试版本不符：" + host)
            before = command([client, "plugin", "list", "--json"], work, as_json=True)
            if any(PLUGIN in str(row.get("name", row.get("id", row.get("pluginId", ""))))
                   for row in installed_rows(host, before)):
                raise ValueError("临时 runner 已有同名插件；拒绝覆盖：" + host)
            # 先读取服务器分发提交；安装后再 fetch 一次，拒绝验收期间分支移动导致的混源。
            reference = work / host
            reference.mkdir()
            command(["git", "init", "--quiet", reference], work)
            branch = "refs/heads/plugins-" + host + "-alpha"
            command(["git", "fetch", "--quiet", "--depth=1", REMOTE, branch], reference)
            commit = command(["git", "rev-parse", "FETCH_HEAD"], reference)
            record_body = command(["git", "show", commit + ":distribution.json"], reference)
            record = json.loads(record_body)
            # 发布器会对同版本同载荷保留旧来源提交；文档更新不能强迫改写已发布分支。
            # 三个宿主仍必须绑定同一个完整来源 SHA，且安装版本必须等于本次验证源码版本。
            source_revision = record["source_revision"]
            if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
                raise ValueError("Git 分发记录不是完整来源 SHA")
            if published_revision is None:
                published_revision = source_revision
                evidence["source_revision"] = source_revision
            if source_revision != published_revision:
                raise ValueError("三个宿主的 Git 分发来源 SHA 不一致")
            validate_distribution(record, host, source_revision, version)
            binding = (record["source_tree_sha256"], record["candidate_sha256"], record["artifacts_sha256"])
            if candidate_binding is None:
                candidate_binding = binding
            if binding != candidate_binding:
                raise ValueError("三个宿主并非来自同一个七附件候选")
            # 比较分发记录与已 fetch 的提交本身，记录不能只约束客户端复制后的缓存。
            names = command(["git", "ls-tree", "-r", "--name-only", "-z", commit], reference).split("\0")
            if set(filter(None, names)) != set(record["files"]) | {"distribution.json"}:
                raise ValueError("远程 Git 文件闭包与分发记录不一致：" + host)
            for name, item in record["files"].items():
                body = command(["git", "show", commit + ":" + name], reference, raw=True)
                if hashlib.sha256(body).hexdigest() != item["sha256"]:
                    raise ValueError("远程 Git 文件摘要与分发记录不一致：" + host)
            if host in {"codex", "claude"}:
                source = REMOTE if host == "codex" else REMOTE + "#plugins-claude-alpha"
                arguments = [client, "plugin", "marketplace", "add", source]
                if host == "codex":
                    arguments.extend(["--ref", "plugins-codex-alpha"])
                command(arguments + ["--json"], work, as_json=True)
                install = [client, "plugin", "add" if host == "codex" else "install", PLUGIN + "@" + MARKETPLACE]
                if host == "claude":
                    install.extend(["--scope", "user"])
                result = command(install + ["--json"], work, as_json=True)
            else:
                command([client, "plugin", "install", "https://github.com/" + REPOSITORY + "/tree/plugins-antigravity-alpha"], work)
                command([client, "plugin", "enable", PLUGIN], work)
            after = command([client, "plugin", "list", "--json"], work, as_json=True)
            row = plugin_row(host, after)
            if row.get("version") != version or not row.get("enabled"):
                raise ValueError("官方宿主没有发现并启用预期版本：" + host)
            installed = Path(result["installedPath"] if host == "codex" else
                             row["installPath"] if host == "claude" else row["path"]).resolve(strict=True)
            if not installed.is_relative_to(home):
                raise ValueError("官方安装结果不在自然 runner HOME 中：" + host)
            detail = verify_installed(installed, record, host, source_revision, version)
            command(["git", "fetch", "--quiet", "--depth=1", REMOTE, branch], reference)
            if command(["git", "rev-parse", "FETCH_HEAD"], reference) != commit:
                raise ValueError("验收期间 Git 分发分支移动；本轮证据无效")
            evidence["hosts"][host] = {**detail, "cli_version": VERSIONS[host], "distribution_commit": commit,
                                       "native_list_discovered": True, "enabled": True}
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    smoke(arguments.vendor_dir, arguments.output)


if __name__ == "__main__":
    main()
