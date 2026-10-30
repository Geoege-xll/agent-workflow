#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PACK_DIR}"
bash "${PACK_DIR}/lib/python_runtime.sh" -m unittest tests.test_prototype_workspace -v
