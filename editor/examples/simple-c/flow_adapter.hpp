#pragma once

#include "services.hpp"
#include "visual/flow/flow.hpp"
#include <memory>

namespace c_starter {

std::unique_ptr<foundation::visual::flow::Block> make_source(Services&);
std::unique_ptr<foundation::visual::flow::Block> make_gain(Services&);
std::unique_ptr<foundation::visual::flow::Block> make_collector(Services&);
void run_samples(Services&);

} // namespace c_starter
