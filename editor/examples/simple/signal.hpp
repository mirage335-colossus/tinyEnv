#pragma once

#include <cstddef>
#include <vector>

namespace starter {

std::size_t sample_count();
float source_sample(std::size_t index);
float apply_gain(float sample, float gain);
void collect_sample(std::vector<float>& destination, float sample);

} // namespace starter
