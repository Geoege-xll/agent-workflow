#!/usr/bin/env python3
"""插件薄入口：校验独立组件后只调用其安全命令，绝不导入配置核心。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

# -I 保证不受当前项目或 PYTHONPATH 注入；唯一额外模块在启动器自身物理目录。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from component_store import ComponentError, PRODUCT, descriptor, installed, physical, prepare


class InputError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse 默认会回显用户传入的敏感文本；公共诊断仅返回固定错误代码。
        raise InputError("invalid_arguments")


def arguments(argv):
    parser = Parser(description="原生 Agent 配置组件安全入口", allow_abbrev=False)
    parser.add_argument("action", nargs="?", choices=("open", "status", "doctor"), default="open")
    parser.add_argument("--host", required=True, choices=("codex", "claude", "antigravity"))
    parser.add_argument("--project", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.action != "open" and (args.prepare or args.artifact is not None or args.no_browser):
        raise InputError("invalid_arguments")
    if args.artifact is not None and not args.prepare:
        raise InputError("preparation_confirmation_required")
    for path in (args.project, args.home, args.artifact):
        if path is not None and (not path.is_absolute() or ".." in path.parts):
            raise InputError("absolute_path_required")
    if args.project is not None and not args.project.is_dir():
        raise InputError("project_unavailable")
    return args


def receipt(args, data, code, state="unavailable"):
    return {"schema_version": 1, "action": getattr(args, "action", "open"), "state": state, "code": code,
            "component": {"product": PRODUCT, "version": data.get("version"), "cli_protocol": 1, "service_protocol": 2},
            "service": {"state": "unknown"}, "location": {"host": getattr(args, "host", None),
                "scope": "project" if getattr(args, "project", None) else "global",
                "project": str(args.project) if getattr(args, "project", None) else None},
            "browser": {"state": "not_requested"}, "console_url": None, "launch_file": None,
            "diagnostics": [code]}


def safe_response(raw, args, data):
    """只接受 P1 安全回执的固定结构；旧 console token URL 或任意异常输出一概不透传。"""
    try:
        value = json.loads(raw)
        expected = receipt(args, data, "")
        if (not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("action") != args.action
                or not isinstance(value.get("service"), dict) or not isinstance(value.get("browser"), dict)
                or not isinstance(value.get("diagnostics"), list)
                or value.get("component", {}).get("product") != PRODUCT
                or value["component"].get("version") != data["version"]
                or value["component"].get("cli_protocol") != 1 or value["component"].get("service_protocol") != 2
                or value.get("location") != expected["location"]):
            raise ValueError
        # 后端自身保证字段脱敏；本层仍对整个回执拒绝 token/URL 片段，防旧接口误接入。
        if any(marker in raw.lower() for marker in ("#token", "token=", "bearer ")):
            raise ValueError
        url = value.get("console_url")
        if url is not None:
            from urllib.parse import urlsplit
            parsed = urlsplit(url)
            if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or parsed.path != "/"):
                raise ValueError
        if args.action != "open" and value.get("launch_file") is not None:
            raise ValueError
        return {key: value.get(key) for key in expected}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ComponentError("invalid_component_response") from None


def run(argv, *, component_root=None, descriptor_path=None, invoke=subprocess.run):
    """测试通过显式 API 注入临时组件根；不替换 HOME、CODEX_HOME，不复制任何认证。"""
    args, data = None, {}
    try:
        args = arguments(argv)
        if sys.platform not in {"darwin", "linux"}:
            raise ComponentError("platform_paused")
        data = descriptor(descriptor_path or Path(__file__).resolve().with_name("component.json"))
        root = physical(Path(component_root) if component_root is not None else
                        Path.home() / ".local/share/agent-workflow/components/native-agent-config")
        target = installed(root, data)
        if target is None and not args.prepare:
            return receipt(args, data, "preparation_required", "preparation_required"), 2
        if target is None:
            target = prepare(root, data, args.artifact)
        command = ["bash", str(target / "scripts/agent_config.sh"), args.action, "--host", args.host,
                   "--data-dir", str(root / "state")]
        for flag, value in (("--project", args.project), ("--home", args.home)):
            if value is not None:
                command.extend((flag, str(value)))
        if args.no_browser:
            command.append("--no-browser")
        # 固定 argv、不使用 shell=True；空格和以破折号开头的项目名均作为单个绝对路径。
        result = invoke(command, capture_output=True, text=True, timeout=40)
        if len(result.stdout) > 64 * 1024:
            raise ComponentError("invalid_component_response")
        value = safe_response(result.stdout, args, data)
        if result.returncode not in {0, 1, 2, 3}:
            raise ComponentError("component_command_failed")
        # exit3 是浏览器失败但服务仍 ready，完整保留私有打开入口，绝不重启或终止服务。
        return value, result.returncode
    except InputError as error:
        return receipt(args, data, str(error)), 2
    except ComponentError as error:
        return receipt(args, data, str(error)), 1
    except (OSError, subprocess.TimeoutExpired):
        return receipt(args, data, "component_command_failed"), 1


def main():
    report, code = run(sys.argv[1:])
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
