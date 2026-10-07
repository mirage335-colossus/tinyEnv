# Arch and Gentoo channels from retained binary archives

[`tools/distro_channel.py`](../tools/distro_channel.py) generates an Arch binary
package and matching Arch/Gentoo recipes from one already qualified portable
archive. It also assembles and authenticates a complete local channel, then
activates a verified generation atomically on a qualified POSIX filesystem.
It performs no network retrieval, application compilation, prerequisite
installation or remote publication. See [distribution](distribution.md),
[release evidence](certification.md) and [retained dependencies](dependencies.md)
for the surrounding release contract.

## Inputs and supported scope

Prepare the application archive and its exact
[`artifact.py`](../tools/artifact.py) inventory first. The archive must have one
installation root and an executable `bin/foundation-cli`. Files keep their bytes;
executable files receive mode `0755`, other files `0644`, and directories `0755`.
Only regular files and required directories are accepted. Links, special entries,
privileged modes, ambiguous names, empty directories and unexpected executables
are rejected. The bounded example accepts at most 10,000 entries and 320 MiB of
total channel file content. A channel retains several copies of package bytes;
raise limits only with corresponding resource and failure tests.

The producer supports Linux `x86_64` and `aarch64`, mapped to Gentoo `amd64` and
`arm64`, with one architecture per channel. Native backend identities are `core`,
`terminal`, `framebuffer`, `fltk`, `rev`, `sdl` and `hosted-web`. Browser/Wasm assets
belong to the web delivery contract rather than a Linux executable package.
Generation support does not qualify any processor, operating system or native
package manager. GUI package generation requires the reviewed
[dependency terms](../third_party/gui-boundary.lock.json); the coexistence fixture
exercises templates without granting additional redistribution rights. The current
recorded permission applies to this repository's source and compiled binaries.

Every specification contains exactly these fields:

| Field | Required meaning |
| --- | --- |
| `schema_version` | Integer `6` for new packages: optional offline-browser and native desktop/browser launch files, combined-archive selection, enforced host services, complete retained notices and the mandatory Gentoo preparation hook. Versions `1`–`5` remain readable with their exact historical templates. |
| `version` | Three canonical numeric components, such as `1.2.3`. |
| `package_release` | Integer `1` through `999999`; increase for a packaging-only change. |
| `architecture`, `backend` | One of the explicit identities above. |
| `archive_url`, `archive_sha256` | Exact HTTPS application archive location and lowercase digest. |
| `license_files` | Complete retained notice paths, verified against the bundled GUI lock and dependency notice index. |
| `redistribution_approved` | Explicit `true` after review of all shipped terms. |
| `application_source`, `packaging_tool`, `sdk` | Each has exactly `url` and `sha256` for its retained archive. |
| `dependencies` | List of additional retained archive references with the same two fields. |
| `runtime_dependencies` | Explicit `arch` and `gentoo` lists including every required backend host service, font and driver. |

URLs must include their expected digest in the URL path, have no credentials,
query or fragment, and use HTTPS. This makes content identity visible and avoids
moving branch/tag assumptions; the bytes still require digest verification.
The application source, packaging tool, SDK and dependency references bind
retained groups, not a promise that an upstream server will retain them. Preserve
and publish those exact groups under the dependency-store contract before
publishing the channel. Keep the verifier implementing this schema with them;
do not change schema-1 template semantics and silently invalidate prior channels.
The helper verifies local application bytes and records provenance references;
it does not fetch or certify those referenced groups.

For example, stage the following already reviewed archives under `build/inputs/`:
`application.tar.gz`, `application-source.tar.gz`, `packaging-tool.tar.gz` and
`sdk-group.tar.gz`. The following creates the complete specification using their
actual digests. Replace the example publication host, version, runtime requirements
and notice paths with the release's reviewed values before delivery.

```sh
python3 tools/artifact.py create build/inputs/application.tar.gz \
  --manifest build/inputs/application.tar.gz.json
python3 - <<'PY'
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, 'tools')
import distro_channel as channel
root = Path('build/inputs')
def reference(name):
    value = hashlib.sha256((root / name).read_bytes()).hexdigest()
    return {'url': f'https://example.invalid/sha256/{value}/{name}', 'sha256': value}
archive = reference('application.tar.gz')
_, payload = channel.archive_payload(root / 'application.tar.gz',
    json.loads((root / 'application.tar.gz.json').read_text()))
spec = {
    'schema_version': 6, 'version': '0.1.0', 'package_release': 1,
    'architecture': 'x86_64', 'backend': 'core',
    'archive_url': archive['url'], 'archive_sha256': archive['sha256'],
    'license_files': channel.required_license_files(payload),
    'redistribution_approved': True,
    'application_source': reference('application-source.tar.gz'),
    'packaging_tool': reference('packaging-tool.tar.gz'),
    'sdk': reference('sdk-group.tar.gz'), 'dependencies': [],
    'runtime_dependencies': channel.runtime_policy('core')}
(root / 'spec.json').write_text(json.dumps(spec, indent=2) + '\n')
PY
python3 tools/distro_channel.py package \
  --archive build/inputs/application.tar.gz \
  --manifest build/inputs/application.tar.gz.json \
  --spec build/inputs/spec.json --output build/native-package-1
```

Output paths must be new and have an existing physical parent. A retry cannot
overwrite an earlier group. Production approval must come from the terms review;
the illustrative boolean above is not a substitute for that review. Dependency
lists describe the actual binary closure and target baseline, including every
required system library. They are not inferred from this example's tiny CLI.

## One build, several native packages

A normal CMake package contains the CLI and every selected native GUI backend.
Use specification version `6` to wrap that same qualified archive for each desired
backend. Select its required runtime services and new output directory; retain the same
`archive_url`, digest, inventory, application source, SDK and dependency references.
Generate one group per backend, then pass all groups to `assemble`. No application
or SDK rebuild, archive rewrite or manual deletion is needed. A single-backend
archive is also valid under version `6`. Existing version-`1` through version-`5`
specifications retain their original verification semantics; version `1` still
rejects combined archives. Use version `6` for new publications. Historical
schemas can still be authenticated, but versions `1`–`3` have a no-op Gentoo
preparation phase that does not meet EAPI 8 and must not be counted as native installation qualification.

For an archive whose reviewed native selection includes `terminal` and `fltk`,
the concrete producer sequence after terms approval is:

```sh
python3 - <<'PY'
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, 'tools')
import distro_channel as channel
root = Path('build/inputs')
base = json.loads((root / 'spec.json').read_text())
for backend in ('core', 'terminal', 'fltk'):
    specification = root / ('spec-' + backend + '.json')
    runtime = {manager: sorted(set(base['runtime_dependencies'][manager]) | set(required))
               for manager, required in channel.runtime_policy(backend).items()}
    current = dict(base, schema_version=6, backend=backend, runtime_dependencies=runtime)
    specification.write_text(json.dumps(current, indent=2) + '\n')
    subprocess.run([sys.executable, 'tools/distro_channel.py', 'package',
                    '--archive', str(root / 'application.tar.gz'),
                    '--manifest', str(root / 'application.tar.gz.json'),
                    '--spec', str(specification), '--output', 'build/native-' + backend], check=True)
PY
python3 tools/distro_channel.py assemble build/native-core build/native-terminal build/native-fltk \
  --output build/native-channel --sequence 1 \
  --signing-key /secure/release-private.asc --trusted-fingerprint FULL_PRIMARY_FINGERPRINT
```

The backend list is explicit: select only profiles present and qualified in the
input archive. All output paths must be new. Supply runtime dependency lists for
the whole retained shared closure before using this sequence.

The complete `bin/` inventory must contain `foundation-cli` and only these known
GUI executables: `foundation-gui-terminal`, `foundation-gui-framebuffer`,
`foundation-gui-fltk`, `foundation-gui-rev`, `foundation-gui-sdl` and
`foundation-gui-web`. The last executable corresponds to `hosted-web`. Every entry
must be a direct executable file; unknown names, nested entries, incorrect modes
and a missing selected backend fail. The package keeps the CLI plus its selected
GUI executable. A core package keeps only the CLI. Every file outside `bin/`
remains unchanged, including the complete private runtime libraries, plugins,
shared resources, developer exports, notices and provenance. Consequently runtime
dependency and license declarations must cover that retained shared superset;
selection does not establish a smaller dependency closure.

The group retains the original archive and full inventory unchanged, plus
`backend-selection.json`. The same receipt is installed at
`share/doc/Foundation/distro-selection.json` inside the private backend tree.
It binds the original archive digest and full file inventory digest, backend,
included and excluded executable digests/modes/lengths, and every retained file.
The generated receipt itself is covered by package/channel inventories. Receipt
path or ancestor collisions fail. Verifiers regenerate the projection and receipt;
a changed or omitted selection cannot be accepted as the original package.

Generated Arch and Gentoo recipes copy the verified combined tree, remove exactly
the named unselected executables from their private installation staging tree,
and install the same receipt. They never delete files outside that new package
tree. All original bytes remain available in the retained archive. A combined
archive containing GUI code requires resolved GUI redistribution terms even for
a core selection, because the retained archive and shared files still contain
that material. The current lock records permission for this repository owner's
software-foundation source and compiled releases. It does not grant unrelated
downstream projects a general Rev license; see the [recorded scope](gui-audit.md#distribution-gate).

## Generated native contents

An Arch package contains `.PKGINFO`, `.MTREE`, the unchanged private application
files, public launchers and combined retained notices. Each backend lives under
`/opt/software-foundation/BACKEND`. The core launcher is `foundation-cli`; another
variant gets `foundation-cli-BACKEND` plus its distinct `foundation-gui-*` launcher.
No private library enters a system library directory. The launcher executes the
private binary directly and preserves its arguments. New schema-6 recipes also
install desktop entries for FLTK, Rev, SDL and the TUI. A complete hosted-web
payload gets `foundation-gui-browser` and a terminal-owned browser desktop entry;
it binds loopback to an ephemeral port and closes with Ctrl+C. Core and the
file-output framebuffer host have no desktop entry. Historical schema templates
retain their original exact public files.
Public manual pages follow the same coexistence rule: `foundation-cli.1` belongs
to core, `foundation-cli-BACKEND.1` belongs to other variants, and each has
`software-foundation-BACKEND.7`. The generated Arch/Gentoo install bodies use
those exact filenames and preserve the archive's original private manuals.

`recipes/arch/` includes a complete `PKGBUILD`, matching `.SRCINFO`, notices and
launchers. Exact source digests bind the download and local helper files.
`package()` copies the private tree; it does not compile sources. The recipe
disables automatic stripping, separate debug output and manual-page compression
to preserve the qualified payload. Installation hooks are absent. See the
[Arch PKGBUILD reference](https://man.archlinux.org/man/PKGBUILD.5.en) for native
metadata and source conventions.

The Gentoo overlay includes `profiles/repo_name`, `metadata/layout.conf`, licenses,
EAPI-8 ebuilds, launcher files and full `Manifest` inventories. The ebuild downloads
the exact archive, declares runtime dependencies, invokes the EAPI-mandated
`eapply_user` preparation hook, leaves configuration and compilation empty,
installs the private tree and restores executable modes. See the
[Gentoo preparation contract](https://devmanual.gentoo.org/ebuild-writing/functions/src_prepare/index.html).
Qualification uses a disposable system without local user patches; any modification
to the retained payload still fails the exact installed-file check.
Release `1` maps to an ebuild without a revision suffix; release `2` maps to `-r1`.
Gentoo keywords remain testing keywords until that target's qualification supports
a stronger claim. See the [Gentoo installation function reference](https://devmanual.gentoo.org/ebuild-writing/functions/src_install/index.html)
when adapting installation behavior.

Verification regenerates every recipe, launcher and native package from the
retained input and compares exact bytes. Even a correctly signed channel is
rejected if it adds an unrecognized hook, changes a recipe, omits an overlay file
or references a different package. Customization requires a reviewed schema/tool
change and a new package release, not a post-generation edit.

## Sign, import and activate

Use independently trusted complete primary fingerprints. A public key bundled
with downloaded assets does not establish its own trust. The example signer uses
an exported dedicated signing key with no interactive passphrase; supply it through
a protected CI secret mount, outside outputs and the checkout. A production signing
service can replace this adapter while preserving verification and inventory rules.
The local prerequisites are Python 3, `gpg`, `gpgv`, `gpgconf` and a POSIX filesystem
supporting advisory locks, directory synchronization and atomic symlink replacement.
No prerequisite is installed by these commands.

```sh
python3 tools/distro_channel.py assemble build/native-package-1 \
  --output build/native-channel-1 --sequence 1 \
  --signing-key /secure/release-private.asc \
  --trusted-fingerprint FULL_PRIMARY_FINGERPRINT
python3 tools/distro_channel.py verify build/native-channel-1 \
  --trusted-fingerprint FULL_PRIMARY_FINGERPRINT
python3 tools/distro_channel.py sync build/native-channel-1 \
  --location build/accepted-channel \
  --trusted-fingerprint FULL_PRIMARY_FINGERPRINT
```

Assembly retains the original portable archive, its inventory, full specification
and generated recipes. It creates signed Arch packages and signed `.db`/`.files`
databases, the complete Gentoo overlay, `public.gpg`, and a detached signature over
`channel.json`. That metadata binds every other file's digest, length and mode,
target identity, all package specifications, a positive increasing sequence and
30-day validity. Directory contents must exactly equal the parents implied by the
file inventory. The private signing key never enters the output.

Retrieve a future candidate into a separate local directory using explicit
transport tooling, then pass the complete directory to `verify` and `sync`.
Retrieval is deliberately separate; it cannot overwrite the active generation.
Publish the entire immutable channel only through the authorized delivery process.
For package-manager use, the accepted `current/arch` directory contains the native
pacman repository, and `current/gentoo` contains the overlay. Configure the native
manager's trust separately and retain signature enforcement for Arch packages and
databases. Set the Gentoo repository location to the accepted overlay, disable any
second automatic sync writer for that location, and use the helper for updates.
This document does not install or modify a system's package-manager configuration.

The updater freezes and authenticates the incoming tree before touching the
activation directory. Under one local writer lock it validates the existing
generation, stages and synchronizes all files/directories, revalidates the stage,
then atomically replaces `current`. Old generations are retained under
`generations/SEQUENCE-DIGEST`; no previous generation or foreign file is deleted.
Unknown activation-root entries, changed prior contents and aliased locks cause
rejection. Keep the activation directory private to cooperating writers; advisory
locks do not exclude arbitrary privileged processes or untrusted mount changes.

Identical refresh is idempotent. Lower sequences, different bytes under the same
sequence, removed backend profiles, package-version downgrades and changed content
under the same package version/release are rejected. A higher sequence can renew
metadata for identical packages. Deliberate profile removal or key replacement
needs a reviewed migration rather than an implicit reset. Preserve/protect accepted
state: deleting `current` removes the local basis for rollback detection.

Any failure before replacement preserves the previous pointer. A durability or
cleanup error after replacement reports `CommitUncertain`; inspect and verify the
actual `current` generation before retrying. Never interpret that outcome as proof
that the old pointer remains active. Interrupted staging can leave an owned
temporary directory; the next run refuses unknown entries for reviewed recovery.
Do not delete a directory merely because its name resembles a temporary output.

## Verification and remaining qualification

[`tests/test_distro_channel.py`](../tests/test_distro_channel.py) exercises real
fixture signing and verification, A-to-B activation, repeated refresh, retained
old state, rollback, same-sequence and same-version conflicts, expiry, tampering,
untrusted identity, complete overlay imports, hidden hooks, unsafe archive names,
links/aliases, backend launcher coexistence, combined-archive selection for all
seven native profiles, unknown-executable rejection, selection provenance and
receipt collisions, failed staging, failure before pointer
replacement and explicit uncertainty afterward. Recipe shell syntax is checked;
GUI fixture approval is isolated to tests; a negative permission fixture also
rejects core selection from a combined GUI archive when its terms gate is closed. Generated Arch install bodies
execute directly in fixtures; Gentoo install bodies execute with small modeled
package-manager helpers. Their resulting bytes and modes are compared with the
generated native payload, including all shared resources. These checks do not
claim execution of the native package managers themselves.

```sh
python3 -m unittest discover -s tests -p test_distro_channel.py -v
```

These local fixtures have run on Linux with actual signing tools. They do not
establish native Arch or Gentoo installation support. Native `makepkg`, `pacman`
and `emerge` qualification is still required on every advertised target, including
generated metadata acceptance, install, A-to-B upgrade, offline cached install,
variant coexistence, remove/reinstall, retained file hashes and bounded checks of
each installed executable. Test custom runtime dependency lists in those native
environments. Windows activation is rejected; other POSIX filesystems, network
filesystems and crash/power-loss behavior require their own qualification.

## Authenticated automatic client refresh

See [native acceptance and normal updates](distribution-release.md#native-acceptance-and-normal-updates)
for the complete public fetch client, Portage sync adapter, APT/pacman configuration,
qualified-channel tracking and actual native client workflow. New distribution
releases generate version-6 recipes: combined-backend selection, complete notices,
required host services, preservation of installed bytes and the mandatory Gentoo
preparation hook. Old schemas retain their original exact templates. Local assembly and native client execution remain distinct
evidence scopes.

## Offline browser assembly

A native archive may additionally retain the verified prebuilt Wasm closure under
`share/software-foundation/wasm/`; see [building](building.md) and
[installed launchers](installed.md). Schema `6` adds a distinct
`foundation-gui-offline-BACKEND` command and desktop entry for every selected
backend carrying that complete closure. Native Arch binaries, PKGBUILDs and
Gentoo ebuilds project the same exact private files and generated public launch
bytes. Wasm is compiled once in its own target graph, then imported with an
explicit manifest digest and matching complete source identity. The local file
launcher uses the installed self-contained HTML; it does not run the hosted-web
server. Historical schemas `1`–`5` retain their exact previous templates.
