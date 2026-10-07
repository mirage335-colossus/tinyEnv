#include "flow_adapter.hpp"
#include <stdexcept>

namespace c_starter {
namespace flow = foundation::visual::flow;

// Stream accounting belongs to this small C++ boundary; processing is ordinary C.
class SourceBlock final : public flow::Block {
public:
    void work(flow::WorkContext& work, flow::WorkResult& result) override {
        if (next_ == simple_c_sample_count()) {
            result.status = flow::WorkStatus::finished;
            return;
        }
        auto output = work.output<float>(0);
        if (output.empty()) {
            result.waits = {flow::WaitCondition::output(0)};
            return;
        }
        output[0] = simple_c_source_sample(next_++);
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
        output[0] = simple_c_apply_gain(input[0], services_.state.gain);
        result.consumed[0] = result.produced[0] = 1;
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
        if (!simple_c_collect_sample(&services_.state, input[0]))
            throw std::runtime_error("C sample buffer is full");
        result.consumed[0] = 1;
        result.status = flow::WorkStatus::progress;
    }
private:
    Services& services_;
};

std::unique_ptr<flow::Block> make_source(Services&) { return std::make_unique<SourceBlock>(); }
std::unique_ptr<flow::Block> make_gain(Services& services) { return std::make_unique<GainBlock>(services); }
std::unique_ptr<flow::Block> make_collector(Services& services) { return std::make_unique<CollectorBlock>(services); }

void run_samples(Services& services) {
    if (!services.graph) throw std::runtime_error("No processing graph");
    services.graph->start(flow::RunMode::cooperative);
    // Four samples finish quickly. A slow/continuing process should run on
    // Graph's worker and post GUI commands through UiPost instead.
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

} // namespace c_starter
