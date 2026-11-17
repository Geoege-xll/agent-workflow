(() => {
  "use strict";
  /* 交付与评审只共用工具相机和有限消息桥；所有记录都在本页内存。
     不读取 iframe DOM，不写磁盘/配置，不连接任何运行时服务。 */
  const $ = id => document.getElementById(id);
  const isReview = document.body.dataset.workspaceMode === "review";
  const pages = { preferences: "调用偏好", native: "原生定义", activation: "工作流启停", diagnostics: "诊断与帮助" };
  let page = new URLSearchParams(location.search).get("page");
  if (!Object.hasOwn(pages, page)) page = "preferences";
  const frame = $("prototype-preview"), world = $("canvas-world"), viewport = $("canvas-viewport"), overlays = $("canvas-overlays");
  frame.addEventListener("load", () => { frame.hidden = false; });
  const width = 1280, height = 900;
  let scale = 1, panX = 0, panY = 0, nonce = "", selected = null, nextRectification = 1, nextAnchor = 1, editing = null, activeTab = "rectifications", context = null;
  const rectifications = [], anchors = [], drafts = new Map();
  // 在工具 DOM 中增加单纯几何占位，保持 iframe 唯一且不重复执行原稿脚本。
  const space = document.createElement("div"); space.className = "ws-canvas-space";
  world.before(space); space.append(world);
  // 工具悬浮层属于视口外壳，滚动/缩放业务稿件不会挤占它们的可用面积。
  for (const selector of [".ws-navigation", ".ws-selection", ".ws-canvas-controls", ".ws-canvas-status"]) {
    const node = viewport.querySelector(selector); if (node) viewport.parentElement.append(node);
  }
  function camera(value) {
    scale = Math.min(1.5, Math.max(.25, value));
    world.style.transform = `translate(${panX}px,${panY}px) scale(${scale})`;
    space.style.inlineSize = `${width * scale}px`; space.style.blockSize = `${height * scale}px`;
    $("canvas-zoom-reset").textContent = `${Math.round(scale*100)}%`;
  }
  function fit() { panX = 0; panY = 0; camera(Math.min((viewport.clientWidth-48)/width, (viewport.clientHeight-48)/height, 1)); }
  // 工具演示不再把 viewport 当原生滚动区；稿内滚动留在 iframe，外相机仅接显式手势。
  viewport.style.overflow = "hidden"; viewport.style.overscrollBehavior = "contain";
  let spaceHeld = false, dragging = null;
  const move = (dx,dy) => { panX += dx; panY += dy; fitted = false; camera(scale); };
  viewport.addEventListener("wheel", event => {
    if (event.defaultPrevented || (!event.ctrlKey && !event.metaKey)) return;
    event.preventDefault(); fitted = false; camera(scale*Math.exp(-event.deltaY*.0022));
  },{passive:false});
  viewport.addEventListener("keydown", event => { if (event.target === viewport && event.code === "Space") { spaceHeld = true; event.preventDefault(); } });
  viewport.addEventListener("keyup", event => { if (event.code === "Space") spaceHeld = false; });
  viewport.addEventListener("pointerdown", event => {
    if (event.button !== 1 && !(event.button === 0 && spaceHeld)) return;
    dragging = {id:event.pointerId,x:event.clientX,y:event.clientY}; viewport.setPointerCapture(event.pointerId); event.preventDefault();
  });
  viewport.addEventListener("pointermove", event => { if (!dragging || dragging.id !== event.pointerId) return; move(event.clientX-dragging.x,event.clientY-dragging.y); dragging.x=event.clientX; dragging.y=event.clientY; });
  const endPan = () => { dragging=null; };
  viewport.addEventListener("pointerup",endPan); viewport.addEventListener("pointercancel",endPan);
  window.addEventListener("blur",()=>{spaceHeld=false;endPan();});
  $("canvas-fit").addEventListener("click", fit);
  $("canvas-zoom-out").addEventListener("click", () => camera(scale-.1));
  $("canvas-zoom-in").addEventListener("click", () => camera(scale+.1));
  $("canvas-zoom-reset").addEventListener("click", () => camera(1));
  let fitted = true;
  $("canvas-fit").addEventListener("click", () => { fitted = true; });
  for (const id of ["canvas-zoom-out","canvas-zoom-in","canvas-zoom-reset"]) $(id).addEventListener("click", () => { fitted = false; });
  window.addEventListener("resize", () => { if (fitted) fit(); });
  function loadPage() {
    nonce = crypto.randomUUID(); selected = null;
    const params = new URLSearchParams({ embedded: "1", view: page, bridge: nonce });
    if (isReview) params.set("review", "1");
    frame.src = `agent-configuration.html?${params}`;
    if (!isReview) {
      $("current-page-title").textContent = `Agent 配置工作台 / ${pages[page]}`;
      $("open-review").href = `prototype-workspace.html?page=${encodeURIComponent(page)}`;
      document.querySelectorAll("[data-page]").forEach(button => { if (button.dataset.page === page) button.setAttribute("aria-current","page"); else button.removeAttribute("aria-current"); });
    }
    drawOverlays();
  }
  if (!isReview) {
    const toggle = $("navigation-toggle"), nav = $("delivery-navigation");
    toggle.addEventListener("click", () => { nav.hidden = !nav.hidden; toggle.setAttribute("aria-expanded", String(!nav.hidden)); });
    document.querySelectorAll("[data-page]").forEach(button => button.addEventListener("click", () => { page = button.dataset.page; loadPage(); nav.hidden = true; toggle.setAttribute("aria-expanded","false"); toggle.focus(); }));
    document.addEventListener("keydown", event => { if (event.key === "Escape" && !nav.hidden) { nav.hidden = true; toggle.setAttribute("aria-expanded","false"); toggle.focus(); } });
  }
  function validTarget(target) {
    return target && typeof target.id === "string" && /^[a-zA-Z][\w:-]{0,159}$/.test(target.id)
      && typeof target.label === "string" && target.label.length <= 120
      && ["x","y","width","height"].every(key => Number.isFinite(target[key]) && Math.abs(target[key]) <= 10000)
      && target.width > 0 && target.height > 0;
  }
  window.addEventListener("message", event => {
    // null origin 不作为信任依据。必须同时是当前唯一 iframe、本轮随机 nonce 和当前页面。
    if (event.source !== frame.contentWindow || event.origin !== "null") return;
    const data = event.data;
    if (!data || typeof data !== "object" || data.namespace !== "xy-solid-glass-prototype-v1" || data.nonce !== nonce || data.page !== page) return;
    if (data.type === "gesture") {
      if (data.gesture === "pan" && [data.dx,data.dy].every(Number.isFinite) && Math.abs(data.dx)<10000 && Math.abs(data.dy)<10000) move(data.dx*scale,data.dy*scale);
      if (data.gesture === "zoom" && Number.isFinite(data.factor) && data.factor>=.01 && data.factor<=100) { fitted=false; camera(scale*data.factor); }
      return;
    }
    if (!isReview || data.type !== "selection" || !validTarget(data.target)) return;
    selected = { ...data.target };
    $("selection-label").textContent = selected.label || selected.id;
    $("selection-tools").hidden = false;
    $("review-status").textContent = `已选中 ${selected.label || selected.id}`;
    drawOverlays();
  });
  function drawOverlays() {
    overlays.replaceChildren();
    if (selected) {
      const outline = document.createElement("div"); outline.className = "ws-target-outline";
      Object.assign(outline.style, { left: `${selected.x}px`, top: `${selected.y}px`, width: `${selected.width}px`, height: `${selected.height}px` }); overlays.append(outline);
    }
    for (const item of [...anchors, ...rectifications]) {
      if (!item.target || item.page !== page) continue;
      const marker = document.createElement("button"); marker.type = "button"; marker.className = "ws-marker"; marker.textContent = item.id; marker.dataset.operation = item.operation || "anchor";
      marker.style.left = `${Math.max(0,item.target.x-12)}px`; marker.style.top = `${Math.max(0,item.target.y-14+(item.markerOffset || 0))}px`;
      marker.setAttribute("aria-label", `${item.id} ${item.message || item.target.label}`);
      marker.addEventListener("click", () => { selected = { ...item.target }; $("selection-tools").hidden = false; $("selection-label").textContent = selected.label; activateTab(item.id.startsWith("A") ? "anchors" : "rectifications"); drawOverlays(); $("record-"+item.id)?.scrollIntoView({block:"nearest"}); });
      overlays.append(marker);
    }
  }
  function textNode(tag, text, className) { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }
  const operationNames = { modify: "修改", add: "新增", delete: "删除" };
  function locate(item) {
    if (!item.target) { $("review-status").textContent = `${item.id} · ${item.scope === "global" ? "本轮整体" : "页面"}意见`; return; }
    selected = { ...item.target }; $("selection-label").textContent = selected.label; $("selection-tools").hidden = false; drawOverlays();
    panX = viewport.clientWidth/3-selected.x*scale; panY = viewport.clientHeight/3-selected.y*scale; fitted=false; camera(scale);
    $("review-status").textContent = `定位 ${item.id} · ${item.target.label}`;
  }
  function renderRecords() {
    if (!isReview) return;
    for (const [name, list] of [["rectification",rectifications],["anchor",anchors]]) {
      const container = $(name+"-list"); container.replaceChildren();
      for (const item of list) {
        const article = document.createElement("article"); article.id = "record-"+item.id; article.className = "ws-record"; article.dataset.operation = item.operation || "anchor";
        const heading = document.createElement("div"); heading.className = "ws-record-heading"; heading.append(textNode("strong",item.id,"ws-record-id"),textNode("span",item.operation ? operationNames[item.operation] : "位置标记","ws-operation-name"));
        article.append(heading, textNode("p",item.message || item.target.label), textNode("p",item.target ? `${pages[item.page]} / ${item.target.label}` : item.scope === "global" ? "本轮整体" : `${pages[item.page]} / 页面`,"ws-record-target"));
        const actions = document.createElement("div"); actions.className = "ws-record-actions";
        for (const [label, action] of [["定位",()=>locate(item)],["编辑",()=>item.id.startsWith("R") ? openRectification(item.scope,item) : editAnchor(item)],["删除",()=>{ list.splice(list.indexOf(item),1); renderRecords(); drawOverlays(); }]]) {
          const button = textNode("button",label,"sg-quiet"); button.type = "button"; button.setAttribute("aria-label",`${label} ${item.id}`); button.addEventListener("click",action); actions.append(button);
        }
        article.append(actions); container.append(article);
      }
      if (!list.length) {
        const empty=document.createElement("div"); empty.className="ws-record-empty";
        empty.append(textNode("h3", name === "anchor" ? "标记关键位置" : "从一处整改开始"),textNode("p",name === "anchor" ? "点选原稿节点，再选择“标记位置”。" : "点选元素，写下修改、新增或删除建议。"));
        if (name === "rectification") { const button=textNode("button","添加页面整改"); button.type="button"; button.addEventListener("click",()=>openRectification("page")); empty.append(button); }
        container.append(empty);
      }
    }
    $("rectification-count").textContent = String(rectifications.length); $("anchor-count").textContent = String(anchors.length); $("record-total").textContent = String(rectifications.length+anchors.length);
    $("feedback-status").textContent = rectifications.length+anchors.length ? `${rectifications.length} 条整改 · ${anchors.length} 个标记 · 仅本页内存` : "尚无评审记录";
  }
  function activateTab(name) {
    activeTab=name;
    for (const current of ["rectifications","anchors"]) { const button=$("tab-"+current), active=current===name; button.setAttribute("aria-selected",String(active)); button.tabIndex=active?0:-1; $(current === "anchors"?"anchor-list":"rectification-list").hidden=!active; }
  }
  function keyFor(scope, item) { return item ? item.id : `${page}:${scope}:${scope === "node" ? selected?.id : ""}`; }
  function rememberDraft() {
    if (!context) return;
    drafts.set(context.key,{message:$("rectification-message").value,operation:document.querySelector('input[name="operation"]:checked').value});
  }
  function openRectification(scope, item=null) {
    if (scope === "node" && !item && !selected) return;
    editing=item;
    context={scope,key:keyFor(scope,item),target:item?.target || (scope === "node" ? {...selected} : null)};
    const draft=drafts.get(context.key) || item || {message:"",operation:"modify"};
    $("rectification-title").textContent=item?`编辑整改 ${item.id}`:"添加整改";
    $("rectification-scope").textContent=scope === "node" ? "节点整改" : scope === "page" ? "页面整改" : "本轮整体意见";
    $("rectification-target").textContent=context.target ? `${pages[page]} / ${context.target.label}` : scope === "global" ? "适用于本轮全部页面" : `适用于“${pages[page]}”整页`;
    $("rectification-message").value=draft.message; document.querySelector(`input[name="operation"][value="${draft.operation}"]`).checked=true;
    $("message-error").hidden=true; $("rectification-message").removeAttribute("aria-invalid");
    $("rectification-dialog").showModal(); $("rectification-message").focus();
  }
  function editAnchor(item) {
    // 标记编辑复用原生模态表单，仅修改描述，不改变位置或独立的 A 编号。
    editing=item; context={scope:"anchor",key:item.id,target:item.target};
    const draft=drafts.get(item.id) || {message:item.message || item.target.label,operation:"modify"};
    $("rectification-title").textContent=`编辑标记 ${item.id}`; $("rectification-scope").textContent="位置标记";
    $("rectification-target").textContent=`${pages[item.page]} / ${item.target.label}`; $("rectification-message").value=draft.message;
    $("message-error").hidden=true; $("rectification-message").removeAttribute("aria-invalid"); document.querySelector(".ws-operation").hidden=true;
    $("rectification-dialog").showModal(); $("rectification-message").focus();
  }
  if (isReview) {
    $("clear-selection").addEventListener("click",()=>{ selected=null; $("selection-tools").hidden=true; drawOverlays(); });
    $("add-rectification").addEventListener("click",()=>openRectification("node"));
    $("page-rectification").addEventListener("click",()=>openRectification("page")); $("global-rectification").addEventListener("click",()=>openRectification("global"));
    $("mark-location").addEventListener("click",()=>{ if (!selected) return; anchors.push({id:`A${nextAnchor++}`,page,target:{...selected},message:""}); renderRecords(); drawOverlays(); activateTab("anchors"); });
    for (const id of ["rectification-close","rectification-cancel"]) $(id).addEventListener("click",()=>$("rectification-dialog").close());
    $("rectification-dialog").addEventListener("close",()=>{ rememberDraft(); document.querySelector(".ws-operation").hidden=false; });
    $("rectification-message").addEventListener("input",()=>{ $("message-error").hidden=true; $("rectification-message").removeAttribute("aria-invalid"); });
    $("rectification-message").addEventListener("keydown",event=>{ if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.isComposing) { event.preventDefault(); $("rectification-form").requestSubmit(); } });
    $("rectification-form").addEventListener("submit",event=>{
      event.preventDefault(); const message=$("rectification-message").value.trim();
      if (!message) { $("message-error").textContent="请写下期望效果后再完成。"; $("message-error").hidden=false; $("rectification-message").setAttribute("aria-invalid","true"); $("rectification-message").focus(); return; }
      if (context.scope === "anchor") editing.message=message;
      else { const values={message,operation:document.querySelector('input[name="operation"]:checked').value,page,scope:context.scope,target:context.target}; if(editing) Object.assign(editing,values); else rectifications.push({id:`R${nextRectification++}`,...values,markerOffset:28}); }
      drafts.delete(context.key); context=null; $("rectification-dialog").close(); renderRecords(); drawOverlays();
    });
    for (const name of ["rectifications","anchors"]) $("tab-"+name).addEventListener("click",()=>activateTab(name));
    $("record-tabs").addEventListener("keydown",event=>{ if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return; event.preventDefault(); activateTab(event.key === "Home" ? "rectifications" : event.key === "End" ? "anchors" : activeTab === "anchors" ? "rectifications" : "anchors"); $("tab-"+activeTab).focus(); });
    $("open-records").addEventListener("click",()=>{ const panel=$("review-panel"); panel.dataset.open=String(panel.dataset.open!=="true"); $("open-records").setAttribute("aria-expanded",panel.dataset.open); });
    $("close-records").addEventListener("click",()=>{ $("review-panel").dataset.open="false"; $("open-records").setAttribute("aria-expanded","false"); $("open-records").focus(); });
    $("export-feedback").addEventListener("click",()=>{ $("export-text").value=["SolidGlass 工具原型演示反馈（非生产协议）",...rectifications.map(item=>`${item.id} [${operationNames[item.operation]}] ${item.target?.label || item.scope}: ${item.message}`),...anchors.map(item=>`${item.id} [位置] ${item.message || item.target.label}`)].join("\n\n"); $("export-status").textContent=""; $("export-dialog").showModal(); });
    $("export-close").addEventListener("click",()=>$("export-dialog").close());
    $("export-copy").addEventListener("click",async()=>{ try { if (!navigator.clipboard?.writeText) throw Error("unavailable"); await navigator.clipboard.writeText($("export-text").value); $("export-status").textContent="已复制演示记录，可粘贴到对话。"; } catch { $("export-text").focus(); $("export-text").select(); $("export-status").textContent="当前 file 环境未提供自动复制，请按 ⌘ / Ctrl + C。"; } });
    renderRecords();
  }
  loadPage(); requestAnimationFrame(fit);
})();
