# Isolated browser rendering

[`createEmbeddedFrontend`](../gui/host/browser_embedding.mjs) places the retained
DOM renderer in an opaque sandboxed iframe. Trusted parent code owns the ordered
Client, native transport token or Wasm Worker, polling, resize, services, files,
download URLs, callbacks and application release. The child receives public
display state and narrowly typed UI/measurement capabilities. Application meaning
and final input authorization remain in the shared C++ boundary described in
[GUI integration](gui-boundary.md).

The embedding API always selects this isolated composition. Startup or protocol
failure closes it; there is no fallback to standalone rendering. The existing
standalone composition remains available for the demo/application launcher.

## Embedding API and launcher selection

Use the generated browser assets together; `browser_embedding.mjs` depends on
the generated child bundle and trusted host modules. Supply an accepted initial
transport state and the trusted exchange/release functions:

```javascript
import {createEmbeddedFrontend} from './browser_embedding.mjs';

const frontend = createEmbeddedFrontend({
  mount: document.querySelector('#application'),
  initialState,
  exchange: envelope => trustedTransport.exchange(envelope),
  release: () => trustedTransport.release(),
  status: (message, paused) => showHostStatus(message, paused)
});
await frontend.ready;
// When the embedding's lifetime ends:
frontend.close();
```

The return value is frozen and contains `frame`, `ready`, `close(reason?)` and
`retry()`. `ready` resolves after the initial document/channel bind; startup
closure rejects it. `close()` is idempotent and releases the trusted application
once. `retry()` retries a failed transport operation when the frontend is ready;
it does not create a new session or replay accepted actions after closure.

Options also include `host=globalThis`, `serviceHost=host`,
`startupTimeout=10000` milliseconds and `pollingInterval=25` milliseconds.
`serviceHost` is a trusted capability provider, described below. The parent
observes `mount` dimensions and sends bounded resize operations itself. It owns
polling and release; the child has no corresponding channel operations.

The launcher defaults to `standalone`. Select `renderer=isolated` in its query,
preserving any other required parameters such as `mode=wasm`, or open the offline
document as `software-foundation-wasm.html#renderer=isolated`. The only accepted
values are `standalone` and `isolated`. Duplicate selectors across query and
fragment fail even when their values agree. Arbitrary renderer URLs, module
sources and sandbox overrides are not launcher inputs. Composition is selected
before the standalone renderer is dynamically imported.

## Parent and child authority

The trusted parent imports [`browser_client.mjs`](../gui/host/browser_client.mjs)
and [`browser_services.mjs`](../gui/host/browser_services.mjs). It never imports or
evaluates `renderer_dom.mjs`, including that module's top-level code. The generated
child bundle is inert string data in the parent. The compatibility `renderer.mjs`
wrapper re-exports the split modules for existing standalone callers; the
dependency direction does not bring renderer evaluation into the isolated parent.

The iframe has exactly `sandbox="allow-scripts"`, with no same-origin, form,
popup, download or top-navigation permission. Its static `srcdoc` includes the
canonical generated script and style, plus escaped startup metadata. Application
text, filenames and service values never enter its markup assembly. The child
policy uses `default-src 'none'`, the exact script SHA-256, inline styles required
by the retained renderer, and `img-src data:`. Connections, workers, nested frames,
objects, base URLs and form submission are disabled. Hosted parent policy admits
the exact child hash needed by inherited `srcdoc` policy; offline packaging has
its own parent policy.

[`tools/browser_bundle.py`](../tools/browser_bundle.py) assembles a fixed reviewed
module graph after the complete patch chain. It checks edges, exports, order and
lexical module wrappers; unsupported imports/re-exports, dynamic imports, cycles
and HTML terminators fail generation. It is a bounded assembler for these assets,
not a general bundler or dependency downloader. The bundle hash covers canonical
script bytes, including the child entry point.

A fresh cryptographic generation identifies each embedding. The initial child
document creates a MessageChannel and transfers one endpoint in its ready
announcement. The parent requires the exact `frame.contentWindow`, opaque origin,
generation, protocol and message shape, waits for the initial load, then connects
over that endpoint. The child's `bound` response completes startup. The value
`origin === 'null'` alone is not authentication. A replacement document cannot
obtain the retained endpoint through a late window message. Global startup
listeners are removed when bound; startup/load/bind deadlines fail closed.

## Delegated input and bounded state

The protocol is `foundation-renderer-v1`. Child requests carry typed UI intents:
activate, checked, edit intent, choose/select/activate-record, submit/action,
pointer/focus/selection/scroll, popup/list input, page and shortcut. Measurements
reply only to currently outstanding measurement IDs. There is no child operation
for a raw Client envelope, service result, file begin/chunk/finish/read, polling,
resize, close or arbitrary host method.

The parent validates exact shapes/types, finite geometry, size, current widget
key/generation, kind and eligibility before accepting it for transport and again
before first dispatch. Measurement batches contain at most 512 unique currently
requested IDs. C++ remains the final authoritative interaction policy. A normal
stale intent is rejected without sending it and receives current state. Malformed,
oversized, duplicate, out-of-order or unauthorized channel input closes the
embedding with a bounded host error.

The Client retains its 1 MiB operation and 8 MiB total queue limits, immutable
accepted operations, adjacent compatible coalescing, action ordering barriers
and exact retry identity. Channel queues additionally limit pending requests to
128. Edit intents reserve the full possible 1 MiB operation; only the parent
builds their edit base from current accepted state. The renderer's existing
fourth `document` argument remains compatible; its fifth options argument can
supply `sendEdit(key, value)` for the typed child path.

State delivery permits one outstanding packet and one latest pending snapshot,
with bounded completions. Each public snapshot is limited to 64 MiB to preserve
the existing pixel/image presentation profile. The child accepts authoritative
state before resolving dependent completions, while visual painting may remain
deferred. Service, close, error and completion ordering retain their meaning
across visual coalescing. An unacknowledged state packet fails after the bounded
channel deadline. Service/modal transitions cancel child pointer capture as well
as authoritative C++ pointer ownership.

Navigation, parent `pagehide`, disposal, startup/protocol failure and restart
revoke the generation, abort services, reject pending work, stop polling and the
resize observer, close ports/client/presentation resources and remove the frame.
Late replies cannot mutate a replacement application. Wasm transport retains its
close acknowledgment followed by termination on its one-second timeout. A new
frontend requires a fresh session; closed work is not replayed.

## Service ownership and revocation

Only an accepted authoritative application service request starts a parent
service. The child cannot supply a service descriptor or file path. The parent
owns prompt DOM, file selection, File/Blob objects, chunks and download URLs.
Default content services preserve the 64 KiB UTF-8 document bound, ordered 4 KiB
chunks, atomic import and explicit Download gesture described in
[bounded content services](gui-boundary.md#bounded-content-services).

An active job binds its session epoch, ID, kind and immutable complete request
descriptor to an AbortController. Changing a descriptor revokes the old job even
when its numeric ID stays the same. Currentness is checked before opening a
dialog/provider, before each file operation, after asynchronous results, before
creating/clicking a download URL and before completion queueing and first
dispatch. Once an envelope has been prepared, transport retries preserve its
identity and do not repeat those callbacks. Withdrawal or closure cleans up
dialogs, temporary resources and owned download URLs.

A trusted `serviceHost.executeService(descriptor, scopedHost)` callback may
replace the default provider. It receives a frozen copied authoritative
descriptor and scoped `signal`, `isCurrent()`, `exchange()` and `ownDownloadURL()`
capabilities. It must honor cancellation/currentness for its own effects. This
hook is parent authority; renderer-supplied values do not grant path access or
permission to use arbitrary host services. The native file-pipe route retains
its existing authority boundary and adds no HTTP file-path endpoint.

Revocation prevents new dispatch and late parent state or completion acceptance.
An operation first dispatched while authorized may still finish after revocation.
It cannot undo an effect that committed while the request was valid, such as a
download handed to the browser or a completed native destination replacement.

## Offline package and legacy compatibility

Output names remain `software-foundation-wasm.html`, `web-manifest.json` and
`manifest.sha256`. The same HTML contains standalone and isolated compositions.
New packages use schema 3 and bind both modes, protocol, sandbox, exact child CSP,
canonical bundle hash, child input digests, new module hashes, notices and final
HTML identity. `--source-root` additionally binds the complete application source
snapshot. Generate through the ordinary CMake package target; manual packaging
and verification retain their existing CLI:

```sh
python3 -B tools/package_wasm.py --verify --output /owned/browser-package
```

Schema-1 and schema-2 packages verify with their original inventories and policies.
They contain no isolated-renderer claim. Native import accepts source-bound
schemas 2 and 3 only, with an independently supplied exact manifest SHA-256 and
the matching complete source identity; an unbound schema-3 package may verify
independently but cannot be imported into a native package. The
[native import command](building.md#prerequisites-and-working-commands) requires
a fresh tree when the selected package identity changes.

## Threat scope and qualification

The isolated renderer cannot directly read parent DOM/globals or transport
tokens, invoke parent services, create parent download URLs or send raw protocol
operations through its delegated channel. A compromised child can still forge
a currently eligible UI intent and read data deliberately displayed to it.
This boundary does not prove a human click, conceal displayed data, provide
general CPU/memory confinement or prevent every possible network exfiltration.
In particular, the sandbox allows navigation of the child's own frame. A later
load closes its channel, but observing that load does not prove the navigation
request was prevented. Message limits apply after browser delivery and do not
bound allocations performed by a malicious sender before delivery.

Qualification requires actual Chromium and Firefox execution in standalone and
isolated hosted/native, HTTP Wasm and direct-file Wasm paths. Malicious-child
fixtures must use the production assembler, sandbox and bridge, prove their code
ran, and independently observe parent state/authority and network canaries with
positive controls. Node mocks, source checks and CSP strings supplement that
execution; they do not establish browser isolation. Schema-3 release evidence
must include the required isolation feature checks bound to current module and
policy hashes. [Validation](validation.md) records executed evidence and omissions.
