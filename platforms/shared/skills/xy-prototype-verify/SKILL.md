---
name: xy-prototype-verify
description: Use when a design Agent must statically validate concrete build-free HTML pages before user visual review, visual approval, or required-prototype production UI work.
---

<!-- agent-workflow-pack:managed-skill -->

# xy-prototype-verify

The active concrete page and its in-page `Page design and interaction contract` are the design
evidence. The verifier is read-only: it validates the stable workspace and returns deterministic
static evidence without creating metadata, reports, screenshots, or revision copies. The prototype
is a user-review artifact; this procedure is not a second visual reviewer or an automated UI test.

## Required checks

This procedure applies only to prototype-mode work. For `design_mode: standards_only`, return to
the PM's standard-maintenance task without running these checks, creating prototype files, or
requesting visual approval. A preloaded Skill is not a mandate to execute an inapplicable procedure.

1. Use the exact project adapter already selected for this task to resolve `docs.standards_root`, then derive its `prototype` child. The
   default active workspace is:

   ```text
   docs/standards/prototype/index.html
   docs/standards/prototype/prototype.css
   docs/standards/prototype/workspace.css
   docs/standards/prototype/workspace.js
   docs/standards/prototype/feedback.css
   docs/standards/prototype/feedback.js
   docs/standards/prototype/page-shell.js
   docs/standards/prototype/<stable-page>.html
   ```

2. Run the repository validator from the project root:

   ```bash
   bash .agent-workflow/lib/python_runtime.sh .agent-workflow/lib/documents/validate_prototype_workspace.py \
     <project-root> docs/standards/prototype --adapter <selected-project-adapter> --json --page <stable-page>.html
   ```

   For an official plugin installation, use its verified source-pack entry and the same selected adapter:

   ```bash
   bash <physical-plugin-root>/lib/python_runtime.sh <physical-plugin-root>/plugins/source_pack.py \
     helper --project <physical-project-root> lib/documents/validate_prototype_workspace.py \
     <physical-project-root> <docs.standards_root>/prototype --adapter <selected-project-adapter> \
     --json --page <stable-page>.html
   ```

   Use `.awf/project.yaml` for the newly applied plugin adapter, or the explicitly selected existing
   `project.yaml`. Both may coexist; never choose again by precedence or create a root configuration as
   a fallback. Central tasks retain their fixed runtime and `.agent-workflow/project.yaml`.
   Substitute the configured project-relative `docs.standards_root` path when it differs. A nonzero
   exit is FAIL. Do not weaken or bypass its path, dependency, structure, contract, or interaction
   checks. Repeat `--page` for multiple scoped concrete pages; omitting it returns all concrete pages.
   Keep the returned per-page fingerprints as internal evidence, not a user-facing JSON report.
3. Verify every scoped active page contains exactly one non-empty
   `Page design and interaction contract` with these exact five sections:

   ```html
   <section data-contract-section="purpose">...</section>
   <section data-contract-section="navigation">...</section>
   <section data-contract-section="interactions">...</section>
   <section data-contract-section="states">...</section>
   <section data-contract-section="exceptions">...</section>
   ```

   Each material interactive control needs a stable `id`, exactly one matching
   `data-contract-for`, and executable declared outcomes.
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
   routing. workspace.css/js and local feedback.js belong only to the index; concrete pages use minimal page-shell.js.
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
5. Confirm the workspace opens through `file://` with ordinary relative navigation and without a
   build, package installation, framework, router, external CDN, live API, database, account,
   credential, or real user data.
6. Use the same command's per-page dependency fingerprints, computed from the safe local transitive
   dependency closure defined by `product/WORKFLOW.md`. Do not reconstruct the algorithm in a separate
   script. To compare approved evidence, add `--expect <stable-page>.html=<approved-sha256>` for every
   scoped approved page. A mismatch exits nonzero and blocks use of the stale scoped approval.
   External, workspace-escaping, missing, dynamic, or unsupported dependencies are FAIL. Only the PM
   may carry non-material changes forward after the documented old/new-delta review and retained user
   approval; uncertain or material changes return to the existing scoped visual-confirmation step.
   The verifier never grants approval or decides visual equivalence.
7. The design Agent performs three self-checks in the same handoff: requirements coverage compares the five
   contract sections with frozen requirements/acceptance; standards conformance checks applicable built-in
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

仅当前任务使用节点反馈时，读取 [反馈消费合同](../xy-ui-design/references/prototype-feedback.md)，通过当前物理插件根白名单 helper 的 `prepare`／`validate` 消费当前绑定；它复用本校验器的安全依赖闭包，不替代上述静态检查。`validate` 失败、需求 SHA 或页面依赖失效时保留原意见，返回 PM 处理；输出 `changes` 只用于当前授权原型修订。修订后仍返回上述 `prototype_verify` 证据，适用需求／视觉批准沿既有规则，反馈不产生批准、自动 patch 或新增业务 gate。

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

Before user handoff, the PM independently compares all five in-page contract sections with the frozen
approved requirements and acceptance criteria. The PM rejects omitted, invented, broadened, or
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

The root prototype index alone is not sufficient.

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

Use `localhost_url` only when one already exists as a convenience. The concrete HTML path remains
authoritative.
