"""注册 awf-cli 用户命令；只创建入口链接，不复制源包或修改 shell 配置。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

from .catalog import clean


def install(bin_directory: Path) -> Path:
    """只新增缺失入口或接受相同链接，已有其他命令一律保留。

    symlink 的创建具有排他性，检查之后出现同名文件也不能被覆盖；不使用
    replace/强制 ln，也不追随待安装名称指向的其他文件写入任何内容。
    """
    directory=bin_directory.expanduser().absolute()
    for component in (directory,*directory.parents):
        if component.is_symlink():raise ValueError("命令目录不可经过符号链接："+str(component))
    source=Path(__file__).resolve().parents[1]/"workflow.sh"
    if not source.is_file() or not os.access(source,os.X_OK):
        raise ValueError("源包启动脚本缺失或不可执行："+str(source))
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/"awf-cli"
    if target.is_symlink():
        try:resolved=target.resolve(strict=True)
        except (OSError,RuntimeError):resolved=None
        if resolved == source:return target
    # lexists 同时覆盖损坏链接；不因它的目标不存在就覆盖这个已有入口。
    if os.path.lexists(target):raise ValueError("已有同名入口，已保留，请先核对："+str(target))
    try:target.symlink_to(source)
    except FileExistsError as exc:raise ValueError("命令入口被其他操作创建，已停止覆盖："+str(target)) from exc
    return target


def command_message(target: Path) -> str:
    """区分入口创建与命令就绪，不调整 PATH，也不执行 PATH 中的其他同名程序。

    按真实查找顺序核对首个可执行入口。若在它之前存在相对/空 PATH 项，
    换工作目录后就可能选到另一条命令，因此不能承诺“任意目录”均可用。
    """
    found=shutil.which("awf-cli")
    if found is None:
        return "入口已创建，但当前 PATH 找不到 awf-cli；可使用入口完整路径启动，或自行配置 PATH。"
    try:matches=Path(found).resolve(strict=True) == target.resolve(strict=True)
    except (OSError,RuntimeError):matches=False
    if not matches:
        return "入口已创建，但 PATH 优先解析到其他同名命令："+clean(found,8192)+"；已有命令和 PATH 均已保留。"
    for directory in os.get_exec_path():
        if not Path(directory).is_absolute():
            return "入口已创建，当前目录可找到本入口；PATH 含相对或空目录项，换目录后解析结果可能变化。"
        if Path(directory)/"awf-cli" == Path(found):break
    return "在任意目录输入 awf-cli 即可打开 TUI。"


def main(argv=None) -> int:
    caller=os.environ.pop("AGENT_WORKFLOW_CALLER_DIR",None)
    if caller:os.chdir(caller)
    parser=argparse.ArgumentParser(prog="awf-cli --install-cli",description="将 awf-cli 注册到用户命令目录，不修改 PATH 或 shell 配置。")
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
