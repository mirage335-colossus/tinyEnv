#pragma once

#include "editor/model/project.hpp"
#include <string>
#include <string_view>
#include <vector>

namespace foundation::editor {

inline constexpr std::string_view generated_ownership_file = ".foundation-editor-owned.json";
inline constexpr std::string_view generated_ownership_content =
    "{\"owner\":\"foundation-editor\",\"schema_version\":1}\n";
inline constexpr std::string_view generated_source_prefix =
    "// Generated from the semantic design; edit ordinary source files for behavior.\n";

struct GeneratedFile {
    std::string relative_path;
    std::string content;
    bool operator==(const GeneratedFile&) const = default;
};
struct GenerationOptions {
    // Empty overrides use the corresponding project settings.
    std::string output_directory;
    std::string cpp_namespace;
    std::size_t output_bytes = 16 * 1024 * 1024;
};
struct GenerationResult {
    std::vector<GeneratedFile> files;
    std::vector<Diagnostic> diagnostics;
    explicit operator bool() const { return !has_errors(diagnostics); }
};

// Pure deterministic generation: no file access, compiler invocation, source
// parsing or handwritten-code mutation. Publish only after checking diagnostics.
GenerationResult generate(const Project&, const GenerationOptions& = {});

// Pure preflight for an EXISTING destination. The caller supplies whether the
// same output directory's ownership guard has been verified byte-for-byte and
// must still use checked file identity/bytes during actual publication.
bool may_replace_generated(const GeneratedFile& expected, std::string_view existing,
                           bool owned_directory);

// These skeletons are exclusively for an explicit create-new-code action.
// The caller must create the destination exclusively; regeneration never calls
// these functions and must never enroll existing user source in a save batch.
std::string handler_stub(const Binding&);
std::string block_stub(const Block&);

// IDs may contain punctuation; their generated C++ names use an
// injective byte encoding rather than lossy punctuation replacement.
std::string generated_identifier(std::string_view id);
bool valid_cpp_type(std::string_view type);
// Preserve accepted historical spellings when navigating existing bindings.
inline std::string_view canonical_event_name(std::string_view name) {
    if(name=="change"||name=="edit")return "text_changed";
    if(name=="toggle")return "checked";
    if(name=="select")return "choose";
    return name;
}

} // namespace foundation::editor
