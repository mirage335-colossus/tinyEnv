#include "editor/generate/generate.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>

using namespace foundation::editor;
namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
Project fixture() {
    Project project;
    project.name = "Escapes: \"quoted\" \\ café\nnext";
    Form form;
    form.id = "panel";
    form.label = "Main";
    Control control;
    control.id = "refresh.button";
    control.label = "Refresh \"devices\"";
    control.parent = "panel.group";
    control.binding = "refresh.adapter";
    form.controls.push_back(control); // Deliberately before its parent.
    Control group;
    group.id = "panel.group";
    group.kind = "group";
    group.layout = {0, 0, 640, 480};
    form.controls.push_back(group);
    project.forms.push_back(form);
    Binding handler;
    handler.id = "refresh.adapter";
    handler.file = "user/wrappers.cpp";
    handler.header = "user/wrappers.hpp";
    handler.symbol = "testwrap::refresh";
    project.bindings.push_back(handler);
    project.flows.push_back({"main", "Main flow"});
    Block source;
    source.id = "sample.source";
    source.factory = "testwrap::source";
    source.header = "user/wrappers.hpp";
    source.outputs.push_back({"samples", "float", true});
    source.params.emplace("count", "3");
    project.blocks.push_back(source);
    Block sink;
    sink.id = "sample.sink";
    sink.factory = "testwrap::sink";
    sink.header = "user/wrappers.hpp";
    sink.inputs.push_back({"samples", "float", true});
    project.blocks.push_back(sink);
    project.edges.push_back({"samples.wire", "sample.source", "samples", "sample.sink", "samples", 7, 0});
    return project;
}
const GeneratedFile& file(const GenerationResult& generated, std::string_view ending) {
    for (const auto& file : generated.files) if (std::string_view(file.relative_path).ends_with(ending)) return file;
    throw std::runtime_error("Missing expected generated file");
}
void write_smoke_fixture(const GenerationResult& generated, const std::filesystem::path& root) {
    // Only an explicit test argument creates a fixture; ordinary generation and
    // the default unit test remain entirely free of source-file writes.
    for (const auto& file : generated.files) {
        const auto path = root / file.relative_path;
        std::filesystem::create_directories(path.parent_path());
        std::ofstream stream(path, std::ios::binary);
        if (!(stream << file.content)) throw std::runtime_error("Cannot write smoke fixture");
    }
    std::filesystem::create_directories(root / "user");
    std::ofstream wrapper(root / "user/wrappers.hpp", std::ios::binary);
    wrapper << R"cpp(#pragma once
#include "visual/ui/ui.hpp"
#include "visual/flow/flow.hpp"
#include <map>
#include <string>
namespace testwrap {
template<class Services, class Ui>
void refresh(Services& services, Ui& ui, const gui::Activate&) {
    ++services.events;
    ui.set_enabled("refresh.button", false);
}
template<class Services>
std::unique_ptr<foundation::visual::flow::Block> source(
    Services& services, const std::map<std::string, std::string>& parameters) {
    using namespace foundation::visual::flow;
    return make_block([&services, left=std::stoi(parameters.at("count"))](WorkContext& context, WorkResult& result) mutable {
        auto output = context.output<float>(0);
        std::size_t made=0;
        while (left && made<output.size()) { output[made++]=static_cast<float>(--left); ++services.produced; }
        result.produced[0]=made;
        result.status=left ? WorkStatus::progress : WorkStatus::finished;
    });
}
template<class Services>
std::unique_ptr<foundation::visual::flow::Block> sink(Services& services) {
    using namespace foundation::visual::flow;
    return make_block([&services](WorkContext& context, WorkResult& result) {
        const auto input=context.input<float>(0);
        services.received+=input.size();
        result.consumed[0]=input.size();
        result.status=context.input_finished(0) ? WorkStatus::finished : WorkStatus::progress;
    });
}
}
)cpp";
    if (!wrapper) throw std::runtime_error("Cannot write smoke wrapper");
    std::ofstream smoke(root / "smoke.cpp", std::ios::binary);
    smoke << R"cpp(#include "generated/visual/forms.hpp"
#include "generated/visual/events.hpp"
#include "generated/visual/flows.hpp"
#include <cassert>
struct Services { int events=0; std::size_t produced=0,received=0; };
struct Context { void set_enabled(const char*,bool) {} };
std::size_t verify_typed_registration(foundation::visual::Ui& ui, Services& services) {
    return foundation::generated::bind_handlers(ui,services);
}
int main() {
    Services services;
    Context ui;
    auto form=foundation::generated::snapshot("panel",9);
    assert(form.widgets.size()==2 && form.widgets[0].spec.key.id=="panel.group");
    assert(form.widgets[1].spec.key.generation==9);
    assert(form.title=="Escapes: \"quoted\" \\ café\nnext");
    auto descriptors=foundation::generated::event_bindings();
    assert(descriptors.size()==1);
    assert(foundation::generated::dispatch_handler(ui,services,{{"refresh.button",9},gui::Activate{}}));
    assert(services.events==1);
    auto graph=foundation::generated::make_flow("main",services);
    graph->validate();
    graph->start(foundation::visual::flow::RunMode::cooperative);
    for (int i=0;i<20;++i) graph->step();
    assert(services.produced==3 && services.received==3);
}
)cpp";
    if (!smoke) throw std::runtime_error("Cannot write smoke consumer");
}
} // namespace

int main(int argc, char** argv) {
    try {
        auto project = fixture();
        auto generated = generate(project);
        if (!generated) for (const auto& issue : generated.diagnostics) std::cerr << issue.path << ": " << issue.message << '\n';
        require(bool(generated), "Fixture must generate successfully");
        require(generated.files == generate(project).files, "Generation must be byte-identical");
        require(file(generated, "/design.json").content == semantic_project(project), "Marker must use exact canonical semantic bytes");
        require(generated.files.back().relative_path.ends_with("/design.json"), "Semantic revision marker must publish last");
        require(generated.files.front().content == generated_ownership_content, "Ownership guard must be exact");
        require(file(generated, "/events.hpp").content.find("#include \"user/wrappers.hpp\"") != std::string::npos, "Wrapper declarations must be included");
        require(file(generated, "/events.hpp").content.find("#include \"user/wrappers.cpp\"") == std::string::npos, "Navigation source must never become a C++ include");
        require(file(generated, "/forms.hpp").content.find("caf\\303\\251") != std::string::npos, "Unicode must survive through stable byte escapes");
        require(file(generated, "/events.hpp").content.find("::testwrap::refresh(services, model, input)") != std::string::npos, "Linked event wrapper must appear in compiled calls");
        require(file(generated, "/flows.hpp").content.find("::testwrap::source(services, parameters)") != std::string::npos, "Linked factory must receive services and parameters");

        const auto before = generated.files;
        project.blocks.front().x = 451;
        project.blocks.front().y = 321;
        require(generate(project).files == before, "Authoring positions must not rewrite application output");
        project.forms.front().controls.front().label = "Modified";
        require(generate(project).files != before, "Semantic changes must change output");

        require(generated_identifier("a.b") != generated_identifier("a_b"), "ID encoding must be injective");
        require(valid_cpp_type("std::complex<float>"), "Complex samples must be supported");
        require(valid_cpp_type("std::array<std::uint32_t, 4>"), "Nested value templates must be supported");
        require(valid_cpp_type("unsigned long long"), "Builtin multibyte integer spelling must be supported");
        require(!valid_cpp_type("float; malicious()"), "C++ type injection must fail");
        require(!valid_cpp_type("float*"), "Stream value aliases should express ownership instead of pointer types");
        require(!valid_cpp_type("std::vector<float>\n#include <bad>"), "Preprocessor injection must fail");
        require(!valid_cpp_type("decltype(run())"), "Type expressions belong in ordinary aliases");
        require(!valid_cpp_type("::float") && !valid_cpp_type("::int") &&
                !valid_cpp_type("::unsigned long"), "Builtin types cannot be globally namespace-qualified");

        auto invalid = fixture();
        invalid.bindings.front().symbol = "class";
        require(!generate(invalid), "C++ keywords cannot become adapter symbols");
        invalid = fixture();
        invalid.bindings.front().header = "user/\"bad.hpp";
        require(!generate(invalid), "Quoted include injection must fail");
        invalid = fixture();
        invalid.edges.front().initial_tokens = 1;
        require(!generate(invalid), "Untyped token counts must never silently create stream samples");
        invalid = fixture();
        invalid.blocks.front().outputs.front().type = "float;void bad()";
        require(!generate(invalid), "Arbitrary statements in port types must fail");
        GenerationOptions tiny;
        tiny.output_bytes = 10;
        auto limited = generate(fixture(), tiny);
        require(!limited && limited.files.empty(), "Output limit must produce no partial publication");

        auto forms_only = fixture();
        forms_only.flows.clear(); forms_only.blocks.clear(); forms_only.edges.clear();
        require(generate(forms_only).files.size() == 4, "Forms-only consumers must not receive graph dependencies");
        auto headless = fixture();
        headless.forms.clear(); headless.bindings.clear();
        auto headless_output = generate(headless);
        require(bool(headless_output) && headless_output.files.size() == 3, "Headless graph consumers must not receive GUI dependencies");
        auto implicit_flow = headless;
        implicit_flow.flows.clear();
        require(file(generate(implicit_flow), "/flows.hpp").content.find("flow_id == \"main\"") != std::string::npos,
                "Implicit headless main flow must produce usable wiring");
        auto form_parent = fixture();
        form_parent.forms.front().controls.front().parent = "panel";
        require(bool(generate(form_parent)), "The form itself must be usable as an implicit root parent");
        auto stacking = fixture();
        Control sibling = stacking.forms.front().controls.front();
        sibling.id = "second.button";
        sibling.binding.clear();
        stacking.forms.front().controls.push_back(sibling);
        const auto stacked_output = generate(stacking);
        const auto& stacked_source = file(stacked_output, "/forms.hpp").content;
        require(stacked_source.find("widget.spec.key = {\"refresh.button\"") <
                stacked_source.find("widget.spec.key = {\"second.button\""),
                "Parent reordering must preserve the original sibling stacking order");
        auto text_area = fixture();
        Control notes;
        notes.id = "notes";
        notes.kind = "text";
        notes.multiline = true;
        notes.read_only = true;
        notes.text = "one\ntwo";
        notes.text_limit = 4 * 1024;
        notes.event_bindings.emplace("submit", "submit.adapter");
        text_area.forms.front().controls.push_back(notes);
        Binding submit;
        submit.id = "submit.adapter";
        submit.event = "submit";
        submit.file = "user/wrappers.hpp";
        submit.symbol = "testwrap::submit";
        text_area.bindings.push_back(submit);
        auto text_output = generate(text_area);
        require(bool(text_output), "Multiline text area must produce valid output");
        const auto& text_source = file(text_output, "/forms.hpp").content;
        require(text_source.find("text_policy.multiline = true") != std::string::npos &&
                text_source.find("text_policy.read_only = true") != std::string::npos &&
                text_source.find("text_policy.max_bytes = 4096") != std::string::npos &&
                text_source.find("gui::SubmitKey::control_enter") != std::string::npos,
                "Text area properties and typed submit capability must survive generation");

        auto configured = fixture();
        configured.generated_directory = "retained";
        configured.cpp_namespace = "consumer::generated";
        auto config_output = generate(configured);
        require(config_output.files.front().relative_path.starts_with("retained/"), "Project output configuration must be honored");
        require(file(config_output, "/forms.hpp").content.find("namespace consumer::generated") != std::string::npos, "Project namespace configuration must be honored");

        const auto& header = file(generated, "/forms.hpp");
        require(!may_replace_generated(header, "// user source\n", false), "Unowned user source must not be replaced");
        require(may_replace_generated(header, header.content + "// old output\n", false), "Previously generated C++ is owned");
        require(!may_replace_generated(generated.files.front(), "{}\n", true), "Invalid ownership marker must not be replaced");
        require(!may_replace_generated(generated.files.back(), "{}\n", false), "Unowned JSON must not be replaced");
        require(may_replace_generated(generated.files.back(), "{}\n", true), "Verified owned revision marker can update");

        require(handler_stub(fixture().bindings.front()).find("void refresh(") != std::string::npos, "Handler action must create an ordinary typed wrapper");
        require(block_stub(fixture().blocks.front()).find("WorkStatus::finished") != std::string::npos, "Block skeleton must terminate safely until implemented");
        if (argc == 2) write_smoke_fixture(generated, argv[1]);
        else require(argc == 1, "Expected at most one optional smoke output directory");
        std::cout << "editor generation checks passed\n";
        return 0;
    } catch (const std::exception& exception) {
        std::cerr << "editor generation check failed: " << exception.what() << '\n';
        return 1;
    }
}
