#!/usr/bin/env python3
"""校验 PROJECT 的 plans 已验收基线与独立 STANDARDS 规范入口。"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import re
import hashlib
import os
import stat
import sys
from pathlib import Path
from urllib.parse import unquote

sys.dont_write_bytecode = True

try:
    from .standard_paths import BUILTIN_STANDARD_SOURCES, canonical_standard_path, standard_domain
    from lib.skills.business_confirmation_policy import read_instruction_contract
    from lib.project.validate_project_config import section_lines, strip_inline_comment, validate_docs
    from lib.documents.plan_documents import validate_plan_index
    from .runtime_pins import PLUGIN_ENV, read_builtin_source, record_binding
except ImportError:
    from standard_paths import BUILTIN_STANDARD_SOURCES, canonical_standard_path, standard_domain
    from lib.skills.business_confirmation_policy import read_instruction_contract
    from lib.project.validate_project_config import section_lines, strip_inline_comment, validate_docs  # type: ignore[no-redef]
    from lib.documents.plan_documents import validate_plan_index
    from runtime_pins import PLUGIN_ENV, read_builtin_source, record_binding


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
STANDARD_RULE_RE = re.compile(r"\[([a-z0-9][a-z0-9._-]*)\]\s*\[(hard|advisory)\]")
RULE_DEFINITION_RE = re.compile(
    r"(?m)(?:^\s*(?:[-*+]\s+)?`?|\|\s*`?|(?=\[(?:eng|des)-))"
    r"\[([a-z0-9][a-z0-9._-]*)\]\s*\[([^\]\n]*)\]"
)


def validate_rule_definitions(body: str, label: str, errors: list[str]) -> None:
    """拒绝非法严重性，避免改过的规则被当成无规则说明而绕过 ID 冲突校验。

    检查行首/表格定义，以及正文中既有eng/des规则的双标签形态，防止把平台规则
    移到表格或说明中并改severity来躲过冲突。单独提及ID不构成规则定义。
    """
    for rule_id, severity in RULE_DEFINITION_RE.findall(body):
        if severity not in {"hard", "advisory"}:
            errors.append(f"invalid standards severity {severity!r} for {rule_id}: {label}")


def read_builtin_standard_sources(pack_root: Path, *, binding: dict | None = None) -> dict[str, str]:
    """安全读取固定的三份内置权威，供安装候选视图和最终项目校验共同消费。

    返回源包相对路径到原正文的映射，不扫描个人 Skill 或宿主分发目录；复用现有
    安全读取，保留祖先/文件类型、硬链接、符号链接及 UTF-8 检查。这里不写文件。
    """
    sources: dict[str, str] = {}
    owners: dict[str, str] = {}
    errors: list[str] = []
    for relative, domain in BUILTIN_STANDARD_SOURCES.items():
        # 插件和显式 pin 都只信各自固定来源；旧 source 调用仍走原安全本地读取。
        body = (read_builtin_source(binding, relative).decode("utf-8")
                if binding is not None or PLUGIN_ENV in os.environ
                else read_instruction_contract(pack_root, relative))
        validate_rule_definitions(body, relative, errors)
        if re.findall(r"(?im)^- Domain: (engineering|design)\s*$", body) != [domain]:
            errors.append(f"builtin standards source must declare Domain: {domain}: {relative}")
        matches = STANDARD_RULE_RE.findall(body)
        if not matches:
            errors.append(f"builtin standards source has no stable severity-tagged rule: {relative}")
        for rule_id, _severity in matches:
            previous = owners.get(rule_id)
            if previous is not None:
                errors.append(f"duplicate standards rule ID {rule_id}: {previous} and {relative}")
            else:
                owners[rule_id] = relative
        sources[relative] = body
    if errors:
        raise ValueError("; ".join(errors))
    return sources


def builtin_standard_rule_catalog(pack_root: Path, *, binding: dict | None = None) -> dict[str, dict[str, object]]:
    """从同一次安全读取取得内置规则元数据，任务图与 QA 共用同一字节/ID/严重性事实。"""
    return {
        path: {
            "domain": BUILTIN_STANDARD_SOURCES[path],
            "content_fingerprint": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "rules": dict(STANDARD_RULE_RE.findall(body)),
        }
        for path, body in read_builtin_standard_sources(pack_root, binding=binding).items()
    }


def parse_docs(config: Path, *, body: bytes | None = None) -> dict[str, str]:
    """只解析受控 docs 段；完整路径安全性仍由 validate_project_config 负责。"""

    # 迁移规划可绑定已经安全采样的配置字节，避免再次读取时把并发配置误作同一输入。
    lines = (config.read_bytes() if body is None else body).decode("utf-8").splitlines()
    result: dict[str, str] = {}
    for raw in section_lines(lines, "docs"):
        match = re.match(r"^  ([A-Za-z0-9_]+):\s*(.*?)\s*$", raw)
        if match:
            result[match.group(1)] = strip_inline_comment(match.group(2)).strip("\"'")
    return result


def read_single_link_regular(path: Path, label: str, errors: list[str]) -> str | None:
    """拒绝符号链接和硬链接，避免校验时把项目外内容当成权威文档。"""

    try:
        info = path.lstat()
    except FileNotFoundError:
        errors.append(f"missing {label}: {path}")
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        errors.append(f"{label} must be a single-link regular file: {path}")
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read UTF-8 {label} {path}: {exc}")
        return None


def normalized_link_target(project_doc: Path, raw: str) -> Path | None:
    """解析普通 Markdown 文件链接；外部 URL、页内锚点和带标题写法不进入功能校验。"""

    candidate = raw.strip()
    if candidate.startswith("<") and ">" in candidate:
        candidate = candidate[1 : candidate.index(">")]
    else:
        candidate = candidate.split(maxsplit=1)[0]
    candidate = unquote(candidate.split("#", 1)[0].split("?", 1)[0])
    if not candidate or candidate.startswith("#") or "://" in candidate:
        return None
    path = Path(candidate)
    if path.is_absolute():
        return path.resolve()
    return (project_doc.parent / path).resolve()


def collect_standard_leaves(root: Path, errors: list[str]) -> dict[Path, str]:
    """安全遍历规范目录，并返回所有 Markdown 叶文档。

    规范是所有实现 Agent 与 QA 的强制输入，所以目录中任何符号链接、特殊节点或
    多硬链接文件都可能把项目外内容伪装成规则权威；这里逐层 ``lstat``，不跟随它们。
    ``prototype`` 是 HTML/CSS 设计证据，不是规范叶；完整节点与依赖安全由
    ``validate_prototype_workspace.py`` 独立负责。主题方案归 plans，
    不再以 references 子目录混入规范树。
    """

    leaves: dict[Path, str] = {}
    prototype_root = root / "prototype"

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            errors.append(f"cannot inspect standards directory {directory}: {exc}")
            return
        for entry in entries:
            path = Path(entry.path)
            try:
                info = path.lstat()
            except OSError as exc:
                errors.append(f"cannot inspect standards entry {path}: {exc}")
                continue
            if stat.S_ISLNK(info.st_mode):
                errors.append(f"standards tree must not contain symlinks: {path}")
            elif stat.S_ISDIR(info.st_mode):
                if path != prototype_root:
                    errors.append(f"standards leaves must be shallow; migrate nested directory: {path}")
            elif stat.S_ISREG(info.st_mode) and path.suffix == ".md":
                body = read_single_link_regular(path, "standards leaf", errors)
                if body is not None:
                    validate_rule_definitions(body, str(path), errors)
                    leaves[path.resolve()] = body
            else:
                errors.append(f"standards tree contains unsupported entry: {path}")

    visit(root)
    return leaves


def validate(config: Path, project_root: Path, *, body: bytes | None = None,
             binding: dict | None = None) -> list[str]:
    """检查语义边界，不对 PROJECT.md 设置行数或字节数限制。

    显式迁移可传入已绑定前像的候选配置正文；普通运行时仍从真实配置读取并拒绝
    所有退役键。该参数只替换配置输入，不改变对磁盘中主题与规范的严格校验。
    """

    errors: list[str] = []
    root = project_root.resolve()
    try:
        # 此入口没有任务包参数，中央 helper 由桥逐进程传入固定 pin；source 默认兼容。
        selected_binding = record_binding({"runtime_binding": binding} if binding is not None else {},
                                          root=root, initialize=True)
        if selected_binding is not None and config.absolute() != root / ".agent-workflow/project.yaml":
            raise ValueError("中央文档校验只能读取本项目 .agent-workflow/project.yaml")
        if PLUGIN_ENV in os.environ:
            # 适配器必须由调用方指向实际项目文件，不能用插件附带配置充当业务事实。
            if ".." in config.parts or not config.absolute().is_relative_to(root):
                raise ValueError("插件文档校验必须显式读取实际项目中的适配器")
            if body is None:
                from lib.hosts.claude_instructions import read_file
                body = read_file(config.absolute())
                if body is None:
                    raise ValueError("实际项目适配器不存在")
    except (OSError, ValueError) as exc:
        return [f"invalid runtime binding: {exc}"]
    text = config.read_text(encoding="utf-8") if body is None else body.decode("utf-8")
    docs = validate_docs(text.splitlines(), root, errors)
    if errors:
        return errors
    standards_value = docs.get("standards")
    standards_root_value = docs.get("standards_root")
    project_value = docs.get("project")
    plans_value = docs.get("plans")
    if not standards_value or not standards_root_value or not project_value or not plans_value:
        return ["docs.standards, docs.standards_root, docs.project and docs.plans are required"]

    root = project_root.resolve()
    standards_path = root / standards_value
    standards_root_path = root / standards_root_value
    project_path = root / project_value
    plans_path = root / plans_value
    standards_doc = standards_path.resolve()
    standards_root = standards_root_path.resolve()
    project_doc = project_path.resolve()
    plans_root = plans_path.resolve()
    if not all(
        path.is_relative_to(root)
        for path in (standards_doc, standards_root, project_doc, plans_root)
    ):
        return ["controlled document paths must stay within project root"]
    if standards_doc.is_relative_to(standards_root):
        errors.append("docs.standards must stay outside docs.standards_root")

    # 本次升级明确不保留旧 STATUS/SPEC 权威层。这里检查的是固定遗留位置，
    # 即使 PROJECT.md 没有链接它们，也必须移除，防止 Agent 或人工搜索时继续
    # 把旧文件误当成第二份当前事实。历史内容由 Git 和迁移后的主题文档保留。
    for legacy_name in ("STATUS.md", "SPEC.md", "ENGINEERING.md", "DESIGN_SYSTEM.md"):
        legacy_path = root / "docs" / legacy_name
        try:
            legacy_path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"cannot inspect unsupported legacy authority {legacy_path}: {exc}")
        else:
            errors.append(
                f"unsupported legacy authority must be removed after direct upgrade: {legacy_path}"
            )

    # 使用未 resolve 的配置路径做 lstat，才能真正识别最后一级符号链接，而不是在
    # 跟随链接后把项目外文件误判为普通受控文档。
    # 项目没有实际规则时不制造索引/目录；配置路径仍保留以约束后续项目写入。
    try:
        standards_path.lstat()
    except FileNotFoundError:
        standards_body = None
    else:
        standards_body = read_single_link_regular(standards_path, "standards index", errors)
    project_body = read_single_link_regular(project_path, "project index", errors)
    try:
        standards_root_info = standards_root_path.lstat()
    except FileNotFoundError:
        standards_root_info = None
    if standards_root_info is not None and (stat.S_ISLNK(standards_root_info.st_mode) or not stat.S_ISDIR(
        standards_root_info.st_mode
    )):
        errors.append(f"standards root must be a real directory: {standards_root}")
        standards_documents = {}
    else:
        standards_documents = collect_standard_leaves(standards_root_path, errors) if standards_root_info else {}
    # 迁移后残留的项目说明需要完整保留，但无规则的 Markdown 不是规范 authority。
    # 所有文档仍经过安全节点/非法定义检查；只有真实规则叶要求 domain 和索引全覆盖。
    standards_leaves = {path: body for path, body in standards_documents.items() if STANDARD_RULE_RE.search(body)}
    if standards_leaves and standards_body is None:
        errors.append(f"project standards leaves require a standards index: {standards_doc}")
    rule_owners: dict[str, Path] = {}
    try:
        for relative, body in read_builtin_standard_sources(
                Path(__file__).resolve().parents[1], binding=selected_binding).items():
            for rule_id, _severity in STANDARD_RULE_RE.findall(body):
                rule_owners[rule_id] = Path(relative)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"invalid builtin standards sources: {exc}")
    for path, body in standards_leaves.items():
        # 显式类型与路径类型一致，避免在扁平目录中偷换工程/设计权限。
        declared_domains = re.findall(r"(?im)^- Domain: (engineering|design)\s*$", body)
        expected_domain = standard_domain(str(path), str(standards_root))
        if not canonical_standard_path(str(path), str(standards_root)) or declared_domains != [expected_domain]:
            errors.append(f"standards leaf must declare Domain: {expected_domain}: {path}")
        matches = STANDARD_RULE_RE.findall(body)
        if not matches:
            errors.append(f"standards leaf has no stable severity-tagged rule: {path}")
            continue
        for rule_id, _severity in matches:
            previous = rule_owners.get(rule_id)
            if previous is not None:
                errors.append(f"duplicate standards rule ID {rule_id}: {previous} and {path}")
            else:
                rule_owners[rule_id] = path

    if standards_body is not None:
        if STANDARD_RULE_RE.search(standards_body):
            errors.append("STANDARDS.md is an index and must not define leaf rules")
        linked_leaves: set[Path] = set()
        for raw in MARKDOWN_LINK_RE.findall(standards_body):
            target = normalized_link_target(standards_doc, raw)
            if target is None or not target.is_relative_to(standards_root):
                continue
            if target == standards_root / "prototype" or target.is_relative_to(standards_root / "prototype"):
                # 原型目录/页面是证据链接，不要求有 Markdown 规则 ID。
                if not target.exists():
                    errors.append(f"STANDARDS.md links missing prototype evidence: {target}")
                continue
            if target not in standards_documents:
                errors.append(f"STANDARDS.md links missing or non-regular standards leaf: {target}")
            elif target in standards_leaves:
                linked_leaves.add(target)
        for path in sorted(set(standards_leaves) - linked_leaves):
            errors.append(f"standards leaf is not linked from STANDARDS.md: {path}")
    if project_body is None:
        return errors
    # 固定遗留权威不能通过唯一入口重新成为事实；无索引旧计划则保留历史边界。
    for legacy in ("STATUS.md", "SPEC.md", "ENGINEERING.md", "DESIGN_SYSTEM.md"):
        if legacy in project_body:
            errors.append(f"PROJECT.md must not reference legacy authority {legacy}")
    errors.extend(validate_plan_index(root, plans_path, project_path, project_body))
    return errors


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate_project_docs.py PROJECT_YAML PROJECT_ROOT", file=sys.stderr)
        return 2
    errors = validate(Path(sys.argv[1]), Path(sys.argv[2]))
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print("[OK] PROJECT/plans baseline and STANDARDS directory contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
