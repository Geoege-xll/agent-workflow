(() => {
  "use strict";
  /* 所有数据只存在于本页面内存。这里不读取本机配置、不使用网络或浏览器持久化。
     平台/范围/事务是三个独立键；保存、放弃与恢复均只触达当前事务。 */
  const $ = id => document.getElementById(id);
  const copy = value => JSON.parse(JSON.stringify(value));
  const hosts = {
    codex: { label: "Codex", models: { "demo-balanced": ["low", "medium", "high"], "demo-fast": ["low", "medium"] }, fallback: "demo-balanced", effort: "medium", identities: [], source: "原生 model/list（离线目录样本）", boundary: "展示模型自身的推理元数据。此处模型ID为虚构样本；零原生角色也可编辑通用默认，不把任务标签视为调用身份。" },
    claude: { label: "Claude Code", models: { sonnet: ["low", "medium", "high"], haiku: ["low", "medium"], opus: ["low", "medium", "high"] }, fallback: "sonnet", effort: "medium", identities: ["demo-tools:reviewer", "researcher"], source: "配置根、用户菜单与别名映射（离线目录样本）", boundary: "调用偏好使用官方别名。目录出现不代表账户可调用，推理候选不证明当前工具参数支持；实际运行未验证。原生文件可接受受支持的完整ID。" },
    antigravity: { label: "Antigravity", models: { flash: [], pro: [] }, fallback: "flash", effort: "", identities: ["reviewer", "planner"], source: "agy models 会话目录＋子代理 tier 合同（离线样本）", boundary: "完整会话ID demo-session-model-01 仅供会话目录展示，不出现在子代理候选中。子代理只使用 inherit / flash / pro；独立推理与调用schema未核实，此原型不生成调用参数。" }
  };
  const kindNames = { preferences: "调用偏好", native: "原生定义文件", activation: "工作流启停" };
  const activationNames = { inherit: "继承", enabled: "启用", disabled: "停用" };
  let host = "codex", scope = "global", project = "/demo/projects/atlas", section = "models", mode = "preferences", plan = null, refreshing = false;
  const locations = new Map();
  // 切换回执可短时收起；草稿数量、当前对象、保存结果不依赖该计时器。
  let switchNoticeTimer = null;
  const key = (h = host, s = scope) => `${h}:${s}${s === "project" ? ":" + project : ""}`;
  // 首次创建独立样本：项目的继承来源是已保存的用户级值，不偷用其他范围的未保存草稿。
  function location(h = host, s = scope) {
    const id = key(h, s);
    if (!locations.has(id)) {
      const preferences = { default: { model: "", effort: "" }, a: { model: "", effort: "" }, b: { model: "", effort: "" } };
      if (h === "claude" && s === "global") preferences.a.model = "opus";
      const native = { user: { model: s === "global" ? hosts[h].fallback : "", effort: h === "antigravity" ? "" : "medium" } };
      const values = { preferences, native, activation: { state: "inherit" } };
      const result = { selected: new Set(), needsReload: false, lastSave: "演示初始值" };
      for (const [name, value] of Object.entries(values)) result[name] = { saved: copy(value), draft: copy(value), partial: null, receipt: "", savedOnce: false };
      locations.set(id, result);
    }
    return locations.get(id);
  }
  const currentKind = () => section === "activation" ? "activation" : mode;
  const current = () => location()[currentKind()];
  const scopeName = () => scope === "global" ? "用户级" : `当前项目 · ${project.split("/").pop()}`;
  const contextName = () => `${hosts[host].label} · ${scopeName()}`;
  const targetName = id => id === "default" ? "通用默认" : id === "user" ? `原生定义 ${host === "antigravity" ? "planner" : "researcher"}` : hosts[host].identities[id === "a" ? 0 : 1];
  function changes(store = current()) {
    const rows = [];
    if ("state" in store.draft) {
      if (store.saved.state !== store.draft.state) rows.push({ id: "activation", field: "state", before: store.saved.state, after: store.draft.state });
      return rows;
    }
    for (const id of Object.keys(store.draft)) for (const field of ["model", "effort"]) {
      if (store.draft[id][field] !== store.saved[id][field]) rows.push({ id, field, before: store.saved[id][field], after: store.draft[id][field] });
    }
    return rows;
  }
  function allDirty() {
    let count = 0;
    for (const loc of locations.values()) for (const kind of Object.keys(kindNames)) count += changes(loc[kind]).length;
    return count;
  }
  function notify(text, tone = "info", id = "action-feedback") {
    const node = $(id); node.textContent = text; node.dataset.tone = tone; node.hidden = !text;
  }
  // 按实际四层顺序逐字段解析。当前范围仅消费当前调用偏好草稿；其他范围消费保存值。
  function resolve(id, field, pending) {
    const layers = [];
    for (const s of ["global", ...(scope === "project" ? ["project"] : [])]) {
      const loc = location(host, s);
      const value = s === scope ? loc.preferences.draft : loc.preferences.saved;
      const prefix = s === "global" ? "用户" : "项目";
      layers.push([s === scope && id === "default" && pending !== undefined ? pending : value.default[field], `${prefix}通用默认`]);
      if (id !== "default") layers.push([s === scope && pending !== undefined ? pending : value[id][field], `${prefix}该 Agent`]);
    }
    let result = { value: field === "model" ? hosts[host].fallback : hosts[host].effort, source: "宿主默认（演示）" };
    for (const [value, source] of layers) if (value) result = { value, source };
    return result;
  }
  function setOptions(node, entries, value) {
    node.replaceChildren();
    const options = [...entries];
    // 不兼容旧值保留在下拉框并明确标记，避免切模型时悄悄更改另一字段。
    if (!options.some(item => item[0] === value)) options.push([value, `${value}（原值不兼容，请重选）`]);
    for (const [id, text] of options) { const option = document.createElement("option"); option.value = id; option.textContent = text; node.append(option); }
    node.value = value;
  }
  // 展示名称与逻辑ID分离，模型目录仍是离线虚构样本；原始ID在解析来源和预览保留。
  const modelLabel = id => ({ "demo-balanced": "均衡模型 · 演示", "demo-fast": "轻量模型 · 演示", sonnet: "Sonnet", haiku: "Haiku", opus: "Opus", flash: "flash · 子代理 tier", pro: "pro · 子代理 tier" })[id] || id;
  const effortLabel = id => ({ low: "低", medium: "中等", high: "高" })[id] || id;
  const modelEntries = () => [["", "沿用继承设置"], ...Object.keys(hosts[host].models).map(id => [id, modelLabel(id)])];
  function effortEntries(model) { return [["", "沿用继承设置"], ...(hosts[host].models[model] || []).map(value => [value, effortLabel(value)])]; }
  function targetError(id, kind = "preferences") {
    const value = location()[kind].draft[id];
    const model = kind === "preferences" ? resolve(id, "model").value : value.model || hosts[host].fallback;
    const effort = kind === "preferences" ? resolve(id, "effort").value : value.effort;
    if (host === "antigravity") return effort ? "当前平台不支持独立推理级别，请显式清除。" : "";
    return effort && !(hosts[host].models[model] || []).includes(effort) ? `模型 ${model} 不支持 ${effort}。请重选推理级别或恢复继承；原值已保留。` : "";
  }
  function prefField(id, modelId, effortId, errorId) {
    const value = location().preferences.draft[id];
    // 继承仍以空值存储，但主选择框呈现真实解析结果，避免所有控件都只写“继承”。
    // 以 pending 空值计算移除当前层后的来源，不把本层草稿错误标成继承值。
    const models = modelEntries();
    models[0] = ["", `${modelLabel(resolve(id, "model", "").value)} · 继承`];
    const efforts = effortEntries(resolve(id, "model").value);
    efforts[0] = ["", host === "antigravity" ? "不支持独立推理" : `${effortLabel(resolve(id, "effort", "").value) || "宿主默认"} · 继承`];
    setOptions($(modelId), models, value.model);
    setOptions($(effortId), efforts, value.effort);
    $(effortId).disabled = host === "antigravity";
    const error = targetError(id); $(errorId).hidden = !error; $(errorId).textContent = error;
    $(effortId).setAttribute("aria-invalid", String(Boolean(error)));
    $(modelId).setAttribute("aria-describedby", id === "default" ? "default-model-source" : `model-source-${id}`);
    $(effortId).setAttribute("aria-describedby", `${id === "default" ? "default-effort-source" : `effort-source-${id}`} ${errorId}`);
  }
  function draftLabel(store, id) { return changes(store).some(row => row.id === id) ? "未保存草稿" : "已保存"; }
  function updateFooter() {
    const store = current(), count = changes(store).length;
    $("save-bar").hidden = section === "diagnostics"; $("save-bar").dataset.dirty = String(count > 0 || Boolean(store.partial));
    $("draft-count").textContent = store.partial ? "部分发布 · 待核对恢复" : count ? `${count} 项未保存更改` : store.savedOnce ? "已模拟保存 · 仅本页内存" : "无未保存更改";
    $("draft-status-detail").textContent = store.partial ? "草稿与恢复收据已保留 · 实际运行未验证" : `${currentKind() === "preferences" ? "供后续派发读取" : "等待新会话加载"} · 实际运行未验证`;
    $("draft-context").textContent = `${contextName()} · ${kindNames[currentKind()]}`;
    $("preview-save").textContent = store.partial ? "查看恢复收据" : "预览并保存";
    $("preview-save").disabled = !count && !store.partial;
    $("discard-draft").disabled = !count || Boolean(store.partial);
    for (const name of ["models", "activation"]) {
      const amount = name === "activation" ? changes(location().activation).length : changes(location().preferences).length + changes(location().native).length;
      $(`nav-${name}`).dataset.dirty = amount ? String(amount) : "";
    }
  }
  function renderBatch() {
    const selected = [...location().selected], previousModel = $("batch-model").value, previousEffort = $("batch-effort").value;
    $("batch-count").textContent = `已选择 ${selected.length} 个 Agent`;
    const batchModels = [["keep", "保持模型原值"], ...modelEntries()];
    const candidate = $("batch-model").options.length ? previousModel : "keep";
    setOptions($("batch-model"), batchModels, batchModels.some(item => item[0] === candidate) ? candidate : "keep");
    const sets = selected.map(id => hosts[host].models[$("batch-model").value === "keep" ? resolve(id, "model").value : $("batch-model").value || resolve(id, "model", "").value] || []);
    const common = sets.length ? sets[0].filter(value => sets.every(set => set.includes(value))) : [];
    const entries = [["keep", "保持推理原值"], ["", "清除本层推理（继承）"], ...common.map(value => [value, effortLabel(value)])];
    // 批量选择器没有已保存字段，目标变化后回到“保持原值”，不伪造能力并集。
    setOptions($("batch-effort"), entries, entries.some(item => item[0] === previousEffort) ? previousEffort : "keep");
    $("batch-effort").disabled = host === "antigravity";
    $("batch-apply").disabled = !selected.length;
  }
  function render() {
    const config = hosts[host], loc = location();
    document.querySelectorAll("[data-host]").forEach(node => { const active = node.dataset.host === host; node.setAttribute("aria-selected", String(active)); node.tabIndex = active ? 0 : -1; });
    $("platform-content").setAttribute("aria-labelledby", `platform-${host}`);
    $("scope-label").textContent = contextName(); $("loaded-project").textContent = project;
    $("project-location-label").textContent = `项目路径 · ${project.split("/").pop()}`;
    $("scope-subtitle").textContent = scope === "global" ? "此平台的所有项目默认使用" : "仅此项目覆盖 · 其他项目继承用户级";
    document.querySelectorAll("[data-section]").forEach(node => { if (node.dataset.section === section) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current"); });
    for (const name of ["models", "activation", "diagnostics"]) $(`section-${name}`).hidden = section !== name;
    $("preferences-editor").hidden = mode !== "preferences";
    $("native-editor").hidden = mode !== "native";
    $("editor-kicker").textContent = mode === "native" ? "高级 · 原生定义文件" : "调用偏好";
    $("models-title").textContent = mode === "native" ? "原生定义文件" : "调用偏好";
    $("editor-description").textContent = mode === "native" ? "编辑受支持的完整定义，插件缓存始终只读。" : "为后续派发选择模型与推理强度。";
    prefField("default", "default-model", "default-effort", "default-error");
    for (const field of ["model", "effort"]) { const resolved = resolve("default", field); $(`default-${field}-source`).textContent = field === "effort" && host === "antigravity" ? "当前平台不支持独立推理级别" : `来源：${resolved.source}`; }
    const defaultDirty = draftLabel(loc.preferences, "default") !== "已保存";
    $("default-state").textContent = defaultDirty ? "未保存草稿" : loc.preferences.saved.default.model || loc.preferences.saved.default.effort ? "本层覆盖" : "继承";
    $("default-reset").disabled = !loc.preferences.draft.default.model && !loc.preferences.draft.default.effort;
    $("default-state").dataset.dirty = String(defaultDirty);
    const hasAgents = config.identities.length > 0;
    $("agent-count").textContent = String(config.identities.length); $("agent-empty").hidden = hasAgents; $("agent-table").hidden = !hasAgents; $("batch-toggle").disabled = !hasAgents; $("batch-toggle").hidden = !hasAgents;
    if (!hasAgents) { $("batch-editor").hidden = true; $("batch-toggle").setAttribute("aria-expanded", "false"); }
    if (hasAgents) for (const id of ["a", "b"]) {
      $(`identity-${id}`).textContent = targetName(id);
      $(`origin-${id}`).textContent = host === "claude" && id === "a" ? "插件调用身份 · 演示发现" : `${scope === "project" ? "项目" : "用户"}调用身份 · 演示发现`;
      prefField(id, `model-${id}`, `effort-${id}`, `error-${id}`);
      $(`model-${id}`).setAttribute("aria-label", `${targetName(id)} 的模型`); $(`effort-${id}`).setAttribute("aria-label", `${targetName(id)} 的推理级别`);
      const resolved = resolve(id, "model"), resolvedEffort = resolve(id, "effort");
      $(`model-source-${id}`).textContent = `来源：${resolved.source}`;
      $(`effort-source-${id}`).textContent = host === "antigravity" ? "当前平台能力边界" : `来源：${resolvedEffort.source}`;
      const saved = loc.preferences.saved[id];
      // 状态只表达本层关系；未保存时额外保留已保存前像，避免每行重复三套徽标。
      const dirty = draftLabel(loc.preferences, id) !== "已保存";
      $(`source-${id}`).textContent = dirty ? `已保存：${saved.model ? modelLabel(saved.model) : "继承"}${host === "antigravity" ? "" : " / " + (saved.effort ? effortLabel(saved.effort) : "继承")}` : saved.model || saved.effort ? "已保存 · 后续派发读取" : "未设置本层字段";
      $(`state-${id}`).textContent = dirty ? "未保存草稿" : saved.model || saved.effort ? "本层覆盖" : "继承";
      $(`state-${id}`).dataset.dirty = String(dirty);
      $(`agent-row-${id}`).dataset.dirty = String(dirty);
      $(`reset-${id}`).disabled = !loc.preferences.draft[id].model && !loc.preferences.draft[id].effort;
      $(`select-${id}`).checked = loc.selected.has(id); $(`select-${id}`).setAttribute("aria-label", `选择 ${targetName(id)}`);
    }
    $("select-all").checked = loc.selected.size === 2; $("select-all").indeterminate = loc.selected.size === 1;
    $("preference-path").textContent = `演示保存位置：/demo/${host}/native-agent-config/dispatch-preferences.json${scope === "project" ? ` → projects[${project}]` : " → defaults / agents"}`;
    $("native-empty").hidden = host !== "codex"; $("native-fields").hidden = host === "codex";
    $("native-plugin-readonly").hidden = host !== "claude";
    if (host !== "codex") {
      $("native-identity").textContent = host === "claude" ? "researcher" : "planner";
      $("native-path").textContent = `演示文件：/demo/${scope === "global" ? "user" : project.slice(6)}/${host}/agents/${host === "claude" ? "researcher.md" : "planner.yaml"}`;
      const value = loc.native.draft.user; setOptions($("native-model"), modelEntries(), value.model); setOptions($("native-effort"), effortEntries(value.model || config.fallback), value.effort); $("native-effort").disabled = host === "antigravity";
      $("native-error").textContent = targetError("user", "native"); $("native-error").hidden = !targetError("user", "native");
      // 高级编辑器复用与调用偏好相同的字段错误语义，错误不会只依靠边框颜色传达。
      $("native-effort").setAttribute("aria-invalid", String(Boolean(targetError("user", "native"))));
      $("native-effort").setAttribute("aria-describedby", "native-error");
    }
    $("activation-supported").hidden = host === "antigravity"; $("activation-unsupported").hidden = host !== "antigravity";
    $("activation-state").disabled = host === "antigravity"; $("activation-state").value = loc.activation.draft.state;
    $("activation-saved").textContent = activationNames[loc.activation.saved.state];
    const inherited = scope === "project" ? location(host, "global").activation.saved.state : "enabled";
    $("activation-inherited").textContent = scope === "project" ? host === "claude" ? "项目 settings.json → 用户级（演示）" : `用户级 · ${inherited === "inherit" ? "宿主默认" : activationNames[inherited]}（演示）` : "官方默认 · 启用（演示）";
    $("activation-effective").textContent = loc.activation.saved.state === "inherit" ? inherited === "disabled" ? "停用（已观察样本）" : "启用（已观察样本）" : `${activationNames[loc.activation.saved.state]}（已观察样本）`;
    $("activation-consequence").textContent = loc.activation.draft.state === "disabled" ? "停用后插件内配置入口可能不可用。请先展开下方恢复说明，保留独立重新打开方式；保存后等待新会话加载。" : "保存后等待新会话加载；当前会话不会清除已加载上下文。";
    $("diagnostic-saved").textContent = loc.lastSave;
    $("catalog-source").textContent = config.source; $("catalog-boundary").textContent = config.boundary;
    $("diagnostic-location").textContent = `演示配置根 /demo/${host}；项目 ${project}。${host === "claude" && scope === "project" ? "启停目标为 .claude/settings.local.json，仅本机当前项目；清除后先继承 .claude/settings.json。" : host === "codex" && scope === "project" ? "启停目标为 .codex/config.toml；项目须受信任，Hook信任与更高层策略保持宿主规则。" : "位置由当前发现来源决定，不提供任意路径写入。"}`;
    $("refresh-catalog").disabled = refreshing;
    $("clear-overrides").disabled = !Object.values(loc.preferences.draft).some(value => value.model || value.effort);
    renderBatch(); updateFooter(); if (!allDirty()) $("switch-status").hidden = true;
  }
  function announceSwitch() {
    window.clearTimeout(switchNoticeTimer);
    const count = allDirty();
    $("switch-status").hidden = !count;
    $("switch-status").textContent = `${contextName()} · ${section === "activation" ? "工作流启停" : section === "diagnostics" ? "诊断与帮助" : kindNames[mode]}。共 ${count} 项未保存字段已按平台、范围与事务保留。`;
    // 仅收起可重复推导的导航回执；错误、保存回执及底部事务归属始终保留。
    if (count) switchNoticeTimer = window.setTimeout(() => { $("switch-status").hidden = true; }, 4000);
  }
  function changeContext(update) { update(); notify(""); $("catalog-feedback").hidden = true; render(); announceSwitch(); }
  document.querySelectorAll("[data-host]").forEach(node => node.addEventListener("click", () => changeContext(() => { host = node.dataset.host; })));
  $("platform-tabs").addEventListener("keydown", event => {
    const tabs = [...document.querySelectorAll("[data-host]")], index = tabs.indexOf(document.activeElement);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].focus(); tabs[next].click();
  });
  // 载入仅在两个虚构样本中选择；绝不探测真实路径，项目草稿使用绝对路径分键。
  $("load-project").addEventListener("click", () => {
    const candidate = $("project-path").value.trim();
    if (!["/demo/projects/atlas", "/demo/projects/orbit"].includes(candidate)) { notify("演示载入失败：请使用 /demo/projects/atlas 或 /demo/projects/orbit。当前项目与全部草稿已保留。", "error", "project-feedback"); $("project-path").setAttribute("aria-invalid", "true"); return; }
    $("project-path").setAttribute("aria-invalid", "false"); changeContext(() => { project = candidate; scope = "project"; $("scope-project").checked = true; }); notify(`已载入演示项目 ${candidate}。该项目三类草稿已恢复，其他目录草稿保留。`, "success", "project-feedback");
  });
  $("project-path").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); $("load-project").click(); } });
  for (const s of ["global", "project"]) $(`scope-${s}`).addEventListener("change", () => changeContext(() => { scope = s; }));
  document.querySelectorAll("[data-section]").forEach(node => node.addEventListener("click", () => changeContext(() => { section = node.dataset.section; })));
  $("open-native").addEventListener("click", () => changeContext(() => { mode = "native"; }));
  $("back-preferences").addEventListener("click", () => changeContext(() => { mode = "preferences"; }));
  // 各个字段显式绑定当前事务，模型变化只重新计算可选项，绝不自动清空 effort。
  for (const id of ["default", "a", "b"]) for (const field of ["model", "effort"]) {
    const control = id === "default" ? `default-${field}` : `${field}-${id}`;
    $(control).addEventListener("change", () => { location().preferences.draft[id][field] = $(control).value; notify(""); render(); });
  }
  for (const id of ["default", "a", "b"]) $(id === "default" ? "default-reset" : `reset-${id}`).addEventListener("click", () => { location().preferences.draft[id] = { model: "", effort: "" }; render(); notify(`${targetName(id)} 已在草稿中恢复继承；预览保存后才记录。`); });
  $("clear-overrides").addEventListener("click", () => { const store = location().preferences; for (const id of Object.keys(store.draft)) store.draft[id] = { model: "", effort: "" }; render(); notify("本范围调用偏好已在草稿中清除；其他范围与原生/启停草稿保持独立。"); });
  for (const field of ["model", "effort"]) $(`native-${field}`).addEventListener("change", () => { location().native.draft.user[field] = $(`native-${field}`).value; render(); });
  $("native-reset").addEventListener("click", () => { location().native.draft.user = { model: "", effort: "" }; render(); notify("原生字段已在草稿中清除；完整定义中的提示词与其他字段不变。"); });
  $("activation-state").addEventListener("change", () => { location().activation.draft.state = $("activation-state").value; render(); });
  for (const id of ["a", "b"]) $(`select-${id}`).addEventListener("change", () => { if ($(`select-${id}`).checked) location().selected.add(id); else location().selected.delete(id); render(); });
  $("select-all").addEventListener("change", () => { location().selected = new Set($("select-all").checked ? ["a", "b"] : []); render(); });
  $("batch-toggle").addEventListener("click", () => { $("batch-editor").hidden = !$("batch-editor").hidden; $("batch-toggle").setAttribute("aria-expanded", String(!$("batch-editor").hidden)); renderBatch(); });
  $("batch-model").addEventListener("change", renderBatch);
  $("batch-apply").addEventListener("click", () => {
    const model = $("batch-model").value, effort = $("batch-effort").value;
    if (model === "keep" && (effort === "keep" || host === "antigravity")) { notify("请至少选择一个需要修改的字段。", "warning"); return; }
    for (const id of location().selected) { const value = location().preferences.draft[id]; if (model !== "keep") value.model = model; if (effort !== "keep" && host !== "antigravity") value.effort = effort; }
    render(); notify(`已更新所选 ${location().selected.size} 个 Agent 的草稿，请检查后预览保存。`);
  });
  $("discard-draft").addEventListener("click", () => { const store = current(); store.draft = copy(store.saved); render(); notify(`已放弃当前${kindNames[currentKind()]}草稿；其他事务与范围草稿保留。`); });
  $("refresh-catalog").addEventListener("click", () => {
    // 模拟异步回执绑定发起时范围；切换之后旧回执不得污染新平台或清空新范围草稿。
    const requestKey = key(), requestHost = host, fail = $("catalog-scenario").value === "failure";
    $("catalog-scenario").value = "success"; refreshing = true; render(); notify("正在模拟读取模型目录…", "info", "catalog-feedback");
    window.setTimeout(() => { refreshing = false; render(); if (key() !== requestKey) return; notify(fail ? "目录读取失败（演示）：客户端未返回目录。已有模型与草稿已保留；请再次刷新，或在诊断中核对来源。" : `${hosts[requestHost].label} 演示目录已刷新；候选来源可在诊断中展开，实际运行仍未验证。`, fail ? "error" : "success", "catalog-feedback"); }, 500);
  });
  $("reload-context").addEventListener("click", () => { location().needsReload = false; render(); notify("已模拟重新读取配置；所有三类草稿保留。可返回原操作区重新预览；这不表示宿主已重新加载。", "success"); });
  function valueLabel(value, field) { return field === "state" ? activationNames[value] : value || "移除本层字段 → 继承"; }
  function drawPreview(rows) {
    $("preview-list").replaceChildren();
    for (const row of rows) { const item = document.createElement("div"), title = document.createElement("strong"), text = document.createElement("p"); item.className = "ac-preview-item"; title.textContent = `${row.id === "activation" ? "工作流启停" : targetName(row.id)} · ${row.field === "model" ? "模型" : row.field === "effort" ? "推理级别" : "本层状态"}`; text.textContent = `${valueLabel(row.before, row.field)} → ${valueLabel(row.after, row.field)}`; item.append(title, text); $("preview-list").append(item); }
  }
  function showReceipt(store) { $("recovery-receipt").hidden = !store.receipt; $("recovery-receipt").textContent = store.receipt; $("recover-save").hidden = !store.partial; }
  window.agentDemo = { preparePreview() {
    const store = current(), kind = currentKind();
    if (store.partial) { plan = { ...store.partial.plan, store, recovering: true }; drawPreview(plan.rows); showReceipt(store); notify("此演示事务存在已发布项，请先核对收据并恢复。", "warning", "save-result"); $("confirm-save").disabled = true; }
    else {
      if (location().needsReload) { notify("来源已变化，请到“诊断与帮助”重新读取后再预览。草稿已保留。", "error"); return false; }
      const ids = kind === "native" ? host === "codex" ? [] : ["user"] : kind === "preferences" ? ["default", ...(hosts[host].identities.length ? ["a", "b"] : [])] : [];
      const invalid = ids.find(id => targetError(id, kind));
      if (invalid) { notify(targetError(invalid, kind), "error"); $(kind === "native" ? "native-effort" : invalid === "default" ? "default-effort" : `effort-${invalid}`).focus(); return false; }
      const rows = changes(store); if (!rows.length) return false;
      plan = { host, scope, kind, rows, before: copy(store.saved), after: copy(store.draft), store, location: location() };
      drawPreview(rows); $("save-result").hidden = true; $("recovery-receipt").hidden = true; $("recover-save").hidden = true; $("confirm-save").disabled = false;
    }
    $("preview-title").textContent = `确认${kindNames[kind]}`; $("preview-scope").textContent = `${contextName()} · 仅此事务，其他草稿保留`;
    $("confirm-save").textContent = "确认模拟保存"; return true;
  } };
  $("confirm-save").addEventListener("click", () => {
    if (!plan || plan.store.partial) return;
    const snapshot = plan, scenario = $("save-scenario").value; $("save-scenario").value = "success";
    $("confirm-save").disabled = true; $("close-preview").disabled = true; $("cancel-preview").disabled = true; $("preview-dialog").setAttribute("aria-busy", "true"); notify("正在模拟保存…不会写入本机文件。", "info", "save-result");
    window.setTimeout(() => {
      $("preview-dialog").setAttribute("aria-busy", "false"); $("close-preview").disabled = false; $("cancel-preview").disabled = false;
      if (scenario === "conflict") { snapshot.location.needsReload = true; notify("模拟保存被拒绝：来源或前像已变化，未发布更改。草稿保留；返回编辑，在诊断中重新读取后重新预览。", "error", "save-result"); }
      else if (scenario === "partial") {
        const first = snapshot.rows[0]; if (first.field === "state") snapshot.store.saved.state = first.after; else snapshot.store.saved[first.id][first.field] = first.after;
        snapshot.store.partial = { before: snapshot.before, plan: snapshot }; snapshot.store.receipt = `模拟收据 DEMO-001：首项“${first.field}”已发布到演示内存；其余项未发布/未确认。前像保留在本页内存，位置已知（演示）。没有真实磁盘备份。返回前请核对并模拟恢复；收据不会因恢复而删除。`;
        showReceipt(snapshot.store); notify("模拟部分发布：请求尚未完整确认，不能视为全部成功或全部回滚。", "warning", "save-result");
      } else {
        snapshot.store.saved = copy(snapshot.after); snapshot.store.draft = copy(snapshot.after); snapshot.store.savedOnce = true; snapshot.location.lastSave = `${kindNames[snapshot.kind]}已模拟保存 · 仅本页内存`;
        notify(`${kindNames[snapshot.kind]}已模拟保存。${snapshot.kind === "preferences" ? "正式行为：供后续派发读取。" : "正式行为：等待新会话重新加载。"}实际运行未验证；本机文件未改变。`, "success", "save-result");
      }
      render();
    }, 550);
  });
  $("recover-save").addEventListener("click", () => {
    const store = plan?.store; if (!store?.partial) return;
    store.saved = copy(store.partial.before); store.partial = null; store.receipt += " 已模拟恢复首项前像，草稿仍保留；原收据保留，实际磁盘与运行均未验证。";
    showReceipt(store); notify("已模拟恢复发布项。请返回编辑，检查草稿后重新预览。", "success", "save-result"); render();
  });
  // 正在结算时阻止 Esc 避免模态消失而结果无处展示；结算后恢复原生取消语义。
  $("preview-dialog").addEventListener("cancel", event => { if ($("preview-dialog").getAttribute("aria-busy") === "true") event.preventDefault(); });
  $("preview-dialog").addEventListener("close", () => { if (plan?.store.partial) notify("存在模拟部分发布，草稿与恢复收据已保留。点击“查看恢复收据”继续处理。", "warning"); render(); if (!$("preview-save").disabled) $("preview-save").focus(); else $(section === "activation" ? "activation-state" : mode === "native" ? "native-model" : "default-model").focus(); });
  render(); announceSwitch();
})();
