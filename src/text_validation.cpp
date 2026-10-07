#include "text_validation.h"

#if defined(FOUNDATION_USE_RUST) && FOUNDATION_USE_RUST
#include <cstdlib>

extern "C" [[noreturn]]
#if (defined(__GNUC__) || defined(__clang__)) && !defined(_WIN32)
__attribute__((visibility("hidden")))
#endif
void foundation_rust_panic() noexcept {
    std::abort();
}
#else
extern "C" uint32_t foundation_text_validate_v1(const uint8_t *bytes,
                                                 size_t length) noexcept {
    if (length == 0 || length > 256) return FOUNDATION_TEXT_INVALID_LENGTH;
    if (bytes == nullptr) return FOUNDATION_TEXT_INVALID_POINTER;
    for (size_t index = 0; index < length; ++index) {
        if (bytes[index] < 32 || bytes[index] > 126) {
            return FOUNDATION_TEXT_INVALID_ASCII;
        }
    }
    return FOUNDATION_TEXT_OK;
}

extern "C" uint32_t foundation_text_provider_v1() noexcept {
    return FOUNDATION_TEXT_PROVIDER_CPP;
}
#endif

namespace foundation::detail {
uint32_t validate_text(const uint8_t *bytes, size_t length) noexcept {
    return foundation_text_validate_v1(bytes, length);
}
}
