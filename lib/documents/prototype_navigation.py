#!/usr/bin/env python3
"""只验证原型页明确声明的需求文档对，不渲染文档或回扫反向原型链接。"""

from __future__ import annotations

# 直接脚本只信任自身物理位置确定的核心根，避免异 cwd 或 PYTHONPATH 中的
# 同名模块劫持内部依赖；正常包导入沿用调用方已选择的固定核心。
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

from pathlib import Path, PurePosixPath

if __package__:
    from lib.documents.plan_documents import local_target
    from lib.documents.requirement_html import digest, normalized_relative, page_record, snapshot
    from lib.project.validate_project_config import validate_docs
else:
    from lib.documents.plan_documents import local_target
    from lib.documents.requirement_html import digest, normalized_relative, page_record, snapshot
    from lib.project.validate_project_config import validate_docs


class RequirementNavigation:
    """复用文档模型的安全读取与产物记录，仅保留本次导航输入的并发核对信息。"""

    def __init__(self, project: Path, prototype: PurePosixPath) -> None:
        self.project = project.absolute()
        self.prototype = self.project / prototype
        self.plans: Path | None = None
        self.inputs: dict[Path, tuple[str, tuple]] = {}
        self.validated_sources: set[Path] = set()

    def _capture(self, path: Path) -> bytes:
        # 不另建文件系统读取层；链接、FIFO、硬链接、UTF-8 和单文件限额均由模型入口处理。
        body, node_identity = snapshot(path)
        current = (digest(body), node_identity)
        if path in self.inputs and self.inputs[path] != current:
            raise ValueError(f"需求导航输入在检查期间变化：{path}")
        self.inputs[path] = current
        return body

    def _configure(self) -> None:
        if self.plans is not None:
            return
        installed = self.project / ".agent-workflow/project.yaml"
        config = installed if installed.exists() or installed.is_symlink() else self.project / "project.yaml"
        errors: list[str] = []
        docs = validate_docs(self._capture(config).decode("utf-8").splitlines(), self.project, errors)
        if errors:
            raise ValueError("需求导航的 docs 配置无效：" + "; ".join(errors))
        if self.prototype != self.project / docs["standards_root"] / "prototype":
            raise ValueError("需求导航只适用于配置 docs.standards_root 下的原型目录")
        self.plans = self.project / docs["plans"]

    def validate(self, page: PurePosixPath, source_raw: str, links: list[tuple[str, str]]) -> None:
        """校验显式槽位内同名 HTML/Markdown，绑定来源字节而不要求 renderer 身份最新。"""
        if not source_raw and not links:
            return
        if not source_raw or sorted(kind for kind, _ in links) != ["html", "markdown"]:
            raise ValueError("需求导航须声明唯一 Markdown 来源和 HTML/Markdown 两个链接")
        relative = normalized_relative(source_raw)
        if relative.suffix != ".md" or any(part.startswith(".") for part in relative.parts):
            raise ValueError("需求导航来源须为规范的项目相对 Markdown 路径")
        self._configure()
        source = self.project / relative
        if not source.is_relative_to(self.plans):
            raise ValueError("需求导航来源必须位于配置 docs.plans 下")
        html = source.with_suffix(".html")
        expected = {"html": html, "markdown": source}
        for kind, raw in links:
            target = local_target(self.project, self.prototype / page, raw)
            if target != expected[kind]:
                raise ValueError(f"需求导航 {kind} 链接未指向声明来源的同名文件对：{raw!r}")
        if source in self.validated_sources:
            return
        source_body = self._capture(source)
        html_body = self._capture(html)
        record, _ = page_record(html_body, {
            "project": str(self.project), "source": relative.as_posix(), "draft": False,
        })
        if record.get("source_sha256") != digest(source_body):
            raise ValueError("需求导航 HTML 与当前 Markdown 内容不匹配")
        # 不调用 process/check、renderer_identity 或 stage_markdown：文档反向链接和渲染器
        # 升级不属于页面渲染依赖，也不能让普通进度更新触发全项目原型重验或视觉重批。
        self.validated_sources.add(source)

    def require_current_inputs(self) -> None:
        """返回原型证据前复核已读输入，不能把期间被替换的文档绑定到成功结果。"""
        for path in self.inputs:
            self._capture(path)
