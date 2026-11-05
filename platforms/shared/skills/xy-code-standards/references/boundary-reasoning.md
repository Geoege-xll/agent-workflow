# Boundary reasoning

Choose questions only for boundaries actually involved in or changed by current code, and judge them against
applicable project rules. This reference does not require prebuilt capabilities, changed legal inputs, fixed
limits or a complete test matrix. Reuse sufficient existing evidence directly.

## Inputs and contracts

Follow real producers through to consumers: does any step change field types, nulls, units, encoding or
normalization? Could so-called cleanup remove valid text, precision or identity information? Locate authoritative
parsing, mapping and error exits, then identify which layer owns the gap. Small explicit mappings need not become
a framework, and type assertions cannot cross a trust boundary.

## Mutable state and asynchronous results

Who owns the state, and which event invalidates an old result? Follow reads, waits, retries and commits to check
the identity, version and business context that must remain valid. A lock, actor or single thread alone does
not prove invariants across waits. Establish whether an operation has side effects and what happens when its
result is unknown before deciding whether replay is safe. Do not infer safety merely from method names or HTTP
methods, or treat old cache/late results as the current authoritative result.

## Resources and cancellation

Trace the actual owner through resource acquisition, transfer, normal completion, failure and cancellation.
Does an existing timeout cover the entire operation? Does cancellation actually end underlying work, and do
child processes, streams, files or subscriptions remain alive? Select observable evidence only for actual risks.
Canceling a waiter does not prove that external side effects stopped; closing a UI does not prove resource release.

## Writes and publication

Identify preparation, commit and publication boundaries: did failure occur before or after them, which old data
must survive, and which temporary resources does the current operation actually own? Check whether exceptions,
interruptions, same-name replacement or concurrent updates change cleanup targets, so cleanup does not damage
another operation. Separate commits to a database and an external system are not naturally atomic across that
boundary. Project contracts and existing implementation still determine transactions, file publication and recovery.

## Distinguish conclusions with evidence

Turn a concern into a concrete failure scenario and observable consequence; first check whether existing coverage
already proves the relevant invariant. Test doubles can control timing and failure location. If a conclusion
depends on a real framework, disk, process or caller, also check existing real-consumer evidence. Mark the limits
of conclusions when evidence is absent. Do not describe a possibility as an observed defect, or expand scope/add
a test stage automatically merely because questions were listed.
