# Unified HTML Prototype Canvas Format (Only `prototype` Mode)

Use only within the currently authorized prototype-design scope, carrying forward the existing
`xy-uiux` canvas contract. Final delivery remains high-fidelity interactive HTML; early wireframes
serve only IA. The presentation canvas does not replace product design, create prototypes for other
branches, or add confirmation.

- The deliverable remains a directly openable HTML prototype with demonstrable interactions. Figma
  is only an analogy for the canvas presentation; do not switch delivery to a design tool or require
  an editor, draggable artboards, or toolbars.
- Each product page has one independent, stable HTML file; update existing pages in their original
  files and add files only for new pages. Output separately the different platform pages that need
  design; do not combine multiple product pages in one HTML or force presentation of all three
  platforms. Demonstrate a page's dialogs, loading, empty, error, and success states interactively in
  that HTML without separate state pages. Agent／PM 交付前先用可信 CLI `prepare-delivery --root --adapter --pages` 幂等准备入口，再由 `open` 显式指定项目、adapter、需求、
  request-id 与具体页；open 缺准备报 preparation_required，不改业务 HTML。返回具体 HTML 的 file URI `delivery_url` 及 `delivery_urls`，提供完整共用缩放画布和默认收起目录。未准备的裸模板不作为完整交付。
  “进入评审”以 `noopener` 新标签页准确打开当前页的 `review_url`；评审进入即批注，
  没有目录、持久浏览模式或开发说明。两页读取同一物理原稿，复用画布组件，各自保留相机和交互状态。
  新项目不生成额外导航 index、不复制通用工具；既有业务首页和未知文件不得按名称删除。
  历史 `prepare` 及 feedback 2／3／4 包独立保留原 index、资产和消费语义。
- For new pages, resolve `templates/prototype/page.html` through the current physical plugin's
  resource entry, and reuse the project's compatible `prototype.css` when present. Do not activate missing tool dependencies in the bare template; prepare-delivery 在首个业务脚本之前插入固定相对 entry 标签，并准备受管 `.xy-prototype-entry` 链接及精确忽略项。通用资源留在中央工具中，不持久化第二份业务 HTML。 Create only authorized page/business-style paths. Preserve the
  unified page header, `.prototype-stage`, `.prototype-frame`, product slot
  `data-prototype-page-content`, and bottom page contract. Fill in page information and explanations
  and set `data-prototype-platform` and `data-prototype-display`; Web defaults to `responsive`, while
  iOS/PC uses `fixed` with `--prototype-frame-width` and `--prototype-frame-height`. Replace placeholder
  content and complete the contract; template explanations are not project facts. If existing shared
  CSS lacks shell styles, add only missing `--prototype-*` presentation tokens and supporting shell
  rules from the runtime template CSS after confirming explicit write authority; do not overwrite
  product styles with an entire file. Without write authority, return to the PM to adjust current
  scope. Top-of-page layout explanations, actual display mode/dimensions, and contract records must agree.
- Arrange each concrete HTML vertically: current page name and compact summary
  → high-fidelity product view → requirements Markdown, optional historical HTML, platform/dimensions,
  and necessary demo explanations → a five-section contract collapsed by default. The single
  nav.prototype-requirement-links requires one explicit markdown link and allows one html link only
  when the corresponding historical file exists; the body's data-prototype-plan-source binds the
  canonical Markdown under the configured plans directory. Every document link opens independently
  with target="_blank" and rel containing noopener. Plan Markdown-to-HTML generation is retired.
  Leave unbound templates empty without fabricated links. The iOS/PC product area is a horizontally
  centered fixed artboard; the Web product area defaults to a naturally expanding responsive webpage.
  The contract area stays outside the product area and is collapsible by default; it does not consume
  product-interface space or remain fixed over the bottom of the browser.
- Use a simple, neutral outer presentation canvas; its background, dimension labels, presentation
  navigation, and contract area are not part of the product interface. Do not require wallpaper or
  generate background images. The artboard contains only the current page's product interface and
  its interactions.
- 原稿页标题、说明、需求导航与五节契约保持在产品插槽之外。具体 `file://` HTML 是完整交付入口，目录来自项目公开 catalog，当前页按真实文件名选择，不用单一 active_request 覆盖其他请求页。唯一 delivery.html shell 投影到中央经典脚本，项目不手抄工具或业务 HTML。file 顶层在业务执行前装配唯一壳，一层独立设计 iframe 执行业务一次；仅此 file 分支允许 allow-scripts allow-same-origin，支持相对业务资源。HTTP 评审仍仅 allow-scripts。公开 binding 无 token，只用于 noopener 同页评审引导；file 不建立控制连接或拿 token。准备或 binding 失效准确提示交付方重跑显式 prepare-delivery／open，不猜端口、不冷启动、不虚称 ready。原稿不写机器路径、端口、认证或动态 review_id。父子同时验证准确 window、page、nonce 和 null origin；HTTP 引导须独立核验顶层导航并仅在响应内提供秘密。产品导航、滚动与浮层仍属于产品区；评审时按提示修饰键临时操作，释放回批注。真实 dialog／popover 在父画布保持可选择与可标注。完整 file 交付壳的目录与相机工具浮于画布，不挤占产品画面，不再显示旧大标题背景；五段契约保留原稿结构，在交付壳以大弹窗查看。下述原稿的自然阅读顺序不要求工具壳重复展示整段说明。详见反馈合同。
- First determine platform and layout scope from the current task and project design standards.
  For fixed previews, reuse existing baseline dimensions first; if no baseline exists, choose and
  explicitly explain one. Responsive Web needs no invented fixed dimensions. Keep previews consistent
  within the same platform and design scope; use logical dimensions (CSS px), not device physical pixels.
- iOS: Use a fixed-width, fixed-height artboard for the selected iPhone, reflecting its safe areas,
  status bar, and bottom gesture area.
- PC clients: Use the project's selected fixed baseline window dimensions, presenting the title bar
  and window controls according to the actual product and target platform. macOS may show red/yellow/
  green buttons; do not apply that appearance to Windows or frameless clients.
- Web: Default to `responsive`; `.prototype-frame` is only a content container without window
  decoration. Do not fix its width/height, add device borders, or force internal scrolling. Lay out
  content according to available width and project responsive rules, allowing ordinary media queries;
  the product's own maximum content width and navigation still follow project standards, and the three
  presentation areas remain independent. Use `fixed` only when fixed-viewport comparison is explicitly
  required, and record baseline dimensions.
- In `fixed` mode, the outer browser is only a presentation canvas and cannot alter the artboard's
  internal baseline layout. Layout breakpoints follow artboard container queries; appearance/
  accessibility media queries may remain. When space is insufficient, allow canvas scrolling or
  proportional scaling without stretching, changing aspect ratio, or clipping necessary actions.
  Long product content scrolls in designated areas inside the artboard; top bars, bottom bars, and
  in-page overlays use the artboard as their layout boundary instead of the entire browser window.
- Keep the contract's existing five sections. In `purpose`, record the target platform and display
  mode in English; for fixed previews, also record the baseline device/window, width/height, and
  scaling explanation; for responsive Web, record applicable layout scope. Product copy follows the
  project language; do not add contract sections, separate explanatory documents, or screenshots.
- Fixed dimensions constrain only the prototype preview, not the actual product's multi-device
  adaptation, Web responsiveness, or client-window resizing. Add no confirmation stages, automated
  browser operations, or QA process. Apply only to the currently authorized prototype task without
  automatically reworking all existing prototypes; this creates no prototype tasks for
  `standards_only` or user-selected direct-development branches.

- 当前任务使用节点反馈时，按需读取 [反馈修订消费合同](prototype-feedback.md)。交付工具位于具体 file HTML 装配的中央外壳，独立评审页进入即批注；用户修改提案不成为产品 DOM、已批准基线或任务批准。继续在原路径修改稳定 HTML，并沿原静态验收与适用视觉确认交付，不新建 spec、sidecar 或独立设计报告。
