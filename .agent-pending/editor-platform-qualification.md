# Optional editor platform qualification

The first editor implementation starts from application commit
`ebd5958886c6e26123738f78cdb0c1a76b844d7b` and the editor architecture plan.
The initial implementation was verified before commit. Its development manifest in
`build/editor-build-dev/source-snapshot.json` records changed-file aggregate SHA-256
`1b203813f52ff8890e9b212a5361f808d2712deaa1da8656689f168598a857c7`
(this pending record is excluded). COMPILE-editor was subsequently updated with
the working retained SDK path. Future qualification should record the Git commit
it tests. This record concerns the optional
editor, not application release gates. It schedules no CI, binary certification,
SDK extension or editor distribution work.

Completed focused development checks on Linux x86_64, 2026-10-05:

- `./build.sh editor test dev --headless --build-dir build/editor-app-checks
  --build-jobs 4 --test-jobs 2`: all ten local editor suites passed. These cover
  model/generation, publication/recovery, ordinary source buffers and conflicts,
  owned processes, typed MIMO execution, GUI helpers, canvas and the actual editor
  application. The application fixture covers event selection, unsaved-close
  cancellation, optional ports/options, distinct handler names, legacy event
  aliases and Build/Run cwd.
- Native SDK builds of FLTK, Rev and framebuffer succeeded through
  `./build.sh editor build dev --backend BACKEND --sdk SDK --build-dir
  build/editor-build-dev/BACKEND-sdk --build-jobs 4`. Each resulting native host
  passed `--smoke-test` under a private joined Xvfb display with
  `LIBGL_ALWAYS_SOFTWARE=1` and `SDL_VIDEODRIVER=x11`. This exercises native
  presentation, add/undo/redo and inert preview, not full manual desktop use.
- Strict existing shared-boundary tests passed 39/39, SDK-path tests 13/13 and
  CI-change selection tests 28/28. The ordinary application configured with its
  existing targets/install rules and no editor target; its full build/test/CI
  matrix was not launched. Documentation and whitespace checks passed.
- Independent C++ adoption and optional Rust 1.63 C ABI adoption builds/runs
  passed: 2-input/4-output counts `[4, 4, 8, 2]`, ordinary injected functions,
  callbacks and GUI choice/text/button updates. The self-host design's ten
  toolbar handlers and helper flow passed. Retained self/demo generation is
  current. Framebuffer form/code/preview/flow captures were inspected.

The existing SDK at `build/agents/rust-package-qualification/sdk` has manifest
SHA-256 `aae50f14b643951566be2fe20944a6654287d74cb6639bda7529d24e589954d2`.
No Rust extension was selected for the editor, and no SDK package was added.
Local evidence is in `build/editor-build-dev/` (build logs, shared-suite receipts,
`native-smoke-final-alias.json` with exact argv, executable hashes and environment),
`build/editor-app-checks/Testing/Temporary/LastTest.log` and its `captures/`, and
`build/editor-examples-dev/`. Earlier failed development runs remain separate;
they are not passing evidence. Build outputs are local ignored files, not a new
artifact retention or publication requirement.

Focused usability follow-up from commit `4bff975f0b3cec536f8f7defd438adbdc1e52b41`,
2026-10-05: all ten local editor suites passed after moving path entry into the
editor window and adding named form/flow creation, Rename and Example access.
The rebuilt FLTK SDK editor is `build/editor-fltk-sdk/foundation-editor-fltk`.
A native FLTK probe verified clipboard paste/replacement, stable focus through
repeated ticks, invalid-path correction and cancellation. Under an isolated KWin
window manager on Xvfb, minimizing and restoring the open path-entry window
preserved the pasted text and subsequent paste behavior. Evidence and exact
source/library identities are in `build/editor-usability-probe/compile-receipt.json`,
`result.json` and `wm-result.json`; UI captures are in
`build/editor-app-checks/usability-captures/`. This focused check adds no SDK,
application CI or release dependency and does not expand the platform claims below.

Focused flow-editing follow-up from commit
`974ef0e0d70fef9d08cd45b7b86ecc4d00e0d092`, 2026-10-05:

- All ten local editor suites passed through the supported headless command in
  `build/editor-gesture-checks`. Coverage includes physical pointer phases,
  drag/undo/cancel, port-name click and drag wiring, rejected-link correction,
  preview transitions, Fit, examples and independent source/factory navigation.
  The application fixture passed again after the final ASCII example caption.
- Rebuilt `build/editor-fltk-sdk/foundation-editor-fltk` with the same native
  C++ SDK. An actual XTest/FLTK probe against its final libraries passed block
  dragging across repaints, Escape rollback, both wiring gestures, native
  Save/Delete/Open/Cancel buttons, clipboard paste and stable focus. Its receipt
  matches the final source/library hashes. Private display/process groups joined.
- Focused native FLTK and Rev pointer-contract probes and shared framebuffer
  pointer checks passed. The retained source-group suite passed 25/25. The shared
  GUI boundary suite passed 38 cases; its remaining fixture was updated for the
  new repatch call and passed on a focused rerun. No editor CI gate was added.
- The simpler C++ starter and Rust 1.63 FIR/decimation example built and ran.
  Rust checks cover state across uneven chunks, capacity/backpressure, counts,
  restart and actual recompilation after a source change. Retained generation
  is current for both new examples, the existing MIMO demo and the editor itself.
  Updated UI captures were inspected, including example spacing and connection
  instructions. Documentation and whitespace checks passed.

Final source identities and the caption follow-up are recorded in
`build/editor-usability-followup/source-snapshot.json`; suite and native evidence
are in `build/editor-gesture-checks/interaction-validation.json`,
`build/editor-gesture-probe/foundation-editor-flow-probe-result.json`,
`build/editor-rev-pointer-probe/receipt.json`,
`build/editor-simple-example-check/check-receipt.json` and
`build/editor-rust-dsp-check/receipt.json`. The refreshed GUI input manifest is
`a6c7f359a4679961d0e8211dcafa6f4743094de5105ca2b5ed0de2d86feb2fbb`;
its upstream revision is unchanged. These are focused development checks, with
no added SDK package, editor distribution step or application release dependency.

Focused C starter and usability follow-up from commit
`0e1e8085d68ec54ae51772d6c34525089ca8c832`, 2026-10-05:

- All ten local editor suites passed in `build/editor-c-qol-checks`. Focused
  regressions cover Enter actions and validation preservation, contextual Details,
  first-use hints, F3 source saving, and C source navigation through C++ bindings.
  The application capture run also passed; changed views were inspected.
- The new C starter compiled its behavior as C17 and its GUI/stream boundaries
  as C++20. Its independent build, project Build/Run recipes, generated form/event
  dispatch, numeric output, bounded buffer and failure recovery checks passed.
- Rebuilt `build/editor-fltk-sdk/foundation-editor-fltk` through the supported
  editor wrapper with the same native SDK recorded above. No SDK package or
  editor/application CI, packaging or release dependency was added.
- A native before/after probe reproduced and fixed shared FLTK prompt focus loss
  in the ordinary application's Change heading dialog. The supported-wrapper
  `foundation.gui.fltk-host` test passed 1/1, including clipboard paste, repeated
  synchronization, deferred focus and accept/cancel restoration, plus its existing
  pointer/control checks. Native modal policy is unchanged. Probe/display process
  groups joined. An earlier build whose source identity changed during parallel
  editing reached zero test assertions; only the stable-source rerun is passing
  evidence. The shared GUI source-boundary guard passed.

Exact source and output identities are recorded in
`build/editor-c-qol-checks/interaction-validation.json`,
`build/editor-simple-c-check/check-receipt.json` and
`build/shared-prompt-focus-check/qualification-receipt.json`.
The refreshed GUI input manifest is
`2dcef6393d9ad9a4c41c8a819f3e836ace78af4c19eb4be7496b9ca41fac78cd`;
its upstream revision and the SDK are unchanged. These focused checks do not
expand the platform or disconnected-operation claims below.

The outstanding broader scope is qualification of actual editor use on selected
native targets/backends: Windows source file/process adapters, native ARM64,
and disconnected editor builds/runtime using an already retained matching native
Linux SDK with the FLTK, Rev or SDL dependency closure. The existing `--sdk`
route is Linux-only. Rev retains its supported module compiler/scanner and graphics
prerequisites; other hosts/platforms are not established by Linux/Xvfb checks.

When explicitly requested, start with the relevant commands in
[editor build/use](../editor/README.md#build-and-run),
[local checks](../editor/README.md#self-hosting-and-local-checks) and
[prepared native dependencies](../docs/gui-boundary.md#prepared-platform-dependencies).
Exercise open/new, drag/resize, Details, MIMO wiring, double-click code editing,
save conflicts, generation/recovery and owned Build/Run/Stop on the selected host.
For a disconnected claim, use fresh build/user/temp state with networking blocked
and record selected SDK identities and dependencies. A successful compiler build
or in-memory smoke check alone does not qualify the complete interactive workflow.

Next manual action: request the specific broader editor target/backend or offline
qualification needed. Generic editor implementation does not authorize the broad
matrix under the [manual-qualification policy](../AGENTS.md#development-checks-and-manual-qualification).
Editor testing must not delay application testing, builds or delivery.
