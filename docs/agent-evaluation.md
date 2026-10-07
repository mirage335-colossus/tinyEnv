# Evaluating useful agent cooperation

Use this optional guide when evaluating a coordination change or harness. Normal
development follows [the coordination workflow](agent-coordination.md); it does
not require an exercise, scorecard, extra journal or evaluator approval. Keep the
requested software outcome primary. This guidance covers general coordination exercises without requiring external
project history or computational workloads.

## Freeze a fair exercise

Before dispatch, retain the exact prompts, public behavioral contracts, acceptance
criteria, guidance/helper hashes, complete source inventory and environment.
Record the actual model/harness versions and available tools, participant count
and concurrency limit. Count every dispatched attempt, including blocked and
failed attempts. A later guidance edit creates a different treatment; unchanged
guidance is a replication, not proof of improvement.

Use independently useful tasks such as two related bug repairs, an integration
change and an independent documentation correction. Include at least one shared
invariant across disjoint files and a real contention point. Keep a useful
independent task available while that point is owned. Evaluate contributions by
observable behavior and preserved changes, not messages, commits or lines written.
Use a matched single-worker or previous-guidance control if making a speed or
quality comparison, and disclose differences in model, tools, task difficulty,
context and machine load. A tiny exercise cannot establish general model rankings.

Materialize complete disposable checkouts, including tracked ignored/vendor
inputs, correct modes and any required dependency groups. Do not inject faults
into production source. Preflight the documented commands and both known-failing
and known-fixed controls before dispatch. Freeze held-out checks and their hashes;
keep solutions and evaluator-only evidence outside workers' accessible context
when the harness can enforce that. Disclose instruction-only blinding and reused
conversation history. Fixture corrections and solution exposure invalidate that
comparison; preserve the attempt instead of silently replacing it with success.

Give every worker the same absolute physical checkout/board paths and applicable
AGENTS/workflow files, plus its task's public contract. Provide known prerequisites
and access constraints. If independent research is an exercise criterion, say so
before dispatch and give matched controls equivalent tools and instructions.
Distinguish actual source/tool evidence from copied citations or self-report.
Unavailable access is an unmet criterion, not a reason to silently change the task.

## Observe the work without adding ceremony

The evaluator follows the same ownership rules for fixtures, observers, snapshots,
logs and Git state. Collect normal harness traces and session records where
available; do not require workers to maintain a second activity journal or extra
status messages. Keep private prompts and unnecessary personal data out of tracked
source. A sample first observed after release cannot by itself prove an unclaimed
write: identify the observation method and any unobserved interval.

Record these parallel dimensions with evidence links and explicit unknowns:

| Dimension | Useful observations |
| --- | --- |
| Software outcome | Required public behaviors passed/failed, preserved peer contributions, regressions, coverage gaps and final candidate digest |
| Iteration cost | Wall time, actual overlapping work, test/build time, ownership waiting and work continued while waiting |
| Coordination cost | Setup trouble, bounded ownership reads, rejected/stale operations, handoff delays and time spent repairing records |
| Human intervention | Each reminder, clarified requirement, tool/environment repair, ownership correction and rescue edit; distinguish necessary input from coaching |
| Research and verification | Evidence of relevant investigation, discriminating tests, failed attempts, omitted checks and independently verified results |
| Protocol behavior | Complete ownership discovery, actual predecessor acknowledgment, guarded saves, stopped output writers and truthful current checkpoints |

Use observed elapsed durations when available; never infer them from publication
timestamps alone. Separate meaningful interventions from automatic helper retries.
Keep original failures and later corrections as different observations. Useful
throughput is accepted, independently checked contributions per elapsed time;
report quality and intervention cost beside it rather than combining unlike units
into an unexplained score. A clean merge or collision-free board is not evidence
that the requested program behavior works.

## Exercise the failure boundaries

Choose scenarios appropriate to the proposed change. A small study may include:

- Two workers request the same file while a third completes independent work.
- A file passes through an intermediate owner without changing its bytes; the next
  owner must discover and acknowledge the actual predecessor.
- A stale prepared edit or changed shared interface is rejected before any dependent
  acknowledgment, generator or test launch.
- A job finishes while acquisition fails; its completion is still reconciled, and
  a parent cannot release outputs while a child or cleanup writer remains active.
- A finished shared edit is released promptly while unrelated evidence work continues.
- A malformed record or changed paginated snapshot prevents affected writes without
  hiding an owner or granting a timeout-based takeover.

Use synchronization barriers and injected failures for deterministic protocol
cases. Preserve successful and failing controls and join all children before
releasing fixture outputs. Never use a synthetic recovery scenario as authority
to reclaim a real session's files. If tools might bypass the protocol, exercise
actual denied writes through every available tool or use enforced isolated
checkouts; instructions and separate directory names do not establish confinement.

The existing [protocol coverage map](agent-recipes.md#invariant-and-scenario-coverage)
and `tests/test_agent_stress.py` test executable filesystem behavior. Their
`FOUNDATION_AGENT_STRESS_WORKERS` process population is not a population of reasoning
agents. Report deterministic process count separately from concurrent model workers,
assignments and waves. Passing those tests does not show that independent models
will follow the guidance, or qualify an untested filesystem, platform or harness.
Do not duplicate those tests as a compulsory model exercise in routine CI.

## Evaluate a frozen result

Freeze final candidate bytes before held-out evaluation. Inspect actual emitted
values, application behavior and complete contribution preservation. Keep the
original expected interfaces; if a test must be adapted, record what changed and
show that the new probe still distinguishes the known bad and good controls.
A setup failure executes zero assertions. Report passed, failed, skipped,
setup-blocked and untested scopes separately, along with all declared criteria.
Do not coach a finished worker with held-out failures and count the repaired result
as the original trial. Label any later supplemental probe explicitly.

A compact evaluator report can use this template; it is not a worker deliverable:

```text
Question/treatments: ...
Frozen prompts, source, guidance, helper and held-out check identities: ...
Models/harnesses/tools/host and actual concurrent workers: ...
All dispatched attempts and any exclusions with reasons: ...
Accepted behavioral contributions and preserved peer work: ...
Elapsed/wait/build/test costs and observation method: ...
Human interventions (requirement, environment, coaching, rescue): ...
Protocol outcomes versus independent software/research outcomes: ...
Failed/setup-blocked/skipped/untested checks and exact evidence: ...
Candidate identity, limitations and the next discriminating experiment: ...
```

Keep only useful evidence under the existing [retention rules](agent-lifecycle.md).
Publish a conclusion proportionate to the observed tasks, models and environments;
a cooperative local trial establishes neither hostile-tool exclusion nor universal
multi-agent speedup.
