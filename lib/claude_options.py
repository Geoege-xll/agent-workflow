"""Claude 可选原生能力的单一配置合同；缺省继承，不改动模型偏好或全局权限。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

if __package__:
    from .role_models import ROLES
else:
    from role_models import ROLES


def validate_window(value: object) -> int:
    """角色字段只接受完整 token 整数；bool、缩写、浮点数都不能静默变成有效窗口。"""
    if type(value) is not int or not 100000 <= value <= 1000000:
        raise ValueError("autoCompactWindow 必须为 100000..1000000 的整数")
    return value


def parse(text: str) -> dict:
    """解析有界 YAML 子集；窗口表用单行 JSON，拒绝重复键与无法证明含义的条目。

    写入保护只提供 inherit / true，避免安装或关闭 Hooks 时意外放宽原生权限。
    inherit 表示不再写该设置，已经启用的原生保护仍由用户在宿主配置中管理。
    """
    result = {"auto_compact_windows": {}, "block_writes_outside_working_directories": "inherit"}
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"^claude_options:", line)]
    if not starts:
        return result
    if len(starts) != 1 or not re.fullmatch(r"claude_options:\s*(?:#.*)?", lines[starts[0]]):
        raise ValueError("claude_options 必须是唯一的映射区块")
    seen = set()
    for line in lines[starts[0] + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            break
        match = re.fullmatch(r"  (auto_compact_windows|block_writes_outside_working_directories): (.+)", line)
        if match is None or match[1] in seen:
            raise ValueError("claude_options 包含重复或不支持的条目")
        key, raw = match.groups()
        seen.add(key)
        if key == "block_writes_outside_working_directories":
            if raw not in {"inherit", "true"}:
                raise ValueError("写入保护只接受 inherit 或 true；关闭请直接管理原生权限")
            result[key] = True if raw == "true" else "inherit"
            continue

        def unique(pairs):
            table = {}
            for role, value in pairs:
                if role in table:
                    raise ValueError("压缩窗口角色不可重复")
                table[role] = value
            return table

        try:
            windows = json.loads(raw, object_pairs_hook=unique)
        except json.JSONDecodeError as exc:
            raise ValueError("auto_compact_windows 必须是单行 JSON 对象") from exc
        if not isinstance(windows, dict) or set(windows) - ROLES:
            raise ValueError("压缩窗口只能配置规范角色")
        result[key] = {role: validate_window(value) for role, value in windows.items()}
    return result


def frontmatter_window(raw: bytes) -> int | None:
    """只读提取已安装角色的窗口，供诊断复用；不把正文里的同名文本当成原生字段。"""
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n") or "\n---\n" not in text:
        raise ValueError("Claude 角色缺少完整 frontmatter")
    front = text.split("\n---\n", 1)[0]
    values = re.findall(r"^autoCompactWindow:[ \t]*([^\n]*)$", front, re.M)
    if not values:
        return None
    if len(values) != 1 or not re.fullmatch(r"[0-9]{6,7}", values[0]):
        raise ValueError("Claude 角色压缩窗口必须为唯一的完整整数")
    return validate_window(int(values[0]))


def main() -> int:
    """生成器仅输出已选择角色的原生字段；无配置时不添加该字段。"""
    if len(sys.argv) != 3 or sys.argv[2] not in ROLES:
        return 2
    try:
        options = parse((Path(sys.argv[1]) / "project.yaml").read_text(encoding="utf-8"))
        window = options["auto_compact_windows"].get(sys.argv[2])
        if window is not None:
            print(f"autoCompactWindow: {window}")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
