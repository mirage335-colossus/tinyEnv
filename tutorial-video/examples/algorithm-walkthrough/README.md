# One file, one function, one visible result

The tutorial opens `editor/examples/simple-c/signal.c`, then highlights
`simple_c_apply_gain` and its return statement at line 21. This is ordinary C17
algorithm code. The form, event bindings, GUI adapters, compiler and CI files
can stay out of the way while changing this function.

The repeatable demonstration copies `signal.c` and `signal.h` from the repository
into `tutorial-video/.work/examples/algorithm/before/` and `after/`. Only the
`after/` copy receives the exact one-line change retained in `add_offset.patch`:

```c
float simple_c_apply_gain(float sample, float gain) {
    return sample * gain + 1.0f;
}
```

With input samples `[1, 2, 3, 4]` and gain `2`, the original code produces
`[2, 4, 6, 8]`. The changed copy produces `[3, 5, 7, 9]`. Both results come from
compiling and running the real C source with this directory's `driver.c`.

From the repository root:

```sh
python3 tutorial-video/examples/check_examples.py --only algorithm
```

The check rejects an unexpected source version or output, exercises the sample
buffer's capacity and two extra gain cases, and records the actual commands,
compiler identity, source checksums and output in
`tutorial-video/.work/examples/algorithm/verification.json`. Repository source
checksums are compared before and after the run. It never edits the original
application example.

`driver.c`, `add_offset.patch` and the check script are retained production
resources. Compiled binaries, copied sources and JSON receipts are regenerated
under the ignored `.work/` directory.
