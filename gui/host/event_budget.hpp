#pragma once
#include <chrono>
#include <cstddef>
namespace foundation::host {
// Bound event draining so a continuously nonempty input queue cannot starve
// presentation. The first blocking/waited event is counted by the caller.
class EventBudget {
    std::size_t remaining_;
    std::chrono::steady_clock::time_point deadline_;
public:
    explicit EventBudget(std::size_t count = 127,
                         std::chrono::milliseconds duration = std::chrono::milliseconds(4))
        : remaining_(count), deadline_(std::chrono::steady_clock::now() + duration) {}
    bool take() {
        if (!remaining_ || std::chrono::steady_clock::now() >= deadline_) return false;
        --remaining_; return true;
    }
};
} // namespace foundation::host
