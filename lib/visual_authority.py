"""沿用同一份静态页面合同，按设计交付、正式执行和 QA 的实际 Git 候选验证视觉批准。"""
from __future__ import annotations

from pathlib import Path

from lib.documents.validate_prototype_workspace import capture_selected_pages
from lib.task_graph import TaskGraphError
from lib.task_sources import project_root


def prototype_owners(graph: dict, writer: dict, path: Path) -> list[dict]:
    """只选同一请求、真实传递前置中负责该页的原型 Writer；规范维护不拥有页面权威。"""
    from lib.foundation_qa import closure
    ancestors = closure(graph, writer["id"]) - {writer["id"]}
    return [task for task in graph["tasks"] if task["id"] in ancestors
            and task["request_id"] == writer["request_id"] and task.get("role") == "xy-uiux"
            and task["task_type"] == "writer" and task.get("design_mode", "prototype") == "prototype"
            and any(path.is_relative_to(base) for base in task["owned_paths"])]


def _linked_revision(repo: Path, record: dict, base: str, tip: str, label: str) -> Path:
    """从项目根证明登记的 checkout、私有 Git 目录和确切提交；同字节的普通目录不能充当工作树。"""
    from lib.delivery.worktree_cli import ancestor, head, linked, object_id
    try:
        candidate = linked(repo, record["root"])
        if head(candidate) != object_id(repo, tip):
            raise TaskGraphError("HEAD differs from the recorded commit")
        ancestor(repo, object_id(repo, base), tip)
        return candidate
    except (OSError, ValueError) as exc:
        raise TaskGraphError(f"{label} worktree or recorded revision is unavailable: {exc}") from exc


def _check_capture(directory: Path, prototype: str, task: dict, page: dict, *, committed: bool) -> None:
    """比对静态验证器的传递依赖指纹；隔离交付还须证明这些原型资源包含于已登记提交。

    拿到页面捕获后，仅检查参与本页渲染的实际资源，运行中其他工作或图文件不会令
    相同原型失效。额外的文档导航由静态验证器核对，文档正文不是页面视觉依赖。
    """
    capture = capture_selected_pages(directory, prototype, pages=[Path(page["path"]).name],
                                     adapter=task["controlled_document_access"]["adapter"])
    actual, = capture["pages"]
    if actual["dependency_fingerprint"] != page["dependency_fingerprint"]:
        raise TaskGraphError(f"prototype dependency fingerprint is stale: {page['path']}")
    if committed:
        from lib.delivery.worktree_cli import git
        resources = [name for name in capture["files"] if Path(name).is_relative_to(prototype)]
        git(directory, "ls-files", "--error-unmatch", "--", *resources)
        git(directory, "diff", "--quiet", "--no-ext-diff", "--no-textconv", "HEAD", "--", *resources)


def _check_checkout(repo: Path, record: dict, base: str, tip: str, label: str,
                    prototype: str, task: dict, page: dict) -> None:
    """检查页面前后绑定同一提交。工作流的图文件 CAS 不会锁住用户的 Git checkout。"""
    from lib.delivery.worktree_cli import head
    directory = _linked_revision(repo, record, base, tip, label)
    try:
        _check_capture(directory, prototype, task, page, committed=True)
        if head(directory) != tip:
            raise TaskGraphError("HEAD changed during page verification")
    except (OSError, ValueError) as exc:
        raise TaskGraphError(f"{label} prototype evidence for {page['path']} is unavailable: {exc}") from exc


def check_visual_page(graph: dict, task: dict, page: dict, root: Path | None, *,
                      stage: str, review_request: str | None = None) -> None:
    """批准核对产出者，执行再核对采用者，QA 核对组合结果；主树只作为普通项目或 Git 身份锚点。"""
    from lib.delivery.worktree_cli import ancestor, git, head, local_objects_only, object_id
    prototype, = graph["ui_contract"]["prototype_paths"]
    prototype = prototype.rstrip("/")
    path = Path(page["path"])
    if path.parent != Path(prototype):
        raise TaskGraphError("visual approval requires a concrete page under the prototype root")
    if stage not in {"approval", "writer", "qa"}:
        raise TaskGraphError("unknown visual authority stage")
    repo = project_root(root)
    request = review_request or task["request_id"]
    integration = graph.get("worktree_integrations", {}).get(request)
    workspace = task.get("execution_workspace")
    historical = stage == "qa" and request != task["request_id"]
    if not integration and not workspace:
        _check_capture(repo, prototype, task, page, committed=False)
        return

    with local_objects_only():
        design_tips = []
        if historical:
            # 旧请求的 Writer 工作树可以已经回收。其提交须在本次共同基线中，
            # 页面及所有渲染依赖仍由本次 QA 实际消费的候选重新核对。
            if workspace:
                baseline = integration["target_base"] if integration else head(repo)
                ancestor(repo, object_id(repo, workspace["head_revision"]), baseline)
            if not integration:
                _check_capture(repo, prototype, task, page, committed=False)
                return
        else:
            owners = prototype_owners(graph, task, path)
            if not owners or not integration or not workspace:
                raise TaskGraphError("isolated visual authority requires bound prototype, Writer and integration worktrees")
            for owner in owners:
                design = owner["execution_workspace"]
                tip = design["head_revision"]
                if not tip:
                    raise TaskGraphError(f"prototype Writer {owner['id']} requires a recorded design checkpoint")
                _check_checkout(repo, design, design["base_revision"], tip, "design Writer", prototype, task, page)
                design_tips.append(tip)
            if stage != "approval":
                base = workspace["base_revision"]
                for tip in design_tips:
                    # merge-base 接受正常的合并提交，只要求正式基线包含设计交付检查点。
                    try:
                        ancestor(repo, tip, base)
                    except ValueError as exc:
                        raise TaskGraphError("production Writer base does not include its design checkpoint") from exc
                writer_tip = workspace["head_revision"] or base
                _check_checkout(repo, workspace, base, writer_tip, "production Writer", prototype, task, page)

        if stage == "writer":
            return
        integrated_tip = integration["head_revision"]
        if not integrated_tip:
            if stage == "qa":
                raise TaskGraphError("QA requires a recorded integration checkpoint for the approved prototype")
            return
        if stage == "approval" and any(git(repo, "merge-base", tip, integrated_tip).decode().strip() != tip
                                       for tip in design_tips):
            # 其他单元的历史组合可能已登记，且还不包含本次设计。此时批准的
            # 权威仍是设计 Writer，不把未开始的后续集成变成前置用户确认。
            return
        expected_head = integrated_tip
        reviewer = next((item for item in graph["tasks"] if item["task_type"] == "qa"
                         and item["request_id"] == request and item.get("qa_projection")), None)
        if reviewer:
            # 验收后的投影提交只可改获准文档，须由原投影合同独立验明方能读取。
            from lib.qa_projection import verify_projection
            verify_projection(graph, reviewer, repo)
            expected_head = reviewer["qa_projection"]["head_revision"]
        for tip in design_tips:
            ancestor(repo, tip, integrated_tip)
        if stage == "qa" and not historical:
            ancestor(repo, object_id(repo, workspace["head_revision"]), integrated_tip)
        _check_checkout(repo, integration, integration["target_base"], expected_head, "integration", prototype, task, page)
