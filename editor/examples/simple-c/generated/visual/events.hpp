// Generated from the semantic design; edit ordinary source files for behavior.
// No editor executable or design document is needed by this header at runtime.
#pragma once

#include "visual/ui/ui.hpp"
#include <cstddef>
#include <vector>
#include "event_adapter.hpp"

namespace foundation::generated {

inline std::vector<foundation::visual::EventBinding> event_bindings() {
    return {
        {"simple_c.run", foundation::visual::EventKind::activate, "simple_c.on_run"},
        {"simple_c.clear", foundation::visual::EventKind::activate, "simple_c.on_clear"},
    };
}

// Services must outlive Ui and its callbacks. An explicit typed wrapper
// can call any linked C++ implementation or a project-owned Rust C ABI.
template<class Services>
std::size_t bind_handlers(foundation::visual::Ui& ui, Services& services) {
    std::size_t registered = 0;
    // design adapter simple_c.on_run
    registered += ui.bind<gui::Activate>("simple_c.run",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::c_starter::on_run(services, model, input);
        });
    // design adapter simple_c.on_clear
    registered += ui.bind<gui::Activate>("simple_c.clear",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::c_starter::on_clear(services, model, input);
        });
    return registered;
}

// The caller must first validate generation, visibility, enabled state and
// the event's ownership. This helper also supports self-hosted UIs
// whose model is application-owned rather than visual::Ui.
template<class UiContext, class Services>
bool dispatch_handler(UiContext& ui, Services& services, const gui::WidgetEvent& event) {
    if (event.target.id == "simple_c.run") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::c_starter::on_run(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "simple_c.clear") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::c_starter::on_clear(services, ui, *input);
            return true;
        }
    }
    return false;
}

} // namespace foundation::generated
