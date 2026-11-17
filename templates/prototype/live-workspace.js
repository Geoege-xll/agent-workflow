/* 双网页入口：连接、草稿保存与来源变化提示在此编排，画布和业务评审状态各有唯一所有者。
 * 交付页无评审写入；评审页使用服务CAS保存，任何冲突/来源变化均保留本页输入并停止自动写入。 */
(() => {
  "use strict";
  // file交付由经典只读编排器负责，绝不创建HTTP控制连接。
  if (location.protocol === "file:") return;
  const $ = (id) => document.getElementById(id), reviewing = document.body.classList.contains("live-review");
  const announce = (message) => { $("review-status").textContent = message; };
  const slots = document.querySelectorAll("script#prototype-review-data");
  const boot = slots.length === 1 && slots[0].type === "application/json" ? window.PrototypeReviewState.parseStartup(slots[0].textContent) : null;
  function fail(message) { $("prototype-preview").removeAttribute("src"); $("prototype-empty").hidden = false; $("prototype-empty").textContent = message; }
  if (!boot?.context || boot.schema_version !== 5 || parent !== window || document.querySelectorAll("iframe").length !== 1
    || $("prototype-preview").getAttribute("sandbox") !== "allow-scripts") { fail(boot?.error || "请从本轮交付入口打开画布。"); return; }
  const connection = window.PrototypeLiveConnection.create(boot.context);
  let model, host, timer = null, saveTimer = null, closed = false, checking = false, revision = 0, pending = null, saving = false, paused = false;
  const warning = document.createElement("p"); warning.className = "live-source-warning"; warning.setAttribute("role", "alert"); warning.hidden = true; $("review-workspace").insertBefore(warning, document.querySelector(".review-toolbar").nextSibling);
  function stopWrites(message, block = false) { paused = true; clearTimeout(saveTimer); warning.hidden = false; warning.textContent = message; if (block) { clearInterval(timer); model?.block(); } model?.setStorageMessage(message); announce(message); }
  function currentName() { return boot.pages.find((entry) => entry.path === model?.state.page)?.name || boot.pages[0].name; }
  async function checkSource() {
    if (closed || checking || model?.state.blocked) return; checking = true;
    try { const value = await connection.context(currentName());
      if (value.status === "source_changed" || value.context.review_id !== boot.context.review_id) stopWrites("原稿已变化；当前旧稿与意见保留，请从交付入口重新开启评审。", true);
    } catch (error) { if (!closed) { if (error.code === "source_changed") stopWrites(error.message, true); else announce(error.message); } }
    finally { checking = false; }
  }
  async function flush() {
    if (saving || paused || !pending || closed) return;
    saving = true; const outgoing = pending; pending = null; model.setStorageMessage("正在保存草稿……");
    try { const value = await connection.saveDraft(revision, outgoing); revision = value.revision; model.setStorageMessage("草稿已保存到本轮本地服务；刷新可恢复。"); }
    catch (error) { pending ||= outgoing; stopWrites(error.message, error.code === "source_changed" || error.code === "draft_conflict"); }
    finally { saving = false; if (pending && !paused && !closed) saveTimer = setTimeout(flush, 180); }
  }
  async function start() {
    // 首次恢复在渲染和编辑之前完成；不会用一个空快照先覆盖服务已有草稿。
    const stored = reviewing ? await connection.readDraft() : { revision: 0, draft: null }; revision = stored.revision;
    const storage = { getItem() { return stored.draft ? JSON.stringify(stored.draft) : null; }, setItem(key, value) {
      if (!reviewing) return; pending = JSON.parse(value); clearTimeout(saveTimer); if (!paused) saveTimer = setTimeout(flush, 180);
    } };
    model = window.PrototypeReviewState.create(boot, storage); if (reviewing) model.setMode("annotate");
    host = window.PrototypeCanvasHost.create({ boot, model, reviewing, announce, onNavigate(entry) {
      if (!reviewing) {
        $("open-review").href = `/review/${encodeURIComponent(entry.name)}`;
        for (const link of $("prototype-pages").querySelectorAll("a")) { if (link.dataset.page === entry.path) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current"); }
      }
      // 地址只投影登记的name，凭据已从fragment清除；刷新不会跳回首个页面。
      history.replaceState(null, "", `/${reviewing ? "review" : "delivery"}/${encodeURIComponent(entry.name)}`);
    } });
    if (reviewing) host.attachViews(window.PrototypeFeedback.create({ model, send: host.send, locate: host.locate, verifySources: async (targets) => { await checkSource(); if (model.state.blocked) throw Error(warning.textContent); await host.verifySources(targets); }, camera: host.camera, announce, present: host.present }));
    else {
      const toggle = $("navigation-toggle"), navigation = $("delivery-navigation");
      // 收起只改变工具目录和焦点，不重建原稿或重置相机；HTTP 与 file 各自仅注册一次。
      function closeNavigation() { navigation.hidden = true; toggle.setAttribute("aria-expanded", "false"); toggle.focus(); }
      // 合同仍属于交付说明，只投影子页声明的五段纯文本；评审壳不维护说明入口或副本。
      host.attachViews({ contract: window.PrototypeCanvasPresentation.contract });
      $("open-review").addEventListener("click", (event) => {
        event.preventDefault();
        // 认证fragment只传给受信同源新窗口，不常驻可见链接/浏览器悬停地址；新窗口即刻清除。
        window.open(connection.reviewURL(currentName()), "_blank", "noopener");
      });
      $("open-developer").addEventListener("click", () => { $("developer-dialog").showModal(); $("developer-title").focus(); });
      $("developer-close").addEventListener("click", () => $("developer-dialog").close());
      for (const entry of boot.pages) { const link = document.createElement("a"); link.textContent = entry.label; link.dataset.page = entry.path; link.href = `/delivery/${encodeURIComponent(entry.name)}`;
        link.addEventListener("click", (event) => { if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); closeNavigation(); host.navigate(entry.path).catch((error) => announce(error.message)); }); $("prototype-pages").append(link); }
      toggle.addEventListener("click", () => { navigation.hidden = !navigation.hidden; toggle.setAttribute("aria-expanded", String(!navigation.hidden)); });
      document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !navigation.hidden) { event.preventDefault(); closeNavigation(); } });
      $("canvas-fit").addEventListener("click", host.camera.fit); $("canvas-zoom-out").addEventListener("click", () => host.camera.zoom(1 / 1.25)); $("canvas-zoom-in").addEventListener("click", () => host.camera.zoom(1.25)); $("canvas-zoom-reset").addEventListener("click", () => host.camera.zoom(1 / model.state.cameras[model.state.page].k));
    }
    const name = decodeURIComponent(location.pathname.split("/").at(-1)), initial = boot.pages.find((entry) => entry.name === name);
    if (!initial) throw Error("此页面未登记在本轮来源中。");
    await host.navigate(initial.path); await checkSource();
    if (!paused) announce(reviewing ? "点选元素进行批注；按住 Alt 临时操作原型，松开恢复批注。" : "当前画布来自唯一原稿。进入评审将在新标签页打开当前页面。");
    if (!model.state.blocked) timer = setInterval(checkSource, 2500);
  }
  // 不在unload盲目重放PUT。未完成保存时明确阻止无意离开，凭据/请求生命周期随网页结束。
  window.addEventListener("beforeunload", (event) => { if (reviewing && (pending || saving)) { event.preventDefault(); event.returnValue = ""; } });
  window.addEventListener("pagehide", () => { closed = true; clearInterval(timer); clearTimeout(saveTimer); host?.close(); connection.close(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkSource(); });
  start().catch((error) => fail(error.message));
})();
