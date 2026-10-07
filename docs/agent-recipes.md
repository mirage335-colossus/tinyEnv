# Coordination recipes

Use the relevant recipe after reading the [workflow](agent-coordination.md).
This is an on-demand reference, not another startup checklist. The optional Python
helpers reduce formatting and publication mistakes; they do not enforce subsequent
source writes. Use their checked transaction or a qualified executable equivalent.
Jump to the needed section; opening a recipe does not restart instruction reading.
Other harnesses may implement [equivalent safe operations](#equivalent-publication-without-the-helper)
in a tested wrapper; workers must not invent a new lock/unlock sequence per task.

Every command below assumes its tool is explicitly bound to the intended checkout
and defines `checkout`, `coord_dir` and `session` in that invocation. Use absolute
physical paths, not a previous shell's variables or working directory. Resolve the
agreed board and verify ignore status **before** initializing missing ordinary
directories. A delegator may supply that proof when its containing checkout is
off limits. Never initialize a new board just because the expected one is missing.

## Initialize and render a record

`agent_session.py capabilities` needs no input and reports whether the
runtime exposes the required publication and guarded-save primitives. It always
reports `filesystem_qualified: false`: API availability does not qualify a mount.
Linux with the required Python/filesystem features is the supplied implementation's
primary shared-write environment. Some POSIX hosts lack the descriptor metadata
API needed for guarded saves. Native Windows requires a separately qualified
adapter or enforced private-checkout/output access; the portable reader and
compatibility helper do not establish equivalent source-save protection.

After the agreed board's physical path and ignore status are verified, initialize
ordinary directories using a JSON request on stdin:

```sh
python3 -B "$checkout/tools/agent_session.py" init --json-errors <<'JSON'
{"board":"/work/software-foundation/.agent-work"}
JSON
```

Substitute the actual board path. This creates missing ordinary directories,
preserves existing contents and rejects links, invalid namespace types or an
active JSON protocol. It does not register ownership. If initialization reports
uncertainty, inspect the created paths before resuming; do not erase a partial
board or choose a new path. Initialization is an agreed administrative setup
operation, not a way to bypass a held claim.

Use [the JSON input template](templates/session.json) with the `render` operation
or `render_record(...)` Python API to generate a complete candidate in memory.
The [filled Markdown reference](templates/session.md) shows the saved format.
Replace every `REPLACE...` value, illustrative path/date, host and task field with
observed facts. Set Updated from the current UTC clock and Next check to the real
planned check. Set progress/inbox events only when they occurred; `unavailable`
records a genuinely unknown event. A previously known event cannot be erased or
moved backwards. Process identity may also explicitly be unavailable. These
values are distinct from `none`, which describes the absence of jobs, claims or
terminal-only fields. Complete the startup inbox check before acquiring work.

`render` validates formatting, typed scopes and lifecycle fields; it neither
checks ownership nor publishes. Next call `review` with every proposed scope and
relevant input, inspect its complete errors and relevant handoffs, then `commit`
with `create: true` and that frozen review. Keep initial JSON/candidate/review data
in memory or stdin until claims grant an artifact directory. Only a successful
commit and owned-mutex cleanup permit dependent mkdir, output or source writes.

## Transition an existing JSON board

New projects initialize the complete record protocol directly. `agent_board.py`
is a compatibility interface for an existing `state.json` board; it is not an
alternative with equivalent guarded-save enforcement. Its entire checked API
remains available while active compatibility sessions finish. All record writers
refuse a board containing `state.json`; compatibility operations refuse a migrated
board. Do not initialize another authority for the same writers or mix helpers.

For an existing board, first publish every session's final disposition and finish
all writers, children, output streams, heartbeat processes and pending transfers.
Release all claims and close every session. Stop automatic registrations and
arrange exclusive administration across all participating harnesses. The migration
operator then reviews the exact complete JSON bytes and revision and computes
their SHA256. Neither an old timestamp nor an empty claim list proves exclusion.

Invoke `agent_migrate.py` with a JSON object containing `root`, `board`, `revision`,
`expected_sha256`, an unused descriptive `operator` ID, factual `review` text and
both `writers_stopped: true` and `exclusive_administration: true`. These last two
fields are positive caller assertions that require evidence; they are not OS
process checks. Send input from memory/stdin and output to the harness, since the
old sessions have released artifacts. The administrative operation supplies its
own narrow authority for the migration evidence it creates.

The helper acquires the compatibility mutex; validates exact reviewed bytes and
revision, terminal/empty sessions and resolved transfers; refuses existing record
destinations; writes complete converted records and immutable messages; preserves
an exact source snapshot and receipt in a unique `artifacts/migration-ID/`; and
checks the saved inventory. Missing old event times remain `unavailable`. Original
closure and deletion dates are preserved, never reset to migration time. Full
scope inventories retain release/acquisition references and source disposition.

The final authority switch removes `state.json` only after verified record
publication and a `protocol.json` marker. It then flushes the board and completes
owned mutex cleanup before reporting success. No active claims are transferred.
New work registers fresh IDs using the complete protocol and reviews retained
predecessor releases normally.

Any failure after output creation is uncertain. Do not rerun automatically or
delete converted files. Before the switch, the exact source remains and partial
destinations intentionally block normal operations; after the switch the record
protocol may already be authoritative despite a failed receipt. Inspect the
marker, source snapshot, original state presence, saved records/messages and lock
under exclusive administration. Resume only after a qualified recovery verifies
one authority and complete provenance. There is no automatic rollback or merge.
Migration evidence follows the source records' original retention eligibility;
consolidate needed lineage before deleting it, without retaining a shadow archive.

## Bounded reading

For the startup read, request AGENTS and the workflow separately. For example:

```sh
python3 -B "$checkout/tools/check_agent_record.py" --read "$checkout/AGENTS.md" --limit 8000
```

Continue at returned `next_offset` using `--offset` and `--snapshot` from that
response until `next_offset` is null, then read the workflow the same way. A
changed snapshot fails instead of mixing pages. Equivalent bounded line reads
are fine; continue to EOF and recover decision-relevant truncation. Do not concatenate them with source, board records or logs.
After startup, use the relevant checkpoint instead of rereading the whole guide.
Apply the same output budgeting to source, test logs and web results. Independent
calls can run in parallel without combining their large bodies into one truncated
result. Retrieve every additional section/source needed for the task; these recipes
do not change the harness's normal research breadth, tool choice or browsing policy.

```sh
python3 -B "$checkout/tools/check_agent_record.py" --scan "$coord_dir/sessions" --compact
```

Both exit status and the JSON `complete` field matter. Compact output has exactly
the same decoded metadata, whole claims and errors as ordinary scan output.
For larger boards add `--limit 8`; continue with returned `next_offset` and
`--snapshot` until null. The helper scans all records on every page, returns whole
records/errors and rejects a changed snapshot. `complete` describes the scan,
while `all_returned`/`next_offset` describe delivery: an error can be on a later
page. Reduce the entry limit or inspect one record if the harness truncates output;
never discard part of its claims. A huge single record needs bounded manual
section reading, not a falsely complete truncated machine decision. One incomplete
record means the registry still needs review; other records' visible claims remain
authoritative. The scan is an observation, not an atomic snapshot.
On a busy board, pages may repeatedly invalidate. Do not hold the mutex across
model/tool turns to read them. Use the checked helper's complete machine ownership
checks and bounded relevant evidence, or an immutable capture in a claimed artifact
with its review identity; revalidate current state in the short commit operation.
Every owner and error must still be checked, but unrelated bodies need not be
printed into the model context. A cached capture never becomes the authority.

```sh
python3 -B "$checkout/tools/check_agent_record.py" \
  --inspect "$coord_dir/sessions/OWNER.md" --section metadata-claims --compact
```

Replace `OWNER` with the actual ID. This reports known metadata and the whole
`Claims held` section, including nested headings. Unknown formats keep their
errors and exit 1 even when useful fields can be extracted. Duplicate, ambiguous,
unreadable or unexpected entries require manual resolution; absence from a
successful-record list does not mean absence of claims. Do not skip temporary
entries: contact their owner to remove its own unpublished candidate.

For an actual overlap, receipt or unclear release, read only the needed handoff:

```sh
python3 -B "$checkout/tools/check_agent_record.py" \
  --inspect "$coord_dir/sessions/OWNER.md" --section handoff
```

Manual fallback reads all identity/liveness/closure metadata and **complete claims**
of each unresolved record, ending sections only at a same- or higher-level heading.
Then read selected dependencies/handoffs if needed. Do not load every task or
progress section to recover a missing template field. Exact current labels are
available without opening prior records:

```sh
python3 -B "$checkout/tools/check_agent_record.py" --fields
```

For temporary knowledge, first discover matching **filenames**, using a real task
path or distinctive symptom. For example, if investigating `tools/release.py`:

```sh
rg --hidden --no-ignore -l -F -- 'tools/release.py' "$coord_dir/notes"
```

No matches means broaden by the relevant component/symptom if needed, not dump all
note bodies. An absent notes directory is normal; an access error needs attention.
Read titles/status/affected paths from the matching files, then only the relevant
notes in full. Do not print sibling result summaries merely to discover a topic.
This filter is for knowledge discovery only: registry ownership review still
includes **every record and whole claim**, regardless of task relevance.

## Discover scope handoffs

Before acquiring a previously used scope, discover its relevant release/acquisition
records even when no current claim or inbox notice points to them:

```sh
python3 -B "$checkout/tools/check_agent_record.py" \
  --handoffs "$coord_dir/sessions" --scope-kind file \
  --scope "$checkout/path/to/target" --limit 8
```

Use `directory` for covering scopes and `resource` for an agreed exact resource ID.
The helper examines every record, including terminal owners, and returns **whole
matching handoff sections** and unresolved errors. It recognizes canonical paths,
covering scopes and conservative prior mentions; uncertain prose/legacy
records require manual inspection. It does not choose the last owner, prove stopped
writers or authorize acquisition. Follow pagination exactly as above; a partial
page collection is incomplete even if the underlying scan was valid.

For new releases/acquisitions include a plain discoverable line inside the existing
`Blockers and handoff` section, alongside release reference, acquired-from chain,
hashes, stopped writers and pending request disposition:

```text
- Scope inventory: complete
- Scope: file: /work/project/src/example.cpp
```

Use one line per exact scope; `directory` and `resource` are also valid kinds. This
is an aid within the same authoritative record, not another registry. The inventory
marker asserts that these typed rows enumerate **every** scope mentioned by the
section's acquisition/release history, including earlier still-needed handoffs.
Use `- Scope: none` only when there is no such scope. Do not add the marker to an
old record without actually checking its whole history. It is a producer assertion,
not machine proof that prose is truthful. Without it, non-neutral prose remains
uncertain even if some explicit scope lines are present; inspect it manually.
Duplicate/invalid markers and contradictory inventories do not permit filtering.
Keep live
handoff references discoverable during compaction. A complete search can find both
relay and quiet intervening owner: follow their acquired-from/release chain and
current claims, not timestamp sorting or equal content hashes. Recheck the relevant
snapshots under the mutex. Scope filtering never replaces the **complete claims**
scan; ambiguous or missing evidence must not be treated as free scope.

## Check your inbox

Choose your session ID before the startup inbox check. With the already-verified
board path, this read-only discovery example distinguishes a missing inbox from
failure. It creates no directory and never marks a nonempty inbox processed:

```sh
python3 -B - "$coord_dir" "$session" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import json, sys
board = Path(sys.argv[1])
session = sys.argv[2]
if not board.is_absolute() or not board.is_dir():
    raise SystemExit('Use the verified, accessible absolute board path')
if not session or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in session) or session in ('.', '..'):
    raise SystemExit('Use a valid session ID')
inbox = board / 'messages' / session
if (board / 'messages').is_symlink() or inbox.is_symlink():
    raise SystemExit('Unexpected inbox alias; inspect it')
try:
    names = sorted(p.name for p in inbox.iterdir())
except FileNotFoundError:
    if not board.is_dir():
        raise SystemExit('Board became inaccessible; inbox check incomplete')
    names = []
now = datetime.now(timezone.utc).isoformat()
print(json.dumps({'entries': names, 'listed_at': now,
                  'empty_check_completed_at': now if not names else None}))
PY
```

Permission errors, non-directory paths and unreadable messages are **not empty**.
For a large inbox, use the harness's paged filename discovery; a truncated list is
incomplete. Read complete new relevant message bodies, including every unresolved
request/receipt, before deciding what they change. Publisher staging names are not
delivered messages; unexpected final entries need investigation. Keep processed IDs
in task context or a compact reference in your own record when needed for resuming.
Do not rely on filename order or a filesystem timestamp to skip unknown messages.

After processing, record that actual time as `Last inbox check`; enumeration alone
does not advance it. A missing/empty inbox observed successfully does complete a
check. Recover any omitted decision-relevant message text after truncation. When
only some messages are processed, keep the last completed check time and name the
remaining work. Complete the startup check before first registration; the current
record format requires a completed event time or the explicit value `unavailable`.
Never invent an event if that check is blocked. Continue independent read-only
work while resolving access. Retain the
last completed check time through unrelated record publications. Reading bytes is
not resolving a receipt: record the actual outcome. Messages arriving afterward
belong to the next checkpoint; do not
wait for hypothetical future acknowledgments after all required handoffs are done.

## Job and handoff checkpoints

Use the existing record, not a second activity journal. Before launching a build,
test or generator that may outlive a tool reply, prepare its claimed outputs and
stable input identity and publish the launch checkpoint. At the first return to
agent control, use the tool's explicit running/completion status; some tools return
handles even for completed jobs. Record a handle as active only while completion
is unconfirmed. A job may finish before the next check; report the
observed completion without inventing its exact finish time. Do not poll solely to
keep documentation busy or start a monitor the harness does not normally need.

| Event | Replace these existing fields together |
| --- | --- |
| Before launch | `Running jobs: launch pending; TMPDIR=/work/tmp/session ./build.sh test dev --label core --build-dir /work/build/session --jobs 2; claimed outputs /work/build/session and /work/tmp/session; expected about 30s; handle unavailable until reply`. Next check is the planned result/inbox check. |
| Tool reports running job `job-17` | Replace launch pending with `Running jobs: build job job-17 via this harness on example-host; same claimed outputs; completion unconfirmed`. Keep other genuinely active jobs. A handle identifies the job, not the session worker. |
| Tool returns completion | If no other jobs remain, `Running jobs: none`. Progress says, for example, `13/13 CTest entries passed; 3 internal ELF cases skipped (patchelf absent); source/configuration and log reference`. Remove the resolved blocker and set Next action to the actual remaining work. |
| Nonempty inbox processed | Read and interpret each pending message, then capture Last inbox check. For a verified release notice, replace `waiting for owner` with `release REF inspected; acquisition pending`, and set Next action to prepare/acquire. Reading a notice does not itself acquire the file. |
| Shared summary released | Remove only that claim, record release/provenance/hashes and stopped writers, replace `awaiting`/`append next` with `released; separate evidence remains`, and stay active for that work. Notify after publication. |
| Separate evidence completed | Replace `evidence next` everywhere in current status with its completed result. Resolve remaining jobs/receipts, then close using the output rule below. Prior startup facts remain labeled as history. |

A short synchronous command that finishes within one invocation needs no fabricated
running stage afterward. Record its relevant result at the next checkpoint; keep
the launch status truthful if it might yield or block. Ordinary read/search calls
do not each need a checkpoint. Combine job, inbox and scope changes into one update
when they coincide. Never hold the registry mutex while a command runs.

Capture event times **after** observing the result or processing messages, not at
wrapper invocation start. A job result observed at `10:02:00Z` and a nonempty inbox
processed at `10:02:57Z` give those two event fields. Publishing the reconciled
record at `10:03:00.123Z` changes Updated only. An unrelated publication at
`10:03:30Z` retains both earlier event times. Do not infer meaningful progress from
changing a text section or mark an inbox processed by printing its bytes. Resolve
what the messages change first; combine those decisions with jobs, blockers and
Next action in the same snapshot. Fractional UTC times avoid invented clock ticks.
Clock uncertainty remains explicit. The checker cannot establish these facts.

Do not defer an observed job completion or processed request until a contested
acquisition succeeds. Publish the truthful status with unchanged claims first
when that acquisition cannot proceed; preserve the pending acquisition as the
remaining work. Use semantic stopped-writer evidence from the release, not an
assertion that another agent used one exact English phrase. Missing or ambiguous
evidence still stops acquisition.

Inspect the underlying test summary and exit result, not just a green wrapper or
the exit code of `tail`/`tee`. Distinguish internal skips and setup failures from
executed assertions. Before replacing a log that explains a fix, keep a distinct
relevant attempt log or a concise command/failure/correction summary in your existing
evidence. No need to retain every transient output or copy logs into the record.

## Session record template

These are **filled format examples**, not facts to copy unchanged. Replace IDs,
paths, host, baseline, times and task details with observed values. Preserve the
exact headings/field labels. Add exact source/resource claims only after review.
The initial candidate can remain in memory/stdin until registration grants its
artifact directory. Do not write a candidate into `sessions/`.

```markdown
# example-session
- Tool / host / local chat reference: local harness / example-host / current task
- Parent / read-only helpers: root / none
- Task and approach: diagnose the reported build failure using the harness's normal research/tools, implement and validate the requested fix
- Checkout / coordination root (absolute physical paths): /work/software-foundation / /work/software-foundation/.agent-work
- Branch / starting HEAD / current HEAD: example-branch / aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa / aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
- Starting worktree and index changes (including work owned by others): clean
## Current checkpoint
- State: active
- Updated (UTC): 2000-01-01T10:00:00Z
- Last meaningful progress (UTC): 2000-01-01T09:59:40Z
- Last inbox check (UTC): 2000-01-01T09:59:55Z
- Next check (UTC) / action: 2000-01-01T10:05:00Z / inspect failure and request exact source scope
- Liveness mode / cadence: checkpoint / five minutes
- Last heartbeat (UTC), if supervised: none
- Run token / heartbeat file and writer, if used: none
- Owner process: unavailable; transient tool shell is not the session worker
- Running jobs: none
- Closed (UTC), if terminal: none
- Delete after (UTC): none
- Retention exception: none
- Contact: messages/example-session/
## Claims held
| Kind | Absolute path or agreed resource ID | Relative path | Intended change/use |
| --- | --- | --- | --- |
| directory | /work/software-foundation/.agent-work/artifacts/example-session | .agent-work/artifacts/example-session | candidates, isolated probes and logs |
| directory | /work/software-foundation/.agent-work/notes/example-session | .agent-work/notes/example-session | relevant unresolved findings |
## Baseline and dependencies
- At startup: clean worktree/index; initial scope was read-only diagnosis. Current ownership is in Claims held.
## Progress and checks
- Startup baseline and complete claims reviewed; implementation and validation pending.
## Blockers and handoff
- None; read-only diagnosis next. No source write authorized by this record.
```

Keep progress current rather than appending corrections to contradictory statements.
For example, after a failed test is fixed, replace the current failure/blocker and
retain the failed command only as concise diagnostic history. A shared-file release
normally leaves the session **active or waiting** while other work/receipts remain:
remove that claim, advance Updated, record release provenance and continue useful
work. Do not tie that release to whole-session closure.

This terminal example follows the same illustrative session after its work and
receipts are resolved. Real outcomes may instead be `failed` or `cancelled`.

```markdown
# example-session
- Tool / host / local chat reference: local harness / example-host / current task
- Parent / read-only helpers: root / none
- Task and approach: diagnose reported build failure, implement and validate
- Checkout / coordination root (absolute physical paths): /work/software-foundation / /work/software-foundation/.agent-work
- Branch / starting HEAD / current HEAD: example-branch / aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa / aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
- Starting worktree and index changes (including work owned by others): clean
## Current checkpoint
- State: done
- Updated (UTC): 2000-01-01T11:00:00.123Z
- Last meaningful progress (UTC): 2000-01-01T10:59:25Z
- Last inbox check (UTC): 2000-01-01T10:59:50Z
- Next check (UTC) / action: none / closed; no pending work or receipts
- Liveness mode / cadence: checkpoint / closed
- Last heartbeat (UTC), if supervised: none
- Run token / heartbeat file and writer, if used: none
- Owner process: unavailable
- Running jobs: none
- Closed (UTC), if terminal: 2000-01-01T11:00:00.123Z
- Delete after (UTC): 2000-01-31T11:00:00.123Z
- Retention exception: none
- Contact: messages/example-session/
## Claims held
None.
## Baseline and dependencies
- At startup: clean worktree/index; initial scope was read-only diagnosis. Current ownership is in Claims held.
## Progress and checks
- Example outcome: diagnosis found no source fix necessary; local probe and task-appropriate research/verification completed. No worktree/index changes or remaining validation.
## Blockers and handoff
- All writers stopped, claims released; no integration or receipt pending.
```

Use literal `none` for terminal Running jobs, with completed-job details in progress.
Empty claims are standalone `None.`, not a table or “none, except…”. Set real closure
time and deletion at closure plus 30 days; longer retention needs the explicit
[lifecycle exception](agent-lifecycle.md#delete-expired-sessions-and-unnecessary-history).
A closed ID cannot resume: create a new ID and acquire afresh. Legacy records need
not be migrated just to make the helper accept them.

### Finish output before releasing its claim

Finish the separate evidence/logs first; stop or join their writers, including
child processes, inherited output descriptors, `tee` and logging/cleanup traps.
Then prepare the terminal candidate and publish with stdout/stderr going to the
**harness response**, not into an artifact released by that publication. Shell
redirection opens a file before the command starts, and the publisher prints its
result after the record is installed. Both ends of that output lifetime need an
owner. Capturing output in memory is also safe; writing it later needs ownership.

The ordinary closing sequence is: finalize evidence → publish/verify closure →
clean only owned registry staging/lock → report through the harness. The registry
cleanup exception does not authorize more artifact/source writes. If another
output or integration genuinely remains, release the completed shared file but
keep that other scope claimed and the session active until its writers finish.
Do not add an intermediate closure or retain the shared file merely to log closure.

## Checked session operations

Use [agent_session.py](../tools/agent_session.py) for a supported board. It uses
the same records and atomic publisher, creates full lock-owner identity, checks
all claims under the mutex, verifies publication, and finishes owned-lock cleanup
before returning a receipt or calling dependent work. It never chooses the last
owner, stops jobs or infers that an inbox was processed.

The checked helper supplies a fresh random token for each registry acquisition.
The low-level publisher requires that token explicitly; matching the session ID
alone cannot borrow another acquisition, including a later acquisition by the same
session. `registry_mutex` yields an immutable `RegistryLock(fd, token)` for wrapper
authors; `commit` passes the token automatically. A token is an accidental-misuse
guard, not authentication against a participant that can read/alter the board.
Do not extract one from an existing lock to bypass a rejection. Already-held
tokenless locks remain owned: their holders finish/release normally or follow
recovery; never retrofit a token into somebody else's lock.
Keep the reader, publisher and transaction wrapper at a compatible tested revision
through each operation. Coordinate helper upgrades while registry writers are
quiescent; do not mix old callers with a new publisher mid-transaction. This is
an integration dependency, not permission to edit another holder's metadata.

Each unrelated chat can call this helper directly; it needs no parent controller.
For a worker that cannot reliably follow the protocol, its harness adapter performs
these operations and enforces allowed writes, or confines it to a private checkout
and outputs. Test denied writes to shared source, board, build trees and common Git
state through the actual available tools before treating this as enforced isolation.
Keep integration serialized by ownership; textual merge success is not exclusion.

When adopting changed helpers or a new board filesystem, qualify the helpers with
their focused tests using a claimed temporary root on that filesystem as well as
normal regression coverage; `/tmp` success alone may miss mount-specific behavior.
Reuse that environment evidence at startup rather than rerunning tests per agent.
An unsupported or failing primitive requires investigation or isolation, never
weaker publication/cleanup checks.

| Operation | Required caller input and result |
| --- | --- |
| `review(board, scopes=..., handoffs=..., inputs=...)` | Exact added scopes, relevant owner IDs and stable input files; returns complete ownership/relevant handoff evidence and a snapshot token, including absent input identity |
| `checkpoint(before, state=..., running_jobs=..., progress=..., handoff=..., next_check=...)` | Replace the complete current status together; claims remain unchanged, inbox/progress event times preserved unless explicit `inbox_at`/`progress_at` are supplied |
| `commit(board, session, candidate, reviewed, ...)` | Filled complete candidate, frozen review and exact own-record hash (or `create=True`); rechecks snapshots/overlaps, stamps Updated, publishes/verifies and cleans the mutex |
| `acknowledgment(receipt, scope=..., previous_owner=..., release_reference=..., request_id=..., review_note=...)` | Formats complete correlated text from an acquisition receipt; does not acquire, publish or infer the predecessor |

For imports, use `importlib.util.spec_from_file_location` with the helper's
absolute path, as its [tests](../tests/test_agent_session.py) demonstrate. Keep
review tokens in memory or an already-claimed artifact; do not print the complete
board token into the model context. Use the bounded reader to inspect the relevant
sections, and freeze the reviewed input/handoff identity **before** preparing the
edit. Recomputing a token/hash after a rejection without reconsidering the changed
facts defeats the check. Ordinary unrelated progress timestamps are excluded from
the ownership fingerprint. When the explicit review scopes cover every prior and
proposed claim, a scoped fingerprint permits unrelated, fully declared ownership
and handoff changes. Relevant input ownership and uncertain/legacy handoffs still
invalidate the review. Narrow or empty scope reviews retain the global fallback;
own-record replacement always checks its exact reviewed hash. All records and
claims are rescanned under the mutex; this is not a cached ownership index.

The CLI accepts a JSON object containing the function's named arguments. For
example, after preparing a claimed operation file with the actual reviewed token,
complete candidate and replacement hash:

```sh
python3 -B "$checkout/tools/agent_session.py" commit \
  --input "$coord_dir/artifacts/$session/operation.json" --json-errors
```

Inspect this result before a **separate** dependent tool call. Do not put a bare
acknowledgment/build command after it in the same shell. In Python, put dependent
work in `after(receipt)` or directly after `commit` with no exception-swallowing
fallback. `precondition` runs outside the mutex and must explicitly return `True`;
its exception/false result prevents publication and `after`. The helper rechecks
the frozen board/input evidence under the mutex afterward. No callback or command
runs while holding that mutex. If an acknowledgment or callback itself fails,
stop the rest and inspect the actual saved message/record before retrying; a
receipt is evidence of one completed operation, not a reusable ownership lease.

Build a successful release summary only after the guarded save and required
checks actually succeed. Run dependent subprocesses with `check=True` (or inspect
their exit status explicitly). Keep the sequence straight-line: acquire,
acknowledge, save, verify, stop/join writers, then construct and publish the release.
Never publish a prewritten success summary from `finally` or a separate command
after an unchecked failed patch/test. A failure may still be released after saved
state is reconciled and all writers stop, but the record must identify the failed
step and the exact unchanged or partially changed source; it must not claim tests
that never ran. The helper cannot verify the truth of a caller's free-text report.

After a successful acquisition, use the acknowledgment builder to avoid omitting
correlation fields. For example, while the exact file and artifact claims remain held:

```python
message = session.acknowledgment(
    receipt, scope={"kind": "file", "value": "/work/software-foundation/src/component.cpp"},
    previous_owner="prior-session", release_reference="component-release-3",
    request_id="request-17",
    review_note="Resolved full owner chain; inspected stopped-writer release and saved source SHA256.")
ack_candidate.write_text(message)  # already-claimed artifact outside sessions/
board.publish_message(coord_dir, receipt["session"], "prior-session", "ack-17",
                      str(ack_candidate))
# Only after successful atomic message publication: guarded source edit.
```

Use actual values from the reviewed handoff. For an unsolicited acquisition, use
an explicit explanation such as `none: independent acquisition after release` for
`request_id`. The scope must exactly match a canonical granted receipt claim;
the builder rejects missing, blank, malformed and multiline fields. It includes
the acquisition record hash and timestamp. The CLI operation `acknowledgment`
accepts the same JSON arguments and returns `{"message": "..."}`. Neither form
publishes the message, proves a supplied receipt authentic/current, nor verifies
free-text release lineage; the caller still resolves the actual predecessor,
checks saved ownership and uses atomic publication before editing. Formatting or
publication failure stops dependent work.

`CoordinationError` remains a `ValueError`, and now exposes `code`, `stage`,
`uncertain`, `retry_action` and `as_dict()`. The CLI's `--json-errors` emits that
structured failure on stderr; success receipts are unchanged. Only clean
`registry_busy` and `stale_review` failures qualify for `retry_delay` advice.
It supplies bounded jitter, not an automatic retry loop: reread/replan changed
ownership, handoffs and inputs before constructing another request. A claim
conflict requires handoff or independent work. Publication, mutex cleanup,
callback or output uncertainty requires saved-state reconciliation; never replay
a candidate or dependent action just because the command failed. A witnessed
changing scan is typed `stale_review` only when every unresolved scan error is a
typed snapshot race; a concurrent malformed/unreadable record still blocks review.
Complete candidate lifecycle and previous-to-proposed transition validation occur
before staging/publication classification, so malformed closure or backwards
timestamps are clean caller errors. Publisher checks remain in place at the save
boundary; actual publication and cleanup failures stay uncertain.

The delay starts at 25–50 ms and doubles its window, with equal jitter within
the upper half and a saturated 2–4-second range. Retain the pending operation's
attempt count across busy/stale rejections; a successful observation alone is
not a completed operation. Reset after completion or an explicit new plan. This
reduces full-board reader traffic at high contention without a controller or
worker-count oracle. The default eight-attempt limit and explicit maximum of 32
are unchanged; exhaustion still stops. A bounded deadline remains necessary,
and this policy does not guarantee fairness.

Pass `handoffs_reviewed` with the IDs whose returned candidate/uncertain handoffs
you actually inspected when adding scope. This includes an intervening closed
owner even if the original notice named another owner. Review release references,
parent-directory scope, stopped writers and acquired-from chain; checking IDs
alone does not establish those facts. Ambiguous prose requires resolution, not
blindly copying all IDs to satisfy the API. New scope lines make discovery easier.

Legacy errors never mean empty claims. An explicit `legacy_reviews` entry carries
that record's exact SHA-256, manually interpreted canonical claims and a concrete
review reason. Read its whole claims, relevant metadata and provenance first.
Changed/missing bytes invalidate the interpretation; no automatic skip, forced
migration or repeated approval is required. A legacy **own** record still uses
an explicitly qualified repair wrapper or coordinated recovery until properly migrated. Unknown
alias/format/filesystem cases similarly use manual review or isolation, never a
less safe fallback. Helpers cannot enumerate every hard-linked descendant or
establish continuously stable inputs: retain the workflow's alias and snapshot rules.

Use `checkpoint` to clear a completed job and reconcile current requests even if
an acquisition failed. Supply observed event times only when those events occurred;
a successfully processed empty inbox is an event, a nonempty filename listing is
not. The builder cannot close a session: prepare the full terminal candidate with
empty claims and stopped writers, then use `commit` without `after` (terminal callbacks are rejected).
Send its final output to the harness. Failed/uncertain closure does not reopen the
old ID, and a successful closure receipt never authorizes another artifact write.

## Guarded source edits

[agent_edit.py](../tools/agent_edit.py) provides a bounded synchronous save for
separate chats and harnesses. First acquire the file normally. Supply the exact
current own-record hash, the source hash inspected while preparing the edit, and
complete replacement bytes. The Python entry point is:

```python
receipt = editor.edit(board, session, source_path, expected_sha256, content_bytes,
                      record_sha256=current_record_sha256,
                      legacy_reviews=exact_manual_assessments)
```

Import it by its absolute path as with the session helper. For the JSON CLI,
`content` is UTF-8 text; the remaining keys match the function arguments:

```sh
python3 -B "$checkout/tools/agent_edit.py"   --input "$coord_dir/artifacts/$session/edit-request.json"
```

Prepare that request in memory or an already-claimed artifact. The editor checks
your current file/covering-directory reservation and every competing claim,
stages complete bytes, then under the short registry mutex rechecks the exact
record, source bytes/inode and staging identity before atomic replacement. It
verifies saved bytes and flushes the directory before returning. This guards
against stale buffers and avoids a partially truncated source after interruption
during staging. It does not claim power-loss durability on every filesystem.

The supported scope is existing regular files of at most 8 MiB, canonical paths,
one hard link, ordinary permission bits, current effective uid/gid and no extended
attributes/ACLs. Mode is preserved; inode identity changes. Board paths are
excluded: records/messages still use their dedicated publication primitives.
Unsupported metadata, aliases or filesystems fail without a direct-write fallback.
Use an appropriately qualified metadata-preserving editor for those cases.

Success reports source preimage/postimage hashes and `claims_released: false`.
Failures expose `EditError.code`, `uncertain` and `as_dict()`. The CLI reports
operation errors as JSON on stderr; argument-parser usage errors remain text.
An uncertain replacement, cleanup or missing receipt means
inspect saved source, staging and reservations before doing anything dependent.
Keep the reservation through required validation and release it separately.
Clean `registry_busy` or `stale_review` errors preserve their code only if no source
replacement was attempted and staging cleanup completed. They permit bounded
backoff and fresh ownership/source review; changed inputs still require replanning.
Do not retry every `EditError`, nor treat a busy timeout as a released reservation.

This is an edit adapter, not arbitrary job supervision or a security boundary.
Never release/change your own reservation concurrently with an edit invocation,
including staging before its mutex acquisition. Join all outstanding edits,
queued saves, generators and child/output writers first. A resumable editor or
unrestricted tool can bypass the adapter; each harness must enforce its own
permissions when that risk needs exclusion. A common task controller is unnecessary,
but agreement on one board and compatible reservation semantics remains essential.

## Publish a record

This low-level interface is for qualified transaction implementations and
maintenance. Ordinary workers use `commit` above; these commands do not acquire
or release a mutex and must not be assembled into an improvised locking script.

The optional [publisher](../tools/agent_publish.py) requires POSIX descriptor-relative
operations, no-follow path opens and same-filesystem hard links. Unsupported
platforms/filesystems fail without a direct-write fallback. Resolve real paths
before invoking it; it rejects symlinks in board/source paths. It provides complete
atomic visibility, not a daemon, ownership arbiter, recovery mechanism or guarantee
of power-loss durability. Windows/native harnesses need a tested wrapper using
equivalent primitives or isolated writes; this helper is not cross-platform qualification.

For an existing session, prepare the **whole** replacement in its claimed artifacts.
Check its structure/content before acquiring the mutex. This is a proposal, not an
event that advances inbox/progress time or grants a claim:

```sh
python3 -B "$checkout/tools/check_agent_record.py" \
  --before "$coord_dir/sessions/$session.md" \
  --after "$coord_dir/artifacts/$session/candidate.md"
```

A pass checks format/timing, not ownership, factual status, release provenance or
stopped writers. Keep the reviewed current record's SHA-256 as `reviewed_sha256`.
Do not recompute that value simply to override a stale-baseline rejection.

If the **existing** record is malformed or legacy, the checker/publisher deliberately
reject it even when the replacement is well formed. Review its complete claims and
handoff manually, prepare the corrected candidate outside `sessions/`, and use the
[equivalent publication procedure](#equivalent-publication-without-the-helper) under your mutex after rechecking those exact
old bytes and all other claims. Preserve ownership, event times and unresolved
work; do not delete/re-register the record to evade validation or lose its claims.
Repairs to another or closed owner's metadata also require the lifecycle procedure.
The helper can be used again once the current record uses the supported format.

The following publication commands run **only inside your already-held mutex**.
Acquire it by one exclusive `mkdir "$coord_dir/registry.lock"`. Write its owner
metadata immediately, including a plain `- Session: YOUR_ID` line, host, UTC,
lock-holder PID/start identity when available, intent and
`- Acquisition token: RANDOM_32_LOWERCASE_HEX`. The acquiring wrapper generates
and retains this fresh token as `lock_token`; it never reads a preexisting lock
to obtain permission. Review all current claims
and relevant releases again under that mutex. If a prior snapshot changed, release
and reassess; do not hold the mutex while investigating or waiting for another agent.
Finalize Updated from the current UTC clock immediately before publication; keep
actual inbox/progress times and reconcile current jobs, blockers and Next action.
Refresh a prepared release's resulting hash from the verified edit. Do not reuse
an old timestamp just because a proposed record passed earlier. The publisher
validates the final bytes again; equivalent manual publication must do the same
checks. This last metadata update is part of publication, not another checkpoint.

For an update after the complete review:

```sh
python3 -B "$checkout/tools/agent_publish.py" record \
  --board "$coord_dir" --session "$session" \
  --candidate "$coord_dir/artifacts/$session/candidate.md" \
  --expected-sha256 "$reviewed_sha256" --lock-token "$lock_token"
```

For first registration, pipe the complete, filled candidate from memory/stdin
instead of creating an unclaimed artifact. With the same ownership review and
matching mutex already held, the command receiving that input is:

```sh
python3 -B "$checkout/tools/agent_publish.py" record \
  --board "$coord_dir" --session "$session" --candidate - --create \
  --lock-token "$lock_token"
```

The helper validates candidate format, checks the owner and acquisition token, stages bytes **inside
the owned mutex**, and publishes atomically. New records cannot replace an existing
ID. Updates compare the reviewed hash and recheck the record/lock before replacement.
They rely on cooperating writers honoring the mutex; this is not an operating-system
compare-and-swap against uncooperative edits. Nothing is staged in `sessions/`.

Confirm the saved record matches the candidate. In a finally/cleanup path, remove
only your own remaining staging and `owner.md`, then `rmdir` your empty lock.
Never recursively remove an unfamiliar/nonempty lock. Check failures through the
caller as described below. The helper does **not** acquire/release the registry
mutex, scan other claims, or close another session.

### Stop dependent work on publication failure

Treat the whole acquisition as a checked operation, starting with its
preconditions. A separate tool call with its result inspected before the next
dependent action is sufficient; no extra approval or
checkpoint is required. In a combined script, explicitly gate **every** dependent
acknowledgment, ownership assertion, mkdir, redirection, generator and job launch.
Failure diagnostics or a recovery request do not assert acquisition and may still
be sent. Newlines, semicolons, the last command's
exit status, or `set -e` alone are not a reliable substitute.

Use the checked helper's `after(receipt)` callback for composed dependent work,
or inspect a successful `commit` result before a separate tool call. The helper
finishes verified owned cleanup before either path proceeds. Inside a callback,
propagate each failure so a failed acknowledgment stops subsequent writes/launches;
for subprocesses use
[`subprocess.run(..., check=True)`](https://docs.python.org/3/library/subprocess.html#subprocess.run).
Do not ask a worker to invent `publish_and_verify` or `release_owned_mutex` shell
functions. A controller needing custom composition must qualify the whole caller
with the failure-ordering tests, including successful publication followed by
cleanup failure. Preserve the original failure; successful cleanup is not success.

A nonzero result can occur **after** atomic publication, for example when deleting
the private staging link or printing the result fails. Stop dependent work and
inspect actual record/message bytes and ownership before retrying; do not assume
the old state remains, restore an old claim, or recompute a hash to bypass rejection.
A complete terminal record stays terminal even if its closing command reports an
error; new work requires a new ID and fresh acquisition. Inspect an uncertain send
before choosing another message ID, so a successful delivery is not duplicated.
Retain failure evidence only within scope still owned after that inspection.

This includes failure before invoking the publisher: an assertion about the
reviewed owner, expected hash or stopped writers must stop a following shell
command too. An acknowledgment is not harmless merely because it edits no source;
other agents can act on its ownership assertion. After an uncertain send, inspect
the same immutable message ID before retrying, never blindly create another one.

### Equivalent publication without the helper

This is an implementation/review specification for a qualified wrapper, not a
worker fallback. Use equivalent filesystem primitives only where their required
semantics are supported and tested. A custom wrapper must preserve all of these
properties, not just atomic visibility; otherwise isolate writes:

1. Prepare the complete body in memory or already-claimed artifacts. For records,
   validate the full record and transition, not only changed fields; the checker
   is optional, its invariants are not. Keep the exact reviewed old bytes/hash.
2. For registration or changed claims, exclusively create the mutex and record
   session, host, UTC, lock-holder role, PID/start identity when available, intent
   and a fresh acquisition token passed explicitly to the publisher.
   Recheck all complete claims, provenance, stopped writers, target bytes and facts
   under it. Investigate uncertainty after releasing your mutex; do not wait in it.
   Messages need no registry mutex or claim scan. Unchanged-claim record updates
   may omit it under the workflow's single-writer rule.
3. For records, finalize Updated without replacing actual event times and revalidate
   final bytes. Stage complete, closed bytes on the destination filesystem, outside
   `sessions/`: records inside the owned mutex, or already-claimed artifacts for a
   mutex-free update; messages in their destination inbox as private staging files.
   Reject unsafe aliases/nonregular paths. Recheck directory identity, owned lock
   identity when applicable, and the expected old record before publication.
4. Use atomic no-replace publication for new records/messages; atomic replacement
   for the exact reviewed existing record. Exclusive creation followed by writing
   is not complete publication. The mutex-free operations retain the same
   applicable validation and atomicity checks.
5. Verify saved bytes. Preserve errors through narrow owned cleanup and follow the
   uncertain-result procedure above. Never delete foreign staging/locks or use
   direct writes as an unsupported-primitive fallback. Use the closure output rule
   for every path capable of writing after the record transition.

Atomic rename/replace and exclusive hard-link publication are distinct operations:
replacement may overwrite a destination, while a link fails when that name already
exists. See the primary [Python filesystem documentation](https://docs.python.org/3/library/os.html#os.replace)
and [link documentation](https://docs.python.org/3/library/os.html#os.link). Check your
shared filesystem's actual semantics; cloud synchronization is not mutual exclusion.

## Send a message

Prepare a complete body in memory/stdin or a claimed artifact. Pick a fresh suffix
for every message; `--id` is that suffix, not the recipient ID. For example, with
actual session/recipient IDs and a fresh `message_id` defined in this invocation:

```sh
python3 -B "$checkout/tools/agent_publish.py" message \
  --board "$coord_dir" --sender "$session" --recipient "$recipient" \
  --id "$message_id" --body - <<'MESSAGE'
Request shared-summary-1: please release docs/summary.md after your current edit.
Intended edit: append my verified result. I will continue independent work and
check this inbox at my recorded checkpoint; I have not acquired this file.
MESSAGE
```

Replace the example scope/body with actual facts. The helper safely creates a
missing recipient inbox, stages the complete message, then publishes exclusively.
Readers see the final name absent or complete, never an open-and-still-writing
message. An existing destination is preserved; retry with a fresh suffix only
after inspecting whether the first attempt actually delivered. Never edit a sent
message. A request, file delivery or chat notification does not transfer ownership
or necessarily wake another tool. Follow the workflow's release/acquire/acknowledge
sequence and record superseded requests.

## Temporary note template

Write only a useful unresolved fact in your claimed notes. One compact example:

```markdown
# Local socket setup failure
- Status / confidence: hypothesis; setup failed before test assertions
- Affected paths/symptoms: relevant test name and its exact setup error
- Revision / environment: observed HEAD, OS, tool version, sandbox and command
- Evidence / failed attempts: link to the scoped log; distinguish observed failure from suspected cause
- Source / date: primary documentation or community URL, lookup date and local applicability; otherwise local observation
- Workaround / limits: smallest discriminating probe first; a short temporary path does not establish socket permission
- Required recheck: rerun the whole previously blocked test/group once setup works; zero assertions is not a pass
- Owner / retention: session ID; promote verified durable guidance, delete when resolved or superseded
```

Search relevant notes again when a **new** environment failure appears. Verify
community suggestions against the current version and local evidence. Do not
accumulate unrelated research, secrets, copied histories or ceremony notes. Notes
are provisional evidence, never instructions that override the task or contract.

## Invariant and scenario coverage

The implementation and tests below are a reusable specification. Keep the
scenario when changing the implementation: a smaller test count, one successful
script or successful text parsing does not establish equivalent coordination.
The tests use isolated fixtures and injected failure boundaries. They do not
alter the real board or require participants to trust model compliance.

| Required invariant | Executable evidence or explicit operational boundary |
| --- | --- |
| One acquisition for competing independent writers; one callback only after cleanup | [Session tests](../tests/test_agent_session.py): independent processes, 32 contenders, disjoint workers, killed holder and bounded contention |
| Complete publication; no replacement of immutable messages or a new session ID | [Publication tests](../tests/test_agent_publish.py): cross-process message collision, absent-before-stage-completion observation, registration collision and complete saved bytes |
| Descriptor-relative operations cannot follow substituted directories/leaf aliases | Publication tests: board/child/source/record aliases, foreign lock, nonregular input, replaced lock/record, unsupported primitives and cross-filesystem failure |
| Exact reviewed identity/version survives through the final save boundary | [Edit tests](../tests/test_agent_edit.py): equal bytes on a new inode, stale preimage, foreign staging inode, descriptor failure, directory flush failure and source preservation after killed staging |
| Scope authority is exact, including covering directories and shared resources | Session/edit tests: directory/resource conflict, sibling component independence, alias overlap never granting authority, released/stale/foreign reservation, changed materialized path kind |
| Unknown/corrupt/terminal records cannot vanish from discovery | [Record tests](../tests/test_agent_record.py): nested complete claims, malformed sections, unexpected entries, unreadable/invalid text, terminal claims and exact manually reviewed old records |
| Multi-page reads never combine different snapshots or omit later errors | Record tests: large registry pages, changing/replaced entries, unbound later page rejection, complete Unicode document reconstruction and bounded section selection |
| New ownership follows the actual predecessor even when bytes never changed | Record/session tests: quiet closed intervening owner, covering scope, relay chain, partial/contradictory scope inventory and complete correlated acknowledgment |
| Disjoint useful work can proceed without ignoring shared dependencies | Session tests: scope-bound review accepts unrelated fully declared changes; unchanged-byte input ownership, incomplete handoffs, unknown entries and omitted held scope still invalidate |
| Failed validation, acquisition, publication or cleanup stops every dependent action | Session/publication tests: precondition, callback, acknowledgment/output/job gates, saved-byte mismatch, cleanup error and uncertain receipt after committed closure |
| Retries distinguish clean contention/observation races from uncertainty | Session/edit tests: typed busy/stale codes, saturated bounded jitter, concurrent malformed entries, cleanup uncertainty and callback/publication failures never offering retry |
| Checkpoints describe actual events and closure cannot conceal jobs/claims | Record/session/migration tests: independent progress/inbox times, unavailable events, completed-job reconciliation after rejected acquisition, future/backwards times, terminal replay/callback rejection, empty claims and retention exceptions |
| Migration cannot establish two authorities or silently discard provenance | [Migration tests](../tests/test_agent_migrate.py): live session rejection, stale reviewed snapshot, stopped-writer assertions, full retained source/messages/releases/dates, interruption on either side of authority switch, unknown protocol marker and partial initialization |
| Every real concurrent contribution survives both shared and disjoint workflows | [Stress tests](../tests/test_agent_stress.py): acquire, exact predecessor acknowledgment, guarded save, verification, release and terminal closure; complete contribution sets, ordered source digest chain, receipt correlation, every child joined |
| Existing compatibility sessions can finish safely before transition | [Compatibility tests](../tests/test_agent_board.py): revision contention, conservative path aliases, pending transfers, corruption, failed publication, independent claims, source inputs and job release/closure gates |
| Command success requires completed descendant output writers | [Process lifetime tests](../tests/test_process_tree.py): real joined/lingering/killed children, stable inherited log, premature finish rejection; Windows suspended-before-assignment and cleanup failure ordering; native Windows job breakaway rejection requires Windows execution |
| Liveness/contact/recovery information is truthful and actionable | [Lifecycle procedure](agent-lifecycle.md): exact host/start/boot identity where exposed; unavailable identities; supervised-only sidecar; positive writer exclusion and narrow recovery. Helpers validate fields and identify their own mutex process, but cannot prove human statements or stop external writers. |
| Cleanup cannot erase a needed predecessor or manufacture liveness | Lifecycle procedure: original closure age, exact-scope dependencies, transferred references, current owner, bounded receipt, 30-day default and seven-day exception review. No automated age-based takeover, process killing or semantic retention decision is supplied. |

Run the focused suite after changing any helper or adapting it to another
filesystem. Set a claimed temporary root **on the board's actual filesystem**;
qualify remote/mounted storage separately from a local fixture. The following
commands assume the output and temporary directories have already been claimed
and created, and the input source snapshot is stable:

```sh
TMPDIR="$owned_tmp" python3 -B -m unittest discover -s "$checkout/tests" -p 'test_agent*.py' -v
```

The process stress suite uses 16 workers by default. Set
`FOUNDATION_AGENT_STRESS_WORKERS=128` for the maximum supported process cohort,
or another integer from 2 through 128 after inspecting shared CPU/memory limits.
Run it as a separate job with its own log; do not overlap it with a heavy
measurement-sensitive workload. Every subprocess has a bounded completion
policy and is joined; a parent result alone is not the release condition.

```sh
FOUNDATION_AGENT_STRESS_WORKERS=128 TMPDIR="$owned_tmp" python3 -B -m unittest discover -s "$checkout/tests" -p 'test_agent_stress.py' -v
```

The process test validates the filesystem protocol and complete useful edits.
It is not evidence that independent AI sessions obey prompts, that research was
adequate, or that uncooperative tools are confined. When harness enforcement is
required, independently test denied writes through every actual tool to shared
source, board, Git state and output trees. Verify the resulting application with
independent public-behavior tests after integration; coordination success alone
cannot establish correct program behavior.

Record Python/runtime and filesystem information, exact source identities,
commands, worker count, executed tests, skips and final outcomes with concise
failure evidence. POSIX-dependent suites are unsupported on native Windows;
a successful runner that skipped them must say so. Guarded-save tests additionally
need extended-metadata inspection. If a filesystem cannot supply user extended
attributes, the metadata-preservation case may be skipped; report this narrower
limit. Actual permission/link/replace failures on an intended supported mount
are qualification failures, not a reason to skip the check. API discovery never
certifies power-loss durability, hostile-writer exclusion, arbitrary network
filesystems or a native adapter that has not passed equivalent scenarios.

## Review discipline for shared work

Keep these constraints in the normal workflow instead of adding mandatory
journals, extra approvals or research quotas:

- Make the requested deliverable concrete before optimizing coordination. Keep
  behavioral requirements, research, implementation, external consumer validation
  and delivery in the current task/progress fields. A tidy board is supporting
  evidence, never the deliverable itself.
- Prepare a shared summary contribution and its evidence before acquiring the
  summary file. After acknowledgment, save and verify it, release that file
  promptly, then finish independent reporting. Do not use one hot append-only
  progress file for every worker or retain a completed claim while waiting for an
  unrelated receipt. Keep one current request per exact scope and reroute it to
  the actual owner when a prior request is superseded.
- Give related changes one integration owner/order and a named invariant resource
  when necessary. A directory claim must actually be narrowed before a child is
  transferred. A parent assignment, unchanged bytes, message exception or clean
  text merge does not establish new ownership or correct combined behavior.
- Bind each tool to the right absolute checkout. Declare all side effects before
  running it: generated files, caches, temporary roots, index/refs/config,
  packages, ports, devices and output descriptors. A unique filename does not
  establish ownership. Isolated output directories do not freeze shared inputs.
- Preserve concise discriminating failure evidence. A repeated symptom does not
  confirm a cause, a green wrapper does not expose skipped inner checks, and
  setup failure before assertions executes zero assertions. Repair the verified
  prerequisite and rerun all previously blocked coverage. Do not shorten a test
  by discarding its difficult condition or claiming narrower coverage as complete.
- Observe and process inbox messages at actual control boundaries, including
  after a yielded command resumes. Do not defer truthful job completion behind a
  contested acquisition or advance an inbox timestamp for enumeration alone.
  Correct current jobs, blockers, progress and next action together.
- Stop the entire dependent chain on error. A success release must be constructed
  only after its actual save and required checks. Never publish it from `finally`
  after a failed patch/test. Reconcile an uncertain send with its same immutable
  ID before retrying; do not duplicate a possibly delivered acknowledgment.
- Finish inherited streams, queued editors, cleanup traps and child writers before
  release. Report closing-operation output to the harness or memory, not a file
  whose claim that operation releases. An error after committed closure neither
  restores the old claim nor permits the closed ID to resume.
- Preserve only useful temporary facts and necessary live lineage. Do not create
  duplicate receipts or shadow archives. Copying a record does not restart its
  retention age. Closed ownership can still matter to a waiting recipient who
  does not yet know that owner's ID, so check exact scope as well as named links.
- Keep uncertainty explicit. Unknown clocks, process namespaces, identity, mount
  semantics or access failures are reasons to investigate or isolate affected
  writes. No timeout, missing PID, stronger model or newer timestamp grants scope.
