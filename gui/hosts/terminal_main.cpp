#include "shared/application.hpp"
#include "terminal_runner.hpp"
#include "host/qualification.hpp"
int main(int argc, char** argv) {
    if (foundation::host::smoke_requested(argc, argv)) try {
        foundation::host::NativeSession<foundation::ui::Application, gui::TerminalAdapter> session;
        session.application.qualify([&] {
            session.tick();
            if (session.adapter.ansi_rows().empty()) throw std::runtime_error("Terminal produced no rows");
        });
        return foundation::host::finish_smoke(session.application, session.adapter);
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return foundation::host::run_terminal<foundation::ui::Application>(argc, argv);
}
