# SDK and workflow cleanup: remaining observations

The original implementation is based on `ea0e17f` plus the local 2026-10-05 cleanup/capacity
changes. The affected offline suites passed 433 cases in 26.7 seconds; the added
private-budget projection case also passed. Focused CI-selection tests, workflow
lint, documentation validation and whitespace checks passed. These checks exercise
growth, complete inventories, provenance, precise deletions, retries, active
consumers and storage-pressure failures. No SDK
rebuild, full qualification, remote publication or deletion was run for that edit.

[Full Latest 37394012851](https://github.com/mirage335-colossus/software-foundation/actions/runs/37394012851),
attempt 1/source `91dd1392ce182dd6aeef6bf9e18c17cfb9786377`, now establishes
the observed [hosted cleanup scope](../docs/validation.md#rust-all-gui-release-and-integrated-packages-2026-10-06):
nine exact temporary handoffs were deleted after successful final consumers,
with absence and all 52 surviving current artifacts independently confirmed.
Public base SDK/GUI inputs, both accepted predecessors and the current screenshot
gallery retained exact identities and digests. The ordinary successful completion
hook `37399475439` records `previous_run_id: null` and zero selected/deleted
artifacts, drafts or tags: the first marked successful full-run baseline.

Remaining hosted observation is an actual C++/Rust SDK same-slot retirement and
preceding eligible full-run pruning during a later normal matching workflow.
GUI replacement does not establish SDK replacement; a baseline does not prove
reclaimed preceding-run storage. Confirm required current evidence, unrelated
releases and retained SDK drafts survive those operations. Do not manufacture
additional expensive runs solely for this observation.

The daily auxiliary-draft expiry policy added after `b900859` was checked locally
with 123 passing cases across `ci_cleanup_expired`, `ci_cleanup_drafts`,
`ci_cleanup_previous`, `workflow_storage` and `ci_changes`, plus pinned actionlint,
documentation and whitespace checks. It reuses exact release/tag deletion guards
and preserves SDK stores and unpublished inputs. No extra hosted build, release,
validation run or immediate remote deletion was performed for this change.
The subsequent user-requested [manual cleanup 37410061631](https://github.com/mirage335-colossus/software-foundation/actions/runs/37410061631)
passed on `b4959a595b446c94bbf15b8fb8f7aec69571664a`, removing all 11 selected
drafts and their 11 tags with `expire_now=true`. Independent readback confirmed
all 10 public releases and 455 asset identities/digests unchanged. This retires
the auxiliary-draft hosted observation; see the [validation record](../docs/validation.md#automatic-ci-draft-cleanup-2026-10-06).
The automatic daily schedule retains its normal age grace and skips a busy
repository for a later sweep. Separate SDK and preceding-run scopes above remain.

Before private operation, complete the account checks in
[the storage budget](../docs/ci.md#private-account-storage-budget): private Packages
inventory was inaccessible, and existing nonzero spending caps do not enforce
the user's included-only storage policy. No billing settings were changed.
Private-account inventory and a zero-overage configuration remain unverified,
not passing qualification or authorization for paid storage. No billing settings
were changed by the observed public hosted release or cleanup.
