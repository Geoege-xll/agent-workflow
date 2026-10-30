#!/usr/bin/env bash
# Portable safety lint. Product/framework-specific rules belong in project tooling.
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $*"; }

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${PROJECT_ROOT}"

is_supported_text_file() {
  case "$1" in
    *.vue|*.ts|*.tsx|*.js|*.jsx|*.css|*.scss|*.swift|*.kt|*.java|*.py|*.rs|*.md|*.toml|*.yaml|*.yml) return 0 ;;
    *) return 1 ;;
  esac
}

files=()
if [[ "$#" -gt 0 ]]; then
  for file in "$@"; do
    is_supported_text_file "${file}" && files+=("${file}")
  done
else
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log_err "未提供文件，且目标项目不是 Git 工作树；未执行扫描。"
    exit 2
  fi
  staged=$(mktemp)
  if ! git diff --cached --name-only --diff-filter=ACMR -z > "${staged}"; then
    rm -f "${staged}"
    log_err "无法读取 Git 暂存区；未执行扫描。"
    exit 2
  fi
  while IFS= read -r -d '' file; do
    is_supported_text_file "${file}" && files+=("${file}")
  done < "${staged}"
  rm -f "${staged}"
fi

if [[ "${#files[@]}" -eq 0 ]]; then
  log_ok "没有需要扫描的受支持文本文件。"
  exit 0
fi

violations=0
for file in "${files[@]}"; do
  if [[ "${file}" == /* ]]; then
    absolute="${file}"
  else
    absolute="${PROJECT_ROOT}/${file}"
  fi
  absolute=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${absolute}")
  if [[ ! -f "${absolute}" ]]; then
    log_err "文件不存在，无法扫描：${file}"
    violations=$((violations + 1))
    continue
  fi
  case "${absolute}" in
    "${PROJECT_ROOT}"/*) ;;
    *)
      log_err "拒绝扫描项目根目录以外的文件：${file}"
      violations=$((violations + 1))
      continue
      ;;
  esac

  log_info "扫描未解决的合并冲突：${file}"
  if grep -nE '^(<<<<<<<|=======|>>>>>>>)([[:space:]]|$)' "${absolute}" >/dev/null; then
    log_err "${file} 含未解决的 Git 合并冲突标记。"
    violations=$((violations + 1))
  fi
done

if [[ "${violations}" -gt 0 ]]; then
  log_err "通用安全 lint 未通过：${violations} 个问题。"
  exit 1
fi

log_ok "通用安全 lint 通过。框架/设计系统规则应由项目自身 lint 命令负责。"
