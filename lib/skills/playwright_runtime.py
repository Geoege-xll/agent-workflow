#!/usr/bin/env python3
"""固定官方Playwright CLI的薄启动与只读诊断；不安装Node或全局npm包。"""
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
from lib.skills.selected_skills import snapshot, VENDOR

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = VENDOR + "/playwright-cli/runtime/node_modules/"
ENTRY = RUNTIME + "@playwright/cli/playwright-cli.js"


def node_runtime() -> tuple[str | None, str | None, bool]:
    """仅查询现有Node的版本；找不到或过旧就报告，不改PATH、不下载运行时。"""
    node = shutil.which("node")
    version = None
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version or "")
    return node, version, bool(match and int(match[1]) >= 20)


def environment() -> dict[str, str]:
    """禁止隐式npm更新查询和浏览器GC，保留用户明确选择的标准浏览器cache。"""
    return {**os.environ, "NO_UPDATE_NOTIFIER": "1", "PLAYWRIGHT_SKIP_BROWSER_GC": "1"}


def doctor(root: Path = ROOT) -> dict:
    """区分CLI完整性、Node和浏览器准备；只调用固定包的路径解析API，不启动浏览器。

    本地文件存在只支持available判断，不能据此冒称宿主授权、系统依赖或真实交互成功。
    浏览器是否真正可用必须由当前任务的命名会话open/snapshot/close证据支持。
    """
    lock, _ = snapshot(root)
    node, version, ready = node_runtime()
    result = {"integrity": "verified", "node": {"path": node, "version": version, "ready": ready},
              "cli": {"entry": str(root / ENTRY), "version": next(p["version"] for p in lock["dependencies"]["playwright-cli"]["packages"] if p["name"] == "@playwright/cli"), "ready": ready},
              "browser": {"ready": False, "matching_executable_present": False, "runtime_verified": False},
              "host_authorization": "task_and_host_permission_required", "upstream_browser_launched": False}
    if ready:
        # 绝对require路径使用固定core；不依赖用户全局playwright或旧revision目录猜测。
        script = "const p=require(process.argv[1]);const fs=require('fs');const e=p.chromium.executablePath();console.log(JSON.stringify({path:e,matching_executable_present:fs.existsSync(e)}));"
        probe = subprocess.run([node, "-e", script, str(root / (RUNTIME + "playwright-core"))], env=environment(), capture_output=True, text=True, timeout=10)
        if probe.returncode == 0:
            result["browser"].update(json.loads(probe.stdout))
        else:
            result["browser"]["diagnostic_error"] = probe.stderr.strip()
    return result


def run(arguments: list[str], root: Path = ROOT) -> int:
    """固定入口替换当前进程，argv、cwd、stdio、信号和退出码由原版Node进程接管。"""
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    if arguments == ["doctor"]:
        print(json.dumps(doctor(root), ensure_ascii=False, sort_keys=True))
        return 0
    snapshot(root)
    node, _, ready = node_runtime()
    if not ready:
        raise ValueError("xy-playwright requires an existing Node >=20; no runtime is installed automatically")
    os.execve(node, [node, str(root / ENTRY), *arguments], environment())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run(sys.argv[1:]))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        raise SystemExit(2)
