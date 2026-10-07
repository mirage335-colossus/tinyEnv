#include "blocks.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace foundation::editor::demo {
namespace flow = foundation::visual::flow;

static std::unique_ptr<Block> source(const std::vector<float>& samples) {
    // Factory-created state makes restart reset the cursor. The borrowed
    // services outlive graph.join() and destruction at the composition root.
    return flow::make_block([&samples, cursor = std::size_t{0}]
                           (flow::WorkContext& work, flow::WorkResult& result) mutable {
        if (work.output_closed(0) || cursor == samples.size()) {
            result.status = flow::WorkStatus::finished;
            return;
        }
        auto output = work.output<float>(0);
        if (output.empty()) {
            result.waits = {flow::WaitCondition::output(0)};
            return;
        }
        const auto count = std::min(output.size(), samples.size() - cursor);
        std::copy_n(samples.begin() + static_cast<std::ptrdiff_t>(cursor), count, output.begin());
        cursor += count;
        result.produced[0] = count;
        result.status = cursor == samples.size() ? flow::WorkStatus::finished
                                                : flow::WorkStatus::progress;
    });
}

std::unique_ptr<Block> source_a(Services& services, const Params&) { return source(services.samples_a); }
std::unique_ptr<Block> source_b(Services& services, const Params&) { return source(services.samples_b); }

// Ordinary helpers can return values, call injected function objects or a C ABI
// shim, and update application-owned state. The editor never parses this code.
static float process_pair(Services& services, float a, float b) {
    if (!services.combine || !services.foreign_transform)
        throw std::logic_error("Missing injected signal-processing function");
    ++services.pair_count;
    return services.foreign_transform(services.combine(a, b));
}

std::unique_ptr<Block> mixer(Services& services, const Params&) {
    return flow::make_block([&services, pairs = std::uint64_t{0}]
                           (flow::WorkContext& work, flow::WorkResult& result) mutable {
        // Unequal input lengths have an explicit policy: finish at the shorter
        // stream. Graph lifecycle closes/discards the other subscription.
        if (work.input_finished(0) || work.input_finished(1)) {
            result.status = flow::WorkStatus::finished;
            return;
        }
        const auto a = work.input<float>(0), b = work.input<float>(1);
        if (a.empty() || b.empty()) {
            if (a.empty()) result.waits.push_back(flow::WaitCondition::input(0));
            if (b.empty()) result.waits.push_back(flow::WaitCondition::input(1));
            return;
        }
        auto sums = work.output<float>(0), differences = work.output<float>(1);
        auto trace = work.output<float>(2);
        auto metrics = work.output<std::uint64_t>(3);
        const bool metric_due = pairs % 2 == 0;
        if (sums.empty() || differences.empty() || trace.size() < 2 || (metric_due && metrics.empty())) {
            if (sums.empty()) result.waits.push_back(flow::WaitCondition::output(0));
            if (differences.empty()) result.waits.push_back(flow::WaitCondition::output(1));
            if (trace.size() < 2) result.waits.push_back(flow::WaitCondition::output(2));
            if (metric_due && metrics.empty()) result.waits.push_back(flow::WaitCondition::output(3));
            return;
        }
        sums[0] = process_pair(services, a.front(), b.front());
        differences[0] = a.front() - b.front();
        trace[0] = a.front(); trace[1] = b.front();
        if (metric_due) metrics[0] = pairs;
        ++pairs;
        result.consumed = {1, 1};
        // Independent counts: trace runs twice as fast and metrics half as fast.
        result.produced = {1, 1, 2, metric_due ? std::size_t{1} : std::size_t{0}};
        result.status = flow::WorkStatus::progress;
        report_progress(services, "Processed pair " + std::to_string(pairs));
    });
}

template<class T>
static std::unique_ptr<Block> sink(std::vector<T>& destination) {
    return flow::make_block([&destination](flow::WorkContext& work, flow::WorkResult& result) {
        const auto input = work.input<T>(0);
        if (!input.empty()) {
            destination.insert(destination.end(), input.begin(), input.end());
            result.consumed[0] = input.size();
            result.status = flow::WorkStatus::progress;
        } else if (work.input_finished(0)) {
            result.status = flow::WorkStatus::finished;
        } else {
            result.waits = {flow::WaitCondition::input(0)};
        }
    });
}

std::unique_ptr<Block> sum_sink(Services& services, const Params&) { return sink(services.sums); }
std::unique_ptr<Block> difference_sink(Services& services, const Params&) { return sink(services.differences); }
std::unique_ptr<Block> trace_sink(Services& services, const Params&) { return sink(services.trace); }
std::unique_ptr<Block> metric_sink(Services& services, const Params&) { return sink(services.metrics); }

} // namespace foundation::editor::demo
