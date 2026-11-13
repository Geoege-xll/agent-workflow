/* 原生 Agent 配置页面：请求协议、草稿状态和 DOM 展示分别在本文件的三个边界内维护。
 * 不缓存令牌到磁盘，不根据 Agent 名字推断权限，也不把保存成功当作实际模型运行收据。 */
(() => {
  "use strict";

  const HOSTS = ["codex", "claude", "antigravity"];
  const HOST_LABELS = { codex: "Codex", claude: "Claude Code", antigravity: "Antigravity" };
  const FIELDS = ["model", "effort"];
  const FIELD_LABELS = { model: "模型", effort: "推理级别" };
  const ACTIVATION_STATES = ["inherit", "enabled", "disabled"];
  const ACTIVATION_LABELS = { inherit: "继承（无本层覆盖）", enabled: "启用", disabled: "停用", unknown: "未知" };
  const activationLabel = value => ACTIVATION_LABELS[value] || "未知";
  const SOURCE_LABELS = { host: "宿主", host_unresolved: "宿主默认未观察", host_default: "宿主默认", global: "用户级", user: "用户级", project: "项目", plugin: "插件", default: "通用默认", configured: "历史偏好", user_default: "用户通用", user_agent: "用户该 Agent", project_default: "项目通用", project_agent: "项目该 Agent" };
  const DEFINITION_LABELS = { shadowed: "被其他来源遮蔽", ambiguous: "定义存在歧义", disabled: "已禁用", installation_observed: "仅观察到安装，启用状态未知", effective_in_discovered_sources: "在已发现来源中生效，会话加载未验证" };
  const SAVE_LABELS = { saved: "已保存", published_location_unknown: "新内容已发布，目标当前位置未核实", not_written: "未写入", rolled_back: "已回滚并恢复前像内容", rolled_back_location_unknown: "已恢复前像内容，目标当前位置未核实", rollback_conflict: "回滚冲突，已保留相关对象与资料", rolled_back_durability_unverified: "已恢复可见前像内容，磁盘耐久性未验证", recovery_required: "需要人工检查保留资料" };
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const locationKey = location => JSON.stringify([location.host, location.scope, location.scope === "project" ? location.project : null]);
  const sourceLabel = value => SOURCE_LABELS[value] || (typeof value === "string" && value ? value : "来源未提供");
  const fieldValue = value => value === null || value === undefined ? "删除本层覆盖" : value === "inherit" ? "直接跟随宿主（inherit）" : value;

  class ApiError extends Error {
    constructor(code, message, status = 0) { super(message); this.code = code; this.status = status; }
  }

  function applyReceiptContract(value, status = 0) {
    const optionalBoolean = (record, key) => !own(record, key) || typeof record[key] === "boolean";
    const mode = value => Number.isInteger(value) && value >= 0 && value <= 0o7777;
    const path = value => typeof value === "string" && value.startsWith("/") && !/[\x00-\x1f]/.test(value);
    const locationStatus = value => ["verified_at_finalization", "unknown"].includes(value);
    const identity = value => value === null || (Array.isArray(value) && value.length >= 2 && value.every(Number.isInteger) && value[0] >= 0 && value[1] >= 0);
    // unknown 必须配合空当前位置和原声明位置；既不能把旧路径继续渲染成可定位，
    // 也不能接受只给 null 而没有可解释位置状态的任意错误正文。
    const recoveryLocation = row => row.location_status === "unknown" ? row.backup === null && path(row.declared_backup) :
      path(row.backup) && (!own(row, "location_status") || locationStatus(row.location_status)) &&
      (!own(row, "declared_backup") || path(row.declared_backup));
    // HTTP 成功和明确失败共用同一收据边界。恢复路径只能按文字展示，不能据此发起文件操作；
    // isolated_object 可能是外部对象，摘要可为 null，权限数字只作为服务端报告的只读证据。
    if (!object(value) || typeof value.saved !== "boolean" || !object(value.effect) ||
        ["partial_failure", "published", "namespace_touched", "temporary_visibility_gap", "context_unavailable", "finalization_failed"].some(key => !optionalBoolean(value, key)) ||
        (own(value, "retention_policy") && typeof value.retention_policy !== "string") ||
        (own(value, "finalization_error_type") && typeof value.finalization_error_type !== "string") ||
        (own(value, "cleanup_pending_location_status") && !locationStatus(value.cleanup_pending_location_status)) ||
        ["saved", "pending_reload", "runtime_verified"].some(key => !optionalBoolean(value.effect, key)) ||
        (own(value, "results") && (!Array.isArray(value.results) || value.results.some(row => !object(row) || typeof row.role !== "string" || typeof row.status !== "string"))) ||
        (own(value, "recovery") && (!Array.isArray(value.recovery) || value.recovery.some(row => !object(row) || typeof row.role !== "string" || !path(row.target) || !recoveryLocation(row) ||
          (own(row, "sha256") && row.sha256 !== null && (typeof row.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(row.sha256))) ||
          ["kind", "sha256_semantics", "retention", "object_role"].some(key => own(row, key) && typeof row[key] !== "string") ||
          !optionalBoolean(row, "content_may_change") || ["observed_identity", "container_identity"].some(key => own(row, key) && !identity(row[key])) ||
          (own(row, "container_mode") && !mode(row.container_mode)) ||
          (own(row, "original_mode") && row.original_mode !== null && !mode(row.original_mode))))) ||
        (own(value, "cleanup_pending") && (!Array.isArray(value.cleanup_pending) || value.cleanup_pending.some(item => !path(item))))) {
      throw new ApiError("invalid_response", "保存回执格式无效，草稿已保留；请重新读取配置后确认。", status);
    }
    // 首次创建失败也可能已经留下真实目录或文件；只读展示核心收据，不据路径提供删除/回滚操作。
    // location_status=unknown 时目标只能标作原声明位置，不能冒称文件仍在该路径。
    if ((own(value, "created_directories") && (!Array.isArray(value.created_directories) || value.created_directories.some(item => !path(item)))) ||
        (own(value, "created_files") && (!Array.isArray(value.created_files) || value.created_files.some(row => !object(row) ||
          typeof row.role !== "string" || !path(row.target) || row.before_absent !== true || typeof row.published !== "boolean" ||
          !identity(row.observed_identity) || !locationStatus(row.location_status) || typeof row.recovery_action !== "string")))) {
      throw new ApiError("invalid_response", "首次创建收据格式无效，草稿已保留；请重新读取配置。", status);
    }
    if (value.context) value.context = contextContract(value.context);
    else if (value.saved && !applyFailed(value) && value.context_unavailable !== true) {
      throw new ApiError("invalid_response", "保存状态缺少配置回读，请重新读取后确认。", status);
    }
    return value;
  }

  function applyFailed(value) {
    // 第一次正式发布被外部文件阻止时 partial_failure 仍可能为 false，但命名空间已变动、
    // 恢复证据已产生。saved、错误、逐项状态和恢复/清理资料必须共同决定后续恢复流程。
    return value.saved !== true || value.partial_failure === true || value.effect?.saved === false || own(value, "error") ||
      (value.results || []).some(row => row.status !== "saved");
  }
  function applyNeedsAttention(value) {
    // 成功发布也可以正常保留原inode与不可变前像。保留资料需要展示，不能据其存在宣称失败。
    return applyFailed(value) || Boolean(value.recovery?.length) || Boolean(value.cleanup_pending?.length);
  }

  function contextContract(value) {
    // 先核验当前界面实际消费的必需字段；新增的来源/权限字段保留原样，不猜测其含义。
    if (!object(value) || !HOSTS.includes(value.host) || !["global", "project"].includes(value.scope) ||
        typeof value.revision !== "string" || !Array.isArray(value.roles) || !object(value.capabilities)) {
      throw new ApiError("invalid_response", "配置服务返回了无法识别的数据，请重新读取。");
    }
    const identifiers = new Set();
    for (const row of value.roles) {
      if (!object(row) || typeof row.role !== "string" || !row.role || identifiers.has(row.role) ||
          !object(row.overrides) || !object(row.effective) || !object(row.sources) ||
          FIELDS.some(field => own(row.overrides, field) && typeof row.overrides[field] !== "string")) {
        throw new ApiError("invalid_response", "Agent 配置行无效；已保留当前草稿。");
      }
      identifiers.add(row.role);
    }
    if (own(value, "dispatch_preferences")) preferenceContract(value.dispatch_preferences);
    if (own(value, "workflow_activation")) {
      activationContract(value.workflow_activation);
      if (value.workflow_activation.scope !== value.scope) throw new ApiError("invalid_response", "工作流配置范围不一致，草稿已保留。");
    }
    return value;
  }

  function preferenceContract(value) {
    // 调用身份、可写权限与运行能力分别校验，dispatch_ready=false 不能被解释为禁止保存。
    if (!object(value) || value.status !== "ready" || !object(value.capabilities) || !Array.isArray(value.targets) || value.runtime_verified !== false) {
      throw new ApiError("invalid_response", "调用偏好数据无效，草稿已保留，请重新读取。");
    }
    const ids = new Set();
    for (const row of value.targets) {
      if (!object(row) || typeof row.target !== "string" || !row.target || ids.has(row.target) ||
          !object(row.overrides) || !object(row.effective) || !object(row.sources) || typeof row.writable !== "boolean" ||
          FIELDS.some(field => own(row.overrides, field) && typeof row.overrides[field] !== "string")) {
        throw new ApiError("invalid_response", "调用偏好目标无效，未更新编辑入口。");
      }
      ids.add(row.target);
    }
    if (!ids.has("*")) throw new ApiError("invalid_response", "调用偏好缺少通用默认目标，请重新读取。");
    return value;
  }

  // 候选目录与保存的历史值分开。Claude 调用覆盖只接受 alias，AGY 子代理只接受 tier；
  // 会话完整 ID 即使在本机目录出现，也不能混进另一个参数合同。
  function modelCandidates(context, catalog, preference = false) {
    const caps = preference ? context?.dispatch_preferences?.capabilities : context?.capabilities;
    const values = new Map();
    const aliases = caps?.model_aliases || [];
    const tiers = caps?.model_tiers || [];
    for (const id of [...aliases, ...tiers]) values.set(id, {id, label:id, source:"documented_parameter_contract"});
    const rows = preference && context?.host === "antigravity" ? catalog?.subagent_models || [] : catalog?.models || [];
    for (const row of rows) {
      if (preference && caps?.model_format === "alias" && !aliases.includes(row.id)) continue;
      if (preference && caps?.model_format === "tier" && !tiers.includes(row.id)) continue;
      if (row.usage === "session_only") continue;
      values.set(row.id, row);
    }
    return [...values.values()];
  }
  function effortOptions(context, catalog, model, preference = false) {
    const caps = preference ? context?.dispatch_preferences?.capabilities : context?.capabilities;
    if (caps?.effort === false) return {values:[], verified:true, note:"当前平台不支持独立推理级别；已有值保留，可清除。"};
    const selected = modelCandidates(context, catalog, preference).find(row => row.id === model);
    if (selected?.efforts_verified === true) return {values:selected.efforts || [], verified:true, note:"推理档位来自当前模型的本机目录元数据，实际运行未验证。"};
    // 未知能力只能显示工具合同允许的值并明确标记，不能把其他模型的档位并集当作本模型能力。
    return {values:caps?.efforts || [], verified:false, note:"当前模型的推理能力未核实；以下为工具合同候选，保存后仍须确认调用支持。"};
  }

  function activationContract(value) {
    // 启停是独立协议，未知值绝不能按“启用”回退；可写身份完全以核心的明确报告为准。
    const nullableString = value => value === null || typeof value === "string";
    if (!object(value) || typeof value.supported !== "boolean" || typeof value.writable !== "boolean" ||
        ![...ACTIVATION_STATES, "unknown"].includes(value.state) ||
        !["enabled", "disabled", "unknown"].includes(value.effective_state) ||
        !["enabled", "disabled", "unknown"].includes(value.inherited_state) ||
        !nullableString(value.plugin_id) || !nullableString(value.source_path) || !nullableString(value.inherited_source) ||
        !["global", "project"].includes(value.scope) || value.runtime_verified !== false ||
        !Array.isArray(value.diagnostics) || value.diagnostics.some(row => !object(row) || typeof row.code !== "string" || typeof row.message !== "string") ||
        !object(value.recovery) || typeof value.recovery.open_command !== "string" ||
        !Array.isArray(value.recovery.official_steps) || value.recovery.official_steps.some(step => typeof step !== "string") ||
        !nullableString(value.recovery.documentation_url) || !nullableString(value.read_only_reason) ||
        (value.writable && (!value.supported || !value.plugin_id || !value.source_path || value.state === "unknown"))) {
      throw new ApiError("invalid_response", "工作流启停数据无效，草稿已保留，请重新读取。");
    }
    return value;
  }

  class ModelApi {
    constructor(token, fetcher = globalThis.fetch.bind(globalThis), timeout = 45000) {
      this.token = token; this.fetcher = fetcher; this.timeout = timeout;
    }
    async request(path, body, signal, errorReceipt) {
      if (!this.token) throw new ApiError("authentication", "连接令牌缺失。请回到宿主主会话，显式运行 xy-workflow:xy-config Skill 重新打开配置页。");
      const controller = new AbortController();
      let timedOut = false;
      const cancel = () => controller.abort();
      if (signal?.aborted) cancel();
      else signal?.addEventListener("abort", cancel, { once: true });
      const timer = setTimeout(() => { timedOut = true; controller.abort(); }, this.timeout);
      try {
        const headers = { Authorization: "Bearer " + this.token, Accept: "application/json" };
        if (body !== undefined) headers["Content-Type"] = "application/json";
        const response = await this.fetcher(path, { method: body === undefined ? "GET" : "POST", headers,
          body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
          cache: "no-store", credentials: "omit", redirect: "error" });
        let value;
        try { value = await response.json(); }
        catch (_) { throw new ApiError("invalid_response", "配置服务返回格式异常，请重新读取。", response.status); }
        if (!response.ok) {
          const error = object(value?.error) ? value.error : {};
          const code = typeof error.code === "string" ? error.code : "request_failed";
          const message = response.status === 401 || response.status === 403 ? "连接验证失败。请回到宿主主会话，显式运行 xy-workflow:xy-config Skill 重新打开配置页。" :
            typeof error.message === "string" ? error.message : "请求未完成，请重试。";
          const failure = new ApiError(code, message, response.status);
          // 错误正文也可能携带核心已发生写入的正式收据；由所属业务API显式识别与校验，
          // 普通鉴权/冲突错误不获得恢复收据，不能借任意错误JSON冒充保存结果。
          const receipt = errorReceipt?.(value, response.status, code);
          if (receipt !== undefined) failure.receipt = receipt;
          throw failure;
        }
        if (!object(value)) throw new ApiError("invalid_response", "配置服务返回数据无效。");
        return value;
      } catch (error) {
        if (error instanceof ApiError) throw error;
        if (signal?.aborted) throw new ApiError("cancelled", "请求已取消。");
        throw new ApiError(timedOut ? "timeout" : "network", timedOut ? "请求超时。草稿已保留，请稍后重试。" : "无法连接本机配置服务。草稿已保留，请确认服务仍在运行。");
      } finally {
        clearTimeout(timer); signal?.removeEventListener("abort", cancel);
      }
    }
    async context(location, signal) {
      const query = new URLSearchParams({ host: location.host, scope: location.scope });
      if (location.scope === "project") query.set("project", location.project);
      return contextContract(await this.request("/api/context?" + query, undefined, signal));
    }
    async catalog(location, signal) {
      const query = new URLSearchParams({ host: location.host });
      if (location.scope === "project") query.set("project", location.project);
      const value = await this.request("/api/catalog?" + query, undefined, signal);
      if (!Array.isArray(value.models) || value.models.some(row => !object(row) || typeof row.id !== "string")) {
        throw new ApiError("invalid_response", "模型目录格式无效，已保留已有候选与选择。");
      }
      return value;
    }
    async preview(location, revision, edits, reset, signal) {
      const body = { host: location.host, scope: location.scope, revision, edits };
      if (location.scope === "project") body.project = location.project;
      if (reset) body.reset = true;
      const value = await this.request("/api/preview", body, signal);
      if (typeof value.preview_id !== "string" || !Array.isArray(value.changes) ||
          value.changes.some(row => !object(row) || typeof row.role !== "string" || !FIELDS.includes(row.field)) ||
          !Array.isArray(value.warnings) || !object(value.effect)) {
        throw new ApiError("invalid_response", "变更预览格式无效，未执行保存。");
      }
      return value;
    }
    async previewPreferences(location, revision, edits, reset = false, signal) {
      // 三种事务互斥：本入口不携带外层 edits/reset 或 workflow_activation，连空值也不发送。
      const body = {host:location.host, scope:location.scope, revision, dispatch_preferences:{edits, reset}};
      if (location.scope === "project") body.project = location.project;
      const value = await this.request("/api/preview", body, signal);
      if (typeof value.preview_id !== "string" || !Array.isArray(value.changes) ||
          value.changes.some(row => !object(row) || typeof row.target !== "string" || !FIELDS.includes(row.field)) ||
          !Array.isArray(value.warnings) || value.effect?.kind !== "dispatch_preferences" || value.effect.runtime_verified !== false) {
        throw new ApiError("invalid_response", "调用偏好预览格式无效，未执行保存。");
      }
      return value;
    }
    async previewActivation(location, revision, state, signal) {
      if (!ACTIVATION_STATES.includes(state)) throw new ApiError("invalid_input", "请选择继承、启用或停用。");
      // 服务端拒绝混合 edits/reset，包括空对象和 false；专用入口从构造时保证请求互斥。
      const body = { host: location.host, scope: location.scope, revision, workflow_activation: { state } };
      if (location.scope === "project") body.project = location.project;
      const value = await this.request("/api/preview", body, signal);
      if (typeof value.preview_id !== "string" || !Array.isArray(value.changes) ||
          value.changes.some(row => !object(row) || row.kind !== "workflow_activation" || row.field !== "enabled" ||
            row.scope !== location.scope || typeof row.source_path !== "string" || typeof row.plugin_id !== "string" ||
            !ACTIVATION_STATES.includes(row.before) || !ACTIVATION_STATES.includes(row.after) ||
            !["enabled", "disabled", "unknown"].includes(row.effective_before) || !["enabled", "disabled", "unknown"].includes(row.effective_after)) ||
          !Array.isArray(value.warnings) || !object(value.effect)) {
        throw new ApiError("invalid_response", "工作流启停预览格式无效，未执行保存。");
      }
      return value;
    }
    async apply(previewId) {
      const value = await this.request("/api/apply", { preview_id: previewId }, undefined, (body, status, code) => {
        if (status !== 409 || code !== "partial_failure") return undefined;
        const receipt = applyReceiptContract(body, status);
        if (receipt.saved !== false || receipt.partial_failure !== true) {
          throw new ApiError("invalid_response", "失败回执与HTTP状态不一致，草稿已保留；请重新读取配置。", status);
        }
        return receipt;
      });
      return applyReceiptContract(value);
    }
  }

  class FieldDraft {
    constructor(location) {
      this.location = { ...location }; this.context = null; this.edits = new Map();
      this.selected = new Set(); this.catalog = null; this.catalogFailure = null; this.conflicted = false;
    }
    row(identifier) { return this.context?.roles.find(row => row.role === identifier); }
    value(identifier, field) {
      const changes = this.edits.get(identifier);
      return changes && own(changes, field) ? changes[field] : this.row(identifier)?.overrides[field] ?? null;
    }
    set(identifier, field, raw) {
      const row = this.row(identifier);
      if (!row || row.writable !== true || !FIELDS.includes(field)) return;
      const value = raw === "" || raw === null ? null : raw;
      const changes = { ...this.edits.get(identifier) };
      if (value === (row.overrides[field] ?? null)) delete changes[field];
      else changes[field] = value;
      if (Object.keys(changes).length) this.edits.set(identifier, changes);
      else this.edits.delete(identifier);
    }
    accept(context, clear = false) {
      this.context = context;
      // 一类操作保存成功只能清除自己的草稿；另一类草稿应在新 revision 上继续保留。
      // 重新读取只更新基线；保留用户明确改过的字段，避免冲突恢复时丢失草稿。
      const previous = clear === true || clear === "model" ? [] : [...this.edits].map(([id, fields]) => [id, { ...fields }]);
      this.edits.clear();
      for (const [id, fields] of previous) {
        // 已消失或变为只读的 Agent 保留草稿供用户看到并明确放弃，绝不静默保存到别的 ID。
        if (!this.row(id) || this.row(id).writable !== true) this.edits.set(id, fields);
        else for (const [field, value] of Object.entries(fields)) this.set(id, field, value);
      }
      this.selected = new Set([...this.selected].filter(id => this.row(id)?.writable === true));
      this.conflicted = false;
    }
    get dirty() { return this.edits.size > 0; }
    get anyDirty() { return this.dirty; }
    get count() { return [...this.edits.values()].reduce((total, fields) => total + Object.keys(fields).length, 0); }
    get unavailableEdits() { return [...this.edits.keys()].filter(id => this.row(id)?.writable !== true); }
    payload() {
      // null 原样发送是删除覆盖；inherit 原样发送是显式宿主继承，两者不能合并。
      return Object.fromEntries([...this.edits].map(([id, fields]) => [id, { ...fields }]));
    }
    clear() { this.edits.clear(); this.conflicted = false; }
  }

  class Draft extends FieldDraft {
    constructor(location) {
      super(location);
      this.activation = new ActivationDraft(); this.preferences = new FieldDraft(location);
      this.lastSave = "尚未在本页保存"; this.receipt = null; this.catalogRevision = null; this.catalogStamp = null; this.catalogAttempt = null;
    }
    accept(context, clear = false) {
      super.accept(context, clear);
      this.activation.accept(context.workflow_activation, clear === "workflow_activation");
      // UI 内部沿用字段编辑器，但 target 始终保持服务端原生调用身份，绝不映射为伪造 Agent。
      const value = context.dispatch_preferences;
      this.preferences.accept({roles:(value?.targets || []).map(row => ({...row, role:row.target})), capabilities:value?.capabilities || {}}, clear === "dispatch_preferences");
    }
    get anyDirty() { return this.dirty || this.activation.dirty || this.preferences.dirty; }
  }

  class ActivationDraft {
    constructor() { this.saved = null; this.edit = null; }
    accept(value, clear = false) {
      this.saved = value || null;
      if (clear || this.edit === value?.state) this.edit = null;
    }
    get value() { return this.edit ?? this.saved?.state ?? "unknown"; }
    get dirty() { return this.edit !== null; }
    set(value) {
      if (this.saved?.writable !== true || !ACTIVATION_STATES.includes(value)) return;
      this.edit = value === this.saved.state ? null : value;
    }
    clear() { this.edit = null; }
  }

  function resolvedField(draft, id, field, preferences = false) {
    const row = draft.row(id);
    if (!row) return {value:null, source:"来源未提供", pending:true};
    const value = draft.value(id, field);
    if (value) return {value, source:draft.edits.get(id) && own(draft.edits.get(id), field) ? "本层草稿" : sourceLabel(row.sources[field]), pending:false};
    // 本层覆盖被清除后，context 不含其遮蔽的上层前像；必须交给真实预览解析，不能猜宿主默认。
    if (own(row.overrides, field)) return {value:null, source:"继承值待预览", pending:true};
    if (preferences && id !== "*") {
      const source = row.sources[field];
      const ownAgentSource = draft.location.scope === "project" ? "project_agent" : "user_agent";
      const defaultEdits = draft.edits.get("*");
      if (source !== ownAgentSource && defaultEdits && own(defaultEdits, field)) {
        const next = draft.value("*", field);
        if (next) return {value:next, source:"本层通用草稿", pending:false};
        // 只有被清除的默认字段原本参与了解析，才会遮蔽下层；其他目标继续保留权威基线。
        const defaultSource = draft.location.scope === "project" ? "project_default" : "user_default";
        if (source === defaultSource) return {value:null, source:"继承值待预览", pending:true};
      }
    }
    return {value:row.effective[field] ?? null, source:sourceLabel(row.sources[field]), pending:false};
  }

  class RequestOwner {
    constructor() { this.generation = 0; this.controller = null; }
    begin() { this.controller?.abort(); this.controller = new AbortController(); return { generation: ++this.generation, signal: this.controller.signal }; }
    current(ticket) { return ticket.generation === this.generation && !ticket.signal.aborted; }
    cancel() { this.controller?.abort(); this.generation++; }
  }

  // Node 用例直接消费同一协议/草稿逻辑，避免测试内重新实现继承或请求规则。
  if (typeof module !== "undefined" && module.exports) module.exports = { ModelApi, ApiError, Draft, ActivationDraft, RequestOwner, contextContract, activationContract, applyReceiptContract, applyFailed, applyNeedsAttention, locationKey, preferenceContract, modelCandidates, effortOptions, resolvedField };
  if (typeof document === "undefined") return;

  const $ = id => document.getElementById(id);
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const api = new ModelApi(fragment.get("token") || "");
  const initialHost = HOSTS.includes(fragment.get("host")) ? fragment.get("host") : "codex";
  const initialProject = fragment.get("project") || "";
  // fragment 只在当前内存使用。尽早从地址栏移除令牌，避免复制链接或浏览历史泄露。
  try { window.history.replaceState(null, "", window.location.pathname + window.location.search); } catch (_) { /* 受限浏览器允许继续，不复制令牌到其他存储。 */ }
  $("project-path").value = initialProject;
  const drafts = new Map();
  const loadOwner = new RequestOwner();
  const catalogOwner = new RequestOwner();
  const previewOwner = new RequestOwner();
  let active = null;
  let editorMode = "dispatch_preferences";
  let section = "models";
  let switchNoticeTimer = null;
  const kindName = () => section === "activation" ? "工作流启停" : preferenceMode() ? "调用偏好" : "原生定义文件";
  const visibleRows = () => editorRows().filter(row => !preferenceMode() || row.role !== "*");
  const preferenceMode = () => editorMode === "dispatch_preferences";
  const editorDraft = () => preferenceMode() ? active.preferences : active;
  const editorRows = () => editorDraft().context?.roles || [];
  const editorCaps = () => editorDraft().context?.capabilities || {};
  let loading = false;
  let refreshing = false;
  let mutation = false;
  let preview = null;
  let decision = null;
  let dialogTrigger = null;
  let decisionTrigger = null;

  function node(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    return result;
  }
  function message(text, tone = "info", target = $("feedback")) {
    target.textContent = text; target.dataset.tone = tone; target.hidden = !text;
  }
  function describeLocation(location) {
    return HOST_LABELS[location.host] + " · " + (location.scope === "global" ? "用户级" : "项目 " + location.project);
  }
  function followLabel() { return "清除字段（恢复宿主默认）"; }
  function writable(row) { return row.writable === true; }
  function readOnlyReason(row) {
    // 权限与来源仅展示服务端明确提供的字段；插件 ID 或文件路径都不能替代可写判定。
    const known = {"Plugin assets are read-only; no official per-agent override is assumed.":"插件缓存只读。请切换到调用偏好，为通用默认或此调用身份设置模型。", "Select the definition's own scope before editing its native file.":"此定义属于其他范围；切换到其用户级或项目范围后编辑原生文件。", "The native definition has no owner write permission.":"原生文件没有属主写权限；请核对文件权限，或使用独立调用偏好。"};
    return typeof row.read_only_reason === "string" ? known[row.read_only_reason] || row.read_only_reason :
      typeof row.writable_reason === "string" ? row.writable_reason : row.writable === false ? "此 Agent 不允许在当前范围写入。" : "服务端未提供写入权限，暂不可编辑。";
  }
  function effectiveDraftModel(id) {
    return resolvedField(editorDraft(), id, "model", preferenceMode()).value;
  }
  function currentCatalog() {
    // 模型来源有独立指纹；偏好或启停保存改变 revision 不意味着模型目录失效。
    // 空指纹代表来源不可确认，不能把旧目录绑定为当前来源。
    return active.catalog && active.catalogStamp && active.catalogStamp === active.context?.catalog_source_stamp ? active.catalog : null;
  }
  function fillEfforts(select, current, model) {
    select.replaceChildren();
    const result = effortOptions(active.context, currentCatalog(), model, preferenceMode());
    const entries = [["", preferenceMode() ? "清除本层字段（继承上层）" : followLabel()], ...result.values.map(value => [value, value + (result.verified ? "" : "（能力未核实）")])];
    if (current && !result.values.includes(current)) entries.push([current, current + "（已有值不受当前目录支持，请重选或清除）"]);
    for (const [value, label] of entries) { const option = node("option", "", label); option.value = value; select.append(option); }
    select.value = current ?? "";
    return result;
  }
  function updateBatchEfforts() {
    const ids = [...editorDraft().selected];
    const models = new Set(ids.map(id => $("batch-model-enabled").checked ? $("batch-model").value || null : effectiveDraftModel(id)));
    const mixed = models.size > 1;
    fillEfforts($("batch-effort"), $("batch-effort").value || "", mixed ? null : [...models][0]);
    // 多模型只允许共有档位的交集；每个模型的未知合同值也不能变成已验证能力。
    if (mixed) {
      const sets = [...models].map(model => effortOptions(active.context, currentCatalog(), model, preferenceMode()).values);
      const shared = sets[0]?.filter(value => sets.every(values => values.includes(value))) || [];
      for (const option of [...$("batch-effort").options]) if (option.value && !shared.includes(option.value)) option.remove();
    }
    $("batch-effort-help").textContent = mixed ? "所选目标使用不同模型，仅提供各模型共有推理档位；不使用档位并集。" : "推理选项按批量目标模型计算；未核实能力会明确标记。";
  }
  function renderModels() {
    const values = new Map(modelCandidates(active.context, currentCatalog(), preferenceMode()).map(row => [row.id, row.label || row.id]));
    if (!preferenceMode()) values.set("inherit", "直接跟随宿主");
    const options = $("model-options"); options.replaceChildren();
    for (const [value, label] of values) { const option = node("option", "", label); option.value = value; options.append(option); }
  }
  function renderCapabilities() {
    const caps = editorCaps();
    $("capability-status").textContent = preferenceMode() ? "调用偏好独立保存，供下一次派发前读取；当前工具参数与真实运行未验证。" + (caps.model_format === "alias" ? " Claude 调用覆盖仅接受别名，完整模型 ID 只适用于原生定义。" : caps.model_format === "tier" ? " 子代理使用 inherit / flash / pro tier；agy 会话模型 ID 不用于此处。" : "") : "原生文件是完整定义；插件缓存只读。保存后需由宿主重新加载，实际运行未验证。";
    const catalog = currentCatalog();
    $("catalog-status").textContent = active.catalogFailure || (catalog ? "本范围模型目录已读取 · " + catalog.models.length + " 项；候选可见不证明账户可调用。" : active.catalog ? "上下文已变化，旧目录已失效；开始编辑时重新读取。" : "开始编辑时按需读取本机目录，也可显式刷新。");
    const list = $("catalog-sources"); list.replaceChildren();
    const sources = {documented_parameter_contract:"工具参数合同（本机映射尚未读取）", official_model_list:"本机 Codex model/list", explicit_official_catalog:"本机明确配置的模型目录", official_alias_local_mapping:"本机 Claude 别名映射", user_model_picker:"本机用户模型菜单", current_local_configuration:"本机当前模型配置", saved_native_definition_unverified:"已保存原生定义（可调用性未验证）", official_subagents_tier:"官方子代理 tier 合同"};
    for (const row of modelCandidates(active.context, catalog, preferenceMode())) list.append(node("li", "", (row.label || row.id) + " · " + (sources[row.source] || row.source)));
    for (const note of catalog?.notes || []) list.append(node("li", "", note));
  }
  function renderDiagnostics() {
    const diagnostics = Array.isArray(active.context?.diagnostics) ? active.context.diagnostics : [];
    const incomplete = active.context?.inventory_complete === false;
    $("discovery-diagnostics").hidden = !diagnostics.length && !incomplete;
    $("discovery-summary").textContent = (incomplete ? "发现不完整" : "发现诊断") + " · " + diagnostics.length + " 项";
    $("discovery-completeness").textContent = incomplete ? "部分定义或来源无法安全解析。已解析且可写的定义仍可编辑；当前清单与命名调用结果不能视为完整。" : "以下为本次原生文件发现的说明；磁盘清单不等于当前会话已加载。";
    const list = $("discovery-items"); list.replaceChildren();
    for (const item of diagnostics) {
      if (!object(item)) continue;
      const code = typeof item.code === "string" ? item.code : "未提供诊断代码";
      const explanation = typeof item.message === "string" ? item.message : ({codex_plugin_agents_not_supported:"Codex 插件不提供可写原生 Agent；请使用上方调用偏好。", plugin_agent_read_only:"插件缓存定义只读；请使用调用偏好。", native_parse_failed:"原生定义解析失败；请核对该文件格式后重新读取。"}[code] || "此来源的原生定义未能完整确认；可先使用调用偏好，检查来源后重新读取。");
      list.append(node("li", "", explanation + "（" + code + "）" + (typeof item.source === "string" && item.source ? " · " + item.source : "")));
    }
  }
  function renderActivationRecovery(target, value) {
    target.replaceChildren();
    if (!value) { target.append(node("p", "help", "恢复信息尚未读取。")); return; }
    target.append(node("p", "help", "独立配置组件重新打开命令（请自行在终端执行）："));
    target.append(node("code", "recovery-command", value.recovery.open_command || "服务未提供重新打开命令"));
    const steps = node("ol", "help");
    for (const step of value.recovery.official_steps) steps.append(node("li", "", step));
    target.append(steps);
    // 仅展示官方 HTTP(S) 资料链接，服务数据不能提供 javascript: 等可执行导航。
    try {
      const url = new URL(value.recovery.documentation_url);
      if (["https:", "http:"].includes(url.protocol)) {
        const link = node("a", "", "查看平台官方管理说明"); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; target.append(link);
      }
    } catch (_) { /* 未提供有效官方链接时保留文字步骤，不生成猜测链接。 */ }
  }
  function renderActivation() {
    const value = active.activation.saved;
    $("activation-card").setAttribute("aria-busy", String(loading));
    $("activation-scope").textContent = describeLocation(active.location) + (active.location.scope === "global" ? " · 用户级默认" : active.location.host === "claude" ? " · 仅本机当前项目（local）" : " · 当前项目覆盖");
    const facts = $("activation-saved"); facts.replaceChildren();
    for (const [label, text] of [["已保存本层值", activationLabel(value?.state)], ["继承值", activationLabel(value?.inherited_state)],
      ["继承来源", value?.inherited_source || "未知／未观察到"], ["已观察配置结果", activationLabel(value?.effective_state)],
      ["插件身份", value?.plugin_id || "未知"], ["目标配置路径", value?.source_path || "未确定"]]) {
      const fact = node("div"); fact.append(node("dt", "", label), node("dd", "", text)); facts.append(fact);
    }
    $("activation-state").value = ACTIVATION_STATES.includes(active.activation.value) ? active.activation.value : "";
    $("activation-status").textContent = active.activation.dirty ? "工作流启停有未保存草稿；请独立预览后保存。" : "工作流启停无未保存更改。";
    $("activation-readonly").textContent = !value ? "工作流状态尚未读取，暂不可编辑。" : value.supported === false ? "当前平台不支持此启停设置。" + (value.read_only_reason || "") : value.writable !== true ? value.read_only_reason || "当前来源无法安全写入。" : "";
    const diagnostics = $("activation-diagnostics"); diagnostics.replaceChildren();
    for (const item of value?.diagnostics || []) diagnostics.append(node("li", "", item.message + "（" + item.code + "）"));
    diagnostics.hidden = !diagnostics.childElementCount;
    renderActivationRecovery($("activation-recovery"), value);
  }
  function setControls() {
    const available = Boolean(active.context) && !loading && !mutation;
    const editable = available && editorRows().some(writable);
    const invalid = editorDraft().unavailableEdits.length > 0;
    const activation = section === "activation";
    const current = activation ? active.activation : editorDraft();
    $("activation-state").disabled = !available || active.activation.saved?.writable !== true;
    $("role-list").setAttribute("aria-busy", String(loading));
    for (const control of document.querySelectorAll("[data-host], [data-section], input[name=scope], #open-native, #back-preferences")) control.disabled = mutation;
    $("load-project").disabled = mutation;
    $("reload-context").disabled = mutation || loading;
    $("refresh-catalog").disabled = !available || refreshing;
    $("refresh-catalog").textContent = refreshing ? "正在刷新…" : "刷新模型目录";
    $("preview-changes").disabled = !available || !current.dirty || active.conflicted || (activation ? active.activation.saved?.writable !== true : invalid);
    $("preview-changes").textContent = mutation && !$("preview-dialog").open ? "正在预览…" : "预览并保存";
    $("discard-draft").disabled = !current.dirty || mutation;
    $("reset-platform").disabled = !editable || !editorRows().some(row => FIELDS.some(field => editorDraft().value(row.role, field)));
    $("reset-platform").textContent = preferenceMode() ? "清除本范围调用偏好" : "清除本范围原生字段";
    $("batch-model").disabled = !editable || !$("batch-model-enabled").checked;
    $("batch-effort-enabled").disabled = !editable || editorCaps().effort === false;
    $("batch-effort").disabled = !editable || !$("batch-effort-enabled").checked || editorCaps().effort === false;
    $("batch-model-enabled").disabled = !editable;
    $("apply-batch").disabled = !editable || !editorDraft().selected.size || (!$("batch-model-enabled").checked && !$("batch-effort-enabled").checked);
    const selectable = visibleRows().filter(writable);
    $("select-all").disabled = !available || !selectable.length;
    $("select-all").checked = selectable.length > 0 && selectable.every(row => editorDraft().selected.has(row.role));
    $("select-all").indeterminate = selectable.some(row => editorDraft().selected.has(row.role)) && !$("select-all").checked;
    $("batch-summary").textContent = "已选 " + editorDraft().selected.size + " 个 Agent · 仅更新勾选字段，预览后保存";
    $("draft-status").textContent = current.dirty ? (activation ? "1 项未保存更改" : editorDraft().count + " 项未保存更改") : "无未保存更改";
    if (!activation && invalid) $("draft-status").textContent += " · 有身份已消失或变为只读，请先放弃草稿";
    if (active.conflicted) $("draft-status").textContent += " · 需重新读取";
    $("recovery-context").hidden = !active.conflicted;
    $("recovery-context").disabled = mutation || loading;
    $("view-receipt").hidden = !active.receipt;
    $("view-receipt").disabled = mutation;
    $("draft-context").textContent = describeLocation(active.location) + " · " + kindName();
    $("save-boundary").textContent = (activation || !preferenceMode() ? "等待新会话加载" : "供后续派发读取") + " · 实际运行未验证";
    $("save-bar").dataset.dirty = String(current.dirty);
    $("save-bar").hidden = section === "diagnostics";
    $("nav-models").dataset.dirty = active.count + active.preferences.count ? String(active.count + active.preferences.count) : "";
    $("nav-activation").dataset.dirty = active.activation.dirty ? "1" : "";
    for (const control of document.querySelectorAll("#agent-rows input, #agent-rows select, #default-settings input, #default-settings select, [data-reset]")) {
      const row = editorDraft().row(control.dataset.agent);
      control.disabled = !available || !row || !writable(row) || (control.dataset.field === "effort" && editorCaps().effort === false && !editorDraft().value(row.role, "effort")) ||
        (control.dataset.reset !== undefined && !FIELDS.some(field => editorDraft().value(row.role, field)));
    }
  }
  function rowState(row, target) {
    const draft = editorDraft();
    const dirty = draft.edits.has(row.role);
    target.replaceChildren();
    const status = node("span", "row-state", dirty ? "未保存草稿" : FIELDS.some(field => row.overrides[field]) ? "本层覆盖" : "继承");
    status.dataset.dirty = String(dirty); target.append(status);
    if (dirty) target.append(node("p", "row-hint", "已保存：" + FIELDS.map(field => row.overrides[field] || "继承").join(" / ")));
    else target.append(node("p", "row-hint", FIELDS.some(field => row.overrides[field]) ? preferenceMode() ? "已保存 · 后续派发读取" : "已保存 · 等待新会话加载" : "未设置本层字段"));
    const reset = node("button", "text-button row-reset", preferenceMode() ? "恢复继承" : "清除字段"); reset.type = "button";
    reset.dataset.agent = row.role; reset.dataset.reset = "true"; reset.setAttribute("aria-label", (row.role === "*" ? "通用默认" : row.name || row.role) + " · " + reset.textContent);
    reset.addEventListener("click", () => {
      for (const field of FIELDS) draft.set(row.role, field, null);
      render(); message("已更新当前目标草稿；预览保存后才记录。");
      // 重绘后回到同一真实身份的模型字段；不拼接opaque ID为选择器，避免特殊字符改变匹配。
      [...document.querySelectorAll("[data-field='model']")].find(control => control.dataset.agent === row.role)?.focus();
    });
    target.append(reset);
    if (!preferenceMode() && row.dispatch_ready === false) target.append(node("p", "blocked-reason", "派发受阻：" + (row.blocked_reason || "当前调用能力未确认")));
    if (object(row.per_invocation) && row.per_invocation.ready === false) target.append(node("p", "row-hint", "单次调用覆盖受阻；原生文件可写性独立判断。"));
  }
  function fieldControl(row, field, index) {
    const container = node("div", "field-cell");
    const id = "agent-" + index + "-" + field;
    const label = node("label", row.role === "*" ? "field-label" : "cell-label", FIELD_LABELS[field]); label.htmlFor = id; container.append(label);
    const input = node(field === "model" ? "input" : "select"); input.id = id; input.dataset.agent = row.role; input.dataset.field = field;
    const displayName = row.role === "*" ? "通用默认" : row.name || row.role;
    input.setAttribute("aria-label", displayName + " 的" + FIELD_LABELS[field] + "（" + row.role + "）");
    input.setAttribute("aria-describedby", id + "-hint " + id + "-error");
    input.addEventListener("focus", ensureCatalog);
    if (field === "model") {
      // 原生 input+datalist 保留任意已保存ID与目录为空时的输入能力；绝不以第一候选替换历史值。
      input.type = "text"; input.maxLength = 200; input.spellcheck = false; input.autocomplete = "off"; input.setAttribute("list", "model-options");
      input.value = editorDraft().value(row.role, field) ?? "";
    }
    container.append(input);
    const hint = node("p", "row-hint"); hint.id = id + "-hint"; container.append(hint);
    const error = node("p", "row-error"); error.id = id + "-error"; error.hidden = true; container.append(error);
    input.addEventListener(field === "model" ? "input" : "change", () => {
      editorDraft().set(row.role, field, input.value || null);
      // 只刷新推导的候选、来源和状态；不重建正编辑的input，避免丢失光标和输入法组合。
      refreshFieldDisplays(); updateBatchEfforts(); setControls();
    });
    return container;
  }
  function refreshFieldDisplays() {
    for (const root of document.querySelectorAll("[data-row]")) {
      const row = editorDraft().row(root.dataset.row); if (!row) continue;
      root.classList.toggle("is-dirty", editorDraft().edits.has(row.role));
      for (const field of FIELDS) {
        const input = root.querySelector('[data-field="' + field + '"]');
        const resolved = resolvedField(editorDraft(), row.role, field, preferenceMode());
        const current = editorDraft().value(row.role, field);
        const hint = $(input.id + "-hint"), error = $(input.id + "-error");
        if (field === "model") {
          input.placeholder = resolved.pending ? "继承值待预览" : (resolved.value || "宿主默认") + " · 继承";
          const known = modelCandidates(active.context, currentCatalog(), preferenceMode()).some(item => item.id === current);
          hint.textContent = "来源：" + resolved.source + (current && !known ? " · 当前值未列出，原值保留" : "") + (!current ? " · 留空继承" : "");
        } else {
          const options = fillEfforts(input, current, effectiveDraftModel(row.role));
          input.options[0].textContent = editorCaps().effort === false ? "不支持独立推理" : resolved.pending ? "继承值待预览" : (resolved.value || "宿主默认") + " · 继承";
          const effectiveEffort = current || (!resolved.pending ? resolved.value : null);
          const incompatible = Boolean(effectiveEffort && (editorCaps().effort === false || options.verified && !options.values.includes(effectiveEffort)));
          error.textContent = incompatible ? "已有推理值与当前模型不兼容；请重选或清除。原值已保留。" : "";
          error.hidden = !incompatible; input.setAttribute("aria-invalid", String(incompatible));
          hint.textContent = editorCaps().effort === false ? "当前平台不支持独立推理；已有值可显式清除" : "来源：" + resolved.source + (!options.verified ? " · 模型能力未核实" : "");
        }
      }
      rowState(row, root.querySelector(".state-cell"));
    }
  }
  function renderRows() {
    const body = $("agent-rows"); body.replaceChildren(); $("default-settings").replaceChildren();
    const rows = visibleRows();
    const defaultRow = preferenceMode() ? editorDraft().row("*") : null;
    $("default-settings").hidden = !defaultRow;
    if (defaultRow) {
      const root = $("default-settings"); root.dataset.row = "*";
      const name = node("div", "default-name"); name.append(node("h3", "", "通用默认"), node("p", "help", "未设置的 Agent 按来源继承"));
      const state = node("div", "state-cell default-status");
      root.append(name, fieldControl(defaultRow, "model", "default"), fieldControl(defaultRow, "effort", "default"), state);
    } else delete $("default-settings").dataset.row;
    $("agent-count").textContent = String(rows.length);
    $("agent-table").hidden = !rows.length;
    $("batch-toggle").hidden = !rows.some(writable);
    if (!rows.some(writable)) { $("batch-panel").hidden = true; $("batch-toggle").setAttribute("aria-expanded", "false"); }
    $("empty-state").hidden = rows.length > 0;
    $("empty-state").textContent = loading ? "正在读取当前平台的 Agent…" : active.context ? preferenceMode() ? "未发现独立调用身份。仍可在上方编辑通用默认。" : "当前范围未发现原生定义；可返回调用偏好，或载入所属项目。" : "配置尚未载入。请在诊断中重新读取，或检查项目路径。";
    rows.forEach((row, index) => {
      const tr = node("tr"); tr.dataset.row = row.role;
      const identity = node("th"); identity.scope = "row";
      const label = node("label", "identity-label"); const checkbox = node("input"); checkbox.type = "checkbox"; checkbox.dataset.agent = row.role;
      checkbox.setAttribute("aria-label", "选择 " + row.role); checkbox.checked = editorDraft().selected.has(row.role);
      checkbox.addEventListener("change", () => { checkbox.checked ? editorDraft().selected.add(row.role) : editorDraft().selected.delete(row.role); updateBatchEfforts(); setControls(); });
      label.append(checkbox,node("strong", "", preferenceMode() ? row.role : row.name || row.role)); identity.append(label);
      identity.append(node("p", "row-hint", sourceLabel(row.origin) + " · " + (writable(row) ? "可编辑" : "只读") + (preferenceMode() && !row.discovered ? " · 历史身份未发现" : "")));
      const details = node("details", "row-details"); details.append(node("summary", "", "身份与来源详情"));
      for (const [caption,value] of [["稳定身份",row.role],["调用名",row.invoke_name],["原生名称",row.native_name],["文件",row.source_path],["范围",sourceLabel(row.scope || active.location.scope)],["定义状态",DEFINITION_LABELS[row.definition_status] || row.definition_status],["遮蔽来源",row.shadowed_by]]) if (value) details.append(node("p", "", caption + "：" + value));
      if (!writable(row)) details.append(node("p", "", readOnlyReason(row)));
      if (row.per_invocation?.blocked_reason) details.append(node("p", "", "单次调用覆盖：" + row.per_invocation.blocked_reason));
      identity.append(details); tr.append(identity);
      for (const field of FIELDS) { const td = node("td"); td.append(fieldControl(row, field, index)); tr.append(td); }
      const state = node("td", "state-cell"); tr.append(state); body.append(tr);
    });
    refreshFieldDisplays();
  }
  function announceSwitch() {
    clearTimeout(switchNoticeTimer);
    const count = [...drafts.values()].reduce((total, draft) => total + draft.count + draft.preferences.count + (draft.activation.dirty ? 1 : 0), 0);
    $("switch-status").textContent = describeLocation(active.location) + " · " + kindName() + (count ? "。共 " + count + " 项草稿已按平台、范围与事务保留。" : "");
    $("switch-status").hidden = false;
    // 只隐藏可推导的导航回执；错误、保存结果和底部当前事务始终可定位。
    switchNoticeTimer = setTimeout(() => { $("switch-status").hidden = true; }, 4000);
  }
  function render() {
    const location = active.location;
    for (const tab of document.querySelectorAll("[data-host]")) { const selected = tab.dataset.host === location.host; tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1; }
    $("config-panel").setAttribute("aria-labelledby", "tab-" + location.host);
    for (const radio of document.querySelectorAll("input[name=scope]")) radio.checked = radio.value === location.scope;
    for (const nav of document.querySelectorAll("[data-section]")) { if (nav.dataset.section === section) nav.setAttribute("aria-current", "page"); else nav.removeAttribute("aria-current"); }
    for (const name of ["models","activation","diagnostics"]) $("section-" + name).hidden = section !== name;
    $("scope-location").textContent = describeLocation(location);
    $("scope-subtitle").textContent = location.scope === "global" ? "此平台的所有项目默认使用" : "仅此项目覆盖 · 其他项目继承用户级";
    $("editor-title").textContent = preferenceMode() ? "模型与推理" : "原生定义文件";
    $("context-summary").textContent = loading ? "正在读取配置…" : preferenceMode() ? "为后续派发设置偏好，未设置的字段按来源继承。" : "完整定义独立保存，宿主规则决定优先级。";
    $("inherit-help").textContent = preferenceMode() ? "* 是通用默认目标，不是原生 Agent；清除覆盖后若上层值被遮蔽，由真实预览解析。" : "原生字段留空只删除对应字段；宿主决定默认值与同名来源优先级。";
    $("editing-help").textContent = preferenceMode() ? "用户通用 → 用户该 Agent → 项目通用 → 项目该 Agent。完整原生定义可能按宿主规则优先。" : "每份原生文件是完整定义；其他范围和插件缓存只读。";
    $("preference-location").textContent = preferenceMode() && active.context?.dispatch_preferences?.source_path ? "偏好保存位置：" + active.context.dispatch_preferences.source_path : "";
    $("save-result").textContent = active.lastSave;
    $("technical-location").textContent = describeLocation(location) + " · revision " + (active.context?.revision || "未读取") + " · 目录来源 " + (active.context?.catalog_source_stamp || "未确认");
    $("native-heading").hidden = preferenceMode(); $("advanced-entry").hidden = !preferenceMode();
    $("list-title").firstChild.textContent = preferenceMode() ? "逐 Agent 覆盖 " : "原生定义 ";
    $("native-readonly-summary").hidden = preferenceMode() || editorRows().some(writable);
    renderModels(); renderCapabilities(); renderDiagnostics(); renderActivation(); renderRows(); updateBatchEfforts(); setControls();
  }
  function validProject(path) {
    // 这里只做输入反馈；真实路径权限、链接身份和存在性仍由服务端权威检查。
    return path.startsWith("/") && path.length <= 4096 && !path.split("/").includes("..") && !/[\x00-\x1f]/.test(path);
  }
  async function loadContext() {
    const draft = active; const ticket = loadOwner.begin(); loading = true; render();
    try {
      const context = await api.context(draft.location, ticket.signal);
      if (!loadOwner.current(ticket) || active !== draft) return;
      draft.accept(context); message(draft.anyDirty ? "配置已重新读取；当前草稿已保留，请再次预览后保存。重新读取不会重新加载宿主。" : "配置已重新读取；宿主会话未重新加载，实际运行未验证。");
    } catch (error) {
      if (!loadOwner.current(ticket) || active !== draft || error.code === "cancelled") return;
      message(error.message + (draft.context ? " 当前显示的是上次读取的配置。" : ""), "error");
    } finally { if (loadOwner.current(ticket) && active === draft) { loading = false; render(); } }
  }
  function switchTo(location) {
    catalogOwner.cancel(); previewOwner.cancel(); refreshing = false;
    const key = locationKey(location);
    if (!drafts.has(key)) drafts.set(key, new Draft(location));
    active = drafts.get(key);
    if (location.scope === "project") $("project-path").value = location.project;
    message(""); loadContext(); announceSwitch();
  }
  function askDecision(action) {
    decision = action; decisionTrigger = document.activeElement;
    $("confirm-decision").textContent = "放弃草稿";
    $("cancel-decision").textContent = "继续编辑";
    $("draft-dialog").showModal(); $("cancel-decision").focus();
  }
  function restoreDecisionFocus() {
    const operable = control => control?.isConnected && !control.disabled && control.getClientRects().length > 0;
    if (operable(decisionTrigger)) { decisionTrigger.focus(); return; }
    // 确认放弃会清空当前事务并重绘，原“放弃”按钮随之禁用。
    // 原生 dialog 的返回焦点不能保证这一步之后仍可操作，因此回到当前事务的真实编辑控件；
    // 取消/Esc 没有清草稿，仍优先保留有效的原触发器，不改变用户键盘位置。
    const candidates = section === "activation" ? [$("activation-state")] :
      [...document.querySelectorAll("#section-models [data-field='model']")];
    const target = candidates.find(operable) ||
      [...document.querySelectorAll("[data-section][aria-current='page']")].find(operable);
    target?.focus();
  }
  function requestSwitch(location) {
    if (mutation || locationKey(location) === locationKey(active.location)) { render(); return; }
    if (location.scope === "project" && !validProject(location.project)) {
      render(); message("请填写不含 .. 的项目绝对路径，再点击“载入项目”。", "error"); $("project-path").focus(); return;
    }
    switchTo(location);
  }
  function ensureCatalog() {
    if (!currentCatalog() && active.catalogAttempt !== (active.context?.catalog_source_stamp || active.context?.revision)) refreshCatalog();
  }
  async function refreshCatalog() {
    if (refreshing || loading || mutation) return;
    const draft = active; const ticket = catalogOwner.begin(); refreshing = true; draft.catalogAttempt = draft.context?.catalog_source_stamp || draft.context?.revision; setControls();
    message("正在读取当前平台的模型目录；已有选择与草稿会保留。");
    try {
      const catalog = await api.catalog(draft.location, ticket.signal);
      if (!catalogOwner.current(ticket) || active !== draft) return;
      if (catalog.status !== "ready") {
        draft.catalogFailure = "模型目录刷新未成功，已保留已有候选与草稿。";
        message(draft.catalogFailure, "warning");
      } else {
        draft.catalog = catalog; draft.catalogFailure = null;
        message("模型目录已刷新。已有字段与草稿未被重置。");
      }
      // Claude 真实 --version 可能改变派发能力，随后只读一次 context 以获取权威 blocked 状态。
      const context = await api.context(draft.location, ticket.signal);
      if (!catalogOwner.current(ticket) || active !== draft) return;
      draft.accept(context);
      if (catalog.status === "ready") {
        // context 再确认目录返回期间来源未变化；晚到或换身份的目录不能盖成新来源。
        draft.catalogRevision = context.revision;
        draft.catalogStamp = catalog.source_stamp === context.catalog_source_stamp ? catalog.source_stamp : null;
        if (!draft.catalogStamp) draft.catalogFailure = "目录读取后来源已变化或不可确认，候选已失效；请显式刷新。草稿保留。";
      }
      draft.catalogAttempt = context.catalog_source_stamp || context.revision;
    } catch (error) {
      if (!catalogOwner.current(ticket) || active !== draft || error.code === "cancelled") return;
      draft.catalogFailure = "刷新失败，已有候选与选择已保留。";
      message(error.message + " " + draft.catalogFailure, "error");
    } finally { if (catalogOwner.current(ticket) && active === draft) { refreshing = false;
      renderModels(); renderCapabilities(); renderActivation();
      refreshFieldDisplays();
      updateBatchEfforts(); setControls();
    } }
  }
  function renderPreview(value, reset, kind = "model") {
    const activation = kind === "workflow_activation";
    const preferences = kind === "dispatch_preferences";
    const changes = $("preview-changes-list"); changes.replaceChildren();
    $("preview-title").textContent = activation ? "确认工作流启停" : preferences ? reset ? "确认清除本范围调用偏好" : "确认调用偏好更改" : reset ? "确认清除本范围模型覆盖" : "确认模型配置更改";
    $("preview-location").textContent = describeLocation(active.location);
    for (const change of value.changes) {
      if (activation) {
        const item = node("section", "change-item"); item.append(node("h3", "", "工作流插件 · " + change.plugin_id));
        item.append(node("p", "help", "目标范围：" + (change.scope === "global" ? "用户级默认" : active.location.host === "claude" ? "仅本机当前项目（local）" : "当前项目")), node("p", "help", "目标路径：" + change.source_path));
        const values = node("div", "change-values");
        for (const [label, raw] of [["保存前", change.before], ["保存后", change.after]]) {
          const part = node("div"); part.append(node("small", "", label), node("span", "", activationLabel(raw))); values.append(part);
        }
        item.append(values, node("p", "change-effective", "已观察配置结果：" + activationLabel(change.effective_before) + " → " + activationLabel(change.effective_after)));
        item.append(node("p", "help", change.after === "inherit" ? "仅移除本层覆盖；Claude 项目仍可能继承共享项目设置。" : change.after === "disabled" ? "停用写入本层配置；当前会话已经加载的上下文不会因此清除。" : "启用写入本层配置；宿主信任、启动参数和托管策略仍由宿主决定。"));
        changes.append(item); continue;
      }
      const identity = preferences ? change.target : change.role;
      const row = (preferences ? active.preferences : active).row(identity);
      const item = node("section", "change-item"); item.append(node("h3", "", (row?.name || identity) + " · " + FIELD_LABELS[change.field]));
      if (row) item.append(node("p", "help", sourceLabel(row.origin) + " · " + sourceLabel(row.scope) + " · " + identity));
      const values = node("div", "change-values");
      for (const [label, raw] of [["保存前", change.before], ["保存后", change.after]]) {
        const part = node("div"); part.append(node("small", "", label), node("span", "", fieldValue(raw))); values.append(part);
      }
      item.append(values);
      item.append(node("p", "change-effective", (preferences ? "解析偏好：" : "定义值：") + fieldValue(change.effective_before) + " → " + fieldValue(change.effective_after) + " · " + sourceLabel(change.source_before) + " → " + sourceLabel(change.source_after)));
      changes.append(item);
    }
    if (!value.changes.length) changes.append(node("p", "help", "此范围没有需要保存的字段更改。"));
    const blocked = value.dispatch_ready === false;
    message(activation ? "此预览仅保存工作流启停；其他两类草稿会保留。文件保存后等待新会话加载，实际运行未验证。" : preferences ? "此预览仅保存调用偏好；原生文件与启停草稿保留。保存后供后续派发前读取，不改变当前会话；实际运行未验证。" : blocked ? "配置可以保存，但当前派发受阻。原因：" + (value.blocked_reason || "服务端未提供具体原因，请重新读取。") : value.dispatch_ready === true ? "预览已生成；保存后仍需由宿主采纳，实际运行尚未验证。" : "预览已生成；派发状态未知。", !activation && blocked ? "warning" : "info", $("preview-status"));
    $("preview-activation-recovery").hidden = !activation;
    if (activation) renderActivationRecovery($("preview-activation-recovery"), active.activation.saved);
    $("preview-effect").textContent = preferences ? "调用偏好保存后供下一次派发前读取；当前会话不会因此改用模型。原生完整定义的优先级、当前工具参数与实际模型执行仍须宿主确认。" : activation ? "启停保存只改变本层文件，等待新会话加载；当前会话已加载上下文不受影响，实际工作流运行未验证。" : "原生定义保存后需要宿主重新加载或重新发现。当前 Agent 不会因此切换模型，实际模型运行未验证；多文件发布不具有跨文件系统崩溃原子性。";
    const warnings = $("warning-list"); warnings.replaceChildren();
    for (const warning of value.warnings) warnings.append(node("li", "", String(warning)));
    $("preview-warnings").hidden = !value.warnings.length;
    if (reset && (preferences ? active.preferences.dirty : active.dirty)) {
      warnings.append(node("li", "", "本次清除操作将替代当前范围的未保存草稿；取消预览会保留草稿。"));
      $("preview-warnings").hidden = false;
    }
    $("confirm-apply").disabled = !value.changes.length;
    $("cancel-preview").textContent = "取消";
    message("", "info", $("apply-feedback"));
    $("apply-results").replaceChildren(); $("apply-results").hidden = true;
  }
  async function openPreview(reset = false, kind = editorMode) {
    const activation = kind === "workflow_activation";
    const preferences = kind === "dispatch_preferences";
    if (!active.context || mutation || loading) return;
    if (!activation) {
      const invalid = [...document.querySelectorAll("#section-models [aria-invalid='true']")].find(control => !control.disabled);
      if (invalid) { message("推理值与当前模型不兼容，请重选或清除后再预览。", "error"); invalid.focus(); return; }
    }
    const intendedDraft = active;
    if (!activation && active.catalog && !currentCatalog()) {
      // 草稿可能在启停保存或外部配置变化前已完成编辑；直接点预览也必须先更新能力来源。
      // 这是用户触发的按需读取，不放进 render；目录失败不能借旧候选继续生成计划。
      await refreshCatalog();
      // 读取目录期间可切换范围或编辑入口；原预览意图不能晚到并应用到另一个范围。
      if (active !== intendedDraft || editorMode !== kind || section !== "models" || mutation || loading) return;
      if (!currentCatalog()) { message("当前模型目录来源未确认；草稿已保留，请刷新目录成功后再预览。", "error"); return; }
    }
    if (active.conflicted || (activation && (!active.activation.dirty || active.activation.saved?.writable !== true))) return;
    if (!activation && !reset && (preferences ? active.preferences : active).unavailableEdits.length) { message("部分草稿对应的 Agent 已消失或变为只读，请先放弃草稿。", "error"); return; }
    loadOwner.cancel();
    catalogOwner.cancel(); refreshing = false;
    const draft = active; const ticket = previewOwner.begin(); mutation = true; dialogTrigger = document.activeElement; setControls();
    try {
      const value = activation ? await api.previewActivation(draft.location, draft.context.revision, draft.activation.value, ticket.signal) : preferences ? await api.previewPreferences(draft.location, draft.context.revision, reset ? {} : draft.preferences.payload(), reset, ticket.signal) : await api.preview(draft.location, draft.context.revision, reset ? {} : draft.payload(), reset, ticket.signal);
      if (!previewOwner.current(ticket) || active !== draft) return;
      preview = { value, draft, kind }; renderPreview(value, reset, kind);
      $("preview-dialog").showModal(); $("preview-title").focus();
    } catch (error) {
      if (!previewOwner.current(ticket) || active !== draft || error.code === "cancelled") return;
      if (error.code === "conflict") draft.conflicted = true;
      message(error.message + (error.code === "conflict" ? " 草稿已保留，请点击“重新读取”后再次预览。" : ""), "error");
    } finally { mutation = false; setControls(); }
  }
  function closePreview() {
    if (mutation) return;
    $("preview-dialog").close(); preview = null;
    restorePreviewFocus();
  }
  function restorePreviewFocus() {
    // 冲突/部分失败后原预览按钮会禁用，焦点应回到可继续恢复的重新读取入口。
    if (dialogTrigger?.isConnected && !dialogTrigger.disabled) dialogTrigger.focus();
    else { section = "diagnostics"; render(); $("reload-context").focus(); }
  }
  function renderSaveDetails(result, draft) {
    const details = $("apply-results"); details.replaceChildren();
    details.append(node("h3", "", "逐项保存与保留资料"));
    details.append(node("p", "", "文件保存标志：" + (result.saved ? "服务报告已保存" : "服务未确认完整保存")));
    const flags = [["published", "新内容正式发布"], ["namespace_touched", "文件命名空间变动"], ["temporary_visibility_gap", "曾出现短暂可见性缺口"]];
    for (const [key, label] of flags) if (own(result, key)) details.append(node("p", "", label + "：" + (result[key] ? "是" : "否")));
    if (result.finalization_failed === true) details.append(node("p", "", "最终收尾未完成：已发生的发布与命名空间变动仍以本收据为准；当前位置可能未核实。"));
    if (typeof result.effect.pending_reload === "boolean") details.append(node("p", "", result.effect.pending_reload ? "宿主状态：待重新加载" : "宿主状态：未声明待重载，实际加载仍未观察"));
    if (typeof result.retention_policy === "string") details.append(node("p", "", "保留策略：" + (result.retention_policy === "until_explicit_safe_cleanup_contract" ? "等待明确的安全清理约定；本页只展示资料" : result.retention_policy)));
    for (const directory of result.created_directories || []) details.append(node("p", "", "请求期间创建过的目录（原声明位置，当前位置请自行核对）：" + directory));
    for (const entry of result.created_files || []) {
      const item = node("section", "recovery-item");
      item.append(node("p", "", "首次创建文件：" + entry.role + " · " + (entry.published ? "已发生发布" : "未报告发布")),
        node("p", "", (entry.location_status === "unknown" ? "原声明路径（当前位置未核实）：" : "收尾时核实路径：") + entry.target),
        node("p", "", entry.recovery_action));
      details.append(item);
    }
    for (const entry of result.results || []) {
      const row = draft.row(entry.role);
      details.append(node("p", "", (row?.name ? row.name + "（" + entry.role + "）" : entry.role) + "：" + (SAVE_LABELS[entry.status] || entry.status)));
    }
    for (const entry of result.recovery || []) {
      const recovery = node("div", "recovery-item");
      const kind = entry.kind === "preview_preimage" ? "预览前像副本（与原文件对象分开）" : entry.kind === "isolated_object" ? "隔离保留对象（原文件或外部对象）" : entry.kind ? "保留对象 · " + entry.kind : "保留对象（类型未提供）";
      recovery.append(node("p", "", "资料类型：" + kind), node("p", "", "原声明目标路径：" + entry.target));
      if (entry.location_status === "unknown") {
        recovery.append(node("p", "", "保留资料当前位置：未知；父目录位置未完成核实，服务未扫描查找。"),
          node("p", "", "保留资料原声明位置（非当前位置）：" + entry.declared_backup));
      } else {
        recovery.append(node("p", "", "保留资料路径（收尾时核实，只读）：" + entry.backup));
      }
      if (Array.isArray(entry.observed_identity)) recovery.append(node("p", "", "观察到的对象身份（设备号 / inode）：" + entry.observed_identity.slice(0, 2).join(" / ")));
      if (Array.isArray(entry.container_identity)) recovery.append(node("p", "", "观察到的容器身份（设备号 / inode）：" + entry.container_identity.join(" / ")));
      const hashLabel = entry.sha256_semantics === "immutable_preview_bytes" || entry.kind === "preview_preimage" ? "预览副本 SHA256" : entry.sha256_semantics === "observed_at_isolation_not_current" || entry.kind === "isolated_object" ? "隔离时观察 SHA256（非当前内容）" : "服务记录 SHA256（观察时点未提供）";
      recovery.append(node("p", "", hashLabel + "：" + (typeof entry.sha256 === "string" ? entry.sha256 : "服务未提供摘要")));
      if (typeof entry.content_may_change === "boolean") recovery.append(node("p", "", entry.content_may_change ? "对象内容：可能继续变化" : "对象内容：服务声明为不可变副本"));
      if (typeof entry.object_role === "string") recovery.append(node("p", "", "对象来源：" + (entry.object_role === "target_at_initial_isolation" ? "首次隔离时的目标对象" : entry.object_role === "target_at_rollback_isolation" ? "回滚隔离时的目标对象" : entry.object_role)));
      const permission = value => value === null ? "未知或不适用" : "0" + value.toString(8).padStart(3, "0");
      if (own(entry, "container_mode")) recovery.append(node("p", "", "隔离容器权限：" + permission(entry.container_mode)));
      if (own(entry, "original_mode")) recovery.append(node("p", "", "原对象权限：" + permission(entry.original_mode)));
      if (entry.kind === "isolated_object") recovery.append(node("p", "", "隔离对象可能继续被已有文件描述符修改；摘要仅表示服务观察时的内容。"));
      details.append(recovery);
    }
    const cleanupLabel = result.cleanup_pending_location_status === "unknown" ? "待清理暂存文件原声明位置（当前位置未核实）：" : "待清理的暂存文件：";
    for (const path of Array.isArray(result.cleanup_pending) ? result.cleanup_pending : []) if (typeof path === "string") details.append(node("p", "", cleanupLabel + path));
    const serviceError = typeof result.error === "string" ? result.error : object(result.error) && typeof result.error.message === "string" ? result.error.message : null;
    if (serviceError) details.append(node("p", "", "服务错误：" + serviceError));
    if (typeof result.context_diagnostic === "string") details.append(node("p", "", "回读诊断：" + result.context_diagnostic));
    details.hidden = false;
  }
  function applyReloadState(result) {
    return result.effect.kind === "dispatch_preferences" ? "待后续派发前读取（当前会话不变）" : result.effect.pending_reload === true ? "宿主待重新加载（内容发布或命名空间曾变动）" : "宿主重新加载状态未知";
  }
  function showApplyAttention(result, draft, error, kind = "model") {
    const failed = Boolean(error) || applyFailed(result);
    if (result.context) draft.accept(result.context, failed ? false : kind);
    draft.conflicted = failed || !result.context; preview = null;
    draft.lastSave = failed ? "保存未完整确认 · 逐项收据已保留" : "已保存 · 实际运行未验证";
    draft.receipt = {result, error};
    renderSaveDetails(result, draft);
    const reportedSaved = result.saved === true && result.effect.saved !== false && !result.partial_failure && (result.results || []).every(row => row.status === "saved");
    const mixed = !error && reportedSaved && own(result, "error");
    const cleanup = Boolean(result.cleanup_pending?.length);
    const summary = mixed ? "服务报告文件已保存，同时返回错误或清理事项。请检查逐项结果与保留资料，关闭结果后重新读取。" : failed ?
      (result.finalization_failed === true && result.published === true ? "新内容已发生发布，但完整请求的最终收尾未获确认。" : "配置未完整保存。") +
      "请检查逐项结果与保留资料；当前编辑已保留，关闭结果后重新读取。" : "配置已保存。" + (cleanup ? "另有暂存文件待清理。" : "") + "服务保留的原文件对象与前像资料如下。";
    message((error ? "HTTP " + error.status + "：" + error.message + " " : "") + summary + applyReloadState(result) + "；实际运行未验证。", mixed || (!failed && cleanup) ? "warning" : failed ? "error" : "success", $("apply-feedback"));
    render();
  }
  async function applyPreview() {
    if (!preview || mutation) return;
    const plan = preview; mutation = true; $("confirm-apply").disabled = true;
    $("confirm-apply").textContent = "正在保存…";
    $("cancel-preview").disabled = true; $("close-preview").disabled = true; setControls();
    message("正在保存，请等待服务端确认。", "info", $("apply-feedback"));
    try {
      const result = await api.apply(plan.value.preview_id);
      const reload = applyReloadState(result);
      if (applyNeedsAttention(result)) {
        showApplyAttention(result, plan.draft, undefined, plan.kind);
      } else if (!result.context) {
        // 原生文件已完成发布而回读失败是独立结果，不能把已知保存成功降级成“请求失败”，
        // 也不能清空旧基线上的草稿后继续编辑；先保留逐项收据，再要求重新读取。
        plan.draft.conflicted = true; preview = null;
        plan.draft.receipt = {result};
        renderSaveDetails(result, plan.draft);
        message("原生文件已保存，但配置回读失败。草稿暂时保留，请保留逐项结果并在关闭预览后重新读取。" + reload + "；实际运行未验证。", "warning", $("apply-feedback"));
      } else {
        plan.draft.accept(result.context, plan.kind);
        plan.draft.lastSave = "已保存 · " + reload + " · 实际运行未验证";
        const gap = result.temporary_visibility_gap === true ? " · 文件曾有短暂可见性缺口" : "";
        message((plan.kind === "workflow_activation" ? "工作流启停已保存；其他草稿已保留" : plan.kind === "dispatch_preferences" ? "调用偏好已保存；原生字段与启停草稿已保留" : "原生字段已保存；调用偏好与启停草稿已保留") + " · " + reload + gap + " · 实际运行未验证。", "success");
        preview = null; $("preview-dialog").close(); render();
      }
    } catch (error) {
      // apply 的计划可能已被服务端消费，网络失败不能重发旧 ID 或伪报保存失败。
      // 保留草稿，关闭后重新读取、重新预览；409 也必须用新 revision 形成新计划。
      preview = null; plan.draft.conflicted = true;
      plan.draft.lastSave = "保存结果未确认 · 请重新读取并核对收据";
      if (error.receipt) showApplyAttention(error.receipt, plan.draft, error, plan.kind);
      else message(error.message + " 保存结果未确认；草稿已保留。请关闭预览，重新读取配置后再预览。", "error", $("apply-feedback"));
    } finally {
      mutation = false; $("confirm-apply").textContent = "确认保存";
      $("cancel-preview").disabled = false; $("close-preview").disabled = false;
      $("cancel-preview").textContent = preview ? "取消" : "关闭结果";
      $("confirm-apply").disabled = !preview; setControls();
      if (!$("preview-dialog").open) restorePreviewFocus();
    }
  }

  for (const tab of document.querySelectorAll("[data-host]")) {
    tab.addEventListener("click", () => requestSwitch({ ...active.location, host: tab.dataset.host }));
    tab.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); const tabs = [...document.querySelectorAll("[data-host]")]; const index = tabs.indexOf(tab);
      // 数据读取并非即时，方向键仅移动焦点，Enter/Space 激活以遵循手动 Tab 模式。
      tabs[event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length].focus();
    });
  }
  for (const radio of document.querySelectorAll("input[name=scope]")) radio.addEventListener("change", () => requestSwitch({ host: active.location.host, scope: radio.value, ...(radio.value === "project" ? { project: $("project-path").value.trim() } : {}) }));
  $("project-form").addEventListener("submit", event => { event.preventDefault(); requestSwitch({ host: active.location.host, scope: "project", project: $("project-path").value.trim() }); });
  for (const nav of document.querySelectorAll("[data-section]")) nav.addEventListener("click", () => { section = nav.dataset.section; render(); announceSwitch(); });
  function setEditorMode(mode) { editorMode = mode; render(); announceSwitch(); }
  $("open-native").addEventListener("click", () => setEditorMode("model"));
  $("back-preferences").addEventListener("click", () => setEditorMode("dispatch_preferences"));
  $("batch-toggle").addEventListener("click", () => { $("batch-panel").hidden = !$("batch-panel").hidden; $("batch-toggle").setAttribute("aria-expanded", String(!$("batch-panel").hidden)); });
  function reloadContext() {
    // context 内的来源指纹决定缓存是否仍有效；相同来源复用，变化只失效目录，不碰草稿。
    catalogOwner.cancel(); refreshing = false; active.catalogAttempt = null; loadContext();
  }
  $("reload-context").addEventListener("click", reloadContext);
  $("recovery-context").addEventListener("click", reloadContext);
  $("view-receipt").addEventListener("click", () => {
    if (!active.receipt || mutation) return;
    dialogTrigger = document.activeElement; preview = null;
    $("preview-title").textContent = "保存收据与恢复资料";
    $("preview-location").textContent = describeLocation(active.location);
    $("preview-changes-list").replaceChildren(); $("preview-warnings").hidden = true; $("preview-activation-recovery").hidden = true;
    message("原始保存收据已保留；本页仅展示恢复路径，不根据路径自动回滚或清理。", "info", $("preview-status"));
    message("", "info", $("apply-feedback"));
    renderSaveDetails(active.receipt.result, active);
    $("preview-effect").textContent = "此处展示服务端原始保存与恢复收据。文件保存、宿主加载与实际运行分别核实；本页不根据路径自动恢复或清理文件。";
    $("confirm-apply").disabled = true; $("cancel-preview").textContent = "关闭结果";
    $("preview-dialog").showModal(); $("preview-title").focus();
  });
  $("refresh-catalog").addEventListener("click", refreshCatalog);
  $("activation-state").addEventListener("change", () => { active.activation.set($("activation-state").value); renderActivation(); setControls(); });
  $("preview-changes").addEventListener("click", () => openPreview(false, section === "activation" ? "workflow_activation" : editorMode));
  $("reset-platform").addEventListener("click", () => {
    for (const row of editorRows().filter(writable)) for (const field of FIELDS) editorDraft().set(row.role, field, null);
    render(); message("本范围字段已在草稿中清除；预览保存后才记录，其他事务保留。");
  });
  $("discard-draft").addEventListener("click", () => {
    const activation = section === "activation";
    const draft = activation ? active.activation : editorDraft();
    askDecision(() => { draft.clear(); render(); message("当前事务草稿已放弃；其他事务和已保存配置保留。"); });
    $("draft-dialog-title").textContent = "放弃" + kindName() + "草稿？";
    $("draft-dialog-description").textContent = "只放弃当前平台、范围与事务的草稿；其他草稿和已保存配置保留。";
  });
  $("select-all").addEventListener("change", () => { editorDraft().selected = new Set($("select-all").checked ? visibleRows().filter(writable).map(row => row.role) : []); renderRows(); updateBatchEfforts(); setControls(); });
  for (const id of ["batch-model-enabled", "batch-effort-enabled"]) $(id).addEventListener("change", () => {updateBatchEfforts(); setControls();});
  $("batch-model").addEventListener("input", updateBatchEfforts);
  $("batch-model").addEventListener("focus", ensureCatalog);
  $("batch-form").addEventListener("submit", event => {
    event.preventDefault();
    if (!editorDraft().selected.size || mutation) return;
    for (const id of editorDraft().selected) {
      if ($("batch-model-enabled").checked) editorDraft().set(id, "model", $("batch-model").value || null);
      if ($("batch-effort-enabled").checked && editorCaps().effort !== false) editorDraft().set(id, "effort", $("batch-effort").value || null);
    }
    render(); message("批量更改已加入草稿，请预览后保存。");
  });
  for (const id of ["close-preview", "cancel-preview"]) $(id).addEventListener("click", closePreview);
  $("confirm-apply").addEventListener("click", applyPreview);
  $("preview-dialog").addEventListener("cancel", event => { event.preventDefault(); closePreview(); });
  $("cancel-decision").addEventListener("click", () => { decision = null; $("draft-dialog").close(); restoreDecisionFocus(); });
  $("confirm-decision").addEventListener("click", () => { const action = decision; decision = null; $("draft-dialog").close(); action?.(); restoreDecisionFocus(); });
  $("draft-dialog").addEventListener("cancel", event => { event.preventDefault(); decision = null; $("draft-dialog").close(); restoreDecisionFocus(); });
  for (const dialog of [$("preview-dialog"), $("draft-dialog")]) dialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    // 原生 dialog 已负责背景 inert；补齐首尾 Tab 循环，防止浏览器把焦点送到文档 body。
    // 保存中按钮全部禁用时仍留在当前对话框，不能把键盘操作落到背景配置表。
    const controls = [...dialog.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex='0']")].filter(control => !control.hidden && control.getClientRects().length > 0);
    const first = controls[0], last = controls[controls.length - 1];
    const focused = document.activeElement;
    if (!first) { event.preventDefault(); return; }
    if (event.shiftKey && (focused === first || !dialog.contains(focused) || focused.tabIndex === -1)) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (focused === last || !dialog.contains(focused))) {
      event.preventDefault(); first.focus();
    }
  });
  window.addEventListener("beforeunload", event => {
    if ([...drafts.values()].some(draft => draft.anyDirty) || mutation) { event.preventDefault(); event.returnValue = ""; }
  });
  window.addEventListener("pagehide", () => { clearTimeout(switchNoticeTimer); loadOwner.cancel(); catalogOwner.cancel(); previewOwner.cancel(); });
  switchTo({ host: initialHost, scope: initialProject ? "project" : "global", ...(initialProject ? { project: initialProject } : {}) });
})();
