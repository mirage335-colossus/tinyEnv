# Building and installing

To build and open an example, start with [COMPILE-gui](../COMPILE-gui) for a
desktop window or [COMPILE-web](../COMPILE-web) for a browser. [COMPILE](../COMPILE)
retains the general command reference; this page explains the build options.

The maintained entry point is `build.sh`, a small shell launcher for
`tools/build.py`. CMake owns the dependency graph, compilation, installation,
and packaging. The wrapper provides predictable defaults and validation; it
must not become an independent build system. Read [testing](testing.md) for
test selection and [portability](portability.md) before promising that a
package runs on another computer.
The [shell script inventory](shell-scripts.md) identifies the Bourne-compatible
project wrappers and the helpers that retain modern POSIX shell requirements.

Use [development speed](development-speed.md) to select the smallest useful check
and keep independent release work parallel. Leaving compile jobs unspecified uses
the available CPU and RAM detector; `--build-jobs` overrides compilation separately
from `--test-jobs`.

`--timings build/timings.json` writes optional monotonic wall times for source and
SDK verification, configuration, compilation, test discovery/startup and test
execution. It does not change test selection or bypass checks. See the
[repeatable warm measurement recipe](development-speed.md#measure-warm-iterations)
for interpreting inclusive subprocess times and recording failed runs.

## Prerequisites and working commands

Install Git, CMake 3.24 or newer, Ninja, Python 3.9 or newer, and a compiler with
the C++20 features used by this repository. Python runs developer helpers; the
installed CLI does not require Python. The default application has no
third-party application runtime dependencies. Compiler and operating-system
runtimes still apply. GUI integration is optional and has separate prerequisites.
The core provider defaults to Rust. For Debian-family native `dev` builds,
install distribution `rustc` and Cargo; Debian 12 supplies the Rust 1.63 baseline.
Other native hosts and release, sanitizer, packaging, portable, Windows, Wasm
or prepared-C++-SDK profiles need an already verified `--rust-sdk PATH` matched
to the selected target. These are build inputs, not installed runtime tools.

```sh
./build.sh build dev
./build.sh test dev --label core
./build.sh test dev --full
./build.sh test asan --rust-sdk /absolute/path/to/rust-sdk
./build.sh package release --rust-sdk /absolute/path/to/rust-sdk
./build.sh package release --rust-sdk /absolute/path/to/rust-sdk --verify-package
./build.sh portable-package --rust-sdk /absolute/path/to/rust-sdk
./build.sh test dev --test core.store --test core.cli
```

On Windows, start a terminal with the intended compiler environment initialized
and invoke the same helper directly:

```powershell
python tools/build.py build dev --rust-sdk C:\retained\rust-sdk
python tools/build.py test dev --rust-sdk C:\retained\rust-sdk --full
python tools/build.py package release --rust-sdk C:\retained\rust-sdk
```

The sanitizer preset requires a supported compiler/runtime combination; do not
interpret rejection of an unsupported compiler as successful sanitizer coverage.
Use `python tools/build.py --help` for the current wrapper options. Paths and
arguments must be passed as arguments, never evaluated as shell text.

| Preset | Output directory | Purpose |
| --- | --- | --- |
| `dev` with Debian distribution Rust | `build/dev-rust/` | Incremental native development and tests |
| `release --rust-sdk PATH` | `build/release-rust-sdk/` | Optimized application and package candidate |
| `asan --rust-sdk PATH` | `build/asan-rust-sdk/` | C++ and boundary instrumentation; stable Rust itself is not instrumented |
| A preset with `--sdk PATH --rust-sdk PATH` | `build/PRESET-sdk-rust-sdk/` | Explicit matched target SDK selection |
| `--core-provider cpp` | Original preset directory, such as `build/dev/` | Complete legacy C++ configuration |

`--gui` adds the optional GUI integration using the complete verified source group
in this checkout, with a `-gui` directory suffix. It needs no second repository,
submodule initialization or supplier download. For example:

```sh
./build.sh test dev --gui --gui-backends terminal,framebuffer,hosted-web --label gui
./build.sh build release --rust-sdk /absolute/path/to/rust-sdk --gui --gui-backends fltk
```

The second command also needs the distribution's FLTK development package and
its platform dependencies. On Debian 12 these are distribution packages; GUI
sources and retained toolkit archives are already in this checkout. The Rev
backend requires the newer compiler/CMake versions described in the GUI guide.
A prepared SDK is optional for ordinary native builds and required when its
specific target/toolchain contract is selected.

`--gui-source /absolute/path/to/pinned-checkout` and `--gui-input-group PATH`
remain explicit alternatives to `--gui`; these three selectors are mutually
exclusive. `--gui-backends` alone does not enable GUI, preserving core-only Wasm
builds. Default core builds do not restore or compile GUI inputs. Follow
[the GUI guide](gui-boundary.md) for extra native-host options. GUI distribution
checks the locked, reviewed supplier permissions. `package` requires a
Release configuration and all selected dependencies and notices.

`package --verify-package` also creates an inventory beside each generated archive,
verifies it after safe extraction into a fresh location, runs the installed CLI
and builds a separate consumer of the installed CMake export. Verification failure
fails the command. `portable-package` selects Release, the portable CPU/runtime policy and this
verification together. Ordinary `package release` retains its existing explicit
portability choice. This is an opt-in local package check; hosted release producers
already perform these checks through their existing delivery path. It does not
install anything into the host or establish other-platform qualification.

A native package may include a browser build produced earlier from the same
complete source tree. Build the Wasm target using its own SDK tree first, then
create a schema-3 browser package with `tools/package_wasm.py --source-root PATH`.
Pass its directory and the exact SHA256 of `web-manifest.json` to the native build:

```sh
./build.sh portable-package --rust-sdk /absolute/path/to/native-rust-sdk \
  --build-dir build/native-with-browser \
  --wasm-package /absolute/path/to/verified-browser-package \
  --wasm-package-sha256 EXACT_WEB_MANIFEST_SHA256
```

Both options are required together. The wrapper verifies the pinned manifest,
self-contained document and complete source identity before and after the native
operation; CMake stages an owned copy and checks it again at installation. The
pair becomes part of the build-tree identity. Changing or removing it requires a
fresh tree. No Emscripten rebuild, SDK download or browser server is introduced in
the native graph. Source-bound schema-2 packages remain eligible for native import;
schema-1 packages verify independently but lack that source binding. Legacy
schemas retain their original validation rules and make no renderer-isolation
claim. See [browser embedding and package policies](browser-embedding.md),
[installed launches](installed.md) for the offline document command and
[distribution channels](distro-channels.md) for native package inclusion.

`test` builds prerequisites before invoking CTest. Its default runs the complete
enabled local test suite. `--label fast`, `core`, `tools`, `integration`, or
`gui` selects a focused scope. A label that selects nothing must fail. Repeat `--test NAME` to select exact
registered CTest names instead; typos and empty selections fail. CTest fixture
setup/cleanup dependencies join the selection, and the wrapper builds the union
of their registered prerequisites in the same graph. It never falls back to
a whole-project build because an exact selection resolved no targets. An
optional feature's tests exist only when the feature is configured.
Each test must call `foundation_test_prerequisites(NAME [TARGET ...])` after
registration. Omit targets explicitly for scripts needing no compiled executable.
The final registry checks every configured test and generates the development
label targets. Keep installation prerequisites complete, including configured GUI
hosts, while a local `core` selection builds only core prerequisites. Candidate
scope assignment is broader and remains derived from the complete test inventory.

Direct CMake remains supported:

```sh
cmake --preset dev -DFOUNDATION_RUST_SDK_ROOT=/absolute/path/to/rust-sdk
cmake --build --preset dev --target foundation-tests --parallel "$(python3 tools/build_capacity.py)"
ctest --preset dev --output-on-failure --no-tests=error --parallel 2
cmake --install build/dev --prefix "$PWD/build/install"
```

The supplied presets use single-configuration Ninja. For Visual Studio or
Ninja Multi-Config, pass `--config Release` to build/install and `-C Release`
to CTest/CPack. Select one configuration consistently. Passing `-C Release`
to CPack cannot turn a single-configuration Debug tree into an optimized build;
configure and compile a Release tree first.

The installed CMake package exports `foundation::core`. A separate consumer
must use `find_package(Foundation CONFIG REQUIRED)` and link that target;
consumers must not copy internal include directories or compiler flags. The
integration checks exercise this installation boundary.

<a id="optional-rust-validation-provider"></a>

## Rust Default And Provider Selection

`--core-provider rust` is the default for all fresh configurations. It selects the private
text-validation leaf while preserving the public C++ `Store` API and its failure
guarantees. The Rust workspace uses edition 2021, a Rust 1.63 baseline, zero
external crates and allocation-free `no_std` code. C++ owns records, strings,
exceptions and frontend behavior; every configured CLI/GUI host links the same
selected core. This is a narrow component, not a rewrite of the application.
The [policy rationale](rust-hybrid-plan.md#why-rust-is-the-default) explains the
security direction, tool requirements and measured-performance limits.
`--core-provider cpp` explicitly selects the complete legacy provider and makes
no Rust discovery, compiler probe, SDK restoration or download. Missing Rust
inputs never silently select it. An existing direct CMake cache keeps its recorded
provider; changing providers requires a fresh tree.

Use a verified [retained Rust extension](sdk.md#retained-rust-extension):

```sh
./build.sh test dev --rust-sdk /absolute/path/to/rust-sdk \
  --build-dir build/dev-rust --label core
./build.sh test dev --sdk /absolute/path/to/cpp-sdk \
  --rust-sdk /absolute/path/to/rust-sdk \
  --build-dir build/dev-sdk-rust --gui --label gui
```

The existing `--sdk` supplies the C++ target SDK; `--rust-sdk` supplies a separate
Rust extension matched to that target. Windows uses its existing dependency-base
selector and Microsoft host prerequisites alongside the Rust extension. Missing,
changed, incomplete or mismatched explicitly selected Rust inputs fail the
operation. An unavailable Rust profile never silently selects C++.

The following target examples consume already restored, verified all-GUI inputs.
They do not prepare or fetch an SDK. Use separate fresh build directories and a
matching native host for each target. The full CTest selection is not a substitute
for the separate real-browser or host-visual qualification prerequisites.

Native Linux x64 or ARM64, with the matching retained C++ and Rust extensions:

```sh
./build.sh test release --sdk /retained/linux-all-gui-sdk \
  --rust-sdk /retained/rust-linux-sdk --portable \
  --gui --gui-backends terminal,framebuffer,fltk,rev,sdl,hosted-web \
  --build-dir build/rust-linux-all-gui --full
```

Native Windows x64, from the initialized matching MSVC developer prompt:

```powershell
python tools/build.py test release --portable `
  --windows-dependencies C:\retained\windows-all-gui-dependencies `
  --dependency-group C:\retained\windows-all-gui-group `
  --rust-sdk C:\retained\rust-windows-sdk `
  --gui --gui-backends terminal,framebuffer,fltk,rev,sdl,hosted-web `
  --build-dir build/rust-windows-all-gui --full
```

The Windows group must be the complete binary/source/checksum group matching the
restored dependency export. It supplies dependencies, not the Microsoft compiler
or Windows SDK; retain and initialize those host prerequisites separately.

Browser Wasm, with the exact paired Emscripten 6.0.10 and Rust 1.63 extensions:

```sh
./build.sh test release --sdk /retained/emscripten-sdk \
  --rust-sdk /retained/rust-emscripten-sdk \
  --gui --gui-backends wasm --build-dir build/rust-wasm --full
```

To create and relocate-verify a native archive, replace `test release`/`--full`
with `package release`/`--verify-package`, preserving the same target, input,
provider, GUI and build-directory options. Wasm test execution uses the retained
Node executor; actual browser interaction remains separate. The
[qualification workflow](../.github/workflows/rust-qualification.yml) supplies
the declared execution environments and records each gate's scope.

Through the wrapper, only Debian-family native Linux `dev` builds without a
target SDK or portable policy may use installed distribution `rustc`/Cargo
instead of `--rust-sdk`. This route needs dpkg-backed ownership and complete
package/license notices; other distributions and unowned tool layouts use the
retained extension until another ownership/notice provider is implemented.
The actual tools, compiler host, target libraries, native link requirements and
notices are checked; rustup proxies are rejected. The native-only library check
accepts the matched package-owned `libstd`/`libtest` links only after binding the
link, regular target, package versions and ownership tool. This does not permit
symlinks in retained SDK target libraries.

With those distribution prerequisites already installed, a fresh focused check is:

```sh
./build.sh test dev --build-dir build/dev-distro-rust \
  --test core.store --test core.cli --test core.text_validation \
  --test core.text_status --test rust.unit --test integration.install
```

The wrapper requires the retained extension for Rust `release`, packaging,
`asan`, portable builds and prepared-target builds. Direct CMake optimization
alone does not establish release qualification. Ordinary builds never install
tools, contact rustup or fetch crates. See [provider tests](testing.md#rust-provider-checks)
for the limits of mixed sanitizer coverage and
[portability](portability.md#rust-provider-boundary) for platform evidence.

Default output names add `-rust` for native development tools or `-rust-sdk` for
a retained extension, after the existing `-sdk` suffix when present. Keep C++ and
Rust in separate trees. Provider, Rust tool digests, target and SDK manifest
identity belong to the configured tree; changing them requires a fresh tree.
Fresh direct CMake configurations default `FOUNDATION_CORE_PROVIDER=rust`; select
`FOUNDATION_RUST_SDK_ROOT=/absolute/path/to/rust-sdk`. An optional
`FOUNDATION_RUST_TARGET` must match the C++ platform target.

For the legacy build on a host with no Rust tools, use a fresh tree explicitly:

```sh
./build.sh test dev --core-provider cpp --build-dir build/legacy-cpp --label core
cmake --preset dev -DFOUNDATION_CORE_PROVIDER=cpp -B build/legacy-cpp-cmake
```

Neither command supplies Rust inputs. Target profiles without a qualified Rust
extension must fail under the default; explicit C++ selection retains their
existing compatibility route.

CMake owns one subordinate Rust archive producer for each selected configuration.
Cargo receives a frozen lockfile, offline mode, one worker, a private Cargo home
and configuration-specific output under `BUILD_DIR/rust/CONFIG`. The helper rejects
ambient Rust/Cargo overrides, external crates and build scripts. It binds source,
compiler, target-library, flag and notice identities into a verified archive
receipt. CMake owns the final C++ link and installation. Rust panics abort;
cross-language LTO is unsupported. The installed export carries the Rust archive
and its native link requirements, so an installed C++ consumer needs no Rust
compiler or Cargo. Application `build-info.txt` records the provider, Rust
compiler/target and retained SDK identities.

## One graph and deliberate configurations

Keep library sources in one reusable target. Link the CLI, tests, and optional
GUI to it. Compile shared GUI behavior once per compatible configuration and
reuse it across adapters. Do not maintain a separate hand-written source list
for every executable, test, and package. Target-scoped include directories,
compile features, definitions, and link requirements carry the contract.

A single build means one authoritative graph and entry point. Separate output
trees remain necessary for incompatible compilers, target architectures,
standard libraries, sanitizer settings, SDK identities, and generators. Never
change a configured tree from one such identity to another. A cached compiler
choice can survive changes to `CC` or `CXX`; a successful reconfiguration alone
does not prove the requested compiler took effect.

Use a fresh, explicitly named build directory through direct CMake when
experimenting with another toolchain. Keep generated files in `build/`. Do not
delete unrelated build trees to fix one stale cache. Record the affected tree,
preserve needed logs, and remove only the owned disposable output.

Configure-time build information should record source revision and dirty state,
compiler path/version, generator, target, build type, feature selection, and SDK
recipe identity. A release build must use clean, identified source. Dirty
development evidence needs a diff identity or file digests as well as a commit.
This provenance is not proof that rebuilding produces identical bytes.

## MSVC build-service ownership

Separate build directories do not isolate compiler services. On Windows, the
supported wrapper, source-test planner, native GUI prerequisites, release source
checks and installed-consumer checks use
[`windows_compiler.py`](../tools/windows_compiler.py) around compiler-capable
commands, including CMake configure/try-compile, build and tests that compile
fixtures. Each operation owns its process tree through completion and cleanup.

The owner binds `cl.exe`, `link.exe` and their helper files to the selected
`VCToolsInstallDir` and PATH, recording physical identity and SHA-256. Each owner,
including a nested one, receives a fresh `_MSPDBSRV_ENDPOINT_` in its child
environment. [Microsoft's build tooling uses this endpoint to isolate PDB-server I/O](https://github.com/microsoft/BuildXL/blob/main/Public/Sdk/Experimental/Msvc/Native/Tools/Link/Link.dsc).
This implementation evidence is not a stable public toolset API promise: qualify
the actual selected toolset with the [native isolation diagnostic](testing.md#focused-host-diagnostics)
when adopting or upgrading it.

After a successful command, every live pinned member must identify the exact
selected `vctip.exe` or `mspdbsrv.exe` before bounded termination and joining.
Another compiler, an unknown process, changed toolkit input or uncertain join
fails. Ordinary commands retain strict descendant completion. Completion receipts
are printed only after the owner closes successfully. Consumer workspaces remain
intact when writer cleanup is uncertain; inspect them before later cleanup.
This requires no global process-name kill, registry change, idle delay, compiler
installation modification or removal of debug information.

For a retained static Windows SDK, the wrapper also disables manifest installation
and app-local deployment in the supplied integration script, and disables its
metrics in the child environment. See the [Windows SDK consumer contract](sdk.md#windows-dependency-base-and-separately-installed-host-tools).
Package-manager post-build hooks are not compiler helpers and receive no cleanup
exception. Requalify consumer configuration when changing a retained SDK.

## Faster iteration without changing behavior

Use incremental builds and the smallest affected target or test label while
editing. Change a public header only when the public contract changes: unnecessary
header dependencies expand recompilation. Disable unused upstream examples and
tools. Generate `compile_commands.json` for accurate editor and analysis input.

The wrapper budgets compilation and testing independently:

```sh
./build.sh test dev --build-jobs 4 --test-jobs 2 --label fast
```

For compilation, `--build-jobs` takes precedence over `--jobs`, then
`CMAKE_BUILD_PARALLEL_LEVEL`, then the resource detector. For tests,
`--test-jobs` takes precedence over `--jobs`, then `CTEST_PARALLEL_LEVEL`, then
an independent resource-aware default capped at four. Every explicit limit must
be positive. These scheduling choices do not change the compiled configuration or require a new
build directory.

The detector combines available processors, Linux CPU affinity and container
quotas, and available host/container memory. It reserves one processor when
possible, reserves at least 256 MiB or ten percent of available memory, and
budgets 768 MiB per automatic compile or test worker. Tests additionally cap the
automatic allowance at four, independently of an explicit compile limit. Unknown
memory limits cap automatic concurrency at two; failed detection falls back to
one. CTest still honors declared resource locks and serial tests. These are
conservative estimates, not a guarantee: large links, instrumented builds and simultaneous sessions can
need lower explicit limits. Measure and adjust for the actual machine.

CMake automatically uses an available `ccache` with Ninja or Makefiles when no
compiler launcher is already selected. It never installs or downloads the
cache tool. Set `-DFOUNDATION_COMPILER_CACHE=OFF` for a new direct-CMake tree to
disable automatic selection, or provide an explicit supported CMake compiler
launcher. Never enable cache settings that weaken dependency checking. A cache
miss must produce the same correct build as a cache hit. Keep cache storage
outside tracked source.

Measure clean and incremental builds, a representative source edit, a public
header edit, and test startup independently. Report compiler, configuration,
available memory, concurrency, and cache status with timings. Adopt precompiled
headers, unity compilation, or link-time optimization only when measurements
justify their complexity and independent builds still pass.

## Offline and portable operation

Configuration and ordinary builds must not download dependencies, install
packages, modify a prepared SDK, or require administrator access. Preparation
is an explicit operation with documented inputs and checksum verification.
Missing inputs produce an actionable error. See [dependencies](dependencies.md)
and [SDKs](sdk.md).

[Disconnected application acceptance](offline-builds.md) names the complete
input categories and the supported Bookworm runner. It restores retained SDK
bytes and invokes this same wrapper inside a verified network boundary, with a
fresh output tree and compiler caching disabled. Compiler reconstruction is a
separate SDK-maintenance operation. Ordinary native development through declared
distribution packages remains supported.

Build a copied checkout and an installed consumer from paths containing spaces.
Avoid hard-coded home directories, `/tmp` include aliases, absolute development
RPATHs, and implicit access to a sibling checkout. A dependency with stricter
path restrictions must reject them at its own preparation boundary and document
that limit; do not impose the restriction on the whole application unnecessarily.

All source and build-tree writes follow [agent coordination](agent-coordination.md).
Claim the output tree for configure, build, test, package, and cleanup together.
Do not run a build against files another session may still modify; use a stable
snapshot or an agreed integration checkpoint.

## Rootless native development dependencies

[`prepare_dependencies.py`](../tools/prepare_dependencies.py) can create a
native Linux development prefix from retained Debian archives without package
installation or administrator access. This is an optional local development
route. It does not replace an isolated release SDK or lower the host runtime
floor. Select exact package versions and architecture, retain the archives, and
review their source package provenance before preparation.

An input JSON file records every package's `package`, `source_package`, `version`,
`architecture` (`all` or the selected host architecture), local `.deb` filename,
`sha256` and upstream `url`. The top-level fields are `schema_version: 1`,
`architecture` in Debian vocabulary, `packages` and `runtime_libraries`.
Each runtime entry has `package`, `development`, `soname` and `link`: it connects
one extracted development linker alias to an installed architecture-qualified
runtime package with exactly the same version. Its physical file digest is
frozen and rechecked. Use an empty list when no host runtime aliases are needed.

```json
{
  "schema_version": 1,
  "architecture": "amd64",
  "packages": [{
    "package": "example-dev", "source_package": "example",
    "version": "1.0-1", "architecture": "amd64",
    "file": "example-dev_1.0-1_amd64.deb",
    "sha256": "REPLACE_WITH_THE_REVIEWED_ARCHIVE_SHA256",
    "url": "https://deb.debian.org/debian/pool/main/e/example/example-dev_1.0-1_amd64.deb"
  }],
  "runtime_libraries": [{
    "package": "example-runtime", "development": "example-dev",
    "soname": "libexample.so.1",
    "link": "usr/lib/x86_64-linux-gnu/libexample.so"
  }]
}
```

This illustrates the schema, not a downloadable package selection. Replace the
example with reviewed existing packages and exact archive digests.

```sh
python3 tools/prepare_dependencies.py prepare --manifest /owned/inputs.json   --packages /owned/retained-debs --output /owned/development-prefix
python3 tools/prepare_dependencies.py verify /owned/development-prefix
./build.sh build dev --dependency-prefix /owned/development-prefix   --build-dir /owned/native-build --build-jobs 2
```

Preparation is offline by default. A separate explicit `--download` operation
may fetch missing declared archives from Debian's approved HTTPS origin and
checks their digests before retaining them. Ordinary configure/build/test never
fetches. Preparation rejects path traversal, conflicting files, special entries
and escaping aliases; include all required archive closure, including shared
documentation needed by relative aliases. It retains the input manifest and
`.deb` files with a complete prepared-tree inventory.

The wrapper verifies the tree before and after use. Direct CMake supports
`-DFOUNDATION_DEPENDENCY_PREFIX=/owned/development-prefix`; it verifies before
discovery and again before compilation and installation. A changed prefix
selection requires a fresh build tree. Target SDKs and restored Windows
dependency groups cannot be combined with this native-only prefix. Development
inputs and host runtime upgrades must be deliberately re-prepared and rechecked.

## Installed dependency notices

Installation and packaging collect dependency terms into
`share/doc/Foundation/dependency-notices`, including a JSON inventory of notice
bytes and exact input providers. The SDK route copies every declared legal-info
file from the verified retained tree. The Windows dependency route checks each
selected port's exported copyright and includes transitive exported notices.
Native portable builds identify the selected static C++/compiler archives through
the compiler and resolve their exact distro ownership. Staged private runtime
libraries are resolved to their original providers and included too. Copyright
references to `/usr/share/common-licenses/NAME` require the corresponding complete
text. An SDK cannot satisfy a missing target notice using the host's license tree.

Bundled source dependencies register a verified notice with
`foundation_notice_file(absolute_path)`; its configure-time digest is rechecked
when installed. Native libraries without local distro ownership need a reviewed
`FOUNDATION_NOTICE_MANIFEST` passed to direct CMake. Its schema is
`{"schema_version":1,"components":[{"name":"example","inputs":["EXACT_LIBRARY_SHA256"],"notices":{"LICENSE":"EXACT_NOTICE_SHA256"}}]}`.
Notice paths are relative to that manifest and must remain inside its directory.
Every explicit component maps exact library bytes to exact complete notice files.
This also applies to static archives extracted into a rootless native prefix.

Missing, changed or ambiguous notice inputs fail packaging. Repeat installation
accepts only an identical existing notice directory; use a fresh owned prefix
for changed dependencies. Copying notices is a mechanical completeness check,
not a grant of redistribution permission. Review dependency terms and preserve
all existing publication gates, including the GUI supplier permission scope.

## Before changing the build

Check command-line diagnostics, path handling, compiler/SDK changes, offline
behavior, a clean build, an incremental build, installation, and an independent
consumer as relevant. Document new options, dependencies, output paths, and
compatibility effects together with the implementation. Do not raise the stated
minimum CMake, Python, or compiler requirement accidentally by adopting a newer
API without a guard.

The preset format and toolchain behavior are defined in the
[CMake 3.24 documentation](https://cmake.org/cmake/help/v3.24/manual/cmake-presets.7.html)
and [toolchain manual](https://cmake.org/cmake/help/v3.24/manual/cmake-toolchains.7.html).

## Explicit output, portability and host-check controls

Use `--build-dir /owned/build-tree` for an independently claimed session tree.
The wrapper still binds it to the exact compiler, SDK, feature choices and
configuration; a different identity requires a fresh tree. Do not share one
build directory between simultaneous writers.

`--portable` selects generic CPU code and the chosen static C++/compiler-runtime
policy. It cannot lower libc requirements by itself. Linux release candidates
must use the qualified glibc 2.36 sysroot, then pass `verify_abi.py` against every
ELF file. A modern native compiler on a newer distro remains a development
configuration until that inspection and oldest-host execution pass.

`--gui-backends` explicitly selects optional backends from the wrapper's checked
inventory. `--host-tests` enables real GUI host execution and requires GUI input;
run it only where the corresponding display/browser prerequisites are available.
`--distribution-tests` enables additional packaging/tool checks. These controls
reduce development work without claiming omitted coverage as successful.

```sh
./build.sh test dev --build-dir /owned/session-build --label core
./build.sh test release --build-dir /owned/release-build --sdk /owned/sdk --rust-sdk /owned/matched-rust-sdk --portable --full
./build.sh package release --build-dir /owned/release-build --sdk /owned/sdk --rust-sdk /owned/matched-rust-sdk --portable
```

Native Windows dependency groups are separate from compiler/sysroot SDKs. Use
`--dependency-group PATH` to bind an exact verified group; its recipe is read
from the complete group's checksum filename. After restoring it with
`sdk_windows.py install`, add `--windows-dependencies RESTORED_PATH` to consume
its checked CMake prefix. Initialize the separately installed Microsoft toolchain
first. The package build
record identifies the dependency recipe for mandatory release retention. See the
[Windows base contract](sdk.md#windows-dependency-base-and-separately-installed-host-tools).

### Dependency policy in new CMake directories

Every target-bearing `CMakeLists.txt` below the root calls
`foundation_register_build_directory()` before defining targets or finding
packages. The root registers automatically. The policy captures imported target
paths, generator expressions and notices while their declaring directory is still
in scope; local imports can have the same name in separate directories. Final
configuration rejects an unregistered target directory. SDK containment runs before
compilation and installation, and imported-library bytes are checked again against
the configured identity. Do not make imports global or skip an inaccessible target
to work around this requirement.

Retained browser SDKs may list only top-level tool licenses in older metadata. The
application notice collector also requires the authenticated Emscripten authors,
musl, C++ runtime, compiler runtime, unwinding and allocator terms already stored
in those SDKs. It never downloads replacement notices or mutates retained SDK bytes.
Checkout text uses LF on every host so exact patch and source identities survive
Windows Git defaults; binary and explicitly byte-preserved dependencies remain exempt.

Third-party subdirectories declaring their own CMake `project()` receive the scoped
dependency guard through `CMAKE_PROJECT_INCLUDE_BEFORE`, preserving existing hooks.
This covers retained source-built libraries without modifying supplier source.
A target-bearing directory without `project()` still requires the explicit
registration call; the final completeness check rejects an omitted directory.
