#!/usr/bin/env python3
"""固定官方现代Web发布包的只读查询入口；不安装、不更新、不发送遥测。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.skills.selected_skills import ROOT, VENDOR, snapshot

PREFIX = VENDOR + "/modern-web-guidance/runtime/skills/modern-web-guidance/"
ENTRY = PREFIX + "modern-web.mjs"


def node_runtime() -> tuple[str | None, str | None, bool]:
    """仅查询已有Node；现代Web要求22，与Playwright自身的20门槛独立。"""
    node, version = shutil.which("node"), None
    if node:
        try:
            version = subprocess.run([node, "--version"], env=environment(), capture_output=True,
                                     text=True, timeout=5, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version or "")
    return node, version, bool(match and int(match[1]) >= 22)


def environment() -> dict[str, str]:
    """禁止上游遥测及文件日志，同时去掉可注入未锁代码的Node启动选项。

    查询使用包内模型和指南，无网络更新；保留cwd供上游只读遵守项目.mwgrc。
    不能通过该适配器调用会修改配置、启动npx或安装的上游其他命令。
    """
    result = {k: v for k, v in os.environ.items() if k not in {"NODE_OPTIONS", "NODE_PATH"}}
    result.update(DISABLE_TELEMETRY="1", ENABLE_FILE_LOGGING="false", NO_UPDATE_NOTIFIER="1")
    return result


def run(arguments: list[str], root: Path = ROOT) -> int:
    """仅放行本任务的三种查询，固定入口、语料版本和30秒上限；失败保留原退出码。"""
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    lock, files = snapshot(root)
    node, version, ready = node_runtime()
    if arguments == ["doctor"]:
        print(json.dumps({"integrity": "verified", "package": lock["dependencies"]["modern-web-guidance"]["package"],
                          "node": {"path": node, "version": version, "ready": ready},
                          "queries_local_only": True, "telemetry_enabled": False,
                          "query_executed": False, "host_adoption_verified": False}, sort_keys=True))
        return 0
    skill_version = files[PREFIX + "skill-version.txt"].decode("utf-8").strip()
    if "--skill-version" in arguments:
        index = arguments.index("--skill-version")
        if arguments[index:] != ["--skill-version", skill_version]:
            raise ValueError("--skill-version must match the fixed bundled corpus")
        arguments = arguments[:index]
    if (not arguments or arguments[0] not in {"search", "retrieve", "list"}
            or len(arguments) != (1 if arguments[0] == "list" else 2)
            or any(not value or value.startswith("-") or len(value) > 2000 or any(ord(c) < 32 for c in value)
                   for value in arguments)):
        raise ValueError("only search <query>, retrieve <ids>, and list are supported")
    if not ready:
        raise ValueError("xy-web-guidance requires an existing Node >=22; no runtime is installed automatically")
    try:
        return subprocess.run([node, str(root / ENTRY), *arguments, "--skill-version", skill_version],
                              env=environment(), timeout=30, check=False).returncode
    except subprocess.TimeoutExpired as exc:
        raise ValueError("fixed modern Web local query timed out after 30 seconds; no network fallback was attempted") from exc


if __name__ == "__main__":
    try:
        raise SystemExit(run(sys.argv[1:]))
    except (ValueError, OSError) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        raise SystemExit(2)
