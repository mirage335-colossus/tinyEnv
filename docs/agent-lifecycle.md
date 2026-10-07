# Session liveness, recovery and cleanup

This is the detailed reference for [the coordination workflow](agent-coordination.md).
Read it before configuring supervised heartbeats, investigating overdue or unknown
ownership, recovering a session/registry lock, resolving missing closure metadata,
or retaining/deleting coordination material. Routine startup and completion still
scan current and legacy session metadata for overdue owners and cleanup candidates;
those scans do not require loading old records or logs wholesale. No age or PID
observation by itself releases ownership.

## Progress, interruption and recovery

Publish a consistent snapshot at scope/progress checkpoints, before potentially
blocking jobs and before pausing or ending a turn. Stamp Updated at publication;
advance inbox/progress times only after those events. Keep heartbeat separate:
a timer can show liveness while work is stuck. These are hints, **not lease expiries**.
Use the [job/inbox recipes](agent-recipes.md#job-and-handoff-checkpoints)
for launch, yielded handles and completion instead of inventing process identity
before a tool returns. Reconcile finished jobs at the next control boundary;
short synchronous results join the next checkpoint.

- When the harness offers a supervised heartbeat hook, use a default 60-second
  cadence while active. Give it a unique run token and one writer for
  `heartbeats/<session-id>.json`. Include session ID, run token, host, UTC time
  and an increasing sequence number. Publish it atomically via a sibling
  temporary file. It reports liveness only; the agent updates work progress.
  Refresh the run token and process identity on restart/resume. Readers accept
  only heartbeats matching the current record's session, host and run token;
  old or mismatched sidecars are not current liveness evidence.
- Without a reliable hook, use `checkpoint` mode and update the session record
  about every five minutes while in control. Before a blocking or unattended
  command, record launch intent, resources, expected duration and next check;
  add its real job identity if the tool yields one, or record completion on return.
  Do not promise a heartbeat the tool cannot produce.
- Stop heartbeat writers on pause, closure or owner exit. Never start an
  unsupervised detached loop that can keep a dead session looking alive. A
  helper's survival or a live desktop application does not prove that this
  particular chat is working. This guide adds no daemon or scheduled cleanup;
  agents or harnesses must perform the documented updates and checks.

Record owner and job identity when the environment exposes it: host, boot
identity, PID namespace/container, PID, and process creation time or equivalent
OS start token. A stable process handle can supplement these where supported;
its numeric value alone is not a portable cross-tool identity. Label the role
(`session worker`, `heartbeat helper`, `build job`, `registry lock holder`) and
record child/detached jobs separately. Do not use a throwaway tool shell's PID
or a desktop process shared by several chats as the session worker. If the
session owner cannot be identified, say `unavailable` and use checkpoints.

Inspect process identity only on the recorded host and in the matching namespace.
Match start/boot identity as well as PID: a reused PID is a different process.
Permission errors, an unreachable host or missing identity information mean
`unknown`, not `exited`. A verified exit helps identify an interrupted run, but
does not prove that its child jobs stopped or that a chat cannot resume. Process
existence also does not prove progress. Do not infer elapsed time from a skewed
or future timestamp; record clock uncertainty and investigate. An advancing
heartbeat sequence is useful evidence when comparing successive observations.

At startup/resume and before requesting an overlapping claim, review records
whose heartbeat is overdue by three expected intervals (at least five minutes)
**and** past any announced next check. In checkpoint mode, use the declared next
check with a five-minute grace period. Missing cadence/next-check data means
`unknown`. Record the observation in your own cleanup report or a message to the
owner; do not rewrite its state as failed based on age.

| Observation | Classification and next action |
| --- | --- |
| Fresh heartbeat or matching live worker/job | Possibly active; preserve claims and inspect progress if needed |
| Overdue heartbeat, owner still live | Possibly stalled or paused; contact owner, keep claims |
| Overdue heartbeat and verified owner exit/start mismatch | Interrupted-run candidate; inspect jobs and use recovery procedure |
| Host/identity unavailable, clock uncertain or no declared cadence | Unknown; no automatic reclamation |
| `done`, `failed` or `cancelled` with closure details | Cleanup candidate; check deletion conditions below |

Release a completed shared-file edit before unrelated evidence formatting or
whole-session closure. Keep the session nonterminal while required delivery
acknowledgments or other work remain, without retaining an unneeded file claim.
Finish retained evidence and all output writers before closing their claims,
including inherited stdout, logging/cleanup traps and the publisher's final output.
The [closure recipe](agent-recipes.md#finish-output-before-releasing-its-claim)
keeps these writes before release. Prepare/check candidates outside `sessions/`;
final review/publication belong inside the short owned registry operation. Clean
only owned staging/lock files. An error after publication does not restore claims:
inspect actual bytes before retrying, especially after a terminal transition.
Retain claims if a child, queued save, output descriptor or cleanup writer cannot
be shown stopped. A successful parent command does not prove every descendant
finished. A failed acquisition must not delay recording a known job completion
with unchanged claims; its failed dependency remains separately pending.

For synchronous evidence-producing commands, [process_tree.py](../tools/process_tree.py)
provides a reusable lifetime owner. `launch(argv, cwd, stream)` returns an owner
with `process`, `poll()`, `wait(timeout)`, `finish()`, `terminate(timeout=5)` and
`close()`. Keep the claimed stream open while it runs. After parent exit, call
`finish()` before digesting or reporting output, and always `close()` in a checked
cleanup path. A successful parent with surviving writers is rejected and its
supervised descendants are stopped. A termination/cleanup error leaves writer
completion uncertain; do not release output ownership or publish passing evidence.

Linux launches a dedicated child-subreaper process before the command. That owner
adopts descendants even when they create another session or process group, including
nested supervisors. It kills remaining adopted children after primary completion
or termination and waits until the kernel reports no children. Its small private
completion receipt distinguishes the primary exit from lingering descendants;
missing or invalid completion remains uncertain. The caller's Python process and
shared harness never become subreapers. A private control pipe supports cancellation
even during startup; parent-death notification and control-pipe closure request
cleanup if the caller exits. `process.pid` identifies the private Linux supervisor;
`poll()`, `wait()` and `returncode` expose the primary command's result only after
the supervisor completes all reaping. An unkillable descendant keeps supervision
alive and prevents a completed receipt.

Commands must not transfer writable handles or delegate continuing writes to an
unrelated service. They must not deliberately kill their supervisor or evade its
ownership through a privileged host facility. Those workloads need qualified OS
confinement; this adapter is cooperative lifetime ownership, not hostile-process
isolation. Other POSIX systems fail closed until an equivalent descendant owner is
supplied, instead of silently falling back to process-group-only cleanup.
On Windows, the adapter
creates a non-breakaway Job Object with kill-on-close, creates the child suspended,
assigns it before its first instruction and only then resumes the initial thread.
Assignment or resume failure stops and joins the child and closes the job; it
never falls back to an unsupervised launch. Native platform tests must qualify
the actual environment. Mocked Windows ordering tests on Linux do not qualify
native Windows process management. See [the lifetime tests](../tests/test_process_tree.py).

Before pausing, release what you no longer need and state which claims remain
held and why, plus an expected return/check if known. On completion, failure or
cancellation, publish results, unresolved questions, changed files and next
action. Resolve jobs and handoffs, stop heartbeat writers, then release claims
under the mutex. In that same record update, set terminal state (`done`, `failed`
or `cancelled`), closure timestamp and deletion deadline in Current checkpoint,
and resolve obsolete blocker/request text. Use literal `Running jobs: none` and
standalone `None.` claims for a completed current-template record; finished job
details belong in Progress and checks. Keep current fields consistent, not in
appended corrective progress entries. A failed command alone does not make the whole
session terminal. Pending integrations should name their receiving session
and record an acknowledgment. Uncommitted edits survive a release of claims:
record them so the next owner preserves or explicitly integrates them.

The mutex becomes available only after successful removal of its directory.
Termination during initialization or cleanup can leave a lock with no owner file;
that empty/partial lock still blocks acquisition. A killed process, missing token
or failed unlock never makes it available. Do not manufacture ownership metadata,
borrow a token, or run cleanup from a different acquisition with the same session ID.
Inspect authoritative saved claims after failure and use the recovery rules below.

Do not steal claims or remove a registry lock solely because it looks old. A chat
may be suspended or running a long test. Contact its owner, inspect available
session/process evidence, and obtain an explicit release. If the owner is gone,
recovery requires positive evidence that the session and its jobs cannot resume
writing, or a user-coordinated stop/handoff. A missing PID alone is insufficient
across hosts or resumable chats. Record the evidence and designated recovery
owner; suspend registry changes during lock recovery. Preserve the abandoned
record/lock metadata in the recovery owner's artifacts before changing anything.
After exclusive access is established, the recovery owner records the evidence,
closes the abandoned session as failed or cancelled as appropriate, and releases
its claims under the registry mutex, preserving the original snapshot. Record
the closure time and handoff before applying the deletion rules below. A recovered
session must register/reclaim before resuming edits.

## Delete expired sessions and unnecessary history

Delete eligible `done`, `failed` and `cancelled` sessions **30 days after verified
closure**. Do not create new archives or require a separate owner opt-in for this
default cleanup. Owners may discard their own resolved records sooner only after
needed provenance is transferred or consolidated, not merely because claims are
empty. No deletion/rewrite may erase the latest ownership/release facts while a
relevant notice, pending acquisition or review/integration depends on them. Under
the mutex, preserve a discoverable current baseline/lineage anchor and redirect
live references before removing predecessors. Imported `archive/sessions/` records have the same
30-day deadline measured from closure, not archival or last access. Copying,
moving or inspecting a record must not restart its age.

At startup and task completion, use local metadata scans to identify due records,
including legacy archives; keep routine claim reads limited to `sessions/`.
Age selects candidates only. Before deletion, verify all of these:

- The record is terminal, has a closure time and holds **no claims**. An old
  `active`, `waiting` or `paused` record must go through recovery first.
- Jobs and heartbeat writers have exited or been explicitly transferred to a
  named live owner. No pending handoff or writer can update the closed record.
- The final result, changed files, uncommitted/staged-work disposition, remaining
  validation and useful findings have a destination where needed. Extract useful
  unresolved facts into concise `notes/` with an owner, evidence and next action;
  promote required durable evidence to maintained records. Do not preserve the
  full session transcript as the note. Uncommitted edits themselves remain intact.
- No active handoff, unresolved investigation or required evidence depends on
  the material being deleted. Redirect essential references to the surviving
  facts with their owners. Incidental author/session IDs and prior cleanup
  links are provenance, not retention pins; keep brief attribution without
  keeping entire histories or leaving misleading links to deleted files.

When a release/acquisition chain still establishes current provenance, keep its
necessary references resolvable or consolidate the relevant ownership/disposition
facts under the mutex with the receiving owner before deleting the source record.
Check live dependencies by exact scope as well as explicit session/reference IDs:
a waiting recipient may not yet know an intervening owner's ID. Do not delete or
compact away that transition merely because nobody named its record. Do not
mistake unchanged file bytes for a redundant ownership transition. Once
the handoff is resolved and no live dependency needs the chain, ordinary retention
applies; this is not a reason to keep an unbounded ownership log.

For older records missing closure fields, the owner or designated recovery owner
may add verified details under the registry mutex, preserving the original
snapshot only while recovery needs it. A missing deletion date means closure
plus 30 days; a missing trustworthy closure time needs investigation. Do not
substitute filesystem modification time for verified closure.
A deletion date beyond closure plus 30 days requires the retention exception
below; a date field alone cannot extend the default lifetime.

Retention exceptions must name a live dependency, responsible owner, exact
material needed, reason and review date within seven days. Record these in a
compact note and review them during cleanup; extend only while the dependency
still exists. Prefer extracting the necessary facts so the session can expire.
An old undated `keep` marker needs review, not perpetual retention. Age alone
still cannot resolve unknown ownership or an unfinished dependency.

Prepare an exact list of eligible paths, including the session record and its
unneeded heartbeat files, messages, logs, original-record snapshots, copies and
old cleanup reports. Do not leave a shadow archive under `artifacts/`. Check
shared references and writers for each item; a session ID in a filename is not
sufficient proof that it is disposable. Notes have their own useful lifetime:
retain compact unresolved facts, and remove superseded/redundant notes after
their useful content and references are handled.

Acquire the registry mutex, reread eligibility and references, then delete only
the listed eligible paths while still holding it. Skip anything changed or
uncertain. Record UTC time, session ID, reason and deleted paths in `cleanup.log`
without copying record contents. Keep at most the newest 100 receipts within
16 KiB total, and none older than 30 days, dropping oldest receipts as needed.
Rewrite atomically under the same mutex; do not rotate receipts into another
archive. Recovery snapshots and migration reports expire with
their resolved source session unless narrowly needed for a live investigation.
Do not duplicate these receipts into every session's artifacts. Use small batches
and release the mutex promptly.

Cleanup never kills processes, edits source or Git state, deletes build trees,
or releases claims just because they are old. It removes only the explicitly
eligible coordination material. If cleanup is interrupted, inspect both the
remaining candidate paths and recent receipt before retrying; recheck eligibility
and record partial results. Do not create backup copies as part of routine
deletion. All agents must coordinate new references with
cleanup: recheck the target and publish the reference or preservation pin during
the same registry mutex hold, so cleanup cannot delete it in between.
