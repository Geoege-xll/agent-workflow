---
name: xy-prototype-verify
description: Use when a design Agent must statically validate concrete build-free HTML pages before user visual review, visual approval, or required-prototype production UI work.
---

从本 Skill 的物理目录向上两级确定插件根。使用同包的[宿主资源说明](../../plugins/antigravity/plugin-context.md)。当前实例已具备同一物理来源、同一版本的完整说明时直接复用；独立启动或内容缺失时补读，来源或版本变化时重新读取。


<!-- agent-workflow-pack:managed-skill -->

# xy-prototype-verify

The active concrete page and its in-page developer notes are the design
evidence. The verifier is read-only: it validates the stable workspace and returns deterministic
static evidence without creating metadata, reports, screenshots, or revision copies. The prototype
is a user-review artifact; this procedure is not a second visual reviewer or an automated UI test.

## Required checks

This procedure applies only to prototype-mode work. For `design_mode: standards_only`, return to
the PM's standard-maintenance task without running these checks, creating prototype files, or
requesting visual approval. A preloaded Skill is not a mandate to execute an inapplicable procedure.

1. Use the exact project adapter already selected for this task to resolve `docs.standards_root`, then derive its `prototype` child. The
   new project contains only concrete pages and necessary business styles:

   ```text
   docs/standards/prototype/prototype.css
   docs/standards/prototype/<stable-page>.html
   ```

2. Run the plugin validator with the actual project and selected adapter:

   ```bash
   bash <physical-plugin-root>/lib/python_runtime.sh <physical-plugin-root>/plugins/source_pack.py \
     helper --project <physical-project-root> lib/documents/validate_prototype_workspace.py \
     <physical-project-root> <docs.standards_root>/prototype --adapter <selected-project-adapter> \
     --standalone --json --page <stable-page>.html
   ```

   Use `.awf/project.yaml` for the newly applied plugin adapter, or the explicitly selected existing
   `project.yaml`. Both may coexist; never choose again by precedence or create a root configuration as
   a fallback.
   Substitute the configured project-relative `docs.standards_root` path when it differs. A nonzero
   exit is FAIL. Do not weaken or bypass its path, dependency, structure, contract, or interaction
   checks. `--standalone` requires explicit concrete `--page` values and does not require index or
   prototype.css/js. Repeat `--page` for multiple scoped pages. Existing workspaces may retain
   `docs/standards/prototype/index.html`; omit `--standalone` only for the strict legacy workspace
   check, whose existing index and local-tool checks below remain applicable. Do not copy the generic
   plugin shell into a new project to satisfy that legacy entry.
   Keep the returned per-page fingerprints as internal evidence, not a user-facing JSON report.
3. 每个具体页保留一个默认折叠的 `details.prototype-contract`，首个 summary 写「开发说明」。
   只核对操作原型后仍不明确、且已有决定的交互。已有规则链接至需求 Markdown 原章节，无补充时允许为空；
   未决行为交 PM。旧稿原有分节可读。重要控件保留稳定 ID；如有 data-contract-for，目标须唯一且确实可交互。
   保留已确认目录分组，并核对真实登记页在各自层级中只出现一次；无来源的旧页仍可访问。
   Native disclosure controls may map the stable ID of a `details` element's first direct-child `summary`
   to the interaction contract. Same-name tags in ordinary containers or a second summary do not count as
   executable disclosure controls. The index may group pages with native `details/summary` inside the single
   `nav#prototype-pages`; ordinary relative links to concrete pages remain the registration source.
   The index may directly host registered concrete pages through one `iframe#prototype-preview` with an
   accessible name. Static src must use the exact canonical local page name; prohibit srcdoc, external/
   out-of-bounds/unregistered targets, self-nesting and extra frames. The iframe still validates the actual
   concrete page and rendering-resource closure; the document-navigation exemption below does not apply,
   and product pages gain no frame permission. The production entry loads pages only through local workspace.js,
   derived from the single registered navigation. Before initialization, the iframe is hidden with no src;
   empty registration shows an explicit empty state. A static design entry without a controller still needs
   an explicit src pointing to a registered page. The index rejects meta refresh, arbitrary scripts and inline
   routing. These index/controller rules apply to existing legacy workspaces only. New projects
   keep workspace.css/js, feedback.css/js and page-shell.js in the plugin and derived review bundle;
   prepare-delivery 仅插入固定相对 entry 标签并准备受管链接／精确忽略项，通用工具留在中央；HTTP 内存响应在原始字节定位后移除该精确标签并装桥，不落盘业务 HTML 副本。普通 symlink/hardlink 仍拒绝，受管入口例外须验证属主／版本／摘要；历史 prepare 保持原派生包语义。
   Shared feedback.css provides the outer panel and target highlight styles; it remains a real local dependency.
   Requirements-bound concrete pages declare the canonical Markdown path under configured plans with
   `body[data-prototype-plan-source]`, and provide one `data-prototype-document="markdown"` link in a
   single `nav.prototype-requirement-links`. One same-name historical HTML link marked
   `data-prototype-document="html"` is optional when that actual file exists. Every document link uses
   `target="_blank"` and `rel` containing `noopener`. Only this slot allows navigation across the prototype
   root. An unbound source template may leave it empty; do not fabricate links. The validator checks safe
   actual files, canonical target binding and concurrent replacement. It does not scan Markdown's reverse
   prototype links, require historical HTML freshness/records/renderer identities, or add documents to
   page-rendering dependencies. Requirements/plan Markdown-to-HTML generation is retired;
   old derived content cannot block Markdown revisions.
4. Confirm every changed prototype path is under the configured
   `docs.standards_root/prototype`, except a separately task-authorized design-standard leaf
   update under `docs.standards_root/DESIGN_*.md`. Reject revision-suffixed, dated, `final`, `new`, or
   task-scoped page copies.
5. Confirm each source page opens through `file://` with its real interactions and without a
   build, package installation, framework, router, external CDN, live API, database, account,
   credential, or real user data. Agent／PM 交付前必须先 prepare-delivery，再由可信 open 验证；delivery_url／delivery_urls 是具体 file HTML 完整工具入口，未准备的裸模板不能作为完整交付。
   离线 HTML 不能冷启动 Python 或发现随机端口；服务不可用由交付方重跑相同显式 open 参数并提供
   新链接，不向项目原稿写认证信息、机器路径或随机端口。
6. Use the same command's per-page dependency fingerprints, computed from the safe local transitive
   dependency closure defined by `product/WORKFLOW.md`. Do not reconstruct the algorithm in a separate
   script. To compare approved evidence, add `--expect <stable-page>.html=<approved-sha256>` for every
   scoped approved page. A mismatch exits nonzero and blocks use of the stale scoped approval.
   External, workspace-escaping, missing, dynamic, or unsupported dependencies are FAIL. Only the PM
   may carry non-material changes forward after the documented old/new-delta review and retained user
   approval; uncertain or material changes return to the existing scoped visual-confirmation step.
   The verifier never grants approval or decides visual equivalence.
7. The design Agent performs three self-checks in the same handoff: requirements coverage compares the concrete page behavior, developer notes and linked requirements with frozen requirements/acceptance; standards conformance checks applicable built-in
   rules and project-specific standards; delivery consistency checks pages, controls, navigation, declared
   outcomes, shared styles and current dependency fingerprints. Omissions, unauthorized additions, conflicts
   or unresolved inconsistency are FAIL. Check only current scope and state exceptions/unverified behavior.
   This requires neither rendering nor a browser and creates no independent prototype QA.
8. Confirm that every concrete changed page can be handed to the user through its direct absolute
   HTML path, and that the handoff names the changed scope and declared operation sequence. Static
   validation proves file readiness; it does not claim that an Agent rendered or operated the page.
9. Record `baseline_ready`, `ia_ready`, `prototype_verified`, and `visual_review_ready` only as
   automatic workflow evidence. Only the PM may record `visual_approved`, and approval remains in
   workflow task state. PM preserves recoverable approval evidence in the existing saved plan when
   the task-level policy saves one; this verifier creates no plan or companion approval document.

## 按需反馈复核

具体页交付与按需反馈复核使用[反馈消费合同](../xy-ui-design/references/prototype-feedback.md)。
通过插件 `source_pack.py resource` 定位或以 `helper` 调用 `lib/documents/context_read.py`
分页时，使用 `platforms/shared/skills/xy-ui-design/references/prototype-feedback.md`。
交付按步骤 5 准备和核对当前 file 入口，批注、来源校验和历史格式按需读取该合同。
仅在当前授权范围内应用已复核的意见，修订后返回当前静态证据；保留既有需求与适用视觉批准。

生产 `templates/prototype` 工具的真实浏览器集成验证用于验证模板产品本身，不能扩张为业务原型默认浏览器操作，亦不改变以下边界。

## Prototype browser boundary

Prototype verification MUST NOT invoke Computer Use or browser automation by default. Do not open
or operate prototype pages through Computer Use, Playwright, `/browser`, a browser MCP, or an
equivalent UI-driving tool merely to reach `prototype_verified` or `visual_review_ready`.

Only either of these user-originated conditions permits the smallest scoped prototype-browser
operation:

1. the user explicitly requests automated operation or browser testing of the prototype; or
2. the user reports that the prototype cannot open or that a concrete interaction is broken, and
   browser operation is needed to diagnose that reported failure.

Prototype complexity, interaction count, material UI risk, host capability, PM preference, or
missing browser evidence does not create an exception. An allowed diagnostic operation is not a
default gate, does not replace user visual approval, and must not create persisted browser evidence.

## Verification ownership and PM review

The `xy-uiux` task owns the deterministic static prototype-verification coverage defined above and
returns current, internally consistent evidence. Record requirements-coverage, standards-conformance and
delivery-consistency self-checks in existing `static_checks` below, issues in `blocking_findings`, and the
conclusion in `result`; add no report or approval. The user still gives final confirmation of concrete pages,
and functional QA after production implementation remains. A host without browser capability is fully capable
of completing the default procedure; browser evidence is not required and the PM must not supplement
it merely because the host could not render or operate the prototype.

Before user handoff, the PM independently compares the concrete page behavior, developer notes and linked requirements with the frozen
approved requirements, applicable solution decisions and acceptance criteria. The PM rejects omitted, invented, broadened, or
conflicting behavior and returns it to `xy-uiux`; it must not ask the user to approve a knowingly
divergent contract. The PM also reviews scope, contract completeness, static evidence freshness and
consistency, fingerprints, and the user-approval handoff. This is a text-and-requirements conformance
review, not browser testing. The PM does not repeat completed static verification. Missing, stale, or
contradictory evidence or a fingerprint mismatch triggers only the smallest affected static recheck;
it does not authorize Computer Use or create a second verification pass.

Integrated QA consumes this frozen handoff instead of activating this procedure again. QA may run
deterministic workspace validation and dependency-fingerprint recomputation, whose machine process
reads complete dependency bytes, but QA does not open or automate the prototype and does not preload
the complete prototype source tree. Missing or stale handoff evidence returns to the PM for
`xy-uiux` rework. This restriction applies to the prototype artifact, not to risk-based testing of
the real production implementation.

## User handoff boundary

The PM MUST provide a direct link to each concrete changed page.

新交付先 prepare-delivery，再提供可信 open 验证的具体页 file URI delivery_url；该 HTML 就是完整交付入口，单独根 index 或未准备模板不足以交付。

The visual-confirmation workflow MUST NOT generate, persist, attach, or present screenshots.
Do not create image assets unless the user explicitly requests an image asset; an image never
substitutes for the interactive page.

Do not create companion design, mapping, QA, or baseline Markdown; a Manifest; a screenshot
directory; or any other companion metadata. Update stable pages in place.

## Report

Return only concise task evidence:

```yaml
prototype_verify:
  result: PASS | FAIL
  prototype_refs:
    - path: <docs.standards_root>/prototype/<stable-page>.html
      clickable_absolute_path: <absolute-html-path>
      localhost_url: null
      dependency_fingerprint: <verified-value>
      changed_scope: []
      declared_operation_sequence: []
  validator:
    command: <exact-command>
    exit_code: <integer>
  static_checks: [] # 复用此列表记录需求覆盖、规范符合性、交付一致性及各自证据/限制
  blocking_findings: []
  pending_business_gate: none | visual_approved
```

交付时 `clickable_absolute_path` 指向 prepare-delivery 后的具体 HTML，正文提供 open 返回的 file URI delivery_url；`localhost_url` 仅可填独立评审无秘密引导 URL 或 null，不能误当正式交付入口。物理 HTML 是原稿权威和完整交付入口，file 不启动／发现服务或持有控制 token。
