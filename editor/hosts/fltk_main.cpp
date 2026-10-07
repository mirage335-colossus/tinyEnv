#include "hosts/launch.hpp"
#include "host/fltk_runner.hpp"
#include <iostream>

int main(int argc, char** argv) {
    try {
        const bool smoke = foundation::editor::hosts::configure(argc, argv);
        char* arguments[3]{};
        auto normalized = foundation::editor::hosts::runner_arguments(smoke, argv, arguments);
        return foundation::host::run_fltk<foundation::editor::Application>(smoke ? 2 : 1, normalized);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
