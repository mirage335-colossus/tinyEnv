#include "workbench/core/launch.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
template<class Operation> void fails(Operation operation) {
    try { operation(); } catch (const std::exception&) { return; }
    throw std::runtime_error("Invalid launch root was accepted");
}
struct Fixture {
    std::filesystem::path root = std::filesystem::temp_directory_path() /
        ("tinyenv-launch-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    Fixture() { std::filesystem::create_directory(root); }
    ~Fixture() { std::error_code error; std::filesystem::remove_all(root, error); }
};
}

int main() {
    try {
        Fixture fixture;
        const auto home = fixture.root / "home";
        std::filesystem::create_directory(home);
        const auto expected = home / "tinyEnv/casual-chats";
        check(!std::filesystem::exists(expected), "Fixture already had a casual chats directory");
        check(tinyenv::resolve_launch_root({}, home) == expected && std::filesystem::is_directory(expected),
              "Omitted root did not create home casual chats directory");
        std::ofstream(expected / "keep.chat.md") << "Keep existing conversation\n";
        check(tinyenv::resolve_launch_root({}, home) == expected && std::filesystem::file_size(expected / "keep.chat.md") > 0,
              "Reopening default root modified an existing conversation");

        const auto explicit_root = fixture.root / "explicit";
        check(tinyenv::resolve_launch_root(explicit_root, {}) == explicit_root && !std::filesystem::exists(explicit_root),
              "Explicit root was created or depended on a home directory");
        check(tinyenv::resolve_launch_root(std::filesystem::path("relative-project"), home) == "relative-project",
              "Explicit relative project root changed");
        fails([&] { (void)tinyenv::resolve_launch_root({}, {}); });
        fails([&] { (void)tinyenv::resolve_launch_root({}, "relative-home"); });
        fails([&] { (void)tinyenv::resolve_launch_root({}, fixture.root / "missing-home"); });
        check(!std::filesystem::exists(fixture.root / "missing-home"), "Missing home was created");

        const auto blocked = fixture.root / "blocked-home";
        std::filesystem::create_directory(blocked);
        std::ofstream(blocked / "tinyEnv") << "ordinary file\n";
        fails([&] { (void)tinyenv::resolve_launch_root({}, blocked); });

#if defined(__unix__)
        const auto linked = fixture.root / "linked-home";
        const auto outside = fixture.root / "outside";
        std::filesystem::create_directory(linked);
        std::filesystem::create_directory(outside);
        std::filesystem::create_directory_symlink(outside, linked / "tinyEnv");
        fails([&] { (void)tinyenv::resolve_launch_root({}, linked); });
        check(!std::filesystem::exists(outside / "casual-chats"), "Default root followed a child symlink");
#endif
        std::cout << "launch: home casual chats creation, repeat launch and explicit-root preservation passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
