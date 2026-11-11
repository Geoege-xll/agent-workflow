"""标准输入输出 MCP；只提供模型偏好查询、派发参数解析及控制台入口。

协议依据 MCP 2025-11-25 的 lifecycle/transports/tools：每行一个 UTF-8
JSON-RPC 消息，stdout 绝不混入诊断；关闭 stdin 即结束当前宿主子进程。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from .contracts import HOSTS
from .server import parse_json, service_error, service_version, validate_location

VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_LINE = 131072
MAX_OUTPUT = 1048576


class RpcError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def tool_definitions():
    """固定工具白名单；不存在写文件、任意命令、Agent runner 或批准工具。"""
    common = {"host": {"type": "string", "enum": list(HOSTS)},
              "project": {"type": "string", "maxLength": 4096,
                          "description": "可选绝对项目目录，省略时使用启动上下文"}}
    definitions = []
    for name, description, extra, required in (
        ("get_model_preferences", "查询模型偏好、逐字段来源与能力；不发现模型目录、不保存配置。",
         {"scope": {"type": "string", "enum": ["global", "project"]}}, []),
        ("resolve_subagent", "读取发现清单中原生 Agent 的设置和已观察调用能力；不推断宿主未提供的调用字段，保存不代表运行生效。",
         {"role": {"type": "string", "maxLength": 200, "description": "get_model_preferences 返回的 opaque Agent ID"}}, ["role"]),
        ("open_console", "按需启动或复用独立原生 Agent 配置页面；不启动 Agent。",
         {"open_browser": {"type": "boolean", "default": False}}, []),
    ):
        definitions.append({"name": name, "description": description,
                            "inputSchema": {"type": "object", "properties": {**common, **extra},
                                            "required": required, "additionalProperties": False},
                            "annotations": {"readOnlyHint": name != "open_console",
                                            "destructiveHint": False, "openWorldHint": False}})
    return definitions


class McpSession:
    def __init__(self, service, *, data_dir: Path, host="codex", project=None,
                 home=None, version=None, console_opener=None):
        self.service = service
        self.data_dir = Path(data_dir)
        self.host, self.project = validate_location(host, project)
        self.home = home
        self.version = version or service_version()
        self.initialized = False
        self.ready = False
        if console_opener is None:
            from .cli import open_console
            console_opener = open_console
        self.console_opener = console_opener

    def handle(self, message):
        """通知无响应；协议错误与工具执行错误分层，避免异常破坏后续会话。"""
        request_id = None
        try:
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise RpcError(-32600, "Invalid Request")
            request_id = message.get("id")
            if "id" in message and (request_id is None or type(request_id) not in {int, str}
                                    or (isinstance(request_id, str) and len(request_id) > 200)):
                request_id = None
                raise RpcError(-32600, "Invalid Request")
            method = message.get("method")
            if not isinstance(method, str) or len(method) > 200:
                raise RpcError(-32600, "Invalid Request")
            if "id" not in message:
                if method == "notifications/initialized" and self.initialized:
                    self.ready = True
                # 未实现的通知（包括取消/进度）不产生回应；当前工具同步且无后台任务。
                return None
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise RpcError(-32602, "Invalid params")
            if method == "ping":
                result = {}
            elif method == "initialize":
                if self.initialized:
                    raise RpcError(-32600, "Already initialized")
                if (not isinstance(params.get("protocolVersion"), str)
                        or len(params["protocolVersion"]) > 100
                        or not isinstance(params.get("capabilities"), dict)
                        or not isinstance(params.get("clientInfo"), dict)
                        or not isinstance(params["clientInfo"].get("name"), str)
                        or not isinstance(params["clientInfo"].get("version"), str)):
                    raise RpcError(-32602, "Invalid initialize params")
                requested = params["protocolVersion"]
                self.initialized = True
                result = {"protocolVersion": requested if requested in VERSIONS else VERSIONS[0],
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "native-agent-config", "version": self.version},
                          "instructions": ("Inspect native Agent definitions and their observed configuration capabilities. "
                                           "Use opaque IDs returned by get_model_preferences. This optional MCP does not "
                                           "run Agents or enforce a workflow. Saved native files do not prove that the "
                                           "current official-host session has loaded or executed them.")}
            elif method in {"tools/list", "tools/call"}:
                if not self.ready:
                    raise RpcError(-32002, "Server not initialized")
                if method == "tools/list":
                    if (set(params) - {"cursor", "_meta"} or params.get("cursor") is not None
                            or ("_meta" in params and not isinstance(params["_meta"], dict))):
                        raise RpcError(-32602, "Invalid cursor")
                    result = {"tools": tool_definitions()}
                else:
                    result = self._call(params)
            else:
                raise RpcError(-32601, "Method not found")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": exc.code, "message": exc.message}}
        except Exception:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32603, "message": "Internal error"}}

    def _call(self, params):
        if set(params) - {"name", "arguments", "_meta"}:
            raise RpcError(-32602, "Invalid tool call")
        name = params.get("name")
        definitions = {tool["name"]: tool for tool in tool_definitions()}
        if not isinstance(name, str) or name not in definitions:
            raise RpcError(-32602, "Unknown tool")
        arguments = params.get("arguments", {})
        schema = definitions[name]["inputSchema"]
        if (not isinstance(arguments, dict) or set(arguments) - set(schema["properties"])
                or any(key not in arguments for key in schema["required"])):
            raise RpcError(-32602, "Invalid tool arguments")
        try:
            host, project = validate_location(arguments.get("host", self.host),
                                              arguments.get("project", self.project))
            if name == "get_model_preferences":
                scope = arguments.get("scope", "project" if project else "global")
                if scope not in {"global", "project"} or (scope == "project" and project is None):
                    raise ValueError("无效范围")
            elif name == "resolve_subagent":
                role = arguments["role"]
                if not isinstance(role, str) or not 1 <= len(role) <= 200:
                    raise ValueError("无效角色")
            elif type(arguments.get("open_browser", False)) is not bool:
                raise ValueError("无效浏览器选项")
        except (ValueError, TypeError):
            raise RpcError(-32602, "Invalid tool arguments") from None
        try:
            if name == "get_model_preferences":
                result = self.service.context(host, scope=scope, project=project)
            elif name == "resolve_subagent":
                result = self.service.resolve_subagent(host, role, project=project)
            else:
                result = self.console_opener(self.data_dir, host, project, home=self.home,
                                             open_browser=arguments.get("open_browser", False))
            # 同时提供 text 和 structuredContent，兼容旧客户端及结构化消费者。
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, allow_nan=False)}],
                    "structuredContent": result, "isError": False}
        except ValueError as exc:
            _, result = service_error(exc)
        except Exception:
            result = {"error": {"code": "internal_error", "message": "本地模型服务暂时无法完成请求"}}
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result, "isError": True}


def run_stdio(service, *, data_dir, host="codex", project=None, input_stream=None,
              output_stream=None, home=None, version=None, console_opener=None):
    """逐条有界读取；超长行排空后报告错误，后续完整消息仍可继续处理。"""
    source = input_stream if input_stream is not None else sys.stdin.buffer
    destination = output_stream if output_stream is not None else sys.stdout.buffer
    session = McpSession(service, data_dir=data_dir, host=host, project=project,
                         home=home, version=version, console_opener=console_opener)
    try:
        while True:
            raw = source.readline(MAX_LINE + 1)
            if not raw:
                return 0
            if len(raw) > MAX_LINE:
                while not raw.endswith(b"\n"):
                    raw = source.readline(MAX_LINE + 1)
                    if not raw:
                        break
                response = {"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32600, "message": "Message exceeds size limit"}}
            else:
                try:
                    message = parse_json(raw)
                except ValueError:
                    response = {"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32700, "message": "Parse error"}}
                else:
                    response = session.handle(message)
            if response is not None:
                encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
                if len(encoded) > MAX_OUTPUT:
                    encoded = json.dumps({"jsonrpc": "2.0", "id": response.get("id"),
                                          "error": {"code": -32603, "message": "Response exceeds size limit"}}).encode("utf-8")
                destination.write(encoded + b"\n")
                destination.flush()
    except (BrokenPipeError, ConnectionResetError):
        return 0
