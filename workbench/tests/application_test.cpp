#include "workbench/ui/application.hpp"
#include "workbench/ui/flow_view.hpp"
#include "workbench/core/pseudocode.hpp"
#include "workbench/core/preferences.hpp"
#include "workbench/core/credentials.hpp"
#include "workbench/core/workspace.hpp"
#include <gui/framebuffer.hpp>
#include <gui/presentation.hpp>
#include <gui/memory_adapter.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <utility>
#include <vector>

using namespace tinyenv;

namespace {
void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}
void near(double actual, double expected, std::string_view message) {
    require(std::abs(actual - expected) < 1e-7, message);
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
    require(bool(stream), "Cannot write fixture " + path.string());
}
struct Temporary {
    std::filesystem::path root = std::filesystem::temp_directory_path() /
        ("tinyenv application fixture " +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    Temporary() { require(std::filesystem::create_directory(root), "Fixture directory collision"); }
    ~Temporary() {
        configure_launch();
        std::error_code error;
        std::filesystem::remove_all(root, error);
    }
};
std::map<std::string, std::string> inventory(const std::filesystem::path& root) {
    std::map<std::string, std::string> result;
    if (!std::filesystem::exists(root)) return result;
    for (const auto& entry : std::filesystem::recursive_directory_iterator(root))
        if (entry.is_regular_file())
            result.emplace(entry.path().lexically_relative(root).generic_string(), read(entry.path()));
    return result;
}
const gui::Widget* find(const gui::Snapshot& snapshot, std::string_view id) {
    const auto item = std::find_if(snapshot.widgets.begin(), snapshot.widgets.end(),
        [&](const auto& widget) { return widget.spec.key.id == id; });
    return item == snapshot.widgets.end() ? nullptr : &*item;
}
const gui::Widget& widget(const gui::Snapshot& snapshot, std::string_view id) {
    const auto* value = find(snapshot, id);
    if (!value) throw std::runtime_error("Missing workbench control " + std::string(id));
    return *value;
}
gui::Point center(gui::Rect bounds) {
    return {bounds.x + bounds.width / 2, bounds.y + bounds.height / 2};
}
bool fully_visible(const gui::Availability& area) {
    constexpr double tolerance = 1e-7;
    return area.visible && area.clip.x <= area.bounds.x + tolerance &&
        area.clip.y <= area.bounds.y + tolerance &&
        area.clip.x + area.clip.width + tolerance >= area.bounds.x + area.bounds.width &&
        area.clip.y + area.clip.height + tolerance >= area.bounds.y + area.bounds.height;
}
bool record(const gui::Widget& list, std::string_view id) {
    return std::any_of(list.state.records.begin(), list.state.records.end(),
        [&](const auto& item) { return item.id == id; });
}
bool option(const gui::Widget& choice, std::string_view id) {
    return std::any_of(choice.state.options.begin(), choice.state.options.end(),
        [&](const auto& item) { return item.id == id; });
}
void capture(const gui::Snapshot& snapshot, const std::filesystem::path& directory,
             std::string_view name) {
    if (directory.empty()) return;
    std::filesystem::create_directories(directory);
    gui::FramebufferAdapter adapter;
    adapter.present(snapshot);
    const auto image = adapter.frame();
    require(image.pixels && image.width && image.height, "Workbench capture contains no frame");
    std::ofstream stream(directory / (std::string(name) + ".ppm"), std::ios::binary);
    stream << "P6\n" << image.width << ' ' << image.height << "\n255\n";
    for (unsigned y = 0; y < image.height; ++y)
        stream.write(reinterpret_cast<const char*>(image.pixels->data() + y * image.stride_bytes),
                     static_cast<std::streamsize>(image.width * 3));
    require(bool(stream), "Workbench capture could not be saved");
}
struct Session {
    gui::FramebufferAdapter metrics;
    gui::MemoryAdapter adapter{[this](const gui::Event& event) { application->handle(event); },
                              64 * 1024 * 1024,
                              [this](const gui::TextMeasureRequest& request) {
                                  return metrics.measure_text(request);
                              }};
    std::unique_ptr<Application> application;
    explicit Session(const std::filesystem::path& root, const std::filesystem::path& chat = {},
                     const std::filesystem::path& config_directory = {}, bool expected_success = true,
                     const std::filesystem::path& runtime_path = {}) {
        configure_launch(root, chat, {}, config_directory.empty() ? root / ".preferences" : config_directory,
                         runtime_path);
        application = std::make_unique<Application>(adapter);
        presented("initial presentation");
        if(expected_success)success("initial presentation");
    }
    const gui::Snapshot& view() const { return application->view(); }
    std::string text(std::string_view id) const {
        if (id == "wb.chat.text") return std::string(application->chat_text());
        return widget(view(), id).state.text;
    }
    std::string rendered_text(std::string_view id = "wb.chat.rendered") const {
        std::string out;
        const auto prefix = std::string(id) + ".block.";
        for (const auto& item : view().widgets)
            if (item.spec.key.id.starts_with(prefix)) out += item.state.text + '\n';
        return out;
    }
    void presented(std::string_view step) const {
        require(!application->presentation_pending(), std::string(step) + ": presentation pending; " +
                (find(view(),"wb.status")?widget(view(),"wb.status").state.text:std::string("no status")));
        require(adapter.snapshot().revision == view().revision,
                std::string(step) + ": adapter has an obsolete snapshot");
        std::set<std::string> ids;
        for (const auto& item : view().widgets)
            require(ids.insert(item.spec.key.id).second,
                    std::string(step) + ": duplicate widget " + item.spec.key.id);
    }
    void success(std::string_view step) const {
        const auto& status = widget(view(), "wb.status");
        require(status.state.font.tone != gui::Tone::error,
                std::string(step) + ": " + status.state.text);
    }
    void error(std::string_view fragment) const {
        const auto& status = widget(view(), "wb.status");
        require(status.state.font.tone == gui::Tone::error,
                "Expected a visible workbench error containing " + std::string(fragment) + "; got: " + status.state.text);
        require(status.state.text.find(fragment) != std::string::npos,
                "Unexpected workbench error: " + status.state.text);
    }
    void reveal(std::string_view id) {
        const auto& control = widget(view(), id);
        if (control.spec.parent != "wb.right" && control.spec.parent != "modal.root" && control.spec.parent != "builder.body") return;
        const auto target = control.spec.key;
        const auto fully_visible = [](const gui::Availability& area) {
            constexpr double tolerance = 1e-7;
            return area.visible && area.clip.x <= area.bounds.x + tolerance &&
                area.clip.y <= area.bounds.y + tolerance &&
                area.clip.x + area.clip.width + tolerance >= area.bounds.x + area.bounds.width &&
                area.clip.y + area.clip.height + tolerance >= area.bounds.y + area.bounds.height;
        };
        if (fully_visible(adapter.resolved_availability(target))) return;
        const auto& group = widget(view(), control.spec.parent);
        const auto frame = adapter.resolved_availability(group.spec.key);
        auto viewport = frame.clip;
        if (group.state.content_clip) {
            const auto clip = *group.state.content_clip;
            viewport = gui::intersect(viewport,
                {frame.bounds.x + clip.x, frame.bounds.y + clip.y, clip.width, clip.height});
        }
        const auto bounds = adapter.resolved_availability(target).bounds;
        double movement{};
        if (bounds.y < viewport.y) movement = bounds.y - viewport.y;
        else if (bounds.y + bounds.height > viewport.y + viewport.height)
            movement = bounds.y + bounds.height - viewport.y - viewport.height;
        if (movement) {
            const auto offset = adapter.scroll_offset(group.spec.key);
            adapter.scroll(group.spec.key, {offset.x, offset.y + movement});
        }
        require(fully_visible(adapter.resolved_availability(target)),
                "Fixture could not scroll the complete control into view: " + std::string(id));
    }
    void send(std::string_view id, gui::Input input) {
        if (!std::holds_alternative<gui::PointerInput>(input)) reveal(id);
        const auto target = widget(view(), id).spec.key;
        require(adapter.send(gui::WidgetEvent{target, std::move(input)}) == gui::Delivery::delivered,
                "Adapter rejected " + std::string(id));
        presented(id);
    }
    void activate(std::string_view id) { send(id, gui::Activate{}); }
    void check(std::string_view id, bool value) { send(id, gui::SetChecked{value}); }
    void choose(std::string_view id, std::string value) {
        reveal(id);
        const auto& control = widget(view(), id);
        if (control.state.selected == value) {
            const auto revision = view().revision;
            const auto epoch = application->input_epoch();
            require(adapter.send(gui::WidgetEvent{control.spec.key, gui::ChooseOption{std::move(value)}}) ==
                        gui::Delivery::ignored,
                    "Adapter delivered an unchanged choice for " + std::string(id));
            presented(id);
            require(view().revision == revision && application->input_epoch() == epoch,
                    "An unchanged choice advanced application state");
            return;
        }
        send(id, gui::ChooseOption{std::move(value)});
    }
    void edit(std::string_view id, std::string value) {
        reveal(id);
        const auto& control = widget(view(), id);
        if (control.state.text == value) {
            const auto revision = view().revision;
            const auto epoch = application->input_epoch();
            require(adapter.send(gui::WidgetEvent{
                        control.spec.key, gui::EditText{std::move(value), control.state.text}}) ==
                        gui::Delivery::ignored,
                    "Adapter delivered an unchanged edit for " + std::string(id));
            presented(id);
            require(view().revision == revision && application->input_epoch() == epoch,
                    "An unchanged edit advanced application state");
            return;
        }
        send(id, gui::EditText{std::move(value), control.state.text});
    }
    void select(std::string_view id, std::string value) {
        send(id, gui::SelectRecord{std::move(value)});
    }
    void activate_record(std::string_view id, std::string value) {
        send(id, gui::ActivateRecord{std::move(value)});
    }
    void pointer(std::string_view id, gui::Point position,
                 gui::PointerKind kind = gui::PointerKind::click, std::uint64_t owner = 1) {
        gui::PointerInput input;
        input.kind = kind;
        input.position = position;
        if (kind == gui::PointerKind::press || kind == gui::PointerKind::move ||
            kind == gui::PointerKind::release || kind == gui::PointerKind::cancel)
            input.pointer_id = owner;
        send(id, input);
    }
    void click(std::string_view id, gui::Point position) {
        pointer(id, position, gui::PointerKind::press);
        pointer(id, position, gui::PointerKind::release);
    }
    void submit(std::string_view id) {
        require(widget(view(), id).spec.text_policy.submit == gui::SubmitKey::enter,
                "Enter submission is unavailable for " + std::string(id));
        send(id, gui::SubmitText{});
    }
    void escape() {
        const auto expected=view().modal_root||find(view(),"flow.drag.cancel")?
            gui::Delivery::delivered:gui::Delivery::ignored;
        require(adapter.send(gui::ShortcutEvent{gui::ShortcutKey::escape})==expected,
                "Escape shortcut was not handled by the application");
        presented("Escape");require(!adapter.closed(),"Escape closed the workbench");
    }
    void chat(std::string value) { select("wb.chats", std::move(value)); }
    void autosave() {
        std::this_thread::sleep_for(std::chrono::milliseconds(350));
        application->tick();
        presented("debounced autosave checkpoint");
    }
    void shortcut(std::string_view id, gui::ShortcutKey key, bool shift = false) {
        reveal(id);
        require(adapter.focus(widget(view(), id).spec.key), "Fixture could not focus " + std::string(id));
        gui::ShortcutEvent input{key, true, shift, false};
        require(adapter.send(input) == gui::Delivery::delivered,
                "Adapter rejected the focused shortcut for " + std::string(id));
        presented("focused shortcut");
    }
    void caret_at_end(std::string_view id) {
        const auto& control = widget(view(), id);
        adapter.text_selection(control.spec.key, {control.state.text.size(), control.state.text.size()});
    }
};

double transcript_maximum(const Session& session, std::string_view id = "wb.chat.rendered") {
    const auto& group = widget(session.view(), id);
    auto viewport = gui::Rect{0, 0, group.state.bounds.width, group.state.bounds.height};
    if (group.state.content_clip) viewport = gui::intersect(viewport, *group.state.content_clip);
    return std::max(0.0, group.state.content_size.height - viewport.height);
}
double transcript_offset(const Session& session, std::string_view id = "wb.chat.rendered") {
    return session.adapter.scroll_offset(widget(session.view(), id).spec.key).y;
}
void scroll_transcript(Session& session, double offset, std::string_view id = "wb.chat.rendered") {
    session.adapter.scroll(widget(session.view(), id).spec.key, {0, offset});
    session.application->tick();
    session.presented("transcript scroll observation");
}
bool rendered_block_visible(const Session& session, std::string_view text,
                            std::string_view id = "wb.chat.rendered") {
    const auto prefix = std::string(id) + ".block.";
    for (const auto& item : session.view().widgets) {
        if (!item.spec.key.id.starts_with(prefix) || item.state.text.find(text) == std::string::npos) continue;
        const auto area = session.adapter.resolved_availability(item.spec.key);
        constexpr double tolerance = 1e-7;
        if (area.visible && area.clip.y <= area.bounds.y + tolerance &&
            area.clip.y + area.clip.height + tolerance >= area.bounds.y + area.bounds.height) return true;
    }
    return false;
}
void require_transcript_tail(const Session& session, std::string_view text,
                             std::string_view id = "wb.chat.rendered") {
    require(rendered_block_visible(session, text, id),
            "The newest transcript block exists but is outside the visible viewport: " + std::string(text));
    near(transcript_offset(session, id), transcript_maximum(session, id),
         "Following the transcript did not reach its current bottom");
}
std::string long_transcript(std::string_view title, int paragraphs = 50) {
    std::string text = "# " + std::string(title) + "\n\n";
    for (int i = 0; i < paragraphs; ++i)
        text += std::string(title) + " earlier paragraph " + std::to_string(i) + ".\n\n";
    return text + std::string(title) + " final tail.\n";
}

template<class Predicate>
void wait_for(Session& session, Predicate ready, std::string_view step) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    do {
        session.application->tick();
        session.presented(step);
        if (ready()) return;
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    } while (std::chrono::steady_clock::now() < deadline);
    session.application->shutdown();
    throw std::runtime_error(std::string(step) + ": local fixture did not finish within ten seconds");
}

std::filesystem::path offline_chat_worker(const std::filesystem::path& directory) {
    const auto worker = directory / "offline chat worker.py";
    write(worker, R"PY(import json, os, sys, time
assert sys.flags.isolated and sys.flags.no_user_site
assert sys.argv[1] == '--request'
with open(sys.argv[2], encoding='utf-8') as stream:
    request = json.load(stream)
assert request['schema_version'] == 1 and request['operation'] in ('chat', 'agent')
assert os.path.realpath(request['root']) == os.path.realpath(os.getcwd())
assert 'zdr' not in request['settings'] and 'zero_data_retention' not in request['settings']
name = os.path.basename(request['chat_path'])
base = os.path.dirname(__file__)
with open(os.path.join(base, name + '.request.json'), 'w', encoding='utf-8') as stream:
    json.dump(request, stream)
with open(os.path.join(base, name + '.launches'), 'a', encoding='utf-8') as stream:
    stream.write('launch\n')
if request['prompt'].startswith('hold:'):
    while not os.path.exists(os.path.join(base, name + '.release')):
        time.sleep(0.01)
print(json.dumps({'ok': True, 'text': 'Local fixture answer.', 'sources': []}))
)PY");
    return worker;
}

std::string task_id(const Session& session, std::string_view owner, std::string_view state) {
    for (const auto& row : widget(session.view(), "wb.tasks").state.records)
        if (row.accessible_text.find(owner) != std::string::npos &&
            row.accessible_text.find(state) != std::string::npos) return row.id;
    throw std::runtime_error("Missing task row for " + std::string(owner) + " " + std::string(state));
}

void task_menu(Session& session, std::string_view target) {
    const auto& list = widget(session.view(), "wb.tasks");
    const auto found = std::find_if(list.state.records.begin(), list.state.records.end(),
        [&](const auto& row) { return row.id == target; });
    require(found != list.state.records.end(), "Task menu fixture lost its exact row identity");
    const auto index = static_cast<std::size_t>(found - list.state.records.begin());
    const auto bounds = session.adapter.resolved_availability(list.spec.key).bounds;
    const auto offset = session.adapter.scroll_offset(list.spec.key);
    session.pointer("wb.tasks", {bounds.x + 12, bounds.y + index * 28 + 14 - offset.y},
                    gui::PointerKind::context_menu);
    require(session.view().modal_root && find(session.view(), "task.cancel") && find(session.view(), "task.show"),
            "Right-clicking a task did not expose its contextual actions");
}

void global_modes_autosave_and_undo() {
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto config = fixture.root / "config";
    write(project / "first.chat.md", "# First\n");
    write(project / "second.chat.md", "# Second\n");
    {
        std::filesystem::create_directory(fixture.root / "empty");
        Session empty(fixture.root / "empty", {}, config);
        for (const auto* id : {"wb.tutorial", "wb.developer"})
            require(widget(empty.view(), id).spec.kind == gui::Kind::toggle &&
                    !widget(empty.view(), id).state.checked &&
                    widget(empty.view(), id).spec.parent == "wb.root" &&
                    empty.adapter.resolved_availability(widget(empty.view(), id).spec.key).visible,
                    "A global mode checkbox was hidden or enabled by default without a chat");
    }
    {
        Session session(project, "first.chat.md", config);
        require(!find(session.view(), "wb.chat.path"), "Chat retained its filename/save-state toolbar row");
        for (const auto* id : {"wb.undo", "wb.redo"})
            require(!find(session.view(), id),
                    "Chat retained a visible Undo/Redo toolbar button");
        for (const auto* id : {"wb.tutorial", "wb.developer"})
            require(widget(session.view(), id).state.label ==
                        (std::string_view(id) == "wb.tutorial" ? "Tutorial" : "Developer") &&
                    widget(session.view(), id).spec.parent == "wb.root",
                    "Mode checkboxes did not use brief global labels");
        session.edit("wb.composer", "First draft");
        session.edit("wb.composer", "Latest first draft");
        session.application->tick();
        require(!std::filesystem::exists(project / Workspace::state_path("first.chat.md")),
                "An immediate tick saved before the debounce elapsed");
        session.shortcut("wb.composer", gui::ShortcutKey::z);
        require(session.text("wb.composer") == "First draft", "Ctrl+Z did not undo a composer edit");
        session.shortcut("wb.composer", gui::ShortcutKey::z, true);
        require(session.text("wb.composer") == "Latest first draft", "Ctrl+Shift+Z did not redo a composer edit");
        session.shortcut("wb.composer", gui::ShortcutKey::z);
        session.shortcut("wb.composer", gui::ShortcutKey::y);
        require(session.text("wb.composer") == "Latest first draft", "Ctrl+Y did not redo a composer edit");
        session.autosave();
        require(Workspace(project).open_chat("first.chat.md").state.draft == "Latest first draft" &&
                read(project / "first.chat.md") == "# First\n",
                "Debounced autosave lost the latest composer or rewrote unchanged history");
        session.activate("tab.center.Pseudocode Editor");
        for (const auto* id : {"wb.undo", "wb.redo"})
            require(!find(session.view(), id),
                    "Pseudocode editor retained a visible Undo/Redo toolbar button");
        const std::string plan = "agent writer: Check requirements and evidence.\n";
        session.edit("wb.flow.text", plan);
        session.shortcut("wb.flow.text", gui::ShortcutKey::z);
        require(session.text("wb.flow.text").empty(), "Ctrl+Z did not undo the pseudocode source edit");
        session.shortcut("wb.flow.text", gui::ShortcutKey::z, true);
        require(session.text("wb.flow.text") == plan, "Ctrl+Shift+Z did not restore the pseudocode source edit");
        session.activate("tab.center.Chat Markdown");
        require(session.text("wb.composer").starts_with("Latest first draft") &&
                session.text("wb.composer").find("```pseudocode\n" + plan + "```\n") != std::string::npos,
                "Pseudocode undo/redo lost the surrounding composer message");
        session.check("wb.developer", true);
        const auto editable_key = widget(session.view(), "wb.chat.text").spec.key;
        session.edit("wb.chat.text", "# Developer edit\n");
        session.shortcut("wb.chat.text", gui::ShortcutKey::z);
        require(session.text("wb.chat.text") == "# First\n", "Ctrl+Z did not undo Developer history editing");
        session.shortcut("wb.chat.text", gui::ShortcutKey::z, true);
        require(session.text("wb.chat.text") == "# Developer edit\n", "Ctrl+Shift+Z did not redo Developer history editing");
        session.check("wb.developer", false);
        require(!find(session.view(), "wb.chat.text") && find(session.view(), "wb.chat.rendered") &&
                read(project / "first.chat.md") == "# Developer edit\n" &&
                session.adapter.send(gui::WidgetEvent{editable_key,
                    gui::EditText{"Stale edit", "# Developer edit\n"}}) == gui::Delivery::ignored,
                "Disabling Developer failed to flush history or revoked editing incompletely");
        session.edit("wb.composer", "Flush immediately when switching.");
        session.chat("second.chat.md");
        require(Workspace(project).open_chat("first.chat.md").state.draft == "Flush immediately when switching.",
                "Chat switching did not flush the pending composer without waiting for debounce");
        session.edit("wb.composer", "Flush immediately when closing.");
        session.check("wb.tutorial", true);
        session.application->handle(gui::CloseEvent{});
        require(session.adapter.closed() &&
                Workspace(project).open_chat("second.chat.md").state.draft == "Flush immediately when closing.",
                "Closing did not flush pending companion state");
    }
    {
        Session reopened(project, "second.chat.md", config);
        require(!widget(reopened.view(), "wb.developer").state.checked &&
                widget(reopened.view(), "wb.tutorial").state.checked &&
                !find(reopened.view(), "wb.chat.text") && find(reopened.view(), "wb.chat.rendered") &&
                reopened.text("wb.composer") == "Flush immediately when closing.",
                "Restart lost global modes or the flushed composer");
        reopened.edit("wb.composer", "Local state recovery draft.");
        const auto state_path = project / Workspace::state_path("second.chat.md");
        const auto external = read(state_path) + "\n";
        write(state_path, external);
        reopened.autosave();
        reopened.error("changed");
        require(reopened.text("wb.composer") == "Local state recovery draft." && read(state_path) == external,
                "A companion-state conflict lost the draft or overwrote external state bytes");
        reopened.application->handle(gui::CloseEvent{});
        require(!reopened.adapter.closed() && reopened.text("wb.composer") == "Local state recovery draft." &&
                read(state_path) == external, "Close discarded a state-conflicted draft");
    }
}

void missing_model_does_not_consume_a_message() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto config = fixture.root / "config";
    const auto worker = offline_chat_worker(fixture.root);
    const std::string history = "# Model preflight fixture\n\n## User\n\nExisting conversation.\n";
    const std::string draft = "Keep this unsent message exactly.\n\n```pseudocode\nagent draft: Keep the composer.\n```\n";
    write(project / "chat.chat.md", history);
    Workspace workspace(project);
    auto chat = workspace.open_chat("chat.chat.md");
    chat.state.ai.provider = "ollama";
    chat.state.ai.model.clear();
    chat.state.ai_configured = true;
    workspace.save_state(chat);
    Session session(project, "chat.chat.md", config, true, worker);
    require(!widget(session.view(), "wb.retry").state.enabled,
            "An old User heading supplied unrecorded Retry provenance");
    session.activate("tab.right.AI");
    require(session.text("ai.model").empty(), "Fresh defaults replaced an explicitly blank chat model");
    const auto defaults_before = inventory(config);
    session.edit("wb.composer", draft);
    session.activate("tab.right.Selector");
    const auto reject = [&](std::string_view fragment) {
        session.activate("wb.send");
        session.error(fragment);
        require(find(session.view(), "ai.model") && session.text("wb.composer") == draft &&
                session.text("wb.chat.text") == history && read(project / "chat.chat.md") == history &&
                !std::filesystem::exists(fixture.root / "chat.chat.md.launches") &&
                !Workspace(project).open_chat("chat.chat.md").state.submission &&
                !widget(session.view(), "wb.retry").state.enabled && inventory(config) == defaults_before,
                "Model preflight hid its AI repair control, consumed a message, launched a worker or changed defaults");
    };
    reject("Choose a model in AI");
    session.edit("ai.model", "   ");
    session.activate("tab.right.Selector");
    reject("Choose a model in AI");
    session.edit("ai.model", "invalid model");
    session.activate("tab.right.Selector");
    reject("Model ID is invalid");
    session.edit("ai.model", "visible-model-without-apply");
    const auto old_send = widget(session.view(), "wb.send").spec.key;
    session.activate("wb.send");
    wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; },
             "valid visible model fake-worker completion");
    session.success("valid model repair");
    const auto request = json::parse(read(fixture.root / "chat.chat.md.request.json"));
    require(request.find("settings")->find("model")->string() == "visible-model-without-apply" &&
            request.find("prompt")->string() == draft &&
            request.find("history")->array().front().find("content")->string() == history &&
            read(fixture.root / "chat.chat.md.launches") == "launch\n" &&
            session.text("wb.composer").empty() && widget(session.view(), "wb.retry").state.enabled &&
            inventory(config) == defaults_before,
            "Model repair required Apply, reused a stale model or launched more than one message");
    const auto previous_attempt = session.text("wb.chat.text");
    const std::string next_draft = "A new message after the prior task finished.";
    session.edit("wb.composer", next_draft);
    const auto epoch = session.application->input_epoch();
    require(session.adapter.send(gui::WidgetEvent{old_send, gui::Activate{}}) == gui::Delivery::ignored &&
            session.application->input_epoch() == epoch && session.text("wb.composer") == next_draft &&
            session.text("wb.chat.text") == previous_attempt &&
            read(fixture.root / "chat.chat.md.launches") == "launch\n",
            "A stale Send action became valid again and consumed the next message");
    session.activate("wb.send");
    wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; },
             "current Send after stale action rejection");
    session.success("current Send after stale action rejection");
    const auto next_request = json::parse(read(fixture.root / "chat.chat.md.request.json"));
    require(next_request.find("prompt")->string() == next_draft &&
            next_request.find("history")->array().front().find("content")->string() == previous_attempt &&
            session.text("wb.composer").empty() && read(fixture.root / "chat.chat.md.launches") == "launch\nlaunch\n",
            "Rejecting stale Send prevented the current control from submitting the new message exactly once");
#endif
}


void composer_actions_share_one_visible_row() {
    Temporary fixture;
    write(fixture.root / "first.chat.md", "# Compact composer\n");
    Session session(fixture.root, "first.chat.md");
    for (const auto size : {gui::Size{900, 640}, gui::Size{1440, 900}}) {
        for (const double scale : {1.0, 2.0}) {
            require(session.adapter.send(gui::ResizeEvent{size, scale}) == gui::Delivery::delivered,
                    "Compact composer fixture resize was rejected");
            session.presented("compact composer resize");
            const auto send_y = widget(session.view(), "wb.send").state.bounds.y;
            for (const bool agentic : {false, true}) {
                session.choose("wb.agentic", agentic ? "true" : "false");
                std::vector<const gui::Widget*> controls;
                for (const auto* id : {"wb.agentic", "wb.image.attach", "wb.retry", "wb.cancel", "wb.send"}) {
                    const auto& control = widget(session.view(), id);
                    near(control.state.bounds.y, send_y, "Composer controls occupied different rows");
                    near(control.state.bounds.height, 29, "A compact action lost its usable height");
                    const auto area = session.adapter.resolved_availability(control.spec.key);
                    require(fully_visible(area),
                            std::string("Composer action is clipped at a supported size: ") + id);
                    controls.push_back(&control);
                }
                if (const auto* label = find(session.view(), "wb.agentic.label")) controls.push_back(label);
                for (std::size_t a = 0; a < controls.size(); ++a)
                    for (std::size_t b = a + 1; b < controls.size(); ++b)
                        require(!gui::has_area(gui::intersect(controls[a]->state.bounds, controls[b]->state.bounds)),
                                "Compact composer controls overlap");
                require(gui::visible_text(widget(session.view(), "wb.agentic")) == (agentic ? "Agentic" : "Chat") &&
                        widget(session.view(), "wb.retry").state.label == "Retry" &&
                        widget(session.view(), "wb.retry").state.accessible_name == "Retry previous message" &&
                        widget(session.view(), "wb.chat.rendered").state.bounds.height >= size.height - 254,
                        "Retry retained its old full-width row or lost its accessible description");
            }
        }
    }
}

void image_drafts_are_explicit_snapshots_and_retry_the_original_images() {
#if defined(__linux__)
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto worker = fixture.root / "offline image worker.py";
    const std::string first_bytes("\x89\x50\x4e\x47\x0d\x0a\x1a\x0a\x00\x00\x00\x0d\x49\x48\x44\x52\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90\x77\x53\xde\x00\x00\x00\x0c\x49\x44\x41\x54\x78\x9c\x63\x60\x60\x60\x00\x00\x00\x04\x00\x01\xf6\x17\x38\x55\x00\x00\x00\x00\x49\x45\x4e\x44\xae\x42\x60\x82", 69);
    const std::string second_bytes("\x89\x50\x4e\x47\x0d\x0a\x1a\x0a\x00\x00\x00\x0d\x49\x48\x44\x52\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90\x77\x53\xde\x00\x00\x00\x0c\x49\x44\x41\x54\x78\x9c\x63\x60\x68\x60\x00\x00\x01\x04\x00\x81\x70\xf6\xc7\xa5\x00\x00\x00\x00\x49\x45\x4e\x44\xae\x42\x60\x82", 69);
    write(project / "first.png", first_bytes);
    write(project / "second.PNG", second_bytes);
    write(project / "bad.png", "This is not a PNG.");
    write(project / "notes.txt", "Ordinary text.");
    write(project / "first.chat.md", "# Image fixture\n");
    write(project / "second.chat.md", "# Independent draft\n");
    write(worker, R"PY(import json, os, sys
assert sys.flags.isolated and sys.flags.no_user_site
with open(sys.argv[2], encoding='utf-8') as stream:
    request = json.load(stream)
assert request['operation'] == 'chat'
assert all(set(image) == {'mime_type', 'data_base64'} for image in request.get('images', []))
base = os.path.dirname(__file__)
count = os.path.join(base, 'image attempts')
attempt = int(open(count, encoding='utf-8').read()) + 1 if os.path.exists(count) else 1
with open(count, 'w', encoding='utf-8') as stream:
    stream.write(str(attempt))
with open(os.path.join(base, 'image request.' + str(attempt) + '.json'), 'w', encoding='utf-8') as stream:
    json.dump(request, stream)
print(json.dumps({'ok': True, 'text': 'Offline image answer ' + str(attempt) + '.', 'sources': []}))
)PY");
    Workspace workspace(project);
    auto chat = workspace.open_chat("first.chat.md");
    chat.state.ai.provider = "ollama";
    chat.state.ai.model = "offline-image-model";
    chat.state.ai_configured = true;
    workspace.save_state(chat);
    const auto image_rows = [](const Session& session) {
        return std::count_if(session.view().widgets.begin(), session.view().widgets.end(),
            [](const auto& item) { return item.spec.key.id.starts_with("wb.image.name."); });
    };
    const auto choose = [](Session& session) {
        session.activate("wb.image.attach");
        auto request = session.application->next_service();
        require(request && request->kind == gui::ServiceKind::prompt && request->value.empty() &&
                request->title.find("PNG/JPEG") != std::string::npos && !session.application->next_service(),
                "Image selection was implicit, unsupported or dispatched twice");
        return *request;
    };
    std::vector<ImageAttachment> submitted, pending;
    std::string first_history;
    {
        auto crowded = workspace.open_chat("second.chat.md");
        for (std::size_t index = 0; index < Workspace::maximum_images; ++index) {
            const auto filename = "crowded-" + std::to_string(index) + ".png";
            write(project / filename, first_bytes + std::to_string(index));
            crowded.state.draft_images.push_back(workspace.attach_image(filename));
        }
        workspace.save_state(crowded);
        Session layout(project, "second.chat.md", {}, true, worker);
        require(layout.adapter.send(gui::ResizeEvent{{900, 640}, 1}) == gui::Delivery::delivered,
                "Four-image layout resize was rejected");
        const auto action_y = widget(layout.view(), "wb.send").state.bounds.y;
        require(image_rows(layout) == 4 && !widget(layout.view(), "wb.image.attach").state.enabled,
                "Four-image draft failed to display or retained an available fifth attachment");
        for (const auto& item : layout.view().widgets)
            if (item.spec.key.id.starts_with("wb.image.name.") || item.spec.key.id.starts_with("wb.image.remove.")) {
                const auto area = layout.adapter.resolved_availability(item.spec.key);
                require(fully_visible(area) && item.state.bounds.y + item.state.bounds.height < action_y,
                        "A four-image draft clipped a filename/removal control or overlapped Send");
            }
        for (const auto& image : crowded.state.draft_images) layout.activate("wb.image.remove." + image.sha256);
        require(image_rows(layout) == 0 && widget(layout.view(), "wb.image.attach").state.enabled &&
                widget(layout.view(), "wb.send").state.bounds.y == action_y,
                "Removing pending images moved the action row or failed to restore attachment selection");
        layout.application->handle(gui::CloseEvent{});
        require(layout.adapter.closed(), "Four-image layout fixture failed to flush");
    }
    {
        Session session(project, "first.chat.md", {}, true, worker);
        session.edit("wb.composer", "Retained draft before explicit image selection.");
        auto picker = choose(session);
        const auto epoch = session.application->input_epoch();
        require(!session.application->complete_service({picker.id + 1, gui::ServiceStatus::success,
                    (project / "first.png").string(), {}}) && session.application->input_epoch() == epoch,
                "A foreign image-selection callback changed this chat");
        require(session.application->complete_service({picker.id, gui::ServiceStatus::cancelled, {}, {}}) &&
                image_rows(session) == 0 && session.text("wb.composer") == "Retained draft before explicit image selection.",
                "Canceling image selection consumed the draft");
        picker = choose(session);
        session.activate("tab.left.Chats");session.chat("second.chat.md");
        require(session.application->complete_service({picker.id, gui::ServiceStatus::success,
                    (project / "first.png").string(), {}}) && image_rows(session) == 0,
                "A stale image selection attached to the newly selected chat");
        session.error("expired");
        session.activate("tab.left.Chats");session.chat("first.chat.md");
        picker = choose(session);
        session.edit("wb.composer", "Retained draft before explicit image selection.a");
        const auto composer = widget(session.view(), "wb.composer").spec.key;
        require(session.adapter.focus(composer), "Could not focus the image fixture composer");
        session.adapter.text_selection(composer, {2, 8});
        require(session.application->complete_service({picker.id, gui::ServiceStatus::success,
                    (project / "first.png").string(), {}}) && image_rows(session) == 0 &&
                session.text("wb.composer") == "Retained draft before explicit image selection.a" &&
                session.adapter.focused() == composer && session.adapter.text_selection(composer) == gui::TextSelection{2, 8},
                "Editing a pending image draft accepted a stale selection or disturbed the composer");
        session.error("expired");
        picker = choose(session);
        require(session.application->complete_service({picker.id, gui::ServiceStatus::success,
                    (project / "first.png").string(), {}}) && image_rows(session) == 1 &&
                session.adapter.focused() == composer && session.adapter.text_selection(composer) == gui::TextSelection{2, 8},
                "Explicit image attachment failed or stole composer focus/selection");
        session.success("explicit image attachment");
        session.edit("wb.composer", "Retained draft before explicit image selection.ab");
        session.shortcut("wb.composer", gui::ShortcutKey::z);
        require(image_rows(session) == 1 && session.text("wb.composer") == "Retained draft before explicit image selection.a",
                "Typing after image selection coalesced with the attachment's undo step");
        session.shortcut("wb.composer", gui::ShortcutKey::z);
        require(image_rows(session) == 0 && session.text("wb.composer") == "Retained draft before explicit image selection.a",
                "A second undo failed to remove the independent image attachment");
        session.shortcut("wb.composer", gui::ShortcutKey::y);
        require(image_rows(session) == 1, "Redo failed to restore the explicit image attachment");
        session.edit("wb.composer", "Retained draft before explicit image selection.");
        session.autosave();
        submitted = workspace.open_chat("first.chat.md").state.draft_images;
        require(submitted.size() == 1 && submitted.front().name == "first.png" &&
                submitted.front().bytes == first_bytes.size(), "The per-chat image draft was not saved");
        const auto remove = "wb.image.remove." + submitted.front().sha256;
        require(widget(session.view(), "wb.image.name." + submitted.front().sha256).state.text.find("first.png") != std::string::npos,
                "A pending image did not show its filename");
        session.activate(remove);
        require(image_rows(session) == 0, "Remove retained a pending image row");
        session.shortcut("wb.composer", gui::ShortcutKey::z);
        require(image_rows(session) == 1 && session.text("wb.composer") == "Retained draft before explicit image selection.",
                "Undo did not restore the explicit image-draft edit");
        session.activate("tab.left.Files");
        session.select("wb.files", "notes.txt");session.activate("wb.file.actions");
        require(!widget(session.view(), "actions.attach-image").state.enabled,
                "Files offered an ordinary text file as a supported image");
        session.activate("modal.cancel");
        session.select("wb.files", "first.png");session.activate("wb.file.actions");session.activate("actions.attach-image");
        session.error("already attached");
        require(image_rows(session) == 1, "Duplicate image attachment changed the draft");
        session.activate("modal.cancel");
        picker = choose(session);
        require(session.application->complete_service({picker.id, gui::ServiceStatus::success, "bad.png", {}}) &&
                image_rows(session) == 1, "An invalid image signature changed the draft");
        session.error("signature");
        session.edit("wb.composer", {});
        write(project / "first.png", "Source was changed after explicit selection.");
        const auto late_picker = choose(session);
        session.activate("wb.send");
        wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; }, "offline image-only Send");
        session.success("image-only Send");
        const auto request = json::parse(read(fixture.root / "image request.1.json"));
        const auto captured = workspace.image_payloads(submitted);
        require(request.find("prompt")->string().empty() && json::stringify(*request.find("images")) == json::stringify(json::Value(captured)) &&
                image_rows(session) == 0 && session.text("wb.composer").empty() &&
                workspace.open_chat("first.chat.md").state.draft_images.empty() &&
                workspace.open_chat("first.chat.md").state.submission->images == submitted,
                "Image-only Send invented text, reloaded source bytes, leaked metadata or retained consumed draft images");
        first_history = session.text("wb.chat.text");
        require(first_history.find("first.png") != std::string::npos && first_history.find(project.string()) == std::string::npos,
                "Submitted attachment history lost filenames or leaked the source path");
        require(session.application->complete_service({late_picker.id, gui::ServiceStatus::success,
                    (project / "second.PNG").string(), {}}) && image_rows(session) == 0,
                "A selection from before Send attached to the successor draft");
        session.error("expired");
        session.edit("wb.composer", "A different unsent image draft.");
        session.select("wb.files", "second.PNG");session.activate("wb.file.actions");session.activate("actions.attach-image");
        require(!session.view().modal_root && image_rows(session) == 1, "Files image attachment did not close its menu");
        session.activate("tab.left.Chats");session.chat("second.chat.md");
        require(image_rows(session) == 0 && session.text("wb.composer").empty(), "Pending images leaked across chats");
        session.activate("tab.left.Chats");session.chat("first.chat.md");
        pending = workspace.open_chat("first.chat.md").state.draft_images;
        require(pending.size() == 1 && pending != submitted && image_rows(session) == 1, "Switching lost the independent pending image draft");
        session.activate("wb.retry");
        wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; }, "offline image Retry");
        session.success("image Retry");
        const auto retried = json::parse(read(fixture.root / "image request.2.json"));
        require(retried.find("prompt")->string().empty() && json::stringify(*retried.find("images")) == json::stringify(json::Value(captured)) &&
                session.text("wb.composer") == "A different unsent image draft." && image_rows(session) == 1 &&
                session.text("wb.chat.text").starts_with(first_history) &&
                workspace.open_chat("first.chat.md").state.draft_images == pending,
                "Retry used the pending image draft, reloaded source bytes or consumed unsent work");
        session.application->handle(gui::CloseEvent{});
        require(session.adapter.closed(), "Image fixture failed to close");
    }
    {
        Session session(project, "first.chat.md", {}, true, worker);
        require(image_rows(session) == 1 && session.text("wb.composer") == "A different unsent image draft." &&
                widget(session.view(), "wb.retry").state.enabled && read(fixture.root / "image attempts") == "2",
                "Restart lost draft/submission images or submitted them automatically");
        write(project / ".tinyenv" / "images" / (submitted.front().sha256 + ".b64"), "corrupt");
        session.activate("wb.retry");
        require(read(fixture.root / "image attempts") == "2" && image_rows(session) == 1 &&
                session.text("wb.composer") == "A different unsent image draft.",
                "Corrupt retained images launched Retry or consumed the current draft");
        session.error("image");
        const auto picker = choose(session);
        session.application->handle(gui::CloseEvent{});
        require(session.adapter.closed() && !session.application->complete_service({picker.id,
                    gui::ServiceStatus::success, "second.PNG", {}}), "A closed workbench accepted late image selection");
    }
#endif
}

void retry_uses_the_previous_submission_and_preserves_the_draft() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto config = fixture.root / "config";
    const auto worker = fixture.root / "offline retry worker.py";
    write(worker, R"PY(import json, os, sys, time
assert sys.flags.isolated and sys.flags.no_user_site
assert sys.argv[1] == '--request'
with open(sys.argv[2], encoding='utf-8') as stream:
    request = json.load(stream)
assert request['schema_version'] == 1 and request['operation'] in ('chat', 'agent')
assert os.path.realpath(request['root']) == os.path.realpath(os.getcwd())
assert 'zdr' not in request['settings'] and 'zero_data_retention' not in request['settings']
base = os.path.dirname(__file__)
counter = os.path.join(base, 'attempts')
attempt = 1
if os.path.exists(counter):
    with open(counter, encoding='utf-8') as stream:
        attempt += int(stream.read())
with open(counter, 'w', encoding='utf-8') as stream:
    stream.write(str(attempt))
receipt = os.path.join(base, 'request.' + str(attempt) + '.json')
with open(receipt + '.tmp', 'w', encoding='utf-8') as stream:
    json.dump(request, stream)
os.replace(receipt + '.tmp', receipt)
if attempt == 2:
    while not os.path.exists(os.path.join(base, 'release')):
        time.sleep(0.01)
if attempt == 1:
    print(json.dumps({'ok': False, 'error': 'Synthetic initial failure.',
                      'text': '', 'sources': []}))
elif attempt == 2:
    print(json.dumps({'ok': False, 'error': 'Synthetic retry partial failure.',
                      'text': 'Retained partial attempt two.', 'sources': []}))
else:
    print(json.dumps({'ok': True, 'text': 'Retry answer ' + str(attempt) + '.', 'sources': []}))
)PY");
    const std::string history = "# Retry fixture\n\n## User\n\nOlder unrelated message.\n\n## Assistant\n\nOlder result.\n";
    const std::string source = "agent original: Check original evidence.\n\n";
    const std::string original = "Original submitted prompt.\n\n```pseudocode\n" + source + "```\n";
    const std::string unsent = "A different unsent draft.\n\n```pseudocode\nagent unsent: Never run this on Retry.\n```\n";
    write(project / "first.chat.md", history);
    write(project / "legacy.chat.md", "# Legacy\n\n## User\n\nManually written message.\n");
    Workspace workspace(project);
    auto chat = workspace.open_chat("first.chat.md");
    chat.state.ai.provider = "ollama";
    chat.state.ai.model = "original-model";
    chat.state.ai_configured = true;
    chat.state.agentic = true;
    workspace.save_state(chat);
    std::string first_attempt, second_attempt;
    const auto count = [](std::string_view text, std::string_view needle) {
        std::size_t result{}, position{};
        while ((position = text.find(needle, position)) != std::string_view::npos) {
            ++result;
            position += needle.size();
        }
        return result;
    };
    const auto request_for = [&](int attempt) {
        return json::parse(read(fixture.root / ("request." + std::to_string(attempt) + ".json")));
    };
    const auto original_context = [&](const json::Value& request) {
        require(request.find("operation")->string() == "agent" &&
                request.find("prompt")->string() == original &&
                request.find("pseudocode")->string() == source &&
                request.find("history")->array().size() == 1 &&
                request.find("history")->array().front().find("content")->string() == history,
                "Retry used the current draft, mode, sidecar or previous attempt as its request context");
    };
    {
        Session session(project, "first.chat.md", config, true, worker);
        require(widget(session.view(), "wb.retry").state.label == "Retry" &&
                widget(session.view(), "wb.retry").state.accessible_name == "Retry previous message" &&
                !widget(session.view(), "wb.retry").state.enabled,
                "Retry was enabled before an explicit submission");
        session.edit("wb.composer", original);
        session.activate("wb.send");
        wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; },
                 "initial failed retry fixture request");
        session.error("Synthetic initial failure");
        original_context(request_for(1));
        first_attempt = session.text("wb.chat.text");
        require(first_attempt == history + "\n## User\n\n" + original + "\n" &&
                session.text("wb.status").find("Use Retry previous message to try again.") != std::string::npos &&
                session.text("wb.status").find("Incomplete output and provenance retained") == std::string::npos &&
                widget(session.view(), "wb.retry").state.enabled && session.text("wb.composer").empty(),
                "An empty failed submission claimed retained output, added an empty result or lost Retry provenance");
        session.edit("wb.composer", unsent);
        session.choose("wb.agentic", "false");
        session.choose("selector.kind", "refs");
        session.edit("selector.path", "reviewed-context.md");
        session.activate("selector.add");
        session.activate("tab.right.AI");
        const auto defaults_before = inventory(config);
        session.edit("ai.model", "");
        session.activate("tab.right.Selector");
        session.activate("wb.retry");
        session.error("Choose a model in AI");
        require(find(session.view(), "ai.model") && session.text("wb.composer") == unsent &&
                session.text("wb.chat.text") == first_attempt && read(fixture.root / "attempts") == "1" &&
                widget(session.view(), "wb.retry").state.enabled,
                "Invalid Retry settings launched a worker or consumed the draft, history or provenance");
        session.edit("ai.model", "retry-visible-model");
        session.edit("ai.temperature", "0.35");
        session.activate("wb.retry");
        wait_for(session, [&] { return std::filesystem::exists(fixture.root / "request.2.json"); },
                 "held retry fixture request receipt");
        const auto retry_request = request_for(2);
        original_context(retry_request);
        const auto& refs = retry_request.find("selector")->find("refs")->array();
        require(retry_request.find("settings")->find("model")->string() == "retry-visible-model" &&
                retry_request.find("settings")->find("temperature")->number() == 0.35 &&
                refs.size() == 1 && refs.front().find("path")->string() == "reviewed-context.md" &&
                refs.front().find("enabled")->boolean() &&
                session.text("wb.composer") == unsent && !widget(session.view(), "wb.retry").state.enabled &&
                session.text("wb.chat.text").starts_with(first_attempt) &&
                count(session.text("wb.chat.text"), "\n## User\n\n" + original + "\n") == 1 &&
                count(session.text("wb.chat.text"), "\n## Retry\n") == 1 && inventory(config) == defaults_before,
                "Retry changed the draft, duplicated the User prompt, lost the old attempt or ignored current visible settings");
        const auto epoch = session.application->input_epoch();
        require(session.adapter.send(gui::WidgetEvent{widget(session.view(), "wb.retry").spec.key,
                    gui::Activate{}}) == gui::Delivery::ignored &&
                session.application->input_epoch() == epoch && read(fixture.root / "attempts") == "2",
                "A running Retry accepted a duplicate explicit action");
        write(fixture.root / "release", "release\n");
        wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; },
                 "partial retry fixture completion");
        session.error("Synthetic retry partial failure");
        second_attempt = session.text("wb.chat.text");
        require(second_attempt.starts_with(first_attempt) &&
                second_attempt.find("Retained partial attempt two.") != std::string::npos &&
                session.text("wb.status").find("Incomplete output and provenance retained.") != std::string::npos &&
                session.text("wb.composer") == unsent && widget(session.view(), "wb.retry").state.enabled &&
                Workspace(project).open_chat("first.chat.md").state.submission,
                "Completed Retry discarded an earlier attempt, current draft or saved provenance");
        const auto stale_retry = widget(session.view(), "wb.retry").spec.key;
        session.chat("legacy.chat.md");
        require(!widget(session.view(), "wb.retry").state.enabled &&
                session.adapter.send(gui::WidgetEvent{stale_retry, gui::Activate{}}) == gui::Delivery::ignored &&
                read(fixture.root / "attempts") == "2",
                "Chat switching supplied inferred Retry provenance or accepted a stale action");
        session.chat("first.chat.md");
        require(session.text("wb.composer") == unsent && widget(session.view(), "wb.retry").state.enabled &&
                read(fixture.root / "attempts") == "2", "Chat switching retried implicitly or lost the unsent draft");
        session.application->handle(gui::CloseEvent{});
        require(session.adapter.closed(), "Retry fixture failed to close after completed requests");
    }
    {
        Session session(project, "first.chat.md", config, true, worker);
        require(session.text("wb.composer") == unsent && session.text("wb.chat.text") == second_attempt &&
                widget(session.view(), "wb.retry").state.enabled && read(fixture.root / "attempts") == "2",
                "Restart lost Retry provenance or implicitly launched a request");
        session.activate("tab.right.AI");
        session.edit("ai.model", "retry-after-restart-model");
        session.activate("wb.retry");
        wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; },
                 "retry after restart completion");
        session.success("Retry after restart");
        const auto request = request_for(3);
        original_context(request);
        require(request.find("settings")->find("model")->string() == "retry-after-restart-model" &&
                session.text("wb.composer") == unsent && session.text("wb.chat.text").starts_with(second_attempt) &&
                session.text("wb.chat.text").find("Retry answer 3.") != std::string::npos &&
                count(session.text("wb.chat.text"), "\n## User\n\n" + original + "\n") == 1 &&
                count(session.text("wb.chat.text"), "\n## Retry\n") == 2 && read(fixture.root / "attempts") == "3",
                "Repeated Retry after restart changed its original context or lost retained attempts/draft");
        session.check("wb.developer", true);
        auto edited = session.text("wb.chat.text");
        edited.replace(edited.find("Original submitted prompt."), std::string("Original submitted prompt.").size(),
                       "Edited submitted prompt.");
        session.edit("wb.chat.text", edited);
        session.activate("wb.retry");
        session.error("The previous message or its earlier history changed");
        require(session.text("wb.chat.text") == edited && session.text("wb.composer") == unsent &&
                read(fixture.root / "attempts") == "3",
                "Retry accepted edited original provenance or lost the retained draft/history");
    }
#endif
}

void streaming_progress_is_visible_saved_and_isolated() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto worker = fixture.root / "gated stream worker.py";
    write(worker, R"PY(import json, os, sys, time
assert sys.flags.isolated and sys.flags.no_user_site
assert sys.argv[1] == '--request'
with open(sys.argv[2], encoding='utf-8') as stream:
    request = json.load(stream)
assert request['schema_version'] == 1 and request['operation'] in ('chat', 'agent')
assert request['stream'] is True
assert os.path.realpath(request['root']) == os.path.realpath(os.getcwd())
base = os.path.dirname(__file__)
counter = os.path.join(base, 'stream attempts')
attempt = 1
if os.path.exists(counter):
    with open(counter, encoding='utf-8') as stream:
        attempt += int(stream.read())
with open(counter, 'w', encoding='utf-8') as stream:
    stream.write(str(attempt))
receipt = os.path.join(base, 'stream.request.' + str(attempt) + '.json')
with open(receipt + '.tmp', 'w', encoding='utf-8') as stream:
    json.dump(request, stream)
os.replace(receipt + '.tmp', receipt)
def emit(sequence, event, **data):
    print(json.dumps(dict(stream_version=1, sequence=sequence, event=event, **data)), flush=True)
def gate(name):
    while not os.path.exists(os.path.join(base, str(attempt) + '.' + name)):
        time.sleep(0.01)
emit(0, 'start', operation=request['operation'])
previews = {1: 'Visible first chunk.', 2: 'Visible retry chunk.',
            3: 'Canceled validated preview.', 4: 'Validated preview before protocol error.'}
if attempt == 1:
    gate('first')
emit(1, 'delta', text=previews[attempt], replace=False)
if attempt == 1:
    gate('append')
    emit(2, 'delta', text=' Second visible chunk.\n\nActive append tail.', replace=False)
    gate('hidden')
    emit(3, 'delta', text='\n\nUnseen continuation tail.', replace=False)
    gate('next')
    emit(4, 'delta', text='\n\nInactive continuation tail.', replace=False)
    gate('replace')
    emit(5, 'delta', text='Superseded burst candidate.', replace=True)
    emit(6, 'delta', text='Replacement candidate for the latest preview.\n\nReplacement latest tail.', replace=True)
    gate('finish')
    emit(7, 'final', result={'ok': True, 'text': 'Final complete answer.\nSecond authoritative line.', 'sources': []})
elif attempt == 2:
    gate('finish')
    emit(2, 'final', result={'ok': True, 'text': 'Final retried answer.', 'sources': []})
elif attempt == 3:
    gate('finish')
elif attempt == 4:
    gate('finish')
    emit(99, 'delta', text='INVALID UNVALIDATED OUTPUT', replace=False)
    gate('joined')
)PY");
    const std::string first_history = long_transcript("First stream chat");
    const std::string second_history = "# Other chat\n";
    const std::string prompt = "Stream this original submitted message.";
    write(project / "first.chat.md", first_history);
    write(project / "second.chat.md", second_history);
    Workspace workspace(project);
    for (const auto* path : {"first.chat.md", "second.chat.md"}) {
        auto chat = workspace.open_chat(path);
        chat.state.ai.provider = "ollama";
        chat.state.ai.model = "offline-stream-fixture";
        chat.state.ai_configured = true;
        workspace.save_state(chat);
    }
    Session session(project, "first.chat.md", {}, true, worker);
    const auto release = [&](int attempt, std::string_view stage) {
        write(fixture.root / (std::to_string(attempt) + "." + std::string(stage)), "release\n");
    };
    const auto receipt = [&](int attempt) {
        return json::parse(read(fixture.root / ("stream.request." + std::to_string(attempt) + ".json")));
    };
    const auto busy = [&] {
        const auto& marker = widget(session.view(), "wb.chat.busy");
        require(marker.spec.kind == gui::Kind::bitmap && marker.spec.parent == "wb.center" &&
                !marker.spec.pointer_input && !marker.spec.context_input && marker.state.actions.empty() &&
                marker.state.bounds.width <= 32 && marker.state.bounds.height <= 32 &&
                session.adapter.resolved_availability(marker.spec.key).visible,
                "Running chat did not expose a small passive visible busy marker");
    };
    const auto live = [&](std::string_view preview) {
        wait_for(session, [&] {
            return widget(session.view(), "wb.cancel").state.enabled &&
                session.rendered_text().find(preview) != std::string::npos;
        }, "visible streamed preview while worker is gated");
        require(session.text("wb.chat.text").find("\n## Streaming\n") != std::string::npos &&
                !find(session.view(), "wb.chat.text") && !widget(session.view(), "wb.retry").state.enabled,
                "Running preview was hidden, editable or enabled duplicate Retry");
        busy();
        require_transcript_tail(session, preview);
    };
    const auto saved_preview = [&](std::string_view preview) {
        wait_for(session, [&] { return read(project / "first.chat.md").find(preview) != std::string::npos; },
                 "checked streamed preview autosave while worker is gated");
        require(widget(session.view(), "wb.cancel").state.enabled,
                "Stream preview was saved only after the worker finished");
    };
    session.chat("second.chat.md");
    session.activate("wb.split");
    session.choose("wb.split.path", "first.chat.md");
    require_transcript_tail(session, "First stream chat final tail.", "wb.split.rendered");
    scroll_transcript(session, 160, "wb.split.rendered");
    session.chat("first.chat.md");
    session.edit("wb.composer", prompt);
    session.activate("wb.send");
    wait_for(session, [&] { return std::filesystem::exists(fixture.root / "stream.request.1.json"); },
             "gated stream worker start without first token");
    busy();
    require(session.text("wb.chat.text").find("## Streaming") == std::string::npos &&
            session.rendered_text().find("Visible first chunk.") == std::string::npos,
            "Pre-token fixture did not keep the first delta gated");
    const auto pretoken_composer = widget(session.view(), "wb.composer").spec.key;
    require(session.adapter.focus(pretoken_composer), "Could not focus the pre-token composer");
    const auto idle_revision = session.view().revision;
    const auto idle_busy = widget(session.view(), "wb.chat.busy").state.bitmap;
    for (int i = 0; i < 8; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        session.application->tick();
        session.presented("pre-token busy idle tick");
        require(session.view().revision == idle_revision &&
                widget(session.view(), "wb.chat.busy").state.bitmap.revision == idle_busy.revision &&
                session.adapter.focused() == pretoken_composer,
                "A stationary pre-token busy marker caused render churn or stole composer focus");
    }
    release(1, "first");
    live("Visible first chunk.");
    saved_preview("Visible first chunk.");
    require(session.adapter.focused() == pretoken_composer,
            "Arrival of the first streamed token stole composer focus");
    const auto first_offset = transcript_offset(session);
    release(1, "append");
    live("Active append tail.");
    saved_preview("Active append tail.");
    require(transcript_offset(session) > first_offset,
            "Following an appended streamed paragraph did not advance toward the newer tail");
    session.check("wb.developer", true);
    require(!find(session.view(), "wb.chat.text") && find(session.view(), "wb.chat.rendered"),
            "Developer exposed an editable transcript while its streaming suffix was owned");
    session.check("wb.developer", false);
    const std::string retained_draft = "Retain this unsent draft while the answer streams.";
    session.edit("wb.composer", retained_draft);
    scroll_transcript(session, 300);
    require(!rendered_block_visible(session, "Active append tail."),
            "Scrolling up did not leave the streamed tail outside the viewport");
    session.chat("second.chat.md");
    session.choose("wb.split.path", "first.chat.md");
    near(transcript_offset(session, "wb.split.rendered"), 160,
         "Sending in one chat reset another owner's paused split of that chat");
    require(!rendered_block_visible(session, "Active append tail.", "wb.split.rendered"),
            "A Send forced an independently paused split to follow the stream");
    const std::string other_draft = "The other chat owns this draft and focus.";
    session.edit("wb.composer", other_draft);
    const auto other_composer = widget(session.view(), "wb.composer").spec.key;
    require(session.adapter.focus(other_composer), "Could not focus the inactive-stream fixture's other composer");
    session.adapter.text_selection(other_composer, {4, 12});
    require(!find(session.view(), "wb.chat.busy"), "Another chat's job showed a busy marker in this idle chat");
    session.activate("wb.split");
    session.activate("tab.left.Running Tasks");
    session.autosave();
    const auto hidden_revision = session.view().revision;
    release(1, "hidden");
    wait_for(session, [&] {
        return read(project / "first.chat.md").find("Unseen continuation tail.") != std::string::npos;
    }, "unseen streamed preview autosave");
    require(session.view().revision == hidden_revision &&
            session.text("wb.chat.text") == second_history && session.text("wb.composer") == other_draft &&
            session.adapter.focused() == other_composer &&
            session.adapter.text_selection(other_composer) == gui::TextSelection{4, 12},
            "An unseen stream or routine save rebuilt the idle chat or disturbed its composer");
    session.activate("tab.left.Chats");
    session.activate("wb.split");
    session.choose("wb.split.path", "first.chat.md");
    release(1, "next");
    wait_for(session, [&] {
        return read(project / "first.chat.md").find("Inactive continuation tail.") != std::string::npos;
    }, "inactive streamed preview autosave");
    require(session.text("wb.chat.text") == second_history && read(project / "second.chat.md") == second_history &&
            session.rendered_text().find("Visible first chunk.") == std::string::npos &&
            session.rendered_text().find("Second visible chunk.") == std::string::npos &&
            session.rendered_text().find("Inactive continuation tail.") == std::string::npos &&
            !find(session.view(), "wb.chat.busy") &&
            session.text("wb.composer") == other_draft &&
            widget(session.view(), "wb.composer").spec.key == other_composer &&
            session.adapter.focused() == other_composer &&
            session.adapter.text_selection(other_composer) == gui::TextSelection{4, 12},
            "Inactive stream updates replaced another chat's transcript, draft, widget identity, focus or selection");
    near(transcript_offset(session, "wb.split.rendered"), 160,
         "A split showing an inactive stream discarded its paused reading position");
    require(session.rendered_text("wb.split.rendered").find("Inactive continuation tail.") != std::string::npos &&
            !rendered_block_visible(session, "Inactive continuation tail.", "wb.split.rendered"),
            "The paused split failed to update its source or followed the arriving tail automatically");
    session.chat("first.chat.md");
    require(session.text("wb.composer") == retained_draft &&
            session.rendered_text().find("Visible first chunk. Second visible chunk.") != std::string::npos &&
            session.rendered_text().find("Inactive continuation tail.") != std::string::npos,
            "Returning to the streaming chat lost its draft or current accumulated preview");
    busy();
    near(transcript_offset(session), 300, "An inactive stream update erased the chat's paused scrollback");
    require(!rendered_block_visible(session, "Inactive continuation tail."),
            "A paused streaming chat resumed following while it was inactive");
    scroll_transcript(session, transcript_maximum(session));
    require_transcript_tail(session, "Inactive continuation tail.");
    const auto composer = widget(session.view(), "wb.composer").spec.key;
    require(session.adapter.focus(composer), "Could not focus the streaming chat composer");
    session.adapter.text_selection(composer, {3, 10});
    release(1, "replace");
    live("Replacement latest tail.");
    saved_preview("Replacement latest tail.");
    require(session.text("wb.chat.text").find("Superseded burst candidate.") == std::string::npos &&
            session.text("wb.chat.text").find("Visible first chunk.") == std::string::npos &&
            session.adapter.focused() == composer &&
            session.adapter.text_selection(composer) == gui::TextSelection{3, 10},
            "A replacement burst duplicated older candidates or disturbed the unsent composer");
    release(1, "finish");
    wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; },
             "stream final completion");
    session.success("stream final completion");
    require(!find(session.view(), "wb.chat.busy"), "Completed reply retained the busy marker");
    require(find(session.view(), "wb.chat.rendered.boundary"), "Saved idle reply omitted its boundary");
    require_transcript_tail(session, "Second authoritative line.");
    const std::string completed = first_history + "\n## User\n\n" + prompt +
        "\n\n## Assistant\n\n> Final complete answer.\n> Second authoritative line.\n";
    require(session.text("wb.chat.text") == completed && read(project / "first.chat.md") == completed &&
            session.rendered_text().find("Final complete answer.") != std::string::npos &&
            session.rendered_text().find("Visible first chunk.") == std::string::npos &&
            session.text("wb.composer") == retained_draft && session.adapter.focused() == composer &&
            session.adapter.text_selection(composer) == gui::TextSelection{3, 10},
            "Final stream duplicated its preview, ignored authoritative text or disturbed the unsent composer");
    session.check("wb.developer", true);
    require(widget(session.view(), "wb.chat.text").state.text == completed,
            "Developer opened an obsolete raw editor after streamed completion");
    session.check("wb.developer", false);
    session.activate("tab.right.AI");
    session.edit("ai.model", "offline-stream-retry-model");
    scroll_transcript(session, 0);
    session.activate("wb.retry");
    live("Visible retry chunk.");
    require(!find(session.view(), "wb.chat.rendered.boundary"), "Retry retained the idle boundary");
    saved_preview("Visible retry chunk.");
    const auto retried = receipt(2);
    require(retried.find("prompt")->string() == prompt && retried.find("operation")->string() == "chat" &&
            retried.find("history")->array().front().find("content")->string() == first_history &&
            retried.find("settings")->find("model")->string() == "offline-stream-retry-model" &&
            session.text("wb.composer") == retained_draft,
            "Streaming Retry used the new draft or prior stream result instead of the original submission/current settings");
    scroll_transcript(session, 300);
    release(2, "finish");
    wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; },
             "retried stream final completion");
    session.success("retried stream final completion");
    require(!find(session.view(), "wb.chat.busy"), "Completed Retry retained the busy marker");
    near(transcript_offset(session), 300, "Final completion discarded the reader's paused scrollback");
    require(!rendered_block_visible(session, "Final retried answer."),
            "Final completion forced a paused reader to the new result");
    const auto after_retry = session.text("wb.chat.text");
    require(after_retry.starts_with(completed + "\n## Retry\n") &&
            after_retry.ends_with("\n## Assistant\n\n> Final retried answer.\n") &&
            after_retry.find("## Streaming") == std::string::npos &&
            after_retry.find("Visible retry chunk.") == std::string::npos &&
            after_retry.find("\n## User\n\n" + prompt + "\n", completed.size()) == std::string::npos &&
            read(project / "first.chat.md") == after_retry &&
            session.text("wb.composer") == retained_draft && read(fixture.root / "stream attempts") == "2",
            "Streaming Retry lost earlier output, duplicated previews or consumed the draft");
    session.edit("wb.composer", "Cancel this submitted stream.");
    session.activate("wb.send");
    live("Canceled validated preview.");
    saved_preview("Canceled validated preview.");
    session.edit("wb.composer", "Keep a new draft after cancellation.");
    scroll_transcript(session, 300);
    session.activate("wb.cancel");
    require(!widget(session.view(), "wb.cancel").state.enabled &&
            !find(session.view(), "wb.chat.busy") &&
            find(session.view(), "wb.chat.rendered.boundary") &&
            session.text("wb.chat.text").ends_with("\n## Incomplete result\n\n> Canceled validated preview.\n") &&
            session.text("wb.chat.text").find("## Streaming") == std::string::npos &&
            read(project / "first.chat.md") == session.text("wb.chat.text") &&
            session.text("wb.composer") == "Keep a new draft after cancellation.",
            "Cancel failed to finalize/save exactly the validated preview or consumed the next draft");
    near(transcript_offset(session), 300, "Cancel discarded the reader's paused scrollback");
    const auto after_cancel = session.text("wb.chat.text");
    session.edit("wb.composer", "Reject malformed progress after this message.");
    session.activate("wb.send");
    live("Validated preview before protocol error.");
    saved_preview("Validated preview before protocol error.");
    release(4, "finish");
    wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; },
             "invalid stream joined worker completion");
    session.error("invalid streaming progress");
    require(session.text("wb.chat.text").starts_with(after_cancel) &&
            !find(session.view(), "wb.chat.busy") &&
            find(session.view(), "wb.chat.rendered.boundary") &&
            session.text("wb.chat.text").ends_with(
                "\n## Incomplete result\n\n> Validated preview before protocol error.\n") &&
            session.text("wb.chat.text").find("## Streaming") == std::string::npos &&
            session.text("wb.chat.text").find("INVALID UNVALIDATED OUTPUT") == std::string::npos &&
            session.rendered_text().find("Validated preview before protocol error.") != std::string::npos &&
            session.rendered_text().find("INVALID UNVALIDATED OUTPUT") == std::string::npos &&
            read(project / "first.chat.md") == session.text("wb.chat.text") &&
            read(fixture.root / "stream attempts") == "4",
            "Invalid streaming progress published unvalidated text or discarded/duplicated the validated partial result");
    require_transcript_tail(session, "Validated preview before protocol error.");
    const auto saved = session.text("wb.chat.text");
    session.application->handle(gui::CloseEvent{});
    require(session.adapter.closed() && read(project / "first.chat.md") == saved,
            "Closing after canceled/failed streams lost or duplicated retained partial output");
#endif
}

void idle_boundary_is_quiet_persistent_and_source_scoped() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;
    const auto project = fixture.root / "project", worker = fixture.root / "boundary worker.py";
    write(worker, R"PY(import json, os, sys, time
with open(sys.argv[2], encoding='utf-8') as stream:
    request = json.load(stream)
base = os.path.dirname(__file__)
prompt = request['prompt']
with open(os.path.join(base, 'boundary.request.json'), 'w', encoding='utf-8') as stream:
    json.dump(request, stream)
print(json.dumps(dict(stream_version=1, sequence=0, event='start', operation=request['operation'])), flush=True)
if prompt in ('hold', 'empty-conflict'):
    with open(os.path.join(base, prompt + '.started'), 'w') as stream:
        stream.write('started')
    gate = 'finish' if prompt == 'hold' else 'empty-conflict.finish'
    while not os.path.exists(os.path.join(base, gate)):
        time.sleep(.01)
if prompt == 'incomplete':
    print(json.dumps(dict(stream_version=1, sequence=1, event='delta', text='Validated incomplete text.', replace=False)), flush=True)
else:
    result = dict(ok=prompt != 'failure', text='' if prompt == 'empty-conflict' else 'Stopped local response.', sources=[])
    if prompt == 'failure':
        result['error'] = 'Offline failure.'
    print(json.dumps(dict(stream_version=1, sequence=1, event='final', result=result)), flush=True)
)PY");
    write(project / "first.chat.md", long_transcript("Boundary history"));
    write(project / "second.chat.md", "# Unopened saved chat\n");
    write(project / "blank.chat.md", " \n\t\n");
    Workspace workspace(project);
    auto chat = workspace.open_chat("first.chat.md");
    chat.state.ai.provider = "ollama";chat.state.ai.model = "offline-boundary-model";
    chat.state.ai_configured = true;workspace.save_state(chat);
    Session session(project, "first.chat.md", {}, true, worker);
    const auto boundary = [&](std::string_view id = "wb.chat.rendered.boundary") {
        const auto& line = widget(session.view(), id);
        require(line.spec.kind == gui::Kind::bitmap && line.state.bounds.height == 1 &&
                line.state.text.empty() && line.state.label.empty() && !line.spec.pointer_input &&
                !line.spec.context_input && line.state.actions.empty() && !gui::focusable(line),
                "Idle boundary was not a thin noninteractive line without text");
        for (const auto& body : session.view().widgets)
            if (body.spec.parent == line.spec.parent && body.spec.key != line.spec.key)
                require(line.state.bounds.y >= body.state.bounds.y + body.state.bounds.height,
                        "Idle boundary overlapped or preceded retained content");
    };
    boundary();
    require(!find(session.view(), "wb.chat.rendered.complete"), "Obsolete timed completion text survived");
    session.activate("wb.split");session.choose("wb.split.path", "second.chat.md");boundary("wb.split.rendered.boundary");
    require(!std::filesystem::exists(project / Workspace::state_path("second.chat.md")),
            "Read-only split boundary created companion state for its unopened source");
    session.choose("wb.split.path", "blank.chat.md");
    require(!find(session.view(), "wb.split.rendered.boundary"), "Blank saved source displayed an idle boundary");
    session.activate("wb.split");
    session.edit("wb.composer", "The pending draft does not change the saved boundary.");session.autosave();
    scroll_transcript(session, 200);
    const auto composer = widget(session.view(), "wb.composer").spec.key;
    require(session.adapter.focus(composer), "Could not focus boundary fixture composer");
    session.adapter.text_selection(composer, {3, 10});
    const auto retained = inventory(project);const auto extent = transcript_maximum(session);
    const auto idle_revision = session.view().revision;
    for (int i = 0; i < 6; ++i) session.application->tick();
    boundary();
    require(session.view().revision == idle_revision && inventory(project) == retained &&
            session.adapter.focused() == composer && session.adapter.text_selection(composer) == gui::TextSelection{3, 10},
            "Idle boundary caused timer repaint, persistence or focus changes");
    session.application->handle(gui::ResizeEvent{session.view().client_size, session.view().display_scale});boundary();
    near(transcript_offset(session), 200, "Boundary repaint moved a paused reader");
    near(transcript_maximum(session), extent, "Boundary repaint changed the reader range");
    const auto before_send = session.text("wb.chat.text");
    session.edit("wb.composer", "hold");session.activate("wb.send");
    require(!find(session.view(), "wb.chat.rendered.boundary"), "Successful Send retained the idle divider");
    wait_for(session, [&] { return std::filesystem::exists(fixture.root / "boundary.request.json"); }, "boundary worker start");
    const auto request = json::parse(read(fixture.root / "boundary.request.json"));
    require(request.find("history")->array().front().find("content")->string() == before_send &&
            before_send.find("Reply complete") == std::string::npos,
            "UI boundary or obsolete completion feedback entered provider history");
    write(fixture.root / "finish", "release");
    wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; }, "boundary final");boundary();
    const auto completed = session.text("wb.chat.text");
    session.activate("tab.left.Chats");session.chat("second.chat.md");session.chat("first.chat.md");
    session.check("wb.developer", true);
    require(widget(session.view(), "wb.chat.text").state.text == completed,
            "Developer opened stale raw text after returning to a completed chat");
    session.edit("wb.chat.text", completed + "\nExplicit history edit.\n");
    session.shortcut("wb.chat.text", gui::ShortcutKey::z);
    require(widget(session.view(), "wb.chat.text").state.text == completed,
            "History Undo restored stale completed editor text");
    session.check("wb.developer", false);boundary();
    for (const auto* prompt : {"failure", "incomplete"}) {
        session.edit("wb.composer", prompt);session.activate("wb.send");
        require(!find(session.view(), "wb.chat.rendered.boundary"), "Running attempt displayed idle feedback");
        wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; }, "stopped attempt boundary");
        boundary();
    }
    session.activate("tab.right.AI");session.edit("ai.model", "");
    session.edit("wb.composer", "Rejected Send keeps its idle boundary.");session.activate("wb.send");
    session.error("Choose a model");boundary();
    session.edit("ai.model", "offline-boundary-model");
    session.edit("wb.composer", "empty-conflict");session.activate("wb.send");
    wait_for(session, [&] { return std::filesystem::exists(fixture.root / "empty-conflict.started"); },
             "empty final conflict launch");
    const auto last_saved = read(project / "first.chat.md");
    write(project / "first.chat.md", "# Independently changed source\n");
    write(fixture.root / "empty-conflict.finish", "release");
    wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; }, "empty conflicting final");
    require(session.text("wb.chat.text") == last_saved &&
            widget(session.view(), "wb.status").state.font.tone == gui::Tone::error &&
            !find(session.view(), "wb.chat.rendered.boundary") &&
            read(project / "first.chat.md") == "# Independently changed source\n",
            "Empty final save conflict displayed a confidently saved boundary or overwrote disk");
    session.activate("tab.left.Chats");session.chat("second.chat.md");
    session.activate("wb.split");session.choose("wb.split.path", "first.chat.md");
    require(!find(session.view(), "wb.split.rendered.boundary"), "Unsaved conflicting history displayed a saved boundary");
    session.application->shutdown();
    Session restarted(project, "second.chat.md");
    require(find(restarted.view(), "wb.chat.rendered.boundary") &&
            !find(restarted.view(), "wb.chat.rendered.complete"),
            "Saved idle boundary did not reconstruct independently of transient state");
#endif
}

void submitted_composer_is_the_only_agent_plan() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto worker = offline_chat_worker(fixture.root);
    const std::string transcript = "# History\n\n## User\n\n```pseudocode\nagent history: Never run history.\n```\n";
    write(project / "chat.chat.md", transcript);
    Workspace workspace(project);
    auto chat = workspace.open_chat("chat.chat.md");
    chat.state.pseudocode = "agent sidecar: Never run a separate plan.\n";
    chat.state.ai.provider = "ollama";
    chat.state.ai.model = "offline-agent-fixture";
    chat.state.ai_configured = true;
    workspace.save_state(chat);
    Session session(project, "chat.chat.md", {}, true, worker);
    session.activate("tab.center.Pseudocode Editor");
    require(session.text("wb.flow.text").empty(), "History or sidecar silently supplied an active agent plan");
    session.activate("tab.center.Chat Markdown");
    session.choose("wb.agentic", "true");
    const auto launches = fixture.root / "chat.chat.md.launches";
    const auto reject = [&](const std::string& draft, std::string_view error) {
        session.edit("wb.composer", draft);
        session.activate("wb.send");
        session.error(error);
        require(session.text("wb.composer") == draft && session.text("wb.chat.text") == transcript &&
                read(project / "chat.chat.md") == transcript && !std::filesystem::exists(launches),
                "Rejected Agentic input launched a worker, consumed its draft or changed history");
    };
    reject("Run the saved workflow.", "fenced pseudocode block in the current message");
    reject("```pseudocode\nagent draft: Unclosed plan.\n", "Close the pseudocode fence");
    reject("```pseudocode\nagent one: First plan.\n```\n~~~flow\nagent two: Second plan.\n~~~\n",
           "exactly one pseudocode block");
    reject("```pseudocode\nrepeat 2\n  agent writer: Missing until.\n```\n", "Repair the pseudocode syntax");
    reject("````text\n```pseudocode\nagent quoted: An inert example.\n```\n````\n", "fenced pseudocode block");
    reject("    ```pseudocode\nagent indented: An inert indented example.\n    ```\n", "fenced pseudocode block");
    reject("````flow\nagent writer: Short closing marker.\n```\n", "Close the pseudocode fence");
    const std::string source = "# Keep exact boundary bytes\nagent submitted: Use only this composer plan.\n\n";
    for (const auto& framing : {std::pair{"```pseudocode\n", "```\n"},
                                std::pair{"~~~~flow\n", "~~~~~\n"},
                                std::pair{"   ```tinyenv\n", "   ```\n"}}) {
        const auto draft = std::string("Current message.\n\n") + framing.first + source + framing.second;
        session.edit("wb.composer", draft);
        const auto before = session.text("wb.chat.text");
        session.shortcut("wb.composer", gui::ShortcutKey::enter);
        require(session.text("wb.composer").empty(), "Ctrl+Enter did not consume exactly one submitted composer");
        const auto epoch = session.application->input_epoch();
        gui::ShortcutEvent repeated{gui::ShortcutKey::enter, true, false, false};
        require(session.adapter.send(repeated) == gui::Delivery::ignored && session.application->input_epoch() == epoch,
                "Repeated Ctrl+Enter sent an empty composer or advanced application state");
        wait_for(session, [&] { return !widget(session.view(), "wb.cancel").state.enabled; }, "offline agent request completion");
        session.success("submitted composer fake-worker completion");
        const auto request = json::parse(read(fixture.root / "chat.chat.md.request.json"));
        require(request.find("operation")->string() == "agent" && request.find("prompt")->string() == draft &&
                request.find("pseudocode")->string() == source &&
                request.find("history")->array().front().find("content")->string() == before &&
                !request.find("settings")->find("zdr"),
                "The agent request used history/sidecar, changed exact submitted bytes, or retained ZDR payload");
        require(session.text("wb.chat.text").starts_with(before + "\n## User\n\n" + draft + "\n") &&
                session.text("wb.chat.text").find("Local fixture answer.") != std::string::npos,
                "Submitting a composer failed to record its message once and publish the local response");
        session.activate("tab.center.Pseudocode Editor");
        require(session.text("wb.flow.text").empty(), "Consumed composer left an executable historical plan active");
        session.activate("tab.center.Chat Markdown");
    }
    require(read(launches) == "launch\nlaunch\nlaunch\n", "Ctrl+Enter launched a duplicate fake worker");
#endif
}

void task_context_cancels_its_exact_owner() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto worker = offline_chat_worker(fixture.root);
    write(project / "first.chat.md", "# First task\n");
    write(project / "second.chat.md", "# Second task\n");
    Workspace seed_workspace(project);
    for (const auto* path : {"first.chat.md", "second.chat.md"}) {
        auto chat = seed_workspace.open_chat(path);
        chat.state.ai.provider = "ollama";
        chat.state.ai.model = "offline-task-fixture";
        chat.state.ai_configured = true;
        seed_workspace.save_state(chat);
    }
    Session session(project, "first.chat.md", {}, true, worker);
    session.edit("wb.composer", "hold: first owner");
    session.activate("wb.send");
    wait_for(session, [&] { return std::filesystem::exists(fixture.root / "first.chat.md.launches"); }, "first local task launch");
    const auto first_chat_cancel = widget(session.view(), "wb.cancel").spec.key;
    session.chat("second.chat.md");
    session.edit("wb.composer", "hold: second owner");
    session.activate("wb.send");
    wait_for(session, [&] { return std::filesystem::exists(fixture.root / "second.chat.md.launches"); }, "second local task launch");
    session.activate("tab.left.Running Tasks");
    const auto first = task_id(session, "first.chat.md", "Running");
    const auto second = task_id(session, "second.chat.md", "Running");
    task_menu(session, first);
    const auto old_cancel = widget(session.view(), "task.cancel").spec.key;
    session.escape();
    require(!session.view().modal_root && session.text("wb.chat.text").starts_with("# Second task\n"),
            "Escape from a task context menu changed the active chat");
    task_menu(session, second);
    require(session.adapter.send(gui::WidgetEvent{old_cancel, gui::Activate{}}) == gui::Delivery::ignored &&
            widget(session.view(), "task.cancel").state.enabled,
            "A stale task menu identity cancelled another task");
    session.escape();
    task_menu(session, first);
    const auto predecessor_cancel = widget(session.view(), "task.cancel").spec.key;
    session.activate("task.cancel");
    session.success("cancel targeted first task");
    require(task_id(session, "first.chat.md", "Cancelled") == first &&
            task_id(session, "second.chat.md", "Running") == second &&
            session.text("wb.chat.text").starts_with("# Second task\n"),
            "Right-click Cancel stopped the current chat instead of the clicked task");
    task_menu(session, first);
    require(!widget(session.view(), "task.cancel").state.enabled,
            "A completed task retained an enabled Cancel action");
    session.activate("task.show");
    require(session.text("wb.chat.text").starts_with("# First task\n"),
            "Task Show did not open the clicked task's owning chat");
    session.activate("tab.left.Chats");
    session.edit("wb.composer", "hold: first successor");
    session.activate("wb.send");
    wait_for(session, [&] { return read(fixture.root / "first.chat.md.launches") == "launch\nlaunch\n"; }, "successor local task launch");
    require(session.adapter.send(gui::WidgetEvent{first_chat_cancel, gui::Activate{}}) == gui::Delivery::ignored &&
            widget(session.view(), "wb.cancel").state.enabled,
            "A stale chat Cancel control stopped that chat's successor task");
    session.chat("second.chat.md");
    session.activate("tab.left.Running Tasks");
    const auto successor = task_id(session, "first.chat.md", "Running");
    require(successor != first, "A successor task reused its predecessor's immutable identity");
    task_menu(session, successor);
    require(session.adapter.send(gui::WidgetEvent{predecessor_cancel, gui::Activate{}}) == gui::Delivery::ignored &&
            widget(session.view(), "task.cancel").state.enabled,
            "A stale predecessor action cancelled the same chat's successor task");
    session.activate("task.cancel");
    require(task_id(session, "first.chat.md", "Cancelled") == successor &&
            task_id(session, "second.chat.md", "Running") == second,
            "Cancelling a successor changed another task");
    session.select("wb.tasks", second);
    session.activate("wb.task.cancel");
    require(task_id(session, "second.chat.md", "Cancelled") == second,
            "The task footer ignored the selected task identity");
    const auto bounds = widget(session.view(), "wb.tasks").state.bounds;
    session.pointer("wb.tasks", {bounds.x + 12, bounds.y + bounds.height - 10}, gui::PointerKind::context_menu);
    require(!session.view().modal_root, "Right-clicking empty task-list space targeted an unrelated task");
#endif
}

void initial_and_tabs(const std::filesystem::path& captures) {
    Temporary fixture;
    {
        Session empty(fixture.root);
        require(find(empty.view(), "wb.empty") && !find(empty.view(), "wb.chat.text"),
                "Empty workspace did not show its start state");
        require(inventory(fixture.root).empty(), "Empty application construction wrote project files");
        for (const auto* id : {"wb.tutorial", "wb.developer"})
            require(find(empty.view(), id) && !widget(empty.view(), id).state.checked,
                    "An empty workspace hid or enabled a global mode by default");
    }
    const std::string original = "\xef\xbb\xbf# Research café\r\n\r\nOrdinary Markdown.\r\n";
    write(fixture.root / "first.chat.md", original);
    write(fixture.root / "second.chat.md", "# Second\n");
    write(fixture.root / "assets/data.txt", "local data\n");
    const auto before = inventory(fixture.root);
    Session session(fixture.root, "first.chat.md");
    require(session.text("wb.chat.text") == original, "Application launch changed Markdown bytes");
    session.chat("second.chat.md");
    session.chat("first.chat.md");
    require(inventory(fixture.root) == before, "Opening pristine chats created companion files");
    const auto left = widget(session.view(), "wb.left").state.bounds;
    const auto middle = widget(session.view(), "wb.center").state.bounds;
    const auto right = widget(session.view(), "wb.right").state.bounds;
    require(left.x + left.width <= middle.x && middle.x + middle.width <= right.x,
            "Workbench panes overlap");
    for (const auto* id : {"tab.left.Chats", "tab.left.Files", "tab.left.Filelight",
                           "tab.left.Running Tasks", "tab.center.Chat Markdown",
                           "tab.center.Pseudocode Editor", "tab.center.Bash Terminal",
                           "tab.right.Git", "tab.right.Sources", "tab.right.Selector",
                           "tab.right.Pseudocode", "tab.right.Prompts", "tab.right.AI"})
        require(widget(session.view(), id).spec.kind == gui::Kind::button, "Missing workbench tab");
    capture(session.view(), captures, "workbench-chat");
    session.activate("tab.left.Running Tasks");
    require(widget(session.view(), "wb.tasks").state.records.empty(),
            "Application construction launched a background task");
    session.activate("tab.left.Filelight");
    require(widget(session.view(), "wb.disk.canvas").spec.kind == gui::Kind::bitmap,
            "Filelight did not declare its shared bitmap");
    capture(session.view(), captures, "workbench-disk");
    const auto disk_directory = std::find_if(session.view().widgets.begin(), session.view().widgets.end(),
        [](const auto& item) { return item.spec.key.id.starts_with("wb.disk.legend.") &&
                                    item.state.accessible_name.starts_with("assets/"); });
    require(disk_directory != session.view().widgets.end(), "Filelight omitted the fixture directory");
    const auto directory_point = center(disk_directory->state.bounds);
    session.pointer("wb.disk.canvas", directory_point, gui::PointerKind::press);
    session.pointer("wb.disk.canvas", directory_point, gui::PointerKind::cancel);
    gui::PointerInput orphan_release;
    orphan_release.kind = gui::PointerKind::release;
    orphan_release.position = directory_point;
    orphan_release.pointer_id = 1;
    require(session.adapter.send(gui::WidgetEvent{
                widget(session.view(), "wb.disk.canvas").spec.key, orphan_release}) == gui::Delivery::ignored,
            "Cancelled disk gesture accepted an orphaned release");
    session.presented("cancelled disk gesture");
    require(session.text("wb.path") == ".", "Cancelled disk input navigated the browser");
    session.click("wb.disk.canvas", directory_point);
    require(session.text("wb.path") == "assets", "Physical disk selection did not open its directory");
    session.activate("wb.back");
    session.activate("tab.left.Chats");
    session.activate("tab.right.Sources");
    require(widget(session.view(), "wb.sources").spec.text_policy.read_only,
            "Source provenance is editable");
    session.activate("wb.split");
    session.choose("wb.split.path", "second.chat.md");
    require(!find(session.view(), "wb.split.text") && find(session.view(), "wb.split.rendered") &&
            session.rendered_text("wb.split.rendered") == "Second\n",
            "Split view did not present a read-only second chat");
    session.activate("wb.split");
    require(!find(session.view(), "wb.split.text") && !find(session.view(), "wb.split.rendered"),
            "Split view did not close");
    session.activate("tab.right.Selector");
    session.application->qualify([&] { session.presented("local qualification"); });
    session.success("local qualification");
    require(inventory(fixture.root) == before,
            "Construction, local tab navigation or qualification wrote project files");
}

void normal_transcript_is_passive_markdown() {
    Temporary fixture;
    const std::string source = "# Readable heading\n\nPlain evidence.\n\n- First item\n- Second item\n\n"
        "> Quoted answer.\n\n```cpp\nint answer = 42;\n```\n\n"
        "<script>alert('inert')</script>\n[remote](https://invalid.example/) ![image](https://invalid.example/pixel)\n";
    write(fixture.root / "chat.chat.md", source);
    const auto files = inventory(fixture.root);
    Session session(fixture.root, "chat.chat.md");
    require(!find(session.view(), "wb.chat.text") &&
            widget(session.view(), "wb.chat.rendered").spec.kind == gui::Kind::group &&
            widget(session.view(), "wb.chat.rendered").state.accessible_name == "Passive Markdown preview" &&
            session.text("wb.chat.text") == source && read(fixture.root / "chat.chat.md") == source,
            "Normal transcript exposed a raw editor or changed its original Markdown");
    const gui::Widget* heading{};
    const gui::Widget* paragraph{};
    const gui::Widget* code{};
    std::size_t blocks{};
    for (const auto& item : session.view().widgets) {
        if (!item.spec.key.id.starts_with("wb.chat.rendered.block.")) continue;
        ++blocks;
        require(item.spec.kind == gui::Kind::text && item.spec.text_policy.read_only &&
                item.spec.text_policy.submit == gui::SubmitKey::none,
                "Passive Markdown emitted an interactive or editable content block");
        if (item.state.text == "Readable heading") heading = &item;
        if (item.state.text == "Plain evidence.") paragraph = &item;
        if (item.state.text.find("int answer = 42;") != std::string::npos) code = &item;
    }
    const auto rendered = session.rendered_text();
    require(blocks >= 6 && heading && paragraph && code && heading->state.font.bold &&
            heading->state.font.size > paragraph->state.font.size &&
            code->state.text.find("```") == std::string::npos &&
            rendered.find("- First item") != std::string::npos &&
            rendered.find("Quoted answer.") != std::string::npos &&
            rendered.find("<script>alert('inert')</script>") != std::string::npos &&
            rendered.find("[remote](https://invalid.example/)") != std::string::npos &&
            rendered.find("![image](https://invalid.example/pixel)") != std::string::npos,
            "Passive transcript did not distinguish heading/list/quote/code or preserve unsupported HTML/links as literal text");
    const auto epoch = session.application->input_epoch();
    require(session.adapter.send(gui::WidgetEvent{code->spec.key,
                gui::EditText{"Edited code", code->state.text}}) == gui::Delivery::ignored &&
            session.application->input_epoch() == epoch && !session.application->next_service() &&
            inventory(fixture.root) == files && session.text("wb.chat.text") == source,
            "Passive transcript editing/navigation executed content, changed source or wrote project files");
    session.check("wb.developer", true);
    require(find(session.view(), "wb.chat.text") &&
            !widget(session.view(), "wb.chat.text").spec.text_policy.read_only &&
            session.text("wb.chat.text") == source,
            "Developer did not explicitly expose the original editable Markdown");
    session.check("wb.developer", false);
    require(!find(session.view(), "wb.chat.text") && find(session.view(), "wb.chat.rendered") &&
            session.text("wb.chat.text") == source,
            "Disabling Developer failed to restore the passive transcript");
}

void transcript_scroll_positions_are_owned_by_chat_and_split_source() {
    Temporary fixture;
    const auto first = long_transcript("First");
    const auto second = long_transcript("Second", 55);
    const auto third = long_transcript("Third", 60);
    write(fixture.root / "first.chat.md", first);
    write(fixture.root / "second.chat.md", second);
    write(fixture.root / "third.chat.md", third);
    Session session(fixture.root, "first.chat.md");
    require(transcript_maximum(session) > 500 && !find(session.view(), "wb.chat.busy"),
            "Long transcript fixture did not overflow or showed a busy marker without a job");
    require_transcript_tail(session, "First final tail.");
    session.edit("wb.composer", "Unsent draft stays with the first chat.");
    const auto composer = widget(session.view(), "wb.composer").spec.key;
    require(session.adapter.focus(composer), "Could not focus the scrollback fixture composer");
    session.adapter.text_selection(composer, {6, 11});
    scroll_transcript(session, 300);
    near(transcript_offset(session), 300, "Scrolling up did not pause at the requested main offset");
    require(!rendered_block_visible(session, "First final tail.") && session.adapter.focused() == composer &&
            session.adapter.text_selection(composer) == gui::TextSelection{6, 11},
            "Scrollback followed the tail again or moved composer focus/selection");
    session.activate("tab.center.Pseudocode Editor");
    session.activate("tab.center.Chat Markdown");
    near(transcript_offset(session), 300, "Changing center tabs lost the main scrollback position");
    session.activate("wb.split");
    session.choose("wb.split.path", "second.chat.md");
    require_transcript_tail(session, "Second final tail.", "wb.split.rendered");
    near(transcript_offset(session), 300, "Opening a split reset the main paused position");
    scroll_transcript(session, 160, "wb.split.rendered");
    session.choose("wb.split.path", "third.chat.md");
    require_transcript_tail(session, "Third final tail.", "wb.split.rendered");
    scroll_transcript(session, 240, "wb.split.rendered");
    session.choose("wb.split.path", "second.chat.md");
    near(transcript_offset(session, "wb.split.rendered"), 160,
         "Changing split source lost its independently paused position");
    near(transcript_offset(session), 300, "Split source scrolling changed the main transcript offset");
    session.activate("tab.center.Pseudocode Editor");
    session.activate("tab.center.Chat Markdown");
    near(transcript_offset(session), 300, "Changing tabs with a split open lost the main position");
    near(transcript_offset(session, "wb.split.rendered"), 160,
         "Changing center tabs lost the split source's scrollback position");
    session.activate("wb.split");
    session.activate("wb.split");
    session.choose("wb.split.path", "second.chat.md");
    near(transcript_offset(session, "wb.split.rendered"), 160, "Closing/reopening the split lost scrollback");
    session.chat("second.chat.md");
    require_transcript_tail(session, "Second final tail.");
    scroll_transcript(session, 500);
    session.activate("wb.split");
    session.choose("wb.split.path", "first.chat.md");
    require_transcript_tail(session, "First final tail.", "wb.split.rendered");
    scroll_transcript(session, 90, "wb.split.rendered");
    session.chat("first.chat.md");
    session.choose("wb.split.path", "second.chat.md");
    near(transcript_offset(session), 300, "Returning to a chat lost its main paused position");
    near(transcript_offset(session, "wb.split.rendered"), 160,
         "Another owner's split reused or erased this owner's saved position");
    require(session.text("wb.composer") == "Unsent draft stays with the first chat.",
            "Restoring transcript positions replaced the chat's unsent draft");
    session.chat("second.chat.md");
    session.choose("wb.split.path", "first.chat.md");
    near(transcript_offset(session), 500, "One chat's offset leaked into another chat");
    near(transcript_offset(session, "wb.split.rendered"), 90,
         "Split positions were keyed only by source instead of owning chat and source");
    require(!session.application->next_service() && read(fixture.root / "first.chat.md") == first &&
            read(fixture.root / "second.chat.md") == second && read(fixture.root / "third.chat.md") == third,
            "Passive transcript scrolling requested a service or mutated history");
}

// Native hosts can settle wrapped scroll ranges after a snapshot is staged.
// This adapter preserves its current text offset while that range changes;
// unlike synchronous MemoryAdapter, growth does not move the old end itself.
struct StagedRangeAdapter final : gui::Adapter {
    gui::FramebufferAdapter metrics;
    gui::MemoryAdapter retained;
    gui::WidgetKey body;
    double maximum = 0, offset = 0, applied_maximum = 0;
    bool staged = false, snapshot_staged = false;
    std::optional<double> pending;
    explicit StagedRangeAdapter(gui::EventSink sink):retained(std::move(sink),64*1024*1024,
        [this](const gui::TextMeasureRequest& request){return metrics.measure_text(request);}) {}
    void range(double value){maximum=value;offset=std::min(offset,maximum);}
    void native_range(double estimate,double applied){staged=true;maximum=estimate;applied_maximum=applied;offset=std::min(offset,applied_maximum);}
    void settle(){if(pending){offset=std::clamp(*pending,0.0,applied_maximum);pending.reset();}snapshot_staged=false;}
    void wheel_to(double value){pending.reset();offset=std::clamp(value,0.0,applied_maximum);}
    void present(gui::Snapshot value) override {if(staged)snapshot_staged=true;retained.present(std::move(value));}
    gui::Size measure_text(const gui::TextMeasureRequest& value) const override{return retained.measure_text(value);}
    gui::Availability resolved_availability(const gui::WidgetKey& key) const override{return retained.resolved_availability(key);}
    std::optional<gui::WidgetKey> focused() const override{return retained.focused();}
    bool focus(std::optional<gui::WidgetKey> key) override{return retained.focus(std::move(key));}
    bool focus_next(bool reverse=false) override{return retained.focus_next(reverse);}
    void scroll(const gui::WidgetKey& key,gui::Point value) override {
        retained.scroll(key,value);if(key==body){if(staged&&snapshot_staged)pending=value.y;else {pending.reset();offset=std::clamp(value.y,0.0,staged?applied_maximum:maximum);}}
    }
    gui::Point scroll_offset(const gui::WidgetKey& key) const override {
        const auto value=retained.scroll_offset(key);return key==body?gui::Point{value.x,pending?std::clamp(*pending,0.0,snapshot_staged?maximum:applied_maximum):offset}:value;
    }
    gui::TextSelection text_selection(const gui::WidgetKey& key) const override{return retained.text_selection(key);}
    void text_selection(const gui::WidgetKey& key,gui::TextSelection value) override{retained.text_selection(key,value);}
    bool open_popup(const gui::WidgetKey& key) override{return retained.open_popup(key);}
    void close_popup(const gui::WidgetKey& key) override{retained.close_popup(key);}
    void invalidate(const gui::WidgetKey& key,gui::PixelRect value) override{retained.invalidate(key,value);}
    bool closed() const override{return retained.closed();}
    void close() override{retained.close();}
};

void following_survives_settling_ranges_and_respects_scroll_up() {
    Temporary fixture;
    const auto source=long_transcript("Staged range",20)+"\n"+std::string(4000,'a')+"\n";
    write(fixture.root/"chat.chat.md",source);
    configure_launch(fixture.root,"chat.chat.md",{},fixture.root/".preferences");
    Application* callback_app=nullptr;
    StagedRangeAdapter adapter([&](const gui::Event& event){callback_app->handle(event);});
    auto app=std::make_unique<Application>(adapter);callback_app=app.get();
    for(const auto& item:app->view().widgets)
        if(item.spec.kind==gui::Kind::text&&item.spec.parent=="wb.chat.rendered")adapter.body=item.spec.key;
    require(!adapter.body.id.empty(),"Staged-range fixture has no tail text body");
    const auto composer=widget(app->view(),"wb.composer").spec.key;
    require(adapter.focus(composer),"Cannot focus staged-range composer");adapter.text_selection(composer,{0,0});
    const auto revision=app->view().revision;
    adapter.range(80);adapter.scroll(adapter.body,{0,80});app->tick();
    adapter.range(240);app->tick();
    near(adapter.scroll_offset(adapter.body).y,240,"Stationary old end was mistaken for scrolling up as the wrapped range grew");
    adapter.range(360);app->tick();
    near(adapter.scroll_offset(adapter.body).y,360,"Follow reconciliation stopped before the native range settled");
    app->tick();
    require(app->view().revision==revision&&adapter.focused()==composer,
            "Native-range reconciliation rebuilt the UI or moved composer focus");
    app->handle(gui::ResizeEvent{{app->view().client_size.width+10,app->view().client_size.height},1});
    adapter.range(40);app->tick();
    near(adapter.scroll_offset(adapter.body).y,40,"A shrinking native clamp changed follow intent");
    adapter.scroll(adapter.body,{0,20});app->tick();
    near(adapter.scroll_offset(adapter.body).y,20,"Follow probes overrode a deliberate upward reader movement");
    adapter.range(160);app->tick();
    near(adapter.scroll_offset(adapter.body).y,20,"Growing text forced an intentionally paused reader to the end");
    app->handle(gui::ResizeEvent{app->view().client_size,1});
    near(adapter.scroll_offset(adapter.body).y,20,"Paused reader position was discarded by repaint");
    adapter.scroll(adapter.body,{0,160});app->tick();
    app->handle(gui::ResizeEvent{{app->view().client_size.width+10,app->view().client_size.height},1});
    adapter.range(280);app->tick();
    near(adapter.scroll_offset(adapter.body).y,280,"Reaching the actual end did not resume following subsequent growth");
    require(adapter.focused()==composer&&adapter.text_selection(composer)==gui::TextSelection{0,0}&&
            read(fixture.root/"chat.chat.md")==source,
            "Follow reconciliation changed text, focus or selection");
    app->shutdown();
}

void following_uses_current_layout_clamps_and_preserves_immediate_input() {
    Temporary fixture;
    const auto source=long_transcript("Projected range",20)+"\n"+std::string(4000,'a')+"\n";
    write(fixture.root/"chat.chat.md",source);
    configure_launch(fixture.root,"chat.chat.md",{},fixture.root/".preferences");
    Application* callback_app=nullptr;
    StagedRangeAdapter adapter([&](const gui::Event& event){callback_app->handle(event);});
    auto app=std::make_unique<Application>(adapter);callback_app=app.get();
    for(const auto& item:app->view().widgets)
        if(item.spec.kind==gui::Kind::text&&item.spec.parent=="wb.chat.rendered")adapter.body=item.spec.key;
    require(!adapter.body.id.empty(),"Projected-range fixture has no tail text body");
    const auto composer=widget(app->view(),"wb.composer").spec.key;
    require(adapter.focus(composer),"Cannot focus projected-range composer");adapter.text_selection(composer,{0,0});
    const auto reflow=[&]{app->handle(gui::ResizeEvent{{app->view().client_size.width+10,app->view().client_size.height},1});};
    const auto tick=[&]{app->tick();adapter.settle();};
    // An estimated pre-sync clamp need not match the applied wrapped row.
    // A settled scrollbar can advertise an extra blank row; the adapter's
    // current-layout clamp must report the reachable applied end instead.
    adapter.native_range(21.6,17);reflow();
    near(adapter.scroll_offset(adapter.body).y,21.6,"Fixture did not expose the estimated queued clamp");
    adapter.settle();adapter.native_range(34,17);
    tick();tick();tick();
    near(adapter.scroll_offset(adapter.body).y,17,"Fixture did not settle to the applied native bottom");
    adapter.native_range(136,119);reflow();adapter.settle();
    near(adapter.scroll_offset(adapter.body).y,119,"Saturated layout did not apply the actual reachable end");
    adapter.wheel_to(102);tick();
    near(adapter.scroll_offset(adapter.body).y,102,
         "Upward input before the first growth sample was overridden");
    adapter.native_range(170,153);reflow();adapter.settle();tick();tick();
    near(adapter.scroll_offset(adapter.body).y,102,"Later growth overrode a deliberately paused reader");
    adapter.scroll(adapter.body,{0,gui::coordinate_limit});adapter.settle();tick();tick();
    near(adapter.scroll_offset(adapter.body).y,153,"Already applied actual-end input did not resume following");
    // Ordinary callbacks publish before the host's timer invokes App.tick,
    // and the host applies their native snapshot after that tick.
    adapter.native_range(204,187);reflow();tick();tick();tick();
    near(adapter.scroll_offset(adapter.body).y,187,"Callback before timer did not preserve following");
    adapter.native_range(238,221);reflow();adapter.settle();tick();tick();
    near(adapter.scroll_offset(adapter.body).y,221,"Native settling paused following after a callback");
    require(adapter.focused()==composer&&adapter.text_selection(composer)==gui::TextSelection{0,0}&&
            read(fixture.root/"chat.chat.md")==source,
            "Projected-range reconciliation changed text, focus or selection");
    app->shutdown();
}

void chats_and_conflicts(const std::filesystem::path& captures) {
    Temporary fixture;
    write(fixture.root / "first.chat.md", "# First\n");
    write(fixture.root / "second.chat.md", "# Second\n");
    Session session(fixture.root, "first.chat.md");
    require(!find(session.view(), "wb.chat.text") && find(session.view(), "wb.chat.rendered") &&
            !widget(session.view(), "wb.developer").state.checked &&
            !find(session.view(), "wb.save") && !find(session.view(), "wb.copy"),
            "Default chat history is editable or still exposes manual chat save controls");
    const auto original_key = widget(session.view(), "wb.chat.rendered").spec.key;
    const auto epoch = session.application->input_epoch();
    require(session.adapter.send(gui::WidgetEvent{original_key,
                gui::EditText{"A refused edit", "# First\n"}}) == gui::Delivery::ignored &&
            session.application->input_epoch() == epoch && session.text("wb.chat.text") == "# First\n",
            "The normal adapter allowed a default read-only transcript edit");
    session.check("wb.developer", true);
    require(!widget(session.view(), "wb.chat.text").spec.text_policy.read_only &&
            AiPreferences(fixture.root / ".preferences").developer_mode(),
            "Developer mode did not enable transcript editing or persist its preference");
    const std::string edited = "# First\n\nEdited café and evidence.\n";
    session.edit("wb.chat.text", edited);
    require(read(fixture.root / "first.chat.md") == "# First\n" &&
            session.view().title.ends_with(" *"), "A transcript edit bypassed the save debounce or lost its dirty marker");
    session.autosave();
    session.success("debounced chat save");
    require(read(fixture.root / "first.chat.md") == edited && !session.view().title.ends_with(" *"),
            "Debounced checked save changed transcript bytes or retained dirty state");
    const std::string retained = "# First\n\nUnsaved recovery text.\n";
    std::string external = "# External editor\n";
    external.resize(retained.size(), ' ');
    session.edit("wb.chat.text", retained);
    session.edit("wb.composer", "Retained conflict draft.");
    write(fixture.root / "first.chat.md", external);
    session.autosave();
    session.error("changed");
    require(session.text("wb.chat.text") == retained &&
            read(fixture.root / "first.chat.md") == external,
            "Autosave conflict lost edits or replaced external text");
    capture(session.view(), captures, "workbench-chat-conflict");
    session.chat("second.chat.md");
    session.chat("first.chat.md");
    require(session.text("wb.chat.text") == retained &&
            read(fixture.root / "first.chat.md") == external,
            "Switching away from a conflicted chat lost the retained buffer or overwrote external text");
    session.application->handle(gui::CloseEvent{});
    session.error("changed");
    require(!session.adapter.closed() && session.text("wb.chat.text") == retained &&
            read(fixture.root / "first.chat.md") == external,
            "Closing a conflicted chat discarded the buffer or bypassed checked saving");
    session.activate("tab.left.Files");
    session.select("wb.files", "first.chat.md");
    session.activate("wb.file.actions");
    require(!widget(session.view(), "actions.copy").state.enabled &&
            widget(session.view(), "actions.copy-retained").state.enabled &&
            widget(session.view(), "actions.discard-retained").state.enabled,
            "A conflicted chat did not expose explicit retained-buffer recovery actions");
    session.activate("actions.copy-retained");
    session.edit("prompt.value", ".tinyenv/recovery.chat.md");
    session.submit("prompt.value");
    require(session.view().modal_root && session.text("modal.message").find("private") != std::string::npos &&
            !std::filesystem::exists(fixture.root / ".tinyenv/recovery.chat.md") &&
            session.text("wb.chat.text") == retained && session.text("wb.composer") == "Retained conflict draft.",
            "Retained-buffer Copy wrote a private destination or lost the editable recovery prompt");
    session.edit("prompt.value", "recovered.chat.md");
    session.submit("prompt.value");
    const auto recovered = Workspace(fixture.root).open_chat("recovered.chat.md");
    require(!session.view().modal_root && record(widget(session.view(), "wb.files"), "recovered.chat.md") &&
            recovered.text == retained && recovered.state.draft == "Retained conflict draft." &&
            session.text("wb.chat.text") == retained && session.text("wb.composer") == "Retained conflict draft." &&
            session.view().title.find("first.chat.md") != std::string::npos &&
            read(fixture.root / "first.chat.md") == external,
            "File-browser recovery lost the draft, changed the active chat or overwrote the conflicted original");
    session.error("Autosave conflict");
    require(session.text("wb.status").find("Copied retained chat and draft to recovered.chat.md.") != std::string::npos,
            "Successful recovery did not report its copy while preserving the original autosave conflict");
    session.activate("wb.file.actions");
    session.activate("actions.discard-retained");
    session.escape();
    require(session.text("wb.chat.text") == retained && session.text("wb.composer") == "Retained conflict draft.",
            "Cancelling retained-buffer discard lost local recovery text");
    session.activate("tab.left.Chats");session.chat("second.chat.md");
    session.activate("wb.split");session.choose("wb.split.path", "first.chat.md");
    require(session.rendered_text("wb.split.rendered").find("Unsaved recovery text.") != std::string::npos,
            "Same-length reload fixture did not prime the retained passive preview");
    session.activate("tab.left.Files");session.select("wb.files", "first.chat.md");
    session.activate("wb.file.actions");
    session.activate("actions.discard-retained");
    session.activate("discard-retained.accept");
    session.success("discard retained changes and reload external chat");
    require(Workspace(fixture.root).open_chat("first.chat.md").text == external &&
            read(fixture.root / "recovered.chat.md") == retained,
            "Explicit discard failed to reload external bytes or changed the retained recovery copy");
    require(session.rendered_text("wb.split.rendered").find("External editor") != std::string::npos &&
            session.rendered_text("wb.split.rendered").find("Unsaved recovery text.") == std::string::npos,
            "Same-length disk reload retained an obsolete passive preview");
    session.activate("tab.left.Chats");session.chat("first.chat.md");
    require(session.text("wb.chat.text") == external && session.text("wb.composer").empty(),
            "Discarded inactive chat retained obsolete raw source or composer draft");
    session.chat("second.chat.md");
    session.activate("wb.new");
    session.edit("prompt.value", "new/session.chat.md");
    session.activate("prompt.accept");
    session.success("new chat");
    require(read(fixture.root / "new/session.chat.md") == "# session\n\n" &&
            record(widget(session.view(), "wb.chats"), "new/session.chat.md"),
            "New chat was not created and listed");
}

void independent_chat_state(const std::filesystem::path& captures) {
    Temporary fixture;
    write(fixture.root / "first.chat.md", "# First\n");
    write(fixture.root / "second.chat.md", "# Second\n");
    Session session(fixture.root, "first.chat.md");
    session.edit("wb.composer", "First chat draft.\n");
    session.choose("selector.deep", "true");
    session.edit("selector.path", "knowledge/expertise.md");
    session.submit("selector.path");
    session.select("selector.paths", "knowledge/expertise.md");
    session.activate("selector.toggle");
    session.choose("selector.kind", "tools");
    session.edit("selector.path", "builtinTools/Web Search");
    session.activate("selector.add");
    session.activate("selector.save");
    session.activate("tab.right.AI");
    session.choose("ai.provider", "ollama");
    session.edit("ai.model", "fixture-model");
    session.edit("ai.num_predict", "384");
    session.edit("ai.num_ctx", "4096");
    session.edit("ai.num_keep", "64");
    session.edit("ai.temperature", "0.4");
    session.edit("ai.top_p", "0.85");
    session.choose("ai.web", "true");
    require(!find(session.view(), "ai.nitro"), "Ollama exposed OpenRouter-only Nitro routing");
    session.activate("ai.apply");
    session.success("AI settings save");
    capture(session.view(), captures, "workbench-ai");
    session.chat("second.chat.md");
    require(session.text("wb.composer").empty(), "Chat switching leaked the first composer draft");
    require(widget(session.view(), "selector.deep").state.selected == "false",
            "Chat switching leaked Deep Research");
    session.choose("selector.kind", "scribbles");
    require(widget(session.view(), "selector.paths").state.records.empty(),
            "Chat switching leaked context paths");
    session.edit("wb.composer", "Second chat draft.");
    session.edit("selector.path", "examples/second");
    session.activate("selector.add");
    session.activate("tab.right.AI");
    require(widget(session.view(), "ai.provider").state.selected == "ollama" &&
            session.text("ai.model") == "fixture-model" && session.text("ai.num_predict") == "384",
            "An unconfigured chat did not inherit the last explicitly applied AI defaults");
    session.choose("ai.provider", "openai");
    session.edit("ai.model", "second-model");
    session.activate("ai.apply");
    session.chat("first.chat.md");
    require(session.text("wb.composer") == "First chat draft.\n" &&
            widget(session.view(), "ai.provider").state.selected == "ollama" &&
            session.text("ai.model") == "fixture-model" && session.text("ai.num_keep") == "64" &&
            !find(session.view(), "ai.nitro"),
            "Returning to a chat did not restore its draft and AI settings");
    session.activate("tab.right.Selector");
    session.choose("selector.kind", "scribbles");
    require(widget(session.view(), "selector.deep").state.selected == "true" &&
            record(widget(session.view(), "selector.paths"), "knowledge/expertise.md") &&
            !record(widget(session.view(), "selector.paths"), "examples/second"),
            "Returning to a chat did not isolate its selectors");
    session.activate("tab.right.Prompts");
    session.activate("snippet.new");
    session.edit("snippet.title", "Evidence check");
    session.edit("snippet.text", "Check each conclusion against its evidence.\n");
    session.activate("snippet.save");
    require(widget(session.view(), "snippet.list").state.records.size() == 1,
            "Prompt snippet was not listed");
    const auto id = widget(session.view(), "snippet.list").state.records.front().id;
    session.caret_at_end("wb.composer");
    const auto composer = session.text("wb.composer");
    session.select("snippet.list", id);
    session.activate_record("snippet.list", id);
    require(session.text("wb.composer") == composer &&
            session.text("snippet.title") == "Evidence check" &&
            session.text("snippet.text") == "Check each conclusion against its evidence.\n",
            "Selecting or activating a prompt snippet inserted it or failed to load its editable fields");
    session.activate("snippet.insert");
    require(session.text("wb.composer") ==
            "First chat draft.\nCheck each conclusion against its evidence.\n",
            "Explicit prompt insertion did not append to this chat's composer");
    session.chat("second.chat.md");
    require(session.text("wb.composer") == "Second chat draft.",
            "Prompt insertion changed another chat's draft");
    Workspace reopened(fixture.root);
    const auto first = reopened.open_chat("first.chat.md");
    const auto second = reopened.open_chat("second.chat.md");
    require(first.state.draft.ends_with("against its evidence.\n") &&
            first.state.selector.scribbles == std::vector<PathToggle>{{"knowledge/expertise.md", false}} &&
            first.state.selector.tools == std::vector<PathToggle>{{"builtinTools/Web Search", true}} &&
            first.state.ai.num_ctx == 4096 && first.state.ai.temperature == 0.4 &&
            second.state.draft == "Second chat draft." && second.state.ai.model == "second-model",
            "Saved companion states did not preserve independent chat settings");
    require(reopened.snippets(SnippetKind::prompts).size() == 1,
            "Prompt snippet was not persisted as project-local data");
}

void remembered_ai_defaults() {
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto config = fixture.root / "user-config";
    write(project / "first.chat.md", "# First configured chat\n");
    write(project / "second.chat.md", "# Second configured chat\n");
    write(project / "unconfigured.chat.md", "# Inherited chat\n");
    {
        Session session(project, "unconfigured.chat.md", config);
        session.activate("tab.right.AI");
        require(widget(session.view(), "ai.provider").state.selected == "openrouter" &&
                session.text("ai.model").empty() &&
                session.text("ai.routing_providers").empty() &&
                widget(session.view(), "ai.routing_providers").state.placeholder ==
                    "Reviewed route selected automatically" && !AiPreferences(config).defaults(),
                "Fresh AI setup selected a model implicitly, hid automatic reviewed routing or saved defaults implicitly");
        session.chat("first.chat.md");
        session.activate("tab.right.AI");
        session.choose("ai.provider", "ollama");
        session.edit("ai.endpoint", "http://127.0.0.1:11434");
        session.edit("ai.model", "first-default");
        session.edit("ai.num_predict", "512");
        session.edit("ai.num_keep", "32");
        session.edit("ai.num_ctx", "8192");
        session.edit("ai.temperature", "0.35");
        session.edit("ai.top_p", "0.9");
        session.choose("ai.web", "true");
        session.activate("ai.apply");
        session.success("remember first AI defaults");
        AiPreferences defaults(config);
        require(defaults.defaults() && defaults.defaults()->provider == "ollama" &&
                defaults.defaults()->model == "first-default" && defaults.defaults()->num_ctx == 8192 &&
                defaults.defaults()->num_keep == 32 && defaults.defaults()->temperature == 0.35 &&
                defaults.defaults()->top_p == 0.9 && defaults.defaults()->web_search,
                "Explicit Apply did not persist the relevant Ollama configuration");
        const auto saved_defaults = inventory(config);
        session.edit("ai.num_predict", "0");
        session.activate("ai.apply");
        session.error("between 1 and 65536");
        require(inventory(config) == saved_defaults && session.text("ai.num_predict") == "0",
                "Invalid AI settings replaced remembered defaults or discarded the editable value");
        session.edit("ai.num_predict", "512");
        session.chat("unconfigured.chat.md");
        session.activate("tab.right.AI");
        require(session.text("ai.model") == "first-default" && session.text("ai.num_ctx") == "8192",
                "A cached unconfigured chat did not inherit newly applied defaults");
        session.chat("second.chat.md");
        session.activate("tab.right.AI");
        session.choose("ai.provider", "openrouter");
        require(session.text("ai.model").empty() && session.text("ai.endpoint").empty() &&
                session.text("ai.models.label").empty() &&
                widget(session.view(), "ai.models.configured").state.selected.value_or("").empty() &&
                inventory(config) == saved_defaults,
                "Manual provider change carried another provider's model/endpoint/selection or changed remembered defaults");
        session.edit("ai.endpoint", "");
        session.edit("ai.model", "second-default");
        session.edit("ai.num_predict", "768");
        session.edit("ai.service_tier", "default");
        session.edit("ai.reasoning_effort", "high");
        session.edit("ai.routing_providers", "deepinfra/fp4, mistral");
        session.choose("ai.web", "false");
        session.choose("ai.nitro", "true");
        require(!find(session.view(), "ai.zdr"), "OpenRouter still exposed removed zero-retention controls");
        session.activate("ai.apply");
        session.success("remember second AI defaults");
        const auto cloud_defaults = AiPreferences(config).defaults();
        require(cloud_defaults && cloud_defaults->provider == "openrouter" &&
                cloud_defaults->service_tier == "default" && cloud_defaults->reasoning_effort == "high" &&
                cloud_defaults->nitro &&
                cloud_defaults->routing_providers == std::vector<std::string>{"deepinfra/fp4", "mistral"},
                "Explicit Apply did not persist the relevant OpenRouter configuration");
        session.chat("first.chat.md");
        session.activate("tab.right.AI");
        require(session.text("ai.model") == "first-default" &&
                widget(session.view(), "ai.provider").state.selected == "ollama" &&
                widget(session.view(), "ai.web").state.selected == "true",
                "New defaults replaced an explicitly configured chat");
        session.chat("unconfigured.chat.md");
        session.activate("tab.right.AI");
        require(session.text("ai.model") == "second-default" &&
                widget(session.view(), "ai.provider").state.selected == "openrouter" &&
                widget(session.view(), "ai.web").state.selected == "false",
                "An inherited chat stopped following the last applied defaults");
        session.activate("wb.new");
        session.edit("prompt.value", "created.chat.md");
        session.activate("prompt.accept");
        session.activate("tab.right.AI");
        require(session.text("ai.model") == "second-default" && session.text("ai.num_predict") == "768",
                "New chat creation did not inherit remembered defaults");
        session.application->handle(gui::CloseEvent{});
        require(session.adapter.closed(), "AI-default fixture did not close cleanly");
    }
    Workspace workspace(project);
    require(workspace.open_chat("first.chat.md").state.ai_configured &&
            workspace.open_chat("second.chat.md").state.ai_configured &&
            !workspace.open_chat("unconfigured.chat.md").state.ai_configured &&
            !workspace.open_chat("created.chat.md").state.ai_configured,
            "Inherited AI settings were incorrectly promoted to explicit chat overrides");
    {
        Session reopened(project, "first.chat.md", config);
        reopened.activate("tab.right.AI");
        require(reopened.text("ai.model") == "first-default" &&
                reopened.text("ai.endpoint") == "http://127.0.0.1:11434",
                "Restart replaced a configured chat with global AI defaults");
        reopened.chat("unconfigured.chat.md");
        reopened.activate("tab.right.AI");
        require(reopened.text("ai.model") == "second-default" && reopened.text("ai.num_predict") == "768",
                "Restart did not restore global defaults for an inherited chat");
    }
    const auto other_project = fixture.root / "other-project";
    std::filesystem::create_directory(other_project);
    {
        Session empty(other_project, {}, config);
        empty.activate("tab.right.AI");
        require(empty.text("ai.model") == "second-default" && empty.text("ai.num_predict") == "768",
                "The AI tab did not restore defaults in another empty workspace");
        const auto before = inventory(config);
        empty.edit("ai.model", "unapplied-model");
        require(inventory(config) == before && inventory(other_project).empty(),
                "Editing an AI field wrote defaults before explicit Apply");
        empty.activate("ai.apply");
        empty.success("apply defaults without a chat");
        require(AiPreferences(config).defaults()->model == "unapplied-model" && inventory(other_project).empty(),
                "Applying defaults without a chat created project files or forgot the setting");
    }
    const std::string corrupt = "{\"broken\":\n";
    write(config / "ai-defaults.json", corrupt);
    {
        Session unreadable(other_project, {}, config, false);
        unreadable.error("AI defaults could not be loaded");
        unreadable.activate("tab.right.AI");
        unreadable.edit("ai.model", "would-overwrite");
        unreadable.activate("ai.apply");
        unreadable.error("AI defaults are unavailable");
        require(read(config / "ai-defaults.json") == corrupt,
                "Unavailable AI defaults were silently replaced by a fallback configuration");
    }
}

void interactive_research_scope() {
    Temporary fixture;
    write(fixture.root / "research.chat.md", "# Offline interface fixture\n");
    Session session(fixture.root, "research.chat.md");
    session.activate("tab.right.Selector");
    const auto& source = widget(session.view(), "research.source");
    require(source.state.selected == "web" &&
            session.text("research.max_queries") == "8" && session.text("research.max_results") == "24",
            "Interactive chat research inherited the tiny automated-test scope");
    for (const auto* scope : {"wikipedia", "stackoverflow", "local", "kiwix", "web"}) {
        session.choose("research.source", scope);
        session.activate("selector.save");
        session.success("save research scope");
        require(Workspace(fixture.root).open_chat("research.chat.md").state.selector.research_source == scope,
                "Research source selection did not persist");
    }
    session.edit("research.max_queries", "64");
    session.edit("research.max_results", "192");
    session.activate("selector.save");
    session.activate("tab.right.AI");
    require(session.text("ai.web.label") == "Web search", "AI web search still claimed a curated-only scope");
    session.activate("tab.left.Running Tasks");
    require(widget(session.view(), "wb.tasks").state.records.empty(),
            "Editing research settings launched a search or provider task");
    session.application->handle(gui::CloseEvent{});
    Session reopened(fixture.root, "research.chat.md");
    reopened.activate("tab.right.Selector");
    require(widget(reopened.view(), "research.source").state.selected == "web" &&
            reopened.text("research.max_queries") == "64" && reopened.text("research.max_results") == "192",
            "Restart discarded interactive research scope or budgets");
}

void tutorial_snippets_are_explicit() {
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto config = fixture.root / "user-config";
    write(project / "chat.chat.md", "# Tutorial fixture\n");
    std::string custom_id;
    {
        Session session(project, "chat.chat.md", config);
        session.activate("tab.right.Pseudocode");
        require(widget(session.view(), "wb.tutorial").spec.kind == gui::Kind::toggle &&
                !widget(session.view(), "wb.tutorial").state.checked &&
                widget(session.view(), "snippet.list").state.records.empty(),
                "A fresh application exposed tutorial snippets before Tutorial mode was enabled");
        session.activate("snippet.new");
        session.edit("snippet.title", "Saved custom workflow");
        session.edit("snippet.text", "agent custom: Preserve this project snippet.\n");
        session.activate("snippet.save");
        const auto& custom_rows = widget(session.view(), "snippet.list").state.records;
        require(custom_rows.size() == 1, "Tutorial mode hid or duplicated the saved custom snippet");
        custom_id = custom_rows.front().id;
        const auto custom_bytes = read(project / ".tinyenv/pseudocode.json");
        session.activate("tab.center.Pseudocode Editor");
        const auto flow = session.text("wb.flow.text");
        session.check("wb.tutorial", true);
        require(widget(session.view(), "wb.tutorial").state.checked &&
                record(widget(session.view(), "snippet.list"), "builtin.1") &&
                record(widget(session.view(), "snippet.list"), custom_id) &&
                AiPreferences(config).tutorial_mode(),
                "Enabling Tutorial mode did not expose examples beside the custom snippet or persist the setting");
        session.select("snippet.list", "builtin.1");
        const auto example = session.text("snippet.text");
        session.activate_record("snippet.list", "builtin.1");
        require(!example.empty() && session.text("wb.flow.text") == flow,
                "Selecting or activating a tutorial snippet inserted it into the workflow");
        session.edit("snippet.title", "My saved tutorial variant");
        session.edit("snippet.text", "agent variant: Preserve an edited tutorial copy.\n");
        session.activate("snippet.save");
        require(Workspace(project).snippets(SnippetKind::pseudocode).size() == 2 &&
                read(project / ".tinyenv/pseudocode.json") != custom_bytes,
                "Saving an edited tutorial example did not create a custom project snippet");
        session.select("snippet.list", "builtin.1");
        require(session.text("snippet.text") == example,
                "Saving a tutorial variant modified the built-in example");
        const auto saved_variants = read(project / ".tinyenv/pseudocode.json");
        session.check("wb.tutorial", false);
        require(!widget(session.view(), "wb.tutorial").state.checked &&
                widget(session.view(), "snippet.list").state.records.size() == 2 &&
                record(widget(session.view(), "snippet.list"), custom_id) &&
                std::none_of(widget(session.view(), "snippet.list").state.records.begin(),
                             widget(session.view(), "snippet.list").state.records.end(),
                             [](const auto& row) { return row.id.starts_with("builtin."); }) &&
                read(project / ".tinyenv/pseudocode.json") == saved_variants &&
                !AiPreferences(config).tutorial_mode(),
                "Disabling Tutorial mode removed custom snippets or saved built-in examples");
        session.check("wb.tutorial", true);
        session.application->handle(gui::CloseEvent{});
        require(session.adapter.closed(), "Tutorial fixture did not close cleanly");
    }
    const auto other_project = fixture.root / "other-project";
    write(other_project / "other.chat.md", "# Other project tutorial fixture\n");
    const auto other_original = inventory(other_project);
    {
        Session other(other_project, "other.chat.md", config);
        other.activate("tab.right.Pseudocode");
        require(widget(other.view(), "wb.tutorial").state.checked &&
                record(widget(other.view(), "snippet.list"), "builtin.1") &&
                !record(widget(other.view(), "snippet.list"), custom_id),
                "Another project did not inherit Tutorial mode or leaked project-local custom snippets");
        other.check("wb.tutorial", false);
        require(inventory(other_project) == other_original,
                "Changing application Tutorial mode wrote the other project's chat or state");
    }
    Session reopened(project, "chat.chat.md", config);
    reopened.activate("tab.right.Pseudocode");
    require(!widget(reopened.view(), "wb.tutorial").state.checked &&
            widget(reopened.view(), "snippet.list").state.records.size() == 2 &&
            record(widget(reopened.view(), "snippet.list"), custom_id),
            "Restart did not retain Tutorial mode off and the project's saved custom snippets");
}

void optional_ai_parameters_and_provider_controls() {
    Temporary fixture;
    Session session(fixture.root);
    session.activate("tab.right.AI");
    const auto blank_default = [&](std::string_view id) {
        require(session.text(id).empty() && widget(session.view(), id).state.placeholder == "Provider default",
                std::string(id) + " did not show an unset value with a Provider default placeholder");
    };
    for (const auto* id : {"ai.num_predict", "ai.temperature", "ai.top_p"}) blank_default(id);
    require(!find(session.view(), "ai.num_ctx") && !find(session.view(), "ai.num_keep") &&
            find(session.view(), "ai.service_tier") && find(session.view(), "ai.reasoning_effort") &&
            find(session.view(), "ai.routing_providers") && find(session.view(), "ai.nitro") &&
            !find(session.view(), "ai.zdr") && find(session.view(), "ai.web"),
            "OpenRouter exposed Ollama controls or omitted its applicable controls");
    session.choose("ai.provider", "openai");
    require(!find(session.view(), "ai.num_ctx") && !find(session.view(), "ai.num_keep") &&
            !find(session.view(), "ai.routing_providers") && !find(session.view(), "ai.nitro") &&
            !find(session.view(), "ai.zdr") && find(session.view(), "ai.service_tier") &&
            find(session.view(), "ai.reasoning_effort") && find(session.view(), "ai.web"),
            "OpenAI exposed another provider's controls or omitted its applicable controls");
    session.choose("ai.provider", "ollama");
    require(!find(session.view(), "ai.service_tier") && !find(session.view(), "ai.reasoning_effort") &&
            !find(session.view(), "ai.routing_providers") && !find(session.view(), "ai.nitro") &&
            !find(session.view(), "ai.zdr") && find(session.view(), "ai.web"),
            "Ollama exposed cloud-only controls or hid general web search");
    for (const auto* id : {"ai.num_predict", "ai.num_ctx", "ai.num_keep", "ai.temperature", "ai.top_p"})
        blank_default(id);
    session.edit("ai.model", "offline-options-fixture");
    session.edit("ai.num_predict", "512");
    session.edit("ai.num_ctx", "4096");
    session.edit("ai.num_keep", "0");
    session.edit("ai.temperature", "0");
    session.edit("ai.top_p", "0.85");
    session.activate("ai.apply");
    session.success("apply explicit optional AI values");
    auto defaults = AiPreferences(fixture.root / ".preferences").defaults();
    require(defaults && defaults->num_predict == 512 && defaults->num_ctx == 4096 &&
            defaults->num_keep.has_value() && *defaults->num_keep == 0 &&
            defaults->temperature.has_value() && *defaults->temperature == 0 && defaults->top_p == 0.85,
            "Explicit zero values were mistaken for unset provider defaults");
    for (const auto* id : {"ai.num_predict", "ai.num_ctx", "ai.num_keep", "ai.temperature", "ai.top_p"})
        session.edit(id, "");
    session.activate("ai.apply");
    session.success("clear optional AI values");
    defaults = AiPreferences(fixture.root / ".preferences").defaults();
    require(defaults && !defaults->num_predict && !defaults->num_ctx && !defaults->num_keep &&
            !defaults->temperature && !defaults->top_p,
            "Clearing optional AI fields restored explicit numbers instead of provider defaults");
    for (const auto* id : {"ai.num_predict", "ai.num_ctx", "ai.num_keep", "ai.temperature", "ai.top_p"})
        blank_default(id);
    const auto valid_defaults = inventory(fixture.root / ".preferences");
    session.edit("ai.num_predict", "0");
    session.activate("ai.apply");
    session.error("between 1 and 65536");
    require(session.text("ai.num_predict") == "0" &&
            inventory(fixture.root / ".preferences") == valid_defaults,
            "An invalid optional AI value changed remembered defaults or discarded the draft");
    session.edit("ai.num_predict", "");
    session.edit("ai.num_ctx", "1");
    session.choose("ai.provider", "openrouter");
    session.activate("ai.apply");
    session.success("apply without parsing an irrelevant Ollama draft");
    require(!AiPreferences(fixture.root / ".preferences").defaults()->num_ctx,
            "An irrelevant numeric draft became an explicit provider setting");
    session.application->handle(gui::CloseEvent{});
    require(session.adapter.closed(), "Optional AI fixture did not close cleanly");
    Session reopened(fixture.root);
    reopened.activate("tab.right.AI");
    for (const auto* id : {"ai.num_predict", "ai.temperature", "ai.top_p"})
        require(reopened.text(id).empty() && widget(reopened.view(), id).state.placeholder == "Provider default",
                "Restart did not preserve an unset optional AI setting");
    reopened.choose("ai.provider", "ollama");
    require(reopened.text("ai.num_ctx").empty() && reopened.text("ai.num_keep").empty(),
            "Restart retained an irrelevant invalid draft or restored cleared Ollama defaults");
}

void configured_models_are_application_wide() {
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto config = fixture.root / "user-config";
    std::filesystem::create_directory(project);
    {
        Session session(project, {}, config);
        session.activate("tab.right.AI");
        session.choose("ai.provider", "ollama");
        session.edit("ai.endpoint", "http://127.0.0.1:11434");
        session.edit("ai.model", "local-fixture");
        session.edit("ai.models.label", "Local fixture");
        session.activate("ai.models.add");
        session.success("add configured local model");
        auto preferences = AiPreferences(config);
        require(!preferences.defaults() && preferences.configured_models() ==
                    std::vector<ConfiguredModel>{{"ollama", "http://127.0.0.1:11434", "local-fixture", "Local fixture"}} &&
                option(widget(session.view(), "ai.models.configured"), "0") && inventory(project).empty(),
                "Adding a configured model applied defaults, missed its saved identity or wrote an empty project");
        session.choose("ai.provider", "openrouter");
        require(session.text("ai.model").empty() && session.text("ai.endpoint").empty() &&
                session.text("ai.models.label").empty() &&
                widget(session.view(), "ai.models.configured").state.selected.value_or("").empty() &&
                AiPreferences(config).configured_models() == preferences.configured_models() &&
                !AiPreferences(config).defaults(),
                "Manual provider change carried another provider's model/endpoint/selection or changed the saved model list");
        session.edit("ai.endpoint", "");
        session.edit("ai.model", "vendor/cloud-fixture");
        session.edit("ai.models.label", "Cloud fixture");
        session.activate("ai.models.add");
        session.success("add configured cloud model");
        require(AiPreferences(config).configured_models().size() == 2 &&
                option(widget(session.view(), "ai.models.configured"), "0") &&
                option(widget(session.view(), "ai.models.configured"), "1"),
                "Adding another provider's model replaced or hid the first configured entry");
        session.edit("ai.temperature", "0.7");
        session.choose("ai.models.configured", "0");
        require(widget(session.view(), "ai.provider").state.selected == "ollama" &&
                session.text("ai.endpoint") == "http://127.0.0.1:11434" &&
                session.text("ai.model") == "local-fixture" && session.text("ai.temperature") == "0.7" &&
                !AiPreferences(config).defaults(),
                "Configured model selection did not restore its identity or changed generation defaults");
        session.activate("ai.models.remove");
        session.success("remove configured local model");
        require(AiPreferences(config).configured_models() ==
                    std::vector<ConfiguredModel>{{"openrouter", "", "vendor/cloud-fixture", "Cloud fixture"}} &&
                session.text("ai.model") == "local-fixture" && !AiPreferences(config).defaults(),
                "Removing a configured entry changed the active model or remembered AI defaults");
    }
    const auto other_project = fixture.root / "other-project";
    std::filesystem::create_directory(other_project);
    Session other(other_project, {}, config);
    other.activate("tab.right.AI");
    require(option(widget(other.view(), "ai.models.configured"), "0") &&
            !option(widget(other.view(), "ai.models.configured"), "1"),
            "Restart in another project did not restore the remaining application model catalog");
    other.choose("ai.models.configured", "0");
    require(widget(other.view(), "ai.provider").state.selected == "openrouter" &&
            other.text("ai.model") == "vendor/cloud-fixture" && other.text("ai.endpoint").empty() &&
            inventory(other_project).empty(),
            "The application model catalog depended on the previous project or created chat files");
}

void model_catalog_refresh_uses_an_offline_worker() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto config = fixture.root / "user-config";
    const auto worker = fixture.root / "offline catalog worker.py";
    const auto receipt = fixture.root / "catalog requests.jsonl";
    const auto mode = fixture.root / "catalog mode.txt";
    std::filesystem::create_directory(project);
    write(worker, R"PY(import json, os, sys, time
assert sys.flags.isolated and sys.flags.no_user_site
assert sys.argv[1] == '--request'
with open(sys.argv[2], encoding='utf-8') as stream:
    request = json.load(stream)
assert set(request) == {'schema_version', 'operation', 'root', 'settings'}
assert request['schema_version'] == 1 and request['operation'] == 'models'
assert os.path.realpath(request['root']) == os.path.realpath(os.getcwd())
assert set(request['settings']) == {'provider', 'endpoint'}
provider = request['settings']['provider']
base = os.path.dirname(__file__)
with open(os.path.join(base, 'catalog requests.jsonl'), 'a', encoding='utf-8') as stream:
    stream.write(provider + ':models\n')
mode = 'success'
if os.path.exists(os.path.join(base, 'catalog mode.txt')):
    with open(os.path.join(base, 'catalog mode.txt'), encoding='utf-8') as stream:
        mode = stream.read().strip()
if mode == 'hold':
    while True:
        time.sleep(0.01)
if provider == 'openai' or mode == 'fail':
    print(json.dumps({'ok': False, 'error': 'Expected offline catalog failure'}))
    sys.exit(7)
assert provider == 'ollama' and request['settings']['endpoint'] == 'http://127.0.0.1:11434'
print(json.dumps({'ok': True, 'models': [
    {'id': 'catalog-fixture-a', 'name': 'Display Alpha', 'provider': provider},
    {'id': 'catalog-fixture-b', 'name': 'Display Beta', 'provider': provider}],
    'models_truncated': True}))
)PY");
    Session session(project, {}, config, true, worker);
    session.activate("tab.right.AI");
    require(!std::filesystem::exists(receipt) && inventory(project).empty() &&
            !std::filesystem::exists(config) && session.text("ai.models.count") == "No catalog loaded" &&
            !widget(session.view(), "ai.models.cancel").state.enabled,
            "Application construction implicitly refreshed models or saved preferences");
    session.choose("ai.provider", "ollama");
    session.edit("ai.endpoint", "http://127.0.0.1:11434");
    session.edit("ai.model", "unapplied-model");
    session.edit("ai.temperature", "0.6");
    const auto refresh_bounds = widget(session.view(), "ai.models.refresh").state.bounds;
    const auto cancel_bounds = widget(session.view(), "ai.models.cancel").state.bounds;
    session.activate("ai.models.refresh");
    require(!widget(session.view(), "ai.models.refresh").state.enabled &&
            widget(session.view(), "ai.models.cancel").state.enabled &&
            widget(session.view(), "ai.models.refresh").state.bounds == refresh_bounds &&
            widget(session.view(), "ai.models.cancel").state.bounds == cancel_bounds,
            "A running catalog job accepted another Refresh or shifted its action controls");
    const auto finish = [&] {
        wait_for(session, [&] { return widget(session.view(), "ai.models.refresh").state.enabled; },
                 "offline catalog worker completion");
    };
    finish();
    session.success("refresh the offline model catalog");
    require(record(widget(session.view(), "ai.models.available"), "catalog-fixture-a") &&
            record(widget(session.view(), "ai.models.available"), "catalog-fixture-b") &&
            session.text("ai.models.count") == "2 of 2 models" &&
            read(receipt) == "ollama:models\n" && inventory(project).empty() &&
            !std::filesystem::exists(config),
            "Model Refresh did not publish worker records or changed application/chat preferences");
    session.select("ai.models.available", "catalog-fixture-b");
    require(session.text("ai.model") == "catalog-fixture-b" &&
            session.text("ai.endpoint") == "http://127.0.0.1:11434" &&
            session.text("ai.temperature") == "0.6" && !std::filesystem::exists(config),
            "Selecting an available model changed generation settings or published preferences");
    session.activate("ai.models.add");
    session.success("save an available catalog model");
    require(AiPreferences(config).configured_models().size() == 1 &&
            AiPreferences(config).configured_models().front().model == "catalog-fixture-b" &&
            !AiPreferences(config).defaults(),
            "Adding an available model did not persist it independently of AI defaults");
    const auto saved_preferences = inventory(config);
    const auto configured = widget(session.view(), "ai.models.configured").state.selected;
    const auto unchanged_filter = [&] {
        require(read(receipt) == "ollama:models\n" && inventory(config) == saved_preferences &&
                inventory(project).empty() && session.text("ai.model") == "catalog-fixture-b" &&
                session.text("ai.temperature") == "0.6" &&
                widget(session.view(), "ai.models.configured").state.selected == configured,
                "Filtering issued a request, saved preferences or changed the chosen model/configured identity");
    };
    for (const auto* query : {"CATALOG-FIXTURE-A", "aLpHa"}) {
        session.edit("ai.models.filter", query);
        require(widget(session.view(), "ai.models.available").state.records.size() == 1 &&
                record(widget(session.view(), "ai.models.available"), "catalog-fixture-a") &&
                !widget(session.view(), "ai.models.available").state.selected &&
                session.text("ai.models.count") == "1 of 2 models",
                "Case-insensitive model ID/display-name filtering missed the match or retained a hidden selection");
        unchanged_filter();
        session.activate("ai.models.filter.clear");
        require(session.text("ai.models.filter").empty() &&
                widget(session.view(), "ai.models.available").state.records.size() == 2 &&
                widget(session.view(), "ai.models.available").state.selected == "catalog-fixture-b" &&
                session.text("ai.models.count") == "2 of 2 models",
                "Clear destroyed the full catalog or failed to restore its hidden model selection");
        unchanged_filter();
    }
    session.edit("ai.models.filter", "  bETA  ");
    require(widget(session.view(), "ai.models.available").state.records.size() == 1 &&
            record(widget(session.view(), "ai.models.available"), "catalog-fixture-b") &&
            widget(session.view(), "ai.models.available").state.selected == "catalog-fixture-b",
            "Display-name filtering failed to trim its query or lost a visible selection");
    session.edit("ai.models.filter", "no-such-fixture-model");
    require(widget(session.view(), "ai.models.available").state.records.empty() &&
            widget(session.view(), "ai.models.available").state.placeholder == "No matching models" &&
            session.text("ai.models.count") == "0 of 2 models", "An unmatched filter did not expose its empty-result state");
    unchanged_filter();
    session.activate("ai.models.filter.clear");
    unchanged_filter();
    write(mode, "fail\n");
    session.activate("ai.models.refresh");
    finish();
    session.error("Expected offline catalog failure");
    require(widget(session.view(), "ai.models.available").state.records.size() == 2 &&
            widget(session.view(), "ai.models.available").state.selected == "catalog-fixture-b" &&
            session.text("ai.models.count") == "2 of 2 models" &&
            inventory(config) == saved_preferences && inventory(project).empty(),
            "A failed refresh discarded its successful catalog/selection or changed saved preferences");
    write(mode, "hold\n");
    session.activate("ai.models.refresh");
    wait_for(session, [&] { return read(receipt) == "ollama:models\nollama:models\nollama:models\n"; },
             "held offline catalog launch");
    session.edit("ai.models.filter", "alpha");
    require(widget(session.view(), "ai.models.available").state.records.size() == 1 &&
            !widget(session.view(), "ai.models.available").state.enabled &&
            session.text("ai.models.count") == "1 of 2 models",
            "Filtering a refreshing catalog destroyed retained records or reenabled selection");
    session.activate("ai.models.cancel");
    session.success("cancel the offline catalog refresh");
    require(widget(session.view(), "ai.models.refresh").state.enabled &&
            !widget(session.view(), "ai.models.cancel").state.enabled &&
            widget(session.view(), "ai.models.cancel").state.bounds == cancel_bounds &&
            widget(session.view(), "ai.models.available").state.enabled &&
            record(widget(session.view(), "ai.models.available"), "catalog-fixture-a"),
            "Cancellation discarded the retained catalog or shifted its fixed action controls");
    session.activate("ai.models.filter.clear");
    require(widget(session.view(), "ai.models.available").state.records.size() == 2 &&
            widget(session.view(), "ai.models.available").state.selected == "catalog-fixture-b",
            "Clearing a filter after cancellation failed to restore the full catalog and selection");
    write(mode, "fail\n");
    session.choose("ai.provider", "openai");
    session.edit("ai.endpoint", "");
    session.activate("ai.models.refresh");
    finish();
    session.error("Expected offline catalog failure");
    require(read(receipt) == "ollama:models\nollama:models\nollama:models\nopenai:models\n" &&
            widget(session.view(), "ai.models.available").state.records.empty() &&
            session.text("ai.models.count") == "No catalog loaded" &&
            inventory(config) == saved_preferences && inventory(project).empty(),
            "A failed model Refresh exposed another provider's records or changed saved preferences");
    session.choose("ai.provider", "ollama");
    session.edit("ai.endpoint", "http://127.0.0.1:11434");
    require(widget(session.view(), "ai.models.available").state.records.size() == 2 &&
            widget(session.view(), "ai.models.available").state.selected.value_or("").empty() &&
            session.text("ai.model").empty() &&
            session.text("ai.models.count") == "2 of 2 models",
            "Returning to the retained catalog lost its contents or restored a model without explicit selection");
    session.edit("ai.endpoint", "http://127.0.0.1:11435");
    require(widget(session.view(), "ai.models.available").state.records.empty() &&
            session.text("ai.models.count") == "No catalog loaded",
            "A different endpoint exposed a catalog with the wrong identity");
    session.edit("ai.endpoint", "http://127.0.0.1:11434");
    require(widget(session.view(), "ai.models.available").state.records.size() == 2 &&
            read(receipt) == "ollama:models\nollama:models\nollama:models\nopenai:models\n" &&
            inventory(config) == saved_preferences,
            "Catalog identity restoration issued an implicit request or discarded retained models");
#endif
}

void ai_keys_are_private_and_explicit() {
    Temporary fixture;
    const auto project = fixture.root / "project";
    const auto config = fixture.root / "user-config";
    const auto worker = offline_chat_worker(fixture.root);
    write(project / "chat.chat.md", "# Private-key UI fixture\n");
    write(project / "other.chat.md", "# Other private-key fixture\n");
    AiPreferences preferences(config);
    AiSettings defaults;
    defaults.provider = "openrouter";
    defaults.model = "vendor/offline-key-fixture";
    preferences.save(defaults);
    preferences.save_guardrail_id("legacy-unused-fixture");
    const std::string router_key = "synthetic-router-key-for-local-ui-fixture-v3";
    const std::string openai_key = "synthetic-openai-key-for-local-ui-fixture-v3";
    const auto public_preferences = [&] { return read(config / "ai-defaults.json"); };
    const auto no_leaks = [&](const Session& session) {
        for (const auto& [path, bytes] : inventory(project)) {
            (void)path;
            require(bytes.find(router_key) == std::string::npos && bytes.find(openai_key) == std::string::npos,
                    "A synthetic API key leaked into a chat or companion state");
        }
        require(public_preferences().find(router_key) == std::string::npos &&
                public_preferences().find(openai_key) == std::string::npos,
                "A synthetic API key leaked into ordinary AI preferences");
        for (const auto& item : session.view().widgets)
            require(item.state.text.find(router_key) == std::string::npos &&
                    item.state.text.find(openai_key) == std::string::npos &&
                    item.state.label.find(router_key) == std::string::npos &&
                    item.state.label.find(openai_key) == std::string::npos &&
                    item.state.help.find(router_key) == std::string::npos &&
                    item.state.help.find(openai_key) == std::string::npos,
                    "A saved synthetic API key was prefilled or exposed in a status/help field");
    };
    {
        Session session(project, "chat.chat.md", config, true, worker);
        session.activate("tab.right.AI");
        require(widget(session.view(), "ai.key").spec.text_policy.masked &&
                !widget(session.view(), "ai.key").spec.text_policy.multiline &&
                widget(session.view(), "ai.key").spec.text_policy.max_bytes == AiCredentials::maximum_key_bytes &&
                session.text("ai.key").empty() && !widget(session.view(), "ai.key.save").state.enabled &&
                !widget(session.view(), "ai.key.remove").state.enabled &&
                !std::filesystem::exists(config / "credentials"),
                "The key field was unmasked/prefilled or construction created private credential storage");
        for (const auto& item : session.view().widgets)
            require(!item.spec.key.id.starts_with("ai.guardrail."),
                    "The AI pane still exposed shared OpenRouter guardrail management controls");
        require(session.text("ai.injection.status").find("no request-only") != std::string::npos,
                "OpenRouter did not explain the documented request-only injection-filter limitation");
        require(session.adapter.send(gui::WidgetEvent{{"ai.guardrail.load", 1}, gui::Activate{}}) == gui::Delivery::ignored,
                "A removed management action remained reachable through the normal adapter");
        if (!AiCredentials::supports("openrouter")) {
            require(!widget(session.view(), "ai.key").state.enabled &&
                    !widget(session.view(), "ai.key.save").state.enabled &&
                    !widget(session.view(), "ai.key.remove").state.enabled,
                    "An unavailable private-storage adapter enabled API-key mutation");
            no_leaks(session);
            return;
        }
        session.autosave();
        const auto project_before_typing = inventory(project);
        const auto preferences_before_typing = public_preferences();
        session.edit("ai.key", router_key);
        session.submit("ai.key");
        session.application->tick();
        require(session.text("ai.key") == router_key &&
                AiCredentials(config).status("openrouter") == CredentialStatus::absent &&
                !std::filesystem::exists(config / "credentials") &&
                inventory(project) == project_before_typing && public_preferences() == preferences_before_typing &&
                !std::filesystem::exists(fixture.root / "chat.chat.md.launches"),
                "Typing or Enter saved a key, changed chat/preferences or launched a worker");
        session.activate("ai.apply");
        session.success("apply settings without saving a pending API key");
        require(session.text("ai.key") == router_key &&
                AiCredentials(config).status("openrouter") == CredentialStatus::absent &&
                !std::filesystem::exists(config / "credentials"),
                "Apply implicitly saved or cleared the separately controlled API-key draft");
        session.chat("other.chat.md");
        session.activate("tab.right.AI");
        require(session.text("ai.key").empty(), "Chat switching retained a pending API-key draft");
        session.chat("chat.chat.md");
        session.activate("tab.right.AI");
        const auto preferences_before_save = public_preferences();
        session.edit("ai.key", router_key);
        session.activate("ai.key.save");
        session.success("explicitly save the synthetic OpenRouter key");
        require(session.text("ai.key").empty() &&
                AiCredentials(config).status("openrouter") == CredentialStatus::saved &&
                read(config / "credentials/openrouter.key") == router_key + "\n" &&
                session.text("ai.key.status") == "Saved private key present" &&
                public_preferences() == preferences_before_save,
                "Explicit Save did not create independent private storage or left the key prefilled");
        no_leaks(session);
        const auto router_remove = widget(session.view(), "ai.key.remove").spec.key;
        const auto router_input = widget(session.view(), "ai.key").spec.key;
        session.edit("ai.key", "synthetic-unsaved-draft");
        session.choose("ai.provider", "openai");
        require(session.text("ai.key").empty() &&
                AiCredentials(config).status("openai") == CredentialStatus::absent &&
                !widget(session.view(), "ai.key.remove").state.enabled && !find(session.view(), "ai.injection.status"),
                "Provider switching retained another provider's key draft/status or OpenRouter-only limitation text");
        session.edit("ai.key", openai_key);
        session.activate("ai.key.save");
        session.success("explicitly save the synthetic OpenAI key");
        require(session.text("ai.key").empty() &&
                AiCredentials(config).status("openai") == CredentialStatus::saved &&
                read(config / "credentials/openai.key") == openai_key + "\n" &&
                read(config / "credentials/openrouter.key") == router_key + "\n" &&
                public_preferences() == preferences_before_save,
                "Saving a second provider's key overwrote the first key or ordinary preferences");
        require(session.adapter.send(gui::WidgetEvent{router_remove, gui::Activate{}}) == gui::Delivery::ignored &&
                session.adapter.send(gui::WidgetEvent{router_input, gui::EditText{"stale-key-edit", ""}}) == gui::Delivery::ignored &&
                read(config / "credentials/openai.key") == openai_key + "\n" && session.text("ai.key").empty(),
                "Stale key controls from another provider removed or edited the current provider's credential");
        no_leaks(session);
        session.edit("ai.key", "synthetic-unsaved-removal-draft");
        session.activate("ai.key.remove");
        session.success("explicitly remove the synthetic OpenAI key");
        require(session.text("ai.key").empty() &&
                AiCredentials(config).status("openai") == CredentialStatus::absent &&
                !std::filesystem::exists(config / "credentials/openai.key") &&
                read(config / "credentials/openrouter.key") == router_key + "\n" &&
                !widget(session.view(), "ai.key.remove").state.enabled,
                "Remove lost another provider's key or retained a pending key draft");
        session.choose("ai.provider", "ollama");
        require(!widget(session.view(), "ai.key").state.enabled &&
                !widget(session.view(), "ai.key.save").state.enabled &&
                !widget(session.view(), "ai.key.remove").state.enabled && session.text("ai.key").empty() &&
                session.text("ai.key.status").find("does not need an API key") != std::string::npos,
                "Ollama exposed authentication actions or retained another provider's key");
        const auto disabled_key = widget(session.view(), "ai.key").spec.key;
        require(session.adapter.send(gui::WidgetEvent{disabled_key, gui::EditText{"refused-key", ""}}) == gui::Delivery::ignored,
                "The normal adapter accepted an API-key edit for an unavailable provider");
        session.choose("ai.provider", "openrouter");
        require(session.text("ai.key").empty() && session.text("ai.key.status") == "Saved private key present",
                "Returning to a provider prefilled its saved key or lost its presence status");
        session.edit("ai.key", "invalid synthetic key with spaces");
        session.activate("ai.key.save");
        session.error("without whitespace");
        require(session.text("ai.key").empty() &&
                read(config / "credentials/openrouter.key") == router_key + "\n" &&
                session.text("ai.key.status") == "Saved private key present",
                "A failed Save discarded the previous private key or left rejected secret input visible");
        no_leaks(session);
        session.application->handle(gui::CloseEvent{});
        require(session.adapter.closed(), "Private-key fixture did not flush and close cleanly");
    }
    {
        Session reopened(project, "chat.chat.md", config, true, worker);
        reopened.activate("tab.right.AI");
        require(reopened.text("ai.key").empty() && reopened.text("ai.key.status") == "Saved private key present" &&
                widget(reopened.view(), "ai.key.remove").state.enabled &&
                AiPreferences(config).openrouter_guardrail_id() == "legacy-unused-fixture",
                "Restart prefilled a private key, lost its saved presence or rewrote compatibility preferences");
        const auto switched_chat = Workspace(project).open_chat("chat.chat.md");
        require(reopened.text("ai.model").empty() && reopened.text("ai.endpoint").empty() &&
                switched_chat.state.ai_configured && switched_chat.state.ai.provider == "openrouter" &&
                switched_chat.state.ai.model.empty() && switched_chat.state.ai.endpoint.empty(),
                "Restart inherited a default over the manually changed provider's explicit blank model/endpoint");
        no_leaks(reopened);
#if defined(__linux__) || defined(_WIN32)
        reopened.edit("ai.model", "vendor/offline-key-fixture");
        reopened.edit("wb.composer", "A local request with no authentication material.");
        reopened.activate("wb.send");
        wait_for(reopened, [&] { return !widget(reopened.view(), "wb.cancel").state.enabled; },
                 "private-key fixture fake-worker completion");
        reopened.success("complete a fake request with separate private credentials");
        const auto request = read(fixture.root / "chat.chat.md.request.json");
        require(request.find(router_key) == std::string::npos && request.find(openai_key) == std::string::npos &&
                request.find("api_key") == std::string::npos && read(fixture.root / "chat.chat.md.launches") == "launch\n",
                "Saving private keys leaked them into a runtime request or implicitly launched a worker");
        no_leaks(reopened);
#endif
        reopened.activate("ai.key.remove");
        reopened.success("remove the remaining private key after restart");
        require(reopened.text("ai.key").empty() &&
                AiCredentials(config).status("openrouter") == CredentialStatus::absent &&
                !std::filesystem::exists(config / "credentials/openrouter.key") &&
                !widget(reopened.view(), "ai.key.remove").state.enabled &&
                reopened.text("ai.key.status").find("No saved private key") != std::string::npos,
                "Explicit Remove failed to clear only the saved provider credential");
        no_leaks(reopened);
    }
}

void pseudocode_edits(const std::filesystem::path& captures) {
    Temporary fixture;
    write(fixture.root / "first.chat.md", "# First\n");
    write(fixture.root / "second.chat.md", "# Second\n");
    Session session(fixture.root, "first.chat.md");
    session.activate("tab.center.Pseudocode Editor");
    const std::string invalid = "repeat 3\n  agent writer: Keep this unfinished draft.\n";
    session.edit("wb.flow.text", invalid);
    require(session.text("wb.flow.text") == invalid &&
            widget(session.view(), "flow.diagnostics").state.font.tone == gui::Tone::error &&
            session.text("flow.diagnostics").find("Line ") != std::string::npos &&
            !widget(session.view(), "flow.add").state.enabled &&
            !widget(session.view(), "flow.apply").state.enabled,
            "Invalid pseudocode did not retain source, diagnostics and disabled graph edits");
    const auto disabled = widget(session.view(), "flow.add").spec.key;
    require(session.adapter.send(gui::WidgetEvent{disabled, gui::Activate{}}) == gui::Delivery::ignored,
            "Invalid pseudocode allowed an unavailable graph action");
    capture(session.view(), captures, "workbench-flow-diagnostics");
    session.chat("second.chat.md");
    session.chat("first.chat.md");
    require(session.text("wb.flow.text") == invalid, "Chat switching lost invalid pseudocode bytes");
    const std::string valid = "agent writer: Draft answer.\ncritique reviewer: Check evidence.\nconclude: Deliver answer.\n";
    session.edit("wb.flow.text", valid);
    require(widget(session.view(), "flow.diagnostics").state.font.tone != gui::Tone::error &&
            widget(session.view(), "flow.add").state.enabled,
            "Repairing pseudocode did not restore graphical editing");
    const auto old_action = widget(session.view(), "flow.add").spec.key;
    session.edit("wb.flow.text", valid + "# New draft identity\n");
    require(session.adapter.send(gui::WidgetEvent{old_action, gui::Activate{}}) == gui::Delivery::ignored,
            "A graph action from an older valid draft was accepted");
    require(session.text("wb.flow.text") == valid + "# New draft identity\n",
            "A stale graph action changed the newer source");
    session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.1").state.bounds));
    require(session.text("node.role") == "writer" && session.text("node.parent") == "0" &&
            session.text("node.index") == "0", "Graph selection did not expose root-node properties");
    session.edit("node.role", "author");
    session.edit("node.text", "Support each claim.");
    session.activate("flow.apply");
    session.success("graph update");
    auto parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes.size() == 3 &&
            parsed.program->nodes[0].role == "author" &&
            parsed.program->nodes[0].text == "Support each claim.",
            "Graph property update did not change the ordinary pseudocode source");
    session.edit("node.parent", "0");
    session.edit("node.index", "2");
    session.choose("node.otherwise", "false");
    session.activate("flow.move");
    session.success("root graph move");
    parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes[0].kind == FlowKind::critique &&
            parsed.program->nodes[1].kind == FlowKind::conclude &&
            parsed.program->nodes[2].role == "author",
            "Graph move did not reorder the root siblings");
    session.activate("tab.right.Pseudocode");
    session.activate("snippet.new");
    session.edit("snippet.title", "Additional review");
    session.edit("snippet.text", "critique auditor: Check unresolved doubts.\n");
    session.activate("snippet.save");
    const auto snippet_id = widget(session.view(), "snippet.list").state.records.back().id;
    session.caret_at_end("wb.flow.text");
    const auto before_snippet = session.text("wb.flow.text");
    session.select("snippet.list", snippet_id);
    session.activate_record("snippet.list", snippet_id);
    require(session.text("wb.flow.text") == before_snippet &&
            session.text("snippet.title") == "Additional review" &&
            session.text("snippet.text") == "critique auditor: Check unresolved doubts.\n",
            "Selecting or activating a pseudocode snippet inserted it or failed to load its editable fields");
    session.activate("snippet.insert");
    parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes.size() == 4 &&
            parsed.program->nodes.back().role == "auditor",
            "Explicit pseudocode insertion did not update source and graph");
    const auto inserted = session.text("wb.flow.text");
    session.activate_record("snippet.list", snippet_id);
    require(session.text("wb.flow.text") == inserted,
            "Pseudocode snippet double activation inserted it twice");
    capture(session.view(), captures, "workbench-flow");
    const auto final_source = session.text("wb.flow.text");
    session.activate("tab.center.Chat Markdown");
    require(session.text("wb.composer").find("```pseudocode\n" + final_source) != std::string::npos &&
            session.text("wb.chat.text") == "# First\n" && read(fixture.root / "first.chat.md") == "# First\n",
            "Graph or snippet edits bypassed the composer and changed transcript history");
    session.autosave();
    session.success("pseudocode draft autosave");
    Workspace reopened(fixture.root);
    require(reopened.open_chat("first.chat.md").state.pseudocode == final_source &&
            reopened.snippets(SnippetKind::pseudocode).back().text ==
                "critique auditor: Check unresolved doubts.\n",
            "Pseudocode source or snippet failed to persist");
    const std::string replaced = "agent editor: Flow edited in the submitted composer.\n";
    session.edit("wb.composer", "```pseudocode\n" + replaced + "```\n");
    session.activate("tab.center.Pseudocode Editor");
    require(session.text("wb.flow.text") == replaced &&
            find(session.view(), "wb.flow.node.1") && !find(session.view(), "wb.flow.node.2"),
            "Editing the composer's pseudocode fence did not synchronize source and graph");
    session.edit("wb.flow.text", "if approved\n  agent helper: Resolve doubts.\nelse\n  conclude: Request clarification.\nend\n");
    session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.1").state.bounds));
    require(widget(session.view(), "node.kind").state.selected == "branch",
            "Selecting a branch exposed the wrong block kind");
    session.choose("node.condition", "supported");
    session.activate("flow.apply");
    parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes[0].kind == FlowKind::branch &&
            parsed.program->nodes[0].condition == FlowCondition::supported &&
            parsed.program->nodes[0].children.size() == 1 &&
            parsed.program->nodes[0].otherwise.size() == 1,
            "Applying branch properties lost its block kind or nested branches");
    session.chat("second.chat.md");
    session.activate("tab.center.Pseudocode Editor");
    session.edit("wb.flow.text", "agent second: Another chat's node.\n");
    session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.1").state.bounds));
    require(session.text("node.role") == "second", "Second chat graph selection failed");
    session.chat("first.chat.md");
    require(!widget(session.view(), "flow.apply").state.enabled,
            "Chat switching reused a selected node with another chat's property fields");
    session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.1").state.bounds));
    require(widget(session.view(), "node.kind").state.selected == "branch" &&
            widget(session.view(), "node.condition").state.selected == "supported",
            "Returning to a chat did not restore its own node properties");
}

void flow_properties_follow_block_kind() {
    Temporary fixture;
    write(fixture.root / "chat.chat.md", "# Block property fixture\n");
    Session session(fixture.root, "chat.chat.md");
    session.activate("tab.center.Pseudocode Editor");
    struct Fields { const char* kind; bool role, text, iterations, condition; };
    for (const auto& row : {Fields{"agent", true, true, false, false},
                            Fields{"critique", true, true, false, false},
                            Fields{"repeat", false, false, true, true},
                            Fields{"branch", false, false, false, true},
                            Fields{"conclude", false, true, false, false}}) {
        session.choose("node.kind", row.kind);
        require(bool(find(session.view(), "node.role")) == row.role &&
                bool(find(session.view(), "node.text")) == row.text &&
                bool(find(session.view(), "node.iterations")) == row.iterations &&
                bool(find(session.view(), "node.condition")) == row.condition &&
                find(session.view(), "node.parent") && find(session.view(), "node.index") &&
                find(session.view(), "node.otherwise"),
                std::string(row.kind) + " showed irrelevant block properties or hid placement controls");
        if (row.condition) {
            const auto& condition = widget(session.view(), "node.condition");
            require(option(condition, "rejected") == (std::string_view(row.kind) == "branch"),
                    "Repeat and branch exposed the same rejection condition");
            require(condition.state.help.find("Approved") != std::string::npos &&
                    condition.state.help.find("Supported") != std::string::npos &&
                    condition.state.help.find("doubt") != std::string::npos,
                    "Condition choices omitted the approval, supportability and unresolved-doubt tooltip");
        }
    }
    session.choose("node.kind", "repeat");
    require(session.text("node.iterations").empty() &&
            widget(session.view(), "node.iterations").state.placeholder == "3",
            "A new loop prefilled its limit instead of showing the insertion default");
    session.edit("node.iterations", "0");
    session.choose("node.kind", "agent");
    require(session.text("node.role").empty() && session.text("node.text").empty() &&
            session.text("node.parent").empty() && session.text("node.index").empty() &&
            widget(session.view(), "node.role").state.placeholder == "writer" &&
            widget(session.view(), "node.text").state.placeholder.find("requirements") != std::string::npos &&
            widget(session.view(), "node.text").state.placeholder.find("evidence") != std::string::npos,
            "A new agent inserted its role, prompt or placement placeholders into editable values");
    session.activate("flow.add");
    require(widget(session.view(), "wb.status").state.font.tone == gui::Tone::error &&
            session.text("wb.flow.text").empty() && session.text("node.text").empty(),
            "Adding a blank agent silently inserted its prompt placeholder");
    session.edit("node.text", "Use the selected evidence.");
    session.activate("flow.add");
    session.success("insert agent with the default role");
    auto parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes.size() == 1 && parsed.program->nodes[0].role == "writer" &&
            parsed.program->nodes[0].text == "Use the selected evidence." &&
            session.text("node.role").empty() && session.text("node.text").empty() &&
            session.text("node.parent").empty() && session.text("node.index").empty() &&
            !widget(session.view(), "flow.apply").state.enabled,
            "Agent insertion parsed a hidden loop limit, lost its default role or retained selected-block values");
    session.choose("node.kind", "critique");
    require(widget(session.view(), "node.role").state.placeholder == "reviewer" &&
            widget(session.view(), "node.text").state.placeholder.find("approval") != std::string::npos &&
            widget(session.view(), "node.text").state.placeholder.find("support") != std::string::npos,
            "Critique insertion displayed agent placeholders");
    session.edit("node.text", "Check every cited claim.");
    session.activate("flow.add");
    session.success("append critique with the default role and position");
    parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes.size() == 2 &&
            parsed.program->nodes[1].kind == FlowKind::critique &&
            parsed.program->nodes[1].role == "reviewer" && parsed.program->nodes[1].text == "Check every cited claim.",
            "Blank placement or role fields did not append a critique with its useful default role");
    session.choose("node.kind", "conclude");
    require(session.text("node.text").empty() &&
            widget(session.view(), "node.text").state.placeholder.find("requirements") != std::string::npos &&
            widget(session.view(), "node.text").state.placeholder.find("evidence") != std::string::npos,
            "Conclusion insertion prefilled its prompt or displayed another block's placeholder");
    session.edit("node.text", "Deliver the checked answer.");
    session.activate("flow.add");
    session.success("append conclusion");
    parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes.size() == 3 &&
            parsed.program->nodes.back().kind == FlowKind::conclude &&
            parsed.program->nodes.back().text == "Deliver the checked answer.",
            "A conclusion parsed irrelevant agent or loop fields");
    session.edit("wb.flow.text", "repeat 7\n  agent inner: Preserve the loop body.\nuntil approved\n"
                                 "if supported\n  agent yes: Preserve the branch body.\nelse\n"
                                 "  conclude: Preserve the alternative.\nend\n");
    session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.1").state.bounds));
    require(session.text("node.iterations") == "7" && !find(session.view(), "node.role") &&
            !find(session.view(), "node.text"),
            "Selecting a loop did not show its actual limit and relevant properties");
    session.edit("node.iterations", "");
    session.choose("node.condition", "supported");
    session.activate("flow.apply");
    session.success("apply loop default and supported condition");
    parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes[0].iterations == 3 &&
            parsed.program->nodes[0].condition == FlowCondition::supported &&
            parsed.program->nodes[0].children.size() == 1 &&
            parsed.program->nodes[0].children[0].text == "Preserve the loop body.",
            "Clearing a loop limit did not use three or applying its relevant fields discarded the body");
    session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.3").state.bounds));
    session.choose("node.condition", "rejected");
    session.activate("flow.apply");
    session.success("apply a branch rejection condition");
    parsed = parse_pseudocode(session.text("wb.flow.text"));
    require(parsed && parsed.program->nodes[1].kind == FlowKind::branch &&
            parsed.program->nodes[1].condition == FlowCondition::rejected &&
            parsed.program->nodes[1].children.size() == 1 && parsed.program->nodes[1].otherwise.size() == 1,
            "Applying a branch condition discarded its nested branches");
    const auto branch_source = session.text("wb.flow.text");
    session.choose("node.kind", "repeat");
    require(widget(session.view(), "node.condition").state.selected == "approved" &&
            !option(widget(session.view(), "node.condition"), "rejected") &&
            session.text("wb.flow.text") == branch_source,
            "Changing a rejected branch to repeat retained an unsupported condition or eagerly edited source");
}

void flow_canvas_transform_and_ownership() {
    const PseudocodeDocument document("agent alpha: Keep the workflow.\n");
    const auto graph = document.graph();
    const gui::Rect viewport{100, 200, 600, 300};
    FlowView flow;
    flow.render(graph, viewport);
    const auto node = graph.nodes.front();
    const auto start = flow.model_to_view({node.x + node.width / 2, node.y + node.height / 2});
    require(!flow.begin_drag(0, start) && !flow.begin_drag(7, {viewport.x - 1, viewport.y}),
            "Flow gesture accepted a missing owner or a press outside its viewport");
    require(flow.begin_drag(7, start) && !flow.begin_drag(8, start),
            "A second pointer replaced the captured flow owner");
    require(!flow.drag_to(8, {start.x + 30, start.y}) &&
            !flow.end_drag(8, start) && !flow.cancel_drag(8) && flow.dragging(),
            "A foreign pointer changed or cancelled the flow gesture");
    require(!flow.drag_to(7, {start.x + 2, start.y + 1}),
            "A small click movement panned the flow canvas");
    near(flow.pan().x, 0, "A small click movement changed horizontal pan");
    near(flow.pan().y, 0, "A small click movement changed vertical pan");
    require(flow.end_drag(7, {start.x + 2, start.y + 1}) == node.id && !flow.dragging(),
            "A small flow gesture did not select its pressed block on release");

    for (const double zoom : {.5, 2.0}) {
        flow.set_view(zoom, {12, 25});
        flow.render(graph, viewport);
        const gui::Point origin{viewport.x + viewport.width - 12, viewport.y + 50};
        require(flow.begin_drag(7, origin), "Zoomed canvas did not capture a fresh pointer");
        require(flow.drag_to(7, {origin.x + 32, origin.y - 12}),
                "Zoomed drag did not pan outside the viewport");
        near(flow.pan().x, 12 - 32 / zoom, "Horizontal drag ignored screen-to-model zoom conversion");
        near(flow.pan().y, 25 + 12 / zoom, "Vertical drag ignored screen-to-model zoom conversion");
        const auto transformed = flow.model_to_view({31, 47});
        const auto round_trip = flow.view_to_model(transformed);
        near(round_trip.x, 31, "Panned horizontal transform failed to round trip");
        near(round_trip.y, 47, "Panned vertical transform failed to round trip");
        require(!flow.end_drag(7, {origin.x + 40, origin.y - 14}) && !flow.dragging(),
                "Releasing a pan selected a block or retained capture");
        near(flow.pan().x, 12 - 40 / zoom, "Release lost the final horizontal pointer position");
        near(flow.pan().y, 25 + 14 / zoom, "Release lost the final vertical pointer position");
    }

    flow.set_view(1, {});
    flow.render(graph, viewport);
    require(flow.begin_drag(7, start) && flow.drag_to(7, {start.x + 20, start.y}) &&
            flow.drag_to(7, start) && !flow.end_drag(7, start),
            "A pan that returned to its origin became a block click");
    flow.set_view(2, {gui::coordinate_limit - 2, gui::coordinate_limit - 3});
    flow.render(graph, viewport);
    const auto empty_start = center(viewport);
    require(flow.begin_drag(7, empty_start), "Canvas near the coordinate limit did not capture");
    require(!flow.drag_to(7, {std::numeric_limits<double>::infinity(), empty_start.y}),
            "Flow gesture accepted a nonfinite pointer position");
    require(flow.drag_to(7, {-gui::coordinate_limit, -gui::coordinate_limit}),
            "Large finite flow displacement did not pan");
    near(flow.pan().x, gui::coordinate_limit, "Horizontal pan escaped its finite coordinate bound");
    near(flow.pan().y, gui::coordinate_limit, "Vertical pan escaped its finite coordinate bound");
    const auto bounded_pan = flow.pan();
    require(flow.cancel_drag(7) && !flow.dragging(), "Flow cancellation did not release its owner");
    near(flow.pan().x, bounded_pan.x, "Cancellation reset horizontal pan");
    near(flow.pan().y, bounded_pan.y, "Cancellation reset vertical pan");
}

gui::Delivery pointer_delivery(Session& session, gui::WidgetKey target, gui::Point point,
                              gui::PointerKind kind, std::uint64_t owner = 1) {
    gui::PointerInput input;
    input.kind = kind; input.position = point; input.pointer_id = owner;
    const auto delivery = session.adapter.send(gui::WidgetEvent{std::move(target), input});
    session.presented("flow pointer delivery");
    return delivery;
}

void flow_canvas_gestures() {
    Temporary fixture;
    const std::string source = "agent alpha: Keep the first block.\ncritique beta: Keep the second block.\n";
    const std::string markdown = "# Gesture fixture\n\n```pseudocode\n" + source + "```\n";
    write(fixture.root / "first.chat.md", markdown);
    Workspace seed_workspace(fixture.root);
    auto seed = seed_workspace.open_chat("first.chat.md");
    seed.state.draft = "```pseudocode\n" + source + "```\n";
    seed_workspace.save_state(seed);
    Session session(fixture.root, "first.chat.md");
    session.activate("tab.center.Pseudocode Editor");
    const auto files = inventory(fixture.root);
    const auto canvas_bounds = widget(session.view(), "wb.flow.canvas").state.bounds;
    const auto stable_canvas = [&](std::string_view step) {
        require(widget(session.view(), "wb.flow.canvas").state.bounds == canvas_bounds,
                std::string(step) + ": gesture controls moved or resized the canvas viewport");
    };
    const auto first = widget(session.view(), "wb.flow.node.1").state.bounds;
    const auto first_point = center(first);
    require(!widget(session.view(), "flow.apply").state.enabled && !find(session.view(), "flow.drag.cancel"),
            "Pristine canvas started with a selected block or active gesture");
    session.pointer("wb.flow.canvas", first_point, gui::PointerKind::press);
    stable_canvas("Block press");
    require(!widget(session.view(), "flow.apply").state.enabled && find(session.view(), "flow.drag.cancel"),
            "Pressing a block selected it before release or omitted gesture cancellation");
    const auto pressed_revision = session.view().revision;
    session.pointer("wb.flow.canvas", {first_point.x + 2, first_point.y + 1}, gui::PointerKind::move);
    stable_canvas("Below-threshold move");
    near(widget(session.view(), "wb.flow.node.1").state.bounds.x, first.x,
         "Below-threshold canvas movement panned its blocks");
    require(session.view().revision == pressed_revision,
            "Below-threshold movement rebuilt an unchanged canvas snapshot");
    session.pointer("wb.flow.canvas", {first_point.x + 2, first_point.y + 1}, gui::PointerKind::release);
    stable_canvas("Block release");
    require(session.text("node.role") == "alpha" && widget(session.view(), "flow.apply").state.enabled &&
            !find(session.view(), "flow.drag.cancel"), "A small released gesture did not select its block");

    const auto second_point = center(widget(session.view(), "wb.flow.node.2").state.bounds);
    session.pointer("wb.flow.canvas", second_point, gui::PointerKind::press);
    stable_canvas("Drag press");
    const auto captured = widget(session.view(), "wb.flow.canvas").spec.key;
    const auto epoch = session.application->input_epoch();
    const auto revision = session.view().revision;
    for (const auto kind : {gui::PointerKind::press, gui::PointerKind::move,
                           gui::PointerKind::release, gui::PointerKind::cancel})
        require(pointer_delivery(session, captured, second_point, kind, 2) == gui::Delivery::ignored,
                "A foreign pointer changed a captured canvas gesture");
    require(session.view().revision == revision && session.application->input_epoch() == epoch,
            "Ignored foreign pointer input advanced application state");
    session.pointer("wb.flow.canvas", {second_point.x + 20, second_point.y + 10}, gui::PointerKind::move);
    stable_canvas("Intermediate drag");
    require(widget(session.view(), "wb.flow.canvas").spec.key == captured && session.text("node.role") == "alpha",
            "Dragging over another block replaced capture or changed the selected block");
    near(widget(session.view(), "wb.flow.node.1").state.bounds.x, first.x + 20,
         "Dragging a block did not pan the canvas horizontally");
    near(widget(session.view(), "wb.flow.node.1").state.bounds.y, first.y + 10,
         "Dragging a block did not pan the canvas vertically");
    const auto moved_revision = session.view().revision;
    const auto moved_bitmap = widget(session.view(), "wb.flow.canvas").state.bitmap;
    session.pointer("wb.flow.canvas", {second_point.x + 20, second_point.y + 10}, gui::PointerKind::move);
    require(session.view().revision == moved_revision &&
            widget(session.view(), "wb.flow.canvas").state.bitmap.source_id == moved_bitmap.source_id &&
            widget(session.view(), "wb.flow.canvas").state.bitmap.revision == moved_bitmap.revision,
            "Repeated identical movement rebuilt the snapshot or replaced the unchanged flow bitmap");
    session.pointer("wb.flow.canvas", {second_point.x + 30, second_point.y + 15}, gui::PointerKind::release);
    stable_canvas("Drag release");
    near(widget(session.view(), "wb.flow.node.1").state.bounds.x, first.x + 30,
         "Canvas release omitted its final horizontal displacement");
    require(session.text("node.role") == "alpha" && session.text("wb.flow.text") == source &&
            inventory(fixture.root) == files, "Panning changed selection, source text or project files");

    const auto viewport = widget(session.view(), "wb.flow.canvas").state.bounds;
    const gui::Point blank{viewport.x + viewport.width - 8, viewport.y + viewport.height - 8};
    const auto before_outside = widget(session.view(), "wb.flow.node.1").state.bounds;
    session.pointer("wb.flow.canvas", blank, gui::PointerKind::press);
    session.pointer("wb.flow.canvas", {blank.x + 20, blank.y}, gui::PointerKind::move);
    session.pointer("wb.flow.canvas", {blank.x + 25, blank.y}, gui::PointerKind::release);
    near(widget(session.view(), "wb.flow.node.1").state.bounds.x, before_outside.x + 25,
         "Captured continuation outside the canvas lost its displacement");
    require(session.text("node.role") == "alpha", "Dragging blank canvas changed the selected block");

    // These right/down drags leave both model-space pan axes negative. The
    // arrows must continue in their own direction rather than jump back to zero.
    const auto before_arrows = widget(session.view(), "wb.flow.node.1").state.bounds;
    session.activate("flow.pan.left");
    near(widget(session.view(), "wb.flow.node.1").state.bounds.x, before_arrows.x + 160,
         "Left navigation reversed direction after a drag produced negative pan");
    session.activate("flow.pan.up");
    near(widget(session.view(), "wb.flow.node.1").state.bounds.y, before_arrows.y + 160,
         "Up navigation reversed direction after a drag produced negative pan");
    session.activate("flow.pan.right");
    near(widget(session.view(), "wb.flow.node.1").state.bounds.x, before_arrows.x,
         "Opposite horizontal navigation did not restore a negative-pan view");
    session.activate("flow.pan.down");
    near(widget(session.view(), "wb.flow.node.1").state.bounds.y, before_arrows.y,
         "Opposite vertical navigation did not restore a negative-pan view");

    session.activate("flow.zoom.in");
    for (unsigned repeat = 0; repeat != 2; ++repeat) {
        const auto before = widget(session.view(), "wb.flow.node.1").state.bounds;
        const auto point = center(before);
        session.pointer("wb.flow.canvas", point, gui::PointerKind::press);
        session.pointer("wb.flow.canvas", {point.x + 16, point.y - 6}, gui::PointerKind::move);
        session.pointer("wb.flow.canvas", {point.x + 16, point.y - 6}, gui::PointerKind::release);
        near(widget(session.view(), "wb.flow.node.1").state.bounds.x, before.x + 16,
             "A repeated zoomed drag changed the screen displacement");
        near(widget(session.view(), "wb.flow.node.1").state.bounds.y, before.y - 6,
             "Zoomed vertical panning used model displacement as screen displacement");
    }
    require(session.text("wb.flow.text") == source && inventory(fixture.root) == files,
            "Repeated zoomed panning changed source bytes or workspace files");
    session.activate("tab.center.Chat Markdown");
    require(session.text("wb.chat.text") == markdown, "Canvas gestures altered the ordinary chat Markdown");
}

void flow_canvas_cancellation() {
    const std::string source = "agent alpha: Preserve this workflow.\ncritique beta: Keep this selection distinct.\n";
    const auto cancelled = [&](std::string_view step, auto cancel, auto restore) {
        Temporary fixture;
        write(fixture.root / "first.chat.md", "# First\n\n```pseudocode\n" + source + "```\n");
        write(fixture.root / "second.chat.md", "# Second\n\n```pseudocode\nagent gamma: Other chat.\n```\n");
        Workspace seed_workspace(fixture.root);
        auto seed = seed_workspace.open_chat("first.chat.md");
        seed.state.draft = "```pseudocode\n" + source + "```\n";
        seed_workspace.save_state(seed);
        Session session(fixture.root, "first.chat.md");
        session.activate("tab.center.Pseudocode Editor");
        session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.1").state.bounds));
        const auto point = center(widget(session.view(), "wb.flow.node.2").state.bounds);
        const auto initial_viewport = widget(session.view(), "wb.flow.canvas").state.bounds;
        session.pointer("wb.flow.canvas", point, gui::PointerKind::press);
        require(widget(session.view(), "wb.flow.canvas").state.bounds == initial_viewport,
                std::string(step) + ": pressing a block moved the canvas viewport");
        const auto old_canvas = widget(session.view(), "wb.flow.canvas").spec.key;
        const gui::Point moved{point.x + 17, point.y + 11};
        session.pointer("wb.flow.canvas", moved, gui::PointerKind::move);
        const auto panned = widget(session.view(), "wb.flow.node.1").state.bounds;
        const auto viewport = widget(session.view(), "wb.flow.canvas").state.bounds;
        require(viewport == initial_viewport,
                std::string(step) + ": intermediate dragging moved the canvas viewport");
        require(session.text("node.role") == "alpha", "Gesture press replaced the current block before cancellation");
        cancel(session, moved);
        require(!find(session.view(), "flow.drag.cancel") && !session.adapter.closed(),
                std::string(step) + ": cancellation retained the gesture or closed the app");
        restore(session);
        const auto canvas = widget(session.view(), "wb.flow.canvas").spec.key;
        const auto current_viewport = widget(session.view(), "wb.flow.canvas").state.bounds;
        require(current_viewport == initial_viewport,
                std::string(step) + ": cancelling a gesture moved the canvas viewport");
        const auto retained = widget(session.view(), "wb.flow.node.1").state.bounds;
        require(canvas != old_canvas, std::string(step) + ": cancellation retained the captured canvas generation");
        near(retained.x - current_viewport.x, panned.x - viewport.x,
             std::string(step) + ": cancellation reset horizontal pan");
        near(retained.y - current_viewport.y, panned.y - viewport.y,
             std::string(step) + ": cancellation reset vertical pan");
        require(session.text("wb.flow.text") == source, std::string(step) + ": cancellation edited the workflow");
        const auto role = session.text("node.role");
        for (const auto& target : {old_canvas, canvas}) {
            require(pointer_delivery(session, target, moved, gui::PointerKind::move) == gui::Delivery::ignored &&
                    pointer_delivery(session, target, moved, gui::PointerKind::release) == gui::Delivery::ignored,
                    std::string(step) + ": cancelled capture accepted an orphan continuation");
        }
        require(session.text("node.role") == role, std::string(step) + ": late release changed block selection");
        session.click("wb.flow.canvas", center(retained));
        require(session.text("node.role") == "alpha" && !find(session.view(), "flow.drag.cancel"),
                std::string(step) + ": cancellation prevented a fresh pointer gesture");
    };
    const auto remain = [](Session&) {};
    cancelled("Escape", [](Session& s, gui::Point) { s.escape(); }, remain);
    cancelled("Stop drag", [](Session& s, gui::Point) { s.activate("flow.drag.cancel"); }, remain);
    cancelled("Focus loss", [](Session& s, gui::Point p) {
        s.pointer("wb.flow.canvas", p, gui::PointerKind::cancel);
    }, remain);
    cancelled("Property input", [](Session& s, gui::Point) { s.edit("node.text", "Unsaved property input."); }, remain);
    cancelled("Tab switch", [](Session& s, gui::Point) { s.activate("tab.center.Chat Markdown"); },
              [](Session& s) { s.activate("tab.center.Pseudocode Editor"); });
    cancelled("Chat switch", [](Session& s, gui::Point) { s.chat("second.chat.md"); },
              [](Session& s) { s.chat("first.chat.md"); });
    cancelled("Modal transition", [](Session& s, gui::Point) { s.activate("wb.new"); },
              [](Session& s) { require(s.view().modal_root.has_value(), "New chat did not open a modal"); s.escape(); });
    cancelled("Resize", [](Session& s, gui::Point) {
        require(s.adapter.send(gui::ResizeEvent{s.view().client_size, s.view().display_scale}) == gui::Delivery::delivered,
                "Explicit resize was not delivered");
        s.presented("resize during flow gesture");
    }, remain);
}

void flow_canvas_wheel_zoom_preserves_the_draft() {
    Temporary fixture;
    const std::string source = "agent first: Keep this source.\ncritique second: Check the evidence.\n";
    const std::string draft = "Retain the surrounding message.\n\n```pseudocode\n" + source + "```\n";
    write(fixture.root / "chat.chat.md", "# Wheel fixture\n");
    Workspace workspace(fixture.root);
    auto chat = workspace.open_chat("chat.chat.md");
    chat.state.draft = draft;
    chat.state.pseudocode = source;
    workspace.save_state(chat);
    Session session(fixture.root, "chat.chat.md");
    session.activate("tab.center.Pseudocode Editor");
    const auto files = inventory(fixture.root);
    const auto viewport = widget(session.view(), "wb.flow.canvas").state.bounds;
    const auto original = widget(session.view(), "wb.flow.node.1").state.bounds;
    const gui::Point anchor{original.x + 1, original.y + 1};
    const auto wheel = [&](double detents) {
        gui::PointerInput input;
        input.kind = gui::PointerKind::wheel;
        input.position = anchor;
        input.wheel_y = detents;
        session.send("wb.flow.canvas", input);
        require(widget(session.view(), "wb.flow.canvas").state.bounds == viewport &&
                session.text("wb.flow.text") == source && inventory(fixture.root) == files,
                "Wheel zoom moved the viewport or changed the source, draft or saved files");
    };
    wheel(1);
    const auto larger = widget(session.view(), "wb.flow.node.1").state.bounds;
    near(larger.width, original.width * 1.25, "Positive canvas wheel did not zoom in");
    near(larger.x, anchor.x + (original.x - anchor.x) * 1.25,
         "Wheel zoom moved the model point under its horizontal pointer anchor");
    near(larger.y, anchor.y + (original.y - anchor.y) * 1.25,
         "Wheel zoom moved the model point under its vertical pointer anchor");
    wheel(-1);
    const auto restored = widget(session.view(), "wb.flow.node.1").state.bounds;
    near(restored.width, original.width, "Negative canvas wheel did not zoom out");
    near(restored.x, original.x, "Opposite wheel zoom failed to restore horizontal placement");
    near(restored.y, original.y, "Opposite wheel zoom failed to restore vertical placement");
    wheel(100);
    near(widget(session.view(), "wb.flow.node.1").state.bounds.width, original.width * 2,
         "Large positive wheel exceeded the canvas zoom upper bound");
    const auto upper_revision = session.view().revision;
    wheel(1);
    require(session.view().revision == upper_revision, "Wheel at the zoom upper bound rebuilt the unchanged view");
    wheel(-100);
    near(widget(session.view(), "wb.flow.node.1").state.bounds.width, original.width * .2,
         "Large negative wheel exceeded the canvas zoom lower bound");
    const auto lower_revision = session.view().revision;
    wheel(-1);
    require(session.view().revision == lower_revision, "Wheel at the zoom lower bound rebuilt the unchanged view");
    const auto stale_canvas = widget(session.view(), "wb.flow.canvas").spec.key;
    const auto edited_source = source + "conclude: Preserve this explicit addition.\n";
    session.edit("wb.flow.text", edited_source);
    const auto edited_bounds = widget(session.view(), "wb.flow.node.1").state.bounds;
    const auto epoch = session.application->input_epoch();
    gui::PointerInput stale_wheel;
    stale_wheel.kind = gui::PointerKind::wheel;
    stale_wheel.position = anchor;
    stale_wheel.wheel_y = 1;
    require(session.adapter.send(gui::WidgetEvent{stale_canvas, stale_wheel}) == gui::Delivery::ignored &&
            session.application->input_epoch() == epoch &&
            widget(session.view(), "wb.flow.node.1").state.bounds == edited_bounds &&
            session.text("wb.flow.text") == edited_source,
            "A wheel action from the older flow draft changed its replacement canvas");
    session.activate("tab.center.Chat Markdown");
    require(session.text("wb.composer") ==
                "Retain the surrounding message.\n\n```pseudocode\n" + edited_source + "```\n" &&
            read(fixture.root / "chat.chat.md") == "# Wheel fixture\n",
            "Wheel navigation consumed the composer or changed conversation history");
}

void latest_pseudocode_fence() {
    Temporary fixture;
    const std::string history = "agent historical: Keep the original workflow.\n";
    const std::string latest = "agent latest: Current instruction.\ncritique checker: Check current version.\n";
    const std::string transcript = "# Transcript\n\n## Assistant\n\n```pseudocode\n" + history +
        "```\n\n## User\n\n```pseudocode\nagent forged: Never execute transcript history.\n```\n";
    write(fixture.root / "history.chat.md", transcript);
    Workspace workspace(fixture.root);
    auto seed = workspace.open_chat("history.chat.md");
    seed.state.draft = "Use this revised workflow.\n\n```pseudocode\n" + latest + "```\n";
    seed.state.pseudocode = "agent sidecar: Never execute a separate saved plan.\n";
    workspace.save_state(seed);
    const std::string updated = "agent latest: Updated current instruction.\ncritique checker: Check current version.\n";
    {
        Session session(fixture.root, "history.chat.md");
        session.activate("tab.center.Pseudocode Editor");
        require(session.text("wb.flow.text") == latest,
                "Pseudocode editor selected history or sidecar instead of the current composer fence");
        session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.1").state.bounds));
        require(session.text("node.role") == "latest", "Composer workflow graph selected a historical node");
        session.edit("node.text", "Updated current instruction.");
        session.activate("flow.apply");
        session.success("composer workflow graph edit");
        require(session.text("wb.flow.text") == updated, "Graph edit did not update the composer workflow");
        session.activate("tab.center.Chat Markdown");
        require(session.text("wb.chat.text") == transcript &&
                session.text("wb.composer") == "Use this revised workflow.\n\n```pseudocode\n" + updated + "```\n",
                "Graph edit changed transcript bytes or surrounding composer text");
        session.application->handle(gui::CloseEvent{});
        require(session.adapter.closed(), "Closing did not flush a clean composer workflow");
    }
    require(read(fixture.root / "history.chat.md") == transcript,
            "Flushing a composer workflow changed historical transcript bytes");
    const std::string assistant_proposal = "\n## Assistant\n\n```pseudocode\nagent proposal: Ignore this assistant suggestion.\n```\n";
    write(fixture.root / "history.chat.md", transcript + assistant_proposal);
    Session reopened(fixture.root, "history.chat.md");
    reopened.activate("tab.center.Pseudocode Editor");
    require(reopened.text("wb.flow.text") == updated &&
            widget(reopened.view(), "wb.flow.node.1").state.accessible_name.find("Updated current instruction.") !=
                std::string::npos,
            "An appended assistant proposal replaced the saved composer workflow");
    const std::string ordinary_note = "\nAn ordinary human-added note.\n";
    reopened.activate("tab.center.Chat Markdown");
    reopened.check("wb.developer", true);
    reopened.edit("wb.chat.text", transcript + assistant_proposal + ordinary_note);
    reopened.activate("tab.center.Pseudocode Editor");
    require(reopened.text("wb.flow.text") == updated,
            "A Developer transcript edit promoted a historical or assistant workflow");
    reopened.click("wb.flow.canvas", center(widget(reopened.view(), "wb.flow.node.1").state.bounds));
    reopened.edit("node.text", "Final user-owned instruction.");
    reopened.activate("flow.apply");
    reopened.success("composer graph edit after assistant proposal");
    const std::string final_source = "agent latest: Final user-owned instruction.\ncritique checker: Check current version.\n";
    require(reopened.text("wb.flow.text") == final_source,
            "Graph editing changed an assistant proposal instead of the composer workflow");
    reopened.activate("tab.center.Chat Markdown");
    const auto final_chat = transcript + assistant_proposal + ordinary_note;
    require(reopened.text("wb.chat.text") == final_chat &&
            reopened.text("wb.composer") == "Use this revised workflow.\n\n```pseudocode\n" + final_source + "```\n",
            "Graph editing altered historical text or lost its composer workflow");
    reopened.autosave();
    reopened.success("composer workflow and Developer history autosave");
    const auto saved = workspace.open_chat("history.chat.md");
    require(read(fixture.root / "history.chat.md") == final_chat &&
            saved.state.pseudocode == final_source && saved.state.draft == reopened.text("wb.composer"),
            "Autosaving a composer workflow lost its exact draft or edited transcript");
}

void terminal_drafts_without_shells() {
    Temporary fixture;
    write(fixture.root / "first.chat.md", "# First terminal draft fixture\n");
    write(fixture.root / "second.chat.md", "# Second terminal draft fixture\n");
    Workspace workspace(fixture.root);
    for (const auto* path : {"first.chat.md", "second.chat.md"}) {
        auto chat = workspace.open_chat(path);
        chat.state.center_tab = "Bash Terminal";
        workspace.save_state(chat);
    }
    const auto original = inventory(fixture.root);
    // Restoring this pane exposes draft inputs without activating Start, Run
    // or the terminal tab action. No shell is started or receives commands.
    Session session(fixture.root, "first.chat.md");
    require(session.text("wb.terminal.command").empty() && session.text("wb.terminal.output").empty(),
            "Restoring the terminal pane started with another session's text");
    session.edit("wb.terminal.command", "first terminal draft text");
    session.chat("second.chat.md");
    require(session.text("wb.terminal.command").empty(), "Chat switching leaked the first terminal draft");
    session.edit("wb.terminal.command", "second terminal draft text");
    session.chat("first.chat.md");
    require(session.text("wb.terminal.command") == "first terminal draft text",
            "Returning to the first chat lost its terminal draft");
    session.chat("second.chat.md");
    require(session.text("wb.terminal.command") == "second terminal draft text",
            "Returning to the second chat lost its terminal draft");
    session.application->tick();
    session.presented("inert terminal draft checkpoint");
    session.activate("tab.left.Running Tasks");
    require(widget(session.view(), "wb.tasks").state.records.empty() &&
            session.text("wb.terminal.output").empty() && inventory(fixture.root) == original,
            "Editing inert terminal drafts launched a process or changed project files");
}

void pseudocode_without_final_newline() {
    Temporary fixture;
    const std::string transcript = "# Framing fixture\n";
    write(fixture.root / "chat.chat.md", transcript);
    Session session(fixture.root, "chat.chat.md");
    const auto one_fence = [](const std::string& text) {
        const auto first = text.find("```pseudocode\n");
        return first != std::string::npos && text.find("```pseudocode\n", first + 1) == std::string::npos;
    };
    const std::string raw = "agent writer: Draft without a final newline.";
    session.activate("tab.center.Pseudocode Editor");
    session.edit("wb.flow.text", raw);
    require(session.text("wb.flow.text") == raw, "Raw flow editing added an unsolicited final newline");
    session.activate("tab.center.Chat Markdown");
    require(one_fence(session.text("wb.composer")) && session.text("wb.chat.text") == transcript,
            "First raw flow edit duplicated its composer plan or changed history");
    const std::string note = "\nAn unrelated composer note.\n";
    session.edit("wb.composer", session.text("wb.composer") + note);
    session.activate("tab.center.Pseudocode Editor");
    require(session.text("wb.flow.text") == raw + "\n",
            "Composer editing did not preserve the exact framed pseudocode body");
    const std::string revised = "agent writer: Revise the source without a final newline.";
    session.edit("wb.flow.text", revised);
    session.activate("tab.center.Chat Markdown");
    require(one_fence(session.text("wb.composer")) &&
            session.text("wb.composer").find(revised + "\n```\n") != std::string::npos &&
            session.text("wb.composer").ends_with(note) && session.text("wb.chat.text") == transcript,
            "A second raw edit duplicated the plan or lost unrelated composer text");
    session.activate("tab.center.Pseudocode Editor");
    session.click("wb.flow.canvas", center(widget(session.view(), "wb.flow.node.1").state.bounds));
    session.edit("node.text", "Apply a graphical revision.");
    session.activate("flow.apply");
    session.success("graph edit without a raw final newline");
    const std::string final_source = "agent writer: Apply a graphical revision.\n";
    require(session.text("wb.flow.text") == final_source, "Graph edit did not update the intended source");
    session.activate("tab.center.Chat Markdown");
    require(one_fence(session.text("wb.composer")) &&
            session.text("wb.composer").find(final_source + "```\n") != std::string::npos &&
            session.text("wb.composer").ends_with(note) && session.text("wb.chat.text") == transcript,
            "Graph editing duplicated a composer plan lacking a raw final newline or changed history");
    session.autosave();
    Workspace saved(fixture.root);
    require(saved.open_chat("chat.chat.md").state.pseudocode == final_source &&
            one_fence(saved.open_chat("chat.chat.md").state.draft) &&
            read(fixture.root / "chat.chat.md") == transcript,
            "Autosaving duplicated the user's composer plan or changed history");
}

void transcription_validation(const std::filesystem::path& captures) {
    Temporary fixture;
    const std::string chat = "# Local transcription fixture\n";
    write(fixture.root / "chat.chat.md", chat);
    // A valid one-sample, mono 16-bit PCM WAV. Validation below must stop
    // before any external executable, model or transcription worker is used.
    constexpr char wav[] = "RIFF" "\x26\0\0\0" "WAVE" "fmt " "\x10\0\0\0"
        "\x01\0\x01\0" "\x40\x1f\0\0" "\x80\x3e\0\0" "\x02\0\x10\0"
        "data" "\x02\0\0\0" "\0\0";
    write(fixture.root / "recording.wav", std::string_view(wav, sizeof(wav) - 1));
    const auto original = inventory(fixture.root);
    Session session(fixture.root, "chat.chat.md");
    session.edit("wb.composer", "Retain this chat draft.");
    session.activate("tab.left.Files");
    session.select("wb.files", "recording.wav");
    session.activate("wb.file.actions");
    require(widget(session.view(), "wb.file.transcribe").state.enabled,
            "Selected WAV did not enable the local transcription action");
    session.activate("wb.file.transcribe");
    session.success("open transcription dialog");
    const auto media = (fixture.root / "recording.wav").string();
    require(session.view().modal_root && session.text("transcription.media") == media &&
            std::filesystem::path(session.text("transcription.media")).is_absolute() &&
            session.text("transcription.executable").empty() && session.text("transcription.model").empty() &&
            session.text("transcription.threads") == "2" && session.text("transcription.timeout") == "120",
            "Transcription dialog did not retain the selected absolute media path and safe local defaults");
    session.activate("transcription.run");
    session.error("absolute paths");
    require(session.view().modal_root && session.text("transcription.media") == media &&
            session.text("transcription.executable").empty() && session.text("transcription.model").empty() &&
            session.text("transcription.threads") == "2" && session.text("transcription.timeout") == "120" &&
            session.text("wb.chat.text") == chat && session.text("wb.composer") == "Retain this chat draft.",
            "Missing transcription paths discarded dialog fields or changed the chat");
    capture(session.view(), captures, "workbench-transcription-validation");
    session.activate("modal.cancel");
    require(!session.view().modal_root && !find(session.view(), "transcription.media"),
            "Transcription Cancel did not close the dialog");
    session.application->tick();
    session.presented("transcription validation checkpoint");
    session.activate("tab.left.Running Tasks");
    require(widget(session.view(), "wb.tasks").state.records.empty() && inventory(fixture.root) == original,
            "Invalid transcription launched a job or wrote project files");
}

void sidebar_visibility_retains_controls_and_is_global() {
    Temporary fixture;
    const auto project=fixture.root/"project",config=fixture.root/"config";
    write(project/"first.chat.md",long_transcript("Sidebar first"));
    write(project/"second.chat.md","# Sidebar second\n");
    Session session(project,"first.chat.md",config);
    require(widget(session.view(),"wb.sidebar").state.checked&&find(session.view(),"wb.right"),
            "The right sidebar did not default to visible");
    require(session.adapter.send(gui::ResizeEvent{{900,640},1})==gui::Delivery::delivered,
            "Sidebar fixture could not resize");
    session.activate("tab.right.Selector");
    session.edit("selector.path","source.txt");session.activate("selector.add");
    session.select("selector.paths","source.txt");
    session.edit("selector.path","Retained unsubmitted path");
    const auto path_key=widget(session.view(),"selector.path").spec.key;
    session.adapter.text_selection(path_key,{3,11});
    const auto right_offset=session.adapter.scroll_offset(widget(session.view(),"wb.right").spec.key);
    const auto old_calculations=widget(session.view(),"selector.calculations").spec.key;
    const auto old_right_tab=widget(session.view(),"tab.right.AI").spec.key;
    const auto old_middle=widget(session.view(),"wb.center").state.bounds;
    const auto old_right=widget(session.view(),"wb.right").state.bounds;
    session.edit("wb.composer","Retain this draft.");
    const auto composer=widget(session.view(),"wb.composer").spec.key;
    require(session.adapter.focus(composer),"Cannot focus sidebar fixture composer");
    session.adapter.text_selection(composer,{2,8});
    scroll_transcript(session,30);
    session.check("wb.sidebar",false);
    require(!find(session.view(),"wb.right")&&!find(session.view(),"tab.right.AI")&&
            !find(session.view(),"selector.calculations")&&
            widget(session.view(),"wb.sidebar").spec.parent=="wb.root"&&
            fully_visible(session.adapter.resolved_availability(widget(session.view(),"wb.sidebar").spec.key)),
            "Hidden sidebar retained controls or hid its global restore checkbox");
    near(widget(session.view(),"wb.center").state.bounds.width,old_middle.width+old_right.width+8,
         "Hidden sidebar did not return its width to the center");
    require(session.adapter.focused()==composer&&session.adapter.text_selection(composer)==gui::TextSelection{2,8}&&
            session.text("wb.composer")=="Retain this draft.",
            "Sidebar hiding changed composer identity, focus, selection or draft");
    const auto epoch=session.application->input_epoch();
    require(session.adapter.send(gui::WidgetEvent{old_calculations,gui::SetChecked{true}})==gui::Delivery::ignored&&
            session.adapter.send(gui::WidgetEvent{old_right_tab,gui::Activate{}})==gui::Delivery::ignored&&
            session.application->input_epoch()==epoch,
            "Hidden sidebar accepted stale controls");
    for(const auto& binding:session.view().key_bindings)
        require(!binding.target.id.starts_with("selector.")&&!binding.target.id.starts_with("ai.")&&
                (!binding.focus||!binding.focus->id.starts_with("selector.")),
                "Hidden sidebar leaked a keyboard target");
    session.edit("wb.composer","Retain this draft. More");
    session.shortcut("wb.composer",gui::ShortcutKey::z);
    require(session.text("wb.composer")=="Retain this draft.","Hidden sidebar broke focused composer undo");
    session.check("wb.sidebar",true);
    require(session.text("selector.path")=="Retained unsubmitted path"&&
            widget(session.view(),"selector.paths").state.selected=="source.txt"&&
            session.adapter.text_selection(widget(session.view(),"selector.path").spec.key)==gui::TextSelection{3,11},
            "Restoring sidebar discarded its field or list selection");
    require(session.adapter.scroll_offset(widget(session.view(),"wb.right").spec.key)==right_offset,
            "Restoring sidebar discarded its scroll position");
    require(session.adapter.focused()==composer&&transcript_offset(session)<=30,
            "Restoring sidebar stole composer focus or resumed transcript following");
    session.activate("tab.center.Pseudocode Editor");
    const auto graph_width=widget(session.view(),"wb.flow.canvas").state.bounds.width;
    const auto draft_before=session.text("wb.flow.text");
    session.check("wb.sidebar",false);
    require(widget(session.view(),"wb.flow.canvas").state.bounds.width>graph_width&&
            session.text("wb.flow.text")==draft_before,
            "Hidden sidebar failed to expand the flow canvas or changed source");
    session.chat("second.chat.md");
    require(!find(session.view(),"wb.right")&&!widget(session.view(),"wb.sidebar").state.checked,
            "Chat switching reset the global sidebar preference");
    session.application->shutdown();
    std::filesystem::create_directory(fixture.root/"other-project");
    Session reopened(fixture.root/"other-project",{},config);
    require(!find(reopened.view(),"wb.right")&&!widget(reopened.view(),"wb.sidebar").state.checked,
            "Sidebar preference did not survive project change and restart");
    reopened.check("wb.sidebar",true);
    require(find(reopened.view(),"wb.right")&&AiPreferences(config).right_sidebar_visible(),
            "Empty workspace could not restore and persist the sidebar");
}

void hidden_sidebar_reveals_ai_and_preserves_preference_conflicts() {
    Temporary fixture;
    const auto project=fixture.root/"project",config=fixture.root/"config";
    write(project/"chat.chat.md","# Sidebar repair\n");
    AiSettings defaults;defaults.provider="ollama";defaults.model="remembered-default";
    AiPreferences(config).save(defaults);
    Session session(project,"chat.chat.md",config);
    session.activate("tab.right.AI");session.edit("ai.model","");
    session.edit("wb.composer","Keep the repair draft.");
    session.check("wb.sidebar",false);
    AiPreferences external(config);external.set_tutorial_mode(true);
    const auto external_bytes=read(config/"ai-defaults.json");
    session.check("wb.sidebar",true);session.error("changed");
    require(!find(session.view(),"wb.right")&&!widget(session.view(),"wb.sidebar").state.checked&&
            read(config/"ai-defaults.json")==external_bytes,
            "A conflicting manual sidebar write changed visibility or replaced external preferences");
    const auto composer=widget(session.view(),"wb.composer").spec.key;
    require(session.adapter.focus(composer),"Cannot focus repair draft");
    session.adapter.text_selection(composer,{1,7});
    session.shortcut("wb.composer",gui::ShortcutKey::enter);
    session.error("Choose a model in AI");
    require(find(session.view(),"ai.model")&&widget(session.view(),"wb.sidebar").state.checked&&
            fully_visible(session.adapter.resolved_availability(widget(session.view(),"ai.model").spec.key))&&
            session.text("wb.status").find("could not remember")!=std::string::npos&&
            read(config/"ai-defaults.json")==external_bytes&&AiPreferences(config).defaults()==defaults&&
            session.text("wb.composer")=="Keep the repair draft."&&
            session.adapter.focused()==composer&&session.adapter.text_selection(composer)==gui::TextSelection{1,7},
            "AI repair stayed hidden, stole focus, consumed the draft or replaced remembered defaults on conflict");
    session.application->shutdown();
    const auto isolated_config=fixture.root/"selection-config";
    write(project/"second.chat.md","# Separate hidden AI selections\n");
    Workspace workspace(project);auto second=workspace.open_chat("second.chat.md");
    second.state.ai.provider="ollama";second.state.ai.model="invalid model two";second.state.ai_configured=true;
    workspace.save_state(second);
    Session separate(project,"chat.chat.md",isolated_config);
    separate.activate("tab.right.AI");separate.choose("ai.provider","ollama");separate.edit("ai.model","invalid model one");
    separate.adapter.text_selection(widget(separate.view(),"ai.model").spec.key,{2,8});
    separate.check("wb.sidebar",false);separate.chat("second.chat.md");separate.edit("wb.composer","Repair this chat only.");
    separate.activate("wb.send");separate.error("Model ID is invalid");
    require(separate.text("ai.model")=="invalid model two"&&
            separate.adapter.text_selection(widget(separate.view(),"ai.model").spec.key)==gui::TextSelection{0,0},
            "AI repair restored another chat's hidden field selection");
}

void code_is_an_explicit_chat_option() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;
    const auto project=fixture.root/"project",config=fixture.root/"config";
    write(project/"first.chat.md","# First Code chat\n");write(project/"second.chat.md","# Second Code chat\n");
    const auto worker=offline_chat_worker(fixture.root);
    {
        Session session(project,"first.chat.md",config,true,worker);
        const auto& code=widget(session.view(),"selector.calculations").state;
        require(code.label=="Code"&&code.accessible_name=="Code"&&!code.checked,
                "Code omitted its visible/accessibility label or defaulted on");
        require(code.help.find("Python-shaped algorithms on numeric arrays")!=std::string::npos&&
                code.help.find("No imports, files, network or shell")!=std::string::npos,
                "Code omitted its bounded array algorithm capability description");
        session.check("selector.calculations",true);
        require(session.text("wb.status")=="Code enabled for this chat.","Code enable status used an obsolete tool name");
        session.activate("tab.right.Sources");
        require(session.text("wb.sources").find("Code: enabled for this chat.")!=std::string::npos,
                "Sources omitted this chat's enabled Code summary");
        session.activate("tab.right.Selector");
        session.chat("second.chat.md");
        require(!widget(session.view(),"selector.calculations").state.checked,
                "Code leaked into another chat");
        session.chat("first.chat.md");
        require(widget(session.view(),"selector.calculations").state.checked&&
                Workspace(project).open_chat("first.chat.md").state.selector.calculations,
                "Code was not retained in its owning chat state");
    }
    Session reopened(project,"first.chat.md",config,true,worker);
    require(widget(reopened.view(),"selector.calculations").state.checked,
            "Code did not survive restart");
    reopened.activate("tab.right.AI");reopened.choose("ai.provider","ollama");reopened.edit("ai.model","offline-code-model");
    reopened.edit("wb.composer","Use the enabled Code tool.");reopened.check("wb.sidebar",false);
    reopened.shortcut("wb.composer",gui::ShortcutKey::enter);
    wait_for(reopened,[&]{return !widget(reopened.view(),"wb.cancel").state.enabled;},"Code request completion");
    const auto request=json::parse(read(fixture.root/"first.chat.md.request.json"));
    require(request.find("selector")->find("calculations")->boolean()&&!find(reopened.view(),"wb.right"),
            "Hidden sidebar dropped the enabled Code flag or was opened by a successful Send");
    reopened.check("wb.sidebar",true);reopened.activate("tab.right.Selector");reopened.check("selector.calculations",false);
    require(reopened.text("wb.status")=="Code disabled for this chat.","Code disable status used an obsolete tool name");
    reopened.activate("tab.right.Sources");
    require(reopened.text("wb.sources").find("Code: off for this chat.")!=std::string::npos,
            "Sources omitted this chat's disabled Code summary");
    reopened.activate("wb.retry");
    wait_for(reopened,[&]{return !widget(reopened.view(),"wb.cancel").state.enabled;},"Code-disabled retry completion");
    require(!json::parse(read(fixture.root/"first.chat.md.request.json")).find("selector")->find("calculations")->boolean(),
            "Retry reused an old Code permission after it was disabled");
#endif
}

void builder_discovery_and_modes_are_explicit() {
    Temporary fixture;
    const auto project=fixture.root/"project",config=fixture.root/"config";
    std::filesystem::create_directory(project);
    {
        Session empty(project,{},config);
        require(!widget(empty.view(),"selector.builder").state.enabled&&
                widget(empty.view(),"selector.builder").state.help.find("chat")!=std::string::npos,
                "Selector builder did not explain that an owning chat is required");
        empty.activate("tab.left.Files");
        require(!widget(empty.view(),"wb.files.builder").state.enabled&&inventory(project).empty(),
                "Files builder implicitly created a chat");
    }
#if defined(__linux__) || defined(_WIN32)
    write(project/"chat.chat.md","# Builder discovery\n");write(project/"input.txt","Source input\n");
    Workspace builder_workspace(project);auto builder_chat=builder_workspace.open_chat("chat.chat.md");
    const auto stale_path=(fixture.root/"missing unrelated context").string();
    builder_chat.state.selector.scribbles={{stale_path,true}};builder_chat.state.selector.refs={{stale_path,true}};
    builder_chat.state.selector.tools={{stale_path,true}};builder_chat.state.selector.kiwix_index=stale_path;
    builder_workspace.save_state(builder_chat);
    AiPreferences preferences(config);
    preferences.save_configured_models({{"openrouter",{},"deepseek/deepseek-r1-0528","My explicit model"},
                                       {"ollama",{},"local-model","Different provider"}});
    const auto worker=fixture.root/"offline builder worker.py";
    write(worker,R"PY(import json, os, sys
assert sys.flags.isolated and sys.flags.no_user_site
with open(sys.argv[2], encoding='utf-8') as stream:
    request=json.load(stream)
assert request['operation'] in ('scribble', 'evaluate', 'models')
base=os.path.dirname(__file__)
with open(os.path.join(base, 'builder.'+request['operation']+'.json'), 'w', encoding='utf-8') as stream:
    json.dump(request,stream)
if request['operation']=='models':
    print(json.dumps({'ok':True,'models':[]}))
else:
    assert request['selector']['calculations'] is False
    if request['operation']=='evaluate':
        assert request['selector']['deep_research'] is False
        assert 'research_queries' not in request
        assert request['allowed_context_paths']==[]
        assert 'input_paths' not in request
    if not request['scribble']['ai_enabled'] and request['operation']=='scribble':
        assert request['settings']['network_enabled'] is False
        assert request['settings']['model']==''
        assert request['selector']['deep_research'] is False
        assert 'research_queries' not in request
        assert request['allowed_context_paths']==[]
        assert all(request['selector'][kind]==[] for kind in ('scribbles','refs','tools'))
        assert 'kiwix_index' not in request and 'research_paths' not in request
    print(json.dumps({'ok':True,'text':'Local builder fixture completed.','sources':[]}))
)PY");
    Session session(project,"chat.chat.md",config,true,worker);
    session.adapter.send(gui::ResizeEvent{{900,640},1});
    session.edit("wb.composer","Preserve builder draft.");session.check("selector.calculations",true);
    session.choose("selector.kind","refs");
    session.activate("selector.builder");
    require(session.text("builder.paths")=="."&&session.text("builder.output")==".zzz_compendium/refs/project"&&
            widget(session.view(),"builder.ai").state.selected=="false"&&!find(session.view(),"builder.model")&&
            !find(session.view(),"builder.web")&&!find(session.view(),"builder.small_model")&&
            session.text("builder.output_help").find("output DIRECTORY")!=std::string::npos&&
            !std::filesystem::exists(fixture.root/"builder.scribble.json"),
            "Visible Selector builder omitted root/Ref defaults, started AI or hid its output instructions");
    session.choose("builder.kind","scribbles");
    require(session.text("builder.output")==".zzz_compendium/scribbles/project",
            "Builder kind did not adjust its untouched output suggestion");
    session.edit("builder.output","chosen-index");session.choose("builder.kind","refs");
    require(session.text("builder.output")=="chosen-index","Builder kind replaced an explicit output path");
    session.choose("builder.ai","true");
    require(session.text("builder.model").empty()&&option(widget(session.view(),"builder.model_choice"),"deepseek/deepseek-r1-0528")&&
            !option(widget(session.view(),"builder.model_choice"),"moonshotai/kimi-k3")&&
            !option(widget(session.view(),"builder.model_choice"),"local-model"),
            "Builder implicitly selected a model, exposed hidden Tutorial examples or included another provider's model");
    session.choose("builder.model_choice","deepseek/deepseek-r1-0528");
    require(session.text("builder.model")=="deepseek/deepseek-r1-0528","Configured builder model was not editable in the Model ID field");
    session.edit("builder.model","openai/gpt-5");session.activate("builder.run");session.error("OpenAI");
    require(!session.view().modal_root&&find(session.view(),"builder.exit")&&!std::filesystem::exists(fixture.root/"builder.scribble.json"),
            "Prohibited builder model launched a task or discarded editable settings");
    session.edit("builder.model","moonshotai/kimi-k3");session.edit("builder.max_calls","not a number");session.choose("builder.web","true");
    session.choose("builder.ai","false");
    session.activate("builder.run");
    wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"local builder request completion");
    session.success("local builder request");
    const auto local=json::parse(read(fixture.root/"builder.scribble.json"));
    session.activate("builder.exit");
    require(local.find("output_dir")->string()=="chosen-index"&&local.find("input_paths")->array().front().string()=="."&&
            local.find("scribble")->find("max_provider_calls")->number()==32&&
            session.text("wb.composer")=="Preserve builder draft."&&
            widget(session.view(),"selector.paths").state.records.size()==1&&
            widget(session.view(),"selector.paths").state.records.front().id==stale_path,
            "Explicit local Build failed on irrelevant AI fields, lost its source/output/draft or silently enabled context");
    session.activate("selector.builder");session.activate("tab.builder.Setup");session.choose("builder.ai","true");session.choose("builder.web","true");
    session.edit("builder.max_calls","unused invalid annotation setting");session.choose("builder.ai","false");
    session.check("builder.evaluation",true);session.edit("builder.small_model","custom/evaluation-model");
    session.edit("builder.paths",stale_path);
    require(!find(session.view(),"builder.web"),"Local mode kept the annotation research control visible");
    session.activate("builder.evaluate");
    wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"explicit local-index evaluation completion");
    session.success("evaluation without stale annotation research");
    const auto evaluation=json::parse(read(fixture.root/"builder.evaluate.json"));
    require(!evaluation.find("selector")->find("deep_research")->boolean()&&!evaluation.find("research_queries")&&
            evaluation.find("settings")->find("model")->string()=="custom/evaluation-model",
            "Explicit evaluation used hidden stale web/call controls or replaced its chosen model");
    session.activate("builder.exit");session.activate("tab.left.Files");session.select("wb.files","input.txt");session.activate("wb.files.builder");
    require(session.text("builder.task.status").find("completed")!=std::string::npos,"Files reentry discarded the retained builder tab/task");
    session.activate("builder.new");
    require(session.text("builder.paths")=="input.txt"&&session.text("builder.output")==".zzz_compendium/scribbles/input.txt",
            "Explicit New task did not default to the selected Files source");
    session.activate("builder.exit");session.activate("tab.left.Chats");session.check("wb.tutorial",true);
    session.activate("selector.builder");session.choose("builder.ai","true");
    require(option(widget(session.view(),"builder.model_choice"),"moonshotai/kimi-k3")&&session.text("builder.model").empty(),
            "Explicit Tutorial mode did not reveal examples or selected a model implicitly");
    session.edit("builder.model","custom/reviewed-model");session.activate("builder.run");
    wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"explicit AI builder request completion");
    require(json::parse(read(fixture.root/"builder.scribble.json")).find("settings")->find("model")->string()=="custom/reviewed-model",
            "Manual builder model ID was replaced by a fixed choice");
    session.activate("builder.exit");session.activate("tab.right.AI");session.activate("ai.models.refresh");
    session.check("wb.sidebar",false);session.activate("tab.left.Running Tasks");
    wait_for(session,[&]{return std::filesystem::exists(fixture.root/"builder.models.json");},"offline model catalog task");
    session.select("wb.tasks",widget(session.view(),"wb.tasks").state.records.back().id);session.activate("wb.task.show");
    require(find(session.view(),"ai.model")&&widget(session.view(),"wb.sidebar").state.checked,
            "Show AI task failed to reveal the hidden sidebar");
#endif
}

void builder_typing_retains_native_control_identity() {
    Temporary fixture;const auto project=fixture.root/"project",config=fixture.root/"config";
    std::filesystem::create_directory(project);write(project/"chat.chat.md","# Builder input identity\n");
    Workspace workspace(project);auto chat=workspace.open_chat("chat.chat.md");
    for(const auto* id:{"task-a","task-b"}){BuilderTask task;task.id=id;task.label=id;task.status="completed";chat.state.builder.tasks.push_back(std::move(task));}
    chat.state.builder.selected_task="task-a";workspace.save_state(chat);
    Session session(project,"chat.chat.md",config);session.activate("selector.builder");session.reveal("builder.paths");
    const auto paths=widget(session.view(),"builder.paths").spec.key,body=widget(session.view(),"builder.body").spec.key,
        workspace_key=widget(session.view(),"builder.workspace").spec.key,run=widget(session.view(),"builder.run").spec.key;
    require(session.adapter.focus(paths),"Cannot focus builder source paths");session.adapter.text_selection(paths,{0,session.text("builder.paths").size()});
    std::string typed;
    for(const char letter:std::string("source.txt")) {
        typed+=letter;
        require(session.adapter.replace(paths,std::string(1,letter))==gui::Delivery::delivered,"Builder rejected consecutive typing without refocus");
        session.presented("builder consecutive typing");
        require(widget(session.view(),"builder.paths").spec.key==paths&&widget(session.view(),"builder.body").spec.key==body&&
                widget(session.view(),"builder.workspace").spec.key==workspace_key&&session.text("builder.paths")==typed&&
                session.adapter.focused()==paths&&session.adapter.text_selection(paths)==gui::TextSelection{typed.size(),typed.size()},
                "Builder typing replaced an input or ancestor, lost focus or failed to advance the caret");
    }
    session.autosave();
    require(widget(session.view(),"builder.paths").spec.key==paths&&widget(session.view(),"builder.body").spec.key==body&&
            widget(session.view(),"builder.workspace").spec.key==workspace_key&&session.adapter.focused()==paths&&
            session.adapter.text_selection(paths)==gui::TextSelection{typed.size(),typed.size()},"Builder autosave replaced the focused setup controls");
    const auto epoch=session.application->input_epoch(),revision=session.view().revision;
    require(session.adapter.send(gui::WidgetEvent{paths,gui::EditText{"obsolete","."}})==gui::Delivery::ignored&&
            session.adapter.send(gui::WidgetEvent{run,gui::Activate{}})==gui::Delivery::ignored&&
            session.application->input_epoch()==epoch&&session.view().revision==revision&&session.text("builder.paths")==typed,
            "Stable setup identity accepted an obsolete edit or stale Build action");
    session.activate("builder.new");require(session.text("builder.paths")=="."&&widget(session.view(),"builder.paths").spec.key!=paths,
            "New task reused the previous setup input identity");
    require(session.adapter.send(gui::WidgetEvent{paths,gui::EditText{"stale setup","."}})==gui::Delivery::ignored&&session.text("builder.paths")==".",
            "A queued edit from the previous setup replaced New task defaults");
    session.activate("tab.builder.Tasks");
    const auto tasks=widget(session.view(),"builder.tasks").spec.key,remove=widget(session.view(),"builder.task.remove").spec.key;
    session.select("builder.tasks","task-b");
    require(session.adapter.send(gui::WidgetEvent{tasks,gui::SelectRecord{"task-a"}})==gui::Delivery::ignored&&
            session.adapter.send(gui::WidgetEvent{remove,gui::Activate{}})==gui::Delivery::ignored&&
            widget(session.view(),"builder.tasks").state.selected=="task-b"&&widget(session.view(),"builder.tasks").state.records.size()==2,
            "Task selection left a stale record event or Remove action valid");
}

void persistent_builder_workspace_and_interrupted_tasks() {
#if defined(__linux__)
    Temporary fixture;const auto project=fixture.root/"project",config=fixture.root/"config";
    std::filesystem::create_directory(project);write(project/"chat.chat.md","# Persistent builder\n");write(project/"other.chat.md","# Other builder\n");write(project/"source.txt","Offline source.\n");
    const auto worker=fixture.root/"persistent builder worker.py";
    write(worker,R"PY(import json, os, pathlib, sys, time
assert sys.flags.isolated and sys.flags.no_user_site
with open(sys.argv[2], encoding='utf-8') as stream:
    request=json.load(stream)
assert request['operation'] in ('scribble','evaluate')
assert request['prompt']=='' and 'history' not in request and 'pseudocode' not in request
assert request['selector']['calculations'] is False
base=pathlib.Path(__file__).parent
with (base/'launches.jsonl').open('a',encoding='utf-8') as stream:
    stream.write(json.dumps(request)+'\n')
resume=request['scribble'].get('resume',False)
if request['operation']=='scribble':
    assert request['stream'] is True
    print(json.dumps({'stream_version':1,'event':'start','sequence':0,'operation':'scribble'}),flush=True)
    print(json.dumps({'stream_version':1,'event':'progress','sequence':1,'phase':'enriching','completed_chunks':1,'total_chunks':2,'resumed_chunks':1 if resume else 0}),flush=True)
while not (base/'finish').exists():
    time.sleep(.01)
if request['operation']=='scribble':
    output=pathlib.Path(request['output_dir'])
    if not output.is_absolute():output=pathlib.Path(request['root'])/output
    output.mkdir(exist_ok=True)
    (output/'scribbles.md').write_text('# Generated offline Scribble\n',encoding='utf-8')
    print(json.dumps({'stream_version':1,'event':'progress','sequence':2,'phase':'completed','completed_chunks':2,'total_chunks':2,'resumed_chunks':1 if resume else 0}),flush=True)
    print(json.dumps({'stream_version':1,'event':'final','sequence':3,'result':{'ok':True,'text':'Retained build result.','sources':[]}}),flush=True)
else:
    print(json.dumps({'ok':True,'text':'Retained evaluation result.','sources':[]}))
)PY");
    const auto launches=[&]{std::vector<json::Value> values;if(std::filesystem::exists(fixture.root/"launches.jsonl")){std::istringstream stream(read(fixture.root/"launches.jsonl"));std::string line;while(std::getline(stream,line))if(!line.empty())values.push_back(json::parse(line));}return values;};
    const auto saved=[&]{return Workspace(project).open_chat("chat.chat.md").state;};
    {
        Session session(project,"chat.chat.md",config,true,worker);session.adapter.send(gui::ResizeEvent{{900,640},1});session.edit("wb.composer","Keep my chat draft.");session.activate("selector.builder");
        require(!session.view().modal_root&&find(session.view(),"builder.workspace")&&!find(session.view(),"wb.center")&&fully_visible(session.adapter.resolved_availability(widget(session.view(),"builder.exit").spec.key)),"Builder did not occupy the main workspace with a persistent Exit control");
        session.edit("builder.output",(project/"retained-output").string());session.edit("builder.label","Retained task");session.escape();require(find(session.view(),"builder.paths")&&launches().empty(),"Escape exited setup or launched a task");
        session.activate("builder.run");wait_for(session,[&]{return launches().size()==1&&session.text("builder.task.status").find("enriching")!=std::string::npos;},"held builder progress");
        const auto first=widget(session.view(),"builder.tasks").state.records.front().id;const auto pause_key=widget(session.view(),"builder.task.pause").spec.key;
        session.escape();session.activate("tab.builder.Results");session.escape();require(!session.view().modal_root&&find(session.view(),"builder.exit")&&session.text("builder.result.text").find("1 / 2")!=std::string::npos,"Escape closed builder/results or progress was lost");
        session.activate("builder.exit");require(widget(session.view(),"wb.cancel").state.enabled&&session.text("wb.composer")=="Keep my chat draft.","Exit stopped the builder or changed the chat draft");
        session.activate("selector.builder");require(find(session.view(),"builder.result.text"),"Reentry reset the selected builder tab");
        session.activate("tab.builder.Setup");session.edit("builder.output","edited-after-launch");session.edit("builder.label","Edited later");session.choose("builder.ai","true");session.edit("builder.model","custom/later-model");
        require(!widget(session.view(),"builder.run").state.enabled&&launches().size()==1,"Setup launched a concurrent task or enabled another launch");
        session.activate("tab.builder.Tasks");session.activate("builder.task.pause");require(session.text("builder.task.status").find("paused")!=std::string::npos&&saved().builder.tasks.front().status=="paused","Explicit Pause did not retain/save the task");
        require(session.adapter.send(gui::WidgetEvent{pause_key,gui::Activate{}})==gui::Delivery::ignored,"Old Pause control remained valid after task completion");
        session.activate("builder.task.resume");wait_for(session,[&]{return launches().size()==2&&session.text("builder.task.status").find("enriching")!=std::string::npos;},"explicit Scribble resume");
        const auto requests=launches();auto original_request=requests[0];original_request.object().erase("stream");require(requests[1].find("scribble")->find("resume")->boolean()&&requests[1].find("output_dir")->string()==(project/"retained-output").string()&&requests[1].find("settings")->find("model")->string().empty()&&saved().builder.tasks.front().request_json==json::stringify(original_request,64*1024),"Resume changed the saved request or used later setup edits");
        session.activate("builder.exit");session.application.reset();require(saved().builder.tasks.front().status=="interrupted"&&saved().builder.selected_task==first,"Shutdown failed to persist interrupted worker ownership");
    }
    {
        Session session(project,"chat.chat.md",config,true,worker);require(launches().size()==2&&session.text("wb.composer")=="Keep my chat draft.","Reopening auto-launched work or lost the chat draft");session.activate("selector.builder");require(widget(session.view(),"builder.task.resume").state.enabled&&session.text("builder.task.status").find("interrupted")!=std::string::npos,"Interrupted saved task lacked explicit Resume");
        session.activate("builder.task.resume");wait_for(session,[&]{return launches().size()==3;},"restart resume launch");write(fixture.root/"finish","done\n");wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"resumed build completion");session.success("resumed build completion");
        require(saved().builder.tasks.front().status=="completed"&&saved().builder.tasks.front().completed_chunks==2&&saved().builder.tasks.front().resumed_chunks==1,"Saved resumed completion/progress was incorrect");
        session.activate("builder.task.show");require(session.text("builder.result.text").find("Retained build result.")!=std::string::npos,"Show Results lost retained output");session.activate("builder.task.refs");require(saved().selector.refs==std::vector<PathToggle>{{(project/"retained-output").string(),true}},"Use as Ref did not enable the task's original output directory");
        session.activate("builder.task.open");require(session.view().modal_root&&session.text("file.text")=="# Generated offline Scribble\n","Completed absolute output did not open in the ordinary file editor");session.escape();require(find(session.view(),"builder.exit")&&!session.view().modal_root,"Escape from nested file editor exited builder");
        session.activate("tab.builder.Setup");require(session.text("builder.output")=="edited-after-launch"&&session.text("builder.model")=="custom/later-model","Restart discarded edited setup");session.choose("builder.ai","false");session.check("builder.evaluation",true);session.edit("builder.small_model","custom/evaluation-model");session.activate("builder.evaluate");wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"retained evaluation completion");require(!widget(session.view(),"builder.task.resume").state.enabled&&widget(session.view(),"builder.task.retry").state.enabled,"Evaluation exposed checkpoint Resume or omitted explicit Retry");
        session.activate("builder.task.retry");wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"explicit evaluation retry");require(saved().builder.tasks.size()==3&&launches().size()==5,"Evaluation retry did not retain a new task");
        session.activate("builder.exit");session.activate("tab.left.Chats");session.chat("other.chat.md");session.activate("selector.builder");require(session.text("builder.output")==".zzz_compendium/scribbles/project"&&launches().size()==5,"Another chat inherited builder setup or launched work");session.activate("builder.exit");session.chat("chat.chat.md");session.activate("selector.builder");require(widget(session.view(),"builder.tasks").state.records.size()==3,"Switching chats discarded retained builder tasks");
        session.activate("builder.task.remove");require(saved().builder.tasks.size()==2&&std::filesystem::exists(project/"retained-output/scribbles.md"),"Remove record changed output files or failed to remove only the selected task");
        require(read(project/"chat.chat.md")=="# Persistent builder\n","Builder work changed chat history");
    }
#endif
}

void builder_restart_ownership_ids_and_checked_launch() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;const auto project=fixture.root/"project",config=fixture.root/"config";
    std::filesystem::create_directory(project);write(project/"chat.chat.md","# Saved tasks\n");
    const auto worker=fixture.root/"checked builder worker.py";write(worker,R"PY(import json, pathlib, sys
with open(sys.argv[2], encoding='utf-8') as stream:request=json.load(stream)
(pathlib.Path(__file__).parent/'launched').write_text(json.dumps(request),encoding='utf-8')
print(json.dumps({'ok':True,'text':'Saved task completed.','sources':[]}))
)PY");
    Workspace workspace(project);auto chat=workspace.open_chat("chat.chat.md");
    chat.state.builder.active=true;chat.state.builder.tab="Tasks";chat.state.builder.selected_task="builder-1";chat.state.builder.next_task_id=1;
    chat.state.builder.fields={{"builder.paths","."},{"builder.kind","scribbles"},{"builder.output","fresh-output"},{"builder.default_output","fresh-output"},{"builder.label","Saved task"},{"builder.ai","false"},{"builder.web","false"},{"builder.evaluation","false"},{"builder.kimi_ceiling","false"},{"builder.max_calls","32"},{"builder.model",""},{"builder.model_choice",""},{"builder.small_model",""},{"builder.questions","A question"}};
    BuilderTask task;task.id="builder-1";task.status="running";task.label="Saved running";task.request_json=json::stringify(json::Value::Object{{"operation","scribble"},{"root",project.string()},{"chat_path","chat.chat.md"},{"scribble",json::Value::Object{{"ai_enabled",false}}}});chat.state.builder.tasks.push_back(task);workspace.save_state(chat);
    {
        Session session(project,"chat.chat.md",config,true,worker);require(session.text("builder.task.status").find("interrupted")!=std::string::npos&&!std::filesystem::exists(fixture.root/"launched"),"Loaded running task stayed running or launched automatically");session.escape();session.activate("tab.builder.Setup");session.activate("builder.run");wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"collision-free saved task ID");
        const auto saved=Workspace(project).open_chat("chat.chat.md").state.builder;require(saved.tasks.size()==2&&saved.tasks[0].id=="builder-1"&&saved.tasks[1].id=="builder-2"&&saved.next_task_id==3,"Stale ID counter produced duplicate task IDs");
    }
    chat=workspace.open_chat("chat.chat.md");chat.state.builder.tab="Tasks";chat.state.builder.selected_task="builder-1";chat.state.builder.tasks[0].request_json=json::stringify(json::Value::Object{{"operation","scribble"},{"root",project.string()},{"chat_path","another.chat.md"},{"scribble",json::Value::Object{{"ai_enabled",false}}}});workspace.save_state(chat);const auto previous_launch=read(fixture.root/"launched");
    {
        Session session(project,"chat.chat.md",config,true,worker);
#if defined(_WIN32)
        require(!widget(session.view(),"builder.task.resume").state.enabled&&widget(session.view(),"builder.task.resume").state.help.find("Windows")!=std::string::npos,"Windows offered unsupported durable Resume");
#else
        session.activate("builder.task.resume");session.error("another root or chat");require(read(fixture.root/"launched")==previous_launch,"Moved/copied task launched against another checkpoint owner");
#endif
    }
    chat=workspace.open_chat("chat.chat.md");chat.state.builder.tab="Setup";chat.state.builder.next_task_id=9007199254740991ULL;task.id="builder-9007199254740991";task.status="completed";task.request_json="{}";chat.state.builder.tasks.push_back(task);workspace.save_state(chat);
    {
        Session session(project,"chat.chat.md",config,true,worker);session.activate("builder.run");session.error("ID limit");require(read(fixture.root/"launched")==previous_launch&&Workspace(project).open_chat("chat.chat.md").state.builder.tasks.size()==3,"ID exhaustion launched work or corrupted task records");
    }
    // A changed state sidecar must block launch before the trusted worker runs.
    std::filesystem::remove(fixture.root/"launched");write(project/"conflict.chat.md","# Conflicting task\n");
    {
        Session session(project,"conflict.chat.md",config,true,worker);session.edit("wb.composer","Preserve conflict draft.");session.activate("selector.builder");const auto path=project/Workspace::state_path("conflict.chat.md");const auto foreign=read(path)+"\n";write(path,foreign);session.edit("builder.output","conflicting-output");session.activate("builder.run");session.error("changed");
        require(!std::filesystem::exists(fixture.root/"launched")&&!widget(session.view(),"builder.task.pause").state.enabled&&session.text("builder.task.status").find("ready")!=std::string::npos&&read(path)==foreign,"Failed prelaunch save started a worker, forged running status or overwrote foreign state");
    }
#endif
}

void builder_metadata_and_edit_limits_do_not_poison_saves() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;const auto project=fixture.root/"project",config=fixture.root/"config";std::filesystem::create_directory(project);write(project/"chat.chat.md","# Safe metadata\n");
    const auto worker=fixture.root/"metadata builder worker.py";write(worker,R"PY(import json, sys
with open(sys.argv[2], encoding='utf-8') as stream:request=json.load(stream)
output=request['output_dir']
result={'ok':True,'text':'Safe retained result.'}
if output=='wrong-type':result['usage']=[]
elif output=='forbidden-key':result['usage']={'authorization':'synthetic-private-fixture'}
elif output=='large-result':result['text']='bounded result '*20000
elif output=='nul-text':result['text']='safe prefix\0unsafe suffix'
elif output=='nul-error':result={'ok':False,'error':'synthetic error\0suffix'}
print(json.dumps(result))
)PY");
    Session session(project,"chat.chat.md",config,true,worker);session.activate("selector.builder");
    require(widget(session.view(),"builder.paths").spec.text_policy.max_bytes==64*1024&&widget(session.view(),"builder.label").spec.text_policy.max_bytes==256,"Builder inputs exceed durable setup/request limits");
    const auto previous=session.text("builder.paths");const auto key=widget(session.view(),"builder.paths").spec.key;require(session.adapter.send(gui::WidgetEvent{key,gui::EditText{std::string(64*1024+1,'x'),previous}})==gui::Delivery::ignored&&session.text("builder.paths")==previous,"Oversized multiline paste poisoned builder setup");
    std::string too_many_paths;for(int i=0;i<129;++i)too_many_paths+="source-"+std::to_string(i)+"\n";session.edit("builder.paths",too_many_paths);session.activate("builder.run");session.error("entry limit");require(Workspace(project).open_chat("chat.chat.md").state.builder.tasks.empty()&&find(session.view(),"builder.paths"),"Invalid path count retained an unsaveable immutable task");session.edit("builder.paths",".");
    for(const auto* output:{"wrong-type","forbidden-key","large-result","nul-text","nul-error"}){session.edit("builder.output",output);session.activate("builder.run");wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"bounded safe builder metadata");const bool nul=std::string_view(output).starts_with("nul-");if(nul)session.error("invalid JSON response");else session.success("safe result metadata");const auto state=Workspace(project).open_chat("chat.chat.md").state;const auto& task=state.builder.tasks.back();const auto result=json::parse(task.result_json);require((nul?task.status=="failed"&&task.error.find('\0')==std::string::npos:task.status=="completed"&&result.find("omitted")&&result.find("omitted")->boolean())&&task.result_json.find("synthetic-private-fixture")==std::string::npos,"Malformed/forbidden/large metadata poisoned or leaked into the saved result");session.activate("builder.exit");session.edit("wb.composer",std::string("Still save after ")+output);session.autosave();session.success("composer save after omitted builder metadata");require(Workspace(project).open_chat("chat.chat.md").state.draft==std::string("Still save after ")+output,"Result metadata blocked later chat saves");session.activate("selector.builder");session.activate("tab.builder.Setup");}
#endif
}

void builder_live_edits_preserve_completion_capacity() {
#if defined(__linux__) || defined(_WIN32)
    Temporary fixture;const auto project=fixture.root/"project",config=fixture.root/"config";std::filesystem::create_directory(project);write(project/"chat.chat.md","# Live setup capacity\n");
    Workspace workspace(project);auto chat=workspace.open_chat("chat.chat.md");chat.state.builder.active=true;chat.state.builder.fields={{"builder.paths","."},{"builder.kind","scribbles"},{"builder.output","live-output"},{"builder.default_output","live-output"},{"builder.label","Live setup"},{"builder.ai","false"},{"builder.web","false"},{"builder.evaluation","true"},{"builder.kimi_ceiling","false"},{"builder.max_calls","32"},{"builder.model",""},{"builder.model_choice",""},{"builder.small_model","custom/model"},{"builder.questions","Original question"}};
    json::Value::Array paths;for(int i=0;i<14;++i)paths.emplace_back(std::string(3450,'p'));const auto snapshot=json::stringify(json::Value::Object{{"operation","scribble"},{"root",project.string()},{"chat_path","chat.chat.md"},{"input_paths",paths}});
    for(int i=1;i<=14;++i){BuilderTask task;task.id="retained-"+std::to_string(i);task.status="completed";task.request_json=snapshot;chat.state.builder.tasks.push_back(task);}workspace.save_state(chat);
    const auto worker=fixture.root/"held capacity worker.py";write(worker,R"PY(import json, pathlib, sys, time
with open(sys.argv[2], encoding='utf-8') as stream:request=json.load(stream)
base=pathlib.Path(__file__).parent
(base/'launched').write_text('started',encoding='utf-8')
while not (base/'finish').exists():time.sleep(.01)
print(json.dumps({'ok':True,'text':'Completion still fits.','sources':[]}))
)PY");
    Session session(project,"chat.chat.md",config,true,worker);session.activate("builder.run");wait_for(session,[&]{return std::filesystem::exists(fixture.root/"launched");},"held aggregate capacity task");session.activate("tab.builder.Setup");session.edit("builder.paths",std::string(64*1024,'"'));session.edit("builder.questions",std::string(64*1024,'"'));session.error("reserved space");require(session.text("builder.questions")=="Original question","Rejected aggregate edit discarded previously valid setup");write(fixture.root/"finish","done\n");session.activate("tab.builder.Tasks");wait_for(session,[&]{return !widget(session.view(),"builder.task.pause").state.enabled;},"completion after bounded live edit");session.success("completion after bounded live edit");require(Workspace(project).open_chat("chat.chat.md").state.builder.tasks.back().status=="completed","Live setup exhausted completion capacity and blocked persistence");
#endif
}

void bounded_settings_and_builder() {
    Temporary fixture;
    write(fixture.root / "chat.chat.md", "# Settings fixture\n");
    write(fixture.root / "other.chat.md", "# Other settings fixture\n");
    write(fixture.root / "source.txt", "Local builder input.\n");
    Session session(fixture.root, "chat.chat.md");
    require(session.text("selector.context_kib") == "256", "Selector context budget has the wrong default");
    Workspace saved(fixture.root);
    for (const auto* valid : {"1", "16384"}) {
        session.edit("selector.context_kib", valid);
        session.activate("selector.save");
        session.success("bounded selector save");
        require(saved.open_chat("chat.chat.md").state.selector.context_max_kib == std::stoi(valid),
                "A valid context budget was not persisted");
    }
    const auto state_path = fixture.root / Workspace::state_path("chat.chat.md");
    for (const auto* invalid : {"0", "16385"}) {
        const auto before = read(state_path);
        session.edit("selector.context_kib", invalid);
        session.activate("selector.save");
        session.error("between 1 and 16384");
        require(session.text("selector.context_kib") == invalid && read(state_path) == before,
                "An invalid context budget changed saved state or discarded its editable input");
        session.chat("other.chat.md");
        session.chat("chat.chat.md");
        require(session.text("selector.context_kib") == "16384",
                "An invalid context budget changed the active chat's selector state");
    }
    session.activate("tab.left.Files");
    session.select("wb.files", "source.txt");
    session.activate("wb.file.actions");
    session.activate("wb.file.scribble");
    session.success("open local builder workspace");
    require(widget(session.view(), "builder.ai").state.selected == "false" &&
            !find(session.view(), "builder.model") && !find(session.view(), "builder.small_model") &&
            !find(session.view(), "builder.kimi_ceiling"),
            "Builder selected AI implicitly or showed irrelevant local-mode model controls");
    session.choose("builder.ai", "true");
    session.check("builder.evaluation", true);
    require(session.text("builder.max_calls") == "32" && session.text("builder.model").empty() &&
            session.text("builder.small_model").empty() && !find(session.view(), "builder.model_choice"),
            "Builder selected a model implicitly, showed hidden Tutorial examples or omitted its call setting");
    const auto unchanged = inventory(fixture.root);
    session.activate("builder.run");
    session.error("model");
    require(!session.view().modal_root && find(session.view(),"builder.exit") && session.text("builder.model").empty() &&
            session.text("builder.small_model").empty() && inventory(fixture.root) == unchanged,
            "Builder missing-model preflight closed the dialog or started a task");
    session.edit("builder.model", "nvidia/nemotron-3-ultra-550b-a55b");
    for (const auto* invalid : {"0", "4097"}) {
        session.edit("builder.max_calls", invalid);
        session.activate("builder.run");
        session.error("between 1 and 4096");
        require(!session.view().modal_root && find(session.view(),"builder.exit") && session.text("builder.max_calls") == invalid,
                "Invalid builder calls started a task or discarded the dialog input");
    }
    session.edit("builder.max_calls", "32");
    session.edit("builder.model", "moonshotai/kimi-k3");
    require(widget(session.view(), "builder.kimi_ceiling").state.selected == "false",
            "Kimi builder did not require an explicit higher price ceiling");
    session.activate("builder.run");
    session.error("explicit higher price ceiling");
    require(!session.view().modal_root && find(session.view(),"builder.exit") &&
            widget(session.view(), "builder.kimi_ceiling").state.selected == "false",
            "Kimi validation started a task or enabled the ceiling implicitly");
    session.activate("builder.exit");
    session.application->tick();
    session.presented("builder validation checkpoint");
    session.activate("tab.left.Running Tasks");
    require(widget(session.view(), "wb.tasks").state.records.empty() && saved.open_chat("chat.chat.md").state.builder.tasks.empty() &&
            read(fixture.root/"chat.chat.md")=="# Settings fixture\n" && read(fixture.root/"source.txt")=="Local builder input.\n",
            "Rejected builder settings launched a job or changed source/chat files");
}

void non_utf8_file_names() {
#if !defined(_WIN32)
    Temporary fixture;
    write(fixture.root / "chat.chat.md", "# Filename fixture\n");
    const std::string raw_name = std::string("odd-") + static_cast<char>(0xff) + ".txt";
    const std::string contents = "Text stored under the exact raw-byte filename.\n";
    write(fixture.root / std::filesystem::path(raw_name), contents);
    Session session(fixture.root, "chat.chat.md");
    session.activate("tab.left.Files");
    session.success("raw-byte file browser presentation");
    const auto& records = widget(session.view(), "wb.files").state.records;
    const auto escaped = std::find_if(records.begin(), records.end(), [](const auto& row) {
        return row.accessible_text.find("odd-\\xff.txt") != std::string::npos;
    });
    require(escaped != records.end(), "File browser omitted the escaped raw-byte filename");
    require(gui::valid_utf8(escaped->id) && gui::valid_utf8(escaped->accessible_text),
            "Raw-byte file record published invalid UTF-8 identity or accessible text");
    const auto id = escaped->id;
    session.select("wb.files", id);
    session.activate("wb.file.open");
    session.success("open raw-byte filename");
    require(session.text("file.text") == contents &&
            session.text("modal.title").find("odd-\\xff.txt") != std::string::npos,
            "Reversible file record identity did not open the exact raw-byte filename");
    session.activate("file.close");
    require(!session.view().modal_root && read(fixture.root / std::filesystem::path(raw_name)) == contents,
            "Opening a raw-byte filename changed its contents or failed to close");
#endif
}

void file_buffers(const std::filesystem::path& captures) {
    Temporary fixture;
    write(fixture.root / "chat.chat.md", "# File fixture\n");
    write(fixture.root / "src/main.cpp", "int main() { return 0; }\n");
    write(fixture.root / "src/nested/data.txt", "original data\n");
    Session session(fixture.root, "chat.chat.md");
    session.activate("tab.left.Files");
    require(record(widget(session.view(), "wb.files"), "src") &&
            !record(widget(session.view(), "wb.files"), "src/main.cpp"),
            "Folder tree eagerly expanded a directory");
    session.activate_record("wb.files", "src");
    require(record(widget(session.view(), "wb.files"), "src/main.cpp"),
            "Folder activation did not expand its children");
    session.activate_record("wb.files", "src");
    require(!record(widget(session.view(), "wb.files"), "src/main.cpp"),
            "Folder activation did not collapse its children");
    session.activate_record("wb.files", "src");
    session.select("wb.files", "src");
    session.activate("wb.file.open");
    require(session.text("wb.path") == "src" &&
            record(widget(session.view(), "wb.files"), "src/main.cpp"),
            "Directory Open did not navigate the browser");
    session.activate("wb.file.actions");
    require(session.view().modal_root.has_value(), "File actions did not open a modal");
    session.activate("modal.cancel");
    session.activate_record("wb.files", "src/main.cpp");
    require(session.view().modal_root.has_value() &&
            session.text("file.text") == "int main() { return 0; }\n",
            "File activation did not open the file buffer");
    const std::string changed = "int main() { return 7; }\n";
    require(!find(session.view(), "file.undo") && !find(session.view(), "file.redo"),
            "File editor retained visible Undo/Redo toolbar buttons");
    session.edit("file.text", changed);
    session.shortcut("file.text", gui::ShortcutKey::z);
    require(session.text("file.text") == "int main() { return 0; }\n", "File Undo lost original text");
    session.shortcut("file.text", gui::ShortcutKey::y);
    require(session.text("file.text") == changed, "File Redo did not restore the edit");
    session.activate("file.close");
    session.error("Save");
    require(session.view().modal_root && session.text("file.text") == changed,
            "Closing a dirty file discarded its buffer");
    session.activate("file.save");
    session.success("checked file save");
    require(read(fixture.root / "src/main.cpp") == changed, "File Save did not publish the buffer");
    session.activate("file.close");
    require(!session.view().modal_root, "Saved file did not close");
    session.activate_record("wb.files", "src/main.cpp");
    session.edit("file.text", "local recovery text\n");
    write(fixture.root / "src/main.cpp", "external text\n");
    session.activate("file.save");
    session.error("changed");
    require(session.text("file.text") == "local recovery text\n" &&
            read(fixture.root / "src/main.cpp") == "external text\n",
            "File conflict lost the local buffer or overwrote external bytes");
    capture(session.view(), captures, "workbench-file-conflict");
    session.activate("file.discard");
    session.success("discard conflicted file buffer");
    require(!session.view().modal_root && read(fixture.root / "src/main.cpp") == "external text\n",
            "Discard changed external bytes or left the file modal open");
    session.activate("wb.back");
    require(session.text("wb.path") == ".", "Browser Back did not restore the root directory");
}

void chat_suffix_escape_and_theme(const std::filesystem::path& captures) {
    Temporary fixture;
    write(fixture.root/"session.chat.md","# Conversation\n");
    write(fixture.root/"another.CHAT.MD","# Case-insensitive conversation\n");
    write(fixture.root/"README.md","# Ordinary project documentation\n");
    write(fixture.root/"notes.markdown","Ordinary notes\n");
    Session session(fixture.root,"session.chat.md");
    const auto& chats=widget(session.view(),"wb.chats");
    require(record(chats,"session.chat.md")&&record(chats,"another.CHAT.MD")&&
            !record(chats,"README.md")&&!record(chats,"notes.markdown"),
            "Chat discovery included ordinary Markdown or lost .chat.md files");
    const auto palette=session.view().palette;
    require(palette.background.red<64&&palette.surface.red<64&&palette.text.red>200,
            "Workbench did not default to a readable dark palette");
    const auto before=inventory(fixture.root);session.escape();
    require(inventory(fixture.root)==before&&!session.view().modal_root,
            "Escape outside a dialog changed workspace files or opened a dialog");
    session.activate("tab.left.Files");session.select("wb.files","README.md");
    const auto bounds=widget(session.view(),"wb.files").state.bounds;
    session.pointer("wb.files",{bounds.x+10,bounds.y+bounds.height-10},gui::PointerKind::context_menu);
    require(!widget(session.view(),"actions.delete").state.enabled&&!widget(session.view(),"actions.rename").state.enabled,
            "Blank-space context menu retained an unrelated selected file");
    session.escape();session.select("wb.files","README.md");session.activate("wb.file.open");
    require(session.view().modal_root&&session.text("file.text")=="# Ordinary project documentation\n",
            "Ordinary Markdown did not open in the file editor");
    require(session.view().palette.background==palette.background&&session.view().palette.text==palette.text,
            "File dialog lost the shared dark palette");
    session.edit("file.text","Unsaved documentation\n");session.escape();session.error("Save");
    require(session.view().modal_root&&session.text("file.text")=="Unsaved documentation\n",
            "Escape discarded a dirty file dialog");
    session.activate("file.discard");session.select("wb.files","another.CHAT.MD");session.activate("wb.file.open");
    require(!session.view().modal_root&&session.text("wb.chat.text")=="# Case-insensitive conversation\n",
            "Opening .chat.md from Files did not select the chat session");
    session.activate("wb.new");require(session.text("prompt.value").ends_with(".chat.md"),"New chat default lacks .chat.md suffix");
    session.escape();require(!session.view().modal_root,"Escape did not cancel a path dialog");
    capture(session.view(),captures,"workbench-dark-files");
}

void common_file_operations(const std::filesystem::path& captures) {
    Temporary fixture;
    write(fixture.root/"session.chat.md","# Original conversation\n");
    write(fixture.root/"nonempty/keep.txt","Preserve this file\n");
    Session session(fixture.root,"session.chat.md");session.activate("tab.left.Files");
    const auto menu=[&](std::string path){session.select("wb.files",std::move(path));session.activate("wb.file.actions");};
    session.activate("wb.file.actions");session.activate("actions.create-file");session.edit("prompt.value","new.txt");session.activate("prompt.accept");session.success("create file");
    require(std::filesystem::exists(fixture.root/"new.txt")&&read(fixture.root/"new.txt").empty(),"Create file did not create an empty ordinary file");
    session.activate("wb.file.actions");session.activate("actions.create-directory");session.edit("prompt.value","empty");session.activate("prompt.accept");session.success("create folder");
    require(std::filesystem::is_directory(fixture.root/"empty"),"Create folder did not create an empty directory");
    menu("new.txt");session.activate("actions.rename");session.edit("prompt.value","renamed.txt");session.activate("prompt.accept");session.success("rename file");
    require(!std::filesystem::exists(fixture.root/"new.txt")&&std::filesystem::exists(fixture.root/"renamed.txt"),"Rename file did not move the selected file");
    write(fixture.root/"renamed.txt","Bytes copied through the file browser.\n");
    menu("renamed.txt");session.activate("actions.copy");session.edit("prompt.value","copied.txt");session.activate("prompt.accept");session.success("copy ordinary file");
    require(read(fixture.root/"renamed.txt")=="Bytes copied through the file browser.\n"&&
            read(fixture.root/"copied.txt")=="Bytes copied through the file browser.\n"&&
            record(widget(session.view(),"wb.files"),"copied.txt"),
            "File-browser Copy changed its source or failed to create and list the destination");
    menu("renamed.txt");session.activate("actions.copy");session.edit("prompt.value","copied.txt");session.activate("prompt.accept");session.error("exist");
    require(session.view().modal_root&&read(fixture.root/"copied.txt")=="Bytes copied through the file browser.\n",
            "Copy overwrote an existing file or discarded its recoverable prompt");
    session.escape();
    menu("renamed.txt");session.activate("actions.delete");session.escape();
    require(std::filesystem::exists(fixture.root/"renamed.txt"),"Canceling delete removed a file");
    menu("renamed.txt");session.activate("actions.delete");session.activate("delete.accept");session.success("delete file");
    require(!std::filesystem::exists(fixture.root/"renamed.txt"),"Confirmed delete retained the ordinary file");
    menu("empty");session.activate("actions.delete");session.activate("delete.accept");session.success("delete empty folder");
    require(!std::filesystem::exists(fixture.root/"empty"),"Empty folder deletion did not use rmdir semantics");
    menu("nonempty");session.activate("actions.delete");session.activate("delete.accept");session.error("empty");
    require(read(fixture.root/"nonempty/keep.txt")=="Preserve this file\n"&&session.view().modal_root,
            "Deleting a non-empty folder removed content or hid its refusal");
    session.escape();
    session.check("wb.developer",true);session.edit("wb.chat.text","# Pending conversation edit\n");
    require(read(fixture.root/"session.chat.md")=="# Original conversation\n","Rename fixture unexpectedly saved before its file action");
    menu("session.chat.md");session.activate("actions.rename");session.edit("prompt.value","renamed.chat.md");session.activate("prompt.accept");session.success("rename autosaves current chat");
    require(session.text("wb.chat.text")=="# Pending conversation edit\n"&&
            read(fixture.root/"renamed.chat.md")=="# Pending conversation edit\n"&&
            !std::filesystem::exists(fixture.root/"session.chat.md")&&
            std::filesystem::exists(fixture.root/Workspace::state_path("renamed.chat.md")),
            "Renaming a pending current chat failed to save its text and restore its settings");
    session.edit("wb.chat.text","# Pending deletion\n");
    menu("renamed.chat.md");session.activate("actions.delete");session.activate("delete.accept");session.success("delete edited current chat");
    require(!std::filesystem::exists(fixture.root/"renamed.chat.md")&&
            !std::filesystem::exists(fixture.root/Workspace::state_path("renamed.chat.md"))&&find(session.view(),"wb.empty"),
            "Deleting a saved current chat left an active buffer or orphan settings");
    session.application->handle(gui::CloseEvent{});
    require(session.adapter.closed()&&!std::filesystem::exists(fixture.root/"renamed.chat.md")&&
            !std::filesystem::exists(fixture.root/Workspace::state_path("renamed.chat.md")),
            "Closing resurrected a deleted chat or its settings");
    (void)captures;
}

void terminal_stop_allows_folder_mutation() {
#if defined(__linux__)
    Temporary fixture;write(fixture.root/"session.chat.md","# Terminal folder fixture\n");std::filesystem::create_directory(fixture.root/"folder");
    Session session(fixture.root,"session.chat.md");session.activate("tab.left.Files");session.select("wb.files","folder");session.activate("wb.file.actions");session.activate("wb.file.cd");session.success("start local terminal");
    require(widget(session.view(),"wb.terminal.stop").state.enabled,"Terminal Stop was unavailable for the running shell");
    session.select("wb.files","folder");session.activate("wb.file.actions");session.activate("actions.rename");session.edit("prompt.value","moved");session.activate("prompt.accept");session.error("terminals");
    require(std::filesystem::is_directory(fixture.root/"folder")&&!std::filesystem::exists(fixture.root/"moved"),"A live terminal's directory was renamed");
    session.escape();session.activate("tab.left.Running Tasks");
    const auto terminal=task_id(session,"session.chat.md","Bash terminal");
    task_menu(session,terminal);
    require(widget(session.view(),"task.cancel").state.label=="Stop terminal",
            "Terminal context actions did not distinguish Stop from job cancellation");
    session.activate("task.cancel");session.success("stop selected local terminal");
    require(widget(session.view(),"wb.tasks").state.records.empty()&&
            !widget(session.view(),"wb.terminal.stop").state.enabled,
            "Stopping a terminal task left its process or task row active");
    session.activate("tab.left.Files");session.select("wb.files","folder");
    session.activate("wb.file.actions");session.activate("actions.rename");session.edit("prompt.value","moved");session.activate("prompt.accept");session.success("rename after terminal stop");
    require(std::filesystem::is_directory(fixture.root/"moved")&&!std::filesystem::exists(fixture.root/"folder")&&
            widget(session.view(),"wb.terminal.cwd").state.text.find("moved")!=std::string::npos,
            "Stopped terminal did not permit mutation or its saved cwd stayed stale");
#endif
}
} // namespace

int main(int argc, char** argv) {
    try {
        std::filesystem::path captures;
        if (argc == 3 && std::string_view(argv[1]) == "--capture") captures = argv[2];
        else require(argc == 1, "Usage: application_test [--capture DIRECTORY]");
        initial_and_tabs(captures);
        normal_transcript_is_passive_markdown();
        transcript_scroll_positions_are_owned_by_chat_and_split_source();
        following_survives_settling_ranges_and_respects_scroll_up();
        following_uses_current_layout_clamps_and_preserves_immediate_input();
        global_modes_autosave_and_undo();
        missing_model_does_not_consume_a_message();
        composer_actions_share_one_visible_row();
        image_drafts_are_explicit_snapshots_and_retry_the_original_images();
        retry_uses_the_previous_submission_and_preserves_the_draft();
        streaming_progress_is_visible_saved_and_isolated();
        idle_boundary_is_quiet_persistent_and_source_scoped();
        submitted_composer_is_the_only_agent_plan();
        task_context_cancels_its_exact_owner();
        chats_and_conflicts(captures);
        independent_chat_state(captures);
        remembered_ai_defaults();
        interactive_research_scope();
        tutorial_snippets_are_explicit();
        optional_ai_parameters_and_provider_controls();
        configured_models_are_application_wide();
        model_catalog_refresh_uses_an_offline_worker();
        ai_keys_are_private_and_explicit();
        pseudocode_edits(captures);
        flow_properties_follow_block_kind();
        flow_canvas_transform_and_ownership();
        flow_canvas_gestures();
        flow_canvas_cancellation();
        flow_canvas_wheel_zoom_preserves_the_draft();
        latest_pseudocode_fence();
        terminal_drafts_without_shells();
        pseudocode_without_final_newline();
        transcription_validation(captures);
        sidebar_visibility_retains_controls_and_is_global();
        hidden_sidebar_reveals_ai_and_preserves_preference_conflicts();
        code_is_an_explicit_chat_option();
        builder_discovery_and_modes_are_explicit();
        builder_typing_retains_native_control_identity();
        persistent_builder_workspace_and_interrupted_tasks();
        builder_restart_ownership_ids_and_checked_launch();
        builder_metadata_and_edit_limits_do_not_poison_saves();
        builder_live_edits_preserve_completion_capacity();
        bounded_settings_and_builder();
        non_utf8_file_names();
        file_buffers(captures);
        chat_suffix_escape_and_theme(captures);
        common_file_operations(captures);
        terminal_stop_allows_folder_mutation();
        std::cout << "application: offline panes, checked autosave/recovery, global modes, scoped undo/send, model preflight, retained Retry, composer-only plans, targeted tasks, flow gestures, snippets, AI catalog filtering, private keys and files passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
