#include <gui/web.hpp>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
}
int main() {
    try {
        using J = gui::web_detail::Json;
        std::vector<gui::Event> events;
        gui::WebAdapter adapter([&](const gui::Event& event) { events.push_back(event); });
        gui::Snapshot view; view.client_size = {300, 200};
        gui::Widget list; list.spec.key = {"files", 1}; list.spec.kind = gui::Kind::list;
        list.spec.context_input = true; list.state.bounds = {20, 20, 180, 80};
        list.state.records = {{"one", "One", {}, true, true}}; view.widgets = {list}; adapter.present(view);
        gui::WebSession session(adapter, "context"); std::uint64_t sequence = 0;
        const auto initial = gui::web_detail::Parser(session.initial()).parse();
        check(initial.at("snapshot").at("widgets").array()[0].at("contextInput").boolean(),
              "Browser presentation lost context-only capability");
        auto send = [&](std::string generation, std::string owner = "0", std::string expected_error = "") {
            const auto operation = J::Object{{"type", "pointer"}, {"key", J::Object{{"id", "files"}, {"generation", std::move(generation)}}},
                {"kind", "context"}, {"pointerId", std::move(owner)}, {"x", 40}, {"y", 40}, {"wheelX", 0}, {"wheelY", 0},
                {"control", false}, {"shift", false}, {"alt", false}};
            const auto reply = session.receive(gui::web_detail::encode(J::Object{{"epoch", "context"},
                {"seq", std::to_string(++sequence)}, {"operation", operation}}));
            check(gui::web_detail::Parser(reply).parse().at("error").str() == expected_error,
                  "Browser context reply did not match its expected validation result");
        };
        send("1"); check(events.size() == 1, "Browser context-only list lost secondary input");
        const auto* input = std::get_if<gui::PointerInput>(&std::get<gui::WidgetEvent>(events.back()).input);
        check(input && input->kind == gui::PointerKind::context_menu && input->pointer_id == 0 &&
              input->position == gui::Point{40, 40}, "Browser context intent changed in transport");
        send("2", "0", "Stale widget generation"); send("1", "8");
        check(events.size() == 1, "Stale or owner-bearing context accepted");
        gui::Widget choice; choice.spec.key = {"choice", 1}; choice.spec.kind = gui::Kind::choice;
        choice.state.bounds = {210, 20, 70, 40}; choice.state.options = {{"one", "One", "", true}};
        view.widgets.push_back(choice); adapter.present(view); check(adapter.open_popup(choice.spec.key), "Browser fixture popup failed");
        send("1"); check(events.size() == 1, "Browser popup allowed background context input"); adapter.close_popup(choice.spec.key);
        view.widgets[0].spec.context_input = false; view.widgets[0].spec.key.generation = 2; adapter.present(view); send("2");
        check(events.size() == 1, "Browser context permission did not follow current presentation");
        std::cout << "In-memory browser context serialization, parsing and permission passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
