#pragma once

#include "editor/generate/generate.hpp"
#include "editor/platform/project_files.hpp"

#include <filesystem>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace foundation::editor {

struct GeneratedBatch {
    std::vector<ProjectFiles::Write> writes;
    ProjectFiles::Write revision_marker;
    bool changed = false;
};

// Capture only design and generator-owned destinations. Handwritten sources are
// never part of this batch. The semantic design.json freshness marker is last;
// the rooted save journal handles interruption and detects foreign file changes.
inline GeneratedBatch capture_generated_batch(ProjectFiles& files,
                                              const GenerationResult& generated,
                                              const FileSnapshot& design,
                                              std::string design_text,
                                              bool creating = false) {
    namespace fs = std::filesystem;
    if (files.recovery_pending())
        throw FileError(FileFailure::conflict, "Interrupted generated publication must be recovered before saving or building");
    if (!generated || generated.files.empty())
        throw std::invalid_argument("Only valid generated output may be published");
    const auto current_design = files.inspect(design.path);
    if (current_design.identity != design.identity || current_design.text != design.text)
        throw FileError(FileFailure::conflict, "Design changed externally; reload it before generation");
    const auto& marker = generated.files.back();
    const auto marker_path = fs::path(std::u8string(marker.relative_path.begin(), marker.relative_path.end()));
    if (!safe_relative_path(marker.relative_path) || marker_path.filename() != "design.json")
        throw std::logic_error("Generator did not supply its design revision marker last");
    const auto guard_path = marker_path.parent_path() / std::string(generated_ownership_file);
    const std::string guard_text(generated_ownership_content);
    bool guard_generated = false;
    std::set<fs::path> paths;
    for (const auto& item : generated.files) {
        const auto path = fs::path(std::u8string(item.relative_path.begin(), item.relative_path.end()));
        if (!safe_relative_path(item.relative_path) || !paths.insert(path).second)
            throw std::logic_error("Generator returned an unsafe or repeated output path");
        if (path == design.path)
            throw std::invalid_argument("Generated output collides with the design file: " + (files.root() / path).string());
        if (path.parent_path() != marker_path.parent_path())
            throw std::logic_error("Generated output escaped its owned directory");
        if (path == guard_path) guard_generated = item.content == guard_text;
    }
    if (!guard_generated) throw std::logic_error("Generator produced no ownership guard");
    if (!guard_path.parent_path().empty()) files.ensure_directory(guard_path.parent_path());
    const auto guard = files.inspect(guard_path);
    const bool owned_directory = guard.identity.exists && guard.text == guard_text;
    GeneratedBatch result;
    for (std::size_t i = 0; i < generated.files.size(); ++i) {
        const auto& item = generated.files[i];
        const auto path = fs::path(std::u8string(item.relative_path.begin(), item.relative_path.end()));
        auto original = path == guard_path ? guard : files.inspect(path);
        if (creating && original.identity.exists && original.text != item.content)
            throw FileError(FileFailure::conflict,
                "New project output already exists: " + (files.root() / path).string());
        if (original.identity.exists && !may_replace_generated(item, original.text, owned_directory))
            throw FileError(FileFailure::conflict,
                "Refusing to replace a file without generator ownership: " + (files.root() / path).string());
        const bool changed = !original.identity.exists || original.text != item.content;
        result.changed = result.changed || changed;
        ProjectFiles::Write write{std::move(original), item.content};
        if (i + 1 == generated.files.size()) result.revision_marker = std::move(write);
        else if (changed || path == guard_path) result.writes.push_back(std::move(write));
    }
    result.changed = result.changed || !design.identity.exists || design.text != design_text;
    // Include an unchanged design as a checked read dependency when other
    // output changes. The journal does not rewrite byte-identical files.
    result.writes.push_back({design, std::move(design_text)});
    return result;
}

} // namespace foundation::editor
