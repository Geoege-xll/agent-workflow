#!/usr/bin/env python3
"""PM 的 worktree 创建、实际 Git 范围核验与本地快进交付工具。

本工具不启动 Agent、不提交代码、不解决冲突、不推送、不清理目录。中间检查点及
集成由 PM 按授权范围组织；本工具把最终主分支变更限制为已完成请求、精确 QA
范围和有效授权上的 fast-forward。JSON 是内部证据，不是用户输出。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True

if __package__:
    from .qa_handoff_cli import QAHandoffError, validate_qa_handoff
    from .task_graph import TaskGraphError, request_closure
    from .task_graph_cli import _execute, _tasks
    from .validate_project_config import validate_docs
    from .validate_project_docs import validate as validate_documents
    from .worktree_policy import WorktreePolicyError, revision, settings
else:
    from qa_handoff_cli import QAHandoffError, validate_qa_handoff
    from task_graph import TaskGraphError, request_closure
    from task_graph_cli import _execute, _tasks
    from validate_project_config import validate_docs
    from validate_project_docs import validate as validate_documents
    from worktree_policy import WorktreePolicyError, revision, settings


class DeliveryError(ValueError):
    """停止交付并保留工作；不能通过强制 Git 操作绕过。"""


def git(repo: Path, *arguments: str, allowed: tuple[int, ...] = (0,)) -> bytes:
    """始终使用参数数组与明确 cwd；拒绝环境变量把操作重定向到其他 Git 仓库。

保留用户 Git 配置和 hooks，不借工作流取消安全检查。读取 diff 禁止外部 diff 和
textconv，避免审计指纹依赖可执行转换器或用户显示偏好。
"""
    environment = dict(os.environ)
    for key in tuple(environment):
        if key.startswith("GIT_") and key not in {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"}:
            environment.pop(key)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(["git", "--literal-pathspecs", "-C", str(repo), *arguments],
                            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=False, timeout=45)
    if result.returncode not in allowed:
        raise DeliveryError(result.stderr.decode("utf-8", errors="replace").strip()
                            or f"git {arguments[0]} failed ({result.returncode})")
    return result.stdout


def repository(path: Path) -> Path:
    """调用者必须给仓库根，而不是让相对路径或子目录偷偷扩大文件作用域。"""
    root = path.resolve(strict=True)
    actual = Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if root != actual:
        raise DeliveryError("--repo must identify the exact repository/worktree root")
    return root


def common_dir(repo: Path) -> Path:
    return (repo / git(repo, "rev-parse", "--git-common-dir").decode().strip()).resolve()


def object_id(repo: Path, value: str) -> str:
    revision(value, "revision")
    actual = git(repo, "rev-parse", "--verify", f"{value}^{{commit}}").decode().strip()
    if actual != value:
        raise DeliveryError("revision must be the exact commit ID, not an alias")
    return actual


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").decode().strip()


def ancestor(repo: Path, base: str, tip: str) -> None:
    git(repo, "merge-base", "--is-ancestor", base, tip)


def clean(repo: Path) -> None:
    """不自动 stash/reset：任何暂存、未暂存、未跟踪或冲突状态都保留给用户。"""
    if git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"):
        raise DeliveryError(f"worktree is not clean; preserve existing work: {repo}")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        location = git(repo, "rev-parse", "--git-path", marker).decode().strip()
        if (repo / location).exists():
            raise DeliveryError(f"unfinished Git operation in {repo}: {marker}")


def linked(repo: Path, raw: str) -> Path:
    """只有同一个仓库登记的真实根目录才是 worktree，普通 branch 名称不构成隔离。"""
    path = Path(raw)
    actual = repository(path)
    if str(actual) != raw or actual == repo or common_dir(actual) != common_dir(repo):
        raise DeliveryError("worktree must be a distinct canonical root in the same repository")
    entries = git(repo, "worktree", "list", "--porcelain", "-z").split(b"\0")
    roots = {os.fsdecode(item[len(b"worktree "):]) for item in entries if item.startswith(b"worktree ")}
    if raw not in roots:
        raise DeliveryError("worktree root is not registered by Git")
    return actual


def target_branch(repo: Path, selected: str) -> str:
    """主分支由明确配置或仓库事实决定；main/master 同时存在且无默认信息时不猜。"""
    if selected == "auto":
        remote = git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", allowed=(0, 1)).decode().strip()
        if remote.startswith("refs/remotes/origin/"):
            selected = remote.removeprefix("refs/remotes/origin/")
        else:
            refs = set(git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/").decode().splitlines())
            candidates = [name for name in ("main", "master") if f"refs/heads/{name}" in refs]
            if len(candidates) != 1:
                raise DeliveryError("cannot resolve one main branch; configure target_branch explicitly")
            selected = candidates[0]
    if not isinstance(selected, str) or selected.startswith("-") or selected.startswith("refs/"):
        raise DeliveryError("target_branch must be an exact local branch name")
    git(repo, "check-ref-format", f"refs/heads/{selected}")
    git(repo, "rev-parse", "--verify", f"refs/heads/{selected}^{{commit}}")
    return selected


def scope(repo: Path, base: str, tip: str) -> dict[str, Any]:
    """导出 QA 与最终交付共用的确定性范围；重命名使用删除/新增两端防止漏审。"""
    object_id(repo, base)
    object_id(repo, tip)
    ancestor(repo, base, tip)
    patch = git(repo, "diff", "--binary", "--full-index", "--no-renames", "--no-ext-diff",
                "--no-textconv", base, tip, "--")
    paths = git(repo, "diff", "--name-only", "--no-renames", "-z", base, tip, "--").split(b"\0")
    return {"path": ".", "base_revision": base, "head_revision": tip,
            "diff_fingerprint": hashlib.sha256(patch).hexdigest(),
            "changed_paths": sorted(os.fsdecode(path) for path in paths if path)}


def create(repo: Path, path: Path, base: str) -> dict[str, str]:
    """只创建全新 detached worktree，不提交主目录、不复制未跟踪配置、不覆盖已有目录。"""
    object_id(repo, base)
    absolute = path.absolute()
    if absolute != absolute.resolve() or absolute.exists() or absolute.is_symlink():
        raise DeliveryError("new worktree path must be canonical, absent, and not a symlink")
    if absolute == repo or absolute.is_relative_to(repo) or repo.is_relative_to(absolute):
        raise DeliveryError("portable worktrees must be outside the original checkout")
    if not absolute.parent.is_dir():
        raise DeliveryError("worktree parent must already exist")
    git(repo, "worktree", "add", "--detach", str(absolute), base)
    actual = linked(repo, str(absolute))
    if head(actual) != base:
        raise DeliveryError("created worktree has unexpected HEAD; preserve it for inspection")
    return {"root": str(actual), "base_revision": base, "head_revision": base}


def within(path: str, owned: str) -> bool:
    return path == owned.rstrip("/") or path.startswith(owned.rstrip("/") + "/")


def merge_check(repo: Path, config: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """最终核验真实仓库状态，不把 JSON 中的 PASS、路径数组或旧任务状态当成事实。"""
    config = config.absolute()
    if config != config.resolve() or not config.is_relative_to(repo) or config.name != "project.yaml":
        raise DeliveryError("merge --config must be the canonical project.yaml inside the target checkout")
    lines = config.read_text(encoding="utf-8").splitlines()
    policy = settings(lines)
    if policy["mode"] == "off":
        raise DeliveryError("parallel_worktrees.mode is off")
    graph = payload.get("task_graph")
    if not isinstance(graph, dict):
        raise DeliveryError("delivery requires the current task_graph")
    _execute("validate", graph)
    if not _execute("qa-ready", graph)["qa_ready"]:
        raise DeliveryError("writers or integration verification are incomplete")
    request_id = graph["request_id"]
    record = graph.get("worktree_integrations", {}).get(request_id)
    if record is None:
        raise DeliveryError("delivery requires this request's worktree integration")
    tasks = _tasks(graph)
    closure = request_closure(tasks, request_id)
    selected = [task for task in graph["tasks"] if task["id"] in closure]
    indexed = {task["id"]: task for task in selected}
    for task in selected:
        # qa-ready 只表示可以开始审查；显式 QA 节点必须实际完成，旧 PASS 不能覆盖复审中或失败态。
        completed = {"QA_PASSED"} if task["task_type"] == "qa" else {"BUILD_VERIFIED", "QA_SCOPE_READY"}
        if task["state"] not in completed:
            raise DeliveryError(f"request task is not complete: {task['id']}")
        if task["task_type"] == "writer" and not set(task["gates"]) <= set(graph.get("approved_gates", [])):
            raise DeliveryError(f"request writer has an unapproved gate: {task['id']}")
    branch = target_branch(repo, policy["target_branch"])
    if record["target_branch"] != branch:
        raise DeliveryError("integration target does not match the configured main branch")
    if git(repo, "symbolic-ref", "--quiet", "HEAD").decode().strip() != f"refs/heads/{branch}":
        raise DeliveryError("target checkout must already be on the resolved main branch; no automatic switch")
    base, tip = record["target_base"], record["head_revision"]
    if head(repo) != base:
        raise DeliveryError("target branch moved; preserve work and refresh integration, QA and consent")
    clean(repo)
    integration = linked(repo, record["root"])
    clean(integration)
    if head(integration) != tip:
        raise DeliveryError("integration HEAD changed after verification")
    current_scope = scope(repo, base, tip)
    if not current_scope["changed_paths"]:
        raise DeliveryError("no changed files to deliver; report a no-op instead of manufacturing a merge")
    # 自动交付第一版只操作一个仓库。嵌套仓库和 submodule 必须逐仓库另行集成，
    # 不能仅更新父仓库指针就声称子仓库的主分支已经交付。
    if any(line.startswith(b"160000 ") for line in git(repo, "ls-tree", "-r", tip).splitlines()):
        raise DeliveryError("submodule delivery requires a separate per-repository integration")
    owned: list[str] = []
    for task in selected:
        if task["task_type"] != "writer":
            continue
        workspace = task.get("execution_workspace")
        if task["request_id"] != request_id:
            # A 已交付后 B 可以依赖 A 的提交，不要求 A 的旧 worktree 仍存在。
            # 历史路径不进入本次写权限；仅核实可证明的检查点已包含于当前共同基线。
            if workspace is not None:
                object_id(repo, workspace["head_revision"])
                ancestor(repo, workspace["head_revision"], base)
            continue
        owned.extend(task["owned_paths"])
        if workspace is None:
            # 跨请求已验证依赖可以来自共同基线；本请求所有 Writer 已由图校验强制隔离。
            continue
        worker = linked(repo, workspace["root"])
        clean(worker)
        if head(worker) != workspace["head_revision"]:
            raise DeliveryError(f"writer HEAD changed after handoff: {task['id']}")
        worker_scope = scope(repo, workspace["base_revision"], workspace["head_revision"])
        # 主分支在开发期间前进后，允许保留已完成工作单元的原基线和检查点。
        # 旧 target_base 仍在上方被拒绝；只有重新集成主线、刷新完整 QA/授权才可交付。
        # scope 已证明 worker base→checkpoint，后面再证明 checkpoint→当前集成结果。
        # B 的基线必须包含所有传递前置 A；中间的只读/证据节点不能截断代码依赖。
        pending = list(task["depends_on"])
        checked: set[str] = set()
        while pending:
            dependency_id = pending.pop()
            if dependency_id in checked:
                continue
            checked.add(dependency_id)
            dependency = indexed[dependency_id]
            pending.extend(dependency["depends_on"])
            predecessor = dependency.get("execution_workspace")
            if predecessor is not None:
                ancestor(repo, predecessor["head_revision"], workspace["base_revision"])
        ancestor(repo, workspace["head_revision"], tip)
        if any(not any(within(path, boundary) for boundary in task["owned_paths"])
               for path in worker_scope["changed_paths"]):
            raise DeliveryError(f"writer checkpoint exceeds owned_paths: {task['id']}")
    projection = payload.get("projection_paths", [])
    if not isinstance(projection, list) or not all(isinstance(path, str) for path in projection):
        raise DeliveryError("projection_paths must be exact PM-owned document paths")
    # 投影是逐文件授权，不接受目录前缀。删除文件也在实际 diff 中，不强制文件当前存在。
    if len(projection) != len(set(projection)) or any(
        path not in current_scope["changed_paths"] or PurePosixPath(path).is_absolute()
        or str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts
        or "\\" in path or not path.endswith(".md") or (integration / path).is_dir()
        for path in projection
    ):
        raise DeliveryError("projection_paths requires unique normalized exact changed Markdown files")
    if projection:
        errors: list[str] = []
        docs = validate_docs(lines, integration, errors)
        allowed_files = {docs.get("project")}
        allowed_roots = [docs.get(key, "") for key in ("features", "plans")]
        if errors or any(path not in allowed_files and not any(root and within(path, root) for root in allowed_roots)
                         for path in projection):
            raise DeliveryError("PM projection must stay within configured PROJECT/features/plans")
        errors = validate_documents(config, integration)
        if errors:
            raise DeliveryError("controlled-document projection is invalid: " + "; ".join(errors))
    if any(path not in projection and not any(within(path, boundary) for boundary in owned)
           for path in current_scope["changed_paths"]):
        raise DeliveryError("integration contains changes outside the request and validated PM projection")
    qa = payload.get("qa_handoff")
    if not isinstance(qa, dict):
        raise DeliveryError("delivery requires the independent QA handoff")
    validate_qa_handoff(qa)
    if qa["audit_result"] != "PASS":
        raise DeliveryError("QA FAIL blocks delivery")
    if qa["review_method"]["scope_ref"]["repositories"] != [current_scope]:
        raise DeliveryError("QA scope does not match the actual complete integration diff")
    coverage = qa["standards_policy_coverage"]
    contract = graph["standards_contract"]
    if any(coverage[key] != contract[key] for key in ("index_path", "root", "index_fingerprint")):
        raise DeliveryError("QA standards index does not match the current task contract")
    writers = [task for task in selected if task["task_type"] == "writer" and task["request_id"] == request_id]
    expected_rules = {rule for task in writers for document in task["controlled_document_access"]["documents"]
                      if document["mode"] != "skip" for rule in document["rule_ids"]}
    if set(coverage["task_pack_rule_ids"]) != expected_rules:
        raise DeliveryError("QA Task Pack rules do not match the current request writers")
    domains = set()
    for task in writers:
        domains.update(("design",) if task["surface_kind"] == "design_ui" else
                       ("engineering", "design") if task["surface_kind"] == "production_ui" else ("engineering",))
    # QA 可以独立发现更多适用规则；但不能通过重填报告删掉当前任务必须覆盖的规范。
    for domain in domains:
        key = f"required_{domain}_rule_ids"
        if not set(contract[key]) <= set(coverage[key]):
            raise DeliveryError(f"QA omits mandatory {domain} rules from the current task contract")
    rule_sources = {rule: leaf for leaf in contract["leaves"] for rule in leaf["rule_ids"]}
    for check in coverage["rule_checks"]:
        leaf = rule_sources.get(check["rule_id"])
        if leaf is None or (check["source_path"], check["source_fingerprint"], check["domain"]) != (
            leaf["path"], leaf["content_fingerprint"], leaf["domain"]
        ):
            raise DeliveryError("QA rule source does not match the current standards contract")
    frozen_sources = [(coverage["index_path"], coverage["index_fingerprint"])] + [
        (check["source_path"], check["source_fingerprint"]) for check in coverage["rule_checks"]
    ]
    for relative, fingerprint in frozen_sources:
        document = integration / relative
        if (document.resolve() != document or not document.is_relative_to(integration)
                or hashlib.sha256(document.read_bytes()).hexdigest() != fingerprint):
            raise DeliveryError(f"QA standards authority changed: {relative}")
    # 授权绑定整个候选版本。项目 auto 是显式配置；confirm 则必须记录用户自然语言答复。
    authorization = payload.get("authorization")
    binding = {"request_id": request_id, "target_branch": branch, "target_base": base,
               "head_revision": tip, "diff_fingerprint": current_scope["diff_fingerprint"]}
    if not isinstance(authorization, dict) or any(authorization.get(key) != value for key, value in binding.items()):
        raise DeliveryError("merge authorization is missing or stale for this candidate")
    mode = authorization.get("mode")
    source = authorization.get("source")
    if mode == "auto":
        if policy["merge"] != "auto" or source != "project:parallel_worktrees.merge":
            raise DeliveryError("automatic merge requires explicit project configuration")
    elif mode == "confirm":
        if not isinstance(source, str) or not source.startswith("user:") or not source[5:].strip():
            raise DeliveryError("confirm mode requires an explicit user reply reference")
    else:
        raise DeliveryError("merge authorization.mode must be confirm or auto")
    return {**binding, "status": "merge_ready", "mode": mode}


def merge(repo: Path, config: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """先完整核验再快进，不解决冲突；Git 仍保留自身的锁、hooks 和脏目录检查。"""
    result = merge_check(repo, config, payload)
    # 不覆盖被忽略的本地文件；不通过 reset/update-ref 绕过 Git 的工作目录保护。
    git(repo, "merge", "--ff-only", "--no-edit", "--no-overwrite-ignore", result["head_revision"])
    if head(repo) != result["head_revision"]:
        raise DeliveryError("merge may have completed but HEAD changed; inspect before retrying, do not reset")
    clean(repo)
    return {**result, "status": "merged", "pushed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("target", "create", "inspect", "merge-ready", "merge"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--path", type=Path)
    parser.add_argument("--base")
    parser.add_argument("--head")
    args = parser.parse_args()
    try:
        repo = repository(args.repo)
        if args.command == "create":
            if args.path is None or args.base is None:
                raise DeliveryError("create requires --path and an exact --base")
            result = create(repo, args.path, args.base)
        elif args.command == "inspect":
            if args.base is None or args.head is None:
                raise DeliveryError("inspect requires exact --base and --head")
            result = scope(repo, args.base, args.head)
        elif args.command == "target":
            config = settings(args.config.read_text().splitlines()) if args.config else settings([])
            branch = target_branch(repo, config["target_branch"])
            result = {"target_branch": branch, "target_base": git(repo, "rev-parse", f"refs/heads/{branch}").decode().strip()}
        else:
            if args.config is None:
                raise DeliveryError("merge commands require the project adapter --config")
            payload = json.loads(args.input.read_text() if args.input else sys.stdin.read())
            if not isinstance(payload, dict):
                raise DeliveryError("delivery input must be an object")
            operation = merge if args.command == "merge" else merge_check
            result = operation(repo, args.config, payload)
    except (DeliveryError, WorktreePolicyError, TaskGraphError, QAHandoffError,
            OSError, UnicodeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
