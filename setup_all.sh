#!/usr/bin/env bash
# setup_all.sh — scaffold portable docs + generate Claude/Codex/Antigravity artefacts
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${DIR}/lib/common.sh"
ONLY=""
ONLY_SEEN=0
CHECK=0
PREFLIGHT=0
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --preflight) PREFLIGHT=1 ;;
    --only=claude|--only=codex|--only=antigravity)
      selected_host="${a#--only=}"
      if [[ "${ONLY_SEEN}" -eq 1 && "${ONLY}" != "${selected_host}" ]]; then
        log_err "conflicting --only selectors: ${ONLY} and ${selected_host}"
        exit 2
      fi
      ONLY="${selected_host}"
      ONLY_SEEN=1
      ;;
    --only=*)
      log_err "invalid --only selector: ${a#--only=}"
      exit 2
      ;;
    *)
      log_err "unknown argument: ${a}"
      exit 2
      ;;
  esac
done

if [[ "${CHECK}" -eq 1 && "${PREFLIGHT}" -eq 1 ]]; then
  log_err "--check and --preflight are mutually exclusive"
  exit 2
fi

if [[ "${CHECK}" -eq 0 && "${PREFLIGHT}" -eq 0 ]]; then
  python3 "${DIR}/lib/ensure_project_id.py" "${PROJECT_YAML}" "${PROJECT_ROOT}"
fi

selected() {
  [[ -z "${ONLY}" || "${ONLY}" == "$1" ]]
}

# Every selected host validates all source/config/collision contracts before the
# aggregate setup creates the first project artifact.
if [[ "${CHECK}" -eq 0 ]]; then
  if [[ -z "${ONLY}" ]]; then
    # 三平台入口合并后先预检最终大小与所有权边界，避免单平台分别通过后局部安装失败。
    python3 "${DIR}/lib/claude_instructions.py" preflight-all "${DIR}" "${PROJECT_ROOT}"
  fi
  for host in claude codex antigravity; do
    selected "${host}" || continue
    bash "${DIR}/setup_${host}.sh" --preflight
  done
  if [[ "${PREFLIGHT}" -eq 1 ]]; then
    echo "setup_all preflight complete"
    exit 0
  fi
  bash "${DIR}/scripts/scaffold_project_docs.sh"
fi

run() {
  local name="$1"
  if [[ -n "${ONLY}" && "${ONLY}" != "${name}" ]]; then
    return 0
  fi
  if [[ "${CHECK}" -eq 1 ]]; then
    bash "${DIR}/setup_${name}.sh" --check
  else
    bash "${DIR}/setup_${name}.sh"
  fi
}

run claude
run codex
run antigravity

if [[ "${CHECK}" -eq 1 ]]; then
  FAIL=0
  for key in standards project; do
    f=$(py_yaml "${DIR}/project.yaml" docs "${key}" 2>/dev/null || true)
    if [[ -n "${f}" && ! -f "${PROJECT_ROOT}/${f}" ]]; then
      echo "[ERROR] missing docs.${key} → ${f} (run setup without --check to scaffold)"
      FAIL=1
    else
      echo "[OK]    docs.${key} → ${f:-"(empty)"}"
    fi
  done
  standards_root=$(py_yaml "${DIR}/project.yaml" docs standards_root 2>/dev/null || true)
  if [[ -n "${standards_root}" && -d "${PROJECT_ROOT}/${standards_root}" ]]; then
    echo "[OK]    docs.standards_root → ${standards_root}"
  else
    echo "[ERROR] missing docs.standards_root → ${standards_root:-"(empty)"}"
    FAIL=1
  fi
  feature_dir=$(py_yaml "${DIR}/project.yaml" docs features 2>/dev/null || true)
  if [[ -n "${feature_dir}" && -d "${PROJECT_ROOT}/${feature_dir}" ]]; then
    echo "[OK]    docs.features → ${feature_dir}"
  else
    echo "[ERROR] missing docs.features → ${feature_dir:-"(empty)"}"
    FAIL=1
  fi
  # UI/UX 是所有项目均可用的基础角色，不等于纯后端项目需要原型目录。
  # 直接消费与两套脚手架一致的 ProjectProfile 判断；命令替换也让发现失败
  # 按 set -e 退出，不能像进程替换那样隐藏错误后跳过必要检查。
  DESIGN_SCAFFOLD_REQUIRED=$(
    python3 "${DIR}/lib/project_profile_cli.py" design-scaffold \
      "${DIR}" "${PROJECT_ROOT}"
  )
  if [[ "${DESIGN_SCAFFOLD_REQUIRED}" == "1" ]]; then
    standards_root=$(py_yaml "${DIR}/project.yaml" docs standards_root 2>/dev/null || true)
    # 规范已压平到 standards_root；UI 唯一的固定子目录是原型工作区。
    # 具体规范叶及其领域由各宿主的文档校验器检查，不能再要求旧 design 目录。
    d="${standards_root%/}/prototype"
    if [[ -n "${d}" && -d "${PROJECT_ROOT}/${d}" ]]; then
      echo "[OK]    docs.standards_root/prototype → ${d}"
    else
      echo "[ERROR] missing docs.standards_root/prototype → ${d:-"(empty)"}"
      FAIL=1
    fi
  fi
  exit "${FAIL}"
fi

echo "setup_all complete (check=${CHECK})"
