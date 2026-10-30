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
    capability_evidence: []
    fallback_reason: null | missing | launch-failed | timeout | malformed-output | unsafe-mutation | recursive-delegation
    scope_ref:
      repositories:
        - path: . | <nested-repository-path>
          base_revision: <fixed-base>
          head_revision: <fixed-head>
          diff_fingerprint: <64-lowercase-hex-sha256>
          changed_paths: []
  ```

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
