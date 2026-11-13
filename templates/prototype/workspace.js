(() => {
  "use strict";

  // 导航只由不可变快照内的封闭启动数据投影；业务旧index不在浏览器执行。
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

  let links = [];
  const entries = new Map();
  let current = null;
  let session = "";
  let focusAfterLoad = false;
  let initialized = false;
  let bridgeReady = false;

  // 反馈模块提供封闭启动解析与草稿管理；缺失时入口拒绝加载未知页面。
  const feedback = window.PrototypeFeedback?.create({ send: (action, target) => {
    if (action === "navigate") {
      const entry = entries.get(target);
      if (!entry) return false;
      select(entry, { updateHash: true, focus: false }); return true;
    }
    if (bridgeReady && current) preview.contentWindow.postMessage({ type: "prototype-review:review", version: 2, page: current.name, token: session, action, target }, targetOrigin);
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
  // 被其他文档嵌入的入口不启动承载器，且启动数据必须来自prepare的唯一JSON槽。
  const startup = document.querySelectorAll("script#prototype-review-data");
  fragment = startup.length === 1 && startup[0].getAttribute("type") === "application/json"
    ? window.PrototypeFeedback?.parseStartup(startup[0].textContent) : null;
  if (window.parent !== window || document.querySelectorAll("nav#prototype-pages").length !== 1
      || document.querySelectorAll("iframe, frame, frameset").length !== 1 || preview.hasAttribute("srcdoc")
      || !fragment?.context) {
    failClosed(fragment?.error || "工作区结构或评审数据无效，请独立打开准备好的评审包。");
    return;
  }
  feedback?.bind(fragment);
  navigation.replaceChildren();
  let previousGroups = [], containers = [navigation];
  for (const item of fragment.pages) {
    // 分组沿核心提供的外到内顺序重建，连续相同祖先复用原生details；所有标签
    // 只写textContent，旧index里的HTML/脚本/链接地址没有执行或加载权限。
    let shared = 0;
    while (shared < item.groups.length && shared < previousGroups.length
      && item.groups[shared].label === previousGroups[shared].label && item.groups[shared].open === previousGroups[shared].open) shared++;
    containers = containers.slice(0, shared + 1);
    for (const group of item.groups.slice(shared)) {
      const details = document.createElement("details"), summary = document.createElement("summary");
      summary.textContent = group.label; details.open = group.open; details.append(summary);
      containers.at(-1).append(details); containers.push(details);
    }
    previousGroups = item.groups;
    const link = document.createElement("a"); link.setAttribute("href", item.url); link.textContent = item.label;
    containers.at(-1).append(link);
    const entry = Object.freeze({ ...item, link }); entries.set(item.name, entry);
    link.addEventListener("click", (event) => {
      if (!initialized) { event.preventDefault(); return; }
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); select(entry, { updateHash: true, focus: true });
    });
  }
  links = Array.from(navigation.querySelectorAll("a[href]"));
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
    if (bridgeReady) preview.contentWindow.postMessage({ type: "prototype-review:state", version: 2, page: current.name, token: session, sidebarExpanded: expanded }, targetOrigin);
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
    // hash只有页面选择权；旧review片段或运行中修改启动绑定都只会停用编辑，
    // 不读取路径/context，也不会把原草稿自动归属给另一版本。
    const params = new URLSearchParams(window.location.hash.slice(1));
    const latest = window.PrototypeFeedback?.parseStartup(startup[0].textContent);
    if (params.has("review")) feedback?.bind({ rawReview: "invalid-fragment", context: null, error: "旧评审片段已失效，请重新 prepare。" });
    else if (latest) feedback?.bind(latest);
    return params.getAll("page").length === 1 ? entries.get(params.get("page")) || null : null;
  };
  const writeHash = (entry, replace) => {
    const hash = `#page=${encodeURIComponent(entry.name)}`;
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
    // src唯一写入点只消费已校验的固定快照URL，不从hash、context或消息拼路径。
    preview.setAttribute("src", entry.url);
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
    preview.contentWindow.postMessage({ type: "prototype-review:connect", version: 2, page: current.name, token: session, focusHeading: focusAfterLoad, sidebarExpanded: !sidebar.hidden }, targetOrigin);
    focusAfterLoad = false;
  });
  window.addEventListener("message", (event) => {
    const data = event.data;
    // origin=null 不具身份意义：同时核对真实 WindowProxy、当前登记页和本轮会话。
    if (!current || event.source !== preview.contentWindow || event.origin !== expectedOrigin
        || !data || typeof data !== "object" || data.version !== 2 || data.page !== current.name
        || data.token !== session || !entries.has(data.page)) return;
    if (data.type === "prototype-review:ready") {
      bridgeReady = true;
      toggle.hidden = data.supportsSidebarToggle === true;
      if (bridgeReady) setSidebar(!sidebar.hidden);
      return;
    }
    if (data.type === "prototype-review:catalog") { feedback?.receive(data); return; }
    if (data.type === "prototype-review:located") { feedback?.receive(data); return; }
    if (data.type !== "prototype-review:intent") return;
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
