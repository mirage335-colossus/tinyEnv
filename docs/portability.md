# Portability and compatibility contracts

Source portability, build-host compatibility, and released-binary compatibility
are different promises. State and test each separately. A successful build on a
new machine does not establish that its binaries run on an older one.

## Declare the supported environment

For every supported release target, record operating system, architecture,
minimum operating-system/runtime version, instruction-set baseline, compiler
runtime policy, enabled features, and required host services. Record the oldest
tested environment and at least one newer environment. Label untested targets
as proposed, even if the source appears portable.

| Target identity | Architecture aliases | Normal release form | Status in this example |
| --- | --- | --- | --- |
| Linux `x86_64` | `amd64`, `x64` | TGZ; optionally Debian `amd64` | All-GUI SDK production and application certification passed on the recorded Debian 12 baseline; other kernels and devices need separate checks |
| Linux `aarch64` | `arm64`, `ARM64` | TGZ; optionally Debian `arm64` | All-GUI Bookworm SDK production and native ARM64 application certification passed; other recipes and environments need separate checks |
| Windows `x86_64` | `AMD64`, `x64` | ZIP; optionally a separately maintained installer | Prepared-SDK producer, six archive backends and source/recovery certification passed on Windows Server 2022; oldest client floor remains separate |
| macOS or another target | Platform-specific naming | Platform-specific package | Extension requiring an explicit support decision |

Aliases identify an architecture, not an interchangeable operating-system ABI.
A 32-bit system cannot run a 64-bit package merely because its processor is
capable. A Linux `aarch64` archive is not a Windows ARM64 archive. Normalize names
once when generating filenames and translate to a package manager's vocabulary
at the packaging boundary.

The [current validation record](validation.md#rust-all-gui-release-and-integrated-packages-2026-10-06) identifies a successfully certified
multi-platform application release published as Latest, with its exact revision,
recipes and environments. All-GUI recipe results do not qualify different core-only
recipes, every older operating system, or independent signed package channels.
Use the [validation template](templates/validation.md) to record adopted targets.

<a id="optional-rust-provider-boundary"></a>

## Rust Provider Boundary

The existing target/release evidence above belongs to its recorded application
bytes and provider. Adding a Rust build profile does not qualify new Rust
binaries on those platforms. Fresh configurations default to Rust; the complete
legacy compatibility route is explicitly selected with `--core-provider cpp`.
Default or explicit Rust selection must succeed with its declared toolchain or fail;
it cannot silently fall back to C++.

The implemented Rust leaf validates the same borrowed byte buffer used by
`Store`, behind a private C ABI. It uses fixed-width statuses and `size_t`/`usize`
lengths, retains no pointers, performs no allocation and never exchanges C++
objects or exceptions. C++ continues to own strings, records, frontend behavior
and the final link. All enabled frontends share this provider, so the language
choice does not create backend-specific application logic. This limited ABI
reduces the compatibility surface; it does not prove the compiler host,
target-library or final runtime contract.

| Rust profile | Implemented boundary and qualification limit |
| --- | --- |
| GNU/Linux x86_64 | Final `41d28fe` native Bookworm lane passed 116 source CTests, including four core and 52 application GUI tests, all six backend runtime checks, package/consumer/ABI gates, actual Firefox/renderer checks, retained-package replay and disconnected acceptance. A separate clean Debian distro-tool development check passed four core tests, six Rust unit cases and the installed consumer without SDKs; it is not portable/full-GUI qualification |
| GNU/Linux aarch64 | Final `41d28fe` native ARM64 Bookworm lane passed the same declared source/backend/package/consumer/ABI/browser/recovery gates. This is native execution with the matching retained extension, not x86_64 emulation; other environments need separate qualification |
| Windows x86_64 MSVC | Final `41d28fe` native lane passed source/GUI/browser/package and all six installed backend gates, seven Debug CTests/static-CRT checks and bounded disconnected core/consumer/package verification. The matching retained extension and Microsoft host-tool/dependency-base closure remain required. Full offline GUI regression and older-client compatibility remain separate |
| Browser wasm32 | Exact Rust 1.63.0 / Emscripten 6.0.10 pair passed final `41d28fe` source/core/package/consumer/replay/disconnected gates and actual Firefox/Chromium application checks, with 30 renderer-isolation cases per engine. Mobile, other engines/devices and other compiler pairs are unqualified. Native Wasm objects, panic abort and no cross-language LTO remain required |
| Arduino and other targets | No implemented Rust profile or qualified board port; use the C++ route and the selective-porting policy below |

See the [current Rust release and integrated-package record](validation.md#rust-all-gui-release-and-integrated-packages-2026-10-06)
for the published four-target application, all 19 GUI backend-target bindings,
complete certificate and native installation/upgrade results. It distinguishes
each release's immutable application, qualifier and packager sources; all bind
`91dd1392…` in the current qualified run.
The historical table above and [earlier Rust validation record](validation.md#optional-rust-qualification-2026-10-04)
retain their original source, recipe, package and receipt identities. See also
[the Rust implementation record](rust-hybrid-plan.md) for implemented scope and limits.
That historical `41d28fe` four-target hosted run passed with remotely retained
evidence; its final metadata inspection did not read back full payload bytes or
create a local accepted bundle. Later complete application-byte and certificate
readbacks are recorded separately in the current release record. Earlier
independent full-byte readbacks also keep their own identities.
Stable Rust 1.63 and edition 2021 are the component
baseline. SDK-free native development currently requires Debian-family package
ownership and complete notices; other Linux distributions or unowned tool
layouts use the retained extension. A newer identified stable compiler does not
establish Rust 1.63 execution or an older runtime floor. Retained
compiler executable host requirements and the final application's target
requirements remain separate, even for an allocation-free static component.

Windows uses Rust `+crt-static` with the project's static MSVC CRT policy.
Cooperating objects, including configuration-specific debug/release inputs,
must have compatible CRT requirements, and the selected native-static-library
receipt must reach the final C++ link. The Rust archive does not replace the
Microsoft compiler, Windows SDK or required system import libraries. Qualify
the exact native toolset and configuration before a Windows compatibility claim.
The recorded hosted checks reused installed Microsoft tools; they do not prove
installation or reinstallation from the retained Microsoft installer layout.

The Wasm profile does not qualify `std`, pthreads/shared memory, arbitrary
callbacks, cross-language LTO or another Emscripten version. Matching target
names alone cannot establish ABI compatibility across independently built
compiler libraries. Inspect the actual archive, final imports and executable
cases for the exact retained pair. The disconnected application and Node consumer
results establish their recorded build/core/package scope. The final hosted
Firefox/Chromium cases and the older local Firefox receipt have separate source
and evidence identities. Direct-file application cases are not whole-browser
network denial, mobile or assistive-device qualification. The existing C++
browser route remains available through explicit C++ selection.

Offline restoration from retained official tools, recovery of retained source
inputs, and compiler reconstruction from source are distinct promises. The last
is **UNVERIFIED** for this extension. See
[the Rust SDK recovery contract](sdk.md#retained-rust-extension);
application recovery with restored tools cannot satisfy compiler reconstruction.

## Arduino as a selective porting target

Arduino's longstanding role is an environment to which selected application
functionality can be ported. Maintain useful commonality with Arduino derivatives
so this example remains a practical starting point for those ports, including
multifunction display (MFD) menus and
[few-button interaction patterns](gui-boundary.md#few-button-framebuffer-controls).
Each derivative selects and adapts the functionality it needs to its board's
resources and services.

The scope is selective application porting, with reusable behavior and interface
patterns as the starting point. A concrete board port establishes its own build,
memory, driver and hardware qualification; this design intent alone does not
establish Arduino support for the complete desktop application or GUI stack.

## Linux runtime baseline

Choose the oldest maintained target runtime that the product intends to support.
Build against that target using a baseline builder or an isolated
[SDK sysroot](sdk.md). A newer compiler can generate code for an older target
runtime when its headers, libraries, linker defaults, and generated requirements
remain compatible. Setting an audit ceiling only detects excess requirements;
it cannot lower them.

Audit every executable and bundled shared library, including indirect
dependencies. Inspect ELF architecture, loader path, dynamic dependencies,
versioned runtime requirements, and RPATH/RUNPATH. Reject requirements above the
declared baseline and unsupported named ABI additions. Audit dynamically loaded
plugins too; dependency inspection alone cannot discover every library selected
at runtime. Keep an explicit inventory of such loads.

Do not bundle the builder's C runtime, system loader, or vendor device/graphics
drivers as a shortcut. Classify each dependency as application-owned,
redistributable compiler runtime, or deliberately host-provided. An exclusion
requires a documented host requirement and a test on a minimal target image.

An old target runtime is a compatibility decision, not permission to retain
known defects. Prefer maintained fixes within the chosen ABI family, pin their
exact source, and requalify the result. Record the target runtime's maintenance
and end-of-support plan. A glibc-based package does not promise musl compatibility.

## Staging relocatable Linux libraries

The retained Linux SDK includes its hash-inventoried `bin/patchelf`. Installation
uses that exact editor only when a copied supplier library has wholly empty
`DT_RPATH`/`DT_RUNPATH` tags. An empty `DT_RUNPATH` prevents inherited executable
RPATH lookup even though it supplies no directories; removing it lets the
application's `$ORIGIN/../lib/runtime` RPATH reach indirect private dependencies.
This follows [the baseline loader's lookup rules](https://github.com/bminor/glibc/blob/glibc-2.36/elf/dl-load.c).
Nonempty paths are never erased to make an audit pass. Absolute paths, empty
colon-delimited components and unresolved dependencies remain errors.

Only temporary installed copies change. `runtime-inventory.json` schema 2 keeps
`files` as the original supplier hashes used by notice collection, adds
`installed_files` for shipped hashes and records each transformation with both
hashes, original tags and the editor digest. Architecture, dependencies, loader
and ABI requirements must remain unchanged. SDK bytes and recipes stay intact.
A native non-SDK build needs distro-provided `patchelf` only if such empty tags
occur; an explicitly selected SDK editor never falls back to a host executable.
The final package must still pass full loader-closure and baseline checks.

## Enforced SDK input boundary

Direct CMake and the wrapper verify a selected SDK's complete retained inventory.
For Linux SDKs, the configured C++ compiler and sysroot must physically match the
manifest; enabling C additionally requires its declared retained C compiler.
Package discovery alone is insufficient: a cached library or imported target
can otherwise refer to a development host after a successful configure.

The final CMake target graph checks imported library locations, include paths,
link directories and target usage requirements. External library inputs must
resolve inside the selected sysroot. Includes may additionally resolve inside
the application source, its owned generated build tree or the explicitly
selected GUI source. Checks use physical paths, so a link inside a permitted
root cannot refer to a foreign host file. Generator expressions are evaluated
for the selected configuration before compilation and installation. Frozen
library digests and the SDK inventory are rechecked, detecting same-path byte
changes and a link retargeted after configuration.

Raw compiler/linker search overrides and target search options are rejected in
an SDK build; express dependencies through verified target include/link
properties instead. This keeps direct CMake, wrapper builds and installation
under the same boundary. It does not prevent a separately written custom command
from reading arbitrary host files: custom generators still need explicit,
reviewed build-host input contracts. Build tools run on the host, while headers
and libraries consumed as target inputs follow the sysroot policy.

Installed static archives and copied runtime libraries also carry their checked
notice closure, described in [building](building.md#installed-dependency-notices).
An SDK legal-info inventory and complete referenced license text travel with the
application package; unavailable terms fail package assembly rather than relying
on a later network lookup. These checks preserve the declared compatibility
baseline and do not relax redistribution gates.

## C++ and Windows runtimes

Choose static or shared compiler-runtime linkage deliberately. Static C++
runtime linkage can remove one host dependency, but it does not make every
other dependency static or remove the operating-system baseline. When loading
host plugins, avoid exposing a private older C++ runtime in a way that overrides
the runtime their own libraries need. Verify actual dependency resolution.

For Windows, document the minimum supported OS, architecture, toolset, Windows
SDK, and CRT policy. If the package uses shared redistributable runtime DLLs,
include them according to their redistribution terms or require a supported
redistributable installation. A DLL found in a system directory is not
automatically part of the operating system. If the project uses static CRT
linkage, compile all cooperating objects consistently and avoid incompatible
allocation ownership across module boundaries.

The supplied portable Linux policy probes the selected C++ headers for
`libstdc++` before applying GNU static-runtime flags. Compiler identity alone is
insufficient: Clang can select another standard library. A different library or
platform fails configuration until its runtime, notices and package policy are
explicitly implemented and qualified. The probe runs again after reconfiguration;
changing `-stdlib` or a toolchain cannot reuse a previous successful result.

Application targets retain `--exclude-libs,ALL`: symbols from every linked static
archive stay private, including GUI/toolkit dependencies and the GNU runtime.
Direct application objects can still export an explicit plugin API. The installed
`foundation_apply_runtime` helper hides only the static GNU runtime archives,
allowing consumer applications and libraries to choose which of their own archive
APIs to export. Both policies let host graphics plugins use their own shared
C++ runtime. The Linux `integration.cxx_runtime` fixture demonstrates the
bundled-runtime problem and an exported-static-symbol failure, then checks the
protected relocated application with the broader policy and a real installed
consumer with runtime-only hiding. No C++ objects or exceptions cross the
fixture's plugin interface; this does not qualify arbitrary cross-runtime
ownership or exception propagation.

Windows CLI arguments enter through the CRT's wide-character entry point and
are explicitly converted from UTF-16 to UTF-8. Invalid UTF-16 fails before record
creation; the application does not depend on the active ANSI code page or a
newer UTF-8 process manifest. The record contract remains printable ASCII: Unicode
and non-ASCII POSIX bytes fail without partial output. Wide argument conversion
prevents a Windows code page from silently replacing unsupported characters with
ASCII question marks that would otherwise be accepted. A Windows-only fixture
round-trips non-BMP Unicode through this same conversion helper and redirected
UTF-8 output, and checks invalid-surrogate rejection; it does not broaden the
application record contract. Windows console rendering is a separate scope.

When consuming archived MSVC-built dependencies, check the documented toolset
compatibility and use a sufficiently recent consuming linker and redistributable.
Treat link-time optimized objects as a separate compatibility constraint. The
compiler and Windows SDK are build prerequisites; do not redistribute them as
ordinary application dependencies. See Microsoft's
[C++ binary compatibility guidance](https://learn.microsoft.com/en-us/cpp/porting/binary-compat-2015-2017?view=msvc-170).

## Relocation and installation

A package is a complete directory: keep executables, private libraries,
resources, licenses, and metadata together. Resolve installed resources relative
to the installation, not the current working directory or source checkout.
Export CMake usage requirements using install-relative paths. The installed
developer package and runnable application may share a source release, but have
different consumers and dependency requirements.

After packaging, extract into a fresh directory whose path contains spaces.
Run it outside the checkout with development-library paths removed. For Linux,
test in the oldest supported runtime image without development packages. For
Windows, test without compiler directories on `PATH`. Verify application startup,
representative behavior, resources, error handling, and an installed library
consumer. If a GUI is enabled, test every shipped backend separately and apply
the shared [GUI boundary contract](gui-boundary.md).

Inspect the exact archives users will download, not just an install staging
directory. Verify archive and internal file digests, file permissions, complete
inventory, licenses, and relocatability after extraction. Do not execute
unverified downloaded bytes to discover their version.

## CPU, data, and platform boundaries

Portable release builds must not inherit `-march=native` or equivalent
builder-specific tuning. If an accelerated implementation is added, retain a
tested baseline implementation and an explicit capability check before dispatch.
Never infer execution support from compilation alone.

Use fixed-width types where persisted or exchanged data requires them; specify
byte order, length limits, encoding, and overflow behavior. Do not serialize
compiler struct layouts, native pointer sizes, or platform-specific path types.
Use filesystem APIs for path operations and preserve non-ASCII names. Document
case sensitivity, line endings, permissions, locking, atomic replacement, and
Windows long-path assumptions wherever they affect behavior.

Treat thread scheduling, timeout clocks, cancellation, environment variables,
locale, timezone, and current working directory as explicit dependencies.
Correctness tests should exercise these boundaries without weakening the public
contract to accommodate a different host.

## Evidence required for a compatibility claim

Retain source and artifact digests, complete dependency inventory, baseline
audit, target execution results, skipped scopes, and known limits. Emulation is
useful additional evidence but does not by itself qualify native GUI, driver,
timing, or device behavior. A container tests user-space compatibility against
the host kernel; document kernel coverage separately when relevant.

Repeat affected qualification after changing compiler, linker, SDK, runtime
linkage, dependencies, CPU flags, install layout, or minimum supported platform.
The [release procedure](releases.md) binds this evidence to the delivered files.

## Enforced baseline and runtime closure

The supplied Linux release baseline is Debian 12 Bookworm: glibc 2.36,
GLIBCXX 3.4.30 and CXXABI 1.3.13 for externally required runtime interfaces.
[`verify_abi.py`](../tools/verify_abi.py) reads ELF metadata without executing the
files. It rejects a wrong processor, excessive or unsupported named ABI
requirements, an unexpected loader, absolute/escaping runtime search paths,
incomplete non-system library closure and declared x86 instruction requirements
above the generic baseline. No ELF files is an error, not passing coverage.

A named ABI capability needs an explicit, supplier-documented minimum runtime;
never silently discard it or parse every nonnumeric requirement as acceptable.
The known `GLIBC_ABI_DT_RELR` capability maps to glibc 2.36, following the
[glibc 2.36 release notes](https://sourceware.org/pipermail/libc-alpha/2022-August/141193.html)
and the supplier's `elf/Versions` declaration. Its original name and effective
floor remain in the audit report. The same rule applies to SDK host tools,
target inputs and application binaries. A lower ceiling still fails, a newer
numeric requirement still wins, unknown names remain errors, and application
imports of private libc interfaces remain prohibited. The portable regression
builds a controlled versioned shared provider and a real ELF consumer with this
named import using baseline Linux tools on either architecture. It checks the
imported requirement, effective floor, private dependency resolution, rejection
below the floor, and consumer execution. This fixture tests ABI requirement
inspection; it does not establish actual glibc packed-relocation loading.
Qualification of generated packed relocations remains a separate check using a
linker that supports their generation for the target architecture, with the
exact toolchain and execution result recorded.

```sh
python3 tools/verify_abi.py /owned/extracted-package --processor x86_64 --output /owned/abi.json
python3 tools/stage_runtime.py --executable /owned/staging/bin/foundation-cli \
  --root /owned/sdk/target/sysroot --output /owned/staging/lib/runtime --processor x86_64
```

The collector searches only explicit target roots, follows dependency edges
recursively, rejects ambiguous providers with different bytes, and records each
copied file. It never asks a host package database to supply missing target
libraries. The narrow system allowlist covers the target libc/loader family;
additional host services require a deliberate contract change and tests.
Dynamically selected plugins still need an explicit inventory and host tests.

Static C++ runtimes remove a common deployment dependency but do not remove the
libc floor or shared-library ABI boundaries. Private libraries need appropriate
relative loader paths, and each final archive is checked after extraction.
Portable Linux executables use `$ORIGIN/../lib/runtime` with linker option
`--disable-new-dtags`, producing inherited `DT_RPATH`. That inherited path also
finds indirect private dependencies without modifying the retained SDK libraries.
Wholly empty loader-path tags may be removed from staged copies as described
above; the original supplier bytes remain retained and identified. An
alternative layout may use `DT_RUNPATH` on every dependent object, but an
executable's `DT_RUNPATH` alone cannot cover its libraries' children; see the
[loader search rules](https://man7.org/linux/man-pages/man8/ld.so.8.html).

The final audit follows every private dependency from each executable using
object-relative loader paths, checks indirect loads in their executable context,
rejects ambiguous providers, and rejects a library found only in an unsearched
directory. Libraries outside those closures need usable paths of their own.
The collector's `staged-requirements` result checks copied bytes and ABI limits;
it explicitly defers loader resolution until the complete package exists. Never
substitute that intermediate report for the final `target` audit.
`--host` auditing inspects SDK tools separately; target compatibility cannot
establish that a compiler starts on the claimed builder.

Windows archives also have an executable inspection path:

```powershell
python tools/verify_pe.py extracted-package --processor x86_64 --output pe-report.json
```

The helper parses PE headers and ordinary/delayed DLL imports without loading
application code. It checks architecture, declared minimum OS and package DLL
closure against a narrow OS allowlist. Static CRT policy rejects imports of
shared compiler runtimes, including DLLs found in System32. The layout follows
[Microsoft's PE format specification](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format).
A header/import inspection cannot establish the availability of every called
Windows API or dynamically selected plugin; clean-machine native execution is a
separate required scope.


## Build environment versus validation environment

The ordinary baseline developer build uses Debian 12 distro packages or the
selected no-cost Microsoft tooling under its applicable terms. Newer generated
SDK tools may be supplied to improve language support while retaining the older
target runtime. Record both host requirements and target requirements; none of
these choices requires shipping a browser with an SDK.

WebAssembly outputs execute in an end user's supported browser. The prepared
WebAssembly build SDK includes Emscripten, its compiler bundle, frozen compiler
cache and Node support runtime. Browser GUI validation separately uses installed
Chromium/Firefox or other declared hosts. Their executable versions and results
belong to validation evidence, and changing a validation browser does not by
itself change the compiled SDK recipe.


The all-GUI SDK profiles are selected explicitly in the [SDK profile table](sdk.md#select-a-complete-dependency-profile).
Native OpenGL dispatch needs a compatible host vendor driver; dynamic driver
selection is declared in SDK host-service metadata and exercised on the actual
validation host. Private library staging must not silently copy a builder's
vendor driver into an otherwise portable release.

GNU x86 instruction properties distinguish required instructions (`ISA needed`)
from optional dispatched implementations (`ISA used`). The package audit rejects
required x86-64-v2/v3/v4 instructions, while permitting optional implementations
in a baseline-compatible library. Wide tool output may place both properties on
one line; parsing must preserve that boundary. Changing audit implementation
changes future SDK producer recipe identities, but existing immutable SDK groups
can still be selected explicitly and rechecked by current consumer tools. Never
relabel their archived bytes or replace their original provenance.
