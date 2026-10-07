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
#include "blocks.hpp"

namespace foundation::generated {

// The returned graph owns blocks and queues. Services must outlive it,
// including shutdown/join. Construction does not start project work.
template<class Services>
std::unique_ptr<foundation::visual::flow::Graph> make_flow_i_demo_2eprocessing(Services& services, foundation::visual::flow::GraphOptions options = {}) {
    using namespace foundation::visual::flow;
    auto graph = std::make_unique<Graph>(options);
    // design block demo.source_a
    BlockSpec spec_i_demo_2esource_5fa;
    spec_i_demo_2esource_5fa.id = "demo.source_a";
    spec_i_demo_2esource_5fa.outputs.push_back(PortSpec::typed<float>("samples", 1, false));
    spec_i_demo_2esource_5fa.breaks_cycle = false;
    spec_i_demo_2esource_5fa.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::demo::source_a(services, parameters); })
            return ::foundation::editor::demo::source_a(services, parameters);
        else
            return ::foundation::editor::demo::source_a(services);
    };
    [[maybe_unused]] const auto node_i_demo_2esource_5fa = graph->add(std::move(spec_i_demo_2esource_5fa));
    // design block demo.source_b
    BlockSpec spec_i_demo_2esource_5fb;
    spec_i_demo_2esource_5fb.id = "demo.source_b";
    spec_i_demo_2esource_5fb.outputs.push_back(PortSpec::typed<float>("samples", 1, false));
    spec_i_demo_2esource_5fb.breaks_cycle = false;
    spec_i_demo_2esource_5fb.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::demo::source_b(services, parameters); })
            return ::foundation::editor::demo::source_b(services, parameters);
        else
            return ::foundation::editor::demo::source_b(services);
    };
    [[maybe_unused]] const auto node_i_demo_2esource_5fb = graph->add(std::move(spec_i_demo_2esource_5fb));
    // design block demo.mixer
    BlockSpec spec_i_demo_2emixer;
    spec_i_demo_2emixer.id = "demo.mixer";
    spec_i_demo_2emixer.inputs.push_back(PortSpec::typed<float>("a", 1, false));
    spec_i_demo_2emixer.inputs.push_back(PortSpec::typed<float>("b", 1, false));
    spec_i_demo_2emixer.outputs.push_back(PortSpec::typed<float>("sum", 1, false));
    spec_i_demo_2emixer.outputs.push_back(PortSpec::typed<float>("difference", 1, false));
    spec_i_demo_2emixer.outputs.push_back(PortSpec::typed<float>("trace", 1, false));
    spec_i_demo_2emixer.outputs.push_back(PortSpec::typed<std::uint64_t>("metric", 1, false));
    spec_i_demo_2emixer.breaks_cycle = false;
    spec_i_demo_2emixer.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::demo::mixer(services, parameters); })
            return ::foundation::editor::demo::mixer(services, parameters);
        else
            return ::foundation::editor::demo::mixer(services);
    };
    [[maybe_unused]] const auto node_i_demo_2emixer = graph->add(std::move(spec_i_demo_2emixer));
    // design block demo.sum_sink
    BlockSpec spec_i_demo_2esum_5fsink;
    spec_i_demo_2esum_5fsink.id = "demo.sum_sink";
    spec_i_demo_2esum_5fsink.inputs.push_back(PortSpec::typed<float>("sum", 1, false));
    spec_i_demo_2esum_5fsink.breaks_cycle = false;
    spec_i_demo_2esum_5fsink.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::demo::sum_sink(services, parameters); })
            return ::foundation::editor::demo::sum_sink(services, parameters);
        else
            return ::foundation::editor::demo::sum_sink(services);
    };
    [[maybe_unused]] const auto node_i_demo_2esum_5fsink = graph->add(std::move(spec_i_demo_2esum_5fsink));
    // design block demo.difference_sink
    BlockSpec spec_i_demo_2edifference_5fsink;
    spec_i_demo_2edifference_5fsink.id = "demo.difference_sink";
    spec_i_demo_2edifference_5fsink.inputs.push_back(PortSpec::typed<float>("difference", 1, false));
    spec_i_demo_2edifference_5fsink.breaks_cycle = false;
    spec_i_demo_2edifference_5fsink.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::demo::difference_sink(services, parameters); })
            return ::foundation::editor::demo::difference_sink(services, parameters);
        else
            return ::foundation::editor::demo::difference_sink(services);
    };
    [[maybe_unused]] const auto node_i_demo_2edifference_5fsink = graph->add(std::move(spec_i_demo_2edifference_5fsink));
    // design block demo.trace_sink
    BlockSpec spec_i_demo_2etrace_5fsink;
    spec_i_demo_2etrace_5fsink.id = "demo.trace_sink";
    spec_i_demo_2etrace_5fsink.inputs.push_back(PortSpec::typed<float>("trace", 1, false));
    spec_i_demo_2etrace_5fsink.breaks_cycle = false;
    spec_i_demo_2etrace_5fsink.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::demo::trace_sink(services, parameters); })
            return ::foundation::editor::demo::trace_sink(services, parameters);
        else
            return ::foundation::editor::demo::trace_sink(services);
    };
    [[maybe_unused]] const auto node_i_demo_2etrace_5fsink = graph->add(std::move(spec_i_demo_2etrace_5fsink));
    // design block demo.metric_sink
    BlockSpec spec_i_demo_2emetric_5fsink;
    spec_i_demo_2emetric_5fsink.id = "demo.metric_sink";
    spec_i_demo_2emetric_5fsink.inputs.push_back(PortSpec::typed<std::uint64_t>("metric", 1, false));
    spec_i_demo_2emetric_5fsink.breaks_cycle = false;
    spec_i_demo_2emetric_5fsink.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::demo::metric_sink(services, parameters); })
            return ::foundation::editor::demo::metric_sink(services, parameters);
        else
            return ::foundation::editor::demo::metric_sink(services);
    };
    [[maybe_unused]] const auto node_i_demo_2emetric_5fsink = graph->add(std::move(spec_i_demo_2emetric_5fsink));
    // design edge demo.a
    graph->connect(node_i_demo_2esource_5fa, 0, node_i_demo_2emixer, 0, 2);
    // design edge demo.b
    graph->connect(node_i_demo_2esource_5fb, 0, node_i_demo_2emixer, 1, 2);
    // design edge demo.sum
    graph->connect(node_i_demo_2emixer, 0, node_i_demo_2esum_5fsink, 0, 2);
    // design edge demo.difference
    graph->connect(node_i_demo_2emixer, 1, node_i_demo_2edifference_5fsink, 0, 2);
    // design edge demo.trace
    graph->connect(node_i_demo_2emixer, 2, node_i_demo_2etrace_5fsink, 0, 2);
    // design edge demo.metric
    graph->connect(node_i_demo_2emixer, 3, node_i_demo_2emetric_5fsink, 0, 2);
    return graph;
}

template<class Services>
std::unique_ptr<foundation::visual::flow::Graph> make_flow(std::string_view flow_id, Services& services, foundation::visual::flow::GraphOptions options = {}) {
    if (flow_id == "demo.processing") return make_flow_i_demo_2eprocessing(services, options);
    throw std::invalid_argument("Unknown generated flow ID");
}

} // namespace foundation::generated
