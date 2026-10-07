# Optional graphical editor

The C++20 editor combines a small form designer, event-source editor and typed
stream-flow designer. Complex behavior stays in ordinary C, C++, headers, Rust
wrappers and normal compiler tools. Start with [COMPILE-editor](../COMPILE-editor)
and the [simple C example](examples/simple-c/README.md), which uses C++ at the
GUI and stream boundaries. The [simple C++ example](examples/simple/README.md) and
[Rust DSP example](examples/rust-dsp/README.md) provide language alternatives;
the [advanced MIMO example](examples/demo/README.md) demonstrates
more integration features. The editor also has its
[own editable design](self/README.md).

The editor uses the existing GUI abstraction for FLTK, Rev and the framebuffer
renderer presented through the existing SDL2 host. It has its own CMake project,
build trees and explicit local tests. The application's ordinary build, SDK
construction and release graph do not compile or run the editor. No editor
installer, binary publication or additional SDK package is introduced.

## Build and run

Run from the repository root. FLTK works with Debian 12's C++20 compiler,
CMake 3.24+, Ninja, Python 3.9+ and FLTK development packages. No Rust compiler,
Cargo, language server or network access is needed to build the editor. Retained
GUI inputs are checked and restored by the existing input machinery.

```sh
./build.sh editor build dev --backend fltk --build-dir build/editor-fltk
./build/editor-fltk/foundation-editor-fltk
```

For the framebuffer window, use the existing SDL2 development package:

```sh
./build.sh editor build dev --backend framebuffer --build-dir build/editor-framebuffer
./build/editor-framebuffer/foundation-editor-framebuffer
```

Rev uses `--backend rev` and `foundation-editor-rev`. It inherits the existing
[prepared Rev toolchain requirements](../docs/gui-boundary.md#prepared-platform-dependencies):
CMake 3.28+ and a supported module compiler/scanner such as Clang 19+ or GCC 15+,
plus the existing platform graphics dependencies. Bookworm's base compiler/CMake
alone do not build Rev. Keep the selected target sysroot and runtime baseline.

An existing verified **native Linux C++ SDK** can supply its already retained
toolchain and toolkit closure; a Rust extension is unnecessary:

```sh
./build.sh editor build dev --backend fltk --sdk /absolute/retained/sdk \
  --build-dir build/editor-fltk-sdk
./build/editor-fltk-sdk/foundation-editor-fltk
```

The `--sdk` route currently accepts native Linux SDKs. Windows source adapters
exist, but editor-specific Windows execution and broader platform qualification
remain [pending](../.agent-pending/editor-platform-qualification.md).
An SDK must already contain the selected backend's matching dependencies;
the editor does not enlarge it or fetch missing inputs.

`./build.sh editor --help` lists `build`/`test`, `dev`/`release`/`asan`, backend,
SDK and concurrency options. `--headless` builds the authoring tool and selected
local tests without a native toolkit host. Each operation/backend/toolchain has
its own stamped tree: the default is `build/editor-fltk-dev`, with `-sdk`,
`-headless` and `-tests` suffixes for those selections. Use a fresh tree when
changing inputs or switching between `build` and `test`; application build trees
cannot be reused for the editor.

## Normal editing

1. Choose **Examples**, then **Simple C**, **Simple C++**, **Rust DSP**, or **Advanced MIMO**.
   Choose **New** for a project directory or
   **Open** for a project JSON file.
   New/Open and Save-as use a path field inside the editor window: type or paste
   a path and press Enter to accept or Escape to cancel. The window remains
   minimizable while entering a path. A project directory selects
   `design/project.json`. The command line accepts
   `--project PATH` and an optional `--root PATH` for a wider existing project.
   Examples opens the chosen editable project under `editor/examples/`; Save changes
   its design/generated files, and saving source changes its ordinary source files.
   Opening it executes no project code and writes no files. Run the editor from
   the repository root if it cannot locate the examples.
2. Choose **Forms**, a form, a widget kind and **Add widget**. Select an element,
   drag it to move, resize with its handle, or change its label/position/size and
   **Apply**, or press Enter in a property field. **New form** asks for a name;
   **Rename** beside the document picker
   changes the selected form's displayed name while keeping its stable ID.
   **Duplicate**, **Delete**, **Undo** and **Redo** provide the small set of layout
   operations. Wheel scroll pans; Ctrl+wheel zooms.
3. Choose an **Event** and double-click the widget, or use **Edit code**. The
   modal window edits the complete ordinary source file. A missing binding gets
   a new header and a small typed handler skeleton on this explicit action.
   Existing functions can be assigned through **Widget / event details** using the source path,
   declaration header and C++ symbol. Source files remain independently editable.
4. **Widget / event details** also sets initial text, enabled state, parent group, text
   multiline/read-only behavior and dropdown options. Option rows use
   `ID | label | value`; IDs give stable selections. Other schema fields can be
   edited directly in the JSON document.
5. Choose **Flows**, a flow and **Add block**. **New flow** asks for a name;
   **Rename** changes the selected flow's displayed name and preserves its ID.
   Drag a block by its body or header. Flows fit the canvas when opened;
   **Fit** restores the whole view after moving blocks or zooming.
   **Ports and source...** sets its C++ factory, source/header paths, **Source symbol (optional)**,
   input/output lists and parameters. The source search text can name the useful
   C, C++ or Rust processing function separately from its factory. Port rows use
   `name : C++ type`, one per line; parameter rows use `name = value`.
   Click an output port name or socket, then an input port, or drag between them
   to connect. The selected origin stays highlighted while wiring; choose a
   different destination after an invalid connection. Click the origin again,
   press Escape, or use **Cancel link** to cancel. Select a wire to delete it.
   Double-click a block to edit its ordinary processing source.
6. **Save** retains the design and deterministically generated C++. Incomplete
   designs can be saved as drafts; diagnostics explain generation/build errors.
   **Preview** presents the selected form without executing application handlers;
   switching documents returns to editing.
   **Build** and **Run** use explicit project recipes; Run builds first and only
   starts the application after a successful build. **Stop** cancels owned work.

**Files** lists ordinary source/build/design files. Selecting a file fills its
path. Double-click it, choose **Open file**, or press Enter in the path field.
The list is bounded to 1,500
matches from 10,000 visited entries and skips hidden/dependency/build directories;
Open file still accepts an explicit valid project-relative path. The code window supplies Save,
Undo/Redo, Find, Reload, External, Close and Discard. Enter in Find searches;
F3 saves the source buffer. Escape closes a clean buffer; save or discard edits
before closing. Outside the source window, F3 saves the design, F2 opens selected
widget/block code, and F5 builds and runs the project. Reload requires a clean
buffer; a save conflict preserves unsaved text. **External** uses an `edit`
recipe or an `EDITOR` executable path, then Reload imports the external change.
There is no C/C++/Rust parser or special source-region ownership convention.

The source window accepts UTF-8 files without zero bytes up to 8 MiB and preserves
untouched bytes, including line endings and BOM. Project paths stay within the selected root;
symlinks, special files and path escapes are rejected. The framebuffer's retained
font has limited glyph coverage, so some Unicode text displays replacement
glyphs even though source bytes are preserved. Use External for such scripts.

## Source and application integration

The JSON owns layout, event references, flow composition and command recipes.
The default `generated/visual/` directory owns `forms.hpp`, `events.hpp`,
`flows.hpp`, its ownership guard and semantic `design.json` revision marker.
Generation never rewrites handwritten handlers or processing implementations.
The generator recognizes ordinary type names and simple templates; use a
header-defined alias for more elaborate C++ types.

Each generated form has one application-side layout using the existing
`gui::Snapshot` contract. An adopting application can present it through any
supported GUI adapter, including terminal and browser adapters; the editor's
own hosts remain FLTK, Rev and SDL/framebuffer. Layout and event decisions stay
above that boundary. Adding a widget kind or input capability requires a shared
contract and adapter support, rather than backend-specific application layouts.

The Forms view edits design JSON; it does not import arbitrary handwritten C++
layouts. The main software-foundation example currently defines its unified
widgets in [`gui/shared/view_definition.hpp`](../gui/shared/view_definition.hpp)
and behavior in [`gui/shared/application.cpp`](../gui/shared/application.cpp).
To edit those files here, open the editor's self project with `--root .` as
shown below, choose **Files**, and open either repository-relative path. Rebuild
the application through its usual commands; every selected backend consumes
the changed shared definition. See [GUI ownership](../docs/gui-boundary.md)
for the existing application boundary and its backend qualification limits.

Generated forms construct `gui::Snapshot` values; generated event registration
calls typed ordinary handlers with `(services, ui, input)`. An explicit C++
services object can contain callbacks, device handles, function objects, state
and Rust C ABI wrappers. Helpers called at any depth can use the passed
`foundation::visual::Ui` to replace dropdown options, update text, enable/disable
buttons or change other supported widget state. See the
[GUI support contract](../visual/ui/README.md) for threading, batching, reliable
worker messages and generation invalidation. UI model access belongs to the GUI
thread; workers post owned commands through `UiPost` and check delivery results.

Generated flows construct graph descriptors and invoke each ordinary factory as
`factory(services, parameters)` or `factory(services)`. Factories return owned
`Block` instances and may call any linked functions or keep suitable owned or
borrowed objects. The composition root owns service lifetimes and joins the graph
before destroying borrowed objects. The editor does not load project code when
opening a design or previewing its form.

Applications adopt only the optional `visual/ui` and/or `visual/flow` runtime
source they need, together with retained generated headers and the existing GUI
boundary. They build with their normal compiler and CMake files, without linking
the editor model, generator, file services or process runner. The
[simple C example](examples/simple-c/README.md) keeps events and processing in
ordinary C17, with small C++ adapters for the GUI and stream runtime. The
[simple C++ example](examples/simple/README.md) keeps event and sample-processing
functions short, with flow plumbing in a separate source file. The
[Rust DSP example](examples/rust-dsp/README.md) implements a stateful FIR filter
and decimation in ordinary Rust behind a small C ABI adapter; it builds with
`rustc` and no external crates. The [advanced demo](examples/demo/README.md)
shows unequal-rate MIMO, injected callbacks and worker-to-GUI messages.
Rust compilation and linking remain explicit project actions; Rust is not an
editor prerequisite.

## Multiple streams and execution

A block has named input and output vectors, including zero-port sources/sinks
and arbitrary MIMO configurations within explicit resource limits. Generated
`make_flow(id, services, GraphOptions)` accepts runtime resource bounds. Each port has
a C++ value type. Each work call reports its consumed/produced counts separately,
so ports may have unequal rates and independent closure. Queue capacities bound
backpressure and memory; connected types must match. One edge owns one producer
and one consumer. Use an ordinary split/broadcast or combining block for fan-out
or fan-in, with the ownership/copy policy in its source.

The [runtime interface](../visual/flow/flow.hpp) provides borrowed typed spans
for trivial values and construction/ownership transfer for object or move-only
values. Spans expire when `work` returns. Blocks must return cooperatively and
report waits or completion; they can wait for input/output, external wake or a
timer. The default executor is an owned worker; applications can use cooperative
stepping instead. Stop requests are joined, and block errors fail the graph.
Feedback uses explicitly initialized state/delay factories with `breaks_cycle`;
a numeric token count cannot initialize arbitrary typed values.

The first interface intentionally exposes fewer controls than the JSON format.
Edit JSON for optional ports (`required: false`), edge capacities, feedback state
declarations, visibility/checked fields, form dimensions and recipes. The bounded
runtime and [design schema contract](model/README.md) describe the applicable limits.
More complicated executors or algorithms can use ordinary project-owned C++.

## Build recipes, freshness and recovery

Recipes are argument arrays, never shell text. Their working directory is
project-relative. **Build** uses the recipe ID `build`; **Run** uses `build`, then
`run`. An optional `edit` recipe substitutes an argument exactly equal to
`{file}` with the absolute source path. For example:

```json
{"id":"build","label":"Build","argv":["cmake","--build","build","--parallel","2"],"working_directory":"."}
```

Configure that application's build tree through its ordinary tools first.
Opening a project starts no commands. Explicit Build, Run and External actions
launch one owned process tree with bounded diagnostic output. A failed build
never launches an old application binary.

The display-free `foundation-editor-tool` supports explicit authoring and review:

```sh
mkdir -p build/new-visual-project
./build/editor-fltk/foundation-editor-tool new --project build/new-visual-project
./build/editor-fltk/foundation-editor-tool validate --project editor/examples/demo/project.json
./build/editor-fltk/foundation-editor-tool generate --project editor/examples/demo/project.json
./build/editor-fltk/foundation-editor-tool check-generated --project editor/examples/demo/project.json
```

`new` never replaces an existing design. `--output` and `--namespace` override
generation settings for new/generate/check-generated; omitted options use the
saved settings. `--root` defines the file boundary. Source edits need only normal
recompilation. Composition changes need explicit Save/Generate; generated C++ is
retained so application builds do not invoke the editor. `check-generated` exits
nonzero for missing/different output and can be used as a project-owned check.

Checked saves reject externally changed files. Generation publishes an owned
output batch with its revision marker last. Keep other project writers quiescent
during publication; the [native service contract](platform/README.md) describes
conflict checks and durability limits. An interrupted batch blocks further
authoring until explicit recovery:

```sh
./build/editor-fltk/foundation-editor-tool recover --project editor/examples/demo/project.json
```

Recovery completes the journaled revision while preserving conflicting foreign
changes. Resolve reported conflicts before retrying; generated publication never
enrolls handwritten files.

## Self-hosting and local checks

The [self project](self/README.md) supplies the editor's retained toolbar, event
bindings and an example inspection flow. Open it with the repository as root:

```sh
./build/editor-fltk/foundation-editor-fltk --project editor/self/project.json --root .
```

Its default Build/Run recipes use `build/editor-fltk`. Adjust the ordinary recipe
array for another build tree/backend. Edit its design or `handlers.hpp`, explicitly
save/generate and rebuild to develop the editor using itself. Retained output
bootstraps the first editor build without a pre-existing executable.

Focused local checks are explicit and use a separate tree:

```sh
./build.sh editor test dev --backend fltk --headless --build-dir build/editor-tests
```

Native hosts accept `--smoke-test` for bounded in-memory presentation/add/undo/
redo/preview checks. It writes no project. Full desktop interaction and native
offline/platform coverage are separate from these checks; see
[pending editor qualification](../.agent-pending/editor-platform-qualification.md).
Editor-only changes do not gate application CI. Changes to shared GUI/build
machinery or optional application runtime source follow their normal applicable
application checks. The [architecture plan](PLAN.md) records the design decisions;
this page documents the first implementation's actual interface.
