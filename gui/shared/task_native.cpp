#include "task.hpp"
#include <condition_variable>
#include <mutex>
#include <thread>

namespace foundation::ui {
namespace {
// One persistent producer owns its copied input. A one-slot latest-progress
// mailbox bounds memory; terminal state remains until the UI consumes it.
// Replacement/cancellation invalidate the generation without waiting on the UI.
class NativeTaskExecutor final : public TaskExecutor {
    struct Work { std::uint64_t generation; std::vector<std::string> input; };
    std::mutex mutex_;
    std::condition_variable changed_;
    std::optional<Work> pending_;
    std::optional<TaskUpdate> update_;
    std::uint64_t serial_ = 0, active_ = 0;
    bool closed_ = false;
    std::thread worker_{[this] { run(); }};
    void run() {
        for (;;) {
            std::unique_lock lock(mutex_);
            changed_.wait(lock, [this] { return closed_ || pending_.has_value(); });
            if (closed_) return;
            auto work = std::move(*pending_); pending_.reset();
            lock.unlock();
            TextTask task; task.start(std::move(work.input));
            while (auto value = task.advance(4096)) {
                value->generation = work.generation;
                lock.lock();
                if (closed_) return;
                if (active_ != work.generation) { lock.unlock(); break; }
                update_ = *value;
                lock.unlock();
                if (value->complete) break;
            }
        }
    }
public:
    ~NativeTaskExecutor() override { shutdown(); }
    TaskUpdate start(std::vector<std::string> input) override {
        TextTask validator;
        auto initial = validator.start(input); // Validate before changing live work.
        std::lock_guard lock(mutex_);
        if (closed_) throw std::logic_error("Task executor is closed");
        if (serial_ == std::numeric_limits<std::uint64_t>::max()) throw std::overflow_error("Task identity exhausted");
        initial.generation = ++serial_; active_ = serial_; update_.reset();
        pending_ = Work{serial_, std::move(input)}; changed_.notify_one();
        return initial;
    }
    std::optional<TaskUpdate> advance() override {
        std::lock_guard lock(mutex_);
        auto value = update_; update_.reset(); return value;
    }
    void cancel() noexcept override {
        std::lock_guard lock(mutex_);
        active_ = 0; pending_.reset(); update_.reset();
    }
    void shutdown() noexcept override {
        {
            std::lock_guard lock(mutex_);
            closed_ = true; active_ = 0; pending_.reset(); update_.reset();
        }
        changed_.notify_one();
        if (worker_.joinable()) worker_.join();
    }
};
}
std::unique_ptr<TaskExecutor> make_task_executor() { return std::make_unique<NativeTaskExecutor>(); }
} // namespace foundation::ui
