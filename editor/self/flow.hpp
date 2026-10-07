#pragma once

#include "visual/flow/flow.hpp"
#include <algorithm>
#include <cstdint>
#include <map>
#include <memory>
#include <string>

namespace foundation::editor::self {

// An optional graph in the self-host design. Services may be any ordinary
// object carrying source_bytes and observed_bytes; no editor runtime requires
// this graph. Bindings demonstrate double-click navigation to project code.
template<class Services>
std::unique_ptr<foundation::visual::flow::Block>
source_bytes(Services& app, const std::map<std::string, std::string>&) {
    namespace flow = foundation::visual::flow;
    return flow::make_block([&app, cursor = std::size_t{0}]
                           (flow::WorkContext& work, flow::WorkResult& result) mutable {
        if (cursor == app.source_bytes.size() || work.output_closed(0)) {
            result.status = flow::WorkStatus::finished;
            return;
        }
        auto output = work.output<std::uint8_t>(0);
        if (output.empty()) { result.waits = {flow::WaitCondition::output(0)}; return; }
        const auto count = std::min(output.size(), app.source_bytes.size() - cursor);
        for (std::size_t i = 0; i < count; ++i)
            output[i] = static_cast<std::uint8_t>(app.source_bytes[cursor + i]);
        cursor += count;
        result.produced[0] = count;
        result.status = cursor == app.source_bytes.size() ? flow::WorkStatus::finished
                                                        : flow::WorkStatus::progress;
    });
}

template<class Services>
std::unique_ptr<foundation::visual::flow::Block>
count_bytes(Services& app, const std::map<std::string, std::string>&) {
    namespace flow = foundation::visual::flow;
    return flow::make_block([&app](flow::WorkContext& work, flow::WorkResult& result) {
        const auto input = work.input<std::uint8_t>(0);
        if (!input.empty()) {
            app.observed_bytes += input.size();
            result.consumed[0] = input.size();
            result.status = flow::WorkStatus::progress;
        } else if (work.input_finished(0)) result.status = flow::WorkStatus::finished;
        else result.waits = {flow::WaitCondition::input(0)};
    });
}

} // namespace foundation::editor::self
