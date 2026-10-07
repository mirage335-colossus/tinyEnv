# Pending qualification

Use ordinary tracked files here for applicable deferred extensive qualification and
directly associated prerequisites that must survive handoff. Optional improvements
and unrelated development backlog stay in their existing locations, including
[FURTHER-agents.txt](../FURTHER-agents.txt). Apply the
[manual-qualification policy](../AGENTS.md#development-checks-and-manual-qualification).

A pending entry records an obligation. It does not schedule or authorize execution,
establish ownership or prove qualification. Record only applicable outstanding work,
not every available test or matrix. Keep implementation gaps and known failures
distinct from completed implementation awaiting extensive checks.

## Keep records proportional

Give each record a descriptive filename and concise scope. Include only applicable
information: source commit or snapshot identity; completed checks and actual results;
outstanding scopes and supported commands or procedure links; prerequisites and SDK
identities; evidence references; and the next manual action or request. Reference
existing manifests and procedures instead of copying inventories or logs. Omit
inapplicable fields; no mandatory index, schema or reporting system is required.

Useful maintained procedures include [testing](../docs/testing.md),
[CI](../docs/ci.md), [SDK use](../docs/sdk.md) and
[release certification](../docs/certification.md). Identify whether work is awaiting
authorization, blocked on a prerequisite, failed or ready to resume; never turn
missing execution into a passing result.

## Review, handoff and disposition

Inspect relevant entries when starting a task, substantively resuming it or changing
scope. Reuse already reviewed information unless relevant state may have changed.
Reassess applicability when source, configuration, dependencies or environment change;
preserve original evidence identities rather than relabeling prior results.

At relevant implementation handoffs, remind the user of outstanding qualification,
what was verified and remains unverified, and the next manual invocation or request.
Do not repeatedly interrupt unrelated work. Required release gates remain binding
even while their execution is deferred.

Retire an entry after verified completion is recorded, or after explicit cancellation,
supersession or a justified scope change. Preserve the disposition and necessary
evidence references in the record, linked maintained evidence or its Git history.
Large logs, payloads, locks and session state belong in their existing locations;
use `.agent-work/` for temporary coordination and generated evidence as appropriate.
Pending files neither replace the [coordination protocol](../docs/agent-coordination.md)
nor acquire any file or resource claim.
