#!/usr/bin/python3
"""维护者在安装或更新 macOS 本地 Claude 候选后，核对载荷并发布有期的文件系统证明。"""

import argparse
import datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile


PLUGIN = "xy-workflow"
MARKET = "xy-workflow-local"
LOCAL_ID = PLUGIN + "@" + MARKET
STABLE_ID = PLUGIN + "@" + PLUGIN
TRUST_DIR = Path("Library/Application Support/agent-workflow/candidate-verification")
SCRIPT = "verify_claude_candidate.py"
CLAUDE = "/opt/homebrew/bin/claude"
APFS = "/System/Library/Filesystems/apfs.fs/Contents/Resources/apfs.util"
MTREE = "/usr/sbin/mtree"
RECEIPT = "receipt.json"
# APFS 的递归计数覆盖子文件内容变更，chmod 并不会提高计数。mtree 只比对元数据，
# 不选择 cksum、sha256 或 xattrsdigest 等会读取载荷的关键字。
METADATA = "type,inode,mode,nlink,size,ctime"
ROOT_LABELS = ("read_from_folder", "install_path")
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def parse_json(body):
    """拒绝 JSON 重复键，防止同一份登记或 pin 被两个读取者解释为不同的来源。"""
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("JSON 存在重复字段：" + key)
            obj[key] = value
        return obj
    return json.loads(body, object_pairs_hook=unique)


def physical_path(value):
    """输入必须已经是物理绝对路径；不能将链接或含上级跳转的输入清洗成可信路径。"""
    if not isinstance(value, str):
        raise ValueError("缺少物理绝对路径")
    path = Path(value)
    if not path.is_absolute() or str(path.resolve(strict=True)) != value:
        raise ValueError("路径不规范或包含符号链接：" + value)
    return path


def protected(path):
    """用户级信任材料只允许当前系统用户持有，其他用户和组不得改写。"""
    info = path.lstat()
    # 各系统报告的链接权限位可能不同；先识别链接，才能准确说明违反的来源约束。
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("用户级核验材料不能是符号链接：" + str(path))
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise ValueError("用户级核验材料不能有额外硬链接：" + str(path))
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("用户级核验材料所有者或写权限不符：" + str(path))


def file_bytes(path, limit=None):
    # 在读取前检查实际打开的对象；非阻塞模式保证错误的 FIFO 也能立即被拒绝。
    physical_path(str(path))
    with os.fdopen(os.open(path, FILE_FLAGS), "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("要求普通文件：" + str(path))
        body = source.read() if limit is None else source.read(limit + 1)
        if limit is not None and len(body) > limit:
            raise ValueError("登记文件超过大小限制：" + str(path))
        return body


def read_pin(directory):
    pin = parse_json(file_bytes(directory / "pin.json", 64 * 1024))
    required = {"marketplace_path", "sha256", "version"}
    if (not isinstance(pin, dict) or not required <= pin.keys() <= required | {"source_revision"}
            or not all(isinstance(value, str) for value in pin.values())
            or not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"])
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", pin["version"])
            or ("source_revision" in pin and not re.fullmatch(r"[a-f0-9]{40}", pin["source_revision"]))):
        raise ValueError("候选 pin 字段、版本或摘要无效")
    return pin


def official_list(arguments, home):
    # 只查询当前项目语境下的两份官方登记。固定本机已安装的宿主二进制与用户配置，
    # 不从项目 PATH 选择同名程序，也不把项目注入的解释器/加载器环境传给子进程。
    env = {"HOME": str(home), "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "DISABLE_AUTOUPDATER": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    result = subprocess.run([CLAUDE, "plugin", *arguments, "list", "--json"], env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30, check=True)
    rows = parse_json(result.stdout)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Claude 登记格式无效")
    return rows


def registered_roots(home, market, version, markets, plugins):
    candidates = [row for row in markets if row.get("name") == MARKET]
    if (len(candidates) != 1 or candidates[0].get("source") != "directory"
            or candidates[0].get("path") != str(market)
            or candidates[0].get("installLocation") != str(market)):
        raise ValueError("候选市场名称、目录来源或安装位置与 pin 不一致")
    # 同一市场目录如果又被另一个市场名称登记，此时来源对应关系不唯一。
    for row in markets:
        if row is not candidates[0] and any(
                isinstance(row.get(key), str) and os.path.realpath(row[key]) == str(market)
                for key in ("path", "installLocation")):
            raise ValueError("多个市场指向同一候选来源")

    local = []
    for row in plugins:
        identity = row.get("id")
        if not isinstance(identity, str):
            raise ValueError("Claude 插件登记缺少身份")
        if identity.partition("@")[0] != PLUGIN:
            continue
        if identity == STABLE_ID and row.get("enabled") is False and row.get("projectEnabled", False) is False:
            continue
        if (identity != LOCAL_ID or row.get("scope") != "user" or row.get("enabled") is not True
                or row.get("projectEnabled", False) is not False):
            raise ValueError("同名插件有未知来源、并行启用或非用户级登记")
        local.append(row)
    if len(local) != 1:
        raise ValueError("需要唯一已启用的用户级候选插件")
    row = local[0]
    if row.get("version") != version or row.get("folderVersion") != version:
        raise ValueError("Claude 登记版本与候选 pin 不符")
    source = physical_path(row.get("readFromFolder"))
    cache = physical_path(row.get("installPath"))
    if (source != market / "plugins" / PLUGIN
            or cache not in (source, home / ".claude/plugins/cache" / MARKET / PLUGIN / version)):
        raise ValueError("已登记插件目录与候选市场或本机缓存位置不符")
    # directory 市场索引本身在插件 ZIP 之外。明确核对发布者当前生成的声明，
    # 防止原索引被改为其它相对路径或附加可执行组件，而 list 仍显示旧缓存。
    manifest = parse_json(file_bytes(market / ".claude-plugin/marketplace.json", 64 * 1024))
    if manifest != {"name": MARKET, "owner": {"name": "Agent Workflow"},
                    "plugins": [{"name": PLUGIN, "source": "./plugins/" + PLUGIN}]}:
        raise ValueError("候选市场索引与已登记的插件来源不符")
    return source, cache


def expected_files(archive_bytes, pin):
    # 对同一份不可变字节先验摘要再开 ZIP，无需解包、写入临时文件或运行包内解释器。
    if hashlib.sha256(archive_bytes).hexdigest() != pin["sha256"]:
        raise ValueError("插件主 ZIP 与可信 pin 的 SHA-256 不符")
    files = {}
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for entry in archive.infolist():
            name = entry.filename
            mode = entry.external_attr >> 16
            if (not re.fullmatch(r"[a-zA-Z0-9._@+ /-]+", name) or name.startswith("/") or "\\" in name or name != entry.orig_filename
                    or any(part in ("", ".", "..") for part in name.split("/")) or name in files
                    or mode not in (stat.S_IFREG | 0o644, stat.S_IFREG | 0o755)):
                raise ValueError("ZIP 含歧义路径或非官方资源模式：" + name)
            files[name] = (hashlib.sha256(archive.read(entry)).digest(), entry.file_size, mode & 0o111)
        metadata = parse_json(archive.read(".claude-plugin/plugin.json"))
        provenance = parse_json(archive.read("sources.json"))
        if (not isinstance(metadata, dict) or metadata.get("name") != PLUGIN
                or metadata.get("version") != pin["version"] or not isinstance(provenance, dict)
                or provenance.get("host") != "claude" or provenance.get("plugin_name") != PLUGIN
                or provenance.get("plugin_version") != pin["version"]):
            raise ValueError("ZIP 不是固定版本的 Claude 插件主包")
    return files


def verify_tree(root, files):
    """按目录描述符逐层核验，包括隐藏文件；不跟随扫描期间替换的子目录或文件链接。"""
    directories = {str(parent) for name in files for parent in Path(name).parents}
    seen = set()

    def walk(directory, prefix):
        if os.fstat(directory).st_dev != device:
            raise ValueError("插件树中存在另一挂载卷")
        for child in os.listdir(directory):
            name = prefix + child
            if name in directories:
                sub = os.open(child, DIR_FLAGS, dir_fd=directory)
                try:
                    walk(sub, name + "/")
                finally:
                    os.close(sub)
                continue
            if name not in files:
                raise ValueError("插件含 ZIP 外资源：" + str(root / name))
            with os.fdopen(os.open(child, FILE_FLAGS, dir_fd=directory), "rb") as source:
                info = os.fstat(source.fileno())
                expected_digest, size, execute_bits = files[name]
                # 只读归档声明的长度加一，及时拒绝被换成大文件或边读边增长的资源。
                if (not stat.S_ISREG(info.st_mode) or info.st_dev != device or info.st_nlink != 1 or info.st_size != size
                        or info.st_mode & 0o7111 != execute_bits
                        or hashlib.sha256(source.read(size + 1)).digest() != expected_digest):
                    raise ValueError("插件文件类型、执行位或内容不符：" + str(root / name))
                seen.add(name)

    descriptor = os.open(root, DIR_FLAGS)
    try:
        device = os.fstat(descriptor).st_dev
        walk(descriptor, "")
    finally:
        os.close(descriptor)
    if seen != files.keys():
        raise ValueError("插件缺少 ZIP 中的资源：" + str(root / min(files.keys() - seen)))


def trust_directory():
    # 从操作系统账户而非调用者可指定的 HOME、工作目录、插件参数定位唯一外部信任根。
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if sys.platform != "darwin" or not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError("请用本机 /usr/bin/python3 -I -B 调用独立核验器")
    if (os.environ.get("HOME", str(home)) != str(home) or
            os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")) != str(home / ".claude")):
        raise ValueError("当前 Claude 配置目录与本机候选登记不符")
    directory = home / TRUST_DIR
    if physical_path(__file__) != directory / SCRIPT:
        raise ValueError("核验器必须由发布者安装在固定用户目录")
    # 核对从账户目录到信任目录的每一级，避免第三方可借可写父目录替换固定材料。
    path = home
    ancestors = [path]
    protected(path)
    for part in TRUST_DIR.parts:
        path = path / part
        protected(path)
        ancestors.append(path)
    materials = [directory / name for name in (SCRIPT, "pin.json", "claude-plugin.zip")]
    for item in materials:
        protected(item)
        if not stat.S_ISREG(item.lstat().st_mode):
            raise ValueError("固定核验材料必须为普通文件：" + str(item))
    # POSIX 模式不包含 macOS 的扩展 ACL。固定信任目录到用户目录之间允许默认的 deny delete，
    # 但不能让另一个身份取得任何写能力。遇到未知 ACL 展示格式时保守退出。
    listing = system_read(["/bin/ls", "-ledn", *map(str, [*ancestors, *materials])]).decode()
    write_rights = {"write", "append", "add_file", "add_subdirectory", "delete", "delete_child",
                    "writeattr", "writeextattr", "writesecurity", "chown"}
    for line in listing.splitlines():
        if re.match(r"^\s*\d+: ", line):
            if " deny " in line:
                continue
            rule = line.partition(" allow ")
            if not rule[1] or write_rights.intersection(rule[2].split(",")):
                raise ValueError("固定信任材料有可写或不明的 ACL")
    return directory


def installation(directory):
    """维护程序只接受官方登记的根，业务会话的实际加载身份另由宿主交付。"""
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    pin = read_pin(directory)
    market = physical_path(pin["marketplace_path"])
    roots = registered_roots(home, market, pin["version"], official_list(["marketplace"], home), official_list([], home))
    if any(directory == root or root in directory.parents or directory in root.parents for root in roots):
        raise ValueError("固定信任材料不能位于候选插件内")
    return pin, roots


def system_read(command):
    # 固定系统工具与 locale，关闭输入。stdout 仅在格式与退出状态均明确时作为证据。
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
                            timeout=120, check=True)
    if result.stderr:
        raise ValueError("系统元数据查询有诊断：" + result.stderr.decode(errors="replace").strip())
    return result.stdout


def boot_session():
    # 重启后重新核对，避免把上一引导中已卸载卷的设备号解释为当前卷身份。
    return str(uuid.UUID(system_read(["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"]).decode().strip()))


def generation(root):
    output = system_read([APFS, "-S", str(root)]).decode()
    counts = re.findall(r"(?m)^gen-count: ([1-9][0-9]*)$", output)
    if len(counts) != 1:
        raise ValueError("该物理根未提供有效 APFS 递归变更计数：" + str(root))
    info = physical_path(str(root)).stat()
    return {"path": str(root), "device": info.st_dev, "inode": info.st_ino, "generation": int(counts[0])}


def metadata(root):
    # 按 inode 和纳秒 ctime 检查同名替换，按 mode 检查内核递归计数不覆盖的执行位改动。
    # 将生成时刻等非规格注释排除，保证文件树不变时两次读取可以逐字节比对。
    spec = system_read([MTREE, "-c", "-n", "-P", "-x", "-k", METADATA, "-p", str(root)])
    return b"".join(line for line in spec.splitlines(keepends=True) if not line.lstrip().startswith(b"#"))


def publish(directory, name, body):
    """只在固定私有目录内原子替换一个普通数据文件，异常时收回尚未发布的临时文件。"""
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
        staged = Path(output.name)
        try:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
            os.replace(staged, directory / name)
        finally:
            staged.unlink(missing_ok=True)


def attest(expires_at):
    """在安装事务内验证 ZIP、市场、两份载荷及前后元数据，最后才发布生效收据。"""
    directory = trust_directory()
    # 同一账户的并行更新不能交叉发布两代规格。旧收据先撤销，失败后必须由维护者重新核对。
    descriptor = os.open(directory, DIR_FLAGS)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (directory / RECEIPT).unlink(missing_ok=True)
        expires = datetime.datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        if expires.strftime("%Y-%m-%dT%H:%M:%SZ") != expires_at:
            raise ValueError("到期时间必须是完整的 UTC 格式 YYYY-MM-DDTHH:MM:SSZ")
        if expires <= datetime.datetime.now(datetime.timezone.utc):
            raise ValueError("维护者指定的 UTC 到期时间已过")
        pin, roots = installation(directory)
        files = expected_files(file_bytes(directory / "claude-plugin.zip"), pin)
        versioned = {}
        for root in dict.fromkeys(roots):
            # 只在运维动作中请求 APFS 维护统计。本命令无须管理员权限，不改变 Claude 权限设置。
            system_read([APFS, "-M", str(root)])
            before = generation(root)
            first = metadata(root)
            verify_tree(root, files)
            if generation(root) != before or metadata(root) != first:
                raise ValueError("完整性核对期间插件发生变化：" + str(root))
            versioned[root] = (before, first)
        if installation(directory) != (pin, roots):
            raise ValueError("核对期间候选 pin 或官方登记发生变化")
        receipt = {"schema": 1, "id": str(uuid.uuid4()), "plugin_id": LOCAL_ID, "pin": pin,
                   "boot_session": boot_session(), "issued_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "expires_at": expires_at, "roots": {}}
        if receipt["issued_at"] >= expires_at:
            raise ValueError("核对期间证明已过期")
        for label, root in zip(ROOT_LABELS, roots):
            proof, spec = versioned[root]
            if generation(root) != proof or metadata(root) != spec:
                raise ValueError("发布前插件元数据已变化：" + str(root))
            publish(directory, label + ".mtree", spec)
            receipt["roots"][label] = {**proof, "metadata_sha256": hashlib.sha256(spec).hexdigest()}
        publish(directory, RECEIPT, (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode())
        return receipt
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--expires-at", required=True, help="维护者选择的证明到期时间，格式为 UTC YYYY-MM-DDTHH:MM:SSZ")
    args = parser.parse_args()
    try:
        receipt = attest(args.expires_at)
        print("已核实候选并发布维护收据：" + receipt["pin"]["sha256"] + "，到期 " + receipt["expires_at"])
    except (ValueError, OSError, KeyError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print("候选安装核验失败：" + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
