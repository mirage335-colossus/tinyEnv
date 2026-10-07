#pragma once
#include <gui/contract.hpp>
#include <array>
#include <string_view>

namespace foundation::ui {
// One application-owned declaration determines creation, ordering and layout.
// Concrete adapters see only the resulting standard Snapshot.
struct ViewDefinition {
    std::string_view id;
    gui::Kind kind;
    double height;
    std::string_view text, label, placeholder;
    bool bold = false;
    gui::TextWrap wrap = gui::TextWrap::none;
    bool remove_extension = false;
};
inline constexpr std::array view_definition{
    ViewDefinition{"entries.form", gui::Kind::group, 0, "", "", ""},
    ViewDefinition{"entries.heading", gui::Kind::label, 32, "Entry list", "", "", true},
    ViewDefinition{"entries.editor", gui::Kind::text, 32, "", "New entry", "Type an entry"},
    ViewDefinition{"entries.add", gui::Kind::button, 32, "", "Add entry", ""},
    ViewDefinition{"entries.options", gui::Kind::menu, 32, "", "Actions", ""},
    ViewDefinition{"entries.task.start", gui::Kind::button, 32, "", "Count text", ""},
    ViewDefinition{"entries.task.cancel", gui::Kind::button, 32, "", "Cancel task", ""},
    ViewDefinition{"entries.task.status", gui::Kind::label, 32, "Task ready", "", ""},
    ViewDefinition{"entries.list", gui::Kind::list, 72, "", "Entries", "No entries"},
    ViewDefinition{"entries.count", gui::Kind::label, 32, "", "", ""},
    ViewDefinition{"entries.status", gui::Kind::label, 32, "", "", "", false, gui::TextWrap::word},
    ViewDefinition{"entries.remove", gui::Kind::button, 32, "", "Remove selected", "", false, gui::TextWrap::none, true}
};
} // namespace foundation::ui
