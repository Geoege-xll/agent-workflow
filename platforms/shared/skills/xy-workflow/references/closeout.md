## Verification evidence and delivery boundaries

Closeout follows `xy-build-verify/references/verification-scope.md`: PM checks successful production
build/compile and runnable evidence, and confirms current delivery matches the verified scope. Do not run
builds, tests or acceptance without information gain merely because a commit is pending, QA PASS exists
or a user reply is imminent. Judge added coverage, invalidated evidence and specific risks under that
policy; ordinary explanatory closeout alone is no reason to rerun. Actual input changes invalidate only
affected conclusions. Mandatory CI/Hooks and worktree-candidate integration checks retain their requirements.
After minimum verification, Light assesses independent audit, documentation and memory by actual risk;
do not create a Full graph, plan or empty closeout record to apply this section. Full still requires its
single valid QA PASS. Both levels default to native implementers; a PM exception needs explicit authority.
Final feedback states only actual verification scope, results and relevant limits, accurately distinguishing
scoped success from full-suite success. Complete commands, logs and reuse provenance remain in existing
evidence references, without a new report/approval step. Read-only audits do not enter this implementation
closeout chain after delivering conclusions. Ordinary explanatory documentation/low-risk copy closeout after
QA checks only changed links, semantics, resources or runtime inputs. Update delivery bindings through
existing mechanisms when needed; do not restart review of unchanged functionality for closeout. Markdown/
copy status does not exempt workflow instructions, permissions, security, APIs or business-contract changes.
New risks, invalidated evidence and explicit user/project rereview requirements still apply to affected scope.

- Every implementation task pack carries its approved goal, non-goals, constraints, acceptance
  evidence, applicable solution decisions and UI authority. Required-prototype design tasks carry concrete pages;
  `UI-Conformance` tasks carry `design_authority_refs`; waived tasks carry the scope-bound
  `prototype_decision` and must not treat an old prototype as current authority. Required-prototype
  tasks carry the same decision plus concrete page authority. Full packs record the projection decision
  in advance; Light assesses actual needs at handoff without mandatory prefilled Full projection records:

  ```yaml
  controlled_document_projection:
    project_docs_update: required | not_required
    change_type: added | updated | replaced | reimplemented | removed | restored | split | merged | renamed | cancelled | none
    affected_features: []
    project_index_update: required | not_required
    reason: <why current verified project or feature truth changes or remains unchanged>
  ```

  For Full work this decision belongs to PM review of the `plan_state: draft` proposal. It describes
  a post-QA projection. 实现与 QA 期间，原主题的已验收行为及其证据保留上次基线。

  Use `required` for an added, changed, replaced, restored, renamed, split, merged, cancelled, or
  removed feature truth. Also use `reimplemented` for a major behavior-preserving rewrite that future
  work must recognize; routine refactors, dependency upgrades, internal performance work, and pure
  visual styling use `not_required` with `change_type: none` only when recorded current facts remain
  unchanged. Update an existing runtime/dependency baseline, rationale or scope in place when it
  changes; do not add a document or chronology merely for the task. A durable UI behavior change updates the
  affected topic plan. Approved concrete HTML remains visual and interaction authority for
  current required-prototype work, or when an unchanged concrete page is explicitly frozen as valid
  `UI-Conformance` authority. If a production-only revision makes an existing document's
  prototype link misleading, project the verified production truth and scoped authority boundary;
  do not synchronize the historical prototype during closeout.

  Full 经当前集成 QA PASS 后投影，Light 在必要验证与选定的独立审查通过后按需更新。开发者在原交接给出实际做法、源码与测试定位和未验证边界，本轮 QA 按审查范围核实。PM 将已验证的版本、已交付行为和维护入口用相对链接写回原主题，未验证项保留原状态；项目级架构与规范只链接其权威章节。PROJECT 的主题目录每个稳定主题只列一次，已验收声明指向可核实的真实基线。迭代、暂停或取消仍保留上次已验收行为。完整移除经实际验收后在原主题标记 `removed`，保留原因、时间和替代关系，撤下当前入口并修复引用。验收失败保留原基线。
  Requirements/plan Markdown-to-HTML generation remains retired; preserve existing HTML as
  historical material without generating, updating or checking its freshness. Follow
  [the retained HTML boundary](../../xy-plan/references/requirements-markdown.md).
### QA 后登记已验收事实

Full 的原 QA 任务包、handoff、`request_receipt` 和受审文档原字节保存在原证据位置。PM 在原主题中更新已核实的验收版本、进展首段、已交付行为和验收证据。保留以往已交付的正文和证据摘要，验收证据行引用本次已接收 handoff 的 SHA-256。首次交付可替换无基线占位；首次添加证据节时，批准依据引用原图已有的方案来源，或用 `requirements_approved@<requirements_fingerprint>` 定位本次已批准的需求。主题可省略恢复节。

通过既有 `task_graph_cli.py update --input <图> --patch <补丁> --expect-sha256 <图原摘要> --root <项目根>`，以单独操作登记。下例的 SHA 和路径应替换为实际值。

```json
{"tasks":{"qa":{"record_qa_projection":{"adapter":"project.yaml","documents":[{"path":"docs/plans/example.md","reviewed":{"path":"/absolute/evidence/reviewed-example.md","sha256":"<原字节摘要>"},"projected_sha256":"<当前文档摘要>"}]}}}}
```

单树从原冻结范围复算受审摘要。主题同时属于受控读取或设计权威时，原已核对的需求、实现与审查合同共用同一份经过验证的前像。Foundation 最终包保留全部 Writer 范围；有本地 Git 提交时，包中的 `qa_document_base` 可定位由 PM 独占的已有文档。对于受审范围之外的 PM 专有文档，工具用同一仓库已冻结的 Git 提交核对原对象。已有未跟踪的 PM 文档可以在原有冻结步骤（Foundation 阶段通过后、最终交接前）使用 `"freeze_qa_scope":{"scope_ref":{"repositories":[…]},"projection_paths":["docs/plans/example.md"]}` 预存字节摘要，保留原档供验收后回放。原档或受审提交不可恢复时应先取得可核实的原始依据。登记、后续就绪与交付核对都会检查原回执及其余受审业务。需求、批准、接口或规范发生变化时，回到受影响的验收范围。

隔离请求保留原 `worktree_integrations` 及其构建、QA 提交。PM 将验收事实提交到该集成工作树，在上例操作中增加 `head_revision` 指向最终文档提交。工具核对两个提交之间的全部差异。交付的 `projection_paths` 明列 PM 路径，合并授权绑定最终提交和完整差异。PROJECT 与相邻的 `ARCHITECTURE.md` 可在受审候选中包含实际目录或模块职责更新。若在 QA 后补入口，可用一条普通 Markdown 列表链接指向本次登记的主题，标签取计划文件名去掉扩展名，路径相对于索引页。其余结构描述应在受审候选中核对。

- Full performs PM commit assessment after QA PASS, and Light after acceptance of minimum verification and
  actually mandatory audit, including verified document projection.
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

  Commit only request-owned changes verified/accepted for the current level, plus verified PM projection;
  Full requires valid QA PASS. Use exact
  pathspecs and inspect the complete staged diff; the PM must not stage unrelated or unverified changes
  and must not use `git add -A` or `git add .`. Preserve pre-existing user edits. Unsafe overlap is
  `blocked`, not permission to stage a whole file. Assess nested repositories independently and
  deepest first. Verify the committed patch against the inspected staged snapshot. This automatic
  action does not create a business-confirmation stage or authorize push, merge, tag, release,
  or another remote mutation.
  The selected [worktree delivery](worktree-delivery.md) branch separately grants bounded PM-local
  checkpoint/integration authority before final QA and confirm/auto delivery after all work completes.
  It never grants workers commit/merge authority or implies a remote operation.
- Before the final report, close out actual task-temporary resources only under the original contract.
  First stop relevant writers and verify task ownership, active use and current plan/handoff/recovery
  references. Continue reusing shared configuration, project environments, databases, system caches and user
  material for their intended roles. Transfer authorized retained valid data/results to the corresponding
  project/service baseline. First place mandatory complete logs and approval/recovery evidence at a readable
  durable location and repair current references; a summary cannot replace the sole complete evidence.
  If transfer is impossible, retain only necessary files/ancestors, not an entire candidate for one reference.
  For scratch, follow the [record-tool preview and cleanup contract](runtime-records.md#allocate-and-clean-up-the-task-scratch-workspace):
  preview this `request-id` read-only with the same necessary `--keep` values, then execute against its reviewed
  snapshot fingerprint. Recheck an invalidated snapshot; `--all` is not default closeout. Likewise reclaim only
  task-owned isolated databases, containers and rolling snapshots with proven ownership, no active use and no
  necessary references. If cleanup occurs, briefly record results/remaining limits in the original task.
  `removed_logical_bytes` counts removed files' logical bytes only; do not claim physical disk space released.

## Instance and evidence closure

Follow WORKFLOW's `agent-instance-lifecycle`: after PM accepts results, necessary verification/QA ends and
evidence is safely preserved, use actually exposed native close capabilities. Without a reliable tool,
record agent_retired:true only in the existing task to prevent misdispatch, and state closure is unconfirmed.
Do not claim physical erasure/destruction or released unconfirmed capacity; retirement does not unlock active
tasks. Keep necessary short-rework/original-Reviewer delta-review windows for the current delivery unit.
Under pressure, prefer accepted, sufficiently handed-off instances; do not simply LRU-evict executing,
evidence-unreceived or necessary-review instances. Protect temporary worktrees/sole logs before AGY kill.
Preserve existing recovery boundaries for cancellation/exceptions. Native closure/scratch cleanup must not
delete still-referenced sole evidence.
