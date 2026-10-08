#include <gui/framebuffer.hpp>
#include <gui/terminal.hpp>
#include <iostream>
#include <stdexcept>
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
template<class F> void rejects(F action){bool failed=false;try{action();}catch(const std::invalid_argument&){failed=true;}check(failed,"Invalid command declaration/lifetime was accepted");}
gui::Widget widget(gui::Kind kind,const char* id,gui::Rect bounds,const char* parent=""){
    gui::Widget value;value.spec.key={id,1};value.spec.kind=kind;value.spec.parent=parent;value.state.bounds=bounds;return value;
}
gui::Snapshot scene(){
    gui::Snapshot view;view.client_size={400,200};
    view.widgets={widget(gui::Kind::group,"center",{0,0,250,150}),widget(gui::Kind::text,"editor",{10,10,220,60},"center"),
        widget(gui::Kind::text,"other",{270,10,110,60})};view.widgets[1].state.text="draft";view.widgets[1].spec.text_policy.multiline=true;
    view.commands={{{"undo",1},true,view.widgets[0].spec.key},{{"redo",1},true,view.widgets[0].spec.key}};
    view.key_bindings={{gui::ShortcutKey::z,view.commands[0].key,true,false,false,view.widgets[1].spec.key},
        {gui::ShortcutKey::z,view.commands[1].key,true,true,false,view.widgets[1].spec.key},
        {gui::ShortcutKey::y,view.commands[1].key,true,false,false,view.widgets[1].spec.key}};return view;
}
void commands(){
    auto view=scene();std::vector<gui::Event> events;gui::InteractiveAdapter adapter([&](const gui::Event& event){events.push_back(event);},
        [](const gui::TextMeasureRequest& request){return gui::Size{double(request.text.size())*8,16};});
    adapter.present(view);check(adapter.focus(view.widgets[1].spec.key),"Editor focus unavailable");
    for(const auto& stroke:{std::pair{gui::Key::z,false},std::pair{gui::Key::z,true},std::pair{gui::Key::y,false}}){
        const auto count=events.size();adapter.key(stroke.first,true,stroke.second);check(events.size()==count+1,"Command shortcut did not deliver once");
        const auto& event=std::get<gui::WidgetEvent>(events.back());check(event.target==(stroke.first==gui::Key::z&&!stroke.second?view.commands[0].key:view.commands[1].key)&&
            std::get<gui::Activate>(event.input).source==view.widgets[1].spec.key,"Command lost target or initiating focus identity");
    }
    check(!adapter.focus(view.commands[0].key),"Nonvisual command became focusable");
    adapter.focus_next();check(adapter.focused()==view.widgets[2].spec.key,"Command entered tab order");
    const auto count=events.size();adapter.key(gui::Key::z,true);check(events.size()==count,"Focused command intercepted another editor");
    check(adapter.policy().send(gui::WidgetEvent{view.commands[0].key,gui::Activate{view.widgets[1].spec.key}})==gui::Delivery::ignored,"Command forged retained focus");
    adapter.focus(view.widgets[1].spec.key);
    check(adapter.policy().send(gui::WidgetEvent{view.commands[0].key,gui::Activate{}})==gui::Delivery::ignored,"Unsourced command was activated");
    check(adapter.policy().send(gui::WidgetEvent{view.commands[0].key,gui::PointerInput{gui::PointerKind::click,{20,20}}})==gui::Delivery::ignored,"Command accepted pointer input");
    check(adapter.policy().send(gui::WidgetEvent{view.commands[0].key,gui::SetChecked{true}})==gui::Delivery::ignored,"Command accepted ordinary control input");
    view.commands[0].enabled=false;adapter.present(view);const auto disabled=events.size();adapter.key(gui::Key::z,true);
    check(events.size()==disabled&&adapter.snapshot().widgets[1].state.text=="draft","Disabled command activated or changed native editing");
    check(gui::shortcut_binding(view,{gui::ShortcutKey::z,true,false,false,view.widgets[1].spec.key})!=nullptr,"Disabled declared shortcut was no longer consumed");
    auto invalid=view;invalid.commands[0].scope=view.widgets[2].spec.key;rejects([&]{adapter.present(invalid);});
    check(adapter.snapshot().commands[0].scope==view.commands[0].scope,"Rejected scope change mutated retained command");
    invalid=view;invalid.commands[0].scope=gui::WidgetKey{"center",2};rejects([&]{gui::validate_snapshot(invalid);});
    invalid=view;invalid.commands[0].key=view.widgets[1].spec.key;rejects([&]{gui::validate_snapshot(invalid);});
    invalid=view;invalid.commands.push_back(invalid.commands[0]);rejects([&]{gui::validate_snapshot(invalid);});
    invalid=view;invalid.commands[0].key.generation=0;rejects([&]{gui::validate_snapshot(invalid);});
    const auto old=view.commands[0].key;view.commands[0].key.generation=2;view.commands[0].enabled=true;view.key_bindings[0].target=view.commands[0].key;adapter.present(view);
    check(adapter.policy().send(gui::WidgetEvent{old,gui::Activate{view.widgets[1].spec.key}})==gui::Delivery::ignored,"Stale command identity activated");
    auto removed=view;removed.commands.erase(removed.commands.begin());removed.key_bindings.erase(removed.key_bindings.begin());adapter.present(removed);
    rejects([&]{adapter.present(view);});view.commands[0].key.generation=3;view.key_bindings[0].target=view.commands[0].key;adapter.present(view);
    invalid=removed;auto fake=widget(gui::Kind::button,"undo",{0,160,60,20});fake.spec.key.generation=3;invalid.widgets.push_back(fake);rejects([&]{adapter.present(invalid);});
    view.widgets[0].state.enabled=false;adapter.present(view);check(!adapter.focus(view.widgets[1].spec.key),"Disabled command scope retained editor focus");
    gui::Event source=gui::WidgetEvent{view.commands[0].key,gui::Activate{view.widgets[1].spec.key}};check(!gui::normalize_event(view,source),"Disabled scope activated command");
    view.widgets[0].state.enabled=true;view.pages={{"one","One"},{"two","Two"}};view.active_page="one";
    view.widgets[0].spec.page="two";view.widgets[1].spec.page="two";source=gui::WidgetEvent{view.commands[0].key,gui::Activate{view.widgets[1].spec.key}};
    gui::validate_snapshot(view);check(!gui::normalize_event(view,source),"Inactive page activated command");
}
void modal_and_rendering(){
    auto view=scene();auto ordinary=view;ordinary.commands.clear();ordinary.key_bindings.clear();
    gui::TerminalAdapter commands,plain;commands.present(view);plain.present(ordinary);check(commands.render()==plain.render(),"Commands changed terminal pixels");
    gui::FramebufferAdapter pixels,baseline;pixels.present(view);baseline.present(ordinary);check(*pixels.frame().pixels==*baseline.frame().pixels,"Commands changed framebuffer pixels");
    check(gui::paint_order(view)==gui::paint_order(ordinary),"Commands entered painting order");
    check(gui::context_target(view,{15,15})==view.widgets[1].spec.key,"Command changed pointer hit target");
    std::vector<gui::Event> events;gui::TerminalAdapter terminal([&](const gui::Event& event){events.push_back(event);});terminal.present(view);terminal.focus(view.widgets[1].spec.key);
    terminal.input("\x1a");terminal.input("\x19");check(events.size()==2&&std::get<gui::WidgetEvent>(events[0]).target==view.commands[0].key&&std::get<gui::WidgetEvent>(events[1]).target==view.commands[1].key,"Terminal command strokes failed");
    auto modal=widget(gui::Kind::group,"modal",{20,80,220,100});auto editor=widget(gui::Kind::text,"modal.editor",{30,90,200,50},"modal");view.widgets.push_back(modal);view.widgets.push_back(editor);view.modal_root=modal.spec.key;
    view.commands.push_back({{"modal.command",1},true,editor.spec.key});view.commands.push_back({{"global.command",1},true,{}});
    gui::validate_snapshot(view);gui::Event background=gui::WidgetEvent{view.commands[0].key,gui::Activate{editor.spec.key}};
    check(!gui::normalize_event(view,background),"Background scope crossed modal boundary");
    gui::Event global=gui::WidgetEvent{view.commands.back().key,gui::Activate{editor.spec.key}};check(!gui::normalize_event(view,global),"Unscoped command crossed modal boundary");
    gui::Event inside=gui::WidgetEvent{view.commands[2].key,gui::Activate{editor.spec.key}};check(gui::normalize_event(view,inside),"Current modal command could not activate");
    gui::MemoryAdapter memory([](const gui::Event&){});memory.present(view);memory.focus(editor.spec.key);check(memory.send(std::get<gui::WidgetEvent>(inside))==gui::Delivery::delivered,"Sourced modal command lost retained focus");
}
}
int main(){try{commands();modal_and_rendering();std::cout<<"Nonvisual commands retain scoped sourced shortcuts, lifetimes and modal policy without rendering or focus targets\n";}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
