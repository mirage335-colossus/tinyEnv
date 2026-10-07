#include "display.hpp"

#include <iomanip>
#include <sstream>

std::string format_result(unsigned run, float sample) {
    std::ostringstream text;
    text << "Run " << run << ": " << std::fixed << std::setprecision(3) << sample;
    return text.str();
}
