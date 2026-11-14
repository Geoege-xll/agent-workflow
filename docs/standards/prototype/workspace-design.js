/* 实质抽取并适配 show-me-you-want-skill 的相机 applyCam/fitCam/zoomAt/wirePanZoom、
* 编号覆盖层/定位及意见呈现结构。固定来源：
* https://github.com/nishuzumi/show-me-you-want-skill/blob/1f6d786dddd36a33b002ce8afff70d43d08a9460/skills/smyw/assets/runtime.js
* 保留许可全文如下；本页移除了spec渲染、组件拖拽、结构patch及上游批准流程。
*
* MIT License
*
* Copyright (c) 2026 box
*
* Permission is hereby granted, free of charge, to any person obtaining a copy
* of this software and associated documentation files (the "Software"), to deal
* in the Software without restriction, including without limitation the rights
* to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
* copies of the Software, and to permit persons to whom the Software is
* furnished to do so, subject to the following conditions:
*
* The above copyright notice and this permission notice shall be included in all
* copies or substantial portions of the Software.
*
* THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
* IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
* FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
* AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
* LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
* OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
* SOFTWARE.
*/
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const root = $("review-workspace");
  if (!root) return;
  const pages = {
    preferences: "调用偏好页", native: "原生定义页"
  };
  const operations = {
    modify: "修改", add: "新增内容", delete: "删除建议"
  };
  const narrow = matchMedia("(max-width: 900px)");
  const editDialog = $("rectification-dialog"), exporter = $("export-dialog"), drawer = $("panel-drawer");
  const panel = $("review-panel"), nav = $("navigation-drawer");
  // 唯一状态：没有旧changes/双页签/侧栏编辑器，也没有第二份spec页面模型。
  // sourceStamp仅用于演示绑定概念，不是生产校验摘要或真实review_id。
  const state = {
    page: "preferences", mode: "browse", panelTab: "rectifications", cameras: {
      preferences: null, native: null
    },
    selected: {
      preferences: null, native: null
    }, activeItemId: null, activeAnchorId: null,
    anchors: [], items: [], nextAnchor: 1, nextRectification: 1,
    drafts: new Map(), modal: null, withdrawn: null, restorePanelFor: null,
    showRectifications: true, showAnchors: true, sourceStamp: "demo-current-html", scenario: "normal",
    lastMessage: "", space: false, panMoved: false, exportText: ""
  };
  const records = new Map();
  const blank = () => ({
    operation: "modify", message: "", comparison: "", req_ids: [], reference_ids: []
  });
  const serialNumber = (number) => String(number).padStart(2, "0");
  // ── 一、HTML装配/命中目录：源ID优先，匿名节点只产生明确的demo_locator。 ──
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function announce(message) {
    // 同一状态重复出现时加不可读空格，避免部分读屏器吞掉相同公告。
    const spoken = message === state.lastMessage ? message + "\u00a0" : message;
    state.lastMessage = spoken;
    $("review-status").textContent = spoken;
  }
  function resolveNode(key) {
    return records.get(key)?.node || $(key);
  }
  function isVisible(node) {
    return !node.closest("[hidden]") && node.getClientRects().length > 0 && getComputedStyle(node).visibility !== "hidden" && node.getBoundingClientRect().width > 0 && node.getBoundingClientRect().height > 0;
  }
  function indexDesigns() {
    document.querySelectorAll("[data-sample-page]").forEach((screen) => {
      const page = screen.dataset.samplePage;
      screen.querySelectorAll("*").forEach((node) => {
        if (node.matches("script,style,option,path,[data-review-ui],.design-deletion-anchor") || node.closest("[data-review-ui]")) return;
        if (!node.textContent.trim() && !node.matches("input,select,textarea,svg,img") && !node.getAttribute("aria-label")) return;
        let key = node.id;
        if (!key) {
          const path = [];
          let current = node;
          while (current && current !== screen) {
            path.unshift(current.tagName.toLowerCase() + ":" + (Array.from(current.parentElement.children).indexOf(current) + 1));
            current = current.parentElement;
          }
          key = "demo:" + page + ":" + path.join("/");
        }
        const label = node.id && document.querySelector('label[for="' + node.id + '"]');
        const name = node.getAttribute("aria-label") || (label && label.textContent.trim()) || node.textContent.trim().replace(/\s+/g, " ").slice(0, 52) || node.tagName.toLowerCase();
        node.dataset.reviewKey = key;
        records.set(key, {
          node, page, name, sourceId: node.id || null
        });
      });
    });
  }
  function refreshDirectory() {
    const directory = $("target-directory");
    directory.replaceChildren(new Option("选择设计稿中的元素", ""));
    records.forEach((record, key) => {
      if (record.page === state.page && isVisible(record.node)) directory.add(new Option(record.name + " · " + record.node.tagName.toLowerCase(), key));
    });
  }
  function parentRecord(key) {
    const node = resolveNode(key);
    let parent = node?.parentElement;
    while (parent && !parent.matches("[data-sample-page]")) {
      if (parent.dataset.reviewKey) return records.get(parent.dataset.reviewKey);
      parent = parent.parentElement;
    }
    return null;
  }
  // ── 二、固定上游相机实质复用：工具在视口，不在world；定位保留k。 ──
  function vpEl() {
    return $("canvas-viewport");
  }
  function worldEl() {
    return $("canvas-world");
  }
  function applyCam() {
    const w = worldEl(), c = state.cameras[state.page];
    if (!w || !c) return;
    w.style.transform = 'translate(' + c.x + 'px,' + c.y + 'px) scale(' + c.k + ')';
    $("canvas-zoom-reset").textContent = Math.round(c.k * 100) + '%';
    renderOverlays();
  }
  function fitCam() {
    const vp = vpEl(), w = worldEl(), r = vp.getBoundingClientRect();
    const W = w.offsetWidth, H = w.offsetHeight;
    if (!W || !r.width) return;
    // 根据浮动工具实际高度留出可读空间，窄屏换行后也不遮住稿件顶部。
    const topInset = root.querySelector(".canvas-floating-controls").offsetHeight + 28;
    const k = Math.max(0.08, Math.min(1, (r.width - 48) / W, (r.height - topInset - 24) / H));
    state.cameras[state.page] = {
      k, x: Math.max(24, (r.width - W * k) / 2), y: Math.max(topInset, topInset + (r.height - topInset - H * k) / 2)
    };
    applyCam();
  }
  function zoomAt(f, mx, my) {
    const c = state.cameras[state.page];
    if (!c) return;
    const k = Math.max(0.08, Math.min(3, c.k * f));
    c.x = mx - (mx - c.x) * (k / c.k);
    c.y = my - (my - c.y) * (k / c.k);
    c.k = k;
    applyCam();
  }
  function focusEl(node) {
    const c = state.cameras[state.page], vp = vpEl();
    if (!node || !c) return;
    const r = node.getBoundingClientRect(), wr = worldEl().getBoundingClientRect(), vr = vp.getBoundingClientRect();
    const lx = (r.left - wr.left) / c.k, ly = (r.top - wr.top) / c.k;
    // 上游原实现会适配目标大小，这里保留当前k，仅将目标中心移入可见视口。
    c.x = vr.width / 2 - (lx + r.width / c.k / 2) * c.k;
    c.y = vr.height / 2 - (ly + r.height / c.k / 2) * c.k;
    applyCam();
  }
  function wirePanZoom(vp) {
    let pan = null;
    vp.addEventListener('pointerdown', (event) => {
      if (!state.cameras[state.page] || event.target.closest('[data-review-ui]')) return;
      const inDesign = Boolean(event.target.closest('[data-sample-page]'));
      const ok = event.button === 1 || (event.button === 0 && (state.space || !inDesign));
      if (!ok) return;
      const c = state.cameras[state.page];
      pan = {
        x: event.clientX, y: event.clientY, cx: c.x, cy: c.y, moved: false, id: event.pointerId
      };
      event.preventDefault();
      vp.setPointerCapture(event.pointerId);
    });
    vp.addEventListener('pointermove', (event) => {
      if (!pan || event.pointerId !== pan.id) return;
      const dx = event.clientX - pan.x, dy = event.clientY - pan.y;
      if (!pan.moved && Math.abs(dx) + Math.abs(dy) < 5) return;
      pan.moved = true;
      vp.classList.add('panning');
      const c = state.cameras[state.page];
      c.x = pan.cx + dx;
      c.y = pan.cy + dy;
      applyCam();
    });
    const end = (event) => {
      if (!pan || event.pointerId !== pan.id) return;
      if (pan.moved) {
        state.panMoved = true;
        setTimeout(() => {
          state.panMoved = false;
        }, 0);
      }
      pan = null;
      vp.classList.remove('panning');
    };
    vp.addEventListener('pointerup', end);
    vp.addEventListener('pointercancel', end);
    vp.addEventListener('wheel', (event) => {
      const c = state.cameras[state.page];
      if (!c) return;
      if (event.target.closest('[data-review-ui]')) return;
      // 浏览时先交还原生控件和稿件的真实滚动容器，不能用相机抢列表/正文滚轮。
      if (state.mode === 'browse' && !event.ctrlKey && !event.metaKey && !state.space) {
        if (event.target.closest('input,select,textarea,button,a')) return;
        let scrollTarget = event.target;
        while (scrollTarget && scrollTarget !== vp) {
          const style = getComputedStyle(scrollTarget);
          const scrollY = /(auto|scroll)/.test(style.overflowY) && scrollTarget.scrollHeight > scrollTarget.clientHeight;
          const scrollX = /(auto|scroll)/.test(style.overflowX) && scrollTarget.scrollWidth > scrollTarget.clientWidth;
          if (scrollY || scrollX) return;
          scrollTarget = scrollTarget.parentElement;
        }
      }
      // 稿件内普通滚轮始终属于业务内容；相机平移只接受画布空白或显式Space手势。
      // Ctrl/Cmd滚轮是明确缩放，可在稿件上以指针为中心执行。
      if (!event.ctrlKey && !event.metaKey && !state.space && event.target.closest("[data-sample-page]")) return;
      event.preventDefault();
      const r = vp.getBoundingClientRect();
      if (event.ctrlKey || event.metaKey) zoomAt(Math.exp(-event.deltaY * 0.0022), event.clientX - r.left, event.clientY - r.top);
      else {
        c.x -= event.shiftKey ? event.deltaY : event.deltaX;
        c.y -= event.shiftKey ? 0 : event.deltaY;
        applyCam();
      }
    }, {
      passive: false
    });
  }
  function bounds(node) {
    const k = state.cameras[state.page]?.k || 1, r = node.getBoundingClientRect(), wr = worldEl().getBoundingClientRect();
    return {
      x: (r.left - wr.left) / k, y: (r.top - wr.top) / k, w: r.width / k, h: r.height / k
    };
  }
  function place(node, b) {
    Object.assign(node.style, {
      left: b.x + "px", top: b.y + "px", width: b.w + "px", height: b.h + "px"
    });
  }
  function nodeTarget(key) {
    return {
      scope: "node", page: records.get(key)?.page || state.page, target_id: key
    };
  }
  function targetKey(target) {
    return target.scope === "global" ? "global" : target.scope + ":" + target.page + ":" + (target.target_id || "");
  }
  function targetName(target) {
    return target.scope === "global" ? "本轮整体" : target.scope === "page" ? pages[target.page] : records.get(target.target_id)?.name || "失配的原目标";
  }
  function sourceProblem(target, stamp = state.sourceStamp) {
    if (state.scenario === "stale" || stamp !== state.sourceStamp) return "演示来源已过期，原意见保留，请重新准备来源；不会自动重绑。";
    if (target.scope === "node") {
      const record = records.get(target.target_id);
      if (!record || record.page !== target.page || !record.node.isConnected) return "原目标已失配，保留输入，不自动换成其他元素。";
    }
    return "";
  }
  function switchPage(page, announceChange = true) {
    if (!pages[page]) return;
    stashModal();
    state.page = page;
    document.querySelectorAll("[data-sample-page]").forEach((screen) => {
      screen.hidden = screen.dataset.samplePage !== page;
    });
    Object.keys(pages).forEach((key) => {
      if (key === page) $("page-" + key).setAttribute("aria-current", "page");
      else $("page-" + key).removeAttribute("aria-current");
    });
    $("current-page-title").textContent = pages[page];
    refreshDirectory();
    renderAll();
    if (!state.cameras[page]) fitCam();
    else applyCam();
    history.replaceState(null, "", "#" + page);
    if (announceChange) announce("已切到" + pages[page] + "，视口和目标草稿分别保留。" );
  }
  function setMode(mode) {
    state.mode = mode;
    $("mode-" + mode).checked = true;
    root.classList.toggle("is-annotating", mode === "annotate");
    $("hover-outline").hidden = true;
    renderSelectionTools();
    announce(mode === "annotate" ? "批注模式：点选目标后可标记位置或添加整改。" : "浏览模式：原生下拉、输入和页面导航可以操作。" );
  }
  function selectNode(key, focusTools = false) {
    const record = records.get(key);
    if (!record || !isVisible(record.node)) return;
    state.selected[state.page] = key;
    state.activeItemId = null;
    state.activeAnchorId = null;
    $("target-directory").value = key;
    renderOverlays();
    announce("已选择：" + record.name + "。标记位置可选，也可直接添加整改。" );
    if (focusTools) $("add-rectification").focus({
      preventScroll: true
    });
  }
  function renderSelectionTools() {
    const node = resolveNode(state.selected[state.page]);
    const activeTarget = anchorById(state.activeAnchorId)?.target || state.items.find((entry) => entry.id === state.activeItemId)?.target;
    const activeHere = activeTarget?.page === state.page && activeTarget?.target_id === state.selected[state.page];
    const visible = (state.mode === "annotate" || activeHere) && node && isVisible(node);
    const bar = $("selection-tools");
    bar.hidden = !visible;
    if (!visible) return;
    const parent = parentRecord(state.selected[state.page]);
    const anchor = anchorById(state.activeAnchorId);
    const item = state.items.find((entry) => entry.id === state.activeItemId);
    const markerSelected = anchor && !anchor.removed && anchor.target.target_id === state.selected[state.page];
    const itemSelected = item && item.target.target_id === state.selected[state.page];
    // 点编号后的就地操作复用既有删除/撤回职责，不引入另一套状态或删除稿件行为。
    $("select-parent").hidden = !parent || state.mode !== "annotate";
    $("mark-location").hidden = state.mode !== "annotate";
    $("add-rectification").hidden = state.mode !== "annotate";
    $("remove-selected-anchor").hidden = !markerSelected;
    $("withdraw-selected-item").hidden = !itemSelected;
    const refs = markerSelected ? markerReferences(anchor.id) : { items: [], drafts: [] };
    const protectedMarker = Boolean(refs.items.length || refs.drafts.length);
    $("remove-selected-anchor").disabled = protectedMarker;
    $("view-anchor-references").hidden = !protectedMarker;
    $("selection-reference-reason").hidden = !protectedMarker;
    $("selection-reference-reason").textContent = protectedMarker ? "被 " + refs.items.length + " 条整改、" + refs.drafts.length + " 份草稿引用；先解除引用或撤回相关整改。" : "";
    const r = node.getBoundingClientRect(), vr = vpEl().getBoundingClientRect();
    const width = Math.min(540, vr.width - 24);
    bar.style.maxWidth = width + "px";
    toolbarRefreshers.forEach((refresh) => refresh());
    const height = bar.offsetHeight || 76;
    const left = Math.max(12, Math.min(r.left - vr.left, vr.width - bar.offsetWidth - 12));
    const above = r.top - vr.top - height - 10;
    const minTop = root.querySelector(".canvas-floating-controls").offsetHeight + 32;
    const top = Math.max(12, Math.min(above >= minTop ? above : Math.max(minTop, r.bottom - vr.top + 10), vr.height - height - 12));
    bar.style.left = left + "px";
    bar.style.top = top + "px";
  }
  // ── 三、整改与独立A定位标记：完成才编号，两序列永不复用。 ──
  function activeAnchors() {
    return state.anchors.filter((anchor) => !anchor.removed);
  }
  function anchorById(id) {
    return state.anchors.find((anchor) => anchor.id === id);
  }
  function anchorLabel(id) {
    return anchorById(id)?.label || "失配标记";
  }
  function markerReferences(id) {
    const items = state.items.filter((item) => item.reference_ids.includes(id));
    const drafts = Array.from(state.drafts.values()).filter((draft) => draft.fields.reference_ids.includes(id));
    return {
      items, drafts
    };
  }
  function markLocation() {
    const key = state.selected[state.page];
    if (!key) return;
    const target = nodeTarget(key), problem = sourceProblem(target);
    if (problem) {
      announce(problem);
      return;
    }
    let anchor = activeAnchors().find((entry) => targetKey(entry.target) === targetKey(target));
    if (!anchor) {
      const number = state.nextAnchor++;
      anchor = {
        id: "anchor-" + number, number, label: "A" + serialNumber(number), target, source_stamp: state.sourceStamp, removed: false
      };
      state.anchors.push(anchor);
      announce("已标记位置 " + anchor.label + "；尚未创建整改。" );
    } else announce("此位置已有 " + anchor.label + "，已选中，没有重复创建。" );
    state.activeAnchorId = anchor.id;
    state.activeItemId = null;
    renderAll();
  }
  function removeAnchor(id) {
    const anchor = anchorById(id);
    if (!anchor || anchor.removed) return;
    const references = markerReferences(id);
    if (references.items.length || references.drafts.length) {
      announce(anchor.label + "仍被整改或草稿引用，请先解除引用或撤回相关整改。" );
      return;
    }
    anchor.removed = true;
    if (state.activeAnchorId === id) state.activeAnchorId = null;
    renderAll();
    announce("已移除" + anchor.label + "，编号不会复用。" );
  }
  function locateTarget(target, stamp) {
    const problem = sourceProblem(target, stamp);
    if (problem) {
      announce(problem);
      return false;
    }
    if (target.page && target.page !== state.page) switchPage(target.page, false);
    if (target.scope === "node") {
      const node = resolveNode(target.target_id);
      if (!isVisible(node)) {
        announce("原目标当前被样例隐藏；保留关联，不自动换目标。" );
        return false;
      }
      state.selected[state.page] = target.target_id;
      focusEl(node);
    } else if (target.scope === "page") focusEl($("sample-" + state.page));
    renderOverlays();
    return true;
  }
  function locateAnchor(id) {
    const anchor = anchorById(id);
    if (!anchor || anchor.removed) {
      announce("定位标记已移除；引用保留为失效，不自动重绑。" );
      return;
    }
    if (!locateTarget(anchor.target, anchor.source_stamp)) return;
    state.activeAnchorId = id;
    state.activeItemId = null;
    setPanelTab("anchors");
    renderOverlays();
    ensureAnchorVisible(id);
    announce("已定位" + anchor.label + "：" + targetName(anchor.target));
  }
  function conflictItems(candidate) {
    if (candidate.target.scope !== "node") return [];
    return state.items.filter((item) => item.id !== candidate.id && targetKey(item.target) === targetKey(candidate.target) && ((item.operation === "delete") !== (candidate.operation === "delete")));
  }
  function validateFields(target, fields, stamp, forSave = true) {
    const problem = sourceProblem(target, stamp);
    if (problem) return problem;
    if (forSave && state.scenario === "save-error") return "完成失败，输入仍在；切回正常演示场景后可重试。";
    if (target.scope !== "node" && fields.operation === "delete") return "页面与本轮整体不支持删除操作。";
    if (target.scope === "global" && fields.operation !== "modify") return "本轮整体仅记录多页面调整意见。";
    if (fields.operation !== "delete" && !fields.message.trim()) return fields.operation === "add" ? "请填写新增内容，再完成整改。" : "请填写期望效果，再完成整改。";
    if (fields.message.length > 4000 || fields.comparison.length > 4000) return "正文与建议文字各最多4000字符。";
    const bad = fields.reference_ids.find((id) => !anchorById(id) || anchorById(id).removed || sourceProblem(anchorById(id).target, anchorById(id).source_stamp));
    if (bad) return anchorLabel(bad) + "已移除或失配，请取消该引用后再完成；原输入保留。";
    return "";
  }
  function commitFields(target, fields, editId, key, stamp) {
    const original = state.items.find((item) => item.id === editId);
    const number = original ? original.number : state.nextRectification++;
    const item = {
      id: original ? original.id : "rectification-" + number, number, target: {
        ...target
      }, ...fields,
      // 当前虚构稿没有真实业务需求映射；保留接口，保存时明确为空，不借用评审工具REQ。
      req_ids: [],
      comparison: target.scope === "node" && fields.operation === "modify" ? fields.comparison : "", source_stamp: stamp
    };
    if (original) state.items = state.items.map((entry) => entry.id === original.id ? item : entry);
    else state.items.push(item);
    state.drafts.delete(key);
    state.activeItemId = item.id;
    state.activeAnchorId = null;
    return item;
  }
  // ── 四、唯一模态与目标草稿：关闭暂存，不创建空条目或占用编号。 ──
  function itemFields(item) {
    return item ? {
      operation: item.operation, message: item.message, comparison: item.comparison, req_ids: [], reference_ids: item.reference_ids.slice()
    } : blank();
  }
  function readFields() {
    return {
      operation: root.querySelector('input[name="operation"]:checked').value,
      message: $("rectification-message").value,
      comparison: $("comparison-after").value,
      // 去掉手选字段后仍保留协议键；本演示没有可靠业务映射，不自动推断关联。
      req_ids: [],
      reference_ids: Array.from($("reference-options").querySelectorAll('input:checked'), (input) => input.value)
    };
  }
  function modalKey() {
    return state.modal.editId ? "edit:" + state.modal.editId : targetKey(state.modal.target);
  }
  function stashModal() {
    if (!state.modal) return;
    const fields = readFields(), original = state.items.find((item) => item.id === state.modal.editId);
    if (JSON.stringify(fields) === JSON.stringify(itemFields(original))) state.drafts.delete(modalKey());
    else state.drafts.set(modalKey(), {
      target: {
        ...state.modal.target
      }, editId: state.modal.editId, fields, source_stamp: state.modal.source_stamp
    });
    $("draft-state").textContent = state.drafts.has(modalKey()) ? "未完成 · 草稿已保留" : "草稿自动保留";
  }
  function prepareEdit(target, editId = null) {
    stashModal();
    state.restorePanelFor = narrow.matches && drawer.open ? "edit" : null;
    if (drawer.open) drawer.close();
    const original = state.items.find((item) => item.id === editId);
    const key = editId ? "edit:" + editId : targetKey(target), draft = state.drafts.get(key);
    const fields = draft ? draft.fields : itemFields(original);
    state.modal = {
      target: {
        ...target
      }, editId, source_stamp: draft?.source_stamp || original?.source_stamp || state.sourceStamp
    };
    $("rectification-title").textContent = original ? "编辑整改 " + serialNumber(original.number) : target.scope === "global" ? "本轮整体意见" : target.scope === "page" ? "添加页面整改" : "添加整改";
    $("rectification-scope").textContent = target.scope === "node" ? "节点整改 · " + pages[target.page] : target.scope === "page" ? "页面整改" : "本轮多个页面";
    $("operation-add-label").hidden = target.scope === "global";
    $("operation-delete-label").hidden = target.scope !== "node";
    root.querySelector('input[name="operation"][value="' + fields.operation + '"]').checked = true;
    $("rectification-message").value = fields.message;
    $("comparison-after").value = fields.comparison;
    $("node-extra").hidden = target.scope !== "node";
    $("original-excerpt").value = target.scope === "node" ? resolveNode(target.target_id)?.innerText?.trim().slice(0, 4000) || targetName(target) : "";
    $("complete-rectification").textContent = original ? "完成修改" : "完成整改";
    clearError();
    renderReferenceOptions(fields.reference_ids);
    updateOperationUI();
    renderSelectedReferences();
    updateCounts();
    $("draft-state").textContent = draft ? "已恢复未完成草稿" : "草稿自动保留";
    requestAnimationFrame(() => {
      if (editDialog.open) $("rectification-message").focus();
    });
  }
  function updateOperationUI() {
    if (!state.modal) return;
    const operation = root.querySelector('input[name="operation"]:checked').value;
    $("message-field-label").textContent = operation === "modify" ? "期望效果" : operation === "add" ? "新增内容" : "删除原因";
    $("message-required").textContent = operation === "delete" ? "可选" : "必填";
    $("rectification-message").required = operation !== "delete";
    $("comparison-field").hidden = operation !== "modify";
    const conflicts = conflictItems({
      id: state.modal.editId, target: state.modal.target, operation
    });
    $("conflict-warning").hidden = !conflicts.length;
    $("conflict-warning").textContent = conflicts.length ? "潜在冲突：同一目标已有 " + conflicts.map((item) => serialNumber(item.number) + " " + operations[item.operation]).join("、") + "。可以继续记录，需交还后一起取舍。" : "";
  }
  function clearError() {
    $("message-error").hidden = true;
    $("rectification-message").removeAttribute("aria-invalid");
  }
  function showError(message) {
    $("message-error").textContent = message;
    $("message-error").hidden = false;
    $("rectification-message").setAttribute("aria-invalid", "true");
    $("rectification-message").focus();
    announce(message);
  }
  function completeModal() {
    if (!state.modal) return;
    stashModal();
    const fields = readFields(), modal = state.modal;
    const problem = validateFields(modal.target, fields, modal.source_stamp);
    if (problem) {
      showError(problem);
      return;
    }
    const item = commitFields(modal.target, fields, modal.editId, modalKey(), modal.source_stamp);
    // 完成后恢复该条的可见范围，只滚动右栏；不移动整页或重置相机。
    $("filter-scope").value = item.target.scope === "global" ? "global" : "current";

    state.modal = null;
    setPanelTab("rectifications");
    renderAll();
    editDialog.close();
    ensureItemVisible(item.id);
    announce("已完成整改 " + serialNumber(item.number) + "，" + operations[item.operation] + "仅作为建议，设计稿没有改变。" );
  }
  function renderReferenceOptions(selected) {
    const container = $("reference-options");
    container.replaceChildren();
    clearContracts("reference-options");
    const entries = state.anchors.filter((anchor) => !anchor.removed || selected.includes(anchor.id));
    if (!entries.length) {
      container.append(el("p", "review-field-help", "还没有定位标记。可先取消并保留草稿，在画布标记位置后回来引用。"));
      return;
    }
    entries.forEach((anchor) => {
      const label = el("label", "reference-option"), input = document.createElement("input");
      input.type = "checkbox";
      input.id = "reference-" + anchor.id;
      input.value = anchor.id;
      input.checked = selected.includes(anchor.id);
      input.dataset.referenceOption = anchor.id;
      label.append(input, el("strong", "", anchor.label), el("span", "", anchor.removed ? "已移除 · 取消引用以继续" : targetName(anchor.target) + " · " + pages[anchor.target.page]));
      container.append(label);
      dynamicContract(input.id, "REQ-811：选择/取消" + anchor.label + "结构化引用，单条可多选；正文不解析为HTML，引用可定位。已移除引用保留为失效，需取消后完成。", "reference-options");
    });
  }
  function renderSelectedReferences() {
    clearContracts("reference-chips");
    const container = $("selected-references");
    container.replaceChildren();
    if (!state.modal) return;
    const refs = readFields().reference_ids;
    $("selected-reference-count").textContent = refs.length;
    refs.forEach((id) => {
      const button = el("button", "reference-chip", anchorLabel(id) + (anchorById(id)?.removed ? " · 已失效" : " ↗"));
      button.type = "button";
      button.id = "modal-reference-" + id;
      button.dataset.previewReference = id;
      container.append(button);
      dynamicContract(button.id, "REQ-811：先暂存并关闭唯一整改弹窗，再定位引用" + anchorLabel(id) + "；草稿保留，失效引用不自动重绑。", "reference-chips");
    });
  }
  // ── 五、画布和右栏是同一状态的视图：编号稳定，新增仅用建议编号，不暗示精确插入位置。 ──
  function dynamicContract(id, text, group) {
    const existing = $("contract-" + id);
    if (existing) existing.remove();
    const paragraph = el("p", "", text);
    paragraph.id = "contract-" + id;
    paragraph.dataset.contractFor = id;
    paragraph.dataset.dynamicGroup = group;
    $("interaction-contracts").append(paragraph);
  }
  function clearContracts(group) {
    document.querySelectorAll('[data-dynamic-group="' + group + '"]').forEach((node) => node.remove());
  }
  function overlayNode(id, tag, className, parent) {
    let node = $(id);
    if (!node) {
      node = el(tag, className);
      node.id = id;
      parent.append(node);
    }
    node.className = className;
    return node;
  }
  function pruneOverlay(container, keep) {
    Array.from(container.children).forEach((node) => {
      if (keep.has(node.id)) return;
      $("contract-" + node.id)?.remove();
      node.remove();
    });
  }
  function renderOverlays() {
    const rects = $("rectification-overlays"), anchors = $("anchor-overlays");
    const keepRects = new Set(), keepAnchors = new Set(), groups = new Map();
    if (state.showRectifications) state.items.forEach((item) => {
      if (item.target.scope !== "node" || item.target.page !== state.page) return;
      const node = resolveNode(item.target.target_id);
      if (!node || !isVisible(node)) return;
      const key = targetKey(item.target);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    groups.forEach((items) => {
      const chosen = items.find((item) => item.id === state.activeItemId) || items[0];
      const b = bounds(resolveNode(chosen.target.target_id));
      // 新增只呈现绿色建议编号；参照节点不是精确插入位置，不画插入线或整块染色。
      if (chosen.operation !== "add") {
        const outlineId = "rectification-outline-" + chosen.id;
        const outline = overlayNode(outlineId, "div", "rectification-outline " + chosen.operation + (chosen.id === state.activeItemId ? " is-active" : ""), rects);
        place(outline, b);
        keepRects.add(outlineId);
      }
      items.forEach((item, index) => {
        const id = "rectification-badge-" + item.id;
        const badge = overlayNode(id, "button", "rectification-badge " + item.operation + (item.id === state.activeItemId ? " is-active" : ""), rects);
        badge.type = "button";
        badge.dataset.locateItem = item.id;
        badge.textContent = serialNumber(item.number) + " " + operations[item.operation];
        badge.style.left = Math.min(1020, Math.max(0, b.x + (index % 4) * 98)) + "px";
        badge.style.top = Math.max(0, b.y - 25 - Math.floor(index / 4) * 27) + "px";
        keepRects.add(id);
        if (!$("contract-" + id)) dynamicContract(id, "REQ-804、808：定位用户整改" + serialNumber(item.number) + "，与右栏同号同色；仅平移、当前项突出，不修改稿件或重新编号。", "overlays");
      });
    });
    if (state.showAnchors) activeAnchors().forEach((anchor) => {
      if (anchor.target.page !== state.page) return;
      const node = resolveNode(anchor.target.target_id);
      if (!node || !isVisible(node)) return;
      const b = bounds(node), id = "anchor-badge-" + anchor.id;
      const badge = overlayNode(id, "button", "anchor-badge" + (state.activeAnchorId === anchor.id ? " is-active" : ""), anchors);
      badge.type = "button";
      badge.dataset.locateAnchor = anchor.id;
      badge.textContent = anchor.label;
      badge.style.left = Math.max(0, Math.min(1060, b.x + b.w - 48)) + "px";
      badge.style.top = Math.min(830, b.y + b.h + 10) + "px";
      keepAnchors.add(id);
      if (!$("contract-" + id)) dynamicContract(id, "REQ-811：定位中性标记" + anchor.label + "，独立于整改编号；隐藏不删除绑定，引用保持。", "overlays");
    });
    pruneOverlay(rects, keepRects);
    pruneOverlay(anchors, keepAnchors);
    const selected = resolveNode(state.selected[state.page]);
    const showSelection = selected && isVisible(selected) && (state.mode === "annotate" || state.activeItemId || state.activeAnchorId);
    $("selection-outline").hidden = !showSelection;
    if (showSelection) place($("selection-outline"), bounds(selected));
    renderSelectionTools();
  }
  function updateCounts() {
    const anchors = activeAnchors();
    $("feedback-count").textContent = state.items.length;
    $("rectification-count").textContent = state.items.length;
    $("anchor-count").textContent = anchors.length;
    const pageCount = state.items.filter((item) => item.target.scope === "page" && item.target.page === state.page).length;
    $("page-rectification-count").textContent = pageCount ? pageCount : "";
    Object.keys(pages).forEach((page) => {
      $("nav-count-" + page).textContent = state.items.filter((item) => item.target.page === page).length + " 条整改";
    });
    $("panel-footer-status").textContent = state.items.length + " 条整改 · " + anchors.length + " 个定位" + (state.drafts.size ? " · " + state.drafts.size + " 份草稿" : "");
  }
  function actionButton(label, id, dataName, value, group, contract) {
    const button = el("button", "review-inline", label);
    button.type = "button";
    button.id = id;
    button.dataset[dataName] = value;
    dynamicContract(id, contract, group);
    return button;
  }
  function renderList() {
    clearContracts("items");
    const list = $("rectification-list");
    list.replaceChildren();
    const scope = $("filter-scope").value;
    const visible = state.items.filter((item) => (scope === "all" || (scope === "global" ? item.target.scope === "global" : item.target.scope === "global" || item.target.page === state.page)));
    const groupKeys = [state.page, ...Object.keys(pages).filter((page) => page !== state.page), "global"];
    groupKeys.forEach((key) => {
      const entries = visible.filter((item) => (item.target.page || "global") === key);
      if (!entries.length) return;
      const section = el("section", "rectification-group");
      section.append(el("h3", "rectification-group-title", key === "global" ? "本轮整体" : pages[key]));
      entries.forEach((item) => {
        const row = el("article", "rectification-item" + (state.activeItemId === item.id ? " is-active" : ""));
        row.id = "rectification-row-" + item.id;
        const meta = el("div", "rectification-item-meta");
        meta.append(el("span", "rectification-number " + item.operation, serialNumber(item.number)), el("span", "operation-label " + item.operation, operations[item.operation]));
        row.append(meta, el("p", "rectification-summary", item.message || "建议删除此元素（未填写原因）。"));
        // 意见正文优先，目标只是次级语境；完整内容不做行数裁切。
        if (item.target.scope === "node") row.append(el("p", "rectification-context", "目标 · " + targetName(item.target)));
        if (item.reference_ids.length) {
          const refs = el("div", "item-references");
          item.reference_ids.forEach((id) => refs.append(actionButton(anchorLabel(id) + (anchorById(id)?.removed ? " · 失效" : " ↗"), "item-" + item.id + "-ref-" + id, "locateAnchor", id, "items", "REQ-811：定位整改引用" + anchorLabel(id) + "；保留真实目标关联，失效不重绑。")));
          row.append(refs);
        }
        const conflicts = conflictItems(item);
        if (conflicts.length) row.append(el("p", "item-conflict", "潜在冲突 · 同目标整改 " + conflicts.map((entry) => serialNumber(entry.number)).join("、")));
        const actions = el("div", "rectification-item-actions");
        actions.append(actionButton("定位", "item-" + item.id + "-locate", "locateItem", item.id, "items", "REQ-804：定位整改" + serialNumber(item.number) + "，右栏内部可见且不重置缩放。"), actionButton("编辑", "item-" + item.id + "-edit", "editItem", item.id, "items", "REQ-804：同一弹窗编辑整改，完成保留编号，取消保留原条及草稿。"), actionButton("撤回", "item-" + item.id + "-withdraw", "withdrawItem", item.id, "items", "REQ-804：只撤回该条及彩色覆盖层，同目标其他条保留；可单次恢复。"));
        row.append(actions);
        section.append(row);
      });
      list.append(section);
    });
    $("rectification-empty").hidden = visible.length > 0;
    $("rectification-empty").querySelector("h3").textContent = state.items.length ? "当前范围没有整改" : "从一处整改开始";
    $("empty-description").textContent = state.items.length ? "调整筛选可查看其他整改；编号与交还内容保持。" : "在批注模式点选元素，写下修改、新增或删除建议。";
    $("start-annotation").textContent = state.items.length ? "查看全部整改" : "开始批注";
  }
  function renderAnchors() {
    clearContracts("anchors");
    const list = $("anchor-list");
    list.replaceChildren();
    if (!activeAnchors().length) {
      list.append(el("p", "review-field-help", "在画布选中元素后点“标记位置”，无需先写整改。"));
      return;
    }
    activeAnchors().forEach((anchor) => {
      const row = el("article", "anchor-item"), heading = el("div", "anchor-item-heading");
      heading.append(actionButton(anchor.label, "anchor-" + anchor.id + "-locate", "locateAnchor", anchor.id, "anchors", "REQ-811：定位" + anchor.label + "的原目标，保持缩放，不创建整改。"), el("span", "", pages[anchor.target.page]));
      row.append(heading, el("p", "", targetName(anchor.target)));
      const references = markerReferences(anchor.id);
      const relation = el("div", "anchor-relations");
      references.items.forEach((item) => relation.append(actionButton("引用 " + serialNumber(item.number), "anchor-" + anchor.id + "-item-" + item.id, "locateItem", item.id, "anchors", "REQ-811：查看引用此定位的整改" + serialNumber(item.number) + "；只定位，不解除绑定。")));
      if (references.drafts.length) relation.append(el("span", "", "另被 " + references.drafts.length + " 份草稿引用"));
      if (references.items.length || references.drafts.length) row.append(relation, el("p", "anchor-protection", "先解除引用或撤回相关整改，才能移除此标记。"));
      const remove = actionButton("移除标记", "anchor-" + anchor.id + "-remove", "removeAnchor", anchor.id, "anchors", "REQ-811：仅无整改/草稿引用时移除，编号不复用；被引用时禁用并说明原因。" );
      remove.disabled = references.items.length > 0 || references.drafts.length > 0;
      row.append(remove);
      list.append(row);
    });
  }
  // 右栏Tab只切换同一状态的实体视图，不复制数据、编辑器或交还载荷。
  function setPanelTab(tab) {
    state.panelTab = tab;
    ["rectifications", "anchors"].forEach((name) => {
      const selected = name === tab;
      const button = $("tab-" + name);
      button.setAttribute("aria-selected", String(selected));
      button.toggleAttribute("focusgroupstart", selected);
      if ("focusGroup" in HTMLElement.prototype) button.removeAttribute("tabindex");
      else button.tabIndex = selected ? 0 : -1;
    });
    $("rectification-tab-panel").hidden = tab !== "rectifications";
    $("anchor-tab-panel").hidden = tab !== "anchors";
    // 空标记列表没有按钮，面板本身成为键盘阅读入口。
    $("anchor-tab-panel").tabIndex = tab === "anchors" && !activeAnchors().length ? 0 : -1;
  }
  function ensureAnchorVisible(id) {
    const button = $("anchor-" + id + "-locate");
    if (!button || !isVisible(button)) return;
    const scroller = $("review-panel-scroll");
    scroller.scrollTop += button.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 12;
  }
  function renderAll() {
    updateCounts();
    renderList();
    renderAnchors();
    setPanelTab(state.panelTab);
    renderOverlays();
  }
  function ensureItemVisible(id) {
    const row = $("rectification-row-" + id), scroller = $("review-panel-scroll");
    if (!row || !isVisible(row)) return;
    scroller.scrollTop += row.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 12;
  }
  function locateItem(id) {
    const item = state.items.find((entry) => entry.id === id);
    if (!item || !locateTarget(item.target, item.source_stamp)) return;
    state.activeItemId = id;
    state.activeAnchorId = null;
    if (item.target.scope !== "node") state.selected[state.page] = null;
    $("filter-scope").value = item.target.scope === "global" ? "global" : "current";

    setPanelTab("rectifications");
    renderAll();
    ensureItemVisible(id);
    announce("已定位整改" + serialNumber(item.number) + "：" + targetName(item.target));
  }
  function withdrawItem(id) {
    const index = state.items.findIndex((item) => item.id === id);
    if (index < 0) return;
    // 该条编辑草稿与撤回快照一起退出活跃集合，避免集中完成草稿时静默复活撤回项。
    // 同目标的其他新建草稿仍是独立用户输入，不能一并清除。
    const editKey = "edit:" + id;
    state.withdrawn = {
      item: state.items[index], index, editDraft: state.drafts.get(editKey) || null
    };
    state.drafts.delete(editKey);
    state.items.splice(index, 1);
    if (state.activeItemId === id) state.activeItemId = null;
    $("withdraw-notice").hidden = false;
    $("withdraw-message").textContent = "已撤回整改 " + serialNumber(state.withdrawn.item.number);
    renderAll();
    $("undo-withdraw").focus({
      preventScroll: true
    });
    announce("已撤回该条，其他整改和定位引用保留。" );
  }
  // ── 六、统一交还：草稿集中处理，引用含目标映射，不声明生产协议已实现。 ──
  function serializeTarget(target) {
    if (target.scope === "global") return {
      scope: "global"
    };
    const out = {
      scope: target.scope, page: target.page
    };
    if (target.scope === "node") {
      const record = records.get(target.target_id);
      if (record?.sourceId) out.target_id = record.sourceId;
      else out.demo_locator = target.target_id;
    }
    return out;
  }
  function buildExport() {
    const anchors = activeAnchors().map((anchor) => ({
      id: anchor.id, number: anchor.label, target: serializeTarget(anchor.target), source_stamp: anchor.source_stamp
    }));
    const items = state.items.map((item) => ({
      id: item.id, number: serialNumber(item.number), operation: item.operation, target: serializeTarget(item.target), message: item.message, req_ids: [], reference_ids: item.reference_ids.slice(), ...(item.comparison ? {
        comparison: {
          before_text: resolveNode(item.target.target_id)?.innerText?.slice(0, 4000) || "", after_text: item.comparison
        }
      } : {
      })
    }));
    const payload = {
      schema_version: 3, demo_only: true, context: {
        // 工具自身的REQ目录只属于开发契约，不充当两个虚构稿的业务需求目录。
        schema_version: 2, demo_only: true, source_stamp: state.sourceStamp, pages: Object.keys(pages), requirements: []
      }, anchors, items
    };
    const summary = state.items.map((item) => serialNumber(item.number) + " · " + operations[item.operation] + " · " + targetName(item.target) + "\n" + (item.message || "删除原因未填写") + (item.reference_ids.length ? "\n引用：" + item.reference_ids.map(anchorLabel).join("、") : "")).join("\n\n");
    return "# 整改反馈 · 交互原型演示\n\n仅为demo_only：定位与来源未经过生产校验，无真实review_id；不能作为现有生产CLI消费输入，不批准方案或自动开始实现。\n\n" + state.items.length + " 条已完成整改，" + anchors.length + " 个独立定位标记\n\n" + summary + "\n\n## 唯一机器载荷\n```json\n" + JSON.stringify(payload, null, 2) + "\n```\n";
  }
  function exportProblem() {
    if (state.scenario === "stale") return "演示来源已过期，整改和草稿仍保留；不能交还或自动重绑。";
    for (const item of state.items) {
      const problem = validateFields(item.target, itemFields(item), item.source_stamp, false);
      if (problem) return "整改 " + serialNumber(item.number) + "：" + problem;
    }
    for (const anchor of activeAnchors()) {
      const problem = sourceProblem(anchor.target, anchor.source_stamp);
      if (problem) return anchor.label + "：" + problem;
    }
    return "";
  }
  function prepareExport() {
    stashModal();
    state.restorePanelFor = narrow.matches && drawer.open ? "export" : null;
    if (drawer.open) drawer.close();
    $("export-saved-count").textContent = state.items.length;
    $("export-draft-count").textContent = state.drafts.size;
    $("export-anchor-count").textContent = activeAnchors().length;
    const problem = exportProblem(), empty = !state.items.length && !activeAnchors().length && !state.drafts.size;
    $("export-save-copy").hidden = !state.drafts.size;
    $("export-copy").hidden = state.drafts.size > 0;
    $("export-save-copy").disabled = state.scenario === "stale";
    $("export-copy").disabled = Boolean(problem) || empty;
    $("export-warning").textContent = problem || (state.drafts.size ? "另有 " + state.drafts.size + " 份未完成草稿。先集中完成再复制，或取消并保留。" : empty ? "尚无可交还内容。先在画布标记位置或完成一条整改。" : "将复制全部已完成整改与定位关系；右侧筛选不改变交还集合。");
    state.exportText = buildExport();
    $("export-text").value = state.exportText;
    const blocked = Boolean(problem) || empty || state.drafts.size > 0;
    $("download-feedback").disabled = blocked;
    $("select-export").disabled = blocked;
    $("export-text").hidden = blocked;
    $("export-result").textContent = "";
    $("export-result").classList.remove("is-error");
  }
  function finishAllDrafts() {
    const entries = Array.from(state.drafts.entries());
    const bad = entries.find(([, draft]) => validateFields(draft.target, draft.fields, draft.source_stamp));
    if (bad) {
      state.restorePanelFor = null;
      exporter.close();
      const draft = bad[1];
      prepareEdit(draft.target, draft.editId);
      editDialog.showModal();
      showError(validateFields(draft.target, draft.fields, draft.source_stamp));
      return false;
    }
    entries.forEach(([key, draft]) => commitFields(draft.target, draft.fields, draft.editId, key, draft.source_stamp));
    setPanelTab("rectifications");
    renderAll();
    const restore = state.restorePanelFor;
    prepareExport();
    state.restorePanelFor = restore;
    return true;
  }
  async function copyExport() {
    if (state.drafts.size || exportProblem() || (!state.items.length && !activeAnchors().length)) return;
    $("export-result").textContent = "正在复制…";
    try {
      if (state.scenario === "copy-error") throw new Error("模拟复制拒绝");
      await navigator.clipboard.writeText(state.exportText);
      $("export-result").classList.remove("is-error");
      $("export-result").textContent = "已复制，请粘贴到当前Agent对话并发送。";
      announce("已复制整改与定位关系，请粘贴发送。" );
    } catch {
      $("export-result").classList.add("is-error");
      $("export-result").textContent = "复制失败，所有内容保留。请手动复制或下载反馈。";
      root.querySelector(".review-export-backup").open = true;
      $("export-text").focus();
      $("export-text").select();
    }
  }
  // ── 七、受控事件装配：浏览事件不被工具夺取；批注与平移明确分开。 ──
  function hit(event) {
    const node = event.target.closest?.("[data-review-key]");
    return node && $("sample-canvas").contains(node) && isVisible(node) ? node : null;
  }
  const toolbarRefreshers = [];
  function wireToolbar(bar) {
    if ("focusGroup" in HTMLElement.prototype) return;
    const visibleButtons = () => Array.from(bar.querySelectorAll("button")).filter((button) => !button.hidden && !button.disabled);
    const refresh = () => {
      const buttons = visibleButtons();
      const active = buttons.find((button) => button.tabIndex === 0) || buttons[0];
      buttons.forEach((button) => {
        button.tabIndex = button === active ? 0 : -1;
      });
    };
    refresh();
    toolbarRefreshers.push(refresh);
    bar.addEventListener("focusin", (event) => {
      visibleButtons().forEach((button) => {
        button.tabIndex = button === event.target ? 0 : -1;
      });
    });
    bar.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const buttons = visibleButtons();
      if (!buttons.length) return;
      event.preventDefault();
      const current = Math.max(0, buttons.indexOf(document.activeElement));
      const direction = getComputedStyle(bar).direction === "rtl" ? -1 : 1;
      const index = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowRight" ? direction : -direction) + buttons.length) % buttons.length;
      buttons[index].focus();
    });
  }
  function bindPicking() {
    const canvas = $("sample-canvas");
    canvas.addEventListener("pointermove", (event) => {
      if (state.mode !== "annotate" || state.space) return;
      const node = hit(event);
      $("hover-outline").hidden = !node;
      if (node) place($("hover-outline"), bounds(node));
    });
    canvas.addEventListener("pointerleave", () => {
      $("hover-outline").hidden = true;
    });
    canvas.addEventListener("pointerdown", (event) => {
      if (state.mode === "annotate" && !state.space && event.button === 0) event.preventDefault();
    }, true);
    canvas.addEventListener("click", (event) => {
      if (state.panMoved || state.space) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }
      if (state.mode !== "annotate") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const node = hit(event);
      if (node) selectNode(node.dataset.reviewKey);
    }, true);
    canvas.addEventListener("keydown", (event) => {
      if (state.mode !== "annotate" || event.isComposing || ["Tab", "Escape"].includes(event.key)) return;
      const node = hit(event);
      if (!node) return;
      if (["Enter", " "].includes(event.key) || event.target.matches("input,select,textarea")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (["Enter", " "].includes(event.key)) selectNode(node.dataset.reviewKey, true);
      }
    }, true);
  }
  function demoStatus(message) {
    $(state.page === "preferences" ? "sample-business-status" : "sample-native-status").textContent = message;
    renderOverlays();
  }
  function updateDemoSelection() {
    const count = document.querySelectorAll('[data-demo-selection]:checked').length;
    $("sample-selected-count").textContent = count ? "已选择 " + count + " 个身份" : "未选择身份";
  }
  function runDemoAction(button) {
    const action = button.dataset.demoAction;
    const messages = {
      project: "项目位置：本页演示项目agent_workflow，未访问磁盘配置。", refresh: "已刷新本页演示目录，没有请求真实宿主。", help: "项目逐身份优先于项目通用，未覆盖时逐层继承。", source: "项目覆盖位置：.claude/agents/xy-uiux.md，仅为示例路径。", definition: "定义摘要：根据已确认需求维护授权原型，不修改生产代码。", preview: "预览当前内存演示值，未发布任何真实配置。"
    };
    if (action === "inherit") {
      const count = document.querySelectorAll('[data-demo-selection]:checked').length;
      demoStatus(count ? "已在演示中恢复所选" + count + "个身份的继承。" : "请先选择身份。");
    } else if (action === "discard") {
      $("sample-default-model").selectedIndex = 0;
      $("sample-default-effort").selectedIndex = 0;
      document.querySelectorAll("[data-demo-choice]").forEach((select) => {
        select.selectedIndex = 0;
      });
      $("sample-save-state").textContent = "没有未保存更改";
      demoStatus("已还原业务演示字段，评审草稿保持。" );
    } else demoStatus(messages[action] || "已执行本页演示操作。");
  }
  function preparePanel() {
    if (narrow.matches) $("drawer-panel-host").append(panel);
    else $("review-panel-slot").append(panel);
    $("open-feedback").setAttribute("aria-expanded", "true");
  }
  function restorePanel(kind) {
    if (state.restorePanelFor !== kind) return;
    state.restorePanelFor = null;
    if (narrow.matches) {
      preparePanel();
      if (!drawer.open) drawer.showModal();
      $(kind === "export" ? "copy-feedback" : "write-global").focus({
        preventScroll: true
      });
    }
  }
  function bindControls() {
    const tabs = [$("tab-rectifications"), $("tab-anchors")];
    tabs.forEach((tab) => {
      const select = () => setPanelTab(tab === tabs[0] ? "rectifications" : "anchors");
      tab.addEventListener("click", select);
      tab.addEventListener("focus", select);
    });
    // focusgroup受支持时使用原生箭头导航；否则仅在这一真实Tab组提供轻量后备。
    if (!("focusGroup" in HTMLElement.prototype)) $("record-tabs").addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const index = event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - tabs.indexOf(document.activeElement);
      tabs[Math.max(0, index)].focus({ preventScroll: true });
    });
    ["browse", "annotate"].forEach((mode) => $("mode-" + mode).addEventListener("change", () => setMode(mode)));
    Object.keys(pages).forEach((page) => $("page-" + page).addEventListener("click", (event) => {
      event.preventDefault();
      switchPage(page);
      nav.close();
    }));
    $("target-directory").addEventListener("change", (event) => {
      if (event.target.value) {
        setMode("annotate");
        selectNode(event.target.value, true);
        focusEl(resolveNode(event.target.value));
        $("target-picker").open = false;
      }
    });
    $("select-parent").addEventListener("click", () => {
      const parent = parentRecord(state.selected[state.page]);
      if (parent) selectNode(parent.node.dataset.reviewKey);
    });
    $("mark-location").addEventListener("click", markLocation);
    $("remove-selected-anchor").addEventListener("click", () => removeAnchor(state.activeAnchorId));
    $("withdraw-selected-item").addEventListener("click", () => withdrawItem(state.activeItemId));
    $("view-anchor-references").addEventListener("click", () => {
      setPanelTab("anchors");
      if (narrow.matches) $("open-feedback").click();
      // 仅移动面板自身滚动区，顶层工具栏保持原位。
      const button = $("anchor-" + state.activeAnchorId + "-locate");
      if (button) {
        const scroller = $("review-panel-scroll");
        scroller.scrollTop += button.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 12;
        button.focus({ preventScroll: true });
      }
    });
    $("start-annotation").addEventListener("click", () => {
      if (state.items.length) {
        $("filter-scope").value = "all";

        renderList();
      } else {
        setMode("annotate");
        if (drawer.open) drawer.close();
      }
    });
    $("rectification-form").addEventListener("submit", (event) => {
      event.preventDefault();
      completeModal();
    });
    ["rectification-message", "comparison-after"].forEach((id) => $(id).addEventListener("input", () => {
      clearError();
      stashModal();
      updateCounts();
    }));
    ["modify", "add", "delete"].forEach((operation) => $("operation-" + operation).addEventListener("change", () => {
      clearError();
      updateOperationUI();
      stashModal();
      updateCounts();
    }));
    $("rectification-message").addEventListener("keydown", (event) => {
      if (!event.isComposing && event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        completeModal();
      }
    });
    $("reference-options").addEventListener("change", (event) => {
      if (event.target.matches("input[data-reference-option]")) {
        stashModal();
        renderSelectedReferences();
        updateCounts();
      }
    });
    $("filter-scope").addEventListener("change", renderList);
    $("undo-withdraw").addEventListener("click", () => {
      if (!state.withdrawn) return;
      const item = state.withdrawn.item;
      state.items.splice(state.withdrawn.index, 0, item);
      if (state.withdrawn.editDraft) state.drafts.set("edit:" + item.id, state.withdrawn.editDraft);
      state.withdrawn = null;
      $("withdraw-notice").hidden = true;
      renderAll();
      const invalid = item.reference_ids.some((id) => !anchorById(id) || anchorById(id).removed);
      announce("已恢复整改" + serialNumber(item.number) + (invalid ? "，但原定位引用已移除，请编辑解除失效引用后交还。" : "，编号保持。"));
    });
    root.addEventListener("click", (event) => {
      const preview = event.target.closest("[data-preview-reference]");
      if (preview) {
        stashModal();
        state.modal = null;
        state.restorePanelFor = null;
        editDialog.close();
        locateAnchor(preview.dataset.previewReference);
        vpEl().focus({
          preventScroll: true
        });
        return;
      }
      const edit = event.target.closest("[data-edit-item]");
      if (edit) {
        const item = state.items.find((entry) => entry.id === edit.dataset.editItem);
        if (item) {
          prepareEdit(item.target, item.id);
          editDialog.showModal();
        } return;
      }
      const withdraw = event.target.closest("[data-withdraw-item]");
      if (withdraw) {
        withdrawItem(withdraw.dataset.withdrawItem);
        return;
      }
      const locate = event.target.closest("[data-locate-item]");
      if (locate) {
        locateItem(locate.dataset.locateItem);
        return;
      }
      const anchor = event.target.closest("[data-locate-anchor]");
      if (anchor) {
        locateAnchor(anchor.dataset.locateAnchor);
        return;
      }
      const remove = event.target.closest("[data-remove-anchor]");
      if (remove) {
        removeAnchor(remove.dataset.removeAnchor);
        return;
      }
      const navigation = event.target.closest("[data-demo-navigation]");
      if (navigation) {
        switchPage(navigation.dataset.demoNavigation);
        return;
      }
      const definition = event.target.closest("[data-definition]");
      if (definition) {
        document.querySelectorAll("[data-definition]").forEach((node) => node.classList.toggle("is-selected", node === definition));
        $("sample-native-name").textContent = definition.dataset.definition;
        $("sample-native-role").textContent = definition.querySelector("small").textContent;
        demoStatus("已查看" + definition.dataset.definition + "的本地演示定义。");
        return;
      }
      const business = event.target.closest("[data-demo-action]");
      if (business) runDemoAction(business);
    });
    ["sample-default-model", "sample-default-effort"].forEach((id) => $(id).addEventListener("change", () => {
      $("sample-save-state").textContent = "有未保存的演示更改";
      demoStatus("已选择本地字段值，未写真实配置。" );
    }));
    document.querySelectorAll("[data-demo-choice]").forEach((select) => select.addEventListener("change", () => {
      $("sample-save-state").textContent = "有未保存的演示更改";
      demoStatus("已展开并选择本地演示候选；不是账户模型目录或API结果。" );
    }));
    $("sample-select-all").addEventListener("change", (event) => {
      document.querySelectorAll("[data-demo-selection]").forEach((node) => {
        node.checked = event.target.checked;
      });
      updateDemoSelection();
    });
    document.querySelectorAll("[data-demo-selection]").forEach((node) => node.addEventListener("change", updateDemoSelection));
    $("sample-native-search").addEventListener("input", (event) => {
      let count = 0;
      const query = event.target.value.toLowerCase();
      document.querySelectorAll("[data-definition]").forEach((node) => {
        node.hidden = !node.textContent.toLowerCase().includes(query);
        if (!node.hidden) count++;
      });
      $("sample-native-empty").hidden = count > 0;
      refreshDirectory();
      renderOverlays();
    });
    $("canvas-fit").addEventListener("click", fitCam);
    const zoomCenter = (factor) => {
      const r = vpEl().getBoundingClientRect();
      zoomAt(factor, r.width / 2, r.height / 2);
    };
    $("canvas-zoom-out").addEventListener("click", () => zoomCenter(1 / 1.25));
    $("canvas-zoom-in").addEventListener("click", () => zoomCenter(1.25));
    $("canvas-zoom-reset").addEventListener("click", () => zoomCenter(1 / state.cameras[state.page].k));
    $("show-rectifications").addEventListener("change", (event) => {
      state.showRectifications = event.target.checked;
      renderOverlays();
    });
    $("show-anchors").addEventListener("change", (event) => {
      state.showAnchors = event.target.checked;
      renderOverlays();
    });
    $("export-copy").addEventListener("click", copyExport);
    $("export-save-copy").addEventListener("click", () => {
      if (finishAllDrafts()) copyExport();
    });
    $("select-export").addEventListener("click", () => {
      $("export-text").focus();
      $("export-text").select();
      $("export-result").textContent = "已全选，请按Ctrl+C / ⌘C手动复制。";
    });
    $("download-feedback").addEventListener("click", () => {
      if (state.drafts.size || exportProblem()) return;
      try {
        const url = URL.createObjectURL(new Blob([state.exportText], {
          type: "text/markdown;charset=utf-8"
        }));
        const link = document.createElement("a");
        link.href = url;
        link.download = "prototype-demo-rectifications.md";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        $("export-result").textContent = "已请求下载；请找到文件后交还当前对话。";
      }
      catch {
        $("export-result").textContent = "下载请求失败，数据保留，请手动复制。";
      }
    });
    $("demo-state").addEventListener("change", (event) => {
      state.scenario = event.target.value;
      announce("已切换演示恢复场景，整改、定位和草稿保持。" );
    });
    editDialog.addEventListener("close", () => {
      stashModal();
      state.modal = null;
      renderAll();
      restorePanel("edit");
    });
    exporter.addEventListener("close", () => restorePanel("export"));
    drawer.addEventListener("close", () => $("open-feedback").setAttribute("aria-expanded", "false"));
    nav.addEventListener("close", () => $("navigation-toggle").setAttribute("aria-expanded", "false"));
    if (!("closedBy" in HTMLDialogElement.prototype)) {
      let downOutside = false;
      const outside = (event) => {
        const r = nav.getBoundingClientRect();
        return event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom;
      };
      nav.addEventListener("pointerdown", (event) => {
        downOutside = outside(event);
      });
      nav.addEventListener("pointerup", (event) => {
        if (downOutside && outside(event)) nav.close();
      });
    }
    narrow.addEventListener("change", () => {
      if (!narrow.matches && drawer.open) drawer.close();
      preparePanel();
      $("open-feedback").setAttribute("aria-expanded", String(drawer.open));
      renderOverlays();
    });
    new ResizeObserver(renderOverlays).observe(vpEl());
    document.addEventListener("keydown", (event) => {
      if (editDialog.open || exporter.open || $("developer-dialog").open || drawer.open || nav.open) return;
      if (event.key === " " && !event.target.closest("input,select,textarea,button,a,summary")) {
        state.space = true;
        vpEl().classList.add("space");
        event.preventDefault();
      }
      if (event.key === "Escape" && state.mode === "annotate") setMode("browse");
      if (event.target === vpEl() && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
        event.preventDefault();
        const c = state.cameras[state.page];
        c.x += event.key === "ArrowLeft" ? 48 : event.key === "ArrowRight" ? -48 : 0;
        c.y += event.key === "ArrowUp" ? 48 : event.key === "ArrowDown" ? -48 : 0;
        applyCam();
      }
    });
    const releaseSpace = () => {
      state.space = false;
      vpEl().classList.remove("space");
    };
    document.addEventListener("keyup", (event) => {
      if (event.key === " ") releaseSpace();
    });
    window.addEventListener("blur", releaseSpace);
  }
  // 初始化只索引实际HTML，整改和A定位序列均空；没有预置用户成果。
  indexDesigns();
  wireToolbar($("canvas-zoom-tools"));
  wireToolbar($("selection-actions"));
  bindPicking();
  wirePanZoom(vpEl());
  bindControls();
  preparePanel();
  $("open-feedback").setAttribute("aria-expanded", "false");
  const requested = location.hash.slice(1);
  switchPage(pages[requested] ? requested : "preferences", false);
  window.reviewPrototype = {
    prepareNavigation() {
      $("navigation-toggle").setAttribute("aria-expanded", "true");
    },
    preparePanel,
    prepareNodeEdit() {
      const key = state.selected[state.page];
      if (!key) {
        announce("请先点选一个目标。");
        return false;
      } prepareEdit(nodeTarget(key));
      return true;
    },
    preparePageEdit() {
      prepareEdit({
        scope: "page", page: state.page
      });
    },
    prepareGlobalEdit() {
      prepareEdit({
        scope: "global"
      });
    },
    prepareExport
  };
})();
