#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace tinyenv {

enum class FlowKind { agent, critique, repeat, branch, conclude };
enum class FlowCondition { approved, supported, rejected };

struct PseudocodeDiagnostic {
    std::size_t line = 1, column = 1;
    std::string message;
    bool operator==(const PseudocodeDiagnostic&) const = default;
};
struct PseudocodeLimits {
    std::size_t source_bytes = 256 * 1024, lines = 8192, nodes = 2048;
    // Configurations above 64 nested blocks or INT32_MAX repeats reject.
    std::size_t nesting = 16, repeat_iterations = 1000;
};
struct FlowNode {
    std::uint64_t id = 0;
    FlowKind kind = FlowKind::agent;
    std::size_t line = 1, end_line = 1;
    std::string role = "writer", text;
    std::size_t iterations = 3;
    FlowCondition condition = FlowCondition::approved;
    std::vector<FlowNode> children, otherwise;
    bool operator==(const FlowNode&) const = default;
};
struct FlowProgram {
    std::vector<FlowNode> nodes;
    bool operator==(const FlowProgram&) const = default;
};
struct PseudocodeParseResult {
    // Always owns the exact edited bytes, including invalid drafts.
    std::string source;
    std::optional<FlowProgram> program;
    std::vector<PseudocodeDiagnostic> diagnostics;
    explicit operator bool() const { return program.has_value(); }
};

PseudocodeParseResult parse_pseudocode(std::string_view source,
                                      const PseudocodeLimits& limits = {});
// Canonical readable DSL; rejects invalid program structure or exceeded bounds.
std::string write_pseudocode(const FlowProgram& program,
                             const PseudocodeLimits& limits = {});
std::string flow_kind_name(FlowKind kind);
std::string flow_condition_name(FlowCondition condition);
std::vector<std::string> pseudocode_snippets();

struct FlowGraphNode {
    std::uint64_t id = 0;
    FlowKind kind = FlowKind::agent;
    std::size_t line = 1;
    std::string label;
    double x = 0, y = 0, width = 250, height = 64;
};
struct FlowGraphEdge {
    std::uint64_t from = 0, to = 0;
    std::string label;
    bool loop = false;
};
struct FlowGraph {
    std::vector<FlowGraphNode> nodes;
    std::vector<FlowGraphEdge> edges;
    double width = 0, height = 0;
};
FlowGraph make_flow_graph(const FlowProgram& program);

enum class FlowEditKind { insert, update, move, erase };
struct FlowEdit {
    FlowEditKind kind = FlowEditKind::insert;
    std::uint64_t node_id = 0;
    // Parent 0 means the top level. Indices address siblings after removal.
    std::uint64_t parent_id = 0;
    std::size_t index = 0;
    bool otherwise = false;
    FlowNode node;
};

// Caller-serialized, GUI-independent draft model. Raw edits always survive;
// graphical edits are atomic and unavailable until the current text parses.
class PseudocodeDocument {
public:
    explicit PseudocodeDocument(std::string source = {}, PseudocodeLimits limits = {});
    void set_text(std::string source);
    const std::string& text() const { return parsed_.source; }
    const PseudocodeParseResult& parsed() const { return parsed_; }
    std::uint64_t revision() const { return revision_; }
    // revision rejects an action issued against an older graph snapshot.
    bool apply(const FlowEdit& edit, std::uint64_t revision, std::string& error);
    FlowGraph graph() const;
private:
    PseudocodeLimits limits_;
    PseudocodeParseResult parsed_;
    std::uint64_t revision_ = 1;
};

} // namespace tinyenv
