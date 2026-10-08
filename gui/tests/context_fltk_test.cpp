#include "adapter.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
struct Restore {
    int x = Fl::e_x, y = Fl::e_y, keysym = Fl::e_keysym, state = Fl::e_state, clicks = Fl::e_clicks;
    ~Restore() { Fl::e_x = x; Fl::e_y = y; Fl::e_keysym = keysym; Fl::e_state = state; Fl::e_clicks = clicks; }
};
}
int main() {
    try {
        std::vector<gui::Event> events;
        gui::fltk::Adapter adapter([&](const gui::Event& event) { events.push_back(event); });
        gui::Snapshot view; view.client_size = {320, 220};
        gui::Widget list; list.spec.key = {"files", 1}; list.spec.kind = gui::Kind::list;
        list.spec.context_input = true; list.state.bounds = {20, 20, 180, 80};
        list.state.records = {{"one", "One", {}, true, true}}; view.widgets = {list};
        adapter.present(view); adapter.show(); adapter.sync(); Fl::check();
        Restore restore;
        Fl::e_keysym = FL_Escape; Fl::e_state = 0;
        for (const auto native_event : {FL_KEYDOWN, FL_SHORTCUT}) {
            check(adapter.window().handle(native_event) == 1,
                  "Native Escape fell through the default window handler");
            check(events.empty() && !adapter.closed() && adapter.window().shown(),
                  "Unbound Escape closed the native application");
        }
        gui::Widget dismiss; dismiss.spec.key = {"dismiss", 1}; dismiss.spec.kind = gui::Kind::button;
        dismiss.state.bounds = {220, 20, 70, 40}; dismiss.state.label = "Dismiss";
        view.widgets.push_back(dismiss); view.key_bindings = {{gui::ShortcutKey::escape, dismiss.spec.key}};
        adapter.present(view); adapter.sync();
        for (const auto native_event : {FL_KEYDOWN, FL_SHORTCUT}) {
            const auto prior = events.size();
            check(adapter.window().handle(native_event) == 1 && events.size() == prior + 1,
                  "Native Escape did not deliver its declared action exactly once");
            const auto* action = std::get_if<gui::WidgetEvent>(&events.back());
            check(action && action->target == dismiss.spec.key && std::holds_alternative<gui::Activate>(action->input) &&
                  !adapter.closed() && adapter.window().shown(), "Declared Escape action closed the native application");
        }
        events.clear(); view.widgets = {list}; view.key_bindings.clear(); adapter.present(view); adapter.sync();
        auto press = [&](int button, int x = 40, int y = 40) {
            Fl::e_x = x; Fl::e_y = y; Fl::e_keysym = FL_Button + button;
            Fl::e_state = button == FL_RIGHT_MOUSE ? FL_BUTTON3 : FL_BUTTON1; Fl::e_clicks = 0;
            adapter.window().handle(FL_PUSH);
        };
        press(FL_RIGHT_MOUSE);
        check(events.size() == 1, "Native secondary press was lost or duplicated");
        const auto* input = std::get_if<gui::PointerInput>(&std::get<gui::WidgetEvent>(events.back()).input);
        check(input && input->kind == gui::PointerKind::context_menu && input->position == gui::Point{40, 40} &&
              input->pointer_id == 0, "Native secondary press changed its generic context intent");
        Fl::e_state = 0; adapter.window().handle(FL_RELEASE);
        check(events.size() == 1, "Native secondary release synthesized another context event");
        gui::Widget raw = list; raw.spec.key = {"surface", 1}; raw.spec.kind = gui::Kind::bitmap;
        raw.spec.pointer_input = true; raw.state.records.clear();
        raw.state.bitmap = {"surface", 1, gui::solid_bitmap(240, 240, 240)};
        gui::Widget choice; choice.spec.key = {"choice", 1}; choice.spec.kind = gui::Kind::choice;
        choice.state.bounds = {220, 20, 70, 40}; choice.state.options = {{"one", "One", "", true}};
        view.widgets = {raw, choice}; adapter.present(view); adapter.sync(); press(FL_LEFT_MOUSE);
        const auto before = events.size(); press(FL_RIGHT_MOUSE);
        check(events.size() == before, "Native secondary intent interrupted primary capture");
        press(FL_RIGHT_MOUSE, 230, 40);
        check(events.size() == before, "Native foreign context popup interrupted primary capture");
        Fl::e_x = 40; Fl::e_y = 40;
        Fl::e_keysym = FL_Button + FL_LEFT_MOUSE; Fl::e_state = 0; adapter.window().handle(FL_RELEASE);
        check(events.size() == before + 1 &&
              std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(events.back()).input).kind == gui::PointerKind::release,
              "Native primary capture lost its release");
        auto native_press = [&] {
            Fl::e_x = 40; Fl::e_y = 40; Fl::e_keysym = FL_Button + FL_LEFT_MOUSE;
            Fl::e_state = FL_BUTTON1; Fl::e_clicks = 0;
            Fl::handle(FL_PUSH, &adapter.window());
            check(Fl::pushed() == &adapter.window() && !Fl::grab(),
                  "Raw pointer fixture did not acquire local native routing");
        };
        native_press(); Fl::e_keysym = FL_Escape; Fl::e_state = 0;
        Fl::handle(FL_KEYDOWN, &adapter.window());
        check(!Fl::pushed() && !Fl::grab() &&
              std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(events.back()).input).kind == gui::PointerKind::cancel,
              "Escape cancelled retained capture but left native pointer routing owned");
        const auto cancelled = events.size();
        Fl::e_keysym = FL_Button + FL_LEFT_MOUSE; Fl::handle(FL_RELEASE, &adapter.window());
        check(events.size() == cancelled, "Cancelled raw gesture later released or activated");
        native_press(); Fl::handle(FL_UNFOCUS, &adapter.window());
        check(!Fl::pushed() && !Fl::grab() && !Fl::focus() &&
              std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(events.back()).input).kind == gui::PointerKind::cancel,
              "Native focus loss retained raw pointer routing or failed to cancel");
        Fl::handle(FL_FOCUS, &adapter.window());
        gui::Widget editor; editor.spec.key = {"editor", 1}; editor.spec.kind = gui::Kind::text;
        editor.state.bounds = {20, 120, 180, 60}; editor.state.text = "Retained draft";
        view.widgets.push_back(editor); adapter.present(view); adapter.sync();
        Fl::handle(FL_FOCUS, &adapter.window());
        adapter.focus(raw.spec.key);
        check(Fl::focus() == adapter.native_widget(raw.spec.key), "Native periodic-focus fixture did not acquire the canvas");
        // Retained focus can change while presentation is queued. Synchronizing
        // that model must not make a native activation request.
        adapter.gui::RetainedAdapter::focus(editor.spec.key);
        for (int tick = 0; tick < 4; ++tick) { adapter.present(view); adapter.sync(); }
        check(Fl::focus() == adapter.native_widget(raw.spec.key),
              "Periodic presentation moved native focus instead of retaining a pending model update");
        adapter.focus(editor.spec.key); adapter.sync();
        check(Fl::focus() == adapter.native_widget(editor.spec.key), "Native focus fixture did not acquire the editor");
        Fl::handle(FL_UNFOCUS, &adapter.window());
        check(!Fl::focus(), "Native unfocus fixture did not release toolkit focus");
        for (int tick = 0; tick < 4; ++tick) { adapter.present(view); adapter.sync(); }
        check(!Fl::focus() && adapter.focused() == editor.spec.key && !adapter.closed(),
              "Background synchronization reclaimed native focus after a window-manager unfocus");
        // FLTK uses FL_HIDE without destroying the native window when a window
        // manager iconifies it. FL_SHOW/FL_FOCUS are its restore path.
        Fl::handle(FL_HIDE, &adapter.window());
        check(adapter.window().shown() && !adapter.window().visible(),
              "Native iconification fixture did not retain the hidden window");
        view.widgets.back().state.text = "Updated while iconified";
        for (int tick = 0; tick < 4; ++tick) { adapter.present(view); adapter.focus(editor.spec.key); adapter.sync(); }
        check(adapter.window().shown() && !adapter.window().visible() && !Fl::focus() && !adapter.closed(),
              "Iconified synchronization activated or reopened the native window");
        Fl::handle(FL_SHOW, &adapter.window()); Fl::handle(FL_FOCUS, &adapter.window()); adapter.sync();
        check(adapter.window().visible() && Fl::focus() == adapter.native_widget(editor.spec.key),
              "Native deiconification did not restore retained editor focus");
        adapter.window().hide();
        view.widgets.back().state.text = "Updated retained draft";
        for (int tick = 0; tick < 4; ++tick) { adapter.present(view); adapter.focus(editor.spec.key); adapter.sync(); }
        check(!adapter.window().shown() && !adapter.window().visible() && !adapter.closed() && !Fl::focus(),
              "A hidden native window was reopened by presentation or retained focus");
        adapter.window().show(); Fl::handle(FL_FOCUS, &adapter.window()); adapter.sync();
        auto* restored = dynamic_cast<Fl_Text_Editor*>(adapter.native_widget(editor.spec.key));
        check(adapter.window().shown() && adapter.window().visible() &&
              Fl::focus() == restored && restored && restored->buffer()->length() == 22,
              "Native restore lost retained focus or background draft updates");
        bool completed = false;
        native_press();
        adapter.service({9, gui::ServiceKind::prompt, "Question", ""}, [&](gui::ServiceResult) { completed = true; });
        check(!Fl::pushed() && !Fl::grab() &&
              std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(events.back()).input).kind == gui::PointerKind::cancel,
              "Native prompt transition retained raw pointer routing");
        adapter.sync(); const auto modal = events.size(); press(FL_RIGHT_MOUSE);
        check(events.size() == modal && !completed, "Native prompt allowed background context input");
        adapter.focus(editor.spec.key);
        Fl::handle(FL_UNFOCUS, Fl::modal());
        check(!Fl::focus(), "Background prompt fixture did not release native focus");
        Fl::modal()->do_callback(); adapter.sync();
        check(completed && !adapter.service_active() && !Fl::focus() && !adapter.closed(),
              "Completing a background prompt reclaimed native main-window focus");
        Fl::handle(FL_FOCUS, &adapter.window()); adapter.sync();
        check(Fl::focus() == adapter.native_widget(editor.spec.key),
              "Main-window focus did not resume after background prompt completion");
        completed = false;
        adapter.service({10, gui::ServiceKind::prompt, "Question", ""}, [&](gui::ServiceResult) { completed = true; });
        Fl::handle(FL_HIDE, &adapter.window());
        Fl::modal()->do_callback(); adapter.sync();
        check(completed && !adapter.service_active() && !adapter.window().visible() && !Fl::focus() && !adapter.closed(),
              "Completing a prompt restored an iconified main window");
        Fl::handle(FL_SHOW, &adapter.window()); Fl::handle(FL_FOCUS, &adapter.window()); adapter.sync();
        bool first_completed = false, next_completed = false;
        adapter.service({11, gui::ServiceKind::prompt, "First", ""}, [&](gui::ServiceResult) {
            first_completed = true;
            adapter.service({12, gui::ServiceKind::prompt, "Next", ""}, [&](gui::ServiceResult) { next_completed = true; });
        });
        Fl::modal()->do_callback(); adapter.sync();
        check(first_completed && !next_completed && adapter.service_active() &&
              Fl::modal() && Fl::modal() != &adapter.window() && Fl::modal()->contains(Fl::focus()),
              "Foreground completion stole native focus from its successor prompt");
        Fl::modal()->do_callback(); adapter.sync();
        check(next_completed && !adapter.service_active() && Fl::focus() == adapter.native_widget(editor.spec.key),
              "Successor prompt completion failed to restore retained native focus");
        bool replacement_completed = false;
        adapter.service({13, gui::ServiceKind::prompt, "Replace control", ""}, [&](gui::ServiceResult) {
            replacement_completed = true;
            editor.spec.key.generation = 2; view.widgets.back().spec.key = editor.spec.key;
            adapter.present(view); adapter.focus(editor.spec.key);
        });
        Fl::modal()->do_callback(); adapter.sync();
        check(replacement_completed && !adapter.service_active() &&
              Fl::focus() == adapter.native_widget(editor.spec.key),
              "Foreground completion restored focus before reply-created native controls existed");
        adapter.close(); adapter.sync(); check(adapter.error().empty(), "Native context callback failed");
        std::cout << "Native FLTK Escape, context, capture, background visibility/focus and modality passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
