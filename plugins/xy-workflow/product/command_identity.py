"""公开命令身份的标准库加载器；只读取指定产品根中的唯一声明。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat


# 这里只保存已审阅内容的完整性 pin，不再维护第二份插件、别名或角色定义。
# 合同获准调整时，从唯一 JSON 读取后以 sort_keys=True、separators=(",", ":")、
# ensure_ascii=False 序列化 UTF-8，再重算 SHA256；同步调用方与发行 provenance。
# 该摘要不是签名或新的业务批准步骤，只防止独立包读取被替换的身份声明。
_APPROVED_CONTENT_SHA256 = "e48a574f9111430bcfbea8a5c01214a7e478bab908cad91d572661b8697d14a5"
_FIELDS = {"schema_version", "plugin_name", "marketplaces", "artifact_prefix", "skill_aliases",
           "managed_roles", "legacy_plugin_name", "legacy_marketplaces"}
_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


def load_identity(root: Path) -> dict:
    """返回校验后的身份；缺失、链接、重复键或非批准身份均抛出 ValueError。

    root 必须由调用方的物理包位置确定，不能使用用户配置或 cwd 搜索回退。
    固定约束属于验证规则，产品值仍只从 JSON 读取；禁止通过修改声明注入其他插件。
    """
    root = Path(root).resolve(strict=True)
    path = root / "product/command_identity.json"
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("命令身份不能使用符号链接")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
        raise ValueError("命令身份必须为有界普通文件")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("命令身份含重复字段")
            result[key] = value
        return result
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    # 类型审查独立于内容 pin，明确拒绝 bool 冒充整数、错误容器和未知字段。
    if (not isinstance(data, dict) or set(data) != _FIELDS
            or type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise ValueError("命令身份 schema 或字段无效")

    def safe(value):
        return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None

    for field in ("plugin_name", "artifact_prefix", "legacy_plugin_name"):
        if not safe(data[field]):
            raise ValueError("命令身份包含不安全标识")
    for field in ("marketplaces", "legacy_marketplaces"):
        markets = data[field]
        if not isinstance(markets, dict) or set(markets) != {"alpha", "local"} or not all(map(safe, markets.values())):
            raise ValueError("命令身份市场映射无效")
    aliases = data["skill_aliases"]
    roles = data["managed_roles"]
    if (not isinstance(aliases, dict) or len(aliases) != 5
            or not all(safe(key) and safe(value) for key, value in aliases.items())
            or not isinstance(roles, list) or len(roles) != 7 or not all(map(safe, roles))
            or len(set(roles)) != len(roles)):
        raise ValueError("命令身份别名或受管角色无效")
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != _APPROVED_CONTENT_SHA256:
        raise ValueError("命令身份不匹配已批准的固定合同")
    return data
