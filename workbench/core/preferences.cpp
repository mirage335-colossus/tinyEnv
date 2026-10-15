#include "preferences.hpp"

#include <cmath>
#include <cstdlib>
#include <limits>
#include <set>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>

namespace tinyenv {
namespace {
using foundation::editor::FileError;
using foundation::editor::FileFailure;
using foundation::editor::ProjectFiles;
using json::Value;

[[noreturn]] void invalid(std::string message) { throw FileError(FileFailure::invalid_path, std::move(message)); }
void text_limit(std::string_view value, std::size_t limit, std::string_view field) {
    if (value.size() > limit) throw FileError(FileFailure::limit, std::string(field) + " exceeds its byte limit");
    if (value.find('\0') != std::string_view::npos || !ProjectFiles::valid_utf8(value))
        throw FileError(FileFailure::encoding, std::string(field) + " must be UTF-8 without NUL");
}
std::string read_string(const Value& value, std::string_view key, std::string fallback = {}) {
    const auto* field = value.find(key); return field ? field->string() : std::move(fallback);
}
bool read_bool(const Value& value, std::string_view key, bool fallback = false) {
    const auto* field = value.find(key); return field ? field->boolean() : fallback;
}
double read_number(const Value& value, std::string_view key, double fallback) {
    const auto* field = value.find(key); return field ? field->number() : fallback;
}
int read_integer(const Value& value, std::string_view key, int fallback) {
    const auto number = read_number(value, key, static_cast<double>(fallback));
    if (!std::isfinite(number) || std::floor(number) != number || number < std::numeric_limits<int>::min() || number > std::numeric_limits<int>::max())
        throw std::runtime_error("AI field " + std::string(key) + " must be an integer");
    return static_cast<int>(number);
}
std::optional<double> read_optional_number(const Value& value, std::string_view key) {
    const auto* field = value.find(key);
    if (!field || std::holds_alternative<std::nullptr_t>(field->data)) return std::nullopt;
    return field->number();
}
std::optional<int> read_optional_integer(const Value& value, std::string_view key) {
    const auto number = read_optional_number(value, key);
    if (!number) return std::nullopt;
    if (!std::isfinite(*number) || std::floor(*number) != *number || *number < std::numeric_limits<int>::min() || *number > std::numeric_limits<int>::max())
        throw std::runtime_error("AI field " + std::string(key) + " must be an integer");
    return static_cast<int>(*number);
}
std::vector<ConfiguredModel> normalized_models(std::vector<ConfiguredModel> models) {
    if (models.size() > 128) throw FileError(FileFailure::limit, "Configured model list exceeds 128 models");
    std::set<std::tuple<std::string, std::string, std::string>> identities;
    for (auto& model : models) {
        text_limit(model.provider, 128, "Configured model provider"); text_limit(model.endpoint, 4096, "Configured model endpoint");
        text_limit(model.model, 512, "Configured model identifier"); text_limit(model.label, 512, "Configured model label");
        if (model.provider.empty() || model.model.empty()) invalid("Configured models require a provider and model identifier");
        if (!identities.emplace(model.provider, model.endpoint, model.model).second) invalid("Configured model identities must be unique");
        if (model.label.empty()) model.label = model.model;
    }
    return models;
}
Value models_json(const std::vector<ConfiguredModel>& models) {
    Value::Array result; result.reserve(models.size());
    for (const auto& model : models)
        result.emplace_back(Value::Object{{"provider", model.provider}, {"endpoint", model.endpoint}, {"model", model.model}, {"label", model.label}});
    return result;
}
std::vector<ConfiguredModel> read_models(const Value& value) {
    if (value.array().size() > 128) throw FileError(FileFailure::limit, "Configured model list exceeds 128 models");
    std::vector<ConfiguredModel> models; models.reserve(value.array().size());
    for (const auto& item : value.array()) {
        for (const auto& [key, unused] : item.object()) {
            (void)unused;
            if (key != "provider" && key != "endpoint" && key != "model" && key != "label")
                invalid("Unsupported configured model field: " + key);
        }
        models.push_back({read_string(item, "provider"), read_string(item, "endpoint"), read_string(item, "model"), read_string(item, "label")});
    }
    return normalized_models(std::move(models));
}
void guardrail_id_valid(std::string_view id) {
    text_limit(id, 128, "OpenRouter guardrail ID");
    for (const char ch : id) {
        if ((ch < 'A' || ch > 'Z') && (ch < 'a' || ch > 'z') && (ch < '0' || ch > '9') && ch != '-' && ch != '_')
            invalid("OpenRouter guardrail ID must contain only letters, digits, hyphens or underscores");
    }
}
std::filesystem::path configured_path(std::filesystem::path directory) {
    if (directory.empty()) directory = default_ai_preferences_directory();
    if (!directory.is_absolute() || directory.relative_path().empty())
        invalid("AI preferences require an absolute application config directory");
    // ProjectFiles pins the filesystem/drive root and traverses all remaining
    // components with its no-symlink contract, including the config directory.
    for (const auto& part : directory.relative_path()) {
        const auto text = part.generic_string();
        if (text.empty() || text == "." || text == ".." || text.find_first_of("\\:") != std::string::npos)
            invalid("Invalid AI config directory component");
        text_limit(text, 255, "AI config directory component");
    }
    text_limit(directory.generic_string(), 4096, "AI config directory");
    return directory;
}
std::filesystem::path required_environment(std::string_view name) {
    const auto* value = std::getenv(std::string(name).c_str());
    if (!value || !*value) invalid(std::string(name) + " is unset; AI defaults have no user config location");
    std::filesystem::path path(value);
    if (!path.is_absolute()) invalid(std::string(name) + " must name an absolute user config location");
    return path;
}
} // namespace

std::filesystem::path default_ai_preferences_directory() {
#if defined(_WIN32)
    if (const auto* appdata = std::getenv("APPDATA"); appdata && *appdata) {
        const std::filesystem::path base(appdata);
        if (!base.is_absolute()) invalid("APPDATA must name an absolute user config location");
        return base / "tinyEnv";
    }
    return required_environment("USERPROFILE") / "AppData" / "Roaming" / "tinyEnv";
#elif defined(__APPLE__)
    return required_environment("HOME") / "Library" / "Application Support" / "tinyEnv";
#else
    if (const auto* xdg = std::getenv("XDG_CONFIG_HOME"); xdg && *xdg) {
        const std::filesystem::path base(xdg);
        if (!base.is_absolute()) invalid("XDG_CONFIG_HOME must name an absolute user config location");
        return base / "tinyEnv";
    }
    return required_environment("HOME") / ".config" / "tinyEnv";
#endif
}

void validate_ai_settings(const AiSettings& ai) {
    text_limit(ai.provider, 128, "AI provider"); text_limit(ai.model, 512, "AI model");
    text_limit(ai.endpoint, 4096, "AI endpoint"); text_limit(ai.service_tier, 128, "Service tier"); text_limit(ai.reasoning_effort, 128, "Reasoning effort");
    if (ai.routing_providers.size() > 8) throw FileError(FileFailure::limit, "AI routing allowlist exceeds 8 providers");
    std::set<std::string> routes;
    for (const auto& route : ai.routing_providers) {
        text_limit(route, 101, "AI routing provider");
        const auto alphanumeric = [](char ch) { return (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9'); };
        if (route.empty() || !alphanumeric(route.front()) || !routes.insert(route).second) invalid("AI routing providers must be unique explicit provider identifiers");
        for (const char ch : route) if (!alphanumeric(ch) && ch != '.' && ch != '_' && ch != '/' && ch != '-') invalid("Invalid AI routing provider identifier");
    }
    if ((ai.num_predict && (*ai.num_predict < -1 || *ai.num_predict == 0 || *ai.num_predict > 1000000)) ||
        (ai.num_keep && (*ai.num_keep < -1 || *ai.num_keep > 4000000)) || (ai.num_ctx && (*ai.num_ctx < 1 || *ai.num_ctx > 4000000)))
        throw FileError(FileFailure::limit, "AI token parameters exceed the supported bounds");
    if ((ai.temperature && (!std::isfinite(*ai.temperature) || *ai.temperature < 0 || *ai.temperature > 2)) ||
        (ai.top_p && (!std::isfinite(*ai.top_p) || *ai.top_p <= 0 || *ai.top_p > 1)))
        throw FileError(FileFailure::limit, "AI temperature or top_p is out of range");
}

Value ai_settings_json(const AiSettings& ai) {
    validate_ai_settings(ai);
    Value::Array routes; for (const auto& route : ai.routing_providers) routes.emplace_back(route);
    Value::Object result{{"provider", ai.provider}, {"endpoint", ai.endpoint}, {"model", ai.model},
        {"web_search", ai.web_search}, {"nitro", ai.nitro}, {"service_tier", ai.service_tier},
        {"reasoning_effort", ai.reasoning_effort}, {"routing_providers", std::move(routes)}, {"zdr", ai.zdr}};
    if (ai.num_predict) result["num_predict"] = *ai.num_predict;
    if (ai.num_keep) result["num_keep"] = *ai.num_keep;
    if (ai.num_ctx) result["num_ctx"] = *ai.num_ctx;
    if (ai.temperature) result["temperature"] = *ai.temperature;
    if (ai.top_p) result["top_p"] = *ai.top_p;
    return result;
}

AiSettings read_ai_settings(const Value& value, bool reject_unknown_fields) {
    (void)value.object();
    if (reject_unknown_fields) {
        static const std::set<std::string> fields{"provider", "endpoint", "model", "num_predict", "num_keep", "num_ctx", "temperature", "top_p",
            "web_search", "nitro", "service_tier", "reasoning_effort", "routing_providers", "zdr"};
        for (const auto& [key, unused] : value.object()) {
            (void)unused;
            if (!fields.contains(key)) invalid("Unsupported AI defaults field: " + key);
        }
    }
    AiSettings settings;
    settings.provider = read_string(value, "provider", settings.provider); settings.endpoint = read_string(value, "endpoint"); settings.model = read_string(value, "model");
    settings.num_predict = read_optional_integer(value, "num_predict"); settings.num_keep = read_optional_integer(value, "num_keep");
    settings.num_ctx = read_optional_integer(value, "num_ctx"); settings.temperature = read_optional_number(value, "temperature");
    settings.top_p = read_optional_number(value, "top_p"); settings.web_search = read_bool(value, "web_search"); settings.nitro = read_bool(value, "nitro");
    settings.service_tier = read_string(value, "service_tier"); settings.reasoning_effort = read_string(value, "reasoning_effort"); settings.zdr = read_bool(value, "zdr");
    if (const auto* routes = value.find("routing_providers")) {
        if (routes->array().size() > 8) throw FileError(FileFailure::limit, "AI routing allowlist exceeds 8 providers");
        for (const auto& route : routes->array()) settings.routing_providers.push_back(route.string());
    }
    validate_ai_settings(settings);
    return settings;
}

AiPreferences::AiPreferences(std::filesystem::path config_directory)
    : directory_(configured_path(std::move(config_directory))), files_(directory_.root_path(), maximum_bytes) {
    const auto relative = directory_.relative_path() / "ai-defaults.json";
    try { original_ = files_.inspect(relative); }
    catch (const FileError& error) {
        if (error.code() != FileFailure::missing) throw;
        original_.path = relative;
    }
    if (!original_.identity.exists) return;
    const auto value = json::parse(original_.text, maximum_bytes); (void)value.object();
    const auto version = read_integer(value, "version", 0);
    if (version != 1 && version != 2) throw std::runtime_error("Unsupported AI defaults version");
    for (const auto& [key, unused] : value.object()) {
        (void)unused;
        if (key != "version" && key != "ai" && !(version == 2 && (key == "configured_models" || key == "tutorial_mode" || key == "developer_mode" || key == "right_sidebar_visible" || key == "openrouter_guardrail_id")))
            invalid("Unsupported AI defaults document field: " + key);
    }
    const auto* ai = value.find("ai");
    if (version == 1 && !ai) throw std::runtime_error("AI defaults document has no settings");
    if (ai) defaults_ = read_ai_settings(*ai, true);
    if (version == 1) {
        // A previous active model remains readily selectable after migration.
        if (!defaults_->provider.empty() && !defaults_->model.empty())
            configured_models_ = normalized_models({{defaults_->provider, defaults_->endpoint, defaults_->model, {}}});
    } else {
        const auto* models = value.find("configured_models");
        if (!models) throw std::runtime_error("AI preferences document has no configured model list");
        configured_models_ = read_models(*models);
        tutorial_mode_ = read_bool(value, "tutorial_mode");
        developer_mode_ = read_bool(value, "developer_mode");
        right_sidebar_visible_ = read_bool(value, "right_sidebar_visible", true);
        openrouter_guardrail_id_ = read_string(value, "openrouter_guardrail_id");
        guardrail_id_valid(openrouter_guardrail_id_);
    }
}

void AiPreferences::save(const AiSettings& settings) {
    save_document(settings, configured_models_, tutorial_mode_, openrouter_guardrail_id_, developer_mode_, right_sidebar_visible_);
}

void AiPreferences::save_configured_models(const std::vector<ConfiguredModel>& models) {
    auto normalized = normalized_models(models);
    save_document(defaults_, std::move(normalized), tutorial_mode_, openrouter_guardrail_id_, developer_mode_, right_sidebar_visible_);
}

void AiPreferences::set_tutorial_mode(bool enabled) {
    save_document(defaults_, configured_models_, enabled, openrouter_guardrail_id_, developer_mode_, right_sidebar_visible_);
}

void AiPreferences::set_developer_mode(bool enabled) {
    save_document(defaults_, configured_models_, tutorial_mode_, openrouter_guardrail_id_, enabled, right_sidebar_visible_);
}

void AiPreferences::set_right_sidebar_visible(bool visible) {
    save_document(defaults_, configured_models_, tutorial_mode_, openrouter_guardrail_id_, developer_mode_, visible);
}

void AiPreferences::save_guardrail_id(std::string id) {
    save_document(defaults_, configured_models_, tutorial_mode_, std::move(id), developer_mode_, right_sidebar_visible_);
}

void AiPreferences::save_document(std::optional<AiSettings> defaults, std::vector<ConfiguredModel> models, bool tutorial_mode, std::string guardrail_id, bool developer_mode, bool right_sidebar_visible) {
    guardrail_id_valid(guardrail_id);
    models = normalized_models(std::move(models));
    Value::Object document{{"version", 2}, {"configured_models", models_json(models)}, {"tutorial_mode", tutorial_mode}, {"developer_mode", developer_mode},
        {"right_sidebar_visible", right_sidebar_visible}, {"openrouter_guardrail_id", guardrail_id}};
    if (defaults) document["ai"] = ai_settings_json(*defaults);
    // Count/string bounds above keep serialization bounded, including escaped
    // bytes. Check the complete document before any directory or file write.
    const auto bytes = json::stringify(document) + "\n";
    if (bytes.size() > maximum_bytes) throw FileError(FileFailure::limit, "AI preferences exceed the 32 KiB document limit");
    files_.ensure_directory(directory_.relative_path());
    original_ = files_.save(original_, bytes);
    defaults_ = std::move(defaults);
    configured_models_ = std::move(models);
    tutorial_mode_ = tutorial_mode;
    developer_mode_ = developer_mode;
    right_sidebar_visible_ = right_sidebar_visible;
    openrouter_guardrail_id_ = std::move(guardrail_id);
}

void AiPreferences::inherit(ChatState& state) const {
    // A model is chosen only by the user, either here or through saved defaults.
    if (!state.ai_configured) state.ai = defaults_.value_or(AiSettings{});
}

} // namespace tinyenv
