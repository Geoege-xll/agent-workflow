(() => {
  "use strict";

  // 此模块只维护浏览器反馈输入；context 是只读绑定，不是批准或执行权限。
  const exact = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
  const text = (value, max = 4096) => typeof value === "string" && value.trim().length > 0 && Array.from(value).length <= max && !value.includes("\0");
  const path = (value) => text(value, 1024) && !value.startsWith("/") && !/[\\:#?%]/.test(value)
    && value.split("/").every((part) => part && part !== "." && part !== "..");
  const sha = (value) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  const stableId = (value) => typeof value === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,127}$/.test(value);
  function parseFragment(hash) {
    // 先限制原始片段大小及参数重复；损坏的评审绑定不影响普通页面浏览。
    const params = new URLSearchParams(hash.slice(1));
    const page = params.getAll("page").length === 1 ? params.get("page") : null;
    const result = { page, rawReview: params.getAll("review").length === 1 ? params.get("review") : null, context: null, error: "" };
    if (!params.has("review")) return result;
    try {
      if (hash.slice(1).length > 12288 || params.getAll("page").length !== 1 || params.getAll("review").length !== 1
          || Array.from(params.keys()).some((key) => key !== "page" && key !== "review")) throw Error();
      const encoded = result.rawReview;
      if (!encoded || !/^[A-Za-z0-9_-]+$/.test(encoded)) throw Error();
      const binary = atob(encoded.replace(/-/g, "+").replace(/_/g, "/"));
      if (binary.length > 8192) throw Error();
      const raw = new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)));
      const context = JSON.parse(raw);
      // prepare只产出紧凑UTF8 JSON；严格往返比对拒绝重复键、尾部空白及替代转义，
      // 防止JSON.parse悄悄采用最后一个同名字段，把坏绑定洗成可用context。
      if (JSON.stringify(context) !== raw) throw Error();
      if (!exact(context, ["schema_version", "request_id", "adapter", "prototype_root", "plan_source", "plan_sha256", "requirements", "pages"])
          || context.schema_version !== 1 || typeof context.request_id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(context.request_id) || !path(context.adapter)
          || !path(context.prototype_root) || !path(context.plan_source) || !context.plan_source.endsWith(".md") || !sha(context.plan_sha256)
          || !Array.isArray(context.requirements) || !context.requirements.length || !Array.isArray(context.pages) || !context.pages.length || context.pages.length > 16) throw Error();
      const requirements = new Set();
      for (const req of context.requirements) {
        if (!exact(req, ["id", "label"]) || !/^REQ-[0-9]{3,}$/.test(req.id) || !text(req.label, 8192) || requirements.has(req.id)) throw Error();
        requirements.add(req.id);
      }
      const pages = new Set();
      for (const item of context.pages) {
        const name = item.path?.slice(context.prototype_root.length + 1);
        if (!exact(item, ["path", "dependency_fingerprint"]) || !path(item.path) || !item.path.startsWith(`${context.prototype_root}/`)
            || !/^[a-z0-9][a-z0-9-]*\.html$/.test(name) || name === "index.html" || !sha(item.dependency_fingerprint) || pages.has(item.path)) throw Error();
        pages.add(item.path);
      }
      result.context = context;
    } catch {
      result.error = "本轮评审链接损坏或超出范围。页面仍可浏览，请重新使用准备好的评审链接；已有输入不会自动重绑。";
    }
    return result;
  }

  function create({ send }) {
    const panel = document.getElementById("prototype-feedback");
    if (!panel) return null;
    const get = (id) => document.getElementById(`feedback-${id}`);
    const form = get("form"), controls = get("fields"), target = get("target"), kind = get("kind"), message = get("message");
    const before = get("before"), after = get("after"), requirements = get("requirements"), relations = get("relations"), list = get("items");
    const storageStatus = get("storage"), status = get("status"), manual = get("manual"), output = get("output");
    let context = null, binding = "", page = "", nodes = [], items = [], editing = null, drafts = {}, storageAvailable = true, bindingBlocked = false, bindingNotice = "", savePending = false, saveTimer = null, pendingAction = null;
    const announce = (value) => { status.textContent = value; };
    const pagePath = () => context && `${context.prototype_root}/${page}`;
    const selectedNode = () => nodes.find((node) => node.id === target.value);
    const make = (tag, value) => { const node = document.createElement(tag); if (value !== undefined) node.textContent = value; return node; };
    const checks = () => Array.from(requirements.querySelectorAll("input")).filter((input) => input.checked).map((input) => input.value);
    const draft = () => ({ page: pagePath(), target_id: target.value, kind: kind.value, message: message.value, after_text: after.value, req_ids: checks(), editing });
    function persist() {
      // sessionStorage 天然按顶层标签页隔离；键和值都绑定完整context，绝不读写localStorage跨页共享草稿。
      // 存储失败只降级持久性，内存和表单仍为当前输入权威，绝不能提示“已保存”。
      if (!binding || !context) return;
      if (page) drafts[pagePath()] = draft();
      try {
        window.sessionStorage.setItem(`prototype-feedback:${binding}`, JSON.stringify({ context, items, drafts }));
        storageAvailable = true;
        storageStatus.textContent = "草稿仅保存在本标签页；相同评审链接刷新后可恢复。复制或下载后仍需独立复核。";
      } catch {
        storageAvailable = false;
        storageStatus.textContent = "浏览器存储不可用：输入仅留在当前页面内存。刷新可能丢失，请先复制或下载反馈。";
      }
    }
    function validItem(item) {
      // sessionStorage同样属于外部输入；恢复采用封闭字段，避免被篡改草稿带入批准等非法字段。
      const required = ["id", "page", "target_id", "kind", "message", "req_ids"];
      const optional = ["comparison", "interaction_id", "interface_refs"];
      const plain = (value, empty = false) => typeof value === "string" && Array.from(value).length <= 4000 && !value.includes("\0") && (empty || value.trim());
      return item && typeof item === "object" && required.every((key) => Object.hasOwn(item, key))
        && Object.keys(item).every((key) => required.includes(key) || optional.includes(key))
        && typeof item.id === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(item.id) && context.pages.some((entry) => entry.path === item.page)
        && stableId(item.target_id) && ["must_change", "suggestion", "question"].includes(item.kind) && plain(item.message)
        && Array.isArray(item.req_ids) && new Set(item.req_ids).size === item.req_ids.length
        && item.req_ids.every((id) => context.requirements.some((req) => req.id === id))
        && (!Object.hasOwn(item, "comparison") || (exact(item.comparison, ["before_text", "after_text"]) && plain(item.comparison.before_text, true) && plain(item.comparison.after_text, true)))
        && (!Object.hasOwn(item, "interaction_id") || stableId(item.interaction_id))
        && (!Object.hasOwn(item, "interface_refs") || (Array.isArray(item.interface_refs) && item.interface_refs.length <= 32 && new Set(item.interface_refs).size === item.interface_refs.length && item.interface_refs.every((ref) => text(ref, 512))));
    }
    function renderItems() {
      list.replaceChildren();
      if (!items.length) list.append(make("p", "尚无反馈。选择节点并保存第一条意见。"));
      for (const item of items) {
        const card = make("article");
        card.append(make("h3", `${({ must_change: "必须改", suggestion: "建议", question: "疑问" })[item.kind]} · ${item.target_id}`));
        card.append(make("p", `${item.page} · ${item.req_ids.join("、") || "未关联 REQ"}`), make("p", item.message));
        if (item.comparison) {
          const compare = make("div"); compare.className = "feedback-comparison";
          const old = make("div"), proposed = make("div");
          old.append(make("strong", "当前浏览器摘录"), make("pre", item.comparison.before_text));
          proposed.append(make("strong", "建议修改"), make("pre", item.comparison.after_text)); compare.append(old, proposed); card.append(compare);
        }
        const actions = make("div"); actions.className = "feedback-actions";
        for (const [label, action] of [["定位节点", () => locate(item)], ["编辑草稿", () => edit(item)], ["撤回意见", () => {
          items = items.filter((entry) => entry.id !== item.id); if (editing === item.id) resetEditor(); persist(); renderItems(); (controls.disabled ? get("heading") : get("save")).focus(); announce("意见已撤回，其他输入保留。");
        }]]) {
          const button = make("button", label); button.type = "button"; button.addEventListener("click", action); actions.append(button);
        }
        card.append(actions); list.append(card);
      }
      get("count").textContent = `${items.length} 条`;
    }
    function cancelPending() {
      if (saveTimer) window.clearTimeout(saveTimer);
      savePending = false;
    }
    function navigateToItem(item, editAfterLoad) {
      pendingAction = { id: item.id, page: item.page, edit: editAfterLoad };
      const name = item.page.slice(context.prototype_root.length + 1);
      if (send("navigate", name) === false) { pendingAction = null; announce("意见所属页面未在导航登记，输入与意见保持不变。"); }
    }
    function locate(item) {
      if (item.page !== pagePath()) { navigateToItem(item, false); return; }
      if (!nodes.some((node) => node.id === item.target_id)) { announce("该节点当前不可定位，可能已更改或不再唯一；意见仍保留。"); return; }
      send("locate", item.target_id); announce(`正在定位节点：${item.target_id}。`);
    }
    function showNode() {
      const node = selectedNode(); before.textContent = node?.text || "当前节点没有可读文字。";
      relations.textContent = node ? `交互映射：${node.interaction_id || "无稳定映射 ID"}。${node.interaction_text || "未发现现有交互说明。"} 接口引用：${node.interface_refs.join("、") || "未声明明确来源"}` : "等待当前页提供唯一稳定节点。";
    }
    function resetEditor() {
      cancelPending();
      editing = null; message.value = ""; after.value = ""; kind.value = "suggestion";
      for (const input of requirements.querySelectorAll("input")) input.checked = false;
      get("save").textContent = "保存意见"; showNode();
    }
    function edit(item) {
      cancelPending();
      if (item.page !== pagePath()) { navigateToItem(item, true); return; }
      if (!nodes.some((node) => node.id === item.target_id)) { locate(item); return; }
      editing = item.id; target.value = item.target_id; kind.value = item.kind; message.value = item.message; after.value = item.comparison?.after_text || "";
      for (const input of requirements.querySelectorAll("input")) input.checked = item.req_ids.includes(input.value);
      get("save").textContent = "保存修改"; showNode(); panel.open = true; message.focus(); persist();
    }
    function exportText() {
      if (!context) throw Error("缺少有效评审绑定");
      // 没有任何approved字段或工作流状态；JSON只是用户输入，必须经过核心validate复核。
      const value = JSON.stringify({ schema_version: 1, context, items }, null, 2);
      if (new TextEncoder().encode(value).length > 1048576) throw Error("反馈超过1MiB");
      return value;
    }
    function saveOpinion() {
      const node = selectedNode();
      if (!context || bindingBlocked || !node || !message.value.trim() || message.value.includes("\0") || after.value.includes("\0")) { announce("请选择当前唯一节点，并填写意见。输入已保留。"); return; }
      if (Array.from(message.value).length > 4000 || Array.from(after.value).length > 4000 || (!editing && items.length >= 256)) {
        announce("意见或建议超过 4000 字符，或意见已达 256 条。请缩短内容或撤回已有意见；原输入已保留。"); return;
      }
      const item = { id: editing || `feedback-${window.crypto.randomUUID()}`, page: pagePath(), target_id: node.id, kind: kind.value, message: message.value, req_ids: checks() };
      if (after.value.trim()) item.comparison = { before_text: node.text, after_text: after.value };
      if (node.interaction_id) item.interaction_id = node.interaction_id;
      if (node.interface_refs.length) item.interface_refs = node.interface_refs;
      if (!validItem(item)) { announce("意见字段不符合本轮格式，输入已保留，请检查节点、类型与关联需求。"); return; }
      const index = items.findIndex((entry) => entry.id === editing);
      const candidate = [...items];
      if (index < 0) candidate.push(item); else candidate[index] = item;
      if (new TextEncoder().encode(JSON.stringify({ schema_version: 1, context, items: candidate }, null, 2)).length > 1048576) {
        announce("反馈超过 1 MiB，无法保存本条。请缩短内容或撤回部分意见；输入已保留。"); return;
      }
      items = candidate;
      resetEditor(); persist(); renderItems(); announce(storageAvailable ? "意见已保存到本标签页草稿；尚未经过独立复核。" : "意见已保留在内存；存储不可用，请先导出。");
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!context || bindingBlocked || !selectedNode()) { announce("当前页节点尚未就绪，输入已保留。"); return; }
      if (savePending) return;
      // 保存前重新向当前页读取文字，不能把首次载入的目录冒称当前浏览器摘录。
      // 只发受控refresh动作；超时/换页取消待保存状态，表单与草稿都保留。
      persist(); savePending = true; announce("正在读取当前节点文字……");
      saveTimer = window.setTimeout(() => { savePending = false; announce("当前页未响应，意见尚未保存；输入已保留，请重试。"); }, 3000);
      send("refresh");
    });
    form.addEventListener("input", persist);
    target.addEventListener("change", () => { cancelPending(); showNode(); persist(); });
    get("locate").addEventListener("click", () => locate({ page: pagePath(), target_id: target.value }));
    get("cancel").addEventListener("click", () => { resetEditor(); persist(); announce("已取消当前编辑，已保存意见保留。"); });
    get("copy").addEventListener("click", async () => {
      try {
        const value = exportText(); announce("正在复制反馈……");
        await navigator.clipboard.writeText(value); announce("反馈 JSON 已复制；后续仍需独立复核。");
      } catch {
        // 剪贴板可能被安全上下文/权限拒绝，改用原生dialog供手动选择，绝不清空表单。
        if (!context) { announce("评审绑定无效，无法导出。输入保持不变。"); return; }
        output.value = exportText(); manual.showModal(); output.focus(); output.select(); announce("自动复制失败。请在对话框手动复制，或关闭后下载 JSON；输入已保留。");
      }
    });
    get("download").addEventListener("click", () => {
      let url;
      try {
        url = URL.createObjectURL(new Blob([exportText()], { type: "application/json;charset=utf-8" }));
        const link = make("a"); link.href = url; link.download = "prototype-feedback.json"; link.click();
        announce("已请求下载反馈 JSON。请确认浏览器下载结果；输入仍保留。");
      } catch { announce("下载未能启动，请使用复制反馈或手动复制；输入保持不变。"); }
      finally { if (url) window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
    });
    get("close").addEventListener("click", () => manual.close());
    return {
      bind(fragment) {
        if (bindingBlocked || (fragment.rawReview === binding && context)) return;
        // 运行期间换context不自动重绑旧草稿；保留当前内存，要求重新打开明确链接。
        if (binding) { cancelPending(); controls.disabled = true; bindingBlocked = true; bindingNotice = "评审绑定已改变，反馈编辑已停用。原输入仍绑定原链接，可导出；请在新标签页打开新的评审链接。"; announce(bindingNotice); return; }
        if (!fragment.context) { controls.disabled = true; bindingBlocked = Boolean(fragment.error); bindingNotice = fragment.error || "普通浏览模式。请通过准备好的评审链接开始反馈。"; announce(bindingNotice); return; }
        context = fragment.context; binding = fragment.rawReview;
        requirements.replaceChildren();
        for (const req of context.requirements) {
          const label = make("label"), input = make("input"); input.type = "checkbox"; input.value = req.id;
          label.append(input, make("span", `${req.id} · ${req.label}`)); requirements.append(label);
        }
        try {
          const saved = JSON.parse(window.sessionStorage.getItem(`prototype-feedback:${binding}`) || "null");
          // 恢复只读取同一context的本标签页快照；损坏内容不写回覆盖，页面内保持可用。
          if (saved) {
            if (JSON.stringify(saved.context) !== JSON.stringify(context) || !Array.isArray(saved.items)
                || saved.items.length > 256 || !saved.items.every(validItem) || new Set(saved.items.map((item) => item.id)).size !== saved.items.length
                || new TextEncoder().encode(JSON.stringify({ schema_version: 1, context, items: saved.items }, null, 2)).length > 1048576) throw Error("草稿无效");
            items = saved.items;
            // 编辑器快照只恢复已知纯文本字段；不执行存储对象提供的路径、selector或动作。
            if (saved.drafts && typeof saved.drafts === "object" && !Array.isArray(saved.drafts)) {
              for (const [key, value] of Object.entries(saved.drafts)) {
                if (context.pages.some((entry) => entry.path === key) && value && value.page === key
                    && typeof value.target_id === "string" && typeof value.message === "string" && typeof value.after_text === "string"
                    && ["must_change", "suggestion", "question"].includes(value.kind) && Array.isArray(value.req_ids)
                    && value.req_ids.every((id) => context.requirements.some((req) => req.id === id))
                    && (value.editing === null || items.some((item) => item.id === value.editing))) drafts[key] = value;
              }
            }
          }
          storageStatus.textContent = "草稿仅保存在本标签页；相同评审链接刷新后可恢复。";
        } catch { storageStatus.textContent = "浏览器存储不可用或草稿损坏，当前输入仅留内存；请及时导出。"; storageAvailable = false; }
        renderItems(); announce("评审绑定已载入。反馈是修订输入，保存或导出不会批准工作流。");
      },
      select(name) {
        cancelPending();
        if (page && context) persist();
        page = name;
        if (pendingAction && pendingAction.page !== pagePath()) pendingAction = null;
        resetEditor(); nodes = []; target.replaceChildren(); controls.disabled = true;
        announce(bindingNotice || (context ? "等待当前页确认唯一稳定节点……" : "普通浏览模式，反馈未启用。"));
      },
      receive(data) {
        if (data.type === "prototype-workspace:located") {
          announce(data.ok ? `已定位当前节点：${data.target}。` : "节点当前不可定位，请先在画板中显示对应状态。输入与意见保持不变。"); return;
        }
        if (!context || bindingBlocked || data.type !== "prototype-workspace:catalog" || !context.pages.some((entry) => entry.path === pagePath()) || !Array.isArray(data.nodes) || data.nodes.length > 512) return;
        // 父壳仍验证消息来源/session；此处再验证有限数据，所有显示均textContent，不执行HTML或路径。
        if (!data.nodes.every((node) => exact(node, ["id", "text", "interaction_id", "interaction_text", "interface_refs"])
            && stableId(node.id) && typeof node.text === "string" && Array.from(node.text).length <= 4000
            && (node.interaction_id === "" || stableId(node.interaction_id)) && typeof node.interaction_text === "string" && Array.from(node.interaction_text).length <= 4000
            && Array.isArray(node.interface_refs) && node.interface_refs.length <= 32 && node.interface_refs.every((ref) => text(ref, 512)))) return;
        if (new Set(data.nodes.map((node) => node.id)).size !== data.nodes.length) return;
        nodes = data.nodes; target.replaceChildren();
        for (const node of nodes) { const option = make("option", `${node.id} · ${node.text.slice(0, 60) || "无文字"}`); option.value = node.id; target.append(option); }
        controls.disabled = !nodes.length;
        const pending = drafts[pagePath()];
        if (pending?.page === pagePath()) {
          target.value = pending.target_id; kind.value = pending.kind || "suggestion"; message.value = pending.message || ""; after.value = pending.after_text || ""; editing = pending.editing || null;
          for (const input of requirements.querySelectorAll("input")) input.checked = pending.req_ids?.includes(input.value) || false;
        }
        get("save").textContent = editing ? "保存修改" : "保存意见";
        showNode();
        if (savePending) { window.clearTimeout(saveTimer); savePending = false; saveOpinion(); return; }
        if (pendingAction?.page === pagePath()) {
          const action = pendingAction; pendingAction = null;
          const item = items.find((entry) => entry.id === action.id);
          if (item) { if (action.edit) edit(item); else locate(item); return; }
        }
        announce(data.error || (nodes.length ? "当前页节点可供反馈。请选择节点，定位后填写意见。" : "当前页没有唯一稳定 ID 节点；页面仍可浏览，已有意见保留。"));
      },
      open() { if (context && !bindingBlocked) send("refresh"); panel.open = true; panel.scrollIntoView({ block: "start" }); get("heading").focus(); },
    };
  }
  window.PrototypeFeedback = Object.freeze({ parseFragment, create });
})();
