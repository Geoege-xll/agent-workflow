(() => {
  "use strict";

  // 登记只读取 index 的普通链接；Map 是该 DOM 的派生索引，不维护第二份页面清单。
  const navigation = document.getElementById("prototype-pages");
  const preview = document.getElementById("prototype-preview");
  const layout = document.getElementById("prototype-workspace");
  const sidebar = document.getElementById("prototype-sidebar");
  const toggle = document.getElementById("prototype-sidebar-toggle");
  const toggleLabel = document.getElementById("prototype-sidebar-toggle-label");
  const empty = document.getElementById("prototype-empty");
  const status = document.getElementById("prototype-workspace-status");
  const count = document.getElementById("prototype-page-count");
  if (!navigation || !preview || !layout || !sidebar || !toggle || !toggleLabel || !empty || !status || !count) return;

  const links = Array.from(navigation.querySelectorAll("a[href]"));
  const entries = new Map();
  const canonicalPage = /^[a-z0-9][a-z0-9-]*\.html$/;
  let current = null;
  let session = "";
  let focusAfterLoad = false;
  let initialized = false;
  let bridgeReady = false;

  // 反馈模块可渐进缺席；普通浏览和现有消息桥始终由工作区独立维护。
  const feedback = window.PrototypeFeedback?.create({ send: (action, target) => {
    if (action === "navigate") {
      const entry = entries.get(target);
      if (!entry) return false;
      select(entry, { updateHash: true, focus: false }); return true;
    }
    if (bridgeReady && current) preview.contentWindow.postMessage({ type: "prototype-workspace:review", version: 1, page: current.name, token: session, action, target }, targetOrigin);
  } });
  let fragment = null;
  const announce = (text) => { status.textContent = text; };
  const failClosed = (text) => {
    // 无合法登记或结构被改坏时不猜测路径，也不留下原有 src/srcdoc 继续加载。
    preview.removeAttribute("src");
    preview.removeAttribute("srcdoc");
    preview.hidden = true;
    toggle.hidden = true;
    empty.hidden = false;
    empty.textContent = text;
    announce(text);
  };
  for (const link of links) {
    link.addEventListener("click", (event) => {
      const entry = entries.get(link.getAttribute("href"));
      if (!initialized || !entry || entry.link !== link) { event.preventDefault(); return; }
      // 有效链接保留修饰键独立打开的原生能力；无效登记连这种点击也拒绝。
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      select(entry, { updateHash: true, focus: true });
    });
  }

  // 被其他文档嵌入的 index 不启动承载器，防止旧页面普通返回链接造成递归自嵌套。
  if (window.parent !== window || document.querySelectorAll("nav#prototype-pages").length !== 1
      || document.querySelectorAll("iframe, frame, frameset").length !== 1 || preview.hasAttribute("srcdoc")) {
    failClosed("工作区结构无效，请独立打开原型入口。");
    return;
  }
  for (const link of links) {
    const name = link.getAttribute("href");
    const label = link.textContent.trim();
    if (!canonicalPage.test(name) || name === "index.html" || entries.has(name) || !label) {
      failClosed("页面登记无效，请检查页面导航。");
      return;
    }
    entries.set(name, Object.freeze({ name, label, link }));
  }
  count.textContent = `${entries.size} 页`;
  if (entries.size === 0) { failClosed("暂无原型页面。添加实际页面后，可在此分组浏览。"); return; }

  const groups = Array.from(navigation.querySelectorAll("details"));
  const syncGroup = (group) => {
    const summary = Array.from(group.children).find((child) => child.tagName === "SUMMARY");
    if (summary) summary.setAttribute("aria-expanded", String(group.open));
  };
  for (const group of groups) {
    syncGroup(group);
    group.addEventListener("toggle", () => syncGroup(group));
  }
  const expandCurrentGroups = () => {
    for (let ancestor = current.link.parentElement; ancestor && ancestor !== navigation; ancestor = ancestor.parentElement) {
      if (ancestor.tagName === "DETAILS") { ancestor.open = true; syncGroup(ancestor); }
    }
  };
  const setSidebar = (expanded) => {
    sidebar.hidden = !expanded;
    layout.classList.toggle("is-sidebar-collapsed", !expanded);
    toggle.setAttribute("aria-expanded", String(expanded));
    toggleLabel.textContent = expanded ? "收起侧栏" : "展开侧栏";
    // 页头只是导航桥接消费者，不自行维护一份侧栏状态。
    if (bridgeReady) preview.contentWindow.postMessage({ type: "prototype-workspace:state", version: 1, page: current.name, token: session, sidebarExpanded: expanded }, targetOrigin);
  };
  const revealNavigation = () => {
    setSidebar(true);
    expandCurrentGroups();
    current.link.focus();
    current.link.scrollIntoView({ block: "nearest" });
    announce(`已定位当前页面导航：${current.label}。`);
  };
  const toggleSidebar = () => {
    const expanded = sidebar.hidden;
    setSidebar(expanded);
    // 通过其他输入方式触发收起时，也不把焦点留在已隐藏的侧栏里。
    if (!expanded && sidebar.contains(document.activeElement)) toggle.focus();
    announce(expanded ? "页面侧栏已展开。" : "页面侧栏已收起。");
  };
  toggle.addEventListener("click", toggleSidebar);

  const readHash = () => {
    // page与review各自只允许一个值；page只用于命中登记表，绝不直接作为地址。
    const params = new URLSearchParams(window.location.hash.slice(1));
    fragment = window.PrototypeFeedback?.parseFragment(window.location.hash);
    if (fragment) feedback?.bind(fragment);
    return params.getAll("page").length === 1 ? entries.get(params.get("page")) || null : null;
  };
  const writeHash = (entry, replace) => {
    const rawReview = new URLSearchParams(window.location.hash.slice(1)).getAll("review");
    const hash = `#page=${encodeURIComponent(entry.name)}${rawReview.length === 1 ? `&review=${encodeURIComponent(rawReview[0])}` : ""}`;
    if (window.location.hash === hash) return;
    if (replace) {
      // file:// 仅替换当前文档片段；宿主限制 History API 时退回同页片段导航。
      const url = new URL(window.location.href);
      url.hash = hash;
      try { window.history.replaceState(null, "", url.href); return; }
      catch { /* 下面的片段赋值保留合法选择，不产生文件路径加载。 */ }
    }
    window.location.hash = hash;
  };
  const newSession = () => {
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  };
  function select(entry, { updateHash = false, replaceHash = false, focus = false } = {}) {
    if (current === entry) { if (updateHash) writeHash(entry, replaceHash); return; }
    feedback?.select(entry.name);
    current = entry;
    session = newSession();
    bridgeReady = false;
    focusAfterLoad = focus;
    for (const item of entries.values()) {
      const selected = item === entry;
      if (selected) item.link.setAttribute("aria-current", "page");
      else item.link.removeAttribute("aria-current");
      let marker = item.link.querySelector("[data-prototype-current-marker]");
      if (!marker) {
        marker = document.createElement("span");
        marker.setAttribute("data-prototype-current-marker", "");
        marker.classList.add("workspace-current-marker");
        marker.textContent = "当前";
        item.link.append(marker);
      }
      marker.hidden = !selected;
    }
    expandCurrentGroups();
    empty.hidden = true;
    toggle.hidden = false;
    preview.hidden = false;
    preview.setAttribute("aria-busy", "true");
    preview.setAttribute("title", entry.label);
    // src 唯一写入点仅接受登记项内的规范页名，不执行消息或 hash 提供的地址。
    preview.setAttribute("src", entry.name);
    document.title = `${entry.label} · 原型工作区`;
    announce(`正在载入：${entry.label}。`);
    if (updateHash) writeHash(entry, replaceHash);
  }

  const targetOrigin = window.location.protocol === "file:" ? "*" : window.location.origin;
  const expectedOrigin = window.location.protocol === "file:" ? "null" : window.location.origin;
  preview.addEventListener("load", () => {
    if (!current) return;
    preview.setAttribute("aria-busy", "false");
    announce(`当前预览：${current.label}。`);
    if (focusAfterLoad) preview.focus();
    // 跨 file 文档只通过消息握手，不读取 contentDocument、location 或子页 DOM。
    preview.contentWindow.postMessage({ type: "prototype-workspace:connect", version: 1, page: current.name, token: session, focusHeading: focusAfterLoad, sidebarExpanded: !sidebar.hidden }, targetOrigin);
    focusAfterLoad = false;
  });
  window.addEventListener("message", (event) => {
    const data = event.data;
    // origin=null 不具身份意义：同时核对真实 WindowProxy、当前登记页和本轮会话。
    if (!current || event.source !== preview.contentWindow || event.origin !== expectedOrigin
        || !data || typeof data !== "object" || data.version !== 1 || data.page !== current.name
        || data.token !== session || !entries.has(data.page)) return;
    if (data.type === "prototype-workspace:ready") {
      bridgeReady = data.supportsSidebarToggle === true;
      toggle.hidden = bridgeReady;
      if (bridgeReady) setSidebar(!sidebar.hidden);
      return;
    }
    if (data.type === "prototype-workspace:catalog") { feedback?.receive(data); return; }
    if (data.type === "prototype-workspace:located") { feedback?.receive(data); return; }
    if (data.type !== "prototype-workspace:intent") return;
    if (data.intent === "open-feedback") { feedback?.open(); return; }
    if (data.intent === "reveal-navigation") revealNavigation();
    else if (data.intent === "toggle-sidebar") toggleSidebar();
    else if (data.intent === "navigate") {
      const entry = typeof data.target === "string" ? entries.get(data.target) : null;
      if (entry) select(entry, { updateHash: true, focus: true });
      else announce("目标页面尚未登记，当前预览保持不变。");
    }
  });
  window.addEventListener("hashchange", () => {
    const entry = readHash() || entries.values().next().value;
    select(entry, { updateHash: true, replaceHash: true, focus: true });
  });
  initialized = true;
  setSidebar(true);
  select(readHash() || entries.values().next().value, { updateHash: true, replaceHash: true });
})();
