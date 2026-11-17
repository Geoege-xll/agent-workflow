(() => {
  "use strict";
  /* 仅本轮静态工具原型使用的选择/显式手势桥，不是生产反馈协议。
     子文档不接收配置指令、不访问父 DOM；sandbox 保持 opaque origin。
     父页面按准确 contentWindow + 本次 nonce + 当前 page 验证消息。 */
  const params = new URLSearchParams(location.search);
  if (params.get("embedded") !== "1" || window.parent === window) return;
  document.documentElement.dataset.prototypeEmbedded = "true";
  const views = { preferences: "nav-models", native: "nav-native", activation: "nav-activation", diagnostics: "nav-diagnostics" };
  const page = Object.hasOwn(views, params.get("view")) ? params.get("view") : "preferences";
  document.getElementById(views[page])?.click();
  // 只在 iframe 根结束滚动链；既有业务 scrollport、字体、尺寸与布局均由原稿持有。
  document.documentElement.style.overscrollBehavior = "contain";
  if (document.scrollingElement) document.scrollingElement.style.overscrollBehavior = "contain";
  const nonce = params.get("bridge"), reviewing = params.get("review") === "1";
  if (!nonce || !/^[a-zA-Z0-9-]{16,80}$/.test(nonce)) return;
  let chosen = null, space = false, pan = null, panMoved = false;
  const send = body => parent.postMessage({ namespace: "xy-solid-glass-prototype-v1", nonce, page, ...body }, "*");
  function sendTarget(target) {
    if (!target?.id) return;
    const rect = target.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const label = (target.getAttribute("aria-label") || target.textContent || target.id).replace(/\s+/g, " ").trim().slice(0,120);
    send({ type: "selection", target: { id: target.id.slice(0,160), label, x: rect.x, y: rect.y, width: rect.width, height: rect.height } });
  }
  document.addEventListener("click", event => {
    if (panMoved) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    if (!reviewing || event.altKey) return;
    const target = event.target.closest("[id]:not([hidden])");
    if (!target || !target.closest("[data-prototype-page-content]")) return;
    event.preventDefault(); event.stopImmediatePropagation(); chosen = target; sendTarget(target);
  }, true);
  document.addEventListener("pointerdown", event => {
    if (event.button === 1 || (event.button === 0 && space)) {
      pan = { id: event.pointerId, x: event.clientX, y: event.clientY }; panMoved = false;
      event.target.setPointerCapture(event.pointerId); event.preventDefault(); return;
    }
    // 评审普通点击仍只选择；Alt 将原生控件操作临时交回原稿。
    if (reviewing && !event.altKey) event.preventDefault();
  }, true);
  document.addEventListener("pointermove", event => {
    if (!pan || pan.id !== event.pointerId) return;
    const dx = event.clientX - pan.x, dy = event.clientY - pan.y;
    if (Math.abs(dx)+Math.abs(dy) <= 3) return;
    panMoved = true; send({ type: "gesture", gesture: "pan", dx, dy }); pan.x = event.clientX; pan.y = event.clientY;
  });
  const endPan = () => { pan = null; setTimeout(() => { panMoved = false; },0); };
  document.addEventListener("pointerup", endPan); document.addEventListener("pointercancel", endPan);
  document.addEventListener("keydown", event => {
    if (event.code === "Space" && !event.target.closest("input,textarea,select,button,a,[contenteditable]")) { space = true; event.preventDefault(); }
  });
  document.addEventListener("keyup", event => { if (event.code === "Space") space = false; });
  window.addEventListener("blur", () => { space = false; pan = null; panMoved = false; });
  document.addEventListener("wheel", event => {
    // 普通 wheel/触控板双指完全原生；Space 不把滚动切换成外画布平移。
    if (event.defaultPrevented || (!event.ctrlKey && !event.metaKey)) return;
    event.preventDefault(); send({ type: "gesture", gesture: "zoom", factor: Math.exp(-event.deltaY*.0022), x:event.clientX, y:event.clientY });
  }, { passive:false });
  document.addEventListener("scroll", () => { if (chosen) sendTarget(chosen); }, true);
  window.addEventListener("resize", () => { if (chosen) sendTarget(chosen); });
})();
