#include <gui/framebuffer.hpp>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
struct Fixture {
    gui::Snapshot view;
    std::vector<gui::Event> events;
    gui::FramebufferAdapter adapter{[this](const gui::Event& event) { events.push_back(event); }};
    Fixture() {
        view.client_size = {300, 200};
        gui::Widget list;
        list.spec.key = {"files", 1}; list.spec.kind = gui::Kind::list;
        list.spec.context_input = true; list.spec.row_height = 20;
        list.state.bounds = {20, 20, 180, 80}; list.state.content_size = {180, 120};
        list.state.records = {{"one", "One", {}, true, true}, {"two", "Two", {}, true, true}};
        view.widgets = {list}; adapter.present(view);
    }
    gui::WidgetEvent context(gui::WidgetKey key = {"files", 1}, gui::Point at = {40, 40}) {
        return {std::move(key), gui::PointerInput{gui::PointerKind::context_menu, at}};
    }
};
void opt_in_and_primary() {
    Fixture f;
    f.adapter.pointer({gui::PointerKind::click, {40, 30}});
    check(f.events.size() == 1 && std::get<gui::SelectRecord>(std::get<gui::WidgetEvent>(f.events.back()).input).id == "one",
          "Context-only list lost ordinary primary selection");
    f.adapter.context_menu({40, 40});
    check(f.events.size() == 2, "Secondary input was lost or dispatched twice");
    const auto& event = std::get<gui::WidgetEvent>(f.events.back());
    const auto* input = std::get_if<gui::PointerInput>(&event.input);
    check(event.target == gui::WidgetKey{"files", 1} && input && input->kind == gui::PointerKind::context_menu &&
          input->pointer_id == 0 && input->position == gui::Point{40, 40}, "Context coordinates or identity changed");
    check(!f.adapter.popup(), "Context opt-in also opened the default popup");
    f.view.widgets[0].spec.context_input = false; f.view.widgets[0].spec.key.generation = 2; f.adapter.present(f.view);
    check(f.adapter.policy().send(f.context({"files", 2})) == gui::Delivery::ignored, "Non-opted-in context request accepted");
    gui::Widget choice; choice.spec.key = {"choice", 1}; choice.spec.kind = gui::Kind::choice;
    choice.state.bounds = {210, 20, 70, 40}; choice.state.options = {{"first", "First", "", true}};
    f.view.widgets.push_back(choice); f.adapter.present(f.view); f.adapter.context_menu({220, 30});
    check(f.adapter.popup() && f.adapter.popup()->key == choice.spec.key && f.events.size() == 2,
          "Default context popup behavior changed");
}
void unavailable_inputs() {
    Fixture f;
    check(f.adapter.policy().send(f.context({"files", 2})) == gui::Delivery::ignored, "Stale generation accepted");
    check(f.adapter.policy().send(f.context({"files", 1}, {201, 40})) == gui::Delivery::ignored, "Outside context coordinates accepted");
    check(f.adapter.policy().send(f.context({"files", 1}, {std::numeric_limits<double>::quiet_NaN(), 40})) == gui::Delivery::ignored,
          "Nonfinite context coordinates accepted");
    auto owned = f.context(); std::get<gui::PointerInput>(owned.input).pointer_id = 7;
    check(f.adapter.policy().send(owned) == gui::Delivery::ignored, "Context request established a physical owner");
    for (const bool hidden : {false, true}) {
        f.view.widgets[0].state.enabled = hidden; f.view.widgets[0].state.visible = !hidden; f.adapter.present(f.view);
        check(f.adapter.policy().send(f.context()) == gui::Delivery::ignored, "Disabled or hidden context target accepted");
    }
    f.view.widgets[0].state.enabled = true; f.view.widgets[0].state.visible = true;
    f.view.pages = {{"active", "Active"}, {"other", "Other"}}; f.view.active_page = "active";
    f.view.widgets[0].spec.page = "other"; f.view.widgets[0].spec.key.generation = 2; f.adapter.present(f.view);
    check(f.adapter.policy().send(f.context({"files", 2})) == gui::Delivery::ignored, "Inactive-page context target accepted");
    f.view.widgets[0].spec.page.clear(); f.view.widgets[0].spec.key.generation = 3; f.view.pages.clear(); f.view.active_page.reset();
    gui::Widget modal; modal.spec.key = {"modal", 1}; modal.spec.kind = gui::Kind::group;
    modal.state.bounds = {220, 110, 60, 60}; f.view.widgets.push_back(modal); f.view.modal_root = modal.spec.key;
    f.adapter.present(f.view);
    check(f.adapter.policy().send(f.context({"files", 3})) == gui::Delivery::ignored, "Background context bypassed modal scope");
    check(f.events.empty(), "Rejected context input reached the application");
}
void overlays_and_scroll() {
    Fixture f;
    gui::Widget label; label.spec.key = {"label", 1}; label.spec.kind = gui::Kind::label;
    label.state.bounds = {30, 30, 80, 24}; label.state.text = "Decoration";
    f.view.widgets.push_back(label); f.adapter.present(f.view); f.adapter.context_menu({40, 40});
    check(f.events.size() == 1, "Inert decoration swallowed context input");
    gui::Widget button; button.spec.key = {"cover", 1}; button.spec.kind = gui::Kind::button;
    button.state.bounds = label.state.bounds; button.state.label = "Overlay";
    f.view.widgets.push_back(button); f.adapter.present(f.view); f.adapter.context_menu({40, 40});
    check(f.events.size() == 1 && f.adapter.policy().send(f.context()) == gui::Delivery::ignored,
          "Interactive overlay leaked context to an underlying target");
    f.view.widgets.back().spec.context_input = true; f.view.widgets.back().spec.key.generation = 2; f.adapter.present(f.view); f.adapter.context_menu({40, 40});
    check(f.events.size() == 2 && std::get<gui::WidgetEvent>(f.events.back()).target == f.view.widgets.back().spec.key,
          "Top opted-in target lost context input");
    gui::Widget group; group.spec.key = {"scroll", 1}; group.spec.kind = gui::Kind::group;
    group.state.bounds = {0, 0, 120, 90}; group.state.content_size = {120, 180}; group.state.content_clip = gui::Rect{0, 0, 120, 70};
    auto list = f.view.widgets[0]; list.spec.parent = "scroll"; list.spec.key.generation = 2; list.state.bounds = {20, 60, 180, 80};
    f.view.widgets = {group, list}; f.adapter.present(f.view); f.adapter.scroll(group.spec.key, {0, 30});
    f.adapter.context_menu({40, 40}); check(f.events.size() == 3, "Scrolled context bounds used unscrolled coordinates");
    check(f.adapter.policy().send(f.context({"files", 2}, {40, 75})) == gui::Delivery::ignored, "Context input escaped parent clip");
    f.view.widgets[0].state.enabled = false; f.adapter.present(f.view);
    check(f.adapter.policy().send(f.context({"files", 2})) == gui::Delivery::ignored, "Disabled ancestor accepted context input");
}
void gesture_and_reentrancy() {
    Fixture f;
    gui::Widget choice; choice.spec.key = {"choice", 1}; choice.spec.kind = gui::Kind::choice;
    choice.state.bounds = {210, 20, 70, 40}; choice.state.options = {{"one", "One", "", true}};
    f.view.widgets.push_back(choice); f.adapter.present(f.view);
    f.adapter.pointer({gui::PointerKind::press, {40, 30}, 0, 0, false, false, false, 9});
    f.adapter.context_menu({40, 30}); check(f.events.empty(), "Secondary click interrupted primary gesture");
    f.adapter.context_menu({220, 30}); check(f.events.empty() && !f.adapter.popup(), "Foreign secondary popup interrupted primary gesture");
    f.adapter.pointer({gui::PointerKind::release, {40, 30}, 0, 0, false, false, false, 9});
    check(f.events.size() == 1 && std::holds_alternative<gui::SelectRecord>(std::get<gui::WidgetEvent>(f.events.back()).input),
          "Suppressed context corrupted the primary gesture");
    gui::FramebufferAdapter* current = nullptr; unsigned count = 0;
    gui::FramebufferAdapter closing([&](const gui::Event&) { ++count; current->close(); }); current = &closing;
    closing.present(f.view); closing.context_menu({40, 40});
    check(count == 1 && closing.closed(), "Context dispatch continued after synchronous close");
    f.adapter.close(); check(f.adapter.policy().send(f.context()) == gui::Delivery::ignored, "Closed adapter accepted context input");
}
}
int main() {
    try {
        opt_in_and_primary(); unavailable_inputs(); overlays_and_scroll(); gesture_and_reentrancy();
        std::cout << "Context input opt-in, primary semantics, lifecycle and geometry passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
