"""从当前物理插件根装配派发和交接策略。"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lib.hosts.dispatch_contract import DEFAULT_DISPATCH, DispatchPolicy
from lib.hosts.handoff import HandoffPolicy, SYSTEM_HANDOFF
from lib.safe_text import read_file
from lib.task_graph import TaskGraphError


ROOT = Path(__file__).resolve().parents[2]
ENTRY = "plugins/host-adapter.json"
MANIFESTS = {
    "codex": ".codex-plugin/plugin.json",
    "claude": ".claude-plugin/plugin.json",
    "antigravity": ".antigravity-plugin/plugin.json",
}


def _object(body: bytes | None, relative: str) -> dict:
    if body is None:
        raise TaskGraphError("missing host adapter resource: " + relative)
    value = json.loads(body)
    if not isinstance(value, dict):
        raise TaskGraphError("invalid host adapter resource: " + relative)
    return value


def packaged_host(root: Path = ROOT, *, provenance: dict | None = None,
                  expected: str | None = None, resources: tuple[str, ...] = ()) -> str | None:
    """核对实体插件的唯一组装入口及原生清单。源码模式只有真实构建树可用。"""
    source_file = "sources.json"
    markers = (source_file, "workflow-sources.json", ENTRY, *MANIFESTS.values(), "plugin.json")
    present = {name for name in markers if (root / name).exists() or (root / name).is_symlink()}
    if not present and provenance is None and expected is None and (root / "packaging/build_plugin.py").is_file():
        return None
    metadata = provenance if provenance is not None else _object(read_file(root / source_file), source_file)
    host, payload = metadata.get("host"), metadata.get("payload_sha256")
    if (type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1
            or metadata.get("product") != "workflow-core" or not isinstance(host, str)
            or host not in MANIFESTS or not isinstance(payload, dict) or (expected is not None and host != expected)):
        raise TaskGraphError("plugin host adapter provenance does not match the physical package")
    manifest_name = MANIFESTS[host]
    if present.intersection((*MANIFESTS.values(), "plugin.json")) != {manifest_name}:
        raise TaskGraphError("plugin host adapter requires its unique native manifest")

    def verified(relative: str) -> bytes:
        body = read_file(root / relative)
        if body is None or sha256(body).hexdigest() != payload.get(relative):
            raise TaskGraphError("plugin host adapter payload digest mismatch: " + relative)
        return body

    entry = _object(verified(ENTRY), ENTRY)
    if type(entry.get("schema_version")) is not int or entry != {
        "schema_version": 1, "host": host, "manifest_target": manifest_name,
    }:
        raise TaskGraphError("plugin host adapter entry does not match the physical package")
    manifest = _object(verified(manifest_name), manifest_name)
    if (not isinstance(metadata.get("plugin_name"), str) or not isinstance(metadata.get("plugin_version"), str)
            or manifest.get("name") != metadata["plugin_name"] or manifest.get("version") != metadata["plugin_version"]):
        raise TaskGraphError("plugin host adapter native manifest has a different identity or version")
    # 普通 helper 已由 source_pack 核完整载荷。原生 Hook 只核对其固定入口和策略
    # 文件；每次写工具调用都扫描整个 ZIP 展开树会显著增加同步 Hook 的开销。
    for relative in resources:
        verified(relative)
    return host


def dispatch_policy(pm_id: str | None = None, *, reference_host: str | None = None) -> DispatchPolicy:
    host = packaged_host()
    # 源码的旧测试和本地入口一直用 PM/候选身份演练 AGY。实体包只接受自己的装配，
    # 即使传入另一宿主的 --host 或 --pm-id，也不能加载别端的原生证据解释器。
    source_agy = host is None and ((pm_id or "").startswith("antigravity:") or reference_host == "antigravity")
    if host == "antigravity" or source_agy:
        from lib.hosts.antigravity_dispatch import AntigravityDispatch
        return AntigravityDispatch(pm_id)
    if (pm_id or "").startswith("antigravity:"):
        raise TaskGraphError("AGY native dispatch requires the Antigravity plugin package")
    return DEFAULT_DISPATCH


def handoff_policy(host: str | None) -> HandoffPolicy:
    """从已经核对的实体包身份选择交接位置。"""
    if host == "antigravity":
        from lib.hosts.antigravity_handoff import ANTIGRAVITY_HANDOFF
        return ANTIGRAVITY_HANDOFF
    return SYSTEM_HANDOFF
