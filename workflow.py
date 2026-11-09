"""源码 CLI 的原生入口；发行性质与业务行为统一由 manager.cli 决定。"""

# Windows 必须先检查隔离标记，再导入任何标准库。sys 是内建模块；如果先
# 导入 pathlib/ctypes/argparse，调用者的 PYTHONPATH 或业务 cwd 便可能抢先
# 执行同名模块。不能在此处通过重新启动来弥补已经发生的非隔离导入。
import sys

if sys.platform == "win32" and not sys.flags.isolated:
    sys.stderr.write("[错误] Windows 源码入口必须以 Python -I 隔离模式启动。\n")
    raise SystemExit(2)

if sys.version_info < (3, 11):
    sys.stderr.write("[错误] 源码入口需要已有的 Python 3.11 或更高版本。\n")
    raise SystemExit(2)

if sys.platform == "win32" and (sys.implementation.name != "cpython" or sys.maxsize != 2**63 - 1):
    sys.stderr.write("[错误] Windows 源码入口需要 CPython 3.11+ x64。\n")
    raise SystemExit(2)

import os
from pathlib import Path


def main() -> int:
    """只绑定自身物理源码根，不切换调用 cwd，也不重写任何业务参数。"""
    source_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(source_root))
    # 此变量仅供旧 Bash 启动器跨 cd 传递目录。当前入口从未切换 cwd，不能
    # 让继承环境中的旧值驱动共享 CLI 跳到另一个业务目录。
    os.environ.pop("AGENT_WORKFLOW_CALLER_DIR", None)
    from manager.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
