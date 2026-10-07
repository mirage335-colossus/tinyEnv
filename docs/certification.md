# Certification of exact release bytes

Certification is a separate operation after assembling the immutable candidate.
It does not rebuild or replace the candidate's application assets. Source checks
compile the recorded application source; archive checks execute the supplied
archives; recovery checks install the retained SDK and reconstruct inputs without
the original base. A branch change cannot repair an earlier release.

The local [release assembler](../tools/release.py) validates and retains source,
application archives, member inventories and exact SDK binary/source/checksum
groups. [The certifier](../tools/certify_release.py) calls that verifier before and
after checking coverage. Its output must live outside the immutable release tree.
It never publishes, replaces assets or modifies a remote channel.

## Support inventory and frozen plans

[release-policy.json](release-policy.json) defines `core` and `all-gui` profiles.
They are required coverage, not a declaration that these environments have passed.
The all-GUI profile names every supported backend; unresolved supplier terms or
an unavailable target cannot be hidden by passing the smaller profile. Adapt the
policy to a new product's honest support promise before creating its release.
Keep named browser environments bound to specific engine/version combinations in
the actual runner configuration and report.

Every delivered target/backend needs source, archive and recovery checks. Linux
adds ABI and Debian package checks; old and newer user-space archive jobs remain
separate. Containers share their host kernel. They do not qualify a different
kernel, physical device, graphical session, or Windows client installation.

A coverage specification contains:

- `schema_version: 1`, `mode: release` and an explicit `checks` array.
- `subject.source_sha256`: the recorded source archive digest.
- `subject.inventory_sha256`: the SHA-256 of the exact `release.json` bytes.
- `subject.configuration_sha256`: `coverage.digest({"policy": POLICY, "profile": NAME})`.
- `inputs`: the complete frozen release input inventory and exact digests. Each
  command rechecks its declared consumed subset before and after execution; unknown
  scopes, incomplete inventories and altered selected bytes fail.
- Each check has unique `id`, `scope`, `target`, `environment`, `backend`, boolean
  `required`, argument-array `argv`, positive `timeout_seconds` and
  `warning_seconds`, and `expected_tests`. A nonempty expected test list requires
  `junit`, a relative file inside that check's evidence directory. Every policy-required
  scope also declares `qualification: "qualification.json"`.

`argv` may use `{python}`, `{root}` and `{evidence}`. Execution uses no shell, runs
in the specified root, creates a fresh evidence directory, retains a bounded
console log, records host details and rechecks inputs. JUnit must contain exactly
the requested tests, with no duplicate, failed or skipped case. Commands without
JUnit can serve diagnostic commands. Release checks also need the bound receipt
from a self-verifying adapter. A successful empty command cannot qualify a release.

```sh
python3 tools/coverage.py freeze --spec build/check-spec.json --output build/check-plan.json
python3 tools/coverage.py run --plan build/check-plan.json --check CHECK_ID \
  --root . --run-id local-candidate --attempt 1 --output build/evidence/CHECK_ID-attempt1
python3 tools/coverage.py merge --plan build/check-plan.json --output build/coverage.json \
  build/evidence/*/result.json
python3 tools/certify_release.py --release dist/candidate \
  --policy docs/release-policy.json --profile core --plan build/check-plan.json \
  --output build/certification-run1.json build/evidence/*/result.json
```

Replace `CHECK_ID` with a check declared in the plan and run every check on its
named environment. Never run a Windows-labelled check on Linux and treat its label
as evidence. The producer records actual host identity; the orchestration layer
must provide the declared environment. Do not overwrite a result to retry: create
a new attempt directory. Ordinary aggregation requires one run and attempt. To
reuse successful earlier checks, create the explicit immutable adoption manifest
below; arbitrary mixtures of attempts remain invalid. Original receipts, execution
attempts, host identities and complete evidence remain unchanged and visible.

### Explicit prior-attempt adoption

The portable scheduler can rerun only failed physical executions. Prepare a new
workspace with the **identical frozen plan and inputs**; keep the prior workspace
and its evidence immutable. A changed source, dependency, configuration, required
environment, test inventory or policy needs a new plan and fresh affected evidence.
The actual required host still runs each remaining check. All logical backend
results belonging to one physical execution must be selected together.

For example, after `CHECK_A` passed and `CHECK_B` failed in attempt 1, run `CHECK_B`
in an identical prepared attempt-2 workspace. These placeholders stand for exact
physical check IDs from `qualification_tasks.py list`; enumerate every required
check when more than two exist. Grouped checks use their listed `*.result.json`
paths instead of `result.json`.

```sh
python3 tools/qualification_tasks.py prepare --root /work/attempt-2 \
  --check CHECK_B --run-id release-candidate --attempt 2
python3 tools/qualification_tasks.py run --root /work/attempt-2 \
  --check CHECK_B --run-id release-candidate --attempt 2
python3 tools/qualification_tasks.py adopt --root /work/attempt-2 \
  --run-id release-candidate --attempt 2 --output /work/adoption-2.json \
  /work/attempt-1/build/evidence/CHECK_A/result.json
python3 tools/coverage.py merge --plan /work/attempt-2/build/check-plan.json \
  --adoption /work/adoption-2.json --output /work/coverage-2.json \
  /work/attempt-1/build/evidence/CHECK_A/result.json \
  /work/attempt-2/build/evidence/CHECK_B/result.json
```

`adopt` verifies frozen input bytes, original complete passing evidence and actual
host requirements; it selects only earlier attempts of that same run. Its new
output binds the complete original result hashes, attempts and host identities.
It never overwrites or relabels a receipt. Aggregation revalidates every original
log, qualification receipt and nested evidence hash, rejects changed/unused
selections, and still requires the complete logical inventory. Missing, failed,
skipped, incomplete and future/current-attempt selections cannot be adopted.
The adoption manifest may select older results from more than one prior attempt,
but projections of a single physical execution must retain one original identity.

Pass the same `--adoption /work/adoption-2.json` and exact selected result paths to
`tools/certify_release.py` with its ordinary release, policy, profile, plan and new
output arguments. Full certification retains the adoption manifest in the
certificate alongside original result hashes and coverage. Certificate bundling,
remote verification and promotion reproduce the same explicit selection and bind
it to the certificate attempt; downstream signed-channel verification uses that
same validator. `coverage.py merge`
alone does not certify or promote a release. A new attempt may also execute all
checks normally without using adoption.

The GitHub certification workflow also supports **Re-run failed jobs** and retries
of the record or attachment job. It retains the original prepare attempt and
matrix, restores current-attempt artifacts through the ordinary strict path, and
uses [`ci_retry.py`](../tools/ci_retry.py) to authenticate earlier successful whole
batches. It checks the original repository, workflow, run, attempt, completed job,
runner, artifact creation interval, immutable artifact ID and ZIP digest, then
validates the original manifest and every extracted byte. The latest execution
wins: a failed or missing current batch cannot be replaced by an older pass.
Ambiguous, expired, changed or incomplete evidence fails closed; rerun all jobs
when the original handoffs are no longer available. Selection is bounded to 64
attempts and the native transport's 48 evidence slots.

The record job rechecks the frozen input payloads required by adopted groups and
uses the same local adoption validator. This saves compilation and execution, but
still downloads and hashes those exact payloads. Source, policy, environment or
plan changes invalidate reuse. Certificates retain the original result identities
and explicit adoption manifest; attachment retries restore the exact successful
record output and append its original certificate attempt. They do not relabel it
as the attachment job's newer attempt. A partially completed remote attachment
still requires normal reconciliation; retry does not authorize replacement.

Local/file-based callers must continue supplying trusted original evidence;
hashes alone do not authenticate producers. The historical path never weakens the
current-attempt transport check, renames old receipts or overwrites artifacts.

## File-based commands for another CI or a local scheduler

[`qualification_tasks.py`](../tools/qualification_tasks.py) exposes the same planner,
prerequisite stage and supervised checks independently of GitHub. Put the exact
assembled release at `build/candidate` in a private source workspace, then freeze
and inspect its execution requirements:

```sh
python3 tools/qualification_tasks.py plan --root . --profile core
python3 tools/qualification_tasks.py list --root .
```

The JSON inventory lists physical execution IDs, target/environment requirements,
logical checks and their relative result paths. Grouped checks launch once and
still produce every logical receipt. A scheduler may dispatch independent
executions concurrently on suitable hosts, or batch compatible executions to
amortize worker setup. This command introduces no scheduler or serial execution
loop. The existing hosted batching remains unchanged.

Copy the same frozen plan, declared tools and required candidate files into each
worker's `build/check-plan.json` and `build/candidate` layout. Keep the complete
candidate metadata; selective payloads must satisfy `coverage.check_inputs` for
the selected execution. The transport must authenticate workers and input origins;
a local hash proves byte identity, not producer identity. Run on the actual
platform and environment required by policy. Existing host checks, including the
Windows baseline, remain enforced; another provider must supply a qualified
adapter or an explicitly revised and qualified policy.

```sh
python3 tools/qualification_tasks.py prepare --root . --check CHECK_ID \
  --run-id local-candidate --attempt 1
python3 tools/qualification_tasks.py run --root . --check CHECK_ID \
  --run-id local-candidate --attempt 1
```

Replace `CHECK_ID` with a physical execution ID from `list`. `prepare` is a no-op
when browser setup is unnecessary. Browser setup retains its explicit disposable
container, image and privilege requirements; it may contact distribution package
repositories. `run` never silently installs prerequisites. Both stages use the
same run ID and positive attempt. The executor supplies `FOUNDATION_PLAN_ID`,
`FOUNDATION_CHECK_ID`, `FOUNDATION_RUN_ID` and `FOUNDATION_RUN_ATTEMPT` only to its
child environment. Browser receipts must match all four; missing or mismatched
context fails. Ordinary callers need not set these variables themselves.

Each execution retains its complete evidence directory at
`build/evidence/CHECK_ID`, with bounded console logs, timing, actual host details
and logical results. A non-passing check exits nonzero. Preserve the entire
directory when collecting results because receipts bind companion evidence files.
Pass exactly the `reports` paths listed in the inventory to the existing
`certify_release.py` command, using `--release build/candidate` and the same policy,
profile and frozen plan. Do not substitute a broad `*/result.json` glob for grouped
results. Use fresh worker/output trees for retries and collect one complete run
and attempt; never overwrite earlier evidence.

The portable plan requires no `.github` files, GitHub variables, `gh` executable
or GitHub API calls. The hosted adapter additionally freezes its provider scripts,
workflow and remote delivery descriptors, supplies native run identity, and retains
producer authentication, selective parallel transfers and publication checks.
SDK preparation, building, assembly and certification continue to use the existing
file-based tools documented in [RELEASE](../RELEASE). This is an incremental
boundary, not a claim that every hosted transport or platform adapter is portable.

## Authoritative check adapters

[`release_check.py`](../tools/release_check.py) implements `source`,
`archive`, `recovery`, native `abi` and disposable-container `apt` scopes. It verifies the complete candidate metadata and each scope's consumed payloads before and after
execution, checks actual target identity, and writes the receipt only after the
operation completes. For example, the argument array for a native archive check is:

```json
["{python}", "{root}/tools/release_check.py", "archive", "--release", "{root}/dist/candidate", "--target", "linux-x86_64", "--backend", "core", "--evidence", "{evidence}"]
```

Source qualification also builds a consumer against the exact delivered library
and CMake export, so success from a newly rebuilt SDK cannot hide a damaged shipped
SDK. Source checks restore the exact source archive and matching compiled SDK
with its full checksum binding. Recovery restores the complete retained
binary/source/checksum group. The frozen source row records `sdk_payload`; older
archived builders retain complete groups when their interface requires them. Both
build the complete enabled source scope and preserve its JUnit
plus individual unit-case reports. Unexpected inner skips, missing prerequisites,
failed subtests and expected failures cannot be hidden inside a green CTest case.
Platform exclusions are explicit named cases in `run_tests.py` and stay visible
in receipts. Recovery receives only the candidate's retained input copies. Run it
inside an environment with network access disabled to establish an offline claim.

Native archive checks relocate and execute the exact CLI and selected GUI backend,
including its shared smoke scenario. ELF or PE audits inspect the shipped files.
Windows recovery checks the actual selected linker against the dependency producer
and supplies the verified restored export to the build. A Linux container receipt
records its real distribution; it does not turn a newer host kernel into an old one.

Browser source/recovery scopes use the retained Wasm SDK, execute the installed
consumer through its Node runtime, then run the rebuilt module in the selected
actual browser. Browser archive checks use copied assets and the harness preserved
in the exact source archive. Pass `--browser firefox --firefox /path/to/firefox` or
`--browser chromium --browser-executable /path/to/chromium --driver /path/to/chromedriver`.
The receipt retains engine/version, exact input hashes, interaction checks, geometry
and captures. Missing browsers fail; no browser is downloaded by qualification.
Desktop browsers remain host prerequisites, outside the compiler SDK. The explicit
CI prerequisite plan selects either existing host tools or a distribution package
and verified repository for the actual operating system. Native Ubuntu checks
inspect the installed browser and, for Chromium, ChromeDriver; they bind the actual
OS, architecture, versions and executable hashes without installing a browser.
Distribution checks retain package versions, repository policy and signing identity.
Both paths recheck the selected executable bytes after execution; neither
substitutes another distribution for the named check. Pass its receipt with
`--browser-prerequisite` and the frozen plan with
`--browser-prerequisite-plan`. The adapter checks the source/inventory, target,
backend, scope, plan, check, run and attempt, actual host and selected executable.
It then compares the observed browser version and preserves the unchanged receipt
as hashed evidence. A package-install log alone cannot certify browser behavior.

Windows Rev qualification uses a separately retained host graphics input through
`--windows-graphics-archive`. The application and SDK contain no software graphics
driver or desktop browser. The [Windows graphics prerequisite](windows-graphics.md)
is qualified with a real native WGL probe, exact loaded DLL paths and bytes, and
required capabilities before running unchanged GUI checks. Temporary driver staging
is confined to the disposable executable directories and removed only after every
owned child has stopped. Compiler/probe/test logs and final cleanup receipts stay
with the check; driver files are excluded from application archives. Failed graphics
setup is an incomplete qualification, never permission to skip appearance checks.

The `apt` adapter requires Linux running as root inside an explicitly selected
Docker/Podman container and `FOUNDATION_DISPOSABLE_CHECK=1`. It refuses ordinary
host use, already installed application packages and colliding payload paths.
Prepare `apt-get`, `dpkg-deb`, `gpg`, `gpgv`, `gpgconf` and `openssl` outside the
check. It packages the exact archive twice with increasing disposable packaging
versions, creates a temporary signing key and HTTPS loopback repository, validates
TLS against its own CA, and runs real APT refresh, installation, upgrade and purge.
Each installed file, version and runtime self-check must match; corrupted signed
metadata must fail specifically at signature validation. Private signing keys are
neither served nor retained in evidence. Cleanup stops the server and signing
agents; failure never produces a passing receipt. Retain `apt.log` with its bound
digest. These synthetic package versions qualify the delivery mechanism while
preserving the exact candidate archive, not an invented application-version upgrade.

Arch and Gentoo client install/update/remove scopes require native environment
adapters with the same receipt contract. The adapter must verify the candidate, execute that scope against its
exact assets and retain observations; a label or placeholder command is insufficient.
`qualification.json` contains schema version, source and inventory digests, target,
backend, scope, actual `coverage.host_identity()`, passing status, nonempty executed
assertion names, details, and a relative filename-to-digest `evidence` map. Source
receipts require exact nonempty test names and `source.junit.xml`. The policy is
intentionally unsatisfied until every promised environment supplies its real adapter
evidence. The [validation record](validation.md) states which environments were
actually exercised here.

Coverage owns the complete process tree until its writers stop. A private Linux
supervisor acts as a child subreaper, including nested sessions and process groups;
it does not change the shared agent harness. Windows children enter a kill-on-close
Job Object before execution. Other POSIX hosts require a qualified adapter. External
services and transferred output ownership require separate OS or harness confinement. A parent exit cannot
silently release a still-writing child.

## Gates and outcomes

The certifier rejects diagnostic mode, changed source/inventory/policy, missing
platforms or backends, duplicated scopes, mandatory scopes made optional, missing
results and altered evidence. It re-parses JUnit rather than trusting only a
summary's pass flag. Reports use distinct passing, failing and incomplete states.
Near-limit complete successes may produce `passed_with_warnings`; this does not
waive assertions. Required incompleteness always blocks the supplied policy.

The optional `--experiment` flag preserves successful evidence but prevents stable
promotion eligibility. An `eligible_for_promotion` result authorizes no action by
itself: maintainers still follow their release authorization and publication
procedure. Before promotion, re-read exact remote assets, tag/application identity,
certification run/attempt and current channel policy. After promotion, verify the
channel resolves to those same bytes. Serialize publishers without cancellation.

Hashes establish byte identity, not who created a result. Treat plans, trusted
runners, checkout permissions and signing credentials as part of the trust model.
Untrusted branch code cannot safely receive publication credentials or execute on
privileged workers. Preserve reports and logs durably beside the release while
keeping the immutable application inventory separate from appended certification
attempts. A failed later attempt stays visible alongside earlier evidence.

## Direct hosted input acquisition

Hosted preparation downloads the complete release metadata and its exact source
archive, which identifies the retained builder's supported SDK interface. It
freezes the original release ID, lifecycle fields, tag commit, complete asset IDs,
sizes and hashes in `candidate-remote.json`. The frozen coverage plan includes
all candidate payload hashes, plus the delivery and remote-descriptor hashes.
Preparation publishes only these controls through the authenticated CI transport;
it does not download and republish every SDK and application archive.

Each qualification batch first authenticates those controls against the exact
workflow run and attempt. It derives its consumed files from the frozen logical
checks, then downloads those original published assets directly. The frozen snapshot
binds the exact acquisition workflow context and repository visibility. Authenticated
same-run consumers use it without repeating release/tag/asset discovery in each job;
historical or unbound consumers retain independent before/after remote checks.
Public downloads carry no credentials; private repositories use authenticated asset
requests. Attachment and promotion still reconcile the complete remote identity.
No selected payload is exposed until the complete download transaction passes;
each check rechecks its selected bytes before and after execution. Recovery keeps
complete SDK binary/source/checksum groups. Older archived builders receive their
required complete groups for source checks as well.

The evidence collector restores the controls and every expected batch outcome in
one grouped transaction, then reconciles the supplied matrix against the frozen
plan. Independent source, recovery, archive and client batches remain parallel.
These changes remove an intermediate full-candidate transfer and repeated metadata
reads without reducing the logical coverage or accepting incomplete certificates.
