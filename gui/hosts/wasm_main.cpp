#include "host/browser.hpp"
#include "shared/application.hpp"
#include <memory>

namespace {
using Runtime = foundation::host::Browser<foundation::ui::Application>;
std::unique_ptr<Runtime> runtime;
std::string response;
std::uint64_t next_runtime = 1;
}
extern "C" {
void gui_web_destroy() { runtime.reset(); response.clear(); }
const char* gui_web_create(const char* epoch) {
    runtime = std::make_unique<Runtime>(epoch && *epoch ? epoch : "wasm-session-" + std::to_string(next_runtime++));
    response = runtime->initial(); return response.c_str();
}
const char* gui_web_receive(const char* message) {
    if (!runtime) gui_web_create(nullptr);
    response = runtime->receive(message ? message : ""); return response.c_str();
}
}
