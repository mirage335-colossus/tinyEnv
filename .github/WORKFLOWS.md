# Workflow examples

These executable workflows are hosted with this repository. Actual observed
qualification is recorded in [validation](../docs/validation.md).
`ci.yml` gives inexpensive automatic feedback for pull requests and main-branch
pushes. `candidate.yml` is manual, defaults to full selected-platform tests,
checks actual target architecture, and creates verified native archives. Routine
handoffs and diagnostics use bounded Actions artifacts; explicitly retained SDK
inputs use private draft release bundles with complete manifests. Neither workflow publishes an application
release or establishes an older-runtime baseline.

Application entry points default `core_provider` to `rust`; `cpp` is an explicit
legacy choice. Development feedback prepares distribution Rust tools and checks
both the default and Rust-free compatibility path. Candidate native jobs prepare
pinned official Rust inputs separately. Prepared-SDK application, GUI, screenshot
and Latest workflows require complete already-retained Rust groups matched to
their C++ targets; missing groups fail before application work. SDK maintenance
provides the explicit Rust group preparation/qualification/publication route.
Normal application configure, build, test and package steps never acquire tools
or crates. See [the default policy](../docs/rust-hybrid-plan.md#why-rust-is-the-default).

Manual candidate inputs:

| Input | Default | Effect |
| --- | --- | --- |
| `devfast` | `false` | `true` runs focused core diagnostics and omits packaging/sanitizers |
| `linux_pool` | `standard` | `faster` selects one administrator-configured larger Linux runner |
| `build_jobs` | `auto` | Use available CPU/RAM capacity, or explicitly select 2, 4 or 8 compiler jobs; test limits remain separate |
| `include_arm` | `true` | Include the Linux ARM64 runner alongside Linux/Windows x64 |

To enable `faster`, configure repository variable `FOUNDATION_FAST_LINUX_RUNNER`
with the authorized larger GitHub-hosted x64 Linux runner label. The example
requires its name to begin `foundation-linux-`. This variable is the allowlisted
choice, not an arbitrary workflow input. Confirm image prerequisites, access,
quotas and cost before configuring the pool. Missing configuration fails early.
The default uses standard runners and requires no such variable.

A development diagnostic can be dispatched with:

```sh
gh workflow run candidate.yml --ref YOUR_BRANCH \
  -f devfast=true -f linux_pool=faster -f build_jobs=8 -f include_arm=false
```

Replace `YOUR_BRANCH` with the intended ref. Record and check the resulting
run's actual commit; wait for completion and inspect logs. Once the fix is ready,
run the default full candidate scope or reuse equivalent current evidence.
`devfast` is never release qualification. Agents can choose permitted faster
runners when justified by elapsed time, without inventing new runner access.

Action revisions are full commit pins checked against the upstream repositories:
[checkout v7.0.1](https://github.com/actions/checkout/tree/3d3c42e5aac5ba805825da76410c181273ba90b1).
Dependabot proposes monthly updates; review requirements and run checks before
merging. Runner software still changes independently and must be recorded per run.

The Windows setup helper imports the selected MSVC developer environment into
later steps. It does not redistribute compiler tooling. Build and package
prerequisites must already be present on custom runner images.

See [CI requirements](../docs/ci.md) for source isolation, complete aggregation,
permissions, caches, SDK reuse and production publishing requirements.

The manual lifecycle is executable, not only described:

- `sdk-maintenance.yml`: explicitly build/upgrade or reuse SDK groups; publish to
  base only after required consumers succeed and execution is selected.
- `sdk-import.yml`: preserve exact legacy SDK/evidence bytes in the current draft
  transport and emit a version-2 replay request; no rebuilding or deletion.
- [`legacy-artifacts.yml`](workflows/legacy-artifacts.yml): preserve explicitly
  pinned old opaque ZIPs before separately reviewed cleanup; no extraction or deletion.
- [`verify-retention.yml`](workflows/verify-retention.yml): independently read back every
  selected retained opaque archive and preserve complete verification receipts.
- `sdk-application.yml`: consume exact base recipes, package each required target,
  retain identical SDK copies and optionally publish an ordinary candidate.
  `package_repository=false` is its standalone default; the Latest caller enables
  it to build and sign native repositories before freezing the candidate inventory.
- `certify.yml` and `promote.yml`: qualify exact remote bytes, attach complete
  evidence, then revalidate the selected certificate before changing Latest.
  Integrated packages require eight native frontend installation/upgrade results
  before the certificate is eligible: five x86_64 frontends and three ARM64
  APT frontends.
- [`_release-latest.yml`](workflows/_release-latest.yml): the visible
  **_Publish new Latest release** entry point composes the full sequence, always
  including signed packages. Set the decimal `package_release` string in
  `1`..`999999` and increase it
  for changed packages at the same application version. Integrated execution and
  certification require `previous_packages`, a bounded JSON string with exact
  predecessor selectors for both Linux targets. APT/pacman discover the resulting
  assets through `releases/latest/download`; Gentoo tracks Latest then pins its
  exact tag. This layout applies to the next rebuild; it has not been qualified
  or deployed by the current source change.
- [`screenshots.yml`](workflows/screenshots.yml): capture fresh initial views of
  all seven actual GUI hosts and optionally publish a non-Latest image gallery.
- [`distribution.yml`](workflows/distribution.yml): turn a certified immutable
  application into legacy separately signed APT, Arch and Gentoo channels with
  exact retained inputs. Its manual publication and verification tools remain
  available. Historical stable-mirror publication is superseded for future
  rebuilds; there is no current mirror helper or workflow route.
- `gui-inputs.yml` and `native-gui.yml`: explicit supplier-input maintenance and
  native host qualification with separate Windows graphics prerequisites.
- [`rust-qualification.yml`](workflows/rust-qualification.yml): four explicitly
  selected Rust lanes for Linux x64/ARM64, Windows x64 and browser Wasm. Its
  preparation step acquires pinned official Rust tools, sources and stage0 inputs;
  application/replay/recovery steps consume retained groups. Run-scoped draft
  bundles retain available packages, per-case results and diagnostics, plus exact
  SDK/source inputs once the recovery kit exists. Earlier failures may retain
  preparation inventories without a complete input kit.
  Every planned lane must complete successfully; no stable application release,
  base/Latest change or distro-channel promotion occurs. Compiler reconstruction
  from source is not claimed. See [the qualification contract](../docs/ci.md#rust-qualification).

`execute=false` may write private CI transport drafts. It does not publish a
public application/base/gallery or advance Latest. See the exact
[storage contract](../docs/ci.md#storage-caches-and-sdk-reuse),
[Latest inputs](../docs/latest-release.md) and [capture inputs](../docs/screenshots.md).
