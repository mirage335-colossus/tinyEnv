# Browser Worker and offline application

`wasm_transport.mjs` is the asynchronous exchange used by the existing browser
Client. One dedicated `wasm_worker.mjs` instance owns one C++ session and its
create/receive/destroy calls. DOM controls, accessible names, native editing,
IME and browser services remain on the page thread. The small cooperative
TextTask still bounds each application step; no audio scheduler, pthreads,
shared memory, Asyncify or fibers are required.

The Client retains ordering, epochs and sequence acknowledgements. The transport
admits only one outstanding exchange, limits each UTF-8 request to 1 MiB and each
response to 32 MiB, and rejects overload instead of accumulating another queue.
The ordered Client also bounds queued operations, including its in-flight retry,
to 8 MiB. It snapshots object inputs, reserves one complete request for dynamic
inputs and only coalesces adjacent equivalent edits; actions remain ordering
barriers. Oversized provisional editor input is rejected before retaining a
closure. These are serialized payload bounds, not a claim about total JS heap use.
A Worker failure rejects pending callers and requires a fresh session. The
browser offers Restart application; it never replays an old action into a new
epoch. A recoverable hosted response loss still uses the Client's identical
sequence retry. Initialization has a 30-second deadline.

Explicit close rejects pending callers, waits up to one second for the Worker to
destroy its runtime and acknowledge close, then terminates it. The returned
`graceful` field distinguishes acknowledgement from forced termination. A page
unload cannot guarantee asynchronous cleanup; `pagehide` stops producers and
requests cleanup, and a persisted page is reloaded into a fresh session.

`foundation-wasm-package` consumes the generated patched browser modules and
compiled module. Its `wasm-package/software-foundation-wasm.html` can be opened
as a local file without a server or companion files. Applicable notices are
included, along with separate `web-manifest.json` and `manifest.sha256` evidence.
Installation places these three files in `share/software-foundation/wasm`.
The ordinary multi-file debugging mode remains available under `web`.

The package preloads Wasm bytes, uses Blob modules and a dedicated Worker,
and applies a Content Security Policy with `connect-src 'none'`. HTTP mode uses
a module Worker. The direct-file package uses a classic Blob Worker entry made
from the reviewed `wasm_worker.mjs` declaration; its factory still loads as an
ES module inside that Worker. This avoids Chromium's file-origin module-Worker
entry restriction without changing CSP, transport ordering, limits or shutdown.
Packaging rejects unreviewed module syntax in the converted entry. The module
factory receives a Blob-safe `locateFile` callback even when Wasm bytes are
supplied: Emscripten may compute the filename before checking those bytes.
Packaging rejects changes to the reviewed boot import edges and HTML shell,
unsafe CSS terminators, missing notices, oversized inputs and unexpected output
files. Package verification checks hashes, the embedded asset inventory and the exact
visible notice text. With `--sdk`, packaging verifies the retained SDK and adds
the same complete Wasm runtime notice closure used by ordinary packages; its
manifest records the SDK recipe and manifest identity.

Use `gui/tests/queue_test.mjs` for byte accounting, retry and rejected-input
settlement. Use `gui/tests/worker_test.mjs` for deterministic lifecycle/bounds cases and an
actual Worker responsiveness check. `gui/tests/browser_test.py --mode wasm-offline`
qualifies the same operations through both an ordinary Wasm host and the direct
local HTML package. It compares geometry, checks editing and accessible names,
executes the bounded task and a cancelled prompt, retains screenshots, rejects
HTTP resources in offline mode and joins browser processes before cleanup.
Browser/toolchain combinations still require execution evidence; the existence
of Wasm support alone does not establish compatibility with module Workers,
Blob imports or local-file restrictions.
