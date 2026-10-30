#!/usr/bin/env bash
# 工作流共用 Python 入口：只选择已有运行时，不安装软件、不修改用户 PATH 或配置。
# 安装脚本通过 common.sh 复用本文件；Agent 直接运行 CLI 时用 bash 调用本文件。

# QA 和预检只读命令不能因 Python 导入而创建 __pycache__ 伴随文件。
export PYTHONDONTWRITEBYTECODE=1

workflow_select_python() {
  local workflow_candidate workflow_executable
  local -a workflow_candidates

  # 用户显式选择的解释器属于确定约束：版本错误应及时失败，不能悄悄换成另一个环境。
  if [[ -n "${AGENT_WORKFLOW_PYTHON:-}" ]]; then
    workflow_candidates=("${AGENT_WORKFLOW_PYTHON}")
  else
    # 先尊重可用的默认 Python；系统默认过旧时再寻找常见的受支持版本化命令。
    # type -P 绕过同名 shell 函数，避免 common.sh 的 python3 包装器发生递归调用。
    workflow_candidates=(python3 python3.14 python3.13 python3.12 python3.11)
  fi
  for workflow_candidate in "${workflow_candidates[@]}"; do
    workflow_executable=$(type -P -- "${workflow_candidate}" 2>/dev/null) || continue
    [[ -f "${workflow_executable}" && -x "${workflow_executable}" ]] || continue
    # 安装器之后可能切换到项目根目录；相对 PATH 或显式相对路径必须先固定，
    # 否则父脚本能运行、子脚本却会在另一个工作目录找不到同一解释器。
    if [[ "${workflow_executable}" != /* ]]; then
      workflow_executable="${PWD}/${workflow_executable}"
    fi
    if "${workflow_executable}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      AGENT_WORKFLOW_PYTHON="${workflow_executable}"
      export AGENT_WORKFLOW_PYTHON
      return 0
    fi
  done
  printf '%s\n' '[ERROR] Python >= 3.11 is required. Install a supported runtime or set AGENT_WORKFLOW_PYTHON to its executable path.' >&2
  return 2
}

# 被 source 时只声明函数；作为 CLI 使用时在任何项目操作前验证版本，并原样传参。
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  workflow_select_python || exit $?
  exec "${AGENT_WORKFLOW_PYTHON}" "$@"
fi
