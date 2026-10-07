# Windows host graphics qualification

The Rev host requires real OpenGL 4.4, or 4.3 with `GL_ARB_buffer_storage`, plus
modern WGL context and pixel-format entry points. A hosted Windows runner image
does not promise those graphics capabilities. Qualification must measure the
driver actually loaded by the executable. A successful compilation alone does
not satisfy that requirement.

The [locked host input](../third_party/host-graphics/mesa-windows.json) supplies
an explicit AMD64 llvmpipe environment for Windows tests. It is an external host
prerequisite, separate from the target SDK, application dependencies and released
payload. The helper neither changes system drivers nor installs supplier scripts.
This profile does not qualify ARM64 Windows or another graphics implementation.

## Acquisition and retention

An authorized maintenance operation may acquire the exact supplier archive:

```sh
python tools/windows_graphics.py fetch /owned/cache/mesa3d-26.2.3-release-msvc.7z --network
python tools/windows_graphics.py verify /owned/cache/mesa3d-26.2.3-release-msvc.7z
```

The cache parent must already exist and be owned by the calling operation.
Ordinary consumers supply that retained archive; configuration and staging never
fetch it. An explicit operator-provided HTTPS retention location can be consumed
with `fetch_retained(url, archive_path)`. Its content must match the same pinned
size and digest. Redirects must remain HTTPS and cannot include credentials.
Operator access queries are omitted from receipts and diagnostics. Existing cache
entries are verified and reused; mismatches are preserved and rejected. A missing
archive without explicit acquisition is an error, with no fallback download.

The supplier archive is 71,063,681 bytes. Only `x64/opengl32.dll` and
`x64/libgallium_wgl.dll` are selected. Exact identities and inspected PE imports
are recorded in the lock. Their selected import closure requires Windows system
DLLs and the companion renderer, with no separate LLVM or C runtime DLL import.
That inspection establishes the intended inputs; the native probe still has to
establish usable WGL and rendering behavior on the actual runner.

The binary archive contains no license texts. The supplier's build-script MIT
license is not a complete license inventory for Mesa, LLVM and linked components.
The [provenance notes](../third_party/host-graphics/README.md) identify the retained
source and notice work required before redistributing an input group. The current
lock explicitly sets redistribution approval to false. These helpers do not
upload the archive, extracted DLLs or a substitute public mirror.

## Bounded test environment

CI and release qualification share `qualified_stage` in
[windows_graphics.py](../tools/windows_graphics.py):

```python
with windows_graphics.qualified_stage(
    retained_archive, [gui_executable_directory],
    probe_directory=owned_fresh_probe_directory,
    compile_log=owned_compile_log,
    environment=selected_msvc_environment,
    protected_roots=[sdk_root, restored_dependency_root, install_root],
) as graphics:
    # Run the existing GUI tests with graphics.environment through the owned
    # process-tree supervisor, finishing all descendants before context exit.
    run_and_finish_gui_tests(environment=graphics.environment)
receipt = graphics.receipt
```

This is an API illustration; the workflow caller supplies its already selected
MSVC environment, owned output directories and real supervised test function.
The helper compiles the [native probe](../tools/windows_gl_probe.cpp), checks its
source identity, selectively extracts the locked DLLs with installed `7z`, and
stages them beside both the probe and test executables. The fresh probe executable,
object and bounded compiler log are retained as evidence. Compiler selection
comes from the supplied child environment. No compiler installation is implicit.

MSVC may leave its optional `vctip.exe` telemetry child running after a successful
compile. [Microsoft’s build tooling documents this non-output helper](https://github.com/microsoft/BuildXL/blob/main/Public/Sdk/Experimental/Msvc/VisualCpp/visualCpp.dsc).
The compiler path binds only the helper beside the selected compiler, including
its physical file identity and SHA-256 before launch. Every live pinned Job member
must match that exact helper before termination is accepted. The supervisor then
terminates and joins all members under one deadline and checks that no assignment
was missed. A different image, changed file, inaccessible identity, unexpected
child or uncertain join remains a failure. The compile receipt distinguishes no
surviving helper from a verified terminated-and-joined helper, with its identity
and observed PIDs.

This policy applies only to successful native probe compilation. Ordinary commands
retain strict descendant completion; a nonzero compiler result still fails. It
requires no registry changes, administrative setup, process breakaway, network
access or modification of the installed toolkit. A toolkit without that optional
helper follows ordinary strict completion. The [focused Windows diagnostic](testing.md#focused-host-diagnostics)
uses this same production path and can select `FOUNDATION_MSVC_STRICT_COMPLETION=1`
to reproduce strict completion behavior while investigating a host.

The probe must report actual loaded paths for both pinned DLLs, llvmpipe, both
required WGL entry points, and the required OpenGL capability. A nonzero exit,
missing field, wrong path, altered driver, timeout or excessive output fails.
`GALLIUM_DRIVER=llvmpipe` is set only in the child environment. GL version, shading
language version and extension overrides are prohibited; qualification cannot
manufacture a supported capability by changing a reported version.

The lower-level `stage(...)` context and `run_probe(...)` are available for an
already compiled probe. `stage` accepts existing directories only, rejects links,
reparse points, duplicate destinations, protected roots and existing driver names,
and publishes each complete verified file without replacing any file. Callers
must own those directories exclusively through cleanup; this is a cooperative
build operation, not confinement of a hostile concurrent filesystem writer.

`run_owned(argv, cwd, log_path, environment=..., timeout=1800,
max_bytes=16777216)` supplies the common bounded process-tree runner. It creates
the combined standard-output/error log exclusively and returns its digest on
success. Nonzero exit, time or output limits fail; a bounded log prefix remains
after confirmed child cleanup. Callers validating a smoke success marker must
check its complete line in that combined log, allowing unrelated driver messages.
Protected roots may be declared before they exist; existing ancestors must still
be ordinary directories. No protected directory is created by this helper.

All test children must finish before leaving the context. Call
`graphics.mark_writers_uncertain()` if supervision cannot establish completion.
Process-tree supervision errors also retain staging automatically. The receipt
then reports `retained-uncertain`, and the caller must retain ownership for
inspection. Normal cleanup removes only the exact unchanged files placed by this
invocation. Changed, replaced or inaccessible files are preserved and cleanup
fails. Serialize the receipt **after** context exit so its final cleanup state is
included. Never continue packaging after uncertain or failed cleanup.
Failures also carry `error.graphics_receipt`, including failures before the
qualification context yields. Preserve extraction and probe output ownership
whenever its cleanup state is not `removed`; do not let an outer temporary-tree
cleanup erase evidence or files whose writers may still be active.
`retain_required(error)` also follows exception causes and contexts, so a failed
log publication cannot hide an earlier supervision error. Outer extraction-tree
cleanup must use this shared predicate before deleting owned temporary trees.

## Evidence and upgrade requirements

Keep the exact source and archive identities, compiler log digest, native probe
receipt, final staging cleanup state, real GUI test results and rendered captures
together. Input fixtures verify selective extraction, tamper rejection, transport,
no-clobber publication and cleanup mechanics. They do not establish Windows
graphics support. Only the native probe followed by the unchanged rendering and
application tests on that Windows environment supplies execution evidence.

An upgrade reviews the supplier release and build revision, complete source and
notice closure, both DLL hashes, architecture and PE imports. Update the lock in
one reviewed change, rerun failure fixtures, then repeat native qualification and
rendered comparisons. Retain the previous input and its evidence until the new
environment passes. Do not weaken rendering assertions or silently package host
driver files to repair a failed prerequisite.

Primary references: [Mesa llvmpipe](https://docs.mesa3d.org/drivers/llvmpipe.html),
[Mesa licensing](https://docs.mesa3d.org/license.html),
[supplier release](https://github.com/pal1000/mesa-dist-win/releases/tag/26.2.3),
and [Microsoft OpenGL overview](https://learn.microsoft.com/en-us/windows/win32/opengl/opengl).

### Private repository retention for hosted replay

The shared hosted `graphics-input` step also accepts an exact own-repository
GitHub asset API URL,
`https://api.github.com/repos/OWNER/REPOSITORY/releases/assets/ASSET_ID`.
It authenticates through the runner's existing GitHub transport, restricts the
asset to that repository, and checks its name, size, digest and downloaded bytes
against the graphics lock. Supply this URL through `graphics_archive_url` for
SDK replay, native GUI checks, application builds and certification. Tokens never
appear in the URL or receipt. A failed transfer stops; no supplier fallback runs.

An operator may retain the exact archive in a private draft release for these
checks. Keep its provenance and immutable asset identity, leave the draft private,
and never select it as Latest or put its DLLs in the SDK/application package.
This private retention does not change the unresolved public redistribution
status. Large retained inputs use release storage, not Actions artifact storage.
