# Design Standards Lifecycle and Ownership

Read for initial design-system establishment, reusable rule changes, visual replacement, or standard
maintenance. This supports the existing workflow; it adds no approval gate, review role or project record.

## Assess Before Updating

In existing plan/task state, PM records whether standards need updating, why, platform/module scope,
exact files, approval basis and rule delta. Do not create another report or expose raw YAML/JSON.

- First establishment: capture confirmed reusable rules; a populated template is not a completed baseline.
- Existing visual reuse: reuse standards and shared styles; no new rules means no update.
- Incremental change: update only affected reusable tokens, components, states or layout rules.
- New visual system: identify replaced rules and authorized scope; adopt approved replacements in place,
  without accumulating competing v2/final authorities.
- Mechanical revision: typo, link and already-decided value synchronization is not a redesign.

Assess standards separately from PROJECT/feature projection. A visual-only change may leave feature
documents unchanged while requiring changed design rules. Page-specific flows stay in the page contract;
shared standards do not copy page contracts or task history.

## Ownership and Minimum Tasks

- PM decides whether to update, replacement scope, approval basis and exact owned_paths, then reviews the result.
- UI Agent is the primary author of design-standard content, limited to explicitly authorized leaves.
- PM may perform mechanical edits directly without an extra Agent. If represented in the task graph,
  use the same restricted xy-uiux maintenance contract; main-session identity does not bypass path protection.
- PM updates the STANDARDS directory and links when files are added, removed or split. Never give a Writer the whole tree.
- Implementation Agents own production tokens, shared components and layout, return exact mappings
  and constraints, and do not independently change the design direction.
- QA remains read-only and checks authorization, before/after rule differences and implementation;
  it must not weaken standards to conceal defects.

Each shared standard, prototype.css or production token file has one explicit writer. Parallel page
designers must not race on shared files. Delegate professional judgment to UI Agent; do not create
administrative microtasks for simple synchronization.

## Two Design Task Modes

Keep role: xy-uiux and surface_kind: design_ui. Omitted design_mode means prototype.

- prototype: produce/change prototypes only for related tasks with user-selected prototype_policy:
  required. Follow existing standards reading, design, static verification and user visual confirmation;
  authorized standard leaves may be updated in the same scope.
- standards_only: maintain exact normative Markdown leaves only. Do not write prototype/, references/,
  HTML, CSS, production source or the STANDARDS index; PM maintains the index. Existing requirements
  approval, STANDARDS reading contracts and ui/accessibility/standards-conformance audit surfaces remain.
  Do not invoke xy-prototype-verify, automate a prototype browser, request/declare visual_approved,
  or require the user to establish a prototype. Return rule delta, basis, scope and document validation.

waived_by_user may have necessary standards_only prerequisites, but no hidden transitive prototype
task. The required branch still needs a genuine prototype task; maintenance cannot substitute page
design evidence. UI-Conformance cannot silently change authority through maintenance; classify an
actual authority change through the existing design-change route. ui_contract.prototype_paths only
declares a protection boundary; pure maintenance does not require the directory or any HTML to exist.

## Approval, Adoption and Fingerprints

Candidate rules belong to the current proposal, not approved global constraints. UI Agent prepares
authorized changes; PM retains the previous basis and pending delta and prevents other tasks from
treating candidates as adopted authority. An existing compatible baseline may be captured under
approved scope. A single approved page does not authorize an unapproved global redesign.

PM assesses durable rule capture after initial visual confirmation; with an explicit baseline or
maintenance request, assess before dispatch. Updates trace to existing requirements approval and,
when prototypes were selected, applicable visual approval. This is not a third confirmation.
waived_by_user uses approved requirements and explicit design decisions, without restoring prototype
confirmation. Missing consequential decisions return to existing requirements clarification;
the Writer cannot invent approval.

Adopt new rules before related production Writers/QA consume them, not after production QA finishes.
PM checks the delta against approval, then refreshes current standards_contract, affected
controlled_document_access, design_authority_refs and index/leaf fingerprints.
First preserve original input contracts and recoverable before-content/diff evidence in existing
input_contracts/task evidence; an old hash without retrievable content is insufficient.
controlled_document_access is the current runtime snapshot, not historical proof of reading. Refresh
all affected tasks retained in the graph, including completed tasks. Keep original inputs unchanged;
refreshing neither claims that a completed task read new rules nor changes its state or reruns it.
Downstream tasks actually read adopted rules on dispatch. A design_standard authority fingerprint
must match the current same-path leaf contract. CLI validates only current snapshots, not historical
evidence content, and never refreshes approval or fingerprints automatically; PM/QA review the evidence.

Send updated inputs only to affected tasks; do not repeat unrelated or unaffected completed work.
Shared CSS/prototype dependency changes require affected page fingerprint refresh; material visual
changes still use existing visual confirmation. Mechanical document edits do not independently
trigger visual confirmation. A fingerprint refresh does not create user approval.
If the design is canceled, PM reverses only this task's unadopted candidate changes and preserves user edits.

Distinguish adopted design authority from completed production migration. Scope staged adoption by
platform/module and identify where old rules remain applicable, without declaring conflicting global
authorities. Project completed migration facts into existing feature/PROJECT documents only after
corresponding implementation passes QA, if needed. Do not put migration logs in standards or indexes.
Standard updates never automatically save agentmemory; assess durable non-obvious knowledge separately.

## Single Source and Replacement Boundaries

- FOUNDATIONS: visual direction, semantic tokens, typography/spacing, platform and accessibility rules.
- COMPONENTS and applicable platform leaves: reusable component, state, interaction and layout constraints.
- prototype.css: shared prototype style implementation; implementation Agents own production tokens/components.
- Concrete HTML: page contract and confirmation material. index.html is a thin directory, not another full standard.

默认设计规范已提供语义颜色、尺度和常用组件行为要求。接入项目时沿用现有 token／组件
定义，只补当前设计范围缺失的映射、变体与平台差异；有模板不等于已有批准的项目基线。
UI Agent 负责专业内容，PM 按已有决策采用，相关实现 Agent 和 QA 使用同一套适用规则。
首次设计或全新视觉的候选值经现有确认后写回授权规范；未改变规则的小任务无需更新。
官方来源放在两份设计叶文档末尾供按需核对，不要求每次联网、全文重读或新增报告。
原型展示 token 与产品 token 分开；Web 默认响应式产品区，iOS／PC 默认固定画板。
两种展示方式共用页头说明、返回目录和页底契约，不影响原型可选分支。

A new visual system replaces only authorized platform/module rules. Preserve applicable accessibility,
engineering, security and upstream boundaries; redesign is not permission to relax other constraints.
Preserve stable IDs when semantics remain unchanged. Make actual retirement/replacement traceable in
the current delta, avoiding conflicting old/new hard rules in the same scope. Choose hard/advisory by
actual constraint type; incidental page styles are not automatically global hard rules.

Within existing request QA, inspect approval, before/after rule delta, scope, conflicts, production
mapping and document links. standards_only audit covers normative changes and applicable constraints;
missing HTML/browser evidence is not FAIL. Where implementation exists, audit adopted rules while
checking that replacing old constraints was authorized; the author's freshly edited standard alone
cannot justify PASS. Return conflicts or omissions to PM instead of editing standards.

Validate affected structure, rule IDs and links with existing validate_project_docs.py. Select
production tests by actual implementation risk; changing standards alone does not require all business
tests or repeat valid prototype static evidence. Keep existing requirements confirmation, optional
prototype confirmation and QA closeout.
