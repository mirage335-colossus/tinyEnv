# Releases, distribution, and qualification

A release is an identified set of source, binaries, dependencies, documentation,
and evidence. Build and verify that set before making it the default download.
Preserve the exact released bytes; a later branch fix does not repair an older
download.

The repository implements local packaging, immutable SDK groups, complete local
release assembly/recovery, exact-evidence certification and Debian repository
metadata generation. These operations do not publish remotely. Having an
implementation or workflow does not establish multi-platform qualification.

Local packaging uses `./build.sh package release --rust-sdk /absolute/path/to/rust-sdk --jobs 2` and writes to
`build/release-rust-sdk/packages/`. The default is TGZ on Unix-like systems and ZIP on
Windows. The exact filename comes from CPack's project version, target system,
and processor. Inspect and verify the emitted archive explicitly:

```sh
python3 tools/artifact.py create PATH_TO_LOCAL_ARCHIVE --manifest build/package.json
python3 tools/artifact.py verify PATH_TO_LOCAL_ARCHIVE --manifest build/package.json
```

Replace `PATH_TO_LOCAL_ARCHIVE` with the actual generated filename. `create`
records the local producer's archive digest and member inventory; it does not
authenticate a downloaded archive. `verify` checks that identity, rejects unsafe
members, relocates the package into a path containing spaces, runs the CLI, and
builds an independent installed-library consumer. The current helper intentionally
accepts only ordinary files/directories and bounded archive sizes. Separate
`verify_abi.py`, native GUI execution and Debian installation scopes must also
pass for a release that claims them. A package smoke result is not a substitute
for those independent checks.

GUI installation and packaging require the reviewed redistribution record and its
complete notice inventory. The current owner-specific permission covers this
repository's GUI source and compiled binaries, including Rev; the GUI dependency's
project-owned CC0 dedication does not replace supplier terms. A new project must
establish its own applicable permissions before enabling public GUI delivery. See the
[GUI permission scope](gui-boundary.md).

## Target and asset inventory

Start with Linux `x86_64`, Linux `aarch64`, and Windows `x86_64` when those
platforms are relevant to the product. Choose explicit minimum runtimes and
test hosts using [the portability contract](portability.md). Do not advertise
targets that have only compiled or have no current qualification.

Generate a release matrix from one manifest containing target OS, architecture,
runtime baseline, feature selection, and GUI backend. Every enabled backend
needs a complete deliverable and the same shared functionality tests. Omit a
backend only through an explicit support decision; a missing asset must not
quietly reduce the promised inventory.

Use unambiguous names, for example:

```text
foundation-VERSION-linux-x86_64-cli.tar.gz
foundation-VERSION-linux-aarch64-cli.tar.gz
foundation-VERSION-windows-x86_64-cli.zip
foundation-VERSION-linux-x86_64-BACKEND.tar.gz
foundation-VERSION-source.tar.gz
release-manifest.json
SHA256SUMS
validation-RUN-ATTEMPT.json
```

`VERSION`, `BACKEND`, `RUN`, and `ATTEMPT` are placeholders to be filled by a
publisher. Backend packages must have separate extraction/install locations if
they coexist. Keep an identical application core and shared behavior in each.
Do not maintain separate feature implementations for release variants.

Include CLI and enabled GUI executables, runtime libraries, required resources,
user documentation, build provenance, dependency inventory, license notices,
and an internal file manifest. Include public headers, libraries, and CMake
exports in the developer package when they are supported deliverables. Keep
large optional diagnostic material separate from ordinary end-user packages.

## Identity and versioning

Record a clean source commit, packaging recipe commit, version, target matrix,
SDK/dependency recipe and archive digests, toolchain versions, build inputs,
creation time with timezone, run ID, and attempt. If repackaging existing binary
bytes, retain their original source and artifact identity and record the new
packager separately. Never describe the packager commit as the application
source when they differ.

Use a monotonically ordered version appropriate to each package manager. A
display label need not be the package version, but the mapping must be explicit.
If timestamps enter ordering, use UTC and a collision-resistant run identity;
local clock changes must not reverse version order. Tags identify fixed source
or recipe commits, never a moving branch.

The [release manifest template](templates/release-manifest.json) intentionally
contains unset values and an empty inventory. Fill and validate it for a real
candidate; it is not evidence of a release.

## Build once, inspect the delivered archives

Prepare required SDK recipes explicitly before application release work. Build
all planned producers against their exact inputs. Keep package producers
independent from expensive regression jobs where possible; join every required
result at the release gate.

For every archive:

1. Verify its digest and expected inventory before extraction or execution.
2. Reject unsafe paths, duplicate members, escaping links, unexpected special
   files, and invalid permissions.
3. Extract to a new owned directory with spaces in its path.
4. Verify the internal file manifest, required notices/resources, and build
   identity; reject unexpected as well as missing files.
5. Audit runtime requirements and dependencies across the entire package.
6. Run representative functionality on each claimed target baseline without
   development paths or development libraries providing accidental support.
7. Verify every enabled GUI backend's interaction and layout contract.
8. Install the developer package and build an independent consumer if shipped.

Checksums prove byte identity against an expected inventory; they do not by
themselves establish the publisher's identity. Publish an authenticated inventory
or supported release provenance mechanism with a documented trust root.
Keep the source and dependency archives required to reconstruct the package.

## Qualification and publication order

Create a draft release or local candidate. Freeze its asset inventory and compute
the manifest/inventory digest before qualification. Each report must identify
the exact source, target, archive hashes, inventory digest, checks, outcomes,
omitted scopes, run, and attempt. A report for another revision or different
bytes cannot satisfy the gate.

Require applicable source regression, installation/relocation, target-baseline,
all-backend, and distribution-install checks. `devfast` and branch diagnostics
never qualify a release. Failures and incomplete mandatory coverage keep the
candidate from becoming the default download. Preserve any accepted narrow
exception and its omitted scope explicitly under a pre-existing policy.

After qualification, publish the checked draft and then verify remotely that the
intended assets, digests, tag commit, release state, and default-download pointer
match the expected release. Do not assume an upload command's success proves
complete publication. On partial failure, inspect actual state and resume
idempotently; never overwrite a conflicting asset to hide a mismatch.

Choose an immutability policy before designing report uploads. GitHub immutable
releases require all assets to be attached before publication; later reports
must live in another durable location linked by the original inventory digest.
If immutable releases are disabled, keep application assets immutable by policy
and append uniquely named qualification reports. See GitHub's
[release management](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
and [immutable release guidance](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).

Prereleases remain separate from the ordinary update channel. Publishing or
qualifying an experiment must not move the stable default pointer. A corrected
release gets a new version/tag and new binaries. Retain prior supported releases
and required SDK inputs according to a stated retention policy.

## Debian packages and a repository hosted as release assets

A `.deb` download is an installable package, not by itself an APT repository.
CPack can create a package; operating an update repository additionally requires
package indexes, repository metadata, signatures, a trusted public key, stable
URLs, and installation/upgrade tests.

A flat repository can contain `Packages`, `Packages.gz`, `Release`, `InRelease`,
`Release.gpg`, a public archive key, a `.sources` example, and the `.deb` assets.
The signed `Release` metadata identifies index digests; indexes identify package
digests and locations. Bind the client to the repository's key with `Signed-By`
and document verification of the complete trusted key fingerprint. Do not ask
users to disable authentication. See Debian's
[APT authentication documentation](https://manpages.debian.org/stable/apt/apt-secure.8.en.html).

Use `amd64` and `arm64` in Debian metadata, mapped explicitly from the archive
architecture names. Package names and installation paths should permit intended
backend coexistence without colliding wrappers or private libraries. Declare
host runtime dependencies accurately. Verify ownership, executable bits,
directory traversal permissions, desktop integration, and uninstall behavior
as an ordinary user. A restrictive signing-job umask must not make installed
directories inaccessible.

Keep private signing material in the publisher's protected secret store. Import
it only into an ephemeral restricted directory, verify the expected public-key
identity, avoid logging its content, and remove temporary material on exit.
Publish rotation, expiry, revocation, and recovery procedures before operating
the channel.

Immutable version URLs are simplest for consistent snapshots. If a moving
default URL exposes repository indexes, make package `Filename` entries point
to immutable release URLs. Also address races between metadata and index fetches
through by-hash support, an atomic repository service, or tested bounded retry
behavior. Do not claim a release-assets-only arrangement has atomic multi-file
updates without evidence. Preserve enough earlier versions for in-flight clients.

Test clean installation, update from a supported prior version, intended backend
coexistence, removal, and corrupted/untrusted metadata. Do not equate a valid
signature with application correctness. Other distribution formats require their
own native metadata, trust, upgrade, and uninstall checks; reusing payload bytes
does not qualify those delivery channels automatically.

## Release checklist ownership

Assign one publisher for shared remote state. Other agents may build independent
owned targets and submit hash-bound results. The publisher verifies inventory
completeness, gathers applicable evidence, and records publication results.
Release automation needs explicit repository permissions and credentials; a
generic template must not contain real keys, tokens, or account-specific runner
names. See [CI](ci.md) and [agent coordination](agent-coordination.md).

## Executable local assembly and recovery

[`tools/release.py`](../tools/release.py) is the release assembler. It takes a
frozen JSON specification with `schema_version: 1`, a source archive path and
SHA-256, a nonempty artifact list, and required scope names. Each artifact names
its path, expected SHA-256, manifest path, target, backends and exact `sdk_recipe`.
Use [the specification template](templates/release-manifest.json); replace every
placeholder with observed values. This specification is input to assembly;
`release.json` is the resulting checked inventory.

Scope names are the exact identifiers in the [checked policy](release-policy.json):
`source` rebuilds retained source and checks its installed consumer, `archive`
exercises the delivered application archive, `recovery` restores exclusively
from release-owned dependency groups, and `abi` inspects target compatibility.
The Linux package policy additionally requires `apt`. Copy the applicable policy
inventory into the frozen plan; these names do not replace the required target,
backend and environment rows. A candidate's scope list cannot weaken that policy.

```sh
python3 tools/release.py assemble --spec candidate-spec.json --base /owned/base --output /owned/candidate
python3 tools/release.py verify /owned/candidate
python3 tools/release.py recover /owned/candidate --output /owned/recovered
```

Assembly requires one packaged `build-info.txt` whose `sdk_recipe_id` matches the
frozen specification. It verifies every package member, checks frozen source and
archive identities, copies the full exact dependency groups and validates the
complete assembled tree before atomically exposing the new directory. A missing
source archive, missing/partial base recipe, changed input, wrong packaged SDK
identity, duplicate asset or incomplete inventory fails. Existing destinations
are preserved.

Every binary release MUST contain its exact SDK binary, source and checksum
groups under `dependencies/<recipe>/`. A base URL, independently retained group,
cache or workflow artifact cannot replace these release-owned copies. Recovery
uses only the release tree and never consults the base, package manager or
upstream server. Restore a dependency group's sources or install its binary with
[`sdk.py`](../tools/sdk.py); use the retained producer for source replay.

A new recovery kit retains the byte-identical `release.json`, a versioned
`recovery.json`, the complete application source archive (including retained GUI
source when enabled), and every declared SDK binary/source/checksum group. It
omits application binaries. The exporter checks the staged kit before publishing
it, rejects output inside the original release, and preserves existing destinations.
Use an exclusively owned new output directory, as for release assembly.

Verify a copied kit independently after the original release and base are gone:

```sh
python3 tools/release.py verify-recovery /owned/recovered \
  --expected-release-sha256 ORIGINAL_MANIFEST_SHA256
```

Replace `ORIGINAL_MANIFEST_SHA256` with the independently trusted digest of the
original `release.json`, for example the inventory identity in verified release
certification. Do not obtain the trust pin from the kit being checked. Verification
checks the actual retained manifest bytes, complete target/dependency relationships,
source archive and tree identity, every SDK group's inner inventories, and the exact
kit file inventory. Missing, added, linked, substituted or changed inputs fail.
Without the optional pin, the result explicitly says `release_pin_verified: false`:
that proves local consistency, not publisher authenticity. Success reports
`scope: retained-recovery-inputs`; it does not certify binaries or execute a rebuild.
Legacy unversioned kits lack original release metadata and are rejected with a
re-export instruction; they are never silently upgraded or treated as authenticated.

After verification, extract the source archive into a new owned source directory.
Select the intended target in the retained manifest's `artifacts` list and its
exact `sdk_recipe`/`dependency_recipes`. For Linux and Wasm, install its retained
binary group with
`tools/sdk.py install --group KIT/dependencies/RECIPE --recipe RECIPE --output NEW_SDK`.
For Windows, use `tools/sdk_windows.py install` with the same arguments and
`--linker-version ACTUAL_SELECTED_LINKER_VERSION`, following the
[Windows host-tool selection and compatibility checks](sdk.md#windows-dependency-base-and-separately-installed-host-tools).
To extract retained producer inputs, use `tools/sdk.py restore-sources` with the
group, recipe and output arguments. Then follow
[the target-specific SDK build instructions](sdk.md) from that source.
Keep the verified kit immutable and place extraction, SDK and build outputs outside
it. These operations require no base or upstream server; independently retain the
[declared host prerequisites](dependencies.md#bootstrap-without-recurring-supplier-access).
Wasm recovery still includes retained upstream precompiled tools; it does not claim
that LLVM, Binaryen or Node have been rebuilt from distribution-provided source.
This explicit verifier adds no work or dependency to ordinary application builds.

The `release.json` output binds source bytes, application archive/member
inventories, complete dependency-group hashes, target/backend identity and
required scopes. Assembly marks it `candidate`. [Certification](certification.md)
binds complete evidence to its exact digest; it does not infer success from
queued workflows, missing reports or a later source checkout. Keep generated
certificates outside the immutable candidate tree unless a new manifest
explicitly includes them.

For hosting, publish the assembled bytes and their authenticated inventory using
an authorized release job. A local success is not remote publication. GitHub
release download assets and a usable APT repository are distinct delivery forms;
see [Debian distribution](distribution.md) for generated Packages/Release
metadata, signing and repository-install qualification.

## Qualification evidence and adoption limits

A production claim requires the exact candidate to pass each policy scope on its
stated target: portable ABI/runtime closure, clean relocated package, installed
library consumer, every shipped GUI backend, browser execution where applicable,
Debian installation where supplied, retained-input offline recovery and selected
regression checks. Record unavailable scopes as unavailable; never convert them
into a green status. Optional omissions remain visible in the report.

The [validation record](validation.md) identifies actual native source production,
Windows compiler runs and fresh-consumer observations for exact retained recipes.
Other recipes and the oldest-host matrix still require their own execution evidence.
Windows archive/provenance/linker fixtures do not replace a Windows compiler run.
Browser Node smoke remains separate from actual browser-host behavior. Consult
the recorded environments and material limits before advertising support.

## Source and feature identity

Create the source archive with the same source inventory used during compilation:

```sh
python3 tools/source_identity.py digest --root .
python3 tools/source_identity.py archive --root . --output /owned/application-source.tar.gz
python3 tools/source_identity.py verify --archive /owned/application-source.tar.gz
```

When using an external GUI checkout, pass `--supplement /owned/gui-source` to
both identity and archive operations. Its actual source bytes are retained under
`third_party/retained/gui/`; recovery must not depend on an upstream URL surviving.
A source archive includes `source.json`, complete per-file hashes and executable
modes. Generated build outputs and ignored coordination files are excluded.
Snapshot creation rechecks the input tree before publishing the archive.

Release assembly verifies that each package's `source_tree_sha256`, normalized
`target`, `gui_backends` and full `dependency_recipes` list match the source
archive and frozen specification. The `sdk_recipe` is the primary prepared
input; optional `dependency_recipes` lists additional required groups and must
include that primary input. Every distinct group in the artifact union is
copied into the release. Relabeling a package or replacing its source with an
unrelated archive fails even if the replacement has a valid checksum.
