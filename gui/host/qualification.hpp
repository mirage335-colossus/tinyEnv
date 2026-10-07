#pragma once
#include <gui/contract.hpp>
#include <iostream>
#include <stdexcept>
#include <string_view>

namespace foundation::host {
inline bool smoke_requested(int argc, char** argv) {
    return argc == 2 && (std::string_view(argv[1]) == "--smoke-test" ||
                         std::string_view(argv[1]) == "--self-check");
}
template<class App, class Adapter> int finish_smoke(App& app, Adapter& adapter) {
    app.handle(gui::CloseEvent{});
    if (!adapter.closed()) throw std::runtime_error("Qualification did not close the adapter");
    std::cout << "software-foundation gui smoke: ok\n";
    return 0;
}
}
