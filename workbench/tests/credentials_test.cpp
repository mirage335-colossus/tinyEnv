#include "core/credentials.hpp"
#include "core/preferences.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

#if defined(__unix__) && !defined(__EMSCRIPTEN__)
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

using namespace tinyenv;
using foundation::editor::FileError;
using foundation::editor::FileFailure;
namespace {
constexpr std::string_view first_key = "fake-openrouter-sentinel-ONLY-FOR-TESTS";
constexpr std::string_view second_key = "fake-openai-sentinel-ONLY-FOR-TESTS";
void check(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
template<class F> void fails(FileFailure expected, F&& action) {
    try { action(); }
    catch (const FileError& error) {
        check(error.code() == expected, "Unexpected credential failure category");
        check(std::string_view(error.what()).find(first_key) == std::string_view::npos &&
              std::string_view(error.what()).find(second_key) == std::string_view::npos,
              "Credential failure disclosed a fake secret");
        return;
    }
    throw std::runtime_error("Expected checked credential failure");
}
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
void raw_write(const std::filesystem::path& path, std::string_view text) {
    std::ofstream output(path, std::ios::binary); output.write(text.data(), static_cast<std::streamsize>(text.size()));
    if (!output) throw std::runtime_error("Cannot write isolated credential fixture");
    output.close();
    check(::chmod(path.c_str(), 0600) == 0, "Cannot protect isolated credential fixture");
}
std::string raw_read(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("Cannot read isolated credential fixture");
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}
unsigned mode(const std::filesystem::path& path) {
    struct stat info{};
    check(::lstat(path.c_str(), &info) == 0, "Cannot inspect isolated credential fixture");
    return static_cast<unsigned>(info.st_mode & 07777);
}
void no_staging_files(const std::filesystem::path& directory) {
    for (const auto& entry : std::filesystem::directory_iterator(directory))
        check(!entry.path().filename().string().starts_with(".tinyenv-key-save-"), "Credential save left a staged secret");
}
#endif
} // namespace

int main() {
    try {
        const auto root = std::filesystem::temp_directory_path() / ("tinyEnv-credentials-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directory(root);
        struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code error; std::filesystem::remove_all(path, error); } } cleanup{root};
        const auto config = root / "user-config" / "tinyEnv";
        AiCredentials credentials(config);
        check(credentials.directory() == config && AiCredentials::supports("openrouter") == AiCredentials::storage_available() &&
              AiCredentials::supports("openai") == AiCredentials::storage_available() &&
              !AiCredentials::supports("ollama") && !AiCredentials::supports("../openrouter") && !AiCredentials::supports("OPENAI"),
              "Credential provider selection escaped its fixed supported set");
        check(credentials.status("ollama") == CredentialStatus::unsupported && !std::filesystem::exists(config.parent_path()),
              "Unsupported credential status created a config directory");
        fails(FileFailure::unavailable, [&] { credentials.save("ollama", first_key); });
        fails(FileFailure::unavailable, [&] { credentials.remove("../openai"); });
        fails(FileFailure::invalid_path, [&] { AiCredentials relative("relative-config"); });
        fails(FileFailure::invalid_path, [&] { AiCredentials traversal(root / ".." / "outside"); });
        fails(FileFailure::invalid_path, [&] { AiCredentials filesystem_root(config.root_path()); });
        fails(FileFailure::invalid_path, [&] { AiCredentials colon(root / "with:colon"); });
        fails(FileFailure::encoding, [&] { credentials.save("openai", std::string(first_key) + "\n"); });
        fails(FileFailure::encoding, [&] { credentials.save("openai", std::string(first_key) + " "); });
        fails(FileFailure::encoding, [&] { credentials.save("openai", std::string(first_key) + '\0'); });
        fails(FileFailure::encoding, [&] { credentials.save("openai", "fake-nonascii-\xc3\xa9"); });
        fails(FileFailure::invalid_path, [&] { credentials.save("openai", ""); });
        fails(FileFailure::limit, [&] { credentials.save("openai", std::string(AiCredentials::maximum_key_bytes + 1, 'x')); });
        check(!std::filesystem::exists(config.parent_path()), "Rejected API key created private storage");

#if defined(__unix__) && !defined(__EMSCRIPTEN__)
        // Every store uses an explicit isolated path. Tests never inspect the
        // actual user's environment, private configuration or live credentials.
        check(credentials.status("openrouter") == CredentialStatus::absent && credentials.status("openai") == CredentialStatus::absent,
              "Absent credential store reported a saved key");
        credentials.remove("openrouter");
        check(!std::filesystem::exists(config.parent_path()), "Checking/removing absent credentials created files");
        const auto old_umask = ::umask(0077);
        struct RestoreUmask { mode_t original; ~RestoreUmask() { ::umask(original); } } restore_umask{old_umask};
        credentials.save("openrouter", first_key);
        const auto private_directory = config / "credentials";
        const auto router_file = private_directory / "openrouter.key", openai_file = private_directory / "openai.key";
        check(mode(config) == 0700 && mode(private_directory) == 0700 && mode(router_file) == 0600,
              "New credential store has unsafe permissions");
        check(raw_read(router_file) == std::string(first_key) + "\n" && credentials.status("openrouter") == CredentialStatus::saved &&
              credentials.status("openai") == CredentialStatus::absent, "Provider key format/status was not isolated");
        credentials.save("openai", second_key);
        check(raw_read(openai_file) == std::string(second_key) + "\n" && raw_read(router_file) == std::string(first_key) + "\n" &&
              mode(openai_file) == 0600, "Saving a second provider replaced another provider's key");
        AiCredentials restarted(config);
        check(restarted.status("openrouter") == CredentialStatus::saved && restarted.status("openai") == CredentialStatus::saved,
              "Private provider status did not survive restart");
        restarted.save("openrouter", "fake-replacement-sentinel");
        check(raw_read(router_file) == "fake-replacement-sentinel\n" && raw_read(openai_file) == std::string(second_key) + "\n",
              "Explicit replacement changed the wrong provider key");
        restarted.remove("openrouter");
        check(!std::filesystem::exists(router_file) && restarted.status("openrouter") == CredentialStatus::absent &&
              restarted.status("openai") == CredentialStatus::saved, "Explicit removal deleted another provider key");
        restarted.remove("openrouter");
        no_staging_files(private_directory);

        // Existing 0755 application preferences are compatible; credentials
        // alone are private and no secret is added to the preferences document.
        const auto preferences_config = root / "shared-preferences";
        AiPreferences preferences(preferences_config);
        AiSettings settings; settings.provider = "openai"; settings.model = "fake-model";
        preferences.save(settings);
        check(::chmod(preferences_config.c_str(), 0755) == 0, "Cannot set preferences compatibility fixture");
        AiCredentials with_preferences(preferences_config); with_preferences.save("openai", second_key);
        check(raw_read(preferences_config / "ai-defaults.json").find(second_key) == std::string::npos &&
              mode(preferences_config) == 0755 && mode(preferences_config / "credentials") == 0700,
              "Private credential persistence altered or leaked through nonsecret preferences");
        with_preferences.save("openai", std::string(AiCredentials::maximum_key_bytes, 'x'));
        check(raw_read(preferences_config / "credentials/openai.key").size() == AiCredentials::maximum_key_bytes + 1 &&
              with_preferences.status("openai") == CredentialStatus::saved, "Maximum supported key failed to roundtrip");

        // Checked saves preserve foreign writes, including a same-size content
        // mutation whose timestamp was restored. The digest is private state.
        AiCredentials stale(config);
        check(stale.status("openrouter") == CredentialStatus::absent, "Conflict fixture was not absent");
        restarted.save("openrouter", first_key);
        fails(FileFailure::conflict, [&] { stale.save("openrouter", "fake-stale-create"); });
        fails(FileFailure::conflict, [&] { stale.remove("openrouter"); });
        check(raw_read(router_file) == std::string(first_key) + "\n", "Stale creation/removal clobbered a foreign key");
        check(stale.status("openrouter") == CredentialStatus::saved, "Conflict refresh did not see the foreign key");
        const auto original_time = std::filesystem::last_write_time(router_file);
        auto altered = std::string(first_key); altered[0] = 'F'; raw_write(router_file, altered + "\n");
        std::filesystem::last_write_time(router_file, original_time);
        fails(FileFailure::conflict, [&] { stale.save("openrouter", first_key); });
        fails(FileFailure::conflict, [&] { stale.remove("openrouter"); });
        check(raw_read(router_file) == altered + "\n", "Checked credential mutation ignored different bytes");
        check(stale.status("openrouter") == CredentialStatus::saved, "Updated key status was not readable");
        std::filesystem::rename(router_file, private_directory / "previous.key"); raw_write(router_file, altered + "\n");
        fails(FileFailure::conflict, [&] { stale.save("openrouter", first_key); });
        fails(FileFailure::conflict, [&] { stale.remove("openrouter"); });
        std::filesystem::remove(private_directory / "previous.key");
        no_staging_files(private_directory);

        // Every existing path component and secret leaf refuses symlinks.
        const auto outside = root / "outside";
        std::filesystem::create_directory(outside); raw_write(outside / "keep.key", "fake-outside-key\n");
        std::filesystem::create_directory_symlink(config, root / "config-alias");
        AiCredentials aliased(root / "config-alias");
        fails(FileFailure::invalid_path, [&] { (void)aliased.status("openai"); });
        fails(FileFailure::invalid_path, [&] { aliased.save("openai", second_key); });
        fails(FileFailure::invalid_path, [&] { aliased.remove("openai"); });
        const auto link_config = root / "linked-private-directory";
        std::filesystem::create_directory(link_config); std::filesystem::create_directory_symlink(outside, link_config / "credentials");
        AiCredentials linked_directory(link_config);
        fails(FileFailure::invalid_path, [&] { (void)linked_directory.status("openai"); });
        fails(FileFailure::invalid_path, [&] { linked_directory.save("openai", second_key); });
        std::filesystem::remove(router_file); std::filesystem::create_symlink(outside / "keep.key", router_file);
        AiCredentials linked_file(config);
        fails(FileFailure::invalid_path, [&] { (void)linked_file.status("openrouter"); });
        fails(FileFailure::invalid_path, [&] { linked_file.save("openrouter", first_key); });
        fails(FileFailure::invalid_path, [&] { linked_file.remove("openrouter"); });
        check(raw_read(outside / "keep.key") == "fake-outside-key\n" && std::filesystem::is_symlink(router_file),
              "Refused credential symlink altered its referent");
        check(linked_file.status("openai") == CredentialStatus::saved, "Unsafe unrelated provider blocked selected-provider status");
        linked_file.save("openai", "fake-valid-openai-replacement");
        check(std::filesystem::is_symlink(router_file), "Saving one provider changed an unsafe unrelated key");
        std::filesystem::remove(router_file); raw_write(router_file, std::string(first_key) + "\n");

        // Private modes, ordinary file type, single-link identity, and the
        // bounded one-line format are requirements on reads and writes alike.
        check(::chmod(config.c_str(), 0777) == 0, "Cannot set unsafe config mode");
        fails(FileFailure::permission, [&] { (void)AiCredentials(config).status("openai"); });
        fails(FileFailure::permission, [&] { AiCredentials(config).save("openai", second_key); });
        check(::chmod(config.c_str(), 0700) == 0 && ::chmod(private_directory.c_str(), 0755) == 0, "Cannot set unsafe private mode");
        fails(FileFailure::permission, [&] { (void)AiCredentials(config).status("openai"); });
        check(::chmod(private_directory.c_str(), 0700) == 0 && ::chmod(router_file.c_str(), 0644) == 0, "Cannot set unsafe key mode");
        fails(FileFailure::permission, [&] { (void)AiCredentials(config).status("openrouter"); });
        fails(FileFailure::permission, [&] { AiCredentials(config).remove("openrouter"); });
        check(::chmod(router_file.c_str(), 0600) == 0, "Cannot restore private key mode");
        std::filesystem::create_hard_link(router_file, private_directory / "hardlink.key");
        fails(FileFailure::invalid_path, [&] { (void)AiCredentials(config).status("openrouter"); });
        fails(FileFailure::invalid_path, [&] { AiCredentials(config).save("openrouter", first_key); });
        std::filesystem::remove(private_directory / "hardlink.key");
        for (const auto& bad : {std::string{}, std::string(first_key), std::string(first_key) + "\n\n", std::string(first_key) + " \n", std::string("fake\0hidden\n", 12)}) {
            raw_write(router_file, bad);
            try { (void)AiCredentials(config).status("openrouter"); throw std::runtime_error("Malformed private key was accepted"); }
            catch (const FileError& error) {
                check(error.code() == FileFailure::encoding || error.code() == FileFailure::invalid_path,
                      "Malformed key reported an unexpected category");
                check(std::string_view(error.what()).find(first_key) == std::string_view::npos, "Malformed private key was echoed");
            }
            check(raw_read(router_file) == bad, "Malformed private key was rewritten during inspection");
            check(AiCredentials(config).status("openai") == CredentialStatus::saved, "Malformed unrelated key blocked selected-provider status");
        }
        raw_write(router_file, std::string(AiCredentials::maximum_key_bytes + 1, 'x') + "\n");
        fails(FileFailure::limit, [&] { (void)AiCredentials(config).status("openrouter"); });
        std::filesystem::remove(router_file); std::filesystem::create_directory(router_file);
        fails(FileFailure::invalid_path, [&] { (void)AiCredentials(config).status("openrouter"); });
        std::filesystem::remove(router_file);
        check(::mkfifo(router_file.c_str(), 0600) == 0, "Cannot create special key fixture");
        fails(FileFailure::invalid_path, [&] { (void)AiCredentials(config).status("openrouter"); });
        std::filesystem::remove(router_file);
        no_staging_files(private_directory);
#else
        check(credentials.status("openai") == CredentialStatus::unsupported, "Unsupported host reported private storage support");
        fails(FileFailure::unavailable, [&] { credentials.save("openai", second_key); });
        fails(FileFailure::unavailable, [&] { credentials.remove("openai"); });
        check(!std::filesystem::exists(config.parent_path()), "Unsupported private storage created files");
#endif
        std::cout << "Private credential checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
