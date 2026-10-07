#pragma once
#include <gui/contract.hpp>
#include <gui/runtime.hpp>
#include <concepts>
#include <functional>

namespace foundation::host {
// The only application contract a platform runner requires. No control IDs,
// product commands, layout policy or core operations belong to a runner.
template<class T> concept Application = requires(T& app, gui::Event event, gui::ServiceResult result,
                                                std::function<void()> present) {
    T{std::declval<gui::Adapter&>()};
    { app.handle(event) } -> std::same_as<void>;
    { app.tick() } -> std::same_as<void>;
    { app.shutdown() } -> std::same_as<void>;
    { app.retry_presentation() } -> std::same_as<void>;
    { app.next_service() } -> std::same_as<std::optional<gui::ServiceRequest>>;
    { app.complete_service(result) } -> std::same_as<bool>;
    { app.qualify(present) } -> std::same_as<void>;
};

// Only physical-key presentation needs authoritative semantic freshness. An
// ordinary embedding/runner remains compatible with the original contract.
template<class T> concept BezelApplication = Application<T> && requires(const T& app) {
    { app.input_epoch() } -> std::same_as<std::uint64_t>;
    { app.presentation_pending() } -> std::same_as<bool>;
};

// Generic event loops need no filesystem or native threading headers. A host
// may inject additional content services without naming application features.
struct AdapterServices {
    bool active() const noexcept { return false; }
    std::optional<gui::ServiceResult> poll() { return std::nullopt; }
    void shutdown() noexcept {}
    template<class Adapter, class Reply> void service(Adapter& adapter, gui::ServiceRequest request, Reply reply) {
        adapter.service(std::move(request), std::move(reply));
    }
};
template<Application App, class Adapter, class Services = AdapterServices> class Session {
    App* current_ = nullptr;
    Services files_;
public:
    Adapter adapter;
    App application;
    Session() : adapter([this](const gui::Event& event) {
        if (current_) { current_->handle(event); services(); }
    }), application(adapter) { current_ = &application; }
    ~Session() { files_.shutdown(); application.shutdown(); adapter.close(); current_ = nullptr; }
    void services() {
        if (adapter.closed()) { files_.shutdown(); return; }
        if (auto result = files_.poll()) current_->complete_service(std::move(*result));
        if (files_.active()) return;
        const bool active = [&] {
            if constexpr (requires { adapter.service_active(); }) return adapter.service_active();
            else return bool(adapter.prompt());
        }();
        if (!adapter.closed() && !active) if (auto request = application.next_service())
            files_.service(adapter, std::move(*request), [this](gui::ServiceResult result) {
                if (current_ && !adapter.closed()) current_->complete_service(std::move(result));
            });
    }
    void tick() {
        application.tick();
        if constexpr (requires { adapter.sync(); }) adapter.sync();
        services();
    }
};
} // namespace foundation::host
