#include "editor/generate/generate.hpp"
#include "editor/generate/publish.hpp"
#include "editor/model/project.hpp"
#include "editor/platform/project_files.hpp"

#include <filesystem>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
namespace fs = std::filesystem;
namespace editor = foundation::editor;

struct Arguments {
    std::string command;
    fs::path project, root;
    editor::GenerationOptions generation;
    bool output_supplied = false, namespace_supplied = false, help = false;
};

fs::path utf8_path(std::string_view value) {
    return fs::path(std::u8string(value.begin(), value.end()));
}

void usage(std::ostream& out) {
    out << "Foundation graphical editor authoring tool\n\n"
        << "Usage: foundation-editor-tool COMMAND --project PATH [--root PATH]\n"
        << "       [--output RELATIVE-DIRECTORY] [--namespace CPP-NAMESPACE]\n\n"
        << "Commands:\n"
        << "  new              Create an empty form/flow design and its generated C++.\n"
        << "  validate         Check the design document and composition contracts.\n"
        << "  generate         Publish deterministic C++ and the saved design revision.\n"
        << "  check-generated  Check retained output without writing any files.\n"
        << "  recover          Complete an interrupted design/output publication.\n\n"
        << "PATH is a design JSON file or an existing project directory. A directory\n"
        << "selects design/project.json. --root sets the project file boundary; otherwise\n"
        << "use the JSON file's parent, or its grandparent when the parent is design.\n"
        << "A relative PATH with --root is relative to that root. The root must\n"
        << "already exist. New never replaces an existing design or handwritten file.\n"
        << "Generation options apply to new, generate and check-generated. New and\n"
        << "generate save these choices in the design; omitted choices use its settings.\n"
        << "Defaults for a new design:\n"
        << "  --output generated/visual  --namespace foundation::generated\n"
        << "Use --help for this text. No command loads code or invokes a compiler.\n";
}

Arguments arguments(int argc, char** argv) {
    Arguments result;
    std::set<std::string> seen;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") { result.help = true; continue; }
        if (!arg.empty() && arg.front() != '-' && result.command.empty()) {
            result.command = arg;
            continue;
        }
        if (arg != "--project" && arg != "--root" && arg != "--output" && arg != "--namespace")
            throw std::invalid_argument("Unknown argument: " + arg);
        if (!seen.insert(arg).second) throw std::invalid_argument("Repeated argument: " + arg);
        if (++i == argc || !*argv[i]) throw std::invalid_argument("Missing value for " + arg);
        const std::string value = argv[i];
        if (value.starts_with("--")) throw std::invalid_argument("Missing value for " + arg);
        if (arg == "--project") result.project = utf8_path(value);
        else if (arg == "--root") result.root = utf8_path(value);
        else if (arg == "--output") { result.generation.output_directory = value; result.output_supplied = true; }
        else { result.generation.cpp_namespace = value; result.namespace_supplied = true; }
    }
    if (result.help) return result;
    if (result.command != "new" && result.command != "validate" && result.command != "generate" &&
        result.command != "check-generated" && result.command != "recover")
        throw std::invalid_argument("Choose new, validate, generate, check-generated or recover");
    if (result.project.empty()) throw std::invalid_argument("--project PATH is required");
    if ((result.command == "validate" || result.command == "recover") &&
        (result.output_supplied || result.namespace_supplied))
        throw std::invalid_argument("Generation options apply only to new, generate and check-generated");
    if (result.output_supplied && !editor::safe_relative_path(result.generation.output_directory))
        throw std::invalid_argument("--output must be a safe project-relative directory");
    if (result.namespace_supplied && !editor::valid_cpp_symbol(result.generation.cpp_namespace))
        throw std::invalid_argument("--namespace must be a C++ namespace name");
    return result;
}

fs::path absolute_path(const fs::path& path) {
    for (const auto& part : path)
        if (part == "..") throw std::invalid_argument("Paths cannot contain parent components: " + path.string());
    std::error_code error;
    auto result = fs::absolute(path, error);
    if (error) throw std::invalid_argument("Cannot resolve path " + path.string() + ": " + error.message());
    return result.lexically_normal();
}

struct Location { fs::path root, design; };

Location location(const Arguments& args) {
    const auto explicit_root = args.root.empty() ? fs::path{} : absolute_path(args.root);
    const auto requested = absolute_path(args.project.is_absolute() || explicit_root.empty()
        ? args.project : explicit_root / args.project);
    std::error_code error;
    const auto status = fs::status(requested, error);
    if (error && error != std::errc::no_such_file_or_directory)
        throw std::invalid_argument("Cannot inspect project path " + requested.string() + ": " + error.message());
    const bool directory = !error && fs::is_directory(status);
    auto root = explicit_root;
    if (root.empty()) {
        root = directory ? requested : requested.parent_path();
        if (!directory && root.filename() == "design") root = root.parent_path();
    }
    const auto design_absolute = directory ? requested / "design/project.json" : requested;
    const auto design = design_absolute.lexically_relative(root);
    if (!editor::safe_relative_path(design.generic_string()))
        throw std::invalid_argument("Design file must be inside the selected project root: " + design_absolute.string());
    return {std::move(root), design};
}

void diagnostics(const std::vector<editor::Diagnostic>& items, const fs::path& file) {
    for (const auto& item : items) {
        std::cerr << file.string();
        if (item.line) {
            std::cerr << ':' << item.line;
            if (item.column) std::cerr << ':' << item.column;
        }
        if (!item.path.empty()) std::cerr << " [" << item.path << ']';
        std::cerr << ": " << (item.severity == editor::Severity::error ? "error: " : "warning: ") << item.message << '\n';
    }
}

int publish(editor::ProjectFiles& files, const editor::FileSnapshot& design,
            const editor::Project& project, const editor::GenerationOptions& options, bool create) {
    auto result = editor::generate(project, options);
    diagnostics(result.diagnostics, files.root() / design.path);
    if (!result) return 1;
    auto batch = editor::capture_generated_batch(files, result, design, editor::write_project(project), create);
    if (batch.changed) (void)files.save_batch(batch.writes, batch.revision_marker);
    std::cout << (create ? "Created " : "Generated ") << (files.root() / design.path).string()
              << " (" << result.files.size() << " retained output files" << (batch.changed ? "; published" : "; unchanged") << ")\n";
    return 0;
}

int check_generated(const editor::ProjectFiles& files, const editor::FileSnapshot& design,
                    const editor::Project& project, const editor::GenerationOptions& options) {
    auto result = editor::generate(project, options);
    diagnostics(result.diagnostics, files.root() / design.path);
    if (!result) return 1;
    bool fresh = true;
    for (const auto& generated : result.files) {
        const auto path = utf8_path(generated.relative_path);
        try {
            const auto actual = files.read(path);
            if (actual.text == generated.content) continue;
            std::cerr << (files.root() / path).string() << ": generated output differs\n";
        } catch (const editor::FileError& error) {
            if (error.code() != editor::FileFailure::missing) throw;
            std::cerr << (files.root() / path).string() << ": generated output is missing\n";
        }
        fresh = false;
    }
    const auto current_design = files.read(design.path);
    if (current_design.identity != design.identity || current_design.text != design.text)
        throw editor::FileError(editor::FileFailure::conflict,
            "Design changed externally during the freshness check: " + (files.root() / design.path).string());
    if (fresh) std::cout << "Generated output is current: " << (files.root() / design.path).string() << '\n';
    else std::cerr << "Run generate explicitly before building this design.\n";
    return fresh ? 0 : 1;
}

int run(const Arguments& args) {
    const auto where = location(args);
    editor::ProjectFiles files(where.root);
    if (args.command == "recover") {
        if (files.recovery_pending()) {
            files.recover_batch();
            std::cout << "Completed interrupted publication in " << files.root().string() << '\n';
        } else std::cout << "No interrupted publication in " << files.root().string() << '\n';
        return 0;
    }
    if (files.recovery_pending())
        throw editor::FileError(editor::FileFailure::conflict,
            "Interrupted publication in " + files.root().string() + "; run recover explicitly before further authoring or building");
    if (args.command == "new") {
        if (!where.design.parent_path().empty()) files.ensure_directory(where.design.parent_path());
        auto design = files.inspect(where.design);
        if (design.identity.exists)
            throw editor::FileError(editor::FileFailure::conflict,
                "New never replaces an existing design: " + (files.root() / where.design).string());
        auto project = editor::empty_project(files.root().filename().string());
        if (project.name.empty()) project.name = "Untitled";
        if (project.forms.empty()) {
            editor::Form form;
            form.id = "form1";
            form.label = "Main";
            project.forms.push_back(std::move(form));
        }
        if (project.flows.empty()) project.flows.push_back(editor::Flow{"flow1", "Main flow"});
        if (args.output_supplied) project.generated_directory = args.generation.output_directory;
        if (args.namespace_supplied) project.cpp_namespace = args.generation.cpp_namespace;
        return publish(files, design, project, args.generation, true);
    }
    const auto design = files.read(where.design);
    auto parsed = editor::parse_project(design.text);
    diagnostics(parsed.diagnostics, files.root() / where.design);
    if (!parsed || editor::has_errors(parsed.diagnostics)) return 1;
    if (args.command == "validate") {
        std::cout << "Valid design: " << (files.root() / where.design).string() << '\n';
        return 0;
    }
    if (args.output_supplied) parsed.project->generated_directory = args.generation.output_directory;
    if (args.namespace_supplied) parsed.project->cpp_namespace = args.generation.cpp_namespace;
    if (args.command == "check-generated") return check_generated(files, design, *parsed.project, args.generation);
    return publish(files, design, *parsed.project, args.generation, false);
}
} // namespace

int main(int argc, char** argv) {
    try {
        const auto args = arguments(argc, argv);
        if (args.help) { usage(std::cout); return 0; }
        return run(args);
    } catch (const std::exception& error) {
        std::cerr << "foundation-editor-tool: " << error.what() << '\n';
        return 1;
    }
}
