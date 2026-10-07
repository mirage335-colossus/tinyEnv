#include "dsp.h"
#include "flow_adapter.hpp"
#include "generated/visual/flows.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>

namespace demo = foundation::editor::rust_dsp;
namespace flow = foundation::visual::flow;

static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

static void check_chunk_processing() {
    const std::vector<float> input{1, 2, 3, 4, 5, 6, 7, 8, 9};
    const std::vector<float> expected{1, 3, 5, 7};

    FoundationRustDspState whole_state{};
    std::array<float, 4> whole_output{};
    const auto whole = foundation_rust_dsp_process(
        &whole_state, input.data(), input.size(), whole_output.data(), whole_output.size());
    require(whole.status == 0 && whole.consumed == 9 && whole.produced == 4,
            "Whole-input counts differ");
    require(std::equal(expected.begin(), expected.end(), whole_output.begin()),
            "Whole-input FIR values differ");

    FoundationRustDspState state{};
    const auto first = foundation_rust_dsp_process(&state, input.data(), 3, nullptr, 0);
    require(first.status == 0 && first.consumed == 1 && first.produced == 0 &&
            state.newer == 1 && state.older == 0 && state.phase == 1,
            "Zero output capacity must consume only the non-output-due sample");
    const auto blocked = foundation_rust_dsp_process(&state, input.data() + 1, 2, nullptr, 0);
    require(blocked.status == 0 && blocked.consumed == 0 && blocked.produced == 0 &&
            state.newer == 1 && state.older == 0 && state.phase == 1,
            "A blocked output-due sample must preserve state");

    state = {};
    std::vector<float> chunk_output;
    std::size_t offset = 0, calls = 0;
    for (const std::size_t chunk : {1u, 3u, 2u, 3u}) {
        const auto end = offset + chunk;
        while (offset < end) {
            float output = 0;
            const std::size_t capacity = calls % 3 == 0 ? 0 : 1;
            require(++calls < 100, "Chunk processing failed to make bounded progress");
            const auto result = foundation_rust_dsp_process(
                &state, input.data() + offset, end - offset,
                capacity ? &output : nullptr, capacity);
            require(result.status == 0 && result.consumed <= end - offset &&
                    result.produced <= capacity, "Chunk processing returned invalid counts");
            require(result.consumed || result.produced || capacity == 0,
                    "Unblocked chunk processing failed to advance");
            offset += result.consumed;
            if (result.produced) chunk_output.push_back(output);
        }
    }
    require(chunk_output == expected && state.newer == whole_state.newer &&
            state.older == whole_state.older && state.phase == whole_state.phase,
            "Uneven chunks changed the FIR history, phase or results");

    const auto empty = foundation_rust_dsp_process(&state, nullptr, 0, nullptr, 0);
    require(empty.status == 0 && empty.consumed == 0 && empty.produced == 0,
            "Empty buffers were rejected");
    const auto invalid = foundation_rust_dsp_process(&state, nullptr, 1, nullptr, 0);
    require(invalid.status == 1 && invalid.consumed == 0 && invalid.produced == 0 &&
            state.newer == 9 && state.older == 8 && state.phase == 1,
            "Invalid ABI input changed filter state");
    state.phase = 2;
    const auto phase = foundation_rust_dsp_process(&state, nullptr, 0, nullptr, 0);
    require(phase.status == 1 && phase.consumed == 0 && phase.produced == 0 && state.phase == 2,
            "Invalid phase was accepted or changed");
}

static void run_to_completion(flow::Graph& graph) {
    graph.start(flow::RunMode::cooperative);
    std::size_t turns = 0;
    while (graph.snapshot().state == flow::GraphState::running && ++turns < 1000)
        graph.step(8);
    graph.join();
    const auto result = graph.snapshot();
    require(result.state == flow::GraphState::completed,
            "Generated graph did not complete");
    require(result.items_consumed == 13 && result.items_produced == 13,
            "Generated graph's independently accounted stream counts differ");
}

int main() {
    try {
        check_chunk_processing();

        demo::Services services;
        services.input = {1, 2, 3, 4, 5, 6, 7, 8, 9};
        auto graph = foundation::generated::make_flow("rust-dsp.processing", services);
        run_to_completion(*graph);
        require(services.output == std::vector<float>({1, 3, 5, 7}),
                "Generated Rust processing output differs");
        services.output.clear();
        run_to_completion(*graph);
        require(services.output == std::vector<float>({1, 3, 5, 7}),
                "Restart did not create fresh Rust filter state");

        // An impulse-plus-step input distinguishes FIR processing from gain.
        services.input = {1, 0, 0, 0, 2, 2, 2, -1, 4};
        services.output.clear();
        run_to_completion(*graph);
        require(services.output == std::vector<float>({0.5f, 0, 1.5f, 1.25f}),
                "Rust FIR impulse/step values differ");
        std::cout << "Rust FIR + decimate 2: 9 inputs -> 4 outputs\n"
                  << "Uneven chunks, backpressure, history and restart checks passed.\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
