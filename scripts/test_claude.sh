#!/usr/bin/env bash
# 保留原测试范围；统一入口负责物理根、解释器选择和失败传播。
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec bash "${SCRIPT_DIR}/test_workflow.sh" claude
