/* 唯一delivery模板的文件编排器：只消费公开目录，不构建控制连接、不猜测服务端口。 */
(async () => {
  "use strict";
  if (location.protocol !== "file:" || parent !== window) return;
  const $ = (id) => document.getElementById(id), state = window.XYFileDeliveryEntry?.state;
  const announce = (message) => { $("review-status").textContent = message; };
  const fail = (message) => { $("prototype-empty").hidden = false; $("prototype-empty").textContent = message; announce(message); };
  let catalog = state?.catalog;
  let directoryTrusted = false;
  const secureHandshake = typeof globalThis.crypto?.getRandomValues === "function";
  const recovery = "交付目录未通过位置校验，请让Agent在当前目录重新执行prepare-delivery；当前画稿保留，目录与评审绑定已停用。";
  const filename = /^[a-z0-9][a-z0-9-]*\.html$/;
  if (!catalog || catalog.schema_version !== 1 || !Array.isArray(catalog.pages) || !catalog.pages.length || catalog.pages.length > 256
    || !catalog.pages.every((entry) => filename.test(entry.name) && entry.name !== "index.html" && typeof entry.path === "string" && !entry.path.split("/").some((part) => part === ".." || !part) && entry.path.split("/").pop() === entry.name && typeof entry.label === "string" && entry.label.length <= 1024
      && Array.isArray(entry.groups) && entry.groups.length <= 32 && entry.groups.every((group) => typeof group?.label === "string" && group.label.trim() && group.label.length <= 1024 && typeof group.open === "boolean"))
    || new Set(catalog.pages.map((entry) => entry.name)).size !== catalog.pages.length) { fail("交付目录无效，请重新准备交付入口。"); return; }
  // 摘要仅绑定当前文件所在目录，无机器绝对路径进入发现信息；不以旧软链推断新目录身份。
  // crypto缺失或失败必须关闭目录/评审能力，不能把可见原稿误称为旧项目的可信交付。
  try {
    if (!secureHandshake || typeof state.originalFileURL !== "string" || !/^[a-f0-9]{64}$/.test(catalog.directory_sha256 || "") || !globalThis.crypto?.subtle) throw Error("directory_unverified");
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(new URL(".", state.originalFileURL).href));
    directoryTrusted = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("") === catalog.directory_sha256;
  } catch { directoryTrusted = false; }
  if (!directoryTrusted) catalog = { pages: [{ name: state.name, path: state.name, label: state.name, viewport: null, binding: null }] };
  const initial = catalog.pages.find((entry) => entry.name === state.name); if (!initial) { fail("此页面未登记，请重新准备交付入口。"); return; }
  const preview = $("prototype-preview"), viewport = $("canvas-viewport");
  // 只有file设计子页允许same-origin以加载相对资源；HTTP评审仍由原承载器严格allow-scripts。
  preview.setAttribute("sandbox", "allow-scripts allow-same-origin");
  let current = initial, nonce = "", readyTimer, cameraValue = null, closed = false;
  const presentation = window.PrototypeCanvasPresentation.create({ viewport, world: $("canvas-world"), preview,
    toolbar: $("canvas-floating-controls"), entry: initial, onResize: () => camera.refresh() });
  const camera = window.PrototypeReviewCamera.create({ viewport, world: $("canvas-world"), read: () => cameraValue,
    write: (value) => { cameraValue = value; }, dimensions: presentation.read, readArea: presentation.readArea,
    onApply: (value) => { $("canvas-zoom-reset").textContent = `${Math.max(1, Math.round(value.k * 100))}%`; } });
  function reviewURL(entry) {
    if (!directoryTrusted) return null;
    const binding = entry.binding;
    if (!binding || !/^[a-f0-9]{32,128}$/.test(binding.review_id || "") || !/^[a-f0-9]{16,128}$/.test(binding.instance || "")
      || typeof binding.request_id !== "string" || !/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(binding.origin || "")) return null;
    const origin = new URL(binding.origin); if (Number(origin.port) > 65535) return null;
    return `${origin.origin}/_entry-review/${encodeURIComponent(binding.instance)}/${encodeURIComponent(binding.review_id)}/${encodeURIComponent(entry.name)}`;
  }
  function navigate(entry) {
    // file文档是opaque origin，History API不能把当前地址改成另一个文件。
    // 登记页切换使用正常顶层file导航，刷新/新标签评审始终对应当前具体物理HTML。
    if (entry.name !== state.name) { location.assign(new URL(entry.name, state.originalFileURL).href); return; }
    current = entry; clearTimeout(readyTimer); nonce = secureHandshake ? Array.from(globalThis.crypto.getRandomValues(new Uint8Array(24)), (value) => value.toString(16).padStart(2, "0")).join("") : "";
    presentation.select(entry); cameraValue = null; camera.fit();
    $("current-page-title").textContent = entry.label; document.title = `${entry.label} · 原型交付`; preview.title = entry.label;
    $("page-contract-content").replaceChildren(); $("prototype-empty").hidden = true; preview.hidden = false; preview.setAttribute("aria-busy", "true");
    const url = new URL(entry.name, location.href); url.hash = new URLSearchParams({ "xy-file-nonce": nonce, "xy-file-page": entry.name });
    if (!secureHandshake) {
      // 整个crypto缺失时不能建立安全随机握手，也不能用弱随机冒充可信连接。
      // 直接显示当前物理原稿并保留其原生滚动/业务行为；不发送握手、不等待ready，
      // 不启用旧目录、评审或依赖子页消息的开发说明。此退化只承诺原稿可读。
      preview.src = new URL(entry.name, state.originalFileURL).href;
      preview.setAttribute("aria-busy", "false");
      $("open-developer").disabled = true; $("navigation-toggle").disabled = true;
      $("open-review").removeAttribute("href"); $("open-review").setAttribute("aria-disabled", "true");
      announce(`${recovery} 安全随机能力不可用，当前仅显示原稿。`); return;
    }
    preview.src = url.href;
    const review = reviewURL(entry); if (review) { $("open-review").href = review; $("open-review").removeAttribute("aria-disabled"); }
    else { $("open-review").removeAttribute("href"); $("open-review").setAttribute("aria-disabled", "true"); }
    selectNavigation(entry.name);
    announce("正在载入当前原稿……"); readyTimer = setTimeout(() => fail("设计页通信超时，请重新准备交付入口后打开；原稿保持。"), 7000);
  }
  preview.addEventListener("load", () => { if (!closed && secureHandshake) preview.contentWindow.postMessage({ type: "xy-file:connect", page: current.name, nonce }, "*"); });
  window.addEventListener("message", (event) => { const data = event.data;
    if (closed || !secureHandshake || event.source !== preview.contentWindow || event.origin !== "null" || !data || data.page !== current.name || data.nonce !== nonce) return;
    if (data.type === "xy-file:ready") { clearTimeout(readyTimer); presentation.matchColorScheme(data.colorScheme); preview.setAttribute("aria-busy", "false"); announce(!directoryTrusted ? recovery : reviewURL(current) ? "原稿可直接操作；已登记评审入口，当前连接未核验。连接失败时请让Agent重开本轮服务。" : "当前原稿可直接操作；评审尚未就绪，请运行本轮open后重新打开此文件。"); }
    if (data.type === "xy-file:size" && presentation.resize(data, true)) camera.refresh();
    if (data.type === "xy-file:contract") {
      // 文件路径只从位置校验通过的登记生成，并按路径段编码；跨目录链接不能由子页消息指定。
      const parts = current.plan_source?.split("/");
      const safe = directoryTrusted && parts?.every((part) => part && part !== "." && part !== ".." && !part.includes("\\")) && current.plan_source.endsWith(".md");
      const path = safe ? "../".repeat(current.path.split("/").length - 1) + parts.map(encodeURIComponent).join("/") : null;
      window.PrototypeCanvasPresentation.contract(data.sections, data.fragment, path && new URL(path, state.originalFileURL).href);
    }
    if (data.type === "xy-file:navigate") { const entry = catalog.pages.find((entry) => entry.name === data.target); if (entry) navigate(entry); else announce("目标未登记，当前原稿保持。"); }
    if (data.type === "xy-file:gesture" && cameraValue) { if (data.gesture === "pan" && [data.dx, data.dy].every(Number.isFinite) && Math.abs(data.dx) < 10000 && Math.abs(data.dy) < 10000) camera.move(data.dx * cameraValue.k, data.dy * cameraValue.k);
      if (data.gesture === "zoom" && [data.factor, data.x, data.y].every(Number.isFinite) && data.factor >= .01 && data.factor <= 100) camera.zoom(data.factor, cameraValue.x + data.x * cameraValue.k, cameraValue.y + data.y * cameraValue.k); }
  });
  const selectNavigation = window.PrototypeCanvasPresentation.navigation(catalog.pages,
    (entry) => new URL(entry.name, state.originalFileURL).href, (entry) => { closeNavigation(); navigate(entry); });
  const toggle = $("navigation-toggle"), navigation = $("delivery-navigation");
  toggle.addEventListener("click", () => { navigation.hidden = !navigation.hidden; toggle.setAttribute("aria-expanded", String(!navigation.hidden)); });
  // 目录选择和 Esc 共用同一收起路径；只恢复工具按钮焦点，不干预 iframe 业务事件。
  function closeNavigation() { navigation.hidden = true; toggle.setAttribute("aria-expanded", "false"); toggle.focus(); }
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !navigation.hidden) { event.preventDefault(); closeNavigation(); } });
  $("open-developer").addEventListener("click", () => { $("developer-dialog").showModal(); $("developer-title").focus(); });
  $("developer-close").addEventListener("click", () => $("developer-dialog").close());
  $("open-review").addEventListener("click", (event) => { if (!reviewURL(current)) { event.preventDefault(); announce(directoryTrusted ? "评审尚未就绪，请运行本轮open后重新打开此文件。" : recovery); } });
  $("canvas-fit").addEventListener("click", camera.fit); $("canvas-zoom-out").addEventListener("click", () => camera.zoom(1 / 1.25));
  $("canvas-zoom-in").addEventListener("click", () => camera.zoom(1.25)); $("canvas-zoom-reset").addEventListener("click", camera.resetZoom);
  window.addEventListener("pagehide", () => { closed = true; clearTimeout(readyTimer); presentation.close(); camera.close(); });
  navigate(initial);
})();
