#include "adapter.hpp"
#include <cstdlib>
#include <iostream>
#include <stdexcept>
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Events {int x=Fl::e_x,y=Fl::e_y,dx=Fl::e_dx,dy=Fl::e_dy;~Events(){Fl::e_x=x;Fl::e_y=y;Fl::e_dx=dx;Fl::e_dy=dy;}};
gui::Snapshot scene(bool overflow,bool canvas){
    gui::Snapshot view;view.client_size={500,300};
    gui::Widget outer;outer.spec.key={"outer",1};outer.spec.kind=gui::Kind::group;outer.state.bounds={0,0,300,180};outer.state.content_size={300,900};
    gui::Widget inner;inner.spec.key={"inner",1};inner.spec.kind=gui::Kind::group;inner.spec.parent="outer";inner.state.bounds={0,0,300,160};inner.state.content_size={300,160};
    gui::Widget child;child.spec.key={"child",1};child.spec.parent="inner";child.state.bounds={10,10,280,80};
    if(canvas){child.spec.kind=gui::Kind::bitmap;child.spec.pointer_input=true;child.state.bitmap={"canvas",1,gui::solid_bitmap(20,30,40)};}
    else{child.spec.kind=gui::Kind::text;child.spec.text_policy={true,true,10000,gui::SubmitKey::none};child.state.wrap=gui::TextWrap::none;
        child.state.text=overflow?std::string("One\nTwo\nThree\nFour\nFive\nSix\nSeven\nEight\nNine\nTen\n"):"A fitting readonly block";}
    view.widgets={outer,inner,child};return view;
}
void wheel(gui::fltk::Adapter& adapter,Fl_Widget* native,int dy){
    Fl::belowmouse(native);Fl::e_x=30;Fl::e_y=30;Fl::e_dx=0;Fl::e_dy=dy;
    Fl::handle(FL_MOUSEWHEEL,&adapter.window());adapter.sync();Fl::flush();
}
void readonly(bool overflow){
    gui::fltk::Adapter adapter;auto view=scene(overflow,false);adapter.present(view);adapter.show();adapter.sync();Fl::check();
    Fl::handle(FL_FOCUS,&adapter.window());adapter.focus(view.widgets[2].spec.key);adapter.text_selection(view.widgets[2].spec.key,{0,0});adapter.scroll(view.widgets[2].spec.key,{});adapter.sync();Fl::flush();
    auto* native=dynamic_cast<Fl_Text_Editor*>(adapter.native_widget(view.widgets[2].spec.key));check(native,"Readonly native editor missing");Events restore;
    wheel(adapter,native,1);
    if(overflow){check(adapter.scroll_offset(view.widgets[2].spec.key).y>0&&adapter.scroll_offset(view.widgets[0].spec.key).y==0,"Overflowing native text did not retain wheel ownership");
        adapter.scroll(view.widgets[2].spec.key,{0,1e6});adapter.sync();wheel(adapter,native,1);}
    check(adapter.scroll_offset(view.widgets[0].spec.key).y==32&&adapter.scroll_offset(view.widgets[1].spec.key).y==0,"Clamped native text/inner group swallowed ancestor wheel");
    char* bytes=native->buffer()->text();const std::string native_text(bytes);std::free(bytes);
    check(adapter.text_selection(view.widgets[2].spec.key)==gui::TextSelection{0,0}&&native_text==view.widgets[2].state.text,"Native readonly wheel changed text or caret");
    adapter.close();adapter.sync();check(adapter.error().empty(),"Native wheel callback failed");
}
void canvas(){
    std::vector<gui::Event> events;gui::fltk::Adapter adapter([&](const gui::Event& event){events.push_back(event);});auto view=scene(false,true);
    gui::Widget label;label.spec.key={"label",1};label.spec.kind=gui::Kind::label;label.spec.parent="inner";label.state.bounds={10,10,280,80};label.state.text="Inert canvas label";view.widgets.push_back(label);
    adapter.present(view);adapter.show();adapter.sync();Fl::check();Events restore;events.clear();wheel(adapter,adapter.native_widget(label.spec.key),-1);
    check(events.size()==1,"Native canvas wheel was lost/duplicated");const auto& event=std::get<gui::WidgetEvent>(events[0]);const auto& input=std::get<gui::PointerInput>(event.input);
    check(event.target==view.widgets[2].spec.key&&input.kind==gui::PointerKind::wheel&&input.position==gui::Point{30,30}&&input.wheel_x==0&&input.wheel_y==1&&adapter.scroll_offset(view.widgets[0].spec.key).y==0,"Native canvas wheel sign/position/ownership changed");
    adapter.close();adapter.sync();check(adapter.error().empty(),"Native canvas callback failed");
}
}
int main(){try{readonly(false);readonly(true);canvas();std::cout<<"Native readonly block wheels chain at bounds; canvas wheels retain positive-up raw input\n";}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
