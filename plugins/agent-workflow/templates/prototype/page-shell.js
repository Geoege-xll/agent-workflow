(() => {
  "use strict";

  const back = document.getElementById("prototype-back-index");
  if (!back) return;
  const name = window.location.pathname.split("/").pop();
  if (!/^[a-z0-9][a-z0-9-]*\.html$/.test(name) || name === "index.html") return;
  // 独立打开也能恢复本页登记项；index 仍查登记表，未知页名不会变成任意路径。
  back.setAttribute("href", `index.html#page=${encodeURIComponent(name)}`);
  if (window.parent === window) return;

  let session = "";
  const toggle = document.getElementById("prototype-page-sidebar-toggle");
  const toggleLabel = document.getElementById("prototype-page-sidebar-toggle-label");
  const syncSidebar = (expanded) => {
    if (!toggle || !toggleLabel) return;
    toggle.hidden = false;
    toggle.setAttribute("aria-expanded", String(expanded));
    toggleLabel.textContent = expanded ? "收起侧栏" : "展开侧栏";
  };
  const targetOrigin = window.location.protocol === "file:" ? "*" : window.location.origin;
  const expectedOrigin = window.location.protocol === "file:" ? "null" : window.location.origin;
  const sendIntent = (intent, target) => {
    window.parent.postMessage({ type: "prototype-workspace:intent", version: 1, page: name, token: session, intent, ...(target ? { target } : {}) }, targetOrigin);
  };
  window.addEventListener("message", (event) => {
    const data = event.data;
    // 只接受真实父窗口为本页建立的会话；不凭 origin=null 或消息名称认定可信。
    if (event.source !== window.parent || event.origin !== expectedOrigin || !data || typeof data !== "object"
        || data.version !== 1 || data.page !== name) return;
    if (data.type === "prototype-workspace:state") {
      if (session && data.token === session && typeof data.sidebarExpanded === "boolean") syncSidebar(data.sidebarExpanded);
      return;
    }
    if (data.type !== "prototype-workspace:connect" || typeof data.token !== "string"
        || !/^[a-f0-9]{32}$/.test(data.token) || typeof data.sidebarExpanded !== "boolean") return;
    session = data.token;
    document.body.classList.add("prototype-embedded");
    syncSidebar(data.sidebarExpanded);
    window.parent.postMessage({ type: "prototype-workspace:ready", version: 1, page: name, token: session, supportsSidebarToggle: Boolean(toggle && toggleLabel) }, targetOrigin);
    if (data.focusHeading === true) document.getElementById("prototype-page-title")?.focus();
  });
  back.addEventListener("click", (event) => {
    if (!session || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    sendIntent("reveal-navigation");
  });
  toggle?.addEventListener("click", () => { if (session) sendIntent("toggle-sidebar"); });
  document.addEventListener("click", (event) => {
    if (!session || event.defaultPrevented || event.button !== 0) return;
    const link = event.target.closest?.("a[href]");
    if (!link || link === back) return;
    const href = link.getAttribute("href");
    if (href.startsWith("#")) return; // 同页状态保留原生锚点，不拆工作区页面。
    // 正式需求对由静态边界校验，独立打开，不能替换受控 iframe。
    const kind = link.getAttribute("data-prototype-document");
    if ((kind === "html" || kind === "markdown")
        && link.closest("nav.prototype-requirement-links") && link.getAttribute("target") === "_blank") return;
    event.preventDefault();
    if (href === "index.html") sendIntent("reveal-navigation");
    else if (/^[a-z0-9][a-z0-9-]*\.html$/.test(href)) sendIntent("navigate", href);
    // 越界、外部和非规范目标没有桥接权限；父控制器另检查目标是否登记。
  });
})();
