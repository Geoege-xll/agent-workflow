"""测试辅助：读取完整的渐进契约，并定位需要篡改的真实源文件。

断言规则而不是规则存在哪个文件。负向用例仍直接改动入口或被引用的原文，
不会把展开后的副本塞回 SKILL.md，因此保留真实安装、引用和漂移检查覆盖。
"""

from pathlib import Path

from lib.business_confirmation_policy import read_instruction_contract
from lib.skill_contracts import BOOTSTRAP_TARGETS, INCLUDE


def read_contract(path: Path) -> str:
    if path.name.startswith("AGENTS.") and path.suffix == ".tpl":
        # 模板已改为目录入口，规则断言需审计其真实引用；原始体积另作直接读取。
        pack = path.parents[2]
        return read_instruction_contract(pack, path.relative_to(pack).as_posix())
    return read_instruction_contract(path.parent, path.name)


def read_bootstrap_contract(path: Path, pack: Path) -> str:
    """检查生成入口的完整契约；不把展开文本当作宿主常驻内容或体积样本。"""
    from lib.skill_contracts import expand_bootstrap_contract
    body = path.read_text(encoding="utf-8")
    # 分别展开受管区块，避免把别的宿主正文误用于当前宿主的语义断言。
    for relative, target in BOOTSTRAP_TARGETS.items():
        source = (pack / relative).read_text(encoding="utf-8").strip()
        if source in body:
            contract = expand_bootstrap_contract(
                source, lambda reference: read_instruction_contract(pack, reference), target,
            )
            body = body.replace(source, contract, 1)
    return body


def contract_file_containing(path: Path, text: str) -> Path:
    """优先保持原文件；仅在原片段被搬入显式引用时返回该引用的真实路径。"""
    body = path.read_text(encoding="utf-8")
    if text in body:
        return path
    if path.name.startswith("AGENTS.") and path.suffix == ".tpl":
        pack = path.parents[2]
        target = BOOTSTRAP_TARGETS[path.relative_to(pack).as_posix()]
        return contract_file_containing(pack / target, text)
    if path.name != "SKILL.md":
        raise AssertionError(f"mutation fragment not found in contract {path}: {text!r}")
    for match in INCLUDE.finditer(body):
        reference = path.parent / match.group(1)
        if text in reference.read_text(encoding="utf-8"):
            return reference
    raise AssertionError(f"mutation fragment not found in contract {path}: {text!r}")
