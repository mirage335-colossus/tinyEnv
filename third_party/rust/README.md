# Retained Rust SDK extensions

The default Rust provider consumes a separate `FOUNDATION_RUST_SDK_ROOT`, paired
with the application's retained C++ SDK or Windows MSVC dependency SDK. These
recipes use official Rust distribution archives, Rust 1.63.0 and Cargo 1.63.0.
Cargo's distribution package reports `0.64.0`; the executable reports `1.63.0`.
No rustup installation, user toolchain override, or application crate download
belongs in an ordinary build.

SDK-free native `dev` builds may instead use Debian-family package-owned Rust
tools and complete distribution notices. Every other supported profile needs
this retained extension. `--core-provider cpp` is the explicit legacy route;
unavailable Rust inputs never silently select it.

| Recipe | Host | Target |
| --- | --- | --- |
| `linux-x86_64.json` | Linux x86_64 | `x86_64-unknown-linux-gnu` |
| `linux-aarch64.json` | Linux aarch64 | `aarch64-unknown-linux-gnu` |
| `windows-x86_64.json` | native Windows x86_64 | `x86_64-pc-windows-msvc` |
| `wasm32-emscripten.json` | Linux x86_64 | `wasm32-unknown-emscripten` |

All supplier URLs and SHA-256 values are literal recipe inputs. The retained
Rust 1.63.0 release manifest supplies component checksums. Compiler source
`src/stage0.json` supplies the Rust 1.62.0 bootstrap compiler, Cargo and host
standard-library checksums. The source group contains the actual archives for
both generations. Stage0 archives are retained inputs; the preparer installs
the official 1.63.0 binary distributions directly and does not execute stage0.

The source group also contains the full official compiler source distribution,
its vendored crates and Cargo source subtree, the `rust-src` distribution,
bootstrap metadata, exact producer helpers, and the complete recipe. The binary
group contains compiler/Cargo executables, their bundled support libraries,
matched host/target `core`, `std` and compiler-builtins, unpacked library sources,
and the supplier notices. Linux compiler inspection checks the Bookworm ABI
ceiling; host glibc and `libgcc-s1` remain explicit OS prerequisites. Native
Windows final linking additionally requires the existing Microsoft v143 toolset
and Windows SDK selected by the application's normal Windows build session.

The Wasm extension pins the complete paired C++ SDK recipe, Emscripten 6.0.10,
and its supplier version-file bytes `6.0.10-git`. The allocation-free application
component uses native Wasm objects with panic abort and without cross-language
LTO. An observed component build does not qualify arbitrary Rust standard-library
facilities, pthreads, or all other Rust/Emscripten combinations.

Explicit producer and restore commands, run from the project root:

```sh
python3 tools/rust_sdk.py recipe-id --recipe third_party/rust/linux-x86_64.json
python3 tools/rust_sdk.py fetch --recipe third_party/rust/linux-x86_64.json --inputs /owned/rust-inputs
python3 tools/rust_sdk.py prepare --recipe third_party/rust/linux-x86_64.json --inputs /owned/rust-inputs --output /owned/rust-group
python3 tools/rust_sdk.py install --group /owned/rust-group --recipe RECIPE_SHA256 --output /owned/rust-sdk --execute
python3 tools/rust_sdk.py verify --root /owned/rust-sdk --execute
python3 tools/rust_sdk.py restore-sources --group /owned/rust-group --recipe RECIPE_SHA256 --output /owned/rust-sources
python3 /owned/rust-sources/tools/rust_sdk.py prepare --recipe /owned/rust-sources/recipe/rust.json --inputs /owned/rust-sources/inputs --output /owned/replayed-rust-group
```

Only `fetch` acquires supplier bytes. `prepare`, `install`, verification and source
restoration use local retained inputs. For the Wasm recipe, pass
`--cpp-sdk /owned/browser-sdk` to preparation and verification. A group contains
exactly `rust-sdk-RECIPE_SHA256-binary.tar.gz`, its `-sources.tar.gz`, and
`-SHA256SUMS`. Verification checks the two archive hashes, complete inner
inventories, recipe/helper identity, exact supplier inputs and binary-to-source
manifest binding. Restore uses a new destination and validates before activation.

This proves retained toolchain restoration and supports a disconnected
application build. Rebuilding the Rust compiler, LLVM, Cargo and all bootstrap
requirements from source is unexecuted and outside this recipe's qualified
recovery scope. The retained source and stage0 archives must not be described
as proof that such a reconstruction ran successfully. See the maintained
[SDK documentation](../../docs/sdk.md) and [validation record](../../docs/validation.md)
for the implementation contract and observed platform qualification.
