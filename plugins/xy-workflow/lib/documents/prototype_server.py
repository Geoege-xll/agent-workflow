"""本机HTTP传输边界：固定登记闭包、隔离内容、受限浏览器权限与独立管理cap。"""
from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
import os
import posixpath
import re
import secrets
from socketserver import TCPServer
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from lib.documents import prototype_review as review
from lib.documents.prototype_live import LiveError, LiveSource
from lib.documents.prototype_targets import MAX_FEEDBACK_BYTES, inject_source_targets, json_bytes, _object


def safe_boot(value):
    """与客户端规范JSON校验一致；只转义运输层危险字符，不改变context身份。"""
    source = json_bytes(value).decode("utf-8")
    for char in ("<", ">", "&", "\u2028", "\u2029"):
        source = source.replace(char, "\\u" + format(ord(char), "04x"))
    return source


class PrototypeServer(ThreadingHTTPServer):
    """只绑定固定环回随机端口；每实例只有一个登记项目/请求和有限存活期。"""
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, source: LiveSource, tools, navigation, *, instance=None, idle_seconds=1800, lifetime_seconds=86400):
        self.source, self.tools = source, dict(tools)
        # 生命周期内固定当次安全捕获的有界闭包，只驻留内存，不在磁盘派生HTML。
        # 外壳通过context检查明确显示来源变化；保存/交还仍重读真实文件，不能将
        # 这里的旧修订画面当作最新源，亦不能随最新指针悄悄替换旧定位所见内容。
        _, self.files, _ = source.current()
        self.instance = instance or secrets.token_hex(24)
        self.token, self.management = secrets.token_hex(32), secrets.token_hex(32)
        self.content_cap = secrets.token_hex(32)
        self.bridges = {page["path"]: secrets.token_hex(32) for page in navigation}
        self.navigation = [{**entry, "url": "/content/" + self.content_cap + "/" + entry["path"] + "#bridge=" + self.bridges[entry["path"]]} for entry in navigation]
        self.started = self.last_activity = time.monotonic()
        self.idle_seconds, self.lifetime_seconds = idle_seconds, lifetime_seconds
        self.stopping = threading.Event()
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(("127.0.0.1", 0), Handler)
        self.timeout = .25
        self.host = "127.0.0.1:" + str(self.server_port)
        self.origin = "http://" + self.host

    def server_bind(self):
        """数字环回服务直接完成真实TCP绑定，不依赖未使用的反向DNS主机名。"""
        # HTTPServer的默认绑定还会调用socket.getfqdn/gethostbyaddr；其系统解析
        # 等待不受可信CLI的12秒握手预算控制。本服务全部Host/Origin、连接记录与
        # 健康请求均使用固定127.0.0.1，沿项目既有环回传输模式略过这一无关副作用。
        # 仍由内核分配随机端口，仍在完整来源/连接发布后才报告ready；不改全局DNS、
        # 启动预算、目录锁或权限检查，也不以提前输出就绪掩盖启动失败。
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def process_request(self, request, client_address):
        # 请求线程和读取超时同时有界，慢客户端不能无限占用本机服务资源。
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: self.slots.release()

    def run(self):
        try:
            while not self.stopping.is_set():
                now = time.monotonic()
                if now - self.last_activity >= self.idle_seconds or now - self.started >= self.lifetime_seconds: break
                self.handle_request()
        finally:
            self.stopping.set()
            self.server_close()

    def urls(self, name=None):
        name = name or self.navigation[0]["name"]
        entry = next((entry for entry in self.navigation if entry["name"] == name), None)
        if entry is None: raise ValueError("页面未登记")
        # 便利入口也遵守CLI的无秘密URL合同，不能让直接服务消费者重新传播旧fragment。
        return {"delivery_url": (self.source.root / entry["path"]).as_uri(),
            "http_delivery_url": self.origin + "/delivery/" + name,
            "review_url": self.origin + "/_entry-review/" + self.instance + "/" + self.source.context["review_id"] + "/" + name}


class Handler(BaseHTTPRequestHandler):
    server_version = "PrototypeReview/5"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        # URL含有只读cap，管理路径含私有cap；一律不输出访问日志或请求正文。
        pass

    def log_error(self, *_): pass

    def answer(self, status, body, mime="application/json; charset=utf-8", *, content=False, shell=False):
        if isinstance(body, dict): body = json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if content:
            self.send_header("Vary", "Origin")
            if self.headers.get_all("Origin", []) == ["null"]:
                # sandbox中的module import和字体以opaque origin请求。只读cap已在
                # 路由内核验，仅这些闭包字节允许null-origin跨源读取；控制/管理API
                # 不经过此分支，永不授予CORS或credentials。
                self.send_header("Access-Control-Allow-Origin", "null")
            # 即便cap被单独打开也保持opaque origin；内容脚本不能取父认证/存储或访问控制API。
            self.send_header("Content-Security-Policy", "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' " + self.server.origin + "; style-src 'unsafe-inline' " + self.server.origin + "; img-src data: " + self.server.origin + "; font-src " + self.server.origin + "; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
        if shell:
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError): pass

    def failure(self, status, code, message):
        self.answer(status, {"status": "error", "error": {"code": code, "message": message}})

    def authorized(self):
        if self.headers.get_all("Authorization", []) != ["Bearer " + self.server.token]: return False
        # 控制API强制精确Origin，null-origin业务iframe及跨站网页均不能借Bearer进入。
        origins = self.headers.get_all("Origin", [])
        if origins: return origins == [self.server.origin]
        # 同源GET的浏览器通常省略Origin；只允许浏览器签发的同源Fetch Metadata
        # 替代缺失头。opaque iframe为cross-site/null，不能借此进入控制边界。
        return self.command == "GET" and self.headers.get_all("Sec-Fetch-Site", []) == ["same-origin"]

    def body(self):
        if self.headers.get("Transfer-Encoding") is not None: raise ValueError("不支持分块请求")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"0|[1-9][0-9]{0,6}", lengths[0]): raise ValueError("JSON长度无效")
        length = int(lengths[0])
        if not 1 <= length <= MAX_FEEDBACK_BYTES: raise ValueError("JSON超过限额")
        if self.headers.get_all("Content-Type", []) not in (["application/json"], ["application/json; charset=utf-8"]):
            raise ValueError("须使用JSON内容类型")
        raw = self.rfile.read(length)
        if len(raw) != length: raise ValueError("JSON请求未完整传输")
        return review._closed_json(raw)

    def dispatch(self):
        if self.headers.get_all("Host", []) != [self.server.host]:
            return self.failure(403, "invalid_host", "仅允许本机精确服务地址")
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment or re.search(r"%(?:2f|5c|00)", parsed.path, re.I):
            return self.failure(400, "invalid_path", "请求路径无效")
        path = unquote(parsed.path)
        if any(part in {".", ".."} for part in path.split("/")) or "\\" in path or "\0" in path:
            return self.failure(400, "invalid_path", "请求路径无效")
        if path == "/health" and self.command == "GET" and not parsed.query:
            return self.answer(200, {"status": "ready"})
        management = "/_service/" + self.server.management + "/"
        if path.startswith("/_service/"):
            # 管理cap仅可信CLI私有文件持有，网页Origin即使同源也一律拒绝。
            if not path.startswith(management) or self.headers.get_all("Origin") or parsed.query:
                return self.failure(403, "forbidden", "管理请求未获授权")
            if path == management + "status" and self.command == "GET":
                return self.answer(200, {"status": "ready", "instance": self.server.instance,
                    "pid": os.getpid(), "review_id": self.server.source.context["review_id"]})
            if path == management + "stop" and self.command == "POST":
                if self.body() != {}: raise ValueError("停止请求只允许空对象")
                self.server.stopping.set()
                return self.answer(200, {"status": "stopping", "instance": self.server.instance})
            return self.failure(404, "not_found", "管理操作未登记")
        if path.startswith("/api/"):
            if not self.authorized(): return self.failure(403, "forbidden", "本机连接无效；请通过插件重新打开本次交付入口")
            self.server.last_activity = time.monotonic()
            if path == "/api/context" and self.command == "GET":
                query = parse_qs(parsed.query, strict_parsing=True) if parsed.query else {}
                if set(query) - {"name"} or any(len(value) != 1 for value in query.values()): raise ValueError("页面查询无效")
                name = query.get("name", [self.server.navigation[0]["name"]])[0]
                selected = next((entry for entry in self.server.navigation if entry["name"] == name), None)
                if selected is None: raise ValueError("页面未登记")
                try: self.server.source.current()
                except LiveError as exc:
                    if exc.code != "source_changed": raise
                    return self.answer(409, {"status": "source_changed", "context": self.server.source.context, "page": selected["path"]})
                return self.answer(200, {"status": "ready", "context": self.server.source.context, "page": selected["path"]})
            if path == "/api/draft" and not parsed.query:
                if self.command == "GET": return self.answer(200, self.server.source.read_draft())
                if self.command == "PUT":
                    value = _object(self.body(), {"revision", "draft"}, "草稿保存请求")
                    return self.answer(200, self.server.source.save_draft(value["revision"], value["draft"]))
            return self.failure(404, "not_found", "控制操作未登记")
        if self.command != "GET": return self.failure(405, "method_not_allowed", "请求方法未登记")
        # 公共ID和Fetch Metadata均不是认证秘密。这一路只负责浏览器顶层引导，
        # 将随机控制Bearer放入隔离的可信父文档；API仍独立核对Bearer和精确Origin。
        # file/opaque iframe、脚本、fetch和object不能借公开导航URL取得凭据。
        bootstrap = False
        bootstrap_name = None
        prefix = "/_entry-review/"
        if path.startswith(prefix):
            expected = prefix + self.server.instance + "/" + self.server.source.context["review_id"] + "/"
            bootstrap_name = path.removeprefix(expected) if path.startswith(expected) else None
            if parsed.query or bootstrap_name not in {entry["name"] for entry in self.server.navigation}:
                return self.failure(404, "not_found", "评审实例、修订或页面已失效；请重新执行open")
            if (self.headers.get_all("Origin", []) or
                self.headers.get_all("Sec-Fetch-Dest", []) != ["document"] or
                self.headers.get_all("Sec-Fetch-Mode", []) != ["navigate"] or
                self.headers.get_all("Sec-Fetch-Site", []) not in (["none"], ["cross-site"], ["same-origin"], ["same-site"])):
                return self.failure(403, "top_level_required", "评审入口只接受浏览器新标签顶层导航")
            try: self.server.source.current()
            except LiveError as exc:
                if exc.code != "source_changed": raise
                return self.failure(409, "source_changed", "原稿或工具已变化；请核对后重新执行open")
            bootstrap = True
        for kind in ("delivery", "review"):
            if ((bootstrap and kind == "review") or path.startswith("/" + kind + "/")) and not parsed.query:
                name = bootstrap_name if bootstrap else path[len(kind) + 2:]
                if name not in {entry["name"] for entry in self.server.navigation}: break
                template = self.server.tools["tool/" + kind + ".html"].decode("utf-8")
                if 'id="prototype-review-data"' in template or template.count("</head>") != 1: raise ValueError("工具启动模板无效")
                boot = {"schema_version": 5, "context": self.server.source.context, "pages": self.server.navigation}
                template = template.replace("</head>", '<script type="application/json" id="prototype-review-data">' + safe_boot(boot) + '</script></head>')
                if bootstrap:
                    connection = {"schema_version": 1, "review_id": self.server.source.context["review_id"], "token": self.server.token}
                    if 'id="prototype-browser-connection"' in template: raise ValueError("工具连接模板重复")
                    template = template.replace("</head>", '<script type="application/json" id="prototype-browser-connection">' + safe_boot(connection) + '</script></head>')
                # 模板只引用固定工具资产，映射为统一绝对路径以兼容两个壳路由。
                for asset in review.LIVE_TOOL_ASSETS:
                    template = template.replace('"' + asset + '"', '"/assets/' + asset + '"')
                return self.answer(200, template.encode("utf-8"), "text/html; charset=utf-8", shell=True)
        if path.startswith("/assets/") and not parsed.query:
            asset = path.removeprefix("/assets/")
            if asset in review.LIVE_TOOL_ASSETS and asset not in {"delivery.html", "review.html"}:
                return self.answer(200, self.server.tools["tool/" + asset], mimetypes.guess_type(asset)[0] or "application/octet-stream")
        prefix = "/content/" + self.server.content_cap + "/"
        if path.startswith(prefix):
            relative = path[len(prefix):]
            files = self.server.files
            if relative not in files or not relative.startswith(self.server.source.context["prototype_root"] + "/"):
                return self.failure(404, "not_found", "内容资源未登记")
            body = files[relative]
            if relative in self.server.bridges:
                from lib.documents.prototype_file_entry import strip_entry
                # 源键按原始HTML字节计算完毕，再仅在HTTP内存响应移除file入口。
                # 顺序反过来会让无ID节点偏移与交接校验不一致，且会递归加载file外壳。
                source = strip_entry(inject_source_targets(relative, body)).decode("utf-8")
                bridge = '<script src="/assets/canvas-presentation.js"></script><script src="/assets/page-shell.js" data-prototype-review-bridge="5" data-prototype-review-page="' + html.escape(relative, quote=True) + '" data-prototype-review-token="' + self.server.bridges[relative] + '"></script>'
                matches = list(re.finditer(r"</body\s*>", source, re.I))
                if len(matches) != 1: raise ValueError("业务页面必须有唯一body结束标签")
                body = (source[:matches[0].start()] + bridge + source[matches[0].start():]).encode("utf-8")
            elif relative.lower().endswith((".html", ".htm")):
                return self.failure(404, "not_found", "HTML页面未登记")
            self.server.last_activity = time.monotonic()
            return self.answer(200, body, (mimetypes.guess_type(relative)[0] or "application/octet-stream") + ("; charset=utf-8" if relative.endswith((".html", ".css", ".js")) else ""), content=True)
        return self.failure(404, "not_found", "资源未登记")

    def handle_operation(self):
        try: self.dispatch()
        except LiveError as exc: self.failure(409, exc.code, str(exc))
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError): self.failure(400, "invalid_request", "请求数据无效或超过范围；输入未被覆盖")
        except OSError: self.failure(503, "service_unavailable", "本机来源或私有存储暂不可用；输入未被覆盖")

    do_GET = handle_operation
    do_PUT = handle_operation
    do_POST = handle_operation
    do_OPTIONS = handle_operation
    do_DELETE = handle_operation
