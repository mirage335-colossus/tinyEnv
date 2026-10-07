#pragma once
#include <algorithm>
#include <cstdint>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace foundation::ui {
struct TaskUpdate {
    std::uint64_t generation = 0;
    std::size_t processed = 0, total = 0, result = 0;
    bool complete = false;
};
// Cooperative work owns its input and performs at most budget bytes per turn.
// No adapter, UI reference, wall-clock sleep or external service enters a task.
class TextTask {
    std::vector<std::string> input_;
    TaskUpdate update_;
    std::size_t row_ = 0, offset_ = 0;
    bool running_ = false, closed_ = false;
public:
    TaskUpdate start(std::vector<std::string> input) {
        if (closed_) throw std::logic_error("Task executor is closed");
        if (input.size() > 1000) throw std::length_error("Task input exceeds record limit");
        std::size_t total = 0;
        for (const auto& text : input) {
            if (text.size() > 256) throw std::length_error("Task input exceeds text limit");
            total += text.size();
        }
        if (update_.generation == std::numeric_limits<std::uint64_t>::max())
            throw std::overflow_error("Task identity exhausted");
        update_ = {update_.generation + 1, 0, total, 0, false};
        input_ = std::move(input); row_ = offset_ = 0; running_ = true;
        return update_;
    }
    std::optional<TaskUpdate> advance(std::size_t budget = 256) {
        if (!running_) return std::nullopt;
        if (!budget || budget > 4096) throw std::invalid_argument("Task step budget must be 1..4096 bytes");
        while (budget && row_ < input_.size()) {
            const auto& text = input_[row_];
            if (offset_ == text.size()) { ++row_; offset_ = 0; continue; }
            update_.result += text[offset_++] != ' ';
            ++update_.processed; --budget;
        }
        if (update_.processed == update_.total) {
            update_.complete = true; running_ = false; input_.clear();
        }
        return update_;
    }
    void cancel() noexcept { running_ = false; input_.clear(); }
    void shutdown() noexcept { cancel(); closed_ = true; }
    bool running() const noexcept { return running_; }
};

class TaskExecutor {
public:
    virtual ~TaskExecutor() = default;
    virtual TaskUpdate start(std::vector<std::string>) = 0;
    virtual std::optional<TaskUpdate> advance() = 0;
    virtual void cancel() noexcept = 0;
    virtual void shutdown() noexcept = 0;
};
class CooperativeTaskExecutor final : public TaskExecutor {
    TextTask task_;
public:
    TaskUpdate start(std::vector<std::string> input) override { return task_.start(std::move(input)); }
    std::optional<TaskUpdate> advance() override { return task_.advance(); }
    void cancel() noexcept override { task_.cancel(); }
    void shutdown() noexcept override { task_.shutdown(); }
};
// The build selects scheduling policy once for the platform. Application
// features depend only on this value-oriented interface, never a UI toolkit.
std::unique_ptr<TaskExecutor> make_task_executor();
} // namespace foundation::ui
