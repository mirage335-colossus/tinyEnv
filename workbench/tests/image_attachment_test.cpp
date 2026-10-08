#include "core/workspace.hpp"
#include "editor/platform/content_digest.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>

#if defined(__unix__) && !defined(__EMSCRIPTEN__)
#include <sys/stat.h>
#endif

using namespace tinyenv;
using foundation::editor::FileError;
using foundation::editor::FileFailure;
namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
template<class F> void fails(FileFailure expected, F&& action) {
    try { action(); } catch (const FileError& error) {
        if (error.code() != expected) throw std::runtime_error("Unexpected image failure: " + std::string(error.what()));
        return;
    }
    throw std::runtime_error("Invalid image operation succeeded");
}
template<class F> void rejects(F&& action) {
    try { action(); } catch (const std::exception&) { return; }
    throw std::runtime_error("Malformed attachment state was accepted");
}
void write(const std::filesystem::path& path, std::string_view bytes) {
    std::ofstream file(path, std::ios::binary); file.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!file) throw std::runtime_error("Cannot write image fixture");
}
std::filesystem::path stored(const ImageAttachment& image) { return std::filesystem::path(".tinyenv/images") / (image.sha256 + ".b64"); }
// The contract checks file signatures, without decoding image pixels. Deliberate
// binary fixtures exercise exact retention, including NUL/non-UTF-8 bytes.
std::string png(std::string_view suffix = {}) { return std::string("\x89PNG\r\n\x1a\n\0\xff", 10) + std::string(suffix); }
std::string jpeg() { return std::string("\xff\xd8\xff\xe0\0\x01\xff\xd9", 8); }
}

int main() {
    try {
        const auto sandbox = std::filesystem::temp_directory_path() /
            ("tinyenv-images-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        const auto root = sandbox / "project";
        std::filesystem::create_directories(root);
        struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ignored; std::filesystem::remove_all(path, ignored); } } cleanup{sandbox};
        Workspace workspace(root);
        check(!std::filesystem::exists(root / ".tinyenv"), "Opening workspace created an image store");
#if !defined(__unix__) || defined(__EMSCRIPTEN__)
        fails(FileFailure::unavailable, [&] { (void)workspace.attach_image("image.png"); });
        std::cout << "Unqualified local image filesystem operations fail closed\n";
        return 0;
#else
        const auto original_png = png("Selected bytes");
        write(root / "diagram.PNG", original_png);
        const auto image = workspace.attach_image("diagram.PNG");
        check(image.name == "diagram.PNG" && image.mime_type == "image/png" && image.bytes == original_png.size() &&
            image.sha256 == foundation::editor::detail::content_digest(original_png), "Selection changed image bytes or metadata");
        const auto payload = workspace.image_payloads({image});
        check(payload.size() == 1 && payload[0].object().size() == 2 && payload[0].find("mime_type")->string() == "image/png" &&
            !payload[0].find("name") && !payload[0].find("path"), "Image request exposed a path or metadata authority");
        const auto snapshot = workspace.files().read(stored(image));
        check(payload[0].find("data_base64")->string() == snapshot.text && workspace.attach_image("diagram.PNG") == image &&
            workspace.files().read(stored(image)).identity == snapshot.identity, "Repeated selection replaced an existing managed copy");
        write(root / "diagram.PNG", png("Changed bytes"));
        check(json::stringify(workspace.image_payloads({image})) == json::stringify(payload), "Source edits changed a retained image");
        const auto changed_image = workspace.attach_image("diagram.PNG");
        check(changed_image.sha256 != image.sha256 && changed_image != image, "Changed source reused an old image identity");
        std::filesystem::remove(root / "diagram.PNG");
        check(json::stringify(workspace.image_payloads({image})) == json::stringify(payload), "Source deletion invalidated the retained image");

        write(sandbox / "outside.JpEg", jpeg());
        const auto external = workspace.attach_image(sandbox / "outside.JpEg");
        check(external.name == "outside.JpEg" && external.mime_type == "image/jpeg" && external.bytes == jpeg().size(),
            "Explicit absolute local image was not retained");
        check(workspace.image_payloads({external})[0].find("data_base64")->string() == "/9j/4AAB/9k=",
            "Binary image base64 does not match the independent known encoding");
        std::filesystem::rename(sandbox / "outside.JpEg", sandbox / "moved.JpEg");
        check(workspace.image_payloads({external})[0].find("mime_type")->string() == "image/jpeg", "Source rename broke its snapshot");

        auto chat = workspace.new_chat("chats/images.chat.md", "# Images\n");
        chat.state.draft = "Unsent message"; chat.state.draft_images = {image, external}; workspace.save_state(chat);
        const auto state = json::parse(chat.state_original.text);
        check(state.find("draft_images")->array().size() == 2 && state.find("draft_images")->array()[0].object().size() == 4 &&
            !state.find("draft_images")->array()[0].find("path") && chat.state_original.text.find("Selected bytes") == std::string::npos,
            "Draft state stored source bytes or a source path");
        auto reopened = workspace.open_chat(chat.path);
        check(reopened.state == chat.state, "Restart lost draft images");
        workspace.copy_entry(chat.path, "copy.chat.md"); workspace.rename_entry("copy.chat.md", "renamed.chat.md");
        check(workspace.open_chat("renamed.chat.md").state.draft_images == chat.state.draft_images &&
            workspace.image_payloads(workspace.open_chat("renamed.chat.md").state.draft_images).size() == 2,
            "Same-project chat copy or rename stranded an image");
        workspace.rename_entry("chats", "moved-chats");
        reopened = workspace.open_chat("moved-chats/images.chat.md");
        check(reopened.state.draft_images == chat.state.draft_images && workspace.image_payloads(reopened.state.draft_images).size() == 2,
            "Moving a chat folder stranded the root image store");
        const auto saved_draft = reopened.state;
        reopened.state.draft_images.clear(); workspace.save_state(reopened);
        check(!json::parse(reopened.state_original.text).find("draft_images") && std::filesystem::exists(root / stored(image)),
            "Removing a draft image left metadata or deleted retained shared bytes");
        reopened.state = saved_draft; workspace.save_state(reopened);

        // Missing or changed snapshots leave chat text/drafts accessible, but
        // explicit Send/Retry preparation refuses to reuse unverified bytes.
        std::filesystem::remove(root / stored(image));
        check(workspace.open_chat(reopened.path).state == reopened.state, "Missing image prevented ordinary chat viewing");
        fails(FileFailure::missing, [&] { (void)workspace.image_payloads(reopened.state.draft_images); });
        check(reopened.state == saved_draft, "Failed image preparation discarded the draft");
        write(root / stored(image), snapshot.text);
        auto changed_encoding = snapshot.text; changed_encoding[4] = changed_encoding[4] == 'A' ? 'B' : 'A';
        write(root / stored(image), changed_encoding);
        fails(FileFailure::conflict, [&] { (void)workspace.image_payloads({image}); });
        write(root / "restore.png", original_png);
        fails(FileFailure::conflict, [&] { (void)workspace.attach_image("restore.png"); });
        check(workspace.files().read(stored(image)).text == changed_encoding, "Attach overwrote a changed retained snapshot");
        for (const auto& malformed : {snapshot.text + "\n", std::string(snapshot.text.size(), '!'),
             std::string("=") + snapshot.text.substr(1), snapshot.text.substr(0, snapshot.text.size() - 1)}) {
            write(root / stored(image), malformed);
            fails(FileFailure::conflict, [&] { (void)workspace.image_payloads({image}); });
        }
        write(root / stored(image), snapshot.text);
        const auto jpeg_snapshot = workspace.files().read(stored(external));
        write(root / stored(external), "/9j/4AAB/9l=");
        fails(FileFailure::conflict, [&] { (void)workspace.image_payloads({external}); });
        write(root / stored(external), jpeg_snapshot.text);
        auto wrong_mime = image; wrong_mime.mime_type = "image/jpeg";
        fails(FileFailure::conflict, [&] { (void)workspace.image_payloads({wrong_mime}); });

        // Signature/extension, rooted path, symlink, permissions and ordinary
        // file checks all happen before a new image can become a draft entry.
        write(root / "wrong.png", jpeg()); write(root / "plain.png", "not an image"); write(root / "empty.png", {});
        for (const auto* path : {"wrong.png", "plain.png"}) fails(FileFailure::encoding, [&] { (void)workspace.attach_image(path); });
        fails(FileFailure::limit, [&] { (void)workspace.attach_image("empty.png"); });
        fails(FileFailure::missing, [&] { (void)workspace.attach_image("missing.png"); });
        fails(FileFailure::invalid_path, [&] { (void)workspace.attach_image("restore.txt"); });
        for (const auto* path : {"../outside.png", ".tinyenv/images/forged.png", ".ssh/key.png", ".env.png"})
            fails(FileFailure::invalid_path, [&] { (void)workspace.attach_image(path); });
        std::filesystem::create_directory(root / "directory.png");
        fails(FileFailure::invalid_path, [&] { (void)workspace.attach_image("directory.png"); });
        std::filesystem::create_symlink(root / "restore.png", root / "link.png");
        std::filesystem::create_directory_symlink(root, sandbox / "alias");
        fails(FileFailure::invalid_path, [&] { (void)workspace.attach_image("link.png"); });
        fails(FileFailure::invalid_path, [&] { (void)workspace.attach_image(sandbox / "alias/restore.png"); });
        std::filesystem::remove(root / stored(image));
        std::filesystem::create_symlink(root / stored(external), root / stored(image));
        fails(FileFailure::invalid_path, [&] { (void)workspace.image_payloads({image}); });
        fails(FileFailure::invalid_path, [&] { (void)workspace.attach_image("restore.png"); });
        std::filesystem::remove(root / stored(image)); write(root / stored(image), snapshot.text);
        write(root / "unreadable.png", png("Unreadable"));
        std::filesystem::permissions(root / "unreadable.png", std::filesystem::perms::none);
        fails(FileFailure::permission, [&] { (void)workspace.attach_image("unreadable.png"); });
        std::filesystem::permissions(root / "unreadable.png", std::filesystem::perms::owner_all);
        write(root / "store-readonly.png", png("Unpublished image"));
        std::filesystem::permissions(root / ".tinyenv/images", std::filesystem::perms::owner_read | std::filesystem::perms::owner_exec);
        fails(FileFailure::permission, [&] { (void)workspace.attach_image("store-readonly.png"); });
        std::filesystem::permissions(root / ".tinyenv/images", std::filesystem::perms::owner_all);
        check(reopened.state == saved_draft, "Failed snapshot publication changed a retained draft");
        check(::mkfifo((root / "pipe.png").c_str(), 0600) == 0, "Cannot create FIFO fixture");
        fails(FileFailure::invalid_path, [&] { (void)workspace.attach_image("pipe.png"); });
        write(root / "line\nheading.png", png("Control filename"));
        fails(FileFailure::invalid_path, [&] { (void)workspace.attach_image("line\nheading.png"); });

        std::vector<ImageAttachment> four{image, external, changed_image};
        write(root / "fourth.png", png("Fourth")); four.push_back(workspace.attach_image("fourth.png"));
        check(workspace.image_payloads(four).size() == Workspace::maximum_images, "Four supported images were refused");
        auto five = four; auto fifth = image; fifth.sha256 = std::string(64, 'a'); five.push_back(fifth);
        fails(FileFailure::limit, [&] { (void)workspace.image_payloads(five); });
        fails(FileFailure::invalid_path, [&] { (void)workspace.image_payloads({image, image}); });
        auto full_a = image, full_b = external; full_a.bytes = full_b.bytes = Workspace::maximum_image_bytes;
        check(make_submission({}, false, {}, {full_a, full_b}).images.size() == 2, "Exact aggregate image metadata limit was rejected");
        auto over_total = changed_image; over_total.bytes = 1;
        fails(FileFailure::limit, [&] { (void)make_submission({}, false, {}, {full_a, full_b, over_total}); });
        auto over_image = image; over_image.bytes = Workspace::maximum_image_bytes + 1;
        fails(FileFailure::limit, [&] { (void)make_submission({}, false, {}, {over_image}); });
        auto large = png("At bound"); large.resize(Workspace::maximum_image_bytes, 'x'); write(root / "large.png", large);
        check(workspace.attach_image("large.png").bytes == Workspace::maximum_image_bytes, "Exact source byte limit was rejected");
        std::filesystem::resize_file(root / "large.png", Workspace::maximum_image_bytes + 1);
        fails(FileFailure::limit, [&] { (void)workspace.attach_image("large.png"); });

        const auto valid_state = json::parse(reopened.state_original.text);
        const auto sidecar = root / reopened.state_original.path;
        for (const auto& malformed : json::Value::Array{nullptr, "path.png", json::Value::Object{},
             json::Value::Array{nullptr}, json::Value::Array{json::Value::Object{{"path", "/etc/password.png"}}}}) {
            auto altered = valid_state; altered.object()["draft_images"] = malformed; write(sidecar, json::stringify(altered));
            rejects([&] { (void)workspace.open_chat(reopened.path); });
        }
        for (const auto* field : {"name", "mime_type", "sha256", "bytes"}) {
            auto altered = valid_state; altered.object()["draft_images"].array()[0].object().erase(field); write(sidecar, json::stringify(altered));
            rejects([&] { (void)workspace.open_chat(reopened.path); });
        }
        for (const auto& malformed : json::Value::Array{0, -1, 1.5, true, "10", static_cast<std::size_t>(Workspace::maximum_image_bytes + 1)}) {
            auto altered = valid_state; altered.object()["draft_images"].array()[0].object()["bytes"] = malformed; write(sidecar, json::stringify(altered));
            rejects([&] { (void)workspace.open_chat(reopened.path); });
        }
        for (const auto* field : {"name", "mime_type", "sha256"}) {
            auto altered = valid_state; altered.object()["draft_images"].array()[0].object()[field] = "../outside.png"; write(sidecar, json::stringify(altered));
            rejects([&] { (void)workspace.open_chat(reopened.path); });
        }
        auto unknown = valid_state; unknown.object()["draft_images"].array()[0].object()["path"] = "/etc/outside.png"; write(sidecar, json::stringify(unknown));
        rejects([&] { (void)workspace.open_chat(reopened.path); });
        write(sidecar, json::stringify(valid_state));
        check(workspace.open_chat(reopened.path).state.draft_images == saved_draft.draft_images, "Malformed-state checks lost retained attachments");
        std::cout << "Explicit bounded PNG/JPEG snapshots, draft persistence, derived payloads, copy/retry prerequisites and filesystem safety passed\n";
#endif
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
