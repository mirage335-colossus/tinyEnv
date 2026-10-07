#include "editor/generate/generate.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <utility>

namespace foundation::editor {
namespace {

struct EventDescription { std::string_view name, input, kind; };
constexpr std::array events{
    EventDescription{"activate", "gui::Activate", "activate"},
    EventDescription{"checked", "gui::SetChecked", "checked"},
    EventDescription{"text_changed", "gui::EditText", "text_changed"},
    EventDescription{"choose", "gui::ChooseOption", "choose"},
    EventDescription{"select_record", "gui::SelectRecord", "select_record"},
    EventDescription{"activate_record", "gui::ActivateRecord", "activate_record"},
    EventDescription{"submit", "gui::SubmitText", "submit"},
    EventDescription{"action", "gui::InvokeAction", "action"},
    EventDescription{"pointer", "gui::PointerInput", "pointer"}
};
const EventDescription* event_description(std::string_view name) {
    // The model's named UI events have these stable spellings. Historical
    // shorthand aliases are accepted without changing the emitted contract.
    name = canonical_event_name(name);
    for (const auto& event : events) if (event.name == name) return &event;
    return nullptr;
}
bool ascii_alpha(char value) {
    return (value >= 'a' && value <= 'z') || (value >= 'A' && value <= 'Z');
}
bool ascii_digit(char value) { return value >= '0' && value <= '9'; }
bool identifier_start(char value) { return ascii_alpha(value) || value == '_'; }
bool identifier_continue(char value) { return identifier_start(value) || ascii_digit(value); }
bool cpp_keyword(std::string_view word) {
    constexpr std::string_view words =
        " alignas alignof and and_eq asm atomic_cancel atomic_commit atomic_noexcept auto "
        " bitand bitor break case catch char char8_t char16_t char32_t class compl concept const "
        " consteval constexpr constinit const_cast continue co_await co_return co_yield decltype "
        " default delete do double dynamic_cast else enum explicit export extern false float for "
        " friend goto if inline int long mutable namespace new noexcept not not_eq nullptr operator "
        " or or_eq private protected public reflexpr register reinterpret_cast requires return short "
        " signed sizeof static static_assert static_cast struct switch synchronized template this "
        " thread_local throw true try typedef typeid typename union unsigned using virtual void "
        " volatile wchar_t while xor xor_eq bool ";
    const auto needle = " " + std::string(word) + " ";
    return words.find(needle) != std::string_view::npos;
}
bool safe_symbol(std::string_view symbol) {
    if (symbol.starts_with("::")) symbol.remove_prefix(2);
    if (symbol.empty()) return false;
    while (!symbol.empty()) {
        const auto end = symbol.find("::");
        const auto component = symbol.substr(0, end);
        if (component.empty() || !identifier_start(component.front()) || cpp_keyword(component)) return false;
        for (char ch : component) if (!identifier_continue(ch)) return false;
        if (end == std::string_view::npos) return true;
        symbol.remove_prefix(end + 2);
        if (symbol.empty()) return false;
    }
    return false;
}
std::string qualified(std::string_view value) {
    return value.starts_with("::") ? std::string(value) : "::" + std::string(value);
}
std::string quoted(std::string_view value) {
    std::string result = "\"";
    for (const unsigned char byte : value) {
        switch (byte) {
            case '"': result += "\\\""; break;
            case '\\': result += "\\\\"; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                // Fixed-width octal cannot absorb following ASCII hex digits.
                // UTF-8 is emitted byte-for-byte and remains independent of a
                // compiler's source execution-character-set configuration.
                if (byte < 32 || byte >= 127) {
                    result += '\\';
                    result += static_cast<char>('0' + (byte >> 6));
                    result += static_cast<char>('0' + ((byte >> 3) & 7));
                    result += static_cast<char>('0' + (byte & 7));
                } else result += static_cast<char>(byte);
        }
    }
    result += '"';
    return result;
}
std::string boolean(bool value) { return value ? "true" : "false"; }
std::string number(double value) {
    if (value == 0) return "0"; // Canonicalize negative zero.
    std::array<char, 96> buffer{};
    const auto result = std::to_chars(buffer.data(), buffer.data() + buffer.size(),
                                      value, std::chars_format::general,
                                      std::numeric_limits<double>::max_digits10);
    if (result.ec != std::errc{}) throw std::invalid_argument("Cannot format layout number");
    return std::string(buffer.data(), result.ptr);
}
bool header_extension(std::string_view file) {
    return file.ends_with(".hpp") || file.ends_with(".h") || file.ends_with(".hh") ||
           file.ends_with(".hxx") || file.ends_with(".inc") || file.ends_with(".inl");
}
bool include_path(std::string_view value) {
    if (!safe_relative_path(value)) return false;
    for (const unsigned char ch : value)
        if (ch < 32 || ch == 127 || ch == '"' || ch == '\\' || ch == '<' || ch == '>') return false;
    return true;
}
std::string binding_header(const Binding& binding) {
    return !binding.header.empty() ? binding.header :
           (header_extension(binding.file) ? binding.file : std::string{});
}
std::string prologue(std::string_view includes, std::string_view ns) {
    return "// Generated from the semantic design; edit ordinary source files for behavior.\n"
           "// No editor executable or design document is needed by this header at runtime.\n"
           "#pragma once\n\n" + std::string(includes) + "\nnamespace " + std::string(ns) + " {\n\n";
}
std::string epilogue(std::string_view ns) { return "\n} // namespace " + std::string(ns) + "\n"; }

struct BoundEvent {
    const Control* control;
    const Binding* binding;
    const EventDescription* event;
};
struct BoundFactory {
    const Block* block;
    std::string symbol, header;
};
void error(std::vector<Diagnostic>& diagnostics, std::string path, std::string message) {
    diagnostics.push_back({Severity::error, std::move(path), std::move(message), 0, 0});
}
void warning(std::vector<Diagnostic>& diagnostics, std::string path, std::string message) {
    diagnostics.push_back({Severity::warning, std::move(path), std::move(message), 0, 0});
}

// Intentionally a type-token recognizer, not a C++ parser. Arbitrary user types
// use a named alias in an ordinary header. No expression, pointer, statement,
// macro directive or code string from a design can enter generated source.
class TypeParser {
public:
    explicit TypeParser(std::string_view input) : input_(input) {}
    bool parse() { return type(0) && (space(), position_ == input_.size()); }
private:
    std::string_view input_;
    std::size_t position_ = 0;
    void space() { while (position_ < input_.size() && input_[position_] == ' ') ++position_; }
    bool consume(std::string_view text) {
        space();
        if (!input_.substr(position_).starts_with(text)) return false;
        position_ += text.size();
        return true;
    }
    std::string_view identifier() {
        space();
        const auto start = position_;
        if (position_ == input_.size() || !identifier_start(input_[position_])) return {};
        while (position_ < input_.size() && identifier_continue(input_[position_])) ++position_;
        return input_.substr(start, position_ - start);
    }
    bool type(std::size_t depth) {
        if (depth >= 16) return false;
        const bool global = consume("::");
        const auto word = identifier();
        if (word.empty()) return false;
        if (cpp_keyword(word)) {
            if (global) return false; // Builtin types are not namespace members.
            if (word == "bool" || word == "char" || word == "char8_t" || word == "char16_t" ||
                word == "char32_t" || word == "wchar_t" || word == "float" || word == "double" || word == "int")
                return true;
            if (word != "signed" && word != "unsigned" && word != "short" && word != "long") return false;
            // Only the ordinary builtin integer type sequences are accepted.
            std::string phrase(word);
            while (true) {
                const auto before = position_;
                const auto next = identifier();
                if (next != "int" && next != "long" && next != "short" && next != "char" && next != "double") {
                    position_ = before;
                    break;
                }
                phrase += ' ';
                phrase += next;
            }
            constexpr std::array<std::string_view, 25> builtin{
                "signed", "unsigned", "short", "long", "signed int", "unsigned int", "short int", "long int",
                "signed char", "unsigned char", "signed short", "unsigned short", "signed long", "unsigned long",
                "signed short int", "unsigned short int", "signed long int", "unsigned long int", "long long",
                "long long int", "signed long long", "unsigned long long", "signed long long int",
                "unsigned long long int", "long double"};
            return std::find(builtin.begin(), builtin.end(), phrase) != builtin.end();
        }
        while (consume("::")) {
            const auto next = identifier();
            if (next.empty() || cpp_keyword(next)) return false;
        }
        if (!consume("<")) return true;
        if (!argument(depth + 1)) return false;
        while (consume(",")) if (!argument(depth + 1)) return false;
        return consume(">");
    }
    bool argument(std::size_t depth) {
        space();
        if (position_ < input_.size() && ascii_digit(input_[position_])) {
            while (position_ < input_.size() && ascii_digit(input_[position_])) ++position_;
            return true;
        }
        return type(depth);
    }
};

std::string forms_source(const Project& project, std::string_view ns) {
    auto out = prologue("#include <gui/contract.hpp>\n#include <algorithm>\n#include <cstdint>\n#include <stdexcept>\n#include <string_view>\n", ns);
    out += "namespace ids {\n";
    auto id = [&](std::string_view value) { out += "inline constexpr std::string_view " + generated_identifier(value) + " = " + quoted(value) + ";\n"; };
    for (const auto& form : project.forms) { id(form.id); for (const auto& control : form.controls) id(control.id); }
    for (const auto& binding : project.bindings) id(binding.id);
    for (const auto& flow : project.flows) id(flow.id);
    for (const auto& block : project.blocks) id(block.id);
    for (const auto& edge : project.edges) id(edge.id);
    out += "} // namespace ids\n\nnamespace form_detail {\n";
    for (const auto& form : project.forms) {
        out += "inline void append_" + generated_identifier(form.id) + "(gui::Snapshot& view, std::uint64_t generation) {\n";
        out += "    view.pages.push_back({" + quoted(form.id) + ", " + quoted(form.label) + "});\n";
        // Parent declaration order can be edited externally; emit a stable
        // topological order without changing sibling stacking order.
        std::map<std::string, std::size_t> indices;
        for (std::size_t i = 0; i < form.controls.size(); ++i) indices.emplace(form.controls[i].id, i);
        std::vector<std::vector<std::size_t>> children(form.controls.size());
        std::set<std::size_t> ready;
        for (std::size_t i = 0; i < form.controls.size(); ++i) {
            const auto& parent = form.controls[i].parent;
            if (parent.empty() || parent == form.id) ready.insert(i);
            else children.at(indices.at(parent)).push_back(i);
        }
        std::vector<const Control*> ordered;
        while (!ready.empty()) {
            const auto index = *ready.begin();
            ready.erase(ready.begin());
            ordered.push_back(&form.controls[index]);
            ready.insert(children[index].begin(), children[index].end());
        }
        if (ordered.size() != form.controls.size()) throw std::invalid_argument("Invalid form parent hierarchy");
        for (const auto* ptr : ordered) {
            const auto& control = *ptr;
            const auto has_event = [&](std::string_view name) {
                for (const auto& [event, adapter] : control.event_bindings) {
                    (void)adapter;
                    if (const auto* description = event_description(event); description && description->name == name) return true;
                }
                for (const auto& binding : project.bindings)
                    if (binding.id == control.binding)
                        if (const auto* description = event_description(binding.event); description && description->name == name) return true;
                return false;
            };
            out += "    { // design widget " + control.id + "\n        gui::Widget widget;\n";
            out += "        widget.spec.key = {" + quoted(control.id) + ", generation};\n";
            out += "        widget.spec.kind = gui::Kind::" + control.kind + ";\n";
            out += "        widget.spec.page = " + quoted(form.id) + ";\n";
            out += "        widget.spec.parent = " + quoted(control.parent == form.id ? std::string{} : control.parent) + ";\n";
            out += "        widget.spec.binding = " + quoted(control.binding) + ";\n";
            if (control.kind == "text") {
                out += "        widget.spec.text_policy.multiline = " + boolean(control.multiline) + ";\n";
                out += "        widget.spec.text_policy.read_only = " + boolean(control.read_only) + ";\n";
                out += "        widget.spec.text_policy.max_bytes = " + std::to_string(control.text_limit) + ";\n";
                if (has_event("submit"))
                    out += "        widget.spec.text_policy.submit = gui::SubmitKey::" + std::string(control.multiline ? "control_enter" : "enter") + ";\n";
                if (control.multiline) out += "        widget.state.wrap = gui::TextWrap::word;\n";
            }
            if (has_event("pointer")) out += "        widget.spec.pointer_input = true;\n";
            out += "        widget.state.bounds = {" + number(control.layout.x) + ", " + number(control.layout.y) + ", " + number(control.layout.width) + ", " + number(control.layout.height) + "};\n";
            out += "        widget.state.label = " + quoted(control.label) + ";\n";
            out += "        widget.state.text = " + quoted(control.text) + ";\n";
            out += "        widget.state.enabled = " + boolean(control.enabled) + ";\n";
            out += "        widget.state.visible = " + boolean(control.visible) + ";\n";
            out += "        widget.state.checked = " + boolean(control.checked) + ";\n";
            for (const auto& option : control.options)
                out += "        widget.state.options.push_back({" + quoted(option.id) + ", " + quoted(option.label) + ", " + quoted(option.value) + ", " + boolean(option.enabled) + "});\n";
            out += "        view.widgets.push_back(std::move(widget));\n    }\n";
        }
        out += "}\n\n";
    }
    out += "} // namespace form_detail\n\n";
    out += "inline gui::Snapshot snapshot(std::string_view form_id, std::uint64_t generation = 1) {\n"
           "    if (generation == 0) throw std::invalid_argument(\"Widget generation must be nonzero\");\n"
           "    gui::Snapshot view;\n    view.revision = 1;\n    view.title = " + quoted(project.name) + ";\n";
    for (const auto& form : project.forms) {
        out += "    if (form_id == " + quoted(form.id) + ") {\n        view.client_size = {" + number(form.width) + ", " + number(form.height) + "};\n";
        out += "        view.active_page = " + quoted(form.id) + ";\n        form_detail::append_" + generated_identifier(form.id) + "(view, generation);\n        return view;\n    }\n";
    }
    out += "    throw std::invalid_argument(\"Unknown generated form ID\");\n}\n\n";
    out += "inline gui::Snapshot all_forms_snapshot(std::uint64_t generation = 1) {\n"
           "    if (generation == 0) throw std::invalid_argument(\"Widget generation must be nonzero\");\n"
           "    gui::Snapshot view;\n    view.revision = 1;\n    view.title = " + quoted(project.name) + ";\n";
    if (!project.forms.empty()) {
        double width = 0, height = 0;
        for (const auto& form : project.forms) { width = std::max(width, form.width); height = std::max(height, form.height); }
        out += "    view.client_size = {" + number(width) + ", " + number(height) + "};\n    view.active_page = " + quoted(project.forms.front().id) + ";\n";
        for (const auto& form : project.forms) out += "    form_detail::append_" + generated_identifier(form.id) + "(view, generation);\n";
    }
    out += "    return view;\n}\n";
    return out + epilogue(ns);
}

std::string event_source(const std::vector<BoundEvent>& bindings, std::string_view ns) {
    std::set<std::string> headers;
    for (const auto& item : bindings) if (auto header = binding_header(*item.binding); !header.empty()) headers.insert(std::move(header));
    std::string includes = "#include \"visual/ui/ui.hpp\"\n#include <cstddef>\n#include <vector>\n";
    for (const auto& header : headers) includes += "#include \"" + header + "\"\n";
    auto out = prologue(includes, ns);
    out += "inline std::vector<foundation::visual::EventBinding> event_bindings() {\n    return {\n";
    for (const auto& item : bindings)
        out += "        {" + quoted(item.control->id) + ", foundation::visual::EventKind::" + std::string(item.event->kind) + ", " + quoted(item.binding->id) + "},\n";
    out += "    };\n}\n\n";
    out += "// Services must outlive Ui and its callbacks. An explicit typed wrapper\n"
           "// can call any linked C++ implementation or a project-owned Rust C ABI.\n"
           "template<class Services>\nstd::size_t bind_handlers(foundation::visual::Ui& ui, Services& services) {\n"
           "    std::size_t registered = 0;\n";
    if (bindings.empty()) out += "    (void)ui; (void)services;\n";
    for (const auto& item : bindings) {
        out += "    // design adapter " + item.binding->id + "\n";
        out += "    registered += ui.bind<" + std::string(item.event->input) + ">(" + quoted(item.control->id) + ",\n";
        out += "        [&services](foundation::visual::Ui& model, const " + std::string(item.event->input) + "& input) {\n";
        out += "            " + qualified(item.binding->symbol) + "(services, model, input);\n        });\n";
    }
    out += "    return registered;\n}\n";
    out += "\n// The caller must first validate generation, visibility, enabled state and\n"
           "// the event's ownership. This helper also supports self-hosted UIs\n"
           "// whose model is application-owned rather than visual::Ui.\n"
           "template<class UiContext, class Services>\n"
           "bool dispatch_handler(UiContext& ui, Services& services, const gui::WidgetEvent& event) {\n";
    if (bindings.empty()) out += "    (void)ui; (void)services; (void)event;\n";
    for (const auto& item : bindings) {
        out += "    if (event.target.id == " + quoted(item.control->id) + ") {\n";
        out += "        if (const auto* input = std::get_if<" + std::string(item.event->input) + ">(&event.input)) {\n";
        out += "            " + qualified(item.binding->symbol) + "(services, ui, *input);\n            return true;\n        }\n    }\n";
    }
    out += "    return false;\n}\n";
    return out + epilogue(ns);
}

std::size_t port_index(const std::vector<Port>& ports, std::string_view id) {
    for (std::size_t i = 0; i < ports.size(); ++i) if (ports[i].id == id) return i;
    throw std::invalid_argument("Missing graph port");
}
std::string flow_source(const Project& project, const std::vector<BoundFactory>& factories, std::string_view ns) {
    std::set<std::string> headers;
    for (const auto& factory : factories) if (!factory.header.empty()) headers.insert(factory.header);
    std::string includes = "#include \"visual/flow/flow.hpp\"\n#include <array>\n#include <complex>\n#include <cstdint>\n#include <map>\n#include <memory>\n#include <stdexcept>\n#include <string>\n#include <string_view>\n#include <vector>\n";
    for (const auto& header : headers) includes += "#include \"" + header + "\"\n";
    auto out = prologue(includes, ns);
    out += "// The returned graph owns blocks and queues. Services must outlive it,\n"
           "// including shutdown/join. Construction does not start project work.\n";
    for (const auto& flow : project.flows) {
        out += "template<class Services>\nstd::unique_ptr<foundation::visual::flow::Graph> make_flow_" + generated_identifier(flow.id) + "(Services& services, foundation::visual::flow::GraphOptions options = {}) {\n";
        out += "    using namespace foundation::visual::flow;\n    auto graph = std::make_unique<Graph>(options);\n";
        bool uses_services = false;
        for (const auto& factory : factories) {
            const auto& block = *factory.block;
            if (block.flow != flow.id) continue;
            uses_services = true;
            const auto name = generated_identifier(block.id);
            out += "    // design block " + block.id + "\n    BlockSpec spec_" + name + ";\n    spec_" + name + ".id = " + quoted(block.id) + ";\n";
            auto emit_ports = [&](const std::vector<Port>& ports, std::string_view direction) {
                for (const auto& port : ports)
                    out += "    spec_" + name + "." + std::string(direction) + ".push_back(PortSpec::typed<" + port.type + ">(" + quoted(port.id) + ", 1, " + boolean(!port.required) + "));\n";
            };
            emit_ports(block.inputs, "inputs"); emit_ports(block.outputs, "outputs");
            out += "    spec_" + name + ".breaks_cycle = " + boolean(block.breaks_cycle) + ";\n";
            out += "    spec_" + name + ".factory = [&services, parameters = std::map<std::string, std::string>{";
            bool first = true;
            for (const auto& [key, value] : block.params) {
                if (!first) out += ", ";
                first = false;
                out += "{" + quoted(key) + ", " + quoted(value) + "}";
            }
            out += "}]() -> std::unique_ptr<Block> {\n";
            out += "        if constexpr (requires { " + qualified(factory.symbol) + "(services, parameters); })\n";
            out += "            return " + qualified(factory.symbol) + "(services, parameters);\n        else\n";
            out += "            return " + qualified(factory.symbol) + "(services);\n    };\n";
            out += "    [[maybe_unused]] const auto node_" + name + " = graph->add(std::move(spec_" + name + "));\n";
        }
        if (!uses_services) out += "    (void)services;\n";
        for (const auto& edge : project.edges) {
            const auto from = std::find_if(project.blocks.begin(), project.blocks.end(), [&](const Block& block) { return block.id == edge.from_block; });
            const auto to = std::find_if(project.blocks.begin(), project.blocks.end(), [&](const Block& block) { return block.id == edge.to_block; });
            if (from == project.blocks.end() || to == project.blocks.end() || from->flow != flow.id) continue;
            out += "    // design edge " + edge.id + "\n    graph->connect(node_" + generated_identifier(edge.from_block) + ", " + std::to_string(port_index(from->outputs, edge.from_port)) + ", node_" + generated_identifier(edge.to_block) + ", " + std::to_string(port_index(to->inputs, edge.to_port)) + ", " + std::to_string(edge.capacity) + ");\n";
        }
        out += "    return graph;\n}\n\n";
    }
    out += "template<class Services>\nstd::unique_ptr<foundation::visual::flow::Graph> make_flow(std::string_view flow_id, Services& services, foundation::visual::flow::GraphOptions options = {}) {\n";
    if (project.flows.empty()) out += "    (void)flow_id; (void)services; (void)options;\n";
    for (const auto& flow : project.flows)
        out += "    if (flow_id == " + quoted(flow.id) + ") return make_flow_" + generated_identifier(flow.id) + "(services, options);\n";
    out += "    throw std::invalid_argument(\"Unknown generated flow ID\");\n}\n";
    return out + epilogue(ns);
}

std::pair<std::string, std::string> split_symbol(std::string_view symbol) {
    if (symbol.starts_with("::")) symbol.remove_prefix(2);
    const auto last = symbol.rfind("::");
    return last == std::string_view::npos ? std::pair{std::string{}, std::string(symbol)} :
        std::pair{std::string(symbol.substr(0, last)), std::string(symbol.substr(last + 2))};
}
} // namespace

std::string generated_identifier(std::string_view id) {
    constexpr char hex[] = "0123456789abcdef";
    std::string result = "i_";
    for (const unsigned char ch : id) {
        if (ascii_alpha(static_cast<char>(ch)) || ascii_digit(static_cast<char>(ch))) result += static_cast<char>(ch);
        else { result += '_'; result += hex[ch >> 4]; result += hex[ch & 15]; }
    }
    return result;
}
bool valid_cpp_type(std::string_view type) {
    return !type.empty() && type.size() <= 256 && TypeParser(type).parse();
}

GenerationResult generate(const Project& project, const GenerationOptions& options) {
    auto config = options;
    if (config.output_directory.empty()) config.output_directory = project.generated_directory;
    if (config.cpp_namespace.empty()) config.cpp_namespace = project.cpp_namespace;
    GenerationResult result;
    result.diagnostics = validate(project);
    if (!safe_relative_path(config.output_directory)) error(result.diagnostics, "generation.output_directory", "Generated output must use a safe project-relative directory");
    if (!safe_symbol(config.cpp_namespace) || config.cpp_namespace.starts_with("::")) error(result.diagnostics, "generation.cpp_namespace", "Expected an ordinary qualified C++ namespace");
    if (config.output_bytes == 0) error(result.diagnostics, "generation.output_bytes", "Generated output limit must be nonzero");
    std::map<std::string, const Binding*> bindings;
    for (const auto& binding : project.bindings) bindings.emplace(binding.id, &binding);
    std::vector<BoundEvent> bound_events;
    for (const auto& form : project.forms) for (const auto& control : form.controls) {
        std::map<std::string, std::string> references = control.event_bindings;
        if (!control.binding.empty()) {
            const auto bound = bindings.find(control.binding);
            if (bound != bindings.end()) references.try_emplace(bound->second->event, control.binding);
        }
        std::set<std::string_view> registered;
        for (const auto& [name, id] : references) {
            const auto found = bindings.find(id);
            if (found == bindings.end()) continue; // Model already diagnoses dangling IDs.
            const auto* event = event_description(name);
            if (!event) { error(result.diagnostics, "controls." + control.id, "Unknown event name: " + name); continue; }
            if (!registered.insert(event->kind).second) { error(result.diagnostics, "controls." + control.id, "Multiple aliases bind the same event"); continue; }
            if (!safe_symbol(found->second->symbol)) error(result.diagnostics, "bindings." + id + ".symbol", "Expected a qualified C++ wrapper symbol");
            const auto header = binding_header(*found->second);
            if (!header.empty() && (!include_path(header) || !header_extension(header))) error(result.diagnostics, "bindings." + id + ".header", "Expected a safe relative C++ declaration header path");
            if (header.empty()) warning(result.diagnostics, "bindings." + id + ".header", "No declaration header: include the wrapper declaration before generated events.hpp");
            bound_events.push_back({&control, found->second, event});
        }
    }
    std::vector<BoundFactory> factories;
    for (const auto& block : project.blocks) {
        const auto bound = bindings.find(block.binding);
        const auto* binding = bound == bindings.end() ? nullptr : bound->second;
        const auto symbol = !block.factory.empty() ? block.factory : !block.symbol.empty() ? block.symbol : binding ? binding->symbol : std::string{};
        const auto header = !block.header.empty() ? block.header : header_extension(block.file) ? block.file : binding ? binding_header(*binding) : std::string{};
        if (!safe_symbol(symbol)) error(result.diagnostics, "blocks." + block.id + ".factory", "Expected a qualified C++ factory symbol");
        if (!header.empty() && (!include_path(header) || !header_extension(header))) error(result.diagnostics, "blocks." + block.id + ".header", "Expected a safe relative C++ declaration header path");
        if (header.empty()) warning(result.diagnostics, "blocks." + block.id + ".header", "No declaration header: include the factory declaration before generated flows.hpp");
        for (const auto& port : block.inputs) if (!valid_cpp_type(port.type)) error(result.diagnostics, "blocks." + block.id + ".inputs." + port.id, "Use a C++ value type or an ordinary header-defined alias");
        for (const auto& port : block.outputs) if (!valid_cpp_type(port.type)) error(result.diagnostics, "blocks." + block.id + ".outputs." + port.id, "Use a C++ value type or an ordinary header-defined alias");
        factories.push_back({&block, symbol, header});
    }
    for (const auto& edge : project.edges)
        if (edge.initial_tokens != 0) error(result.diagnostics, "edges." + edge.id + ".initial_tokens", "A count alone cannot initialize arbitrary typed samples; provide seeded state in a breaks_cycle block factory");
    if (has_errors(result.diagnostics)) return result;
    try {
        // Enforce aggregate document limits before constructing emitted source,
        // including when the caller assembled a Project without JSON parsing.
        const auto semantic = semantic_project(project);
        const auto path = [&](std::string_view file) { return config.output_directory + "/" + std::string(file); };
        result.files.push_back({path(generated_ownership_file), std::string(generated_ownership_content)});
        if (!project.forms.empty()) {
            result.files.push_back({path("forms.hpp"), forms_source(project, config.cpp_namespace)});
            result.files.push_back({path("events.hpp"), event_source(bound_events, config.cpp_namespace)});
        }
        auto explicit_flows = project;
        if (explicit_flows.flows.empty() && !explicit_flows.blocks.empty())
            explicit_flows.flows.push_back({"main", "Main"});
        if (!explicit_flows.flows.empty()) result.files.push_back({path("flows.hpp"), flow_source(explicit_flows, factories, config.cpp_namespace)});
        // Exact semantic bytes make freshness checks collision-free and exclude
        // harmless graph positions. This marker is never linked into consumers.
        result.files.push_back({path("design.json"), semantic});
        std::size_t bytes = 0;
        for (const auto& file : result.files) {
            if (file.content.size() > config.output_bytes - bytes) {
                error(result.diagnostics, "generation", "Generated output exceeds the configured byte limit");
                result.files.clear();
                break;
            }
            bytes += file.content.size();
        }
    } catch (const std::exception& exception) {
        error(result.diagnostics, "generation", exception.what());
        result.files.clear();
    }
    return result;
}

bool may_replace_generated(const GeneratedFile& expected, std::string_view existing,
                           bool owned_directory) {
    if (existing == expected.content) return true;
    const auto slash = expected.relative_path.rfind('/');
    const auto name = std::string_view(expected.relative_path).substr(
        slash == std::string::npos ? 0 : slash + 1);
    if (name == generated_ownership_file) return false;
    if (name == "forms.hpp" || name == "events.hpp" || name == "flows.hpp")
        return owned_directory || existing.starts_with(generated_source_prefix);
    if (name == "design.json") return owned_directory;
    return false;
}

std::string handler_stub(const Binding& binding) {
    const auto* event = event_description(binding.event);
    if (!safe_id(binding.id) || !safe_symbol(binding.symbol) || !event) throw std::invalid_argument("Handler stub requires a safe adapter ID, wrapper symbol and supported event");
    const auto [ns, function] = split_symbol(binding.symbol);
    std::string out = "#pragma once\n#include \"visual/ui/ui.hpp\"\n\n";
    if (!ns.empty()) out += "namespace " + ns + " {\n\n";
    out += "// adapter " + binding.id + "\n";
    out += "template<class Services>\nvoid " + function + "(Services& services, foundation::visual::Ui& ui, const " + std::string(event->input) + "& event) {\n";
    out += "    (void)services; (void)ui; (void)event;\n    // Call ordinary project functions and update Ui here.\n}\n";
    if (!ns.empty()) out += "\n} // namespace " + ns + "\n";
    return out;
}
std::string block_stub(const Block& block) {
    const auto symbol = !block.factory.empty() ? block.factory : block.symbol;
    if (!safe_id(block.id) || !safe_symbol(symbol)) throw std::invalid_argument("Block stub requires a safe block ID and factory symbol");
    const auto [ns, function] = split_symbol(symbol);
    std::string out = "#pragma once\n#include \"visual/flow/flow.hpp\"\n#include <map>\n#include <string>\n\n";
    if (!ns.empty()) out += "namespace " + ns + " {\n\n";
    out += "// block " + block.id + "\n";
    out += "template<class Services>\nstd::unique_ptr<foundation::visual::flow::Block> " + function + "(Services& services, const std::map<std::string, std::string>& parameters) {\n";
    out += "    (void)services; (void)parameters;\n    using namespace foundation::visual::flow;\n";
    out += "    return make_block([](WorkContext& context, WorkResult& result) {\n        (void)context;\n        // Set per-port consumed/produced counts after calling ordinary code.\n        // The initial skeleton ends cleanly until an implementation is added.\n        result.status = WorkStatus::finished;\n    });\n}\n";
    if (!ns.empty()) out += "\n} // namespace " + ns + "\n";
    return out;
}

} // namespace foundation::editor
