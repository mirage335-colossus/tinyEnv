#include "adapter.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Events {int key=Fl::e_keysym,state=Fl::e_state,length=Fl::e_length,x=Fl::e_x,y=Fl::e_y,dx=Fl::e_dx,dy=Fl::e_dy;char* text=Fl::e_text;
    ~Events(){Fl::e_keysym=key;Fl::e_state=state;Fl::e_length=length;Fl::e_text=text;Fl::e_x=x;Fl::e_y=y;Fl::e_dx=dx;Fl::e_dy=dy;}};
struct Clipboard:Fl_Widget {std::string received;Clipboard():Fl_Widget(0,0,0,0){}void draw()override{}
    int handle(int event)override{if(event==FL_PASTE){received.assign(Fl::event_text(),std::size_t(Fl::event_length()));return 1;}return 0;}};
void pixel(gui::fltk::Adapter& adapter,Fl_Widget& native,gui::Color expected){
    Fl::flush();adapter.window().make_current();const std::unique_ptr<unsigned char[]> image(fl_read_image(nullptr,native.x(),native.y(),1,1));
    if(!image||gui::Color{image[0],image[1],image[2]}!=expected){
        std::cerr<<"frame expected "<<int(expected.red)<<','<<int(expected.green)<<','<<int(expected.blue)<<" actual ";
        if(image)std::cerr<<int(image[0])<<','<<int(image[1])<<','<<int(image[2]);else std::cerr<<"unavailable";
        std::cerr<<" focused="<<(adapter.focused()==gui::WidgetKey{"text",1})<<" text_frame="<<adapter.snapshot().widgets[1].state.text_frame
                 <<" bounds="<<native.x()<<','<<native.y()<<','<<native.w()<<','<<native.h()<<" shown="<<adapter.window().shown()<<'\n';
        throw std::runtime_error("Native text perimeter retained/changed its frame unexpectedly");
    }
}
gui::Snapshot scene(bool multiline,bool readonly,bool masked){
    gui::Snapshot view;view.client_size={420,260};gui::Widget parent;parent.spec.key={"parent",1};parent.spec.kind=gui::Kind::group;
    parent.state.bounds={0,0,400,240};parent.state.content_size={400,1000};
    gui::Widget text;text.spec.key={"text",1};text.spec.kind=gui::Kind::text;text.spec.parent="parent";text.spec.text_policy={multiline,readonly,8192,gui::SubmitKey::none,masked};
    text.state.bounds={20,20,280,multiline?80.0:32.0};text.state.text="Selectable readonly prose";text.state.wrap=gui::TextWrap::none;view.widgets={parent,text};return view;
}
void exercise(bool multiline,bool readonly,bool masked){
    gui::fltk::Adapter adapter;auto view=scene(multiline,readonly,masked);const auto key=view.widgets[1].spec.key;
    adapter.present(view);adapter.show();adapter.sync();
    // A new X window must process its initial native Expose before capture.
    // This fixed bounded readiness step precedes all appearance assertions.
    for(int attempt=0;attempt<10;++attempt){Fl::wait(.01);adapter.sync();Fl::flush();}
    Fl::handle(FL_FOCUS,&adapter.window());
    auto* native=adapter.native_widget(key);check(native,"Native text control missing");adapter.focus(std::nullopt);adapter.sync();pixel(adapter,*native,view.palette.border);
    check(native->take_focus()&&adapter.focused()==key,"Native text focus unavailable");adapter.text_selection(key,{2,12});adapter.sync();pixel(adapter,*native,view.palette.accent);
    const std::array<int,4> geometry{native->x(),native->y(),native->w(),native->h()};const auto box=native->box();
    view.widgets[1].state.text_frame=false;adapter.present(view);adapter.sync();Fl::flush();
    check(adapter.native_widget(key)==native&&Fl::focus()==native&&adapter.focused()==key&&adapter.text_selection(key)==gui::TextSelection{2,12},"Appearance update replaced native text or changed focus/selection");
    check(geometry==std::array<int,4>{native->x(),native->y(),native->w(),native->h()}&&native->box()==box,"Borderless native text changed box geometry/padding");
    pixel(adapter,*native,view.palette.surface);Events restore;
    if(!masked){
        Clipboard copied;Fl::e_state=FL_CTRL;Fl::e_keysym='c';Fl::e_text=const_cast<char*>("c");Fl::e_length=1;
        native->handle(FL_KEYDOWN);Fl::paste(copied,1);Fl::check();
        check(copied.received==view.widgets[1].state.text.substr(2,10),"Borderless native text lost original clipboard selection");
        Fl::belowmouse(native);Fl::e_x=30;Fl::e_y=30;Fl::e_state=0;Fl::e_dx=0;Fl::e_dy=1;Fl::handle(FL_MOUSEWHEEL,&adapter.window());adapter.sync();Fl::flush();
        check(adapter.scroll_offset(view.widgets[0].spec.key).y==32&&adapter.text_selection(key)==gui::TextSelection{2,12},"Borderless fitting text lost ancestor wheel/selection");
        adapter.scroll(view.widgets[0].spec.key,{});adapter.sync();
    }
    view.widgets[1].state.text_frame=true;adapter.present(view);adapter.sync();pixel(adapter,*native,view.palette.accent);
    check(adapter.native_widget(key)==native&&adapter.text_selection(key)==gui::TextSelection{2,12},"Restoring frame replaced native selection");
    adapter.close();adapter.sync();check(adapter.error().empty(),"Native text appearance callback failed");
}
}
int main(){try{for(bool readonly:{false,true}){exercise(false,readonly,false);exercise(true,readonly,false);exercise(false,readonly,true);}
    std::cout<<"Native text/secret frames opt out and restore without changing control, focus, selection, copy, padding or wheel ownership\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
