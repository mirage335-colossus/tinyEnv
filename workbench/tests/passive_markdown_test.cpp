#include "workbench/ui/passive_markdown.hpp"
#include "workbench/ui/passive_diagram.hpp"
#include <gui/bitmap.hpp>

#include <algorithm>
#include <cmath>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>

namespace {
// Only the graph bodies involved in the reported rendering failure are kept.
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
void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
bool ascii(std::string_view text) {
    return std::all_of(text.begin(), text.end(), [](unsigned char ch) { return ch == '\n' || (ch >= 32 && ch <= 126); });
}
void safe_document(const tinyenv::PassiveMarkdownDocument& document, tinyenv::PassiveMarkdownLimits limits = {}) {
    check(ascii(document.display_text), "Display projection contains a forbidden character");
    check(document.display_text.size() <= limits.display_bytes, "Display byte cap exceeded");
    check(document.blocks.size() <= limits.blocks, "Block count cap exceeded");
    for (const auto& block : document.blocks) {
        check(ascii(block.text) && ascii(block.fence_language), "Block contains a forbidden character");
        check(block.text.size() <= limits.block_bytes, "Block byte cap exceeded");
        check(block.kind != tinyenv::PassiveMarkdownKind::table || (block.table_columns > 0 && block.table_columns <= 8 && block.table_rows <= 32 && block.complete),
              "A rendered table exceeded metadata bounds or was split");
        if (block.kind == tinyenv::PassiveMarkdownKind::table) {
            check(block.table_cells.size() == block.table_rows + 1 && block.table_alignment.size() == block.table_columns,
                  "Table structured rows/alignment do not match metadata");
            for (const auto& row : block.table_cells) {
                check(row.size() == block.table_columns, "Table model retained ragged cells");
                for (const auto& cell : row) check(ascii(cell) && cell.size() <= 128, "Table cell bypassed ASCII or byte bounds");
            }
        } else check(block.table_cells.empty() && block.table_alignment.empty(), "Literal fallback retained a partial table model");
    }
    if (document.truncated()) check(!document.blocks.empty() && document.blocks.front().kind == tinyenv::PassiveMarkdownKind::notice,
                                   "Preview truncation has no visible leading notice");
}
void blocks() {
    const std::string source = "# Title\n\nordinary **bold** `code` \\*escaped\\*\n\n- first\n12) second\n\n> quoted\n>> second quote stays literal\n\n```cpp\n\n<script>literal</script>\n\n```\n";
    const auto before = source;
    auto parsed = tinyenv::parse_passive_markdown(source); safe_document(parsed);
    check(source == before, "Parser changed the original source");
    check(parsed.blocks.size() == 7, "Bounded block grammar changed");
    check(parsed.blocks[0].kind == tinyenv::PassiveMarkdownKind::heading && parsed.blocks[0].text == "Title" && parsed.blocks[0].heading_level == 1, "Heading was not projected");
    check(parsed.blocks[1].text == "ordinary **bold** `code` \\*escaped\\*", "Inline syntax was evaluated");
    check(parsed.blocks[2].kind == tinyenv::PassiveMarkdownKind::list && parsed.blocks[2].text == "- first", "Unordered list marker was lost");
    check(parsed.blocks[3].text == "12) second", "Ordered list marker was lost");
    check(parsed.blocks[4].kind == tinyenv::PassiveMarkdownKind::quote && parsed.blocks[4].text == "quoted" && parsed.blocks[4].quote_depth == 1,
          "First quote depth was not retained");
    check(parsed.blocks[5].kind == tinyenv::PassiveMarkdownKind::quote && parsed.blocks[5].text == "second quote stays literal" && parsed.blocks[5].quote_depth == 2,
          "Nested quote did not retain its own block depth");
    check(parsed.blocks[6].kind == tinyenv::PassiveMarkdownKind::code && parsed.blocks[6].text == "\n<script>literal</script>\n\n" && parsed.blocks[6].closed, "Fenced code whitespace or inert content changed");
    const auto quoted = tinyenv::parse_passive_markdown("> ## Assistant title\n> - item\n> ```mermaid\n> flowchart TD\n> A[Hello] --> B[Done]\n> ```\n");
    safe_document(quoted);
    check(quoted.blocks.size() == 3 && quoted.blocks[0].kind == tinyenv::PassiveMarkdownKind::heading && quoted.blocks[0].quoted,
          "Saved reply heading was not parsed inside one quote layer");
    check(quoted.blocks[2].fence_language == "mermaid" && quoted.blocks[2].text.starts_with("flowchart TD\n") && quoted.blocks[2].closed,
          "Saved quoted reply fence was not projected");
    for (const auto text : {"```\n# literal\n~~\n", "~~~~\n```\n# literal\n~~~\n", "```\n# literal"}) {
        const auto partial = tinyenv::parse_passive_markdown(text); safe_document(partial);
        check(partial.blocks.size() == 1 && partial.blocks.front().kind == tinyenv::PassiveMarkdownKind::code && !partial.blocks.front().closed,
              "Malformed or partial fence escaped its literal code block");
    }
}
void characters_and_inert_syntax() {
    std::string bytes; for (unsigned byte = 0; byte < 256; ++byte) bytes += static_cast<char>(byte);
    const auto every_byte = tinyenv::parse_passive_markdown(bytes); safe_document(every_byte);
    check(every_byte.display_text.find("[U+0000]") != std::string::npos && every_byte.display_text.find("[U+001B]") != std::string::npos && every_byte.display_text.find("[U+007F]") != std::string::npos,
          "Control bytes were invisible or removed");
    const std::string source = "a\t b\r\nc\rd \xE2\x80\x8D \xE2\x80\xAE \xE2\x81\xA6 \xE2\x80\xA8 \xC2\xA0 \xF0\x9F\x99\x82 \xF4\x8F\xBF\xBF \xE0\x80\xAF \xED\xA0\x80 \xE2\x80";
    const auto parsed = tinyenv::parse_passive_markdown(source); safe_document(parsed);
    for (const auto escape : {"[U+200D]", "[U+202E]", "[U+2066]", "[U+2028]", "[U+00A0]", "[U+1F642]", "[U+10FFFF]", "[0xE0]", "[0xED]", "[0xE2]", "[0x80]"})
        check(parsed.display_text.find(escape) != std::string::npos, "A codepoint or malformed byte was not visibly escaped");
    check(parsed.display_text.starts_with("a     b\nc[U+000D]d"), "Tab or CRLF normalization changed");
    const std::string inert = "<script>alert(1)</script> <img src=file:///tmp/x> [go](javascript:alert(1)) ![x](https://example.invalid/x) <https://example.invalid> &lt; &#x3C; \\u202E %E2%80%8D [U+200D] [0x1B] \\x1b [ref]: file:///tmp/x";
    const auto literal = tinyenv::parse_passive_markdown(inert); safe_document(literal);
    check(literal.display_text == inert, "HTML, URL, entity, percent or escape syntax was evaluated");
    const auto hidden = tinyenv::parse_passive_markdown("#\xE2\x80\x8D title\n`\x01``\n>\x01 quote\n");
    safe_document(hidden);
    check(hidden.blocks.front().kind == tinyenv::PassiveMarkdownKind::paragraph && hidden.blocks.front().text.starts_with("#[U+200D]"),
          "Sanitization silently joined a heading delimiter");
}
void bounds_and_tail() {
    tinyenv::PassiveMarkdownLimits limits{4096, 1024, 128, 8};
    for (const auto size : {127U,128U,129U,4095U,4096U,4097U,10000U}) {
        const auto parsed = tinyenv::parse_passive_markdown(std::string(size, 'a') + "newest", limits); safe_document(parsed, limits);
        if (!parsed.display_text.ends_with("newest")) throw std::runtime_error("Newest long-line content was omitted at " + std::to_string(size) + ": " + parsed.display_text.substr(parsed.display_text.size() > 40 ? parsed.display_text.size() - 40 : 0));
    }
    const auto escaped = tinyenv::parse_passive_markdown(std::string(10000, '\x01') + "newest", limits); safe_document(escaped, limits);
    check(escaped.display_truncated && escaped.display_text.ends_with("newest"), "Expanded display cap discarded the newest content");
    const tinyenv::PassiveMarkdownLimits tiny_display{4096,512,8192,8};
    const auto retained = tinyenv::parse_passive_markdown(std::string(4000, 'a') + "newest", tiny_display); safe_document(retained, tiny_display);
    check(retained.display_text.ends_with("newest"), "A small display budget discarded the newest block");
    for (const auto& block : escaped.blocks) if (block.kind != tinyenv::PassiveMarkdownKind::notice) {
        for (std::size_t at = 0; at < block.text.size();) {
            if (std::string_view(block.text).substr(at, 8) == "[U+0001]") at += 8;
            else { check(std::string_view("newest").find(block.text[at]) != std::string_view::npos, "An escape atom was cut"); ++at; }
        }
    }
    std::string headings; for (unsigned index = 0; index < 300; ++index) headings += "# heading " + std::to_string(index) + '\n';
    const auto numerous = tinyenv::parse_passive_markdown(headings, limits); safe_document(numerous, limits);
    check(numerous.blocks_truncated && numerous.display_text.ends_with("heading 299"), "Block cap did not retain newest headings");
    const auto source_tail = tinyenv::parse_passive_markdown("# earlier\n" + std::string(10000, 'x') + "\n## newest\n", limits); safe_document(source_tail, limits);
    check(source_tail.source_truncated && source_tail.blocks.back().kind == tinyenv::PassiveMarkdownKind::heading && source_tail.blocks.back().text == "newest", "Source tail boundary lost the newest heading");
    const auto fenced_tail = tinyenv::parse_passive_markdown("```mermaid\n" + std::string(10000, 'x') + "\nflowchart TD\nA --> B\n```\n## newest\n", limits); safe_document(fenced_tail, limits);
    check(fenced_tail.blocks[1].kind == tinyenv::PassiveMarkdownKind::code && fenced_tail.blocks[1].fence_language.empty(), "A fence begun outside the retained preview became a rich diagram");
    check(fenced_tail.blocks.back().text == "newest", "Fence tail context hid the following heading");
    const auto control_close = tinyenv::parse_passive_markdown("~~~\n~~~\r\r\n" + std::string(10000, 'x') + "\n```mermaid\nflowchart TD\nA --> B\n```\n## literal\n", limits);
    safe_document(control_close, limits);
    check(control_close.blocks.back().kind == tinyenv::PassiveMarkdownKind::code && control_close.blocks.back().fence_language.empty(), "Prefix controls silently closed a retained fence");
    const auto oversized = tinyenv::parse_passive_markdown(std::string(8 * 1024 * 1024 + 1, 'x') + "\n```mermaid\nflowchart TD\nA --> B\n```\n"); safe_document(oversized);
    check(std::none_of(oversized.blocks.begin(), oversized.blocks.end(), [](const auto& block) { return block.kind == tinyenv::PassiveMarkdownKind::code; }), "Out-of-contract prefix triggered rich syntax");
    bool rejected = false; try { (void)tinyenv::parse_passive_markdown("text", {1,512,128,257}); } catch (const std::invalid_argument&) { rejected = true; }
    check(rejected, "Unbounded caller limits were accepted");
}
void native_projection_and_cache() {
    tinyenv::PassiveMarkdownView view;
    std::size_t measured = 0;
    const gui::TextMeasure measure = [&](const auto&) { ++measured; return gui::Size{100,20}; };
    const gui::Rect area{0,0,400,300};
    const auto widgets = view.render("# Stable\n\nparagraph", area, "preview", "", measure);
    gui::Snapshot snapshot; snapshot.client_size = {400,300}; snapshot.widgets = widgets; gui::validate_snapshot(snapshot);
    check(widgets.front().spec.kind == gui::Kind::group && widgets[1].state.font.bold && widgets[1].state.font.size == 20, "Heading did not use native font styling");
    for (const auto& widget : widgets) {
        check(widget.spec.kind == gui::Kind::group || widget.spec.kind == gui::Kind::text, "Ordinary Markdown used an active or raster widget");
        if (widget.spec.kind == gui::Kind::text) {
            check(widget.state.enabled && widget.spec.text_policy.read_only && widget.spec.text_policy.multiline && widget.spec.text_policy.submit == gui::SubmitKey::none,
                  "Text block lost readonly selection/copy semantics");
            check(widget.state.options.empty() && widget.state.actions.empty() && !widget.spec.pointer_input && !widget.spec.context_input,
                  "Text block exposed a resource or active capability");
            gui::Event edit = gui::WidgetEvent{widget.spec.key, gui::EditText{"changed", widget.state.text}};
            gui::Event submit = gui::WidgetEvent{widget.spec.key, gui::SubmitText{}};
            check(!gui::normalize_event(snapshot, edit) && !gui::normalize_event(snapshot, submit), "Readonly Markdown accepted edit or submit events");
        }
    }
    const auto revision = view.revision(), count = measured;
    const auto repeated = view.render("# Stable\n\nparagraph", area, "preview", "", measure);
    check(view.revision() == revision && measured == count && repeated[1].spec.key == widgets[1].spec.key, "Unchanged presentation reparsed or remeasured blocks");
    const auto streamed = view.render("# Stable\n\nparagraph extended", area, "preview", "", measure);
    check(measured == count + 1 && streamed[1].spec.key == widgets[1].spec.key, "Streamed append rebuilt an unaffected heading");
    const auto before_versioned = view.revision();
    view.render("# Version\n\ntext", area, "preview", "", measure, 1, 1);
    const auto versioned = view.revision();
    view.render("# Version\n\ntext", area, "preview", "", measure, 1, 1);
    check(versioned == before_versioned + 1 && view.revision() == versioned, "Authoritative content version was not cached");
    view.render("# Changed\n\ntext", area, "preview", "", measure, 1, 2);
    check(view.revision() == versioned + 1 && view.document().blocks.front().text == "Changed", "Changed content version retained stale text");
    tinyenv::PassiveMarkdownView tail_view({256,1024,128,8});
    std::string contextual = "~~~\n"; for (unsigned index = 0; index < 100; ++index) contextual += "padding\n"; contextual += "## latest\n";
    tail_view.render(contextual, area, "tail", "", measure);
    check(tail_view.document().blocks.back().kind == tinyenv::PassiveMarkdownKind::code, "Retained prefix fence context was lost");
    const auto contextual_revision = tail_view.revision(); contextual.replace(0, 3, "abc");
    tail_view.render(contextual, area, "tail", "", measure);
    check(tail_view.revision() == contextual_revision + 1 && tail_view.document().blocks.back().kind == tinyenv::PassiveMarkdownKind::heading,
          "Same-length prefix edit retained obsolete fence context");
    for (const auto& text : {std::string(20000, 'a'), std::string(20000, '\n') + "end", std::string{}}) {
        snapshot.widgets = view.render(text, {0,0,20,300}, "preview", "", measure, 16); gui::validate_snapshot(snapshot);
        for (const auto& widget : snapshot.widgets) if (widget.spec.kind == gui::Kind::text) check(widget.state.bounds.height <= 240, "Native block height was unbounded");
    }
    bool rejected = false; try { view.render("text", area, "preview", "", [](const auto&) { return gui::Size{1,std::numeric_limits<double>::quiet_NaN()}; }); } catch (const std::invalid_argument&) { rejected = true; }
    // Change width to invalidate a preceding valid cached measurement.
    if (!rejected) try { view.render("text", {0,0,401,300}, "preview", "", [](const auto&) { return gui::Size{1,std::numeric_limits<double>::quiet_NaN()}; }); } catch (const std::invalid_argument&) { rejected = true; }
    check(rejected, "Invalid geometry from a measurement callback was accepted");
}
const tinyenv::PassiveMarkdownBlock& named_block(const tinyenv::PassiveMarkdownDocument& document, std::string_view text) {
    const auto found = std::find_if(document.blocks.begin(), document.blocks.end(), [&](const auto& block) { return block.text == text; });
    if (found == document.blocks.end()) throw std::runtime_error("Missing Markdown block: " + std::string(text));
    return *found;
}
const gui::Widget& named_text(const std::vector<gui::Widget>& widgets, std::string_view text) {
    const auto found = std::find_if(widgets.begin(), widgets.end(), [&](const auto& widget) { return widget.spec.kind == gui::Kind::text && widget.state.text == text; });
    if (found == widgets.end()) throw std::runtime_error("Missing native Markdown text: " + std::string(text));
    return *found;
}
void richer_passive_blocks() {
    using Kind = tinyenv::PassiveMarkdownKind;
    using Role = tinyenv::PassiveMarkdownRole;
    // The reported chat uses two quote layers around this fence: one for saved
    // assistant storage, then one for the example nested inside that reply.
    const std::string table = "+--------+----------+\n| apple  | red      |\n+--------+----------+\n| banana | yellow   |\n+--------+----------+\n";
    const std::string source = "## Assistant\n\n> > a nested introduction\n>\n> ### 1. The Invisible Table\n"
        "> Mixed *shape* and **Word: Definition** and `inline code` remain readable.\n>\n> **Prompt Example:**\n"
        "> > Input: `apple red, banana yellow`\n> > Output:\n> > ```text\n> > +--------+----------+\n"
        "> > | apple  | red      |\n> > +--------+----------+\n> > | banana | yellow   |\n> > +--------+----------+\n> > ```\n"
        ">\n> ***\n>\n> **Want to try one?** Tell me what you have.\n";
    const auto original = source;
    const auto parsed = tinyenv::parse_passive_markdown(source); safe_document(parsed);
    const auto& code = named_block(parsed, table);
    check(code.kind == Kind::code && code.quote_depth == 2 && code.quoted && code.closed && code.complete && code.fence_language == "text" &&
          code.role == Role::assistant && !code.message_title && !code.strong, "Reported nested ASCII table did not become exact native code");
    const auto& strong = named_block(parsed, "Prompt Example:");
    check(strong.strong && strong.quote_depth == 1 && strong.kind == Kind::quote && strong.role == Role::assistant,
          "Standalone reported strong paragraph did not retain its native-bold meaning");
    const auto& mixed = named_block(parsed, "Mixed *shape* and **Word: Definition** and `inline code` remain readable.");
    check(!mixed.strong, "Mixed inline syntax was flattened to an unsupported whole-block font");
    const auto& rule = named_block(parsed, "--------------------------------");
    check(rule.kind == Kind::rule && rule.quote_depth == 1 && rule.role == Role::assistant && !rule.message_title,
          "Quoted thematic break did not become an assistant separator");
    check(!named_block(parsed, "**Want to try one?** Tell me what you have.").strong, "Mixed strong paragraph lost literal markers");
    tinyenv::PassiveMarkdownView view; std::size_t measured = 0;
    const gui::TextMeasure measure = [&](const auto&) { ++measured; return gui::Size{100,20}; };
    gui::Snapshot snapshot; snapshot.client_size = {640,900};
    snapshot.widgets = view.render(source, {0,0,640,900}, "richer", "", measure); gui::validate_snapshot(snapshot);
    const auto& title = named_text(snapshot.widgets, "Assistant");
    const auto& table_widget = named_text(snapshot.widgets, table);
    check(table_widget.state.wrap == gui::TextWrap::none && table_widget.state.text == table && table_widget.state.bounds.x == title.state.bounds.x + 12,
          "Nested ASCII table was wrapped, changed or lost its quote indentation");
    check(named_text(snapshot.widgets, "Prompt Example:").state.font.bold && named_text(snapshot.widgets, "Prompt Example:").state.bounds.x == title.state.bounds.x,
          "Whole-block strong styling shifted the assistant storage lane");
    const auto& separator = named_text(snapshot.widgets, "--------------------------------");
    check(separator.state.bounds.height < named_text(snapshot.widgets, "Prompt Example:").state.bounds.height && separator.state.wrap == gui::TextWrap::none,
          "Thematic separator did not retain compact native geometry");
    for (const auto& widget : snapshot.widgets) {
        check(widget.spec.kind == gui::Kind::group || widget.spec.kind == gui::Kind::text, "Rich passive blocks introduced an active or raster capability");
        if (widget.spec.kind == gui::Kind::text) {
            check(widget.spec.text_policy.read_only && widget.spec.text_policy.multiline && !widget.spec.pointer_input && !widget.spec.context_input &&
                  widget.state.options.empty() && widget.state.actions.empty() && widget.state.text_frame == (widget.state.text == "Assistant"),
                  "Rich passive text lost copy semantics or title-only framing");
            gui::Event edit = gui::WidgetEvent{widget.spec.key, gui::EditText{"changed", widget.state.text}};
            check(!gui::normalize_event(snapshot, edit), "Rich passive text accepted editing");
        }
    }
    const auto revision = view.revision(), measurements = measured;
    const auto repeated = view.render(source, {0,0,640,900}, "richer", "", measure);
    check(view.revision() == revision && measured == measurements && named_text(repeated, table).spec.key == table_widget.spec.key,
          "Unchanged nested/strong/rule blocks lost native identity or measurement caching");
    check(source == original, "Richer passive rendering rewrote source Markdown");
    tinyenv::PassiveMarkdownView style_view;
    const auto plain_widgets = style_view.render("bold", {0,0,640,900}, "style-cache", "", measure);
    const auto plain_measurements = measured;
    const auto strong_widgets = style_view.render("**bold**", {0,0,640,900}, "style-cache", "", measure);
    check(measured == plain_measurements + 1 && named_text(strong_widgets, "bold").state.font.bold &&
          named_text(strong_widgets, "bold").spec.key == named_text(plain_widgets, "bold").spec.key,
          "Plain-to-strong update retained stale font/measurements or replaced native identity");
    const auto quoted_widgets = style_view.render("> bold", {0,0,640,900}, "style-cache", "", measure);
    const auto quoted_measurements = measured;
    const auto deeper_widgets = style_view.render("> > bold", {0,0,640,900}, "style-cache", "", measure);
    check(measured == quoted_measurements + 1 && named_text(deeper_widgets, "bold").state.bounds.x == named_text(quoted_widgets, "bold").state.bounds.x + 12 &&
          named_text(deeper_widgets, "bold").spec.key == named_text(quoted_widgets, "bold").spec.key,
          "Quote-depth update retained stale geometry/measurements or replaced native identity");
    for (const auto text : {"**bold**", "__bold__"}) {
        const auto document = tinyenv::parse_passive_markdown(text); safe_document(document);
        check(document.blocks.size() == 1 && document.blocks.front().text == "bold" && document.blocks.front().strong,
              "Simple complete strong delimiter did not become bold text");
    }
    for (const auto text : {"*emphasis*", "`code`", "***both***", "**  x**", "** edge**", "**edge **", "**a** and **b**", "**a_b**", "**`code`**", "**a\\b**", "**a\nb**", "**open"}) {
        const auto document = tinyenv::parse_passive_markdown(text); safe_document(document);
        check(document.display_text == text && !document.blocks.front().strong, "Unsupported or malformed inline formatting lost its literal source");
    }
    for (const auto text : {"---", " * * * ", "** **", "   ___", "> > - - -"}) {
        const auto document = tinyenv::parse_passive_markdown(text); safe_document(document);
        check(document.blocks.size() == 1 && document.blocks.front().kind == Kind::rule && document.display_text == "--------------------------------",
              "Simple thematic break did not produce a bounded ASCII separator");
    }
    for (const auto text : {"--", "****text", "- _ -", "    ---", "\\***"}) {
        const auto document = tinyenv::parse_passive_markdown(text); safe_document(document);
        check(document.display_text == text && document.blocks.front().kind != Kind::rule, "Unsupported separator syntax was hidden or transformed");
    }
    const auto escaped = tinyenv::parse_passive_markdown("**\xE2\x80\xAE**\n\n> > ```text\n> > | \x01 | \xE2\x96\x88 |\n> > ```\n");
    safe_document(escaped);
    check(named_block(escaped, "[U+202E]").strong && named_block(escaped, "| [U+0001] | [U+2588] |\n").kind == Kind::code,
          "Rich formatting hid or recursively interpreted fixed escapes");
}
void nested_quotes_fences_and_tails() {
    using Kind = tinyenv::PassiveMarkdownKind;
    const auto depth = tinyenv::parse_passive_markdown("> > > > > > > > eight\n> > > > > > > > > ninth stays literal\n"); safe_document(depth);
    check(depth.blocks.size() == 1 && depth.blocks.front().quote_depth == 8 && depth.blocks.front().text == "eight\n> ninth stays literal",
          "Quote layer cap exceeded eight or discarded overdepth text");
    const auto mismatched = tinyenv::parse_passive_markdown("> > ```text\n> > exact\n> shallow\n> > > deeper\n> ```\n> > > ```\n> > ```\n## User\n"); safe_document(mismatched);
    check(mismatched.blocks.size() == 2 && mismatched.blocks.front().kind == Kind::code && mismatched.blocks.front().quote_depth == 2 &&
          mismatched.blocks.front().text == "exact\n> shallow\n> deeper\n> ```\n> ```\n" && mismatched.blocks.front().closed && mismatched.blocks.back().message_title,
          "A mismatched quote depth closed a code fence or changed literal body text");
    const tinyenv::PassiveMarkdownLimits limits{64,1024,128,8};
    std::string source = ">\t> ```text\n"; for (unsigned index = 0; index < 100; ++index) source += "> > padding\n";
    source += "> > ```\n## newest\n";
    const auto tail = tinyenv::parse_passive_markdown(source, limits); safe_document(tail, limits);
    check(tail.source_truncated && tail.blocks[1].kind == Kind::code && tail.blocks[1].quote_depth == 2 && tail.blocks[1].fence_language.empty() &&
          tail.blocks.back().kind == Kind::heading && tail.blocks.back().text == "newest",
          "Tab-projected nested fence context disagreed with the retained tail");
    tinyenv::PassiveMarkdownView view(limits); const gui::Rect area{0,0,400,300};
    view.render(source, area, "nested-tail", ""); const auto before = view.revision();
    source[0] = 'x'; view.render(source, area, "nested-tail", "");
    check(view.revision() == before + 1 && view.document().blocks.back().kind == Kind::code,
          "Same-length omitted-prefix edit retained stale nested-fence context");
    std::string contextual = "> > ~~~\n"; for (unsigned index = 0; index < 100; ++index) contextual += "> > padding\n";
    contextual += "> > ~~~\n## newest\n";
    view.render(contextual, area, "nested-tail", ""); const auto old_depth_revision = view.revision();
    contextual.replace(0, 7, ">   ~~~"); view.render(contextual, area, "nested-tail", "");
    check(view.revision() == old_depth_revision + 1 && view.document().blocks.back().kind == Kind::code && view.document().blocks.back().quote_depth == 1,
          "Omitted-prefix quote-depth edit was absent from cache invalidation");
    for (const auto suffix : {"**plain**", "---", ">> ## User"}) {
        const tinyenv::PassiveMarkdownLimits partial{std::string_view(suffix).size(),1024,128,8};
        const auto document = tinyenv::parse_passive_markdown(std::string(1000, 'x') + suffix, partial); safe_document(document, partial);
        const auto& block = document.blocks.back();
        check(block.kind == Kind::paragraph && block.text == suffix && !block.strong && !block.quote_depth && !block.message_title,
              "A retained partial line promoted new Markdown syntax");
    }
    const tinyenv::PassiveMarkdownLimits partial_code{11,1024,128,8};
    const auto code = tinyenv::parse_passive_markdown("> > ```text\npadding> > literal", partial_code); safe_document(code, partial_code);
    check(code.blocks.back().kind == Kind::code && code.blocks.back().text == "> > literal" && !code.blocks.back().closed,
          "A retained partial code line silently removed apparent quote prefixes");
    const auto spoof = tinyenv::parse_passive_markdown("## **User**\n\n> > ## Assistant\n\n> > **User**\n"); safe_document(spoof);
    check(std::none_of(spoof.blocks.begin(), spoof.blocks.end(), [](const auto& block) { return block.message_title || block.role != tinyenv::PassiveMarkdownRole::none; }),
          "Strong projection or nested quote heading acquired a message role");
    const tinyenv::PassiveMarkdownLimits chunks{4096,4096,128,4};
    const auto chunked = tinyenv::parse_passive_markdown("> > ```text\n> > " + std::string(500, 'x') + "\n> > ```\n", chunks); safe_document(chunked, chunks);
    check(chunked.blocks_truncated && std::all_of(chunked.blocks.begin() + 1, chunked.blocks.end(), [](const auto& block) {
        return block.kind == Kind::code && block.quote_depth == 2 && block.quoted && block.closed && !block.complete;
    }), "Block splitting/truncation lost nested fence metadata");
    gui::Snapshot narrow; narrow.client_size = {40,300};
    narrow.widgets = view.render("> > > > > > > > deep\n", {0,0,40,300}, "nested-narrow", ""); gui::validate_snapshot(narrow);
    for (const auto& widget : narrow.widgets) if (widget.spec.kind == gui::Kind::text)
        check(widget.state.bounds.width > 0 && widget.state.bounds.x >= 0 && widget.state.bounds.x + widget.state.bounds.width <= 40,
              "Deep quote indentation exceeded a narrow viewport");
}
std::string table_fence(std::string_view table, std::string_view language = "markdown", unsigned depth = 0, bool close = true) {
    const auto prefix = depth ? std::string(depth, '>') + ' ' : std::string{};
    std::string source = prefix + "```" + std::string(language) + '\n';
    for (std::size_t at = 0; at < table.size();) {
        const auto newline = table.find('\n', at), end = newline == std::string_view::npos ? table.size() : newline;
        source += prefix; source += table.substr(at, end - at); source += '\n';
        at = end + (newline != std::string_view::npos);
    }
    if (close) source += prefix + "```\n";
    return source;
}
void passive_pipe_tables() {
    using Kind = tinyenv::PassiveMarkdownKind;
    const std::string source = "Left | Middle | Right\n:--- | :---: | ---:\na | xy | 7\nlength | z | 12345\n";
    const std::string expected = "+--------+--------+-------+\n| Left   | Middle | Right |\n+--------+--------+-------+\n| a      |   xy   |     7 |\n| length |   z    | 12345 |\n+--------+--------+-------+";
    const auto document = tinyenv::parse_passive_markdown(source); safe_document(document);
    check(document.blocks.size() == 1 && document.blocks.front().kind == Kind::table && document.blocks.front().text == expected &&
          document.blocks.front().table_columns == 3 && document.blocks.front().table_rows == 2 && !document.blocks.front().strong && !document.blocks.front().message_title,
          "Pipe table did not become the independently expected aligned ASCII grid");
    check(document.display_text == expected, "Displayed/copied table projection differs from native grid text");
    const auto framed = table_fence(source, "markdown", 2);
    const auto quoted = tinyenv::parse_passive_markdown("## Assistant\n\n" + framed); safe_document(quoted);
    const auto& block = named_block(quoted, expected);
    check(block.kind == Kind::table && block.quote_depth == 2 && block.role == tinyenv::PassiveMarkdownRole::assistant && block.fence_language == "markdown" &&
          block.source_offset == std::string("## Assistant\n\n").size() && block.closed && block.complete && block.part == 0,
          "Nested table-only markdown fence lost depth, role, opener identity or complete metadata");
    const auto header_only = tinyenv::parse_passive_markdown("| H |\n|---|\n"); safe_document(header_only);
    check(header_only.blocks.size() == 1 && header_only.blocks.front().kind == Kind::table && header_only.blocks.front().table_rows == 0 &&
          header_only.display_text == "+-----+\n| H   |\n+-----+", "Empty-body table lost its header or duplicated a border");
    const auto empty_cells = tinyenv::parse_passive_markdown("| A | B |\n|---|---|\n||x|\n"); safe_document(empty_cells);
    check(empty_cells.blocks.front().kind == Kind::table && empty_cells.display_text.find("|     | x   |") != std::string::npos,
          "Empty table cell was discarded or moved into another column");
    const auto escaped_pipe = tinyenv::parse_passive_markdown("| A | B |\n|---|---|\n| a\\|b | c |\n| d\\\\ | e |\n"); safe_document(escaped_pipe);
    check(escaped_pipe.blocks.front().kind == Kind::table && escaped_pipe.display_text.find("a\\|b") != std::string::npos && escaped_pipe.display_text.find("d\\\\") != std::string::npos,
          "Pipe delimiter escaping decoded source bytes or changed column boundaries");
    const std::string inert_cells = "| Text | Other |\n|---|---|\n| **strong** `code` &lt; [U+200D] | [go](javascript:bad) ![img](https://example.invalid/x) <script>x</script> |\n";
    const auto inert = tinyenv::parse_passive_markdown(inert_cells); safe_document(inert);
    check(inert.blocks.front().kind == Kind::table && inert.display_text.find("**strong** `code` &lt; [U+200D]") != std::string::npos &&
          inert.display_text.find("[go](javascript:bad) ![img](https://example.invalid/x) <script>x</script>") != std::string::npos,
          "Table cell markup was recursively interpreted, loaded or hidden");
    const auto unicode = tinyenv::parse_passive_markdown("| Day | Vibe |\n|---|---|\n| Monday | \xE2\x98\x95 |\n| Tuesday | \xF0\x9F\x90\xAA |\n| bad | \xFF\x01 |\n"); safe_document(unicode);
    check(unicode.blocks.front().kind == Kind::table && unicode.display_text.find("[U+2615]") != std::string::npos &&
          unicode.display_text.find("[U+1F42A]") != std::string::npos && unicode.display_text.find("[0xFF][U+0001]") != std::string::npos,
          "Table rendering lost visible Unicode/control/malformed-byte escapes");
    // A table may begin immediately after prose and end before following prose.
    const auto adjacent = tinyenv::parse_passive_markdown("intro\n" + source + "after\n"); safe_document(adjacent);
    check(adjacent.blocks.size() == 3 && adjacent.blocks[0].text == "intro" && adjacent.blocks[1].kind == Kind::table && adjacent.blocks[2].text == "after",
          "Ordinary table detection swallowed adjacent prose");
    for (const auto& raw : {std::string("| A | B |\n|--|---|\n|x|y|\n"), std::string("| A | B |\n|---|---|\n|x|y|\n|ragged|\n"),
                           std::string("| A | B |\n| - - - |---|\n|x|y|\n"), std::string("| A | B |\n|---|---|\n|x|y|z|\n")}) {
        const auto unsupported = tinyenv::parse_passive_markdown(raw); safe_document(unsupported);
        check(std::none_of(unsupported.blocks.begin(), unsupported.blocks.end(), [](const auto& item) { return item.kind == Kind::table; }) &&
              unsupported.display_text == raw.substr(0, raw.size() - 1), "Malformed ordinary table rendered a partial grid or lost raw rows");
    }
    for (const auto& body : {std::string("prose\n") + source, source + "after\n", source + '\n' + source,
                            std::string("| A | B |\n|---|---|\n|ragged|\n")}) {
        const auto unsupported = tinyenv::parse_passive_markdown(table_fence(body)); safe_document(unsupported);
        check(unsupported.blocks.size() == 1 && unsupported.blocks.front().kind == Kind::code && unsupported.blocks.front().text == body,
              "Markdown fence with unsupported content was partially or recursively rendered");
    }
    for (const auto language : {"text", "md", "Markdown", "markdown extra", "mermaid"}) {
        const auto unsupported = tinyenv::parse_passive_markdown(table_fence(source, language)); safe_document(unsupported);
        check(unsupported.blocks.front().kind == Kind::code && unsupported.blocks.front().text == source,
              "A nonexact markdown fence became a table");
    }
    const auto partial = tinyenv::parse_passive_markdown(table_fence(source, "markdown", 2, false)); safe_document(partial);
    check(partial.blocks.front().kind == Kind::code && !partial.blocks.front().closed && partial.blocks.front().text == source,
          "Partial markdown fence rendered an unsupported table");
    const auto blank_edges = tinyenv::parse_passive_markdown(table_fence('\n' + source + "\n\n")); safe_document(blank_edges);
    check(blank_edges.blocks.front().kind == Kind::table && blank_edges.display_text == expected,
          "Table-only markdown fence rejected harmless edge blank lines");
    const auto followed_fence = tinyenv::parse_passive_markdown("| A | B |\n|---|---|\n|x|y|\n```text|details\n|literal|row|\n```\n## User\nmessage\n"); safe_document(followed_fence);
    check(followed_fence.blocks.size() == 4 && followed_fence.blocks[0].kind == Kind::table && followed_fence.blocks[1].kind == Kind::code &&
          followed_fence.blocks[1].fence_language == "text|details" && followed_fence.blocks[1].text == "|literal|row|\n" && followed_fence.blocks[1].closed &&
          followed_fence.blocks[2].message_title && followed_fence.blocks[2].role == tinyenv::PassiveMarkdownRole::user && followed_fence.blocks[3].text == "message",
          "An ordinary table swallowed a pipe-bearing fence opener or following message role");
    const std::string inner_fence = "| A | B |\n|---|---|\n```text|details\n|x|y|\n```\n";
    const auto nested_fence = tinyenv::parse_passive_markdown("````markdown\n" + inner_fence + "````\n"); safe_document(nested_fence);
    check(nested_fence.blocks.size() == 1 && nested_fence.blocks[0].kind == Kind::code && nested_fence.blocks[0].text == inner_fence,
          "A table-only fence interpreted an embedded fence as a table row");
    const auto indented = tinyenv::parse_passive_markdown("    | A | B |\n    |---|---|\n    |x|y|\n"); safe_document(indented);
    check(indented.blocks.size() == 1 && indented.blocks.front().kind == Kind::paragraph && indented.display_text == "    | A | B |\n    |---|---|\n    |x|y|",
          "Indented code-like table text became an ordinary Markdown table");
    const auto heading_first = tinyenv::parse_passive_markdown("# Heading | Other\n|---|---|\n|x|y|\n"); safe_document(heading_first);
    check(heading_first.blocks.front().kind == Kind::heading && heading_first.blocks.front().text == "Heading | Other" &&
          std::none_of(heading_first.blocks.begin(), heading_first.blocks.end(), [](const auto& item) { return item.kind == Kind::table; }),
          "Table lookahead changed established heading precedence");
    const auto following_list = tinyenv::parse_passive_markdown("| A | B |\n|---|---|\n|x|y|\n- item | other\n"); safe_document(following_list);
    check(following_list.blocks.size() == 2 && following_list.blocks[0].kind == Kind::table && following_list.blocks[0].table_rows == 1 &&
          following_list.blocks[1].kind == Kind::list && following_list.blocks[1].text == "- item | other", "Table body swallowed an established list block");
    const auto inline_markers = tinyenv::parse_passive_markdown("| A | B |\n|---|---|\n| # literal | - literal |\n"); safe_document(inline_markers);
    check(inline_markers.blocks.front().kind == Kind::table && inline_markers.display_text.find("# literal") != std::string::npos && inline_markers.display_text.find("- literal") != std::string::npos,
          "Unambiguous outer-pipe cells were mistaken for structural blocks");
}
void pipe_table_bounds_and_native_cache() {
    using Kind = tinyenv::PassiveMarkdownKind;
    const auto make_table = [](unsigned columns, unsigned rows, std::size_t cell_bytes = 1) {
        std::string source;
        const auto row = [&](std::string_view cell) { source += '|'; for (unsigned index = 0; index < columns; ++index) { source += cell; source += '|'; } source += '\n'; };
        row("H"); row("---");
        for (unsigned index = 0; index < rows; ++index) row(std::string(cell_bytes, 'x'));
        return source;
    };
    for (const auto& [columns, rows, bytes] : {std::tuple{8u,32u,1u}, std::tuple{1u,1u,128u}}) {
        const auto parsed = tinyenv::parse_passive_markdown(make_table(columns, rows, bytes)); safe_document(parsed);
        check(parsed.blocks.size() == 1 && parsed.blocks.front().kind == Kind::table && parsed.blocks.front().table_columns == columns && parsed.blocks.front().table_rows == rows,
              "A supported table cap boundary fell back or was split");
    }
    for (const auto& [columns, rows, bytes] : {std::tuple{9u,1u,1u}, std::tuple{2u,33u,1u}, std::tuple{1u,1u,129u}, std::tuple{8u,32u,128u}}) {
        const auto raw = make_table(columns, rows, bytes);
        const auto parsed = tinyenv::parse_passive_markdown(table_fence(raw)); safe_document(parsed);
        check(std::none_of(parsed.blocks.begin(), parsed.blocks.end(), [](const auto& block) { return block.kind == Kind::table; }) && parsed.display_text == raw,
              "An oversized table rendered, dropped cells or changed its complete raw fallback");
    }
    // Output 5 * 25 + 4 = 129 bytes. With max block128 its short raw input
    // remains complete literal code; block129 admits the whole grid.
    const std::string expansion = "| A | B |\n|---|---|\n|123456789|abcdefghi|\n";
    for (const auto cap : {128u,129u}) {
        const tinyenv::PassiveMarkdownLimits limits{4096,1024,cap,8};
        const auto parsed = tinyenv::parse_passive_markdown(table_fence(expansion), limits); safe_document(parsed, limits);
        check(parsed.blocks.size() == 1 && (parsed.blocks.front().kind == Kind::table) == (cap == 129) && parsed.blocks.front().complete,
              "Table expansion was not preflighted against the exact block byte budget");
    }
    const tinyenv::PassiveMarkdownLimits truncated{64,1024,128,8};
    const auto tail = tinyenv::parse_passive_markdown("```markdown\n" + std::string(500, 'x') + "\n| A | B |\n|---|---|\n|x|y|\n```\n", truncated); safe_document(tail, truncated);
    check(tail.blocks.back().kind == Kind::code && tail.blocks.back().fence_language.empty(), "An omitted table opener became a rich table");
    const std::string partial_header = "| A | B |\n|---|---|\n|x|y|";
    const tinyenv::PassiveMarkdownLimits partial_limits{partial_header.size(),1024,128,8};
    const auto cut = tinyenv::parse_passive_markdown(std::string(500, 'x') + partial_header, partial_limits); safe_document(cut, partial_limits);
    check(std::none_of(cut.blocks.begin(), cut.blocks.end(), [](const auto& block) { return block.kind == Kind::table; }),
          "A partial retained table header was promoted to supported syntax");
    const std::string raw = "| A | B |\n|---|---|\n|x|y|\n";
    tinyenv::PassiveMarkdownView view; std::size_t measured = 0;
    const gui::TextMeasure measure = [&](const auto& request) { ++measured; return gui::Size{double(request.text.size()),90}; };
    const gui::Rect area{0,0,400,300};
    const auto widgets = view.render(raw, area, "tables", "", measure, 1, 1);
    const auto projected = view.document().blocks.front().text;
    gui::Snapshot snapshot; snapshot.client_size = {400,300}; snapshot.widgets = widgets; gui::validate_snapshot(snapshot);
    const auto& table = named_text(widgets, "x");
    const auto canvas = std::find_if(widgets.begin(), widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; });
    check(canvas != widgets.end() && canvas->state.accessible_name == "Markdown table, 2 columns, 1 data rows" &&
          std::none_of(widgets.begin(), widgets.end(), [&](const auto& widget) { return widget.state.text == projected; }) &&
          table.state.wrap == gui::TextWrap::word && !table.state.text_frame && table.spec.text_policy.read_only &&
          table.spec.text_policy.multiline && table.state.options.empty() && table.state.actions.empty() && !table.spec.pointer_input && !table.spec.context_input,
          "Native table did not replace ASCII borders with passive selectable cells and a drawn grid");
    gui::Event edit = gui::WidgetEvent{table.spec.key, gui::EditText{"bad", table.state.text}};
    check(!gui::normalize_event(snapshot, edit), "Native table accepted edit input");
    const auto measurements = measured, revision = view.revision(), raster_revision = canvas->state.bitmap.revision;
    const auto repeated = view.render(raw, area, "tables", "", measure, 1, 1);
    check(measured == measurements && view.revision() == revision && named_text(repeated, "x").spec.key == table.spec.key &&
          repeated[1].state.bitmap.revision == raster_revision,
          "Idle authoritative table rendering reparsed, remeasured, repainted or replaced identity");
    const auto appended = view.render(raw + "\nstream body", area, "tables", "", measure, 1, 2);
    check(measured == measurements + 1 && named_text(appended, "x").spec.key == table.spec.key && appended[1].state.bitmap.revision == raster_revision,
          "A streamed paragraph append remeasured or repainted an unchanged table");
    const auto invalid = view.render(raw + "|ragged|\n", area, "tables", "", measure, 1, 3);
    check(view.document().blocks.front().kind != Kind::table && invalid[1].spec.key.id == "tables.block.0.0" &&
          std::none_of(invalid.begin(), invalid.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; }),
          "A streamed ragged row retained a partial grid or changed source block identity");
    const auto invalid_measurements = measured;
    const auto valid_again = view.render(raw + "|ragged|fixed|\n", area, "tables", "", measure, 1, 4);
    check(view.document().blocks.front().kind == Kind::table && measured > invalid_measurements && named_text(valid_again, "x").spec.key == table.spec.key,
          "Completed streamed row failed to replace raw fallback with native cells");
    const auto restored_measures = measured;
    const auto grown = view.render(raw + "|ragged|fixed|\n|new|row|\n", area, "tables", "", measure, 1, 5);
    check(measured == restored_measures + 2 && named_text(grown, "x").spec.key == table.spec.key,
          "A streamed table row remeasured unchanged cells or replaced their identity");
    view.render(raw, area, "tables", "", measure);
    check(view.document().blocks.front().table_rows == 1, "Switching to zero-revision fallback retained stale authoritative content");
    view.render(raw + "|new|row|\n", area, "tables", "", measure);
    check(view.document().blocks.front().table_rows == 2, "Zero-revision table cache missed a new row");
    for (const auto role : {"User", "Assistant"}) {
        const auto source = std::string("## ") + role + "\n\n" + table_fence(raw, "markdown", 8);
        snapshot.client_size = {40,300}; snapshot.widgets = view.render(source, {0,0,40,300}, "tables", "", measure); gui::validate_snapshot(snapshot);
        for (const auto& widget : snapshot.widgets) if (widget.spec.kind == gui::Kind::text)
            check(widget.state.bounds.width > 0 && widget.state.bounds.x >= 0 && widget.state.bounds.x + widget.state.bounds.width <= snapshot.widgets.front().state.content_size.width &&
                  widget.state.bounds.y + widget.state.bounds.height <= snapshot.widgets.front().state.content_size.height,
                  "Nested user/assistant table cells escaped the outer scrollable extent");
    }
}
void drawn_table_geometry_and_limits() {
    const std::string source = "| Left | Center | Right |\n|:---|:---:|---:|\n| longleft | c | 1 |\n| x | longercenter | 999999 |\n";
    tinyenv::PassiveMarkdownView view;
    std::size_t measures = 0;
    const gui::TextMeasure measure = [&](const auto& request) {
        ++measures;
        const auto natural = request.text.size() * 7.0;
        const auto lines = request.wrap == gui::TextWrap::word ? std::max(1.0, std::ceil(natural / request.available_width)) : 1.0;
        return gui::Size{request.wrap == gui::TextWrap::word ? std::min(natural, request.available_width) : natural, lines * 18};
    };
    gui::Snapshot snapshot; snapshot.client_size = {400,400}; snapshot.display_scale = 1.25;
    snapshot.widgets = view.render(source, {.25,.75,320,300}, "drawn", "", measure, 1.25, 1); gui::validate_snapshot(snapshot);
    check(snapshot.widgets.size() == 11 && snapshot.widgets[1].spec.kind == gui::Kind::bitmap,
          "Drawn table did not have one rule surface followed by nine independent cells");
    const auto& canvas = snapshot.widgets[1];
    const auto& left1 = named_text(snapshot.widgets, "longleft"), &left2 = named_text(snapshot.widgets, "x");
    const auto& center1 = named_text(snapshot.widgets, "c"), &center2 = named_text(snapshot.widgets, "longercenter");
    const auto& right1 = named_text(snapshot.widgets, "1"), &right2 = named_text(snapshot.widgets, "999999");
    check(left1.state.bounds.x == left2.state.bounds.x &&
          center1.state.bounds.x + center1.state.bounds.width / 2 == center2.state.bounds.x + center2.state.bounds.width / 2 &&
          right1.state.bounds.x + right1.state.bounds.width == right2.state.bounds.x + right2.state.bounds.width,
          "Native table alignment relied on character padding rather than positioned cells");
    for (std::size_t index = 2; index < snapshot.widgets.size(); ++index) {
        const auto& cell = snapshot.widgets[index]; const auto& b = cell.state.bounds; const auto& grid = canvas.state.bounds;
        check(cell.spec.kind == gui::Kind::text && cell.spec.parent == "drawn" && cell.state.font.bold == (index < 5) &&
              cell.spec.text_policy.read_only && !cell.state.text_frame && cell.state.options.empty() && cell.state.actions.empty() &&
              !cell.spec.pointer_input && !cell.spec.context_input && cell.spec.text_policy.submit == gui::SubmitKey::none &&
              b.x > grid.x && b.y > grid.y && b.x + b.width < grid.x + grid.width && b.y + b.height < grid.y + grid.height,
              "A table cell lost bold-header, passive or inside-rule geometry semantics");
    }
    const auto device = gui::device_rect(canvas.state.bounds, snapshot.display_scale);
    check(std::size_t(device.width) * device.height <= 2 * 1024 * 1024,
          "Published table device pixels bypassed aggregate reservation");
    const auto sample = [&](const gui::BitmapSource& painter, gui::PixelFormat format, bool partial) {
        gui::BitmapImage image(unsigned(device.width), unsigned(device.height), format);
        auto request = gui::full_bitmap_request(unsigned(device.width), unsigned(device.height), format);
        const auto paint = [&](const gui::BitmapRequest& part) {
            painter.paint(part, [&](unsigned x, unsigned y, gui::PixelBlock block) { image.blit(x,y,block); });
        };
        if (!partial) paint(request);
        else {
            const auto first = unsigned(device.height) / 2;
            request.damage.height = first; paint(request);
            request.damage = {0,first,unsigned(device.width),unsigned(device.height) - first}; paint(request);
        }
        return std::vector<std::uint8_t>(image.block().bytes.begin(), image.block().bytes.end());
    };
    const auto old_painter = canvas.state.bitmap.source;
    const auto old_pixels = sample(old_painter, gui::PixelFormat::rgb24, false);
    for (const auto format : {gui::PixelFormat::rgb24, gui::PixelFormat::gray8, gui::PixelFormat::mono1})
        check(sample(old_painter, format, false) == sample(old_painter, format, true),
              "Table partial-damage paint differs from full-grid paint");
    const auto monochrome = sample(old_painter, gui::PixelFormat::mono1, false);
    const auto body_y = unsigned((left2.state.bounds.y - canvas.state.bounds.y + left2.state.bounds.height / 2) * device.height / canvas.state.bounds.height);
    const auto mono_stride = gui::pixel_row_bytes(unsigned(device.width), gui::PixelFormat::mono1);
    check((monochrome[body_y * mono_stride] & 0x80) && !(monochrome[body_y * mono_stride] & 0x08),
          "Monochrome table lost its body rule against the dark surface");
    check(std::any_of(old_pixels.begin(), old_pixels.end(), [&](auto value) { return value != old_pixels.front(); }),
          "Drawn table rule bitmap is spatially uniform");
    const auto before = measures, old_revision = canvas.state.bitmap.revision;
    const auto idle = view.render(source, {.25,.75,320,300}, "drawn", "", measure, 1.25, 1);
    check(measures == before && idle[1].state.bitmap.revision == old_revision, "Idle drawn table rebuilt its cached geometry");
    const auto changed = view.render(source + "| last | final | 123456 |\n", {.25,.75,320,300}, "drawn", "", measure, 1.25, 2);
    check(changed[1].state.bitmap.revision != old_revision && sample(old_painter, gui::PixelFormat::rgb24, false) == old_pixels,
          "A streaming table changed a frozen bitmap or reused its raster revision");
    view.render("| A | B |\n|---|---|\n|ragged|\n", {0,0,320,300}, "drawn", "", measure, 1, 3);
    const auto restored = view.render(source, {0,0,320,300}, "drawn", "", measure, 1, 4);
    check(restored[1].state.bitmap.revision != old_revision,
          "Restored table reused a revision for different immutable pixels");
    const std::string literal = "| Value | Other |\n|---|---|\n| **strong** `code` <br /> [go](javascript:bad) | \\| [U+200D] |\n";
    const auto passive = view.render(literal, {0,0,160,300}, "drawn", "", measure, 1, 5);
    check(named_text(passive, "**strong** `code` <br /> [go](javascript:bad)").spec.text_policy.read_only &&
          named_text(passive, "\\| [U+200D]").state.text == "\\| [U+200D]",
          "Native cells interpreted inline HTML, links or escape text");
    check(passive.front().state.content_size.height > passive[1].state.bounds.height &&
          passive.back().state.bounds.y + passive.back().state.bounds.height <= passive.front().state.content_size.height,
          "Wrapped final cell was hidden behind an internally clipped table");
    // Every header and empty cell counts. Small eight-column tables each use
    // sixteen controls; at24tables the384-cell cap is exactly full.
    std::string table = "|A|B|C|D|E|F|G|H|\n|---|---|---|---|---|---|---|---|\n|||||||||\n\n";
    for (const auto count : {23u,24u,25u}) {
        std::string many; for (unsigned index = 0; index < count; ++index) many += table;
        const auto widgets = view.render(many, {0,0,200,300}, "budget", "");
        const auto cells = std::count_if(widgets.begin(), widgets.end(), [](const auto& w) { return w.spec.key.id.find(".table.cell.") != std::string::npos; });
        check(cells == std::min(count,24u) * 16 && cells <= 384, "Aggregate native table cell budget omitted empty/header cells");
        if (count == 25) check(widgets[1].spec.kind == gui::Kind::text && widgets[2].spec.kind == gui::Kind::bitmap,
                              "Aggregate cell cap did not preserve newest complete tables with literal oldest fallback");
        check(widgets.front().state.content_size.width > 200, "Narrow table did not expose horizontal outer scroll extent");
    }
    const gui::TextMeasure long_word_metrics = [](const auto& request) { return gui::Size{request.text.size() * 8.0,16}; };
    const auto token = std::string(128,'x');
    const auto long_word = view.render("| Header |\n|---|\n|" + token + "|\n", {0,0,80,300}, "long-word", "", long_word_metrics);
    check(named_text(long_word, token).state.bounds.height >= std::ceil(128 * 8.0 / 52) * 16 &&
          long_word.front().state.content_size.height > 300,
          "Label-style long-token measurement left the native cell internally clipped");
    const auto scaled = view.render(source, {0,0,320,300}, "high-scale", "", {}, 16);
    check(scaled[1].spec.kind == gui::Kind::text && std::none_of(scaled.begin(), scaled.end(), [](const auto& w) { return w.spec.kind == gui::Kind::bitmap; }),
          "High-density table allocated/published a bitmap before device-pixel preflight");
    const auto tiny_scale = view.render(source, {0,0,320,300}, "tiny-scale", "", {}, .000001);
    check(tiny_scale[1].spec.kind == gui::Kind::bitmap, "Valid tiny display scale overflowed logical raster reservation");
    bool rejected = false;
    try { old_painter.paint(gui::full_bitmap_request(4096,1024), [](unsigned,unsigned,gui::PixelBlock) {}); }
    catch (const std::length_error&) { rejected = true; }
    check(rejected, "Table bitmap painter accepted an oversized sample request");
}
gui::Rect node_bounds(const gui::Widget& label, tinyenv::PassiveDiagramShape shape) {
    const auto& text = label.state.bounds;
    const bool decision = shape == tinyenv::PassiveDiagramShape::decision;
    const double scale = text.width / (decision ? 98 : 176);
    return {text.x - (decision ? 49 : 10) * scale, text.y - (decision ? 18 : 8) * scale, 196 * scale, 72 * scale};
}
bool visible_forward_rail(const gui::Widget& canvas, gui::Rect from, gui::Rect to) {
    const auto width = unsigned(std::ceil(canvas.state.bounds.width)), height = unsigned(std::ceil(canvas.state.bounds.height));
    gui::BitmapImage sampled(width, height);
    canvas.state.bitmap.source.paint(gui::full_bitmap_request(width, height), [&](unsigned x, unsigned y, gui::PixelBlock block) { sampled.blit(x,y,block); });
    const auto& pixels = sampled.pixels();
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
void message_roles_and_layout() {
    using Role = tinyenv::PassiveMarkdownRole;
    const std::string source = "> ordinary outside quote\n\n## User\n\nuser paragraph\n\n- user item\n\n```text\nuser code\n```\n\n## Assistant\n\n> assistant paragraph\n>\n> ### assistant detail\n>\n> - assistant item\n>\n> ```text\n> assistant code\n> ```\n\n## Retry\n\nretry paragraph\n\n## Streaming\n\n> stream preview\n";
    const auto original = source;
    const auto parsed = tinyenv::parse_passive_markdown(source); safe_document(parsed);
    check(named_block(parsed, "ordinary outside quote").role == Role::none && !named_block(parsed, "ordinary outside quote").message_title,
          "A standalone quote became a message");
    for (const auto title : {"User", "Retry"}) {
        const auto& block = named_block(parsed, title);
        check(block.role == Role::user && block.message_title, "Canonical user title lost its message role");
    }
    for (const auto title : {"Assistant", "Streaming"}) {
        const auto& block = named_block(parsed, title);
        check(block.role == Role::assistant && block.message_title, "Canonical assistant title lost its message role");
    }
    for (const auto text : {"user paragraph", "- user item", "user code\n", "retry paragraph"}) {
        const auto& block = named_block(parsed, text);
        check(block.role == Role::user && !block.message_title, "User body lost its role or became a title");
    }
    for (const auto text : {"assistant paragraph", "assistant detail", "- assistant item", "assistant code\n", "stream preview"}) {
        const auto& block = named_block(parsed, text);
        check(block.role == Role::assistant && !block.message_title, "Assistant body lost its role or became a title");
    }
    for (const auto title : {"Incomplete result", "Transcription", "Builder"}) {
        const auto document = tinyenv::parse_passive_markdown("## " + std::string(title) + "\n\n> body\n"); safe_document(document);
        check(document.blocks.front().role == Role::assistant && document.blocks.front().message_title && document.blocks.back().role == Role::assistant && !document.blocks.back().message_title,
              "Canonical result title or body did not retain assistant presentation");
    }
    tinyenv::PassiveMarkdownView view;
    const gui::Rect area{17,23,500,900};
    const auto widgets = view.render(source, area, "messages", "");
    gui::Snapshot snapshot; snapshot.client_size = {700,1200}; snapshot.widgets = widgets; gui::validate_snapshot(snapshot);
    const auto& user = named_text(widgets, "User"); const auto& assistant = named_text(widgets, "Assistant");
    check(user.state.bounds.x > assistant.state.bounds.x && user.state.bounds.width == assistant.state.bounds.width,
          "Message lanes did not align user right and assistant left with equal widths");
    for (const auto text : {"User", "user paragraph", "- user item", "user code\n", "Retry", "retry paragraph"}) {
        const auto& widget = named_text(widgets, text);
        check(widget.state.bounds.x == user.state.bounds.x && widget.state.bounds.width == user.state.bounds.width,
              "A user title or body escaped its shared message lane");
    }
    for (const auto text : {"Assistant", "assistant paragraph", "assistant detail", "- assistant item", "assistant code\n", "Streaming", "stream preview"}) {
        const auto& widget = named_text(widgets, text);
        check(widget.state.bounds.x == assistant.state.bounds.x && widget.state.bounds.width == assistant.state.bounds.width,
              "Assistant storage quoting or list syntax added an extra body margin");
    }
    for (const auto& widget : widgets) if (widget.spec.kind == gui::Kind::text) {
        const auto& block = named_block(parsed, widget.state.text);
        check(widget.state.text_frame == block.message_title, "Native framing did not match title-only presentation");
        check(widget.state.bounds.x >= area.x && widget.state.bounds.x + widget.state.bounds.width <= area.x + area.width,
              "A message lane exceeded its viewport horizontally");
        check(widget.state.enabled && widget.spec.text_policy.read_only && widget.spec.text_policy.multiline,
              "Frameless message text lost selectable readonly semantics");
    }
    check(!named_text(widgets, "ordinary outside quote").state.text_frame,
          "Ordinary quoted body retained an individual paragraph box");
    check(source == original, "Message presentation rewrote saved source");
    const auto before = view.revision(); const auto repeated = view.render(source, area, "messages", "");
    check(view.revision() == before && named_text(repeated, "User").spec.key == user.spec.key && named_text(repeated, "user paragraph").state.bounds == named_text(widgets, "user paragraph").state.bounds,
          "Unchanged message layout lost cached identities or geometry");
    snapshot.client_size = {80,300}; snapshot.widgets = view.render(source, {0,0,40,300}, "messages", ""); gui::validate_snapshot(snapshot);
    for (const auto& widget : snapshot.widgets) if (widget.spec.kind == gui::Kind::text)
        check(widget.state.bounds.width > 0 && widget.state.bounds.x >= 0 && widget.state.bounds.x + widget.state.bounds.width <= 40,
              "A narrow message viewport produced an invalid lane");
}
void message_role_spoofing_and_tail() {
    using Role = tinyenv::PassiveMarkdownRole;
    const std::string spoof = "# User\n\nunknown body\n\n> ## User\n\n> quoted pseudo body\n\n```text\n## User\n## Assistant\n```\n\n## Assistant\n\n> ## User\n>\n> quoted user text\n>\n> ```text\n> ## User\n> ```\n\n## user\n\ncase lookalike\n\n## User!\n\npunctuation lookalike\n\n### Retry\n\nwrong level\n\n## Assistant[U+200D]\n\nescaped lookalike\n\n## User\xE2\x80\x8D\n\nhidden lookalike\n\n ## User\n\nindented lookalike\n\n##User\n\nmissing separator\n\n## User ##\n\nclosing hashes\n\n## \\u0055ser\n\nliteral escape\n";
    const auto document = tinyenv::parse_passive_markdown(spoof); safe_document(document);
    const auto title_offset = spoof.find("\n## Assistant\n\n") + 1;
    check(std::count_if(document.blocks.begin(), document.blocks.end(), [](const auto& block) { return block.message_title; }) == 1,
          "Quoted, fenced or lookalike headings spoofed a message title");
    for (const auto& block : document.blocks)
        check(block.role == (block.source_offset < title_offset ? Role::none : Role::assistant),
              "Quoted, fenced or lookalike headings changed the inherited message role");
    tinyenv::PassiveMarkdownView spoof_view;
    const auto widgets = spoof_view.render(spoof, {0,0,400,600}, "spoof", "");
    for (const auto& widget : widgets) if (widget.spec.kind == gui::Kind::text)
        check(widget.state.text_frame == (widget.state.text == "Assistant"), "A spoofed title or body was framed");
    const tinyenv::PassiveMarkdownLimits source_limits{128,1024,128,8};
    for (const auto title : {"## User\n", "##\tUser\r\n", "## Assistant\n", "##\tAssistant\r\n"}) {
        const auto expected = std::string_view(title).find("User") != std::string_view::npos ? Role::user : Role::assistant;
        const std::string source = std::string(title) + "\n" + std::string(3000, 'a') + "\n\nlatest body\n";
        const auto tail = tinyenv::parse_passive_markdown(source, source_limits); safe_document(tail, source_limits);
        check(tail.source_truncated && tail.blocks.back().role == expected && !tail.blocks.back().message_title && tail.blocks.back().text == "latest body",
              "A source-tail cut lost the role established by a normalized message title");
    }
    for (const auto title : {"## User\rsuffix\n", "## User\r\r\n", " ## User\n", "##User\n", "## User ##\n", "> ## User\n"}) {
        const auto tail = tinyenv::parse_passive_markdown(std::string(title) + "\n" + std::string(3000, 'a') + "\n\nlatest body\n", source_limits); safe_document(tail, source_limits);
        check(tail.blocks.back().role == Role::none && !tail.blocks.back().message_title,
              "Prefix normalization promoted a noncanonical or quoted role title");
    }
    const auto fenced = tinyenv::parse_passive_markdown("## User\n\n```text\n## Assistant\n" + std::string(3000, 'a') + "\n```\nlatest body\n", source_limits); safe_document(fenced, source_limits);
    check(fenced.blocks.back().role == Role::user && !fenced.blocks.back().message_title,
          "A fenced heading outside the retained tail switched message role");
    const auto partial = tinyenv::parse_passive_markdown("## Assistant\n\nbody\n\n## User" + std::string(3000, ' ') + "suffix", source_limits); safe_document(partial, source_limits);
    check(partial.blocks.back().role == Role::assistant && !partial.blocks.back().message_title,
          "A partial long heading at the tail boundary became a message title");
    const tinyenv::PassiveMarkdownLimits block_limits{4096,4096,128,4};
    std::string sections = "## User\n\n"; for (unsigned index = 0; index < 20; ++index) sections += "# section " + std::to_string(index) + '\n';
    const auto bounded = tinyenv::parse_passive_markdown(sections, block_limits); safe_document(bounded, block_limits);
    check(bounded.blocks_truncated && std::all_of(bounded.blocks.begin() + 1, bounded.blocks.end(), [](const auto& block) { return block.role == Role::user && !block.message_title; }),
          "Block truncation lost body role after omitting the message title");
    const tinyenv::PassiveMarkdownLimits display_limits{4096,512,128,8};
    const auto expanded = tinyenv::parse_passive_markdown("## User\n\n" + std::string(3000, '\x01') + "\n\nlatest body\n", display_limits); safe_document(expanded, display_limits);
    check(expanded.display_truncated && expanded.blocks.back().role == Role::user && !expanded.blocks.back().message_title,
          "Display expansion truncation lost message-role context");
    tinyenv::PassiveMarkdownView tail_view(source_limits);
    std::string contextual = "## User\n\n" + std::string(3000, 'a') + "\n\nlatest body\n";
    const auto first = tail_view.render(contextual, {0,0,400,300}, "tail-role", "");
    check(tail_view.document().blocks.back().role == Role::user && !named_text(first, "latest body").state.text_frame, "Retained user body did not remain frameless");
    const auto revision = tail_view.revision(); contextual.replace(3, 4, "Nope");
    tail_view.render(contextual, {0,0,400,300}, "tail-role", "");
    check(tail_view.revision() == revision + 1 && tail_view.document().blocks.back().role == Role::none,
          "Same-length omitted-prefix edit retained a stale user lane");
}
void diagrams() {
    tinyenv::PassiveMarkdownView view; gui::Snapshot snapshot; snapshot.client_size = {400,600};
    const std::string diagram = "> ```mermaid\n> flowchart TD\n> A[Hello] --> B[Done]\n> ```\n";
    snapshot.widgets = view.render(diagram, {0,0,400,600}, "preview", ""); gui::validate_snapshot(snapshot);
    const auto bitmap = std::find_if(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; });
    check(bitmap != snapshot.widgets.end() && bitmap->state.actions.empty() && !bitmap->spec.pointer_input, "Quoted Mermaid did not produce a passive local diagram");
    const auto bitmap_revision = bitmap->state.bitmap.revision;
    auto repeated = view.render(diagram, {0,0,400,600}, "preview", "");
    const auto repeated_bitmap = std::find_if(repeated.begin(), repeated.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; });
    check(repeated_bitmap != repeated.end() && repeated_bitmap->state.bitmap.revision == bitmap_revision, "Unchanged Mermaid rebuilt its raster");
    for (const auto depth : {2u,8u,9u}) {
        const auto prefix = std::string(depth, '>') + ' ';
        const auto nested = prefix + "```mermaid\n" + prefix + "flowchart TD\n" + prefix + "A[Hello] --> B[Done]\n" + prefix + "```\n";
        snapshot.widgets = view.render(nested, {0,0,400,600}, "preview", ""); gui::validate_snapshot(snapshot);
        check(std::count_if(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; }) == (depth <= 8 ? 1 : 0),
              "Nested Mermaid exceeded the quote cap or lost an eligible bounded fence");
    }
    // Exercise the exact one-layer storage form used by completed and streaming
    // replies, with the benign Mermaid syntax that previously fell back.
    for (const auto heading : {"Assistant", "Streaming"}) {
        const auto source = std::string("## ") + heading + "\n\n> ```mermaid\n> flowchart TD\n> %% A local build decision\n"
            "> A([Start]) --> B{Ready?}\n> B -->|Yes| C((Done))\n> B -- No --> A\n> ```\n";
        snapshot.widgets = view.render(source, {0,0,400,600}, "preview", ""); gui::validate_snapshot(snapshot);
        check(std::any_of(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; }),
              "Stored Assistant/Streaming common Mermaid remained literal code");
        for (const auto label : {"Yes", "No"})
            check(std::any_of(snapshot.widgets.begin(), snapshot.widgets.end(), [&](const auto& widget) { return widget.spec.kind == gui::Kind::label && widget.state.text == label; }),
                  "Stored reply lost its visible branch label");
    }
    snapshot.widgets = view.render("> ```mermaid\n> flowchart LR\n> A[\"Step 1: Build (local); test\"] -->|Ready / repeat| B[Done]\n> ```\n", {0,0,400,600}, "preview", "");
    gui::validate_snapshot(snapshot);
    check(std::any_of(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.state.text == "Step 1: Build (local); test"; }),
          "Quoted reply punctuation did not reach its native diagram label");
    for (const auto source : {"```mermaid\nflowchart TD\nA --> B", "```mermaid\nflowchart TD\nA --> B\nclick A \"javascript:alert(1)\"\n```\n", "```mermaid\n%%{init: {}}%%\nflowchart TD\nA --> B\n```\n"}) {
        snapshot.widgets = view.render(source, {0,0,400,600}, "preview", ""); gui::validate_snapshot(snapshot);
        check(std::none_of(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; }), "Partial or unsupported Mermaid became a diagram");
        check(std::any_of(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::text; }), "Unsupported diagram did not retain literal source");
    }
    std::string several; for (unsigned count = 0; count < 8; ++count) several += "```mermaid\nflowchart TD\nA --> B\n```\n";
    snapshot.widgets = view.render(several, {0,0,400,600}, "preview", ""); gui::validate_snapshot(snapshot);
    check(std::count_if(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; }) == 4,
          "Aggregate diagram budget exceeded four rasters");
}
std::string quoted_diagram(std::string_view graph, std::string_view heading) {
    std::string source = "## " + std::string(heading) + "\n\n> ```mermaid\n";
    for (std::size_t at = 0; at < graph.size();) {
        const auto newline = graph.find('\n', at);
        const auto end = newline == std::string_view::npos ? graph.size() : newline;
        source += "> "; source += graph.substr(at, end - at); source += '\n';
        if (newline == std::string_view::npos) break;
        at = newline + 1;
    }
    source += "> ```\n";
    return source;
}
void reported_chat_diagrams() {
    for (std::size_t index = 0; index < std::size(reported_flowcharts); ++index) {
        const auto graph = reported_flowcharts[index];
        const auto model = tinyenv::parse_passive_diagram(graph);
        check(model.supported && model.nodes.size() == (index == 0 ? 6 : 8) && model.edges.size() == (index == 0 ? 5 : 7),
              "Reported chat graph was not completely parsed");
        for (const auto heading : {"Assistant", "Streaming"}) {
            const auto source = quoted_diagram(graph, heading), original = source;
            const auto parsed = tinyenv::parse_passive_markdown(source); safe_document(parsed);
            check(parsed.blocks.size() == 2 && parsed.blocks.front().message_title && parsed.blocks.front().text == heading,
                  "Reported reply lost its canonical title or gained extra body blocks");
            const auto& body = parsed.blocks.back();
            check(body.kind == tinyenv::PassiveMarkdownKind::code && body.quoted && body.closed && body.complete && body.fence_language == "mermaid" &&
                  body.text == graph && body.role == tinyenv::PassiveMarkdownRole::assistant && !body.message_title,
                  "One-layer reply storage changed the exact closed Mermaid body or its role");
            tinyenv::PassiveMarkdownView view;
            gui::Snapshot snapshot; snapshot.client_size = {640,900};
            snapshot.widgets = view.render(source, {0,0,640,900}, "reported-chat", ""); gui::validate_snapshot(snapshot);
            check(std::count_if(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; }) == 1,
                  "Reported stored Assistant/Streaming graph still falls back to literal code");
            check(std::count_if(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::text; }) == 1,
                  "Valid styled graph leaked a literal fallback body beside its diagram");
            const auto bitmap = std::find_if(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; });
            check(bitmap->state.bounds.height >= 96 && bitmap->state.bounds.height <= 1536 && gui::has_area(bitmap->state.bounds) &&
                  bitmap->state.bounds.height == tinyenv::passive_diagram_height(model, bitmap->state.bounds.width),
                  "Reported graph lost its bounded local bitmap layout");
            gui::BitmapImage pixels(640, 240);
            bitmap->state.bitmap.source.paint(gui::full_bitmap_request(640, 240), [&](unsigned x, unsigned y, gui::PixelBlock block) { pixels.blit(x,y,block); });
            const auto& sampled = pixels.pixels();
            bool nonuniform = false;
            for (std::size_t pixel = 3; pixel + 2 < sampled.size(); pixel += 3)
                if (sampled[pixel] != sampled[0] || sampled[pixel + 1] != sampled[1] || sampled[pixel + 2] != sampled[2]) { nonuniform = true; break; }
            check(nonuniform, "Reported stored graph produced a spatially uniform bitmap");
            for (const auto& node : model.nodes)
                check(std::any_of(snapshot.widgets.begin(), snapshot.widgets.end(), [&](const auto& widget) { return widget.spec.kind == gui::Kind::label && widget.state.text == node.label && gui::has_area(widget.state.bounds); }),
                      "A reported node label did not reach the native diagram overlay");
            for (const auto& edge : model.edges) if (!edge.label.empty())
                check(std::any_of(snapshot.widgets.begin(), snapshot.widgets.end(), [&](const auto& widget) { return widget.spec.kind == gui::Kind::label && widget.state.text == edge.label && gui::has_area(widget.state.bounds); }),
                      "A reported branch label did not reach the native diagram overlay");
            const auto find_label = [&](std::string_view text) -> const gui::Widget& {
                const auto found = std::find_if(snapshot.widgets.begin(), snapshot.widgets.end(), [&](const auto& widget) { return widget.spec.kind == gui::Kind::label && widget.state.text == text; });
                if (found == snapshot.widgets.end()) throw std::runtime_error("Missing stored branch label: " + std::string(text));
                return *found;
            };
            const auto& first_caption = find_label(model.edges[1].label); const auto& second_caption = find_label(model.edges[2].label);
            check(!gui::has_area(gui::intersect(first_caption.state.bounds, second_caption.state.bounds)), "Stored reply forward branch captions overlap");
            for (const auto& node : model.nodes) {
                const auto area = node_bounds(find_label(node.label), node.shape);
                check(!gui::has_area(gui::intersect(first_caption.state.bounds, area)) && !gui::has_area(gui::intersect(second_caption.state.bounds, area)),
                      "Stored reply branch caption overlaps a node");
            }
            const auto decision = node_bounds(find_label(model.nodes[1].label), model.nodes[1].shape);
            for (const auto node : {2u,3u})
                check(visible_forward_rail(*bitmap, decision, node_bounds(find_label(model.nodes[node].label), model.nodes[node].shape)),
                      "Stored reply caption empty backing erased the forward junction or rail");
            for (const auto& widget : snapshot.widgets)
                check(widget.state.actions.empty() && widget.state.options.empty() && !widget.spec.pointer_input && !widget.spec.context_input,
                      "Reported styled reply acquired a link, resource or active input capability");
            const auto revision = bitmap->state.bitmap.revision;
            const auto repeated = view.render(source, {0,0,640,900}, "reported-chat", "");
            const auto retained = std::find_if(repeated.begin(), repeated.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; });
            check(retained != repeated.end() && retained->state.bitmap.revision == revision, "Unchanged reported reply rebuilt its diagram raster");
            check(source == original && view.document().blocks.back().text == graph, "Diagram presentation changed the raw stored reply");
        }
    }
    for (const auto invalid : {"style A fill:red", "style A fill:url(https://example.test/x)", "style Missing fill:#abc", "style A fill:#abc,fill:#def", "style A fill:#abc\nclick A href \"https://example.test/\""}) {
        const std::string graph = "flowchart TD\nA[Start: /local] --> B[Done]\n" + std::string(invalid) + '\n';
        const auto source = quoted_diagram(graph, "Assistant");
        tinyenv::PassiveMarkdownView view;
        gui::Snapshot snapshot; snapshot.client_size = {640,900};
        snapshot.widgets = view.render(source, {0,0,640,900}, "rejected-chat", ""); gui::validate_snapshot(snapshot);
        check(std::none_of(snapshot.widgets.begin(), snapshot.widgets.end(), [](const auto& widget) { return widget.spec.kind == gui::Kind::bitmap; }),
              "Unsafe or malformed style rendered a partial stored graph");
        const auto& literal = named_text(snapshot.widgets, graph);
        check(literal.spec.text_policy.read_only && !literal.spec.pointer_input && !literal.spec.context_input && literal.state.actions.empty() && literal.state.options.empty(),
              "Rejected graph did not retain inert selectable literal source");
    }
}
}
int main() {
    try { blocks(); characters_and_inert_syntax(); bounds_and_tail(); native_projection_and_cache(); richer_passive_blocks(); nested_quotes_fences_and_tails(); passive_pipe_tables(); pipe_table_bounds_and_native_cache(); drawn_table_geometry_and_limits(); message_roles_and_layout(); message_role_spoofing_and_tail(); diagrams(); reported_chat_diagrams(); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return 0;
}
