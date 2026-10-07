# Prepared SDKs and target sysroots

An SDK is a versioned developer input: host tools plus a controlled target
environment. Its host requirements describe where the tools run. Its target
requirements describe where the generated application runs. Keep these
contracts separate in metadata, documentation, and tests.

The default example combines the selected native C++ tools with Rust. This repository also implements
pinned native source SDK preparation, WebAssembly build SDK preparation, Windows
dependency bases, immutable local base storage, strict installation and complete
release recovery. These are executable maintenance facilities. Compiled SDK
archives are generated outputs, not committed inputs. A runnable producer does
not establish that every host or target is qualified; record actual cold-build
and oldest-runtime results separately.

Ordinary Debian-family native `dev` Rust builds need only the checkout and
distribution packages, including package-owned `rustc`/Cargo and selected
toolkit development packages. Other Rust profiles require their verified
retained extension. Explicit C++ builds need no Rust inputs. `--gui` restores the
checked-in source group; it does not prepare an SDK. Wasm and Windows use
the checkout plus retained complete C++ and Rust SDK/dependency groups and their
declared host prerequisites.
Keep these groups outside Git. See the [independence boundary](dependencies.md#bootstrap-without-recurring-supplier-access).

Use [offline application builds](offline-builds.md) for the complete retained-input
contract and disconnected Bookworm acceptance commands. That operation restores
an already prepared group; it does not reconstruct a compiler. Source URLs and
checksums describe provenance but do not replace retained archive contents.

## Ordinary SDK development qualification

The explicit `native-gui.yml` workflow accepts `development: true` on Linux.
It consumes the exact retained SDK recipe on its native architecture in Debian
Bookworm, then runs both `build dev --sdk` and `test dev --sdk --full` in one
build tree with all native GUI hosts and no `--portable` flag. It records these
checks separately in the qualification receipt and never produces an application
release. A failure in either command prevents a passed receipt. This opt-in check
adds no work to ordinary builds or automatic development feedback.

An empty `gui_input` in this workflow explicitly uses the verified source group
from the selected checkout. A supplied remote selector must succeed on its own;
there is no fallback to different bytes. Windows GUI qualification continues to
use its retained graphics prerequisite and Release configuration. Existing SDK
recipes can qualify new consumer code without relabeling or rebuilding their bytes;
SDK producer changes require their own new maintenance and publication evidence.

## SDK versus installed developer package

The installed `Foundation` CMake package contains the application library,
headers, and exported usage requirements. It is consumed with an existing
compiler. A target SDK additionally supplies or identifies compilers, binary
utilities, target headers/libraries, build-tool prerequisites, licenses, and
its compatibility baseline. Neither is an application runtime prerequisite.

```sh
./build.sh build dev --sdk /absolute/path/to/prepared-sdk --rust-sdk /absolute/path/to/rust-sdk --jobs 2
./build.sh test dev --sdk /absolute/path/to/prepared-sdk --rust-sdk /absolute/path/to/rust-sdk --jobs 2
./build.sh package release --sdk /absolute/path/to/prepared-sdk --rust-sdk /absolute/path/to/rust-sdk --jobs 2
```

These commands require a valid prepared SDK matching the toolchain file's
metadata contract. A foreign target requires a suitable test executor or native
test machine; do not run its executables on the build host by assumption.
Ordinary native SDK development executables now use the private static GNU
language runtime and an audited per-executable `.sdk-runtime/TARGET` closure.
Inherited `$ORIGIN` paths resolve transitive private libraries; the target libc
and loader remain host requirements and never enter that closure. Build-time
provider hashes remain bound to the configured SDK inventory. Selected executable
builds verify their existing private output even when no relink is needed; missing
closures are restaged, while changed or unowned output fails. Installation retains
its separate notice/provenance and portable-package audits. Current project
libraries are static; a future project-owned shared library needs explicit provider
registration rather than an arbitrary build-directory search.

Linux SDK builds link the exact private runtime path without CMake colon padding,
which would add the working directory to the loader search. After target install
rules, the install helper rewrites only executable copies recorded by that install
invocation to their intended installed path. Portable copies use
`$ORIGIN/../lib/runtime`; ordinary copies retain their configured install policy
and require their shared GUI providers on the destination system. Use
`portable-package` when those providers must travel with the application.
This does not rewrite build executables or add work to warm links. The helper
supports `CMAKE_INSTALL_BINDIR`, components, prefixes and `DESTDIR`; ambiguous
installed executable names, generated/metacharacter paths, and an installed path
longer than the linked path fail explicitly. Installed private-provider collection
and final ABI audits still run separately for portable packages.

The shared [`sdk_environment.py`](../tools/sdk_environment.py) policy rejects
ambient compiler/include/library/loader overrides before consuming an SDK, and
clears them during explicit SDK production. This includes `GCC_EXEC_PREFIX`,
`COMPILER_PATH`, `LD_PRELOAD`, `LD_LIBRARY_PATH` and `LD_AUDIT`. Ordinary builds
never repair or download an SDK. New producer recipes retain the shared helper;
previous retained groups keep their original identities and bytes.

The current consumer implementation and required fields are in
[`cmake/toolchains/sdk.cmake`](../cmake/toolchains/sdk.cmake).

The current manifest is `SDK_ROOT/sdk.json` with `schema_version: 1`, a nonempty
`recipe_id` containing a complete SHA-256, and a `target` object containing
`system: "Linux"` or `"Emscripten"`, `processor`,
`triple`, `sysroot`, and `cxx_compiler`. The last two are existing relative paths
whose resolved locations stay inside the SDK. The `files` object maps every
SDK file other than the root manifest to its SHA-256; the compiler must be
included. Native producer manifests also declare `target.c_compiler`, naming the
retained `<triple>-gcc` executable. The validator checks its containment and full
file inventory; CMake selects it again in nested compilation checks. Legacy
native manifests without this field support C++-only consumers; enabling C fails
instead of selecting a host compiler. Emscripten's retained rules explicitly select
its C and C++ wrappers. The wrapper verifies completeness and every digest before configuration
and retains the manifest digest in the build-tree identity.

Production manifests also carry host requirements, target runtime ceilings,
licenses, complete source-inventory identity, preparation kind, relocation policy
and separate host/target audit results. `sdk_verify.py --release` rejects missing
production evidence. Windows dependency bases deliberately name an external
Microsoft toolchain; they never claim to contain the compiler.

Review the supplier's complete installed shared-library inventory, including
optional facilities enabled by default and development aliases. Preserve static
linking inputs and developer debugging support. Source-proven private libc or
loader imports are accepted only in the exact declared SDK libc inventory, with
the matched provider, source/recipe identities, approved library locations,
byte-identical development aliases and runtime version checks. Arbitrary files
with private ABI requirements remain rejected, and application packages cannot
inherit this SDK allowance or bundle the target libc/loader.

<a id="optional-retained-rust-extension"></a>

## Retained Rust Extension

The C++ SDK remains `sdk.json`. Retained Rust builds use a separate
`rust-sdk.json` extension; it does not change the existing C++ manifest
or make Rust a prerequisite of explicitly selected C++ builds. Fresh
configurations default to Rust; missing matched inputs fail clearly. See
[provider selection](building.md#rust-default-and-provider-selection). All ordinary
Rust builds consume existing inputs without supplier access or SDK mutation.

The separate SDK-free development route is currently Debian-family native Linux
only: actual distribution tools, target libraries, native link requirements and
dpkg-backed notices are identified in the build receipt, not a `rust-sdk.json`.
Matched package-owned `libstd`/`libtest` links are verified together with their
ordinary targets and package versions. Retained extensions still reject target
library symlinks. Other Linux distributions or unowned tool layouts use the
retained route; see [provider selection](building.md#optional-rust-validation-provider).

[`rust_sdk.py`](../tools/rust_sdk.py) prepares exact official Rust 1.63.0 compiler,
Cargo, host/target library and source components from the recipes in
[`third_party/rust`](../third_party/rust). Recipes cover native GNU/Linux x86_64
and aarch64, native Windows x86_64 MSVC, and the exact Rust 1.63.0 / Emscripten
6.0.10 profile. Recipe availability is not platform qualification. Official
Rust distribution archives are an explicit supplier for this extension; a
distribution-package-only policy cannot be inferred from the existing C++ SDK.
No rustup installation or moving toolchain selection is used.

The source group also retains official Rust 1.62.0 stage0 `rustc`, Cargo and
native-host `std` archives dated 2022-06-30. Their exact hashes are checked against
the Rust 1.63 compiler source's `src/stage0.json`, retained in the group as
`bootstrap/stage0.json`. These are retained
bootstrap inputs, not the active Rust 1.63 application tools. Their presence
does not establish a complete source-build bootstrap closure or a rebuilt
compiler.

Only the explicit `fetch` action acquires missing recipe-pinned supplier bytes.
`prepare` is offline and requires all declared files to be retained already:

```sh
python3 tools/rust_sdk.py recipe-id --recipe third_party/rust/linux-x86_64.json
python3 tools/rust_sdk.py fetch --recipe third_party/rust/linux-x86_64.json \
  --inputs /owned/retained-rust-inputs
python3 tools/rust_sdk.py prepare --recipe third_party/rust/linux-x86_64.json \
  --inputs /owned/retained-rust-inputs --output /owned/new-rust-group
python3 tools/rust_sdk.py verify-group --group /owned/new-rust-group \
  --recipe EXACT_RECIPE_SHA256
python3 tools/rust_sdk.py restore --group /owned/new-rust-group \
  --recipe EXACT_RECIPE_SHA256 --output /owned/new-rust-sdk --execute
python3 tools/rust_sdk.py verify --root /owned/new-rust-sdk --execute
```

Use the complete recipe identity returned by `recipe-id` in place of
`EXACT_RECIPE_SHA256`. Preparation and restoration destinations must be new.
The identity binds the recipe and five retained producer helpers:
`rust_sdk.py`, `dependency_archive.py`, `sdk_environment.py`, `sdk_manifest.py`
and `verify_abi.py`.
The same offline lifecycle applies to the other recipes. Add
`--cpp-sdk /absolute/path/to/cpp-sdk` when pairing a retained C++ target SDK;
the supplied Emscripten recipe pins the exact C++ SDK recipe as well as version
6.0.10 and its retained supplier version-file text `6.0.10-git`. Another SDK at
the same nominal version is not interchangeable. `--execute` is a native host
tool probe, not a foreign-target execution claim.

The complete retained group is exactly
`rust-sdk-RECIPE-binary.tar.gz`, `rust-sdk-RECIPE-sources.tar.gz` and
`rust-sdk-RECIPE-SHA256SUMS`. The binary manifest binds the source inventory,
compiler/Cargo versions, compiler host, target triple and library directory,
licenses and every retained file digest. GNU/Linux and MSVC extensions must
match the selected C++ target ABI. Emscripten also binds the exact C++ SDK recipe
and Emscripten version. Missing or differing inputs fail instead of falling back
to tools on PATH. The component build independently rechecks the selected tools,
target libraries, notices and manifest before and after use.

The extension records `host_requirements` separately from application target
requirements. Linux host tools declare Debian 12/glibc 2.36 and ambient glibc
and `libgcc-s1` prerequisites. Preparation on Linux also records a `host_audit`
bound to retained executable/library bytes. This is static ELF/ABI inspection;
runtime dependency resolution is not checked by that audit. Native execution
probes and final application/runtime checks remain separate evidence. Windows
host requirements name system DLLs and the Microsoft MSVC v143/Windows SDK final
link prerequisites.

Keep three recovery results separate:

| Operation | Retained inputs and scope |
| --- | --- |
| Toolchain restoration | Restore the exact official compiler, Cargo and matched target-library binaries from the verified group, then probe on their declared native host |
| Source-input recovery | `restore-sources --group GROUP --recipe RECIPE --output NEW_DIRECTORY` recovers official compiler/Cargo source with vendored dependencies, library sources, supplier components, the exact stage0 archives and their source-metadata checksum binding, release metadata, recipe and helper bytes |
| Compiler reconstruction | A source compiler/Cargo build, complete bootstrap closure and executable rebuilt toolchain are **UNVERIFIED**; retaining sources, stage0 binaries or `bootstrap/stage0.json` does not establish this result |

`rust-src` also supplies retained library sources inside the binary extension for
inspection. The source inventory records the bounded recovery contract and
`bootstrap_reconstructed: false`; the binary inventory records
`compiler_reconstructed: false`. Keep these limits visible in release recovery
evidence. An offline application rebuild using restored official tools proves
application recovery only. Platform host/runtime/GUI qualification remains
separate in [the Rust implementation record](rust-hybrid-plan.md) and
[portability](portability.md#optional-rust-provider-boundary).

The [current Rust release record](validation.md#rust-all-gui-release-and-integrated-packages-2026-10-06)
and its [public inventory](https://github.com/mirage335-colossus/software-foundation/releases/download/release-37394012851-attempt-1/release.json)
identify the exact eight retained C++/Rust groups, cloud application/control
source, complete certificate and integrated native packages. This rebuild used
retained SDK binaries; it does not claim a new compiler build. Earlier SDK
publication and offline qualification retain their original execution revisions
in [the previous release record](validation.md#rust-enabled-portable-release-and-signed-channels-2026-10-05).
Supplier-package replay does not establish compiler reconstruction from source.

## Linux SDK filenames and destination filesystems

Native Linux producers explicitly declare `path_policy: "linux-case-sensitive-v1"`
in the binary `sdk.json`. This policy requires both `host.system` and
`target.system` to be `Linux`. Linux target headers can contain distinct names
such as `xt_CONNMARK.h` and `xt_connmark.h`; both are required inputs. Preserve
both names and their complete bytes. Never omit or rename a header to accommodate
a filesystem or archive validator.

An absent `path_policy` retains the strict portable default. Unknown values,
non-Linux host/target combinations, and Windows dependency bases cannot select
the Linux policy. Source inventories, source archives, release asset names,
Windows and WebAssembly SDKs, and ordinary archive operations retain portable
case-insensitive collision checks. These checks include implicit directories,
file-versus-directory conflicts, and excluded manifest entries. Retained supplier
source archives are ordinary byte blobs inside the portable source group; they
are not unpacked there.

The binary SDK verifier reads one bounded, exact root `sdk.json` before applying
the declared policy to every archive member and complete file hash. Metadata
ordering does not affect policy selection. Exact duplicate names, traversal,
links, special entries, privileged modes and files used as directories remain
invalid under both policies. Inspection of a retained binary group is read-only
and may run on any supported host; installing or exporting a Linux-policy tree
requires Linux and a filesystem that preserves distinct names.

Before copying supplier files or extracting an SDK, the implementation checks
each newly created destination directory with two exclusive case-distinct files.
It validates independent identities and bytes, then removes only verified owned
probe files. Payload copies also use exclusive creation. A filesystem that folds
these names is rejected before it can discard compiler inputs. If a probe entry
changes or cleanup becomes uncertain, the owned staging tree is preserved and
the reported path must be inspected before retrying; a failed attempt never
qualifies an installation. Do not relocate an SDK onto an unsupported mount.

Verification remains read-only: it checks current case lookup in every populated
directory and compares the complete exact-name inventory. Installation, binary
export and post-relocation resealing all use the same validated policy. A moved
SDK with recorded absolute locations must be reinstalled from its retained group;
changing a manifest field does not perform relocation. Paired-header regression
checks preserve both digests across deterministic export, byte-identical group
copy, installation, relocation and actual consumer compilation.

The policy and its helpers are producer recipe inputs. Introducing or changing
them creates new recipe identities for every recipe that retains those helpers;
old archives are never relabeled or treated as byte-equivalent. Filesystem fixture
success is separate from complete cold SDK preparation and target qualification.

## Recipe and archive identity

Track the recipe, not a large generated SDK tree. The recipe must identify every
direct and transitive source, bootstrap input, exact revision, source archive
digest, patch, configuration, and relevant build helper. Include host tools in
the inventory, including generators required only while preparing dependencies.
Content-address the recipe from normalized paths and complete input bytes.

Cross-host recipe identity requires identical checkout bytes, including line
endings. The project [attributes](../.gitattributes) pin owned text inputs,
including PowerShell helpers, to LF. Verify effective attributes and actual bytes
in existing worktrees before computing an identity or reusing a retained group;
a changed attribute does not rewrite an already checked-out file. Preserve exact
supplier bytes and retained source archives. Never normalize during hashing or
treat different recipe IDs as equivalent because only line endings differ.

Keep mutable build outcomes and qualification status in separate receipts bound
to the recipe and archive digests. They are not recipe inputs: recording a
successful cold build must not change the identity of the exact group it verified.

A recipe identifier is not an archive digest. Two cold builds of one recipe may
produce different bytes until reproducibility is demonstrated. Preserve the
actual archive SHA-256 alongside the recipe identifier. Never silently replace
different bytes published under an existing immutable recipe asset name.

Publish a matched group:

1. Compiled SDK archive for its host and target pair.
2. Complete source archive with recipe, helpers, patches, bootstrap inputs, and
   selected dependency downloads sufficient for an offline rebuild.
3. Checksum inventory for both archives, plus provenance and license inventory.

Keep prepared inputs in durable release storage or a maintained artifact store.
Actions caches and expiring workflow artifacts cannot be their only copy.
Every binary release MUST retain byte-for-byte copies of its exact required
SDK/dependency binary, source and checksum group. A pointer to a base, external
URL, workflow artifact or cache is never a substitute. `release.py assemble`
refuses missing groups, and `release.py recover` works using the release alone.

## Explicit preparation lifecycle

Separate fetch, build, export, install/relocate, verify, and publish operations.
Ordinary application configuration invokes none of them implicitly. Network
access belongs to explicit fetching; offline preparation fails on missing or
changed inputs. Reuse the exact verified prepared recipe during ordinary CI and
releases. A missing recipe requires explicit SDK maintenance.

Fetch into temporary files, verify expected digests, then publish atomically.
Bound retries and timeouts; retry a transient download failure without changing
the pinned source or silently substituting another version. Preserve the first
useful failure and final result. Never bless a downloaded digest as trusted
merely because it matches a checksum downloaded from the same untrusted source.

Validate archive entries before extraction: reject traversal, absolute output
paths, duplicate entries, unexpected special files, escaping links, and writes
through link parents. Install into a new owned staging directory; publish the
finished tree atomically. Preserve an existing valid installation if preparation
fails. Never recursively replace an unmanaged destination.

Relocation must be an explicit, verified operation for SDKs with embedded paths.
Record the installed root or otherwise verify relocatability. After moving an
SDK, rerun its relocation procedure and use a new application build tree.
Reject a changed SDK root or manifest digest in an existing tree.

## Isolate host tools from target dependencies

The toolchain must select its compiler and sysroot before CMake's `project()`
initializes languages. Set target system and processor explicitly. Search
programs in the host environment, while target headers, libraries, and package
metadata are restricted to the target root. Disable user/system CMake package
registries for isolated builds. Propagate required SDK variables into
`try_compile` projects and use toolchain-file-relative paths.

Reject conflicting `CC`, `CXX`, compiler options, and ambient include/library
search overrides. Configure `pkg-config` with the target sysroot and target
metadata directories; clear host metadata paths. Validate both lexical paths
and resolved links so a supposedly contained dependency cannot escape to the
host. A target library must never be taken from a host directory as fallback.
These distinctions follow the
[CMake toolchain model](https://cmake.org/cmake/help/v3.24/manual/cmake-toolchains.7.html).

Keep compile capability probes separate from executable probes. Cross builds
may compile a check that they cannot execute. Either provide a declared test
executor or record runtime checks as unavailable. Do not globally disable linker
checks to make a broken toolchain configure successfully.

## New tools with an older target runtime

Build target libraries against the selected older runtime headers and libraries,
even if the compiler itself is recent. A recent compiler may change default
language dialects, diagnostics, or linker behavior; supply the dependency's
documented dialect and narrowly justified compatibility fixes. Scope those
settings to the affected dependency, retain the patch, and verify its expected
upstream context before applying it.

Do not transplant the entire configuration from an unrelated newer dependency
version. Recheck licenses, source inventory, configure options, and upstream
maintenance status. Keep auxiliary host generators on the versions they require;
an older target library does not imply every host generator must use that same
source snapshot.

Audit SDK host tools as well as target libraries. A target ABI ceiling can pass
while the compiler, build system, or a compiler helper fails to start on the
advertised build host. If private host C++ runtime files are bundled, distinguish
them from target files and verify that each resolves its own dependencies after
relocation. Never classify every file outside the sysroot as a host file without
accounting for target compiler-support libraries stored elsewhere.

Sanitizer use requires matching target runtimes in the SDK. If absent, reject
instrumented SDK builds with an explanation; do not borrow host runtimes.
Test SDK-built developer executables too. They may require runtime staging even
before packaging, and build-tree search paths must not accidentally select a
target C runtime incompatible with the host loader.

## Qualification and maintenance

Qualify the actual installed archive, not the builder's pre-export directory:

- Verify every retained source and archive digest and the recipe identity.
- Run host tools on the oldest declared build host after relocation.
- Compile, link, and execute a representative C++20 consumer on the target.
- Inspect every shipped target binary's architecture and runtime requirements.
- Build the application offline; test its normal and installed forms.
- Build and test every enabled GUI backend and any dynamic loading paths.
- Restore from the source archive into an empty cache with networking disabled.

Record exact commands, observed results, and omitted scope using the
[validation template](templates/validation.md). Maintain separate fast fixture
tests for recipe identity, path containment, interrupted installation, changed
manifests, missing archives, and corruption. These checks can run on every
relevant change without rebuilding a compiler.

An upgrade creates a new recipe identity, archives, and qualification record.
Keep the previous group available for supported releases. Follow the dependency
[upgrade procedure](dependencies.md) and the application
[release procedure](releases.md) for downstream requalification.

## Native source producer and Bookworm bootstrap

[`third_party/sdk/recipe.json`](../third_party/sdk/recipe.json) pins Buildroot,
a maintained glibc 2.36 input and all direct digests. Buildroot pins the selected
transitive source inputs. The recipe selects GCC 15 and a glibc 2.36 target; its
host tools are built on Debian 12 Bookworm. `distro_sdk.py` rejects a different
production builder. Install the recipe's listed bootstrap packages once using
the ordinary Debian package manager. Preparation needs no retired distro mirror.

```sh
python3 tools/distro_sdk.py bootstrap
python3 tools/distro_sdk.py recipe-id
python3 tools/distro_sdk.py fetch --cache /owned/sdk-cache --jobs 2
python3 tools/distro_sdk.py verify-inputs --cache /owned/sdk-cache
python3 tools/distro_sdk.py build --cache /owned/sdk-cache --output /owned/sdk-group --jobs 2
```

`fetch` is the explicit network operation. `build` verifies all retained input
hashes, the retained dependency-resolution digest and complete resolved download
inventory, then disables every Buildroot download command. A missing input fails;
the producer never substitutes a moving upstream version. Use an OS network
restriction when demonstrating disconnected recovery, as disabled application
download commands alone do not establish network isolation.

A development sysroot is not a bootable operating-system image. Assembly omits
virtual runtime directories and the pinned skeleton's mount-table and resolver
aliases (`etc/mtab` and `etc/resolv.conf`). Validate both exact supplier link targets
before removing either; a changed target, redirected parent or unexpected regular
file is a maintenance decision, not permission to discard it. All other unresolved
or escaping aliases still fail materialization. Never resolve a target runtime
service through the build host's filesystem or relax general link validation to
make a supplier skeleton copy succeed.

The supplier's host root has a separate legacy alias, `usr -> .`, created by
Buildroot's `package/skeleton/skeleton.mk`. Native assembly validates that exact
link after compilation and legal-information collection, then omits it before
materialization. A replacement directory/file or any other link target fails with
an explicit `usr` diagnostic. Host tools already live directly under the host
root; the target's real `sysroot/usr` and normal library aliases remain compiler
inputs. This exception does not permit arbitrary ancestor cycles. It is confined
to the native producer and does not change other SDK producers or identities.

The compiler SDK also omits a reviewed, source-bound set of target OS programs
and conversion modules. Host tools, target headers and link libraries,
`fltk-config` and `sdl2-config` remain. New libc source identities require an
explicit inventory review. Omission records name every removed path and preserve
the supplier relocation entries for retained files.

The x86_64 recipe is the default. The native ARM64 recipe is
[`aarch64/recipe.json`](../third_party/sdk/aarch64/recipe.json); pass it with
`--recipe` to every producer command on a Debian 12 ARM64 host. It selects the
same maintained runtime and newer compiler, with a checked generic CPU override.
Its tools run on ARM64, and its outputs target ARM64. Neither recipe silently
executes foreign binaries or claims emulation as native qualification.

The source group includes the recipe, overlay, exact preparation helpers, selected
source downloads, resolution record, input inventory and available project license.
Restore it into a fresh tree and replay using those retained helpers, not a newer
checkout. `export-sources` can preserve the fetched inputs before a cold build:

```sh
python3 tools/distro_sdk.py export-sources --cache /owned/sdk-cache --output /owned/source-inputs
python3 /owned/restored/tools/distro_sdk.py build \
  --recipe /owned/restored/recipe/recipe.json --cache /owned/restored/cache \
  --output /owned/rebuilt-group --jobs 2
```

A cold compiler build is deliberately separate from routine application jobs.
The compiler's C++ language support does not imply a newer target libc. The
narrow libc dialect override is checked against the pinned upstream context.
Host CMake, Ninja, Python and pkg-config are explicitly selected; they cannot
disappear merely because the builder already has suitable tools.

## Immutable base, installation and reuse

A group contains exactly `sdk-<recipe>-binary.tar.gz`,
`sdk-<recipe>-sources.tar.gz` and `sdk-<recipe>-SHA256SUMS`. Both outer hashes and
both complete inner inventories are checked. Their internal recipe identities
and the binary's recorded source-inventory hash must agree. Full recipe IDs
include producing helper bytes; archive hashes identify actual output bytes.

```sh
python3 tools/dependency_store.py put --base /owned/base --group /owned/sdk-group --recipe <recipe>
python3 tools/dependency_store.py fetch --base /owned/base --recipe <recipe> --output /owned/fetched-group
python3 tools/sdk.py install --group /owned/fetched-group --recipe <recipe> --output /owned/installed-sdk
python3 tools/sdk.py verify /owned/installed-sdk --release
python3 tools/sdk.py smoke /owned/installed-sdk --work /owned/compiler-smoke
./build.sh test release --sdk /owned/installed-sdk --rust-sdk /owned/matched-rust-sdk --portable --full --jobs 2
```

`put` reuses identical bytes and rejects a conflicting immutable recipe. `fetch`
only copies an existing exact group: it cannot build, download or choose a newer
recipe. The local base format can be transported to a durable release store by
an explicitly authorized publisher. These tools never publish remotely.

Publishing a new verified group to GitHub `base` now retires older complete
groups in the same SDK family/host/target/profile, after readback succeeds.
This keeps base inventories short without replacing immutable asset names or
moving the base tag. Other profiles and application release copies remain intact.
Old base recipe hashes may therefore become unavailable: update configured recipe
selectors when replacing an SDK. See the precise [base lifecycle](github-delivery.md#dependency-base-lifecycle).

Application producer jobs use `fetch-sdk-binary`: the binary archive and complete
pair checksum are transferred, and all three immutable remote asset identities
and digests are reconciled before activation. The binary's recipe and complete
source-inventory binding are checked, then installation checks the complete frozen
checksum map. Supplier source bytes remain in `base`; release assembly fetches
and verifies the complete group once. SDK maintenance, relocation qualification,
archive publication and offline recovery retain the full binary/source checks.

Disposable container setup selects packages by action and qualification scope.
Runtime archive checks omit compiler/development headers; application and
source/recovery checks retain build tools for their full source/tool fixtures.
GUI consumers install the runtime X11, Wayland and OpenGL services; GUI SDK
producers also install development prerequisites. Every setup uses strict signed
APT indexes and bounded transient-fetch recovery through `tools/ci-apt.sh`.
A physical qualification batch bootstraps packages once into a private immutable
Docker image, then starts a fresh disposable container and builder account for
each case. Browser prerequisites and evidence are still bound per case. Case
package-manager mutations cannot reach later cases; the setup image is removed
after all child commands finish. Independent payload preparation, verified
transfers and evidence fetches use at most four workers, joined before validation
or cleanup. Text evidence transport uses deterministic fast compression; already
compressed SDK/application archives keep their original bytes.

Generated archives contain ordinary files only, with sorted entries, stable
modes, normalized owner/time metadata and a deterministic gzip header. Supplier
links must resolve inside their tree before materialization. Extraction rejects
links, traversal, duplicate/case-ambiguous entries, privileged modes, parent/file
collisions and excessive size before creating the final destination.

Installation refuses an existing destination. Buildroot relocation runs at the
new final root, records that root and the original archive digest, then rehashes
the installed tree. A moved installation must be reinstalled from the retained
archive. Compiler smoke compiles C++20 code, audits the generated ELF and executes
it in a clean environment. WebAssembly SDK smoke uses its retained Node executor.
Diagnostic fixtures can be installed with `--diagnostic`, but cannot satisfy
release-readiness validation.

## WebAssembly build SDK and separate browser validation

[`third_party/sdk/wasm.json`](../third_party/sdk/wasm.json) pins Emscripten, its
compiler bundle and Node by exact archive digests. This SDK builds WebAssembly
applications. Node runs compiler support code and command-line checks; it is not
a desktop browser and is not an end-user prerequisite for a browser application.
The SDK includes no Chromium, Firefox, browser profile, or browser installer.
Use ordinary distro browsers or separately installed no-cost browsers for GUI
validation, with their versions recorded in that validation environment. Do not
add browsers to a compiler recipe merely to run GUI tests. Preparation consumes retained
inputs, warms the declared C++ library/exception configuration, and verifies a
second compile using a frozen cache. Ordinary compiles fail when a new library
variant is needed; change and prepare the recipe deliberately.

Disconnected acceptance keeps `EM_CACHE` on the installed SDK's prepared cache
and sets `EM_FROZEN_CACHE=1`. An empty writable cache outside the SDK is not an
equivalent input: missing variants must fail rather than trigger preparation or
downloads during an application build.

```sh
python3 tools/sdk_wasm.py fetch --inputs /owned/browser-inputs
python3 tools/sdk_wasm.py recipe-id
python3 tools/sdk_wasm.py prepare --inputs /owned/browser-inputs --output /owned/browser-group
python3 tools/dependency_store.py put --base /owned/base --group /owned/browser-group --recipe <recipe>
python3 tools/sdk.py install --group /owned/browser-group --recipe <recipe> --output /owned/browser-sdk
python3 tools/sdk_wasm.py smoke --root /owned/browser-sdk --output /owned/browser-smoke
```

The source group retains the exact upstream source and precompiled compiler/Node
archives used. It supports disconnected replay from those inputs; it does not
claim to rebuild LLVM, Binaryen or Node from their native source. Python 3.10 or
newer remains a host prerequisite for this supplier version. The pinned prepared
launcher change adds Python's `-B` option, because the supplier's `-E` option
ignores environment-only bytecode controls. Original archives, producer code and
the changed entry-point inventory remain available in the group. A JavaScript executor check does not establish
browser layout, resource-loading, worker, accessibility or interaction coverage.
Those require the separate browser execution matrix.

## Windows dependency base and separately installed host tools

[`windows-toolchain.json`](../third_party/sdk/windows-toolchain.json) selects v143,
x64, static CRT and an explicit Windows SDK. `select-windows-toolchain.ps1`
inventories installed components, prefers the supported installed toolset, and
fails instead of silently switching to a newer ABI family. `ci_windows.ps1`
initializes that exact environment and reports its compiler/linker details.
Consumers inspect the selected native Microsoft linker file through the shared
[`windows_toolchain.py`](../tools/windows_toolchain.py) adapter. It checks the
selected toolset path, x64 executable identity, Microsoft version resource and
unchanged file bytes, then enforces the recorded minimum linker version. A help
command exit status is not a version probe. The ordinary Windows tools suite
exercises the actual native resource API before expensive SDK production.

[`windows-base.json`](../third_party/sdk/windows-base.json) pins the upstream
package-manager revision, target triplet, ports, Debug/Release variants, runtime
policy and disabled LTO. The default core needs no external libraries, so its
complete base can be produced without inventing a third-party dependency:

```powershell
./tools/ci_windows.ps1
python tools/sdk_windows.py recipe-id
python tools/sdk_windows.py empty-base --provenance producer.json --output prepared-group
```

`producer.json` contains the exact recipe fields plus `linker_version` and
`windows_sdk` observed from the selected installed tools. The SDK version must
match the pinned policy. Nonempty port recipes also require `tools_version` and
`installation_path` from that selection; the producer checks the actual active
linker before building. Initialize that environment before invoking the producer.

The same executable lifecycle handles empty and nonempty port selections:

```powershell
python tools/sdk_windows.py fetch --provenance producer.json --cache retained-inputs --jobs 2
python tools/sdk_windows.py verify-inputs --cache retained-inputs
python tools/sdk_windows.py build --provenance producer.json --cache retained-inputs --output prepared-group --jobs 2
```

`fetch` is the explicit network operation. For a nonempty recipe it resolves the
full pinned vcpkg commit, retains its Git source archive and bootstrap executable,
and collects the dependency/tool download cache through a complete maintenance
installation. This also reaches downloads requested during configuration or
compilation, including build tools omitted by `--only-downloads`. Its generated
triplet fixes the selected v143 tools, Windows SDK, static CRT/libraries, both
configurations and no LTO. The maintenance installation is discarded; its compiled
outputs are never reused as proof of the independent cold offline build. This
extra work belongs to preparing a new base, and is amortized by reusing that exact
base for ordinary application builds. The empty core recipe fetches no package
manager or external libraries.

`build` verifies every retained input and restores a fresh supplier tree. It
clears remote binary-cache settings and inherited overlays, disables new asset
downloads with `--no-downloads` and `clear;x-block-origin`, then creates a raw
export with transitive libraries and integration files. Required selected-port
notices and installed inventory records are checked before archive assembly.
A source group retains the complete cache, exact recipe, host policy and helpers;
restore with `sdk.py restore-sources` and run its retained `sdk_windows.py build`
using `--recipe-file restored/recipe/windows-base.json --cache restored/cache`.
Microsoft host tools still come from the separately retained installer layout.

Ordinary application consumers use the verified static export with manifest
installation and both build-time and install-time app-local deployment disabled.
Static libraries and a static CRT need no package-manager DLL-copy hook; runtime
packaging independently checks the delivered dependency closure. Disabling
manifest mode alone does not disable a retained integration script's post-build
commands. The supplier documents [app-local deployment separately from manifest installation](https://learn.microsoft.com/en-us/vcpkg/users/buildsystems/cmake-integration#vcpkg_applocal_deps).
Keep this distinction in the SDK consumer contract, and inspect the actual retained
scripts when upgrading a base.

The consumer also [disables package-manager metrics](https://learn.microsoft.com/en-us/vcpkg/users/config-environment#vcpkg_disable_metrics)
in its child environment, matching the explicit SDK-maintenance environment. This is not a network sandbox
or evidence of offline closure. The retained inputs, disabled installation and
deployment hooks, unchanged-SDK checks and native consumer qualification establish
the relevant build contract. Unknown surviving child processes remain failures;
never enlarge the compiler-helper policy to conceal a package-manager subprocess.

A successful `--only-downloads` operation alone does not establish source closure:
some port recipes fetch additional inputs later. The fresh offline build must
pass before publication. A missing late input requires explicit maintenance of
the selected recipe/cache and a new complete qualification attempt; never enable
network fallback in `build`. See the supplier's
[download controls](https://learn.microsoft.com/en-us/vcpkg/commands/install),
[asset caching](https://learn.microsoft.com/en-us/vcpkg/users/assetcaching), and
[raw export contract](https://learn.microsoft.com/en-us/vcpkg/commands/export).

For a separately reviewed export, the lower-level assembly command remains:

```powershell
python tools/sdk_windows.py assemble --export-root prepared-export --source-root retained-inputs --provenance producer.json --output prepared-group
python tools/sdk_windows.py install --group prepared-group --recipe <recipe> --output installed-base --linker-version <actual-linker-version>
python tools/build.py test release --dependency-group prepared-group --windows-dependencies installed-base --rust-sdk C:\retained\rust-windows-sdk --portable --full
```

The nonempty export provenance includes complete `files` and `source_files`
digest maps and must agree with the pinned recipe. Archives preserve both code
and corresponding licenses; record the exact exported package-manager checkout,
port recipes and input downloads in the source tree. Consumers must use a linker
at least as recent as the producing linker. Runtime, configuration and LTO rules
are checked rather than inferred from an archive filename.

The shipped example can use the no-cost Community edition where its terms
permit, or Build Tools for qualifying open-source use. No paid IDE feature is
required. Eligibility is governed by Microsoft
[licensing guidance](https://www.microsoft.com/licensing/guidance/Visual-Studio);
availability without a purchase does not grant unrestricted use.

Microsoft compiler and Windows SDK installation media are not dependency-base
contents. Offline setup of a host without them requires a separately retained,
complete Microsoft offline installer layout, with its component configuration,
installer version, checksums and local verification result. Install from that
layout using the supplier
[offline procedure](https://learn.microsoft.com/en-us/visualstudio/install/create-an-offline-installation-of-visual-studio).
Do not retain only an online bootstrap executable. Tool availability and an edition's
license eligibility are separate questions; this repository does not certify
eligibility for every organization. Native Windows execution remains required.

### One-time Windows host-tool bootstrap

Retain Python, CMake, Ninja and Git alongside the Microsoft offline installer
layout. The Windows all-GUI SDK source archive already retains the first three
ZIPs in its complete download cache. The empty core dependency base does not;
retain these host-tool inputs separately for a core-only offline kit. Git is
needed for checkout identity and Git-based test fixtures. Do not assume the
Microsoft compiler layout includes it. Browser/graphics validation also needs its
separately retained host prerequisites.

On a new Windows host without Python, use Windows' bundled `tar.exe` to extract
only `sources.json` and the three named tool ZIPs from an already verified source
archive. Check the outer archive SHA-256 against the trusted retained checksum
inventory before extracting; do not derive trust from a newly computed hash.
For the currently retained all-GUI group the member names are:

```text
sources.json
cache/downloads/python-3.14.2-embed-amd64.zip
cache/downloads/cmake-4.4.0-windows-x86_64.zip
cache/downloads/ninja-win-1.13.2.zip
```

Use a new owned extraction directory. Pass those local ZIP paths and their
individual hashes from the trusted `sources.json` inventory to the explicit
[bootstrap helper](../tools/restore-windows-host-tools.ps1):

```powershell
$inputs = 'C:\offline\extracted-inputs'
$files = (Get-Content -LiteralPath "$inputs\sources.json" -Raw | ConvertFrom-Json).files
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\restore-windows-host-tools.ps1 `
  -PythonArchive "$inputs\cache\downloads\python-3.14.2-embed-amd64.zip" `
  -PythonSha256 $files.'cache/downloads/python-3.14.2-embed-amd64.zip' `
  -CmakeArchive "$inputs\cache\downloads\cmake-4.4.0-windows-x86_64.zip" `
  -CmakeSha256 $files.'cache/downloads/cmake-4.4.0-windows-x86_64.zip' `
  -NinjaArchive "$inputs\cache\downloads\ninja-win-1.13.2.zip" `
  -NinjaSha256 $files.'cache/downloads/ninja-win-1.13.2.zip' `
  -Output C:\offline\host-tools
```

The helper requires Windows PowerShell 5.1, drive-absolute local paths for every
archive/output argument, and a new destination beneath an existing owned directory.
The example changes script execution policy only for that process. It checks hashes, member paths, collisions, types and
expanded-size limits before publishing the tool tree. It preserves the embedded
Python standard library and original isolated-path policy, disabling that policy
only after validating its expected layout so Python can import sibling checkout
helpers. It downloads and executes nothing. Its receipt records `not-executed`;
extraction alone is not host qualification.

Use the Python path and CMake/Ninja directories in `bootstrap.json` in the chosen
shell environment, initialize the separately installed Microsoft compiler, then
run the ordinary retained-group restore/install and build commands above. Qualify
the actual tools and run the opt-in extraction diagnostics with
`python -B tests/diagnostics/windows_bootstrap.py -v` on native Windows. This
one-time helper is not invoked by ordinary builds, tests, SDK consumers or CI.
Changing its behavior does not relabel existing SDK recipes or rebuild an SDK.

Prepared SDK trees remain immutable during ordinary builds. Tool environments and
WebAssembly compiler wrappers disable Python bytecode writes, WebAssembly library caches
are frozen, and production installation rechecks the complete inventory after
compiler smoke. A successful program run followed by changed SDK files is a
failed installation. Do not repair such a failure by accepting newly generated
files into the old published recipe; prepare and qualify a new immutable group.

## Exclude producer paths during SDK qualification

Maintenance moves any existing `build/sdk-inputs` tree into a fresh private sibling
before SDK installation, compiler smoke, the core package consumer and the GUI
consumer. Both consumers must succeed while the original path is absent. The
orchestrator checks absence and directory identity around each consumer and only
restores the original tree after all checks complete. A fresh `source=base` or
`source=retained` job records initial absence instead; an unexpectedly present
producer tree is isolated by the same procedure. This prevents the consumer from
silently satisfying absolute paths through the original compiler or target files.

`build/sdk-isolation.json` records the exact recipe, group digests, workflow commit,
run and attempt, initial state, checked boundaries and restoration outcome. It is
retained in the SDK proof bundle. Consumer `qualification.json` files include
its SHA-256 and are published only after successful guard exit; the publication
plan follows those receipts. A failed consumer or filesystem operation emits a
failed isolation receipt, when its original parent remains accessible, and preserves
the quarantined tree. A recreated original
path, changed directory identity, link/reparse point or failed restoration stops
qualification without overwriting or deleting either tree. Inspect the receipt,
stop all relevant writers, reconcile both locations, and use a new owned output
for a retry; do not automatically remove a conflicting directory.

This check relies on exclusive ownership of the job workspace and synchronous
consumers; it is not confinement of hostile processes or proof against every
ambient host dependency. Native Linux compiler outputs and supplier trees remain
inside the isolated cache. Windows producer temporary checkouts and WebAssembly
preparation trees have already been removed on producer return; their retained
cache is isolated too. Selected Microsoft tools, operating-system prerequisites
and the separate GUI input group remain intentional external inputs. SDK host
Python supplies the declared build functionality; features needing optional
extensions must probe those extensions explicitly. Mocked fixtures should not
accidentally require optional extensions. Maintenance and actual HTTPS distribution
checks require a host Python with working TLS support. A fresh
runner consuming an exact retained group supplies stronger separation from the
producer host. Changing only this orchestration leaves SDK recipe identities and
archived binary/source bytes unchanged.

## Qualification boundaries for the supplied recipes

The executable tests cover corruption, incomplete inventories, host/target
selection, fresh offline Windows command construction, retained-source replay,
relocation and immutable installation. Native core and GUI Buildroot configurations
have separate recipe identities and are checked against their pinned source.
Actual Bookworm x86_64/ARM64 production, Windows producer and fresh-consumer
observations are listed in the [validation record](validation.md). Only those exact
recipes and observed environments are qualified. Configuration success and mocked
supplier execution cannot replace a real build or oldest-host execution.
The WebAssembly compiler/Node preparation is a separate qualification scope from
the ordinary Chromium/Firefox validation-host matrix. Each release must identify
which exact retained recipe groups and actual execution records it uses.


## Select a complete dependency profile

Keep the small default core build independent of native GUI libraries. A release
that enables all native backends must select the matching GUI profile before
fetching or preparing its dependency group:

| Native host and target | Core recipe | All-native-GUI recipe |
| --- | --- | --- |
| Debian 12 x86_64 | `third_party/sdk/recipe.json` | `third_party/sdk/gui-x86_64/recipe.json` |
| Debian 12 ARM64 | `third_party/sdk/aarch64/recipe.json` | `third_party/sdk/gui-aarch64/recipe.json` |
| Windows x64 | `third_party/sdk/windows-base.json` | `third_party/sdk/windows-gui/windows-base.json` |

Use `--recipe` for each native producer command and `--recipe-file` for each
Windows producer command. Pass the same selected recipe throughout fetch,
verification, build and identity calculation. Every profile has its own immutable
recipe ID. An all-GUI release cannot substitute the smaller core group.

The native GUI profile selects FLTK, SDL2 with X11, X11 development libraries,
and GLVND OpenGL dispatch libraries. Required selections are checked after real
Buildroot configuration; disappearing options fail preparation. Upstream
Buildroot recipes pin their full transitive inputs, and `legal-info` supplies
their notices. FLTK is built as a static toolkit so its C++ objects use the
application's chosen static compiler runtime. The selected Buildroot recipe pins
FLTK 1.3.7 for the compatible 1.3 API baseline. Upstream marks the 1.3 series
end-of-life; see the [supplier release status](https://www.fltk.org/software.php).
Review fixes and the supported distro's maintenance separately, and upgrade the
pinned toolkit through the documented dependency procedure when appropriate.
A newer toolkit is not required merely to build this generic example.
The Windows GUI profile selects `fltk[core]` and `sdl2[core]` with
the common static runtime/toolset policy. Its OpenGL development interface comes
from the pinned Windows SDK. The retained GUI source group already contains the
exact GLEW and FreeType inputs compiled by its adapter; do not compile duplicate
copies into the dependency base.

The Linux native GUI profile requires an X11 service and a compatible installed
OpenGL vendor driver. GLVND dispatch libraries may select that driver at runtime; it is
an explicit host service, outside the private application library inventory.
Test the exact package on both the oldest declared host and the intended display
hosts. The SDK does not include an X server, desktop browser, or vendor driver.
Prepared manifests record the profile's `capabilities` and `runtime_host_services`;
qualification still requires actual builds and execution of every selected host.

The SDK-only libc audit binds its ordinary files, target architecture, retained
source digest and complete recipe identity to one sysroot. It permits the private
interface only between the declared libc cohort and its matching loader, checks
numeric runtime versions, and rejects changed files, wrong locations or missing
providers. Materialized libc development aliases must have exactly the same
bytes as their retained versioned provider. Application package audits retain
their strict private-interface and
bundled-libc rejection. This distinction is required to inspect a compiler
sysroot without weakening the deployed application's runtime policy.

## Retain complete SDK bytes after a consumer failure

SDK maintenance runs a separate retention check even when consumer qualification
fails. It recomputes the recipe for the selected target/profile, checks the origin,
and verifies the exact binary/source/checksum triplet and complete inner
inventories. Only a successful retention check may store the
`sdk-group-<target>-<attempt>` draft-release bundle. Missing, partial, unexpected
or changed bytes produce no retention success output.

The sibling `sdk-proof-<target>-<attempt>` bundle includes bounded
`sdk-retention.json` and `sdk-origin.json` records. Retention binds target, profile,
recipe, source commit, run, attempt and all three file digests. Its qualification
is always `unqualified` and `publication_approved` is false: reusable bytes do not
establish a working consumer. A failed consumer remains failed; publication still
requires successful current consumers and an explicit execution gate.

Hosted replay selects `source=retained`, one exact target/profile, and this strict
version-2 `retained_input` object. Replace every placeholder with reviewed values:

```json
{
  "schema_version": 2,
  "repository": "OWNER/REPOSITORY",
  "target": "windows-x86_64",
  "profile": "all-gui",
  "recipe_id": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS",
  "run_id": 123,
  "source_commit": "REPLACE_WITH_EXACT_PRODUCER_COMMIT",
  "attempt": 1,
  "job_id": 456,
  "workflow": "sdk-maintenance.yml",
  "group": {
    "manifest_id": 789,
    "manifest_sha256": "REPLACE_WITH_GROUP_MANIFEST_SHA256"
  },
  "proof": {
    "manifest_id": 790,
    "manifest_sha256": "REPLACE_WITH_PROOF_MANIFEST_SHA256"
  }
}
```

The manifest IDs identify release assets, and each digest covers its complete
manifest JSON. These are not Actions artifact IDs or transport ZIP hashes. The
manifest binds exact chunk IDs and hashes, whole archive bytes, complete file
inventory, repository/source/run/attempt and producer job. Only explicit SDK
maintenance or SDK import workflows are accepted. A consumer uses its current
recipe and application source; the selected producer identifies the earlier
retained bytes. A changed recipe requires an appropriate other group or explicit
maintenance, never relabelling or a silent cold-build fallback.

[`ci_plan.retained_sdk`](../tools/ci_plan.py) fetches both pinned bundles through
[`ci_transport.py`](../tools/ci_transport.py), checks the completed producer and
both records, verifies the exact SDK triplet, then publishes a fresh local group.
Completed failed producers are deliberately accepted for this retention path;
running, cancelled and timed-out jobs are not. Overall run success is neither
required nor inferred. All remote identities and downloaded bytes are verified.
Missing, changed or incomplete inputs fail. Normal consumption never reads
Actions artifact storage.

For local recovery, save the exact version-2 request as `build/retry/request.json`
in an owned output tree and inspect its producer through the authenticated API:

```text
gh run view RUN_ID --repo OWNER/REPOSITORY --json headSha,status,conclusion,event,workflowName,url
python tools/ci_transport.py fetch --repository OWNER/REPOSITORY --run-id RUN_ID --attempt ATTEMPT --source-commit COMMIT --workflow sdk-maintenance.yml --name sdk-group-windows-x86_64-ATTEMPT --job-id JOB_ID --manifest-id GROUP_MANIFEST_ID --manifest-sha256 GROUP_MANIFEST_SHA256 --allow-failed --output build/retry/group --receipt build/retry/group-receipt.json
python tools/ci_transport.py fetch --repository OWNER/REPOSITORY --run-id RUN_ID --attempt ATTEMPT --source-commit COMMIT --workflow sdk-maintenance.yml --name sdk-proof-windows-x86_64-ATTEMPT --job-id JOB_ID --manifest-id PROOF_MANIFEST_ID --manifest-sha256 PROOF_MANIFEST_SHA256 --allow-failed --output build/retry/proof --receipt build/retry/proof-receipt.json
python tools/sdk_windows.py recipe-id --recipe-file third_party/sdk/windows-gui/windows-base.json
python tools/dependency_store.py verify --group build/retry/group --recipe RECIPE
```

Use `third_party/sdk/windows-base.json` for the core profile. Compare the selected
recipe and all triplet hashes with `sdk-retention.json` and verify its target,
profile and producer identity before using the bytes. The hosted helper performs
these comparisons automatically. A local fetch alone is not SDK qualification.
Use `sdk-import.yml` as the workflow argument when the exact origin is an import.

On a matching Windows host, select the pinned external compiler in PowerShell,
then install the dependencies into a new location and run a fresh consumer:

```powershell
./tools/ci_windows.ps1 -Output build/retry/windows-toolchain.json
$selected = Get-Content build/retry/windows-toolchain.json -Raw | ConvertFrom-Json
python tools/sdk_windows.py install --group build/retry/group --recipe RECIPE --output build/retry/dependencies --linker-version $selected.LinkerVersion
python tools/build.py test release --windows-dependencies build/retry/dependencies --dependency-group build/retry/group --rust-sdk C:\retained\rust-windows-sdk --build-dir build/retry/core-build --portable --full --jobs 2
```

The core check does not qualify GUI capabilities. To rerun the existing complete
GUI consumer, supply the separately retained GUI input group and pinned external
host graphics archive. In the same selected compiler environment:

```text
python -c "import sys; from pathlib import Path; sys.path.insert(0, 'tools'); import ci_plan; ci_plan.prepared_check('windows-x86_64', 'RECIPE', Path('build/retry/group'), Path('build/retry/gui-check'), 2, gui_group=Path('RETAINED_GUI_GROUP'), graphics_archive=Path('RETAINED_GRAPHICS_ARCHIVE'), rust_group=Path('RETAINED_RUST_GROUP'), rust_recipe='EXACT_RUST_RECIPE_ID')"
```

That command verifies and relocates the SDK, builds in one tree, probes actual
host graphics, runs the complete GUI checks and removes its temporary driver
files before reporting success. It does not download missing inputs. GUI inputs
and host graphics remain subject to their separate retention and redistribution
rules.

For a matching Linux host, verify the group as above and use the existing SDK
consumer commands:

```text
python tools/sdk.py install --group build/retry/group --recipe RECIPE --output build/retry/sdk
python tools/sdk.py verify build/retry/sdk --release
python tools/build.py test release --sdk build/retry/sdk --rust-sdk /owned/matched-rust-sdk --build-dir build/retry/native-build --portable --full --jobs 2
```

Choose a new output directory for every attempt and preserve failure evidence.
Restore and verify the complete matching Rust extension separately before these
application commands. The prepared GUI helper consumes its complete Rust group
and exact 64-character recipe digest. For a deliberately legacy C++ recovery,
select `--core-provider cpp` (or `core_provider='cpp'` in the helper) explicitly.
Native GUI and browser requirements still need their relevant full consumers.
Hosted `source=auto` and `source=base` continue to use qualified base storage;
draft bundle reuse requires the separate explicit `source=retained` selection.
A retained group or local retry does not itself authorize base publication.

## Explicit migration from legacy Actions storage

[`sdk-import.yml`](../.github/workflows/sdk-import.yml) is a one-time migration
entry point for older retained SDK groups. It accepts the exact legacy schema-1
request: the same repository, target/profile, recipe, run/attempt/job and source
fields, with `group` and `proof` containing immutable artifact `id` and full ZIP
`sha256`, and no `workflow` field. It does not infer the latest run or artifact.
The legacy reader exists only for this explicit import; ordinary SDK replay
rejects version 1 and never falls back to that reader.

The importer verifies the original maintenance workflow, repository and producer
identity, completed job, complete artifact metadata and ZIP hashes, safe bounded
members, both inner SDK inventories and exact retention receipt. It preserves the
original request and lineage, writes new import-run origin/retention records, and
stores the unchanged triplet and proof as draft bundles. Its output is a concrete
version-2 request referencing `sdk-import.yml`; use that exact request for a fresh
consumer. Importing verified bytes never certifies the consumer or publishes base.

Preserve the old assets until the new bundles have been fetched independently,
the triplet matches byte for byte and the replay is usable. Then review exact
superseded artifact IDs and dependencies before an authorized cleanup. Never
remove unrelated artifacts or the sole surviving qualification evidence. The
importer does not delete remote data or create new Actions artifacts.

## Replay without supplier acquisition

SDK maintenance with an all-GUI profile and native GUI qualification require an
explicit `gui_input` selector, in the same base/retained format used by the
[screenshot workflow](screenshots.md). The workflow restores and verifies that
complete group before entering the SDK consumer container. Replaying a retained
SDK never clones the GUI supplier. Obtain a new group only through the explicit
GUI-input maintenance workflow. Missing, changed or incomplete retained inputs
fail without a supplier fallback. Windows replay also requires an explicitly
retained graphics archive URL; only `source=rebuild` may acquire the pinned
upstream graphics prerequisite when no retained URL is selected. Browser engines
remain host prerequisites and are never added to the compiler SDK.
