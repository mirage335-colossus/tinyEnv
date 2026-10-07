#include "text_validation.h"

#include <array>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
}

int main() {
    try {
#if defined(FOUNDATION_EXPECT_RUST) && FOUNDATION_EXPECT_RUST
        constexpr uint32_t expected_provider = FOUNDATION_TEXT_PROVIDER_RUST;
#else
        constexpr uint32_t expected_provider = FOUNDATION_TEXT_PROVIDER_CPP;
#endif
        require(foundation_text_provider_v1() == expected_provider,
                "linked text provider differs from configured provider");
        const uint8_t one = 'x';
        require(foundation::detail::validate_text(&one, 1) == FOUNDATION_TEXT_OK,
                "C++ validation bridge rejected valid text");
        for (const auto* pointer : {static_cast<const uint8_t*>(nullptr), &one}) {
            for (const size_t length : {size_t{0}, size_t{257},
                                       std::numeric_limits<size_t>::max()}) {
                require(foundation_text_validate_v1(pointer, length) == FOUNDATION_TEXT_INVALID_LENGTH,
                        "invalid length did not precede buffer access");
            }
        }
        for (const size_t length : {size_t{1}, size_t{256}}) {
            require(foundation_text_validate_v1(nullptr, length) == FOUNDATION_TEXT_INVALID_POINTER,
                    "nonnull buffer contract was not enforced");
        }
        for (unsigned value = 0; value <= 255; ++value) {
            const auto byte = static_cast<uint8_t>(value);
            const uint32_t expected = value >= 32 && value <= 126
                ? FOUNDATION_TEXT_OK : FOUNDATION_TEXT_INVALID_ASCII;
            require(foundation_text_validate_v1(&byte, 1) == expected,
                    "single byte acceptance differs from printable ASCII");
        }
        std::array<uint8_t, 256> bytes;
        bytes.fill('~');
        const auto valid_bytes = bytes;
        for (size_t length = 1; length <= bytes.size(); ++length) {
            require(foundation_text_validate_v1(bytes.data(), length) == FOUNDATION_TEXT_OK,
                    "allowed length rejected");
        }
        require(bytes == valid_bytes, "validation changed valid borrowed bytes");
        for (size_t position = 0; position < bytes.size(); ++position) {
            for (const uint8_t invalid : {uint8_t{0}, uint8_t{31}, uint8_t{127},
                                         uint8_t{128}, uint8_t{255}}) {
                bytes[position] = invalid;
                const auto input = bytes;
                require(foundation_text_validate_v1(bytes.data(), bytes.size()) == FOUNDATION_TEXT_INVALID_ASCII,
                        "invalid byte was missed within a bounded buffer");
                require(bytes == input, "validation changed invalid borrowed bytes");
            }
            bytes[position] = '~';
        }
        require(bytes == valid_bytes, "validation changed the borrowed buffer");
        std::cout << "text component ABI passed (provider="
                  << (expected_provider == FOUNDATION_TEXT_PROVIDER_RUST ? "Rust" : "C++")
                  << ")\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
