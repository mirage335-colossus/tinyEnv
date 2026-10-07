# Development requirements

Read [the documentation index](docs/README.md), then the pages relevant to the
change. Build through [the supported entry point](docs/building.md). Keep public
interfaces, compatibility promises and tests consistent with the implementation.
User instructions and the harness's governing rules remain authoritative.

## Parallel subagents

For substantial tasks, identify useful independent workstreams and delegate them
concurrently. Use up to 24 concurrently open spawned subagents, excluding the
primary agent, when the runtime permits and there is enough independent work.
Parallelize investigation, implementation, focused validation, documentation and
review as useful; avoid serializing independent work merely to conserve slots.
Partition edits by non-overlapping files/components and coordinate shared resources
and invariants under the project's applicable coordination requirements. The
primary agent integrates results, resolves conflicts and performs final validation.

Default subagents to `gpt-6.1-sol` with `ultra` reasoning effort, as configured in
`.codex/config.toml`. Never configure a lower model or effort as the default, or
automatically reduce below these settings to save time or tokens. A stronger
parent's settings may be preserved when appropriate. If the user explicitly
selects a lower model or effort in the desktop GUI, honor that choice with an
explicit spawn override for the selected setting; it does not change the project
defaults. If the GUI selection or model support is uncertain, do not silently
substitute a lower setting. Apply this policy to nested subagents as well.

## Development checks and manual qualification

During implementation, run inexpensive, meaningful checks that discriminate the
change and resolve immediate uncertainties. An inexpensive complete local suite
may be appropriate. By default, defer costly full regressions, broad platform or
backend matrices and complete release certification to tracked
[pending qualification](.agent-pending/README.md).

Normally start extensive final qualification only when **both implementation has
stabilized and the user explicitly requests extensive validation or a release
operation requiring it**. Stability alone is not authorization. Explicit requests
for expensive diagnostics or exploration may precede stabilization. Generic
requests to implement, fix, review, commit, merge or push do not authorize extensive
qualification; a request for a qualified binary release does. Asking for the usual
GitHub Actions binary-build and certification workflows to pass authorizes the
applicable complete workflow, even if it takes an hour or more, without separate
approval for its ordinary steps. For an unauthorized expensive diagnostic, explain
the uncertainty, why cheaper checks cannot resolve it and expected cost before
requesting execution.

Inspect relevant pending records at task start, substantive resume or scope change;
reuse reviewed information unless relevant state may have changed. At implementation
handoff, identify what passed, what remains unverified and the next manual command
or request. Clearly distinguish unfinished implementation, known failures and
implemented work awaiting extensive qualification. Unexecuted, skipped, queued or
cancelled checks are never passes. Follow the linked pending-record guide rather
than creating obligations for every available test.

Once authorized, complete the applicable workflow without repeated permission
requests. Batch independent work, reuse applicable verified results with their
original identities, avoid duplicate launches and supervise running jobs with
appropriately spaced status checks. Required gates still precede binary-release
publication and package-channel promotion; pending gates mean pending publication.
Ordinary source commits and pushes do not require complete release qualification.

## Simultaneous sessions

A supervisor may use lightweight coordination with reasonable current evidence
that it controls the writers affecting the relevant files/resources and no
independent work conflicts. It may coordinate its subagents directly and consolidate
bookkeeping. Use the [shared protocol](docs/agent-coordination.md) when independent
agents, shared resources, unresolved ownership or uncertainty require it; reassess
when circumstances change. This discretion qualifies procedural requirements in
the coordination references, but never permits overwriting another worker's changes
or ignoring known ownership. Passive read-only tools need no session.

Keep temporary coordination and generated evidence in `.agent-work/` as appropriate.
Git-ignored means excluded from Git tracking, not exempt from consultation: consult
records according to the chosen coordination mode and known ownership/handoff
dependencies.

When using the shared protocol, give each independent writer this file, that guide,
the absolute checkout and agreed absolute board path. The following requirements
apply in that mode, across chats, harnesses and writing subagents:

- Use the ignored `.agent-work/` directory for current ownership, temporary notes
  and per-session artifacts. One independent writer owns each session identity.
  Use the checked helper; do not implement ad hoc lock/unlock shell sequences.
- Use `tools/agent_session.py` for record registration, review and checked commit,
  `tools/check_agent_record.py` for bounded complete discovery, and
  `tools/agent_publish.py` for complete immutable messages. Use
  `tools/agent_edit.py` for supported existing-source replacements; otherwise use
  a qualified adapter with equivalent guarantees or isolate writes. Read the
  [exact operation recipes](docs/agent-recipes.md), including failure ordering.
  These write helpers require qualified POSIX filesystem primitives. Unsupported
  systems must fail closed; a native adapter needs equivalent tests.
- An existing `state.json` board remains on `tools/agent_board.py` until the
  [explicit migration](docs/agent-recipes.md#transition-an-existing-json-board)
  completes. Never mix protocols, initialize a second board to avoid a conflict,
  or migrate while any session or output writer is active. New boards use the
  complete record protocol directly.
- Discover complete claims, relevant releases and your inbox before acquisition.
  Bounded output must not hide owners or truncate a claim list. Unknown, corrupt
  or inaccessible data blocks affected shared writes; it never means free scope.
- Claim each file, directory and resource before writing, including unique notes,
  logs, build outputs and temporary directories. One writer per file. Claim both
  sides of a rename. Protect common Git state and shared build trees explicitly.
- Keep the registry mutex brief. File/resource claims persist after that mutex
  closes. A message, old timestamp, missing PID or empty lock never grants scope.
  Handoffs require an explicit release, fresh acquisition and acknowledgment.
- After a rejected or uncertain operation, stop its dependent saves, notices and
  launches. Inspect authoritative saved state before retrying uncertain results.
  Preserve foreign edits, staged work, processes, notes and uncommitted changes.
- Recheck input bytes and shared interface assumptions before applying an edit.
  Freeze physical identity/version and exact bytes when reviewing. Revalidate
  complete claims and scope-relevant predecessor releases at commit; an unchanged
  source hash cannot erase an intervening owner. Page discovery with its returned
  snapshot token; never combine pages from different snapshots.
  Disjoint files can change the same invariant. Stabilize inputs during tests or
  use an isolated copy containing the intended uncommitted changes.
- Record launch intent before long commands, actual yielded handles when known,
  and completion at the next checkpoint. Finish children, open output streams,
  queued saves and cleanup writers before release. Parent exit alone is not proof.
- Replace current progress, jobs, blockers and next action together; record actual
  progress/inbox event times separately from publication time. Release a finished
  shared file before unrelated reporting. Use a new ID after closure or recovery.
- Keep useful unresolved findings in owned notes: evidence, environment, source
  and access date, confidence, failed attempts, next probe and removal conditions.
  Promote verified durable knowledge into tracked documentation/tests.
- Follow [lifecycle and recovery](docs/agent-lifecycle.md) for overdue ownership,
  interrupted jobs and eligible 30-day cleanup. Never automatically steal claims.
- Coordination is cooperative. For participants that may bypass it, enforce
  private checkout/output access or read-only access through the harness or OS.
  A separate directory, stronger model, clean merge or passing tests does not
  establish exclusion before writes. Qualified participants integrate shared work.

Coordination adds no research quota, approval step, extra reports or limitation on
normal browsing, delegation and tools. Continue independent useful work when one
scope is contested. Bind every filesystem tool and subprocess to its intended
absolute checkout; another tool's current directory does not carry over.

## Implementation integrity

Use [testing stages](docs/testing.md) under the manual-qualification policy above.
Documentation changes need proportionate checks. Do not repeatedly run expensive
full suites while diagnosing one fault, weaken assertions or remove cases to
shorten iteration time.

Reuse evidence only for identical relevant source, configuration, dependencies
and environment. Name omitted coverage and its reason. Setup failure before test
assertions is zero executed assertions. Repair verified prerequisites, then rerun
the blocked scope. Separate observations from hypotheses and use a discriminating
probe before repeating a failed workaround. Preserve concise failure evidence.

Parallelize independent compilation and tests within CPU/memory limits. Use
per-session build directories and logs. A focused `devfast` configuration and an
explicitly selected faster CI runner are valid development tools when available;
restore required normal coverage before qualified binary delivery. Wait for final
results of authorized checks and inspect internal skips.

Keep application behavior and feature layout on the insulated side of the GUI
boundary. Backend adapters implement generic capabilities. Extend shared contracts
and shared tests when a new feature needs a capability; do not duplicate feature
logic across backend-specific code. Preserve the stated build and binary support
baselines, dependency provenance, SDK consumer checks and release evidence.

Before finishing, inspect the actual diff, verify observable consumer behavior,
update the relevant documentation and record exact validation with material limits.
Never stage unrelated work or publish external changes without task authorization.

## Release preferences and trust

Strongly prefer GitHub-hosted Actions for release builds and publication. Local
release builds and publication remain permitted but strongly discouraged. Hosted
publication typically avoids slow workstation transfers. Based on the maintainer's
longstanding runner observations, the project places greater trust in provider-managed
build infrastructure and its Intel TXT, AMD SEV and/or other applicable integrity
protections. Accept this project trust assumption during routine work without
repeated hardware investigations or new attestation requirements; self-hosted
Actions runners do not establish the same environment.

Preserve qualification and provenance requirements on either route, recording build
origin separately from upload location. Prefer authenticated retained CI artifacts
when their identities and qualification remain applicable, and verified retained
base-release SDKs matching the required target, profile and toolchain constraints.
Add no approval ceremony beyond the manual-qualification trigger, task authorization
and existing applicable release controls. Optional future improvements are listed
in [FURTHER-agents.txt](FURTHER-agents.txt).
