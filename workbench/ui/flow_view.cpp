#include "flow_view.hpp"
#include "passive_diagram.hpp"
#include "theme.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

namespace tinyenv {
namespace {
using Color = theme::RasterColor;
constexpr auto palette = theme::dark_palette();
constexpr Color background = theme::rgb(palette.background);
constexpr Color paper = theme::rgb(palette.surface);
constexpr Color ink{91, 108, 130}, accent = theme::rgb(palette.accent);
constexpr Color loop_ink{122, 151, 194};
constexpr Color selected_fill = theme::rgb(palette.selection);
constexpr Color agent_fill{31, 44, 61}, critique_fill{43, 41, 56};
constexpr Color branch_fill{52, 45, 33}, repeat_fill{44, 39, 58};
constexpr Color conclude_fill{30, 49, 43};
constexpr std::size_t max_pixels = 2 * 1024 * 1024;
constexpr std::size_t max_nodes = 8192, max_edges = 32768;

bool finite(gui::Point p) { return std::isfinite(p.x) && std::isfinite(p.y); }

bool same_graph(const FlowGraph& a, const FlowGraph& b) {
    return a.width == b.width && a.height == b.height &&
        a.nodes.size() == b.nodes.size() && a.edges.size() == b.edges.size() &&
        std::equal(a.nodes.begin(), a.nodes.end(), b.nodes.begin(), [](const auto& x, const auto& y) {
            return x.id == y.id && x.kind == y.kind && x.line == y.line && x.label == y.label &&
                x.x == y.x && x.y == y.y && x.width == y.width && x.height == y.height;
        }) &&
        std::equal(a.edges.begin(), a.edges.end(), b.edges.begin(), [](const auto& x, const auto& y) {
            return x.from == y.from && x.to == y.to && x.label == y.label && x.loop == y.loop;
        });
}

// Only visible raster pixels are visited. The bitmap remains immutable after
// render and never retains FlowView or the caller's graph.
class Raster {
public:
    explicit Raster(gui::Rect viewport) : viewport_(viewport) {
        double scale = std::min(1.0, 2048.0 / std::max({1.0, viewport.width, viewport.height}));
        if (viewport.width * viewport.height * scale * scale > max_pixels)
            scale = std::sqrt(double(max_pixels) / (viewport.width * viewport.height));
        width_ = std::max(1u, static_cast<unsigned>(std::ceil(viewport.width * scale)));
        height_ = std::max(1u, static_cast<unsigned>(std::ceil(viewport.height * scale)));
        height_ = std::min(height_, static_cast<unsigned>(max_pixels / width_));
        pixels_.resize(std::size_t(width_) * height_ * 3);
        const auto stride = std::size_t(width_) * 3;
        for (std::size_t i = 0; i < stride; i += 3) {
            pixels_[i] = background[0]; pixels_[i + 1] = background[1]; pixels_[i + 2] = background[2];
        }
        for (unsigned y = 1; y < height_; ++y)
            std::copy_n(pixels_.data(), stride, pixels_.data() + std::size_t(y) * stride);
    }
    gui::Point local(gui::Point p) const {
        return {(p.x - viewport_.x) * width_ / viewport_.width,
                (p.y - viewport_.y) * height_ / viewport_.height};
    }
    void pixel(int x, int y, Color color) {
        if (x < 0 || y < 0 || x >= int(width_) || y >= int(height_)) return;
        const auto i = (std::size_t(y) * width_ + unsigned(x)) * 3;
        pixels_[i] = color[0]; pixels_[i + 1] = color[1]; pixels_[i + 2] = color[2];
    }
    void fill(gui::Rect area, Color color, bool diamond = false) {
        const auto visible = gui::intersect(area, viewport_);
        if (!gui::has_area(visible)) return;
        const auto a = local({visible.x, visible.y});
        const auto b = local({visible.x + visible.width, visible.y + visible.height});
        const auto center = local({area.x + area.width / 2, area.y + area.height / 2});
        const double half_width = area.width * width_ / viewport_.width / 2;
        const double half_height = area.height * height_ / viewport_.height / 2;
        const int left = std::max(0, int(std::floor(a.x)));
        const int right = std::min(int(width_), int(std::ceil(b.x)));
        const int top = std::max(0, int(std::floor(a.y)));
        const int bottom = std::min(int(height_), int(std::ceil(b.y)));
        if (!diamond && left < right && top < bottom) {
            auto* row = pixels_.data() + (std::size_t(top) * width_ + unsigned(left)) * 3;
            for (int x = 0; x < right - left; ++x) {
                row[std::size_t(x) * 3] = color[0]; row[std::size_t(x) * 3 + 1] = color[1];
                row[std::size_t(x) * 3 + 2] = color[2];
            }
            for (int y = top + 1; y < bottom; ++y)
                std::copy_n(row, std::size_t(right - left) * 3,
                            pixels_.data() + (std::size_t(y) * width_ + unsigned(left)) * 3);
            return;
        }
        for (int y = top; y < bottom; ++y)
            for (int x = left; x < right; ++x)
                if (!diamond || (std::abs((x + .5 - center.x) / half_width) +
                                 std::abs((y + .5 - center.y) / half_height) <= 1))
                    pixel(x, y, color);
    }
    void line(gui::Point a, gui::Point b, Color color, int thickness = 1) {
        a = local(a); b = local(b);
        const double dx = b.x - a.x, dy = b.y - a.y;
        double first = 0, last = 1;
        const auto clip = [&](double p, double q) {
            if (p == 0) return q >= 0;
            const double t = q / p;
            if (p < 0) { if (t > last) return false; first = std::max(first, t); }
            else { if (t < first) return false; last = std::min(last, t); }
            return true;
        };
        if (!clip(-dx, a.x) || !clip(dx, width_ - 1 - a.x) ||
            !clip(-dy, a.y) || !clip(dy, height_ - 1 - a.y)) return;
        int x = int(std::round(a.x + first * dx)), y = int(std::round(a.y + first * dy));
        const int end_x = int(std::round(a.x + last * dx)), end_y = int(std::round(a.y + last * dy));
        const int sx = x < end_x ? 1 : -1, sy = y < end_y ? 1 : -1;
        const int ax = std::abs(end_x - x), ay = -std::abs(end_y - y);
        int residual = ax + ay;
        for (;;) {
            for (int yy = 0; yy < thickness; ++yy)
                for (int xx = 0; xx < thickness; ++xx) pixel(x + xx, y + yy, color);
            if (x == end_x && y == end_y) break;
            const int twice = 2 * residual;
            if (twice >= ay) { residual += ay; x += sx; }
            if (twice <= ax) { residual += ax; y += sy; }
        }
    }
    void frame(gui::Rect area, Color color, bool diamond, int thickness) {
        std::array<gui::Point, 4> points;
        if (diamond)
            points = {{{area.x + area.width / 2, area.y},
                       {area.x + area.width, area.y + area.height / 2},
                       {area.x + area.width / 2, area.y + area.height},
                       {area.x, area.y + area.height / 2}}};
        else
            points = {{{area.x, area.y}, {area.x + area.width, area.y},
                       {area.x + area.width, area.y + area.height}, {area.x, area.y + area.height}}};
        for (std::size_t i = 0; i < points.size(); ++i)
            line(points[i], points[(i + 1) % points.size()], color, thickness);
    }
    gui::BitmapSource source() && {
        const auto width = width_, height = height_;
        auto bytes = std::make_shared<const std::vector<std::uint8_t>>(std::move(pixels_));
        return gui::BitmapSource([bytes, width, height](const gui::BitmapRequest& request,
                                                       const gui::BitmapSink& sink) {
            if (request.width > 32768 || request.height > 32768 ||
                std::size_t(request.width) * request.height > 128 * 1024 * 1024)
                throw std::length_error("Flow canvas sample grid exceeds limits");
            // Native RGB presentations usually request our exact raster grid.
            // PixelBlock is borrowed for this synchronous sink call, so the
            // immutable frame can supply the requested rows without resampling.
            if (request.format == gui::PixelFormat::rgb24 && request.width == width && request.height == height) {
                const auto stride = std::size_t(width) * 3;
                const auto start = std::size_t(request.damage.y) * stride + std::size_t(request.damage.x) * 3;
                sink(request.damage.x, request.damage.y,
                     {request.damage.width, request.damage.height, stride, request.format,
                      std::span<const std::uint8_t>(*bytes).subspan(start)});
                return;
            }
            std::vector<std::uint8_t> row(gui::pixel_row_bytes(request.damage.width, request.format));
            for (unsigned y = 0; y < request.damage.height; ++y) {
                std::fill(row.begin(), row.end(), 0);
                const auto sy = std::min(height - 1, static_cast<unsigned>(
                    (double(request.damage.y + y) + .5) * height / request.height));
                for (unsigned x = 0; x < request.damage.width; ++x) {
                    const auto sx = std::min(width - 1, static_cast<unsigned>(
                        (double(request.damage.x + x) + .5) * width / request.width));
                    const auto i = (std::size_t(sy) * width + sx) * 3;
                    if (request.format == gui::PixelFormat::rgb24) {
                        const auto target = std::size_t(x) * 3;
                        row[target] = (*bytes)[i]; row[target + 1] = (*bytes)[i + 1]; row[target + 2] = (*bytes)[i + 2];
                    }
                    else {
                        const auto gray = std::uint8_t((77u * (*bytes)[i] + 150u * (*bytes)[i + 1] +
                                                       29u * (*bytes)[i + 2] + 128u) / 256u);
                        if (request.format == gui::PixelFormat::gray8) row[x] = gray;
                        else if (gray >= 128) row[x / 8] |= std::uint8_t(0x80u >> (x % 8));
                    }
                }
                sink(request.damage.x, request.damage.y + y,
                     {request.damage.width, 1, row.size(), request.format, row});
            }
        });
    }
private:
    gui::Rect viewport_;
    unsigned width_ = 1, height_ = 1;
    std::vector<std::uint8_t> pixels_;
};

gui::Widget label(std::string id, std::string text, gui::Rect bounds,
                  gui::Rect viewport, double size, gui::Tone tone = gui::Tone::normal,
                  bool bold = false) {
    gui::Widget widget;
    widget.spec.key = {std::move(id), 1}; widget.spec.kind = gui::Kind::label;
    widget.spec.parent = "wb.center";
    widget.state.bounds = gui::intersect(bounds, viewport);
    widget.state.text = passive_diagram_safe_text(text, 512); widget.state.accessible_name = widget.state.text;
    widget.state.font = {size, bold, tone};
    widget.state.wrap = gui::TextWrap::word;
    return widget;
}

Color fill_color(FlowKind kind) {
    switch (kind) {
    case FlowKind::agent: return agent_fill;
    case FlowKind::critique: return critique_fill;
    case FlowKind::branch: return branch_fill;
    case FlowKind::repeat: return repeat_fill;
    case FlowKind::conclude: return conclude_fill;
    default: return paper;
    }
}
} // namespace

void FlowView::set_view(double zoom, gui::Point pan) {
    if (!std::isfinite(zoom) || zoom < .2 || zoom > 4 || !finite(pan) ||
        std::abs(pan.x) > gui::coordinate_limit || std::abs(pan.y) > gui::coordinate_limit)
        throw std::invalid_argument("Invalid flow canvas view");
    if (zoom_ == zoom && pan_ == pan) return;
    zoom_ = zoom; pan_ = pan;
    // The previous hit geometry belongs to the previous view transform.
    hits_.clear();
}

bool FlowView::zoom_at(double wheel_y, gui::Point anchor) {
    if (!std::isfinite(wheel_y) || wheel_y == 0 || !finite(anchor) ||
        !gui::has_area(viewport_) || !gui::contains(viewport_, anchor)) return false;
    const double next = std::clamp(zoom_ * std::pow(1.25, std::clamp(wheel_y, -16.0, 16.0)), .2, 2.0);
    if (next == zoom_) return false;
    const auto point = view_to_model(anchor);
    const gui::Point pan{
        std::clamp(point.x - (anchor.x - viewport_.x - 18) / next, -gui::coordinate_limit, gui::coordinate_limit),
        std::clamp(point.y - (anchor.y - viewport_.y - 18) / next, -gui::coordinate_limit, gui::coordinate_limit)};
    cancel_drag();
    set_view(next, pan);
    return true;
}

void FlowView::fit(const FlowGraph& graph, gui::Rect viewport) {
    if (!gui::valid_rect(viewport)) throw std::invalid_argument("Invalid flow canvas viewport");
    if (graph.nodes.size() > max_nodes || graph.edges.size() > max_edges)
        throw std::length_error("Flow canvas graph exceeds limits");
    cancel_drag();viewport_ = viewport; hits_.clear();
    if (graph.nodes.empty() || !gui::has_area(viewport)) { reset_view(); return; }
    double left = std::numeric_limits<double>::max(), top = left;
    double right = std::numeric_limits<double>::lowest(), bottom = right;
    for (const auto& node : graph.nodes) {
        const gui::Rect area{node.x, node.y, node.width, node.height};
        if (!gui::valid_rect(area) || !gui::has_area(area))
            throw std::invalid_argument("Invalid flow canvas node geometry");
        left = std::min(left, area.x); top = std::min(top, area.y);
        right = std::max(right, area.x + area.width); bottom = std::max(bottom, area.y + area.height);
    }
    // Include the return-arrow lane and its label in the visible graph extent.
    if (std::any_of(graph.edges.begin(), graph.edges.end(), [](const auto& edge) { return edge.loop; }))
        right += 124;
    const double available_width = std::max(1.0, viewport.width - 36);
    const double available_height = std::max(1.0, viewport.height - 36);
    const double width = right - left, height = bottom - top;
    const double scale = std::clamp(std::min(available_width / width, available_height / height), .2, 1.0);
    set_view(scale, {left - std::max(0.0, (available_width - width * scale) / 2) / scale,
                     top - std::max(0.0, (available_height - height * scale) / 2) / scale});
}

gui::Point FlowView::model_to_view(gui::Point point) const {
    return {viewport_.x + 18 + (point.x - pan_.x) * zoom_,
            viewport_.y + 18 + (point.y - pan_.y) * zoom_};
}

gui::Point FlowView::view_to_model(gui::Point point) const {
    return {(point.x - viewport_.x - 18) / zoom_ + pan_.x,
            (point.y - viewport_.y - 18) / zoom_ + pan_.y};
}

std::optional<std::uint64_t> FlowView::hit_test(gui::Point point) const {
    if (!finite(point) || !gui::contains(viewport_, point)) return {};
    for (auto it = hits_.rbegin(); it != hits_.rend(); ++it) {
        const auto area = it->bounds;
        if (!gui::contains(area, point)) continue;
        if (!it->diamond || std::abs((point.x - area.x - area.width / 2) / (area.width / 2)) +
                            std::abs((point.y - area.y - area.height / 2) / (area.height / 2)) <= 1)
            return it->id;
    }
    return {};
}

bool FlowView::begin_drag(std::uint64_t owner, gui::Point position) {
    if (!owner || drag_ || !finite(position) || !gui::contains(viewport_, position)) return false;
    drag_ = Drag{owner, position, pan_, hit_test(position)};
    return true;
}

bool FlowView::drag_to(std::uint64_t owner, gui::Point position) {
    if (!drag_ || drag_->owner != owner || !finite(position)) return false;
    const auto dx = position.x - drag_->start.x, dy = position.y - drag_->start.y;
    if (!drag_->moved && std::hypot(dx, dy) < 4) return false;
    drag_->moved = true;
    // Pointer coordinates are in screen space; pan is in model space. Keep a
    // dragged viewport within the same finite bounds as other navigation.
    const gui::Point pan{std::clamp(drag_->pan.x - dx / zoom_, -gui::coordinate_limit, gui::coordinate_limit),
                         std::clamp(drag_->pan.y - dy / zoom_, -gui::coordinate_limit, gui::coordinate_limit)};
    if (pan_ == pan) return false;
    set_view(zoom_, pan);
    return true;
}

std::optional<std::uint64_t> FlowView::end_drag(std::uint64_t owner, gui::Point position) {
    if (!drag_ || drag_->owner != owner) return {};
    (void)drag_to(owner, position);
    const auto gesture = std::exchange(drag_, {});
    if (!finite(position) || gesture->moved || !gesture->node || hit_test(position) != gesture->node) return {};
    return gesture->node;
}

bool FlowView::cancel_drag(std::uint64_t owner) noexcept {
    if (!drag_ || drag_->owner != owner) return false;
    drag_.reset();return true;
}

std::vector<gui::Widget> FlowView::render(
    const FlowGraph& graph, gui::Rect viewport, std::uint64_t selected,
    const std::vector<PseudocodeDiagnostic>& diagnostics) {
    if (!gui::valid_rect(viewport)) throw std::invalid_argument("Invalid flow canvas viewport");
    if (graph.nodes.size() > max_nodes || graph.edges.size() > max_edges)
        throw std::length_error("Flow canvas graph exceeds limits");
    if(viewport_ != viewport)cancel_drag();
    viewport_ = viewport; hits_.clear();
    std::vector<gui::Widget> result, labels;
    if (!gui::has_area(viewport)) { frame_.reset(); return result; }
    if (frame_ && frame_->viewport == viewport && frame_->zoom == zoom_ && frame_->pan == pan_ &&
        frame_->selected == selected && frame_->diagnostics == diagnostics && same_graph(frame_->graph, graph)) {
        hits_ = frame_->hits;
        return frame_->widgets;
    }
    Raster raster(viewport);
    std::map<std::uint64_t, gui::Rect> areas;
    for (const auto& node : graph.nodes) {
        const gui::Rect model{node.x, node.y, node.width, node.height};
        if (!gui::valid_rect(model) || !gui::has_area(model) || node.id == 0 || areas.contains(node.id))
            throw std::invalid_argument("Invalid flow canvas node geometry or identity");
        const auto origin = model_to_view({node.x, node.y});
        const gui::Rect area{origin.x, origin.y, node.width * zoom_, node.height * zoom_};
        areas.emplace(node.id, area);
        hits_.push_back({node.id, area, node.kind == FlowKind::branch});
    }
    std::size_t edge_index = 0;
    for (const auto& edge : graph.edges) {
        const auto from_it = areas.find(edge.from), to_it = areas.find(edge.to);
        if (from_it == areas.end() || to_it == areas.end()) continue;
        const auto from = from_it->second, to = to_it->second;
        std::vector<gui::Point> points;
        gui::Rect label_area;
        const bool loop = edge.loop || to.y < from.y;
        if (loop) {
            const double lane = std::max(from.x + from.width, to.x + to.width) + 24 * zoom_;
            const auto start = gui::Point{from.x + from.width, from.y + from.height / 2};
            const auto end = gui::Point{to.x + to.width, to.y + to.height / 2};
            points = {start, {lane, start.y}, {lane, end.y}, end};
            label_area = {lane + 4, (start.y + end.y) / 2 - 10, 90 * zoom_, 32 * zoom_};
        } else {
            const auto start = gui::Point{from.x + from.width / 2, from.y + from.height};
            const auto end = gui::Point{to.x + to.width / 2, to.y};
            const double middle = (start.y + end.y) / 2;
            points = {start, {start.x, middle}, {end.x, middle}, end};
            label_area = {(start.x + end.x) / 2 + 5, middle - 17 * zoom_,
                          120 * zoom_, 28 * zoom_};
        }
        for (std::size_t i = 1; i < points.size(); ++i)
            raster.line(points[i - 1], points[i], loop ? loop_ink : ink, loop ? 2 : 1);
        const auto end = points.back();
        const auto before = points[points.size() - 2];
        const double angle = std::atan2(end.y - before.y, end.x - before.x);
        const double length = std::clamp(7 * zoom_, 4.0, 14.0);
        for (const double delta : {-.5, .5})
            raster.line({end.x - length * std::cos(angle + delta),
                         end.y - length * std::sin(angle + delta)}, end, loop ? loop_ink : ink);
        if (!edge.label.empty() && gui::has_area(gui::intersect(label_area, viewport)))
            labels.push_back(label("wb.flow.edge." + std::to_string(edge_index), edge.label,
                                   label_area, viewport, std::clamp(11 * zoom_, 8.0, 20.0),
                                   gui::Tone::muted));
        ++edge_index;
    }
    for (const auto& node : graph.nodes) {
        const auto area = areas.at(node.id);
        const bool is_selected = node.id == selected, diamond = node.kind == FlowKind::branch;
        raster.fill(area, is_selected ? selected_fill : fill_color(node.kind), diamond);
        raster.frame(area, is_selected ? accent : ink, diamond, is_selected ? 2 : 1);
        if (!gui::has_area(gui::intersect(area, viewport))) continue;
        // A diamond's rectangular center is the safe region for its text.
        const double inset = diamond ? area.width * .25 : 9 * zoom_;
        const double top = diamond ? area.height * .25 : 7 * zoom_;
        const gui::Rect text_area{area.x + inset, area.y + top,
                                 std::max(1.0, area.width - 2 * inset),
                                 std::max(1.0, area.height - 2 * top)};
        labels.push_back(label("wb.flow.node." + std::to_string(node.id), "[" + std::to_string(node.id) + "] " + node.label,
                               text_area, viewport, std::clamp(12 * zoom_, 8.0, 24.0),
                               is_selected ? gui::Tone::accent : gui::Tone::normal, true));
        labels.back().state.accessible_name = flow_kind_name(node.kind) + ", line " +
            std::to_string(node.line) + ": " + passive_diagram_safe_text(node.label, 512);
    }
    if (graph.nodes.empty()) {
        std::string message = diagnostics.empty()
            ? "Add pseudocode to see its flow. Select a node to edit its properties."
            : "The flow is unavailable until the pseudocode is valid.";
        labels.push_back(label("wb.flow.empty", std::move(message),
                               {viewport.x + 24, viewport.y + 24, std::max(1.0, viewport.width - 48), 52},
                               viewport, 13, gui::Tone::muted));
    }
    for (std::size_t i = 0; i < std::min<std::size_t>(diagnostics.size(), 8); ++i) {
        const auto& diagnostic = diagnostics[i];
        const gui::Rect area{viewport.x + 24, viewport.y + 84 + i * 42,
                             std::max(1.0, viewport.width - 48), 40};
        if (!gui::has_area(gui::intersect(area, viewport))) break;
        labels.push_back(label("wb.flow.diagnostic." + std::to_string(i),
                               "Line " + std::to_string(diagnostic.line) + ": " + diagnostic.message,
                               area, viewport, 12, gui::Tone::error));
    }
    gui::Widget canvas;
    canvas.spec.key = {"wb.flow.canvas", 1}; canvas.spec.kind = gui::Kind::bitmap;
    canvas.spec.parent = "wb.center"; canvas.spec.pointer_input = true;
    canvas.state.bounds = viewport; canvas.state.accessible_name = "Pseudocode flow canvas. Scroll to zoom; drag to pan; click a block to select.";
    canvas.state.bitmap = {"tinyenv.flow", ++revision_, std::move(raster).source()};
    result.push_back(std::move(canvas));
    result.insert(result.end(), std::make_move_iterator(labels.begin()), std::make_move_iterator(labels.end()));
    frame_ = Frame{graph, viewport, zoom_, pan_, selected, diagnostics, result, hits_};
    return result;
}

} // namespace tinyenv
