"""网页及脚本共用的原生 Agent 文件服务；无工作流角色或中央安装依赖。"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import os
from pathlib import Path
import re
import secrets
import threading
import time

from . import activation, activation_codecs, adapters, catalog as model_catalog, codecs, inventory, storage
from .contracts import (ConfigError, ConflictError, FIELDS, HOSTS, MAX_BATCH,
                        MAX_INVENTORY_BYTES, absolute_path, host_name, json_bytes,
                        unique_json, validate_fields)
from .version_probe import observe_claude_version


@dataclass(frozen=True)
class _Context:
    host: str
    scope: str
    project: Path | None
    inventory: inventory.Inventory
    activation: activation.Activation
    revision: str


@dataclass(frozen=True)
class _Plan:
    before: _Context
    writes: tuple[storage.Write, ...]
    created: float

    @property
    def cost(self):
        return self.before.inventory.total_bytes + self.before.activation.total_bytes + sum(len(item.after) for item in self.writes)


class ModelService:
    def __init__(self, data_dir: Path, home: Path | None = None, *, client_versions: dict | None = None):
        self.data_dir = absolute_path(data_dir)
        self.home = absolute_path(home if home is not None else Path.home())
        # 恢复入口必须保留“显式隔离 home”与“宿主环境选根”的区别。
        # 仅保存最终 home 路径会丢失这一来源，重开时无条件传 --home 将使
        # CODEX_HOME / CLAUDE_CONFIG_DIR 原有覆盖语义失效。
        self._explicit_home = home is not None
        self.environment = dict(os.environ)
        self.environment["HOME"] = str(self.home)
        # 显式 home 是测试/脚本隔离边界；父进程的真实宿主定位不能覆盖它。
        self.host_roots = {"codex": self.home / ".codex", "claude": self.home / ".claude",
                           "antigravity": self.home / ".gemini/config"}
        if home is None:
            for host, variable in (("codex", "CODEX_HOME"), ("claude", "CLAUDE_CONFIG_DIR")):
                if self.environment.get(variable):
                    self.host_roots[host] = absolute_path(self.environment[variable])
        self.environment.update(CODEX_HOME=str(self.host_roots["codex"]),
                                CLAUDE_CONFIG_DIR=str(self.host_roots["claude"]))
        if client_versions is not None and (not isinstance(client_versions, dict) or set(client_versions) - set(HOSTS)):
            raise ConfigError("可信宿主版本无效")
        self._versions = dict(client_versions or {})
        if any(not isinstance(value, str) or not re.fullmatch(r"\d{1,6}\.\d{1,6}\.\d{1,6}", value) for value in self._versions.values()):
            raise ConfigError("可信宿主版本须是稳定版本号")
        self._version_status, self._catalogs, self._plans = {}, {}, {}
        self._lock = threading.RLock()

    def _capture(self, host, scope="global", project=None):
        host_name(host)
        if not isinstance(scope, str) or scope not in {"global", "project"}:
            raise ConfigError("配置范围无效")
        if (scope == "project") != (project is not None):
            raise ConfigError("项目范围必须指定绝对项目路径，通用范围不指定项目")
        path = absolute_path(project) if project is not None else None
        identity = storage.project_identity(path) if path is not None else ()
        found = inventory.discover(host, self.home, path, host_roots=self.host_roots)
        enabled = activation.capture(host, scope, path, self.host_roots[host], data_dir=self.data_dir,
                                     home=self.home if self._explicit_home else None,
                                     environment=self.environment)
        revision = hashlib.sha256(json_bytes([host, scope, str(path) if path else None, identity, found.revision(), enabled.revision()])).hexdigest()
        return _Context(host, scope, path, found, enabled, revision)

    def _capabilities(self, host):
        return adapters.capabilities(host, self._versions.get(host), self._version_status.get(host, "not_probed"))

    @staticmethod
    def _writable(agent, scope):
        if agent.origin == "plugin":
            return False, "Plugin assets are read-only; no official per-agent override is assumed."
        if (scope == "global" and agent.origin != "user") or (scope == "project" and agent.origin != "project"):
            return False, "Select the definition's own scope before editing its native file."
        if not agent.snapshot.identity[2] & 0o200:
            return False, "The native definition has no owner write permission."
        return True, None

    def _row(self, agent, scope, *, complete=True):
        fields = dict(agent.document.fields)
        view = adapters.invocation(agent.host, agent.invoke_name, fields, version=self._versions.get(agent.host),
                                   definition_status=agent.definition_status,
                                   resolution_complete=complete and agent.invoke_name_verified)
        writable, reason = self._writable(agent, scope)
        return {"role": agent.id, "name": agent.document.name, "native_name": agent.document.name,
                "invoke_name": agent.invoke_name, "origin": agent.origin, "scope": agent.scope,
                "invoke_name_verified": agent.invoke_name_verified, "inventory_complete": complete,
                "source_path": str(agent.path), "source_identity": agent.source_id, "plugin": agent.plugin,
                "description": "".join(char for char in agent.document.description if char.isprintable())[:512],
                "writable": writable, "read_only_reason": reason, "enabled": agent.enabled,
                "definition_status": agent.definition_status, "shadowed": agent.definition_status == "shadowed",
                "shadowed_by": agent.shadowed_by, "effective_definition": agent.definition_status == "effective_in_discovered_sources",
                "overrides": fields, "effective": {field: fields.get(field, "inherit") for field in FIELDS},
                "effective_scope": "native_definition_preferences",
                "sources": {field: agent.origin if field in fields else "host_unresolved" for field in FIELDS},
                "dispatch_ready": view["dispatch_ready"], "invoke_ready": view["invoke_ready"],
                "blocked_reason": view["blocked_reason"], "per_invocation": view["per_invocation"],
                "runtime_verified": False}

    def _public(self, state):
        return {"host": state.host, "scope": state.scope, "project": str(state.project) if state.project else None,
                "revision": state.revision, "roles": [self._row(agent, state.scope, complete=state.inventory.complete) for agent in state.inventory.agents],
                "capabilities": self._capabilities(state.host), "diagnostics": state.inventory.diagnostics,
                "workflow_activation": state.activation.public,
                "runtime_verified": False, "inventory_complete": state.inventory.complete,
                "discovery_scope": "documented_local_files_and_observed_install_records"}

    def context(self, host, scope="global", project=None):
        return self._public(self._capture(host, scope, project))

    def _selection(self, state, values):
        cached = self._catalogs.get((state.host, str(state.project)))
        if cached is None or state.host != "codex":
            return "Model and effort capability are unverified; saving a definition does not verify execution."
        try:
            fresh = model_catalog.source_stamp(self.host_roots[state.host], state.project)
        except (ValueError, OSError):
            return "Model capability source is unavailable; capability remains unverified."
        if cached.get("source_stamp") != fresh:
            return "Model capability source changed; explicitly refresh the catalog."
        selected = next((row for row in cached["models"] if row["id"] == values.get("model")), None)
        if selected is not None and selected.get("efforts_verified") and "effort" in values:
            if values["effort"] not in selected["efforts"]:
                raise ConfigError("实际模型目录不支持所选推理档位；请清除 effort 或使用目录档位")
            return "Reasoning capability metadata was observed; actual model execution remains unverified."
        return "Model capability remains unverified for this definition."

    def preview(self, request):
        request = unique_json(json_bytes(request))
        if (not isinstance(request, dict) or "host" not in request
                or set(request) - {"host", "scope", "project", "revision", "edits", "reset", "workflow_activation"}):
            raise ConfigError("预览请求字段无效")
        if "workflow_activation" in request and ({"edits", "reset"} & set(request)):
            raise ConfigError("工作流启停不能与模型编辑或重置混合预览")
        state = self._capture(request["host"], request.get("scope", "global"), request.get("project"))
        if not isinstance(request.get("revision"), str) or request["revision"] != state.revision:
            raise ConflictError("原生 Agent 清单或文件在编辑后变化")
        if "workflow_activation" in request:
            writes, changes, warnings = activation.preview(state.activation, request["workflow_activation"])
            return self._store_preview(state, writes, changes, warnings)
        edits, reset = request.get("edits", {}), request.get("reset", False)
        if not isinstance(edits, dict) or type(reset) is not bool or (reset and edits):
            raise ConfigError("编辑与重置参数无效")
        agents = {agent.id: agent for agent in state.inventory.agents}
        warnings = ["Native files are saved directly; current-session loading and actual execution are unverified."]
        if reset:
            edits = {agent.id: {field: None for field in agent.document.fields}
                     for agent in state.inventory.agents if self._writable(agent, state.scope)[0] and agent.document.fields}
            warnings.append("Reset clears model/effort only in writable definitions of the selected scope; plugin assets and agent bodies are preserved.")
        if len(edits) > MAX_BATCH:
            raise ConfigError("一次最多编辑 64 个原生 Agent")
        changes, writes = [], []
        for opaque, fields in edits.items():
            if opaque not in agents:
                raise ConfigError("Agent ID 不属于当前发现清单")
            agent = agents[opaque]
            writable, reason = self._writable(agent, state.scope)
            if not writable:
                raise ConfigError("Agent 为只读来源，请选择可写原生定义")
            if not isinstance(fields, dict) or not fields:
                raise ConfigError("每个 Agent 须给出部分模型字段")
            checked = validate_fields(state.host, fields, edits=True)
            after = codecs.patch(state.host, agent.snapshot.body, checked)
            after_fields = codecs.parse(state.host, after).fields
            warnings.append(self._selection(state, after_fields))
            if after == agent.snapshot.body:
                continue
            writes.append(storage.Write(opaque, agent.path, agent.snapshot, after))
            for field in FIELDS:
                before, new = agent.document.fields.get(field), after_fields.get(field)
                if before != new:
                    changes.append({"role": opaque, "name": agent.document.name, "origin": agent.origin,
                                    "field": field, "before": before, "after": new,
                                    "effective_before": before or "inherit", "effective_after": new or "inherit",
                                    "source_before": agent.origin if before is not None else "host_unresolved",
                                    "source_after": agent.origin if new is not None else "host_unresolved"})
        if sum(len(item.after) for item in writes) > 8 * 1024 * 1024:
            raise ConfigError("一次批量原生文件超过容量限制")
        return self._store_preview(state, writes, changes, warnings)

    def _store_preview(self, state, writes, changes, warnings):
        """启停和模型共用容量、TTL、单次消费与保存计划，不创建第二事务通道。"""
        plan = _Plan(state, tuple(writes), time.monotonic())
        with self._lock:
            self._plans = {key: value for key, value in self._plans.items() if plan.created - value.created < 900}
            if len(self._plans) >= 128 or sum(item.cost for item in self._plans.values()) + plan.cost > 32 * 1024 * 1024:
                raise ConfigError("服务端预览容量已满，请稍后重新预览")
            opaque = secrets.token_urlsafe(32)
            self._plans[opaque] = plan
        agents = {agent.id: agent for agent in state.inventory.agents}
        selected = [self._row(agents[item.role], state.scope, complete=state.inventory.complete) for item in writes if item.role in agents]
        blocked = [row["blocked_reason"] for row in selected if row["blocked_reason"]]
        return {"preview_id": opaque, "changes": changes, "warnings": list(dict.fromkeys(warnings)),
                "effect": adapters.effect(), "dispatch_ready": not blocked,
                "blocked_reason": "; ".join(dict.fromkeys(blocked)) or None}

    def apply(self, preview_id):
        if not isinstance(preview_id, str) or not 1 <= len(preview_id) <= 128:
            raise ConfigError("预览 ID 无效")
        with self._lock:
            plan = self._plans.pop(preview_id, None)
            if plan is None or time.monotonic() - plan.created >= 900:
                raise ConflictError("预览不存在、已使用或已过期")
            before = plan.before
            creating = any(item.before.body is None for item in plan.writes)
            def guard(*, initial=False):
                now = self._capture(before.host, before.scope, before.project)
                # 首次 mkdir 是 storage 已核实目录链后的自有变化。其余文件、
                # 安装身份、继承来源仍逐次检查；目标父目录由 storage 的原链
                # 前像检查及全程持有的 no-follow 描述符负责，不能被普通回读替代。
                same = now.revision == before.revision
                if creating and not initial:
                    same = (now.inventory.revision() == before.inventory.revision()
                            and now.activation.revision(include_target_parent=False)
                            == before.activation.revision(include_target_parent=False))
                if not same:
                    raise ConflictError("原生 Agent 来源在预览后变化，请重新预览")
                for item in plan.writes:
                    if item.role == "workflow_activation":
                        activation_codecs.parse(before.host, item.after)
                    else:
                        codecs.parse(before.host, item.after)
            guard(initial=True)
            result = storage.write_batch(plan.writes, guard)
            response = {**result, "effect": adapters.effect(saved=result["saved"],
                        published=result["published"] or result.get("namespace_touched", False))}
            try:
                response["context"] = self.context(before.host, before.scope, before.project)
            except (ValueError, OSError):
                # 发布结果和恢复资料比刷新展示更重要；回读失败不能掩盖已发生的
                # 部分写入，也不能要求调用方重复提交已经消费的同一计划。
                response.update(context_unavailable=True,
                                context_diagnostic="Native files could not be reread safely; preserve per-agent save and recovery results before refreshing.")
            return response

    def catalog(self, host, project=None):
        state = self._capture(host, "project" if project is not None else "global", project)
        if host == "claude":
            try:
                observed = observe_claude_version(self.environment)
            except (OSError, ValueError):
                observed = {"status": "probe_failed", "version": None}
            self._version_status[host] = observed["status"]
            if observed["version"] is None:
                self._versions.pop(host, None)
            else:
                self._versions[host] = observed["version"]
        try:
            result = model_catalog.discover(host, self.host_roots[host], state.project, self.environment)
            if host == "codex":
                result["source_stamp"] = model_catalog.source_stamp(self.host_roots[host], state.project)
        except (ValueError, OSError, TypeError, RecursionError):
            result = {"host": host, "status": "failed", "models": [], "notes": ["Official model discovery failed; native saved values remain visible."], "runtime_verified": False}
        self._catalogs[(host, str(state.project))] = copy.deepcopy(result)
        result = {**result, "models": copy.deepcopy(result["models"]), "capabilities": self._capabilities(host)}
        known = {row["id"] for row in result["models"]}
        for agent in state.inventory.agents:
            model = agent.document.fields.get("model")
            if model and model not in known:
                result["models"].append({"id": model, "label": model, "source": "saved_native_definition_unverified", "efforts": [], "efforts_verified": False})
                known.add(model)
        return result

    def resolve_subagent(self, host, role, project=None):
        if not isinstance(role, str) or not re.fullmatch(r"agent_[0-9a-f]{64}", role):
            raise ConfigError("必须使用发现清单中的 opaque Agent ID")
        state = self._capture(host, "project" if project is not None else "global", project)
        agent = next((agent for agent in state.inventory.agents if agent.id == role), None)
        if agent is None:
            raise ConfigError("Agent ID 不属于当前发现清单")
        row = self._row(agent, state.scope, complete=state.inventory.complete)
        return {"host": host, **row,
                **adapters.invocation(host, agent.invoke_name, agent.document.fields,
                                      version=self._versions.get(host), definition_status=agent.definition_status,
                                      resolution_complete=state.inventory.complete and agent.invoke_name_verified),
                "capabilities": self._capabilities(host), "effect": adapters.effect(),
                "warnings": ["Named invocation relies on the official host discovering this exact definition. Managed policy and the current session remain unobserved."]}
