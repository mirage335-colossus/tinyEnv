# Initial application screenshots

## View screenshots

**Cloud-built source snapshot — 2026-10-05.** These seven fresh initial views
show the Rust/C++ application built on GitHub-hosted Actions from source commit
[`2e33720a73f0686dc1ffe72992dfb52e472cd059`](https://github.com/mirage335-colossus/software-foundation/commit/2e33720a73f0686dc1ffe72992dfb52e472cd059).
The [published screenshot release](https://github.com/mirage335-colossus/software-foundation/releases/tag/screenshots-37383282720-attempt-1)
and [capture run 37383282720, attempt 1](https://github.com/mirage335-colossus/software-foundation/actions/runs/37383282720/attempts/1)
record the exact hosted execution.
The date is the source commit date. The images document that exact source;
later documentation commits do not change the capture's identity.

The gallery's PNGs and provenance files total about 100 KB and can be
viewed offline in a Markdown viewer. Read [BUILD.txt](screenshots/BUILD.txt) for
the capture summary, [screenshots.json](screenshots/screenshots.json) for exact
source, SDK, Rust compiler, runtime, binary and image identities, and
[SHA256SUMS](screenshots/SHA256SUMS) for the unaltered gallery checksums.
Native and Wasm builds both use their verified retained Rust extensions.
All ten downloaded release assets matched their public SHA-256 identities before
the complete gallery was checked in. These images document appearance;
functional release qualification remains separate.

### FLTK

![Fresh FLTK Entry list application with an empty entry field, action buttons and no entries.](screenshots/fltk.png)

FLTK native window: 640 by 480 client pixels, 96 DPI, scale one.

### Rev

![Fresh Rev Entry list application with an empty entry field, action buttons and no entries.](screenshots/rev.png)

Rev native window: 640 by 480 client pixels, 96 DPI, scale one.

### SDL

![Fresh SDL Entry list application with an empty entry field, action buttons and no entries.](screenshots/sdl.png)

SDL native window: 640 by 480 client pixels, 96 DPI, scale one.

### Terminal

![Fresh terminal Entry list application showing the complete Type an entry placeholder with an inverse-color caret on the T.](screenshots/terminal.png)

The cloud capture includes the [reviewed caret correction](../gui/patches/terminal-caret.patch):
the caret cell's colors invert while its character remains visible. Xterm uses
80 by 31 cells, captured at 644 by 531 pixels with the status row and border
retained. The image was neither cropped nor resampled. The earlier
[2026-10-04 local verification](terminal-caret/capture.json) and its
[terminal image](terminal-caret/terminal.png) remain historical evidence.

### Framebuffer

![Fresh framebuffer Entry list application with an empty entry field, action buttons and no entries.](screenshots/framebuffer.png)

Application framebuffer: 640 by 480 pixels, scale one.

### Hosted browser

![Fresh hosted browser Entry list application with an empty entry field, action buttons and no entries.](screenshots/hosted-web.png)

Hosted browser transport: 640 by 480 viewport pixels, scale one.

### Browser Wasm

![Fresh browser Wasm Entry list application with an empty entry field, action buttons and no entries.](screenshots/wasm.png)

Browser Wasm transport: 640 by 480 viewport pixels, scale one. The two browser
captures have matching initial geometry and identical PNG bytes; the original
manifest records their separate actual capture modes.

## Regenerate or refresh the checked-in gallery

Use the existing [screenshot workflow](../.github/workflows/screenshots.yml) on
the desired source revision with exact prepared SDK recipes and a reviewed GUI
input selector. [SCREENSHOTS](../SCREENSHOTS) is a short command reference;
the capture inputs and prerequisites are described below. `execute=false`
captures and retains private draft release assets. `execute=true` additionally
publishes a new immutable screenshot prerelease through the protected publisher.

To download this exact public snapshot from the repository root, use a fresh
temporary directory and the existing verifier:

```sh
gallery_tag=screenshots-37383282720-attempt-1
gallery_download="$(mktemp -d)"
gh release download "$gallery_tag" \
  --repo mirage335-colossus/software-foundation --dir "$gallery_download"
python3 -B tools/screenshots.py verify "$gallery_download"
```

For a refresh, select the new exact `screenshots-` tag, confirm the downloaded
manifest's source commit, run and attempt against that release and capture run,
and inspect all seven views. After verification succeeds, copy the complete
inventory without editing or mixing its original provenance:

```sh
cp "$gallery_download/"*.png "$gallery_download/BUILD.txt" \
  "$gallery_download/screenshots.json" "$gallery_download/SHA256SUMS" docs/screenshots/
python3 -B tools/screenshots.py verify docs/screenshots
```

Update the capture source date, source commit and release/run links above in
the same change. Keep exactly the seven PNGs and three original companion files
in `docs/screenshots/`; the verifier rejects extra files and altered bytes.

## Capture inputs and behavior

The [screenshot workflow](../.github/workflows/screenshots.yml) builds this
application and captures seven actual surfaces: FLTK, Rev, the SDL window,
the terminal in xterm, the framebuffer, hosted browser rendering and browser
Wasm rendering. Each host starts with a fresh application. No editing scenario,
test-only application or copied image stands in for another backend.

Select existing Linux x64 GUI and browser SDK recipe digests from the dependency
base, a compile job count, and an optional new `screenshots-` tag. Missing SDKs
fail without starting a compiler-base build. Preparing or updating SDKs is a
separate explicit maintenance operation. An explicit `gui_input` JSON selector is
also required. Ordinary capture consumes an existing complete reviewed GUI group;
it never clones upstream or builds a missing dependency group. It does not publish
that source or its application binaries.

Captures default `core_provider` to `rust`. The native and Wasm applications each
need their separate complete matching Rust extension. Hosted
`--native-rust-recipe`/`--wasm-rust-recipe` selectors may name exact retained
recipes; omitted values derive the checked-in producer identities.
`rust_source=base` consumes their exact public base groups. For private recovery,
select `rust_source=retained` and provide `rust_retained_inputs` with exactly
`native` and `wasm` schema-1 Rust requests: repository, target, exact `recipe_id`,
producer run/source/attempt/job, `workflow: "sdk-maintenance.yml"` and
`group` containing `manifest_id`/`manifest_sha256`. The authenticated bundle must
be `rust-sdk-group-<target>-<attempt>`. Invalid or missing groups fail; normal
collection uses only existing local inputs. Explicit `core_provider=cpp` needs
no Rust groups and preserves the legacy capture route.

The default `source=base` consumes only the exact public base. For recovery or
qualification before base publication, select `source=retained` and provide
`retained_inputs`, a JSON object with exactly `native` and `wasm` entries. Each
entry is the complete version-2 retained SDK request from the explicit SDK
producer/import workflow: repository, target, all-GUI profile, recipe, producer
run/job/attempt/source and both group/proof manifest IDs and digests. Neither
mode falls back to the other. Both selected origins are recorded in the gallery;
retained bytes remain explicitly unqualified for SDK publication. Legacy Actions
storage must first pass the explicit import workflow, never implicit retrieval.

For GUI input from the public base, use
`{"source":"base","manifest_sha256":"<exact group manifest digest>"}`.
For a private retained group, use `{"source":"retained","pointer":{...},
"manifest_sha256":"<exact group manifest digest>"}`. Copy the complete pointer
from a successful [GUI input maintenance job](../.github/workflows/gui-inputs.yml):
its exact repository, run, attempt, source, workflow, bundle name, job, release,
tag and manifest asset identity must all match. The bundle must be
`gui-inputs-<attempt>` from `gui-inputs.yml`, containing `gui-group/` and its
`gui-publication-plan.json`. The consumer verifies every group byte and the current
lock and integration patches before installing it. Failed producers, partial
inputs, altered identities and different patches are rejected. Reusing private
bytes grants no qualification or redistribution approval. Invalid selectors fail
before browser setup, acquisition or compilation. The private diagnostics retain
`build/screenshots-inputs/gui-origin.json`; the public gallery retains the exact
GUI group manifest digest without publishing its source archives.

The capture job uses the ordinary unprivileged Ubuntu runner account. It uses
prepared Bookworm SDKs for compilation and explicit distribution packages for the
display, CMake, Ninja, software graphics, fonts and Selenium. The browser-target
SDK restricts its host tool search to system directories, so a tool found only in
a runner-specific tool cache does not satisfy this prerequisite. Its installed Chromium or Chrome
and matching driver remain host prerequisites; no browser enters either SDK.
An [early sandbox and render probe](gallery-browser.md) must pass before SDK
acquisition or compilation. Capture keeps the browser sandbox enabled and changes
no host or container security policy. Compiler and capture children receive only
runtime paths and provenance, excluding transport credentials. The default native client and browser application area
are 640 by 480 pixels at scale one, on a private 96 DPI display. The terminal
uses 80 by 31 cells with its status row and border retained; its physical size
is recorded rather than cropped or stretched to resemble another renderer.

The collector checks that new native windows have painted, have the expected
size and remain stable before capture. Existing or ambiguous windows cannot be
selected. Browser capture waits for completed requests, loaded fonts/images,
the actual requested transport and a stable initial view. Both browser modes
must report the same widget geometry. The collector makes no application edits
and performs no resampling. Native font rendering may still differ.

All long build/capture commands run under the shared process-tree owner.
The hosted helper owns an explicit Xvfb process, with private cookie authentication,
TCP listening disabled, server-selected display allocation and bounded readiness.
It verifies the complete 1280 by 900 display at 96 DPI before launching collection.
After collection succeeds or fails, it terminates and joins that exact server;
a bounded termination timeout uses kill followed by another join. A server exit
during collection fails the run. The outer owner still rejects surviving
descendants; no display child is exempt from this check. A kernel file-size limit
bounds `xvfb.log` to 4 MiB, and reaching that limit fails the display prerequisite.
`build/screenshots-display/` retains `xvfb.log`, `collector.log` and `display.json`
as private diagnostics. Only those logs and receipt are eligible for diagnostic
retention; the private authentication file and browser profiles are excluded.
The authentication file is removed only after the server is joined.
Application children, terminal children and browser descendants must stop
before successful collection. Failure preserves diagnostic outputs in the
owned work directory and does not replace an older gallery. The public output
directory is installed only after the complete new gallery validates.

## Retention and publication

`execute=false` builds, captures and retains the gallery in the run's private
draft release storage. It does write these private release assets; it does not
publish a screenshot release or move Latest. The pipeline uses no Actions
artifacts. Images and their accompanying metadata remain release assets even
when their compressed size would be small.

`execute=true` additionally invokes the protected `release-publisher`
environment. Configure its allowed branches and required reviewers in GitHub.
The publisher downloads the completed producer's verified bundle and requires
exactly seven PNGs, `BUILD.txt`, `screenshots.json` and `SHA256SUMS`. It rejects
extra files, changed image bytes, omitted surfaces and incomplete provenance.

Publication creates a new draft under a `screenshots-` tag fixed to the source
commit, uploads the complete inventory and downloads every uploaded asset for
verification. It then publishes a prerelease with Latest explicitly disabled
and verifies the final asset identities and pointer. An existing release/tag,
partial upload or uncertain remote outcome requires reconciliation; there is
no overwrite, delete or automatic resume. Screenshot publication shares the
application publisher lock but uses a distinct release namespace.

`screenshots.json` records the source commit and tree digest, actual executable
digests, both complete SDK triplets, reviewed GUI input identity, runtime/tool
versions, run/attempt, dimensions and image checksums. New schema-2 galleries
also bind the provider, both Rust compiler/manifest identities, targets/versions,
complete group inventories and origins. Historical schema-1 C++ galleries retain
their original validation rules and bytes. `BUILD.txt` is a short
human-readable companion. Source, executable files, SDK archives, browser
profiles and external graphics libraries are excluded from the public gallery.

Screenshots are visual documentation. They do not establish functional release
qualification, physical display compatibility or permission to redistribute
application dependencies. The existing GUI package licensing gate remains
independent of producing these images. Conformance captures and actual interaction
tests remain separate qualification evidence.

## Local use and checks

The [collector](../tools/screenshots.py) supports `collect` with exact existing
`--native-group`, `--native-recipe`, `--wasm-group`, `--wasm-recipe` and
`--gui-group` inputs, plus new `--work` and `--output` directories. Use Linux x64,
a clean source checkout, the declared display/runtime environment and the same
prerequisites as the workflow. `hosted` runs the complete unprivileged hosted-runtime
path and explicitly fetches its existing SDK and required `--gui-input` selections. `publish` plans by default;
only its `--execute` switch mutates a public release.

Default Rust collection additionally supplies `--native-rust-group`,
`--native-rust-recipe`, `--wasm-rust-group` and `--wasm-rust-recipe`, with optional
`--rust-origins`. `--core-provider cpp` explicitly selects legacy collection.

Run the [offline failure suite](../tests/test_screenshots.py) through the normal
tool-test runner. It covers complete inventories, changed images, nonblank
capture, startup/display failures, window ambiguity, process cleanup, immutable
publication, changed asset identity, exact retained GUI selection, authenticated
display setup, bounded readiness and join ordering, and partial-upload uncertainty. These mocks
do not qualify actual browser, toolkit, display or GitHub permission behavior;
the complete hosted screenshot job must pass on the intended source revision.
