#include "adapter.hpp"
#include "probe.hpp"
#include "host/contract.hpp"
#include "tests/fixture.hpp"
#include <iostream>
#include <cmath>

namespace {
void raw_pointer_contract() {
    using gui::rev::Probe;
    std::vector<gui::WidgetEvent> events;
    gui::rev::Adapter adapter([&](const gui::Event& event) {
        if(const auto* value=std::get_if<gui::WidgetEvent>(&event))events.push_back(*value);
    });
    gui::Snapshot view;view.client_size={320,220};
    gui::Widget surface;surface.spec.key={"fixture.surface",1};surface.spec.kind=gui::Kind::bitmap;
    surface.spec.pointer_input=true;surface.state.bounds={20,20,220,140};
    surface.state.bitmap={"fixture.surface",1,gui::solid_bitmap(240,240,240)};
    gui::Widget label;label.spec.key={"fixture.annotation",1};label.spec.kind=gui::Kind::label;
    label.state.bounds={40,40,120,24};label.state.text="Samples";
    view.widgets={surface,label};adapter.present(view);adapter.show();adapter.sync();adapter.pump();
    Probe::pointer_phase(adapter,gui::PointerKind::press,{60,50});
    view.widgets.back().state.bounds={140,80,120,24};adapter.present(view);adapter.sync();
    Probe::pointer_phase(adapter,gui::PointerKind::move,{280,200});
    Probe::pointer_phase(adapter,gui::PointerKind::release,{280,200});
    fixture::check(events.size()==3,"Rev raw gesture lost a phase or synthesized an extra click");
    const gui::PointerKind phases[]{gui::PointerKind::press,gui::PointerKind::move,gui::PointerKind::release};
    for(unsigned i=0;i<3;++i) {
        const auto* input=std::get_if<gui::PointerInput>(&events[i].input);
        fixture::check(events[i].target==surface.spec.key&&input&&input->kind==phases[i]&&input->pointer_id!=0,
            "Rev raw gesture changed target or pointer owner");
    }
    fixture::check(std::get<gui::PointerInput>(events.back().input).position==gui::Point{280,200},
        "Rev captured release coordinates were clipped");
    Probe::pointer_phase(adapter,gui::PointerKind::press,{60,50});Probe::key(adapter,"escape");
    fixture::check(events.size()==5&&std::get<gui::PointerInput>(events.back().input).kind==gui::PointerKind::cancel,
        "Escape did not cancel the Rev raw gesture");
    Probe::pointer_phase(adapter,gui::PointerKind::release,{60,50});
    fixture::check(events.size()==5,"Cancelled Rev gesture later released");
    Probe::pointer_phase(adapter,gui::PointerKind::press,{60,50});
    Probe::pointer_phase(adapter,gui::PointerKind::cancel,{60,50});
    fixture::check(events.size()==7&&std::get<gui::PointerInput>(events.back().input).kind==gui::PointerKind::cancel,
        "Window focus loss did not cancel the Rev raw gesture");
    Probe::pointer_phase(adapter,gui::PointerKind::press,{60,50});
    view.widgets[0].spec.key.generation=2;adapter.present(view);adapter.sync();
    const auto count=events.size();Probe::pointer_phase(adapter,gui::PointerKind::release,{60,50});
    fixture::check(events.size()==count,"Replaced Rev raw target inherited pointer ownership");
    Probe::wheel(adapter,{150,90},{0,1});
    fixture::check(events.size()==count+1&&events.back().target==view.widgets[0].spec.key&&
        std::get<gui::PointerInput>(events.back().input).kind==gui::PointerKind::wheel,
        "Inert Rev label swallowed the underlying surface wheel event");
    gui::Widget button;button.spec.key={"fixture.button",1};button.spec.kind=gui::Kind::button;
    button.state.bounds={40,40,100,32};button.state.label="Native";
    view.widgets.push_back(button);adapter.present(view);adapter.sync();adapter.pump();
    Probe::pointer_phase(adapter,gui::PointerKind::press,{60,50});
    fixture::check(events.size()==count+1,"Native Rev button leaked a raw surface press");
    Probe::pointer_phase(adapter,gui::PointerKind::release,{60,50});
    fixture::check(events.size()==count+2&&events.back().target==button.spec.key&&
        std::holds_alternative<gui::Activate>(events.back().input),"Rev raw routing replaced ordinary native button handling");
    adapter.close();adapter.sync();fixture::check(adapter.error().empty(),"Rev raw gesture callback failed");
}
}

int main(){try{
    raw_pointer_contract();
    foundation::host::Session<foundation::ui::Application,gui::rev::Adapter> session;
    auto& adapter=session.adapter;adapter.show();
    auto sync=[&]{session.tick();adapter.pump();session.tick();fixture::check(adapter.error().empty(),"Native callback failed");};sync();
    // Native scale belongs to the host. Verify physical storage and logical
    // widget rectangles before the shared unit-scale comparison scenarios.
    const auto native_scale=session.application.view().display_scale;
    fixture::check(std::isfinite(native_scale)&&native_scale>0,"Invalid native display scale");
    {
        const auto& view=session.application.view();
        const auto image=adapter.capture();
        fixture::check(image.width()==unsigned(std::ceil(view.client_size.width*native_scale))&&
            image.height()==unsigned(std::ceil(view.client_size.height*native_scale)),
            "Native physical capture differs from scaled logical viewport");
        for(const auto& widget:view.widgets) {
            if(!widget.state.visible)continue;
            const auto actual=gui::rev::Probe::bounds(adapter,widget.spec.key);
            const auto expected=widget.state.bounds;
            fixture::check(std::abs(actual.x-expected.x)<0.01&&std::abs(actual.y-expected.y)<0.01&&
                std::abs(actual.width-expected.width)<0.01&&std::abs(actual.height-expected.height)<0.01,
                "Native scale changed logical widget geometry");
        }
        std::cout<<"Rev native scale "<<native_scale<<" logical "<<view.client_size.width<<'x'
            <<view.client_size.height<<" physical "<<image.width()<<'x'<<image.height()<<'\n';
    }
    fixture::feature(session.application,
        [&](std::string text){gui::rev::Probe::edit_text(adapter,{"entries.editor",1},std::move(text));},
        [&](std::string id){gui::rev::Probe::activate(adapter,{std::move(id),1});},
        [&](std::string id){gui::rev::Probe::select_record(adapter,{"entries.list",1},std::move(id));},sync);
    fixture::parity(session.application.view());
    fixture::unavailable_service(adapter);
    fixture::visual_sizes(session.application,adapter,"rev",sync,[&](const std::string& name){
        const auto image=adapter.capture();fixture::check(image.width()>0&&image.height()>0,"Native capture failed");
        fixture::capture(image.pixels().data(),image.width(),image.height(),name.c_str());
    });
    gui::rev::Probe::select_option(adapter,{"entries.options",1},"heading");sync();
    fixture::check(adapter.service_active(),"Native service not started");
    gui::rev::Probe::complete_prompt(adapter,"New heading");sync();
    fixture::check(fixture::widget(session.application.view(),"entries.heading").state.text=="New heading","Prompt result lost");
    session.application.handle(gui::CloseEvent{});fixture::check(adapter.closed(),"Native close failed");
    std::cout<<"Rev native callbacks, shared extension, declarations, capture, services and close passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
