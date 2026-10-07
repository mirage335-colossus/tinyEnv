# Validation: CHANGE OR CANDIDATE

This is an unfilled template. Do not describe it as a completed check.
Store real records with the relevant change or release; keep transient debugging
notes in the ignored coordination directory.

## Identity and scope

- Question or requirement being checked:
- Source commit and dirty state; diff/file digests when not clean:
- Packaging/helper commit if different:
- Platform, architecture, OS/runtime baseline, compiler, and configuration:
- SDK/dependency recipe and archive digests:
- Candidate inventory digest and exact artifact hashes, if applicable:
- Runner/image identity, available CPU/memory, and concurrency:
- Run ID, attempt, and UTC start/end times:
- Required scope and explicit exclusions:

## Execution and results

| Command/check | Selected inventory | Actual result | Evidence path/digest | Elapsed time |
| --- | --- | --- | --- | --- |
| Fill with the command actually executed | Named tests or manifest | `not_run` | Not yet recorded | Not measured |

- Expected versus observed test names; missing/duplicate/extra cases:
- Original failure/reproducer and result after change, if applicable:
- Checks reused from unchanged source/configuration and their actual run IDs:
- Passed checks:
- Failed checks and focused follow-up:
- Skipped, cancelled, incomplete, or unavailable checks:
- Accepted exception, exact classifier/scope, authority, and recheck condition:
- Sanitizer, native GUI, target baseline, and package-install coverage:
- Relocation and installed-consumer results:
- Complete source/SDK recovery results, when required:

## Conclusion and remaining work

- What the evidence establishes:
- What the evidence does not establish:
- Required checks still outstanding:
- Known risks and unsupported environments:
- Release/default-download eligibility and governing gate, if applicable:
- Remote publication identity verification, if performed:
- Responsible maintainer and next action:
