"""插件专用组件仓：只做发行完整性、私有版本目录和原子登记，不导入配置业务。"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
import zlib

if os.name != "nt":
    import fcntl

PRODUCT = "native-agent-config"
REPOSITORY = "Geoege-xll/agent-workflow"
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_CONTENT = 64 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
DOWNLOAD_BUDGET = 60
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-alpha\.[0-9]+")
DIGEST = re.compile(r"[0-9a-f]{64}")


class ComponentError(Exception):
    """错误只携带固定代码；调用方不得回传异常原文或下载响应。"""


def physical(path: Path, *, private=False):
    """逐层拒绝软链，避免注册表、组件根或暂存目录跳出明确选择的位置。"""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ComponentError("invalid_component_path")
    for node in (path, *path.parents):
        if node.is_symlink():
            raise ComponentError("unsafe_component_path")
    if private and path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ComponentError("component_permissions")
    return path


def release_url(url: str, name: str):
    """只允许已审仓库的固定 GitHub Release 资产，不猜标签、镜像或相邻 ZIP。"""
    parsed = urllib.parse.urlsplit(url)
    prefix = f"/{REPOSITORY}/releases/download/"
    tail = parsed.path.removeprefix(prefix).split("/")
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
            or not parsed.path.startswith(prefix) or len(tail) != 2
            or not re.fullmatch(r"[A-Za-z0-9._-]+", tail[0]) or tail[1] != name):
        raise ComponentError("invalid_release_url")
    return url


def descriptor(path: Path):
    try:
        physical(path)
        if path.stat().st_size > 16 * 1024 or not path.is_file():
            raise ComponentError("invalid_descriptor")
        data = json.loads(path.read_text(encoding="utf-8"))
        if (set(data) != {"schema_version", "product", "version", "channel", "cli_protocol", "service_protocol", "release_status", "artifact"}
                or data["schema_version"] != 1 or data["product"] != PRODUCT or data["channel"] != "alpha"
                or data["cli_protocol"] != 1 or data["service_protocol"] != 2
                or not VERSION.fullmatch(data["version"]) or data["release_status"] not in {"unpublished", "published"}):
            raise ComponentError("invalid_descriptor")
        artifact = data["artifact"]
        if (set(artifact) != {"name", "sha256", "url"}
                or artifact["name"] != f"{PRODUCT}-{data['version']}.zip"
                or not isinstance(artifact["sha256"], str) or not isinstance(artifact["url"], str)
                or artifact["sha256"] and not DIGEST.fullmatch(artifact["sha256"])):
            raise ComponentError("invalid_descriptor")
        if data["release_status"] == "published":
            if not artifact["sha256"] or not artifact["url"]:
                raise ComponentError("invalid_descriptor")
            release_url(artifact["url"], artifact["name"])
        elif artifact["url"]:
            raise ComponentError("invalid_descriptor")
        return data
    except (OSError, ValueError, TypeError, KeyError):
        raise ComponentError("invalid_descriptor") from None


def payload_name(name):
    """发行包只接受配置工具的封闭文件布局；目录项也拒绝，避免解压语义歧义。"""
    parts = PurePosixPath(name).parts
    if (not name or "\\" in name or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
            or any(part in {".", ".."} for part in name.split("/"))
            or name.startswith("/") or PurePosixPath(name).as_posix() != name):
        raise ComponentError("unsafe_archive_path")
    return (name in {"BUILD.json", "README.md", "product/command_identity.json", "product/command_identity.py", "product/__init__.py", "native_config/VERSION", "scripts/agent_config.sh", "scripts/agent_config.py", "scripts/python_runtime.sh"}
            or name in {"native_config/web/index.html", "native_config/web/console.js", "native_config/web/console.css"}
            or len(parts) >= 2 and parts[0] == "native_config" and name.endswith(".py"))


def checked_build(bodies, expected_version):
    """认证包自身声明的版本、文件闭包和摘要，不把后来新增的运行 ABI 套在历史库存上。"""
    try:
        build = json.loads(bodies["BUILD.json"].decode("utf-8"))
        if (set(build) != {"name", "version", "third_party_dependencies", "files"}
                or build["name"] != PRODUCT or build["version"] != expected_version
                or build["third_party_dependencies"] != [] or not isinstance(build["files"], dict)
                or set(build["files"]) != set(bodies) - {"BUILD.json"}
                or bodies["native_config/VERSION"].decode("ascii").strip() != expected_version):
            raise ComponentError("invalid_build_manifest")
        for name, digest in build["files"].items():
            if not isinstance(digest, str) or not DIGEST.fullmatch(digest) or hashlib.sha256(bodies[name]).hexdigest() != digest:
                raise ComponentError("build_digest_mismatch")
        return build
    except (ValueError, KeyError, UnicodeError, TypeError):
        raise ComponentError("invalid_build_manifest") from None


def checked_release_payload(bodies, expected_version):
    """当前发行/运行入口的完整 ABI；新输入、当前活动版本和登记重试都必须满足。"""
    build = checked_build(bodies, expected_version)
    required = {"scripts/agent_config.sh", "scripts/agent_config.py", "scripts/python_runtime.sh",
                "native_config/__init__.py", "native_config/cli.py", "native_config/VERSION", "product/command_identity.json", "product/command_identity.py", "product/__init__.py",
                "native_config/web/index.html", "native_config/web/console.js", "native_config/web/console.css", "README.md"}
    if not required.issubset(bodies):
        raise ComponentError("invalid_build_manifest")
    return build


def archive_payload(path: Path, expected_version: str, expected_sha: str | None = None, *, snapshot=None):
    """公开发行输入始终采用当前 ABI，防止装配 descriptor 等调用者意外接受历史布局。"""
    return _archive_payload(path, expected_version, expected_sha,
                            check_payload=checked_release_payload, snapshot=snapshot)


def _archive_payload(path: Path, expected_version: str, expected_sha: str | None, *, check_payload, snapshot=None):
    """先在内存中完整检查中央目录、类型、大小及 BUILD 闭包，再允许写入任何版本文件。"""
    try:
        physical(path)
        if not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
            raise ComponentError("archive_too_large")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha is not None and digest != expected_sha:
            raise ComponentError("artifact_digest_mismatch")
        bodies, total = {}, 0
        # 摘要和 ZIP 验证使用同一快照，避免验证期间源文件被替换造成摘要与解压内容分离。
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            entries = package.infolist()
            if not entries or len(entries) > 256:
                raise ComponentError("invalid_archive")
            for entry in entries:
                mode = entry.external_attr >> 16
                if (not payload_name(entry.filename) or entry.filename in bodies or entry.is_dir()
                        or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or entry.flag_bits & 1):
                    raise ComponentError("unsafe_archive_entry")
                total += entry.file_size
                if entry.file_size > MAX_FILE or total > MAX_CONTENT:
                    raise ComponentError("archive_too_large")
                bodies[entry.filename] = package.read(entry)
        check_payload(bodies, expected_version)
        if snapshot is not None:
            with snapshot.open("xb") as stream:
                stream.write(raw)
            snapshot.chmod(0o600)
        return digest, bodies
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError):
        raise ComponentError("invalid_archive") from None


def download_remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ComponentError("download_timeout")
    return min(15, remaining)


class DeadlineHTTPSConnection(http.client.HTTPSConnection):
    """每次建立连接、TLS 握手前后都扣同一预算；DNS 等系统阻塞由外层 worker 监管。"""
    def __init__(self, host, *, deadline, **options):
        self.deadline = deadline
        options["timeout"] = download_remaining(deadline)
        super().__init__(host, **options)

    def connect(self):
        self.timeout = download_remaining(self.deadline)
        super().connect()
        self.sock.settimeout(download_remaining(self.deadline))


class DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, deadline):
        super().__init__()
        self.deadline = deadline

    def https_open(self, request):
        def connection(host, **options):
            return DeadlineHTTPSConnection(host, deadline=self.deadline, **options)
        request.timeout = download_remaining(self.deadline)
        return self.do_open(connection, request, context=self._context)


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub 允许跳转到其资产 CDN；每次跳转继续限制 HTTPS、目标域和次数。"""
    def __init__(self, deadline=None):
        self.deadline = deadline

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        count = getattr(request, "component_redirects", 0) + 1
        release_path = getattr(request, "component_release_path", urllib.parse.urlsplit(request.full_url).path)
        if (count > 4 or target.scheme != "https" or target.hostname not in {
                "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
                or target.username or target.password or target.port not in {None, 443}
                or target.hostname == "github.com" and (target.path != release_path or target.query)):
            raise ComponentError("unsafe_download_redirect")
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if self.deadline is not None:
            request.timeout = download_remaining(self.deadline)
        if redirected is not None:
            redirected.component_redirects = count
            redirected.component_release_path = release_path
        return redirected


def download_transfer(data, destination: Path, deadline):
    """worker 内的真实传输；read1 每次只读取一次底层数据，滴入内容不能重置总预算。"""
    artifact = data["artifact"]
    release_url(artifact["url"], artifact["name"])
    opener = urllib.request.build_opener(DeadlineHTTPSHandler(deadline), ReleaseRedirect(deadline))
    request = urllib.request.Request(artifact["url"], headers={"User-Agent": "agent-workflow-component/1"})
    try:
        with opener.open(request, timeout=download_remaining(deadline)) as response, destination.open("xb") as output:
            total = 0
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > MAX_ARCHIVE):
                raise ComponentError("archive_too_large")
            while True:
                if response.isclosed():
                    break
                # urllib 的 read(n) 可在一次调用中反复等满 n 字节；改为 read1 后，
                # 每次至多一个底层读取，并在下次 socket 等待前更新剩余预算。
                response.fp.raw._sock.settimeout(download_remaining(deadline))
                chunk = response.read1(64 * 1024)
                download_remaining(deadline)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE:
                    raise ComponentError("archive_too_large")
                output.write(chunk)
            if length is not None and total != int(length):
                raise ComponentError("download_failed")
    except TimeoutError:
        raise ComponentError("download_timeout") from None
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        raise ComponentError("download_failed") from None


def download(data, destination: Path, *, _budget=DOWNLOAD_BUDGET, _worker_command=None):
    """只监管本次自有子进程，硬性限制连接/响应头/重定向/正文的统一总时间。

    urllib 在响应头、chunk header、DNS 等内部操作中可能暂不归还控制；即使 socket
    持续收到单字节，父进程仍会在同一总预算到期时终止并回收本次 worker。它不会
    接触配置服务进程。测试只注入回环传输 worker 命令和短预算，不放宽生产 URL 规则。
    """
    artifact = data["artifact"]
    release_url(artifact["url"], artifact["name"])
    deadline = time.monotonic() + _budget
    command = _worker_command or [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--download-worker"]
    payload = {"data": data, "destination": str(destination), "deadline": deadline}
    try:
        # subprocess.run 超时只 kill/wait 自己创建的下载子进程，保证不会遗留占锁 worker。
        result = subprocess.run(command, input=json.dumps(payload), capture_output=True, text=True,
                                timeout=max(0, deadline - time.monotonic()))
        if time.monotonic() >= deadline:
            raise ComponentError("download_timeout")
        report = json.loads(result.stdout)
        if result.returncode == 0 and report == {"code": "ok"}:
            return
        code = report.get("code") if isinstance(report, dict) else None
        if code not in {"download_timeout", "download_failed", "archive_too_large", "unsafe_download_redirect", "invalid_release_url"}:
            code = "download_failed"
        raise ComponentError(code)
    except subprocess.TimeoutExpired:
        raise ComponentError("download_timeout") from None
    except (OSError, ValueError):
        raise ComponentError("download_failed") from None


def download_worker():
    """内部 worker 只接受 stdin 中的单次下载任务，stdout 永远只有固定脱敏代码。"""
    try:
        payload = json.load(sys.stdin)
        download_transfer(payload["data"], Path(payload["destination"]), payload["deadline"])
        report, code = {"code": "ok"}, 0
    except ComponentError as error:
        report, code = {"code": str(error)}, 1
    except (OSError, ValueError, KeyError, TypeError):
        report, code = {"code": "download_failed"}, 1
    print(json.dumps(report))
    return code


def directory_name(data):
    return f"{data['version']}-{data['artifact']['sha256']}"


def verified_version(root: Path, version: str, digest: str):
    """认证不可变库存并返回其字节；是否能作为当前运行版本由调用方的发行合同决定。"""
    target = physical(root / "versions" / f"{version}-{digest}", private=True)
    physical(root / "versions", private=True)
    if not target.is_dir():
        raise ComponentError("invalid_registry")
    # 原始发行包保存在版本目录外的私有内容寻址区。历史活动记录使用其原先登记的
    # 外层摘要重新认证 BUILD 与文件闭包，不要求它具有后来新增的身份文件。
    # 落盘字节仍须逐一匹配保留原包，不能靠同时改写文件和 BUILD 自证为完整。
    physical(root / "artifacts", private=True)
    trusted_archive = physical(root / "artifacts" / (digest + ".zip"), private=True)
    _, trusted_bodies = _archive_payload(trusted_archive, version, digest, check_payload=checked_build)
    bodies = {}
    for path in target.rglob("*"):
        physical(path, private=True)
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        name = path.relative_to(target).as_posix()
        if not stat.S_ISREG(info.st_mode) or not payload_name(name) or info.st_size > MAX_FILE:
            raise ComponentError("invalid_component_files")
        bodies[name] = path.read_bytes()
        if len(bodies) > 256 or sum(map(len, bodies.values())) > MAX_CONTENT:
            raise ComponentError("invalid_component_files")
    checked_build(bodies, version)
    if bodies != trusted_bodies:
        raise ComponentError("installed_payload_mismatch")
    return target, bodies


def installed(root: Path, data):
    """只读验证活动记录及整个不可变版本，绝不创建目录、修权限或猜源码位置。"""
    physical(root, private=True)
    registry = root / "registry.json"
    if not registry.exists():
        return None
    try:
        physical(registry, private=True)
        if not registry.is_file() or registry.stat().st_size > 16 * 1024:
            raise ComponentError("invalid_registry")
        record = json.loads(registry.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or set(record) != {"schema_version", "product", "version", "sha256", "directory"}
                or record["schema_version"] != 1 or record["product"] != PRODUCT
                or not isinstance(record["version"], str) or not VERSION.fullmatch(record["version"])
                or not isinstance(record["sha256"], str) or not DIGEST.fullmatch(record["sha256"])
                or record["directory"] != f"versions/{record['version']}-{record['sha256']}"):
            raise ComponentError("invalid_registry")
        target, bodies = verified_version(root, record["version"], record["sha256"])
        # 合法旧版本只认证和保留，绝不返回旧代码供启动器执行。精确匹配当前固定
        # 发行后仍须检查当前 ABI，不能用历史认证路径绕过当前运行要求。
        if (record["version"], record["sha256"]) != (data["version"], data["artifact"]["sha256"]):
            return None
        checked_release_payload(bodies, data["version"])
        return target
    except (OSError, ValueError, TypeError):
        raise ComponentError("invalid_registry") from None


def private_directory(path):
    """仅准备路径调用；已有不安全权限直接拒绝，避免 chmod 意外改变用户内容。"""
    physical(path, private=True)
    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    physical(path, private=True)


@contextlib.contextmanager
def preparation_lock(root):
    private_directory(root)
    path = physical(root / "prepare.lock", private=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        end = time.monotonic() + 12
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise ComponentError("preparation_busy")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def prepare(root: Path, data, artifact: Path | None):
    """显式确认后才进入此处；失败不改活动记录、不覆盖旧版本，也不接触旧服务。"""
    if not data["artifact"]["sha256"] or artifact is None and data["release_status"] != "published":
        raise ComponentError("artifact_unavailable")
    with preparation_lock(root):
        current = installed(root, data)
        if current is not None:
            return current
        versions = root / "versions"
        private_directory(versions)
        artifacts = root / "artifacts"
        private_directory(artifacts)
        target = versions / directory_name(data)
        # 暂存和原子 rename 均位于独立用户根，不将内容写入插件缓存或当前项目。
        with tempfile.TemporaryDirectory(prefix=".preparing-", dir=root) as temporary:
            stage = Path(temporary)
            if target.exists() or target.is_symlink():
                # 上次可能已成功原子发布版本，但在 registry 发布时遇到 ENOSPC 等瞬时错误。
                # 只能接续完全匹配本次 pinned 发行的安全版本；任何缺文件、软链、摘要或
                # BUILD 不一致都会失败。这里不重写、删除旧目录，也不碰旧活动服务。
                _, bodies = verified_version(root, data["version"], data["artifact"]["sha256"])
                checked_release_payload(bodies, data["version"])
            else:
                selected = artifact
                if selected is None:
                    selected = stage / "component.zip"
                    download(data, selected)
                verified = stage / "verified.zip"
                _, bodies = archive_payload(selected, data["version"], data["artifact"]["sha256"], snapshot=verified)
                unpacked = stage / "payload"
                unpacked.mkdir(mode=0o700)
                for name, body in bodies.items():
                    destination = unpacked / name
                    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with destination.open("xb") as stream:
                        stream.write(body)
                    destination.chmod(0o700 if name.endswith(".sh") else 0o600)
                cached = physical(artifacts / (data["artifact"]["sha256"] + ".zip"), private=True)
                if cached.exists():
                    archive_payload(cached, data["version"], data["artifact"]["sha256"])
                else:
                    os.rename(verified, cached)
                os.rename(unpacked, target)
            record = {"schema_version": 1, "product": PRODUCT, "version": data["version"],
                      "sha256": data["artifact"]["sha256"], "directory": "versions/" + target.name}
            pending = stage / "registry.json"
            with pending.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            pending.chmod(0o600)
            os.replace(pending, root / "registry.json")
        return installed(root, data)


if __name__ == "__main__":
    raise SystemExit(download_worker() if sys.argv[1:] == ["--download-worker"] else 2)
