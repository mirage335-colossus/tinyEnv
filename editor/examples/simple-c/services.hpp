#pragma once

#include "signal.h"

namespace foundation::visual::flow { class Graph; }

namespace c_starter {

// The composition root owns the C state, graph and GUI. The C functions use
// their state and synchronous callbacks without depending on C++ definitions.
struct Services {
    simple_c_state state{};
    foundation::visual::flow::Graph* graph = nullptr;
    Services() { simple_c_state_init(&state); }
};

} // namespace c_starter
