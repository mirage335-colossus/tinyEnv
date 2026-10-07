# Documentation requirements

The README answers what the repository provides, how to run the smallest example,
where to start changing it and what is actually supported. `COMPILE`, `COMPILE-gui`,
`COMPILE-web`, `SCREENSHOTS` and `RELEASE` are short command references.
`docs/README.md` routes readers to one maintained home per topic.
Keep relative links valid both in a checkout and wherever the
document subset is distributed; an installed README may require the matching
source bundle for source-relative links.

Keep the root `README.md` as the GitHub repository landing page. Store workflow
guidance in [`.github/WORKFLOWS.md`](../.github/WORKFLOWS.md): a `.github/README.md`
would [take precedence over the root README](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes).

## What to document

- **Requirements:** observable behavior, compatibility constraints, input bounds,
  error behavior, supported platforms, explicit non-goals and acceptance criteria.
- **Architecture:** module responsibilities, dependency direction, caller-to-callee
  paths, state ownership, lifetimes, concurrency, resource budgets and I/O boundaries.
- **Build:** tool versions, native prerequisites, clean and incremental commands,
  generated files, optional features, caches, offline use and recovery from stale trees.
- **Dependencies:** suppliers, exact revisions, source checksums, licenses, modifications,
  preparation recipes, API integration and tests required after an upgrade.
- **Tests:** case ownership, selection commands, prerequisites, deterministic inputs,
  expected outputs, expensive scopes, time budgets and complete-result rules.
- **Delivery:** asset names, target architectures, minimum OS/runtime, backend inventory,
  installation/uninstallation, SDK use, package repository metadata and rollback.
- **Operation:** command usage, configuration precedence, paths, exit codes, logs,
  resource limits and failure recovery, where those features exist.
- **Decisions:** problem, chosen approach, alternatives, tradeoffs, evidence,
  owner and conditions requiring reconsideration. Keep short decision records.
- **Validation:** source/artifact identity, exact commands, environment, scope,
  results, failures, omissions and reproducibility limits. Distinguish observation
  from explanation or inference.

A public function documents its contract; comments explain reasoning that code
cannot express. Avoid repeating obvious statements or maintaining competing
copies of the same list in prose, CMake and workflows. Prefer generated inventories
and stable references to authoritative declarations.

## Installed user documentation

Ship usage, exit status, configuration and removal instructions with the binaries.
Provide native manual pages where appropriate; their source should build and install
offline with ordinary distro tools. Keep command help and manuals synchronized,
check formatting, and verify installed documentation after package relocation.
Backend packages that coexist must use distinct public manual aliases just as
they use distinct launchers. See [the maintained manual sources](man/README.md).

## Evidence and maintenance

Instructions and proposed improvements do not prove execution. Mark example
manifests as incomplete until populated and validated. Do not turn a warning into
a pass or claim that an interface supports every future feature. Date source
references and record pinned revisions; external community advice is a hypothesis
until checked in the relevant environment.

Store large evidence separately with a small indexed manifest, retention policy,
checksums and reproduction instructions. Keep temporary findings under the
ignored coordination board. Promote durable verified knowledge into current
contracts, tests and procedures. Do not force every contributor to read all logs.

A change affecting behavior updates its contract, test and user instructions in
the same review. Renames preserve or repair inbound links. Use
`python3 tools/check_docs.py` for local file links, heading targets, strict JSON and the requirements-to-code/test map; it does not
validate external links or prove the truth of prose. Review examples by executing
them in an appropriate environment. Avoid exposing workstation paths, identities,
secrets or application-specific material in a reusable template.
