## Inputs

Receive only the current self-contained schema 2 QA pack: `schema_version: 2`, this task's `task`, necessary
applicable standards, approval/UI authority, current review scope and evidence. The task includes
workflow_level, module, role, agent_alias, instance_policy:fresh, context_policy:handoff_only and actual
agent_ref. A new Reviewer must not inherit/copy full PM or sibling history. Full retains request-closure
audit. Light requires no Full graph, but selected independent QA still needs current identity/evidence binding.

### 新项目 Foundation 检查点

A new-project Foundation request uses the same QA node and original native Reviewer twice:
first its graph-derived `qa_checkpoint.kind: foundation` closure, then `kind: request` for the full writer
closure. The pack carries `qa_checkpoint.writer_ids` and `qa_checkpoint_fingerprint`; never self-select a
subset or treat a Foundation PASS as final request acceptance. `qa_scope` remains `request`. PM accepts
the first validated current-byte PASS through exclusive `accept_foundation`; QA returns to `DECLARED`
with its identity intact. PM checks actual native completion separately, then resumes this same Reviewer
for final request review through `accept_request`. Old/mixed checkpoint packs, missing UI/standards
scope and changed Foundation evidence fail acceptance. Existing three-round recovery limits apply to
this same request; no second Reviewer or business approval is added.

### 方案正文与批准来源

普通 Full 和 Foundation 的 QA 包在有关 Writer 声明方案时携带 `reviewed_solution_decisions`。每项列出 `request_id`、决定 `id`、原始 `content`、`writer_ids` 和 `approval_gate`。同请求中采用同一正文的多个 Writer 共用一项。阶段包只含该阶段的采用者，最终包覆盖完整请求闭包。

Reviewer 核对原图 `approved_gates` 中的精确门值及实际行为。有 `source_ref` 时，按该定位核对 PM 记录的用户答复。旧图可能只记有与请求、ID 和正文绑定的批准门；如验收需要用户原话而证据缺失，向 PM 指出缺口。用户消息的来源只能由有依据的 PM 记录。

独立执行 `task_graph_cli.py verify-solution-scope --input <QA包> --source <Full图或Light Writer单包>` 可以复核正文、准许门及采用者，返回两个原文件摘要。Light 选定独立审查时，PM 用 `task_graph_cli.py task --input <Light QA包> --source <同请求Light Writer包>` 导出相同条目和关联的 `approved_gates`、`solution_approval_sources`；有记录的 `source_ref` 须与 gate 的映射相符。旧包仍可读取，缺少本次必审内容时按当前来源补交。

## 分批取证

每批围绕一个或一组关联验收项。在冻结的变更路径中按[源码取证示例](implementation-acceptance.md#按符号和行段核对源码)找出符号、调用方和必要行段，连同实际命令、退出码及日志定位判断该项。按[受控文档读取约定](../../xy-workflow/references/runtime-records.md#完整读取必需长文)核对适用规则的原文、例外与上下文。登记这批路径与规则的对应关系；发现包外适用规则时向 PM 指出漏派依据。

在原任务交接中向 PM 简述已核验项及证据定位（版本／规则／路径行段／命令和日志）、未覆盖项及下一处定位，PM 可就地保留进度。上下文趋满时停止打开新来源，先交接当前可核验进度。摘要本身不释放上下文；取得足够可用空间后才由同一 Reviewer 续查，复用仍与当前范围和指纹相符的结论，恢复已丢失但后续必需的原文。硬性证据缺口按既有 FAIL 合同处理；批次交接和宿主终止均不能生成最终回执。

## 当前包与范围

- approved task contract, request dependency closure, and exact owned paths;
- 对声明实质方案的受影响任务，核对当前请求、决定 ID、正文、实际批准依据和实现行为。免原型或视觉批准只影响页面权威；方案未定或已变更时交回 PM。
- implementation diff and real source/components/tokens;
- implementer evidence summaries and resolvable complete-log references;
- applicable built-in sources bound to current fingerprints, the project-specific standards index when
  present, and non-skip controlled_document_access sources/leaves selected by the task pack. With no specific
  leaves and a physically absent index, use configured paths + null fingerprint; do not omit built-in rules
  or generate an empty index for QA. Non-UI implementation contributes engineering leaves,
  production UI contributes engineering and design leaves, and prototype design contributes design
  leaves. Missing, `skip`, stale, or incomplete authority is FAIL; QA must not preload every
  `project.yaml` -> `docs.*` document to repair a broken task pack;
- for `UI-Conformance`, the frozen `ui_change` record and every resolvable
  `design_authority_refs` entry; for a design-change route with `prototype_policy: required`, the
  scope-bound `prototype_decision`, designer's complete verification handoff, every approved
  concrete page path and verified fingerprint, and the exact in-page contract
  (`Page design and interaction contract`); for `waived_by_user`, the same scope-bound
  `prototype_decision`, frozen approved requirements, and any applicable non-prototype authority;

## 按需核对记忆依据

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

## Skill 与审计面

- the task's specialist policy fields, directly inside `task`:

  ```json
  {
    "required_skills": [],
    "audit_surfaces": []
  }
  ```

  结果的 `skill_evidence.skills_used` 仅记录实际应用过的 Skill。PASS 必须逐项匹配
  当前包明确要求的标识，且 `unavailable_required_skills` 为空。QA 任务声明的
  `standards-conformance`、`ui`、`accessibility` 属于强制审计面，PASS 的
  `uncovered_audit_surfaces` 必须排除这些面。生产 UI Writer 投影要求 QA 包同时声明
  `ui` 和 `accessibility`。其它面如实报告补充覆盖缺口，缺少可选 Skill 时继续基础核验。

## 审查方法证据

### 核对原生审查目标

先读取当前 QA 包的冻结范围和 PM 留下的实际差异，核对同一文件中哪些改动属于本次请求。再按宿主说明确认可调用的入口、权限和它实际会读到的内容。

对已完成 `freeze_qa_scope` 的普通 Full，PM 或 Reviewer 可以直接比对候选与包内 `task.qa_scope_ref`、`task.qa_scope_fingerprint`，在原交接中复用结果。下例的 `plugin` 是当前插件根，`project` 是项目根，`qa_task_pack` 是原 QA 包，`candidate` 是项目外的候选 JSON 文件。提交区间用完整提交 ID 替换示例占位符。

```json
{"kind":"commit-range","repository":".","base_revision":"<base>","head_revision":"<head>"}
```

```sh
bash "$plugin/lib/python_runtime.sh" -B -X utf8 "$plugin/plugins/source_pack.py" \
  helper --project "$project" lib/delivery/qa_handoff_cli.py compare-target \
  --task-pack "$qa_task_pack" --input "$candidate"
```

若入口只读当前仓库的全部未提交变更，候选为 `{"kind":"uncommitted","repository":"."}`。比对器检查一个 Git 目标能否覆盖整份冻结范围。对于使用其它范围合同的检查点，直接核对原合同、实际差异与宿主输入。

| 诊断结果 | Reviewer 的下一步 |
| --- | --- |
| `match` | 候选的修订、路径和补丁字节吻合。核实宿主确实按该目标执行，保留审查输出和调用前后的范围证据。 |
| `not-representable` | 该目标遗漏或混入变更。核对当前入口是否还有精确的目标选项。 |
| `needs-evidence` | 按给出的原因补证，例如回读独立的请求补丁，把同一文件里的旧改动区分出来。 |

所有可用目标都无法只审本次差异时，以既有 `fallback_reason: missing` 记录缺少精确入口，令 `capability_evidence` 指向具体的候选、混入或遗漏的改动。按原顺序用下一个能读取这份差异的方法。若本次差异本身都无法重建，交 PM 补证。

实际执行后，输入已变或输出无法绑定本次目标，丢弃该结果并记 `malformed-output`。工具改写了工作区则按 `unsafe-mutation` 交 PM 处理。实际审查完成、结果与范围都已核实，才记录原生方法和 `fallback_reason: null`。

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

## 逐路径与逐规则覆盖

- an internal standards coverage record for PM validation. QA derives applicable rules independently
  from the registered built-in sources, optional existing project index and actual changed paths; `task_pack_rule_ids` records what PM dispatched:

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

## Schema 2 result binding

The QA result must declare top-level `schema_version: 2` and include:

```yaml
handoff_ref:
  request_id: <current-QA-pack-task-request_id>
  task_id: <current-QA-pack-task-id>
  agent_alias: <current-QA-pack-task-agent_alias>
  agent_ref: {host: <actual-host>, agent_id: <actual-native-id>}
  task_pack_sha256: <SHA-256-of-the-complete-current-QA-pack-bytes>
```

Both `validate` and `extract` require `--task-pack`. CLI checks request, task, alias, native identity, SHA
and existing scope/standards semantics against the current pack. It rejects old formats, identity mismatches
and old-pack PASS. A valid pack SHA/structure does not prove actual review execution, model reading or read-only
tools; PM/QA still verify real evidence. Retain no fallback for old handoffs. An executing QA pack must bind
an actual RUNNING／QA, non-retired xy-qa task. After PASS, preserve that original pack and byte SHA as
acceptance grounds. A graph entering QA_PASSED needs no re-export, and old results must not be rebound to
a re-exported pack. Only scope/standards changes require an updated complete pack, delta review by the
original Reviewer and a new result bound to that pack, retaining still-valid conclusions.

## 固定回执构造

普通后台 Reviewer 无原生结构化输出能力时，沿用同一审查方法。原 Reviewer 在交接中给出当前包原字节 SHA-256、最终判定及已核实的证据。只读 Reviewer 通过原消息交接；若本任务和宿主已授权写入指定交接位置，可使用该位置。Shell 重定向也须遵守原有只读权限。PM 核对发件实例和当前原生调用，把原判定送入固定 `compose` 命令。承载者只负责传输，不替 Reviewer 选择结论、归类路径或补写证据。无需为本轮生成 Python、Shell 或其他一次性组装脚本。

下例演示一个已有冻结范围的任务如何提交一条规则。替换包摘要、方法执行记录、路径和命令日志等示例值；规则结论须能从原文和证据复核。

```json
{
  "task_pack_sha256": "<本次 Reviewer 已核对的原包摘要>",
  "audit_result": "PASS",
  "review_method": {"selected": "host-native-review", "capability_evidence": ["<本次只读审查执行记录>"]},
  "skill_evidence": {"skills_used": ["xy-qa-review"], "unavailable_required_skills": [], "uncovered_audit_surfaces": []},
  "review_details": {"findings": [], "verification": [{"command": "<实际核对的命令>", "exit_code": 0, "log_ref": "<完整日志>"}]},
  "path_groups": [{"paths": ["services/api.py"], "rule_ids": ["eng-source-boundary"], "reason": "外部请求在此进入服务"}],
  "rule_groups": [{"rule_ids": ["eng-source-boundary"], "severity": "hard", "disposition": "pass", "evidence_refs": ["<固定版本 services/api.py 对应行段与测试定位>"]}]
}
```

- `review_method`、`skill_evidence`、`review_details` 沿用当前回执字段。包内已有 `task.qa_scope_ref` 时，可省略 `review_method.scope_ref`；否则由 Reviewer 给出完整的实际审查范围。
- 每条固定路径在 `path_groups` 显式出现一次，每项待审规则在 `rule_groups` 显式出现一次。只合并适用规则、判定依据相同的路径，或结论和直接证据相同的规则。没有适用规则的路径写空 `rule_ids` 并解释原因；`not_applicable` 写明 `not_applicable_reason`。项目规则提供原文的 `severity`，使用非规则 ID 的原文定位时给出 `source_anchor`。发现漏派规则时提供其实际 `source_path`、`source_fingerprint` 和适用证据，向 PM 返回有阻断发现的 FAIL。
- 由 PM 把展开后的完整回执直接保存到新的内部候选文件。向会话交回摘要、证据位置、命令退出状态及结果路径即可。以下命令在已授权的交接目录使用尚不存在的文件名，`set -C` 防止覆盖已有普通文件。

```bash
(
  set -C
  bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/delivery/qa_handoff_cli.py compose \
    --task-pack "${qa_task_pack:?当前 QA 包}" --input "${qa_decisions:?原 Reviewer 的最终判定}" > "${qa_candidate:?新的候选回执路径}"
)
```

省略 `--input` 可由授权承载方通过 stdin 传入同一判定。退出 0 表示回执可按既有 `validate` 校验，实际结论取其 `audit_result`。失败、草稿、宿主错误或无法归属原 Reviewer 的文字都不能替换有效回执。证据不足以支持 PASS 时，由原 Reviewer 交回有依据的阻断发现；尚未形成最终判定，或命令拒绝输入时，PM 保持待验。原生结构化调用已发生但失败、取消或结果残缺时按原宿主规则处理，不将其包装成普通判定。

<a id="原生结构化交接"></a>

## Native structured handoff

When the current host's available, authorized QA invocation supports a schema, first obtain this pack's
current QA handoff JSON Schema with `qa_handoff_cli.py schema` and pass it to that same native QA call.
Do not add a model call merely to convert existing prose into JSON or start another Reviewer.
PM 在已授权的内部交接目录准备两个未使用的路径，分别在原生调用前输出 schema、成功终止后提取结果，完整对象直接进入对应文件：

```bash
(
  set -C
  bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/delivery/qa_handoff_cli.py schema > "${qa_schema:?新的 schema 路径}"
)
# 取得本宿主成功终止的结构化结果后执行。以下以 Codex 为例。
(
  set -C
  bash "<plugin-root>/lib/python_runtime.sh" -B -X utf8 "<plugin-root>/plugins/source_pack.py" helper --project "<absolute-project>" lib/delivery/qa_handoff_cli.py extract \
    --host codex --input "${native_qa_result:?set actual terminal native-result.json}" \
    --task-pack "${qa_task_pack:?set current complete QA task pack}" > "${qa_candidate:?新的候选回执路径}"
)
```

`extract` reads Codex's saved final QA object, or extracts a structured object from a successful Claude/AGY
terminal envelope, then directly reuses existing `validate` checks for scope, review_method, rule coverage
and evidence semantics. Success proves only those mechanical contracts. PM/QA still check actual review
execution, read-only boundaries, pinned scope, model/effort and evidence before accepting QA PASS. Failure,
cancellation, partial streams, non-objects or absent structured results must not masquerade as valid handoffs.

当前原生 Reviewer 若因上下文耗尽而终止，PM 在既有任务记录保留终止证据定位及最近一次批次进度。
缺少绑定当前包和原实例、经校验的最终回执时，独立 QA 保持待验，沿用仍有效的 Writer 构建和测试证据。
宿主错误通知及进度摘要均不能生成 PASS 或 FAIL。依照原请求恢复合同处理，不向耗尽实例自动重放，
也不创建第二个 QA 节点、替换已绑定的身份或以换审查方法跳过待验范围。

同一次原生结果在 `review_details` 内记录发现和验证条目，使用已有方法取得的真实证据：

```yaml
review_details:
  findings:
    - severity: P1
      blocking: true
      detail: <具体位置、触发条件与可观察影响>
      evidence_refs: [<可复核的差异、源文件或完整日志引用>]
      owner_role: xy-backend
      next_step: <负责角色可实施的返工或补证事项>
  verification:
    - command: <实际执行或核对的完整命令>
      exit_code: 1
      log_ref: <可读取的完整日志引用>
```

发现优先级用 `P0` 到 `P3`，是否阻断由 `blocking` 明确给出。每条发现至少有一项
证据引用。FAIL 至少有一条阻断发现，并给出原 Writer 角色或 `pm` 及具体后续动作。
PASS 可以附带非阻断建议，此时无需指派的 `owner_role`、`next_step` 填 `null`。
没有发现或未运行及核对任何命令时，填写相应空数组。退出码根据命令目的判断，预期的
负向验证可以有非零退出码。字段校验通过后，PM 仍须核实引用指向当前运行和完整日志。

已存在的内部 schema 2 回执可省略 `review_details`。其中旧版 FAIL 需要有已记录的硬
规则失败、当前包确实漏派的适用规则，或具名的强制 Skill／审计面缺口。沿用既有扩展元数据
时，`extract` 原样返回内层对象。新的严格生成 schema 始终输出 `review_details`。

- Codex uses the current version's supported `exec --output-schema <schema-file>`. `codex review` lacks
  that flag; do not append it to review or bypass existing review_method order for structured output.
  Save final QA JSON with `--output-last-message <native-result.json>` before extract. Do not treat the
  exec event stream as a final message; also verify successful completion of the native call.
- Claude uses supported, authorized `-p --json-schema <schema-json>`. A successful terminal result
  envelope must still meet type／subtype／is_error and structured_output contracts.
- AGY uses supported, authorized `--json-schema <schema-json>`. Terminal results require
  `conversation_id`, `status: SUCCESS` and `structured_output`. `response`/`usage` may be absent;
  validate structure/consistency when present. Usage visibility is not a new QA gate.

Ordinary JSON handoffs use `validate --input <handoff.json> --task-pack <current-qa-task-pack.json>`.
省略 `--input` 时从 stdin 读取。两个入口共同拒绝重复键、非有限数和非法 UTF-8
或孤立代理字符。回执和原生终端输入限制为 4 MiB，文件应通过无链接父目录的实际路径
指向稳定的单链接普通文件。stdin 以 UTF-8 字节流读取。
Task Packs still export through `task_graph_cli.py task`, without the QA schema. Check native commands
against current help and actual session capabilities; static documentation/successful extraction do not
prove successful model execution. AGY diff/Artifact human approval is human review, not `host-native-review`
or independent AI QA. Existing approval, read/write boundaries and method order remain unchanged.

对验收声明的检查按[实现验收](implementation-acceptance.md)核对原文与证据。
