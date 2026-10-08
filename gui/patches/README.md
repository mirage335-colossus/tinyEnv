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
- `context-contract.patch` appends default-disabled `context_input` and the
  `context_menu` pointer kind. It validates secondary intent against the top
  interactive target, clip, availability and zero pointer owner, leaving existing
  event values and ordinary declarations unchanged.
- `context-interaction.patch` dispatches one context event to an opted-in surface
  through inert decorations. Existing declared popup behavior remains the
  fallback; modal prompts and active primary gestures prevent dispatch.
- `fltk-context.patch` and `rev-context.patch` translate native secondary clicks
  without changing primary control handling. Shared framebuffer/SDL dispatches
  the same generic intent through its interaction policy.
- `fltk-escape.patch` follows the context patch and handles both native keydown
  and fallback shortcut Escape events through the same shared shortcut policy.
  An unbound Escape is consumed instead of invoking FLTK's implicit window
  close; a declared Escape button action still runs. The focused native context
  fixture exercises both event paths with and without a binding. Remove the
  patch when the pinned upstream passes the same behavior.
- `fltk-background-focus.patch` follows the Escape patch and restores native
  control focus only while the main window is visible and retains native focus
  ownership. FLTK focus restoration can activate or remap its top-level window;
  background and minimized windows therefore keep focus changes in the retained
  model until the window manager restores native focus. Explicit initial show,
  window-manager restore and application close remain separate lifecycle actions.
  Same-window child focus changes preserve native ownership. The native fixture
  checks unfocus, iconification events, repeated background updates, hidden state
  and restoration. Completing a foreground prompt returns focus to its visible
  parent even when native FocusIn is deferred; background or iconified completion
  leaves native focus unchanged. Prompt and context fixtures cover both paths.
  Remove the patch when upstream passes the same behavior.
- `fltk-native-ownership.patch` follows the background-focus patch and removes
  native focus requests from ordinary presentation altogether. Retained focus
  remains pending until a native FocusIn or explicit foreground interaction.
  Toolkit focus callbacks while controls are retired cannot refocus a child.
  A finishing foreground prompt restores focus once, after prompt teardown and
  reply-created controls are materialized, through an explicit completion
  boundary. A successor prompt/popup retains focus; background/hidden completion
  still leaves focus deferred. Raw cancellation and presentation revocation also
  clear only this adapter's native `Fl::pushed` routing, so Escape or focus loss
  cannot leave an abandoned drag owned by the top-level window. The native
  fixtures check pending model focus, true toolkit press/cancel routing, prompts
  and restoration. Remove when upstream passes the same contracts.
- `bitmap-copy.patch` bulk-copies equal RGB24/gray8 rows and clears byte-addressable
  damage without repeating per-pixel format conversion. Input is still copied
  before any destination write, preserving self-overlap. Packed mono pixels keep
  their original bit handling. A full repaint starts with a new black grid while
  preserving the previous committed image on producer failure. Supplier bitmap
  checks and `bitmap_copy_test.cpp` cover pixel equality, padding, overlaps,
  packed tails, sparse replacement and rollback. Remove when upstream provides
  equivalent behavior and passes these checks.
- `fltk-bitmap.patch` follows native ownership and draws an exact-size RGB bitmap
  directly during the synchronous native operation. Other formats and fractional
  native dimensions retain conversion/scaling. Borrowed CPU pixels never survive
  the draw. Idle synchronization does not schedule a redraw; accepted snapshots,
  bitmap invalidation, scroll changes, popup retirement and prompt completion
  still update the native controls. `fltk_bitmap_test.cpp` checks idle native
  damage, fresh pixels, representations, resize, replacement and prompt completion;
  existing native focus/cancellation fixtures remain applicable. Remove when
  upstream provides equivalent behavior and passes these checks.
- `web-context.patch` and `web-context-renderer.patch` transport the opt-in field
  and event through both browser serialization and the isolated renderer channel.
  They retain generation/availability checks and suppress browser default menus
  for a declared context-input surface while preserving existing popup handling.
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
- `shortcut-contract.patch` appends physical Z/Y shortcut keys and optional
  current-generation focus scopes. Shortcut activation carries its initiating
  control identity; global bindings and existing aggregate declarations retain
  their defaults. `shortcut-memory.patch` stamps the retained focused control,
  and `shortcut-interaction.patch`, `terminal-shortcuts.patch`, the generic SDL
  runner and `rev-shortcuts.patch` translate the same physical keys. Matching
  declared shortcuts consume input even when their action is unavailable, so an
  editor cannot interpret a disabled command as a newline or native undo.
- `fltk-interactions.patch` checks declared editor shortcuts before native Enter
  and undo handling, keeps unchanged geometry and fonts out of FLTK editor
  relayout, and schedules no redraw for unchanged/clamped scroll offsets. Existing
  native ownership and pointer cancellation patches still precede it. Native
  fixtures cover focused delivery, initiating identity, disabled actions, tooltip
  help, retained draft/selection and no-op scrolling. Widget help already uses the
  native tooltip capability and needs no feature-specific adapter logic.
- `availability-path.patch` resolves only the current widget's ancestor chain,
  retaining nested scroll, clip, page and modal rules. `shortcut-memory.patch`
  skips unchanged scrolling and preserves unrelated bitmap storage for a group
  without bitmap descendants. Modal/focus/popup decisions are staged before
  commit; groups with bitmap descendants retain transactional grid preparation
  and rollback. Shared fixtures require retained pixel storage and modal rollback.
- `web-shortcuts.patch` serializes focus scopes and accepts the appended keys.
  `web-shortcuts-renderer.patch` captures matching focused strokes before editor
  submit handling while leaving other fields' native editing available. The
  authoritative shared policy stamps actual retained focus before dispatch.

Remove these interaction and scroll patches when the pinned upstream implements
and passes the corresponding shared and native fixtures.

- `fltk-text-scroll.patch` applies text-editor scrolling immediately when native
  layout is current, so the next offset query reports FLTK's applied position.
  Its advertised scrollbar range can include a blank row that native resize
  removes; that projected end must not be reported as reachable. Staged snapshots
  preserve raw requests until final native layout owns their clamp. Generic label
  metrics can treat an unbroken token as one row while the editor wraps it into
  hundreds, so they cannot clamp the request before native synchronization.
  Native scroll owns invalidation; a true no-op retains prior damage throughout
  its native parent chain and leaves no pending reset. The editable/readonly
  fixture covers immediate/applied clamp
  equality, reflow, LF endings, one visible row, same-length text replacement,
  extreme finite requests, Unicode, caret/focus retention, unbroken tokens,
  CRLF syntax lines and unrelated periodic snapshots.
- The `masked-text-*` patches append default-disabled single-line masking to
  `TextPolicy`, reject multiline/nontext/suggested masked controls, and map obscured
  Unicode display positions back to authoritative UTF-8 byte offsets. Shared
  interaction, terminal and framebuffer paths measure and draw the obscured
  projection; input callbacks still receive the actual value.
- `fltk-masked-text.patch` uses native secret input for caret and selection while
  routing edits through shared text policy. It suppresses copy/cut/drag and ordinary
  native undo, so authoritative clearing cannot expose an older value through undo.
- `web-masked-text.patch` and `web-masked-text-renderer.patch` serialize the same
  declaration and set password mode before values. Accessible names and measurement
  use an obscured projection; copy/cut/drag export is suppressed, while paste and
  composition still deliver actual input.
- `rev-masked-text.patch` accepts masked declarations but renders a disabled fixed
  **Masked input unavailable** label. It never creates a clear-text native editor,
  routes masked input or displays the value/placeholder. Other controls remain
  usable. Rev native masked editing remains unavailable; its focused fixture needs
  the optional supported Rev toolchain and native display qualification.

The masked fixtures cover shared rendering/input, browser serialization/DOM and
native FLTK display/edit/clear behavior. These declarations obscure presentation
and prevent the listed exports; they do not encrypt values or remove application
and native input buffers. Remove the adaptations when upstream supplies the same
contract and passes these fixtures.

- `nonvisual-command-contract.patch` adds a trailing `Snapshot.commands` list with
  exact identity, mutable enabled state and optional widget/group scope. Existing
  shortcut targets can name a current command without declaring a visual button;
  activation requires a sourced available focused control within that scope and
  obeys page/clipping/modal rules. Commands never enter widget rendering/hit/tab
  paths. `nonvisual-command-memory.patch` shares the monotonic generation registry,
  makes scope immutable within a generation, and requires direct sourced command
  activation to match retained focus. Disabled declared strokes remain consumed.
- `nonvisual-command-web.patch` transports bounded command metadata and shortcut
  target identities. `nonvisual-command-renderer.patch` keeps keyboard routing on
  current authoritative declarations while commands remain absent from DOM controls.
  The isolated renderer channel admits appended Z/Y strokes and command metadata;
  direct command click operations remain rejected. Shared, browser and native FLTK
  fixtures cover scoped Ctrl+Z/Shift+Z/Y, disabled interception, identity replacement
  and absence from control trees. Remove these patches when upstream supplies the
  same nonvisual action contract and passes the corresponding fixtures.

- `wheel-chaining-interaction.patch` tries a logical ancestor when a text, list or
  group wheel request cannot change its scroll offset. Overflowing children keep
  wheel ownership; clamped or fitting children no longer block their parent group.
- `wheel-chaining-renderer.patch` preserves browser-native text/list scrolling
  while it has room in the requested direction, then routes the wheel to a logical
  group that can move. Raw bitmap wheel handlers, native selection controls and
  browser Ctrl-wheel behavior retain ownership. Shared, browser and native FLTK
  fixtures cover this policy without application-specific block rendering. Remove
  these patches when upstream supplies the same ancestor routing and passes the
  corresponding fixtures.

- `text-frame-contract.patch` appends default-enabled `WidgetState::text_frame`;
  disabling it is accepted only on text controls. It is mutable visual state and
  does not change the text policy or widget generation.
- `text-frame-framebuffer.patch` suppresses normal/focused text outlines in the
  software renderer, preserving fill, clipping, selection and content geometry.
  Terminal text already has no rectangular frame and retains its existing output.
- `text-frame-fltk.patch` suppresses the ordinary editor and secret input's manual
  rectangle while retaining the existing flat native box, focus, selection, copy
  policy, caret, padding and scroll limits. `text-frame-rev.patch` makes only text
  borders transparent after normal/focused styles without changing border width.
- `text-frame-web.patch` serializes the same generic appearance declaration.
  `text-frame-renderer.patch` makes native editor borders transparent and removes
  focused outlines; true or an absent field restores existing CSS defaults. The
  native DOM control and its geometry remain unchanged. Remove these adaptations
  when upstream supplies the same appearance capability and passes the focused
  shared, browser and native fixtures.
