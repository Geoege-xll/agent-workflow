/* 父工作台只负责登记路由、会话握手和跨file消息；不跨文档读取DOM。
 * 所有页面URL来自boot3白名单，page/token/source/origin缺一即拒绝。 */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id), preview = $("prototype-preview"), navigation = $("prototype-pages");
  const slots = document.querySelectorAll("script#prototype-review-data");
  const boot = slots.length === 1 && slots[0].type === "application/json" ? window.PrototypeReviewState?.parseStartup(slots[0].textContent) : null;
  function fail(message) { preview?.removeAttribute("src"); if (preview) preview.hidden = true; $("prototype-empty").hidden = false; $("prototype-empty").textContent = message; }
  if (!boot?.context || window.parent !== window || document.querySelectorAll("iframe,frame,frameset").length !== 1 || preview.hasAttribute("srcdoc")
    || document.querySelectorAll("nav#prototype-pages").length !== 1) { fail(boot?.error || "请独立打开prepare生成的评审包。"); return; }
  const model = window.PrototypeReviewState.create(boot), state = model.state, entries = new Map(boot.pages.map((entry) => [entry.path, entry]));
  const targetOrigin = location.protocol === "file:" ? "*" : location.origin, expectedOrigin = location.protocol === "file:" ? "null" : location.origin;
  let current = null, token = "", ready = false, readyWaiters = [], navigationVersion = 0, views = null, presenting = false;
  const requests = new Map();
  const announce = (message) => { $("review-status").textContent = message; };
  function send(action, payload = {}) {
    if (!ready || !current) return false;
    preview.contentWindow.postMessage({ type: "prototype-review:review", version: 3, page: current.path, token, action, ...payload }, targetOrigin); return true;
  }
  const camera = window.PrototypeReviewCamera.create({ viewport: $("canvas-viewport"), world: $("canvas-world"),
    read: () => state.cameras[state.page], write: (cam) => model.setCamera(state.page, cam),
    topInset: () => document.querySelector(".canvas-floating-controls").offsetHeight + 28,
    onApply: (cam) => { $("canvas-zoom-reset").textContent = `${Math.round(cam.k * 100)}%`; } });
  function present() {
    if (presenting) return;
    presenting = true;
    send("present", { items: state.items, anchors: state.anchors, showItems: state.showItems, showAnchors: state.showAnchors,
      activeAnchor: views?.activeAnchor || null, activeItem: views?.activeItem || null, cameraScale: state.cameras[state.page]?.k || 1 });
    presenting = false;
  }
  function randomToken() { const bytes = new Uint8Array(16); crypto.getRandomValues(bytes); return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join(""); }
  function setHash(entry, replace = false) {
    const hash = `#page=${encodeURIComponent(entry.name)}`;
    if (location.hash === hash) return;
    if (replace) { try { const url = new URL(location.href); url.hash = hash; history.replaceState(null, "", url); return; } catch { /* file宿主限制History时保留同页hash后备。 */ } }
    location.hash = hash;
  }
  function readHash() { const params = new URLSearchParams(location.hash.slice(1)); return params.getAll("page").length === 1 ? boot.pages.find((entry) => entry.name === params.get("page")) : null; }
  function navigate(path, options = {}) {
    const entry = entries.get(path); if (!entry) return Promise.reject(Error("页面未登记，当前稿件保持不变。"));
    if (current === entry) {
      if (options.hash !== false) setHash(entry, options.replace);
      if (ready) return Promise.resolve();
      // 同页hashchange只能等待既有握手，不能再次重载iframe并使原token无限失效。
      return new Promise((resolve, reject) => { const waiter = { resolve, reject, timer: setTimeout(() => { readyWaiters = readyWaiters.filter((item) => item !== waiter); reject(Error("当前页面握手超时。")); }, 5000) }; readyWaiters.push(waiter); });
    }
    // 切换使旧会话立即失效；挂起请求拒绝而不是把迟到响应送给新页面。
    for (const [, request] of requests) { clearTimeout(request.timer); request.reject(Error("页面已切换，请重试；输入保留。")); } requests.clear();
    readyWaiters.forEach((waiter) => { clearTimeout(waiter.timer); waiter.reject(Error("页面已切换。")); }); readyWaiters = [];
    current = entry; token = randomToken(); ready = false; const version = ++navigationVersion;
    model.setPage(path); $("current-page-title").textContent = entry.label; document.title = `${entry.label} · 原型评审工作台`;
    for (const link of navigation.querySelectorAll("a")) {
      if (link.dataset.page === path) { link.setAttribute("aria-current", "page"); for (let parent = link.parentElement; parent && parent !== navigation; parent = parent.parentElement) if (parent.tagName === "DETAILS") parent.open = true; }
      else link.removeAttribute("aria-current");
    }
    $("prototype-empty").hidden = true; preview.hidden = false; preview.setAttribute("title", entry.label); preview.setAttribute("aria-busy", "true");
    preview.src = entry.url; if (options.hash !== false) setHash(entry, options.replace);
    announce(`正在载入：${entry.label}`);
    return new Promise((resolve, reject) => { const waiter = { version, resolve, reject, timer: setTimeout(() => { readyWaiters = readyWaiters.filter((item) => item !== waiter); reject(Error("设计页通信超时，输入仍保留；请重新打开当前页面。")); }, 5000) }; readyWaiters.push(waiter); });
  }
  function request(action, payload = {}) {
    return new Promise((resolve, reject) => {
      const id = crypto.randomUUID(), timer = setTimeout(() => { requests.delete(id); reject(Error("设计页没有响应，输入仍保留，请重试。")); }, 4000);
      requests.set(id, { resolve, reject, timer, page: current?.path });
      if (!send(action, { ...payload, request: id })) { clearTimeout(timer); requests.delete(id); reject(Error("当前设计页尚未就绪。")); }
    });
  }
  async function locate(target) {
    if (target.scope === "global") { announce("已定位本轮整体意见。"); return; }
    await navigate(target.page);
    if (target.scope === "page") { announce("已定位页面整改，当前缩放保持不变。"); return; }
    const result = await request("locate", { target });
    if (!result.ok) throw Error("原目标当前无法定位，输入和引用保留；请显示原状态后重试。");
    camera.focus(result.bounds);
  }
  async function verifySources(targets) {
    // 完成交还前实际逐页向child重查源目标；父壳不从缓存目录或局部文字推断来源。
    const previous = state.page, selection = state.selection;
    const byPage = new Map();
    for (const target of targets) if (target?.scope === "node") { if (!byPage.has(target.page)) byPage.set(target.page, []); byPage.get(target.page).push(target); }
    try {
      for (const [page, values] of byPage) {
        await navigate(page, { hash: false }); const result = await request("verify", { targets: values });
        if (!Array.isArray(result.results) || result.results.length !== values.length || result.results.some((ok) => ok !== true)) throw Error("部分目标来源已失效，全部输入保留；请显式重新选择或撤回对应条目。");
      }
    } finally { await navigate(previous, { hash: false }); if (selection) model.select(selection); }
  }
  // 固定导航分组只投影label与open，绝不执行旧业务index的HTML或脚本。
  navigation.replaceChildren(); let previousGroups = [], containers = [navigation];
  for (const entry of boot.pages) {
    let shared = 0;
    while (shared < previousGroups.length && shared < entry.groups.length && previousGroups[shared].label === entry.groups[shared].label && previousGroups[shared].open === entry.groups[shared].open) shared++;
    containers = containers.slice(0, shared + 1);
    for (const group of entry.groups.slice(shared)) { const details = document.createElement("details"), summary = document.createElement("summary"); summary.textContent = group.label; details.open = group.open; details.append(summary); containers.at(-1).append(details); containers.push(details); }
    previousGroups = entry.groups;
    const link = document.createElement("a"), label = document.createElement("strong"); link.className = "review-page"; link.href = `#page=${encodeURIComponent(entry.name)}`; link.dataset.page = entry.path; label.textContent = entry.label; link.append(label); containers.at(-1).append(link);
    link.addEventListener("click", (event) => { if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); $("navigation-drawer").close(); navigate(entry.path).catch((error) => announce(error.message)); });
  }
  preview.addEventListener("load", () => {
    if (!current) return;
    // 业务脚本或浏览器可独立触发iframe重载。每次load都撤销旧ready、目录和token，
    // 不让未认证的新文档继承前一页权限；真正的bridge3重新握手后才恢复编辑。
    ready = false; token = randomToken(); preview.setAttribute("aria-busy", "true"); model.clearCatalog(current.path); views?.catalog();
    for (const [, pending] of requests) { clearTimeout(pending.timer); pending.reject(Error("设计页已重新载入，输入保留，请重试。")); } requests.clear();
    announce("设计页已载入，正在重新确认来源通信……");
    // file://只能使用*投递；接收端还严格核真实window身份、null来源、page与随机会话。
    preview.contentWindow.postMessage({ type: "prototype-review:connect", version: 3, page: current.path, token, mode: state.mode }, targetOrigin);
  });
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!current || event.source !== preview.contentWindow || event.origin !== expectedOrigin || !data || typeof data !== "object" || Array.isArray(data)
      || data.version !== 3 || data.page !== current.path || data.token !== token || !entries.has(data.page)) return;
    if (data.type === "prototype-review:ready") {
      ready = true; preview.setAttribute("aria-busy", "false");
      if (!state.cameras[state.page]) camera.fit(); else camera.applyCam();
      send("mode", { mode: state.mode }); present();
      for (const waiter of readyWaiters) { clearTimeout(waiter.timer); waiter.resolve(); } readyWaiters = []; announce("浏览模式保留稿件业务交互；切到批注后点选元素。"); return;
    }
    if (data.type === "prototype-review:catalog") {
      if (model.setCatalog(current.path, data.nodes)) { views?.catalog(); if (data.error) announce(String(data.error).slice(0, 4000)); } return;
    }
    if (data.type === "prototype-review:contract") { views?.contract(data.sections); return; }
    if (!ready) return;
    if (["prototype-review:located", "prototype-review:verified"].includes(data.type)) {
      const pending = requests.get(data.request); if (!pending || pending.page !== current.path) return;
      clearTimeout(pending.timer); requests.delete(data.request); pending.resolve(data); return;
    }
    if (data.type === "prototype-review:selected") {
      const record = model.catalog().find((entry) => entry.key === data.key); if (!record) return;
      model.select(record, data.explicitParent === true); views?.selected(data.bounds); return;
    }
    if (data.type === "prototype-review:record" && ["anchor", "item"].includes(data.kind) && typeof data.id === "string") { views?.selectRecord(data.kind, data.id); present(); return; }
    if (data.type === "prototype-review:gesture") {
      const cam = state.cameras[state.page]; if (!cam) return;
      if (data.gesture === "zoom" && [data.factor, data.x, data.y].every(Number.isFinite) && data.factor >= .01 && data.factor <= 100) camera.zoom(data.factor, cam.x + data.x * cam.k, cam.y + data.y * cam.k);
      if (data.gesture === "pan" && [data.dx, data.dy].every(Number.isFinite) && Math.abs(data.dx) < 10000 && Math.abs(data.dy) < 10000) camera.move(data.dx * cam.k, data.dy * cam.k); return;
    }
    if (data.type === "prototype-review:intent" && data.intent === "navigate" && typeof data.target === "string") {
      const entry = boot.pages.find((item) => item.name === data.target);
      if (entry) navigate(entry.path).catch((error) => announce(error.message)); else announce("目标没有登记为本轮设计页，当前页面保持不变。");
    }
  });
  views = window.PrototypeFeedback.create({ model, send, locate, verifySources, camera, announce, present });
  model.subscribe(() => { camera.applyCam(); present(); });
  window.addEventListener("hashchange", () => {
    const latest = window.PrototypeReviewState.parseStartup(slots[0].textContent);
    if (!latest.context || latest.rawReview !== boot.rawReview || new URLSearchParams(location.hash.slice(1)).has("review")) { model.block(); announce("本轮绑定已改变，输入保留，不能继续完成或交还。"); return; }
    const entry = readHash() || boot.pages[0]; navigate(entry.path, { replace: true }).catch((error) => announce(error.message));
  });
  $("workspace-requirement-markdown").href = `project/${boot.context.plan_source}`;
  navigate((readHash() || boot.pages[0]).path, { replace: true }).catch((error) => announce(error.message));
})();
