#pragma once

#include "editor/platform/project_files.hpp"
#include <cstdlib>
#include <filesystem>
#include <stdexcept>

namespace tinyenv {

// An explicit project root remains an existing-directory selection. Only the
// omitted-root launch creates the general-purpose chats directory in home.
inline std::filesystem::path resolve_launch_root(const std::filesystem::path& requested,
                                                const std::filesystem::path& home) {
    if (!requested.empty()) return requested;
    if (home.empty() || !home.is_absolute())
        throw std::invalid_argument("The home directory must be an existing absolute directory; supply --root to select a project");
    foundation::editor::ProjectFiles files(home);
    const std::filesystem::path casual("tinyEnv/casual-chats");
    files.ensure_directory(casual);
    return files.directory(casual);
}

inline std::filesystem::path resolve_launch_root(const std::filesystem::path& requested = {}) {
    if (!requested.empty()) return requested;
#if defined(_WIN32)
    const auto* value = std::getenv("USERPROFILE");
    constexpr auto missing = "USERPROFILE is unset; supply --root to select a project directory";
#else
    const auto* value = std::getenv("HOME");
    constexpr auto missing = "HOME is unset; supply --root to select a project directory";
#endif
    if (!value || !*value) throw std::invalid_argument(missing);
    return resolve_launch_root({}, std::filesystem::path(value));
}

} // namespace tinyenv
