#!/usr/bin/env bash
# 从任意目录启动管理器；沿用现有 Python 选择器，不改 PATH 或全局宿主配置。
set -euo pipefail
# awf-cli 是安装在用户 bin 目录的符号链接；必须先找到源脚本，不能把 bin 当源包。
# 每段相对链接均按该链接所在目录解析；解析目录的 cd 位于子 shell，不改变调用目录。
# 每次内部 cd 仅在命令执行期间清空 CDPATH，防止同名目录跳转和额外输出污染路径。
# 命令级赋值结束后恢复原值，不改变调用者或随后 Python 进程使用的环境。
WORKFLOW_MANAGER_ENTRY="${BASH_SOURCE[0]}"
while [[ -L "${WORKFLOW_MANAGER_ENTRY}" ]]; do
  WORKFLOW_MANAGER_LINK_DIR="$(CDPATH= cd -P -- "$(dirname "${WORKFLOW_MANAGER_ENTRY}")" && pwd -P)"
  WORKFLOW_MANAGER_ENTRY="$(readlink "${WORKFLOW_MANAGER_ENTRY}")"
  if [[ "${WORKFLOW_MANAGER_ENTRY}" != /* ]]; then
    WORKFLOW_MANAGER_ENTRY="${WORKFLOW_MANAGER_LINK_DIR}/${WORKFLOW_MANAGER_ENTRY}"
  fi
done
WORKFLOW_MANAGER_ROOT="$(CDPATH= cd -P -- "$(dirname "${WORKFLOW_MANAGER_ENTRY}")" && pwd -P)"
export AGENT_WORKFLOW_CALLER_DIR="$(pwd -P)"
# 相对解释器和相对 PATH 必须在调用目录中解析。复用现有选择器后直接 exec，
# 不再经运行时脚本重复探测；共享运行时及三平台安装流程均不改动。
source "${WORKFLOW_MANAGER_ROOT}/lib/python_runtime.sh"
workflow_select_python || exit $?
CDPATH= cd -P -- "${WORKFLOW_MANAGER_ROOT}"
if [[ "${1:-}" == "--install-cli" ]]; then
  shift
  exec "${AGENT_WORKFLOW_PYTHON}" -B -X utf8 -m manager.install_cli "$@"
fi
exec "${AGENT_WORKFLOW_PYTHON}" -B -X utf8 -m manager.cli "$@"
