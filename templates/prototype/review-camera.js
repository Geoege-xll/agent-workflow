/* 相机 applyCam / fitCam / zoomAt 与平移计算实质抽取并适配自固定上游：
 * https://github.com/nishuzumi/show-me-you-want-skill/blob/1f6d786dddd36a33b002ce8afff70d43d08a9460/skills/smyw/assets/runtime.js
 * MIT / Copyright (c) 2026 box；完整许可随 THIRD_PARTY_NOTICES.txt 分发。
 * 该模块不认识DOM目标、整改或导出；可变相机始终由调用方唯一state持有。 */
(() => {
  "use strict";
  const clamp = (value) => Math.max(.08, Math.min(3, value));
  function zoomAt(camera, factor, mx, my) {
    const k = clamp(camera.k * factor);
    return { x: mx - (mx - camera.x) * (k / camera.k), y: my - (my - camera.y) * (k / camera.k), k };
  }
  function fitCam(width, height, worldWidth = 1120, worldHeight = 860, topInset = 76) {
    const k = Math.max(.08, Math.min(1, (width - 48) / worldWidth, (height - topInset - 24) / worldHeight));
    return { k, x: Math.max(24, (width - worldWidth * k) / 2), y: Math.max(topInset, topInset + (height - topInset - worldHeight * k) / 2) };
  }
  function focusBounds(camera, bounds, width, height) {
    return { k: camera.k, x: width / 2 - (bounds.x + bounds.w / 2) * camera.k, y: height / 2 - (bounds.y + bounds.h / 2) * camera.k };
  }
  function create({ viewport, world, read, write, topInset = () => 76, onApply = () => {} }) {
    let pan = null, space = false;
    function applyCam() {
      const c = read(); if (!c) return;
      world.style.transform = 'translate(' + c.x + 'px,' + c.y + 'px) scale(' + c.k + ')';
      onApply(c);
    }
    const update = (c) => { write(c); applyCam(); };
    const fit = () => { const r = viewport.getBoundingClientRect(); update(fitCam(r.width, r.height, 1120, 860, topInset())); };
    function zoom(factor, x, y) {
      const r = viewport.getBoundingClientRect(); if (!read()) return;
      update(zoomAt(read(), factor, x ?? r.width / 2, y ?? r.height / 2));
    }
    function move(dx, dy) { if (read()) update({ ...read(), x: read().x + dx, y: read().y + dy }); }
    // 画布空白拥有平移；稿件内的原生控件/滚动由child处理后，仅显式手势发到此边界。
    viewport.addEventListener("pointerdown", (event) => {
      if (event.target.closest("[data-review-ui]")) return;
      if (event.button !== 1 && !(event.button === 0 && (space || event.target === viewport))) return;
      const c = read(); if (!c) return;
      pan = { id: event.pointerId, x: event.clientX, y: event.clientY, cx: c.x, cy: c.y };
      viewport.setPointerCapture(event.pointerId); event.preventDefault();
    });
    viewport.addEventListener("pointermove", (event) => {
      if (!pan || pan.id !== event.pointerId) return;
      viewport.classList.add("panning"); update({ ...read(), x: pan.cx + event.clientX - pan.x, y: pan.cy + event.clientY - pan.y });
    });
    const end = () => { pan = null; viewport.classList.remove("panning"); };
    viewport.addEventListener("pointerup", end); viewport.addEventListener("pointercancel", end);
    viewport.addEventListener("wheel", (event) => {
      if (event.target.closest("[data-review-ui]")) return;
      const r = viewport.getBoundingClientRect(); event.preventDefault();
      if (event.ctrlKey || event.metaKey) zoom(Math.exp(-event.deltaY * .0022), event.clientX - r.left, event.clientY - r.top);
      else move(-(event.shiftKey ? event.deltaY : event.deltaX), -(event.shiftKey ? 0 : event.deltaY));
    }, { passive: false });
    viewport.addEventListener("keydown", (event) => {
      if (event.target !== viewport) return;
      if (event.code === "Space") { space = true; viewport.classList.add("space"); event.preventDefault(); }
      const delta = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] }[event.key];
      if (delta) { event.preventDefault(); move(...delta); }
    });
    viewport.addEventListener("keyup", () => { space = false; viewport.classList.remove("space"); });
    window.addEventListener("blur", end);
    return Object.freeze({ applyCam, fit, zoom, move, focus(bounds) { const r = viewport.getBoundingClientRect(); if (read()) update(focusBounds(read(), bounds, r.width, r.height)); } });
  }
  window.PrototypeReviewCamera = Object.freeze({ zoomAt, fitCam, focusBounds, create });
})();
