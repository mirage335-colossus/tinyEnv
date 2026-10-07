#include "signal.hpp"

namespace starter {

// These are ordinary functions. They need no editor or stream-runtime API.
std::size_t sample_count() {
    return 4;
}

float source_sample(std::size_t index) {
    return static_cast<float>(index + 1); // 1, 2, 3, 4
}

float apply_gain(float sample, float gain) {
    return sample * gain;
}

void collect_sample(std::vector<float>& destination, float sample) {
    destination.push_back(sample);
}

} // namespace starter
