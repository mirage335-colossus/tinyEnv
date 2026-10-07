# Third-party dependencies and upgrades

A dependency must remain identifiable and maintainable after its original
integrator leaves. Keep a machine-readable inventory in
[`third_party/dependencies.json`](../third_party/dependencies.json) and concise
maintenance notes for each selected dependency. Preserve upstream license and
notice files with the source and all applicable binary distributions.

The default library and CLI combine the C++ standard library and platform/compiler
runtimes with the Rust `no_std` validation archive. They have no external
application crates or added third-party application runtime dependency. Rust
tools are build inputs supplied by Debian-family native development packages or
the matched retained extension; installed executables and C++ consumers need no
Rust toolchain. Optional
GUI integration consumes the complete source group retained in this checkout,
with its own toolchain, runtime, and redistribution requirements. An explicit
pinned checkout or source group can override the bundled input. Build/test tools are still
dependencies and must be identified in environment records. Keep three inventories
separate: tools needed to build, files shipped with the application, and tools
needed only for validation. A WebAssembly compiler and its Node executor belong
to build inputs; desktop browsers belong to validation hosts. Ordinary native
builds do not need either. Avoid adding a package manager, browser download,
container runtime or prepared SDK to the default build when distro tools suffice.

## Required record

Use [the dependency template](templates/dependency.md). At minimum record:

| Field | Required information |
| --- | --- |
| Supplier | Upstream project, canonical repository/homepage, release and issue locations |
| Identity | Human version, full resolved commit, source archive URL and SHA-256 |
| Acquisition | Vendored subset, submodule, system package, prepared bundle, or SDK; explicit preparation command |
| Scope | Files included/omitted, features enabled/disabled, direct and transitive dependencies |
| Licensing | SPDX identifier when known, exact license/notice paths, modifications, redistribution status |
| Changes | Ordered patches, rationale, upstream issue/commit, removal condition, patch digests |
| Build | Supported compiler/runtime/configuration, required host tools, offline recipe, install layout |
| Consumers | Targets and call sites using it, API/ownership/error assumptions, adapter boundary |
| Upgrade | Review steps, compatibility risks, affected tests, package/SDK requalification |
| Ownership | Responsible maintainer, last reviewed date, outstanding limitations and recheck trigger |

Resolve an annotated Git tag to its commit with `git rev-parse 'TAG^{commit}'`
in a verified upstream checkout. Record the resulting full commit rather than
only a mutable branch or tag name. A source archive digest identifies its bytes;
a commit identifies repository content. Retain both when available.

For distribution packages, record supplier/repository snapshot, package version,
architecture, source package, archive digest, and how license/source material is
retained. A list of package names alone is not enough to reproduce a release.
For system runtime prerequisites, state tested versions and compatibility limits
without pretending those files are vendored.

## Source and integration boundaries

Prefer the smallest maintainable dependency set. Do not copy a large upstream
tree when only a small documented subset is used, but retain all required source,
licenses, build metadata, and upgrade context. Document omissions so an upgrade
does not accidentally discard a new required file.

Keep third-party headers out of application public interfaces when a small
adapter can hide them. Do not leak toolkit classes, allocator assumptions, or
dependency-specific error types through a general application contract. Review
the callers and callees: changes in lifetime, callback timing, threading,
ownership, encoding, or error behavior can break a consumer even if it compiles.

Keep upstream code close to its original form. Prefer a versioned patch series
or isolated adapter over undocumented edits. Apply patches with exact context
and fail if the expected upstream content changed. Never silently skip a failed
patch or suppress all warnings globally to accept an upgrade.

Default configuration must not fetch the network. Provide an explicit
preparation step and pinned inputs, then support offline configuration/build.
Local caches must be ignored, durable enough for ordinary development, and
separate from tracked recipes. Do not rely on ephemeral `/tmp` aliases or
unidentified binaries recovered from an old application installation.

## Upgrade procedure

1. Identify current consumers and preserve the current lock/manifest and test
   results. Read upstream release notes, migration notes, and maintenance notices.
2. Select an exact maintained version or commit. Verify provenance and archive
   digests through the established trust process; review new transitive inputs.
3. Compare the included source subset, licenses, options, public interfaces,
   generated files, minimum tools, and runtime requirements.
4. Reapply or retire each local patch deliberately. Record upstream fixes and
   retain a regression for each behavior the application depends on.
5. Trace every affected call path through the adapter and its callers. Update
   ownership, lifetime, error, concurrency, and resource handling as required.
6. Run focused integration tests, then the applicable normal regression matrix,
   installation checks, SDK qualification, and exact-package compatibility tests.
7. Update the machine inventory, maintenance note, notices, recipe identities,
   source archives, and build/release documentation in the same change.
8. Preserve the previous prepared inputs for supported releases and publish new
   immutable recipe assets. Document rollback to the prior complete set.

A dependency upgrade can raise the runtime baseline even when application code
is unchanged. Reaudit every delivered runtime file. A warning-free compilation
does not prove that all downstream assumptions still hold.

## Licensing and redistribution

Record the actual upstream terms; do not infer a license from a public repository,
a familiar project name, or a dependency's dependency. If required terms are
absent or unresolved, mark redistribution blocked and omit the affected binary
from distributable output until resolved. Local technical evaluation does not
establish redistribution permission.

Retain source and modifications where the applicable terms require them; satisfy
required notices, attribution, and relinking/source obligations for the actual
linkage used. An SDK includes host tools and target libraries that may have
different obligations. Keep private credentials out of sources, archives, and
build logs. Document a contact and process for reported dependency defects.

The inventory must distinguish shipped dependencies from development tools,
optional integrations, and proposed dependencies. Do not fill an empty field
with an invented license, supplier, tested platform, or digest merely to satisfy
a checklist.

## Durable recovery

Keep exact source inputs, patches, recipes, and binary archive digests together.
An upstream URL may disappear. Every binary release MUST retain exact copies
of its required prepared dependency binary/source/checksum groups. External
references are supplemental and cannot replace release-owned recovery inputs. Test reconstruction from the retained source inventory in
an empty, offline cache when qualifying a new SDK recipe. See [SDKs](sdk.md).

Temporary investigation findings belong in the ignored coordination notes with
source URL/date, dependency revision, affected environments, evidence, confidence,
and recheck condition. Promote durable verified findings into this inventory,
maintenance documentation, and regression tests. Community workarounds remain
hypotheses until validated against the pinned dependency and current callers.


## Bootstrap without recurring supplier access

The supported independence boundary is explicit:

| Build | Inputs retained before disconnecting |
| --- | --- |
| Debian-family native `dev` core/CLI | This checkout and distribution build packages including package-owned `rustc`/Cargo and complete notices |
| Debian-family native `dev` GUI | This checkout (including `third_party/gui-inputs`), Rust prerequisites above, and selected distribution toolkit/development packages |
| Linux release/portable/ASan or controlled compiler/target sysroot | Checkout, matching retained Rust extension, selected C++ SDK group where required, and declared distribution host prerequisites |
| Browser/Wasm | Checkout, complete matched Emscripten/Node and Rust SDK groups, and declared distribution host prerequisites |
| Native Windows | Checkout, complete matching dependency and Rust groups, local host tools and complete Microsoft compiler/Windows SDK installer layout |

Explicit `--core-provider cpp` preserves the original build closure without Rust
inputs. The Rust default never substitutes that provider when inputs are missing.

“Complete group” includes binary, source/bootstrap inputs and checksum inventory;
it is kept outside Git in durable local storage. A release URL or recipe alone
is not an offline input. Regular builds reuse installed verified SDKs; cold SDK
reconstruction and complete source-group recovery are separate maintenance checks.
Do not add either operation to every edit/build/test cycle. Existing compilation
parallelism, focused tests and certification gates remain unchanged.

The GUI group preserves upstream's Rev sources, GLEW/FreeType archives, fonts and
notices. It includes the FLTK adapter; the FLTK library itself comes from the
distribution FLTK package, or the complete prepared SDK for that target.
Rev needs newer compiler/CMake support than stock Debian 12 supplies; use suitable
distribution packages or the prepared SDK. See [GUI inputs](gui-boundary.md#complete-offline-gui-input-group)
and [SDK recovery](sdk.md#replay-without-supplier-acquisition).

Debian 12 supplies the default C++20 compiler, CMake, Ninja, Python, Rust 1.63 and Cargo through its
normal package repositories. Native SDK preparation also uses the explicit
`bootstrap_packages` list in its pinned recipe. Capture installed package
versions and retain a supported installation image or permitted package cache
when a machine must be recoverable without network access. The compiled SDK does
not replace the host operating system, its loader or every bootstrap package.

Windows host setup uses the selected v143 compiler and pinned Windows SDK from a
complete local Microsoft installer layout. No paid IDE feature is required for
this example; follow the edition's applicable terms. Prepared Windows dependency
bases contain only the selected reusable third-party inputs, including an empty
base when none are needed. A recipe must not fetch unused libraries to justify
the existence of a dependency bundle.

Initial acquisition and reviewed upgrades may need supplier access. Ordinary
builds consume verified retained inputs, and every binary release keeps exact
binary/source/checksum copies. Test the recovery path with networking disabled;
a URL list and an expiring CI cache do not establish disconnected recovery.
