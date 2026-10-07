#pragma once

namespace foundation::editor::demo {

// This ordinary application-owned function object is injected by main.cpp.
// Its implementation and public signatures do not belong to the design format.
struct BiasAdder {
    float bias{};
    float operator()(float a, float b) const { return a + b + bias; }
};

} // namespace foundation::editor::demo
