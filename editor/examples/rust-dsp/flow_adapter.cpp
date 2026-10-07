#include "flow_adapter.hpp"
#include "dsp.h"
#include <algorithm>

namespace foundation::editor::rust_dsp {
namespace flow = visual::flow;

// These small C++ adapters connect ordinary application buffers and the Rust
// function to the generic stream runtime. The algorithm itself lives in dsp.rs.
class Source final : public flow::Block {
public:
    explicit Source(const std::vector<float>& samples) : samples_(samples) {}
    void work(flow::WorkContext& work, flow::WorkResult& result) override {
        if (work.output_closed(0) || cursor_ == samples_.size()) {
            result.status = flow::WorkStatus::finished;
            return;
        }
        auto output = work.output<float>(0);
        // Deliberately publish uneven chunks, independently of queue capacity.
        const std::size_t requested[] = {1, 3, 2, 1};
        const auto count = std::min({output.size(), samples_.size() - cursor_,
                                     requested[chunk_ % 4]});
        if (count == 0) {
            result.waits = {flow::WaitCondition::output(0)};
            return;
        }
        std::copy_n(samples_.data() + cursor_, count, output.data());
        cursor_ += count;
        ++chunk_;
        result.produced[0] = count;
        result.status = cursor_ == samples_.size() ? flow::WorkStatus::finished
                                                  : flow::WorkStatus::progress;
    }
private:
    const std::vector<float>& samples_;
    std::size_t cursor_ = 0;
    std::size_t chunk_ = 0;
};

class Filter final : public flow::Block {
public:
    void work(flow::WorkContext& work, flow::WorkResult& result) override {
        if (work.output_closed(0) || work.input_finished(0)) {
            // Finite-stream policy: no synthetic zeros or FIR tail are emitted.
            // An unmatched final input updates history but produces no sample.
            result.status = flow::WorkStatus::finished;
            return;
        }
        auto input = work.input<float>(0);
        auto output = work.output<float>(0);
        const auto processed = foundation_rust_dsp_process(
            &state_, input.data(), input.size(), output.data(), output.size());
        if (processed.status != 0) {
            result.status = flow::WorkStatus::error;
            result.error = "Rust filter rejected its C ABI arguments";
            return;
        }
        result.consumed[0] = processed.consumed;
        result.produced[0] = processed.produced;
        if (processed.consumed || processed.produced) {
            result.status = flow::WorkStatus::progress;
        } else if (input.empty()) {
            result.waits = {flow::WaitCondition::input(0)};
        } else {
            result.waits = {flow::WaitCondition::output(0)};
        }
    }
private:
    FoundationRustDspState state_{}; // Each factory call resets its own stream.
};

class Sink final : public flow::Block {
public:
    explicit Sink(std::vector<float>& samples) : samples_(samples) {}
    void work(flow::WorkContext& work, flow::WorkResult& result) override {
        auto input = work.input<float>(0);
        if (!input.empty()) {
            // Read one at a time to exercise downstream backpressure.
            samples_.push_back(input.front());
            result.consumed[0] = 1;
            result.status = flow::WorkStatus::progress;
        } else if (work.input_finished(0)) {
            result.status = flow::WorkStatus::finished;
        } else {
            result.waits = {flow::WaitCondition::input(0)};
        }
    }
private:
    std::vector<float>& samples_;
};

std::unique_ptr<flow::Block> make_source(Services& services, const Parameters&) {
    return std::make_unique<Source>(services.input);
}
std::unique_ptr<flow::Block> make_filter(Services&, const Parameters&) {
    return std::make_unique<Filter>();
}
std::unique_ptr<flow::Block> make_sink(Services& services, const Parameters&) {
    return std::make_unique<Sink>(services.output);
}

} // namespace foundation::editor::rust_dsp
