"""注册显式源码开发命令 awf-dev；正式 awf-cli 由 Homebrew 提供。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import sys

from lib.central.runtime_project import absolute_directory
from .catalog import clean


DEVELOPMENT_COMMAND = "awf-dev"


def install(bin_directory: Path) -> Path:
    """只新增源码 awf-dev 或接受相同直链，已有命令和正式入口一律保留。

    公开调用签名保持不变，但不再占用正式命令 awf-cli。目录创建与链接发布
    复用中央运行时的逐段 no-follow/dir_fd 原语，目录在操作中被换链时不向
    新目标写入，也不能把原目录中的发布结果错误报告为当前路径已就绪。
    """
    directory=bin_directory.expanduser().absolute()
    source=Path(__file__).resolve().parents[1]/"workflow.sh"
    if not source.is_file() or not os.access(source,os.X_OK):
        raise ValueError("源包启动脚本缺失或不可执行："+str(source))
    # 发行包的入口归 Homebrew 管理，不能被另起的开发软链冒用。只要发行标记
    # 存在（包括损坏链接）就先拒绝，既不猜测来源，也不创建用户 bin 目录。
    if os.path.lexists(source.parent/"manager/release.json"):
        raise ValueError("发行包的正式 awf-cli 由 Homebrew 提供；请从源码 workflow.sh --install-cli 注册 awf-dev")
    target=directory/DEVELOPMENT_COMMAND
    with absolute_directory(directory,create=True) as descriptor:
        try:before=os.stat(DEVELOPMENT_COMMAND,dir_fd=descriptor,follow_symlinks=False)
        except FileNotFoundError:before=None
        if before is not None:
            # 只认可本安装器生成的绝对直链，不把任意间接链或损坏链接当成归属
            # 证明。读取前后核对同一 inode，避免检查时被另一进程换成新入口。
            if stat.S_ISLNK(before.st_mode):
                link=os.readlink(DEVELOPMENT_COMMAND,dir_fd=descriptor)
                after=os.stat(DEVELOPMENT_COMMAND,dir_fd=descriptor,follow_symlinks=False)
                stamp=lambda info:(info.st_dev,info.st_ino,info.st_mode,info.st_nlink,
                                   info.st_size,info.st_mtime_ns,info.st_ctime_ns)
                if link == str(source) and stamp(before) == stamp(after):
                    return target
            raise ValueError("已有同名入口，已保留，请先核对："+str(target))
        # symlink 是排他创建：检查后出现同名文件也会失败，不能覆盖对方保存；
        # 不使用 replace/强制 ln，失败时保留已存在的文件及已创建的普通目录。
        try:os.symlink(str(source),DEVELOPMENT_COMMAND,dir_fd=descriptor)
        except FileExistsError as exc:raise ValueError("命令入口被其他操作创建，已停止覆盖："+str(target)) from exc
    return target


def command_message(target: Path) -> str:
    """区分入口创建与命令就绪，不调整 PATH，也不执行 PATH 中的其他同名程序。

    按真实查找顺序核对首个可执行入口。若在它之前存在相对/空 PATH 项，
    换工作目录后就可能选到另一条命令，因此不能承诺“任意目录”均可用。
    """
    found=shutil.which(DEVELOPMENT_COMMAND)
    if found is None:
        return "开发入口已创建，但当前 PATH 找不到 awf-dev；可使用入口完整路径启动，或自行配置 PATH。"
    try:matches=Path(found).resolve(strict=True) == target.resolve(strict=True)
    except (OSError,RuntimeError):matches=False
    if not matches:
        return "入口已创建，但 PATH 优先解析到其他同名命令："+clean(found,8192)+"；已有命令和 PATH 均已保留。"
    for directory in os.get_exec_path():
        if not Path(directory).is_absolute():
            return "入口已创建，当前目录可找到本入口；PATH 含相对或空目录项，换目录后解析结果可能变化。"
        if Path(directory)/DEVELOPMENT_COMMAND == Path(found):break
    return "在任意目录输入 awf-dev 即可打开源码 TUI；正式 awf-cli 仍由 Homebrew 提供。"


def main(argv=None) -> int:
    caller=os.environ.pop("AGENT_WORKFLOW_CALLER_DIR",None)
    if caller:os.chdir(caller)
    parser=argparse.ArgumentParser(prog="workflow.sh --install-cli",description="将显式源码开发命令 awf-dev 注册到用户命令目录；正式 awf-cli 由 Homebrew 提供，不修改 PATH 或 shell 配置。")
    parser.add_argument("--bin-dir",type=Path,default=Path.home()/".local/bin",help="默认 ~/.local/bin；也可指定已有 PATH 目录")
    args=parser.parse_args(argv)
    try:
        target=install(args.bin_dir)
        print("已安装命令入口："+clean(target,8192))
        print(command_message(target))
        return 0
    except (OSError,ValueError) as exc:
        print("[错误] "+clean(exc,8192),file=sys.stderr);return 2


if __name__ == "__main__":raise SystemExit(main())
