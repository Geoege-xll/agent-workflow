"""核对最终 QA 后的 PM 文档投影。保留独立原字节证据，只允许精确、可重放的差异。"""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path, PurePosixPath
import re

from lib.documents.document_links import projection_link_errors
from lib.documents.markdown_headings import atx_section_bounds, iter_visible_lines
from lib.documents.plan_documents import SECTIONS, parse_plan
from lib.foundation_qa import _reference, _sha
from lib.safe_text import read_file
from lib.task_graph import TaskGraphError
from lib.task_graph_records import digest, file_digest, read_record
from lib.validate_project_docs import project_docs_layout


def projection_kind(path: str, docs: dict) -> str | None:
    """架构页使用 PROJECT 同目录的固定单文件。plans 只接受规范化的具体 Markdown。"""
    relative = PurePosixPath(path)
    if (relative.as_posix() != path or relative.is_absolute() or '..' in relative.parts
            or '\\' in path or relative.suffix != '.md'):
        return None
    project = PurePosixPath(docs["project"])
    if relative == project or relative == project.with_name("ARCHITECTURE.md"):
        return "index"
    return "plan" if relative.is_relative_to(docs["plans"]) else None


def reviewed_adapter(payload: dict, qa: dict) -> str:
    """从本请求已声明的项目适配器确定唯一文档布局；不让路径清单另选配置扩大权限。"""
    choices = {writer["controlled_document_access"]["adapter"] for writer in payload["tasks"]
               if writer["task_type"] == "writer" and writer["request_id"] == qa["request_id"]}
    if len(choices) != 1:
        raise TaskGraphError("PM projection requires one reviewed project adapter")
    return choices.pop()


def capture_baselines(payload: dict, qa: dict, root: Path, paths: list[str]) -> dict:
    """在正常冻结步骤取未跟踪 PM 文档的前像；不把文档加入 Writer 权限或已改代码范围。"""
    from lib.foundation_qa import _scoped_content
    _, docs = project_docs_layout(root, Path(reviewed_adapter(payload, qa)))
    if (not isinstance(paths, list) or not paths or any(not isinstance(path, str) for path in paths)
            or len(set(paths)) != len(paths)):
        raise TaskGraphError("projection_paths requires unique exact PM document paths")
    baselines = {}
    for path in paths:
        if not projection_kind(path, docs):
            raise TaskGraphError("PM projection baseline is outside configured document paths")
        content = _scoped_content(root, path)
        if not content or content[1]:
            raise TaskGraphError("PM projection baseline requires an existing non-executable document")
        baselines[path] = content[0]
    return baselines


def validate_shape(qa: dict) -> None:
    """结构校验也适用于历史图；只有复核完整回执时才访问实际项目、原档和 Git。"""
    operation = qa.get("qa_projection")
    required = {"adapter", "documents"}
    if (qa.get("state") != "QA_PASSED" or not qa.get("request_receipt")
            or not isinstance(operation, dict) or set(operation) not in (required, required | {"head_revision"})):
        raise TaskGraphError("qa_projection requires an accepted request and exact document evidence")
    adapter = operation["adapter"]
    if (not isinstance(adapter, str) or PurePosixPath(adapter).name != "project.yaml"
            or PurePosixPath(adapter).is_absolute() or str(PurePosixPath(adapter)) != adapter
            or ".." in PurePosixPath(adapter).parts or "\\" in adapter):
        raise TaskGraphError("QA projection requires the selected project adapter")
    if "head_revision" in operation and (not isinstance(operation["head_revision"], str)
            or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", operation["head_revision"])):
        raise TaskGraphError("QA projection requires the full Git commit ID")
    entries = operation["documents"]
    if not isinstance(entries, list) or not entries:
        raise TaskGraphError("QA projection requires changed documents")
    names = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"path", "reviewed", "projected_sha256"}
                or not isinstance(entry["path"], str) or entry["path"] in names
                or not _sha(entry["projected_sha256"])):
            raise TaskGraphError("QA projection requires unique exact document paths and SHA256")
        _reference(entry["reviewed"])
        names.add(entry["path"])


def _plan_evidence(body: str, path: str, *, new_evidence: bool = False, new_delivery: bool = False) -> tuple:
    """只剔除明确允许变更的值；可选恢复节和首次验收依据按实际主题出现。"""
    document = parse_plan(body, path, selected=True)
    changes = []
    if SECTIONS[3] in document.sections:
        start, end = atx_section_bounds(body, SECTIONS[3])
        start = body.index("\n", start, end) + 1
        first = re.match(r"(?:[ \t]*\r?\n)*[^\r\n]+", body[start:end])
        if first:
            changes.append((start, start + first.end()))
    delivered = ""
    if SECTIONS[4] in document.sections:
        start, end = atx_section_bounds(body, SECTIONS[4])
        content_start = body.index("\n", start, end) + 1
        delivered = body[content_start:end].strip()
        changes.append((start if new_delivery else content_start, end))
    evidence = ""
    evidence_line = None
    if SECTIONS[5] in document.sections:
        start, end = atx_section_bounds(body, SECTIONS[5])
        section = body[start:end]
        # 屏蔽围栏和注释，同时保留原字符位置；示例行不能替代被审计划的真实验收行。
        visible = "".join(iter_visible_lines(section.splitlines(keepends=True), hide_comments=True, list_fences=True))
        match = re.search(r"(?m)^- 验收证据[:：][ \t]*(.+)$", visible)
        if not match:
            raise TaskGraphError("PM projection requires one acceptance evidence line")
        evidence = match[1]
        evidence_line = len(body[:start + match.start()].splitlines()) + 1
        if new_evidence:
            # 首次验收允许补上二行来源；其中批准依据还须指向图上已有的具体授权。
            if not re.fullmatch(r"## 批准依据与必要证据\s*\n- 批准依据[:：][^\n]+\n- 验收证据[:：][^\n]+\s*", section):
                raise TaskGraphError("first acceptance section requires only approval and evidence references")
            changes.append((start, end))
        else:
            changes.append((start + match.start(1), start + match.end(1)))
    # 元信息只消费页首，标题、历史文本、批准依据以及业务章节继续逐字比较。
    header = body.split("\n## ", 1)[0]
    for name in ("已验收版本", "阶段"):
        match = re.search(r"(?m)^- " + name + r"[:：][ \t]*(.+)$", header)
        if not match:
            raise TaskGraphError("PM projection requires reviewed plan metadata")
        changes.append(match.span(1))
    stable = body
    for start, end in sorted(changes, reverse=True):
        stable = stable[:start] + stable[end:]
    return stable.rstrip("\r\n"), delivered, evidence, evidence_line, document


def _verify_plan(path: str, before: str, after: str, qa: dict, payload: dict) -> tuple[str, tuple[int | None, int]]:
    """旧交付段必须整段保留；首次交付可替换无基线模板并引用已经存在的批准。"""
    stable, delivered, old_evidence, old_line, old = _plan_evidence(before, path)
    first = old.accepted_version == "none" and SECTIONS[5] not in old.sections
    current, added, evidence, new_line, new = _plan_evidence(
        after, path, new_evidence=first, new_delivery=old.accepted_version == "none" and SECTIONS[4] not in old.sections)
    receipt_sha = qa["request_receipt"]["handoff"]["sha256"]
    if first:
        from lib.foundation_qa import request_writers
        gates = {gate for writer in request_writers(payload, qa) for gate in writer["gates"]}
        authority = {value for gate, value in payload.get("solution_approval_sources", {}).items() if gate in gates}
        if "requirements_approved" in payload.get("approved_gates", []) and payload.get("requirements_fingerprint"):
            authority.add("requirements_approved@" + payload["requirements_fingerprint"])
        if new.approval_basis not in authority:
            raise TaskGraphError("first acceptance requires an existing, bound approval source")
    placeholder = old.accepted_version == "none" and delivered.startswith(("当前尚无已验收基线", "当前没有已验收基线"))
    # 整行移入已交付历史时仍可恢复旧摘要与原声明；当前验收行只需引用本轮材料。
    archived = old_line is not None and before.splitlines()[old_line - 1] in added.splitlines()
    retained_hashes = re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", old_evidence)
    if (stable != current or new.accepted_version == "none" or not added
            or placeholder and added.startswith(("当前尚无已验收基线", "当前没有已验收基线"))
            or not re.search(r"(?<![0-9a-f])" + receipt_sha + r"(?![0-9a-f])", evidence)
            or old.stage != new.stage and (old.stage not in {"draft", "active"} or new.stage not in {"active", "completed"})
            or not archived and any(value not in evidence for value in retained_hashes)
            or delivered and not placeholder and not (added == delivered or added.startswith(delivered + "\n\n")
                                                      or added.endswith("\n\n" + delivered))):
        raise TaskGraphError("PM plan projection changed reviewed requirements, authority or historical results")
    # PM 摘要使用普通正文及经过校验的链接；HTML、围栏、引用定义等可改变 Markdown
    # 余下文档的解释，不能把这些结构放在验收栏来绕开受审正文的比较。
    for line in Counter(after.splitlines()) - Counter(before.splitlines()):
        if re.search(r"<!--|</?[A-Za-z]|^\s*(```|~~~|\[[^]]+\]:)|^ {4}|^\t", line):
            raise TaskGraphError("PM projection only permits plain closeout text and verified links")
    return new.topic_id.casefold(), (old_line, new_line)


def _git_document(repo: Path, revision: str, name: str) -> bytes:
    """只读取这个提交中精确路径的非可执行普通 blob，拒绝目录、链接、删除及特殊模式。"""
    from lib.delivery.worktree_cli import git, object_id
    object_id(repo, revision)
    listing = git(repo, "ls-tree", "-z", revision, "--", name)
    if not listing.startswith(b"100644 blob "):
        raise TaskGraphError("PM projection baseline requires an existing regular Git document")
    object_name = listing.split(b"\t", 1)[0].split()[2].decode("ascii")
    if int(git(repo, "cat-file", "-s", object_name)) > 4 * 1024 * 1024:
        raise TaskGraphError("PM projection exceeds the document read limit")
    return git(repo, "cat-file", "blob", object_name)


def verify_projection(payload: dict, qa: dict, root: Path, *, delivered: bool = False) -> dict:
    """原档内容还要经过原检查点摘要的最终比对。仅凭自报的前后 SHA 不会得到 PASS。"""
    from lib.delivery.worktree_cli import clean, head, linked, scope
    validate_shape(qa)
    operation = qa["qa_projection"]
    entries = operation["documents"]
    names = {entry["path"] for entry in entries}
    adapter = operation["adapter"]
    integration = payload.get("worktree_integrations", {}).get(qa["request_id"])
    candidate = root
    if integration:
        projected_revision = operation.get("head_revision")
        if not projected_revision:
            raise TaskGraphError("post-QA integration projection requires a commit")
        if not delivered:
            candidate = linked(root, integration["root"])
            clean(candidate)
            if head(candidate) != projected_revision:
                raise TaskGraphError("projected integration HEAD differs from its recorded commit")
        reviewed_revision = integration["head_revision"]
        if set(scope(root, reviewed_revision, projected_revision)["changed_paths"]) != names:
            raise TaskGraphError("post-QA Git delta must contain exactly the registered documents")
        # 候选 adapter 在同一轮及主树必须均允许这些位置；亦防止通过候选配置扩大范围。
        _, main_docs = project_docs_layout(root, Path(adapter))
        if any(not projection_kind(name, main_docs) for name in names):
            raise TaskGraphError("PM projection outside main project document configuration")
    else:
        if "head_revision" in operation:
            raise TaskGraphError("non-isolated PM projection requires the project adapter and no commit override")
        if reviewed_adapter(payload, qa) != adapter:
            raise TaskGraphError("PM projection adapter differs from reviewed request")
        from lib.foundation_qa import _frozen_scope_paths, request_writers
        from lib.task_graph_cli import _is_within
        writers = request_writers(payload, qa)
        # 普通请求由冻结差异绑定文件；旧的分阶段最终检查点则取所有 Writer 的
        # 实际交付内容。两者都绑定明确采用的权威原文，PM 文档并不需要虚挂所有权。
        scope_ref = qa.get("qa_scope_ref")
        if scope_ref:
            scoped = set(_frozen_scope_paths(scope_ref))
        elif "foundation_task_id" in qa:
            scoped = {name for name in names if any(_is_within(name, owned)
                      for writer in writers for owned in writer["owned_paths"])}
        else:
            raise TaskGraphError("single-tree projection requires a frozen request scope")
        authorities = {doc["path"] for task in [qa, *writers]
                       for doc in task.get("controlled_document_access", {}).get("documents", []) if doc["mode"] != "skip"}
        authorities.update(ref["path"] for task in writers for ref in task.get("ui_change", {}).get("design_authority_refs", [])
                           if ref["kind"] != "prototype_contract")
        scoped.update(authorities)
    _, docs = project_docs_layout(candidate, Path(adapter))
    plans = [name for name in names if projection_kind(name, docs) == "plan"]
    originals = {}
    topics = {}
    documents = {}
    acceptance_lines = {}
    for entry in entries:
        name = entry["path"]
        kind = projection_kind(name, docs)
        if kind is None:
            raise TaskGraphError("PM projection outside configured PROJECT, ARCHITECTURE and plans")
        target = candidate / name
        previous = read_record(Path(entry["reviewed"]["path"]))
        # 已交付工作树可能已清理；历史验证仅取已合并提交对象，避免把当前主分支上
        # 后续请求的文档误判成旧投影。活动分支仍必须检查实物、模式和干净的 HEAD。
        current = _git_document(root, projected_revision, name) if delivered else read_file(target)
        if (current is None or current == previous or digest(previous) != entry["reviewed"]["sha256"]
                or digest(current) != entry["projected_sha256"] or not delivered and target.stat().st_mode & 0o111):
            raise TaskGraphError("PM projection bytes or file mode differ from declared evidence")
        if integration:
            # 必须是原候选已审的普通文档，包括未被原 diff 修改的文件；不接受替换链接、
            # 新增业务说明或自选旧快照冒充该 Git 提交中的输入。
            if _git_document(root, reviewed_revision, name) != previous:
                raise TaskGraphError("PM projection baseline differs from the reviewed Git document")
        elif name in qa.get("qa_projection_baselines", {}):
            if digest(previous) != qa["qa_projection_baselines"][name]:
                raise TaskGraphError("PM projection differs from its frozen document baseline")
        elif name not in scoped:
            # PM 专有文档无需交给 Writer。范围外文件取原受审提交中的对象作为前像，
            # 这样选错目录、自报任意旧文或只提供当前工作目录摘要都不能授予豁免。
            from lib.task_graph_records import decode
            if scope_ref:
                repositories = scope_ref["repositories"]
                revision = repositories[0]["head_revision"] if len(repositories) == 1 and repositories[0]["path"] == "." else None
            else:
                # 原阶段图没有 qa_scope_ref。读取已被独立结论按字节绑定的最终 QA 包；
                # 旧包优先沿原 handoff 的真实单仓提交定位，绝不采用当前 HEAD 当作过去。
                reference = qa["request_receipt"]["task_pack"]
                raw = read_record(Path(reference["path"]))
                if digest(raw) != reference["sha256"]:
                    raise TaskGraphError("reviewed Foundation task pack changed")
                revision = decode(raw).get("qa_document_base")
                if not revision:
                    reference = qa["request_receipt"]["handoff"]
                    raw = read_record(Path(reference["path"]))
                    if digest(raw) != reference["sha256"]:
                        raise TaskGraphError("reviewed Foundation handoff changed")
                    repositories = decode(raw)["review_method"]["scope_ref"]["repositories"]
                    revision = repositories[0]["head_revision"] if len(repositories) == 1 and repositories[0]["path"] == "." else None
            if not revision or _git_document(root, revision, name) != previous:
                raise TaskGraphError("PM-owned document differs from the reviewed Git commit")
        before, after = previous.decode("utf-8"), current.decode("utf-8")
        if kind == "plan":
            topic, acceptance_lines[target] = _verify_plan(name, before, after, qa, payload)
            if not delivered and topic in topics and not target.samefile(topics[topic]):
                raise TaskGraphError(f"duplicate 主题 ID {topic}: {topics[topic]} and {target}")
            topics[topic] = target
        else:
            # 目录/架构的维护信息可在受审候选中完整编辑。验收后的附加导航只引用本次
            # 一并验证的主题，不能借 ARCHITECTURE 或 PROJECT 发布未经审查的职责修改。
            prefix = previous.rstrip(b"\r\n") + b"\n\n"
            allowed = [prefix + f"- [{Path(plan).stem}]({os.path.relpath(plan, Path(name).parent)})\n".encode()
                       for plan in plans]
            if current not in allowed:
                raise TaskGraphError("post-QA index projection requires an exact link to a verified plan")
        originals[name] = (digest(previous), digest(current))
        documents[target] = before, after
    # 历史收口按原提交重放。活动投影同时核对本轮验收行采用的证据和其余引用增量。
    if not delivered:
        errors = projection_link_errors(candidate, documents,
                                        lambda target: file_digest(candidate, target.relative_to(candidate).as_posix()),
                                        acceptance_lines=acceptance_lines)
        if errors:
            raise TaskGraphError("invalid PM projection links or evidence: " + "; ".join(errors))
    return originals
