#include "adapter.hpp"
#include <iostream>
#include <stdexcept>
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Events {int key=Fl::e_keysym,state=Fl::e_state,length=Fl::e_length,x=Fl::e_x,y=Fl::e_y;char* text=Fl::e_text;
    ~Events(){Fl::e_keysym=key;Fl::e_state=state;Fl::e_length=length;Fl::e_x=x;Fl::e_y=y;Fl::e_text=text;}};
}
int main(){try{
    gui::Snapshot view;view.client_size={500,280};gui::Widget editor;editor.spec.key={"editor",1};editor.spec.kind=gui::Kind::text;
    editor.spec.text_policy.multiline=true;editor.state.bounds={20,20,220,90};editor.state.text="draft";view.widgets={editor};
    view.commands={{{"undo",1},false,editor.spec.key},{{"redo",1},true,editor.spec.key}};
    view.key_bindings={{gui::ShortcutKey::z,view.commands[0].key,true,false,false,editor.spec.key},
        {gui::ShortcutKey::z,view.commands[1].key,true,true,false,editor.spec.key},{gui::ShortcutKey::y,view.commands[1].key,true,false,false,editor.spec.key}};
    gui::fltk::Adapter* active=nullptr;std::vector<gui::WidgetEvent> commands;
    gui::fltk::Adapter adapter([&](const gui::Event& event){if(const auto* widget=std::get_if<gui::WidgetEvent>(&event)){
        if(const auto* edit=std::get_if<gui::EditText>(&widget->input)){view.widgets[0].state.text=edit->value;active->present(view);}
        else commands.push_back(*widget);
    }});active=&adapter;adapter.present(view);adapter.show();adapter.sync();Fl::check();Fl::flush();
    auto* native=dynamic_cast<Fl_Text_Editor*>(adapter.native_widget(editor.spec.key));check(native,"Native editor missing");
    check(!adapter.native_widget(view.commands[0].key)&&!adapter.native_widget(view.commands[1].key),"Command created a native control");
    Events restore;Fl::belowmouse(native);Fl::e_x=native->x()+20;Fl::e_y=native->y()+20;Fl::e_keysym=FL_Button+FL_LEFT_MOUSE;Fl::e_state=FL_BUTTON1;
    Fl::handle(FL_PUSH,&adapter.window());Fl::e_state=0;Fl::handle(FL_RELEASE,&adapter.window());adapter.sync();Fl::flush();
    check(adapter.focused()==editor.spec.key&&Fl::focus()==native,"Mouse-selected native editor focus failed");
    Fl::e_keysym='a';Fl::e_text=const_cast<char*>("a");Fl::e_length=1;Fl::handle(FL_KEYDOWN,&adapter.window());adapter.sync();Fl::flush();
    const auto edited=view.widgets[0].state.text;check(edited.size()==6,"Native editing did not create undo history");
    Fl::e_state=FL_CTRL;Fl::e_keysym='z';Fl::e_text=const_cast<char*>("z");Fl::handle(FL_KEYDOWN,&adapter.window());adapter.sync();Fl::flush();
    check(commands.empty()&&view.widgets[0].state.text==edited&&native->buffer()->length()==6,"Disabled command fell through to ordinary native undo");
    view.commands[0].enabled=true;adapter.present(view);adapter.sync();Fl::flush();
    for(const auto& stroke:{std::pair{'z',FL_CTRL},std::pair{'z',FL_CTRL|FL_SHIFT},std::pair{'y',FL_CTRL}}){
        Fl::e_keysym=stroke.first;Fl::e_state=stroke.second;Fl::handle(FL_KEYDOWN,&adapter.window());adapter.sync();Fl::flush();
    }
    check(commands.size()==3&&commands[0].target==view.commands[0].key&&commands[1].target==view.commands[1].key&&commands[2].target==view.commands[1].key,"Native Ctrl+Z/Shift+Z/Y command routing failed");
    for(const auto& command:commands)check(std::get<gui::Activate>(command.input).source==editor.spec.key,"Native command lost source focus");
    check(view.widgets[0].state.text==edited&&adapter.focused()==editor.spec.key,"Command routing changed text or focus");
    const auto children=adapter.window().children();view.commands.clear();view.key_bindings.clear();adapter.present(view);adapter.sync();Fl::flush();
    check(adapter.window().children()==children,"Removing commands changed native child controls");
    adapter.close();adapter.sync();check(adapter.error().empty(),"Native command callback failed");
    std::cout<<"Native nonvisual commands have no controls and consume scoped Ctrl+Z/Shift+Z/Y before native undo\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
