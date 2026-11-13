(() => {
  "use strict";

  const back = document.getElementById("prototype-back-index");
  const name = window.location.pathname.split("/").pop();
  if (!/^[a-z0-9][a-z0-9-]*\.html$/.test(name) || name === "index.html") return;
  if (window.parent === window) return;
  // 派生页在body尾注入本桥；源页面可能还保留旧defer桥或重复加载同一v2资源。
  // 只注册一次v2监听，且不依赖返回按钮；v1桥得不到新协议会话，不能抢握手。
  if (window.__prototypeReviewBridgeV2) return;
  window.__prototypeReviewBridgeV2 = true;
  // 新源页不再复制feedback.css。只有prepare注入的真实工具脚本才可从自身
  // 固定目录加载同包反馈样式，不能根据hash、消息或业务链接寻找资源。
  const injectedScript = document.currentScript;
  if (injectedScript?.hasAttribute("data-prototype-review-bridge")) {
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = new URL("feedback.css", injectedScript.src).href;
    document.head.append(stylesheet);
  }

  let session = "";
  let highlighted = null;
  const feedbackButton = document.getElementById("prototype-page-feedback");
  const stableId = (id) => typeof id === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,127}$/.test(id);
  const unique = (id) => {
    // 不拼接用户selector；从实际DOM ID列表精确相等查找，重复ID（包括外壳）一律拒绝。
    const matches = Array.from(document.querySelectorAll("[id]")).filter((node) => node.getAttribute("id") === id);
    return matches.length === 1 ? matches[0] : null;
  };
  function catalog() {
    const roots = document.querySelectorAll("[data-prototype-page-content]");
    if (roots.length !== 1) return [];
    const root = roots[0];
    const mappings = Array.from(document.querySelectorAll("[data-contract-for]"));
    return Array.from(root.querySelectorAll("[id]")).filter((node) => stableId(node.getAttribute("id")) && unique(node.getAttribute("id")) === node).map((node) => {
      const id = node.getAttribute("id");
      const matches = mappings.filter((mapping) => mapping.getAttribute("data-contract-for") === id);
      const mapping = matches.length === 1 ? matches[0] : null;
      const mappingId = mapping?.getAttribute("id");
      // 来源只来自匹配目标的唯一交互条目，不猜测API，也不读取href或发送接口请求。
      const refs = mapping ? [mapping, ...mapping.querySelectorAll("[data-interface-ref]")].map((entry) => entry.getAttribute("data-interface-ref")).filter((value) => typeof value === "string" && value.trim()) : [];
      return { id, text: node.textContent.trim(), interaction_id: stableId(mappingId) && unique(mappingId) === mapping ? mappingId : "",
        interaction_text: mapping?.textContent.trim() || "", interface_refs: [...new Set(refs)] };
    });
  }
  const sendCatalog = () => {
    const nodes = catalog();
    // 不静默截断节点/文字/接口；超限节点仍可浏览，反馈目录显式停止，避免导出冒充完整摘录。
    const valid = nodes.length <= 512 && nodes.every((node) => Array.from(node.text).length <= 4000 && Array.from(node.interaction_text).length <= 4000
      && node.interface_refs.length <= 32 && node.interface_refs.every((ref) => Array.from(ref).length <= 512));
    window.parent.postMessage({ type: "prototype-review:catalog", version: 2, page: name, token: session, nodes: valid ? nodes : [], error: valid ? "" : "节点文字或引用超过反馈限额。" }, targetOrigin);
  };
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
    window.parent.postMessage({ type: "prototype-review:intent", version: 2, page: name, token: session, intent, ...(target ? { target } : {}) }, targetOrigin);
  };
  window.addEventListener("message", (event) => {
    const data = event.data;
    // 只接受真实父窗口为本页建立的会话；不凭 origin=null 或消息名称认定可信。
    if (event.source !== window.parent || event.origin !== expectedOrigin || !data || typeof data !== "object"
        || data.version !== 2 || data.page !== name) return;
    if (data.type === "prototype-review:review") {
      if (!session || data.token !== session) return;
      if (data.action === "refresh") { sendCatalog(); return; }
      if (data.action !== "locate" || !stableId(data.target)) return;
      const node = unique(data.target);
      const roots = document.querySelectorAll("[data-prototype-page-content]");
      const ok = roots.length === 1 && node && roots[0].contains(node) && node !== roots[0]
        && (!node.getClientRects || node.getClientRects().length > 0);
      if (ok) {
        if (highlighted) highlighted.removeAttribute("data-prototype-feedback-highlight");
        highlighted = node; node.setAttribute("data-prototype-feedback-highlight", "");
        node.scrollIntoView({ block: "center" });
        // 非交互状态节点只临时添加tabindex，失焦后恢复原状，保留产品原有焦点协议。
        if (!node.hasAttribute("tabindex")) {
          node.setAttribute("tabindex", "-1");
          node.addEventListener("blur", () => node.removeAttribute("tabindex"), { once: true });
        }
        node.focus({ preventScroll: true });
      }
      window.parent.postMessage({ type: "prototype-review:located", version: 2, page: name, token: session, target: data.target, ok: Boolean(ok) }, targetOrigin);
      return;
    }
    if (data.type === "prototype-review:state") {
      if (session && data.token === session && typeof data.sidebarExpanded === "boolean") syncSidebar(data.sidebarExpanded);
      return;
    }
    if (data.type !== "prototype-review:connect" || typeof data.token !== "string"
        || !/^[a-f0-9]{32}$/.test(data.token) || typeof data.sidebarExpanded !== "boolean") return;
    if (session === data.token) return; // 同一握手重发不重复发目录或移动焦点。
    session = data.token;
    document.body.classList.add("prototype-embedded");
    syncSidebar(data.sidebarExpanded);
    if (feedbackButton) feedbackButton.hidden = false;
    window.parent.postMessage({ type: "prototype-review:ready", version: 2, page: name, token: session, supportsSidebarToggle: Boolean(toggle && toggleLabel) }, targetOrigin);
    sendCatalog();
    if (data.focusHeading === true) document.getElementById("prototype-page-title")?.focus();
  });
  feedbackButton?.addEventListener("click", () => { if (session) sendIntent("open-feedback"); });
  back?.addEventListener("click", (event) => {
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
