# Architecture and repository map

Keep application decisions in a reusable library. Executables compose that
library with hosts; adapters translate capabilities and events. Build, test and
release tools belong outside the runtime dependency graph.

| Path | Responsibility and ownership rule |
| --- | --- |
| `src/` | Compiled implementation and thin CLI composition root; no public implementation details leak into consumers |
| `rust/text_validation/` | Default allocation-free text validator behind the private C ABI; portable logic stays independent of GUI toolkits |
| `include/foundation/` | Public, self-contained C++ interfaces; document ownership, bounds, failures and concurrency |
| `gui/` | Shared feature declarations and composition roots; generic external adapters stay in their pinned package |
| `tests/` | Independent contract checks, failure cases and tool tests; private fixtures live here with provenance |
| `examples/` | Small external consumer using installed public interfaces |
| `tools/` | Build, coordination, evidence and artifact helpers; explicit inputs, bounded effects and nonzero failure codes |
| `third_party/` | Supplier inventory, revision locks, upgrade and license records; cached downloads remain ignored |
| `cmake/` | Target-specific build policy, exported package configuration and toolchains |
| `build/` | Ignored, replaceable generated output; each configuration owns its own tree |
| `.github/` | Workflow definitions, review templates and dependency-update configuration |
| `docs/` | Indexed contracts, procedures, decisions, maintenance guidance and validation |
| `COMPILE`, `RELEASE` | Short operational entry points linking detailed procedures |
| `build.sh` | Thin POSIX entry into the cross-platform Python wrapper |
| `CMakeLists.txt`, `CMakePresets.json` | Authoritative target graph and shared supported presets |
| `AGENTS.md` | Required agent startup, ownership, scope and validation discipline |
| `.gitignore` | Explicit local caches, coordination board and generated outputs; no blanket hiding of source |
| `.gitattributes` | Predictable text endings and binary treatment; exact-byte exceptions stay narrowly scoped |
| `.editorconfig` | Basic editor consistency without requiring one editor |
| `.agent-work/` | Ignored shared temporary coordination and knowledge; never an authority over tracked requirements |
| `LICENSE` | Terms for this repository's own work; dependency terms remain separate |

## Executable paths

`foundation-cli` validates command shape in `src/main.cpp`, calls `Store::add`
for every argument, then obtains an owning snapshot and formats it. No records
are emitted until the complete input has passed validation. An invalid argument
cannot leave a partial successful-looking listing. Failures return nonzero;
usage errors are distinguished from runtime/input failures.

The browser-target SDK also builds a Node CLI and runs the same core and CLI
contracts through its retained Node executable. The small
[`src/platform/node_console.js`](../src/platform/node_console.js) adapter uses
synchronous writes so an output failure reaches the C++ stream error state.
The default asynchronous JavaScript console cannot provide that guarantee.

`Store::add` validates text, checks capacity and ID availability, creates an
owned record, and advances the ID only after insertion succeeds. `update`
validates first, finds by stable ID, prepares a replacement, then swaps it into
place. `erase` removes the selected ID while preserving other IDs. `get` and
`snapshot` return values, so callers cannot mutate internal storage. The class
requires caller-serialized access; it does not imply thread safety.

The private validator defaults to Rust through `src/text_validation.h`; its
borrowed-buffer contract and status translation preserve the public C++ API.
`--core-provider cpp` selects the equivalent legacy implementation. Every selected
frontend reaches the same provider through `Store`, so feature code is never
duplicated in backend adapters. See [the boundary and policy](rust-hybrid-plan.md).

`tests/store_test.cpp` checks failure atomicity, stable IDs, independent snapshots,
maximum length and every possible input byte. `tests/check_cli.py` checks actual
process exit status and complete output, including rejection after an earlier
valid argument. These tests retain their assertions in optimized builds.

The optional [GUI application](gui-boundary.md) owns state and event meaning once.
The host selects a generic adapter; layout and features remain shared. Boundary
contracts are tested without requiring every physical display on each edit.

## Build and delivery paths

`build.sh` resolves its own directory and forwards arguments unchanged to
`tools/build.py`. The wrapper selects one preset, validates configuration identity,
configures incrementally, builds declared prerequisites, and runs CTest or CPack.
CMake compiles `foundation_core` and one Rust archive per compatible
configuration, then links consumers to them. The
exported target carries the required language level and installed include path.
Private warnings do not become downstream consumer policy.

The prepared browser toolchain reapplies its retained compiler wrappers after
CMake loads the supplier's platform rules. Both direct CMake builds and the Python
entry point therefore use the frozen SDK cache. Configuration probes, application
targets and installed consumers use the same retained exception/assertion variant;
an unavailable cache variant is an error requiring explicit SDK maintenance.

`tests/check_install.py` installs into a temporary prefix, renames it to a path
with spaces, then builds an external consumer through `find_package`.
`tools/artifact.py` separately verifies the actual produced archive, rejects
unsafe entries, extracts into a new prefix and exercises its CLI and SDK export.
Neither test proves compatibility with an older operating system; that requires
the target environment and [portability gates](portability.md).

`tools/test_plan.py` freezes the complete configured test inventory, divides it
without overlap, checks source identity before/after execution, and merges only
complete passing shard reports. It never infers success from the existence of a
log file. [CI](ci.md) and [testing](testing.md) explain when to use it.

## Extension rules

Add features to the owning module and its contract first. Keep I/O, platform
services and UI toolkits behind explicit interfaces. Make public headers compile
independently. Avoid globally mutable state, toolkit types in core interfaces,
application names in adapters and dependencies added merely for convenience.
A new shared contract may require coordinated adapter implementation; update
all advertised capabilities and conformance tests together.

Favor composition and a few explicit targets. Do not manufacture plugin systems,
network services or persistence layers until a requirement justifies them.


## Source, dependency and qualification identity

`source_identity.py` inventories the complete retained source and executable modes.
The build graph writes that identity, target, GUI backend inventory and all dependency
recipe identities into `build-info.txt`. `release.py` compares those fields with
the archived source and retained groups before accepting an application archive.
A surviving release therefore supplies its own source and dependency inputs even
when its supplier or original base release disappears.

`coverage.py` runs frozen commands under process ownership and binds complete
receipts to source, release inventory and policy. `run_tests.py` exposes every
inner unit-test outcome; `release_check.py` exercises actual source, delivered
archives, rebuilt recovery inputs and installed consumers. `certify_release.py`
requires the complete target/backend/environment inventory before promotion
eligibility. `github_release.py` separately verifies remote bytes and the selected
certification before updating Latest. Distribution helpers wrap verified archives
without rebuilding application code.
