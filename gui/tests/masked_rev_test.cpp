#include "adapter.hpp"
#include "probe.hpp"
#include <gui/presentation.hpp>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

namespace {
void check(bool value,const char* message) {
    if(!value)throw std::runtime_error(message);
}
gui::Widget editor(gui::WidgetKey key,std::string value,bool masked=false) {
    gui::Widget result;result.spec.key=std::move(key);result.spec.kind=gui::Kind::text;
    result.spec.text_policy.masked=masked;result.state.text=std::move(value);
    result.state.bounds={20,20,240,32};return result;
}
void masked_control_is_unavailable() {
    std::vector<gui::WidgetEvent> events;
    gui::rev::Adapter adapter([&](const gui::Event& event) {
        if(const auto* input=std::get_if<gui::WidgetEvent>(&event))events.push_back(*input);
    });
    const gui::WidgetKey plain{"ordinary",1},masked{"masked",1},button_key{"button",1},surface_key{"surface",1};
    gui::Snapshot view;view.revision=11;view.title="Generic fixture";view.client_size={320,220};
    view.pages={{"active","Active"},{"other","Other"}};view.active_page="active";
    auto ordinary=editor(plain,"Ordinary text");ordinary.spec.page="active";
    gui::Widget surface;surface.spec.key=surface_key;surface.spec.kind=gui::Kind::group;
    surface.spec.pointer_input=true;surface.spec.page="active";surface.state.bounds={20,60,240,32};
    auto secret=editor(masked,"A\xc3\xa9\xf0\x9f\x98\x80Z",true);secret.spec.page="active";
    secret.spec.pointer_input=true;secret.spec.context_input=true;secret.state.bounds=surface.state.bounds;
    secret.state.placeholder="Synthetic private placeholder";secret.state.display_text="Synthetic private display";
    gui::Widget button;button.spec.key=button_key;button.spec.kind=gui::Kind::button;
    button.spec.page="active";button.state.bounds={20,110,120,32};button.state.label="Ordinary action";
    view.key_bindings={{gui::ShortcutKey::enter,button_key,false,false,false,masked}};
    view.widgets={ordinary,surface,secret,button};adapter.present(view);adapter.sync();
    check(!adapter.closed()&&adapter.error().empty(),"Masked text prevented ordinary Rev startup");
    check(adapter.snapshot().widgets[2].state.text==secret.state.text,
        "Unavailable native masking changed the authoritative clear value");
    check(gui::rev::Probe::exists(adapter,masked)&&!gui::rev::Probe::enabled(adapter,masked)&&
        gui::rev::Probe::text(adapter,masked)=="Masked input unavailable",
        "Rev did not use a disabled fixed placeholder for masked text");
    const gui::TextSelection selection{1,7};adapter.text_selection(masked,selection);
    check(adapter.text_selection(masked)==selection,"Unavailable native masking changed UTF-8 byte selection");
    adapter.scroll(masked,{20,0});adapter.sync();
    check(gui::rev::Probe::text(adapter,masked)=="Masked input unavailable",
        "Masked scrolling replaced the safe native placeholder");
    check(adapter.focus(plain)&&!adapter.focus(masked)&&adapter.focused()==plain,
        "Unavailable native mask stole ordinary editor focus");
    adapter.focus(std::nullopt);
    check(adapter.focus_next()&&adapter.focused()==plain,"Ordinary native tab focus was lost");
    check(adapter.focus_next()&&adapter.focused()==button_key,"Native tab focus entered unavailable masking");
    check(adapter.focus_next()&&adapter.focused()==plain,"Ordinary native tab wrap was lost");
    check(adapter.focus_next(true)&&adapter.focused()==button_key,"Reverse tab entered unavailable masking");
    gui::rev::Probe::pointer(adapter,{40,70});
    gui::rev::Probe::pointer(adapter,{40,70},3);
    gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::press,{40,70});
    gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::release,{40,70});
    check(events.empty(),"Unavailable masking emitted input or exposed a covered raw surface");
    check(!adapter.open_popup(masked),"Unavailable masking opened a native suggestion/context popup");
    // Even retained focus set through the shared qualification seam cannot
    // create native secret editing, selection, copy/cut or paste behavior.
    check(adapter.policy().focus(masked),"Shared masked focus could not be established for the negative control");
    adapter.sync();
    for(const auto* key:{"c","x","v","backspace","enter","right"})
        gui::rev::Probe::key(adapter,key,key[0]=='c'||key[0]=='x'||key[0]=='v');
    gui::rev::Probe::edit_text(adapter,masked,"Rejected native replacement",{0,8});
    check(events.empty()&&adapter.snapshot().widgets[2].state.text==secret.state.text&&
        adapter.text_selection(masked)==selection&&gui::rev::Probe::text(adapter,masked)=="Masked input unavailable",
        "Unavailable masking exposed native editing or changed authoritative text/selection");
    check(adapter.focus(plain),"Unavailable masking blocked a later ordinary focus request");
    gui::rev::Probe::activate(adapter,button_key);
    check(events.size()==1&&events.back().target==button_key&&std::holds_alternative<gui::Activate>(events.back().input),
        "Unavailable masking disabled an ordinary native action");
    // Masking can cover an already pressed ordinary native control. Its
    // release must cancel that native press without activating the control.
    gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::press,{40,120});
    auto covered=view;auto overlay=secret;overlay.spec.key={"overlay-mask",1};overlay.state.bounds=button.state.bounds;
    covered.widgets.push_back(overlay);adapter.present(covered);adapter.sync();
    gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::release,{40,120});
    check(events.size()==1,"Masked overlay released a previously pressed native button");
    adapter.present(view);adapter.sync();gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::release,{40,120});
    check(events.size()==1,"Masked overlay left a stale native press after removal");
    gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::press,{40,120});
    gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::release,{40,120});
    check(events.size()==2&&events.back().target==button_key,
        "Masked cancellation prevented a later ordinary native button click");
    for(unsigned mode=0;mode<6;++mode) {
        auto next=view;next.revision=12+mode;
        auto& field=next.widgets[2];field.state.text=mode==0?"":"Updated synthetic secret";
        if(mode==1)field.state.visible=false;
        if(mode==2)field.state.enabled=false;
        if(mode==3)field.state.bounds={1000,1000,240,32};
        if(mode==4)field.spec.page="other",field.spec.key.generation=2;
        if(mode==5)field.spec.text_policy.read_only=true,field.spec.key.generation=2;
        // Restore a removed generation using a fresh identity, as required by
        // the shared contract; state-only updates preserve the current one.
        if(mode==5)field.spec.key.generation=3;
        next.key_bindings.front().focus=field.spec.key;
        adapter.present(next);adapter.sync();
        check(!adapter.closed()&&adapter.error().empty()&&adapter.snapshot().widgets[2].state.text==field.state.text&&
            gui::rev::Probe::exists(adapter,field.spec.key)&&!gui::rev::Probe::enabled(adapter,field.spec.key)&&
            gui::rev::Probe::text(adapter,field.spec.key)=="Masked input unavailable",
            "Masked availability/value changes leaked text or damaged ordinary Rev presentation");
        if(mode==0||mode==2||mode==5) {
            gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::press,{40,70});
            gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::release,{40,70});
            gui::rev::Probe::pointer(adapter,{40,70},3);gui::rev::Probe::wheel(adapter,{40,70},{0,1});
            check(events.size()==2,"Empty, disabled or read-only masking exposed covered input");
        }
        if(mode==5)view=std::move(next);
    }
    gui::Snapshot only_mask=view;only_mask.widgets={view.widgets[2]};only_mask.key_bindings.clear();
    only_mask.widgets.front().state.bounds={0,0,320,220};adapter.present(only_mask);adapter.sync();
    check(!adapter.focus_next()&&!adapter.focused()&&!adapter.focus(only_mask.widgets.front().spec.key),
        "All-unavailable tab traversal focused masked native text");
    check(!adapter.closed()&&adapter.error().empty(),"An unavailable-only view closed the Rev adapter");
    std::vector<gui::ServiceResult> replies;
    check(adapter.service({41,gui::ServiceKind::prompt,"Ordinary prompt","Ordinary value"},
        [&](gui::ServiceResult reply){replies.push_back(std::move(reply));}),
        "Background masking prevented an ordinary native prompt");
    const auto accept=gui::prompt_accept_bounds(only_mask.client_size);
    const gui::Point at{accept.x+accept.width/2,accept.y+accept.height/2};
    gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::press,at);
    gui::rev::Probe::pointer_phase(adapter,gui::PointerKind::release,at);adapter.sync();
    check(replies.size()==1&&replies.front().status==gui::ServiceStatus::success&&
        replies.front().value=="Ordinary value"&&!adapter.service_active(),
        "Background masked placeholder intercepted an active native prompt");
    adapter.close();adapter.sync();
}
}
int main() {
    try {
        masked_control_is_unavailable();
        std::cout<<"Rev accepts masked snapshots using disabled opaque placeholders while preserving clear model values and ordinary controls\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
