"""新项目 UI Foundation 的两个固定 QA 检查点，不提供通用阶段引擎。

图仍保存一个 QA 节点与一个原生 Reviewer；阶段 PASS 只解除功能 Writer 的基础
设施前置条件。所有证据通过既有 records 读取与 CAS 发布，模块不派发、不批准。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

# 脚本入口与包入口统一使用仓库已有 lib 命名空间，避免依赖调用者 cwd。
if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.task_graph import TaskGraphError
from lib.task_intent import CLAIM_FIELDS

SHA_FIELDS = {"task_pack", "handoff"}
REQUEST_RECEIPT_FIELDS = SHA_FIELDS | {"agent_ref", "scope_fingerprint"}
FROZEN_SCOPE_FIELDS = {"qa_scope_ref", "qa_scope_fingerprint"}
ISOLATED_RECEIPT_FIELDS = REQUEST_RECEIPT_FIELDS | {"writer_contract_fingerprint"}


def project_qa_read_only(task: dict) -> None:
    """将已验证 QA 的临时副本投影为只读候选，用于复用既有 ready 门；调用者保留原记录。"""
    task["task_type"] = "read_only"
    # QA 身份、阶段和返工证据仅在原节点上有语义。两种就绪入口必须作相同
    # 投影，防止失效后保留的原 QA 证据在兄弟候选检查时被看成错误的只读输入。
    for field in ("foundation_task_id", "foundation_receipt", "request_receipt", "qa_projection",
                  "qa_projection_baselines", "qa_review_revision", "qa_scope_ref", "qa_scope_fingerprint",
                  "qa_result_scope", "qa_failed_pack_fingerprint"):
        task.pop(field, None)


def closure(payload: dict, task_id: str) -> set[str]:
    """只沿真实依赖边取 Foundation 闭包；不把同请求的后续功能纳入阶段范围。"""
    indexed = {task["id"]: task for task in payload["tasks"]}
    found, pending = set(), [task_id]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(indexed[current]["depends_on"])
    return found


def validate_contract(payload: dict, *, handoff: bool = False) -> None:
    """可选引用只能声明一次；功能依赖 Foundation，自身绝不能依赖 QA。"""
    indexed = {task["id"]: task for task in payload["tasks"]}
    for qa in indexed.values():
        if "request_receipt" in qa:
            receipt = qa["request_receipt"]
            accepted_shapes = [REQUEST_RECEIPT_FIELDS, ISOLATED_RECEIPT_FIELDS]
            if "foundation_task_id" in qa:
                # 旧阶段图只保存文件引用，可查看但不能由此证明当前功能合同仍相同。
                accepted_shapes.append(SHA_FIELDS)
            if (qa.get("task_type") != "qa" or qa.get("workflow_level") != "Full"
                    or not isinstance(receipt, dict) or set(receipt) not in accepted_shapes):
                raise TaskGraphError("request_receipt requires the corresponding Full QA acceptance contract")
            for field in SHA_FIELDS:
                _reference(receipt[field])
            if "scope_fingerprint" in receipt and (
                    not _sha(receipt["scope_fingerprint"]) or not qa.get("agent_ref")
                    or receipt["agent_ref"] != qa["agent_ref"]):
                raise TaskGraphError("request_receipt requires the reviewed scope and original Reviewer")
            if "writer_contract_fingerprint" in receipt and not _sha(receipt["writer_contract_fingerprint"]):
                raise TaskGraphError("isolated request receipt requires a Writer contract SHA256")
        if "qa_projection_baselines" in qa:
            baselines = qa["qa_projection_baselines"]
            if (not is_full_reviewer(qa) or "qa_scope_ref" not in qa or not isinstance(baselines, dict)
                    or not baselines or any(not isinstance(path, str) or not _sha(value)
                                           for path, value in baselines.items())):
                raise TaskGraphError("PM document baselines require a frozen request and SHA256")
        if "qa_projection" in qa:
            from lib.qa_projection import validate_shape
            validate_shape(qa)
        if FROZEN_SCOPE_FIELDS & qa.keys():
            integrations = payload.get("worktree_integrations", {})
            if (not is_full_reviewer(qa) or "qa_scope_ref" not in qa
                    or isinstance(integrations, dict) and qa["request_id"] in integrations):
                raise TaskGraphError("qa_scope_ref belongs only to non-isolated Full request QA")
            _frozen_scope_paths(qa["qa_scope_ref"])
            if "qa_scope_fingerprint" in qa and not _sha(qa["qa_scope_fingerprint"]):
                raise TaskGraphError("qa_scope_fingerprint must be a SHA256 of the frozen Writer inputs")
        if "qa_review_revision" in qa and (not is_full_reviewer(qa)
                or type(qa["qa_review_revision"]) is not int or qa["qa_review_revision"] < 1):
            raise TaskGraphError("qa_review_revision belongs only to Full QA and must be positive")
        if "foundation_receipt" in qa and "foundation_task_id" not in qa:
            raise TaskGraphError("foundation_receipt requires foundation_task_id")
        if "foundation_task_id" not in qa:
            continue
        reference = qa["foundation_task_id"]
        if (qa.get("task_type") != "qa" or qa.get("workflow_level") != "Full"
                or not isinstance(reference, str) or not reference.strip()):
            raise TaskGraphError("foundation_task_id belongs only to a Full QA task")
        if handoff:
            continue
        foundation = indexed.get(reference)
        if (foundation is None or foundation.get("task_type") != "writer"
                or foundation.get("workflow_level") != "Full"
                or foundation.get("surface_kind") != "production_ui"
                or foundation["request_id"] != qa["request_id"]):
            raise TaskGraphError("foundation_task_id must identify the same request's Full production_ui writer")
        foundation_ids = closure(payload, reference)
        if qa["id"] in foundation_ids:
            raise TaskGraphError("Foundation must not depend on its QA")
        # 阶段审查只有基础设施闭包；同一节点的最终全请求 barrier 由 qa-ready 计算。
        # 因此 QA 不可声明后续功能依赖，否则又会把 Foundation 审查锁死在功能后面。
        if not set(qa["depends_on"]) <= foundation_ids:
            raise TaskGraphError("Foundation QA dependencies must stay inside the Foundation closure")
        for task in indexed.values():
            if (task["request_id"] != qa["request_id"] or task["task_type"] != "writer"
                    or task.get("surface_kind") != "production_ui" or task["id"] in foundation_ids):
                continue
            dependencies = closure(payload, task["id"])
            if reference not in dependencies or qa["id"] in dependencies:
                raise TaskGraphError("production UI features must depend on Foundation, never on the QA node")
        receipt = qa.get("foundation_receipt")
        if receipt is not None:
            fields = {"checkpoint_fingerprint", "agent_ref", "task_pack", "handoff"}
            if not isinstance(receipt, dict) or set(receipt) != fields:
                raise TaskGraphError("foundation_receipt has missing or unsupported fields")
            if receipt["agent_ref"] != qa.get("agent_ref"):
                raise TaskGraphError("foundation_receipt must retain the original Reviewer")
            if not _sha(receipt["checkpoint_fingerprint"]):
                raise TaskGraphError("foundation_receipt requires a checkpoint SHA256")
            for field in SHA_FIELDS:
                _reference(receipt[field])


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _reference(value: Any) -> None:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not Path(value["path"]).is_absolute()
            or str(Path(value["path"])) != value["path"] or ".." in Path(value["path"]).parts
            or not _sha(value["sha256"])):
        raise TaskGraphError("QA evidence requires a normalized absolute path and byte SHA256")


def is_full_reviewer(task: dict) -> bool:
    return task.get("task_type") == "qa" and task.get("workflow_level") == "Full"


def is_ordinary_reviewer(task: dict) -> bool:
    return is_full_reviewer(task) and "foundation_task_id" not in task


def request_writers(payload: dict, qa: dict) -> list[dict]:
    from lib.task_graph import request_closure
    from lib.task_graph_cli import _tasks
    ids = request_closure(_tasks(payload), qa["request_id"])
    return sorted((task for task in payload["tasks"] if task["id"] in ids and task["task_type"] == "writer"),
                  key=lambda task: task["id"])


def request_inputs(payload: dict, qa: dict, writers: list[dict]) -> dict:
    """只保留已审 Writer 的输入、输出、构建状态及实际采用的读取约定。"""
    from lib.task_graph_records import _document_contract
    contracts = []
    for task in writers:
        # 下游反向边、锁、宿主身份及交接建议只调度或记账。其他请求借用本 Writer
        # 时可新增 blocks；这不代表本次审查的代码、证据或合同发生改变。
        omitted = CLAIM_FIELDS | {"blocks", "semantic_locks", "agent_ref", "agent_retired",
                                  "handoff_assessment", "controlled_document_access"}
        contract = {key: value for key, value in task.items() if key not in omitted}
        access = _document_contract(task)
        if access is not None:
            access["documents"] = [doc for doc in access["documents"] if doc["mode"] != "skip"]
        contract["controlled_document_access"] = access
        contracts.append(contract)
    # 领取前的 CAS 基线和原待派状态只证明是哪一次占用。冻结→领取→绑定
    # 应保留同一受审范围和轮次；独立回执仍须校验实际 Reviewer 身份及包字节。
    # 保留 task_revision、revision_source、实际合同和方案/批准，避免接受旧范围。
    reviewer_metadata = CLAIM_FIELDS | {
        "state", "agent_ref", "agent_retired", "blocks", "semantic_locks", "handoff_assessment",
        "request_receipt", "qa_review_revision", "qa_scope_fingerprint", "qa_projection",
        "revision_ack", "revision_result", "qa_result_scope", "qa_failed_pack_fingerprint"}
    reviewer = {key: value for key, value in qa.items() if key not in reviewer_metadata}
    return {"writers": contracts, "reviewer": reviewer,
            "integration": payload.get("worktree_integrations", {}).get(qa["request_id"])}


def _authority_digest(root: Path, relative: str) -> str:
    """项目文档在实际受审树取样；内置规范按已绑定插件或固定核心的物理根取样。"""
    from lib import task_graph_records as records
    from lib.standard_paths import builtin_source_path
    from lib.task_sources import PLUGIN_ENV
    builtin = builtin_source_path(relative)
    if builtin is not None and PLUGIN_ENV not in os.environ:
        return records.document_digest(Path(__file__).resolve().parents[1], builtin)
    return records.document_digest(root, relative)


def request_fingerprints(payload: dict, qa: dict, writers: list[dict], pack: dict, *,
                         root: Path | None = None, require_current: bool = False) -> tuple[str, str]:
    """绑定图中可归因的证据、实际文件与权威，只在正式接收时要求全部权威仍有效。"""
    from lib.task_sources import project_root

    selected_root = project_root(root)
    projection = request_inputs(payload, qa, writers)
    integration = projection["integration"]
    # 隔离请求审查实际集成候选；跨请求已交付的 Writer 可能已清理旧目录，其
    # 当前内容应从本候选（普通请求为项目根）读取。旧修订仍保存在 Writer 合同里。
    candidate_root = selected_root
    changed_paths = _frozen_scope_paths(qa["qa_scope_ref"]) if "qa_scope_ref" in qa else ()
    reviewed_content = {}
    if qa.get("qa_projection"):
        # 只有已接收的最终回执可使用精确的验收后投影。先验证变化，再还原受审文件摘要。
        from lib.qa_projection import verify_projection
        reviewed_content = verify_projection(payload, qa, selected_root)
    if require_current and qa.get("qa_projection_baselines"):
        from lib.qa_projection import capture_baselines
        pending = [path for path in qa["qa_projection_baselines"] if path not in reviewed_content]
        if pending:
            captured = capture_baselines(payload, qa, selected_root, pending)
            if any(qa["qa_projection_baselines"][path] != value for path, value in captured.items()):
                raise TaskGraphError("PM projection baseline changed after scope freeze")
    if integration:
        from lib.delivery.worktree_cli import clean, head, linked, scope
        candidate_root = linked(selected_root, integration["root"])
        if require_current:
            clean(candidate_root)
        projection["candidate_head"] = integration["head_revision"] if reviewed_content else head(candidate_root)
        if require_current and projection["candidate_head"] != integration["head_revision"]:
            raise TaskGraphError("integration HEAD changed after verification")
        if integration["head_revision"]:
            changed_paths = scope(selected_root, integration["target_base"], integration["head_revision"])["changed_paths"]
    # owned_paths 是保护及授权边界，经常包含整目录。仅对冻结范围列出的文件取样，
    # 不读同目录的缓存、被忽略文件或与本候选无关的其他写入。
    if not integration and "foundation_task_id" in qa:
        # 既有分阶段图没有普通 QA 的冻结路径；最终审查须绑定每个被审 Writer
        # 的实际交付内容。沿用阶段对目录所有权的遍历约定，保留文件删除与模式。
        files = set()
        for writer in writers:
            for relative in writer["owned_paths"]:
                path = candidate_root / relative
                if path.is_dir() and not path.is_symlink():
                    for child in path.rglob("*"):
                        if child.is_symlink() or not child.is_dir():
                            files.add(child.relative_to(candidate_root).as_posix())
                else:
                    files.add(relative)
        changed_paths = sorted(files)
    content = {relative: _scoped_content(candidate_root, relative) for relative in changed_paths}
    for relative, previous in reviewed_content.items():
        if relative in content:
            # mode 从当前实物取得；单树普通文档及 Git 对象另在投影校验中限制为无执行位。
            if content[relative] != [previous[1], 0]:
                raise TaskGraphError("projected document changed during QA verification")
            content[relative] = [previous[0], 0]
    contract = pack["standards_contract"]
    authorities = {contract["index_path"]: {contract["index_fingerprint"]}}
    documents = [doc for task in [qa, *writers]
                 for doc in task.get("controlled_document_access", {}).get("documents", []) if doc["mode"] != "skip"]
    design_refs = [ref for task in writers for ref in task.get("ui_change", {}).get("design_authority_refs", [])]
    for source in [*contract["leaves"], *documents, *(ref for ref in design_refs if ref["kind"] != "prototype_contract")]:
        authorities.setdefault(source["path"], set()).add(source["content_fingerprint"])
    actual_authorities = {}
    for relative, expected in sorted(authorities.items()):
        try:
            actual = _authority_digest(candidate_root, relative)
        except FileNotFoundError:
            actual = None
        if relative in reviewed_content:
            # 同一个主题也可能是 Writer、QA 或设计读取的权威。投影的合法差异已单独
            # 验证，各角色复算原合同都须读取同一个前像；现有实物仍须匹配登记的后像。
            before_sha, after_sha = reviewed_content[relative]
            if actual != after_sha:
                raise TaskGraphError("projected authority changed during QA verification")
            actual = before_sha
        if require_current and expected != {actual}:
            raise TaskGraphError(f"request QA authority is stale: {relative}")
        actual_authorities[relative] = actual
    if pack.get("solution_approval_sources"):
        projection["solution_approval_sources"] = pack["solution_approval_sources"]
    if integration and require_current:
        projection["prototype_authority"] = _isolated_prototypes(payload, qa, writers, selected_root)
    else:
        projection["prototype_authority"] = _prototype_authority(candidate_root, writers, pack, require_current)
    # 宿主状态、退役及反向边独立于已审事实。Revision 则让一次明确返工即使
    # 恰好产出完全相同的文件和证据也必须重新交接，不能接收上一轮旧包。
    projection.update(content=content, authorities=actual_authorities,
                      standards=contract, requirements=pack.get("requirements_fingerprint"),
                      approved_gates=pack["approved_gates"], ui_contract=pack.get("ui_contract"))
    # Scope证书不使用Reviewer轮次。只因Reviewer中止而续审时，同一实际候选范围
    # 仍可信；任务包摘要另含轮次，保证之前已发出的包不能重放。
    scope_fingerprint = _json_digest(projection)
    projection["revision"] = qa.get("qa_review_revision", 0)
    return _json_digest(projection), scope_fingerprint


def _json_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _frozen_scope_paths(scope_ref: Any) -> tuple[str, ...]:
    # 冻结图和 Reviewer 回执使用相同仓库/路径合同；只有图内 PM 冻结入口能写权威。
    from lib.delivery.qa_handoff_cli import _validate_scope
    if not isinstance(scope_ref, dict) or set(scope_ref) != {"repositories"}:
        raise TaskGraphError("qa_scope_ref requires only its repositories array")
    return _validate_scope({"scope_ref": scope_ref})


def verify_frozen_scope(qa: dict, writers: list[dict], scope_fingerprint: str, *, freezing: bool) -> None:
    from lib.task_graph_cli import _is_within
    scope_ref = qa.get("qa_scope_ref")
    if scope_ref is None or (not freezing and "qa_scope_fingerprint" not in qa):
        raise TaskGraphError("ordinary request QA requires a PM-frozen qa_scope_ref")
    if not freezing and qa["qa_scope_fingerprint"] != scope_fingerprint:
        raise TaskGraphError("PM-frozen QA scope is stale; freeze the current Writer scope before review")
    owned = [relative for task in writers for relative in task["owned_paths"]]
    if any(not any(_is_within(path, boundary) for boundary in owned) for path in _frozen_scope_paths(scope_ref)):
        raise TaskGraphError("frozen QA changed path is outside the reviewed Writer closure")


def _isolated_prototypes(payload: dict, qa: dict, writers: list[dict], root: Path) -> dict:
    """按相同 Writer/QA 规则核对已登记工作树、提交祖先和页面依赖，再采用实际通过的摘要。"""
    from lib.delivery.worktree_cli import linked
    from lib.visual_authority import check_visual_page
    actual = {}
    for writer in writers:
        change = writer.get("ui_change", {})
        refs = [ref for ref in change.get("design_authority_refs", []) if ref["kind"] == "prototype_contract"]
        if not refs:
            continue
        if change.get("prototype_policy") != "required":
            # UI-Conformance 可重用已冻结的既有页面，没有本轮设计 Writer；
            # 仍从本请求的真实集成候选复核该页及依赖，不能额外要求新的视觉批准。
            candidate = linked(root, payload["worktree_integrations"][qa["request_id"]]["root"])
            actual.update(_prototype_authority(candidate, [writer], payload, True))
            continue
        for ref in refs:
            page = {"path": ref["path"], "dependency_fingerprint": ref["content_fingerprint"]}
            check_visual_page(payload, writer, page, root, stage="qa", review_request=qa["request_id"])
            actual[ref["path"]] = ref["content_fingerprint"]
    return actual


def _prototype_authority(root: Path, writers: list[dict], pack: dict, require_current: bool) -> dict:
    """复用具体原型页闭包的公开指纹，采用页及其实际依赖，不把 HTML 原字节当批准指纹。"""
    from lib.documents.validate_prototype_workspace import capture_selected_pages
    selected = {}
    for writer in writers:
        for reference in writer.get("ui_change", {}).get("design_authority_refs", []):
            if reference["kind"] != "prototype_contract":
                continue
            relative = Path(reference["path"])
            prototype, = pack["ui_contract"]["prototype_paths"]
            if relative.parent.as_posix() != prototype:
                raise TaskGraphError("request QA prototype authority must be a concrete page in the approved root")
            adapter = writer["controlled_document_access"]["adapter"]
            selected.setdefault((prototype, adapter), {}).setdefault(relative.name, set()).add(reference["content_fingerprint"])
    actual = {}
    for (prototype, adapter), expected in selected.items():
        available = [page for page in expected if (root / prototype / page).exists()]
        capture = capture_selected_pages(root, prototype, pages=available, adapter=adapter)["pages"] if available else []
        fingerprints = {Path(page["path"]).name: page["dependency_fingerprint"] for page in capture}
        for page, values in expected.items():
            fingerprint = fingerprints.get(page)
            if require_current and values != {fingerprint}:
                raise TaskGraphError(f"request QA prototype dependency fingerprint is stale: {page}")
            actual[f"{prototype}/{page}"] = fingerprint
    return actual


def _scoped_content(root: Path, relative: str) -> list | None:
    """读取明确的文件或删除标识，拒绝链接和特殊文件，不把目录展开成额外范围。"""
    from lib.task_graph_records import file_digest
    target = root / relative
    if root.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent.is_relative_to(root)):
        raise TaskGraphError("request QA content root and parents must be physical directories")
    if target.is_symlink():
        raise TaskGraphError("request QA content must not use symlinks")
    # Git 的文件→目录替换包含删除及新增记录；新增子文件会各自出现在精确范围。
    if target.is_dir() or not target.exists():
        return None
    # 文件摘要流式支持二进制和大文件。可执行位也影响候选行为，需独立保留。
    return [file_digest(root, relative), target.lstat().st_mode & 0o111]


def fingerprint(payload: dict, qa: dict, *, root: Path | None = None) -> str:
    """冻结闭包自身合同、构建、内容与采用权威，不绑定整图或集成全局 HEAD。

    内容读取仅遍历闭包 owned_paths，拒绝链接与特殊文件；规则内容沿用既有安全
    读取器。无关 feature 合同、状态及集成 HEAD 均不进入摘要，正常开发不会撤销
    已通过的基础设施；Foundation 返工、证据、采用规范和批准变化会改变摘要。
    """
    from lib import task_graph_records as records
    from lib.task_sources import project_root
    selected_root = project_root(root)
    ids = closure(payload, qa["foundation_task_id"])
    tasks = [task for task in payload["tasks"] if task["id"] in ids]
    sources, content, contracts = {}, {}, []
    gates = {gate for task in tasks for gate in task["gates"]}
    reviewed = {}
    if qa.get("qa_projection"):
        from lib.qa_projection import verify_projection
        reviewed = verify_projection(payload, qa, selected_root)
    integration = payload.get("worktree_integrations", {}).get(qa["request_id"])
    projected_root = Path(integration["root"]) if integration else selected_root

    def original(relative: str, content_root: Path, actual: str) -> str:
        if relative not in reviewed:
            return actual
        previous, projected = reviewed[relative]
        if content_root == projected_root:
            if actual != projected:
                raise TaskGraphError("Foundation projected document changed during verification")
            return previous
        # 尚在工作的隔离 Writer 必须保留自己的原字节；其它工作目录不能套用此替代。
        return actual

    # 页面授权的指纹覆盖同一页的依赖，不把 HTML 单文件的哈希冒充视觉批准。
    # 主树和组合候选都按同一种页合同核验，防止组合阶段换掉 CSS 后继续放行。
    prototypes = (_isolated_prototypes(payload, qa, tasks, selected_root) if integration
                  else _prototype_authority(selected_root, tasks, payload, True))
    # Foundation 和最终审查采用同一领取边界。阶段合同继续绑定 Writer 的修订、
    # 交付及原有身份，不让领取前状态、领取令牌或新增下游改变已审实现。
    metadata = CLAIM_FIELDS | {"blocks", "agent_retired", "handoff_assessment"}
    for task in sorted(tasks, key=lambda item: item["id"]):
        contracts.append({key: value for key, value in task.items() if key not in metadata})
        execution_root = Path(task.get("execution_workspace", {}).get("root", selected_root))
        content_roots = {"writer": execution_root}
        integration = payload.get("worktree_integrations", {}).get(task["request_id"])
        if integration:
            # 集成 HEAD 会随正常 feature 变化；只绑定候选中 Foundation 自己的内容，
            # 既检测错误组合/阶段包后改动，又不把无关提交误当成 Foundation 返工。
            content_roots["integration"] = Path(integration["root"])
        for source, content_root in content_roots.items():
            if content_root.is_symlink() or not content_root.is_dir():
                raise TaskGraphError("Foundation content root must be an existing physical directory")
            for relative in task["owned_paths"]:
                target = content_root / relative
                if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != content_root and content_root in parent.parents):
                    raise TaskGraphError("Foundation content must not use symlinks")
                if target.is_dir():
                    paths = sorted(target.rglob("*"))
                else:
                    paths = [target]
                for path in paths:
                    if path.is_symlink():
                        raise TaskGraphError("Foundation content must not use symlinks")
                    if path.is_dir():
                        continue
                    name = path.relative_to(content_root).as_posix()
                    content[f"{source}:{task['id']}:{name}"] = original(name, content_root, records.file_digest(content_root, name))
        for doc in task.get("controlled_document_access", {}).get("documents", []):
            if doc.get("mode") == "skip":
                continue
            actual = original(doc["path"], projected_root, _authority_digest(projected_root, doc["path"]))
            if actual != doc["content_fingerprint"]:
                raise TaskGraphError("Foundation controlled document fingerprint is stale: " + doc["path"])
            sources[doc["path"]] = actual
        for ref in task.get("ui_change", {}).get("design_authority_refs", []):
            if ref["kind"] == "prototype_contract":
                actual = prototypes[ref["path"]]
            else:
                actual = original(ref["path"], projected_root, _authority_digest(projected_root, ref["path"]))
            if actual != ref["content_fingerprint"]:
                raise TaskGraphError("Foundation design authority fingerprint is stale: " + ref["path"])
            sources[ref["path"]] = actual
    standard = copy.deepcopy(payload["standards_contract"])
    selected_rules = {rule for task in tasks for document in task.get("controlled_document_access", {}).get("documents", [])
                      for rule in document.get("rule_ids", [])}
    standard["leaves"] = [leaf for leaf in standard["leaves"] if leaf["path"] in sources]
    for leaf in standard["leaves"]:
        # 同一内置源可供后续feature采用更多规则；仅新采用的规则不改变Foundation
        # 已审合同，Foundation自己的读取rule_ids变化则仍通过tasks投影使回执失效。
        leaf["rule_ids"] = [rule for rule in leaf["rule_ids"] if rule in selected_rules]
    from lib.task_graph_cli import _paths_overlap
    owned = [path for task in tasks for path in task["owned_paths"]]
    standard["protected_paths"] = [policy for policy in standard["protected_paths"]
                                   if any(_paths_overlap(path, policy["path"]) for path in owned)]
    rules = {rule for leaf in standard["leaves"] for rule in leaf["rule_ids"]}
    for domain in ("engineering", "design"):
        key = f"required_{domain}_rule_ids"
        standard[key] = [rule for rule in standard[key] if rule in rules]
    projection = {"tasks": contracts, "content": content, "sources": sources, "standards": standard,
                  "requirements_fingerprint": payload.get("requirements_fingerprint"),
                  "approved_gates": sorted(set(payload.get("approved_gates", [])) & gates),
                  "ui_contract": payload.get("ui_contract")}
    sources = {gate: ref for gate, ref in payload.get("solution_approval_sources", {}).items() if gate in gates}
    if sources:
        projection["solution_approval_sources"] = sources
    return hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def valid_receipt(payload: dict, qa: dict, *, root: Path | None = None) -> bool:
    """旧或失效证据仅表示阶段未通过；不能因旧 PASS 而解除功能前置条件。"""
    from lib import task_graph_records as records
    receipt = qa.get("foundation_receipt")
    if not receipt:
        return False
    try:
        integration = payload.get("worktree_integrations", {}).get(qa["request_id"])
        if integration and qa.get("state") == "QA_PASSED" and qa.get("request_receipt"):
            try:
                Path(integration["root"]).lstat()
            except FileNotFoundError:
                # 已交付且撤除工作树时，原最终包同时携带当时有效的阶段回执。
                # 最终历史分支独立查真实合并、Writer 合同及两套回执，不再读取已清理目录。
                return current_request_receipt(payload, qa, root=root)
        return (receipt["agent_ref"] == qa.get("agent_ref")
                and receipt["checkpoint_fingerprint"] == fingerprint(payload, qa, root=root)
                and all(records.digest(records.read_record(Path(receipt[key]["path"]))) == receipt[key]["sha256"]
                        for key in SHA_FIELDS))
    except (OSError, ValueError, KeyError):
        return False


def checkpoint(payload: dict, qa: dict, *, root: Path | None = None) -> dict:
    """只从当前权威图推导两种固定审查范围，调用者不能自报或缩小 writer IDs。"""
    from lib.task_graph import request_closure
    from lib.task_graph_cli import _tasks
    foundation = qa.get("foundation_task_id")
    stage = bool(foundation and not valid_receipt(payload, qa, root=root))
    ids = closure(payload, foundation) if stage else request_closure(_tasks(payload), qa["request_id"])
    return {"kind": "foundation" if stage else "request", "writer_ids": sorted(
        task["id"] for task in payload["tasks"] if task["id"] in ids and task["task_type"] == "writer")}


def _evidence_bytes(operation: dict) -> dict[str, bytes]:
    """按正式 QA 回执的独立文件及原字节指纹读取，PASS 和定向返工使用同一边界。"""
    from lib import task_graph_records as records
    bodies = {}
    for field in SHA_FIELDS:
        _reference(operation[field])
        bodies[field] = records.read_record(Path(operation[field]["path"]))
        if records.digest(bodies[field]) != operation[field]["sha256"]:
            raise TaskGraphError("QA checkpoint evidence fingerprint changed")
    return bodies


def _finding_matches_writer(payload: dict, pack: dict, finding: dict, writer: dict, path: str, changed: tuple) -> bool:
    if not finding["blocking"] or finding["owner_role"] != writer["role"]:
        return False
    # 现有回执允许源码、Git diff 或日志定位。兼容常见文件名、行列和 GitHub 行锚点；
    # 仅有日志时，如受审面内该角色只有一位 Writer，也能从已验证的原合同唯一定位。
    # 同角色多位 Writer 且没有路径依据时，不能靠 PM 的任意索引将别人的缺陷分过来。
    def refers_to(relative):
        pattern = (r"(?:(?:diff|file|path|source):)?" + re.escape(relative)
                   + r"(?::[0-9]+(?::[0-9]+|-[0-9]+)?|#L[0-9]+(?:-L[0-9]+)?)?")
        return any(re.fullmatch(pattern, ref) for ref in finding["evidence_refs"])
    located = {entry for entry in changed if refers_to(entry)}
    if located:
        return path in located
    owners = [task["id"] for task in payload["tasks"] if task["id"] in pack["qa_checkpoint"]["writer_ids"]
              and task["role"] == writer["role"]]
    return owners == [writer["id"]]


def return_writer_for_rework(payload: dict, writer: dict, value: Any, *, root: Path | None = None) -> None:
    """原 Writer 已构建交付后，仅允许当前独立 QA 正式 FAIL 中归属此路径的阻断项返工。"""
    from lib import task_graph_records as records
    from lib.task_graph_cli import task_pack_with_review_scope, _safe_relative_path, _is_within
    from lib.delivery.qa_handoff_cli import validate_qa_handoff
    from lib.delivery.native_handoff import decode_handoff_json
    base = SHA_FIELDS | {"reviewer_id", "affected_path"}
    if (not isinstance(value, dict) or set(value) not in (base | {"finding_index"}, base | {"rule_id"})
            or writer.get("workflow_level") != "Full" or writer.get("task_type") != "writer"
            or writer["state"] != "BUILD_VERIFIED" or not writer.get("revision_result")
            or not writer.get("agent_ref") or writer.get("agent_retired")):
        raise TaskGraphError("rework_from_qa requires the original non-retired revised Full Writer and QA evidence")
    qa = next((task for task in payload["tasks"] if task["id"] == value["reviewer_id"]), None)
    if (not qa or not is_full_reviewer(qa) or qa["request_id"] != writer["request_id"]
            or qa["state"] != "FAILED" or not qa.get("agent_ref") or qa.get("agent_retired")
            or not qa.get("qa_failed_pack_fingerprint") or qa.get("request_receipt")):
        raise TaskGraphError("writer rework requires the same request's current independent failed Reviewer")
    bodies = _evidence_bytes(value)
    pack = records.decode(bodies["task_pack"])
    if (not isinstance(pack, dict) or _json_digest(pack) != qa["qa_failed_pack_fingerprint"]
            or writer["id"] not in pack.get("qa_checkpoint", {}).get("writer_ids", [])):
        raise TaskGraphError("writer rework requires the exact original failed QA pack and reviewed Writer")
    _, current_scope = task_pack_with_review_scope(payload, qa["id"], root=root, require_current_qa=True)
    if current_scope != qa["qa_result_scope"]:
        raise TaskGraphError("failed QA no longer describes the current Writer scope")
    handoff = decode_handoff_json(bodies["handoff"])
    if not isinstance(handoff, dict):
        raise TaskGraphError("writer rework requires a structured independent QA handoff")
    validate_qa_handoff(handoff, bodies["task_pack"])
    if handoff["audit_result"] != "FAIL":
        raise TaskGraphError("writer rework requires the original independent FAIL evidence")
    if qa["request_id"] in payload.get("worktree_integrations", {}):
        _validate_integration(payload, qa, handoff, root=root)
    path = _safe_relative_path(value["affected_path"], "rework affected_path")
    changed_paths = _frozen_scope_paths(handoff["review_method"]["scope_ref"])
    if path not in changed_paths or not any(_is_within(path, owned) for owned in writer["owned_paths"]):
        raise TaskGraphError("writer rework path must belong to the actual reviewed scope and original Writer")
    if "finding_index" in value:
        findings = handoff.get("review_details", {}).get("findings", [])
        index = value["finding_index"]
        if (type(index) is not int or not 0 <= index < len(findings)
                or not _finding_matches_writer(payload, pack, findings[index], writer, path, changed_paths)):
            raise TaskGraphError("QA finding must identify a blocking issue for the original Writer role and path")
        issue = f"finding {index}"
    else:
        # 旧版正式 FAIL 可通过硬规则的定向失败证据成立，沿用其原 affected_paths；
        # 无实现路径的工具/能力故障需要 PM 协调，不能拿来重开任意已交付 Writer。
        rule = value["rule_id"]
        checks = handoff["standards_policy_coverage"]["rule_checks"]
        if not any(check["rule_id"] == rule and check["severity"] == "hard" and check["disposition"] == "fail"
                   and path in check["affected_paths"] for check in checks):
            raise TaskGraphError("writer rework requires an actual hard rule failure on its reviewed path")
        issue = f"rule {rule}"
    # 保留原实现身份、写范围、构建及 FAIL 证据。只增加返工修订号并返回待续派；
    # RUNNING 及新版确认仍分别走原依赖、路径锁、同 ID 投递和结果回执。
    previous = writer.pop("revision_result")
    writer["acceptance_evidence"].extend([
        f"第 {previous['revision']} 版构建依据：{previous['source']}",
        f"QA 返工依据：{value['handoff']['path']}@{value['handoff']['sha256']} {issue} ({path})"])
    writer.pop("revision_ack")
    writer["task_revision"] += 1
    writer["state"] = "DECLARED"


def accept(payload: dict, qa: dict, operation: Any, *, kind: str, root: Path | None = None) -> dict:
    """读取当前原字节包/结论，验证唯一 Reviewer 和范围，再产生受保护记录字段。"""
    from lib import task_graph_records as records
    from lib.task_graph_cli import export_task_pack, _execute
    from lib.delivery.qa_handoff_cli import validate_qa_handoff
    from lib.delivery.native_handoff import decode_handoff_json
    ordinary = is_ordinary_reviewer(qa)
    if (qa.get("task_type") != "qa" or qa.get("workflow_level") != "Full"
            or kind == "foundation" and ordinary or not qa.get("agent_ref")
            or qa.get("state") not in {"QA", "RUNNING"} or qa.get("agent_retired")):
        raise TaskGraphError("checkpoint acceptance requires the active original Full Reviewer")
    if not isinstance(operation, dict) or set(operation) != SHA_FIELDS:
        raise TaskGraphError("checkpoint acceptance requires task_pack and handoff byte references")
    bodies = _evidence_bytes(operation)
    pack = records.decode(bodies["task_pack"])
    current = export_task_pack(payload, qa["id"], root=root, require_current_qa=True)
    if pack != current or pack.get("qa_checkpoint", {}).get("kind") != kind:
        raise TaskGraphError("QA task pack differs from the current checkpoint")
    candidate = copy.deepcopy(payload)
    candidate["request_id"] = qa["request_id"]
    if not _execute("qa-ready", candidate, root=root)["qa_ready"]:
        raise TaskGraphError("QA checkpoint is not ready")
    handoff = decode_handoff_json(bodies["handoff"])
    if not isinstance(handoff, dict):
        raise TaskGraphError("QA checkpoint handoff must be an object")
    validate_qa_handoff(handoff, bodies["task_pack"])
    if handoff["audit_result"] != "PASS":
        raise TaskGraphError("QA checkpoint acceptance requires PASS")
    if kind == "request":
        isolated = qa["request_id"] in payload.get("worktree_integrations", {})
        receipt = {"scope_fingerprint": current["qa_checkpoint_fingerprint"],
                   "agent_ref": copy.deepcopy(qa["agent_ref"]), **copy.deepcopy(operation)}
        if isolated:
            _validate_integration(payload, qa, handoff, root=root)
            receipt["writer_contract_fingerprint"] = _writer_contract_fingerprint(payload, qa)
        elif (ordinary or "qa_scope_ref" in qa) and handoff["review_method"]["scope_ref"] != qa["qa_scope_ref"]:
            raise TaskGraphError("QA handoff does not match the complete PM-frozen scope_ref")
        return {"state": "QA_PASSED", "request_receipt": receipt}
    return {"state": "DECLARED", "foundation_receipt": {
        "checkpoint_fingerprint": fingerprint(payload, qa, root=root),
        "agent_ref": copy.deepcopy(qa["agent_ref"]), **copy.deepcopy(operation)}}


def _validate_integration(payload: dict, qa: dict, handoff: dict, *, root: Path | None = None) -> None:
    integration = payload["worktree_integrations"][qa["request_id"]]
    from lib.delivery.worktree_cli import scope
    from lib.task_sources import project_root
    current_scope = scope(project_root(root), integration["target_base"], integration["head_revision"])
    if handoff["review_method"]["scope_ref"]["repositories"] != [current_scope]:
        raise TaskGraphError("QA scope does not match the actual complete integration diff")


def _writer_contract_fingerprint(payload: dict, qa: dict) -> str:
    # 已交付后工作树可删除。独立冻结不依赖候选目录的合同与轮次，用于验证旧记录
    # 仍描述同一次交付；原 QA 包和真实 Git diff 另行按自己的原始依据验证。
    projection = request_inputs(payload, qa, request_writers(payload, qa))
    projection["revision"] = qa.get("qa_review_revision", 0)
    return _json_digest(projection)


def _historical_integration(payload: dict, qa: dict, handoff: dict, *, root: Path | None) -> bool:
    from lib.delivery.worktree_cli import ancestor, git, repository
    from lib.task_sources import project_root
    integration = payload["worktree_integrations"][qa["request_id"]]
    if qa["request_receipt"].get("writer_contract_fingerprint") != _writer_contract_fingerprint(payload, qa):
        return False
    repo = repository(project_root(root))
    # 只使用记录的本地分支完整引用，禁止把同名标签或别的仓库对象当已交付证据。
    target = git(repo, "show-ref", "--verify", "--hash", f"refs/heads/{integration['target_branch']}").decode().strip()
    ancestor(repo, qa.get("qa_projection", {}).get("head_revision", integration["head_revision"]), target)
    _validate_integration(payload, qa, handoff, root=repo)
    if qa.get("qa_projection"):
        from lib.qa_projection import verify_projection
        verify_projection(payload, qa, repo, delivered=True)
    return True


def current_request_receipt(payload: dict, qa: dict, *, root: Path | None = None) -> bool:
    """历史无绑定 PASS 只供查看；有回执也必须是同一 Reviewer、当前范围及原证据字节。"""
    from lib import task_graph_records as records
    from lib.delivery.native_handoff import decode_handoff_json
    from lib.delivery.qa_handoff_cli import validate_qa_handoff
    from lib.task_graph_cli import export_task_pack
    receipt = qa.get("request_receipt")
    if qa.get("state") != "QA_PASSED" or not receipt:
        return False
    try:
        bodies = {field: records.read_record(Path(receipt[field]["path"])) for field in SHA_FIELDS}
        if any(records.digest(body) != receipt[field]["sha256"] for field, body in bodies.items()):
            return False
        if not is_full_reviewer(qa) or "scope_fingerprint" not in receipt:
            return False
        pack = decode_handoff_json(bodies["task_pack"])
        writer_ids = [writer["id"] for writer in request_writers(payload, qa)]
        if (not isinstance(pack, dict) or not isinstance(pack.get("task"), dict)
                or pack.get("qa_checkpoint") != {"kind": "request", "writer_ids": writer_ids}
                or pack.get("qa_checkpoint_fingerprint") != receipt["scope_fingerprint"]
                or receipt["agent_ref"] != qa.get("agent_ref")
                or pack["task"].get("agent_ref") != qa.get("agent_ref")):
            return False
        # 目标分支清理后也须以当前图复核被审请求的批准。包级来源不要求历史图补造
        # 用户消息，但任何现有来源、需求或采用门发生变化都不能复活已交付的旧结论。
        writers = request_writers(payload, qa)
        gates = {gate for item in [qa, *writers] for gate in item["gates"]}
        if (not gates <= set(payload.get("approved_gates", []))
                or set(pack["approved_gates"]) != gates
                or pack.get("requirements_fingerprint") != payload.get("requirements_fingerprint")
                or pack.get("solution_approval_sources", {}) != {gate: value for gate, value in
                    payload.get("solution_approval_sources", {}).items() if gate in gates}):
            return False
        handoff = decode_handoff_json(bodies["handoff"])
        if not isinstance(handoff, dict) or handoff.get("audit_result") != "PASS":
            return False
        validate_qa_handoff(handoff, bodies["task_pack"])
        integration = payload.get("worktree_integrations", {}).get(qa["request_id"])
        if integration:
            try:
                Path(integration["root"]).lstat()
            except FileNotFoundError:
                # 只对已实际合并且路径确实已清理的历史证据启用此分支。活跃 QA
                # 仍走现有真实工作树、干净候选和完整 diff 检查。
                if "foundation_task_id" in qa:
                    stage = qa.get("foundation_receipt")
                    if not stage or stage != pack["task"].get("foundation_receipt") or any(
                            records.digest(records.read_record(Path(stage[key]["path"]))) != stage[key]["sha256"]
                            for key in SHA_FIELDS):
                        return False
                return _historical_integration(payload, qa, handoff, root=root)
        elif (is_ordinary_reviewer(qa) or "qa_scope_ref" in qa) and handoff["review_method"]["scope_ref"] != qa.get("qa_scope_ref"):
            return False
        if "foundation_task_id" in qa and not valid_receipt(payload, qa, root=root):
            return False
        current = export_task_pack(payload, qa["id"], root=root, require_current_qa=True)
        if receipt["scope_fingerprint"] != current["qa_checkpoint_fingerprint"]:
            return False
        return True
    except (OSError, ValueError, KeyError):
        return False


def validate_publication(target: Path, before: bytes | None, after: bytes, *, root: Path | None = None) -> None:
    """发布锁内重读新阶段回执，拒绝同一记录自毁证据和计算后的证据替换。"""
    from lib import task_graph_records as records
    if before is None:
        return
    try:
        previous, current = records.decode(before), records.decode(after)
    except (ValueError, UnicodeError):
        return
    # publish同时服务任意普通bytes/JSON；仅schema2图的新QA收据进入本守卫。
    # 非图数据必须沿用原发布语义，不能因碰巧含tasks键而被新机制误判。
    def graph_tasks(value: Any) -> list[dict] | None:
        if (not isinstance(value, dict) or value.get("schema_version") != 2
                or not isinstance(value.get("tasks"), list)
                or any(not isinstance(task, dict) or not isinstance(task.get("id"), str)
                       for task in value["tasks"])):
            return None
        return value["tasks"]
    previous_tasks, current_tasks = graph_tasks(previous), graph_tasks(current)
    if previous_tasks is None or current_tasks is None:
        return
    old = {task["id"]: task for task in previous_tasks}
    for task in current_tasks:
        request = task.get("request_receipt")
        previous_task = old.get(task["id"], {})
        if (is_full_reviewer(task) and task.get("state") == "QA_PASSED"
                and previous_task.get("state") != "QA_PASSED" and not request):
            raise TaskGraphError("new Full request QA_PASSED requires accept_request evidence")
        if task.get("qa_projection") and task["qa_projection"] != previous_task.get("qa_projection"):
            # 在 CAS 锁内再次校验原回执、文档输入/输出和其余受审合同，阻断校验后替换。
            if request != previous_task.get("request_receipt") or not current_request_receipt(current, task, root=root):
                raise TaskGraphError("QA projection or original receipt changed before publication")
        if request and request != previous_task.get("request_receipt"):
            for field in SHA_FIELDS:
                reference = request[field]
                path = Path(reference["path"])
                if path.samefile(target) or records.digest(records.read_record(path)) != reference["sha256"]:
                    raise TaskGraphError("new request QA receipt requires unchanged independent evidence")
            if is_full_reviewer(task):
                # 锁内按发布前权威图重走一次完整验收。只比较文件摘要无法发现读取与
                # 落盘之间代码／集成变化，也无法证明写入者确实提交了正式 PASS。
                accepted = accept(previous, previous_task, {field: request[field] for field in SHA_FIELDS},
                                  kind="request", root=root)
                if (task["state"] != accepted["state"] or request != accepted["request_receipt"]
                        or not current_request_receipt(current, task, root=root)):
                    raise TaskGraphError("request QA scope changed before receipt publication")
        receipt = task.get("foundation_receipt")
        if not receipt or receipt == old.get(task["id"], {}).get("foundation_receipt"):
            continue
        for field in SHA_FIELDS:
            reference = receipt[field]
            path = Path(reference["path"])
            if path.samefile(target) or records.digest(records.read_record(path)) != reference["sha256"]:
                raise TaskGraphError("new Foundation receipt requires unchanged independent evidence")
        if not valid_receipt(current, task, root=root):
            raise TaskGraphError("Foundation changed before receipt publication")
