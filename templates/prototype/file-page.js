/* file设计子页只负责只读呈现与手势，不获得HTTP控制连接或评审凭据。 */
(() => {
  "use strict";
  const context = window.XYFilePageContext; if (!context || parent === window || location.protocol !== "file:") return;
  const scriptURL = document.currentScript.src;
  let connected = false, space = false, pan = null, panMoved = false;
  const send = (type, body = {}) => { if (connected) parent.postMessage({ type: `xy-file:${type}`, page: context.name, nonce: context.nonce, ...body }, "*"); };
  function start() {
    const root = document.querySelector("[data-prototype-page-content]"); if (!root) return;
    // 保留stage/frame本身的布局约束，仅隐藏外围说明与导航；不把祖先变为contents。
    const frame = document.querySelector(".prototype-frame") || root;
    const stage = frame.parentElement?.closest(".prototype-stage");
    let branch = stage || frame;
    while (branch && branch !== document.body) { for (const sibling of branch.parentElement.children) if (sibling !== branch && !["SCRIPT", "STYLE", "LINK"].includes(sibling.tagName)) sibling.hidden = true; branch = branch.parentElement; }
    document.body.style.margin = "0"; document.body.style.padding = "0";
    // iframe 的根滚动链在文档边界结束；nested scrollport 保留业务原有 overflow、
    // overscroll 与自然链路。只设置根，不拦截普通 wheel，也不靠 stopPropagation 假隔离。
    document.documentElement.style.overscrollBehavior = "contain";
    if (document.scrollingElement) document.scrollingElement.style.overscrollBehavior = "contain";
    // 原始手机frame保持固定宽高；外层stage仅移除展示页的居中留白，避免在真实390视口里再次偏移。
    for (let ancestor = frame.parentElement; ancestor && ancestor !== document.body; ancestor = ancestor.parentElement) {
      ancestor.style.margin = "0"; ancestor.style.padding = "0"; ancestor.style.minHeight = "0";
      if (getComputedStyle(ancestor).display.includes("flex")) { ancestor.style.justifyContent = "flex-start"; ancestor.style.alignItems = "flex-start"; }
    }
    const measure = () => { if (document.body.dataset.prototypeDisplay !== "fixed") return;
      const r = frame.getBoundingClientRect(); send("size", { display: "fixed", width: r.width, height: r.height }); };
    window.addEventListener("message", (event) => { const data = event.data;
      if (event.source !== parent || event.origin !== "null" || data?.type !== "xy-file:connect" || data.page !== context.name || data.nonce !== context.nonce) return;
      if (connected) return;
      connected = true;
      // 只有本轮只读握手通过后，才启用与 HTTP 评审共用的根及舞台背景规则。
      document.documentElement.classList.add("prototype-canvas-embedded");
      stage?.classList.add("prototype-canvas-stage");
      const stylesheet = document.createElement("link");
      stylesheet.rel = "stylesheet"; stylesheet.href = new URL("feedback.css", scriptURL).href;
      document.head.append(stylesheet);
      send("ready", { colorScheme: getComputedStyle(document.documentElement).colorScheme }); measure(); send("contract", window.PrototypeCanvasPresentation.readNotes()); });
    new ResizeObserver(measure).observe(frame);
    document.addEventListener("click", (event) => { if (panMoved) { event.preventDefault(); event.stopImmediatePropagation(); return; } const link = event.target.closest?.("a[href]"); if (!link || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const href = link.getAttribute("href"); if (!href || href.startsWith("#")) return; event.preventDefault(); send("navigate", { target: href }); }, true);
    document.addEventListener("keydown", (event) => { if (event.code === "Space" && !event.target.closest("input,textarea,select,button,a,[contenteditable]")) { space = true; event.preventDefault(); } });
    document.addEventListener("keyup", (event) => { if (event.code === "Space") space = false; }); window.addEventListener("blur", () => { space = false; pan = null; panMoved = false; });
    document.addEventListener("pointerdown", (event) => { if (connected && (event.button === 1 || (event.button === 0 && space))) { panMoved = false; pan = { id: event.pointerId, x: event.clientX, y: event.clientY }; event.target.setPointerCapture(event.pointerId); event.preventDefault(); } }, true);
    document.addEventListener("pointermove", (event) => { if (!pan || pan.id !== event.pointerId) return;
      const dx = event.clientX - pan.x, dy = event.clientY - pan.y; if (Math.abs(dx)+Math.abs(dy)<=3) return;
      panMoved = true; send("gesture", { gesture: "pan", dx, dy }); pan.x = event.clientX; pan.y = event.clientY; });
    // 显式拖动结束后的合成 click 不得激活业务链接；下一事件轮恢复普通点击。
    const endPan = () => { pan = null; setTimeout(() => { panMoved = false; },0); };
    document.addEventListener("pointerup", endPan); document.addEventListener("pointercancel", endPan);
    document.addEventListener("wheel", (event) => { if (!connected || event.defaultPrevented || (!event.ctrlKey && !event.metaKey)) return; event.preventDefault(); send("gesture", { gesture: "zoom", factor: Math.exp(-event.deltaY * .0022), x: event.clientX, y: event.clientY }); }, { passive: false });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true }); else start();
})();
