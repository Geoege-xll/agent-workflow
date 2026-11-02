"""把 PM 明示的精简决定机械组装为初始任务图，不推导业务权威。

本入口只补重复结构与当前文件指纹；规则选择、保护边界、门禁、批准及任务合同
仍来自输入。完成状态和执行身份不能经初始化导入，旧图继续使用原有 update。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from typing import Any, Callable

try:
    from . import task_graph_records as records
    from .task_graph import TaskGraphError
    from .validate_project_config import validate_docs
    from .standard_paths import builtin_source_path, source_domain
    from .validate_project_docs import collect_standard_leaves, STANDARD_RULE_RE, validate_rule_definitions
except ImportError:
    import task_graph_records as records
    from task_graph import TaskGraphError
    from validate_project_config import validate_docs
    from standard_paths import builtin_source_path, source_domain
    from validate_project_docs import collect_standard_leaves, STANDARD_RULE_RE, validate_rule_definitions


INPUT_FIELDS = {
    "request_id", "requirements_fingerprint", "capacity", "approved_gates",
    "active_paths", "active_semantic_locks", "adapter_path", "standards", "tasks",
}
STANDARDS_FIELDS = {
    "index_path", "root", "required_engineering_rule_ids", "required_design_rule_ids",
    "leaves", "protected_paths",
}
TASK_FIELDS = {
    "id", "task_type", "role", "surface_kind", "design_mode", "goal", "depends_on",
    "blocks", "gates", "owned_paths", "semantic_locks", "input_contracts",
    "output_contracts", "acceptance_evidence", "verification_commands", "ui_change",
    "required_skills", "audit_surfaces", "standards_exceptions", "selected_standards",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _object(value: Any, label: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    """白名单既约束精简格式，也阻止把旧图完成态、执行身份或权限容器带入新图。"""
    if not isinstance(value, dict):
        raise TaskGraphError(f"{label} must be an object")
    if set(value) - allowed:
        raise TaskGraphError(f"{label} has unsupported field(s): {', '.join(sorted(set(value) - allowed))}")
    if required - set(value):
        raise TaskGraphError(f"{label} is missing field(s): {', '.join(sorted(required - set(value)))}")
    return value


def _strings(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if (not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(set(value)) != len(value) or (nonempty and not value)):
        raise TaskGraphError(f"{label} must contain unique non-empty strings")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskGraphError(f"{label} must be a non-empty string")
    return value


def _verification(value: Any, label: str) -> None:
    """保留现有命令字符串和 run/expected 对象两种任务包表达，不执行命令。"""
    if not isinstance(value, list) or not value:
        raise TaskGraphError(f"{label} must contain verification commands")
    for position, command in enumerate(value):
        item_label = f"{label}[{position}]"
        if isinstance(command, str):
            _text(command, item_label)
        else:
            _object(command, item_label, {"run", "expected"}, {"run", "expected"})
            _text(command["run"], f"{item_label}.run")
            _text(command["expected"], f"{item_label}.expected")


def _adapter_docs(root: Path, relative: str) -> tuple[dict[str, str], str]:
    """复用适配器现有 docs 解析与路径校验；不发现业务模块或读取完整规范树。"""
    expected = records.file_digest(root, relative)
    body = records.read_record(root / relative)
    if records.digest(body) != expected:
        raise TaskGraphError("adapter changed while reading init decisions")
    lines = body.decode("utf-8").splitlines()
    # section_lines 只取首段；先拒绝重复或非块状 docs，避免解析时静默选择一份权威。
    sections = [line for line in lines if re.match(r"^docs\s*:", line)]
    if len(sections) != 1 or not re.fullmatch(r"docs:\s*(?:#.*)?", sections[0]):
        raise TaskGraphError("init adapter requires exactly one block docs section")
    errors: list[str] = []
    docs = validate_docs(lines, root, errors)
    if errors:
        raise TaskGraphError("invalid init adapter docs: " + "; ".join(errors))
    return docs, expected


def initialize(decisions: Any, root: Path, output: Path,
               validate: Callable[[str, dict[str, Any]], dict[str, Any]], *,
               input_path: Path | None = None, input_body: bytes | None = None) -> dict[str, Any]:
    """验证 PM 决定、补固定字段、复用原校验后，仅向明确的新文件原子发布。

    读取集合在发布前再次核对，失败不产生输出。最终发布仍用 records.publish 的
    安全读取、协作锁和 missing 前置条件，不另建备份、状态账本或执行器。
    """
    source = _object(decisions, "init decisions", INPUT_FIELDS,
                     {"request_id", "capacity", "standards", "tasks"})
    # JSON 标准不包含 NaN/Infinity；Python 解码器接受的扩展值不能落入正式记录。
    json.dumps(source, allow_nan=False)
    request_id = _text(source["request_id"], "request_id")
    if root.is_symlink():
        raise TaskGraphError("init root must not be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise TaskGraphError("init root must be an existing directory")
    if output.exists() or output.is_symlink():
        raise TaskGraphError("init output must be a new file; update existing graphs with update")

    sources: dict[str, str] = {}

    def fingerprint(relative: str) -> str:
        """每个显式文件只首次取指纹；不因同一叶被多任务使用而重复读取正文。"""
        _text(relative, "init fingerprint path")
        if relative not in sources:
            sources[relative] = records.file_digest(root, relative)
        return sources[relative]

    raw_standards = _object(source["standards"], "standards", STANDARDS_FIELDS,
                            {"required_engineering_rule_ids", "required_design_rule_ids", "leaves", "protected_paths"})
    standards = copy.deepcopy(raw_standards)
    if ("index_path" in standards) != ("root" in standards):
        raise TaskGraphError("standards.index_path and standards.root must be provided together")
    if "index_path" not in standards:
        adapter = source.get("adapter_path", "project.yaml")
        docs, adapter_fingerprint = _adapter_docs(root, adapter)
        sources[adapter] = adapter_fingerprint
        standards.update(index_path=docs["standards"], root=docs["standards_root"].rstrip("/"))
    elif "adapter_path" in source:
        raise TaskGraphError("adapter_path cannot be combined with explicit standards.index_path/root")
    leaves = standards["leaves"]
    if not isinstance(leaves, list):
        raise TaskGraphError("standards.leaves must be an array")
    indexed_leaves: dict[str, dict[str, Any]] = {}
    for position, leaf in enumerate(leaves):
        label = f"standards.leaves[{position}]"
        _object(leaf, label, {"path", "domain", "rule_ids"}, {"path", "domain", "rule_ids"})
        path = _text(leaf["path"], f"{label}.path")
        _text(leaf["domain"], f"{label}.domain")
        if path in indexed_leaves:
            raise TaskGraphError("standards.leaves must not duplicate paths")
        leaf["content_fingerprint"] = fingerprint(path)
        if builtin_source_path(path) is None:
            # 保留说明文件不产生规范权威；init拥有真实root，须核对选定项目叶确有
            # 相同domain及规则ID，而不能只给任意备注文件贴一组规则编号。
            body_bytes = records.read_record(root / path)
            if records.digest(body_bytes) != leaf["content_fingerprint"]:
                raise TaskGraphError(f"init project standards changed while reading: {path}")
            text = body_bytes.decode("utf-8")
            errors: list[str] = []
            validate_rule_definitions(text, path, errors)
            matches = STANDARD_RULE_RE.findall(text)
            if errors or not matches or re.findall(r"(?im)^- Domain: (engineering|design)\s*$", text) != [leaf["domain"]]:
                raise TaskGraphError(f"selected project standards must contain valid rules and matching domain: {path}")
            if set(_strings(leaf["rule_ids"], f"{label}.rule_ids")) - {rule_id for rule_id, _severity in matches}:
                raise TaskGraphError(f"selected project standards claims unknown rule IDs: {path}")
        indexed_leaves[path] = leaf
    # 缺失索引只在没有项目规则叶时合法。保留配置路径用于以后新增专项规范；
    # 不创建空索引、不以占位SHA冒充已读取。实际缺失事实仅由有root的init确认。
    try:
        standards["index_fingerprint"] = fingerprint(standards["index_path"])
    except FileNotFoundError:
        if any(builtin_source_path(path) is None for path in indexed_leaves):
            raise TaskGraphError("project standards leaves require an existing standards index")
        relative_root = Path(standards["root"])
        if relative_root.is_absolute() or ".." in relative_root.parts or relative_root.as_posix() != standards["root"]:
            raise TaskGraphError("standards.root must be a normalized project-relative directory")
        project_standards = root / relative_root
        if not project_standards.resolve().is_relative_to(root) or any(parent.is_symlink() for parent in (project_standards, *project_standards.parents) if parent != root and root in parent.parents):
            raise TaskGraphError("standards.root must not use symlinks or escape the project")
        errors: list[str] = []
        documents = collect_standard_leaves(project_standards, errors) if project_standards.exists() else {}
        if errors:
            raise TaskGraphError("invalid project standards: " + "; ".join(errors))
        if any(STANDARD_RULE_RE.search(body) for body in documents.values()):
            raise TaskGraphError("existing project standards rules require a standards index")
        standards["index_fingerprint"] = None
    policies = standards["protected_paths"]
    if not isinstance(policies, list):
        raise TaskGraphError("standards.protected_paths must be an array")
    for position, policy in enumerate(policies):
        _object(policy, f"standards.protected_paths[{position}]",
                {"path", "rule_id", "allowed_paths", "direct_edit"}, {"path", "rule_id", "allowed_paths"})
        policy.setdefault("direct_edit", "forbidden_without_exception")

    graph = {key: copy.deepcopy(source[key]) for key in
             ("request_id", "capacity", "requirements_fingerprint") if key in source}
    if "requirements_fingerprint" in graph and (
            not isinstance(graph["requirements_fingerprint"], str)
            or not SHA256_RE.fullmatch(graph["requirements_fingerprint"])):
        raise TaskGraphError("requirements_fingerprint must be lowercase SHA-256")
    for field in ("approved_gates", "active_paths", "active_semantic_locks"):
        graph[field] = copy.deepcopy(_strings(source.get(field, []), field))
    graph["standards_contract"] = standards
    raw_tasks = source["tasks"]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise TaskGraphError("init tasks must be a non-empty array")
    tasks = []
    for position, raw_task in enumerate(raw_tasks):
        label = f"tasks[{position}]"
        _object(raw_task, label, TASK_FIELDS, {"id", "task_type", "gates", "owned_paths"})
        task = copy.deepcopy(raw_task)
        for field in ("id", "task_type", "role", "surface_kind", "design_mode"):
            if field in task:
                _text(task[field], f"{label}.{field}")
        selection = _strings(task.pop("selected_standards", []), f"{label}.selected_standards")
        if task["task_type"] == "writer":
            # 合同内容与适用规则都是 PM 决定；初始化只拒绝缺失，绝不生成替代需求。
            for field in ("goal", "role", "surface_kind"):
                _text(task.get(field), f"{label}.{field}")
            for field in ("input_contracts", "output_contracts", "acceptance_evidence"):
                _strings(task.get(field), f"{label}.{field}", nonempty=True)
            _verification(task.get("verification_commands"), f"{label}.verification_commands")
        task.update(request_id=request_id, state="DECLARED")
        for field in ("depends_on", "blocks", "semantic_locks"):
            task.setdefault(field, [])
        if "role" in task:
            task["qa_scope"] = "request"
        audit = _strings(task.get("audit_surfaces", []), f"{label}.audit_surfaces")
        if task["task_type"] == "writer" and "standards-conformance" not in audit:
            audit.append("standards-conformance")
        if "role" in task or audit:
            task["audit_surfaces"] = audit
        if task["task_type"] == "writer" or selection:
            # 选择一条叶引用即显式采用该叶中 PM 已列明的规则集；不按文件后缀、
            # 技术栈或角色选择叶子，也不把 required_* 自动补进选择集合。
            if task["task_type"] == "writer":
                domains = ("design",) if task["surface_kind"] == "design_ui" else ("engineering", "design") if task["surface_kind"] == "production_ui" else ("engineering",)
                for domain in domains:
                    if not any(builtin_source_path(path) is not None and source_domain(path, standards["root"]) == domain for path in selection):
                        raise TaskGraphError(f"{label} new init requires a selected builtin {domain} standards source")
            documents = [{"path": standards["index_path"], "rule_ids": []}] if standards["index_fingerprint"] is not None else []
            for path in selection:
                if path not in indexed_leaves:
                    raise TaskGraphError(f"{label} selects a leaf absent from standards: {path}")
                documents.append({"path": path, "rule_ids": copy.deepcopy(indexed_leaves[path]["rule_ids"])})
            for document in documents:
                document.update(mode="full", reason="PM 明确选择本任务完整读取并遵守此文档",
                                sections_or_queries=[], applies_to=copy.deepcopy(task["owned_paths"]),
                                content_fingerprint=fingerprint(document["path"]))
            task["controlled_document_access"] = {"adapter": "project.yaml", "documents": documents}
        tasks.append(task)
    graph["tasks"] = tasks
    if any(task.get("surface_kind") in {"production_ui", "design_ui"} for task in tasks):
        # 原校验器已把原型根固定为 standards.root/prototype；此处不引入新边界。
        graph["ui_contract"] = {"prototype_paths": [f"{standards['root']}/prototype"]}

    validate("validate", graph)
    validate("ready", graph)  # 同时复用容量、批准与活动锁的现有输入校验；不写 READY 状态。
    for relative, expected in sources.items():
        if records.file_digest(root, relative) != expected:
            raise TaskGraphError(f"init source fingerprint changed: {relative}")
    if standards["index_fingerprint"] is None:
        try:
            (root / standards["index_path"]).lstat()
        except FileNotFoundError:
            pass
        else:
            raise TaskGraphError("init absent standards index changed before publication")
    if input_path is not None and records.read_record(input_path) != input_body:
        raise TaskGraphError("init decision record changed before publication")
    body = (json.dumps(graph, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    records.publish(output, body, "missing")
    return {"initialized": True, "path": str(output.absolute()), "sha256": records.digest(body),
            "task_count": len(tasks)}
