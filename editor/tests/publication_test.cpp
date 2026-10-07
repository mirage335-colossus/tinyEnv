#include "editor/generate/publish.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>

using namespace foundation::editor;
namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
template<class Function> void conflict(Function&& function) {
    try { function(); }
    catch (const FileError& error) {
        require(error.code() == FileFailure::conflict, "Unexpected publication error category");
        return;
    }
    throw std::runtime_error("Expected a publication conflict");
}
void write_external(const std::filesystem::path& path, std::string_view text) {
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    file.write(text.data(), static_cast<std::streamsize>(text.size()));
    if (!file) throw std::runtime_error("Could not write external fixture bytes");
}
}

int main() {
    try {
        const auto root = std::filesystem::temp_directory_path() /
            ("foundation editor publication " + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        require(std::filesystem::create_directory(root), "Could not create fixture root");
        struct Cleanup {
            std::filesystem::path path;
            ~Cleanup() { std::error_code error; std::filesystem::remove_all(path, error); }
        } cleanup{root};
        ProjectFiles files(root);
        files.ensure_directory("design");
        auto project = empty_project("Publication fixture");
        Form form;
        form.id = "form1";
        form.label = "Main";
        project.forms.push_back(form);
        const auto original_text = write_project(project);
        auto design = files.save(files.inspect("design/project.json"), original_text);
        const auto output = generate(project);
        require(static_cast<bool>(output), "Could not generate publication fixture");

        // A valid snapshot does not authorize replacing a later external edit,
        // even when the editor's current design would save identical bytes.
        write_external(root / design.path, "external design bytes\n");
        conflict([&] { (void)capture_generated_batch(files, output, design, original_text); });
        require(files.read(design.path).text == "external design bytes\n", "Preflight overwrote foreign design");
        write_external(root / design.path, original_text);
        design = files.read(design.path);

        files.ensure_directory("generated/visual");
        (void)files.save(files.inspect("generated/visual/forms.hpp"), "handwritten function bodies\n");
        conflict([&] { (void)capture_generated_batch(files, output, design, original_text); });
        require(files.read("generated/visual/forms.hpp").text == "handwritten function bodies\n", "Preflight overwrote handwritten source");
        require(!files.inspect("generated/visual/.foundation-editor-owned.json").identity.exists, "Failed preflight published ownership");
        std::filesystem::remove(root / "generated/visual/forms.hpp");
        auto batch = capture_generated_batch(files, output, design, original_text);
        require(batch.changed && batch.revision_marker.original.path == "generated/visual/design.json", "Wrong publication marker");
        (void)files.save_batch(batch.writes, batch.revision_marker);
        require(files.read(design.path).identity == design.identity, "Unchanged design was unnecessarily rewritten");
        require(!files.recovery_pending(), "Successful publication left a recovery journal");
        design = files.read(design.path);
        require(!capture_generated_batch(files, output, design, original_text).changed, "Retained output is not deterministic");

        // Publication freezes the original design and ownership guard in the
        // batch; foreign edits before committing still fail without output loss.
        project.forms[0].label = "Updated label";
        const auto updated = generate(project);
        batch = capture_generated_batch(files, updated, design, write_project(project));
        const auto old_marker = files.read("generated/visual/design.json").text;
        write_external(root / design.path, "external edit during generation\n");
        conflict([&] { (void)files.save_batch(batch.writes, batch.revision_marker); });
        require(files.read("generated/visual/design.json").text == old_marker, "Conflict advanced the generated revision");
        require(!files.recovery_pending(), "Preflight conflict left a journal");
        require(files.read(design.path).text == "external edit during generation\n", "Conflict lost the external design");
        std::cout << "Editor publication ownership and conflict checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Publication test: " << error.what() << '\n';
        return 1;
    }
}
