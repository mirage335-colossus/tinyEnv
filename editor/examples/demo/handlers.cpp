#include "handlers.hpp"

#include <stdexcept>
#include <utility>

namespace foundation::editor::demo {
using namespace foundation::visual;

void set_busy(Ui& ui, bool busy) {
    const auto batch = ui.batch();
    ui.set_enabled("demo.start", !busy);
    ui.set_enabled("demo.refresh", !busy);
    ui.set_enabled("demo.stop", busy);
}

void refresh_devices(Services&, Ui& ui) {
    const auto batch = ui.batch();
    ui.replace_options("demo.device", {
        {"simulated", "Simulated receiver", "simulated", true},
        {"recording", "Stored recording", "recording", true}
    }, SelectionPolicy::keep_if_present);
    if (!ui.selected("demo.device").value)
        ui.select("demo.device", std::string("simulated"));
    ui.set_text("demo.status", "Device choices refreshed by an ordinary C++ helper.");
}

void on_refresh(Services& services, Ui& ui, const gui::Activate&) {
    refresh_devices(services, ui);
}

void on_start(Services& services, Ui& ui, const gui::Activate&) {
    if (services.running) return;
    services.ui_post = ui.begin_request();
    services.status = *ui.widget("demo.status");
    services.start_button = *ui.widget("demo.start");
    services.stop_button = *ui.widget("demo.stop");
    services.refresh_button = *ui.widget("demo.refresh");
    set_busy(ui, true);
    ui.set_text("demo.status", "Processing the two-input / four-output graph.");
    try {
        if (!services.start) throw std::logic_error("No processing service installed");
        services.start();
        services.running = true;
    } catch (const std::exception& error) {
        services.running = false;
        set_busy(ui, false);
        ui.set_text("demo.status", error.what());
    }
}

void on_stop(Services& services, Ui& ui, const gui::Activate&) {
    if (services.stop) services.stop();
    services.running = false;
    ui.begin_request(); // Invalidates any late updates from the stopped request.
    set_busy(ui, false);
    ui.set_text("demo.status", "Stopped.");
}

void report_progress(Services& services, std::string message) {
    const auto result = services.ui_post.post(SetText{services.status, std::move(message)},
                                            Delivery::progress, "demo.progress");
    if (result != PostResult::accepted && result != PostResult::coalesced)
        ++services.rejected_posts;
}

void announce_completion(Services& services) {
    // Helpers several calls below an event can cause GUI effects, using only an
    // owned mailbox capability. UI draining occurs on the composition thread.
    const auto post = [&](UiCommand command) {
        if (services.ui_post.post(std::move(command)) != PostResult::accepted)
            ++services.rejected_posts;
    };
    post(SetText{services.status, "Completed: four sums, four differences, eight trace items, two metrics."});
    post(SetEnabled{services.start_button, true});
    post(SetEnabled{services.stop_button, false});
    post(SetEnabled{services.refresh_button, true});
    services.running = false;
}

} // namespace foundation::editor::demo
