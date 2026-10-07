// Generated from the semantic design; edit ordinary source files for behavior.
// No editor executable or design document is needed by this header at runtime.
#pragma once

#include <gui/contract.hpp>
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string_view>

namespace foundation::editor::self_generated {

namespace ids {
inline constexpr std::string_view i_editor_2echrome = "editor.chrome";
inline constexpr std::string_view i_editor_2eopen = "editor.open";
inline constexpr std::string_view i_editor_2enew = "editor.new";
inline constexpr std::string_view i_editor_2esave = "editor.save";
inline constexpr std::string_view i_editor_2eundo = "editor.undo";
inline constexpr std::string_view i_editor_2eredo = "editor.redo";
inline constexpr std::string_view i_editor_2epreview = "editor.preview";
inline constexpr std::string_view i_editor_2ebuild = "editor.build";
inline constexpr std::string_view i_editor_2erun = "editor.run";
inline constexpr std::string_view i_editor_2estop = "editor.stop";
inline constexpr std::string_view i_editor_2edetails = "editor.details";
inline constexpr std::string_view i_self_2eopen = "self.open";
inline constexpr std::string_view i_self_2enew = "self.new";
inline constexpr std::string_view i_self_2esave = "self.save";
inline constexpr std::string_view i_self_2eundo = "self.undo";
inline constexpr std::string_view i_self_2eredo = "self.redo";
inline constexpr std::string_view i_self_2epreview = "self.preview";
inline constexpr std::string_view i_self_2ebuild = "self.build";
inline constexpr std::string_view i_self_2erun = "self.run";
inline constexpr std::string_view i_self_2estop = "self.stop";
inline constexpr std::string_view i_self_2edetails = "self.details";
inline constexpr std::string_view i_self_2einspect = "self.inspect";
inline constexpr std::string_view i_self_2esource = "self.source";
inline constexpr std::string_view i_self_2ecount = "self.count";
inline constexpr std::string_view i_self_2ebytes = "self.bytes";
} // namespace ids

namespace form_detail {
inline void append_i_editor_2echrome(gui::Snapshot& view, std::uint64_t generation) {
    view.pages.push_back({"editor.chrome", "Editor toolbar"});
    { // design widget editor.open
        gui::Widget widget;
        widget.spec.key = {"editor.open", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.open";
        widget.state.bounds = {8, 8, 72, 32};
        widget.state.label = "Open";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.new
        gui::Widget widget;
        widget.spec.key = {"editor.new", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.new";
        widget.state.bounds = {84, 8, 62, 32};
        widget.state.label = "New";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.save
        gui::Widget widget;
        widget.spec.key = {"editor.save", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.save";
        widget.state.bounds = {150, 8, 62, 32};
        widget.state.label = "Save";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.undo
        gui::Widget widget;
        widget.spec.key = {"editor.undo", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.undo";
        widget.state.bounds = {216, 8, 64, 32};
        widget.state.label = "Undo";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.redo
        gui::Widget widget;
        widget.spec.key = {"editor.redo", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.redo";
        widget.state.bounds = {284, 8, 64, 32};
        widget.state.label = "Redo";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.preview
        gui::Widget widget;
        widget.spec.key = {"editor.preview", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.preview";
        widget.state.bounds = {352, 8, 78, 32};
        widget.state.label = "Preview";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.build
        gui::Widget widget;
        widget.spec.key = {"editor.build", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.build";
        widget.state.bounds = {434, 8, 64, 32};
        widget.state.label = "Build";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.run
        gui::Widget widget;
        widget.spec.key = {"editor.run", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.run";
        widget.state.bounds = {502, 8, 58, 32};
        widget.state.label = "Run";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.stop
        gui::Widget widget;
        widget.spec.key = {"editor.stop", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.stop";
        widget.state.bounds = {564, 8, 62, 32};
        widget.state.label = "Stop";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget editor.details
        gui::Widget widget;
        widget.spec.key = {"editor.details", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "editor.chrome";
        widget.spec.parent = "";
        widget.spec.binding = "self.details";
        widget.state.bounds = {630, 8, 72, 32};
        widget.state.label = "Details";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
}

} // namespace form_detail

inline gui::Snapshot snapshot(std::string_view form_id, std::uint64_t generation = 1) {
    if (generation == 0) throw std::invalid_argument("Widget generation must be nonzero");
    gui::Snapshot view;
    view.revision = 1;
    view.title = "Foundation editor self-host";
    if (form_id == "editor.chrome") {
        view.client_size = {1100, 720};
        view.active_page = "editor.chrome";
        form_detail::append_i_editor_2echrome(view, generation);
        return view;
    }
    throw std::invalid_argument("Unknown generated form ID");
}

inline gui::Snapshot all_forms_snapshot(std::uint64_t generation = 1) {
    if (generation == 0) throw std::invalid_argument("Widget generation must be nonzero");
    gui::Snapshot view;
    view.revision = 1;
    view.title = "Foundation editor self-host";
    view.client_size = {1100, 720};
    view.active_page = "editor.chrome";
    form_detail::append_i_editor_2echrome(view, generation);
    return view;
}

} // namespace foundation::editor::self_generated
