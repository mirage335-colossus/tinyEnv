#include "event_handlers.hpp"
#include "flow_adapter.hpp"
#include <exception>
#include <sstream>

namespace starter {

// Helpers called from event code can update any widget through the same Ui.
static void show_samples(const Services& services, foundation::visual::Ui& ui) {
    std::ostringstream text;
    text << "Output:";
    for (float sample : services.samples) text << ' ' << sample;
    ui.set_text("simple.output", text.str());
}

void on_run(Services& services, foundation::visual::Ui& ui, const gui::Activate&) {
    const auto choice = ui.selected("simple.gain_choice").value;
    services.gain = choice == "half" ? 0.5f : 2.0f;
    ui.set_enabled("simple.run", false);
    ui.set_text("simple.output", "Processing...");
    try {
        run_samples(services);
        show_samples(services, ui);
    } catch (const std::exception& error) {
        ui.set_text("simple.output", error.what());
    }
    ui.set_enabled("simple.run", true);
}

void on_clear(Services& services, foundation::visual::Ui& ui, const gui::Activate&) {
    services.samples.clear();
    ui.set_text("simple.output", "Choose a gain, then Run samples.");
}

} // namespace starter
