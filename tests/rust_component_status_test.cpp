#include "foundation/store.hpp"
#include "text_validation.h"

#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

namespace {
uint32_t injected_status = FOUNDATION_TEXT_OK;

void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

template<class Error, class Function>
void rejects(Function function, const char* message) {
    try { function(); }
    catch (const Error& error) {
        require(std::string(error.what()) == message, "component status error changed");
        return;
    }
    throw std::runtime_error("component failure was accepted");
}
}

namespace foundation::detail {
// This executable substitutes a component result to test the caller's contract.
uint32_t validate_text(const uint8_t*, size_t) noexcept {
    return injected_status;
}
}

int main() {
    try {
        foundation::Store store(1);
        const auto id = store.add("Original");
        const auto before = store.snapshot();
        injected_status = FOUNDATION_TEXT_INVALID_LENGTH;
        rejects<std::invalid_argument>([&] { store.add("Input"); },
                                       "text must contain 1..256 bytes");
        injected_status = FOUNDATION_TEXT_INVALID_ASCII;
        rejects<std::invalid_argument>([&] { store.update(id, "Input"); },
                                       "text must contain printable ASCII only");
        for (const uint32_t status : {uint32_t{FOUNDATION_TEXT_INVALID_POINTER},
                                      uint32_t{4}, std::numeric_limits<uint32_t>::max()}) {
            injected_status = status;
            rejects<std::logic_error>([&] { store.add("Input"); },
                                      "text validation component failed");
            rejects<std::logic_error>([&] { store.update(id, "Input"); },
                                      "text validation component failed");
            rejects<std::logic_error>([&] { store.update(0, "Input"); },
                                      "text validation component failed");
        }
        require(store.snapshot() == before, "component failure changed records");
        injected_status = FOUNDATION_TEXT_OK;
        require(store.erase(id), "original record was lost");
        require(store.add("Next") == id + 1, "component failure consumed an ID");
        std::cout << "component failure translation passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
