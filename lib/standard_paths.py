"""浅层规范路径分类：目录不再承担工程/设计的安全边界。

设计规范统一使用 DESIGN_ 前缀，其余规范为工程类。索引及叶文档仍声明实际适用
范围；此处只做确定性的路径类型校验，防止把工程文件改标为设计输入而获得写权限。
"""

from __future__ import annotations

from pathlib import PurePosixPath


def standard_domain(path: str, root: str) -> str | None:
    """只识别规范根目录中的直接 Markdown 叶，排除原型、嵌套目录和非规范产物。"""

    leaf = PurePosixPath(path)
    if leaf.parent.as_posix().casefold() != PurePosixPath(root).as_posix().casefold() or leaf.suffix.casefold() != ".md":
        return None
    return "design" if leaf.name.casefold().startswith("design_") else "engineering"


def canonical_standard_path(path: str, root: str) -> bool:
    """拒绝大小写别名，避免 macOS 将不同合同路径落到同一物理文件。

    分类先保守识别大小写别名，权限检查不会把 design_ 当工程；真正的合同只能
    使用适配器原样根目录、.md 扩展名和 DESIGN_ 前缀，避免并行锁与指纹注册分裂。
    """

    leaf = PurePosixPath(path)
    domain = standard_domain(path, root)
    return (
        domain is not None
        and leaf.parent == PurePosixPath(root)
        and leaf.suffix == ".md"
        and (domain != "design" or leaf.name.startswith("DESIGN_"))
    )
