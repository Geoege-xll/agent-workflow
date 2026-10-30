#!/usr/bin/env bash
# 从任意工作目录启动一次性安装包；项目路径由参数或终端拖入提供。
set -euo pipefail
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${INSTALLER_DIR}/lib/python_runtime.sh" \
  "${INSTALLER_DIR}/lib/install_workflow.py" "$@"
