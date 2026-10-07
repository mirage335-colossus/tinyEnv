#include "adapter.hpp"
#include "host/contract.hpp"
#include "tests/fixture.hpp"
#include <iostream>

namespace {
void native_prompt_focus_contract() {
    foundation::host::Session<foundation::ui::Application,gui::fltk::Adapter> session;
    auto& adapter=session.adapter;adapter.show();
    auto sync=[&]{session.tick();Fl::check();Fl::flush();};sync();
    const gui::WidgetKey editor{"entries.editor",1},list{"entries.list",1};
    fixture::check(adapter.focus(editor),"Missing main-window focus before prompt");
    auto open=[&] {
        adapter.policy().send(gui::WidgetEvent{{"entries.options",1},gui::ChooseOption{"heading"}});sync();
        auto* window=Fl::modal();
        fixture::check(adapter.service_active()&&window&&window!=&adapter.window(),"Missing native heading prompt");
        Fl_Input* input=nullptr;
        for(int i=0;i<window->children();++i)if(auto* candidate=dynamic_cast<Fl_Input*>(window->child(i)))input=candidate;
        fixture::check(input,"Missing native prompt input");
        return input;
    };
    auto* input=open();
    fixture::check(Fl::focus()==input,"Initial native prompt focus was stolen");
    for(unsigned tick=0;tick<120;++tick) {
        sync();fixture::check(Fl::focus()==input,"Main-window synchronization stole native prompt focus");
    }
    const std::string heading="Pasted heading";
    input->position(input->size(),0);Fl::copy(heading.data(),int(heading.size()),1);Fl::paste(*Fl::focus(),1);sync();
    fixture::check(std::string(input->value())==heading,"Native clipboard paste missed the heading prompt");
    fixture::check(adapter.focus(list)&&adapter.focused()==list,"Retained focus did not update during prompt");
    sync();fixture::check(Fl::focus()==input,"Programmatic main-window focus stole native prompt input");
    Fl_Return_Button* accept=nullptr;
    for(int i=0;i<Fl::modal()->children();++i)
        if(auto* candidate=dynamic_cast<Fl_Return_Button*>(Fl::modal()->child(i)))accept=candidate;
    fixture::check(accept,"Missing native prompt accept button");accept->do_callback();
    // Native dialog teardown can deliver focus to the former main-window child
    // before the service completion is synchronized (notably on Windows).
    for(const auto& key:{editor,gui::WidgetKey{"entries.options",1},list}) {
        adapter.native_widget(key)->handle(FL_FOCUS);
        fixture::check(adapter.focused()==list,"Background native focus changed retained focus during prompt completion");
    }
    sync();
    fixture::check(!adapter.service_active()&&fixture::widget(session.application.view(),"entries.heading").state.text==heading,
        "Native prompt did not apply pasted heading");
    fixture::check(Fl::focus()==adapter.native_widget(list),"Native focus was not restored after prompt completion");
    fixture::check(adapter.native_widget(editor)->take_focus()&&adapter.focused()==editor,
        "Native user focus did not resume after prompt completion");
    input=open();fixture::check(Fl::focus()==input,"Reopened native prompt lost input focus");
    adapter.focus(std::nullopt);sync();fixture::check(Fl::focus()==input,"Clearing main-window focus changed active prompt focus");
    Fl::modal()->do_callback();
    for(const auto& key:{editor,gui::WidgetKey{"entries.options",1},list}) {
        adapter.native_widget(key)->handle(FL_FOCUS);
        fixture::check(!adapter.focused(),"Background native focus restored cleared retained focus during prompt cancellation");
    }
    sync();
    fixture::check(!adapter.service_active()&&Fl::focus()==nullptr,"Cancelled prompt did not restore cleared main-window focus");
    fixture::check(fixture::widget(session.application.view(),"entries.heading").state.text==heading,
        "Cancelled native prompt changed the heading");
    fixture::check(adapter.error().empty(),"Native prompt callback failed");
    adapter.close();adapter.sync();
}

void raw_pointer_contract() {
    std::vector<gui::WidgetEvent> events;
    gui::fltk::Adapter adapter([&](const gui::Event& event) {
        if(const auto* value=std::get_if<gui::WidgetEvent>(&event))events.push_back(*value);
    });
    gui::Snapshot view;view.client_size={320,220};
    gui::Widget surface;surface.spec.key={"fixture.surface",1};surface.spec.kind=gui::Kind::bitmap;
    surface.spec.pointer_input=true;surface.state.bounds={20,20,220,140};
    surface.state.bitmap={"fixture.surface",1,gui::solid_bitmap(240,240,240)};
    gui::Widget label;label.spec.key={"fixture.annotation",1};label.spec.kind=gui::Kind::label;
    label.state.bounds={40,40,120,24};label.state.text="Samples";
    view.widgets={surface,label};adapter.present(view);adapter.show();adapter.sync();Fl::check();
    struct Restore {
        int x=Fl::e_x,y=Fl::e_y,keysym=Fl::e_keysym,state=Fl::e_state,clicks=Fl::e_clicks;
        ~Restore(){Fl::e_x=x;Fl::e_y=y;Fl::e_keysym=keysym;Fl::e_state=state;Fl::e_clicks=clicks;}
    } restore;
    auto pointer=[&](int event,int x,int y) {
        Fl::e_x=x;Fl::e_y=y;Fl::e_keysym=FL_Button+FL_LEFT_MOUSE;
        Fl::e_state=event==FL_RELEASE?0:FL_BUTTON1;Fl::e_clicks=0;
        adapter.window().handle(event);
    };
    pointer(FL_PUSH,60,50);
    Fl::e_keysym=FL_Button+FL_MIDDLE_MOUSE;Fl::e_state=FL_BUTTON1;
    adapter.window().handle(FL_RELEASE);
    fixture::check(events.size()==1,"Foreign mouse release ended the left-button gesture");
    view.widgets.back().state.bounds={140,80,120,24};adapter.present(view);adapter.sync();
    pointer(FL_DRAG,280,200);pointer(FL_RELEASE,280,200);
    fixture::check(events.size()==3,"Native raw gesture lost phase or synthesized an extra click");
    const gui::PointerKind phases[]{gui::PointerKind::press,gui::PointerKind::move,gui::PointerKind::release};
    for(unsigned i=0;i<3;++i) {
        const auto* input=std::get_if<gui::PointerInput>(&events[i].input);
        fixture::check(events[i].target==surface.spec.key&&input&&input->kind==phases[i]&&input->pointer_id!=0,
            "Native raw gesture changed target or pointer owner");
    }
    fixture::check(std::get<gui::PointerInput>(events.back().input).position==gui::Point{280,200},"Captured release coordinates were clipped");
    pointer(FL_PUSH,60,50);Fl::e_keysym=FL_Escape;adapter.window().handle(FL_KEYDOWN);
    fixture::check(events.size()==5&&std::get<gui::PointerInput>(events.back().input).kind==gui::PointerKind::cancel,
        "Escape did not cancel the native raw gesture");
    pointer(FL_RELEASE,60,50);fixture::check(events.size()==5,"Cancelled native gesture later released");
    pointer(FL_PUSH,60,50);view.widgets[0].spec.key.generation=2;adapter.present(view);adapter.sync();
    const auto count=events.size();pointer(FL_RELEASE,60,50);
    fixture::check(events.size()==count,"Replaced native raw target inherited pointer ownership");
    pointer(FL_PUSH,60,50);
    gui::Widget overlay;overlay.spec.key={"fixture.overlay",1};overlay.spec.kind=gui::Kind::button;
    overlay.state.label="Cover";overlay.state.bounds={40,40,120,24};view.widgets.push_back(overlay);
    adapter.present(view);adapter.sync();const auto obscured=events.size();pointer(FL_RELEASE,60,50);
    fixture::check(events.size()==obscured,"Obscured native raw surface retained pointer ownership");
    adapter.close();adapter.sync();
    fixture::check(adapter.error().empty(),"Native raw gesture callback failed");
}
}

int main(){try{
    native_prompt_focus_contract();
    raw_pointer_contract();
    foundation::host::Session<foundation::ui::Application,gui::fltk::Adapter> session;
    auto& adapter=session.adapter;adapter.show();
    auto sync=[&]{session.tick();Fl::check();Fl::flush();};sync();
    fixture::feature(session.application,
        [&](std::string text){auto* editor=dynamic_cast<Fl_Text_Editor*>(adapter.native_widget({"entries.editor",1}));fixture::check(editor,"Missing native editor");editor->buffer()->text(text.c_str());editor->do_callback();},
        [&](std::string id){auto* button=dynamic_cast<Fl_Button*>(adapter.native_widget({id,1}));if(!button||!button->active())throw std::runtime_error("Missing active native button: "+id+"; shared enabled="+std::to_string(fixture::widget(session.application.view(),id).state.enabled));button->do_callback();},
        [&](std::string){fixture::check(adapter.focus(gui::WidgetKey{"entries.list",1}),"Native list focus failed");const auto old=Fl::e_keysym;Fl::e_keysym=FL_Down;fixture::check(adapter.native_widget({"entries.list",1})->handle(FL_KEYDOWN)==1,"Native list key rejected");Fl::e_keysym=old;},sync);
    adapter.window().size(800,640);sync();
    fixture::parity(session.application.view());
    fixture::unavailable_service(adapter);
    int work_x=0,work_y=0,work_width=0,work_height=0;
    Fl::screen_work_area(work_x,work_y,work_width,work_height,0);
    // Begin at the display edge: enlarging a default-positioned window can leave
    // part of its client area off screen, which native pixel reads cannot retain.
    adapter.window().position(work_x+work_width-32,work_y+work_height-32);sync();
    fixture::visual_sizes(session.application,adapter,"fltk",[&]{
        const auto size=session.application.view().client_size;
        auto& window=adapter.window();window.size(int(size.width),int(size.height));sync();
        const int decorated_width=window.decorated_w(),decorated_height=window.decorated_h();
        fixture::check(decorated_width<=work_width&&decorated_height<=work_height,
            "Display work area is too small for the complete native capture");
        window.position(work_x+(work_width-window.w())/2,
                        work_y+(work_height-decorated_height)/2+decorated_height-window.h());
        window.redraw();sync();
        fixture::check(window.x_root()>=work_x&&window.y_root()>=work_y&&
            window.x_root()+window.w()<=work_x+work_width&&
            window.y_root()+window.h()<=work_y+work_height,
            "Native capture viewport extends outside the display work area");
        std::cout<<"FLTK capture client "<<window.x_root()<<','<<window.y_root()<<' '
            <<window.w()<<'x'<<window.h()<<" inside work area "<<work_x<<','<<work_y<<' '
            <<work_width<<'x'<<work_height<<'\n';
    },[&](const std::string& name){
        Fl::flush();
        fixture::check(Fl::focus()==nullptr,"Native focus was not cleared");
        adapter.window().make_current();
        const std::unique_ptr<unsigned char[]> image(fl_read_image(nullptr,0,0,adapter.window().w(),adapter.window().h()));
        fixture::check(bool(image),"Native capture failed");
        fixture::capture(image.get(),unsigned(adapter.window().w()),unsigned(adapter.window().h()),name.c_str());
    });
    adapter.policy().send(gui::WidgetEvent{{"entries.options",1},gui::ChooseOption{"heading"}});sync();
    fixture::check(adapter.service_active(),"Native service not started");
    session.application.handle(gui::CloseEvent{});sync();
    fixture::check(!adapter.window().shown()&&!adapter.service_active(),"Native close did not release service/window");
    fixture::check(adapter.error().empty(),"Native callback failed");
    // Generic kind coverage protects the maintained flat-control adapter patch.
    unsigned toggles=0;
    gui::fltk::Adapter generic([&](const gui::Event& event){
        if(const auto* widget=std::get_if<gui::WidgetEvent>(&event))
            if(const auto* value=std::get_if<gui::SetChecked>(&widget->input))
                if(value->value)++toggles;
    });
    gui::Snapshot declaration;declaration.client_size={320,120};
    gui::Widget toggle;toggle.spec.key.id="fixture.toggle";toggle.spec.kind=gui::Kind::toggle;
    toggle.state.label="Enable option";toggle.state.bounds={16,16,288,32};
    declaration.widgets.push_back(toggle);generic.present(declaration);generic.show();generic.sync();Fl::check();
    auto* native_toggle=dynamic_cast<Fl_Check_Button*>(generic.native_widget(toggle.spec.key));
    fixture::check(native_toggle,"Missing generic native toggle");
    native_toggle->value(1);native_toggle->do_callback();
    fixture::check(toggles==1,"Flat toggle changed native callback meaning");
    fixture::check(generic.focus(toggle.spec.key),"Generic toggle focus failed");
    generic.focus(std::nullopt);fixture::check(Fl::focus()==nullptr,"Generic clear focus failed");
    generic.close();
    std::cout<<"FLTK real controls, shared extension, declarations, capture and close passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
