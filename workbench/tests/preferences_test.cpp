#include "core/preferences.hpp"
#include "core/workspace.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

using namespace tinyenv;
using foundation::editor::FileError;
using foundation::editor::FileFailure;
namespace {
void check(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
template<class F> void fails(FileFailure expected, F&& action) {
    try { action(); } catch (const FileError& error) { check(error.code() == expected, "Unexpected file failure category"); return; }
    throw std::runtime_error("Expected checked file failure");
}
template<class F> void malformed(F&& action) {
    try { action(); } catch (const std::runtime_error&) { return; }
    throw std::runtime_error("Expected malformed preferences failure");
}
void raw_write(const std::filesystem::path& path, std::string_view text) {
    std::ofstream output(path, std::ios::binary); output.write(text.data(), static_cast<std::streamsize>(text.size()));
    if (!output) throw std::runtime_error("Cannot write isolated test fixture");
}
std::string raw_read(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("Cannot read isolated test fixture");
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}
} // namespace

int main() {
    try {
        const auto root = std::filesystem::temp_directory_path() / ("tinyEnv-preferences-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directory(root);
        struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code error; std::filesystem::remove_all(path, error); } } cleanup{root};
        const auto config = root / "user-config" / "tinyEnv";
        // Every preferences instance has an explicit local fixture path. None
        // resolves, creates, or changes the actual user's home/config files.
        AiPreferences preferences(config);
        check(!preferences.defaults() && preferences.configured_models().empty() && !preferences.tutorial_mode() && !preferences.developer_mode() && preferences.right_sidebar_visible() && preferences.openrouter_guardrail_id().empty() &&
            !std::filesystem::exists(config.parent_path()), "Reading absent preferences changed defaults or created files");
        ChatState builtin; preferences.inherit(builtin);
        check(builtin.ai == AiSettings{} && builtin.ai.model.empty() && !builtin.ai_configured && !std::filesystem::exists(config.parent_path()),
            "Fresh AI settings selected an implicit model or created configuration");
        ChatState explicit_empty; explicit_empty.ai_configured = true;
        preferences.inherit(explicit_empty);
        check(explicit_empty.ai == AiSettings{}, "Inheritance replaced explicitly configured fields");
        check(!builtin.ai.num_predict && !builtin.ai.num_keep && !builtin.ai.num_ctx && !builtin.ai.temperature && !builtin.ai.top_p,
            "Unspecified generation controls acquired numeric defaults");
        const auto builtin_json = ai_settings_json(builtin.ai);
        for (const auto* field : {"num_predict", "num_keep", "num_ctx", "temperature", "top_p"})
            check(!builtin_json.find(field), "Unset generation control was serialized");
        check(read_ai_settings(json::parse("{\"num_predict\":null,\"num_keep\":null,\"num_ctx\":null,\"temperature\":null,\"top_p\":null}"), true) == AiSettings{},
            "Explicit null generation controls were not unset");
        for (const auto* bad : {"{\"num_predict\":true}", "{\"num_keep\":\"0\"}", "{\"num_ctx\":1.5}", "{\"temperature\":[]}", "{\"top_p\":false}"})
            malformed([&] { (void)read_ai_settings(json::parse(bad), true); });
        AiSettings bounds; bounds.num_predict = -1; bounds.num_keep = -1; bounds.num_ctx = 1; bounds.temperature = 0; bounds.top_p = 0.0001;
        check(read_ai_settings(ai_settings_json(bounds), true) == bounds, "Explicit supported lower generation bounds were lost");
        bounds.num_predict = 1000000; bounds.num_keep = 4000000; bounds.num_ctx = 4000000; bounds.temperature = 2; bounds.top_p = 1;
        check(read_ai_settings(ai_settings_json(bounds), true) == bounds, "Explicit supported upper generation bounds were lost");
        for (const int invalid : {-2, 0, 1000001}) { auto bad = bounds; bad.num_predict = invalid; fails(FileFailure::limit, [&] { validate_ai_settings(bad); }); }
        for (const int invalid : {-2, 4000001}) { auto bad = bounds; bad.num_keep = invalid; fails(FileFailure::limit, [&] { validate_ai_settings(bad); }); }
        for (const int invalid : {0, 4000001}) { auto bad = bounds; bad.num_ctx = invalid; fails(FileFailure::limit, [&] { validate_ai_settings(bad); }); }
        for (const double invalid : {-0.001, 2.001, std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::infinity()}) {
            auto bad = bounds; bad.temperature = invalid; fails(FileFailure::limit, [&] { validate_ai_settings(bad); });
        }
        for (const double invalid : {0.0, 1.001, std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::infinity()}) {
            auto bad = bounds; bad.top_p = invalid; fails(FileFailure::limit, [&] { validate_ai_settings(bad); });
        }
        fails(FileFailure::invalid_path, [&] { AiPreferences relative("relative-config"); });
        fails(FileFailure::invalid_path, [&] { AiPreferences traversal(root / ".." / "outside"); });
        const auto minimal_config = root / "minimal-config";
        std::filesystem::create_directory(minimal_config);
        raw_write(minimal_config / "ai-defaults.json", "{\"version\":2,\"configured_models\":[]}\n");
        AiPreferences minimal(minimal_config);
        check(!minimal.defaults() && minimal.configured_models().empty() && !minimal.tutorial_mode() && !minimal.developer_mode() && minimal.right_sidebar_visible() && minimal.openrouter_guardrail_id().empty(),
            "Missing optional application preferences did not use their defaults");
        const auto sidebar_config = root / "sidebar-config";
        AiPreferences sidebar(sidebar_config); sidebar.set_right_sidebar_visible(false);
        AiPreferences sidebar_restarted(sidebar_config);
        const auto sidebar_document = json::parse(raw_read(sidebar_config / "ai-defaults.json"));
        check(!sidebar_restarted.right_sidebar_visible() && !sidebar_restarted.defaults() && sidebar_restarted.configured_models().empty() &&
            !sidebar_restarted.tutorial_mode() && !sidebar_restarted.developer_mode() && sidebar_restarted.openrouter_guardrail_id().empty() &&
            sidebar_document.find("version")->number() == 2 && !sidebar_document.find("right_sidebar_visible")->boolean() && !sidebar_document.find("ai"),
            "Hiding the sidebar before AI configuration changed independent settings or did not persist");
        sidebar_restarted.set_right_sidebar_visible(true);
        check(AiPreferences(sidebar_config).right_sidebar_visible(), "Showing the sidebar did not persist after restart");

        // Registry and application controls work before selecting active AI
        // settings. They share one checked document but preserve each other.
        const auto catalog_config = root / "catalog-config";
        AiPreferences catalog(catalog_config);
        const std::vector<ConfiguredModel> models{{"openrouter", {}, "vendor/cloud-model", "Shared label"},
            {"ollama", "http://localhost:11434", "local-model", "Shared label"}, {"ollama", "http://localhost:22434", "local-model", {}}};
        auto normalized = models; normalized.back().label = "local-model";
        catalog.save_configured_models(models);
        check(!catalog.defaults() && catalog.configured_models() == normalized && !catalog.tutorial_mode(), "Saving model list created active defaults or lost labels");
        check(!json::parse(raw_read(catalog_config / "ai-defaults.json")).find("ai"), "List-only preference save serialized active AI defaults");
        AiPreferences catalog_restarted(catalog_config);
        check(!catalog_restarted.defaults() && catalog_restarted.configured_models() == normalized, "List-only preferences did not survive restart");
        catalog_restarted.set_right_sidebar_visible(false);
        catalog_restarted.set_tutorial_mode(true); catalog_restarted.save_guardrail_id("guardrail_fixture-123");
        catalog_restarted.set_developer_mode(true);
        check(!catalog_restarted.defaults() && catalog_restarted.configured_models() == normalized && !catalog_restarted.right_sidebar_visible(),
            "Saving application controls changed AI defaults, models or sidebar visibility");
        AiSettings catalog_default; catalog_default.model = "active-model"; catalog_default.num_keep = 0;
        catalog_restarted.save(catalog_default);
        check(catalog_restarted.defaults() == catalog_default && catalog_restarted.configured_models() == normalized && catalog_restarted.tutorial_mode() && catalog_restarted.developer_mode() &&
            !catalog_restarted.right_sidebar_visible() && catalog_restarted.openrouter_guardrail_id() == "guardrail_fixture-123", "Saving AI defaults replaced independent preferences");
        catalog_restarted.save_configured_models({normalized.front()});
        check(catalog_restarted.defaults() == catalog_default && catalog_restarted.configured_models() == std::vector<ConfiguredModel>{normalized.front()} &&
            catalog_restarted.tutorial_mode() && catalog_restarted.developer_mode() && !catalog_restarted.right_sidebar_visible() && catalog_restarted.openrouter_guardrail_id() == "guardrail_fixture-123", "Removing models changed active defaults or application controls");
        AiPreferences catalog_later(catalog_config);
        check(catalog_later.defaults() == catalog_default && catalog_later.configured_models() == catalog_restarted.configured_models() && catalog_later.tutorial_mode() && catalog_later.developer_mode() &&
            !catalog_later.right_sidebar_visible() && catalog_later.openrouter_guardrail_id() == "guardrail_fixture-123", "Independent preferences did not roundtrip");
        const auto catalog_known = raw_read(catalog_config / "ai-defaults.json");
        auto duplicate = normalized.front(); duplicate.label = "Another label";
        fails(FileFailure::invalid_path, [&] { catalog_later.save_configured_models({normalized.front(), duplicate}); });
        fails(FileFailure::invalid_path, [&] { catalog_later.save_configured_models({{"", {}, "model", {}}}); });
        fails(FileFailure::invalid_path, [&] { catalog_later.save_configured_models({{"openrouter", {}, "", {}}}); });
        fails(FileFailure::encoding, [&] { catalog_later.save_configured_models({{"openrouter", {}, "model", std::string("bad\0label", 9)}}); });
        fails(FileFailure::limit, [&] { catalog_later.save_configured_models(std::vector<ConfiguredModel>(129)); });
        std::vector<ConfiguredModel> oversized;
        for (int index = 0; index < 100; ++index) oversized.push_back({"openrouter", {}, "model-" + std::to_string(index), std::string(512, 'x')});
        fails(FileFailure::limit, [&] { catalog_later.save_configured_models(oversized); });
        for (const auto* bad_id : {"../other", "id?token=value", "has space", "https://other.invalid/id"})
            fails(FileFailure::invalid_path, [&] { catalog_later.save_guardrail_id(bad_id); });
        fails(FileFailure::limit, [&] { catalog_later.save_guardrail_id(std::string(129, 'x')); });
        check(raw_read(catalog_config / "ai-defaults.json") == catalog_known && catalog_later.defaults() == catalog_default && catalog_later.tutorial_mode() && !catalog_later.right_sidebar_visible() &&
            catalog_later.openrouter_guardrail_id() == "guardrail_fixture-123", "Rejected registry/guardrail save changed preferences");
        // Stale no-op saves still check ownership; desired equality is no excuse
        // to overwrite a different writer's settings.
        catalog_restarted.set_tutorial_mode(false);
        const auto foreign_catalog = raw_read(catalog_config / "ai-defaults.json");
        fails(FileFailure::conflict, [&] { catalog_later.save_configured_models(catalog_later.configured_models()); });
        fails(FileFailure::conflict, [&] { catalog_later.set_tutorial_mode(true); });
        fails(FileFailure::conflict, [&] { catalog_later.set_developer_mode(false); });
        fails(FileFailure::conflict, [&] { catalog_later.set_right_sidebar_visible(false); });
        fails(FileFailure::conflict, [&] { catalog_later.set_right_sidebar_visible(true); });
        fails(FileFailure::conflict, [&] { catalog_later.save(catalog_default); });
        fails(FileFailure::conflict, [&] { catalog_later.save_guardrail_id("different_id"); });
        check(raw_read(catalog_config / "ai-defaults.json") == foreign_catalog && catalog_later.tutorial_mode() && catalog_later.developer_mode() && !catalog_later.right_sidebar_visible() &&
            catalog_later.openrouter_guardrail_id() == "guardrail_fixture-123", "Conflicting independent save overwrote stored or loaded preferences");
        catalog_restarted.save_guardrail_id(""); catalog_restarted.save_configured_models({});
        AiPreferences cleared(catalog_config);
        check(cleared.configured_models().empty() && cleared.openrouter_guardrail_id().empty() && !cleared.tutorial_mode() && cleared.developer_mode() && !cleared.right_sidebar_visible() && cleared.defaults() == catalog_default,
            "Clearing models or guardrail ID changed active AI settings");
        cleared.set_developer_mode(false);
        AiPreferences ordinary(catalog_config);
        check(!ordinary.developer_mode() && !ordinary.tutorial_mode() && !ordinary.right_sidebar_visible() && ordinary.defaults() == catalog_default,
            "Disabling Developer did not persist independently");
        ordinary.set_right_sidebar_visible(true);
        AiPreferences visible_again(catalog_config);
        check(visible_again.right_sidebar_visible() && !visible_again.developer_mode() && !visible_again.tutorial_mode() &&
            visible_again.defaults() == catalog_default && visible_again.configured_models().empty() && visible_again.openrouter_guardrail_id().empty(),
            "Showing the sidebar changed independent application preferences");
        for (const auto* value : {"null", "1", "\"true\"", "[]"}) {
            const auto bytes = std::string("{\"version\":2,\"configured_models\":[],\"developer_mode\":") + value + "}";
            raw_write(minimal_config / "ai-defaults.json", bytes);
            malformed([&] { AiPreferences invalid_mode(minimal_config); });
            check(raw_read(minimal_config / "ai-defaults.json") == bytes,
                "Malformed Developer mode was silently replaced");
        }
        for (const auto* value : {"null", "0", "1", "\"false\"", "[]", "{}"}) {
            const auto bytes = std::string("{\"version\":2,\"configured_models\":[],\"right_sidebar_visible\":") + value + "}";
            raw_write(minimal_config / "ai-defaults.json", bytes);
            malformed([&] { AiPreferences invalid_sidebar(minimal_config); });
            check(raw_read(minimal_config / "ai-defaults.json") == bytes, "Malformed sidebar visibility was silently replaced");
        }

        const auto legacy_config = root / "legacy-config";
        std::filesystem::create_directory(legacy_config);
        const std::string legacy_bytes = "{\"version\":1,\"ai\":{\"provider\":\"ollama\",\"endpoint\":\"http://localhost:11434\",\"model\":\"legacy-model\",\"num_predict\":-1,\"num_keep\":0,\"num_ctx\":32768,\"temperature\":0.2,\"top_p\":1}}\n";
        raw_write(legacy_config / "ai-defaults.json", legacy_bytes);
        AiPreferences migrated(legacy_config);
        check(migrated.defaults()->num_predict == -1 && migrated.defaults()->num_keep == 0 && migrated.defaults()->num_ctx == 32768 &&
            migrated.defaults()->temperature == 0.2 && migrated.defaults()->top_p == 1 &&
            migrated.configured_models() == std::vector<ConfiguredModel>{{"ollama", "http://localhost:11434", "legacy-model", "legacy-model"}} &&
            !migrated.tutorial_mode() && !migrated.developer_mode() && migrated.right_sidebar_visible() && raw_read(legacy_config / "ai-defaults.json") == legacy_bytes, "Legacy explicit settings or model identity were lost during read-only migration");
        migrated.set_tutorial_mode(true);
        check(AiPreferences(legacy_config).defaults() == migrated.defaults() && AiPreferences(legacy_config).right_sidebar_visible() && json::parse(raw_read(legacy_config / "ai-defaults.json")).find("version")->number() == 2,
            "Legacy preferences did not migrate on explicit save");

        AiSettings first{"ollama", "http://localhost:11434", "first-model", 1536, 512, 64000, 0.35, 0.95, true, true, "auto", "medium", {"trusted-provider/model-route"}, true};
        preferences.save(first);
        check(preferences.defaults() == first && std::filesystem::is_regular_file(config / "ai-defaults.json"), "Explicit Apply did not persist defaults");
        const auto stored = raw_read(config / "ai-defaults.json");
        check(stored.find("api_key") == std::string::npos && stored.find("credential") == std::string::npos && stored.find("draft") == std::string::npos, "Defaults persisted non-settings fields");
        AiPreferences restarted(config);
        check(restarted.defaults() == first, "Defaults did not roundtrip after restart");

        std::filesystem::create_directory(root / "project-one"); std::filesystem::create_directory(root / "project-two");
        Workspace one(root / "project-one"), two(root / "project-two");
        auto inherited = one.new_chat("new.chat.md"); restarted.inherit(inherited.state);
        check(inherited.state.ai == first && !inherited.state.ai_configured, "New chat did not inherit saved app defaults");
        one.save_state(inherited);
        inherited = one.open_chat(inherited.path);
        check(!inherited.state.ai_configured, "Saving inherited settings turned them into an explicit override");
        auto other = two.new_chat("another.chat.md"); restarted.inherit(other.state);
        check(other.state.ai == first, "Defaults were confined to one project");

        // A configured legacy chat has no new marker; its existing model wins.
        one.files().ensure_directory(".tinyenv");
        raw_write(one.root() / "legacy.chat.md", "Legacy configured chat\n");
        raw_write(one.root() / ".tinyenv/legacy.chat.md.state.json", "{\"version\":1,\"ai\":{\"provider\":\"ollama\",\"model\":\"kept-model\"},\"selector\":{}}\n");
        auto legacy = one.open_chat("legacy.chat.md"); restarted.inherit(legacy.state);
        check(legacy.state.ai_configured && legacy.state.ai.model == "kept-model", "Saved legacy chat override was replaced");
        check(legacy.state.selector.research_source == "wikipedia" && legacy.state.selector.research_max_queries == 2 && legacy.state.selector.research_max_results == 3,
            "Legacy implicit research limits changed");
        one.save_state(legacy);
        check(one.open_chat(legacy.path).state.ai_configured, "Legacy override marker was not persisted");

        for (const auto* legacy_ai : {"{\"provider\":\"openrouter\",\"model\":\"\"}", "{\"provider\":\"\",\"model\":\"orphan-model\"}", "{}"}) {
            raw_write(one.root() / "unconfigured.chat.md", "Unconfigured chat\n");
            raw_write(one.root() / ".tinyenv/unconfigured.chat.md.state.json", std::string("{\"version\":1,\"ai\":") + legacy_ai + "}\n");
            auto old = one.open_chat("unconfigured.chat.md"); restarted.inherit(old.state);
            check(!old.state.ai_configured && old.state.ai == first, "An unconfigured legacy chat did not inherit defaults");
        }

        auto second = first; second.model = "next-default"; second.web_search = false; second.temperature = 0.7;
        restarted.save(second); restarted.inherit(inherited.state); restarted.inherit(legacy.state);
        check(inherited.state.ai == second && !inherited.state.ai_configured && legacy.state.ai.model == "kept-model", "Updating defaults replaced an explicit override or left inherited settings stale");
        AiPreferences later_restart(config); later_restart.inherit(other.state);
        check(other.state.ai == second, "Latest defaults were not restored across another restart");
        one.save_state(inherited); inherited = one.open_chat(inherited.path); later_restart.inherit(inherited.state);
        check(inherited.state.ai == second && !inherited.state.ai_configured, "Reopening saved inherited settings lost defaults behavior");

        auto invalid_settings = second; invalid_settings.temperature = 4;
        const auto before_invalid = raw_read(config / "ai-defaults.json");
        fails(FileFailure::limit, [&] { restarted.save(invalid_settings); });
        check(restarted.defaults() == second && raw_read(config / "ai-defaults.json") == before_invalid, "Invalid settings altered loaded defaults");

        // Ordinary concurrent config edits are checked against the loaded bytes.
        const auto known = raw_read(config / "ai-defaults.json");
        raw_write(config / "ai-defaults.json", "{\"version\":1,\"ai\":{\"model\":\"foreign-model\"}}\n");
        fails(FileFailure::conflict, [&] { restarted.save(first); });
        check(raw_read(config / "ai-defaults.json").find("foreign-model") != std::string::npos && restarted.defaults() == second, "Concurrent defaults edit was overwritten");
        raw_write(config / "ai-defaults.json", known);
        for (const auto* bad : {"{", "{\"version\":999,\"ai\":{}}", "{\"version\":1}", "{\"version\":1,\"api_key\":\"test-only\",\"ai\":{}}",
                               "{\"version\":1,\"configured_models\":[],\"ai\":{}}", "{\"version\":1,\"ai\":{\"api_key\":\"test-only\"}}", "{\"version\":1,\"ai\":{\"num_predict\":1.5}}",
                               "{\"version\":2,\"ai\":{}}", "{\"version\":2,\"configured_models\":null}", "{\"version\":2,\"configured_models\":[],\"ai\":null}",
                               "{\"version\":2,\"configured_models\":[],\"tutorial_mode\":\"true\"}", "{\"version\":2,\"configured_models\":[],\"openrouter_guardrail_id\":\"../other\"}",
                               "{\"version\":2,\"configured_models\":[{\"provider\":\"ollama\",\"model\":\"model\",\"api_key\":\"test-only\"}]}",
                               "{\"version\":2,\"configured_models\":[{\"provider\":\"ollama\",\"model\":\"model\"},{\"provider\":\"ollama\",\"model\":\"model\",\"label\":\"different\"}]}"}) {
            raw_write(config / "ai-defaults.json", bad);
            malformed([&] { AiPreferences rejected(config); });
            check(raw_read(config / "ai-defaults.json") == bad, "Malformed preferences were silently replaced");
        }
        raw_write(config / "ai-defaults.json", std::string(32769, ' '));
        fails(FileFailure::limit, [&] { AiPreferences too_large(config); });
        raw_write(config / "ai-defaults.json", known);

#if defined(__unix__) && !defined(__EMSCRIPTEN__)
        std::filesystem::create_directory_symlink(config, root / "config-link");
        fails(FileFailure::invalid_path, [&] { AiPreferences link(root / "config-link"); });
        fails(FileFailure::invalid_path, [&] { AiPreferences ancestor(root / "config-link" / "missing-child"); });
        std::filesystem::rename(config / "ai-defaults.json", config / "real-defaults.json");
        std::filesystem::create_symlink(config / "real-defaults.json", config / "ai-defaults.json");
        fails(FileFailure::invalid_path, [&] { AiPreferences linked_file(config); });
        check(raw_read(config / "real-defaults.json") == known, "Symlink rejection modified its target");
        std::filesystem::remove(config / "ai-defaults.json");
        std::filesystem::rename(config / "real-defaults.json", config / "ai-defaults.json");
        std::filesystem::permissions(config / "ai-defaults.json", std::filesystem::perms::owner_read | std::filesystem::perms::group_read | std::filesystem::perms::others_read);
        AiPreferences read_only(config);
        fails(FileFailure::permission, [&] { read_only.save(first); });
        fails(FileFailure::permission, [&] { read_only.set_right_sidebar_visible(false); });
        check(read_only.right_sidebar_visible() && raw_read(config / "ai-defaults.json") == known,
            "Refused sidebar save changed loaded visibility or the read-only document");
        std::filesystem::permissions(config / "ai-defaults.json", std::filesystem::perms::owner_read | std::filesystem::perms::owner_write);
#endif
        std::cout << "AI preferences checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
