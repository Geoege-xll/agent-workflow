/* 派生设计页唯一DOM所有者：命中、局部几何、可见目录与覆盖层都留在子文档。
 * 只响应prepare注入的bridge3，独立打开项目源时不改变外观或业务行为。 */
(() => {
  "use strict";
  const injected = document.currentScript;
  if (window.parent === window || injected?.getAttribute("data-prototype-review-bridge") !== "3" || window.__prototypeReviewBridgeV3) return;
  window.__prototypeReviewBridgeV3 = true;
  const expectedOrigin = window.location.protocol === "file:" ? "null" : window.location.origin;
  const targetOrigin = window.location.protocol === "file:" ? "*" : window.location.origin;
  const roots = document.querySelectorAll("[data-prototype-page-content]");
  if (roots.length !== 1) return;
  const root = roots[0], sourceAttr = "data-prototype-review-source";
  let session = "", page = "", mode = "browse", selected = null, overlay = null, hover = null, frame = 0;
  let presentation = { anchors: [], items: [], showAnchors: true, showItems: true, activeAnchor: null, activeItem: null };
  const runtimeKeys = new WeakMap(); let runtimeSequence = 0;
  let nodes = new Map(), pan = null, space = false, panMoved = false;
  const stableId = (value) => typeof value === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,127}$/.test(value);
  const sourceKey = (value) => typeof value === "string" && /^source-[a-f0-9]{64}$/.test(value);
  const exact = (value, keys) => value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
  const excluded = (node) => !node || !root.contains(node) || node.closest("script,style,template,link,meta,noscript,[data-prototype-review-overlay]");
  function visible(node) {
    if (excluded(node) || node.closest("[hidden],[inert]")) return false;
    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  }
  const meaningful = (node) => !excluded(node) && (node === root || node.textContent.trim() || node.matches("img,svg,input,select,textarea,button,a,[role]"));
  const excerpt = (node) => Array.from(((node instanceof HTMLElement ? node.innerText : node.textContent) || node.getAttribute("aria-label") || node.getAttribute("alt") || "").trim()).slice(0, 4000).join("");
  function unique(attribute, value) {
    const matches = Array.from(document.querySelectorAll(`[${attribute}]`)).filter((node) => node.getAttribute(attribute) === value);
    return matches.length === 1 ? matches[0] : null;
  }
  function target(node) {
    const key = node?.getAttribute(sourceAttr);
    // 运行时新增ID也不能冒充源。没有prepare注入的来源键，绝不自动寻找祖先代绑。
    if (!sourceKey(key) || unique(sourceAttr, key) !== node || excluded(node)) return null;
    const id = node.getAttribute("id");
    return { scope: "node", page, locator: stableId(id) && unique("id", id) === node ? { type: "id", id } : { type: "source", key } };
  }
  function resolve(value) {
    if (!exact(value, ["scope", "page", "locator"]) || value.scope !== "node" || value.page !== page) return null;
    let node = null;
    if (exact(value.locator, ["type", "id"]) && value.locator.type === "id" && stableId(value.locator.id)) node = unique("id", value.locator.id);
    if (exact(value.locator, ["type", "key"]) && value.locator.type === "source" && sourceKey(value.locator.key)) node = unique(sourceAttr, value.locator.key);
    return node && target(node) && JSON.stringify(target(node)) === JSON.stringify(value) ? node : null;
  }
  function parentNode(node) {
    if (node === root) return null;
    let parent = node?.parentElement;
    while (parent && root.contains(parent)) { if (meaningful(parent) && visible(parent)) return parent; parent = parent.parentElement; }
    return null;
  }
  function keyFor(node) {
    const source = node.getAttribute(sourceAttr);
    if (sourceKey(source)) return source;
    if (!runtimeKeys.has(node)) runtimeKeys.set(node, `runtime-${++runtimeSequence}`);
    return runtimeKeys.get(node);
  }
  function metadata(node) {
    const mappings = Array.from(document.querySelectorAll("[data-contract-for]")).filter((entry) => entry.getAttribute("data-contract-for") === node.id);
    const mapping = stableId(node.id) && unique("id", node.id) === node && mappings.length === 1 ? mappings[0] : null;
    const interactionId = mapping?.getAttribute("id");
    const refs = mapping ? [mapping, ...mapping.querySelectorAll("[data-interface-ref]")].map((entry) => entry.getAttribute("data-interface-ref")).filter(Boolean) : [];
    const text = excerpt(node);
    return { key: keyFor(node), target: target(node), text,
      label: Array.from(`${node.tagName.toLowerCase()} · ${node.getAttribute("aria-label") || text || node.getAttribute("alt") || "容器"}`).slice(0, 120).join(""),
      has_parent: Boolean(parentNode(node)), req_ids: [...new Set((node.getAttribute("data-req-ids") || "").split(/\s+/).filter(Boolean))],
      interaction_text: mapping ? Array.from(mapping.textContent.trim()).slice(0, 4000).join("") : "",
      interaction_id: stableId(interactionId) && unique("id", interactionId) === mapping ? interactionId : "", interface_refs: [...new Set(refs)] };
  }
  const send = (type, body = {}) => { if (session) window.parent.postMessage({ type: `prototype-review:${type}`, version: 3, page, token: session, ...body }, targetOrigin); };
  function catalog() {
    nodes = new Map();
    for (const node of [root, ...root.querySelectorAll("*")]) if (meaningful(node) && visible(node)) nodes.set(keyFor(node), node);
    const entries = Array.from(nodes.values()).map(metadata);
    send("catalog", { nodes: entries.length <= 4096 ? entries : [], error: entries.length <= 4096 ? "" : "当前可见元素超过4096个，请缩小可见状态。" });
  }
  function bounds(node) { const rect = node.getBoundingClientRect(); return { x: rect.left, y: rect.top, w: rect.width, h: rect.height }; }
  function choose(node, explicitParent = false) {
    if (!node || !meaningful(node) || !visible(node)) return;
    selected = node; catalog(); send("selected", { key: keyFor(node), bounds: bounds(node), explicitParent }); render();
  }
  function rectangle(node, className) {
    const el = document.createElement("div"), r = bounds(node); el.className = className;
    Object.assign(el.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` }); return el;
  }
  function render() {
    if (!overlay) return;
    overlay.replaceChildren();
    if (selected && visible(selected)) overlay.append(rectangle(selected, "pr-selection"));
    if (mode === "annotate" && hover && hover !== selected && visible(hover)) overlay.append(rectangle(hover, "pr-hover"));
    const offsets = new Map();
    function badge(entry, anchor) {
      const node = resolve(entry.target); if (!node || !visible(node)) return;
      const r = bounds(node), key = JSON.stringify(entry.target), offset = offsets.get(key) || 0; offsets.set(key, offset + 1);
      if (!anchor && entry.operation !== "add") overlay.append(rectangle(node, `pr-outline ${entry.operation}`));
      const button = document.createElement("button"); button.type = "button";
      button.className = anchor ? "pr-anchor" : `pr-badge ${entry.operation}`;
      if ((anchor ? presentation.activeAnchor : presentation.activeItem) === entry.id) button.classList.add("is-active");
      button.textContent = `${anchor ? "A" : ""}${String(entry.number).padStart(2, "0")}`;
      button.setAttribute("aria-label", `${anchor ? "定位标记 A" : "整改 "}${String(entry.number).padStart(2, "0")}`);
      Object.assign(button.style, { left: `${Math.max(0, r.x + offset * 46)}px`, top: `${Math.max(0, r.y - 26)}px` });
      button.addEventListener("click", () => { choose(node); send("record", { kind: anchor ? "anchor" : "item", id: entry.id }); }); overlay.append(button);
    }
    if (presentation.showItems) presentation.items.forEach((entry) => badge(entry, false));
    if (presentation.showAnchors) presentation.anchors.forEach((entry) => badge(entry, true));
  }
  function queueRender() { if (frame) return; frame = requestAnimationFrame(() => { frame = 0; render(); }); }
  function embed() {
    document.body.classList.add("prototype-review-embedded");
    // 只在认证派生页隐藏真实画板之外的展示壳。祖先保留DOM与业务监听，以contents解除外层边距。
    let child = root;
    while (child && child !== document.body) {
      for (const sibling of child.parentElement.children) if (sibling !== child && !["SCRIPT", "STYLE", "LINK"].includes(sibling.tagName)) sibling.classList.add("prototype-review-shell-hidden");
      child = child.parentElement; if (child !== document.body) child.classList.add("prototype-review-shell-ancestor");
    }
    overlay = document.createElement("div"); overlay.setAttribute("data-prototype-review-overlay", ""); overlay.className = "pr-overlays"; document.body.append(overlay);
    const stylesheet = document.createElement("link"); stylesheet.rel = "stylesheet"; stylesheet.href = new URL("feedback.css", injected.src).href; document.head.append(stylesheet);
    stylesheet.addEventListener("load", () => { catalog(); render(); });
    const contract = Array.from(document.querySelectorAll("details")).find((el) => el.querySelector("summary")?.textContent.trim() === "Page design and interaction contract");
    const sections = ["purpose", "navigation", "interactions", "states", "exceptions"].map((name) => ({ name, text: Array.from(contract?.querySelectorAll(`[data-contract-section="${name}"]`) || []).map((node) => node.textContent.trim()).join("\n") }));
    send("contract", { sections });
    new MutationObserver((changes) => {
      if (changes.every((change) => overlay.contains(change.target) || change.target === overlay)) return;
      catalog(); queueRender();
    }).observe(root, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["hidden", "class", "style", "id", sourceAttr, "data-req-ids"] });
  }
  window.addEventListener("message", (event) => {
    const data = event.data;
    // null来源仅对固定parent窗口有意义，还必须联合登记page和随机token；任何单项都不授予权限。
    if (event.source !== window.parent || event.origin !== expectedOrigin || !data || data.version !== 3 || typeof data.page !== "string") return;
    if (data.type === "prototype-review:connect") {
      if (session || !/^[a-f0-9]{32}$/.test(data.token) || !window.location.pathname.endsWith(`/${data.page}`)) return;
      page = data.page; session = data.token; mode = data.mode === "annotate" ? "annotate" : "browse";
      embed(); send("ready"); catalog(); return;
    }
    if (!session || data.page !== page || data.token !== session) return;
    if (data.type !== "prototype-review:review") return;
    if (data.action === "refresh") { catalog(); return; }
    if (data.action === "mode" && ["browse", "annotate"].includes(data.mode)) {
      mode = data.mode; document.body.classList.toggle("pr-annotating", mode === "annotate"); queueRender(); return;
    }
    if (data.action === "present" && Array.isArray(data.items) && Array.isArray(data.anchors) && data.items.length <= 256 && data.anchors.length <= 256) {
      // 只投影本页node记录，绝不根据消息执行HTML或任意selector。
      presentation = { items: data.items.filter((entry) => entry.target?.scope === "node" && entry.target.page === page),
        anchors: data.anchors.filter((entry) => entry.target?.scope === "node" && entry.target.page === page), showItems: data.showItems === true,
        showAnchors: data.showAnchors === true, activeAnchor: data.activeAnchor, activeItem: data.activeItem, cameraScale: data.cameraScale }; queueRender(); return;
    }
    if (data.action === "select" && typeof data.key === "string") { choose(nodes.get(data.key)); return; }
    if (data.action === "parent") { choose(parentNode(selected), true); return; }
    if (data.action === "locate") {
      const node = resolve(data.target), ok = Boolean(node && visible(node));
      if (ok) {
        // 仅滚动画板内部；父工作台收到局部几何后只平移相机，不重置比例或滚动顶层工具栏。
        for (let parent = node.parentElement; parent && root.contains(parent); parent = parent.parentElement) {
          if (parent.scrollHeight > parent.clientHeight || parent.scrollWidth > parent.clientWidth) {
            const r = node.getBoundingClientRect(), p = parent.getBoundingClientRect();
            parent.scrollTop += r.top - p.top - parent.clientHeight / 2 + r.height / 2;
            parent.scrollLeft += r.left - p.left - parent.clientWidth / 2 + r.width / 2;
          }
        }
        choose(node); send("located", { request: data.request, ok: true, bounds: bounds(node) });
      } else send("located", { request: data.request, ok: false }); return;
    }
    if (data.action === "verify" && Array.isArray(data.targets) && data.targets.length <= 512) {
      catalog(); send("verified", { request: data.request, results: data.targets.map((value) => Boolean(resolve(value))) });
    }
  });
  function inContent(event) { const node = event.target instanceof Element ? event.target : event.target.parentElement; return meaningful(node) && visible(node) ? node : null; }
  document.addEventListener("click", (event) => {
    if (!session || event.target.closest?.("[data-prototype-review-overlay]")) return;
    if (panMoved) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    const node = inContent(event);
    if (mode === "annotate" && node) { event.preventDefault(); event.stopImmediatePropagation(); choose(node); return; }
    if (mode !== "browse" || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest?.("a[href]"); if (!link) return;
    const href = link.getAttribute("href"); if (href.startsWith("#")) return;
    event.preventDefault(); send("intent", { intent: "navigate", target: href });
  }, true);
  document.addEventListener("pointermove", (event) => {
    if (!session) return;
    if (pan && pan.id === event.pointerId) {
      const dx = event.clientX - pan.x, dy = event.clientY - pan.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) { panMoved = true; send("gesture", { gesture: "pan", dx, dy }); pan.x = event.clientX; pan.y = event.clientY; }
      return;
    }
    if (mode === "annotate") { hover = inContent(event); queueRender(); }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!session || !(event.button === 1 || (event.button === 0 && space)) || event.target.closest?.("[data-prototype-review-overlay]")) return;
    event.preventDefault(); event.stopImmediatePropagation(); panMoved = false;
    pan = { id: event.pointerId, x: event.clientX, y: event.clientY, k: presentation.cameraScale || 1 }; event.target.setPointerCapture(event.pointerId);
  }, true);
  const endPan = () => { pan = null; setTimeout(() => { panMoved = false; }, 0); };
  document.addEventListener("pointerup", endPan); document.addEventListener("pointercancel", endPan);
  document.addEventListener("wheel", (event) => {
    if (!session || !(event.ctrlKey || event.metaKey || space)) return;
    event.preventDefault(); send("gesture", { gesture: event.ctrlKey || event.metaKey ? "zoom" : "pan", x: event.clientX, y: event.clientY,
      factor: Math.exp(-event.deltaY * .0022), dx: -event.deltaX, dy: -event.deltaY });
  }, { passive: false });
  document.addEventListener("keydown", (event) => {
    if (!session) return;
    if (event.code === "Space" && !event.target.closest?.("input,select,textarea,button,a,[contenteditable]")) { space = true; event.preventDefault(); }
    if (mode === "annotate" && ["Enter", " "].includes(event.key) && inContent(event)) { event.preventDefault(); event.stopImmediatePropagation(); choose(inContent(event)); }
  }, true);
  document.addEventListener("keyup", () => { space = false; });
  window.addEventListener("blur", () => { space = false; pan = null; });
  window.addEventListener("scroll", queueRender, true); window.addEventListener("resize", queueRender);
})();
