#include <gui/framebuffer.hpp>
#include <gui/web.hpp>
#include "host/framebuffer_touch.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
struct Fixture {
    gui::Snapshot view;
    std::vector<gui::Event> events;
    gui::FramebufferAdapter adapter{[this](const gui::Event& event){events.push_back(event);}};
    Fixture() {
        view.client_size={200,100};
        gui::Widget button;button.spec.key={"button",1};button.spec.kind=gui::Kind::button;button.state.bounds={0,0,60,40};
        gui::Widget raw;raw.spec.key={"raw",1};raw.spec.pointer_input=true;raw.state.bounds={80,0,60,40};
        view.widgets={button,raw};adapter.present(view);
    }
    void pointer(gui::PointerKind phase,gui::Point at={20,20},std::uint64_t id=9) {
        adapter.pointer({phase,at,0,0,false,false,false,id});
    }
};
void semantic_release() {
    Fixture f;f.pointer(gui::PointerKind::press);check(f.events.empty(),"Press activated button");
    f.pointer(gui::PointerKind::release,{20,20},10);check(f.events.empty(),"Foreign release activated button");
    f.pointer(gui::PointerKind::move,{199,99});f.pointer(gui::PointerKind::release);
    check(f.events.size()==1&&std::holds_alternative<gui::Activate>(std::get<gui::WidgetEvent>(f.events.back()).input),"Captured return did not activate once");
    f.pointer(gui::PointerKind::release);check(f.events.size()==1,"Duplicate release activated");
    f.pointer(gui::PointerKind::press);f.pointer(gui::PointerKind::cancel);f.pointer(gui::PointerKind::release);check(f.events.size()==1,"Cancel activated");
    f.pointer(gui::PointerKind::press);f.pointer(gui::PointerKind::release,{190,90});check(f.events.size()==1,"Outside release activated");
    f.pointer(gui::PointerKind::press);f.view.widgets[0].spec.key.generation=2;f.adapter.present(f.view);f.pointer(gui::PointerKind::release);check(f.events.size()==1,"Replaced generation inherited capture");
    f.pointer(gui::PointerKind::press);f.view.widgets[0].state.enabled=false;f.adapter.present(f.view);
    f.view.widgets[0].state.enabled=true;f.adapter.present(f.view);f.pointer(gui::PointerKind::release);check(f.events.size()==1,"Reenabled target inherited invalidated capture");
}
void raw_capture() {
    Fixture f;f.pointer(gui::PointerKind::press,{90,20});f.pointer(gui::PointerKind::press,{95,20},10);
    f.pointer(gui::PointerKind::move,{-50,-20});f.pointer(gui::PointerKind::release,{250,120});
    check(f.events.size()==3,"Raw capture lost outside motion/release or accepted extra finger");
    check(std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(f.events[1]).input).position==gui::Point{-50,-20},"Captured coordinates were clamped");
    f.pointer(gui::PointerKind::release,{90,20});check(f.events.size()==3,"Raw stale release delivered");
    f.pointer(gui::PointerKind::press,{90,20});f.pointer(gui::PointerKind::cancel,{-20,100});
    check(std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(f.events.back()).input).kind==gui::PointerKind::cancel,"Raw cancel became release");
    auto forged=gui::PointerInput{gui::PointerKind::release,{-10,-10},0,0,false,false,false,55};
    check(f.adapter.policy().send(gui::WidgetEvent{{"raw",1},forged})==gui::Delivery::ignored,"Direct policy bypass accepted unowned release");
    f.pointer(gui::PointerKind::press,{90,20});f.view.widgets[1].spec.key.generation=2;f.adapter.present(f.view);
    const auto n=f.events.size();f.pointer(gui::PointerKind::release,{90,20});check(f.events.size()==n,"Raw replaced target inherited capture");
    f.pointer(gui::PointerKind::press,{90,20});check(f.events.size()==n+1,"Stale capture blocked fresh generation");
}
void raw_double_click() {
    Fixture f;f.pointer(gui::PointerKind::press,{90,20});
    f.adapter.pointer({gui::PointerKind::release,{90,20},0,0,false,false,false,9,2});
    check(f.events.size()==3,"Physical raw double-click semantic lost");
    check(std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(f.events.back()).input).kind==gui::PointerKind::double_click,"Raw double-click not preserved");
    f.pointer(gui::PointerKind::press,{90,20});f.adapter.pointer({gui::PointerKind::cancel,{90,20},0,0,false,false,false,9,2});
    check(f.events.size()==5&&std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(f.events.back()).input).kind==gui::PointerKind::cancel,"Cancel synthesized raw double-click");
}
void transparent_raw_labels() {
    Fixture f;gui::Widget label;label.spec.key={"annotation",1};label.spec.kind=gui::Kind::label;
    label.state.bounds={85,5,45,25};label.state.text="Sample";
    f.view.widgets.push_back(label);f.adapter.present(f.view);
    f.adapter.pointer({gui::PointerKind::wheel,{90,20},0,1});
    f.adapter.pointer({gui::PointerKind::move,{90,20}});
    check(f.events.size()==2,"Inert text swallowed raw surface wheel or hover");
    for(const auto& event:f.events)check(std::get<gui::WidgetEvent>(event).target.id=="raw","Inert text changed raw target");
    f.pointer(gui::PointerKind::press,{90,20});
    f.view.widgets.back().state.bounds={140,60,45,25};f.adapter.present(f.view);
    f.pointer(gui::PointerKind::move,{170,80});f.pointer(gui::PointerKind::release,{170,80});
    check(f.events.size()==5,"Moving inert text revoked the surface capture");
}
void changing_targets_and_prompt() {
    Fixture f;gui::Widget list;list.spec.key={"rows",1};list.spec.kind=gui::Kind::list;list.spec.row_height=20;list.state.bounds={0,50,100,40};
    list.state.records={{"old","Old",{},true,true},{"next","Next",{},true,true}};f.view.widgets.push_back(list);f.adapter.present(f.view);
    f.pointer(gui::PointerKind::press,{10,60});f.view.widgets.back().state.records.erase(f.view.widgets.back().state.records.begin());f.adapter.present(f.view);
    f.pointer(gui::PointerKind::release,{10,60});check(f.events.empty(),"Replaced list row inherited pressed coordinates");
    unsigned completed=0;f.pointer(gui::PointerKind::press);
    check(f.adapter.service({7,gui::ServiceKind::prompt,"Question",""},[&](gui::ServiceResult result){if(result.status==gui::ServiceStatus::success)++completed;}),"Prompt failed to open");
    const auto bounds=f.adapter.prompt_accept_bounds();const gui::Point accept{bounds.x+bounds.width/2,bounds.y+bounds.height/2};
    f.pointer(gui::PointerKind::release,accept);check(completed==0,"Prompt inherited earlier capture");
    f.pointer(gui::PointerKind::press,accept);f.pointer(gui::PointerKind::cancel,accept);f.pointer(gui::PointerKind::release,accept);
    check(completed==0&&f.adapter.prompt().has_value(),"Cancelled touch accepted prompt");
    f.pointer(gui::PointerKind::press,accept);f.pointer(gui::PointerKind::release,accept);check(completed==1,"Prompt release did not use shared semantic path");
}
void web_capture() {
    Fixture f;std::vector<gui::Event> events;gui::WebAdapter adapter([&](const gui::Event& event){events.push_back(event);});adapter.present(f.view);
    gui::WebSession session(adapter,"touch");std::uint64_t sequence=0;
    auto send=[&](const char* kind,std::uint64_t owner,double x) {
        using J=gui::web_detail::Json;
        const auto op=J::Object{{"type","pointer"},{"key",J::Object{{"id","raw"},{"generation","1"}}},
            {"kind",kind},{"pointerId",std::to_string(owner)},{"x",x},{"y",20},{"wheelX",0},{"wheelY",0},
            {"control",false},{"shift",false},{"alt",false}};
        const auto reply=session.receive(gui::web_detail::encode(J::Object{{"epoch","touch"},{"seq",std::to_string(++sequence)},{"operation",op}}));
        check(gui::web_detail::Parser(reply).parse().at("error").str().empty(),"Web pointer schema rejected a phase");
    };
    send("press",4,90);send("release",5,90);send("move",4,-10);send("cancel",4,220);send("release",4,90);
    check(events.size()==3,"Web pointer owner gate differs from framebuffer path");
    check(std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(events.back()).input).kind==gui::PointerKind::cancel,"Web cancellation became activation");
}
void popup_revokes_capture() {
    Fixture f;auto& choice=f.view.widgets[1];choice.spec.kind=gui::Kind::choice;choice.spec.key.generation=2;
    choice.state.options={{"one","One","",true},{"two","Two","",true}};f.adapter.present(f.view);const auto key=choice.spec.key;
    f.pointer(gui::PointerKind::press,{90,20});check(f.adapter.open_popup(key),"Raw software popup did not open");
    f.pointer(gui::PointerKind::release,{90,20});check(f.events.size()==1,"Software popup kept raw capture");
    f.adapter.close_popup(key);f.pointer(gui::PointerKind::press,{90,20});f.pointer(gui::PointerKind::release,{90,20});
    check(f.events.size()==3,"Popup revocation blocked fresh software gesture");
    std::vector<gui::Event> events;gui::WebAdapter web([&](const gui::Event& event){events.push_back(event);});web.present(f.view);
    auto send=[&](gui::PointerKind kind,std::uint64_t id){return web.policy().send(gui::WidgetEvent{key,gui::PointerInput{kind,{90,20},0,0,false,false,false,id}});};
    check(send(gui::PointerKind::press,4)==gui::Delivery::delivered,"Web raw press rejected");check(web.open_popup(key),"Web popup did not open");
    check(send(gui::PointerKind::release,4)==gui::Delivery::ignored&&events.size()==1,"Retained popup kept raw Web capture");
    web.close_popup(key);check(send(gui::PointerKind::press,5)==gui::Delivery::delivered&&send(gui::PointerKind::release,5)==gui::Delivery::delivered,"Web popup revocation blocked fresh owner");
}
void web_modal_and_resize() {
    Fixture f;std::vector<gui::Event> events;bool pending=false;
    gui::WebAdapter adapter([&](const gui::Event& event){events.push_back(event);});adapter.present(f.view);
    gui::WebSession session(adapter,"modal",[&]()->std::optional<gui::ServiceRequest>{
        if(!pending)return std::nullopt;
        pending=false;return gui::ServiceRequest{42,gui::ServiceKind::prompt,"Question",""};
    },[](gui::ServiceResult){return true;});
    using J=gui::web_detail::Json;std::uint64_t sequence=0;
    auto call=[&](J::Object op) {
        const auto reply=session.receive(gui::web_detail::encode(J::Object{{"epoch","modal"},{"seq",std::to_string(++sequence)},{"operation",std::move(op)}}));
        check(gui::web_detail::Parser(reply).parse().at("error").str().empty(),"Modal/resize wire operation failed");
    };
    auto pointer=[&](const char* kind,std::uint64_t owner) {call(J::Object{{"type","pointer"},{"key",J::Object{{"id","raw"},{"generation","1"}}},
        {"kind",kind},{"pointerId",std::to_string(owner)},{"x",90},{"y",20},{"wheelX",0},{"wheelY",0},{"control",false},{"shift",false},{"alt",false}});};
    pointer("press",4);pending=true;call({{"type","poll"}});
    pointer("cancel",4);pointer("press",8);check(events.size()==1,"Modal service delivered background pointer");
    call({{"type","service"},{"id","42"},{"status","cancelled"},{"value",""},{"error",""}});
    pointer("release",4);check(events.size()==1,"Pre-modal capture survived service completion");
    pointer("press",9);pointer("release",9);check(events.size()==3,"Modal capture revocation blocked fresh gesture");
    pointer("press",10);call({{"type","resize"},{"width",200},{"height",100},{"scale",1}});const auto before=events.size();
    pointer("release",10);check(events.size()==before,"Explicit same-size resize kept old capture");
    pointer("press",11);check(events.size()==before+1,"Resize cancellation blocked next pointer");
}
void driver_ownership() {
    Fixture f;foundation::host::FramebufferTouch driver;
    using C=foundation::host::Contact;using P=foundation::host::ContactPhase;
    const C first{C::Source::touch,1,3},second{C::Source::touch,1,4},mouse{C::Source::mouse,0,0};
    check(driver.input(f.adapter,first,P::press,{20,20}),"First contact rejected");
    check(!driver.input(f.adapter,second,P::press,{20,20}),"Second finger accepted");
    check(!driver.input(f.adapter,mouse,P::press,{20,20}),"Synthetic mouse duplicate accepted");
    check(!driver.input(f.adapter,second,P::release,{20,20}),"Foreign release accepted");
    driver.cancel(f.adapter);check(f.events.empty(),"Driver focus cancellation activated");
    check(driver.input(f.adapter,mouse,P::press,{20,20}),"Fresh mouse press rejected");
    driver.input(f.adapter,mouse,P::release,{20,20});check(f.events.size()==1,"Driver release missed semantic path");
    const auto retained=f.adapter.frame();f.adapter.close();check(!driver.input(f.adapter,first,P::press,{20,20}),"Closed adapter accepted contact");
    check(retained.pixels&&retained.pixels->size()==retained.stride_bytes*retained.height,"Retained frame invalidated by close");
}
}
int main() {try{semantic_release();raw_capture();raw_double_click();transparent_raw_labels();changing_targets_and_prompt();web_capture();popup_revokes_capture();web_modal_and_resize();driver_ownership();std::cout<<"Touch ownership and capture passed\n";return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
