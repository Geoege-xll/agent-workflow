## Output projections

Produce two projections from one plan. The internal planning record retains the exact summary fields
and machine-readable graph needed by the PM. The concise user approval brief is a natural-language
projection of material decisions only; it is not a serialization of the internal record.

### Internal planning record

Keep the following structures in PM working state; PM projects the approved plan into one concise
recoverable Markdown file, not another serialized DAG. Never present the raw `task_graph` JSON,
`plan_summary` YAML, request or task IDs, requirement fingerprints, path arrays, semantic locks,
scheduler states, gate arrays, or complete command lists unless the user explicitly asks to inspect
or export the internal plan.

```yaml
plan_summary:
  goal: ""
  affected_surfaces: []
  affected_modules: []
  workstreams: []
  parallel_lanes: []
  mandatory_sequence: []
  shared_contracts: []
  controlled_document_candidates: []
  major_risks: []
  acceptance_strategy: []
  prototype_choice:
    applicable: true | false
    affected_surfaces: []
    recommended_policy: required | waived_by_user | not_applicable
    recommendation_reason: ""
    selected_policy: null
```

### Concise user approval brief

Before approval, the PM presents only:

- the observable goal and affected surfaces;
- in-scope work and explicit non-goals;
- a short list of workstreams, meaningful parallel work, and mandatory order;
- material public-contract, data, security, migration, or compatibility impact;
- major risks or irreversible effects; and
- the acceptance strategy plus the PM's plain-language controlled-document update conclusion; and
- for design-change UI, the recommended prototype branch with one short reason and the two user
  choices: design/update prototype or direct implementation.

Use short prose and bullets. Omit raw YAML/JSON, internal Skill names, requirement fingerprints,
task IDs and states, memory/provider details, complete Task Packs, and routine scheduler output.
Complete this brief before the PM presents or invokes the single approval choice; do not append
material plan details after opening that choice. For a revised request with an explicit production-only
instruction, follow the linked plan lifecycle rather than inheriting a completed prototype task or
asking for the same choice again. Draft only the current affected work; preserve unaffected approvals.

```json
{
  "task_graph": {
    "request_id": "<stable-request-id>",
    "plan_state": "draft",
    "requirements_fingerprint": "<fingerprint-of-the-reviewed-requirement-brief>",
    "standards_contract": {
      "index_path": "<project.yaml-resolved-docs.standards-path>",
      "root": "<project.yaml-resolved-docs.standards_root-path>",
      "index_fingerprint": "<64-lowercase-hex-sha256>",
      "required_engineering_rule_ids": ["<applicable-engineering-rule-id>"],
      "required_design_rule_ids": ["<applicable-design-rule-id>"],
      "leaves": [
        {
          "path": "<standards_contract.root/relevant-leaf.md>",
          "domain": "engineering",
          "content_fingerprint": "<leaf-sha256>",
          "rule_ids": ["<applicable-engineering-rule-id>"]
        },
        {
          "path": "<standards_contract.root/DESIGN_RELEVANT.md>",
          "domain": "design",
          "content_fingerprint": "<leaf-sha256>",
          "rule_ids": ["<applicable-design-rule-id>"]
        }
      ],
      "protected_paths": []
    },
    "ui_contract": {
      "prototype_paths": ["<project.yaml-resolved-docs.standards_root>/prototype"]
    },
    "tasks": [
      {
        "id": "<task-id>",
        "request_id": "<stable-request-id>",
        "task_type": "writer",
        "role": "<xy-role>",
        "surface_kind": "production_ui",
        "qa_scope": "request",
        "goal": "<independently testable deliverable>",
        "owned_paths": ["<exact/path>"],
        "semantic_locks": ["<shared-contract-key>"],
        "depends_on": [],
        "blocks": [],
        "gates": ["requirements_approved"],
        "input_contracts": [],
        "output_contracts": [],
        "acceptance_evidence": [],
        "verification_commands": [
          {"run": "<exact command>", "expected": "<expected output or exit condition>"}
        ],
        "controlled_document_access": {
          "adapter": "project.yaml",
          "documents": [
            {
              "path": "<standards_contract.index_path>",
              "mode": "full",
              "reason": "resolve the smallest applicable standards leaves",
              "sections_or_queries": [],
              "content_fingerprint": "<standards_contract.index_fingerprint>",
              "applies_to": ["<owned-path-covered-by-this-authority>"],
              "rule_ids": []
            },
            {
              "path": "<standards_contract.root/relevant-leaf.md>",
              "mode": "targeted",
              "reason": "<why these engineering rules apply>",
              "sections_or_queries": ["<relevant-heading-or-rule-id>"],
              "content_fingerprint": "<leaf-sha256>",
              "applies_to": ["<owned-path-covered-by-this-authority>"],
              "rule_ids": ["<applicable-engineering-rule-id>"]
            },
            {
              "path": "<standards_contract.root/DESIGN_RELEVANT.md>",
              "mode": "targeted",
              "reason": "<why these design rules apply>",
              "sections_or_queries": ["<relevant-heading-or-rule-id>"],
              "content_fingerprint": "<leaf-sha256>",
              "applies_to": ["<owned-path-covered-by-this-authority>"],
              "rule_ids": ["<applicable-design-rule-id>"]
            }
          ]
        },
        "ui_change": {
          "route": "<UI-Conformance|UI-Patch|UI-Page|UI-Flow>",
          "design_delta": "none | changed",
          "prototype_policy": "not_applicable | required | waived_by_user",
          "prototype_decision": null,
          "design_authority_refs": [
            {
              "kind": "<controlled_document|prototype_contract|design_standard|production_baseline>",
              "authority_id": "<stable-lowercase-id>",
              "path": "<normalized-project-relative-path>",
              "anchor": "<heading-or-contract-anchor>",
              "content_fingerprint": "<64-lowercase-hex-sha256>",
              "resolution_state": "resolved"
            }
          ],
          "affected_surfaces": ["<exact UI surface>"],
          "justification": "<objective routing evidence>"
        },
        "required_skills": [],
        "audit_surfaces": ["standards-conformance", "ui", "accessibility"],
        "state": "DECLARED"
      }
    ]
  }
}
```

This example is a `production_ui` task. Use `surface_kind: design_ui` for `xy-uiux`; use
`surface_kind: non_ui` and omit `ui_change` for non-UI work. Every dependency must have the matching
reverse `blocks` edge. Every writer must have exact owned paths, a role, concrete acceptance
evidence, and verification. Every Writer carries the STANDARDS index plus the matching smallest
domain leaves and `standards-conformance`; `xy-uiux + design_ui` uses design leaves without
engineering leaves. Protected upstream writes require a documented allowed path or a complete `standards_exceptions`
record bound to an exceptional Gate. `xy-uiux` and `design_ui` are a mandatory pair. Bind every
`prototype_contract` authority to `ui_contract.prototype_paths` and every `design_standard`
authority to a leaf under `standards_contract.root/DESIGN_*.md`; do not relabel a typed path with another authority kind.
The shown `prototype_decision: null` is valid only for `UI-Conformance` or an unapproved
design-change draft. A design-change graph cannot be validated or dispatched until the PM replaces
it with the exact machine record containing `source: requirements_confirmation_user_choice`, a
stable `user:` choice reference, the current 64-hex requirement fingerprint, exactly matching
affected surfaces, `recommended_policy`, a non-empty `recommendation_reason`, and
`selected_policy` matching `prototype_policy`. For `waived_by_user`, omit prototype authorities,
prototype-design dependencies, prototype writes, and visual Gates. Necessary `standards_only`
maintenance remains allowed. For `required`, add the matching prototype-mode design task,
prototype authority, and exact page Gates. Preserve requirements approval, standards conformance,
build evidence, and ui/accessibility QA in both branches.
Across the graph, only the `xy-uiux + design_ui` Writer may own either the prototype or design-standards boundary; reject
non-design roles, missing roles, broad ancestor ownership, and hidden transitive Writers.
Keep the draft in PM working state;
the PM decides the post-QA controlled-document projection, presents the prototype recommendation
and choices when applicable, requests approval in natural language, materializes the selected UI
branch, freezes the approved fingerprint and `prototype_decision` internally, and validates the
graph before dispatch.
