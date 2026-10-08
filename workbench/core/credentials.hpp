#pragma once

#include "editor/platform/project_files.hpp"

#include <array>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>

namespace tinyenv {

enum class CredentialStatus { unsupported, absent, saved };

// Private provider authentication, separate from chat state and ai-defaults.json.
// The public API reports presence only: saved secret bytes are never returned.
// Resolving/inspecting an absent store creates no directories or files.
class AiCredentials {
public:
    static constexpr std::size_t maximum_key_bytes = 8192;
    explicit AiCredentials(std::filesystem::path config_directory = {});
    [[nodiscard]] const std::filesystem::path& directory() const noexcept { return directory_; }
    [[nodiscard]] static bool storage_available() noexcept;
    // Supported provider and qualified private-storage host, together.
    [[nodiscard]] static bool supports(std::string_view provider) noexcept;
    // Checks only the selected provider and refreshes its checked-save snapshot.
    // Unsafe, unreadable or malformed storage raises a secret-free FileError.
    [[nodiscard]] CredentialStatus status(std::string_view provider) const;
    // Explicit Save/Remove actions only. Save accepts 1..8192 printable ASCII
    // bytes without whitespace; files contain those bytes followed by one LF.
    // On qualified POSIX hosts credentials/ is 0700 and each key file is 0600.
    // Other hosts fail closed until an equivalent private-storage adapter exists.
    void save(std::string_view provider, std::string_view key);
    void remove(std::string_view provider);
private:
    struct Snapshot {
        foundation::editor::FileIdentity identity;
        std::string digest;
        friend bool operator==(const Snapshot&, const Snapshot&) = default;
    };
    std::filesystem::path directory_;
    mutable std::array<std::optional<Snapshot>, 2> snapshots_;
    [[nodiscard]] Snapshot inspect(std::string_view provider) const;
};

} // namespace tinyenv
