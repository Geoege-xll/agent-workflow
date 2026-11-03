"""报告当前入口的真实发行标识与中央源根；源码目录本身不代表已发布版本。"""

from __future__ import annotations

import json
from pathlib import Path
import re


def describe() -> str:
    module = Path(__file__).resolve()
    metadata = module.with_suffix(".json")
    label = "源码未打包"
    if metadata.exists() or metadata.is_symlink():
        try:
            # release.json 仅由构建器写入归档，放在 manager 内确保 Formula 复制目录时保留。
            # 不从 README、目录名或 Git 标签猜版本；异常标记明确失败，不能回退冒充源码。
            if metadata.is_symlink() or not metadata.is_file() or metadata.stat().st_size > 4096:
                raise ValueError("发行元数据不是有界普通文件")
            data = json.loads(metadata.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("schema_version") != 1
                    or not isinstance(data.get("version"), str)
                    or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", data["version"], re.ASCII)):
                raise ValueError("发行元数据格式无效")
            label = data["version"]
        except (OSError, ValueError, RecursionError) as exc:
            raise ValueError(f"无法读取有效的发行元数据：{metadata}") from exc
    # __file__ 经过物理路径解析，短链接入口和调用目录都不会改变实际载荷根。
    return f"awf-cli {label}\n中央源根：{module.parents[1]}"
