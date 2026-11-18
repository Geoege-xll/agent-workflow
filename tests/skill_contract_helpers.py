"""测试辅助：读取完整的渐进契约，并定位需要篡改的真实源文件。

断言规则而不是规则存在哪个文件。负向用例仍直接改动入口或被引用的原文，
不会把展开后的副本塞回 SKILL.md，因此保留真实安装、引用和漂移检查覆盖。
"""

from pathlib import Path

from lib.skills.business_confirmation_policy import read_instruction_contract
from lib.skills.skill_contracts import INCLUDE


def read_contract(path: Path) -> str:
    return read_instruction_contract(path.parent, path.name)


def contract_file_containing(path: Path, text: str) -> Path:
    """优先保持原文件；仅在原片段被搬入显式引用时返回该引用的真实路径。"""
    body = path.read_text(encoding="utf-8")
    if text in body:
        return path
    if path.name != "SKILL.md":
        raise AssertionError(f"mutation fragment not found in contract {path}: {text!r}")
    for match in INCLUDE.finditer(body):
        reference = path.parent / match.group(1)
        if text in reference.read_text(encoding="utf-8"):
            return reference
    raise AssertionError(f"mutation fragment not found in contract {path}: {text!r}")
