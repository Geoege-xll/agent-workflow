"""安装入口与中央服务共用的项目目标校验，不导入安装编排。"""

from __future__ import annotations

from pathlib import Path
import shlex

if __package__:
    from .platform_fs import os
else:
    from platform_fs import os


class InstallError(Exception):
    """中央安装前置条件或目标边界校验失败。"""



def target_path(raw: str, source_root: Path) -> Path:
    """兼容终端拖入的引号与反斜杠转义，但绝不通过 shell 执行路径。"""

    value = raw.rstrip("\r\n")
    if not value.strip():
        raise InstallError("未提供项目目录。请拖入目录后按回车，或将目录作为参数传入。")
    candidates = [value]
    if value.strip() != value:
        candidates.append(value.strip())
    # 参数模式收到的是 shell 已解引用的真实路径，文件夹名本身可能含单引号；
    # 只有原样和去除误输入空白的路径都不存在时，才解析终端拖入的转义形式。
    if not any(Path(candidate).expanduser().is_dir() for candidate in candidates):
        try:
            tokens = shlex.split(value)
        except ValueError as exc:
            raise InstallError(f"项目路径的引号或转义不完整：{exc}") from exc
        if len(tokens) == 1:
            candidates.append(tokens[0])
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.is_dir():
            continue
        if os.name == "nt":
            if __package__:
                from .windows_fs import Directory
            else:
                from windows_fs import Directory
            # resolve 会抹去 junction 的路径身份；先由目录边界拒绝其祖先，避免越过目标范围。
            with Directory(path):
                resolved = path.resolve(strict=True)
        else:
            resolved = path.resolve(strict=True)
        if resolved == source_root or resolved.is_relative_to(source_root):
            raise InstallError("目标项目不能是安装包本身或其子目录。")
        if source_root.is_relative_to(resolved):
            raise InstallError("目标目录不能包含当前安装包；请选择具体项目根目录。")
        return resolved
    raise InstallError(f"项目目录不存在或不是文件夹：{value}")
