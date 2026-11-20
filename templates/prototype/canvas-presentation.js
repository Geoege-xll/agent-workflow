/* 文件与HTTP画布共同的尺寸/合同边界。尺寸来自声明或子页受限实测，
 * 保留原始frame的宽高、裁剪和内部滚动；外部相机只改变展示比例。 */
(() => {
  "use strict";
  const validSize = (value) => value && Number.isFinite(value.width) && Number.isFinite(value.height)
    && value.width >= 1 && value.width <= 16384 && value.height >= 1 && value.height <= 16384;
  function measure() {
    // 只有明确 fixed 稿件的 frame 是设计视口。responsive 的自然高度是内容高度，
    // 不能上报后反过来撑大 iframe，否则长页会再次 fit 成一张极小的整页缩略图。
    if (document.body.dataset.prototypeDisplay === "fixed") {
      const frames = document.querySelectorAll(".prototype-frame");
      const frame = frames.length === 1 ? frames[0] : document.querySelector("[data-prototype-page-content]");
      const rect = frame?.getBoundingClientRect();
      if (validSize(rect && { width: rect.width, height: rect.height })) return { width: rect.width, height: rect.height };
    }
    return { width: innerWidth, height: innerHeight };
  }
  function create({ viewport, world, preview, toolbar, entry, onResize = () => {} }) {
    let current = entry, size, area, measured = false;
    const declared = () => current?.display !== "responsive" && validSize(current?.viewport);
    function resize(value, fromChild = false) {
      if (!validSize(value)) return false;
      // 父层持有最终设计视口。声明固定尺寸优先；只有未解析到声明的 fixed 页允许
      // 首次子页 frame 测量补足。responsive/未声明页面绝不消费自然内容的整页高度。
      // HTTP 启动目录只提供导航身份，没有 display 字段。认证子桥只给明确的 fixed 画板
      // 上报这个标记；如果文件交付已有展示声明，则始终优先采用目录里的固定／响应式约定。
      const fixed = current?.display === "fixed" || (!current?.display && value.display === "fixed");
      if (fromChild && (declared() || !fixed || measured)) return false;
      if (fromChild) measured = true;
      size = { width: value.width, height: value.height };
      for (const node of [world, preview]) { node.style.width = `${size.width}px`; node.style.height = `${size.height}px`; node.style.inlineSize = `${size.width}px`; node.style.blockSize = `${size.height}px`; }
      return true;
    }
    function readArea() {
      const rect = viewport.getBoundingClientRect();
      // 两个入口的原点都在 viewport 左上角。工具条的真实顶部已包含底部边距、整组复选框与换行，
      // 因此这条边界以下留给工具，顶部无需再扣历史工具条高度。
      const height = toolbar ? Math.max(0, Math.min(rect.height, toolbar.getBoundingClientRect().top - rect.top)) : rect.height;
      return { width: rect.width, height, paddingX: Math.min(24, rect.width / 4), paddingY: Math.min(24, height / 4) };
    }
    function resizeToArea() {
      // 响应式使用父级可用视口，不采用子页自然高度。短视口仍保留最小布局盒，
      // 由相机缩放显示，避免通过一个极窄或极矮的逻辑视口改变稿件的布局分支。
      resize({ width: Math.max(120, area.width - 2 * area.paddingX), height: Math.max(120, area.height - 2 * area.paddingY) });
    }
    function select(value) {
      current = value; measured = false;
      preview.style.colorScheme = "";
      area = readArea();
      if (declared()) resize(current.viewport);
      else resizeToArea();
    }
    function matchColorScheme(scheme) {
      // 浏览器会为不同色系的 iframe 和子文档补一层不透明 Canvas 色。这里只匹配单色系原稿；
      // 双色系稿沿用已由嵌入元素传入的偏好。协议只把已认证子页反馈映射到固定 CSS 值。
      if (scheme === "normal") preview.style.colorScheme = "normal";
      if (scheme === "light" || scheme === "only light") preview.style.colorScheme = "light";
      if (scheme === "dark" || scheme === "only dark") preview.style.colorScheme = "dark";
    }
    const observer = new ResizeObserver(() => {
      const next = readArea();
      if (next.width === area.width && next.height === area.height) return;
      area = next;
      if (!declared() && !measured) resizeToArea();
      onResize();
    });
    observer.observe(viewport);
    if (toolbar) observer.observe(toolbar);
    select(entry);
    return Object.freeze({ select, resize, read: () => size, readArea, matchColorScheme, close() { observer.disconnect(); } });
  }
  function navigation(pages, href, choose) {
    const nav = document.getElementById("prototype-pages");
    const groups = new Map(), links = new Map();
    nav.replaceChildren();
    for (const entry of pages) {
      let parent = nav;
      const path = [];
      // 文件名排序与分组无关。按完整祖先路径复用节点，同名子组可以出现在不同父组下。
      // 旧页缺少权威分组时保持可访问；多页目录用独立的未分组节点，不猜测业务归属。
      const declared = entry.groups || [];
      const chain = declared.length ? declared : pages.length > 1 ? [{ label: "未分组", open: false }] : [];
      for (const group of chain) {
        path.push(group.label);
        const key = declared.length ? JSON.stringify(path) : "";
        if (!groups.has(key)) {
          const details = document.createElement("details"), summary = document.createElement("summary");
          summary.textContent = group.label;
          details.open = group.open;
          details.append(summary);
          parent.append(details);
          groups.set(key, details);
        }
        parent = groups.get(key);
      }
      const link = document.createElement("a");
      link.href = href(entry);
      link.dataset.page = entry.name;
      link.textContent = entry.label;
      link.addEventListener("click", (event) => {
        if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        choose(entry);
      });
      parent.append(link);
      links.set(entry.name, link);
    }
    return (name) => {
      for (const [key, link] of links) {
        if (key !== name) { link.removeAttribute("aria-current"); continue; }
        link.setAttribute("aria-current", "page");
        // 只展开当前页的祖先，不重建目录或干扰其他分支的展开状态。
        for (let node = link.parentElement; node && node !== nav; node = node.parentElement) node.open = true;
      }
    };
  }

  function readNotes() {
    const notes = document.querySelector("details.prototype-contract");
    // 使用原稿的直接内容节点，兼容旧稿分节和新稿自由段落；不将脚本、样式或原始 HTML 发给父壳。
    const sections = Array.from(notes?.childNodes || [])
      .filter((node) => node.nodeType === 3 || node.nodeType === 1 && !["SUMMARY", "SCRIPT", "STYLE", "TEMPLATE"].includes(node.tagName))
      .map((node) => node.textContent.trim()).filter(Boolean);
    const link = document.querySelector('nav.prototype-requirement-links a[data-prototype-document="markdown"]');
    // 父壳自己决定允许打开的已登记文档。子页只传原有链接的片段，永远不提供协议、路径或新窗口目标。
    return { sections, fragment: link ? new URL(link.href).hash : null };
  }

  function contract(sections, fragment, requirementURL) {
    const content = document.getElementById("page-contract-content");
    if (!content) return;
    content.replaceChildren();
    if (!Array.isArray(sections) || !sections.every((value) => typeof value === "string" && value.length <= 65536)) return;
    for (const text of sections) {
      const paragraph = document.createElement("p");
      paragraph.textContent = text;
      content.append(paragraph);
    }
    if (!sections.length) content.textContent = "本页没有补充开发说明。";
    if (requirementURL && typeof fragment === "string" && fragment.length <= 2048 && (!fragment || fragment.startsWith("#"))) {
      const url = new URL(requirementURL);
      url.hash = fragment;
      const link = document.createElement("a");
      link.href = url.href; link.target = "_blank"; link.rel = "noopener";
      link.textContent = fragment ? "查看关联需求章节" : "查看关联需求";
      content.append(link);
    }
  }
  window.PrototypeCanvasPresentation = Object.freeze({ validSize, measure, create, navigation, readNotes, contract });
})();
