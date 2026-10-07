# From a task to the file you edit

Start with the behavior you want to change. Open its owning file, find the small
function, make the change, then check the result. The paths below are relative
to the repository root unless a table gives a prefix.

The visual editor is optional. If you want an AI agent's work to remain visually
editable, ask it to follow the project schema, typed event bindings and block
interfaces in `editor/README.md`. The editor does not infer a visual design from
arbitrary source. You can also work entirely with ordinary source tools.

## Small C application

Prefix: `editor/examples/simple-c/`

| What you want to change | File | Where to look |
| --- | --- | --- |
| Gain calculation | `signal.c` | `simple_c_apply_gain`, lines 20–22 |
| Processing state or declarations | `signal.h` | State structure and public C functions |
| What Run does | `events.c` | `simple_c_on_run` |
| UI callbacks exposed to C | `events.h` | `struct simple_c_ui` |
| C callbacks connected to the shared GUI | `event_adapter.cpp` | Adapter functions |
| Stream buffers connected to the C algorithm | `flow_adapter.cpp` | Processing block adapter |
| Controls, event bindings and graph connections | `project.json` | Forms and Flows in the editor |
| A newly created Reset handler | `src/ui/i_button1_activate.hpp` | Created in the tutorial's disposable project |
| Additional compiled source files | `CMakeLists.txt` | `simple-c-behavior` and the application target |
| Expected application results | `main.cpp` | Assertions for behavior and generated bindings |

The demonstrated edit changes `return sample * gain;` to
`return sample * gain + 1.0f;`. Inputs `1, 2, 3, 4` with gain `2` change from
`2, 4, 6, 8` to `3, 5, 7, 9`. The [replay check](examples/algorithm-walkthrough/README.md)
compiles both versions in generated copies. Update the full application's
expectations deliberately when adapting it to the new behavior.

In the editor, use **Files → Open** with a project-relative path, then **Find**
with the function name. Bound widgets and processing blocks also offer direct
routes to their source. Save the design after changing layout or bindings;
rebuild after source changes. `generated/visual/` contains generated connections
and layout: change the saved design when you want those changes to survive
regeneration.

## C++ and Rust

| Task | File |
| --- | --- |
| C++ gain function | `editor/examples/simple/signal.cpp` |
| C++ button actions and state | `editor/examples/simple/events.cpp`, `editor/examples/simple/services.hpp` |
| Rust filter mathematics and state | `editor/examples/rust-dsp/dsp.rs`, `process_samples` |
| Rust DSP C interface | `editor/examples/rust-dsp/dsp.h` |
| Rust DSP stream integration | `editor/examples/rust-dsp/flow_adapter.cpp` |
| Advanced MIMO block implementation | `editor/examples/demo/blocks.cpp` |
| Advanced MIMO factory declarations | `editor/examples/demo/blocks.hpp` |

The independent mixed-language example is under
`tutorial-video/examples/language-integration/`:

| Task | File |
| --- | --- |
| Edit C processing | `processing.c`, declared by `processing.h` |
| Edit C++ formatting | `display.cpp`, declared by `display.hpp` |
| Edit Rust processing | `rust/gain.rs`, `rust/smoother.rs` |
| Declare Rust modules and C ABI exports | `rust/lib.rs` |
| Declare matching calls for C/C++ | `rust/ffi.h` |
| Call these functions from behavior | `app.cpp`, `on_run` |
| Compile source files, track Rust modules and link the archive | `CMakeLists.txt` |

A C/C++ header declares a callable interface; add its implementation source to
the correct CMake target. For an additional Rust module, add the file, its `mod`
declaration, and its build dependency. Expose only the interface the caller needs
and keep ownership explicit at the C ABI boundary. Merely opening a file in the
editor does not add it to compilation.

## Main application and supporting systems

The main Entry list application is separate from the editor's teaching examples.

| Responsibility | Path |
| --- | --- |
| Core record behavior | `src/store.cpp`, `include/foundation/store.hpp` |
| Shared GUI actions | `gui/shared/application.cpp` |
| Shared handwritten widget layout | `gui/shared/view_definition.hpp` |
| Default private Rust validator | `rust/text_validation/src/lib.rs` |
| Directory and responsibility map | `docs/architecture.md` |
| Documentation topic index | `docs/README.md` |
| Forms, Files, Events and Flows | `editor/README.md`, `COMPILE-editor` |
| Build and SDK choices | `docs/building.md`, `docs/sdk.md`, `COMPILE` |
| Observed checks and qualification | `docs/validation.md` |
| Latest release package publication | `docs/distribution-release.md` |
| User installation and updates | `docs/installed.md` |

The Forms editor edits its design JSON; it does not import arbitrary handwritten
widget definitions. Platform adapters, retained SDKs, build scripts and CI remain
available when a task needs them. Everyday algorithm changes usually have a much
smaller working set.

## Graphical documentation and PDFs

Open `documentation-tool/published/index.html` in a local browser. The retained
bundle works without a web server, AI service or documentation rebuild. Keep the
whole `published/` directory together.

1. Choose **Add a widget & click handler**, then **1. Declare the widget**.
   Inspect the explanation, exact source location, example and **Parameter
   guide** section.
2. Choose **Add a source file to the compiler** for the ownership and target
   source-list map. **Core .cpp** leads to the core target's source registration.
3. **Compiler & toolchain → foundation_core** opens the target reference.
   **Read target in PDF** leads to its corresponding printable page.

| PDF under `documentation-tool/published/pdf/` | Use it for |
| --- | --- |
| `00-edit-paths.pdf` | Widget and source-file change recipes |
| `01-code-walkthroughs.pdf` | Functions, ownership and full source |
| `02-compiler-reference.pdf` | Targets, source lists and toolchain declarations |
| `03-execution-flows.pdf` | Build, startup and event execution |
| `04-code-flowcharts.pdf` | Source lines inside nested diagrams |
| `AI-AUTHORED__GUI-MENTAL-MODEL.pdf` | Separately labeled conceptual explanation |

The included documentation is an October 4 snapshot of the main application;
it predates the editor examples. Check the capture date and current source when
making changes. Links between PDFs depend on viewer support. Use
`documentation-tool/README.md` for the reading and explicit refresh procedures.

Local documentation, the example source, the optional editor and prepared
toolchains remain useful for manual development when frontier AI providers are
unavailable.
