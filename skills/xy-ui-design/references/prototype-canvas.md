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
  that HTML without separate state pages. 新交付由可信 CLI `open` 显式指定项目、adapter、需求、
  request-id 与具体页，返回 HTTP `delivery_url`，提供共用缩放画布和默认收起目录。
  “进入评审”以 `noopener` 新标签页准确打开当前页的 `review_url`；评审进入即批注，
  没有目录、持久浏览模式或开发说明。两页读取同一物理原稿，复用画布组件，各自保留相机和交互状态。
  新项目不生成额外导航 index、不复制通用工具；既有业务首页和未知文件不得按名称删除。
  历史 `prepare` 及 feedback 2／3／4 包独立保留原 index、资产和消费语义。
- For new pages, resolve `templates/prototype/page.html` through the current physical plugin's
  resource entry, and reuse the project's compatible `prototype.css` when present. Remove template
  references to plugin-only feedback/bridge resources from the project page; live 服务仅在 HTTP
  内存响应提供这些资源，不持久化第二份业务 HTML。 Create only authorized page/business-style paths. Preserve the
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
- 原稿页标题、说明、需求导航与五节契约保持在产品插槽之外。HTTP 交付壳从登记元数据派生
  默认收起目录，不在每页手抄。`file://` 原稿可离线查看与操作，但不承诺完整相机、目录或 Python
  冷启动；服务不可用时由交付方用相同显式参数重跑 `prototype_feedback_cli.py open` 并提供新链接。
  不在原稿写 token、机器路径或随机端口。产品导航、滚动与浮层仍属于产品区；评审时按工具提示的
  修饰键临时操作设计，释放回批注。真实 dialog／popover 在父画布保持可选择与可标注。
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

- 当前任务使用节点反馈时，按需读取 [反馈修订消费合同](prototype-feedback.md)。交付工具位于 HTTP 外壳，独立评审页进入即批注；用户修改提案不成为产品 DOM、已批准基线或任务批准。继续在原路径修改稳定 HTML，并沿原静态验收与适用视觉确认交付，不新建 spec、sidecar 或独立设计报告。
