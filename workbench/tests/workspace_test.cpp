#include "core/workspace.hpp"
#include "core/json.hpp"

#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace tinyenv;
using foundation::editor::FileError;
using foundation::editor::FileFailure;
namespace {
void check(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
template<class F> void fails(FileFailure expected, F&& action) {
    try { action(); } catch (const FileError& error) { check(error.code() == expected, "Unexpected file failure category"); return; }
    throw std::runtime_error("Expected file failure");
}
template<class F> void malformed(F&& action) {
    try { action(); } catch (const std::runtime_error&) { return; }
    throw std::runtime_error("Expected malformed data failure");
}
void raw_write(const std::filesystem::path& path, std::string_view text) {
    std::ofstream file(path, std::ios::binary); file.write(text.data(), static_cast<std::streamsize>(text.size()));
    if (!file) throw std::runtime_error("Cannot write test fixture");
}
} // namespace

int main() {
    try {
        const auto root = std::filesystem::temp_directory_path() / ("tinyEnv-workspace-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directory(root);
        struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code error; std::filesystem::remove_all(path, error); } } cleanup{root};
        Workspace workspace(root);
        check(!std::filesystem::exists(root / ".tinyenv") && workspace.chats().empty(), "Opening workspace wrote files");
        raw_write(root / "README.md", "# An ordinary document\n");
        raw_write(root / "notes.markdown", "Ordinary notes\n");
        check(workspace.chats().empty() && !Workspace::is_chat_path("README.md") && !Workspace::is_chat_path("notes.markdown") &&
            Workspace::is_chat_path("sample.chat.md") && Workspace::is_chat_path("SAMPLE.CHAT.MD"), "Ordinary Markdown was classified as a chat");
        fails(FileFailure::invalid_path, [&] { (void)workspace.open_chat("README.md"); });
        fails(FileFailure::invalid_path, [&] { (void)workspace.new_chat("document.md"); });
        fails(FileFailure::invalid_path, [&] { (void)Workspace::state_path("README.md"); });
        const std::string markdown = "\xef\xbb\xbf# Research café\r\n\r\nText remains ordinary Markdown.\r\n";
        auto chat = workspace.new_chat("chats/first.chat.md", markdown);
        check(chat.text == markdown && chat.state.cwd == "chats", "New chat changed bytes or cwd");
        check(!std::filesystem::exists(root / "chats/.tinyenv"), "New chat eagerly created state");
        chat.state.draft = "Review the hypothesis\n"; chat.state.pseudocode = "repeat 3 { ask \"check\" }";
        chat.state.selector.deep_research = true;
        chat.state.selector.scribbles = {{"knowledge/expertise.md", true}, {"external library", false}};
        chat.state.selector.refs = {{"examples/source", true}}; chat.state.selector.tools = {{"builtinTools/Web Search", false}};
        chat.state.ai = {"ollama", "http://localhost:11434", "local-model", 1536, 512, 64000, 0.35, 0.95, false, true, "auto", "medium", {"trusted-provider/model-route"}, true};
        chat.state.ai_configured = true;
        chat.state.selector.research_max_queries = 7; chat.state.selector.research_max_results = 11;
        chat.state.selector.research_source = "kiwix"; chat.state.selector.kiwix_index = "offline/local-index.json";
        chat.state.selector.context_max_kib = 4096;
        chat.state.sources_json = json::stringify(json::Value::Array{
            json::Value::Object{{"title", "Offline source"}, {"url", "local:manual"}, {"kind", "local-man"}},
            json::Value::Object{{"title", "Synthetic search excerpt"}, {"url", "https://docs.example.com/reference?q=files"}, {"kind", "web-search"},
                {"metadata", json::Value::Object{{"search_excerpt", true}, {"search_provider", "duckduckgo"}, {"query", "file reference"}}}}});
        chat.state.agentic = true; chat.state.split_chat = true; chat.state.left_tab = "Files"; chat.state.center_tab = "Pseudocode Editor"; chat.state.right_tab = "AI";
        workspace.save(chat);
        Workspace reopened(root);
        auto loaded = reopened.open_chat("chats/first.chat.md");
        check(loaded.text == markdown && loaded.state == chat.state, "Chat or independent window state did not roundtrip");
        check(loaded.state_original.text.find("api_key") == std::string::npos, "Sidecar included an API key field");
        auto other = workspace.new_chat("second.chat.md", "# Second\n");
        check(other.state.draft.empty() && !other.state.agentic && other.state.ai.model.empty() && other.state.cwd == ".", "New chat inherited another chat's window state");
        check(other.state.selector.research_max_queries == 8 && other.state.selector.research_max_results == 24 && other.state.selector.research_source == "web" && other.state.selector.kiwix_index.empty() && other.state.ai.routing_providers.empty() && !other.state.ai.zdr, "New chat lost interactive provider/research defaults");
        check(other.state.selector.context_max_kib == 256, "New chat lost conservative context default");
        check(!other.state.ai.num_predict && !other.state.ai.num_keep && !other.state.ai.num_ctx && !other.state.ai.temperature && !other.state.ai.top_p,
            "New chat acquired explicit generation defaults");
        workspace.save_state(other);
        const auto empty_state = json::parse(other.state_original.text);
        for (const auto* field : {"num_predict", "num_keep", "num_ctx", "temperature", "top_p"})
            check(!empty_state.find("ai")->find(field), "Unset chat generation settings were serialized");
        check(workspace.open_chat(other.path).state == other.state, "Unset chat generation settings did not roundtrip");
        const auto found = workspace.chats();
        check(found.size() == 2 && found[0] == "chats/first.chat.md" && found[1] == "second.chat.md", "Explicit chat discovery failed");
        fails(FileFailure::conflict, [&] { (void)workspace.new_chat("second.chat.md", "overwrite"); });
        fails(FileFailure::invalid_path, [&] { (void)workspace.new_chat("../outside.chat.md"); });
        fails(FileFailure::invalid_path, [&] { (void)workspace.new_chat("commands.sh"); });
        fails(FileFailure::invalid_path, [&] { (void)workspace.new_chat(".git/chat.chat.md"); });
        const auto long_name = std::string(247, 'x') + ".chat.md";
        auto long_chat = workspace.new_chat(long_name, "Long filename\n");
        workspace.save_state(long_chat);
        check(long_chat.state_original.path.filename().string().size() == 75 && workspace.open_chat(long_name).text == "Long filename\n", "Long chat name created an overlong sidecar");
        std::filesystem::remove(root / long_name); std::filesystem::remove(root / long_chat.state_original.path);
        workspace.files().ensure_directory("orphans/.tinyenv");
        raw_write(root / "orphans/.tinyenv/old.chat.md.state.json", "{\"version\":1,\"draft\":\"orphan\"}");
        fails(FileFailure::conflict, [&] { (void)workspace.new_chat("orphans/old.chat.md", "replacement"); });
        check(!std::filesystem::exists(root / "orphans/old.chat.md"), "Orphan state conflict left a new chat behind");
        raw_write(root / "nul.chat.md", std::string("text\0hidden", 11));
        fails(FileFailure::encoding, [&] { (void)workspace.open_chat("nul.chat.md"); });
        std::filesystem::remove(root / "nul.chat.md");
        loaded.text = "unsaved chat"; raw_write(root / loaded.path, "foreign chat");
        fails(FileFailure::conflict, [&] { reopened.save(loaded); });
        check(loaded.text == "unsaved chat" && workspace.files().read(loaded.path).text == "foreign chat", "Conflict lost edits or clobbered foreign text");
        loaded = reopened.open_chat(loaded.path); loaded.text = "pending text";
        raw_write(root / loaded.state_original.path, "{\"version\":1,\"draft\":\"foreign state\"}\n");
        fails(FileFailure::conflict, [&] { reopened.save(loaded); });
        check(workspace.files().read(loaded.path).text == "foreign chat", "State conflict allowed chat text to be changed");
        loaded = reopened.open_chat(loaded.path); loaded.state.ai.temperature = 4;
        fails(FileFailure::limit, [&] { reopened.save_state(loaded); });
        loaded.state.ai.temperature = 0.2; loaded.state.selector.scribbles = {{"same", true}, {"same", false}};
        fails(FileFailure::invalid_path, [&] { reopened.save_state(loaded); });
        loaded.state.selector.scribbles.clear(); loaded.state.sources_json = "{}";
        malformed([&] { reopened.save_state(loaded); });
        loaded.state.sources_json = "[]";
        raw_write(root / loaded.state_original.path, "{\"version\":1,\"cwd\":\"../outside\"}");
        fails(FileFailure::invalid_path, [&] { (void)reopened.open_chat(loaded.path); });
        raw_write(root / loaded.state_original.path, "{\"version\":999}");
        malformed([&] { (void)reopened.open_chat(loaded.path); });

        auto validation = workspace.open_chat("second.chat.md");
        for (const int limit : {1, 16384}) {
            validation.state.selector.context_max_kib = limit; workspace.save_state(validation);
            check(workspace.open_chat(validation.path).state.selector.context_max_kib == limit, "Context limit did not roundtrip at supported boundary");
        }
        for (const int bad : {0, 16385}) { validation.state.selector.context_max_kib = bad; fails(FileFailure::limit, [&] { workspace.save_state(validation); }); }
        validation.state.selector.context_max_kib = 256;
        validation.state.selector.research_max_queries = 1000; validation.state.selector.research_max_results = 3000;
        for (const auto* source : {"web", "wikipedia", "stackoverflow", "local", "kiwix"}) {
            validation.state.selector.research_source = source; workspace.save_state(validation);
            check(workspace.open_chat(validation.path).state == validation.state, "Research configuration did not roundtrip");
        }
        for (const int bad : {0, 1001}) { validation.state.selector.research_max_queries = bad; fails(FileFailure::limit, [&] { workspace.save_state(validation); }); }
        validation.state.selector.research_max_queries = 2;
        for (const int bad : {0, 3001}) { validation.state.selector.research_max_results = bad; fails(FileFailure::limit, [&] { workspace.save_state(validation); }); }
        validation.state.selector.research_max_results = 3; validation.state.selector.research_source = "https://unapproved.invalid";
        fails(FileFailure::invalid_path, [&] { workspace.save_state(validation); });
        validation.state.selector.research_source = "wikipedia";
        for (const auto* route : {"bad route", "--script", "trusted?api_key=secret"}) {
            validation.state.ai.routing_providers = {route}; fails(FileFailure::invalid_path, [&] { workspace.save_state(validation); });
        }
        validation.state.ai.routing_providers = {"trusted", "trusted"};
        fails(FileFailure::invalid_path, [&] { workspace.save_state(validation); });
        validation.state.ai.routing_providers = {"a", "b", "c", "d", "e", "f", "g", "h", "i"};
        fails(FileFailure::limit, [&] { workspace.save_state(validation); });
        validation.state.ai.routing_providers.clear();
        for (const auto* metadata : {"[{\"api_key\":\"private\"}]", "[{\"text\":\"full source\"}]", "[{\"metadata\":{\"authorization\":\"private\"}}]"}) {
            validation.state.sources_json = metadata; fails(FileFailure::invalid_path, [&] { workspace.save_state(validation); });
        }

        check(workspace.snippets("Prompts").empty(), "Absent snippet collection was not empty");
        const std::vector<Snippet> prompts{{"critique", "Critique a hypothesis", "Identify unresolved doubts.\n"}, {"support", "Support", "State the evidence café."}};
        workspace.save_snippets(SnippetKind::prompts, prompts);
        check(reopened.snippets("prompts") == prompts, "Prompt snippets did not persist");
        const std::vector<Snippet> loops{{"repeat", "Repeat until reviewed", "repeat 3 {\n  ask \"check\"\n}\n"}};
        workspace.save_snippets("Pseudocode", loops);
        check(reopened.snippets(SnippetKind::pseudocode) == loops && reopened.snippets("Prompts") == prompts, "Snippet collections were mixed");
        malformed([&] { workspace.save_snippets("unknown", {}); });
        fails(FileFailure::invalid_path, [&] { workspace.save_snippets("Prompts", {{"x", "First", "text"}, {"x", "Second", "text"}}); });
        (void)reopened.snippets("Prompts");
        raw_write(root / ".tinyenv/prompts.json", "{\"version\":1,\"snippets\":[]}");
        fails(FileFailure::conflict, [&] { reopened.save_snippets("Prompts", prompts); });
        check(workspace.files().read(".tinyenv/prompts.json").text.find("\"snippets\":[]") != std::string::npos, "Snippet conflict overwrote foreign collection");

        workspace.files().ensure_directory(".git"); workspace.files().ensure_directory(".ssh"); workspace.files().ensure_directory("files/sub");
        raw_write(root / ".git/hidden.chat.md", "not a chat"); raw_write(root / ".ssh/private.chat.md", "not a chat"); raw_write(root / ".env.fixture", "PRIVATE=test");
        raw_write(root / "files/a.bin", "12345"); raw_write(root / "files/sub/b.bin", "1234567");
        std::filesystem::create_directory_symlink(root / "files", root / "alias");
        std::filesystem::create_symlink(root / "second.chat.md", root / "linked.chat.md");
        const auto entries = workspace.children();
        check(std::any_of(entries.begin(), entries.end(), [](const auto& entry) { return entry.name == "alias" && entry.symlink; }), "File browser did not identify symlink");
        check(std::any_of(entries.begin(), entries.end(), [](const auto& entry) { return entry.name == ".git" && entry.directory; }), "File browser hid Git directory");
        check(std::none_of(entries.begin(), entries.end(), [](const auto& entry) { return entry.name == ".ssh" || entry.name == ".env.fixture" || entry.name == ".tinyenv"; }), "File browser exposed credentials or private state");
        check(workspace.chats().size() == 2, "Chat discovery followed symlinks or private directory");
        fails(FileFailure::invalid_path, [&] { (void)workspace.open_chat("linked.chat.md"); });
        malformed([&] { (void)workspace.children("alias"); });
        const auto usage = workspace.disk_usage("files");
        check(usage.total_bytes == 12 && usage.entries.size() == 2 && usage.entries[0].name == "sub" && usage.entries[0].bytes == 7 && !usage.truncated, "Disk usage did not aggregate immediate children");
        const auto limited = workspace.disk_usage("files", 1);
        check(limited.visited == 1 && limited.truncated, "Disk traversal did not report partial results");
        fails(FileFailure::limit, [&] { (void)workspace.children(".", 1); });
        fails(FileFailure::limit, [&] { (void)workspace.chats(1); });
        fails(FileFailure::limit, [&] { (void)workspace.chats(0); });
        fails(FileFailure::limit, [&] { (void)workspace.disk_usage(".", Workspace::maximum_scan_entries + 1); });

        // File operations use actual ordinary entries, with no text decoding of
        // binary/large files, no overwrite and kernel-enforced empty rmdir.
        workspace.create_directory("operations");
        workspace.create_file("operations/plain.md", "A document\n");
        workspace.create_file("operations/fresh.chat.md", "# Fresh\n");
        check(workspace.files().read("operations/plain.md").text == "A document\n" &&
            workspace.open_chat("operations/fresh.chat.md").text == "# Fresh\n", "File creation did not preserve type or bytes");
        fails(FileFailure::conflict, [&] { workspace.create_file("operations/plain.md"); });
        fails(FileFailure::conflict, [&] { workspace.create_directory("operations"); });
        fails(FileFailure::missing, [&] { workspace.create_file("missing-parent/child.txt"); });
        fails(FileFailure::missing, [&] { workspace.create_directory("missing-parent/child"); });
        check(!std::filesystem::exists(root / "missing-parent"), "File-manager creation made implicit parents");
        const auto plain_original = workspace.files().read("operations/plain.md");
        workspace.copy_entry("operations/plain.md", "operations/copied.md");
        const auto plain_after_copy = workspace.files().read("operations/plain.md");
        check(workspace.files().read("operations/copied.md").text == plain_original.text &&
            plain_after_copy.text == plain_original.text && plain_after_copy.identity == plain_original.identity,
            "Text copy changed bytes or the source identity");
        fails(FileFailure::conflict, [&] { workspace.copy_entry("operations/plain.md", "operations/copied.md"); });
        fails(FileFailure::conflict, [&] { workspace.copy_entry("operations/plain.md", "operations/plain.md"); });
        fails(FileFailure::conflict, [&] { workspace.copy_entry("operations/plain.md", "operations"); });
        fails(FileFailure::missing, [&] { workspace.copy_entry("operations/plain.md", "missing-parent/copied.md"); });
        fails(FileFailure::missing, [&] { workspace.copy_entry("operations/missing.md", "operations/missing-copy.md"); });
        fails(FileFailure::invalid_path, [&] { workspace.copy_entry("operations", "copied-directory"); });
        check(!std::filesystem::exists(root / "missing-parent") && !std::filesystem::exists(root / "operations/missing-copy.md") &&
            !std::filesystem::exists(root / "copied-directory"), "Invalid copy created a destination or parent");
        workspace.copy_entry("operations/fresh.chat.md", "operations/fresh-copy.CHAT.MD");
        const auto fresh_copy = workspace.open_chat("operations/fresh-copy.CHAT.MD");
        check(fresh_copy.text == "# Fresh\n" && fresh_copy.state.draft.empty() && fresh_copy.state.cwd == "operations" &&
            !fresh_copy.state_original.identity.exists, "Copy invented state for an untouched chat");
        workspace.remove_entry(fresh_copy.path);
        raw_write(root / "operations/binary.bin", std::string("binary\0\xff", 8));
        fails(FileFailure::encoding, [&] { workspace.copy_entry("operations/binary.bin", "operations/binary-copy.bin"); });
        raw_write(root / "operations/nul.txt", std::string("text\0hidden", 11));
        fails(FileFailure::encoding, [&] { workspace.copy_entry("operations/nul.txt", "operations/nul-copy.txt"); });
        raw_write(root / "operations/large.txt", "x");
        std::filesystem::resize_file(root / "operations/large.txt", workspace.files().max_bytes() + 1);
        fails(FileFailure::limit, [&] { workspace.copy_entry("operations/large.txt", "operations/large-copy.txt"); });
        check(!std::filesystem::exists(root / "operations/binary-copy.bin") && !std::filesystem::exists(root / "operations/nul-copy.txt") &&
            !std::filesystem::exists(root / "operations/large-copy.txt"),
            "Unsupported text copy left a partial output");
        workspace.remove_entry("operations/large.txt");
        workspace.create_directory("readonly-copy");
        std::filesystem::permissions(root / "readonly-copy", std::filesystem::perms::owner_read | std::filesystem::perms::owner_exec);
        fails(FileFailure::permission, [&] { workspace.copy_entry("operations/plain.md", "readonly-copy/copied.md"); });
        check(!std::filesystem::exists(root / "readonly-copy/copied.md"), "Read-only destination left copied text");
        std::filesystem::permissions(root / "readonly-copy", std::filesystem::perms::owner_all);
        workspace.rename_entry("operations/binary.bin", "operations/renamed.bin");
        check(std::filesystem::file_size(root / "operations/renamed.bin") == 8, "Binary rename decoded or changed the file");
        fails(FileFailure::conflict, [&] { workspace.rename_entry("operations/renamed.bin", "operations/plain.md"); });
        check(std::filesystem::exists(root / "operations/renamed.bin") && workspace.files().read("operations/plain.md").text == "A document\n", "Rename replaced a destination");
        workspace.remove_entry("operations/renamed.bin");
        check(!std::filesystem::exists(root / "operations/renamed.bin"), "Binary file deletion failed");
        fails(FileFailure::conflict, [&] { workspace.remove_entry("operations"); });
        check(std::filesystem::exists(root / "operations/plain.md") && std::filesystem::exists(root / "operations/fresh.chat.md"), "Nonempty directory deletion removed descendants");
        workspace.create_directory("operations/empty"); workspace.remove_entry("operations/empty");
        check(!std::filesystem::exists(root / "operations/empty"), "Empty directory deletion failed");
        for (const auto* path : {".", "../outside", ".git", ".tinyenv", ".env.local", ".codex/item", "operations/.tinyenv/item", ".foundation-editor-journal"}) {
            fails(FileFailure::invalid_path, [&] { workspace.remove_entry(path); });
            fails(FileFailure::invalid_path, [&] { workspace.create_file(path); });
            fails(FileFailure::invalid_path, [&] { workspace.create_directory(path); });
            fails(FileFailure::invalid_path, [&] { workspace.rename_entry("operations/plain.md", path); });
            fails(FileFailure::invalid_path, [&] { workspace.copy_entry("operations/plain.md", path); });
            fails(FileFailure::invalid_path, [&] { workspace.copy_entry(path, "operations/private-copy.md"); });
        }
        std::filesystem::create_symlink(root / "operations/plain.md", root / "operations/link.md");
        for (const auto* path : {"operations/link.md", "alias/a.bin"}) {
            fails(FileFailure::invalid_path, [&] { workspace.remove_entry(path); });
            fails(FileFailure::invalid_path, [&] { workspace.rename_entry(path, "operations/unlinked.md"); });
            fails(FileFailure::invalid_path, [&] { workspace.create_file(path); });
            fails(FileFailure::invalid_path, [&] { workspace.copy_entry(path, "operations/unlinked.md"); });
        }
        fails(FileFailure::conflict, [&] { workspace.rename_entry("operations/plain.md", "operations/link.md"); });
        fails(FileFailure::conflict, [&] { workspace.copy_entry("operations/plain.md", "operations/link.md"); });
        fails(FileFailure::invalid_path, [&] { workspace.copy_entry("operations/plain.md", "alias/copied.md"); });
        check(!std::filesystem::exists(root / "operations/unlinked.md") && !std::filesystem::exists(root / "files/copied.md"), "Copy followed a symlink");
        check(workspace.files().read("operations/plain.md").text == "A document\n" && std::filesystem::is_symlink(root / "operations/link.md"), "Symlink refusal changed a referent or link");

        auto managed = workspace.open_chat("operations/fresh.chat.md"); managed.state.draft = "Keep this draft";
        managed.state.pseudocode = "agent writer: Preserve the flow."; managed.state.ai.model = "saved-model"; managed.state.ai_configured = true;
        managed.state.selector.refs = {{"saved-reference", true}}; workspace.save_state(managed);
        const auto managed_text = managed.original, managed_state = managed.state_original;
        workspace.create_directory("copy-target");
        workspace.copy_entry(managed.path, "copy-target/copied.chat.md");
        auto managed_copy = workspace.open_chat("copy-target/copied.chat.md");
        check(managed_copy.text == managed.text && managed_copy.state == managed.state &&
            managed_copy.original.path == managed_copy.path && managed_copy.state_original.path == Workspace::state_path(managed_copy.path) &&
            managed_copy.original.identity.object != managed.original.identity.object &&
            managed_copy.state_original.identity.object != managed.state_original.identity.object,
            "Chat copy lost saved settings or shared file identity with its source");
        managed_copy.text = "# Independent copy\n"; managed_copy.state.draft = "A separate draft"; workspace.save(managed_copy);
        const auto managed_after_copy = workspace.open_chat(managed.path);
        check(managed_after_copy.original.identity == managed_text.identity && managed_after_copy.text == managed_text.text &&
            managed_after_copy.state_original.identity == managed_state.identity && managed_after_copy.state_original.text == managed_state.text,
            "Saving the copied chat changed source text, history or state");
        workspace.remove_entry(managed_copy.path);
        fails(FileFailure::invalid_path, [&] { workspace.copy_entry(managed.path, "operations/chat-copy.md"); });
        workspace.files().ensure_directory("readonly-copy/.tinyenv");
        std::filesystem::permissions(root / "readonly-copy/.tinyenv", std::filesystem::perms::owner_read | std::filesystem::perms::owner_exec);
        fails(FileFailure::permission, [&] { workspace.copy_entry(managed.path, "readonly-copy/copied.chat.md"); });
        check(!std::filesystem::exists(root / "readonly-copy/copied.chat.md"), "Read-only companion directory left copied chat text");
        std::filesystem::permissions(root / "readonly-copy/.tinyenv", std::filesystem::perms::owner_all);
        workspace.create_directory("unsafe-copy-target");
        std::filesystem::create_directory_symlink(root / "operations/.tinyenv", root / "unsafe-copy-target/.tinyenv");
        fails(FileFailure::invalid_path, [&] { workspace.copy_entry(managed.path, "unsafe-copy-target/copied.chat.md"); });
        check(!std::filesystem::exists(root / "unsafe-copy-target/copied.chat.md"), "Unsafe companion parent left copied chat text");
        workspace.rename_entry("operations/fresh.chat.md", "operations/renamed.chat.md");
        const auto renamed = workspace.open_chat("operations/renamed.chat.md");
        check(renamed.state.draft == "Keep this draft" && !std::filesystem::exists(root / managed.path) &&
            !std::filesystem::exists(root / managed.state_original.path), "Chat rename stranded its companion state");
        fails(FileFailure::invalid_path, [&] { workspace.rename_entry("operations/renamed.chat.md", "operations/renamed.md"); });
        raw_write(root / "operations/.tinyenv/orphan.chat.md.state.json", "{\"version\":1}");
        fails(FileFailure::conflict, [&] { workspace.rename_entry("operations/renamed.chat.md", "operations/orphan.chat.md"); });
        fails(FileFailure::conflict, [&] { workspace.create_file("operations/orphan.chat.md"); });
        fails(FileFailure::conflict, [&] { workspace.copy_entry("operations/renamed.chat.md", "operations/orphan.chat.md"); });
        check(!std::filesystem::exists(root / "operations/orphan.chat.md"), "Companion conflict left copied chat text");
        check(workspace.open_chat("operations/renamed.chat.md").state.draft == "Keep this draft", "Destination sidecar conflict altered source state");
        workspace.remove_entry("operations/renamed.chat.md");
        check(!std::filesystem::exists(root / renamed.path) && !std::filesystem::exists(root / renamed.state_original.path), "Chat deletion left its companion state behind");
        workspace.create_file("operations/legacy.md", "# Legacy chat\n");
        raw_write(root / "operations/.tinyenv/legacy.md.state.json", "{\"version\":1,\"draft\":\"Legacy draft\"}");
        workspace.rename_entry("operations/legacy.md", "operations/migrated.chat.md");
        check(workspace.open_chat("operations/migrated.chat.md").state.draft == "Legacy draft" &&
            !std::filesystem::exists(root / "operations/.tinyenv/legacy.md.state.json"), "Explicit legacy migration discarded state");
        const auto managed_long_name = "operations/" + std::string(247, 'z') + ".chat.md";
        auto long_managed = workspace.new_chat(managed_long_name, "# Long chat\n"); long_managed.state.draft = "Long draft"; workspace.save_state(long_managed);
        const auto long_copy_name = "operations/" + std::string(247, 'y') + ".chat.md";
        workspace.copy_entry(managed_long_name, long_copy_name);
        const auto long_copy = workspace.open_chat(long_copy_name);
        check(long_copy.state.draft == "Long draft" && long_copy.state_original.path != long_managed.state_original.path &&
            long_copy.state_original.path.filename().string().size() == 75, "Long-name chat copy lost its independent hashed state");
        workspace.remove_entry(long_copy_name);
        workspace.rename_entry(managed_long_name, "operations/short.chat.md");
        check(workspace.open_chat("operations/short.chat.md").state.draft == "Long draft" &&
            !std::filesystem::exists(root / long_managed.state_original.path), "Hashed-sidecar rename lost state");
        workspace.remove_entry("operations/short.chat.md");
        workspace.create_directory("folder"); workspace.create_file("folder/document.md", "move me");
        auto folder_chat = workspace.new_chat("folder/history.chat.md", "# History\n"); folder_chat.state.draft = "Folder draft"; workspace.save_state(folder_chat);
        fails(FileFailure::invalid_path, [&] { workspace.rename_entry("folder", "folder/inside"); });
        workspace.rename_entry("folder", "renamed-folder");
        check(!std::filesystem::exists(root / "folder") && workspace.files().read("renamed-folder/document.md").text == "move me" &&
            workspace.open_chat("renamed-folder/history.chat.md").state.draft == "Folder draft" &&
            workspace.open_chat("renamed-folder/history.chat.md").state.cwd == "renamed-folder", "Nonempty directory rename lost layout/state or left an unusable cwd");
        fails(FileFailure::conflict, [&] { workspace.remove_entry("renamed-folder"); });
        auto unsafe_chat = workspace.new_chat("operations/unsafe.chat.md", "preserve me");
        std::filesystem::create_symlink(root / "README.md", root / "operations/.tinyenv/unsafe.chat.md.state.json");
        fails(FileFailure::invalid_path, [&] { workspace.remove_entry(unsafe_chat.path); });
        fails(FileFailure::invalid_path, [&] { workspace.rename_entry(unsafe_chat.path, "operations/moved.chat.md"); });
        fails(FileFailure::invalid_path, [&] { workspace.copy_entry(unsafe_chat.path, "operations/unsafe-copy.chat.md"); });
        check(!std::filesystem::exists(root / "operations/unsafe-copy.chat.md"), "Unsafe source state left copied chat text");
        check(workspace.files().read(unsafe_chat.path).text == "preserve me", "Unsafe companion rejection changed chat text");
        auto invalid_state = workspace.new_chat("operations/invalid-state.chat.md", "preserve invalid state\n");
        raw_write(root / invalid_state.state_original.path, "{\"version\":999}\n");
        malformed([&] { workspace.copy_entry(invalid_state.path, "operations/invalid-state-copy.chat.md"); });
        check(!std::filesystem::exists(root / "operations/invalid-state-copy.chat.md"), "Malformed source state left copied chat text");
        auto invalid_cwd = workspace.new_chat("operations/cwd.chat.md", "# Cwd\n"); workspace.save_state(invalid_cwd);
        raw_write(root / invalid_cwd.state_original.path, "{\"version\":1,\"cwd\":\"missing-directory\"}");
        check(workspace.open_chat(invalid_cwd.path).state.cwd == "operations", "Missing saved cwd did not recover to chat directory");
        for (const auto* cwd : {"../outside", "alias"}) {
            raw_write(root / invalid_cwd.state_original.path, json::stringify(json::Value::Object{{"version", 1}, {"cwd", cwd}}));
            fails(FileFailure::invalid_path, [&] { (void)workspace.open_chat(invalid_cwd.path); });
        }

        // Explicit legacy values stay explicit; missing or null controls mean
        // provider defaults, including after a state save and another reopen.
        auto legacy_generation = workspace.new_chat("legacy-generation.chat.md", "# Legacy generation\n");
        raw_write(root / legacy_generation.state_original.path,
            "{\"version\":1,\"ai\":{\"provider\":\"ollama\",\"model\":\"legacy-model\",\"num_predict\":2048,\"num_keep\":0,\"num_ctx\":32768,\"temperature\":0.2,\"top_p\":1}}\n");
        legacy_generation = workspace.open_chat(legacy_generation.path);
        check(legacy_generation.state.ai_configured && legacy_generation.state.ai.num_predict == 2048 && legacy_generation.state.ai.num_keep == 0 &&
            legacy_generation.state.ai.num_ctx == 32768 && legacy_generation.state.ai.temperature == 0.2 && legacy_generation.state.ai.top_p == 1,
            "Legacy explicit chat generation settings were replaced");
        workspace.save_state(legacy_generation);
        check(workspace.open_chat(legacy_generation.path).state == legacy_generation.state, "Legacy explicit generation settings changed on save");
        raw_write(root / legacy_generation.state_original.path,
            "{\"version\":1,\"ai\":{\"provider\":\"ollama\",\"model\":\"legacy-model\",\"num_predict\":null,\"num_keep\":null,\"temperature\":null}}\n");
        legacy_generation = workspace.open_chat(legacy_generation.path);
        check(!legacy_generation.state.ai.num_predict && !legacy_generation.state.ai.num_keep && !legacy_generation.state.ai.num_ctx &&
            !legacy_generation.state.ai.temperature && !legacy_generation.state.ai.top_p, "Missing or null chat generation settings acquired numeric defaults");
        workspace.save_state(legacy_generation);
        check(workspace.open_chat(legacy_generation.path).state == legacy_generation.state, "Cleared generation settings did not survive a state save");
        for (const auto* bad : {"{\"num_predict\":true}", "{\"num_keep\":1.5}", "{\"temperature\":\"0.2\"}"}) {
            raw_write(root / legacy_generation.state_original.path, std::string("{\"version\":1,\"ai\":") + bad + "}\n");
            malformed([&] { (void)workspace.open_chat(legacy_generation.path); });
        }

        const auto json_value = json::parse("{\"unicode\":\"\\ud83d\\ude00\",\"number\":-1.25e2,\"boolean\":true,\"array\":[null,\"x\"]}");
        check(json_value.find("unicode")->string() == "😀" && json_value.find("number")->number() == -125 && json_value.find("boolean")->boolean(), "JSON values parsed incorrectly");
        check(json::parse(json::stringify(json_value)).find("array")->array().size() == 2, "JSON serialization did not roundtrip");
        for (const auto* bad : {"{\"x\":1,\"x\":2}", "[1,]", "01", "1e", "NaN", "\"\\ud800\"", "\"\\udc00\"", "\"\\u0000\"", "true false"}) malformed([&] { (void)json::parse(bad); });
        check(json::parse("[[]]", 100, 1).array().size() == 1, "JSON depth rejected a value at the limit");
        malformed([&] { (void)json::parse("[[[]]]", 100, 1); });
        malformed([&] { (void)json::parse("null", 100, 1000000); });
        malformed([&] { (void)json::parse("[1,2,3]", 100, 64, 3); });
        malformed([&] { (void)json::parse("\"too long\"", 3); });
        malformed([&] { (void)json::stringify(json_value, 3); });
        std::cout << "workspace: explicit chats, independent state, checked file operations, snippets, bounded files and JSON passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
