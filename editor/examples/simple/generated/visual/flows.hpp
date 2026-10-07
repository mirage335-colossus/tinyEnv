// Generated from the semantic design; edit ordinary source files for behavior.
// No editor executable or design document is needed by this header at runtime.
#pragma once

#include "visual/flow/flow.hpp"
#include <array>
#include <complex>
#include <cstdint>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
#include "flow_adapter.hpp"

namespace foundation::generated {

// The returned graph owns blocks and queues. Services must outlive it,
// including shutdown/join. Construction does not start project work.
template<class Services>
std::unique_ptr<foundation::visual::flow::Graph> make_flow_i_simple_2eprocessing(Services& services, foundation::visual::flow::GraphOptions options = {}) {
    using namespace foundation::visual::flow;
    auto graph = std::make_unique<Graph>(options);
    // design block simple.source
    BlockSpec spec_i_simple_2esource;
    spec_i_simple_2esource.id = "simple.source";
    spec_i_simple_2esource.outputs.push_back(PortSpec::typed<float>("out", 1, false));
    spec_i_simple_2esource.breaks_cycle = false;
    spec_i_simple_2esource.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::starter::make_source(services, parameters); })
            return ::starter::make_source(services, parameters);
        else
            return ::starter::make_source(services);
    };
    [[maybe_unused]] const auto node_i_simple_2esource = graph->add(std::move(spec_i_simple_2esource));
    // design block simple.gain
    BlockSpec spec_i_simple_2egain;
    spec_i_simple_2egain.id = "simple.gain";
    spec_i_simple_2egain.inputs.push_back(PortSpec::typed<float>("in", 1, false));
    spec_i_simple_2egain.outputs.push_back(PortSpec::typed<float>("out", 1, false));
    spec_i_simple_2egain.breaks_cycle = false;
    spec_i_simple_2egain.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::starter::make_gain(services, parameters); })
            return ::starter::make_gain(services, parameters);
        else
            return ::starter::make_gain(services);
    };
    [[maybe_unused]] const auto node_i_simple_2egain = graph->add(std::move(spec_i_simple_2egain));
    // design block simple.collector
    BlockSpec spec_i_simple_2ecollector;
    spec_i_simple_2ecollector.id = "simple.collector";
    spec_i_simple_2ecollector.inputs.push_back(PortSpec::typed<float>("in", 1, false));
    spec_i_simple_2ecollector.breaks_cycle = false;
    spec_i_simple_2ecollector.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::starter::make_collector(services, parameters); })
            return ::starter::make_collector(services, parameters);
        else
            return ::starter::make_collector(services);
    };
    [[maybe_unused]] const auto node_i_simple_2ecollector = graph->add(std::move(spec_i_simple_2ecollector));
    // design edge simple.source_to_gain
    graph->connect(node_i_simple_2esource, 0, node_i_simple_2egain, 0, 2);
    // design edge simple.gain_to_collector
    graph->connect(node_i_simple_2egain, 0, node_i_simple_2ecollector, 0, 2);
    return graph;
}

template<class Services>
std::unique_ptr<foundation::visual::flow::Graph> make_flow(std::string_view flow_id, Services& services, foundation::visual::flow::GraphOptions options = {}) {
    if (flow_id == "simple.processing") return make_flow_i_simple_2eprocessing(services, options);
    throw std::invalid_argument("Unknown generated flow ID");
}

} // namespace foundation::generated
