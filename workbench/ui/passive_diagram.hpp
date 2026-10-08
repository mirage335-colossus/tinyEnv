#pragma once

#include <gui/contract.hpp>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace tinyenv {

enum class PassiveDiagramDirection { top_down, left_right, right_left, bottom_up };
enum class PassiveDiagramShape { box, rounded, decision };

struct PassiveDiagramNode {
    std::string id;
    std::string label;
    PassiveDiagramShape shape = PassiveDiagramShape::box;
    bool operator==(const PassiveDiagramNode&) const = default;
};
struct PassiveDiagramEdge {
    std::size_t from = 0, to = 0;
    std::string label = {};
    bool operator==(const PassiveDiagramEdge&) const = default;
};
struct PassiveDiagram {
    bool supported = false;
    // Always an inert ASCII projection, including when the grammar is rejected.
    // Line breaks remain structural. No escape sequence is decoded.
    std::string sanitized_source;
    std::string diagnostic;
    PassiveDiagramDirection direction = PassiveDiagramDirection::top_down;
    std::vector<PassiveDiagramNode> nodes;
    std::vector<PassiveDiagramEdge> edges;
};

inline constexpr std::size_t passive_diagram_input_limit = 16 * 1024;
inline constexpr std::size_t passive_diagram_node_limit = 32;
inline constexpr std::size_t passive_diagram_edge_limit = 64;
inline constexpr std::size_t passive_diagram_label_limit = 80;

// One pass, with no decoding: replace controls, non-ASCII bytes and escape
// shapes (backslashes, [U+hex], [0xHH], HTML entities and percent-encoded bytes)
// and native label symbol marker '@' by '_'.
// The result contains only printable ASCII and is capped at max_bytes, which
// itself is capped at passive_diagram_input_limit. This is also suitable for
// labels in the application's separate pseudocode flow canvas.
std::string passive_diagram_safe_text(std::string_view raw_text,
                                     std::size_t max_bytes = 4096);

// A deliberately small local Mermaid subset: graph/flowchart TD, TB, LR, RL or
// BT; ASCII node IDs; optional [label], (label) or {label}; and --> edges with
// optional |label| or -- label --> text. ((label)) and ([label]) use rounded
// native boxes. Ordinary full-line %% comments are inert. Newlines separate
// statements. Semicolons inside quoted/pipe labels remain text; elsewhere they
// separate statements. Quoted and delimiter-bounded labels accept a small
// punctuation set, subject to these separators; all labels remain
// bounded ASCII. A lowercase style statement may target an already-declared
// node with 1..3 unique fill/stroke/stroke-width properties: #RGB/#RRGGBB colors
// or 1..8px integer widths, in at most 128 bytes. These declarations are validated
// then discarded; rendering always uses the app's fixed palette. Every other
// unsupported statement rejects the whole diagram. No CSS engine, web, SVG,
// JavaScript, expressions or resource loading.
PassiveDiagram parse_passive_diagram(std::string_view raw_source);

// Suggested scroll-content height, bounded to [96, 1536]. Rendering scales its
// deterministic geometry into the supplied viewport and accepts cycles.
double passive_diagram_height(const PassiveDiagram&, double width);

class PassiveDiagramView {
public:
    // Bitmap plus inert label widgets, with no pointer/action/link capability.
    // Snapshots own immutable raster bytes and retain only sanitized ASCII text.
    std::vector<gui::Widget> render(const PassiveDiagram&, gui::Rect viewport,
                                  std::string key_prefix,
                                  std::string parent = {});
private:
    std::uint64_t revision_ = 0;
};

} // namespace tinyenv
