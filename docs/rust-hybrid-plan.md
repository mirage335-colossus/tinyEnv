# Default Rust/C++ implementation

Implementation date: 2026-10-04. This document supersedes the research proposal
written against `45b27ebc36feabdb772ae99edb2f86dca2c6b093`. The subsequent Rust-default
policy supersedes the original optional-provider decision; historical execution
records below keep their original source and provider identities. Implementation started
from `8854f4fb9026c21d72d9066f6afffca7bd17bf31`. Contracts and execution evidence
are separate below: existing C++ release evidence in [validation](validation.md)
does not automatically qualify Rust binaries.

## Decision

Rust is the default implementation of one shared application component in all
fresh configurations, including native and browser targets. The public C++ API,
application behavior, GUI feature layout and package formats are unchanged.
`--core-provider cpp` explicitly selects the complete legacy implementation and
performs no Rust discovery. The default fails clearly when its Rust inputs are
unavailable; it never silently changes provider. Unsupported Rust targets retain
the explicit C++ compatibility route without acquiring an unqualified toolchain.

The initial Rust component uses stable Rust 1.63, edition 2021, a format-3
lockfile and no external application crates. It has no build scripts, procedural
macros, allocator, OS calls, threads or retained pointers. CMake owns the final
link; Cargo is only a subordinate producer of an identified static archive.

This follows the kernel's incremental adoption and reviewed foreign interfaces,
not its build machinery or target promises. See the
[kernel abstraction guidance](https://docs.kernel.org/6.15/rust/general-information.html)
and [architecture restrictions](https://docs.kernel.org/rust/arch-support.html).
Safe Rust cannot repair invalid pointers from C++ or an unsound foreign interface.

## Why Rust Is The Default

An example's normal path influences how downstream application code grows.
Selecting the reviewed Rust boundary by default gives maintainers a working,
tested place to add suitable portable logic using safe Rust, with the existing
C++ GUI adapters and public interfaces. This aligns with
[NSA/CISA's 2025 memory-safety guidance](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4223298/nsa-and-cisa-release-csi-highlighting-importance-of-memory-safe-languages-in-so/),
which supports interoperability during gradual adoption, and
[ONCD's 2024 technical report](https://bidenwhitehouse.archives.gov/wp-content/uploads/2024/02/Final-ONCD-Technical-Report.pdf),
which recommends prioritizing critical functions when migrating existing code.

The initial boundary is deliberately small. After the caller establishes its
borrowed-buffer contract, slice iteration and validation run in safe Rust; the
single raw-pointer conversion remains reviewed unsafe code. C++ still owns
records, strings, allocation, state and GUI integration. Toolkit and platform
code also remain C++. The default establishes neither whole-application memory
safety nor a substantially Rust application. Future parsers, bounded state
transitions and selected MFD/menu logic are useful candidates when their real
contracts justify extending this boundary; backend adapters should continue to
implement generic capabilities.

The supplier and portability cost is controlled: stable Rust 1.63 source,
zero external application crates, retained target tools, frozen/offline Cargo,
one archive per compatible configuration and no Rust installation at runtime
or for installed C++ consumers. Bookworm distribution tools cover native
development; the exact retained extensions cover qualified release, Windows
and Wasm configurations. CMake/Python, runtime floors and Windows CRT policy
remain unchanged. Default builds do require an additional compiler and its
complete local inputs. SDK restoration and application building are verified
separately from compiler reconstruction, which remains unverified.

Incremental dependency tracking preserves the small development loop. The Rust
archive is reused by every selected frontend; changing only Rust component
sources rebuilds that producer and affected final links without requiring
unchanged C++ GUI library compilation. Input verification still runs. The
historical 8.372-second warm no-op below is not a C++/Rust comparison and does
not prove that added compilation always costs a few seconds. Use the
[warm measurement recipe](development-speed.md#measure-warm-iterations) with
matched source, configuration and inputs before claiming iteration-time,
review-effort or AI token savings. This policy is based on the available
integration and security direction, not an unmeasured performance promise.
The [subsequent local comparison](validation.md#measured-local-build-cost)
measured about eight seconds of added wrapper time for this small core-only
sample, including verification; it is not a cross-platform performance guarantee.

Memory-safety policy can inform customer requirements, but selecting a language
is not a compliance certificate. The
[CISA/FBI Product Security Bad Practices announcement](https://www.cisa.gov/news-events/alerts/2025/01/17/cisa-and-fbi-release-updated-guidance-product-security-bad-practices)
describes voluntary guidance, and the
[European Commission's CRA summary](https://digital-strategy.ec.europa.eu/en/policies/cra-summary)
describes risk assessment, vulnerability handling and conformity obligations.
These sources do not establish a blanket prohibition on C++ or demonstrate this
project's compliance. Evaluate actual contractual and legal obligations for a
derivative's product, market and delivery date.

## Shared component

```text
CLI and all selected shared GUI frontends
                  |
          foundation::Store
                  |
 foundation::detail::validate_text
                  |
       private versioned C ABI
          /               \
   C++ provider       Rust provider
```

The component validates printable ASCII text. Empty text, text longer than 256
bytes and bytes outside inclusive ASCII 32 through 126 retain the existing
errors. Length checks precede byte checks; validation precedes mutation. C++
continues to own strings, records, allocation, exceptions, IDs and GUI objects.
`include/foundation/store.hpp` is unchanged.

FLTK, Rev, SDL, TUI, framebuffer and hosted web all use the existing shared
application/core. Browser Wasm uses that same core in its existing Emscripten
module. No adapter duplicates validation or implements Rust-specific features.
Hosted web is a native server; browser Wasm is a separate target ABI.

### Foreign interface

`src/text_validation.h` is private, not an installed public API. It accepts
`const uint8_t *` and `size_t`, corresponding to `*const u8` and `usize`, and
returns a `uint32_t`/`u32` status:

| Value | Meaning |
| --- | --- |
| 0 | Valid text |
| 1 | Invalid length, checked first |
| 2 | Invalid ASCII byte |
| 3 | Null pointer with an otherwise acceptable length |

For an accepted length the caller must provide initialized, readable bytes in
one live allocation, unchanged for the call. Neither provider changes, frees
or retains that buffer. Invalid lengths are rejected before dereferencing or
constructing a slice. Pointer validity beyond null cannot be checked generally.
See the [slice contract](https://doc.rust-lang.org/std/slice/fn.from_raw_parts.html)
and [Rust FFI guidance](https://doc.rust-lang.org/nomicon/ffi.html).

C++ translates expected status codes to existing exceptions after Rust returns.
Unknown statuses fail closed. No strings, vectors, native enums, trait objects,
exceptions or language-owned allocations cross the boundary. This does not make
the installed C++ classes a stable cross-compiler ABI.

Production Rust is `no_std` with `panic=abort`, one code-generation unit and no
LTO. Its panic handler invokes a non-returning C++ `noexcept` abort hook. Expected
input errors return values; a panic terminates the process/module. No unwinding
or recovery crosses languages. The C++ forwarder and panic hook share a
translation unit so static archive extraction resolves the callback correctly.
Native Rust unit tests use a separate standard test harness/output tree; that
harness is not the production panic policy.

## Configuration

The supported wrapper selects `--core-provider cpp|rust`, default `rust`, and
`--rust-sdk /absolute/path`. Direct CMake exposes
`FOUNDATION_CORE_PROVIDER=cpp|rust` (fresh-tree default `rust`) and
`FOUNDATION_RUST_SDK_ROOT`. There is no
automatic provider. Missing tools, missing target libraries, changed identities
or incompatible SDK pairs fail; they never select C++ silently.

```sh
python3 tools/build.py test dev --core-provider cpp --build-dir build/cpp --label core
python3 tools/build.py test dev \
  --rust-sdk /absolute/rust-sdk --build-dir build/rust-dev --label core
python3 tools/build.py test release \
  --sdk /absolute/cpp-sdk --rust-sdk /absolute/rust-sdk \
  --gui --build-dir build/rust-release --test core.text_validation
```

Paths are already prepared inputs, not download requests. Windows uses
`--windows-dependencies` for prepared C++ dependencies. Browser builds pair the
Emscripten `--sdk` with its Rust extension. [Building](building.md) gives backend,
test and package commands. Changing provider/toolchain requires a fresh compatible
tree; native and Wasm ABIs necessarily use separate trees.

SDK-free native development currently supports Debian-family package-owned
`rustc`/Cargo and dpkg-backed complete notices. It is restricted to wrapper `dev`
without a target SDK or portable policy; other Linux distributions and unowned
tool layouts use the retained extension until an ownership/notice provider exists.
The receipt binds actual tools, target libraries, native link requirements and
notices. Only matched package-owned `libstd`/`libtest` links are accepted in this
native route; retained SDK target libraries still reject symlinks.
Portable/release, Windows and browser profiles require retained tools.
Rustup proxies are not accepted as selected compiler executables. Actual Rust
1.63 execution, not just `rust-version`, verifies source compatibility with the
[Bookworm compiler baseline](https://packages.debian.org/bookworm/rustc).
Record [Cargo's package version](https://packages.debian.org/bookworm/cargo)
separately from its executable version.

### Build and installation

One Rust archive per target/configuration is reused by every frontend. Debug
and Release have separate output directories, including multi-config CMake.
`tools/rust_build.py` binds source/manifests/lockfile, compiler, Cargo, target
libraries, flags, notices and output in a receipt. Only an explicitly registered
generated archive in the owned build tree is exempted from configure-time
imported-library hashing; all other SDK/imported-path checks remain.

Cargo runs with a private home/output directory, frozen inputs, offline mode,
explicit compiler/sysroot and one job. Ambient Cargo configuration, wrappers and
uncontrolled flags are rejected. Metadata verifies the exact dependency-free
workspace. No normal configure/build/test/package action acquires missing inputs.

Installation verifies the receipt and ships the finished Rust archive, native
link requirements and notices alongside the C++ archive. The installed CMake
package imports that archive before its exported core. It has no SDK/build-tree
paths or compiler-facing `.rlib` dependency and never invokes Rust tools.
Relocation tests shadow Rust commands with failing launchers. Consumers still
need a compatible C++ compiler/runtime, exactly as before.

The existing wrapper retains CPU/memory budgeting. Cargo's single job prevents
nested parallelism from multiplying the CMake budget. Existing process-tree and
Windows compiler-session ownership cover compiler subprocesses. Test discovery,
focused selections, disjoint shards and source-bound evidence reuse include the
new provider and inputs; different providers cannot reuse behavior evidence.

## Target contracts

| Target | Rust integration contract |
| --- | --- |
| Linux x86_64 | GNU target, generic CPU, existing glibc/private C++ runtime floors and final ELF audit |
| Linux aarch64 | Native GNU target and matching aarch64 libraries; x86_64 execution is not ARM runtime evidence |
| Windows x86_64 | Native MSVC final link, official MSVC Rust target libraries, existing static CRT policy and native execution |
| Browser wasm32 | `wasm32-unknown-emscripten`, exact Rust 1.63/core/builtins plus retained Emscripten 6.0.10 tuple, native Wasm objects, no LTO or pthreads |

CMake 3.24, Python 3.9 and existing Bookworm build-host/runtime floors remain.
Compiler executables have host requirements, and `no_std` alone does not prove
the final executable has no libc requirements. Final runtime audits still apply.
Other OSes/CPUs, musl, Windows ARM64 and Arduino firmware are not qualified by
this implementation. This narrower Rust list does not restrict the C++ route.

### Browser decision

There is no wasm-bindgen, `wasm32-unknown-unknown` substitution or second Rust
browser module. C++ and Rust code link into the existing application module.
Rust 1.63 uses LLVM 14 and the retained Emscripten SDK uses a newer LLVM; their
bitcode is not interchangeable. The link consumes native Wasm objects with LTO
disabled and fatal signature warnings. The exact compiler, libraries, SDK recipe
and exception/link settings form one qualification tuple. Upgrades require new
ABI and browser evidence, as cautioned by
[Rust's Emscripten guidance](https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-emscripten.html#emscripten-abi-compatibility).

## SDK and recovery

This task permits free-to-use official Rust distributions alongside distro and
Microsoft tools, superseding the proposal's distro-only supplier restriction.
No third-party application crate or repository is added. Acquisition is an
explicit SDK preparation operation, separate from ordinary application work.

`tools/rust_sdk.py` and `third_party/rust/*.json` define a separate extension.
`rust-sdk.json` records compiler, Cargo, target, host, licenses and a complete
inventory. Retained groups contain binary/source archives and checksums under
an exact recipe ID. Existing C++ SDKs retain their schema/identity; Wasm binds
the exact C++ SDK recipe as well.

```sh
python3 tools/rust_sdk.py fetch --recipe third_party/rust/linux-x86_64.json \
  --inputs /absolute/rust-inputs
python3 tools/rust_sdk.py prepare --recipe third_party/rust/linux-x86_64.json \
  --inputs /absolute/rust-inputs --output /absolute/new-rust-group
python3 tools/rust_sdk.py recipe-id --recipe third_party/rust/linux-x86_64.json
python3 tools/rust_sdk.py restore --group /absolute/rust-group \
  --recipe EXACT_RECIPE_ID --output /absolute/new-rust-sdk --execute
python3 tools/rust_sdk.py restore-sources --group /absolute/rust-group \
  --recipe EXACT_RECIPE_ID --output /absolute/recovered-rust-sources
```

Only `fetch` downloads. `prepare` needs all pinned supplier bytes already
present. Wasm also requires `--cpp-sdk /absolute/emscripten-sdk`. Source recovery
retains exact sources, supplier inputs, bootstrap metadata/binaries, recipes,
hashes and licenses. It is not a compiler build command.

Four distinct claims are recorded:

1. **Offline application build:** retained tools/targets run configure, compile,
   test and package with network access denied.
2. **Retained-toolchain restoration:** original binary inputs are verified,
   restored and executed without downloads.
3. **Source-input recovery:** exact retained source, vendored dependencies,
   supplier archives and stage0 inputs are recovered and checked. Reassembling
   the original supplier binaries from those inputs is not a compiler build.
4. **Compiler reconstruction from source:** compiler/LLVM/Cargo and their entire
   bootstrap closure are rebuilt and validated. This is not claimed here.

A source archive or `stage0.json` is not proof of compiler reconstruction. The
manifest states this bounded recovery scope. A complete source producer requires
separate qualification and considerably more resources.

Release metadata identifies the provider and Rust inputs. Application packages
contain finished binaries/archives and notices, not a runtime Rust installer.
Existing Debian, Arch and Gentoo mechanisms wrap verified payloads; package
installation requires no Cargo or crates.io. Rust retained groups accompany
dependency recovery inputs. Duplicate-target and promotion gates remain intact.
The original implementation task did not authorize stable publication or repository
promotion. The separately authorized [Rust release and signed channels](validation.md#rust-enabled-portable-release-and-signed-channels-2026-10-05)
record later publication and qualification with their exact source identities.

## Qualification evidence

Initial discriminating checks passed during implementation:

- Default C++ core tests with no Rust tools on the host PATH; missing-Rust and
  in-place provider-change rejection.
- Installed/relocated C++ consumer with Rust commands shadowed to fail.
- Existing C++ runtime fixture's dynamic/export negative controls, protected
  runtime and changed-header rejection after extracting the validator.
- Preliminary native Rust 1.63 Debug/Release and Multi-Config builds, six Rust
  unit cases, relocated consumers and unchanged archive/executable mtimes on a
  no-op build. These used evolving sources and a provisional SDK; their retained
  evidence is not relabeled as final source/toolchain qualification.
- Rust 1.63/Emscripten 6.0.10 mixed probe: 1,352 Node assertions, primitive ABI
  checks and intentional Rust panic reaching C++ abort.
- Actual Rust source, C++ bridge and exhaustive boundary tests linked and ran
  in Node in Debug and Release; retained SDK/cache inventories unchanged.
- Namespace/container adapter unit tests and a derived, verified Bookworm rootfs
  prepared without modifying the original boundary.

### Executed application qualification

The complete four-target
[`rust-qualification.yml`](../.github/workflows/rust-qualification.yml)
[run 37211392657](https://github.com/mirage335-colossus/software-foundation/actions/runs/37211392657),
attempt 1, passed at commit
`41d28fec5481c77fc5b20e20808405ff3f83707a`. Native Linux x86_64, native Linux
aarch64, native Windows x86_64 and browser wasm32 producers all succeeded, as
did verdict job `111473327645`.

| Final hosted scope | Observed result |
| --- | --- |
| Native Linux x86_64 and aarch64 | Each executed 116 passed source CTests, including four core, one Rust-unit harness and 52 application GUI tests. Actual Firefox interactions and all 30 renderer-isolation cases passed. Package/installed-consumer, six backend runtime, ABI, retained compiler-package replay and disconnected acceptance gates succeeded on their native Bookworm architectures. |
| Native Windows x86_64 | Full source/GUI/browser/package and all six installed backend gates succeeded; seven Debug CTests and static-CRT checks passed. Its bounded disconnected core/consumer/package gate completed. Full offline GUI regression and Microsoft host-tool reinstallation were not selected. |
| Browser wasm32 | 65 source CTests passed: four core, 51 tooling and ten controller/Node/integration tests, not ten browser frontends. Actual Firefox and Chromium Wasm application cases and all 30 renderer-isolation cases per engine passed. Retained compiler-package replay and disconnected acceptance completed. Native Rust unit/native install CTests were not scheduled for Emscripten. |

The proof consists of authenticated completed-job/run context, complete console
logs, executed fail-closed gates and immutable remote retention pointers. The
small manifests were locally SHA-256 checked; final archive chunks and per-file
payloads were not read back locally. The metadata records explicitly say
`full_payload_readback: false` and `bundle_accepted: false`; they do not grant an
additional qualification or accepted bundle receipt. The exact job IDs,
manifest hashes, observed counts and limits are in
[the canonical Rust validation record](validation.md#optional-rust-qualification-2026-10-04)
and `build/agents/rust-ci-hosted/run37211392657/final-evidence-index.md`.
Subsequent documentation edits do not change those source-bound evidence
identities. Final inner Python/Rust case totals and browser versions are not
inferred from uninspected payload metadata.

The local frozen checkout is
`e3ce53899b49915d466388fcdcafda71116f1b6686aaf4c264ff92a27347042e`.
The same checkout plus its retained GUI-source supplement has identity
`fc38ea4046a6cef53e00aae1e308b8de59e0bd0cc0d5429a6eb1efab69dbbfbf`.
These are different inventory scopes, not interchangeable source identifiers.
The snapshot records base commit `8854f4f` plus its exact implementation diff;
later workflow-only repairs do not relabel that original evidence.

The latest pre-policy default-C++ local check used committed
`41d28fec5481c77fc5b20e20808405ff3f83707a`, source inventory
`3cbb6adb3b6959721bb7cad1f2ddda31c7d93c8cc486b8c4ebbe41c9bf7618fb`.
It passed all 65 CTests and 1,533 Python cases in 58 suites, with the same three
explicit native-Windows exclusions, no nonpassing cases and no runtime skips.
The host had no `rustc`, `cargo` or `rustup` on PATH. The same clean commit passed
the separate SDK-free Bookworm Rust development scope described below.

The retained-extension Debug check remains bound to
`6455ee46d3eaa505f6935b4b9c2ad3efd65d3b0e`, source inventory
`a7be2688618648eb63225cb5064fef09b21c2d48b079d18ceead5f4d82213c4d`.
It passed four core CTests, the six-case Rust unit harness and the relocated C++
consumer with Rust tools shadowed to fail. Its no-op wrapper
build retained identical archive, receipt and executable timestamps and sizes;
the measured wrapper time was 8.372 seconds, including input verification, not
a claimed improvement over C++. That retained-extension check is host-development
coverage, not new Bookworm or hosted-platform qualification.

| Scope | Observed result |
| --- | --- |
| Original frozen default C++ checks | 65 CTests passed on the host without Rust commands on PATH; 58 Python suites contain 1,498 passed cases. These retain the original `e3ce5389` inventory; the later 1,533-case result above has its own identity. |
| Debian distro-tool development | Clean `41d28fe` passed six CTests: four core tests, six Rust unit cases and the poison-tool relocated installed consumer, without C++ or Rust SDKs. Actual Bookworm packages were rustc `1.63.0+dfsg1-2` and Cargo `0.66.0+ds1-1`; the executables reported rustc 1.63.0 and Cargo 1.65.0. The normal planner and changed-compiler rejection passed in the denied namespace; source/rootfs/retained-input rechecks passed. No portable, GUI, package or full-tool-matrix result is inferred. |
| Distribution regression checks | Five additional suites, 148 cases, passed with no exclusions. Temporary signing agents required execution outside the outer sandbox; no host package installation or keyring changes occurred. |
| Disconnected native Bookworm | Rust 1.63 release/portable build of all six backends, four core tests, TGZ packaging, ELF runtime-floor audit, installed C++ consumer and all six installed backend smoke checks passed. |
| Disconnected browser Wasm | Existing mixed application module built with the pinned pair; four core tests executed in Node; TGZ packaging and installed CMake/Node consumer passed. This is not a real-browser interaction claim. |
| Actual Firefox application | Firefox 153.4.0esr on Debian 13 passed HTTP and direct-file Wasm, each standalone and isolated; all 30 renderer-security cases and six additional input-error cases passed. Ten screenshots and exact input hashes are retained. Browser sandboxing remained enabled. |
| Actual distro payload projections | Seven core/backend projections through Debian, Arch and Gentoo preserved all Rust archive/notices; 21 extracted CLI checks and three linked C++ consumers passed. Arch install-body execution and modeled Gentoo helpers are not native package-manager transactions. |
| Actual Debian transactions | In a fresh disconnected Bookworm rootfs, all seven packages installed/configured, their complete payloads matched, 28 CLI checks and six public backend smoke checks passed, and removal/purge restored the original package inventory. An additional GCC 12 C++ consumer passed with explicit `-no-pie`; default-PIE consumption with that different compiler is not qualified. No Rust tools were installed. |
| Retained native toolchain recovery | Source-input recovery and offline regeneration from the original supplier archives reproduced all three retained-group hashes; restored compiler/Cargo executed successfully. Compiler reconstruction from source was not performed. |
| Trusted native Windows lane | Run `37206730598` at `3f70889` passed 102 source CTests, including 49 application GUI tests, and 1,164 Python cases with 64 explicit platform exclusions. Seven Debug CTests, static-CRT audits, all six installed backends and Firefox 156.0.1 hosted standalone/isolated checks passed. Bounded disconnected retained-input recovery, five core CTests, installed consumer and package verification completed; full offline GUI regression was not selected. This successful lane is not the failed matrix's four-target verdict. |

The original local retained-SDK Linux/Wasm cases used fresh homes/caches/output,
read-only source, retained groups and restored SDKs, loopback-only networking and zero effective
and bounding capabilities. External connections failed and attempted writes to
the Rust SDK failed with `EROFS`. Final rootfs and retained-input rechecks passed.
The complete local acceptance receipt is
`build/agents/rust-hybrid-root/offline-final/acceptance.json`, SHA256
`6c6c3d1d12984ab00ab8ce329c3ee04f3c4042939a96560b19005d98446e1df8`.
Per-target commands, compiler identities, recipes and package hashes are in its
`linux-x86_64/execute.json` and `browser-wasm32/execute.json`.

Firefox evidence is in
`build/agents/rust-wasm-browser-local/qualification.json` (SHA256
`4bc0d292e57ac9fd8577ad3f929fbdab49b17cd152b4bec657a1a791427984e5`).
It covers a desktop Firefox window, not Chromium, mobile devices or whole-browser
network isolation. Distro projection evidence is in
`build/agents/rust-package-qualification/qualification.json` (SHA256
`6e653c85b27f4500f033895f2bd80f099c8dc4a8e8e591f6b6147a19cbc1ee42`).
Separate Debian transaction evidence is in
`build/agents/rust-debian-transaction/evidence-v3/qualification.json` (SHA256
`def97e27464050846f09a9d42525f05d1179764db4672729629eb6bf8fc96abe`).
Its disposable rootfs used an explicit manpage path-include to override the
Debian slim-image exclusion, preserving complete payload assertions. The
additional distro-compiler consumer does not broaden the existing matching-SDK
C++ consumer contract; no `-no-pie` requirement is exported to consumers. Native
Arch/Gentoo transactions, APT repository retrieval, upgrades, signing and
repository activation were not performed.

The clean Debian distro-tool receipt is
`build/agents/rust-distro-native/attempt-v3/evidence/qualification.json`, SHA256
`81f7eae4b6d567b1c4905d8a153e8c446c45c381856fdce719773f2f0e8e3e17`.
Its prerequisite receipt distinguishes explicit Debian package preparation from
the ordinary build, which acquired nothing. Use the focused commands in
[building](building.md#optional-rust-validation-provider) to reproduce the
development selection with those prerequisites already installed.

The earlier accepted Windows producer is job `111452286607`,
[run 37206730598](https://github.com/mirage335-colossus/software-foundation/actions/runs/37206730598), attempt 1,
at commit `3f70889d0eab35af067f51c4bbf3281c120d5723`, source inventory
`1f1851daccd31f328d460491e138dd6c915e3a991decd552e719ee96a960ce88`.
Strict successful-producer transport verification checked the full context and
archive/file hashes; its retained manifest SHA256 is
`e0010181e1e4c96bce6ec899e8ff3d30a2eb8755f78f47cb61501b794bb5a9df`.
The detailed scope and recovery readback are under
`build/agents/rust-ci-hosted/run37206730598/`, starting at `windows-scope.md`.
Its owned firewall stage completed in about 209 seconds with external controls
denied, loopback working and the original firewall state restored. Those inner
counts and browser version retain their original `3f70889` identity.

The preceding complete four-target
[run 37209852887](https://github.com/mirage335-colossus/software-foundation/actions/runs/37209852887)
at `9860e00` also succeeded. Complete-byte local readbacks were accepted for its
Windows and both Linux bundles; its successful remote Wasm retention was not
accepted as a local bundle because the workstation full fetch timed out after
600 seconds. No workstation full-payload re-download is an extra hosted gate.
Earlier cancelled runs `37200078067`, `37201305850` and `37205559015` remain
forensic-only; the successful `3f70889` Windows lane was part of an otherwise
failed matrix. Later successes do not retroactively qualify those producers.
Full Windows offline GUI regression, Microsoft host-tool installation from
retained media, older operating-system floors and unexecuted targets remain
separate. Compiler reconstruction from Rust source remains **UNVERIFIED**.
Those historical qualification runs make no stable publication or distro-channel
promotion claim. The [later release record](validation.md#rust-enabled-portable-release-and-signed-channels-2026-10-05)
records the separately executed delivery gates. Unexecuted, skipped or
compile-only targets are not runtime passes.

## Future portable logic

Arduino is not an implementation target. The bounded byte/status leaf and C++
equivalent are a starting point for selected firmware functionality, not the
entire desktop Store or GUI stack. Future MFD menus/state transitions should
use explicit bounded inputs/outputs behind the feature abstraction, with board
adapters providing display, input and device services. Each board needs its own
memory, target-library, interrupt, panic and mixed-link qualification.

Expand Rust where a meaningful component benefits from its ownership/type
checking. Measure iteration time, test cost, review effort and defects before
claiming fewer AI tokens or lower maintenance. Two providers and another SDK
have a real cost. Agents must coordinate shared ABI/build invariants and freeze
relevant inputs during qualification under the existing
[coordination policy](agent-coordination.md).
