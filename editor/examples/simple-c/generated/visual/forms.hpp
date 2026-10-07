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
inline constexpr std::string_view i_simple_5fc_2econtrols = "simple_c.controls";
inline constexpr std::string_view i_simple_5fc_2eheading = "simple_c.heading";
inline constexpr std::string_view i_simple_5fc_2egain_5fchoice = "simple_c.gain_choice";
inline constexpr std::string_view i_simple_5fc_2erun = "simple_c.run";
inline constexpr std::string_view i_simple_5fc_2eclear = "simple_c.clear";
inline constexpr std::string_view i_simple_5fc_2eoutput = "simple_c.output";
inline constexpr std::string_view i_simple_5fc_2eon_5frun = "simple_c.on_run";
inline constexpr std::string_view i_simple_5fc_2eon_5fclear = "simple_c.on_clear";
inline constexpr std::string_view i_simple_5fc_2eprocessing = "simple_c.processing";
inline constexpr std::string_view i_simple_5fc_2esource = "simple_c.source";
inline constexpr std::string_view i_simple_5fc_2egain = "simple_c.gain";
inline constexpr std::string_view i_simple_5fc_2ecollector = "simple_c.collector";
inline constexpr std::string_view i_simple_5fc_2esource_5fto_5fgain = "simple_c.source_to_gain";
inline constexpr std::string_view i_simple_5fc_2egain_5fto_5fcollector = "simple_c.gain_to_collector";
} // namespace ids

namespace form_detail {
inline void append_i_simple_5fc_2econtrols(gui::Snapshot& view, std::uint64_t generation) {
    view.pages.push_back({"simple_c.controls", "Gain controls"});
    { // design widget simple_c.heading
        gui::Widget widget;
        widget.spec.key = {"simple_c.heading", generation};
        widget.spec.kind = gui::Kind::label;
        widget.spec.page = "simple_c.controls";
        widget.spec.parent = "";
        widget.spec.binding = "";
        widget.state.bounds = {12, 12, 496, 28};
        widget.state.label = "";
        widget.state.text = "Four samples through an ordinary C gain function";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget simple_c.gain_choice
        gui::Widget widget;
        widget.spec.key = {"simple_c.gain_choice", generation};
        widget.spec.kind = gui::Kind::choice;
        widget.spec.page = "simple_c.controls";
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
    { // design widget simple_c.run
        gui::Widget widget;
        widget.spec.key = {"simple_c.run", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "simple_c.controls";
        widget.spec.parent = "";
        widget.spec.binding = "simple_c.on_run";
        widget.state.bounds = {224, 50, 140, 32};
        widget.state.label = "Run samples";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget simple_c.clear
        gui::Widget widget;
        widget.spec.key = {"simple_c.clear", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "simple_c.controls";
        widget.spec.parent = "";
        widget.spec.binding = "simple_c.on_clear";
        widget.state.bounds = {376, 50, 100, 32};
        widget.state.label = "Clear";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget simple_c.output
        gui::Widget widget;
        widget.spec.key = {"simple_c.output", generation};
        widget.spec.kind = gui::Kind::text;
        widget.spec.page = "simple_c.controls";
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
    view.title = "Simple C starter";
    if (form_id == "simple_c.controls") {
        view.client_size = {520, 220};
        view.active_page = "simple_c.controls";
        form_detail::append_i_simple_5fc_2econtrols(view, generation);
        return view;
    }
    throw std::invalid_argument("Unknown generated form ID");
}

inline gui::Snapshot all_forms_snapshot(std::uint64_t generation = 1) {
    if (generation == 0) throw std::invalid_argument("Widget generation must be nonzero");
    gui::Snapshot view;
    view.revision = 1;
    view.title = "Simple C starter";
    view.client_size = {520, 220};
    view.active_page = "simple_c.controls";
    form_detail::append_i_simple_5fc_2econtrols(view, generation);
    return view;
}

} // namespace foundation::generated
