#include "generated/visual/forms.hpp"
#include "generated/visual/events.hpp"
#include "generated/visual/flows.hpp"
#include <gui/memory_adapter.hpp>
#include <iostream>
#include <stdexcept>
#include <string>

static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

static void click(foundation::visual::Ui& ui, const char* id) {
    const auto button = ui.widget(id);
    require(button.has_value(), "Missing button");
    require(ui.handle(gui::WidgetEvent{*button, gui::Activate{}}) ==
            foundation::visual::DispatchResult::handled, "Event was not handled");
}

static void require_samples(const simple_c_state& state, float gain) {
    require(state.count == 4, "Sample count is incorrect");
    for (std::size_t index = 0; index < state.count; ++index)
        require(state.samples[index] == static_cast<float>(index + 1) * gain,
                "C gain output is incorrect");
}

static void require_text(const foundation::visual::Ui& ui, const char* expected) {
    const auto output = ui.widget("simple_c.output");
    require(output.has_value(), "Missing output widget");
    require(gui::find_widget(ui.view(), *output)->state.text == expected,
            "C event helper did not update output text");
}

static void require_run_enabled(const foundation::visual::Ui& ui) {
    const auto run = ui.widget("simple_c.run");
    require(run && gui::find_widget(ui.view(), *run)->state.enabled,
            "C event handler did not restore the Run button");
}

int main() {
    try {
        c_starter::Services services;
        // This display-free host exercises the same form and handlers that a
        // native GUI host would present through its selected adapter.
        gui::MemoryAdapter adapter;
        foundation::visual::Ui ui(adapter, foundation::generated::snapshot("simple_c.controls"));
        auto graph = foundation::generated::make_flow("simple_c.processing", services);
        services.graph = graph.get();
        require(foundation::generated::bind_handlers(ui, services) == 2,
                "Event bindings are missing");

        ui.select("simple_c.gain_choice", std::string("double"));
        click(ui, "simple_c.run");
        require_samples(services.state, 2.0f);
        require_text(ui, "Output: 2 4 6 8");
        require_run_enabled(ui);
        require(!simple_c_collect_sample(&services.state, 99.0f),
                "A full C buffer accepted an extra sample");
        require_samples(services.state, 2.0f);

        ui.select("simple_c.gain_choice", std::string("half"));
        click(ui, "simple_c.run");
        require_samples(services.state, 0.5f);
        require_text(ui, "Output: 0.5 1 1.5 2");
        require_run_enabled(ui);
        click(ui, "simple_c.clear");
        require(services.state.count == 0, "Clear did not reset C state");
        require_text(ui, "Choose a gain, then Run samples.");

        // A C++ processing failure is converted at the boundary into a C status.
        // The C event code still reports failure and re-enables the button.
        services.graph = nullptr;
        click(ui, "simple_c.run");
        require_text(ui, "Processing failed.");
        require_run_enabled(ui);
        services.graph = graph.get();
        click(ui, "simple_c.run");
        require_samples(services.state, 0.5f);
        require_text(ui, "Output: 0.5 1 1.5 2");

        std::cout << "C starter: gain 2 -> 2 4 6 8; gain 0.5 -> 0.5 1 1.5 2; "
                     "GUI events, bounded C buffer and failure recovery verified.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "C starter: " << error.what() << '\n';
        return 1;
    }
}
