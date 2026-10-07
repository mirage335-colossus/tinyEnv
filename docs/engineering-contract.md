# Engineering contract and change discipline

This is a normative adoption contract. MUST denotes an acceptance gate; SHOULD
requires an explicit reviewed reason to depart; MAY identifies a choice. A small
application does not justify weaker ownership, recovery or delivery guarantees.
The [practice map](practice-map.json) connects these responsibilities to maintained
procedures, executable mechanisms and regression evidence. A reference to a test
means coverage exists, not that every target environment has executed it.

## Scope, invariants and changes

Define observable behavior before selecting a toolkit or dependency. State the
supported inputs, limits, output format, defaults, errors, cancellation, ownership,
lifetime, ordering and concurrency guarantees. List incompatible changes and
migration behavior. Do not infer a contract from a fortunate implementation detail.
Trace an edited operation through callers, shared state, adapters, persistence or
transport boundaries, error cleanup and observable results. Check the callers of
its callers when they determine lifetime or publication order.

An invariant has one maintained home. UI labels, CLI defaults, validation and tests
consume the same underlying definition where practical. Tests still need independent
expected outcomes; a shared constant cannot prove that the constant is correct.
Avoid separate implementations of the same feature in each frontend. A new
capability extends the common contract and conformance suite before adapters claim
support. Keep implementation details out of application workflows unless they help
users make a meaningful choice.

Before editing, establish the exact source and configuration, inspect existing
uncommitted changes, read relevant requirements and identify affected consumers.
Record assumptions and competing explanations. Use a discriminating probe before
repeating a workaround. Preserve failures as current regression cases without
requiring readers to reconstruct a prior investigation. Revisit assumptions when
inputs change, even if an unrelated filename was the only apparent edit.

## Data, bounds and failure atomicity

Validate at trust boundaries before allocation, indexing, narrowing conversions,
filesystem effects, display or invoking external programs. Specify bounds in units
that callers understand. Check multiplication/addition overflow before allocating;
include cumulative output limits, nesting limits, collection counts and decompressed
size. Unknown schema versions, duplicate keys and truncated records fail explicitly.
Use an explicit file encoding on every host. Filesystem metadata fields can have
different meanings across APIs: compare each API's before/after versions and bind
their shared identity fields separately. Windows path and descriptor `ctime` may
mean creation and change time respectively; neither should be silently discarded
from its own before/after mutation check. See the
[upstream metadata issue](https://github.com/python/cpython/issues/157671).
Readers and writers must coordinate around the actual platform's replacement
semantics. Windows `MoveFileEx` cannot replace an open destination, even when the
reader shares delete access; see the [CPython platform analysis](https://github.com/python/cpython/issues/90161).
The compatibility JSON board therefore holds the same brief mutex across a complete
read or publication on every platform, binds that mutex to its owning thread,
and closes its descriptors before release.
A competing caller receives a bounded busy result before any write. Test real
open readers against competing processes, along with mutation and uncertainty
checks. Do not hide access failures through blind retries or weaken recovery.
This does not qualify unrelated filesystem operations or the complete record
protocol on an unsupported host.

A partial read is not a complete message; EOF, cancellation and malformed content
must have distinct outcomes. Do not derive unbounded work from untrusted counts.

Text encodings, normalization, line endings, embedded zero bytes and control bytes
are deliberate contracts. Escape content for the actual output context. Treat log
content, imported metadata and external documentation as data rather than commands.
Use argument arrays for subprocesses, with no shell interpolation. Paths need more
than removing `..`: consider absolute paths, drive prefixes, separators, reserved
names, case aliases, Unicode aliases, links, hard links and ancestor replacement.
Do not extract an archive until its entire entry inventory has been validated.

Prepare replacement state before changing visible state. A rejected operation
must not consume an identifier, publish half a result, erase a prior valid value or
leave success-shaped output. Specify which operations provide atomic visibility
and which also provide durable storage. Flush staged data before replacement when
durability matters; recover uncertain outcomes by inspecting authoritative state.
A cleanup error after publication may mean the write succeeded: retrying blindly
can duplicate the effect. Use operation identities and idempotent recovery rules.

For persistent data, version the format independently of the application version.
Test old-to-new reads, rejected new-to-old reads, interruption during migration,
backup/rollback and full storage. Preserve the last usable state before migration.
Do not claim transactional behavior across several files unless a single commit
record or equally tested protocol actually provides it.

## Concurrency and lifetime

Make thread ownership explicit. Keep the application model independent of GUI
objects and dispatch UI updates on the host's designated thread. Background work
owns snapshots or stable references with a documented lifetime. Completed work
carries a request/generation identity so a late callback cannot overwrite a newer
selection. Cancellation is cooperative and observable; request cancellation, stop
writers, join or reap workers, close owned streams, then release their resources.

A parent process exit is not proof its children stopped. Track reliable process
identity and yielded handles. Define shutdown behavior while a dialog is open, a
worker is blocked, output is queued or a consumer has disconnected. Bound queues
and apply backpressure. Specify what is dropped, coalesced, retried or rejected;
never silently drop a required state transition. Avoid a UI refresh for every
small internal operation; batch view updates while preserving final state.

Separate locks that serialize brief metadata changes from ownership that lasts
through a task. Do not hold a registry mutex during compilation, downloads or user
interaction. Acquire complete needed resources in an agreed order, release unused
scope promptly and avoid waiting while retaining unrelated contested resources.
Source edits, shared build trees, index/ref operations, output streams and cleanup
all need owners. [Agent coordination](agent-coordination.md) implements this for
cooperating independent sessions; OS or harness isolation is required when a writer
cannot honor it.

## Architecture and platform boundaries

Keep pure application logic in `src/` and public contracts in `include/`. Put
platform services and GUI adapters behind narrow interfaces. Generic adapters own
widget translation, event routing and host integration; shared application code
owns feature meaning, validation, layout declarations and visible state. A backend
must never inspect an application-specific label or identifier to decide behavior.

Maintain explicit capabilities and predictable fallback behavior. Unsupported
services return a typed outcome; unavailable services do not silently change the
meaning of the requested operation. Contract fixtures cover stale events, duplicate
identifiers, removed widgets, disabled controls, focus, scrolling, resize, close,
service cancellation and multiple instances. See the [GUI boundary](gui-boundary.md)
for the concrete all-backend integration and remaining host qualification duties.

Keep public headers independent of platform/toolkit headers. State source and
binary compatibility separately. Avoid leaking private compiler warning options
into installed consumers. Test an external consumer of the installed package after
moving it, without a build-tree package registry. A static library still requires
compatible compiler/runtime choices; its presence alone is not a stable binary API.

## Build and supply chain

One configured build graph owns common libraries and every selected frontend.
Focused test targets build the necessary executables before running them. Never
count a stale binary or a `ctest` selection that matched zero tests as evidence.
Configuration identity includes compiler bytes, language/runtime choices, SDK,
dependencies, sanitizer mode and frontend selection. An incompatible change needs
a fresh tree; a cache is not a toolchain migration mechanism.

Separate build-host tools from the target sysroot and released runtime baseline.
A newer compiler can run on an older baseline when built and audited appropriately.
A newer build host cannot gain an older runtime simply by declaring an ABI ceiling.
Reject ambient include/library search overrides in isolated SDK builds. Use a
generic CPU instruction floor, never the current runner's optional instructions.
Every application and retained library contributes to runtime compatibility.

Normal builds consume prepared inputs and do not fetch, install or cold-build
large dependencies. Explicit base maintenance produces immutable recipe groups.
Retain exact source inputs, patches, build recipes, provenance, terms and checksums
beside the compiled SDK; each binary release copies the exact groups it used.
URLs and expiring CI artifacts are not recovery storage. Test recovery from a
surviving binary release with the original base unavailable. See [SDK](sdk.md),
[dependencies](dependencies.md), and [portability](portability.md).

For upgrades, inspect upstream release notes, tool requirements, API/ABI changes,
build defaults, terms and transitive inputs. Reapply and test local patches against
exact expected bytes; context drift requires review, not approximate application.
Rebuild affected consumers, exercise old supported targets and refresh manifests
only after reviewing the intended differences. Retain a reversible previous recipe.

## Verification without excessive iteration cost

During diagnosis, run the smallest case that distinguishes the suspected cause.
Apply the [manual-qualification policy](../AGENTS.md#development-checks-and-manual-qualification)
to extensive checks: defer them until implementation is stable and execution is
explicitly authorized, except for explicitly requested earlier diagnostics. Required
platform, frontend, package and SDK gates remain mandatory before qualified binary
delivery; record applicable deferred scopes in [pending work](../.agent-pending/README.md).
Do not repeat unchanged expensive successes merely because another independent scope was
repaired. Evidence reuse requires identical relevant source, configuration,
dependency inventory, case inventory and environment; retain the original attempt.

Partition expensive suites by independent cases and aggregate their original raw
results. Every required case appears exactly once, including newly added cases.
Missing, duplicate, stale, skipped and failed results are rejected. Do not average
rounded summaries or weaken a combined acceptance gate to make splitting easier.
Parallel compilation, test processes and each test's workers share a CPU/memory
budget. Run timing-sensitive or exclusive-device scopes independently.

Successful checks near a computation allowance may warn. An exhausted allowance
is incomplete, not success. Real behavior/cancellation deadlines remain unchanged
under instrumentation. Any permitted environmental exception needs an exact typed
classifier, narrow scope, retained evidence, owner, recheck condition and declared
release consequence; unrelated assertions stay mandatory. The supplied generic
release policy grants no incomplete-coverage exception. Do not copy a product's
particular tolerance into a new project's default policy without justification.

A setup failure means no affected assertions executed. Identify and repair the
verified prerequisite, preserve concise evidence, then rerun that scope. Bounded
infrastructure retries retain both attempts. Repeating an assertion until it happens
to pass cannot qualify a candidate. [Testing](testing.md) and [CI](ci.md) define the
local and hosted execution paths.

## Packaging, release and certification

Package consumers receive executables, private runtime libraries, data, command
help, notices, dependency provenance and complete inventories. Installation must
not rely on the developer's checkout, current working directory or loader overrides.
Test the actual final archive after relocation to a path containing spaces, in a
clean environment. Inspect every runtime dependency; library loading through
plugins or explicit runtime requests requires a separately declared inventory.
Keep host loaders, drivers and system services separate from redistributable files.

Build a release inventory before publication. Bind source bytes, each platform and
backend artifact, prepared dependency groups, package-manager metadata and notices.
Reject duplicate names, unknown targets, incomplete groups or mismatched recipes.
Assemble in a new directory and verify before making it visible. Never overwrite
released binaries, recipes or prior reports to repair a failure. A fix creates a
new release. Repackaging retains the old application-source and dependency identity
and records the new packaging-tool identity separately.

Certification tests exact delivered bytes, not a branch that may have moved. A
frozen policy names every required target/backend/environment/scope. The report
binds the inventory and source digests, check commands, actual results, attempts,
evidence and explicit omissions. A diagnostic result cannot promote a release.
Experiments remain ineligible for the ordinary stable channel. Publication and
promotion are separate mutations; verify the remote assets and final channel
pointer after either operation. [Certification](certification.md) supplies local
executable checks; the repository does not require or perform remote publication.

Package-manager channels wrap already verified binaries without rebuilding them.
Pin payload locations to immutable releases even when users follow a moving index.
Authenticate metadata with an independently trusted key, compare payload digests,
reject hidden install hooks, test install/update/removal, and detect rollback or
same-version replacement. Keep application variants in separate private trees so
they coexist. [Distribution](distribution.md) covers the concrete Debian channel
and the contracts for other native package managers.

## Documentation and maintenance

A newcomer must find prerequisites, one build entry point, test scopes, architecture,
extension points, public contracts, dependency suppliers, SDK reconstruction,
release steps, recovery and current qualification limits without reading a chat.
Procedures are runnable; placeholders are named explicitly. Requirements,
implementation, proposals and observed results are separate. Each claim of support
has evidence or a clearly named outstanding qualification requirement.

Record transient discoveries in ignored owned notes with evidence, revision,
environment, confidence, references/access dates, failed attempts and recheck
conditions. Promote durable facts into tracked contracts/tests. Do not retain
redundant task logs as required project documentation. Revisit temporary workarounds
when their condition changes; name who owns the upgrade/removal decision.

Review a completed diff for unwanted generated files, unrelated edits, accidental
secrets, environment-specific paths, temporary allowances, weakened assertions and
undocumented compatibility changes. Preserve useful failure evidence without
including confidential input. Backups and retention rules cover required source,
SDKs, releases and key material independently. Periodically rehearse restoration;
an inventory of filenames is not proof that the retained files can rebuild or run.
