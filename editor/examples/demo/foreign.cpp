#include "foreign.hpp"

// Identical C++ implementation for an adoption project without Rust tools.
extern "C" float foundation_demo_gain(float sample) { return sample * 2.0f; }
extern "C" float foundation_demo_gain_report(float sample, void* context,
                                             void (*report)(void*, float)) {
    const auto result = foundation_demo_gain(sample);
    if (report) report(context, result);
    return result;
}
