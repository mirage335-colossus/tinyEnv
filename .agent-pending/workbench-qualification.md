# tinyEnv workbench qualification

This record concerns the optional desktop workbench added to the working tree
based on commit `cd7d264b2859624611ce234fb58ea6e4c1faedab`. Focused integrated
development checks and the Linux FLTK smoke passed; evidence below establishes
only its named source and scope. It does not add application-release, SDK or
binary-publication work.

The expanded Code tool handoff was checked on 2026-10-08 at source
`18f404cdc7d01918e425741dc0b2a46806eddcb0e98d87dc8cb5a7a429d7b0d1`.
Implementation is complete in this scope. Selector shows **Code**, retaining
the existing per-chat `selector.calculations` state and `calculate` tool name.
The bounded numeric interpreter now supports custom functions, `while` loops,
bit operations, slices and scalar array updates. Explicit input accepts only
finite numeric/boolean values and nested lists, privately copied. There is no
image decoder, attachment/file access, import or general Python execution.
Source rejects quotes, backslashes, non-ASCII and other unsupported controls
before parsing; combined evaluation nesting and existing resource limits bound
execution. Numeric pixel algorithms check their own dimensions/channel ranges.

- The supported optimized build and all fifteen workbench CTests passed,
  including 506 Python cases with zero skips. Command:
  `CMAKE_PREFIX_PATH=.agent-work/workbench-integration/fltk-dev ./build.sh
  workbench test release --backend fltk --build-dir build/workbench-code-v14
  --build-jobs 4 --test-jobs 2`. It took 64.398 seconds with source unchanged.
  Exact inputs, command, internal results and artifact hashes are retained in
  `.agent-work/code-tool-root-v14/consistent/`. Thirteen copied service/helper
  modules match their sources; the generated path module is accounted for in
  `runtime-copy.json`.
- Seventeen private-Xvfb checks passed: production smoke, native Code label
  and help, an older state defaulting off, opt-in autosaved before closing,
  restart and per-chat separation, custom IIR output, encoded-string rejection
  followed by raw-pixel correction, bounded tool accounting and saved/drawn
  replies. The copied production runtime used a guarded fake provider.
  Screenshots were reviewed. Evidence is in `.agent-work/code-native-v14/final/`,
  `host-final/` and `.agent-work/code-tool-root-v14/native-final/`. Source and
  native inputs remained unchanged. All owned app, worker and display
  processes finished; synthetic workspaces, display socket and lock were removed.
- Independent boundary review passed 181 synthetic probes with zero skips.
  Algorithm acceptance covers biquad impulse, step and frequency responses,
  pixel convolution/components, finder patterns and GF256/Reed-Solomon
  primitives. These establish no complete QR decoder or image-recognition
  quality. Root's 21 focused runtime/algorithm cases and the extracted
  documentation example also passed. Original identities and limits remain
  under `.agent-work/code-security-v14/`, `code-algorithms-v14/`,
  `code-language-v14/`, `code-docs-v14/revised-depth/` and
  `code-tool-root-v14/focused/`.
- Review found and repaired composed host-stack exhaustion by adding the
  combined evaluation-depth cap. Source-length and argument-cardinality checks
  now precede broader traversal. Preliminary probe-harness failures and the
  pre-repair nesting failure remain preserved with their original identities;
  none are counted as passing evidence.

The executable is `build/workbench-code-v14/tinyenv-workbench-fltk`, SHA-256
`fcfc64674c3c280e16a3f081ddea68d3b4784ac24da1139e111eb30bda207451`.
Generic GUI inputs remain in the retained group below. All checks were offline
and synthetic; no real chat, user desktop, credential or external service was
used. Live model algorithm quality, broad platform/window-manager and release
qualification remain unverified and await explicit qualification authorization.
Next manual action: launch `./build/workbench-code-v14/tinyenv-workbench-fltk`,
enable **Selector → Code**, then request a computation on explicit numeric data.
This receipt is a subsequent documentation-only change.

The persistent Scribble workspace handoff was checked on 2026-10-08 at source
`cee34c467fbc20b58ecee49b3ecc9bc2a82af7eab42dfb5c6f430561a9920cb7`.
Implementation is complete in this scope. Setup, Tasks and Results retain
per-chat drafts and task records. Explicit Exit keeps running work; Escape does
not leave the workspace or cancel a task. Reopening starts no work. Supported
POSIX builds save completed annotations and research context for explicit Resume;
an interrupted request whose response was not saved may repeat. The call budget
applies per invocation, not across all attempts. Evaluations can be retried as
new records. Windows fresh builds remain available without durable Resume; the
existing macOS worker limitation remains.

- The supported optimized build and all fifteen workbench CTests passed,
  including 484 Python cases with zero skips. Final command:
  `CMAKE_PREFIX_PATH=.agent-work/workbench-integration/fltk-dev ./build.sh
  workbench test release --backend fltk --build-dir
  build/workbench-scribble-mode-v13 --build-jobs 4 --test-jobs 2`.
  It took 37.109 seconds with source unchanged. Exact inputs, commands, logs and
  artifact hashes are in
  `.agent-work/scribble-mode-root-v13/consistent-ui-fixed/`.
- Nineteen focused private-Xvfb checks passed, including production smoke,
  actual typing, three tabs, saved setup, harmless Escape, Exit retaining the
  same worker, Pause, paused restart without launch, and explicit Resume using
  one saved annotation and generating only the remaining two. The copied
  production runtime and checkpoint implementation ran against a guarded fake
  provider. Exact source bytes, unchanged task request, three artifact hashes,
  separate Results and reentry were verified. Screenshots were reviewed.
  Evidence is in `.agent-work/scribble-native-v13/ui-fixed/`, `host-ui-fixed/`
  and `.agent-work/scribble-mode-root-v13/native-ui-fixed/`. All owned app,
  worker and display processes joined; synthetic workspaces, display sockets
  and locks were removed. Active shutdown recovery is covered by application
  fixtures, and research reuse by runtime fixtures, not by this native scenario.
- Focused storage review passed fifteen offline adversarial probes, including
  process death during checkpoint and final-artifact publication, exact input
  identity checks, lock contention and preservation of foreign output. Runtime
  fixtures verify completed-chunk and research reuse. Independent state,
  integration and UI reviews passed. Their original identities and limitations
  remain in `.agent-work/scribble-resume-review-v13/`,
  `scribble-runtime-v13/`, `scribble-state-v13/`, `scribble-ui-v13/` and
  `scribble-integration-review-v13/`.
- Initial integrated runs exposed two test-fixture defects: differing parent
  and child module identities, and a same-byte rewrite that did not reliably
  change file identity. Fixtures now preserve the exact adapter identity and
  use a verified replacement inode; product checks were not weakened. The
  first native run then exposed focus loss after the first typed character.
  The repaired UI keeps fields and ancestor panels stable while separately
  invalidating changed task actions and explicitly reset setup. Its regression
  and the unchanged native input sequence pass. Original failures remain in
  `consistent/`, `consistent-fixed/`, `native-final/` and the owning agents'
  repair records; none are relabeled as successful checks.

The executable is `build/workbench-scribble-mode-v13/tinyenv-workbench-fltk`,
SHA-256 `1df32ad770cf25e3674cb29ea99a4247f971015d3bfcde7942433c34f84cb743`.
Generic GUI inputs are unchanged from the retained group below. All new checks
were offline and synthetic; no real chat, user desktop, credentials, account or
external service was accessed. Live provider quality/scale, power-loss durability,
broader platform/window-manager and release qualification remain unverified.
Next manual action: launch
`./build/workbench-scribble-mode-v13/tinyenv-workbench-fltk`, then open
**Build Scribble / Ref…** from Selector or Files. This receipt is a subsequent
documentation-only change.

The Scribble discovery, restricted calculations and Sidebar handoff was checked
on 2026-10-08 at source
`ed577c6037b6d8d495e8366a9c6e7ac3d23b775f8f64fcd024dbd77e7dc6efe2`.
Implementation is complete in this scope. Selector and Files now expose the
builder directly. It starts with local indexing and explicit source inputs;
AI annotations require an explicit mode/model, and evaluation cannot inherit
hidden research settings. Calculations is a separate per-chat opt-in for a
bounded numeric AST language, with no general Python or I/O capability. Sidebar
visibility persists globally, reclaims center width and preserves chat drafts.

- The supported optimized build and all fifteen workbench CTests passed,
  including 459 Python cases with zero skips. Command:
  `CMAKE_PREFIX_PATH=.agent-work/workbench-integration/fltk-dev ./build.sh
  workbench test release --backend fltk --build-dir build/workbench-tools-v12
  --build-jobs 4 --test-jobs 2`. It took 60.136 seconds with source unchanged.
  Commands, inventories, logs and hashes are retained in
  `.agent-work/workbench-tools-root-v12/consistent/`.
- Fourteen focused private-Xvfb checks passed, including production smoke,
  actual Sidebar hide/show/restart geometry and draft retention, both visible
  builder entries, local construction of the three verified artifacts, and
  an explicit calculation tool round trip through an in-memory fake provider.
  The copied production runtime and calculator were used; no provider,
  credentials or research loader was allowed. Source bytes, hashes and output
  provenance were verified. Screenshots were reviewed. Evidence is in
  `.agent-work/workbench-native-v12/final/`, `host-build/` and
  `.agent-work/workbench-tools-root-v12/native-final/`. All owned application,
  worker and display processes joined; temporary source files, display sockets
  and locks were removed. The optional 900x640 native scenario was not run.
- Focused interpreter and runtime reviews passed 130 adversarial interpreter
  cases and 109 runtime assertions. They cover complete forbidden-syntax
  rejection, resource limits before expensive work/output, strict opt-in,
  shared tool budgets, bounded correction errors and withheld malformed tool
  envelopes. UI/core/docs review and documentation/whitespace checks passed.
  Evidence is under `.agent-work/calculation-review-v12/`,
  `calculation-runtime-v12/` and `workbench-review-v12/`. Initial focused UI
  runs failed because Sidebar restoration tried to scroll non-scrollable
  controls; the corrected scrollable-only restoration passed its discriminating
  fixtures and the final native checks. Original failures remain recorded.

The executable is `build/workbench-tools-v12/tinyenv-workbench-fltk`, SHA-256
`30595509f4c86cd3d630a0be5450fa107d7c9e2170bc6e95cca40127f1bcf486`.
Generic GUI inputs are unchanged from the retained v11 group below. All new
checks were offline and used synthetic data; no user desktop, real chat,
credential, account or external service was accessed. Live provider/tool
adoption, AI enrichment quality/scale and broader platform/window-manager or
release qualification remain unverified by this handoff. Existing earlier
receipts retain their own scope. Next manual action: launch
`./build/workbench-tools-v12/tinyenv-workbench-fltk`; use Selector or Files for
the builder, Selector for Calculations and the bottom-bar Sidebar checkbox.
This receipt is a subsequent documentation-only change.

The graphical-table, quiet-divider and native streaming-follow handoff was
checked on 2026-10-08 at source
`891a25a76bd544224c09cf7fbba3b738f1bf5316889bb3966cd3944ff6592df8`.
Valid bounded tables now have drawn rules, bold headers and selectable native
cells. The idle marker is a passive one-pixel line with no timer or transcript
content; successful Send/Retry hides it until the chat is idle again. Streaming
batches at 16 ms, permitting each normal 20 ms desktop poll to update. The
current-layout FLTK scroll operation reports its actual applied position;
pending snapshots retain raw requests until native layout. Following now
survives wrapped-range growth and clamping, preserves deliberate scroll-back,
and resumes at the reachable end. This exercised implementation is complete.

- The supported optimized build and all fifteen workbench CTests passed,
  including 433 Python cases with zero skips. Final command:
  `CMAKE_PREFIX_PATH=.agent-work/workbench-integration/fltk-dev ./build.sh
  workbench test release --backend fltk --build-dir
  build/workbench-rendered-v11-final --build-jobs 4 --test-jobs 2`.
  The final incremental check took 12.818 seconds with source unchanged;
  the preceding fresh build took 54.858 seconds. Exact commands, source
  inventories, logs and binary hashes are in
  `.agent-work/chat-rendered-root-v11/consistent/` and `stable/`.
- Focused generic native checks passed: 96 current-layout combinations plus
  staged requests and the original 16 long-wheel scenarios, wheel chaining
  and native interaction. They cover actual position before synchronization,
  Unicode, LF endings, wrapping, one-row viewports, same-length replacement,
  finite extreme requests, caret/focus and every ancestor's existing damage.
  The original adapter fails the new applied-position assertion. Evidence is
  in `.agent-work/chat-native-scroll-contract-v11/receipt.md`; all private
  display/process resources were cleaned up. App fixtures also discriminate
  immediate upward input after growth, paused growth, actual-end resume and
  callback-before-timer ordering.
- Production smoke and nine integrated private-Xvfb checks passed with exactly
  two local fake workers. All fifteen captured table candidates were checked:
  fourteen graphical tables, plus the intentionally literal fence containing
  extra prose. Six growing prefixes and the timed append burst kept their last
  glyph fully within the viewport. Manual scroll-back, returning to the bottom,
  continued output and foreign-window focus passed. The one-pixel idle line
  persisted past five seconds, disappeared on next Send and stayed out of
  saved text/state. Screenshots were reviewed. Evidence is in
  `.agent-work/chat-native-v11/complete/` and `host-final/`; all owned workers,
  application and Xvfb joined, with sockets and locks removed.
- The bounded 24-fragment, 20 ms synthetic burst produced 21 distinct naturally
  painted prefixes, with no settled-bottom failures. Independent raw first-paint
  analysis measured 23.580 ms median / 24.948 ms maximum update intervals and
  16.424 ms median / 26.808 ms maximum emitted-to-first-paint delay. All 24
  unpaused frame samples through the burst checkpoint showed the full tail.
  This is a local diagnostic, not a live-provider or general frame-rate guarantee.
  Its observer adds work; the original receipt's 80 ms last-prefix observation
  includes a gated hold and is not first-delivery latency. The synthetic history
  includes copied table examples but is not a complete performance replay of the
  user chat. Independent analysis is in `.agent-work/chat-native-v11-review/`.

The final executable is
`build/workbench-rendered-v11-final/tinyenv-workbench-fltk`, SHA-256
`7f8ba0964fb6efc6d5f27019eda08f1a25707530342479e6a58b6f5515950267`.
Retained GUI group
`00044ea5438248b32fac301633cc2342efb99387b649664f7851dc264b6e2cd7`
was exported and verified through the supported source-group tool from the clean
pinned upstream revision `7a704f73e563a167ea335dd23ccd9f383ebec274`.
The upstream tree and license are unchanged. This corrects the generic adapter,
with application behavior remaining on the shared workbench side. Native checks
loaded the system FLTK 1.3.11-2 runtime; the development prefix supplied 1.3.8
headers/link input. Exact resolved paths and hashes are retained in
`.agent-work/chat-rendered-root-v11/native-runtime-identity.json`.

Earlier v11 attempts remain failures with their original identities. Initial
fixture clipping and wheel-placement prerequisites were corrected before the
native run exposed a real hidden-tail failure at the third prefix; explicit
wheel input made that tail visible. The original scrollbar maximum includes an
unreachable row, so final assertions require the actual full last glyph and
outer end, not equality to that advertised limit. A subsequent supported run
passed its workbench suites but failed source stability because the separate
generic test changed during compilation; it was rerun after all sources froze.
A real ancestor-damage defect and a later fixture ordering error were also fixed
and rechecked. These receipts and rejected observation-cache prototypes remain
under the corresponding v11 `.agent-work/` directories; they are not passes.
Independent final source review and documentation/whitespace checks passed.
This qualification receipt is a subsequent documentation-only change.

Current chat bytes stayed unchanged. All automated checks were offline; no
provider, search, catalog, Kiwix, real credential, account or user-desktop operation
ran. The existing preview bounds and literal unsupported Markdown remain in
force. Near-limit throughput, synchronous saves of very large histories,
live-provider cadence and broader platform/window-manager/release qualification
remain unverified. The earlier isolated 2 MiB save measurements identify a
separate synchronous-save scaling limit, not a fixed delay in every reply.
Next manual action: launch
`./build/workbench-rendered-v11-final/tinyenv-workbench-fltk` and reopen the chat.
Extensive qualification awaits an applicable explicit request. Earlier receipts
retain their original source identities and limits.

The table, streaming and completion-cue handoff was checked on 2026-10-08 at
source `e06de8a599b4d48e957a3b41388981350a2602f729d5805eff3f46ba8eab5390`.
Bounded pipe tables, including table-only `markdown` fences, now render aligned
selectable ASCII grids. Runtime prose fragments no longer wait for another
provider callback, and visible UI updates batch at 33 ms. A successful nonempty
saved reply shows `--- Reply complete ---` for five seconds. The cue never enters
stored history or provider context. Implementation is complete in this scope.

- All fifteen supported workbench CTests passed, including 433 Python cases
  with zero skips, through `./build.sh workbench test dev --backend fltk
  --build-dir build/workbench-tables-v10 --build-jobs 2 --test-jobs 2` with the
  retained FLTK prefix. The complete command took 65.169 seconds; source stayed
  unchanged. Logs, identities and artifacts are in
  `.agent-work/chat-tables-root-v10/final/`.
- Focused fixtures check table bounds, literal fallback, escaped characters,
  fence/message boundaries, same-length disk reload, source/cache freshness,
  inactive streaming, paused readers and completion success/expiry/exclusions.
  The captured reported chat renders all five tables and both diagrams within
  the unchanged preview bounds; its existing 128-block cap still produces an
  omission notice for earlier content. Original chat bytes remained unchanged.
- A synthetic sparse fragment previously held about 310 ms until completion
  now forwarded in 0.099 ms in the same narrow runtime probe. Paired private
  12 KiB MemoryAdapter profiles showed 70 versus 35 publications with similar
  per-frame costs. These are local diagnostics, not live-provider or native
  frame-rate guarantees. Receipts are in `chat-stream-audit-v10`,
  `chat-stream-runtime-v10`, `chat-stream-ui-v10` and `chat-tables-markdown-v10`
  under `.agent-work/`.
- Production smoke and nine private-Xvfb native checks passed: all five copied
  tables plus an unfenced table, successive painted prefixes before final,
  paused inner/outer scroll and foreign-window focus, successful cue and actual
  pixel clearing after expiry, and no cue on error/cancel. Exactly three local
  fake workers ran. Evidence is in `.agent-work/chat-native-v10/final-repaired/`
  and `host-build/`. All owned processes joined and display sockets/locks were
  removed. Reviewed screenshots confirm readable columns and the transient cue.

The first native attempt passed both table checks and smoke, then stopped before
any worker because its observer incorrectly required transcript-only buffer data
from an ordinary model input. That prerequisite was repaired; transcript paint
assertions and product bytes were unchanged. Its receipt remains in
`.agent-work/chat-native-v10/final/`. Focused fixture setup failures and their
discriminating corrections are retained in the component receipts.
Independent source review, documentation and whitespace checks passed.
The binary `build/workbench-tables-v10/tinyenv-workbench-fltk` has SHA-256
`c67e3330e472f49b399b72a3c1bc1fa0c4e40d4582c8412e13e4b3054d6ef836`.
Generic GUI inputs/group `85a501e40b9e31d4e6c1c7f82fe6bc2e69391534e27d3e0bf34c645de50ce622`
are unchanged. This receipt is a subsequent documentation-only change.

Large-history checked saves remain synchronous: an illustrative 2 MiB Debug
fixture still measured approximately 55–59 ms in that stage. Near-limit output
throughput and live provider cadence remain unqualified. The preexisting,
unmeasured cancellation case involving a paused non-tail reply block is retained
with a focused next probe in `.agent-work/chat-review-v10/review.md`; the native
run verified the active tail and cue expiry, not every cancellation position.
No provider, search, catalog, Kiwix, real credential, account or user-desktop
operation ran. Broader platform/window-manager and release qualification remain
unverified pending the applicable explicit request. Next manual action: launch
`./build/workbench-tables-v10/tinyenv-workbench-fltk` and reopen the saved chat.
Earlier receipts retain their original identities and limits.

The richer Markdown, compact Retry and image-input handoff was checked on
2026-10-08 at source
`57ea0087d00244380fb9a99e48c918cc3863642fcaded2db5875224a04d14551`.
Nested quoted fences preserve the reported ASCII table, standalone strong labels
are bold and thematic rules display a compact divider. Mixed inline markup stays
literal. Retry now shares the Cancel/Send row. Explicit PNG/JPEG attachments use
checked managed snapshots, per-chat drafts and original-image Retry; normal chat
supports image-only submissions. All three provider adapters serialize images.
Implementation is complete in this bounded scope.

- All fifteen supported workbench CTests passed, including 431 Python cases with
  zero skips, through `./build.sh workbench test dev --backend fltk
  --build-dir build/workbench-rich-v9 --build-jobs 2 --test-jobs 2` with the
  retained FLTK prefix. Frozen source inventories, commands, logs and artifact
  hashes are in `.agent-work/chat-composer-root-v9/final/`.
- Offline fixtures check immutable image storage, missing/tampered data, limits,
  metadata compatibility, draft/Retry/Undo behavior, stale path-dialog replies,
  image-only requests, provider wire formats, streaming and agent budgets. The
  complete reported chat also passed a captured passive-renderer probe: 68
  blocks, the exact ASCII table, six bold example labels, a divider and both
  diagrams. No provider request was needed.
- Production `--smoke-test` and eight private-Xvfb native checks passed. Actual
  Files selection attached a synthetic PNG, saved its immutable snapshot and
  displayed filename/Remove controls; later source mutation left the snapshot
  unchanged and Remove cleared the draft. Reviewed screenshots show readable
  nested formatting, the previous Mermaid graph and compact composer buttons.
  Receipts and linked inputs are in `.agent-work/chat-native-v9/final/` and
  `host-build/`. All owned processes joined and display sockets/locks were
  removed. The original user chat and copied transcript stayed unchanged.

The first supported run passed fourteen suites but exposed a new test expecting
a stale path-dialog result to succeed after its draft changed. The corrected
fixture proves rejection, then opens a fresh selection; no production guard was
relaxed. Original evidence remains in
`.agent-work/chat-composer-root-v9/first-supported-fixture-failure/`.
Documentation checks and independent source review passed. The production binary
`build/workbench-rich-v9/tinyenv-workbench-fltk` has SHA-256
`a7d95c225a2352bc5c3361ac9c938a4138fefa2327b92a2992ef1c596ec5fd07`.
Generic GUI inputs and group
`85a501e40b9e31d4e6c1c7f82fe6bc2e69391534e27d3e0bf34c645de50ce622`
are unchanged and retain their earlier evidence identities.

Images are limited to four, 4 MiB each and 8 MiB combined. Agentic mode's
conservative encoded-byte budget is smaller; the workbench reports exhaustion
without inventing a model-independent image token estimate. Later ordinary
messages need explicit reattachment; Retry retains its original images. These
implemented limits, snapshot retention/export and the qualified POSIX import
boundary are documented in `docs/workbench.md`.
This receipt is a subsequent documentation-only change. All tests were offline;
no provider, search, catalog, Kiwix, real credential, account or user-desktop
operation occurred. Actual provider/model image inference, native path-dialog
interaction, browser/Rev appearance, broader platform/window-manager and release
qualification remain unverified and await an applicable explicit request.
Next manual action: launch `./build/workbench-rich-v9/tinyenv-workbench-fltk`,
reopen the saved chat and inspect Files / Attach image with a local PNG or JPEG.
Earlier receipts retain their original source identities and limits.

The saved-chat Mermaid fix was checked on 2026-10-08 at source
`de5b4bcade9bde51bce2ee991dfe88bafc15c32937e0d2199b371de933e33dc4`.
Both reported diagrams now render: unquoted colon/slash punctuation is accepted,
and bounded simple node styles are validated then discarded in favor of the
fixed native palette. Forward branch captions occupy separate target lanes;
short caption backings preserve the surrounding connector rails. Unsupported
syntax still falls back to literal text. Implementation is complete in this
exercised scope; full Mermaid compatibility is not claimed.

- All fourteen supported workbench CTests passed, including 408 Python cases
  with zero skips, through `./build.sh workbench test dev --backend fltk
  --build-dir build/workbench-mermaid-v8 --build-jobs 2 --test-jobs 2` using
  the retained FLTK prefix. Commands, logs, artifacts and unchanged source
  inventories are in `.agent-work/chat-mermaid-v8/final/`.
- Focused warning-clean C++ checks cover the two exact graph bodies, quoted
  Assistant/Streaming rendering, style validation/discard, passive capabilities,
  caption separation and visible branch rails. Preserved pre-repair input
  demonstrates the original parse rejection and later geometry failures.
- Production `--smoke-test` exited zero. Five native checks passed on private
  Xvfb at 1440x900, with an observer linked to the exact supported libraries.
  Both diagrams and distinguishing labels painted without literal fallback;
  manual screenshot inspection confirmed separated captions and visible rails.
  The original chat remained unchanged. All owned processes joined and display
  sockets/locks were removed. Evidence is in
  `.agent-work/chat-mermaid-native-v8/final-layout-fixed/` and
  `host-build-layout-fixed/`. Earlier native evidence remains in `final/`:
  its five rendering checks passed, but visual review exposed the overlapping
  captions and erased rails that prompted this repair.

The production binary `build/workbench-mermaid-v8/tinyenv-workbench-fltk` has
SHA-256 `24ba5324cf5eb5f009e994f69626b87e63e6fb57978dfef5f91defb6c686849a`.
The generic GUI inputs are unchanged; group
`85a501e40b9e31d4e6c1c7f82fe6bc2e69391534e27d3e0bf34c645de50ce622`
retains its earlier evidence identities. Documentation and whitespace checks
passed. This receipt is a subsequent documentation-only change. No provider,
search, catalog, Kiwix, real credential, account or user-desktop operation ran.
Live provider behavior, actual browser appearance, native Rev, window-manager,
broader platform and release qualification remain unverified and await the
applicable explicit request. Next manual action: launch
`./build/workbench-mermaid-v8/tinyenv-workbench-fltk` and reopen the saved chat.
Earlier receipts retain their original source identities and limits.

The chat-response handoff was checked on 2026-10-07 at source
`4944f5bfde664b83449845e5ec89532fa0f9073b273737378f7de8d52a6f2b91`.
Common bounded Mermaid flowcharts now accept labeled edges, quoted punctuation,
plain comments and rounded-box aliases for circle/stadium syntax. Unsupported
syntax remains literal. Main and split readers follow new text, pause when
scrolled up, and retain their positions independently. Send/Retry resumes the
main reader. A stationary corner ring marks a pending or streaming reply.
Implementation is complete in the exercised scope.

- All fourteen supported workbench CTests passed, including 408 Python cases
  with zero skips, through `./build.sh workbench test dev --backend fltk
  --build-dir build/workbench-response-v7 --build-jobs 2 --test-jobs 2` with the
  retained FLTK prefix. Commands, logs, artifact hashes and source inventories
  are in `.agent-work/chat-response-v7/final/`.
- Gated offline fixtures establish text delivery before completion through real
  urllib/HTTPResponse parsing over anonymous pipes, runtime subprocess output,
  native job polling and the rendered transcript. Provider and runtime code
  required no buffering change; the application previously left new reply text
  below the viewport. These checks do not establish live provider delivery.
- Production `--smoke-test` exited zero. Ten native consumer checks passed on
  isolated Xvfb at 1440x900, using a read-only observer linked to the exact
  supported application/core/adapter artifacts. They checked painted diagrams,
  waiting and streamed text before completion, inner and outer follow/scrollback,
  preserved draft and foreign-window focus, new Send and final busy-icon removal.
  The final paint checks require current native buffer/geometry and cleared
  toolkit damage; all 324 pixels of the old busy area returned to background.
  Exactly two local fake workers ran. Final receipts, reviewed screenshots and
  linked input hashes are in `.agent-work/workbench-response-native-v7/`, under
  `final-painted/` and `host-build-painted-fixed/`. All owned processes joined
  and isolated display sockets/locks were removed.

Native testing caught and repaired an actual paused-body scroll reset from 391
to zero on the next delta. The unchanged assertion now retains 391. It also
exposed an ambiguous labeled return arrow; the existing side rail now separates
that return from the forward edge. Original failures remain preserved in
`.agent-work/workbench-response-native-v7/`, along with fixture import and
screenshot-synchronization discriminators. An initial sandbox display failure
executed zero feature assertions. A scoped private-display run supplied native
evidence; the user desktop was never used.

The retained GUI group remains
`85a501e40b9e31d4e6c1c7f82fe6bc2e69391534e27d3e0bf34c645de50ce622`;
upstream revision remains `7a704f73e563a167ea335dd23ccd9f383ebec274`.
All 187 compared generic GUI inputs match the previous handoff, so its named
boundary evidence retains its original identity rather than being rerun here.
The production binary `build/workbench-response-v7/tinyenv-workbench-fltk` has
SHA-256 `6b5c9886d64ab0f7d6db37f3cfb09eefaa4fdcbc2438b51843467699658a3e2c`.
Documentation and whitespace checks passed. This receipt is a subsequent
documentation-only change. No live provider, search, catalog, Kiwix, real
credential or account operation occurred. Live provider behavior, actual browser
appearance, native Rev, broader platform and release qualification remain
unverified and await the applicable explicit request. The next manual action is
to launch `./build/workbench-response-v7/tinyenv-workbench-fltk` and inspect a
conversation. Earlier receipts retain their original source identities and limits.


The message-layout handoff was checked on 2026-10-07 at source
`cebf996d3173ae1eecf219d8c9871472bfe0b58f01a3f70c0352347f1146f01f`.
Only message titles are framed; user titles/bodies occupy the right lane and
assistant titles/bodies the left. Body text retains native selection, copying
and scrolling. The generic `text_frame` capability defaults to the previous
framed appearance. Implementation is complete in this exercised scope.

- All fourteen supported workbench CTests passed, including 405 Python cases
  with zero skips, through `./build.sh workbench test dev --backend fltk
  --build-dir build/workbench-layout-v6 --build-jobs 2 --test-jobs 2` with the
  retained FLTK prefix. Production `--smoke-test` exited zero.
- Eleven focused main-wrapper GUI checks passed with zero internal skips,
  covering the new shared, software, browser and native FLTK text-frame behavior,
  browser channel, contract, framebuffer, renderer, masking and retained-input
  verification. Exact commands, logs, artifact hashes and unchanged post-build/
  post-native source inventories are in `.agent-work/chat-layout-v6/final/`.
- Six native consumer checks passed on isolated Xvfb at 1440x900. The observer
  linked the frozen supported application/core/adapter artifacts and verified
  actual role-lane geometry, title/body perimeter pixels, readonly mouse
  selection, exact Ctrl+C/Ctrl+V output and wheel scrolling/restoration. The
  first probe's drag did not select text; corrected inside-padding coordinates
  and event spacing passed the unchanged selection/copy assertions on identical
  product bytes. The individual cause was not isolated. Both receipts and screenshots remain in
  `.agent-work/workbench-layout-native-v6/`, final result `final-padding/`.
  All owned processes joined and isolated displays were removed.

The retained GUI group is
`85a501e40b9e31d4e6c1c7f82fe6bc2e69391534e27d3e0bf34c645de50ce622`;
upstream revision remains `7a704f73e563a167ea335dd23ccd9f383ebec274`.
The production binary `build/workbench-layout-v6/tinyenv-workbench-fltk` has
SHA-256 `feedea783e38126b755b85a82833a3c8124f38727c0d478fbef32e9dfbba17b9`.
This receipt is a subsequent documentation-only change. All checks were offline;
no provider, search, Kiwix, real credential or user desktop was accessed.
Actual browser appearance/clipboard, native Rev, broader platform and release
qualification remain unverified and await the applicable explicit request.
The next manual action is to launch
`./build/workbench-layout-v6/tinyenv-workbench-fltk` and inspect a conversation.
Earlier receipts retain their original source identities and limits.

The streaming, passive Markdown and wheel-zoom handoff was checked on
2026-10-07 at source
`803d9eecae6e6e16f2f9390402d4b0d8f57bcefc2270a88eb1cbd193426bf1d5`.
The complete inventory and unchanged post-build inventory are in
`.agent-work/stream-v5/repaired/`. The retained GUI group is
`6b2860b8f38c14b56764144a0a8891aa177fec87953bf188b3be1aa7ac5c0a7a`,
with upstream revision unchanged at `7a704f73e563a167ea335dd23ccd9f383ebec274`.
This receipt is a subsequent documentation-only change.

- All fourteen supported workbench CTests passed, including 405 Python cases
  with zero skips. The command was `./build.sh workbench test dev --backend fltk
  --build-dir build/workbench-stream-v5 --build-jobs 2 --test-jobs 2`, using
  the retained FLTK prefix and Linux toolchain described below. Checks exercise
  SSE/NDJSON framing, incomplete output, callback redaction, output bounds,
  ordered native progress, per-chat autosave and final reconciliation, passive
  ASCII rendering, restricted diagrams, blank fresh/builder models and anchored
  wheel zoom. Production `--smoke-test` exited zero.
- Nine focused main-wrapper GUI checks passed at source
  `12f6a358fff7309e6796f7671f76f2564685e98a5f22e277c267f168d72c2b24`:
  `tools.gui_boundary`, `tools.gui_source_group`, and `foundation.gui.` checks
  `wheel-chaining`, `wheel-chaining-renderer`, `wheel-chaining-fltk`,
  `upstream.interaction`, `upstream.framebuffer`, `upstream.terminal`, `renderer`.
  The wrapper used `test dev --core-provider cpp --gui --gui-backends
  terminal,framebuffer,fltk,hosted-web --host-tests` with two build/test jobs.
  Only `workbench/ui/application.cpp` changed afterward; all relevant GUI inputs
  are identical. Exact commands, logs, zero-skip internal results and the input
  comparison remain in `.agent-work/stream-v5/final/` and `repaired/`.

- Twelve native consumer checks passed on isolated Xvfb at 1440x900, using a
  post-sync observational host linked to the frozen application/core/adapter
  artifacts. Actual mouse/key events checked ASCII escapes, inert flowchart and
  unsupported-syntax fallback, blank model preflight, anchored wheel zoom,
  visible/autosaved streaming before completion, exact final replacement and
  cancellation with draft preservation. A separate owned X window retained
  focus through 45 samples spanning a later delta and final completion. Exactly
  two local fake workers ran in the successful check. No window manager or
  user desktop was involved. The production executable
  `build/workbench-stream-v5/tinyenv-workbench-fltk` has SHA-256
  `2f4156156aef322ae8b35eaa7abe3f76b53cd344bb5d5f1f28e0bf7f4ca4d798`.
  Evidence and inspected screenshots are in
  `.agent-work/workbench-stream-native-v5/final-completed/`; linked artifact
  identities are in its parent `host-build/receipt.json`. All owned processes,
  display sockets and fake workers joined; implementation inputs stayed unchanged.

The initial application check caught a real stale-wheel defect: editing the
workflow did not retire the old canvas identity. A separate exact source revision
now invalidates old events, while drag/pan/zoom keep a stable identity. The
unchanged assertion passed after the fix. The original failed integration and
independent reproducer are retained, not relabeled as passes.

The first native observer attempt used an exact-color pixel threshold that did
not account for antialiasing; seven preceding checks passed but that run failed.
A second attempt failed during initial resize synchronization with zero feature
assertions executed. Both remain recorded. The final observer waits for one
consistent native/snapshot geometry, verifies interior foreground contrast and
uses a local gate to hold completion until the streaming screenshot is captured.
The final run used the same product and linked artifacts as the failed observers.

All automated work used synthetic files, credentials and local fake services;
no live provider/catalog, search, Kiwix, account-management or user-desktop
operation occurred. Live streaming, real browser geometry, broader desktop/
platform/Rev and release qualification remain unverified and await the applicable
explicit request. This is implemented work awaiting those checks, with no known
remaining failure in the exercised scope. Next manual action: launch
`./build/workbench-stream-v5/tinyenv-workbench-fltk`, select or enter a model in
AI (or keep user-saved defaults), send a message and inspect streamed output.
Earlier receipts below retain their original source identities and limits.

The toolbar, Retry and provider-default handoff was checked on 2026-10-07 at
source `734e9742af2d82b00117f0d3e711307738fb77c4c5b5fd213dd4164414cf1fba`.
The complete inventory and unchanged post-build/post-native inventories are in
`.agent-work/chat-v4/repaired/`. The retained GUI group is
`87ff6b2a8338bacb5d87778b85cb5a793fcf02ab12f56a5328b7c1e0eb0e5d9d`,
with upstream revision unchanged at `7a704f73e563a167ea335dd23ccd9f383ebec274`.
This receipt is a subsequent documentation-only change.

- All twelve supported workbench CTests passed, including 370 Python cases with
  zero skips. The command was `./build.sh workbench test dev --backend fltk
  --build-dir build/workbench-chat-v4 --build-jobs 2 --test-jobs 2`, using the
  existing retained FLTK prefix and Linux toolchain described below. Checks cover
  recorded-message Retry across restart/copy and repeated attempts, unchanged
  original context, draft preservation, current visible settings without Apply,
  missing-model preflight, stale Send rejection, new-chat defaults and bounded
  provider routing. Native production `--smoke-test` exited zero.
- Twenty-one focused main-wrapper GUI checks passed at source
  `9d4a1680cc296252564cd556023e9ba9e684cdbcaf067a4977c8a3f4373fbfd6`.
  Only the two workbench test fixtures changed afterward; all relevant GUI inputs
  remain identical. Coverage includes nonvisual commands, browser serialization
  and channel delivery, shared contract/input policy, native FLTK shortcuts,
  masking, composer scrolling and context input. Exact wrapper selections,
  source comparisons, logs and zero-skip internal results are retained in
  `.agent-work/chat-v4/final/` and `.agent-work/chat-v4/repaired/`.
- Nine native consumer checks passed under isolated Xvfb at 1440x900, using an
  observational host linked to the frozen application/core/adapter artifacts.
  Actual mouse/key events verified no visible Undo/Redo or filename bar,
  Ctrl+Z/Ctrl+Shift+Z/Ctrl+Y in composer and file editor, the fresh explicit model,
  and Retry with original prompt/mode/context plus current model and selectors.
  The old partial attempt and unsent draft remained intact. Exactly two local
  fake worker calls ran. The production executable
  `build/workbench-chat-v4/tinyenv-workbench-fltk` has SHA-256
  `917b86b2873db7576419c2da4fd7c65a95b7f6b0ababf9ca9ae369bdfa378676`.
  Evidence and inspected screenshots are in
  `.agent-work/workbench-chat-native-v4/final-explicit-model/`; linked input
  identities are in its parent `host-build/receipt.json`. Owned processes joined.

Initial failures remain recorded, not relabeled as passes. One application
fixture assumed a fresh config directory already existed; another edited a BOM
byte and accidentally made its transcript invalid UTF-8. The repaired fixtures
kept their assertions. The first native Retry probe correctly rejected its
synthetic model without the required publisher/model slash; correcting that
identifier passed on unchanged application bytes.

All automated work used synthetic files and local fake services. No live model,
catalog, search, Kiwix, real credential, account-management or user-desktop
operation occurred. Public provider-policy research informed the defaults;
current live route availability is unverified. Defaults use reviewed provider
routes and the no-training filter, without promising physical data residency or
absolute confidentiality; see [provider policy](../docs/workbench.md#providers-and-research).
Broader desktop/platform/browser/Rev and release qualification remain pending
the applicable explicit request. The next manual check is to run
`./build/workbench-chat-v4/tinyenv-workbench-fltk`, send a message, retain a new
draft and use Retry; older chats without a recorded submission first need a new
Send. Earlier receipts below retain their original identities and limits.

The model-filter, private-key and composer-scroll handoff was checked on
2026-10-07 at source
`680de9d233c4c03c9c1c68cf913b4bbb7124cd08f3820146d1260a215a1b663e`.
The complete inventory is `.agent-work/workbench-ai-v3/final/ready-source.json`;
post-build and post-native inventories confirm unchanged implementation inputs.
The retained GUI group is
`0274ca4fe43c9d4e822270aa2a197af3ecbfff3b9f8eeb9cb499561b90247193`,
with upstream revision unchanged at `7a704f73e563a167ea335dd23ccd9f383ebec274`.
This receipt is a subsequent documentation-only change.

- All eleven supported workbench CTests passed, including 366 Python cases with
  zero skips. The supported command was `./build.sh workbench test dev --backend
  fltk --build-dir build/workbench-ai-v3 --build-jobs 2 --test-jobs 2`, using
  `.agent-work/workbench-integration/fltk-dev` as `CMAKE_PREFIX_PATH` with the
  Linux GCC 14.2/CMake 3.31/Python 3.13.5/FLTK 1.3.8-5 environment. Coverage includes
  local model filtering and selection, retained catalogs, explicit masked-key
  Save/Remove, private storage permissions and checked writes, credential loading
  and trusted worker configuration outside request JSON. The native smoke exited
  zero. Documentation and source whitespace checks passed.
- Seventeen focused main-wrapper GUI tests passed with zero internal skips:
  `tools.gui_boundary`, `tools.gui_source_group`, and `foundation.gui.` tests
  `masked-text`, `masked-web`, `masked-renderer`, `masked-fltk`, `text-scroll-fltk`,
  `upstream.contract`, `upstream.adapter`, `upstream.interaction`, `renderer`,
  `shortcuts`, `interactions-fltk`, `context-input`, `context-web`, `context-fltk`
  and `fltk-host`. The wrapper used `test dev --core-provider cpp --gui
  --gui-backends terminal,framebuffer,fltk,hosted-web --host-tests` in the fresh
  `build/workbench-ai-v3-boundary` tree with two build/test jobs. Exact commands,
  logs, environment and source comparisons are in
  `.agent-work/workbench-ai-v3/final/checks.json` and adjacent logs.
- The composer failure was reproduced with one unbroken 24,000-byte token:
  native wrapping produced hundreds of rows, but generic label measurement
  clamped scrolling to zero. A native wheel moved 51px and queued synchronization
  reset it to zero. The adapter now clamps against native wrapped-row ranges and
  avoids queued no-op resets. The direct discriminator and sixteen permanent
  editable/readonly/caret/text-shape cases passed; evidence and exact patch-chain
  identity are in `.agent-work/text-scroll-v3/receipt.md`.
- The development executable `build/workbench-ai-v3/tinyenv-workbench-fltk` has
  SHA-256 `0a95263a21cb0fbf3aa212ece0c5fcd8947d87ecb14eb4525d6c845dc39f0e1f`.
  Fifteen native consumer checks passed on isolated Xvfb at 1440x900 using an
  observational host linked to the same frozen application/core/adapter artifacts
  and a local fake worker. Actual mouse/keyboard actions verified masked key
  entry, exact private save/remove, absence from chat/preferences, display-name
  and ID filtering, no matches, selection and Clear with only one explicit fake
  catalog call. Long-token composer scrolling remained monotonic through autosave
  and idle updates with both start/end carets; text, caret and widget identity
  were preserved. Final evidence is
  `.agent-work/workbench-ai-native-v3/final-post-sync/receipt.json` and the parent
  receipt. Product/fixture hashes stayed unchanged; all owned display, GUI and
  worker processes were joined.

Initial checks and observer mistakes are retained, not counted as passes. A local
runtime stub initially lacked the new optional constructor argument. Native
observation initially accepted unsettled resize geometry, expected a key file
without its defined trailing LF, and sampled a staged scroll projection before
NativeSession synchronization. The corrected observer runs after the unchanged
session sync, with the same exact text/caret/monotonic assertions; it forces no
extra presentation, sync, focus or edit. A separate discriminator confirmed that
the intermediate projected zero did not move the native viewport.

Every automated check used synthetic credentials and local fixtures/fake
services. No real credential, live provider/catalog, account-management,
external-search or Kiwix operation, or user-desktop action occurred. Public
OpenRouter documentation was reviewed separately: request-only prompt-injection
blocking using an ordinary inference key is not documented; normal AI controls
now explain that limitation and expose no account-management actions.

The implemented Rev fallback keeps the AI pane usable but displays masked entry
as unavailable. Its native masked fixture, real browser password/clipboard
behavior, other platforms, low-end hardware and complete release qualification
remain unexecuted; extensive qualification awaits the applicable explicit
request. Live OpenRouter anonymous catalog availability is also unverified.
The next manual check is to run `./build/workbench-ai-v3/tinyenv-workbench-fltk`
and try the user's own long composer text and normal desktop window management.
Earlier receipts below retain their original scope and identities.

The current conversation/AI-pane handoff was checked on 2026-10-07 at source
`b986ce3812e394465341bb6f3aa9f23480c4278af9ea2af3861621f67e7343d8`.
The complete inventory is
`.agent-work/workbench-conversation-v2/final/ready-source.json`; post-build and
post-native inventories confirm unchanged implementation inputs. The retained
GUI group is `e497265a3e451cce974a5a033739bd42b490379186aca8a099d8dffaf5b08302`,
with upstream revision unchanged. The Linux GCC 14.2/CMake 3.31/Python 3.13.5 and
retained FLTK 1.3.8-5 environment below was used. This receipt is a subsequent
documentation-only update.

- All ten supported workbench CTests passed, including 342 Python cases with
  zero skips. The command was `./build.sh workbench test dev --backend fltk
  --build-dir build/workbench-conversation-v2 --build-jobs 2 --test-jobs 2`,
  with the existing `.agent-work/workbench-integration/fltk-dev` prefix.
  Coverage includes global Tutorial/Developer persistence, read-only history,
  checked debounced autosave and recovery, scoped undo/send, composer-only agent
  execution, safe copies, targeted task actions, blank provider endpoints,
  ignored legacy retention flags and stable flow gestures. Native smoke exited
  zero. Exact commands, environments, source comparisons and logs are in
  `.agent-work/workbench-conversation-v2/final/`.
- Twelve selected main-wrapper GUI checks passed at their original source
  `d2dee493007495175492a398b7a7e1fd35f62fc96aaf131b63a2c6fea6c8a54e`:
  `tools.gui_boundary`, `tools.gui_source_group`, `foundation.gui.upstream.bitmap`,
  `foundation.gui.bitmap-copy`, `foundation.gui.fltk-bitmap`,
  `foundation.gui.context-input`, `foundation.gui.context-web`,
  `foundation.gui.context-fltk`, `foundation.gui.fltk-host`,
  `foundation.gui.upstream.interaction`, `foundation.gui.renderer` and
  `foundation.gui.browser-channel`. Four focused checks also passed at
  `717afc44b4fa5e0a168c0aa5acfd489cdf47664fcd779ca1a2b6a6b8678a4e48`:
  `foundation.gui.shortcuts`, `foundation.gui.interactions-fltk`,
  `foundation.gui.upstream.contract` and `foundation.gui.upstream.adapter`.
  The main-wrapper options and receipts are in the parent `checks.json` /
  `boundary.log` and `.agent-work/native-interactions-v2/receipt.md`.
  `final/reused-checks.json` confirms all relevant GUI inputs, fixtures,
  dependencies and environment stayed identical; only workbench application/
  fixture code and explanatory prose differ between these source identities.
- The rebuilt executable `build/workbench-conversation-v2/tinyenv-workbench-fltk`
  has SHA-256 `97e8d96c385140248a1461e567dec946b82befa3db51cbdfd3a8bee99adb6a9f`.
  Fourteen bounded native consumer checks passed at 1440x900 on isolated Xvfb,
  including global controls, readonly history, autosave, native undo/redo,
  flow-to-composer edits, a 40x20 canvas drag, wheel access and foreign-focus
  retention. The send/task portion used a small consumer linked to the same
  frozen application/adapter libraries and a local fake worker: held Ctrl+Enter
  invoked the worker exactly once, and Stop targeted the first chat's terminal
  while preserving the second chat's terminal and selection. A separate normal
  Ctrl+Enter tap produced one saved response with no error status. Holding the
  key past completion can repeat an empty send and show the normal empty-message
  diagnostic. Evidence: `.agent-work/workbench-conversation-native/final-observed/`
  and `normal-tap/`; source/link identities are in that directory's receipt.
- The same synthetic scrolling probe used a 2,305,085-byte wrapped chat and
  1000 native AI wheel ticks. Time for the next click to appear fell from 4.975
  seconds on the previous binary to 0.284 seconds on this binary; final total
  scroll/action time was 0.503 seconds and application CPU time 0.43 seconds.
  The app remained responsive and alive. The exact unchanged script and both
  original identities are recorded in
  `.agent-work/native-interactions-v2/long-prior-final-observed/` and `long-final/`.
  These Debug/Xvfb observations do not establish low-end hardware qualification.

Initial failures are retained, not counted as passes: a retained-copy fixture
incorrectly expected the original conflict warning to disappear; a conditional
Stop drag row changed canvas bounds and cancelled gestures; and an older file
fixture still required manual saving. Final tests check actual copied bytes/state,
persistent original conflicts, stable canvas bounds and autosave during file
operations. The first native task-menu observer used an incorrect glyph-count
threshold and stopped before clicking Stop; corrected bounded rectangle/glyph
recognition completed the same checks on unchanged binaries. All owned GUI,
worker, terminal and display processes were joined.

Every automated check used local fixtures/fake services. No live provider,
model-catalog, guardrail, external-search or Kiwix calls, private credential reads,
or user-desktop operations occurred. Live model refresh remains unverified even
though its blank-endpoint failure is fixed and covered offline. Actual window
manager/virtual-desktop behavior, low-end hardware and broader platform/backend/
release qualification remain unexecuted and await the applicable explicit
request. The next manual observation is to launch the executable above and check
minimize/restore, desktop switching, flow dragging and AI-pane scrolling on the
user's desktop. Earlier receipts below retain their original scope and identity.

The earlier usability handoff was checked on 2026-10-07 at source digest
`4bfebae513a3cfb098332662d83e24ad6f31448f27c83bfdf438221d6baf63a0`.
The complete inventory in
`.agent-work/workbench-usability/repaired/ready-source.json` remained unchanged
through the supported workbench checks, native smoke and final consumer probe;
`after-native-source.json` records the last comparison. This receipt is a later
documentation-only change. The same Linux toolchain/header prefix below was used
with retained GUI group
`54b72eb9eec987968798946733debb856c1951d647ad81ce14b41ae3778adfa0`;
upstream revision remains `7a704f73e563a167ea335dd23ccd9f383ebec274`.

- The supported workbench wrapper with `test dev --backend fltk --build-dir
  build/workbench-usability-ready --build-jobs 2 --test-jobs 2` passed all ten
  CTest entries, including 335 Python cases with zero skips. Coverage includes
  preview-only snippet selection/activation, explicit insertion, persisted
  Tutorial mode, conditional block fields, unset versus explicit numeric values,
  configured model persistence, explicit fake-worker model/guardrail operations,
  stale remote status, flow cache invalidation and bitmap-copy equivalence.
  Evidence: `.agent-work/workbench-usability/repaired/workbench.log` and
  `build/workbench-usability-ready/Testing/Temporary/LastTest.log`.
- Seven supported main-wrapper checks passed in
  `build/workbench-usability-ready-boundary`: `tools.gui_boundary`,
  `tools.gui_source_group`, `foundation.gui.upstream.bitmap`,
  `foundation.gui.bitmap-copy`, `foundation.gui.fltk-bitmap`,
  `foundation.gui.context-fltk` and `foundation.gui.fltk-host`. They used
  `--core-provider cpp --gui --gui-backends terminal,framebuffer,fltk,hosted-web
  --host-tests --build-jobs 2 --test-jobs 2`, with each name selected by `--test`.
  These passes retain their original source identity
  `364ded805552f6138c52746f37f75e60a6b306968a774b641b6941a122a62aed`.
  Only `workbench/ui/application.cpp` and `workbench/tests/application_test.cpp`
  changed afterward; their relevant GUI inputs, dependencies and environment
  did not change. Evidence: `.agent-work/workbench-usability/boundary.log` and
  its adjacent `ready-source.json` and `checks.json`.
- Native `--smoke-test` exited 0. The rebuilt executable
  `build/workbench-usability-ready/tinyenv-workbench-fltk` has SHA-256
  `981d3fc7fa2553188a716c4355871aaa7788b153b2a5c4545e32d89bc1738423`.
  At 1440x900, it passed all 16 isolated native consumer checks: relevant block
  fields and muted defaults, Tutorial mode initially off, drag with intermediate
  positions, exact workflow preservation on preview, one explicit insertion,
  configured model persistence, omitted optional numeric fields, native wheel
  access to Apply, readable guardrail help, foreign-focus and hidden-window
  retention. Evidence and inspected screenshots:
  `.agent-work/workbench-usability-native/final-observed/`; the receipt also
  confirms unchanged binary identity and joined process/display cleanup.
- Bounded synthetic renderer measurements used 30-node graphs, twelve pan
  frames per size, GCC 14.2 Debug and isolated Xvfb. Median native preparation,
  drawing and capture time decreased from 64.95 to 7.16 ms at 650x300 and from
  238.10 to 22.19 ms at 1200x600. All compared canvas pixels matched. These are
  illustrative local observations, not guaranteed frame rates or low-end
  hardware qualification. Exact scoped inputs, methods and retained logs are in
  `.agent-work/flow-performance/receipt.md` and `frozen-inputs.json`.

Initial failures remain recorded. The first workbench run passed nine of ten
entries but its application fixture attempted to activate an offscreen AI Apply
button. The fixture now scrolls through the public adapter and requires the whole
control to be visible before normal input delivery. Native screenshot review
also found clipped AI helper text; shorter labels and adequate wrapped-help
height repaired it. The initial normal-height consumer stopped after nine checks
because its button detector confused neighboring input borders; saved pixels
showed the pane had scrolled correctly. The corrected detector requires continuous
rectangle sides, and the final unchanged binary completed all 16 checks.
Failed and candidate evidence remains in the respective original directories.

All automated checks used local fixtures, fake providers/transports and no
external services. No live model catalogs, guardrail reads/updates, completions,
web searches or user desktop interactions ran. Live integration remains
unverified, including credential-less OpenRouter catalog availability; the
documented management controls require a separate management key and an existing
shared guardrail. No remote policy was changed by this work.

Actual window-manager/virtual-desktop behavior, low-end hardware and broad
backend/platform/release qualification remain unexecuted. The next manual
observation is to launch `build/workbench-usability-ready/tinyenv-workbench-fltk`,
drag a flow, switch applications/desktops, minimize/restore, and scroll the AI
pane. Extensive qualification still awaits an explicit request. Earlier receipts
below preserve their original identities and do not replace this current handoff.

The draggable flow canvas and native input-ownership refinements were checked
on 2026-10-07 at source digest
`21d98f8b0c8d1b7171c6d5d4f419af9d04fccb976202b9cfa26dfb218fd5480e`.
Inventory `.agent-work/workbench-flow-repair/ready-source.json` remained unchanged
through all builds, tests and native consumer probes. This section is a later
documentation-only edit. The same Linux toolchain/header prefix below was used
with retained GUI group
`78613235aebaf6320fe96e1023db178176e0187be2b841ac336c927ba056ba39`;
the upstream revision is unchanged.

- The supported workbench wrapper with `test dev --backend fltk --build-dir
  build/workbench-flow-ready --build-jobs 2 --test-jobs 2` passed all eight
  CTest entries, including 273 Python cases with zero skips. Flow cases cover
  the drag threshold, zoom scaling, pointer ownership, unchanged text/selection,
  negative pan and arrow navigation, Escape and scene cancellation, and stale
  release rejection. Evidence: `.agent-work/workbench-flow-repair/ready-workbench.log`.
- The supported main wrapper with the same four selected GUI tests and backend
  options as below passed in `build/workbench-flow-ready-boundary`:
  `tools.gui_boundary`, `tools.gui_source_group`, `foundation.gui.context-fltk`
  and `foundation.gui.fltk-host`. Native assertions cover released press routing,
  absence of periodic focus transfer, prompt successors and reply-created
  controls. Evidence: `.agent-work/workbench-flow-repair/ready-boundary.log`.
- Native `--smoke-test` exited 0. Evidence:
  `.agent-work/workbench-flow-repair/ready-native-smoke.log`.
- The actual rebuilt GUI passed 12 isolated native consumer checks: text editing
  and Save, blank/block dragging, Escape cancellation, Reset, dropdown dismissal,
  click selection, workflow preservation, foreign-window focus retention and
  hidden-window retention. The final receipt and inspected captures are in
  `.agent-work/workbench-flow-native/final-flow-ready-observed/`. The binary
  SHA-256 is `5744fbb089eec6eb8cc983f3d3ca32efb681eda7325e6c210f9216d79746c72a`.
  Selection appeared after 419 ms, within the one-second observation bound;
  foreign focus and hidden state remained intact over four and three seconds.
  These are bounded native observations, not sustained desktop qualification.

The exact reported foreground/virtual-desktop takeover was not reproduced under
Xvfb without a window manager. The prior binary also passed foreign-focus and
unmap observations; these results do not dismiss the report. Narrower negative
controls did reproduce stale FLTK press routing after Escape and periodic native
focus transfer. The implementation now releases owned routing and removes focus
activation from ordinary presentation. A reviewed intermediate prompt-successor
regression was repaired and independently reproduced by a negative control.
Details and final direct native passes are in `.agent-work/desktop-focus/receipt.md`.
The initial integrated candidate
`e9e7fc02ed7060ed325a71a4493faa8dfc745d5c83e2bb7649bc876d586b574e`
passed its then-current eight/four checks before that review finding; its inventory and logs remain in
`.agent-work/workbench-flow-repair/` and are not relabeled as final coverage.

Initial consumer receipts sampled selection or saved bytes too early and remain
failures in `final-flow-ready/` and `final-flow-ready-synchronized/`. An unchanged
binary discriminator verified rapid and held clicks before/after dragging within
one second. The final probe waits for actual rendered/saved state with bounded
deadlines and retains the same assertions; no application change was made for
those observation corrections. All checks were offline, using synthetic files,
isolated configuration and owned displays; no provider/search calls or user
desktop interaction occurred. Owned processes were terminated and joined.

Actual window-manager and virtual-desktop qualification remains unexecuted.
The next manual observation uses
`build/workbench-flow-ready/tinyenv-workbench-fltk`: drag the flow, switch to
another application/desktop, and minimize/restore it. Broad backend/platform and
release qualification still awaits an explicit request.

The minimize, remembered AI defaults and interactive search refinements were
checked on 2026-10-07 at source digest
`ec10ad4f06810e0bf6f96add8546e6094388dd09f16cad0d247b3ce254577c24`.
The complete inventory is `.agent-work/workbench-behavior/final-source.json`;
its bytes were unchanged through compilation, tests and native smoke. This
record is a later documentation-only edit. The same Linux toolchain/header
prefix below was used with retained GUI group
`4b014b7224993e921fcb9eb39862e01c41fca1419615a8d0a38e66ea244b39ce`,
preserving the existing upstream revision.

- `./build.sh workbench test dev --backend fltk --build-dir
  build/workbench-behavior-final --build-jobs 2 --test-jobs 2` passed all eight
  CTest entries, including 273 Python cases with zero skips. Added cases cover
  defaults across restarts/projects, no-chat configuration, chat overrides,
  malformed/conflicting preference saves, general interactive search, public
  transport address validation and source-snippet provenance. Evidence:
  `.agent-work/workbench-behavior/final-workbench.log` and
  `build/workbench-behavior-final/Testing/Temporary/LastTest.log`.
- The supported main wrapper with `--core-provider cpp --gui --gui-backends
  terminal,framebuffer,fltk,hosted-web --host-tests` and fresh
  `build/workbench-behavior-final-boundary` passed all four selected checks:
  `tools.gui_boundary`, `tools.gui_source_group`, `foundation.gui.context-fltk`
  and `foundation.gui.fltk-host`. Native fixtures cover background focus,
  iconification, retained draft restoration and foreground/background prompt
  completion. Evidence: `.agent-work/workbench-behavior/final-boundary.log`.
- Rebuilt native FLTK `--smoke-test` exited 0 using the isolated local demo.
  Evidence: `.agent-work/workbench-behavior/final-native-smoke.log`. No actual
  user's home configuration was written by these checks.

Two intermediate integration failures were repaired and rerun, not counted as
passes. Source `e191a148c2a901aa46c6007571874f7e27c71fe05ee4a48a5f2269dfab271df6`
failed the new empty-workspace AI control fixture (seven of eight CTest entries
passed); the UI had still hidden AI controls without an open chat. Its repair
passed all eight entries at
`e1f9dd4e5fdcabb3ca0289dae871602040c60843498e92cd885c1aa44f8fbbeb`.
The initial focus patch's GUI group
`303f2578113925464c803093701c4afdf45ea3a81eb9511f4ad8a7e40c35a6cd`
passed the three boundary/context checks but failed the existing native host
fixture's prompt-focus restoration assertion. The final patch restores focus
only when a finishing foreground prompt still owns it and its parent is visible.
Evidence is retained in `.agent-work/workbench-behavior/` (`workbench.log`,
`repaired-workbench.log`, `boundary.log`, `native-prompt.log`) and
`.agent-work/minimize-fix/receipt.md`.

All automated checks used local fixtures, fake providers/transports and disabled
external network access; this refinement made no live search, DNS or provider
requests. Native events ran under an isolated Xvfb display without a window
manager; actual desktop minimize/restore behavior remains a manual qualification
scope. General DuckDuckGo search is implemented but its live endpoint behavior
is unverified. The next local observation is to launch
`build/workbench-behavior-final/tinyenv-workbench-fltk`, minimize it while a local
task runs, and restore it. Any user-directed live search qualification remains
limited to a few dry technical queries/results from reputable sources; those
qualification restrictions do not limit normal user queries in the interface.
Broad platform/release qualification still awaits an explicit request.

The subsequent desktop refinements were checked on 2026-10-07 at source digest
`00ff96e70b9aa37c04f5bd1b03d487fa89b524d2ac66a63271a69d2ecb45def7`.
The complete input inventory is
`.agent-work/workbench-refinements/test-source.json`; its bytes remained
unchanged through compilation, tests and native inspection. This paragraph is
a later documentation-only edit. The same Linux toolchain/header prefix below
was used with retained GUI group
`a37f727e4979bb5c54544be7fb5aa4328b39afcba26ca10f1672e0ef3c5a136a`.

- `./build.sh workbench test dev --backend fltk --build-dir
  build/workbench-refinements --build-jobs 2 --test-jobs 2` passed all seven
  CTest entries, including 255 Python cases with zero skips. The new local
  cases cover `.chat.md` separation, default-home directory creation, file
  mutations/sidecars, rejection of non-empty directory deletion, terminal Stop,
  Escape and preservation of unsaved content. Evidence:
  `.agent-work/workbench-refinements/workbench.log`.
- The supported main wrapper with `--core-provider cpp --gui --gui-backends
  terminal,framebuffer,fltk,hosted-web --host-tests` and fresh
  `build/workbench-refinements-boundary` passed the selected
  `tools.gui_boundary`, `tools.gui_source_group` and
  `foundation.gui.context-fltk` checks. The native fixture checks both
  `FL_KEYDOWN` and `FL_SHORTCUT` Escape paths. Evidence:
  `.agent-work/workbench-refinements/boundary.log`.
- Native FLTK smoke passed. Two actual Escape key presses kept the isolated
  window open; another pair dismissed the file context menu and kept the window
  open. Native dark flow and right-click menu captures were inspected under
  `.agent-work/workbench-refinements/` (`native-dark.png`,
  `native-file-menu.png`, `native-smoke.log`, `native-escape.log`,
  `native-menu-escape.log`). Only an isolated local demo was used, with no live
  provider/search calls and no writes to the actual user's home chat directory.

The new GUI group preserves the existing upstream revision and adds the generic
native Escape fallback fix. These results do not extend platform, backend or
release qualification; the remaining scopes below still apply.

Completed focused documentation checks on Linux, 2026-10-07:

- `python3 tools/check_docs.py` passed local links, headings, JSON and practice
  references. `git diff --check` passed for the changed documentation.
  `./build.sh workbench --help` confirmed the documented wrapper flags.
- The production runtime CLI, `python3 -I -B workbench/services/runtime.py
  --request ABSOLUTE-FIXTURE-REQUEST`, completed the documented explicit
  `scribble.ai_enabled: false`, `network_enabled: false` operation using a
  two-line synthetic local technical fixture. It produced exactly
  `scribbles.md`, `index.json` and `evidence.json`, with zero model calls and
  no external content/services. Python was 3.13.5. Service bytes were unchanged
  before/after; SHA-256 of the sorted JSON relative-path-to-file-SHA-256 map was
  `6d9a95d4d061607c5c705b0794550ed9b31e114f69ba01585c9a92a94b915acb`.
  Temporary fixture/output files were removed. This source invocation does not
  substitute for the copied worker or native application suites.

Completed integrated Linux development checks on 2026-10-07 used GCC 14.2,
CMake 3.31, Python 3.13.5 and retained FLTK 1.3.8-5 headers. Code snapshot
`ac04e7d219fe23e3916b84b70d62b9837ec21a3d34fba39eca145aec55d2e34f`
passed:

- `./build.sh workbench test dev --backend fltk --build-dir
  build/workbench-focused --build-jobs 2 --test-jobs 2`, with
  `CMAKE_PREFIX_PATH` set to this checkout's
  `.agent-work/workbench-integration/fltk-dev`, passed all six CTest entries,
  including 255 Python cases with zero skips. Evidence:
  `.agent-work/workbench-integration/repaired-workbench.log`. Automated cases
  used only local fixtures/fake services. Transcription fixtures used a fake
  executable, model and WAV, not an actual Whisper model/audio run.
- Native `--smoke-test` exited 0. Evidence:
  `.agent-work/workbench-integration/repaired-native-smoke.log`.
  The final native window screenshot
  `.agent-work/workbench-integration/workbench-native-final.png` was inspected
  for coherent files, flow, snippets and ASCII toolbar labels. This is a native
  smoke/visual observation, not sustained desktop or backend qualification.
- The two corrected boundary fixtures, `tools.gui_boundary` and
  `foundation.gui.context-web`, passed their focused rerun. Evidence:
  `.agent-work/workbench-integration/repaired-boundary.log`. Its recorded wrapper
  expanded to `ctest --test-dir build/workbench-boundary-checks
  --output-on-failure --no-tests=error --parallel 2
  -R '^(foundation\.gui\.context\-web|tools\.gui_boundary)$'` after the supported
  build/configuration steps recorded there. The fixes supplied the isolated
  Rev fixture's missing repatch helper and expected the existing stale-event
  rejection. The affected production GUI code was unchanged.

Six other selected boundary passes are reused with their original snapshot
`ee067eb9083d5ad39a3c463c15add7fa88059385f23e728a2f34fda224d77fed`
and unchanged relevant bytes: `tools.gui_source_group`, `tools.source_identity`,
`docs.links`, `foundation.gui.context-input`, `foundation.gui.browser-channel`
and `foundation.gui.context-fltk`. Evidence:
`.agent-work/workbench-integration/final-boundary.log`. The shared GUI input
group identity was
`bc9f72a850cf38899b846fb59346dd5dcd0337d267c6d5b2fd92c0c9505be628`.
This record's final documentation edit occurs after the code snapshot and does
not relabel prior tests as covering these new documentation bytes; documentation
links/whitespace are checked separately after publication of this edit.

Completed user-authorized tiny manual probes on 2026-10-07 are recorded in
`.agent-work/workbench-integration/live/`. These used the production Python
provider, research and scribble services through a manual capture helper,
rather than the desktop workflow. No automated test made those calls.

- Curated research made exactly one Wikipedia query (`intitle:readdir`), returned
  one article metadata result and fetched one explicit `mkdir(2)` page from
  man7: two results and two HTTP requests in total. Only 1,800 characters from
  the manual were inspected/retained, with no external links followed. The
  receipt is `research-evidence.json`; no Kiwix content was accessed.
- Each successful annotation used the same single 2,256-byte technical fixture,
  one source/chunk, including that existing manual excerpt. Its source SHA-256 is
  `201a224c867c6e80b8f5b28b89fbcd7617104e828255e0844d947087f0ee2fe7`.
  The reviewed OpenRouter routes used a $3/million-token input/output ceiling,
  disabled fallbacks/data collection and optional zero retention off. Each
  generated the three checked scribble artifacts with validated annotations
  and keywords. No extra searches occurred.

| Annotation model | Receipt | Input/output tokens | Result |
| --- | --- | --- | --- |
| `nvidia/nemotron-3-ultra-550b-a55b` | `nemotron-ultra-generation.json` | 1,056 / 568 | Passed one annotation |
| `mistralai/mistral-large-4-0` | `mistral-large4-generation.json` | 958 / 2,848 | Passed one annotation |
| `deepseek/deepseek-r1-0528` | `deepseek-r1-optional-fields-generation.json` | 1,007 / 2,376 | Passed one diagnostic retry |

The first DeepSeek attempt failed strict nonempty-field validation; its receipt
`deepseek-r1-generation.json` is retained as a failure. The implementation now
accepts empty optional commentary/relationship/nuance fields while requiring a
nonempty moniker, description and keyword list. The single retry above passed
that corrected schema; the original attempt remains a failure.

Earlier Nemotron attempts also failed: selecting the fixture under excluded
`.agent-work` produced no eligible source before inference; moving it to `/tmp`
then produced the sanitized diagnostic `provider callback failed; no retry was
made`. That failure did not distinguish endpoint-metadata access from model
completion and its usage is unavailable. After authentication/route metadata
checks and clearer typed diagnostics, one deliberate retry produced the passing
receipt above. The early same-named failure file was overwritten before the
capture helper was corrected, so this history records the limitation without
assigning a cause or invented token usage.

`nemotron-ultra-evaluation.json` records one paired question using
`nvidia/nemotron-3.5-lightning`: exactly two calls, the same source chunk before
and after Nemotron Ultra annotations. Original input/output usage was 802 / 23
tokens; enriched usage was 1,301 / 16. Both answers matched the explicit expected
`EEXIST` substring, scoring 1.0 / 1.0 with difference 0.0. The probe passed the
comparison workflow and found no measured improvement; it does not establish
better large-knowledgebase comprehension or general RAG quality. Kimi and
OpenAI knowledge generation were not tested. No additional live calls are
planned for this implementation task.

The local-only `offline-keyword-retrieval.json` compares the saved indexes with
an in-memory baseline using the same original content/local keywords and the
AI keywords removed. It made zero external calls and did not alter artifacts.
Three selected keyword queries each gained a source-chunk match for Ultra and
Mistral; the selected DeepSeek keyword queries gained none. This verifies
additional keyword retrieval for one chunk, not general recall, scale or
comprehension improvement.

The supported focused offline command is:

```sh
./build.sh workbench test dev --headless --build-dir build/workbench-checks
```

Automated fixtures must use local files and fake provider/search responses, with
no external service, search or Kiwix calls. A passing fixture establishes its
named local scope only.

Applicable qualification scopes, with distinct authorization/prerequisite status:

- Broader desktop/backend qualification is awaiting an explicit extensive
  validation request. This includes sustained actual desktop interaction:
  chat switching,
  state restoration, terminal ownership, file actions, flow text/graph edits,
  cancellation and recoverable errors. Start with the FLTK command in
  [COMPILE-workbench](../COMPILE-workbench), then record the exact source,
  backend/toolchain, commands and observations.
- The user authorized only tiny manual scribble-building and small-model
  comprehension probes using actually available requested models,
  a non-sensitive technical fixture and terms permitting knowledgebase creation.
  The completed scope is recorded above. Use explicit reviewed trustworthy
  provider routes with no training; zero retention is optional under the user's
  clarification. Confirm current model identifier/cost and never use an OpenAI
  model. Kimi remains constrained by the price ceiling and is omitted from the
  intended tiny default-price probes.
- Curated search, Deep Research and optional Kiwix live probes are limited to
  at most a few dry technical queries/results from the permitted sites. Record
  whether each tiny requested probe actually ran. The completed search receipt
  above checks direct curated search/fetch, rather than the subsequently added
  AI follow-up-query loop. That loop has local fake-provider/search checks only;
  no extra live search was run. Larger research runs and
  million-token knowledgebase/comprehension qualification remain unexecuted;
  explicit larger implementation budgets do not establish scale qualification.

The Bash PTY is currently Linux-only; macOS worker execution is unavailable.
Windows worker/native-host qualification is unexecuted. Kiwix support reads a
local exported text index, with no ZIM reader or Kiwix server. The workbench
currently has no installation/package operation. Local media transcription
requires Linux x86_64 or aarch64 and an existing trusted whisper.cpp executable,
compatible model and WAV. These implementation boundaries
are not pending passing tests.

Model-directed Bash and custom executable tool descriptors are unimplemented;
the selected model tools read/list/search bounded local files and, when
separately enabled, interpret bounded numeric calculations. The
user-operated Bash terminal is separate. This feature boundary is not an
unexecuted qualification scope.

Actual transcription model/audio quality is unverified; executable fixtures
alone do not establish it. The next user-directed local media probe can use
File Actions → Media transcribe with an existing compatible model and a small
non-sensitive WAV. It needs no downloads or provider calls.

Unimplemented behavior or a known failure must be recorded separately from an
unexecuted qualification scope. Further sustained desktop/backend qualification
awaits an explicit extensive validation request. Its next manual command is the
native FLTK build/run procedure in [COMPILE-workbench](../COMPILE-workbench).
Consult [workbench operation and restrictions](../docs/workbench.md) before any
live provider/search probe. This record neither schedules nor authorizes broad
backend, provider or release matrices.
