#pragma once

#include "visual/flow/flow.hpp"
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace foundation::editor::rust_dsp {

// Normal application data. It outlives the graph, including join().
struct Services {
    std::vector<float> input;
    std::vector<float> output;
};
using Parameters = std::map<std::string, std::string>;

std::unique_ptr<visual::flow::Block> make_source(Services&, const Parameters&);
std::unique_ptr<visual::flow::Block> make_filter(Services&, const Parameters&);
std::unique_ptr<visual::flow::Block> make_sink(Services&, const Parameters&);

} // namespace foundation::editor::rust_dsp
