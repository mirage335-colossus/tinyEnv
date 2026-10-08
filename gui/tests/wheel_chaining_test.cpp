#include <gui/framebuffer.hpp>
#include <gui/terminal.hpp>
#include <iostream>
#include <stdexcept>
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
gui::Snapshot scene(gui::Kind kind,bool overflow){
    gui::Snapshot view;view.client_size={500,300};gui::Widget outer;outer.spec.key={"outer",1};outer.spec.kind=gui::Kind::group;outer.state.bounds={0,0,300,180};outer.state.content_size={300,900};
    gui::Widget inner;inner.spec.key={"inner",1};inner.spec.kind=gui::Kind::group;inner.spec.parent="outer";inner.state.bounds={0,0,300,160};inner.state.content_size={300,160};
    gui::Widget child;child.spec.key={"child",1};child.spec.kind=kind;child.spec.parent="inner";child.state.bounds={10,10,280,80};
    if(kind==gui::Kind::text){child.spec.text_policy={true,true,10000,gui::SubmitKey::none};child.state.wrap=gui::TextWrap::none;
        child.state.text=overflow?std::string("One\nTwo\nThree\nFour\nFive\nSix\nSeven\nEight\nNine\nTen\n"):"A fitting readonly text block";}
    if(kind==gui::Kind::list)for(int i=0;i<(overflow?20:1);++i)child.state.records.push_back({std::to_string(i),"Row",{},true,false});
    view.widgets={outer,inner,child};return view;
}
template<class Adapter> void chaining(Adapter& adapter,gui::Kind kind,bool overflow){
    const auto view=scene(kind,overflow);adapter.present(view);if(kind==gui::Kind::text){adapter.focus(view.widgets[2].spec.key);adapter.text_selection(view.widgets[2].spec.key,{0,0});}
    adapter.pointer({gui::PointerKind::wheel,{30,30},0,-1});
    if(overflow){check(adapter.scroll_offset(view.widgets[2].spec.key).y>0&&adapter.scroll_offset(view.widgets[0].spec.key).y==0,"Overflowing child did not retain wheel ownership");
        adapter.scroll(view.widgets[2].spec.key,{0,1e6});adapter.pointer({gui::PointerKind::wheel,{30,30},0,-1});}
    check(adapter.scroll_offset(view.widgets[0].spec.key).y==32&&adapter.scroll_offset(view.widgets[1].spec.key).y==0,"Clamped child/inner group swallowed ancestor wheel");
    if(kind==gui::Kind::text)check(adapter.text_selection(view.widgets[2].spec.key)==gui::TextSelection{0,0}&&adapter.snapshot().widgets[2].state.text==view.widgets[2].state.text,"Readonly block wheel changed text or caret");
}
void raw_canvas(){
    std::vector<gui::Event> events;gui::FramebufferAdapter adapter([&](const gui::Event& event){events.push_back(event);});auto view=scene(gui::Kind::bitmap,false);
    view.widgets[2].spec.pointer_input=true;view.widgets[2].state.bitmap={"canvas",1,gui::solid_bitmap(20,30,40)};adapter.present(view);
    adapter.pointer({gui::PointerKind::wheel,{30,30},.5,1});check(events.size()==1,"Raw canvas wheel was lost/duplicated");
    const auto& item=std::get<gui::WidgetEvent>(events.back());const auto& input=std::get<gui::PointerInput>(item.input);
    check(item.target==view.widgets[2].spec.key&&input.kind==gui::PointerKind::wheel&&input.wheel_x==.5&&input.wheel_y==1&&input.position==gui::Point{30,30}&&adapter.scroll_offset(view.widgets[0].spec.key).y==0,"Canvas wheel sign/position/ownership changed");
}
}
int main(){try{for(const auto kind:{gui::Kind::text,gui::Kind::list})for(bool overflow:{false,true}){
    gui::FramebufferAdapter pixels;chaining(pixels,kind,overflow);gui::TerminalAdapter terminal;chaining(terminal,kind,overflow);
}raw_canvas();std::cout<<"Shared fitting/clamped text/list wheels reach scrollable ancestors while overflow and raw canvases retain ownership\n";}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
