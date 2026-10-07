"""Small, source-backed runtime walkthroughs for the existing application.

Only the supplied atlas resolver reads captured source. This module neither
opens target files nor imports or executes application code. Nodes describe
existing behavior; call, return and asynchronous-delivery arrows stay distinct.
"""
from __future__ import annotations


def make_runtime_flows(ref, node, edge, finish):
    """Return four existing-code flows, each with at most eight snake-layout nodes."""
    app = 'gui/shared/application.cpp'
    session = 'gui/host/contract.hpp'
    files = 'gui/host/file_services.hpp'
    browser = 'gui/host/browser.hpp'
    positions = ((0, 0), (1, 0), (2, 0), (3, 0),
                 (3, 1), (2, 1), (1, 1), (0, 1))

    def r(label, path, needle):
        return ref(label, path, needle)

    def n(index, id, role, title, summary, action, why, references):
        column, row = positions[index]
        return node(id, role, title, summary, action, why, column, row, references)

    meaning = ('These arrows describe existing execution. CALL is a named source call; '
               'PROCESS nodes group work and STEP arrows continue local statements. RETURN '
               'resumes a caller, including caught exception unwinding; EVENT crosses '
               'a callback, queue or asynchronous-delivery boundary. Conditional arrows '
               'name the selected branch. Supplier adapter internals are outside this walkthrough.')

    ctor = r('Shared Application constructor', app,
             'Application::Application(gui::Adapter& adapter, std::unique_ptr<TaskExecutor> executor)')
    publish = r('Shared publication body', app, 'void Application::publish() {')
    layout = r('Shared layout call', app,
               'const auto boxes = gui::compose_layout(panel, {16, 16, width, height},')
    present = r('Generic adapter presentation call', app, '    adapter_.present(next);')
    normal_publish = r('handle publishes after normal dispatch', app,
                       '        }, widget->input);\n    }\n    publish();')
    completion_publish = r('Service completion publishes its outcome', app,
                           '    publish();\n    return true;\n}\n\nvoid Application::shutdown()')
    native_callback = r('Native event callback', session,
                        '        if (current_) { current_->handle(event); services(); }')
    browser_callback = r('Browser event callback', browser,
                         '        if (application_) application_->handle(event);')
    normalization = r('Application event normalization', app,
                      'if (!gui::normalize_event(view_, event, [this](const gui::WidgetKey& key) {')
    epoch = r('Authoritative semantic epoch', app, 'void Application::advance_input_epoch() {')
    service_kind = r('Shared service-kind selection', app,
                     'request.kind = input.id == "heading" ? gui::ServiceKind::prompt :')
    service_limit = r('Shared request byte limit', app,
                      'request.byte_limit = input.id == "heading" ? 80 : 65536;')
    enqueue = r('Queue the owned service request', app,
                'if (!services_.enqueue(std::move(request)))')
    next_service = r('Application yields one queued request', app,
                     'std::optional<gui::ServiceRequest> Application::next_service() {')
    begin_next = r('Begin the next queued service', app, 'auto request = services_.begin_next();')
    host_service = r('Session calls the content provider', session,
                     'files_.service(adapter, std::move(*request), [this](gui::ServiceResult result) {')
    native_selector = r('Native host asks for a path', files,
                        'selection.title += " - file path";')
    native_worker = r('Native file worker starts', files,
                      'void start(gui::ServiceRequest request, std::filesystem::path path) {')
    native_transfer = r('Native bounded transfer', files,
                        'inline gui::ServiceResult transfer(const gui::ServiceRequest& request,')
    native_result = r('Native session delivers a polled result', session,
                      'if (auto result = files_.poll()) current_->complete_service(std::move(*result));')
    browser_result = r('Browser bridge calls shared completion', browser,
                       '[this](gui::ServiceResult result) { return application_->complete_service(std::move(result)); },')
    complete = r('Shared completion entry', app,
                 'bool Application::complete_service(gui::ServiceResult result) {')
    service_id = r('Match the currently active service ID', app,
                   'if (!request || request->id != result.id) return false;')
    queue_complete = r('Complete and normalize the queued result', app,
                       'if (!services_.complete(result)) return false;')
    error_status = r('Transport error becomes shared status', app,
                     'if (status_error_) status_ = std::move(result.error);')
    cancelled_status = r('Cancellation becomes shared status', app,
                         'else if (result.status == gui::ServiceStatus::cancelled) status_ = "Service cancelled";')
    content_contract = r('Owned text-service contract extension', 'gui/patches/file-services.patch',
                         '+    // These content services always enforce a maximum of 64 KiB.')

    startup = finish(
        'startup', 'First GUI run: entry point to event loop',
        'What executes when the GUI starts, before the first user action?',
        'This concrete path follows a normal FLTK launch without qualification flags. '
        'Other hosts supply different adapters but create the same shared Application. '
        'Browser startup references show the corresponding factory and receive boundary. '
        'The CLI is a separate entry in src/main.cpp and does not create this GUI.', meaning,
        [
            n(0, 'start-entry', 'ENTRY', 'main calls run_fltk', 'Owned FLTK composition root',
              'The executable main calls run_fltk<foundation::ui::Application>(argc, argv). '
              'The runner checks its arguments before constructing the session.',
              'This is one real GUI entry point, rather than a compiler or documentation entry.',
              [r('FLTK executable entry', 'gui/hosts/fltk_main.cpp',
                 'int main(int argc, char** argv) { return foundation::host::run_fltk<foundation::ui::Application>(argc, argv); }'),
               r('Separate CLI entry logic', 'src/main.cpp', 'int run(int argc, const char* const* argv) {')]),
            n(1, 'start-session', 'CALL', 'Construct the native session', 'Adapter + shared Application + file services',
              'run_fltk constructs NativeSession<App, gui::fltk::Adapter>. NativeSession aliases '
              'Session<App, Adapter, FileServices>; Session constructs the adapter callback before application(adapter). '
              'The callback starts forwarding only after current_ is assigned.',
              'The host chooses an adapter and generic services; it does not define product widgets.',
              [r('Native session instance', 'gui/hosts/fltk_main.cpp', 'NativeSession<App, gui::fltk::Adapter> session;'),
               r('Native session alias', 'gui/host/native_session.hpp',
                 'template<Application App, class Adapter> using NativeSession = Session<App, Adapter, FileServices>;'),
               r('Application construction in Session', session, '}), application(adapter) { current_ = &application; }')]),
            n(2, 'start-application', 'CALL', 'Application initializes state', 'Constructor receives the adapter',
              'The shared constructor requires its selected task executor, sets the window title, and begins '
              'creating declared controls. Browser<App> also constructs this same App with its WebAdapter.',
              'Application owns the Store and feature state, while the adapter remains host-supplied.',
              [ctor, r('Browser creates the shared App', browser, 'application_ = std::make_unique<App>(adapter);')]),
            n(3, 'start-widgets', 'PROCESS', 'Create declared widgets', 'view_definition → Application::add',
              'The constructor loops over view_definition and calls add for rows outside the optional Remove extension. '
              'add copies identity, kind, text, label, font and wrapping into widgets and assigns the current root parent. '
              'The constructor then configures editor policy, menu options and list behavior.',
              'The declaration table is consumed before the first snapshot is presented.',
              [r('Creation loop', app, '        if (!definition.remove_extension) add(definition);'),
               r('Widget creation method', app, 'gui::Widget& Application::add(const ViewDefinition& definition) {'),
               r('Widget declaration table', 'gui/shared/view_definition.hpp', 'inline constexpr std::array view_definition{')]),
            n(4, 'start-layout', 'CALL', 'Constructor calls publish', 'Records + status + shared layout',
              'Before the constructor returns, publish stages next from view_, projects Store records and status, '
              'composes the column layout, copies bounds, and sets enabled flags.',
              'Geometry and feature state are prepared by shared code before crossing the adapter boundary.',
              [r('Initial constructor publication', app,
                 '    entries.spec.follow_tail = true;\n    publish();\n}'), publish, layout]),
            n(5, 'start-present', 'CALL', 'Present the first snapshot', 'adapter_.present(next)',
              'publish increments the staged revision and calls adapter_.present(next). After that call succeeds '
              'it commits next to view_ and clears presentation_pending_. The concrete adapter body is outside '
              'the captured owned-source walkthrough.',
              'A failed presentation does not turn this boundary into a successful return.',
              [present, r('Commit after presentation', app,
                          '    view_ = std::move(next);\n    presentation_pending_ = false;')]),
            n(6, 'start-return', 'PROCESS', 'Return to the host runner', 'Construction finishes before input dispatch',
              'Successful publish returns through Application construction and Session construction to run_fltk. '
              'The runner shows the window and schedules its timer. Browser entry points instead construct '
              'Browser<App> and obtain its initial transport response.',
              'Native and browser startup share Application construction but use different outer event loops.',
              [r('Show native window and schedule ticks', 'gui/hosts/fltk_main.cpp',
                 'session.adapter.show(); Fl::add_timeout(0, Timer::tick, &timer);'),
               r('Hosted browser composition', 'gui/hosts/web_main.cpp',
                 'foundation::host::Browser<foundation::ui::Application> runtime(epoch);'),
               r('Wasm creation entry', 'gui/hosts/wasm_main.cpp', 'const char* gui_web_create(const char* epoch) {')]),
            n(7, 'start-loop', 'EVENT', 'Wait for events and ticks', 'FLTK wait → callbacks / Session::tick',
              'The normal native runner waits while the adapter is open. Its timer calls Session::tick, which calls '
              'Application::tick and pumps services. Adapter callbacks call Application::handle. Browser receives '
              'and ordered polls reach the same shared event/tick logic through Browser and WebSession.',
              'Startup hands control to ongoing input and progress delivery; these are later invocations.',
              [r('Native event loop', 'gui/hosts/fltk_main.cpp', 'while (!session.adapter.closed()) Fl::wait(.02);'),
               r('Native timer calls session tick', 'gui/hosts/fltk_main.cpp',
                 'self.owner.tick(); Fl::repeat_timeout(.02, tick, data);'),
               r('Session tick boundary', session, '        application.tick();'), native_callback,
               r('Browser receive boundary', browser, '        return session.receive(message);')]),
        ], [
            edge('start-entry', 'start-session', 'run_fltk constructs', 'call'),
            edge('start-session', 'start-application', 'application(adapter)', 'call'),
            edge('start-application', 'start-widgets', 'add(definition) loop', 'call'),
            edge('start-widgets', 'start-layout', 'publish()', 'call'),
            edge('start-layout', 'start-present', 'adapter_.present(next)', 'call'),
            edge('start-present', 'start-return', 'successful construction', 'return'),
            edge('start-return', 'start-loop', 'show / timer / wait', 'event'),
        ])

    button_click = finish(
        'button-click', 'Button click: Add entry to visible result',
        'Which functions are called by the existing Add button?',
        'This follows entries.add with Activate; editor SubmitText also calls append_entry. '
        'The native callback is shown concretely and browser forwarding is linked separately. '
        'Only caught input/capacity errors return through this normal publication path; other exceptions may escape.', meaning,
        [
            n(0, 'click-delivery', 'EVENT', 'Deliver the button event', 'entries.add + gui::Activate',
              'A supported adapter supplies WidgetEvent for the declared button. The native Session callback '
              'calls the current Application::handle(event); the browser callback uses its application_ pointer.',
              'The callback-to-application calls are owned source; vendor input translation is not expanded here.',
              [native_callback, r('Existing Add button', 'gui/shared/view_definition.hpp',
                                  'ViewDefinition{"entries.add", gui::Kind::button'), browser_callback]),
            n(1, 'click-handle', 'CALL', 'handle gates and dispatches', 'normalize_event → target-ID match',
              'handle rejects closed/shut-down state and normalizes against authoritative view_ and scroll offsets. '
              'Rejected input returns without publication. For accepted Activate on entries.add the visitor calls append_entry.',
              'A delivered event must still pass current availability, identity and input policy.',
              [normalization, r('Existing Add dispatch', app,
                                'if (widget->target.id == "entries.add") append_entry();')]),
            n(2, 'click-append', 'CALL', 'append_entry calls the core', 'Editor text → entries_.add(text)',
              'append_entry advances input_epoch before mutation, reads entries.editor text and calls entries_.add(text) '
              'inside its try block. Epoch exhaustion occurs before that try block and can escape.',
              'This helper owns application status and editor behavior, rather than widget dispatch.',
              [r('Application action helper', app, 'void Application::append_entry() {'),
               r('Core insertion call', app, '        entries_.add(text);'), epoch]),
            n(3, 'click-core', 'CALL', 'Store::add validates first', 'Owned domain insertion',
              'Store::add calls validate(text) before checking capacity, identifier availability and insertion. '
              'It owns records independently of the GUI.',
              'No list-row mutation can replace this core operation.',
              [r('Core add method', 'src/store.cpp', 'RecordId Store::add(std::string_view text) {')]),
            n(4, 'click-validator', 'CALL', 'Validate through the selected provider', 'Store::validate → private ABI',
              'Store::validate calls detail::validate_text, which calls foundation_text_validate_v1. The configured '
              'Rust or C++ provider returns a numeric status; Store translates it to success or an exception.',
              'Provider choice is conditional configuration, not two calls made for each click.',
              [r('Domain validation translation', 'src/store.cpp', 'void Store::validate(std::string_view text) {'),
               r('Private validation wrapper', 'src/text_validation.cpp',
                 'uint32_t validate_text(const uint8_t *bytes, size_t length) noexcept {'),
               r('Rust provider entry', 'rust/text_validation/src/lib.rs',
                 'pub unsafe extern "C" fn foundation_text_validate_v1'),
               r('Selected C++ provider entry', 'src/text_validation.cpp',
                 'extern "C" uint32_t foundation_text_validate_v1')]),
            n(5, 'click-insert', 'PROCESS', 'Resume Store::add and return', 'Capacity / ID / owned record',
              'After successful validation, add rejects a full collection or exhausted ID, then pushes an owned record '
              'and increments next_id_. Its RecordId returns to append_entry; this caller does not use the returned ID.',
              'Validation returns into Store::add. It does not call GUI publication.',
              [r('Owned record insertion', 'src/store.cpp', '    records_.push_back({id, std::string(text)});'),
               r('Collection capacity failure', 'src/store.cpp', '        throw std::length_error("collection is full");')]),
            n(6, 'click-status', 'PROCESS', 'Set success or caught error status', 'Return to append_entry',
              'Success clears editor text and sets Entry added. Caught invalid_argument or length_error sets error '
              'status without clearing the editor. Other exceptions escape. The helper itself never calls publish.',
              'Status handling returns to handle; publication is the caller\'s subsequent action.',
              [r('Success status', app, '        status_ = "Entry added";'),
               r('Caught input error', app, '    } catch (const std::invalid_argument& error) {'),
               r('Caught capacity error', app, '    } catch (const std::length_error& error) {')]),
            n(7, 'click-publish', 'OUTPUT', 'handle publishes after dispatch', 'Store rows / status → adapter',
              'After the visitor returns normally, handle calls publish. Shared projection rebuilds list rows, status, '
              'layout and enabled state before calling adapter_.present(next). Presentation failure leaves retry debt.',
              'The visible result follows normal dispatch completion, not a direct call from validation.',
              [normal_publish, publish, present]),
        ], [
            edge('click-delivery', 'click-handle', 'handle(event)', 'call'),
            edge('click-handle', 'click-append', 'Activate + entries.add', 'call'),
            edge('click-append', 'click-core', 'entries_.add(text)', 'call'),
            edge('click-core', 'click-validator', 'validate(text)', 'call'),
            edge('click-validator', 'click-insert', 'validation succeeded', 'return'),
            edge('click-validator', 'click-status', 'throws invalid_argument', 'return'),
            edge('click-insert', 'click-status', 'ID / caught length_error', 'return'),
            edge('click-status', 'click-handle', 'visitor resumes', 'return'),
            edge('click-handle', 'click-publish', 'after normal dispatch', 'call'),
        ])

    import_flow = finish(
        'import', 'Import: menu request to atomic replacement',
        'What executes after Actions → Import entries?',
        'Shared code requests owned UTF-8 text with a 64 KiB maximum. Native selectors/worker and browser '
        'file transport differ, then deliver the same correlated ServiceResult. Parsing mutates a staged Store '
        'and commits the complete replacement only on success.', meaning,
        [
            n(0, 'import-action', 'EVENT', 'handle receives Import option', 'ChooseOption id = import',
              'The menu event reaches handle through the host callback and passes normalize_event before its '
              'ChooseOption branch recognizes import.',
              'Import begins with shared menu intent, not an application file-path call.',
              [r('Import menu declaration', app, '{"import", "Import entries", "", true}'),
               r('Service command route', app, '} else if (input.id == "heading" || input.id == "import" || input.id == "export") {'),
               normalization, native_callback]),
            n(1, 'import-request', 'PROCESS', 'Queue a read_text request', 'Owned request ID + 64 KiB bound',
              'handle assigns the next service ID, read_text kind and title, with byte_limit 65536. It advances '
              'input_epoch, enqueues the request and updates pending counters. Normal handle dispatch then publishes '
              'before returning to the native service pump or browser bridge.',
              'Enqueueing does not itself read a file or call next_service.',
              [service_kind, service_limit, enqueue, epoch, normal_publish]),
            n(2, 'import-begin', 'CALL', 'Host calls next_service', 'begin_next returns one queued request',
              'The native Session services method checks host activity, calls application.next_service and passes the '
              'returned request to FileServices. next_service advances input_epoch, begins the queued request and '
              'decrements pending count. Browser WebSession uses the supplied next_service callback.',
              'Queued and active requests are separate states; only one active request is yielded.',
              [next_service, begin_next, host_service,
               r('Browser request callback', browser, '[this] { return application_->next_service(); }')]),
            n(3, 'import-read', 'EVENT', 'Host obtains bounded text', 'Native worker / browser file transport',
              'Native FileServices asks for a path on the host side, starts its worker and calls file_detail::transfer '
              'to read a regular file within the byte bound. Browser file helpers use fatal UTF-8 decoding and ordered '
              'upload/finish operations. No path or browser File enters Application.',
              'This asynchronous boundary is transport-specific; record parsing remains shared.',
              [native_selector, native_worker, native_transfer,
               r('Browser text read', 'gui/host/file_services.mjs',
                 'export async function readTextFile(file, requestedLimit, {signal, isCurrent} = {}) {'),
               r('Browser UTF-8 decoding', 'gui/host/file_services.mjs',
                 "return new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes);"), content_contract]),
            n(4, 'import-delivery', 'EVENT', 'Deliver the service result', 'Poll/callback → complete_service',
              'Native Session polls the worker result on the UI owner and calls complete_service. Selector cancellation '
              'or errors may use its reply callback instead. Browser WebSession delivers through the supplied '
              'complete_service callback after its transport checks.',
              'The file worker does not call Application or manipulate widgets.',
              [native_result, r('Native immediate reply callback', session,
                               'if (current_ && !adapter.closed()) current_->complete_service(std::move(result));'), browser_result]),
            n(5, 'import-accept', 'DECISION', 'Correlate and normalize completion', 'Active service ID + queue contract',
              'complete_service rejects closed/shut-down state and a missing or mismatched active request. It advances '
              'input_epoch and calls services_.complete(result), which consumes and normalizes the accepted result. '
              'Only successful read_text reaches parsing; cancellation or error updates status instead.',
              'Unmatched results return false without parsing or publication; UTF-8/limit rejection becomes an error outcome.',
              [complete, service_id, queue_complete, error_status, cancelled_status, content_contract]),
            n(6, 'import-commit', 'PROCESS', 'Parse a staged Store, then commit', 'replacement.add → entries_ assignment',
              'The success branch copies entries_, erases old records in that copy, splits lines, strips a trailing CR '
              'and calls replacement.add for each record. Only after all records validate does it move replacement '
              'into entries_ and clear selection. An empty file replaces with an empty collection; malformed content '
              'leaves live records and next-ID state unchanged and sets error status.',
              'Copying the existing Store preserves monotonic ID allocation; rebuilding a fresh Store would reuse IDs.',
              [r('Staged replacement', app,
                 'auto replacement = entries_; // Commit all records together; preserve ID monotonicity.'),
               r('Validate each imported line', app, '                replacement.add(line);'),
               r('Commit imported records', app, '            entries_ = std::move(replacement);'),
               r('Core add validates before insertion', 'src/store.cpp', 'RecordId Store::add(std::string_view text) {')]),
            n(7, 'import-publish', 'OUTPUT', 'Publish the accepted outcome', 'Committed rows or unchanged rows + status',
              'Accepted success, parse failure, transport error or cancellation reaches publish from complete_service. '
              'It projects the resulting Store and shared status to the adapter, then completion returns true. '
              'A publication exception can escape while accepted authoritative changes remain.',
              'The outcome distinguishes content acceptance from service delivery and painting.',
              [completion_publish, publish, present]),
        ], [
            edge('import-action', 'import-request', 'ChooseOption branch', 'step'),
            edge('import-request', 'import-begin', 'after handle returns: host pump', 'event'),
            edge('import-begin', 'import-read', 'dispatch content capability', 'event'),
            edge('import-read', 'import-delivery', 'asynchronous result', 'event'),
            edge('import-delivery', 'import-accept', 'complete_service(result)', 'call'),
            edge('import-accept', 'import-commit', 'successful read_text', 'conditional'),
            edge('import-accept', 'import-publish', 'accepted cancellation / error', 'conditional'),
            edge('import-commit', 'import-publish', 'commit or caught parse error', 'call'),
        ])

    export_flow = finish(
        'export', 'Export: captured records to host handoff',
        'What executes after Actions → Export entries?',
        'Export captures record text when the command is accepted and sends owned UTF-8 content. '
        'Native transfer replaces a chosen destination after writing a temporary file; browser transfer offers '
        'a download. Shared success says Export handed to host, not durably saved.', meaning,
        [
            n(0, 'export-action', 'EVENT', 'handle receives Export option', 'ChooseOption id = export',
              'The declared menu event passes handle normalization and enters the export branch of shared '
              'service-command routing.',
              'The feature request begins in shared code before any host file selector.',
              [r('Export menu declaration', app, '{"export", "Export entries", "", true}'),
               r('Export serialization branch', app, '                    if (input.id == "export") {'), normalization]),
            n(1, 'export-serialize', 'PROCESS', 'Capture and bound serialized text', 'Store snapshot → request.value',
              'The command serializes each Store record as text plus newline into owned request.value. It checks '
              'the complete byte count against byte_limit. Oversized output advances input_epoch, sets error status '
              'and returns from the visitor without enqueueing; handle still performs its normal publication.',
              'Later record edits do not rewrite content already captured in the request.',
              [r('Current serialization', app,
                 'for (const auto& record : entries_.snapshot()) request.value += record.text + "\\n";'),
               r('Serialized byte count check', app, 'if (request.value.size() > request.byte_limit) {'), service_limit]),
            n(2, 'export-request', 'PROCESS', 'Queue the bounded write_text request', 'Service ID + content + epoch',
              'For output within the bound, handle uses write_text, advances input_epoch, enqueues its owned request '
              'and updates counters. It publishes and returns before host service delivery.',
              'No file has been written by the enqueue call.',
              [service_kind, enqueue, epoch, normal_publish, content_contract]),
            n(3, 'export-begin', 'CALL', 'Host begins the queued service', 'next_service → generic content provider',
              'The service pump calls next_service, which begins one active request and advances input_epoch. Native '
              'Session passes it to FileServices; Browser supplies equivalent request/completion callbacks to WebSession.',
              'Application passes owned content and receives a correlated result, not a host pathname.',
              [next_service, begin_next, host_service, browser_result]),
            n(4, 'export-write', 'EVENT', 'Host writes or offers a download', 'Native temporary replacement / browser offer',
              'Native FileServices obtains its selected path and its worker calls file_detail::transfer. That routine '
              'writes an exclusive sibling temporary file and replaces the destination only after completed writing '
              'and close when not cancelled. Browser file helpers retrieve bounded export content and offer a download. '
              'Cancellation before native commit preserves the destination; cancellation after commit cannot undo it.',
              'These generic transport steps do not promise crash durability or that a user retained a browser download.',
              [native_selector, native_worker, native_transfer,
               r('Native successful replacement marker', files, '            committed = true;'),
               r('Browser export reads', 'gui/host/file_services.mjs',
                 'export async function downloadTextFile(service, exchange, signal, isCurrent) {')]),
            n(5, 'export-accept', 'DECISION', 'Deliver and correlate completion', 'ServiceResult → active request match',
              'The native UI pump/reply callback or browser completion callback calls complete_service. Closed/shut-down '
              'or unmatched results return false. A matching active result advances input_epoch and passes through '
              'services_.complete before shared outcome handling.',
              'A late or repeated result does not authorize another output request or shared success status.',
              [complete, service_id, queue_complete, native_result, browser_result]),
            n(6, 'export-status', 'PROCESS', 'Set honest shared status', 'Success / cancellation / transport error',
              'Successful write_text sets Export handed to host. Accepted cancellation sets Service cancelled; '
              'an error uses the normalized error text. This completion does not mutate Store records.',
              'Success reports the content capability\'s handoff semantics, not durable storage.',
              [r('Export handoff message', app,
                 'else if (request->kind == gui::ServiceKind::write_text) status_ = "Export handed to host";'),
               error_status, cancelled_status]),
            n(7, 'export-publish', 'OUTPUT', 'Publish the resulting status', 'complete_service → publish → present',
              'After accepted service outcome handling, complete_service calls publish and returns true on normal '
              'completion. The local oversized-output branch reaches publication directly from handle, without '
              'starting a service. Repainting does not serialize or write the export again.',
              'Publication is a separate visible result after request rejection or service completion.',
              [completion_publish, normal_publish, publish, present]),
        ], [
            edge('export-action', 'export-serialize', 'ChooseOption branch', 'step'),
            edge('export-serialize', 'export-request', 'serialized bytes fit', 'conditional'),
            edge('export-serialize', 'export-publish', 'too large: local status', 'conditional'),
            edge('export-request', 'export-begin', 'after handle returns: host pump', 'event'),
            edge('export-begin', 'export-write', 'dispatch content capability', 'event'),
            edge('export-write', 'export-accept', 'asynchronous result / callback', 'event'),
            edge('export-accept', 'export-status', 'accepted outcome', 'conditional'),
            edge('export-status', 'export-publish', 'publish()', 'call'),
        ])

    return [startup, button_click, import_flow, export_flow]
