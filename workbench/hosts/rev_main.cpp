#include "hosts/launch.hpp"
#include "host/rev_runner.hpp"
#include <iostream>

int main(int argc, char** argv) {
    try {
        const bool smoke = tinyenv::hosts::configure(argc, argv);
        char* arguments[3]{};
        auto normalized = tinyenv::hosts::runner_arguments(smoke, argv, arguments);
        return foundation::host::run_rev<tinyenv::Application>(smoke ? 2 : 1, normalized);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
