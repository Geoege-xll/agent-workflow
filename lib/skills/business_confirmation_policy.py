#!/usr/bin/env python3
"""校验实际插件入口的条件式业务确认、独立权限与任务例外。"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import json
import re
from lib.platform_fs import os
import stat
import sys
from pathlib import Path
from typing import Iterable

# 直接脚本由上方可信 __file__ 引导到核心根，包模式则沿用调用方已选定的固定核心。
from lib.skills.skill_contracts import expand_skill_contract, verification_scope_errors
from lib.task_graph import SOLUTION_GATE_RE


# 只有 WORKFLOW 声明这张适用条件表。schema 和全局约束链接同一节；
# 校验整个代码块，避免在正确的首几行后追加无条件签字项仍然通过打包。
POLICY_AUTHORITY = Path("product/WORKFLOW.md")
POLICY_SECTION = "### Business confirmation policy"
POLICY_REFERENCE = "(WORKFLOW.md#business-confirmation-policy)"
POLICY_CONSUMERS = (Path("product/AGENT_SCHEMA.md"), Path("product/GLOBAL_CONSTRAINTS.md"))
POLICY_HEADER = "business_confirmation_policy:"
DEFAULT_POLICY = """business_confirmation_policy:
  requirements_approved: current_goal_and_scope
  solution_approved: material_solution_decision
  visual_approved: selected_required_prototype
  additional_gates: exceptional"""

COMMON_SOURCES = (
    "product/WORKFLOW.md",
    "product/AGENT_SCHEMA.md",
    "product/GLOBAL_CONSTRAINTS.md",
    "plugins/main-session-context.md",
    "platforms/shared/skills/xy-workflow/SKILL.md",
    "platforms/shared/skills/xy-prototype-verify/SKILL.md",
    "platforms/shared/skills/xy-build-verify/SKILL.md",
    "roles/xy-uiux.md",
    "product/ROLES.yaml",
)

# 三端均从主会话进入业务适配，再按宿主选取 PM 细则。直接核验这些随包发布的
# 文件，确保变更到达真实调用链；不为检查器额外制造一份“安装后”指令模板。
HOST_INTEGRATIONS = {
    host: f"platforms/{host}/references/pm-integration.md"
    for host in ("codex", "claude", "antigravity")
}
HOST_SOURCES = {
    "codex": ("plugins/plugin-context.md", HOST_INTEGRATIONS["codex"], "platforms/codex/WORKER_CONSTRAINTS.md"),
    "claude": ("plugins/plugin-context.md", HOST_INTEGRATIONS["claude"]),
    "antigravity": ("plugins/antigravity/plugin-context.md", HOST_INTEGRATIONS["antigravity"]),
}
HOST_SOURCES["all"] = tuple(dict.fromkeys(path for paths in HOST_SOURCES.values() for path in paths))

REQUIRED_ANCHORS = (
    "requirements_approved",
    "solution_decisions",
    "solution_approved:<id>@<sha256>",
    "visual_approved",
    "baseline_ready",
    "ia_ready",
    "prototype_verified",
    "visual_review_ready",
    "additional_business_confirmation:",
    "decision_scope:",
    "resume_condition:",
    "Platform security prompts",
)

FORBIDDEN_PATTERNS = (
    # 已退役的固定轮次说法会让真实入口跳过有分歧的方案，或让已定方案反复求批。
    ("fixed confirmation sequence", re.compile(
        r"\b(?:requirements/visual two-step policy|two[- ]stage business confirmation policy|"
        r"(?:normal|default) two business confirmations|no business confirmation after\s+`?requirements_approved|"
        r"(?:all|every) (?:Full |Light )?requests? (?:must obtain|always require|requires?) solution (?:approval|confirmation))\b",
        re.I,
    )),
    ("legacy Baseline business gate", re.compile(r"\bBaseline\s+Proceed\b", re.I)),
    ("legacy IA business gate", re.compile(r"\bIA\s+Proceed\b", re.I)),
    ("legacy Plan business gate", re.compile(r"\bPlan\s+Proceed\b", re.I)),
    (
        "automatic evidence promoted to business confirmation",
        re.compile(
            r"\b(?:document|contract|implementation\s+plan|plan|HTML[ -]?preview|"
            r"baseline|IA|build|QA|rework|closeout)\s+(?:user\s+)?(?:approval|confirmation)\b",
            re.I,
        ),
    ),
    (
        "automatic evidence promoted to business confirmation",
        re.compile(
            r"\b(?:approve|confirm)\s+(?:the\s+)?(?:document|contract|"
            r"implementation\s+plan|plan|HTML[ -]?preview|baseline|IA|build|QA|rework|closeout)\b",
            re.I,
        ),
    ),
)

ADDITIONAL_CONFIRMATION_PATTERNS = (
    re.compile(
        r"\b(?:must|shall|is\s+required\s+to)\s+"
        r"(?:obtain|request|record|wait\s+for)\s+(?:an?\s+|the\s+)?"
        r"(?P<name>[a-z][a-z0-9 _-]{1,80}?)\s+(?:approval|confirmation)\b",
        re.I,
    ),
    re.compile(
        r"\b(?P<name>[a-z][a-z0-9 _-]{1,80}?)\s+(?:approval|confirmation)\s+"
        r"(?:is|are)\s+(?:required|mandatory)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:the\s+)?(?:user|PM)\s+must\s+(?:approve|confirm)\s+(?:the\s+)?"
        r"(?P<name>[a-z][a-z0-9 _-]{1,80}?)\s+before\b",
        re.I,
    ),
    re.compile(
        r"\b(?:do\s+not|must\s+not|cannot)\s+proceed\s+until\s+(?:the\s+)?"
        r"(?:user|PM)\s+(?:approves?|confirms?)\s+(?:the\s+)?"
        r"(?P<name>[a-z][a-z0-9 _-]{1,80}?)(?:[.;]|$)",
        re.I,
    ),
    re.compile(
        r"\b(?P<name>[a-z][a-z0-9 _-]{1,80}?)\s+(?:approval|confirmation)\s+"
        r"must\s+be\s+(?:obtained|recorded|granted)\b",
        re.I,
    ),
    re.compile(
        r"\bproceed\s+only\s+after\s+(?:the\s+)?(?:user|PM)\s+"
        r"(?:approves?|confirms?)\s+(?:the\s+)?(?P<name>[a-z][a-z0-9 _-]{1,80}?)(?:[.;]|$)",
        re.I,
    ),
    re.compile(
        r"\b(?:implementation|work|task)\s+(?:is|remains)\s+blocked\s+pending\s+"
        r"(?P<name>[a-z][a-z0-9 _-]{1,80}?)\s+(?:approval|confirmation)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:the\s+)?(?:PM|user)\s+cannot\s+(?:continue|proceed)\s+without\s+"
        r"(?P<name>[a-z][a-z0-9 _-]{1,80}?)\s+(?:approval|confirmation)\b",
        re.I,
    ),
)

EXCEPTION_FIELDS = (
    "name",
    "reason",
    "decision_scope",
    "options",
    "evidence",
    "resume_condition",
)


def _excerpt(body: str, match: re.Match[str]) -> str:
    start = max(0, body.rfind("\n", 0, match.start()) + 1)
    end = body.find("\n", match.end())
    if end < 0:
        end = len(body)
    return " ".join(body[start:end].split())[:180]


def _is_negated_confirmation(body: str, match: re.Match[str]) -> bool:
    after = body[match.end() : match.end() + 80]
    if re.match(r"\s+(?:is|are)\s+not\s+(?:required|mandatory|needed)\b", after, re.I):
        return True
    before = body[max(0, match.start() - 60) : match.start()]
    return re.search(
        r"\b(?:(?:does|do)\s+not\s+require|"
        r"(?:PM|user)\s+must\s+not\s+(?:request|obtain|record))\s+"
        r"(?:an?\s+|the\s+)?$",
        before,
        re.I,
    ) is not None


def _exception_records(body: str) -> list[dict[str, str]]:
    """Extract non-template exception records from fenced or indented YAML snippets."""

    records: list[dict[str, str]] = []
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "additional_business_confirmation:":
            continue
        fields: dict[str, str] = {}
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            if not candidate.strip() or candidate.lstrip().startswith("#"):
                cursor += 1
                continue
            if candidate.strip().startswith("```"):
                break
            match = re.match(r"^\s{2,}([a-z_]+):\s*(.*?)\s*$", candidate)
            if not match:
                if not candidate.startswith((" ", "\t")):
                    break
                cursor += 1
                continue
            field, value = match.groups()
            if field in {"options", "evidence"} and not value:
                field_indent = len(candidate) - len(candidate.lstrip())
                entries: list[str] = []
                cursor += 1
                while cursor < len(lines):
                    list_line = lines[cursor]
                    if not list_line.strip():
                        cursor += 1
                        continue
                    list_indent = len(list_line) - len(list_line.lstrip())
                    item = re.match(r"^\s*-\s+(.+?)\s*$", list_line)
                    if list_indent <= field_indent or item is None:
                        break
                    entries.append(item.group(1))
                    cursor += 1
                fields[field] = "[" + ", ".join(entries) + "]" if entries else ""
                continue
            fields[field] = value
            cursor += 1
        present_values = [fields.get(field, "") for field in EXCEPTION_FIELDS]
        if any("<" in value or ">" in value for value in present_values):
            continue
        records.append(fields)
    return records


def _yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return parsed if isinstance(parsed, str) else value
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _record_error(record: dict[str, str]) -> str | None:
    missing = [field for field in EXCEPTION_FIELDS if not record.get(field)]
    if missing:
        return "missing fields: " + ", ".join(missing)
    scalar_fields = ("name", "reason", "decision_scope", "resume_condition")
    invalid_scalars = {
        "[]",
        "{}",
        "null",
        "~",
        "true",
        "false",
    }
    for field in scalar_fields:
        value = _yaml_scalar(record[field])
        if value.casefold() in invalid_scalars | {"tbd", "none", "unknown", "n/a"} or len(value) < 3:
            return f"{field} must be a concrete scalar"
    for field in ("options", "evidence"):
        value = record[field].strip()
        if not (value.startswith("[") and value.endswith("]") and value[1:-1].strip()):
            return f"{field} must be a non-empty inline list"
        entries = [entry.strip().casefold() for entry in value[1:-1].split(",")]
        if any(entry in {"", "none", "tbd", "unknown", "n/a"} for entry in entries):
            return f"{field} must contain concrete entries"
    reason = _yaml_scalar(record["reason"]).casefold()
    if not re.search(
        r"(?:explicit(?:ly)?\s+(?:user\s+)?request|user\s+request|"
        r"cannot\s+safely\s+be\s+folded|"
        r"(?:existing|default)\s+(?:business\s+)?confirmations?\s+(?:are|is)\s+insufficient)",
        reason,
    ):
        return "reason must state an explicit user request or why existing confirmations are insufficient"
    return None


def _gate_key(name: str) -> str:
    stop = {"a", "an", "the", "business", "user", "pm", "additional", "final"}
    tokens = [token for token in re.findall(r"[a-z0-9]+", name.casefold()) if token not in stop]
    return " ".join(tokens)


def _record_matches_gate(record: dict[str, str], gate_name: str) -> bool:
    key = _gate_key(gate_name)
    if not key:
        return False
    haystack = _gate_key(
        _yaml_scalar(record.get("name", ""))
        + " "
        + _yaml_scalar(record.get("decision_scope", ""))
    )
    return all(token in haystack.split() for token in key.split())


def _split_inline_gate_items(value: str) -> tuple[list[str], str | None]:
    if not (value.startswith("[") and value.endswith("]")):
        return [], "gates must be an inline list or an indented scalar list"
    content = value[1:-1].strip()
    if not content:
        return [], None
    items: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    for index, character in enumerate(content):
        if quote == '"' and character == "\\" and not escaped:
            escaped = True
            continue
        if character in {'"', "'"} and not escaped:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
        elif character == "," and quote is None:
            items.append(content[start:index].strip())
            start = index + 1
        escaped = False
    if quote is not None:
        return [], "unterminated quoted gate value"
    items.append(content[start:].strip())
    return items, None


def _parse_gate_scalar(raw: str) -> tuple[str | None, str | None]:
    raw = raw.strip()
    if not raw:
        return None, "empty gate value"
    if raw.startswith(('"', "'")):
        if len(raw) < 2 or raw[-1] != raw[0]:
            return None, "unterminated quoted gate value"
        value = _yaml_scalar(raw)
        if not value:
            return None, "empty gate value"
        return value, None
    if re.fullmatch(r"[a-z][a-z0-9_-]*", raw):
        return raw, None
    return None, f"gate value must be a string scalar, not {raw!r}"


def _gate_names(body: str) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    errors: list[str] = []
    lines = body.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*gates:\s*(.*?)\s*(?:#.*)?$", line)
        if not match:
            continue
        inline = match.group(1)
        if inline:
            items, list_error = _split_inline_gate_items(inline)
            if list_error:
                errors.append(f"line {index + 1}: {list_error}")
                continue
            for raw in items:
                name, item_error = _parse_gate_scalar(raw)
                if item_error:
                    errors.append(f"line {index + 1}: {item_error}")
                elif name is not None:
                    names.add(name)
            continue
        base_indent = len(line) - len(line.lstrip())
        found_item = False
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                continue
            indent = len(candidate) - len(candidate.lstrip())
            if indent <= base_indent:
                break
            item = re.match(r"^\s*-\s*(?P<value>.*?)\s*$", candidate)
            if item is None:
                errors.append(f"line {index + 1}: gates contains a non-list or mapping value")
                continue
            found_item = True
            name, item_error = _parse_gate_scalar(item.group("value"))
            if item_error:
                errors.append(f"line {index + 1}: {item_error}")
            elif name is not None:
                names.add(name)
        if not found_item:
            errors.append(f"line {index + 1}: gates block is empty")
    return names, errors


def _is_visual_gate(name: str) -> bool:
    if name == "visual_approved:<page-id>@<dependency-fingerprint>":
        return True
    return re.fullmatch(
        r"visual_approved:[a-z0-9][a-z0-9._/-]*@[a-z0-9][a-z0-9._-]*",
        name,
    ) is not None


def _is_applicable_or_external_gate(name: str) -> bool:
    # 模板可演示有范围的占位门值。具体方案必须和调度器采用相同的实际格式，
    # 只有运行时对请求、事项和正文重新计算摘要后才可作为用户的当前授权。
    return (
        name in {"requirements_approved", "platform_security_prompt", "solution_approved:<id>@<sha256>"}
        or SOLUTION_GATE_RE.fullmatch(name) is not None
        or _is_visual_gate(name)
    )


def _is_conditional_solution_instruction(body: str, match: re.Match[str]) -> bool:
    """只豁免明确作用于实质决定的方案指令；通篇提到方案不能覆盖另一条固定签字。"""
    name = match.group("name").strip().casefold()
    if name not in {"solution", "material solution"}:
        return False
    # 在同一句前后取条件，允许 Markdown 的自然换行；句号和段落隔离
    # 两条独立指令，防止上一段的真实方案理由被套用到下一段的固定审批。
    before = re.split(r"[.!?;。；]|\n\s*\n", body[:match.start()])[-1]
    after = re.split(r"[.!?;。；]|\n\s*\n", body[match.end():], maxsplit=1)[0]
    sentence = " ".join((before + match.group() + after).casefold().split())
    return re.search(
        r"\b(?:for|when|if|where) (?:an? |the )?(?:task depends on (?:an? |the )?)?"
        r"(?:material (?:unresolved |open )?|unresolved material )(?:solution )?(?:decision|trade-?off)\b",
        sentence,
    ) is not None


def _validate_structured_exceptions(path: Path, body: str) -> list[str]:
    errors: list[str] = []
    matches: list[re.Match[str]] = []
    for pattern in ADDITIONAL_CONFIRMATION_PATTERNS:
        for match in pattern.finditer(body):
            name = " ".join(match.group("name").lower().split())
            if name in {"requirement", "requirements", "visual", "final visual"} or _is_conditional_solution_instruction(body, match):
                continue
            matches.append(match)
    records = _exception_records(body)
    gates, gate_errors = _gate_names(body)
    errors.extend(f"invalid gates in {path}: {error}" for error in gate_errors)
    for gate in sorted(gates):
        if _is_applicable_or_external_gate(gate):
            continue
        # 裸门没有事项或页面范围，不能靠同名例外记录包装成已批准。
        if gate in {"solution_approved", "visual_approved"}:
            errors.append(f"unscoped confirmation gate {gate!r} in {path}")
        elif re.fullmatch(r"[a-z][a-z0-9_-]*", gate) is None:
            errors.append(f"unsupported or scoped gate {gate!r} in {path}")
    if matches and not records:
        errors.append(
            "unstructured additional business confirmation in "
            f"{path}: {_excerpt(body, matches[0])}"
        )

    valid_records: list[dict[str, str]] = []
    for record in records:
        record_error = _record_error(record)
        if record_error:
            errors.append(
                f"incomplete additional_business_confirmation in {path}: {record_error}"
            )
        else:
            valid_records.append(record)
    record_names = [_yaml_scalar(record["name"]) for record in valid_records]
    duplicate_names = sorted({name for name in record_names if record_names.count(name) > 1})
    for name in duplicate_names:
        errors.append(f"duplicate additional_business_confirmation name {name!r} in {path}")
    valid_by_name = {
        _yaml_scalar(record["name"]): record
        for record in valid_records
        if _yaml_scalar(record["name"]) not in duplicate_names
    }
    exceptional_gates = {
        name
        for name in gates
        if not _is_applicable_or_external_gate(name)
        and re.fullmatch(r"[a-z][a-z0-9_-]*", name)
    }
    for gate in sorted(exceptional_gates):
        if gate not in valid_by_name:
            errors.append(
                f"exceptional gate {gate!r} has no complete additional_business_confirmation in {path}"
            )
    for record in valid_records:
        name = _yaml_scalar(record["name"])
        if name not in exceptional_gates:
            errors.append(
                f"additional_business_confirmation {name!r} is not referenced by gates in {path}"
            )
    for match in matches:
        if not any(
            _yaml_scalar(record["name"]) in exceptional_gates
            and _record_matches_gate(record, match.group("name"))
            for record in valid_records
        ):
            errors.append(
                "unstructured additional business confirmation in "
                f"{path}: {_excerpt(body, match)}"
            )
    return errors


def _secure_read_pack_text(pack: Path, relative: str) -> str:
    """Read one pack-owned regular file without following links or blocking on FIFOs."""

    parts = Path(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise OSError(f"unsafe relative path: {relative}")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptors: list[int] = []
    try:
        current = os.open(pack, directory_flags)
        descriptors.append(current)
        for component in parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            descriptors.append(current)
        file_descriptor = os.open(parts[-1], file_flags, dir_fd=current)
        descriptors.append(file_descriptor)
        info = os.fstat(file_descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"not a regular file: {relative}")
        if info.st_nlink != 1:
            raise OSError(f"hard-linked file is not allowed: {relative}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_descriptor, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > 2 * 1024 * 1024:
                raise OSError(f"file exceeds 2 MiB limit: {relative}")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="strict")
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def read_instruction_contract(root: Path, relative: str) -> str:
    """读取入口及其显式分支用于语义校验，引用仍经过同样的安全文件读取。

    不展开普通辅助链接，不修改 Skill 文件。将入口缩短不能让审批/QA 规则逃过
    构建检查；分支缺失、非法引用或非普通文件都会使插件构建失败。
    """
    body = _secure_read_pack_text(root, relative)
    # Codex 的强制注入源不能为空；预检和渲染共用此入口，避免“文件存在但角色
    # 边界为空”仍被打包。只约束 Codex 专属文件，不给另外两个宿主增加依赖。
    if relative == "platforms/codex/WORKER_CONSTRAINTS.md" and not body.strip():
        raise ValueError("Codex WORKER_CONSTRAINTS.md must not be empty")
    if Path(relative).name != "SKILL.md":
        return body
    return expand_skill_contract(
        body,
        lambda reference: _secure_read_pack_text(
            root, (Path(relative).parent / reference).as_posix()
        ),
    )


def validate_business_confirmation_texts(
    sources: Iterable[tuple[Path, str]],
) -> list[str]:
    errors: list[str] = []
    combined_parts: list[str] = []
    authority_count = 0
    for path, body in sources:
        # 构建前接收绝对资源路径，加载后的投影则传入包内路径。两条入口
        # 均核验同一权威小节；消费者可以解释字段，却不能重新声明默认政策。
        relative = Path(*path.parts[-2:])
        if relative == POLICY_AUTHORITY:
            authority_count += 1
            section_pattern = r"^" + re.escape(POLICY_SECTION) + r"\n(.*?)(?=^#{1,3} |\Z)"
            section = re.search(section_pattern, body, re.M | re.S)
            fenced_policy = "```yaml\n" + DEFAULT_POLICY + "\n```"
            if not section or fenced_policy not in section.group(1) or body.count(POLICY_HEADER) != 1:
                errors.append(f"missing or invalid canonical business confirmation policy in {path}")
        else:
            if POLICY_HEADER in body:
                errors.append(f"duplicate business confirmation policy outside its authority: {path}")
            if relative in POLICY_CONSUMERS and POLICY_REFERENCE not in body:
                errors.append(f"missing canonical business confirmation policy reference in {path}")
        combined_parts.append(body)
        for label, pattern in FORBIDDEN_PATTERNS:
            for match in pattern.finditer(body):
                if _is_negated_confirmation(body, match):
                    continue
                errors.append(f"{label} in {path}: {_excerpt(body, match)}")
                break
        errors.extend(_validate_structured_exceptions(path, body))

    if authority_count != 1:
        errors.append(f"expected one business confirmation authority, found {authority_count}")
    combined = "\n".join(combined_parts)
    for anchor in REQUIRED_ANCHORS:
        if anchor not in combined:
            errors.append(f"business confirmation policy missing anchor: {anchor}")
    return errors


def validate_execution_texts(sources: Iterable[tuple[Path, str]]) -> list[str]:
    """核对当前插件的执行等级、schema 2 任务包和各宿主独立调度边界。"""
    errors: list[str] = []
    required = (
        "Light", "Full", "schema_version: 2", "workflow_level", "module", "role",
        "agent_alias", "instance_policy: fresh", "context_policy: handoff_only", "agent_retired",
    )
    host_required = {
        "codex": ('fork_turns: "none"', "agent_retired", "interrupt_agent", "nested delegation disabled"),
        "claude": ("plugin-qualified `subagent_type`", "xy-workflow:xy-backend", "SendMessage", "TaskStop", "agent_retired", "never delegate"),
        "antigravity": ("invoke_subagent", "worktree", "agent_retired", "role Agents never delegate"),
    }
    for path, body in sources:
        # 等级名大小写固定为 Trivial；普通英文形容词 trivial 不是一条执行路由。
        if re.search(r"\bTrivial\b", body):
            errors.append(f"plugin execution contract contains retired Trivial routing: {path}")
        normalized = " ".join(body.split())
        anchors = required if path.name in {"WORKFLOW.md", "AGENT_SCHEMA.md"} else ()
        # 三端细则文件同名，使用其固定的宿主父目录区分调度工具与禁嵌套约束。
        if path.name == "pm-integration.md":
            host = path.parent.parent.name
            if host not in host_required:
                errors.append(f"unsupported host integration source: {path}")
                continue
            anchors = ("schema_version: 2", "instance_policy: fresh", "context_policy: handoff_only",
                       *host_required[host])
        elif path.name == "main-session-context.md":
            # 原生 Hook、Claude PM 和 AGY 规则都投影此入口；缺少任一分支即无法到达后续权威。
            anchors = ("@INVOCATION@ [@MAINTENANCE_ACTIONS@]", "skills/xy-config/SKILL.md", "`@BUSINESS_ADAPTER@`",
                       "skills/xy-workflow/SKILL.md", "product/WORKFLOW.md")
        elif path.name == "plugin-context.md":
            # 只承认同包指定细则。共享 adapter 在运行时按宿主替换路径里的 <host>。
            integration = (HOST_INTEGRATIONS["antigravity"] if path.parent.name == "antigravity"
                           else "platforms/<host>/references/pm-integration.md")
            anchors = (integration, "product/WORKFLOW.md", "instance_policy: fresh",
                       "context_policy: handoff_only")
        for anchor in anchors:
            if anchor not in normalized:
                errors.append(f"plugin execution contract missing {anchor!r}: {path}")
    return errors


def validate_business_confirmation_pack(pack: Path, host: str) -> list[str]:
    if host not in HOST_SOURCES:
        return [f"unsupported business confirmation host: {host}"]

    errors: list[str] = []
    sources: list[tuple[Path, str]] = []
    for relative in (*COMMON_SOURCES, *HOST_SOURCES[host]):
        path = pack / relative
        try:
            body = read_instruction_contract(pack, relative)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"cannot read business confirmation source {path}: {exc}")
            continue
        sources.append((path, body))

    errors.extend(validate_business_confirmation_texts(sources))
    errors.extend(validate_execution_texts(sources))
    # 三个宿主都调用这个只读源检查，因此验证范围策略只维护一套，且缺失/反向
    # 规则在实际项目写入之前拒绝，不依赖安装后的模型自行发现冲突。
    verification = next((body for path, body in sources
                         if path == pack / "platforms/shared/skills/xy-build-verify/SKILL.md"), "")
    if verification:
        errors.extend(verification_scope_errors(verification))
    return errors


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: business_confirmation_policy.py PACK_DIR codex|claude|antigravity|all",
            file=sys.stderr,
        )
        return 2
    errors = validate_business_confirmation_pack(Path(sys.argv[1]), sys.argv[2])
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print(f"[OK] {sys.argv[2]} conditional business confirmation policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
