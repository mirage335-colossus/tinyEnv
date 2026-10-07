#pragma once

#include "view_definition.hpp"
#include "task.hpp"
#include <gui/runtime.hpp>
#include <foundation/store.hpp>
#include <functional>

namespace foundation::ui {

// Only the composition root knows which concrete adapter is supplied.
class Application {
public:
    explicit Application(gui::Adapter& adapter, std::unique_ptr<TaskExecutor> executor = make_task_executor());
    const gui::Snapshot& view() const noexcept { return view_; }
    void handle(gui::Event event);
    void retry_presentation();
    void tick();
    void shutdown() noexcept;
    bool complete_task(const TaskUpdate& update);
    const TaskUpdate& task_progress() const noexcept { return task_progress_; }
    bool task_running() const noexcept { return task_running_; }
    ~Application() { shutdown(); }
    bool presentation_pending() const noexcept { return presentation_pending_; }
    // Authoritative input meaning, independent of painting/revision retries.
    // UINT64_MAX is permanently invalid for retained input tokens.
    std::uint64_t input_epoch() const noexcept { return input_epoch_; }
    std::optional<gui::ServiceRequest> next_service();
    bool complete_service(gui::ServiceResult result);

    // Demonstrates an ordinary feature extension without modifying a renderer.
    void enable_remove_feature();
    // Installed qualification keeps every feature identity on the shared side.
    // The host supplies only a bounded presentation/event-loop step.
    void qualify(const std::function<void()>& present);

private:
    gui::Adapter& adapter_;
    gui::Snapshot view_;
    gui::ServiceQueue services_;
    static constexpr std::size_t entry_limit_ = 1000;
    foundation::Store entries_{entry_limit_};
    std::uint64_t next_service_ = 1;
    std::uint64_t input_epoch_ = 1;
    std::size_t pending_services_ = 0;
    bool shutdown_ = false;
    bool presentation_pending_ = false;
    bool remove_feature_ = false;
    std::string status_ = "Ready";
    bool status_error_ = false;
    std::unique_ptr<TaskExecutor> task_;
    TaskUpdate task_progress_;
    bool task_running_ = false;
    std::string task_status_ = "Task ready";

    gui::Widget& add(const ViewDefinition& definition);
    static gui::Widget& lookup(gui::Snapshot& view, std::string_view id);
    gui::Widget& get(std::string_view id) { return lookup(view_, id); }
    void append_entry();
    void advance_input_epoch();
    void publish();
};

} // namespace foundation::ui
