#include "task.hpp"
namespace foundation::ui {
std::unique_ptr<TaskExecutor> make_task_executor() { return std::make_unique<CooperativeTaskExecutor>(); }
}
