#!/usr/bin/env bash
# 插件物理目录是唯一入口来源；不搜索源码、缓存、相邻发行包，也不修改 PATH。
set -euo pipefail
AGENT_CONFIG_LAUNCHER_DIR="$(CDPATH= cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
for AGENT_CONFIG_CANDIDATE in python3 python3.14 python3.13 python3.12 python3.11; do
  AGENT_CONFIG_PYTHON="$(type -P -- "${AGENT_CONFIG_CANDIDATE}" 2>/dev/null)" || continue
  if "${AGENT_CONFIG_PYTHON}" -I -B -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    exec "${AGENT_CONFIG_PYTHON}" -I -B -X utf8 "${AGENT_CONFIG_LAUNCHER_DIR}/launcher.py" "$@"
  fi
done
printf '%s\n' '{"schema_version":1,"state":"unavailable","code":"python_required","diagnostics":["需要本机已有 Python 3.11+；启动器不会安装解释器。"]}'
exit 1
