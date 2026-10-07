#pragma once

#include "services.hpp"
#include "visual/ui/ui.hpp"

namespace starter {

void on_run(Services&, foundation::visual::Ui&, const gui::Activate&);
void on_clear(Services&, foundation::visual::Ui&, const gui::Activate&);

} // namespace starter
