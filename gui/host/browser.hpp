#pragma once
#include "host/contract.hpp"
#include <gui/web.hpp>
#include <memory>

namespace foundation::host {
// Both browser transports instantiate this runtime. Application meaning remains
// in App; WebSession owns framing, identity, validation and service completion.
template<Application App> class Browser {
    std::unique_ptr<App> application_;
public:
    gui::WebAdapter adapter;
    gui::WebSession session;
    explicit Browser(std::string epoch) : adapter([this](const gui::Event& event) {
        if (application_) application_->handle(event);
    }), session(adapter, std::move(epoch), [this] { return application_->next_service(); },
        [this](gui::ServiceResult result) { return application_->complete_service(std::move(result)); },
        [this] { application_->tick(); }) {
        application_ = std::make_unique<App>(adapter);
    }
    ~Browser() { application_->shutdown(); adapter.close(); }
    App& application() { return *application_; }
    std::string initial() { application_->retry_presentation(); return session.initial(); }
    std::string receive(std::string_view message) {
        application_->retry_presentation();
        return session.receive(message);
    }
};
}
