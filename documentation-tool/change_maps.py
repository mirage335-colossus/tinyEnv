"""Task-specific edit routes, resolved against captured source without execution.

The recipes express project ownership decisions; source anchors, snippets and
function links are regenerated. Missing/ambiguous anchors fail visibly rather
than silently drifting to an unrelated line. Proposed methods are illustrations,
not definitions discovered in the checkout.
"""
from __future__ import annotations


def make_change_maps(files: list[dict]) -> list[dict]:
    from source_anchors import make_source_ref
    ref = make_source_ref(files)

    button = ref('Existing button row', 'gui/shared/view_definition.hpp',
                 'ViewDefinition{"entries.add", gui::Kind::button')
    route = ref('Existing Activate routing', 'gui/shared/application.cpp',
                'if (widget->target.id == "entries.add") append_entry();')
    app_decl = ref('Existing member declaration', 'gui/shared/application.hpp', '    void append_entry();')
    app_impl = ref('Existing application helper', 'gui/shared/application.cpp',
                   'void Application::append_entry() {')
    core_add = ref('Existing domain operation', 'src/store.cpp',
                   'RecordId Store::add(std::string_view text) {')
    core_decl = ref('Public core interface', 'include/foundation/store.hpp', 'class Store')
    publish = ref('Shared state projection', 'gui/shared/application.cpp', 'void Application::publish() {')
    present = ref('Present projected state', 'gui/shared/application.cpp', '    adapter_.present(next);')
    after_dispatch = ref('Publication after dispatch returns', 'gui/shared/application.cpp',
                         '        }, widget->input);\n    }\n    publish();')
    creation = ref('Existing widget creation loop', 'gui/shared/application.cpp',
                   '        if (!definition.remove_extension) add(definition);')
    core_target = ref('Core source list', 'CMakeLists.txt',
                      'add_library(foundation_core STATIC src/store.cpp src/text_validation.cpp)')
    gui_target = ref('Shared GUI source list', 'gui/CMakeLists.txt',
                     'add_library(foundation_gui_application STATIC shared/application.cpp ${foundation_task_executor})')
    cli_target = ref('CLI source list', 'CMakeLists.txt', 'add_executable(foundation-cli src/main.cpp)')
    host_target = ref('Host target helper', 'gui/CMakeLists.txt', 'function(foundation_gui_executable target source)')
    rust_root = ref('Reachable crate root', 'rust/text_validation/src/lib.rs', '#![cfg_attr(not(test), no_std)]')
    source_glob = ref('GUI inventory, not compiler selection', 'gui/CMakeLists.txt',
                      'file(GLOB_RECURSE foundation_gui_owned_sources')
    wrapper = ref('Existing manual build entry', 'build.sh', '"$root/tools/build.py"')

    def node(id, role, title, summary, action, why, column, row, refs=(), **extra):
        references = list(refs)
        primary = references[0] if references else {}
        status = ('missing' if any(r['status'] == 'missing' for r in references)
                  else 'proposed' if role == 'NEW' else 'verified')
        return dict(id=id, role=role, title=title, summary=summary, action=action,
                    why=why, column=column, row=row, references=references,
                    path=primary.get('path'), line=primary.get('line'),
                    file_id=primary.get('file_id'), symbol_id=primary.get('symbol_id'),
                    snippet=primary.get('snippet', ''), status=status,
                    optional=False, **extra)

    def edge(a, b, label, kind='edit-dependency'):
        return dict(from_=a, to=b, label=label, kind=kind)

    def finish(id, title, question, summary, meaning, nodes, edges):
        for e in edges:
            e['from'] = e.pop('from_')
        return dict(id=id, title=title, question=question, summary=summary,
                    edge_meaning=meaning, nodes=nodes, edges=edges)

    widget = finish(
        'widget', 'Add a clickable widget and a helper',
        'Which files do I edit for a widget, its click event, and a function called beneath that event?',
        'Start with the top row. Follow the helper-ownership branch, then use the conditional steps below. '
        'Click any box for the edit, the reason, and the exact existing example. on_custom(), '
        'apply_custom_action(), and custom_operation() below are proposed names, not existing functions.',
        'Arrows show edit dependencies. They are not execution arrows. EDIT/NEW boxes identify work; '
        'REUSE boxes identify machinery already in place. The existing Add-entry runtime has its own linked map.',
        [
            node('widget-row', 'EDIT', '1. Declare the widget', 'view_definition.hpp · stable ID',
                 'Add a ViewDefinition row for a supported widget kind, for example a button with ID entries.custom, '
                 'label, and height. Insert the row at the desired vertical position. For its parent, tab, spacing, or custom bounds, '
                 'follow the Place a widget map linked below. Reuse that exact ID in the event route. '
                 'A new widget instance uses the existing gui::Activate event.',
                 'This ordered table already supplies widget creation, ordering, and shared layout. '
                 'A new rendering capability or new event type would be a separate contract change.', 0, 0, [button],
                 link_map='widget-placement'),
            node('activation', 'EDIT', '2. Route its click', 'Application::handle · Activate',
                 'Inside the gui::Activate branch, add a target-ID case that calls on_custom(), following the entries.add case. '
                 'Keep the existing close/shutdown checks and event normalization ahead of dispatch.',
                 'Widget identity selects application behavior. The generic host already forwards events to handle.', 1, 0, [route]),
            node('handler', 'NEW', '3. Add on_custom()', 'Application handler · proposed',
                 'Declare on_custom() in Application (normally private), and implement it in application.cpp. '
                 'Have it read the relevant widget state and call your helper. Follow append_entry() for owned core calls, '
                 'status updates, and exception handling; preserve input_epoch invalidation when changing authoritative input meaning.',
                 'Separate event dispatch from feature behavior, so another event can reuse the same action.', 2, 0, [app_impl, app_decl]),
            node('helper-owner', 'DECISION', '4. What does the helper own?', 'UI behavior or reusable domain logic?',
                 'Choose the helper by responsibility. Application commands and view state stay in the shared GUI. '
                 'Behavior useful to the CLI and GUI belongs in the core. The helper below the handler does not belong in a renderer.',
                 'This is the decision that determines the next file to edit.', 3, 0, [app_impl, core_decl]),
            node('existing-machinery', 'REUSE', 'Creation and event plumbing', 'Existing table + shared host',
                 'For another instance of an already supported widget, the constructor already creates table rows '
                 'and the host already forwards events. Inspect these anchors if you need context.',
                 'Ordinary application widget behavior is shared across backends.', 0, 1,
                 [creation, ref('Native event forwarding', 'gui/host/contract.hpp',
                                '        if (current_) { current_->handle(event); services(); }')]),
            node('existing-example', 'JUMP', 'Trace the existing Add button', 'Actual click → handler → core helper',
                 'Open the existing Add-entry runtime map to see entries.add → handle → append_entry → Store::add '
                 '→ Store::validate, followed by publication from handle.',
                 'Use a concrete, source-linked implementation as the pattern for the proposed edit.', 1, 1,
                 [route, app_impl, core_add], link_map='widget-runtime'),
            node('gui-helper', 'NEW', '4a. apply_custom_action()', 'UI helper · Application · proposed',
                 'Implement apply_custom_action() beside the other Application methods and declare it in application.hpp '
                 'if it is a member. The proposed on_custom() calls it. A file-local free helper may stay in the same .cpp '
                 'without adding a header declaration.',
                 'Feature state and command meaning belong here. Existing .cpp files are already compiled.', 2, 1,
                 [app_impl, app_decl]),
            node('core-helper', 'NEW', '4b. custom_operation()', 'Domain helper · Store · proposed',
                 'Add reusable behavior to the appropriate core module. For the proposed Store::custom_operation(), declare the API in store.hpp '
                 'and implement it in store.cpp; then call it from the Application handler. '
                 'The existing append_entry() → Store::add() relationship is the pattern.',
                 'Core behavior should be usable without a GUI adapter or widget ID.', 3, 1, [core_add, core_decl, app_impl]),
            node('projection', 'EDIT', '5. Project changed state', 'Application::publish · if needed',
                 'If the widget needs derived text, enabled state, status, or custom bounds, update publish(). '
                 'Table-driven creation and normal vertical layout already apply. '
                 'handle() calls publish() after dispatch returns; do not assume append_entry() calls it.',
                 'Presentation is a projection of shared state. adapter_.present receives the resulting snapshot.', 2, 2,
                 [publish, after_dispatch, present]),
            node('new-translation-unit', 'JUMP', 'New .cpp file?', 'Only then register it with CMake',
                 'If all new functions remain in an already compiled .cpp, no source-list addition is needed. '
                 'If you create a new .cpp, open the source-file map and register it with its owning target.',
                 'A new function and a new translation unit are different extension steps.', 3, 2,
                 [gui_target, core_target], link_map='source-files'),
        ], [
            edge('widget-row', 'activation', 'same widget ID'),
            edge('activation', 'handler', 'calls on_custom()'),
            edge('handler', 'helper-owner', 'calls a helper'),
            edge('helper-owner', 'gui-helper', 'UI-only', 'conditional'),
            edge('helper-owner', 'core-helper', 'domain behavior', 'conditional'),
            edge('gui-helper', 'projection', 'if visible state changes', 'conditional'),
            edge('core-helper', 'projection', 'if visible state changes', 'conditional'),
            edge('handler', 'new-translation-unit', 'if any new .cpp', 'conditional'),
            edge('widget-row', 'existing-machinery', 'already consumed'),
        ])

    source = finish(
        'source-files', 'Make a new source file compile',
        'Where do I put a new file, and which compiler source list must I edit?',
        'Choose the role of the file. Each branch names the file location and the exact source-registration edit. '
        'An existing function body or header declaration is different from a new translation unit.',
        'Decision arrows choose one source role. Each branch is a self-contained edit recipe; these are not build-execution arrows.',
        [
            node('choose-role', 'DECISION', 'What kind of file?', 'Choose the owner before adding it',
                 'Decide whether the new code is core behavior, shared GUI behavior, CLI composition, host support, '
                 'a Rust module, or a header. Then follow the corresponding branch.',
                 'The owning target determines where the compiler gets its source list.', 1, 0, []),
            node('core-cpp', 'EDIT', 'Core .cpp', 'src/new_file.cpp → foundation_core',
                 'Create the .cpp under src/. Add its source-relative path to add_library(foundation_core STATIC ...), '
                 'or an explicit target_sources(foundation_core PRIVATE ...) in the root CMakeLists.txt. '
                 'Expose public declarations under include/foundation/.',
                 'A new file in src/ is not automatically compiled.', 0, 1, [core_target, core_decl]),
            node('gui-cpp', 'EDIT', 'Shared GUI .cpp', 'gui/shared/ → foundation_gui_application',
                 'Create the file under gui/shared/. In gui/CMakeLists.txt add shared/new_file.cpp to '
                 'foundation_gui_application, alongside shared/application.cpp. Include the appropriate declaration '
                 'from the caller. Preserve the existing platform selection for task executors.',
                 'The recursive GUI source GLOB watches boundary checks; it is not the compiler source list.', 1, 1,
                 [gui_target, source_glob]),
            node('cli-cpp', 'EDIT', 'CLI support .cpp', 'foundation-cli source list',
                 'Add the CLI-specific implementation file to add_executable(foundation-cli ...) in root CMakeLists.txt, '
                 'or target_sources(foundation-cli PRIVATE ...). Put reusable operations in the core instead.',
                 'The CLI target composes the application and links foundation::core.', 2, 1, [cli_target]),
            node('host-cpp', 'EDIT', 'Host support .cpp', 'selected host target in gui/CMakeLists.txt',
                 'For an extra file in an existing host, use target_sources(the-existing-host PRIVATE ...) after its '
                 'foundation_gui_executable declaration. For a new executable composition root, use the existing helper. '
                 'Keep product widget IDs and command meaning on the shared Application side.',
                 'The helper accepts a target and one primary source; additional translation units belong to the actual target.',
                 0, 2, [host_target]),
            node('rust-module', 'EDIT', 'Rust module .rs', 'existing crate + reachable mod declaration',
                 'Add the .rs file under rust/text_validation/src/ and declare mod new_module; from lib.rs '
                 'or another reachable module. Call or expose its functions as needed. The existing CMake input inventory '
                 'already watches .rs files, but it does not make an undeclared Rust module reachable.',
                 'A new crate, dependency, or build.rs is a separate build-policy change, not this internal-module recipe.', 1, 2,
                 [rust_root, ref('Rust source inventory', 'cmake/RustComponent.cmake', 'file(GLOB_RECURSE rust_inputs'),
                  ref('Workspace restrictions', 'tools/rust_build.py', 'def _metadata(root, cargo, environment, build):')]),
            node('header-only', 'EDIT', 'Header or existing-file method', 'declaration/include; no new translation unit',
                 'Add the declaration to the owning header and include it from reachable code. If the implementation '
                 'stays in an existing .cpp, there is no new source file to register. Inline/template definitions belong '
                 'in a reachable header. Public include/foundation headers are covered by the existing include-directory install rule.',
                 'CMake source registration is required for a new .cpp, not merely for a new function declaration.', 2, 2,
                 [app_decl, ref('Public header installation', 'CMakeLists.txt',
                                'install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})')]),
            node('normal-build', 'REUSE', 'Use the existing build entry', 'build.sh → tools/build.py → CMake',
                 'After an actual implementation change, use the project\'s existing manual build workflow and selected '
                 'configuration. This documentation generator only shows that workflow and does not invoke it.',
                 'Registering an ordinary source in its target does not require adding a documentation build hook '
                 'or changing CI, compiler installation, presets, or runners.', 1, 3, [wrapper]),
        ], [edge('choose-role', n, label, 'conditional') for n, label in [
            ('core-cpp', 'core'), ('gui-cpp', 'shared GUI'), ('cli-cpp', 'CLI'),
            ('host-cpp', 'host'), ('rust-module', 'Rust'), ('header-only', 'header / existing .cpp')]]
    )

    runtime = finish(
        'widget-runtime', 'Existing example: Add entry',
        'Which existing functions does an Add-entry click reach?',
        'This is the source-backed example behind the edit recipe. Follow the call chain into the deeper helper; '
        'handle() publishes after its event dispatch returns. It also routes SubmitText to append_entry().',
        'Arrows show named calls or explicit event/return ordering in this example, not a complete runtime graph. '
        'The adapter event bridge is a contract relationship. Provider selection remains conditional.',
        [
            node('add-widget', 'REUSE', 'entries.add button', 'view_definition.hpp',
                 'The row declares the button ID and label. A supported adapter turns activation into a WidgetEvent '
                 'targeting that ID with gui::Activate input.',
                 'Use the same ID in declaration and dispatch.', 0, 0, [button]),
            node('event-bridge', 'REUSE', 'Generic event forwarding', 'Session → application.handle(event)',
                 'The native Session adapter callback forwards events to the application. Browser hosts have their '
                 'own transport bridge but reach the same shared application event logic.',
                 'A feature click does not need separate business handlers for each backend.', 1, 0,
                 [ref('Session callback', 'gui/host/contract.hpp',
                      '        if (current_) { current_->handle(event); services(); }')]),
            node('dispatch', 'REUSE', 'Application::handle', 'Activate + entries.add → append_entry()',
                 'After normalization, the Activate branch matches widget->target.id. The entries.add case calls '
                 'append_entry(). After normal visitor completion, handle calls publish().',
                 'This is the precise routing edit point for a new button ID.', 2, 0, [route, after_dispatch]),
            node('app-operation', 'REUSE', 'Application::append_entry', 'handler helper → entries_.add(text)',
                 'Read editor text, call the core operation, clear the editor on success, and set shared status. '
                 'Caught invalid_argument and length_error exceptions update shared error status; other exceptions can escape. '
                 'append_entry does not itself call publish.',
                 'This is the model for the function below your event handler.', 3, 0, [app_impl]),
            node('publish', 'REUSE', 'Application::publish', 'snapshot → state/layout → present',
                 'After normal dispatch completion, handle calls publish. It projects Store records into list rows and updates '
                 'layout, status, and enabled flags before adapter_.present(next).',
                 'Edit this function when new state needs a visible projection.', 0, 1, [publish, present, after_dispatch]),
            node('provider', 'REUSE', 'Selected text validator', 'private C ABI → Rust or C++ provider',
                 'detail::validate_text calls foundation_text_validate_v1. The selected provider implements that private ABI; '
                 'fresh configurations default to Rust. Both providers preserve the same text contract.',
                 'Follow these deeper links when changing validation itself.', 1, 1,
                 [ref('Private wrapper', 'src/text_validation.cpp',
                      'uint32_t validate_text(const uint8_t *bytes, size_t length) noexcept {'),
                  ref('Rust entry', 'rust/text_validation/src/lib.rs', 'pub unsafe extern "C" fn foundation_text_validate_v1'),
                  ref('Rust validation body', 'rust/text_validation/src/lib.rs', 'fn validate_text(bytes: &[u8]) -> u32 {'),
                  ref('C++ provider', 'src/text_validation.cpp', 'extern "C" uint32_t foundation_text_validate_v1')]),
            node('domain-helper', 'REUSE', 'Store::validate', 'deeper helper beneath Store::add',
                 'Store::add calls validate(text). This helper calls detail::validate_text and translates private '
                 'status codes into the public C++ exception contract.',
                 'This is a concrete function called by the function beneath the event.', 2, 1,
                 [ref('Core validator helper', 'src/store.cpp', 'void Store::validate(std::string_view text) {')]),
            node('core-operation', 'REUSE', 'Store::add', 'validate → capacity / ID → owned record',
                 'Validate text before insertion, check capacity and identifier availability, then insert an owned record '
                 'and advance the ID. Callers receive the new record ID.',
                 'Reusable domain rules are implemented here, outside GUI event routing.', 3, 1, [core_add]),
        ], [
            edge('add-widget', 'event-bridge', 'adapter emits Activate', 'runtime'),
            edge('event-bridge', 'dispatch', 'forwards event', 'runtime'),
            edge('dispatch', 'app-operation', '1. calls handler helper', 'runtime'),
            edge('app-operation', 'core-operation', 'entries_.add(text)', 'runtime'),
            edge('core-operation', 'domain-helper', 'validate(text)', 'runtime'),
            edge('domain-helper', 'provider', 'detail::validate_text', 'runtime'),
            edge('dispatch', 'publish', '2. after normal dispatch', 'runtime'),
        ])
    definition = ref('Shared declaration model', 'gui/shared/view_definition.hpp', 'struct ViewDefinition {')
    order = ref('Widget declaration order', 'gui/shared/view_definition.hpp',
                'inline constexpr std::array view_definition{')
    root_group = ref('Current root group', 'gui/shared/view_definition.hpp',
                     'ViewDefinition{"entries.form", gui::Kind::group')
    parenting = ref('Current fixed parent assignment', 'gui/shared/application.cpp',
                    'if (definition.id != view_definition.front().id) widget.spec.parent = view_definition.front().id;')
    layout_column = ref('Current vertical layout', 'gui/shared/application.cpp',
                        'panel.kind = gui::LayoutKind::column;')
    layout_rows = ref('Table order and height feed layout', 'gui/shared/application.cpp',
                      'child(std::string(definition.id), definition.height);')
    layout_bounds = ref('Client-space composition', 'gui/shared/application.cpp',
                        'const auto boxes = gui::compose_layout(panel, {16, 16, width, height},')
    bounds_copy = ref('Computed bounds become widget state', 'gui/shared/application.cpp',
                      'lookup(next, box.id).state.bounds = box.bounds;')
    supplier_contract = '@gui-boundary/include/gui/contract.hpp'
    supplier_example = '@gui-boundary/examples/application.hpp'
    page_membership = ref('Retained WidgetSpec membership', supplier_contract, 'std::string page,parent,binding;')
    same_page = ref('Retained parent/page invariant', supplier_contract,
                    'require(found->second->spec.page==s.page,"Child and parent must use the same page");')
    page_event = ref('Retained page event', supplier_contract, 'struct PageEvent {std::string id;};')
    page_bar = ref('Retained tab-bar bounds', supplier_contract, 'Rect page_bar;')
    normalization = ref('Existing event normalization', 'gui/shared/application.cpp',
                         'if (!gui::normalize_event(view_, event, [this](const gui::WidgetKey& key) {')

    placement = finish(
        'widget-placement', 'Place a widget in the right position and page',
        'Where do I set its order, height, parent group, and tab?',
        'Today this application has one vertical panel and no page tabs. In that panel, table order sets vertical '
        'order and each row sets height. An ID prefix does not select a tab. For page membership, first follow '
        'the Add a tab path; the current declaration model has no page or parent field.',
        'Arrows choose placement edits. Ordinary ordering reuses the current column; custom grouping and pages '
        'require shared declaration and layout changes. These are editing paths, not runtime calls.',
        [
            node('placement-choice', 'DECISION', 'Where should it appear?', 'Current column, custom group, or page?',
                 'Choose the existing entries.form column, a custom arrangement, or a page tab. The current app '
                 'has no tabs. Do not infer parent or page from an ID such as settings.button.',
                 'The placement choice determines whether a row edit is enough.', 1, 0, [root_group, parenting]),
            node('table-order', 'EDIT', 'Set vertical order and height', 'view_definition · row position + height',
                 'Insert or move the widget row between the controls that should appear above and below it. '
                 'Set its height field. Keep entries.form first: add() currently parents every other widget to that root. '
                 'The normal publish() loop consumes the rows in this order; optional remove_extension rows appear only when enabled.',
                 'A row in this table is the ordinary vertical placement edit; coordinates are computed later.', 0, 1,
                 [order, button, layout_rows]),
            node('custom-layout', 'EDIT', 'Change grouping or spacing', 'Application::publish + explicit parents',
                 'For spacing, edit panel.gap and panel.padding in publish(). For horizontal rows or nested groups, '
                 'build the corresponding shared LayoutNode tree and extend ViewDefinition/add() to assign matching explicit parents. '
                 'Each parent group must precede its children in the snapshot. Update the existing entries.form clipping assumptions '
                 'when introducing additional root groups; no renderer should position application-specific controls.',
                 'The layout tree computes bounds; WidgetSpec.parent supplies containment and clipping. Both must agree.', 1, 1,
                 [layout_column, ref('Panel padding', 'gui/shared/application.cpp', 'panel.padding = {8, 8, 8, 8};'),
                  ref('Panel spacing', 'gui/shared/application.cpp', 'panel.gap = 4;'), parenting]),
            node('choose-page', 'EDIT', 'Assign page and parent', 'WidgetSpec.page + WidgetSpec.parent',
                 'Once pages are initialized, set the intended page ID explicitly on the widget and on its parent group. '
                 'Give each page its own root group before its children, and map the declaration fields in add(). '
                 'An empty page means shared chrome. A nonempty page must name a declared page; parent and child must use the same page.',
                 'Names such as entries.custom are widget IDs only; they do not establish tab membership.', 2, 1,
                 [definition, parenting, page_membership, same_page]),
            node('compose-bounds', 'REUSE', 'Let shared layout place it', 'publish → compose_layout → bounds',
                 'Keep layout in publish(): compose within the client area, then copy flattened layout boxes into '
                 'widget.state.bounds. The present app uses a 16-unit outer inset and a column with 8-unit padding and 4-unit gaps. '
                 'Use per-page content bounds when a tab bar is introduced. Resize events reach the same publication path.',
                 'Changing a backend-specific pixel position would bypass the shared placement source.', 0, 2,
                 [layout_bounds, bounds_copy, publish]),
            node('placement-event', 'JUMP', 'Wire the placed control', 'Use its same stable widget ID',
                 'After placement, follow the widget/event/helper path to implement the control behavior. '
                 'Adding only a row or member method in an existing .cpp does not add a compiler source-list step.',
                 'Placement and click behavior are distinct edits, connected by the widget ID.', 1, 2,
                 [route], link_map='widget'),
            node('create-pages', 'JUMP', 'No tabs yet? Add the page model', 'Pages + switching + tab-bar geometry',
                 'Follow Add a tab for the first page system and for subsequent pages. It covers page declarations, '
                 'membership, layout, tab-bar bounds, PageEvent routing, and active-page/focus consistency.',
                 'Another ViewDefinition row alone cannot create a tab in this application.', 2, 2,
                 [page_event, page_bar], link_map='tabs'),
        ], [
            edge('placement-choice', 'table-order', 'ordinary column', 'conditional'),
            edge('placement-choice', 'custom-layout', 'rows / groups', 'conditional'),
            edge('placement-choice', 'choose-page', 'page membership', 'conditional'),
            edge('table-order', 'compose-bounds', 'computed placement'),
            edge('custom-layout', 'compose-bounds', 'matching layout tree'),
            edge('choose-page', 'create-pages', 'first establish pages'),
            edge('compose-bounds', 'placement-event', 'then behavior'),
        ])

    tabs = finish(
        'tabs', 'Add a page tab and place its contents',
        'Which edits create a tab, put widgets beneath it, and make switching work?',
        'This is a proposed extension: the current Application initializes no pages. The retained GUI contract already '
        'supports Page, WidgetSpec.page, PageEvent, and page_bar; there is no Kind::tabs widget. For the first tabs, '
        'complete this path. Once shared support exists, another tab mainly adds a page entry and its owned content. '
        'Supplier links are read-only excerpts from the pinned local archive, not files to edit.',
        'Arrows show the required application edit sequence. All edits belong in gui/shared; supported tabs and '
        'controls reuse generic adapters. NEW marks application state to add, not existing functionality.',
        [
            node('declare-pages', 'NEW', '1. Declare pages and selection', 'Application constructor · pages + active_page',
                 'Near view_.title in the constructor, initialize view_.pages with stable IDs and labels, for example '
                 'entries and settings, then set view_.active_page to an available page ID. Keep page IDs unique and nonempty. '
                 'After this support is implemented, adding another tab starts by adding its Page entry here.',
                 'The tab registry and selection belong to the shared Snapshot. This app currently initializes neither.', 0, 0,
                 [ref('Application initialization', 'gui/shared/application.cpp', 'view_.title = "Entry list";'),
                  ref('Retained Page type', supplier_contract, 'struct Page {'),
                  ref('Retained page initialization example', supplier_example,
                      'view_.pages={{"main","Controls"},{"other","Other page"}};view_.active_page="main";')]),
            node('declare-page-content', 'EDIT', '2. Declare page-owned content', 'ViewDefinition · page + parent fields',
                 'Extend ViewDefinition with explicit page ID and parent ID fields, then update its rows. '
                 'Declare an entries root group and a settings root group before their children; assign each root and all '
                 'of its descendants the same page ID. Existing entries controls must be assigned deliberately instead of '
                 'remaining page-less. Leave page empty only for chrome intentionally shared by all pages.',
                 'The current row schema has no page or parent field; an ID prefix cannot select a tab.', 1, 0,
                 [definition, order, page_membership, same_page]),
            node('copy-membership', 'EDIT', '3. Create widgets on their page', 'Application::add · replace fixed root',
                 'Replace add()\'s universal first-row parent assignment with the explicit parent and page from each '
                 'declaration. Preserve unique widget IDs and ensure each parent is an earlier group on the same page. '
                 'Update any other feature-created widgets to follow that ownership model.',
                 'Without this edit, every widget still belongs to entries.form, regardless of the intended tab.', 2, 0,
                 [parenting, page_membership, same_page,
                  ref('Retained parent ordering rule', supplier_contract,
                      'require(found!=widgets.end()&&found->second!=&w&&found->second->spec.kind==Kind::group,"Parent must be an earlier group");')]),
            node('page-layout', 'EDIT', '4. Lay out content and tab bar', 'Application::publish · per-page layout',
                 'Replace the single entries.form layout assumption with one content layout per page plus any shared chrome. '
                 'Apply bounds to the corresponding widget IDs and update group content size/clipping for each root. '
                 'Set next.page_bar to a positive rectangle inside the client area, reserve space so it does not overlap content, '
                 'and recompute both on resize. Zero default page_bar means no visible tab controls.',
                 'Declaring Page entries alone does not allocate visible tab-bar space or place their contents.', 3, 0,
                 [layout_bounds, bounds_copy, page_bar,
                  ref('Retained tab-bar layout example', supplier_example,
                      'next.page_bar={16,std::max(0.0,next.client_size.height-32),std::max(0.0,next.client_size.width-32),24};')]),
            node('page-switch', 'EDIT', '5. Handle a page switch', 'Application::handle · PageEvent',
                 'After the existing normalize_event gate, add a std::get_if<gui::PageEvent> branch and set '
                 'view_.active_page to page->id. Preserve the final publish() call so selection and visibility reach the adapter. '
                 'Use input-epoch invalidation if the switch changes authoritative input meaning; do not bypass event normalization.',
                 'The current handler has no PageEvent branch. Normalization already rejects unavailable pages, the active page, '
                 'and page switches while a modal root is active.', 3, 1,
                 [normalization, after_dispatch, page_event,
                  ref('Retained page event example', supplier_example,
                      '} else if(const auto* page=std::get_if<gui::PageEvent>(&event)) {')]),
            node('reuse-tabs', 'REUSE', '6. Reuse tab rendering', 'Page registry → generic adapters',
                 'Publish the shared Snapshot. Existing supported adapters draw the tab bar from pages/page_bar and emit PageEvent; '
                 'page membership determines content availability. Do not add a product-specific tab to each renderer. '
                 'This recipe stays in existing shared source files, so it does not require a new compiler source entry.',
                 'Pages are an existing GUI contract capability. Supplier excerpts are evidence and examples, not edit targets.', 2, 1,
                 [present, ref('Retained tab projection', '@gui-boundary/include/gui/presentation.hpp',
                               'inline std::vector<PageTab> page_tabs(const Snapshot& snapshot) {')]),
            node('page-focus', 'REUSE', '7. Reuse adapter focus handling', 'Focus is adapter-owned · optional policy',
                 'Keep active_page and all page memberships valid if pages are removed. Publishing the new snapshot '
                 'lets the adapter clear focus that is no longer available; focus is not a Snapshot field. If a particular '
                 'control should gain keyboard focus after a page switch, call adapter_.focus(...) after publish() succeeds, '
                 'using a visible, enabled, focusable target in the newly presented page. Keyboard Tab follows available '
                 'controls in snapshot order; it differs from the page tabs described here.',
                 'The existing adapter owns focus and availability. Add application focus policy only when the feature needs it.', 1, 1,
                 [ref('Retained adapter focus API', supplier_contract,
                      'virtual bool focus(std::optional<WidgetKey> target)=0;'),
                  ref('Retained keyboard traversal API', supplier_contract,
                      'virtual bool focus_next(bool reverse=false)=0;'),
                  ref('Retained active-page check', supplier_contract,
                      'require(!view.active_page||pages.contains(*view.active_page),"Unknown active page");')]),
            node('tab-widget', 'JUMP', 'Then add the page widgets', 'Place them, then wire their events',
                 'Use Place a widget to set order, height, parent, and page. Use the widget/event/helper map for click behavior. '
                 'For each later tab, add its page entry and group/content declarations; reuse the shared switching and layout policy '
                 'introduced above unless its arrangement needs a new layout.',
                 'The tab path establishes navigation; each control still has a stable ID and its own behavior.', 0, 1,
                 [definition, route], link_map='widget-placement'),
        ], [
            edge('declare-pages', 'declare-page-content', 'page IDs'),
            edge('declare-page-content', 'copy-membership', 'explicit ownership'),
            edge('copy-membership', 'page-layout', 'matching roots'),
            edge('page-layout', 'page-switch', 'visible navigation'),
            edge('page-switch', 'reuse-tabs', 'publish'),
            edge('reuse-tabs', 'page-focus', 'presented selection'),
            edge('page-focus', 'tab-widget', 'extend content'),
        ])
    from parameter_guides import GUIDE_LINKS, make_parameter_guides
    from behavior_paths import make_behavior_maps
    guides = make_parameter_guides(ref)
    maps = [widget, placement, tabs, source, *make_behavior_maps(ref, node, edge, finish), runtime]
    for change_map in maps:
        for step in change_map['nodes']:
            step['parameter_guides'] = [guides[key] for key in
                                       GUIDE_LINKS.get((change_map['id'], step['id']), [])]
    return maps
