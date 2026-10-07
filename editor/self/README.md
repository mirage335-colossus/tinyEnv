# The editor's own design

From the repository root, build and open this project explicitly:

```sh
./build.sh editor build dev --backend fltk --build-dir build/editor-fltk
build/editor-fltk/foundation-editor-fltk --project editor/self/project.json --root .
```

`project.json` is the ordinary Forms/Flows design used by the editor itself.
Its generated toolbar controls and event bindings are compiled into the editor;
`handlers.hpp` contains the ordinary C++ event functions. Double-click a toolbar
control in this design to edit that header, or edit it in an external editor.
The explicit repository root permits these project-relative source paths without
permitting paths above the repository.

Change a toolbar label or layout, Save/Generate, then Build and Run to observe
the changed editor. The retained `generated/visual` files make the initial
editor build possible without an existing editor binary. This project has no
automatic application-build, release, SDK or CI hook.

The `self.inspect` flow is a small optional example of calling ordinary code to
count source bytes through a bounded stream. It is an authoring input, independent
of the editor UI's execution; its explicit block functions are in `flow.hpp`.
