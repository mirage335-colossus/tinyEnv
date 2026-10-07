#include "event_adapter.hpp"
#include "events.h"
#include "flow_adapter.hpp"

namespace c_starter {
namespace {

struct Context { Services& services; foundation::visual::Ui& ui; };

bool applied(foundation::visual::UiResult result) {
    return result == foundation::visual::UiResult::applied ||
           result == foundation::visual::UiResult::unchanged;
}

// All boundary callbacks contain C++ exceptions. C sees explicit status codes.
extern "C" {
static int gain_is_half(void* context) noexcept {
    try {
        const auto selected = static_cast<Context*>(context)->ui.selected("simple_c.gain_choice");
        if (!applied(selected.result)) return -1;
        return selected.value == "half" ? 1 : 0;
    } catch (...) { return -1; }
}

static int set_run_enabled(void* context, int enabled) noexcept {
    try {
        return applied(static_cast<Context*>(context)->ui.set_enabled("simple_c.run", enabled != 0));
    } catch (...) { return 0; }
}

static int set_output_text(void* context, const char* text) noexcept {
    try {
        return applied(static_cast<Context*>(context)->ui.set_text("simple_c.output", text));
    } catch (...) { return 0; }
}

static int run(void* context) noexcept {
    try {
        run_samples(static_cast<Context*>(context)->services);
        return 1;
    } catch (...) { return 0; }
}
} // extern "C"

simple_c_ui facade(Context& context) {
    return {&context, gain_is_half, set_run_enabled, set_output_text, run};
}

} // namespace

void on_run(Services& services, foundation::visual::Ui& ui, const gui::Activate&) {
    Context context{services, ui};
    const auto callbacks = facade(context);
    simple_c_on_run(&services.state, &callbacks);
}

void on_clear(Services& services, foundation::visual::Ui& ui, const gui::Activate&) {
    Context context{services, ui};
    const auto callbacks = facade(context);
    simple_c_on_clear(&services.state, &callbacks);
}

} // namespace c_starter
