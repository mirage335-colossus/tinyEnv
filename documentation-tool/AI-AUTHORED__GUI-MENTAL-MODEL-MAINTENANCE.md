# Maintainer notes: AI-authored conceptual documentation

For developers specifically revising or regenerating the static conceptual guide.
This note lives beside its [authored source](AI-AUTHORED__GUI-MENTAL-MODEL.json)
and renderers; it is not part of the generated explorer or PDF collection.
To read the included documentation, use the
[published reader links](README.md#read-the-included-documentation). They need no
rebuild or development environment.

The diagrams explain mechanisms that usually survive changes to the example's
features. They need editorial attention when those mechanisms change or an
explanation can be made clearer, rather than on every application edit.

There are two different operations. **Rebuild** captures source again and renders
the saved explanations. It needs no AI and does not rewrite the conceptual guide.
**Improve the explanations** edits their versioned content, with or without AI,
then rebuilds and reviews the result. A newer snapshot date is not evidence that
the AI-authored explanation has been reconsidered.

## Choose the kind of change

| Desired improvement | Edit here |
| --- | --- |
| Explain a stable idea with a simple conceptual diagram | [AI-AUTHORED__GUI-MENTAL-MODEL.json](AI-AUTHORED__GUI-MENTAL-MODEL.json) |
| Change conceptual HTML layout, navigation or zoom | [render_concept_html.py](render_concept_html.py) |
| Change conceptual PDF layout, links or printing | [render_concept_pdf.py](render_concept_pdf.py) |
| Change the main explorer's presentation | [explorer.js](explorer.js), [explorer.css](explorer.css), [render_html.py](render_html.py) |
| Add a prospective “what should I edit?” path | [change_maps.py](change_maps.py), [behavior_paths.py](behavior_paths.py) |
| Explain an existing execution scenario or exact source-line path | [runtime_flows.py](runtime_flows.py), [workflow_flows.py](workflow_flows.py), [runtime_code_maps.py](runtime_code_maps.py), [workflow_code_maps.py](workflow_code_maps.py) |
| Change collection, output registration or rendering order | [docmap.py](docmap.py); conceptual schema/link checks are in [conceptual_guide.py](conceptual_guide.py) |

Keep the source-reference diagrams literal and source-backed. Put deliberately
simplified explanations in the conspicuously named AI-authored companion.
Do not edit a generated `index.html`, `data.js`, `atlas.json` or PDF as the lasting
fix: the next generation would discard that edit. Commit the generator and
authored JSON changes, and update the reviewed `published/` reader bundle when
that snapshot update is requested. Keep raw working captures outside the source
checkout.

## Rebuild saved content without AI

After the [one-time environment setup](README.md#run-only-when-a-new-snapshot-is-wanted),
run from the chosen checkout's repository root:

```sh
../software-foundation-docmap-env/bin/python -B documentation-tool/docmap.py
```

This rebuilds the main explorer, separate AI-authored explorer page, all six
default PDFs, and the source snapshot. The tool prints their new locations.
Use `--no-pdf` for an HTML/JSON-only preview. With `--output`, always select a new
directory outside the source checkout; an existing directory is refused.
For a read-only capture of a sibling checkout, supply `--source ../other-checkout`.
Neither form builds, tests or runs that application.

Keep machine-specific paths out of versioned documentation and configuration.
The external virtual environment contains absolute interpreter and installation
paths, so recreate it from `requirements.txt` on each computer. Never commit the
environment. Raw captures also record an absolute source-root path as capture
metadata; keep those working outputs external. The explicit export described
below replaces that host path with portable metadata in the reader bundle. Its
navigation uses local relative links and captured source data, so readers do not
need the original checkout location.

Open the new `AI-AUTHORED__GUI-MENTAL-MODEL.html` and its same-named PDF in `pdf/`.
Keep the complete output directory together: its links need the main explorer,
source data and other PDF volumes. A browser tab already showing an older
snapshot does not move to the new output automatically.

Rebuilding refreshes source anchors, exact source snippets, diagram links and
PDF page references. It does **not** decide whether a conceptual explanation is
still correct. Review changed-source markers, and review the explanation when
an ownership rule, interface or control path changes. Leave `authored_at`
unchanged for a render-only rebuild; update it when the authored explanation
is revised. The generated `generated_at` records the separate capture time.

## Update the committed reader bundle

The included `published/` directory is a reviewed static snapshot, not an
automatic build product. Update it only when a new committed reader snapshot is
explicitly requested:

1. Generate a fresh external capture with the command above. Inspect the new
   explorer, conceptual guide and all six PDFs; review missing anchors and
   changed-source markers. This step does not run application builds or tests.
2. Export into a fresh sibling staging directory. Run from the isolated
   documentation checkout's repository root, replacing the snapshot path:

   ```sh
   python3 -B documentation-tool/export_snapshot.py \
     --snapshot ../path/to/external-snapshot \
     --output documentation-tool/published-staging
   ```

   The exporter refuses an existing output directory. Choose another fresh
   staging name if this one already exists. It copies the reader collection
   without recapturing source or rerendering HTML/PDFs. It writes compact
   `atlas.json` and the complete model in `data.js`, with portable source-root
   metadata; other reader artifacts keep their existing bytes. Keep
   `atlas.json`: the compiler PDF links to it.
   Export supports the default six PDF volumes. Capture without
   `--reference-handbooks`: those optional inventory covers contain the original
   source-root path and are refused by this copy-only exporter.
3. Open the staged `index.html`, the AI-authored HTML, and the six PDFs. Check
   navigation, source and diagram links, dates and the included file collection.
   Keep the complete directory together, including assets and captured source
   data. Cross-PDF navigation also depends on the reader's PDF viewer.
4. Once the requested snapshot is reviewed, replace only
   `documentation-tool/published/` with that staged reader bundle. Preserve the
   generator, authored JSON and all application files. Include the reviewed
   bundle and any intentional documentation-tool source changes in the
   authorized documentation commit; do not merge or push unless requested.

If there is no included bundle yet, the same export command can use
`--output documentation-tool/published` directly. Export is also useful for
relocating an existing reader collection: it accepts its `atlas.json`, or safely
extracts the JSON from its `data.js` without evaluating JavaScript. Pass that
collection's directory to `--snapshot`, not an individual file. Re-exporting
an old collection does not refresh its capture date or source content.

## Prompts you can reuse

Replace the bracketed values before sending a prompt. Include this common scope
with any of the requests below:

```text
Work on the standalone software-foundation documentation only. Read
documentation-tool/AI-AUTHORED__GUI-MENTAL-MODEL-MAINTENANCE.md and the
generator setup in documentation-tool/README.md. Use [isolated documentation checkout] for
edits and [source checkout] as read-only input. Other agents may be working on
the application. Do not change application code, build definitions, CI, tests,
agent coordination records or the active application's Git state. Do not run
application builds, scripts, tests or release commands. Keep generation local,
manual and independent of AI. Preserve the explicit AI-authored labels.
Write new snapshots outside the source checkout. Commit only documentation-tool
changes in the authorized isolated documentation branch; include a reviewed
published/ reader bundle only when its update is requested. Do not merge or push.
Report what changed, the output paths, checks actually performed and limitations.
```

**Rebuild only:**

```text
Rebuild the existing saved documentation from [source checkout] into a new
external snapshot directory. Do not revise the authored explanations or
application. Generate the main explorer, AI-authored conceptual explorer and
PDF collection. Report missing source anchors separately from successful
rendering, and give me links to the new outputs.
```

**Update the included reader snapshot:**

```text
Generate a fresh external documentation snapshot from [source checkout]. Export
it to a fresh documentation-tool/published-staging directory, inspect the main
explorer, AI-authored HTML, all six PDFs and their links, then replace only
documentation-tool/published with the reviewed bundle. Include those artifacts
in the authorized isolated documentation commit. Do not change the application,
run its tools, merge or push. Report the capture date, exported paths and checks.
```

**Add or clarify one conceptual model:**

```text
Improve the AI-authored conceptual guide to answer this newcomer question:
[one concrete question, for example: which object owns the actual records,
and which objects only hold data to display?]
Read the implementation and existing detailed diagrams before writing.
Use a small diagram with plain-language labels, a clear primary path and
separate call, data, event and return arrows. Show ownership or the boundary
crossed when it matters. Link boxes to the relevant detailed code diagrams
and checked source anchors. Keep infrastructure secondary. Label any proposed
behavior as proposed; do not portray it as implemented. Prefer changing the
authored JSON to special-casing a renderer. Update the authorship date,
regenerate both HTML and PDF, and inspect legibility and navigation.
```

**Improve exploration or print layout:**

```text
Improve [specific navigation/layout issue] in the documentation explorer and
PDFs. Preserve the explanations and source meaning unless correcting a
verified error. Keep simple conceptual diagrams distinct from literal code
diagrams. Retain local-file operation, readable printing, source links,
deeper-diagram links and upward navigation. Verify HTML-only mode as well as
PDF output when the change affects both. Do not add network or AI dependencies.
```

A useful request states the question the reader must answer and the desired
visible result, rather than merely asking for “more detail.” For example:
“Show the request leaving Application, the host doing file I/O, and the result
returning to Application; make it obvious which side owns parsing.”

## Add another conceptual diagram

1. Check whether the idea already has a conceptual diagram, an edit map or a
   detailed code diagram. Add a simple model only when it explains a relationship
   that those views make hard to see.
2. Add a diagram to the JSON's `diagrams` array. Give it a stable lowercase,
   hyphenated `id`, a reader question, a short summary, nodes and edges.
   Retain existing IDs so saved links keep working. Aim for five to seven boxes;
   the current schema allows at most eight, with unique positions using columns
   `0..2` and rows `0..5`. Split a complicated subject into smaller diagrams.
3. Use node kinds `call`, `data`, `application`, `boundary`, `backend` or `core`,
   and edge kinds `call`, `data`, `event`, `return` or `step`. A
   `detail: {"map": "...", "node": "..."}` must name an existing code-map
   target; `node` is optional. A `source: {"path": "...", "needle": "..."}`
   must identify a unique literal source fragment. The builder resolves its
   current line; do not hand-maintain line numbers or PDF page numbers.
4. Read the linked implementation and review the explanation separately.
   Check deferred callbacks, ownership, rejected/stale results and returns to
   callers. A matched source anchor proves a location was found, not that an
   AI-authored causal claim is true. Fix stale documentation, never application
   code to make an old documentation anchor match.
5. Rebuild a fresh snapshot and check the resulting HTML and PDF. Follow the
   new links, check the main explorer's entry to the guide, inspect all changed
   PDF pages, and confirm labels and arrows are readable. Check
   `conceptual_guide.source_status` and `conceptual_guide.source_warnings`
   in `atlas.json`.
   Missing source should remain a visible review item. If JavaScript changed,
   `node --check documentation-tool/explorer.js` is a useful optional syntax
   check; Node is not required to run the documentation generator.

Adding ordinary diagrams to the existing guide does not require editing the
renderers. The current implementation supports one conceptual guide with a fixed
filename, however: dropping a second JSON file beside it does not register a
second guide. A new subject-specific volume needs explicit generator, renderer,
index and link registration. Keep an `AI-AUTHORED__...` filename and visible
authorship label for every such companion. Check cover/index pagination as a
guide grows instead of squeezing more concepts onto each page.

## Which conceptual models are worth adding?

Explain the reusable mechanisms that a developer is likely to keep while
replacing the example's feature. Treat these as **stable patterns in this
example**, not promises that all hosts or future versions are identical.
Prefer ownership and handoff diagrams over diagrams of temporary filenames,
release numbers, runner choices or every defensive check.

The following are proposed additions, not diagrams already present in the
four-diagram conceptual guide. Some already have more detailed source views:

| Priority and model | Newcomer question and simple picture | Existing detail to reuse |
| --- | --- | --- |
| 1. Authoritative data and display state | “Which object should I change?” Store owns records; Application owns editing/selection state and projects record copies into gui::Snapshot -> adapter. Distinguish Store::snapshot() copies from gui::Snapshot; selection uses stable record IDs. | `application-ownership`, `core-add`, `publish-view`; the selected-entry edit map |
| 2. Generic import/export service boundary | “Where does format logic stop and file I/O start?” Import: request -> host reads -> matching completion -> shared parse/apply -> publish. Export: shared serialization -> host writes -> matching completion -> status. Keep service-ID correlation distinct from input freshness. | `service-request`, `service-pump`, `service-completion`, `import-parser`, `native-transfer` |
| 3. Background work and stale results | “How can work finish without updating the wrong view?” Copied input -> task executor -> owned value result -> generation/progress checks -> shared publication. Show cancellation separately and keep workers free of UI/live Store references; native and cooperative executors use different machinery. | Background-task edit map and its captured TaskExecutor/Application source; add missing code-detail diagrams explicitly |
| 4. Source files, targets and build phases | “Why does adding a file not automatically compile it?” Source/module ownership -> target declaration -> configure target graph -> generated prerequisites -> compile/Cargo -> link. Distinguish declaration relationships from execution order, Rust module membership from C++ source lists, and test registration from execution. | Source-file edit map, `cmake-core`, `build-sequence`, `rust-component`, `test-registration` |
| 5. The C++/Rust provider boundary | “How can implementation language change without changing callers?” Store contract -> private validation ABI -> configured C++ or Rust provider -> status/error conversion. Selection happens at configuration time; C++ retains record ownership. | `core-validation`, `cpp-provider`, `rust-provider`, `rust-component` |
| 6. Host composition around shared behavior | “What changes between CLI, native GUI and browser?” Distinct entry points and host services around shared domain behavior; native/browser GUI hosts share Application, while CLI uses core directly. | `gui-startup`, `application-ownership`, entry-point inventory; add missing CLI/browser detail diagrams explicitly |

Ownership, background tasks and import/export fit naturally beside the GUI
models. Build phases and language-provider selection would be clearer in a
separately registered conceptual companion than in an ever-longer GUI guide.
Do not describe page tabs as existing application behavior: this example has an
edit path for adding them, but its current shared application has no tabs.
