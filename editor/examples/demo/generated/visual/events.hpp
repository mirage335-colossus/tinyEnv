// Generated from the semantic design; edit ordinary source files for behavior.
// No editor executable or design document is needed by this header at runtime.
#pragma once

#include "visual/ui/ui.hpp"
#include <cstddef>
#include <vector>
#include "handlers.hpp"

namespace foundation::generated {

inline std::vector<foundation::visual::EventBinding> event_bindings() {
    return {
        {"demo.refresh", foundation::visual::EventKind::activate, "demo.on_refresh"},
        {"demo.start", foundation::visual::EventKind::activate, "demo.on_start"},
        {"demo.stop", foundation::visual::EventKind::activate, "demo.on_stop"},
    };
}

// Services must outlive Ui and its callbacks. An explicit typed wrapper
// can call any linked C++ implementation or a project-owned Rust C ABI.
template<class Services>
std::size_t bind_handlers(foundation::visual::Ui& ui, Services& services) {
    std::size_t registered = 0;
    // design adapter demo.on_refresh
    registered += ui.bind<gui::Activate>("demo.refresh",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::demo::on_refresh(services, model, input);
        });
    // design adapter demo.on_start
    registered += ui.bind<gui::Activate>("demo.start",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::demo::on_start(services, model, input);
        });
    // design adapter demo.on_stop
    registered += ui.bind<gui::Activate>("demo.stop",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::demo::on_stop(services, model, input);
        });
    return registered;
}

// The caller must first validate generation, visibility, enabled state and
// the event's ownership. This helper also supports self-hosted UIs
// whose model is application-owned rather than visual::Ui.
template<class UiContext, class Services>
bool dispatch_handler(UiContext& ui, Services& services, const gui::WidgetEvent& event) {
    if (event.target.id == "demo.refresh") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::demo::on_refresh(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "demo.start") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::demo::on_start(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "demo.stop") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::demo::on_stop(services, ui, *input);
            return true;
        }
    }
    return false;
}

} // namespace foundation::generated
