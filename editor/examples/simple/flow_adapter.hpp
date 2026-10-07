#pragma once

#include "services.hpp"
#include "visual/flow/flow.hpp"
#include <memory>

namespace starter {

// Only this boundary needs the stream runtime's block interface. The graphical
// design calls these factories; double-clicking opens signal.cpp instead.
std::unique_ptr<foundation::visual::flow::Block> make_source(Services&);
std::unique_ptr<foundation::visual::flow::Block> make_gain(Services&);
std::unique_ptr<foundation::visual::flow::Block> make_collector(Services&);
void run_samples(Services&);

} // namespace starter
