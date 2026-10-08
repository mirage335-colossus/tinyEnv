#include "workbench/ui/passive_diagram.hpp"
#include <gui/bitmap.hpp>

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace {
// Only the two relevant diagrams from the reported rendering failure are kept;
// the surrounding chat is deliberately absent from these offline fixtures.
constexpr std::string_view reported_flowcharts[]{
    R"(flowchart TD
    A[Start: User wants a flowchart] --> B{What type?}
    B -- Text-based --> C[Generate ASCII/Mermaid code]
    B -- Visual (if capable) --> D[Render image]
    C --> E[Output code]
    E --> F[User copies/pastes to renderer]
    style A fill:#f9f,stroke:#333,stroke-width:2px
    style C fill:#bbf,stroke:#333,stroke-width:2px
)",
    R"(flowchart TD
    A[Start: User requests flowchart] --> B{Select Style}
    B -->|Text-based ASCII| C[Generate ASCII Art]
    B -->|Mermaid Syntax| D[Generate Mermaid Code]
    C --> E[Output ASCII Diagram]
    D --> F[Output Mermaid Code]
    E --> G[User views in terminal]
    F --> H[User pastes to renderer]
    style A fill:#f9f,stroke:#333,stroke-width:2px
    style C fill:#bbf,stroke:#333,stroke-width:2px
    style D fill:#bfb,stroke:#333,stroke-width:2px
)"
};
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
bool printable(std::string_view text, bool source = false) {
    return std::all_of(text.begin(), text.end(), [source](unsigned char c) {
        return (c >= 32 && c <= 126) || (source && c == '\n');
    });
}
void rejected(std::string_view source) {
    const auto diagram = tinyenv::parse_passive_diagram(source);
    check(!diagram.supported, "Unsupported diagram was accepted");
    check(diagram.nodes.empty() && diagram.edges.empty(), "Rejected diagram retained a partially parsed graph");
    check(!diagram.diagnostic.empty() && printable(diagram.diagnostic), "Rejected diagram lacked an inert diagnostic");
    check(printable(diagram.sanitized_source, true), "Rejected source projection retained non-ASCII controls");
}
template<class Callback> void invalid_model(Callback change) {
    auto model = tinyenv::parse_passive_diagram("flowchart TD\nA[Start] --> B[Done]");
    change(model);
    tinyenv::PassiveDiagramView view;
    bool failed = false;
    try { (void)view.render(model, {0, 0, 400, 240}, "test"); }
    catch (const std::invalid_argument&) { failed = true; }
    check(failed, "Public mutable diagram model bypassed renderer validation");
}
gui::BitmapImage sample(const gui::BitmapSource& source, unsigned width, unsigned height,
                        gui::PixelFormat format = gui::PixelFormat::rgb24) {
    gui::BitmapImage image(width, height, format);
    source.paint(gui::full_bitmap_request(width, height, format),
                 [&](unsigned x, unsigned y, gui::PixelBlock block) { image.blit(x, y, block); });
    return image;
}
gui::Rect node_bounds(const gui::Widget& label, tinyenv::PassiveDiagramShape shape) {
    const auto& text = label.state.bounds;
    const bool decision = shape == tinyenv::PassiveDiagramShape::decision;
    const double scale = text.width / (decision ? 98 : 176);
    return {text.x - (decision ? 49 : 10) * scale, text.y - (decision ? 18 : 8) * scale, 196 * scale, 72 * scale};
}
bool visible_forward_rail(const gui::Widget& canvas, gui::Rect from, gui::Rect to) {
    const auto width = unsigned(std::ceil(canvas.state.bounds.width)), height = unsigned(std::ceil(canvas.state.bounds.height));
    const auto pixels = sample(canvas.state.bitmap.source, width, height).pixels();
    const auto local = [&](gui::Point point) {
        return std::pair{int(std::round((point.x - canvas.state.bounds.x) * width / canvas.state.bounds.width)),
                         int(std::round((point.y - canvas.state.bounds.y) * height / canvas.state.bounds.height))};
    };
    const double source_x = from.x + from.width / 2, source_y = from.y + from.height;
    const double target_x = to.x + to.width / 2, middle_y = (source_y + to.y) / 2;
    const auto [stroke_x, stroke_y] = local({source_x, source_y});
    const auto [first_x, row] = local({source_x, middle_y});
    const auto [last_x, same_row] = local({target_x, middle_y});
    if (stroke_x < 0 || stroke_x >= int(width) || stroke_y < 0 || stroke_y >= int(height) ||
        first_x < 0 || last_x < 0 || first_x >= int(width) || last_x >= int(width) || row < 0 || row >= int(height) || row != same_row) return false;
    const auto stroke = std::size_t(stroke_y) * width + unsigned(stroke_x);
    const auto same_stroke = [&](std::size_t pixel) {
        return pixels[pixel * 3] == pixels[stroke * 3] && pixels[pixel * 3 + 1] == pixels[stroke * 3 + 1] && pixels[pixel * 3 + 2] == pixels[stroke * 3 + 2];
    };
    if (same_stroke(0)) return false;
    // The one-line caption occupies the top of its 48px wrap box. The middle
    // branch rail is below those glyph rows: its junction and connector must
    // stay visible, while a small stem gap behind actual text is acceptable.
    for (int x = std::min(first_x,last_x); x <= std::max(first_x,last_x); ++x)
        if (!same_stroke(std::size_t(row) * width + unsigned(x))) return false;
    return true;
}
void forward_branch_geometry(const tinyenv::PassiveDiagram& model, const std::vector<gui::Widget>& widgets) {
    const auto find = [&](std::string_view text) -> const gui::Widget& {
        const auto found = std::find_if(widgets.begin(), widgets.end(), [&](const auto& widget) { return widget.spec.kind == gui::Kind::label && widget.state.text == text; });
        if (found == widgets.end()) throw std::runtime_error("Missing branch geometry label: " + std::string(text));
        return *found;
    };
    const auto& first = find(model.edges[1].label); const auto& second = find(model.edges[2].label);
    check(!gui::has_area(gui::intersect(first.state.bounds, second.state.bounds)), "Reported forward branch captions overlap");
    for (const auto& node : model.nodes) {
        const auto area = node_bounds(find(node.label), node.shape);
        check(!gui::has_area(gui::intersect(first.state.bounds, area)) && !gui::has_area(gui::intersect(second.state.bounds, area)),
              "Reported forward branch caption overlaps a node");
    }
    const auto decision = node_bounds(find(model.nodes[1].label), model.nodes[1].shape);
    for (const auto node : {2u,3u}) {
        const auto target = node_bounds(find(model.nodes[node].label), model.nodes[node].shape);
        check(visible_forward_rail(widgets.front(), decision, target), "Reported branch caption empty backing erased the forward junction or rail");
    }
}

void sanitizer() {
    std::string hostile;
    for (unsigned c = 0; c < 256; ++c) hostile.push_back(char(c));
    check(printable(tinyenv::passive_diagram_safe_text(hostile)), "Safe text retained nonprintable bytes");
    check(tinyenv::passive_diagram_safe_text("A\xE2\x80\x8D" "B") == "A___B", "UTF-8 joiner was not blocked before rendering");
    check(tinyenv::passive_diagram_safe_text("x\\u202Ey[U+202E]&lt;%3C") == "x_y___", "Escape-shaped text was not replaced in one pass");
    check(tinyenv::passive_diagram_safe_text("\\x3C\\U0000003E\\u{003C}\\00003c") == "____", "Encoded delimiters survived safety projection");
    check(tinyenv::passive_diagram_safe_text("&amp;lt;") == "_lt;", "Nested entity was recursively decoded");
    check(tinyenv::passive_diagram_safe_text("[U+005B]U+003C]") == "_U+003C]", "Fixed escape replacement was recursively reinterpreted");
    check(tinyenv::passive_diagram_safe_text("tail\\") == "tail_", "Trailing escape did not terminate safely");
    check(tinyenv::passive_diagram_safe_text("[0xFF][0x00]@symbol") == "___symbol", "Invalid-byte escapes or native label symbols survived projection");
    check(tinyenv::passive_diagram_safe_text("a\nb\rc\td") == "a_b_c_d", "Label controls retained layout authority");
    check(tinyenv::passive_diagram_safe_text(std::string(20000, 'a'), 20000).size() == tinyenv::passive_diagram_input_limit,
          "Shared sanitizer exceeded its maximum output/input scan budget");
    check(tinyenv::passive_diagram_safe_text("abcdef", 3) == "abc", "Shared sanitizer ignored caller text cap");
    check(tinyenv::passive_diagram_safe_text("abcdef", 0).empty(), "Zero text cap produced text");
    for (const auto text : {"&", "&broken", "&#", "\\u", "\\u{", "[U+", "[U+XYZ]", "%", "%GG"})
        check(printable(tinyenv::passive_diagram_safe_text(text)), "Malformed escape projection was not inert");
}

void grammar() {
    for (const auto direction : {"TD", "TB", "LR", "RL", "BT"}) {
        const auto source = std::string("flowchart ") + direction + "\r\nA[Start] --> B{Ready?}; B --> C(\"Done\")\nC --> A";
        const auto diagram = tinyenv::parse_passive_diagram(source);
        check(diagram.supported && diagram.nodes.size() == 3 && diagram.edges.size() == 3, "Supported bounded direction/shape/cycle was rejected");
        check(diagram.nodes[1].shape == tinyenv::PassiveDiagramShape::decision && diagram.nodes[2].label == "Done", "Node shape or quoted text was lost");
        check(printable(diagram.sanitized_source, true), "Accepted source retained non-ASCII/control bytes");
    }
    const auto chain = tinyenv::parse_passive_diagram("graph LR; A --> B --> C; B[Middle]; A --> B; C --> C");
    check(chain.supported && chain.nodes.size() == 3 && chain.edges.size() == 3, "Chained/duplicate/self edges or later label declaration failed");
    check(chain.nodes[1].label == "Middle", "Later explicit node label did not replace identifier text");
    const auto unsafe_label = tinyenv::parse_passive_diagram("graph TD\nA[raw \xE2\x80\xAE" "name] --> B[\\u003Cscript\\u003E]");
    check(unsafe_label.supported && unsafe_label.nodes[0].label == "raw ___name" && unsafe_label.nodes[1].label == "_script_",
          "Raw Unicode/bidi or encoded label delimiters bypassed preparse projection");
    for (const auto label : {"&lt;script&gt;", "&#60;script&#62;", "&#x3c;script&#x3e;", "%3Cscript%3E", "[U+003C]script[U+003E]"}) {
        const auto diagram = tinyenv::parse_passive_diagram(std::string("graph TD\nA[") + label + "]");
        check(diagram.supported && diagram.nodes[0].label == "_script_", "An encoded label was decoded or retained escape authority");
    }
    const auto inert_words = tinyenv::parse_passive_diagram("graph TD\nA[click button] --> B[class style words]");
    check(inert_words.supported, "Inert label words were confused with active directives");
    const auto encoded_inline = tinyenv::parse_passive_diagram("graph TD\nA\\u002D\\u002D\\u003EB");
    check(encoded_inline.supported && encoded_inline.edges.empty(), "Escaped arrow created a structural edge");
    rejected("graph TD\nA \\u002D\\u002D\\u003E B");
    rejected("graph TD\nA &#45;&#45;&gt; B");
    rejected("gr\\u0061ph TD\nA --> B");
    rejected("graph TD\nA\\\n--> B");
    rejected("graph TD\r\nA\\\r\n--> B");
    const auto tab_node = tinyenv::parse_passive_diagram("graph TD\nA;\tB");
    check(tab_node.supported && tab_node.nodes[1].id == "_B", "Control projection unexpectedly regained parser authority");
    rejected(std::string("graph TD\nA") + '\0' + " --> B\nclick B");
    for (const auto suffix : {
        "click B \"javascript:alert(1)\"", "click B href \"https://example.test/\"", "style B fill:red",
        "classDef x fill:red", "class B x", "linkStyle 0 stroke:red", "subgraph group", "direction LR",
        "accTitle: external", "A:::x", "A[<img src=x>]",
        "A[{{expression}}]", "A[@symbol]", "A[[nested]]", "A[`code`]",
        "A---B", "A-.->B", "A==>B", "A<-->B", "A[one] --> A[two]", "A[unterminated", "click", "end"
    }) rejected(std::string("graph TD\nA[Start] --> B[Done]\n") + suffix);
    // Colon/slash punctuation now makes these labels valid inert display text,
    // consistent with quoted labels. No URL navigation capability is declared.
    for (const auto label : {"https://example.test/", "javascript:alert(1)"}) {
        const auto literal = tinyenv::parse_passive_diagram(std::string("graph TD\nA[") + label + "]");
        check(literal.supported && literal.nodes.front().label == label, "URL-shaped label was decoded or lost literal text");
        tinyenv::PassiveDiagramView view;
        const auto widgets = view.render(literal, {0,0,400,240}, "literal-url");
        check(widgets.back().state.text == label, "URL-shaped label did not remain literal in the native view");
        for (const auto& widget : widgets)
            check(!widget.spec.pointer_input && !widget.spec.context_input && widget.state.actions.empty() && widget.state.options.empty(),
                  "Literal URL-shaped text acquired an active capability");
    }
    for (const auto source : {"%%{init: {}}%%\ngraph TD\nA-->B", "graph TD\n%% {init: {}}\nA-->B", "sequenceDiagram\nA-->B",
                              "graph XX\nA-->B", "graph TD", "A-->B", "graph TD\nA -->", "graph TD\nA B", "graph\tTD\nA"}) rejected(source);
}

void common_flowcharts() {
    // This graph is copied from the retained gui-boundary specification's
    // responsibility/data-direction example. It previously fell back as soon
    // as the first pipe label was mistaken for a node identifier.
    const auto specification = tinyenv::parse_passive_diagram(
        "flowchart LR\n"
        "A[Shared application] -->|Owned presentation snapshot| B[GUI adapter]\n"
        "B -->|Normalized input events| A\n"
        "A -->|Immutable bitmap source| B\n"
        "B -->|Grid, format, damage request| C[Bitmap producer]\n"
        "C -->|Borrowed pixel blocks| B\n"
        "A -->|Service request| D[Host services]\n"
        "D -->|Matching result| A\n");
    check(specification.supported && specification.nodes.size() == 4 && specification.edges.size() == 7,
          "Retained documentation's ordinary labeled flowchart still falls back");
    check(specification.edges[0].label == "Owned presentation snapshot", "Pipe edge label was discarded");
    const auto branch = tinyenv::parse_passive_diagram(
        "%% A local build decision; no executable directive\nflowchart TD\n"
        "A([Start]) --> B{Ready?}\nB -->|Yes| C((Done))\nB -- No --> A\n");
    check(branch.supported && branch.edges[1].label == "Yes" && branch.edges[2].label == "No",
          "Common decision branch or benign comment still falls back");
    check(branch.nodes[0].shape == tinyenv::PassiveDiagramShape::rounded && branch.nodes[2].shape == tinyenv::PassiveDiagramShape::rounded,
          "Common start/end aliases did not become native rounded shapes");
    const auto punctuation = tinyenv::parse_passive_diagram(
        "flowchart TD\nA[\"Step 1: Build (local); test / x+y=1's\"] -->|\"Ready; yes / no\"| B[Done];B -- Retry --> A\n");
    check(punctuation.supported && punctuation.nodes[0].label == "Step 1: Build (local); test / x+y=1's" &&
          punctuation.edges[0].label == "Ready; yes / no", "Quoted ASCII punctuation retained delimiter authority or failed to render");
    const auto chained = tinyenv::parse_passive_diagram("graph LR\nA-->|first|B -- second --> C-->|third|D");
    check(chained.supported && chained.edges.size() == 3 && chained.edges[2].label == "third", "Labeled chaining failed");
    const auto encoded = tinyenv::parse_passive_diagram("graph TD\nA-->|raw \xE2\x80\xAE" "text\\u003C|B");
    check(encoded.supported && encoded.edges[0].label == "raw ___text_", "Edge labels bypassed safety projection");
    for (const auto source : {"graph TD\nA-->|unclosed B", "graph TD\nA-->||B", "graph TD\nA -- --> B",
                              "graph TD\nA-->|<img src=x>|B", "graph TD\nA-->|`code`|B", "graph TD\nA((broken)",
                              "graph TD\nA([broken]"}) rejected(source);
    rejected("graph TD\nA[\"<script>\"]");
    rejected("graph TD\nA[\"{{expression}}\"]");
    rejected("graph TD\nA[\"@symbol\"]");
    rejected("graph TD\nA-->|Yes|B\nclick B \"javascript:alert(1)\"");
    check(tinyenv::parse_passive_diagram("graph TD\nA-->|" + std::string(tinyenv::passive_diagram_label_limit, 'x') + "|B").supported,
          "Exact edge label budget was rejected");
    rejected("graph TD\nA-->|" + std::string(tinyenv::passive_diagram_label_limit + 1, 'x') + "|B");
    std::string comments = "graph TD\nA\n";
    for (unsigned i = 0; i < 126; ++i) comments += "%% comment\n";
    check(tinyenv::parse_passive_diagram(comments).supported, "Exact statement budget including comments was rejected");
    rejected(comments + "%% extra\n");

    tinyenv::PassiveDiagramView view;
    const auto widgets = view.render(branch, {0,0,400,600}, "branch");
    for (const auto label : {"Yes", "No"}) {
        const auto found = std::find_if(widgets.begin(), widgets.end(), [&](const auto& widget) { return widget.state.text == label; });
        check(found != widgets.end() && found->spec.kind == gui::Kind::label && gui::has_area(found->state.bounds),
              "Branch edge label did not reach a visible native text widget");
        check(!found->spec.pointer_input && found->state.actions.empty(), "Edge label acquired executable interaction");
    }
    for (const auto direction : {"TD", "LR", "RL", "BT"}) {
        const auto common = tinyenv::parse_passive_diagram(std::string("flowchart ") + direction +
            "\n%% A local build decision\nA([Start]) --> B{Ready?}\nB -->|Yes| C((Done))\nB -- No --> A\n");
        const auto common_widgets = view.render(common, {0,0,800,600}, "common");
        const auto no = std::find_if(common_widgets.begin(), common_widgets.end(), [](const auto& w) { return w.state.text == "No"; });
        const auto start = std::find_if(common_widgets.begin(), common_widgets.end(), [](const auto& w) { return w.state.text == "Start"; });
        check(no != common_widgets.end() && start != common_widgets.end() && gui::has_area(no->state.bounds),
              "Common directional return lost its visible label or target");
        for (const auto& widget : common_widgets) if (widget.spec.key.id.find(".node.") != std::string::npos)
            check(no->state.bounds.x > widget.state.bounds.x + widget.state.bounds.width,
                  "Common return still shares the forward track instead of the side margin");
        // Start is a rounded box: its label has symmetric 10/8 model-unit
        // insets. Its return arrow must point left into the right side, so the
        // upper head endpoint lies six units to the right and four above center.
        const double scale = start->state.bounds.width / 176;
        const double right = start->state.bounds.x + start->state.bounds.width + 10 * scale;
        const double center_y = start->state.bounds.y + start->state.bounds.height / 2;
        const auto pixels = sample(common_widgets.front().state.bitmap.source, 800, 600).pixels();
        const auto upper = (std::size_t(std::round(center_y - 4 * scale)) * 800 + std::size_t(std::round(right + 6 * scale))) * 3;
        const auto tip = (std::size_t(std::round(center_y)) * 800 + std::size_t(std::round(right))) * 3;
        check(pixels[upper] == pixels[tip] && pixels[upper + 1] == pixels[tip + 1] && pixels[upper + 2] == pixels[tip + 2],
              "Common return arrowhead does not enter the target from the right");
        const auto long_edge = tinyenv::parse_passive_diagram(std::string("flowchart ") + direction +
            "\nA[Start] --> B[Work]\nB --> C[Done]\nC -- Retry --> A\n");
        const auto labeled = view.render(long_edge, {0,0,800,600}, "long");
        const auto retry = std::find_if(labeled.begin(), labeled.end(), [](const auto& w) { return w.state.text == "Retry"; });
        check(retry != labeled.end() && gui::has_area(retry->state.bounds), "Long retry route lost its visible label");
        for (const auto& widget : labeled) if (widget.spec.key.id.find(".node.") != std::string::npos)
            check(!gui::has_area(gui::intersect(retry->state.bounds, widget.state.bounds)), "Long edge label still covers intervening node text");
    }
    auto mutable_edge = branch;
    mutable_edge.edges[1].label = "raw \xE2\x80\xAE" "text\\u003C";
    const auto safe_widgets = view.render(mutable_edge, {0,0,400,600}, "safeedge");
    check(std::any_of(safe_widgets.begin(), safe_widgets.end(), [](const auto& widget) { return widget.state.text == "raw ___text_"; }),
          "Public edge model bypassed render-boundary projection");
    invalid_model([](auto& d) { d.edges[0].label = "<script>"; });
    invalid_model([](auto& d) { d.edges[0].label = std::string(81, 'x'); });
}

std::string without_styles(std::string_view source) {
    std::string result;
    for (std::size_t at = 0; at < source.size();) {
        const auto newline = source.find('\n', at), end = newline == std::string_view::npos ? source.size() : newline;
        const auto line = source.substr(at, end - at);
        const auto begin = line.find_first_not_of(' ');
        if (begin == std::string_view::npos || !line.substr(begin).starts_with("style ")) { result += line; result += '\n'; }
        if (newline == std::string_view::npos) break;
        at = newline + 1;
    }
    return result;
}
void reported_flowchart_regressions() {
    for (std::size_t index = 0; index < std::size(reported_flowcharts); ++index) {
        const auto raw = reported_flowcharts[index];
        const auto original = std::string(raw);
        const auto model = tinyenv::parse_passive_diagram(raw);
        check(model.supported && model.direction == tinyenv::PassiveDiagramDirection::top_down && model.nodes.size() == (index == 0 ? 6 : 8) && model.edges.size() == (index == 0 ? 5 : 7),
              "Reported colon/slash/style flowchart did not retain its complete graph");
        const auto assert_node = [&](std::string_view id, std::string_view label) {
            const auto found = std::find_if(model.nodes.begin(), model.nodes.end(), [&](const auto& node) { return node.id == id; });
            check(found != model.nodes.end() && found->label == label, "Reported graph lost a literal node label");
        };
        if (index == 0) {
            assert_node("A", "Start: User wants a flowchart"); assert_node("B", "What type?");
            assert_node("C", "Generate ASCII/Mermaid code"); assert_node("D", "Render image");
            assert_node("E", "Output code"); assert_node("F", "User copies/pastes to renderer");
            check(model.edges[1].label == "Text-based" && model.edges[2].label == "Visual (if capable)", "Reported dashed branch labels were lost");
        } else {
            assert_node("A", "Start: User requests flowchart"); assert_node("B", "Select Style");
            assert_node("C", "Generate ASCII Art"); assert_node("D", "Generate Mermaid Code");
            assert_node("E", "Output ASCII Diagram"); assert_node("F", "Output Mermaid Code");
            assert_node("G", "User views in terminal"); assert_node("H", "User pastes to renderer");
            check(model.edges[1].label == "Text-based ASCII" && model.edges[2].label == "Mermaid Syntax", "Reported pipe branch labels were lost");
        }
        const auto plain = tinyenv::parse_passive_diagram(without_styles(raw));
        check(plain.supported && plain.nodes == model.nodes && plain.edges == model.edges && plain.direction == model.direction,
              "Inert styles changed diagram semantics");
        tinyenv::PassiveDiagramView view;
        const auto styled_widgets = view.render(model, {0,0,640,900}, "reported");
        const auto plain_widgets = view.render(plain, {0,0,640,900}, "reported");
        check(sample(styled_widgets.front().state.bitmap.source, 640, 900).pixels() == sample(plain_widgets.front().state.bitmap.source, 640, 900).pixels(),
              "Validated style declarations changed the fixed raster palette or stroke");
        check(styled_widgets.size() == model.nodes.size() + 3 && styled_widgets.size() == plain_widgets.size(), "Reported nodes or branch labels did not reach native widgets");
        for (std::size_t widget = 1; widget < styled_widgets.size(); ++widget) {
            const auto& styled = styled_widgets[widget]; const auto& unstyled = plain_widgets[widget];
            check(styled.spec.kind == gui::Kind::label && styled.state.text == unstyled.state.text && styled.state.font == unstyled.state.font && styled.state.bounds == unstyled.state.bounds,
                  "Ignored styles changed a native label's text, font or position");
            check(!styled.spec.pointer_input && !styled.spec.context_input && styled.state.actions.empty() && styled.state.options.empty(), "Reported style acquired native interaction");
        }
        for (const auto& node : model.nodes)
            check(std::any_of(styled_widgets.begin(), styled_widgets.end(), [&](const auto& widget) { return widget.spec.kind == gui::Kind::label && widget.state.text == node.label; }),
                  "Reported model label disappeared from the bitmap's native text overlay");
        const auto branch_widgets = view.render(model, {0,0,600,std::ceil(tinyenv::passive_diagram_height(model,600))}, "branch-geometry");
        forward_branch_geometry(model, branch_widgets);
        check(raw == original, "Diagram rendering rewrote the fixture source");
    }
    const auto punctuation = tinyenv::parse_passive_diagram("graph TD\nA[Step 1: Build (local) / x+y=1's] --> B[Done]");
    check(punctuation.supported && punctuation.nodes[0].label == "Step 1: Build (local) / x+y=1's", "Delimiter-bounded unquoted ASCII punctuation was rejected");
    rejected("graph TD\nA[Step 1; Build]");
    rejected("graph TD\nA[<script>]"); rejected("graph TD\nA[@symbol]");
}
void inert_style_boundaries() {
    const std::string base = "graph TD\nA[Start] --> B[Done]\n";
    const auto plain = tinyenv::parse_passive_diagram(base);
    for (const auto style : {"style A fill:#f9f", "style A stroke:#123456", "style A stroke-width:1px", "style A stroke-width:8px",
                             "style A stroke:#ABCDEF,fill:#aBc,stroke-width:2px", "style A fill : #abc , stroke : #123456 , stroke-width : 8px"}) {
        const auto model = tinyenv::parse_passive_diagram(base + style);
        check(model.supported && model.nodes == plain.nodes && model.edges == plain.edges, "Valid bounded inert style was rejected or changed graph semantics");
        tinyenv::PassiveDiagramView view;
        const auto styled = view.render(model, {0,0,400,240}, "styles");
        const auto unstyled = view.render(plain, {0,0,400,240}, "styles");
        check(sample(styled.front().state.bitmap.source, 400, 240).pixels() == sample(unstyled.front().state.bitmap.source, 400, 240).pixels(),
              "Allowed colors or stroke widths changed the fixed display palette");
    }
    const std::string short_style = "style A fill:#abc";
    const std::string exact_style = "style A " + std::string(128 - short_style.size(), ' ') + "fill:#abc";
    check(exact_style.size() == 128 && tinyenv::parse_passive_diagram(base + exact_style).supported, "Exact inert-style statement budget was rejected");
    rejected(base + "style A  " + exact_style.substr(8));
    for (const auto style : {
        "style Z fill:#abc", "style a fill:#abc", "style AB fill:#abc", "style A,B fill:#abc", "style A", "style A fill:", "style A ,fill:#abc", "style A fill:#abc,", "style A fill:#abc,,stroke:#123",
        "style A fill:#abc,fill:#def", "style A fill:#abc,stroke:#123,stroke-width:2px,fill:#def", "style A color:#abc", "style A Fill:#abc",
        "style A fill:red", "style A fill:#ab", "style A fill:#abcd", "style A fill:#abcde", "style A fill:#abcdef0", "style A fill:#00000000", "style A fill:#ggg",
        "style A stroke-width:0px", "style A stroke-width:9px", "style A stroke-width:10px", "style A stroke-width:1.0px", "style A stroke-width:+2px", "style A stroke-width:-2px",
        "style A stroke-width:2PX", "style A stroke-width:2em", "style A stroke-width:2px!important", "style A stroke-width:2px/*comment*/",
        "style A fill:url(https://example.test/x)", "style A fill:expression(alert(1))", "style A stroke:url(file:///tmp/x)", "style A stroke-width:calc(2px)",
        "style A fill:\\u0023abc", "style A fill:%23abc", "style A fill:&#35;abc", "style A fill:[U+0023]abc", "style A \\u0066ill:#abc", "style A %66ill:#abc", "style A stroke-width:1\\u0070x",
        "style A fill:\t#abc", "style A fill:\n#abc",
        "style A fill:#abc click A", "style A fill:#abc;click A", "style A fill:#abc,onclick:alert(1)", "style A fill:#abc background-image:url(x)"
    }) rejected(base + style);
    rejected(base + std::string("style A fill:") + '\0' + "#abc");
    rejected("graph TD\nstyle A fill:#abc\nA[Start] --> B[Done]\n");
    const auto implicit = tinyenv::parse_passive_diagram("graph TD\nA --> B; style B fill:#abc; B[Done]");
    check(implicit.supported && implicit.nodes.size() == 2 && implicit.nodes[1].id == "B" && implicit.nodes[1].label == "Done" && implicit.edges.size() == 1,
          "Style validation changed an existing implicit node or later label");
    rejected(base + "style A fill:#abc\nclick A href \"https://example.test/\"");
    std::string styles = "graph TD\nA\n";
    for (unsigned index = 0; index < 126; ++index) styles += "style A fill:#abc\n";
    check(tinyenv::parse_passive_diagram(styles).supported, "Styles did not share the existing exact statement budget");
    rejected(styles + "style A fill:#abc\n");
}

void budgets() {
    std::string nodes = "graph TD\n";
    for (std::size_t i = 0; i < tinyenv::passive_diagram_node_limit; ++i) nodes += "N" + std::to_string(i) + "\n";
    check(tinyenv::parse_passive_diagram(nodes).supported, "Exact node budget was rejected");
    rejected(nodes + "Extra\n");
    std::string edges = "graph TD\n";
    for (std::size_t i = 0; i < tinyenv::passive_diagram_edge_limit; ++i) edges += "A-->B\n";
    check(tinyenv::parse_passive_diagram(edges).supported, "Exact edge budget was rejected");
    rejected(edges + "A-->B\n");
    check(tinyenv::parse_passive_diagram("graph TD\nA[" + std::string(tinyenv::passive_diagram_label_limit, 'x') + "]").supported,
          "Exact label budget was rejected");
    rejected("graph TD\nA[" + std::string(tinyenv::passive_diagram_label_limit + 1, 'x') + "]");
    check(tinyenv::parse_passive_diagram("graph TD\n" + std::string(32, 'a')).supported, "Exact identifier budget was rejected");
    rejected("graph TD\n" + std::string(33, 'a'));
    std::string statements = "graph TD\n";
    for (unsigned i = 0; i < 127; ++i) statements += "A\n";
    check(tinyenv::parse_passive_diagram(statements).supported, "Exact statement budget was rejected");
    rejected(statements + "A\n");
    std::string source = "graph TD\nA";
    source.resize(tinyenv::passive_diagram_input_limit, ' ');
    check(tinyenv::parse_passive_diagram(source).supported, "Exact input budget was rejected");
    rejected(source + " ");
}

void rendering() {
    const auto model = tinyenv::parse_passive_diagram("flowchart TD\nA[Start] --> B{Ready?}\nB --> C[Done]\nC --> A\nA --> A");
    tinyenv::PassiveDiagramView view;
    auto widgets = view.render(model, {10, 20, 400, 240}, "test", "parent");
    check(widgets.size() == model.nodes.size() + 1 && widgets[0].spec.kind == gui::Kind::bitmap, "Diagram did not use the generic bitmap/label vocabulary");
    for (const auto& widget : widgets) {
        check(!widget.spec.pointer_input && !widget.spec.context_input && widget.state.actions.empty(), "Passive diagram acquired interaction or actions");
        check(printable(widget.state.text) && printable(widget.state.accessible_name), "Passive diagram exposed unsafe display/accessibility text");
        check(widget.spec.parent == "parent" && gui::valid_rect(widget.state.bounds), "Diagram lost parent or valid geometry");
    }
    const auto retained = widgets[0].state.bitmap.source;
    const auto original = sample(retained, 400, 240).pixels();
    check(std::adjacent_find(original.begin(), original.end(), std::not_equal_to<>()) != original.end(), "Diagram raster was blank");
    auto modified = model;
    modified.nodes[0].label = "raw \xE2\x80\xAE" "text\\u003C";
    modified.sanitized_source = std::string(100000, 'x');
    modified.diagnostic = std::string(100000, 'x');
    const auto projected = view.render(modified, {0, 0, 300, 200}, "projected");
    check(projected[1].state.text == "raw ___text_", "Public model labels bypassed shared safety projection");
    check(sample(retained, 400, 240).pixels() == original, "Later render mutated a retained diagram raster");
    gui::BitmapSource after_scope;
    {
        tinyenv::PassiveDiagramView temporary;
        const auto scoped_model = tinyenv::parse_passive_diagram("graph TD\nA[Scoped]");
        after_scope = temporary.render(scoped_model, {0, 0, 240, 120}, "scoped").front().state.bitmap.source;
    }
    check(!sample(after_scope, 240, 120).pixels().empty(), "Diagram source depended on expired view/model lifetime");
    const auto box = tinyenv::parse_passive_diagram("graph TD\nA[Shape]");
    const auto rounded = tinyenv::parse_passive_diagram("graph TD\nA(Shape)");
    const auto box_pixels = sample(view.render(box, {0, 0, 240, 120}, "box").front().state.bitmap.source, 240, 120).pixels();
    const auto round_pixels = sample(view.render(rounded, {0, 0, 240, 120}, "round").front().state.bitmap.source, 240, 120).pixels();
    check(box_pixels != round_pixels, "Rounded node shape did not change raster corners");
    for (const auto format : {gui::PixelFormat::rgb24, gui::PixelFormat::gray8, gui::PixelFormat::mono1}) {
        for (const auto size : {gui::Size{400, 240}, gui::Size{157, 113}}) {
            const auto width = unsigned(size.width), height = unsigned(size.height);
            const auto full = sample(retained, width, height, format);
            gui::BitmapImage tiled(width, height, format);
            const unsigned split = width / 2;
            for (const auto damage : {gui::PixelRect{0, 0, split, height}, gui::PixelRect{split, 0, width - split, height}})
                retained.paint({width, height, damage, format}, [&](unsigned x, unsigned y, gui::PixelBlock block) { tiled.blit(x, y, block); });
            check(tiled.pixels() == full.pixels(), "Damage sampling changed a retained diagram raster");
            if (format != gui::PixelFormat::rgb24) {
                const auto rgb = sample(retained, width, height);
                gui::BitmapImage expected(width, height, format);
                expected.blit(0, 0, rgb.block());
                check(full.pixels() == expected.pixels(), "Diagram format conversion disagreed with the generic boundary");
            }
        }
    }
    bool excessive = false;
    try { retained.paint(gui::full_bitmap_request(4096, 4096), [](unsigned, unsigned, gui::PixelBlock) {}); }
    catch (const std::length_error&) { excessive = true; }
    check(excessive, "Unbounded diagram sampling was accepted");
    retained.paint(gui::full_bitmap_request(4096, 512), [](unsigned, unsigned, gui::PixelBlock) {});
    for (const auto size : {gui::Size{4096, 513}, gui::Size{4097, 1}}) {
        bool rejected_grid = false;
        try { retained.paint(gui::full_bitmap_request(unsigned(size.width), unsigned(size.height)), [](unsigned, unsigned, gui::PixelBlock) {}); }
        catch (const std::length_error&) { rejected_grid = true; }
        check(rejected_grid, "Axis or pixel sampling limit did not reject one-over request");
    }
    for (const auto direction : {"TD", "LR", "RL", "BT"}) {
        auto graph = tinyenv::parse_passive_diagram(std::string("graph ") + direction + "\nA-->B\nB-->A");
        check(!view.render(graph, {0, 0, 10000, 10000}, "large").empty(), "Large bounded cyclic canvas failed");
        const double height = tinyenv::passive_diagram_height(graph, 400);
        check(std::isfinite(height) && height >= 96 && height <= 1536, "Diagram height escaped its finite bound");
    }
    std::string chain_source = "graph TD\n";
    for (std::size_t i = 1; i < tinyenv::passive_diagram_node_limit; ++i)
        chain_source += "N" + std::to_string(i - 1) + "-->N" + std::to_string(i) + "\n";
    const auto chain = tinyenv::parse_passive_diagram(chain_source);
    check(chain.supported && view.render(chain, {0, 0, 400, 1536}, "chain").size() == 33, "Maximum-depth graph escaped finite rank layout");
    const auto mixed = tinyenv::parse_passive_diagram("graph LR\nA-->B-->C\nX-->Y-->X\nP\nQ\nR\nS\nT\nU");
    check(mixed.supported && !view.render(mixed, {0, 0, 500, 240}, "mixed").empty(), "Mixed DAG/cyclic graph escaped finite rank layout");
    check(!view.render(model, {0, 0, 1, 1}, "one").empty(), "Minimum valid pixel viewport failed");
    check(!view.render(model, {0, 0, 10000, 1}, "thin").empty(), "Extreme-aspect finite viewport failed");
    check(view.render(model, {0, 0, std::numeric_limits<double>::denorm_min(), 1}, "tiny").empty(), "Denormal viewport reached raster division");
    check(view.render(model, {0, 0, .5, .5}, "tiny").empty(), "Subpixel viewport created raster work");
    for (const auto value : {std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::infinity(), -1.0}) {
        bool failed = false;
        try { (void)view.render(model, {0, 0, value, 240}, "invalid"); }
        catch (const std::invalid_argument&) { failed = true; }
        check(failed, "Invalid viewport reached raster math");
    }
    invalid_model([](auto& d) { d.supported = false; });
    invalid_model([](auto& d) { d.nodes.clear(); });
    invalid_model([](auto& d) { d.nodes[0].label = "<script>"; });
    invalid_model([](auto& d) { d.nodes[0].label = std::string(81, 'x'); });
    invalid_model([](auto& d) { d.nodes[0].id = "unsafe@id"; });
    invalid_model([](auto& d) { d.nodes[0].shape = static_cast<tinyenv::PassiveDiagramShape>(999); });
    invalid_model([](auto& d) { d.direction = static_cast<tinyenv::PassiveDiagramDirection>(999); });
    invalid_model([](auto& d) { d.nodes[1].id = d.nodes[0].id; });
    invalid_model([](auto& d) { d.edges[0].to = d.nodes.size(); });
    invalid_model([](auto& d) { d.nodes.resize(tinyenv::passive_diagram_node_limit + 1); });
    invalid_model([](auto& d) { d.edges.resize(tinyenv::passive_diagram_edge_limit + 1); });
}
}

int main() {
    try { sanitizer(); grammar(); common_flowcharts(); reported_flowchart_regressions(); inert_style_boundaries(); budgets(); rendering(); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return 0;
}
