#include "ui.hpp"

#include <algorithm>
#include <limits>
#include <mutex>
#include <set>
#include <stdexcept>
#include <utility>

namespace foundation::visual {
namespace ui_detail {
struct Message {
    UiGeneration generation;
    UiCommand command;
    Delivery delivery;
    std::string key;
    std::size_t bytes;
};
struct Mailbox {
    explicit Mailbox(std::size_t capacity) : capacity(capacity) {}
    mutable std::mutex mutex;
    std::deque<Message> messages;
    UiGeneration generation;
    const std::size_t capacity;
    static constexpr std::size_t byte_capacity = 16 * 1024 * 1024;
    std::size_t bytes = 0;
    bool closed = false;
};
}
namespace {
std::size_t payload_bytes(const UiCommand& command) {
    // Saturation makes maliciously large producer payloads fail the byte bound.
    std::size_t bytes = sizeof(ui_detail::Message);
    const auto add = [&](std::size_t amount) {
        if (amount > std::numeric_limits<std::size_t>::max() - bytes)
            bytes = std::numeric_limits<std::size_t>::max();
        else bytes += amount;
    };
    std::visit([&](const auto& value) {
        using T = std::decay_t<decltype(value)>;
        add(value.target.id.capacity());
        if constexpr (std::is_same_v<T, SetText> || std::is_same_v<T, SetLabel>) add(value.value.capacity());
        else if constexpr (std::is_same_v<T, ReplaceOptions>) {
            if (value.value.capacity() > std::numeric_limits<std::size_t>::max() / sizeof(gui::Option))
                add(std::numeric_limits<std::size_t>::max());
            else add(value.value.capacity() * sizeof(gui::Option));
            for (const auto& item : value.value) {
                add(item.id.capacity()); add(item.label.capacity()); add(item.value.capacity());
            }
        } else if constexpr (std::is_same_v<T, ReplaceRecords>) {
            if (value.value.capacity() > std::numeric_limits<std::size_t>::max() / sizeof(gui::Record))
                add(std::numeric_limits<std::size_t>::max());
            else add(value.value.capacity() * sizeof(gui::Record));
            for (const auto& item : value.value) {
                add(item.id.capacity()); add(item.accessible_text.capacity());
                if (item.cells.capacity() > std::numeric_limits<std::size_t>::max() / sizeof(gui::Cell))
                    add(std::numeric_limits<std::size_t>::max());
                else add(item.cells.capacity() * sizeof(gui::Cell));
                for (const auto& cell : item.cells) add(cell.text.capacity());
            }
        } else if constexpr (std::is_same_v<T, Select>) {
            if (value.value) add(value.value->capacity());
        }
    }, command);
    return bytes;
}
bool valid_selection_policy(SelectionPolicy value) {
    return value == SelectionPolicy::clear || value == SelectionPolicy::keep_if_present;
}
bool modal_ancestor(const gui::Snapshot& view, const gui::WidgetKey& target) {
    if (!view.modal_root) return false;
    const auto* current = gui::find_widget(view, *view.modal_root);
    for (std::size_t depth = 0; current && depth <= view.widgets.size(); ++depth) {
        if (current->spec.key == target) return true;
        if (current->spec.parent.empty()) break;
        const auto parent = current->spec.parent;
        current = nullptr;
        for (const auto& candidate : view.widgets) if (candidate.spec.key.id == parent) { current = &candidate; break; }
    }
    return false;
}
bool supports(EventKind event, const gui::Widget& widget) {
    switch (event) {
        case EventKind::activate: return widget.spec.kind == gui::Kind::button;
        case EventKind::checked: return widget.spec.kind == gui::Kind::toggle;
        case EventKind::text_changed: case EventKind::submit: return widget.spec.kind == gui::Kind::text;
        case EventKind::choose: return widget.spec.kind == gui::Kind::choice || widget.spec.kind == gui::Kind::menu || widget.spec.kind == gui::Kind::text;
        case EventKind::select_record: case EventKind::activate_record: return widget.spec.kind == gui::Kind::list;
        case EventKind::action: return widget.spec.kind == gui::Kind::bitmap;
        case EventKind::pointer: return widget.spec.pointer_input;
    }
    return false;
}
EventKind event_kind(const gui::Input& input) {
    return std::visit([](const auto& value) {
        using T = std::decay_t<decltype(value)>;
        if constexpr (std::is_same_v<T, gui::Activate>) return EventKind::activate;
        else if constexpr (std::is_same_v<T, gui::SetChecked>) return EventKind::checked;
        else if constexpr (std::is_same_v<T, gui::EditText>) return EventKind::text_changed;
        else if constexpr (std::is_same_v<T, gui::ChooseOption>) return EventKind::choose;
        else if constexpr (std::is_same_v<T, gui::SelectRecord>) return EventKind::select_record;
        else if constexpr (std::is_same_v<T, gui::ActivateRecord>) return EventKind::activate_record;
        else if constexpr (std::is_same_v<T, gui::SubmitText>) return EventKind::submit;
        else if constexpr (std::is_same_v<T, gui::InvokeAction>) return EventKind::action;
        else return EventKind::pointer;
    }, input);
}
template<class Items>
bool has_id(const Items& items, const std::string& id) {
    return std::any_of(items.begin(), items.end(), [&](const auto& item) { return item.id == id; });
}
}

PostResult UiPost::post(UiCommand command, Delivery delivery, std::string key) const {
    const auto mailbox = mailbox_.lock();
    if (!mailbox) return PostResult::closed;
    const bool valid_target = std::visit([](const auto& value) {
        return !value.target.id.empty() && value.target.generation != 0 && gui::valid_utf8(value.target.id);
    }, command);
    if (!valid_target || (delivery != Delivery::reliable && delivery != Delivery::progress) ||
        (delivery == Delivery::progress && (key.empty() || !gui::valid_utf8(key))))
        return PostResult::invalid_command;
    auto bytes = payload_bytes(command);
    if (key.capacity() > ui_detail::Mailbox::byte_capacity || bytes > ui_detail::Mailbox::byte_capacity - key.capacity())
        return PostResult::full;
    bytes += key.capacity();
    std::lock_guard lock(mailbox->mutex);
    if (mailbox->closed) return PostResult::closed;
    if (generation_ != mailbox->generation) return PostResult::stale;
    if (delivery == Delivery::progress) {
        for (auto& previous : mailbox->messages) {
            if (previous.delivery == Delivery::progress && previous.key == key && previous.generation == generation_) {
                if (bytes > ui_detail::Mailbox::byte_capacity - (mailbox->bytes - previous.bytes)) return PostResult::full;
                // Replacement retains its place relative to reliable transitions.
                const auto previous_bytes = previous.bytes;
                previous = ui_detail::Message{generation_, std::move(command), delivery, std::move(key), bytes};
                mailbox->bytes = mailbox->bytes - previous_bytes + bytes;
                return PostResult::coalesced;
            }
        }
    }
    if (mailbox->messages.size() >= mailbox->capacity || bytes > ui_detail::Mailbox::byte_capacity - mailbox->bytes)
        return PostResult::full;
    mailbox->messages.push_back({generation_, std::move(command), delivery, std::move(key), bytes});
    mailbox->bytes += bytes;
    return PostResult::accepted;
}
std::size_t UiPost::pending() const {
    const auto mailbox = mailbox_.lock();
    if (!mailbox) return 0;
    std::lock_guard lock(mailbox->mutex);
    return mailbox->closed || generation_ != mailbox->generation ? 0 : mailbox->messages.size();
}

Ui::Batch::Batch(Ui& ui) : ui_(&ui) { ui.require_owner(); ++ui.batch_depth_; }
Ui::Batch::~Batch() { if (ui_) ui_->end_batch(); }
Ui::Ui(gui::Adapter& adapter, gui::Snapshot view, std::size_t capacity)
    : adapter_(adapter), view_(std::move(view)), owner_(std::this_thread::get_id()),
      mailbox_(std::make_shared<ui_detail::Mailbox>(capacity)) {
    if (!capacity) throw std::invalid_argument("UI mailbox capacity must be positive.");
    gui::validate_snapshot(view_);
    for (const auto& item : view_.widgets) widget_epoch_ = std::max(widget_epoch_, item.spec.key.generation);
    publish();
}
Ui::~Ui() {
    // No native operations in destruction; the host owns its adapter and loop.
    std::lock_guard lock(mailbox_->mutex);
    mailbox_->closed = true;
    mailbox_->messages.clear();
    mailbox_->bytes = 0;
}
void Ui::require_owner() const {
    if (std::this_thread::get_id() != owner_) throw std::logic_error("Ui access requires its owner thread; workers use UiPost.");
}
const gui::Snapshot& Ui::view() const { require_owner(); return view_; }
std::optional<gui::WidgetKey> Ui::widget(std::string_view id) const {
    require_owner();
    if (closed_) return std::nullopt;
    for (const auto& item : view_.widgets) if (item.spec.key.id == id) return item.spec.key;
    return std::nullopt;
}
Ui::Batch Ui::batch() { return Batch(*this); }
UiResult Ui::lookup(const gui::WidgetKey& target, const gui::Widget*& output) const {
    require_owner(); output = nullptr;
    if (closed_) return UiResult::closed;
    for (const auto& item : view_.widgets) {
        if (item.spec.key.id != target.id) continue;
        if (item.spec.key.generation != target.generation) return UiResult::stale_widget;
        output = &item; return UiResult::unchanged;
    }
    return UiResult::missing_widget;
}
UiResult Ui::lookup(const gui::WidgetKey& target, gui::Widget*& output) {
    const gui::Widget* item = nullptr;
    const auto result = std::as_const(*this).lookup(target, item);
    output = const_cast<gui::Widget*>(item); return result;
}
void Ui::changed() { dirty_ = true; if (!batch_depth_) publish(); }
void Ui::end_batch() noexcept {
    if (batch_depth_) --batch_depth_;
    if (!batch_depth_) {
        try { publish(); }
        catch (...) { presentation_error_ = std::current_exception(); pending_ = true; }
    }
}

UiResult Ui::set_text(const gui::WidgetKey& target, std::string value) {
    gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (item->spec.kind == gui::Kind::group || item->spec.kind == gui::Kind::bitmap) return UiResult::wrong_kind;
    if (!gui::valid_utf8(value) || (item->spec.kind == gui::Kind::text && !gui::text_error(value, item->spec.text_policy).empty()))
        return UiResult::invalid_value;
    if (item->state.text == value) return UiResult::unchanged;
    item->state.text = std::move(value); changed(); return UiResult::applied;
}
UiResult Ui::set_label(const gui::WidgetKey& target, std::string value) {
    gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (!gui::valid_utf8(value)) return UiResult::invalid_value;
    if (item->state.label == value) return UiResult::unchanged;
    item->state.label = std::move(value); changed(); return UiResult::applied;
}
UiResult Ui::set_enabled(const gui::WidgetKey& target, bool value) {
    gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (item->state.enabled == value) return UiResult::unchanged;
    if (!value && modal_ancestor(view_, target)) return UiResult::invalid_value;
    item->state.enabled = value; changed(); return UiResult::applied;
}
UiResult Ui::show(const gui::WidgetKey& target, bool value) {
    gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (item->state.visible == value) return UiResult::unchanged;
    if (!value && modal_ancestor(view_, target)) return UiResult::invalid_value;
    item->state.visible = value; changed(); return UiResult::applied;
}
UiResult Ui::set_checked(const gui::WidgetKey& target, bool value) {
    gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (item->spec.kind != gui::Kind::toggle) return UiResult::wrong_kind;
    if (item->state.checked == value) return UiResult::unchanged;
    item->state.checked = value; changed(); return UiResult::applied;
}
UiResult Ui::replace_options(const gui::WidgetKey& target, std::vector<gui::Option> value, SelectionPolicy policy) {
    gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (item->spec.kind != gui::Kind::choice && item->spec.kind != gui::Kind::menu && item->spec.kind != gui::Kind::text)
        return UiResult::wrong_kind;
    if (!valid_selection_policy(policy)) return UiResult::invalid_value;
    std::set<std::string> ids;
    for (const auto& option : value) {
        if (option.id.empty() || !ids.insert(option.id).second || !gui::valid_utf8(option.id) ||
            !gui::valid_utf8(option.label) || !gui::valid_utf8(option.value) ||
            (item->spec.kind == gui::Kind::text && !gui::text_error(option.value, item->spec.text_policy).empty()))
            return UiResult::invalid_value;
    }
    auto selection = item->state.selected;
    if (policy == SelectionPolicy::clear || (selection && !has_id(value, *selection))) selection.reset();
    if (item->state.options == value && item->state.selected == selection) return UiResult::unchanged;
    item->state.options = std::move(value); item->state.selected = std::move(selection); changed(); return UiResult::applied;
}
UiResult Ui::replace_records(const gui::WidgetKey& target, std::vector<gui::Record> value, SelectionPolicy policy) {
    gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (item->spec.kind != gui::Kind::list) return UiResult::wrong_kind;
    if (!valid_selection_policy(policy) || double(value.size()) * item->spec.row_height > gui::coordinate_limit)
        return UiResult::invalid_value;
    std::set<std::string> ids;
    for (const auto& row : value) {
        if (row.id.empty() || !ids.insert(row.id).second || !gui::valid_utf8(row.id) || !gui::valid_utf8(row.accessible_text))
            return UiResult::invalid_value;
        for (const auto& cell : row.cells) {
            if (!gui::valid_utf8(cell.text) || !gui::valid_rect(cell.bounds)) return UiResult::invalid_value;
            try { gui::validate_font(cell.font); gui::validate_wrap(cell.wrap); }
            catch (const std::invalid_argument&) { return UiResult::invalid_value; }
        }
    }
    auto selection = item->state.selected;
    if (policy == SelectionPolicy::clear || (selection && !has_id(value, *selection))) selection.reset();
    if (item->state.records == value && item->state.selected == selection) return UiResult::unchanged;
    item->state.records = std::move(value); item->state.selected = std::move(selection); changed(); return UiResult::applied;
}
UiResult Ui::select(const gui::WidgetKey& target, std::optional<std::string> value) {
    gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (item->spec.kind != gui::Kind::list && item->spec.kind != gui::Kind::choice) return UiResult::wrong_kind;
    if (value && (value->empty() || !gui::valid_utf8(*value) ||
        !(item->spec.kind == gui::Kind::list ? has_id(item->state.records, *value) : has_id(item->state.options, *value))))
        return UiResult::invalid_value;
    if (item->state.selected == value) return UiResult::unchanged;
    item->state.selected = std::move(value); changed(); return UiResult::applied;
}
SelectionResult Ui::selected(const gui::WidgetKey& target) const {
    const gui::Widget* item; const auto status = lookup(target, item); if (!item) return {status, {}};
    if (item->spec.kind != gui::Kind::choice && item->spec.kind != gui::Kind::list) return {UiResult::wrong_kind, {}};
    return {UiResult::unchanged, item->state.selected};
}
UiResult Ui::focus(const gui::WidgetKey& target) {
    const gui::Widget* item; const auto status = lookup(target, item); if (!item) return status;
    if (!gui::focusable(*item)) return UiResult::wrong_kind;
    const auto area = gui::availability(view_, target,
        [&](const gui::WidgetKey& key) { return adapter_.scroll_offset(key); });
    if (!area.enabled || !area.visible) return UiResult::invalid_value;
    pending_focus_ = target;
    if (!batch_depth_) publish();
    return UiResult::applied;
}
UiResult Ui::invalidate_layout() {
    require_owner(); if (closed_) return UiResult::closed;
    changed(); return UiResult::applied;
}

#define FOUNDATION_VISUAL_ID_SETTER(name, type) \
UiResult Ui::name(std::string_view id, type value) { \
    const auto target = widget(id); \
    if (!target) return closed_ ? UiResult::closed : UiResult::missing_widget; \
    return name(*target, std::move(value)); \
}
FOUNDATION_VISUAL_ID_SETTER(set_text, std::string)
FOUNDATION_VISUAL_ID_SETTER(set_label, std::string)
FOUNDATION_VISUAL_ID_SETTER(set_enabled, bool)
FOUNDATION_VISUAL_ID_SETTER(show, bool)
FOUNDATION_VISUAL_ID_SETTER(set_checked, bool)
FOUNDATION_VISUAL_ID_SETTER(select, std::optional<std::string>)
#undef FOUNDATION_VISUAL_ID_SETTER
UiResult Ui::replace_options(std::string_view id, std::vector<gui::Option> value, SelectionPolicy policy) {
    const auto target = widget(id); if (!target) return closed_ ? UiResult::closed : UiResult::missing_widget;
    return replace_options(*target, std::move(value), policy);
}
UiResult Ui::replace_records(std::string_view id, std::vector<gui::Record> value, SelectionPolicy policy) {
    const auto target = widget(id); if (!target) return closed_ ? UiResult::closed : UiResult::missing_widget;
    return replace_records(*target, std::move(value), policy);
}
SelectionResult Ui::selected(std::string_view id) const {
    const auto target = widget(id); if (!target) return {closed_ ? UiResult::closed : UiResult::missing_widget, {}};
    return selected(*target);
}
UiResult Ui::focus(std::string_view id) {
    const auto target = widget(id); if (!target) return closed_ ? UiResult::closed : UiResult::missing_widget;
    return focus(*target);
}

bool Ui::bind(std::string id, EventKind kind, Handler handler) {
    require_owner(); if (closed_ || !handler) return false;
    const auto target = widget(id); if (!target) return false;
    if (!supports(kind, *gui::find_widget(view_, *target))) return false;
    bindings_.push_back({std::move(id), kind, std::make_shared<Handler>(std::move(handler))}); return true;
}
DispatchResult Ui::dispatch_one(gui::Event event) {
    if (closed_) return DispatchResult::closed;
    if (!gui::normalize_event(view_, event, [&](const gui::WidgetKey& target) { return adapter_.scroll_offset(target); }))
        return DispatchResult::rejected;
    auto updates = batch();
    if (const auto* input = std::get_if<gui::WidgetEvent>(&event)) {
        std::visit([&](const auto& value) {
            using T = std::decay_t<decltype(value)>;
            if constexpr (std::is_same_v<T, gui::SetChecked>) set_checked(input->target, value.value);
            else if constexpr (std::is_same_v<T, gui::EditText>) set_text(input->target, value.value);
            else if constexpr (std::is_same_v<T, gui::ChooseOption>) {
                const auto* item = gui::find_widget(view_, input->target);
                if (item->spec.kind == gui::Kind::choice) select(input->target, value.id);
                else if (item->spec.kind == gui::Kind::text)
                    for (const auto& option : item->state.options) if (option.id == value.id) { set_text(input->target, option.value); break; }
            } else if constexpr (std::is_same_v<T, gui::SelectRecord> || std::is_same_v<T, gui::ActivateRecord>) select(input->target, value.id);
        }, input->input);
        const auto kind = event_kind(input->input);
        // Retain callable identities, so mutable callable state persists while
        // handlers can safely add bindings/restart during dispatch.
        std::vector<std::shared_ptr<Handler>> handlers;
        for (const auto& binding : bindings_) if (binding.id == input->target.id && binding.kind == kind) handlers.push_back(binding.handler);
        for (auto& handler : handlers) {
            if (closed_ || !gui::find_widget(view_, input->target)) break;
            (*handler)(*this, *input);
        }
    } else if (const auto* page = std::get_if<gui::PageEvent>(&event)) {
        view_.active_page = page->id; changed();
    } else if (const auto* size = std::get_if<gui::ResizeEvent>(&event)) {
        view_.client_size = size->client_size; view_.display_scale = size->display_scale; changed();
    } else if (std::holds_alternative<gui::CloseEvent>(event)) close();
    return DispatchResult::handled;
}
DispatchResult Ui::handle(gui::Event event) {
    require_owner(); if (closed_) return DispatchResult::closed;
    if (dispatching_ || !events_.empty()) {
        if (events_.size() >= event_capacity_) return DispatchResult::full;
        events_.push_back(std::move(event));
        if (!dispatching_) dispatch_pending(event_capacity_);
        return DispatchResult::queued;
    }
    struct Reset { bool& value; ~Reset() { value = false; } } reset{dispatching_};
    dispatching_ = true;
    const auto first = dispatch_one(std::move(event));
    // Bounded per turn, even if a handler keeps synthesizing further actions.
    for (std::size_t count = 0; !events_.empty() && count < event_capacity_; ++count) {
        auto next = std::move(events_.front()); events_.pop_front(); dispatch_one(std::move(next));
    }
    return first;
}
std::size_t Ui::dispatch_pending(std::size_t maximum) {
    require_owner();
    if (dispatching_) throw std::logic_error("Recursive GUI event dispatch is not allowed.");
    struct Reset { bool& value; ~Reset() { value = false; } } reset{dispatching_}; dispatching_ = true;
    std::size_t count = 0;
    while (!closed_ && !events_.empty() && count < maximum) {
        auto event = std::move(events_.front()); events_.pop_front(); ++count;
        dispatch_one(std::move(event));
    }
    return count;
}

UiPost Ui::postbox() const {
    require_owner(); std::lock_guard lock(mailbox_->mutex); return UiPost(mailbox_, mailbox_->generation);
}
UiPost Ui::begin_request() {
    require_owner(); std::deque<ui_detail::Message> discarded;
    UiGeneration generation;
    {
        std::lock_guard lock(mailbox_->mutex);
        if (closed_) return UiPost(mailbox_, mailbox_->generation);
        if (mailbox_->generation.request == std::numeric_limits<std::uint64_t>::max())
            throw std::overflow_error("UI request generation exhausted.");
        ++mailbox_->generation.request;
        discarded.swap(mailbox_->messages); mailbox_->bytes = 0; generation = mailbox_->generation;
    }
    return UiPost(mailbox_, generation);
}
UiResult Ui::apply(UiCommand command) {
    return std::visit([&](auto value) {
        using T = std::decay_t<decltype(value)>;
        if constexpr (std::is_same_v<T, SetText>) return set_text(value.target, std::move(value.value));
        else if constexpr (std::is_same_v<T, SetLabel>) return set_label(value.target, std::move(value.value));
        else if constexpr (std::is_same_v<T, SetEnabled>) return set_enabled(value.target, value.value);
        else if constexpr (std::is_same_v<T, Show>) return show(value.target, value.value);
        else if constexpr (std::is_same_v<T, SetChecked>) return set_checked(value.target, value.value);
        else if constexpr (std::is_same_v<T, ReplaceOptions>) return replace_options(value.target, std::move(value.value), value.selection);
        else if constexpr (std::is_same_v<T, ReplaceRecords>) return replace_records(value.target, std::move(value.value), value.selection);
        else return select(value.target, std::move(value.value));
    }, std::move(command));
}
UiDrainResult Ui::drain(std::size_t maximum) {
    require_owner();
    if (draining_) throw std::logic_error("Recursive UI mailbox drain is not allowed.");
    struct Reset { bool& value; ~Reset() { value = false; } } reset{draining_}; draining_ = true;
    UiDrainResult result; auto updates = batch();
    for (std::size_t count = 0; count < maximum; ++count) {
        std::optional<ui_detail::Message> message;
        {
            std::lock_guard lock(mailbox_->mutex);
            if (mailbox_->closed || mailbox_->messages.empty()) break;
            message.emplace(std::move(mailbox_->messages.front())); mailbox_->messages.pop_front();
            mailbox_->bytes -= message->bytes;
        }
        ++result.processed;
        try { result.results.push_back(apply(std::move(message->command))); }
        catch (...) { result.errors.push_back(std::current_exception()); }
    }
    return result;
}
void Ui::restart(gui::Snapshot view) {
    require_owner(); if (closed_) throw std::logic_error("A closed UI instance cannot restart.");
    gui::validate_snapshot(view);
    std::uint64_t epoch = widget_epoch_;
    for (const auto& item : view.widgets) epoch = std::max(epoch, item.spec.key.generation);
    if (epoch == std::numeric_limits<std::uint64_t>::max()) throw std::overflow_error("Widget generation exhausted.");
    ++epoch;
    for (auto& item : view.widgets) item.spec.key.generation = epoch;
    for (auto& binding : view.key_bindings) binding.target.generation = epoch;
    if (view.modal_root) view.modal_root->generation = epoch;
    view.revision = view_.revision;
    std::deque<ui_detail::Message> discarded;
    {
        std::lock_guard lock(mailbox_->mutex);
        if (mailbox_->generation.view == std::numeric_limits<std::uint64_t>::max() || mailbox_->generation.request == std::numeric_limits<std::uint64_t>::max())
            throw std::overflow_error("UI generation exhausted.");
        ++mailbox_->generation.view; ++mailbox_->generation.request;
        discarded.swap(mailbox_->messages); mailbox_->bytes = 0;
    }
    view_ = std::move(view); widget_epoch_ = epoch; pending_focus_.reset(); events_.clear(); bindings_.clear(); changed();
}
void Ui::close() {
    require_owner(); if (closed_) return;
    closed_ = true; pending_focus_.reset(); events_.clear(); bindings_.clear();
    std::deque<ui_detail::Message> discarded;
    { std::lock_guard lock(mailbox_->mutex); mailbox_->closed = true; discarded.swap(mailbox_->messages); mailbox_->bytes = 0; }
}
bool Ui::closed() const { require_owner(); return closed_; }
bool Ui::publish() {
    require_owner(); if (closed_) return false;
    if (batch_depth_) return true;
    try {
        if (dirty_) {
            if (view_.revision == std::numeric_limits<std::uint64_t>::max()) throw std::overflow_error("UI presentation revision exhausted.");
            gui::validate_snapshot(view_);
            ++view_.revision; dirty_ = false; pending_ = true;
        }
        if (pending_) { adapter_.present(view_); pending_ = false; }
        if (pending_focus_) {
            if (!adapter_.focus(*pending_focus_)) throw std::runtime_error("Requested widget could not receive focus.");
            pending_focus_.reset();
        }
        presentation_error_ = {}; return true;
    } catch (...) { presentation_error_ = std::current_exception(); return false; }
}
bool Ui::presentation_pending() const { require_owner(); return dirty_ || pending_ || pending_focus_.has_value(); }
std::exception_ptr Ui::presentation_error() const { require_owner(); return presentation_error_; }

} // namespace foundation::visual
