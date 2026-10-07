#include "flow_adapter.hpp"
#include "signal.hpp"
#include <stdexcept>

namespace starter {
namespace flow = foundation::visual::flow;

// Adapters turn the runtime's bounded stream leases into calls to ordinary
// functions. One sample per turn keeps the accounting easy to follow.
class SourceBlock final : public flow::Block {
public:
    void work(flow::WorkContext& work, flow::WorkResult& result) override {
        if (next_ == sample_count()) {
            result.status = flow::WorkStatus::finished;
            return;
        }
        auto output = work.output<float>(0);
        if (output.empty()) {
            result.waits = {flow::WaitCondition::output(0)};
            return;
        }
        output[0] = source_sample(next_);
        ++next_;
        result.produced[0] = 1;
        result.status = flow::WorkStatus::progress;
    }
private:
    std::size_t next_ = 0;
};

class GainBlock final : public flow::Block {
public:
    explicit GainBlock(Services& services) : services_(services) {}
    void work(flow::WorkContext& work, flow::WorkResult& result) override {
        const auto input = work.input<float>(0);
        if (input.empty()) {
            if (work.input_finished(0)) result.status = flow::WorkStatus::finished;
            else result.waits = {flow::WaitCondition::input(0)};
            return;
        }
        auto output = work.output<float>(0);
        if (output.empty()) {
            result.waits = {flow::WaitCondition::output(0)};
            return;
        }
        output[0] = apply_gain(input[0], services_.gain);
        result.consumed[0] = 1;
        result.produced[0] = 1;
        result.status = flow::WorkStatus::progress;
    }
private:
    Services& services_;
};

class CollectorBlock final : public flow::Block {
public:
    explicit CollectorBlock(Services& services) : services_(services) {}
    void work(flow::WorkContext& work, flow::WorkResult& result) override {
        const auto input = work.input<float>(0);
        if (input.empty()) {
            if (work.input_finished(0)) result.status = flow::WorkStatus::finished;
            else result.waits = {flow::WaitCondition::input(0)};
            return;
        }
        collect_sample(services_.samples, input[0]);
        result.consumed[0] = 1;
        result.status = flow::WorkStatus::progress;
    }
private:
    Services& services_;
};

std::unique_ptr<flow::Block> make_source(Services&) {
    return std::make_unique<SourceBlock>();
}

std::unique_ptr<flow::Block> make_gain(Services& services) {
    return std::make_unique<GainBlock>(services);
}

std::unique_ptr<flow::Block> make_collector(Services& services) {
    return std::make_unique<CollectorBlock>(services);
}

void run_samples(Services& services) {
    if (!services.graph) throw std::runtime_error("No processing graph");
    services.samples.clear();
    services.graph->start(flow::RunMode::cooperative);
    // This finite four-sample example finishes immediately. A long-running
    // application should use Graph's worker and send UI updates through UiPost.
    for (std::size_t turn = 0; turn < 128; ++turn) {
        if (services.graph->snapshot().state != flow::GraphState::running) break;
        services.graph->step(1);
    }
    if (services.graph->snapshot().state == flow::GraphState::running) {
        services.graph->request_stop();
        services.graph->join();
        throw std::runtime_error("Processing did not finish");
    }
    services.graph->join();
    const auto finished = services.graph->snapshot();
    if (finished.state != flow::GraphState::completed)
        throw std::runtime_error("Processing failed: " + finished.error);
}

} // namespace starter
