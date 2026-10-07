"""Curated literal-code diagrams below the four runtime overview scenarios.

All displayed code is resolved by the caller from captured source. The strings
below are exact source anchors, never replacement code or executed examples.
"""
from __future__ import annotations


def make_runtime_code_maps(code, edge, diagram):
    app = 'gui/shared/application.cpp'
    session = 'gui/host/contract.hpp'
    fltk = 'gui/hosts/fltk_main.cpp'
    definitions = 'gui/shared/view_definition.hpp'
    core = 'src/store.cpp'
    cpp = 'src/text_validation.cpp'
    rust = 'rust/text_validation/src/lib.rs'
    files = 'gui/host/file_services.hpp'
    positions = ((0, 0), (1, 0), (1, 1), (0, 1), (0, 2), (1, 2))

    def c(index, id, title, path, fragment, *, child=None, note='', emphasis='primary', role='CODE'):
        column, row = positions[index]
        return code(id, title, path, fragment, column=column, row=row,
                    child=child, note=note, emphasis=emphasis, role=role)

    def link(map, node=None):
        return {'map': map, **({'node': node} if node else {})}

    def d(id, title, summary, nodes, edges, *, scope='Shared application behavior'):
        return diagram(id, title, summary, nodes, edges, scope=scope, category='runtime')

    maps = []
    maps.append(d('main-to-widgets', 'main to the declared widgets: calls and the data they consume',
        'Normal native startup reaches the shared Application constructor, which loops over view_definition '
        'and calls add for each eligible row to create shared Snapshot widgets. The editor/Add declarations '
        'feed that loop as data; they are not calls. Layout and adapter presentation happen later in publish.', [
            c(0, 'entry', 'main → run_fltk<Application>', fltk,
              'int main(int argc, char** argv) { return foundation::host::run_fltk<foundation::ui::Application>(argc, argv); }',
              child=link('gui-startup', 'session'), role='CALL'),
            c(1, 'session', 'Session constructor → Application', session,
              '    Session() : adapter([this](const gui::Event& event) {\n'
              '        if (current_) { current_->handle(event); services(); }\n'
              '    }), application(adapter) { current_ = &application; }',
              child=link('application-ownership', 'construct'), role='CALL',
              note='The runner creates NativeSession, a Session alias. The callback body runs later; application(adapter) constructs the shared Application now.'),
            c(2, 'application', 'Enter Application constructor', app,
              'Application::Application(gui::Adapter& adapter, std::unique_ptr<TaskExecutor> executor)\n'
              '    : adapter_(adapter), task_(std::move(executor)) {', child=link('application-init', 'enter')),
            c(3, 'definitions', 'view_definition: editor and Add rows', definitions,
              '    ViewDefinition{"entries.editor", gui::Kind::text, 32, "", "New entry", "Type an entry"},\n'
              '    ViewDefinition{"entries.add", gui::Kind::button, 32, "", "Add entry", ""},',
              child=link('widget-definitions', 'controls'), role='DATA',
              note='These constexpr aggregate values are declarations. The same table supplies creation order and later layout policy.'),
            c(4, 'loop', 'Creation loop → add(definition)', app,
              '    for (const auto& definition : view_definition)\n'
              '        if (!definition.remove_extension) add(definition);',
              child=link('widget-definitions', 'loop'), role='CALL',
              note='Only rows with remove_extension == false are created here. Its declared default is false; the optional Remove row sets it true.'),
            c(5, 'add', 'Application::add creates one widget', app,
              'gui::Widget& Application::add(const ViewDefinition& definition) {\n'
              '    gui::Widget widget;\n'
              '    widget.spec.key.id = definition.id;\n'
              '    widget.spec.kind = definition.kind;\n'
              '    if (definition.id != view_definition.front().id) widget.spec.parent = view_definition.front().id;',
              child=link('widget-create', 'identity'),
              note='The remainder copies strings/font/wrapping, appends to the shared view_ Snapshot, and returns the widget. Height is consumed later by publish/layout; add creates no native control.'),
        ], [edge('entry', 'session', 'run_fltk runner creates NativeSession; Session constructor', 'call'),
            edge('session', 'application', 'application(adapter)', 'call'),
            edge('application', 'loop', 'constructor body; executor check and title set'),
            edge('definitions', 'loop', 'view_definition supplies declaration rows', 'dependency'),
            edge('loop', 'add', 'eligible row: add(definition)', 'call'),
            edge('add', 'loop', 'add returns; next declaration row', 'return')],
        scope='Primary native startup to shared Snapshot widget creation'))

    maps.append(d('widget-definitions', 'Widget declaration table: fields, rows and their consumer',
        'Representative literal rows from the application-owned table. Aggregate field order and defaults '
        'expand from the first card. Data arrows feed the actual constructor loop; only its add arrow is a call. '
        'The constructor excludes the optional Remove row.', [
            c(0, 'fields', 'ViewDefinition aggregate field order', definitions,
              '    std::string_view id;\n'
              '    gui::Kind kind;\n'
              '    double height;\n'
              '    std::string_view text, label, placeholder;',
              child=link('widget-definition-fields', 'identity'), role='DATA',
              note='Following fields declare bold=false, wrap=none and remove_extension=false. Expand for their exact declarations.'),
            c(1, 'root', 'First row declares the parent group', definitions,
              'inline constexpr std::array view_definition{\n'
              '    ViewDefinition{"entries.form", gui::Kind::group, 0, "", "", ""},', role='DATA',
              note='add compares each ID with view_definition.front().id; the first root gets no parent assignment.'),
            c(2, 'controls', 'Editor and Add declaration values', definitions,
              '    ViewDefinition{"entries.editor", gui::Kind::text, 32, "", "New entry", "Type an entry"},\n'
              '    ViewDefinition{"entries.add", gui::Kind::button, 32, "", "Add entry", ""},', role='DATA',
              note='Other ordinary rows are omitted here. Their table order is preserved by the creation loop.'),
            c(3, 'remove', 'Optional Remove row sets the final flag', definitions,
              '    ViewDefinition{"entries.remove", gui::Kind::button, 32, "", "Remove selected", "", false, gui::TextWrap::none, true}',
              role='DATA', emphasis='supporting',
              note='The final true initializes remove_extension. This row is skipped during default constructor creation.'),
            c(4, 'loop', 'Constructor iterates the declaration table', app,
              '    for (const auto& definition : view_definition)\n'
              '        if (!definition.remove_extension) add(definition);', role='CALL'),
            c(5, 'add', 'add copies identity and chooses the default parent', app,
              'gui::Widget& Application::add(const ViewDefinition& definition) {\n'
              '    gui::Widget widget;\n'
              '    widget.spec.key.id = definition.id;\n'
              '    widget.spec.kind = definition.kind;\n'
              '    if (definition.id != view_definition.front().id) widget.spec.parent = view_definition.front().id;',
              child=link('widget-create', 'identity'),
              note='Non-root IDs receive the first row as parent. Height is used later by publish/layout; the loop already filtered remove_extension.'),
        ], [edge('fields', 'root', 'aggregate field order determines row meanings', 'dependency'),
            edge('fields', 'controls', 'same fields and declared defaults', 'dependency'),
            edge('fields', 'remove', 'final field is remove_extension', 'dependency', emphasis='supporting'),
            edge('root', 'loop', 'table starts with the root group', 'dependency'),
            edge('controls', 'loop', 'ordinary rows consumed in table order', 'dependency'),
            edge('remove', 'loop', 'declared row; true flag excludes it', 'dependency', emphasis='supporting'),
            edge('loop', 'add', 'remove_extension is false: add(definition)', 'call'),
            edge('add', 'loop', 'return; continue iteration', 'return')],
        scope='Declaration data and constructor consumer'))

    maps.append(d('widget-definition-fields', 'ViewDefinition: literal types and declared defaults',
        'Field declarations in aggregate order. Dependency arrows show declaration order, not execution. '
        'The editor/Add rows supply the first six fields and use the trailing declared defaults. '
        'Other rows can override those defaults, as the optional Remove row does.', [
            c(0, 'identity', 'Identity, widget kind and layout height', definitions,
              'struct ViewDefinition {\n'
              '    std::string_view id;\n'
              '    gui::Kind kind;\n'
              '    double height;', role='DATA'),
            c(1, 'strings', 'Text, label and placeholder', definitions,
              '    std::string_view text, label, placeholder;', role='DATA'),
            c(2, 'presentation', 'Default font weight and wrapping', definitions,
              '    bool bold = false;\n'
              '    gui::TextWrap wrap = gui::TextWrap::none;', role='DATA'),
            c(3, 'optional', 'Default creation flag', definitions,
              '    bool remove_extension = false;', role='DATA',
              note='The constructor creates false rows. The optional Remove declaration explicitly overrides this default with true.'),
        ], [edge('identity', 'strings', 'following aggregate members', 'dependency'),
            edge('strings', 'presentation', 'following aggregate members / defaults', 'dependency'),
            edge('presentation', 'optional', 'final aggregate member / default', 'dependency')],
        scope='Application-owned declaration types and defaults'))

    maps.append(d('gui-startup', 'Native GUI startup: real entry and host calls',
        'Normal FLTK launch, excluding the qualification branch. Expand construction for shared behavior. '
        'Window waiting and timer callbacks are supporting host infrastructure.', [
            c(0, 'entry', 'Executable entry', fltk,
              'int main(int argc, char** argv) { return foundation::host::run_fltk<foundation::ui::Application>(argc, argv); }'),
            c(1, 'session', 'Runner constructs its session', fltk,
              '        NativeSession<App, gui::fltk::Adapter> session;',
              note='Argument checks run before this statement; the smoke branch is outside this normal-launch diagram.'),
            c(2, 'construct', 'Session constructs callback and Application', session,
              '    Session() : adapter([this](const gui::Event& event) {\n'
              '        if (current_) { current_->handle(event); services(); }\n'
              '    }), application(adapter) { current_ = &application; }',
              child=link('application-init', 'enter'),
              note='The callback body runs on later input. application(adapter) constructs the shared App; current_ is assigned afterward.'),
            c(3, 'show', 'Show and schedule', fltk,
              '        session.adapter.show(); Fl::add_timeout(0, Timer::tick, &timer);', emphasis='supporting'),
            c(4, 'loop', 'Native wait loop', fltk,
              '        while (!session.adapter.closed()) Fl::wait(.02);', emphasis='supporting'),
            c(5, 'tick', 'Timer calls the session', fltk,
              '                    if (self.owner.adapter.closed()) return;\n'
              '                    self.owner.tick(); Fl::repeat_timeout(.02, tick, data);',
              child=link('service-pump', 'poll'), emphasis='supporting',
              note='Session::tick first advances Application work, then optional adapter sync, then services. Closing/error cleanup is outside this excerpt.'),
        ], [edge('entry', 'session', 'run_fltk; argument checks passed', 'call'),
            edge('session', 'construct', 'NativeSession aliases Session', 'call'),
            edge('construct', 'show', 'construction/publish returned; normal branch', 'return'),
            edge('show', 'loop', 'wait for input', 'step', emphasis='supporting'),
            edge('loop', 'tick', 'scheduled callback', 'event', emphasis='supporting'),
            edge('tick', 'loop', 'return / reschedule', 'return', emphasis='supporting')],
        scope='Native composition; supporting host infrastructure'))

    maps.append(d('application-ownership', 'Object relationships: Session, Application and Store',
        'These are declaration relationships, not runtime call arrows. Session contains its adapter and '
        'Application. Application borrows the adapter by reference, owns a Snapshot and owns its Store; '
        'the constructor body expands separately.', [
            c(0, 'alias', 'NativeSession is a typed Session alias', 'gui/host/native_session.hpp',
              'template<Application App, class Adapter> using NativeSession = Session<App, Adapter, FileServices>;', emphasis='supporting'),
            c(1, 'session-members', 'Session contains adapter and application', session,
              '    Adapter adapter;\n'
              '    App application;', emphasis='supporting'),
            c(2, 'construct', 'Session supplies adapter to Application', session,
              '    Session() : adapter([this](const gui::Event& event) {\n'
              '        if (current_) { current_->handle(event); services(); }\n'
              '    }), application(adapter) { current_ = &application; }', child=link('application-init', 'enter')),
            c(3, 'view', 'Application borrows adapter and owns view', 'gui/shared/application.hpp',
              '    gui::Adapter& adapter_;\n'
              '    gui::Snapshot view_;'),
            c(4, 'store', 'Application owns a bounded Store', 'gui/shared/application.hpp',
              '    static constexpr std::size_t entry_limit_ = 1000;\n'
              '    foundation::Store entries_{entry_limit_};',
              note='The Store member is constructed before the Application constructor body; 1000 is the current application capacity.'),
            c(5, 'records', 'Store owns records and next identity', 'include/foundation/store.hpp',
              '    std::size_t capacity_;\n'
              '    RecordId next_id_ = 1;\n'
              '    std::vector<Record> records_;'),
        ], [edge('alias', 'session-members', 'typed alias instantiates Session', 'dependency', emphasis='supporting'),
            edge('session-members', 'construct', 'members initialized by this constructor', 'dependency'),
            edge('construct', 'view', 'adapter passed by reference', 'dependency'),
            edge('construct', 'store', 'Application contains Store member', 'dependency'),
            edge('store', 'records', 'Store owns value records / monotonic ID', 'dependency')],
        scope='Object ownership and declaration relationships'))

    maps.append(d('application-init', 'Application constructor: declarations to first publish',
        'Existing constructor statements. The default executor argument is evaluated before entry; this diagram '
        'begins with the received executor. Widget creation and publication expand below.', [
            c(0, 'enter', 'Bind supplied state', app,
              'Application::Application(gui::Adapter& adapter, std::unique_ptr<TaskExecutor> executor)\n'
              '    : adapter_(adapter), task_(std::move(executor)) {'),
            c(1, 'initial', 'Require executor and set title', app,
              '    if (!task_) throw std::invalid_argument("Task executor is required");\n'
              '    view_.title = "Entry list";'),
            c(2, 'rows', 'Create eligible declaration rows', app,
              '    for (const auto& definition : view_definition)\n'
              '        if (!definition.remove_extension) add(definition);', child=link('widget-definitions', 'loop')),
            c(3, 'editor', 'Configure editor input', app,
              '    get("entries.editor").spec.text_policy = {false, false, foundation::Store::max_text_bytes, gui::SubmitKey::enter};'),
            c(4, 'options', 'Declare menu options', app,
              '    get("entries.options").state.options = {{"clear", "Clear entries", "", true},\n'
              '                                           {"heading", "Change heading", "", true},\n'
              '                                           {"import", "Import entries", "", true},\n'
              '                                           {"export", "Export entries", "", true}};'),
            c(5, 'publish', 'Configure list and publish', app,
              '    auto& entries = get("entries.list");\n'
              '    entries.spec.row_height = 32;\n'
              '    entries.spec.follow_tail = true;\n'
              '    publish();', child=link('publish-view', 'stage')),
        ], [edge('enter', 'initial', 'constructor body'),
            edge('initial', 'rows', 'executor present', 'conditional'),
            edge('rows', 'editor', 'creation loop completed'),
            edge('editor', 'options', 'next statements'),
            edge('options', 'publish', 'list setup; next publish call', 'step')]))

    maps.append(d('widget-create', 'Application::add: create one declared widget',
        'Called once per eligible row. The parent condition applies to every row except the current first root. '
        'Return resumes the constructor or optional-feature creation loop.', [
            c(0, 'identity', 'Create widget and identity', app,
              '    gui::Widget widget;\n'
              '    widget.spec.key.id = definition.id;\n'
              '    widget.spec.kind = definition.kind;'),
            c(1, 'parent', 'Assign the current root parent', app,
              '    if (definition.id != view_definition.front().id) widget.spec.parent = view_definition.front().id;'),
            c(2, 'text', 'Copy presentation strings', app,
              '    widget.state.text = definition.text;\n'
              '    widget.state.label = definition.label;\n'
              '    widget.state.placeholder = definition.placeholder;'),
            c(3, 'font', 'Copy font and wrapping', app,
              '    widget.state.font.bold = definition.bold;\n'
              '    widget.state.wrap = definition.wrap;'),
            c(4, 'append', 'Append owned widget', app,
              '    view_.widgets.push_back(std::move(widget));'),
            c(5, 'return', 'Return the created widget', app,
              '    return view_.widgets.back();'),
        ], [edge('identity', 'parent', 'next statement'),
            edge('parent', 'text', 'after condition; root skips assignment'),
            edge('text', 'font', 'next statements'),
            edge('font', 'append', 'append'), edge('append', 'return', 'insertion succeeded')]))

    maps.append(d('event-dispatch', 'Add-button dispatch: callback to helper and publication',
        'Selected WidgetEvent/Activate path. Close, resize, other inputs and other target IDs have their own '
        'branches in the full handler. Rejected normalization returns before publication.', [
            c(0, 'bridge', 'Native callback calls Application', session,
              '        if (current_) { current_->handle(event); services(); }',
              note='services() runs after handle returns. Browser forwarding uses Browser<App> instead of this Session callback.'),
            c(1, 'closed', 'Reject closed adapter', app, '    if (adapter_.closed()) return;', emphasis='supporting'),
            c(2, 'normalize', 'Normalize current input', app,
              '    if (!gui::normalize_event(view_, event, [this](const gui::WidgetKey& key) {\n'
              '            return adapter_.scroll_offset(key);\n'
              '        })) return;',
              note='The close-event and shutdown branches precede this fragment. Scroll lookup is a callback used by normalization.'),
            c(3, 'widget', 'Enter the widget visitor', app,
              '    } else if (const auto* widget = std::get_if<gui::WidgetEvent>(&event)) {\n'
              '        auto& current = get(widget->target.id);\n'
              '        std::visit([&](const auto& input) {'),
            c(4, 'activation', 'Route the Add target', app,
              '            } else if constexpr (std::is_same_v<T, gui::Activate>) {\n'
              '                if (widget->target.id == "entries.add") append_entry();', child=link('append-entry', 'epoch')),
            c(5, 'publish', 'Publish after normal visitor return', app,
              '        }, widget->input);\n'
              '    }\n'
              '    publish();', child=link('publish-view', 'stage')),
        ], [edge('bridge', 'closed', 'handle(event)', 'call'),
            edge('closed', 'normalize', 'open; close/shutdown checks passed', 'conditional'),
            edge('normalize', 'widget', 'accepted WidgetEvent', 'conditional'),
            edge('widget', 'activation', 'visitor selects Activate; Add ID', 'conditional'),
            edge('activation', 'publish', 'append_entry and visitor return normally', 'return')]))

    maps.append(d('append-entry', 'append_entry: epoch, core call, success or caught error',
        'The semantic epoch advances before mutation and outside the try block. Caught invalid_argument and '
        'length_error return to handle; other exceptions can escape and skip its publication.', [
            c(0, 'epoch', 'Advance epoch and read editor', app,
              '    advance_input_epoch();\n'
              '    const auto& text = get("entries.editor").state.text;'),
            c(1, 'core', 'Call the domain operation', app,
              '    try {\n'
              '        // Core owns collection validation, capacity, identity and mutation.\n'
              '        entries_.add(text);', child=link('core-add', 'validate')),
            c(2, 'success', 'Successful input clears editor', app,
              '        get("entries.editor").state.text.clear();\n'
              '        status_ = "Entry added";\n'
              '        status_error_ = false;'),
            c(3, 'invalid', 'Caught input rejection', app,
              '    } catch (const std::invalid_argument& error) {\n'
              '        status_ = error.what();\n'
              '        status_error_ = true;', emphasis='supporting'),
            c(4, 'full', 'Caught capacity failure', app,
              '    } catch (const std::length_error& error) {\n'
              '        status_ = error.what();\n'
              '        status_error_ = true;', emphasis='supporting'),
            c(5, 'epoch-body', 'Epoch helper rejects exhaustion first', app,
              '    if (input_epoch_ == std::numeric_limits<std::uint64_t>::max()) {\n'
              '        throw std::overflow_error("Input epoch exhausted");\n'
              '    }\n'
              '    ++input_epoch_;', emphasis='supporting',
              note='Called by the first block; the overflow exception is outside append_entry\'s catches.'),
        ], [edge('epoch', 'epoch-body', 'advance_input_epoch()', 'call', emphasis='supporting'),
            edge('epoch-body', 'core', 'epoch advanced; editor read', 'return'),
            edge('core', 'success', 'Store::add returns', 'return'),
            edge('core', 'invalid', 'throws invalid_argument', 'return', emphasis='supporting'),
            edge('core', 'full', 'throws length_error', 'return', emphasis='supporting')]))

    maps.append(d('core-add', 'Store::add: validate, capacity, identity, insertion',
        'Failed validation, capacity, identity or allocation exits before ID advancement. Throw statements '
        'inside guard boxes are terminal exits; arrows show the accepted path.', [
            c(0, 'validate', 'Validate before mutation', core,
              'RecordId Store::add(std::string_view text) {\n'
              '    validate(text);', child=link('core-validation', 'enter')),
            c(1, 'capacity', 'Check collection capacity', core,
              '    if (records_.size() == capacity_) {\n'
              '        throw std::length_error("collection is full");\n'
              '    }'),
            c(2, 'identity', 'Check identifier availability', core,
              '    if (next_id_ == std::numeric_limits<RecordId>::max()) {\n'
              '        throw std::overflow_error("record identifiers exhausted");\n'
              '    }'),
            c(3, 'insert', 'Insert an owned record', core,
              '    const auto id = next_id_;\n'
              '    records_.push_back({id, std::string(text)});'),
            c(4, 'advance', 'Advance ID after insertion', core, '    ++next_id_;'),
            c(5, 'return', 'Return stable identity', core, '    return id;'),
        ], [edge('validate', 'capacity', 'validation returns', 'return'),
            edge('capacity', 'identity', 'not full', 'conditional'),
            edge('identity', 'insert', 'ID available', 'conditional'),
            edge('insert', 'advance', 'insertion succeeded'), edge('advance', 'return', 'return to caller')],
        scope='Reusable domain behavior'))

    maps.append(d('core-validation', 'Store::validate: ABI status to C++ contract',
        'The assertion is compile-time context. Runtime calls the selected provider bridge, then chooses '
        'one switch case. Invalid-pointer or unknown status reaches default, rather than ordinary input rejection.', [
            c(0, 'enter', 'Declaration and compile-time bound', core,
              'void Store::validate(std::string_view text) {\n'
              '    static_assert(max_text_bytes == 256, "private text ABI length limit changed");',
              note='static_assert is not an executing runtime branch.'),
            c(1, 'status', 'Call private validation and switch on status', core,
              '    const auto status = detail::validate_text(\n'
              '        reinterpret_cast<const std::uint8_t*>(text.data()), text.size());\n'
              '    switch (status) {', child=link('cpp-provider', 'bridge')),
            c(2, 'ok', 'Valid input returns', core,
              '    case FOUNDATION_TEXT_OK:\n'
              '        return;'),
            c(3, 'length', 'Translate length rejection', core,
              '    case FOUNDATION_TEXT_INVALID_LENGTH:\n'
              '        throw std::invalid_argument("text must contain 1..256 bytes");', emphasis='supporting'),
            c(4, 'ascii', 'Translate byte rejection', core,
              '    case FOUNDATION_TEXT_INVALID_ASCII:\n'
              '        throw std::invalid_argument("text must contain printable ASCII only");', emphasis='supporting'),
            c(5, 'fault', 'Reject component failure', core,
              '    default:\n'
              '        throw std::logic_error("text validation component failed");', emphasis='supporting'),
        ], [edge('enter', 'status', 'runtime body reaches bridge call', 'step'),
            edge('status', 'ok', 'OK', 'conditional'),
            edge('status', 'length', 'INVALID_LENGTH', 'conditional', emphasis='supporting'),
            edge('status', 'ascii', 'INVALID_ASCII', 'conditional', emphasis='supporting'),
            edge('status', 'fault', 'other status', 'conditional', emphasis='supporting')],
        scope='Reusable domain validation'))

    maps.append(d('cpp-provider', 'Private ABI bridge and the selected C++ provider',
        'The bridge calls one configured implementation. The preprocessor box is a declaration dependency, '
        'not a runtime decision; expand it for the mutually exclusive Rust implementation. Guard returns leave the provider.', [
            c(0, 'bridge', 'Private C++ bridge', cpp,
              'uint32_t validate_text(const uint8_t *bytes, size_t length) noexcept {\n'
              '    return foundation_text_validate_v1(bytes, length);\n'
              '}'),
            c(1, 'selection', 'Compile-time provider selection', cpp,
              '#if defined(FOUNDATION_USE_RUST) && FOUNDATION_USE_RUST',
              child=link('rust-provider', 'length'), emphasis='supporting',
              note='Rust is selected when this condition is true; the C++ ABI implementation below is in its #else branch.'),
            c(2, 'bounds', 'Return length or pointer error early', cpp,
              '    if (length == 0 || length > 256) return FOUNDATION_TEXT_INVALID_LENGTH;\n'
              '    if (bytes == nullptr) return FOUNDATION_TEXT_INVALID_POINTER;'),
            c(3, 'loop', 'Scan bytes in order', cpp,
              '    for (size_t index = 0; index < length; ++index) {'),
            c(4, 'byte', 'Reject a non-printable byte', cpp,
              '        if (bytes[index] < 32 || bytes[index] > 126) {\n'
              '            return FOUNDATION_TEXT_INVALID_ASCII;\n'
              '        }'),
            c(5, 'ok', 'Return OK after the scan', cpp, '    return FOUNDATION_TEXT_OK;'),
        ], [edge('bridge', 'selection', 'implementation chosen at compile time', 'dependency', emphasis='supporting'),
            edge('bridge', 'bounds', 'foundation_text_validate_v1; configured cpp only', 'call'),
            edge('bounds', 'loop', 'length valid; pointer nonnull', 'conditional'),
            edge('loop', 'byte', 'index < length', 'conditional'),
            edge('byte', 'loop', 'byte accepted; increment index', 'conditional'),
            edge('loop', 'ok', 'scan completed', 'conditional')], scope='Private provider boundary'))

    maps.append(d('rust-provider', 'Selected Rust provider: preflight, borrow, pure checks',
        'This alternative is called by the same private bridge when configured for Rust. Length and null checks '
        'precede slice creation. Each guard can return its status; the helper length check is redundant after ABI preflight.', [
            c(0, 'length', 'ABI rejects invalid length', rust,
              '    if length == 0 || length > MAX_TEXT_BYTES {\n'
              '        return INVALID_LENGTH;\n'
              '    }'),
            c(1, 'pointer', 'ABI rejects null before borrowing', rust,
              '    if bytes.is_null() {\n'
              '        return INVALID_POINTER;\n'
              '    }'),
            c(2, 'borrow', 'Borrow bounded bytes and call helper', rust,
              '    let text = unsafe { core::slice::from_raw_parts(bytes, length) };\n'
              '    validate_text(text)',
              note='The caller must supply initialized bytes in one unchanged live allocation; this function retains none.'),
            c(3, 'pure-length', 'Pure helper checks length', rust,
              'fn validate_text(bytes: &[u8]) -> u32 {\n'
              '    if bytes.is_empty() || bytes.len() > MAX_TEXT_BYTES {\n'
              '        return INVALID_LENGTH;\n'
              '    }'),
            c(4, 'ascii', 'Pure helper checks printable bytes', rust,
              '    if bytes.iter().any(|&byte| byte < 32 || byte > 126) {\n'
              '        return INVALID_ASCII;\n'
              '    }'),
            c(5, 'ok', 'Return OK through the ABI', rust, '    OK\n}'),
        ], [edge('length', 'pointer', 'length valid', 'conditional'),
            edge('pointer', 'borrow', 'nonnull', 'conditional'),
            edge('borrow', 'pure-length', 'validate_text(text)', 'call'),
            edge('pure-length', 'ascii', 'length valid', 'conditional'),
            edge('ascii', 'ok', 'all bytes printable', 'conditional')], scope='Private Rust provider alternative'))

    maps.append(d('publish-view', 'Publication: authoritative records to adapter, then commit',
        'Selected critical statements from publish. List lookup/clear, status, enabled flags and scroll geometry '
        'also run between the highlighted groups. A presentation exception skips the final view commit and leaves retry debt.', [
            c(0, 'stage', 'Stage a snapshot and mark retry debt', app,
              '    presentation_pending_ = true;\n'
              '    auto next = view_;'),
            c(1, 'rows', 'Iterate authoritative records', app,
              '    for (const auto& entry : entries_.snapshot()) {\n'
              '        gui::Record record;'),
            c(2, 'record', 'Copy identity and visible text', app,
              '        record.id = std::to_string(entry.id);\n'
              '        record.accessible_text = entry.text;\n'
              '        record.cells = {{entry.text, {}, {}}};\n'
              '        list.records.push_back(std::move(record));'),
            c(3, 'layout', 'Call shared composition', app,
              '    const auto boxes = gui::compose_layout(panel, {16, 16, width, height},\n'
              '        [&](std::string_view id, double available) {', child=link('publish-layout', 'panel')),
            c(4, 'present', 'Present staged state', app,
              '    ++next.revision;\n'
              '    adapter_.present(next);'),
            c(5, 'commit', 'Commit only after successful present', app,
              '    view_ = std::move(next);\n'
              '    presentation_pending_ = false;'),
        ], [edge('stage', 'rows', 'lookup and clear list; begin iteration'),
            edge('rows', 'record', 'an entry remains', 'conditional'),
            edge('record', 'rows', 'next entry'),
            edge('rows', 'layout', 'no entries remain; status/tree setup follows', 'conditional'),
            edge('layout', 'present', 'compose returns; bounds and flags updated', 'return'),
            edge('present', 'commit', 'present returned successfully', 'return')]))

    maps.append(d('publish-layout', 'Shared layout: rows, composition callback, bounds and clip',
        'The panel is created with ID entries.form before these policy statements. The child lambda builds one '
        'LayoutNode per eligible row. Supplier compose internals are a boundary; the captured callback and output copying are shown.', [
            c(0, 'panel', 'Column policy', app,
              '    panel.kind = gui::LayoutKind::column;\n'
              '    panel.padding = {8, 8, 8, 8};\n'
              '    panel.gap = 4;'),
            c(1, 'children', 'Call the child lambda for eligible rows', app,
              '    for (const auto& definition : view_definition)\n'
              '        if (definition.id != panel.id && (!definition.remove_extension || remove_feature_))\n'
              '            child(std::string(definition.id), definition.height);'),
            c(2, 'compose', 'Compute client extent and call compose', app,
              '    const auto width = std::max(0.0, next.client_size.width - 32);\n'
              '    const auto height = std::max(0.0, next.client_size.height - 32);\n'
              '    const auto boxes = gui::compose_layout(panel, {16, 16, width, height},\n'
              '        [&](std::string_view id, double available) {'),
            c(3, 'measure', 'Composition callback measures labels', app,
              '            const auto& widget = lookup(next, id);\n'
              '            if (widget.spec.kind != gui::Kind::label) return gui::Size{available, 0};\n'
              '            return adapter_.measure_text({widget.state.text, widget.state.font,\n'
              '                available, next.display_scale, widget.state.wrap});'),
            c(4, 'bounds', 'Copy flattened client bounds', app,
              '    for (const auto& box : gui::flatten_layout(boxes))\n'
              '        lookup(next, box.id).state.bounds = box.bounds;'),
            c(5, 'clip', 'Set the group-relative viewport', app,
              '    group.content_clip = gui::Rect{8, 8, std::max(0.0, width - 16),\n'
              '                                  std::max(0.0, group.bounds.height - 16)};',
              note='Group content size and bounded height are assigned immediately before this fragment. content_clip coordinates are group-relative; widget bounds are client-relative.'),
        ], [edge('panel', 'children', 'build the column children'),
            edge('children', 'compose', 'creation loop completed'),
            edge('compose', 'measure', 'measurement callback as needed', 'call'),
            edge('measure', 'compose', 'return measured size', 'return'),
            edge('compose', 'bounds', 'compose returns boxes', 'return'),
            edge('bounds', 'clip', 'group extent/height setup follows')]))

    maps.append(d('service-request', 'Menu service request: fields, export bound, enqueue',
        'Shared heading/import/export branch after normalized ChooseOption. Import skips export serialization. '
        'A return in the oversize box returns from the visitor; handle still publishes. Enqueue success updates counters '
        'and normal handle publication precedes host service pumping.', [
            c(0, 'route', 'Select service command and guard identity', app,
              '                } else if (input.id == "heading" || input.id == "import" || input.id == "export") {\n'
              '                    if (next_service_ == std::numeric_limits<std::uint64_t>::max())\n'
              '                        throw std::overflow_error("Service identity exhausted");'),
            c(1, 'request', 'Create request identity and kind', app,
              '                    gui::ServiceRequest request;\n'
              '                    request.id = next_service_;\n'
              '                    request.kind = input.id == "heading" ? gui::ServiceKind::prompt :\n'
              '                        input.id == "import" ? gui::ServiceKind::read_text : gui::ServiceKind::write_text;'),
            c(2, 'limit', 'Set title and byte bound', app,
              '                    request.title = input.id == "heading" ? "Change heading" : input.id == "import" ? "Import entries" : "Export entries";\n'
              '                    request.byte_limit = input.id == "heading" ? 80 : 65536;',
              note='read_text/write_text carry valid UTF-8 text with a 64 KiB contract maximum, not arbitrary binary content.'),
            c(3, 'serialize', 'Export captures record text', app,
              '                    if (input.id == "export") {\n'
              '                        for (const auto& record : entries_.snapshot()) request.value += record.text + "\\n";\n'
              '                        if (request.value.size() > request.byte_limit) {'),
            c(4, 'oversize', 'Oversize result returns before enqueue', app,
              '                            advance_input_epoch();\n'
              '                            status_ = "Export exceeds the 64 KiB limit"; status_error_ = true; return;',
              child=link('event-dispatch', 'publish'), emphasis='supporting'),
            c(5, 'enqueue', 'Advance epoch and enqueue owned request', app,
              '                    advance_input_epoch();\n'
              '                    if (!services_.enqueue(std::move(request)))\n'
              '                        throw std::logic_error("Service request rejected");',
              child=link('service-pump', 'begin'),
              note='Pending/service-ID counters advance after queue success. The child is the later host pump, not a call made by enqueue.'),
        ], [edge('route', 'request', 'service ID available', 'conditional'),
            edge('request', 'limit', 'next fields'),
            edge('limit', 'serialize', 'export selected', 'conditional'),
            edge('limit', 'enqueue', 'import / heading; prompt default set if needed', 'conditional'),
            edge('serialize', 'oversize', 'serialized bytes exceed limit', 'conditional', emphasis='supporting'),
            edge('serialize', 'enqueue', 'serialized bytes fit', 'conditional')]))

    maps.append(d('service-pump', 'Native service pump: poll, begin, dispatch, later reply',
        'Supporting transport infrastructure called after native handle or tick. Only idle host state begins a queued '
        'request. The callee snippet shows normal request yield; shutdown/pending/current guards and epoch advancement precede it.', [
            c(0, 'poll', 'Poll and deliver an existing result', session,
              '        if (adapter.closed()) { files_.shutdown(); return; }\n'
              '        if (auto result = files_.poll()) current_->complete_service(std::move(*result));',
              child=link('service-completion', 'match'), emphasis='supporting'),
            c(1, 'worker', 'Wait while worker is active', session,
              '        if (files_.active()) return;', emphasis='supporting'),
            c(2, 'adapter', 'Check adapter service/prompt activity', session,
              '        const bool active = [&] {\n'
              '            if constexpr (requires { adapter.service_active(); }) return adapter.service_active();\n'
              '            else return bool(adapter.prompt());\n'
              '        }();', emphasis='supporting'),
            c(3, 'begin', 'Call shared next_service when idle', session,
              '        if (!adapter.closed() && !active) if (auto request = application.next_service())', emphasis='supporting'),
            c(4, 'yield', 'Begin queue entry and return owned request', app,
              '    auto request = services_.begin_next();\n'
              '    if (!request) throw std::logic_error("Pending service missing");\n'
              '    --pending_services_;\n'
              '    return request;', emphasis='supporting'),
            c(5, 'dispatch', 'Call provider with a completion callback', session,
              '            files_.service(adapter, std::move(*request), [this](gui::ServiceResult result) {\n'
              '                if (current_ && !adapter.closed()) current_->complete_service(std::move(result));\n'
              '            });', child=link('native-transfer', 'selection'), emphasis='supporting',
              note='Callback may deliver selector cancellation/error. Worker content results are delivered by later UI polling. Browser hosts use Browser/WebSession callbacks instead.'),
        ], [edge('poll', 'worker', 'after optional completion', 'step', emphasis='supporting'),
            edge('worker', 'adapter', 'no active worker', 'conditional', emphasis='supporting'),
            edge('adapter', 'begin', 'host idle', 'conditional', emphasis='supporting'),
            edge('begin', 'yield', 'application.next_service()', 'call', emphasis='supporting'),
            edge('yield', 'dispatch', 'owned request returned', 'return', emphasis='supporting'),
            edge('dispatch', 'poll', 'later tick/input poll or reply', 'event', emphasis='supporting')],
        scope='Supporting native service infrastructure'))

    maps.append(d('service-completion', 'complete_service: correlation, outcome, parser, publication',
        'The active-request guard rejects late/unmatched replies. The queue normalizes accepted status/text. '
        'Read-text success expands into the parser; accepted error/cancellation bypasses it. Browser and native '
        'delivery use this same shared method.', [
            c(0, 'match', 'Match active service, then advance epoch', app,
              '    if (shutdown_ || adapter_.closed()) return false;\n'
              '    const auto request = services_.current();\n'
              '    if (!request || request->id != result.id) return false;\n'
              '    advance_input_epoch();'),
            c(1, 'queue', 'Complete and normalize queued result', app,
              '    if (!services_.complete(result)) return false;'),
            c(2, 'errors', 'Handle error and cancellation', app,
              '    status_error_ = result.status == gui::ServiceStatus::error;\n'
              '    if (status_error_) status_ = std::move(result.error);\n'
              '    else if (result.status == gui::ServiceStatus::cancelled) status_ = "Service cancelled";', emphasis='supporting'),
            c(3, 'status', 'Successful prompt or export result', app,
              '    else if (request->kind == gui::ServiceKind::prompt) get("entries.heading").state.text = std::move(result.value);\n'
              '    else if (request->kind == gui::ServiceKind::write_text) status_ = "Export handed to host";',
              note='Export reports handoff, not disk durability or that a browser user retained the offered download.'),
            c(4, 'import', 'Successful read_text enters parser', app,
              '    else if (request->kind == gui::ServiceKind::read_text) {', child=link('import-parser', 'copy')),
            c(5, 'publish', 'Catch parser failure, publish accepted outcome', app,
              '        } catch (const std::exception& error) { status_ = error.what(); status_error_ = true; }\n'
              '    }\n'
              '    publish();\n'
              '    return true;', child=link('publish-view', 'stage'),
              note='The parser catch is included as source context. Accepted error/cancellation and prompt/export success also reach the same publication.'),
        ], [edge('match', 'queue', 'matching request; open', 'conditional'),
            edge('queue', 'errors', 'accepted/normalized result'),
            edge('errors', 'publish', 'error / cancellation', 'conditional', emphasis='supporting'),
            edge('errors', 'status', 'success', 'conditional'),
            edge('status', 'publish', 'prompt / write_text', 'conditional'),
            edge('status', 'import', 'read_text alternative', 'conditional'),
            edge('import', 'publish', 'parser returns or exception is caught', 'return')]))

    maps.append(d('import-parser', 'Import parser: staged Store loop and atomic commit',
        'This is inside the successful read_text try block. Empty input reaches commit with no records. A trailing '
        'newline creates no extra record; an interior blank line is rejected by Store::add. Any exception returns '
        'to the parent catch without committing staged records or staged next-ID state.', [
            c(0, 'copy', 'Copy Store and clear only the copy', app,
              '            auto replacement = entries_; // Commit all records together; preserve ID monotonicity.\n'
              '            for (const auto& record : replacement.snapshot()) replacement.erase(record.id);\n'
              '            std::size_t begin = 0;'),
            c(1, 'loop', 'Check for another input line', app,
              '            while (begin < result.value.size()) {'),
            c(2, 'line', 'Find newline and borrow the line', app,
              '                const auto end = result.value.find(\'\\n\', begin);\n'
              '                auto line = std::string_view(result.value).substr(begin,\n'
              '                    end == std::string::npos ? end : end - begin);'),
            c(3, 'add', 'Strip trailing CR and validate/add', app,
              '                if (!line.empty() && line.back() == \'\\r\') line.remove_suffix(1);\n'
              '                replacement.add(line);', child=link('core-add', 'validate')),
            c(4, 'advance', 'Stop at end or advance beyond newline', app,
              '                if (end == std::string::npos) break;\n'
              '                begin = end + 1;'),
            c(5, 'commit', 'Commit all records and clear selection', app,
              '            entries_ = std::move(replacement);\n'
              '            get("entries.list").state.selected.reset();\n'
              '            status_ = "Entries imported";'),
        ], [edge('copy', 'loop', 'begin staged parsing'),
            edge('loop', 'line', 'input remains', 'conditional'),
            edge('loop', 'commit', 'input exhausted / empty', 'conditional'),
            edge('line', 'add', 'line view created'),
            edge('add', 'advance', 'Store::add returned', 'return'),
            edge('advance', 'loop', 'newline found; continue', 'conditional'),
            edge('advance', 'commit', 'no newline; break', 'conditional')]))

    maps.append(d('native-transfer', 'Native content service: selector, worker, transfer and UI poll',
        'Supporting infrastructure excerpts, not application parsing. Read/write loops, bounds, temporary-file '
        'cleanup and destination replacement remain in the complete transfer source. The worker stores a value-only '
        'result; later UI polling returns it to Session. Browser file transport is a separate implementation.', [
            c(0, 'selection', 'Selected path stays on the host', files,
              '            try { start(request, std::filesystem::path(std::u8string(result.value.begin(), result.value.end()))); }',
              emphasis='supporting', note='This callback follows a generic path prompt. Selector cancellation/errors use reply without starting the worker.'),
            c(1, 'worker', 'Launch worker with owned values', files,
              '        worker_ = std::thread([this, request = std::move(request), path = std::move(path)] {', emphasis='supporting'),
            c(2, 'transfer', 'Worker calls transfer and captures failure', files,
              '            try { result = file_detail::transfer(request, path, stop_); }\n'
              '            catch (const std::exception& error) { result = {request.id, gui::ServiceStatus::error, {}, error.what()}; }', emphasis='supporting'),
            c(3, 'read', 'Read branch calls the file reader', files,
              '        while (!stop) {\n'
              '            const int count = file.read(buffer, sizeof buffer);\n'
              '            if (count < 0) { if (errno == EINTR) continue; throw std::runtime_error("Cannot read selected file"); }\n'
              '            if (count == 0) break;', emphasis='supporting',
              note='Regular-file and byte-bound checks precede/continue this fragment. Accepted chunks append to result.value.'),
            c(4, 'write', 'Write branch calls the file writer', files,
              '            const int count = file.write(request.value.data() + offset,\n'
              '                static_cast<unsigned>(std::min<std::size_t>(4096, request.value.size() - offset)));\n'
              '            if (count < 0 && errno == EINTR) continue;\n'
              '            if (count <= 0) throw std::runtime_error("Cannot write selected file");', emphasis='supporting',
              note='This writes an exclusive temporary file; successful close and noncancelled replacement commit afterward. It does not promise crash durability.'),
            c(5, 'poll', 'UI poll retrieves result and joins worker', files,
              '        { std::lock_guard lock(mutex_); result.swap(result_); }\n'
              '        if (result && worker_.joinable()) worker_.join();\n'
              '        return result;', child=link('service-completion', 'match'), emphasis='supporting',
              note='Worker storage into result_ precedes this later poll. Session calls complete_service with the returned value; the worker never calls Application.'),
        ], [edge('selection', 'worker', 'start(request, path)', 'call', emphasis='supporting'),
            edge('worker', 'transfer', 'worker executes its body', 'event', emphasis='supporting'),
            edge('transfer', 'read', 'read_text branch', 'conditional', emphasis='supporting'),
            edge('transfer', 'write', 'write_text branch', 'conditional', emphasis='supporting'),
            edge('read', 'poll', 'transfer returns; result stored; later UI poll', 'event', emphasis='supporting'),
            edge('write', 'poll', 'transfer returns; result stored; later UI poll', 'event', emphasis='supporting')],
        scope='Supporting native file-service infrastructure'))

    targets = {
        'startup': {
            'start-entry': ('main-to-widgets', 'entry'), 'start-session': ('gui-startup', 'session'),
            'start-application': ('application-init', 'enter'), 'start-widgets': ('widget-definitions', 'loop'),
            'start-layout': ('publish-layout', 'panel'), 'start-present': ('publish-view', 'present'),
            'start-return': ('gui-startup', 'show'), 'start-loop': ('gui-startup', 'loop')},
        'button-click': {
            'click-delivery': ('event-dispatch', 'bridge'), 'click-handle': ('event-dispatch', 'normalize'),
            'click-append': ('append-entry', 'epoch'), 'click-core': ('core-add', 'validate'),
            'click-validator': ('core-validation', 'status'), 'click-insert': ('core-add', 'insert'),
            'click-status': ('append-entry', 'success'), 'click-publish': ('publish-view', 'stage')},
        'import': {
            'import-action': ('service-request', 'route'), 'import-request': ('service-request', 'enqueue'),
            'import-begin': ('service-pump', 'begin'), 'import-read': ('native-transfer', 'read'),
            'import-delivery': ('service-pump', 'poll'), 'import-accept': ('service-completion', 'match'),
            'import-commit': ('import-parser', 'commit'), 'import-publish': ('service-completion', 'publish')},
        'export': {
            'export-action': ('service-request', 'route'), 'export-serialize': ('service-request', 'serialize'),
            'export-request': ('service-request', 'enqueue'), 'export-begin': ('service-pump', 'begin'),
            'export-write': ('native-transfer', 'write'), 'export-accept': ('service-completion', 'match'),
            'export-status': ('service-completion', 'status'), 'export-publish': ('service-completion', 'publish')},
    }
    bindings = {f'{flow}/{step}': link(map, target)
                for flow, steps in targets.items() for step, (map, target) in steps.items()}
    return {'maps': maps, 'bindings': bindings}
