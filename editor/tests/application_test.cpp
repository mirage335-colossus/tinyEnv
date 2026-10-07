#include "editor/ui/application.hpp"
#include "editor/ui/canvas.hpp"
#include "editor/model/project.hpp"
#include "editor/self/generated/visual/forms.hpp"
#include "editor/self/generated/visual/events.hpp"
#include "gui/host/framebuffer.hpp"
#include <gui/framebuffer.hpp>
#include <gui/memory_adapter.hpp>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>

using namespace foundation::editor;
static_assert(foundation::host::Application<Application>);
static_assert(foundation::host::BezelApplication<Application>);

namespace {
void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}
std::string read(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("Cannot read fixture " + path.string());
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}
void write(const std::filesystem::path& path, std::string_view bytes) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream stream(path, std::ios::binary);
    stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!stream) throw std::runtime_error("Cannot write fixture " + path.string());
}
struct Temporary {
    std::filesystem::path root = std::filesystem::temp_directory_path() /
        ("foundation editor application fixture " +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    Temporary() { require(std::filesystem::create_directory(root), "Fixture directory collision"); }
    ~Temporary() {
        configure_launch();
        std::error_code error;
        std::filesystem::remove_all(root, error);
    }
};
struct WorkingDirectory {
    std::filesystem::path previous = std::filesystem::current_path();
    explicit WorkingDirectory(const std::filesystem::path& path) { std::filesystem::current_path(path); }
    ~WorkingDirectory() {
        std::error_code error;
        std::filesystem::current_path(previous, error);
    }
};
const gui::Widget* find(const gui::Snapshot& snapshot, std::string_view id) {
    const auto item = std::find_if(snapshot.widgets.begin(), snapshot.widgets.end(),
        [&](const auto& widget) { return widget.spec.key.id == id; });
    return item == snapshot.widgets.end() ? nullptr : &*item;
}
const gui::Widget& widget(const gui::Snapshot& snapshot, std::string_view id) {
    const auto* value = find(snapshot, id);
    if (!value) throw std::runtime_error("Missing editor control " + std::string(id));
    return *value;
}
gui::Point center(gui::Rect bounds) {
    return {bounds.x + bounds.width / 2, bounds.y + bounds.height / 2};
}
std::map<std::string, std::string> inventory(const std::filesystem::path& root) {
    std::map<std::string, std::string> result;
    for (const auto& entry : std::filesystem::recursive_directory_iterator(root))
        if (entry.is_regular_file()) result.emplace(entry.path().lexically_relative(root).generic_string(), read(entry.path()));
    return result;
}
void capture(const gui::Snapshot& snapshot, const std::filesystem::path& directory, std::string_view name) {
    if (directory.empty()) return;
    std::filesystem::create_directories(directory);
    gui::FramebufferAdapter adapter;
    adapter.present(snapshot);
    const auto image = adapter.frame();
    require(image.pixels && image.width && image.height, "Editor capture contains no frame");
    const auto path = directory / (std::string(name) + ".ppm");
    std::ofstream stream(path, std::ios::binary);
    stream << "P6\n" << image.width << ' ' << image.height << "\n255\n";
    for (unsigned y = 0; y < image.height; ++y)
        stream.write(reinterpret_cast<const char*>(image.pixels->data() + y * image.stride_bytes),
                     static_cast<std::streamsize>(image.width * 3));
    require(bool(stream), "Editor capture could not be saved");
}
struct Session {
    gui::FramebufferAdapter metrics;
    gui::MemoryAdapter adapter{[this](const gui::Event& event) { application->handle(event); },
                              64 * 1024 * 1024,
                              [this](const gui::TextMeasureRequest& request) { return metrics.measure_text(request); }};
    std::unique_ptr<Application> application;
    explicit Session(const std::filesystem::path& project = {}, const std::filesystem::path& root = {},
                     const std::filesystem::path& executable = {}) {
        configure_launch(project, root, executable);
        application = std::make_unique<Application>(adapter);
        healthy("initial presentation");
    }
    const gui::Snapshot& view() const { return application->view(); }
    void healthy(std::string_view step) const {
        require(!application->presentation_pending(), std::string(step) + ": presentation pending");
        require(adapter.snapshot().revision == view().revision, std::string(step) + ": adapter has an obsolete snapshot");
        const auto& status = widget(view(), "editor.status");
        require(status.state.font.tone != gui::Tone::error,
                std::string(step) + ": " + status.state.text + "\n" + widget(view(), "editor.diagnostics").state.text);
    }
    void send(std::string_view id, gui::Input input, bool expect_success = true) {
        const auto target = widget(view(), id).spec.key;
        require(adapter.send(gui::WidgetEvent{target, std::move(input)}) == gui::Delivery::delivered,
                "Adapter rejected " + std::string(id));
        if (expect_success) healthy(id);
    }
    void activate(std::string_view id, bool expect_success = true) { send(id, gui::Activate{}, expect_success); }
    void choose(std::string_view id, std::string value) { send(id, gui::ChooseOption{std::move(value)}); }
    void edit(std::string_view id, std::string value) {
        send(id, gui::EditText{std::move(value), widget(view(), id).state.text});
    }
    void submit(std::string_view id, bool expect_success = true) {
        require(widget(view(), id).spec.text_policy.submit == gui::SubmitKey::enter,
                "Enter submission is unavailable for " + std::string(id));
        send(id, gui::SubmitText{}, expect_success);
    }
    void select(std::string value) { send("editor.objects", gui::SelectRecord{std::move(value)}); }
    void pointer(gui::Point position, gui::PointerKind kind = gui::PointerKind::click, bool expect_success = true) {
        gui::PointerInput input; input.kind = kind; input.position = position;
        if (kind == gui::PointerKind::press || kind == gui::PointerKind::move ||
            kind == gui::PointerKind::release || kind == gui::PointerKind::cancel) input.pointer_id = 1;
        send("canvas.surface", input, expect_success);
    }
    std::size_t objects() const { return widget(view(), "editor.objects").state.records.size(); }
};
Project initial_project() {
    auto project = empty_project("Application integration fixture");
    Form form; form.id = "main"; form.label = "Main panel";
    Control start; start.id = "start"; start.label = "Start"; start.layout = {24, 24, 120, 32}; start.binding = "on_start";
    form.controls.push_back(start);
    project.forms.push_back(form);
    project.flows.push_back({"main_flow", "Processing chain"});
    project.bindings.push_back({"on_start", "activate", "src/handlers.hpp", "fixture::on_start", "on_start", "src/handlers.hpp"});
    return project;
}
Project saved_project(const std::filesystem::path& root) {
    auto parsed = parse_project(read(root / "design/project.json"));
    require(bool(parsed), "Saved design could not be parsed");
    return std::move(*parsed.project);
}
void self_toolbar(Session& session) {
    const auto toolbar = self_generated::snapshot("editor.chrome", 1);
    for (const auto& expected : toolbar.widgets) {
        const auto& actual = widget(session.view(), expected.spec.key.id);
        require(actual.spec.kind == expected.spec.kind && actual.state.bounds == expected.state.bounds &&
                actual.state.label == expected.state.label, "Actual toolbar differs from retained self-generated forms");
    }
    struct Actions {
        std::string last;
        void invoke(std::string_view action) { last = action; }
    } actions;
    unsigned handlers = 0;
    for (const auto& binding : self_generated::event_bindings()) {
        gui::WidgetEvent event{{binding.widget_id, 1}, gui::Activate{}};
        require(self_generated::dispatch_handler(actions, actions, event), "Self-generated toolbar omitted a dispatch");
        require(actions.last == binding.widget_id, "Ordinary self-host handler invoked the wrong editor action");
        ++handlers;
    }
    require(handlers >= 10, "Self-host toolbar has no ordinary action bindings");
}
void source_and_forms(Session& session, const std::filesystem::path& root, const std::filesystem::path& captures) {
    require(session.objects() == 1, "Project launch did not load its form");
    self_toolbar(session);
    capture(session.view(), captures, "editor-initial");
    const auto unchanged = inventory(root);
    session.activate("editor.add");
    require(session.objects() == 2, "Add-widget command did not alter the form");
    session.activate("editor.undo");
    require(session.objects() == 1, "Generated Undo action did not restore the form");
    session.activate("editor.redo");
    require(session.objects() == 2, "Generated Redo action did not restore the added widget");
    session.select("start");
    require(widget(session.view(), "editor.objects").state.selected == "start", "Element list failed to select a widget");
    session.pointer({234, 154}, gui::PointerKind::double_click);
    require(session.view().modal_root.has_value(), "Double-click did not open a source window");
    const auto original = read(root / "src/handlers.hpp");
    require(widget(session.view(), "code.text").state.text == original, "Code window did not open the ordinary bound file");
    require(inventory(root) == unchanged, "Opening an existing source file changed project files");
    capture(session.view(), captures, "editor-code");
    const auto amended = original + "\n// Edited through the ordinary GUI source buffer: caf\xc3\xa9.\n";
    session.edit("code.text", amended);
    session.activate("code.undo");
    require(widget(session.view(), "code.text").state.text == original, "Source Undo did not restore source bytes");
    session.activate("code.redo");
    require(widget(session.view(), "code.text").state.text == amended, "Source Redo did not restore source bytes");
    session.activate("code.save");
    require(read(root / "src/handlers.hpp") == amended, "Source Save did not publish the ordinary file");
    const auto local = amended + "// Local unsaved change\n";
    session.edit("code.text", local);
    const std::string external = "// An independent editor changed this ordinary source file.\n";
    write(root / "src/handlers.hpp", external);
    session.activate("code.save", false);
    require(widget(session.view(), "editor.status").state.font.tone == gui::Tone::error, "Conflicting source save reported success");
    require(read(root / "src/handlers.hpp") == external, "Conflicting source save overwrote the external edit");
    require(widget(session.view(), "code.text").state.text == local, "Conflicting source save lost local code");
    session.activate("code.discard");
    session.select("start");
    session.activate("editor.preview");
    const auto& preview = widget(session.view(), "canvas.preview.start");
    require(!preview.state.enabled && !widget(session.view(), "canvas.surface").spec.pointer_input,
            "Preview left project controls or design gestures live");
    const auto before_preview = inventory(root);
    require(session.adapter.send(gui::WidgetEvent{preview.spec.key, gui::Activate{}}) == gui::Delivery::ignored,
            "Inert preview dispatched application code");
    capture(session.view(), captures, "editor-preview");
    session.activate("editor.preview");
    require(inventory(root) == before_preview, "Preview changed project source files");
    session.activate("editor.save");
    const auto design = saved_project(root);
    require(design.forms.at(0).controls.size() == 2, "Design Save did not retain form edits");
    require(read(root / "src/handlers.hpp") == external, "Design Save rewrote ordinary handler source");
    require(std::filesystem::is_regular_file(root / "generated/visual/forms.hpp"), "Design Save did not retain generated layouts");
    // Existing Rust files are editable text and need no Rust compiler or SDK.
    session.choose("editor.mode", "files");
    session.send("editor.objects", gui::ActivateRecord{"src/bridge.rs"});
    const auto rust = read(root / "src/bridge.rs");
    require(widget(session.view(), "code.text").state.text == rust, "Files workspace did not open ordinary Rust source");
    session.edit("code.text", rust + "// Rust remains project-owned source.\n");
    session.activate("code.save");
    require(read(root / "src/bridge.rs") == rust + "// Rust remains project-owned source.\n", "Rust text save changed the source bytes");
    session.activate("code.close");
}
gui::Point port_position(const Project& project, const Session& session, std::string_view block,
                         std::string_view port, PortDirection direction) {
    Canvas canvas; CanvasOptions options;
    options.mode = CanvasMode::flows;
    options.document = widget(session.view(), "editor.document").state.selected.value_or("");
    options.viewport = widget(session.view(), "canvas.viewport").state.bounds;
    options.measure_text = [&](const gui::TextMeasureRequest& request) { return session.adapter.measure_text(request); };
    (void)canvas.render(project, options);
    const auto position = canvas.port_position(block, port, direction);
    require(position.has_value(), "Canvas omitted an arbitrary named port");
    return *position;
}
void flows(Session& session, const std::filesystem::path& root, const std::filesystem::path& captures) {
    session.choose("editor.mode", "flows");
    session.activate("editor.add");
    require(session.objects() == 1, "Add-block command did not create a block");
    session.edit("property.label", "Source");
    session.edit("property.position", "24, 32");
    session.activate("editor.apply");
    session.activate("editor.details");
    session.edit("detail.inputs", "sample : float\nmode : int\nextra : double\n");
    session.edit("detail.outputs", "out : float\nphase : int\n");
    session.edit("detail.params", "gain = 2\nnote = arbitrary project object\n");
    session.activate("detail.apply");
    // A draft without a factory is saveable; code generation waits for the
    // ordinary source factory created by the explicit double-click gesture.
    session.activate("editor.save", false);
    require(widget(session.view(), "editor.status").state.font.tone == gui::Tone::error,
            "Incomplete block factory did not leave an actionable draft diagnostic");
    require(saved_project(root).blocks.size() == 1, "Incomplete flow draft could not be saved");
    session.pointer(center(widget(session.view(), "canvas.block." +
                    widget(session.view(), "editor.objects").state.selected.value_or("")).state.bounds),
                    gui::PointerKind::double_click);
    require(session.view().modal_root.has_value(), "Source block double-click did not open ordinary factory code");
    session.activate("code.close");
    session.activate("editor.add");
    session.edit("property.label", "Sink");
    session.edit("property.position", "390, 100");
    session.activate("editor.apply");
    session.activate("editor.details");
    session.edit("detail.inputs", "in : float\nstate : int\n");
    session.edit("detail.outputs", "result : double\n");
    session.activate("detail.apply");
    session.pointer(center(widget(session.view(), "canvas.block." +
                    widget(session.view(), "editor.objects").state.selected.value_or("")).state.bounds),
                    gui::PointerKind::double_click);
    require(session.view().modal_root.has_value(), "Sink block double-click did not open ordinary factory code");
    session.activate("code.close");
    session.activate("editor.save", false);
    require(widget(session.view(), "editor.status").state.font.tone == gui::Tone::error,
            "Unconnected required MIMO ports lost their draft diagnostic");
    auto design = saved_project(root);
    require(design.blocks.size() == 2, "Saved flow did not retain arbitrary blocks");
    const auto& source = design.blocks.at(0);
    const auto& sink = design.blocks.at(1);
    require(source.inputs.size() == 3 && source.outputs.size() == 2 &&
            sink.inputs.size() == 2 && sink.outputs.size() == 1,
            "Block Details constrained the arbitrary MIMO port lists");
    require(source.params.at("gain") == "2", "Block Details lost a project-owned parameter");
    const auto source_id = source.id, sink_id = sink.id;
    session.activate("editor.zoom.reset", false);
    require(widget(session.view(), "editor.status").state.font.tone == gui::Tone::error,
            "Changing canvas zoom discarded the unresolved flow draft diagnostic");
    session.pointer(port_position(design, session, source_id, "out", PortDirection::output));
    session.pointer(port_position(design, session, sink_id, "in", PortDirection::input));
    require(session.objects() == 3, "Pointer port gesture did not create an edge");
    session.activate("editor.save", false);
    require(widget(session.view(), "editor.status").state.font.tone == gui::Tone::error,
            "Partly connected MIMO draft incorrectly reported runnable generation");
    design = saved_project(root);
    require(design.edges.size() == 1 && design.edges.front().from_block == source_id &&
            design.edges.front().from_port == "out" && design.edges.front().to_block == sink_id &&
            design.edges.front().to_port == "in", "Saved connection differs from the visually selected ports");
    capture(session.view(), captures, "editor-flows");
    // Selecting an element retains the useful unresolved draft diagnostic.
    session.send("editor.objects", gui::SelectRecord{source_id}, false);
    session.pointer(center(widget(session.view(), "canvas.block." + source_id).state.bounds), gui::PointerKind::double_click);
    require(session.view().modal_root.has_value(), "Double-click did not open the block source file");
    const auto source_path = root / design.blocks.front().file;
    require(std::filesystem::is_regular_file(source_path), "Double-click did not create ordinary block code");
    require(widget(session.view(), "code.text").state.text == read(source_path), "Block code window is not the ordinary source buffer");
    require(read(source_path).find(design.blocks.front().factory) != std::string::npos,
            "Block source has no editable factory declaration");
    session.activate("code.close");
}
void gesture_regressions(const std::filesystem::path& root, const std::filesystem::path& captures) {
    auto project = initial_project();
    Block source; source.id = "source"; source.flow = "main_flow"; source.label = "Source";
    source.x = 32; source.y = 36; source.factory = "fixture::source";
    source.header = "src/blocks.hpp"; source.file = source.header;
    source.outputs = {{"samples", "float", false}, {"count", "int", false}};
    Block sink; sink.id = "sink"; sink.flow = "main_flow"; sink.label = "Sink";
    sink.x = 362; sink.y = 162; sink.factory = "fixture::sink";
    sink.header = source.header; sink.file = source.header;
    sink.inputs = {{"samples", "float", false}, {"count", "int", false}};
    auto remote_source = source; remote_source.id = "remote_source"; remote_source.flow = "remote_flow";
    remote_source.x = 20; remote_source.y = 20;
    auto remote_sink = sink; remote_sink.id = "remote_sink"; remote_sink.flow = "remote_flow";
    remote_sink.x = 1000; remote_sink.y = 500;
    project.flows.push_back({"remote_flow", "Widely spaced chain"});
    project.blocks = {source, sink, remote_source, remote_sink};
    write(root / "design/project.json", write_project(project));
    write(root / "src/handlers.hpp", "#pragma once\n// on_start is ordinary project source.\n");
    write(root / "src/blocks.hpp", "#pragma once\n// source and sink are ordinary project factories.\n");
    const auto source_bytes = read(root / "src/blocks.hpp");
    Session session(root / "design/project.json", root);
    session.activate("editor.preview");
    require(!widget(session.view(), "canvas.surface").spec.pointer_input, "Form preview left the design surface live");
    session.choose("editor.mode", "flows");
    require(widget(session.view(), "canvas.surface").spec.pointer_input,
            "Switching from form preview to flows left block gestures disabled");
    session.activate("editor.zoom.reset");
    const auto origin = center(widget(session.view(), "canvas.block.source").state.bounds);
    session.pointer(origin, gui::PointerKind::press);
    session.pointer({origin.x + 12, origin.y + 18}, gui::PointerKind::move);
    session.pointer({origin.x + 40, origin.y + 60}, gui::PointerKind::move);
    session.pointer({origin.x + 40, origin.y + 60}, gui::PointerKind::release);
    session.activate("editor.save");
    auto saved = saved_project(root);
    require(saved.blocks.front().x == 72 && saved.blocks.front().y == 96,
            "Press/move/release did not move the selected flow block by the pointer delta");
    session.activate("editor.undo"); session.activate("editor.save");
    saved = saved_project(root);
    require(saved.blocks.front().x == source.x && saved.blocks.front().y == source.y &&
            !widget(session.view(), "editor.undo").state.enabled,
            "One drag did not undo as exactly one design edit");
    session.activate("editor.redo"); session.activate("editor.save");
    saved = saved_project(root);
    require(saved.blocks.front().x == 72 && saved.blocks.front().y == 96,
            "Redo did not restore the completed block drag");
    const auto returned_origin = center(widget(session.view(), "canvas.block.source").state.bounds);
    session.pointer(returned_origin, gui::PointerKind::press);
    session.pointer({returned_origin.x + 30, returned_origin.y + 18}, gui::PointerKind::move);
    session.pointer(returned_origin, gui::PointerKind::cancel);
    session.activate("editor.save"); saved = saved_project(root);
    require(saved.blocks.front().x == 72 && saved.blocks.front().y == 96,
            "Cancelling a physical block drag did not restore the original position");
    session.pointer(returned_origin, gui::PointerKind::press);
    session.pointer({returned_origin.x + 18, returned_origin.y + 24}, gui::PointerKind::move);
    session.pointer(returned_origin, gui::PointerKind::move);
    session.pointer(returned_origin, gui::PointerKind::release);
    session.activate("editor.save"); saved = saved_project(root);
    require(saved.blocks.front().x == 72 && saved.blocks.front().y == 96,
            "Dragging away and back to the press point did not restore the initial block position");
    session.activate("editor.undo"); session.activate("editor.save");
    saved = saved_project(root);
    require(saved.blocks.front().x == source.x && saved.blocks.front().y == source.y &&
            !widget(session.view(), "editor.undo").state.enabled,
            "An unchanged return-to-origin drag created an extra history edit");
    session.activate("editor.redo"); session.activate("editor.save"); saved = saved_project(root);
    const auto pending = [&] {
        const auto* cancel = find(session.view(), "editor.connection.cancel");
        return cancel && cancel->state.enabled;
    };
    const auto click_port = [&](gui::Point point, bool expect_success = true) {
        session.pointer(point, gui::PointerKind::press, false);
        session.pointer(point, gui::PointerKind::release, expect_success);
    };
    const auto output = port_position(saved, session, "source", "samples", PortDirection::output);
    const auto input = port_position(saved, session, "sink", "samples", PortDirection::input);
    const auto other_output = port_position(saved, session, "source", "count", PortDirection::output);
    click_port(output);
    require(pending(), "A port press/release did not start a pending connection");
    capture(session.view(), captures, "editor-pending-port");
    require(std::any_of(session.view().key_bindings.begin(), session.view().key_bindings.end(), [](const auto& binding) {
        return binding.key == gui::ShortcutKey::escape && binding.target.id == "editor.connection.cancel";
    }), "Pending wiring did not offer Escape cancellation");
    click_port(other_output, false);
    require(pending() && widget(session.view(), "editor.status").state.font.tone == gui::Tone::error,
            "An invalid destination discarded the selected source port or reported success");
    click_port(input);
    require(!pending(), "A corrected destination left the connection gesture pending");
    session.activate("editor.save"); saved = saved_project(root);
    require(saved.edges.size() == 1 && saved.edges.front().from_block == "source" &&
            saved.edges.front().from_port == "samples" && saved.edges.front().to_block == "sink" &&
            saved.edges.front().to_port == "samples", "Correcting a rejected connection changed its initial source port");
    const auto count_output = port_position(saved, session, "source", "count", PortDirection::output);
    click_port(count_output); require(pending(), "Second wiring gesture did not start");
    click_port(count_output); require(!pending(), "Clicking the pending port again did not cancel wiring");
    click_port(count_output); session.activate("editor.connection.cancel");
    require(!pending(), "Cancel wiring left the selected port pending");
    click_port(count_output);
    require(session.adapter.send(gui::ShortcutEvent{gui::ShortcutKey::escape}) == gui::Delivery::delivered,
            "Escape did not dispatch the pending connection's cancel action");
    session.healthy("Escape cancelled wiring");
    require(!pending(), "Escape left the selected port pending");
    session.activate("editor.save");
    require(saved_project(root).edges.size() == 1, "Cancelling wiring created an edge");
    click_port(count_output); click_port(input, false);
    require(pending(), "A rejected stream type discarded the original port selection");
    const auto count_caption = center(widget(session.view(), "canvas.port.6:source.out.count").state.bounds);
    const auto destination_caption = center(widget(session.view(), "canvas.port.4:sink.in.count").state.bounds);
    session.pointer(count_caption, gui::PointerKind::press, false);
    session.pointer({(count_caption.x + destination_caption.x) / 2,
                     (count_caption.y + destination_caption.y) / 2}, gui::PointerKind::move, false);
    session.pointer(destination_caption, gui::PointerKind::release);
    session.activate("editor.save"); saved = saved_project(root);
    require(!pending() && saved.edges.size() == 2 && saved.edges.back().from_block == "source" &&
            saved.edges.back().from_port == "count" && saved.edges.back().to_block == "sink" &&
            saved.edges.back().to_port == "count", "Dragging between port names did not connect the compatible streams");
    capture(session.view(), captures, "editor-block-gestures");
    const auto all_remote_ports_visible = [&] {
        for (const auto id : {"remote_source", "remote_sink"}) {
            const auto* block_title = find(session.view(), std::string("canvas.block.") + id);
            if (!block_title || block_title->state.bounds.width < 20 || block_title->state.bounds.height < 10) return false;
        }
        for (const auto id : {"samples", "count"}) {
            if (!find(session.view(), std::string("canvas.port.13:remote_source.out.") + id) ||
                !find(session.view(), std::string("canvas.port.11:remote_sink.in.") + id)) return false;
        }
        return true;
    };
    session.choose("editor.document", "remote_flow");
    require(all_remote_ports_visible(), "Selecting a flow did not automatically frame its distant blocks and ports");
    session.activate("editor.zoom.reset");
    require(!find(session.view(), "canvas.block.remote_sink"), "100% reset did not expose the need to fit a wide graph");
    session.activate("editor.zoom.fit");
    require(all_remote_ports_visible(), "Fit did not bring the complete flow back into the canvas");
    capture(session.view(), captures, "editor-fit-flow");
    session.choose("editor.document", "main_flow"); session.activate("editor.zoom.reset");
    session.activate("editor.add"); session.activate("editor.save", false);
    saved = saved_project(root);
    require(saved.blocks.size() == project.blocks.size() + 1, "Add block did not create a new flow block");
    const auto& added = saved.blocks.back();
    Canvas canvas; CanvasOptions options;
    options.mode = CanvasMode::flows; options.document = "main_flow";
    options.viewport = widget(session.view(), "canvas.viewport").state.bounds;
    options.measure_text = [&](const auto& request) { return session.adapter.measure_text(request); };
    (void)canvas.render(saved, options);
    const auto new_bounds = canvas.object_bounds(added.id);
    require(new_bounds.has_value(), "The added block has no canvas geometry");
    for (const auto& block : saved.blocks) {
        if (block.id == added.id || block.flow != added.flow) continue;
        const auto bounds = canvas.object_bounds(block.id);
        require(bounds && !gui::has_area(gui::intersect(*new_bounds, *bounds)),
                "Automatic Add block placement overlaps an existing flow block");
    }
    require(read(root / "src/blocks.hpp") == source_bytes, "Flow gestures rewrote ordinary processing source");
}
void editing_regressions(const std::filesystem::path& root) {
    auto project = empty_project("Editing regressions");
    Form form; form.id = "main"; form.label = "Input";
    Control input; input.id = "input"; input.kind = "text"; input.label = "Input";
    input.multiline = true; input.layout = {24, 24, 280, 64};
    input.event_bindings = {{"text_changed", "text"}, {"submit", "submit"}};
    Control choice; choice.id = "choice"; choice.kind = "choice"; choice.layout = {24, 120, 280, 32};
    choice.options = {{"disabled", "Unavailable", "a", false}, {"enabled", "Available", "b", true}};
    Control punctuated; punctuated.id = "a-b"; punctuated.label = "Hyphen"; punctuated.layout = {24, 180, 120, 32};
    Control underscored; underscored.id = "a_b"; underscored.label = "Underscore"; underscored.layout = {170, 180, 120, 32};
    Control alias_map; alias_map.id = "alias_map"; alias_map.kind = "text"; alias_map.label = "Mapped alias";
    alias_map.layout = {24, 300, 280, 32}; alias_map.event_bindings = {{"edit", "alias.map.binding"}};
    Control alias_legacy; alias_legacy.id = "alias_legacy"; alias_legacy.kind = "text"; alias_legacy.label = "Legacy alias";
    alias_legacy.layout = {24, 360, 280, 32}; alias_legacy.binding = "alias.legacy.binding";
    Control legacy; legacy.id = "legacy"; legacy.label = "Legacy event"; legacy.layout = {24, 240, 160, 32}; legacy.binding = "legacy.binding";
    form.controls = {input, choice, punctuated, underscored, alias_map, alias_legacy, legacy}; project.forms.push_back(form);
    project.bindings = {{"text", "text_changed", "src/text.hpp", "fixture::on_text", "on_text", "src/text.hpp"},
                        {"submit", "submit", "src/submit.hpp", "fixture::on_submit", "on_submit", "src/submit.hpp"},
                        {"legacy.binding", "activate", "src/legacy.hpp", "fixture::on_legacy", "on_legacy", "src/legacy.hpp"},
                        {"alias.map.binding", "text_changed", "src/alias_map.hpp", "fixture::on_map", "on_map", "src/alias_map.hpp"},
                        {"alias.legacy.binding", "change", "src/alias_legacy.hpp", "fixture::on_alias", "on_alias", "src/alias_legacy.hpp"}};
    project.flows.push_back({"main_flow", "Optional ports"});
    Block block; block.id = "optional"; block.flow = "main_flow"; block.label = "Optional ports";
    block.factory = "fixture::make_optional"; block.header = "src/block.hpp"; block.file = block.header;
    block.inputs = {{"in", "float", false}}; block.outputs = {{"out", "int", false}};
    project.blocks.push_back(block);
    write(root / "design/project.json", write_project(project));
    write(root / "src/text.hpp", "#pragma once\n// Ordinary on_text source.\n");
    write(root / "src/submit.hpp", "#pragma once\n// Ordinary on_submit source.\n");
    write(root / "src/legacy.hpp", "#pragma once\n// Ordinary on_legacy default activation source.\n");
    write(root / "src/alias_map.hpp", "#pragma once\n// Original on_map handler bound through the edit alias.\n");
    write(root / "src/alias_legacy.hpp", "#pragma once\n// Original on_alias handler using legacy change event.\n");
    write(root / "src/block.hpp", "#pragma once\n// Ordinary make_optional factory.\n");
    Session session(root / "design/project.json", root);
    session.select("input");
    session.choose("editor.event", "submit");
    session.pointer({234, 154}, gui::PointerKind::double_click);
    require(widget(session.view(), "code.text").state.text == read(root / "src/submit.hpp"),
            "Double-click reset the explicitly chosen nondefault widget event");
    const auto original = read(root / "src/submit.hpp");
    const auto local = original + "// Unsaved source survives a cancelled host close.\n";
    session.edit("code.text", local);
    bool reopen_rejected = false;
    try { session.application->invoke("editor.code"); }
    catch (const std::exception&) { reopen_rejected = true; }
    require(reopen_rejected && widget(session.view(), "code.text").state.text == local,
            "Reopening replaced an unsaved ordinary source buffer");
    require(session.adapter.send(gui::CloseEvent{}) == gui::Delivery::delivered, "Host close was not delivered");
    require(find(session.view(), "unsaved.cancel"), "Dirty source host close omitted the unsaved prompt");
    session.activate("unsaved.cancel");
    require(session.view().modal_root && find(session.view(), "code.text") &&
            widget(session.view(), "code.text").state.text == local,
            "Cancelling host close lost the open dirty source window");
    require(read(root / "src/submit.hpp") == original, "Cancelled host close published unsaved source");
    session.activate("code.discard");
    session.select("alias_map");
    session.pointer({234, 430}, gui::PointerKind::double_click);
    require(widget(session.view(), "code.text").state.text == read(root / "src/alias_map.hpp"),
            "Canonical text event double-click did not reuse an edit-alias event map binding");
    session.activate("code.close");
    session.select("alias_legacy");
    session.pointer({234, 490}, gui::PointerKind::double_click);
    require(widget(session.view(), "code.text").state.text == read(root / "src/alias_legacy.hpp"),
            "Canonical text event double-click did not reuse a legacy change-event binding");
    session.activate("code.close"); session.activate("editor.save");
    require(saved_project(root).bindings.size() == project.bindings.size(),
            "Navigating accepted event aliases created replacement handler bindings");
    session.select("choice");
    session.activate("editor.details");
    session.activate("detail.apply");
    session.choose("editor.mode", "flows");
    session.select("optional");
    session.activate("editor.details");
    session.activate("detail.apply");
    session.activate("editor.save");
    const auto saved = saved_project(root);
    const auto& options = saved.forms.front().controls.at(1).options;
    require(options.size() == 2 && !options.front().enabled && options.back().enabled,
            "Unchanged Details Apply re-enabled a disabled dropdown option");
    require(saved.blocks.front().inputs.size() == 1 && !saved.blocks.front().inputs.front().required &&
            saved.blocks.front().outputs.size() == 1 && !saved.blocks.front().outputs.front().required,
            "Unchanged Details Apply converted project-owned optional ports to required ports");
    session.choose("editor.mode", "forms");
    session.select("a-b"); session.activate("editor.code"); session.activate("code.close");
    session.select("a_b"); session.activate("editor.code"); session.activate("code.close");
    session.activate("editor.save");
    const auto collision = saved_project(root);
    const auto binding_for = [&](std::string_view control_id) -> const Binding& {
        for (const auto& control : collision.forms.front().controls) if (control.id == control_id)
            for (const auto& binding : collision.bindings) if (control.event_bindings.at("activate") == binding.id) return binding;
        throw std::runtime_error("Created ordinary handler has no retained binding");
    };
    const auto& left = binding_for("a-b"); const auto& right = binding_for("a_b");
    require(left.file != right.file && left.symbol != right.symbol &&
            std::filesystem::is_regular_file(root / left.file) && std::filesystem::is_regular_file(root / right.file),
            "Punctuated widget identities collided in ordinary handler filenames or C++ symbols");
    session.select("legacy");
    session.activate("editor.details");
    require(widget(session.view(), "detail.file").state.text == "src/legacy.hpp",
            "Details did not resolve the same-event legacy handler");
    session.activate("detail.apply"); session.activate("editor.save");
    const auto same_event = saved_project(root);
    require(same_event.bindings.size() == collision.bindings.size(), "Same-event Details Apply duplicated a legacy binding");
    const auto legacy_bytes = read(root / "src/legacy.hpp");
    session.choose("editor.event", "pointer");
    session.pointer({234, 370}, gui::PointerKind::double_click);
    require(widget(session.view(), "code.text").state.text != legacy_bytes,
            "Unbound event double-click reopened the unrelated legacy default handler");
    session.activate("code.close"); session.activate("editor.save");
    const auto other_event = saved_project(root);
    const auto& legacy_control = other_event.forms.front().controls.back();
    require(legacy_control.binding == "legacy.binding" && legacy_control.event_bindings.contains("pointer"),
            "New event handler replaced the legacy default event binding");
    const auto new_binding = std::find_if(other_event.bindings.begin(), other_event.bindings.end(), [&](const auto& binding) {
        return binding.id == legacy_control.event_bindings.at("pointer");
    });
    require(new_binding != other_event.bindings.end() && new_binding->event == "pointer" &&
            new_binding->file != "src/legacy.hpp" && read(root / "src/legacy.hpp") == legacy_bytes,
            "New event source is not independent of the retained legacy handler");
}
void path_prompt_regressions(const std::filesystem::path& root, const std::filesystem::path& captures) {
    write(root / "design/project.json", write_project(initial_project()));
    write(root / "src/handlers.hpp", "#pragma once\n// Existing ordinary source.\n");
    const auto before = inventory(root);
    Session session(root / "design/project.json", root);
    session.activate("editor.open");
    require(session.view().modal_root && session.view().modal_root->id == "modal.root" &&
            find(session.view(), "prompt.value") && find(session.view(), "prompt.accept") &&
            find(session.view(), "prompt.cancel"), "Open did not use the editor's same-window prompt");
    require(!session.application->next_service(), "Open queued a native prompt that can block the host window manager");
    capture(session.view(), captures, "editor-open-prompt");
    const auto add_key = widget(session.view(), "editor.add").spec.key;
    require(session.adapter.send(gui::WidgetEvent{add_key, gui::Activate{}}) == gui::Delivery::ignored,
            "Same-window prompt left background project editing active");
    session.activate("prompt.cancel");
    require(!session.view().modal_root && session.objects() == 1 && inventory(root) == before,
            "Cancelling Open changed the current project or source files");
    session.activate("editor.open");
    const auto invalid = (root / "does-not-exist/project.json").string();
    session.edit("prompt.value", invalid);
    session.activate("prompt.accept", false);
    require(find(session.view(), "prompt.value") && widget(session.view(), "prompt.value").state.text == invalid &&
            session.view().modal_root && inventory(root) == before,
            "Invalid Open path closed the prompt, lost its input or changed project files");
    session.activate("prompt.cancel");
    session.activate("editor.new");
    require(find(session.view(), "prompt.value") && !session.application->next_service(),
            "New project did not use the same-window path prompt");
    session.edit("prompt.value", (root / "cancelled-new").string());
    session.activate("prompt.cancel");
    require(session.objects() == 1 && inventory(root) == before && !std::filesystem::exists(root / "cancelled-new"),
            "Cancelling New replaced the open project or created a directory");
    session.activate("editor.open");
    session.edit("prompt.value", root.string());
    session.activate("prompt.accept");
    require(!session.view().modal_root && session.objects() == 1 && inventory(root) == before,
            "Open did not accept a project directory without modifying ordinary files");
    {
        Session unsaved;
        unsaved.activate("editor.save");
        require(find(unsaved.view(), "prompt.value") && !unsaved.application->next_service(),
                "Save-as queued a native path prompt");
        const auto destination = root / "saved-new";
        unsaved.edit("prompt.value", destination.string());
        unsaved.activate("prompt.accept");
        require(!unsaved.view().modal_root && std::filesystem::is_regular_file(destination / "design/project.json"),
                "Same-window Save-as did not persist the new project");
    }
    {
        Session unsaved;
        unsaved.activate("editor.document.new"); unsaved.edit("prompt.value", "Unsaved memory form"); unsaved.activate("prompt.accept");
        unsaved.activate("editor.open"); unsaved.activate("unsaved.save");
        const auto destination = root / "saved-before-open";
        unsaved.edit("prompt.value", destination.string()); unsaved.activate("prompt.accept");
        require(find(unsaved.view(), "prompt.value") && !unsaved.application->next_service() &&
                std::filesystem::is_regular_file(destination / "design/project.json"),
                "Saving an unsaved design did not resume its pending Open prompt");
        unsaved.edit("prompt.value", root.string()); unsaved.activate("prompt.accept");
        require(!unsaved.view().modal_root && unsaved.objects() == 1 &&
                widget(unsaved.view(), "editor.document").state.selected == "main" &&
                saved_project(destination).forms.front().label == "Unsaved memory form",
                "Resumed Open prompt lost its action or failed to retain the saved memory form");
    }
}
void document_name_regressions(const std::filesystem::path& root, const std::filesystem::path& captures) {
    auto project = initial_project();
    Block source; source.id = "source"; source.label = "Source"; source.flow = "main_flow";
    source.factory = "fixture::source"; source.header = "src/blocks.hpp"; source.file = source.header;
    source.outputs = {{"out", "float", true}};
    Block sink; sink.id = "sink"; sink.label = "Sink"; sink.flow = "main_flow";
    sink.factory = "fixture::sink"; sink.header = "src/blocks.hpp"; sink.file = sink.header;
    sink.inputs = {{"in", "float", true}};
    project.blocks = {source, sink}; project.edges.push_back({"samples", "source", "out", "sink", "in", 16, 0});
    write(root / "design/project.json", write_project(project));
    write(root / "src/handlers.hpp", "#pragma once\n// on_start remains ordinary source.\n");
    write(root / "src/blocks.hpp", "#pragma once\n// source and sink remain ordinary source.\n");
    const auto handler_bytes = read(root / "src/handlers.hpp");
    const auto block_bytes = read(root / "src/blocks.hpp");
    std::string new_form_id, new_flow_id;
    {
        Session session(root / "design/project.json", root);
        session.activate("editor.document.new");
        require(widget(session.view(), "prompt.value").state.text == "New form" && !session.application->next_service(),
                "New form omitted its editable name prompt");
        session.activate("prompt.cancel");
        require(widget(session.view(), "editor.document").state.options.size() == 1,
                "Cancelled form-name prompt created a form");
        session.activate("editor.document.new");
        session.edit("prompt.value", "  "); session.activate("prompt.accept", false);
        require(find(session.view(), "prompt.value") && widget(session.view(), "prompt.value").state.text == "  " &&
                widget(session.view(), "editor.document").state.options.size() == 1,
                "Empty form name closed the prompt, lost input or created a form");
        session.send("prompt.value", gui::EditText{"Device settings", "  "}, false);
        session.send("prompt.value", gui::SubmitText{});
        new_form_id = widget(session.view(), "editor.document").state.selected.value_or("");
        require(!new_form_id.empty() && new_form_id != "main" && session.objects() == 0,
                "Named form creation did not select a new stable identity");
        session.activate("editor.undo");
        require(widget(session.view(), "editor.document").state.options.size() == 1 &&
                widget(session.view(), "editor.document").state.selected == "main",
                "Undo of form creation did not restore a valid selected document");
        session.activate("editor.redo"); session.choose("editor.document", new_form_id);
        session.activate("editor.document.rename");
        require(widget(session.view(), "prompt.value").state.text == "Device settings",
                "Rename form did not prefill the selected form's name");
        capture(session.view(), captures, "editor-name-prompt");
        session.edit("prompt.value", "Device controls"); session.activate("prompt.accept");
        require(widget(session.view(), "editor.document").state.selected == new_form_id,
                "Renaming a form changed its stable identity");
        session.activate("editor.undo"); session.activate("editor.document.rename");
        require(widget(session.view(), "prompt.value").state.text == "Device settings", "Undo did not restore the form name");
        session.activate("prompt.cancel"); session.activate("editor.redo");
        session.activate("editor.document.rename");
        require(widget(session.view(), "prompt.value").state.text == "Device controls", "Redo did not restore the form name");
        session.activate("prompt.cancel");
        session.choose("editor.document", "main"); session.activate("editor.document.rename");
        session.edit("prompt.value", "Primary controls"); session.activate("prompt.accept");
        session.choose("editor.mode", "flows");
        session.activate("editor.document.new");
        require(widget(session.view(), "prompt.value").state.text == "New flow", "New flow omitted its editable name prompt");
        session.edit("prompt.value", "Capture processing"); session.activate("prompt.accept");
        new_flow_id = widget(session.view(), "editor.document").state.selected.value_or("");
        require(!new_flow_id.empty() && new_flow_id != "main_flow", "Named flow creation did not select a stable identity");
        session.activate("editor.undo");
        require(widget(session.view(), "editor.document").state.options.size() == 1 &&
                widget(session.view(), "editor.document").state.selected == "main_flow",
                "Undo of flow creation did not restore a valid selected document");
        session.activate("editor.redo"); session.choose("editor.document", new_flow_id);
        session.activate("editor.document.rename"); session.edit("prompt.value", "Filtered capture"); session.activate("prompt.accept");
        session.activate("editor.undo"); session.activate("editor.document.rename");
        require(widget(session.view(), "prompt.value").state.text == "Capture processing", "Undo did not restore the flow name");
        session.activate("prompt.cancel"); session.activate("editor.redo");
        session.activate("editor.document.rename");
        require(widget(session.view(), "prompt.value").state.text == "Filtered capture" &&
                widget(session.view(), "editor.document").state.selected == new_flow_id,
                "Redo lost the renamed flow or its stable identity");
        session.activate("prompt.cancel");
        session.choose("editor.document", "main_flow"); session.activate("editor.document.rename");
        session.edit("prompt.value", "Main sample processing"); session.activate("prompt.accept");
        require(session.objects() == 3, "Renaming a populated flow lost its blocks or edge");
        session.activate("editor.save");
    }
    const auto saved = saved_project(root);
    require(saved.forms.size() == 2 && saved.forms.at(0).id == "main" && saved.forms.at(0).label == "Primary controls" &&
            saved.forms.at(0).controls.at(0).id == "start" && saved.forms.at(0).controls.at(0).binding == "on_start" &&
            saved.bindings.at(0).file == "src/handlers.hpp" && saved.forms.at(1).id == new_form_id &&
            saved.forms.at(1).label == "Device controls", "Saving renamed forms changed control/binding identities or lost names");
    require(saved.flows.size() == 2 && saved.flows.at(0).id == "main_flow" && saved.flows.at(0).label == "Main sample processing" &&
            saved.flows.at(1).id == new_flow_id && saved.flows.at(1).label == "Filtered capture" &&
            saved.blocks.size() == 2 && saved.blocks.at(0).flow == "main_flow" && saved.blocks.at(1).flow == "main_flow" &&
            saved.edges.size() == 1 && saved.edges.at(0).id == "samples" && saved.edges.at(0).from_block == "source" &&
            saved.edges.at(0).to_block == "sink", "Saving renamed flows changed graph identities or lost names");
    require(read(root / "src/handlers.hpp") == handler_bytes && read(root / "src/blocks.hpp") == block_bytes,
            "Document naming rewrote ordinary source files");
    Session reloaded(root / "design/project.json", root);
    reloaded.choose("editor.document", new_form_id); reloaded.activate("editor.document.rename");
    require(widget(reloaded.view(), "prompt.value").state.text == "Device controls", "Reload lost a named form");
    reloaded.activate("prompt.cancel"); reloaded.choose("editor.mode", "flows");
    reloaded.choose("editor.document", new_flow_id); reloaded.activate("editor.document.rename");
    require(widget(reloaded.view(), "prompt.value").state.text == "Filtered capture", "Reload lost a named flow");
    reloaded.activate("prompt.cancel");
}
void small_action_regressions(const std::filesystem::path& root, const std::filesystem::path& captures) {
    write(root / "design/project.json", write_project(initial_project()));
    const std::string source = "void alpha(void) {}\nvoid beta(void) {}\n";
    write(root / "src/helpers.c", source);
    write(root / "src/handlers.hpp", "#pragma once\n// Ordinary on_start source.\n");
    Session session(root / "design/project.json", root);
    require(!find(session.view(), "editor.properties.details"),
            "Contextual Details appeared without an editable selection");
    session.select("start");
    session.edit("property.label", "Capture"); session.submit("property.label");
    require(widget(session.view(), "canvas.control.start").state.text == "Capture",
            "Enter in Label did not apply the selected widget's label");
    session.edit("property.position", "40, 56"); session.submit("property.position");
    session.edit("property.size", "150, 44"); session.submit("property.size");
    session.activate("editor.save");
    auto saved = saved_project(root);
    require(saved.forms.front().controls.front().label == "Capture" &&
            saved.forms.front().controls.front().layout == Rect{40, 56, 150, 44},
            "Enter did not retain the selected widget's position or size");
    const auto before = inventory(root);
    const auto label_bounds = widget(session.view(), "canvas.control.start").state.bounds;
    session.edit("property.label", "Pending label");
    session.edit("property.position", "not a coordinate");
    session.submit("property.position", false);
    require(widget(session.view(), "property.position").state.text == "not a coordinate" &&
            widget(session.view(), "property.label").state.text == "Pending label" &&
            widget(session.view(), "canvas.control.start").state.text == "Capture" &&
            widget(session.view(), "canvas.control.start").state.bounds == label_bounds && inventory(root) == before,
            "Invalid Enter submission lost property text, changed the widget or wrote files");
    session.send("property.position", gui::EditText{"60, 72", "not a coordinate"}, false);
    session.send("property.size", gui::EditText{"2, 44", "150, 44"}, false);
    session.submit("property.size", false);
    require(widget(session.view(), "property.size").state.text == "2, 44" &&
            widget(session.view(), "canvas.control.start").state.text == "Capture" &&
            widget(session.view(), "canvas.control.start").state.bounds == label_bounds && inventory(root) == before,
            "Rejected widget size partially applied the label or position");
    session.send("property.size", gui::EditText{"160, 48", "2, 44"}, false);
    session.submit("property.size");
    session.activate("editor.properties.details");
    require(find(session.view(), "detail.options") &&
            widget(session.view(), "detail.file").state.text == "src/handlers.hpp",
            "Contextual Details did not open the selected widget's ordinary bindings and options");
    session.activate("detail.cancel"); capture(session.view(), captures, "editor-properties");
    session.activate("editor.save"); saved = saved_project(root);
    require(saved.forms.front().controls.front().label == "Pending label" &&
            saved.forms.front().controls.front().layout == Rect{60, 72, 160, 48},
            "Correcting rejected properties did not complete Enter submission");
    session.choose("editor.mode", "flows");
    require(widget(session.view(), "editor.help").state.text.find("Add block") != std::string::npos,
            "Empty flow instructions did not explain the next editing action");
    session.activate("editor.add");
    session.edit("property.label", "Ordinary source"); session.submit("property.label");
    session.edit("property.position", "80, 100"); session.submit("property.position");
    session.activate("editor.properties.details");
    require(find(session.view(), "detail.inputs") && find(session.view(), "detail.outputs") &&
            find(session.view(), "detail.anchor"), "Contextual block Details omitted ports or ordinary source navigation");
    session.activate("detail.cancel");
    session.choose("editor.mode", "files");
    session.select("src/helpers.c");
    require(widget(session.view(), "file.path").state.text == "src/helpers.c" && !session.view().modal_root,
            "Selecting an ordinary file did not fill its path without opening a source window");
    capture(session.view(), captures, "editor-files");
    const auto files_before = inventory(root);
    session.edit("file.path", "src/missing.c"); session.submit("file.path", false);
    require(widget(session.view(), "file.path").state.text == "src/missing.c" && !session.view().modal_root &&
            inventory(root) == files_before, "Invalid file Enter submission lost input or modified the project");
    session.send("file.path", gui::EditText{"src/helpers.c", "src/missing.c"}, false);
    session.submit("file.path");
    require(widget(session.view(), "code.text").state.text == source && inventory(root) == files_before,
            "Enter did not open the ordinary C file without modifying source");
    session.edit("code.find", "beta"); session.submit("code.find");
    const auto& code_widget = widget(session.view(), "code.text");
    const auto selection = session.adapter.text_selection(code_widget.spec.key);
    const auto match = source.find("beta");
    require(selection.anchor == match && selection.caret == match + 4,
            "Enter in Find did not select the source match");
    require(std::any_of(session.view().key_bindings.begin(), session.view().key_bindings.end(), [](const auto& binding) {
        return binding.key == gui::ShortcutKey::f3 && binding.target.id == "code.save";
    }), "The source window omitted its F3 Save shortcut");
    const auto design_bytes = read(root / "design/project.json");
    const auto amended = source + "// Saved through the source window's F3 shortcut.\n";
    session.edit("code.text", amended);
    require(session.adapter.send(gui::ShortcutEvent{gui::ShortcutKey::f3}) == gui::Delivery::delivered,
            "F3 source Save was not delivered through the shared shortcut contract");
    session.healthy("F3 source Save");
    require(read(root / "src/helpers.c") == amended && read(root / "design/project.json") == design_bytes,
            "F3 did not save the ordinary source independently of unsaved flow edits");
    session.activate("code.close");
    require(read(root / "src/helpers.c") == amended, "Closing the source window lost its explicitly saved C file");
}
void first_use_regressions(const std::filesystem::path& root, const std::filesystem::path& captures) {
    {
        Session unopened;
        const auto& help = widget(unopened.view(), "editor.help").state.text;
        require(help.find("Choose New") != std::string::npos && help.find("Examples") != std::string::npos &&
                !widget(unopened.view(), "editor.add").state.enabled,
                "Editor startup omitted the first-use project or example instructions");
        capture(unopened.view(), captures, "editor-first-use");
    }
    write(root / "design/project.json", write_project(empty_project("Empty project")));
    Session session(root / "design/project.json", root);
    require(widget(session.view(), "editor.help").state.text.find("New form") != std::string::npos &&
            !widget(session.view(), "editor.add").state.enabled,
            "Project without forms omitted the first-use New form instructions");
    session.activate("editor.document.new"); session.edit("prompt.value", "First form"); session.submit("prompt.value");
    require(widget(session.view(), "editor.help").state.text.find("Add widget") != std::string::npos &&
            widget(session.view(), "editor.add").state.enabled,
            "Empty form instructions did not explain adding its first widget");
    capture(session.view(), captures, "editor-empty-form");
    session.activate("editor.add");
    require(widget(session.view(), "editor.help").state.text.find("Drag") != std::string::npos,
            "Populated form retained first-use instructions instead of editing gestures");
    session.choose("editor.mode", "flows");
    require(widget(session.view(), "editor.help").state.text.find("New flow") != std::string::npos &&
            !widget(session.view(), "editor.add").state.enabled,
            "Project without flows omitted the first-use New flow instructions");
    session.activate("editor.document.new"); session.edit("prompt.value", "First flow"); session.submit("prompt.value");
    require(widget(session.view(), "editor.help").state.text.find("Add block") != std::string::npos &&
            widget(session.view(), "editor.add").state.enabled,
            "Empty flow instructions did not explain adding its first block");
    session.activate("editor.add");
    require(widget(session.view(), "editor.help").state.text.find("Drag") != std::string::npos,
            "Populated flow retained first-use instructions instead of editing gestures");
}
void example_regressions(const std::filesystem::path& root, const std::filesystem::path& captures) {
    // Discovery must work when the editor is launched outside the repository,
    // using its executable's ancestors rather than the process working directory.
    const auto original_examples = std::filesystem::path(__FILE__).parent_path().parent_path() / "examples";
    const auto bundle = root / "bundle";
    const auto demo = bundle / "editor/examples/demo";
    std::filesystem::create_directories(demo.parent_path());
    for (const auto name : {"demo", "simple", "simple-c", "rust-dsp"})
        std::filesystem::copy(original_examples / name, demo.parent_path() / name,
                              std::filesystem::copy_options::recursive);
    const auto executable = bundle / "build/editor-fixture/foundation-editor-fixture";
    write(executable, "Executable location fixture.\n");
    const auto current = root / "unrelated-project";
    write(current / "design/project.json", write_project(initial_project()));
    write(current / "src/handlers.hpp", "#pragma once\n// Existing on_start current-project handler.\n");
    const auto original = inventory(root);
    WorkingDirectory outside_repository(current);
    Session session(current / "design/project.json", current, executable);
    session.activate("editor.add"); const auto dirty_objects = session.objects();
    session.activate("editor.example");
    require(find(session.view(), "unsaved.cancel"), "Example bypassed the current design's unsaved-changes prompt");
    session.activate("unsaved.cancel");
    require(session.objects() == dirty_objects && inventory(root) == original, "Cancelling Example lost unsaved project work");
    session.activate("editor.example"); session.activate("unsaved.discard");
    require(find(session.view(), "example.cancel"), "Discard did not continue to the pending example picker");
    session.activate("example.cancel");
    require(session.objects() == dirty_objects && inventory(root) == original,
            "Cancelling the continued picker changed the uncommitted design or ordinary files");
    session.activate("editor.open");
    require(find(session.view(), "unsaved.cancel"),
            "Cancelling the continued picker incorrectly marked the retained design as saved");
    session.activate("unsaved.cancel");
    session.activate("editor.undo"); session.select("start"); session.activate("editor.code");
    const auto source = widget(session.view(), "code.text").state.text;
    session.edit("code.text", source + "// Unsaved ordinary code.\n");
    session.application->invoke("editor.example");
    // Ordinary generated handlers invoke actions inside handle(). This direct
    // facade probe needs a harmless host event to publish the changed snapshot.
    require(session.adapter.send(gui::ResizeEvent{session.view().client_size, session.view().display_scale}) == gui::Delivery::delivered,
            "Example facade probe could not present the unsaved prompt");
    session.healthy("Example requested from an open source buffer");
    require(find(session.view(), "unsaved.cancel"), "Example bypassed dirty ordinary source");
    session.activate("unsaved.cancel");
    require(find(session.view(), "code.text") && widget(session.view(), "code.text").state.text == source + "// Unsaved ordinary code.\n",
            "Cancelling Example discarded the ordinary source buffer");
    session.activate("code.discard");
    session.activate("editor.example");
    require(session.view().modal_root && find(session.view(), "example.simple") && find(session.view(), "example.c") &&
            find(session.view(), "example.rust") && find(session.view(), "example.demo"),
            "Example did not offer the simple C/C++, Rust DSP and advanced MIMO designs");
    capture(session.view(), captures, "editor-example-picker");
    session.activate("example.cancel");
    require(!session.view().modal_root && session.objects() == 1 && inventory(root) == original,
            "Cancelling the example picker changed the current project or ordinary files");
    session.activate("editor.example"); session.activate("example.demo");
    const auto demo_project = parse_project(read(demo / "project.json"));
    require(bool(demo_project) && !demo_project.project->forms.empty() && !demo_project.project->flows.empty(),
            "Retained example omits a form or flow");
    const auto& form = demo_project.project->forms.front();
    require(widget(session.view(), "editor.mode").state.selected == "forms" &&
            widget(session.view(), "editor.document").state.selected == form.id && session.objects() == form.controls.size(),
            "Example did not open its form through the normal editor workspace");
    capture(session.view(), captures, "editor-example-form");
    const auto bound = std::find_if(form.controls.begin(), form.controls.end(), [](const auto& control) { return !control.binding.empty(); });
    require(bound != form.controls.end(), "Example form has no ordinary event binding");
    const auto binding = std::find_if(demo_project.project->bindings.begin(), demo_project.project->bindings.end(),
        [&](const auto& value) { return value.id == bound->binding; });
    require(binding != demo_project.project->bindings.end(), "Example event has no source reference");
    session.select(bound->id); session.activate("editor.code");
    require(widget(session.view(), "code.text").state.text == read(demo / binding->file), "Example event did not open ordinary source");
    session.activate("code.close"); session.choose("editor.mode", "flows");
    const auto& flow = demo_project.project->flows.front();
    require(widget(session.view(), "editor.document").state.selected == flow.id && session.objects() >= 3,
            "Example did not expose an editable connected flow");
    capture(session.view(), captures, "editor-example-flow");
    const auto block = std::find_if(demo_project.project->blocks.begin(), demo_project.project->blocks.end(),
        [&](const auto& value) { return value.flow == flow.id && !value.file.empty(); });
    require(block != demo_project.project->blocks.end(), "Example flow has no ordinary processing source");
    session.select(block->id); session.activate("editor.code");
    require(widget(session.view(), "code.text").state.text == read(demo / block->file), "Example block did not open ordinary processing source");
    session.activate("code.close");
    session.activate("editor.example"); session.activate("example.simple");
    require(widget(session.view(), "editor.mode").state.selected == "forms" &&
            widget(session.view(), "editor.document").state.selected == "simple.controls",
            "Simple C++ example did not begin with its form controls");
    capture(session.view(), captures, "editor-simple-form");
    session.select("simple.run"); session.activate("editor.code");
    require(widget(session.view(), "code.text").state.text == read(demo.parent_path() / "simple/events.cpp"),
            "Simple C++ form did not open its ordinary event source");
    session.activate("code.close"); session.choose("editor.mode", "flows");
    require(widget(session.view(), "editor.document").state.selected == "simple.processing",
            "Simple C++ example did not expose its ordinary signal-processing flow");
    session.select("simple.gain"); session.activate("editor.details");
    require(widget(session.view(), "detail.anchor").state.text == "starter::apply_gain" &&
            widget(session.view(), "detail.symbol").state.text == "starter::make_gain",
            "Block Details conflated the ordinary source function with its flow factory");
    session.activate("detail.apply"); session.activate("editor.code");
    require(widget(session.view(), "code.text").state.text == read(demo.parent_path() / "simple/signal.cpp") &&
            widget(session.view(), "code.find").state.text == "apply_gain",
            "Unchanged Details Apply lost navigation to the simple processing function");
    session.activate("code.close"); capture(session.view(), captures, "editor-simple-flow");
    session.activate("editor.example"); session.activate("example.c");
    const auto c_root = demo.parent_path() / "simple-c";
    require(widget(session.view(), "editor.mode").state.selected == "forms" &&
            widget(session.view(), "editor.document").state.selected == "simple_c.controls",
            "Simple C example did not begin with its shared form controls");
    session.select("simple_c.run"); session.activate("editor.properties.details");
    require(widget(session.view(), "detail.file").state.text == "events.c" &&
            widget(session.view(), "detail.header").state.text == "event_adapter.hpp" &&
            widget(session.view(), "detail.symbol").state.text == "c_starter::on_run",
            "C widget did not retain an ordinary C file with its C++ boundary declaration");
    session.activate("detail.apply"); session.activate("editor.code");
    require(widget(session.view(), "code.text").state.text == read(c_root / "events.c") &&
            widget(session.view(), "code.find").state.text == "simple_c_on_run",
            "Unchanged widget Details lost navigation to its ordinary C event function");
    capture(session.view(), captures, "editor-c-event-source");
    session.activate("code.close"); session.choose("editor.mode", "flows");
    require(widget(session.view(), "editor.document").state.selected == "simple_c.processing",
            "Simple C example did not expose its shared processing flow");
    session.select("simple_c.gain"); session.activate("editor.properties.details");
    require(widget(session.view(), "detail.anchor").state.text == "simple_c_apply_gain" &&
            widget(session.view(), "detail.file").state.text == "signal.c" &&
            widget(session.view(), "detail.header").state.text == "flow_adapter.hpp" &&
            widget(session.view(), "detail.symbol").state.text == "c_starter::make_gain",
            "C block did not retain separate ordinary C navigation and C++ flow factory references");
    session.activate("detail.apply"); session.activate("editor.code");
    require(widget(session.view(), "code.text").state.text == read(c_root / "signal.c") &&
            widget(session.view(), "code.find").state.text == "simple_c_apply_gain",
            "Unchanged block Details lost navigation to its ordinary C signal function");
    capture(session.view(), captures, "editor-c-signal-source");
    session.activate("code.close"); capture(session.view(), captures, "editor-c-flow");
    session.activate("editor.example"); session.activate("example.rust");
    require(widget(session.view(), "editor.mode").state.selected == "flows" &&
            widget(session.view(), "editor.document").state.selected == "rust-dsp.processing",
            "Rust DSP example did not open its flow when no form exists");
    session.select("rust-dsp.filter"); session.activate("editor.details");
    require(widget(session.view(), "detail.anchor").state.text == "process_samples" &&
            widget(session.view(), "detail.file").state.text == "dsp.rs" &&
            widget(session.view(), "detail.symbol").state.text == "foundation::editor::rust_dsp::make_filter",
            "Rust block did not retain distinct source navigation and C++ factory references");
    session.activate("detail.apply"); session.activate("editor.code");
    require(widget(session.view(), "code.text").state.text == read(demo.parent_path() / "rust-dsp/dsp.rs") &&
            widget(session.view(), "code.find").state.text == "process_samples",
            "Rust processing block did not navigate to its ordinary Rust algorithm");
    capture(session.view(), captures, "editor-rust-source");
    session.activate("code.close"); capture(session.view(), captures, "editor-rust-flow");
    {
        const auto rust_root = demo.parent_path() / "rust-dsp";
        Session launched(rust_root / "project.json", rust_root, executable);
        require(widget(launched.view(), "editor.mode").state.selected == "flows" &&
                widget(launched.view(), "editor.document").state.selected == "rust-dsp.processing" && launched.objects() >= 3,
                "Launching a flow-only project left the initial Forms workspace empty");
    }
    require(inventory(root) == original, "Opening the Example or its source wrote files or ran a project recipe");
}
#if defined(__linux__)
template<class Predicate> void await(Session& session, Predicate&& finished) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (std::chrono::steady_clock::now() < deadline) {
        session.application->tick();
        if (finished()) return;
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    throw std::runtime_error("Editor recipe did not reach its expected result within five seconds");
}
void recipe_regressions(const std::filesystem::path& root, const std::filesystem::path& executable) {
    auto project = initial_project();
    project.recipes = {{"build", "Build", {executable.string(), "--recipe-child", "build.cwd"}, "."},
                       {"run", "Run", {executable.string(), "--recipe-child", "run.cwd"}, "nested"}};
    write(root / "design/project.json", write_project(project));
    write(root / "src/handlers.hpp", "#pragma once\n// on_start fixture.\n");
    std::filesystem::create_directory(root / "nested");
    {
        Session session(root / "design/project.json", root);
        session.activate("editor.build");
        await(session, [&] { return !widget(session.view(), "editor.stop").state.enabled; });
        session.healthy("Build recipe completed");
        require(read(root / "build.cwd") == root.generic_string() + "\n", "Build recipe did not use the project-root working directory");
        require(!std::filesystem::exists(root / "nested/run.cwd"), "Build command unexpectedly ran the application recipe");
        std::filesystem::remove(root / "build.cwd");
        session.activate("editor.run");
        await(session, [&] {
            return std::filesystem::exists(root / "nested/run.cwd") && !widget(session.view(), "editor.stop").state.enabled;
        });
        session.healthy("Build-and-run recipes completed");
        require(read(root / "build.cwd") == root.generic_string() + "\n", "Run command omitted its preceding project-root build");
        require(read(root / "nested/run.cwd") == (root / "nested").generic_string() + "\n", "Run recipe did not use its nested working directory");
    }
    project.recipes.front().argv = {"no-such-foundation-editor-fixture-executable"};
    write(root / "design/project.json", write_project(project));
    std::filesystem::remove(root / "nested/run.cwd");
    Session failure(root / "design/project.json", root);
    failure.activate("editor.run", false);
    await(failure, [&] { return widget(failure.view(), "editor.status").state.font.tone == gui::Tone::error; });
    require(!widget(failure.view(), "editor.stop").state.enabled, "Failed executable left the editor's owned process running");
    require(!std::filesystem::exists(root / "nested/run.cwd"), "Failed build still launched the run recipe");
}
#endif
void smoke_without_writes(const std::filesystem::path& root) {
    configure_launch(root / "design/project.json", root);
    const auto before = inventory(root);
    foundation::host::FramebufferHost<Application> host;
    unsigned presentations = 0;
    host.application().qualify([&] {
        host.application().tick();
        const auto frame = host.adapter().frame();
        require(frame.pixels && frame.width && frame.height, "Generic framebuffer host presented no editor pixels");
        ++presentations;
    });
    require(presentations >= 6, "Native editor smoke omitted toolbar interactions");
    require(!host.application().presentation_pending(), "Native smoke has a failed editor presentation");
    require(inventory(root) == before, "Native editor smoke wrote to the opened project");
}
}
int main(int argc, char** argv) {
#if defined(__linux__)
    if (argc == 3 && std::string_view(argv[1]) == "--recipe-child") {
        write(std::filesystem::current_path() / argv[2], std::filesystem::current_path().generic_string() + "\n");
        std::cout << "Fast recipe completed\n";
        return 0;
    }
#endif
    try {
        std::filesystem::path captures;
        if (argc == 3 && std::string_view(argv[1]) == "--capture-dir") captures = std::filesystem::absolute(argv[2]);
        else require(argc == 1, "Usage: foundation-editor-application_test [--capture-dir PATH]");
        Temporary temporary;
        const auto root = temporary.root;
        write(root / "design/project.json", write_project(initial_project()));
        write(root / "src/handlers.hpp", "#pragma once\nnamespace fixture { void on_start(); }\n");
        write(root / "src/bridge.rs", "#[no_mangle]\npub extern \"C\" fn fixture_value() -> i32 { 7 }\n");
        {
            Session session(root / "design/project.json", root);
            source_and_forms(session, root, captures);
            flows(session, root, captures);
        }
        smoke_without_writes(root);
        editing_regressions(root / "editing-regressions");
        path_prompt_regressions(root / "path-prompt-regressions", captures);
        document_name_regressions(root / "document-name-regressions", captures);
        small_action_regressions(root / "small-action-regressions", captures);
        first_use_regressions(root / "first-use-regressions", captures);
        gesture_regressions(root / "gesture-regressions", captures);
        example_regressions(root / "example-regressions", captures);
#if defined(__linux__)
        recipe_regressions(root / "recipe-regressions", std::filesystem::canonical(argv[0]));
#endif
        std::cout << "editor application: shell, same-window prompts, document names, first-use hints, Enter actions, contextual Details, example picker, C/C++/Rust source navigation, block dragging, port wiring, fitted flows, generated dispatch, forms, ordinary source, conflicts, arbitrary MIMO, preview, native smoke: ok\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
