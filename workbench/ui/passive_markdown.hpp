#pragma once

#include <gui/contract.hpp>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace tinyenv {

enum class PassiveMarkdownKind { paragraph, heading, list, quote, code, notice, rule, table };
enum class PassiveMarkdownRole { none, user, assistant };
enum class PassiveMarkdownAlignment { left, center, right };

struct PassiveMarkdownBlock {
    PassiveMarkdownKind kind = PassiveMarkdownKind::paragraph;
    std::string text, fence_language;
    std::size_t source_offset = 0, part = 0;
    unsigned heading_level = 0;
    bool quoted = false, closed = true, complete = true;
    // Presentation of the existing transcript's exact, unquoted message headings.
    // This is never an authorization or execution boundary.
    PassiveMarkdownRole role = PassiveMarkdownRole::none;
    bool message_title = false;
    // Quoted transcript replies add one storage layer. Further layers retain
    // their own bounded indentation; they never establish a message role.
    unsigned quote_depth = 0;
    // The generic selectable control has one font, so only an entire block
    // with simple strong delimiters can use native bold presentation.
    bool strong = false;
    // A complete bounded table retains its literal cells and alignment for
    // native geometry. text remains the bounded ASCII fallback projection.
    // Unsupported/split blocks never carry partial table metadata.
    unsigned table_columns = 0, table_rows = 0;
    std::vector<std::vector<std::string>> table_cells{};
    std::vector<PassiveMarkdownAlignment> table_alignment{};
    bool operator==(const PassiveMarkdownBlock&) const = default;
};

// Hard upper bounds also apply when callers choose smaller fixture limits.
// Preview limits never change the original saved Markdown.
struct PassiveMarkdownLimits {
    std::size_t source_bytes = 256 * 1024;
    std::size_t display_bytes = 256 * 1024;
    std::size_t block_bytes = 8 * 1024;
    std::size_t blocks = 128;
};

struct PassiveMarkdownDocument {
    std::vector<PassiveMarkdownBlock> blocks;
    std::string display_text;
    std::size_t source_bytes = 0, source_begin = 0;
    bool source_truncated = false, display_truncated = false, blocks_truncated = false;
    bool truncated() const noexcept { return source_truncated || display_truncated || blocks_truncated; }
};

// This parser emits only printable ASCII and LF. Tabs become four spaces;
// other valid codepoints become fixed [U+XXXX] escapes and malformed bytes
// become [0xXX]. Escapes are never interpreted again. Only block syntax is
// recognized: headings, lists, up to eight quote layers, thematic breaks and
// literal fenced code. Bounded pipe tables retain cells and an ASCII fallback; an exact
// closed markdown fence may do so only when its entire body is a single table.
// Entire simple strong-delimited paragraphs can be bold;
// mixed inline emphasis/code retains its markers because the shared selectable
// control has no rich spans. HTML, links, images, entities and escapes are text.
PassiveMarkdownDocument parse_passive_markdown(
    std::string_view source, PassiveMarkdownLimits limits = {});

// Native selectable readonly text in a generic scrolling group. There is no
// browser document, URL/resource field, script engine or source evaluation.
// Exact closed mermaid fences may use the separately restricted diagram model;
// unsupported/partial diagrams remain literal text. Tables draw passive rules
// and selectable readonly cells, with bold headers and geometric alignment.
// At most 384 table cells and 2,097,152 table raster pixels are presented, newest
// fitting tables first; other tables keep the selectable ASCII fallback.
// Selection/copy is per text block or table cell.
class PassiveMarkdownView {
public:
    explicit PassiveMarkdownView(PassiveMarkdownLimits limits = {});
    ~PassiveMarkdownView();
    PassiveMarkdownView(PassiveMarkdownView&&) noexcept;
    PassiveMarkdownView& operator=(PassiveMarkdownView&&) noexcept;
    PassiveMarkdownView(const PassiveMarkdownView&) = delete;
    PassiveMarkdownView& operator=(const PassiveMarkdownView&) = delete;

    std::vector<gui::Widget> render(
        std::string_view source, gui::Rect viewport, std::string id,
        std::string parent, const gui::TextMeasure& measure = {}, double display_scale = 1,
        std::uint64_t source_revision = 0);
    // A nonzero source_revision is the caller's authoritative content version:
    // change it after every source mutation. Zero uses bounded content/context
    // comparison. Measurements cache by block, width and display scale; keep the
    // measuring adapter stable for this view's lifetime.
    const PassiveMarkdownDocument& document() const noexcept;
    std::uint64_t revision() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace tinyenv
