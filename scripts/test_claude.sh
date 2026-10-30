#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PACK_DIR}"
# 共享正文、薄入口、所有权保护和失败回滚与原有 Claude 合同一同回归。
bash "${PACK_DIR}/lib/python_runtime.sh" -m unittest -v tests.test_claude_workflow tests.test_claude_instructions tests.test_shared_memory_contract
