// Generated from the semantic design; edit ordinary source files for behavior.
// No editor executable or design document is needed by this header at runtime.
#pragma once

#include <gui/contract.hpp>
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string_view>

namespace foundation::generated {

namespace ids {
inline constexpr std::string_view i_simple_2econtrols = "simple.controls";
inline constexpr std::string_view i_simple_2eheading = "simple.heading";
inline constexpr std::string_view i_simple_2egain_5fchoice = "simple.gain_choice";
inline constexpr std::string_view i_simple_2erun = "simple.run";
inline constexpr std::string_view i_simple_2eclear = "simple.clear";
inline constexpr std::string_view i_simple_2eoutput = "simple.output";
inline constexpr std::string_view i_simple_2eon_5frun = "simple.on_run";
inline constexpr std::string_view i_simple_2eon_5fclear = "simple.on_clear";
inline constexpr std::string_view i_simple_2eprocessing = "simple.processing";
inline constexpr std::string_view i_simple_2esource = "simple.source";
inline constexpr std::string_view i_simple_2egain = "simple.gain";
inline constexpr std::string_view i_simple_2ecollector = "simple.collector";
inline constexpr std::string_view i_simple_2esource_5fto_5fgain = "simple.source_to_gain";
inline constexpr std::string_view i_simple_2egain_5fto_5fcollector = "simple.gain_to_collector";
} // namespace ids

namespace form_detail {
inline void append_i_simple_2econtrols(gui::Snapshot& view, std::uint64_t generation) {
    view.pages.push_back({"simple.controls", "Gain controls"});
    { // design widget simple.heading
        gui::Widget widget;
        widget.spec.key = {"simple.heading", generation};
        widget.spec.kind = gui::Kind::label;
        widget.spec.page = "simple.controls";
        widget.spec.parent = "";
        widget.spec.binding = "";
        widget.state.bounds = {12, 12, 496, 28};
        widget.state.label = "";
        widget.state.text = "Four samples through an ordinary C++ gain function";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget simple.gain_choice
        gui::Widget widget;
        widget.spec.key = {"simple.gain_choice", generation};
        widget.spec.kind = gui::Kind::choice;
        widget.spec.page = "simple.controls";
        widget.spec.parent = "";
        widget.spec.binding = "";
        widget.state.bounds = {12, 50, 200, 32};
        widget.state.label = "Gain";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        widget.state.options.push_back({"double", "Gain 2", "2", true});
        widget.state.options.push_back({"half", "Gain 0.5", "0.5", true});
        view.widgets.push_back(std::move(widget));
    }
    { // design widget simple.run
        gui::Widget widget;
        widget.spec.key = {"simple.run", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "simple.controls";
        widget.spec.parent = "";
        widget.spec.binding = "simple.on_run";
        widget.state.bounds = {224, 50, 140, 32};
        widget.state.label = "Run samples";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget simple.clear
        gui::Widget widget;
        widget.spec.key = {"simple.clear", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "simple.controls";
        widget.spec.parent = "";
        widget.spec.binding = "simple.on_clear";
        widget.state.bounds = {376, 50, 100, 32};
        widget.state.label = "Clear";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget simple.output
        gui::Widget widget;
        widget.spec.key = {"simple.output", generation};
        widget.spec.kind = gui::Kind::text;
        widget.spec.page = "simple.controls";
        widget.spec.parent = "";
        widget.spec.binding = "";
        widget.spec.text_policy.multiline = true;
        widget.spec.text_policy.read_only = true;
        widget.spec.text_policy.max_bytes = 1048576;
        widget.state.wrap = gui::TextWrap::word;
        widget.state.bounds = {12, 96, 496, 100};
        widget.state.label = "Output";
        widget.state.text = "Choose a gain, then Run samples.";
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
    view.title = "Simple C++ starter";
    if (form_id == "simple.controls") {
        view.client_size = {520, 220};
        view.active_page = "simple.controls";
        form_detail::append_i_simple_2econtrols(view, generation);
        return view;
    }
    throw std::invalid_argument("Unknown generated form ID");
}

inline gui::Snapshot all_forms_snapshot(std::uint64_t generation = 1) {
    if (generation == 0) throw std::invalid_argument("Widget generation must be nonzero");
    gui::Snapshot view;
    view.revision = 1;
    view.title = "Simple C++ starter";
    view.client_size = {520, 220};
    view.active_page = "simple.controls";
    form_detail::append_i_simple_2econtrols(view, generation);
    return view;
}

} // namespace foundation::generated
