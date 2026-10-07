"""Concrete newcomer edit routes, with evidence supplied by the atlas resolver.

This module describes proposed edits. It neither opens nor modifies source files.
"""


def make_behavior_maps(ref, node, edge, finish):
    """Return five small edit maps using change_maps' shared helper schema."""
    app = 'gui/shared/application.cpp'
    declaration = 'gui/shared/application.hpp'
    core = 'src/store.cpp'
    header = 'include/foundation/store.hpp'
    task = 'gui/shared/task.hpp'
    contract = '@gui-boundary/include/gui/contract.hpp'

    def evidence(label, path, needle):
        return ref(label, path, needle)

    projection = evidence('Shared visible-state projection', app, 'void Application::publish() {')
    publication = evidence('Publication after event dispatch', app,
                           '        }, widget->input);\n    }\n    publish();')
    invalidation = evidence('Authoritative input epoch', app, 'void Application::advance_input_epoch() {')
    exception_status = evidence('Input error becomes shared status', app,
                                '    } catch (const std::invalid_argument& error) {')
    public_contract = evidence('Store input and mutation contract', header,
                               '// Text is 1..256 printable ASCII bytes; duplicates are allowed.')
    core_validation = evidence('Domain validation and exception translation', core,
                               'void Store::validate(std::string_view text) {')
    core_update = evidence('Existing update operation', core,
                           'bool Store::update(RecordId id, std::string_view text) {')
    update_declaration = evidence('Existing update declaration', header,
                                  '    bool update(RecordId id, std::string_view text);')
    activation = evidence('Existing button activation route', app,
                          'if (widget->target.id == "entries.add") append_entry();')
    button = evidence('Existing supported button declaration', 'gui/shared/view_definition.hpp',
                      'ViewDefinition{"entries.add", gui::Kind::button')
    helper = evidence('Existing shared application helper', app, 'void Application::append_entry() {')
    helper_declaration = evidence('Example application member declaration', declaration, '    void append_entry();')
    selection = evidence('List selection becomes shared state', app,
                         '} else if constexpr (std::is_same_v<T, gui::SelectRecord>) {')
    selected_id = evidence('Resolve selection using stable record IDs', app,
                           'if (list.selected == std::to_string(record.id)) entries_.erase(record.id);')
    selected_enabled = evidence('Existing selected-action enablement', app,
                                'if (remove_feature_) lookup(next, "entries.remove").state.enabled = list.selected.has_value();')
    source_location = evidence('Shared GUI compilation target', 'gui/CMakeLists.txt',
                               'add_library(foundation_gui_application STATIC shared/application.cpp ${foundation_task_executor})')
    service_complete = evidence('Shared service completion', app,
                                'bool Application::complete_service(gui::ServiceResult result) {')
    service_id = evidence('Reject unmatched service completions', app,
                          'if (!request || request->id != result.id) return false;')
    service_request = evidence('Shared service kind selection', app,
                               'request.kind = input.id == "heading" ? gui::ServiceKind::prompt :')
    service_limit = evidence('Current text-transfer bound', app,
                             'request.byte_limit = input.id == "heading" ? 80 : 65536;')

    validation = finish(
        'validation', 'Change record validation or a business rule',
        'Where do I change which records are accepted, and how do errors reach the user?',
        'Start with the rule owner. A domain rule belongs in Store; a changed private text format must remain consistent '
        'across Rust and C++ providers. Input limits are mirrored in several places. Follow conditional edits only when '
        'the rule changes that contract; preserve validation before mutation.',
        'Arrows show edit dependencies. Provider and limit steps are conditional, not runtime execution.',
        [
            node('rule-scope', 'DECISION', '1. Identify the rule owner', 'Domain rule or private text format?',
                 'For collection/domain meaning, edit Store validation or the owning core operation. For byte admissibility '
                 'or the private ABI length limit, follow the provider-contract steps as well.',
                 'CLI, GUI and import should receive the same rule through core; a UI-only filter would leave other callers different.',
                 0, 0, [core_validation, public_contract]),
            node('rule-contract', 'EDIT', '2. State the accepted input', 'store.hpp · public behavior',
                 'Update the public input/failure contract if it changes. Preserve stable IDs, caller-serialized access '
                 'and the guarantee that a failed operation leaves stored state unchanged.',
                 'A newcomer needs to know both what is accepted and what happens on rejection.',
                 1, 0, [public_contract]),
            node('rule-providers', 'EDIT', '3. Match both text providers', 'If the private format changes',
                 'Change the Rust validator and explicit C++ compatibility validator together. If adding a numeric status, '
                 'update the private C ABI declaration, Rust constants and C++ translation consistently.',
                 'Fresh configurations use Rust; selecting C++ must retain equivalent accepted input and status meaning.',
                 2, 0, [evidence('Rust pure validator', 'rust/text_validation/src/lib.rs',
                                'fn validate_text(bytes: &[u8]) -> u32 {'),
                        evidence('C++ compatibility validator', 'src/text_validation.cpp',
                                 'extern "C" uint32_t foundation_text_validate_v1'),
                        evidence('Private ABI numeric statuses', 'src/text_validation.h',
                                 'FOUNDATION_TEXT_INVALID_ASCII = 2,')]),
            node('rule-core', 'EDIT', '4. Apply rules before mutation', 'Store::validate · messages',
                 'Implement the domain rule or translate provider statuses into an appropriate public exception. '
                 'Keep validation before insertion/replacement, and update error text when its meaning changes.',
                 'Returning an old ASCII-only message for a different rule would mislead the caller.',
                 2, 1, [core_validation, evidence('Insertion validates first', core,
                                                'RecordId Store::add(std::string_view text) {'), core_update]),
            node('rule-bounds', 'EDIT', '5. Follow mirrored limits', 'Only if length/capacity changes',
                 'Review the public constants, private ABI/provider bounds, editor text policy and captured-task bounds. '
                 'Do not increase a public constant alone; preserve agreement among the relevant contracts.',
                 'The current private text ABI is bounded to 256 bytes, and tasks separately enforce 256-byte records.',
                 1, 1, [evidence('Public text bound', header, 'static constexpr std::size_t max_text_bytes = 256;'),
                        evidence('Editor policy uses the core bound', app,
                                 'get("entries.editor").spec.text_policy = {false, false, foundation::Store::max_text_bytes, gui::SubmitKey::enter};'),
                        evidence('Captured task input bound', task,
                                 'if (text.size() > 256) throw std::length_error("Task input exceeds text limit");')]),
            node('rule-consumers', 'REUSE', '6. Follow existing consumers', 'Core calls → shared error status',
                 'Reuse Store calls from CLI, GUI and import. Shared GUI code already catches invalid input and '
                 'projects its error status; inspect those paths to see the user-facing result of the changed rule.',
                 'The validation remains one reusable behavior rather than a separate rule per frontend.',
                 0, 1, [helper, exception_status, projection,
                        evidence('CLI validates all input before output', 'src/main.cpp',
                                 'for (int i = 2; i < argc; ++i) store.add(argv[i]);')]),
        ], [
            edge('rule-scope', 'rule-contract', 'public behavior'),
            edge('rule-contract', 'rule-providers', 'if private format changes', 'conditional'),
            edge('rule-providers', 'rule-core', 'shared statuses'),
            edge('rule-scope', 'rule-core', 'domain rule', 'conditional'),
            edge('rule-core', 'rule-bounds', 'if bounds change', 'conditional'),
            edge('rule-bounds', 'rule-consumers', 'same accepted input'),
            edge('rule-core', 'rule-consumers', 'existing bounds unchanged', 'conditional'),
        ])

    selected_entry = finish(
        'core-operation', 'Edit the selected entry',
        'How do I replace the selected record text while preserving its identity?',
        'Store::update already provides this core operation. Add shared UI intent and selection resolution, then reuse it. '
        'get/snapshot return copies; editing a copy does not change Store. Erase plus add would allocate a different ID. '
        'The proposed edit action and handler below do not already exist.',
        'Arrows show the editing sequence for a shared UI action. Existing core behavior is explicitly marked REUSE.',
        [
            node('edit-owner', 'DECISION', '1. Reuse the existing operation', 'Store::update preserves IDs',
                 'Use Store::update for replacement text on an existing record. Add a different core API only if the '
                 'required domain behavior cannot be expressed by the current contract.',
                 'The same API can serve a future CLI command; the current CLI has no edit command or persistent store.',
                 0, 0, [core_update, update_declaration,
                        evidence('CLI composition root', 'src/main.cpp', 'int run(int argc, const char* const* argv) {')]),
            node('edit-intent', 'NEW', '2. Add an Update action', 'Shared button/route/handler · proposed',
                 'Declare a supported button such as entries.update, add its target-ID Activate case, and declare '
                 'a proposed Application::edit_selected() member implemented in application.cpp. Reuse the current widget/edit pattern.',
                 'Widget identity and command meaning belong to shared Application. Existing application.cpp is already compiled.',
                 1, 0, [button, activation, helper_declaration, source_location], link_map='widget'),
            node('edit-selection', 'EDIT', '3. Resolve the selected ID', 'Selection string → stable RecordId',
                 'Read entries.list selected state and entries.editor text. If no selection exists, do not mutate. '
                 'Match the selected string against std::to_string(record.id) from authoritative Store records, following '
                 'the existing removal pattern, and retain the matching RecordId. Call advance_input_epoch() before accepted '
                 'semantic mutation; keep that increment even if later publication fails.',
                 'A selected string is an identity, not a vector index. Returned snapshots are owning copies.',
                 2, 0, [selection, selected_id, invalidation,
                        evidence('Editor text used by a shared action', app,
                                 'const auto& text = get("entries.editor").state.text;')]),
            node('edit-update', 'REUSE', '4. Call Store::update', 'ID + replacement text',
                 'Call entries_.update(resolved_id, replacement_text) from the new shared handler. '
                 'Keep the existing core implementation when its behavior fits the requirement.',
                 'update validates text first, returns false for a missing ID when the text is valid, and prepares a replacement '
                 'string before swapping it into place. The record ID stays unchanged.',
                 2, 1, [core_update, update_declaration]),
            node('edit-result', 'EDIT', '5. Handle rejected/missing input', 'Shared status and error state',
                 'Handle invalid_argument as user input rejection and a false return as a missing record. Set a useful '
                 'shared status; decide whether successful editing clears or retains editor text. Do not report a false return as success.',
                 'Invalid replacement text can throw before missing-ID lookup, so both outcomes need explicit handling.',
                 1, 1, [exception_status, helper, core_update]),
            node('edit-view', 'EDIT', '6. Project updated text and availability', 'publish · selection + enabled state',
                 'Add Update enabled-state logic based on valid selection and the intended edit policy. Reuse publish to rebuild '
                 'rows from Store and retain/clear selection consistently. The existing handle publishes after dispatch returns.',
                 'UI text becomes visible through the shared snapshot; core mutation alone does not define action availability.',
                 0, 1, [projection, selected_enabled, publication]),
        ], [
            edge('edit-owner', 'edit-intent', 'shared UI intent'),
            edge('edit-intent', 'edit-selection', 'current selected record'),
            edge('edit-selection', 'edit-update', 'stable ID + text'),
            edge('edit-update', 'edit-result', 'success / false / exception'),
            edge('edit-result', 'edit-view', 'shared visible state'),
        ])

    commands = finish(
        'commands', 'Add a menu command or keyboard shortcut',
        'How do I add an action to the menu and reuse its behavior from a shortcut?',
        'Add shared command intent and route it to one helper. Menu options arrive as ChooseOption; shortcuts are normalized '
        'into Activate on a current button. The pinned shortcut keys are Escape, Enter and F1–F12 with modifier flags. '
        'A proposed command/helper does not already exist.',
        'Arrows show shared edits; shortcut-related steps are conditional. Existing normalization is reused.',
        [
            node('command-option', 'EDIT', '1. Declare the menu option', 'Stable option ID + label',
                 'Append an option to entries.options in the Application constructor, using a distinct command ID '
                 'and the desired label. Keep availability derived from shared state when it changes over time.',
                 'Options declare user intent; generic renderers do not implement product command meaning.',
                 0, 0, [evidence('Existing menu options', app,
                                'get("entries.options").state.options = {{"clear", "Clear entries", "", true},')]),
            node('command-helper', 'NEW', '2. Implement one command helper', 'Application member · proposed',
                 'Declare and implement a proposed shared helper for the command. Put reusable record/domain behavior '
                 'in core and call it from the helper; keep status and menu meaning in Application. Call '
                 'advance_input_epoch() before accepted semantic mutation, preserving the increment if publication fails.',
                 'A menu action and a button/shortcut can call the same helper.',
                 1, 0, [helper_declaration, helper, invalidation], link_map='widget'),
            node('command-route', 'EDIT', '3. Route ChooseOption', 'Option ID → shared helper',
                 'Add an input.id case in the ChooseOption branch and call the helper. For another menu, use '
                 'unambiguous command IDs or explicitly check widget->target.id before interpreting its options.',
                 'The current menu dispatch checks option IDs alone; repeated IDs in different menus could otherwise share unintended meaning.',
                 2, 0, [evidence('Menu input route', app,
                                '} else if constexpr (std::is_same_v<T, gui::ChooseOption>) {'),
                        evidence('Existing clear command', app, 'if (input.id == "clear") {')]),
            node('command-button', 'EDIT', '4. Route a current button', 'Only if adding a shortcut',
                 'Provide a current button for the action, and route its target-ID Activate case to the same helper. '
                 'Preserve enabled/visible state so shortcut eligibility matches the action.',
                 'The retained contract requires every shortcut to target a current button, not a menu option ID.',
                 2, 1, [activation, button,
                        evidence('Shortcut target constraint', contract, '"Shortcut must target a current button"')]),
            node('command-binding', 'EDIT', '5. Declare a supported key binding', 'Only if adding a shortcut',
                 'Initialize view_.key_bindings with a supported ShortcutKey, the current button WidgetKey and '
                 'control/shift/alt flags. Use a unique key/modifier combination; arbitrary letter keys are not in this pinned vocabulary.',
                 'A shortcut is declared in the shared Snapshot, independent of a native toolkit callback.',
                 1, 1, [evidence('Retained key-binding fields', contract, 'struct KeyBinding {'),
                        evidence('Supported shortcut keys', contract,
                                 'enum class ShortcutKey { escape,enter,f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12 };')]),
            node('command-project', 'REUSE', '6. Normalize and project state', 'Activate reuse + shared status',
                 'Reuse normalize_event: it maps a matched ShortcutEvent to the button Activate path. Keep '
                 'normalization before command dispatch, and update publish if the command changes status or availability.',
                 'Menu, button and shortcut behavior can converge on the same shared action, with normal stale/disabled input rejection.',
                 0, 1, [evidence('Shortcut normalization', contract, 'event=WidgetEvent{*target,Activate{}};'),
                        evidence('Application normalizes first', app,
                                 'if (!gui::normalize_event(view_, event, [this](const gui::WidgetKey& key) {'),
                        projection]),
        ], [
            edge('command-option', 'command-helper', 'one implementation'),
            edge('command-helper', 'command-route', 'menu calls helper'),
            edge('command-route', 'command-button', 'if shortcut requested', 'conditional'),
            edge('command-button', 'command-binding', 'current target'),
            edge('command-binding', 'command-project', 'normalized Activate'),
            edge('command-route', 'command-project', 'menu result'),
        ])

    background = finish(
        'background-task', 'Change background work, cancel and progress',
        'Where do I change the work and its displayed result while retaining cancellation and responsiveness?',
        'The current task counts non-space bytes from captured record text. Computation is owned/value-only; '
        'native and cooperative schedulers reuse it. If result semantics change, review completion guards that '
        'currently require result <= processed and complete == (processed == total).',
        'Arrows show edit dependencies across algorithm, input, completion and shared lifecycle; these are not thread-execution arrows.',
        [
            node('task-result', 'DECISION', '1. Define the result/progress contract', 'Keep or change TaskUpdate?',
                 'Keep the current processed/total/result counters if the new work has the same meaning. If changing '
                 'the value shape or invariants, update TaskUpdate and every consumer consistently.',
                 'The current completion validator encodes counting semantics; a different numeric result may legitimately exceed processed.',
                 0, 0, [evidence('Owned progress fields', task, 'struct TaskUpdate {'),
                        evidence('Completion validation', app,
                                 'bool Application::complete_task(const TaskUpdate& update) {')]),
            node('task-work', 'EDIT', '2. Change bounded computation', 'TextTask::advance',
                 'Modify the work in TextTask while preserving owned input, bounded work per advance call and '
                 'cancellation/shutdown behavior. Update totals when the work unit changes.',
                 'The existing result increments for non-space bytes; changing only the UI label does not change the computation.',
                 1, 0, [evidence('Bounded task step', task,
                                'std::optional<TaskUpdate> advance(std::size_t budget = 256) {'),
                        evidence('Current non-space computation', task, "update_.result += text[offset_++] != ' ';")]),
            node('task-start', 'EDIT', '3. Capture inputs and route start/cancel', 'Application activation branches',
                 'Adapt the shared Start branch if input capture changes. Copy authoritative record text into owned '
                 'task input, start through TaskExecutor, and keep cancellation through the existing Cancel branch.',
                 'Later edits to live records must not mutate already captured work, and workers must not retain Application or adapter references.',
                 2, 0, [evidence('Start dispatch', app, 'else if (widget->target.id == "entries.task.start") {'),
                        evidence('Owned task start', app, 'task_progress_ = task_->start(std::move(input));'),
                        evidence('Cancel dispatch', app,
                                 'task_->cancel(); task_running_ = false; task_status_ = "Task cancelled";')]),
            node('task-schedule', 'REUSE', '4. Reuse scheduling and tick delivery', 'TaskExecutor · native/cooperative',
                 'Retain the value-oriented TaskExecutor boundary for ordinary algorithm changes. Existing ticks '
                 'advance/poll work and deliver updates on the shared application side.',
                 'Scheduling is selected once for the platform; task logic does not need a separate implementation in each GUI renderer.',
                 2, 1, [evidence('Executor interface', task, 'class TaskExecutor {'),
                        evidence('Tick delivers progress', app,
                                 'if (const auto update = task_->advance()) complete_task(*update);')]),
            node('task-completion', 'EDIT', '5. Interpret completion honestly', 'Guard values + result text',
                 'Update result/progress text in complete_task. Review changed result invariants while retaining '
                 'generation matching, stale/cancelled completion rejection and monotonic progress where required.',
                 'Current guards reject result > processed, and require complete to mean processed == total; keep or deliberately revise these with the contract.',
                 1, 1, [evidence('Shared task completion', app,
                                'bool Application::complete_task(const TaskUpdate& update) {'),
                        evidence('Current counter-result guard', app, 'update.processed > update.total || update.result > update.processed ||')]),
            node('task-lifecycle', 'REUSE', '6. Project controls and close owned work', 'publish + shutdown',
                 'Reuse shared Start/Cancel enabled states and progress projection; edit them if the new task policy '
                 'changes. Preserve shutdown of the executor before application state destruction.',
                 'Responsiveness includes cancellation, late update rejection and complete owned-work cleanup, not just showing progress.',
                 0, 1, [evidence('Start availability', app, 'lookup(next, "entries.task.start").state.enabled = !task_running_;'),
                        evidence('Cancel availability', app, 'lookup(next, "entries.task.cancel").state.enabled = task_running_;'),
                        evidence('Owned task/service shutdown', app,
                                 'task_->shutdown(); task_running_ = false; services_.shutdown();')]),
        ], [
            edge('task-result', 'task-work', 'meaning + work units'),
            edge('task-work', 'task-start', 'owned inputs'),
            edge('task-start', 'task-schedule', 'executor interface'),
            edge('task-schedule', 'task-completion', 'value-only progress'),
            edge('task-completion', 'task-lifecycle', 'visible result + close'),
        ])

    transfer = finish(
        'import-export', 'Change import/export content format',
        'Where do I change record serialization without duplicating file transport across hosts?',
        'The current format is one text record per line, with CR stripped on import. Shared code owns format and '
        'record meaning; generic hosts transfer bytes. Import stages a replacement Store before commit. '
        'Export reports handoff to the host, which is not a promise of durable storage.',
        'Arrows show paired serializer/parser edits, then shared bounds, transport reuse and honest completion status.',
        [
            node('format-owner', 'DECISION', '1. Separate content from transport', 'Record format belongs to shared/core code',
                 'Define the desired record representation and malformed-input policy. Keep format interpretation '
                 'in shared/core code; leave paths, browser file selection and byte movement in generic services.',
                 'Changing a content format does not require copying application meaning into every backend.',
                 0, 0, [service_request, service_complete, public_contract]),
            node('format-export', 'EDIT', '2. Change export serialization', 'Shared request.value',
                 'Replace the current record-text-plus-newline serialization in the export command branch. '
                 'Check the complete serialized byte count against the service request bound before enqueueing.',
                 'The serialized representation, not merely the number of records, determines transfer size.',
                 1, 0, [evidence('Current line serialization', app,
                                'for (const auto& record : entries_.snapshot()) request.value += record.text + "\\n";'),
                        evidence('Serialized size check', app, 'if (request.value.size() > request.byte_limit) {')]),
            node('format-import', 'EDIT', '3. Parse into a replacement Store', 'All records before commit',
                 'Replace line parsing in complete_service with the matching parser. Populate a temporary copy '
                 'through core record operations, then commit only after every record succeeds. Preserve monotonic IDs '
                 'and clear obsolete selection on successful replacement.',
                 'Mutating the live Store while parsing would expose a partial import on rejection.',
                 2, 0, [evidence('Atomic import preparation', app,
                                'auto replacement = entries_; // Commit all records together; preserve ID monotonicity.'),
                        evidence('Current newline parser', app, "const auto end = result.value.find('\\n', begin);"),
                        evidence('Import commit', app, 'entries_ = std::move(replacement);')]),
            node('format-freshness', 'REUSE', '4. Preserve bounds and freshness', 'Service ID + input epoch + result validation',
                 'Retain request limits, pending-service identity checks and shutdown/cancellation/error paths. '
                 'Keep authoritative input-epoch invalidation around request/completion changes so stale inputs cannot '
                 'apply against changed meaning. A deliberately different size bound is a contract change.',
                 'A format parser alone does not authorize an unmatched service result or stale input.',
                 2, 1, [service_limit, service_id, invalidation,
                        evidence('Service queue validates completion', app, 'if (!services_.complete(result)) return false;')]),
            node('format-transport', 'REUSE', '5. Reuse native/browser byte transport', 'read_text / write_text',
                 'Keep existing read_text/write_text capabilities for valid UTF-8 text formats within the 64 KiB '
                 'transfer ceiling. Arbitrary binary data requires a different capability or text encoding within that bound. '
                 'Inspect generic transfer behavior; do not move record parsing into the host.',
                 'Native and browser hosts own their file-selection/transfer authority while the application owns content meaning.',
                 1, 1, [service_request, evidence('Native generic byte transfer', 'gui/host/file_services.hpp',
                                                'inline gui::ServiceResult transfer(const gui::ServiceRequest& request,'),
                        evidence('Strict browser UTF-8 decoding', 'gui/host/file_services.mjs',
                                 "return new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes);"),
                        evidence('Native transport ceiling', 'gui/host/file_services.hpp',
                                 'if (request.byte_limit > 65536 || request.value.size() > request.byte_limit)')]),
            node('format-status', 'EDIT', '6. Project honest completion state', 'Import success/errors · export handoff',
                 'Set shared import/parse/error status and project the committed rows. Keep export wording honest: '
                 'the existing completion says Export handed to host, not that data is durably saved. Preserve cancelled '
                 'and transport-error outcomes.',
                 'The visible result must distinguish a successfully parsed replacement, rejected content and host handoff.',
                 0, 1, [service_complete, projection,
                        evidence('Honest export completion', app,
                                 'else if (request->kind == gui::ServiceKind::write_text) status_ = "Export handed to host";')]),
        ], [
            edge('format-owner', 'format-export', 'output representation'),
            edge('format-export', 'format-import', 'matching input representation'),
            edge('format-import', 'format-freshness', 'atomic accepted completion'),
            edge('format-freshness', 'format-transport', 'bounded owned bytes'),
            edge('format-transport', 'format-status', 'completion meaning'),
        ])

    return [validation, selected_entry, commands, background, transfer]
