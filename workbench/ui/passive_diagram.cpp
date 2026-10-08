#include "passive_diagram.hpp"
#include "theme.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <iterator>
#include <limits>
#include <memory>
#include <stdexcept>
#include <utility>

namespace tinyenv {
namespace {
constexpr std::size_t identifier_limit = 32, statement_limit = 128, style_byte_limit = 128;
constexpr std::size_t raster_pixel_limit = 512 * 1024;
constexpr std::size_t sample_pixel_limit = 2 * 1024 * 1024;
constexpr unsigned raster_axis_limit = 2048, sample_axis_limit = 4096;
using Color = theme::RasterColor;
constexpr auto palette = theme::dark_palette();
constexpr auto background = theme::rgb(palette.surface);
constexpr Color node_fill{35, 48, 63}, decision_fill{51, 45, 58};
constexpr auto border = theme::rgb(palette.accent);

bool ascii_letter(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}
bool digit(char c) { return c >= '0' && c <= '9'; }
bool hex(char c) {
    return digit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}
bool identifier_char(char c) { return ascii_letter(c) || digit(c) || c == '_'; }
bool plain_label_char(char c) {
    return identifier_char(c) || c == ' ' || c == '.' || c == ',' || c == '!' ||
        c == '?' || c == '-';
}
bool label_char(char c) {
    return plain_label_char(c) || c == ':' || c == ';' || c == '(' || c == ')' ||
        c == '/' || c == '+' || c == '=' || c == '\'';
}
std::string_view trim(std::string_view text) {
    while (!text.empty() && text.front() == ' ') text.remove_prefix(1);
    while (!text.empty() && text.back() == ' ') text.remove_suffix(1);
    return text;
}

// Work only on original bytes. Replacements are appended directly and are never
// inspected again. LF/CRLF are structural separators only for diagram source;
// all other controls become underscores before grammar parsing.
std::string project(std::string_view raw, std::size_t max_bytes, bool source) {
    raw = raw.substr(0, passive_diagram_input_limit);
    max_bytes = std::min(max_bytes, passive_diagram_input_limit);
    std::string out;
    out.reserve(std::min(raw.size(), max_bytes));
    for (std::size_t i = 0; i < raw.size() && out.size() < max_bytes;) {
        const auto byte = static_cast<unsigned char>(raw[i]);
        if (source && raw[i] == '\r' && i + 1 < raw.size() && raw[i + 1] == '\n') {
            out.push_back('\n'); i += 2; continue;
        }
        if (source && raw[i] == '\n') { out.push_back('\n'); ++i; continue; }
        if (byte < 32 || byte > 126) { out.push_back('_'); ++i; continue; }
        if (raw[i] == '\\') {
            // Block literal backslashes and the entire common escape shape.
            // Unknown escapes consume their following character as well.
            std::size_t end = std::min(i + 2, raw.size());
            if (source && i + 1 < raw.size() && (raw[i + 1] == '\n' || raw[i + 1] == '\r'))
                end = i + 1;
            if (i + 1 < raw.size() && (raw[i + 1] == 'u' || raw[i + 1] == 'U' || raw[i + 1] == 'x')) {
                if (end < raw.size() && raw[end] == '{') {
                    ++end;
                    while (end < raw.size() && end - i < 128 && raw[end] != '\n' && raw[end] != '}') ++end;
                    if (end < raw.size() && raw[end] == '}') ++end;
                } else {
                    const std::size_t count = raw[i + 1] == 'x' ? 2 : raw[i + 1] == 'u' ? 4 : 8;
                    for (std::size_t n = 0; n < count && end < raw.size() && hex(raw[end]); ++n) ++end;
                }
            } else if (i + 1 < raw.size() && hex(raw[i + 1])) {
                end = i + 1;
                while (end < raw.size() && end - (i + 1) < 6 && hex(raw[end])) ++end;
            }
            out.push_back('_'); i = end; continue;
        }
        if (raw[i] == '[' && i + 3 < raw.size() && raw[i + 1] == 'U' && raw[i + 2] == '+') {
            std::size_t end = i + 3;
            while (end < raw.size() && end - (i + 3) < 8 && hex(raw[end])) ++end;
            if (end > i + 3 && end < raw.size() && raw[end] == ']') {
                out.push_back('_'); i = end + 1; continue;
            }
        }
        if (raw[i] == '[' && i + 5 < raw.size() && raw[i + 1] == '0' &&
            (raw[i + 2] == 'x' || raw[i + 2] == 'X') && hex(raw[i + 3]) && hex(raw[i + 4]) && raw[i + 5] == ']') {
            out.push_back('_'); i += 6; continue;
        }
        // Some native label controls interpret ASCII '@' as a symbol selector.
        // Diagram source rejects it through the label grammar; generic flow
        // display text uses this stronger projection instead.
        if (!source && raw[i] == '@') { out.push_back('_'); ++i; continue; }
        if (raw[i] == '&') {
            std::size_t end = i + 1;
            if (end < raw.size() && raw[end] == '#') ++end;
            while (end < raw.size() && end - i <= 32 && (ascii_letter(raw[end]) || digit(raw[end]))) ++end;
            if (end > i + 1 && end < raw.size() && raw[end] == ';') ++end;
            else end = i + 1;
            // Also block malformed entity starts; no downstream decoder exists.
            out.push_back('_'); i = end; continue;
        }
        if (raw[i] == '%' && i + 2 < raw.size() && hex(raw[i + 1]) && hex(raw[i + 2])) {
            out.push_back('_'); i += 3; continue;
        }
        out.push_back(raw[i++]);
    }
    return out;
}

bool reserved(std::string_view id) {
    std::string lower(id);
    for (auto& c : lower) if (c >= 'A' && c <= 'Z') c = char(c - 'A' + 'a');
    constexpr std::array words{"click", "style", "class", "classdef", "linkstyle", "subgraph",
                               "end", "direction", "acctitle", "accdescr", "init", "config"};
    return std::find(words.begin(), words.end(), lower) != words.end();
}
bool valid_id(std::string_view id) {
    return !id.empty() && id.size() <= identifier_limit && !reserved(id) &&
        std::all_of(id.begin(), id.end(), identifier_char);
}
bool valid_label(std::string_view label) {
    return !label.empty() && label.size() <= passive_diagram_label_limit &&
        std::all_of(label.begin(), label.end(), label_char);
}
bool valid_shape(PassiveDiagramShape shape) {
    return shape == PassiveDiagramShape::box || shape == PassiveDiagramShape::rounded ||
        shape == PassiveDiagramShape::decision;
}
bool valid_direction(PassiveDiagramDirection direction) {
    return direction == PassiveDiagramDirection::top_down || direction == PassiveDiagramDirection::left_right ||
        direction == PassiveDiagramDirection::right_left || direction == PassiveDiagramDirection::bottom_up;
}

struct Parser {
    PassiveDiagram& result;
    std::vector<bool> defined;
    std::size_t parsed_edges = 0;

    bool fail(std::string message) {
        result.diagnostic = std::move(message);
        return false;
    }
    void spaces(std::string_view text, std::size_t& pos) const {
        while (pos < text.size() && text[pos] == ' ') ++pos;
    }
    bool node(std::string_view text, std::size_t& pos, std::size_t& index) {
        spaces(text, pos);
        const auto start = pos;
        while (pos < text.size() && identifier_char(text[pos])) ++pos;
        const auto id = text.substr(start, pos - start);
        if (!valid_id(id)) return fail("Unsupported diagram node identifier.");
        spaces(text, pos);
        std::string label(id);
        auto shape = PassiveDiagramShape::box;
        bool explicit_label = false;
        if (pos < text.size() && (text[pos] == '[' || text[pos] == '(' || text[pos] == '{')) {
            explicit_label = true;
            const char opening = text[pos++];
            char closing = opening == '[' ? ']' : opening == '(' ? ')' : '}';
            bool double_rounded = false;
            shape = opening == '[' ? PassiveDiagramShape::box : opening == '(' ?
                PassiveDiagramShape::rounded : PassiveDiagramShape::decision;
            // These common start/end spellings are inert rounded-box aliases,
            // rather than a second geometry implementation.
            if (opening == '(' && pos < text.size() && (text[pos] == '(' || text[pos] == '[')) {
                closing = text[pos++] == '(' ? ')' : ']';
                double_rounded = true;
            }
            spaces(text, pos);
            const bool quoted = pos < text.size() && text[pos] == '"';
            if (quoted) ++pos;
            const auto label_start = pos;
            while (pos < text.size() && text[pos] != (quoted ? '"' : closing)) ++pos;
            if (pos == text.size()) return fail("Unclosed diagram node label.");
            label = std::string(trim(text.substr(label_start, pos - label_start)));
            if (!valid_label(label)) return fail("Unsupported diagram label; use short ASCII words and simple punctuation.");
            if (quoted) { ++pos; spaces(text, pos); }
            if (pos == text.size() || text[pos] != closing) return fail("Unsupported diagram label syntax.");
            ++pos;
            if (double_rounded) {
                if (pos == text.size() || text[pos] != ')') return fail("Unsupported diagram rounded label syntax.");
                ++pos;
            }
        }
        const auto found = std::find_if(result.nodes.begin(), result.nodes.end(), [&](const auto& n) { return n.id == id; });
        if (found == result.nodes.end()) {
            if (result.nodes.size() == passive_diagram_node_limit) return fail("Diagram node limit exceeded.");
            index = result.nodes.size();
            result.nodes.push_back({std::string(id), std::move(label), shape});
            defined.push_back(explicit_label);
        } else {
            index = std::size_t(found - result.nodes.begin());
            if (explicit_label && defined[index] && (found->label != label || found->shape != shape))
                return fail("Conflicting diagram node declarations.");
            if (explicit_label) { found->label = std::move(label); found->shape = shape; defined[index] = true; }
        }
        return true;
    }
    bool edge_label(std::string_view text, std::string& label) {
        text = trim(text);
        if (text.size() >= 2 && text.front() == '"' && text.back() == '"') text = text.substr(1, text.size() - 2);
        if (!valid_label(text)) return fail("Unsupported diagram edge label; use short ASCII text.");
        label = std::string(text);
        return true;
    }
    bool style(std::string_view text) {
        if (text.size() > style_byte_limit) return fail("Diagram node style byte limit exceeded.");
        std::size_t pos = 5;
        spaces(text, pos);
        const auto start = pos;
        while (pos < text.size() && identifier_char(text[pos])) ++pos;
        const auto id = text.substr(start, pos - start);
        if (!valid_id(id) || pos == text.size() || text[pos] != ' ')
            return fail("Unsupported diagram node style syntax.");
        if (std::none_of(result.nodes.begin(), result.nodes.end(), [&](const auto& n) { return n.id == id; }))
            return fail("Diagram node style requires an already-declared node.");
        spaces(text, pos);
        std::array<bool, 3> seen{};
        std::size_t count = 0;
        for (;;) {
            const auto comma = text.find(',', pos);
            const auto declaration = trim(text.substr(pos, comma == std::string_view::npos ? comma : comma - pos));
            const auto colon = declaration.find(':');
            if (colon == std::string_view::npos) return fail("Unsupported diagram node style property.");
            const auto key = trim(declaration.substr(0, colon));
            const auto value = trim(declaration.substr(colon + 1));
            const std::size_t property = key == "fill" ? 0 : key == "stroke" ? 1 : key == "stroke-width" ? 2 : 3;
            if (property == seen.size() || seen[property] || ++count > seen.size())
                return fail("Unsupported or repeated diagram node style property.");
            seen[property] = true;
            const bool valid = property == 2 ?
                (value.size() == 3 && value[0] >= '1' && value[0] <= '8' && value.substr(1) == "px") :
                ((value.size() == 4 || value.size() == 7) && value.front() == '#' &&
                    std::all_of(value.begin() + 1, value.end(), hex));
            if (!valid) return fail("Unsupported diagram node style value.");
            if (comma == std::string_view::npos) break;
            pos = comma + 1;
        }
        // Styles are recognized only for compatibility. No declaration reaches
        // the model or painter; the app's fixed native palette remains in use.
        return true;
    }
    bool statement(std::string_view text) {
        if (text.starts_with("style ")) return style(text);
        std::size_t pos = 0, from = 0;
        if (!node(text, pos, from)) return false;
        spaces(text, pos);
        while (pos < text.size()) {
            std::string label;
            if (text.substr(pos, 3) == "-->") {
                pos += 3;
                spaces(text, pos);
                if (pos < text.size() && text[pos] == '|') {
                    const auto start = ++pos;
                    while (pos < text.size() && text[pos] != '|') ++pos;
                    if (pos == text.size()) return fail("Unclosed diagram edge label.");
                    if (!edge_label(text.substr(start, pos - start), label)) return false;
                    ++pos;
                }
            } else if (text.substr(pos, 2) == "--") {
                pos += 2;
                const auto arrow = text.find("-->", pos);
                if (arrow == std::string_view::npos || !edge_label(text.substr(pos, arrow - pos), label))
                    return fail("Unsupported diagram edge syntax.");
                pos = arrow + 3;
            } else return fail("Unsupported diagram statement; only node declarations and --> edges are rendered.");
            std::size_t to = 0;
            if (!node(text, pos, to)) return false;
            if (++parsed_edges > passive_diagram_edge_limit) return fail("Diagram edge limit exceeded.");
            if (std::find(result.edges.begin(), result.edges.end(), PassiveDiagramEdge{from, to, label}) == result.edges.end())
                result.edges.push_back({from, to, std::move(label)});
            from = to;
            spaces(text, pos);
        }
        return true;
    }
};

struct Layout {
    double width = 1, height = 1;
    std::vector<gui::Rect> nodes;
    std::vector<gui::Rect> edge_labels;
    std::vector<bool> edge_detours;
};
bool same_route(const PassiveDiagramEdge& a, const PassiveDiagramEdge& b) {
    return (a.from == b.from && a.to == b.to) || (a.from == b.to && a.to == b.from);
}
std::size_t maximum_label_tracks(const PassiveDiagram& diagram) {
    std::size_t maximum = 0;
    for (const auto& edge : diagram.edges) if (!edge.label.empty()) {
        std::size_t count = 0;
        for (const auto& other : diagram.edges) if (!other.label.empty() && same_route(edge, other)) ++count;
        maximum = std::max(maximum, count);
    }
    return maximum;
}

// Kahn ranks give simple branching graphs useful layers. Remaining cyclic
// nodes receive finite deterministic ranks; arrows may travel back to any rank.
Layout layout(const PassiveDiagram& diagram) {
    const auto count = diagram.nodes.size();
    std::vector<std::size_t> indegree(count), rank(count), queue;
    for (const auto& edge : diagram.edges) ++indegree[edge.to];
    for (std::size_t i = 0; i < count; ++i) if (!indegree[i]) queue.push_back(i);
    for (std::size_t cursor = 0; cursor < queue.size(); ++cursor) {
        const auto from = queue[cursor];
        for (const auto& edge : diagram.edges) if (edge.from == from) {
            rank[edge.to] = std::max(rank[edge.to], rank[from] + 1);
            if (--indegree[edge.to] == 0) queue.push_back(edge.to);
        }
    }
    std::size_t next_rank = 0;
    for (const auto i : queue) next_rank = std::max(next_rank, rank[i] + 1);
    for (std::size_t i = 0; i < count; ++i) if (indegree[i]) rank[i] = next_rank++;
    const bool horizontal = diagram.direction == PassiveDiagramDirection::left_right ||
        diagram.direction == PassiveDiagramDirection::right_left;
    const bool reverse = diagram.direction == PassiveDiagramDirection::right_left ||
        diagram.direction == PassiveDiagramDirection::bottom_up;
    std::vector<std::vector<std::size_t>> layers(count);
    for (std::size_t i = 0; i < count; ++i) layers[rank[i]].push_back(i);
    Layout result;
    result.nodes.resize(count);
    const auto tracks = maximum_label_tracks(diagram);
    const double label_margin = tracks ? double(tracks) * 26 + 4 : 0;
    double primary = 22 + (horizontal ? 0 : label_margin);
    constexpr std::size_t lanes = 4;
    for (const auto& layer : layers) {
        if (layer.empty()) continue;
        for (std::size_t begin = 0; begin < layer.size(); begin += lanes) {
            const auto in_row = std::min(lanes, layer.size() - begin);
            for (std::size_t lane = 0; lane < in_row; ++lane) {
                const auto id = layer[begin + lane];
                const double cross = 22 + (horizontal ? label_margin : 0) + double(lane) * (horizontal ? 104 : 224);
                result.nodes[id] = horizontal ? gui::Rect{primary, cross, 196, 72} : gui::Rect{cross, primary, 196, 72};
                result.width = std::max(result.width, result.nodes[id].x + 218);
                result.height = std::max(result.height, result.nodes[id].y + 94 + label_margin);
            }
            primary += horizontal ? (tracks ? 420 : 240) : (tracks ? 72 + std::max(80.0, double(tracks) * 52) : 108);
        }
    }
    if (diagram.direction == PassiveDiagramDirection::right_left)
        for (auto& area : result.nodes) area.x = result.width - area.x - area.width;
    if (diagram.direction == PassiveDiagramDirection::bottom_up)
        for (auto& area : result.nodes) area.y = result.height - area.y - area.height;
    result.edge_labels.resize(diagram.edges.size());
    result.edge_detours.resize(diagram.edges.size());
    const double rail_left = result.width + 12;
    std::size_t detours = 0;
    for (std::size_t index = 0; index < diagram.edges.size(); ++index) {
        const auto& edge = diagram.edges[index];
        if (edge.label.empty()) continue;
        const auto& a = result.nodes[edge.from];
        const auto& b = result.nodes[edge.to];
        std::size_t count = 0, track = 0;
        for (std::size_t i = 0; i < diagram.edges.size(); ++i) if (!diagram.edges[i].label.empty() && same_route(edge, diagram.edges[i])) {
            if (i < index) ++track;
            ++count;
        }
        const double offset = (double(track) - (double(count) - 1) / 2) * 52;
        const bool returning = edge.from != edge.to && (horizontal ?
            (reverse ? b.x > a.x : b.x < a.x) : (reverse ? b.y > a.y : b.y < a.y));
        const bool forward = edge.from != edge.to && !returning;
        // Keep branch captions in their target lane. Source/target midpoints
        // give neighboring branches only half a lane of separation.
        const double center_x = edge.from == edge.to ? a.x + a.width / 2 :
            forward && !horizontal ? b.x + b.width / 2 :
                (a.x + a.width / 2 + b.x + b.width / 2) / 2;
        const double center_y = edge.from == edge.to ? a.y - 26 :
            forward && horizontal ? b.y + b.height / 2 :
                (a.y + a.height / 2 + b.y + b.height / 2) / 2;
        auto& area = result.edge_labels[index];
        area = {center_x - 98, center_y - 24 + offset, 196, 48};
        // A labeled return needs a separate track and a head entering the target
        // from its side. Reuse the bounded rail already used for colliding labels;
        // explicit self-loop geometry remains unchanged when its label fits.
        if (returning || std::any_of(result.nodes.begin(), result.nodes.end(), [&](const auto& node) {
                return gui::has_area(gui::intersect(area, node));
            })) {
            area = {rail_left, 22 + double(detours++) * 52, 196, 48};
            result.edge_detours[index] = true;
            result.height = std::max(result.height, area.y + area.height + 22);
        }
    }
    if (detours) result.width = rail_left + 218;
    return result;
}

PassiveDiagram validated(const PassiveDiagram& raw) {
    if (!raw.supported || raw.nodes.empty() || raw.nodes.size() > passive_diagram_node_limit ||
        raw.edges.size() > passive_diagram_edge_limit || !valid_direction(raw.direction))
        throw std::invalid_argument("Invalid passive diagram model");
    PassiveDiagram safe;
    safe.supported = true;
    safe.direction = raw.direction;
    safe.nodes.reserve(raw.nodes.size());
    // The public model can be independently constructed. Reapply the same
    // projection at the display boundary and then recheck its restricted grammar.
    for (std::size_t i = 0; i < raw.nodes.size(); ++i) {
        const auto& node = raw.nodes[i];
        if (!valid_id(node.id) || !valid_shape(node.shape) || node.label.size() > passive_diagram_input_limit)
            throw std::invalid_argument("Invalid passive diagram node");
        auto label = passive_diagram_safe_text(node.label, passive_diagram_label_limit + 1);
        if (!valid_label(label)) throw std::invalid_argument("Invalid passive diagram label");
        for (std::size_t j = 0; j < i; ++j) if (safe.nodes[j].id == node.id)
            throw std::invalid_argument("Duplicate passive diagram node");
        safe.nodes.push_back({node.id, std::move(label), node.shape});
    }
    for (const auto& edge : raw.edges) {
        if (edge.from >= safe.nodes.size() || edge.to >= safe.nodes.size())
            throw std::invalid_argument("Invalid passive diagram edge");
        if (edge.label.size() > passive_diagram_input_limit) throw std::invalid_argument("Invalid passive diagram edge label");
        auto label = passive_diagram_safe_text(edge.label, passive_diagram_label_limit + 1);
        if (!label.empty() && !valid_label(label)) throw std::invalid_argument("Invalid passive diagram edge label");
        safe.edges.push_back({edge.from, edge.to, std::move(label)});
    }
    return safe;
}

class Raster {
public:
    explicit Raster(gui::Rect viewport) : viewport_(viewport) {
        double scale = std::min(1.0, double(raster_axis_limit) / std::max(viewport.width, viewport.height));
        if (viewport.width * viewport.height * scale * scale > raster_pixel_limit)
            scale = std::sqrt(double(raster_pixel_limit) / (viewport.width * viewport.height));
        width_ = std::max(1u, unsigned(std::ceil(viewport.width * scale)));
        height_ = std::max(1u, unsigned(std::ceil(viewport.height * scale)));
        height_ = std::min(height_, unsigned(raster_pixel_limit / width_));
        pixels_.resize(std::size_t(width_) * height_ * 3);
        for (std::size_t i = 0; i < pixels_.size(); i += 3)
            std::copy(background.begin(), background.end(), pixels_.begin() + std::ptrdiff_t(i));
    }
    void pixel(int x, int y, Color color) {
        if (x < 0 || y < 0 || x >= int(width_) || y >= int(height_)) return;
        const auto i = (std::size_t(y) * width_ + unsigned(x)) * 3;
        std::copy(color.begin(), color.end(), pixels_.begin() + std::ptrdiff_t(i));
    }
    gui::Point local(gui::Point point) const {
        return {(point.x - viewport_.x) / viewport_.width * width_,
                (point.y - viewport_.y) / viewport_.height * height_};
    }
    void label_backing(gui::Rect area) {
        const auto a = local({area.x, area.y}), b = local({area.x + area.width, area.y + area.height});
        for (int y = std::max(0, int(std::floor(a.y))); y < std::min(int(height_), int(std::ceil(b.y))); ++y)
            for (int x = std::max(0, int(std::floor(a.x))); x < std::min(int(width_), int(std::ceil(b.x))); ++x)
                pixel(x, y, background);
    }
    void line(gui::Point from, gui::Point to, Color color = border) {
        from = local(from); to = local(to);
        int x = int(std::round(from.x)), y = int(std::round(from.y));
        const int end_x = int(std::round(to.x)), end_y = int(std::round(to.y));
        const int dx = std::abs(end_x - x), dy = -std::abs(end_y - y);
        const int sx = x < end_x ? 1 : -1, sy = y < end_y ? 1 : -1;
        int residual = dx + dy;
        for (;;) {
            pixel(x, y, color);
            if (x == end_x && y == end_y) break;
            const int twice = 2 * residual;
            if (twice >= dy) { residual += dy; x += sx; }
            if (twice <= dx) { residual += dx; y += sy; }
        }
    }
    void node(gui::Rect area, PassiveDiagramShape shape) {
        const auto a = local({area.x, area.y});
        const auto b = local({area.x + area.width, area.y + area.height});
        const double cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
        const double half_width = std::max(.5, (b.x - a.x) / 2), half_height = std::max(.5, (b.y - a.y) / 2);
        const double radius = std::min({half_width, half_height, (b.x - a.x) * 10 / 196});
        for (int y = std::max(0, int(std::floor(a.y))); y < std::min(int(height_), int(std::ceil(b.y))); ++y)
            for (int x = std::max(0, int(std::floor(a.x))); x < std::min(int(width_), int(std::ceil(b.x))); ++x) {
                const double corner_x = std::max({a.x + radius - (x + .5), 0.0, (x + .5) - (b.x - radius)});
                const double corner_y = std::max({a.y + radius - (y + .5), 0.0, (y + .5) - (b.y - radius)});
                const bool inside = shape == PassiveDiagramShape::decision ?
                    std::abs((x + .5 - cx) / half_width) + std::abs((y + .5 - cy) / half_height) <= 1 :
                    shape != PassiveDiagramShape::rounded || corner_x * corner_x + corner_y * corner_y <= radius * radius;
                if (inside)
                    pixel(x, y, shape == PassiveDiagramShape::decision ? decision_fill : node_fill);
            }
        if (shape == PassiveDiagramShape::rounded) {
            const double r = area.width * 10 / 196;
            line({area.x + r, area.y}, {area.x + area.width - r, area.y});
            line({area.x + r, area.y + area.height}, {area.x + area.width - r, area.y + area.height});
            line({area.x, area.y + r}, {area.x, area.y + area.height - r});
            line({area.x + area.width, area.y + r}, {area.x + area.width, area.y + area.height - r});
            const std::array<gui::Point, 4> centers{{{area.x + r, area.y + r}, {area.x + area.width - r, area.y + r},
                {area.x + area.width - r, area.y + area.height - r}, {area.x + r, area.y + area.height - r}}};
            const double pi = std::acos(-1.0);
            for (std::size_t corner = 0; corner < centers.size(); ++corner) {
                const double angle = pi + double(corner) * pi / 2;
                auto previous = gui::Point{centers[corner].x + r * std::cos(angle), centers[corner].y + r * std::sin(angle)};
                for (unsigned step = 1; step <= 8; ++step) {
                    const double theta = angle + double(step) * pi / 16;
                    const gui::Point next{centers[corner].x + r * std::cos(theta), centers[corner].y + r * std::sin(theta)};
                    line(previous, next); previous = next;
                }
            }
            return;
        }
        std::array<gui::Point, 4> corners;
        if (shape == PassiveDiagramShape::decision)
            corners = {{{area.x + area.width / 2, area.y}, {area.x + area.width, area.y + area.height / 2},
                        {area.x + area.width / 2, area.y + area.height}, {area.x, area.y + area.height / 2}}};
        else corners = {{{area.x, area.y}, {area.x + area.width, area.y},
                         {area.x + area.width, area.y + area.height}, {area.x, area.y + area.height}}};
        for (std::size_t i = 0; i < corners.size(); ++i) line(corners[i], corners[(i + 1) % corners.size()]);
    }
    gui::BitmapSource source() && {
        const auto width = width_, height = height_;
        const auto bytes = std::make_shared<const std::vector<std::uint8_t>>(std::move(pixels_));
        return gui::BitmapSource([bytes, width, height](const gui::BitmapRequest& request, const gui::BitmapSink& sink) {
            if (request.width > sample_axis_limit || request.height > sample_axis_limit ||
                std::size_t(request.width) * request.height > sample_pixel_limit)
                throw std::length_error("Passive diagram sample grid exceeds limits");
            if (request.format == gui::PixelFormat::rgb24 && request.width == width && request.height == height) {
                const auto stride = std::size_t(width) * 3;
                const auto start = std::size_t(request.damage.y) * stride + std::size_t(request.damage.x) * 3;
                sink(request.damage.x, request.damage.y, {request.damage.width, request.damage.height, stride,
                    request.format, std::span<const std::uint8_t>(*bytes).subspan(start)});
                return;
            }
            std::vector<std::uint8_t> row(gui::pixel_row_bytes(request.damage.width, request.format));
            for (unsigned y = 0; y < request.damage.height; ++y) {
                std::fill(row.begin(), row.end(), 0);
                const auto sy = std::min(height - 1, unsigned((double(request.damage.y + y) + .5) * height / request.height));
                for (unsigned x = 0; x < request.damage.width; ++x) {
                    const auto sx = std::min(width - 1, unsigned((double(request.damage.x + x) + .5) * width / request.width));
                    const auto i = (std::size_t(sy) * width + sx) * 3;
                    if (request.format == gui::PixelFormat::rgb24) {
                        const auto target = std::size_t(x) * 3;
                        row[target] = (*bytes)[i]; row[target + 1] = (*bytes)[i + 1]; row[target + 2] = (*bytes)[i + 2];
                    } else {
                        const auto gray = std::uint8_t((77u * (*bytes)[i] + 150u * (*bytes)[i + 1] +
                                                       29u * (*bytes)[i + 2] + 128u) / 256u);
                        if (request.format == gui::PixelFormat::gray8) row[x] = gray;
                        else if (gray >= 128) row[x / 8] |= std::uint8_t(0x80u >> (x % 8));
                    }
                }
                sink(request.damage.x, request.damage.y + y, {request.damage.width, 1, row.size(), request.format, row});
            }
        });
    }
private:
    gui::Rect viewport_;
    unsigned width_ = 1, height_ = 1;
    std::vector<std::uint8_t> pixels_;
};

} // namespace

std::string passive_diagram_safe_text(std::string_view raw_text, std::size_t max_bytes) {
    return project(raw_text, max_bytes, false);
}

PassiveDiagram parse_passive_diagram(std::string_view raw_source) {
    PassiveDiagram result;
    result.sanitized_source = project(raw_source, passive_diagram_input_limit, true);
    if (raw_source.size() > passive_diagram_input_limit) {
        result.diagnostic = "Diagram input limit exceeded; source projection is truncated.";
        return result;
    }
    Parser parser{result, {}, 0};
    bool header = false;
    std::size_t statements = 0, begin = 0;
    bool quoted = false, pipe = false, comment = false, inspected = false;
    for (std::size_t end = 0; end <= result.sanitized_source.size(); ++end) {
        if (end < result.sanitized_source.size()) {
            const char c = result.sanitized_source[end];
            if (!inspected && c != ' ') {
                inspected = true;
                const auto rest = std::string_view(result.sanitized_source).substr(end);
                comment = rest.starts_with("%% ") || rest == "%%" || rest.starts_with("%%\n");
                if (comment && trim(rest.substr(2)).starts_with('{')) comment = false;
            }
            if (!comment && c == '"') quoted = !quoted;
            if (!comment && !quoted && c == '|') pipe = !pipe;
            if (c != '\n' && (c != ';' || quoted || pipe || comment)) continue;
        }
        const auto text = trim(std::string_view(result.sanitized_source).substr(begin, end - begin));
        begin = end + 1;
        const bool ignored_comment = comment;
        quoted = pipe = comment = inspected = false;
        if (text.empty()) continue;
        if (++statements > statement_limit) { parser.fail("Diagram statement limit exceeded."); break; }
        if (ignored_comment) continue;
        if (!header) {
            const auto space = text.find(' ');
            if (space == std::string_view::npos || (text.substr(0, space) != "graph" && text.substr(0, space) != "flowchart")) {
                parser.fail("Only the local graph/flowchart subset is rendered."); break;
            }
            const auto direction = trim(text.substr(space + 1));
            if (direction == "TD" || direction == "TB") result.direction = PassiveDiagramDirection::top_down;
            else if (direction == "LR") result.direction = PassiveDiagramDirection::left_right;
            else if (direction == "RL") result.direction = PassiveDiagramDirection::right_left;
            else if (direction == "BT") result.direction = PassiveDiagramDirection::bottom_up;
            else { parser.fail("Unsupported diagram direction."); break; }
            header = true;
        } else if (!parser.statement(text)) break;
    }
    if (result.diagnostic.empty() && (!header || result.nodes.empty())) result.diagnostic = "Diagram requires a header and at least one node.";
    result.supported = result.diagnostic.empty();
    if (!result.supported) { result.nodes.clear(); result.edges.clear(); }
    return result;
}

double passive_diagram_height(const PassiveDiagram& raw, double width) {
    if (!std::isfinite(width) || width < 1) return 96;
    const auto diagram = validated(raw);
    const auto geometry = layout(diagram);
    return std::clamp(geometry.height * std::min(1.0, width / geometry.width), 96.0, 1536.0);
}

std::vector<gui::Widget> PassiveDiagramView::render(const PassiveDiagram& raw, gui::Rect viewport,
                                                 std::string key_prefix, std::string parent) {
    if (!gui::valid_rect(viewport)) throw std::invalid_argument("Invalid passive diagram viewport");
    // Avoid divisions by tiny positive coordinates and keep subpixel surfaces
    // empty. The surrounding Markdown code can display its literal fallback.
    if (viewport.width < 1 || viewport.height < 1) return {};
    const auto diagram = validated(raw);
    auto geometry = layout(diagram);
    const double scale = std::min({1.0, viewport.width / geometry.width, viewport.height / geometry.height});
    const double left = viewport.x + (viewport.width - geometry.width * scale) / 2;
    const double top = viewport.y + (viewport.height - geometry.height * scale) / 2;
    for (auto& area : geometry.nodes) area = {left + area.x * scale, top + area.y * scale, area.width * scale, area.height * scale};
    for (auto& area : geometry.edge_labels) area = {left + area.x * scale, top + area.y * scale, area.width * scale, area.height * scale};
    Raster raster(viewport);
    const bool horizontal = diagram.direction == PassiveDiagramDirection::left_right || diagram.direction == PassiveDiagramDirection::right_left;
    const bool reverse = diagram.direction == PassiveDiagramDirection::right_left || diagram.direction == PassiveDiagramDirection::bottom_up;
    const double sign = reverse ? -1 : 1;
    std::vector<gui::Widget> edge_labels;
    for (std::size_t edge_index = 0; edge_index < diagram.edges.size(); ++edge_index) {
        const auto& edge = diagram.edges[edge_index];
        const auto& a = geometry.nodes[edge.from];
        const auto& b = geometry.nodes[edge.to];
        if (!edge.label.empty()) {
            gui::Widget label;
            label.spec.key = {key_prefix + ".edge." + std::to_string(edge_index), 1};
            label.spec.parent = parent; label.spec.kind = gui::Kind::label;
            label.state.bounds = gui::intersect(geometry.edge_labels[edge_index], viewport);
            label.state.text = label.state.accessible_name = edge.label;
            label.state.font = {std::clamp(11 * scale, 8.0, 11.0), false, gui::Tone::normal};
            label.state.wrap = gui::TextWrap::word;
            edge_labels.push_back(std::move(label));
        }
        if (geometry.edge_detours[edge_index]) {
            const gui::Point from{a.x + a.width, a.y + a.height / 2}, to{b.x + b.width, b.y + b.height / 2};
            const auto& label_area = geometry.edge_labels[edge_index];
            const double rail_x = label_area.x + label_area.width / 2, label_y = label_area.y + label_area.height / 2;
            raster.line(from, {rail_x, from.y});
            raster.line({rail_x, from.y}, {rail_x, label_y});
            raster.line({rail_x, label_y}, {rail_x, to.y});
            raster.line({rail_x, to.y}, to);
            raster.line(to, {to.x + 6 * scale, to.y - 4 * scale});
            raster.line(to, {to.x + 6 * scale, to.y + 4 * scale});
            continue;
        }
        if (edge.from == edge.to) {
            const double x = a.x + a.width, y = a.y + a.height / 2, detour = 12 * scale;
            raster.line({x, y}, {x + detour, y});
            raster.line({x + detour, y}, {x + detour, a.y - detour});
            raster.line({x + detour, a.y - detour}, {a.x + a.width / 2, a.y - detour});
            raster.line({a.x + a.width / 2, a.y - detour}, {a.x + a.width / 2, a.y});
            raster.line({a.x + a.width / 2, a.y}, {a.x + a.width / 2 - 4 * scale, a.y - 6 * scale});
            raster.line({a.x + a.width / 2, a.y}, {a.x + a.width / 2 + 4 * scale, a.y - 6 * scale});
            continue;
        }
        const gui::Point from = horizontal ? gui::Point{a.x + (reverse ? 0 : a.width), a.y + a.height / 2} :
            gui::Point{a.x + a.width / 2, a.y + (reverse ? 0 : a.height)};
        const gui::Point to = horizontal ? gui::Point{b.x + (reverse ? b.width : 0), b.y + b.height / 2} :
            gui::Point{b.x + b.width / 2, b.y + (reverse ? b.height : 0)};
        const double middle = horizontal ? (from.x + to.x) / 2 : (from.y + to.y) / 2;
        raster.line(from, horizontal ? gui::Point{middle, from.y} : gui::Point{from.x, middle});
        raster.line(horizontal ? gui::Point{middle, from.y} : gui::Point{from.x, middle},
                    horizontal ? gui::Point{middle, to.y} : gui::Point{to.x, middle});
        raster.line(horizontal ? gui::Point{middle, to.y} : gui::Point{to.x, middle}, to);
        raster.line(to, horizontal ? gui::Point{to.x - sign * 6 * scale, to.y - 4 * scale} :
                                      gui::Point{to.x - 4 * scale, to.y - sign * 6 * scale});
        raster.line(to, horizontal ? gui::Point{to.x - sign * 6 * scale, to.y + 4 * scale} :
                                      gui::Point{to.x + 4 * scale, to.y - sign * 6 * scale});
    }
    for (const auto& label : edge_labels) {
        auto backing = label.state.bounds;
        // A conservative single-line ASCII footprint keeps caption glyphs
        // readable without blanking the empty rows of the native wrap control.
        // Wrapped captions retain their bounded backing instead of guessing
        // backend-specific word breaks.
        const double text_width = (double(label.state.text.size()) + .5) * label.state.font.size * .7;
        if (text_width <= backing.width) {
            backing.width = text_width;
            backing.height = std::min(backing.height, label.state.font.size * 1.6 + 2);
        }
        raster.label_backing(backing);
    }
    std::vector<gui::Widget> widgets;
    widgets.reserve(diagram.nodes.size() + edge_labels.size() + 1);
    widgets.insert(widgets.end(), std::make_move_iterator(edge_labels.begin()), std::make_move_iterator(edge_labels.end()));
    for (std::size_t i = 0; i < diagram.nodes.size(); ++i) {
        const auto& node = diagram.nodes[i];
        const auto& area = geometry.nodes[i];
        raster.node(area, node.shape);
        const bool diamond = node.shape == PassiveDiagramShape::decision;
        const double inset = diamond ? area.width * .25 : 10 * scale;
        const double text_top = diamond ? area.height * .25 : 8 * scale;
        gui::Widget label;
        label.spec.key = {key_prefix + ".node." + std::to_string(i), 1};
        label.spec.parent = parent; label.spec.kind = gui::Kind::label;
        label.state.bounds = gui::intersect({area.x + inset, area.y + text_top,
            std::max(0.0, area.width - 2 * inset), std::max(0.0, area.height - 2 * text_top)}, viewport);
        label.state.text = node.label;
        label.state.accessible_name = node.label;
        label.state.font = {std::clamp(12 * scale, 8.0, 12.0), false, gui::Tone::normal};
        label.state.wrap = gui::TextWrap::word;
        widgets.push_back(std::move(label));
    }
    gui::Widget canvas;
    canvas.spec.key = {key_prefix + ".canvas", 1}; canvas.spec.parent = std::move(parent);
    canvas.spec.kind = gui::Kind::bitmap; canvas.state.bounds = viewport;
    canvas.state.accessible_name = "Passive flowchart. " + std::to_string(diagram.nodes.size()) + " nodes.";
    canvas.state.bitmap = {key_prefix + ".raster", ++revision_, std::move(raster).source()};
    widgets.insert(widgets.begin(), std::move(canvas));
    return widgets;
}

} // namespace tinyenv
