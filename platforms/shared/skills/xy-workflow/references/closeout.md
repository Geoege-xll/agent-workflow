## 验证证据与交付边界

收口沿用 `xy-build-verify/references/verification-scope.md`：PM 核对生产交付的构建／编译
成功、可运行证据以及当前交付与已验证范围
一致，不因准备提交、已有 QA PASS 或即将回复用户而再执行无信息增量的构建、测试或验收。
新增覆盖、失效证据或具体风险的判断沿上述策略，普通说明收尾本身不构成重跑理由。
真实输入变化只失效受影响的结论；强制 CI／Hook 和 worktree 候选集成验证保持原有要求。
Light 完成最小验证后按实际风险评估独立审计、文档与记忆，不为应用本段补建 Full 图、
计划或空收口记录；Full 仍需有效唯一 QA PASS。两等级都默认原生实施者，PM例外须有明确授权。
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
  tasks carry the same decision plus concrete page authority. Full包预先记录投影决定，Light在
  交接时按实际需要评估，不强制预填下列Full投影记录：

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

  Full 在 integrated QA PASS 后投影；Light 依据实际接收、必要独立审计和文档评估更新，
  不把未审计结果写成QA-verified。The PM applies the smallest current-truth projection. `PROJECT.md` keeps
  only the current project directory and active feature links; each active feature document keeps
  current requirements, acceptance and functional/architectural rationale. Git owns full history;
  update obsolete text in place, not as a chronology. Cross-feature rationale may have one shared
  detail in the same features directory. Do not create an independent ADR category.

  A verified removal is one closeout operation: delete the active feature row from `PROJECT.md`,
  rename `<feature>.md` to `<feature>.removed.md`, mark it removed with reason/date/replacement and
  historical-only requirements, then repair current links. Before QA PASS there is no
  `removal_pending` projection. If QA fails, canonical documents remain unchanged.
- Full 在 QA PASS 后、Light 在最小验证与实际必需审计接收后，连同已验证文档投影执行 PM 提交评估。
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

  只提交本请求拥有且按当前等级验证／验收的变更，加已验证的PM投影；Full必须有效QA PASS。 Use exact
  pathspecs and inspect the complete staged diff; the PM must not stage unrelated or unverified changes
  and must not use `git add -A` or `git add .`. Preserve pre-existing user edits. Unsafe overlap is
  `blocked`, not permission to stage a whole file. Assess nested repositories independently and
  deepest first. Verify the committed patch against the inspected staged snapshot. This automatic
  action does not create a third business-confirmation stage or authorize push, merge, tag, release,
  or another remote mutation.
  The selected [worktree delivery](worktree-delivery.md) branch separately grants bounded PM-local
  checkpoint/integration authority before final QA and confirm/auto delivery after all work completes.
  It never grants workers commit/merge authority or implies a remote operation.
- 最终报告前，仅在确有本任务临时资源时按原合同收口。先停止相关写者，核对任务归属、
  活跃使用及当前计划／交接／恢复引用；共享配置、项目环境、数据库、系统缓存与用户材料
  继续按其职责复用。将按授权需保留的有效数据与成果移交相应项目／服务基线，必需完整
  日志及批准／恢复证据先取得可读持久落点并修复当前引用，不能用摘要代替唯一完整证据。
  无法移交时仅保留必要文件及祖先目录，不因单个引用保留全部候选。
  scratch 按[记录工具的预览与清理合同](runtime-records.md#allocate-and-clean-up-the-task-scratch-workspace)
  先以本 `request-id` 只读预览，携带相同的必要 `--keep`，核对后用预览快照指纹执行；
  快照失效先重新核实，`--all` 不作默认收口。隔离库、容器、滚动快照同样只回收可证明
  归属且无活跃使用与必要引用的本任务资源。确有清理时在原任务中简述结果与剩余限制；
  `removed_logical_bytes` 仅为已移除文件的逻辑字节统计，不声称实际物理磁盘释放量。

## 实例与证据收口

按 WORKFLOW 的 `agent-instance-lifecycle`：PM接收成果、必要验证／QA结束且证据已安全
保存后，用实际暴露的原生结束能力回收。没有可靠工具时只在现有任务记agent_retired:true，
阻止误派并说明结束未确认；不能声称物理清空、销毁或释放未确认容量，退役不解锁仍活动任务。
保留当前交付单元必要短返工及原Reviewer差量复查窗口；压力时优先已验收且交接充分者，
不能简单LRU淘汰仍执行、证据未交付或必要复查实例。AGY kill前保护临时worktree与唯一日志。
取消／异常保留已有恢复边界；不让原生结束或scratch清理删除仍被引用的唯一证据。
