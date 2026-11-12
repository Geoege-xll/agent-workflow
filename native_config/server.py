"""只面向本机浏览器的 HTTP 传输；业务规则由 ModelService 统一处理。"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
from socketserver import TCPServer
import stat
import threading
import time
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from .contracts import HOSTS

PROTOCOL_VERSION = 2
MAX_BODY = 65536
MAX_RESPONSE = 8 * 1048576
ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = Path(__file__).resolve().parent / "web"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def service_version() -> str:
    """发行版本必须来自包内唯一版本源，缺文件不能冒充兼容版本。"""
    try:
        version = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("独立配置服务版本文件缺失，请使用完整配置服务包") from exc
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("独立配置服务版本文件无效")
    return version


def configuration_identity(service) -> str:
    """服务复用同时绑定配置根；同一状态目录不能串用不同测试 home 或宿主根。"""
    home = str(getattr(service, "home", Path.home()))
    roots = {key: str(value) for key, value in getattr(service, "host_roots", {}).items()}
    material = json.dumps({"home": home, "roots": roots}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def service_error(exc):
    """只传递核心定义的恢复字段，不把原始异常正文、文件正文或令牌拼进响应。"""
    code = getattr(exc, "code", "invalid_request")
    if code == "partial_failure":
        result = {"saved": False, "partial_failure": True,
                  "error": {"code": code, "message": "部分原生文件保存未完成，请检查逐项结果及恢复文件"}}
        payload = getattr(exc, "result", {})
        for key in ("results", "recovery", "cleanup_pending", "effect", "published"):
            if isinstance(payload, dict) and key in payload:
                result[key] = payload[key]
            elif hasattr(exc, key):
                result[key] = getattr(exc, key)
        # 命名空间曾被改动与曾出现可见性空隙是核心提供的独立事实，不能从
        # published、逐项状态或 partial_failure 推断。仅透传实际存在的 bool，
        # 保留明确 False；缺失或类型不符时不补默认值，也不把字符串转成真值。
        for key in ("namespace_touched", "temporary_visibility_gap"):
            value = payload[key] if isinstance(payload, dict) and key in payload else getattr(exc, key, None)
            if type(value) is bool:
                result[key] = value
        return 409, result
    if code == "conflict":
        return 409, {"error": {"code": code, "message": "原生配置已变化，请重新读取并预览"}}
    if code not in {"invalid_request", "unsupported_format"}:
        code = "invalid_request"
    return 400, {"error": {"code": code, "message": "请求或原生配置无效，请检查输入"}}


def parse_json(raw: bytes):
    """拒绝重复键、非有限数字和过深结构，防止不同层对同一输入产生歧义。"""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("重复 JSON 字段")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("无效 JSON 数字")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=invalid_constant)
        pending = [(value, 0)]
        count = 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if depth > 24 or count > 4096:
                raise ValueError("JSON 结构超限")
            if isinstance(item, dict):
                for key in item:
                    key.encode("utf-8", errors="strict")
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
            elif isinstance(item, str):
                item.encode("utf-8", errors="strict")
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("无效 JSON 数字")
        return value
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("无效 JSON") from exc


def validate_location(host, project=None):
    """传输入口仅接受已知宿主和绝对项目路径；项目是否可用交给业务服务。"""
    if not isinstance(host, str) or host not in HOSTS:
        raise ValueError("未知宿主")
    if project is not None:
        if (not isinstance(project, str) or len(project) > 4096 or "\x00" in project
                or not Path(project).is_absolute() or ".." in Path(project).parts):
            raise ValueError("项目路径必须为不含上级跳转的绝对路径")
    return host, project


class RequestError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


class ConsoleServer(ThreadingHTTPServer):
    """限制并发连接，并串行进入同一个业务对象，避免预览缓存的并发竞态。"""
    # 业务请求可能拥有目录查询进程组或正在写原生定义；退出必须等待其 finally。
    # 不能依赖 daemon 线程随主进程消失，否则查询组回收和保存收尾会被截断。
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, service, *, port=0, token=None, version=None, web_root=None):
        self.service = service
        self.configuration_identity = configuration_identity(service)
        self.token = token or secrets.token_urlsafe(32)
        self.version = version or service_version()
        self.instance_id = secrets.token_hex(16)
        self.web_root = Path(web_root) if web_root else WEB_ROOT
        self.service_lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.request_states = {}
        self.closing = False
        self.slots = threading.BoundedSemaphore(16)
        self.last_activity = time.monotonic()
        super().__init__(("127.0.0.1", port), ConsoleHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def server_bind(self):
        """绑定固定数字回环地址，不为未使用的主机名依赖系统反向 DNS。"""
        # HTTPServer.server_bind 在真实 bind 后额外调用 socket.getfqdn，后者
        # 会进入 gethostbyaddr；系统解析器的等待不受 CLI 启动/健康握手预算约束。
        # 本服务的监听、Origin 校验、连接记录和健康请求都只使用 127.0.0.1，
        # 因此直接复用 TCPServer 的真实绑定与端口分配，再记录实际数字地址。
        # 不修改全局解析器，不提前宣布就绪；CLI 仍在写连接记录后输出启动收据。
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            request.settimeout(5)
            with self.request_lock:
                self.request_states[request] = "reading"
            super().process_request(request, client_address)
        except BaseException:
            with self.request_lock:
                self.request_states.pop(request, None)
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.request_lock:
                self.request_states.pop(request, None)
            self.slots.release()

    @contextmanager
    def business_request(self, connection):
        """只让已进入业务的请求在关闭时结算，排队请求不能在关闭后再启动查询或写入。"""
        with self.service_lock:
            with self.request_lock:
                if self.closing:
                    raise ConnectionAbortedError("本地服务正在关闭")
                self.request_states[connection] = "business"
            try:
                yield
            finally:
                with self.request_lock:
                    self.request_states[connection] = "responding"

    def begin_response(self, connection):
        """响应开始后保留连接到有界发送结束；被关闭取消的慢请求无需再写错误响应。"""
        with self.request_lock:
            if self.closing and self.request_states.get(connection) == "reading":
                return False
            self.request_states[connection] = "responding"
            return True

    def server_close(self):
        """先停止接收，再打断未进入业务的慢 socket，最后等待活跃业务及其 owned 查询收尾。"""
        self.socket.close()
        with self.request_lock:
            self.closing = True
            pending = [connection for connection, phase in self.request_states.items() if phase == "reading"]
        for connection in pending:
            try:
                # 单次 socket timeout 不能防止持续滴入字节；shutdown 会唤醒头部/正文读取。
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # ThreadingMixIn 在非 daemon 模式 join 所有工作线程。业务 finally 已执行、
        # 响应发送/读取已结束后才返回，CLI 随后方可删连接记录并释放 service.lock。
        super().server_close()

    def connection(self):
        return {"port": self.server_port, "token": self.token, "pid": os.getpid(),
                "instance_id": self.instance_id, "protocol_version": PROTOCOL_VERSION,
                "service_version": self.version, "configuration_identity": self.configuration_identity}


class ConsoleHandler(BaseHTTPRequestHandler):
    # HTTP/1.0 逐请求关闭连接：拒绝请求时无需继续吞咽不可信请求体。
    protocol_version = "HTTP/1.0"
    server_version = "NativeAgentConfig"
    sys_version = ""

    def log_message(self, _format, *_args):
        # URL 可包含用户项目路径；常规访问日志不记录路径、鉴权头或配置值。
        pass

    def _send(self, status, payload, content_type="application/json; charset=utf-8"):
        if not self.server.begin_response(self.connection):
            return
        body = (json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
                if content_type.startswith("application/json") else payload)
        if len(body) > MAX_RESPONSE and isinstance(payload, dict) and payload.get("partial_failure"):
            # 恢复资料优先于庞大的清单回读；不能因清单容量而抹掉已经发布的逐项结果。
            payload = {key: value for key, value in payload.items() if key != "context"}
            payload["context_unavailable"] = True
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(body) > MAX_RESPONSE:
            status, body = 500, b'{"error":{"code":"response_limit","message":"response too large"}}'
            content_type = "application/json; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, code, message):
        self._send(status, {"error": {"code": code, "message": message}})

    def _route(self, method):
        try:
            self._dispatch(method)
        except RequestError as exc:
            self._error(exc.status, exc.code, exc.message)
        except ValueError as exc:
            # 业务异常可能含文件路径或原始输入，只暴露稳定错误码和通用中文提示。
            status, payload = service_error(exc)
            self._send(status, payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass
        except Exception:
            self._error(500, "internal_error", "本地服务暂时无法完成请求")

    def _dispatch(self, method):
        if self.headers.get_all("Host", []) != [f"127.0.0.1:{self.server.server_port}"]:
            raise RequestError(403, "invalid_host", "仅允许当前回环地址")
        origins = self.headers.get_all("Origin", [])
        if origins and origins != [self.server.origin]:
            raise RequestError(403, "invalid_origin", "请求来源不匹配")
        if len(self.path) > 8192:
            raise RequestError(414, "request_limit", "请求地址过长")
        split = urlsplit(self.path)
        path = unquote(split.path)
        if (split.scheme or split.netloc or split.fragment or "\\" in path or "\x00" in path
                or any(part in {".", ".."} for part in path.split("/"))):
            raise RequestError(400, "invalid_path", "请求路径无效")
        if method not in {"GET", "POST"}:
            raise RequestError(405, "method_not_allowed", "不支持该请求方法")
        self.server.last_activity = time.monotonic()
        if not path.startswith("/api/"):
            if method != "GET":
                raise RequestError(405, "method_not_allowed", "静态页面仅支持读取")
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/index.html": ("index.html", "text/html; charset=utf-8"),
                      "/console.js": ("console.js", "text/javascript; charset=utf-8"),
                      "/console.css": ("console.css", "text/css; charset=utf-8")}
            if path not in assets:
                raise RequestError(404, "not_found", "页面不存在")
            name, content_type = assets[path]
            target = self.server.web_root / name
            if target.is_symlink() or not target.is_file():
                raise RequestError(404, "not_found", "页面资源尚未就绪")
            if target.stat().st_size > MAX_RESPONSE:
                raise RequestError(500, "response_limit", "页面资源过大")
            self._send(200, target.read_bytes(), content_type)
            return
        headers = self.headers.get_all("Authorization", [])
        expected = "Bearer " + self.server.token
        if len(headers) != 1 or not hmac.compare_digest(headers[0].encode("utf-8"), expected.encode("utf-8")):
            raise RequestError(401, "unauthorized", "需要本地控制台令牌")
        if method == "POST" and origins != [self.server.origin]:
            raise RequestError(403, "invalid_origin", "写入请求必须来自当前控制台")
        try:
            query = parse_qs(split.query, keep_blank_values=True, max_num_fields=8)
        except ValueError:
            raise RequestError(400, "invalid_query", "查询参数过多") from None
        if any(len(values) != 1 for values in query.values()):
            raise RequestError(400, "invalid_query", "查询参数不可重复")
        if method == "GET":
            if path == "/api/health":
                if query:
                    raise ValueError("健康检查不接受参数")
                self._send(200, {key: value for key, value in self.server.connection().items()
                                 if key not in {"token", "pid", "port"}})
                return
            allowed = {"host", "project", "scope"} if path == "/api/context" else {"host", "project"}
            if path not in {"/api/context", "/api/catalog"}:
                raise RequestError(404, "not_found", "接口不存在")
            if set(query) - allowed:
                raise ValueError("未知查询参数")
            host, project = validate_location(query.get("host", [None])[0], query.get("project", [None])[0])
            with self.server.business_request(self.connection):
                if path == "/api/context":
                    scope = query.get("scope", ["global"])[0]
                    if scope not in {"global", "project"} or (scope == "project" and project is None):
                        raise ValueError("无效配置范围")
                    result = self.server.service.context(host, scope=scope, project=project)
                else:
                    result = self.server.service.catalog(host, project=project)
            self._send(200, result)
            return
        if query or path not in {"/api/preview", "/api/apply"}:
            raise RequestError(404, "not_found", "接口不存在")
        data = self._json_body()
        with self.server.business_request(self.connection):
            if path == "/api/preview":
                if set(data) - {"host", "scope", "project", "revision", "edits", "reset"}:
                    raise ValueError("未知预览字段")
                validate_location(data.get("host"), data.get("project"))
                result = self.server.service.preview(data)
            else:
                if set(data) != {"preview_id"} or not isinstance(data["preview_id"], str) or len(data["preview_id"]) > 200:
                    raise ValueError("无效预览标识")
                result = self.server.service.apply(data["preview_id"])
        self._send(200, result)

    def _json_body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,8}", lengths[0]):
            raise RequestError(400, "invalid_length", "需要明确请求长度")
        size = int(lengths[0])
        if size > MAX_BODY:
            raise RequestError(413, "request_limit", "请求体过大")
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "invalid_content_type", "仅接受 JSON 请求")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("请求体不完整")
        result = parse_json(raw)
        if not isinstance(result, dict):
            raise ValueError("请求必须为对象")
        return result

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_OPTIONS(self):
        self._route("OPTIONS")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def do_PATCH(self):
        self._route("PATCH")


def private_runtime_dir(data_dir: Path) -> Path:
    """连接令牌只保存于独立私有目录，拒绝软链及其他用户拥有的目录。"""
    target = Path(data_dir) / "console"
    if target.is_symlink():
        raise ValueError("连接目录不能是符号链接")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = target.stat()
    if info.st_uid != os.getuid():
        raise ValueError("连接目录所有者不匹配")
    target.chmod(0o700)
    return target


@contextmanager
def process_lock(path: Path, *, blocking=True, timeout=None):
    """文件锁随进程退出自动释放；不使用 PID 猜测，也不代管任何 Agent。"""
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("连接锁无效")
        os.fchmod(descriptor, 0o600)
        # serve 保留非阻塞唯一锁；open 显式传总预算的剩余秒数，避免另一个
        # 启动进程持锁或失去响应时让当前客户端永久挂起。锁超时不代管持锁进程。
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if blocking and deadline is None else fcntl.LOCK_NB))
                break
            except BlockingIOError as exc:
                if not blocking:
                    raise ConsoleLifecycleError("service_busy", "同一数据目录的控制台服务已运行") from exc
                if deadline is not None and time.monotonic() >= deadline:
                    raise ConsoleLifecycleError("launch_timeout", "等待控制台启动锁超时") from exc
                time.sleep(min(0.05, max(0, deadline - time.monotonic())) if deadline is not None else 0.05)
        yield
    finally:
        os.close(descriptor)


def write_connection(directory: Path, connection: dict):
    """在同目录原子替换记录，避免其他会话读到半个令牌或端口。"""
    temporary = directory / ("connection-" + secrets.token_hex(8) + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(connection, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "connection.json")
    finally:
        temporary.unlink(missing_ok=True)


def read_connection(directory: Path):
    target = directory / "connection.json"
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("控制台连接记录无效") from exc
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or info.st_mode & 0o077 or info.st_size > 8192):
            raise ValueError("控制台连接记录权限或大小无效")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            result = parse_json(stream.read(8193))
    finally:
        os.close(descriptor)
    if (not isinstance(result, dict) or type(result.get("port")) is not int
            or not 1 <= result["port"] <= 65535
            or not isinstance(result.get("token"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", result["token"])
            or not isinstance(result.get("instance_id"), str)):
        raise ValueError("控制台连接记录无效")
    return result


class ConsoleLifecycleError(ValueError):
    """只使用固定错误码的生命周期拒绝，安全命令不转发异常正文。"""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _health(record, timeout):
    """认证健康探测共用一个单调时钟预算，滴入头部或正文不能重置预算。"""
    deadline = time.monotonic() + max(0, timeout)
    payload = bytearray()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(max(0.001, deadline - time.monotonic()))
        connection.connect(("127.0.0.1", record["port"]))
        request = (f"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:{record['port']}\r\n"
                   f"Authorization: Bearer {record['token']}\r\nConnection: close\r\n\r\n")
        connection.settimeout(max(0.001, deadline - time.monotonic()))
        connection.sendall(request.encode("ascii"))
        # 本组件固定返回 HTTP/1.0 + Content-Length，不接受重定向、分块或任意地址。
        # 每次 recv 都只做一次 socket 读取，重新扣减预算，避免 readline/read(n)
        # 内部多次读取使持续滴入的数据绕过超时。健康内容和头部各限制 8 KiB。
        while len(payload) <= 16384:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("健康探测超时")
            connection.settimeout(remaining)
            chunk = connection.recv(min(4096, 16385 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if b"\r\n\r\n" not in payload:
                if len(payload) > 8192:
                    raise ValueError("健康响应头超限")
                continue
            headers, body = payload.split(b"\r\n\r\n", 1)
            lines = headers.split(b"\r\n")
            if len(headers) > 8192 or not re.fullmatch(rb"HTTP/1\.[01] 200(?: [^\r\n]*)?", lines[0]):
                raise ValueError("健康响应无效")
            lengths = [line.split(b":", 1)[1].strip() for line in lines[1:]
                       if line.lower().startswith(b"content-length:")]
            if (len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > 8192
                    or any(line.lower().startswith(b"transfer-encoding:") for line in lines[1:])):
                raise ValueError("健康响应长度无效")
            if len(body) >= int(lengths[0]):
                if len(body) != int(lengths[0]):
                    raise ValueError("健康响应长度不匹配")
                return parse_json(body)
    raise ValueError("健康响应未完成")


def reusable_connection(directory: Path, version: str, identity: str, *, timeout=1):
    record = read_connection(directory)
    if record is None:
        return None
    # 禁止把新版本页面接到旧版本服务；安装更新后由旧服务正常空闲退出。
    if record.get("protocol_version") != PROTOCOL_VERSION or record.get("service_version") != version:
        raise ConsoleLifecycleError("incompatible_service", "已记录的控制台版本不兼容，请先关闭旧服务")
    if record.get("configuration_identity") != identity:
        raise ConsoleLifecycleError("configuration_conflict", "同一数据目录已经关联其他配置根，请使用独立 --data-dir")
    try:
        health = _health(record, timeout)
    except (OSError, ValueError):
        return None
    if not isinstance(health, dict) or any(health.get(key) != record.get(key)
               for key in ("protocol_version", "service_version", "instance_id", "configuration_identity")):
        raise ConsoleLifecycleError("handshake_failed", "控制台版本握手失败")
    return record


def console_result(connection, host, project=None, *, reused=False):
    validate_location(host, project)
    fragment = {"token": connection["token"], "host": host}
    if project is not None:
        fragment["project"] = project
    return {"url": f"http://127.0.0.1:{connection['port']}/#" + urlencode(fragment),
            "reused": reused, "protocol_version": connection["protocol_version"],
            "service_version": connection["service_version"]}
