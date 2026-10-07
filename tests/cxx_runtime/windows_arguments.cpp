#include "platform/windows_arguments.hpp"

#include <iostream>
#include <vector>

int wmain(int argc, wchar_t** argv) {
    try {
        std::vector<std::string> values;
        for (int index = 1; index < argc; ++index)
            values.push_back(foundation::platform::utf8_argument(argv[index]));
        // Validate every argument before emitting bytes, as the real CLI does.
        for (const auto& value : values) std::cout << value << '\n';
        return std::cout.flush() ? 0 : 1;
    } catch (const std::exception&) {
        return 1;
    }
}
