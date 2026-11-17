/* 原生定义只读投影：搜索和选中身份不拥有模型/推理值，编辑始终进入现有 FieldDraft。 */
(() => {
  "use strict";
  class NativeDefinitions {
    constructor() { this.locations = new Map(); }
    state(key) {
      if (!this.locations.has(key)) this.locations.set(key, {query:"", selected:null});
      return this.locations.get(key);
    }
    project(key, rows) {
      const state = this.state(key), query = state.query.trim().toLocaleLowerCase();
      // 首次载入选真实首项；一旦选定，即使搜索将它隐藏也不把编辑对象改成搜索首项。
      if (state.selected === null && rows.length) state.selected = rows[0].role;
      return {rows:rows.filter(row => !query || [row.name, row.role, row.description, row.source_path].some(value => typeof value === "string" && value.toLocaleLowerCase().includes(query))),
        selected:rows.find(row => row.role === state.selected) || null, query:state.query};
    }
    search(key, query) { this.state(key).query = query; }
    select(key, id, rows) { if (rows.some(row => row.role === id)) this.state(key).selected = id; }
  }
  function facts(row) {
    // 明确区分false与未提供；职责、来源和权限不由身份名或插件路径猜测。
    return [["权限", "宿主未提供可核验权限信息"],
      ["启用状态", row.enabled === true ? "已观察到启用 · 会话加载未验证" : row.enabled === false ? "已观察到停用" : "宿主未提供可核验启用状态"],
      ["稳定身份", row.role], ["定义状态", row.definition_status || "宿主未提供定义状态"]];
  }
  const PREPARATION_STATUSES = {missing:"可准备 · 仅创建缺失定义", existing:"已有定义 · 保留原文件", conflict:"存在冲突 · 不会覆盖", blocked:"当前受阻 · 不会写入"};
  function preparationState(value, host) {
    // 准备候选属于服务端只读来源，不属于已发现身份。独立校验这个可选能力，
    // 来源缺失或损坏只关闭准备入口，不能阻断已经存在的原生定义编辑。
    const record = item => item !== null && typeof item === "object" && !Array.isArray(item);
    const text = item => typeof item === "string" && item.length > 0;
    const ids = new Set();
    const valid = record(value) && typeof value.supported === "boolean" && Array.isArray(value.candidates) &&
      (value.supported ? text(value.source_id) && text(value.source_revision) : value.source_id === null && value.source_revision === null && !value.candidates.length) &&
      value.candidates.every(row => {
        if (!record(row) || !text(row.candidate_id) || ids.has(row.candidate_id) || !text(row.name) || typeof row.description !== "string" ||
            !Object.prototype.hasOwnProperty.call(PREPARATION_STATUSES, row.status) || !text(row.target_path)) return false;
        ids.add(row.candidate_id); return true;
      });
    if (!valid || !value.supported) return {available:false, candidates:[], missing:[], message:host === "codex" ?
      "当前入口尚未绑定可验证的 Codex 原生候选。请从 Codex 的 xy-config 入口重新打开以绑定其候选来源，再刷新定义；已有定义仍可编辑。" :
      "当前宿主暂不支持此准备入口。可切换到 Codex 并从已安装插件重新打开；已有定义仍可编辑。"};
    return {available:true, source_id:value.source_id, source_revision:value.source_revision, candidates:value.candidates,
      missing:value.candidates.filter(row => row.status === "missing"), message:"仅创建缺失定义；已有、冲突或受阻的文件不会改写。"};
  }
  function preparationPayload(context) {
    const state = preparationState(context?.native_preparation, context?.host);
    if (!state.available || !state.missing.length) return null;
    // 客户端只交服务端已核验的候选 ID 与来源指纹，绝不提交目标路径、TOML 正文或其他事务草稿。
    return {source_id:state.source_id, source_revision:state.source_revision, candidate_ids:state.missing.map(row => row.candidate_id)};
  }
  const exports = {NativeDefinitions, facts, PREPARATION_STATUSES, preparationState, preparationPayload};
  if (typeof module !== "undefined" && module.exports) module.exports = exports;
  else globalThis.ConsoleNativeDefinitions = exports;
})();
