#pragma once

#include <gui/contract.hpp>
#include <gui/runtime.hpp>
#include <filesystem>
#include <functional>
#include <memory>
#include <string_view>

namespace tinyenv {

// The native composition root sets launch paths before constructing a session.
// runtime_path optionally selects an existing trusted worker for chat, model
// and guardrail requests; empty uses the configured copied runtime.
// config_directory scopes application preferences and private saved provider
// keys; it is passed to trusted workers outside their JSON request documents.
void configure_launch(std::filesystem::path root = {}, std::filesystem::path chat = {},
                      std::filesystem::path executable = {},
                      std::filesystem::path config_directory = {},
                      std::filesystem::path runtime_path = {});

class Application {
public:
    explicit Application(gui::Adapter&);
    ~Application();
    Application(const Application&) = delete;
    Application& operator=(const Application&) = delete;
    const gui::Snapshot& view() const noexcept;
    // Original in-memory Markdown; passive preview projection never rewrites it.
    std::string_view chat_text() const noexcept;
    void handle(gui::Event);
    void tick();
    void shutdown() noexcept;
    void retry_presentation();
    bool presentation_pending() const noexcept;
    std::uint64_t input_epoch() const noexcept;
    std::optional<gui::ServiceRequest> next_service();
    bool complete_service(gui::ServiceResult);
    void qualify(const std::function<void()>& present);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace tinyenv
