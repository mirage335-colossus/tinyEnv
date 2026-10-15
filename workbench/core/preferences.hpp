#pragma once

#include "workspace.hpp"
#include "json.hpp"

#include <filesystem>
#include <optional>

namespace tinyenv {

// The application's config directory, independent of the selected project.
// Resolving it creates no files; a nonabsolute configured location is an error.
[[nodiscard]] std::filesystem::path default_ai_preferences_directory();

// Shared state/defaults codec. Only the nonsecret AiSettings fields are written.
void validate_ai_settings(const AiSettings& settings);
[[nodiscard]] json::Value ai_settings_json(const AiSettings& settings);
[[nodiscard]] AiSettings read_ai_settings(const json::Value& value, bool reject_unknown_fields = false);

// The saved catalog is independent of the current chat and AI defaults.
// Provider, endpoint and model form its unique identity; labels are display text.
struct ConfiguredModel {
    std::string provider{"openrouter"}, endpoint, model, label;
    friend bool operator==(const ConfiguredModel&, const ConfiguredModel&) = default;
};

// One checked, bounded user preference file. Loading creates no directories and
// reports malformed/unsafe/unreadable settings instead of replacing them.
// An explicit config directory lets callers isolate tests and portable launches.
class AiPreferences {
public:
    explicit AiPreferences(std::filesystem::path config_directory = {});
    [[nodiscard]] const std::filesystem::path& directory() const noexcept { return directory_; }
    [[nodiscard]] const std::optional<AiSettings>& defaults() const noexcept { return defaults_; }
    [[nodiscard]] const std::vector<ConfiguredModel>& configured_models() const noexcept { return configured_models_; }
    [[nodiscard]] bool tutorial_mode() const noexcept { return tutorial_mode_; }
    [[nodiscard]] bool developer_mode() const noexcept { return developer_mode_; }
    [[nodiscard]] bool right_sidebar_visible() const noexcept { return right_sidebar_visible_; }
    [[nodiscard]] const std::string& openrouter_guardrail_id() const noexcept { return openrouter_guardrail_id_; }
    // The caller uses this only for an explicit Apply action. It never persists
    // a draft, credentials, or incidental changes caused by switching chats.
    void save(const AiSettings& settings);
    // Adding/removing catalog entries never replaces active/default AI settings.
    // An empty label is saved as the model identifier. Checked conflicts leave
    // both in-memory settings and the stored document unchanged.
    void save_configured_models(const std::vector<ConfiguredModel>& models);
    // Application-wide display preference, off until explicitly enabled.
    void set_tutorial_mode(bool enabled);
    // Chat history is read-only unless this application-wide opt-in is enabled.
    void set_developer_mode(bool enabled);
    // Application-wide layout preference, visible until explicitly hidden.
    void set_right_sidebar_visible(bool visible);
    // Nonsecret management-resource identity only. Actual remote guardrail
    // state and management credentials are never stored in this document.
    void save_guardrail_id(std::string id);
    // Existing explicit chat settings win; otherwise use the latest defaults.
    void inherit(ChatState& state) const;
private:
    static constexpr std::size_t maximum_bytes = 32 * 1024;
    std::filesystem::path directory_;
    foundation::editor::ProjectFiles files_;
    foundation::editor::FileSnapshot original_;
    std::optional<AiSettings> defaults_;
    std::vector<ConfiguredModel> configured_models_;
    bool tutorial_mode_{}, developer_mode_{};
    bool right_sidebar_visible_{true};
    std::string openrouter_guardrail_id_;
    void save_document(std::optional<AiSettings> defaults, std::vector<ConfiguredModel> models, bool tutorial_mode, std::string guardrail_id, bool developer_mode, bool right_sidebar_visible);
};

} // namespace tinyenv
