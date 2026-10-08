#include "core/pseudocode.hpp"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace tinyenv;

namespace {
void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}
template<class Function> void rejects(Function function) {
    bool rejected = false;
    try { function(); } catch (const std::invalid_argument&) { rejected = true; }
    require(rejected, "invalid graph serialization must reject");
}
const std::string sample =
    "# Review without shell evaluation\n"
    "repeat 3\n"
    "  agent writer: Improve the answer # preserve this prompt comment.\n"
    "  if rejected\n"
    "    repeat 2\n"
    "      agent research: Resolve remaining doubts.\n"
    "      critique reviewer: Check all new evidence.\n"
    "    until supported\n"
    "  else\n"
    "    critique auditor: Check conclusion support.\n"
    "  end\n"
    "  critique reviewer: Approve only when all doubts are resolved.\n"
    "until approved\n"
    "conclude: Deliver the reviewed answer.\n";

void parsing_and_roundtrip() {
    const auto parsed = parse_pseudocode(sample);
    require(bool(parsed), "nested flow should parse");
    require(parsed.source == sample, "parser must retain exact source");
    const auto& nodes = parsed.program->nodes;
    require(nodes.size() == 2 && nodes[0].kind == FlowKind::repeat, "expected repeat then conclude");
    require(nodes[0].iterations == 3 && nodes[0].line == 2 && nodes[0].end_line == 13,
            "loop limits and source positions");
    const auto& branch = nodes[0].children.at(1);
    require(branch.kind == FlowKind::branch && branch.condition == FlowCondition::rejected,
            "conditional branch must retain condition");
    require(branch.children.at(0).iterations == 2 && branch.otherwise.size() == 1,
            "nested repeat and else body");
    require(nodes[0].children[0].text.find("# preserve") != std::string::npos,
            "inline # belongs to the agent prompt");
    const auto canonical = write_pseudocode(*parsed.program);
    const auto again = parse_pseudocode(canonical);
    require(bool(again), "serialized flow must parse");
    require(write_pseudocode(*again.program) == canonical, "canonical text must be idempotent");
    require(bool(parse_pseudocode("agent test: hello\r\ncritique check: support\r\n")), "CRLF must parse");
    require(bool(parse_pseudocode("\t# no executable statement\n")), "empty drafts are valid editable graphs");
    for (const auto& snippet : pseudocode_snippets()) require(bool(parse_pseudocode(snippet)), "every snippet parses");
}

void diagnostic_drafts_and_bounds() {
    for (const auto& source : {
            "unknown prose\n", "agent writer without colon\n", "agent 5bad: prompt\n",
            "agent writer: \n", "critique writer: \n", "repeat 0\nagent w: x\nuntil approved\n",
            "repeat 1001\nagent w: x\nuntil approved\n", "repeat two\nagent w: x\nuntil approved\n",
            "repeat 2\nuntil approved\n", "repeat 2\nagent w: x\n",
            "repeat 2\nagent w: x\nuntil rejected\n", "if maybe\nend\n",
            "if approved\nagent w: x\n", "else\n", "end\n", "until approved\n", "conclude:\n"}) {
        const auto parsed = parse_pseudocode(source);
        require(!parsed && !parsed.diagnostics.empty(), "invalid flow must produce diagnostics");
        require(parsed.source == source, "invalid edits must never be replaced or dropped");
        require(parsed.diagnostics[0].line > 0 && parsed.diagnostics[0].column > 0,
                "diagnostics must have source positions");
    }
    std::string nul = "agent w: safe";
    nul.push_back('\0'); nul += "unsafe\n";
    require(!parse_pseudocode(nul), "NUL bytes rejected");
    require(!parse_pseudocode("agent w: \xc0\x80\n"), "overlong UTF-8 rejected");
    require(!parse_pseudocode("agent w: \xc2\x85\n"), "Unicode control characters rejected");
    require(bool(parse_pseudocode("agent w: \xe2\x9c\x93\n")), "Unicode prompts remain supported");
    require(!parse_pseudocode("agent w: first\rsecond\n"), "embedded carriage return rejected");
    PseudocodeLimits limits;
    limits.source_bytes = 4;
    require(!parse_pseudocode("agent w: x\n", limits), "byte limit applies before parsing");
    limits = {}; limits.lines = 1;
    require(!parse_pseudocode("agent w: x\nagent w: y\n", limits), "line limit");
    limits = {}; limits.nodes = 1;
    require(!parse_pseudocode("agent w: x\nagent w: y\n", limits), "node limit");
    limits = {}; limits.nesting = 1;
    require(!parse_pseudocode("if approved\nif approved\nagent w: x\nend\nend\n", limits), "nesting limit");
    limits = {}; limits.nesting = 65;
    require(!parse_pseudocode("agent w: x\n", limits), "unsafe configurable nesting ceiling rejected");
    auto program = *parse_pseudocode("agent writer: answer\n").program;
    program.nodes[0].text = "injected\nagent evil: second";
    rejects([&] { write_pseudocode(program); });
    program.nodes[0].text = "safe"; program.nodes[0].role = "bad role";
    rejects([&] { write_pseudocode(program); });
    program.nodes[0].role = "writer"; program.nodes[0].children.push_back(FlowNode{});
    rejects([&] { write_pseudocode(program); });
    const std::string indented = "if approved\n  agent w: x\nend\n";
    const auto nested = *parse_pseudocode(indented).program;
    limits = {}; limits.source_bytes = indented.size(); limits.lines = 3;
    require(write_pseudocode(nested, limits) == indented, "serializer accepts exact indentation/newline byte boundary");
    --limits.source_bytes;
    rejects([&] { write_pseudocode(nested, limits); });
    limits.source_bytes = indented.size(); limits.lines = 2;
    rejects([&] { write_pseudocode(nested, limits); });
}

void graph_contract() {
    const auto program = *parse_pseudocode(
        "repeat 2\nif rejected\nagent writer: retry\nelse\nagent writer: revise\nend\n"
        "critique reviewer: check\nuntil approved\nconclude: reviewed\n").program;
    const auto graph = make_flow_graph(program);
    require(graph.nodes.size() == 6, "graph includes each semantic node exactly once");
    const auto has_edge = [&](std::uint64_t from, std::uint64_t to, const std::string& label, bool loop = false) {
        return std::any_of(graph.edges.begin(), graph.edges.end(), [&](const auto& edge) {
            return edge.from == from && edge.to == to && edge.label == label && edge.loop == loop;
        });
    };
    require(has_edge(1, 2, "iterate") && has_edge(2, 3, "yes") && has_edge(2, 4, "no"),
            "graph exposes nested branch control flow");
    require(has_edge(3, 5, "") && has_edge(4, 5, "") && has_edge(5, 1, "retry", true),
            "both branches join critique then retry loop");
    require(has_edge(1, 6, "until approved"), "only condition-approved loop exit points at conclusion");
    require(graph.nodes[2].x > graph.nodes[1].x && graph.nodes[1].x > graph.nodes[0].x,
            "layout exposes nesting depth");
    require(graph.width > 0 && graph.height > 0, "graph reports scroll extents");
}

void transactional_graph_edits() {
    PseudocodeDocument document("agent writer: first\nagent writer: second\n");
    const auto first_revision = document.revision();
    FlowEdit edit;
    edit.kind = FlowEditKind::insert; edit.index = 1;
    edit.node.kind = FlowKind::critique; edit.node.role = "reviewer"; edit.node.text = "Check support.";
    std::string error;
    require(document.apply(edit, first_revision, error), "insert node between agents");
    require(document.text() == "agent writer: first\ncritique reviewer: Check support.\nagent writer: second\n",
            "graph insertion regenerates readable ordered text");
    const auto saved = document.text();
    require(!document.apply(edit, first_revision, error) && document.text() == saved,
            "stale graph action must fail atomically");
    edit.kind = FlowEditKind::move; edit.node_id = 3; edit.index = 0;
    require(document.apply(edit, document.revision(), error), "move final agent before first");
    require(document.text().starts_with("agent writer: second\n"), "move action changes control order");
    edit.kind = FlowEditKind::update; edit.node_id = 1; edit.node.kind = FlowKind::agent;
    edit.node.role = "writer"; edit.node.text = "updated";
    require(document.apply(edit, document.revision(), error), "edit node prompt");
    require(document.text().starts_with("agent writer: updated\n"), "prompt update serialized");
    edit.node.text = "malformed\ncommand";
    const auto valid_saved = document.text();
    require(!document.apply(edit, document.revision(), error) && document.text() == valid_saved,
            "invalid graph replacement leaves exact valid source unchanged");
    document.set_text("unfinished manually typed text\n");
    require(document.text() == "unfinished manually typed text\n" && !document.parsed(),
            "invalid raw editor text is retained");
    require(document.graph().nodes.empty(), "invalid text disables graphical projection");
    require(!document.apply(edit, document.revision(), error), "graph mutations unavailable on invalid drafts");

    document.set_text("repeat 2\nagent writer: answer\nuntil approved\nif supported\nend\n");
    edit = {}; edit.kind = FlowEditKind::move; edit.node_id = 1; edit.parent_id = 2;
    require(!document.apply(edit, document.revision(), error), "moving parent under descendant rejected");
    edit.kind = FlowEditKind::erase; edit.node_id = 2;
    const auto nested_saved = document.text();
    require(!document.apply(edit, document.revision(), error) && document.text() == nested_saved,
            "erasing sole repeat body cannot create invalid loop");
    edit.kind = FlowEditKind::insert; edit.parent_id = 3; edit.otherwise = true; edit.index = 0;
    edit.node.kind = FlowKind::agent; edit.node.role = "fallback"; edit.node.text = "Resolve gaps.";
    require(document.apply(edit, document.revision(), error), "insert into else branch");
    require(document.text().find("else\n  agent fallback: Resolve gaps.\nend") != std::string::npos,
            "else branch insertion serializes its block");
}
} // namespace

int main() {
    try {
        parsing_and_roundtrip();
        diagnostic_drafts_and_bounds();
        graph_contract();
        transactional_graph_edits();
        std::cout << "pseudocode parser, graph and transactional editor: 4 cases passed\n";
        return 0;
    } catch (const std::exception& failure) {
        std::cerr << failure.what() << '\n';
        return 1;
    }
}
