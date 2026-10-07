#include "hosts/launch.hpp"
#include "sdl_runner.hpp"
#include "host/qualification.hpp"
#include <iostream>

namespace {
struct Smoke {
    static constexpr bool testing = true;
    bool* completed;
    template<class Session> void start(Session& session) {
        session.application.qualify([&] { session.tick(); });
    }
    template<class Session> void frame(Session& session, SDL_Window*, const gui::Frame& frame) {
        if (!frame.pixels || frame.pixels->empty() || !frame.width || !frame.height)
            throw std::runtime_error("Editor framebuffer presented no pixels");
        foundation::host::finish_smoke(session.application, session.adapter);
        *completed = true;
    }
};
}
int main(int argc, char** argv) {
    try {
        const bool smoke = foundation::editor::hosts::configure(argc, argv);
        if (smoke) {
            bool completed = false;
            const auto result = foundation::host::run_sdl<foundation::editor::Application>(1, argv, Smoke{&completed});
            return result == 0 && completed ? 0 : 1;
        }
        return foundation::host::run_sdl<foundation::editor::Application>(1, argv);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
