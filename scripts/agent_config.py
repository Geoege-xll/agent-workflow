#!/usr/bin/env python3
"""独立原生 Agent 配置入口；从安装根定位，仅使用已有 Python 标准库。"""

import sys
from pathlib import Path

# 默认 python3 可能较旧，必须先诊断，再导入需要 tomllib 的配置核心。
if sys.version_info < (3, 11):
    sys.stderr.write("需要 Python >= 3.11。请使用 bash scripts/agent_config.sh，或明确使用现有 python3.11+ 运行本文件。\n")
    raise SystemExit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from native_config.cli import main

raise SystemExit(main())
