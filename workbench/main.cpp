#include "workbench/core/json.hpp"
#include "workbench/core/pseudocode.hpp"
#include "workbench/core/workspace.hpp"

#include <filesystem>
#include <iostream>
#include <locale>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
namespace fs = std::filesystem;

struct Arguments {
    std::string command;
    fs::path root, file;
    bool help = false;
};

std::string path_text(const fs::path& path) {
    const auto text = path.generic_u8string();
    std::string result(text.begin(), text.end());
    if (!foundation::editor::ProjectFiles::valid_utf8(result))
        throw std::invalid_argument("A workspace path is not valid UTF-8");
    return result;
}

fs::path utf8_path(std::string_view value) {
    return fs::path(std::u8string(value.begin(), value.end()));
}

void usage(std::ostream& out) {
    out << "tinyEnv headless UI workbench tool\n\n"
        << "Usage: tinyenv-workbench-tool inspect --root PATH\n"
        << "       tinyenv-workbench-tool parse --file PATH [--root PATH]\n\n"
        << "  inspect  Print JSON with the root, chat paths and root directory entries.\n"
        << "  parse    Print JSON with canonical pseudocode, its program and flow graph.\n\n"
        << "All paths and source files must be UTF-8. The root must already exist.\n"
        << "A relative --file with --root is relative to that root. Without --root,\n"
        << "the file is relative to the current directory and its parent is the root.\n"
        << "Files must stay inside the root; parent components and symlink traversal\n"
        << "are rejected. Both commands only read files. Syntax diagnostics go to\n"
        << "stderr as file:line:column: error: message. Any error returns status 1.\n"
        << "Use --help or -h for this text.\n";
}

Arguments arguments(int argc, char** argv) {
    // Validate every argument before taking a help shortcut or interpreting paths.
    for (int i = 1; i < argc; ++i)
        if (!foundation::editor::ProjectFiles::valid_utf8(argv[i]))
            throw std::invalid_argument("Arguments must be valid UTF-8");
    Arguments result;
    std::set<std::string> seen;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            if (!seen.insert("--help").second)
                throw std::invalid_argument("Repeated argument: --help");
            result.help = true;
            continue;
        }
        if (i == 1 && !arg.empty() && arg.front() != '-') {
            result.command = arg;
            continue;
        }
        if (arg != "--root" && arg != "--file")
            throw std::invalid_argument("Unknown argument: " + arg);
        if (!seen.insert(arg).second)
            throw std::invalid_argument("Repeated argument: " + arg);
        if (++i == argc || !*argv[i] || argv[i][0] == '-')
            throw std::invalid_argument("Missing value for " + arg);
        if (arg == "--root") result.root = utf8_path(argv[i]);
        else result.file = utf8_path(argv[i]);
    }
    if (result.command.empty()) {
        if (result.help && seen.size() == 1) return result;
        throw std::invalid_argument("Choose inspect or parse");
    }
    if (result.command != "inspect" && result.command != "parse")
        throw std::invalid_argument("Choose inspect or parse");
    if (result.command == "inspect" && !result.file.empty())
        throw std::invalid_argument("--file applies only to parse");
    if (result.help) return result;
    if (result.command == "inspect" && result.root.empty())
        throw std::invalid_argument("inspect requires --root PATH");
    if (result.command == "parse" && result.file.empty())
        throw std::invalid_argument("parse requires --file PATH");
    return result;
}

fs::path absolute_path(const fs::path& path) {
    for (const auto& component : path)
        if (component == "..")
            throw std::invalid_argument("Paths cannot contain parent components: " + path_text(path));
    std::error_code error;
    auto absolute = fs::absolute(path, error);
    if (error)
        throw std::invalid_argument("Cannot resolve path " + path_text(path) + ": " + error.message());
    return absolute.lexically_normal();
}

struct Location { fs::path root, file; };

Location location(const Arguments& args) {
    auto root = args.root.empty() ? fs::path{} : absolute_path(args.root);
    const auto file = absolute_path(args.file.is_absolute() || root.empty()
        ? args.file : root / args.file);
    if (root.empty()) root = file.parent_path();
    const auto relative = file.lexically_relative(root);
    if (relative.empty() || relative == "." || relative.is_absolute())
        throw std::invalid_argument("The file must be inside the selected root: " + path_text(file));
    for (const auto& component : relative)
        if (component == "..")
            throw std::invalid_argument("The file must be inside the selected root: " + path_text(file));
    return {std::move(root), relative};
}

void json_string(std::ostream& out, std::string_view value) {
    out << tinyenv::json::stringify(tinyenv::json::Value(value));
}

void json_number(std::ostream& out, double value) {
    out << tinyenv::json::stringify(tinyenv::json::Value(value));
}

void program_nodes(std::ostream& out, const std::vector<tinyenv::FlowNode>& nodes) {
    out << '[';
    bool comma = false;
    for (const auto& node : nodes) {
        if (comma) out << ',';
        comma = true;
        out << "{\"id\":" << node.id << ",\"kind\":";
        json_string(out, tinyenv::flow_kind_name(node.kind));
        out << ",\"line\":" << node.line << ",\"end_line\":" << node.end_line << ",\"role\":";
        json_string(out, node.role);
        out << ",\"text\":";
        json_string(out, node.text);
        out << ",\"iterations\":" << node.iterations << ",\"condition\":";
        json_string(out, tinyenv::flow_condition_name(node.condition));
        out << ",\"children\":";
        program_nodes(out, node.children);
        out << ",\"otherwise\":";
        program_nodes(out, node.otherwise);
        out << '}';
    }
    out << ']';
}

void graph_json(std::ostream& out, const tinyenv::FlowGraph& graph) {
    out << "{\"width\":";
    json_number(out, graph.width);
    out << ",\"height\":";
    json_number(out, graph.height);
    out << ",\"nodes\":[";
    bool comma = false;
    for (const auto& node : graph.nodes) {
        if (comma) out << ',';
        comma = true;
        out << "{\"id\":" << node.id << ",\"kind\":";
        json_string(out, tinyenv::flow_kind_name(node.kind));
        out << ",\"line\":" << node.line << ",\"label\":";
        json_string(out, node.label);
        out << ",\"x\":"; json_number(out, node.x);
        out << ",\"y\":"; json_number(out, node.y);
        out << ",\"width\":"; json_number(out, node.width);
        out << ",\"height\":"; json_number(out, node.height);
        out << '}';
    }
    out << "],\"edges\":[";
    comma = false;
    for (const auto& edge : graph.edges) {
        if (comma) out << ',';
        comma = true;
        out << "{\"from\":" << edge.from << ",\"to\":" << edge.to << ",\"label\":";
        json_string(out, edge.label);
        out << ",\"loop\":" << (edge.loop ? "true" : "false") << '}';
    }
    out << "]}";
}

std::ostringstream json_output() {
    std::ostringstream out;
    out.imbue(std::locale::classic());
    return out;
}

int inspect(const Arguments& args) {
    tinyenv::Workspace workspace(absolute_path(args.root));
    const auto chats = workspace.chats();
    const auto files = workspace.children();
    auto out = json_output();
    out << "{\"schema_version\":1,\"root\":";
    json_string(out, path_text(workspace.root()));
    out << ",\"chats\":[";
    bool comma = false;
    for (const auto& chat : chats) {
        if (comma) out << ',';
        comma = true;
        json_string(out, path_text(chat));
    }
    out << "],\"files\":[";
    comma = false;
    for (const auto& file : files) {
        if (comma) out << ',';
        comma = true;
        out << "{\"path\":";
        json_string(out, path_text(file.path));
        out << ",\"name\":";
        json_string(out, path_text(file.path.filename()));
        out << ",\"directory\":" << (file.directory ? "true" : "false")
            << ",\"symlink\":" << (file.symlink ? "true" : "false")
            << ",\"bytes\":" << file.bytes << '}';
    }
    out << "]}\n";
    std::cout << out.str();
    return 0;
}

int parse(const Arguments& args) {
    const auto where = location(args);
    tinyenv::Workspace workspace(where.root);
    const auto file = path_text(workspace.root() / where.file);
    foundation::editor::FileSnapshot source;
    try {
        source = workspace.files().read(where.file);
    } catch (const foundation::editor::FileError& error) {
        throw std::runtime_error(file + ": " + error.what());
    }
    const auto parsed = tinyenv::parse_pseudocode(source.text);
    for (const auto& diagnostic : parsed.diagnostics)
        std::cerr << file << ':' << diagnostic.line << ':' << diagnostic.column
                  << ": error: " << diagnostic.message << '\n';
    if (!parsed) return 1;
    const auto canonical = tinyenv::write_pseudocode(*parsed.program);
    const auto graph = tinyenv::make_flow_graph(*parsed.program);
    auto out = json_output();
    out << "{\"schema_version\":1,\"root\":";
    json_string(out, path_text(workspace.root()));
    out << ",\"file\":";
    json_string(out, path_text(where.file));
    out << ",\"canonical\":";
    json_string(out, canonical);
    out << ",\"program\":{\"nodes\":";
    program_nodes(out, parsed.program->nodes);
    out << "},\"graph\":";
    graph_json(out, graph);
    out << "}\n";
    std::cout << out.str();
    return 0;
}
} // namespace

int main(int argc, char** argv) {
    try {
        const auto args = arguments(argc, argv);
        int status = 0;
        if (args.help) usage(std::cout);
        else status = args.command == "inspect" ? inspect(args) : parse(args);
        std::cout.flush();
        if (!std::cout) throw std::runtime_error("Cannot write standard output");
        return status;
    } catch (const std::exception& error) {
        std::cerr << "tinyenv-workbench-tool: " << error.what() << '\n';
        return 1;
    }
}
