## Antigravity native PM delta

This entire managed section applies only in Antigravity; ignore other hosts' integration sections.

Standalone read-only audits follow WORKFLOW's matching branch and stop at the scoped conclusion,
without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.

Use `/xy-workflow` for non-Trivial implementation; roles are `.agents/agents/xy-*.md`, Skills are
`.agents/skills/xy-*/SKILL.md`. Only the PM may use `invoke_subagent`; role Agents never delegate and
`max_depth` is `1`. Dispatch READY tasks: `inherit` stays `inherit`, `worktree` becomes `branch`
only when the actual runtime proves a distinct registered worktree root and the required base;
`share` is forbidden. A branch name alone is not filesystem isolation. For multi-feature selection,
integration and confirm/auto local main delivery, read `/xy-workflow`'s `references/worktree-delivery.md`.
If isolated tool binding is unavailable, report it and retain safe ownership-based scheduling;
never emulate isolation by concurrently switching branches in one directory or overwriting host settings.

Clear one-file non-UI corrections with no shared contract use WORKFLOW's `General Trivial early exit`:
applicable engineering rules, direct local verification, scoped commit assessment, then stop without
DAG, repeated approval, independent QA or automatic document/memory closeout. Reclassify material risk.

Classify Trivial UI copy before UI routes: explicit local wording only, unchanged business/behavior,
no sensitive or unresolved shared impact; follow `.agent-workflow/product/WORKFLOW.md` -> `Trivial UI copy`.
Edit directly with applicable standards and local checks. No repeated approval, Grill/plan/DAG,
prototype choice, independent QA or document/memory churn; assess scoped commit after verification,
without fake QA PASS. Stricter project rules and requested review still apply. The following
execution and post-QA stages govern non-Trivial work, not this early exit.

Full: classify → facts → Grill Me → `xy-plan` draft → projection decision →
`requirements_approved`; Grill Me remains requirements-only. For design-change UI, include the PM
recommendation and prototype choice in that confirmation; freeze truth until QA PASS.
Full work records the Grill Me coverage check and `plan_state: draft`; the pre-approval projection
decision remains a draft, while post-QA controlled-document projection happens only after QA PASS.
PM saves the approved Full plan in `docs.plans` before first design/implementation dispatch.
Trivial does not save by default; Light saves only for actual pause/recovery/handoff or user request.
For revisions/recovery follow `/xy-workflow`'s `references/plan-lifecycle.md`: one requirement, one
current plan; replace affected complete worker/QA inputs and reuse unaffected verified work.
Feature details include current architectural rationale, with no separate ADR category.
`UI-Conformance` uses `prototype_policy: not_applicable`, resolved/fingerprinted
`design_authority_refs`, `surface_kind: production_ui`, `qa_scope: request`, no `xy-uiux`, and no
visual gate. Changed routes require a scope-bound `prototype_decision` from
`requirements_confirmation_user_choice`: `required` adds `xy-uiux` and a dependency fingerprint
page Gate `visual_approved`; `waived_by_user` adds no prototype-design dependency, prototype write, or visual
gate. The PM must not default either choice; full UI/accessibility QA remains. Platform security
prompts remain separate.

For initial/revised standards or full visual replacement, read `/xy-workflow`'s
`references/design-standards.md`. PM assesses/adopts scope separately from feature documentation;
UI Agent writes authorized leaves. `design_mode: standards_only` may precede waived production,
without prototype files, verification or visual gates. PM refreshes affected authority before use.

Prototype verification MUST NOT invoke Computer Use or `/browser` by default. Use `/browser` only
when the user explicitly requests prototype automation or reports a concrete failure needing the
smallest diagnostic operation. Production QA may still use risk-based browser testing. No rendered
frame may be persisted or used as approval evidence.

Current controlled documents and explicit user approvals win over recalled memory. Without strict
isolation or provenance, call neither recall nor save. For non-Trivial implementation, at BUILD_VERIFIED dispatch exactly one
integrated, read-only `xy-qa`. Waived work skips old-prototype comparison.

The reviewer tries `host-native-review`, then one `installed-code-review-skill` proven installed and
capable, then `internal-xy-qa-procedure`, moving forward only on technical unavailability. The sole
Superpowers option is `requesting-code-review/code-reviewer.md`. Findings or `FAIL` never switch
review method or reviewer.

Final QA outcome: PASS | FAIL. Require `qa_handoff_cli.py validate`. Completion: QA PASS → projection
→ PM commit assessment → memory closeout via `/xy-project-memory` → final user report. Setup owns
marked artifacts and one signed, named assist Hook in `.agents/hooks.json`; other host settings,
MCP, plugins, permissions, Agent mode and Artifact review policy stay unchanged. The Hook reminds
at native SessionStart, not on every model invocation, and creates no temporary deduplication markers.
It does not infer user turns or context recovery from invocation counters or user message content.
The actual client must support and execute SessionStart; generated configuration alone is not proof.
See `.agent-workflow/platforms/shared/HOOKS.md`
only for Hook setup or diagnostics.

## 原生工具短路径

按需使用 `xy-workflow/references/runtime-records.md` 的 doctor、用量与 continuation 路径。
doctor 默认不启动进程，`--probe` 仅 `--version`，不执行 `/skills`。其
documented/source_observed/runtime_unverified 区分文档、明确项目来源与运行未验证；
`.agents/skills/grill-me/SKILL.md` 的声明／SHA 和 same_name_risk=possible 不能证明
当前 `/grill-me` 的 actual_source（仍 unknown）。在目标宿主核对实际路径与指令后使用；
原生 `/grill-me` 不自动替换本包 Full requirements coverage check，不自动改别名。

PM 用实际 `invoke_subagent` 结果的 ID 经现 update 补记 `agent_ref`，以当前观察查询
`continuation --host antigravity --observed-state <当前观察>`；只有当前已暴露且授权的
原生续发／等待工具才能执行建议。取消、未知、失效或跨宿主均阻塞自动续用，仍须交接
完整 Task Pack／scope；没有能力时不自建 runner、daemon、MCP 或替代 Reviewer。
AGY 原生累计用量保留 unknown 初始基线、last_cumulative 与 observed_delta，不逐条累加。

QA 结构化输出见 `xy-qa-review/references/inputs.md`：支持时同次授权调用使用
`--json-schema <schema-json>`，再 `qa_handoff_cli.py extract --host antigravity
--input <native-result.json>`。可选 usage 缺失不成为 QA 门禁。diff／Artifact 人工审阅
不冒充原生 AI 审查或独立 AI QA；native、boost、teamwork 等模式不自动启用，
也不调整现有 Artifact 策略、权限或 model／effort 来促成调用。
