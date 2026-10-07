# Native package repositories and copied installations

A package-manager channel wraps already qualified portable archives. It must not
silently rebuild the application or substitute the packager's current SDK. Retain
application-source identity, original archive digest, packaging-tool revision and
all exact dependency groups. Generate a new candidate when recipes change; never
replace an earlier published asset to make a retry pass.

## Debian and Ubuntu

[`tools/apt_repo.py`](../tools/apt_repo.py) provides a concrete local Debian package
and signed flat repository path using distro-provided `dpkg-deb`, `gpg` and `gpgv`.
It verifies the portable archive inventory, compares the final Debian payload with
the staged source payload, rejects hidden installation hooks, and keeps each backend
under `/opt/software-foundation/BACKEND`. Public launchers preserve the private tree.
When the archive includes the installed manuals, expose the core CLI as
`man foundation-cli` and each GUI variant's CLI as `man foundation-cli-BACKEND`.
Each package exposes `man 7 software-foundation-BACKEND`; private original manuals
remain byte-identical. These regular public copies are part of the verified
payload and are removed with the owning package, so variants can coexist.
Backend suffixes let multiple GUI variants coexist. GUI redistribution remains
blocked while the dependency's recorded terms are unresolved.

The Debian wrapper accepts a combined native archive. Each package contains only
`foundation-cli` plus its selected GUI executable; `hosted-web` selects
`foundation-gui-web`, and `core` selects only the CLI. Unknown or nested executable
entries, nonexecutable programs, a missing selected host and generated receipt-path
collisions fail before an output package directory is published. Public CLI
launchers gain the backend suffix; each GUI launcher keeps its distinct executable
name. New packages add desktop entries for FLTK, Rev and SDL, and a terminal
entry for the TUI. A complete hosted-web payload also gets `foundation-gui-browser`,
a visible terminal launcher that opens a loopback server at an ephemeral port and
the system browser. Ctrl+C closes its server and sessions; it prints the URL when
automatic browser opening is unavailable. Core and file-output framebuffer packages
have no desktop entry. No source recompilation or relinking occurs.

All files outside `bin/` remain byte-for-byte present, including the complete
private runtime, resources, developer export and notices. This deliberately retains
a shared-file superset. A core selection from an archive containing GUI code still
requires its GUI redistribution terms, because shared resources remain present.
The complete original archive receives the ABI/loader audit; selection only removes
known application executables and preserves every runtime-provider path.

New Debian payload receipts use schema version `4`, adding optional offline-browser
launch files to the exact generated public inventory. Schemas `2` and `3` remain readable
with its unchanged historical template. They bind the original archive
manifest and digest, its complete source-file inventory, selected and omitted
executable identities, and every retained file. An installed
`share/doc/Foundation/debian-selection.json` records the same selection. Verification
reconstructs the exact permitted private tree and public launchers from that record;
a renamed backend or changed original inventory cannot qualify a package. Older
schema-1 receipts lack this proof and must be regenerated into a new output.

```sh
python3 tools/apt_repo.py package --archive build/application.tar.gz \
  --manifest build/application.tar.gz.json --version 1.0.0 \
  --architecture amd64 --backend core --output build/debian-1
python3 tools/apt_repo.py assemble --output build/apt-1 \
  --base-url https://example.invalid/releases/download/v1.0.0/ \
  --signing-key /secure/release-private.asc --trusted-fingerprint FULL_PRIMARY_FINGERPRINT \
  --sequence 1 build/debian-1/*.deb.json
python3 tools/apt_repo.py verify build/apt-1 --trusted-fingerprint FULL_PRIMARY_FINGERPRINT \
  --output build/accepted-repository-1.json
```

The URL and fingerprint are explicit replacements for a real deployment. All
commands above only write local outputs. Assembly uses a temporary private keyring;
private keys must stay outside the checkout and output. The repository's public key
must match an independently trusted complete fingerprint. Never establish trust
solely from a key downloaded beside the assets it authenticates.

The flat output includes `.deb` files, payload receipts, `Packages`, `Packages.gz`,
`Release`, `InRelease`, `Release.gpg`, a public keyring and `repository.json`.
Publish every output immutably as release assets when separately authorized.
`Packages` uses repository-relative `Filename` entries, as expected by
[the Debian index format](https://manpages.debian.org/bookworm/dpkg-dev/dpkg-scanpackages.1.en.html).
An absolute HTTPS URL in that field is not supported: APT appends it to the source
URI and requests the wrong path. A consumer pins `URIs:` to the immutable release
directory used for `--base-url`, uses `Suites: ./` and a `Signed-By` path, and keeps
that directory available throughout refresh and installation. For GitHub Releases,
use `/releases/download/EXACT_TAG/`; do not point APT at `/releases/latest/download/`.

To update, publish the complete newer repository under a new immutable tag, verify
it against the prior accepted record with `--previous`, then change the consumer's
source URI to that exact tag. Run `apt-get update` and install the explicitly
selected package version; retain the preceding assets for rollback investigation
and clients still using them. Signed hashes reject substituted bytes, but cannot
make a moving URL retain an older payload. A continuously updated repository needs
a publishing design that preserves every indexed payload; the
[stable package mirrors](distribution-release.md#stable-package-mirrors) retain
versioned packages while replacing signed indexes and await native stable-URL
qualification. Do not use
`trusted=yes`, disable validity checking, or install private libraries into system
library directories.

Repository verification checks both signatures, matching signed content, complete
metadata and payload inventories, expiration/future dates and every payload receipt.
Use `--previous` with the prior accepted verification record to reject a lower
sequence or changed content under the same sequence. Identical refresh is idempotent.
Keep accepted state until a verified replacement is durably saved. A package's
version must also increase under the package manager's comparison rules; UTC build
identifiers avoid ambiguous local timestamps. A new metadata sequence alone cannot
make an older package version a legitimate upgrade.

The accepted verification record also retains each package's SHA-256. A newer
metadata sequence may advertise the same version only when its package bytes are
identical. Changed bytes require a greater package version. A prior record missing
that payload identity cannot authorize an equal-version replacement; establish a
reviewed trusted baseline rather than silently accepting it.

Native qualification must test initial install, A-to-B update, idempotent refresh,
variant coexistence, remove/reinstall, offline cached install, changed bytes,
untrusted key, expired metadata, rollback and interrupted retrieval. Verify actual
installed file hashes and run bounded CLI and GUI checks. A package creation fixture
is not an installation test. Signing fixture keys are disposable and never trusted
for delivered releases. Read the [Debian control field policy](https://www.debian.org/doc/debian-policy/ch-controlfields.html)
and [APT authentication contract](https://manpages.debian.org/bookworm/apt/apt-secure.8.en.html)
when adapting installation metadata.

## Other native channels

The same source/binary identity contract applies to Arch/pacman, Gentoo and other
package managers. A native recipe must point to an immutable verified archive,
install its private tree and notices, and expose nonconflicting launchers. It must
never download an unpinned moving branch during installation. Treat a recipe as
executable code and review its complete install/uninstall behavior.

For pacman, generate one binary package per target/backend, verify the package
contents against the portable inventory, sign package and repository database,
retain both detached signatures, and test native `pacman` install/update/remove.
Use one checked repository database update transaction; reject duplicate names,
foreign architecture, unexpected script hooks and a database referring to missing
payloads. Publish metadata last, after immutable packages are available.

For Gentoo, use a binary-package or binary-archive ebuild with exact source URLs,
digests, supported architectures, terms and host runtime dependencies. An overlay
sync helper must authenticate a complete versioned inventory, reject rollback and
same-sequence replacement, stage all files before activation, preserve the prior
working overlay on any error, and remove only previously owned stale files.
Bootstrap host prerequisites from a configured binary repository; if a required
binary is unavailable, fail with an actionable explanation instead of starting a
long source build implicitly. Qualify both initial installation and update on a
native environment, including absent or tampered metadata and recovery.

Do not claim these channels from a Debian test. Add their exact native acceptance
checks to the frozen release policy before advertising them. A generated recipe
without a native installation result is an implementation input, not qualification.

## Copied portable archives

Keep `bin`, private `lib`, data and notices together. Run directly without checkout
paths, registry edits or loader override variables. Preserve executable modes and
check the complete inventory before execution. The destination provides its system
loader, compatible kernel, display services/fonts and drivers. A bundled library
does not supply those services. Installer/package tools are not runtime prerequisites.

A relocation test removes access to the original installation, clears ambient
loader overrides, uses a destination with spaces and verifies dependency resolution.
It must reject missing, modified and unlisted files. Check all native executables,
shared libraries and required browser assets from the final archived bytes; do not
substitute checks on an unarchived staging tree. See [portability](portability.md)
and [certification](certification.md) for target/runtime qualification.

## Prebuilt offline browser payload

Native archive assembly can import a separately built, verified Wasm package from
the exact same source snapshot, without recompiling Wasm for each native target.
The [build wrapper](building.md) requires the package directory and exact
`web-manifest.json` SHA-256. Configure, selected application builds, direct install
and CPack recheck that identity and the complete embedded asset/notice inventory.

When the installed `share/software-foundation/wasm/` closure is present, schema-4
Debian projections retain every browser byte and generate
`foundation-gui-offline-BACKEND` plus its desktop entry. The command opens that
private installation's document through its adjacent relocatable launcher.
Incomplete closures fail packaging. Hosted-web launch behavior remains separately
available, and earlier schema projections reproduce their original bytes.
