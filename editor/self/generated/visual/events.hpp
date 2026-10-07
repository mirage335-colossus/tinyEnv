// Generated from the semantic design; edit ordinary source files for behavior.
// No editor executable or design document is needed by this header at runtime.
#pragma once

#include "visual/ui/ui.hpp"
#include <cstddef>
#include <vector>
#include "editor/self/handlers.hpp"

namespace foundation::editor::self_generated {

inline std::vector<foundation::visual::EventBinding> event_bindings() {
    return {
        {"editor.open", foundation::visual::EventKind::activate, "self.open"},
        {"editor.new", foundation::visual::EventKind::activate, "self.new"},
        {"editor.save", foundation::visual::EventKind::activate, "self.save"},
        {"editor.undo", foundation::visual::EventKind::activate, "self.undo"},
        {"editor.redo", foundation::visual::EventKind::activate, "self.redo"},
        {"editor.preview", foundation::visual::EventKind::activate, "self.preview"},
        {"editor.build", foundation::visual::EventKind::activate, "self.build"},
        {"editor.run", foundation::visual::EventKind::activate, "self.run"},
        {"editor.stop", foundation::visual::EventKind::activate, "self.stop"},
        {"editor.details", foundation::visual::EventKind::activate, "self.details"},
    };
}

// Services must outlive Ui and its callbacks. An explicit typed wrapper
// can call any linked C++ implementation or a project-owned Rust C ABI.
template<class Services>
std::size_t bind_handlers(foundation::visual::Ui& ui, Services& services) {
    std::size_t registered = 0;
    // design adapter self.open
    registered += ui.bind<gui::Activate>("editor.open",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_open(services, model, input);
        });
    // design adapter self.new
    registered += ui.bind<gui::Activate>("editor.new",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_new(services, model, input);
        });
    // design adapter self.save
    registered += ui.bind<gui::Activate>("editor.save",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_save(services, model, input);
        });
    // design adapter self.undo
    registered += ui.bind<gui::Activate>("editor.undo",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_undo(services, model, input);
        });
    // design adapter self.redo
    registered += ui.bind<gui::Activate>("editor.redo",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_redo(services, model, input);
        });
    // design adapter self.preview
    registered += ui.bind<gui::Activate>("editor.preview",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_preview(services, model, input);
        });
    // design adapter self.build
    registered += ui.bind<gui::Activate>("editor.build",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_build(services, model, input);
        });
    // design adapter self.run
    registered += ui.bind<gui::Activate>("editor.run",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_run(services, model, input);
        });
    // design adapter self.stop
    registered += ui.bind<gui::Activate>("editor.stop",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_stop(services, model, input);
        });
    // design adapter self.details
    registered += ui.bind<gui::Activate>("editor.details",
        [&services](foundation::visual::Ui& model, const gui::Activate& input) {
            ::foundation::editor::self::on_details(services, model, input);
        });
    return registered;
}

// The caller must first validate generation, visibility, enabled state and
// the event's ownership. This helper also supports self-hosted UIs
// whose model is application-owned rather than visual::Ui.
template<class UiContext, class Services>
bool dispatch_handler(UiContext& ui, Services& services, const gui::WidgetEvent& event) {
    if (event.target.id == "editor.open") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_open(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.new") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_new(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.save") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_save(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.undo") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_undo(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.redo") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_redo(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.preview") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_preview(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.build") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_build(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.run") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_run(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.stop") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_stop(services, ui, *input);
            return true;
        }
    }
    if (event.target.id == "editor.details") {
        if (const auto* input = std::get_if<gui::Activate>(&event.input)) {
            ::foundation::editor::self::on_details(services, ui, *input);
            return true;
        }
    }
    return false;
}

} // namespace foundation::editor::self_generated
