"""报告当前入口的真实发行标识与中央源根；源码目录本身不代表已发布版本。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat


VERSION_PATTERN = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", re.ASCII)


def _regular_bytes(path: Path, limit: int) -> bytes:
    """只读有界单链接普通文件；拒绝链接、替换和读取期间的并发保存。

    版本诊断发生在正常服务启动之前，不能借错误元数据回退为另一个来源。
    根目录由调用者明确传入，且每一级祖先都拒绝符号链接。
    """
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError("版本文件祖先不能是符号链接")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    before = path.lstat()
    with os.fdopen(os.open(path, flags), "rb") as stream:
        actual = os.fstat(stream.fileno())
        if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1 or actual.st_size > limit:
            raise ValueError("版本文件不是有界单链接普通文件")
        body = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                          info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if (len(body) > limit or stamp(before) != stamp(actual) or stamp(after) != stamp(actual)
            or stamp(path.lstat()) != stamp(actual)):
        raise ValueError("版本文件在读取期间变化")
    return body


def source_version(root: Path) -> str:
    """product/VERSION 是唯一人工版本源；构建器与源码诊断使用同一解析边界。"""
    raw = _regular_bytes(Path(root) / "product/VERSION", 128)
    version = raw.decode("ascii", errors="strict").removesuffix("\n")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("product/VERSION 必须为不带前导 v 的 X.Y.Z")
    return version


def describe() -> str:
    module = Path(__file__).resolve()
    metadata = module.with_suffix(".json")
    version = source_version(module.parents[1])
    label = version + "（源码未打包）"
    origin = "source（显式源码开发）"
    if metadata.exists() or metadata.is_symlink():
        try:
            # release.json 仅由构建器写入归档，放在 manager 内确保 Formula 复制目录时保留。
            # 不从 README、目录名或 Git 标签猜版本；异常标记明确失败，不能回退冒充源码。
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("发行元数据字段重复")
                    result[key] = value
                return result
            data = json.loads(_regular_bytes(metadata, 4096), object_pairs_hook=unique)
            if (not isinstance(data, dict) or set(data) != {"schema_version", "version"}
                    or type(data.get("schema_version")) is not int or data["schema_version"] != 1
                    or not isinstance(data.get("version"), str)
                    or not VERSION_PATTERN.fullmatch(data["version"]) or data["version"] != version):
                raise ValueError("发行元数据格式无效")
            label = data["version"]
            origin = "formal（发行包）"
        except (OSError, ValueError, RecursionError) as exc:
            raise ValueError(f"无法读取有效的发行元数据：{metadata}") from exc
    # __file__ 经过物理路径解析，短链接入口和调用目录都不会改变实际载荷根。
    # 来源由本载荷内通过严格校验的发行元数据决定；PATH、入口文件名、环境
    # 变量及 Cellar 目录名都不是发行证明。formal 只声明本载荷已打包，不猜测
    # Homebrew 的外部登记状态；物理根让开发入口和正式 wrapper 可直接对照。
    root = module.parents[1]
    return f"awf-cli {label}\n中央源根：{root}\n入口来源：{origin}\n物理载荷根：{root}"
