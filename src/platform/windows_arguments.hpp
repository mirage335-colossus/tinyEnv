#pragma once

#ifdef _WIN32
#include <windows.h>

#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>

namespace foundation::platform {
// Convert the CRT's original UTF-16 argument before any locale/code-page loss.
// Invalid UTF-16 is an error; no replacement characters enter application data.
inline std::string utf8_argument(std::wstring_view value) {
    if (value.empty()) return {};
    if (value.size() > static_cast<std::size_t>((std::numeric_limits<int>::max)()))
        throw std::invalid_argument("Command-line argument is too long");
    const auto length = static_cast<int>(value.size());
    const int required = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS,
        value.data(), length, nullptr, 0, nullptr, nullptr);
    if (required == 0) throw std::invalid_argument("Invalid UTF-16 command-line argument");
    std::string result(static_cast<std::size_t>(required), '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), length,
            result.data(), required, nullptr, nullptr) != required)
        throw std::runtime_error("Could not convert command-line argument to UTF-8");
    return result;
}
}  // namespace foundation::platform
#endif
