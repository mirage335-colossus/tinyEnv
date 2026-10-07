#include "shared/application.hpp"
#include "sdl_runner.hpp"
#include "host/qualification.hpp"
namespace {
struct Smoke {
    static constexpr bool testing = true;
    bool* completed;
    template<class Session> void start(Session& session) {
        session.application.qualify([&] { session.tick(); });
    }
    template<class Session> void frame(Session& session, SDL_Window*, const gui::Frame& frame) {
        if (!frame.pixels || frame.pixels->empty() || !frame.width || !frame.height)
            throw std::runtime_error("SDL presented no pixels");
        foundation::host::finish_smoke(session.application, session.adapter);
        *completed = true;
    }
};
}
int main(int argc, char** argv) {
    if (foundation::host::smoke_requested(argc, argv)) {
        bool completed = false;
        const auto result = foundation::host::run_sdl<foundation::ui::Application>(1, argv, Smoke{&completed});
        return result == 0 && completed ? 0 : 1;
    }
    return foundation::host::run_sdl<foundation::ui::Application>(argc, argv);
}
