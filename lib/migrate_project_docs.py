#!/usr/bin/env python3
"""显式单次迁移 features 或 notes；默认只预检，保全原文，不猜测归属或验收。"""

from __future__ import annotations

import argparse
import base64
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
import stat
import shutil
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit

from claude_instructions import read_file
from platform_fs import os as secure_os, project_install_lock
from plan_documents import LINK, SECTIONS, collect_plans, local_target, parse_plan, scalar
from standard_paths import canonical_standard_path
from validate_project_config import strip_inline_comment, validate_docs
from validate_project_docs import parse_docs, validate
from task_graph_records import publish


PLACEHOLDER = "{{原文}}"
RECOVERY_KIND = "agent-workflow-docs-migration-recovery"


def git_originals(root: Path, inputs: dict[Path, bytes | None]):
    """逐文件证明真实提交中仍可恢复的原字节；工作区存在 Git 并不自动构成保护。"""
    executable = shutil.which("git")
    if executable is None:
        return None, {}
    try:
        def run(*arguments):
            return subprocess.run([executable, "-C", str(root), *arguments], capture_output=True,
                                  check=True, timeout=10).stdout
        revision = run("rev-parse", "--verify", "HEAD").decode("ascii").strip()
        repository = Path(run("rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision) or not root.is_relative_to(repository):
            return None, {}
        proven = {}
        for path, body in inputs.items():
            if body is None:
                continue
            name = path.relative_to(repository).as_posix()
            try:
                entry = run("ls-tree", "-z", revision, "--", name).split(b"\0")
                mode = {b"100644": 0o644, b"100755": 0o755}.get(entry[0].split(b" ", 1)[0])
                # Git 只保存执行位；0600 等项目权限不能因正文已提交就当作可恢复。
                if mode == stat.S_IMODE(path.lstat().st_mode) and run("show", f"{revision}:{name}") == body:
                    proven[path] = name
            except subprocess.CalledProcessError:
                continue
        return revision, proven
    except (OSError, UnicodeError, subprocess.SubprocessError):
        # 没有可核实的 Git 版本时走原件快照；绝不能用源 SHA 或进程内 before 冒充可恢复原件。
        return None, {}


def preserve_originals(root: Path, recovery: Path, updates: dict[Path, bytes | None],
                       inputs: dict[Path, bytes | None], modes: dict[Path, int], mapping: Path,
                       input_modes: dict[Path, int], *, raw_snapshot: bool = False) -> dict:
    """删除旧源前保全成功后的恢复入口；有缺口才写单份、范围明确且权限私有的快照。

    快照只保存本次实际变更的前像；Git 已证明的文件只记精确提交与路径，其余用原始
    字节编码保存。固定文件不能被另一轮或另一项目静默覆盖，成功后不清理唯一原件。
    """
    # notes 的长期目标只保留归纳结果，原始杂记与完整日志必须有独立原字节恢复入口；
    # 因此该显式模式总写单份恢复包，不以 Git 中恰好存在的正文替代原件保全。
    revision, proven = (None, {}) if raw_snapshot else git_originals(root, inputs)
    missing = [path for path, body in inputs.items()
               if body is not None and path not in proven and (not raw_snapshot or path in updates)]
    if not missing and not raw_snapshot:
        return {"strategy": "git", "revision": revision,
                "paths": [str(path.relative_to(root)) for path in proven]}
    if recovery in updates or recovery == mapping:
        raise ValueError("恢复副本不得覆盖迁移输入、目标或映射文件")
    files = {}
    for path, after in updates.items():
        before = inputs[path]
        mode = input_modes.get(path)
        files[path.relative_to(root).as_posix()] = {
            "before_sha256": None if before is None else hashlib.sha256(before).hexdigest(),
            "after_sha256": None if after is None else hashlib.sha256(after).hexdigest(),
            "before_mode": mode,
            "after_mode": None if after is None else modes.get(path, mode if mode is not None else 0o644),
            "git_path": proven.get(path),
            "body_base64": base64.b64encode(before).decode("ascii") if before is not None and path not in proven else None,
        }
    body = (json.dumps({"schema_version": 1, "kind": RECOVERY_KIND, "project": str(root),
                       "git_revision": revision, "files": files}, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n").encode("utf-8")
    if len(body) > 4 * 1024 * 1024:
        raise ValueError("必要恢复副本超出共用安全读取上限；停止删除，先明确真实可恢复来源")
    existing = read_file(recovery)
    if existing is not None and existing != body:
        raise ValueError(f"固定恢复副本已存在且前像不同，保留并停止：{recovery}")
    if existing is not None and os.name != "nt" and stat.S_IMODE(recovery.lstat().st_mode) != 0o600:
        raise ValueError(f"已有恢复副本权限不是私有，保留并停止：{recovery}")
    publish(recovery, body, "missing" if existing is None else hashlib.sha256(existing).hexdigest())
    return {"strategy": "scoped_recovery", "path": str(recovery), "sha256": hashlib.sha256(body).hexdigest(),
            "git_revision": revision, "raw_originals": [str(path.relative_to(root)) for path in missing]}


def recovery_changes(root: Path, snapshot: dict):
    """恢复仅匹配当前迁移产物的名字；用户后续编辑、未知快照或损坏原件都拒绝覆盖。"""
    if (not isinstance(snapshot, dict) or set(snapshot) != {"schema_version", "kind", "project", "git_revision", "files"}
            or snapshot["schema_version"] != 1 or snapshot["kind"] != RECOVERY_KIND
            or snapshot["project"] != str(root) or not isinstance(snapshot["files"], dict) or not snapshot["files"]):
        raise ValueError("恢复副本不属于本项目或格式未知")
    updates, inputs, modes = {}, {}, {}
    for name, record in snapshot["files"].items():
        fields = {"before_sha256", "after_sha256", "before_mode", "after_mode", "git_path", "body_base64"}
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError("恢复副本条目格式未知")
        for prefix in ("before", "after"):
            digest, mode = record[prefix + "_sha256"], record[prefix + "_mode"]
            if digest is None:
                if mode is not None:
                    raise ValueError("缺失文件不能声明权限")
            elif (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                  or type(mode) is not int or not 0 <= mode <= 0o777):
                raise ValueError("恢复副本的摘要或权限不合法")
        if (record["body_base64"] is not None and not isinstance(record["body_base64"], str)
                or record["git_path"] is not None and not isinstance(record["git_path"], str)):
            raise ValueError("恢复副本原件来源不合法")
        # 安装态配置是唯一允许的隐藏受控文件；不授予 .git 或其他隐藏目录写入权。
        path = root / name if name == ".agent-workflow/project.yaml" else relative(root, name)
        current = read_file(path)
        actual = None if current is None else hashlib.sha256(current).hexdigest()
        if actual != record["after_sha256"] or (current is not None and stat.S_IMODE(path.lstat().st_mode) != record["after_mode"]):
            raise ValueError(f"迁移后文件已变化，保留现状并停止恢复：{path}")
        before = None
        if record["before_sha256"] is not None:
            if record["body_base64"] is not None:
                before = base64.b64decode(record["body_base64"], validate=True)
            else:
                revision, git_path = snapshot["git_revision"], record["git_path"]
                if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision) or not isinstance(git_path, str):
                    raise ValueError("恢复副本缺少真实 Git 原件身份")
                command = ["git", "-C", str(root), "show", f"{revision}:{git_path}"]
                try:
                    before = subprocess.run(command, capture_output=True, check=True, timeout=10).stdout
                except (OSError, subprocess.SubprocessError) as exc:
                    raise ValueError("原 Git 版本不可恢复，保留现状；不能伪造原件") from exc
            if hashlib.sha256(before).hexdigest() != record["before_sha256"]:
                raise ValueError(f"恢复原件摘要不符：{path}")
            before.decode("utf-8")
            modes[path] = record["before_mode"]
        inputs[path], updates[path] = current, before
    return updates, inputs, modes


def relative(root: Path, value: str) -> Path:
    """迁移清单只接受规范项目相对路径，沿用安全读取核对祖先和文件类型。"""
    if (not isinstance(value, str) or not value or "\\" in value or "\0" in value
            or Path(value).is_absolute() or Path(value).as_posix() != value
            or any(part in {".", ".."} or part.startswith(".") for part in Path(value).parts)):
        raise ValueError(f"迁移路径须为非隐藏规范相对路径：{value!r}")
    path = root / value
    read_file(path)
    return path


def legacy_files(directory: Path) -> set[Path]:
    """完整覆盖旧目录的实际文档；未知资产和链接先停，避免丢弃项目专有内容。"""
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ValueError(f"旧文档必须是真实目录：{directory}")
    result = set()
    for path in sorted(directory.iterdir()):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            result.update(legacy_files(path))
        elif stat.S_ISREG(info.st_mode) and path.suffix == ".md" and info.st_nlink == 1:
            read_file(path)
            result.add(path)
        else:
            raise ValueError(f"旧目录含未明确迁移的资产或不安全节点：{path}")
    return result


def navigation_metadata(root: Path, destination: Path) -> None:
    """媒体/目录只检查项目内安全节点，不读取正文、套用文本限额或搬移资源。

    路径已由 local_target 归一并限制在项目内；再逐级以 no-follow 目录句柄定位，
    末节点只 stat。复用平台文件系统后端以拒绝符号链接/reparse、硬链接和特殊节点，
    不能为允许普通二进制导航而读取 FIFO、媒体内容或跟随危险祖先。
    """
    parts = destination.relative_to(root).parts
    flags = (secure_os.O_RDONLY | secure_os.O_DIRECTORY | secure_os.O_NOFOLLOW
             | getattr(secure_os, "O_CLOEXEC", 0))
    descriptor = secure_os.open(root, flags)
    try:
        for component in parts[:-1]:
            child = secure_os.open(component, flags, dir_fd=descriptor)
            secure_os.close(descriptor)
            descriptor = child
        try:
            info = (secure_os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
                    if parts else secure_os.fstat(descriptor))
        except FileNotFoundError as exc:
            raise ValueError(f"迁移链接目标不存在：{destination}") from exc
        if not (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
            raise ValueError(f"迁移导航目标须为真实目录或单链接普通文件：{destination}")
    finally:
        secure_os.close(descriptor)


def rewrite_links(body: str, root: Path, source: Path, target: Path,
                  mapping: dict[Path, Path], *, only_mapped: bool = False) -> str:
    """仅重定位普通 Markdown 链接，正文原样保留；不丢弃标题、批准或历史。

    有歧义语法直接停止。相对链接按原文件定位，再用显式映射重写；不会以同名、
    标题或状态猜测两个主题的关系，也不跟随符号／硬链接到项目外内容。
    """
    if re.search(r"!\s*\[|(?m:^\s{0,3}\[[^\]]+\]:)", body):
        raise ValueError(f"迁移不支持图片或引用式链接，请先明确资产处置：{source}")
    if "](" in LINK.sub("", body):
        raise ValueError(f"迁移链接存在歧义，保留源文件：{source}")

    def replace(match):
        raw = match[1]
        destination = local_target(root, source, raw)
        if destination is None:
            return match.group()
        if only_mapped and destination not in mapping:
            return match.group()
        # Markdown 属于可解析原稿，仍保留共用 UTF-8、单链接及文本大小限制；
        # 普通媒体和真实目录只是导航目标，安全元数据足够，不能把资源正文当文本读。
        if destination.suffix == ".md":
            if read_file(destination) is None:
                raise ValueError(f"迁移链接目标不存在：{source}: {raw}")
        else:
            navigation_metadata(root, destination)
        destination = mapping.get(destination, destination)
        split = urlsplit(raw)
        suffix = "#" + split.fragment if split.fragment else ""
        href = quote(Path(os.path.relpath(destination, target.parent)).as_posix(), safe="/.-_")
        # Path/relpath 会消去目录末尾斜杠；重定位仍须保留原 URI 的目录导航形状，
        # 再沿既有规则追加 fragment。query 仍在 local_target 拒绝，不在此扩权。
        if split.path.endswith("/"):
            href += "/"
        href += suffix
        return match.group().replace("(" + raw + ")", "(" + href + ")", 1)

    return LINK.sub(replace, body)


def prove_baseline(source: str, migrated, original_template, *, indexed: bool, label: str) -> None:
    """只传递旧来源中已经存在的版本／批准／验收事实；清单不能创造 QA 或批准。

    对缺少明确旧证据的当前索引条目停止迁移。调用者应先找到真实旧来源，而不能
    填一个非空说明或把 completed 改成 accepted 来绕过事实核对。
    """
    if indexed and not migrated.has_current_baseline:
        raise ValueError(f"已有当前基线不能在迁移中静默撤回：{label}")
    if migrated.accepted_version == "none":
        return
    if migrated.has_current_baseline and not indexed:
        raise ValueError(f"未索引旧材料不能在迁移中升级为当前基线：{label}")
    old_ids = re.findall(r"(?im)^- (?:Feature ID|功能 ID)[:：][ \t]*(.+)$", source)
    old_states = re.findall(r"(?im)^- (?:Status|状态)[:：][ \t]*(.+)$", source)
    expected_state = "removed" if migrated.stage == "removed" else "active"
    # 旧索引位置不是授信来源：仍须有旧模型明确身份和合法状态，不能把删除墓碑
    # 或无归属资料仅凭相同版本／证据文本恢复为当前行为。英文旧字段仅在此迁移读取。
    if (len(old_ids) != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", scalar(old_ids[0]))
            or len(old_states) != 1 or scalar(old_states[0]) != expected_state
            or (migrated.has_current_baseline and Path(label).name.endswith(".removed.md"))):
        raise ValueError(f"旧来源缺少明确身份或匹配状态，不能授信为当前基线：{label}")
    checks = (
        (r"Current version|当前版本|已验收版本", migrated.accepted_version),
        (r"Approval basis|批准依据", migrated.approval_basis),
        (r"Acceptance evidence|验收证据", migrated.acceptance_evidence),
    )
    for labels, expected in checks:
        actual = re.findall(r"(?m)^- (?:" + labels + r")[:：][ \t]*(.+)$", source)
        if len(actual) != 1 or scalar(actual[0]) != expected:
            raise ValueError(f"旧来源缺少匹配的真实版本／批准／验收依据，停止：{label}: {labels}")
    if original_template.sections.get(SECTIONS[4], "").strip() != PLACEHOLDER:
        raise ValueError(f"已验收基线须完整使用旧原文，不允许清单添加新已交付声明：{label}")


def notes_config_view(body: bytes) -> tuple[bytes, dict[str, str]]:
    """只在迁移内部识别并剔除两个精确旧键；不会创建运行时别名或发布配置。

    行号绑定真实所属段，避免误删别的配置块中的同名字段。重复旧键或不匹配目录
    均停止；features 调用者只使用返回的只读校验视图，仍发布保留 notes 的原配置。
    """
    lines = body.decode("utf-8").splitlines(keepends=True)
    section, retired, removed = "", {}, set()
    for index, line in enumerate(lines):
        top = re.match(r"^([A-Za-z0-9_]+):", line)
        if top:
            section = top[1]
        field = re.match(r"^  ([A-Za-z0-9_]+):\s*(.*?)\s*$", line)
        if field is None or (section, field[1]) not in {("docs", "notes"), ("memory", "fallback_dir")}:
            continue
        name = section + "." + field[1]
        value = strip_inline_comment(field[2]).strip("\"'")
        if name in retired or not value:
            raise ValueError(f"旧 {name} 须唯一且非空，不能猜测迁移归属")
        retired[name] = value
        removed.add(index)
    if ("memory.fallback_dir" in retired and "docs.notes" in retired
            and retired["memory.fallback_dir"] != retired["docs.notes"]):
        raise ValueError("旧 memory.fallback_dir 与 docs.notes 不匹配，先明确真实归属")
    return "".join(line for index, line in enumerate(lines) if index not in removed).encode("utf-8"), retired


def bound_update(root: Path, item: dict, label: str) -> tuple[Path, bytes, bytes]:
    """完整替换只能作用于已有安全 Markdown，并以显式摘要绑定当前实际前像。"""
    if not isinstance(item, dict) or set(item) != {"path", "before_sha256", "content"}:
        raise ValueError(f"{label} 每项只接受 path、before_sha256、content")
    path = relative(root, item["path"])
    before, content = read_file(path), item["content"]
    if path.suffix != ".md" or before is None:
        raise ValueError(f"{label} 只允许已有 Markdown，不创建目标或空主题：{path}")
    if (not isinstance(item["before_sha256"], str)
            or hashlib.sha256(before).hexdigest() != item["before_sha256"]):
        raise ValueError(f"{label} 前像摘要不匹配：{path}")
    if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError(f"{label} content 须为安全大小的非空完整正文")
    return path, before, content.encode("utf-8")


def migration_link_targets(body: str, label: str) -> list[str]:
    """收集普通链接和引用定义的实际目标，覆盖 full/collapsed/shortcut 共同来源。

    这里只做删除前的保守依赖检查，不重写或猜测标签归属。所有引用定义即使暂未
    使用也检查；窄语法无法无歧义解释时停止，不能当作“未发现旧链接”继续删源。
    """
    targets = LINK.findall(body)
    # 保守覆盖引用块/列表等容器中的定义，不凭缩进或代码外观跳过可能生效的依赖。
    definitions = re.finditer(r"\[(?:\\.|[^\[\]\\]){1,999}\]:[ \t]*([^\r\n]*)", body)
    for match in definitions:
        value = match[1].strip()
        if not value:
            # CommonMark 允许目的地址放在定义的下一行；不跨空段落搜寻猜测目标。
            following = body[match.end():].splitlines()
            value = following[1].strip() if len(following) > 1 else ""
        parsed = re.fullmatch(r'''(?:<([^<>\s]+)>|([^\s<>]+))(?:[ \t]+(?:"[^"\r\n]*"|'[^'\r\n]*'|\([^()\r\n]*\)))?''', value)
        if parsed is None:
            raise ValueError(f"无法安全解析引用式链接定义，保留原稿并明确引用目标：{label}")
        targets.append(parsed[1] or parsed[2])
    # 内联与引用定义统一且只归一一次，再交同一个 local_target 做外逃/链接校验；
    # 不能把 note&#115; 当成另一个目录，也不能双重解码而改变 Markdown 的实际目标。
    return [unescape(target) for target in targets]


def paired_html_inputs(root: Path, config: Path, updates: dict, inputs: dict) -> list[tuple]:
    """在项目锁内绑定已有配对 HTML 前像；无配对页时只绑定缺失状态，不创建页。

    页的工具记录、正文摘要和原稿归属沿用 requirement_html，手改/未知页面不能
    因迁移需要被覆盖。这里只采样，不持项目锁等待 Node；候选渲染在锁外完成。
    """
    from requirement_html import page_record, snapshot
    docs = parse_docs(config, body=notes_config_view(inputs[config])[0])
    plans, prototype = root / docs["plans"], root / docs["standards_root"] / "prototype"
    jobs = []
    for source, after in tuple(updates.items()):
        if source.suffix != ".md" or after is None or after == inputs[source]:
            continue
        target = source.with_suffix(".html")
        if target in inputs:
            raise ValueError(f"配对 HTML 与现有迁移输入重叠：{target}")
        old, target_identity = snapshot(target, required=False)
        inputs[target] = old
        if old is None:
            continue
        if not source.is_relative_to(plans):
            raise ValueError(f"已有同名 HTML 不属于 plans 派生页，保留原页并先明确处置：{target}")
        binding = {"project": str(root), "source": source.relative_to(root).as_posix(), "draft": False}
        page_record(old, binding)
        before, source_identity = snapshot(source)
        if before != inputs[source]:
            raise ValueError(f"配对 HTML 采样期间原稿变化：{source}")
        jobs.append((source, target, after, prototype, (before, source_identity), (old, target_identity)))
    return jobs


def plan_notes_migration(root: Path, config: Path, manifest: dict):
    """按显式多对多映射将必要结论归入既有主题/规范，原稿全文由恢复包保全。

    目标更新与引用更新均使用完整最终正文和实际前像摘要，不根据文件名、completed
    或 QA 字样推断归属与批准。仅显式 notes 清单精确覆盖旧目录后才退役配置和源文件。
    """
    fields = {"schema_version", "mode", "documents", "target_updates", "reference_updates"}
    if not isinstance(manifest, dict) or set(manifest) != fields or manifest.get("schema_version") != 2 or manifest.get("mode") != "notes":
        raise ValueError("notes 迁移须为 schema_version: 2、mode: notes 的完整显式映射")
    config_body = read_file(config)
    if config_body is None:
        raise ValueError("项目配置不存在")
    after_config, retired = notes_config_view(config_body)
    if not retired:
        raise ValueError("配置已退役 notes；不会再次迁移或从目录存在恢复写入口")
    if "docs.notes" not in retired:
        raise ValueError("缺少明确旧 docs.notes，不能从 fallback_dir 或目录存在猜测迁移归属")
    if "features" in parse_docs(config, body=config_body):
        raise ValueError("先完成显式 features 迁移，再迁移 notes；不会隐式删除 features 配置")
    errors = []
    docs = validate_docs(after_config.decode("utf-8").splitlines(), root, errors)
    if errors:
        raise ValueError("notes 退役后配置无效：" + "; ".join(errors))
    # relative 的末节点按安全普通文件检查；探针只核对目录祖先，绝不创建探针文件。
    notes = relative(root, retired["docs.notes"].rstrip("/") + "/__migration_parent_probe__.md").parent
    if notes.relative_to(root).parts[:1] != ("docs",) or notes == root / "docs":
        raise ValueError("旧 notes 须为 docs/ 下明确独立目录")
    # 不能让手工旧配置把 plans、规范或索引纳入源删除树；空/缺失旧目录也须显式空映射。
    for path in (root / docs[key] for key in docs):
        if notes == path or notes in path.parents or path in notes.parents:
            raise ValueError("旧 notes 不得与受控目录或索引重叠")
    actual_sources = legacy_files(notes) if notes.exists() or notes.is_symlink() else set()
    documents, targets, references = (manifest[key] for key in ("documents", "target_updates", "reference_updates"))
    if not all(isinstance(items, list) for items in (documents, targets, references)):
        raise ValueError("documents、target_updates、reference_updates 均须为显式列表")
    updates, inputs, target_paths = {}, {}, set()
    plans = root / docs["plans"]
    for item in targets:
        path, before, after = bound_update(root, item, "target_updates")
        if not (path.is_relative_to(plans) or canonical_standard_path(item["path"], docs["standards_root"])):
            raise ValueError(f"notes 目标只允许已有 plans 或直接项目规范叶：{path}")
        if path in target_paths:
            raise ValueError(f"重复目标更新：{path}")
        if path.is_relative_to(plans):
            prior = parse_plan(before.decode("utf-8"), str(path))
            future = parse_plan(after.decode("utf-8"), str(path))
            # 迁移是信息归属，不是验收：保留既有身份、阶段、版本与真实批准/验收依据；
            # 旧历史稿也不能仅凭 note 中的 completed/QA 文本升级成生命周期基线。
            def identity(document):
                return None if document is None else (document.topic_id, document.stage, document.modules,
                    document.task_level, document.accepted_version, document.approval_basis, document.acceptance_evidence)
            if identity(prior) != identity(future):
                raise ValueError(f"notes 迁移不能创造主题或改变阶段/验收身份：{path}")
        target_paths.add(path)
        inputs[path], updates[path] = before, after
    sources, referred_targets = set(), set()
    for item in documents:
        if not isinstance(item, dict) or set(item) != {"source", "source_sha256", "targets"}:
            raise ValueError("notes documents 每项只接受 source、source_sha256、targets")
        source = relative(root, item["source"])
        original = read_file(source)
        if source not in actual_sources or source in sources:
            raise ValueError(f"重复或目录外 notes 原稿：{source}")
        if original is None or hashlib.sha256(original).hexdigest() != item["source_sha256"]:
            raise ValueError(f"notes 原稿摘要不匹配：{source}")
        if not isinstance(item["targets"], list) or not item["targets"] or not all(isinstance(ref, str) for ref in item["targets"]):
            raise ValueError("每篇 notes 须有非空显式 targets 引用，可跨多个既有主题")
        for ref in item["targets"]:
            split = urlsplit(ref)
            if split.scheme or split.netloc or split.query:
                raise ValueError(f"notes 目标引用须为项目内既有 Markdown：{ref}")
            target = relative(root, split.path)
            if target not in target_paths:
                raise ValueError(f"notes 目标引用须有绑定前像的 target_updates：{ref}")
            # 片段仅作显式定位，不自动生成/猜测锚点；普通 Markdown 标题按去标点与空格
            # 形状核对，复杂自定义渲染锚点可直接使用该已有文件引用，或显式 HTML id。
            if split.fragment:
                body = updates[target].decode("utf-8")
                anchors = {re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
                           for heading in re.findall(r"(?m)^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", body)}
                anchors.update(re.findall(r"\b(?:id|name)=[\"']([^\"']+)[\"']", body))
                if unquote(split.fragment) not in anchors:
                    raise ValueError(f"notes 目标片段不存在，须由清单明确正文归属：{ref}")
            referred_targets.add(target)
        sources.add(source)
        inputs[source], updates[source] = original, None
    if sources != actual_sources or referred_targets != target_paths:
        raise ValueError("notes 映射须精确覆盖所有旧 Markdown 与所有目标更新；未知/缺失归属先停止")
    for item in references:
        path, before, after = bound_update(root, item, "reference_updates")
        if path in updates or path == config or path.is_relative_to(notes):
            raise ValueError(f"引用更新不能重复或与源/目标/配置重叠：{path}")
        inputs[path], updates[path] = before, after
    # 已知受控消费者和显式入站引用都必须清除旧链接；多目标去向由完整替换正文决定，
    # 不把一篇旧 note 的全部入站引用一律重定向到首个目标。未变读取也绑定到发布前复核。
    readers = {root / docs["project"], root / docs["standards"], *collect_plans(plans)}
    standard_root = root / docs["standards_root"]
    if standard_root.is_dir():
        readers.update(standard_root.glob("*.md"))
    readers.update(path for path, body in updates.items() if body is not None)
    for path in sorted(readers):
        before = inputs.get(path) if path in inputs else read_file(path)
        if before is None:
            continue
        inputs.setdefault(path, before)
        candidate = updates.get(path, before).decode("utf-8")
        for raw in migration_link_targets(candidate, str(path)):
            destination = local_target(root, path, raw)
            if destination is not None and destination.is_relative_to(notes):
                raise ValueError(f"仍有 notes 入站引用，须显式更新其所有者：{path}: {raw}")
    updates[config], inputs[config] = after_config, config_body
    return updates, inputs


def plan_migration(root: Path, config: Path, manifest: dict):
    """只读生成全部候选与前像；每个旧源必须有一对一显式主题归属。"""
    config_body = read_file(config)
    if config_body is None:
        raise ValueError("项目配置不存在")
    docs = parse_docs(config, body=config_body)
    if "features" not in docs:
        raise ValueError("配置已使用新模型；不会再次迁移或把旧目录恢复为运行时别名")
    lines = config_body.decode("utf-8").splitlines(keepends=True)
    entries = [index for index, line in enumerate(lines) if re.match(r"^  features:", line)]
    if len(entries) != 1:
        raise ValueError("旧 docs.features 须唯一，不能猜测配置归属")
    after_config = "".join(line for index, line in enumerate(lines) if index != entries[0]).encode("utf-8")
    errors = []
    # 原 schema1 可来自同时含 notes 的旧合法配置；只读视图允许分步迁移，实际发布
    # 仍保留 notes，必须由后续显式 notes 清单退役，默认安装/运行时从不接受这些键。
    validation_config, _retired = notes_config_view(after_config)
    new_docs = validate_docs(validation_config.decode("utf-8").splitlines(), root, errors)
    if errors:
        raise ValueError("新模型配置无效：" + "; ".join(errors))
    feature_path = Path(docs["features"].rstrip("/"))
    # 只为旧配置校验其目录归属，不把该值带入新运行时解析。
    if (feature_path.is_absolute() or feature_path.parts[:1] != ("docs",)
            or any(part.startswith(".") for part in feature_path.parts)):
        raise ValueError("旧 features 路径不安全")
    features = root / feature_path
    read_file(features / "__migration_parent_probe__.md")
    plans = root / new_docs["plans"]
    if features == plans or features in plans.parents or plans in features.parents:
        raise ValueError("features 和 plans 不能指向同一目录或相互嵌套")
    project = root / new_docs["project"]
    project_body = read_file(project)
    if project_body is None:
        raise ValueError("缺少真实 PROJECT 索引，无法核对旧基线归属")
    if not isinstance(manifest, dict) or set(manifest) - {"schema_version", "documents", "reference_updates"} or manifest.get("schema_version") != 1:
        raise ValueError("迁移输入须为 schema_version: 1 的显式映射")
    documents = manifest.get("documents")
    if not isinstance(documents, list):
        raise ValueError("documents 须为显式列表（旧目录确实为空时可为空）")
    mapping, inputs, templates, topic_ids = {}, {}, {}, set()
    existing_topics = {doc.topic_id.casefold() for path, body in collect_plans(plans).items()
                       if (doc := parse_plan(body, str(path))) is not None}
    for item in documents:
        if not isinstance(item, dict) or set(item) != {"source", "target", "source_sha256", "content"}:
            raise ValueError("每项只接受 source、target、source_sha256、content")
        source, target = relative(root, item["source"]), relative(root, item["target"])
        if not source.is_relative_to(features) or not target.is_relative_to(plans) or target.suffix != ".md":
            raise ValueError("源须在旧 features，目标须在新 plans 且为 .md")
        if source in mapping or target in mapping.values() or read_file(target) is not None:
            raise ValueError(f"主题／目标冲突，不覆盖或自动合并：{target}")
        if read_file(target.with_suffix(".html")) is not None:
            raise ValueError(f"目标派生 HTML 已存在，先明确归属：{target}")
        original = read_file(source)
        if original is None or hashlib.sha256(original).hexdigest() != item["source_sha256"]:
            raise ValueError(f"旧源摘要不匹配：{source}")
        content = item["content"]
        if not isinstance(content, str) or content.count(PLACEHOLDER) != 1:
            raise ValueError("content 须显式使用一次 {{原文}}，不能丢弃旧正文")
        document = parse_plan(content, str(target), required=True)
        topic = document.topic_id.casefold()
        if topic in topic_ids or topic in existing_topics:
            raise ValueError(f"主题 ID 已存在，禁止猜测合并：{document.topic_id}")
        topic_ids.add(topic)
        mapping[source], inputs[source], templates[source] = target, original, content
    if set(mapping) != legacy_files(features):
        raise ValueError("映射必须精确覆盖旧目录的所有 Markdown；缺失／额外主题关系先停止")
    indexed = {local_target(root, project, raw) for raw in LINK.findall(project_body.decode("utf-8"))}
    updates = {}
    for source, target in mapping.items():
        original = rewrite_links(inputs[source].decode("utf-8"), root, source, target, mapping)
        template = parse_plan(templates[source], str(target), required=True)
        # 模板引用按目标位置书写；原文按原位置重定位，只有原文占位被替换。
        content = templates[source].replace(PLACEHOLDER, original)
        document = parse_plan(content, str(target), required=True)
        prove_baseline(original, document, template, indexed=source in indexed, label=str(source))
        updates[target], inputs[target], updates[source] = content.encode("utf-8"), None, None
    references = manifest.get("reference_updates", [])
    if not isinstance(references, list) or not all(isinstance(path, str) for path in references):
        raise ValueError("reference_updates 须为明确的项目内 Markdown 路径列表")
    indexes = {project, root / new_docs["standards"], *(relative(root, path) for path in references)}
    if set(mapping) & indexes or set(mapping.values()) & indexes or config in indexes:
        raise ValueError("引用更新路径不能与源、目标或配置重叠")
    for path in sorted(indexes):
        before = read_file(path)
        if before is None:
            continue
        if path.suffix != ".md":
            raise ValueError("引用更新只处理明确的 Markdown 文档")
        after = rewrite_links(before.decode("utf-8"), root, path, path, mapping, only_mapped=True).encode("utf-8")
        if after != before:
            updates[path], inputs[path] = after, before
    updates[config], inputs[config] = after_config, config_body
    return updates, inputs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mapping", type=Path)
    source.add_argument("--restore", type=Path, help="按单次恢复副本预检；加 --apply 才恢复原字节")
    parser.add_argument("--recovery", type=Path, help="缺少 Git 原件时使用的单份恢复副本，默认在映射同目录 migration-recovery.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--request-id", help="涉及已有配对 HTML 时，用当前请求 scratch 预渲染候选；不先发布 Markdown")
    args = parser.parse_args(argv)
    try:
        if args.project.is_symlink() or not args.project.is_dir():
            raise ValueError("项目必须是已有真实目录")
        root = args.project.resolve(strict=True)
        installed = root / ".agent-workflow/project.yaml"
        config = installed if installed.exists() or installed.is_symlink() else root / "project.yaml"
        if args.restore is not None and args.recovery is not None:
            raise ValueError("--restore 不接受另一个 --recovery 路径")
        mapping = (args.mapping or args.restore).absolute()
        manifest_body = read_file(mapping)
        if manifest_body is None:
            raise ValueError("显式映射不存在")
        if args.restore is not None and os.name != "nt" and stat.S_IMODE(mapping.lstat().st_mode) != 0o600:
            raise ValueError("恢复副本须保持私有权限，保留现状并停止")
        manifest = json.loads(manifest_body)
        protection = None
        html_jobs = []
        with project_install_lock(root):
            if args.restore is not None:
                updates, inputs, modes = recovery_changes(root, manifest)
            else:
                notes_mode = isinstance(manifest, dict) and manifest.get("mode") == "notes"
                updates, inputs = (plan_notes_migration if notes_mode else plan_migration)(root, config, manifest)
                # 移动同一私有原稿时保留其原权限，不因新增目标默认权限扩大可读范围。
                modes = {} if notes_mode else {
                    root / item["target"]: stat.S_IMODE((root / item["source"]).lstat().st_mode)
                    for item in manifest["documents"]}
                if notes_mode:
                    html_jobs = paired_html_inputs(root, config, updates, inputs)
            input_modes = {path: stat.S_IMODE(path.lstat().st_mode) for path, body in inputs.items() if body is not None}
            if mapping in updates:
                raise ValueError("显式映射文件不能同时是迁移写入或删除目标")
        if html_jobs:
            if not args.request_id:
                raise ValueError("已有配对 HTML 需要 --request-id，在当前请求 scratch 完成候选渲染后才可删源")
            from requirement_html import render_candidate, snapshot
            for source, target, after, prototype, source_before, target_before in html_jobs:
                page = render_candidate(root, source, after, source, prototype, args.request_id)
                if snapshot(source) != source_before or snapshot(target) != target_before:
                    raise ValueError("候选渲染期间原稿或 HTML 并发变化，保留原件并停止")
                updates[target] = page
            # 配对 HTML 的最终条件发布也先于任何源删除；即使在候选完成后、
            # Markdown 发布期间发生页面编辑，HTML 前像冲突也能在删源前停止。
            updates = {**{path: body for path, body in updates.items() if body is not None},
                       **{path: body for path, body in updates.items() if body is None}}
        if args.apply:
            # 恢复文件可以就在项目根；先释放规划锁，再用现有条件发布取得其目录锁，
            # 防止同目录锁递归冲突。随后重新持项目锁，复核同一批原字节／权限再执行。
            if args.restore is None:
                recovery = args.recovery.absolute() if args.recovery else mapping.with_name("migration-recovery.json")
                if notes_mode:
                    _view, retired = notes_config_view(inputs[config])
                    notes = root / retired["docs.notes"]
                    if recovery.is_relative_to(notes):
                        raise ValueError("唯一恢复包不能保存在待退役 notes 源目录中")
                protection = preserve_originals(root, recovery, updates, inputs, modes, mapping, input_modes,
                                                raw_snapshot=notes_mode)
            from apply_antigravity_setup import publish_document_changes

            def validate_after():
                if args.restore is not None:
                    if any(read_file(path) != body for path, body in updates.items()):
                        raise ValueError("恢复后原字节校验失败")
                    return
                # features 的分步兼容仅影响本次验证输入，磁盘旧 notes 键保持原样；
                # notes 完成后与普通运行时一样使用真实配置，不留下永久兼容开关。
                validation_body = None if notes_mode else notes_config_view(updates[config])[0]
                errors = validate(config, root, body=validation_body)
                if errors:
                    raise ValueError("迁移结果校验失败：" + "; ".join(errors))
                if html_jobs:
                    from requirement_html import process as check_html
                    for source, *_rest in html_jobs:
                        check_html("check", root, source.relative_to(root).as_posix())
                if notes_mode and (notes.exists() or notes.is_symlink()) and legacy_files(notes):
                    raise ValueError("发布期间 notes 新增未映射原稿，停止并回滚本次迁移")

            with project_install_lock(root):
                if read_file(mapping) != manifest_body or any(
                        read_file(path) != body or (body is not None and stat.S_IMODE(path.lstat().st_mode) != input_modes[path])
                        for path, body in inputs.items()):
                    raise ValueError("原件保护后迁移输入／权限变化，保留原件并停止")
                if args.restore is None and notes_mode:
                    # 锁释放期间可能新建未映射原稿/资产；只核对旧文件前像不足以证明
                    # 整个源目录仍已覆盖，必须再次拒绝新增或变型节点后才退役入口。
                    actual = legacy_files(notes) if notes.exists() or notes.is_symlink() else set()
                    expected = {root / item["source"] for item in manifest["documents"]}
                    if actual != expected:
                        raise ValueError("原件保护后 notes 目录内容变化，保留原件并停止")
                publish_document_changes(root, updates, inputs, validate_after, desired_modes=modes)
        print(json.dumps({"status": ("restored" if args.restore is not None else "migrated") if args.apply else "checked",
            "recovery": protection, "changes": [
            {"path": str(path.relative_to(root)), "action": "delete" if body is None else "write",
             "sha256": None if body is None else hashlib.sha256(body).hexdigest()}
            for path, body in updates.items()]}, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
