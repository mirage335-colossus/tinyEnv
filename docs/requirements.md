# Reusable engineering requirements

Use MUST for adoption gates, SHOULD for defaults with a recorded reason for an
exception, and MAY for optional capabilities. Tailor supported products and
platforms explicitly; an unimplemented capability must never be advertised as
verified. The full normative [engineering contract](engineering-contract.md) covers lifecycle,
failure handling, supply recovery and qualification. The machine-readable
[practice map](practice-map.json) binds the obligations below to concrete tools,
procedures and tests. Optional delivery channels must pass their own gates before
being advertised; omission must never be disguised as successful coverage.

| ID | Requirement | Evidence or maintained home |
| --- | --- | --- |
| ARCH-1 | Application behavior MUST have one owner independent of UI and platform adapters | [Architecture](architecture.md), [GUI boundary](gui-boundary.md) |
| API-1 | Public interfaces MUST state input bounds, ownership, lifetime, errors, concurrency and compatibility | Public headers and independent contract tests |
| BUILD-1 | One build graph MUST reuse common targets across enabled executables | CMake targets and [building](building.md) |
| BUILD-2 | Toolchain/configuration changes MUST use a fresh compatible tree or explicitly verified cache identity | Wrapper identity and [SDK](sdk.md) |
| DEP-1 | Every shipped external component MUST be traceable to pinned source, supplier, terms, patches and upgrade checks | [Dependencies](dependencies.md) |
| PORT-1 | Build-host requirements and target runtime requirements MUST be stated separately | [Portability](portability.md) |
| PORT-2 | Compatibility claims MUST cover the entire shipped dependency closure and CPU instruction floor | Target execution, binary inspection and relocation evidence |
| TEST-1 | Changes MUST start with meaningful focused checks; applicable final gates remain required for qualified binary delivery under the manual-qualification policy | [Testing](testing.md), [authorization](../AGENTS.md#development-checks-and-manual-qualification) |
| TEST-2 | Missing, failed, cancelled, skipped and incomplete coverage MUST remain distinct from passing coverage | Inventory-complete results and [validation](validation.md) |
| CI-1 | CI MUST have bounded concurrency, unambiguous scopes and minimally privileged execution | [CI](ci.md) |
| GUI-1 | Existing feature vocabulary MUST be declared and handled entirely in shared application code | Cross-adapter feature-extension test |
| GUI-2 | Layout, focus, event validity and capabilities MUST be specified consistently | [GUI audit](gui-audit.md) and conformance tests |
| COLLAB-1 | Under shared coordination, concurrent writers MUST claim files/resources and coordinate read dependencies before mutation | [Coordination modes](../AGENTS.md#simultaneous-sessions), [protocol](agent-coordination.md) |
| COLLAB-2 | Temporary knowledge MUST be bounded, attributable, ignored by Git and promoted when durable | [Lifecycle](agent-lifecycle.md) |
| REL-1 | Published artifacts MUST have immutable identities and verification of their actual bytes | [Release requirements](releases.md) |
| REL-2 | Source, recipes, notices and required dependency inputs MUST remain recoverable with each release | Release inventory and source bundles |
| SDK-1 | Ordinary consumers MUST use the exact immutable prepared recipe; base maintenance MUST retain complete reconstruction inputs | [SDK lifecycle](sdk.md) |
| SDK-2 | Binary releases MUST carry the exact compiled/source/checksum groups, with recovery tested without the base | [Release assembly](releases.md), [certification](certification.md) |
| DIST-1 | Package channels MUST preserve archive bytes and verify signed metadata, update identity and installed payloads | [Distribution](distribution.md) |
| COLLAB-3 | Under shared coordination, source saves MUST recheck current ownership, reviewed input identity and predecessor handoffs through a qualified helper | [Coordination modes](../AGENTS.md#simultaneous-sessions), [checked operations](agent-recipes.md) |
| DOC-1 | Maintained docs MUST separate requirements, proposals, procedures and observed evidence | [Documentation rules](documentation.md) |
| MAINT-1 | Failures MUST preserve diagnostic context without leaking sensitive material or corrupting state | [Maintenance](maintenance.md) |

## Small application contract

The record collection accepts 1–256 printable ASCII bytes per record, permits
duplicate text, holds at most its configured capacity (1–4096 records), and never
reuses an identifier within an instance. This restricted input contract keeps
the example deterministic; a project requiring wider text support must define
its own normalization, editing and display contract rather than silently changing
this one. Empty/malformed/oversized input is rejected. Returned records are owned
copies. Missing IDs produce empty/false results; invalid replacement text still
raises an input error even when the ID is missing. Failed additions do not consume
IDs or alter records. Storage is in-memory and lasts for the instance's lifetime.

The CLI accepts `-- TEXT ...`, `--version`, `--help`, and `--self-check`. It emits
one tab-separated record per line only after all input is valid. The CLI's default
collection is limited to 64 records. Exit status 0 means success, 2 means invalid
command shape, and 1 means input/runtime/output failure.

Version 0.x is a reference API under development. Do not infer a stable C++ binary
interface across compilers, standard libraries, runtime choices or future releases.
The installed static library is intended for matching-toolchain consumers.
