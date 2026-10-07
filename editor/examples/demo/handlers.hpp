#pragma once

#include "visual/ui/ui.hpp"
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace foundation::editor::demo {

// The composition root owns services. Existing algorithms, device objects,
// callbacks and foreign-language shims can be injected as ordinary C++ values.
struct Services {
    std::vector<float> samples_a{1, 2, 3, 4};
    std::vector<float> samples_b{10, 20, 30, 40};
    std::vector<float> sums, differences, trace;
    std::vector<std::uint64_t> metrics;
    std::function<float(float, float)> combine;
    std::function<float(float)> foreign_transform;
    std::function<void()> start, stop;
    foundation::visual::UiPost ui_post;
    gui::WidgetKey status{"demo.status", 1};
    gui::WidgetKey start_button{"demo.start", 1};
    gui::WidgetKey stop_button{"demo.stop", 1};
    gui::WidgetKey refresh_button{"demo.refresh", 1};
    bool running{};
    std::size_t pair_count{}, foreign_callbacks{}, rejected_posts{};
};

void set_busy(foundation::visual::Ui&, bool);
void refresh_devices(Services&, foundation::visual::Ui&);
void announce_completion(Services&);
void report_progress(Services&, std::string);
void on_refresh(Services&, foundation::visual::Ui&, const gui::Activate&);
void on_start(Services&, foundation::visual::Ui&, const gui::Activate&);
void on_stop(Services&, foundation::visual::Ui&, const gui::Activate&);

} // namespace foundation::editor::demo
