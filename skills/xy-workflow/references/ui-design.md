新页面或新流程，先核对本次目标与验收，再从同一需求主题取得影响原型的已确认方案，包括角色、状态转移、权限、失败提示与恢复。只向 `xy-uiux` 交付已就绪的范围；尚有实质分歧时由 PM 先取得对应决定，原型用于呈现和检验已定行为。仅原型同样遵守这一顺序，最后停在设计交付。详见[当前请求的确认](requirements-confirmation.md)。

设计交接时，PM 按[任务池派发](dispatch.md#continuous-intake-dispatch)逐个领取已就绪的独立原型任务，并将每个任务绑定到宿主实际创建的 `xy-uiux` 实例。

- Ordinary low-risk Light UI copy uses production_ui with existing UI-Conformance, zero design delta,
  real resolved/frozen authority and engineering/design standards. Retain minimum verification and
  handoff risk assessment without forcing Full planning/confirmation/QA. Actual design/interaction
  changes are Full; non_ui labels, empty authority or splitting changes must not bypass standards.
- `project.yaml` → `docs.standards_root/prototype/` is the stable prototype workspace.
  It keeps one in-page developer notes per page and its page dependency
  fingerprint. Required-prototype QA lets the machine read complete bytes; the QA Agent reads only
  that contract and the smallest relevant source slice. A waived route skips old-prototype
  comparison but keeps production UI/accessibility QA.
- Classify `UI-Conformance` only when current approved requirements and controlled evidence fully
  determine the result. Record `route: UI-Conformance`, `design_delta: none`,
  `prototype_policy: not_applicable`, `prototype_decision: null`, structured resolved
  and fingerprinted `design_authority_refs`, affected surfaces, and the objective justification in
  the task pack.
  It does not dispatch `xy-uiux`, does not mutate a prototype, and does not require
  `visual_approved`. Except for the explicit Light copy above, it remains Full, retaining Full planning coverage,
  xy-plan, applicable user decisions, xy-build-verify and integrated QA; Light does not relax other UI changes.
- A `UI-Conformance` task must not edit `docs.standards_root/DESIGN_*.md`. Its production writer
  uses the frozen authority references and declares both UI and accessibility audit surfaces.
  Missing, stale, contradictory, incomplete, or choice-requiring evidence stops the affected write:
  reclassify the request as `UI-Patch`, `UI-Page`, or `UI-Flow`, update the plan, and reopen
  only the requirement, solution or page decision affected by the actual change. A small diff, delivery pressure, or a
  request to skip design is not proof of a zero design delta.
- With `prototype_policy: required`, `UI-Patch`, `UI-Page`, and `UI-Flow` production tasks use
  `design_delta: changed`, depend on the matching `xy-uiux` task, and carry a resolved
  `prototype_contract`. Each prototype authority maps
  exactly to `visual_approved:<authority_id>@<content_fingerprint>`; a stale, generic, or unrelated
  visual Gate does not unlock production. The task also carries the selection record below; a PM
  default or existing prototype files cannot substitute for user choice.
- Both design-change branches carry `prototype_decision` with source
  `requirements_confirmation_user_choice`, a stable `user:` choice reference, the current
  requirement SHA-256, exactly matching affected surfaces, `recommended_policy`, a non-empty
  `recommendation_reason`, and `selected_policy` equal to `ui_change.prototype_policy`. The PM must
  not invent or default this record. When `selected_policy: waived_by_user`, the task has
  no prototype-design dependency, no prototype write, no `prototype_contract`, and no visual gate. It keeps
  `requirements_approved` and any required solution decision, production ownership, build verification, standards conformance, and
  full ui and accessibility QA. QA PASS still permits document projection and PM commit assessment;
  absence of a newly updated prototype is not itself a finding.
- A waived task may depend on authorized `standards_only` maintenance, but not on prototype-mode
  work through any dependency chain. Required-prototype work cannot substitute a standards task
  for the matching prototype task. Standard adoption refreshes only affected task authority.
- For an explicit production-only revision during implementation/acceptance, follow WORKFLOW's
  `Production-only revisions after prototype approval` and the
  [plan lifecycle](plan-lifecycle.md). The user's unambiguous current instruction can
  resolve scope and prototype choice without a duplicate confirmation. Replace affected worker/QA
  inputs; do not reopen the old designer or synchronize prototype files. Keep unaffected authority,
  actual task-level verification, and the separate production-path owner. Merely approving a
  prototype for implementation is not a waiver; neither is a generic defect report.
- Required-prototype work in existing or second-development projects without an approved design baseline first runs
  an `xy-uiux` current-product audit. Record `baseline_ready`; do not ask for another
  business confirmation.
- PM 在基线任务包中授权 `project.yaml` → `docs.standards_root/prototype` 及需要维护的准确
  `docs.standards_root/DESIGN_*.md` 叶子，并将 `xy-ui-design` 列入 `required_skills`。
  额外设计方法按[共享 Skill 选择规则](skill-selection.md)选用。
- With `prototype_policy: required`, `UI-Patch`: targeted artifact or fragment, then `prototype_verified` and
  `visual_review_ready`.
- With `prototype_policy: required`, `UI-Page` and `UI-Flow`: automatic `ia_ready`, prototype work, then explicit
  `xy-prototype-verify`, `prototype_verified`, and `visual_review_ready`.
- The `xy-uiux` task owns deterministic static prototype-verification coverage. The design Agent self-checks
  requirements coverage, standards conformance and delivery consistency in the same handoff, using existing
  static_checks/blocking_findings/result. Add no independent prototype QA, report or approval. The user gives
  final confirmation; functional QA after production implementation remains. The PM reviews
  current scope, evidence freshness and consistency, fingerprints, and the approval handoff. Before
  user handoff, independently compare the concrete behavior, developer notes and linked requirements with the frozen approved
  requirements, applicable approved solution decisions and acceptance criteria; return missing, invented, broadened, or conflicting
  behavior to `xy-uiux`. This semantic review does not invoke a browser. The PM does not repeat
  deterministic checks already proven by current evidence.
- Prototype verification MUST NOT invoke Computer Use or browser automation by default. Only an
  explicit user request to automate the prototype, or diagnosis of a concrete prototype failure
  reported by the user, permits the smallest scoped browser operation. Complexity, risk, host
  capability, or PM preference does not make browser evidence mandatory.
- Request only the smallest affected static recheck when evidence is missing, stale,
  contradictory, or fingerprints mismatch. The PM does not supplement missing browser evidence,
  repeat completed static verification, or create a new confirmation gate.
- The active concrete page and its in-page developer notes are the design evidence.
  Antigravity 使用静态验证通过的具体原稿。Codex 与 Claude Code 先显式 prepare-delivery 准备受管入口，再由 open 验证准备并返回具体页 file URI delivery_url／delivery_urls，共用画布与评审读取同一物理原稿。新项目不生成导航 index；旧 index 登记仅适用于历史分支，不能替代具体页证据。
- For `UI-Patch`, `UI-Page`, or `UI-Flow` with `prototype_policy: required`, at `visual_review_ready`, ask once for
  `visual_approved` bound to the concrete changed pages,
  changed scope, declared operation sequence, and verified page dependency fingerprints. Reopen
  only the affected confirmation after a material change or when equivalence cannot be established.
  A fingerprint mismatch blocks use of stale evidence until the smallest recheck completes; it does
  not by itself require another user confirmation. Carry non-material changes forward only under
  WORKFLOW's scoped old/new-delta review, retained user approval and verified fingerprint rule.
- The PM MUST provide a direct link to each concrete changed page.
- Antigravity 直接交付具体页的绝对路径或 file URI，附变更范围和操作步骤供用户确认，使用静态验证所得依赖指纹。Codex 与 Claude Code 提供已 prepare-delivery 且 open 验证过的具体页 file URI delivery_url；file 壳仅用无秘密绑定在 noopener 新标签页引导同页 HTTP 评审，不持有控制 token；失效提示重跑显式准备／open，不猜端口或冷启动。
- The visual-confirmation workflow MUST NOT generate, persist, attach, or present screenshots.
- Approval remains in workflow task state. Do not create companion design, mapping, or baseline
  Markdown; a Manifest; a screenshot directory; or a companion approval file.
  Preserve the approval source, scope and fingerprint in the existing plan when plan policy saves
  one. The same plan is a recovery aid, not an independent approval authority.
- Required-prototype production UI work cannot start before its approved concrete pages and
  fingerprints have `visual_approved` state. `UI-Conformance` and `waived_by_user` have no such
  gate. Dispatch depends on the approved scope, applicable solution decisions and the route’s frozen authority or prototype decision.
- For a new project, one platform owner builds and verifies the UI Foundation before
  feature-page writers run in parallel.
- Pending UI gates block production UI paths, not every unrelated workstream. Read-only
  diagnosis may proceed. A non-UI writer may proceed only after clarification, exact
  owned paths, a path and semantic conflict check, and confirmation that it has no
  semantic dependency on the pending UI decision; otherwise it waits.
- The `visual_approved` gate is a selective DAG edge: it blocks only tasks that declare a dependency on
  that gate. When the exact gate resolves, dependent tasks enter the ready queue
  immediately; unrelated branches continue.
- `contract_ready`, `plan_ready`, `BUILD_VERIFIED`, QA, and closeout projection are
  automatic evidence states. Platform security prompts remain mandatory for destructive,
  production, paid, external-mutation, or privileged operations and retain their separate authorization.


## 登记具体页的视觉批准

PM 核实同请求的原型 Writer 已交付，完成 `prototype_verified`、`visual_review_ready`，取得用户对具体页、范围和交互的明确答复后，以当前图 SHA 使用一次独立的 `approve_visuals` 补丁。以下字符串占位符需替换为本轮真实值。

```json
{
  "approve_visuals": [{
    "request_id": "checkout",
    "task_id": "web",
    "requirements_fingerprint": "<当前已确认需求的 64 位小写 SHA-256>",
    "authority_id": "settings",
    "path": "docs/standards/prototype/settings.html",
    "previous_fingerprint": "<图中本页当前 content_fingerprint>",
    "dependency_fingerprint": "<本次已经验证的页面依赖指纹>",
    "approval_ref": "user:checkout/settings-review",
    "changed_scope": ["保存设置时的确认范围"],
    "interactions": ["打开确认框，取消后返回设置页"]
  }]
}
```

```sh
bash <plugin-root>/lib/python_runtime.sh -B -X utf8 <plugin-root>/plugins/source_pack.py helper --project <project-root> lib/task_graph_cli.py update --root <project-root> --input <graph.json> --expect-sha256 <current-graph-sha256> --patch -
```

补丁可从标准输入提供。工具核对请求、任务、需求指纹、页面 ID 和物理路径，检查该页所属原型任务及其前置，静态重算页面和本地依赖的指纹。旧图版本、旧页面绑定、实物变化或证据未就绪会拒绝写入。成功时，在同一图更新受影响 Writer 的页面权威、门值和带用户来源的批准记录。其他工作仍依据各自的当前前置执行。

首次登记使用图里现有的页面指纹作为 `previous_fingerprint`。页面返工时，PM 先协调已在执行的 Writer，再通过普通状态更新将受影响任务退回待执行。修改真实页面或依赖并重新验证后，按其实际变化核对用户对本次版本的授权，用原绑定与新指纹提交同一操作。已登记的页面若在批准后发生字节变化，原型即使重新交付，关联 Writer 的就绪、正式导出和新交付登记仍会等到页面指纹与获准范围再次匹配。无变化的已受理批准使用当前图及页面指纹重交可保持幂等。


使用 Git worktree 时，PM 按同一张图登记各 Writer 的执行树、基线、交付检查点和请求的集成树。视觉批准核对负责该页的设计 Writer 已交付的提交及其实际资源。如果已登记的集成修订包含该设计，也要核对该候选中的页面。生产 Writer 的基线须包含设计检查点，领取、交接与登记交付以它自己将要执行的工作树复核。QA 再按当前集成修订检查组合后的页面。主树可继续保留旧页面；缺失的工作树、未包含所需提交的基线、漂移的 HEAD 或页面依赖会阻止使用相关批准。既有多父提交只需满足对应祖先关系，无须让各树的 HEAD 相同。
