#include "foundation/store.hpp"

#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
template<class Error, class Function> void rejects(Function function) {
    try { function(); }
    catch (const Error&) { return; }
    throw std::runtime_error("expected rejection did not occur");
}
template<class Function> void rejects_text(Function function, const char* message) {
    try { function(); }
    catch (const std::invalid_argument& error) {
        require(std::string(error.what()) == message, "text error message changed");
        return;
    }
    throw std::runtime_error("expected text rejection did not occur");
}
}

int main() {
    try {
        rejects<std::invalid_argument>([] { foundation::Store store(0); });
        rejects<std::invalid_argument>([] { foundation::Store store(4097); });
        foundation::Store store(2);
        const auto a = store.add("Alpha");
        const auto b = store.add("Beta");
        require(a == 1 && b == 2, "initial IDs");
        const auto before = store.snapshot();
        rejects<std::length_error>([&] { store.add("Gamma"); });
        constexpr auto length_error = "text must contain 1..256 bytes";
        constexpr auto ascii_error = "text must contain printable ASCII only";
        rejects_text([&] { store.add(""); }, length_error);
        rejects_text([&] { store.add("bad\ntext"); }, ascii_error);
        rejects_text([&] { store.update(a, std::string_view{}); }, length_error);
        rejects_text([&] { store.update(a, std::string(257, 'x')); }, length_error);
        rejects_text([&] { store.update(a, std::string(257, '\n')); }, length_error);
        rejects_text([&] { store.update(a, "bad\ntext"); }, ascii_error);
        rejects_text([&] { store.update(a, std::string("a\0b", 3)); }, ascii_error);
        rejects_text([&] { store.update(0, ""); }, length_error);
        rejects_text([&] { store.update(0, "bad\ntext"); }, ascii_error);
        require(store.snapshot() == before, "failed operation changed state");
        require(!store.update(0, "Valid") && !store.erase(0), "missing ID accepted");
        require(store.update(a, std::string(256, 'x')), "maximum length rejected");
        auto copy = store.get(a);
        copy->text = "local";
        require(store.get(a)->text.size() == 256, "copy modified owned state");
        require(store.erase(a) && !store.get(a), "erase failed");
        require(store.add("Gamma") == 3, "ID reused or failure consumed ID");
        require(store.get(b)->text == "Beta", "unrelated record changed");
        foundation::Store bytes(1);
        for (unsigned value = 0; value < 256; ++value) {
            const auto text = std::string(1, static_cast<char>(value));
            if (value >= 32 && value <= 126) {
                const auto id = bytes.add(text);
                require(bytes.get(id)->text == text, "valid byte changed");
                bytes.erase(id);
            } else {
                rejects<std::invalid_argument>([&] { bytes.add(text); });
            }
        }
        std::cout << "store contract passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
