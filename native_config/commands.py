"""维护启动器使用的安全 JSON 命令；鉴权材料只进入浏览器与私有链接文件。"""

from __future__ import annotations

import hashlib
import html
import importlib.util
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys
import webbrowser

from .server import (ConsoleLifecycleError, PROTOCOL_VERSION, ROOT, configuration_identity,
                     parse_json, read_connection, reusable_connection, service_version,
                     validate_location)

CLI_PROTOCOL = 1
PRODUCT = "native-agent-config"
REQUIRED_FILES = {"native_config/VERSION", "native_config/cli.py", "native_config/commands.py",
                  "native_config/server.py", "native_config/service.py", "native_config/web/index.html",
                  "native_config/web/console.js", "native_config/web/console.css",
                  "scripts/agent_config.py", "scripts/agent_config.sh", "scripts/python_runtime.sh"}


def _diagnostic(code, message, severity="error"):
    """诊断文字来自固定模板，绝不拼入异常、连接正文或配置正文。"""
    return {"code": code, "severity": severity, "message": message}


def _regular_file(root, relative, *, limit=16 * 1048576):
    """只读取本组件内有界普通文件；来源检查不借软链读取组件外文件。"""
    path = root / relative
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("组件来源包含符号链接")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("组件文件类型或大小无效")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(limit + 1)
        if len(body) > limit:
            raise ValueError("组件文件超限")
        return body
    finally:
        os.close(descriptor)


def _component(action):
    """doctor 核对发行 BUILD；源码树诚实标明开发来源，不能冒充已校验发行包。"""
    component = {"product": PRODUCT, "version": None, "cli_protocol": CLI_PROTOCOL,
                 "service_protocol": PROTOCOL_VERSION, "root": str(ROOT), "integrity": "unchecked",
                 "source": "unknown"}
    diagnostics = []
    try:
        component["version"] = service_version()
        for relative in REQUIRED_FILES:
            _regular_file(ROOT, relative)
        if sys.version_info < (3, 11) or importlib.util.find_spec("tomllib") is None:
            raise ValueError("运行依赖缺失")
        manifest = ROOT / "BUILD.json"
        if not manifest.exists() and not manifest.is_symlink():
            if not (ROOT / "packaging/build_agent_config.py").is_file():
                raise ValueError("组件缺少来源清单")
            component.update(source="development_source", integrity="development_source")
            diagnostics.append(_diagnostic("development_source", "当前运行开发源码；未提供发行 BUILD 完整性证明。", "info"))
        else:
            component["source"] = "release"
            if action == "doctor":
                record = parse_json(_regular_file(ROOT, "BUILD.json", limit=65536))
                if (not isinstance(record, dict) or record.get("name") != PRODUCT
                        or record.get("version") != component["version"]
                        or record.get("third_party_dependencies") != []
                        or not isinstance(record.get("files"), dict)
                        or not REQUIRED_FILES <= set(record["files"]) or len(record["files"]) > 256):
                    raise ValueError("组件来源清单无效")
                total = 0
                for relative, digest in record["files"].items():
                    if (not isinstance(relative, str) or not relative or "\\" in relative
                            or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts
                            or PurePosixPath(relative).as_posix() != relative
                            or not isinstance(digest, str) or len(digest) != 64):
                        raise ValueError("组件来源路径或摘要无效")
                    body = _regular_file(ROOT, relative)
                    total += len(body)
                    if total > 32 * 1048576 or hashlib.sha256(body).hexdigest() != digest:
                        raise ValueError("组件摘要不匹配")
                # 发行目录的实际闭包必须等于 BUILD；忽略 Python 可再生字节码，
                # 其余未登记文件不能被错误地报告为完整来源。
                actual = set()
                for path in ROOT.rglob("*"):
                    if "__pycache__" in path.parts:
                        continue
                    if path.is_symlink():
                        raise ValueError("发行目录包含符号链接")
                    if path.is_file():
                        actual.add(path.relative_to(ROOT).as_posix())
                        if len(actual) > 257:
                            raise ValueError("发行目录文件超限")
                if actual != set(record["files"]) | {"BUILD.json"}:
                    raise ValueError("组件来源闭包不匹配")
                component["integrity"] = "verified"
            else:
                component["integrity"] = "not_checked"
        if action == "doctor":
            diagnostics.append(_diagnostic("dependencies_available", "Python 3.11+ 标准库依赖可用；未运行宿主命令。", "info"))
    except (OSError, ValueError, UnicodeError):
        component["integrity"] = "invalid"
        diagnostics.append(_diagnostic("invalid_component", "独立组件的版本、文件、依赖或发行来源校验失败。"))
    return component, diagnostics


def _runtime_state(data_dir, version, identity, *, probe=True):
    """纯读取连接目录和认证健康端点；不修复权限、不创建锁、不清理坏记录。"""
    directory = data_dir / "console"
    try:
        if directory.is_symlink():
            raise ValueError("连接目录不能是软链")
        if not directory.exists():
            return "stopped", None
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("连接目录不私有")
        record = read_connection(directory)
        if record is None:
            return "stopped", None
        if not probe:
            # open 在启动锁内做唯一一次真实健康握手；这里仅拒绝坏记录和身份冲突，
            # 避免锁外健康读取另占一段启动预算，也避免把尚未验证的记录宣称 ready。
            if record.get("protocol_version") != PROTOCOL_VERSION or record.get("service_version") != version:
                return "incompatible_service", None
            if record.get("configuration_identity") != identity:
                return "configuration_conflict", None
            return "recorded", None
        connection = reusable_connection(directory, version, identity)
        return ("ready", connection) if connection is not None else ("unreachable", None)
    except ConsoleLifecycleError as exc:
        return exc.code, None
    except (OSError, ValueError):
        return "invalid_record", None


def _private_launch_file(data_dir, authenticated_url):
    """在已由 open 建立的 0700 目录写 0600 链接，鉴权片段不进入公共回执。"""
    directory = data_dir / "console"
    path = directory / ("launch-" + secrets.token_hex(12) + ".html")
    # 不自动跳转：浏览器直接打开原认证 URL；失败时用户可点本地文件内的链接。
    # CSP 禁止脚本和外部资源，no-referrer 防止片段以外的信息被外链泄漏。
    body = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'">'
            '<meta name="referrer" content="no-referrer"><title>原生配置控制台</title>'
            '<p><a rel="noreferrer" href="' + html.escape(authenticated_url, quote=True) + '">'
            '打开本机原生 Agent 配置控制台</a></p></html>')
    # 用目录描述符固定私有父目录，再以 dir_fd 创建文件。若另一个进程在
    # 服务握手后把 console 路径换成软链，不能把认证链接写到替代目录中。
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory_fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("私有链接目录权限无效")
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory_fd)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            os.unlink(path.name, dir_fd=directory_fd)
            raise
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)
    return str(path)


def execute(action, data_dir, host="codex", project=None, *, home=None, no_browser=False):
    """返回安全回执及退出码：0 正常，1 服务/组件失败，2 参数错误，3 浏览器失败。"""
    component, diagnostics = _component(action)
    result = {"schema_version": 1, "action": action, "state": "error", "code": "invalid_component",
              "component": component, "service": {"state": "unknown", "reused": False},
              "location": {"host": host, "scope": "project" if project is not None else "global", "project": project},
              "browser": {"state": "not_requested", "opened": False}, "console_url": None,
              "launch_file": None, "diagnostics": diagnostics}
    if component["integrity"] == "invalid":
        return result, 1
    try:
        validate_location(host, project)
        data_dir = Path(data_dir).expanduser().resolve()
        home = Path(home).expanduser().absolute() if home is not None else None
        from .service import ModelService
        service = ModelService(data_dir, home=home)
        identity = configuration_identity(service)
        if project is not None and not Path(project).is_dir():
            result["diagnostics"].append(_diagnostic("project_unavailable", "指定项目目录当前不可用。", "warning"))
        if action == "doctor":
            # 只检查范围是否存在，不调用 discover/context/catalog 或宿主版本探测。
            root = service.host_roots[host]
            result["diagnostics"].append(_diagnostic("configuration_scope", "已选择项目级原生定义范围。" if project else "已选择用户级原生定义范围。", "info"))
            if not root.is_dir():
                result["diagnostics"].append(_diagnostic("host_root_missing", "所选宿主的用户配置目录尚不存在。", "info"))
    except (OSError, ValueError, TypeError):
        result.update(state="error", code="invalid_arguments")
        result["diagnostics"].append(_diagnostic("invalid_arguments", "宿主或配置范围参数无效；项目须为绝对路径。"))
        return result, 2
    state, connection = _runtime_state(data_dir, component["version"], identity, probe=action != "open")
    result.update(state=state, code=state)
    result["service"]["state"] = state
    if action != "open":
        if connection is not None:
            result["console_url"] = f"http://127.0.0.1:{connection['port']}/"
            result["service"].update(protocol_version=connection["protocol_version"], version=connection["service_version"])
        if state not in {"ready", "stopped"}:
            result["diagnostics"].append(_diagnostic(state, "现有连接记录未通过安全复用校验；只读检查未改动记录或服务。"))
        return result, 0 if state in {"ready", "stopped"} else 1
    if state not in {"ready", "recorded", "stopped", "unreachable"}:
        result["diagnostics"].append(_diagnostic(state, "现有连接记录或服务不兼容；未终止旧服务。"))
        return result, 1
    try:
        from .cli import open_console
        opened = open_console(data_dir, host, project, home=home, open_browser=False)
        result.update(state="ready", code="ready", console_url=opened["url"].split("#", 1)[0])
        result["service"].update(state="ready", reused=opened["reused"],
                                  protocol_version=opened["protocol_version"], version=opened["service_version"])
    except (OSError, ValueError) as exc:
        # 旧 console/MCP 继续保留自身接口，只有此维护接口过滤掉所有原异常正文。
        code = getattr(exc, "code", "startup_failed")
        if code not in {"launch_timeout", "startup_failed", "handshake_failed", "service_busy", "incompatible_service", "configuration_conflict"}:
            code = "startup_failed"
        result.update(state="error", code=code)
        result["service"]["state"] = "error"
        result["diagnostics"].append(_diagnostic(code, "控制台启动或复用失败；未终止既有服务。"))
        return result, 1
    try:
        result["launch_file"] = _private_launch_file(data_dir, opened["url"])
    except (OSError, ValueError):
        result["code"] = "launch_file_failed"
        result["diagnostics"].append(_diagnostic("launch_file_failed", "服务已就绪，但无法创建私有打开文件；可修复状态目录权限后重试。"))
        return result, 1
    if not no_browser:
        try:
            browser_opened = bool(webbrowser.open(opened["url"]))
        except Exception:
            browser_opened = False
        result["browser"] = {"state": "opened" if browser_opened else "failed", "opened": browser_opened}
        if not browser_opened:
            result["code"] = "browser_failed"
            result["diagnostics"].append(_diagnostic("browser_failed", "浏览器未能打开；服务保留就绪，可打开私有 HTML 文件。", "warning"))
            return result, 3
    return result, 0
