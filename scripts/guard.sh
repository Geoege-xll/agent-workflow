#!/usr/bin/env bash
# ============================================================================
# guard.sh — portable soft audit for multi-agent collab workflow
# ============================================================================
# Default: report-only discovered module attribution, exit 0.
# Strict: GUARD_STRICT=1 and project.yaml deny_prefixes set → exit 1 on hits.
# Discovered module roots are attribution hints, not OS locks.
# Compatible with macOS Bash 3.2 (no mapfile).
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_err()   { echo -e "${RED}[ERROR]${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACK_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${PACK_DIR}/.." && pwd)"
PROJECT_YAML="${PACK_DIR}/project.yaml"
cd "${PROJECT_ROOT}"

STRICT=0
[[ "${GUARD_STRICT:-0}" == "1" ]] && STRICT=1

log_info "Discovered module attribution audit (soft by default)"
log_info "Project root: ${PROJECT_ROOT}"
[[ "${STRICT}" -eq 1 ]] && log_info "GUARD_STRICT=1 — deny_prefixes will fail the audit"

# Collect porcelain paths (relative)
CHANGED=()
while IFS= read -r line; do
  [[ -z "${line}" ]] && continue
  status="${line:0:2}"
  rest="${line:3}"
  if [[ "${status}" == R* ]] || [[ "${rest}" == *" -> "* ]]; then
    file="${rest##* -> }"
  else
    file="${rest}"
  fi
  file="${file#\"}"
  file="${file%\"}"
  file="${file#./}"
  [[ -z "${file}" ]] && continue
  CHANGED+=("${file}")
done < <(git status --porcelain 2>/dev/null || true)

if [[ ${#CHANGED[@]} -eq 0 ]]; then
  log_ok "Working tree clean — nothing to attribute."
  exit 0
fi

# Validate configuration and consume discovered ProjectProfile module scopes.
# Outputs lines: module\trole\troot or deny\tprefix.
MAP_FILE=$(mktemp)
if ! PYTHONDONTWRITEBYTECODE=1 bash "${PACK_DIR}/lib/python_runtime.sh" --workflow-paths=1,2,3,4 - "${PACK_DIR}/lib" "${PROJECT_YAML}" "${PROJECT_ROOT}" "${PACK_DIR}/roles" <<'PY' > "${MAP_FILE}"; then
import re
import sys

lib_dir, config_path, project_root, roles_dir = sys.argv[1:]
sys.path.insert(0, lib_dir)
from validate_project_config import section_lines, strip_inline_comment, validate_with_profile

result = validate_with_profile(config_path, project_root, roles_dir)
if result.errors or result.profile is None:
    for error in result.errors:
        print(f"[ERROR] {error}", file=sys.stderr)
    raise SystemExit(1)
profile = result.profile
def module_depth(root):
    return 0 if root == "." else len(root.split("/"))

for module in sorted(
    profile.modules,
    key=lambda item: (-module_depth(item.root), item.root),
):
    print(f"module\t{module.primary_role}\t{module.root}")

def section(name):
    return section_lines(open(config_path, encoding="utf-8").read().splitlines(), name)

for raw in section("deny_prefixes"):
    match = re.match(r"^\s*-\s+(.+?)\s*$", raw)
    if match:
        print(f"deny\t{strip_inline_comment(match.group(1)).strip(chr(34)).strip(chr(39))}")
PY
  rm -f "${MAP_FILE}"
  exit 1
fi

# Load discovered module map and deny list.
MODULE_ROLES=()
MODULE_ROOTS=()
DENY_PREFIXES=()
while IFS=$'\t' read -r kind a b; do
  [[ -z "${kind}" ]] && continue
  if [[ "${kind}" == "module" ]]; then
    MODULE_ROLES+=("${a}")
    MODULE_ROOTS+=("${b}")
  elif [[ "${kind}" == "deny" ]]; then
    DENY_PREFIXES+=("${a}")
  fi
done < "${MAP_FILE}"
rm -f "${MAP_FILE}"

# Always-soft pack / docs paths (informational labels only)
label_for() {
  local file="$1" i prefix
  file="${file#./}"
  case "${file}" in
    CLAUDE.md|AGENTS.md|PROGRESS.md) echo "pm-docs"; return ;;
    .agent-workflow/*) echo "workflow-pack"; return ;;
    docs/*) echo "docs"; return ;;
    .claude/*) echo "claude-config"; return ;;
    .codex/*) echo "codex-config"; return ;;
  esac
  i=0
  while [[ $i -lt ${#MODULE_ROOTS[@]} ]]; do
    prefix="${MODULE_ROOTS[$i]}"
    prefix="${prefix#./}"
    prefix="${prefix%/}"
    if [[ "${prefix}" == "." ]] || [[ -n "${prefix}" && ( "${file}" == "${prefix}" || "${file}" == "${prefix}/"* ) ]]; then
      echo "${MODULE_ROLES[$i]}"
      return
    fi
    i=$((i + 1))
  done
  echo "unscoped"
}

echo ""
echo -e "${BOLD}Changed files → discovered module attribution${NC}"
echo "----------------------------------------"
STRICT_HITS=()
for file in "${CHANGED[@]}"; do
  label=$(label_for "${file}")
  printf "  %-18s  %s\n" "[${label}]" "${file}"
  if [[ "${STRICT}" -eq 1 && ${#DENY_PREFIXES[@]} -gt 0 ]]; then
    for dp in "${DENY_PREFIXES[@]}"; do
      dp="${dp#./}"
      if [[ -n "${dp}" && "${file}" == ${dp}* ]]; then
        STRICT_HITS+=("${file}")
      fi
    done
  fi
done
echo "----------------------------------------"

if [[ ${#MODULE_ROOTS[@]} -eq 0 ]]; then
  log_warn "No implementation modules discovered — report is path-only."
fi

log_info "Discovered module roots are soft role scopes (prefer dispatch xy-*). Not OS locks."
log_info "Default exit 0. Set GUARD_STRICT=1 + project.yaml deny_prefixes for hard fail."

if [[ "${STRICT}" -eq 1 && ${#STRICT_HITS[@]} -gt 0 ]]; then
  echo ""
  log_err "GUARD_STRICT hits on deny_prefixes:"
  for h in "${STRICT_HITS[@]}"; do
    echo -e "  - ${RED}${h}${NC}"
  done
  exit 1
fi

log_ok "Soft audit complete (exit 0)."
exit 0
