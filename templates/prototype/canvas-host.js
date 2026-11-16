/* 两种网页共用的画布承载器：只管理登记页、隔离握手、局部几何与相机。
 * 不读取iframe DOM，不请求控制API；来源内容、整改状态分别由原稿和模型唯一持有。 */
(() => {
  "use strict";
  function create({ boot, model, announce, onNavigate = () => {}, reviewing = false }) {
    const $ = (id) => document.getElementById(id), preview = $("prototype-preview"), viewport = $("canvas-viewport");
    const entries = new Map(boot.pages.map((entry) => [entry.path, entry]));
    let current = null, token = "", ready = false, catalogReady = false, views = null, marks = [], closed = false;
    let waiters = [], pinnedOrigin = null, activationEpoch = 0;
    const requests = new Map(), layer = document.createElement("div"); layer.className = "live-overlays"; viewport.append(layer);
    const camera = window.PrototypeReviewCamera.create({ viewport, world: $("canvas-world"), read: () => model.state.cameras[model.state.page],
      write: (cam) => model.setCamera(model.state.page, cam), topInset: () => $("canvas-zoom-tools").offsetHeight + 40,
      onApply: (cam) => { $("canvas-zoom-reset").textContent = `${Math.round(cam.k * 100)}%`; render(); } });
    function send(action, body = {}) {
      if (!ready || closed) return false;
      preview.contentWindow.postMessage({ type: "prototype-review:review", version: 5, page: current.path, token, action, ...body }, "*"); return true;
    }
    function present() { const state = model.state; send("present", { items: reviewing ? state.items : [], anchors: reviewing ? state.anchors : [], showItems: state.showItems,
      showAnchors: state.showAnchors, activeAnchor: state.activeAnchor, activeItem: state.activeItem, cameraScale: state.cameras[state.page]?.k || 1 }); }
    function settle() { if (ready && catalogReady) { waiters.forEach((waiter) => { clearTimeout(waiter.timer); waiter.resolve(); }); waiters = []; } }
    function rejectPending(message) {
      for (const pending of [...waiters, ...requests.values()]) { clearTimeout(pending.timer); pending.reject(Error(message)); }
      waiters = []; requests.clear();
    }
    function waitReady() { if (ready && catalogReady) return Promise.resolve(); return new Promise((resolve, reject) => {
      const waiter = { resolve, reject, timer: setTimeout(() => { waiters = waiters.filter((value) => value !== waiter); reject(Error("设计页通信超时，输入保留，请重新打开本轮入口。")); }, 6000) }; waiters.push(waiter);
    }); }
    function navigate(path) {
      const entry = entries.get(path); if (!entry) return Promise.reject(Error("未登记的页面不能载入。"));
      if (entry === current) return waitReady();
      rejectPending("页面已切换，输入保留，请重试。"); current = entry; ready = false; catalogReady = false; pinnedOrigin = null; marks = []; render();
      token = new URL(entry.url, location.origin).hash.slice("#bridge=".length);
      model.setPage(path); $("current-page-title").textContent = entry.label; document.title = `${entry.label} · ${reviewing ? "原型评审" : "原型交付"}`;
      preview.title = entry.label; preview.hidden = false; preview.setAttribute("aria-busy", "true"); $("prototype-empty").hidden = true;
      preview.src = entry.url; onNavigate(entry); return waitReady();
    }
    function loaded() {
      if (!current || closed) return;
      ready = false; catalogReady = false; pinnedOrigin = null; marks = []; model.clearCatalog(current.path); views?.catalog?.(); render();
      for (const pending of requests.values()) { clearTimeout(pending.timer); pending.reject(Error("设计页已重载，输入保留。")); } requests.clear();
      // sandbox无allow-same-origin，因此发送必须用*；接收必须联合真实window、null、page和cap内随机token。
      preview.contentWindow.postMessage({ type: "prototype-review:connect", version: 5, page: current.path, token, mode: reviewing ? "annotate" : "browse" }, "*");
    }
    function request(action, body) { return new Promise((resolve, reject) => {
      const id = crypto.randomUUID(), timer = setTimeout(() => { requests.delete(id); reject(Error("设计页没有响应，输入保留。")); }, 5000);
      requests.set(id, { resolve, reject, timer }); if (!send(action, { ...body, request: id })) { clearTimeout(timer); requests.delete(id); reject(Error("设计页尚未就绪。")); }
    }); }
    function validBounds(value) { return value && [value.x, value.y, value.w, value.h].every(Number.isFinite)
      && Math.abs(value.x) < 1e7 && Math.abs(value.y) < 1e7 && value.w >= 0 && value.h >= 0 && value.w < 1e7 && value.h < 1e7; }
    async function activateMarker(kind, id) {
      const epoch = ++activationEpoch;
      const entry = (kind === "anchor" ? model.state.anchors : model.state.items).find((value) => value.id === id);
      if (!entry || entry.target?.scope !== "node" || entry.target.page !== current?.path) throw Error("该编号已不属于当前可见页面，意见保留。");
      // 父层编号只有展示几何，不是目标确认凭据。先让认证子页真实resolve/choose，
      // 再激活记录；刷新selection为空或原选另一节点时，浮条必须与编号指向同一来源。
      await locate(entry.target);
      if (closed || epoch !== activationEpoch) return;
      if (model.state.blocked) throw Error("原稿已变化，意见保留，请重新开启评审后核对定位。");
      if (!model.state.selection?.target || model.targetKey(model.state.selection.target) !== model.targetKey(entry.target)) throw Error("编号目标当前无法确认，意见与原输入保留。");
      views?.selectRecord?.(kind, id);
    }
    function render() {
      layer.replaceChildren(); const cam = model.state.cameras[model.state.page]; if (!cam || !reviewing) return;
      for (const mark of marks) {
        const r = mark.bounds, outline = document.createElement("div"); outline.className = `live-outline ${mark.kind} ${["modify", "add", "delete"].includes(mark.operation) ? mark.operation : ""}`;
        Object.assign(outline.style, { left: `${cam.x + r.x * cam.k}px`, top: `${cam.y + r.y * cam.k}px`, width: `${r.w * cam.k}px`, height: `${r.h * cam.k}px` });
        if (mark.kind !== "anchor" && mark.operation !== "add") layer.append(outline);
        if (!["anchor", "item"].includes(mark.kind)) continue;
        const button = document.createElement("button"); button.type = "button"; button.className = `live-marker ${mark.kind} ${["modify", "add", "delete"].includes(mark.operation) ? mark.operation : ""}`;
        button.textContent = `${mark.kind === "anchor" ? "A" : ""}${String(mark.number).padStart(2, "0")}`;
        button.setAttribute("aria-label", `${mark.kind === "anchor" ? "定位标记" : "整改"} ${button.textContent}`);
        Object.assign(button.style, { left: `${Math.max(0, cam.x + r.x * cam.k + mark.offset * 46)}px`, top: `${Math.max(0, cam.y + r.y * cam.k - 28)}px` });
        button.addEventListener("click", () => { activateMarker(mark.kind, mark.id).catch((error) => announce(error.message)); }); layer.append(button);
      }
    }
    function message(event) {
      const data = event.data;
      if (closed || !current || event.source !== preview.contentWindow || event.origin !== "null" || !data || typeof data !== "object" || Array.isArray(data)
        || data.version !== 5 || data.page !== current.path || data.token !== token) return;
      // 支持Origin API时额外固定真实opaque origin；旧浏览器由event.source与随机token提供等效隔离。
      if ("Origin" in globalThis) { try { const origin = Origin.from(event); if (!origin.opaque || (pinnedOrigin && !origin.isSameOrigin(pinnedOrigin))) return; pinnedOrigin ||= origin; } catch { return; } }
      if (data.type === "prototype-review:ready") { ready = true; preview.setAttribute("aria-busy", "false"); if (!model.state.cameras[current.path]) camera.fit(); else camera.applyCam(); present(); settle(); return; }
      if (data.type === "prototype-review:catalog") { if (model.setCatalog(current.path, data.nodes)) { catalogReady = true; views?.catalog?.(); settle(); if (typeof data.error === "string" && data.error) announce(data.error.slice(0, 4000)); } return; }
      if (data.type === "prototype-review:contract") { views?.contract?.(data.sections); return; }
      if (!ready) return;
      if (["prototype-review:located", "prototype-review:verified"].includes(data.type)) { const pending = requests.get(data.request); if (pending) { clearTimeout(pending.timer); requests.delete(data.request); pending.resolve(data); } return; }
      if (data.type === "prototype-review:selected" && !model.state.blocked) { const record = model.catalog().find((entry) => entry.key === data.key); if (record) { model.select(record, data.explicitParent === true); views?.selected?.(data.bounds); } return; }
      if (data.type === "prototype-review:geometry" && Array.isArray(data.marks) && data.marks.length <= 514
        && data.marks.every((mark) => ["selection", "hover", "anchor", "item"].includes(mark.kind) && validBounds(mark.bounds)
          && (!["anchor", "item"].includes(mark.kind) || (Number.isSafeInteger(mark.number) && mark.number > 0 && Number.isSafeInteger(mark.offset) && mark.offset >= 0 && mark.offset <= 512 && typeof mark.id === "string")))) { marks = data.marks; render(); return; }
      if (data.type === "prototype-review:gesture") { const cam = model.state.cameras[current.path]; if (!cam) return;
        if (data.gesture === "zoom" && [data.factor, data.x, data.y].every(Number.isFinite) && data.factor >= .01 && data.factor <= 100) camera.zoom(data.factor, cam.x + data.x * cam.k, cam.y + data.y * cam.k);
        if (data.gesture === "pan" && [data.dx, data.dy].every(Number.isFinite) && Math.abs(data.dx) < 10000 && Math.abs(data.dy) < 10000) camera.move(data.dx * cam.k, data.dy * cam.k); return; }
      if (data.type === "prototype-review:intent" && data.intent === "navigate" && typeof data.target === "string") {
        const entry = boot.pages.find((item) => item.name === data.target); if (entry) navigate(entry.path).catch((error) => announce(error.message)); else announce("目标未登记为本轮页面，当前稿件保持。");
      }
    }
    async function locate(target) { if (model.state.blocked) throw Error("原稿已变化，意见保留，请重新开启评审后核对定位。"); if (target.scope === "global") return; await navigate(target.page); if (target.scope !== "node") return;
      const result = await request("locate", { target }); if (model.state.blocked) throw Error("原稿已变化，意见保留，请重新开启评审后核对定位。"); if (!result.ok || !validBounds(result.bounds)) throw Error("原目标当前不可见，输入保留；按住Alt恢复其业务状态后重试。"); camera.focus(result.bounds); }
    async function verifySources(targets) {
      const previous = model.state.page, selected = model.state.selection, grouped = new Map();
      for (const target of targets) if (target?.scope === "node") { if (!grouped.has(target.page)) grouped.set(target.page, []); grouped.get(target.page).push(target); }
      try { for (const [page, values] of grouped) { await navigate(page); const result = await request("verify", { targets: values });
        if (!Array.isArray(result.results) || result.results.length !== values.length || result.results.some((value) => value !== true)) throw Error("部分来源已失效，输入保留，请重新选择或撤回对应意见。"); }
      } finally { await navigate(previous); if (selected) model.select(selected); }
    }
    preview.addEventListener("load", loaded); window.addEventListener("message", message);
    const unsubscribe = model.subscribe(() => { camera.applyCam(); present(); });
    return Object.freeze({ camera, send, present, navigate, locate, verifySources, attachViews(value) { views = value; }, close() { closed = true; rejectPending("画布已关闭。"); unsubscribe(); preview.removeEventListener("load", loaded); window.removeEventListener("message", message); layer.remove(); } });
  }
  window.PrototypeCanvasHost = Object.freeze({ create });
})();
