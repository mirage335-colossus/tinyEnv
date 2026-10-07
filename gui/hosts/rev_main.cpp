#include "shared/application.hpp"
#include "host/rev_runner.hpp"
int main(int argc, char** argv) { return foundation::host::run_rev<foundation::ui::Application>(argc, argv); }
