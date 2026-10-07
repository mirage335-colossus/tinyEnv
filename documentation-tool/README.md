# software-foundation documentation

The included documentation answers **where do I start, and what do I edit to
make this change?** through graphical edit paths, nested code diagrams, source
references, and linked PDFs. It includes a separately labeled AI-authored guide
for a simple first look at the GUI design.

## Read the included documentation

Open [the code explorer](published/index.html) directly in your browser, or start
with the [AI-authored GUI mental model](published/AI-AUTHORED__GUI-MENTAL-MODEL.html).
These are committed reader files in **`published/`**. Reading them needs no
rebuild, Python setup, AI, web server, or application checkout at its original
capture location.
Use a local clone or downloaded copy for the HTML explorer; GitHub's file view
shows HTML source. The PDF links can also be read on GitHub.

The six included PDF volumes are:

- [Edit paths](published/pdf/00-edit-paths.pdf): where to change widgets, behavior,
  and source-file registration.
- [Code walkthroughs](published/pdf/01-code-walkthroughs.pdf): referenced functions,
  ownership, control structures, and full source.
- [Compiler reference](published/pdf/02-compiler-reference.pdf): source lists,
  targets, options, and toolchain declarations.
- [Execution flows](published/pdf/03-execution-flows.pdf): what runs during build,
  startup, clicks, import, and export.
- [Code flowcharts](published/pdf/04-code-flowcharts.pdf): numbered source lines
  inside diagrams, with links to deeper calls and parent diagrams.
- [AI-authored GUI mental model](published/pdf/AI-AUTHORED__GUI-MENTAL-MODEL.pdf):
  simple conceptual diagrams with links to the detailed source views.

Keep the complete `published/` directory together; it contains the local HTML
assets, captured source data, `atlas.json`, and `pdf/` links. PDF cross-file links
depend on viewer support and work best with the collection opened locally.
The files are a documentation snapshot and may not be kept up to date.

The generator is versioned in the separate **`documentation-tool/` directory**.
Fresh captures and its virtual environment stay outside the application
checkout. An explicit export places reviewed reader artifacts in `published/`
for versioning. Source capture never edits application code, build definitions,
CI workflows, regression tests, Git metadata, or agent coordination records.
There is deliberately no build hook, watcher, scheduled job, or automatic refresh.
Generation requires no AI, API key, service, compiler, CMake configuration,
compile database, or application build.

## Run only when a new snapshot is wanted

From a checkout containing `documentation-tool/`, prepare an independent
environment once:

```sh
python3 -m venv ../software-foundation-docmap-env
../software-foundation-docmap-env/bin/python -m pip install -r documentation-tool/requirements.txt
```

Virtual environments contain local absolute paths. Create this external
environment afresh on each computer; never copy or commit it. Its dependency list
in `requirements.txt` is versioned.

Then invoke explicitly whenever new documentation is wanted:

```sh
../software-foundation-docmap-env/bin/python -B documentation-tool/docmap.py
```

The containing checkout is the default source. Every run creates a **new**
timestamped directory under the sibling `<checkout-name>-documentation/snapshots/`
and prints its location. The tool excludes its own directory from the source
inventory. Open `index.html` directly in a browser. No web server is needed.

The tool can also live outside a checkout. In the original standalone layout,
`software-foundation-docmap/` defaults to its sibling `software-foundation/` as
source and creates snapshots under the tool's own `snapshots/` directory. Its
existing `.venv/bin/python -B docmap.py` invocation still works.

To choose the locations explicitly:

```sh
../software-foundation-docmap-env/bin/python -B documentation-tool/docmap.py \
  --source . \
  --output ../software-foundation-documentation/manual-snapshot
```

Existing output directories are refused, even if empty. Output inside the source
tree, or a parent containing the source tree, is refused. These checks also
resolve symlinks. The capture generator can read its containing checkout, but its
new snapshot output must remain outside that checkout. The separate export step
can copy a reviewed reader bundle into `documentation-tool/published/`.
Keep the Python environment outside the checkout and use `-B` as shown above.

For HTML/JSON only, add `--no-pdf`. Additional exclusions can be specified as
source-relative paths, for example `--exclude tests --exclude .github`.
Files larger than 4 MiB are reported as skipped; adjust `--max-file-mb` if needed.

The documentation is a navigation snapshot and may not be kept up to date.
Regenerate explicitly when its broad map stops being useful. It records the
capture time, per-file hashes, parser versions, coverage gaps, and a combined
hash of the captured files. It detects edits to captured files during collection,
but it cannot guarantee an atomic repository snapshot while other agents work.

To update the committed reader files, export a reviewed external snapshot into a
fresh staging directory and follow the scoped replacement procedure in the
[maintenance note](AI-AUTHORED__GUI-MENTAL-MODEL-MAINTENANCE.md#update-the-committed-reader-bundle).

## Start with the change you want

For a simple first look, open **`AI-AUTHORED__GUI-MENTAL-MODEL.html`** or its
same-named PDF in `pdf/`. The main explorer links to this companion prominently.
Its large, simple diagrams explain startup to widget definitions, the GUI
abstraction boundary, publication and display, and an Add-button click.
Cards lead into the exact source-backed code diagrams when more detail is useful.

This is explicitly **AI-authored editorial explanation**, written for the example
and stored in `AI-AUTHORED__GUI-MENTAL-MODEL.json`. It emphasizes the stable
design and deliberately simplifies control flow. The generator renders the saved
explanation locally and checks its source anchors and diagram links; it never
calls AI or rewrites the explanation. Matching anchors do not prove that every
conceptual claim remains current. Changed anchors are marked for review, and
the guide retains its separate authorship date alongside the capture date.

**Add a widget, a click event, and a helper beneath the event.** The first diagram
leads from the row in `view_definition.hpp`, through target-ID routing in
`Application::handle`, to the new handler and its helper. A decision splits
UI-specific behavior in `Application` from reusable domain behavior in the core.
Conditional steps cover state projection in `publish` and registration of a
genuinely new `.cpp` file. Existing event forwarding and table-driven layout are
marked **REUSE**. Proposed function names are marked **NEW**.

**Make a new source file compile.** This diagram asks which module owns
the code, then points to the exact core, GUI, CLI, or host target source list.
Rust module declarations and header-only changes have their own branches.
Adding a method inside an existing compiled `.cpp` requires no source-list edit.

**Place a widget in the right position and page.** This diagram makes the current
single-panel arrangement explicit: declaration order controls vertical order;
the row sets height; `publish` owns spacing and composed bounds; `add` currently
parents every non-root widget to the first root group. Custom rows or groups need
matching changes to declarations, parents, and the shared layout tree. A widget
ID prefix does not assign a page.

**Add a page tab and place its contents.** The current application initializes no
tabs, although the retained GUI contract supports them. The chart shows the first
implementation path: declare pages and an active page, add explicit page/parent
membership, compose page contents and visible tab-bar geometry, handle `PageEvent`,
keep focus consistent, and reuse generic adapter rendering. Once that shared
support exists, another tab adds a page entry and its owned content. This means
page tabs, not the keyboard Tab key used to move focus.

**Change validation or a business rule.** Follow the public contract, Store's
validation before mutation, equivalent Rust/C++ text providers, mirrored limits,
and the existing error/status consumers. Provider and capacity edits are
conditional on which rule changes.

**Edit the selected entry.** Add shared Update intent and resolve selection to a
stable record ID, then reuse the existing `Store::update` operation. Handle its
false return and invalid-input exception, and project the result. This avoids
mistaking a copied snapshot or a row index for the authoritative record.

**Add a menu command or keyboard shortcut.** Declare an option, route it to one
shared helper, and optionally reuse that helper from a button and a supported
key binding. The chart identifies normalization, current-button requirements,
and the pinned shortcut vocabulary.

**Change background work, cancellation and progress.** Follow the result contract,
bounded computation, owned input capture, executor scheduling, completion guards
and shared lifecycle. A different result meaning may require changing guards
that currently assume a byte count.

**Change import/export format.** Follow shared serialization and atomic parsing,
transfer bounds and freshness checks, generic byte transport, and honest status.
The chart explains why import preserves monotonic IDs and export completion
means host handoff rather than a durable-save guarantee.

Click a box to see **what to change, why it belongs there, the exact source
location, and an existing code example**. Follow the deeper links to the actual
function, its callers/callees, or captured source. The companion runtime diagram
traces the existing Add button through `append_entry`, `Store::add`, and
`Store::validate`; publication is shown as a later call from `handle`.

Dense examples have **Parameters explained** guides next to the relevant edit
steps. Each guide includes a readable synopsis, numbered field names, types,
meanings and defaults, followed by a filled multiline example with labels beside
its values. The guides cover `ViewDefinition`, `gui::Page`, `gui::Rect`,
widget page/parent assignments, CMake `target_sources`, `gui::KeyBinding`, and
`Store::update`. The PDF links each
step to a deduplicated parameter-reference appendix and back again.

Reading notation is labeled separately from usable C++/CMake fragments. C++
aggregate fields are shown in declaration order; proposed page/parent additions
are not presented as existing `ViewDefinition` fields. The guides check their
source anchors, including complete aggregate declarations, so field-order drift
shows a review warning. Their explanations are curated local data in
`parameter_guides.py`, not AI-generated at documentation build time.

These edit recipes encode project ownership deliberately; an arbitrary desired
feature cannot be inferred reliably from syntax alone. The separate
`change_maps.py` and `behavior_paths.py` contain these small, reviewable recipes. Generation resolves
their source anchors and snippets against the captured code, without AI.
Missing or ambiguous anchors display **Source anchor changed; review required**.
The arrows distinguish prospective edit dependencies from the existing runtime
example. They do not claim every marked function must change for every feature.

## Follow what runs when

Start with **main() -> widget definitions** on the explorer's opening page or
execution index. One diagram connects the real entry call, Session construction,
Application constructor, declaration loop and `Application::add`. Actual editor
and Add-button rows appear beside the loop with a **data dependency** arrow:
the array supplies values; it is not another function call. Click those rows for
the root, controls, optional feature and field/default diagrams. Host waiting,
object ownership and the rest of initialization have separate deeper diagrams.

This path ends at creation of the shared Snapshot widgets. The constructor's
publication branch leads onward to layout and adapter presentation. Declaration
order and height are consumed by layout; `add` copies the widget properties and
assigns its root parent. Creating a Snapshot widget does not itself create a
native control or assign its bounds.

The explorer's **What runs when…** scenarios illustrate existing code paths for
compilation, testing, release, startup, an Add-button click, import and export.
Choose a scenario, then follow its arrows and click a function or process box
to open a deeper **code diagram**. All overview steps have a diagram destination.
The next level puts actual captured code or configuration lines inside the boxes,
with line numbers and call, return, branch, event, sequence or dependency arrows.
Calls that have another selected detail diagram lead down another level;
source links remain available separately. Up links return to the parent diagram.

The bold primary path highlights the feature or build operation being followed.
Supporting guards, error paths and host plumbing use a quieter style and remain
visible. These focused diagrams deliberately select important spans rather than
trying to put an entire large function on one page. Line-number gaps and edge
labels identify transitions; an arrow does not assert that intervening source
was removed or is irrelevant. Exact full source remains one click away.

For example, follow GUI startup into session construction, widget creation and
publication; follow Add through event dispatch, the application helper, Store
validation, the selected provider and the caller's publication; or follow CMake
source/target declarations into conditional Rust setup and generated build
commands. Configuration dependencies are labeled separately from runtime calls.

The charts distinguish a direct **function call**, a **subprocess/command**,
an **event or asynchronous completion**, a **conditional branch**, a
**return**, and a **local step/sequence**. For example, `append_entry` calls `Store::add`;
publication occurs after returning to `Application::handle`. File transfer
crosses a host-service boundary before `complete_service` processes the result.
The release scenario distinguishes local packaging from hosted publication.

These are curated, source-backed representative paths, not recorded executions.
Compiler target selection and platform branches remain conditional. Missing
source anchors remain visible as review items. Generating the charts never
invokes any command shown in them, including builds, tests, or release tools.

## Supporting reference views

- From the task maps, open the reference inventory and entry points, then drill down through
  a component, file, object, and function. Every level has an upward route.
- Search symbols and paths, inspect callers and callees, and follow source-line
  links within the captured source. The exported directory is self-contained.
- Inspect function control structures: conditions, branches, loops, returns,
  exception handling, and nested blocks. Source remains the final reference.
- Read the build map for target/source relationships, declared links, options,
  presets, and toolchain files, without configuring any of them.
- Use the extension guide to find the existing targets for a new C++ file, the
  Rust module boundary, shared GUI feature ownership, and runtime entry points.

The default print collection has five source-reference volumes and one
conspicuously named AI-authored companion:

- `pdf/00-edit-paths.pdf` starts with a task index, then provides the charts,
  actions, ownership rationales, source links and parameter reference. It is the
  primary printable entry point.
- `pdf/01-code-walkthroughs.pdf` follows the chart references into captured
  functions and types: signatures, ownership/member information, full bodies,
  structural control outlines, and named caller/callee candidates. It also
  provides source context for chart anchors outside those symbols. The scope is
  the edit paths, with links to the full explorer inventory.
- `pdf/02-compiler-reference.pdf` provides declared targets with source/link
  arguments, options/defaults, toolchain assignments, presets, Cargo data,
  helper declarations and compiler/link configuration context. Conditions and
  variables remain symbolic, just as they do in the explorer.
- `pdf/03-execution-flows.pdf` provides the **What runs when…** flowcharts, with
  named calls and process/event boundaries. Its overview boxes open deeper code
  diagrams in the next volume; evidence notes remain secondary links.
- `pdf/04-code-flowcharts.pdf` expands the overview into diagrams containing
  literal code/configuration lines, highlighted primary paths, nested helper
  diagrams, source links and links back to the parent charts. Its first diagram
  keeps the full main-to-widget path on one landscape Letter page with 9.2-point
  source text, and links directly into declaration rows and constructor detail. Dense diagrams
  continue on linked pages instead of shrinking or dropping source text.
- `pdf/AI-AUTHORED__GUI-MENTAL-MODEL.pdf` provides the simple conceptual diagrams
  described above. It is labeled AI-authored on the cover and diagram pages,
  with links to detailed code diagrams and its separate explorer page.

The edit steps and explorer offer **Read in PDF** links to exact reference pages
where available. The reference books link back to the edit guide and to their
explorer views. Full source bodies and control outlines are retained in the
walkthroughs; candidate-call tables identify any display limits explicitly.
Add `--reference-handbooks` only when you also want six broad inventory volumes
for toolchain, core/CLI, GUI/browser, developer tools, tests/examples, and the
overall file inventory. Detailed explorer views can also be browser-printed.
Keep the `pdf/` folder beside `index.html`; relative cross-file
links depend on PDF viewer support and may require downloading/opening locally.

## What the diagrams mean

[Tree-sitter](https://github.com/tree-sitter/py-tree-sitter) reads C/C++, Rust,
Python, JavaScript, and shell syntax without compiling or executing source.
The CMake readers inventory command declarations and lexical control nesting. JSON/TOML
provide configuration context. Other text is available as captured source.

Function and class locations are syntax-derived. Call links are **name-based
candidates**, not proof of runtime dispatch. Control diagrams describe source
structure, not a compiler-validated control-flow graph. Preprocessor branches,
macros, templates, overloads, virtual calls, callbacks, generated code, language
extensions, implicit exceptions and dynamic imports prevent complete static
resolution. Parse errors and unresolved calls are visible, rather than silently
reported as complete analysis. The C++ grammar also indexes C-like files; it is
not a language-standard conformance check.

CMake conditions, functions, variables, generator expressions and loops remain
symbolic. A source declaration may be conditional, and a helper declaration may
represent several generated targets. The generator does not claim that these
are the targets of any particular configured build.

By default `build/`, `third_party/`, caches, Git internals, agent work directories,
and symlinks are excluded. For page/tab and parameter guidance, the tool reads four selected
GUI contract/example files from the pinned local source archive into memory;
they appear under `@gui-boundary/` with archive provenance. These supplier files
are evidence, not application edit targets. Archives are never extracted,
dependency sources never restored, and patches never applied. Other adapter code
can therefore appear as external/unresolved references. Tests are indexed for navigation but
never run. PowerShell, patches, workflows, non-CMake configuration and documentation
have text/declaration views rather than full function-control analysis. The coverage
page and `atlas.json` list omissions, parsing warnings and excluded directories.

This scope is intentional: answer “where should I start editing?” with modest
local prerequisites. [Doxygen](https://www.doxygen.nl/manual/diagrams.html) is an
alternative for API documentation and call/class diagrams; this tool combines
the mixed-language source map with repository-specific build and extension
guidance. The project-specific prose lives in `navigation_guide.py` and must be
reviewed if ownership conventions change.

## Set up on another computer

Use Python 3.11 or newer and a private environment outside the source checkout.
For the versioned `documentation-tool/` layout, use the setup commands at the top
of this document. For a separately copied tool directory outside the checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
.venv/bin/python -B docmap.py --source ../software-foundation
```

On Windows use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.
Setup downloads prebuilt parser/PDF libraries; **generation itself is offline**.
No Graphviz, Doxygen, LaTeX or application SDK is needed. For a disconnected
machine, first download wheels on a machine with the same OS, CPU and Python:

```sh
python3 -m pip download --only-binary=:all: -r requirements.txt -d wheels
.venv/bin/python -m pip install --no-index --find-links wheels -r requirements.txt
```

Do not add this command to CMake, build scripts, GitHub Actions or regression
test runners. Invoke it only when a person or agent explicitly wants updated
documentation.

## Tool layout

`docmap.py` owns read-only collection, snapshot metadata, conservative candidate
call linking, and output-path checks. `syntax_scan.py` reads syntax trees;
`build_map.py` inventories build declarations; `change_maps.py` and `behavior_paths.py` supply the
task-first edit paths; `source_anchors.py` verifies curated source references.
`flow_maps.py`, `workflow_flows.py`, and `runtime_flows.py` supply the existing
call/process/event scenarios. `code_maps.py` resolves exact source spans and
validates the diagram hierarchy; `workflow_code_maps.py` and
`runtime_code_maps.py` select its critical paths. `parameter_guides.py` explains
dense examples with labeled fields and values; `navigation_guide.py` supplies
project navigation guidance with evidence lines resolved against the snapshot.
`render_html.py`, `explorer.js`, and `explorer.css` provide the browser explorer;
`supplier_reference.py` captures the bounded retained GUI contract evidence.
`render_change_pdf.py` creates the primary edit-path guide;
`render_walkthrough_pdf.py` and `render_compiler_pdf.py` create its deeper linked
references. `render_flow_pdf.py` creates the graphical execution companion;
`render_code_pdf.py` creates its detailed code diagrams. An initial execution
PDF pass records parent pages; a final pass links to exact code-diagram pages.
`conceptual_guide.py` loads and validates the clearly named AI-authored JSON;
`render_concept_html.py` and `render_concept_pdf.py` render that fixed explanation.
`render_pdf.py` creates the optional inventory volumes.
`atlas.json` retains the complete analysis and captured text without requiring
either presentation layer. `export_snapshot.py` copies a reviewed snapshot into
a fresh portable reader directory, including its compact `atlas.json` and
complete `data.js`; it does not run the generator or application tooling.

## Snapshots and verification

The reviewed reader snapshot is committed in `published/`, including `index.html`,
the AI-authored companion HTML, and all six default PDFs. Raw working captures
remain outside the source checkout; exporting selects the reader collection to
version. Neither generation nor export refreshes it automatically. Its capture
date, hashes, coverage notes, and source data remain available in the bundle.

Generator-only checks passed for source/output isolation, symlink and FIFO
handling, parser fixtures, unique symbol IDs, source spans, call targets, guide
references, HTML route logic and escaping, cross-file class membership, PDF
bookmarks, and reference links. Representative final PDF pages were rendered
and visually inspected. Eight C++ files contain recoverable syntax limitations;
the coverage report also records lexical CMake notices and symbolic-build limits.

The expanded collection was generated through the packaged CLI; HTML-only mode
was also checked. All ten edit maps, seven execution scenarios, 35 detailed code
diagrams, seven parameter guides, exact PDF page mappings,
cross-file PDF links, internal bookmarks, source routes, and annotation bounds
passed focused checks. Full selected source bodies and indexed flow labels were
checked for presence; call-table omission counts are explicit. The application
source fingerprint was unchanged by generation. The code-diagram checks cover
all 56 overview destinations, 48 deeper links, 208 code boxes and 515 literal
source lines. Every printed source excerpt is checked on its mapped page;
changed anchors remain explicit review warnings rather than guessed code.
The startup check distinguishes its direct constructor/call path from the table's
data feed; changing a captured widget declaration produces a review marker instead
of retaining an obsolete literal snippet.

The AI-authored companion has four conceptual diagrams, 27 cards and 24 checked
source anchors. Its five PDF pages were rendered and visually inspected; all
card/source links and exact diagram-page destinations were checked. The HTML
checks cover complete labels, arrow routing, source-button clearance, authorship
and capture dates, local links, escaping, and omission of PDF links in HTML-only
mode. A missing-anchor fixture keeps the guide readable and marks all affected
cards for review. The conceptual prose received a separate source review.

The available in-app browser blocked local `file:` URLs, so live browser layout
and interaction were not visually verified here. JavaScript syntax and route
logic were checked independently; open the explorer in your own browser for
that final visual check. No application build, application script, regression
test, Git mutation, or workflow was invoked by the documentation generator.
