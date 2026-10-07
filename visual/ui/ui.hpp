#pragma once

#include <gui/contract.hpp>
#include <cstddef>
#include <deque>
#include <exception>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

namespace foundation::visual {

enum class UiResult { applied, unchanged, missing_widget, stale_widget, wrong_kind, invalid_value, closed };
enum class SelectionPolicy { keep_if_present, clear };
enum class EventKind { activate, checked, text_changed, choose, select_record, activate_record, submit, action, pointer };

// Declarative generated metadata. Adapter IDs refer to ordinary project-owned
// lambdas/functions; this does not impose an ABI on application services.
struct EventBinding {
    std::string widget_id;
    EventKind event = EventKind::activate;
    std::string adapter_id;
};

struct SetText { gui::WidgetKey target; std::string value; };
struct SetLabel { gui::WidgetKey target; std::string value; };
struct SetEnabled { gui::WidgetKey target; bool value; };
struct Show { gui::WidgetKey target; bool value; };
struct SetChecked { gui::WidgetKey target; bool value; };
struct ReplaceOptions {
    gui::WidgetKey target;
    std::vector<gui::Option> value;
    SelectionPolicy selection = SelectionPolicy::keep_if_present;
};
struct ReplaceRecords {
    gui::WidgetKey target;
    std::vector<gui::Record> value;
    SelectionPolicy selection = SelectionPolicy::keep_if_present;
};
struct Select { gui::WidgetKey target; std::optional<std::string> value; };
using UiCommand = std::variant<SetText, SetLabel, SetEnabled, Show, SetChecked, ReplaceOptions, ReplaceRecords, Select>;

enum class Delivery { reliable, progress };
enum class PostResult { accepted, coalesced, full, stale, closed, invalid_command };
struct UiGeneration {
    std::uint64_t view = 1, request = 1;
    bool operator==(const UiGeneration&) const = default;
};

namespace ui_detail { struct Mailbox; }

// Workers keep an owned copy of this weak mailbox capability, never Ui& or an
// adapter. A successful enqueue acknowledges delivery to the UI queue, not
// execution. Reliable transitions are FIFO and are explicitly rejected if full.
class UiPost {
public:
    UiPost() = default;
    PostResult post(UiCommand command, Delivery delivery = Delivery::reliable,
                    std::string coalesce_key = {}) const;
    UiGeneration generation() const noexcept { return generation_; }
    std::size_t pending() const;
private:
    friend class Ui;
    UiPost(std::weak_ptr<ui_detail::Mailbox> mailbox, UiGeneration generation)
        : mailbox_(std::move(mailbox)), generation_(generation) {}
    std::weak_ptr<ui_detail::Mailbox> mailbox_;
    UiGeneration generation_;
};

struct UiDrainResult {
    std::size_t processed = 0;
    std::vector<UiResult> results;
    std::vector<std::exception_ptr> errors;
};
struct SelectionResult {
    UiResult result = UiResult::missing_widget;
    std::optional<std::string> value;
};
enum class DispatchResult { handled, rejected, queued, full, closed };

// Optional application-side support. The composition root owns services and
// adapter lifetimes. All Ui methods run on the constructing thread, except
// copies of UiPost, which may be used from any producer thread.
class Ui {
public:
    using Handler = std::function<void(Ui&, const gui::WidgetEvent&)>;
    class Batch {
    public:
        Batch(const Batch&) = delete;
        Batch& operator=(const Batch&) = delete;
        Batch(Batch&& other) noexcept : ui_(std::exchange(other.ui_, nullptr)) {}
        ~Batch();
    private:
        friend class Ui;
        explicit Batch(Ui& ui);
        Ui* ui_;
    };

    explicit Ui(gui::Adapter& adapter, gui::Snapshot view, std::size_t mailbox_capacity = 128);
    ~Ui();
    Ui(const Ui&) = delete;
    Ui& operator=(const Ui&) = delete;
    const gui::Snapshot& view() const;
    std::optional<gui::WidgetKey> widget(std::string_view id) const;
    Batch batch();

    UiResult set_text(const gui::WidgetKey& target, std::string value);
    UiResult set_label(const gui::WidgetKey& target, std::string value);
    UiResult set_enabled(const gui::WidgetKey& target, bool value);
    UiResult show(const gui::WidgetKey& target, bool value);
    UiResult set_checked(const gui::WidgetKey& target, bool value);
    UiResult replace_options(const gui::WidgetKey& target, std::vector<gui::Option> value,
                             SelectionPolicy selection = SelectionPolicy::keep_if_present);
    UiResult replace_records(const gui::WidgetKey& target, std::vector<gui::Record> value,
                             SelectionPolicy selection = SelectionPolicy::keep_if_present);
    UiResult select(const gui::WidgetKey& target, std::optional<std::string> value);
    SelectionResult selected(const gui::WidgetKey& target) const;
    UiResult focus(const gui::WidgetKey& target);
    UiResult invalidate_layout();

    // Stable generated IDs resolve the current generation on the owner thread.
    UiResult set_text(std::string_view id, std::string value);
    UiResult set_label(std::string_view id, std::string value);
    UiResult set_enabled(std::string_view id, bool value);
    UiResult show(std::string_view id, bool value);
    UiResult set_checked(std::string_view id, bool value);
    UiResult replace_options(std::string_view id, std::vector<gui::Option> value,
                             SelectionPolicy selection = SelectionPolicy::keep_if_present);
    UiResult replace_records(std::string_view id, std::vector<gui::Record> value,
                             SelectionPolicy selection = SelectionPolicy::keep_if_present);
    UiResult select(std::string_view id, std::optional<std::string> value);
    SelectionResult selected(std::string_view id) const;
    UiResult focus(std::string_view id);

    bool bind(std::string widget_id, EventKind event, Handler handler);
    template<class Input, class Function>
    bool bind(std::string widget_id, Function handler) {
        constexpr auto kind = [] {
            if constexpr (std::is_same_v<Input, gui::Activate>) return EventKind::activate;
            else if constexpr (std::is_same_v<Input, gui::SetChecked>) return EventKind::checked;
            else if constexpr (std::is_same_v<Input, gui::EditText>) return EventKind::text_changed;
            else if constexpr (std::is_same_v<Input, gui::ChooseOption>) return EventKind::choose;
            else if constexpr (std::is_same_v<Input, gui::SelectRecord>) return EventKind::select_record;
            else if constexpr (std::is_same_v<Input, gui::ActivateRecord>) return EventKind::activate_record;
            else if constexpr (std::is_same_v<Input, gui::SubmitText>) return EventKind::submit;
            else if constexpr (std::is_same_v<Input, gui::InvokeAction>) return EventKind::action;
            else { static_assert(std::is_same_v<Input, gui::PointerInput>, "Unsupported GUI input type"); return EventKind::pointer; }
        }();
        return bind(std::move(widget_id), kind,
                    [handler = std::make_shared<Function>(std::move(handler))](Ui& ui, const gui::WidgetEvent& event) {
                        (*handler)(ui, std::get<Input>(event.input));
                    });
    }
    DispatchResult handle(gui::Event event);
    std::size_t dispatch_pending(std::size_t max_events = 128);

    UiPost postbox() const;
    UiPost begin_request(); // Cancels queued/late updates from the prior request.
    UiDrainResult drain(std::size_t max_commands = 128);
    void restart(gui::Snapshot view); // New view generations invalidate old keys.
    void close(); // Closes this model/mailbox; the host separately owns native close.
    bool closed() const;
    bool publish(); // Retryable; failed presentation retains the authoritative view.
    bool presentation_pending() const;
    std::exception_ptr presentation_error() const;

private:
    struct Binding { std::string id; EventKind kind; std::shared_ptr<Handler> handler; };
    gui::Adapter& adapter_;
    gui::Snapshot view_;
    const std::thread::id owner_;
    std::shared_ptr<ui_detail::Mailbox> mailbox_;
    std::vector<Binding> bindings_;
    std::deque<gui::Event> events_;
    std::size_t batch_depth_ = 0, event_capacity_ = 128;
    std::uint64_t widget_epoch_ = 0;
    bool closed_ = false, dispatching_ = false, draining_ = false, dirty_ = true, pending_ = false;
    std::optional<gui::WidgetKey> pending_focus_;
    std::exception_ptr presentation_error_;
    void require_owner() const;
    UiResult lookup(const gui::WidgetKey& target, gui::Widget*& widget);
    UiResult lookup(const gui::WidgetKey& target, const gui::Widget*& widget) const;
    void changed();
    void end_batch() noexcept;
    UiResult apply(UiCommand command);
    DispatchResult dispatch_one(gui::Event event);
};

} // namespace foundation::visual
