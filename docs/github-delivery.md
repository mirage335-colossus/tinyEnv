# GitHub delivery of exact retained bytes

[`github_release.py`](../tools/github_release.py) connects the local dependency,
release and certification contracts to GitHub. It supports an immutable application
inventory, append-only certification attempts and a separately controlled Latest
pointer. The implementation uses the authenticated `gh` executable through argument
arrays. Pagination consumes the complete concatenated JSON page stream and does
not require the newer `gh api --slurp` option; older distro-provided CLI versions
remain usable. Empty, malformed, truncated and failed page streams are rejected.
It never builds missing inputs, force-updates a tag or uploads with overwrite
enabled. Newly verified base SDK groups retire superseded groups in the same
consumer slot; published application assets remain untouched.

The transport adapter has **offline transport tests** and concrete
[hosted lifecycle workflows](ci.md#executable-hosted-lifecycle). Those tests do not
prove live publication, repository permission setup or successful hosted execution.
Qualify the deployed workflow revision and repository settings before production use. Read [release requirements](releases.md), [dependency groups](dependencies.md)
and [certification](certification.md) first.

## Explicit execution and owned inputs

Each command takes one strict JSON request. Unknown arguments, duplicate JSON
fields and nonfinite values fail. Mutation commands return a local plan by default:

```sh
python3 tools/github_release.py publish-candidate --input build/publication-request.json
```

Only the separate command-line `--execute` option enables changes to GitHub. An
`execute` key inside the request is rejected. The corresponding Python functions
also default to `execute=False`. A plan validates local inputs and identifies their
exact hashes, but does not authenticate, query or reserve a remote tag. Its digest
is a review aid, not an authorization token. Executing later revalidates the inputs;
the caller must compare against its reviewed plan and hold those inputs unchanged.

`fetch-base` and `fetch-rust-base` are read operations: they read GitHub and create a new local destination,
without making remote changes. It never falls back to compiling dependencies.

For an authorized publishing job, execute the same frozen request explicitly:

```sh
python3 tools/github_release.py publish-candidate --input build/publication-request.json --execute
```

Assign one publisher for a repository's release lifecycle. Hold the agreed release
resource claim from preflight through final receipt, including the shared `base`
release and Latest pointer. Local [coordination](agent-coordination.md) protects
cooperating sessions on one agreed board; it is not a distributed GitHub lock.
Base/application publication, certificate attachment, promotion and native
acceptance share the repository-wide release-lifecycle concurrency group.
Signed-channel publication uses a target-scoped group so independent architectures
can progress concurrently. Use `cancel-in-progress: false`; each hosted or manual
publisher must honor the lock for the state it mutates. See the
[distribution ordering contract](distribution-release.md) for predecessor gates.

Keep the source checkout, assembled release, requests, SDK groups, policy, reports
and retained logs stable during an operation. Own separate temporary and receipt
directories. Set `TMPDIR` on POSIX or the supported temporary-directory setting on
Windows to owned space. The helper rechecks bytes and observed identities at
critical boundaries; it cannot provide a distributed transaction or stop an actor
that ignores the agreed exclusion. No remote compare-and-swap API is assumed.

Use a protected publisher environment and the least repository permissions needed
for release/tag creation. Authenticate `gh` through its supported environment or
credential store; never put secrets in request JSON, command arguments, published
evidence or console diagnostics. The helper suppresses CLI stderr in its own
errors, but this does not sanitize arbitrary logs bundled by a caller. Review
evidence for secrets before permitting publication.

## Command contracts

All requests use `repository: "OWNER/REPO"`. The supported service is `github.com`;
the transport pins that host explicitly. Tags and asset names must be portable
single components. Slash-separated tags, unsafe path components, platform-reserved
names and ambiguous names that differ only by letter case are rejected. Commits
are complete lowercase 40- or 64-character object IDs. Generated tags directly
identify commits; annotated tags are deliberately outside this adapter's contract.

The following fields are required unless a default is shown. Filesystem paths
belong to the local caller. `delivery` is the complete generated object from the
candidate plan or successful publication receipt, not a reconstructed abbreviation.

| Command | JSON request fields | Result and required invariant |
| --- | --- | --- |
| `fetch-base` | `repository`, `recipe`, `output` | Fetch the exact recipe's binary/source/checksum group into a new directory; verify all three before publishing the local directory. |
| `publish-base` | `repository`, `recipe`, `group`, `source_commit` | Verify the complete local group, reuse an exact existing group or append a new group; never replace a partial or conflicting group. |
| `fetch-rust-base` | `repository`, `recipe`, `output` | Fetch and verify the complete exact Rust binary/source/checksum group into a new directory. |
| `publish-rust-base` | `repository`, `recipe`, `group`, `source_commit` | Verify and append or exactly reuse a complete immutable Rust group through the same base lifecycle. |
| `publish-candidate` | `repository`, `tag`, `directory`, `source_commit`, `packager_commit`, `publication_id`, optional `experiment: false` | Freeze delivery identity, create an absent tag and draft, upload every required file, verify bytes and then publish without moving Latest. |
| `attach-certificate` | `repository`, `tag`, `directory`, `delivery`, `certificate`, `check_plan`, `policy`, `profile`, `reports`, positive `attempt` | Reproduce the certificate, retain complete evidence, append its uniquely named bundle and envelope, verify uploads and preserve all existing assets. |
| `promote` | `repository`, `tag`, `directory`, `delivery`, `policy`, `profile`, `run_id`, positive `attempt`, `certificate_sha256` | Reproduce the exact selected remote certificate against current policy, recheck all identities, change Latest and verify the final pointer. |

`recipe` is the digest produced by the [dependency store](../tools/dependency_store.py).
For Rust commands it is `rust_sdk.recipe_identity` from the checked-in recipe
and producing helper bytes. `rust_sdk.verify_group` checks the complete
`rust-sdk-HASH-binary.tar.gz`, `rust-sdk-HASH-sources.tar.gz` and
`rust-sdk-HASH-SHA256SUMS` group, including source binding and inventories.
No binary-only fetch or publication shortcut is supported. Rust uses the same
immutable base lifecycle and draft transport conventions as the C++ groups;
normal application operations consume verified local inputs. Implementing these
commands does not itself publish any Rust group or qualify a live operation.
`group` contains exactly its verified binary archive, corresponding source archive
and checksum manifest. `directory` is the complete output of
[`release.py assemble`](../tools/release.py). `reports` is an explicit ordered array
of result JSON paths, one selected result per planned check. The selected report
can retain an earlier check attempt under the unchanged plan; its actual attempt
remains visible. The delivery `attempt` names a new immutable certification
publication, never an excuse to overwrite an older report.

For example, a candidate request has this structure. Replace the example values
with the exact reviewed release and commit identities before execution:

```json
{
  "repository": "example/project",
  "tag": "v1.0.0",
  "directory": "dist/candidate",
  "source_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "packager_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "publication_id": "candidate-1",
  "experiment": false
}
```

Retain the entire printed receipt in owned append-only storage. Preserve its
`delivery` object for attachment and promotion requests. `certificate_sha256` is
the digest of the actual certifier output, not the digest of its remote envelope.
The attachment plan includes both filenames, their hashes and the full envelope,
making the intended run and attempt reviewable before any upload.

## Dependency base lifecycle

The `base` release is a published prerelease named `base`, and must never be Latest.
Creating it first reserves an absent direct Git tag at `source_commit`, then creates
a draft. A new recipe group uploads its binary and source archives before the
checksum manifest. The caller obtains no valid reusable group until all three
exist, download correctly and pass `dependency_store.verify_group`.

An existing complete published group is reused only after verifying the supplied
local group and comparing every remote asset size and SHA-256. This reuse does not
download unchanged bytes again; the original publication still requires full
readback. Binary/source uploads and readback are bounded parallel operations, with
the checksum uploaded after both payloads finish. A partial group, changed bytes or incompatible release state fails
without overwrite. Once a new group passes complete readback, publication verifies
older complete groups and removes only those matching its SDK family, host,
target and capability/configuration profile. Rust and C++ groups remain separate.
Unknown, partial, corrupt and differently targeted groups are preserved. Cleanup
uses exact reconciled asset IDs, removes each checksum marker before its payloads,
and stops on a changed inventory or uncertain mutation without retrying deletion.
Discovery is bounded to 64 groups per SDK family. Existing recipes reused without
publication are not a cleanup trigger. Application release copies remain intact;
old base-only recipe selectors must be updated or restored from an independently
retained complete group. The base tag's current commit is frozen and rechecked;
adding a later group does not move that tag to the new recipe's source commit.

GUI input publication applies the same rule to complete older groups with the
same kind, upstream and license. It verifies their own retained foundation locks
and patches before retiring exact IDs. Legacy SDKs have no small target/profile
index, so classification downloads their binary archives; matching removals also
verify source/checksum bytes. This happens only when publishing a new group,
not during ordinary builds or exact group reuse.

Fetching validates repository visibility, base state, tag and the complete paged
asset inventory. Missing recipes fail clearly. Authentication failures and unknown
responses never become cache misses. A failed download remains in temporary staging;
it does not publish a usable destination. The assembly job uses `fetch_bases` to
share discovery across its recipes inside one process. It downloads and verifies
the complete groups with four transfer workers. Each SDK starts verification as
soon as all of its files finish, using a separate pool of at most four verification
workers while other transfers continue. Failure joins both pools before removing
staging; no partially verified destination becomes available. It performs one
fresh reconciliation of the base release, tag and asset identities, then publishes
the staged output directory. The batch uses seven metadata reads when inventories
fit one page, instead of seven per recipe. It introduces no cross-job metadata
artifact or persistent cache. Exact SDK source retention is required
for [recovery qualification](certification.md), even when cached binaries exist.

## Candidate and certificate lifecycle

Candidate planning calls the complete local release verifier, then freezes the
application source archive, exact `release.json`, every application archive and
retained dependency member. GitHub asset names are flattened from these paths;
any collision blocks delivery. `delivery.json` retains the original path mapping,
hashes, sizes, source commit, packaging commit, tag commit and publication identity.

Repository visibility is confirmed before absence checks. The helper lists every
release page, including drafts, and rejects duplicate matching tags. It creates
the Git reference before the draft; an existing release or orphan reference is
never silently adopted. This reservation still needs the caller's repository-wide
lock. After uploading, it lists every asset page separately, downloads each expected
asset by its remote ID, reconstructs the original tree and runs the complete release
verifier. Only then does it finalize the draft with `prerelease: true` and
`make_latest: false`, and verify the resulting state and pointer. This prerelease
state applies to ordinary candidates too, until explicit certified promotion.
GitHub can select the first normal release as Latest despite a false request;
keeping the candidate a prerelease excludes that fallback. The
[GitHub release API](https://docs.github.com/en/rest/releases/releases#create-a-release)
states that prereleases cannot be Latest. Do not weaken the independent pointer
check. After any uncertain outcome, inspect the exact release, tag and asset
identities before retrying; preserve the bytes and correct only reviewed lifecycle
metadata when necessary.

Ordinary candidates require equal source and packaging commits. An intentional
split requires `experiment: true`, receives the title `experiment`, remains a
prerelease and cannot pass this helper's promotion gate. Full commit strings alone
do not prove the bytes came from those commits: the publisher must construct the
source and packaging inputs from those reviewed revisions. The release manifest's
source identity and package checks bind the retained tree to the application.
The transport does not independently reproduce a Git commit from its tree archive
or authenticate the person who supplied a request.

Certification publication appends two assets:

- `certification-RUN-attempt-N.tar.gz`: the exact certificate, frozen plan, tested
  policy, ordered selected reports and every declared evidence file.
- `certification-RUN-attempt-N.json`: a small envelope binding the bundle digest,
  certificate digest, delivery identity, run, attempt, outcome and eligibility.

The helper revalidates the copied evidence before archiving it. It uploads the
bundle first and the envelope last. A failed or incomplete qualification can be
retained as a new attempt, but cannot promote the release. Every previous report
and binary remains intact. Unknown extra assets or incomplete certificate pairs
block subsequent mutations until explicitly reconciled.

Promotion selects one exact run, attempt and certificate digest. It downloads and
verifies the pair, checks a complete bundle file inventory, extracts it under the
strict archive policy and reruns the certifier against the current local support
policy. A changed policy, stale source, different application inventory, failed
required check, omitted mandatory scope or ineligible experiment blocks promotion.
The adapter limits uncompressed evidence bundles to 4 GiB; split oversized logs or
choose another reviewed evidence-storage contract before producing the candidate.

Immediately before updating Latest, promotion rereads the release, direct tag and
all remote asset identities. After updating, it rechecks those identities and the
Latest endpoint. Matching names or byte hashes alone are insufficient: replacing
an asset with identical bytes changes its ID and invalidates the earlier review.
Warnings retained by an otherwise eligible certificate remain visible; they do not
waive mandatory checks. Passing reports rely on trusted, reviewed check adapters
and runner provenance. A self-declared JSON assertion is not proof against a
malicious producer.

This protocol requires GitHub's immutable-release feature to be disabled because
it appends evidence after publishing a candidate. Application assets remain
immutable by enforced policy. If repository policy requires server-enforced
immutable releases, collect evidence before publication or place later evidence in
a separate durable store bound to the original inventory; qualify a corresponding
adapter rather than enabling overwrite or weakening repository policy.

## Rate-limited reads and bounded waiting

The shared transport follows [GitHub's rate-limit response rules](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#exceeding-the-rate-limit).
Read-only requests may retry an explicit rate response after its `Retry-After`
delay or exhausted primary quota's reset time. Recognized secondary limits use
bounded backoff. Confirmed transient HTTP 500, 502, 503 and 504 read responses
also use bounded retries, honoring `Retry-After` when present. Permission failures,
invalid complete data and other unrelated errors remain errors.
Each read or write-quota preflight permits at most eight attempts within a
180-minute deadline. Each transport instance shares a cumulative 180-minute
retry-wait budget; a single CLI invocation has a ten-minute limit. Waits
are interruptible in at most 60-second steps, with sanitized quota diagnostics
instead of credentials or raw private responses.

A paginated retry starts a fresh complete response inventory; it never accepts a
successful prefix of a failed read. Binary retries likewise use fresh temporary
files and discard partial response data. The normal complete byte and identity
verification still applies after transfer. Before writes, each transport client
reuses valid core-quota headers from its existing authenticated API responses for
up to 30 seconds, with a conservative local remaining allowance. It serializes
fallback read-only quota probes when observations are unavailable, stale or need
replenishment. The check can wait for 128 remaining
requests (or the entire quota for a smaller limit), but neither headers nor a
separate probe reserve repository capacity against other jobs. Best-effort
temporary-artifact cleanup explicitly disables that preflight and fails promptly
rather than waiting for a fresh quota window. A failed write or upload is never
automatically replayed. Preserve and
reconcile its outcome using the procedure below.

Budget quota waits separately from compilation and tests. Grouped bundle reads
and publications share authoritative run, producer and asset inventories at their
transaction boundaries. This avoids repeating those API requests for each input;
parallel downloads alone cannot reduce the request count. The workflow batches
independent cases while retaining their distinct results; see
[qualification batching](ci.md#grouped-qualification-work). Actual HTTP operations
share a process-wide limit of four, including nested transfer callers. Waiting
cannot guarantee service availability or replace a missing required result.

Lifecycle and transport entry points report sanitized per-process metrics on stderr.
They count observed API response pages separately from quota probes, actual CLI
calls, completed upload/download bytes and accumulated request/retry wait time.
They retain only numeric quota headers and add no API calls. Parallel operation
seconds are accumulated work, not elapsed job time; lost responses and legacy
upload commands may leave API request counts incomplete. Complete release quota
use still needs hosted measurement, including other simultaneous repository jobs.

## Failure, uncertainty and recovery

An API or CLI success is not sufficient evidence of publication. Every mutation
sequence verifies the resulting remote IDs, lifecycle and bytes. An exception
after the first attempted remote change yields `uncertain: true`, including a lost
output receipt after execution. The change may have completed. Stop dependent
uploads, retries and promotion; preserve the original request and local evidence.

Under the same publisher lock, inspect repository visibility, tag target, release
ID/state, complete paged assets and their downloaded hashes. Compare these with
the frozen request and receipt. Do not infer absence from a timeout, lack of local
output or inaccessible credentials. Do not rerun a mutating command merely because
its client failed. There is intentionally no automatic resume, rollback, deletion,
clobber or tag adoption command. Resolve a partial group/draft through an explicitly
reviewed administrative procedure, or choose a fresh release identity while
preserving the incident evidence. A failed promotion can already have changed
Latest, so verify the pointer before deciding the next authorized action.

Initial release discovery tolerates one narrowly defined pagination race: a
validated release ID repeated across distinct pages can restart the complete
inventory at most twice, discarding every earlier page. Explicit authenticated
page reads follow validated `Link` headers, with no extra request or wait on a
successful first inventory. Transport failures and inventory restarts share the
existing eight-attempt, deadline and cumulative-wait limits. Each inventory is
bounded to 256 pages and 16 MiB; all attempts together admit at most 768 page
requests. Persistent repetition, same-page duplicates, malformed records or links,
authentication/permission failures and distinct releases matching the same tag
remain errors. This read-only recovery never retries publication. Exact-ID final
publication and native-acceptance readback remain unchanged.

The helper rejects missing server SHA-256 digests, incomplete upload states,
duplicate asset IDs/names, malformed JSON and incomplete pagination. It bounds
parsed JSON to 16 MiB. Repositories beyond those limits need a reviewed extension;
truncating discovery is not a workaround. Read-only download failures leave no
permission to rebuild or publish replacement bytes.

## Executable coverage and limits

Run the focused offline suite:

```sh
python3 -B -m unittest discover -s tests -p test_github_release.py -v
```

| Invariant | Offline scenarios |
| --- | --- |
| Explicit authorization | All mutation defaults avoid transport calls; CLI rejects execution inside JSON; lost execution receipt reports uncertainty. |
| Immutable candidate | Existing release/draft, duplicate tags, orphan reference, incomplete upload and missing local dependency member block finalization or mutation. |
| Complete dependency group | Missing group has no fallback; exact reuse succeeds; partial or changed existing group fails. |
| Fresh review | Same-byte asset replacement, tag movement during download and altered bytes invalidate observations. |
| Retained qualification | Complete round trip reproduces the certificate; later failed attempts preserve earlier evidence; duplicate/stale/partial attempts and altered evidence or policy fail. |
| Controlled channel | Experiments cannot promote; changed post-update assets and an incorrect final pointer report uncertainty without rollback. |
| Transport boundary | Complete pagination, safe argument arrays, private diagnostics and explicit rejection of access failures as cache misses. |

These fixtures use actual local release, archive and certification validators
with an in-memory GitHub transport. They do not establish service permission
behavior, retention policy enforcement, native Windows hosting, authentication,
cross-machine exclusion or server failure timing. Qualify those in an authorized
deployment before describing a production release as supported.

The transport contract follows the primary documentation for
[`gh api` pagination and JSON input](https://cli.github.com/manual/gh_api) and
[GitHub release REST operations](https://docs.github.com/en/rest/releases/releases).

## Hosted operation ordering

Dispatch SDK maintenance explicitly when a recipe is absent or has changed. Its
optional publisher verifies the complete new group and appends it to `base`;
ordinary application jobs only fetch exact existing groups. Dispatch the prepared
application workflow with the complete recipe map. Review its retained candidate,
`delivery.json` and publication request before enabling execution for a new
candidate identity. Published candidates are immutable and remain outside Latest.

Certify a published candidate by its exact tag and release-inventory digest.
The prepare job captures complete paged remote assets, verifies the inventory and
delivery descriptor, downloads the source for archived-builder compatibility,
and rereads remote IDs and the direct tag. It retains an authenticated control
bundle containing the frozen complete asset snapshot, repository visibility,
acquisition workflow context and plan. Same-run native consumers authenticate those
controls through immutable Actions artifacts and workflow dependencies, then fetch
their required original source, archive or SDK assets and hash bytes in quarantine.
They do not rediscover the release in each parallel job. Unbound and historical
consumers retain independent remote snapshots. Public payload URLs are credential-free
and size/hash pinned; private repositories retain authenticated downloads. This
removes the complete-candidate private relay and repeated same-run discovery. Recovery still
receives complete retained inputs and every logical result remains required. Initial publication keeps
its complete byte readback; recording, attachment and promotion reconcile the
complete remote inventory and SHA-256 digests while downloading only their
controls and certificate evidence. Missing remote digests fail closed. The recording job rejects
missing, stale, mixed-run or altered evidence. A failed full report may be
attached as a new attempt, preserving previous reports and binaries.

Promotion is a separately gated reusable workflow, dispatched manually with
`execute=false` by default or invoked by Latest orchestration after certification. Its
plan names one certificate run, attempt and digest; execution validates that
remote certificate against the current reviewed policy and then verifies the
Latest pointer. An updated qualification attempt never rebuilds or overwrites
the candidate. A changed source or dependency inventory requires a new candidate.

Protected base/application publication, certificate attachment, promotion and
native acceptance share the release-lifecycle group; signed-channel publication
uses its target-scoped group. Other workflows and manual publishers must honor
the corresponding exclusion. A failed
publication step retains an uncertainty receipt whenever possible. A lost
receipt still requires remote reconciliation before retrying; do not rerun
an interrupted mutation blindly. Setup failures and incomplete artifacts remain
failed gates, even if a later upload step succeeds.

The hosted GUI input maintenance workflow uses the same checked `Remote`
transport and base lifecycle through `ci_plan.publish_gui_group`. Its complete
three-file group is namespaced by the manifest digest, verified before planning,
and verified again after remote download. Partial/conflicting existing groups
are never overwritten; changed asset IDs invalidate an observation. Ordinary
GUI application jobs use `fetch_gui_group` and an explicit digest, so only
maintenance jobs acquire upstream sources. The GUI source group remains separate
from compiler SDK recipe groups and its full source is retained in the candidate.


Public release storage publishes its bytes. GUI input inspection with unresolved
terms retains only its non-source plan. Source groups and compiled GUI outputs
must not enter public releases until verified terms allow redistribution.
Explicit SDK maintenance and native GUI qualification consume source on a
disposable runner and retain only the declared test evidence. Private CI transport
and successful local builds do not waive the public distribution gate.

SDK maintenance defaults to verified reuse with `source=auto`. Only positively
observed complete absence permits cold production in that maintenance workflow;
`base` requires existing bytes, and `rebuild` explicitly prepares a fresh group.
Every resulting group passes a relocated application and installed-consumer probe,
and GUI-capable groups additionally run the native GUI checks before eligibility.
Receipts distinguish reuse from new production. Existing groups remain immutable,
including after an explicit rebuild that produces different bytes.


## External Windows graphics qualification input

For native Windows GUI qualification, supply `graphics_archive_url` to the
ordinary GUI or certification workflow. It must identify operator-retained bytes
matching the [reviewed host graphics input](windows-graphics.md); HTTPS redirects
remain HTTPS and embedded credentials are rejected. The ordinary workflow never
substitutes a supplier download after an absent or invalid retained input. Explicit
SDK maintenance is the separate operation that may acquire the pinned supplier
archive. Maintain allowed source, notices and redistribution records alongside
any operator-retained copy.

The runtime is staged temporarily beside test consumers and a native capability
probe, with the selected compiler SDK protected from modification. Full GUI tests
retain actual visual captures and their qualification records. All test writers
must finish before cleanup or packaging. Uncertain cleanup fails the job and
preserves ownership for recovery. Uploaded evidence contains receipts, captures
and diagnostics; it excludes graphics archives/DLLs and GUI source/executables.
This host input neither changes the application SDK recipe nor waives any release
policy check or unresolved redistribution requirement.

## Run storage separate from product publication

[The CI storage contract](ci.md#storage-caches-and-sdk-reuse) uses
native Actions artifacts for routine temporary handoffs, and
[`ci_transport.py`](../tools/ci_transport.py) draft bundles for retained SDKs,
historical replay and deliberately selected legacy bundles. Preparation-only
application runs retain native candidate controls instead of another SDK-bearing
archive. Every store is a draft prerelease tagged by exact run/attempt;
it stays private, is never Latest and is not a qualified dependency base. Its
manifest-last bundles permit same-byte reconciliation after an interrupted upload.
This is deliberately a separate protocol from immutable candidate publication:
the product publisher does not adopt arbitrary partial drafts. Text evidence can
use deterministic gzip at level 6; consumers also accept existing
uncompressed tar bundles. Independent chunks download concurrently with a maximum
of four workers, then reassemble in the manifest's exact order. Every worker joins
before cleanup or local publication, including after a failed download. A batch
shares complete provenance inventories at its boundaries, including all selected
producers. Every selected namespace must remain unchanged, and duplicate remote
names or IDs are rejected across the complete asset inventory. Unrelated jobs
may add their own bundles concurrently. Downloads stay private until every
selected bundle passes the final checks; publication verifies all payloads before
writing their manifest commit markers.

Even with `execute=false`, trusted workflows may create these transport drafts.
The execution gate controls public product/base changes and Latest. Small pointers
live in job outputs and summaries. Routine application payloads and diagnostics
use bounded native artifacts; explicitly retained large inputs use draft bundles.
Reference a bundle by repository, exact producer and manifest ID/digest when reusing
another run. See [SDK retention and legacy migration](sdk.md#retain-complete-sdk-bytes-after-a-consumer-failure).
Marked successful full application/regression/certification workflows now trigger
bounded cleanup of their current and preceding full run's exact transient draft
stores and unchanged tags, after consumers have finished. SDK/legacy retention,
unknown namespaces, partial stores and unrelated releases remain excluded. Failed,
preparation-only, preserved and rerun application attempts do not trigger it.
A separate daily sweep expires known auxiliary diagnostic drafts after 24 hours,
including older attempts; GUI inputs, screenshots and distribution stores require
successful publication by that exact attempt. Unknown, incomplete and retained
SDK stores remain protected. See the precise
[completion cleanup policy](ci.md#storage-caches-and-sdk-reuse). Native artifacts
expire after one day when preserved or when cleanup cannot finish; draft releases
have no GitHub-provided expiry, so these checked cleanup policies govern them.

GitHub's [release API permission rules](https://docs.github.com/en/rest/releases/releases#create-a-release)
require additional workflow-write authorization when the target commit changes
workflow files relative to the default branch; `GITHUB_TOKEN` cannot receive that
permission. Integrate reviewed workflow changes into the default branch before
running these examples with the ordinary workflow token. Feature branches with
unchanged workflow files can use the normal path. Do not interpret a 404/403 from
this rule as an absent release or permission to change the source/tag identity.
Use an explicitly reviewed operator credential only when a project deliberately
qualifies that separate permission arrangement. Keep the default branch's
`.github/workflows/` bytes stable while any running producer still needs to create
its source-bound tag, transport draft or product release, including failure
retention. A workflow change pushed during a long preparation can make that older
job require authorization its token cannot hold. Before dispatch, compare the
selected revision's workflow tree with the default branch; this observation is
not an atomic reservation or a guarantee of write permission. Coordinate the
freeze with other publishers, then reconcile exact remote state after any refusal.
Changing ordinary source or documentation without changing workflow bytes does
not introduce this particular permission difference.
