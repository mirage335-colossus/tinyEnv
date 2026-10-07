# Programming and maintenance practices

## Contracts and implementation

Choose the smallest clear module boundary that gives each behavior one owner.
Separate computation from I/O and platform access. Use types to represent valid
states, immutable snapshots at asynchronous boundaries, explicit ownership, scoped
resources and deterministic cleanup. State whether a function is reentrant or
thread safe; never infer safety from const qualification or a single passing test.

Validate sizes and ranges before allocation, arithmetic and indexing. Bound data
and metadata separately. Check overflow before conversions or multiplication.
Give failed operations a defined state guarantee. Use error messages that identify
the failed operation without dumping private inputs. Do not catch and ignore an
unexpected failure or silently replace a missing dependency with a different one.

Keep cancellation, completion and exhaustion separate. Cancellation must unwind
owned resources and stop future writes; a timed-out task is not completed work.
Use monotonic time for durations and actual state transitions for completion.
Workers should publish owned results carrying a generation or request identity;
consumers reject stale results after replacement or cancellation. Stop accepting
new work before shutdown, cancel/join outstanding work and release resources last.

Treat external input and generated artifacts as untrusted data. Escape at the
output boundary, use argument arrays for subprocesses, avoid executable string
construction, constrain extraction and file destinations, and prevent accidental
overwrite. Set resource quotas for bytes, item counts, time and concurrent work.
For networked or persistent features, add an explicit threat model, authentication,
versioning, migration and rollback plan before adding those capabilities.

## Testing and diagnosis

Reproduce a fault with the smallest meaningful case. Test independently specified
outputs, boundaries, malformed inputs, cancellation, stale events and failure
atomicity; round trips alone may hide coupled mistakes. Prefer fixed inputs and
injected clocks/services to sleeps and environmental assumptions. Check resource
cleanup and actual error statuses. Assertions in tests must remain enabled in
Release builds. Keep tests independent and use unique temporary paths.

Use compiler warnings, sanitizers and static analysis where applicable. Keep
instrumented timing separate from production timing, while retaining real product
deadlines. Profile before optimizing. Record setup, CPU, memory, concurrency,
compiler and dependency versions when comparing performance. A warning about
slower execution must not excuse failed correctness checks. Follow
[the testing progression](testing.md) rather than repeatedly running every suite.

## Dependencies and builds

Prefer standard facilities when sufficient. Review dependencies for maintenance,
license and distribution obligations, build portability and target support. Keep
upstream code separate from local patches. Never edit generated output as the
source of truth. Ensure optional features fail clearly when requested but unavailable.
No configure step should unexpectedly fetch or execute new remote code.

Use target-scoped include paths/options and explicit dependency edges. Keep public
compile requirements separate from local warning policy. Avoid workstation CPU
optimizations in distributable builds. A successful build on a newer workstation
does not establish support for an older runtime. Pin and verify delivery inputs;
use caches only as replaceable performance aids. See [dependencies](dependencies.md)
and [portability](portability.md).

## Review and ongoing care

Keep changes reviewable and explain the observable before/after behavior, test
evidence and material limits. Avoid unrelated formatting and speculative redesign.
Review callers when changing a callee's contract, not just its immediate test.
Check downstream install/SDK consumers when public headers or exports change.

Document the supported toolchain/OS window, deprecation policy and ownership.
Schedule dependency updates according to actual exposure and maintenance needs;
remove unused dependencies. Preserve source and notice archives needed for released
binaries. Never replace published artifacts to conceal a mistake; publish a new
version with clear upgrade and rollback guidance. Revisit operational assumptions
when compilers, runners, external APIs or dependency versions change.

Keep source control clean of generated output and transient coordination data.
Preserve other contributors' work, including untracked/staged files. Coordinate
Git index, commits, merges and release operations as shared resources. Read
[agent coordination](agent-coordination.md) before simultaneous editing.
