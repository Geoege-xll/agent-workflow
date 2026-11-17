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
  const exports = {NativeDefinitions, facts};
  if (typeof module !== "undefined" && module.exports) module.exports = exports;
  else globalThis.ConsoleNativeDefinitions = exports;
})();
