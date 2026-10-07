#pragma once

#include <cstddef>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace foundation::editor {

enum class ProcessState { idle, running, succeeded, failed, cancelled };
struct ProcessStatus {
    ProcessState state{ProcessState::idle};
    int exit_code{-1};
    std::string output;
    bool output_truncated{};
    std::string error;
    [[nodiscard]] bool finished() const noexcept { return state != ProcessState::running && state != ProcessState::idle; }
};

// One owned process tree. start is an explicit action; argv is never shell text.
// poll is nonblocking. cancel terminates and joins the owned tree. Destruction
// cancels remaining work. Successful exit requires descendant output to finish.
class ProcessRunner {
public:
    explicit ProcessRunner(std::size_t max_log_bytes = 2 * 1024 * 1024);
    ~ProcessRunner();
    ProcessRunner(const ProcessRunner&) = delete;
    ProcessRunner& operator=(const ProcessRunner&) = delete;
    void start(const std::vector<std::string>& argv, const std::filesystem::path& cwd);
    [[nodiscard]] ProcessStatus poll();
    [[nodiscard]] ProcessStatus cancel();
    [[nodiscard]] bool running() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace foundation::editor
