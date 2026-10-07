# Signed package repositories

## Application-release packages

Latest rebuilds prepare their signed package repositories as ordinary
application-release assets. [`release_packages.py`](../tools/release_packages.py)
builds and signs them from the prepared application archives before the candidate
inventory and checksum list are frozen. `release.json` therefore binds the package
bytes through the normal delivery and certification path. There is no later
package attachment or separate mirror publication in this route.

The release download root contains `packages.json`, its detached signature,
`archive-keyring.gpg`, `INSTALL.md`, and the signed repository assets. The combined
APT index covers both Linux architectures: two packages for the core profile or
14 backend/architecture variants for all-GUI. The flat Arch database and packages
cover x86_64 only: one core package or seven all-GUI variants. The signed
`native-linux-x86_64.tar.gz` and `native-linux-aarch64.tar.gz` bundles retain the
respective native channel and Gentoo inputs for exact-tag verification and
activation. Creating ARM64 recipes does not establish Arch or Gentoo support on
ARM64. Each application release also retains its original source, application and
SDK recovery inputs.
Integrated native recipes opt into specification 7 (legacy default 6) for exact
GitHub tag URLs and checksums without duplicate SDK alias copies.

Use the same independently reviewed signing fingerprint and protected
`DISTRIBUTION_SIGNING_KEY` secret described below. The Latest caller always sets
the prepared-SDK producer's `package_repository` option to `true`; standalone
`sdk-application.yml` calls default it to `false`. `package_release` is a decimal
string bounded to `1`..`999999` and must increase explicitly for changed packages
at the same application version. Packaging and signing finish before checksums are published; certificate
and promotion checks then bind the complete frozen application inventory.

APT and pacman use this stable public download root:

```text
https://github.com/OWNER/REPOSITORY/releases/latest/download/
```

Configure APT with the independently trusted key, flat suite `./` and the desired
`amd64` or `arm64` architecture. Configure x86_64 pacman with
`SigLevel = Required DatabaseRequired` and the same root as its `Server`.
Ordinary `apt-get update` or `pacman -Syu` discovers the newly promoted release.
Its `INSTALL.md` supplies the complete setup. Gentoo uses the operator-trusted
`distro_client.py` tree with `selection: {"track":"latest"}`; discovery pins the
exact application tag before verifying its signed per-target native bundle and
activating the existing Portage sync adapter. Independent key trust, signatures,
policy and metadata expiry remain required.

Every new Latest release contains its own complete package inventory. It does not
copy prior versions into the new release for clients holding an older index, and
there is no mutable mirror ledger or index-replacement protocol. Refresh the
signed native repository after Latest advances; historical exact release tags
retain their own immutable bytes. The reviewed
[Data Pump example](https://github.com/mirage335-colossus/pumpModem/blob/2bbd92c63e22490e7708c6bc3d878eb4d1fe09e7/tools/apt-release.py#L306)
provides the package-before-checksum ordering pattern; Foundation additionally
requires its normal complete delivery inventory and native qualification.

### Application-package qualification

Integrated certification requires all eight native frontends: Debian Bookworm,
Debian Trixie and Ubuntu 24.04 APT clients on both Linux architectures, plus Arch
and Gentoo on x86_64. Every declared backend must install, verify its actual native
package version and private payload, exercise the application, refresh the
repository, upgrade from its exact predecessor and uninstall. Missing, skipped
or failed native receipts leave the certificate ineligible for promotion.

The Latest `previous_packages` input is a bounded JSON string mapping both
`linux-x86_64` and `linux-aarch64` to exact predecessor selectors. It may be omitted
for planning, but integrated execution and certification require both targets.
Legacy selectors keep their existing `tag`, `manifest_sha256` and `target` fields
so the first rebuild can prove upgrades from the accepted immutable channels.
Integrated selectors add `"format":"release-packages"`, identify an exact
application tag, and bind `manifest_sha256` to its signed `packages.json`. A
strictly newer version or package revision is required on each target; an absent
entry cannot count as upgrade evidence. See [Latest inputs](latest-release.md).

This layout passed the complete cloud-built Rust/all-GUI release at source
`91dd1392ce182dd6aeef6bf9e18c17cfb9786377`: all eight native predecessor upgrades,
eligible certification, protected promotion and exact public Latest readback
passed in [run 37394012851, attempt 1](validation.md#rust-all-gui-release-and-integrated-packages-2026-10-06).
Earlier source-only/deferred results, public application releases, signed channels
and package mirrors preserve their historical identities and bytes.

## Legacy immutable package releases

The following manual workflow and client procedures preserve the existing
separate-channel format. They remain available for explicit legacy operations;
they do not describe the integrated Latest package inventory above.

[`distribution.yml`](../.github/workflows/distribution.yml) wraps an existing,
certified application release as a separate package-manager release. It never
rebuilds application code, substitutes dependencies, appends package assets to the
application release, or changes Latest. Its default dispatch validates a plan only.
An explicit execute dispatch uses the protected `release-publisher` environment.
Concurrency is scoped by target across refs: distinct target channels may publish
and qualify in parallel, while revisions for the same target share one group.
Native acceptance retains the separate shared release-lifecycle lock. Dispatch
each new revision only after its predecessor is accepted; `cancel-in-progress:
false` protects running work but does not preserve every pending dispatch in
GitHub's [default concurrency queue](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency).
A workflow adopted while an older concurrency
group is still running does not acquire that older group's lock. Wait for the
affected predecessor before dispatching its next revision. Invalid request JSON
or an unsupported target must fail before signing or publication.

The source application must be an ordinary public release with the exact requested
inventory and a complete certificate attempt that reproduces against the current
release policy. Preparation fetches and verifies the complete original delivery
once, retaining
its recovery closure. Later checks reconcile every remote asset ID, size and digest
against the frozen delivery. The exact certificate pair is downloaded once during
preparation and retained; publication reproduces that evidence locally and checks
its hashes against the current remote assets. Independent channel uploads, complete
recovery fetches and first-publication readback use at most four transfers
concurrently; payload writes join before signed control records or publication,
and all transfers join before cleanup. A
passing workflow name, stored status or adjacent checksum alone cannot authorize
this operation. GUI material still requires resolved recorded redistribution terms.

Each target gets a distinct immutable tag:
`distro-VERSION-ARCH-rPACKAGE_RELEASE-sSEQUENCE`. APT files and Arch databases,
packages and signatures live directly at that release's download root. The full
signed native channel, Arch recipes and Gentoo overlay also live in
`channels.tar.gz`. The release starts as a prerelease and is never selected as Latest. Native client
acceptance can subsequently mark it qualified without changing any asset.

All original delivery files are copied to assets named
`sha256-DIGEST-ORIGINAL_FILENAME`. This retains the original source archive, every
application archive and manifest, every exact SDK/dependency triplet and the original
release inventory. The selected certificate pair, frozen delivery descriptor,
current policy and complete packaging source archive are retained the same way.
Generated recipes point to those exact immutable HTTPS aliases; the archive used
for installation cannot drift when a supplier repository changes or disappears.

The packaging source is bound to its actual clean Git checkout, not a commit label.
The signed manifest retains the bounded raw commit object; verification reconstructs
Git blob and tree identities from every archived source byte and executable mode,
then verifies the tree and commit ID. Both supported Git object formats are covered.
This [Git object proof](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
remains checkable offline after the packaging checkout is unavailable.
Line-ending or executable-mode conversions that differ from the committed tree fail
closed; use the clean Linux packaging checkout supplied by the workflow.

The signed `distribution.json` binds every output byte, original application release
ID, certificate, target, complete backend selection and recipe reference. Verification
restores the application inventory, reproduces its certificate from retained
evidence, verifies both package channels and checks the flat downloads against their
signed originals. APT backend receipts must match the exact certified archive and
version. Each selected backend gets its own package with shared files preserved.

## Request and protected inputs

Use this complete JSON as the workflow's `request` input, replacing every identity
with the actual reviewed value. Obtain the packaging commit from the checked-out
revision; ordinary execution requires a clean checkout at that exact commit.

```json
{
  "schema_version": 1,
  "repository": "OWNER/REPOSITORY",
  "application_tag": "v1.2.3",
  "inventory_sha256": "EXACT_RELEASE_JSON_SHA256",
  "profile": "core",
  "certificate_run": "EXACT_CERTIFICATE_RUN",
  "certificate_attempt": 1,
  "certificate_sha256": "EXACT_CERTIFICATE_SHA256",
  "target": "linux-x86_64",
  "version": "1.2.3",
  "package_release": 1,
  "sequence": 1,
  "valid_days": 30,
  "trusted_fingerprint": "FULL_INDEPENDENTLY_TRUSTED_PRIMARY_FINGERPRINT",
  "license_files": ["share/doc/Foundation/LICENSE"],
  "runtime_dependencies": {
    "arch": ["glibc>=2.36"],
    "gentoo": [">=sys-libs/glibc-2.36"]
  },
  "packager_commit": "EXACT_PACKAGING_COMMIT"
}
```

The values above illustrate the schema and are deliberately not executable
identities. Use a profile actually declared in `docs/release-policy.json`. Supported
targets are `linux-x86_64` and `linux-aarch64`. The complete backend list comes from
the certified archive, not from an operator-provided subset. Review the retained
license list and host runtime prerequisites for that exact archive; GUI hosts also
need compatible display services, fonts and drivers. The helper preserves the
existing channel tools' ABI checks and redistribution gates. Current recipes derive
the minimum complete license list from the actual archive: the project license,
the bundled GUI lock and every notice it declares, and the dependency notice index
and every file it indexes. Listed bytes, sizes and data-file modes are verified;
omitted terms or unindexed dependency notices fail before signing. This applies
to core projections too, because their shared resources remain installed. Use
`distro_channel.required_license_files(payload)` on the verified archive payload
to construct the request; review additional project-specific terms when adopting
this example. The workflow accepts at most 32 KiB of UTF-8 request JSON and rejects
larger inputs before parsing. Serialize compactly, retain the complete notice list,
and measure the full dispatch input payload against GitHub's 65,535-character
limit, including any previous-channel selector.

Store the armored private signing key as the protected environment secret
`DISTRIBUTION_SIGNING_KEY`, and its independently reviewed full primary fingerprint
as `DISTRIBUTION_SIGNING_FINGERPRINT` in both the repository variables and the
`release-publisher` environment variables. Planning/native qualification and
protected publication must use the same independently trusted value. The workflow requires the request to match
that fingerprint. Key bytes are removed from the process environment before child
commands run, written only to a private temporary file outside the checkout, and
deleted after local signing. Outputs and transport bundles contain only public
verification material. Use a dedicated signing key; rotate trust through a reviewed
transition, never by trusting whatever key accompanies a download.

The Debian version is `VERSION+rPACKAGE_RELEASE`; Arch uses
`VERSION-PACKAGE_RELEASE`, and Gentoo uses the existing reviewed revision mapping.
Increase the application version or package release when package bytes change.
Increase sequence for a fresh signed metadata publication. A new immutable tag is
required for new signatures or expiry dates; identical prepared bytes may be retried.

## Local and remote operations

```sh
python3 tools/distribution_release.py plan --request request.json
python3 tools/distribution_release.py prepare --request request.json \
  --output build/distribution --signing-key /secure/private.asc
python3 tools/distribution_release.py verify --directory build/distribution \
  --trusted-fingerprint FULL_PRIMARY_FINGERPRINT
python3 tools/distribution_release.py publish --directory build/distribution \
  --trusted-fingerprint FULL_PRIMARY_FINGERPRINT
```

`prepare` performs read-only remote retrieval and local signing. `publish` prints
its plan unless `--execute` is explicitly supplied. Publication checks the current
remote application inventory and exact certificate again, creates a draft, uploads
without overwrite, downloads every channel asset and reruns signature and complete
closure verification before first publication. Identical already-public retries
reconcile the complete signed inventory and remote asset identities without
repeating payload downloads. A still-private draft always receives full readback.
Lost responses or incomplete uploads preserve their
draft state. Only confirmed fresh atomic tag creation permits one draft creation;
other writers and uncertain responses use bounded reads. An orphan tag without a
visible draft requires explicit reconciliation, never another creation request.

Successful workflow diagnostics retain the signed descriptor, signature, keyring,
request and publication receipt. The complete closure already lives in its exact
public channel and is not uploaded again to private run transport. Failed
publication diagnostics retain the complete prepared closure for recovery.
Retry the identical prepared directory to reconcile exact bytes; do not
regenerate it with new timestamps under the same tag. A public incomplete or changed
release is rejected and is never repaired automatically.

```sh
python3 tools/distribution_release.py fetch --native-only --repository OWNER/REPOSITORY \
  --tag distro-1.2.3-x86_64-r1-s1 --manifest-sha256 EXACT_MANIFEST_SHA256 \
  --output build/verified-channel --trusted-fingerprint FULL_PRIMARY_FINGERPRINT
```

`--native-only` fetches or verifies the four-file native channel projection while
reconciling every retained asset against the authenticated complete descriptor.
Use `verify --native-only --directory build/verified-channel` with the independently
trusted fingerprint before native configuration. Omit the flag for a complete
source/SDK/certificate recovery download and verification. Older signed installation
instructions remain verifiable; newly generated instructions select the native path.
The native projection still transfers the unified APT/Arch/Gentoo archive;
frontend-specific transfer requires a separately versioned authenticated format.

Fetch requires the exact manifest digest and independent fingerprint. It rejects
unexpected files, changed asset IDs during retrieval, missing evidence, wrong policy,
expired channels and a package release selected as Latest. `INSTALL.md` contains
the actual immutable URL, key fingerprint, APT source stanza, Arch configuration
and Gentoo overlay activation instructions. The managed overlay location is
`ACTIVATION_ROOT/current/gentoo`, with automatic external sync disabled. Keep previously accepted channel state
and apply the existing tools' rollback checks before moving a client to another
tag; signed bytes alone cannot establish freshness for a newly introduced client.

The implementation preflights GitHub's per-asset limit and the 1,000-asset bound
before remote mutation. Each direct package/source/dependency asset must be smaller
than 2 GiB; oversize input fails with no partially published channel. Existing native
channel generation additionally enforces its 256 MiB complete-channel bound.
The repository configuration follows the [pacman configuration contract](https://man.archlinux.org/man/core/pacman/pacman.conf.5.en); both package and database signatures are mandatory.
No Actions artifacts are uploaded. A final private CI bundle retains the prepared
assets or completed failure state for reconciliation, using the shared chunked
draft-release transport. Signing keys are never selected for that bundle.

Local fixtures use actual ELF executables, Debian packages and disposable signing
keys, plus a mocked GitHub service. They cover signature and inventory tampering,
source/certificate closure, publication planning, private partial failure,
idempotent recovery and complete downloaded verification. This does not establish
native pacman or Portage install/update qualification. The native workflow below
provides those checks; report its actual result for the exact release before
advertising support. Public service behavior requires hosted execution.

## Stable package mirrors

The separately published mirrors are historical deployments superseded by
[application-release packages](#application-release-packages) for future rebuilds.
Their [x86_64 instructions](https://github.com/mirage335-colossus/software-foundation/releases/download/packages-x86_64/INSTALL.md)
and [aarch64 instructions](https://github.com/mirage335-colossus/software-foundation/releases/download/packages-aarch64/INSTALL.md)
retain the original APT/Arch discovery URLs. Their exact publication and public
client evidence remains in [validation](validation.md#stable-package-repository-urls-2026-10-05).

That historical design retained versioned payloads while replacing signed indexes,
using a pending-state ledger and protected `mirror_only` publication jobs. Native
installation and upgrade across two mirror generations were not executed. The
mirror helper and workflow route have been removed from current source; no live
mirror, application release, asset or instruction was changed by that removal.
The obsolete older-payload retention obligation is superseded by qualification of
the new complete application-release layout. Legacy immutable distribution tools
and their exact-tag clients below remain available.

## Native acceptance and normal updates

The [native client workflow](../.github/workflows/distro-check.yml) fetches the exact
signed native channel and reproduces its complete signature, policy, expiry,
package inventory and package-byte checks before installation. It reconciles the
complete remote release asset identities and digests, while transferring only
`distribution.json`, its signature, the keyring and `channels.tar.gz`. Full source,
SDK and application certificate closure remains mandatory during publication and
separate recovery qualification. Debian Bookworm, Debian Trixie and Ubuntu
24.04 run natively on x86-64 and ARM64. Official Arch Linux and the current Gentoo
example image run on x86-64. Generating an ARM64 Arch/Gentoo recipe does not establish
native client support on those systems. Every backend in the selected archive must
install, retain its exact private files, launchers and manuals, pass its self-check,
accept a repeated repository refresh, and uninstall. An optional older `previous`
selection adds a real package-version upgrade using two published immutable releases.
Every previously present backend must have a strictly newer application version or
`package_release`; a sequence increase alone cannot qualify as a package upgrade.
Omitting it reports `upgrade_from: null`; repeated installation is not a version-upgrade claim.

An unchanged managed refresh fetches only the small signed controls, revalidates
the active native channel and derived repository bytes, and avoids extraction or
payload downloads. Changed selections may reuse only assets with matching exact
hashes. A failed refresh preserves the previous active generation.

Disposable Gentoo verification builds each binary wrapper, then resolves and merges
all selected backend atoms together with CPU/RAM-bounded `--jobs`. Its temporary
Portage environment uses `parallel-install -merge-sync`; ordinary client
configuration is unaffected. Two-revision Gentoo checks retain a 150-minute
container safety bound within a 180-minute job. Other checks retain 75-minute
container and 90-minute job bounds. Individual commands retain 15-minute limits.
These are failure ceilings, not predicted durations; cleanup still joins owned
containers and display services, and incomplete checks fail.

For this publication workflow, renewing expiring metadata requires increasing both
`sequence` and `package_release`, even when the application archive is unchanged.
Each immutable distribution tag changes retained source/SDK URLs embedded in native
package provenance. Those changed package bytes must receive a new package release.
The lower-level channel updater can renew metadata alone only when the complete
package specifications, including their retained URLs, remain identical.

`distribution.yml` calls these checks after initially publishing the signed channel
as a prerelease. Only its protected acceptance job may mark that same unchanged
channel eligible for automatic tracking. This changes the channel's qualification
metadata, never its files, source tag or the application's Latest selection. Failed
checks leave a reviewable prerelease. Evidence uses the private draft-release transport,
with exact run/attempt/job/source binding and no Actions artifact storage. The public
qualification marker binds the required native result digests. It supplements the
signed payload and independent key trust; it is not a new signing authority.

For manual qualification, dispatch `distro-check.yml` with `channel` set to:

```json
{"tag":"distro-1.2.3-x86_64-r1-s1","manifest_sha256":"EXACT_DISTRIBUTION_JSON_SHA256","target":"linux-x86_64"}
```

The optional `distro` input selects `apt`, `arch` or `gentoo` for focused diagnosis;
its default `all` runs every required client. A partial selection cannot use
`accept=true`. Use `accept=false` for observation, or `accept=true` with `all` after reviewing the publication
operation. The latter uses the protected publisher environment. A retry must match
the recorded exact identity; different accepted evidence needs an explicit reviewed
lifecycle transition, not replacement in place.

If a native check exposes a verifier or test-harness defect after publication,
preserve the signed channel assets and their original packaging source tag. Fix
and review the consumer-side defect, then dispatch the native workflow against
the same exact channel with the corrected checkout. All required native jobs must
pass in one qualifier run before acceptance. The public marker binds that
qualifier revision independently of the packaging revision retained by the signed
manifest. This permits requalification of unchanged packages without regenerating
signatures or replacing public bytes; it does not repair a defective payload.
Changed package contents require a new package release and immutable tag.

[`distro_client.py`](../tools/distro_client.py) provides normal client refresh through
Python, GnuPG and standard HTTPS. Public retrieval requires no GitHub account or
third-party Git hosting service beyond the project's own retained release. Install
an operator-trusted copy of the source tool tree and its `docs/release-policy.json`
at a persistent path, preserving the relative `tools`, `docs` and `third_party` paths.
Do not download and execute a changing remote helper during refresh.

The public client uses the REST API for complete release and asset metadata, then
fetches file bytes from their canonical public release URLs. Routing every retained
SDK, source, package and evidence file through the unauthenticated asset API can
exceed its hourly quota in a single refresh. The client binds each download ID to
the observed repository, tag, name, size and digest; limits HTTPS redirects and
transfer duration; stages fresh bytes; and verifies the full signed channel before
activation. Public data downloads do not require a GitHub token. Construct the
expected public URL by percent-encoding each validated tag and filename component;
for example, the plus in a Debian revision becomes `%2B`. Compare that canonical
URL exactly with metadata rather than decoding arbitrary URLs or relaxing origin,
path, query or digest checks. Metadata calls
still share the public API budget, so bound refresh frequency across clients and
preserve the last verified generation when retrieval fails. Explicit rate-limit
responses and HTTP 500/502/503/504 responses use at most three read attempts.
Metadata and asset operations share a 120-second wait budget. Each complete
metadata operation has a 180-second deadline; each asset has one 600-second deadline
covering all attempts, transfers and waits, with socket waits capped at 60 seconds.
The client respects the later applicable retry/reset delay and uses bounded
backoff for transient server errors. Exhaustion reports a sanitized metadata route
or bound asset ID, numeric rate fields and retry-delay guidance; it never prints
redirect query credentials or response bodies.

Every asset attempt restarts at the verified canonical URL with fresh redirect
state and a private response file. Failed responses and partial files close and
are removed before waiting; successful bytes still require the exact size and
digest before publication. A retry on a later metadata page restarts the complete
inventory. The client does not inject credentials or retry ordinary permission,
origin, size, digest or truncated-response failures. These bounds improve short
transient recovery but cannot guarantee availability during a prolonged outage
or exhausted shared public-IP quota. Follow [GitHub's retry guidance](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
within the local attempt, wait and whole-operation budgets.

Create a root-owned configuration outside the tool tree:

```json
{
  "schema_version": 1,
  "repository": "OWNER/REPOSITORY",
  "target": "linux-x86_64",
  "trusted_fingerprint": "FULL_INDEPENDENTLY_TRUSTED_PRIMARY_FINGERPRINT",
  "policy_sha256": "EXACT_REVIEWED_POLICY_SHA256",
  "selection": {"tag":"distro-1.2.3-x86_64-r1-s1","manifest_sha256":"EXACT_DISTRIBUTION_JSON_SHA256"},
  "location": "/var/lib/software-foundation-channel"
}
```

`selection: {"track":"qualified"}` explicitly opts into subsequent qualified
channels for the same target. Discovery is only a candidate lookup: all assets,
signatures, certificate evidence, target and policy are verified before activation.
The first trusted selection still requires independent freshness review. Once a
channel is accepted, sequence rollback, package removal, version downgrade and
same-version byte replacement are rejected. Trust-key or policy updates require an
operator-reviewed configuration change. Expired metadata fails; refresh signing
metadata with a new `sequence`, `package_release` and immutable tag before its expiry.

```sh
sudo python3 -B /opt/foundation-tools/tools/distro_client.py refresh --config /etc/foundation-channel.json
python3 -B /opt/foundation-tools/tools/distro_client.py config --config /etc/foundation-channel.json --kind apt
python3 -B /opt/foundation-tools/tools/distro_client.py config --config /etc/foundation-channel.json --kind arch
```

Install the printed APT stanza in a dedicated `.sources` file, or the Arch stanza
in a dedicated file included by `pacman.conf`. Import and locally trust the same
independently verified key with `pacman-key` before installation. Both frontends use
the locally retained signed repository through a single managed `current` pointer.
Run the refresh command before `apt-get update` or `pacman -Syu`, or schedule that
same explicit command using the host's service manager. A failed refresh preserves
the previous pointer; do not proceed to an intended upgrade as though it succeeded.
Ordinary package updates can continue using an unexpired retained generation when
network access is unavailable. This service is opt-in; application installation
never adds a timer or modifies package-manager configuration on its own.

For an explicit refresh followed by a normal interactive system upgrade, use the
single-operation entry point after installing that native configuration:

```sh
sudo python3 -B /opt/foundation-tools/tools/distro_client.py upgrade \
  --config /etc/foundation-channel.json --kind apt
# On a qualified x86_64 Arch host instead:
sudo python3 -B /opt/foundation-tools/tools/distro_client.py upgrade \
  --config /etc/foundation-channel.json --kind arch
```

This command upgrades the host's configured packages, not only Foundation. APT runs
`apt-get update -o APT::Update::Error-Mode=any` followed by `apt-get upgrade`; Arch
runs `pacman -Syu` to avoid a partial system upgrade. The native confirmation
prompts remain; the helper never supplies `-y` or `--noconfirm`. It requires root,
uses fixed native executable paths, and installs no hooks, configuration or timers.

A failed signed refresh, policy check, channel check or APT metadata update stops
the operation before upgrade. The helper reacquires the channel lock, rejects an
intervening generation change, and revalidates the signed assets/derived channel
before holding that lock through the native commands. A later native failure does
not roll back installed packages or discard the verified generation; inspect the
native error before an explicit retry. This convenience adds no new trust source,
freshness exception, rollback permission or automatic network fallback.

For Gentoo, the installed source tree must remain at its trusted path:

```sh
sudo python3 -B /opt/foundation-tools/tools/distro_client.py install-portage --config /etc/foundation-channel.json
sudo emaint sync -r software-foundation-bin
```

The adapter invokes the same authenticated refresh and activates the complete
binary overlay. Ebuilds wrap retained application bytes with empty compilation
phases; resolve host prerequisites through a configured binary package repository.
Version-3 and later recipes exclude the private application and manual directories from
Portage's compression transformations so installed-byte checks remain meaningful.
Version-1/2 template verification remains unchanged. Keep Portage's generated caches
outside the authenticated channel tree; modifications to a retained generation
fail the next refresh instead of silently becoming trusted input.

The refresh lock serializes cooperating callers. New complete generations are
verified before the atomic pointer replacement; old generations are kept for
inspection. A directory-sync failure after replacement is reported as uncertain:
inspect `current` and the retained manifests before retrying. The helper is not a
security boundary against another root process, and it does not garbage-collect
old SDK/source archives. Explicitly budget local disk space and retire only
unreferenced generations after stopping client writers.

### Repository trust configuration

The current repository distribution signing fingerprint is
`EF876322B5CE4782062CB3E991649063150BC781`. The private signing key is supplied only
through the `release-publisher` environment secret `DISTRIBUTION_SIGNING_KEY`; the
matching public fingerprint is configured as `DISTRIBUTION_SIGNING_FINGERPRINT`
in both repository and protected-environment variables.
This environment accepts the `main` branch. A project copied from this example
must generate its own key, configure its own independent trust value, and keep
a private recovery backup outside source control and release assets. Never copy
this fingerprint as authority for a different project's packages. Public releases
carry the corresponding verification key alongside signed metadata.

Native package metadata declares host services per backend: hosted web requires
Python, while Rev and SDL require a Mesa GLX vendor implementation. The signed
Arch/Gentoo request must include the union of the selected backend requirements;
for the complete GUI profile this is `glibc>=2.36`, `python`, `mesa`, `fontconfig`,
`ttf-dejavu` on Arch, and `>=sys-libs/glibc-2.36`, `dev-lang/python`,
`media-libs/mesa[X,opengl]`, `media-libs/fontconfig`, `media-fonts/dejavu` on Gentoo.
Debian metadata selects `python3`, `libglx-mesa0`, `fontconfig-config` and
`fonts-dejavu-core` where needed alongside glibc. Font configuration and font data
are runtime resources: bundling the client library alone does not provide them.
The native test bootstrap supplies verification/display infrastructure, but does
not explicitly install the vendor driver. Python also runs the verification
harness, so metadata checks establish its declared dependency and an installed
HTTP session test exercises the actual hosted-web wrapper. Private runtime
libraries remain bound to the original archive inventory.

Native container checks use an authenticated, job-owned Xvfb server supplied by the
runner's distribution. Only its own Unix socket and read-only authorization file
enter the container; no desktop session or host-wide authorization bypass is used.
Container names and labels bind cleanup ownership, containers stop before the
display server is joined, and display lifecycle evidence accompanies the native
receipt. This makes the display service explicit while keeping package-manager
and client-library verification native to each tested distribution. Gentoo
prerequisites remain binary-only even when optional display-wrapper packages are
absent from its current binary repository.

After both initial installation and each upgrade round, Arch qualification queries
`pacman -Q` for every packaged backend and requires the exact signed version and
package release. Payload equality and `pacman -Qkk` alone cannot prove an upgrade
when two revisions install identical files. Retain each round's native query
output and observed versions. Acceptance also binds every result to the requested
predecessor's exact tag and manifest digest; an initial installation cannot be
substituted for an upgrade or for another predecessor.

Arch keyring initialization runs in a dedicated child that remains alive through
initialization, key import, local trust, scoped service shutdown and bounded child
joining. It preserves the official Arch keys in the disposable container's existing
keyring. A successful `gpgconf --homedir ... --kill all` command alone does not
prove daemon completion; the worker must join its adopted children before exit.
The outer process owner still rejects any unconfirmed surviving descendant. Never
replace this with process-name termination or cleanup of another session's keyring.

APT metadata verification requires both the cleartext and detached signatures
from the independently trusted key. Capture decoded cleartext from a successful
`gpgv --output -` invocation: named-output finalization differs between versions.
The detached signature authenticates the exact canonical `Release` bytes. Some
providers include the cleartext framing newline in decoded output and others
exclude it; the comparison permits only that one terminal LF difference in either
direction. Other whitespace, line-ending or content changes fail. Keep tests for
both provider directions and invalid signatures when upgrading signing tools;
never substitute broad whitespace normalization for exact content checks.

New native recipes use specification version 4 so `src_prepare` invokes the
mandatory Gentoo `eapply_user` hook. Schemas 1–3 remain reproducible for immutable
readback, but their legacy no-op preparation phase cannot establish native Gentoo
support. Correct a published recipe with a new package release and sequence;
never edit signed historical bytes or silently change their template semantics.
The disposable Portage configuration accepts each selected package's exact
`Foundation-Bundled-<backend>` token. Partial license-name globs are not supported;
do not replace them with global license acceptance.

All native qualification frontends verify the complete signed distribution,
including its Debian packages. The disposable Arch and Gentoo environments
therefore install their distribution-provided `dpkg` verifier alongside signing
tools before running client checks. Gentoo obtains these prerequisites from its
configured binary repository with source-build fallback disabled.

Before channel refresh or package installation, resolve the complete signed runtime
atom set with `emerge --pretend --getbinpkgonly --usepkgonly
--binpkg-respect-use=y --oneshot --with-bdeps=n`. Host USE settings must satisfy
the actual binary dependency graph. The minimal Gentoo example host explicitly
sets `media-libs/libglvnd X` in its dedicated
`/etc/portage/package.use/software-foundation` file when the signed runtime atoms
require `media-libs/mesa[X,opengl]`. Other package settings remain unchanged.
Use the [per-package USE configuration](https://raw.githubusercontent.com/gentoo/portage/master/man/portage.5)
and preserve the [binary matching options](https://raw.githubusercontent.com/gentoo/portage/master/man/emerge.1);
do not replace a missing binary capability with source compilation or disabled
USE matching. A failed resolver check stops the disposable qualification before
its slower channel refresh. A changed profile or binary repository needs its own
recorded resolution and installation evidence.

Minimal distribution images may suppress manual-page installation globally. The
disposable native checks explicitly restore man-page extraction through the
package manager configuration before installation; they still compare every
public manual and private payload file with the authenticated package inventory.
