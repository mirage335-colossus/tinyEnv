# Reviewed integration changes

These unified diffs adapt the pinned public repository in the build directory.
The original source tree is never edited. The dependency lock verifies every
input; `apply.py` additionally requires exact hunk positions and context. There
is no fuzzy application, type alias to an upstream demonstration, or application
identity inside a renderer.

- `terminal-runner.patch` exposes `run_terminal<App>` under the typed host
  contract. Terminal setup, input, output bounds and restoration stay upstream.
- `terminal-caret.patch` inverts the focused editor's caret cell colors without
  replacing its glyph. Placeholders and text stay readable at the insertion point,
  including the first character and literal Unicode escapes. The caret remains
  clipped to the editor and terminal viewport. Generic cell/ANSI regressions and
  the actual terminal-host test cover this behavior. Remove the patch when the
  pinned upstream provides the same behavior and passes those checks.
- `sdl-runner.patch` exposes `run_sdl<App, Observer>`. It removes the upstream
  demonstration's test actions and accepts a test observer. Production uses a
  no-op observer. Input translation, texture upload, damage and window handling
  remain upstream. The test observer lives with tests and is never in product code.
- `rev-build.patch` consumes explicit verified source paths and creates reusable
  toolkit/adapter targets, without the upstream demonstration or install rules.
- `rev-dependencies.patch` passes the preserved archive root explicitly to the
  upstream GLEW/FreeType recipe.
- `rev-pointer.patch` translates physical raw pointer gestures with stable
  ownership through release or cancellation, skipping inert text when choosing
  the declared input surface. `rev-pointer-probe.patch` exposes native phase
  input to focused tests while retaining the existing semantic click probe.
- `fltk-appearance.patch` renders generic groups, buttons, toggles and menus with
  the shared flat palette, border and font roles. It uses a monospaced font class
  throughout, including measurement, and clears native focus when requested.
  Native button/editor callbacks and keyboard handling remain in the toolkit.
  No application identity or command occurs in this adapter patch. Real native
  control, toggle, focus and pixel-comparison fixtures protect its behavior.
- `fltk-pointer.patch` follows the appearance patch and translates physical
  pointer input on declared raw surfaces into press, move and release, retaining
  the target through a drag outside its bounds. Escape and loss of window focus
  cancel ownership. Inert labels and groups let an underlying surface receive
  input; ordinary buttons, text editors and lists keep their toolkit handling.
  The native FLTK fixture checks phases, capture and cancellation. Remove the
  patch when the pinned upstream implements and passes the same contract.
- `fltk-service-focus.patch` leaves keyboard and clipboard focus with the active
  native prompt while ordinary main-window state synchronizes. Retained focus
  changes still apply, and native main-window focus resumes after acceptance or
  cancellation. Main-window controls also ignore native focus feedback while
  the prompt owns focus, including saved-child reactivation during Windows dialog
  teardown. The ordinary application's Change heading fixture checks native
  paste, repeated ticks, programmatic focus changes, background focus feedback,
  completion and subsequent user focus. Remove the patch when the pinned upstream
  provides this behavior and passes those checks.

- `contract-portability.patch` makes the upstream synchronous text acknowledgment
  test capture an explicitly declared pointer, then assigns it after construction.
  The adapter constructor only stores the handler. A guard rejects any callback
  before assignment; the original event-delivery and selection assertions remain.
  This avoids MSVC's rejection of self-reference from the initializer's implicit
  capture. Only the generated test is patched. Remove this adaptation when the
  pinned upstream uses a supported capture and passes the same Windows test.

- `adapter-portability.patch` applies the same explicit target binding to the
  metrics callback. Mutation and recursive measurement still execute inside the
  callback and must be rejected by the adapter's original guards. Constructor
  timing, exception recovery and all original assertions remain checked. Remove
  it when the pinned upstream passes these checks with supported MSVC captures.

Small FLTK/Rev loops and the two browser composition roots implement the common
host contract directly. `host/browser.hpp` is the single native/Wasm runtime.
The portable loopback transport replaces only the pinned server's pipe session
class; its existing assets, HTTP checks and session registry are reused.

For an upgrade, review upstream changes, refresh the pin and hashes, regenerate
and inspect each diff, and run every selected host/conformance check. Never
refresh hashes just to bypass a mismatch. Upstreaming typed runners, portable
pipe transport and shared appearance roles would remove these local adaptations. Their provenance
is the locked gui-boundary revision; project-owned sources now use CC0-1.0, while retained suppliers keep their
separate terms. The lock records the repository owner’s confirmed distribution scope and
retains supplier notices; it grants no general downstream supplier permission.

- `web-ordering.patch` coalesces only the last pending compatible operation.
  Actions and edits to another control retain their order under slow delivery.
  Client close rejects pending input and prevents late replies repainting a dead
  view; an abortable prompt removes its dialog during session teardown.
  `web-ordering-test.patch` points retained assertions at the patched renderer
  and adds a delayed-delivery action-barrier regression. Both browser transports
  consume this same generated module.

- `web-tick.patch` adds an optional owner-thread tick to the reusable web session.
  Only an authenticated, new ordered poll calls it; retries cannot repeat work.
- `web-lifecycle.patch` connects the bounded polling module to both browser
  transports, disconnects resize observation and cancels outstanding prompts on
  navigation. Wasm releases its application; the hosted transport releases its
  process. Restored pages create a fresh session.
- `web-assets.patch` adds exactly the retained lifecycle, Worker transport, presenter and file-service modules to the server's
  static allowlist. Host/Origin, token and path checks remain unchanged.

The terminal runner calls the same application tick as the other hosts. No task
identity or progress calculation appears in any runner, adapter or browser asset.

- `rev-conformance-scale.patch` maps three supplier bitmap sample points through
  the fixture's existing logical-to-physical transform. The unmodified check
  fails at scale 1.25 despite correct rendering; color and clipping assertions
  are unchanged. Both ordinary and scaled native runs remain required.

- `file-services.patch` appends bounded owned-content read/write capabilities to
  the public service contract; old path-selection kinds keep their meanings.
- `web-file-services.patch` delegates only those generic content capabilities to
  the host helper. Paths and browser File objects never enter shared features.
- `web-responsiveness.patch` bounds measurement batches, reuses/prunes probes and
  retains keyed row/cell DOM nodes. It follows the ordering patch exactly.
- `web-presentation.patch` accepts authoritative state immediately and coalesces
  visual snapshots with explicit service/error/close boundaries and owned teardown.

- `web-file-transfer.patch` extends the tick-enabled session with bounded ordered
  import chunks, bounded export reads and a native-only completion seam. Existing
  epoch/sequence retries remain authoritative, service identity/byte bounds gate
  every chunk, and only complete UTF-8 content reaches application callbacks.
  The composition root alone exposes selected native paths through a distinct
  anonymous pipe; browser messages cannot acquire that authority.
- Terminal and SDL runner patches compose the common native content provider.
  Selectors remain generic host prompts; feature code receives owned contents.
