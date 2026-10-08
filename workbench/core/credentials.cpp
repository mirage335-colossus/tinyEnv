#include "credentials.hpp"
#include "preferences.hpp"
#include "editor/platform/content_digest.hpp"

#include <cerrno>
#include <cstring>
#include <utility>

#if defined(__unix__) && !defined(__EMSCRIPTEN__)
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace tinyenv {
namespace {
using foundation::editor::FileError;
using foundation::editor::FileFailure;
using foundation::editor::FileIdentity;

[[noreturn]] void invalid(std::string message) { throw FileError(FileFailure::invalid_path, std::move(message)); }

std::filesystem::path checked_directory(std::filesystem::path directory) {
    if (directory.empty()) directory = default_ai_preferences_directory();
    if (!directory.is_absolute() || directory.relative_path().empty())
        invalid("Provider credentials require an absolute application config directory");
    const auto complete = directory.generic_string();
    if (complete.size() > 4096) throw FileError(FileFailure::limit, "Credential config directory exceeds its byte limit");
    for (const auto& part : directory.relative_path()) {
        const auto name = part.generic_string();
        if (name.empty() || name == "." || name == ".." || name.find_first_of("\\:") != std::string::npos ||
            name.find('\0') != std::string::npos || !foundation::editor::ProjectFiles::valid_utf8(name))
            invalid("Invalid credential config directory component");
        if (name.size() > 255) throw FileError(FileFailure::limit, "Credential config directory component exceeds its byte limit");
    }
    return directory;
}

std::size_t provider_index(std::string_view provider) {
    if (provider == "openrouter") return 0;
    if (provider == "openai") return 1;
    throw FileError(FileFailure::unavailable, "Saved API-key authentication is unavailable for this provider");
}
const char* provider_file(std::string_view provider) { return provider_index(provider) == 0 ? "openrouter.key" : "openai.key"; }

void validate_key(std::string_view key) {
    if (key.empty()) invalid("Enter a nonempty API key before saving");
    if (key.size() > AiCredentials::maximum_key_bytes)
        throw FileError(FileFailure::limit, "API key exceeds the 8192-byte limit");
    for (const unsigned char byte : key) {
        if (byte < 0x21 || byte > 0x7e)
            throw FileError(FileFailure::encoding, "API keys must contain printable ASCII without whitespace");
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

[[noreturn]] void os_error(std::string_view operation, int error = errno) {
    auto code = FileFailure::io;
    if (error == ENOENT) code = FileFailure::missing;
    else if (error == EACCES || error == EPERM || error == EROFS) code = FileFailure::permission;
    else if (error == ELOOP || error == ENOTDIR) code = FileFailure::invalid_path;
    throw FileError(code, std::string(operation) + ": " + std::strerror(error));
}

FileIdentity identity(const struct stat& info) {
    FileIdentity result{true, static_cast<std::uint64_t>(info.st_dev), static_cast<std::uint64_t>(info.st_ino),
                        static_cast<std::uint64_t>(info.st_size), 0, 0, static_cast<std::uint32_t>(info.st_mode & 07777)};
#if defined(__APPLE__)
    result.modified_seconds = info.st_mtimespec.tv_sec; result.modified_nanoseconds = info.st_mtimespec.tv_nsec;
#else
    result.modified_seconds = info.st_mtim.tv_sec; result.modified_nanoseconds = info.st_mtim.tv_nsec;
#endif
    return result;
}

struct DirectoryIdentity {
    std::uint64_t device{}, object{};
    friend bool operator==(const DirectoryIdentity&, const DirectoryIdentity&) = default;
};
DirectoryIdentity directory_identity(int descriptor) {
    struct stat info{};
    if (::fstat(descriptor, &info) != 0) os_error("Cannot inspect credential directory");
    return {static_cast<std::uint64_t>(info.st_dev), static_cast<std::uint64_t>(info.st_ino)};
}

void check_config_directory(int descriptor, bool private_directory) {
    struct stat info{};
    if (::fstat(descriptor, &info) != 0) os_error("Cannot inspect credential directory");
    if (!S_ISDIR(info.st_mode)) invalid("Credential storage requires ordinary directories");
    if (info.st_uid != ::geteuid() || (private_directory ? (info.st_mode & 07777) != 0700 : (info.st_mode & 0022) != 0))
        throw FileError(FileFailure::permission, "Credential directories must be owned by the current user and privately writable");
}

Descriptor open_directory(const std::filesystem::path& path, bool create) {
    Descriptor current(::open(path.root_path().c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
    if (current.value < 0) os_error("Cannot open credential filesystem root");
    for (const auto& part : path.relative_path()) {
        bool created{};
        Descriptor next(::openat(current.value, part.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
        if (next.value < 0 && errno == ENOENT) {
            if (!create) return Descriptor{};
            if (::mkdirat(current.value, part.c_str(), 0700) == 0) created = true;
            else if (errno != EEXIST) os_error("Cannot create credential config directory");
            next = Descriptor(::openat(current.value, part.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
        }
        if (next.value < 0) os_error("Cannot open credential config directory");
        if (created && ::fchmod(next.value, 0700) != 0) os_error("Cannot protect credential config directory");
        current = std::move(next);
    }
    check_config_directory(current.value, false);
    return current;
}

Descriptor open_private_directory(const std::filesystem::path& config, bool create) {
    auto parent = open_directory(config, create);
    if (parent.value < 0) return Descriptor{};
    bool created{};
    Descriptor result(::openat(parent.value, "credentials", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
    if (result.value < 0 && errno == ENOENT) {
        if (!create) return Descriptor{};
        struct stat info{};
        if (::fstat(parent.value, &info) != 0) os_error("Cannot inspect credential config directory");
        if (!(info.st_mode & 0200)) throw FileError(FileFailure::permission, "Credential config directory is read-only");
        if (::mkdirat(parent.value, "credentials", 0700) == 0) created = true;
        else if (errno != EEXIST) os_error("Cannot create private credential directory");
        result = Descriptor(::openat(parent.value, "credentials", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
    }
    if (result.value < 0) os_error("Cannot open private credential directory");
    if (created && ::fchmod(result.value, 0700) != 0) os_error("Cannot protect private credential directory");
    check_config_directory(result.value, true);
    return result;
}

struct CheckedFile {
    FileIdentity identity;
    std::string digest;
    friend bool operator==(const CheckedFile&, const CheckedFile&) = default;
};

CheckedFile read_key(int directory, const char* leaf) {
    if (directory < 0) return {};
    Descriptor file(::openat(directory, leaf, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC));
    if (file.value < 0) { if (errno == ENOENT) return {}; os_error("Cannot open saved provider key"); }
    struct stat before{}, after{};
    if (::fstat(file.value, &before) != 0) os_error("Cannot inspect saved provider key");
    if (!S_ISREG(before.st_mode) || before.st_nlink != 1) invalid("Saved provider keys must be ordinary files without hard links");
    if (before.st_uid != ::geteuid() || (before.st_mode & 07777) != 0600)
        throw FileError(FileFailure::permission, "Saved provider key must be owned by the current user with mode 0600");
    if (before.st_size < 0 || static_cast<std::uint64_t>(before.st_size) > AiCredentials::maximum_key_bytes + 1)
        throw FileError(FileFailure::limit, "Saved provider key exceeds its byte limit");
    std::array<char, AiCredentials::maximum_key_bytes + 2> bytes{};
    struct Erase {
        std::array<char, AiCredentials::maximum_key_bytes + 2>& bytes;
        ~Erase() { volatile char* target = bytes.data(); for (std::size_t index = 0; index < bytes.size(); ++index) target[index] = 0; }
    } erase{bytes};
    std::size_t size{};
    for (;;) {
        const auto count = ::read(file.value, bytes.data() + size, bytes.size() - size);
        if (count < 0) { if (errno == EINTR) continue; os_error("Cannot read saved provider key"); }
        if (count == 0) break;
        size += static_cast<std::size_t>(count);
        if (size > AiCredentials::maximum_key_bytes + 1)
            throw FileError(FileFailure::limit, "Saved provider key exceeds its byte limit");
    }
    if (::fstat(file.value, &after) != 0) os_error("Cannot recheck saved provider key");
    if (identity(before) != identity(after) || after.st_uid != before.st_uid || after.st_nlink != 1 || size != static_cast<std::size_t>(after.st_size))
        throw FileError(FileFailure::conflict, "Saved provider key changed while being checked; refresh its status");
    if (size == 0 || bytes[size - 1] != '\n')
        throw FileError(FileFailure::encoding, "Saved provider key has an invalid private-file format");
    validate_key(std::string_view(bytes.data(), size - 1));
    return {identity(after), foundation::editor::detail::content_digest(std::string_view(bytes.data(), size))};
}

void check_directory_current(const std::filesystem::path& path, int pinned) {
    const auto current = open_private_directory(path, false);
    if (current.value < 0 || directory_identity(current.value) != directory_identity(pinned))
        throw FileError(FileFailure::conflict, "Credential directory changed externally; refresh its status");
}

void write_bytes(int descriptor, std::string_view bytes) {
    std::size_t offset{};
    while (offset < bytes.size()) {
        const auto count = ::write(descriptor, bytes.data() + offset, bytes.size() - offset);
        if (count < 0) { if (errno == EINTR) continue; os_error("Cannot write private provider key"); }
        if (count == 0) throw FileError(FileFailure::io, "Short write while saving private provider key");
        offset += static_cast<std::size_t>(count);
    }
}
#else
[[noreturn]] void unavailable() {
    throw FileError(FileFailure::unavailable, "Private provider-key storage is unavailable on this platform");
}
#endif
} // namespace

AiCredentials::AiCredentials(std::filesystem::path config_directory) : directory_(checked_directory(std::move(config_directory))) {}

bool AiCredentials::storage_available() noexcept {
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    return true;
#else
    return false;
#endif
}

bool AiCredentials::supports(std::string_view provider) noexcept {
    return storage_available() && (provider == "openrouter" || provider == "openai");
}

AiCredentials::Snapshot AiCredentials::inspect(std::string_view provider) const {
    const auto* leaf = provider_file(provider);
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    const auto directory = open_private_directory(directory_, false);
    const auto file = read_key(directory.value, leaf);
    if (directory.value >= 0) check_directory_current(directory_, directory.value);
    return {file.identity, file.digest};
#else
    (void)leaf; unavailable();
#endif
}

CredentialStatus AiCredentials::status(std::string_view provider) const {
    if (!supports(provider)) return CredentialStatus::unsupported;
    auto snapshot = inspect(provider);
    const auto result = snapshot.identity.exists ? CredentialStatus::saved : CredentialStatus::absent;
    snapshots_[provider_index(provider)] = std::move(snapshot);
    return result;
}

void AiCredentials::save(std::string_view provider, std::string_view key) {
    const auto index = provider_index(provider);
    validate_key(key);
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    const auto expected = snapshots_[index] ? *snapshots_[index] : inspect(provider);
    auto directory = open_private_directory(directory_, true);
    auto matches = [&] {
        check_directory_current(directory_, directory.value);
        const auto current = read_key(directory.value, provider_file(provider));
        if (current.identity != expected.identity || current.digest != expected.digest)
            throw FileError(FileFailure::conflict, "Saved provider key changed externally; refresh its status before saving");
    };
    matches();
    Descriptor temporary;
    std::string staged;
    for (unsigned attempt = 0; attempt < 1000; ++attempt) {
        staged = ".tinyenv-key-save-" + std::to_string(::getpid()) + "-" + std::to_string(attempt);
        temporary = Descriptor(::openat(directory.value, staged.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600));
        if (temporary.value >= 0) break;
        if (errno != EEXIST) os_error("Cannot stage private provider key");
    }
    if (temporary.value < 0) throw FileError(FileFailure::io, "No free private provider-key staging name");
    bool staged_exists = true;
    try {
        if (::fchmod(temporary.value, 0600) != 0) os_error("Cannot protect staged provider key");
        write_bytes(temporary.value, key); write_bytes(temporary.value, "\n");
        if (::fsync(temporary.value) != 0) os_error("Cannot flush private provider key");
        if (::close(std::exchange(temporary.value, -1)) != 0) os_error("Cannot close staged provider key");
        // Checked saves assume cooperative editors, just like ProjectFiles.
        // The final comparison is not a cross-process compare-and-swap claim.
        matches();
        if (expected.identity.exists) {
            if (::renameat(directory.value, staged.c_str(), directory.value, provider_file(provider)) != 0)
                os_error("Cannot replace private provider key");
            staged_exists = false;
        } else {
            if (::linkat(directory.value, staged.c_str(), directory.value, provider_file(provider), 0) != 0) {
                if (errno == EEXIST) throw FileError(FileFailure::conflict, "Provider key was created externally during save");
                os_error("Cannot publish private provider key");
            }
            if (::unlinkat(directory.value, staged.c_str(), 0) != 0) os_error("Provider key saved but staging cleanup failed");
            staged_exists = false;
        }
        if (::fsync(directory.value) != 0) os_error("Provider key saved but directory durability could not be confirmed");
        snapshots_[index] = inspect(provider);
    } catch (...) {
        if (staged_exists) ::unlinkat(directory.value, staged.c_str(), 0);
        throw;
    }
#else
    (void)index; unavailable();
#endif
}

void AiCredentials::remove(std::string_view provider) {
    const auto index = provider_index(provider);
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    const auto expected = snapshots_[index] ? *snapshots_[index] : inspect(provider);
    const auto directory = open_private_directory(directory_, false);
    const auto current = read_key(directory.value, provider_file(provider));
    if (current.identity != expected.identity || current.digest != expected.digest)
        throw FileError(FileFailure::conflict, "Saved provider key changed externally; refresh its status before removing");
    if (directory.value >= 0) check_directory_current(directory_, directory.value);
    if (!current.identity.exists) { snapshots_[index] = Snapshot{}; return; }
    // Recheck exact identity and content immediately before the explicit remove.
    if (read_key(directory.value, provider_file(provider)) != current)
        throw FileError(FileFailure::conflict, "Saved provider key changed externally before removing");
    if (::unlinkat(directory.value, provider_file(provider), 0) != 0) os_error("Cannot remove saved provider key");
    if (::fsync(directory.value) != 0) os_error("Provider key removed but directory durability could not be confirmed");
    snapshots_[index] = Snapshot{};
#else
    (void)index; unavailable();
#endif
}

} // namespace tinyenv
