#pragma once

#include "../core/pseudocode.hpp"
#include <gui/contract.hpp>
#include <cstdint>
#include <optional>
#include <vector>

namespace tinyenv {

// Shared UI geometry and drawing; retained bitmap snapshots own their bytes.
class FlowView {
public:
    std::vector<gui::Widget> render(
        const FlowGraph&, gui::Rect viewport, std::uint64_t selected = 0,
        const std::vector<PseudocodeDiagnostic>& diagnostics = {});
    std::optional<std::uint64_t> hit_test(gui::Point) const;
    void set_view(double zoom, gui::Point pan = {});
    // Positive wheel detents zoom in, retaining the model point under the
    // pointer. Invalid/outside events and already-clamped views are inert.
    bool zoom_at(double wheel_y, gui::Point anchor);
    void fit(const FlowGraph&, gui::Rect viewport);
    void reset_view() { set_view(1, {}); }
    double zoom() const { return zoom_; }
    gui::Point pan() const { return pan_; }
    gui::Point model_to_view(gui::Point) const;
    gui::Point view_to_model(gui::Point) const;
    // Physical drags pan after a small screen-space threshold. A stationary
    // release can select its original node; dragging never changes the graph.
    bool begin_drag(std::uint64_t owner, gui::Point position);
    bool drag_to(std::uint64_t owner, gui::Point position);
    std::optional<std::uint64_t> end_drag(std::uint64_t owner, gui::Point position);
    void cancel_drag() noexcept { drag_.reset(); }
    bool cancel_drag(std::uint64_t owner) noexcept;
    bool dragging() const noexcept { return drag_.has_value(); }
private:
    struct Hit { std::uint64_t id; gui::Rect bounds; bool diamond = false; };
    gui::Rect viewport_;
    double zoom_ = 1;
    gui::Point pan_;
    std::vector<Hit> hits_;
    struct Drag {
        std::uint64_t owner;
        gui::Point start, pan;
        std::optional<std::uint64_t> node;
        bool moved = false;
    };
    std::optional<Drag> drag_;
    std::uint64_t revision_ = 0;
    // Retain only the last immutable frame. Unrelated UI publications preserve
    // its bitmap identity and do not rebuild the graph's pixels or hit regions.
    struct Frame {
        FlowGraph graph;
        gui::Rect viewport;
        double zoom;
        gui::Point pan;
        std::uint64_t selected;
        std::vector<PseudocodeDiagnostic> diagnostics;
        std::vector<gui::Widget> widgets;
        std::vector<Hit> hits;
    };
    std::optional<Frame> frame_;
};

} // namespace tinyenv
