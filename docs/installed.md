# Installed Software Foundation package

This native package contains `foundation-cli`, the static developer library,
public headers, a CMake package export, build information and license notices.
It does not install a background service or modify system configuration.

Extract the archive into a directory you own. Run `bin/foundation-cli --help`
(or `bin/foundation-cli.exe --help` on Windows) from that directory. Use
`--version`, `--self-check`, or `-- "First entry" "Second entry"` to exercise it.
The collection is in-memory; it does not persist records. Remove the extracted
directory to uninstall an archive installation. Do not overwrite a separately
managed installation with an extracted archive.

`build-info.txt` records the producing compiler and target. A native build does
not imply support for older operating-system runtimes. Use the release's stated
compatibility matrix and validation report when deploying to another system.

## Developer package

With a matching C++20 toolchain, configure your consumer with
`-DCMAKE_PREFIX_PATH=/absolute/extracted/prefix` and use:

```cmake
find_package(Foundation 0.1 CONFIG REQUIRED)
add_executable(example main.cpp)
target_link_libraries(example PRIVATE foundation::core)
foundation_apply_runtime(example)
```

Include `<foundation/store.hpp>` and `<foundation/version.hpp>`. The collection
owns its data, returns independent copies, accepts 1–256 printable ASCII bytes
per record, and requires caller-serialized access. Invalid input throws; IDs are
stable for the lifetime of each collection. The static C++ library requires a
compatible compiler, standard library and runtime configuration. This package
is not a standalone compiler/sysroot SDK.

Call `foundation_apply_runtime` for each final consumer target. It applies the
package's recorded Microsoft runtime choice, portable GNU/Clang runtime linkage,
or browser exception settings. Linking a static archive alone does not configure
the consumer's runtime. Keep the matching prepared SDK for SDK-produced packages;
this helper does not turn a different compiler or target into a compatible one.

A package produced with the default Rust core provider also installs its Rust
static archive. `foundation::core` includes that archive and its recorded native
link requirements automatically; ordinary installed C++ consumers do not need
Cargo, rustc or rustup. `build-info.txt` identifies the selected provider and Rust
compiler/SDK. The matching C++ toolchain, target and runtime requirements above
still apply; this does not add a general default-PIE or shared-library guarantee.
Explicitly selected C++ packages retain their original export without a Rust
archive. A consumer uses the same public interface for either provider.

The accompanying `LICENSE` applies to this package's own code.
`third_party/dependencies.json` records dependency status. Core packages contain
only the CLI and developer library. GUI packages additionally contain the selected
`foundation-gui-*` applications, shared resources and their notices; the release
inventory is authoritative for that selection. Each executable uses the same
application widget definitions and behavior. `share/doc/Foundation/dependency-notices`
retains the linked dependencies' notices and exact provenance. The matching source
repository provides the full development specification and reproducible build instructions.

A complete release also retains the exact prepared dependency groups that produced
its binaries. They are development/recovery assets, not application installation
requirements. Use the matching source tree's `tools/release.py verify` and
`recover` commands to check and restore those inputs without consulting a base
store. The release's compatibility evidence applies to exact archived bytes;
changing a private library or mixing files from different releases invalidates it.

## Desktop and browser launchers

New Debian/Arch/Gentoo packages install desktop entries for the FLTK, Rev and SDL
windows and the terminal UI. The hosted-web package also supplies
`foundation-gui-browser` when its complete asset closure is present. This starts
a private loopback server on an available port, opens the system browser and
prints the URL. Keep its terminal open; Ctrl+C closes the server and sessions.
Core and the framebuffer PPM-output example have no native-window desktop entry. These wrapper
files are verified package contents; they reuse the selected compiled payload.

## Optional offline browser application

A native archive assembled with `--wasm-package` also contains
`share/software-foundation/wasm/software-foundation-wasm.html`. Run
`share/software-foundation/open-offline.sh` on Linux or the adjacent
`open-offline.cmd` on Windows, or open that exact HTML
file in a browser. The scripts find the document in their adjacent `wasm` directory after archive
relocation; they do not start a server or select another installed version. Linux
automatic opening uses the desktop's `xdg-open` or `gio`; a browser remains a host
prerequisite. The HTML contains its Wasm, scripts, styles and license notices and
runs its application in a dedicated Worker with networking disabled by CSP.

New Debian/Arch/Gentoo package projections add the coinstallable
`foundation-gui-offline-BACKEND` command and an offline-browser desktop entry when
this complete payload is present. Even core/framebuffer variants can carry it.
The retained `web-manifest.json` and `manifest.sha256` identify the exact browser
bytes; native assembly requires an explicit manifest digest and the same complete
source snapshot. Separate native and Wasm compiler graphs reuse their finished
outputs. See [building](building.md) for the import flags.

On Windows, FLTK, Rev and SDL graphical executables use the Windows GUI subsystem
and a UTF-8 application manifest. Their composition-layer entry shim forwards the
CRT argument vector (and initializes SDL's main-ready state). The CLI, terminal,
framebuffer file-output and hosted-web process retain console entry points.
