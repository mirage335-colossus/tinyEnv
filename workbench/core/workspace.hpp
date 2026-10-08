#pragma once

#include "editor/platform/project_files.hpp"
#include "json.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace tinyenv {

struct PathToggle {
    std::string path;
    bool enabled{true};
    friend bool operator==(const PathToggle&, const PathToggle&) = default;
};
struct AiSettings {
    std::string provider{"openrouter"}, endpoint, model;
    // Unset generation controls leave the provider's model defaults intact.
    std::optional<int> num_predict, num_keep, num_ctx;
    std::optional<double> temperature, top_p;
    bool web_search{}, nitro{};
    std::string service_tier, reasoning_effort;
    std::vector<std::string> routing_providers;
    bool zdr{};
    friend bool operator==(const AiSettings&, const AiSettings&) = default;
};
struct SelectorState {
    bool deep_research{};
    std::vector<PathToggle> scribbles, refs, tools;
    int research_max_queries{8}, research_max_results{24};
    std::string research_source{"web"}, kiwix_index;
    int context_max_kib{256};
    friend bool operator==(const SelectorState&, const SelectorState&) = default;
};
// Explicitly selected local bytes, retained in the managed image store. Names
// are display metadata; only a validated digest locates the immutable copy.
struct ImageAttachment {
    std::string name, mime_type, sha256;
    std::size_t bytes{};
    friend bool operator==(const ImageAttachment&, const ImageAttachment&) = default;
};
// An explicit submission record, never inferred from Markdown headings. The
// digest checks prior transcript bytes; it is integrity metadata, not a signature.
struct SubmittedMessage {
    std::string prompt;
    bool agentic{};
    std::size_t history_bytes{};
    std::string history_sha256;
    std::vector<ImageAttachment> images;
    friend bool operator==(const SubmittedMessage&, const SubmittedMessage&) = default;
};
struct ChatState {
    SelectorState selector;
    AiSettings ai;
    // False when AI settings follow app defaults. Legacy saved provider/model
    // selections are read as configured, preserving their per-chat override.
    bool ai_configured{};
    std::string cwd{"."}, draft, pseudocode;
    std::vector<ImageAttachment> draft_images;
    // Bounded untrusted provenance metadata; the JSON root must be an array.
    std::string sources_json{"[]"};
    std::string left_tab{"Chats"}, center_tab{"Chat Markdown"}, right_tab{"Selector"};
    bool agentic{}, split_chat{};
    std::optional<SubmittedMessage> submission;
    friend bool operator==(const ChatState&, const ChatState&) = default;
};
struct Chat {
    std::filesystem::path path;
    std::string text;
    ChatState state;
    foundation::editor::FileSnapshot original, state_original;
};
[[nodiscard]] SubmittedMessage make_submission(std::string_view prompt, bool agentic, std::string_view history,
                                              const std::vector<ImageAttachment>& images = {});
// Returns the original pre-submission history. Refuses a modified/truncated
// prefix or original user message; later response/retry text remains untouched.
[[nodiscard]] std::string submission_history(const Chat& chat);
struct TreeEntry {
    std::filesystem::path path;
    std::string name;
    bool directory{}, symlink{};
    std::uint64_t bytes{};
};
struct DiskEntry {
    std::filesystem::path path;
    std::string name;
    bool directory{};
    std::uint64_t bytes{};
};
struct DiskUsage {
    std::vector<DiskEntry> entries;
    std::uint64_t total_bytes{};
    std::size_t visited{};
    bool truncated{};
};
struct Snippet {
    std::string id, title, text;
    friend bool operator==(const Snippet&, const Snippet&) = default;
};
enum class SnippetKind { prompts, pseudocode };

// Project-relative UTF-8 .chat.md files, with checked independent sidecars.
// Construction and reads create no files. The caller serializes this model.
class Workspace {
public:
    static constexpr std::size_t default_scan_entries = 10000;
    static constexpr std::size_t maximum_scan_entries = 100000;
    static constexpr std::size_t maximum_scan_depth = 32;
    static constexpr std::size_t maximum_images = 4;
    static constexpr std::size_t maximum_image_bytes = 4 * 1024 * 1024;
    static constexpr std::size_t maximum_images_bytes = 8 * 1024 * 1024;
    explicit Workspace(std::filesystem::path root);
    ~Workspace();
    [[nodiscard]] const std::filesystem::path& root() const noexcept { return files_.root(); }
    [[nodiscard]] foundation::editor::ProjectFiles& files() noexcept { return files_; }
    [[nodiscard]] const foundation::editor::ProjectFiles& files() const noexcept { return files_; }
    [[nodiscard]] std::vector<std::filesystem::path> chats(std::size_t max_entries = default_scan_entries) const;
    [[nodiscard]] Chat open_chat(const std::filesystem::path& path) const;
    [[nodiscard]] Chat new_chat(const std::filesystem::path& path, std::string_view text = "");
    // Preflight checks both originals, then save text and state independently.
    // A failure after text publication may leave only state unsaved; snapshots
    // reflect every completed write, so callers retain drafts and can reload.
    void save(Chat& chat);
    void save_state(Chat& chat);
    // Only an explicit attach action reads an ordinary local PNG/JPEG source.
    // Relative paths select this project; absolute paths select a local file.
    // No symlink component is followed. Original paths are never persisted.
    [[nodiscard]] ImageAttachment attach_image(const std::filesystem::path& path);
    // Revalidate managed bytes before Send/Retry. Metadata cannot direct a
    // read elsewhere; returned provider inputs contain inline bytes only.
    [[nodiscard]] json::Value::Array image_payloads(const std::vector<ImageAttachment>& images) const;
    [[nodiscard]] static bool is_chat_path(const std::filesystem::path& path);
    // Ordinary rooted file-manager operations. Parents must already exist,
    // destinations never replace entries, and symlink/private paths are refused.
    void create_file(const std::filesystem::path& path, std::string_view text = "");
    void create_directory(const std::filesystem::path& path);
    // Copy a bounded ordinary UTF-8 file, checking its original bytes. A chat
    // keeps its suffix and copies saved companion state to an independent path.
    // Text and state publish separately; a late failure describes the copy.
    void copy_entry(const std::filesystem::path& source, const std::filesystem::path& destination);
    // A .chat.md file keeps its suffix and its independent companion state.
    // These paired changes are not atomic; failures describe any partial result.
    void rename_entry(const std::filesystem::path& source, const std::filesystem::path& destination);
    // Removes a regular file or an empty directory, never a directory tree.
    void remove_entry(const std::filesystem::path& path);
    [[nodiscard]] std::vector<TreeEntry> children(const std::filesystem::path& directory = ".", std::size_t max_entries = default_scan_entries) const;
    [[nodiscard]] DiskUsage disk_usage(const std::filesystem::path& directory = ".", std::size_t max_entries = default_scan_entries) const;
    [[nodiscard]] std::vector<Snippet> snippets(SnippetKind kind) const;
    [[nodiscard]] std::vector<Snippet> snippets(std::string_view kind) const;
    void save_snippets(SnippetKind kind, const std::vector<Snippet>& snippets);
    void save_snippets(std::string_view kind, const std::vector<Snippet>& snippets);
    [[nodiscard]] static std::filesystem::path state_path(const std::filesystem::path& chat);
private:
    foundation::editor::ProjectFiles files_;
    std::intptr_t operations_root_{-1};
    mutable std::map<SnippetKind, foundation::editor::FileSnapshot> snippet_originals_;
    [[nodiscard]] foundation::editor::FileSnapshot inspect_optional(const std::filesystem::path& path) const;
};

} // namespace tinyenv
