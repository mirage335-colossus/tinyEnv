# Validation record

This records observed checks of the generic reference implementation. Requirements,
workflow definitions and fixture success do not imply qualification on an untested
platform. Generated logs and temporary SDKs remain in ignored local output trees.
Release delivery must preserve its own exact, immutable input and evidence inventory.

The main environment is Debian 13 x86_64, GCC 14.2, CMake 3.31.6, Ninja 1.12.1 and
Python 3.13.5. Native GUI qualification also used an isolated Clang 19 toolchain,
verified toolkit inputs and a virtual display. A remote repository is configured.
Observed hosted results below identify exact revisions and scopes. Earlier
failures produced focused regressions and repairs; unqualified scopes remain
explicit. The current delivery record below distinguishes public publication from
earlier private preparation and local fixtures.

## Automatic CI draft cleanup (2026-10-06)

[Cleanup run 37410061631](https://github.com/mirage335-colossus/software-foundation/actions/runs/37410061631)
passed its single job on source `b4959a595b446c94bbf15b8fb8f7aec69571664a`,
attempt 1. The explicitly requested manual `expire_now=true` invocation removed
11 completed auxiliary draft releases and their 11 exact tags, covering 14,349,068
listed asset bytes. Preceding full-run Actions artifact pruning was skipped.

Independent readback found zero remaining numeric `ci-RUN-attempt-N` releases or
tags. All 10 public releases and all 455 asset identities, sizes and digests were
unchanged, including Latest release `404206667`, base, CI tools and galleries.
The manual entry point passed 29 expiry and 21 preceding-cleanup local cases,
pinned actionlint and documentation checks before dispatch. No application build
or release qualification was rerun. Daily cleanup retains its 24-hour grace;
the manual override waives only that wait and preserves the same input and
publication guards. This observation does not establish the separate SDK
same-slot retirement or preceding full-run artifact pruning scopes.

## Retired predecessor package channels (2026-10-06)

The user-requested cleanup subsequently removed the two published r5 predecessor
channels and their exact tags: `distro-0.1.0-x86_64-r5-s5` (release `403999768`)
and `distro-0.1.0-aarch64-r5-s5` (release `404001723`). The operation checked idle
workflows, complete frozen inventories, unchanged tags and non-Latest identity
before exact deletion, without replaying mutations. It retired 164 assets totaling
11,892,282,081 listed bytes. Independent readback confirmed both release IDs and
tags absent, zero numeric CI drafts, and all eight surviving releases and 291
asset identities, sizes and digests unchanged.

CI Tools stays at release `403986164`; its configured validator URL is unchanged.
Base `401599028` and Latest `404206667` remain intact. Current downloads and
retained certificate reproduction remain self-contained. The removed r5 package
URLs and fresh reproduction of those historical r5-to-r6 upgrades are no longer
available; future releases should use the current integrated application release
as their [exact predecessor](latest-release.md). No additional Actions run or
application rebuild was needed for this retirement.

## Rust all-GUI release and integrated packages (2026-10-06)

The cloud-built Rust/all-GUI application is certified and promoted to ordinary
public Latest. [Full workflow 37394012851](https://github.com/mirage335-colossus/software-foundation/actions/runs/37394012851)
passed all 65 jobs at attempt 1, with no failed, cancelled or skipped jobs.
Application, certifier, packager, promoter and tag commit all bind source
`91dd1392ce182dd6aeef6bf9e18c17cfb9786377`. This completes the speed and integrated
package qualification obligations; earlier failed candidates remain separate.

| Accepted identity | Verified result and public evidence |
| --- | --- |
| Application Latest | [release-37394012851-attempt-1](https://github.com/mirage335-colossus/software-foundation/releases/tag/release-37394012851-attempt-1), release ID `404206667`, 95 assets; ordinary public non-draft/non-prerelease, exact final readback passed. |
| Complete inventory | [release.json](https://github.com/mirage335-colossus/software-foundation/releases/download/release-37394012851-attempt-1/release.json), SHA256 `7a079a1d0c549520433e39bf9a8ee5e352921bba5b14106cb7644e2da4c5d0d0`. |
| Certificate | [public index](https://github.com/mirage335-colossus/software-foundation/releases/download/release-37394012851-attempt-1/certification-37394012851-attempt-1.json) and [complete evidence archive](https://github.com/mirage335-colossus/software-foundation/releases/download/release-37394012851-attempt-1/certification-37394012851-attempt-1.tar.gz); certificate SHA256 `78b4965293775ef1ddb6d3c7fc2f6b204027cb73f5b391ba4a030fd829cb0c8c`, passed/eligible, no experiment or adoption. |
| Signed integrated packages | [packages.json](https://github.com/mirage335-colossus/software-foundation/releases/download/release-37394012851-attempt-1/packages.json), SHA256 `ff9b6059f70824627ddee90cf190f5f7e72c8db35e83cc3e39f6512a2493a325`; independently trusted fingerprint `EF876322B5CE4782062CB3E991649063150BC781`. |
| Protected promotion | [promote job 112062936831](https://github.com/mirage335-colossus/software-foundation/actions/runs/37394012851/job/112062936831) and [final readback 112063056814](https://github.com/mirage335-colossus/software-foundation/actions/runs/37394012851/job/112063056814) passed after exact certificate and asset revalidation. |

All 106 mandatory logical checks passed across 66 distinct physical executions
in 23 transport batches. The complete bundle contains 107 reports, including
native packages, and 6,075 file hashes; no certificate omissions or warnings.
All eight native upgrades passed with fresh preparation in that same attempt.
The original named mandatory step metadata was complete and passed directly.

The independent final audit reconciled all 95 remote asset identities/digests
(6,127,014,318 bytes) and reproduced the complete public certificate. Its archive
is 22,302,836 bytes, SHA256
`f9558290c39c57effb24c5eeee1b61d845b30f85d8416febccd81aaf9f2417ef`.
Hosted publication/certification verified the application/SDK payload bytes;
this independent audit did not download those payloads again. It verified explicit
Rust identity on all four targets and 38 source/recovery provider bindings.
The exact retained SDK groups and source/delivery digests are in the public
inventory and certificate; previous SDK/offline results keep their original scope.

The release used retained SDKs and the Rust provider on Linux x86_64,
native Linux aarch64, Windows x86_64 and browser Wasm, profile `all-gui`, package
revision `6`, standard Linux pools and automatic capacity. Original application
archives/build records and every Rust identity are bound by the inventory and
certificate; package receipt consistency alone does not establish provider semantics.

The integrated inventory binds signed `packages.json`, both Linux native bundles,
combined APT assets and x86_64 Arch assets before application checksums freeze.
Native qualification covered install, payload/version verification, execution,
repository refresh, actual upgrade from the exact accepted predecessor and
uninstall: Debian Bookworm, Debian Trixie and Ubuntu 24.04 on both Linux targets,
plus Arch and Gentoo on x86_64. ARM Arch/Gentoo are outside this selected scope.
Both independent native reviews checked exact r5/r6 installs, all seven signed
backend payload anchors and the accepted predecessor selectors in `packages.json`.

| Native target | Passed frontend jobs in run 37394012851, attempt 1 |
| --- | --- |
| Linux x86_64 | Bookworm `112056756164`; Trixie `112056756199`; Ubuntu `112056756089`; Arch `112056756208`; Gentoo `112056756088`. |
| Linux aarch64 | Bookworm `112056756230`; Trixie `112056756122`; Ubuntu `112056756207`. |

See the [package contract](distribution-release.md#application-release-packages).

### Feature and safeguard scope

The completed performance work adds resource-aware workers and bounded release
discovery; remaining optional work is listed in [FURTHER-agents.txt](../FURTHER-agents.txt).
Automatic test/planner/tooling workers honor CPU affinity, container CPU/RAM
limits, retained growth headroom and scoped
nested worker budgets. Explicit operator limits and shared-resource locks remain.

Independent Linux source, recovery, archive and ABI checks share verified
read-only inputs/prepared images and keep writable outputs, containers and
displays separate. Handoff requires confirmed writer shutdown; failures aggregate
before evidence publication. Native Windows, host-browser and package operations
retain ordering. Source and reconstruction results retain separate identities.

Initial release discovery restarts a complete inventory at most twice only for
validated IDs repeated across different pages. It discards all earlier pages and
shares existing retry/time/wait budgets, with 768 total requests and 256 pages
per inventory. Successful initial discovery adds no calls or waits. Same-page
duplicates, malformed/access/ambiguous results and persistent repetition fail;
immutable publication and exact-ID final acceptance remain enforced.

Python loading registers imported modules to preserve ordinary fixture semantics.
Whole suites remain the scheduling unit. The local timing investigation did not
justify additional class workers; it does not claim measured hosted speedup.
Existing qualified assembly/retry reuse remains. Additional cross-run application
build reuse was considered but dropped because its conditional time savings did
not justify the added complexity and maintenance burden for this example.
See [development speed](development-speed.md).

### Development evidence

| Completed check | Scope and evidence |
| --- | --- |
| Initial local tooling snapshot | Initial implementation `3d1ba14a15df90910e18805b4eba948af630dc40`: all 66 complete suites, 1,855 cases and three explicit Linux platform exclusions, no accepted internal skips. The local ledger binds each changed-file SHA256 and selected rerun receipt. These original counts are not current `91dd` totals; final hosted regression establishes current qualification. |
| Rust development core | Four core suites passed; component ABI reports `provider=Rust`. Frozen archive/build identity remains in the root local validation ledger. |
| Linux headless editor | All ten supported-wrapper suites passed; 252 input files unchanged across execution. `.agent-work/artifacts/further-pending-20261005/editor-run.json`. This establishes the recorded Linux authoring/runtime/application fixture scope. |
| Early native Windows | [37352186436](https://github.com/mirage335-colossus/software-foundation/actions/runs/37352186436) and [37352211039](https://github.com/mirage335-colossus/software-foundation/actions/runs/37352211039), attempt 1, source `946007da9328e78cdc1380cd0238c9740f435042`: planner 54/54 and orchestration 116/116, no exclusions/skips. Complete authenticated receipts: `.agent-work/artifacts/further-pending-20261005/hosted/summary.json`. |
| Portable signing contracts | [37387186519](https://github.com/mirage335-colossus/software-foundation/actions/runs/37387186519), attempt 1, exact `d0a6c3f…`: twenty cases, no errors/failures/exclusions/skips on native Windows CPython 3.14.7 x64; all 620 maintained source files match. `.agent-work/artifacts/further-release-audit-20261005/host-contracts-37387186519-final-verification.json`. |
| Portable-fixture feedback | [37387167002](https://github.com/mirage335-colossus/software-foundation/actions/runs/37387167002), attempt 1, exact `d0a6c3f…`: all four jobs green. |
| Current development feedback | [37393752282](https://github.com/mirage335-colossus/software-foundation/actions/runs/37393752282), attempt 1, exact `91dd1392…`: all four jobs green. This does not replace final certification/promotion. |

The initial local ledger (`.agent-work/artifacts/further-root-20261005/local-validation.json`)
preserves original GPG-helper sandbox failures and complete
authorized reruns, and the earlier CI-plan fixture failure with its complete
repaired rerun. The three exclusions concern native Windows delete-pending
directories, selected-linker identity and Job Object containment. Workflow lint,
documentation and whitespace checks passed. Docker execution is hosted evidence.
Overlapping focused cases and wrappers are not additive assertion totals.

### Cloud prerequisites and screenshot provenance

The retained [actionlint prerequisite](https://github.com/mirage335-colossus/software-foundation/releases/tag/ci-tools-actionlint-1.7.12-20261005),
release `403986164`, preserves the pinned official binary, source, MIT license,
provenance and checksums. All five exact readbacks matched; no local rebuild.
See `.agent-work/artifacts/further-validator-20261005/completion.json`.

The repaired GUI group `bf9a364b…` was fully published by
[maintenance 37363634930](https://github.com/mirage335-colossus/software-foundation/actions/runs/37363634930),
attempt 3, source `2e33720a73f0686dc1ffe72992dfb52e472cd059`; all 24 existing
C++/Rust SDK assets survived unchanged. Serialized
[native Windows 37363626265](https://github.com/mirage335-colossus/software-foundation/actions/runs/37363626265),
attempt 4 on that source, passed 104 unique JUnit cases with zero errors,
failures or skips, including relocated-SDK/all-native-GUI/full-source checks.
Exact group/archive/recipe/runtime identities and full retained bytes are bound
by `.agent-work/artifacts/further-release-audit-20261005/gui-bf9a-prerequisites-final-verification.json`.

Attempts 1/2 of those prerequisites executed zero steps during the retained
[Actions runner-allocation incident](https://www.githubstatus.com/incidents/3q1yb5m7ltvb).
Native attempt 3 executed zero tests: concurrent base GUI publication changed
the frozen complete inventory. Serialize base publication before SDK consumers;
preserve the guard that rejected the changed input.

The accepted predecessor channels were separately built from the already
certified `release-37245250573-attempt-1` after historical distro tags disappeared.
[x86_64 bootstrap 37352060627](https://github.com/mirage335-colossus/software-foundation/actions/runs/37352060627)
and [aarch64 bootstrap 37352082640](https://github.com/mirage335-colossus/software-foundation/actions/runs/37352082640)
passed at attempt 1/source `946007d…`, accepting respectively
`distro-0.1.0-x86_64-r5-s5` and `distro-0.1.0-aarch64-r5-s5`.
Final upgrade receipts bind those exact frozen manifest selectors; these
channels do not establish upgrades from the deleted historical tags.
Both r5 channels were later [retired](#retired-predecessor-package-channels-2026-10-06);
the completed certificate retains their signed controls and upgrade receipts.

[Fresh screenshots 37383282720](https://github.com/mirage335-colossus/software-foundation/actions/runs/37383282720)
passed all three jobs at attempt 1/source `2e33720a…` and GUI group `bf9a364b…`.
[Public gallery 404150639](https://github.com/mirage335-colossus/software-foundation/releases/tag/screenshots-37383282720-attempt-1)
contains ten verified assets and seven inspected views, built by native/Wasm
cloud Rust providers. README integration is `cfcab000c8fcb96f8bf42677c7881ef6b3efafd9`.
[The current gallery manifest](screenshots/screenshots.json) binds every source,
SDK, binary and image identity. Captures retain 640×480 native/browser content
at scale 1/96 DPI and complete 80×31 terminal cells, border/status; no resampling
or content edits. Appearance only, not release qualification.

These fresh PNG bytes match the original gallery, whose distinct source/run
remain in [the original tagged manifest](https://github.com/mirage335-colossus/software-foundation/releases/download/screenshots-37352058694-attempt-1/screenshots.json).
Historical screenshot evidence is not linked to the newer current manifest.

### Failed attempts and focused repairs

Original source/attempt identities remain separate from later passing evidence.
No failed Latest below produced an eligible certificate or promoted a release.

| Original attempt and exact source | Failure and resulting repair |
| --- | --- |
| [37358862485](https://github.com/mirage335-colossus/software-foundation/actions/runs/37358862485), attempt 1, `2371ad4d820073919f7c38c68d3785ec2eaae632` | Complete source handoff measured 27,277,415 bytes and exceeded 24 MiB before application builds. `b6d192d5ce59039d19d552d119401ed7c40511c7` raises only the slot to 40 MiB; strict complete inventories and at least 100 MiB private Free reserve remain. Complete real-byte replay and artifact suite passed. |
| [37359677255](https://github.com/mirage335-colossus/software-foundation/actions/runs/37359677255), attempt 1, `b6d192d5ce59039d19d552d119401ed7c40511c7` | Application/Windows tooling failures exposed undeclared PyYAML cleanup wiring, ambient mocked package mode and actual FLTK prompt-focus race. `2e33720a73f0686dc1ffe72992dfb52e472cd059` makes cleanup tests standard-library-only, scopes fixture package mode, and guards three inbound retained-focus handlers. |
| [37383219288](https://github.com/mirage335-colossus/software-foundation/actions/runs/37383219288), attempt 1, `2e33720a73f0686dc1ffe72992dfb52e472cd059` | All four Rust producers/full candidate regression passed, but correctly selected protected environment resolved the signing key empty. Setup stopped before lifecycle assembly/publication; certificate/promotion skipped. `d4a94574129165264bce8b43b000a5ff0cbcb4da` adds optional callee declaration plus named caller secret mapping without changing protection or key guards. |
| [37385992507](https://github.com/mirage335-colossus/software-foundation/actions/runs/37385992507), attempt 1, `d4a94574129165264bce8b43b000a5ff0cbcb4da` | Windows signing-test setup inserted a synthetic oversized key into the real process environment, exceeding its 32,767-character limit before the guard executed. Remaining producers were cancelled. `d0a6c3f5cf2067fc843ab8c4d2c02a1cca9d7b70` isolates synthetic environments with ordinary dictionaries; production key bound remains unchanged. |
| [Diagnostic CI 37385654742](https://github.com/mirage335-colossus/software-foundation/actions/runs/37385654742), attempt 1, `cfcab000c8fcb96f8bf42677c7881ef6b3efafd9` | Three jobs passed; one signed-client test counted GPG subprocess polling in a global sleep mock. The test-only scoped transport clock in `d0a6c3f…` retains assertions and real subprocess timing. Passing development runs at other sources do not relabel this failure. |
| [37387659465](https://github.com/mirage335-colossus/software-foundation/actions/runs/37387659465), attempt 1, `d0a6c3f5cf2067fc843ab8c4d2c02a1cca9d7b70` | Signing, candidate publication/readback, full regression and all eight native upgrades passed. Sole qualification failure was ARM Ubuntu Firefox startup at the 20-second bound, before GUI assertions. Complete failed certificate reproduced: ineligible, promotion skipped, old Latest unchanged; terminal jobs 60 success/3 failure/1 skipped. |

The standard-library cleanup repair rejected eleven unsafe workflow mutations;
hostile ambient package mode remained isolated. The final actual dialog-hide
focus regression fails against the original adapter while preserving clipboard/
focus checks. These focused evidence counts are not added to the tooling total.

[Hosted boolean probe 37385671588](https://github.com/mirage335-colossus/software-foundation/actions/runs/37385671588)
passed all five jobs/source `cfcab000…`: direct presence true, undeclared-unmapped
false, declared-unmapped false, declared-named-mapped true; agreement passed.
No secret values/lengths, inherit-all mapping, signing or publication were exposed.
All three temporary diagnostics were removed. The clock investigation reproduced
global mock contamination with an actual timed-wait child and zero scoped mock
waits; the complete repaired signed-client suite passed without exclusions.

The [published d0 candidate](https://github.com/mirage335-colossus/software-foundation/releases/tag/release-37387659465-attempt-1)
(`404181190`) retains its failed certificate and exact inventory. All eight
native records bind that source/run/attempt, accepted target-specific r5 tags
and all seven signed backend payloads; they do not qualify the new `91dd` run.

[First probe 37392975669](https://github.com/mirage335-colossus/software-foundation/actions/runs/37392975669),
source `cd7a4cf5c97d758e5a0ae0a19490014dfc659846`, reproduced the timeout;
its longer trial's total elapsed time did not isolate automation connection.
[Fresh paired probe 37393372940](https://github.com/mirage335-colossus/software-foundation/actions/runs/37393372940),
source `e852b1c5d0efb4ee6e3c82413c0ab044795f145f`, measured 21.582 seconds
to connect under a 120-second bound; the separate 20-second control took 7.830.
Both used the same native Firefox 156 executable digest as the failed check;
complete small artifacts were verified. Startup variation exceeded the old bound.

Probe CI [37392948056](https://github.com/mirage335-colossus/software-foundation/actions/runs/37392948056)
correctly rejected direct artifact upload bypassing the storage guard. The bounded
adapter repair passed [37393335345](https://github.com/mirage335-colossus/software-foundation/actions/runs/37393335345).
Final `91dd` changes only Firefox startup to 120 seconds; protocol/application
waits remain bounded and unchanged. GUI boundary 41/41, storage 39/39, lint of
21 workflows, docs and independent review passed; temporary probes were removed.

### Cleanup evidence and retained limits

The successful current attempt precisely removed nine temporary artifacts after
their final consumers succeeded: three package handoffs, source/four application
handoffs after publication/readback, and certificate handoff after verified public
attachment. Complete authenticated inventory confirms every selected ID absent;
all 52 surviving artifacts are nonexpired and bind the current source/run,
including final verification and promotion evidence. The base's 27 assets, both
accepted predecessors' 82 assets each and the current gallery's ten assets retain
exact public identities, sizes and digests.

[Ordinary completion hook 37399475439](https://github.com/mirage335-colossus/software-foundation/actions/runs/37399475439)
passed with current source-run ID `37394012851`, status `complete`,
`previous_run_id: null` and zero selected/deleted artifacts, drafts or tags.
This establishes the first marked successful full-run baseline; it does not
prove preceding-run pruning. Prior failed/cancelled hooks skipped correctly.
The failed d0 attempt's separate nine cleanup removals retain their own identity.
GUI replacement is separate from unexecuted C++/Rust SDK same-slot replacement.
Next eligible full-run pruning, SDK retirement and inaccessible private Packages/
billing/zero-overage checks remain [pending](../.agent-pending/cleanup-capacity-hosted.md).

Optional editor Windows/ARM64/disconnected interaction remains
[pending](../.agent-pending/editor-platform-qualification.md). Full Windows
offline GUI and Microsoft installer host-bootstrap remain separately
[pending](../.agent-pending/offline-platform-qualification.md). Headless editor,
screenshots and ordinary online release do not expand these scopes. Rust
compiler reconstruction from source remains unverified without named evidence.

Local independent audit receipts retain their scope in
`.agent-work/artifacts/further-release-audit-20261005/latest-37394012851-attempt-1/final-verification.json`
and `.agent-work/artifacts/integrated-package-review-cleanup-20261005/` native,
cleanup and survivor readbacks. Failed d0 certificate and Firefox timing receipts
retain their original sources. Public accepted evidence is linked above; local
receipts do not substitute for its complete certificate and inventory.

## Application-release package layout: qualification deferred (2026-10-05)

The following dated sections preserve historical results and pointer identities
at their original recording time. The current qualified Latest is recorded in
[the completed integrated release above](#rust-all-gui-release-and-integrated-packages-2026-10-06).

The source change based on `c88fb7988037d38ca1685f9a22ff0ea604b04179` moves signed
APT/Arch packages and per-target native bundles into the next application
candidate before its inventory and checksums are frozen. The intended complete
release certificate requires all eight native frontends and exact predecessor
upgrades before promotion. APT/pacman use `releases/latest/download`; Gentoo
discovers Latest and then pins the exact tag. See the
[package contract](distribution-release.md#application-release-packages).

This is implementation scope, not execution evidence. The user requested source
changes for the next rebuild and excluded test executions, Actions runs and live
consolidation. No new package build, signing, certification, native installation
or upgrade, publication or Latest change is claimed here. Static integration
review completed: 17 changed/new Python files and 24 embedded Python blocks parse
with Python 3.9 grammar, four workflow YAML files parse, local reusable-workflow
inputs match their declarations, and `git diff --check` passes. Added regression
cases were unexecuted at this source. Complete release/native qualification was
then deferred; [the later integrated release](#rust-all-gui-release-and-integrated-packages-2026-10-06)
records its successful execution at `91dd1392…` and resolves that obligation.
Historical mirror and immutable-channel results below retain their original
identities and limits; they are not relabeled as new-layout qualification.

## Stable package repository URLs (2026-10-05)

This historical deployment record is preserved. Its separate mirror design is
superseded for future rebuilds by application-release packages; removing its
source helper and workflow route did not mutate any published release or asset.

The permanent [x86_64 repository](https://github.com/mirage335-colossus/software-foundation/releases/download/packages-x86_64/INSTALL.md)
and [aarch64 repository](https://github.com/mirage335-colossus/software-foundation/releases/download/packages-aarch64/INSTALL.md)
are public and linked from application Latest. Release IDs are `403414270`
(40 assets) and `403416008` (22 assets). All signed mirror assets match the accepted
immutable channels identified below; no package was rebuilt or resigned. Both
mirror ledgers have `pending: null`. Application Latest remains `403269840`, with
39 assets and the same application inventory and successful certificate digests.

The manual `mirror_only` route was added in
`e5022ab7a748d1fdba0b047bdb8902db02e0d5f6`, following mirror implementation
`84a599e2d4608bd7b6acbd992939f62b574c7c73`. It uses the protected publisher
environment, existing lifecycle lock and a 15-minute job ceiling. The sole required
job is `mirror`; its every step passed. `plan`, `install` and `accept` were
intentionally excluded and reported skipped, not counted as new qualification.
Original exact-package native acceptance remains run `37253584672` for x86_64 and
run `37257537261` for ARM, with their original source identities and receipts.
No build, certification or long native matrix was launched for this publication.

| Publication | Successful workflow, attempt 1 | Job duration |
| --- | --- | --- |
| x86_64 initial mirror | [37271199227](https://github.com/mirage335-colossus/software-foundation/actions/runs/37271199227), job `111638369959`, source e5022ab | 109 seconds |
| ARM APT mirror | [37271430425](https://github.com/mirage335-colossus/software-foundation/actions/runs/37271430425), job `111639079457`, source e5022ab | 108 seconds |
| x86_64 instructions correction | [37271683693](https://github.com/mirage335-colossus/software-foundation/actions/runs/37271683693), job `111639833170`, source c3b889b | 93 seconds |

Live inspection found that the original Arch instruction template stripped its
trailing slash, so the mirror's URL substitution missed its `Server` line. Fix
`c3b889b5327397828ce3bcb75594b092913c816b` corrects the prefix substitution and
permits only generated `INSTALL.md` corrections within the same generation,
using the existing pending-state recovery. Both new regression checks reject the
old helper; nine mirror cases and one real signed acceptance fixture passed with
zero skips. YAML, embedded Python, route isolation and documentation checks passed.
Final remote reconciliation confirmed that only `INSTALL.md` changed asset ID;
all 39 other x86_64 asset IDs, sizes and digests were preserved. Its corrected
instruction SHA256 is `f2e765b09e89230636cb454b9ec04054bfe9e1ebb2c9add6111385002ab0ca42`.

Short public client checks used isolated state on Debian 13.7 x86_64. APT 3.0.3
performed signed `apt-get update` and downloaded all seven variants for each of
amd64 `0.1.0+r4` and arm64 `0.1.0+r3`. All 14 package identities, `InRelease`
and decoded `Packages` matched the authenticated signed inventories. Each update
or download operation took under four seconds. Extracted pacman 7.0.0/libalpm
15.0.0 refreshed the signed stable database twice and downloaded all seven
`0.1.0-4` packages in 18.918 seconds. `Required DatabaseRequired` stayed enabled;
independent GPG checks also verified the database and seven package signatures.
Existing fakeroot satisfied pacman's UID check without OS privilege; all paths
were isolated, downloader privilege transitions disabled, and dependency
resolution omitted for download-only scope. No package was installed or launched.
Gentoo's public `track: qualified` discovery and authenticated native refresh
passed in 65.56 seconds, verifying all seven overlay recipes and generated sync
configuration. No new Portage execution occurred.

Initial sandbox DNS failures were setup failures, then resolved through authorized
network access. APT's absent empty preferences directory warning and pacman's
legacy public-keyring warning did not bypass signatures; exact-byte and independent
signature checks passed. These checks establish repository discovery, signatures
and downloads. They do not establish native ARM execution or new installation/
upgrade coverage. The existing native qualification is recorded below. The
previously deferred two-generation mirror upgrade and older-payload retention
obligation was superseded by the next application-release package layout; it
was not executed or counted as passed. The replacement full native/upgrade
qualification subsequently [passed for the integrated release](#rust-all-gui-release-and-integrated-packages-2026-10-06).
Arch/Gentoo support remains x86_64 only. Metadata expiry and non-atomic index
replacement describe the [historical mirror design](distribution-release.md#stable-package-mirrors).

Exact local evidence remains under `.agent-work/artifacts/stable-package-mirrors-live-20261005/`:

| Evidence | SHA256 |
| --- | --- |
| `final-audit.json` | `014438ae0fb0c2f7594b6b8c48771891f16539b74332466176ed8f334a22792a` |
| `instruction-validation.json` (final nine mirror cases, signed fixture and regression logs) | `a6ab0cba5f273c01ae704934b8a4f9e3c613e4de48439a3d238a69fe418ab92d` |
| `apt-probe/final-index.json` | `5ccf7f7cfcadd045632d97b482ffe6be853b7294e23e463425e013e4decc186c` |
| `arch-probe/result.json` | `98d7315a0c304c03d01d3832c996f33556d92fb691098c7c081c916b796bf816` |
| `gentoo-probe/result.json` | `d49e00cd7c16449ede63e905e9834ac4c92d283d597c2617f99c2012210f5b64` |

## Rust-enabled portable release and signed channels (2026-10-05)

This is the earlier release and separate-channel record at its original recording
time; [the current integrated release](#rust-all-gui-release-and-integrated-packages-2026-10-06)
supersedes its application Latest pointer without changing these accepted bytes.

The Rust/all-GUI application is certified and promoted to ordinary public Latest.
Its immutable application source is `13ed8311dc28e7951ed0b2fbd72f3eeae88a9351`;
the certifier, promoter and signed-channel packager source is
`e864abb9f9bc088ea5396b49b4f042614ceb343d`. These identities remain separate.
Both signed channels are public and accepted. The ARM native checker uses
`c45f8f3316d32986ad70e291f5bddb8d44ec7ae7`; its package bytes retain the e864
packager identity. The original ARM publication workflow failed after publication,
and successful fresh native qualification is recorded separately.

| Delivery gate | Verified identity and result |
| --- | --- |
| Public Latest application | [Tag `release-37245250573-attempt-1`](https://github.com/mirage335-colossus/software-foundation/releases/tag/release-37245250573-attempt-1), release ID `403269840`, 39 assets; immutable 13ed application |
| Complete standalone certification | [Run 37251267915](https://github.com/mirage335-colossus/software-foundation/actions/runs/37251267915), attempt 1 at e864; all 27 jobs and independent complete inspection passed |
| Protected promotion | [Run 37252930718](https://github.com/mirage335-colossus/software-foundation/actions/runs/37252930718), attempt 1 at e864; promotion and final independent Latest inspection passed |
| x86_64 signed channel | [Run 37253584672](https://github.com/mirage335-colossus/software-foundation/actions/runs/37253584672), attempt 1 at e864; all nine jobs passed, including publisher `111586011936`, five native clients and protected acceptance `111595732249`; release `403315362`, [tag `distro-0.1.0-x86_64-r4-s4`](https://github.com/mirage335-colossus/software-foundation/releases/tag/distro-0.1.0-x86_64-r4-s4), 82 assets |
| aarch64 original publication | [Run 37253586732](https://github.com/mirage335-colossus/software-foundation/actions/runs/37253586732), attempt 1 at e864; publisher `111586013358` failed after publication; release `403315776`, [tag `distro-0.1.0-aarch64-r3-s3`](https://github.com/mirage335-colossus/software-foundation/releases/tag/distro-0.1.0-aarch64-r3-s3), 82 signed assets reconciled; original qualification skipped |
| aarch64 fresh native acceptance | [Run 37257537261](https://github.com/mirage335-colossus/software-foundation/actions/runs/37257537261), attempt 1 at c45f; all five jobs passed, including three native clients and protected acceptance `111598380092`; existing signed channel accepted without rebuilding or resigning |

Application source archive SHA256:
`b348368cecb91c41073fb4bd0b9f7b57ad98794aafca0615c23a55116bca6171`;
supplemented source-tree SHA256:
`abb40b11887479294b9cdc1980455c1a7241d166ae71fa3951a19ea49b99adae`;
delivery SHA256:
`b77e66667cc410ec520daa9fb59ef3466ea39e4de195ee1e9edfd6bb3f3dd1c3`.
Application inventory SHA256:
`e5a142600dfc0484858110417d446de01c2a134962aa78c3f34befd64051eaef`.
Accepted certificate SHA256:
`6786f42481dec8944a3152ab24ad459349dfdaef769b2f1fb61db8c2ffb7cb73`.
The certificate was reproduced from public retained evidence; its complete archive
SHA256 is `3bfe3f1a7041d8b049a812bfdcc79fe721fa27844a956007bd9eec7d4cc8ed67`.

Complete certification covers 106 logical checks, 66 physical executions in 23
batches, eight source/recovery JUnit files and 424 inner tool reports: 11,762 passed
unittest case occurrences and 164 declared platform-exclusion occurrences, with
no required runtime skips, failed or incomplete outcomes. Eight installed and four
delivered consumers passed. Wrappers and inner case counts overlap and are not
additive assertion counts. Independent full application archive/member/export
inspection covered all four archives and 19 GUI backend-target bindings.
Every production target uses the Rust provider. Retained build configuration,
Rust static libraries, CMake exports and transitive C++ linkage agree with actual
Rust/C++ ABI execution and relocated installed consumers. Frontend execution and
package binding complement this evidence; no direct Rust marker in every frontend
binary is claimed. Compatibility baselines and dependency policy remain unchanged
(policy SHA256 `b0f65fdedef9d597d5423d5c1ca5d57b5c0fbb04137b2b2fc1fb2a813fdaa734`).

Qualifier development [run 37251218678](https://github.com/mirage335-colossus/software-foundation/actions/runs/37251218678),
attempt 1 at e864, passed all four jobs: 12 Rust fast CTests (Cargo unit outside
that label), four explicit C++ CTests, 43 shared GUI CTests, and 24 infrastructure
suites with 708 case occurrences and zero exclusions, failures or runtime skips.
Documentation links and workflow lint passed; this is development feedback.

SDK maintenance/publication [run 37235528096](https://github.com/mirage335-colossus/software-foundation/actions/runs/37235528096),
attempt 1 at `1b338e0e504a4e3c8ab6f0ba9f307f28e8ea32aa`, passed. Four C/C++
groups were reused and four Rust extensions newly published into `base` release
`401599028`; all 24 selected public asset digests matched eight publication receipts.

| Target | C/C++ recipe SHA256 | Rust extension recipe SHA256 |
| --- | --- | --- |
| Linux x86_64 | `3e7438a4b5ee7a4baf5d7abacbdd320087aab42f24ea021f0f023b61db55bb33` | `888eaacdca83ecc2d518a2062e13b65d43fdbe6188ee6daaf29713f2aabb13cd` |
| Linux aarch64 | `afe8d1ba004206fcf234376a2110e69c4e9e1ef6b373e7afe23afe8497f8e4de` | `7b930acdbda806699c5ac752dbb30d20000e6a74f4fa97560a8f96d56e33fa23` |
| Windows x86_64 | `da0aa41ad58536497e23503b4ca778521e47cbd412c5b944490aa3c4d535bf0a` | `e224a3b622d0af5e40b511d67f8bfa6426abdd35b54756cc7f6343d15c01eebe` |
| Browser wasm32 | `74f5153e31c23f899f01d8340ffa4aba7f5a8ed81b0db206e6da8a1b38ece541` | `f9e35b94f0f7c65b7f2c7fe6d8af2c93fee6056d572ed2943c2dc6ea81f609f4` |

GUI maintenance/publication [run 37234010192](https://github.com/mirage335-colossus/software-foundation/actions/runs/37234010192)
passed at initial source `4753bae990c3f73fcecdd0804321b6032946ff62`, with prepare
`111529422829` and publish `111529490015` completed successfully.
The GUI input group is
`7fca961e0e472f353e1f7332baca565f479ddc71ff82a33d6b1dbfb89009add8`.
Windows graphics asset `604977464` is pinned by SHA256
`3f3613adb43cfd0f2e665ce2400b130c275f0b3317cb3a05566320a3a67589ed`;
it supplies host qualification only and does not establish public redistribution approval.

Full Rust [candidate 37240914371](https://github.com/mirage335-colossus/software-foundation/actions/runs/37240914371)
and explicit C++ [candidate 37241363978](https://github.com/mirage335-colossus/software-foundation/actions/runs/37241363978)
each passed all 19 jobs and nine source scopes at e260, including coverage merge
and installed/package consumers. The explicit C++ run intentionally omitted 13
Rust preparation steps and exercised provider 0 without Rust SDK/unit requirements;
those omissions are not Rust production coverage.

Original Rust/offline qualification [run 37240910392](https://github.com/mirage335-colossus/software-foundation/actions/runs/37240910392)
remains bound to `e260ab0f3f2bf44ea70dffbc906b141cf1b671f5`: Linux x86_64,
ARM and wasm used attempt 1; Windows used successful attempt 2 after cancellation.
It passed 399 source CTest occurrences and 5,881 inner tool case occurrences
(1,587 distinct methods); 82 platform-exclusion occurrences covered 76 methods,
each executed on another applicable target. Seven Windows Debug and five bounded
offline consumer checks are outside the 399. The sole e260-to-13ed change adds
27 prose lines to `FURTHER-agents.txt`. Reviewed reuse supports unchanged relevant
implementation while preserving original source/run/attempt/receipt identities;
it does not establish exact 13ed offline execution.

Fresh 13ed application controls in [run 37245250573](https://github.com/mirage335-colossus/software-foundation/actions/runs/37245250573)
passed the nested candidate and all four runtime lanes, including 19 GUI bindings,
actual Rust/C++ ABI probes and package consumers. That original Latest run still
failed seven of 23 certification batches and did not promote. Successful full Windows GUI/backend and
Firefox execution is separate from the original e260 bounded offline
core/consumer/package evidence.

Focused application fixes were
`24435107d14da4d731876b65c01fc119942610a8` (installed consumer provider inspection),
`1b338e0e504a4e3c8ab6f0ba9f307f28e8ea32aa` (missing `iproute2` prerequisite) and
`e260ab0f3f2bf44ea70dffbc906b141cf1b671f5` (numeric CMake capacity and flat Rust
evidence retention). Later qualifier commit `561f4dbae0a10dc72359a937802b45fbea91cfe5`
added Node to browser archive prerequisites and removed transport `CONTROL_ATTEMPT`
from archived child tests; 162 focused tests passed. Its standalone
[run 37249070053](https://github.com/mirage335-colossus/software-foundation/actions/runs/37249070053)
passed all 23 batches but failed retention: 6,016 files required 23,500,974 bytes,
exceeding both the old 1 MiB manifest and 16 MiB certificate slot. Commit e864
raised only those limits to 2 MiB/24 MiB, with a 378 MiB aggregate below the
384 MiB ceiling; 146 focused tests passed, followed by fresh complete certification
and promotion. Failed original runs remain failures.

Signed requests preserve exact predecessors `distro-0.1.0-x86_64-r3-s3` and
`distro-0.1.0-aarch64-r2-s2`, the independently trusted signing fingerprint
`EF876322B5CE4782062CB3E991649063150BC781`, and complete derived notice lists
(152 x86_64, 151 ARM). Signed manifest SHA256 values are
`d9221f635cdd70d0d43909c445ad35a8b18b2e286d4cf93eca2fb2640f223842` (x86_64) and
`e7933abea7a4eeed1a8f3e19e4114145a660743b360b1ae4a368982238ccc083` (ARM).

The ARM publisher failed during final global release-inventory lookup after the
public PATCH, with `invalid or duplicate release inventory entry`. The offending
row was not retained, so its cause remains unresolved. Bounded reconciliation
verified all 82 public asset identities against failed-producer file hashes and
authenticated the signed controls; no completed publication receipt exists.
The skipped original qualification supplied no native receipts. Fix c45f changes
only the final publisher and native-acceptance confirmations to use their already
verified release IDs. Strict initial discovery and every identity, asset, body,
reference and non-Latest guard remain. Two real signed regression fixtures failed
at the original final lookup and passed after the fix; all 189 affected local
release/native/transport cases passed with zero skips.

Fix development [run 37257471699](https://github.com/mirage335-colossus/software-foundation/actions/runs/37257471699)
passed all four jobs at c45f: 12 Rust fast CTests, four C++ core checks, 43 shared
GUI checks, documentation and workflow lint, and 58 complete infrastructure suites
with 1,614 passed cases. Its three declared Windows-only exclusions concern
pending-delete directories, native linker-file identity and Job Object containment;
there were no unexpected runtime skips or failures.

All five x86_64 clients (Bookworm, Trixie, Ubuntu 24.04, Arch, Gentoo) and three
ARM APT clients (Bookworm, Trixie, Ubuntu 24.04) passed. Each exercised all seven
variants: core, terminal, framebuffer, FLTK, rev, SDL and hosted-web. Each performed
two installation rounds, first the exact predecessor and then the new version,
with one actual version upgrade. APT advanced x86_64 `0.1.0+r3` to `0.1.0+r4`
and ARM `0.1.0+r2` to `0.1.0+r3`; Arch advanced `0.1.0-3` to `0.1.0-4`, and
Gentoo `0.1.0-r2` to `0.1.0-r3`. Exact predecessor manifest hashes are
`383f1bc7e510bc2a375d86ab3364adc7af6507e85d1a8af1bb6ddea170816a32` (x86_64) and
`57d7632206b6a329d386a1b954d08a396acc2949291b578e19c5506d04966544` (ARM).

The audits verified authenticated complete native receipts, CLI/GUI/HTTP checks,
package contents, command outcomes/timings and joined display cleanup. Protected
acceptance recomputed payload identities and each whole canonical public marker
matched the native results. No required native job or step was skipped. Both
82-asset signed inventories, both 70-asset predecessor inventories, and public
Latest `403269840` with all 39 asset identities were preserved. A first local x64
comparison rejected increased embedded download counters; the retained diagnosis
proved only those volatile counters changed, and the corrected comparison retained
all stable release fields and exact asset identities.

Independent evidence indices below are retained under `.agent-work/artifacts/`;
public workflow and release links above preserve the hosted delivery provenance.

| Independent proof | Retained record and SHA256 |
| --- | --- |
| Complete certificate | `rust-sdk-inspection-20261004/latest-inspection-13ed/e864-run37251267915-attempt-1/public-certificate-replay/independent-candidate-certificate-inspection.json` — `f615915b1e23e3043e4a2e68dc5285f6f9f6ee4e00e93e1bf01f37f290e2e91b` |
| Latest promotion | `rust-sdk-inspection-20261004/latest-inspection-13ed/e864-promotion-run37252930718-attempt-1/final-latest-inspection/independent-promotion-inspection.json` — `40ee172e6ebb6d6ed827c71f4bdcbfaf4a006c4ca433ac145271421d4609e7f9` |
| x86_64 native channel | `rust-distribution-inspection-20261004/source-e864abb-standalone/run37253584672/channel_gate_review-v1/native-audit-final.json` — `fbe74c86f04623231b9017ea1c62fb3dda2aaa206e9ab65af2e9912199005369` |
| ARM native channel | `rust-distribution-inspection-20261004/source-e864abb-standalone/run37253586732/standalone-native-37257537261-attempt-1/final-native-audit.json` — `7baa6f0d8395bd0cc674a1718ba63b142f46b9080ec095646c3685fbc4c2acb5` |

Material limits follow the [Rust portability boundary](portability.md#rust-provider-boundary)
and [SDK recovery contract](sdk.md#retained-rust-extension):

- Rust 1.63 standard-library binaries are not ASAN-instrumented; Wasm has no native Rust unit harness, with mixed Node/browser execution supplying the recorded evidence.
- Linux container/ABI checks do not qualify older kernels or physical hardware. Windows Server 2022 execution does not qualify the oldest Windows client. Full Windows GUI execution passed; offline Windows GUI and MSVC installation/reinstallation remain unverified.
- Retained official compiler-package reassembly is not Rust compiler/Cargo reconstruction from source; that reconstruction remains unverified.
- Certificate source/recovery controls rebuild retained input closures without a base fetch fallback; their ordinary execution route does not impose OS network denial. Additional e260 offline evidence retains its original scope and source identity.
- Local SDK inspection verified selected hash-bound controls, not complete SDK payload/source/bootstrap recovery. Visual image pixels were not reviewed.
- Protected native acceptance recomputed physical payload identities; local channel audits verified receipts and bindings without extracting the channel archives. Native receipts have no Rust-provider field; their Rust provenance is bound to the certified application inventory and build records.
- No ARM Arch/Gentoo, offline native installation, separate reinstall or physical-device coverage is claimed. The failed ARM publisher and its skipped original qualification remain failures/skips; fresh native acceptance is bound to its separate successful run.

## Rust-default selection (2026-10-04)

Local checks of the default-policy change used base commit
`49a4f397b9c58c3c364bdce8af2d6b296f7c551b` plus its exact working changes,
including the new native host-preparation script. The frozen 435-file source
inventory is `a46f29084bf1c1c8f0890628b133903ac9b8fcf221756f6f8fc418d16a14bb2f`.
These are intentional dirty-source checks, not a claim that the unchanged base
commit contains the new defaults. Later documentation edits retain this evidence
identity. See the [default-policy rationale](rust-hybrid-plan.md#why-rust-is-the-default).

| Scope | Observed result |
| --- | --- |
| Missing default toolchain | A fresh wrapper invocation with the provider omitted failed before creating its output tree. The diagnostic named retained Rust inputs, distro tools and explicit `--core-provider cpp`; no fallback occurred. Cargo, rustc and rustup were absent from the host PATH. |
| Explicit C++ compatibility | All 65 CTests and 1,577 executed Python cases in 58 suites passed. No runtime skips or nonpassing cases occurred. The three explicit native-Windows exclusions remain delete-pending directories, selected linker file identity and Job Object containment. |
| Retained Rust default | With only `--rust-sdk` supplied, all six selected CTests passed: four core checks, the six-case Rust unit harness and the relocated installed C++ consumer with Rust commands poisoned. The compiler was the retained official Rust 1.63.0. |
| Direct CMake default | A fresh direct configuration omitting `FOUNDATION_CORE_PROVIDER` selected `rust`, built the mixed executable and passed its CLI self-check. This did not depend on the wrapper supplying the provider. |
| Actual disconnected Bookworm | Omitted provider selected distro rustc 1.63.0 and Cargo executable 1.65.0 with neither SDK selected; the same six CTests and six Rust assertions passed. A separate explicit C++ phase passed five CTests with Rust commands mounted read-only as failing stubs, without discovery or invocation. Normal test planning passed; replacing a copied compiler caused the required stale-identity rejection. |
| Tooling and review | Independent integration review found no actionable issue. Changed workflows passed retained actionlint 1.7.12. All 26 changed Python files parsed with Python 3.9 grammar; this is a syntax check, not execution on Python 3.9. Documentation and whitespace checks passed. |

The Bookworm probe used fresh private outputs/homes/caches, read-only source,
rootfs and retained inputs, zero effective/bounding capabilities and a denied
external network. Original/new rootfs, source, harness and retained Debian input
inventories were unchanged afterward; all three owned process groups were empty.
An initial sandbox sysfs-mount rejection executed no application assertions; its
evidence was preserved and the authorized escalation reran the unchanged boundary
and checks successfully. No package/tool acquisition occurred in either build.

Evidence is retained under `build/agents/rust-default-root/`:

| Receipt | SHA-256 |
| --- | --- |
| `cpp-full.junit.xml` | `e049d9657ef517c926479e6c5a351b3f1e2381a74f3bc9a7eb72fe3d25491c59` |
| `cpp-full.timings.json` | `6463c099d1eec8b938106bf0b47b75e86b063954421458ed047460743ae9da79` |
| `rust-core.junit.xml` | `95ebb6a79b1277066ed3057c9b368f9dde2e36ffa2f545d1aaca2761561e3ab2` |
| `rust-core.timings.json` | `bed7e0cd235957f4d9aa622454f1e942c8d6b7f3365209eaad4f47a99d419a45` |
| `warm-logs.json` | `b75d9296bf0fbf9dd5d42581497782885ba8614f76860a72dab7d20c100d5a2f` |

The separate Bookworm receipt is
`build/agents/rust-default-native-probe/attempt-v2/evidence/qualification.json`,
SHA-256 `7f6644a3cf80f4ab47c53f54e041c2cc39cf6252ba943d9fb0bb22e8c9b27dfc`.
Its archived source, exact diff, individual commands, JUnit, planner results and
input afterchecks retain the scope above. Its unequal six/five-test phase times
are not the matched build comparison below.

### Hosted development checks

The committed default-policy implementation passed all four jobs in
[development run 37226774800](https://github.com/mirage335-colossus/software-foundation/actions/runs/37226774800)
at exact revision `1ad555fdd2eb05e5789cc89ee13a929e4777bed1`: 12 focused Rust
CTests, four explicit C++ compatibility CTests, 43 shared GUI CTests, workflow
syntax and all 60 selected complete infrastructure suites. The Ubuntu lane
selected actual distro `/usr/bin/rustc` and `/usr/bin/cargo` 1.75.0 after explicit
tool preparation. No runtime failure or skip markers occurred. Conditional
omission of the docs-only step and the release-storage fallback after successful
Actions artifact upload omitted no runtime tests.

The preceding [run 37226479586](https://github.com/mirage335-colossus/software-foundation/actions/runs/37226479586)
at `fefdd0cd094f005780457ffca632c4a176dc472f` failed one gallery test fixture:
its mocked Git revision disagreed with inherited `GITHUB_SHA`. The follow-up
commit bound the fixture environment to its mocked revision; production
provenance checks were unchanged. All 40 gallery cases also passed locally with
an intentionally conflicting inherited revision before the successful rerun.

Complete console logs and authenticated completed-run metadata are retained in
`build/agents/rust-default-ci/hosted/run37226774800/`, indexed by `inspection.md`.
Their SHA-256 values are respectively
`9e2aedb1344aec86381a28371274f9d285545338d1ec67c931c6b4c0c955e9f4` and
`448bfd75cda26f946b5a3905f7ad1712e9d466a8d7307e421a9da550deb64270`.
The uploaded tooling receipt artifact was not downloaded locally; these console
and run outcomes do not assert an exact inner Python case count or local
artifact-byte verification. This is native Linux development feedback, not new
Windows, Wasm, complete-backend, release, SDK-maintenance or gallery execution
qualification.

### Measured local build cost

One fresh build tree per provider and three alternating warm no-op builds per
provider used the same frozen source, Debian 13 host, GNU 14.2, Debug configuration,
four compile jobs, no GUI and no prepared C++ SDK. Rust used the retained 1.63.0
extension. Tools and operating-system caches were already available; these were
not cold-machine or SDK-provisioning measurements. Wrapper wall time starts after
argument parsing and includes input verification, configuration and build work.

| Build | Explicit C++ | Default Rust | Difference |
| --- | --- | --- | --- |
| Fresh tree, one observation | 1.516 s | 9.612 s | 8.096 s |
| Warm no-op, median of three | 0.445 s | 8.346 s | 7.901 s |

The warm ranges were 0.441-0.461 seconds and 8.329-8.388 seconds respectively.
All C++ warm runs reported no work; all Rust warm runs reported the archive
fresh. The remaining Rust cost is verification/configuration/build orchestration,
not repeated component compilation. The build phase itself includes verification,
so it must not be labeled pure compiler time. No integrity checks were relaxed.
Receipts are `cpp-cold.json`, `rust-cold.json` and each provider's
`*-warm-1.json` through `*-warm-3.json` in the same output directory.

This small core-only sample does not establish all-GUI iteration time, changed-file
compile cost, other-machine performance, CI preparation/transfer cost or AI-token
savings. The preceding four-target runtime qualification below remains tied to
`41d28fe`; the default-policy checks do not relabel it or constitute a rerun of
changed hosted release, SDK-maintenance or gallery workflows. No stable release,
base SDK publication or package-channel promotion was performed for this change.

## Optional Rust qualification (2026-10-04)

The optional [Rust validation component](rust-hybrid-plan.md) passed the complete
four-target hosted qualification at commit
`41d28fec5481c77fc5b20e20808405ff3f83707a` in
[run 37211392657](https://github.com/mirage335-colossus/software-foundation/actions/runs/37211392657),
attempt 1, of
[`rust-qualification.yml`](../.github/workflows/rust-qualification.yml).
All four producers and verdict job `111473327645` succeeded. This qualifies the
declared configurations and executed gates, not every operating system, device
or recovery claim. Subsequent documentation edits do not change those evidence
identities. The default application provider at that revision was C++; the later
Rust-default policy and its separate checks are recorded above.

| Final hosted target | Console-observed result |
| --- | --- |
| Native Linux x86_64, job `111466315537` | 116 source CTests passed: four core, one Rust-unit harness, 58 tooling, 52 `foundation.gui.*` tests and documentation. Actual Firefox interactions and all 30 renderer-isolation cases passed. Package/installed-consumer, all six backend runtime, ABI, retained compiler-package replay and disconnected acceptance gates completed. |
| Native Linux aarch64, job `111466315485` | The same 116-test source inventory passed on the native ARM64 lane, with actual Firefox interactions and all 30 renderer-isolation cases. Package/installed-consumer, all six backend runtime, ABI, retained compiler-package replay and disconnected acceptance gates completed. This is native execution, not x86_64 emulation. |
| Native Windows x86_64, job `111466315478` | Full source/GUI/browser/package gates, all six installed backends and the bounded disconnected core/consumer/package gate succeeded. All seven Debug CTests passed: five core, `rust.unit` and installed consumer; static-CRT checks passed. Final Release inner case totals and browser versions are not asserted from uninspected payload receipts. Full offline GUI regression and Microsoft host-tool reinstallation were not selected. |
| Browser wasm32, job `111466315491` | 65 source CTests passed: four core, 51 tooling and ten `foundation.gui.*` controller/Node/integration tests, not ten browser frontends. Actual Firefox and Chromium Wasm interactions passed editing, geometry, retained rows, bounded import, offered export and pagehide cleanup; each engine passed all 30 renderer-isolation cases. Retained compiler-package replay and disconnected acceptance completed. Native Rust-unit and native install CTests were not scheduled for Emscripten. |

The proof is the authenticated completed producer/run context, complete local
console logs and the implemented fail-closed gates, with immutable remote
retention pointers. The complete payloads remain in run-scoped draft retention
release `403087008`. Each small manifest was downloaded, SHA-256 checked and
context-validated; final archive chunks and per-file payload bytes were **not**
read back locally. Every final `readback-scope.json` records
`full_payload_readback: false`, `bundle_accepted: false` and
`local_file_bytes_verified: false`. Metadata inspection grants no additional
qualification or accepted bundle receipt; a workstation multi-gigabyte
re-download is not another hosted platform gate.

| Target | Manifest asset | Manifest SHA-256 |
| --- | --- | --- |
| Windows x86_64 | `610112088` | `6f764f45d5461b213375347973ca7d8c44c2f227c3f5bc3bd4c1bd0c82599119` |
| Linux x86_64 | `610116838` | `c53a8911d6367fd6024a01e7766c12463bc37845315d52e3343a30ebf378706a` |
| Linux aarch64 | `610126271` | `63ec2df73efdee1315abfe8c1a71ac25e11121796ae8498cdab81dcc5e096d3b` |
| Browser wasm32 | `610133601` | `01465c802f06d5e8af5cee288c91b546a2c7f0bebdc6720a989654a244d6a864` |

The local index is
`build/agents/rust-ci-hosted/run37211392657/final-evidence-index.md`, with log
hashes, original completed-job/run metadata and per-target `*-remote-metadata/`
pointers. No runtime skip markers occurred in the observed Linux/Wasm source
logs; unexpected runtime skips fail the executed runner. Applicable omissions
are explicit source-bound platform policy. Exact final inner Python totals,
full exclusion inventories and Rust inner-case totals are not inferred from
uninspected payload metadata. Earlier complete readbacks remain source-bound
to their original revisions below.

The latest default-C++ development check used commit
`41d28fec5481c77fc5b20e20808405ff3f83707a`, source inventory
`3cbb6adb3b6959721bb7cad1f2ddda31c7d93c8cc486b8c4ebbe41c9bf7618fb`.
All 65 CTests and 1,533 executed Python cases in 58 suites passed, with no runtime
skips or nonpassing cases and the same three explicit native-Windows exclusions
listed below. `rustc`, Cargo and rustup were absent from the host PATH; the
configured provider was `cpp` and Rust SDK/compiler fields were `none`.
Its receipts under `build/agents/rust-hybrid-root/` are
`cpp-final-41d28fe.junit.xml`, SHA-256
`6aac6add0f7fccdd9068185f287dae2bb5a1da1fb8c82da125349e63f13fd71a`,
`cpp-final-41d28fe/test-reports/`, `build-info.txt` in that tree, and
`cpp-final-41d28fe.timings.json`, SHA-256
`d77cc0db9ca8409a87444983a5d58179d84dadadbcee390430b768bef3bbe49a`.
These later host-development results do not relabel the older package evidence.

The disconnected runner froze a 434-file checkout with source identity
`e3ce53899b49915d466388fcdcafda71116f1b6686aaf4c264ff92a27347042e`.
The original default C++ build records that same identity. Both Rust GUI build/package
records instead identify
`fc38ea4046a6cef53e00aae1e308b8de59e0bd0cc0d5429a6eb1efab69dbbfbf`:
the same frozen checkout plus the verified retained GUI-source supplement.
Recomputing that combined inventory with the frozen source helper reproduces
the package identity. These hashes describe different inventory scopes, not
different application source. Later documentation or workflow edits do not
relabel these receipts as evidence for a newer complete source snapshot.

| Scope | Observed result |
| --- | --- |
| Original frozen C++ check without a Rust application toolchain | All 65 enabled CTests passed. The 58 Python suite receipts contain 1,498 passed executed cases and exactly three explicit native-Windows platform exclusions: delete-pending directory semantics, Win32 linker file identity and Job Object containment. This is the original `e3ce5389` snapshot, not the latest 1,533-case result above. |
| Debian distro-tool Rust development | Clean commit `41d28fe`, source inventory `3cbb6adb`, passed four core CTests, six Rust unit cases and the poison-tool relocated installed consumer with neither SDK selected. The actual Bookworm rustc package `1.63.0+dfsg1-2` reports 1.63.0; Cargo package `0.66.0+ds1-1` reports executable 1.65.0. The normal planner and changed-compiler rejection passed in a loopback-only, external-network-denied namespace with fresh homes and read-only source/rootfs; input/rootfs rechecks passed. No GUI, release, portable, package or complete-tool-matrix result is inferred. |
| Additional distribution helpers | Five CTests and 148 Python cases passed with no exclusions in a separate C++ development tree. Its configured source identity is `052118622e0d9f5ba7e63f1844ef5b8c50c603299cbac448f4a74da0309cf931`. These are helper regressions, not new signed-channel publication or package-manager transaction certification. |
| Actual Rust package projections | Seven core/backend projections in each of Debian, Arch and Gentoo formats produced 21 projections on the Debian 13 host. Each preserved all 206 shared non-`bin` files, including the Rust archive and notices, byte for byte with matching modes; all 21 CLI version/self-check invocations passed. Three separately extracted C++ consumers linked the Rust provider, checked rejection/atomicity and confirmed Rust symbols with `nm`. A real `.deb` and ELF audit, Arch `package()` Bash execution and modeled Gentoo helpers passed. This projection-only receipt did not exercise native package-manager transactions, public `/opt` launchers, channel activation, signing or publication; the separate Bookworm transaction result follows. |
| Actual Debian Rust package transactions | In a fresh disposable disconnected Bookworm rootfs, `dpkg` installed and configured all seven retained Debian variants, verified their installed payloads, passed 28 public/private CLI version/self-check commands and six Xvfb GUI smoke commands, then removed and purged all seven variants. Rust tools and Rust tool packages were absent, the host package database was unused, the baseline distribution package state was preserved, and retained inputs/rootfs passed rechecks. This used the original package projections above, not packages rebuilt from the later final-source snapshot. |
| Complete local disconnected x86_64 host inventory | `linux-x86_64` and `browser-wasm32`, both explicitly selecting Rust, passed fresh SDK restoration, builds, four core tests each, packaging and installed CMake consumers. The aggregate, retained-input rechecks and rootfs recheck passed. Source, both retained groups and restored execution SDKs were read-only; build, HOME, temporary, cache, Cargo home and rustup home were fresh. Parent/child probes recorded loopback only, denied external connections and zero capabilities. |
| Native Bookworm Rust application | Actual Rust 1.63.0 compiled the Release/portable component into one native graph with terminal, framebuffer, FLTK, Rev, SDL and hosted-web. The package passed its explicit Bookworm ABI audit, relocated installed C++ consumer and all six installed backend smoke checks. This scope does not include full backend interaction or visual certification. |
| Disconnected Rust Wasm application | The exact Rust 1.63.0 / Emscripten 6.0.10 tuple passed fresh application compilation, four Node core tests, packaging and the installed Node/CMake consumer using the retained frozen SDK cache. This original local receipt is separate from the later hosted Firefox/Chromium qualification above. |
| Local Firefox Rust Wasm application | Firefox 153.4.0esr on the Debian 13 desktop host passed four application cases: HTTP and direct-file, each standalone and isolated. Editing, tasks, geometry, retained rows, atomic invalid-ASCII import, 65,537-byte file rejection and pagehide/navigation cleanup passed. The complete 30-case renderer-isolation inventory and six additional error-state cases passed, with ten desktop capture files retained. Browser/server owners joined and input bytes were rechecked. |
| Native retained source-input replay | The complete Rust source group was recovered offline, its retained original supplier archives regenerated the extension, and its native toolchain probe passed against recipe `888eaacdca83ecc2d518a2062e13b65d43fdbe6188ee6daaf29713f2aabb13cd`. Input/rootfs rechecks passed. Compiler/Cargo reconstruction from source was not executed or qualified. |
| Trusted native Windows lane | Successful producer job `111452286607` in run `37206730598` at `3f70889` passed 102 source CTests, including 49 `foundation.gui.*` application tests, and 1,164 Python cases with 64 explicit platform exclusions and zero runtime skips. Seven Debug core/unit/consumer CTests, static-CRT audits, all six installed backend checks and Firefox 156.0.1 hosted standalone/isolated checks passed. Its bounded disconnected recovery, five core CTests, installed consumer and package verification completed; full offline GUI regression was explicitly false. This lane is not the otherwise failed matrix's four-target verdict. |

A retained-extension native-development check at commit
`6455ee46d3eaa505f6935b4b9c2ad3efd65d3b0e` records source inventory
`a7be2688618648eb63225cb5064fef09b21c2d48b079d18ceead5f4d82213c4d`.
The Debug Rust tree used the final retained
Rust 1.63.0 extension and passed six CTests: the four core tests, `rust.unit`
(six Rust unit cases) and `integration.install`. The latter relocated the package
and built/executed an ordinary C++ consumer with poison Cargo/rustc/rustup launchers
without invoking them. This Debian 13/GNU 14.2 configuration had GUI and portable
mode disabled and no prepared C++ SDK; it is not new portable/full-GUI release
qualification. Its retained receipts are `rust-final-6455ee4.junit.xml` and that
tree's `build-info.txt` under `build/agents/rust-hybrid-root/`.

The same `6455ee4` Rust development tree passed a warm no-op with input
verification and Cargo freshness checks. The archive, receipt and CLI retained
their exact timestamps and sizes. The measured wrapper total was 8.372 seconds;
this is one local observation, not a speedup or cross-platform performance claim.
Its source/SDK-bound record and phase measurements are
`build/agents/rust-hybrid-root/rust-final-6455ee4.noop.json` and
`rust-final-6455ee4.noop.timings.json` in that same directory. These later checks
do not relabel the older package, browser or disconnected receipts.

The original local retained-SDK Linux/Wasm targets executed exactly `core.cli`, `core.store`,
`core.text_status` and `core.text_validation`. Native Rust unit execution and
broader GUI/regression coverage cannot be inferred from that four-test selection.
The retained C++ recipes are
`3e7438a4b5ee7a4baf5d7abacbdd320087aab42f24ea021f0f023b61db55bb33`
for native Linux and
`74f5153e31c23f899f01d8340ffa4aba7f5a8ed81b0db206e6da8a1b38ece541`
for Wasm. Their Rust extension recipes are respectively
`888eaacdca83ecc2d518a2062e13b65d43fdbe6188ee6daaf29713f2aabb13cd`
and `f9e35b94f0f7c65b7f2c7fe6d8af2c93fee6056d572ed2943c2dc6ea81f609f4`.

The native application archive SHA-256 is
`edc1cef5a96a17300dd1fac86a013e3044ab743df48c50dff7a7a2228a649468`,
with inventory manifest
`da3c9a07ecd93a1f3cc2eee921d9fd9988010c88276090dc330145092faf5a71`.
The Wasm archive SHA-256 is
`d09acca2cf0fc8774f24088578966bcdb42a6d9718f9b4b770fba1fca1dbdd9d`,
with inventory manifest
`1f24f4b9fc781277dd185a9b575eccb74c7659ca81b85be196feab08b8ee70d4`.
These are retained local outputs, not published application releases.

Evidence remains under `build/agents/rust-hybrid-root/`: `cpp-default.junit.xml`
and `cpp-default/test-reports/`, `distribution-final.junit.xml` and
`distribution-final/test-reports/`, and `offline-final/acceptance.json` with
per-target `stage.json`, `execute.json`, core JUnit, package inventories and
configured `build-info.txt`. Source-input replay has its separate original
receipt at
`build/agents/rust-offline-adapters/native-source-replay-v2/qualification.json`.
The clean Debian distro-tool receipt is
`build/agents/rust-distro-native/attempt-v3/evidence/qualification.json`, SHA-256
`81f7eae4b6d567b1c4905d8a153e8c446c45c381856fdce719773f2f0e8e3e17`.
Its separate prerequisite inventory records explicit Debian package preparation;
the ordinary application build acquired nothing. Native package-owned library
links and complete notices were validated without relaxing retained-SDK rules.
The actual projection evidence is
`build/agents/rust-package-qualification/qualification.json`, SHA-256
`6e653c85b27f4500f033895f2bd80f099c8dc4a8e8e591f6b6147a19cbc1ee42`,
and its `validation-summary.json`, SHA-256
`c13802cfbf99bc46ce767823cefb5fe5d744464ae144a5506b2ec63e8c184404`.
The actual Debian transaction aggregate is
`build/agents/rust-debian-transaction/evidence-v3/qualification.json`, SHA-256
`def97e27464050846f09a9d42525f05d1179764db4672729629eb6bf8fc96abe`;
its `transaction.json` retains commands, installed payload checks and limits.
The evidence index is `build/agents/rust-debian-transaction/evidence-SHA256SUMS`,
SHA-256 `9b48a40f16f048bf8c4bcc16b5ba2eb491570eaa4e84b1aa59aef399dc9b7805`.
The Bookworm GCC 12.2/CMake 3.25.1 consumer passed only with an explicitly selected
`-no-pie` link policy. The default-PIE consumer failed in the retained v2 attempt
on an absolute relocation in the C++ store object. The read-only historical
same-SDK C++ archive comparison,
`build/agents/rust-debian-transaction/cpp-pie-comparison.json`, SHA-256
`4678966e03abb5a214c7fda7d9fb4efb0588eb54f3f385828a1cba90ece959d6`,
also found non-PIC absolute relocations; it did not execute a historical PIE link.
No production PIC policy or exported `-no-pie` requirement changed. The existing
matching C++ toolchain/runtime contract remains in force; default-PIE consumers
are not qualified by this additional check. The transaction explicitly included
manual pages excluded by the rootfs's Docker-slim filter. It did not activate an
APT repository, perform authenticated network retrieval, exercise Arch/Gentoo
package-manager lifecycles, sign or publish packages. GUI smoke commands are not
desktop interaction or browser-launch qualification.
The Firefox aggregate is
`build/agents/rust-wasm-browser-local/qualification.json`, SHA-256
`4bc0d292e57ac9fd8577ad3f929fbdab49b17cd152b4bec657a1a791427984e5`.
It binds the unchanged Wasm package above and matching production child modules;
application direct-file cases observed no HTTP/S resources. This is not
whole-browser network denial, Chromium/native Windows, mobile or assistive-device
qualification. The renderer's authority and navigation limits remain those
documented in [browser embedding](browser-embedding.md).
The earlier accepted [Windows lane in run 37206730598](https://github.com/mirage335-colossus/software-foundation/actions/runs/37206730598) above is bound to commit
`3f70889d0eab35af067f51c4bbf3281c120d5723` and source inventory
`1f1851daccd31f328d460491e138dd6c915e3a991decd552e719ee96a960ce88`.
Strict successful-producer transport verification checked the complete context
and archive/file hashes. Its retained manifest SHA-256 is
`e0010181e1e4c96bce6ec899e8ff3d30a2eb8755f78f47cb61501b794bb5a9df`;
the scope, strict fetch receipt, recovery readback and producer log are under
`build/agents/rust-ci-hosted/run37206730598/`, starting at `windows-scope.md`.
Its about-209-second owned firewall stage denied external TCP 443 controls,
permitted loopback, restored original profiles and removed its temporary rule.
The recorded Debug PE import result covers its five executables and consumer,
not every GUI binary or an older Windows OS. These older inner counts and browser
version are not transferred to final `41d28fe` evidence.

The preceding complete four-target
[run 37209852887](https://github.com/mirage335-colossus/software-foundation/actions/runs/37209852887)
at `9860e00` also succeeded. Strict complete-byte local readbacks were accepted
for its Windows, Linux x86_64 and Linux aarch64 bundles. Its Wasm producer and
remote retention succeeded, but the workstation's full Wasm fetch timed out at
600 seconds and was not accepted. This is not a failed hosted platform gate.
Earlier cancelled runs `37200078067`, `37201305850` and `37205559015` retain
forensic diagnostics, not target qualification. The successful `3f70889` Windows
lane belonged to an otherwise failed matrix. No later success retroactively
certifies those incomplete or failed producers.
Full Windows offline GUI regression, Microsoft tool installation/reinstallation,
older-client floors and other unexecuted platforms/devices remain unqualified.
Retained toolchain restoration, source-input recovery
and a compiler rebuilt from source remain distinct claims; the last is
**UNVERIFIED**. Those historical qualification runs make no stable publication or
distro-channel promotion claim. The [later release record](#rust-enabled-portable-release-and-signed-channels-2026-10-05)
records the separately executed delivery gates.

## Disconnected builds, stale actions and browser authority (2026-10-04)

This implementation began from clean commit
`2cc4ea9fddddcb2ea963a56de6b9b375a09a83fd`. The reference repositories remained
unchanged. It preserves the existing hosts, application features, build entry
point, SDKs, distro projections and release workflows. Application changes add a
generic semantic input epoch; backend details remain in adapters and composition.
Bezel activation now requires the exact successfully displayed presentation.
Privileged browser embedding uses an opaque renderer frame and host-owned
transport, services and lifecycle. See [disconnected builds](offline-builds.md),
[browser embedding](browser-embedding.md) and [GUI contracts](gui-boundary.md).

The complete initial disconnected x86_64 host acceptance used immutable source
`a1153bfdb09856ee6fc8d54d7eb3a00bd4adb9bd6b2f2de84aa4a56dfd08cb8f`.
The final 394-file source snapshot, after a Chromium offline Worker correction
and qualification/test refinements, is
`6ef7a6acded51e94b12953ca7c4e663d9cf37d830c25e746b12230104ab2a2cd`.
All native application C++ sources, renderer/host modules, CMake definitions and
maintained supplier patches are identical between these snapshots. The delta is
the offline packager, release-evidence gate, their tests, two hostile-browser
fixtures, documentation and the native-platform pending record. Native evidence
retains its original identity; it is not relabeled as a full rebuild of the later
snapshot. Only this validation entry changed after the final snapshot.

| Scope | Observed result |
| --- | --- |
| Bookworm isolation | Prepared Debian 12 amd64 rootfs, 395 configured distro packages and exact file/link/mode inventory. Application and child probes saw loopback only, external connection refusal, no capabilities, read-only source/groups/SDK and fresh application build/HOME/temp/cache directories. Host HOME, supplier checkouts and unrelated caches were absent. Rootfs and retained inputs passed final rechecks. Setup ran on the Debian 13 host; application compilation, linking, packaging and consumer checks ran inside Bookworm. |
| Complete initial host inventory | Both `linux-x86_64` and `browser-wasm32` passed SDK restoration, fresh builds, exactly two core tests each, packaging and installed CMake consumers. Native Linux passed the explicit Bookworm ABI audit and installed smoke checks for terminal, framebuffer, FLTK, Rev, SDL and hosted-web. One native graph built all six backends; Wasm used its necessary separate toolchain graph. |
| Final corrected Wasm | A new disconnected run of the final snapshot passed fresh Wasm compilation, two core tests, packaging and installed Node/CMake consumer verification using the retained read-only SDK and frozen prepared cache. Its `--case browser-wasm32` receipt explicitly records focused coverage, not a second complete native host inventory. |
| Shared GUI regressions | All 41 registered GUI-label CTests passed inside disconnected Bookworm, with zero skipped/failed cases. The same native build, wrapper identity and six application binary hashes were preserved. This configuration has toolkit host/supplier/visual qualification disabled; the separate six installed package smoke checks above are not substitutes for those broader tests. |
| Actual browser interactions | Firefox 153.4.0 and Chromium 154.0.8037.92 each passed six cases: hosted native, HTTP Wasm and direct-file Wasm, each with standalone and isolated compositions. Tests covered editing, accessibility, geometry, retained rows, bounded/atomic import, export offering, task/prompt behavior, navigation and cleanup. Direct-file execution observed no HTTP resources. Browser owners joined. |
| Renderer boundary | Each engine passed the complete 30-case hostile-renderer inventory. Correctly hashed malicious child code, including top-level code, executed before independent parent/token/service/storage/network/URL/lifetime checks. Actual retained fixtures, canonical bundles, input hashes and policies passed the tightened release gate; the twelve security assets exactly match final delivered Wasm assets. |
| Native Wasm import | The final source-bound schema-3 document passed verification/staging and fresh core-only native portable assembly in Bookworm. Its installed consumer passed. All three imported document files matched the Wasm package byte for byte, and both installed offline launchers were present. Original six-backend native binaries stayed unchanged. This is separate from rebuilding all six backends with an imported document. |
| Focused tooling | The final packager/bundle/import suites passed 27 methods; the final release gate passed 33 methods. The initial tools-label aggregate passed 55 of 56 CTests: the failing mock serialized a socket `MagicMock` into Firefox preferences. Giving it an explicit loopback address repaired that fixture; both affected GUI-boundary/release-check CTests passed. The failed aggregate is retained. Offline helpers/container tests and documentation/boundary/whitespace checks passed. |

Chromium initially rejected the direct-file module Blob Worker entry with
`Refused to cross-origin redirects of the top-level worker script.` Under the
unchanged package CSP, a discriminating probe established classic Worker entry,
Worker-owned Blob ES module import and Wasm compilation. Schema 3 now derives a
narrowly validated classic entry with explicit strict mode from the same retained
Worker source. HTTP keeps its module Worker; ordering, bounds, cancellation,
close acknowledgements and CSP remain unchanged. Both engines then passed the
complete corrected Wasm matrix. The original failure and probes remain retained.
An independent review also found and repaired missing retained-fixture validation
in the release gate; missing fields or changed fixture bytes now fail qualification.

Evidence is under these ignored local directories, with original source/group/SDK
identities, commands, phase receipts, JUnit results, package hashes and failures:

- `.agent-work/artifacts/sol-ultra-implementation-v1/offline-bookworm-final/`
  (`acceptance.json`, native `reentry-gui.json` and
  `reentry-wasm-import-6ef7a6acded51e94.json`).
- `.agent-work/artifacts/sol-ultra-implementation-v1/offline-bookworm-wasm-packagefix/`
  (`acceptance.json` and final Wasm `execute.json`).
- `.agent-work/artifacts/sol-ultra-browser-tests-v1/final-browser-matrix.json`
  and its exact positive/security receipts, fixtures, policies and captures.
- `.agent-work/artifacts/sol-ultra-implementation-v1/` contains the original and
  repaired tooling JUnit reports and native-import log; the local re-entry launcher
  is retained as evidence, not a new supported build API.

The renderer can forge currently eligible delegated UI intents; this is not proof
of a human gesture. Own-frame navigation may issue a request before channel
revocation. Message limits apply after browser delivery, not to sender allocation
or CPU use. An operation first dispatched while authorized may finish after
revocation; subsequent dispatch and late parent completion effects are rejected.
Worker computation, native process isolation and disconnected build networking
remain distinct boundaries.

At that revision, these local receipts did not establish native aarch64/Windows
offline execution, a new hosted CI run, distro-channel transactions or release
publication. Later source-bound Rust qualification is recorded above; broader
unselected scopes remain in
[pending native qualification](../.agent-pending/offline-platform-qualification.md).
These historical receipts retain their original limits and source identity.

## Remaining transfer implementation (2026-10-04)

Final hosted qualification at `3a3b7626161a8069cfa4f3729e1a51c0dbf4bfdb`
passed all four platform package producers and combined assembly: **353 CTests
and 5,132 Python cases**, plus **1,020 native Windows diagnostic executions**.
The exact source identities, SDK consumer proofs, local checks, historical failures
and limits are recorded below. All four newly qualified SDK groups are published
in the [base prerelease](https://github.com/mirage335-colossus/software-foundation/releases/tag/base),
with existing SDK assets and application Latest preserved.

The follow-up implements the previously omitted general-purpose examples:
Windows GUI subsystem entry/UTF-8 manifests; source-matched prebuilt Wasm import
into native packages; exact installed offline-document launchers and versioned
APT/Arch/Gentoo projections; opt-in phase timings; verified interactive native
upgrade convenience; optional agent evaluation guidance; generic three/five-key
bezel navigation; terminal/SDL/embedded file-provider composition; bounded ordered
browser content chunks; and an optional Linux no-socket worker with a separate
trusted native-file pipe. Shared application code is unchanged. Ordinary builds
add no dependency download or mandatory timing/qualification work.

Native GUI qualification can explicitly consume the verified checkout GUI group.
Its optional Linux development mode executes ordinary `build dev` and full
`test dev` without portable mode; Windows keeps native Release qualification.
The supplier stays at `7a704f73e563a167ea335dd23ccd9f383ebec274`; the refreshed
retained group is
`b04e85cc9fb8aabe48888efe9fc0ae2f24d074fb49b6111805fee9afe73f8554`.

Local integration used a complete 366-file snapshot
`d7d9062deb03ce56d7c2369f70fa4674c99abcc6b92f9c919b65b73f5e286ff1`.
The final helper/documentation corrections were checked in snapshot
`5c48879ffcd4a20ac23142863a7061f167a5829379af9182e4e7dce9eb0d9d1d`.
The GUI/browser/native-import/sanitizer implementation files are unchanged between
these copies. The imported Wasm package is bound to the complete first snapshot;
the second snapshot is separate evidence for the helper/documentation corrections.

| Scope | Observed result |
| --- | --- |
| Full native core/tooling/distribution | 61/62 CTests initially passed; 1,491 Python cases passed, two failed and two were explicitly inapplicable on Linux. A local `shutil` import in the new lifecycle branch shadowed the module in certification commands. Removing that import repaired the existing regression tests. All four affected/final CI-plan, workflow-storage, runner-policy and documentation CTests then passed; the original aggregate remains recorded as failed. |
| Retained Wasm SDK | Release build and offline package completed from the retained SDK with no preparation/download. All ten selected GUI/Worker/browser/source-boundary CTests passed. |
| Actual Firefox | Hosted, Wasm and direct offline-file modes passed editing, accessibility, geometry, retained rows, bounded import, atomic invalid-input rejection, export offering, navigation/pagehide and cleanup. Offline mode recorded no network resources. |
| Native prebuilt-Wasm assembly | The wrapper built and verified a native TGZ, relocated the CLI and installed CMake consumer, and directly installed the exact previously built HTML. The pinned web manifest was `97a1bad0b90ac725756f300aedb29a404864834c8019b4d40465a62452764892`. |
| Native GUI | All 51 CTests passed with no skips, including six public hosts, FLTK/Rev/SDL visual and clipboard checks, bezel, file chunks and actual worker isolation. The later GUI archive attempt stopped before creation because the extracted distro prefix lacks `dpkg-query` ownership for `libSDL2.a`; notice verification was not bypassed. SDK-backed package qualification is separate. |
| Development and sanitizers | Five native Debug checks passed for bezel, file chunks, no-socket policy, real isolated worker and file content. Three address/undefined/leak-sanitized bezel, file-transfer and file-content checks passed. |
| Focused contributor coverage | All 92 import/Wasm/APT/distro/distribution cases passed. Build iteration: 29 applicable cases and one explicit native-Windows exclusion; distro client: 49 cases passed. Actual cold/warm core runs each passed 2/2; phase measurements are in the development-speed guide. |
| Platform test declarations | The two Unix-only opener/compiler fixtures are explicitly inapplicable on Windows; portable import/source-identity checks remain required there. Missing tools or unexpected skips still fail. |
| Static/checkout qualification | Python 3.9 grammar for 137 files, documentation, GUI boundary and whitespace checks passed. The actual checkout-GUI lifecycle command verified/copied/reverified the exact retained group. |

Follow-up portability repairs were checked in the complete 366-file snapshot
`afa4c373a5332a16a91805679be4ff0caabcdb5c05e24db10d4e0328dc7c8678`.
All 62 CTest suites passed across the full invocation and a focused rerun: the
first invocation passed 57/62, with five signed-package suites failing GnuPG
fixture startup inside the restricted sandbox. Those exact five suites passed
outside the sandbox with temporary local daemon support. Their final reports
contain 1,499 passing Python cases, two explicit native-Windows exclusions and
no unexpected skips; the original failed aggregate is retained as failed.
Python 3.9 grammar and whitespace checks passed.

Native qualification of `850c4a74f21ec1f2ee0274c7d9d78a3d667710f0` exposed
CMake's trailing-colon build-RPATH padding on both Linux architectures, correctly
rejected by the runtime audit. Exact link paths and install-only normalization
replace that padding without weakening the audit or rewriting warm build outputs.
The 98 affected SDK/runtime/portability cases passed; real generator fixtures
passed CMake 3.31.6 and retained 4.4.0, including relocation, components, repeated
installation and untouched no-op outputs. Windows compiled all application and
GUI-test targets and passed all six native hosts, native visual and clipboard
checks, then failed 13 regression suites. Repairs cover canonical Wasm checksum
bytes, binary/LF/CRLF fixtures, portable declaration keys, declared/physical path
normalization, exact source-payload expectations and native junction rejection.
The latter exercises actual reparse protection rather than skipping Windows.
Independent review added prefix-sibling and caller-preserved alias regressions.
These changes preserve application/backend insulation and SDK recipe identities.

Qualification of `65a71a0cbe2fcf6ee3c8b65b1f4bb24b212913c2` passed all
51 native GUI cases on each Linux architecture and all 45 on Windows. The Linux
runs passed 101/103 CTests but exposed CMake 3.25's manual `$ORIGIN` escaping in
the two runtime fixture suites; the main SDK application build used CMake 4.4 and
passed its strict runtime audit. The repair delegates encoding to CMake's managed
RPATH property while preserving the caller's separate installed policy. All 98
affected cases passed with privately extracted Bookworm CMake 3.25. Real build,
install and CPack fixtures passed 3.25, 3.31 and 4.4, including execution after
removing SDK/build access and unchanged warm-build hashes/timestamps. No SDK
recipe, runtime auditor or application/backend contract changed.

The Windows run passed 87/91 CTests. Three remaining fixture failures now retain
exact checksum/evidence bytes and accept CMake diagnostics from either output
stream. A bounded structural diagnostic identified the fourth failure precisely:
CMake lowercases the Windows drive in `CMAKE_CACHEFILE_DIR`, unlike the supplied
root. Known source/build drive-letter aliases now normalize without folding
directory components, external paths or other cache values; strict identity
equality remains required. Optional host diagnostics now select any of these
four complete tooling suites with the installed native compiler, binding the full
maintained source inventory. They require no repeated GUI build and cannot qualify
a release. The focused diagnostic helper suite passed after an independent review
added detection of newly introduced source inputs. The first native targeted
runs passed the retry and package suites; import passed both applicable cases
with two explicit Unix-only exclusions. Its outer diagnostic owner correctly
rejected a surviving MSVC telemetry helper. Compiler-capable Windows diagnostics
now use the existing exact-toolkit private build-session owner, with a retained
completion receipt; generic process completion remains strict. The [native planner rerun](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174039430)
passed all 37 cases and exact compiler cleanup on `7040420`. The import rerun
correctly rejected a different surviving `MSBuild.exe` worker: its fixture had
implicitly selected the ambient Visual Studio generator. The fixture now selects
the project's supported Ninja/Release configuration while preserving every
positive and negative import assertion. The complete local import suite passed;
its final native execution on `ca255290` passed with exact compiler-helper
termination and join. The [workflow](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174242327)
remains failed because evidence retention rejected an inconsistent release
inventory after draft creation; no payload bytes were uploaded. The helper
allowlist was not broadened.

That retention failure identified an unnecessary global-history reread after a
confirmed draft creation. The transport now validates the complete creation
response and observes its exact release ID with bounded read-only visibility
checks. Lost responses and competing initialization retain strict discovery;
uncertain creation is never repeated. All 111 release and 66 transport cases
passed, including unstable unrelated pagination, identity/lifecycle mismatch,
delayed visibility, access failure and lost-response controls. Two negative
controls fail the earlier implementation. The final [native import diagnostic](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174654721)
on `51dd4fc` passed execution, strict compiler-helper completion and evidence
retention. Subsequent complete-suite feedback exposed stale distribution fixtures
that still delayed list discovery. Those fixtures now delay the exact ID GET and
assert bounded reads, unchanged strict mismatch rejection and no mutation replay.
The artifact-policy fixture also chooses its environment explicitly so its
optional-path case cannot inherit a required-artifact setting from CI.

The final complete local 366-file snapshot
`ed3d9011d83747b15ca8e2422c014af8a1f0cfbb914a0242a9be0f17abb0f983`
passed **62/62 CTest entries in 34.64 seconds**, including all optional distribution
suites and real disposable GnuPG/loopback fixtures. Its 57 complete Python reports
contain **1,517 passed cases**, two explicit native-Windows exclusions and no
unexpected skips. The immediately preceding aggregate remains failed (61/62);
its sole stale distribution-fixture failure is repaired by this final run.
Exact report/log/source hashes are retained in
`.agent-work/artifacts/completion-root-v1/complete-final2-validation.json`.

The [implementation feedback run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37171429379)
passed all four jobs. The [GUI maintenance run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37171470282)
published the exact three-file retained GUI group. The Wasm producer in
[SDK maintenance](https://github.com/mirage335-colossus/software-foundation/actions/runs/37171568881)
passed core 2/2, full GUI/tooling 56/56 and 1,291 Python cases, with only two
explicit native-Windows exclusions. Both consumer receipts and all four producer
isolation checkpoints passed; this producer result alone does not establish
publication or success of the still-separate native producer jobs.

Repaired native Linux development runs on `ca255290` passed **103/103 CTests**
for both [x64](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174256576)
and [ARM64](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174260724),
including all 51 GUI-labelled entries, without portable mode. Their workflows
remain failed solely at the old evidence-retention inventory check before any
payload upload; exact raw job logs retain all executed passing rows.

Fresh SDK consumers, reusing the original complete compiler groups, passed:

| Consumer / source | Core | Full GUI/tooling | Python cases / explicit platform exclusions |
| --- | --- | --- | --- |
| [ARM64](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174082162), `7040420` | 2/2 | 103/103 | 1,360 / 2 |
| [Wasm](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174079259), `7040420` | 2/2 | 56/56 | 1,304 / 2 |
| [Windows](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174326956), `ca255290` | 3/3 | 91/91 | 1,051 / 64 |

All three have complete verified proof archives, passed qualification records and
four passed isolation checkpoints with producer inputs absent. No unexpected
skips occurred. Their workflows remain failed only during redundant SDK-group
retention using the old inventory code; proof retention succeeded. The Windows
Mesa probe and exact host-only graphics cleanup passed. The original cold x64
SDK completed and was retained; its old consumer failed the already-repaired
RPATH padding check. Its final retained consumer qualification is separate.
At that checkpoint no newly built SDK had been publicly published. The final
x64 qualification and approved publication are recorded below.

The first final [application archive run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174274156)
on `ca255290` passed actual Linux x64/ARM and Wasm packages, strict runtime
inventories, relocated CLI and installed-library consumers. Windows passed all
48 GUI-labelled entries but stopped at the now-repaired artifact-policy fixture
(90/91 CTests); it produced no package, and complete assembly was skipped. A new
source-bound four-platform package run was required after that fixture repair;
archives cannot be relabelled to another source revision. That required rerun is
recorded below. Packaged GUI executables
are inventoried/audited but not individually launched after relocation. The
native prebuilt-Wasm bridge and real browser execution have their separate local
checks above; this workflow does not perform them.

The next [application run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37175187646)
on `6d85914` passed Linux x64/ARM **103/103 CTests and 1,369 Python cases** each,
and Wasm **56/56 and 1,313 cases**. Complete package inventories and relocated
CLI/installed consumers passed. Windows passed every one of its 48 GUI-labelled
entries and the repaired artifact-policy fixture, but failed one compatibility
coordination case (90/91 CTests; 1,059 passed Python cases and one failure).
One of eight writers received `WinError 5` from exclusive mutex-directory creation
before acquiring ownership. This aggregate remains failed and assembly was skipped.
The retained complete evidence is in
`.agent-work/artifacts/final-app-proof-v1/qualification.json`.

The narrow repair retries only that Windows creation error, with seven exclusive
creation attempts and at most 315 ms of deliberate backoff. Persistent denial
raises the original error; an occupied directory still rejects as busy; no lock
is removed and protected work cannot replay. Four portable controls preserve
those distinctions. A native held-handle fixture separately tests Windows
pending-deletion behavior; the original traceback alone does not prove which
process or filesystem condition caused its transient denial. The optional complete
`agent_board` diagnostic permits repeated native checks without another GUI build.
Its source selector/helper tests pass, and the original eight-writer contribution
assertions remain unchanged. The [old-source Windows baseline](https://github.com/mirage335-colossus/software-foundation/actions/runs/37175782630)
completed 20 repetitions without reproducing the intermittent failure under
Python 3.12.10. The original failure used Python 3.14.7, so this is a different
interpreter sample and does not erase that failure or establish its cause. The complete repaired
366-file local snapshot
`64dad5afcca71d1a70495e1f644a03c54d92b88261c7322df71de0e32a8834d1`
passed **62/62 CTests in 34.15 seconds**, with **1,522 passing Python cases**,
three explicit native-Windows exclusions and no unexpected skips. This includes
all optional distribution suites. Native repair qualification is recorded
separately. Exact reports are in
`.agent-work/artifacts/completion-root-v1/complete-final3-validation.json`.

The [repaired Windows diagnostic](https://github.com/mirage335-colossus/software-foundation/actions/runs/37176024270)
used the exact Python 3.14.7 family from the original failure. In all 20 repetitions,
50 cases passed, including the unchanged eight-writer test; only the new native
probe failed. Its `RemoveDirectoryW` setup allowed immediate name reuse on this
runner, so the assumed pending-deletion condition was not constructed and the
production retry was never reached by that probe. This failed diagnostic is
preserved as 1,000 passing case executions and 20 failures, with no exclusions.

The fixture-only correction explicitly sets classic `FileDispositionInfo` on an
owned DELETE-access directory handle and verifies `FileStandardInfo.DeletePending`
before requiring the actual WinError 5. API structure sizes, exclusive-acquisition
checks and handle cleanup were independently reviewed. The production helper is
unchanged. All 50 Linux-applicable board cases and four runner cases passed again;
only the native case remains explicitly excluded there. Unchanged scopes from the
complete local run were not needlessly repeated.

The corrected [single native probe](https://github.com/mirage335-colossus/software-foundation/actions/runs/37176646295)
passed all 51 cases at `3a3b7626161a8069cfa4f3729e1a51c0dbf4bfdb`.
The final [20-repetition Windows diagnostic](https://github.com/mirage335-colossus/software-foundation/actions/runs/37176741520)
then passed **1,020/1,020 cases**, with zero exclusions, failures or skips under
Python 3.14.7, optimization disabled. Every repetition checked the actual
`Directory` and `DeletePending` state, observed native `WinError 5`, acquired the
mutex exclusively after handle closure, and passed the unchanged eight-writer
case. All 41 retained members and six exact source hashes were verified; all
writers stopped. The proof manifest SHA-256 is
`4f8cd56f88ebbb7ba687feec7be7d1b0d6960c6bd848acc4e4a456c3c184e5ed`.
This tests the repair under a constructed native condition; it does not establish
the cause of the original intermittent error. The [final feedback run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37176646150)
at the same implementation revision passed all four jobs.

The final [x64 SDK consumer run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37176095244)
at `324b1b4484cafb4175aaaaf1f967c29f04ac04b5` passed its entire workflow:
core **2/2**, GUI/tooling **103/103**, and **1,374 Python cases**, with three
explicit Windows-only exclusions and zero unexpected skips. Its 86 proof members,
exact SDK triplet, both consumer receipts and all four producer-isolation
checkpoints were verified. The retained proof manifest SHA-256 is
`ce7621b97f92627e61f99afeeb040d7b7bb96fc329f746ebb9cc8811f741c37c`.
The preceding x64 consumer run had also passed those consumer scopes but failed
retention with HTTP 403 before any payload upload. Its complete inventory and
absent tag were reconciled; the cause was not established. It remains failed and
is not substituted for this successfully retained final proof.

The approved x64 SDK publication initially stopped with an uncertain upload
under the normal 600-second CLI-command limit. Complete raw reconciliation found
one exact uploaded source asset and one incomplete binary `starter`, with no
checksum marker. All 21 pre-existing asset identities/digests, the base tag and
Latest were unchanged. Reviewed administrative recovery removed only that failed
starter, preserved the valid source asset, and uploaded the missing binary once
with an explicitly bounded 3,600-second transport configuration. It published the
checksum last and verified all three downloaded files and their inner inventories.
The standard publisher's refusal of partial groups was preserved; no blind replay
or overwrite of an earlier group occurred. The first operation remains failed;
the successful recovery has its own receipt. The underlying transport error was
not established beyond the retained uncertainty and observed remote state.

All four approved all-GUI SDK groups are now published in the public
[base prerelease](https://github.com/mirage335-colossus/software-foundation/releases/tag/base).
Each contains the exact qualified binary archive, complete supplier-source archive
and checksum file. Publication reused the verified retained bytes without rebuilding
the compilers; every complete group passed downloaded-byte and inner-inventory
verification. The recipe links below provide the binary/source checksums.

| Target | Published recipe / checksums | Successful consumer proof |
| --- | --- | --- |
| Linux x64 | [3e7438a4b5ee7a4baf5d7abacbdd320087aab42f24ea021f0f023b61db55bb33](https://github.com/mirage335-colossus/software-foundation/releases/download/base/sdk-3e7438a4b5ee7a4baf5d7abacbdd320087aab42f24ea021f0f023b61db55bb33-SHA256SUMS) | [37176095244](https://github.com/mirage335-colossus/software-foundation/actions/runs/37176095244) |
| Linux ARM64 | [afe8d1ba004206fcf234376a2110e69c4e9e1ef6b373e7afe23afe8497f8e4de](https://github.com/mirage335-colossus/software-foundation/releases/download/base/sdk-afe8d1ba004206fcf234376a2110e69c4e9e1ef6b373e7afe23afe8497f8e4de-SHA256SUMS) | [37174082162](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174082162) |
| Windows x64 | [da0aa41ad58536497e23503b4ca778521e47cbd412c5b944490aa3c4d535bf0a](https://github.com/mirage335-colossus/software-foundation/releases/download/base/sdk-da0aa41ad58536497e23503b4ca778521e47cbd412c5b944490aa3c4d535bf0a-SHA256SUMS) | [37174326956](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174326956) |
| Browser Wasm | [74f5153e31c23f899f01d8340ffa4aba7f5a8ed81b0db206e6da8a1b38ece541](https://github.com/mirage335-colossus/software-foundation/releases/download/base/sdk-74f5153e31c23f899f01d8340ffa4aba7f5a8ed81b0db206e6da8a1b38ece541-SHA256SUMS) | [37174079259](https://github.com/mirage335-colossus/software-foundation/actions/runs/37174079259) |

The final complete public inventory contains **33 assets**: all **21 earlier
assets retain their exact IDs, sizes and digests**, and the only additions are the
**12 approved SDK assets**. Base release ID `401599028` remains a public prerelease;
its tag still identifies `3df32968cdae5894635938db10825008dcfcc808`. Application
Latest remains [release-37070391587-attempt-1](https://github.com/mirage335-colossus/software-foundation/releases/tag/release-37070391587-attempt-1)
(ID `402199557`). No application release was replaced or promoted.
The complete receipt-to-public-inventory audit is
`.agent-work/artifacts/completion-root-v1/sdk-publication-final-audit.json`, SHA-256
`5905f8406ebeaa3c6213b29103335f73bed71170f441d39afdc1a9a488b60d39`.

The final [application package run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37176743158)
at `3a3b7626161a8069cfa4f3729e1a51c0dbf4bfdb` passed all four producers and
combined assembly. It consumed the previously published SDK recipes
`bdd39974a891e6161d667bbaa0ff2c1894fe9f188ed76d47d1ad6c896972c9f8`
(x64), `88c7d871f5cf6210cb4dac6874e666a275dd5f359d42439369a7206b39dbe109`
(ARM64), `cd16aeb6bd2dff13115d456ffbea2d166db37427106a5e03961926f840f10feb`
(Windows), and `783adcbd828ccd3dce72fefa575755d0d94f4eec528634bd4a9bdce7341356d5`
(Wasm). The new SDK groups have their separate consumer qualifications above.
Its exact source-bound package archives were independently checked against their
complete descriptors:

| Target | CTests | Python cases | Explicit platform exclusions | Verified package members |
| --- | --- | --- | --- | --- |
| Linux x64 | 103/103 | 1,374 | 3 | 196 |
| Linux ARM64 | 103/103 | 1,374 | 3 | 195 |
| Windows x64 | 91/91 | 1,066 | 64 | 78 |
| Browser Wasm | 56/56 | 1,318 | 3 | 72 |

There were no failures or unexpected skips. Each producer completed the separate
installed-library consumer compilation and execution; native packages also passed
relocated CLI checks. All six native GUI hosts are present in each native package.
All fourteen packaged Linux executables have exactly `$ORIGIN/../lib/runtime` as
their runtime path. Windows FLTK/Rev/SDL executables use GUI subsystem 2 and contain
parsed manifest resource ID 1 with UTF-8 and supported-OS declarations; CLI and
terminal executables use console subsystem 3. The graphics probe passed and its
temporary Mesa DLLs are absent from the package. GUI runtime tests execute build
outputs; packaged GUI binaries were audited rather than separately launched after
relocation. Native prebuilt-Wasm import and actual DOM-browser operation retain
their separate local evidence above. This run selected `execute=false` and
`require_regression=false`: it qualifies package production and assembly, not a
public application release or a complete release certificate. The assembled
21-file release inventory has SHA-256
`7a6dbd000bca181a719d10485e33bc78b76b0e7e7ad69c15cec1eeb3889ed7e6`;
its 22-file delivery map matches all four package descriptors and their four
complete SDK triplets. The source archive SHA-256 is
`fefd48689a77e19f07e9bbec87264a778a39bd499c1db0133268616484d90918`.
The independently verified retained-control record is
`.agent-work/artifacts/final-app-proof-v2/qualification.json`, SHA-256
`87817da0567db9afa0dda7404814216eaae0ee2d8fe4b49261c5b9bbd242fb33`.

These observations do not establish physical touch/bezel/VR hardware, Arduino,
or an actual system package upgrade. Package-manager commands were intercepted
while real signed-generation verification ran. The worker boundary limits socket authority, not general
filesystem/process authority. Forced native export termination can leave its
exclusive temporary file and an uncertain commit outcome; the host guide documents
that recovery limit.

## General-purpose transfer implementation (2026-10-04)

The final implementation before this validation entry has source-tree SHA-256
`f70de93b8e941a7dbc028e70cd0f1c2154ffb1919dc2a6e61b32856de7a2a6da`
(350 files, including then-untracked source). This pre-commit validation snapshot
was subsequently committed and pushed as `d8e712c8893ed411ba4b1a7f95ec25c441f12578`.
Its [development feedback run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37169878041)
passed all four jobs, including focused application, shared GUI, workflow syntax
and selected complete tooling suites. This feedback does not replace the separate
platform qualifications below. The pinned GUI supplier revision is unchanged. The checked-in retained group was regenerated to include
the reviewed service and browser patches; normal native configuration still
requires no supplier checkout or download.

The transfer adds native owned background work, bounded transactional content
services behind the host boundary, browser measurement/presentation scheduling,
retained DOM rows, framebuffer stride/pixel conversion, bounded SDL event draining,
exact named-test selection, conservative affected-suite CI, desktop launchers,
a verified portable-package entry point, and retained-SDK development runtime
closure/environment checks. Application features remain in the shared application;
platform hosts implement generic capabilities. DSP and simulation implementations
were not imported.

Qualification used isolated copies of all selected source, including uncommitted
new files, with before/after inventories and two compilation/test workers. Relevant
source identities were compared before reusing results. The full native snapshot
was `d1b608cf001aa06a3f18f835497fd21df3cbdae4081e39955b07409d5b860eef`;
the native GUI snapshot was
`2ef361d23985c3cfec79f10134569217237416ed34fd3d9defd4d129bd1f8e10`.
The final browser/file/sanitizer snapshot was
`1068ca5d2790ce76a663028f0ea07e4bc1b95382ce0461f3f207d341a6d8be08`.
The final differences are documented fixes/tests below, documentation, and SDK/CI
changes covered by their final native/tooling checks; unrelated earlier GUI
results are reused only for unchanged relevant code and dependencies.

| Scope | Observed result |
| --- | --- |
| Native full wrapper | Initially 55/56 CTest entries; 1,335/1,336 executed Python cases passed, with two explicit native Windows exclusions and no skips. The sole failed synthetic header-mirror fixture lacked its new runtime-header input. After adding that input, its entire 34-case suite passed with all byte, timestamp and stale-output assertions preserved. The earlier failed aggregate remains failed; the repaired suite completes the required local coverage alongside the other unchanged 55 entries. |
| Native GUI | Clang 19 built all selected hosts using retained distro toolkit inputs. Initially 46/47 GUI CTests passed with no skips; the sole failure was the same repaired header fixture. Actual FLTK, Rev, SDL, terminal/framebuffer/hosted smoke, scaled/clipboard, touch, embedding and visual checks passed. |
| SDK/build iteration | 115 focused cases passed, with one explicit native Windows exclusion; two additional runtime-closure probes passed using retained `patchelf`. Coverage includes environment injection, exact selection/fixtures, transitive private runtime closure, missing closure recovery and changed output rejection even without relinking. |
| Package/CI helpers | 221 cases across nine strict suites passed; after completing the browser asset inventory, all 76 APT/distro/distribution cases passed again. Historical package schema recipes retain their original verified bytes. |
| Portable package | The explicit wrapper produced a TGZ, verified relocation, ran its CLI and built an external installed CMake consumer. Runtime closure audit passed. This native Trixie build records observed GLIBC 2.38 requirements; it is not a Bookworm binary qualification. |
| Retained Wasm SDK | Release build and offline HTML generation passed without preparing or downloading an SDK. Nine selected core/Worker/browser/Wasm CTests passed; the affected file-helper and package checks passed again after the BOM correction. |
| Browser execution | Actual Firefox 153.4.0 passed hosted, Wasm and single-file offline checks against the final helper: editing, accessible names, geometry, retained rows, bounded import, atomic rejection, export dialog, pagehide/navigation and cleanup. Offline execution reported no HTTP(S) resources and enforced its no-connect CSP. |
| Sanitizers | Four address/undefined/leak-sanitized lifecycle, native worker, file-content and framebuffer embedding tests passed, including the final BOM regression. |
| Static checks | Python 3.9 grammar, GUI boundary guard, documentation links/JSON, workflow syntax with retained actionlint 1.7.12, and diff whitespace passed. |

Read-only review found that the browser decoder discarded a leading UTF-8 BOM
while the native reader preserved it. The browser now preserves that character;
the same BOM-prefixed content is rejected by shared printable-ASCII validation.
Node preservation and native atomic-rejection regressions passed. Review also
caught and repaired missing runtime-integrity checking on no-relink SDK builds.

The initial display/browser attempts were blocked by the execution sandbox's
socket policy before browser assertions. The initial sanitizer attempt failed
because LeakSanitizer cannot operate under the restricted tracer. Socket-enabled
and unrestricted sanitizer repeats passed without disabling checks; failures are
retained separately. All launched browser, display, compiler and test children
were joined before releasing their owners.

Limits at that revision: no new stock Bookworm execution, native Windows/ARM run,
or native Debian/Arch/Gentoo installation qualification was performed. The hosted
development feedback result above was obtained after the local validation snapshot.
The retained Wasm consumer was exercised; new SDK producer identities were not
built or published. Real native toolkit controls/prompts and the host file service
with a fake selector/real files were tested separately; actual FLTK/Rev file
import/export dialogs were not exercised end to end. Browser export qualification
opened and cancelled the Download dialog; Node tests exercised download offering,
not a user saving a file. Touch and display-driver fixtures do not establish
physical touchscreen, VR or Arduino support. Native regular-file operations are
byte-bounded but a stalled OS call can delay joined shutdown, as documented in
the GUI guide.

Raw receipts, source inventories and failure diagnostics remain under
`.agent-work/artifacts/transfer-root-v1/`, the referenced worker artifact trees,
and `build/agents/transfer-root-v1/`. The maintained implementation and limits are
in the [GUI guide](gui-boundary.md), [SDK guide](sdk.md),
[build guide](building.md), [testing guide](testing.md), and
[development-speed guide](development-speed.md).

## Offline checkout and retained SDK inputs (2026-10-03)

The completed implementation snapshot before this validation entry has source-tree
SHA-256 `9eb82e3315aed150828944e24bebf80f82574eb0a07801a03bc96dc4e27ffab3`
(311 source files). It includes offline release-recovery verification, opt-in
CTest stop-on-failure, the complete retained GUI group, explicit `--gui` selection,
direct CMake fallback and the optional Windows host-tool bootstrap helper.
The GUI group contains exactly three files totaling 5,961,400 bytes.

A clean source export without Git metadata or an external GUI supplement passed
in a fresh network namespace with only loopback available:

- Default Release `test --full`: 53/53 CTest entries, with 1,274 Python outcomes
  passed and two explicitly excluded native Windows cases.
- Release `test --gui --gui-backends terminal,framebuffer,hosted-web --label gui`:
  23/23 CTest entries; all 59 included Python outcomes passed.
- Repeating the GUI command left every restored file's modification time unchanged
  and Ninja reported no work. Cold build plus tests took 75.675 seconds; the repeat
  took 6.665 seconds with two compile/test workers.
- Direct CMake with `FOUNDATION_BUILD_GUI=ON` and no source selectors configured
  successfully using checkout-contained inputs. Default core GUI support stayed off.

A five-sample warm hashing comparison measured approximately 6.4 milliseconds of
additional source-hash time per pass for the retained group on this host. This is
an observation with uncontrolled OS caching, not a cross-machine timing guarantee.
Documentation and whitespace checks passed. Publication review verified every
implementation file still matched this tested snapshot; only this validation
entry was subsequently added.

The native Windows bootstrap's eight opt-in diagnostics were not executed here;
its three original retained ZIP hashes/layouts and source were inspected. Fresh
stock Bookworm, FLTK/SDL/Rev execution, prepared Wasm consumers and native Windows
remain outside this local qualification. No SDK recipe, hosted test matrix or
ordinary-build dependency preparation changed. Detailed raw results remain under
`build/agents/checkout-sdk-independence-v1/`; this maintained summary preserves the
observed scope independently of ignored local evidence.

## Current public delivery evidence (2026-10-03)

The four SDK base qualification and public publication runs completed successfully:
[Linux x64](https://github.com/mirage335-colossus/software-foundation/actions/runs/36979799032),
[Linux ARM64](https://github.com/mirage335-colossus/software-foundation/actions/runs/36979801780),
[Windows x64](https://github.com/mirage335-colossus/software-foundation/actions/runs/36977319633)
and [Wasm](https://github.com/mirage335-colossus/software-foundation/actions/runs/36977322721).
Their publication receipts were independently fetched and checked. The consumer
selectors identify these retained recipes exactly:

| Target | SDK recipe SHA-256 |
| --- | --- |
| Linux x64 | `bdd39974a891e6161d667bbaa0ff2c1894fe9f188ed76d47d1ad6c896972c9f8` |
| Linux ARM64 | `88c7d871f5cf6210cb4dac6874e666a275dd5f359d42439369a7206b39dbe109` |
| Windows x64 | `cd16aeb6bd2dff13115d456ffbea2d166db37427106a5e03961926f840f10feb` |
| Wasm | `783adcbd828ccd3dce72fefa575755d0d94f4eec528634bd4a9bdce7341356d5` |

The [GUI source publication](https://github.com/mirage335-colossus/software-foundation/actions/runs/36979568787)
also passed and was independently read back. Its group identity is
`10d22dd104c3c3de38b979b5c5d9b6d3e9cea827d0dc748b87d97baee081c8b3`.
New producer code can define a new recipe identity without invalidating an explicit
consumer selection of verified retained bytes; never relabel an old archive.

The [public screenshot run](https://github.com/mirage335-colossus/software-foundation/actions/runs/36977734580)
passed and published [seven actual backend captures](https://github.com/mirage335-colossus/software-foundation/releases/tag/screenshots-36977734580-attempt-1).
The publication receipt and images were independently downloaded and verified.
Framebuffer, FLTK and Rev captures show the same geometry and palette, with small
native-font rendering differences. The gallery also contains SDL, terminal,
hosted web and Wasm captures. Browser tooling is a host prerequisite, outside the
SDK and application payload. The gallery separately verified the browser's
namespace and seccomp sandbox; that evidence does not imply that every other
browser test performs the same sandbox-status probe.

The [complete Latest workflow](https://github.com/mirage335-colossus/software-foundation/actions/runs/37070391587)
passed all 45 jobs at `4787098055de7190da730a577d6e0946c8849f2d` and
published [the certified application release](https://github.com/mirage335-colossus/software-foundation/releases/tag/release-37070391587-attempt-1).
All eleven certification batches passed: 106 logical checks across 66 physical
executions, with no warnings or omitted requirements. The policy covers Linux
x64 and ARM64, Windows x64, and Wasm; its recorded environments include Debian
12 and 13, Ubuntu 24.04, Windows Server 2022, Chromium and Firefox. The 106 checks
comprise 44 archive, 19 source, 19 recovery, 12 ABI and 12 APT results.

| Exact delivery identity | SHA-256 |
| --- | --- |
| Release inventory | `b386888b83f234662662c22683c72de3b93824a7aa789569411e0d2061fa2c4e` |
| Certificate | `273aa9762ea2b474125d568eec57cf75ace01729c08f90b593fa2dc87af1291d` |
| Final Latest receipt | `a6a15a755f94e2a11d34c61f3015f83372a205e29f6e916fdc93d3e4dc7cab0d` |

The final receipt was independently fetched from successful job `111096703678`;
the remote Latest endpoint identified ordinary public release `402199557`, with
25 assets. Independent certificate readback reproduced all 106 results, rehashed
2,761 evidence files and confirmed the original 23 asset identities were unchanged.
It rehashed 55 source inputs and checked 22 payload input identities against retained
metadata; the hosted jobs performed the full payload download and execution.
This bounded independent audit is not a second local replay of all payloads or
evidence of a separately network-disabled recovery run.

The [focused Windows GUI run](https://github.com/mirage335-colossus/software-foundation/actions/runs/37069286298),
release producer and published-release certification all passed. The producer and
each source/recovery execution passed 68 CTest entries and 721 tool cases, with 60
explicit platform exclusions. Certification passed all 18 Windows logical checks,
including six archive backends and installed consumers. The verified static SDK
configuration, graphics cleanup and private compiler-owner completion all passed;
no incomplete cleanup was observed. These results qualify the recorded toolset and
runner, not every older Windows client or an exhaustive process/network trace.

Application delivery, full release certification and signed package-channel
installation are separate qualifications. The first live signed-channel run
[37087057851](https://github.com/mirage335-colossus/software-foundation/actions/runs/37087057851)
failed during preparation when a per-reference loop replaced the callable needed
for the next backend. It created no channel release or tag, and the application
Latest was unchanged. Native signed-channel acceptance requires its own completed
client evidence, recorded separately below. A real signed two-backend fixture reproduced the exact
failure before the correction and passed afterward; the complete affected suite
passed all 30 cases without exclusions. Signature, retained-reference and package
validation remain intact.

The corrected publication run
[37089527346](https://github.com/mirage335-colossus/software-foundation/actions/runs/37089527346)
at `ab095d83f2dfa77caa11e303e1ae52d38530fe16` published the unchanged
certified application bytes in the signed x64 package prerelease
`distro-0.1.0-x86_64-r1-s1`. Its manifest identity is
`43eaa54dfab1cc1204b7d5e81172a6c6b4b08ce789901f46cc73de9eea46701f`.
Native Debian Bookworm, Debian Trixie and Ubuntu checks passed; Arch and Gentoo
failed after successful signature checks when reading decoded cleartext output.
Arch GnuPG 2.4.9-3 returned exactly one terminal LF fewer than the signed Release;
this was reproduced with the distribution verifier and its published patch.
Gentoo GnuPG 2.5.21 left the requested decoded filename absent, consistent with
its deferred named-output finalization. The failed run did not accept the channel.
Its immutable signed bytes are preserved. The later-discovered Gentoo recipe
defect described below means this revision remains permanently unaccepted; a
consumer-side correction cannot repair that signed payload.
The correction captures checked verifier stdout and allows only the observed
terminal framing LF difference while retaining both signatures and exact detached
content authentication. Ten affected cases passed with stock GnuPG; 59 APT, native
channel and distribution cases passed using the extracted official Arch verifier,
with no exclusions. The isolated verifier used the Debian host runtime with
Arch's matching private libassuan; this is not native Arch installation qualification.

Native-only requalification
[37095133010](https://github.com/mirage335-colossus/software-foundation/actions/runs/37095133010)
at `592ee7bb69c63e9eda4c30be5b161e870c1187cc` passed all three APT
clients. Arch passed signed-distribution verification, then failed strict process
completion after `pacman-key --init` returned while descendants remained alive.
This is separate from metadata verification and does not qualify native Arch
installation. Its retained failed evidence preserves the keyring initialization
output. The correction groups initialization, import and local trust in one
dedicated worker, shuts down only its container-owned GPG home, then joins every
adopted child before exiting. The outer strict supervisor is unchanged. Twelve
focused cases passed, including the original unmanaged-daemon failure, corrected
completion and an unrelated keyring whose same daemon identity remains usable.
That local regression does not replace native Arch package-manager qualification.
Gentoo passed signed-distribution verification and prepared activation, then its
first `emaint sync` failed on an unauthenticated metadata request with HTTP 403
rate-limit status. The existing verified generation was preserved. The retained
error does not identify the endpoint or rate headers, so it does not establish
whether a primary shared-IP quota or secondary limit caused the refusal. The
client already obtains asset bytes through public release URLs; a one-page exact
refresh needs six REST metadata requests, separate from those data transfers.
The bounded public retry correction passed 31 focused client cases, including
rate recovery, exhausted budgets, complete-pagination restart and preservation of
an actual signed active generation. Those local tests use controlled responses;
they do not establish that the hosted runner's public quota is available.

Native-only requalification
[37097683752](https://github.com/mirage335-colossus/software-foundation/actions/runs/37097683752)
at `1d96a7c1e30966074af867c8c596456b1ecb51c3` passed native Arch
and all three APT clients. Gentoo completed prerequisite installation but its first
public `emaint sync` rejected asset metadata; acceptance was skipped. Independent
metadata readback identified fourteen Debian filenames whose plus signs are
correctly percent-encoded as `%2B` in GitHub's public download URLs. The client
incorrectly compared those URLs against unencoded path components. A focused
regression reproduced the error before correction; all 32 public-client cases
passed after canonical component encoding, with no exclusions. The checks still
reject foreign, double-encoded, slash-substituted or query-modified URLs and verify
exact downloaded size/digest before activation. One fixture attempt placed a
private test key inside the checkout and correctly failed the key-location guard;
the complete successful run used an owned temporary root outside the checkout.
These local results do not relabel the failed native run or establish Gentoo
installation. The subsequent native-only run
[37099357741](https://github.com/mirage335-colossus/software-foundation/actions/runs/37099357741)
at `ecbc3eba735ae343158cf5eb3a2136f1199b2dea` passed the three APT
clients and Arch, then was cancelled before acceptance after the immutable
recipe defect below was identified. Its cancellation is not a qualification pass.

ARM publication
[37095147094](https://github.com/mirage335-colossus/software-foundation/actions/runs/37095147094)
at `592ee7bb69c63e9eda4c30be5b161e870c1187cc` completed package
preparation but GitHub rejected its first tag creation and failure retention with
HTTP 403 while primary quota remained positive. Independent authenticated readback
found neither its channel tag/release nor its transport tag/release. Default-branch
workflow bytes changed during preparation, which is consistent with GitHub's
[workflow-write permission restriction](https://docs.github.com/en/rest/releases/releases#create-a-release);
the retained response omitted the error message, so the exact cause is unproven.
No native qualification ran and no signed channel was published by this attempt.
The replacement uses the current workflow revision and preserves the certified
application inputs. Running replacements are not qualification evidence.

A subsequent upgrade-path review found that Arch payload checks alone could
accept unchanged installed files without proving a package-revision advance.
The correction queries every installed backend's native package version after
each round and rejects stale, duplicate, missing or foreign package records.
Acceptance also checks the exact requested predecessor tag and manifest digest.
All 14 focused native-checker cases passed without exclusions on the Linux host
with private GnuPG sockets available. An earlier sandboxed attempt could not start
the unrelated-keyring fixture and failed; it is not counted as passed coverage.
These regressions do not replace the required live two-revision native upgrade.

Inspection against Gentoo's EAPI 8 preparation contract found that the existing
schema-3 recipe omitted the required `eapply_user` call. A phase-invariant fixture
reproduced old-recipe failure and corrected schema-4 success. New production now
emits schema 4; complete schemas 1–3 inventory hashes are unchanged, and a real
signed schema-3 channel still replays exactly through the current verifier.
All 21 recipe and 31 distribution cases passed without exclusions. Native Portage
configuration also now names each selected package's exact license token rather
than an unsupported partial token glob; all 15 checker cases passed. The combined
recipe, distribution, checker and public-client snapshot passed all 99 cases with
no exclusions. These fixes
do not make the historical x64 r1 recipe installable: it remains unqualified for
Gentoo. A new immutable revision must establish the first successful installation,
followed by a newer revision for actual cross-frontend upgrade qualification.

Corrected x64 publication
[37100870828](https://github.com/mirage335-colossus/software-foundation/actions/runs/37100870828)
at `a3a214a88d61db2cf0e534830fccbad7ff9df4e0` published
`distro-0.1.0-x86_64-r2-s2`, with manifest
`d309a5902bac556b17f9a8e46ca5e40518dc4ca1bbcbf505a6d8537c53e587ee`.
All three APT checks and Arch passed. Gentoo synced the signed channel and
successfully prepared, installed into the staging tree and created the schema-4
core binary package. Its first native `emerge` then rejected Mesa's dependency on
`libglvnd[X]` because the minimal host's provider lacked that USE selection.
Acceptance was skipped; successful recipe preparation is not completed native
installation. This run left the signed revision unchanged and unaccepted.

A resolver-only comparison used the exact failed job's retained Gentoo stage3
and Portage image identities, the same five signed runtime atoms and strict
binary-only options. The baseline reproduced the `libglvnd[X]` refusal; adding
only `media-libs/libglvnd X` resolved 30 binary packages. The observed binary
index digest was
`9c00a3191248fbbf8308900031b784fd7ec34c8d7cd85acfa4eb891ac328df13`.
Both comparisons used the same private namespace root user/group accommodation
and joined all descendants. No dependency or application was installed or
compiled; this probe establishes dependency resolution, not native acceptance.
The focused checker suite passed all 16 cases with no exclusions, including
configuration ordering, preservation of unrelated settings and propagation of a
missing-binary failure.

Requalification
[37108497393](https://github.com/mirage335-colossus/software-foundation/actions/runs/37108497393)
at `cb2072c9384d9a3abdfd5081e2a1ccc4fdcd159a` subsequently passed all seven jobs
and accepted the same
[`distro-0.1.0-x86_64-r2-s2`](https://github.com/mirage335-colossus/software-foundation/releases/tag/distro-0.1.0-x86_64-r2-s2).
All three APT environments, Arch and Gentoo installed every selected variant,
verified exact payloads and self-checks, repeated the native update/refresh, and
removed the packages. Independent readback verified the signature, all five
native receipts and the exact acceptance marker. Comparison with the original
pre-qualification snapshot confirmed release ID `402367320` and all 70 asset IDs,
names, sizes and digests were unchanged. Packaging remains bound to
`a3a214a88d61db2cf0e534830fccbad7ff9df4e0`; qualification uses the later corrected
helper. Latest remains `402199557`. This is the first accepted x64 installation;
its receipts record `upgrade_from: null` and establish initial installation only.
The later r2-to-r3 upgrade evidence is recorded below.

The corrected Gentoo native step in
[run 37108497393](https://github.com/mirage335-colossus/software-foundation/actions/runs/37108497393)
passed in 48 minutes 23 seconds. Its two-revision path repeats the complete channel
verification and installation sequence. The upgrade-only Gentoo budget therefore
allows 150 minutes inside a 180-minute job; other scopes and individual native
verification command deadlines remain unchanged. A focused negative control with
the previous fixed deadline rejected the Gentoo upgrade case. The updated fixture
exercises timeout cleanup for all three frontend kinds, with and without a prior
revision; all 16 checker cases passed without exclusions. Workflow lint and
Python 3.9 syntax checks passed. No timeout failure is claimed for the completed
initial run, and a larger limit does not qualify an unexecuted upgrade.

The x64 r3 publication and upgrade run
[37112267197](https://github.com/mirage335-colossus/software-foundation/actions/runs/37112267197)
at `d8295ec1724ee1a8da26b4d07a22d9c5ed564cac` published the signed revision
`distro-0.1.0-x86_64-r3-s3`, manifest
`383f1bc7e510bc2a375d86ab3364adc7af6507e85d1a8af1bb6ddea170816a32`.
All three APT environments and Arch passed the actual r2-to-r3 upgrade. Gentoo
installed all seven variants at both native versions (`0.1.0-r1` then `0.1.0-r2`,
corresponding to channel package releases 2 and 3). Its fourth and final repository
sync returned HTTP 500 before the second round's payload/self-check verification
and removal. No complete Gentoo receipt was produced and acceptance was skipped.
This was a failed public read, not an execution-budget timeout. The exact failing
URL was not retained; the raw error shape is consistent with the public asset
retrieval path. Independent evidence review rehashed the complete failed bundle,
and remote readback confirmed the original r3 and accepted r2 inventories of 70
assets each were unchanged.

The public client now applies its bounded GET retry policy to transient server
responses on metadata and asset reads. An identical HTTP-500-then-valid-body
comparison failed with the old client after one GET and no destination; the
corrected client returned exact bytes after two GETs and closed the failed
response. The focused suite passed all 43 cases with
no exclusions: recovery and exhaustion for each selected HTTP status, full-page
restart, shared wait limits, whole-transfer deadlines, closed partial responses,
unchanged permission/origin/content checks and preservation of a real signed active
generation. These controlled cases do not qualify the incomplete native upgrade;
that requires a subsequent complete run against the unchanged signed revision.

The initial ARM64 signed channel
[`distro-0.1.0-aarch64-r1-s1`](https://github.com/mirage335-colossus/software-foundation/releases/tag/distro-0.1.0-aarch64-r1-s1)
was accepted by
[run 37098054299](https://github.com/mirage335-colossus/software-foundation/actions/runs/37098054299),
with all seven jobs successful. Packaging and qualification both used
`1d96a7c1e30966074af867c8c596456b1ecb51c3`; the signed manifest is
`dac4345be2d503ace832a53972cd8f7d647131a3ce54ee8d607072f819694152`.
Native Debian Bookworm, Debian Trixie and Ubuntu 24.04 each installed every selected
backend, checked exact payloads and self-checks, refreshed repeatedly and removed
the packages. Independent readback verified the trusted signature, all 70 remote
asset identities, all three native receipts and their exact acceptance marker;
the application's Latest release remained `402199557`. Hosted jobs replayed the
complete payload; the independent readback checked signed controls and retained
native evidence. This initial installation records `upgrade_from: null` and does
not establish a version upgrade. ARM64 Arch/Gentoo frontends remain outside the
native matrix.

The subsequent ARM64 channel
[`distro-0.1.0-aarch64-r2-s2`](https://github.com/mirage335-colossus/software-foundation/releases/tag/distro-0.1.0-aarch64-r2-s2)
passed all seven jobs in
[run 37103102371](https://github.com/mirage335-colossus/software-foundation/actions/runs/37103102371)
at `a3a214a88d61db2cf0e534830fccbad7ff9df4e0`. Its signed manifest is
`57d7632206b6a329d386a1b954d08a396acc2949291b578e19c5506d04966544`.
Every APT environment installed and checked all seven variants at `0.1.0+r1`,
upgraded them to `0.1.0+r2`, repeated the refresh/install operation, checked exact
payloads and self-checks, then removed them. The exact accepted r1 tag and manifest
are recorded in every upgrade receipt. Independent readback and peer review
reconciled both 70-asset inventories, signatures and native receipt identities;
application/SDK input identities were unchanged, and Latest remained `402199557`.
This establishes the observed ARM64 APT version upgrade.

Native-only requalification of
[`distro-0.1.0-x86_64-r3-s3`](https://github.com/mirage335-colossus/software-foundation/releases/tag/distro-0.1.0-x86_64-r3-s3)
subsequently passed all seven jobs in
[run 37121695761](https://github.com/mirage335-colossus/software-foundation/actions/runs/37121695761)
at `6b911833bc6e2eb17058bb1e65d1eb6b0e701968`. Its original packaging revision
remains `d8295ec1724ee1a8da26b4d07a22d9c5ed564cac`, and its signed manifest
remains `383f1bc7e510bc2a375d86ab3364adc7af6507e85d1a8af1bb6ddea170816a32`.
Debian Bookworm, Debian Trixie, Ubuntu 24.04, Arch and Gentoo each installed and
checked all seven variants from accepted channel r2, upgraded to r3, repeated
repository refreshes, verified exact package versions, payloads and self-checks,
then removed the packages. APT repeated exact-version installation requests;
Arch repeated `pacman -Syu`.
The native version transitions were `0.1.0+r2` to `0.1.0+r3` for APT,
`0.1.0-2` to `0.1.0-3` for Arch, and `0.1.0-r1` to `0.1.0-r2` for Gentoo.
Every receipt binds the exact accepted r2 tag and manifest recorded above.

Independent readback verified both trusted signed manifests, complete remote
asset inventories, all five native receipts and the exact acceptance marker.
Comparison with the original r3 publication snapshot confirmed all 70 asset IDs,
names, sizes and digests were preserved. A further readback confirmed the accepted
r2 predecessor's 70 assets and the application's Latest release `402199557` with
all 25 assets were unchanged. It also rechecked source tags and release bodies.
Hosted native jobs replayed full payloads; this independent audit checked signed
controls, retained execution evidence and remote metadata without repeating the
multi-gigabyte payload replay locally. Application and SDK input identities were
unchanged by these package revisions.

Earlier application runs remain useful failure evidence; none are relabeled as
successful qualification. Run
[36994657303](https://github.com/mirage335-colossus/software-foundation/actions/runs/36994657303)
passed the complete source gates, four application producers and assembly, then
stopped when its first normal candidate was observed as Latest despite the false
publication request. The exact release was reconciled and changed to prerelease;
its source tag and all 23 assets were preserved and the Latest endpoint was
independently confirmed absent. Candidate publication now requires prerelease
status until certified promotion. This failed run is not qualification evidence
for certification or Latest. The later all-GUI candidate
[37025224490](https://github.com/mirage335-colossus/software-foundation/actions/runs/37025224490)
passed source gates, all four producers, assembly and public candidate readback.
Seven of eleven certification batches passed; four correctly failed on the source
fixture and Windows lifetime defects described below. Its failed certificate was
attached immutably, promotion was skipped and the final verdict failed. These
results are preserved, not counted as successful release qualification. The later
successful Latest evidence is recorded above; native signed channels have their
own distinct client requirements.

The subsequent candidate
[37045706923](https://github.com/mirage335-colossus/software-foundation/actions/runs/37045706923)
at `52c5adf12c665c5743395bfe0677c33c7126d366` passed all six Windows
archive checks. Its source and recovery executions each passed all 67 CTest entries
and all 31 tool suites: 693 executed cases passed, with 60 declared platform
exclusions. Their retained evidence hashes were independently verified. Both outer
executions nevertheless failed strict completion: the source command left VCTIP
and another unclassified process alive; recovery left the selected toolset's
MSPDBSRV alive. The inner passes do not establish complete release qualification.
This exposed compiler-capable build and installed-consumer commands outside the
existing narrow graphics-probe owner. Its failed certificate was attached immutably,
promotion was skipped, and independent readback verified the public evidence bytes,
original asset digests and prerelease status. The candidate remains ineligible for promotion.

The next run,
[37061687505](https://github.com/mirage335-colossus/software-foundation/actions/runs/37061687505),
stopped at its Windows source gate before building release archives. A new unit
fixture compared the temporary directory's short Windows path with its canonical
expanded path. The fixture now canonicalizes its own root before testing exact
selected-toolkit identity; production validation and the independently qualified
native compiler-service behavior are unchanged.

Run [37064137298](https://github.com/mirage335-colossus/software-foundation/actions/runs/37064137298)
passed the full source gates. The Windows tools inventory was independently
verified: 709 executed cases passed across 32 suites, with 60 declared platform
exclusions; all 33 CTest entries passed. Its three non-Windows producers passed.
The Windows producer compiled its targets but rejected a surviving versioned
package-manager executable. Inspection of the exact retained integration script
found its default post-build `z-applocal` hook. The observed temporary executable
path also matches the supplier's background metrics implementation; the child
command line and any completed network request were not captured. This is a
failed producer, with no candidate assembled or promoted. Static SDK consumers
now explicitly disable the unnecessary deployment hooks and metrics. The later
native producer, source and recovery verification recorded above passed with
those settings.

## Native process cleanup evidence

The strengthened Windows process test observes the exact descendant handle,
confirms Job Object membership and requires it to be signaled before termination
returns. This exposed a real cleanup race; an empty active-process count alone did
not prove that every observed child had finished. The implementation now pins and
joins descendant handles under one deadline, detects membership uncertainty and
preserves cleanup failures instead of reporting later success.

At `73f364feb08da1743fef52820ededd046bc801fd`, focused native diagnostics passed
20 complete repetitions on both
[Python 3.12.10](https://github.com/mirage335-colossus/software-foundation/actions/runs/37024667217)
and [Python 3.14.7](https://github.com/mirage335-colossus/software-foundation/actions/runs/37024672042).
Each run recorded 720 passed cases and 140 explicit Linux-only exclusions, with no
failed or internally skipped executed cases. Both complete inventories were
independently fetched and verified against the exact source hashes, interpreter
binary and version. These focused diagnostics establish the observed cleanup
behavior; they do not replace the complete release gates.

A later full candidate exposed two separate paths: delivered source tests assumed
a Git checkout, and a browser wrapper deleted its profile before all descendants
finished. The source fixture now creates its own temporary Git repository; the
production Git check remains intact. A discriminating source-archive check outside
all Git ancestors failed before the correction and passed afterward. Browser and
driver wrappers now own and join their inner process trees before copying logs or
removing profiles, with uncertain cleanup preserved as failure.

The focused [native Windows host diagnostic](https://github.com/mirage335-colossus/software-foundation/actions/runs/37041245500)
at `59ec5f6390d0fd8a8fe72172c153173b06597552` passed Firefox 156.0.1
automation and immediate profile removal. The compiler case failed and retained
the exact verified Job member: MSVC 14.44.35207 `vctip.exe`, observed executable
with wait state 258 after `cl.exe` exited. This identifies a compiler helper
lifetime issue; it is not a passing compiler or release qualification. The failed
bundle was independently fetched and all twelve consumed source hashes checked.

At `356e0cb29d8762ae6deddceb537bee9451945cad`, the corrected production
compiler path passed [one native diagnostic](https://github.com/mirage335-colossus/software-foundation/actions/runs/37044777895),
then twenty complete repetitions each on
[Python 3.12.10](https://github.com/mirage335-colossus/software-foundation/actions/runs/37045035782)
and [Python 3.14.7](https://github.com/mirage335-colossus/software-foundation/actions/runs/37045040414).
Each repeated run passed all forty cases without exclusions or internal skips.
Every compiler case actually terminated and joined the exact selected VCTIP helper
and verified x64 PE output; every Firefox 156.0.1 case completed automation and
immediate profile removal. Both bundles were independently fetched, with all
twelve consumed source hashes and complete case inventories checked. Their Windows
runner image was `20260927.320.1`. The compiler-specific helper policy preserves
strict completion for other commands; these diagnostics do not replace full
release qualification.

At `7abbdaaf3566ca733a88ff8551204b533cac0915`, explicit build owners
passed [one native check](https://github.com/mirage335-colossus/software-foundation/actions/runs/37060552322)
and twenty repetitions each on
[Python 3.12.10](https://github.com/mirage335-colossus/software-foundation/actions/runs/37061018594)
and [Python 3.14.7](https://github.com/mirage335-colossus/software-foundation/actions/runs/37061021979).
Each repeated run passed all sixty cases without exclusions or internal skips;
all thirteen consumed source hashes were independently checked. Every repetition
created two concurrent private PDB servers, pinned the control server's exact
handle, and proved it remained alive through the other owner's cleanup and a
second compile. Both owners then joined their selected helpers and immediately
released their output directories. The graphics compiler and Firefox cleanup
cases also passed. The selected toolset was MSVC 14.44.35207 on runner image
`20260927.320.1`. These results qualify the observed endpoint isolation and
cleanup behavior for these inputs; complete release certification remains a
separate gate.

## Delivery workflow expansion

The current update replaces Actions artifact transport with per-run private draft
release bundles, adds explicit legacy SDK migration, an initial seven-host gallery
workflow and the `_Publish new Latest release` orchestration. The local focused
checks passed 32 transport, 108 workflow/retention, 30 GitHub delivery and 22 GUI
boundary cases. The boundary cases include actual incremental CMake rebuilds when
nested headers are added or changed. Documentation links and workflow syntax pass.
The screenshot and Latest suites passed 17 and 10 cases respectively. Combined
Release verification with distribution enabled passed all 38 CTest entries across
one complete invocation and one targeted rerun: 770 inner Python cases passed,
with two explicit native-Windows exclusions and no unexpected skips. The rerun
made the new incremental-header fixture timestamp deterministically newer than
its build stamp; all dependency-rejection assertions remain in place.
Subsequent integration passed all 41 CTest entries in one invocation: 832 inner
Python cases passed, with two explicit native-Windows exclusions and no unexpected
skips. This includes 36 transport, 31 delivery, 24 signed-distribution, 20 browser
prerequisite and 13 opaque-preservation cases. Workflow syntax and documentation
checks passed. The distribution cases include actual signed packages, exact Git
source proofs, certificate replay and uncertain-creation recovery. The separately
added retention verifier passed all thirteen cases through its registered CTest
entry, with no exclusions or skips.

Candidate [36943440689](https://github.com/mirage335-colossus/software-foundation/actions/runs/36943440689)
passed all nineteen jobs at `fd646d616c129a6fede37e0ea7e7522d90565970`, including
concurrent draft transport and fresh Linux x64, Linux ARM64 and Windows x64 archive
consumers. GitHub permits duplicate draft tags: confirmed atomic tag creation now
selects the sole initializer, with bounded read-only visibility reconciliation.

Expanded candidate [36948123794](https://github.com/mirage335-colossus/software-foundation/actions/runs/36948123794)
passed at `2bd67a29dd3a6c3d91fbae32757bad29c3860797`, including the
signed-distribution suite and three native archive consumers. All nineteen jobs
passed: Linux x64 and ARM64 each recorded 784 passing Python cases, Windows x64
recorded 529, and no incomplete or skipped case outcomes were accepted. Platform
exclusions remain explicit. The distribution job passed 7 Debian, 17 Arch/Gentoo
and 24 publication cases plus the actual signed Bookworm client transaction.

All four exact legacy SDK imports passed at
`2332d31e77e5b632e3f7d8a7b5031153e794e9dc`: browser
[36942942745](https://github.com/mirage335-colossus/software-foundation/actions/runs/36942942745),
Linux ARM64 [36942949383](https://github.com/mirage335-colossus/software-foundation/actions/runs/36942949383),
Linux x64 [36942956015](https://github.com/mirage335-colossus/software-foundation/actions/runs/36942956015)
and Windows x64 [36942962164](https://github.com/mirage335-colossus/software-foundation/actions/runs/36942962164).
Each retained complete original proof bytes and emitted exact version-2 replay
identities; import establishes storage preservation, not new SDK qualification.
The full manifests and completed producer identities were independently checked.

Opaque preservation [36943434563](https://github.com/mirage335-colossus/software-foundation/actions/runs/36943434563)
retained 35 selected archives totaling 18,494,607,185 bytes in private draft bundles.
Independent [readback 36949071982](https://github.com/mirage335-colossus/software-foundation/actions/runs/36949071982)
passed for all 35 archives at `c2281bba00804bd7186f332098ff25576feded0a`.
The complete report and every receipt were fetched and bound to manifest asset
`604516921`, SHA-256 `94234661c4c45a96404f8115360cd5528d4df9d2216d833f4e6bcaef9a32feb4`.
After rechecking all original identities, a separately reviewed manual operation
deleted exactly those 35 originals and independently confirmed their absence.
A fresh API inventory on 2026-10-03 at 11:11 UTC confirmed 225 artifacts totaling
18,809,636 bytes; the largest was 461,803 bytes, with none at or above 1,000,000
bytes. The private preservation release retains
manual audit asset `604540708` (`cleanup-receipt.json`), SHA-256
`d834b495d696aa3ae42ad43ddc780d9a6d5f328d4cfe00789d57b03bf1a3f5f4`;
its complete uploaded bytes were independently read back. No workflow run,
unrelated artifact or preserved release bundle was deleted. No SDK recipe or
retained SDK group bytes changed in this update.

GUI source maintenance [36949360683](https://github.com/mirage335-colossus/software-foundation/actions/runs/36949360683)
retained the complete exact source group privately at
`8e0bd09bebf2fc16b35dd94750c7293a35ced1d9`; its bytes were independently fetched
and verified. The first host-browser gallery attempt passed its actual sandbox
and rendering preflight, then stopped because the restricted Wasm build path lacked
distro CMake. The repaired path installs ordinary host CMake/Ninja and explicitly
joins its authenticated virtual display. Thirty-three focused gallery cases passed,
with no skips, alongside actual local authenticated display, success/failure cleanup,
4 MiB log-cap and surviving-descendant rejection checks.

Hosted gallery [36951973933](https://github.com/mirage335-colossus/software-foundation/actions/runs/36951973933)
passed at `217ff90d01c25c419fc4e621515579f30668984e`. All seven actual surfaces
were independently downloaded, checksum-verified and visually inspected. FLTK,
Rev, SDL and framebuffer have closely matching layout; hosted web and Wasm agree
in widget geometry and appearance. The terminal preserves the shared controls
in its cell layout at 644 by 531 pixels; the other six images are 640 by 480.
The ordinary Chrome 154.0.8037.57 host passed namespace and seccomp sandbox
checks, and its authenticated 96-DPI Xvfb session reports joined cleanup.
Gallery manifest asset `604563666` has SHA-256
`9c9535b491791ade577c70a32b060b644bc40717d290f543e22efd361c7ad240`;
the separately verified private diagnostics bind the exact retained GUI selector
and contain no private display authorization file. `execute=false` retained
private evidence and a publication plan; it did not publish a public gallery.
At that revision, public base/application/certification/promotion execution was
a separate, unexecuted scope. See the current delivery record for later evidence.

Final candidate [36951980262](https://github.com/mirage335-colossus/software-foundation/actions/runs/36951980262)
passed all nineteen jobs at `217ff90d01c25c419fc4e621515579f30668984e`.
Linux x64 and ARM64 each passed 813 Python cases; Windows x64 passed 558.
All 33 screenshot fixtures passed on each native platform. Platform exclusions
were explicit, with no failed, skipped or incomplete case outcomes. The separate
distribution job passed all 48 cases and the actual signed HTTPS Debian client
transaction, including upgrade, tamper rejection and removal.

## Observed mechanisms

| Area | Executed evidence |
| --- | --- |
| Shared GUI | All seven hosts use one application-side widget/layout table; 28 native CTests passed, including actual framebuffer/FLTK/Rev captures at two sizes, with matching declarations and mean RGB error below 1.01/255; a retained offline source group passed 19 wrapper-driven GUI checks |
| Browser GUI | Actual Firefox 153.4.0 and Chromium 154.0.8037.57 passed hosted and compiled Wasm interaction, accessible-name, prompt-cancel, geometry and capture checks; geometry agreed across transports and engines |
| Agent coordination | 237 individual contract tests passed without skips; separate 128-process shared-file and disjoint-file checks preserved exact contributions, revision chains, acknowledgments and ownership closure |
| Prepared browser SDK | Verified supplier archives, complete binary/source/checksum group, path-with-spaces relocation, frozen-cache C++ compilation, retained Node execution, unchanged file inventory and retained-source recipe reconstruction passed; actual CMake GUI build, Node GUI contract, core/CLI contracts and relocated installed consumer also passed using Emscripten 6.0.10 and Node 24.19.0 |
| Browser engine qualification | Both actual browser engines repeated interaction, accessible-name, prompt-cancel, capture and cleanup checks against the prepared SDK's compiled output; parsed geometry was equal across engines |
| Descendant lifetime | Private Linux child-subreaper tests cover detached sessions, nested supervisors, timeout, caller exit, bounded receipts and unchanged caller process state; 20 executed cases passed and one Windows-only case was explicitly excluded |
| Native SDK preparation | All four pinned native core/GUI configurations resolved; actual all-GUI x86_64/ARM64 source production ran in Debian 12 Bookworm and sealed complete groups; exact fresh-runner consumer results appear below |
| Dependency and release contracts | Safe archive, complete inventory, recipe identity, mandatory release-owned copies, full source binding, corruption rejection and retained recovery fixtures passed |
| Runtime inspection | Actual ELF fixtures test architecture, ABI ceilings and private direct/indirect loader resolution; PE fixtures test bounded parsing, architecture and normal/delayed dependency closure |
| Distribution | Seven actual Debian payload/signature/update tests and 17 Arch/Gentoo generation/channel tests passed; combined archives select the requested backend without compilation, preserve shared files and provenance, and reject unknown executables, rollback, tampering and same-version replacement |
| GitHub delivery | 29 offline lifecycle/transport fixtures passed; they exercise exact inventories, immutable bytes, retained certification and promotion rejection, without remote mutation |
| Documentation | Local destinations, heading anchors, strict JSON and requirement-to-code/test references checked |
| Workflows | Eight workflows passed actionlint; 49 CI helper, 39 SDK-retention and 11 source-identity cases passed; hosted execution remains separate evidence |
| Installed documentation | Both manual pages passed formatting checks and relocated installation checks; Debian, Arch and Gentoo fixtures preserve variant-specific public manual names |
| Windows host graphics | 28 prerequisite fixtures and 15 artifact fixtures passed; exact pinned driver extraction, native WGL probing and cleanup passed; six actual Windows captures passed; complete prepared-SDK execution is reported with its exact replay status below |
| APT client adapter | Disposable-container preflight and descendant-timeout regressions passed; actual signed HTTPS install/update/tamper-rejection/removal passed in the hosted Bookworm workflow |

Combined native Release verification with distribution tests passed all 34 CTest
entries in one invocation, including the relocated installed consumer and both
manual pages. The signing suites used disposable local GnuPG agent sockets. Its
30 inner Python suites recorded 664 executed passing cases and two explicit
native-Windows exclusions.
The selected-linker native case passed separately on Windows as recorded below.
No unexpected skips were accepted. The preceding
portable native archive also passed complete inventory verification, relocated
execution and an independent installed-library consumer build.

The preceding address/undefined-behavior configuration passed both core and CLI
checks; the relevant core implementation is unchanged. Actual prepared-SDK
browser-target compilation, archive execution and installed-library consumption
also passed. The SDK inventory remained unchanged throughout those operations.
Current GUI-only changes were qualified separately as described above.

Reuse evidence only for unchanged relevant code, configuration, dependencies and
environment; documentation edits do not establish a new runtime result. These are
local implementation checks, not a complete release-policy certification.

## Hosted candidate and maintenance observations

Candidate [36930890192](https://github.com/mirage335-colossus/software-foundation/actions/runs/36930890192)
passed all nineteen jobs at `44a8687afc60ad630e0d96bf6147814a13189c99` on
Windows x86_64, Linux x86_64 and Linux ARM64. Source/tool, packaging, fresh
copied-archive consumer, sanitizer and distribution jobs succeeded. The disposable
Bookworm client exercised signed HTTPS refresh, installation, exact payload
verification, execution, upgrade, tampered-signature rejection and removal.
The corrected ABI fixture passed all 32 cases on native ARM64 with no exclusions.
The preceding fixture proof was independently checksum-verified; its source is
unchanged in this candidate.
These results qualify their exact inputs and environments, not every older runtime.

Cold SDK maintenance
[36922792668](https://github.com/mirage335-colossus/software-foundation/actions/runs/36922792668)
at `1126cdc3bbb7834a1200904f6ede6bad1f663451` produced complete sealed groups for
all four targets below. Subsequent checks reuse those exact binary/source/checksum
triplets on fresh runners; they neither rebuild nor relabel the SDKs. Recipe inputs
and all seven recipe identities remain unchanged.

The browser replay uses `44a8687afc60ad630e0d96bf6147814a13189c99`. Linux native
replays use `c137d29f383afc643dac384edd0bd425129127d5`; the Windows replay uses
`e2d14be3d21c5a0cbe98bdce9fcd4bb7b53192c4`. Changes after the candidate select
native SDL test drivers and repair configuration-aware CTest fixture discovery.
The core/package/sanitizer/APT implementations and the browser implementation
remain unchanged; their preceding successful checks apply to those same relevant
inputs. Every maintenance run uses `execute=false`.

| Target and replay | Observed result | Exact recipe |
| --- | --- | --- |
| [Browser Wasm 36930860584](https://github.com/mirage335-colossus/software-foundation/actions/runs/36930860584) | Passed: two core checks, 30 GUI/source checks, 651 tool cases; two explicit Windows-only exclusions, zero JUnit skips | `783adcbd828ccd3dce72fefa575755d0d94f4eec528634bd4a9bdce7341356d5` |
| [Windows x86_64 36935214911](https://github.com/mirage335-colossus/software-foundation/actions/runs/36935214911) | Passed: two core checks, 51 GUI/source checks, 409 tool cases; 55 explicit platform exclusions, zero JUnit skips; actual Windows SDL driver | `cd16aeb6bd2dff13115d456ffbea2d166db37427106a5e03961926f840f10feb` |
| [Linux x86_64 36933074074](https://github.com/mirage335-colossus/software-foundation/actions/runs/36933074074) | Passed: two core checks, 58 GUI/source checks, 663 tool cases; two explicit Windows-only exclusions, zero JUnit skips; actual X11 SDL driver | `bdd39974a891e6161d667bbaa0ff2c1894fe9f188ed76d47d1ad6c896972c9f8` |
| [Linux ARM64 36933047430](https://github.com/mirage335-colossus/software-foundation/actions/runs/36933047430) | Passed: two core checks, 58 GUI/source checks, 663 tool cases; two explicit Windows-only exclusions, zero JUnit skips; actual X11 SDL driver | `88c7d871f5cf6210cb4dac6874e666a275dd5f359d42439369a7206b39dbe109` |

The browser run compiled and executed Wasm through retained Node, relocated its
SDK and passed an installed-library consumer. It did not exercise a browser
engine; Firefox and Chromium results above remain separate supporting evidence.
Group `11196926091`, proof `11196850985` and plan `11196681188` identify this
result. Proof and plan ZIP bytes, canonical plan digest, every inner case and
explicit exclusion were independently verified. Both consumer receipts bind the
passed isolation receipt; the original producer path remained absent throughout.

Both Linux replays passed all checks with the actual X11 SDL driver. Their six
framebuffer/FLTK/Rev captures have identical shared declarations at 800×640 and
480×360. Mean channel errors against framebuffer were 0.27826/0.59174 for FLTK
and 0.11736/0.33521 for Rev, with unchanged bounds. Raw capture hashes and
comparison assertions were independently checked. Both core and GUI receipts
bind a passed isolation receipt with all four checkpoints complete.

Windows passed all 51 GUI/source checks, including 26 GUI checks, and both
configuration-aware discovery fixtures. Installed SDL and its interaction scenario
executed with the actual `windows` driver. The six captures and all 24 bound
graphics evidence hashes were independently verified. Exact loaded WGL DLL paths
and locked hashes matched; graphics prerequisite cleanup completed. Mean channel
errors against framebuffer were 0.61927/1.41589 for FLTK and 0.11736/0.33521 for
Rev at the two sizes. Native fonts differ within the unchanged comparison bounds.
Both consumer receipts bind a passed isolation receipt with all four checkpoints
complete.

The following artifact identities supplement the exact replay links above:

| Target | Complete group | Verified proof ZIP | Verified plan ZIP |
| --- | --- | --- | --- |
| Browser Wasm | `11196926091` | `11196850985` | `11196681188` |
| Linux x86_64 | `11196364488` | `11196349636` | `11196329556` |
| Linux ARM64 | `11196973595` | `11196654515` | `11196834046` |
| Windows x86_64 | `11198750342` | `11198735489` | `11198615462` |

For all four completed replays, the full binary/source/checksum triplet agrees
across origin, retention, isolation, core/GUI consumer receipts and publication
plan. Proof and plan ZIP digests and canonical plan hashes were independently
verified. Large group ZIP identities were checked against GitHub metadata without
redundant downloads; each actual replay restored and checked the complete bytes.
Retention is deliberately marked `unqualified` and `publication_approved=false`;
separate passed consumer receipts establish the recorded checks. `execute=false`
plans do not publish a base release or qualify publication credentials.

Concrete failures produced tracked regressions for exact source bytes and native
paths, case-distinct SDK inputs, complete private-runtime inventories,
[known ABI capability floors](portability.md#enforced-baseline-and-runtime-closure),
Windows process completion, optional test-runtime extensions,
[producer-path isolation](sdk.md#exclude-producer-paths-during-sdk-qualification),
and [native capture/display prerequisites](gui-boundary.md). The ABI reader rejects
unknown named capabilities and requirements above the baseline; its controlled
real ELF import fixture works with baseline linkers on both Linux architectures.
Separate local packed-relocation execution demonstrated the original rejection
and corrected acceptance. Neither fixture alone qualifies a complete SDK or an
older target runtime. Native visual comparisons preserve raw captures and
unchanged bounds; separately executed scale checks preserve logical geometry.

Requested, running, cancelled and failed jobs never count as successful
qualification. These observations do not approve GUI redistribution or authorize
release publication.

## Development speed validation

The development-speed changes were checked from an isolated source snapshot on
2026-10-03 with the installed Linux x86-64 compiler and distribution tools. All
50 native CTest entries passed, including 1,138 applicable cases in the registered
unit suites. Two explicitly native Windows cases were excluded on Linux. The
first sandboxed build/check run took 32.77 seconds and passed 45 entries; its five
signing suites could not start GPG's Unix sockets. Those same frozen fixtures
passed in 10.57 seconds when local sockets were permitted. They use disposable
keys and mocked remote services, with no package installation or publication.

A real configure-only candidate followed by a scoped core build/check took
1.88 seconds. Its complete plan identity remained unchanged after compilation.
The tools prerequisite target built no application executables. A separately
archived baseline release/fast build with two compile and two test jobs took
6.29 seconds; these are different selected scopes, not a same-workload speedup
ratio. Documentation validation, Python parsing, workflow lint and whitespace
checks passed.

Accounting against a retained signed x86-64 channel reduces native fetch from
3,728,405,200 bytes across 70 assets to 165,787,187 bytes across four assets
(95.55% less). An unchanged refresh transfers 209,337 bytes of signed controls
and revalidates its stored channel. This is an inventory-derived transfer count,
not a hosted elapsed-time measurement. Full publication/recovery retains the
complete inputs. Complete all-GUI certification still requires 106 logical
checks and 66 physical operations, scheduled as 23 scope-separated batches with
up to eight running concurrently.

The updated workflows have not yet been timed or qualified on hosted Windows,
ARM64 or browser runners. Their local validators and fixture coverage do not
replace those execution environments. The archived-builder compatibility path,
missing remote digests, tampered selected payloads, failed refresh preservation
and rejection of partial native acceptance were exercised locally.

## Transfer and scheduling follow-up validation

A further isolated native run on 2026-10-03 configured, compiled and exercised
51 CTest entries in 40.81 seconds using eight compile jobs and two test jobs.
Integration exposed two outdated workflow contract expectations and one retry
fixture that reached its request deadline before its intended wait-budget limit.
Those fixtures were corrected and only the two affected suites were rerun:
23 workflow-storage cases and 44 signed-client cases passed. Combined with the
unchanged production-code results, all 1,198 applicable registered unit cases
passed; two explicitly native Windows cases remained excluded on Linux. The
native application, install consumer, documentation, workflow lint, Python syntax,
whitespace and generic-name checks passed. Signing fixtures used disposable keys
and local sockets with mocked remotes; no packages were installed or published.

A one-page transport fixture measured 12 metadata reads for eight grouped bundle
fetches, versus 96 when fetched separately. Eight-bundle publication used 18
metadata reads on creation and 16 on an identical retry. These counts exclude
asset downloads/uploads and initialization POSTs; real pagination adds requests.
Exact scope selection, changed identities, collisions, failed parallel transfers,
immutable retries, compression bounds, and joined workers were checked. The
production upload path uses a validated release ID without another tag lookup.
Success diagnostics retained controls and receipts; failed-publication selection
retained complete prepared payloads.

These results do not measure hosted throughput, real Docker bootstrap reuse,
Windows/ARM64 execution, cold SDK construction or complete GUI/browser operation.
The full release still retains required recovery inputs and can exceed one shared
API quota window. Reduced byte and request counts are structural improvements,
not a claim that a particular hosted elapsed time has been achieved.

## Reproduce the integrated checks

```sh
python3 tools/build.py test release --full --distribution-tests --jobs 2 --build-dir build/qualification/native
python3 tools/build.py test asan --label core --jobs 2 --build-dir build/qualification/asan
python3 tools/build.py package release --portable --jobs 2 --build-dir build/qualification/package
python3 tools/check_docs.py
```

Use [the archive and shard recipes](testing.md), [prepared SDK commands](sdk.md),
[GUI qualification commands](gui-boundary.md) and [certification adapters](certification.md)
for their exact prerequisites and identities. Repository signing tests require local
GPG agent sockets; a restricted wrapper which forbids them cannot qualify that
scope. The fixtures use disposable keys and never install or publish packages.

## Material limits

- Prepared SDK checks qualify their exact recipes and observed environments.
  A tested all-GUI recipe does not qualify different core-only or future recipe
  identities. The oldest declared Windows runtime and older Linux user-space/kernel
  combinations still need their own actual environments; mocked checks cannot
  replace them.
- Native source production used actual Debian 12 Bookworm containers on hosted
  kernels. The WebAssembly toolchain uses retained upstream binaries; its native source
  rebuild is not supplied by that recipe. Source availability is documented separately.
- At that baseline, GUI redistribution was blocked by unresolved upstream terms;
  the subsequently reviewed permission scope is recorded in [the GUI audit](gui-audit.md).
  Local compilation and tests do not approve binary redistribution.
- Signed-channel initial installation and actual version upgrades passed on x64
  Debian Bookworm, Debian Trixie, Ubuntu 24.04, Arch and Gentoo, and on ARM64
  Debian Bookworm, Debian Trixie and Ubuntu 24.04, as recorded above.
  Arch/Gentoo native checks are scoped to x64; generating their ARM64 recipes
  does not qualify those frontends. Historical x64 r1 remains unaccepted.
- SDK, gallery and signed-channel publication credentials were exercised
  as recorded above. An adopted repository must qualify its own permissions,
  signing trust and external services.
- Shared-source coordination requires the stated filesystem primitives and
  cooperative writers. Uncooperative participants need enforced private access.
- Real devices, assistive technology, every desktop/window-manager combination,
  long-duration operation and workload performance need separately specified checks.
  Passing this record is not a guarantee for every future feature or environment.

## October 2026 development iteration and direct certification inputs

The next optimization pass was qualified from an isolated copy of the working
source based on `5cda8ec5cd887d73b387243668f317aa7f4093b5`. All **52 CTest
entries passed**, including **1,235 applicable unit cases** and two explicitly
inapplicable native Windows cases on the Linux host. The complete case inventory
and exclusions were identical in the two-worker and four-worker runs.

| Native Release scope with distribution fixtures | Two test workers | Four test workers |
| --- | ---: | ---: |
| CTest elapsed time | 42.16 seconds | 24.67 seconds |
| Configure/build/test wrapper | 43.516 seconds | 25.131 seconds |

CTest used approximately **41.5 percent less elapsed time**, or **1.71 times the
throughput**, in this single comparison. Compilation used eight jobs; the second
run reused the configured build. Comparing CTest separately excludes that build
warmup difference. The resource detector selected four automatic test workers on
this host; smaller CPU/memory budgets still select fewer. These are local native
measurements, not hosted, GUI SDK or cross-platform release timing.

The first four-worker run exposed a new aggregation fixture that mocked away its
working-directory change and left output outside its temporary tree. Only the
fixture was corrected: it now uses its real temporary directory, restores the
caller directory, and checks all three written summaries. Its complete 26-case
suite passed twice from the same working directory, then the complete four-worker
run passed. Production behavior and test inventory were unchanged by that repair.
Signed fixtures required permission to create disposable local GnuPG sockets;
the sandbox denied that prerequisite before signed assertions in the first
focused attempt. The permitted local run passed using fake GitHub transport.

Focused transport, release, distribution, source-identity, build-capacity, change
selection and direct-input tests cover hashes, remote mutation, missing scopes,
failed uploads, late destination collisions and fresh consumer boundaries.
All workflow files passed the retained validator; documentation, Python syntax,
whitespace and generic-name checks passed.
No commit, push, hosted dispatch, real package installation or public release was
performed during this pass.

Certification now retains authenticated controls and fetches selected original
published inputs directly. For the retained roughly 3.5 GB candidate this avoids
approximately 7 GB of intermediate download/reupload traffic. The request model
estimates about 70 fewer metadata/bundle requests plus roughly 20 preparation
payload downloads, rather than assuming every saved byte removes an API request.
Each batch still independently verifies complete public release identity. Quota
stalls remain possible; the next hosted run can account for actual responses,
transferred bytes and waits through sanitized process metrics.

Exact source identities, test reports, fixture correction, request-model references
and measurement limits are retained in
`build/agents/development-speed-v3/final-validation.json`. Full hosted duration
remains unmeasured. Target-specific signed distribution recovery inventories,
per-format signed projections and a new private transport trust protocol were
not introduced; their compatibility and identity contracts require separate work.


## Bounded evidence artifacts and lower transport cost

The 2026-10-03 transport pass replaces the blanket Actions-artifact prohibition
for selected small regression and certification evidence. The complete selection
is limited to 62 immutable slots per run attempt, at most 2 MiB each, with one-day
retention. Oversized bundles and failed artifact uploads preserve complete release
fallback. SDK/application archives continue to use release storage. Downloads
verify context, actual producer identity/completion, whole archives and all member
hashes; corrupt artifacts cannot silently fall back. Mixed inputs remain private
until every selected input passes. Historical cross-run transport keeps its
stricter checks.

The same 23-batch model estimates roughly **1,650 to 610 transport API calls**,
about **63% fewer**, including the large combined certificate's release fallback.
This excludes Actions runtime storage traffic, public SDK/release operations,
initial draft creation, pagination and retries. It is not a hosted measurement or
a guarantee of staying within one quota window. Retained evidence is about 9 MB
compressed in total; representative individual reports are about 257 KB and
seven-backend groups about 1.8 MB. The complete certificate appropriately exceeds
the small-artifact cap and remains in release storage.

Local archive qualification now combines inventory with extraction or small
build-record inspection: a native archive check uses three application archive
decompression passes instead of six and removes two complete temporary package
extractions. All backend checks and final payload verification remain. Source and
recovery testing uses the wrapper's resource-aware worker default independently
of compile parallelism.

The final isolated source snapshot passed **53/53 CTest entries**, including the
optional signed distribution fixtures, in **33.32 seconds** with eight compiler
and four test workers. Its receipts account for **1,269 passed Python cases** and
two explicit native-Windows exclusions on Linux. Workflow lint, Python 3.9 grammar,
documentation and whitespace checks passed. An initial 47/48 native pass exposed
one fixture that asserted the old workflow transport layout; its replacement
asserts bounded control publication and preservation of evidence/prerequisites.
The final run includes that corrected test and all five optional distro suites.

The source manifest, receipts and limitations are retained in
`build/agents/artifact-speed-integration-v1/validation.json`; the detailed request
model is `.agent-work/artifacts/release-api-v4/request-model.json`. No hosted run,
public release, push or SDK rebuild was performed. Actual all-platform wall time
and account quota use remain to be measured on the next ordinary hosted run.


## Native routine transport and shared public discovery

The later 2026-10-03 simplification supersedes the preceding 62-slot storage
policy and 750–1,150 complete-release request estimate. Routine application,
package, source and certification handoffs now use native Actions artifacts.
That historical policy allocated a dedicated 16 MiB certificate slot and at
most 370 MiB across all 79 slots per attempt, plus outer archive overhead.
The [2026-10-05 release record](#rust-enabled-portable-release-and-signed-channels-2026-10-05)
records the later measured capacity repair: a 2 MiB manifest, 24 MiB certificate
slot and 378 MiB aggregate bound. SDK archives
remain in release storage, including during preparation-only application runs.
There is no automatic private-release fallback in routine workflows.

Same-run consumers trust exact executing Actions context, immutable artifact
names and explicit workflow dependencies, then verify complete local bytes.
Certification shares one frozen public inventory. Offline transport fixtures
confirm that the retained 23 public certification batches need no authenticated
REST requests for their 87 payload acquisitions. Published-release boundary
checks, complete first-publication byte readback and strict historical replay
remain. A bounded independent review found no actionable issue in credential-free
public redirects or context-bound frozen controls.

The final applicable local coverage is **54 CTest entries**, including all five
optional distribution suites, with **1,301 passed Python cases** and two explicit
native-Windows exclusions on Linux. The isolated full run took **30.91 seconds**:
52 suites passed and two failed because fixture expectations still described the
old workflow transport or release-list endpoint. Only those fixtures changed;
their signed-byte, isolated-consumer and active-generation assertions remain.
Both affected suites then passed in **6.29 seconds**. Unchanged production source
and the other 52 passing suites were not rerun. Earlier affected checks also
caught an old step-title assertion and a repository-visibility mock omission;
the final complete coverage includes their corrected contracts.

All workflow files passed actionlint. Documentation validation, whitespace checks,
117 Python files parsed with Python 3.9 grammar, and the generic-name scan passed.
The tested snapshot matches implementation source; only final explanatory
documentation changed afterward. Reports and exact source hashes are retained in
`build/agents/transport-simple-integration-v1/validation.json` and its source
manifest. Signed local fixtures used disposable GnuPG sockets and fake remote
transport; no hosted job, public upload, SDK rebuild, commit or push was performed.

The [current request accounting](development-speed.md#account-for-the-actual-critical-path)
models **255 primary-quota operations** for a complete public warm-SDK release,
or **201** when temporary artifacts expire instead of being deleted immediately.
This includes 53 artifacts and 54 cleanup calls. Approximately 29 quota-preflight
HTTP requests and native artifact/public download traffic are additional network
operations. Authenticated graphics URLs can add eight quota operations; private
repositories, retries, extra pages and cold publication cost more. Cleanup spaces
its 53 deletions over at least 52 seconds, after the final consumer, and never
waits for a quota reset. Failed runs keep one-day diagnostics.
These are code-derived costs, not a newly measured hosted duration or quota result.


## Delete larger handoffs at their last consumer

The next 2026-10-03 pass replaces whole-attempt cleanup with direct upload IDs.
Source and application archives are removed after verified candidate publication
and its delivery receipt; the certificate is removed after verified attachment
and its receipt. Each regression package is removed after its fresh-package check.
Small receipts and diagnostics expire after one day. Preparation-only application
outputs and failed-consumer handoffs remain available; `preserve_artifacts=true`
reaches all nested consumers and disables early deletion.

Cleanup performs one DELETE per unique supplied ID, with no inventory listing,
quota probe, retry, or quota-headroom wait. Empty arrays perform no remote work;
missing, malformed and partially invalid arrays fail before any mutation. Distinct
matrix outputs preserve all target IDs; the assembly selector requires the exact
core or all-GUI target set and rejects missing, duplicate or foreign IDs. Cleanup
runs after the final receipt upload so a receipt failure preserves rerun inputs.
Independent job scheduling and all qualification gates remain intact.

All **68 affected offline tests passed in 1.801 seconds**. The isolated complete
native regression, including all five optional distribution suites, then passed
**54/54 CTest entries in 29.69 seconds**. After the final receipt/cleanup ordering
adjustment, the three affected workflow suites passed again in **1.16 seconds**;
unchanged suites were not repeated. Final receipts contain **1,303 passed Python
cases**, with two explicitly inapplicable native-Windows cases on Linux.
Workflow lint, documentation, whitespace, Python 3.9 grammar and generic-name
checks passed. Independent read-only review found no actionable issue in matrix
ID propagation, final-consumer barriers, preservation or permission inheritance.

The complete public warm-SDK all-GUI request model is now **210 quota-counted
operations**, including nine targeted deletions, compared with 255 including the
previous 54-call cleanup. Explicit preservation remains 201. Approximately 29
primary-unmetered quota probes and Actions/public-download network traffic remain.
The five-item publication cleanup uses four seconds of deliberate mutation spacing;
the three package deletions and certificate deletion are single-item operations.
Small retained artifacts expire without cleanup API calls. These are code-derived
costs, not newly measured hosted latency or quota consumption.

The final source manifest, full-run manifest, receipts and logs are recorded in
`build/agents/artifact-consumer-integration-v1/validation.json`. Only final validation
documentation changed after the tested snapshot. No hosted workflow, actual remote
artifact deletion, public upload, SDK rebuild, commit or push was performed.


## Manual repository artifact cleanup

The 2026-10-03 manual maintenance addition deletes a frozen, fully paginated
Actions-artifact inventory while preserving workflow runs, normal logs and release
assets. Before deleting, it checks all five active workflow statuses and refuses
other runs. This observation does not lock out future workflow starts. Deletion
has one-second spacing, no mutation retry or quota wait, a 25-minute loop budget,
and confirmed count/byte reporting. It is not called by routine development jobs.

All **15 focused offline helper tests passed**. The isolated integrated native
suite, including all five optional distribution suites, passed **55/55 CTest
entries in 30.57 seconds**, with **1,319 passed Python cases** and two explicitly
inapplicable native-Windows cases on Linux. Coverage includes complete pagination,
all busy statuses, changing or malformed inventories, duplicate IDs, partial
failure, real transport handling of a 404, exact request counts, bounded progress,
and deadline reporting. Workflow lint, documentation validation, whitespace,
119 Python files parsed with Python 3.9 grammar, and the generic-name scan passed.
Independent read-only review found no actionable issue.

Exact source hashes, local receipts and the log are recorded in
`build/agents/manual-artifact-cleanup-v1/validation.json`. Only this validation
record changed after the tested source snapshot. No hosted workflow, remote
artifact deletion, commit or push was performed. For a nonempty inventory of
`N` artifacts, the normal API cost is `N + ceil(N / 100) + 5`; an empty inventory
requires one GET. This optional maintenance cost does not change routine release
request accounting.


## Share SDK metadata within assembly

The next 2026-10-03 change batches assembly's four SDK recipes behind one complete
in-memory base-release inventory and one fresh final reconciliation. Downloads
and group verification retain four-worker parallelism. Every file still passes
its size/hash and SDK checks. All groups stay in temporary staging until the
whole batch succeeds. There is no additional workflow job, artifact upload,
cross-job metadata handoff or persistent cache.

Release clients reuse valid core-quota response headers for up to 30 seconds,
with conservative local write admissions. Fallback probes are serialized within
the client and bounded by the existing request deadline, including lock wait.
A fresh adequate probe can admit a write despite a lower local estimate, avoiding
an unnecessary reset wait. Unknown or stale observations retain fallback checks;
failed mutations are never replayed.

The isolated full native regression, including all five optional distribution
suites, passed **55/55 CTest entries in 30.56 seconds**, with **1,338
passed Python cases** and two explicit native-Windows exclusions on Linux.
The 19 new cases cover exact batch request counts, four simultaneous transfers,
changed metadata, corrupt bytes, staging cleanup after joined workers, workflow
ordering, header reuse, concurrent fallback, stale observations, bounded waits,
and uncertain mutations. Workflow lint, documentation, whitespace, Python 3.9
grammar for 119 files and the generic-name scan passed. Independent read-only
review found no actionable issue.

The public warm-SDK complete-release model falls from 210 to **189 quota-counted
requests**, or **180** with preservation. Assembly metadata reads fall from 28
to seven for four recipes and one-page inventories. The former 29 quota-probe
requests become conditional fallback traffic; there is no guaranteed fixed count.
These are code-derived savings, not hosted measurements. Evidence and exact source
hashes are retained in `build/agents/sdk-metadata-batch-v1/validation.json`.
Only this validation documentation changed after the tested snapshot. No hosted
workflow, real remote operation, SDK rebuild, commit or push was performed.


## Portable qualification commands

The 2026-10-03 incremental extraction provides file-based plan, list, prerequisite
and execution commands through `tools/qualification_tasks.py`. The core planner
requires no provider files or GitHub context. Hosted scheduling, authenticated
transport and publication stay in their adapter. Browser receipts now bind to
explicit plan/check/run/attempt values supplied only to supervised children.
The all-GUI coverage remains **106 logical checks, 66 physical executions and
23 hosted batches**, with grouped work, selective payloads and full diagnostics.

The isolated final native regression, including all five optional distribution
suites, passed **56/56 CTest entries in 31.55 seconds**, with **1,357 passed Python
cases** and the same two explicit native-Windows exclusions on Linux. The 19 new
cases cover provider-free planning and real child execution, altered input and
identity rejection, grouped report inventory, explicit browser setup and hosted
boundary delegation. An initial full run exposed a missing receipt-parent creation
and an outdated writer mock; the old behavior was restored, the fixture updated,
and all 22 affected cases plus the complete final suite passed without removing
assertions. Workflow lint, documentation, whitespace, Python 3.9 grammar for 122
files and the generic-name scan passed. Independent integration review found no
actionable issue before that final tested compatibility repair.

Exact source hashes, reports and retained failure/final logs are recorded in
`build/agents/portable-qualification-v1/validation.json`. Only this validation
record changed after the final tested snapshot. No hosted workflow, real remote
API operation, SDK rebuild, commit or push was performed. This extraction adds
no artifact handoff or API request: the existing public complete-release model
remains **189**, or **180** with preservation. These local tests establish the
command boundary and preserved contracts, not a new hosted elapsed-time result
or qualification of another provider's runners and transport.


## Restore SDK overlap and certification concurrency

The next 2026-10-03 change starts verification of each fully downloaded SDK while
other SDK downloads continue. Separate pools retain at most four transfer workers
and four verification workers. Both pools finish before failed staging cleanup;
all verification and the final shared remote reconciliation must pass before the
output directory becomes available. The four-recipe metadata cost remains seven
reads, with no additional transfer, artifact or persistent cache.

Certification now makes every planned batch eligible by default: all 23 batches
for the current all-GUI policy. The repository Actions variable
`FOUNDATION_CERTIFICATION_JOBS` optionally caps jobs for constrained runner pools;
unset or `0` uses the actual matrix count. Invalid values fail before remote input
acquisition. Runner/account availability still controls actual concurrency. Batch
identity, artifact slots, coverage and publication gates remain unchanged.

The final isolated native regression, including all five optional distribution
suites, passed **56/56 CTest entries in 30.96 seconds**, with **1,364 passed Python
cases** and two explicit native-Windows exclusions on Linux. Seven new cases cover
real thread ordering for overlapping download/verification, independent worker
bounds, joining writers after failure in either stage, full-matrix/default and
lower-cap scheduling, invalid settings and empty matrix rejection. Existing exact
API-count, tamper and output-publication checks also passed. Focused runs passed
105/105 SDK delivery cases and 38/38 workflow storage cases. Independent read-only
review, workflow lint, documentation, whitespace, Python 3.9 grammar for 122 files
and the generic-name scan passed.

Exact source hashes and reports are recorded in
`build/agents/concurrency-restore-v1/validation.json`. Only this validation record
changed after the tested snapshot. No hosted workflow, real remote API operation,
SDK rebuild, commit or push was performed. The public complete-release estimate
remains **189 requests**, or **180** with preservation. Greater job concurrency
changes request timing, not its normal total; hosted elapsed-time improvement and
burst behavior require observation during an ordinary run.


## Restore audited development and portability gaps

The 2026-10-03 implementation adds complete explicit test prerequisites. Planning
requires no compilation in registered builds, ordinary shards compile only their
selected targets, and script-only selections invoke no build. Candidate core
ownership still includes enabled GUI tests. Missing declarations and changed
inventories fail instead of silently reducing coverage. Deferred directory-local
label collection preserves the CMake 3.24 baseline; the optional Rev module probe
separately requires CMake 3.28+ and a suitable installed module compiler.

Explicit prior-attempt adoption preserves original successful receipts, attempt
numbers, hosts and evidence bytes. Qualification, certification, certificate
bundling and independent remote reconstruction validate that selection. Ordinary
mixed-attempt aggregation still fails. Existing hosted workflows do not yet
acquire and authenticate earlier-attempt artifacts automatically; this addition
provides the explicit local/alternative-scheduler command and consumer boundary.

The isolated native regression, including all five optional distribution suites,
passed **58/58 CTest entries in 30.26 seconds**, with **1,396 passed Python cases**
and two explicit native-Windows exclusions on Linux. Terminal, framebuffer and
hosted-web GUI checks passed **25/25 entries in 5.08 seconds** using the unchanged
retained GUI group. Address/undefined-behavior sanitizer core checks passed **2/2**
with leak detection enabled. The small actual Rev probe compiled four pinned
production modules and passed both comparison/layout cases with Clang 19 in
**6.21 seconds**; its 16 helper cases also passed in the native suite.

Final review preserved the existing application-wide static-archive symbol hiding;
installed consumers receive narrower GNU-runtime hiding so their own archive APIs
remain available. After that localized correction, a fresh isolated portable
Release archive build passed, core checks passed **2/2**, and the installed consumer
plus runtime/plugin integration passed **2/2 in 5.04 seconds**. The runtime fixture
includes bundled-shared and exported-static negative controls, relocated execution,
installed library consumption and stale-header-probe rejection. Other implementation
bytes are unchanged from the preceding native/GUI/sanitizer runs and were not
needlessly retested. Exact snapshot differences are retained with the results.

The first full run exposed an extracted GUI CMake fixture missing the new helper;
loading the actual helper repaired it without changing its assertions. A separate
review caught and removed a CMake 3.28-only property API. GnuPG socket setup and
LeakSanitizer failed under the execution sandbox; discriminating native runs
confirmed those restrictions, and the affected checks passed with local sockets
and normal process inspection available. No signing or sanitizer checks were
weakened. Workflow lint, documentation, whitespace and Python 3.9 grammar for
126 source files passed.

Evidence, commands and exact source hashes are recorded in
`build/agents/audit-integration-v1/validation.json`, with frozen source manifests
and retained failure/final logs below that directory. Only this final validation
record changed after the final source snapshot. Native Windows wide-argument
conversion is registered but was not executed locally; ARM64, Wasm, FLTK/SDL/Rev
native surfaces and actual hosted workflows were not rerun. CMake 3.24/3.25 was
reviewed for API compatibility, not executed on this host. No SDK rebuild, dependency
acquisition, remote publication, commit or push was performed. These checks do not
establish a new hosted elapsed-time measurement or broaden the existing platform
support claims. Internal case/seed partitioning remains conditional on measured
need; current complete CTest-level parallelism is retained.
