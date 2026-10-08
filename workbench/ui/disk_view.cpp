#include "disk_view.hpp"
#include "theme.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <iomanip>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace tinyenv {
namespace {

using Color = theme::RasterColor;
constexpr auto theme_palette = theme::dark_palette();
constexpr Color background = theme::rgb(theme_palette.surface);
constexpr Color center_color = theme::rgb(theme_palette.surface);
constexpr Color ring_line{59, 70, 85}, selected_edge = theme::rgb(theme_palette.accent);
constexpr std::array<Color, 13> palette{{
    {77, 126, 179}, {58, 141, 131}, {165, 118, 65}, {126, 99, 162},
    {165, 86, 111}, {98, 135, 78}, {68, 133, 156}, {151, 133, 63},
    {96, 107, 164}, {164, 101, 68}, {144, 91, 147}, {64, 128, 100},
    {110, 122, 140}
}};
constexpr std::size_t maximum_named_sectors = palette.size() - 1;
constexpr double pi = 3.141592653589793238462643383279502884;
constexpr double turn = 2 * pi;

double angle(gui::Point point, gui::Point center) {
    double value = std::atan2(point.y - center.y, point.x - center.x) + pi / 2;
    if (value < 0) value += turn;
    if (value >= turn) value = 0;
    return value;
}

Color shade(Color color, double factor) {
    for (auto& channel : color)
        channel = static_cast<std::uint8_t>(std::clamp(channel * factor, 0.0, 255.0));
    return color;
}

std::string bytes_text(long double bytes) {
    constexpr std::array<const char*, 7> units{"B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"};
    std::size_t unit = 0;
    while (bytes >= 1024 && unit + 1 < units.size()) { bytes /= 1024; ++unit; }
    std::ostringstream out;
    out << std::fixed << std::setprecision(unit == 0 ? 0 : bytes >= 10 ? 1 : 2)
        << bytes << ' ' << units[unit];
    return out.str();
}

std::string display_text(std::string_view raw, std::size_t limit) {
    std::string text;
    std::size_t offset = 0;
    while (offset < raw.size() && text.size() < limit) {
        const auto first = static_cast<unsigned char>(raw[offset]);
        const std::size_t count = first < 0x80 ? 1 : first >= 0xc2 && first <= 0xdf ? 2 :
            first >= 0xe0 && first <= 0xef ? 3 : first >= 0xf0 && first <= 0xf4 ? 4 : 0;
        if (count && count <= raw.size() - offset && gui::valid_utf8(raw.substr(offset, count))) {
            if (count > limit - text.size()) break;
            if (first < 32 || first == 127) text += '?';
            else text.append(raw.substr(offset, count));
            offset += count;
        } else { text += '?'; ++offset; }
    }
    if (offset < raw.size()) text += "...";
    return text;
}

std::string short_name(const std::string& path, std::size_t limit) {
    auto end = path.size();
    while (end > 1 && (path[end - 1] == '/' || path[end - 1] == '\\')) --end;
    const auto separator = end ? path.find_last_of("/\\", end - 1) : std::string::npos;
    auto text = std::string_view(path).substr(separator == std::string::npos ? 0 : separator + 1,
                           end - (separator == std::string::npos ? 0 : separator + 1));
    if (text.empty()) text = path.empty() ? std::string_view("Unnamed") : std::string_view(path);
    return display_text(text, limit);
}

gui::Widget label(std::string id, std::string text, gui::Rect bounds,
                  gui::Rect viewport, double size = 12, bool bold = false,
                  gui::Tone tone = gui::Tone::normal) {
    gui::Widget widget;
    widget.spec.key = {std::move(id), 1};
    widget.spec.kind = gui::Kind::label;
    widget.spec.parent = "wb.left";
    widget.state.bounds = gui::intersect(bounds, viewport);
    widget.state.text = std::move(text);
    widget.state.accessible_name = widget.state.text;
    widget.state.font = {size, bold, tone};
    widget.state.wrap = gui::TextWrap::word;
    return widget;
}

// Owned RGB storage is at most 2048 x 2048 (12 MiB), even for a very large
// logical viewport. Sampling never mutates it or allocates a second image.
class Raster {
public:
    explicit Raster(gui::Rect viewport) : viewport_(viewport) {
        const double scale = std::min(1.0, 2048.0 / std::max({1.0, viewport.width, viewport.height}));
        width_ = std::clamp(static_cast<unsigned>(std::ceil(viewport.width * scale)), 1u, 2048u);
        height_ = std::clamp(static_cast<unsigned>(std::ceil(viewport.height * scale)), 1u, 2048u);
        pixels_.resize(std::size_t(width_) * height_ * 3);
        for (std::size_t i = 0; i < pixels_.size(); i += 3)
            std::copy(background.begin(), background.end(), pixels_.begin() + i);
    }

    template<class Paint>
    void paint(Paint&& color_at) {
        for (unsigned y = 0; y < height_; ++y)
            for (unsigned x = 0; x < width_; ++x) {
                const gui::Point point{
                    viewport_.x + (x + .5) * viewport_.width / width_,
                    viewport_.y + (y + .5) * viewport_.height / height_};
                const Color color = color_at(point);
                const auto offset = (std::size_t(y) * width_ + x) * 3;
                std::copy(color.begin(), color.end(), pixels_.begin() + offset);
            }
    }

    void fill(gui::Rect bounds, Color color) {
        bounds = gui::intersect(bounds, viewport_);
        if (!gui::has_area(bounds)) return;
        const auto local_x = [&](double x) { return (x - viewport_.x) * width_ / viewport_.width; };
        const auto local_y = [&](double y) { return (y - viewport_.y) * height_ / viewport_.height; };
        const auto left = std::clamp(int(std::floor(local_x(bounds.x))), 0, int(width_));
        const auto right = std::clamp(int(std::ceil(local_x(bounds.x + bounds.width))), 0, int(width_));
        const auto top = std::clamp(int(std::floor(local_y(bounds.y))), 0, int(height_));
        const auto bottom = std::clamp(int(std::ceil(local_y(bounds.y + bounds.height))), 0, int(height_));
        for (int y = top; y < bottom; ++y)
            for (int x = left; x < right; ++x) {
                const auto offset = (std::size_t(y) * width_ + unsigned(x)) * 3;
                std::copy(color.begin(), color.end(), pixels_.begin() + offset);
            }
    }

    gui::BitmapSource source() && {
        const auto width = width_, height = height_;
        auto pixels = std::make_shared<const std::vector<std::uint8_t>>(std::move(pixels_));
        return gui::BitmapSource([pixels, width, height](const gui::BitmapRequest& request, const gui::BitmapSink& sink) {
            if (request.width > 32768 || request.height > 32768 ||
                std::size_t(request.width) * request.height > 128 * 1024 * 1024)
                throw std::length_error("Disk chart sample grid exceeds limits");
            std::vector<std::uint8_t> row(gui::pixel_row_bytes(request.damage.width, request.format));
            for (unsigned y = 0; y < request.damage.height; ++y) {
                std::fill(row.begin(), row.end(), 0);
                const auto sy = std::min(height - 1, static_cast<unsigned>((double(request.damage.y + y) + .5) * height / request.height));
                for (unsigned x = 0; x < request.damage.width; ++x) {
                    const auto sx = std::min(width - 1, static_cast<unsigned>((double(request.damage.x + x) + .5) * width / request.width));
                    const auto offset = (std::size_t(sy) * width + sx) * 3;
                    if (request.format == gui::PixelFormat::rgb24)
                        std::copy_n(pixels->data() + offset, 3, row.data() + std::size_t(x) * 3);
                    else {
                        const auto gray = std::uint8_t((77u * (*pixels)[offset] + 150u * (*pixels)[offset + 1] + 29u * (*pixels)[offset + 2] + 128u) / 256u);
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
    unsigned width_{1}, height_{1};
    std::vector<std::uint8_t> pixels_;
};

} // namespace

std::vector<gui::Widget> DiskView::render(const std::vector<DiskSector>& entries,
                                       gui::Rect viewport, const std::string& selected) {
    if (!gui::valid_rect(viewport)) throw std::invalid_argument("Invalid disk chart viewport");
    if (revision_ == std::numeric_limits<std::uint64_t>::max())
        throw std::overflow_error("Disk chart revision exhausted");
    viewport_ = viewport;
    sectors_.clear();
    legend_.clear();
    inner_radius_ = outer_radius_ = 0;
    std::vector<gui::Widget> widgets;
    if (!gui::has_area(viewport)) return widgets;

    struct Entry { std::string path; long double bytes{}; bool directory{}, aggregate{}; };
    std::vector<Entry> shown;
    long double total = 0, other = 0;
    std::size_t omitted = 0;
    for (const auto& entry : entries) {
        total += static_cast<long double>(entry.bytes);
        if (entry.bytes == 0) continue;
        if (shown.size() < maximum_named_sectors)
            shown.push_back({entry.path, static_cast<long double>(entry.bytes), entry.directory, false});
        else { other += static_cast<long double>(entry.bytes); ++omitted; }
    }
    if (other > 0) shown.push_back({{}, other, false, true});

    const double padding = std::min(14.0, viewport.width / 12);
    const double available_width = std::max(0.0, viewport.width - 2 * padding);
    const double heading_height = std::min(28.0, viewport.height / 8);
    const double diameter = std::max(0.0, std::min(available_width, viewport.height * .46));
    outer_radius_ = diameter / 2;
    inner_radius_ = outer_radius_ * .38;
    center_ = {viewport.x + viewport.width / 2,
               viewport.y + heading_height + outer_radius_ + 8};
    if (center_.y + outer_radius_ > viewport.y + viewport.height)
        center_.y = viewport.y + viewport.height / 2;

    double next = 0;
    if (total > 0) {
        long double cumulative = 0;
        for (const auto& entry : shown) {
            cumulative += entry.bytes;
            // Cumulative ratios keep ends monotonic even when a category is
            // smaller than the rounding error of the preceding large entries.
            const double end = std::clamp(static_cast<double>(cumulative / total * turn), next, turn);
            sectors_.push_back({entry.path, next, end});
            next = end;
        }
        // Avoid a rounding seam between the first and last categories.
        if (!sectors_.empty()) sectors_.back().end = turn;
    }

    Raster raster(viewport);
    raster.paint([&](gui::Point point) -> Color {
        const double distance = std::hypot(point.x - center_.x, point.y - center_.y);
        if (outer_radius_ <= 0 || distance > outer_radius_) return background;
        if (distance < inner_radius_) return center_color;
        if (shown.empty()) return ring_line;
        const double direction = angle(point, center_);
        const auto iterator = std::upper_bound(sectors_.begin(), sectors_.end(), direction,
            [](double value, const Sector& sector) { return value < sector.end; });
        if (iterator == sectors_.end()) return background;
        const auto index = static_cast<std::size_t>(iterator - sectors_.begin());
        const auto& entry = shown[index];
        // Concentric shading gives the familiar radial usage view. These bands
        // are decoration; the input contains immediate entries, not a subtree.
        const double fraction = distance / outer_radius_;
        const bool is_selected = !selected.empty() && !entry.aggregate && entry.path == selected;
        const double edge = std::min(direction - iterator->start, iterator->end - direction) * distance;
        if (is_selected && (distance > outer_radius_ - 2 || distance < inner_radius_ + 2 || edge < 1.5))
            return selected_edge;
        if (sectors_.size() > 1 && edge < .7) return background;
        if (std::abs(fraction - .62) * outer_radius_ < .65 ||
            std::abs(fraction - .82) * outer_radius_ < .65) return background;
        auto color = palette[entry.aggregate ? palette.size() - 1 : index];
        const double factor = fraction < .62 ? 1.13 : fraction < .82 ? 1 : .88;
        if (is_selected) color = shade(color, 1.08);
        return shade(color, factor);
    });

    std::vector<gui::Widget> labels;
    labels.push_back(label("wb.disk.title", "Disk usage",
        {viewport.x + padding, viewport.y + 2, available_width, heading_height}, viewport, 14, true));
    const double center_width = inner_radius_ * 1.85;
    if (center_width >= 40) {
        const double font_size = center_width >= 115 ? 15 : 11;
        const auto total_text = bytes_text(total);
        const double total_width = std::min(center_width, total_text.size() * font_size * .75);
        labels.push_back(label("wb.disk.total", total_text,
            {center_.x - total_width / 2, center_.y - 13, total_width, 24}, viewport, font_size, true));
        labels.push_back(label("wb.disk.total.caption", "total",
            {center_.x - 15, center_.y + 10, 35, 20}, viewport, 11, false, gui::Tone::muted));
    }

    const double legend_top = center_.y + outer_radius_ + 15;
    const double available_height = std::max(0.0, viewport.y + viewport.height - padding - legend_top);
    constexpr double row_height = 56;
    const auto capacity = static_cast<std::size_t>(available_height / row_height);
    const auto rows = std::min(capacity, shown.size());
    for (std::size_t i = 0; i < rows; ++i) {
        const auto& entry = shown[i];
        const bool is_selected = !selected.empty() && !entry.aggregate && entry.path == selected;
        const double y = legend_top + i * row_height;
        const auto color = palette[entry.aggregate ? palette.size() - 1 : i];
        raster.fill({viewport.x + padding, y + 5, 10, 10}, color);
        if (is_selected) raster.fill({viewport.x + padding - 4, y + 2, 2, row_height - 8}, selected_edge);
        std::ostringstream percent;
        percent << std::fixed << std::setprecision(1) << (total > 0 ? entry.bytes / total * 100 : 0) << '%';
        const auto name_limit = static_cast<std::size_t>(std::clamp((available_width - 17) / 7 * 1.7, 8.0, 160.0));
        auto name = entry.aggregate ? "Other (" + std::to_string(omitted) + " entries)" : short_name(entry.path, name_limit);
        if (entry.directory) name += '/';
        auto widget = label("wb.disk.legend." + std::to_string(i),
            std::move(name),
            {viewport.x + padding + 17, y, std::max(0.0, available_width - 17), 32},
            viewport, 12, is_selected, is_selected ? gui::Tone::accent : gui::Tone::normal);
        if (!entry.aggregate) {
            widget.state.accessible_name = display_text(entry.path, 1024) + (entry.directory ? "/, " : ", ") +
                bytes_text(entry.bytes) + ", " + percent.str();
            legend_.push_back({entry.path, {viewport.x + padding, y, available_width, row_height}});
        }
        labels.push_back(std::move(widget));
        labels.push_back(label("wb.disk.legend.size." + std::to_string(i),
            bytes_text(entry.bytes) + "  " + percent.str(),
            {viewport.x + padding + 17, y + 32, std::max(0.0, available_width - 17), 20},
            viewport, 11, false, gui::Tone::muted));
    }
    if (shown.empty()) {
        labels.push_back(label("wb.disk.empty", "No file data in this directory",
            {viewport.x + padding, legend_top, available_width, 44}, viewport, 12, false, gui::Tone::muted));
    } else if (rows < shown.size() && available_height - rows * row_height >= 18) {
        labels.push_back(label("wb.disk.more", std::to_string(shown.size() - rows) + " more chart entries",
            {viewport.x + padding, legend_top + rows * row_height, available_width, 20}, viewport, 11, false, gui::Tone::muted));
    }

    gui::Widget canvas;
    canvas.spec.key = {"wb.disk.canvas", 1};
    canvas.spec.kind = gui::Kind::bitmap;
    canvas.spec.parent = "wb.left";
    canvas.spec.pointer_input = true;
    canvas.state.bounds = viewport;
    canvas.state.accessible_name = "Disk usage chart, " + bytes_text(total) + " total. Select a sector or legend entry to open it.";
    canvas.state.bitmap = {"wb.disk.canvas", ++revision_, std::move(raster).source()};
    widgets.push_back(std::move(canvas));
    for (auto& widget : labels)
        if (gui::has_area(widget.state.bounds)) widgets.push_back(std::move(widget));
    return widgets;
}

std::optional<std::string> DiskView::hit_test(gui::Point point) const {
    if (!std::isfinite(point.x) || !std::isfinite(point.y) || !gui::contains(viewport_, point)) return {};
    for (const auto& entry : legend_)
        if (gui::contains(entry.bounds, point) && !entry.path.empty()) return entry.path;
    const double distance = std::hypot(point.x - center_.x, point.y - center_.y);
    if (distance < inner_radius_ || distance > outer_radius_ || sectors_.empty()) return {};
    const double direction = angle(point, center_);
    for (const auto& sector : sectors_)
        if (direction >= sector.start && direction < sector.end)
            return sector.path.empty() ? std::optional<std::string>{} : std::optional<std::string>{sector.path};
    return {};
}

} // namespace tinyenv
