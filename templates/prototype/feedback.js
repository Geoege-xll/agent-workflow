/* 工作台视图、唯一编辑器与交还操作。所有业务变更通过review-state的公开方法，
 * 不持有第二份整改/草稿集合，不把用户文本作为HTML执行，不在浏览器声称Agent已收到。 */
(() => {
  "use strict";
  const operations = { modify: "修改", add: "新增内容", delete: "删除建议" };
  const number = (entry, anchor = false) => `${anchor ? "A" : ""}${String(entry.number).padStart(2, "0")}`;
  const make = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
  function formatExport(payload, scopeLabel) {
    // 唯一实际交还formatter同时供复制、备用文字、下载及原子完成的提交前验证使用。
    // 用户正文逐行作为引用，防止正文中的机器标题/反引号产生第二个机器块。
    const summary = ["# 原型评审反馈", `已完成整改：${payload.items.length}；定位标记：${payload.anchors.length}。`];
    for (const item of payload.items) summary.push(`\n${number(item)} · ${operations[item.operation]} · ${scopeLabel(item.target)}`, ...item.message.split("\n").map((line) => `> ${line}`));
    for (const anchor of payload.anchors) summary.push(`${number(anchor, true)} · ${scopeLabel(anchor.target)}`);
    const value = `${summary.join("\n")}\n\n## Agent Workflow Feedback Payload\n\x60\x60\x60json\n${JSON.stringify(payload, null, 2)}\n\x60\x60\x60\n`;
    // 摘要和pretty JSON会额外占字节，只有最终全文通过同一UTF8预算才能对外交还。
    return window.PrototypeReviewState.checkFeedbackBytes(value, "交还全文（含摘要与机器载荷）");
  }
  function create({ model, send, locate, verifySources, camera, announce, present }) {
    const $ = (id) => document.getElementById(id), state = model.state;
    const editor = $("rectification-dialog"), exporter = $("export-dialog"), drawer = $("panel-drawer"), panel = $("review-panel");
    const narrow = matchMedia("(max-width:900px)");
    let exportEpoch = 0, busy = false, saving = false, backup = "";
    const resumeDrawer = new WeakMap();
    const button = (label, action, className = "review-inline") => { const el = make("button", label, className); el.type = "button"; el.addEventListener("click", action); return el; };
    const report = (error) => announce(error?.message || "操作失败，当前输入已保留。");
    const safe = (action) => { try { const result = action(); if (result?.catch) result.catch(report); } catch (error) { report(error); } };
    const draft = () => state.drafts[state.editor];
    function openPanel() {
      if (!narrow.matches || drawer.open) return;
      $("drawer-panel-host").append(panel); drawer.showModal(); $("open-feedback").setAttribute("aria-expanded", "true");
    }
    function showModal(dialog) {
      // 窄屏先关闭清单抽屉，再打开同一编辑/交还模态；关闭后恢复同一个panel，绝不嵌套。
      resumeDrawer.set(dialog, drawer.open);
      if (drawer.open) drawer.close();
      dialog.showModal();
    }
    drawer.addEventListener("close", () => { $("review-panel-slot").append(panel); $("open-feedback").setAttribute("aria-expanded", "false"); });
    for (const dialog of [editor, exporter]) dialog.addEventListener("close", () => {
      if (dialog === editor) model.closeEditor();
      if (dialog === exporter) { exportEpoch++; busy = false; }
      if (resumeDrawer.get(dialog)) { resumeDrawer.set(dialog, false); openPanel(); }
      dialog.returnValue = "";
    });
    narrow.addEventListener("change", () => { if (!narrow.matches && drawer.open) drawer.close(); });
    for (const [open, close, dialog] of [["navigation-toggle", "close-navigation", $("navigation-drawer")], ["open-developer", "developer-close", $("developer-dialog")]]) {
      $(open).addEventListener("click", () => { if (open === "open-developer") $("page-contract").open = true; dialog.showModal(); $(open).setAttribute("aria-expanded", "true"); if (open === "open-developer") $("developer-title").focus(); });
      $(close).addEventListener("click", () => dialog.close());
      dialog.addEventListener("close", () => { $(open).setAttribute("aria-expanded", "false"); dialog.returnValue = ""; });
    }
    // closedby仅作渐进增强，Safari等宿主仍通过几何检测提供原型约定的抽屉外点关闭。
    if (!("closedBy" in HTMLDialogElement.prototype)) {
      const nav = $("navigation-drawer"); let pressedOutside = false;
      const outside = (e) => { const r = nav.getBoundingClientRect(); return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom; };
      nav.addEventListener("pointerdown", (e) => { pressedOutside = outside(e); });
      nav.addEventListener("pointerup", (e) => { if (pressedOutside && outside(e)) nav.close(); });
    }
    $("open-feedback").addEventListener("click", openPanel); $("close-panel").addEventListener("click", () => drawer.close());
    $("mode-browse").addEventListener("change", () => setMode("browse")); $("mode-annotate").addEventListener("change", () => setMode("annotate"));
    function setMode(mode) { model.setMode(mode); send("mode", { mode }); $("mode-browse").checked = mode === "browse"; $("mode-annotate").checked = mode === "annotate"; announce(mode === "browse" ? "浏览模式：原生控件、滚动与业务导航保持可用。" : "批注模式：点选元素后标记位置或添加整改。"); }
    $("canvas-fit").addEventListener("click", camera.fit); $("canvas-zoom-out").addEventListener("click", () => camera.zoom(1 / 1.25));
    $("canvas-zoom-in").addEventListener("click", () => camera.zoom(1.25)); $("canvas-zoom-reset").addEventListener("click", () => camera.zoom(1 / state.cameras[state.page].k));
    $("show-anchors").addEventListener("change", () => model.setView({ showAnchors: $("show-anchors").checked }));
    $("show-rectifications").addEventListener("change", () => model.setView({ showItems: $("show-rectifications").checked }));
    $("select-parent").addEventListener("click", () => send("parent"));
    $("mark-location").addEventListener("click", () => safe(() => { const anchor = model.addAnchor(); model.setView({ activeAnchor: anchor.id, activeItem: null }); announce(`已标记位置 ${number(anchor, true)}；尚未创建整改。`); }));
    $("add-rectification").addEventListener("click", () => safe(() => openEditor(state.selection?.target || null)));
    $("page-rectification").addEventListener("click", () => safe(() => openEditor({ scope: "page", page: state.page })));
    $("write-global").addEventListener("click", () => safe(() => openEditor({ scope: "global" })));
    $("remove-selected-anchor").addEventListener("click", () => safe(() => { model.removeAnchor(state.activeAnchor); model.setView({ activeAnchor: null }); }));
    $("withdraw-selected-item").addEventListener("click", () => safe(() => { model.withdrawItem(state.activeItem); model.setView({ activeItem: null }); announce("已撤回当前整改，可单次恢复原编号与编辑草稿。"); }));
    $("view-anchor-references").addEventListener("click", () => { setTab("anchors"); openPanel(); scrollRecord(state.activeAnchor, true); });
    $("start-annotation").addEventListener("click", () => { if (state.items.length) model.setView({ filter: "all" }); else setMode("annotate"); if (drawer.open) drawer.close(); });
    $("filter-scope").addEventListener("change", () => model.setView({ filter: $("filter-scope").value }));
    $("undo-withdraw").addEventListener("click", () => safe(() => { const item = model.restoreItem(); announce(item?.reference_ids.some((id) => !state.anchors.some((anchor) => anchor.id === id)) ? "已恢复原编号；存在失效A引用，请编辑解除后交还。" : "已恢复原编号及该条编辑草稿。"); }));
    function setTab(tab) { model.setView({ tab }); }
    const tabs = [$("tab-rectifications"), $("tab-anchors")];
    tabs.forEach((tab, index) => { tab.addEventListener("click", () => setTab(index ? "anchors" : "rectifications")); tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - index; tabs[next].focus(); setTab(next ? "anchors" : "rectifications");
    }); });
    function scrollRecord(id, anchor = false) {
      const el = document.getElementById(`${anchor ? "anchor" : "item"}-${id}`); if (!el) return;
      const scroller = document.querySelector(".review-panel-scroll"), r = el.getBoundingClientRect(), s = scroller.getBoundingClientRect();
      scroller.scrollTop += r.top - s.top - 12;
    }
    function scopeLabel(target) { return !target ? "未确认来源的动态元素" : target.scope === "global" ? "本轮整体" : state.pages.find((page) => page.path === target.page)?.label || "页面"; }
    async function locateRecord(entry, anchor) {
      await locate(entry.target); model.setView({ activeAnchor: anchor ? entry.id : null, activeItem: anchor ? null : entry.id, tab: anchor ? "anchors" : "rectifications", filter: "all" });
      scrollRecord(entry.id, anchor);
    }
    function renderLists() {
      $("rectification-count").textContent = state.items.length; $("feedback-count").textContent = state.items.length; $("anchor-count").textContent = state.anchors.length;
      $("page-rectification-count").textContent = state.items.filter((item) => item.target.scope === "page" && item.target.page === state.page).length || "";
      $("feedback-storage").textContent = state.storageMessage;
      tabs.forEach((tab, index) => { const selected = state.tab === (index ? "anchors" : "rectifications"); tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1; });
      $("rectification-tab-panel").hidden = state.tab !== "rectifications"; $("anchor-tab-panel").hidden = state.tab !== "anchors";
      $("filter-scope").value = state.filter;
      const list = $("rectification-list"); list.replaceChildren();
      const items = state.items.filter((item) => state.filter === "all" || (state.filter === "global" ? item.target.scope === "global" : item.target.scope === "global" || item.target.page === state.page));
      $("rectification-empty").hidden = items.length > 0; $("empty-description").textContent = state.items.length ? "此范围暂无整改，可恢复全部页面。" : "在批注模式点选元素，写下修改、新增或删除建议。";
      for (const item of items) {
        const row = make("article", undefined, "rectification-item"); row.id = `item-${item.id}`; row.classList.toggle("is-active", state.activeItem === item.id);
        const meta = make("div", undefined, "rectification-item-meta"); meta.append(make("span", number(item), `rectification-number ${item.operation}`), make("strong", operations[item.operation], `operation-label ${item.operation}`));
        row.append(meta, make("p", item.message || "删除原因未填写", "rectification-summary"), make("p", `${scopeLabel(item.target)} · ${item.target.scope === "node" ? model.recordFor(item.target)?.label || "原目标（当前状态不可见）" : item.target.scope === "page" ? "页面" : "整体"}`, "rectification-context"));
        if (item.reference_ids.length) { const refs = make("div", undefined, "item-references"); for (const id of item.reference_ids) {
          const anchor = state.anchors.find((entry) => entry.id === id); refs.append(button(anchor ? number(anchor, true) : "失效A引用", () => anchor ? safe(() => locateRecord(anchor, true)) : report(Error("请编辑解除失效A引用。"))));
        } row.append(refs); }
        const actions = make("div", undefined, "rectification-item-actions");
        actions.append(button("定位", () => safe(() => locateRecord(item, false))), button("编辑", () => safe(async () => { if (item.target.scope === "node") await locate(item.target); openEditor(item.target, item.id); })),
          button("撤回", () => safe(() => { model.withdrawItem(item.id); announce(`整改${number(item)}已撤回。`); })));
        row.append(actions);
        if (model.conflicts(item.target, item.operation, item.id).length) row.append(make("p", "同一目标存在删除与修改/新增建议，请交还时一起复核。", "item-conflict"));
        list.append(row);
      }
      $("withdraw-notice").hidden = !state.withdrawn; $("withdraw-message").textContent = state.withdrawn ? `已撤回 ${number(state.withdrawn.item)}` : "";
      const anchors = $("anchor-list"); anchors.replaceChildren();
      if (!state.anchors.length) anchors.append(make("p", "尚无定位标记。在批注模式选择元素后标记位置。", "anchor-section-help"));
      for (const anchor of state.anchors) {
        const row = make("article", undefined, "anchor-item"); row.id = `anchor-${anchor.id}`;
        const head = make("div", undefined, "anchor-item-heading"); head.append(button(number(anchor, true), () => safe(() => locateRecord(anchor, true))), make("span", scopeLabel(anchor.target)));
        const users = model.anchorUsers(anchor.id), protection = users.items.length || users.drafts.length;
        row.append(head, make("p", model.recordFor(anchor.target)?.text || "原来源目标（文字摘录不作为来源证明）"));
        if (protection) { const relations = make("div", undefined, "anchor-relations"); relations.append(make("span", `被${users.items.length}条整改、${users.drafts.length}份草稿引用`)); users.items.forEach((item) => relations.append(button(`整改${number(item)}`, () => safe(() => locateRecord(item, false))))); row.append(relations); }
        const remove = button("移除标记", () => safe(() => model.removeAnchor(anchor.id))); remove.disabled = Boolean(protection); row.append(remove);
        if (protection) row.append(make("p", "请先解除引用或撤回相关整改。", "anchor-protection")); anchors.append(row);
      }
      renderSelection();
    }
    function renderSelection() {
      const selection = state.selection, anchor = state.anchors.find((entry) => entry.id === state.activeAnchor), item = state.items.find((entry) => entry.id === state.activeItem);
      $("selection-tools").hidden = !selection; $("select-parent").hidden = !selection?.has_parent;
      $("remove-selected-anchor").hidden = !anchor; $("view-anchor-references").hidden = !anchor; $("withdraw-selected-item").hidden = !item;
      const users = anchor ? model.anchorUsers(anchor.id) : null, protectedAnchor = users && (users.items.length || users.drafts.length);
      $("remove-selected-anchor").disabled = Boolean(protectedAnchor);
      $("mark-location").disabled = !selection?.target;
      const reason = !selection?.target ? "此动态元素无可确认来源。可保留整改输入，再显式选择有来源的父层。" : protectedAnchor ? "此A标记被完成整改或活跃草稿引用，请先解除或撤回。" : "";
      $("selection-reference-reason").hidden = !reason; $("selection-reference-reason").textContent = reason;
    }
    function renderReferences() {
      const value = draft(); if (!value) return;
      const refs = $("reference-options"), chips = $("selected-references"); refs.replaceChildren(); chips.replaceChildren();
      const ids = [...new Set([...state.anchors.map((anchor) => anchor.id), ...value.reference_ids])];
      for (const id of ids) {
        const anchor = state.anchors.find((entry) => entry.id === id), label = make("label", undefined, "reference-option"), input = document.createElement("input");
        input.type = "checkbox"; input.value = id; input.checked = value.reference_ids.includes(id); input.id = `reference-${id}`; label.htmlFor = input.id;
        label.append(input, make("strong", anchor ? number(anchor, true) : "失效A引用"), make("span", anchor ? scopeLabel(anchor.target) : "请取消选中以解除失效引用"));
        input.addEventListener("change", () => { const selected = new Set(draft().reference_ids); input.checked ? selected.add(id) : selected.delete(id); model.updateDraft({ reference_ids: [...selected] }); renderReferences(); clearError(); }); refs.append(label);
        if (input.checked) chips.append(button(anchor ? number(anchor, true) : "解除失效A引用", () => {
          if (!anchor) { model.updateDraft({ reference_ids: draft().reference_ids.filter((value) => value !== id) }); renderReferences(); return; }
          // 定位离开前关闭时会保留同目标草稿，不因引用导航覆盖原表单。
          resumeDrawer.set(editor, false); editor.close(); safe(() => locateRecord(anchor, true));
        }, "reference-chip"));
      }
      $("selected-reference-count").textContent = value.reference_ids.length;
    }
    function clearError() { $("message-error").hidden = true; $("rectification-message").removeAttribute("aria-invalid"); }
    function showError(error) { $("message-error").textContent = error.message; $("message-error").hidden = false; $("rectification-message").setAttribute("aria-invalid", "true"); $("rectification-message").focus(); }
    function renderEditor() {
      const value = draft(); if (!value) return;
      const scope = value.target?.scope || "node";
      $("rectification-scope").textContent = scope === "global" ? "本轮整体意见" : scope === "page" ? "页面整改" : "节点整改";
      $("rectification-title").textContent = value.editing ? "编辑整改" : "添加整改";
      $("operation-add-label").hidden = scope === "global"; $("operation-delete-label").hidden = scope !== "node";
      for (const radio of document.querySelectorAll('input[name="operation"]')) { radio.checked = radio.value === value.operation; radio.disabled = (radio.value === "delete" && scope !== "node") || (radio.value === "add" && scope === "global"); }
      $("rectification-message").value = value.message; $("comparison-after").value = value.after_text; $("original-excerpt").value = value.excerpt;
      const source = value.target ? model.recordFor(value.target) : state.selection;
      $("target-relations").textContent = `交互说明：${source?.interaction_text || "未声明"}；接口引用：${source?.interface_refs.join("、") || "未声明"}。`;
      $("node-extra").hidden = scope !== "node"; $("comparison-field").hidden = value.operation !== "modify"; $("additional-details").hidden = scope !== "node";
      $("message-field-label").textContent = value.operation === "delete" ? "删除原因" : value.operation === "add" ? "新增内容" : "期望效果";
      $("message-required").textContent = value.operation === "delete" ? "可选" : "必填"; $("rectification-message").required = value.operation !== "delete";
      $("conflict-warning").hidden = !model.conflicts(value.target, value.operation, value.editing).length;
      $("conflict-warning").textContent = "同一目标已有删除与修改/新增建议，允许保留，请一起复核。";
      renderReferences(); clearError();
    }
    function openEditor(target, itemId = null) { model.openEditor(target, itemId); renderEditor(); if (!editor.open) showModal(editor); $("rectification-message").focus(); }
    $("rectification-message").addEventListener("input", () => { model.updateDraft({ message: $("rectification-message").value }); clearError(); });
    $("comparison-after").addEventListener("input", () => { model.updateDraft({ after_text: $("comparison-after").value }); clearError(); });
    for (const radio of document.querySelectorAll('input[name="operation"]')) radio.addEventListener("change", () => { model.updateDraft({ operation: radio.value }); renderEditor(); });
    for (const id of ["rectification-close", "rectification-cancel"]) $(id).addEventListener("click", () => editor.close());
    $("rectification-form").addEventListener("submit", async (event) => {
      event.preventDefault(); if (saving) return;
      const key = state.editor, value = draft(); if (!value) return;
      saving = true; $("complete-rectification").disabled = true; $("draft-state").textContent = "正在确认目标来源……";
      try {
        // 完成前重新走真实child来源解析，不能把首次目录或局部文字冒称当前来源。
        // 引用可以跨页，验证也会逐页确认；任一失败仍留在同一草稿且不分配编号。
        await verifySources([value.target, ...value.reference_ids.map((id) => state.anchors.find((anchor) => anchor.id === id)?.target)]);
        if (!editor.open || state.editor !== key) return;
        const [item] = model.completeEditor(); editor.close(); model.setView({ activeItem: item.id, activeAnchor: null }); scrollRecord(item.id); announce(`整改 ${number(item)} 已完成，编号保持稳定。`);
      } catch (error) { if (editor.open && state.editor === key) showError(error); }
      finally { saving = false; $("complete-rectification").disabled = false; $("draft-state").textContent = "草稿自动保留"; }
    });
    editor.addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); $("rectification-form").requestSubmit(); } });
    function allTargets(includeDrafts = false) { return [...state.items, ...state.anchors, ...(includeDrafts ? model.activeDrafts().map(([, value]) => value) : [])].map((entry) => entry.target); }
    function exportText() {
      return formatExport(model.exportPayload(), scopeLabel);
    }
    function counts() { $("export-saved-count").textContent = state.items.length; $("export-anchor-count").textContent = state.anchors.length; $("export-draft-count").textContent = model.activeDrafts().length; }
    function enableExport(enabled) { for (const id of ["export-copy", "select-export", "download-feedback"]) $(id).disabled = !enabled; $("export-save-copy").disabled = busy; }
    function exportResult(message, failed = false) { $("export-result").textContent = message; $("export-result").classList.toggle("is-error", failed); }
    async function refreshExport() {
      const epoch = ++exportEpoch; backup = ""; $("export-text").value = ""; counts(); enableExport(false);
      const unfinished = model.activeDrafts().length > 0; $("export-save-copy").hidden = !unfinished; $("export-copy").hidden = unfinished;
      if (unfinished) { exportResult("仍有未完成草稿。可验证全部草稿后一起完成；任一失败都不会部分交还。"); return; }
      try { await verifySources(allTargets()); if (epoch !== exportEpoch || !exporter.open) return; backup = exportText(); $("export-text").value = backup; enableExport(true); exportResult("已核对目标，可以复制或下载反馈；之后仍需粘贴并发送。"); }
      catch (error) { if (epoch === exportEpoch) { enableExport(false); exportResult(error.message, true); } }
    }
    $("copy-feedback").addEventListener("click", () => { showModal(exporter); refreshExport(); });
    for (const id of ["export-close", "export-cancel"]) $(id).addEventListener("click", () => exporter.close());
    async function copyFeedback(finishDrafts) {
      if (busy) return; busy = true; const epoch = ++exportEpoch;
      // 新交还必须重新生成全文；来源或字节校验失败时不能把上一次backup冒充本次结果。
      backup = ""; $("export-text").value = ""; enableExport(false); exportResult("正在核对来源并准备复制……");
      try {
        await verifySources(allTargets(finishDrafts));
        if (epoch !== exportEpoch || !exporter.open) return;
        if (finishDrafts) model.completeAll((payload) => formatExport(payload, scopeLabel));
        backup = exportText(); $("export-text").value = backup; counts(); $("export-save-copy").hidden = true; $("export-copy").hidden = false;
        await navigator.clipboard.writeText(backup);
        if (epoch === exportEpoch) exportResult("反馈已复制。请粘贴到当前对话后发送。");
      } catch (error) {
        if (epoch !== exportEpoch) return;
        if (error.draftKey) {
          // 所有草稿验证失败时退出交还、回到该草稿。state尚未分配任何新编号。
          resumeDrawer.set(exporter, false); exporter.close(); model.resumeEditor(error.draftKey); renderEditor(); showModal(editor); showError(error); return;
        }
        exportResult(backup ? "自动复制失败，输入已保留；请使用下方手动复制或下载备用。" : error.message, true);
        if (backup) { $("export-backup-toggle").parentElement.open = true; $("export-text").focus(); }
      } finally { busy = false; if (exporter.open) enableExport(Boolean(backup) && !model.activeDrafts().length); }
    }
    $("export-copy").addEventListener("click", () => copyFeedback(false)); $("export-save-copy").addEventListener("click", () => copyFeedback(true));
    $("select-export").addEventListener("click", () => { if (!backup) return; $("export-text").focus(); $("export-text").select(); exportResult("已选中全部文字，请按 Ctrl / Cmd + C 复制。"); });
    $("download-feedback").addEventListener("click", async () => {
      if (busy || !backup) return;
      busy = true; const epoch = ++exportEpoch; let url;
      backup = ""; $("export-text").value = ""; enableExport(false);
      try {
        await verifySources(allTargets()); if (!exporter.open || epoch !== exportEpoch) return;
        const value = exportText(); backup = value; $("export-text").value = value;
        url = URL.createObjectURL(new Blob([value], { type: "text/markdown;charset=utf-8" }));
        const link = make("a"); link.href = url; link.download = "prototype-feedback.md"; link.click(); exportResult("已请求下载反馈 .md，请确认浏览器下载结果。");
      } catch (error) { if (epoch === exportEpoch) exportResult(error.message || "下载未能启动，请手动复制；输入保留。", true); }
      finally {
        if (url) setTimeout(() => URL.revokeObjectURL(url), 1000);
        busy = false; if (exporter.open && epoch === exportEpoch) enableExport(Boolean(backup) && !model.activeDrafts().length);
      }
    });
    $("target-directory").addEventListener("change", () => { const key = $("target-directory").value; if (key) { setMode("annotate"); send("select", { key }); } });
    model.subscribe(renderLists); renderLists();
    return Object.freeze({
      get activeAnchor() { return state.activeAnchor; }, get activeItem() { return state.activeItem; },
      catalog() { const select = $("target-directory"), old = select.value; select.replaceChildren(new Option("选择设计稿中的元素", "")); for (const record of model.catalog()) select.add(new Option(record.label, record.key)); if (model.catalog().some((record) => record.key === old)) select.value = old; },
      selected(bounds) {
        model.setView({ activeAnchor: null, activeItem: null }); renderSelection();
        if (!bounds || ![bounds.x, bounds.y, bounds.w, bounds.h].every(Number.isFinite)) return;
        const cam = state.cameras[state.page], vp = $("canvas-viewport"); if (!cam) return;
        const toolbar = $("selection-tools"); toolbar.style.left = `${Math.max(14, Math.min(vp.clientWidth - toolbar.offsetWidth - 14, cam.x + bounds.x * cam.k))}px`;
        toolbar.style.top = `${Math.max(70, Math.min(vp.clientHeight - toolbar.offsetHeight - 60, cam.y + (bounds.y + bounds.h) * cam.k + 12))}px`;
        if (!state.selection?.target) announce("当前动态元素无来源；整改输入可以保留，请显式选择有来源的父层。");
      },
      selectRecord(kind, id) {
        const entries = kind === "anchor" ? state.anchors : state.items, entry = entries.find((value) => value.id === id); if (!entry || entry.target.page !== state.page) return;
        model.setView({ activeAnchor: kind === "anchor" ? id : null, activeItem: kind === "item" ? id : null, tab: kind === "anchor" ? "anchors" : "rectifications", filter: "all" }); openPanel(); scrollRecord(id, kind === "anchor");
      },
      contract(sections) {
        if (!Array.isArray(sections) || sections.length !== 5 || !sections.every((entry, index) => entry?.name === ["purpose", "navigation", "interactions", "states", "exceptions"][index] && typeof entry.text === "string" && entry.text.length <= 65536)) return;
        const content = $("page-contract-content"); content.replaceChildren();
        for (const entry of sections) { const section = make("section"), heading = make("h2", ({ purpose: "页面职责", navigation: "导航", interactions: "交互", states: "状态与恢复", exceptions: "例外与实现边界" })[entry.name]); section.append(heading, make("p", entry.text)); content.append(section); }
      },
    });
  }
  window.PrototypeFeedback = Object.freeze({ create, formatExport });
})();
