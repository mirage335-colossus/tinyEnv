#include <foundation/store.hpp>
#include <foundation/version.hpp>
#include <cstdint>
#include <string_view>

#if defined(FOUNDATION_EXPECT_TEXT_PROVIDER)
// This qualification probe intentionally checks the private, versioned ABI.
// The ordinary installed C++ interface remains foundation::Store.
extern "C" std::uint32_t foundation_text_provider_v1() noexcept;
#endif

int main() {
#if defined(FOUNDATION_EXPECT_TEXT_PROVIDER)
    if (foundation_text_provider_v1() != FOUNDATION_EXPECT_TEXT_PROVIDER) return 1;
#endif
    foundation::Store store;
    const auto id = store.add("External consumer");
    return store.get(id)->text == "External consumer" &&
        std::string_view(FOUNDATION_VERSION) == "0.1.0" ? 0 : 1;
}
