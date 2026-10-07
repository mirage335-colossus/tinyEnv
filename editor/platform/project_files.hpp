#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace foundation::editor {

enum class FileFailure { invalid_path, missing, permission, encoding, limit, conflict, io, unavailable };
class FileError : public std::runtime_error {
public:
    FileError(FileFailure code, std::string message) : std::runtime_error(std::move(message)), code_(code) {}
    [[nodiscard]] FileFailure code() const noexcept { return code_; }
private:
    FileFailure code_;
};
struct FileIdentity {
    bool exists{};
    std::uint64_t device{}, object{}, size{};
    std::int64_t modified_seconds{}, modified_nanoseconds{};
    std::uint32_t permissions{};
    friend bool operator==(const FileIdentity&, const FileIdentity&) = default;
};
struct FileSnapshot {
    std::filesystem::path path; // Relative to the captured ProjectFiles root.
    std::string text;
    FileIdentity identity;
};

// Ordinary UTF-8 files only. Every path component must be inside root, with no
// symlink/reparse-point traversal. No project load runs commands or creates files.
class ProjectFiles {
public:
    static constexpr std::size_t default_max_bytes = 8 * 1024 * 1024;
    explicit ProjectFiles(std::filesystem::path root, std::size_t max_bytes = default_max_bytes);
    ~ProjectFiles();
    ProjectFiles(const ProjectFiles&) = delete;
    ProjectFiles& operator=(const ProjectFiles&) = delete;
    ProjectFiles(ProjectFiles&&) noexcept;
    ProjectFiles& operator=(ProjectFiles&&) noexcept;
    [[nodiscard]] const std::filesystem::path& root() const noexcept { return root_; }
    [[nodiscard]] std::size_t max_bytes() const noexcept { return max_bytes_; }
    [[nodiscard]] FileSnapshot read(const std::filesystem::path& relative) const;
    // Capture a nonexistent leaf for a checked first save, without making it.
    [[nodiscard]] FileSnapshot inspect(const std::filesystem::path& relative) const;
    [[nodiscard]] FileSnapshot save(const FileSnapshot& original, std::string_view text) const;
    [[nodiscard]] FileSnapshot save(const std::filesystem::path& relative,
                                    const FileSnapshot& original, std::string_view text) const;
    void ensure_directory(const std::filesystem::path& relative) const;
    // Existing process working directory; "." explicitly selects project root.
    [[nodiscard]] std::filesystem::path directory(const std::filesystem::path& relative) const;
    [[nodiscard]] std::filesystem::path absolute(const std::filesystem::path& relative) const;
    struct Write { FileSnapshot original; std::string text; };
    // Design/output batch with recoverable journal. Marker is published last.
    // Pending publication blocks a new batch until explicit recovery is performed.
    [[nodiscard]] std::vector<FileSnapshot> save_batch(const std::vector<Write>& writes,
                                                      const Write& revision_marker) const;
    [[nodiscard]] bool recovery_pending() const;
    // Complete the recorded new revision. Conflicting foreign edits are preserved.
    void recover_batch() const;
    static bool valid_utf8(std::string_view text) noexcept;
private:
    std::filesystem::path root_;
    std::size_t max_bytes_{};
    std::intptr_t native_root_{-1};
};

// File-sized plain-text editing. The original snapshot survives failed saves.
// Histories share the same bounded byte budget; edits exceeding it fail explicitly.
class CodeBuffer {
public:
    explicit CodeBuffer(FileSnapshot original,
                        std::size_t history_bytes = 32 * 1024 * 1024);
    [[nodiscard]] const std::filesystem::path& path() const noexcept { return original_.path; }
    [[nodiscard]] const std::string& text() const noexcept { return text_; }
    [[nodiscard]] const FileSnapshot& original() const noexcept { return original_; }
    [[nodiscard]] bool dirty() const noexcept { return text_ != original_.text; }
    void set_text(std::string text);
    void replace(std::size_t offset, std::size_t count, std::string_view text);
    [[nodiscard]] bool undo();
    [[nodiscard]] bool redo();
    [[nodiscard]] std::size_t find(std::string_view needle, std::size_t from = 0) const noexcept;
    void reload(FileSnapshot snapshot);
    void save(const ProjectFiles& files);
private:
    FileSnapshot original_;
    std::string text_;
    std::vector<std::string> undo_, redo_;
    std::size_t history_limit_{}, history_used_{};
    void retain(std::vector<std::string>& destination, std::string text);
    void clear(std::vector<std::string>& destination) noexcept;
};

} // namespace foundation::editor
