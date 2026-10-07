# Simple C starter

This example keeps processing and event decisions in ordinary C17 files. The
form has a gain dropdown, Run samples, Clear, and an output text area. Its flow
is **Source → Gain → Collector**, processing four floats. Gain 2 produces
`2 4 6 8`; gain 0.5 produces `0.5 1 1.5 2`.

From the repository root, build and run the application:

```sh
cmake -S editor/examples/simple-c -B build/editor-simple-c-check -G Ninja
cmake --build build/editor-simple-c-check --parallel 2
build/editor-simple-c-check/foundation-editor-simple-c
```

CMake compiles `signal.c` and `events.c` separately with the C compiler using
C17. The C++ boundary and the existing shared GUI/flow support use C++20. There
is no editor, GUI toolkit, Rust compiler, network or extra SDK requirement.
The retained generated headers are regular build inputs; a build never runs
the editor or reads the project JSON.

Choose **Examples → Simple C**, or open
`editor/examples/simple-c/project.json` in the editor. In **Flows**, double-click
Source, Gain or Collector to open its short function in `signal.c`. Start with
`simple_c_apply_gain`: two floats in, one float out, with no runtime API.
`signal.h` contains the plain C state and declarations; the collector checks
the fixed four-sample buffer before storing a sample.

In **Forms**, double-click Run samples or Clear to open `events.c`.
`simple_c_on_run` reads the chosen gain, disables the Run button, calls the flow,
updates the output through a helper, and enables Run again even after processing
fails. The small callback facade in `events.h` lets C functions cause GUI effects
without seeing the C++ GUI types. Callbacks are synchronous, copy supplied text,
and return status codes; the C++ bridge catches exceptions before they reach C.

`event_adapter.cpp` translates that facade to the shared `visual::Ui` abstraction.
`flow_adapter.cpp` translates bounded streams to the C processing functions.
The design keeps C source navigation separate from its C++ event bindings and
block factories. The GUI layout lives once in `project.json` and its generated
form; a native host can present the same form and handlers through its adapter.

The included display-free application checks the generated form, typed event
dispatch, dropdown selection, output text, repeated runs, fixed-buffer limits,
and recovery after a processing failure. It prints the checked sample values.
Change its expected results in `main.cpp` when changing the algorithm. This
finite four-sample flow runs cooperatively; slower or continuing processing
should use the graph worker and `UiPost` mailbox shown in `../demo`.

Opening an example executes no commands and opens the actual editable directory.
Save/Generate after changing the form or flow, then use the ordinary build.
Source edits need only rebuilding; handwritten C files remain separate from
generated output. The Build and Run recipes use the configured directory above.
The C++ starter (`../simple`) and Rust DSP example (`../rust-dsp`) show the same
ordinary-source workflow in other languages.
