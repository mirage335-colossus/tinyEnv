#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace foundation::editor {

// The design owns composition only. Source files and function bodies remain
// ordinary project-owned files. Coordinates use logical pixels; control x/y
// are absolute form-space coordinates (parent changes ownership, not origin).
// Block x/y are authoring view state and never affect application behavior.
struct Rect {
    double x = 0, y = 0, width = 120, height = 32;
    bool operator==(const Rect&) const = default;
};
struct Option {
    std::string id, label, value;
    bool enabled = true;
    bool operator==(const Option&) const = default;
};
struct Control {
    std::string id, kind = "button", parent, label, text;
    Rect layout;
    std::vector<Option> options;
    std::string binding;
    std::map<std::string, std::string> event_bindings;
    bool enabled = true, visible = true, checked = false;
    bool multiline = false, read_only = false;
    std::size_t text_limit = 1024 * 1024;
    bool operator==(const Control&) const = default;
};
struct Form {
    std::string id, label;
    double width = 640, height = 480;
    std::vector<Control> controls;
    bool operator==(const Form&) const = default;
};
struct Binding {
    std::string id, event = "activate", file, symbol, anchor, header;
    bool operator==(const Binding&) const = default;
};
struct Port {
    std::string id, type = "float";
    bool required = true;
    bool operator==(const Port&) const = default;
};
struct Flow {
    std::string id, label;
    bool operator==(const Flow&) const = default;
};
struct Block {
    std::string id, label, factory, binding, file, symbol, header;
    std::string flow = "main";
    double x = 0, y = 0;
    std::vector<Port> inputs, outputs;
    std::map<std::string, std::string> params;
    bool breaks_cycle = false;
    bool operator==(const Block&) const = default;
};
struct Edge {
    std::string id, from_block, from_port, to_block, to_port;
    std::size_t capacity = 256;
    std::size_t initial_tokens = 0;
    bool operator==(const Edge&) const = default;
};
struct Recipe {
    std::string id, label;
    std::vector<std::string> argv;
    std::string working_directory = ".";
    bool operator==(const Recipe&) const = default;
};
struct Project {
    std::uint32_t schema_version = 1;
    std::string name = "Untitled";
    std::string generated_directory = "generated/visual";
    std::string cpp_namespace = "foundation::generated";
    std::vector<Form> forms;
    std::vector<Binding> bindings;
    std::vector<Flow> flows;
    std::vector<Block> blocks;
    std::vector<Edge> edges;
    std::vector<Recipe> recipes;
    bool operator==(const Project&) const = default;
};

struct Limits {
    std::size_t file_bytes = 8 * 1024 * 1024;
    std::size_t string_bytes = 2 * 1024 * 1024;
    std::size_t nesting = 32;
    std::size_t json_values = 200000;
    std::size_t forms = 128, controls = 8192, bindings = 8192;
    std::size_t flows = 256, blocks = 8192, ports = 32768, edges = 32768;
    std::size_t recipes = 128, options = 32768, parameters = 32768;
    std::size_t edge_capacity = 1024 * 1024;
};
enum class Severity { warning, error };
struct Diagnostic {
    Severity severity = Severity::error;
    std::string path, message;
    std::size_t line = 0, column = 0;
};
struct ParseResult {
    std::optional<Project> project;
    std::vector<Diagnostic> diagnostics;
    explicit operator bool() const { return project.has_value(); }
};

bool safe_id(std::string_view value);
bool safe_relative_path(std::string_view value, bool allow_dot = false);
bool valid_utf8(std::string_view value);
bool valid_cpp_symbol(std::string_view value);
std::vector<Diagnostic> validate(const Project& project, const Limits& limits = {});
bool has_errors(const std::vector<Diagnostic>& diagnostics);
ParseResult parse_project(std::string_view bytes, const Limits& limits = {});
// A structurally readable document is returned even when semantic diagnostics
// contain errors, so incomplete designs can be repaired in the editor.
// Deterministic schema-1 JSON, preserving declared order and source bytes.
// Throws std::invalid_argument for unsafe/unrepresentable data. Composition
// errors remain saveable drafts; callers must validate before generation.
std::string write_project(const Project& project, const Limits& limits = {});
// Canonical source-generation input: excludes block positions only.
std::string semantic_project(const Project& project, const Limits& limits = {});
Project empty_project(std::string name = "Untitled");
Project demo_project();

// Bounded snapshot history. Call reset on project open, commit after each
// semantic edit, and use returned snapshots for undo/redo. Source buffers keep
// their own history; this never owns or rewrites their text.
class History {
public:
    explicit History(std::size_t bytes = 16 * 1024 * 1024,
                     std::size_t entries = 128);
    void reset(const Project& project);
    bool commit(const Project& project);
    std::optional<Project> undo();
    std::optional<Project> redo();
    bool can_undo() const;
    bool can_redo() const;
    std::size_t bytes() const;
private:
    std::size_t limit_bytes_, limit_entries_, cursor_ = 0, bytes_ = 0;
    std::vector<std::string> snapshots_;
};

} // namespace foundation::editor
