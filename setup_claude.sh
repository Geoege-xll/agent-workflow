#!/usr/bin/env bash
# setup_claude.sh — 共享 AGENTS.md + CLAUDE.md 薄入口 + Custom Agents + 按需 Skills
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
CLAUDE_DIR="${PROJECT_ROOT}/.claude"
CLAUDE_AGENTS="${CLAUDE_DIR}/agents"
CLAUDE_SKILLS="${CLAUDE_DIR}/skills"
BEGIN="<!-- agent-workflow-pack:claude-begin -->"
END="<!-- agent-workflow-pack:claude-end -->"
MANAGED_SKILL_MARKER="<!-- agent-workflow-pack:managed-skill -->"
MANAGED_AGENT_MARKER="<!-- agent-workflow-pack:managed-agent -->"
TPL="${PLATFORMS_DIR}/claude/AGENTS.claude.tpl"
INSTRUCTIONS_CLI="${PACK_DIR}/lib/claude_instructions.py"
SHARED_SKILLS_SRC="${PLATFORMS_DIR}/shared/skills"
CLAUDE_VALIDATOR="${PACK_DIR}/lib/validate_claude_artifacts.py"
PROJECT_PROFILE_CLI="${PACK_DIR}/lib/project_profile_cli.py"

CLAUDE_CORE_SKILLS=()

load_claude_project_skills() {
  local output name
  [[ "${#CLAUDE_CORE_SKILLS[@]}" -eq 0 ]] || return 0
  output=$(python3 "${PACK_DIR}/lib/shared_core_skills.py" list "${PACK_DIR}")
  while IFS= read -r name; do
    [[ -n "${name}" ]] || continue
    CLAUDE_CORE_SKILLS+=("${name}")
  done <<< "${output}"
  if [[ "${#CLAUDE_CORE_SKILLS[@]}" -eq 0 ]]; then
    log_err "shared core Skill loader returned no names"
    return 1
  fi
}

is_claude_core_skill() {
  local wanted="$1" name
  for name in "${CLAUDE_CORE_SKILLS[@]}"; do
    [[ "${name}" == "${wanted}" ]] && return 0
  done
  return 1
}

claude_profile_query() {
  [[ "$1" == "roles" ]] || {
    log_err "unsupported Claude profile query: $1"
    return 2
  }
  python3 "${PROJECT_PROFILE_CLI}" roles "${PACK_DIR}" "${PROJECT_ROOT}"
}

roles_field() {
  python3 --workflow-paths=1 - "$ROLES_YAML" "$1" "$2" <<'PY'
import re, sys
path, role, key = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(path, encoding="utf-8").read().splitlines()
in_role = False
for raw in lines:
    if re.match(rf"^  {re.escape(role)}:\s*$", raw):
        in_role = True
        continue
    if in_role and re.match(r"^  [a-zA-Z_]", raw):
        break
    if in_role and raw.strip().startswith(key + ":"):
        print(raw.split(":", 1)[1].strip().strip('"').strip("'"))
        break
PY
}

claude_tools() {
  # Skill is intentionally available to every role for Claude-native on-demand matching.
  case "$1" in
    *delegation*) echo "Read, Grep, Glob, Bash, Edit, Write, Skill, Agent" ;;
    *write-tests*|*tests*) echo "Read, Grep, Glob, Bash, Edit, Write, Skill" ;;
    *read*) echo "Read, Grep, Glob, Bash, Skill" ;;
    *) echo "Read, Grep, Glob, Bash, Edit, Write, Skill" ;;
  esac
}

render_claude_role_body() {
  local src="$1"
  role_body "${src}" | python3 -c '
import sys
body = sys.stdin.read()
body = body.replace("$xy-", "/xy-")
body = body.replace("let Codex match", "let Claude match")
body = body.replace("Codex match", "Claude match")
sys.stdout.write(body)
'
}

claude_agent_name() {
  printf '%s\n' "$1"
}

render_claude_task_pack_boundary() {
  echo "## PM task-pack boundary (generated)"
  echo
  echo "- Start from a PM task pack containing task ID, approvals, exact \`owned_paths\`, dependencies/gates, ProjectProfile routing evidence, task-scoped \`controlled_document_access\`, required Skills, acceptance evidence, \`audit_surfaces\`, and verification commands."
  echo "- ProjectProfile is routing only. Report missing, stale, or conflicting facts to the PM; never infer or widen scope."
  # 动态任务目录属于派发合同，不永久改变所有角色的隔离方式或用户设置。
  echo "- When execution_workspace is present, verify its actual root/base and keep all edits/commands there. Return checkpoint evidence to PM; never independently commit, merge, or remove worktrees. QA uses the assigned integration root read-only."
  echo
}

render_claude_agent() {
  local role="$1" src="${ROLES_DIR}/${role}.md"
  local agent_name desc toolsets color max_turns skills_raw tools disallowed desc_yaml
  agent_name=$(claude_agent_name "${role}")
  desc=$(roles_field "${role}" description)
  toolsets=$(roles_field "${role}" toolsets)
  color=$(roles_field "${role}" claude_color)
  max_turns=$(roles_field "${role}" claude_max_turns)
  skills_raw=$(roles_field "${role}" claude_skills)
  [[ -n "${desc}" ]] || desc="${role} specialist"
  if [[ "${toolsets}" == *write-tests* || "${toolsets}" == *tests* ]]; then
    desc="${desc} Use only for PM-routed QA task packs."
  else
    desc="${desc} Use only for PM task packs; owned_paths are write authority."
  fi
  tools=$(claude_tools "${toolsets:-write}")
  disallowed=""
  echo "${toolsets}" | grep -q delegation || disallowed="Agent"
  desc_yaml=$(printf '%s' "${desc}" | json_string)

  {
    echo "---"
    echo "name: ${agent_name}"
    echo "description: ${desc_yaml}"
    # 模型偏好仅生成宿主支持的字段；不改权限、技能或角色正文。
    python3 "${PACK_DIR}/lib/role_models.py" "${PACK_DIR}" claude "${role}" || return 1
    # 压缩窗口独立于模型偏好；必须输出完整整数，不能让宿主把 200k 误读成 200。
    python3 "${PACK_DIR}/lib/claude_options.py" "${PACK_DIR}" "${role}" || return 1
    echo "tools: ${tools}"
    [[ -n "${disallowed}" ]] && echo "disallowedTools: ${disallowed}"
    # Keep project Custom Agents inside the caller's normal permission prompts.
    echo "permissionMode: default"
    [[ -n "${max_turns}" ]] && echo "maxTurns: ${max_turns}"
    [[ -n "${color}" ]] && echo "color: ${color}"
    if [[ -n "${skills_raw}" && "${skills_raw}" == \[* ]]; then
      echo "skills:"
      echo "${skills_raw}" | tr -d '[]' | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' | while read -r skill; do
        echo "  - ${skill}"
      done
    fi
    echo "---"
    echo
    echo "${MANAGED_AGENT_MARKER}"
    echo
    render_claude_task_pack_boundary
    render_claude_role_body "${src}"
  }
}

build_claude_block() {
  local out="$1"
  TPL="${TPL}" BEGIN="${BEGIN}" END="${END}" OUT_PATH="${out}" \
  python3 <<'PY'
from pathlib import Path
import os

# 预检快照和最终发布使用相同的换行规范，避免目录化入口被误判为内容漂移。
template = Path(os.environ["TPL"]).read_text(encoding="utf-8").rstrip("\n")
Path(os.environ["OUT_PATH"]).write_text(
    f'{os.environ["BEGIN"]}\n{template}\n{os.environ["END"]}\n',
    encoding="utf-8",
)
PY
}

claude_agent_is_managed() {
  local path="$1" expected_name="$2"
  python3 --workflow-paths=1,2 - "${PACK_LIB_DIR}" "${path}" "${expected_name}" "${MANAGED_AGENT_MARKER}" <<'PY'
import stat
import sys

library, path, expected_name, marker = sys.argv[1:]
sys.path.insert(0, library)
from platform_fs import os
try:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4 * 1024 * 1024:
            raise ValueError("unsafe managed Agent file")
        chunks = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    body = b"".join(chunks).decode("utf-8", errors="strict")
    lines = body.splitlines()
    if "\r" in body or not body.endswith("\n") or not lines or lines[0] != "---":
        raise ValueError("noncanonical managed Agent")
    closing = lines.index("---", 1)
    names = [line.split(":", 1)[1].strip() for line in lines[1:closing] if line.startswith("name:")]
    if names != [expected_name] or lines.count(marker) != 1:
        raise ValueError("managed Agent identity mismatch")
    if lines[closing + 1 : closing + 3] != ["", marker]:
        raise ValueError("managed Agent marker position mismatch")
except (OSError, UnicodeError, ValueError):
    raise SystemExit(1)
PY
}

resolve_skill_src() {
  local name="$1"
  is_claude_core_skill "${name}" || return 1
  [[ -f "${SHARED_SKILLS_SRC}/${name}/SKILL.md" ]] || return 1
  echo "${SHARED_SKILLS_SRC}/${name}/SKILL.md"
}

array_contains() {
  local wanted="$1" item
  shift
  for item in "$@"; do
    [[ "${item}" == "${wanted}" ]] && return 0
  done
  return 1
}

stale_claude_skill_is_managed() {
  local name="$1" dir="${CLAUDE_SKILLS}/${name}"
  python3 --workflow-paths=1,2 - "${PACK_DIR}/lib" "${dir}" "${name}" "${MANAGED_SKILL_MARKER}" <<'PY'
import os
import stat
import sys
from pathlib import Path

library, directory, name, marker = sys.argv[1:]
sys.path.insert(0, library)
from platform_fs import os
from shared_core_skills import (  # noqa: E402
    SharedCoreSkillError,
    parse_managed_skill_bytes,
    validate_stale_managed_skill_directory,
)

skill_dir = Path(directory)
skill_path = skill_dir / "SKILL.md"
try:
    # Prove the complete current managed-state tree before removing stale output.
    validate_stale_managed_skill_directory(skill_dir, name)
    descriptor = os.open(
        skill_path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SharedCoreSkillError(
                f"stale managed Skill must be a single-link regular file: {skill_path}"
            )
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    body_bytes = b"".join(chunks)
    parse_managed_skill_bytes(body_bytes, name, str(skill_path))
    body = body_bytes.decode("utf-8", errors="strict")
    lines = body.splitlines()
    closing = lines.index("---", 1)
    if (
        "\r" in body
        or not body.endswith("\n")
        or lines.count(marker) != 1
        or lines[closing + 1 : closing + 3] != ["", marker]
    ):
        raise SharedCoreSkillError(
            f"stale Skill marker is not in the exact pack-managed position: {skill_path}"
        )
except (OSError, UnicodeError, ValueError, SharedCoreSkillError):
    raise SystemExit(1)
PY
}

validate_claude_markers() {
  [[ -f "${ROOT_AGENTS_MD}" ]] || return 0
  python3 --workflow-paths=1 - "${ROOT_AGENTS_MD}" "${BEGIN}" "${END}" <<'PY'
from pathlib import Path
import sys
path, begin, end = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
body = path.read_text(encoding="utf-8")
bc, ec = body.count(begin), body.count(end)
if bc == 0 and ec == 0:
    raise SystemExit(0)
if bc != 1 or ec != 1 or body.index(begin) > body.index(end):
    print(
        f"[ERROR] malformed managed markers in {path}: {bc} begin, {ec} end",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
}

preflight_claude_collisions() {
  # 先验证当前统一入口；旧正文和用户内容都不自动迁移，在写项目产物前停止。
  python3 "${INSTRUCTIONS_CLI}" preflight "${PACK_DIR}" "${PROJECT_ROOT}"
  python3 "${PACK_DIR}/lib/workflow_hook_install.py" preflight "${PACK_DIR}" "${PROJECT_ROOT}" claude
  validate_claude_markers
  local name src dest tmp role agent_name path skill_dir stem enabled_names=" "
  for name in "${CLAUDE_CORE_SKILLS[@]}"; do
    src=$(resolve_skill_src "${name}") || {
      log_err "missing Claude Skill source: ${name}"
      return 1
    }
    dest="${CLAUDE_SKILLS}/${name}"
    python3 "${PACK_DIR}/lib/shared_core_skills.py" \
      target-safe "$(dirname "${src}")" "${dest}" "${name}" || return 1
  done

  for path in "${CLAUDE_SKILLS}"/*/SKILL.md; do
    [[ -f "${path}" ]] || continue
    skill_dir=$(dirname "${path}")
    [[ -L "${skill_dir}" || -L "${path}" ]] && continue
    name=$(basename "$(dirname "${path}")")
    array_contains "${name}" "${CLAUDE_CORE_SKILLS[@]}" && continue
    grep -Fq "${MANAGED_SKILL_MARKER}" "${path}" || continue
    if ! stale_claude_skill_is_managed "${name}"; then
      log_err "user-owned or unproven stale Claude Skill collision: ${path}"
      return 1
    fi
  done

  while IFS= read -r role; do
    [[ -n "${role}" ]] || continue
    agent_name=$(claude_agent_name "${role}")
    enabled_names="${enabled_names}${agent_name} "
    dest="${CLAUDE_AGENTS}/${agent_name}.md"
    [[ -f "${dest}" ]] || continue
    if claude_agent_is_managed "${dest}" "${agent_name}"; then
      continue
    fi
    log_err "user-owned Claude Agent collision: ${dest}"
    return 1
  done < <(claude_profile_query roles)

  for path in "${CLAUDE_AGENTS}"/xy_*.md; do
    [[ -e "${path}" || -L "${path}" ]] || continue
    log_err "noncanonical underscore Claude Agent is unsupported: ${path}"
    return 1
  done
  for path in "${CLAUDE_AGENTS}"/xy-*.md; do
    [[ -e "${path}" || -L "${path}" ]] || continue
    stem=$(basename "${path}" .md)
    [[ "${enabled_names}" == *" ${stem} "* ]] && continue
    if ! claude_agent_is_managed "${path}" "${stem}"; then
      log_err "user-owned or unproven stale Claude Agent collision: ${path}"
      return 1
    fi
  done
}

atomic_copy() {
  local src="$1" dest="$2" tmp
  mkdir -p "$(dirname "${dest}")"
  tmp=$(mktemp "${dest}.tmp.XXXXXX")
  cp "${src}" "${tmp}"
  mv "${tmp}" "${dest}"
}

sync_claude_skills() {
  mkdir -p "${CLAUDE_SKILLS}"
  local name src dest path skill_dir
  for name in "${CLAUDE_CORE_SKILLS[@]}"; do
    src=$(resolve_skill_src "${name}")
    dest="${CLAUDE_SKILLS}/${name}/SKILL.md"
    python3 "${PACK_DIR}/lib/shared_core_skills.py" \
      sync-tree "$(dirname "${src}")" "$(dirname "${dest}")" "${name}"
    log_ok ".claude/skills/${name}/SKILL.md"
  done

  for path in "${CLAUDE_SKILLS}"/*/SKILL.md; do
    [[ -f "${path}" ]] || continue
    skill_dir=$(dirname "${path}")
    if [[ -L "${skill_dir}" || -L "${path}" ]]; then
      log_warn "preserved user-owned symlinked Claude Skill: ${skill_dir}"
      continue
    fi
    name=$(basename "$(dirname "${path}")")
    if ! array_contains "${name}" "${CLAUDE_CORE_SKILLS[@]}" \
      && stale_claude_skill_is_managed "${name}"; then
      python3 "${PACK_DIR}/lib/shared_core_skills.py" \
        remove-installed "${skill_dir}" "${name}"
      log_ok "removed stale managed Claude Skill: ${name}"
    fi
  done
}

write_claude_agents() {
  mkdir -p "${CLAUDE_AGENTS}"
  local role agent_name dest tmp path stem count=0 enabled_names=" "
  while IFS= read -r role; do
    [[ -n "${role}" && -f "${ROLES_DIR}/${role}.md" ]] || continue
    agent_name=$(claude_agent_name "${role}")
    enabled_names="${enabled_names}${agent_name} "
    dest="${CLAUDE_AGENTS}/${agent_name}.md"
    tmp=$(mktemp "${dest}.tmp.XXXXXX")
    render_claude_agent "${role}" > "${tmp}"
    mv "${tmp}" "${dest}"
    log_ok ".claude/agents/${agent_name}.md"
    count=$((count + 1))
  done < <(claude_profile_query roles)

  for path in "${CLAUDE_AGENTS}"/xy-*.md "${CLAUDE_AGENTS}"/xy_*.md; do
    [[ -f "${path}" ]] || continue
    if [[ -L "${path}" ]]; then
      log_warn "preserved user-owned symlinked Claude Agent: ${path}"
      continue
    fi
    stem=$(basename "${path}" .md)
    if [[ "${enabled_names}" == *" ${stem} "* ]]; then
      continue
    fi
    if claude_agent_is_managed "${path}" "${stem}"; then
      rm -f "${path}"
      log_ok "removed stale managed Claude Agent: ${stem}"
    fi
  done
  [[ "${count}" -gt 0 ]] || {
    log_err "no Claude Agents generated"
    return 1
  }
  log_ok "Claude agents: ${count}"
}

check_claude_block_matches() {
  local expected="$1"
  python3 --workflow-paths=1,2 - "${ROOT_AGENTS_MD}" "${expected}" "${BEGIN}" "${END}" <<'PY'
from pathlib import Path
import sys
target, expected = Path(sys.argv[1]), Path(sys.argv[2])
begin, end = sys.argv[3].encode(), sys.argv[4].encode()
if not target.is_file():
    print(f"[ERROR] missing generated AGENTS.md: {target}", file=sys.stderr)
    raise SystemExit(1)
body = target.read_bytes()
wanted = expected.read_bytes().rstrip(b"\n")
if body.count(begin) != 1 or body.count(end) != 1 or body.index(begin) > body.index(end):
    print(f"[ERROR] malformed CLAUDE managed markers: {target}", file=sys.stderr)
    raise SystemExit(1)
actual = body[body.index(begin):body.index(end) + len(end)]
if actual != wanted:
    print(f"[ERROR] generated CLAUDE managed block differs from source: {target}", file=sys.stderr)
    raise SystemExit(1)
PY
}

check_agent_outputs_match() {
  local role agent_name dest tmp failed=0
  while IFS= read -r role; do
    [[ -n "${role}" ]] || continue
    agent_name=$(claude_agent_name "${role}")
    dest="${CLAUDE_AGENTS}/${agent_name}.md"
    tmp=$(mktemp)
    render_claude_agent "${role}" > "${tmp}"
    if [[ ! -f "${dest}" ]] || ! cmp -s "${tmp}" "${dest}"; then
      log_err "generated Claude Agent differs from source: ${dest}"
      failed=1
    fi
    rm -f "${tmp}"
  done < <(claude_profile_query roles)
  return "${failed}"
}

check_claude_contract() {
  local block name src
  python3 "${INSTRUCTIONS_CLI}" check "${PACK_DIR}" "${PROJECT_ROOT}"
  python3 "${PACK_DIR}/lib/workflow_hook_install.py" check "${PACK_DIR}" "${PROJECT_ROOT}" claude
  python3 "${CLAUDE_VALIDATOR}" generated "${PACK_DIR}" "${PROJECT_ROOT}"
  block=$(mktemp)
  build_claude_block "${block}"
  check_claude_block_matches "${block}"
  rm -f "${block}"
  check_agent_outputs_match
  for name in "${CLAUDE_CORE_SKILLS[@]}"; do
    src=$(resolve_skill_src "${name}")
    python3 "${PACK_DIR}/lib/shared_core_skills.py" \
      tree-match "$(dirname "${src}")" "${CLAUDE_SKILLS}/${name}" "${name}"
  done
  log_ok "Claude generated artifacts match sources"
}

validate_rendered_staging() {
  local stage role agent_name
  stage=$(mktemp -d)
  mkdir -p "${stage}/.claude/agents" "${stage}/.claude/skills"
  python3 "${PACK_DIR}/lib/shared_core_skills.py" \
    stage-copy "${PACK_DIR}" "${stage}/.claude/skills"
  # 暂存校验使用真实入口生成器，保证预检和正式安装验证同一对文件，
  # 避免仅复制 AGENTS.md 而漏掉新的 CLAUDE.md 薄入口合同。
  if ! python3 "${INSTRUCTIONS_CLI}" apply "${PACK_DIR}" "${stage}"; then
    rm -rf "${stage}"
    return 1
  fi
  while IFS= read -r role; do
    [[ -n "${role}" ]] || continue
    agent_name=$(claude_agent_name "${role}")
    render_claude_agent "${role}" > "${stage}/.claude/agents/${agent_name}.md"
  done < <(claude_profile_query roles)
  if ! python3 "${CLAUDE_VALIDATOR}" generated "${PACK_DIR}" "${stage}" "${PROJECT_ROOT}"; then
    rm -rf "${stage}"
    return 1
  fi
  rm -rf "${stage}"
  log_ok "Claude staged artifacts"
}

validate_inputs() {
  require_pack_layout
  python3 "${PACK_DIR}/lib/validate_project_config.py" \
    "${PROJECT_YAML}" "${PROJECT_ROOT}" "${ROLES_DIR}"
  python3 "${CLAUDE_VALIDATOR}" sources "${PACK_DIR}" "${PROJECT_ROOT}"
  validate_rendered_staging
}

load_claude_project_skills

if [[ "${PREFLIGHT_ONLY}" -eq 1 ]]; then
  python3 "${PROJECT_PROFILE_CLI}" preview "${PACK_DIR}" "${PROJECT_ROOT}"
  validate_inputs
  preflight_claude_collisions
  log_ok "Claude preflight"
  exit 0
fi

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
  echo -e "${BOLD}Claude --check${NC}"
  validate_inputs
  python3 "${PACK_DIR}/lib/validate_project_docs.py" \
    "${PROJECT_YAML}" "${PROJECT_ROOT}"
  preflight_claude_collisions
  check_claude_contract
  exit 0
fi

echo -e "${BOLD}Claude Code setup — native Skills + Custom Agents${NC}"
validate_inputs
preflight_claude_collisions

# Shared validator runs before this first project write.
bash "${PACK_DIR}/scripts/scaffold_project_docs.sh"

python3 "${INSTRUCTIONS_CLI}" apply "${PACK_DIR}" "${PROJECT_ROOT}"
log_ok "AGENTS.md Claude managed block + CLAUDE.md thin entry"

sync_claude_skills
write_claude_agents

# 只合并可证明归属的 Hooks 和显式选择的写入保护；其余权限、Auto Memory、用户 Hooks 保留。
python3 "${PACK_DIR}/lib/workflow_hook_install.py" apply "${PACK_DIR}" "${PROJECT_ROOT}" claude

echo -e "${GREEN}${BOLD}✅ Claude setup complete${NC}"
