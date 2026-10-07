# Shell scripts and interpreter compatibility

`build.sh`, `editor.sh` and `fork.sh` support both Dash and traditional
SVR4-style Bourne shell, tested with Heirloom Bourne 050706. CI bootstrap helpers
and generated offline launchers retain their modern POSIX shell requirements.
Modern Git, Python, CMake and Unix utilities are still required where used.
The original V7 shell and historical operating systems are outside this scope.

## Maintained entry points

| Script | Purpose | Additional requirements |
| --- | --- | --- |
| [`build.sh`](../build.sh) | Dispatch build/test/package arguments to `tools/build.py`. | Python and the selected [build prerequisites](building.md). |
| [`editor.sh`](../editor.sh) | Select the system or retained-SDK editor, build it if absent, then launch it. | Native editor prerequisites in [COMPILE-editor](../COMPILE-editor). |
| [`fork.sh`](../fork.sh) | Create an independent shallow repository with the original `main` tip and no remote. | Git, `mktemp -d` and modern Unix utilities; [configuration](../README.md#start-a-new-repository). |
| [`tools/ci-apt.sh`](../tools/ci-apt.sh) | Configure Debian/Ubuntu CI mirrors and perform bounded APT recovery; unchanged. | Modern POSIX shell (including Dash), Debian/Ubuntu APT, dpkg, coreutils, sed and grep; installation permissions when actually installing. |

This table enumerates the four tracked standalone project shell scripts. It
excludes unrelated workspace backups and external dependency scripts.

## Generated shell entry points

| Generated file or command | Maintained source | Purpose and interpreter |
| --- | --- | --- |
| `share/software-foundation/open-offline.sh` | [`tools/import_wasm.py`](../tools/import_wasm.py), `POSIX_LAUNCHER` | Open the adjacent verified Wasm document with `xdg-open` or `gio`; modern POSIX shell, unchanged. |
| `/usr/bin/foundation-cli`, `foundation-cli-BACKEND`, `foundation-gui-*` | [`tools/apt_repo.py`](../tools/apt_repo.py), `launchers` | Debian public wrappers for private installed binaries; already compatible, unchanged. |
| `/usr/bin/foundation-gui-offline-BACKEND` | [`tools/apt_repo.py`](../tools/apt_repo.py), `offline_desktop_files` | Debian wrapper for the private offline-document launcher; already compatible, unchanged. |
| Arch/Gentoo public CLI and GUI wrappers | [`tools/distro_channel.py`](../tools/distro_channel.py), `recipe_files` | Dispatch to the corresponding private backend binary; already compatible, unchanged. |
| `PKGBUILD` and EAPI-8 `.ebuild` recipes | [`tools/distro_channel.py`](../tools/distro_channel.py) | Package-manager recipes; retain their package manager's Bash requirement. They are not standalone `/bin/sh` entry points. |

The existing public package wrappers do not enable `set -u`; their `"$@"`
forwarding already preserves zero and empty arguments under Dash and Heirloom.
Their templates, package schemas and verification code are unchanged. The public
offline wrapper can forward arguments under either shell, but its child
`open-offline.sh` still requires a modern POSIX shell. Existing archived copies
remain unchanged. See [Debian projections](distribution.md) and
[native channel schemas](distro-channels.md).

The portability change is limited to locally testable wrapper behavior: path
resolution, argument boundaries, editor selection and child exit status. CI APT
configuration and the generated offline launcher remain byte-for-byte unchanged.
APT fixtures cannot establish real mirror/installation behavior, and changing
generated launcher bytes affects verification of retained staging directories.
Those changes are excluded from this shell compatibility work.

The hosted-web browser launcher is generated Python, not shell. Vendor SDK
scripts retain upstream interpreter requirements; `tools/sdk_wasm.py` adjusts
the retained Emscripten driver without promising historical shell compatibility
for the entire SDK. Test-only shell stubs are disposable fixtures rather than
public entry points.

## Verification and maintenance

In the scripts supporting traditional Bourne shell, avoid `$(...)`, arithmetic
expansion, parameter prefix/suffix trimming, `command -v`, `cd --` and shell `!`
negation in the common shell subset. Use
guarded `${1+"$@"}` when forwarding an optional argument list with `set -u`. Traditional
Bourne shells also differ in redirected compound-command scope and `set -e`/
exit-trap behavior, so syntax checks alone are insufficient.

The shell fixtures use inert build/editor substitutes. They check literal and
empty arguments, paths, editor selection, dispatch and failure statuses without
opening a GUI, building applications or fetching from the network.
The launcher fixture is opt-in: `manual_shell_launchers.py` is excluded from
normal `test_*.py` discovery and is not registered by CMake.

```sh
FOUNDATION_TEST_SHELL=/bin/dash python3 -B tests/manual_shell_launchers.py
```

Set `FOUNDATION_TEST_SHELL` to one interpreter executable path to exercise the
build/editor fixtures with a specific shell. The fork suite uses
`FOUNDATION_FORK_SHELL`. Set both when selecting another interpreter;
the normal defaults use `/bin/sh`. Missing requested interpreters are failures,
not skipped checks. These local checks require no application rebuild, signing,
package qualification or GitHub Actions dispatch. Workflow definitions and CI
selectors are unchanged. A future push or pull request can still run the existing
broad development feedback for changed shell entry points; the opt-in launcher
fixture adds no normal test suite.
