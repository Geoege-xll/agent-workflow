---
name: xy-build-verify
description: "Verify the build, runnable results and relevant tests for the current Light／Full delivery, handing off real evidence according to actual risk."
---

<!-- agent-workflow-pack:managed-skill -->

# xy-build-verify

Both Light／Full use minimum sufficient verification appropriate to the actual delivery type. Production
code retains evidence of a successful affected-target build/compile and minimum startup/smoke or key entry;
verify documentation/static prototypes by type. Light defaults to a native implementer with the current
self-contained task pack; loading this Skill does not force a Full plan, DAG or independent QA. At handoff,
PM assesses independent audit, documentation and memory by actual risk. Full and selected mandatory
independent QA must not be omitted. Ordinary copy uses WORKFLOW's `Light UI copy` consumer/resource checks;
file suffixes do not exempt actual build inputs.

Before verification, read [verification scope](references/verification-scope.md).
Select proportionate commands from the task pack, adapter and repository evidence; discovered
commands are candidates, not a mandatory full-suite list. Preserve required checks, run selected
commands for real, and record every exit code. Reuse valid evidence and stop when coverage is
sufficient; expand or repeat only for a specific gap identified by the linked policy.
Determine the minimum sufficient scope before execution. Repository-wide tests require an actual coverage
need or explicit requirement, not merely entry into delivery. Production-target build/compile and runnable
evidence are mandatory. Hand off when coverage is sufficient and evidence remains valid; do not append
unsupported repeated builds/regressions.

<!-- workflow-contract: references/verification-scope.md -->

## Evidence contract

```text
## Build-verify
- Role: xy-*
- Scope: <changed behavior and mandatory coverage; distinguish new execution from valid reused evidence>
- Build / runnable result: <affected target, environment and actual build plus run/smoke evidence; non-production applicability>
- Commands: <exact commands>
- Exit code: 0
- Evidence summary: <success trailer and relevant warnings>
- Full log: <subagent thread reference or ignored local artifact path>
```

Do not paste a long raw log into the PM handoff. The full reference must be resolvable
by QA. If a command fails, include the exit code, a short failure excerpt, the full-log
reference, and `Status: BLOCKED`. After two failed repair attempts, stop and report to
the PM. Never invent, paraphrase away, or claim unexecuted validation.
In existing Validation, explain added coverage, invalidated evidence/specific risk, or the new diagnosis,
testable hypothesis/repair progress and expected evidence for continued failed rework. Keep relevant
unverified scope explicit. Without progress, stop the current repeated failing path early and return it to
PM under the policy above; do not reset existing limits or treat stopping as success. Without a gap, add
no verification report/test file. A scoped pass supports only that scope, not a claim that all tests passed.

`BUILD_VERIFIED` is evidence, not a QA result or user-facing completion state. For Full work, preserve the order
`QA PASS -> controlled-document projection -> PM commit assessment -> memory closeout -> final report`;
this Skill creates no QA report, design artifact,
approval record, or metadata file. Light assesses closeout at the actual handoff; an unaudited result is not QA PASS.
After PM accepts evidence and the necessary feedback window ends, close or retire the instance under WORKFLOW's
instance lifecycle. Retain readable full-log references; ending a native instance must not lose the sole evidence.

For isolated tasks, hand evidence back with the exact worktree/base/checkpoint identity; only PM
creates scoped local transport checkpoints. Follow `xy-workflow/references/worktree-delivery.md` for
composed-result verification and confirm/auto main-branch delivery. A unit's green tests are not
integration proof; keep checks proportional and preserve the ordinary non-worktree route.
