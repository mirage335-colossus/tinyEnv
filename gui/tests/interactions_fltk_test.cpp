#include "adapter.hpp"
#include <iostream>
#include <stdexcept>
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Restore {int key=Fl::e_keysym,state=Fl::e_state;char* text=Fl::e_text;int length=Fl::e_length;
    ~Restore(){Fl::e_keysym=key;Fl::e_state=state;Fl::e_text=text;Fl::e_length=length;}};
}
int main() {
    try {
        std::vector<gui::Event> events;gui::fltk::Adapter adapter([&](const gui::Event& e){events.push_back(e);});
        gui::Snapshot view;view.client_size={640,480};
        gui::Widget editor;editor.spec.key={"editor",1};editor.spec.kind=gui::Kind::text;editor.spec.text_policy.multiline=true;
        editor.state.bounds={10,10,270,320};editor.state.text="Native retained draft";
        gui::Widget other=editor;other.spec.key={"other",1};other.state.bounds={10,340,270,60};
        gui::Widget action;action.spec.key={"action",1};action.spec.kind=gui::Kind::button;action.state.bounds={300,10,90,30};
        gui::Widget pane;pane.spec.key={"pane",1};pane.spec.kind=gui::Kind::group;pane.state.bounds={400,10,230,440};pane.state.content_size={230,1200};
        gui::Widget choice;choice.spec.key={"choice",1};choice.spec.kind=gui::Kind::choice;choice.spec.parent="pane";
        choice.state.bounds={410,30,210,30};choice.state.options={{"one","One","",true}};choice.state.help="Explain the declared option filter";
        view.widgets={editor,other,action,pane,choice};view.key_bindings={
            {gui::ShortcutKey::enter,action.spec.key,true,false,false,editor.spec.key},
            {gui::ShortcutKey::z,action.spec.key,true,false,false,editor.spec.key}};
        adapter.present(view);adapter.show();adapter.sync();Fl::check();Fl::handle(FL_FOCUS,&adapter.window());adapter.focus(editor.spec.key);
        Restore restore;Fl::e_state=FL_CTRL;Fl::e_text=const_cast<char*>("\r");Fl::e_length=1;
        for(const auto key:{FL_Enter,int('z')}) {
            Fl::e_keysym=key;const auto before=events.size();Fl::handle(FL_KEYDOWN,&adapter.window());adapter.sync();
            check(events.size()==before+1,"Native declared editor shortcut was lost or duplicated");
            const auto& event=std::get<gui::WidgetEvent>(events.back());
            check(event.target==action.spec.key&&std::get<gui::Activate>(event.input).source==editor.spec.key,
                "Native shortcut lost its focused editor origin");
        }
        auto* native=dynamic_cast<Fl_Text_Editor*>(adapter.native_widget(editor.spec.key));
        check(native&&native->buffer()->length()==int(editor.state.text.size()),"Ctrl+Enter or declared undo modified native draft");
        view.widgets[2].state.enabled=false;adapter.present(view);adapter.sync();
        Fl::e_keysym=FL_Enter;const auto disabled=events.size();Fl::handle(FL_KEYDOWN,&adapter.window());adapter.sync();
        check(events.size()==disabled&&native->buffer()->length()==int(editor.state.text.size()),
            "Unavailable declared Ctrl+Enter fell through to native newline insertion");
        view.widgets[2].state.enabled=true;adapter.present(view);adapter.sync();
        check(std::string(adapter.native_widget(choice.spec.key)->tooltip())==choice.state.help,"Native choice did not expose declared help");
        adapter.text_selection(editor.spec.key,{3,8});const auto retained=adapter.text_selection(editor.spec.key);
        auto* fixed=adapter.native_widget(editor.spec.key);const auto original=gui::Rect{double(fixed->x()),double(fixed->y()),double(fixed->w()),double(fixed->h())};
        adapter.scroll(pane.spec.key,{0,64});adapter.sync();Fl::flush();
        check(gui::Rect{double(fixed->x()),double(fixed->y()),double(fixed->w()),double(fixed->h())}==original&&
            adapter.text_selection(editor.spec.key)==retained&&native->buffer()->length()==int(editor.state.text.size()),
            "Scrolling another pane changed retained editor state");
        adapter.window().clear_damage();adapter.scroll(pane.spec.key,{0,64});adapter.sync();
        check(adapter.window().damage()==0,"No-op native pane scroll scheduled a complete redraw");
        adapter.scroll(pane.spec.key,{0,10000});adapter.sync();Fl::flush();adapter.window().clear_damage();
        adapter.scroll(pane.spec.key,{0,10000});adapter.sync();check(adapter.window().damage()==0,"Clamped native wheel scroll redrew the window");
        adapter.close();adapter.sync();check(adapter.error().empty(),"Native interaction callback failed");
        std::cout<<"Native focused shortcuts, tooltip, retained editor and no-op scrolling passed\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
