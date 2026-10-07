# Software Foundation videos

Two videos explain the project through fresh examples, narration and editor
recordings:

- **Tutorial — know which file to edit.** Follow a button into its C function,
  make a one-line calculation change, find the corresponding C++ and Rust files,
  add compiler inputs, and connect processing blocks visually.
- **Capabilities.** See ordinary source code connected to a visual frontend,
  side-by-side screenshots of seven application GUI and terminal hosts, continuous
  processing, retained SDKs, regression checks and direct distribution through
  GitHub Latest releases. The opening presents the intended reduction in
  repeated development from roughly two weeks to hours through reuse.

The capabilities comparison shows the same application in FLTK, Rev, SDL,
framebuffer, hosted browser, browser WebAssembly, and the terminal TUI. A layer
diagram explains how shared application behavior and layout are insulated from
backend rendering, input and platform details. Screenshots come from the verified
October 5 application gallery in `docs/screenshots/`, read without modification.

The editor is an optional helper. AI coding agents can follow its project schema,
event bindings and block interfaces when visual editing is wanted; ordinary
source development remains available independently. The examples, editor,
prepared toolchains and local documentation also support continued development
during frontier AI provider downtime.

This production is isolated in `tutorial-video/`. The application and editor
are read-only subjects. Authored dialogue, scene instructions, capture actions,
rendering code, demonstration sources and fonts are retained here for future
retakes, including recordings made without AI. The narration model is an optional
local production dependency and is not stored in Git. Large generated media and
temporary project copies are also ignored.

See [reproduction instructions](README-reproduction.md) to generate both films,
or [the file guide](FILE-GUIDE.md) for the tutorial's map from task to source.
The editable scripts are [tutorial.json](stories/tutorial.json) and
[capabilities.json](stories/capabilities.json). The `sentences` arrays are the
complete narration; the remaining fields define the visuals.

The tutorial shows the repository's retained HTML documentation explorer and
matching PDFs. These reader files live in `documentation-tool/published/` and
are captured as read-only inputs. They are an October 4 snapshot of the main
application, separate from the newer editor examples. Reading the bundle needs
no AI service, web server or documentation rebuild.

The default results are `output/tutorial/film.mp4` and
`output/capabilities/film.mp4`, accompanied by captions, chapters, transcripts,
timelines and verification receipts. These files are generated locally rather
than checked into Git.

## Evidence and scope

The explanations were checked against repository commit
`e33d72a3e2229e9c876f30dd1d52e583756ec1b9`. New recordings operate on disposable
copies of this repository's examples. The production runs compiled checks for
the C edit, the mixed C/C++/Rust example, and the generated Reset event binding.

[File and documentation research](research/file-map.txt) records exact source
locations. [History notes](research/history-facts.txt) connect the recurring
development difficulties to the repository history. The two-week development
and hours-of-adaptation figures describe the intended benefit of reuse, not
measurements derived from commit timestamps. The capabilities narration presents
that intent without attributing an opinion to the team. This example represents
work by members of the development team and one part of their broader capabilities.

Application GUI hosts and optional editor hosts have separate qualification
records. Computer vision is presented as a use for custom processing blocks;
the demonstrated algorithms are gain processing and a stateful Rust filter.
APT and pacman consume the GitHub Latest download root directly. Gentoo uses
the verified Portage sync adapter described in the distribution documentation.

After changing source paths, editor behavior or distribution contracts, review
the story scripts and regenerate the affected recordings before rendering.
