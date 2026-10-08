#pragma once
#include "ui/application.hpp"
#include <filesystem>
#include <stdexcept>
#include <string_view>

namespace tinyenv::hosts {
inline std::filesystem::path utf8_path(std::string_view value) {
    return std::filesystem::path(std::u8string(value.begin(), value.end()));
}
inline bool configure(int argc, char** argv) {
    std::filesystem::path root, chat;
    bool smoke = false, root_seen = false, chat_seen = false;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument(argv[index]);
        if (argument == "--root" || argument == "--chat") {
            bool& seen = argument == "--root" ? root_seen : chat_seen;
            if (seen || index + 1 == argc || std::string_view(argv[index + 1]).empty() ||
                std::string_view(argv[index + 1]).starts_with("--"))
                throw std::invalid_argument("Supply each --root or --chat path once");
            seen = true;
            (argument == "--root" ? root : chat) = utf8_path(argv[++index]);
        } else if (argument == "--smoke-test" || argument == "--self-check" || argument == "--smoke") {
            smoke = true;
        } else {
            throw std::invalid_argument("Usage: tinyenv-workbench-HOST [--root PATH] [--chat RELATIVE-FILE] [--smoke-test]");
        }
    }
    configure_launch(root, chat, utf8_path(argv[0]));
    return smoke;
}
inline char** runner_arguments(bool smoke, char** original, char* (&arguments)[3]) {
    static char smoke_argument[] = "--smoke-test";
    arguments[0] = original[0];
    arguments[1] = smoke ? smoke_argument : nullptr;
    arguments[2] = nullptr;
    return arguments;
}
} // namespace tinyenv::hosts
