#include "shared/application.hpp"
#include "host/native_session.hpp"
#include "host/qualification.hpp"
#include <gui/framebuffer.hpp>

#include <fstream>
#include <iostream>

// The host owns output and lifecycle; application identities never appear here.
int main(int argc, char** argv) {
    if (foundation::host::smoke_requested(argc, argv)) try {
        foundation::host::NativeSession<foundation::ui::Application, gui::FramebufferAdapter> session;
        session.application.qualify([&] {
            session.tick(); const auto frame = session.adapter.frame();
            if (!frame.pixels || frame.pixels->empty() || !frame.width || !frame.height)
                throw std::runtime_error("Framebuffer produced no pixels");
        });
        return foundation::host::finish_smoke(session.application, session.adapter);
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    if (argc != 2) {
        std::cerr << "Usage: foundation-gui-framebuffer OUTPUT.ppm\n";
        return 2;
    }
    try {
        foundation::ui::Application* current = nullptr;
        gui::FramebufferAdapter adapter([&](const gui::Event& event) {
            if (current) current->handle(event);
        });
        foundation::ui::Application app(adapter);
        current = &app;
        const auto frame = adapter.frame();
        std::ofstream output(argv[1], std::ios::binary);
        if (!output || !frame.pixels) throw std::runtime_error("Cannot produce frame");
        output << "P6\n" << frame.width << ' ' << frame.height << "\n255\n";
        for (unsigned row = 0; row < frame.height; ++row)
            output.write(reinterpret_cast<const char*>(frame.pixels->data() + row * frame.stride_bytes),
                         static_cast<std::streamsize>(frame.width) * 3);
        output.close();
        if (!output) throw std::runtime_error("Cannot write frame");
        app.handle(gui::CloseEvent{});
        std::cout << "Rendered " << frame.width << 'x' << frame.height << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
