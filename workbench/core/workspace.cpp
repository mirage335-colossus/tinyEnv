#include "workspace.hpp"
#include "json.hpp"
#include "preferences.hpp"
#include "editor/platform/content_digest.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <functional>
#include <limits>
#include <set>
#include <utility>

#if defined(__unix__) && !defined(__EMSCRIPTEN__)
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__linux__)
#include <sys/syscall.h>
#elif defined(__APPLE__)
#include <stdio.h>
#endif
#endif

namespace tinyenv {
namespace {
using foundation::editor::FileError;
using foundation::editor::FileFailure;
using foundation::editor::FileSnapshot;
using foundation::editor::ProjectFiles;
using json::Value;
constexpr std::size_t field_bytes = 1024 * 1024;
constexpr std::size_t list_entries = 4096;
constexpr std::size_t submission_bytes = 64 * 1024;
constexpr std::size_t history_bytes = 8 * 1024 * 1024;

[[noreturn]] void invalid(std::string message) { throw FileError(FileFailure::invalid_path, std::move(message)); }
void text_limit(std::string_view value, std::size_t limit, std::string_view field) {
    if (value.size() > limit) throw FileError(FileFailure::limit, std::string(field) + " exceeds its byte limit");
    if (value.find('\0') != std::string_view::npos || !ProjectFiles::valid_utf8(value))
        throw FileError(FileFailure::encoding, std::string(field) + " must be UTF-8 without NUL");
}
void image_valid(const ImageAttachment& image) {
    text_limit(image.name, 255, "Image name");
    if (image.name.empty() || image.name == "." || image.name == ".." || image.name.find_first_of("/\\:") != std::string::npos)
        invalid("Image names must be ordinary filenames");
    for (const auto ch : image.name) if (static_cast<unsigned char>(ch) < 0x20 || ch == 0x7f)
        invalid("Image names cannot contain control characters");
    if (image.mime_type != "image/png" && image.mime_type != "image/jpeg") invalid("Images must be PNG or JPEG");
    if (!image.bytes || image.bytes > Workspace::maximum_image_bytes)
        throw FileError(FileFailure::limit, "Each image must contain between 1 byte and 4 MiB");
    if (image.sha256.size() != 64 || image.sha256.find_first_not_of("0123456789abcdef") != std::string::npos)
        invalid("Image digest is invalid");
}
void images_valid(const std::vector<ImageAttachment>& images) {
    if (images.size() > Workspace::maximum_images) throw FileError(FileFailure::limit, "Attach at most four images");
    std::size_t total{}; std::set<std::string> identities;
    for (const auto& image : images) {
        image_valid(image);
        if (!identities.insert(image.sha256).second) invalid("An image is attached more than once");
        if (image.bytes > Workspace::maximum_images_bytes - total)
            throw FileError(FileFailure::limit, "Attached images exceed the combined 8 MiB limit");
        total += image.bytes;
    }
}
std::string image_mime(std::string_view bytes) {
    if (bytes.starts_with(std::string_view("\x89PNG\r\n\x1a\n", 8))) return "image/png";
    if (bytes.size() >= 3 && static_cast<unsigned char>(bytes[0]) == 0xff &&
        static_cast<unsigned char>(bytes[1]) == 0xd8 && static_cast<unsigned char>(bytes[2]) == 0xff) return "image/jpeg";
    throw FileError(FileFailure::encoding, "The selected image does not have a PNG or JPEG signature");
}
std::string image_extension_mime(const std::filesystem::path& path) {
    auto extension = path.extension().string();
    for (auto& ch : extension) if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    if (extension == ".png") return "image/png";
    if (extension == ".jpg" || extension == ".jpeg") return "image/jpeg";
    invalid("Select a .png, .jpg or .jpeg image");
}
std::string encode_base64(std::string_view bytes) {
    constexpr std::string_view alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string encoded; encoded.reserve((bytes.size() + 2) / 3 * 4);
    for (std::size_t offset = 0; offset < bytes.size(); offset += 3) {
        const auto a = static_cast<unsigned char>(bytes[offset]);
        const auto b = offset + 1 < bytes.size() ? static_cast<unsigned char>(bytes[offset + 1]) : 0;
        const auto c = offset + 2 < bytes.size() ? static_cast<unsigned char>(bytes[offset + 2]) : 0;
        encoded += alphabet[a >> 2]; encoded += alphabet[((a & 3) << 4) | (b >> 4)];
        encoded += offset + 1 < bytes.size() ? alphabet[((b & 15) << 2) | (c >> 6)] : '=';
        encoded += offset + 2 < bytes.size() ? alphabet[c & 63] : '=';
    }
    return encoded;
}
std::string decode_image_base64(std::string_view encoded, std::size_t expected) {
    if (encoded.size() != (expected + 2) / 3 * 4)
        throw FileError(FileFailure::conflict, "Retained image size changed; attach it again");
    constexpr std::string_view alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string bytes; bytes.reserve(expected);
    for (std::size_t offset = 0; offset < encoded.size(); offset += 4) {
        unsigned values[4]{};
        for (std::size_t i = 0; i < 4; ++i) {
            const auto ch = encoded[offset + i];
            if (ch == '=' && i >= 2 && offset + 4 == encoded.size()) continue;
            const auto position = alphabet.find(ch);
            if (position == std::string_view::npos)
                throw FileError(FileFailure::conflict, "Retained image encoding changed; attach it again");
            values[i] = static_cast<unsigned>(position);
        }
        bytes += static_cast<char>((values[0] << 2) | (values[1] >> 4));
        if (encoded[offset + 2] != '=') bytes += static_cast<char>((values[1] << 4) | (values[2] >> 2));
        if (encoded[offset + 3] != '=') bytes += static_cast<char>((values[2] << 6) | values[3]);
    }
    if (bytes.size() != expected || encode_base64(bytes) != encoded)
        throw FileError(FileFailure::conflict, "Retained image encoding changed; attach it again");
    return bytes;
}
std::filesystem::path image_store_path(const ImageAttachment& image) {
    image_valid(image);
    return std::filesystem::path(".tinyenv/images") / (image.sha256 + ".b64");
}
void submission_valid(const SubmittedMessage& value) {
    text_limit(value.prompt, submission_bytes, "Previous message");
    images_valid(value.images);
    if (value.images.empty() && (value.prompt.empty() || value.prompt.find_first_not_of(" \t\r\n") == std::string::npos))
        invalid("Previous message must not be empty");
    if (value.history_bytes > history_bytes)
        throw FileError(FileFailure::limit, "Previous message history exceeds its byte limit");
    if (value.history_sha256.size() != 64 || value.history_sha256.find_first_not_of("0123456789abcdef") != std::string::npos)
        invalid("Previous message history digest is invalid");
}
void relative_path(const std::filesystem::path& path, bool allow_root = false) {
    if (allow_root && path == ".") return;
    if (path.empty() || path.is_absolute() || path.has_root_name() || path.has_root_directory()) invalid("Use a project-relative path");
    for (const auto& component : path) {
        const auto part = component.generic_string();
        if (part.empty() || part == "." || part == ".." || part.find_first_of("\\:") != std::string::npos) invalid("Invalid project path component");
        text_limit(part, 255, "Path component");
    }
    text_limit(path.generic_string(), 4096, "Path");
}
void chat_path(const std::filesystem::path& path) {
    relative_path(path);
    if (!Workspace::is_chat_path(path)) invalid("Chats must use the .chat.md filename suffix");
    for (const auto& part : path) {
        auto name = part.string();
        for (auto& ch : name) if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
        if (name == ".tinyenv" || name == ".git") invalid("Chats cannot be stored inside reserved state directories");
    }
}
std::size_t scan_limit(std::size_t maximum) {
    if (!maximum || maximum > Workspace::maximum_scan_entries) throw FileError(FileFailure::limit, "Scan budget must be between 1 and 100000 entries");
    return maximum;
}
bool secret_name(std::string_view name) {
    std::string lower(name);
    for (auto& ch : lower) if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    return lower == ".ssh" || lower == ".aws" || lower == ".kube" || lower == ".gnupg" || lower == "credentials" ||
           lower == "credentials.json" || lower == "secrets" || lower == "secrets.json" || lower == "id_rsa" ||
           lower == "id_ed25519" || lower == "id_dsa" || lower == "id_ecdsa" || lower.starts_with(".env") ||
           lower.ends_with(".pem") || lower.ends_with(".key");
}
bool private_name(std::string_view name) {
    return secret_name(name) || name == ".git" || name == ".tinyenv" || name == ".codex" || name == ".agents" ||
           name == ".agent-work" || name == "node_modules" || name == ".venv" || name == "build";
}
void mutable_path(const std::filesystem::path& path) {
    relative_path(path);
    for (const auto& component : path) {
        auto name = component.string();
        for (auto& ch : name) if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
        if (secret_name(name) || name == ".git" || name == ".tinyenv" || name == ".codex" || name == ".agents" ||
            name == ".agent-work" || name.starts_with(".foundation-editor-"))
            invalid("File operations cannot change private or application-state paths");
    }
}
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
struct Descriptor {
    int value{-1};
    explicit Descriptor(int fd = -1) : value(fd) {}
    ~Descriptor() { if (value >= 0) ::close(value); }
    Descriptor(const Descriptor&) = delete;
    Descriptor& operator=(const Descriptor&) = delete;
    Descriptor(Descriptor&& other) noexcept : value(std::exchange(other.value, -1)) {}
    Descriptor& operator=(Descriptor&& other) noexcept {
        if (this != &other) { if (value >= 0) ::close(value); value = std::exchange(other.value, -1); }
        return *this;
    }
};
[[noreturn]] void operation_error(std::string_view operation, int error = errno) {
    auto code = FileFailure::io;
    if (error == ENOENT) code = FileFailure::missing;
    else if (error == EACCES || error == EPERM || error == EROFS) code = FileFailure::permission;
    else if (error == ELOOP || error == ENOTDIR || error == EINVAL) code = FileFailure::invalid_path;
    else if (error == EEXIST || error == ENOTEMPTY) code = FileFailure::conflict;
    else if (error == ENOSYS || error == ENOTSUP) code = FileFailure::unavailable;
    throw FileError(code, std::string(operation) + ": " + std::strerror(error));
}
struct EntryParent { Descriptor directory; std::string leaf; };
EntryParent entry_parent(std::intptr_t root, const std::filesystem::path& path) {
    relative_path(path);
    Descriptor current(::fcntl(static_cast<int>(root), F_DUPFD_CLOEXEC, 0));
    if (current.value < 0) operation_error("Cannot pin file-operation root");
    for (const auto& part : path.parent_path()) {
        Descriptor next(::openat(current.value, part.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
        if (next.value < 0) operation_error("Cannot pin file-operation parent");
        current = std::move(next);
    }
    return {std::move(current), path.filename().string()};
}
struct stat entry_stat(const EntryParent& parent) {
    struct stat result{};
    if (::fstatat(parent.directory.value, parent.leaf.c_str(), &result, AT_SYMLINK_NOFOLLOW) != 0)
        operation_error("Cannot inspect file-operation entry");
    if (!S_ISREG(result.st_mode) && !S_ISDIR(result.st_mode))
        invalid("File operations require ordinary files or directories, without symlinks");
    return result;
}
void absent_entry(const EntryParent& parent) {
    struct stat entry{};
    if (::fstatat(parent.directory.value, parent.leaf.c_str(), &entry, AT_SYMLINK_NOFOLLOW) == 0)
        throw FileError(FileFailure::conflict, "Destination already exists");
    if (errno != ENOENT) operation_error("Cannot inspect file-operation destination");
}
void writable_parent(const EntryParent& parent) {
    struct stat directory{};
    if (::fstat(parent.directory.value, &directory) != 0) operation_error("Cannot inspect copy directory");
    // Match ProjectFiles' explicit read-only-directory guard even when the
    // current process could otherwise bypass the ordinary permission bits.
    if (!(directory.st_mode & 0222)) throw FileError(FileFailure::permission, "Copy destination directory is read-only");
}
void unchanged_entry(const EntryParent& parent, const struct stat& expected) {
    const auto actual = entry_stat(parent);
#if defined(__APPLE__)
    const bool time_equal = actual.st_mtimespec.tv_sec == expected.st_mtimespec.tv_sec && actual.st_mtimespec.tv_nsec == expected.st_mtimespec.tv_nsec;
#else
    const bool time_equal = actual.st_mtim.tv_sec == expected.st_mtim.tv_sec && actual.st_mtim.tv_nsec == expected.st_mtim.tv_nsec;
#endif
    if (actual.st_dev != expected.st_dev || actual.st_ino != expected.st_ino || actual.st_mode != expected.st_mode ||
        actual.st_size != expected.st_size || !time_equal)
        throw FileError(FileFailure::conflict, "Entry changed during the file operation; refresh before retrying");
}
bool same_image_stat(const struct stat& a, const struct stat& b) {
#if defined(__APPLE__)
    const bool timestamps = a.st_mtimespec.tv_sec == b.st_mtimespec.tv_sec && a.st_mtimespec.tv_nsec == b.st_mtimespec.tv_nsec &&
        a.st_ctimespec.tv_sec == b.st_ctimespec.tv_sec && a.st_ctimespec.tv_nsec == b.st_ctimespec.tv_nsec;
#else
    const bool timestamps = a.st_mtim.tv_sec == b.st_mtim.tv_sec && a.st_mtim.tv_nsec == b.st_mtim.tv_nsec &&
        a.st_ctim.tv_sec == b.st_ctim.tv_sec && a.st_ctim.tv_nsec == b.st_ctim.tv_nsec;
#endif
    return a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_mode == b.st_mode && a.st_size == b.st_size && timestamps;
}
std::string read_image_source(const EntryParent& parent) {
    Descriptor source(::openat(parent.directory.value, parent.leaf.c_str(), O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC));
    if (source.value < 0) operation_error("Cannot open selected image");
    struct stat before{}, after{}, named{};
    if (::fstat(source.value, &before) != 0) operation_error("Cannot inspect selected image");
    if (!S_ISREG(before.st_mode)) invalid("Select an ordinary image file without symlinks");
    if (!(before.st_mode & 0444)) throw FileError(FileFailure::permission, "The selected image is not readable");
    if (before.st_size <= 0 || static_cast<std::uint64_t>(before.st_size) > Workspace::maximum_image_bytes)
        throw FileError(FileFailure::limit, "Each image must contain between 1 byte and 4 MiB");
    std::string bytes; bytes.reserve(static_cast<std::size_t>(before.st_size)); char chunk[16384];
    for (;;) {
        const auto count = ::read(source.value, chunk, sizeof chunk);
        if (!count) break;
        if (count < 0) { if (errno == EINTR) continue; operation_error("Cannot read selected image"); }
        if (static_cast<std::size_t>(count) > Workspace::maximum_image_bytes - bytes.size())
            throw FileError(FileFailure::limit, "The selected image grew beyond 4 MiB");
        bytes.append(chunk, static_cast<std::size_t>(count));
    }
    if (::fstat(source.value, &after) != 0 ||
        ::fstatat(parent.directory.value, parent.leaf.c_str(), &named, AT_SYMLINK_NOFOLLOW) != 0)
        operation_error("Cannot recheck selected image");
    if (!same_image_stat(before, after) || !same_image_stat(before, named) ||
        bytes.size() != static_cast<std::size_t>(after.st_size))
        throw FileError(FileFailure::conflict, "The selected image changed while being read; select it again");
    return bytes;
}
void rename_without_replace(const EntryParent& source, const EntryParent& destination) {
#if defined(__linux__) && defined(SYS_renameat2)
    // RENAME_NOREPLACE is 1 in the Linux syscall ABI. Never emulate it with a
    // check followed by renameat(), which could overwrite an intervening entry.
    if (::syscall(SYS_renameat2, source.directory.value, source.leaf.c_str(), destination.directory.value, destination.leaf.c_str(), 1u) != 0)
        operation_error("Cannot rename entry without replacement");
#elif defined(__APPLE__) && defined(RENAME_EXCL)
    if (::renameatx_np(source.directory.value, source.leaf.c_str(), destination.directory.value, destination.leaf.c_str(), RENAME_EXCL) != 0)
        operation_error("Cannot rename entry without replacement");
#else
    (void)source; (void)destination;
    throw FileError(FileFailure::unavailable, "This platform lacks qualified no-replace entry renaming");
#endif
}
void remove_checked(const EntryParent& parent, const struct stat& expected) {
    unchanged_entry(parent, expected);
    // The kernel's rmdir semantics are the sole directory-removal operation.
    if (::unlinkat(parent.directory.value, parent.leaf.c_str(), S_ISDIR(expected.st_mode) ? AT_REMOVEDIR : 0) != 0)
        operation_error(S_ISDIR(expected.st_mode) ? "Cannot remove directory (it must be empty)" : "Cannot remove file");
}
#endif
std::filesystem::path child_path(const std::filesystem::path& directory, const std::filesystem::path& name) {
    return directory == "." ? name : directory / name;
}
std::filesystem::path companion_path(const std::filesystem::path& path) {
    const auto name = path.filename().string();
    const auto leaf = name.size() <= 244 ? name + ".state.json" : foundation::editor::detail::content_digest(name) + ".state.json";
    return path.parent_path() / ".tinyenv" / leaf;
}
bool legacy_markdown(const std::filesystem::path& path) {
    auto extension = path.extension().string();
    for (auto& ch : extension) if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    return extension == ".md" || extension == ".markdown";
}
std::uint64_t add_bytes(std::uint64_t a, std::uint64_t b) {
    if (b > std::numeric_limits<std::uint64_t>::max() - a) throw FileError(FileFailure::limit, "Disk byte count overflow");
    return a + b;
}
void same(const FileSnapshot& expected, const FileSnapshot& actual) {
    if (expected.path != actual.path || expected.identity != actual.identity || expected.text != actual.text)
        throw FileError(FileFailure::conflict, "File changed externally; reload before saving");
}
std::string read_string(const Value& value, std::string_view key, std::string fallback = {}) {
    const auto* field = value.find(key);
    return field ? field->string() : std::move(fallback);
}
bool read_bool(const Value& value, std::string_view key, bool fallback = false) {
    const auto* field = value.find(key); return field ? field->boolean() : fallback;
}
double read_number(const Value& value, std::string_view key, double fallback) {
    const auto* field = value.find(key); return field ? field->number() : fallback;
}
int read_integer(const Value& value, std::string_view key, int fallback) {
    const auto result = read_number(value, key, static_cast<double>(fallback));
    if (!std::isfinite(result) || std::floor(result) != result || result < std::numeric_limits<int>::min() || result > std::numeric_limits<int>::max())
        throw std::runtime_error("State field " + std::string(key) + " must be an integer");
    return static_cast<int>(result);
}
void toggles_valid(const std::vector<PathToggle>& paths) {
    if (paths.size() > list_entries) throw FileError(FileFailure::limit, "Selector list exceeds 4096 paths");
    std::set<std::string> seen;
    for (const auto& entry : paths) {
        text_limit(entry.path, 4096, "Selector path");
        if (entry.path.empty() || !seen.insert(entry.path).second) invalid("Selector paths must be nonempty and unique within their list");
    }
}
void sources_valid(const Value& sources) {
    if (sources.array().size() > list_entries) throw FileError(FileFailure::limit, "Sources metadata exceeds 4096 entries");
    static const std::set<std::string> source_fields{"id", "title", "url", "path", "kind", "query", "metadata"};
    static const std::set<std::string> metadata_fields{
        "untrusted", "instruction_authority", "no_links_followed", "sha256", "bytes_loaded", "truncated", "source_path",
        "source_sha256", "index_sha256", "keywords", "ranked", "local_path", "article", "index_path", "query", "search_excerpt", "search_provider"};
    for (const auto& source : sources.array()) {
        for (const auto& [key, field] : source.object()) {
            if (!source_fields.contains(key)) invalid("Sources persist provenance metadata only; unsupported field: " + key);
            if (key != "metadata") { text_limit(field.string(), 4096, "Source metadata field"); continue; }
            for (const auto& [name, value] : field.object()) {
                if (!metadata_fields.contains(name)) invalid("Unsupported source provenance field: " + name);
                if (name == "keywords") {
                    if (value.array().size() > 128) throw FileError(FileFailure::limit, "Source keywords exceed 128 entries");
                    for (const auto& keyword : value.array()) text_limit(keyword.string(), 512, "Source keyword");
                } else if (const auto* text = std::get_if<std::string>(&value.data)) text_limit(*text, 4096, "Source metadata field");
                else if (!std::holds_alternative<bool>(value.data) && !std::holds_alternative<double>(value.data))
                    invalid("Source metadata must contain scalar provenance fields");
            }
        }
    }
}
void state_valid(const ChatState& state, const ProjectFiles& files) {
    if (state.submission) submission_valid(*state.submission);
    images_valid(state.draft_images);
    text_limit(state.draft, field_bytes, "Draft"); text_limit(state.pseudocode, field_bytes, "Pseudocode");
    text_limit(state.sources_json, field_bytes, "Sources metadata");
    const auto sources = json::parse(state.sources_json, field_bytes);
    sources_valid(sources);
    (void)json::stringify(sources, field_bytes);
    for (const auto* field : {&state.left_tab, &state.center_tab, &state.right_tab}) text_limit(*field, 128, "Pane selection");
    toggles_valid(state.selector.scribbles); toggles_valid(state.selector.refs); toggles_valid(state.selector.tools);
    const auto& selector = state.selector;
    if (selector.context_max_kib < 1 || selector.context_max_kib > 16384)
        throw FileError(FileFailure::limit, "Context limit requires 1..16384 KiB");
    if (selector.research_max_queries < 1 || selector.research_max_queries > 1000 || selector.research_max_results < 1 || selector.research_max_results > 3000)
        throw FileError(FileFailure::limit, "Research limits require 1..1000 queries and 1..3000 results");
    if (selector.research_source != "web" && selector.research_source != "wikipedia" && selector.research_source != "stackoverflow" && selector.research_source != "local" && selector.research_source != "kiwix")
        invalid("Research source must be web, wikipedia, stackoverflow, local or kiwix");
    text_limit(selector.kiwix_index, 4096, "Kiwix index path");
    relative_path(state.cwd, true); (void)files.directory(state.cwd);
    validate_ai_settings(state.ai);
}
Value toggles_json(const std::vector<PathToggle>& paths) {
    Value::Array result; result.reserve(paths.size());
    for (const auto& entry : paths) result.emplace_back(Value::Object{{"path", entry.path}, {"enabled", entry.enabled}});
    return result;
}
std::vector<PathToggle> read_toggles(const Value& value, std::string_view key) {
    std::vector<PathToggle> result;
    if (const auto* field = value.find(key)) {
        if (field->array().size() > list_entries) throw FileError(FileFailure::limit, "Selector list exceeds 4096 paths");
        for (const auto& item : field->array()) {
            (void)item.object(); result.push_back({read_string(item, "path"), read_bool(item, "enabled", true)});
        }
    }
    return result;
}
Value images_json(const std::vector<ImageAttachment>& images) {
    Value::Array values;
    for (const auto& image : images) values.emplace_back(Value::Object{
        {"name", image.name}, {"mime_type", image.mime_type}, {"sha256", image.sha256}, {"bytes", image.bytes}});
    return values;
}
std::vector<ImageAttachment> read_images(const Value& value) {
    if (value.array().size() > Workspace::maximum_images) throw FileError(FileFailure::limit, "Attach at most four images");
    std::vector<ImageAttachment> images;
    static const std::set<std::string> names{"name", "mime_type", "sha256", "bytes"};
    for (const auto& saved : value.array()) {
        if (saved.object().size() != names.size()) invalid("Invalid image attachment record");
        for (const auto& [key, field] : saved.object()) { (void)field; if (!names.contains(key)) invalid("Invalid image attachment field"); }
        const auto bytes = read_integer(saved, "bytes", -1);
        if (bytes < 1) throw FileError(FileFailure::limit, "Image byte length must be positive");
        images.push_back({read_string(saved, "name"), read_string(saved, "mime_type"), read_string(saved, "sha256"), static_cast<std::size_t>(bytes)});
    }
    images_valid(images);
    return images;
}
Value state_json(const ChatState& state) {
    Value::Object result{
        {"version", 1}, {"cwd", state.cwd}, {"draft", state.draft}, {"pseudocode", state.pseudocode},
        {"sources", json::parse(state.sources_json, field_bytes)},
        {"left_tab", state.left_tab}, {"center_tab", state.center_tab}, {"right_tab", state.right_tab},
        {"agentic", state.agentic}, {"split_chat", state.split_chat},
        {"selector", Value::Object{{"deep_research", state.selector.deep_research}, {"scribbles", toggles_json(state.selector.scribbles)},
            {"refs", toggles_json(state.selector.refs)}, {"tools", toggles_json(state.selector.tools)},
            {"research_max_queries", state.selector.research_max_queries}, {"research_max_results", state.selector.research_max_results},
            {"research_source", state.selector.research_source}, {"kiwix_index", state.selector.kiwix_index}, {"context_max_kib", state.selector.context_max_kib}}},
        {"ai_configured", state.ai_configured}, {"ai", ai_settings_json(state.ai)}
    };
    if (!state.draft_images.empty()) result["draft_images"] = images_json(state.draft_images);
    if (state.submission) {
        const auto& value = *state.submission;
        result["submission"] = Value::Object{{"prompt", value.prompt}, {"agentic", value.agentic},
            {"history_bytes", value.history_bytes}, {"history_sha256", value.history_sha256}};
        if (!value.images.empty()) result["submission"].object()["images"] = images_json(value.images);
    }
    return result;
}
ChatState read_state(std::string_view bytes) {
    const auto value = json::parse(bytes); (void)value.object();
    if (read_integer(value, "version", 0) != 1) throw std::runtime_error("Unsupported chat state version");
    ChatState state;
    if (const auto* images = value.find("draft_images")) state.draft_images = read_images(*images);
    if (const auto* saved = value.find("submission")) {
        static const std::set<std::string> names{"prompt", "agentic", "history_bytes", "history_sha256", "images"};
        (void)saved->object();
        for (const auto* name : {"prompt", "agentic", "history_bytes", "history_sha256"})
            if (!saved->find(name)) invalid("Incomplete previous-message record");
        for (const auto& [key, field] : saved->object()) { (void)field; if (!names.contains(key)) invalid("Invalid previous-message field"); }
        const auto count = read_integer(*saved, "history_bytes", -1);
        if (count < 0) invalid("Previous message history length is invalid");
        state.submission = SubmittedMessage{read_string(*saved, "prompt"), read_bool(*saved, "agentic"),
            static_cast<std::size_t>(count), read_string(*saved, "history_sha256"), {}};
        if (const auto* images = saved->find("images")) state.submission->images = read_images(*images);
        submission_valid(*state.submission);
    }
    if (const auto* sources = value.find("sources")) { (void)sources->array(); state.sources_json = json::stringify(*sources, field_bytes); }
    state.cwd = read_string(value, "cwd", state.cwd); state.draft = read_string(value, "draft"); state.pseudocode = read_string(value, "pseudocode");
    state.left_tab = read_string(value, "left_tab", state.left_tab); state.center_tab = read_string(value, "center_tab", state.center_tab);
    state.right_tab = read_string(value, "right_tab", state.right_tab); state.agentic = read_bool(value, "agentic"); state.split_chat = read_bool(value, "split_chat");
    if (const auto* selector = value.find("selector")) {
        (void)selector->object(); state.selector.deep_research = read_bool(*selector, "deep_research");
        state.selector.scribbles = read_toggles(*selector, "scribbles"); state.selector.refs = read_toggles(*selector, "refs"); state.selector.tools = read_toggles(*selector, "tools");
        // Old states with an empty selector object used the previous curated
        // defaults. New states always write their selected source and budgets.
        state.selector.research_max_queries = read_integer(*selector, "research_max_queries", 2);
        state.selector.research_max_results = read_integer(*selector, "research_max_results", 3);
        state.selector.research_source = read_string(*selector, "research_source", "wikipedia");
        state.selector.kiwix_index = read_string(*selector, "kiwix_index");
        state.selector.context_max_kib = read_integer(*selector, "context_max_kib", state.selector.context_max_kib);
    }
    if (const auto* ai = value.find("ai")) {
        state.ai = read_ai_settings(*ai);
        state.ai_configured = !state.ai.provider.empty() && !state.ai.model.empty();
    }
    state.ai_configured = read_bool(value, "ai_configured", state.ai_configured);
    return state;
}
SnippetKind snippet_kind(std::string_view kind) {
    if (kind == "prompts" || kind == "Prompts") return SnippetKind::prompts;
    if (kind == "pseudocode" || kind == "Pseudocode") return SnippetKind::pseudocode;
    invalid("Unknown snippet collection");
}
std::filesystem::path snippet_path(SnippetKind kind) {
    switch (kind) {
    case SnippetKind::prompts: return ".tinyenv/prompts.json";
    case SnippetKind::pseudocode: return ".tinyenv/pseudocode.json";
    }
    invalid("Unknown snippet collection");
}
void snippets_valid(const std::vector<Snippet>& snippets) {
    if (snippets.size() > list_entries) throw FileError(FileFailure::limit, "Snippet collection exceeds 4096 entries");
    std::set<std::string> ids;
    for (const auto& snippet : snippets) {
        text_limit(snippet.id, 256, "Snippet ID"); text_limit(snippet.title, 4096, "Snippet title"); text_limit(snippet.text, field_bytes, "Snippet text");
        if (snippet.id.empty() || !ids.insert(snippet.id).second) invalid("Snippet IDs must be nonempty and unique");
    }
}
} // namespace

SubmittedMessage make_submission(std::string_view prompt, bool agentic, std::string_view history, const std::vector<ImageAttachment>& images) {
    text_limit(history, history_bytes, "Previous message history");
    SubmittedMessage result{std::string(prompt), agentic, history.size(),
        foundation::editor::detail::content_digest(history), images};
    submission_valid(result);
    return result;
}

std::string submission_history(const Chat& chat) {
    if (!chat.state.submission) invalid("No previous submitted message is available to retry");
    const auto& saved = *chat.state.submission;
    submission_valid(saved);
    const auto transcript = std::string_view(chat.text);
    const auto frame = "\n## User\n\n" + saved.prompt + "\n";
    if (saved.history_bytes > transcript.size() ||
        !transcript.substr(saved.history_bytes).starts_with(frame) ||
        foundation::editor::detail::content_digest(transcript.substr(0, saved.history_bytes)) != saved.history_sha256)
        throw FileError(FileFailure::conflict, "The previous message or its earlier history changed; send a new message to continue");
    return std::string(transcript.substr(0, saved.history_bytes));
}

Workspace::Workspace(std::filesystem::path root) : files_(std::filesystem::absolute(std::move(root))) {
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    operations_root_ = ::open(files_.root().c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (operations_root_ < 0) operation_error("Cannot pin workspace file-operation root");
#endif
}

Workspace::~Workspace() {
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    if (operations_root_ >= 0) ::close(static_cast<int>(operations_root_));
#endif
}

bool Workspace::is_chat_path(const std::filesystem::path& path) {
    auto name = path.filename().string();
    for (auto& ch : name) if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    return name.ends_with(".chat.md");
}

std::filesystem::path Workspace::state_path(const std::filesystem::path& chat) {
    chat_path(chat);
    // Preserve normal readable filenames while supporting the filesystem's full
    // 255-byte leaf length without creating an overlong sidecar destination.
    return companion_path(chat);
}

FileSnapshot Workspace::inspect_optional(const std::filesystem::path& path) const {
    relative_path(path);
    try { return files_.inspect(path); }
    catch (const FileError& error) {
        if (error.code() != FileFailure::missing) throw;
        return FileSnapshot{path, {}, {}};
    }
}

Chat Workspace::open_chat(const std::filesystem::path& path) const {
    chat_path(path);
    Chat chat; chat.path = path; chat.original = files_.read(path); chat.text = chat.original.text;
    text_limit(chat.text, files_.max_bytes(), "Chat");
    chat.state_original = inspect_optional(state_path(path));
    if (chat.state_original.identity.exists) chat.state = read_state(chat.state_original.text);
    else if (!path.parent_path().empty()) chat.state.cwd = path.parent_path().generic_string();
    // Moving a closed chat's directory preserves its adjacent sidecar, but the
    // saved project-relative terminal start may no longer exist. Recover only
    // an ordinary missing directory; unsafe, symlink and permission failures
    // remain errors. The checked sidecar snapshot still preserves its bytes.
    relative_path(chat.state.cwd, true);
    try { (void)files_.directory(chat.state.cwd); }
    catch (const FileError& error) {
        if (error.code() != FileFailure::missing) throw;
        chat.state.cwd = path.parent_path().empty() ? "." : path.parent_path().generic_string();
    }
    state_valid(chat.state, files_);
    return chat;
}

Chat Workspace::new_chat(const std::filesystem::path& path, std::string_view text) {
    chat_path(path); text_limit(text, files_.max_bytes(), "Chat");
    if (!path.parent_path().empty()) files_.ensure_directory(path.parent_path());
    const auto original = files_.inspect(path);
    if (original.identity.exists) throw FileError(FileFailure::conflict, "Chat file already exists");
    if (inspect_optional(state_path(path)).identity.exists)
        throw FileError(FileFailure::conflict, "State for this chat name already exists; choose a different name");
    (void)files_.save(original, text);
    return open_chat(path);
}

void Workspace::save(Chat& chat) {
    chat_path(chat.path); state_valid(chat.state, files_); text_limit(chat.text, files_.max_bytes(), "Chat");
    if (chat.original.path != chat.path || chat.state_original.path != state_path(chat.path)) invalid("Chat snapshots do not belong to this chat");
    const auto state_bytes = json::stringify(state_json(chat.state)) + "\n";
    same(chat.original, files_.inspect(chat.path)); same(chat.state_original, inspect_optional(chat.state_original.path));
    files_.ensure_directory(chat.state_original.path.parent_path());
    if (chat.text != chat.original.text) chat.original = files_.save(chat.original, chat.text);
    if (!chat.state_original.identity.exists || state_bytes != chat.state_original.text) chat.state_original = files_.save(chat.state_original, state_bytes);
}

void Workspace::save_state(Chat& chat) {
    chat_path(chat.path); state_valid(chat.state, files_);
    if (chat.original.path != chat.path || chat.state_original.path != state_path(chat.path)) invalid("Chat snapshots do not belong to this chat");
    const auto bytes = json::stringify(state_json(chat.state)) + "\n";
    same(chat.original, files_.inspect(chat.path)); same(chat.state_original, inspect_optional(chat.state_original.path));
    files_.ensure_directory(chat.state_original.path.parent_path());
    if (!chat.state_original.identity.exists || bytes != chat.state_original.text) chat.state_original = files_.save(chat.state_original, bytes);
}

ImageAttachment Workspace::attach_image(const std::filesystem::path& path) {
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    const auto source_path = path.is_absolute() ? path.relative_path() : path;
    mutable_path(source_path);
    const auto expected_mime = image_extension_mime(path);
    // Check display metadata before reading or publishing any source bytes.
    ImageAttachment image{path.filename().string(), expected_mime, std::string(64, '0'), 1};
    image_valid(image);
    Descriptor filesystem_root;
    auto source_root = operations_root_;
    if (path.is_absolute()) {
        filesystem_root = Descriptor(::open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
        if (filesystem_root.value < 0) operation_error("Cannot pin local image filesystem root");
        source_root = filesystem_root.value;
    }
    const auto parent = entry_parent(source_root, source_path);
    const auto bytes = read_image_source(parent);
    if (image_mime(bytes) != expected_mime)
        throw FileError(FileFailure::encoding, "The selected image signature does not match its filename extension");
    image.bytes = bytes.size(); image.sha256 = foundation::editor::detail::content_digest(bytes);
    const auto stored_path = image_store_path(image);
    const auto encoded = encode_base64(bytes);
    files_.ensure_directory(stored_path.parent_path());
    const auto stored = files_.inspect(stored_path);
    if (stored.identity.exists) {
        if (stored.text != encoded) throw FileError(FileFailure::conflict, "The retained image copy changed; preserve it and resolve the conflict");
    } else (void)files_.save(stored, encoded);
    return image;
#else
    (void)path;
    throw FileError(FileFailure::unavailable, "Local image attachment needs qualified no-follow filesystem operations on this platform");
#endif
}

json::Value::Array Workspace::image_payloads(const std::vector<ImageAttachment>& images) const {
    images_valid(images);
    json::Value::Array values;
    for (const auto& image : images) {
        const auto stored = files_.read(image_store_path(image));
        const auto bytes = decode_image_base64(stored.text, image.bytes);
        if (foundation::editor::detail::content_digest(bytes) != image.sha256 || image_mime(bytes) != image.mime_type)
            throw FileError(FileFailure::conflict, "The retained image bytes or type changed; attach the image again");
        values.emplace_back(Value::Object{{"mime_type", image.mime_type}, {"data_base64", stored.text}});
    }
    return values;
}

void Workspace::create_file(const std::filesystem::path& path, std::string_view text) {
    mutable_path(path);
    // A file-manager action never implicitly creates missing parents.
    (void)files_.directory(path.parent_path().empty() ? std::filesystem::path(".") : path.parent_path());
    if (is_chat_path(path)) { (void)new_chat(path, text); return; }
    text_limit(text, files_.max_bytes(), "New file");
    const auto original = files_.inspect(path);
    if (original.identity.exists) throw FileError(FileFailure::conflict, "Destination already exists");
    (void)files_.save(original, text);
}

void Workspace::create_directory(const std::filesystem::path& path) {
    mutable_path(path);
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    const auto parent = entry_parent(operations_root_, path);
    if (::mkdirat(parent.directory.value, parent.leaf.c_str(), 0700) != 0)
        operation_error("Cannot create directory");
#else
    throw FileError(FileFailure::unavailable, "Qualified file-manager directory creation is unavailable on this platform");
#endif
}

void Workspace::copy_entry(const std::filesystem::path& source, const std::filesystem::path& destination) {
    mutable_path(source); mutable_path(destination);
    if (source == destination) throw FileError(FileFailure::conflict, "Choose a different destination name");
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    const auto from = entry_parent(operations_root_, source), to = entry_parent(operations_root_, destination);
    const auto entry = entry_stat(from);
    if (!S_ISREG(entry.st_mode)) invalid("Copy requires an ordinary file; directories cannot be copied");
    absent_entry(to); writable_parent(to);
    const bool source_chat = is_chat_path(source), destination_chat = is_chat_path(destination);
    if (source_chat && !destination_chat) invalid("A chat copy must retain the .chat.md suffix");
    FileSnapshot original, state;
    if (source_chat) {
        // Opening validates saved chat state before any destination publication,
        // while retaining the exact saved text/state rather than a live draft.
        const auto chat = open_chat(source);
        original = chat.original; state = chat.state_original;
    } else original = files_.read(source);
    text_limit(original.text, files_.max_bytes(), destination_chat ? "Chat" : "File");
    const auto target = files_.inspect(destination);
    if (target.identity.exists) throw FileError(FileFailure::conflict, "Destination already exists");
    FileSnapshot state_target;
    if (destination_chat) {
        state_target = inspect_optional(state_path(destination));
        if (state_target.identity.exists)
            throw FileError(FileFailure::conflict, "Companion state for the destination chat already exists");
    }
    if (state.identity.exists) {
        try { writable_parent(entry_parent(operations_root_, state_target.path)); }
        catch (const FileError& error) { if (error.code() != FileFailure::missing) throw; }
    }
    // Every path, source byte and sidecar validation above precedes creation.
    // As with chat Save, the two publications are independent transactions.
    if (state.identity.exists) files_.ensure_directory(state_target.path.parent_path());
    if (state.identity.exists) same(state, files_.inspect(state.path));
    same(original, files_.inspect(source)); unchanged_entry(from, entry);
    (void)files_.save(target, original.text);
    if (!state.identity.exists) return;
    try {
        same(state, files_.inspect(state.path));
        (void)files_.save(state_target, state.text);
    } catch (const std::exception& failure) {
        throw FileError(FileFailure::io, "Chat copied to " + destination.generic_string() +
            "; companion state publication could not be confirmed at " + state_target.path.generic_string() +
            ". This copy did not modify the source chat or state. Preserve and inspect the copy before reopening: " + failure.what());
    }
#else
    throw FileError(FileFailure::unavailable, "Qualified file-manager copying is unavailable on this platform");
#endif
}

void Workspace::rename_entry(const std::filesystem::path& source, const std::filesystem::path& destination) {
    mutable_path(source); mutable_path(destination);
    if (source == destination) throw FileError(FileFailure::conflict, "Choose a different destination name");
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    const auto from = entry_parent(operations_root_, source), to = entry_parent(operations_root_, destination);
    const auto original = entry_stat(from); absent_entry(to);
    if (S_ISDIR(original.st_mode)) {
        const auto below = destination.lexically_relative(source);
        if (!below.empty() && *below.begin() != "..") invalid("A directory cannot be moved inside itself");
    }
    const bool source_chat = S_ISREG(original.st_mode) && is_chat_path(source);
    const bool destination_chat = S_ISREG(original.st_mode) && is_chat_path(destination);
    if (source_chat && !destination_chat) invalid("A chat rename must retain the .chat.md suffix");
    FileSnapshot state;
    if (source_chat || (destination_chat && legacy_markdown(source))) {
        state = inspect_optional(companion_path(source));
        // An explicit legacy .md -> .chat.md rename can migrate its genuine
        // old state; arbitrary same-named sidecars are not adopted as settings.
        if (!source_chat && state.identity.exists) state_valid(read_state(state.text), files_);
    }
    if (destination_chat && inspect_optional(state_path(destination)).identity.exists)
        throw FileError(FileFailure::conflict, "Companion state for the destination chat already exists");
    if (!state.identity.exists) {
        unchanged_entry(from, original); rename_without_replace(from, to); return;
    }
    const auto state_destination = state_path(destination);
    files_.ensure_directory(state_destination.parent_path());
    const auto state_from = entry_parent(operations_root_, state.path), state_to = entry_parent(operations_root_, state_destination);
    const auto state_original = entry_stat(state_from); absent_entry(state_to);
    same(state, files_.inspect(state.path)); unchanged_entry(state_from, state_original); unchanged_entry(from, original);
    rename_without_replace(from, to);
    try {
        same(state, files_.inspect(state.path)); unchanged_entry(state_from, state_original);
        rename_without_replace(state_from, state_to);
    } catch (const std::exception& failure) {
        const std::string reason = failure.what();
        try {
            unchanged_entry(to, original); rename_without_replace(to, from);
        } catch (const std::exception& rollback) {
            throw FileError(FileFailure::io, "Chat moved to " + destination.generic_string() + "; its companion remains at " + state.path.generic_string() +
                ". Restore matching names before reopening. State move failed: " + reason + "; text rollback failed: " + rollback.what());
        }
        throw FileError(FileFailure::io, "Companion state move failed; the chat text was restored to " + source.generic_string() + ": " + reason);
    }
#else
    throw FileError(FileFailure::unavailable, "Qualified file-manager renaming is unavailable on this platform");
#endif
}

void Workspace::remove_entry(const std::filesystem::path& path) {
    mutable_path(path);
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    const auto parent = entry_parent(operations_root_, path);
    const auto original = entry_stat(parent);
    if (S_ISDIR(original.st_mode) || !is_chat_path(path)) { remove_checked(parent, original); return; }
    const auto state = inspect_optional(state_path(path));
    if (!state.identity.exists) { remove_checked(parent, original); return; }
    const auto state_parent = entry_parent(operations_root_, state.path);
    const auto state_original = entry_stat(state_parent);
    same(state, files_.inspect(state.path)); unchanged_entry(state_parent, state_original);
    remove_checked(parent, original);
    try {
        same(state, files_.inspect(state.path)); remove_checked(state_parent, state_original);
    } catch (const std::exception& failure) {
        throw FileError(FileFailure::io, "Chat removed; companion state remains at " + state.path.generic_string() +
            ". Preserve and inspect that state before reusing the chat name: " + failure.what());
    }
#else
    throw FileError(FileFailure::unavailable, "Qualified file-manager deletion is unavailable on this platform");
#endif
}

std::vector<TreeEntry> Workspace::children(const std::filesystem::path& directory, std::size_t max_entries) const {
    scan_limit(max_entries); relative_path(directory, true);
    const auto absolute = files_.directory(directory);
    std::vector<TreeEntry> result;
    std::error_code error;
    std::filesystem::directory_iterator iterator(absolute, error), end;
    if (error) throw FileError(FileFailure::io, "Cannot list project directory: " + error.message());
    std::size_t visited = 0;
    for (; iterator != end; iterator.increment(error)) {
        if (error) throw FileError(FileFailure::io, "Project directory listing failed: " + error.message());
        if (visited == max_entries) throw FileError(FileFailure::limit, "Directory exceeds its listing entry budget");
        ++visited;
        const auto name = iterator->path().filename();
        if (secret_name(name.string()) || name == ".tinyenv") continue;
        const auto status = iterator->symlink_status(error);
        if (error) throw FileError(FileFailure::io, "Cannot inspect directory entry: " + error.message());
        const bool directory_entry = std::filesystem::is_directory(status), symlink = std::filesystem::is_symlink(status);
        std::uint64_t bytes = 0;
        if (std::filesystem::is_regular_file(status)) {
            bytes = iterator->file_size(error);
            if (error) throw FileError(FileFailure::io, "Cannot inspect file size: " + error.message());
        }
        result.push_back({child_path(directory, name), name.string(), directory_entry, symlink, bytes});
    }
    if (error) throw FileError(FileFailure::io, "Project directory listing failed: " + error.message());
    std::sort(result.begin(), result.end(), [](const TreeEntry& a, const TreeEntry& b) {
        if (a.directory != b.directory) return a.directory > b.directory;
        return a.name < b.name;
    });
    return result;
}

std::vector<std::filesystem::path> Workspace::chats(std::size_t max_entries) const {
    scan_limit(max_entries);
    std::size_t visited = 0;
    std::vector<std::filesystem::path> result;
    std::function<void(const std::filesystem::path&, std::size_t)> walk = [&](const auto& directory, auto depth) {
        if (depth > maximum_scan_depth) throw FileError(FileFailure::limit, "Chat discovery exceeds its 32-directory depth budget; open a known chat path directly");
        std::error_code error;
        std::filesystem::directory_iterator iterator(files_.directory(directory), error), end;
        if (error) throw FileError(FileFailure::io, "Cannot discover chats: " + error.message());
        for (; iterator != end; iterator.increment(error)) {
            if (error) throw FileError(FileFailure::io, "Chat discovery failed: " + error.message());
            if (visited == max_entries) throw FileError(FileFailure::limit, "Chat discovery exceeds its entry budget; open a known chat path directly or increase the scan budget");
            ++visited;
            const auto name = iterator->path().filename(); if (private_name(name.string())) continue;
            const auto status = iterator->symlink_status(error);
            if (error) throw FileError(FileFailure::io, "Cannot inspect chat entry: " + error.message());
            const auto path = child_path(directory, name);
            if (std::filesystem::is_symlink(status)) continue;
            if (std::filesystem::is_directory(status)) walk(path, depth + 1);
            else if (std::filesystem::is_regular_file(status) && is_chat_path(path)) result.push_back(path);
        }
        if (error) throw FileError(FileFailure::io, "Chat discovery failed: " + error.message());
    };
    walk(".", 0); std::sort(result.begin(), result.end()); return result;
}

DiskUsage Workspace::disk_usage(const std::filesystem::path& directory, std::size_t max_entries) const {
    scan_limit(max_entries); relative_path(directory, true); (void)files_.directory(directory);
    DiskUsage result;
    std::function<std::uint64_t(const std::filesystem::path&, std::size_t, bool)> walk;
    walk = [&](const auto& parent, auto depth, bool top) -> std::uint64_t {
        if (depth > maximum_scan_depth) { result.truncated = true; return 0; }
        std::error_code error;
        std::filesystem::directory_iterator iterator(files_.directory(parent), error), end;
        if (error) throw FileError(FileFailure::io, "Cannot inspect disk usage: " + error.message());
        std::uint64_t total = 0;
        for (; iterator != end; iterator.increment(error)) {
            if (error) throw FileError(FileFailure::io, "Disk traversal failed: " + error.message());
            if (result.visited == max_entries) { result.truncated = true; break; }
            ++result.visited;
            const auto name = iterator->path().filename(); if (private_name(name.string())) continue;
            const auto status = iterator->symlink_status(error);
            if (error) throw FileError(FileFailure::io, "Cannot inspect disk entry: " + error.message());
            if (std::filesystem::is_symlink(status)) continue;
            const auto path = child_path(parent, name); const bool is_directory = std::filesystem::is_directory(status);
            std::uint64_t bytes = 0;
            if (is_directory) bytes = walk(path, depth + 1, false);
            else if (std::filesystem::is_regular_file(status)) {
                bytes = iterator->file_size(error);
                if (error) throw FileError(FileFailure::io, "Cannot inspect disk file size: " + error.message());
            } else continue;
            total = add_bytes(total, bytes);
            if (top) result.entries.push_back({path, name.string(), is_directory, bytes});
        }
        if (error) throw FileError(FileFailure::io, "Disk traversal failed: " + error.message());
        return total;
    };
    result.total_bytes = walk(directory, 0, true);
    std::sort(result.entries.begin(), result.entries.end(), [](const auto& a, const auto& b) {
        if (a.bytes != b.bytes) return a.bytes > b.bytes;
        return a.name < b.name;
    });
    return result;
}

std::vector<Snippet> Workspace::snippets(SnippetKind kind) const {
    const auto original = inspect_optional(snippet_path(kind)); std::vector<Snippet> result;
    if (original.identity.exists) {
        const auto value = json::parse(original.text); (void)value.object();
        if (read_integer(value, "version", 0) != 1) throw std::runtime_error("Unsupported snippet collection version");
        const auto* items = value.find("snippets"); if (!items) throw std::runtime_error("Snippet collection has no snippets array");
        if (items->array().size() > list_entries) throw FileError(FileFailure::limit, "Snippet collection exceeds 4096 entries");
        for (const auto& item : items->array()) {
            (void)item.object(); result.push_back({read_string(item, "id"), read_string(item, "title"), read_string(item, "text")});
        }
        snippets_valid(result);
    }
    snippet_originals_.insert_or_assign(kind, original); return result;
}

std::vector<Snippet> Workspace::snippets(std::string_view kind) const { return snippets(snippet_kind(kind)); }

void Workspace::save_snippets(SnippetKind kind, const std::vector<Snippet>& snippets) {
    snippets_valid(snippets); const auto path = snippet_path(kind);
    if (!snippet_originals_.contains(kind)) (void)this->snippets(kind);
    Value::Array items; items.reserve(snippets.size());
    for (const auto& snippet : snippets) items.emplace_back(Value::Object{{"id", snippet.id}, {"title", snippet.title}, {"text", snippet.text}});
    const auto bytes = json::stringify(Value::Object{{"version", 1}, {"snippets", std::move(items)}}) + "\n";
    auto& original = snippet_originals_.at(kind); same(original, inspect_optional(path));
    files_.ensure_directory(path.parent_path());
    if (!original.identity.exists || original.text != bytes) original = files_.save(original, bytes);
}

void Workspace::save_snippets(std::string_view kind, const std::vector<Snippet>& snippets) { save_snippets(snippet_kind(kind), snippets); }

} // namespace tinyenv
