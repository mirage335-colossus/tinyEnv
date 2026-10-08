#include <gui/framebuffer.hpp>
#include <gui/terminal.hpp>
#include <array>
#include <iostream>
#include <stdexcept>
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
gui::Snapshot scene(){
    gui::Snapshot view;view.client_size={320,180};gui::Widget parent;parent.spec.key={"parent",1};parent.spec.kind=gui::Kind::group;
    parent.state.bounds={0,0,300,160};parent.state.content_size={300,800};
    gui::Widget text;text.spec.key={"text",1};text.spec.kind=gui::Kind::text;text.spec.parent="parent";text.spec.text_policy={true,true,8192,gui::SubmitKey::none};
    text.state.bounds={20,20,220,80};text.state.text="Selectable readonly prose";text.state.wrap=gui::TextWrap::none;view.widgets={parent,text};return view;
}
gui::Color pixel(const gui::Frame& frame,unsigned x,unsigned y){const auto at=std::size_t(y)*frame.stride_bytes+std::size_t(x)*3;return {(*frame.pixels)[at],(*frame.pixels)[at+1],(*frame.pixels)[at+2]};}
void declarations(){
    gui::WidgetState legacy;check(legacy.text_frame,"Existing widget state changed its default frame");auto view=scene();view.widgets[1].state.text_frame=false;
    gui::validate_snapshot(view);view.widgets[1].spec.text_policy.read_only=false;gui::validate_snapshot(view);
    view.widgets[1].spec.text_policy={false,false,8192,gui::SubmitKey::none,true};gui::validate_snapshot(view);
    for(const auto kind:{gui::Kind::group,gui::Kind::label,gui::Kind::button,gui::Kind::toggle,gui::Kind::choice,gui::Kind::list,gui::Kind::bitmap,gui::Kind::menu}){
        auto bad=scene();bad.widgets[1].spec.kind=kind;bad.widgets[1].state.text_frame=false;bool rejected=false;
        try{gui::validate_snapshot(bad);}catch(const std::invalid_argument&){rejected=true;}check(rejected,"Borderless appearance accepted on a nontext control");
    }
}
void software(){
    auto view=scene();const auto key=view.widgets[1].spec.key;gui::FramebufferAdapter adapter;adapter.present(view);
    check(pixel(adapter.frame(),20,20)==view.palette.border,"Default software text frame changed");
    check(adapter.focus(key),"Readonly text cannot focus");adapter.text_selection(key,{2,12});const auto framed=adapter.frame();
    check(pixel(framed,20,20)==view.palette.accent,"Default focused software text frame changed");
    const auto text_bounds=adapter.text_bounds(view.widgets[1]);view.widgets[1].state.text_frame=false;adapter.present(view);const auto plain=adapter.frame();
    check(pixel(plain,20,20)==view.palette.surface,"Borderless software text retained a focused outline");
    for(unsigned y=21;y<99;++y)for(unsigned x=21;x<239;++x)check(pixel(framed,x,y)==pixel(plain,x,y),"Text-frame toggle changed internal selection/content geometry");
    check(adapter.focused()==key&&adapter.text_selection(key)==gui::TextSelection{2,12}&&adapter.text_bounds(adapter.snapshot().widgets[1])==text_bounds,"Mutable text appearance lost focus, selection or padding");
    adapter.pointer({gui::PointerKind::wheel,{30,30},0,-1});check(adapter.scroll_offset(view.widgets[0].spec.key).y==32,"Borderless fitting text swallowed parent wheel");
    check(adapter.snapshot().widgets[1].state.text==view.widgets[1].state.text,"Borderless readonly wheel changed source text");
    view.widgets[1].state.text_frame=true;adapter.present(view);check(pixel(adapter.frame(),20,20)==view.palette.accent,"Restoring default frame lost focused outline");
    check(adapter.scroll_offset(view.widgets[0].spec.key).y==32&&adapter.focused()==key&&adapter.text_selection(key)==gui::TextSelection{2,12},"Restoring frame reset retained scroll, focus or selection");
    for(bool multiline:{false,true})for(bool readonly:{false,true}){
        auto variant=scene();variant.widgets[1].spec.text_policy.multiline=multiline;variant.widgets[1].spec.text_policy.read_only=readonly;variant.widgets[1].state.text_frame=false;
        gui::FramebufferAdapter fresh;fresh.present(variant);fresh.focus(variant.widgets[1].spec.key);
        check(pixel(fresh.frame(),20,20)==variant.palette.surface,"A text policy variant retained a focused software frame");
    }
    auto masked=scene();masked.widgets[1].spec.text_policy={false,false,8192,gui::SubmitKey::none,true};masked.widgets[1].state.text_frame=false;
    gui::FramebufferAdapter secret;secret.present(masked);secret.focus(masked.widgets[1].spec.key);
    check(pixel(secret.frame(),20,20)==masked.palette.surface,"Masked software text retained a focused frame");
}
void terminal(){
    auto view=scene();gui::TerminalAdapter adapter;adapter.present(view);adapter.focus(view.widgets[1].spec.key);adapter.text_selection(view.widgets[1].spec.key,{2,12});
    const auto rendered=adapter.render(),styled=adapter.ansi_rows();view.widgets[1].state.text_frame=false;adapter.present(view);
    check(adapter.render()==rendered&&adapter.ansi_rows()==styled,"Frame-free terminal text lost its existing selection/focus appearance");
}
}
int main(){try{declarations();software();terminal();std::cout<<"Text frames default on; opt-out removes only outlines and retains selection, focus, geometry and wheel chaining\n";}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
