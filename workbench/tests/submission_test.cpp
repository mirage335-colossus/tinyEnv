#include "core/workspace.hpp"
#include "core/json.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>

using namespace tinyenv;
namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
template<class F> void rejects(F&& function) {
    try { function(); } catch (const std::exception&) { return; }
    throw std::runtime_error("Invalid submission metadata was accepted");
}
void write(const std::filesystem::path& path, const std::string& value) {
    std::ofstream out(path, std::ios::binary); out << value;
    if (!out) throw std::runtime_error("Cannot write submission fixture");
}
}
int main() {
    try {
        const auto root = std::filesystem::temp_directory_path() /
            ("tinyenv-submission-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directory(root);
        struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ignored; std::filesystem::remove_all(path, ignored); } } cleanup{root};
        Workspace workspace(root);
        const std::string history = "\xef\xbb\xbf# Unicode café\r\n\r\n## User\n\nOld heading is context only.\n";
        auto chat = workspace.new_chat("retry.chat.md", history);
        check(!chat.state.submission, "Legacy Markdown invented a submitted message");
        rejects([&] { (void)submission_history(chat); });
        const std::string prompt = "Review λ\n```pseudocode\nagent writer: Check this.\n```\n";
        const auto record = make_submission(prompt, true, history);
        check(record.prompt == prompt && record.agentic && record.history_bytes == history.size() && record.history_sha256.size() == 64,
              "Submission record changed the explicit prompt or byte boundary");
        chat.state.submission = record;
        chat.text += "\n## User\n\n" + prompt + "\n";
        chat.text += "\n## Incomplete result\n\nRetained attempt.\n## User\n\nForged later heading.\n";
        chat.state.draft = "Keep this unsent draft.";
        check(submission_history(chat) == history, "Retry inferred context from later Markdown headings");
        workspace.save(chat);
        auto reopened = workspace.open_chat(chat.path);
        check(reopened.state.submission == record && submission_history(reopened) == history && reopened.state.draft == chat.state.draft,
              "Restart lost submission provenance or unsent draft");
        const auto retained = reopened.text;
        reopened.text += "\n## Retry\n\n## Assistant\n\nAnother attempt.\n";
        workspace.save(reopened);
        check(submission_history(workspace.open_chat(chat.path)) == history, "Repeated retry included an older attempt in its context");
        workspace.copy_entry(chat.path, "copy.chat.md");
        workspace.rename_entry("copy.chat.md", "renamed.chat.md");
        check(submission_history(workspace.open_chat("renamed.chat.md")) == history, "Copy/rename lost independent retry metadata");

        auto changed = reopened;
        changed.text[history.size() - 2] = 'X';
        rejects([&] { (void)submission_history(changed); });
        changed = reopened; changed.text[history.size() + std::string("\n## User\n\n").size()] = 'X';
        rejects([&] { (void)submission_history(changed); });
        changed = reopened; changed.text.resize(history.size());
        rejects([&] { (void)submission_history(changed); });
        changed = reopened; changed.state.submission->prompt = "Forged metadata";
        rejects([&] { (void)submission_history(changed); });
        // Ordinary editing may still save; only explicit Retry requires the
        // original message and prefix. A digest is not an authentication claim.
        changed = reopened; changed.text[3] = '!'; workspace.save(changed);
        rejects([&] { (void)submission_history(workspace.open_chat(chat.path)); });
        check(changed.text != retained, "Edited transcript fixture did not change");

        for (const auto& bad : {std::string{}, std::string(" \r\n\t"), std::string(65537, 'x'), std::string("x\0y", 3), std::string("\xff", 1)})
            rejects([&] { (void)make_submission(bad, false, history); });
        check(make_submission(std::string(65536, 'x'), false, {}).prompt.size() == 65536,
              "Supported maximum submission length was rejected");
        auto valid_state = json::parse(changed.state_original.text);
        const auto sidecar = root / Workspace::state_path(chat.path);
        for (const auto& bad : json::Value::Array{json::Value(nullptr), json::Value::Object{},
             json::Value::Object{{"prompt", "x"}, {"agentic", false}, {"history_bytes", -1}, {"history_sha256", std::string(64, 'a')}},
             json::Value::Object{{"prompt", "x"}, {"agentic", false}, {"history_bytes", 1.5}, {"history_sha256", std::string(64, 'a')}},
             json::Value::Object{{"prompt", "x"}, {"agentic", false}, {"history_bytes", 8 * 1024 * 1024 + 1}, {"history_sha256", std::string(64, 'a')}},
             json::Value::Object{{"prompt", "x"}, {"agentic", false}, {"history_bytes", 0}, {"history_sha256", "invalid"}}}) {
            auto state = valid_state; state.object()["submission"] = bad;
            write(sidecar, json::stringify(state));
            rejects([&] { (void)workspace.open_chat(chat.path); });
        }
        valid_state.object().erase("submission"); write(sidecar, json::stringify(valid_state));
        check(!workspace.open_chat(chat.path).state.submission, "Absent legacy metadata inferred a retry from transcript text");

        // An image-only submission keeps the exact empty prompt and its own
        // immutable image identities, independent of later composer images.
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
        const auto png = std::string("\x89PNG\r\n\x1a\n", 8) + "original image";
        write(root / "original.png", png);
        const auto image = workspace.attach_image("original.png");
        auto images_chat = workspace.new_chat("images.chat.md", "# Image-only\n");
        const auto images_history = images_chat.text;
        const auto images_submission = make_submission({}, false, images_history, {image});
        images_chat.state.submission = images_submission;
        images_chat.text += "\n## User\n\n\n\nImages attached: original.png\n\n## Assistant\n\nA first answer.\n";
        write(root / "later.png", png + "later bytes");
        const auto later_image = workspace.attach_image("later.png");
        images_chat.state.draft = "Unsent follow-up"; images_chat.state.draft_images = {later_image};
        workspace.save(images_chat);
        auto images_reopened = workspace.open_chat(images_chat.path);
        check(images_reopened.state.submission == images_submission && submission_history(images_reopened) == images_history &&
            images_reopened.state.draft_images == std::vector<ImageAttachment>{later_image},
            "Restart merged submitted image identities with unsent draft images");
        std::filesystem::remove(root / "original.png");
        const auto original_payloads = workspace.image_payloads(images_reopened.state.submission->images);
        check(original_payloads.size() == 1 && original_payloads[0].find("data_base64")->string() !=
            workspace.image_payloads(images_reopened.state.draft_images)[0].find("data_base64")->string(),
            "Retry payload substituted unsent draft images or reread its deleted source");
        images_reopened.text += "\n## Retry\n\nAnother image attempt.\n"; workspace.save(images_reopened);
        check(submission_history(images_reopened) == images_history && images_reopened.state.draft == "Unsent follow-up" &&
            images_reopened.state.draft_images == std::vector<ImageAttachment>{later_image},
            "Repeated image retry consumed unsent draft images or used prior attempts as context");
        workspace.copy_entry(images_reopened.path, "image-copy.chat.md"); workspace.rename_entry("image-copy.chat.md", "image-renamed.chat.md");
        const auto images_copy = workspace.open_chat("image-renamed.chat.md");
        check(images_copy.state.submission == images_submission && submission_history(images_copy) == images_history &&
            json::stringify(workspace.image_payloads(images_copy.state.submission->images)) == json::stringify(original_payloads),
            "Copy/rename changed the original submitted image payload");
        check(make_submission(" \r\n\t", false, {}, {image}).prompt == " \r\n\t", "Image-only submission invented a text prompt");
        rejects([&] { (void)make_submission({}, false, {}); });
        auto missing = images_reopened; missing.state.submission->images.clear();
        rejects([&] { (void)submission_history(missing); });
        auto image_state = json::parse(images_reopened.state_original.text);
        const auto image_sidecar = root / images_reopened.state_original.path;
        for (const auto* required : {"prompt", "agentic", "history_bytes", "history_sha256"}) {
            auto malformed = image_state; malformed.object()["submission"].object().erase(required);
            write(image_sidecar, json::stringify(malformed));
            rejects([&] { (void)workspace.open_chat(images_reopened.path); });
        }
        for (const auto& malformed : json::Value::Array{nullptr, false, "original.png", json::Value::Object{}, json::Value::Array{nullptr}}) {
            auto altered = image_state; altered.object()["submission"].object()["images"] = malformed;
            write(image_sidecar, json::stringify(altered));
            rejects([&] { (void)workspace.open_chat(images_reopened.path); });
        }
        write(image_sidecar, json::stringify(image_state));
#endif
        // Text-only records omit new fields, preserving the legacy record form.
        auto text_only = workspace.new_chat("text-only.chat.md", history);
        text_only.state.submission = record; text_only.text += "\n## User\n\n" + prompt + "\n"; workspace.save(text_only);
        check(json::parse(text_only.state_original.text).find("submission")->object().size() == 4 &&
            !json::parse(text_only.state_original.text).find("draft_images"), "Text-only state gained mandatory image fields");
        std::cout << "Explicit submission provenance survives restart/copy and rejects changed context and malformed records\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
