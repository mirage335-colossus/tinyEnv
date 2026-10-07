#pragma once
#include "ui/application.hpp"
#include <filesystem>
#include <stdexcept>
#include <string_view>

namespace foundation::editor::hosts {
inline std::filesystem::path utf8_path(std::string_view value) {
    std::u8string bytes;
    bytes.reserve(value.size());
    for (const auto byte : value) bytes.push_back(static_cast<char8_t>(static_cast<unsigned char>(byte)));
    return std::filesystem::path(bytes);
}
inline bool configure(int argc, char** argv) {
    std::filesystem::path project, root;
    bool smoke = false;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument(argv[index]);
        if (argument == "--project" && index + 1 < argc) project = utf8_path(argv[++index]);
        else if (argument == "--root" && index + 1 < argc) root = utf8_path(argv[++index]);
        else if (argument == "--smoke-test" || argument == "--self-check" || argument == "--smoke") smoke = true;
        else throw std::invalid_argument("Usage: foundation-editor-HOST [--project PATH] [--root PATH] [--smoke-test]");
    }
    configure_launch(project, root, utf8_path(argv[0]));
    return smoke;
}
// The existing generic runners receive only their supported physical-host flags.
inline char** runner_arguments(bool smoke, char** original, char* (&arguments)[3]) {
    static char smoke_argument[] = "--smoke-test";
    arguments[0] = original[0];
    arguments[1] = smoke ? smoke_argument : nullptr;
    arguments[2] = nullptr;
    return arguments;
}
} // namespace foundation::editor::hosts
