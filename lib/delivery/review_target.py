"""比对已冻结的 QA 范围与一个真实 Git 目标；仅输出本机取证结果。"""
from __future__ import annotations

import mmap
from pathlib import Path, PurePosixPath
import re
from subprocess import TimeoutExpired

from lib.delivery.worktree_cli import diff_bytes, git, head, local_objects_only, private_dir, repository, scope
from lib.task_graph_records import digest
from lib.worktree_policy import REVISION


def _uses_split_index(repo: Path) -> bool:
    """直接辨认 index 的 link 扩展，避免向 Git 查询共享索引时就刷新其 mtime。"""
    directory = private_dir(repo)
    shared_ids = {path.name.removeprefix("sharedindex.") for path in directory.glob("sharedindex.*")}
    index = directory / "index"
    if not shared_ids or not index.exists():
        return False
    if index.is_symlink() or not index.is_file():
        raise ValueError("无法只读核对物理 Git 索引")
    # 关闭 split index 后旧共享文件仍会滞留。只对当前索引中 link + 4 字节长度
    # 后的完整 SHA-1/SHA-256 与在场的共享索引对应时保留缺口，普通索引继续比对。
    with index.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for match in re.finditer(b"link", data):
            start = match.end() + 4
            if any(data[start:start + size].hex() in shared_ids for size in (20, 32)):
                return True
    return False


def _worktree_snapshot(repo: Path) -> tuple[dict, str]:
    """按未提交目标的语义枚举索引、工作区和未跟踪项；不能从普通 diff 推断后两者为空。"""
    current = head(repo)
    observed = {"base_revision": current, "head_revision": current}
    if _uses_split_index(repo):
        return observed, "当前工作树正在使用拆分索引，读取状态会刷新共享索引时间；需要独立的只读取证。"
    # 状态查询可能启动用户的过滤器或文件监控。这里只在可直接读取时取证，不通过改
    # 仓库配置取得不同的补丁；Git 子模块另有独立工作区，根仓状态不足以审查其中内容。
    monitor = git(repo, "config", "--type=bool", "--get", "core.fsmonitor", allowed=(0, 1)).strip()
    if monitor == b"true":
        return observed, "工作区配置了文件监控，需要能独立确认只读的取证方法。"
    index = git(repo, "ls-files", "-v", "--stage", "-z").split(b"\0")
    if any(item and (item[:1] != b"H" or item[2:].startswith(b"160000 ")) for item in index):
        return observed, "索引含隐藏、冲突或子模块条目，当前方法无法核实所有改动。"
    settings = git(repo, "config", "-z", "--get-regexp", r"^filter\..*\.(clean|process)$", allowed=(0, 1))
    # 同名配置后者覆盖前者，空命令可关闭原驱动。保留子段中的驱动名及其大小写，
    # 防止全局 LFS 使只标记了另一个未启用过滤器的文件也失去比对机会。
    effective = {}
    for item in settings.split(b"\0"):
        key, _, command = item.partition(b"\n")
        if key:
            effective[key] = command
    drivers = {key[len(b"filter."):].rsplit(b".", 1)[0] for key, command in effective.items() if command.strip()}
    if drivers:
        # 安装了 LFS 等驱动不代表本仓有文件使用它。NUL 输入保留特殊文件名；工作区
        # 与索引可有不同的 attributes，两者都取证后才决定是否需要独立的只读途径。
        names = b"".join(item.split(b"\t", 1)[1] + b"\0" for item in index if item)
        for options in ((), ("--cached",)):
            attributes = git(repo, "check-attr", *options, "-z", "--stdin", "filter", stdin=names)
            if drivers.intersection(attributes.split(b"\0")[2::3]):
                return observed, "仓库路径使用已配置的内容过滤器，需要核实其读取语义与副作用。"
    rows = git(repo, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all",
               "--ignore-submodules=none").split(b"\0")
    entries = [(row[:2], row[3:].decode("utf-8")) for row in rows if row]
    observed["changed_paths"] = sorted(path for _, path in entries)
    if any(state == b"??" for state, _ in entries):
        return observed, "目标包含未跟踪条目；普通 Git 补丁未绑定它们的内容。"
    if any(state[:1] != b" " and state[1:] != b" " for state, _ in entries):
        return observed, "同一路径同时包含索引和工作区变更；单份 HEAD 补丁可能隐藏中间的暂存内容。"
    observed["diff_fingerprint"] = digest(diff_bytes(repo, current))
    return observed, ""


@local_objects_only()
def compare_target(task: dict, reference: dict, target: dict, project: Path) -> dict:
    """在包内已绑定的项目相对仓库中检查一个目标，保留原范围及真实摘要供调用前后比对。"""
    frozen = task.get("qa_scope_ref")
    report = {"handoff_ref": reference, "candidate": target, "frozen_scope": frozen,
              "qa_scope_fingerprint": task.get("qa_scope_fingerprint")}

    def result(status: str, reason: str) -> dict:
        return {**report, "status": status, "reason": reason}

    if not frozen or not report["qa_scope_fingerprint"]:
        return result("needs-evidence", "当前包缺少 PM 已冻结的范围及其输入指纹，需取得可归属本次请求的依据。")
    kind = target.get("kind")
    fields = {"kind", "repository"}
    if kind == "commit-range":
        fields.update(("base_revision", "head_revision"))
    elif kind != "uncommitted":
        return result("needs-evidence", "需要宿主确实支持的固定提交区间或仅未提交改动的目标。")
    if fields != target.keys() or not isinstance(target["repository"], str):
        return result("needs-evidence", "候选仓库或修订参数不完整，或存在无法解释的额外目标参数。")
    repositories = frozen["repositories"]
    if len(repositories) != 1 or target["repository"] != repositories[0]["path"]:
        return result("not-representable", "该单仓目标不能覆盖完整冻结仓库集合。")
    expected = repositories[0]
    name = expected["path"]
    try:
        # 拒绝把嵌套路径重定向到其他目录或由 Git 向上发现外层仓库。特殊 gitfile
        # 可能指向项目外的管理目录；由调用方另取已登记身份的证据，不跟随它猜测。
        project = project.resolve(strict=True)
        relative = Path(name)
        location = project / relative
        if (location.resolve(strict=True) != location or not location.is_relative_to(project)
                or ".git" in (part.lower() for part in relative.parts)
                or (location / ".git").is_symlink()
                or (name != "." and not (location / ".git").is_dir())):
            return result("needs-evidence", "嵌套仓库的物理根或 Git 管理目录需要独立身份证据。")
        repo = repository(location)
        report["repository_root"] = str(repo)
        # 部分克隆也可能已经拥有这段变更所需的全部对象。整次调用已禁用隐式抓取
        # 和传输，因此直接读实际对象；缺少对象时由下方统一返回证据缺口。
        if kind == "commit-range":
            base, tip = target["base_revision"], target["head_revision"]
            if any(not isinstance(oid, str) or not REVISION.fullmatch(oid) for oid in (base, tip)):
                return result("needs-evidence", "提交区间需要两个完整的不可变 Git 提交 ID。")
            # gitlink 只钉住内层提交。即使根树的表面路径和摘要相等，也不能把它
            # 冒充已展开审查的子仓内容。原始记录的路径用 NUL 隔开，不能按空格拆文件名。
            raw = git(repo, "diff", "--raw", "-z", "--no-renames", "--no-ext-diff",
                      "--ignore-submodules=none", base, tip, "--").split(b"\0")
            if any(b"160000" in row.removeprefix(b":").split(b" ", 2)[:2] for row in raw[::2]):
                return result("needs-evidence", "提交区间含子模块指针变更，需核对子仓范围。")
            observed = scope(repo, base, tip)
            # Git 允许非 UTF-8 文件名，原 scope 的本机路径解码会保留这些字节。
            # schema 2 只能绑定合法 Unicode；不能在诊断 JSON 写出损坏的候选清单。
            for path in observed["changed_paths"]:
                path.encode("utf-8", errors="strict")
            extra = ""
        else:
            # 可变的工作区需要重新采样；同一路径清单下仍可能在两次采样间换掉某个 hunk。
            observed, extra = _worktree_snapshot(repo)
            if (observed, extra) != _worktree_snapshot(repo):
                return result("needs-evidence", "取证期间工作树或暂存区发生变化，请基于稳定候选重新比对。")
    except (OSError, ValueError, RuntimeError, TimeoutExpired) as exc:
        return result("needs-evidence", f"无法从指定仓库核对完整候选：{exc}")
    observed["path"] = name
    if "changed_paths" in observed:
        observed["changed_paths"] = [(PurePosixPath(name) / path).as_posix() for path in observed["changed_paths"]]
    report["observed"] = observed
    if any(not REVISION.fullmatch(expected[key]) for key in ("base_revision", "head_revision")):
        return result("needs-evidence", "冻结修订使用不同的快照标识，需要原取证方法解释其与 Git 目标的关系。")
    if any(observed[key] != expected[key] for key in ("base_revision", "head_revision")):
        return result("not-representable", "候选基线或终点不同于冻结的提交。")
    if "changed_paths" in observed and sorted(expected["changed_paths"]) != observed["changed_paths"]:
        return result("not-representable", "候选变更路径与冻结范围不同，无法完整且仅覆盖本次范围。")
    if extra:
        return result("needs-evidence", extra)
    if not observed["changed_paths"] or observed["diff_fingerprint"] == digest(b""):
        return result("not-representable", "候选没有可审查的变更。")
    if observed["diff_fingerprint"] != expected["diff_fingerprint"]:
        # 普通 Full 允许 PM 冻结实际补丁原字节，未约定唯一编码。摘要不同既可能
        # 是同文件混入旧 hunks，也可能源于不同补丁编码，不能单凭路径判定归属。
        return result("needs-evidence", "补丁字节摘要不同，请核对冻结补丁的编码和变更前基线以确定 hunk 归属。")
    return result("match", "单仓 Git 目标与 PM 冻结的修订、路径、补丁字节摘要一致。请求归属以冻结时的独立证据为准。")
