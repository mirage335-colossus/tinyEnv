# Regenerate the videos

This is a video production project inside the repository's `tutorial-video/`
directory. It uses the repository as read-only subject material and keeps its
scripts, dialogue, scene instructions, examples and fonts in this subtree. These
sources preserve what was presented for a future retake, including one recorded
without AI. The large voice model, generated recordings, speech, frames, copied
projects and films are ignored by Git. Automated reproduction is optional and
requires supplying the local voice model described below; neither another video
project nor previously generated media is needed.

## Optional local narration model

The existing production pipeline requires
`tutorial-video/assets/voices/en_US-ljspeech-medium.onnx`, which is not included
in a checkout. Before running the pipeline, obtain that model manually using the
source and SHA-256 recorded in [voice provenance](assets/voices/PROVENANCE.md),
and place it at that path. Its small JSON configuration, notices and expected
checksum remain in Git. The pipeline checks the supplied model against
`assets/inventory.json`; it does not download it automatically.

The model and production tools are unnecessary for reading or reusing the dialogue
in the `sentences` arrays of `stories/tutorial.json` and
`stories/capabilities.json`. Their scene instructions, the examples and the
file guide also remain available for a manually recorded retake.

## Prepare host tools once

The recorded production was run on Linux with Python 3.12, FFmpeg 7.1.5, an X11
virtual display and the FLTK editor. Install Python with `venv`/`pip`, FFmpeg and
ffprobe with libx264, libass and x11grab support, Xvfb, xdotool and ImageMagick's
`import` command. The examples also use a C17 compiler, C++20 compiler, CMake,
Ninja and Rust. Building the editor requires the prerequisites described in
[`../COMPILE-editor`](../COMPILE-editor); an already built editor may be supplied
instead. The documentation walkthrough requires an installed Chromium or Chrome
with its native PDF viewer. Browser automation uses the same private X display
and native input tools as the editor capture; Playwright is not required. Media
generation does not download or install dependencies. Native editor/browser UI
uses the host's installed fonts; install DejaVu or equivalent standard sans and
monospace fonts. Editorial panels and captions use the retained fonts in `assets/`.

For a Debian-family machine, the ordinary host tool packages include:

```sh
sudo apt-get install ffmpeg xvfb xdotool imagemagick build-essential \
  cmake ninja-build libfltk1.3-dev chromium fonts-dejavu-core
```

Create the production Python environment from the repository root, using your
installed Python interpreter. Python 3.12 was used for the retained dependency
versions. This explicit preparation step may access PyPI; an independently
prepared wheel directory can be passed to pip with `--no-index --find-links`.

```sh
python3.12 -m venv tutorial-video/.work/venv
tutorial-video/.work/venv/bin/python -m pip install \
  -r tutorial-video/requirements.txt
```

The requirements pin direct and transitive Python dependencies. Do not set
`PYTHONPATH` to an earlier production directory: the pipeline clears it for its
children and selects `.work/venv/bin/python` automatically when that environment
exists. A different prepared environment can be selected with `--python`.
Host tools and installed development SDKs are declared toolchain prerequisites;
they are not copied Python installations or undisclosed content resources.

## Rebuild everything from source content

From the repository root, with the local narration model supplied and the tools
and Rust compiler in `PATH`:

```sh
tutorial-video/.work/venv/bin/python \
  tutorial-video/production/pipeline.py all
```

The `all` command checks production asset hashes and the Python dependency versions,
builds the FLTK editor under `.work/editor` if needed, executes the compiled C,
C++ and Rust examples, records new private editor sessions, checks the actual
exported Reset event, synthesizes narration, renders both films and verifies their
delivery hashes and complete streams. The
editor build uses the supported repository `build.sh` entry point. It writes to
the video's own `.work/editor` build tree.

Capture also records the local HTML documentation explorer and its corresponding
PDF collection. It reads the complete committed
[`../documentation-tool/published/`](../documentation-tool/published/README.md)
reader bundle, copies it to a neutral temporary directory and navigates that copy
with a fresh browser profile. The capture process closes its browser and display
and removes the temporary reader copy and profile when finished. No documentation generation, additional Python
dependencies, external page or application modification is involved. The bundle
is a reference snapshot and may not match subsequent application edits;
preparation records its snapshot date, fingerprint and all reader-file hashes.

The capabilities film also compares the seven committed application views in
[`../docs/screenshots/`](../docs/screenshots.md), dated 2026-10-05. Before
capabilities rendering, `production/backend_comparison.py` verifies the exact
ten-file gallery with `tools/screenshots.py verify`, then composes four pairs:
FLTK/Rev, SDL/framebuffer, hosted browser/Browser Wasm, and FLTK/terminal TUI.
The reviewed date is retained against this exact source commit, so depth-one
checkouts can regenerate it. A future gallery uses its own commit's date; when
that historical commit is absent, retain a reviewed commit/date mapping in the
generator before regenerating the comparisons.
The images remain complete at their original pixel dimensions, with no cropping
or resampling. The terminal border and status row remain visible. A fixed
diagram shows the shared application, insulating GUI abstraction and host layer;
the browser pair identifies its common renderer and different execution modes.
This stage requires only the retained gallery, production code, fonts, Pillow
and media tools; it does not build or recapture the application.

Use an existing editor and a deliberately selected Rust compiler when available:

```sh
tutorial-video/.work/venv/bin/python \
  tutorial-video/production/pipeline.py all \
  --editor /path/to/foundation-editor-fltk \
  --rustc /path/to/rustc \
  --browser /path/to/chromium
```

Every process working on project files uses private copies. Source-editor windows
run from unique neutral temporary directories so the recordings do not expose
the workstation's parent directory names. These temporary directories are owned
by the capture process. The copied and edited projects needed for the event check
are exported to `.work/projects`; original application example files are read-only.
The default private X displays are `:95`, `:96` and `:97`; choose another free
group with `--display`. A restricted execution environment may need permission for Xvfb to
create its local X11 sockets; the display listens to no TCP port.

Individual stages are available when reviewing changes:

```sh
python3 tutorial-video/production/pipeline.py prepare --editor /path/to/editor
python3 tutorial-video/production/pipeline.py capture --editor /path/to/editor
python3 tutorial-video/production/pipeline.py render
python3 tutorial-video/production/pipeline.py verify
```

To update only documentation footage while retaining existing editor captures:

```sh
python3 tutorial-video/production/pipeline.py capture --documentation-only \
  --browser /path/to/chromium
```

`render --film tutorial` or `render --film capabilities` selects one film.
Any capabilities render regenerates `.work/gallery/backend-comparison.mp4`
before narration or visual assembly. The screenshot comparison can also be
regenerated and its four preview PNGs reviewed independently:

```sh
tutorial-video/.work/venv/bin/python \
  tutorial-video/production/backend_comparison.py
```

The direct generator accepts `--ffmpeg`, `--ffprobe`, `--tools-root` and
`--library-path` with the same meanings as the pipeline. Its `--verify-only`
mode checks the existing comparison receipt without encoding a replacement.

`render --previews-only` creates editorial previews; `render --narration-only`
creates the timed narration and captions without encoding video. A successful
preview or narration run does not mean that a film has been verified.
`verify` checks rendered outputs without recompiling the examples. The example
checks can be invoked separately using `examples/check_examples.py --only all`.
After successful verification, it publishes clearly named MP4 copies in the
output directory and verifies that their bytes match the original per-film files.
The exported event check can be invoked with
`examples/language-integration/event-check/run_check.py --project /path/to/copied/project`.
It restores its GUI headers from the repository's retained input archive into
`.work/event-check`, using a small CMake configuration; it does not build the
application or require headers from another production project.

Normally run `capture` once after a relevant scene change, then use cached sentence
audio and segments during review. To prove regeneration with no existing media,
move or delete **only your own** `.work/capture`, `.work/gallery`, `output/tutorial` and
`output/capabilities` directories, and run `all`. Preserve `.work/venv` and the
editor build as prepared toolchain inputs. A clean checkout also starts with no
generated media.

## Tool and output overrides

Tools are selected from `PATH`. All of these accept explicit executable paths:
`--python`, `--ffmpeg`, `--ffprobe`, `--xvfb`, `--xdotool`, `--imagemagick`,
`--editor`, `--browser` and `--rustc`. Browser detection tries Chromium and Chrome;
`FOUNDATION_VIDEO_BROWSER` can also select the prepared browser. The recorded
PDF page/zoom controls use Chromium's native viewer.
`--sdk` selects a retained native C++ SDK for an editor
build. `--build-jobs` defaults to two.

An extracted tool prefix can be supplied with `--tools-root /path/to/host-tools`;
the pipeline looks at its root and `usr/bin` for executables and uses its
`usr/lib/x86_64-linux-gnu` directory for runtime libraries. For a different layout,
use the individual overrides and an explicit `--library-path` instead. These
paths describe the selected host's prepared tools; no fixed workstation paths
are embedded in the scripts.

By default all persistent generated files stay in `tutorial-video/.work/` and
`tutorial-video/output/`. The pipeline rejects output paths that would write into
application source or escape through a symlink. An explicitly selected
`--output-dir /path/outside/repository` is permitted for delivery. The default
per-film size limit is 120 MB and can be changed with `--size-limit-mb`.

## Inputs and outputs

| Path | Purpose |
| --- | --- |
| `stories/tutorial.json` | Tutorial's narration, scene order and visual content |
| `stories/capabilities.json` | Capabilities video's narration and visual content |
| `capture/` | Fresh screen capture actions and clipboard helper |
| `production/` | Pipeline, drawing and video/audio assembly code |
| `examples/` | Retained C/C++/Rust demonstrations and compiled checks |
| `assets/voices/` | Retained JSON, provenance, license information and model card; ONNX model supplied locally and ignored |
| `assets/fonts/` | Four retained DejaVu fonts and complete notices |
| `assets/inventory.json` | Expected sizes and SHA-256 values for retained assets and the local voice model |
| `../documentation-tool/published/` | Committed local HTML/PDF reader bundle used in the documentation walkthrough |
| `../docs/screenshots/` | Seven complete application screenshots and three original provenance companions |
| `production/backend_comparison.py` | Verified screenshot comparison generator |
| `.work/capture/` | Regenerated native MP4 clips, screenshots and capture receipts |
| `.work/capture/documentation-html.mp4` | Fresh interactive HTML explorer walkthrough |
| `.work/capture/documentation-pdf.mp4` | Fresh corresponding PDF walkthrough |
| `.work/gallery/backend-comparison.mp4` | Regenerated 44-second, four-pair application comparison |
| `.work/gallery/` | Comparison preview PNGs and source/clip identity receipt |
| `.work/projects/` | Exported copies of the projects edited during recording |
| `.work/examples/` | Compiled demonstration outputs and verification receipts |
| `.work/event-check/` | Restored GUI headers and the actual exported-event verification |
| `.work/preparation.json` | Selected tool identities and source content hashes |
| `.work/logs/` | Stage logs |
| `output/software-foundation-tutorial.mp4` | Named final tutorial copy |
| `output/software-foundation-capabilities.mp4` | Named final capabilities video copy |
| `output/tutorial/film.mp4` | Tutorial master with its supporting files alongside |
| `output/capabilities/film.mp4` | Capabilities master with supporting files alongside |
| `output/verification.json` | Complete film decode and identity verification result |

The revision-two friendly films have been preserved locally in
`output/previous-v2/` with matching-hash receipts for comparison. This directory
contains ignored generated files. Regenerating the current films from a clean
checkout requires the local voice model and prepared production tools.

Each film directory also contains captions in SRT and VTT, chapter metadata,
the narrated script, timeline, preview PNGs, source identity/delivery metadata,
audio and decode reports, and `SHA256SUMS`. Generated audio/segments live beside
them and can be removed and synthesized again. The MP4 contains narration,
burned captions and embedded chapters.

The renderer freezes its story input, hashes source footage and fonts, and checks
the full audio/video streams with FFmpeg's strict error mode. Visual review remains
necessary for readability and scene correctness; successful decoding alone does
not establish that a tutorial demonstrates the right action. New renderings can
have different bytes or timing across tool versions and speech inference; the
retained content supports future retakes. Running this automated pipeline also
requires the local model and production tools; byte-identical MP4s are not promised.

Preparation also records the ten gallery input hashes, source commit and capture
identity. The screenshot comparison receipt records its gallery, generator and
font identities, preview checksums and fully decoded clip hash. `verify` checks
these identities against current retained files whenever a film uses that clip,
so a changed gallery or generator requires a new capabilities render.

The retained asset notices identify their upstream sources. Do not substitute
assets silently; an intentional asset replacement requires updating its inventory
and reviewing the resulting narration or typography.
