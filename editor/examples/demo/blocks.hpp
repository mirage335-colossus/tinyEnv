#pragma once

#include "handlers.hpp"
#include "visual/flow/flow.hpp"
#include <map>
#include <memory>
#include <string>

namespace foundation::editor::demo {
using Params = std::map<std::string, std::string>;
using Block = foundation::visual::flow::Block;

std::unique_ptr<Block> source_a(Services&, const Params&);
std::unique_ptr<Block> source_b(Services&, const Params&);
std::unique_ptr<Block> mixer(Services&, const Params&);
std::unique_ptr<Block> sum_sink(Services&, const Params&);
std::unique_ptr<Block> difference_sink(Services&, const Params&);
std::unique_ptr<Block> trace_sink(Services&, const Params&);
std::unique_ptr<Block> metric_sink(Services&, const Params&);

} // namespace foundation::editor::demo
