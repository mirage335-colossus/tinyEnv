# Actual exported Reset event check

The probe reads the fresh captured `.work/projects/simple-c` form,
generated event bindings, and Reset handler unchanged. It instantiates the
actual generated binding against `foundation::visual::Ui`, then dispatches
`button1` Activate using the display-free `gui::MemoryAdapter`.

The exact exported handler calls the actual C `simple_c_state_init` function and
updates `simple_c.output`. The probe verifies three registered handlers, handled
dispatch, the restored C gain, an empty sample count and buffer, and the expected
output text. All checks remain active without relying on assertions.

Expected output from actual native C17/C++20 compilation and dispatch:

```text
Exported GUI bindings: 3
button1 Activate: handled
C state: gain 2, count 0, samples cleared
Output: State reset. Choose a gain and run again.
Actual generated Reset event: PASS
```

After completing the capture stage, run from the repository root:

```sh
python3 tutorial-video/examples/language-integration/event-check/run_check.py
```

The defaults are `--project tutorial-video/.work/projects/simple-c`,
`--work-dir tutorial-video/.work/event-check`, and the existing `cc` and `c++`
compilers on `PATH` (or `CC`/`CXX`). Override the compiler paths with `--cc` and
`--cxx`. The captured project must already contain the saved Reset handler and
exported binding.

The repository retains its GUI inputs as `third_party/gui-inputs`. A small,
configure-only CMake project uses the repository's existing verified restoration
and patching helpers to prepare those headers under `.work/event-check/gui-build`.
It downloads nothing and needs CMake 3.24+, Ninja and Python 3.9+. Alternatively,
`--gui-include /absolute/path/to/prepared/include` selects existing patched headers.
`--gui-input-group` can select another retained input group. `--foundation` can
select the matching read-only repository root.

Objects, dependency files, prepared headers, the executable, `output.txt` and
`verification.json` are written only under the generated work directory. The
receipt records every exact configure/compiler/link/run command and its output,
compiler identities, binary hash, and captured-project, visual-source and GUI
header hashes before and after the check. An unexpected transcript, failed
check or changing input fails the command. No application build or source edit
is performed.

This verifies the generated event's behavior through the real UI model. Native
drawing, native input translation and other platforms require their own checks.
