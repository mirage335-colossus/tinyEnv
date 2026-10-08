#pragma once

#include "json.hpp"

#include <cstddef>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace tinyenv {

enum class ServiceState { idle, running, succeeded, failed, cancelled };

struct JobStatus {
    ServiceState state{ServiceState::idle};
    int exit_code{-1};
    std::optional<json::Value> response;
    std::string error;
    // Validated assistant preview, retained after a failed/cancelled stream.
    // A final successful response remains authoritative. Legacy workers leave
    // these fields at their defaults until returning their single JSON result.
    std::string partial_text;
    bool streaming{};
    std::size_t stream_revision{};
    [[nodiscard]] bool finished() const noexcept {
        return state != ServiceState::idle && state != ServiceState::running;
    }
};

// Explicit, owned runtime invocation. Credentials belong in private provider
// configuration/environment, never in the transient request. Construction and
// polling do not contact providers or execute project scripts. The optional
// absolute credential_directory is trusted application startup configuration;
// only its path is passed separately to the worker, never key bytes.
// Chat/agent requests may explicitly set stream:true. Version-1 NDJSON progress
// is parsed incrementally with bounded frames, text and wire bytes; the legacy
// single-JSON response remains supported. Invalid progress stops/joins the
// worker and retains only the previously validated assistant preview.
class Job {
public:
    explicit Job(std::size_t max_response_bytes = 8 * 1024 * 1024,
                 std::filesystem::path runtime_path = {},
                 std::string python_executable = {},
                 std::filesystem::path credential_directory = {});
    ~Job();
    Job(const Job&) = delete;
    Job& operator=(const Job&) = delete;
    void start(const json::Value& request, const std::filesystem::path& root);
    [[nodiscard]] JobStatus poll();
    [[nodiscard]] JobStatus cancel();
    [[nodiscard]] bool running() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

struct TerminalStatus {
    bool running{};
    int exit_code{-1};
    std::string output;
    std::string error;
    bool output_truncated{};
};

// Keep one inert instance per chat. start is an explicit terminal action and
// launches Bash without profiles or rc files. send submits a user command;
// drain is nonblocking and returns the bounded, printable UTF-8 transcript.
// shutdown owns and joins the shell and descendants, including escaped groups.
class Terminal {
public:
    explicit Terminal(std::size_t max_scrollback_bytes = 1024 * 1024);
    ~Terminal();
    Terminal(const Terminal&) = delete;
    Terminal& operator=(const Terminal&) = delete;
    void start(const std::filesystem::path& cwd);
    void send(std::string_view command);
    [[nodiscard]] TerminalStatus drain();
    void resize(unsigned columns, unsigned rows);
    void interrupt();
    void shutdown();
    [[nodiscard]] bool running() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

struct GitFile {
    char index_status{' '};
    char worktree_status{' '};
    std::string path;
    std::string original_path;
};
struct GitStatus {
    ServiceState state{ServiceState::idle};
    std::string branch;
    std::vector<GitFile> files;
    std::string error;
    [[nodiscard]] bool finished() const noexcept {
        return state != ServiceState::idle && state != ServiceState::running;
    }
};

// Read-only local status with paging, hooks, submodule inspection and filesystem
// monitor commands disabled. Active clean/process filters fail closed before
// status; unused global filter settings are harmless. The optional project_root
// excludes the full workbench project when cwd is a nested chat directory.
// Git is selected outside that project through absolute PATH entries.
// No network or Git mutation operation is exposed.
class GitStatusJob {
public:
    GitStatusJob();
    ~GitStatusJob();
    GitStatusJob(const GitStatusJob&) = delete;
    GitStatusJob& operator=(const GitStatusJob&) = delete;
    void start(const std::filesystem::path& cwd, const std::filesystem::path& project_root = {});
    [[nodiscard]] GitStatus poll();
    [[nodiscard]] GitStatus cancel();
    [[nodiscard]] bool running() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace tinyenv
