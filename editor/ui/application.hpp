#pragma once

#include <gui/runtime.hpp>
#include <gui/contract.hpp>
#include <filesystem>
#include <functional>
#include <memory>

namespace foundation::editor {

// Startup configuration is set by the composition root before constructing a
// session. Project code is never loaded or executed by opening a design.
void configure_launch(std::filesystem::path project = {}, std::filesystem::path root = {},
                      std::filesystem::path executable = {});

class Application {
public:
    explicit Application(gui::Adapter&);
    ~Application();
    Application(const Application&) = delete;
    Application& operator=(const Application&) = delete;
    const gui::Snapshot& view() const noexcept;
    void handle(gui::Event);
    void tick();
    void shutdown() noexcept;
    void retry_presentation();
    bool presentation_pending() const noexcept;
    std::uint64_t input_epoch() const noexcept;
    std::optional<gui::ServiceRequest> next_service();
    bool complete_service(gui::ServiceResult);
    void qualify(const std::function<void()>& present);
    // Ordinary handlers in the self-hosted editor project call this interface.
    void invoke(std::string_view action);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace foundation::editor
