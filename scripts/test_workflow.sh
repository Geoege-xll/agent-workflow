#!/usr/bin/env bash
# 唯一 unittest 入口：使用源包物理根和已有解释器选择器，不下载依赖或改变宿主配置。
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
SCRIPT_DIR="$(CDPATH= cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PACK_DIR="$(CDPATH= cd -P -- "${SCRIPT_DIR}/.." && pwd -P)"
cd -- "${PACK_DIR}"
# exec 使测试失败/中断直接成为入口的退出状态；不加重试，也不吞掉 unittest 输出。
exec bash "${PACK_DIR}/lib/python_runtime.sh" -B -X utf8 "${PACK_DIR}/scripts/test_workflow.py" "$@"
