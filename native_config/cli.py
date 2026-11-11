"""独立原生配置入口：网页优先，脚本查询与可选 stdio MCP 共用同一核心。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import webbrowser

from .contracts import HOSTS
from .server import (ConsoleServer, ROOT, configuration_identity, console_result, private_runtime_dir,
                     process_lock, read_connection, reusable_connection,
                     service_version, validate_location, write_connection)


def default_data_dir():
    """状态及恢复文件独立保存；不创建工作流安装、绑定或官方宿主配置。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "NativeAgentConfig"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "native-agent-config"


def open_console(data_dir, host="codex", project=None, *, home=None, open_browser=False):
    """只有控制台请求才启动 HTTP；MCP 初始化及模型查询不会创建连接记录。"""
    validate_location(host, project)
    data_dir = Path(data_dir).expanduser().resolve()
    from .service import ModelService
    identity = configuration_identity(ModelService(data_dir, home=home))
    version = service_version()
    directory = private_runtime_dir(data_dir)
    with process_lock(directory / "launch.lock"):
        connection = reusable_connection(directory, version, identity)
        reused = connection is not None
        if connection is None:
            command = [sys.executable, "-B", str(ROOT / "scripts" / "agent_config.py"),
                       "serve", "--data-dir", str(data_dir), "--host", host]
            if home is not None:
                command.extend(("--home", str(home)))
            if project is not None:
                command.extend(("--project", project))
            # 只拉起独立配置工具的固定入口，不接受外部命令或启动 Agent。
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    if not selector.select(timeout=8):
                        raise ValueError("控制台服务启动超时")
                    raw = child.stdout.readline(8193)
                if not raw or len(raw) > 8192:
                    raise ValueError("控制台服务未能启动")
                connection = reusable_connection(directory, version, identity)
                if connection is None:
                    raise ValueError("控制台服务启动握手失败")
            except BaseException:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
                raise
            finally:
                child.stdout.close()
    result = console_result(connection, host, project, reused=reused)
    if open_browser:
        result["browser_opened"] = bool(webbrowser.open(result["url"]))
    return result


def serve(data_dir, host="codex", project=None, *, home=None, port=0, idle_timeout=1800):
    from .service import ModelService

    validate_location(host, project)
    directory = private_runtime_dir(data_dir)
    with process_lock(directory / "service.lock", blocking=False):
        server = ConsoleServer(ModelService(data_dir=Path(data_dir), home=home), port=port)
        connection = server.connection()
        previous_handlers = {}
        stopping = False

        def stop(_signum, _frame):
            nonlocal stopping
            stopping = True

        try:
            write_connection(directory, connection)
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[signum] = signal.signal(signum, stop)
            server.timeout = 0.25
            print(json.dumps(console_result(connection, host, project), ensure_ascii=False), flush=True)
            while not stopping:
                server.handle_request()
                if idle_timeout and time.monotonic() - server.last_activity >= idle_timeout:
                    break
        finally:
            # 关闭监听并等待活跃请求的业务 finally；其目录查询组回收或原生保存结算
            # 完成后才能清理连接身份、释放当前 data_dir 的唯一服务锁。
            server.server_close()
            # 仅删除自己的记录，其他服务的数据或后继实例记录不受影响。
            try:
                current = read_connection(directory)
            except (ValueError, OSError):
                # 记录被外部编辑或替换时保持原样；退出不承担修复其他记录的职责。
                current = None
            if current is not None and current.get("instance_id") == connection["instance_id"]:
                (directory / "connection.json").unlink(missing_ok=True)
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
    return 0


def parser():
    result = argparse.ArgumentParser(description="独立三平台原生 Agent 配置服务（Python 3.11+）")
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("console", "serve", "list", "resolve", "mcp"):
        sub = commands.add_parser(command)
        sub.add_argument("--data-dir", type=Path, default=None)
        sub.add_argument("--host", choices=HOSTS, default="codex")
        sub.add_argument("--project", default=None)
        sub.add_argument("--home", type=Path, default=None, help="明确选择原生配置根；测试请使用临时目录")
        if command == "console":
            sub.add_argument("--no-browser", action="store_true")
        elif command == "serve":
            sub.add_argument("--port", type=int, default=0)
            sub.add_argument("--idle-timeout", type=int, default=1800)
        elif command == "list":
            sub.add_argument("--scope", choices=("global", "project"), default=None)
        elif command == "resolve":
            sub.add_argument("--role", required=True, help="list 返回的 opaque Agent ID")
    return result


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    try:
        validate_location(args.host, args.project)
        service_version()
        data_dir = (args.data_dir or default_data_dir()).expanduser().resolve()
        # 不改环境变量；显式 home 仅作为当前业务实例参数，由子进程固定参数传递。
        home = args.home.expanduser().absolute() if args.home is not None else None
        if args.command == "console":
            print(json.dumps(open_console(data_dir, args.host, args.project,
                                          home=home, open_browser=not args.no_browser), ensure_ascii=False), flush=True)
            return 0
        if args.command == "serve":
            if not 0 <= args.port <= 65535 or not 0 <= args.idle_timeout <= 86400:
                argument_parser.error("端口须为0至65535，空闲秒数须为0至86400")
            return serve(data_dir, args.host, args.project, home=home, port=args.port, idle_timeout=args.idle_timeout)
        from .service import ModelService
        service = ModelService(data_dir=data_dir, home=home)
        if args.command == "list":
            scope = args.scope or ("project" if args.project else "global")
            print(json.dumps(service.context(args.host, scope=scope, project=args.project), ensure_ascii=False), flush=True)
            return 0
        if args.command == "resolve":
            print(json.dumps(service.resolve_subagent(args.host, args.role, project=args.project), ensure_ascii=False), flush=True)
            return 0
        from .mcp import run_stdio
        return run_stdio(service, data_dir=data_dir, host=args.host, project=args.project, home=home)
    except (ValueError, OSError):
        # 不把异常中的项目路径、令牌、原配置或堆栈写到宿主诊断日志。
        print("原生配置服务请求失败：请检查完整配置服务包、参数、权限及现有服务版本；版本文件不可缺失。", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
