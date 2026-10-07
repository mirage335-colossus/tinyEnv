#include "shared/task.hpp"
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>
using namespace foundation::ui;
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
TaskUpdate finish(TaskExecutor& executor, TaskUpdate initial) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (std::chrono::steady_clock::now() < deadline) {
        if (auto update = executor.advance()) {
            check(update->generation == initial.generation && update->processed >= initial.processed,
                  "Stale or regressing producer update");
            initial = *update;
            if (update->complete) return *update;
        }
        std::this_thread::yield();
    }
    throw std::runtime_error("Producer did not complete");
}
int main() { try {
    auto executor = make_task_executor();
    std::vector<std::string> input(1000, std::string(256, 'x'));
    auto initial = executor->start(input); input.clear();
    auto result = finish(*executor, initial);
    check(result.result == 256000 && !executor->advance(), "Owned input or terminal delivery lost");
    for (unsigned i=0; i<200; ++i) {
        executor->start(std::vector<std::string>(1000, std::string(256,'a')));
        executor->cancel();
        initial = executor->start({"new value"});
        result = finish(*executor,initial);
        check(result.result == 8 && result.total == 9, "Cancelled work reached replacement");
    }
    initial = executor->start({}); check(finish(*executor, initial).complete, "Empty work lost");
    executor->start(std::vector<std::string>(1000, std::string(256,'z')));
    executor->shutdown(); executor->shutdown();
    check(!executor->advance(), "Closed worker retained completion");
    bool rejected=false; try { executor->start({"late"}); } catch(const std::logic_error&) { rejected=true; }
    check(rejected,"Closed worker restarted");
    std::cout << "Native owned input, bounded mailbox, replacement, cancellation and joined shutdown passed\n";
} catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; } }
