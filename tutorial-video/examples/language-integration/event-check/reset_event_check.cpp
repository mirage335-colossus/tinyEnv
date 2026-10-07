// Probe the actual exported form and binding without changing their files.
#include "generated/visual/forms.hpp"
#include "generated/visual/events.hpp"
#include "services.hpp"
#include <gui/memory_adapter.hpp>

#include <iostream>
#include <stdexcept>

static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

int main() {
    try {
        c_starter::Services services;
        gui::MemoryAdapter adapter;
        foundation::visual::Ui ui(
            adapter, foundation::generated::snapshot("simple_c.controls"));
        require(foundation::generated::bind_handlers(ui, services) == 3,
                "Expected Run, Clear, and newly exported Reset bindings");

        services.state.gain = 7.0f;
        services.state.count = 2;
        services.state.samples[0] = 12.0f;
        services.state.samples[1] = 24.0f;
        ui.set_text("simple_c.output", "Before reset");

        const auto button = ui.widget("button1");
        require(button.has_value(), "The exported Reset button is missing");
        require(ui.handle(gui::WidgetEvent{*button, gui::Activate{}}) ==
                    foundation::visual::DispatchResult::handled,
                "The actual generated Reset binding did not handle Activate");
        require(services.state.gain == 2.0f, "Reset did not restore the C gain");
        require(services.state.count == 0, "Reset did not clear the C sample count");
        for (const float sample : services.state.samples)
            require(sample == 0.0f, "Reset did not clear the C sample buffer");

        const auto output = ui.widget("simple_c.output");
        require(output.has_value(), "The exported output widget is missing");
        require(gui::find_widget(ui.view(), *output)->state.text ==
                    "State reset. Choose a gain and run again.",
                "Reset did not update the output widget");

        std::cout << "Exported GUI bindings: 3\n"
                     "button1 Activate: handled\n"
                     "C state: gain 2, count 0, samples cleared\n"
                     "Output: State reset. Choose a gain and run again.\n"
                     "Actual generated Reset event: PASS\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
