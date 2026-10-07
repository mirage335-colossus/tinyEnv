# GUI boundary audit and qualification

The consuming project integrates every host supplied by the pinned gui-boundary
revision: terminal, framebuffer output, FLTK, SDL window, Rev, hosted browser and
compiled browser Wasm. Every path composes the same application/core library and
shared layout. Ordinary changes within the existing public vocabulary require no
backend-specific feature implementation. This is a tested finite contract, not
a promise that every future OS facility or new control needs no adapter work.

## Inspected paths and resolved maintenance gaps

The review followed declarations through application publication, retained state,
input normalization, rendering, host event loops and service completion. It
included shared geometry/text/bitmap/runtime rules, all native adapters, terminal
mode management, framebuffer input/damage, both browser transports and renderer,
resource preparation, pinned dependency manifests and relevant conformance tests.

The public boundary supports groups, labels, buttons, toggles, choices, text,
lists, bitmaps and menus; shared logical bounds, clipping, scrolling, pages,
availability, stable identities, immutable image ownership and queued services.
Application identifiers occur only in shared code and fixtures. Native adapters
select behavior by generic widget kind and declared values.

The exact application-to-renderer routes are:

| Host | Application definition and generic consumer |
| --- | --- |
| Terminal | `view_definition.hpp` → `Application` → typed terminal runner → `TerminalAdapter` |
| Framebuffer | Same definition/application → framebuffer composition → `FramebufferAdapter` |
| SDL window | Same definition/application → typed SDL runner → the same framebuffer adapter |
| FLTK | Same definition/application → `Session<Application, fltk::Adapter>` → verified patched native adapter |
| Rev | Same definition/application → `Session<Application, rev::Adapter>` → retained native adapter/toolkit |
| Hosted browser | Same definition/application → `Browser<Application>` → `WebAdapter`/`WebSession` → shared renderer/assets |
| Browser Wasm | Same definition/application → the same browser runtime and adapter/session → the same renderer/assets |

Widget construction and layout iterate the same shared definition table. Shared
reducers own product actions and data projections. Backend files contain no
application widget IDs; the maintained adapter changes select only generic kinds,
palette roles and public state. Extending an existing button/list/menu feature
changes shared declarations/reducers and shared fixtures, without editing any
backend. A new primitive or service legitimately extends the public contract and
its selected adapters.

This integration closes these practical consumer gaps:

- A slow-delivery fixture proves edits cannot coalesce across an action or another
  control. The original renderer fails the same assertion; the reviewed patch
  retains ordered commands in both browser transports.
- A visible shared task demonstrates copied input, bounded progress, cancellation,
  restart identity, late-result rejection and close. All hosts use the same
  controller and declaration; no adapter contains task actions. Browser polling
  has one outstanding operation and teardown cancels timers/dialogs/queued input.
- Native supplier conformance now executes FLTK, Rev and clipboard assertions
  against the same selected adapters linked into the application.

- The architecture guard scans nested shared and host source trees and common
  C/C++ header/implementation suffixes. A real command-line regression places
  prohibited toolkit dependencies and application IDs in nested files, observes
  rejection, then verifies the generic replacement succeeds.

- Every backend has an explicit build target, dependencies and host lifecycle;
  previously uncomposed paths are not left as references to a different example.
- Terminal/SDL platform runners accept a typed application. Maintained exact
  patches replace hardwired demonstration composition and remove SDL's
  demonstration-specific smoke actions; host qualification calls one shared
  application scenario and contains no feature dispatch.
- Native and Wasm browser bridges instantiate one runtime; both use identical
  verified DOM renderer/assets. The portable hosted transport avoids POSIX-only
  pipe readiness, bounds request/response queues and time, and reaps failed children.
- The feature fixture adds a real control at runtime and exercises its meaning
  through each selected adapter. Canonical serialization compares declarations,
  geometry, actions and values; a browser fixture compares actual DOM geometry.
- Generic FLTK appearance now uses the same flat surface/disabled/border roles
  and monospaced font class as the pixel/native reference. Native focus clearing
  is explicit; actual controls retain their input/callback behavior. Real capture
  checks detect geometry, palette and missing-text regressions.
- A complete offline source input group retains all upstream implementation and
  reviewed integration patches. Complete source-tree verification covers files
  outside the consumed-header lock, and the ordinary build entry point restores
  the group before configuring the same selected targets.
- The shared Windows CMake interface defines `NOMINMAX` before native toolkit
  headers are parsed. Direct adapter consumers, composed application hosts and
  tests inherit the guard, so Win32 macros cannot rewrite generic C++ `std::min`
  and `std::max` calls. Toolkit producer targets keep their own configuration.
  A compile fixture exercises real interface inheritance and a failing control
  with the guard removed; Windows uses its actual platform header. The portable
  fixture alone does not establish successful native GUI execution.
- GUI install destinations exist behind reviewed lock metadata. Local development
  can build all hosts; an unresolved dependency license cannot silently turn into
  a redistributable binary package.

[Patch provenance and upgrade rules](../gui/patches/README.md) identify the exact
local adaptations. The source dependency remains unchanged. Upstreaming typed
runners, shared appearance roles and portable pipe handling would eliminate those
maintained changes.

## Capability and fallback policy

| Concern | Shared contract and required behavior | Qualification limit |
| --- | --- | --- |
| Geometry | One logical layout; scale applies at the renderer; clipping/hit testing use the same resolved geometry | Native fonts and terminal cells need not have identical pixels |
| Input | Shared edit/selection normalization; stable record keys; stale generation/base rejection; disabled/hidden controls cannot act | Native IME, touch, drag capture and complex text need selected-platform checks/extensions |
| Text | UTF-8 at the boundary, explicit byte limits, common editor policy, visible rejection status from core validation | Bitmap font coverage is finite; this core intentionally accepts printable ASCII records |
| Accessibility | Shared labels/names, row descriptions, keyboard traversal, readable status text; browser uses semantic controls/ARIA | Accessible names alone do not qualify a screen reader; terminal/framebuffer/native accessibility bridges remain profile-specific |
| Services | Explicit request identity, exactly one accepted completion, cancel/error distinguished, late completion rejected after shutdown | Prompt is the common implemented service; file/location calls explicitly fail in these native hosts |
| Clipboard | Adapter/host owns platform access, application never receives native handles | FLTK/Rev expose host clipboard writes; SDL handles editor clipboard keys; browser permissions can reject requests |
| Rendering | Immutable frame ownership, revision/damage tracking, retry presentation without repeating core mutation | GPU drivers and physical high-DPI displays require native target qualification |
| Async work | Shared cooperative task owns its input, limits each turn, reports progress and supports cancel/restart/close; browser polling is bounded and replay-safe | Blocking work still needs a separate owned executor and joined shutdown; no toolkit objects in workers |
| Session lifecycle | New browser epoch on recreation, ordered operations, duplicate command suppression, bounded transport | Hosted server is loopback-only and is not a multiuser deployment framework |

Capabilities belong to the selected deployment profile, not toolkit-name branches
inside shared features. Before adding a service, state required semantics and
which profiles support it; supply a generic fallback or disable the shared action
with an explanation. Unsupported requests must complete with a visible error,
never claim success. A shared contract extension must land with all required
adapter implementations and fixtures before a feature depends on it.

Practical checks include unsupported file-service errors completed exactly once,
prompt cancellation, close with pending service, invalid core text and recovery,
stale events, browser retry/session isolation, transport timeout/blocked-pipe
cleanup, disabled-action behavior, resize/minimize recovery, frame lifetime and
injected presentation failure. The browser fixture verifies accessible control
and row names. It does not substitute for assistive-device testing.

Remaining vocabulary limits include multiwindow application coordination, rich
text, complex script shaping, drag capture, native accessibility trees, file
objects and more elaborate layout rules. If an adopted project needs them, extend
the common contract first and prove behavior in every required backend. Do not
invent unrelated backend-specific implementations to conceal an unsupported need.

## Executed verification

The local profile uses Debian 13 x86-64, Clang 19.1.7 and its matching module scanner,
CMake 3.31.6, Ninja, FLTK 1.3.11, SDL 2.32.4, system GLEW/FreeType and the pinned
Rev sources. Optional distribution packages were extracted into an isolated build
prefix; none are fetched by CMake. This newer development host does not establish
Debian 12 or any older release's binary baseline.

| Path | Executed evidence |
| --- | --- |
| Terminal | Real process on private PTY; input, normal close and interruption restore modes; shared extension/geometry suites |
| Framebuffer | Real pixel renderer, pointer/keyboard input, shared extension, immutable frame and resize checks |
| SDL | Real SDL queue, text/key input, added control, resize, software texture upload and close using the declared X11 video driver |
| Rev | Compiled 46 toolkit modules; real native callback paths and OpenGL capture under Xvfb; shared extension, services, close and serialized parity |
| FLTK | Actual native editor/button/list callbacks under Xvfb; shared extension, serialized parity, capture, unavailable-service error and pending-service shutdown |
| Hosted browser | Actual child and loopback sessions, identity/retry/security checks, child/worker cleanup; real Firefox/Chromium editing and prompt cancellation using copied assets |
| Wasm browser | Actual retained Emscripten 6.0.10-git compilation and Node execution; real Firefox/Chromium editing, prompt cancellation and DOM geometry equality with hosted mode |

Firefox 153.4.0 ESR and Chromium 154.0.8037.57 rendered both transport modes
successfully. Shared DOM geometry also matched between those engines. Their captured
screens show the same ordered controls, spacing and logical sizing, with only the
transport status text differing. SDL/framebuffer and Rev captures retain the same
shared arrangement; native glyph rendering may differ. Captures are retained build artifacts with explicit comparison assertions;
there is no exact-pixel guarantee across fonts, window systems or machines.

The real native visual fixture runs framebuffer, FLTK and Rev at 800×640 and
480×360. Canonical declarations must match exactly. Pixel checks require shared
fills and border positions, visible text for each control, horizontal/vertical
text extent within eight pixels of the framebuffer reference, and bounded text
coverage. Overall RGB channel error must remain below 4 on the 0–255 scale; this
secondary check cannot replace the per-control assertions. Negative checks must
reject an erased heading, changed disabled fill and shifted editor. The updated shared task controls preserve these bounds. The executed
profile passed with mean channel error below 1.01 across all compared captures.
Native font rasterization remains different; normal-size controls have the same
order, dimensions, spacing and shared palette.

Run the automated comparison with the prepared display/toolkits:

```sh
cmake --build build/gui-native --target foundation-gui-tests --parallel 2
xvfb-run -a ctest --test-dir build/gui-native -R '^foundation.gui.visual$' \
  --output-on-failure
```

Each comparison creates a fresh `gui/visual-evidence/run-*` directory containing
real RGB captures, PNG previews, canonical declaration JSON, process logs and a
success-only `qualification.json` with binary/capture hashes and measured error.
The fixture clears actual native focus after resize delivery before comparison;
a separate focus assertion checks that behavior. Physical display, high-DPI and
assistive-device behavior still require their selected native profile.

The updated native profile passed 35 GUI CTests, including all six
native executable smoke checks, shared/parity/PTY/HTTP checks and the actual
native visual comparison, the new bounded task and browser lifecycle checks,
and supplier FLTK/Rev/clipboard conformance against the actual selected adapters.
An additional non-unit-scale check reproduced an upstream fixture coordinate
defect; the reviewed test-only mapping fix then passed both the application and
supplier checks at scale 1.25. That supplier scenario is now registered explicitly
as `foundation.gui.supplier.rev-scaled`. Expected pixels and comparison bounds
were preserved.
The updated shared view also compiled against an
unchanged prepared browser SDK and passed the Wasm/Node check, including task
start/cancel/restart/completion. Real Firefox/Chromium runs exercise the visible
task and cover both hosted and Wasm modes. The retained-group fixtures cover complete-tree tampering,
unsafe/duplicate entries, changed integration inputs, dirty source, deterministic
export, mode handling, and atomic/idempotent restore with foreign output preserved.
The updated complete source group exported and restored successfully at the new
CC0 pin, with owner-specific distribution permission and complete retained notices.
An earlier group was consumed through the normal build wrapper; all 19 enabled
GUI checks passed using those restored sources.
Eleven pinned upstream suites cover contract, bitmap, adapter, layout, runtime,
presentation, extension, interaction, framebuffer, terminal and web behavior.
The upstream DOM-renderer suite and local source/patch guards supplement them.
Tests that depend on a display, Node, browser or toolkit are explicit; an omitted
lane is missing evidence. See [build and test commands](gui-boundary.md#build-and-run)
and the optional real-browser command below.

```sh
python3 -B gui/tests/browser_test.py \
  --server build/gui-native/gui/web/serve.py \
  --executable build/gui-native/gui/foundation-gui-web \
  --wasm-dir build/gui-wasm/gui --output build/gui-browser-check
python3 -B gui/tests/browser_test.py --browser chromium \
  --browser-executable /path/to/chromium --driver /path/to/chromedriver \
  --mode hosted --server /copied/share/software-foundation/web/serve.py \
  --executable /copied/bin/foundation-gui-web --output build/chromium-hosted-check
python3 -B gui/tests/browser_test.py --browser firefox --firefox /path/to/firefox \
  --mode wasm --server /copied/share/software-foundation/web/serve.py \
  --wasm-dir /copied/share/software-foundation/web --output build/firefox-wasm-check
```

The browser fixture needs the explicitly selected browser, a matching ChromeDriver
for Chromium, and permission to bind private local sockets. Inputs are prepared
outside the fixture; it never installs browser packages. Chromium uses the
[documented driver setup](https://developer.chrome.com/docs/chromedriver/get-started)
and [WebDriver HTTP commands](https://www.w3.org/TR/webdriver2/).
`--mode hosted`, `--mode wasm` and default `--mode both` let artifact qualification
exercise each deliverable separately. Source-build server assets and Wasm modules
may reside in different directories. Installed modules and server assets share
`share/software-foundation/web`. The output directory must be new.

Only after successful checks and cleanup does the fixture publish
`qualification.json`: schema version `1`, status `passed`, engine, actual browser
version, selected mode, completed checks, explicit browser arguments and the
verified input SHA256 map. It rejects changed input bytes, saves captures and
`geometry.json`, removes its temporary profile and stops browser/server children.
Failure leaves no success receipt. Browser/driver logs survive both startup
failure and normal temporary-profile cleanup. On systems with bounded local
socket names, use a short owned `TMPDIR`; a long temporary path can prevent
Chromium startup before any application assertion. Retain that receipt with the release's broader
environment and compatibility evidence. `FOUNDATION_GUI_CAPTURE_DIR` optionally saves native fixture captures
to an existing claimed output directory. Keep browser/display runs separate from
ordinary focused edit loops unless those paths changed.

Windows, ARM64, macOS, Debian 12 execution, physical GPU/input devices, screen
readers and browser engines beyond the two listed above were not qualified by this
local profile. Cross-platform code and CI recipes are implementation support;
release claims require execution in the actual declared profile.

## Distribution gate

The pinned dependency dedicates project-owned work under CC0-1.0 and explicitly
excludes third-party code and generated font data. The repository owner confirmed
that the existing Rev agreement covers this repository's source releases and
compiled application binaries. The lock retains that dated, owner-specific scope,
the supplier provenance record and exact hashes of all required license notices.
It records `license: CC0-1.0` and `redistribution.approved: true` for this scope.
This does not grant a general Rev license for unrelated downstream projects.
A project reusing this example must review its own supplier rights and permission
scope; copying this approval is not that review.

CMake derives `FOUNDATION_GUI_DISTRIBUTABLE` from the reviewed lock and verified
notice files; no configure switch waives that review. Native application
executables install under `bin`, browser assets/modules under
`share/software-foundation/web`, and the complete dependency notices and permission
record under the installed documentation directory. The build compiles this
repository's application against reusable adapters; upstream demonstration
executables are not application deliverables. Verify the runtime library closure,
notice bundle and actual execution on every target before issuing release assets.
Permission to distribute is distinct from native release qualification.

## Initial-view gallery

[The screenshot workflow](screenshots.md) is separate from interaction/parity
qualification. It launches fresh application instances and captures FLTK, Rev,
SDL, a terminal window, the application framebuffer, hosted web and compiled Wasm
web from the same view definition. Conformance captures taken after editing state
are not substituted for initial screenshots. The gallery records viewport, DPI,
source, exact SDK groups, host prerequisites and image digests. Actual capture
execution is recorded in [validation](validation.md); a helper fixture pass alone
is not evidence that every native window was captured.

## Small Rev compiler diagnostic

[`tools/rev_probe.py`](../tools/rev_probe.py) compiles four modules from the verified
retained GUI input group and runs two focused comparison/layout cases. It requires
an installed supported compiler, CMake and Ninja, consumes no display or graphics
dependency build, and performs no supplier download. Each new attempt records exact
inputs, selected tool identities, case results and joined process lifetimes.
The manual [Rev diagnostic workflow](../.github/workflows/rev-probe.yml) selects
a native runner and an installed compiler, restores an exact existing GUI group,
and retains bounded diagnostic evidence. It builds no SDK and installs no packages.
For an installed Clang 19 toolchain and a prepared GUI group:

```sh
python3 -B tools/rev_probe.py --gui-input-group /prepared/gui-group \
  --compiler clang++-19 --jobs auto --output build/rev-probe-001
```

Use a new owned output directory for every attempt. This optional module probe
needs CMake 3.28+; it does not raise the ordinary build's CMake 3.24 minimum.
See [the diagnostic instructions](../tests/rev_style_probe/README.md). This is useful
before compiler or supplier upgrades; all-backend qualification remains required.
