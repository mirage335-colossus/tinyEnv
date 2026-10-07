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
inline constexpr std::string_view i_demo_2epanel = "demo.panel";
inline constexpr std::string_view i_demo_2eheading = "demo.heading";
inline constexpr std::string_view i_demo_2edevice = "demo.device";
inline constexpr std::string_view i_demo_2erefresh = "demo.refresh";
inline constexpr std::string_view i_demo_2estart = "demo.start";
inline constexpr std::string_view i_demo_2estop = "demo.stop";
inline constexpr std::string_view i_demo_2estatus = "demo.status";
inline constexpr std::string_view i_demo_2eon_5frefresh = "demo.on_refresh";
inline constexpr std::string_view i_demo_2eon_5fstart = "demo.on_start";
inline constexpr std::string_view i_demo_2eon_5fstop = "demo.on_stop";
inline constexpr std::string_view i_demo_2eprocessing = "demo.processing";
inline constexpr std::string_view i_demo_2esource_5fa = "demo.source_a";
inline constexpr std::string_view i_demo_2esource_5fb = "demo.source_b";
inline constexpr std::string_view i_demo_2emixer = "demo.mixer";
inline constexpr std::string_view i_demo_2esum_5fsink = "demo.sum_sink";
inline constexpr std::string_view i_demo_2edifference_5fsink = "demo.difference_sink";
inline constexpr std::string_view i_demo_2etrace_5fsink = "demo.trace_sink";
inline constexpr std::string_view i_demo_2emetric_5fsink = "demo.metric_sink";
inline constexpr std::string_view i_demo_2ea = "demo.a";
inline constexpr std::string_view i_demo_2eb = "demo.b";
inline constexpr std::string_view i_demo_2esum = "demo.sum";
inline constexpr std::string_view i_demo_2edifference = "demo.difference";
inline constexpr std::string_view i_demo_2etrace = "demo.trace";
inline constexpr std::string_view i_demo_2emetric = "demo.metric";
} // namespace ids

namespace form_detail {
inline void append_i_demo_2epanel(gui::Snapshot& view, std::uint64_t generation) {
    view.pages.push_back({"demo.panel", "Receiver panel"});
    { // design widget demo.heading
        gui::Widget widget;
        widget.spec.key = {"demo.heading", generation};
        widget.spec.kind = gui::Kind::label;
        widget.spec.page = "demo.panel";
        widget.spec.parent = "";
        widget.spec.binding = "";
        widget.state.bounds = {12, 12, 620, 32};
        widget.state.label = "";
        widget.state.text = "Ordinary C++ events and unequal-rate MIMO streams";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget demo.device
        gui::Widget widget;
        widget.spec.key = {"demo.device", generation};
        widget.spec.kind = gui::Kind::choice;
        widget.spec.page = "demo.panel";
        widget.spec.parent = "";
        widget.spec.binding = "";
        widget.state.bounds = {12, 52, 620, 32};
        widget.state.label = "Input";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        widget.state.options.push_back({"simulated", "Simulated receiver", "simulated", true});
        view.widgets.push_back(std::move(widget));
    }
    { // design widget demo.refresh
        gui::Widget widget;
        widget.spec.key = {"demo.refresh", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "demo.panel";
        widget.spec.parent = "";
        widget.spec.binding = "demo.on_refresh";
        widget.state.bounds = {12, 94, 140, 32};
        widget.state.label = "Refresh inputs";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget demo.start
        gui::Widget widget;
        widget.spec.key = {"demo.start", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "demo.panel";
        widget.spec.parent = "";
        widget.spec.binding = "demo.on_start";
        widget.state.bounds = {162, 94, 100, 32};
        widget.state.label = "Start";
        widget.state.text = "";
        widget.state.enabled = true;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget demo.stop
        gui::Widget widget;
        widget.spec.key = {"demo.stop", generation};
        widget.spec.kind = gui::Kind::button;
        widget.spec.page = "demo.panel";
        widget.spec.parent = "";
        widget.spec.binding = "demo.on_stop";
        widget.state.bounds = {272, 94, 100, 32};
        widget.state.label = "Stop";
        widget.state.text = "";
        widget.state.enabled = false;
        widget.state.visible = true;
        widget.state.checked = false;
        view.widgets.push_back(std::move(widget));
    }
    { // design widget demo.status
        gui::Widget widget;
        widget.spec.key = {"demo.status", generation};
        widget.spec.kind = gui::Kind::text;
        widget.spec.page = "demo.panel";
        widget.spec.parent = "";
        widget.spec.binding = "";
        widget.spec.text_policy.multiline = true;
        widget.spec.text_policy.read_only = true;
        widget.spec.text_policy.max_bytes = 1048576;
        widget.state.wrap = gui::TextWrap::word;
        widget.state.bounds = {12, 140, 620, 120};
        widget.state.label = "Status";
        widget.state.text = "Ready. Sources and functions are ordinary editable C++ files.";
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
    view.title = "Minimal adopted project";
    if (form_id == "demo.panel") {
        view.client_size = {648, 300};
        view.active_page = "demo.panel";
        form_detail::append_i_demo_2epanel(view, generation);
        return view;
    }
    throw std::invalid_argument("Unknown generated form ID");
}

inline gui::Snapshot all_forms_snapshot(std::uint64_t generation = 1) {
    if (generation == 0) throw std::invalid_argument("Widget generation must be nonzero");
    gui::Snapshot view;
    view.revision = 1;
    view.title = "Minimal adopted project";
    view.client_size = {648, 300};
    view.active_page = "demo.panel";
    form_detail::append_i_demo_2epanel(view, generation);
    return view;
}

} // namespace foundation::generated
