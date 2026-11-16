/* 本机服务唯一HTTP边界。控制凭据仅限当前实例的context/draft，绝不发给iframe。
 * 每次请求有超时；写请求不重试、不续期，CAS冲突保留调用方的原始输入。 */
(() => {
  "use strict";
  function create(context) {
    const key = `prototype-live-credential:${location.origin}:${context.review_id}`;
    const fragment = new URLSearchParams(location.hash.slice(1));
    let token = "";
    if (fragment.getAll("token").length === 1 && /^[a-f0-9]{32,128}$/.test(fragment.get("token"))) token = fragment.get("token");
    // 无秘密URL的浏览器顶层引导把凭据放在独立JSON槽，必须与startup同一review_id。
    // file分支根本不调用此边界；业务iframe没有此槽，也不会收到控制token。
    if (typeof document !== "undefined") {
      const slots = document.querySelectorAll("script#prototype-browser-connection");
      if (slots.length && (slots.length !== 1 || slots[0].type !== "application/json")) throw Error("评审引导无效，请重新打开交付入口。");
      if (slots.length === 1) {
        try { const value = JSON.parse(slots[0].textContent);
          if (value && Object.keys(value).length === 3 && value.schema_version === 1 && value.review_id === context.review_id && /^[a-f0-9]{32,128}$/.test(value.token)) token = value.token;
          else throw Error("invalid_bootstrap");
        } catch { throw Error("评审引导与当前修订不匹配，请重新打开交付入口。"); }
        slots[0].remove();
      }
    }
    try {
      if (token) sessionStorage.setItem(key, token);
      else token = sessionStorage.getItem(key) || "";
    } catch { /* 禁止存储时当前页仍可使用，刷新必须由受信入口重新打开。 */ }
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    const controllers = new Set(); let closed = false;
    async function request(path, method = "GET", body) {
      if (closed || !/^[a-f0-9]{32,128}$/.test(token)) throw Error("连接凭据不可用，请从本轮交付入口重新打开；输入保留。");
      const controller = new AbortController(); controllers.add(controller);
      const timer = setTimeout(() => controller.abort(), 7000);
      try {
        const response = await fetch(path, { method, signal: controller.signal, cache: "no-store", credentials: "omit", redirect: "error",
          headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
          ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
        const value = await response.json();
        if (!response.ok) {
          const code = response.status === 409 && value?.status === "source_changed" && value.context && typeof value.page === "string" ? "source_changed" : value?.error?.code;
          const error = Error(code === "source_changed" ? "原稿已变化；本轮旧稿与意见保留，请从交付入口重新开启评审。"
            : code === "draft_conflict" ? "另一评审窗口已保存新草稿；当前输入保留，未覆盖另一窗口。请先交还或保留当前输入后刷新。"
              : response.status === 401 || response.status === 403 ? "连接已失效，请从交付入口重新打开；输入保留。" : "本地服务请求失败，当前输入保留。");
          error.code = typeof code === "string" ? code : "request_failed"; throw error;
        }
        return value;
      } catch (error) {
        if (error.name === "AbortError") throw Error("本地服务响应超时，输入仍在当前页；写入不会自动重放。");
        if (error.code) throw error;
        throw Error("无法连接本轮本地服务，请从交付入口重新打开；当前输入保留，写入不会自动重放。", { cause: error });
      } finally { clearTimeout(timer); controllers.delete(controller); }
    }
    function draftResponse(value) {
      if (!value || !Number.isSafeInteger(value.revision) || value.revision < 0 || !Object.hasOwn(value, "draft")
        || Object.keys(value).length !== 2 || (value.draft !== null && (typeof value.draft !== "object" || Array.isArray(value.draft)))) throw Error("草稿响应损坏，输入保留。");
      return value;
    }
    return Object.freeze({
      async context(name) { const value = await request(`/api/context?name=${encodeURIComponent(name)}`);
        if (!value || Object.keys(value).length !== 3 || !["ready", "source_changed"].includes(value.status) || !value.context || typeof value.page !== "string") throw Error("来源状态响应损坏。"); return value; },
      async readDraft() { return draftResponse(await request("/api/draft")); },
      async saveDraft(revision, draft) { return draftResponse(await request("/api/draft", "PUT", { revision, draft })); },
      reviewURL(name) { return `${location.origin}/review/${encodeURIComponent(name)}#token=${token}`; },
      close() { closed = true; for (const controller of controllers) controller.abort(); controllers.clear(); token = ""; },
    });
  }
  window.PrototypeLiveConnection = Object.freeze({ create });
})();
