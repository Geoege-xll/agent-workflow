## Inputs

- approved task contract, request dependency closure, and exact owned paths;
- implementation diff and real source/components/tokens;
- implementer evidence summaries and resolvable complete-log references;
- the current fingerprinted STANDARDS index and the task pack's selected non-`skip`
  `controlled_document_access` leaves. Non-UI implementation contributes engineering leaves,
  production UI contributes engineering and design leaves, and prototype design contributes design
  leaves. Missing, `skip`, stale, or incomplete authority is FAIL; QA must not preload every
  `project.yaml` -> `docs.*` document to repair a broken task pack;
- for `UI-Conformance`, the frozen `ui_change` record and every resolvable
  `design_authority_refs` entry; for a design-change route with `prototype_policy: required`, the
  scope-bound `prototype_decision`, designer's complete verification handoff, every approved
  concrete page path and verified fingerprint, and the exact in-page contract
  (`Page design and interaction contract`); for `waived_by_user`, the same scope-bound
  `prototype_decision`, frozen approved requirements, and any applicable non-prototype authority;
- when the PM actually ran on-demand start retrieval and the recalled claims affect this request,
  the resulting `memory_context` returned by `xy-project-memory`:

  ```yaml
  memory_context:
    provider: agentmemory | docs-fallback
    fallback_reason: null | provider-unavailable | project-isolation-unavailable
    project_id: <memory.project_id>
    filter_enforced: true | false
    capability_evidence: []
    query_scope: []
    memory_ids: []
    provenance_refs: []
    document_refs: []
    stale_or_conflicting: []
  ```

- the task pack's specialist policy:

  ```yaml
  skill_policy:
    required_skills: []
    audit_surfaces: []
  ```

- the single reviewer's selected-method evidence:

  ```yaml
  review_method:
    selected: host-native-review | installed-code-review-skill | internal-xy-qa-procedure
    external_skill: null | <host-exposed installed code-review Skill identifier>
    capability_evidence: [<actual-capability-and-execution-evidence-reference>]
    fallback_reason: null | missing | launch-failed | timeout | malformed-output | unsafe-mutation | recursive-delegation
    scope_ref:
      repositories:
        - path: . | <nested-repository-path>
          base_revision: <fixed-base>
          head_revision: <fixed-head>
          diff_fingerprint: <64-lowercase-hex-sha256>
          changed_paths: []
  ```

- Every `review_method` field shown above is required. `selected` accepts only the three listed
  methods. `external_skill` is a non-empty host-exposed Skill identifier only for
  `installed-code-review-skill`; it is `null` for native/internal methods. `capability_evidence`
  is a non-empty list of unique non-empty evidence references for every selected method.
  Native selection requires `fallback_reason: null`; either later method requires one listed
  technical reason and evidence explaining the preceding methods' unavailability. An unpinned
  response is `malformed-output`, not permission to shrink the request scope. Method findings/FAIL
  never qualify as a fallback reason. The handoff validator checks these shapes and combinations;
  PM/QA still inspect the referenced execution, permissions, model/effort and actual scope. Valid
  strings do not prove that a command ran or that a capability was available.

- an internal standards coverage record for PM validation. QA derives applicable rules independently
  from the index and actual changed paths; `task_pack_rule_ids` records what PM dispatched:

  ```yaml
  standards_policy_coverage:
    index_path: <standards_contract.index_path>
    root: <standards_contract.root>
    index_fingerprint: <standards_contract.index_fingerprint>
    task_pack_rule_ids: []
    required_engineering_rule_ids: []
    required_design_rule_ids: []
    path_checks:
      - path: <fixed changed path>
        applicable_rule_ids: []
        reason: <why these rules apply or why none apply>
    rule_checks:
      - rule_id: <stable-rule-id>
        source_path: <standards leaf path>
        source_fingerprint: <64-lowercase-hex-sha256>
        source_anchor: <heading-or-rule-anchor>
        domain: engineering | design
        severity: hard | advisory
        disposition: pass | fail | not_applicable
        affected_paths: []
        evidence_refs: []
        exception_ref: ""
  ```

Do not substitute the root prototype index, task summary, recalled memory, claimed result, or
potential Skill match for applicable design authority, current source, and real logs.

## 原生结构化交接

当前宿主已提供且已获授权的 QA 调用支持 schema 时，先用
`qa_handoff_cli.py schema` 获取本包当前 QA handoff 的 JSON Schema，将其交给同一次
原生 QA 调用；不为将已有自然语言改成 JSON 额外开模型调用，不启动另一位 Reviewer。
在安装态项目根使用以下只读入口：

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/qa_handoff_cli.py schema
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/qa_handoff_cli.py extract \
  --host codex --input "${native_qa_result:?set actual terminal native-result.json}"
```

`extract` 读取 Codex 保存的最终 QA 对象，或从 Claude／AGY 终端成功 envelope 提取
结构化对象后，直接复用原 `validate` 的范围、
review_method、规则覆盖与证据语义校验；成功只证明这些机械合同满足，PM／QA 仍须
核对真实审查执行、只读边界、固定 scope、model／effort 与证据，才能接受 QA PASS。
失败、取消、半截流、非对象或无结构化结果不能伪装成有效 handoff。

- Codex 使用当前版本支持的 `exec --output-schema <schema-file>`；`codex review`
  没有该旗标，不给 review 拼接它，也不为结构化输出绕过原 review_method 顺序。
  用 `--output-last-message <native-result.json>` 保存最终 QA JSON 后再 extract，
  不将 exec 事件流当作最终消息；还须核对该原生调用确实成功完成。
- Claude 使用已支持且获授权的 `-p --json-schema <schema-json>`，成功终端 result
  envelope 仍须符合 type／subtype／is_error 与 structured_output 合同。
- AGY 使用已支持且获授权的 `--json-schema <schema-json>`，终端结果必须有
  `conversation_id`、`status: SUCCESS` 和 `structured_output`；`response`、`usage`
  可缺省，存在时校验结构和一致性，用量可见性不成为 QA 新门禁。

普通 JSON handoff 仍使用原 `validate --input <handoff.json>`。Task Pack 继续通过
`task_graph_cli.py task` 导出，不套 QA schema。原生命令须核对当前 help 和实际会话能力，
不能由静态文档或成功提取推断模型运行成功。AGY 的 diff／Artifact 人工批准是人工审阅，
不能冒充 `host-native-review` 或独立 AI QA；原审批、读写边界与 method 顺序保持不变。
