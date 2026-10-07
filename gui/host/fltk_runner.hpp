#pragma once
#include "host/native_session.hpp"
#include "host/qualification.hpp"
#include "adapter.hpp"
#include <iostream>

namespace foundation::host {
template<Application App> int run_fltk(int argc, char** argv) {
    try {
        const bool smoke = smoke_requested(argc, argv);
        if (argc != 1 && !smoke) throw std::invalid_argument("Usage: foundation-gui-fltk [--smoke-test|--self-check]");
        NativeSession<App, gui::fltk::Adapter> session;
        if (smoke) {
            session.adapter.show();
            session.application.qualify([&] {
                session.tick(); Fl::check(); Fl::flush();
                if (!session.adapter.error().empty()) throw std::runtime_error(session.adapter.error());
            });
            session.adapter.window().make_current();
            const std::unique_ptr<unsigned char[]> pixels(fl_read_image(nullptr, 0, 0,
                session.adapter.window().w(), session.adapter.window().h()));
            if (!pixels) throw std::runtime_error("Native capture failed");
            return finish_smoke(session.application, session.adapter);
        }
        struct Timer {
            decltype(session)& owner;
            std::exception_ptr failure;
            static void tick(void* data) {
                auto& self = *static_cast<Timer*>(data);
                try {
                    if (self.owner.adapter.closed()) return;
                    self.owner.tick(); Fl::repeat_timeout(.02, tick, data);
                } catch (...) { self.failure = std::current_exception(); self.owner.adapter.close(); }
            }
            ~Timer() { Fl::remove_timeout(tick, this); }
        } timer{session, {}};
        session.adapter.show(); Fl::add_timeout(0, Timer::tick, &timer);
        while (!session.adapter.closed()) Fl::wait(.02);
        if (timer.failure) std::rethrow_exception(timer.failure);
        if (!session.adapter.error().empty()) throw std::runtime_error(session.adapter.error());
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return 0;
}
}
