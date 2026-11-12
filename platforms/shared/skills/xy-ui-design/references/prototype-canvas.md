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
  that HTML without separate state pages. `index.html` enters the grouped browsing workspace directly,
  hosting only the current page, without a separate directory landing layer or extra global header.
  Ordinary relative links in the single `nav#prototype-pages` are the registration source; groups use
  native details/summary. Keep an empty state when no actual pages are registered; do not register
  the page.html template or invented business pages. The workspace uses separate workspace.css/js;
  concrete pages load prototype.css, shared feedback.css target-highlight styles, and the minimal
  page-shell.js bridge. workspace.css/js and feedback.js remain index-only, keeping navigation
  styles and feedback state outside page fingerprints.
- For new pages, directly reuse `.agent-workflow/templates/prototype/page.html` and the project
  prototype directory's `prototype.css` without regenerating the presentation shell. Preserve the
  unified page header, `.prototype-stage`, `.prototype-frame`, product slot
  `data-prototype-page-content`, and bottom page contract. Fill in page information and explanations
  and set `data-prototype-platform` and `data-prototype-display`; Web defaults to `responsive`, while
  iOS/PC uses `fixed` with `--prototype-frame-width` and `--prototype-frame-height`. Replace placeholder
  content and complete the contract; template explanations are not project facts. If existing shared
  CSS lacks shell styles, add only missing `--prototype-*` presentation tokens and supporting shell
  rules from the runtime template CSS after confirming explicit write authority; do not overwrite
  product styles with an entire file. Without write authority, return to the PM to adjust current
  scope. Top-of-page layout explanations, actual display mode/dimensions, and contract records must agree.
- Arrange each concrete HTML vertically: current page name, compact summary, and circular back control
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
- At the top of the current page, use a circular back control with a light background, thin border,
  and black left chevron, providing a name and visible focus without relying on browser history.
  Inside the workspace, back only expands the sidebar/current group and focuses the current link
  while preserving the view; a standalone page returns to its page deep link in index. Use a separate
  toggle to expand/collapse the sidebar. Demo data, reset-on-refresh behavior, unimplemented scope,
  and necessary pending confirmations belong to the explanations after the view; actual business
  messages remain inside the artboard. The product's own navigation, scrolling, and overlays do not
  move into the outer workspace.
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

- 当前任务使用节点反馈时，按需读取 [反馈修订消费合同](prototype-feedback.md)。反馈工具保持在默认折叠的展示外壳内；用户修改提案不成为产品 DOM、已批准基线或任务批准。继续在原路径修改稳定 HTML，并沿原静态验收与适用视觉确认交付，不新建 spec、sidecar 或独立设计报告。
