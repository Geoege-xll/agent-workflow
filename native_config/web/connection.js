/* 浏览器连接生命周期：只持有服务签发的短期凭据，配置草稿仍由 console.js 管理。 */
(() => {
  "use strict";
  const STORAGE_KEY = "agent-workflow.console.session.v1";
  const HISTORY_KEY = "agentWorkflowConsole";
  const HOSTS = ["codex", "claude", "antigravity"];
  const REOPEN = "请回到宿主主会话，显式运行 xy-workflow:xy-config Skill 重新打开配置页。";
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  function navigation(value) {
    if (!object(value) || !HOSTS.includes(value.host) || !["global", "project"].includes(value.scope)) return null;
    if (value.scope === "project" && (typeof value.project !== "string" || !value.project.startsWith("/") || value.project.length > 4096 || value.project.split("/").includes("..") || /[\x00-\x1f]/.test(value.project))) return null;
    return {host:value.host, scope:value.scope, ...(value.scope === "project" ? {project:value.project} : {}),
      view:["preferences", "native", "activation", "diagnostics"].includes(value.view) ? value.view : "preferences"};
  }
  function sessionContract(value, origin, now = Date.now()) {
    // 恢复数据是可篡改输入：格式、origin及绝对期限全部验证，不能只凭存储键存在获得认证。
    return object(value) && value.schema_version === 1 && value.origin === origin &&
      typeof value.session_token === "string" && /^[A-Za-z0-9_-]{43}$/.test(value.session_token) &&
      typeof value.instance_id === "string" && /^[a-f0-9]{32}$/.test(value.instance_id) &&
      Number.isSafeInteger(value.expires_at) && value.expires_at > now && value.expires_at <= now + 1800000 ? value : null;
  }
  class Connection {
    constructor(api, environment) {
      this.api = api; this.environment = environment; this.session = null; this.ready = false; this.storageAvailable = true;
    }
    error(code, message) { const error = new Error(message + " " + REOPEN); error.code = code; return error; }
    clear() {
      this.ready = false; this.session = null; this.api.token = "";
      try { this.environment.storage().removeItem(STORAGE_KEY); } catch (_) { this.storageAvailable = false; }
    }
    remember(location, view) {
      // history只记录非秘密导航，并合并其它消费者已有state；原入口/派生令牌均不进入history。
      const value = navigation({...location, view}); if (!value) return;
      const {history} = this.environment;
      try { history.replaceState({...(object(history.state) ? history.state : {}), [HISTORY_KEY]:value}, "", this.environment.cleanUrl); }
      catch (_) { /* history受限不影响当前合法会话；刷新上下文恢复能力由浏览器决定。 */ }
    }
    async start(fragment) {
      const env = this.environment;
      const fresh = Boolean(fragment.get("token"));
      const storedNavigation = navigation(env.history.state?.[HISTORY_KEY]);
      this.initial = fresh ? navigation({host:HOSTS.includes(fragment.get("host")) ? fragment.get("host") : "codex",
        scope:fragment.get("project") ? "project" : "global", project:fragment.get("project"), view:"preferences"}) : storedNavigation;
      this.initial ||= {host:"codex", scope:"global", view:"preferences"};
      // 清片段发生在第一个异步点前；失败也不会将带认证片段的地址保留给复制操作。
      this.remember(this.initial, this.initial.view);
      try {
        if (fresh) {
          this.clear(); this.api.token = fragment.get("token"); fragment.delete("token");
          let value;
          try { value = await this.api.request("/api/session", {}); }
          finally { this.api.token = ""; }
          this.session = sessionContract(value, env.origin);
          if (!this.session) throw this.error("invalid_session", "连接会话响应无效。");
          // 仅序列化白名单，防止未来服务字段或原始入口意外混入浏览器存储。
          const {schema_version, origin, instance_id, expires_at, session_token} = this.session;
          this.session = {schema_version, origin, instance_id, expires_at, session_token};
          try { env.storage().setItem(STORAGE_KEY, JSON.stringify(this.session)); }
          catch (_) { this.storageAvailable = false; }
        } else {
          let saved;
          try { saved = JSON.parse(env.storage().getItem(STORAGE_KEY) || "null"); }
          catch (_) { this.storageAvailable = false; }
          this.session = sessionContract(saved, env.origin);
          if (!this.session) throw this.error("authentication", "连接凭据缺失或已过期，当前平台与项目目标已保留。");
        }
        this.api.token = this.session.session_token;
        const health = await this.api.request("/api/health");
        if (health.protocol_version !== 2 || health.instance_id !== this.session.instance_id) throw this.error("instance_changed", "配置服务实例已变化或协议不匹配。");
        this.ready = true;
        return this.initial;
      } catch (error) { this.clear(); throw error; }
    }
    authorize() {
      if (this.ready && this.session?.expires_at > Date.now()) return;
      this.clear(); throw this.error("authentication", "连接凭据缺失或已过期，禁止保存；当前平台与项目目标已保留。");
    }
  }
  const exports = {Connection, navigation, sessionContract, STORAGE_KEY, HISTORY_KEY, REOPEN};
  if (typeof module !== "undefined" && module.exports) module.exports = exports;
  else globalThis.ConsoleConnection = exports;
})();
