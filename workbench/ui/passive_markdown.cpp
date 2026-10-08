#include "passive_markdown.hpp"
#include "passive_diagram.hpp"
#include "theme.hpp"
#include <gui/bitmap.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <limits>
#include <map>
#include <optional>
#include <stdexcept>
#include <utility>

namespace tinyenv {
namespace {
constexpr std::string_view omission = "[Earlier content omitted from rendered preview. Saved chat is unchanged.]";
constexpr std::size_t scan_limit = 8 * 1024 * 1024;
void validate_limits(const PassiveMarkdownLimits& limits) {
    if (!limits.source_bytes || limits.source_bytes > 256 * 1024 ||
        limits.display_bytes < 512 || limits.display_bytes > 256 * 1024 ||
        limits.block_bytes < 128 || limits.block_bytes > 8 * 1024 ||
        limits.blocks < 2 || limits.blocks > 256)
        throw std::invalid_argument("Invalid passive Markdown limits");
}
struct Atom {
    std::array<char, 12> text{};
    std::size_t bytes = 1, length = 0;
};
Atom atom(std::string_view source, std::size_t at) {
    Atom result;
    const auto first = static_cast<unsigned char>(source[at]);
    if (first == '\n' || (first >= 32 && first <= 126)) {
        result.text[0] = static_cast<char>(first); result.length = 1; return result;
    }
    if (first == '\t') { std::fill_n(result.text.begin(), 4, ' '); result.length = 4; return result; }
    if (first == '\r' && at + 1 < source.size() && source[at + 1] == '\n') {
        result.text[0] = '\n'; result.length = 1; result.bytes = 2; return result;
    }
    unsigned value = first, following = 0, minimum = 0;
    bool valid = first < 128;
    if (first >= 0xc2 && first <= 0xdf) { value = first & 31; following = 1; minimum = 0x80; }
    else if (first >= 0xe0 && first <= 0xef) { value = first & 15; following = 2; minimum = 0x800; }
    else if (first >= 0xf0 && first <= 0xf4) { value = first & 7; following = 3; minimum = 0x10000; }
    if (following && following < source.size() - at) {
        valid = true;
        for (unsigned next = 1; next <= following; ++next) {
            const auto byte = static_cast<unsigned char>(source[at + next]);
            if ((byte & 0xc0) != 0x80) { valid = false; break; }
            value = (value << 6) | (byte & 63);
        }
        valid = valid && value >= minimum && value <= 0x10ffff && !(value >= 0xd800 && value <= 0xdfff);
        if (valid) result.bytes = following + 1;
    }
    constexpr char hex[] = "0123456789ABCDEF";
    if (!valid) {
        result.text = {'[','0','x',hex[first >> 4],hex[first & 15],']'};
        result.length = 6; return result;
    }
    result.text[0] = '['; result.text[1] = 'U'; result.text[2] = '+';
    unsigned digits = value > 0xffff ? (value > 0xfffff ? 6 : 5) : 4;
    for (unsigned digit = 0; digit < digits; ++digit)
        result.text[3 + digit] = hex[(value >> ((digits - digit - 1) * 4)) & 15];
    result.text[3 + digits] = ']'; result.length = 4 + digits; return result;
}
std::string_view trim(std::string_view value) {
    const auto begin = value.find_first_not_of(" \t");
    if (begin == std::string_view::npos) return {};
    return value.substr(begin, value.find_last_not_of(" \t") - begin + 1);
}
constexpr unsigned quote_limit = 8;
struct Line { std::string_view text; unsigned quote_depth = 0; };
Line line_body(std::string_view line) {
    unsigned depth = 0;
    while (depth < quote_limit) {
        std::size_t indent = 0;
        while (indent < line.size() && line[indent] == ' ' && indent < 4) ++indent;
        if (indent > 3 || indent == line.size() || line[indent] != '>') break;
        line.remove_prefix(indent + 1);
        if (!line.empty() && line.front() == ' ') line.remove_prefix(1);
        ++depth;
    }
    return {line, depth};
}
std::string_view fence_body(std::string_view line, unsigned depth) {
    // Remove exactly the opening fence's quote layers. A deeper marker belongs
    // to literal code, and a shallower line remains visibly unchanged.
    auto body = line;
    for (unsigned layer = 0; layer < depth; ++layer) {
        std::size_t indent = 0;
        while (indent < body.size() && body[indent] == ' ' && indent < 4) ++indent;
        if (indent > 3 || indent == body.size() || body[indent] != '>') return line;
        body.remove_prefix(indent + 1);
        if (!body.empty() && body.front() == ' ') body.remove_prefix(1);
    }
    return body;
}
struct Fence { char marker = 0; std::size_t count = 0; unsigned quote_depth = 0; bool operator==(const Fence&) const = default; };
struct FenceLine { char marker = 0; std::size_t count = 0; std::string_view info; };
FenceLine fence_line(std::string_view line) {
    std::size_t indent = 0;
    while (indent < line.size() && line[indent] == ' ') ++indent;
    if (indent > 3 || indent == line.size() || (line[indent] != '`' && line[indent] != '~')) return {};
    line.remove_prefix(indent);
    std::size_t count = 0; while (count < line.size() && line[count] == line.front()) ++count;
    if (count < 3) return {};
    return {line.front(), count, trim(line.substr(count))};
}
bool closes(Fence active, FenceLine line, unsigned depth) {
    return active.marker && active.quote_depth == depth && line.marker == active.marker &&
           line.count >= active.count && line.info.empty();
}
bool opens(FenceLine line) {
    return line.marker && (line.marker != '`' || line.info.find('`') == std::string_view::npos);
}
PassiveMarkdownRole message_role(std::string_view title) {
    if (title == "User" || title == "Retry") return PassiveMarkdownRole::user;
    if (title == "Assistant" || title == "Streaming" || title == "Incomplete result" ||
        title == "Transcription" || title == "Builder") return PassiveMarkdownRole::assistant;
    return PassiveMarkdownRole::none;
}
struct PrefixContext {
    Fence fence;
    PassiveMarkdownRole role = PassiveMarkdownRole::none;
    bool operator==(const PrefixContext&) const = default;
};
PrefixContext preceding_context(std::string_view source, std::size_t before) {
    PrefixContext context;
    auto& active = context.fence;
    for (std::size_t at = 0; at < before;) {
        const auto newline = source.find('\n', at);
        // A tail starting within a line must not promote its incomplete prefix
        // to a message heading or fence delimiter.
        if (newline == std::string_view::npos || newline >= before) break;
        const auto end = newline;
        auto raw = source.substr(at, end - at); if (raw.ends_with('\r')) raw.remove_suffix(1);
        // Quote/fence prefixes see the same four-space tab projection as the
        // retained preview. Only the first 64 input bytes can contain a bounded
        // quote/indent prefix; later tabs affect neither delimiter nor title.
        // Only that prefix expands; the temporary line copy stays bounded by
        // the 8 MiB source contract plus at most 192 replacement bytes.
        std::string expanded;
        const auto prefix = raw.substr(0, 64);
        if (prefix.find('\t') != std::string_view::npos) {
            expanded.reserve(raw.size() + 192);
            for (const auto ch : prefix) {
                if (ch == '\t') expanded += "    ";
                else expanded += ch;
            }
            expanded += raw.substr(prefix.size()); raw = expanded;
        }
        const auto line = line_body(raw); const auto candidate = fence_line(line.text);
        if (active.marker) { if (closes(active, candidate, line.quote_depth)) active = {}; }
        else if (opens(candidate)) active = {candidate.marker, candidate.count, line.quote_depth};
        else if (!line.quote_depth && line.text.size() > 2 && line.text.starts_with("##") &&
                 (line.text[2] == ' ' || line.text[2] == '\t')) {
            // Tabs become spaces in the display projection. Only these exact
            // ASCII titles can match; controls and Unicode cannot disappear.
            const auto role = message_role(trim(line.text.substr(2)));
            if (role != PassiveMarkdownRole::none) context.role = role;
        }
        at = end + 1;
    }
    return context;
}
struct Sanitized {
    std::string text;
    // Sanitized line beginnings mapped to original byte positions, not glyphs.
    std::vector<std::pair<std::size_t, std::size_t>> lines;
    std::size_t begin = 0;
    bool source_truncated = false, display_truncated = false, line_boundary = true;
};
Sanitized sanitize_tail(std::string_view source, const PassiveMarkdownLimits& limits) {
    Sanitized out;
    out.begin = source.size() > limits.source_bytes ? source.size() - limits.source_bytes : 0;
    out.source_truncated = out.begin != 0;
    if (out.begin) {
        const auto newline = source.find('\n', out.begin);
        if (newline != std::string_view::npos && newline + 1 < source.size()) out.begin = newline + 1;
    }
    const auto budget = limits.display_bytes - omission.size() - 2;
    std::size_t total = 0;
    for (auto at = out.begin; at < source.size();) { const auto item = atom(source, at); total += item.length; at += item.bytes; }
    if (total > budget) {
        out.display_truncated = true;
        while (out.begin < source.size() && total > budget) {
            const auto item = atom(source, out.begin); total -= item.length; out.begin += item.bytes;
        }
        const auto newline = source.find('\n', out.begin);
        if (newline != std::string_view::npos && newline + 1 < source.size()) out.begin = newline + 1;
    }
    out.line_boundary = out.begin == 0 || source[out.begin - 1] == '\n';
    out.text.reserve(std::min(total, budget)); out.lines.emplace_back(0, out.begin);
    for (auto at = out.begin; at < source.size();) {
        const auto item = atom(source, at); out.text.append(item.text.data(), item.length); at += item.bytes;
        if (item.length == 1 && item.text[0] == '\n') out.lines.emplace_back(out.text.size(), at);
    }
    return out;
}
bool hex_digit(char ch) { return (ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'F') || (ch >= 'a' && ch <= 'f'); }
std::size_t chunk_boundary(std::string_view value, std::size_t maximum) {
    if (value.size() <= maximum) return value.size();
    // Preserve fixed escape atoms, including identical forms typed literally.
    for (auto start = maximum > 10 ? maximum - 10 : 0; start < maximum; ++start) {
        if (value[start] != '[') continue;
        std::size_t digits = 0, prefix = 0;
        if (value.substr(start, 3) == "[U+") { prefix = 3; while (start + prefix + digits < value.size() && hex_digit(value[start + prefix + digits]) && digits < 6) ++digits; if (digits < 4) continue; }
        else if (value.substr(start, 3) == "[0x") { prefix = 3; digits = 2; }
        if (prefix && start + prefix + digits < value.size() && value[start + prefix + digits] == ']' && start + prefix + digits + 1 > maximum) return start;
    }
    return maximum;
}
unsigned heading_level(std::string_view value) {
    unsigned level = 0; while (level < value.size() && level < 7 && value[level] == '#') ++level;
    return level >= 1 && level <= 6 && (level == value.size() || value[level] == ' ') ? level : 0;
}
bool list_line(std::string_view value) {
    if (value.size() >= 2 && (value[0] == '-' || value[0] == '*' || value[0] == '+') && value[1] == ' ') return true;
    std::size_t count = 0; while (count < value.size() && count < 9 && value[count] >= '0' && value[count] <= '9') ++count;
    return count && count + 1 < value.size() && (value[count] == '.' || value[count] == ')') && value[count + 1] == ' ';
}
bool thematic_break(std::string_view value) {
    std::size_t indent = 0;
    while (indent < value.size() && value[indent] == ' ') ++indent;
    if (indent > 3 || indent == value.size()) return false;
    value.remove_prefix(indent);
    const auto marker = value.front();
    if (marker != '*' && marker != '-' && marker != '_') return false;
    std::size_t count = 0;
    for (const auto ch : value) {
        if (ch == marker) ++count;
        else if (ch != ' ') return false;
    }
    return count >= 3;
}
void simple_strong(PassiveMarkdownBlock& block) {
    if ((block.kind != PassiveMarkdownKind::paragraph && block.kind != PassiveMarkdownKind::quote) || block.text.size() < 5) return;
    const auto text = std::string_view(block.text);
    const auto marker = text.front();
    if ((marker != '*' && marker != '_') || text[1] != marker || text[text.size() - 2] != marker || text.back() != marker) return;
    const auto body = text.substr(2, text.size() - 4);
    if (body.empty() || trim(body) != body || body.find_first_of("*_`\\\n") != std::string_view::npos) return;
    block.text = std::string(body); block.strong = true;
}
constexpr std::size_t table_columns_limit = 8, table_rows_limit = 32, table_cell_limit = 128;
using TableAlignment = PassiveMarkdownAlignment;
using TableRow = std::vector<std::string_view>;
bool table_boundary(std::string_view value) {
    return opens(fence_line(value)) || heading_level(value) || list_line(value) || thematic_break(value);
}
std::optional<TableRow> pipe_row(std::string_view value) {
    const auto first = value.find_first_not_of(' ');
    if (first == std::string_view::npos || first > 3) return std::nullopt;
    value = trim(value);
    std::vector<std::size_t> delimiters;
    unsigned backslashes = 0;
    for (std::size_t at = 0; at < value.size(); ++at) {
        if (value[at] == '\\') { ++backslashes; continue; }
        if (value[at] == '|' && !(backslashes % 2)) {
            delimiters.push_back(at);
            if (delimiters.size() > table_columns_limit + 1) return std::nullopt;
        }
        backslashes = 0;
    }
    if (delimiters.empty()) return std::nullopt;
    const std::size_t begin = delimiters.front() == 0 ? 1 : 0;
    const auto end = delimiters.back() == value.size() - 1 ? value.size() - 1 : value.size();
    if (begin > end) return std::nullopt;
    TableRow cells;
    const auto cell = [&](std::size_t from, std::size_t to) {
        const auto text = trim(value.substr(from, to - from));
        if (text.size() > table_cell_limit || cells.size() == table_columns_limit) return false;
        cells.push_back(text); return true;
    };
    auto from = begin;
    for (const auto delimiter : delimiters) {
        if (delimiter < begin || delimiter >= end) continue;
        if (!cell(from, delimiter)) return std::nullopt;
        from = delimiter + 1;
    }
    if (!cell(from, end)) return std::nullopt;
    return cells;
}
std::optional<std::vector<TableAlignment>> table_delimiter(const TableRow& row) {
    std::vector<TableAlignment> alignments;
    for (auto text : row) {
        const bool left = !text.empty() && text.front() == ':';
        if (left) text.remove_prefix(1);
        const bool right = !text.empty() && text.back() == ':';
        if (right) text.remove_suffix(1);
        if (text.size() < 3 || text.find_first_not_of('-') != std::string_view::npos) return std::nullopt;
        alignments.push_back(left && right ? TableAlignment::center : right ? TableAlignment::right : TableAlignment::left);
    }
    return alignments;
}
bool table_header(std::string_view header, std::string_view delimiter) {
    const auto first = pipe_row(header), second = pipe_row(delimiter);
    return first && second && first->size() == second->size() && table_delimiter(*second).has_value();
}
bool project_table(PassiveMarkdownBlock& block, std::size_t maximum) {
    if (block.text.size() > maximum) return false;
    std::vector<std::string_view> lines;
    const auto source = std::string_view(block.text);
    for (std::size_t at = 0; at < source.size();) {
        const auto newline = source.find('\n', at), end = newline == std::string_view::npos ? source.size() : newline;
        lines.push_back(source.substr(at, end - at));
        at = end + (newline != std::string_view::npos);
    }
    auto begin = std::size_t{0}, end = lines.size();
    while (begin < end && trim(lines[begin]).empty()) ++begin;
    while (end > begin && trim(lines[end - 1]).empty()) --end;
    if (end - begin < 2 || end - begin > table_rows_limit + 2) return false;
    if (table_boundary(lines[begin])) return false;
    const auto header = pipe_row(lines[begin]), delimiter = pipe_row(lines[begin + 1]);
    if (!header || !delimiter || header->size() != delimiter->size()) return false;
    const auto alignments = table_delimiter(*delimiter);
    if (!alignments) return false;
    std::vector<TableRow> rows; rows.push_back(*header);
    std::vector<std::size_t> widths(header->size(), 3);
    for (std::size_t index = begin + 2; index < end; ++index) {
        if (table_boundary(lines[index])) return false;
        auto row = pipe_row(lines[index]);
        if (!row || row->size() != header->size()) return false;
        rows.push_back(std::move(*row));
    }
    for (const auto& row : rows)
        for (std::size_t column = 0; column < row.size(); ++column) widths[column] = std::max(widths[column], row[column].size());
    std::size_t row_bytes = 1;
    for (const auto width : widths) row_bytes += width + 3;
    // Header, one delimiter, and at most 32 data rows have been frozen before
    // expanding padding. Reject the complete candidate before allocating its
    // output; padding a short input can otherwise multiply the preview size.
    const auto line_count = rows.size() + 2 + (rows.size() > 1);
    if (maximum < line_count - 1 || row_bytes > (maximum - (line_count - 1)) / line_count) return false;
    const auto output_bytes = row_bytes * line_count + line_count - 1;
    std::string output; output.reserve(output_bytes);
    const auto newline = [&] { if (!output.empty()) output += '\n'; };
    const auto border = [&] {
        newline(); output += '+';
        for (const auto width : widths) { output.append(width + 2, '-'); output += '+'; }
    };
    const auto render_row = [&](const TableRow& row) {
        newline(); output += '|';
        for (std::size_t column = 0; column < row.size(); ++column) {
            const auto padding = widths[column] - row[column].size();
            const auto left = (*alignments)[column] == TableAlignment::right ? padding : (*alignments)[column] == TableAlignment::center ? padding / 2 : 0;
            output.append(left + 1, ' '); output += row[column]; output.append(padding - left + 1, ' '); output += '|';
        }
    };
    border(); render_row(rows.front()); border();
    for (std::size_t index = 1; index < rows.size(); ++index) render_row(rows[index]);
    if (rows.size() > 1) border();
    // Commit the structured model only after every row and output allocation
    // has passed. A literal fallback cannot accidentally retain partial cells.
    std::vector<std::vector<std::string>> cells;
    for (const auto& row : rows) {
        auto& saved = cells.emplace_back();
        for (const auto value : row) saved.emplace_back(value);
    }
    block.kind = PassiveMarkdownKind::table; block.text = std::move(output);
    block.table_columns = unsigned(widths.size()); block.table_rows = unsigned(rows.size() - 1);
    block.table_cells = std::move(cells); block.table_alignment = *alignments;
    return true;
}
std::string block_key(const std::string& id, const PassiveMarkdownBlock& block) {
    return id + ".block." + std::to_string(block.source_offset) + "." + std::to_string(block.part);
}
gui::Font block_font(const PassiveMarkdownBlock& block) {
    gui::Font font{13, false, block.quoted || block.kind == PassiveMarkdownKind::quote || block.kind == PassiveMarkdownKind::notice ? gui::Tone::muted : gui::Tone::normal};
    if (block.kind == PassiveMarkdownKind::heading) { constexpr double sizes[]{20,18,16,15,14,13}; font.size = sizes[block.heading_level - 1]; font.bold = true; }
    if (block.strong) font.bold = true;
    if (block.kind == PassiveMarkdownKind::rule) { font.size = 10; font.tone = gui::Tone::muted; }
    return font;
}
constexpr std::size_t table_widget_limit = 384, table_pixel_limit = 2 * 1024 * 1024;
constexpr unsigned table_sample_axis_limit = 4096;
struct BlockLane { double indent, width; };
BlockLane block_lane(const PassiveMarkdownBlock& block, double viewport_width) {
    const auto available = viewport_width - 8;
    const bool message = block.role != PassiveMarkdownRole::none;
    const auto inset = message ? std::min(80.0, available * .14) : 0.0;
    const auto depth = block.quote_depth - (block.role == PassiveMarkdownRole::assistant && block.quote_depth ? 1 : 0);
    const auto quoted = std::min(12.0 * depth, std::max(0.0, available - inset - 1));
    const auto list = !message && !depth && block.kind == PassiveMarkdownKind::list ? std::min(12.0, available - 1) : 0.0;
    return {(block.role == PassiveMarkdownRole::user ? inset : 0.0) + quoted + list,
            std::max(1.0, available - (message ? inset : 0.0) - quoted - list)};
}
struct TableCellMeasure {
    std::string text;
    gui::Font font;
    gui::Size intrinsic, wrapped;
    double available = -1, scale = 0;
    bool measured = false, valid = false;
};
struct TableLayout {
    std::vector<TableCellMeasure> measurements;
    std::vector<gui::Rect> cells;
    std::vector<double> columns, rows;
    double width = 0, height = 0;
    std::size_t pixels = 0;
    std::uint64_t revision = 0;
    gui::BitmapSource source;
};
gui::Size table_measure(std::string_view text, gui::Font font, double width, double scale,
                        gui::TextWrap wrap, const gui::TextMeasure& measure) {
    gui::Size size;
    if (measure) size = measure({std::string(text), font, width, scale, wrap});
    else {
        const auto natural = text.size() * font.size * .65;
        const auto lines = wrap == gui::TextWrap::word ? std::max(1.0, std::ceil(natural / width)) : 1.0;
        size = {wrap == gui::TextWrap::word ? std::min(width, natural) : natural, lines * font.size * 1.45};
    }
    if (!gui::valid_rect({0,0,size.width,size.height})) throw std::invalid_argument("Invalid passive table text measurement");
    return size;
}
gui::BitmapSource table_rules(double width, double height, std::vector<double> columns, std::vector<double> rows) {
    // Immutable geometry is tiny; the adapter caches painted pixels under the
    // stable ID/revision. No source strings, URLs or executable content enter it.
    return gui::BitmapSource([width, height, columns = std::move(columns), rows = std::move(rows)]
        (const gui::BitmapRequest& request, const gui::BitmapSink& sink) {
        if (request.width > table_sample_axis_limit || request.height > table_sample_axis_limit ||
            std::size_t(request.width) * request.height > table_pixel_limit)
            throw std::length_error("Passive table sample grid exceeds limits");
        const auto palette = theme::dark_palette();
        std::vector<std::uint8_t> output(gui::pixel_row_bytes(request.damage.width, request.format));
        const auto near = [](double coordinate, const auto& edges, double step) {
            return std::any_of(edges.begin(), edges.end(), [&](double edge) { return std::abs(coordinate - edge) <= step; });
        };
        for (unsigned y = 0; y < request.damage.height; ++y) {
            std::fill(output.begin(), output.end(), 0);
            const auto py = (request.damage.y + y + .5) * height / request.height;
            const bool horizontal = near(py, rows, std::max(.65, height / request.height));
            for (unsigned x = 0; x < request.damage.width; ++x) {
                const auto px = (request.damage.x + x + .5) * width / request.width;
                const bool header = std::abs(py - rows[1]) <= std::max(1.4, height / request.height);
                const bool rule = header || horizontal || near(px, columns, std::max(.65, width / request.width));
                const auto color = header ? palette.accent : rule ? palette.border : palette.surface;
                if (request.format == gui::PixelFormat::rgb24) {
                    output[x * 3] = color.red; output[x * 3 + 1] = color.green; output[x * 3 + 2] = color.blue;
                } else {
                    const auto gray = std::uint8_t((77u * color.red + 150u * color.green + 29u * color.blue + 128u) / 256u);
                    if (request.format == gui::PixelFormat::gray8) output[x] = gray;
                    else if (rule) output[x / 8] |= std::uint8_t(0x80u >> (x % 8));
                }
            }
            sink(request.damage.x, request.damage.y + y, {request.damage.width, 1, output.size(), request.format, output});
        }
    });
}
bool layout_table(TableLayout& layout, const PassiveMarkdownBlock& block, double available,
                  double scale, const gui::TextMeasure& measure, std::uint64_t& revision) {
    const auto count = block.table_cells.size() * block.table_columns;
    if (!count || count > table_widget_limit || block.table_cells.size() != block.table_rows + 1 ||
        block.table_alignment.size() != block.table_columns) return false;
    layout.measurements.resize(count);
    std::vector<double> widths(block.table_columns, 72);
    const auto base_font = block_font(block);
    for (std::size_t row = 0; row < block.table_cells.size(); ++row) {
        if (block.table_cells[row].size() != block.table_columns) return false;
        for (std::size_t column = 0; column < block.table_columns; ++column) {
            auto& cell = layout.measurements[row * block.table_columns + column];
            auto font = base_font; font.bold = row == 0;
            const auto& text = block.table_cells[row][column];
            if (!cell.valid || cell.text != text || cell.font != font || cell.scale != scale || cell.measured != bool(measure)) {
                cell.text = text; cell.font = font; cell.scale = scale; cell.measured = bool(measure); cell.valid = true;
                cell.intrinsic = table_measure(text, font, 2048, scale, gui::TextWrap::none, measure); cell.available = -1;
            }
            widths[column] = std::max(widths[column], std::min(240.0, cell.intrinsic.width + 20));
        }
    }
    double total = 0; for (const auto width : widths) total += width;
    const auto minimum = 72.0 * widths.size();
    if (total > available && available >= minimum && total > minimum) {
        const auto factor = (available - minimum) / (total - minimum);
        for (auto& width : widths) width = 72 + (width - 72) * factor;
    }
    std::vector<double> columns{0}, rows{0};
    for (const auto width : widths) columns.push_back(columns.back() + width);
    std::vector<gui::Rect> bounds(count);
    for (std::size_t row = 0; row < block.table_cells.size(); ++row) {
        double height = base_font.size * 1.6 + 20;
        for (std::size_t column = 0; column < block.table_columns; ++column) {
            auto& cell = layout.measurements[row * block.table_columns + column];
            const auto inner = widths[column] - 20;
            if (cell.available != inner) {
                cell.wrapped = cell.intrinsic.width <= inner ? cell.intrinsic :
                    table_measure(cell.text, cell.font, inner, scale, gui::TextWrap::word, measure);
                cell.available = inner;
            }
            // Label-style metrics may leave an unbroken word on one line while
            // a native text editor wraps it at the cell bounds. Reserve its
            // character-wrap height too, rather than hiding it in inner scroll.
            const auto lines = std::max(1.0, std::ceil(cell.intrinsic.width / inner));
            const auto text_height = std::max(cell.wrapped.height, lines * std::max(cell.intrinsic.height, base_font.size * 1.45));
            height = std::max(height, text_height + 20);
        }
        rows.push_back(rows.back() + height);
        for (std::size_t column = 0; column < block.table_columns; ++column) {
            const auto& cell = layout.measurements[row * block.table_columns + column];
            const auto box = std::min(widths[column] - 12, cell.wrapped.width + 8);
            const auto space = widths[column] - 12 - box;
            const auto align = block.table_alignment[column];
            const auto left = align == TableAlignment::right ? space : align == TableAlignment::center ? space / 2 : 0;
            bounds[row * block.table_columns + column] = {columns[column] + 6 + left, rows[row] + 6,
                std::max(8.0, box), height - 12};
        }
    }
    if (!gui::valid_rect({0,0,columns.back(),rows.back()})) return false;
    // Endpoint snapping can add one pixel at a translated origin. Reserve that
    // pixel on each axis before exposing any table bitmap to an adapter.
    const auto device = gui::device_rect({0,0,columns.back(),rows.back()}, scale);
    const auto device_width = std::size_t(device.width) + 1, device_height = std::size_t(device.height) + 1;
    if (device_width > table_sample_axis_limit || device_height > table_sample_axis_limit ||
        device_width * device_height > table_pixel_limit) return false;
    if (columns != layout.columns || rows != layout.rows) {
        layout.source = table_rules(columns.back(), rows.back(), columns, rows); layout.revision = ++revision;
    }
    layout.columns = std::move(columns); layout.rows = std::move(rows); layout.cells = std::move(bounds);
    layout.width = layout.columns.back(); layout.height = layout.rows.back();
    layout.pixels = device_width * device_height;
    return true;
}
} // namespace

PassiveMarkdownDocument parse_passive_markdown(std::string_view source, PassiveMarkdownLimits limits) {
    validate_limits(limits);
    auto safe = sanitize_tail(source, limits);
    PassiveMarkdownDocument out; out.source_bytes = source.size(); out.source_begin = safe.begin;
    out.source_truncated = safe.source_truncated; out.display_truncated = safe.display_truncated;
    // Inputs larger than the workbench's 8 MiB source contract remain bounded
    // literal text; no unbounded prefix walk tries to recover fence context.
    const bool syntax = source.size() <= scan_limit;
    const auto budget = limits.display_bytes - omission.size() - 2;
    std::deque<PassiveMarkdownBlock> blocks; std::size_t bytes = 0;
    const auto emit = [&](PassiveMarkdownBlock block) {
        const auto part_limit = std::min(limits.block_bytes, budget);
        if (syntax && (block.source_offset != safe.begin || safe.line_boundary)) {
            simple_strong(block);
            if (block.kind == PassiveMarkdownKind::code && block.closed && block.fence_language == "markdown")
                project_table(block, part_limit);
        }
        const auto complete = block.text.size() <= part_limit;
        std::string_view remaining = block.text; std::size_t part = 0;
        do {
            const auto length = chunk_boundary(remaining, part_limit);
            PassiveMarkdownBlock piece{block.kind, std::string(remaining.substr(0, length)), block.fence_language,
                                       block.source_offset, part++, block.heading_level, block.quoted, block.closed, complete,
                                       block.role, block.message_title, block.quote_depth, block.strong,
                                       block.table_columns, block.table_rows, block.table_cells, block.table_alignment};
            bytes += piece.text.size() + (blocks.empty() ? 0 : 2); blocks.push_back(std::move(piece));
            while (blocks.size() > limits.blocks - 1 || bytes > budget) {
                out.blocks_truncated = out.blocks_truncated || blocks.size() > limits.blocks - 1;
                out.display_truncated = out.display_truncated || bytes > budget;
                bytes -= blocks.front().text.size(); blocks.pop_front(); if (!blocks.empty()) bytes -= 2;
            }
            remaining.remove_prefix(length);
        } while (!remaining.empty());
    };
    const auto context = syntax ? preceding_context(source, safe.begin) : PrefixContext{};
    Fence active = context.fence;
    auto role = context.role;
    std::optional<PassiveMarkdownBlock> pending;
    if (active.marker) pending = PassiveMarkdownBlock{PassiveMarkdownKind::code, {}, {}, safe.begin, 0, 0, bool(active.quote_depth), false, true, role, false, active.quote_depth};
    const auto flush = [&] { if (pending) { emit(std::move(*pending)); pending.reset(); } };
    for (std::size_t index = 0; index < safe.lines.size(); ++index) {
        const auto at = safe.lines[index].first;
        if (at == safe.text.size()) break;
        const auto newline = safe.text.find('\n', at), end = newline == std::string::npos ? safe.text.size() : newline;
        const auto original = safe.lines[index].second;
        const auto raw = std::string_view(safe.text).substr(at, end - at);
        const bool line_syntax = syntax && (index != 0 || safe.line_boundary);
        auto line = line_syntax ? line_body(raw) : Line{raw, 0};
        const auto fence = line_syntax ? fence_line(line.text) : FenceLine{};
        if (active.marker) {
            if (closes(active, fence, line.quote_depth)) { pending->closed = true; flush(); active = {}; }
            else { pending->text += line_syntax ? fence_body(raw, active.quote_depth) : raw; if (newline != std::string::npos) pending->text += '\n'; }
            continue;
        }
        if (opens(fence)) {
            flush(); active = {fence.marker, fence.count, line.quote_depth};
            pending = PassiveMarkdownBlock{PassiveMarkdownKind::code, {}, fence.info.size() <= 32 ? std::string(fence.info) : "[omitted fence label]", original, 0, 0, bool(line.quote_depth), false, true, role, false, line.quote_depth}; continue;
        }
        if (trim(line.text).empty()) { flush(); continue; }
        if (line_syntax && !table_boundary(line.text) && line.text.find('|') != std::string_view::npos && index + 1 < safe.lines.size() && safe.lines[index + 1].first < safe.text.size()) {
            const auto next_at = safe.lines[index + 1].first, next_newline = safe.text.find('\n', next_at);
            const auto next_raw = std::string_view(safe.text).substr(next_at, (next_newline == std::string::npos ? safe.text.size() : next_newline) - next_at);
            const auto next = line_body(next_raw);
            if (line.quote_depth == next.quote_depth && table_header(line.text, next.text)) {
                flush();
                PassiveMarkdownBlock table{line.quote_depth ? PassiveMarkdownKind::quote : PassiveMarkdownKind::paragraph,
                    std::string(line.text) + '\n' + std::string(next.text), {}, original, 0, 0, bool(line.quote_depth), true, true, role, false, line.quote_depth};
                std::size_t following = index + 2;
                for (; following < safe.lines.size() && safe.lines[following].first < safe.text.size(); ++following) {
                    const auto row_at = safe.lines[following].first, row_newline = safe.text.find('\n', row_at);
                    const auto row = line_body(std::string_view(safe.text).substr(row_at, (row_newline == std::string::npos ? safe.text.size() : row_newline) - row_at));
                    if (row.quote_depth != line.quote_depth || table_boundary(row.text) || row.text.find('|') == std::string_view::npos) break;
                    table.text += '\n'; table.text += row.text;
                }
                project_table(table, std::min(limits.block_bytes, budget));
                emit(std::move(table)); index = following - 1; continue;
            }
        }
        if (line_syntax && thematic_break(line.text)) {
            flush(); emit({PassiveMarkdownKind::rule, "--------------------------------", {}, original, 0, 0, bool(line.quote_depth), true, true, role, false, line.quote_depth}); continue;
        }
        const auto level = line_syntax ? heading_level(line.text) : 0;
        const auto kind = level ? PassiveMarkdownKind::heading : line_syntax && list_line(line.text) ? PassiveMarkdownKind::list : line.quote_depth ? PassiveMarkdownKind::quote : PassiveMarkdownKind::paragraph;
        const auto text = level ? trim(line.text.substr(level)) : line.text;
        if (kind == PassiveMarkdownKind::heading || kind == PassiveMarkdownKind::list) {
            flush();
            const auto title_role = level == 2 && !line.quote_depth ? message_role(text) : PassiveMarkdownRole::none;
            const bool title = title_role != PassiveMarkdownRole::none;
            if (title) role = title_role;
            emit({kind, std::string(text), {}, original, 0, level, bool(line.quote_depth), true, true, role, title, line.quote_depth}); continue;
        }
        if (!pending || pending->kind != kind || pending->quote_depth != line.quote_depth) {
            flush(); pending = PassiveMarkdownBlock{kind, {}, {}, original, 0, 0, bool(line.quote_depth), true, true, role, false, line.quote_depth};
        }
        if (!pending->text.empty()) pending->text += '\n';
        pending->text += text;
    }
    flush();
    if (out.truncated()) out.blocks.push_back({PassiveMarkdownKind::notice, std::string(omission), {}, 0});
    for (auto& block : blocks) out.blocks.push_back(std::move(block));
    bool after_notice = false;
    for (const auto& block : out.blocks) {
        if (!out.display_text.empty() && (block.part == 0 || after_notice)) out.display_text += "\n\n";
        out.display_text += block.text;
        after_notice = block.kind == PassiveMarkdownKind::notice;
    }
    return out;
}

struct PassiveMarkdownView::Impl {
    PassiveMarkdownLimits limits;
    PassiveMarkdownDocument document;
    std::string source_tail;
    std::size_t source_size = std::numeric_limits<std::size_t>::max();
    std::uint64_t source_revision = 0;
    PrefixContext prefix_context;
    std::uint64_t revision = 0, table_revision = 0;
    struct Entry {
        PassiveMarkdownBlock block;
        double width = -1, scale = 0, height = 0;
        bool measured = false, diagram_checked = false;
        PassiveDiagram diagram;
        PassiveDiagramView diagram_view;
        std::vector<gui::Widget> diagram_widgets;
        gui::Rect diagram_bounds;
        std::string diagram_parent;
        TableLayout table;
    };
    std::map<std::string, Entry> cache;
    explicit Impl(PassiveMarkdownLimits value) : limits(value) { validate_limits(limits); }
};
PassiveMarkdownView::PassiveMarkdownView(PassiveMarkdownLimits limits) : impl_(std::make_unique<Impl>(limits)) {}
PassiveMarkdownView::~PassiveMarkdownView() = default;
PassiveMarkdownView::PassiveMarkdownView(PassiveMarkdownView&&) noexcept = default;
PassiveMarkdownView& PassiveMarkdownView::operator=(PassiveMarkdownView&&) noexcept = default;
const PassiveMarkdownDocument& PassiveMarkdownView::document() const noexcept { return impl_->document; }
std::uint64_t PassiveMarkdownView::revision() const noexcept { return impl_->revision; }

std::vector<gui::Widget> PassiveMarkdownView::render(std::string_view source, gui::Rect viewport, std::string id, std::string parent, const gui::TextMeasure& measure, double scale, std::uint64_t source_revision) {
    (void)gui::device_rect(viewport, scale);
    if (id.empty() || !gui::valid_utf8(id) || !gui::valid_utf8(parent)) throw std::invalid_argument("Invalid passive Markdown widget identity");
    auto& state = *impl_;
    const auto tail = source.substr(source.size() > state.limits.source_bytes ? source.size() - state.limits.source_bytes : 0);
    // Prefix changes can alter a retained tail's fence context. Consult only
    // the bounded 8 MiB workbench input contract; never retain a second full
    // history copy merely to invalidate the preview cache.
    const auto context = !source_revision && source.size() <= scan_limit ? preceding_context(source, std::min(state.document.source_begin, source.size())) : PrefixContext{};
    const bool changed = source_revision ? state.source_revision != source_revision || state.source_size != source.size() :
        state.source_revision || state.source_size != source.size() || state.source_tail != tail || state.prefix_context != context;
    if (changed) {
        state.document = parse_passive_markdown(source, state.limits); state.source_size = source.size();
        // An authoritative revision already binds content; retain a comparison
        // tail only for callers using the zero-revision fallback.
        if (source_revision) state.source_tail.clear(); else state.source_tail = tail;
        state.source_revision = source_revision;
        state.prefix_context = !source_revision && source.size() <= scan_limit ? preceding_context(source, state.document.source_begin) : PrefixContext{};
        ++state.revision;
    }
    gui::Widget group; group.spec.key = {id, 1}; group.spec.kind = gui::Kind::group; group.spec.parent = std::move(parent);
    group.state.bounds = viewport; group.state.content_clip = gui::Rect{0,0,viewport.width,viewport.height};
    group.state.accessible_name = "Passive Markdown preview";
    std::vector<gui::Widget> result; result.push_back(std::move(group));
    if (viewport.width < 16 || viewport.height == 0) return result;
    double y = viewport.y + 4, content_right = viewport.x + viewport.width;
    std::map<std::string, TableLayout> tables;
    std::size_t cell_budget = table_widget_limit, pixel_budget = table_pixel_limit;
    // Reserve whole native tables from the newest end. Never publish a partial
    // collection of cells, and never retain excluded tables' measurement/source
    // caches after this frame.
    for (auto at = state.document.blocks.rbegin(); at != state.document.blocks.rend(); ++at) {
        if (at->kind != PassiveMarkdownKind::table) continue;
        const auto count = at->table_cells.size() * at->table_columns;
        if (count > cell_budget) continue;
        const auto key = block_key(id, *at);
        auto found = state.cache.find(key);
        auto layout = found == state.cache.end() ? TableLayout{} : std::move(found->second.table);
        if (!layout_table(layout, *at, block_lane(*at, viewport.width).width, scale, measure, state.table_revision) || layout.pixels > pixel_budget) continue;
        cell_budget -= count; pixel_budget -= layout.pixels;
        tables.emplace(key, std::move(layout));
    }
    const auto diagram_candidate = [](const auto& block) { return block.kind == PassiveMarkdownKind::code && block.closed && block.complete && block.fence_language == "mermaid"; };
    auto remaining_diagrams = std::count_if(state.document.blocks.begin(), state.document.blocks.end(), diagram_candidate);
    std::map<std::string, Impl::Entry> next_cache;
    for (const auto& block : state.document.blocks) {
        const auto key = block.kind == PassiveMarkdownKind::notice ? id + ".notice" : block_key(id, block);
        auto found = state.cache.find(key);
        auto entry = found == state.cache.end() ? Impl::Entry{} : std::move(found->second);
        if (entry.block != block) { entry = {}; entry.block = block; }
        const auto lane = block_lane(block, viewport.width);
        const auto indent = lane.indent, width = lane.width;
        const auto table = tables.find(key);
        if (table != tables.end()) entry.table = std::move(table->second); else entry.table = {};
        const bool native_table = table != tables.end();
        if (block.message_title && y > viewport.y + 4) y += 10;
        const auto font = block_font(block);
        const auto wrap = block.kind == PassiveMarkdownKind::code || block.kind == PassiveMarkdownKind::rule || block.kind == PassiveMarkdownKind::table ? gui::TextWrap::none : gui::TextWrap::word;
        if (!native_table && (entry.width != width || entry.scale != scale || entry.measured != bool(measure))) {
            gui::Size natural;
            if (measure) natural = measure({block.text, font, std::max(1.0, width - 8), scale, wrap});
            else {
                const auto rows = 1 + std::count(block.text.begin(), block.text.end(), '\n');
                natural = {width, rows * font.size * 1.45};
            }
            if (!gui::valid_rect({0,0,natural.width,natural.height})) throw std::invalid_argument("Invalid passive Markdown text measurement");
            entry.height = block.kind == PassiveMarkdownKind::rule ? std::clamp(natural.height + 6, 12.0, 26.0) :
                std::clamp(natural.height + 14, font.size * 1.6 + 8, 240.0);
            entry.width = width; entry.scale = scale; entry.measured = bool(measure);
        }
        const bool eligible_diagram = diagram_candidate(block) && remaining_diagrams-- <= 4;
        if (!eligible_diagram) entry.diagram_widgets.clear();
        if (!entry.diagram_checked && eligible_diagram) {
            entry.diagram = parse_passive_diagram(block.text); entry.diagram_checked = true;
        }
        const bool diagram = eligible_diagram && entry.diagram.supported;
        const auto height = native_table ? entry.table.height : diagram ? passive_diagram_height(entry.diagram, width) : entry.height;
        if (y + height > gui::coordinate_limit) break;
        const gui::Rect bounds{viewport.x + 4 + indent, y, width, height};
        if (native_table) {
            const auto& layout = entry.table;
            const gui::Rect grid{bounds.x, bounds.y, layout.width, layout.height};
            gui::Widget rules; rules.spec.key = {key + ".table.rules", 1}; rules.spec.kind = gui::Kind::bitmap; rules.spec.parent = id;
            rules.state.bounds = grid; rules.state.label = rules.state.accessible_name = "Markdown table, " +
                std::to_string(block.table_columns) + " columns, " + std::to_string(block.table_rows) + " data rows";
            rules.state.bitmap = {key + ".table.raster", layout.revision, layout.source};
            result.push_back(std::move(rules));
            for (std::size_t row = 0; row < block.table_cells.size(); ++row) {
                for (std::size_t column = 0; column < block.table_columns; ++column) {
                    const auto index = row * block.table_columns + column;
                    const auto& local = layout.cells[index];
                    gui::Widget cell; cell.spec.key = {key + ".table.cell." + std::to_string(row) + "." + std::to_string(column), 1};
                    cell.spec.kind = gui::Kind::text; cell.spec.parent = id;
                    cell.spec.text_policy = {true, true, table_cell_limit, gui::SubmitKey::none};
                    cell.state.bounds = {grid.x + local.x, grid.y + local.y, local.width, local.height};
                    cell.state.text = block.table_cells[row][column]; cell.state.font = layout.measurements[index].font;
                    cell.state.wrap = gui::TextWrap::word; cell.state.text_frame = false;
                    cell.state.label = cell.state.accessible_name = row == 0 ? "Table header, column " + std::to_string(column + 1) :
                        "Table row " + std::to_string(row) + ", column " + std::to_string(column + 1) + ", " + block.table_cells[0][column];
                    result.push_back(std::move(cell));
                }
            }
            content_right = std::max(content_right, grid.x + grid.width + 4);
        } else if (diagram) {
            if (entry.diagram_widgets.empty() || entry.diagram_bounds != bounds || entry.diagram_parent != id) {
                entry.diagram_widgets = entry.diagram_view.render(entry.diagram, bounds, key + ".diagram", id);
                entry.diagram_bounds = bounds; entry.diagram_parent = id;
            }
            result.insert(result.end(), entry.diagram_widgets.begin(), entry.diagram_widgets.end());
        } else {
            gui::Widget widget; widget.spec.key = {key, 1}; widget.spec.kind = gui::Kind::text; widget.spec.parent = id;
            widget.spec.text_policy = {true, true, std::max(state.limits.block_bytes, block.text.size()), gui::SubmitKey::none};
            widget.state.bounds = bounds; widget.state.text = block.text; widget.state.font = font; widget.state.wrap = wrap;
            widget.state.text_frame = block.message_title;
            widget.state.label = widget.state.accessible_name = block.kind == PassiveMarkdownKind::code ? "Literal code" : block.kind == PassiveMarkdownKind::heading ? "Markdown heading" : block.kind == PassiveMarkdownKind::notice ? "Preview omission" : block.kind == PassiveMarkdownKind::rule ? "Markdown separator" : block.strong ? "Markdown strong text" : "Markdown text";
            if (block.kind == PassiveMarkdownKind::table)
                widget.state.label = widget.state.accessible_name = "Markdown table, " + std::to_string(block.table_columns) + " columns, " + std::to_string(block.table_rows) + " data rows";
            if (entry.diagram_checked && !entry.diagram.supported) widget.state.help = entry.diagram.diagnostic;
            result.push_back(std::move(widget));
        }
        next_cache.emplace(key, std::move(entry)); y += height + 6;
    }
    state.cache = std::move(next_cache);
    result.front().state.content_size = {std::min(gui::coordinate_limit, content_right - viewport.x), std::min(gui::coordinate_limit, std::max(viewport.height, y - viewport.y + 4))};
    return result;
}
} // namespace tinyenv
