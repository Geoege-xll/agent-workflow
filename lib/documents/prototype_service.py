"""可信CLI拥有的本机服务生命周期；网页只能使用已登记实例的受限浏览器权限。"""
from __future__ import annotations

from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.documents import prototype_review as review
from lib.documents.prototype_live import LiveSource, capture_live, register_live, replace_json, read_json
from lib.documents.prototype_server import PrototypeServer
from lib.documents.prototype_targets import _object, json_bytes

START_TIMEOUT = 12
STOP_TIMEOUT = 8


@contextmanager
def service_directory(identity, data_dir, *, create=False):
    with review._request_directory(identity, data_dir, create=create) as (path, fd):
        live_fd = review._child(fd, "live", create=create)
        try: yield path / "live", live_fd
        finally: os.close(live_fd)


def _read_connection(fd, identity=None):
    value = read_json(fd, "connection.json", 32768)
    _object(value, {"schema_version", "pid", "instance", "port", "token", "management", "context"}, "私有服务连接")
    if type(value["schema_version"]) is not int or value["schema_version"] != 5: raise ValueError("私有连接版本无效")
    if type(value["pid"]) is not int or value["pid"] <= 1 or type(value["port"]) is not int or not 1 <= value["port"] <= 65535:
        raise ValueError("私有连接进程或端口无效")
    for field in ("instance", "token", "management"):
        if not isinstance(value[field], str) or not re.fullmatch(r"[a-f0-9]{48,128}", value[field]): raise ValueError("私有连接身份无效")
    review.check_context(value["context"], schema_version=3)
    if identity and any(value["context"][key] != identity[key] for key in ("project_id", "request_id")):
        raise ValueError("私有连接不属于当前项目请求")
    return value


def _management(connection, operation):
    """独立随机管理cap证明当前socket实例；不根据PID单独发信号，避免PID复用误伤。"""
    client = http.client.HTTPConnection("127.0.0.1", connection["port"], timeout=2)
    try:
        stop = operation == "stop"
        client.request("POST" if stop else "GET", "/_service/" + connection["management"] + "/" + operation,
            body=b"{}" if stop else None, headers={"Content-Type": "application/json"} if stop else {})
        response = client.getresponse()
        raw = response.read(32769)
        if response.status != 200 or len(raw) > 32768: raise ValueError("管理实例未响应")
        value = review._closed_json(raw)
        if value.get("instance") != connection["instance"]: raise ValueError("管理实例身份不一致")
        if not stop and (value.get("pid") != connection["pid"] or value.get("review_id") != connection["context"]["review_id"]):
            raise ValueError("管理进程或修订身份不一致")
        return value
    finally: client.close()


def _active(connection):
    try:
        os.kill(connection["pid"], 0)
    except ProcessLookupError: return False
    except OSError as exc: raise ValueError("无法安全确认已有进程身份；未启动重复服务或终止其他进程") from exc
    try:
        return _management(connection, "status")["status"] == "ready"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        # 活PID与不可验证socket不能当作“已停”：否则一次暂时无响应就会产生
        # 两个活动实例，或在PID复用后误终止无关进程。保留记录并准确报告不可用。
        raise ValueError("已有服务进程暂时无法验证；请稍后检查状态，未启动重复服务或终止其他进程") from exc


def _stop(connection):
    if not _active(connection): return
    _management(connection, "stop")
    deadline = time.monotonic() + STOP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            # 只检测同一随机cap是否仍可访问；身份不符的其他进程永不获得停止信号。
            _management(connection, "status")
        except (OSError, ValueError, http.client.HTTPException): return
        time.sleep(.05)
    raise ValueError("已请求优雅停止但实例仍未退出，请稍后重新检查；未终止其他进程")


def _identity(root, request_id):
    review._identifier(request_id, "请求ID")
    project = Path(root)
    if not project.is_absolute() or ".." in project.parts or "\\" in str(project): raise ValueError("项目根必须是明确的实际绝对目录")
    return {"project_id": review.project_id(project), "request_id": request_id}


def service_status(root, request_id, *, data_dir=None):
    review.require_external_data_dir(root, data_dir)
    identity = _identity(root, request_id)
    try:
        with service_directory(identity, data_dir) as (_, fd), review._lock(fd):
            connection = _read_connection(fd, identity)
            if not _active(connection): return {"status": "stopped", "request_id": request_id}
            return {"status": "ready", "request_id": request_id, "review_id": connection["context"]["review_id"], "pid": connection["pid"]}
    except FileNotFoundError: return {"status": "stopped", "request_id": request_id}


def stop_service(root, request_id, *, data_dir=None):
    review.require_external_data_dir(root, data_dir)
    identity = _identity(root, request_id)
    try:
        with service_directory(identity, data_dir) as (_, fd), review._lock(fd):
            connection = _read_connection(fd, identity)
            _stop(connection)
            # 只删除刚刚验证的本实例连接文件，元数据、旧意见和历史包始终保留。
            if _read_connection(fd) == connection:
                os.unlink("connection.json", dir_fd=fd); os.fsync(fd)
    except FileNotFoundError: pass
    return {"status": "stopped", "request_id": request_id}


def _launch(configuration, fd):
    read_fd, write_fd = os.pipe()
    process = None
    try:
        # 认证信息只通过继承管道传递；argv不包含token、机器业务路径或任意shell片段。
        process = subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--bootstrap-fd", str(read_fd)],
            cwd=str(review.TOOL_ROOT), pass_fds=(read_fd,), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        os.close(read_fd); read_fd = -1
        body = json_bytes(configuration)
        if len(body) > 32768: raise ValueError("可信启动配置超限")
        view = memoryview(body)
        while view:
            count = os.write(write_fd, view)
            if count <= 0: raise OSError("启动管道写入无进展")
            view = view[count:]
        os.close(write_fd); write_fd = -1
        if not select.select([process.stdout], [], [], START_TIMEOUT)[0]: raise ValueError("服务启动超时")
        ready = process.stdout.readline(1024)
        if ready != b'{"status":"ready"}\n': raise ValueError("服务启动失败；未更改现有原稿或草稿")
        connection = _read_connection(fd)
        if connection["pid"] != process.pid or connection["instance"] != configuration["instance"] or not _active(connection):
            raise ValueError("服务启动身份复核失败")
        return connection
    except BaseException:
        # 只有本次Popen对象可在超时/失败中被终止，不按持久化PID猜测进程。
        if process is not None:
            process.terminate()
            try: process.wait(timeout=STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=2)
        raise
    finally:
        for descriptor in (read_fd, write_fd):
            if descriptor >= 0: os.close(descriptor)
        if process is not None:
            process.stdout.close(); process.stderr.close()


def open_service(root, adapter, plan, request_id, pages=None, *, data_dir=None):
    review.require_external_data_dir(root, data_dir)
    if not isinstance(pages, list) or not pages: raise ValueError("open必须显式登记具体页面数组")
    from lib.documents.prototype_file_entry import require_prepared, publish_binding
    # open只消费显式prepare-delivery已经准备的入口；不暗中改写原稿或冷准备。
    require_prepared(root, adapter, pages, data_dir=data_dir)
    tool, _ = review.capture_tool(format_version=5)
    context, _, _, navigation = capture_live(root, adapter, plan, request_id, pages, tool=tool)
    register_live(root, context, data_dir=data_dir)
    with service_directory(context, data_dir, create=True) as (_, fd), review._lock(fd):
        try: connection = _read_connection(fd, context)
        except FileNotFoundError: connection = None
        reused = bool(connection and connection["context"] == context and _active(connection))
        if not reused:
            if connection: _stop(connection)
            configuration = {"root": str(root), "adapter": adapter, "plan": plan, "request_id": request_id,
                "pages": [page["path"] for page in context["pages"]], "data_dir": str(data_dir or review.default_data_dir()),
                "review_id": context["review_id"], "instance": secrets.token_hex(24)}
            connection = _launch(configuration, fd)
        base = "http://127.0.0.1:" + str(connection["port"])
        name = navigation[0]["name"]
        publish_binding(root, adapter, [page["path"] for page in context["pages"]], context, connection, data_dir=data_dir)
        deliveries = [(Path(root) / page["path"]).as_uri() for page in context["pages"]]
        return {"status": "ready", "request_id": request_id, "review_id": context["review_id"], "reused": reused,
            "delivery_url": deliveries[0], "delivery_urls": deliveries,
            "http_delivery_url": base + "/delivery/" + name,
            "review_url": base + "/_entry-review/" + connection["instance"] + "/" + context["review_id"] + "/" + name}


def serve_from_pipe(fd):
    """内部启动只接受当前用户继承的FIFO；不暴露网页root/argv/文件控制接口。"""
    info = os.fstat(fd)
    if not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid(): raise ValueError("可信启动管道无效")
    chunks, size = [], 0
    deadline = time.monotonic() + 5
    try:
        while size <= 32768:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]: raise ValueError("可信启动管道超时")
            chunk = os.read(fd, min(8192, 32769 - size))
            if not chunk: break
            chunks.append(chunk); size += len(chunk)
    finally: os.close(fd)
    raw = b"".join(chunks)
    if len(raw) > 32768: raise ValueError("可信启动配置超限")
    value = review._closed_json(raw)
    _object(value, {"root", "adapter", "plan", "request_id", "pages", "data_dir", "review_id", "instance"}, "可信启动")
    if not isinstance(value["instance"], str) or not re.fullmatch(r"[a-f0-9]{48}", value["instance"]): raise ValueError("可信启动实例无效")
    tool, tools = review.capture_tool(format_version=5)
    context, _, _, navigation = capture_live(value["root"], value["adapter"], value["plan"], value["request_id"], value["pages"], tool=tool)
    if context["review_id"] != value["review_id"]: raise ValueError("来源在启动期间变化")
    server = PrototypeServer(LiveSource(value["root"], context, data_dir=value["data_dir"]), tools, navigation, instance=value["instance"])
    connection = {"schema_version": 5, "pid": os.getpid(), "instance": server.instance, "port": server.server_port,
        "token": server.token, "management": server.management, "context": context}
    # 外层open持有live目录锁直到握手结束；子进程仅发布当前连接，不反向等待同一锁。
    with service_directory(context, value["data_dir"]) as (_, directory): replace_json(directory, "connection.json", connection)
    def terminate(_signum, _frame): server.stopping.set()
    signal.signal(signal.SIGTERM, terminate); signal.signal(signal.SIGINT, terminate)
    print('{"status":"ready"}', flush=True)
    try: server.run()
    finally:
        # open/stop可能正持有锁等待退出；非阻塞锁失败时交给它回收，不产生停服死锁。
        try:
            with service_directory(context, value["data_dir"]) as (_, directory), review._lock(directory):
                if _read_connection(directory) == connection:
                    os.unlink("connection.json", dir_fd=directory); os.fsync(directory)
        except (FileNotFoundError, ValueError): pass


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "--bootstrap-fd": raise ValueError("仅支持可信内部启动")
        serve_from_pipe(int(sys.argv[2]))
    except (ValueError, OSError, TypeError, RecursionError):
        print('{"status":"error"}', flush=True)
        raise SystemExit(1)
