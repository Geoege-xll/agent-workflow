#!/usr/bin/env bash
# .agent-workflow/lib/common.sh — 三脚本共用
# shellcheck disable=SC2034

PACK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 所有安装/发现入口使用同一解释器选择规则。版本探测先于配置初始化、文档脚手架
# 和宿主产物写入；导出的路径也让聚合脚本的子进程沿用同一已验证运行时。
# shellcheck source=python_runtime.sh
source "${PACK_LIB_DIR}/python_runtime.sh"
workflow_select_python || return $?
python3() {
  command "${AGENT_WORKFLOW_PYTHON}" "$@"
}
PACK_DIR="$(cd "${PACK_LIB_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${PACK_DIR}/.." && pwd)"

PRODUCT_DIR="${PACK_DIR}/product"
ROLES_DIR="${PACK_DIR}/roles"
PLATFORMS_DIR="${PACK_DIR}/platforms"
SCRIPTS_DIR="${PACK_DIR}/scripts"
PROJECT_YAML="${PACK_DIR}/project.yaml"
ROLES_YAML="${PRODUCT_DIR}/ROLES.yaml"
WORKFLOW_MD="${PRODUCT_DIR}/WORKFLOW.md"
GLOBAL_CONSTRAINTS_MD="${PRODUCT_DIR}/GLOBAL_CONSTRAINTS.md"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_err()   { echo -e "${RED}[ERROR]${NC} $*"; }

require_pack_layout() {
  local missing=0
  for f in "${PROJECT_YAML}" "${WORKFLOW_MD}" "${ROLES_YAML}"; do
    if [[ ! -f "$f" ]]; then log_err "缺少 $f"; missing=1; fi
  done
  if [[ ! -d "${ROLES_DIR}" ]] || ! compgen -G "${ROLES_DIR}/xy-*.md" >/dev/null; then
    log_err "缺少 ${ROLES_DIR}/xy-*.md"; missing=1
  fi
  [[ "${missing}" -eq 0 ]] || exit 1
}

# 简易 YAML：读取 project.yaml 顶层 key 的字符串值（单行）
yaml_get() {
  local file="$1" key="$2"
  awk -v k="${key}" '
    $0 ~ "^" k ":[[:space:]]*" {
      sub("^[^:]+:[[:space:]]*", "")
      gsub(/^["'\'']|["'\'']$/, "")
      print; exit
    }
  ' "${file}"
}

role_body() {
  # 去掉 frontmatter 的正文
  local file="$1"
  awk 'BEGIN{f=0} /^---[[:space:]]*$/{f++; next} f>=2{print}' "${file}" \
    | sed '/^## define_subagent 参数/,$d' \
    | sed '/^## 工作区策略/,$d' \
    | sed 's/view_file/Read/g'
}

role_frontmatter() {
  local key="$1" file="$2"
  awk -v key="${key}" '
    BEGIN { in_fm=0 }
    /^---[[:space:]]*$/ { if (in_fm==0) { in_fm=1; next } else exit }
    in_fm && $0 ~ ("^" key ":[[:space:]]*") {
      sub("^[^:]+:[[:space:]]*", "")
      gsub(/^["'\'']|["'\'']$/, "")
      print; exit
    }
  ' "${file}"
}

# 从 ROLES.yaml 取角色字段（简易：角色块内 key）
roles_yaml_get() {
  local role="$1" key="$2"
  awk -v r="${role}" -v k="${key}" '
    $0 ~ "^[[:space:]]*" r ":" { in_r=1; next }
    in_r && /^[[:space:]]{0,2}[a-zA-Z_].*:/ && $0 !~ /^[[:space:]]{4,}/ && $0 !~ r { if ($0 ~ /^  [a-z]/ && $0 !~ /^    /) { if (!($0 ~ "^  " r)) in_r=0 } }
    in_r && $0 ~ "^[[:space:]]+" k ":[[:space:]]*" {
      sub("^[^:]+:[[:space:]]*", "")
      gsub(/^["'\'']|["'\'']$/, "")
      gsub(/#.*/, ""); gsub(/[[:space:]]+$/, "")
      print; exit
    }
  ' "${ROLES_YAML}"
}

# 更可靠：用 python 解析 ROLES.yaml / project.yaml（项目内已依赖 python3）
py_yaml() {
  python3 - "${PACK_LIB_DIR}" "$@" <<'PY'
import sys, re
# 极简：不依赖 PyYAML。支持本 pack 的缩进 YAML 子集。
lib_dir, path, *pathkeys = sys.argv[1:]
text = open(path, encoding="utf-8").read().splitlines()

def parse(lines):
    root = {}
    stack = [( -1, root )]
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        # list item
        if line.startswith("- "):
            val = line[2:].strip().strip("\"'")
            # attach to last list
            parent = stack[-1][1]
            if not isinstance(parent, list):
                # convert last key to list? use orphan
                continue
            parent.append(val)
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if v == "" or v == "|" or v == ">":
            # nested map or list follows
            # peek next non-empty
            node = {}
            parent[k] = node
            stack.append((indent, node))
        elif v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            items = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
            parent[k] = items
        else:
            parent[k] = v.strip("\"'")
    return root

# Fix list parsing: when key has empty value and next lines are "- "
def parse2(lines):
    def strip_inline_comment(value):
        quote = None
        escaped = False
        for index, char in enumerate(value):
            if escaped:
                escaped = False
                continue
            if char == "\\" and quote == '"':
                escaped = True
                continue
            if char in ('"', "'"):
                quote = None if quote == char else char if quote is None else quote
                continue
            if char == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
                return value[:index].rstrip()
        return value.strip()

    root = {}
    stack = [(-1, root)]
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            val = strip_inline_comment(line[2:]).strip().strip("\"'")
            if isinstance(parent, list):
                parent.append(val)
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), strip_inline_comment(v.strip())
        if v == "":
            # look ahead for list
            j = i
            is_list = False
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip() or nxt.lstrip().startswith("#"):
                    j += 1
                    continue
                nindent = len(nxt) - len(nxt.lstrip(" "))
                if nindent > indent and nxt.strip().startswith("- "):
                    is_list = True
                break
            if is_list:
                node = []
            else:
                node = {}
            if not isinstance(parent, dict):
                continue
            parent[k] = node
            stack.append((indent, node))
        else:
            if not isinstance(parent, dict):
                continue
            if v.startswith("[") and v.endswith("]"):
                inner = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
                parent[k] = inner
            elif k == "project_name" and indent == 0:
                # 自动项目名会使用带转义的 YAML 字符串，必须与安装器、Antigravity
                # 共用解码规则，不能把引号/反斜杠原样带入项目文档。
                sys.path.insert(0, lib_dir)
                from validate_project_config import parse_project_name
                parent[k] = parse_project_name(v)
            else:
                parent[k] = v.strip("\"'")
    return root

data = parse2(text)
cur = data
for pk in pathkeys:
    if cur is None:
        break
    if isinstance(cur, dict):
        cur = cur.get(pk)
    else:
        cur = None
if cur is None:
    sys.exit(0)
if isinstance(cur, list):
    print("\n".join(str(x) for x in cur))
elif isinstance(cur, dict):
    import json
    print(json.dumps(cur, ensure_ascii=False))
else:
    print(cur)
PY
}

project_profile_query() {
  local query="$1" role="${2:-}"
  python3 - "${PACK_LIB_DIR}" "${PROJECT_YAML}" "${PROJECT_ROOT}" "${ROLES_DIR}" "${query}" "${role}" <<'PY'
import shlex
import sys

lib_dir, config_path, project_root, roles_dir, query, role = sys.argv[1:]
sys.path.insert(0, lib_dir)
from validate_project_config import validate_with_profile

result = validate_with_profile(config_path, project_root, roles_dir)
if result.errors or result.profile is None:
    for error in result.errors:
        print(f"[ERROR] {error}", file=sys.stderr)
    raise SystemExit(1)
profile = result.profile
if query == "roles":
    print("\n".join(profile.enabled_roles))
elif query == "scopes":
    ui_roles = {"xy-web", "xy-desktop", "xy-apple", "xy-android"}
    for module in profile.modules:
        if (
            module.primary_role == role
            or role == "xy-qa"
            or role == "xy-uiux" and module.primary_role in ui_roles
        ):
            print(module.root)
elif query == "commands":
    for module in profile.modules:
        for command in module.verification_commands:
            print(f"{module.root}\t{command.purpose}\t{shlex.join(command.argv)}")
else:
    raise SystemExit(f"unsupported project profile query: {query}")
PY
}

role_scope_paths() {
  project_profile_query scopes "$1"
}

format_role_scopes_inline() {
  local role="$1" value rendered=""
  while IFS= read -r value; do
    [[ -n "${value}" ]] || continue
    if [[ -n "${rendered}" ]]; then
      rendered="${rendered}, "
    fi
    rendered="${rendered}\`${value}\`"
  done < <(role_scope_paths "${role}")
  printf '%s\n' "${rendered}"
}

toml_string() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().rstrip("\n"), ensure_ascii=False))'
}

json_string() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().rstrip("\n"), ensure_ascii=False))'
}

build_sandbox_table_md() {
  echo "| Role | Workspace scope |"
  echo "|:-----|:---------|"
  local r sb value
  while IFS= read -r r; do
    [[ -z "$r" ]] && continue
    sb=""
    while IFS= read -r value; do
      [[ -n "${value}" ]] || continue
      if [[ -n "${sb}" ]]; then
        sb="${sb}<br>"
      fi
      sb="${sb}\`${value}\`"
    done < <(role_scope_paths "${r}")
    [[ -z "$sb" ]] && sb="(repository-wide/read-only support scope)"
    echo "| \`${r}\` | ${sb} |"
  done < <(project_profile_query roles)
}

build_commands_section_md() {
  echo "* **Sync Claude Code**: \`bash .agent-workflow/setup_claude.sh\`"
  echo "* **Sync Codex**: \`bash .agent-workflow/setup_codex.sh\`"
  echo "* **Sync Antigravity**: \`bash .agent-workflow/setup_antigravity.sh\`"
  echo "* **Sync all hosts**: \`bash .agent-workflow/setup_all.sh\`"
  echo "* **Workspace attribution audit (soft)**: \`bash .agent-workflow/scripts/guard.sh\`"
  echo "* **Style and contract lint**: \`bash .agent-workflow/scripts/lint_rules.sh <file>\`"
  local root purpose command
  while IFS=$'\t' read -r root purpose command; do
    [[ -n "${command}" ]] || continue
    echo "* **Discovered ${purpose} (${root})**: \`${command}\`"
  done < <(project_profile_query commands)
}

render_product_workflow() {
  cat "${WORKFLOW_MD}"
}

upsert_marked_block() {
  # upsert_marked_block FILE BEGIN END CONTENT_FILE
  local target="$1" begin="$2" end="$3" content_file="$4"
  local tmp marker_state begin_count end_count begin_line end_line target_dir target_mode
  target_dir=$(dirname "${target}")
  mkdir -p "${target_dir}"
  tmp=$(mktemp "${target}.tmp.XXXXXX")
  if [[ ! -f "${target}" ]]; then
    cp "${content_file}" "${tmp}"
    mv "${tmp}" "${target}"
    return 0
  fi
  target_mode=$(stat -f '%Lp' "${target}" 2>/dev/null || stat -c '%a' "${target}")
  marker_state=$(awk -v begin="${begin}" -v end="${end}" '
    $0 == begin { begin_count++; if (begin_line == 0) begin_line=NR }
    $0 == end { end_count++; if (end_line == 0) end_line=NR }
    END { print begin_count + 0, end_count + 0, begin_line + 0, end_line + 0 }
  ' "${target}")
  read -r begin_count end_count begin_line end_line <<< "${marker_state}"

  if [[ "${begin_count}" -eq 1 && "${end_count}" -eq 1 && "${begin_line}" -lt "${end_line}" ]]; then
    awk -v begin="${begin}" -v end="${end}" -v cf="${content_file}" '
      BEGIN { while ((getline l < cf) > 0) b = b l ORS; close(cf) }
      $0 == begin { printf "%s", b; skip=1; next }
      $0 == end { skip=0; next }
      skip != 1 { print }
    ' "${target}" > "${tmp}"
    chmod "${target_mode}" "${tmp}"
    mv "${tmp}" "${target}"
  elif [[ "${begin_count}" -eq 0 && "${end_count}" -eq 0 ]]; then
    {
      cat "${target}"
      echo
      cat "${content_file}"
    } > "${tmp}"
    chmod "${target_mode}" "${tmp}"
    mv "${tmp}" "${target}"
  else
    rm -f "${tmp}"
    log_err "malformed managed markers in ${target}: ${begin_count} begin, ${end_count} end"
    return 1
  fi
}
