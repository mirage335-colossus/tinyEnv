#ifndef FOUNDATION_TEXT_VALIDATION_H
#define FOUNDATION_TEXT_VALIDATION_H

#include <stddef.h>
#include <stdint.h>

#if (defined(__GNUC__) || defined(__clang__)) && !defined(_WIN32)
#define FOUNDATION_TEXT_HIDDEN __attribute__((visibility("hidden")))
#else
#define FOUNDATION_TEXT_HIDDEN
#endif

/* Private in-process ABI. These numeric values are shared by both providers. */
enum {
    FOUNDATION_TEXT_OK = 0,
    FOUNDATION_TEXT_INVALID_LENGTH = 1,
    FOUNDATION_TEXT_INVALID_ASCII = 2,
    FOUNDATION_TEXT_INVALID_POINTER = 3,
    FOUNDATION_TEXT_PROVIDER_CPP = 0,
    FOUNDATION_TEXT_PROVIDER_RUST = 1
};

#ifdef __cplusplus
extern "C" {
#define FOUNDATION_TEXT_NOEXCEPT noexcept
#else
#define FOUNDATION_TEXT_NOEXCEPT
#endif

/* Length errors precede pointer errors. For length 1..256, bytes must address
   that many initialized bytes in one live allocation, unchanged until return.
   The function neither mutates nor retains the buffer. */
FOUNDATION_TEXT_HIDDEN uint32_t foundation_text_validate_v1(const uint8_t *bytes, size_t length)
    FOUNDATION_TEXT_NOEXCEPT;
FOUNDATION_TEXT_HIDDEN uint32_t foundation_text_provider_v1(void) FOUNDATION_TEXT_NOEXCEPT;

#ifdef __cplusplus
}
namespace foundation::detail {
FOUNDATION_TEXT_HIDDEN uint32_t validate_text(const uint8_t *bytes, size_t length) noexcept;
}
#endif
#undef FOUNDATION_TEXT_NOEXCEPT
#undef FOUNDATION_TEXT_HIDDEN

#endif
