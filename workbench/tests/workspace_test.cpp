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
        check(chat.text == markdown && chat.state.cwd == "chats" && !chat.state.selector.calculations, "New chat changed bytes, cwd or calculation opt-in");
        check(!std::filesystem::exists(root / "chats/.tinyenv"), "New chat eagerly created state");
        chat.state.draft = "Review the hypothesis\n"; chat.state.pseudocode = "repeat 3 { ask \"check\" }";
        chat.state.selector.deep_research = true; chat.state.selector.calculations = true;
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
        const auto loaded_document = json::parse(loaded.state_original.text);
        check(loaded_document.find("version")->number() == 1 && loaded_document.find("selector")->find("calculations")->boolean(),
            "Calculation opt-in changed the chat schema or was not stored as a boolean");
        check(loaded.state_original.text.find("api_key") == std::string::npos, "Sidecar included an API key field");
        auto other = workspace.new_chat("second.chat.md", "# Second\n");
        check(other.state.draft.empty() && !other.state.agentic && other.state.ai.model.empty() && other.state.cwd == ".", "New chat inherited another chat's window state");
        check(other.state.selector.research_max_queries == 8 && other.state.selector.research_max_results == 24 && other.state.selector.research_source == "web" && other.state.selector.kiwix_index.empty() && other.state.ai.routing_providers.empty() && !other.state.ai.zdr, "New chat lost interactive provider/research defaults");
        check(other.state.selector.context_max_kib == 256 && !other.state.selector.calculations, "New chat lost conservative context or calculation defaults");
        check(!other.state.ai.num_predict && !other.state.ai.num_keep && !other.state.ai.num_ctx && !other.state.ai.temperature && !other.state.ai.top_p,
            "New chat acquired explicit generation defaults");
        workspace.save_state(other);
        const auto empty_state = json::parse(other.state_original.text);
        check(!empty_state.find("selector")->find("calculations")->boolean(), "Disabled calculation opt-in was not saved explicitly");
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

        // Old state never grants calculation access. Its other selector defaults
        // remain unchanged, and the new explicit flag survives saving/restart.
        auto calculation_chat = workspace.new_chat("calculations.chat.md", "# Calculations\n");
        for (const auto* legacy_state : {"{\"version\":1}", "{\"version\":1,\"selector\":{}}",
                "{\"version\":1,\"selector\":{\"deep_research\":true,\"research_source\":\"local\",\"research_max_queries\":7,\"research_max_results\":9}}"}) {
            raw_write(root / calculation_chat.state_original.path, legacy_state);
            calculation_chat = workspace.open_chat(calculation_chat.path);
            check(!calculation_chat.state.selector.calculations, "Legacy chat silently enabled calculations");
            if (!json::parse(legacy_state).find("selector"))
                check(calculation_chat.state.selector.research_source == "web" && calculation_chat.state.selector.research_max_queries == 8 &&
                    calculation_chat.state.selector.research_max_results == 24, "Absent legacy selector lost interactive research defaults");
            else if (!calculation_chat.state.selector.deep_research)
                check(calculation_chat.state.selector.research_source == "wikipedia" && calculation_chat.state.selector.research_max_queries == 2 &&
                    calculation_chat.state.selector.research_max_results == 3, "Empty legacy selector lost curated research defaults");
            else
                check(calculation_chat.state.selector.research_source == "local" && calculation_chat.state.selector.research_max_queries == 7 &&
                    calculation_chat.state.selector.research_max_results == 9, "Legacy selector settings changed during calculation migration");
            workspace.save_state(calculation_chat);
            check(Workspace(root).open_chat(calculation_chat.path).state == calculation_chat.state, "Legacy calculation default changed after save/restart");
        }
        for (const bool enabled : {true, false}) {
            calculation_chat.state.selector.calculations = enabled; workspace.save_state(calculation_chat);
            check(Workspace(root).open_chat(calculation_chat.path).state == calculation_chat.state, "Calculation toggle did not survive save/restart");
        }
        for (const auto* bad : {"null", "0", "1", "\"true\"", "[]", "{}"}) {
            const auto bytes = std::string("{\"version\":1,\"selector\":{\"calculations\":") + bad + "}}\n";
            raw_write(root / calculation_chat.state_original.path, bytes);
            malformed([&] { (void)workspace.open_chat(calculation_chat.path); });
            check(workspace.files().read(calculation_chat.state_original.path).text == bytes, "Malformed calculation flag was silently replaced");
        }
        const std::string foreign_calculation_state = "{\"version\":1,\"draft\":\"Foreign draft\",\"selector\":{\"calculations\":false}}\n";
        calculation_chat.state.selector.calculations = true;
        raw_write(root / calculation_chat.state_original.path, foreign_calculation_state);
        fails(FileFailure::conflict, [&] { workspace.save_state(calculation_chat); });
        check(calculation_chat.state.selector.calculations && workspace.files().read(calculation_chat.state_original.path).text == foreign_calculation_state,
            "Calculation save conflict changed the retained opt-in or foreign state");

        // Builder mode and each task belong to the owning chat. Reading state
        // is passive: it preserves a running record for UI recovery to decide.
        auto builder_chat = workspace.new_chat("builder.chat.md", "# Builder owner\n");
        check(builder_chat.state.builder == BuilderState{} && !std::filesystem::exists(root / builder_chat.state_original.path),
            "New chat acquired builder work or eager state");
        raw_write(root / builder_chat.state_original.path, "{\"version\":1,\"draft\":\"Legacy draft\"}\n");
        builder_chat = workspace.open_chat(builder_chat.path);
        check(builder_chat.state.builder == BuilderState{} && builder_chat.state.draft == "Legacy draft", "Legacy chat did not retain passive builder defaults");
        workspace.save_state(builder_chat);
        check(!json::parse(builder_chat.state_original.text).find("builder"), "Unused builder state was serialized into a legacy chat");
        auto& builder = builder_chat.state.builder;
        builder.active = true; builder.tab = "Tasks"; builder.next_task_id = 3;
        builder.fields = {{"builder.paths", "docs\nREADME.md"}, {"builder.kind", "scribbles"}, {"builder.output", ".zzz_compendium/scribbles/project"},
            {"builder.default_output", ".zzz_compendium/scribbles/project"}, {"builder.label", "Local café"}, {"builder.model", ""},
            {"builder.model_choice", ""}, {"builder.small_model", "example/small"}, {"builder.ai", "false"}, {"builder.web", "false"},
            {"builder.evaluation", "false"}, {"builder.kimi_ceiling", "false"}, {"builder.max_calls", "32"}, {"builder.questions", "What is this source?"}};
        BuilderTask build_task;
        build_task.id = "builder.1"; build_task.label = "Local café"; build_task.status = "running"; build_task.phase = "indexing";
        build_task.completed_chunks = 2; build_task.total_chunks = 4; build_task.resumed_chunks = 1;
        build_task.request_json = json::stringify(json::Value::Object{
            {"schema_version", 1}, {"operation", "scribble"}, {"root", root.string()}, {"chat_path", builder_chat.path.generic_string()}, {"prompt", ""},
            {"settings", json::Value::Object{{"provider", "openrouter"}, {"model", ""}, {"network_enabled", false}}},
            {"selector", json::Value::Object{{"deep_research", false}, {"calculations", false}, {"scribbles", json::Value::Array{}}, {"refs", json::Value::Array{}}, {"tools", json::Value::Array{}}}},
            {"input_paths", json::Value::Array{"docs", "README.md"}}, {"allowed_context_paths", json::Value::Array{}}, {"output_dir", ".zzz_compendium/scribbles/project"},
            {"research_source", "web"}, {"research_limits", json::Value::Object{{"max_queries", 2}, {"max_results", 3}}},
            {"context_limits", json::Value::Object{{"max_total_bytes", 262144}, {"max_file_bytes", 262144}, {"max_files", 128}}},
            {"scribble", json::Value::Object{{"ai_enabled", false}, {"label", "Local café"}, {"max_provider_calls", 32}}}});
        BuilderTask evaluation_task;
        evaluation_task.id = "builder.2"; evaluation_task.operation = "evaluate"; evaluation_task.status = "completed"; evaluation_task.label = "Small evaluation";
        evaluation_task.request_json = " { \"operation\": \"evaluate\", \"questions\": [\"What is this source?\"] } ";
        evaluation_task.result_json = json::stringify(json::Value::Object{{"operation", "evaluate"}, {"ok", true}, {"text", "Evaluation complete"},
            {"evaluation", json::Value::Object{{"original_score", 1.0}, {"enriched_score", 1.0}}}, {"omitted", true}});
        builder.tasks = {build_task, evaluation_task}; builder.selected_task = build_task.id;
        workspace.save_state(builder_chat);
        const auto builder_bytes = builder_chat.state_original.text;
        const auto builder_reopened = Workspace(root).open_chat(builder_chat.path);
        check(builder_reopened.state == builder_chat.state && builder_reopened.state.builder.tasks.front().status == "running" &&
            workspace.files().read(builder_chat.state_original.path).text == builder_bytes,
            "Restart altered task records, request text or disk state");
        check(workspace.open_chat("second.chat.md").state.builder == BuilderState{}, "Builder state leaked into another chat");
        for (const auto* tab : {"Setup", "Tasks", "Results"}) {
            builder.tab = tab; workspace.save_state(builder_chat);
            check(Workspace(root).open_chat(builder_chat.path).state.builder == builder, "Builder tab or mode did not survive restart");
        }
        for (const auto* status : {"ready", "running", "paused", "interrupted", "completed", "failed", "cancelled"}) {
            builder.tasks.front().status = status; workspace.save_state(builder_chat);
            check(Workspace(root).open_chat(builder_chat.path).state.builder.tasks.front().status == status, "Builder status did not survive restart");
        }
        const auto valid_builder = builder;
        // UI preflight uses the exact save contract without assigning candidate
        // metadata or touching the checked companion snapshot.
        const auto preflight_snapshot = builder_chat.state_original;
        const auto preflight_bytes = workspace.files().read(builder_chat.state_original.path).text;
        validate_builder_state(valid_builder);
        auto candidate_builder = valid_builder;
        candidate_builder.tasks.front().result_json = "{\"usage\":{\"authorization\":\"synthetic\"}}";
        const auto rejected_candidate = candidate_builder;
        fails(FileFailure::invalid_path, [&] { validate_builder_state(candidate_builder); });
        check(candidate_builder == rejected_candidate, "Builder preflight changed the rejected candidate");
        candidate_builder.tasks.front().result_json = "{\"usage\":[]}";
        malformed([&] { validate_builder_state(candidate_builder); });
        check(builder == valid_builder &&
            builder_chat.state_original.identity == preflight_snapshot.identity && builder_chat.state_original.text == preflight_snapshot.text &&
            workspace.files().read(builder_chat.state_original.path).text == preflight_bytes,
            "Builder preflight changed retained state, snapshot or disk bytes");
        auto reject_builder = [&](FileFailure expected, const auto& change) {
            builder = valid_builder; change(builder); const auto disk = workspace.files().read(builder_chat.state_original.path).text;
            fails(expected, [&] { workspace.save_state(builder_chat); });
            check(workspace.files().read(builder_chat.state_original.path).text == disk, "Invalid builder state replaced a saved sidecar");
        };
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.tab = "Other"; });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.selected_task = "missing"; });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.fields["builder.api_key"] = "synthetic"; });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.tasks.front().operation = "chat"; });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.tasks.front().status = "complete"; });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.tasks.front().id.clear(); });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.tasks.front().id = "../foreign"; });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.tasks.back().id = value.tasks.front().id; });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.tasks.front().request_json = "{\"operation\":\"evaluate\"}"; });
        reject_builder(FileFailure::invalid_path, [](auto& value) { value.tasks.front().result_json = "{\"operation\":\"evaluate\"}"; });
        reject_builder(FileFailure::limit, [](auto& value) { value.next_task_id = 0; });
        reject_builder(FileFailure::limit, [](auto& value) { value.next_task_id = 9007199254740992ULL; });
        reject_builder(FileFailure::limit, [](auto& value) { value.tasks.front().total_chunks = 4097; });
        reject_builder(FileFailure::limit, [](auto& value) { value.tasks.front().completed_chunks = value.tasks.front().total_chunks + 1; });
        reject_builder(FileFailure::limit, [](auto& value) { value.tasks.front().resumed_chunks = value.tasks.front().completed_chunks + 1; });
        reject_builder(FileFailure::limit, [](auto& value) { value.fields["builder.paths"] = std::string(65537, 'x'); });
        reject_builder(FileFailure::limit, [](auto& value) { value.fields["builder.model"] = std::string(4097, 'x'); });
        reject_builder(FileFailure::limit, [](auto& value) { value.tasks.front().request_json = std::string(65537, 'x'); });
        reject_builder(FileFailure::limit, [](auto& value) { value.tasks.front().result_json = std::string(131073, 'x'); });
        reject_builder(FileFailure::limit, [](auto& value) {
            value.tasks.clear(); value.selected_task.clear();
            for (int i = 0; i < 33; ++i) { BuilderTask task; task.id = "task-" + std::to_string(i); value.tasks.push_back(std::move(task)); }
        });
        for (const auto* unsafe : {
            "{\"operation\":\"scribble\",\"settings\":{\"endpoint\":\"https://user:synthetic@openrouter.ai/api/v1\"}}",
            "{\"operation\":\"scribble\",\"settings\":{\"endpoint\":\"https://openrouter.ai/api/v1?api_key=synthetic\"}}",
            "{\"operation\":\"scribble\",\"settings\":{\"endpoint\":\"https://openrouter.ai/api/v1#synthetic\"}}",
            "{\"operation\":\"scribble\",\"settings\":{\"Api-Key\":\"synthetic\"}}",
            "{\"operation\":\"scribble\",\"settings\":{\"provider\":\"openrouter\",\"server_tools\":[]}}",
            "{\"operation\":\"scribble\",\"history\":[]}", "{\"operation\":\"scribble\",\"prompt\":\"Unsent draft\"}",
            "{\"operation\":\"scribble\",\"pseudocode\":\"\"}", "{\"operation\":\"scribble\",\"images\":[]}",
            "{\"operation\":\"scribble\",\"selector\":{\"calculations\":true}}",
            "{\"operation\":\"scribble\",\"selector\":{\"tools\":[{\"path\":\"tool.json\"}]}}",
            "{\"operation\":\"scribble\",\"scribble\":{\"nativeexec\":false}}",
            "{\"operation\":\"scribble\",\"unknown\":{}}"}) {
            reject_builder(FileFailure::invalid_path, [&](auto& value) { value.tasks.front().request_json = unsafe; });
        }
        for (const auto* invalid_limit : {"{\"operation\":\"scribble\",\"scribble\":{\"max_provider_calls\":4097}}",
                "{\"operation\":\"scribble\",\"scribble\":{\"max_files\":129}}", "{\"operation\":\"scribble\",\"scribble\":{\"max_total_bytes\":0}}",
                "{\"operation\":\"scribble\",\"research_limits\":{\"max_queries\":1001}}", "{\"operation\":\"scribble\",\"context_limits\":{\"max_file_bytes\":4194305}}"}) {
            reject_builder(FileFailure::limit, [&](auto& value) { value.tasks.front().request_json = invalid_limit; });
        }
        for (const auto* unsafe : {"{\"usage\":{\"credential_directory\":\"synthetic\"}}", "{\"usage\":{\"credential\":\"synthetic\"}}", "{\"scribble\":{\"evidence\":{\"native_exec\":false}}}",
                "{\"history\":[]}", "{\"unknown\":{}}"}) {
            reject_builder(FileFailure::invalid_path, [&](auto& value) { value.tasks.front().result_json = unsafe; });
        }
        for (const auto* bad_json : {"[]", "null", "\"object\"", "{\"operation\":\"scribble\",\"selector\":false}",
                "{\"operation\":\"scribble\",\"settings\":{\"network_enabled\":1}}", "{\"operation\":\"scribble\",\"questions\":[{}]}"}) {
            builder = valid_builder; builder.tasks.front().request_json = bad_json;
            malformed([&] { workspace.save_state(builder_chat); });
        }
        for (const auto* bad_json : {"[]", "null", "{\"ok\":1}", "{\"omitted\":\"true\"}", "{\"schema_version\":\"1\"}", "{\"schema_version\":1.5}", "{\"sources\":{}}", "{\"usage\":[]}"}) {
            builder = valid_builder; builder.tasks.front().result_json = bad_json;
            malformed([&] { workspace.save_state(builder_chat); });
        }
        builder = valid_builder;
        for (const auto* endpoint : {"", "https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/"}) {
            auto saved_request = json::parse(builder.tasks.front().request_json); saved_request.find("settings")->object()["endpoint"] = endpoint;
            builder.tasks.front().request_json = json::stringify(saved_request); workspace.save_state(builder_chat);
            check(Workspace(root).open_chat(builder_chat.path).state.builder == builder, "Credential-free builder endpoint did not roundtrip");
        }
        builder = valid_builder;
        builder.tasks.front().request_json = "{\"operation\":\"scribble\",\"research_limits\":{\"max_context_chars\":16777216,\"max_excerpt_chars\":524288,\"max_planner_calls\":0}}";
        workspace.save_state(builder_chat);
        check(Workspace(root).open_chat(builder_chat.path).state.builder == builder, "Runtime research limits did not roundtrip");
        builder = valid_builder;
        builder.next_task_id = 9007199254740991ULL; builder.tasks.front().completed_chunks = builder.tasks.front().total_chunks = builder.tasks.front().resumed_chunks = 4096;
        workspace.save_state(builder_chat);
        check(Workspace(root).open_chat(builder_chat.path).state.builder == builder, "Builder counter or next-ID boundary lost precision");
        builder = valid_builder; builder.tasks.clear(); builder.selected_task.clear();
        for (int i = 0; i < 32; ++i) { BuilderTask task; task.id = "task-" + std::to_string(i); builder.tasks.push_back(std::move(task)); }
        workspace.save_state(builder_chat);
        check(Workspace(root).open_chat(builder_chat.path).state.builder.tasks.size() == 32, "Maximum builder task history did not roundtrip");
        for (auto& task : builder.tasks) task.result_json = json::stringify(json::Value::Object{{"text", std::string(40000, 'x')}});
        malformed([&] { workspace.save_state(builder_chat); });
        builder = valid_builder; workspace.save_state(builder_chat);
        const auto valid_document = json::parse(builder_chat.state_original.text);
        auto bad_saved_builder = [&](const auto& change) {
            auto document = valid_document; change(document.find("builder")->object()); const auto bytes = json::stringify(document) + "\n";
            raw_write(root / builder_chat.state_original.path, bytes);
            malformed([&] { (void)workspace.open_chat(builder_chat.path); });
            check(workspace.files().read(builder_chat.state_original.path).text == bytes, "Malformed saved builder was replaced during open");
        };
        for (const auto* bad : {"null", "0", "\"true\"", "[]", "{}"}) {
            bad_saved_builder([&](auto& value) { value["active"] = json::parse(bad); });
        }
        for (const auto* field : {"tab", "selected_task", "fields", "tasks", "next_task_id"}) {
            bad_saved_builder([&](auto& value) { value[field] = nullptr; });
        }
        for (const double number : {-1.0, 0.0, 1.5, 9007199254740992.0}) {
            bad_saved_builder([&](auto& value) { value["next_task_id"] = number; });
        }
        for (const auto* field : {"id", "operation", "status", "label", "request_json", "result_json", "error", "phase", "completed_chunks", "total_chunks", "resumed_chunks"}) {
            bad_saved_builder([&](auto& value) { value["tasks"].array().front().object()[field] = nullptr; });
        }
        for (const double number : {-1.0, 1.5, 4097.0}) {
            bad_saved_builder([&](auto& value) { value["tasks"].array().front().object()["total_chunks"] = number; });
        }
        bad_saved_builder([](auto& value) { value["fields"].object()["builder.paths"] = false; });
        bad_saved_builder([](auto& value) { value["unknown"] = true; });
        bad_saved_builder([](auto& value) { value["tasks"].array().front().object().erase("request_json"); });
        builder = valid_builder; builder.fields["builder.label"] = "Retained after conflict";
        const auto retained_builder = builder;
        const std::string foreign_builder_state = "{\"version\":1,\"draft\":\"Foreign builder draft\"}\n";
        raw_write(root / builder_chat.state_original.path, foreign_builder_state);
        fails(FileFailure::conflict, [&] { workspace.save_state(builder_chat); });
        check(builder == retained_builder && workspace.files().read(builder_chat.state_original.path).text == foreign_builder_state,
            "Builder save conflict lost retained mode/tasks or overwrote foreign state");
        builder_chat = workspace.open_chat(builder_chat.path);
        check(builder_chat.state.builder == BuilderState{} && builder_chat.state.draft == "Foreign builder draft", "Explicit reload did not adopt foreign state");

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
