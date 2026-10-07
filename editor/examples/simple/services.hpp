#pragma once

#include <vector>

namespace foundation::visual::flow { class Graph; }

namespace starter {

// main.cpp owns these objects. The generated graph and event handlers receive
// the same services, so ordinary code can share application state.
struct Services {
    float gain = 2.0f;
    std::vector<float> samples;
    foundation::visual::flow::Graph* graph = nullptr;
};

} // namespace starter
