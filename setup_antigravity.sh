#!/usr/bin/env bash
# setup_antigravity.sh — native static Antigravity Agents + shared Skills
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

CHECK_ONLY=0
PREFLIGHT_ONLY=0
for argument in "$@"; do
  case "${argument}" in
    --check) CHECK_ONLY=1 ;;
    --preflight) PREFLIGHT_ONLY=1 ;;
    *)
      log_err "unknown argument: ${argument}"
      exit 2
      ;;
  esac
done
if [[ "${CHECK_ONLY}" -eq 1 && "${PREFLIGHT_ONLY}" -eq 1 ]]; then
  log_err "--check and --preflight are mutually exclusive"
  exit 2
fi
if [[ "${CHECK_ONLY}" -eq 0 && "${PREFLIGHT_ONLY}" -eq 0 ]]; then
  python3 "${PACK_DIR}/lib/ensure_project_id.py" "${PROJECT_YAML}" "${PROJECT_ROOT}"
fi

ROOT_AGENTS_MD="${PROJECT_ROOT}/AGENTS.md"
ROOT_DOT_AGENTS="${PROJECT_ROOT}/.agents"
ROOT_NATIVE_AGENTS="${ROOT_DOT_AGENTS}/agents"
ROOT_NATIVE_SKILLS="${ROOT_DOT_AGENTS}/skills"
PROD_BEGIN="<!-- pack:product-begin -->"
PROD_END="<!-- pack:product-end -->"
CODEX_BEGIN="<!-- pack:codex-begin -->"
CODEX_END="<!-- pack:codex-end -->"
ANTI_BEGIN="<!-- pack:antigravity-begin -->"
ANTI_END="<!-- pack:antigravity-end -->"
ANTI_TPL="${PLATFORMS_DIR}/antigravity/AGENTS.antigravity.tpl"
VALIDATOR="${PACK_DIR}/lib/validate_antigravity_artifacts.py"
RENDERER="${PACK_DIR}/lib/render_antigravity_agent.py"
APPLIER="${PACK_DIR}/lib/apply_antigravity_setup.py"
STAGING_ROOT=""
RESET_BACKUP=""
RESET_ACTIVE=0
RESET_COMMITTED=0

cleanup_staging() {
  [[ -n "${STAGING_ROOT}" && -d "${STAGING_ROOT}" ]] || return 0
  case "$(basename "${STAGING_ROOT}")" in
    agent-workflow-antigravity-stage.*)
      /bin/rm -r -- "${STAGING_ROOT}"
      ;;
    *)
      log_err "refusing to clean unexpected staging path: ${STAGING_ROOT}"
      return 1
      ;;
  esac
}

cleanup_native_reset() {
  [[ "${RESET_ACTIVE}" -eq 1 ]] || return 0
  if [[ "$(dirname "${RESET_BACKUP}")" != "${PROJECT_ROOT}" ]] ||
    [[ "$(basename "${RESET_BACKUP}")" != .agent-workflow-antigravity-reset.* ]]; then
    log_err "refusing to clean unexpected native reset backup: ${RESET_BACKUP}"
    return 1
  fi
  if [[ "${RESET_COMMITTED}" -eq 1 ]]; then
    if [[ -L "${RESET_BACKUP}" ]]; then
      /bin/rm -- "${RESET_BACKUP}"
    else
      /bin/rm -r -- "${RESET_BACKUP}"
    fi
    RESET_ACTIVE=0
    return 0
  fi
  if [[ -e "${ROOT_DOT_AGENTS}" || -L "${ROOT_DOT_AGENTS}" ]]; then
    if ! python3 "${VALIDATOR}" restore "${PROJECT_ROOT}" "${RESET_BACKUP}"; then
      log_err "cannot safely restore native reset backup"
      return 1
    fi
    RESET_ACTIVE=0
    return 0
  fi
  mv -- "${RESET_BACKUP}" "${ROOT_DOT_AGENTS}"
  RESET_ACTIVE=0
}

cleanup_all() {
  local exit_status=$? reset_status=0 staging_status=0
  trap - EXIT
  set +e
  cleanup_native_reset
  reset_status=$?
  cleanup_staging
  staging_status=$?
  if [[ "${exit_status}" -eq 0 && ("${reset_status}" -ne 0 || "${staging_status}" -ne 0) ]]; then
    exit_status=1
  fi
  exit "${exit_status}"
}
trap cleanup_all EXIT

reset_owned_native_root() {
  local ownership="$1" candidate reset_ownership
  [[ "${ownership}" != "missing" ]] || return 0
  case "${ownership}" in
    managed) ;;
    *)
      log_err "unexpected Antigravity ownership classification: ${ownership}"
      return 1
      ;;
  esac
  candidate=$(mktemp -d "${PROJECT_ROOT}/.agent-workflow-antigravity-reset.XXXXXX")
  rmdir -- "${candidate}"
  if ! reset_ownership=$(
    python3 "${VALIDATOR}" reset "${PROJECT_ROOT}" "${candidate}"
  ); then
    return 1
  fi
  if [[ "${reset_ownership}" != "${ownership}" ]]; then
    log_err "native root changed before reset: expected ${ownership}, got ${reset_ownership}"
    return 1
  fi
  RESET_BACKUP="${candidate}"
  RESET_ACTIVE=1
}

validate_role() {
  local file="$1" name toolsets workspace base
  name=$(role_frontmatter name "${file}")
  toolsets=$(role_frontmatter toolsets "${file}")
  workspace=$(role_frontmatter workspace "${file}")
  base=$(basename "${file}" .md)
  [[ -n "${name}" && "${name}" == "${base}" ]] || {
    log_err "${base}: invalid name"
    return 1
  }
  [[ "${name}" =~ ^xy-[a-z0-9]+(-[a-z0-9]+)*$ ]] || {
    log_err "${base}: role name must use lowercase hyphens"
    return 1
  }
  [[ -n "${toolsets}" ]] || {
    log_err "${base}: missing toolsets"
    return 1
  }
  [[ -n "${workspace}" ]] || workspace="inherit"
  case "${workspace}" in
    inherit|worktree) ;;
    *)
      log_err "${base}: bad workspace"
      return 1
      ;;
  esac
  if ! grep -qE 'Tech Stack Lock|Identity|Critical Rules' "${file}"; then
    log_warn "${base}: role body may be incomplete (no Identity/Stack Lock)"
  fi
  log_ok "role ${name} (toolsets=${toolsets}, workspace=${workspace})"
}

validate_all_roles() {
  local role failed=0
  while IFS= read -r role; do
    [[ -n "${role}" ]] || continue
    if [[ ! -f "${ROLES_DIR}/${role}.md" ]]; then
      log_err "missing enabled role source: ${role}"
      failed=1
      continue
    fi
    validate_role "${ROLES_DIR}/${role}.md" || failed=1
  done < <(python3 "${RENDERER}" --roles "${PACK_DIR}")
  [[ "${failed}" -eq 0 ]]
}

write_product_block() {
  local target="$1" temporary
  temporary=$(mktemp "${STAGING_ROOT}/.product-block.XXXXXX")
  {
    echo "${PROD_BEGIN}"
    cat "${PLATFORMS_DIR}/shared/AGENTS.product.tpl"
    echo "${PROD_END}"
  } > "${temporary}"
  mv "${temporary}" "${target}"
}

write_antigravity_block() {
  local target="$1" temporary
  temporary=$(mktemp "${STAGING_ROOT}/.antigravity-block.XXXXXX")
  {
    echo "${ANTI_BEGIN}"
    cat "${ANTI_TPL}"
    echo "${ANTI_END}"
  } > "${temporary}"
  mv "${temporary}" "${target}"
}

stage_native_artifacts() {
  local role temporary
  STAGING_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/agent-workflow-antigravity-stage.XXXXXX")
  mkdir -p "${STAGING_ROOT}/agents" "${STAGING_ROOT}/skills"

  python3 "${PACK_DIR}/lib/shared_core_skills.py" \
    stage-copy "${PACK_DIR}" "${STAGING_ROOT}/skills"

  while IFS= read -r role; do
    [[ -n "${role}" ]] || continue
    temporary=$(mktemp "${STAGING_ROOT}/agents/.${role}.XXXXXX")
    python3 "${RENDERER}" "${PACK_DIR}" "${role}" > "${temporary}"
    mv "${temporary}" "${STAGING_ROOT}/agents/${role}.md"
  done < <(python3 "${RENDERER}" --roles "${PACK_DIR}")

  write_product_block "${STAGING_ROOT}/AGENTS.product.block"
  write_antigravity_block "${STAGING_ROOT}/AGENTS.antigravity.block"
  python3 "${VALIDATOR}" staging "${PACK_DIR}" "${STAGING_ROOT}"
}

marker_pair_is_safe() {
  local target="$1" begin="$2" end="$3"
  local state begin_count end_count begin_line end_line
  state=$(awk -v begin="${begin}" -v end="${end}" '
    $0 == begin { begin_count++; if (begin_line == 0) begin_line=NR }
    $0 == end { end_count++; if (end_line == 0) end_line=NR }
    END { print begin_count + 0, end_count + 0, begin_line + 0, end_line + 0 }
  ' "${target}")
  read -r begin_count end_count begin_line end_line <<< "${state}"
  if [[ "${begin_count}" -eq 0 && "${end_count}" -eq 0 ]]; then
    return 0
  fi
  if [[ "${begin_count}" -eq 1 && "${end_count}" -eq 1 && "${begin_line}" -lt "${end_line}" ]]; then
    return 0
  fi
  log_err "malformed managed markers in ${target}: ${begin_count} begin, ${end_count} end"
  return 1
}

basic_check() {
  local failed=0
  echo -e "${BOLD}Antigravity --check${NC}"
  if ! python3 "${APPLIER}" check "${PACK_DIR}" "${PROJECT_ROOT}" "${STAGING_ROOT}"; then
    failed=1
  fi
  if ! python3 "${VALIDATOR}" generated "${PACK_DIR}" "${PROJECT_ROOT}"; then
    failed=1
  fi
  if ! python3 "${PACK_DIR}/lib/validate_project_docs.py" \
    "${PROJECT_YAML}" "${PROJECT_ROOT}"; then
    failed=1
  fi
  if [[ ! -f "${ROOT_AGENTS_MD}" ]]; then
    log_err "missing root AGENTS.md"
    failed=1
  else
    marker_pair_is_safe "${ROOT_AGENTS_MD}" "${PROD_BEGIN}" "${PROD_END}" || failed=1
    marker_pair_is_safe "${ROOT_AGENTS_MD}" "${CODEX_BEGIN}" "${CODEX_END}" || failed=1
    marker_pair_is_safe "${ROOT_AGENTS_MD}" "${ANTI_BEGIN}" "${ANTI_END}" || failed=1
  fi
  [[ "${failed}" -eq 0 ]]
}

require_pack_layout
python3 "${PACK_DIR}/lib/validate_project_config.py" \
  "${PROJECT_YAML}" "${PROJECT_ROOT}" "${ROLES_DIR}"
python3 "${VALIDATOR}" sources "${PACK_DIR}"
validate_all_roles
stage_native_artifacts
# 预检与实际安装使用同一归属判定。聚合入口会先执行所有宿主预检，因此用户碰撞必须在
# 任一宿主/文档脚手架开始发布之前暴露，不能只在最后一个宿主准备 reset 时才发现。
OWNERSHIP=$(python3 "${VALIDATOR}" ownership "${PROJECT_ROOT}")
if [[ "${CHECK_ONLY}" -eq 0 && "${PREFLIGHT_ONLY}" -eq 0 && ! -e "${ROOT_DOT_AGENTS}/hooks.json" ]]; then
  # 混有原生 Hooks 时只做路径级事务更新，不搬走/重建包含用户条目的整个 .agents。
  reset_owned_native_root "${OWNERSHIP}"
fi
python3 "${APPLIER}" preflight "${PACK_DIR}" "${PROJECT_ROOT}" "${STAGING_ROOT}"

if [[ "${PREFLIGHT_ONLY}" -eq 1 ]]; then
  python3 "${PACK_DIR}/lib/project_profile_cli.py" \
    preview "${PACK_DIR}" "${PROJECT_ROOT}"
  log_ok "Antigravity source and staging preflight"
  exit 0
fi

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
  basic_check
  exit $?
fi

echo -e "${BOLD}Antigravity native setup${NC}"
python3 "${APPLIER}" apply "${PACK_DIR}" "${PROJECT_ROOT}" "${STAGING_ROOT}"
python3 "${PACK_DIR}/lib/validate_project_docs.py" \
  "${PROJECT_YAML}" "${PROJECT_ROOT}"
if [[ "${AGENT_WORKFLOW_PACK_TEST_FAILPOINT:-}" == "antigravity-generated-validator-failure" ]]; then
  log_err "injected Antigravity generated validator failure"
  exit 1
fi
python3 "${VALIDATOR}" generated "${PACK_DIR}" "${PROJECT_ROOT}"
RESET_COMMITTED=1
echo -e "${GREEN}${BOLD}✅ Antigravity native setup done${NC}"
