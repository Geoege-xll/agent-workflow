/* 文件与HTTP画布共同的尺寸/合同边界。尺寸来自声明或子页受限实测，
 * 保留原始frame的宽高、裁剪和内部滚动；外部相机只改变展示比例。 */
(() => {
  "use strict";
  const validSize = (value) => value && Number.isFinite(value.width) && Number.isFinite(value.height)
    && value.width >= 1 && value.width <= 16384 && value.height >= 1 && value.height <= 16384;
  function measure() {
    const frames = document.querySelectorAll(".prototype-frame");
    const frame = frames.length === 1 ? frames[0] : document.querySelector("[data-prototype-page-content]");
    const rect = frame?.getBoundingClientRect();
    return validSize(rect && { width: rect.width, height: rect.height }) ? { width: rect.width, height: rect.height } : { width: innerWidth, height: innerHeight };
  }
  function create({ viewport, world, preview, entry, onResize = () => {} }) {
    let current = entry, size, measured = false;
    function resize(value, fromChild = false) { if (!validSize(value) || (fromChild && measured)) return false;
      if (fromChild) measured = true; size = { width: value.width, height: value.height };
      for (const node of [world, preview]) { node.style.width = `${size.width}px`; node.style.height = `${size.height}px`; node.style.inlineSize = `${size.width}px`; node.style.blockSize = `${size.height}px`; }
      onResize(size); return true; }
    function select(value) { current = value; measured = false;
      // 响应式稿由当前可用画布宽度驱动媒体查询；固定稿只用声明尺寸，未知稿先测量真实子页。
      const rect = viewport.getBoundingClientRect();
      resize(validSize(value?.viewport) ? value.viewport : { width: Math.max(120, rect.width - 48), height: Math.max(120, rect.height - 48) }); }
    const observer = new ResizeObserver(() => { if (!validSize(current?.viewport) && !measured) select(current); }); observer.observe(viewport);
    select(entry);
    return Object.freeze({ select, resize, read: () => size, close() { observer.disconnect(); } });
  }
  function contract(sections) {
    const names = ["purpose", "navigation", "interactions", "states", "exceptions"];
    if (!Array.isArray(sections) || sections.length !== 5 || !sections.every((entry, index) => entry?.name === names[index] && typeof entry.text === "string" && entry.text.length <= 65536)) return;
    const content = document.getElementById("page-contract-content"); if (!content) return; content.replaceChildren();
    const titles = ["页面职责", "导航", "交互", "状态与恢复", "例外与实现边界"];
    sections.forEach((entry, index) => { const section = document.createElement("section"), title = document.createElement("h3"), text = document.createElement("p");
      title.textContent = titles[index]; text.textContent = entry.text || "本页尚未声明此段说明。"; section.append(title, text); content.append(section); });
  }
  window.PrototypeCanvasPresentation = Object.freeze({ validSize, measure, create, contract });
})();
