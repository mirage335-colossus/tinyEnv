#include "pseudocode.hpp"

#include <algorithm>
#include <charconv>
#include <stdexcept>
#include <utility>

namespace tinyenv {
namespace {
std::string_view trim(std::string_view value) {
    const auto start = value.find_first_not_of(" \t\r");
    if (start == std::string_view::npos) return {};
    const auto end = value.find_last_not_of(" \t\r");
    return value.substr(start, end - start + 1);
}
bool role_valid(std::string_view value) {
    auto alpha = [](char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); };
    if (value.empty() || value.size() > 64 || !alpha(value.front())) return false;
    return std::all_of(value.begin(), value.end(), [&](char c) {
        return alpha(c) || (c >= '0' && c <= '9') || c == '_' || c == '-';
    });
}
std::optional<FlowCondition> condition(std::string_view value) {
    if (value == "approved") return FlowCondition::approved;
    if (value == "supported") return FlowCondition::supported;
    if (value == "rejected") return FlowCondition::rejected;
    return std::nullopt;
}
bool starts(std::string_view value, std::string_view prefix) {
    return value.size() >= prefix.size() && value.substr(0, prefix.size()) == prefix;
}
struct Line { std::string_view text; std::size_t number; };
std::optional<std::pair<std::uint32_t, std::size_t>> codepoint(std::string_view value, std::size_t offset) {
    const auto first = static_cast<unsigned char>(value[offset]);
    if (first < 128) return std::pair<std::uint32_t, std::size_t>{first, 1};
    std::size_t bytes = 0;
    std::uint32_t result = 0, minimum = 0;
    if (first >= 0xc2 && first <= 0xdf) { bytes = 2; result = first & 0x1fU; minimum = 0x80; }
    else if (first >= 0xe0 && first <= 0xef) { bytes = 3; result = first & 0xfU; minimum = 0x800; }
    else if (first >= 0xf0 && first <= 0xf4) { bytes = 4; result = first & 7U; minimum = 0x10000; }
    else return std::nullopt;
    if (bytes > value.size() - offset) return std::nullopt;
    for (std::size_t index = 1; index < bytes; ++index) {
        const auto byte = static_cast<unsigned char>(value[offset + index]);
        if ((byte & 0xc0U) != 0x80U) return std::nullopt;
        result = (result << 6U) | (byte & 0x3fU);
    }
    if (result < minimum || result > 0x10ffffU || (result >= 0xd800 && result <= 0xdfff)) return std::nullopt;
    return std::pair<std::uint32_t, std::size_t>{result, bytes};
}
enum class Stop { none, until, otherwise, end };
class Parser {
public:
    Parser(PseudocodeParseResult& result, const PseudocodeLimits& limits)
        : result_(result), limits_(limits) {}
    void parse() {
        if (limits_.nesting > 64 || limits_.repeat_iterations > 2147483647U) {
            fail(1, "configured nesting or repeat limit exceeds its hard ceiling"); return;
        }
        if (result_.source.size() > limits_.source_bytes) {
            fail(1, "source exceeds the byte limit"); return;
        }
        std::size_t number = 1, offset = 0;
        while (offset < result_.source.size()) {
            if (number > limits_.lines) { fail(number, "source exceeds the line limit"); return; }
            const auto newline = result_.source.find('\n', offset);
            const auto count = newline == std::string::npos ? result_.source.size() - offset : newline - offset;
            auto view = std::string_view(result_.source).substr(offset, count);
            for (std::size_t i = 0; i < view.size();) {
                const auto point = codepoint(view, i);
                if (!point) { fail(number, "source contains invalid UTF-8", i + 1); return; }
                const auto [value, bytes] = *point;
                if ((value < 32 && value != '\t' && value != '\r') || (value >= 127 && value <= 159)) {
                    fail(number, "control character is not allowed", i + 1); return;
                }
                if (view[i] == '\r' && i + 1 != view.size()) {
                    fail(number, "carriage return is only allowed at line end", i + 1); return;
                }
                i += bytes;
            }
            lines_.push_back({trim(view), number++});
            if (newline == std::string::npos) break;
            offset = newline + 1;
        }
        FlowProgram program;
        program.nodes = block(0, Stop::none);
        if (result_.diagnostics.empty()) result_.program = std::move(program);
    }
private:
    void fail(std::size_t line, std::string message, std::size_t column = 1) {
        if (result_.diagnostics.size() < 64) result_.diagnostics.push_back({line, column, std::move(message)});
    }
    Stop stop(std::string_view text) const {
        if (starts(text, "until ") || text == "until") return Stop::until;
        if (text == "else") return Stop::otherwise;
        if (text == "end") return Stop::end;
        return Stop::none;
    }
    std::vector<FlowNode> block(std::size_t depth, Stop closing) {
        std::vector<FlowNode> nodes;
        if (depth > limits_.nesting) {
            fail(cursor_ < lines_.size() ? lines_[cursor_].number : 1, "nesting limit exceeded");
            cursor_ = lines_.size(); return nodes;
        }
        while (cursor_ < lines_.size()) {
            const auto line = lines_[cursor_];
            if (line.text.empty() || starts(line.text, "#")) { ++cursor_; continue; }
            const auto terminal = stop(line.text);
            if (terminal != Stop::none) {
                if (closing == Stop::until && terminal == Stop::until) return nodes;
                if (closing == Stop::end && (terminal == Stop::end || terminal == Stop::otherwise)) return nodes;
                fail(line.number, "unexpected block terminator"); ++cursor_; continue;
            }
            if (next_id_ > limits_.nodes) { fail(line.number, "node limit exceeded"); cursor_ = lines_.size(); break; }
            FlowNode node;
            node.id = next_id_++; node.line = node.end_line = line.number;
            ++cursor_;
            if (starts(line.text, "agent ") || starts(line.text, "critique ")) {
                node.kind = starts(line.text, "agent ") ? FlowKind::agent : FlowKind::critique;
                const auto prefix = node.kind == FlowKind::agent ? 6U : 9U;
                const auto payload = line.text.substr(prefix);
                const auto colon = payload.find(':');
                if (colon == std::string_view::npos) {
                    fail(line.number, "agent and critique commands require ROLE: TEXT"); continue;
                }
                node.role = std::string(trim(payload.substr(0, colon)));
                node.text = std::string(trim(payload.substr(colon + 1)));
                if (!role_valid(node.role)) fail(line.number, "role must start with a letter and contain only letters, digits, _ or -");
                if (node.text.empty()) fail(line.number, "prompt or critique criteria must not be empty");
            } else if (starts(line.text, "repeat ")) {
                node.kind = FlowKind::repeat;
                const auto value = trim(line.text.substr(7));
                const auto parsed = std::from_chars(value.data(), value.data() + value.size(), node.iterations);
                if (value.empty() || parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() ||
                    node.iterations == 0 || node.iterations > limits_.repeat_iterations)
                    fail(line.number, "repeat requires a positive bounded iteration count");
                node.children = block(depth + 1, Stop::until);
                if (node.children.empty()) fail(line.number, "repeat body must not be empty");
                if (cursor_ == lines_.size()) fail(line.number, "repeat is missing until approved or until supported");
                else {
                    const auto terminal_line = lines_[cursor_++];
                    node.end_line = terminal_line.number;
                    const auto value_condition = condition(trim(terminal_line.text.substr(5)));
                    if (!value_condition || *value_condition == FlowCondition::rejected)
                        fail(terminal_line.number, "until requires approved or supported");
                    else node.condition = *value_condition;
                }
            } else if (starts(line.text, "if ")) {
                node.kind = FlowKind::branch;
                const auto value_condition = condition(trim(line.text.substr(3)));
                if (!value_condition) fail(line.number, "if requires approved, supported or rejected");
                else node.condition = *value_condition;
                node.children = block(depth + 1, Stop::end);
                if (cursor_ < lines_.size() && lines_[cursor_].text == "else") {
                    ++cursor_; node.otherwise = block(depth + 1, Stop::end);
                }
                if (cursor_ == lines_.size() || lines_[cursor_].text != "end") fail(line.number, "if is missing end");
                else node.end_line = lines_[cursor_++].number;
            } else if (starts(line.text, "conclude:")) {
                node.kind = FlowKind::conclude;
                node.text = std::string(trim(line.text.substr(9)));
                if (node.text.empty()) fail(line.number, "conclusion checkpoint label must not be empty");
            } else {
                fail(line.number, "unknown command; use agent, critique, repeat, if or conclude"); continue;
            }
            nodes.push_back(std::move(node));
        }
        return nodes;
    }
    PseudocodeParseResult& result_;
    const PseudocodeLimits& limits_;
    std::vector<Line> lines_;
    std::size_t cursor_ = 0;
    std::uint64_t next_id_ = 1;
};

void write_nodes(std::string& output, const std::vector<FlowNode>& nodes, std::size_t depth,
                 std::size_t& count, std::size_t& lines, const PseudocodeLimits& limits) {
    if (depth > limits.nesting) throw std::invalid_argument("nesting limit exceeded");
    const auto append = [&](std::string value) {
        const auto indentation = depth * 2;
        if (output.size() > limits.source_bytes) throw std::invalid_argument("source byte limit exceeded");
        const auto remaining = limits.source_bytes - output.size();
        if (indentation > remaining || value.size() > remaining - indentation ||
            remaining - indentation - value.size() < 1)
            throw std::invalid_argument("source byte limit exceeded");
        if (lines >= limits.lines) throw std::invalid_argument("source line limit exceeded");
        ++lines;
        output.append(indentation, ' ');
        output += value;
        output.push_back('\n');
    };
    for (const auto& node : nodes) {
        if (++count > limits.nodes) throw std::invalid_argument("node limit exceeded");
        if (node.kind != FlowKind::repeat && node.kind != FlowKind::branch &&
            (!node.children.empty() || !node.otherwise.empty()))
            throw std::invalid_argument("only repeat and if commands can own children");
        if (node.kind != FlowKind::branch && !node.otherwise.empty())
            throw std::invalid_argument("only if commands can own an else branch");
        if (node.kind == FlowKind::agent || node.kind == FlowKind::critique || node.kind == FlowKind::conclude) {
            if (trim(node.text).empty() || node.text.find_first_of("\r\n") != std::string::npos)
                throw std::invalid_argument("text must be a nonempty single line");
            if (node.kind == FlowKind::conclude) append("conclude: " + node.text);
            else {
                if (!role_valid(node.role)) throw std::invalid_argument("invalid agent role");
                append(flow_kind_name(node.kind) + " " + node.role + ": " + node.text);
            }
        } else if (node.kind == FlowKind::repeat) {
            if (node.iterations == 0 || node.iterations > limits.repeat_iterations)
                throw std::invalid_argument("invalid repeat iteration count");
            if (node.children.empty()) throw std::invalid_argument("repeat body must not be empty");
            if (node.condition == FlowCondition::rejected) throw std::invalid_argument("repeat cannot stop on rejection");
            append("repeat " + std::to_string(node.iterations));
            write_nodes(output, node.children, depth + 1, count, lines, limits);
            append("until " + flow_condition_name(node.condition));
        } else if (node.kind == FlowKind::branch) {
            append("if " + flow_condition_name(node.condition));
            write_nodes(output, node.children, depth + 1, count, lines, limits);
            if (!node.otherwise.empty()) {
                append("else"); write_nodes(output, node.otherwise, depth + 1, count, lines, limits);
            }
            append("end");
        } else throw std::invalid_argument("unknown flow node kind");
    }
}

struct Location { std::vector<FlowNode>* list = nullptr; std::size_t index = 0; };
Location locate(std::vector<FlowNode>& nodes, std::uint64_t id) {
    for (std::size_t index = 0; index < nodes.size(); ++index) {
        if (nodes[index].id == id) return {&nodes, index};
        auto found = locate(nodes[index].children, id);
        if (found.list) return found;
        found = locate(nodes[index].otherwise, id);
        if (found.list) return found;
    }
    return {};
}
bool contains(const FlowNode& node, std::uint64_t id) {
    if (node.id == id) return true;
    for (const auto& child : node.children) if (contains(child, id)) return true;
    for (const auto& child : node.otherwise) if (contains(child, id)) return true;
    return false;
}
std::vector<FlowNode>* destination(FlowProgram& program, std::uint64_t id, bool otherwise) {
    if (!id) return otherwise ? nullptr : &program.nodes;
    auto found = locate(program.nodes, id);
    if (!found.list) return nullptr;
    auto& node = (*found.list)[found.index];
    if (node.kind == FlowKind::branch) return otherwise ? &node.otherwise : &node.children;
    if (node.kind == FlowKind::repeat && !otherwise) return &node.children;
    return nullptr;
}
struct Frontier { std::uint64_t id; std::string label; };
std::vector<Frontier> graph_nodes(FlowGraph& graph, const std::vector<FlowNode>& nodes,
                                std::vector<Frontier> previous, std::size_t depth,
                                std::size_t& row) {
    for (const auto& node : nodes) {
        std::string label;
        switch (node.kind) {
        case FlowKind::agent: case FlowKind::critique:
            label = flow_kind_name(node.kind) + " " + node.role + ": " + node.text; break;
        case FlowKind::repeat: label = "repeat " + std::to_string(node.iterations); break;
        case FlowKind::branch: label = "if " + flow_condition_name(node.condition); break;
        case FlowKind::conclude: label = "conclude: " + node.text; break;
        }
        graph.nodes.push_back({node.id, node.kind, node.line, std::move(label),
                               20.0 + depth * 290.0, 20.0 + row++ * 88.0, 250, 64});
        for (const auto& from : previous) graph.edges.push_back({from.id, node.id, from.label, false});
        if (node.kind == FlowKind::repeat) {
            auto tails = graph_nodes(graph, node.children, {{node.id, "iterate"}}, depth + 1, row);
            for (const auto& tail : tails)
                graph.edges.push_back({tail.id, node.id, tail.label.empty() ? "retry" : tail.label + "; retry", true});
            previous = {{node.id, "until " + flow_condition_name(node.condition)}};
        } else if (node.kind == FlowKind::branch) {
            auto yes = graph_nodes(graph, node.children, {{node.id, "yes"}}, depth + 1, row);
            auto no = graph_nodes(graph, node.otherwise, {{node.id, "no"}}, depth + 1, row);
            previous = std::move(yes);
            previous.insert(previous.end(), no.begin(), no.end());
        } else previous = {{node.id, {}}};
    }
    return previous;
}
} // namespace

PseudocodeParseResult parse_pseudocode(std::string_view source, const PseudocodeLimits& limits) {
    PseudocodeParseResult result;
    result.source = std::string(source);
    Parser(result, limits).parse();
    return result;
}
std::string write_pseudocode(const FlowProgram& program, const PseudocodeLimits& limits) {
    if (limits.nesting > 64 || limits.repeat_iterations > 2147483647U)
        throw std::invalid_argument("configured nesting or repeat limit exceeds its hard ceiling");
    std::string output;
    std::size_t count = 0, lines = 0;
    write_nodes(output, program.nodes, 0, count, lines, limits);
    const auto result = parse_pseudocode(output, limits);
    if (!result) throw std::invalid_argument(result.diagnostics.front().message);
    return output;
}
std::string flow_kind_name(FlowKind kind) {
    switch (kind) {
    case FlowKind::agent: return "agent";
    case FlowKind::critique: return "critique";
    case FlowKind::repeat: return "repeat";
    case FlowKind::branch: return "if";
    case FlowKind::conclude: return "conclude";
    }
    throw std::invalid_argument("unknown flow kind");
}
std::string flow_condition_name(FlowCondition value) {
    switch (value) {
    case FlowCondition::approved: return "approved";
    case FlowCondition::supported: return "supported";
    case FlowCondition::rejected: return "rejected";
    }
    throw std::invalid_argument("unknown flow condition");
}
std::vector<std::string> pseudocode_snippets() {
    return {
        "agent writer: Answer the user request using the selected context.\n",
        "critique reviewer: Check hypothesis, evidence, conclusion support and unresolved doubts.\n",
        "repeat 3\n  agent writer: Improve the answer using previous reviewer feedback.\n  critique reviewer: Approve only supported conclusions with no unresolved doubts.\nuntil approved\nconclude: Deliver the reviewed answer.\n",
        "if rejected\n  agent researcher: Resolve the specific gaps identified by the reviewer.\nelse\n  conclude: Deliver the supported answer.\nend\n",
        "repeat 2\n  repeat 3\n    agent writer: Resolve the current hypothesis.\n    critique reviewer: Reject unsupported claims and record remaining doubts.\n  until approved\n  critique auditor: Check the whole conclusion against the user request.\nuntil approved\nconclude: Deliver the audited answer.\n"
    };
}
FlowGraph make_flow_graph(const FlowProgram& program) {
    FlowGraph graph;
    std::size_t row = 0;
    graph_nodes(graph, program.nodes, {}, 0, row);
    for (const auto& node : graph.nodes) {
        graph.width = std::max(graph.width, node.x + node.width + 20);
        graph.height = std::max(graph.height, node.y + node.height + 20);
    }
    return graph;
}
PseudocodeDocument::PseudocodeDocument(std::string source, PseudocodeLimits limits) : limits_(limits) {
    parsed_ = parse_pseudocode(source, limits_);
}
void PseudocodeDocument::set_text(std::string source) {
    parsed_ = parse_pseudocode(source, limits_);
    ++revision_;
}
bool PseudocodeDocument::apply(const FlowEdit& edit, std::uint64_t revision, std::string& error) {
    error.clear();
    if (revision != revision_) { error = "the graph changed before this action"; return false; }
    if (!parsed_.program) { error = "repair the text diagnostics before editing its graph"; return false; }
    auto program = *parsed_.program;
    if (edit.kind == FlowEditKind::insert) {
        auto* list = destination(program, edit.parent_id, edit.otherwise);
        if (!list || edit.index > list->size()) { error = "invalid insertion destination"; return false; }
        list->insert(list->begin() + static_cast<std::ptrdiff_t>(edit.index), edit.node);
    } else {
        const auto found = locate(program.nodes, edit.node_id);
        if (!found.list) { error = "the selected node no longer exists"; return false; }
        if (edit.kind == FlowEditKind::erase) {
            found.list->erase(found.list->begin() + static_cast<std::ptrdiff_t>(found.index));
        } else if (edit.kind == FlowEditKind::update) {
            auto replacement = edit.node;
            // Scalar edits retain existing nested branches. Use erase/move for
            // removing children, or supply a nonempty replacement subtree.
            const auto& previous = (*found.list)[found.index];
            if (replacement.kind == previous.kind) {
                if (replacement.children.empty()) replacement.children = previous.children;
                if (replacement.otherwise.empty()) replacement.otherwise = previous.otherwise;
            }
            (*found.list)[found.index] = std::move(replacement);
        } else if (edit.kind == FlowEditKind::move) {
            auto moving = (*found.list)[found.index];
            if (contains(moving, edit.parent_id)) { error = "a node cannot move into itself or its descendants"; return false; }
            found.list->erase(found.list->begin() + static_cast<std::ptrdiff_t>(found.index));
            auto* list = destination(program, edit.parent_id, edit.otherwise);
            if (!list || edit.index > list->size()) { error = "invalid move destination"; return false; }
            list->insert(list->begin() + static_cast<std::ptrdiff_t>(edit.index), std::move(moving));
        } else { error = "unknown graph edit"; return false; }
    }
    try {
        auto source = write_pseudocode(program, limits_);
        auto next = parse_pseudocode(source, limits_);
        if (!next) { error = next.diagnostics.front().message; return false; }
        parsed_ = std::move(next); ++revision_;
    } catch (const std::exception& failure) { error = failure.what(); return false; }
    return true;
}
FlowGraph PseudocodeDocument::graph() const {
    return parsed_.program ? make_flow_graph(*parsed_.program) : FlowGraph{};
}

} // namespace tinyenv
