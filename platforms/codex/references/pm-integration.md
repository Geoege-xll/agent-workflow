## Codex-only integration

- Non-trivial implementation: activate `$xy-workflow`; all Trivial work uses the shared early exit.
- Standalone read-only audits use WORKFLOW's matching branch and stop at the scoped conclusion,
  without the implementation/QA closeout loop; actual implementation acceptance keeps its QA contract.
- `$xy-project-memory`: retrieve only needed cross-session/history facts; retain post-QA closeout.
- Load `.agents/skills/` progressively, using only Codex `$xy-*` aliases, never other hosts' slash commands.
- Custom agents: canonical `xy-*` IDs in `.codex/agents/`; settings in `.codex/config.toml` come from
  `project.yaml` → `orchestration`.
- Plan revision/recovery: `$xy-workflow`'s `references/plan-lifecycle.md`.
- The main-session PM dispatches independent READY tasks in parallel through Codex-native
  custom Agents and keeps nested delegation disabled.
- Superpowers planning, execution, TDD, branch-finishing, and Subagent orchestration remain
  disabled by default.
- 测试与交付沿用已安装 `xy-build-verify/references/verification-scope.md`：派发时选最小
  充分范围，接收有效证据后不以 PM 身份重复跑一遍。全量测试或追加检查要有具体依据；
  生产交付仍必须有受影响目标构建／编译成功和可运行证据。
  保留独立 QA、强制验证和 worktree 集成要求，满足停止条件即进入既有收口。
- For non-Trivial implementation, the PM dispatches exactly one `xy-qa` reviewer. That same reviewer tries Codex native review as
  `host-native-review`, then one `installed-code-review-skill` proven installed and capable, then
  `internal-xy-qa-procedure`, moving forward only on technical unavailability. The allowed
  Superpowers option is only its installed `requesting-code-review/code-reviewer.md` prompt; Grill
  Me remains requirements-only. Findings or `FAIL` never switch review method or reviewer.
- Role TOML references boundaries and project documents; do not duplicate their content.
- Project command Hooks provide bounded intake/recovery reminders, not approvals or QA results.
  Respect native project/Hook trust and disabled settings; never bypass trust to make setup pass.
  See `.agent-workflow/platforms/shared/HOOKS.md` only for Hook configuration or diagnostics.
- SessionStart recovery includes native `fork` and `compact` sources. After a fork, verify the actual
  workspace and still-valid task authority; copied conversation context does not authorize another
  writer or repeat completed work. Do not add a second PostCompact reminder for the same recovery.

## Native review method

Use an exposed `/review` capability or `codex review` only when the unique QA reviewer can invoke
it without nested Agent delegation. Merely having a CLI binary or an installed third-party review
Skill does not prove native method availability. Resolve the selected project's effective QA
model/effort and native override layers; preserve them through supported invocation options rather
than introducing review-specific defaults or silently using another CLI profile.

For a CLI whose current help confirms the options, read-only invocation has the form
`codex --sandbox read-only --ask-for-approval never review <scope-options>`.
This invocation must remain inside existing host/project permissions and trust; do not widen them
to make review launch. `--uncommitted` covers staged, unstaged and untracked changes; `--commit`
covers that commit's introduced change; `--base` compares against the selected base branch's
merge-base semantics. Select only an option whose actual diff equals the frozen request scope.
A base argument alone is not an arbitrary pinned base/head pair, and a clean worktree does not
remove already committed request changes. Do not assume optional scope flags combine with custom
instructions: use the installed version's supported syntax and reject scope mismatches.

Bind root/nested-repository base/head, complete changed paths and dirty-diff fingerprints before and
after review. Discard output if inputs changed, a nested repository was omitted or the native range
cannot represent the request. Preserve native findings as general review evidence; the same QA
verifies findings and adds only uncovered project-acceptance checks. Record actual capability,
effective invocation, scope and result references in the existing `review_method`. Help output is
capability discovery, never proof of a completed model review. If the current tool surface cannot
invoke native review safely, record the technical reason and continue the existing method order.

## 原生工具短路径

按需使用 `xy-workflow/references/runtime-records.md` 的 doctor、原生用量和 `continuation`
操作路径；诊断的 documented/source_observed/runtime_unverified 不等于本会话执行证明。
PM 从当前原生工具取得真实 ID，经现有 update 补记 `agent_ref`，依实时 running/idle
观察查询后，通过当前已暴露的原生 follow-up／wait 能力复用同一 Agent。取消、失效、
未知或跨宿主不自动恢复；不新建 runner／Reviewer。完整 Task Pack 与 scope 仍须交接。
当前工具表没有续发能力时如实报告，不用新开用户 chat 冒充同 Agent 续用。

QA 结构化输出见 `xy-qa-review/references/inputs.md`：支持时在同次授权调用使用
`codex exec --output-schema <schema-file>`，并用 `--output-last-message <native-result.json>`
取得最终对象，再 `qa_handoff_cli.py extract --host codex --input <native-result.json>`。
`codex review` 不支持该 schema 旗标；不得改变原审查方法顺序、模型／effort 或权限来
凑结构化输出。原生用量按响应去重，样本范围和缺失值照实披露，不推算费用或节省比例。

Regenerate with `bash .agent-workflow/setup_codex.sh`; validate with
`bash .agent-workflow/setup_codex.sh --check`.
