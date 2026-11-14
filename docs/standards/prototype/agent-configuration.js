(() => {
  "use strict";
  /* 所有数据只存在于本页面内存。这里不读取本机配置、不使用网络或浏览器持久化。
     平台/范围/事务是三个独立键；保存、放弃与恢复均只触达当前事务。 */
  const $ = id => document.getElementById(id);
  const copy = value => JSON.parse(JSON.stringify(value));
  const hosts = {
    codex: { label: "Codex", models: { "demo-balanced": ["low", "medium", "high"], "demo-fast": ["low", "medium"], "demo-long-context-reasoning-model-2026-preview": ["medium", "high"], "demo-code-review-specialist-extended": ["low", "medium", "high"] }, fallback: "demo-balanced", effort: "medium", identities: [], source: "原生 model/list（离线目录样本）", boundary: "展示模型自身的推理元数据。此处模型ID为虚构样本；零原生角色也可编辑通用默认，不把任务标签视为调用身份。" },
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
    let result = { value: field === "model" ? hosts[host].fallback : hosts[host].effort, source: "宿主默认" };
    for (const [value, source] of layers) if (value) result = { value, source };
    return result;
  }
  function setOptions(node, entries, value) {
    node.replaceChildren();
    const options = [...entries];
    // 不兼容旧值保留在下拉框并明确标记，避免切模型时悄悄更改另一字段。
    if (!options.some(item => item[0] === value)) options.push([value, node.id.includes("model") ? `${value}（目录未列出 / 原值保留）` : `${effortLabel(value)}（原值不兼容，请重选）`]);
    for (const [id, text] of options) { const option = document.createElement("option"); option.value = id; option.textContent = text; node.append(option); }
    node.value = value;
  }
  // 展示名称与逻辑ID分离，模型目录仍是离线虚构样本；原始ID在解析来源和预览保留。
  const modelLabel = id => ({ "demo-balanced": "均衡模型", "demo-fast": "轻量模型", "demo-long-context-reasoning-model-2026-preview": "长上下文推理模型 · Preview", "demo-code-review-specialist-extended": "代码审查扩展模型", sonnet: "Sonnet", haiku: "Haiku", opus: "Opus", flash: "flash · 子代理 tier", pro: "pro · 子代理 tier" })[id] || id;
  const effortLabel = id => ({ low: "低", medium: "中等", high: "高" })[id] || id;
  const modelEntries = () => [["", "沿用继承设置"], ...Object.keys(hosts[host].models).map(id => [id, modelLabel(id)])];
  function effortEntries(model) {
    // 未知模型只展示独立的工具合同候选，绝不声称这些是该模型的目录能力。
    const known = Object.hasOwn(hosts[host].models, model);
    const values = known ? hosts[host].models[model] : host === "antigravity" ? [] : ["low", "medium", "high"];
    return [["", "沿用继承设置"], ...values.map(value => [value, `${effortLabel(value)}${known ? "" : " · 能力未核实"}`])];
  }
  function targetError(id, kind = "preferences") {
    const value = location()[kind].draft[id];
    const model = kind === "preferences" ? resolve(id, "model").value : value.model || hosts[host].fallback;
    const effort = kind === "preferences" ? resolve(id, "effort").value : value.effort;
    if (host === "antigravity") return effort ? "当前平台不支持独立推理级别，请显式清除。" : "";
    const values = Object.hasOwn(hosts[host].models, model) ? hosts[host].models[model] : ["low", "medium", "high"];
    return effort && !values.includes(effort) ? `模型 ${model} 的目录不支持推理值 ${effort}。请重选模型/推理或恢复继承；原值已保留。` : "";
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
    const unknownModel = value.model && !Object.hasOwn(hosts[host].models, value.model);
    $(modelId).dataset.unknown = String(Boolean(unknownModel));
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
    $("batch-apply").disabled = !selected.length; syncPickers();
  }
  function render() {
    const config = hosts[host], loc = location();
    document.querySelectorAll("[data-host]").forEach(node => { const active = node.dataset.host === host; node.setAttribute("aria-selected", String(active)); node.tabIndex = active ? 0 : -1; });
    $("platform-content").setAttribute("aria-labelledby", `platform-${host}`);
    $("scope-label").textContent = contextName(); $("loaded-project").textContent = project;
    $("current-platform").textContent = config.label;
    $("current-scope").textContent = scope === "global" ? "用户级" : `项目 · ${project.split("/").pop()}`;
    $("open-native").hidden = mode === "native"; $("back-preferences").hidden = mode !== "native";
    $("project-location-label").textContent = `项目位置 · ${project.split("/").pop()}`;
    $("scope-subtitle").textContent = scope === "global" ? "此平台的所有项目默认使用" : "仅此项目覆盖 · 其他项目继承用户级";
    document.querySelectorAll("[data-section]").forEach(node => { if (node.dataset.section === section) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current"); });
    for (const name of ["models", "activation", "diagnostics"]) $(`section-${name}`).hidden = section !== name;
    $("preferences-editor").hidden = mode !== "preferences";
    $("native-editor").hidden = mode !== "native";
    $("editor-kicker").textContent = mode === "native" ? "高级 · 原生定义文件" : "调用偏好";
    $("models-title").textContent = mode === "native" ? "原生定义文件" : "模型与推理";
    $("editor-description").textContent = mode === "native" ? "编辑受支持的完整定义，插件缓存始终只读。" : "为后续调用设置偏好，未设置字段按来源继承。";
    prefField("default", "default-model", "default-effort", "default-error");
    for (const field of ["model", "effort"]) { const resolved = resolve("default", field); $(`default-${field}-source`).textContent = field === "effort" && host === "antigravity" ? "当前平台不支持独立推理级别" : `${resolved.source}${!Object.hasOwn(config.models, resolve("default", "model").value) ? field === "model" ? " · 目录未列出，能力未核实" : " · 工具合同候选，模型能力未核实" : ""}`; }
    // 同一模型与推理来源只在视觉上显示一次；字段aria-describedby仍保留各自完整来源。
    $("default-effort-source").hidden = host === "antigravity" || resolve("default", "model").source === resolve("default", "effort").source && Object.hasOwn(config.models, resolve("default", "model").value);
    const defaultDirty = draftLabel(loc.preferences, "default") !== "已保存";
    $("default-state").textContent = defaultDirty ? "未保存草稿" : loc.preferences.saved.default.model || loc.preferences.saved.default.effort ? "本层覆盖" : "继承";
    $("default-reset").disabled = !loc.preferences.draft.default.model && !loc.preferences.draft.default.effort;
    $("default-state").dataset.dirty = String(defaultDirty);
    const hasAgents = config.identities.length > 0;
    $("agent-count").textContent = String(config.identities.length); $("agent-empty").hidden = hasAgents; $("agent-table").hidden = !hasAgents; $("batch-toggle").disabled = !hasAgents; $("batch-toggle").hidden = !hasAgents;
    if (!hasAgents) { $("batch-editor").hidden = true; $("batch-toggle").setAttribute("aria-expanded", "false"); }
    if (hasAgents) for (const id of ["a", "b"]) {
      $(`identity-${id}`).textContent = targetName(id);
      $(`origin-${id}`).textContent = host === "claude" && id === "a" ? "插件调用身份" : `${scope === "project" ? "项目" : "用户"}调用身份`;
      prefField(id, `model-${id}`, `effort-${id}`, `error-${id}`);
      $(`model-${id}`).setAttribute("aria-label", `${targetName(id)} 的模型`); $(`effort-${id}`).setAttribute("aria-label", `${targetName(id)} 的推理级别`);
      const resolved = resolve(id, "model"), resolvedEffort = resolve(id, "effort");
      $(`model-source-${id}`).textContent = `${resolved.source}${loc.preferences.draft[id].model && !Object.hasOwn(config.models, loc.preferences.draft[id].model) ? " · 目录未列出，能力未核实" : ""}`;
      $(`effort-source-${id}`).textContent = host === "antigravity" ? "当前平台能力边界" : `${resolvedEffort.source}${!Object.hasOwn(config.models, resolve(id, "model").value) ? " · 模型能力未核实" : ""}`;
      $(`effort-source-${id}`).hidden = host === "antigravity" || resolved.source === resolvedEffort.source && Object.hasOwn(config.models, resolve(id, "model").value);
      const saved = loc.preferences.saved[id];
      // 状态只表达本层关系；未保存时额外保留已保存前像，避免每行重复三套徽标。
      const dirty = draftLabel(loc.preferences, id) !== "已保存";
      $(`source-${id}`).textContent = dirty ? `已保存：${saved.model ? modelLabel(saved.model) : "继承"}${host === "antigravity" ? "" : " / " + (saved.effort ? effortLabel(saved.effort) : "继承")}` : "";
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
      $("native-capability-note").hidden = !value.model || Object.hasOwn(config.models, value.model);
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
    renderBatch(); updateFooter(); syncPickers(); $("refresh-catalog").setAttribute("aria-busy", String(refreshing)); $("refresh-catalog").querySelector("span").textContent = refreshing ? "读取中…" : "刷新目录"; if (!allDirty()) $("switch-status").hidden = true;
  }
  function announceSwitch() {
    window.clearTimeout(switchNoticeTimer);
    const count = allDirty();
    $("switch-status").hidden = !count;
    $("switch-status").textContent = `${contextName()} · ${section === "activation" ? "工作流启停" : section === "diagnostics" ? "诊断与帮助" : kindNames[mode]}。共 ${count} 项未保存字段已按平台、范围与事务保留。`;
    // 仅收起可重复推导的导航回执；错误、保存回执及底部事务归属始终保留。
    if (count) switchNoticeTimer = window.setTimeout(() => { $("switch-status").hidden = true; }, 4000);
  }
  function changeContext(update) { closePicker(false); closeContextMenus(); update(); notify(""); $("catalog-feedback").hidden = true; render(); announceSwitch(); }
  document.querySelectorAll("[data-host]").forEach(node => node.addEventListener("click", () => { changeContext(() => { host = node.dataset.host; }); $("platform-switch").focus(); }));
  $("platform-tabs").addEventListener("keydown", event => {
    const tabs = [...document.querySelectorAll("[data-host]")], index = tabs.indexOf(document.activeElement);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    // 披露中的平台Tab采用手动激活：方向键只定位，Enter/Space才选择并收起，避免箭头一动菜单就消失。
    event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (["ArrowRight","ArrowDown"].includes(event.key) ? 1 : -1) + tabs.length) % tabs.length;
    tabs.forEach((tab, i) => { tab.tabIndex = i === next ? 0 : -1; }); tabs[next].focus();
  });
  // 载入仅在两个虚构样本中选择；绝不探测真实路径，项目草稿使用绝对路径分键。
  $("load-project").addEventListener("click", () => {
    const candidate = $("project-path").value.trim();
    if (!["/demo/projects/atlas", "/demo/projects/orbit"].includes(candidate)) { notify("演示载入失败：请使用 /demo/projects/atlas 或 /demo/projects/orbit。当前项目与全部草稿已保留。", "error", "project-feedback"); $("project-path").setAttribute("aria-invalid", "true"); return; }
    $("project-path").setAttribute("aria-invalid", "false"); changeContext(() => { project = candidate; scope = "project"; $("scope-project").checked = true; }); notify(`已载入项目 ${candidate} 的演示配置；该项目草稿已恢复。`, "success"); $("project-toggle").focus();
  });
  $("project-path").addEventListener("keydown", event => { if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); $("load-project").click(); } });
  for (const s of ["global", "project"]) $(`scope-${s}`).addEventListener("change", () => { changeContext(() => { scope = s; }); $("scope-switch").focus(); });
  document.querySelectorAll("[data-section]").forEach(node => node.addEventListener("click", () => changeContext(() => { section = node.dataset.section; })));
  // 高级入口和返回控件在切换后会隐藏，焦点移到新事务可见入口，避免遗留在隐藏按钮。
  $("open-native").addEventListener("click", () => { changeContext(() => { mode = "native"; }); $("back-preferences").focus(); });
  $("back-preferences").addEventListener("click", () => { changeContext(() => { mode = "preferences"; }); focusField("default-model"); });
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
  function discardCurrent() {
    // 先恢复当前事务，再由明确确认按钮关闭dialog；关闭后不会把焦点留在已禁用的放弃按钮。
    const store = current(); store.draft = copy(store.saved); render();
    notify(`已放弃当前${kindNames[currentKind()]}草稿；其他事务与范围草稿保留。`);
  }
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
    // 前像与计划值分别显示；每次均使用textContent，模型ID不会作为HTML执行。
    for (const row of rows) {
      const item = document.createElement("div"), title = document.createElement("strong"), values = document.createElement("div");
      item.className = "ac-preview-item"; values.className = "ac-preview-values";
      title.textContent = `${row.id === "activation" ? "工作流启停" : targetName(row.id)} · ${row.field === "model" ? "模型" : row.field === "effort" ? "推理强度" : "本层状态"}`;
      for (const [label, value] of [["已保存", row.before], ["保存后", row.after]]) {
        const column = document.createElement("div"), caption = document.createElement("small"), text = document.createElement("p");
        caption.textContent = label; text.textContent = valueLabel(value, row.field); column.append(caption, text); values.append(column);
      }
      item.append(title, values); $("preview-list").append(item);
    }
  }
  function showReceipt(store) { $("recovery-receipt").hidden = !store.receipt; $("recovery-receipt").textContent = store.receipt; $("recover-save").hidden = !store.partial; }
  window.agentDemo = { discardCurrent, prepareDiscard() {
    $("discard-description").textContent = `${contextName()} · ${kindNames[currentKind()]}，共 ${changes().length} 项更改将恢复为已保存值。其他平台、范围与事务草稿保留。`;
    return changes().length > 0 && !current().partial;
  }, preparePreview() {
    const store = current(), kind = currentKind();
    if (store.partial) { plan = { ...store.partial.plan, store, recovering: true }; drawPreview(plan.rows); showReceipt(store); notify("此演示事务存在已发布项，请先核对收据并恢复。", "warning", "save-result"); $("confirm-save").disabled = true; }
    else {
      if (location().needsReload) { notify("来源已变化，请到“诊断与帮助”重新读取后再预览。草稿已保留。", "error"); return false; }
      const ids = kind === "native" ? host === "codex" ? [] : ["user"] : kind === "preferences" ? ["default", ...(hosts[host].identities.length ? ["a", "b"] : [])] : [];
      const invalid = ids.find(id => targetError(id, kind));
      if (invalid) { notify(targetError(invalid, kind), "error"); focusField(kind === "native" ? "native-effort" : invalid === "default" ? "default-effort" : `effort-${invalid}`); return false; }
      const rows = changes(store); if (!rows.length) return false;
      plan = { host, scope, kind, rows, before: copy(store.saved), after: copy(store.draft), store, location: location() };
      drawPreview(rows); $("save-result").hidden = true; $("recovery-receipt").hidden = true; $("recover-save").hidden = true; $("confirm-save").disabled = false;
    }
    $("preview-title").textContent = `确认${kindNames[kind]}`; $("preview-scope").textContent = `${contextName()} · 仅此事务，其他草稿保留`;
    const unverified = kind !== "activation" && Object.values(store.draft).some(value => value.model && !Object.hasOwn(hosts[host].models, value.model));
    $("preview-boundary").textContent = `模拟保存只更新本页内存，不改写本机文件。配置记录不等于宿主已加载或真实模型实际采用。${unverified ? " 此事务含目录未列出的模型；推理项仅为工具合同候选，模型能力与可调用性未核实。" : ""}`;
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
  $("preview-dialog").addEventListener("close", () => { if (plan?.store.partial) notify("存在模拟部分发布，草稿与恢复收据已保留。点击“查看恢复收据”继续处理。", "warning"); render(); if (!$("preview-save").disabled) $("preview-save").focus(); else focusField(section === "activation" ? "activation-state" : mode === "native" ? "native-model" : "default-model"); });

  /* 统一选择器是呈现适配层：读取原生select候选，确认后只发原字段change。
     不另存模型/推理草稿，平台差异、继承、批量交集与预览验证仍由上述单一状态机负责。
     每个触发按钮、搜索、关闭与自定义入口均在HTML五段契约中具有稳定映射。 */
  const pickerControls = new Map();
  let activePicker = null, pickerFrame = 0;
  const panel = $("choice-panel"), optionList = $("choice-options"), searchInput = $("choice-search");
  const nativePopover = Object.hasOwn(HTMLElement.prototype, "popover") && typeof panel.showPopover === "function";
  function focusField(id) { const button = pickerControls.get(id); (button && !button.hidden ? button : $(id)).focus(); }
  function syncPickers() {
    for (const [id, trigger] of pickerControls) {
      const source = $(id), option = source.selectedOptions[0];
      trigger.querySelector(".ac-picker-value").textContent = option?.textContent || "请选择";
      trigger.disabled = source.disabled;
      trigger.dataset.inherited = String(!source.value);
      trigger.setAttribute("aria-invalid", source.getAttribute("aria-invalid") || "false");
      // 复制当前字段名和就近说明，标签不会因为只剩可见数值而消失。
      const label = source.getAttribute("aria-label") || trigger.dataset.fieldLabel || ({"save-scenario":"下次模拟保存","catalog-scenario":"下次目录刷新"})[id] || id;
      trigger.setAttribute("aria-label", `${label}：${option?.textContent || "请选择"}`);
      const description = source.getAttribute("aria-describedby");
      if (description) trigger.setAttribute("aria-describedby", description); else trigger.removeAttribute("aria-describedby");
    }
  }
  function closePicker(returnFocus = true) {
    if (!activePicker) return;
    const trigger = activePicker.trigger;
    activePicker = null;
    if (nativePopover && panel.matches(":popover-open")) panel.hidePopover();
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false"); searchInput.setAttribute("aria-expanded", "false");
    searchInput.removeAttribute("aria-activedescendant"); optionList.removeAttribute("aria-activedescendant");
    if (returnFocus && !trigger.disabled && trigger.getClientRects().length) trigger.focus();
  }
  function customAllowed() {
    return activePicker?.model && (host === "codex" || host === "claude" && activePicker.source.id === "native-model");
  }
  function validCustomModelId(value) {
    // 与核心MODEL_ID保持同一字符合同：首位字母/数字，后续只允许列出的ASCII字符，最多200位。
    // 分别检查首位与全串非法字符，不使用JS的$结束锚，避免末尾换行/Unicode行分隔符被宽松接受。
    return value.length > 0 && value.length <= 200 && /^[A-Za-z0-9]/.test(value) &&
      !/[^A-Za-z0-9._:/+@\[\]-]/.test(value);
  }
  function customCandidate() {
    // 搜索仍可输入空格或中文；仅合法的原始输入可成为自定义ID，不静默裁剪成另一值。
    const value = searchInput.value;
    return customAllowed() && validCustomModelId(value) &&
      ![...activePicker.source.options].some(option => option.value === value) ? value : "";
  }
  function setActiveOption(index, scroll = true) {
    if (!activePicker) return;
    const options = [...optionList.children];
    activePicker.index = options.length ? Math.max(0, Math.min(index, options.length - 1)) : -1;
    for (let i = 0; i < options.length; i++) options[i].dataset.active = String(i === activePicker.index);
    const option = options[activePicker.index], receiver = activePicker.model ? searchInput : optionList;
    if (option) { receiver.setAttribute("aria-activedescendant", option.id); if (scroll) option.scrollIntoView({block:"nearest"}); }
    else receiver.removeAttribute("aria-activedescendant");
  }
  function positionPicker() {
    if (!activePicker) return;
    const rect = activePicker.trigger.getBoundingClientRect(), viewport = window.visualViewport;
    // 使用视觉视口处理缩放/软键盘；上下择优，左右夹紧，限高由候选容器局部滚动承担。
    const leftEdge = (viewport?.offsetLeft || 0) + 8, topEdge = (viewport?.offsetTop || 0) + 8;
    const width = viewport?.width || document.documentElement.clientWidth, height = viewport?.height || window.innerHeight;
    const rightEdge = leftEdge + width - 16, bottomEdge = topEdge + height - 16;
    if (rect.bottom < topEdge || rect.top > bottomEdge) { closePicker(false); return; }
    panel.style.inlineSize = `${Math.min(Math.max(rect.width, activePicker.model ? 360 : 280), width - 16)}px`;
    panel.style.maxBlockSize = `${Math.min(440, height - 16)}px`;
    const natural = panel.scrollHeight, below = bottomEdge - rect.bottom - 6, above = rect.top - topEdge - 6;
    const useAbove = below < Math.min(natural, 240) && above > below;
    const available = Math.max(40, useAbove ? above : below);
    panel.style.maxBlockSize = `${Math.min(440, available, height - 16)}px`;
    const actualHeight = panel.getBoundingClientRect().height, actualWidth = panel.getBoundingClientRect().width;
    panel.style.left = `${Math.max(leftEdge, Math.min(rect.left, rightEdge - actualWidth))}px`;
    panel.style.top = `${Math.max(topEdge, Math.min(useAbove ? rect.top - 6 - actualHeight : rect.bottom + 6, bottomEdge - actualHeight))}px`;
  }
  function schedulePickerPosition() {
    if (!activePicker || pickerFrame) return;
    pickerFrame = requestAnimationFrame(() => { pickerFrame = 0; positionPicker(); });
  }
  function renderChoices() {
    if (!activePicker) return;
    const source = activePicker.source, model = activePicker.model, query = model ? searchInput.value.trim().toLocaleLowerCase() : "";
    optionList.replaceChildren();
    const entries = [...source.options].filter(option => !query || `${option.textContent} ${option.value}`.toLocaleLowerCase().includes(query));
    for (const [index, option] of entries.entries()) {
      const item = document.createElement("div"), check = document.createElement("span"), copy = document.createElement("span"), name = document.createElement("strong");
      item.id = `choice-${source.id}-${index}`; item.className = "ac-choice-option"; item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(option.value === source.value)); item.dataset.value = option.value;
      item.dataset.inherited = String(option.value === "");
      check.className = "ac-option-check"; check.setAttribute("aria-hidden", "true"); check.textContent = option.value === source.value ? "✓" : "";
      copy.className = "ac-option-copy"; name.textContent = option.textContent; copy.append(name);
      if (model && option.value && option.value !== "keep") {
        const raw = document.createElement("small"); raw.textContent = option.value; copy.append(raw);
      }
      item.append(check, copy);
      // 已选与当前键盘活动各自表达；继承与未知值有文字标记，完全不依赖颜色。
      const badgeText = option.value === "" ? "继承" : model && option.value !== "keep" && !Object.hasOwn(hosts[host].models, option.value) ? "目录未列出" : option.value === source.value ? "当前" : "";
      if (badgeText) { const badge = document.createElement("span"); badge.className = "ac-option-badge"; badge.textContent = badgeText; item.append(badge); }
      item.addEventListener("pointermove", () => setActiveOption(index, false));
      item.addEventListener("pointerdown", event => event.preventDefault());
      item.addEventListener("click", () => commitChoice(option.value)); optionList.append(item);
    }
    $("choice-empty").hidden = entries.length > 0;
    $("choice-custom").hidden = !customCandidate();
    $("choice-custom-label").textContent = customCandidate() ? `使用自定义 ID：${customCandidate()}` : "使用自定义模型 ID";
    const invalidCustomInput = model && customAllowed() && searchInput.value && !validCustomModelId(searchInput.value);
    $("choice-help").textContent = invalidCustomInput ? "仅用于搜索：自定义 ID 须以英文字母/数字开头，最多200位，仅含字母、数字及 . _ : / + @ [ ] -" : model ? customAllowed() ? "↑ ↓ 选择 · Enter 确认 · 自定义值的模型能力待核实" : host === "antigravity" ? "仅使用子代理 flash / pro tier · 会话模型 ID 不适用" : "调用偏好仅接受官方别名 · 完整 ID 请在原生定义编辑" : "↑ ↓ / Home End 选择 · Enter 确认 · Esc 取消";
    const selected = entries.findIndex(option => option.value === source.value);
    setActiveOption(selected < 0 ? 0 : selected, false); positionPicker();
  }
  function openPicker(source, last = false) {
    const trigger = pickerControls.get(source.id);
    if (!trigger || trigger.disabled) return;
    if (activePicker?.source === source) { closePicker(); return; }
    closePicker(false);
    const model = source.id.includes("model");
    activePicker = {source, trigger, model, index: -1};
    $("choice-title").textContent = model ? "选择模型" : source.id.includes("effort") ? "选择推理强度" : source.id === "activation-state" ? "本层工作流设置" : "选择演示结果";
    $("choice-search-area").hidden = !model; optionList.tabIndex = model ? -1 : 0;
    optionList.setAttribute("aria-label", $("choice-title").textContent);
    searchInput.value = ""; searchInput.setAttribute("aria-expanded", String(model));
    trigger.setAttribute("aria-expanded", "true"); panel.hidden = false;
    // 使用特性检测，不引入polyfill/CDN。原生Popover可用时处于top layer；回退仍有完整关闭/键盘语义。
    if (nativePopover) panel.showPopover();
    renderChoices();
    if (last) setActiveOption(optionList.children.length - 1, false);
    (model ? searchInput : optionList).focus({preventScroll:true});
    setActiveOption(activePicker.index);
  }
  function commitChoice(value) {
    if (!activePicker) return;
    const {source, trigger} = activePicker;
    // 自定义入口也通过同一个原生字段事件提交，文本始终不作为HTML/代码解释。
    if (![...source.options].some(option => option.value === value)) {
      const option = document.createElement("option"); option.value = value; option.textContent = `${value}（目录未列出 / 原值保留）`; source.append(option);
    }
    closePicker(false); source.value = value; source.dispatchEvent(new Event("change", {bubbles:true})); syncPickers();
    if (!trigger.disabled) trigger.focus();
  }
  function initPickers() {
    // 浮层挂在body，避开产品容器查询形成的fixed包含块；复用同一.ac语义token，
    // 因此原生Popover及手动回退都使用视觉视口坐标，不被表格或保存栏裁切。
    panel.classList.add("ac"); document.body.append(panel);
    for (const source of document.querySelectorAll("select[data-picker-source]")) {
      const trigger = $(`${source.id}-picker`);
      const label = document.querySelector(`label[for="${source.id}"]`);
      if (label) { trigger.dataset.fieldLabel = label.textContent.trim(); label.htmlFor = trigger.id; }
      pickerControls.set(source.id, trigger); source.hidden = true; trigger.hidden = false;
      trigger.addEventListener("click", () => openPicker(source));
      trigger.addEventListener("keydown", event => {
        if (["ArrowDown","ArrowUp"].includes(event.key)) { event.preventDefault(); openPicker(source, event.key === "ArrowUp"); }
      });
      source.addEventListener("change", syncPickers);
    }
    $("choice-close").addEventListener("click", () => closePicker());
    $("choice-custom").addEventListener("click", () => { const value = customCandidate(); if (value) commitChoice(value); });
    searchInput.addEventListener("input", () => renderChoices());
    panel.addEventListener("keydown", event => {
      if (!activePicker || event.isComposing) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closePicker(); return; }
      if (event.key === "Tab") {
        const trigger = activePicker.trigger;
        // 先按DOM顺序遍历关闭、搜索和可见自定义入口，保证每个按钮都能由键盘到达；
        // 跨出浮层边界才按原触发按钮的页面顺序继续，Tab始终不确认高亮项。
        const localTargets = [...panel.querySelectorAll('button,input,[tabindex="0"]')].filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
        const localNext = localTargets[localTargets.indexOf(document.activeElement) + (event.shiftKey ? -1 : 1)];
        if (localNext) { event.preventDefault(); localNext.focus(); return; }
        const targets = [...document.querySelectorAll('a[href],button,input,select,summary,[tabindex="0"]')].filter(node => !panel.contains(node) && !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
        const index = targets.indexOf(trigger), next = targets[index + (event.shiftKey ? -1 : 1)];
        closePicker(false); if (next) { event.preventDefault(); next.focus(); } else trigger.focus(); return;
      }
      if (![searchInput,optionList].includes(event.target)) return;
      const count = optionList.children.length;
      if (["ArrowDown","ArrowUp"].includes(event.key) || event.target === optionList && ["Home","End"].includes(event.key)) {
        event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : count ? (activePicker.index + (event.key === "ArrowDown" ? 1 : -1) + count) % count : -1;
        setActiveOption(next); return;
      }
      if (event.key === "Enter" || event.key === " " && event.target === optionList) {
        event.preventDefault(); const option = optionList.children[activePicker.index];
        if (option) commitChoice(option.dataset.value); else if (customCandidate()) commitChoice(customCandidate());
      }
    });
    document.addEventListener("pointerdown", event => { if (activePicker && !panel.contains(event.target) && !activePicker.trigger.contains(event.target)) closePicker(false); });
    document.addEventListener("focusin", event => { if (activePicker && !panel.contains(event.target) && !activePicker.trigger.contains(event.target)) closePicker(false); });
    window.addEventListener("resize", schedulePickerPosition); document.addEventListener("scroll", schedulePickerPosition, true);
    window.visualViewport?.addEventListener("resize", schedulePickerPosition); window.visualViewport?.addEventListener("scroll", schedulePickerPosition);
    $("discard-dialog").addEventListener("close", () => {
      if (!$("discard-draft").disabled) $("discard-draft").focus();
      else focusField(section === "activation" ? "activation-state" : mode === "native" ? "native-model" : "default-model");
    });
  }


  const contextMenus = [$("platform-menu"), $("scope-menu"), $("project-toggle").parentElement];
  function closeContextMenus() { contextMenus.forEach(menu => { menu.open = false; }); }
  function initContextMenus() {
    for (const menu of contextMenus) {
      const summary = menu.querySelector("summary");
      menu.addEventListener("toggle", () => { if (menu.open) { closePicker(false); contextMenus.forEach(other => { if (other !== menu) other.open = false; }); } });
      menu.addEventListener("keydown", event => {
        if (event.key === "Escape" && menu.open) { event.preventDefault(); event.stopPropagation(); menu.open = false; summary.focus(); }
      });
      menu.addEventListener("focusout", event => { if (!menu.contains(event.relatedTarget)) menu.open = false; });
    }
    $("platform-switch").addEventListener("keydown", event => {
      if (event.key === "ArrowDown") { event.preventDefault(); $("platform-menu").open = true; requestAnimationFrame(() => $(`platform-${host}`).focus()); }
    });
    document.addEventListener("pointerdown", event => { contextMenus.forEach(menu => { if (menu.open && !menu.contains(event.target)) menu.open = false; }); });
  }

  initPickers(); initContextMenus(); render(); announceSwitch();
})();
