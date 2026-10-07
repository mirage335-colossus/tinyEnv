# Documentation index

Each topic has one maintained home. Requirements describe expected behavior;
implementation references explain current code; validation records establish
what was observed. A proposed platform or procedure is not execution evidence.

| Topic | Start here |
| --- | --- |
| Start an independent project | [New repository script and configuration](../README.md#start-a-new-repository) |
| Shell entry points | [Script inventory, Bourne/Dash compatibility and checks](shell-scripts.md) |
| Build and run an example | [CLI commands](../COMPILE), [desktop GUI](../COMPILE-gui), [browser GUI](../COMPILE-web), [view screenshots](screenshots.md#view-screenshots), [capture commands](../SCREENSHOTS) |
| Scope and specification | [Engineering contract](engineering-contract.md), [requirements](requirements.md), [practice map](practice-map.json), [architecture and directory map](architecture.md) |
| Build and SDK | [Building](building.md), [offline application builds](offline-builds.md), [SDK](sdk.md), [portability](portability.md), [COMPILE](../COMPILE) |
| Default Rust/C++ application | [Default-policy rationale and implementation](rust-hybrid-plan.md), [current Rust release and integrated packages](validation.md#rust-all-gui-release-and-integrated-packages-2026-10-06), [historical qualification](validation.md#optional-rust-qualification-2026-10-04), [provider selection](building.md#rust-default-and-provider-selection), [retained Rust extension](sdk.md#retained-rust-extension), [provider tests](testing.md#rust-provider-checks), [platform limits](portability.md#rust-provider-boundary) |
| Verification speed and coverage | [Development speed](development-speed.md), [testing](testing.md), [CI](ci.md), [workflow examples](../.github/WORKFLOWS.md), [legacy archive preservation](legacy-artifacts.md), [validation](validation.md) |
| Dependency maintenance | [Dependency requirements](dependencies.md), [inventory](../third_party/README.md) |
| Installed manuals | [Manual sources and preview](man/README.md) |
| Interfaces | [GUI contract and integration](gui-boundary.md), [browser embedding](browser-embedding.md), [GUI audit](gui-audit.md), [Windows graphics prerequisite](windows-graphics.md), [core source](../include/foundation/store.hpp) |
| Optional graphical editor | [Build/run commands](../COMPILE-editor), [editing, ordinary-source integration and local checks](../editor/README.md), [architecture decisions](../editor/PLAN.md), [pending native qualification](../.agent-pending/editor-platform-qualification.md) |
| Collaboration | [Agent requirements](../AGENTS.md), [coordination](agent-coordination.md), [checked operation recipes](agent-recipes.md), [lifecycle](agent-lifecycle.md), [optional cooperation evaluation](agent-evaluation.md) |
| Delivery | [Release requirements](releases.md), [certification](certification.md), [Debian distribution](distribution.md), [Arch and Gentoo channels](distro-channels.md), [GitHub delivery](github-delivery.md), [signed package release workflow and native clients](distribution-release.md), [Latest workflow](latest-release.md), [screenshots](screenshots.md), [browser prerequisite](gallery-browser.md), [installed package instructions](installed.md), [RELEASE](../RELEASE) |
| Sustained maintenance | [Engineering practices](maintenance.md), [documentation rules](documentation.md) |
| Reusable forms | [Decision](templates/decision.md), [dependency](templates/dependency.md), [temporary note](templates/temporary-note.md), [validation](templates/validation.md), [release inventory](templates/release-manifest.json) |

Search current source and the relevant topic before opening large logs. Follow
linked contracts through callers and tests; do not treat this index as a limit on
investigation. Update the relevant topic and backlinks when adding documents.
