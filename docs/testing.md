# Test selection, completeness, and execution cost

Use the least expensive check that can answer the current development question,
then follow the [manual-qualification trigger](../AGENTS.md#development-checks-and-manual-qualification)
for costly broader checks; readiness alone does not authorize execution. A focused
pass proves only its named scope. A test plan must identify what is required
for the change and what remains outstanding.

See [development speed](development-speed.md) for targeted prerequisites, independent
compile/test concurrency and scope-specific release inputs.

## Select the applicable stage

These are available stages, not a mandatory sequence for every change. Defer
applicable extensive stages to [pending work](../.agent-pending/README.md) until authorized.

```sh
./build.sh test dev --label core
./build.sh test dev --full
./build.sh test asan --rust-sdk /absolute/path/to/rust-sdk
./build.sh package release --rust-sdk /absolute/path/to/rust-sdk
```

These commands use the Rust default and the prerequisites documented in
[building](building.md#rust-default-and-provider-selection). Debian-family
native `dev` commands can use installed package-owned Rust tools. Choose the first label for the actual change: `core`, `tools`, `integration`, or
`gui`. `fast` is the inexpensive cross-cutting selection. These labels can
overlap; running several overlapping labels is not additional independent
coverage. The dependency-free GUI input and visual-comparison fixtures also belong
to `tools`, so ordinary native candidate jobs exercise them before any GUI SDK
preparation. Their `gui;focused` labels preserve targeted GUI selection; each
suite is registered once and records every case through the common test runner.
The wrapper rebuilds test prerequisites. Direct `ctest` alone does
not compile modified source. For a narrower iteration, repeat exact names:

```sh
./build.sh test dev --test core.store --test core.cli
./build.sh test dev --gui --test foundation.gui.task-native --test foundation.gui.file-content
```

An unknown name or empty selection fails. Fixture setup and cleanup tests join
the selected inventory, and compilation uses their complete prerequisite union.
Script-only selections do not compile the default target. Exact names and labels
are alternative selectors; focused success does not replace the candidate scope.

During diagnosis, `./build.sh test dev --label core --stop-on-failure` stops
CTest from scheduling further cases after its first failure. The same option works
with `test asan`. Already running cases may still finish when tests run in parallel.
The command remains failed; unexecuted cases are incomplete coverage. Without the
option, all selected cases run as before. After the fix, rerun the required complete
scope without this option; it does not alter candidate or release qualification.

| Change | First useful evidence | Candidate checks |
| --- | --- | --- |
| Library behavior or public contract | Reproducer and affected core tests | Full local suite; supported platform and sanitizer scopes |
| CLI parsing or output | CLI integration cases | Core and CLI regression; packaged executable checks |
| Build/helper logic | Small offline fixtures | Clean and incremental builds; install consumer; package checks |
| SDK/dependency recipe | Recipe/manifest fixtures | SDK host and target qualification; affected application matrix |
| Shared GUI behavior | Shared application and boundary tests | Every enabled adapter's contract, interaction, and layout checks |
| Backend adapter | Adapter conformance cases | Shared contract plus affected native backend execution |
| Documentation only | Links, commands, consistency | No unrelated expensive runtime matrix unless still outstanding |

During diagnosis, preserve a failing reproducer, fix the cause, and repeat that
scope. Do not continually rebuild SDKs or rerun every platform while the same
fault is unresolved. Run broader applicable final gates once implementation is
stable and their extensive execution is authorized; otherwise record pending work.
Reuse evidence only for unchanged source, configuration, dependency identity,
test inventory, and relevant environment. Record reused results explicitly.

<a id="optional-rust-provider-checks"></a>

## Rust Provider Checks

The private text-validation tests are available in both provider configurations.
`core.text_validation` checks provider identity, byte and length boundaries,
null/overlong inputs and unchanged caller buffers through the actual C++ caller.
`core.text_status` verifies unknown provider statuses fail closed.
`core.store` checks exact errors, validation precedence and state preservation;
`core.cli` checks observable executable behavior. Rust unit tests supplement
these foreign-caller checks rather than replacing them.

```sh
./build.sh test dev --core-provider cpp --build-dir build/check-cpp --label core
./build.sh test dev --rust-sdk /absolute/path/to/rust-sdk \
  --build-dir build/check-rust --label core
./build.sh test dev --rust-sdk /absolute/path/to/rust-sdk \
  --build-dir build/check-rust --test rust.unit
```

`rust.unit` is registered only for an executable exact-host native Rust target.
A Wasm or foreign-target tree does not claim Rust unit execution by omitting
that test. Its C++ contract tests still require the declared target executor.
The installed-consumer check must relocate the package and consume
`foundation::core` with Rust tools absent, carrying the installed archive's
transitive native requirements. The consumer calls the linked provider marker
and requires it to match the installed `Foundation_CORE_PROVIDER` export before
exercising the C++ Store API. This verifies actual Rust execution and mixed
C++/Rust linkage for Rust packages; explicit C++ packages require the C++ marker.
Historical exports without provider metadata retain their original consumer
check. Unknown declared providers fail configuration. Check default Rust selection and clear failure
when its required tools/extension are absent. Also check an explicitly selected
legacy C++ build with Rust tools
and caches absent; its configuration must make zero Rust discovery or acquisition
attempts.

The SDK-free Rust development check is Debian-family native only. Exercise its
actual package-owned tools, library-link/target identities, complete notices and
native link requirements; then change the selected compiler and require stale
identity rejection. This is separate from restoring an official Rust extension.
GUI-labelled CTests include tooling suites: report `foundation.gui.*` application
tests separately from tooling cases when describing frontend execution.

Build-helper coverage must distinguish frozen/offline inputs, hostile Cargo/Rust
configuration, invalid SDK pairing, changed tools/target libraries/notices,
archive/receipt tampering, missing-output rebuilds, incremental reuse and separate
Debug/Release outputs. Selecting a missing retained Rust SDK must fail even when
unrelated Rust tools are available. Shared GUI tests run against the selected
core, with every applicable frontend remaining in its normal backend inventory.
Provider, compiler, SDK/group and source identities must survive CI receipts,
source replay and package recovery; a C++ result cannot certify Rust bytes.

Stable Rust 1.63 code is not instrumented by the existing C++ `asan` preset.
Mixed ASan success establishes the exercised C++ and boundary scope; it is not
Rust-internal sanitizer coverage. No nightly toolchain is acquired for an ordinary
test. Native ARM64/Windows and full browser application execution remain their
own qualification scopes. A successful primitive Wasm ABI probe establishes
only its exact compiler/SDK/settings/cases. Offline toolchain restoration and
source-input recovery likewise do not certify a compiler rebuilt from source.
Use [platform limits](portability.md#rust-provider-boundary) and
[the implementation record](rust-hybrid-plan.md) for actual outcomes.

## Test design

Assert public behavior and invariants. Use independent expected values,
boundary cases, invalid inputs, ownership/lifetime checks, cancellation, and
failure cleanup. A test that repeats the implementation cannot establish its
correctness. Keep pure library tests independent of the desktop, network,
clock, and installed application when those services are not under test.

Use unique temporary output directories and deterministic inputs. A test must
not overwrite another test's files, use a fixed shared port without coordination,
or depend on execution order. Always clean up owned resources, while retaining
diagnostics on failure. Set individual timeouts and test process exit status as
well as output. Test assertions must remain active in optimized builds. Visual
qualification rejects an interpreter started with assertions disabled; setting
Python optimization flags must never turn a failed comparison into a pass.

Firefox automation allows up to 120 seconds for its initial connection because
fresh native ARM startup can exceed twenty seconds. This bounded prerequisite
margin preserves the fifteen-second protocol/application waits, early process
exit detection, required browser assertions and descendant cleanup. Chromium's
startup bound is unchanged. Clock-driven regressions cover delayed readiness
and deadline expiry; real native browser qualification remains required.

Tests shipped in a source archive must run without the original checkout or its
Git metadata. A fixture that exercises Git identity must create and commit its own
temporary repository; keep the production identity check real. Route CI output
files and other inherited output channels into the fixture's owned directory.
When repairing an archive-only failure, run the affected complete suite from a
fresh extraction outside any parent checkout and without `.git` before repeating
an expensive release workflow.
Never add fabricated repository metadata to a delivered archive or exclude a
required case to conceal the failure.

Keep contract regressions when refactoring. Modify an assertion only when the
intended public contract changes and the change is reviewed. Document numerical
tolerances and environment assumptions where relevant. Do not loosen a
correctness requirement merely to obtain a faster or green CI run.

## Inventory-driven parallel work

CTest's machine-readable inventory can support deterministic assignment:

```sh
ctest --test-dir build/dev-rust --show-only=json-v1
ctest --test-dir build/dev-rust --output-on-failure --no-tests=error \
  --output-junit build/dev-rust/results.xml --parallel 2
```

The project helper may wrap these operations; the underlying features are
documented in [CTest 3.24](https://cmake.org/cmake/help/v3.24/manual/ctest.1.html).
Before running a shard, record the complete inventory, selected names, source
revision, configuration, and shard rule. For a required distributed suite:

1. Every enabled required test belongs to exactly one shard for that scope.
2. Selection is deterministic and duplicate test names are rejected.
3. Every shard reports exact executed names and outcomes, not only a zero exit.
4. Aggregation rejects missing, duplicate, unexpected, skipped, or stale cases.
5. The union of shard results equals the expected inventory before success.

A newly added test must be assigned automatically to a documented default
scope or rejected as unassigned. An empty shard is either explicitly declared
valid in the plan or an error. A selector typo must not produce a green job.
Delete a prior run's result file before execution so it cannot satisfy a later
failed attempt.

The supplied [`tools/test_plan.py`](../tools/test_plan.py) freezes the test
inventory and source identity, runs disjoint selections, and rejects incomplete
aggregation. Every project test declares its compiled prerequisites through
[`cmake/TestPrerequisites.cmake`](../cmake/TestPrerequisites.cmake), including an
explicit empty declaration for script-only tests. Configuration rejects missing,
duplicate or unknown declarations. Planning freezes the complete generated
`test-prerequisites.json` and CTest declarations without compiling. Each shard
then incrementally builds only the union of its selected targets. A script-only
shard invokes no build command; it must never fall back to the default `all` target.
Legacy external CMake trees without this registry retain the complete prerequisite
build behavior. A registered tree with missing metadata fails. Plans bind the complete source snapshot, including configured GUI
sources, current compiler bytes and resolved path, normalized complete CMake cache,
build metadata, test definitions, and verified SDK/dependency/GUI input inventories.
Shards recheck these before rebuilding prerequisites, after compilation, and after
test execution; changed inputs invalidate the plan. Retained SDK CMake/CTest and
environment are used when configured. Direct native CMake trees remain supported;
prepared external groups require their verified wrapper metadata.
Prior result and aggregate files are removed before an attempt so a failed run
cannot leave an earlier successful receipt available for reuse. Completed records
are published atomically. This example runs two shards
sequentially so their use is safe in one owned local build tree:

```sh
cmake --preset release -DFOUNDATION_RUST_SDK_ROOT=/absolute/path/to/rust-sdk
python3 tools/test_plan.py plan --build build/release --shards 2 --output build/plan.json
python3 tools/test_plan.py run --build build/release --plan build/plan.json \
  --shard 0 --jobs 2 --output build/result-0.json
python3 tools/test_plan.py run --build build/release --plan build/plan.json \
  --shard 1 --jobs 2 --output build/result-1.json
python3 tools/test_plan.py merge --plan build/plan.json --output build/coverage.json \
  build/result-0.json build/result-1.json
```

For simultaneous execution, give each shard its own build tree or runner and
unique output. Match the frozen source/configuration and planned inventory.
Do not launch multiple CTest writers against one tree's `Testing/` directory.
Distributed production plans can add weighted assignment based on recorded
durations while preserving the same input and completeness checks.

For tests divided internally across workers, retain every required case and
input identifier. Aggregate original raw results before applying any combined
acceptance criterion. Averaging independently rounded shard summaries can change
the decision. Validate missing/duplicate inputs and preserve the original
per-case and combined gates. Test partition planning with tiny fixtures before
running the expensive work.

## Resource management

Build concurrency, concurrent test processes, and each test's internal workers
multiply. Budget CPU and memory across all three. Use CTest `PROCESSORS`,
`RUN_SERIAL`, `RESOURCE_LOCK`, or resource groups when appropriate; these are
local scheduler controls, not cross-machine locks. A long serial test can run
on its own CI runner while independent suites execute elsewhere.

Separate package production from expensive regression work so copied-package
checks can start as soon as the archive exists. All required outcomes must
still reach the final gate. Prefer modest repeated compilation to transferring
configured build trees whose absolute paths and toolchain state are not
portable. Measure total runner minutes as well as elapsed critical-path time.

Do not run timing-sensitive checks under simultaneous heavy builds unless that
contention is the condition being tested. Instrumented execution and software
GUI rendering can be much slower. Keep real behavioral deadlines separate from
the outer computation allowance. Adjust an outer allowance only with evidence;
retain all correctness and cancellation assertions.

## Result vocabulary and failure handling

Use `passed`, `failed`, `skipped`, `incomplete`, and `not_run` distinctly. A
cancelled job, unavailable target, omitted sanitizer scope, exhausted work
allowance, or external timeout is never a pass. A successful near-timeout case
can emit a timing warning. A progressing but unfinished case is incomplete.
This example's required gates fail if mandatory coverage is incomplete.

Local `test_plan.py run` compiles selected prerequisites with automatic CPU/RAM
capacity. Planning needs no compile in a registered tree; legacy external trees
still build the complete prerequisite target.
Use `--build-jobs N` for an explicit compile limit; an explicit legacy `--jobs N`
continues to set compile/test concurrency. Automatic test execution uses the
CPU/RAM policy, or an explicit `CTEST_PARALLEL_LEVEL`. Concurrent parents divide
their inherited worker allowance before starting children; configured resource
locks and complete case inventories remain required.
Both `run` and `candidate-run` accept `--summary PATH`.

Candidate scope receipts retain each case's measured JUnit duration and declared
CTest timeout, plus prerequisite-build, test and complete-scope wall times.
`candidate-run --summary PATH` appends the five longest cases to the job summary.
The hosted candidate uses this for its existing GitHub summary file. Passed cases
using at least 80% of their declared timeout produce a margin warning; failed
and incomplete cases retain their failure outcome. Missing JUnit durations are
reported as unknown. Aggregation rechecks case timings against the exact retained
JUnit and frozen timeout inventory. Per-test durations may overlap under CTest
parallelism, so their sum is not elapsed wall time.

If a product permits a narrow environmental exception, define a typed error
classifier, exact affected scope, evidence, owner, expiry/recheck condition,
and release consequence in advance. Preserve unrelated mandatory checks. Do
not accept all crashes, all graphics errors, or any timeout under one label.
Reports must enumerate omitted coverage even when the enclosing workflow is
allowed to finish successfully under its documented policy.

On failure, retain console logs, selected inventory, machine-readable outcomes,
configuration, and timing. Run the focused reproducer while fixing the failure,
then rerun the affected complete gate. Retry infrastructure failures only with
a bounded policy and keep both attempts visible. Repeating until one attempt
passes is not a substitute for investigating a flaky assertion.

## AI-agent requirements

Agents must state the affected scope, use the smallest meaningful checks during
editing, and apply the manual-qualification trigger at the candidate checkpoint.
They must not claim full validation from `devfast`, a subset, an old build tree, or another
revision. Recheck [coordination](agent-coordination.md) before launching shared
builds or long tests. Record process identity and owned output paths if a job
outlives a tool response; do not launch duplicate work because the tool yielded.

For each completed change, report commands, actual pass/failure status, omitted
coverage, and remaining external qualification. Use the
[validation template](templates/validation.md) for durable evidence and the
ignored coordination directory for transient investigation notes.

## Unit-case evidence and release attempts

CMake runs each Python suite through [`run_tests.py`](../tools/run_tests.py).
The helper registers the imported module so module and class fixtures execute
with normal unittest semantics, discovers its complete case inventory, records each outcome and exposes
narrow platform exclusions separately. Missing fixture privileges or tools are
incomplete coverage and return failure. Unittest's successful process exit after
an internal skip cannot become a complete passing receipt. Optimized C++ tests use
explicit checks rather than assertions removed by the compiler.

Whole Python suites remain the unit of parallel scheduling. Measurements of the
five slow suites on 2026-10-05 found single classes owning 92% and 97% of the
`github_release` and `gui_boundary` times; even the more balanced suites offered
only about three seconds of theoretical class-level savings in isolation.
Additional intra-suite process orchestration is deferred until timings justify
its fixture, aggregation and cleanup complexity.

For multi-environment release work use [the frozen coverage and certification
protocol](certification.md). Its immutable attempt directories and supervised
process trees add source/asset/policy identity to the local CTest shard mechanism.
Candidate execution configures one complete graph, then compiles the registered
prerequisites for its complete selected scope. Candidate `core` owns all tests
without a tools/integration label, including GUI tests. The local developer
`--label core` selects only core-labelled tests and their prerequisites; it does
not compile GUI hosts merely because GUI support is configured. Generated CTest commands
and configuration stay frozen across those independent trees even before other
executables exist. Ordinary shards use the same complete prerequisite registry. Neither local helper authorizes concurrent writes to a common build directory.


## Focused host diagnostics

The manual [Host contract diagnostics workflow](../.github/workflows/host-contracts.yml)
runs one complete `process_tree`, `windows_graphics`, `ci_plan`, `github_release`,
`ci_transport`, `latest_release`, `agent_board`, `test_plan`, `ci_retry`, `package_wasm` or `import_wasm` unit suite
directly on a Windows x64, Linux x64 or Linux ARM64 runner. The last four bind the
complete maintained source inventory before and after execution. On Windows they
select the installed native compiler and own a fresh private MSVC build session,
retaining its exact helper identity and joined-completion receipt. This permits
small configure/compile fixtures without rebuilding application GUI backends or
acquiring an SDK. The `agent_board` selection runs the complete compatibility-board
suite, including its eight independent writers, with the exact helper and runner
source bound before/after each diagnostic. It requires no compiler or GUI build.
The `latest_release` selection also binds the complete maintained source inventory
because its orchestration fixtures inspect workflow and helper files. It requires
no compiler setup, application build or SDK acquisition.
These diagnostic receipts never qualify a release.

The opt-in `windows_hosts` suite requires Windows and exercises the actual
installed MSVC compiler and Firefox. It compiles the same native probe with the
same arguments and process owner as graphics qualification. It also runs two
simultaneous compiler clients with distinct private PDB-service endpoints, requires
distinct server processes, and pins the control server's exact handle. Completing
the first owner must leave that same control server alive through another compile;
a replacement server cannot satisfy the check. Both owners must then join their
services and immediately release their output directories. The suite separately opens
an automation session, checks a simple page and verifies immediate profile removal
after browser shutdown. It acquires no SDK or graphics driver and does not execute
the graphics probe. These cases live outside ordinary unit-test discovery and
CMake coverage; ordinary unit tests must not require installed browsers or MSVC.
Select `runner-default`, Python `3.12` or `3.14`, and 1, 5 or 20 repetitions. Explicit versions resolve only the highest complete stable patch in
`RUNNER_TOOL_CACHE`; an unavailable or mismatched native interpreter fails without
downloading Python. The default uses the workflow shell's existing interpreter.

[`host_contracts.py`](../tools/host_contracts.py) records the selected executable,
its SHA256, reported Python version and architecture, runner image, source hashes
and exact workflow revision. Every repetition retains the complete `run_tests.py`
case inventory and console log. A failure stays failed even when later repetitions
pass; missing inventories, internal skips, timeouts and incomplete repetitions
cannot pass. Each suite has a 120-second execution limit and the complete run has
a 50-minute limit. Cleanup must stop and join supervised writers before another
repetition starts; uncertain cleanup stops the run and permits retention only of
the failed summary, never potentially active child logs or inventories.

Give each process tree the same lifetime as the resources it can write. An outer
test-runner supervisor cannot protect an inner temporary profile that the test
deletes before it exits. Browser and driver wrappers must stop and join their own
descendants before closing logs, copying evidence or removing temporary files.
If that join is uncertain, preserve the workspace and fail the check. Test the
case where a child keeps writing after its primary process has exited; waiting for
the primary alone does not establish cleanup.

On Windows, the process supervisor pins descendant identities and waits for their
handles to become signaled after Job Object termination, under the same bounded
deadline as parent cleanup. An empty active-process count alone cannot establish
that child output handles have closed. Membership changes, inaccessible identities
and cleanup failures remain failures. The native regression observes the exact
child handle and immediately renames and removes its output after cleanup; it does
not hide uncertain shutdown behind a delay or deletion retry. When a command
exits with a live Windows descendant, the failure retains the first verified
member identity, process image or query error, wait state and bounded membership
counts. Later process exit cannot erase that observation. Diagnose the observed
helper before changing compiler options; an unrelated telemetry switch or a
passing retry does not establish the cause. The native compiler has an explicit
[exact-helper completion policy](windows-graphics.md#bounded-test-environment) for
its identified optional telemetry child. This verifies every live member and
terminates and joins it before reading output; it does not relax ordinary command
completion or accept unclassified descendants. Compiler-capable build operations
use the separate [private MSVC build-service owner](building.md#msvc-build-service-ownership),
which additionally isolates and joins the selected PDB server. Both policies keep
unknown members and uncertain cleanup as failures.

Source-test candidates and shards own their prerequisite builds and entire CTest
regions because tests can compile fixtures. A joined nonzero CTest exit still
produces the ordinary failed JUnit/result evidence. Ownership failures and timeouts
propagate before report processing; a partial test file cannot establish safe
completion. Keep these outcomes distinct when adapting the test runner.

The workflow always attempts to retain `result.json` and each repetition's logs
and inventory through the existing lifecycle `bundle-store`, using the run-scoped
`host-contracts-ATTEMPT` bundle. It needs repository contents write permission only
for that retained evidence transport; the test step receives no token. Failed runs
can be inspected with the [same exact bundle recovery](github-delivery.md) as other
lifecycle evidence. No Actions artifact storage or prepared SDK build is required.
These diagnostic receipts never satisfy source, package or release qualification;
repeat the required complete gate after a diagnostic correction.
