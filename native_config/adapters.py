"""区分原生定义、命名调用及额外调用覆盖；任何投影都不是运行验收。"""

from __future__ import annotations

import re

from .contracts import (AGY_TIERS, CLAUDE_ALIASES, CLAUDE_EFFORTS, DOCUMENTATION,
                        host_name)


def capabilities(host, version=None, version_status="not_probed"):
    host_name(host)
    return {"model": True, "effort": host != "antigravity", "native_file_writes": True,
            "plugin_writes": False, "runtime_verified": False, "actual_runtime": "unobserved",
            "configuration_fields": ["model", "model_reasoning_effort"] if host == "codex" else
                                    (["model", "effort"] if host == "claude" else ["model"]),
            "efforts": [] if host == "antigravity" else list(CLAUDE_EFFORTS) if host == "claude" else
                       ["low", "medium", "high", "xhigh", "max", "ultra"],
            "effort_capability_status": "model_dependent_unverified" if host == "codex" else "documented",
            "model_aliases": list(CLAUDE_ALIASES) if host == "claude" else list(AGY_TIERS) if host == "antigravity" else [],
            "client_version": version, "client_version_status": "observed" if version else version_status,
            "per_invocation_effort_minimum_version": "2.1.292" if host == "claude" else None,
            "invoke_schema_status": "unverified" if host == "antigravity" else "documented",
            "explicit_inherit": {"model": "clear_field" if host == "codex" else "native_explicit_inherit",
                                 "effort": "unsupported" if host == "antigravity" else "clear_field"},
            "clear_field_semantics": "Remove this field from this complete definition; defer to official host resolution, not another same-name agent definition.",
            "documentation": DOCUMENTATION[host],
            "note": "Native definitions are complete definitions, not field-level overlays. Managed policy, session flags, environment, reload behavior and actual execution remain unverified."}


def effect(*, saved=False, published=False):
    return {"saved": saved, "pending_reload": published, "runtime_verified": False,
            "running_agents_changed": False, "cross_filesystem_crash_atomic": False,
            "message": "Saved native files require the official host to reload or rediscover definitions. Running agents and actual model execution are unverified. Multi-file publication is not a cross-filesystem crash-atomic transaction."}


def invocation(host, name, fields, *, version=None, definition_status="effective_in_discovered_sources", resolution_complete=True):
    configuration = {("model_reasoning_effort" if host == "codex" and key == "effort" else key): value
                     for key, value in fields.items()}
    parameters, blocked = {}, []
    model, effort = fields.get("model"), fields.get("effort")
    if model and model != "inherit":
        if host == "claude" and model not in CLAUDE_ALIASES:
            blocked.append("Full Claude model IDs are valid in native definitions, but the Agent call model override accepts aliases only.")
        elif host != "antigravity":
            parameters["model"] = model
    if effort:
        if host == "codex":
            if effort in {"low", "medium", "high", "xhigh", "max", "ultra"}:
                parameters["reasoning_effort"] = effort
            else:
                blocked.append("The native effort is outside the observed spawn_agent reasoning_effort enum; only the named definition is used.")
        elif host == "claude":
            stable = tuple(map(int, version.split("."))) if isinstance(version, str) and re.fullmatch(r"\d{1,6}\.\d{1,6}\.\d{1,6}", version) else None
            if stable is not None and stable >= (2, 1, 292):
                parameters["effort"] = effort
            else:
                blocked.append("The optional per-invocation effort override requires an observed Claude Code >= 2.1.292; the native definition effort remains independently writable.")
    ready = definition_status == "effective_in_discovered_sources"
    reasons = [] if ready else ["This definition is shadowed, ambiguous, disabled, or plugin enablement is unobserved."]
    if not resolution_complete:
        ready = False
        reasons.append("Native discovery or the invocation namespace is incomplete; a unique official named definition cannot be confirmed.")
    if host == "antigravity":
        dispatch = {}
        ready = False
        reasons.append("The invoke_subagent argument schema is unobserved; no invocation model parameter is invented.")
        blocked.append(reasons[-1])
    else:
        dispatch = {"agent_type" if host == "codex" else "subagent_type": name} if ready else {}
    return {"configuration_fields": configuration, "dispatch": dispatch,
            "dispatch_ready": ready, "invoke_ready": ready, "blocked_reason": "; ".join(reasons) or None,
            "per_invocation": {"parameters": parameters, "ready": not blocked,
                               "blocked_reason": "; ".join(blocked) or None},
            "runtime_verified": False, "runtime_status": "unverified"}
