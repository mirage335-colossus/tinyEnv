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
std::unique_ptr<foundation::visual::flow::Graph> make_flow_i_rust_2ddsp_2eprocessing(Services& services, foundation::visual::flow::GraphOptions options = {}) {
    using namespace foundation::visual::flow;
    auto graph = std::make_unique<Graph>(options);
    // design block rust-dsp.source
    BlockSpec spec_i_rust_2ddsp_2esource;
    spec_i_rust_2ddsp_2esource.id = "rust-dsp.source";
    spec_i_rust_2ddsp_2esource.outputs.push_back(PortSpec::typed<float>("out", 1, false));
    spec_i_rust_2ddsp_2esource.breaks_cycle = false;
    spec_i_rust_2ddsp_2esource.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::rust_dsp::make_source(services, parameters); })
            return ::foundation::editor::rust_dsp::make_source(services, parameters);
        else
            return ::foundation::editor::rust_dsp::make_source(services);
    };
    [[maybe_unused]] const auto node_i_rust_2ddsp_2esource = graph->add(std::move(spec_i_rust_2ddsp_2esource));
    // design block rust-dsp.filter
    BlockSpec spec_i_rust_2ddsp_2efilter;
    spec_i_rust_2ddsp_2efilter.id = "rust-dsp.filter";
    spec_i_rust_2ddsp_2efilter.inputs.push_back(PortSpec::typed<float>("in", 1, false));
    spec_i_rust_2ddsp_2efilter.outputs.push_back(PortSpec::typed<float>("out", 1, false));
    spec_i_rust_2ddsp_2efilter.breaks_cycle = false;
    spec_i_rust_2ddsp_2efilter.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::rust_dsp::make_filter(services, parameters); })
            return ::foundation::editor::rust_dsp::make_filter(services, parameters);
        else
            return ::foundation::editor::rust_dsp::make_filter(services);
    };
    [[maybe_unused]] const auto node_i_rust_2ddsp_2efilter = graph->add(std::move(spec_i_rust_2ddsp_2efilter));
    // design block rust-dsp.sink
    BlockSpec spec_i_rust_2ddsp_2esink;
    spec_i_rust_2ddsp_2esink.id = "rust-dsp.sink";
    spec_i_rust_2ddsp_2esink.inputs.push_back(PortSpec::typed<float>("in", 1, false));
    spec_i_rust_2ddsp_2esink.breaks_cycle = false;
    spec_i_rust_2ddsp_2esink.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::rust_dsp::make_sink(services, parameters); })
            return ::foundation::editor::rust_dsp::make_sink(services, parameters);
        else
            return ::foundation::editor::rust_dsp::make_sink(services);
    };
    [[maybe_unused]] const auto node_i_rust_2ddsp_2esink = graph->add(std::move(spec_i_rust_2ddsp_2esink));
    // design edge rust-dsp.input
    graph->connect(node_i_rust_2ddsp_2esource, 0, node_i_rust_2ddsp_2efilter, 0, 3);
    // design edge rust-dsp.output
    graph->connect(node_i_rust_2ddsp_2efilter, 0, node_i_rust_2ddsp_2esink, 0, 1);
    return graph;
}

template<class Services>
std::unique_ptr<foundation::visual::flow::Graph> make_flow(std::string_view flow_id, Services& services, foundation::visual::flow::GraphOptions options = {}) {
    if (flow_id == "rust-dsp.processing") return make_flow_i_rust_2ddsp_2eprocessing(services, options);
    throw std::invalid_argument("Unknown generated flow ID");
}

} // namespace foundation::generated
