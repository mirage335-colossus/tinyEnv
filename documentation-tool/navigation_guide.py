"""Project-specific navigation advice, with lines resolved from snapshot text."""


def make_guide(files):
    """Build concise software-foundation guide cards from supplied source records.

    Missing files or changed evidence needles omit that reference. No source files
    are opened, imported, modified or executed by this module.
    """
    records = [(str(item.get("path", "")).replace("\\", "/"), item.get("text", ""))
               for item in files if isinstance(item.get("text", ""), str)]

    def link(label, wanted, needle):
        for path, text in records:
            if path == wanted or path.endswith("/" + wanted):
                position = text.find(needle)
                if position >= 0:
                    return {"label": label, "path": path, "line": text.count("\n", 0, position) + 1}
        return None

    def card(title, body, references):
        resolved = [link(*reference) for reference in references]
        return {"title": title, "body": body, "links": [value for value in resolved if value is not None]}

    return [
        card("Software-foundation navigation snapshot",
             "This guide is project-specific guidance for software-foundation. Follow source links to confirm current behavior. "
             "Generated maps are navigation snapshots and may lag active development. Missing or changed evidence is omitted. "
             "Application code, build policy, dependency provenance and documentation each have their own owner.", [
                 ("Repository responsibilities", "docs/architecture.md", "| `src/` |"),
                 ("Extension rules", "docs/architecture.md", "Add features to the owning module"),
                 ("Documentation index", "docs/README.md", "# Documentation index")]),
        card("Start with executable entry points",
             "The CLI enters through main or Windows wmain, then run dispatches help, version, self-check or text collection. "
             "It validates all arguments through Store before printing a snapshot. GUI composition roots live in gui/hosts: "
             "terminal, framebuffer, FLTK, Rev, SDL, hosted-web and Wasm share application behavior.", [
                 ("CLI dispatcher", "src/main.cpp", "int run("),
                 ("Windows CLI entry", "src/main.cpp", "int wmain("),
                 ("Ordinary CLI entry", "src/main.cpp", "int main("),
                 ("Terminal entry", "gui/hosts/terminal_main.cpp", "int main("),
                 ("Framebuffer entry", "gui/hosts/framebuffer_main.cpp", "int main("),
                 ("FLTK entry", "gui/hosts/fltk_main.cpp", "int main("),
                 ("Rev entry", "gui/hosts/rev_main.cpp", "int main("),
                 ("SDL entry", "gui/hosts/sdl_main.cpp", "int main(")]),
        card("Put reusable behavior in the core",
             "Store owns record validation, bounded capacity, stable IDs, mutation and owning snapshots. Public C++ declarations "
             "belong under include/foundation; implementation belongs under src. CLI argument parsing and output belong in the "
             "CLI composition root. Keep GUI toolkits and platform services behind interfaces; callers serialize Store access.", [
                 ("Store public contract", "include/foundation/store.hpp", "class Store"),
                 ("Record insertion", "src/store.cpp", "RecordId Store::add"),
                 ("Record mutation", "src/store.cpp", "bool Store::update"),
                 ("Owning snapshot", "src/store.cpp", "Store::snapshot")]),
        card("Trace the private C++ and Rust boundary",
             "Store translates private text-validator statuses into public C++ exceptions. The detail wrapper calls a private C ABI. "
             "Fresh configurations default to the Rust validator; an explicit C++ provider implements the same contract. "
             "Validation changes must preserve shared numeric statuses, borrowed-buffer rules and the corresponding provider behavior.", [
                 ("Exception translation", "src/store.cpp", "void Store::validate"),
                 ("Private ABI contract", "src/text_validation.h", "Length errors precede pointer errors"),
                 ("C++ dispatch", "src/text_validation.cpp", "uint32_t validate_text("),
                 ("Rust exported entry", "rust/text_validation/src/lib.rs", 'pub unsafe extern "C" fn foundation_text_validate_v1'),
                 ("Default provider", "CMakeLists.txt", 'set(FOUNDATION_CORE_PROVIDER "rust"')]),
        card("Understand compiler and configuration ownership",
             "build.sh forwards to tools/build.py. The wrapper chooses a CMake preset and verifies compiler, provider, SDK and output-tree "
             "identity before configuring and compiling. CMake owns final C++ linking; Rust is a subordinate archive producer. "
             "Presets use Ninja and distinguish Debug, Release and sanitizer configurations. Changing compiler/provider identity "
             "normally requires a fresh build directory. This documentation tool reads those declarations independently.", [
                 ("POSIX build entry", "build.sh", '"$root/tools/build.py"'),
                 ("Wrapper options", "tools/build.py", "def main("),
                 ("Configuration and compilation", "tools/build.py", 'timings.call("configure", run'),
                 ("Presets", "CMakePresets.json", '"configurePresets"'),
                 ("C++ language requirement", "CMakeLists.txt", "target_compile_features(foundation_core PUBLIC"),
                 ("Rust archive producer", "cmake/RustComponent.cmake", "add_custom_target(foundation-rust")]),
        card("Add C++ files to an explicit target",
             "A new core .cpp belongs in src and must be added to foundation_core's source list, or an explicit target_sources statement. "
             "CLI support belongs in foundation-cli. Shared GUI .cpp files must be added to foundation_gui_application; host support belongs "
             "to its selected host target. The GUI recursive GLOB watches boundary-check inputs and does not automatically compile a new file. "
             "Public headers under include are exposed to consumers without becoming translation units.", [
                 ("Core source selection", "CMakeLists.txt", "add_library(foundation_core STATIC"),
                 ("CLI source selection", "CMakeLists.txt", "add_executable(foundation-cli"),
                 ("Shared GUI source selection", "gui/CMakeLists.txt", "add_library(foundation_gui_application STATIC"),
                 ("Host target helper", "gui/CMakeLists.txt", "function(foundation_gui_executable"),
                 ("Boundary input inventory", "gui/CMakeLists.txt", "file(GLOB_RECURSE foundation_gui_owned_sources")]),
        card("Add Rust modules inside the existing crate",
             "An internal .rs file can live under rust/text_validation/src and be declared with mod from reachable crate code. "
             "CMake inventories Rust inputs, while Rust module declarations determine which code is compiled. The retained build policy "
             "allows exactly one dependency-free workspace member, edition 2021, Rust 1.63 and the foundation_rust staticlib/rlib targets. "
             "Adding a workspace crate, external dependency or build.rs requires a separately reviewed build-policy change.", [
                 ("Current crate root", "rust/text_validation/src/lib.rs", "fn validate_text("),
                 ("Workspace membership", "rust/Cargo.toml", "members ="),
                 ("Archive crate types", "rust/text_validation/Cargo.toml", "crate-type ="),
                 ("Rust input inventory", "cmake/RustComponent.cmake", "file(GLOB_RECURSE rust_inputs"),
                 ("Workspace policy", "tools/rust_build.py", "def _metadata("),
                 ("Build-script restriction", "tools/rust_build.py", "Rust build scripts are unsupported")]),
        card("Add GUI features on the shared side",
             "Application owns command meaning, feature state, menus and projection of core records. The ordered view_definition table "
             "owns widget identity, labels, order and layout heights. Trace an event into Application::handle, then the corresponding "
             "feature method and publish. Generic adapters receive Snapshot and return Event; product-specific logic belongs with Application.", [
                 ("Shared application contract", "gui/shared/application.hpp", "class Application"),
                 ("Widget declarations", "gui/shared/view_definition.hpp", "inline constexpr std::array view_definition"),
                 ("Event dispatch", "gui/shared/application.cpp", "void Application::handle"),
                 ("Append-entry behavior", "gui/shared/application.cpp", "void Application::append_entry"),
                 ("Example feature extension", "gui/shared/application.cpp", "void Application::enable_remove_feature"),
                 ("Projection and layout", "gui/shared/application.cpp", "void Application::publish")]),
        card("Follow host lifecycle, tasks and services",
             "Session composes the adapter and application, forwards events, ticks the application and dispatches generic services. "
             "Application ticks poll value-only task updates and retry presentation. TextTask owns captured input; the TaskExecutor interface "
             "selects native background or cooperative scheduling. Service completions return to shared application code; import prepares "
             "a replacement collection before committing it. Shutdown closes owned work before state destruction.", [
                 ("Host contract and session", "gui/host/contract.hpp", "class Session"),
                 ("Application tick", "gui/shared/application.cpp", "void Application::tick"),
                 ("Owned task logic", "gui/shared/task.hpp", "class TextTask"),
                 ("Executor contract", "gui/shared/task.hpp", "class TaskExecutor"),
                 ("Scheduling selection", "gui/CMakeLists.txt", "set(foundation_task_executor"),
                 ("Service completion", "gui/shared/application.cpp", "bool Application::complete_service"),
                 ("Shutdown", "gui/shared/application.cpp", "void Application::shutdown")]),
        card("Browser entry points include exported lifecycle APIs",
             "Hosted-web starts a native worker from web_main.cpp and exchanges framed messages with Browser<Application>. Wasm uses "
             "gui_web_create, gui_web_receive and gui_web_destroy rather than an ordinary main. Both transports reach the shared application "
             "through Browser and WebSession. Browser client, Worker, presentation and service modules contain additional message-driven entry points.", [
                 ("Hosted native worker", "gui/hosts/web_main.cpp", "int main("),
                 ("Hosted server script", "gui/hosts/web_host.py", "class Session"),
                 ("Common browser runtime", "gui/host/browser.hpp", "class Browser"),
                 ("Wasm lifecycle", "gui/hosts/wasm_main.cpp", "void gui_web_destroy"),
                 ("Wasm exports", "gui/CMakeLists.txt", "-sEXPORTED_FUNCTIONS="),
                 ("Browser client", "gui/host/browser_client.mjs", "export class Client"),
                 ("Worker installation", "gui/host/wasm_worker.mjs", "export function installWasmWorker")]),
        card("Distinguish owned, retained and generated GUI sources",
             "Owned code lives under gui/shared, gui/host and gui/hosts. Many <gui/...> headers and concrete adapters belong to the retained "
             "gui-boundary dependency. CMake verifies its locked input hashes, restores explicit retained inputs and mirrors/patches headers "
             "into build output. The wrapper and direct CMake use different restore locations. A source-only snapshot may therefore lack "
             "resolved supplier headers. Generated outputs should be traced back to their source and patch declarations.", [
                 ("Retained input selection", "gui/CMakeLists.txt", 'set(FOUNDATION_GUI_INPUT_GROUP ""'),
                 ("CMake restoration", "gui/CMakeLists.txt", 'restore "${FOUNDATION_GUI_INPUT_GROUP}"'),
                 ("Wrapper restoration", "tools/build.py", 'str(build / "inputs/gui")'),
                 ("Supplier hash verification", "gui/CMakeLists.txt", 'file(SHA256 "${path}" actual)'),
                 ("Generated patch helper", "gui/CMakeLists.txt", "function(foundation_gui_patch"),
                 ("Header mirror", "gui/CMakeLists.txt", "set(foundation_gui_mirrored_headers)")]),
    ]
