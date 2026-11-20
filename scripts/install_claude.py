#!/usr/bin/env python3
"""供用户在 macOS／Linux 终端直接运行的独立 Claude Code 安装入口。"""

import argparse
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


MARKET = "xy-workflow"
PLUGIN = "xy-workflow@xy-workflow"
URL = "https://github.com/Geoege-xll/agent-workflow.git"
REF = "plugins-claude-stable"
SOURCE = (
    "本机已安装的 xy-workflow 插件来源为 https://github.com/Geoege-xll/agent-workflow 。"
    "此说明仅涉及从该安装版本已核实的物理根运行本地工作流校验、读取当前派发身份的偏好，"
    "以及在当前项目和请求范围内读取或写入任务记录。"
)
# 旧版手动配置使用过这条精确英文描述。保留原文，避免重复添加，也不把任意提到仓库的文本当作同意。
PREVIOUS_SOURCE = (
    "- **Installed workflow CLI (across projects)**: The locally installed xy-workflow plugin from "
    "https://github.com/Geoege-xll/agent-workflow is a trusted code source solely for its packaged "
    "helpers performing local workflow validation, reading dispatch preferences, and maintaining "
    "workflow records for the current project and task. This source exception grants no trust for "
    "network transfers, repository publication, arbitrary scripts, credentials, or changes to permission settings."
)


def unique_object(pairs):
    """重名 JSON 字段无法无损合并，及早拒绝，以免写回后丢掉用户设置。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("用户设置中有重复 JSON 字段，请先处理冲突")
        result[key] = value
    return result


def read_settings(path):
    """通过同一普通文件描述符取得字节与权限，拒绝替换用户的符号链接或特殊文件。"""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, 0o600, {}
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("用户 settings.json 必须是独立普通文件")
        raw = stream.read()
    settings = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(settings, dict):
        raise ValueError("用户 settings.json 必须是 JSON 对象")
    return raw, stat.S_IMODE(info.st_mode), settings


def environment(settings):
    """缺少数组表示沿用宿主默认。现有空数组则是用户显式取舍，必须原样保留。"""
    auto = settings.get("autoMode", {})
    if not isinstance(auto, dict):
        raise ValueError("已有 autoMode 格式不兼容，请检查用户设置")
    entries = auto.get("environment", ["$defaults"])
    if not isinstance(entries, list) or not all(isinstance(value, str) for value in entries):
        raise ValueError("已有 autoMode.environment 必须是字符串数组")
    return entries


@contextmanager
def install_lock(directory):
    # 在物理用户目录上加锁，多个项目启动的安装器共享同一把锁，无需持久化标记或拒绝记录。
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def check_declaration(settings):
    """官方市场列表可能仍来自缓存，同时核对本次准备修改的用户文件中的来源声明。"""
    declarations = settings.get("extraKnownMarketplaces", {})
    if not isinstance(declarations, dict):
        raise ValueError("用户设置中的市场声明格式不兼容")
    if MARKET in declarations:
        declaration = declarations[MARKET]
        if not isinstance(declaration, dict) or declaration.get("source") != {"source": "git", "url": URL, "ref": REF}:
            raise ValueError("用户设置已声明不同来源的同名市场")


def exchange_files(staged, target):
    """一次系统调用交换两个名字。原文件系统不支持时退出，不降级为可覆盖的 rename。"""
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameatx_np" if sys.platform == "darwin" else "renameat2", None)
    if function is None:
        raise OSError(errno.ENOTSUP, "当前系统不支持安全交换设置文件，可按手册配置来源说明")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # macOS RENAME_SWAP 和 Linux RENAME_EXCHANGE 的标志均为 2，两个名字位于同一目录。
        if function(directory, os.fsencode(staged.name), directory, os.fsencode(target.name), 2):
            code = ctypes.get_errno()
            raise OSError(code, "文件系统无法安全交换设置文件：" + os.strerror(code))
    finally:
        os.close(directory)


def save_source(path):
    """确认后重新读取最新设置，原子发布单个新增条目。调用方持有同一用户目录锁。"""
    raw, mode, settings = read_settings(path)
    check_declaration(settings)
    entries = environment(settings)
    if SOURCE in entries or PREVIOUS_SOURCE in entries:
        return
    settings.setdefault("autoMode", {})["environment"] = [*entries, SOURCE]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix="settings.xy-workflow-", suffix=".json", delete=False) as stream:
        staged = Path(stream.name)
        cleanup = True
        try:
            json.dump(settings, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
            # 其它设置编辑器不持有安装器的目录锁。检测写入期间可观察到的修改，保留对方结果。
            if read_settings(path)[:2] != (raw, mode):
                raise ValueError("用户设置在保存期间发生变化，请重新运行 --configure-source")
            if raw is None:
                os.link(staged, path)
            else:
                # 发布之前比对仍会有间隙。原子交换把实际换出的文件放到 staged 名下，
                # 即使最后一瞬间其它编辑器刚发布了一份新设置，其版本也仍然可定位。
                cleanup = False
                try:
                    exchange_files(staged, path)
                except OSError:
                    cleanup = True  # 系统调用失败时双方都在原位，临时文件仍属于本安装器。
                    raise
                try:
                    unchanged = read_settings(staged)[:2] == (raw, mode)
                except (OSError, ValueError):
                    unchanged = False  # 被换出的是意外格式或节点，也必须完整保留。
                if not unchanged:
                    # 回换后，导致冲突的原文件重新成为活动设置。保留另一份实际文件，
                    # 即使在两次交换之间又有第三方保存，仍可通过报错中的路径找回它。
                    try:
                        exchange_files(staged, path)
                    except OSError as error:
                        raise ValueError(f"用户设置发生变化，无法回换。已保全的文件位于 {staged}") from error
                    raise ValueError(f"用户设置在发布瞬间发生变化，已回换。另一版本保存在 {staged}，请核对。")
                cleanup = True
        finally:
            if cleanup:
                staged.unlink(missing_ok=True)


def claude(cwd, *args, listing=False):
    # 管理命令从临时空目录运行，避免某个项目的启停设置或附加市场影响用户级判断。
    # 父进程已把自定义配置目录转成绝对路径，切换 CLI 工作目录后仍指向同一位置。
    result = subprocess.run(["claude", "plugin", *args], cwd=cwd, check=True, timeout=180,
                            stdout=subprocess.PIPE if listing else None, text=True)
    if listing:
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Claude 官方列表格式不可识别")
        return rows


def check_market(cwd):
    rows = [r for r in claude(cwd, "marketplace", "list", "--json", listing=True) if r.get("name") == MARKET]
    if not rows:
        return False
    if len(rows) != 1 or tuple(rows[0].get(k) for k in ("source", "url", "ref")) != ("git", URL, REF):
        raise ValueError("同名市场的来源与正式 Git 地址或分支不一致，请通过 Claude 检查现有市场")
    return True


def user_plugin(cwd):
    rows = [r for r in claude(cwd, "list", "--json", listing=True) if r.get("id") == PLUGIN]
    if any(r.get("scope") not in ("user", "project", "local", "managed") for r in rows):
        raise ValueError("官方列表未明确插件的安装范围")
    matches = [r for r in rows if r["scope"] == "user"]
    if len(matches) > 1 or (matches and type(matches[0].get("enabled")) is not bool):
        raise ValueError("用户级插件的启用状态不明确")
    return matches[0] if matches else None


def install(cwd, path):
    _, _, settings = read_settings(path)
    # 官方 CLI 也会修改用户设置。先验证目标字段及已声明来源，避免覆盖损坏配置或未加载的冲突声明。
    environment(settings)
    check_declaration(settings)
    known = check_market(cwd)
    previous = user_plugin(cwd)
    if not known:
        if previous is not None:
            raise ValueError("已有用户级安装但缺少匹配的市场来源，请先核实原安装")
        claude(cwd, "marketplace", "add", URL + "#" + REF, "--scope", "user")
        if not check_market(cwd):
            raise ValueError("添加市场后未找到预期正式来源")
    if previous is None:
        claude(cwd, "install", PLUGIN, "--scope", "user")
    current = user_plugin(cwd)
    if current is None or not check_market(cwd):
        raise ValueError("官方列表未确认来自预期市场的用户级安装")
    if not current["enabled"]:
        raise ValueError("用户级插件已停用。如需启用，请运行 claude plugin enable " + PLUGIN + " --scope user")
    return previous is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure-source", action="store_true", help="已有安装也显示可选的来源设置")
    args = parser.parse_args()
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser().resolve()
    os.environ["CLAUDE_CONFIG_DIR"] = str(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = root / "settings.json"
    with tempfile.TemporaryDirectory(prefix="xy-claude-install-") as cwd:
        with install_lock(root):
            first = install(cwd, settings)
            entries = environment(read_settings(settings)[2])
        print("已核实用户级插件安装并启用。")
        if SOURCE in entries or PREVIOUS_SOURCE in entries:
            print("已有来源说明，所有项目可复用。")
            return
        if not first and not args.configure_source:
            print("沿用现有来源设置。需要补选时请加 --configure-source。")
            return
        print(f"可选：在 {settings} 的 autoMode.environment 中添加下列说明，供所有项目使用。")
        print(SOURCE)
        print("Claude 仍会执行权限询问、拒绝规则和组织策略。")
        if not sys.stdin.isatty() or input("添加请键入 yes，直接回车可跳过：").strip() != "yes":
            print("已跳过来源设置。稍后可加 --configure-source 补选。")
            return
        # 等待用户输入期间不占用锁。重新验证来源与启用状态，随后合并最新磁盘数据。
        with install_lock(root):
            current = user_plugin(cwd)
            if not check_market(cwd) or current is None or not current["enabled"]:
                raise ValueError("确认期间安装来源或启用状态发生变化，请先检查官方列表")
            save_source(settings)
        print("已保存。可在任一项目运行 claude auto-mode config 核对生效的来源说明。")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, EOFError, subprocess.SubprocessError) as error:
        sys.exit("安装或来源设置未完成：" + str(error))
