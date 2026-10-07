#include "generated/visual/forms.hpp"
#include "generated/visual/events.hpp"
#include "generated/visual/flows.hpp"
#include "foreign.hpp"
#include "ordinary_algorithms.hpp"
#include <gui/memory_adapter.hpp>
#include <iostream>
#include <stdexcept>
#include <string>

namespace demo = foundation::editor::demo;
namespace flow = foundation::visual::flow;

static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

// This synchronous foreign callback cannot throw across the C ABI. For a
// callback doing fallible work, catch exceptions here and return/store a status.
extern "C" void demo_report_gain(void* context, float) noexcept {
    ++static_cast<demo::Services*>(context)->foreign_callbacks;
}

int main() {
    try {
        // Same generated composition can be presented by a native GUI host. A
        // MemoryAdapter makes this adoption example runnable without a display.
        gui::MemoryAdapter adapter;
        demo::Services services;
        foundation::visual::Ui ui(adapter, foundation::generated::snapshot("demo.panel"));
        services.combine = demo::BiasAdder{0.5f};
        services.foreign_transform = [&services](float sample) {
            return foundation_demo_gain_report(sample, &services, demo_report_gain);
        };
        auto graph = foundation::generated::make_flow("demo.processing", services);
        services.start = [&graph] { graph->start(flow::RunMode::cooperative); };
        services.stop = [&graph] { graph->request_stop(); graph->join(); };
        require(foundation::generated::bind_handlers(ui, services) == 3, "Event bindings missing");
        ui.select("demo.device", std::string("simulated"));
        const auto activate = [&](std::string_view id) {
            const auto target = ui.widget(id);
            require(target.has_value(), "Missing generated widget");
            return ui.handle(gui::WidgetEvent{*target, gui::Activate{}});
        };
        require(activate("demo.refresh") == foundation::visual::DispatchResult::handled,
                "Refresh handler was not dispatched");
        require(gui::find_widget(ui.view(), *ui.widget("demo.device"))->state.options.size() == 2,
                "Ordinary helper did not replace dropdown options");
        require(ui.selected("demo.device").value == std::optional<std::string>("simulated"),
                "Dropdown selection was not preserved");
        ui.select("demo.device", std::string("recording"));
        require(activate("demo.refresh") == foundation::visual::DispatchResult::handled,
                "Repeated refresh handler was not dispatched");
        require(ui.selected("demo.device").value == std::optional<std::string>("recording"),
                "Refresh replaced the user's existing stable choice");
        require(activate("demo.start") == foundation::visual::DispatchResult::handled,
                "Start handler was not dispatched");
        require(!gui::find_widget(ui.view(), *ui.widget("demo.start"))->state.enabled,
                "Start button did not lock while processing");
        require(gui::find_widget(ui.view(), *ui.widget("demo.stop"))->state.enabled,
                "Stop button did not unlock while processing");

        // Cooperative execution demonstrates the exact same general Work API
        // without timing-dependent assertions. Normal applications can choose
        // Graph's owned worker and drain UiPost from the GUI owner thread.
        for (std::size_t turn = 0; turn < 10000; ++turn) {
            if (graph->snapshot().state != flow::GraphState::running) break;
            graph->step(1);
            const auto drained = ui.drain();
            require(drained.errors.empty(), "GUI mailbox application failed");
        }
        graph->join();
        const auto completed = graph->snapshot();
        if (completed.state != flow::GraphState::completed)
            throw std::runtime_error("Graph did not complete: " + completed.error);
        demo::announce_completion(services);
        const auto drained = ui.drain();
        require(drained.errors.empty(), "Completion mailbox application failed");
        require(services.sums == std::vector<float>({23, 45, 67, 89}), "Injected sum/foreign transform incorrect");
        require(services.differences == std::vector<float>({-9, -18, -27, -36}), "Difference stream incorrect");
        require(services.trace == std::vector<float>({1, 10, 2, 20, 3, 30, 4, 40}), "Unequal trace stream incorrect");
        require(services.metrics == std::vector<std::uint64_t>({0, 2}), "Unequal metric stream incorrect");
        require(services.pair_count == 4 && services.foreign_callbacks == 4,
                "Ordinary helper or C ABI callback was not called");
        require(services.rejected_posts == 0, "A GUI update was rejected");
        require(gui::find_widget(ui.view(), *ui.widget("demo.start"))->state.enabled,
                "Completion helper did not release button lockout");
        require(!gui::find_widget(ui.view(), *ui.widget("demo.stop"))->state.enabled,
                "Completion helper did not disable Stop");
        require(gui::find_widget(ui.view(), *ui.widget("demo.status"))->state.text.starts_with("Completed:"),
                "Completion helper did not update text");
        std::cout << "Adopted design passed: 2 inputs -> 4 outputs [4, 4, 8, 2], "
                     "GUI choices/text/lockout, injected C++ and C ABI callbacks.\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
