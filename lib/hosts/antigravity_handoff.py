"""AGY 的项目内交接根与升级前临时交接的兼容位置。"""

import os
from pathlib import Path

from lib.hosts.handoff import HandoffPolicy, project_scratch_base


class AntigravityHandoff(HandoffPolicy):
    workspace_ignore = True

    def current_base(self, root: Path) -> Path:
        return root.absolute() / ".awf" / "agy-requests"

    def compatible_bases(self, root: Path) -> tuple[Path, Path]:
        """Hook 同时识别本轮项目内目录和旧的临时交接目录。"""
        return self.current_base(root), project_scratch_base(root)

    def cleanup_base(self, root: Path, slot: str | None) -> Path:
        if slot is None:
            # 显式 --all 沿用当前 AGY 根，绝不遍历系统临时索引或旧槽。
            return self.current_base(root)
        current, previous = self.compatible_bases(root)
        # 当前路径即使是损坏链接也不能当作缺失。交回共用层按原规则报错，
        # 避免以当前目录异常为由误删另一处在途交接。
        if not os.path.lexists(current / slot) and os.path.lexists(previous / slot):
            return previous
        return current


ANTIGRAVITY_HANDOFF = AntigravityHandoff()
