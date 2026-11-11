#!/usr/bin/env bash
# 独立服务固定入口：包内携带相同解释器选择器，不依赖工作流源码或修改 PATH。
set -euo pipefail
AGENT_CONFIG_SCRIPT_DIR="$(CDPATH= cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec bash "${AGENT_CONFIG_SCRIPT_DIR}/python_runtime.sh" -B -X utf8 "${AGENT_CONFIG_SCRIPT_DIR}/agent_config.py" "$@"
