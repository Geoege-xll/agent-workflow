"""请求交接的路径合同以及所有宿主共用的系统临时根。"""

import hashlib
from pathlib import Path
import re
import tempfile

from lib.task_graph import TaskGraphError


# 使用独立容器完成命名升级：旧版原始 ID 也可能恰好长得像哈希名，不能靠正则区分归属。
# 旧 agent-workflow-scratch 容器整体留待原任务或人工核对，不参与新版分配和清理。
SCRATCH_ROOT_NAME = "agent-workflow-request-scratch"
SCRATCH_SLOT_RE = re.compile(r"request-[0-9a-f]{64}\Z")


def project_scratch_base(root: Path) -> Path:
    """按真实项目根路径派生唯一确定性的临时根目录，避免每个任务自造 /tmp 目录。"""
    if root.is_symlink():
        raise TaskGraphError(f"scratch project root must not be a symlink: {root}")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise TaskGraphError(f"scratch project root must be an existing directory: {root}")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved.name).strip("-._") or "project"
    slug = slug[:48]
    project_hash = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    container = temp_root / SCRATCH_ROOT_NAME
    if container.is_symlink():
        raise TaskGraphError(f"scratch container must not be a symlink: {container}")
    base = container / f"{slug}-{project_hash}"
    if base.is_symlink():
        raise TaskGraphError(f"project scratch root must not be a symlink: {base}")
    return base


def validated_scratch_slot(request_id: str | None) -> str:
    """逻辑 ID 沿用任务图的非空字符串合同，磁盘名称只使用其完整字节摘要。"""
    logical_id = "shared" if request_id is None else request_id
    if not isinstance(logical_id, str) or not logical_id.strip():
        raise TaskGraphError(f"invalid scratch request_id: {request_id!r}")
    # 不把用户 ID 当路径片段；中文、斜杠、设备保留名及长 ID 均可安全映射。
    # 摘要保留大小写差异，避免 macOS/Windows 上两个逻辑请求共用同一目录。
    return "request-" + hashlib.sha256(logical_id.encode("utf-8")).hexdigest()


class HandoffPolicy:
    """选择交接目录；创建、校验、清理和摘要仍由任务记录模块负责。"""

    workspace_ignore = False

    def current_base(self, root: Path) -> Path:
        return project_scratch_base(root)

    def cleanup_base(self, root: Path, slot: str | None) -> Path:
        return self.current_base(root)

    def compatible_bases(self, root: Path) -> tuple[Path, ...]:
        return (self.current_base(root),)


SYSTEM_HANDOFF = HandoffPolicy()
