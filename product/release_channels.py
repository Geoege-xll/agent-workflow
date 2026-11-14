"""两个独立产品共用的发行版本合同；仅接受正式版和保留的 alpha 历史。"""
from __future__ import annotations

import re


# 使用完整匹配并排除前导零：版本既进入文件名也进入远程 ref，不能接受宽松
# SemVer、未知预发行标签或构建元数据后再替调用方猜测渠道。
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-alpha\.([1-9][0-9]*))?")
CHANNELS = ("stable", "alpha")


def parse_version(version: str) -> tuple[int, int, int, int, int]:
    """返回可比较的版本键；相同主次修订中，正式版高于所有 alpha。"""
    match = VERSION.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        raise ValueError("发行版本必须为 X.Y.Z 或 X.Y.Z-alpha.N，且不得含前导零")
    major, minor, patch, alpha = match.groups()
    return (int(major), int(minor), int(patch), int(alpha is None), int(alpha or 0))


def version_channel(version: str) -> str:
    """由唯一版本源推导渠道；声明中的 channel 不能覆盖版本事实。"""
    return "stable" if parse_version(version)[3] else "alpha"


def validate_channel(version: str, channel: str) -> str:
    """在输入边界拒绝未知渠道及正式／预发行混用，返回已验证的渠道。"""
    if channel not in CHANNELS or version_channel(version) != channel:
        raise ValueError("发行版本与渠道不匹配")
    return channel


def compare_versions(left: str, right: str) -> int:
    """比较发行先后；0 表示同版，负数／正数表示左侧较旧／较新。"""
    left_key, right_key = parse_version(left), parse_version(right)
    return (left_key > right_key) - (left_key < right_key)
