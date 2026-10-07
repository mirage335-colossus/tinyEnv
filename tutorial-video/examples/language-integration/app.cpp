#include "display.hpp"
#include "processing.h"
#include "rust/ffi.h"

#include <cmath>
#include <iostream>
#include <stdexcept>

struct Services {
    float previous = 0.0f;
    float gain = 2.0f;
};

// An event-style C++ function. This console proof calls it twice; a GUI handler
// can call the same helpers and pass the result to Ui::set_text.
float on_run(Services& services, float input) {
    const float clipped = processing_clamp(input, -2.0f, 2.0f);  // C17
    const float amplified = tutorial_rust_gain(clipped, services.gain); // Rust
    services.previous = tutorial_rust_smooth(services.previous, amplified, 0.5f);
    return services.previous;
}

static void require_close(float actual, float expected) {
    if (!std::isfinite(actual) || std::fabs(actual - expected) > 0.000001f)
        throw std::runtime_error("Integration result did not match expected value");
}

int main() {
    try {
        Services services;
        const float first = on_run(services, 4.0f);
        require_close(first, 2.0f);
        std::cout << format_result(1, first) << '\n'; // ordinary C++20 helper

        const float second = on_run(services, 8.0f);
        require_close(second, 3.0f);
        std::cout << format_result(2, second) << '\n';

        require_close(processing_clamp(-5.0f, -2.0f, 2.0f), -2.0f);
        require_close(processing_clamp(0.25f, -2.0f, 2.0f), 0.25f);
        require_close(tutorial_rust_smooth(3.0f, 9.0f, 0.0f), 3.0f);
        require_close(tutorial_rust_smooth(3.0f, 9.0f, 1.0f), 9.0f);
        std::cout << "C17 helper, C++20 handler, and Rust modules linked: PASS\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
