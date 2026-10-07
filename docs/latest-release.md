# Publish a new Latest release

[`_Publish new Latest release`](../.github/workflows/_release-latest.yml) is the
single application-release entry point. Select the source branch in Actions,
the complete support profile, exact existing SDK recipe map and a new tag.
An empty tag becomes `release-RUN-attempt-ATTEMPT`. A later repair or rerun gets
a fresh identity; the workflow never adopts or overwrites an existing tag.

The core profile covers Linux x64, Linux ARM64 and Windows x64. The all-GUI
profile adds the declared backends and browser target. Its existing supplier
redistribution requirements must be resolved before application publication;
passing local GUI checks does not bypass them. All-GUI also requires an exact
retained GUI group and the explicit verified Windows host graphics input.

Latest preparation always enables `package_repository`: signed native packages
are application-release assets and are certified with the application. The
standalone `sdk-application.yml` route defaults this option to `false`.
`package_release` is a decimal string from `1` through `999999`. Increase it
explicitly when publishing new package bytes for the same application version; never reuse a
same-version package revision. Existing protected signing inputs are required
before package preparation; see [the package contract](distribution-release.md#application-release-packages).

`previous_packages` is a bounded JSON string mapping both `linux-x86_64` and
`linux-aarch64` to exact predecessor selectors. Planning may omit it; integrated
execution and certification require both entries so every native frontend proves
an actual upgrade. Migration can use the existing immutable signed channels:

```json
{
  "linux-x86_64": {"tag":"distro-VERSION-x86_64-rREVISION-sSEQUENCE","manifest_sha256":"EXACT_DISTRIBUTION_JSON_SHA256","target":"linux-x86_64"},
  "linux-aarch64": {"tag":"distro-VERSION-aarch64-rREVISION-sSEQUENCE","manifest_sha256":"EXACT_DISTRIBUTION_JSON_SHA256","target":"linux-aarch64"}
}
```

For a predecessor with integrated packages, add `"format":"release-packages"`
to its selector, use its exact application release tag and bind
`manifest_sha256` to that release's signed `packages.json`. Each target retains
its own selector even when both come from the same release. The new package
version must be strictly newer on both targets. An omitted predecessor cannot
produce upgrade qualification.

Supply a JSON object mapping every profile target to its full SDK recipe digest.
The preflight verifies complete base asset presence before expensive work.
Producers then download and validate those groups, restore them into fresh
locations and compile against them. Missing or partial groups fail. The workflow
does not silently compile a new SDK; use explicit SDK maintenance first.

`core_provider` defaults to `rust`. The preflight derives the exact per-target
Rust recipes from the checked-in recipes and producing helper bytes, and requires
their complete retained binary/source/checksum triplets alongside the selected
C++ groups. Missing, partial or stale Rust inputs fail before SDK consumption
or publication. It returns the Rust recipe map to the existing producers and
retains those groups with application recovery inputs. Explicit
`core_provider=cpp` selects the complete legacy release route without Rust
inputs; historical delivered inventories keep their original provider identity.

## Executable ordering

1. Freeze the exact source revision, selected inventory, new tag and existing
   dependency identities. Reject malformed or incomplete inputs before builds.
2. Run the complete native candidate regression, including Windows and ARM64,
   independent packages, fresh installed consumers and distribution checks.
3. Build the application from its frozen source archive with the exact prepared
   SDKs. Require the supported producers and backend inventory. Assemble one
   complete release with application archives, source and exact SDK binary,
   source and checksum copies. Build and sign the package repositories from those
   same prepared application bytes before freezing the candidate's release
   inventory and checksum list. This includes the combined Linux APT repository,
   x86_64 Arch repository, per-target native bundles and signed package manifest.
4. When execution is requested, publish that ordinary candidate as a prerelease
   until certification and promotion. This also prevents the first normal release
   from becoming Latest through platform fallback. The publisher verifies draft
   uploads, remote assets and the Latest pointer. Application and packaging
   revisions must match.
5. Download the exact published candidate and run every required policy check
   against its bytes and retained sources. Bind immutable reports to source,
   inventory, environment, backend, scope, run and attempt; append the complete
   certificate evidence without replacing older assets. Integrated packages also
   require all eight native frontends and their exact predecessor upgrades: APT
   on Debian Bookworm, Debian Trixie and Ubuntu 24.04 for both Linux architectures,
   plus Arch and Gentoo on x86_64. Failed, skipped or absent native results make
   the certificate ineligible for promotion.
6. Reproduce the qualifying ordinary certificate, reread remote asset identities,
   clear prerelease status and select Latest in one release update, then verify
   the Latest pointer.
7. An independent final job requires every mandatory stage to have succeeded.
   It downloads and verifies the complete release again, reproduces its retained
   certificate, and checks that Latest names this exact release, source and
   inventory. Skipped, cancelled, incomplete or stale stages cannot produce a
   successful execution verdict.

The workflow calls the existing versioned workflows directly. It does not
duplicate their implementation or dispatch unrelated runs and infer completion.
Local reusable workflow references execute at the caller's commit, and their
outputs carry the exact delivery and certification identities. This follows
GitHub's [reusable workflow contract](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

## Preparation, permissions and recovery

`execute=false` is the default. It runs preflight, full candidate checks and
application preparation. Certification and promotion are deliberately omitted
because no public candidate was requested. The final result says **prepared**,
with `qualified=false` and `published=false`; it is not a Latest release success.
Reusable SDKs and public application/certificate assets use release storage.
Source, application and certification handoffs use bounded one-day Actions
artifacts; the complete certificate fits its own larger slot. Preparation-only runs retain frozen candidate controls, while their source and
application components already have separate handoffs. They do not upload duplicate
SDK recovery archives. Native handoff failures do not silently activate a private relay.

Large handoffs are removed after their final successful consumer: source and
application archives after verified candidate publication, certificate after
verified public attachment, and each regression package after its fresh-package
check. Exact upload IDs flow through the nested workflows; no final sweep is needed.
Small receipts and diagnostics expire after one day. Preparation-only source and
application outputs and failed-consumer handoffs also remain for one day.
Set `preserve_artifacts=true` to disable early deletion throughout the nested calls.
Cleanup failures are visible but cannot turn a completed release into an hour-long
quota wait; one-day expiration remains available. Workflow history and public
release assets are preserved. See the [storage contract](ci.md#storage-caches-and-sdk-reuse).

`execute=true` requests the entire sequence. Public mutation jobs use the
protected `release-publisher` environment and a shared publisher lock with
cancellation disabled. Configure required reviewers, permitted branches and
token permissions before operating it. Draft storage also needs `contents: write`
on the trusted manual run. Never expose these jobs to untrusted pull-request
source. The orchestrator uses a different concurrency key from its child
publishers, so waiting for a child cannot deadlock the parent-held lock.

The application call explicitly maps only `DISTRIBUTION_SIGNING_KEY`, and the
reusable application workflow declares that optional secret. Its protected
assembly environment still supplies the configured environment key and the
bounded key check remains mandatory for signed packages. A hosted availability
probe found that the environment binding and declaration alone left this key
empty in a reusable call; the named mapping restored availability. Preserve this
handoff without inheriting unrelated secrets or moving the key out of its
protected environment.

The entry point intentionally offers no experiment switch or shortened test
mode. Experiments use the separate candidate workflow and remain ineligible for
Latest. A failed or uncertain remote mutation must be inspected under the same
publisher lock before any retry; a client failure does not prove no remote
change occurred. Preserve the original inputs, asset identities and failure
evidence. Follow [GitHub delivery recovery](github-delivery.md).

Integrated package certification requires fresh preparation and all eight native
jobs in the same attempt. A failed-jobs-only rerun retaining an earlier prepare
job fails closed; rerun the complete certification workflow with fresh
preparation. Existing application-only evidence adoption remains unchanged.

## Application assets and package repositories

The application inventory includes the signed package repositories alongside the
exact source, application and dependency copies required for recovery. The
ordinary delivery verifier, complete certificate and protected promotion cover
these assets together. APT and pacman use the stable
`https://github.com/OWNER/REPOSITORY/releases/latest/download/` root. Gentoo uses
`selection: {"track":"latest"}` to discover the application release, then pins
its exact tag and verifies the signed per-target native bundle before activation.
See [package layout and native qualification](distribution-release.md#application-release-packages).

The next rebuild uses this layout. Existing releases, immutable signed channels
and historical package mirrors keep their published bytes; no live consolidation
is part of this source change. The new route does not retain older packages in
the next Latest release to serve clients holding an older index. APT and pacman
clients must refresh their signed indexes when Latest changes; each historical
release retains its own immutable recovery inventory. Legacy separate-channel
publication and verification remain available through the explicit
[distribution workflow](distribution-release.md#legacy-immutable-package-releases).

The [orchestration helper](../tools/latest_release.py) and
[offline tests](../tests/test_latest_release.py) verify stage completeness,
source/inventory/attempt binding, explicit preparation-only results and final
remote certificate/pointer checks. Hosted permissions, environment approvals and
the complete executable workflow still require actual qualification on the
source revision to be delivered.
