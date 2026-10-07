# Remaining native offline platform qualification

Implementation started from `2cc4ea9fddddcb2ea963a56de6b9b375a09a83fd`.
The new disconnected-build input contract preserves Linux x86_64, Linux aarch64,
browser wasm32 and native Windows x86_64 support. It does not introduce cross-host
SDK support. See [disconnected builds](../docs/offline-builds.md),
[SDK use](../docs/sdk.md) and the current [validation record](../docs/validation.md).

The x86_64 Bookworm native case passed SDK restoration, a fresh application build,
core tests, portable packaging, installed consumer, ABI audit and all six installed
GUI smoke checks. Its original immutable source and per-phase receipts are under
`.agent-work/artifacts/sol-ultra-implementation-v1/offline-bookworm-final/`.
Those receipts retain their original source identity; they are not evidence for a
later changed source snapshot. Wasm and browser results are recorded separately in
the validation record.

Qualification is revision- and scope-specific. The optional Rust four-target
matrix at `41d28fec5481c77fc5b20e20808405ff3f83707a` completed successfully in
[run 37211392657](https://github.com/mirage335-colossus/software-foundation/actions/runs/37211392657).
Both native Bookworm architectures passed source/all-six-backend, package,
installed-consumer, ABI, browser, retained-package replay and disconnected gates.
The native Windows source/GUI/browser/package, Debug/static-CRT and bounded
disconnected core/consumer/package gates passed. Wasm passed its declared
source/core/package/consumer/replay/disconnected scope and actual Firefox and
Chromium application/renderer checks. Native ARM64 was executed, not emulated.
See the [current Rust record](../docs/validation.md#optional-rust-qualification-2026-10-04)
for precise counts and immutable evidence pointers. These results do not relabel
older C++ receipts. Final complete console/job evidence and SHA-verified small
manifests are local; payload bytes remain remotely retained without a final local
full-byte bundle acceptance claim.

The later [Rust release record](../docs/validation.md#rust-enabled-portable-release-and-signed-channels-2026-10-05) includes
Rust/offline qualification at `e260ab0f3f2bf44ea70dffbc906b141cf1b671f5` in
[run 37240910392](https://github.com/mirage335-colossus/software-foundation/actions/runs/37240910392),
with successful Windows attempt 2 and the other three targets at attempt 1.
Its reuse for application `13ed8311dc28e7951ed0b2fbd72f3eeae88a9351` is limited
to independently verified identical relevant implementation; it is not exact
13ed or later qualifier execution under an OS-level network block. The complete
fresh all-GUI certificate and signed-channel native checks have their own sources
and scopes. The current release record preserves all remaining limits below.

The following broader scopes were not selected and are not implied by those passes:

- Full native Windows x86_64 offline GUI/host-bootstrap scope: a supported Windows
  host, the complete Microsoft offline installer layout and selected compiler/Windows SDK
  components, plus the retained dependency group matching recipe
  `da0aa41ad58536497e23503b4ca778521e47cbd412c5b944490aa3c4d535bf0a`.
  Follow the existing [Windows offline prerequisite procedure](../docs/sdk.md#windows-dependency-base-and-separately-installed-host-tools)
  with external networking unavailable, fresh build/HOME/temp directories and
  no undeclared caches. The Linux Bookworm namespace launcher is not a Windows
  isolation adapter. Record build, packaging, installed-consumer and all six GUI
  runtime results separately.

The declared four-target Rust qualification has no outstanding hosted job.
Broader Windows offline GUI/host-bootstrap work needs an explicit support claim
and qualification request before execution. The existing Microsoft prerequisite
procedure remains required; bounded checks reused selected installed host tools
and do not establish installation/reinstallation from retained media. Other OS
floors, devices and target/compiler pairs require their own scope. Retained
compiler-package replay is not compiler reconstruction from Rust source, which
remains **UNVERIFIED**. Preserve each newly executed result's source identity.
The historical offline results alone make no publication or promotion claim.
Later application and signed-channel publication is recorded in the linked current
release record; it does not expand offline GUI or host-bootstrap qualification.
