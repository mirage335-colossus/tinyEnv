#include "generated/visual/forms.hpp"
#include "generated/visual/events.hpp"
#include "generated/visual/flows.hpp"
#include "services.hpp"
#include <gui/memory_adapter.hpp>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

static void click(foundation::visual::Ui& ui, const char* id) {
    const auto button = ui.widget(id);
    require(button.has_value(), "Missing button");
    require(ui.handle(gui::WidgetEvent{*button, gui::Activate{}}) ==
            foundation::visual::DispatchResult::handled, "Event was not handled");
}

int main() {
    try {
        starter::Services services;
        // A display-free GUI host keeps this tiny application easy to build.
        // The same form and handlers can be composed with a native GUI adapter.
        gui::MemoryAdapter adapter;
        foundation::visual::Ui ui(adapter, foundation::generated::snapshot("simple.controls"));
        auto graph = foundation::generated::make_flow("simple.processing", services);
        services.graph = graph.get();
        require(foundation::generated::bind_handlers(ui, services) == 2,
                "Event bindings are missing");

        ui.select("simple.gain_choice", std::string("double"));
        click(ui, "simple.run");
        require(services.samples == std::vector<float>({2, 4, 6, 8}), "Gain 2 output is incorrect");
        const auto* output = gui::find_widget(ui.view(), *ui.widget("simple.output"));
        require(output && output->state.text == "Output: 2 4 6 8", "Output text was not updated");
        require(gui::find_widget(ui.view(), *ui.widget("simple.run"))->state.enabled,
                "Run button was not restored");

        ui.select("simple.gain_choice", std::string("half"));
        click(ui, "simple.run");
        require(services.samples == std::vector<float>({0.5f, 1, 1.5f, 2}),
                "Repeated run or Gain 0.5 output is incorrect");
        click(ui, "simple.clear");
        require(services.samples.empty(), "Clear did not reset samples");
        output = gui::find_widget(ui.view(), *ui.widget("simple.output"));
        require(output && output->state.text == "Choose a gain, then Run samples.",
                "Clear did not update output text");
        std::cout << "C++ starter: gain 2 -> 2 4 6 8; gain 0.5 -> 0.5 1 1.5 2; GUI events verified.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "C++ starter: " << error.what() << '\n';
        return 1;
    }
}
