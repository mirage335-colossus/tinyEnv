#include "adapter.hpp"
#include "probe.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void check(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
gui::Color pixel(const gui::BitmapImage& image,unsigned x,unsigned y) {
    check(image.format()==gui::PixelFormat::rgb24&&x<image.width()&&y<image.height(),"Invalid Rev capture pixel");
    const auto at=(std::size_t(y)*image.width()+x)*3;
    return {image.pixels()[at],image.pixels()[at+1],image.pixels()[at+2]};
}
unsigned distance(gui::Color a,gui::Color b) {
    return unsigned(std::abs(int(a.red)-int(b.red))+std::abs(int(a.green)-int(b.green))+std::abs(int(a.blue)-int(b.blue)));
}
gui::DeviceRect pixels(const gui::BitmapImage& image,gui::Size client,gui::Rect bounds) {
    const double scale=double(image.width())/client.width;
    check(scale>0&&std::abs(double(image.height())-std::ceil(client.height*scale))<=1,
        "Rev capture scale does not match the logical viewport");
    const auto result=gui::device_rect(bounds,scale);
    check(result.x>=0&&result.y>=0,"Text-frame fixture lies outside the native capture");return result;
}
std::size_t decoration(const gui::BitmapImage& image,const gui::Snapshot& view,gui::Rect bounds,gui::Color wanted,gui::Color fill) {
    const auto box=pixels(image,view.client_size,bounds);
    const auto band=std::max(1u,unsigned(std::ceil(2.0*image.width()/view.client_size.width)));
    check(box.width>band*4&&box.height>band*4,"Text-frame fixture has no straight native edge");
    std::size_t found=0;
    for(unsigned y=box.y;y<box.y+box.height;++y)for(unsigned x=box.x;x<box.x+box.width;++x) {
        // Top and bottom straight edges cannot contain horizontally clipped glyphs.
        const bool edge=(y<box.y+band||y>=box.y+box.height-band)&&
            x>=box.x+band&&x<box.x+box.width-band;
        if(!edge)continue;
        const auto value=pixel(image,x,y);
        if(distance(value,wanted)<std::min(distance(value,fill),distance(value,view.palette.background)))++found;
    }
    return found;
}
void no_frame(const gui::BitmapImage& image,const gui::Snapshot& view,const gui::Widget& widget,gui::Color fill) {
    check(decoration(image,view,widget.state.bounds,view.palette.border,fill)==0,
        "An unframed Rev editor retained its decorative border");
    check(decoration(image,view,widget.state.bounds,view.palette.accent,fill)==0,
        "An unframed Rev editor retained its focused border");
}
void same_interior(const gui::BitmapImage& framed,const gui::BitmapImage& unframed,const gui::Snapshot& view,gui::Rect bounds) {
    check(framed.width()==unframed.width()&&framed.height()==unframed.height(),"Text framing changed native window size");
    bounds.x+=3;bounds.y+=3;bounds.width-=6;bounds.height-=6;
    const auto box=pixels(framed,view.client_size,bounds);
    for(unsigned y=box.y;y<box.y+box.height;++y)for(unsigned x=box.x;x<box.x+box.width;++x)
        check(pixel(framed,x,y)==pixel(unframed,x,y),"Text framing changed native padding, glyphs or editor interior");
}
void native_text_frames() {
    const gui::WidgetKey editor_key{"editor",1},masked_key{"masked",1};
    gui::Snapshot view;view.client_size={340,220};view.title="Text frame fixture";
    view.palette.border={227,25,65};view.palette.accent={23,197,81};
    view.palette.surface={246,247,248};view.palette.background=view.palette.surface;
    view.palette.disabled={201,210,219};
    gui::Widget editor;editor.spec.key=editor_key;editor.spec.kind=gui::Kind::text;
    editor.state.bounds={20,20,280,40};editor.state.text="A\xc3\xa9\xf0\x9f\x98\x80Z"+std::string(80,'W');
    gui::Widget masked;masked.spec.key=masked_key;masked.spec.kind=gui::Kind::text;masked.spec.text_policy.masked=true;
    masked.state.bounds={20,84,280,40};masked.state.text="Synthetic secret";
    gui::Widget button;button.spec.key={"button",1};button.spec.kind=gui::Kind::button;
    button.state.bounds={20,148,180,32};button.state.label="Ordinary action";
    view.widgets={editor,masked,button};
    unsigned edits=0;gui::rev::Adapter* bound=nullptr;
    gui::rev::Adapter adapter([&](const gui::Event& event) {
        check(bound!=nullptr,"Rev dispatched before its fixture adapter was bound");
        if(const auto* input=std::get_if<gui::WidgetEvent>(&event))if(const auto* value=std::get_if<gui::EditText>(&input->input)) {
            check(input->target==editor_key,"Text framing changed the native edit identity");
            ++edits;view.widgets.front().state.text=value->value;++view.revision;bound->present(view);
        }
    });bound=&adapter;adapter.present(view);adapter.sync();
    auto image=adapter.capture();
    check(decoration(image,view,editor.state.bounds,view.palette.border,view.palette.surface)>5,
        "Default Rev text lost its ordinary frame");
    check(decoration(image,view,masked.state.bounds,view.palette.border,view.palette.disabled)>5,
        "Default masked Rev fallback lost its ordinary frame");
    check(decoration(image,view,button.state.bounds,view.palette.border,view.palette.surface)>5,
        "Text framing changed an ordinary nontext control");
    check(adapter.focus(editor_key),"Default Rev text could not receive focus");adapter.sync();
    image=adapter.capture();
    check(decoration(image,view,editor.state.bounds,view.palette.accent,view.palette.surface)>5,
        "Default focused Rev text lost its focus frame");
    const gui::TextSelection selection{1,7},secret_selection{1,4};
    adapter.text_selection(editor_key,selection);adapter.text_selection(masked_key,secret_selection);
    adapter.scroll(editor_key,{80,0});adapter.focus(std::nullopt);adapter.sync();
    const auto offset=adapter.scroll_offset(editor_key);const auto bounds=gui::rev::Probe::bounds(adapter,editor_key);
    check(offset.x>0&&gui::rev::Probe::selection(adapter,editor_key)==selection,
        "Native byte selection and horizontal scrolling were not established");
    const auto framed=adapter.capture();
    view.widgets[0].state.text_frame=false;view.widgets[1].state.text_frame=false;adapter.present(view);adapter.sync();
    const auto unframed=adapter.capture();no_frame(unframed,view,view.widgets[0],view.palette.surface);
    no_frame(unframed,view,view.widgets[1],view.palette.disabled);
    same_interior(framed,unframed,view,editor.state.bounds);same_interior(framed,unframed,view,masked.state.bounds);
    check(gui::rev::Probe::bounds(adapter,editor_key)==bounds&&adapter.scroll_offset(editor_key)==offset&&
        adapter.text_selection(editor_key)==selection&&gui::rev::Probe::selection(adapter,editor_key)==selection&&
        adapter.text_selection(masked_key)==secret_selection&&gui::rev::Probe::text(adapter,editor_key)==editor.state.text&&
        !gui::rev::Probe::enabled(adapter,masked_key)&&gui::rev::Probe::text(adapter,masked_key)=="Masked input unavailable",
        "Text framing changed native editor geometry, selection, scroll or masking");
    check(adapter.focus(editor_key),"Unframed native text lost keyboard focus");adapter.sync();
    no_frame(adapter.capture(),view,view.widgets[0],view.palette.surface);
    view.widgets[0].state.text_frame=true;view.widgets[1].state.text_frame=true;adapter.present(view);adapter.sync();
    image=adapter.capture();
    check(decoration(image,view,editor.state.bounds,view.palette.accent,view.palette.surface)>5&&
        decoration(image,view,masked.state.bounds,view.palette.border,view.palette.disabled)>5,
        "Re-enabling text frames did not restore focused and masked defaults");
    view.widgets[0].state.text_frame=false;view.widgets[1].state.text_frame=false;adapter.present(view);adapter.sync();
    no_frame(adapter.capture(),view,view.widgets[0],view.palette.surface);
    gui::rev::Probe::edit_text(adapter,editor_key,"A\xc3\xa9Z",{1,3});adapter.sync();
    check(edits==1&&view.widgets[0].state.text=="A\xc3\xa9Z"&&
        adapter.text_selection(editor_key)==gui::TextSelection{1,3}&&gui::rev::Probe::selection(adapter,editor_key)==gui::TextSelection{1,3},
        "Unframed native text changed edit delivery or UTF-8 byte selection");
    view.widgets[0].state.enabled=false;adapter.present(view);adapter.sync();
    no_frame(adapter.capture(),view,view.widgets[0],view.palette.disabled);
    view.widgets[0].state.enabled=true;view.widgets[0].spec.key.generation=2;view.widgets[0].spec.text_policy.read_only=true;
    adapter.present(view);check(adapter.focus(view.widgets[0].spec.key),"Read-only unframed text lost focus");adapter.sync();
    no_frame(adapter.capture(),view,view.widgets[0],view.palette.surface);
    check(adapter.error().empty()&&!adapter.closed(),"Text-frame fixture encountered a native callback failure");
    adapter.close();adapter.sync();
}
}
int main() {
    try {native_text_frames();std::cout<<"Rev text frames preserve defaults, native geometry and editing while hiding ordinary/focused/masked decoration\n";}
    catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
