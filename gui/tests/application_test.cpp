#include "shared/application.hpp"
#include <gui/framebuffer.hpp>
#include <gui/memory_adapter.hpp>
#include <gui/terminal.hpp>

#include <iostream>
#include <type_traits>

namespace {
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

const gui::Widget& widget(const gui::Snapshot& view, std::string id) {
    const auto* found = gui::find_widget(view, {std::move(id), 1});
    if (!found) throw std::runtime_error("Missing fixture control");
    return *found;
}

template<class Adapter> void edit(Adapter& adapter, const std::string& text) {
    check(adapter.focus(gui::WidgetKey{"entries.editor", 1}), "Editor cannot receive focus");
    adapter.key(gui::Key::select_all);
    if constexpr (std::is_same_v<Adapter, gui::TerminalAdapter>)
        adapter.input("\x1b[200~" + text + "\x1b[201~");
    else adapter.text(text);
}

template<class Adapter> void activate(Adapter& adapter, std::string id) {
    const gui::WidgetKey key{std::move(id), 1};
    if constexpr (std::is_same_v<Adapter, gui::TerminalAdapter>) {
        check(adapter.focus(key), "Button cannot receive focus");
        adapter.input("\r");
    } else {
        const auto area = adapter.resolved_availability(key).bounds;
        adapter.pointer({gui::PointerKind::click,
            {area.x + area.width / 2, area.y + area.height / 2}});
    }
}

template<class Adapter> gui::Snapshot scenario() {
    foundation::ui::Application* current = nullptr;
    Adapter adapter([&](const gui::Event& event) { if (current) current->handle(event); });
    foundation::ui::Application app(adapter);
    current = &app;
    check(!widget(app.view(), "entries.add").state.enabled, "Empty entry accepted");
    edit(adapter, "\xc3\xa9");
    activate(adapter, "entries.add");
    check(widget(app.view(), "entries.list").state.records.empty(), "Invalid core input changed collection");
    check(widget(app.view(), "entries.editor").state.text == "\xc3\xa9", "Rejected input was lost");
    check(widget(app.view(), "entries.status").state.text == "text must contain printable ASCII only",
          "Core validation error did not reach the shared status label");
    check(widget(app.view(), "entries.status").state.font.tone == gui::Tone::error, "Validation error is not marked");
    edit(adapter, std::string(foundation::Store::max_text_bytes + 1, 'x'));
    check(widget(app.view(), "entries.editor").state.text == "\xc3\xa9", "Oversized native replacement changed editor");
    edit(adapter, "First entry");
    activate(adapter, "entries.add");
    check(widget(app.view(), "entries.list").state.records.size() == 1, "Entry missing");
    check(widget(app.view(), "entries.editor").state.text.empty(), "Editor did not clear");
    check(widget(app.view(), "entries.status").state.text == "Entry added", "Validation did not recover");
    edit(adapter, "Second entry");
    // A stale queued full replacement must not overwrite the newer value.
    const auto before_stale_edit = app.input_epoch();
    app.handle(gui::WidgetEvent{{"entries.editor", 1}, gui::EditText{"Obsolete", "First entry"}});
    check(widget(app.view(), "entries.editor").state.text == "Second entry", "Stale edit accepted");
    check(app.input_epoch() == before_stale_edit, "Stale edit changed input meaning");
    activate(adapter, "entries.add");
    // This adds a real control, meaning and layout solely in shared code.
    const auto before_extension = app.input_epoch();
    app.enable_remove_feature();
    check(app.input_epoch() == before_extension + 1, "Feature extension retained old input meaning");
    app.enable_remove_feature();
    check(app.input_epoch() == before_extension + 1, "Repeated feature extension changed input meaning");
    adapter.focus(gui::WidgetKey{"entries.list", 1});
    adapter.key(gui::Key::down);
    check(widget(app.view(), "entries.remove").state.enabled, "New feature not enabled");
    const auto remove_key = widget(app.view(), "entries.remove").spec.key;
    const auto remove_label = widget(app.view(), "entries.remove").state.label;
    const auto before_selection = app.input_epoch();
    const auto second_id = widget(app.view(), "entries.list").state.records.back().id;
    app.handle(gui::WidgetEvent{{"entries.list", 1}, gui::SelectRecord{second_id}});
    check(app.input_epoch() == before_selection + 1, "Changed Remove operand retained old input meaning");
    check(widget(app.view(), "entries.remove").spec.key == remove_key &&
          widget(app.view(), "entries.remove").state.label == remove_label &&
          widget(app.view(), "entries.remove").state.enabled,
          "Selection fixture changed the Remove control identity");
    app.handle(gui::WidgetEvent{{"entries.list", 1}, gui::SelectRecord{second_id}});
    check(app.input_epoch() == before_selection + 1, "Duplicate record selection changed input meaning");
    app.handle(gui::WidgetEvent{{"entries.list", 1},
        gui::SelectRecord{widget(app.view(), "entries.list").state.records.front().id}});
    activate(adapter, "entries.remove");
    check(widget(app.view(), "entries.list").state.records.size() == 1, "New feature failed");
    check(widget(app.view(), "entries.list").state.records.front().accessible_text == "Second entry",
          "New feature removed the wrong stable record");
    const auto before_stale_generation = app.input_epoch();
    app.handle(gui::WidgetEvent{{"entries.remove", 0}, gui::Activate{}});
    check(widget(app.view(), "entries.list").state.records.size() == 1, "Stale generation accepted");
    check(app.input_epoch() == before_stale_generation, "Stale widget generation changed input meaning");

    check(adapter.open_popup({"entries.options", 1}), "Menu did not open");
    const auto before_service_intent = app.input_epoch();
    adapter.key(gui::Key::down);
    adapter.key(gui::Key::enter);
    check(app.input_epoch() == before_service_intent + 1, "Service intent retained old input meaning");
    auto request = app.next_service();
    check(request.has_value(), "Generic service request missing");
    check(app.input_epoch() == before_service_intent + 2, "Service begin retained old input meaning");
    const auto before_service_completion = app.input_epoch();
    check(!app.next_service() && app.input_epoch() == before_service_completion,
          "Active service retrieval changed input meaning");
    check(!app.complete_service({request->id + 1, gui::ServiceStatus::success, "Stale", {}}) &&
          app.input_epoch() == before_service_completion, "Stale service completion changed input meaning");
    check(app.complete_service({request->id, gui::ServiceStatus::success, "Updated heading", {}}),
          "Service completion rejected");
    check(app.input_epoch() == before_service_completion + 1, "Service completion retained old input meaning");
    check(!app.complete_service({request->id, gui::ServiceStatus::success, "Repeated", {}}),
          "Service completion repeated");
    check(app.input_epoch() == before_service_completion + 1, "Repeated service completion changed input meaning");
    check(widget(app.view(), "entries.heading").state.text == "Updated heading", "Heading not updated");

    const auto before_resize = app.input_epoch();
    adapter.resize({800, 640}, 1.25);
    check(app.view().display_scale == 1.25, "Resize scale lost");
    check(app.input_epoch() == before_resize, "Layout-only resize changed semantic input meaning");
    if constexpr (std::is_same_v<Adapter, gui::TerminalAdapter>) {
        check(!adapter.render().empty(), "Terminal produced no cells");
    } else {
        const auto retained = adapter.frame();
        check(retained.width == 1000 && retained.height == 800 && retained.pixels,
              "Framebuffer failed to render scaled geometry");
        adapter.resize({640, 480});
        check(retained.pixels->size() == 1000u * 800u * 3u, "Frame ownership was not retained");
        adapter.resize({800, 640}, 1.25);
    }
    const auto result = app.view();
    // Small and zero-size views preserve state and recover through shared layout.
    adapter.resize({80, 64});
    adapter.resize({0, 0});
    adapter.resize({800, 640}, 1.25);
    const auto before_close = app.input_epoch();
    app.handle(gui::CloseEvent{});
    app.handle(gui::WidgetEvent{{"entries.add", 1}, gui::Activate{}});
    check(adapter.closed() && !app.presentation_pending(), "Close did not finish");
    check(app.input_epoch() == before_close + 1, "Close retained old input meaning");
    app.shutdown();
    check(app.input_epoch() == before_close + 1, "Repeated shutdown changed input meaning");
    return result;
}

class FailingAdapter final : public gui::RetainedAdapter {
public:
    FailingAdapter() : gui::RetainedAdapter({}, [](const gui::TextMeasureRequest& request) {
        return gui::Size{request.available_width, 16};
    }) {}
    bool fail = false;
    bool fail_measurement = false;
    gui::Size measure_text(const gui::TextMeasureRequest& request) const override {
        if (fail_measurement) throw std::runtime_error("Injected measurement failure");
        return gui::RetainedAdapter::measure_text(request);
    }
    void present(gui::Snapshot view) override {
        if (fail) throw std::runtime_error("Injected presentation failure");
        gui::RetainedAdapter::present(std::move(view));
    }
};

void recovery() {
    FailingAdapter adapter;
    foundation::ui::Application app(adapter);
    const auto initial_epoch = app.input_epoch();
    adapter.fail = true;
    try {
        app.handle(gui::WidgetEvent{{"entries.editor", 1}, gui::EditText{"Accepted value", ""}});
        throw std::logic_error("Expected presentation failure");
    } catch (const std::runtime_error&) {}
    check(app.presentation_pending(), "Presentation debt disappeared");
    check(widget(app.view(), "entries.editor").state.text == "Accepted value", "Accepted edit rolled back");
    check(app.input_epoch() == initial_epoch + 1, "Failed presentation lost accepted edit epoch");
    app.handle(gui::WidgetEvent{{"entries.editor", 1}, gui::EditText{"Stale", ""}});
    check(app.input_epoch() == initial_epoch + 1, "Stale edit during presentation debt changed epoch");
    app.handle(gui::WidgetEvent{{"entries.editor", 1}, gui::EditText{"Accepted value", "Accepted value"}});
    check(app.input_epoch() == initial_epoch + 1, "Duplicate edit during presentation debt changed epoch");
    adapter.fail = false;
    app.retry_presentation();
    check(!app.presentation_pending(), "Presentation did not recover");
    check(widget(adapter.snapshot(), "entries.editor").state.text == "Accepted value", "Retry lost edit");
    check(app.input_epoch() == initial_epoch + 1, "Painting retry changed accepted edit epoch");
    adapter.fail = true;
    try {
        app.handle(gui::WidgetEvent{{"entries.add", 1}, gui::Activate{}});
        throw std::logic_error("Expected presentation failure after core mutation");
    } catch (const std::runtime_error&) {}
    check(app.presentation_pending(), "Core mutation lost presentation debt");
    check(app.input_epoch() == initial_epoch + 2, "Failed presentation lost accepted command epoch");
    adapter.fail = false;
    app.retry_presentation();
    app.retry_presentation();
    check(widget(app.view(), "entries.list").state.records.size() == 1,
          "Presentation retry lost or repeated core mutation");
    check(app.input_epoch() == initial_epoch + 2, "Repeated painting retry changed command epoch");
    adapter.fail_measurement = true;
    try {
        app.handle(gui::WidgetEvent{{"entries.editor", 1}, gui::EditText{"Measured value", ""}});
        throw std::logic_error("Expected measurement failure");
    } catch (const std::runtime_error&) {}
    check(app.presentation_pending() && app.input_epoch() == initial_epoch + 3,
          "Measurement failure lost accepted mutation epoch");
    check(widget(app.view(), "entries.editor").state.text == "Measured value",
          "Measurement failure rolled back accepted mutation");
    adapter.fail_measurement = false;
    app.retry_presentation();
    check(!app.presentation_pending() && app.input_epoch() == initial_epoch + 3,
          "Measurement retry changed accepted mutation epoch");
    adapter.fail = true;
    app.handle(gui::CloseEvent{});
    check(adapter.closed(), "Painting failure blocked shutdown");
    check(app.input_epoch() == initial_epoch + 4, "Shutdown after painting failure retained input meaning");
}

void shutdown_without_close() {
    FailingAdapter adapter;
    foundation::ui::Application app(adapter);
    const auto before_shutdown = app.input_epoch();
    app.shutdown();
    check(!adapter.closed() && app.input_epoch() == before_shutdown + 1,
          "Shutdown did not invalidate input before adapter closure");
    app.handle(gui::WidgetEvent{{"entries.editor", 1}, gui::EditText{"Late edit", ""}});
    app.enable_remove_feature();
    app.tick();
    check(!app.next_service() && !app.complete_service({1, gui::ServiceStatus::success, "Late", {}}),
          "Shutdown retained service dispatch");
    check(widget(app.view(), "entries.editor").state.text.empty() &&
          !gui::find_widget(app.view(), {"entries.remove", 1}) &&
          app.input_epoch() == before_shutdown + 1,
          "Shutdown allowed later semantic mutation");
    app.handle(gui::CloseEvent{});
    check(adapter.closed() && app.input_epoch() == before_shutdown + 1,
          "Adapter closure repeated application shutdown epoch");
}
} // namespace

int main() {
    try {
        const auto terminal = scenario<gui::TerminalAdapter>();
        const auto framebuffer = scenario<gui::FramebufferAdapter>();
        check(terminal.widgets.size() == framebuffer.widgets.size(), "Backend changed widget inventory");
        for (std::size_t i = 0; i < terminal.widgets.size(); ++i) {
            check(terminal.widgets[i].spec == framebuffer.widgets[i].spec, "Backend changed feature declaration");
            check(terminal.widgets[i].state.bounds == framebuffer.widgets[i].state.bounds, "Backend changed layout");
            check(terminal.widgets[i].state.text == framebuffer.widgets[i].state.text, "Backend changed values");
            check(terminal.widgets[i].state.records == framebuffer.widgets[i].state.records, "Backend changed rows");
        }
        recovery();
        shutdown_without_close();
        std::cout << "Shared feature, real input boundaries, layout, lifecycle and retry checks passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
