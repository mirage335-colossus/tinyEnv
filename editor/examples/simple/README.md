# Simple C++ starter

Start with this example when learning the editor. Its form has a gain dropdown,
Run samples, Clear, and an output text area. Its flow is **Source → Gain →
Collector**, processing four floats. Gain 2 produces `2 4 6 8`; gain 0.5
produces `0.5 1 1.5 2`.

From the repository root, build and run the ordinary application:

```sh
cmake -S editor/examples/simple -B build/editor-simple-example-check -G Ninja
cmake --build build/editor-simple-example-check --parallel 2
build/editor-simple-example-check/foundation-editor-simple
```

This tiny application uses a display-free reference GUI adapter. It exercises
the generated form, event dispatch, dropdown state, button enable/disable and
output text, then prints the checked sample results. It needs no editor binary,
native toolkit, Rust compiler, downloaded packages or running display server.
The same generated form and event handlers can be composed with a native host.

Choose **Examples → Simple C++** in the editor, open
`editor/examples/simple/project.json`, or use the command line:

```sh
./build/editor-fltk-sdk/foundation-editor-fltk --project editor/examples/simple/project.json
```

In **Forms**, double-click Run samples or Clear to open their ordinary functions
in `events.cpp`. `on_run` reads the dropdown, locks the Run button during work,
calls a helper, updates the output, and unlocks the button. Helpers can use the
same `Ui` object to change other widgets.

In **Flows**, drag a block by its body. Connect its right output port to a left
input port of the next block. Double-click a block to open its short processing
function in `signal.cpp`. Start by changing `apply_gain`; it takes two floats and
returns one float, with no special editor or runtime API. `source_sample` and
`collect_sample` are ordinary functions too. `main.cpp` checks the expected sample
values and output text; update those expectations when changing the algorithm.

`flow_adapter.cpp` contains the bounded-stream plumbing and named factories.
The design stores a source file and navigation symbol separately from the C++
factory, so the editor can open the useful processing function directly.
`services.hpp` holds ordinary application state; `main.cpp` owns it and the graph.
The finite example runs cooperatively in an event helper. A continuing or slow
process should use the graph's worker and the `UiPost` mailbox, as shown by the
advanced `../demo` example, to keep the GUI responsive.

Opening this project executes no source code. It opens the actual editable
example directory: Save changes its design/generated files, and source Save
changes its C++ files. Save/Generate after changing the form or flow; ordinary
source changes need only the normal build. Retained `generated/visual/` headers
let the application build without the editor; regeneration leaves handwritten
source files alone. Build and Run recipes assume the directory above has already
been configured. The advanced demo remains available for unequal-rate MIMO,
injected callbacks and worker-to-GUI messages; the Rust DSP example offers a
separate processing-language alternative.
