"""只在显式专题查询时加载上游检索函数；每次查询使用独立的内存索引。"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from lib.skills.selected_skills import (
    DESIGN_ENGINE, DESIGN_QUERY, DESIGN_ROOT, DESIGN_TOPICS, VENDOR, locked_dependency, locked_file,
)


def search(root: Path, domain: str, keywords: str, limit: int,
           verify_source: Callable[[str, str], None] | None) -> dict:
    if (domain not in DESIGN_TOPICS or not keywords.strip() or keywords.startswith("-")
            or len(keywords) > 512 or not keywords.isprintable()):
        raise ValueError("expected a design topic and 1..512 printable keyword characters")
    item = locked_dependency(root, DESIGN_QUERY, verify_source)
    engine, engine_sha = locked_file(root, DESIGN_QUERY, item, DESIGN_ENGINE, verify_source)
    data_relative = DESIGN_ROOT + "/data/" + DESIGN_TOPICS[domain]
    data, data_sha = locked_file(root, DESIGN_QUERY, item, data_relative, verify_source)
    vendor = root / VENDOR / DESIGN_QUERY
    data_path = vendor / data_relative

    def open_topic(path: Path, mode: str, *, encoding: str):
        # core.search 的 CSV reader 消费已验字节。即使包中出现额外的可选 products.csv，
        # 也只能走上游内建关键词分支；检索器不能从磁盘重新打开已被替换的正文。
        if path != data_path or mode != "r" or encoding != "utf-8":
            raise FileNotFoundError("outside the selected design corpus")
        return io.TextIOWrapper(io.BytesIO(data), encoding=encoding)

    # 执行与锁及发行清单匹配的原版源码，不经可替换的 .pyc 或项目目录解析上游模块。
    # 上游 core 只依赖标准库；完整 CLI 的设计系统、持久化、下载和预览均不在闭包内。
    engine_path = str(vendor / DESIGN_ENGINE)
    core = {"__name__": "ui_ux_pro_max_core", "__file__": engine_path, "open": open_topic}
    exec(compile(engine, engine_path, "exec"), core)
    result = core["search"](keywords, domain=domain, max_results=limit)
    if "error" in result:
        raise ValueError(result["error"])
    result["source"] = {"commit": item["commit"], "engine_sha256": engine_sha,
                        "path": f"{VENDOR}/{DESIGN_QUERY}/{data_relative}", "sha256": data_sha}
    return result
