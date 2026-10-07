# Rust signal-processing example

Choose **Examples → Rust DSP** in the editor, or open `project.json`, choose
**Flows**, then **Rust FIR and decimation**. Double-click **Rust FIR / decimate 2** to edit the ordinary
`process_samples` function in [dsp.rs](dsp.rs). Its small C ABI wrapper is below
the algorithm. C++ stream-runtime plumbing is separate in
[flow_adapter.cpp](flow_adapter.cpp); the generated graph calls its factories.
Opening the example executes no code.

The Rust algorithm applies the three-tap FIR `[1/4, 1/2, 1/4]` and outputs every
second filtered sample. Each stream owns its history and decimation phase across
chunk boundaries. It stops before consuming an output-due input when the output
buffer is full, and returns separate consumed/produced counts. Startup history
is zero; finite input emits no synthetic padding or FIR tail. Nine inputs yield
four outputs, including an unmatched final input that updates history only.

Build and run from the repository root with an existing native Rust 1.63 or newer
compiler, C++20 compiler, CMake 3.24+, Ninja and Python 3.9+. There are no Cargo
crates, downloads, GUI toolkit or editor executable in this build:

```sh
cmake -S editor/examples/rust-dsp -B build/editor-rust-dsp -G Ninja
cmake --build build/editor-rust-dsp --parallel 2
build/editor-rust-dsp/foundation-editor-rust-dsp
```

If `rustc` is absent from `PATH`, add
`-DFOUNDATION_RUST_DSP_RUSTC=/absolute/path/to/existing/rustc` when configuring.
For this checkout, the already retained native compiler is
`$PWD/build/agents/rust-sdk/linux-sdk-final/bin/rustc`. The native C++ SDK that
builds the editor does not itself supply Rust; this optional example adds no
editor or SDK prerequisite. The Rust and C++ compilers must target the same
platform and ABI. These commands demonstrate ordinary native use; select and
qualify matching inputs through the project's normal toolchain policy for another
target. The existing SDK import guard remains in force for prebuilt archives.

The executable checks real Rust linking, filter values, uneven chunk boundaries,
zero/one output capacity, invalid ABI arguments, queue backpressure and fresh state
after graph restart. It prints the results and exits without a display. The C ABI
borrows caller-owned disjoint buffers only for the call and never retains pointers.
Rust uses no allocator, and a panic aborts instead of unwinding into C++.

After CMake configuration, the editor's **Build** and **Run** recipes use
`build/editor-rust-dsp`. A normal build recompiles `dsp.rs` when it changes and
relinks the executable; Run builds first. After graph edits, choose
**Save/Generate**, then rebuild. Retained generated headers are compiled directly;
CMake never invokes the editor.

The normal CMake rule runs this plain compiler command with its selected paths:

```sh
rustc editor/examples/rust-dsp/dsp.rs --crate-name foundation_rust_dsp \
  --crate-type staticlib --edition 2021 -C panic=abort -C opt-level=2 \
  -o build/editor-rust-dsp/libfoundation_rust_dsp.a
```

An optional `-DFOUNDATION_RUST_DSP_ARCHIVE=/absolute/path/to/prebuilt.a` consumes
a project-owned matching archive instead. In that mode its ordinary producer
owns recompilation, and the example does not discover or invoke Rust.
