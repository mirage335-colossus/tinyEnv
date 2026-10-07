# C, C++, and Rust integration example

This is a fresh, standalone console demonstration for the software-foundation
tutorial. It verifies language linking and an event-style function; it does not
create a GUI or claim to record GUI interaction. It has no package downloads,
Cargo dependencies, or dependency on the software-foundation checkout.

`app.cpp` calls ordinary C17 source in `processing.c`, an ordinary C++20 helper
in `display.cpp`, and two Rust modules through a small scalar C ABI. `Services`
keeps the previous sample across handler calls. Each input is clipped to
`[-2, 2]`, multiplied by 2, then smoothed halfway toward its new value.

## Build and run

From this directory, with an existing native Rust compiler on `PATH`:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
./build/tutorial-integration
ctest --test-dir build --output-on-failure
```

If Rust is outside `PATH`, add
`-DTUTORIAL_RUSTC=/absolute/path/to/existing/rustc` to the configure command.
This example uses a native compiler matching the host C/C++ target. A cross build
also needs a matching Rust target and archive; this example does not configure
that process.

Verified output:

```text
Run 1: 2.000
Run 2: 3.000
C17 helper, C++20 handler, and Rust modules linked: PASS
```

## Tutorial excerpts

Add new C/C++ implementation files to the application's target:

```cmake
target_sources(tutorial-integration PRIVATE app.cpp processing.c display.cpp)
target_compile_features(tutorial-integration PRIVATE c_std_17 cxx_std_20)
target_link_libraries(tutorial-integration PRIVATE tutorial_rust)
```

The C header uses `extern "C"` when included by C++. Rust exports matching
`extern "C"` functions with stable linker names. The example passes only `float`
values, so it does not transfer object ownership or Rust containers.

Add Rust functionality by declaring its source module in `rust/lib.rs`:

```rust
mod gain;
mod smoother;

#[no_mangle]
pub extern "C" fn tutorial_rust_smooth(previous: f32, sample: f32, alpha: f32) -> f32 {
    smoother::apply(previous, sample, alpha)
}
```

List `rust/smoother.rs` in the CMake custom command's `DEPENDS` so changes rebuild
the archive. The custom command compiles `lib.rs`; Rust finds declared modules
beside it. It produces a `staticlib`, which the imported `tutorial_rust` target
links into the executable. No Cargo project or manifest is required for this
example.

In the actual software-foundation starter, generated GUI dispatch calls a handler
with this signature (read-only reference:
`editor/examples/simple/events.cpp`):

```cpp
void on_run(Services& services, foundation::visual::Ui& ui, const gui::Activate&);
```

That handler can call the same ordinary functions, then update the application's
widget through `ui.set_text`. This example's two-argument `on_run` isolates the
processing and linkage check; it is not a substitute for the generated GUI
signature.

The `no_std` Rust library uses `panic=abort`, a panic handler backed by the native
C runtime, and no allocator. These are example-specific choices that keep the
proof small; Rust integrations may instead use standard library facilities and
the required native runtime libraries.

## Verification

The executable checks two successive handler outputs, both clipping branches,
an unchanged in-range sample, and smoother endpoint weights. Checks remain active
in Release builds. CTest executes that same integration check.

Run `tutorial-video/examples/check_examples.py --only all` from the repository
root to retain the configure/build/run/test commands, outputs, compiler identities
and source hashes in
`tutorial-video/.work/examples/language-integration/verification.json`. The inspected local target was
x86-64 Linux; other platform builds have not been executed.
