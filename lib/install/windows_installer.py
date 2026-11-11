"""消费已校验发行归档，准备私有程序环境，并通过物理 CLI 激活中央核心。

本模块只拥有 install-root 下的程序资料；中央版本、项目策略及任务 pin 的
所有权始终属于现有 runtime CLI。pyz 可从内存加载，不能用 __file__ 猜源码根。
"""

from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
import uuid

from lib.platform_fs import os, directory_lock, project_mode
from lib.central.runtime_project import (
    LIMIT, Node, Tree, absolute_directory, json_bytes, native_snapshot, read_at, unique_json,
)
from lib.install.install_process import ACTIVE_RUNNER, SetupRunner, capture_process
from lib.runtime_store import validate_binding
from lib.windows_fs import validate_component


ARCHIVE_LIMIT = 2 * LIMIT
EXPANDED_LIMIT = 128 * 1024 * 1024
MEMBER_LIMIT = LIMIT
MEMBER_COUNT_LIMIT = 20000
ROOT_RECEIPT = ".awf-windows-root.json"
VERSION_RECEIPT = "install.json"
ROOT_BYTES = json_bytes({"schema_version": 1, "owner": "agent-workflow-windows-installer"})
VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", re.ASCII)
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
LAUNCHER_HEADER = "Agent Workflow managed Windows launcher v1"
# 4096 字节 JSON 的 base64 行小于 CMD 的 8191 字符解析界；超长身份必须在
# 程序/中央写入前拒绝，不能生成 CMD 无法消费的 rem 行并事后冒充入口就绪。
LAUNCHER_IDENTITY_LIMIT = 4096


class InstallerError(ValueError):
    """携带已确认阶段；失败绝不暗示中央事务已回滚。"""

    def __init__(self, message, *, phase="preflight", exit_code=2, retained=None):
        super().__init__(message)
        self.phase, self.exit_code, self.retained = phase, exit_code, retained


def _absolute(value: str | Path) -> Path:
    raw = str(value)
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or "\0" in raw:
        raise InstallerError("路径必须是无上级跳转的绝对路径")
    if os.name == "nt":
        from lib.windows_fs import absolute_path
        if raw.startswith(("\\\\", "//")):
            raise InstallerError("安装只接受本地磁盘绝对路径")
        return absolute_path(raw)
    return path


def _write(tree: Tree, relative: str, body: bytes, *, expected=Node(), mode=0o600) -> Node:
    """写入授权来自调用者的完整前像；Windows 生命周期由唯一 FS 层负责。

    条件写失败时不尝试重新读取并认领未知文件。暂存归属、ACL、关闭后的
    LastWriteTime 结算和原子发布均沿用 SDK，不在发行安装器复制 Win32 层。
    """
    parent, name = tree.parent(relative, create=True)
    if os.name == "nt":
        from lib.windows_fs import write_regular_if_unchanged
        value = write_regular_if_unchanged(
            parent, name, ".awf-stage-" + uuid.uuid4().hex,
            expected=None if expected.kind == "missing" else native_snapshot(expected),
            payload=body, mode=mode, max_bytes=MEMBER_LIMIT)
        return Node(**value)
    # 便携测试也实际消费原有锚定写者；生产 Windows 始终走上方完整 Node CAS。
    from manager.state_files import AnchoredFile
    if read_at(parent, name) != expected:
        raise InstallerError("程序文件在发布前变化，已保留现场")
    with AnchoredFile(tree.root, relative) as target:
        target.write(body, mode, (None, None) if expected.kind == "missing" else (expected.payload, expected.mode))
    return read_at(parent, name)


def _verified_archive(path: Path, digest: str) -> bytes:
    # read_at 在同一文件句柄验证类型、单链接、身份、容量及 Windows ACL。
    # 返回的不可变 bytes 是后续 tar 的唯一输入，校验后绝不重开下载路径。
    with absolute_directory(path.parent) as parent:
        node = read_at(parent, path.name, max_bytes=ARCHIVE_LIMIT)
    if node.kind != "file" or hashlib.sha256(node.payload).hexdigest() != digest:
        raise InstallerError("发行归档 SHA256 不匹配或文件不存在")
    return node.payload


class _ExpandedReader:
    """压缩层总预算也覆盖 PAX、填充和尾部，防止仅限制正文仍遭解压炸弹。"""

    def __init__(self, stream):
        self.stream, self.count = stream, 0

    def read(self, size):
        body = self.stream.read(min(size, EXPANDED_LIMIT - self.count + 1))
        self.count += len(body)
        if self.count > EXPANDED_LIMIT:
            raise InstallerError("归档展开总量超过预算", phase="extract")
        return body


def _member_path(name: str, prefix: str) -> str:
    parts = name.split("/")
    if parts[0] != prefix or any(not part for part in parts):
        raise InstallerError("归档成员不在固定发行根目录内", phase="extract")
    for part in parts:
        validate_component(part)
        # NTFS 的短文件名别名不能成为第二个入口；同时拒绝非规范 Unicode
        # 拼写，让跨平台预检也保守拦住同名目标，而不是等写入时碰撞。
        if "~" in part or unicodedata.normalize("NFC", part) != part:
            raise InstallerError("归档成员含 Windows 名称别名", phase="extract")
    return "/".join(parts[1:])


def extract_payload(data: bytes, tree: Tree | None, version: str) -> dict[str, dict]:
    """逐项解析、计量并锚定发布，只接受普通文件和目录；不调用 extractall。"""
    import tarfile
    prefix = "agent-workflow-" + version
    seen, spellings, files, required_bodies = {}, {}, {}, {}
    root_seen, total = False, 0
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as compressed:
        bounded = _ExpandedReader(compressed)
        with tarfile.open(fileobj=bounded, mode="r|") as archive:
            for count, member in enumerate(archive, 1):
                if count > MEMBER_COUNT_LIMIT:
                    raise InstallerError("归档成员数量超过预算", phase="extract")
                relative = _member_path(member.name, prefix)
                parts = member.name.split("/")
                for index in range(1, len(parts) + 1):
                    spelling = "/".join(parts[:index])
                    folded = spelling.upper().casefold()
                    if folded in spellings and spellings[folded] != spelling:
                        raise InstallerError("归档成员含大小写路径别名", phase="extract")
                    spellings[folded] = spelling
                key = member.name.upper().casefold()
                if key in seen or not (member.isdir() or member.isreg()) or member.issparse():
                    raise InstallerError("归档含重复名称、链接或特殊成员", phase="extract")
                if member.size < 0 or member.size > MEMBER_LIMIT or member.isdir() and member.size:
                    raise InstallerError("归档成员大小超过预算或类型不合法", phase="extract")
                seen[key] = "directory" if member.isdir() else "file"
                if not relative:
                    if not member.isdir() or count != 1:
                        raise InstallerError("归档缺少首项发行根目录", phase="extract")
                    root_seen = True
                    continue
                if not root_seen:
                    raise InstallerError("归档缺少首项发行根目录", phase="extract")
                # 先拒绝祖先被声明为文件；隐式目录和后出现的显式目录可共存，
                # 但大小写不同的祖先拼写不允许产生 Windows 路径别名。
                for index in range(1, len(member.name.split("/"))):
                    ancestor = "/".join(member.name.split("/")[:index])
                    old = seen.get(ancestor.upper().casefold())
                    if old == "file":
                        raise InstallerError("归档成员的祖先是普通文件", phase="extract")
                target = "payload/" + relative
                if member.isdir():
                    if tree is not None:
                        tree.directory(target, create=True)
                    continue
                total += member.size
                if total > EXPANDED_LIMIT:
                    raise InstallerError("归档正文总量超过预算", phase="extract")
                with archive.extractfile(member) as stream:
                    body = stream.read(MEMBER_LIMIT + 1)
                if len(body) != member.size:
                    raise InstallerError("归档成员正文截断", phase="extract")
                mode = project_mode(0o700 if member.mode & 0o111 else 0o600)
                if tree is not None:
                    _write(tree, target, body, mode=mode)
                files[relative] = {"sha256": hashlib.sha256(body).hexdigest(), "mode": mode}
                if relative in {"product/VERSION", "manager/release.json"}:
                    required_bodies[relative] = body
        while bounded.read(1024 * 1024):
            pass
    if not root_seen:
        raise InstallerError("发行归档为空", phase="extract")
    for required in ("workflow.py", "requirements-windows.txt", "product/VERSION", "manager/release.json"):
        if required not in files:
            raise InstallerError("发行归档缺少必要程序文件：" + required, phase="extract")
    if required_bodies["product/VERSION"] not in {(version + "\n").encode(), (version + "\r\n").encode()}:
        raise InstallerError("发行产品版本与安装参数不一致", phase="extract")
    metadata = unique_json(required_bodies["manager/release.json"])
    if metadata != {"schema_version": 1, "version": version} or type(metadata["schema_version"]) is not int:
        raise InstallerError("发行元数据必须保持既有两字段合同", phase="extract")
    return files


def _environment():
    env = dict(os.environ)
    # 只改变本次子进程环境，不写 PATH、profile、ExecutionPolicy 或全局解释器。
    for key in tuple(env):
        if key.upper() in {"PYTHONPATH", "PYTHONHOME", "BASH_ENV", "ENV", "CDPATH", "SHELLOPTS", "BASHOPTS"}:
            env.pop(key)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _validate_host():
    if (sys.platform != "win32" or not sys.flags.isolated or sys.implementation.name != "cpython"
            or sys.version_info < (3, 11) or sys.maxsize != 2**63 - 1):
        raise InstallerError("安装引擎需要原生 Windows CPython 3.11+ x64，并以 -I 隔离启动")
    node = shutil.which("node.exe")
    if node is None:
        raise InstallerError("需要已有的 Node.js 20+；安装器不会下载解释器")
    process = capture_process([node, "--version"], env=_environment(), timeout=30)
    if process.returncode or not re.fullmatch(rb"v(?:2[0-9]|[3-9][0-9]|[1-9][0-9]{2,})\.[0-9]+\.[0-9]+\s*", process.stdout):
        raise InstallerError("需要已有且可运行的 Node.js 20+")


def _python(version_root: Path) -> Path:
    return version_root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _prepare_environment(root: Path, runner: SetupRunner):
    # venv 的配置和脚本包含绝对路径，必须直接在最终路径创建，不能先建 stage
    # 再重命名。任何中途失败都保留该目录；下次拒绝没有完整收据的目录。
    commands = [[sys.executable, "-I", "-B", "-X", "utf8", "-m", "venv", "--copies", str(root / "venv")],
                [str(_python(root)), "-I", "-B", "-X", "utf8", "-m", "pip", "--isolated",
                "--disable-pip-version-check", "install", "--require-hashes", "--only-binary=:all:",
                "-r", str(root / "payload/requirements-windows.txt")]]
    for command in commands:
        # capture_process 消费 ACTIVE_RUNNER 的共同预算和 Job 所有者，同时
        # 隔离 pip/venv 的过程输出，保证安装器 --json 的 stdout 只有结果信封。
        process = capture_process(command, env=_environment(), timeout=1200)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)


def _validate_payload(tree: Tree, files: dict):
    observed, pending = set(), ["payload"]
    while pending:
        directory = pending.pop()
        with os.scandir(tree.directory(directory)) as entries:
            names = [entry.name for entry in entries]
        for name in names:
            validate_component(name)
            relative = directory + "/" + name
            parent = tree.directory(directory)
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                pending.append(relative)
            else:
                path = relative.removeprefix("payload/")
                fact = files.get(path)
                if fact is None:
                    raise InstallerError("程序载荷含未知文件或特殊节点，拒绝执行")
                node = tree.read(relative)
                if (node.kind != "file" or node.mode != fact["mode"]
                        or hashlib.sha256(node.payload).hexdigest() != fact["sha256"]):
                    raise InstallerError("程序载荷与已校验归档不一致，拒绝执行")
                observed.add(path)
            if len(observed) + len(tree.directories) > MEMBER_COUNT_LIMIT + 2:
                raise InstallerError("程序载荷节点数量超过预算")
    if observed != set(files):
        raise InstallerError("程序载荷缺少已校验归档中的文件")


def _cli(root: Path, options: list[str], command: list[str], *, dry_run=False) -> dict:
    process = capture_process([str(_python(root)), "-I", "-B", "-X", "utf8", str(root / "payload/workflow.py"),
                               *options, "--json", *command], env=_environment(), timeout=1200)
    if process.returncode:
        raise InstallerError("物理 payload CLI 拒绝了安装阶段", exit_code=process.returncode)
    if len(process.stdout) > LIMIT:
        raise InstallerError("物理 payload CLI 响应超过预算")
    envelope = unique_json(process.stdout)
    if (not isinstance(envelope, dict) or set(envelope) != {"schema_version", "command", "dry_run", "result"}
            or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1
            or envelope["command"] != " ".join(command[:2]) or envelope["dry_run"] is not dry_run
            or not isinstance(envelope["result"], dict)):
        raise InstallerError("物理 payload CLI 没有返回可确认的成功信封")
    return envelope["result"]


def _launcher_bodies(identity: dict) -> dict[str, bytes]:
    root = Path(identity["install_root"]) / "versions" / (identity["version"] + "-" + identity["archive_sha256"])
    # CMD 的 rem 仍会经历变量展开和元字符解析，不是安全的数据容器。身份行
    # 只写 URL-safe base64；原始路径与选项只出现在 PS 的单引号数据字面量。
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    identity_bytes = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(identity_bytes) > LAUNCHER_IDENTITY_LIMIT:
        raise InstallerError("程序入口身份超过有界容量")
    metadata = base64.urlsafe_b64encode(identity_bytes).decode("ascii")
    arguments = ", ".join(quote(value) for value in (
        "-I", "-B", "-X", "utf8", root / "payload/workflow.py", *identity["cli_options"]))
    # 与物理 payload/workflow.ps1 使用相同 .NET ArgumentList 边界。直接
    # & python @args 会受 PowerShell 7.0/Legacy 原生参数拼接影响，丢失空串或
    # 嵌入双引号；不能靠修改用户的全局 NativeCommandArgumentPassing 弥补。
    # 工作目录取 FileSystem provider 的当前位置，标准流直接继承；无需修改
    # AGENT_WORKFLOW_PYTHON，因此异常、业务拒绝及取消均不会污染调用者环境。
    ps = (f"# {LAUNCHER_HEADER}\r\n# {metadata}\r\n"
          "#requires -Version 7.0\r\n"
          "$ErrorActionPreference = 'Stop'\r\n"
          "try {\r\n"
          "    if (-not $IsWindows) { throw '此受管入口需要原生 Windows PowerShell 7。' }\r\n"
          "    $start = [System.Diagnostics.ProcessStartInfo]::new()\r\n"
          f"    $start.FileName = {quote(_python(root))}\r\n"
          "    $start.UseShellExecute = $false\r\n"
          "    $location = Get-Location\r\n"
          "    if ($location.Provider.Name -ne 'FileSystem') { throw '请从文件系统目录调用受管入口。' }\r\n"
          "    $start.WorkingDirectory = $location.ProviderPath\r\n"
          f"    foreach ($argument in @({arguments})) {{\r\n"
          "        $start.ArgumentList.Add($argument)\r\n"
          "    }\r\n"
          "    foreach ($argument in $args) {\r\n"
          "        if ($argument -isnot [string] -or $argument.IndexOf([char]0) -ge 0) {\r\n"
          "            throw 'CLI 参数必须为不含 NUL 的字符串。'\r\n"
          "        }\r\n"
          "        $start.ArgumentList.Add($argument)\r\n"
          "    }\r\n"
          "    $process = [System.Diagnostics.Process]::Start($start)\r\n"
          "    try {\r\n"
          "        $process.WaitForExit()\r\n"
          "        $result = $process.ExitCode\r\n"
          "    }\r\n"
          "    finally { $process.Dispose() }\r\n"
          "}\r\n"
          "catch {\r\n"
          "    [Console]::Error.WriteLine('[错误] 受管入口启动失败：' + $_.Exception.Message)\r\n"
          "    exit 2\r\n"
          "}\r\n"
          "exit $result\r\n")
    # 沿已有 workflow.cmd 的固定 PowerShell 安装入口；不按 cwd/PATH 搜索
    # pwsh.exe，不用 CALL 二次求值，关闭 delayed expansion 保留正常 CMD 引用。
    cmd = (f"@rem {LAUNCHER_HEADER}\r\n@rem {metadata}\r\n"
           '@echo off\r\nsetlocal EnableExtensions DisableDelayedExpansion\r\n'
           '"%ProgramFiles%\\PowerShell\\7\\pwsh.exe" -NoLogo -NoProfile -File "%~dp0awf-cli.ps1" %*\r\n'
           'exit /b %errorlevel%\r\n')
    return {"awf-cli.ps1": ps.encode("utf-8"), "awf-cli.cmd": cmd.encode("utf-8")}


def _receipt(tree: Tree, relative: str, version: str, digest: str) -> tuple[dict | None, Node]:
    node = tree.read(relative)
    if node.kind == "missing":
        return None, node
    value = unique_json(node.payload)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "version", "archive_sha256", "phase", "files", "cli_options"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["version"] != version or value["archive_sha256"] != digest
            or value["phase"] not in {"environment_ready", "activation_started", "activated", "complete"}
            or not isinstance(value["files"], dict) or not value["files"]
            or not isinstance(value["cli_options"], list)):
        raise InstallerError("程序版本目录没有可识别的受管收据")
    return value, node


def _launcher_before(tree: Tree, name: str) -> Node:
    node = tree.read("bin/" + name)
    if node.kind == "missing":
        return node
    lines = node.payload.decode("utf-8").splitlines()
    comment = "# " if name.endswith(".ps1") else "@rem "
    if len(lines) < 2 or lines[0] != comment + LAUNCHER_HEADER or not lines[1].startswith(comment):
        raise InstallerError("已有入口不属于受管 Windows 安装器，拒绝覆盖")
    encoded = lines[1][len(comment):]
    if (len(encoded) > ((LAUNCHER_IDENTITY_LIMIT + 2) // 3) * 4
            or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", encoded, re.ASCII)):
        raise InstallerError("已有入口的受管身份编码不合法，拒绝覆盖")
    try:
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(decoded) > LAUNCHER_IDENTITY_LIMIT:
            raise ValueError("受管身份超过有界容量")
        identity = unique_json(decoded)
    except (ValueError, UnicodeError) as exc:
        raise InstallerError("已有入口的受管身份编码不合法，拒绝覆盖") from exc
    if (not isinstance(identity, dict) or set(identity) != {"install_root", "version", "archive_sha256", "cli_options"}
            or identity["install_root"] != str(tree.root)
            or not isinstance(identity["version"], str) or not VERSION_PATTERN.fullmatch(identity["version"])
            or not isinstance(identity["archive_sha256"], str) or not DIGEST_PATTERN.fullmatch(identity["archive_sha256"])
            or not isinstance(identity["cli_options"], list) or not all(isinstance(item, str) for item in identity["cli_options"])):
        raise InstallerError("已有入口的受管身份不合法，拒绝覆盖")
    receipt, _ = _receipt(tree, "versions/" + identity["version"] + "-" + identity["archive_sha256"] + "/" + VERSION_RECEIPT,
                          identity["version"], identity["archive_sha256"])
    if (receipt is None or receipt["phase"] not in {"activated", "complete"}
            or receipt["cli_options"] != identity["cli_options"] or node.payload != _launcher_bodies(identity)[name]):
        raise InstallerError("已有入口与受管程序收据不一致，拒绝覆盖")
    return node


def _require_private_install_root(path: Path) -> None:
    """受管写入前只读断言根的真实 owner/protected DACL，不修复未知权限。

    新根由已有 mkdir(0700) 原语创建私有 SD；既有空根也必须通过同一 SDK
    的真实 ACL 断言，不能凭空目录、POSIX mode 或持锁认领共享可写位置。
    Directory 的祖先锚仅在活句柄期禁止换名；本断言不评估父目录授予外部
    用户的 DELETE_CHILD，因此不代表关闭安装句柄后整条父链的持久安全证明。
    """
    if os.name == "nt":
        from lib.windows_fs import assert_private
        assert_private(path)


def install(args) -> dict:
    """执行程序安装；失败保留现场，绝不自行回退中央 current 或删除旧版本。"""
    phase, root = "preflight", None
    runner = SetupRunner(timeout=1800)
    token = ACTIVE_RUNNER.set(runner)
    try:
        _validate_host()
        if not VERSION_PATTERN.fullmatch(args.version) or not DIGEST_PATTERN.fullmatch(args.archive_sha256):
            raise InstallerError("版本必须为 X.Y.Z，SHA256 必须为 64 位小写十六进制")
        install_root, archive = _absolute(args.install_root), _absolute(args.archive)
        options = []
        if args.state_dir:
            options += ["--state-dir", str(_absolute(args.state_dir))]
        if args.host_home:
            options += ["--host-home", str(_absolute(args.host_home))]
        if (args.state_dir or os.environ.get("AGENT_WORKFLOW_STATE_DIR")) and not args.host_home:
            raise InstallerError("独立状态目录的激活需要显式 --host-home")
        identity = {"install_root": str(install_root), "version": args.version,
                    "archive_sha256": args.archive_sha256, "cli_options": options}
        launcher_bodies = _launcher_bodies(identity)
        data = _verified_archive(archive, args.archive_sha256)
        with ExitStack() as stack:
            stack.enter_context(absolute_directory(install_root, create=True))
            _require_private_install_root(install_root)
            stack.enter_context(directory_lock(install_root, "windows-program-install"))
            tree = stack.enter_context(Tree(install_root))
            root_node = tree.read(ROOT_RECEIPT)
            if root_node.kind == "missing":
                if os.listdir(tree.directories[""]):
                    raise InstallerError("安装根目录含未知内容，拒绝认领")
                _write(tree, ROOT_RECEIPT, ROOT_BYTES)
            elif root_node.payload != ROOT_BYTES:
                raise InstallerError("安装根目录不属于受管 Windows 安装器")
            if set(os.listdir(tree.directories[""])) - {ROOT_RECEIPT, "versions", "bin"}:
                raise InstallerError("安装根目录含未知内容，拒绝继续")
            tree.directory("bin", create=True)
            if set(os.listdir(tree.directory("bin"))) - {"awf-cli.ps1", "awf-cli.cmd"}:
                raise InstallerError("程序入口目录含未知内容，拒绝继续")
            before = {name: _launcher_before(tree, name) for name in ("awf-cli.ps1", "awf-cli.cmd")}
            relative = "versions/" + args.version + "-" + args.archive_sha256
            root = install_root / relative
            parent = tree.directory("versions", create=True)
            try:
                os.mkdir(root.name, 0o700, dir_fd=parent)
                os.fsync(parent)
                fresh = True
            except FileExistsError:
                fresh = False
            version_tree = stack.enter_context(Tree(root))
            record, record_node = _receipt(version_tree, VERSION_RECEIPT, args.version, args.archive_sha256)
            if fresh:
                phase = "extract"
                files = extract_payload(data, version_tree, args.version)
                phase = "environment"
                version_tree.check()
                version_tree.directory("venv", create=True)
                _prepare_environment(root, runner)
                record = {"schema_version": 1, "version": args.version, "archive_sha256": args.archive_sha256,
                          "phase": "environment_ready", "files": files, "cli_options": options}
                record_node = _write(version_tree, VERSION_RECEIPT, json_bytes(record))
            elif record is None:
                raise InstallerError("已有版本目录未完成受管准备，拒绝覆盖；请人工检查保留目录")
            elif record["phase"] == "activation_started":
                raise InstallerError("上次中央激活结果未知；请先使用物理 CLI runtime status/recover 核对，程序环境已保留",
                                     phase="activation_unknown")
            # 本地收据只证明目录归属，不能授权变更程序字节。重复安装也从本次
            # 同一已 hash 归档推导清单，再遍历全部实际文件，拒绝额外导入模块。
            expected_files = files if fresh else extract_payload(data, None, args.version)
            if record["files"] != expected_files:
                raise InstallerError("程序收据与已校验归档不一致")
            _validate_payload(version_tree, expected_files)
            stack.enter_context(absolute_directory(_python(root).parent))
            if not stat.S_ISREG(os.stat(_python(root), follow_symlinks=False).st_mode):
                raise InstallerError("私有解释器不是普通文件")
            phase = "runtime_install"
            tree.check(); version_tree.check()
            result = _cli(root, options, ["runtime", "install", str(root / "payload")])
            binding = validate_binding(result.get("runtime_binding"))
            phase = "activate_preview"
            preview = _cli(root, options, ["runtime", "activate", binding["content_id"], "--dry-run"], dry_run=True)
            if preview.get("can_apply") is not True or preview.get("runtime_binding") != binding:
                raise InstallerError("中央激活预览存在冲突或版本不一致")
            # 在首个可能改变中央状态的调用前持久化未知边界。即便进程丢失响应、
            # Ctrl+C 或返回坏 JSON，也保留解释器、载荷和该收据，不猜已回滚。
            phase = "activation_started"
            record.update(phase=phase, cli_options=options)
            record_node = _write(version_tree, VERSION_RECEIPT, json_bytes(record), expected=record_node)
            applied = _cli(root, options, ["runtime", "activate", binding["content_id"]])
            if (applied.get("new_task_allowed") is not True or applied.get("management_write_allowed") is not True
                    or applied.get("pending_activation") is not None or applied.get("issues") != []
                    or applied.get("runtime_binding") != binding):
                raise InstallerError("中央激活响应不能确认预期版本")
            record["phase"] = "activated"
            record_node = _write(version_tree, VERSION_RECEIPT, json_bytes(record), expected=record_node)
            phase = "publish_launchers"
            for name, body in launcher_bodies.items():
                _write(tree, "bin/" + name, body, expected=before[name])
            record["phase"] = "complete"
            _write(version_tree, VERSION_RECEIPT, json_bytes(record), expected=record_node)
            return {"phase": "complete", "install_root": str(install_root), "version_root": str(root),
                    "runtime_binding": binding, "launchers": [str(install_root / "bin" / name) for name in before]}
    except BaseException as exc:
        if isinstance(exc, (SystemExit, GeneratorExit)):
            raise
        code = exc.exit_code if isinstance(exc, InstallerError) else exc.returncode if isinstance(exc, subprocess.CalledProcessError) else 130 if isinstance(exc, KeyboardInterrupt) else 2
        actual_phase = exc.phase if isinstance(exc, InstallerError) and exc.phase != "preflight" else phase
        raise InstallerError(str(exc) or "安装已中断", phase=actual_phase, exit_code=code,
                             retained=str(root) if root is not None else None) from exc
    finally:
        ACTIVE_RUNNER.reset(token)
        runner.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--install-root", required=True, type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--host-home", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = install(args)
    except InstallerError as exc:
        value = {"schema_version": 1, "ok": False, "phase": exc.phase, "exit_code": exc.exit_code,
                 "error": str(exc), "retained_version_root": exc.retained}
        if args.json:
            print(json.dumps(value, ensure_ascii=False))
        else:
            print(f"[错误] 阶段 {exc.phase}：{exc}；保留目录：{exc.retained or '无'}", file=sys.stderr)
        return exc.exit_code
    if args.json:
        print(json.dumps({"schema_version": 1, "ok": True, "exit_code": 0, **result}, ensure_ascii=False))
    else:
        print("安装完成；程序目录：" + result["version_root"])
        print("请通过完整路径使用：" + result["launchers"][0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
