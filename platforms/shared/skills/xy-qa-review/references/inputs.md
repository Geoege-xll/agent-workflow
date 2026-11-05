## Inputs

Receive only the current self-contained 2.0 QA pack: `schema_version: 2`, this task's `task`, necessary
applicable standards, approval/UI authority, current review scope and evidence. The task includes
workflow_level, module, role, agent_alias, instance_policy:fresh, context_policy:handoff_only and actual
agent_ref. A new Reviewer must not inherit/copy full PM or sibling history. Full retains request-closure
audit. Light requires no Full graph, but selected independent QA still needs current identity/evidence binding.


- approved task contract, request dependency closure, and exact owned paths;
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

## 2.0 result binding

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

<a id="原生结构化交接"></a>

## Native structured handoff

When the current host's available, authorized QA invocation supports a schema, first obtain this pack's
current QA handoff JSON Schema with `qa_handoff_cli.py schema` and pass it to that same native QA call.
Do not add a model call merely to convert existing prose into JSON or start another Reviewer. Use these
read-only entries from the installed project root:

```bash
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/qa_handoff_cli.py schema
bash .agent-workflow/lib/python_runtime.sh -X utf8 .agent-workflow/lib/qa_handoff_cli.py extract \
  --host codex --input "${native_qa_result:?set actual terminal native-result.json}" \
  --task-pack "${qa_task_pack:?set current complete QA task pack}"
```

`extract` reads Codex's saved final QA object, or extracts a structured object from a successful Claude/AGY
terminal envelope, then directly reuses existing `validate` checks for scope, review_method, rule coverage
and evidence semantics. Success proves only those mechanical contracts. PM/QA still check actual review
execution, read-only boundaries, pinned scope, model/effort and evidence before accepting QA PASS. Failure,
cancellation, partial streams, non-objects or absent structured results must not masquerade as valid handoffs.

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
Task Packs still export through `task_graph_cli.py task`, without the QA schema. Check native commands
against current help and actual session capabilities; static documentation/successful extraction do not
prove successful model execution. AGY diff/Artifact human approval is human review, not `host-native-review`
or independent AI QA. Existing approval, read/write boundaries and method order remain unchanged.

Document acceptance checks current goals/execution stage separately from the topic plan's genuinely accepted
version. PROJECT links only explicit baselines. completed, HTML existence or non-empty lists do not create
approval/delivery. Preserve old baselines during iteration/cancellation; do not automatically index old
historical drafts without grounds.
