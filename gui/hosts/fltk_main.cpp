#include "shared/application.hpp"
#include "host/fltk_runner.hpp"
int main(int argc, char** argv) { return foundation::host::run_fltk<foundation::ui::Application>(argc, argv); }
