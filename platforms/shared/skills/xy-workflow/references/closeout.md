## 验证证据与交付边界

收口沿用 `xy-build-verify/references/verification-scope.md`：PM 核对生产交付的构建／编译
成功、可运行证据以及当前交付与已验证范围
一致，不因准备提交、已有 QA PASS 或即将回复用户而再执行全套测试。真实输入变化只
失效受影响的结论；强制 CI／Hook 和 worktree 候选集成验证保持原有要求。
Trivial 继续使用主会话局部验证，不能为了应用本段补建独立 QA 或其他收口记录。
最终反馈只说明实际验证范围、结果及相关限制，准确区分局部通过和全量通过。
完整命令、日志及复用来源留在现有证据引用，不创建新的报告或审批环节。
只读审计交付结论后不进入本实现收口链。QA 通过后的普通说明文档或低风险文案收尾，
只检查实际变化的链接、语义、资源或运行输入；需要更新交付绑定时沿用现有机制，不能
为收尾从头再审未变功能。工作流指令、权限、安全、API 或业务合同变化不因是 Markdown
或文案而豁免；新风险、失效证据和用户／项目明确要求的复审仍按受影响范围执行。

- Every implementation task pack carries its approved goal, non-goals, constraints, acceptance
  evidence, and applicable UI authority. Required-prototype design tasks carry concrete pages;
  `UI-Conformance` tasks carry `design_authority_refs`; waived tasks carry the scope-bound
  `prototype_decision` and must not treat an old prototype as current authority. Required-prototype
  tasks carry the same decision plus concrete page authority. The task pack also records:

  ```yaml
  controlled_document_projection:
    project_docs_update: required | not_required
    change_type: added | updated | replaced | reimplemented | removed | restored | split | merged | renamed | cancelled | none
    affected_features: []
    project_index_update: required | not_required
    reason: <why current verified project or feature truth changes or remains unchanged>
  ```

  For Full work this decision belongs to PM review of the `plan_state: draft` proposal. It describes
  a post-QA projection and is never early write authority. Canonical documents remain the last
  QA-verified project truth while implementation and QA are in progress.

  Use `required` for an added, changed, replaced, restored, renamed, split, merged, cancelled, or
  removed feature truth. Also use `reimplemented` for a major behavior-preserving rewrite that future
  work must recognize; routine refactors, dependency upgrades, internal performance work, and pure
  visual styling use `not_required` with `change_type: none` only when recorded current facts remain
  unchanged. Update an existing runtime/dependency baseline, rationale or scope in place when it
  changes; do not add a document or chronology merely for the task. A durable UI behavior change updates the
  affected feature document. Approved concrete HTML remains visual and interaction authority for
  current required-prototype work, or when an unchanged concrete page is explicitly frozen as valid
  `UI-Conformance` authority. If a production-only revision makes an existing document's
  prototype link misleading, project the verified production truth and scoped authority boundary;
  do not synchronize the historical prototype during closeout.

  After integrated QA PASS, the PM applies the smallest current-truth projection. `PROJECT.md` keeps
  only the current project directory and active feature links; each active feature document keeps
  current requirements, acceptance and functional/architectural rationale. Git owns full history;
  update obsolete text in place, not as a chronology. Cross-feature rationale may have one shared
  detail in the same features directory. Do not create an independent ADR category.

  A verified removal is one closeout operation: delete the active feature row from `PROJECT.md`,
  rename `<feature>.md` to `<feature>.removed.md`, mark it removed with reason/date/replacement and
  historical-only requirements, then repair current links. Before QA PASS there is no
  `removal_pending` projection. If QA fails, canonical documents remain unchanged.
- After QA PASS and the validated controlled-document projection, perform the PM commit assessment.
  Keep the result internal:

  ```yaml
  commit_decision:
    needed: true | false
    reason: <request-level evidence>
    repositories:
      - path: . | <nested-repository-path>
        action: committed | skipped | blocked
        scoped_paths: []
        staged_diff_fingerprint: null | <64-lowercase-hex-sha256>
        commit_revision: null | <full-commit-id>
        reason: <repository-specific evidence>
  ```

  Commit only request-owned, QA-verified changes plus the validated PM projection. Use exact
  pathspecs and inspect the complete staged diff; the PM must not stage unrelated or unverified changes
  and must not use `git add -A` or `git add .`. Preserve pre-existing user edits. Unsafe overlap is
  `blocked`, not permission to stage a whole file. Assess nested repositories independently and
  deepest first. Verify the committed patch against the inspected staged snapshot. This automatic
  action does not create a third business-confirmation stage or authorize push, merge, tag, release,
  or another remote mutation.
  The selected [worktree delivery](worktree-delivery.md) branch separately grants bounded PM-local
  checkpoint/integration authority before final QA and confirm/auto delivery after all work completes.
  It never grants workers commit/merge authority or implies a remote operation.
