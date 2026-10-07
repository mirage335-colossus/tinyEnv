#pragma once
#include "host/native_session.hpp"
#include "host/qualification.hpp"
#include "adapter.hpp"
#include <chrono>
#include <iostream>
#include <thread>

namespace foundation::host {
template<Application App> int run_rev(int argc, char** argv) {
    try {
        const bool smoke = smoke_requested(argc, argv);
        if (argc != 1 && !smoke) throw std::invalid_argument("Usage: foundation-gui-rev [--smoke-test|--self-check]");
        NativeSession<App, gui::rev::Adapter> session;
        session.adapter.show();
        if (smoke) {
            session.application.qualify([&] {
                session.tick(); session.adapter.pump(); session.tick();
                if (!session.adapter.error().empty()) throw std::runtime_error(session.adapter.error());
            });
            const auto pixels = session.adapter.capture();
            if (!pixels.width() || !pixels.height()) throw std::runtime_error("Native capture failed");
            return finish_smoke(session.application, session.adapter);
        }
        while (!session.adapter.closed()) {
            session.tick(); if (!session.adapter.pump()) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(4));
        }
        if (!session.adapter.error().empty()) throw std::runtime_error(session.adapter.error());
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return 0;
}
}
