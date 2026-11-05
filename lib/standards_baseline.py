#!/usr/bin/env python3
"""规范迁移计划与限定于规范创建/删除快照的精确恢复原语。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import tempfile
from typing import Mapping
from urllib.parse import quote

try:
    from .project_discovery import ProjectProfile
    from .claude_instructions import read_file
    from .validate_project_config import parse_project_name
    from .platform_fs import os as fs, publish_exclusive
except ImportError:
    from project_discovery import ProjectProfile
    from claude_instructions import read_file
    from validate_project_config import parse_project_name
    from platform_fs import os as fs, publish_exclusive

COMMON_BEGIN = b"<!-- agent-workflow:general-common:begin -->"
COMMON_END = b"<!-- agent-workflow:general-common:end -->"
# 受管标记只能定位候选区，不能证明其内容仍属于工作流。只有四个已提交历史版本
# 的完整区块指纹可授权整区删除；正文、无 ID 注释、续段和表格改动都会使证明失效。
LEGACY_COMMON_BLOCK_HASHES = frozenset({
    "bbb132631f610df0278e82e70185c0d37c7692f4200a038626a3a77ad30b6b40",
    "6b95913ab30f370206303305c0c265d8cd29499c8c2f02f4a0cf3d93572b2e95",
    "060243dd76ceffde4bcdb2d759feba14bc14fb1a1fd33d26ee3e18b2d1a0c71e",
    "8fbef748d8b9218a988e644d49343721c5f657ce8213207ea84b20acfaaefb22",
})
# 已提交历史模板的指纹仅用于归属证明，不保留第二份规则正文；实际规则从 Skill 读取。
LEGACY_TEMPLATE_HASHES = {
    "GENERAL.md": frozenset({
        "9b6677a35d453eddbd7f0a7c26d810b47645ada418b3dceee0dfd4dffcb9df86",
        "bdc3f09082e94f5a0f8fb930dae8e628edb651645f5e97052d95293188ce02c6",
        "ae73f00772dfe6f7e1922145a8f0c99f6d308ecc2aa27ea44012ad5751ec36f9",
        "62b1527a50d7f2fd9883cd7022f3878d3c402c719eac9e371ed41fc584660b43",
    }),
    "UPSTREAM.md": frozenset({"5a52ff35788f790174eb79fb5775dea56870050da8142ebce02250fd8234067e"}),
    "DESIGN_FOUNDATIONS.md": frozenset({"9bdf9baaf72b396fd86107b95a5b0b85de4336aa5278768ccb65ea99ece59c87"}),
    "DESIGN_COMPONENTS.md": frozenset({"76759ac10ae0342e0de6bd162a422fa5c06b83aa7fbc85268794c64754dfdbf9"}),
    "STANDARDS.md": frozenset({
        "f56cf0044d17a7c60ec0c2815879ffda537492d590e387077824a6bf9ba53097",
        "f936d4cd96c46f737565b32ab9f612faa9a310ae3ad5c5ed46bc7a94ed2aef00",
    }),
}
# 85f84a70705550fd47feb68eed544c1f9f9c9b9d 中真实旧条目的完整摘要，只证明历史归属。
# 英文化会改变当前正文，因此不能只与当前条目比较；也不能凭 ID、首句或相似度删除。
# 摘要按既有规则仅统一 CRLF 并移除条目末尾换行，包含完整 ID、严重性、续段与附表。
# 任何用户追加内容都会产生不同摘要；生产不保存第二份旧规则正文，原整模板/区块摘要不变。
LEGACY_BUILTIN_ITEM_HASHES = frozenset({
    # platforms/shared/skills/xy-code-standards/references/rules.md；原始来源 SHA256 5a022280b3800b2db40056441398dce3db4adb587e250aa0d10bf50a5d6db509。
    "d8c29f42d287dd492a888ad2c43c3b14ec6efd08c3cfbea2d6812ee049679ef3",  # eng-verification-001
    "2061b13fa2defd3d62bb45bc57bf12354707e6026ac1cf2a0a1381a63bf93fd5",  # eng-verification-002
    "69231a5d19b2bd369c465c1445cf0c7a57318fbf7f4b5a529f1b471f8fe844cf",  # eng-verification-003
    "bac10e43631e3b8e3103f3bfd804cba2be9ca087d00efd1c13b1203e95036f2a",  # eng-secrets-001
    "08b504c9379641b12491494dd455ca374702b1fb4a21a5ccd8b621b2acd01b91",  # eng-common-001
    "ac6fae3068995d814edba60ab97908309ddb47bb881ddc808e0844fadd5b4dd5",  # eng-common-006
    "b5ae8198ed02bc93a34c02c3f71d4d3680b3d65978247c568db30154fda39d6b",  # eng-common-007
    "f00e96bdbe3fb45cfdc4023c6a1c042e43f1dcb6292b09455062bff49456de4c",  # eng-common-014
    "bf23e6d8dec15ae4ac6aad84cdf019211f92008fca488628e54beed5951834ae",  # eng-common-002
    "21f44ceefcf3d1a35b582429d22bbfad5e269570474cd931d17fcd2319254b2a",  # eng-common-008
    "baf20e6b0a7b1f4379e10256dda0d9690a3ca05f39d6e96cee79664a0112f08c",  # eng-common-010
    "b99ba65053db24fd50d7f28703869c0a07fb1c543d723fdd793fd11d61e4aaeb",  # eng-common-011
    "3e57415d099d20edd5d00b368facc4c6c90da76b02201894667cbd5f9bfb3b53",  # eng-common-012
    "ee5b7587aece8ea282fe0ccba7a2b510384c1a760f20b349b52546c098c442db",  # eng-common-013
    "e13132c72a7d2c3a2874761d3877bb44d31d9f3c9a8d5d610838f3aea2c2cc34",  # eng-common-021
    "9b9600fab1de4589dc9033829868f409645406599978e346eeddf990e84f49a4",  # eng-common-022
    "90ddda5604df305120af28c9d22aec6221be819b3ea5c1b786ca284453adb2ef",  # eng-common-023
    "17352b2d7c20264ec977a2b4cf136db32bac1e7b33ffec105f8a3fcaefb07f45",  # eng-common-015
    "a8dcbda78e799dec1906dd22113cdab10ef82f5c4b18e3ae5b2fd3b16ce2c869",  # eng-common-016
    "30001dc705154ceffe35a8122ef2ecf0d33d8920e666917a0f84a72b63bb87fb",  # eng-common-017
    "7b11ea4b5314d9f970d4f87d1d2aab46c5eff653ac6e071a1ee1aab5f4a8dac7",  # eng-common-018
    "142ab0eabbb10b442d4981107d807a5c1b72f738dacd1936040bd540343d53dc",  # eng-common-024
    "a276aaecdd124f450fe12ec3a69173ef155e3e25906f93f126aacde883516222",  # eng-common-025
    "4e68895e65e041158236a215944cb8c8a7264a1e7ab72868ca89694c847aa417",  # eng-common-026
    "358c357698222ce18c4b80a2b7c72bb9839a70f96ca18a208eec2ad2ed49446a",  # eng-common-027
    "d1f533d0ab4395257b5149f5dba7b005c92de3e19dab627df5b6bcd25268408e",  # eng-common-028
    "0335e205c7bc7f4724f71d927e8f2cd318aeda9b4656cc4f2ce3a7a0d3a88019",  # eng-common-029
    "d03f72b93e40bb6c69b8eab795983288153c6f5f9998b66767e663641471b63f",  # eng-common-003
    "0d9cf4b87ad9d2fe0fa0974dbdfa63b5bca7b6789f63b7bccf147221be0327c1",  # eng-common-004
    "36231c391221a4a218c26325654bb2f5e4a71172efbe2f1504c16612f66890ea",  # eng-common-005
    "cc4551d78365ee88e4069c2e3e7ebedbdc886aa19187d0a75ead476b223c4fe7",  # eng-common-009
    "27e62dcca2895b46e32901e3a3d29c0a11c81f1b444babd533302ec31dd721ac",  # eng-common-019
    "5ccfa58e9f64379df51300af524237345ca7e0593102788f9fa0defe24626903",  # eng-common-020
    "4f4a72c9f63b2df5880fba9b4eecb09bc727505473deca4353b7292384cf8edf",  # eng-common-030
    "64d664febe4a0968d0369372a2af5607d224831957201b05279986db80e731a2",  # eng-upstream-001
    "ed63657a0d1aab46eb3f911e264f4b17d53776a80ce51299e1a551dc325538a5",  # eng-upstream-002
    # platforms/shared/skills/xy-ui-design/references/foundations-rules.md；原始来源 SHA256 717904828357ae90b1ef8036d8e203c3496ee61b09af156b93165b7b9f4c514e。
    "06bd2bf165cc442120c4e4e75bdbab1e2ba1b68601180b753834bc4f8babbe02",  # des-baseline-001
    "347ca181fc210934bde4153cd19875c736c7f0d049838e00896528ce1a0e0bdd",  # des-baseline-002
    "01063cb76058969a42edbb914c1985fe301920bafab73e70edf917d9a8856bcd",  # des-accessibility-001
    "9f20941ef5a95864c533fbf1759cfa8c18bd033d4d45a1e826efae0d1a9ca5f2",  # des-accessibility-002
    "dd04f5e27055cc372b6f1cd8e488e16d97d009a232541a8c557a695c19f344cc",  # des-accessibility-003
    "7338cdee59ef794ed7b8d3466db8165da939e39702025edb6dde5c464c0fc384",  # des-accessibility-004
    "8d6b4184079cf443ae0a477b582688d60f9883f9ddead43918f0495c47202708",  # des-platform-001
    "78cebe8ae1f0cc81af44684ff784a01f975f8bdcd7236512826af03c0f2d4b80",  # des-token-001
    "434defe5a4efa524e3ea238b39ccd9e5555fc69a2124a6cd372a01d019e36449",  # des-token-002
    "73a89ccb429e508e085b2d9e17af278a7cc59fd0ffea63a59bb68a2c8669bf1e",  # des-token-003
    "baadf2286fd7dca75c7ee7c013a3feff479823ac5e9d06439a558096812efc32",  # des-token-004
    "94b83bf9e8ed6fe5a807a981721e7b10264f813bb6a796135ef2c14f8460f4cc",  # des-scale-001
    "022ba836fb96c5b9e9c49630556562e6c397130eccf4e85d0ebfe62868bf38e6",  # des-motion-001
    "db40f3a77b7850eb942d0e1a24299b70b025f4fbb5086e14c49e8090425ec7eb",  # des-prototype-001
    "670de71cdaafe47a3b03568bc67232b02f9ea3a062fb5bdf0ae734aae8363b32",  # des-meaning-001
    # platforms/shared/skills/xy-ui-design/references/components-rules.md；原始来源 SHA256 15ee6027d37df8b89fe02de037897188f43e4b1f4ab6340dca8f340467df291a。
    "8f73995da9ebeb62265b122927012b85b8d7a00fa8bda0d57dcdf6696d50b744",  # des-component-001
    "1601558fc3d343b55061885e47bf88949c7d351fa978135d4a193113f6fb99de",  # des-component-002
    "790c84898c802e8c4b19603d73d04b936296484ba73834013b7b1440ac08d977",  # des-component-003
    "fd51b933ee05b322a4e3e056cd23c119e3f722f195b26c2b1d75450d06fc2265",  # des-dialog-001
    "0529d05586dd03acc3a7a23c200c94e864513c53464dbfb0daa077d7b18d0bfd",  # des-dialog-002
    "42c80f79a966ad79c2db4e57022e8ca264f798d0c7524214d46568c9073295c8",  # des-dialog-003
    "3261af26992f269b60662489814aedf1ee479074461a82b19886334126d1ff95",  # des-dialog-004
    "684530b898aaf7564acafa495d71f03c24a0a596e0f7b06a96ebca74d72c1218",  # des-segment-001
    "e3e201d0059f0e6edecd8ea58daa4e0d5d1196c7b51452e749a12ca5a4f0b6b6",  # des-segment-002
    "e5f9f8479b17077c9c7eb9aac6c0b8a92604abfc904e8727e7c3fb9cdfa28fa3",  # des-segment-003
    "656a784017d137b18dc660e33b6cc3d02fee43b0ae6641cf513720d0c749ea9c",  # des-control-001
    "19494312dc1fec9bd88214dcc29ae0c2b4e7ea9982e539b6d841ca4dc1725b73",  # des-form-001
    "d980d53c35ddd970c2b297a2ef5df7507acb5d8d2bf4ce940870bafe05c295e7",  # des-data-001
    "e7d24e6273f81264c0e5000cfa1ffdeaee65dec5aede7eec850fcef379df2efb",  # des-state-001
    "69a937c552e246fa6108d2c080a70340ebd3719e7c6255871dc755c10d195de8",  # des-state-002
    "ebcc5ed9f8b763b939b438a90dad0903a75f7e9af7ad03e564dbf03685586bd5",  # des-responsive-001
    "8841c5cb593c7cddec330a761b7b5a92be6fdc79382d7baccaba31b91da939dd",  # des-responsive-002
    "2c183b4cffc7cf4d7aa8f04964ef4ff14834436362a1a716f95d32f05e2001d0",  # des-evidence-001
})
# 只支持已有规范的顶层规则条目，不扩成通用 Markdown 解析器。空行后的缩进续段、
# 无缩进附表仍属于当前规则，直到同级条目或标题；项目扩展不能因首段相同而丢失 ID。
RULE_ITEM_RE = re.compile(
    rb"(?ms)^- `\[([a-z0-9][a-z0-9._-]*)\] \[(hard|advisory)\]`.*?(?=^- |^#{1,6} |\Z)"
)



def common_span(body: bytes) -> tuple[int, int] | None:
    """只认完整、唯一、独占行的受管标记；不凭标题猜测所有权。"""
    if COMMON_BEGIN not in body and COMMON_END not in body:
        return None
    intervals = []
    for marker in (COMMON_BEGIN, COMMON_END):
        matches = list(re.finditer(rb"(?m)^" + re.escape(marker) + rb"\r?$", body))
        if body.count(marker) != 1 or len(matches) != 1:
            raise ValueError("GENERAL.md has malformed or duplicate common managed markers")
        intervals.append((matches[0].start(), matches[0].start() + len(marker)))
    if intervals[0][0] >= intervals[1][0]:
        raise ValueError("GENERAL.md has reversed common managed markers")
    return intervals[0][0], intervals[1][1]


def common_block(body: bytes) -> bytes | None:
    """兼容既有标记读取；迁移仅处理这对明确边界。"""
    span = common_span(body)
    return None if span is None else body[span[0]:span[1]]


def remove_created_standard(path: Path, expected: bytes, mode: int, identity: tuple[int, int]) -> None:
    """只撤回新建规范索引的已采样身份，不能 unlink 采样之后出现的用户替换。

    POSIX 先把当前名字移入本函数独占的临时名，再核对身份、权限和完整内容；若移动
    的已是用户替换，只能排他放回，不能覆盖间隙的新文件。Windows 复用已有按打开
    身份校验并删除的原语。临时名仅保护这一文件，失败保留的路径随错误交回调用方。
    """
    if fs.name == "nt":
        try:
            from .windows_fs import remove_file_if_unchanged
        except ImportError:
            from windows_fs import remove_file_if_unchanged
        info = fs.lstat(path)
        if stat.S_IMODE(info.st_mode) != mode or not remove_file_if_unchanged(
            path, hashlib.sha256(expected).hexdigest(), identity,
        ):
            raise ValueError(f"created standard changed during rollback; preserved: {path}")
        return

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.rollback-", dir=path.parent)
    temporary = Path(temporary_name)
    placeholder = fs.fstat(descriptor)
    placeholder_identity = (placeholder.st_dev, placeholder.st_ino)
    # 持有最初空临时文件的描述符直到 finally，防止其 inode 被复用后误认用户文件。
    try:
        fs.replace(path, temporary)
        moved = fs.lstat(temporary)
        if (not stat.S_ISREG(moved.st_mode) or moved.st_nlink != 1
                or (moved.st_dev, moved.st_ino) != identity
                or stat.S_IMODE(moved.st_mode) != mode or read_file(temporary) != expected):
            raise ValueError(f"created standard changed during rollback; preserved: {path}")
        fs.unlink(temporary)
        try:
            fs.lstat(path)
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"new user file appeared during rollback; preserved: {path}")
    finally:
        try:
            try:
                remaining = fs.lstat(temporary)
            except FileNotFoundError:
                remaining = None
            if remaining is not None:
                if (remaining.st_dev, remaining.st_ino) == placeholder_identity:
                    # rename 尚未发生时这里只能清理仍为本函数的空占位，不能误删新资料。
                    if read_file(temporary) != b"":
                        raise ValueError(f"rollback temporary changed; preserved: {temporary}")
                    fs.unlink(temporary)
                else:
                    try:
                        publish_exclusive(temporary, path)
                    except OSError as exc:
                        raise ValueError(
                            f"rollback conflict; preserved current file and displaced content: {path}; {temporary}"
                        ) from exc
        finally:
            fs.close(descriptor)


def _observed_baseline(profile: ProjectProfile) -> str:
    """仅为识别旧安装器精确生成的观察；不再向项目写入观察或规范占位。"""
    if not profile.modules:
        return "- No implementation module was discovered; add explicit rules only after verification."
    lines = []
    for module in profile.modules:
        stacks = ", ".join(module.stack_facts) if module.stack_facts else "unknown"
        lines.append(f"- `{module.root}` → role `{module.primary_role}`; stacks: {stacks}; "
                     f"evidence: {', '.join(module.evidence_paths) or 'none'}")
        if module.verification_commands:
            encoded = ", ".join(json.dumps(list(command.argv), ensure_ascii=False)
                                for command in module.verification_commands)
            lines.append(f"  - Discovered verification commands: {encoded}")
    return "\n".join(lines)


def _legacy_template(name: str, body: bytes, values: Mapping[str, str], profile: ProjectProfile) -> bool:
    """只归一化已知模板变量再比整文指纹；项目注释、规则差异和旧观察均会保留。"""
    text = body.decode("utf-8", errors="strict").replace("\r\n", "\n")
    title, separator, rest = text.partition("\n")
    suffix = " — " + values["PROJECT_NAME"]
    if title.endswith(suffix):
        title = title[:-len(suffix)] + " — {{PROJECT_NAME}}"
    text = title + separator + rest
    if name == "GENERAL.md":
        observed = re.search(
            r"(?s)(?<=## Observed repository baseline\n\n)(.*?)(?=\n\nThese observations guide routing and verification;)", text)
        if observed:
            allowed = {"{{OBSERVED_BASELINE}}", _observed_baseline(profile),
                       "- Not initialized. Setup replaces this exact template-only line with read-only repository observations."}
            if observed.group() not in allowed:
                return False
            text = text[:observed.start()] + "{{OBSERVED_BASELINE}}" + text[observed.end():]
    if name == "STANDARDS.md":
        base, parent = values["DOC_STANDARDS_ROOT"], posixpath.dirname(values["DOC_STANDARDS"])
        engineering = "\n".join(f"- [{label}]({posixpath.relpath(base + '/' + leaf, parent)})"
                                for label, leaf in (("General engineering rules", "GENERAL.md"),
                                                    ("Upstream and second-development boundaries", "UPSTREAM.md")))
        design = "\n".join(f"- [{label}]({posixpath.relpath(base + '/' + leaf, parent)})"
                           for label, leaf in (("Design foundations", "DESIGN_FOUNDATIONS.md"),
                                               ("Component and interaction standards", "DESIGN_COMPONENTS.md")))
        text = text.replace(engineering, "{{ENGINEERING_STANDARDS_INDEX}}")
        for content in (design, "- No design standards are configured for the discovered project profile."):
            text = text.replace(content, "{{DESIGN_STANDARDS_INDEX}}")
    # 旧 features 路径仅用于已提交模板的归属指纹，不是运行时配置别名。
    for key in ("DOC_FEATURES_DIR", "DOC_PROJECT", "DOC_DESIGN_DIR"):
        # 只还原明确反引号引用，不抹掉用户普通正文中的路径子串。
        for slash in ("/", ""):
            text = text.replace(f"`{values[key]}{slash}`", f"`{{{{{key}}}}}{slash}`")
    text = text.replace(f"`{values['DOC_DESIGN_DIR']}/prototype/`", "`{{DOC_DESIGN_DIR}}/prototype/`")
    return hashlib.sha256(text.encode("utf-8")).hexdigest() in LEGACY_TEMPLATE_HASHES.get(name, ())


def _without_builtin_items(body: bytes, paragraphs: Mapping[bytes, bytes]) -> bytes:
    """完整规则条目相同才剥离；项目续段或附表变化保留并交冲突校验拒绝。"""
    removals = []
    for match in RULE_ITEM_RE.finditer(body):
        item = match.group().replace(b"\r\n", b"\n").rstrip(b"\n")
        # 必须仍是当前内置 ID，且完整字节匹配当前正文或已取证历史摘要。
        # 条目扫描一直延伸到下一同级条目/标题，空行后用户续段和附表不能被前缀删除。
        if match[1] in paragraphs and (
            paragraphs[match[1]] == item
            or hashlib.sha256(item).hexdigest() in LEGACY_BUILTIN_ITEM_HASHES
        ):
            removals.append((match.start(), match.start() + len(match.group().rstrip(b"\r\n"))))
    for start, end in reversed(removals):
        body = body[:start] + body[end:]
    return body


def validate_planned_rule_ids(root: Path, updates: Mapping[Path, bytes | None], *, pack_root: Path) -> None:
    """用候选视图核对内置与项目 ID 唯一性；删除条目不能继续占据规则所有权。"""
    try:
        from .validate_project_docs import STANDARD_RULE_RE, collect_standard_leaves, read_builtin_standard_sources
    except ImportError:
        from validate_project_docs import STANDARD_RULE_RE, collect_standard_leaves, read_builtin_standard_sources
    errors = []
    leaves = collect_standard_leaves(root, errors) if root.exists() else {}
    for path, body in updates.items():
        if path.parent == root and path.suffix == ".md":
            if body is None:
                leaves.pop(path.resolve(), None)
            else:
                leaves[path.resolve()] = body.decode("utf-8", errors="strict")
    owners = {}
    for path, body in [*read_builtin_standard_sources(pack_root).items(), *leaves.items()]:
        for rule_id, _severity in STANDARD_RULE_RE.findall(body):
            if rule_id in owners:
                errors.append(f"duplicate standards rule ID {rule_id}: {owners[rule_id]} and {path}")
            else:
                owners[rule_id] = path
    if errors:
        raise ValueError("; ".join(errors))


def _remove_deleted_links(line: str, index: Path, deleted: set[Path], resolve) -> str:
    """纯默认链接行可去掉；混合项目说明只移除对应链接，保留其余原文。"""
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    matches = [match for match in pattern.finditer(line) if resolve(index, match[1]) in deleted]
    if len(matches) == 1 and re.fullmatch(r"[ \t]*[-*]?[ \t]*" + re.escape(matches[0].group()) + r"[ \t\r\n]*", line):
        return ""
    for match in reversed(matches):
        line = line[:match.start()] + line[match.end():]
    return line


def plan_standard_updates(pack: Path, project: Path, *, docs: Mapping[str, str],
                          profile: ProjectProfile,
                          expected_inputs: dict[Path, bytes | None] | None = None) -> dict[Path, bytes | None]:
    """三种安装入口共用只读迁移计划；None 为经过归属证明的精确删除。

    只处理四个旧默认叶及索引，不接管其他项目文件。含项目内容时保留原始字节，只移除
    受管区或完整相同的通用段落。发布器仍负责权限、身份复核、失败回滚与并发编辑保护。
    """
    try:
        from .validate_project_docs import STANDARD_RULE_RE, MARKDOWN_LINK_RE, collect_standard_leaves, normalized_link_target, read_builtin_standard_sources
    except ImportError:
        from validate_project_docs import STANDARD_RULE_RE, MARKDOWN_LINK_RE, collect_standard_leaves, normalized_link_target, read_builtin_standard_sources
    # 调用方已检查显式根目录。这里再次拒绝根本身的链接，再归一化 macOS 的
    # /var 等合法系统祖先别名；配置的内部相对路径仍由 read_file 逐级拒绝链接。
    for base in (pack, project):
        if not stat.S_ISDIR(base.lstat().st_mode):
            raise ValueError(f"standard migration root must be a real directory: {base}")
    pack, project = pack.resolve(), project.resolve()
    config = read_file(pack / "project.yaml")
    if config is None:
        raise ValueError("project.yaml is missing")
    name_match = re.search(r"(?m)^project_name:[ \t]*(.*)$", config.decode("utf-8"))
    if name_match is None:
        raise ValueError("project.yaml is missing project_name")
    values = {"PROJECT_NAME": parse_project_name(name_match[1]), "DOC_STANDARDS": docs["standards"],
              "DOC_STANDARDS_ROOT": docs["standards_root"].rstrip("/"), "DOC_PROJECT": docs["project"],
              "DOC_FEATURES_DIR": "docs/features", "DOC_DESIGN_DIR": docs["standards_root"].rstrip("/")}
    root, index = project / docs["standards_root"], project / docs["standards"]
    index_body = read_file(index)
    originals = {index: index_body}
    errors = []
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError(f"standards root must be a real directory: {root}")
    leaves = collect_standard_leaves(root, errors) if root.exists() else {}
    if errors:
        raise ValueError("; ".join(errors))
    paragraphs = {}
    for source in read_builtin_standard_sources(pack).values():
        for match in RULE_ITEM_RE.finditer(source.encode("utf-8")):
            if match[1] in paragraphs:
                raise ValueError(f"duplicate builtin paragraph: {match[1].decode()}")
            paragraphs[match[1]] = match.group().replace(b"\r\n", b"\n").rstrip(b"\n")
    updates = {}
    for leaf in ("GENERAL.md", "UPSTREAM.md", "DESIGN_FOUNDATIONS.md", "DESIGN_COMPONENTS.md"):
        target = root / leaf
        current = read_file(target)
        originals[target] = current
        if current is None or not current:
            continue
        span = common_span(current) if leaf == "GENERAL.md" else None
        if _legacy_template(leaf, current, values, profile):
            updates[target] = None
            continue
        body = current
        if span is not None:
            region = current[span[0]:span[1]]
            if hashlib.sha256(region.replace(b"\r\n", b"\n")).hexdigest() not in LEGACY_COMMON_BLOCK_HASHES:
                raise ValueError("GENERAL.md common managed region differs from known defaults; preserved unchanged")
            unknown = {rule.encode() for rule, _ in STANDARD_RULE_RE.findall(region.decode("utf-8"))} - paragraphs.keys()
            if unknown:
                raise ValueError("GENERAL.md common managed region contains unknown project rule IDs")
            body = body[:span[0]] + body[span[1]:]
        body = _without_builtin_items(body, paragraphs)
        if body != current:
            updates[target] = body
    remaining = {path: body for path, body in leaves.items() if updates.get(path, b"") is not None}
    for path, body in updates.items():
        if body is not None:
            remaining[path] = body.decode("utf-8")
    normative = {path: body for path, body in remaining.items() if STANDARD_RULE_RE.search(body)}
    deleted = {path.resolve() for path, body in updates.items() if body is None}
    if index_body is not None and _legacy_template("STANDARDS.md", index_body, values, profile):
        index_body = None
        if not normative:
            updates[index] = None
    if normative:
        if not index_body:
            source = read_file(pack / "templates/docs/STANDARDS.md")
            if source is None:
                raise ValueError("project standards index template is missing")
            lines = {"engineering": [], "design": []}
            for path in sorted(normative):
                domain = "design" if path.name.startswith("DESIGN_") else "engineering"
                link = quote(os.path.relpath(path, index.parent), safe="/")
                lines[domain].append(f"- [{path.stem}]({link})")
            substitutions = values | {"ENGINEERING_STANDARDS_INDEX": "\n".join(lines["engineering"]),
                                      "DESIGN_STANDARDS_INDEX": "\n".join(lines["design"])}
            text = re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: substitutions[match[1]], source.decode("utf-8"))
            updates[index] = text.encode("utf-8")
        else:
            text = index_body.decode("utf-8")
            text = re.sub(r"(?m)^.*\[[^\]]+\]\([^)]+\).*?(?:\r?\n|$)",
                          lambda line: _remove_deleted_links(line.group(), index, deleted, normalized_link_target), text)
            linked = {normalized_link_target(index, raw) for raw in MARKDOWN_LINK_RE.findall(text)}
            newline = "\r\n" if b"\r\n" in index_body else "\n"
            missing = [path for path in sorted(normative) if path.resolve() not in linked]
            if missing:
                text += ("" if text.endswith(newline * 2) else newline if text.endswith(newline) else newline * 2)
                text += newline.join(f"- [{path.stem}]({quote(os.path.relpath(path, index.parent), safe='/')})" for path in missing) + newline
            if text.encode("utf-8") != index_body:
                updates[index] = text.encode("utf-8")
    elif index_body:
        text = re.sub(r"(?m)^.*\[[^\]]+\]\([^)]+\).*?(?:\r?\n|$)",
                      lambda line: _remove_deleted_links(line.group(), index, deleted, normalized_link_target), index_body.decode("utf-8"))
        if text.encode("utf-8") != index_body:
            updates[index] = text.encode("utf-8")
    validate_planned_rule_ids(root, updates, pack_root=pack)
    if expected_inputs is not None:
        # 发布方必须绑定生成 after 时实际读取的 before；不能在计划后重新采样并
        # 把并发编辑追认为本轮输入。原字节只在当前内存事务保留，不创建副本文件。
        expected_inputs.update({path: originals[path] for path in updates})
    return updates
