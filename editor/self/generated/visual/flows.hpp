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
#include "editor/self/flow.hpp"

namespace foundation::editor::self_generated {

// The returned graph owns blocks and queues. Services must outlive it,
// including shutdown/join. Construction does not start project work.
template<class Services>
std::unique_ptr<foundation::visual::flow::Graph> make_flow_i_self_2einspect(Services& services, foundation::visual::flow::GraphOptions options = {}) {
    using namespace foundation::visual::flow;
    auto graph = std::make_unique<Graph>(options);
    // design block self.source
    BlockSpec spec_i_self_2esource;
    spec_i_self_2esource.id = "self.source";
    spec_i_self_2esource.outputs.push_back(PortSpec::typed<std::uint8_t>("bytes", 1, false));
    spec_i_self_2esource.breaks_cycle = false;
    spec_i_self_2esource.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::self::source_bytes(services, parameters); })
            return ::foundation::editor::self::source_bytes(services, parameters);
        else
            return ::foundation::editor::self::source_bytes(services);
    };
    [[maybe_unused]] const auto node_i_self_2esource = graph->add(std::move(spec_i_self_2esource));
    // design block self.count
    BlockSpec spec_i_self_2ecount;
    spec_i_self_2ecount.id = "self.count";
    spec_i_self_2ecount.inputs.push_back(PortSpec::typed<std::uint8_t>("bytes", 1, false));
    spec_i_self_2ecount.breaks_cycle = false;
    spec_i_self_2ecount.factory = [&services, parameters = std::map<std::string, std::string>{}]() -> std::unique_ptr<Block> {
        if constexpr (requires { ::foundation::editor::self::count_bytes(services, parameters); })
            return ::foundation::editor::self::count_bytes(services, parameters);
        else
            return ::foundation::editor::self::count_bytes(services);
    };
    [[maybe_unused]] const auto node_i_self_2ecount = graph->add(std::move(spec_i_self_2ecount));
    // design edge self.bytes
    graph->connect(node_i_self_2esource, 0, node_i_self_2ecount, 0, 256);
    return graph;
}

template<class Services>
std::unique_ptr<foundation::visual::flow::Graph> make_flow(std::string_view flow_id, Services& services, foundation::visual::flow::GraphOptions options = {}) {
    if (flow_id == "self.inspect") return make_flow_i_self_2einspect(services, options);
    throw std::invalid_argument("Unknown generated flow ID");
}

} // namespace foundation::editor::self_generated
