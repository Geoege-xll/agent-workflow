/* 唯一评审状态所有者：输入、编号、引用与原子完成都在此处；视图只消费公开方法。
 * context2 是只读来源绑定，feedback3 才承载本次整改；相机/草稿永不混入机器载荷。 */
(() => {
  "use strict";
  const exact = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
  const text = (value, max = 4096) => typeof value === "string" && value.trim().length > 0 && Array.from(value).length <= max && !value.includes("\0");
  const path = (value) => text(value, 1024) && !value.startsWith("/") && !/[\\:#?%\x00-\x1f\x7f]/.test(value)
    && value.split("/").every((part) => part && part !== "." && part !== "..");
  const sha = (value) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  const stableId = (value) => typeof value === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,127}$/.test(value);
  function parseStartup(raw) {
    const result = { rawReview: "", context: null, pages: [], error: "" };
    try {
      // 数据只来自prepare写入的唯一非执行script。紧凑JSON安全转义往返检查同时
      // 拒绝重复键，不能把JSON.parse最后同名值洗成可信启动绑定；不读取hash中的context。
      if (typeof raw !== "string") throw Error();
      const boot = JSON.parse(raw);
      const safe = JSON.stringify(boot).replace(/[<>&\u2028\u2029]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
      if (safe !== raw || !exact(boot, ["schema_version", "context", "pages"]) || boot.schema_version !== 3) throw Error();
      const context = boot.context;
      if (!exact(context, ["schema_version", "request_id", "project_id", "adapter", "adapter_sha256", "prototype_root", "plan_source", "plan_sha256", "navigation_sha256", "requirements", "pages", "tool", "review_id"])
          || context.schema_version !== 2 || new TextEncoder().encode(JSON.stringify(context)).length > 8192
          || typeof context.request_id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(context.request_id)
          || !path(context.adapter) || !path(context.prototype_root) || !path(context.plan_source) || !context.plan_source.endsWith(".md")
          || ![context.project_id, context.adapter_sha256, context.plan_sha256, context.navigation_sha256, context.review_id].every(sha)
          || !exact(context.tool, ["version", "payload_sha256"]) || typeof context.tool.version !== "string"
          || !/^[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}$/.test(context.tool.version) || !sha(context.tool.payload_sha256)
          || !Array.isArray(context.requirements) || !context.requirements.length || !Array.isArray(context.pages) || !context.pages.length || context.pages.length > 16) throw Error();
      const requirements = new Set();
      for (const req of context.requirements) {
        if (!exact(req, ["id", "label"]) || typeof req.id !== "string" || !/^REQ-[0-9]{3,}$/.test(req.id) || !text(req.label, 8192) || requirements.has(req.id)) throw Error();
        requirements.add(req.id);
      }
      const pages = new Set();
      for (const item of context.pages) {
        const name = typeof item?.path === "string" ? item.path.slice(context.prototype_root.length + 1) : "";
        if (!exact(item, ["path", "dependency_fingerprint"]) || !path(item.path) || !item.path.startsWith(`${context.prototype_root}/`)
            || !/^[a-z0-9][a-z0-9-]*\.html$/.test(name) || name === "index.html" || !sha(item.dependency_fingerprint) || pages.has(item.path)) throw Error();
        pages.add(item.path);
      }
      if (!Array.isArray(boot.pages) || boot.pages.length !== pages.size) throw Error();
      const registered = new Set();
      for (const entry of boot.pages) {
        // URL不是可推导的消息输入，只接受核心给出的project/精确源路径映射。
        // 全部校验成功后才生成导航和设置iframe src，任何损坏都不能留下部分可用清单。
        if (!exact(entry, ["name", "path", "url", "label", "groups"]) || !pages.has(entry.path) || registered.has(entry.path)
            || entry.name !== entry.path.slice(context.prototype_root.length + 1) || entry.url !== `project/${entry.path}`
            || !text(entry.label, 1024) || !Array.isArray(entry.groups)
            || !entry.groups.every((group) => exact(group, ["label", "open"]) && text(group.label, 1024) && typeof group.open === "boolean")) throw Error();
        registered.add(entry.path);
      }
      result.context = context; result.rawReview = JSON.stringify(context); result.pages = boot.pages;
    } catch {
      result.error = "本轮评审快照数据损坏或超出范围，请重新准备评审包；已有输入不会自动重绑。";
    }
    return result;
  }
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const plain = (value, empty = true) => typeof value === "string" && Array.from(value).length <= 4000 && !value.includes("\0") && (empty || value.trim().length > 0);
  const identifier = (value) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(value);
  const sourceKey = (value) => typeof value === "string" && /^source-[a-f0-9]{64}$/.test(value);
  const targetKey = (target) => JSON.stringify(target);
  const positive = (value) => Number.isSafeInteger(value) && value > 0;
  function checkFeedbackBytes(value, label = "反馈") {
    // 核心先限制整个输入文件的UTF8字节数，再提取机器载荷；JSON与Markdown
    // 必须复用同一个1MiB预算，不能按JS字符数或只按compact JSON推断可交还。
    if (new TextEncoder().encode(value).length > 1048576) throw Error(`${label}超过1MiB，请缩短正文或撤回部分整改；全部输入仍保留。`);
    return value;
  }
  function create(boot, storage = null) {
    if (!boot.context || boot.error) throw Error(boot.error || "评审绑定无效");
    const context = clone(boot.context), pages = new Set(context.pages.map((entry) => entry.path));
    const listeners = new Set(), catalogs = new Map();
    const state = { context, pages: clone(boot.pages), page: boot.pages[0]?.path || "", mode: "browse", cameras: {}, selection: null,
      anchors: [], items: [], drafts: {}, withdrawn: null, nextAnchor: 1, nextItem: 1, editor: null,
      activeAnchor: null, activeItem: null, tab: "rectifications", filter: "current", showAnchors: true, showItems: true, storageMessage: "", blocked: false };
    const storageKey = `prototype-review:v3:${context.review_id}`;
    // 读取sessionStorage本身也可能被宿主拒绝，和setItem失败采用同一内存保留策略。
    if (!storage) { try { storage = window.sessionStorage; } catch { storage = { getItem() { throw Error("存储拒绝"); }, setItem() { throw Error("存储拒绝"); } }; } }
    function validTarget(target) {
      if (exact(target, ["scope"]) && target.scope === "global") return true;
      if (exact(target, ["scope", "page"]) && target.scope === "page") return pages.has(target.page);
      if (!exact(target, ["scope", "page", "locator"]) || target.scope !== "node" || !pages.has(target.page)) return false;
      return (exact(target.locator, ["type", "id"]) && target.locator.type === "id" && stableId(target.locator.id))
        || (exact(target.locator, ["type", "key"]) && target.locator.type === "source" && sourceKey(target.locator.key));
    }
    const validRefs = (refs) => Array.isArray(refs) && refs.length <= 256 && new Set(refs).size === refs.length && refs.every(identifier);
    const validReqs = (reqs) => Array.isArray(reqs) && new Set(reqs).size === reqs.length && reqs.every((id) => context.requirements.some((req) => req.id === id));
    const validComparison = (value) => exact(value, ["before_text", "after_text"]) && plain(value.before_text) && plain(value.after_text);
    const optionalMetadata = (entry) => (!Object.hasOwn(entry, "interaction_id") || stableId(entry.interaction_id))
      && (!Object.hasOwn(entry, "interface_refs") || (Array.isArray(entry.interface_refs) && entry.interface_refs.length <= 32
        && new Set(entry.interface_refs).size === entry.interface_refs.length && entry.interface_refs.every((ref) => text(ref, 512))));
    function validItem(item) {
      const required = ["id", "number", "operation", "target", "message", "req_ids", "reference_ids"];
      const optional = ["comparison", "interaction_id", "interface_refs"];
      return item && required.every((key) => Object.hasOwn(item, key)) && Object.keys(item).every((key) => required.includes(key) || optional.includes(key))
        && identifier(item.id) && positive(item.number) && validTarget(item.target) && ["modify", "add", "delete"].includes(item.operation)
        && (item.target.scope === "node" || item.operation !== "delete") && (item.target.scope !== "global" || item.operation === "modify")
        && plain(item.message, item.operation === "delete") && validReqs(item.req_ids) && validRefs(item.reference_ids)
        && (!item.comparison || (item.target.scope === "node" && item.operation === "modify" && validComparison(item.comparison))) && optionalMetadata(item);
    }
    function validAnchor(anchor) {
      return exact(anchor, ["id", "number", "target"]) && identifier(anchor.id) && positive(anchor.number) && validTarget(anchor.target) && anchor.target.scope === "node";
    }
    function validDraft(draft) {
      return exact(draft, ["target", "operation", "message", "after_text", "reference_ids", "editing", "excerpt", "req_ids", "interaction_id", "interface_refs"])
        && (draft.target === null || validTarget(draft.target)) && ["modify", "add", "delete"].includes(draft.operation)
        && plain(draft.message) && plain(draft.after_text) && plain(draft.excerpt) && validRefs(draft.reference_ids) && validReqs(draft.req_ids)
        && (draft.editing === null || identifier(draft.editing)) && (draft.interaction_id === "" || stableId(draft.interaction_id))
        && optionalMetadata({ ...(draft.interaction_id ? { interaction_id: draft.interaction_id } : {}), interface_refs: draft.interface_refs });
    }
    function uniqueSequence(entries) {
      return new Set(entries.map((entry) => entry.id)).size === entries.length && new Set(entries.map((entry) => entry.number)).size === entries.length;
    }
    function persist() {
      // 封闭会话格式与导出协议彻底分开，旧版本草稿不读取、不迁移或重绑。存储失败保留内存。
      const snapshot = { schema_version: 3, review_id: context.review_id, anchors: state.anchors, items: state.items,
        drafts: state.drafts, withdrawn: state.withdrawn, nextAnchor: state.nextAnchor, nextItem: state.nextItem, cameras: state.cameras };
      try { storage.setItem(storageKey, JSON.stringify(snapshot)); state.storageMessage = "草稿仅保存在本标签页；同一评审包刷新可恢复。"; }
      catch { state.storageMessage = "浏览器存储失败：输入仍在当前内存，刷新可能丢失，请及时交还。"; }
    }
    const emit = (save = true) => { if (save) persist(); for (const listener of listeners) listener(state); };
    function validCameras(cameras) {
      return cameras && typeof cameras === "object" && !Array.isArray(cameras) && Object.entries(cameras).every(([page, cam]) => pages.has(page)
        && exact(cam, ["k", "x", "y"]) && [cam.k, cam.x, cam.y].every(Number.isFinite) && cam.k >= .08 && cam.k <= 3 && Math.abs(cam.x) < 1e7 && Math.abs(cam.y) < 1e7);
    }
    try {
      const raw = storage.getItem(storageKey);
      if (raw) {
        const saved = JSON.parse(raw);
        if (!exact(saved, ["schema_version", "review_id", "anchors", "items", "drafts", "withdrawn", "nextAnchor", "nextItem", "cameras"])
          || saved.schema_version !== 3 || saved.review_id !== context.review_id || !Array.isArray(saved.anchors) || saved.anchors.length > 256
          || !Array.isArray(saved.items) || saved.items.length > 256 || !saved.anchors.every(validAnchor) || !saved.items.every(validItem)
          || !uniqueSequence(saved.anchors) || !uniqueSequence(saved.items) || !positive(saved.nextAnchor) || !positive(saved.nextItem)
          || saved.anchors.some((anchor) => anchor.number >= saved.nextAnchor) || saved.items.some((item) => item.number >= saved.nextItem)
          || !saved.drafts || typeof saved.drafts !== "object" || Array.isArray(saved.drafts) || !Object.values(saved.drafts).every(validDraft)
          || Object.entries(saved.drafts).some(([key, draft]) => key !== (draft.editing ? `edit:${draft.editing}` : draft.target ? targetKey(draft.target) : "unresolved"))
          || Object.values(saved.drafts).some((draft) => draft.editing && !saved.items.some((item) => item.id === draft.editing))
          || !validCameras(saved.cameras)
          || (saved.withdrawn !== null && (!exact(saved.withdrawn, ["item", "draft"]) || !validItem(saved.withdrawn.item)
            || (saved.withdrawn.draft !== null && (!validDraft(saved.withdrawn.draft) || saved.withdrawn.draft.editing !== saved.withdrawn.item.id))
            || saved.items.some((item) => item.id === saved.withdrawn.item.id || item.number === saved.withdrawn.item.number)
            || saved.withdrawn.item.number >= saved.nextItem))) throw Error("会话格式失效");
        Object.assign(state, { anchors: saved.anchors, items: saved.items, drafts: saved.drafts, withdrawn: saved.withdrawn,
          nextAnchor: saved.nextAnchor, nextItem: saved.nextItem, cameras: saved.cameras });
      }
      state.storageMessage = "草稿仅保存在本标签页；同一评审包刷新可恢复。";
    } catch { state.storageMessage = "旧草稿或会话数据无效，未恢复；当前输入仅从本轮开始，不迁移旧数据。"; }
    function recordFor(target) {
      if (target?.scope !== "node") return null;
      return catalogs.get(target.page)?.find((record) => record.target && targetKey(record.target) === targetKey(target)) || null;
    }
    function validateDraft(draft) {
      if (state.blocked) throw Error("本轮来源绑定已改变，请重新准备评审包；输入保留。");
      if (!validDraft(draft) || !draft.target) throw Error("当前动态元素没有可确认的来源。输入已保留，请显式选择有来源的父层。");
      if (draft.target.scope !== "node" && (draft.operation === "delete" || (draft.target.scope === "global" && draft.operation !== "modify"))) throw Error("当前范围不支持此整改类型。");
      if (!plain(draft.message, draft.operation === "delete")) throw Error("修改或新增内容必须填写正文，最多4000字符；删除原因可选。");
      if (draft.reference_ids.some((id) => !state.anchors.some((anchor) => anchor.id === id))) throw Error("存在已失效的A引用，请显式解除引用后再完成或交还。");
      const record = draft.target.scope === "node" ? recordFor(draft.target) : null;
      if (draft.target.scope === "node" && !record) throw Error("目标当前无法独立确认，请重新显示并选择原目标；输入已保留。");
      const item = { id: draft.editing || "pending", number: draft.editing ? state.items.find((entry) => entry.id === draft.editing)?.number : 1,
        operation: draft.operation, target: clone(draft.target), message: draft.message, req_ids: record?.req_ids || [], reference_ids: [...draft.reference_ids] };
      if (draft.target.scope === "node" && draft.operation === "modify" && draft.after_text.trim()) item.comparison = { before_text: record.text, after_text: draft.after_text };
      if (record?.interaction_id) item.interaction_id = record.interaction_id;
      if (record?.interface_refs.length) item.interface_refs = [...record.interface_refs];
      if (!validItem(item)) throw Error("整改内容超过限额或字段无效，输入已保留。");
      return item;
    }
    function envelope(items = state.items, anchors = state.anchors) {
      const value = { schema_version: 3, context: clone(context), anchors: clone(anchors), items: clone(items) };
      checkFeedbackBytes(JSON.stringify(value));
      return value;
    }
    function activeDrafts() { return Object.entries(state.drafts).filter(([, draft]) => draft.editing || draft.message || draft.after_text || draft.reference_ids.length || draft.operation !== "modify"); }
    function complete(keys, validatePayload = () => {}) {
      // 先对全部候选执行同一验证，再一次性换入集合和计数。任何失败均不部分完成、不占号。
      let next = state.nextItem;
      const prepared = keys.map((key) => {
        try { return { key, item: validateDraft(state.drafts[key]) }; }
        catch (error) { error.draftKey = key; throw error; }
      });
      const items = clone(state.items);
      for (const { item } of prepared) {
        const index = items.findIndex((entry) => entry.id === item.id);
        if (index >= 0) items[index] = item;
        else { item.id = `item-${window.crypto.randomUUID()}`; item.number = next++; items.push(item); }
      }
      if (items.length > 256) throw Error("本轮最多256条整改，请先撤回部分条目。");
      // 交还可以在此校验含摘要的实际传输全文。校验失败时编号、草稿、集合与存储
      // 均尚未提交，避免“完成草稿并复制”因全文超限而先清掉全部原始草稿。
      validatePayload(envelope(items));
      state.items = items; state.nextItem = next;
      for (const { key } of prepared) delete state.drafts[key];
      state.editor = null; state.tab = "rectifications"; state.filter = "all"; emit();
      return prepared.map((entry) => clone(entry.item));
    }
    function anchorUsers(id) {
      return { items: state.items.filter((item) => item.reference_ids.includes(id)), drafts: activeDrafts().filter(([, draft]) => draft.reference_ids.includes(id)).map(([key]) => key) };
    }
    return Object.freeze({ state, validTarget, recordFor, targetKey,
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      setPage(page) { if (!pages.has(page)) throw Error("未登记页面"); state.page = page; state.selection = null; emit(); },
      setMode(mode) { if (!["browse", "annotate"].includes(mode)) return; state.mode = mode; emit(false); },
      setCamera(page, camera) { if (!validCameras({ [page]: camera })) return; state.cameras[page] = { ...camera }; emit(); },
      select(record, explicitParent = false) {
        state.selection = record ? clone(record) : null;
        if (explicitParent && record?.target && state.drafts.unresolved) {
          // 只有明确点击“选择父层”才转移不可定位草稿；普通点选绝不静默重绑。
          const draft = state.drafts.unresolved; draft.target = clone(record.target); draft.excerpt = record.text;
          const key = targetKey(record.target);
          if (!state.drafts[key]) { state.drafts[key] = draft; delete state.drafts.unresolved; }
        }
        emit();
      },
      setCatalog(page, records) {
        if (!pages.has(page) || !Array.isArray(records) || records.length > 4096) return false;
        if (!records.every((record) => exact(record, ["key", "target", "text", "label", "has_parent", "req_ids", "interaction_id", "interaction_text", "interface_refs"])
          && text(record.key, 160) && (record.target === null || (validTarget(record.target) && record.target.page === page))
          && plain(record.text) && typeof record.label === "string" && Array.from(record.label).length <= 160 && typeof record.has_parent === "boolean"
          && plain(record.interaction_text) && validReqs(record.req_ids) && (record.interaction_id === "" || stableId(record.interaction_id))
          && optionalMetadata({ ...(record.interaction_id ? { interaction_id: record.interaction_id } : {}), interface_refs: record.interface_refs }))
          || new Set(records.map((record) => record.key)).size !== records.length) return false;
        catalogs.set(page, clone(records)); emit(false); return true;
      },
      clearCatalog(page) { catalogs.delete(page); if (state.page === page) state.selection = null; emit(false); },
      catalog(page = state.page) { return clone(catalogs.get(page) || []); },
      block() { state.blocked = true; emit(false); },
      setView(patch) { for (const key of ["tab", "filter", "showAnchors", "showItems", "activeAnchor", "activeItem"]) if (Object.hasOwn(patch, key)) state[key] = patch[key]; emit(false); },
      openEditor(target, itemId = null) {
        const item = itemId ? state.items.find((entry) => entry.id === itemId) : null;
        if (itemId && !item) throw Error("整改已撤回，不能继续编辑。");
        const actual = item?.target || target;
        if (actual !== null && !validTarget(actual)) throw Error("目标范围无效");
        const key = item ? `edit:${item.id}` : actual ? targetKey(actual) : "unresolved";
        const record = actual ? recordFor(actual) : state.selection;
        if (!state.drafts[key]) state.drafts[key] = { target: clone(actual), operation: item?.operation || "modify", message: item?.message || "",
          after_text: item?.comparison?.after_text || "", reference_ids: [...(item?.reference_ids || [])], editing: item?.id || null,
          excerpt: record?.text || "", req_ids: record?.req_ids || [], interaction_id: record?.interaction_id || "", interface_refs: record?.interface_refs || [] };
        state.editor = key; emit(); return state.drafts[key];
      },
      updateDraft(patch) {
        const draft = state.drafts[state.editor]; if (!draft) return;
        // 表单超长/非法字符也留在当前内存以供修复，不截断用户输入；完成时严格验证。
        for (const key of ["operation", "message", "after_text", "reference_ids"]) if (Object.hasOwn(patch, key)) draft[key] = clone(patch[key]); emit();
      },
      resumeEditor(key) { if (!Object.hasOwn(state.drafts, key)) throw Error("草稿已失效"); state.editor = key; emit(false); },
      closeEditor() { state.editor = null; emit(); },
      completeEditor() { return complete([state.editor]); },
      completeAll(validatePayload) { return complete(activeDrafts().map(([key]) => key), validatePayload); },
      activeDrafts,
      anchorUsers,
      addAnchor() {
        const target = state.selection?.target;
        if (!target || !recordFor(target)) throw Error("此动态元素没有可确认来源，请显式选择有来源的父层。");
        const previous = state.anchors.find((anchor) => targetKey(anchor.target) === targetKey(target)); if (previous) return clone(previous);
        if (state.anchors.length >= 256) throw Error("本轮最多256个定位标记。");
        const anchor = { id: `anchor-${window.crypto.randomUUID()}`, number: state.nextAnchor, target: clone(target) };
        envelope(state.items, [...state.anchors, anchor]); state.anchors.push(anchor); state.nextAnchor++; emit(); return clone(anchor);
      },
      removeAnchor(id) {
        const users = anchorUsers(id); if (users.items.length || users.drafts.length) throw Error("此标记仍被完成整改或活跃草稿引用，请先解除或撤回。");
        state.anchors = state.anchors.filter((anchor) => anchor.id !== id); emit();
      },
      withdrawItem(id) {
        const item = state.items.find((entry) => entry.id === id); if (!item) return;
        const key = `edit:${id}`; state.withdrawn = { item: clone(item), draft: state.drafts[key] ? clone(state.drafts[key]) : null };
        delete state.drafts[key]; if (state.editor === key) state.editor = null;
        state.items = state.items.filter((entry) => entry.id !== id); emit();
      },
      restoreItem() {
        if (!state.withdrawn) return;
        // 撤回后可能已有新整改补满容量。恢复必须先检查同一256条上限，
        // 拒绝时不修改集合、编号、单次撤回快照或其编辑草稿，也不触发持久化。
        // 现有视图的safe错误入口会显示原因，不能静默挤掉另一条整改腾位置。
        if (state.items.length >= 256) throw Error("无法恢复：已达256条整改上限；原撤回快照和编辑草稿仍保留。");
        const { item, draft } = state.withdrawn;
        // 条数合法不代表字节预算合法：撤回期间其他正文可能增大。候选集合必须
        // 经过与新增/导出相同的envelope预算，失败时保留原撤回快照和关联草稿。
        envelope([...state.items, item]);
        // 恢复保留原编号及可能失效的引用；显式报错要求解除，不删除引用或自动绑定其他A。
        state.items.push(item); if (draft) state.drafts[`edit:${item.id}`] = draft; state.withdrawn = null; emit(); return clone(item);
      },
      conflicts(target, operation, editing) { return state.items.filter((item) => item.id !== editing && targetKey(item.target) === targetKey(target)
        && ((item.operation === "delete") !== (operation === "delete"))); },
      exportPayload() {
        if (state.blocked) throw Error("来源绑定已改变，请重新准备评审包。");
        if (activeDrafts().length) throw Error("仍有未完成草稿，请先完成全部草稿或返回保留输入。");
        if (!state.items.length && !state.anchors.length) throw Error("尚无整改或定位标记可交还。");
        if (state.items.some((item) => !validItem(item) || item.reference_ids.some((id) => !state.anchors.some((anchor) => anchor.id === id)))) throw Error("存在失效的A引用或无效整改，请编辑解除后交还。");
        return envelope();
      },
    });
  }
  window.PrototypeReviewState = Object.freeze({ parseStartup, create, exact, stableId, sourceKey, checkFeedbackBytes });
})();
