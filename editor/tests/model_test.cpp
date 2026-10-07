#include "model/project.hpp"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace foundation::editor;
namespace {
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
bool mentions(const std::vector<Diagnostic>& diagnostics, const std::string& part) {
    return std::any_of(diagnostics.begin(), diagnostics.end(), [&](const auto& item) { return item.message.find(part) != std::string::npos; });
}
void parsing() {
    auto demo = demo_project(); demo.name = "Receiver — 日本語 😀";
    demo.forms.front().controls.back().text = "line one\r\nline two\t\"quoted\"\\end";
    require(!has_errors(validate(demo)), "demo must validate");
    const auto bytes = write_project(demo); const auto parsed = parse_project(bytes);
    require(parsed.project && *parsed.project == demo, "Unicode/project round trip changed source bytes");
    require(write_project(*parsed.project) == bytes, "writer is nondeterministic");
    auto moved = demo; moved.blocks[0].x += 14; moved.blocks[1].y -= 25;
    require(write_project(moved) != bytes && semantic_project(moved) == semantic_project(demo), "view movement changed generation input");
    const auto escaped = parse_project(R"({"schema_version":1,"name":"\uD83D\uDE00"})");
    require(escaped.project && escaped.project->name == "😀", "surrogate pair decoding failed");
    for (const auto& invalid : {R"({"schema_version":1,"name":"\uD800"})", R"({"schema_version":1,"name":"\uDE00"})", R"({"schema_version":1,"name":"\u0000"})", R"({"schema_version":1,"name":"\q"})", R"({"schema_version":1,"schema_version":1})", R"({"schema_version":1,"unknown":true})", R"({"schema_version":2})", R"({"schema_version":1,"forms":{}})", R"({"schema_version":1,"blocks":[{"id":"block","x":1e999}]})", R"({"schema_version":01})", R"({"schema_version":1} trailing)"}) {
        const auto result = parse_project(invalid);
        require(!result.project && has_errors(result.diagnostics), "malformed/unsupported JSON accepted");
    }
    auto invalid_utf8 = std::string("{\"schema_version\":1,\"name\":\""); invalid_utf8 += char(0xc0); invalid_utf8 += char(0xaf); invalid_utf8 += "\"}";
    require(!parse_project(invalid_utf8).project, "overlong UTF-8 accepted");
    const auto misplaced = parse_project("{\n \"schema_version\": 1,\n \"name\": }");
    require(!misplaced.project && misplaced.diagnostics[0].line == 3 && misplaced.diagnostics[0].column > 1, "parse location missing");
    Limits tiny; tiny.file_bytes = 10;
    require(!parse_project(bytes, tiny).project, "file byte bound ignored");
    tiny = {}; tiny.string_bytes = 2;
    require(!parse_project(R"({"schema_version":1})", tiny).project, "key string byte bound ignored");
    tiny = {}; tiny.json_values = 2;
    require(!parse_project(R"({"schema_version":1,"name":"test"})", tiny).project, "value count bound ignored");
    tiny = {}; tiny.nesting = 2;
    require(!parse_project(R"({"schema_version":1,"forms":[{"controls":[{}]}]})", tiny).project, "nesting bound ignored");
    tiny = {}; tiny.controls = 2;
    require(!parse_project(bytes, tiny).project, "control count bound ignored");
}
void paths_and_ids() {
    for (const std::string value : {"../secret", "/tmp/file", "src/../../file", "src//file", "src/./file", "C:/file", "src\\file", "src/"}) require(!safe_relative_path(value), "unsafe project path accepted");
    require(safe_relative_path("src/日本語.cpp") && safe_relative_path(".", true), "valid project path rejected");
    require(safe_id("widget.id-1") && !safe_id("1widget") && !safe_id("widget id"), "stable ID grammar broken");
    require(valid_cpp_symbol("::example::on_start") && !valid_cpp_symbol("example::") && !valid_cpp_symbol("on_start(); injected()"), "C++ symbol grammar broken");
    auto project = demo_project(); project.bindings[0].file = "../outside.cpp";
    require(has_errors(validate(project)), "unsafe binding path passed validation");
    bool threw = false; try { (void)write_project(project); } catch (const std::invalid_argument&) { threw = true; }
    require(threw, "writer persisted unsafe path");
    project = demo_project(); project.forms[0].controls[0].id = project.blocks[0].id;
    require(mentions(validate(project), "duplicate project"), "global ID collision not diagnosed");
    project = demo_project(); project.forms[0].controls[0].options[1].id = project.forms[0].controls[0].options[0].id;
    require(mentions(validate(project), "duplicate option"), "option ID collision not diagnosed");
}
void composition() {
    auto project = demo_project();
    project.edges[0].from_port = "missing";
    const auto broken = validate(project);
    require(has_errors(broken) && mentions(broken, "unknown output"), "missing edge port not diagnosed");
    auto draft = parse_project(write_project(project));
    require(draft.project && has_errors(draft.diagnostics), "safe incomplete draft was not retained for repair");
    project = demo_project(); project.blocks[1].inputs[0].type = "std::complex<float>";
    require(mentions(validate(project), "stream type mismatch"), "stream type mismatch not diagnosed");
    project = demo_project(); project.edges.push_back({"duplicate_input", "source", "out", "gain", "in", 8, 0});
    require(mentions(validate(project), "already has a producer"), "multiple input producers accepted");
    project = demo_project(); project.forms[0].controls[1].binding = "absent";
    require(mentions(validate(project), "unknown binding"), "unknown event binding accepted");
    project = demo_project(); project.forms[0].controls[3].multiline = false; project.forms[0].controls[3].text = "one\ntwo";
    require(mentions(validate(project), "single-line text"), "single-line text policy ignored");
    project = demo_project(); project.forms[0].controls[3].multiline = false; project.forms[0].controls[3].options = {{"suggestion", "Suggestion", "one\ntwo", true}};
    require(mentions(validate(project), "suggested text"), "text suggestion policy ignored");
    project = demo_project(); project.forms[0].controls[1].options = {{"option", "Option", "value", true}};
    require(mentions(validate(project), "options are supported only"), "options accepted on a button");
    project = demo_project(); project.flows.push_back({"other", "Other flow"}); project.blocks[1].flow = "other";
    require(mentions(validate(project), "different flow"), "cross-flow connection accepted");
    project = demo_project(); project.edges.clear();
    require(has_errors(validate(project)) && mentions(validate(project), "required input"), "unconnected required ports must prevent generation");
    project = demo_project(); project.blocks[0].inputs = {{"feedback", "float", true}}; project.blocks[2].outputs = {{"feedback", "float", true}};
    project.edges.push_back({"feedback", "sink", "feedback", "source", "feedback", 8, 0});
    require(mentions(validate(project), "feedback cycle"), "zero-state cycle accepted");
    project.blocks[2].breaks_cycle = true;
    require(!has_errors(validate(project)), "explicit stateful cycle breaker rejected");
    project.edges.back().initial_tokens = 1;
    require(mentions(validate(project), "lack typed values"), "untyped numeric initial tokens accepted");
    project = empty_project(); Form form; form.id = "form";
    Control a; a.id = "a"; a.kind = "group"; a.parent = "b";
    Control b; b.id = "b"; b.kind = "group"; b.parent = "a";
    form.controls = {a, b}; project.forms.push_back(form);
    require(mentions(validate(project), "parent cycle"), "control parent cycle accepted");
    project = demo_project();
    // A 4-output/2-input block proves the model is not fixed to one input/output
    // and preserves independently named typed streams. Splits are explicit.
    Block split; split.id = "split"; split.factory = "example::make_split";
    split.inputs = {{"one", "float", true}, {"two", "float", true}};
    for (int i = 0; i < 4; ++i) split.outputs.push_back({"out" + std::to_string(i), "float", false});
    project.blocks.push_back(split);
    project.blocks[0].outputs.push_back({"branch_one", "float", true});
    project.blocks[0].outputs.push_back({"branch_two", "float", true});
    project.edges.push_back({"source_split_one", "source", "branch_one", "split", "one", 7, 0});
    project.edges.push_back({"source_split_two", "source", "branch_two", "split", "two", 9, 0});
    require(!has_errors(validate(project)), "arbitrary MIMO design rejected");
    require(parse_project(write_project(project)).project->blocks.back().outputs.size() == 4, "MIMO ports lost during save");
    project.edges.back().from_port = "branch_one";
    require(mentions(validate(project), "already has a consumer"), "implicit broadcast connection accepted");
}
void history() {
    auto project = demo_project(); History history; history.reset(project);
    const auto initial = project; project.name = "changed"; require(history.commit(project), "edit not committed");
    project.forms[0].controls[0].label = "Changed label"; history.commit(project);
    require(history.can_undo() && !history.can_redo(), "history availability wrong");
    auto undo = history.undo(); require(undo && undo->name == "changed" && undo->forms[0].controls[0].label == initial.forms[0].controls[0].label, "first undo wrong");
    undo = history.undo(); require(undo && *undo == initial, "second undo wrong");
    require(!history.undo(), "undo passed oldest snapshot");
    auto redo = history.redo(); require(redo && redo->name == "changed", "redo wrong");
    auto branch = *redo; branch.name = "branch"; history.commit(branch); require(!history.can_redo(), "branched history retained redo");
    const auto bytes = write_project(initial).size(); History bounded(bytes * 2 + 100, 2); bounded.reset(initial);
    auto p = initial; p.name = "p1"; bounded.commit(p); p.name = "p2"; bounded.commit(p);
    require(bounded.bytes() <= bytes * 2 + 100, "history byte bound ignored");
    require(bounded.undo().has_value() && !bounded.undo(), "history entry pruning wrong");
    History oversized(bytes, 2); oversized.reset(initial); auto bigger = initial; bigger.name += std::string(bytes, 'x');
    require(!oversized.commit(bigger) && oversized.bytes() == bytes, "oversized edit damaged history");
}
}
int main() {
    try { parsing(); paths_and_ids(); composition(); history(); std::cout << "editor model tests passed\n"; return 0; }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
