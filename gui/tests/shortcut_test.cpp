#include <gui/interaction.hpp>
#include <gui/terminal.hpp>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
gui::Widget control(gui::Kind kind,const char* id,gui::Rect bounds) {
    gui::Widget widget;widget.spec.key={id,1};widget.spec.kind=kind;widget.state.bounds=bounds;return widget;
}
}
int main() {
    try {
        std::vector<gui::Event> events;
        gui::InteractiveAdapter adapter([&](const gui::Event& event){events.push_back(event);},
            [](const gui::TextMeasureRequest& request){return gui::Size{double(request.text.size())*8,16};});
        gui::Snapshot view;view.client_size={500,300};
        auto first=control(gui::Kind::text,"first",{0,0,140,60});first.spec.text_policy.multiline=true;
        auto second=control(gui::Kind::text,"second",{0,70,140,60});
        auto send=control(gui::Kind::button,"send",{160,0,80,30});
        auto undo=control(gui::Kind::button,"undo",{160,40,80,30});
        view.widgets={first,second,send,undo};
        view.key_bindings={{gui::ShortcutKey::enter,send.spec.key,true,false,false,first.spec.key},
            {gui::ShortcutKey::z,undo.spec.key,true,false,false,first.spec.key},
            {gui::ShortcutKey::z,send.spec.key,true,false,false,second.spec.key}};
        adapter.present(view);adapter.focus(first.spec.key);
        adapter.key(gui::Key::enter,true);
        check(events.size()==1,"Focused Ctrl+Enter was not delivered once");
        auto event=std::get<gui::WidgetEvent>(events.back());
        check(event.target==send.spec.key&&std::get<gui::Activate>(event.input).source==first.spec.key,
            "Shortcut lost its initiating editor identity");
        adapter.key(gui::Key::z,true);event=std::get<gui::WidgetEvent>(events.back());
        check(event.target==undo.spec.key&&std::get<gui::Activate>(event.input).source==first.spec.key,
            "Focused Z shortcut did not retain its initiating editor");
        adapter.focus(second.spec.key);const auto previous=events.size();adapter.key(gui::Key::enter,true);
        check(events.size()==previous,"Focused shortcut intercepted another editor");
        adapter.key(gui::Key::z,true);event=std::get<gui::WidgetEvent>(events.back());
        check(event.target==send.spec.key&&std::get<gui::Activate>(event.input).source==second.spec.key,
            "Distinct scopes sharing one stroke were not resolved");
        adapter.policy().send(gui::ShortcutEvent{gui::ShortcutKey::z,true,false,false,first.spec.key});
        check(std::get<gui::Activate>(std::get<gui::WidgetEvent>(events.back()).input).source==second.spec.key,
            "Caller forged the actual focused shortcut origin");
        view.key_bindings.push_back({gui::ShortcutKey::y,undo.spec.key,true});adapter.present(view);
        adapter.key(gui::Key::y,true);check(std::get<gui::WidgetEvent>(events.back()).target==undo.spec.key,
            "Unscoped shortcut compatibility changed");
        auto invalid=view;invalid.key_bindings.front().focus=gui::WidgetKey{"first",2};
        bool rejected=false;try{adapter.present(invalid);}catch(const std::invalid_argument&){rejected=true;}
        check(rejected,"Stale shortcut scope was accepted");
        invalid=view;invalid.key_bindings.push_back(invalid.key_bindings.front());rejected=false;
        try{adapter.present(invalid);}catch(const std::invalid_argument&){rejected=true;}
        check(rejected,"Duplicate focused stroke was accepted");
        view.widgets[0].state.visible=false;adapter.present(view);const auto hidden=events.size();
        gui::Event stale=gui::WidgetEvent{undo.spec.key,gui::Activate{first.spec.key}};
        check(!gui::normalize_event(view,stale)&&events.size()==hidden,"Hidden activation origin was accepted");
        gui::TerminalAdapter terminal([&](const gui::Event& e){events.push_back(e);});terminal.present(view);terminal.focus(second.spec.key);
        terminal.input("\x19");check(std::get<gui::WidgetEvent>(events.back()).target==undo.spec.key,"Terminal Ctrl+Y was not translated");
        terminal.input("\x1a");check(std::get<gui::WidgetEvent>(events.back()).target==send.spec.key,"Terminal Ctrl+Z lost focused routing");
        // Unrelated pixel storage must remain retained during a text-only pane
        // scroll, and an unchanged offset must retain every pixel grid.
        gui::MemoryAdapter memory;gui::Snapshot scroll;scroll.client_size={300,200};
        auto pane=control(gui::Kind::group,"pane",{0,0,100,100});pane.state.content_size={100,400};
        auto label=control(gui::Kind::label,"label",{0,30,80,40});label.spec.parent="pane";
        auto bitmap=control(gui::Kind::bitmap,"bitmap",{130,0,150,150});
        bitmap.state.bitmap={"pixels",1,gui::solid_bitmap(20,40,60)};scroll.widgets={pane,label,bitmap};
        memory.present(scroll);memory.repaint(bitmap.spec.key);const auto* pixels=memory.image(bitmap.spec.key).pixels().data();
        memory.scroll(pane.spec.key,{0,32});
        check(memory.scroll_offset(pane.spec.key)==gui::Point{0,32}&&memory.image(bitmap.spec.key).pixels().data()==pixels,
            "Text-only group scrolling copied unrelated bitmap storage");
        check(memory.resolved_availability(label.spec.key).bounds==gui::Rect{0,-2,80,40},"Fast pane scroll changed descendant geometry");
        memory.scroll(pane.spec.key,{0,32});
        check(memory.image(bitmap.spec.key).pixels().data()==pixels,"No-op group scrolling copied pixel storage");
        memory.scroll(pane.spec.key,{0,999});const auto end=memory.scroll_offset(pane.spec.key);
        memory.scroll(pane.spec.key,{0,999});check(memory.scroll_offset(pane.spec.key)==end&&memory.image(bitmap.spec.key).pixels().data()==pixels,
            "Clamped no-op scrolling replaced pixel storage");
        // A modal descendant still prevents scrolling it out of input reach.
        auto modal=control(gui::Kind::group,"modal",{0,10,80,50});modal.spec.parent="pane";
        scroll.widgets.push_back(modal);scroll.modal_root=modal.spec.key;memory.scroll(pane.spec.key,{0,0});memory.present(scroll);
        rejected=false;try{memory.scroll(pane.spec.key,{0,300});}catch(const std::invalid_argument&){rejected=true;}
        check(rejected&&memory.scroll_offset(pane.spec.key)==gui::Point{},"Fast scroll did not roll back a hidden modal");
        std::cout<<"Focused shortcut origins and retained group scrolling passed\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
