"""浅层规范路径分类：目录不再承担工程/设计的安全边界。

设计规范统一使用 DESIGN_ 前缀，其余规范为工程类。索引及叶文档仍声明实际适用
范围；此处只做确定性的路径类型校验，防止把工程文件改标为设计输入而获得写权限。
"""

from __future__ import annotations

from pathlib import PurePosixPath


# 内置规则的权威只有运行时源文件；宿主 .agents/.claude 的发现副本不属于项目规范源。
# 精确列举路径而不接受任意 Skill/references，防止通过路径或 domain 标签扩大规则权限。
BUILTIN_STANDARD_SOURCES = {
    "platforms/shared/skills/xy-code-standards/references/rules.md": "engineering",
    "platforms/shared/skills/xy-ui-design/references/foundations-rules.md": "design",
    "platforms/shared/skills/xy-ui-design/references/components-rules.md": "design",
}
BUILTIN_INSTALL_PREFIX = ".agent-workflow/"


def builtin_source_path(path: str) -> str | None:
    """把两种精确权威路径归一到源包键；大小写、重复前缀及路径别名均不接受。"""
    relative = path[len(BUILTIN_INSTALL_PREFIX):] if path.startswith(BUILTIN_INSTALL_PREFIX) else path
    return relative if relative in BUILTIN_STANDARD_SOURCES else None


def source_domain(path: str, root: str) -> str | None:
    """只读规则来源分类；不能用于授予项目写权限。"""
    builtin = builtin_source_path(path)
    if builtin is not None:
        return BUILTIN_STANDARD_SOURCES[builtin]
    # 即使纯JSON伪造root，也不能把宿主分发副本或未知运行时Skill文件降格成项目叶。
    # 仅封闭只读来源命名空间，项目可写路径的standard_domain保持原样。
    if path.casefold().startswith((".agents/", ".claude/", ".agent-workflow/", "platforms/shared/skills/")):
        return None
    return standard_domain(path, root)


def canonical_standard_source_path(path: str, root: str) -> bool:
    """接受固定内置源或原有直接项目叶，保持可写路径分类的原安全边界。"""
    return source_domain(path, root) is not None and (
        builtin_source_path(path) is not None or canonical_standard_path(path, root)
    )


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
