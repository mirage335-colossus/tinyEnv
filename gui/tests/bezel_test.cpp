#include "host/framebuffer.hpp"
#include "shared/application.hpp"
#include <iostream>

namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Display {
    std::vector<gui::Frame> frames;
    std::vector<std::vector<std::string>> labels;
    bool fail=false;
    void present(const gui::Frame& frame,const std::vector<std::string>& text) {
        if(fail)throw std::runtime_error("Display failed");
        frames.push_back(frame);labels.push_back(text);
    }
};
// An ordinary generic application fixture. Its public epoch is independent of
// snapshot revision (intentionally repeated) and all host descriptors.
struct App {
    gui::Adapter& adapter;
    gui::Snapshot view;
    std::uint64_t epoch=1;
    unsigned activations=0,choices=0,cancellations=0,completions=0;
    bool pending=false,fail=false;
    std::function<void()> on_tick,on_activate;
    explicit App(gui::Adapter& target):adapter(target) {
        view.client_size={320,220};
        const auto add=[&](const char* id,gui::Kind kind,const char* label,gui::Rect bounds) {
            gui::Widget widget;widget.spec.key={id,1};widget.spec.kind=kind;widget.state.label=label;widget.state.bounds=bounds;
            view.widgets.push_back(widget);
        };
        add("action",gui::Kind::button,"Run",{5,5,80,30});
        add("menu",gui::Kind::menu,"Options",{5,45,80,30});
        view.widgets.back().state.options={{"first","First","value1",true},{"disabled","Disabled","",false},{"second","Second","value2",true}};
        add("toggle",gui::Kind::toggle,"Switch",{5,85,80,30});
        add("raw",gui::Kind::bitmap,"",{200,5,80,30});view.widgets.back().spec.pointer_input=true;
        add("progress",gui::Kind::label,"",{5,130,200,30});
        publish();
    }
    void publish() {
        pending=true;
        if(fail)throw std::runtime_error("Application publish failed");
        adapter.present(view);pending=false;
    }
    void handle(gui::Event event) {
        if(const auto* widget=std::get_if<gui::WidgetEvent>(&event)) {
            if(std::holds_alternative<gui::Activate>(widget->input)) {
                ++epoch;++activations;
                if(on_activate)on_activate();
            } else if(const auto* checked=std::get_if<gui::SetChecked>(&widget->input)) {
                ++epoch;view.widgets[2].state.checked=checked->value;
            } else if(std::holds_alternative<gui::ChooseOption>(widget->input)) {++epoch;++choices;}
            else if(const auto* pointer=std::get_if<gui::PointerInput>(&widget->input);
                    pointer&&pointer->kind==gui::PointerKind::cancel) {
                ++epoch;++cancellations;view.widgets[0].state.label="After cancel";
            }
            publish();
        } else if(const auto* resize=std::get_if<gui::ResizeEvent>(&event)) {
            view.client_size=resize->client_size;view.display_scale=resize->display_scale;publish();
        } else if(std::holds_alternative<gui::CloseEvent>(event))adapter.close();
    }
    void tick(){if(on_tick){auto callback=std::move(on_tick);on_tick={};callback();}retry_presentation();}
    void retry_presentation(){if(pending&&!adapter.closed())publish();}
    void shutdown(){}
    std::uint64_t input_epoch() const{return epoch;}
    bool presentation_pending() const{return pending;}
    std::optional<gui::ServiceRequest> next_service(){return std::nullopt;}
    bool complete_service(gui::ServiceResult){++epoch;++completions;view.widgets[0].state.label="After service";publish();return true;}
    void qualify(const std::function<void()>& present){present();}
};
struct Services : foundation::host::AdapterServices {
    inline static std::optional<gui::ServiceResult> result;
    std::optional<gui::ServiceResult> poll(){auto reply=std::move(result);result.reset();return reply;}
};
using Host=foundation::host::FramebufferHost<App>;
template<class H> auto show(H& host,Display& display) {
    auto shown=host.prepare_bezel();check(bool(shown),"Preparation unavailable");
    display.present(shown.frame(),shown.labels());
    check(host.commit_bezel(shown.token()),"Displayed presentation not committed");return shown;
}
template<class H> auto select(H& host,Display& display,std::string label) {
    for(unsigned i=0;i<30;++i) {
        auto shown=show(host,display);
        if(shown.labels()[2]==label)return shown;
        check(host.bezel_button(shown.token(),2),"Next did not select a declared action");
    }
    throw std::runtime_error("Projected action not found");
}
void projection_and_transactions() {
    Host host;Display display;
    check(host.bezel_labels()==std::vector<std::string>{"Previous","Next","Run"},"Initial labels differ");
    Host::BezelToken missing;
    check(!host.bezel_button(missing,3)&&host.application().activations==0,"Missing token activated");
    auto candidate=host.prepare_bezel();
    check(!host.bezel_button(candidate.token(),3)&&host.application().activations==0,"Uncommitted labels armed input");
    auto shown=show(host,display);const auto retained=shown.frame();
    check(host.bezel_button(shown.token(),2),"Next selection failed");
    check(!host.bezel_button(shown.token(),3)&&host.application().choices==0,"Next armed undisplayed Execute");
    auto first=show(host,display);
    check(first.labels()[2]=="First"&&first.frame().damage.width==0&&first.frame().damage.height==0,
          "Labels-only change was not presented with zero damage");
    check(host.bezel_button(first.token(),2),"Second selection failed");
    auto second=show(host,display);check(second.labels()[2]=="Second","Disabled action was projected");
    check(host.bezel_button(second.token(),3)&&host.application().choices==1,"Declared option did not dispatch");
    check(!host.bezel_button(second.token(),3)&&host.application().choices==1,"Consumed token repeated");
    check(!host.commit_bezel(second.token()),"Consumed token rearmed");
    check(retained.pixels&&retained.width==320,"Retained frame was lost");
    Host foreign;
    check(!foreign.commit_bezel(second.token())&&!foreign.bezel_button(second.token(),3),"Foreign token accepted");
    std::optional<Host> recycled;recycled.emplace();auto expired=show(*recycled,display);
    const auto* old_address=&*recycled;recycled.reset();recycled.emplace();
    check(&*recycled==old_address,"Host address reuse fixture did not reuse storage");
    auto replacement=show(*recycled,display);
    check(!recycled->commit_bezel(expired.token())&&!recycled->bezel_button(expired.token(),3)&&
          recycled->application().activations==0,"Destroyed host token revived at a reused address");
    check(recycled->bezel_button(replacement.token(),3)&&recycled->application().activations==1,
          "Replacement host token rejected after address reuse");
    check(!host.commit_bezel(missing),"Invalid commit accepted");
    auto old=host.prepare_bezel();auto latest=host.prepare_bezel();
    display.present(old.frame(),old.labels());check(!host.commit_bezel(old.token()),"Obsolete asynchronous commit accepted");
    display.present(latest.frame(),latest.labels());check(host.commit_bezel(latest.token()),"Latest asynchronous commit rejected");
    check(!host.bezel_button(old.token(),3)&&host.application().choices==1,"Older committed opportunity replaced current token");
    Host failed;Display broken;auto undisplayed=failed.prepare_bezel();broken.fail=true;
    bool threw=false;try{broken.present(undisplayed.frame(),undisplayed.labels());}catch(const std::runtime_error&){threw=true;}
    check(threw&&!failed.bezel_button(undisplayed.token(),3)&&failed.application().activations==0,"Failed display armed input");
    broken.fail=false;auto retry=show(failed,broken);
    check(retry.frame().damage.width==retry.frame().width,"Failed display advanced damage base");
    check(failed.bezel_button(retry.token(),3)&&failed.application().activations==1,"Failed display retry lost action");
    Host convenience;Display automatic;
    check(convenience.present_bezel(automatic)&&automatic.labels.size()==1,"Generic display convenience failed");
}
void changing_declarations() {
    const auto scenario=[](const std::function<void(gui::Snapshot&)>& mutate) {
        Host host;Display display;auto shown=show(host,display);
        mutate(host.application().view);host.application().publish();
        check(!host.bezel_button(shown.token(),3)&&host.application().activations==0&&host.application().choices==0,
              "Changed declaration dispatched old or fallback action");
        check(!host.bezel_button(shown.token(),3),"Rejected declaration token remained armed");
    };
    scenario([](auto& view){view.widgets.erase(view.widgets.begin());});
    scenario([](auto& view){view.widgets[0].state.enabled=false;});
    scenario([](auto& view){view.widgets[0].state.visible=false;});
    scenario([](auto& view){std::swap(view.widgets[0],view.widgets[1]);});
    scenario([](auto& view){++view.widgets[0].spec.key.generation;});
    scenario([](auto& view){view.widgets[1].state.options[0].value="changed meaning";});
    scenario([](auto& view){
        gui::Widget modal;modal.spec.key={"modal",1};modal.spec.kind=gui::Kind::group;modal.state.bounds={0,0,320,220};
        view.widgets.insert(view.widgets.begin(),modal);view.modal_root=modal.spec.key;
    });
    scenario([](auto& view){view.key_bindings.push_back({gui::ShortcutKey::escape,view.widgets[0].spec.key});});
    scenario([](auto& view){view.pages={{"one","One",true,true},{"two","Two",true,true}};view.active_page="one";});
    Host toggle;Display display;auto shown=select(toggle,display,"Switch");
    toggle.application().view.widgets[2].state.checked=true;toggle.application().publish();
    check(!toggle.bezel_button(shown.token(),3)&&toggle.application().view.widgets[2].state.checked,"Stale toggle desired value applied");
    auto fresh=show(toggle,display);
    check(toggle.bezel_button(fresh.token(),3)&&!toggle.application().view.widgets[2].state.checked,"Fresh toggle did not apply captured value");
}
void transient_contexts() {
    Host host(5);Display display;auto background=show(host,display);
    bool cancelled=false;
    host.adapter().service({7,gui::ServiceKind::prompt,"Value","old",10},[&](gui::ServiceResult result){cancelled=result.status==gui::ServiceStatus::cancelled;});
    check(!host.bezel_button(background.token(),3)&&host.application().activations==0,"Prompt allowed background action");
    auto prompt=show(host,display);
    check(prompt.labels()==std::vector<std::string>{"Cancel","Accept","","",""},"Prompt projected background keys");
    host.adapter().text("new");
    check(!host.bezel_button(prompt.token(),2)&&bool(host.adapter().prompt()),"Changed prompt accepted stale value");
    auto changed=show(host,display);
    check(host.bezel_button(changed.token(),1)&&cancelled&&!host.adapter().prompt(),"Prompt cancel missing");
    host.adapter().service({8,gui::ServiceKind::prompt,"First","",10},[](auto){});
    auto first=show(host,display);host.adapter().key(gui::Key::escape);
    bool replacement=false;host.adapter().service({9,gui::ServiceKind::prompt,"Second","",10},[&](auto){replacement=true;});
    check(!host.bezel_button(first.token(),2)&&!replacement,"Replacement prompt accepted old token");
    auto second=show(host,display);check(host.bezel_button(second.token(),1)&&replacement,"Replacement prompt cannot cancel");
    check(host.adapter().open_popup({"menu",1}),"Popup did not open");
    auto popup=show(host,display);check(popup.labels()[2]=="Choose","Popup did not own bezel keys");
    check(host.bezel_button(popup.token(),2),"Popup Next missing");
    check(!host.bezel_button(popup.token(),3)&&host.application().choices==0,"Popup Next armed undisplayed choice");
    auto next=show(host,display);check(host.bezel_button(next.token(),3)&&host.application().choices==1,"Popup selected option did not dispatch");
    check(host.adapter().open_popup({"menu",1}),"Popup did not reopen");
    auto obsolete=show(host,display);
    host.application().view.widgets[1].state.options[0].value="replacement";host.application().publish();
    check(!host.bezel_button(obsolete.token(),3)&&host.application().choices==1,"Popup declaration disagreement dispatched");
    check(!host.commit_bezel(host.prepare_bezel().token()),"Disagreeing popup committed");
    host.adapter().key(gui::Key::escape);
    auto closed=show(host,display);host.adapter().close();
    check(!host.bezel_button(closed.token(),3)&&!host.prepare_bezel(),"Closed host accepted key");
    check(host.bezel_labels()==std::vector<std::string>(5),"Closed labels not empty");
    bool rejected=false;try{foundation::host::Bezel invalid(4);}catch(const std::invalid_argument&){rejected=true;}
    check(rejected,"Unsupported key count accepted");
}
void settlement_and_failures() {
    Host tick;Display display;auto shown=show(tick,display);
    tick.application().on_tick=[&]{++tick.application().epoch;tick.application().view.widgets[0].state.label="After tick";tick.application().publish();};
    check(!tick.bezel_button(shown.token(),3)&&tick.application().activations==0,"Tick changed meaning after key validation");
    foundation::host::FramebufferHost<App,Services> services;
    auto service=show(services,display);Services::result=gui::ServiceResult{17,gui::ServiceStatus::success,"",{}};
    check(!services.bezel_button(service.token(),3)&&services.application().completions==1&&services.application().activations==0,
          "Service completion changed meaning after key validation");
    Host touch;
    using C=foundation::host::Contact;using P=foundation::host::ContactPhase;
    check(touch.contact({C::Source::touch,0,1},P::press,{220,20}),"Raw pointer press missing");
    auto contact=show(touch,display);
    check(!touch.bezel_button(contact.token(),3)&&touch.application().cancellations==1&&touch.application().activations==0,
          "Touch cancellation changed meaning after key validation");
    Host failure;auto old=show(failure,display);failure.application().fail=true;
    ++failure.application().epoch;failure.application().view.widgets[0].state.label="New meaning";
    bool threw=false;try{failure.application().publish();}catch(const std::runtime_error&){threw=true;}
    check(threw&&failure.application().presentation_pending(),"Publish failure fixture did not fail");
    threw=false;try{failure.bezel_button(old.token(),3);}catch(const std::runtime_error&){threw=true;}
    check(threw&&failure.application().activations==0,"Failed publication activated old visible meaning");
    failure.application().fail=false;failure.application().retry_presentation();
    check(!failure.bezel_button(old.token(),3)&&!failure.commit_bezel(old.token()),"Exception left input opportunity armed");
    Host reentrant;auto once=show(reentrant,display);bool nested=true;
    reentrant.application().on_activate=[&]{nested=reentrant.bezel_button(once.token(),3);};
    check(reentrant.bezel_button(once.token(),3)&&!nested&&reentrant.application().activations==1,"Reentrant activation reused token");
    Host exception;auto attempt=show(exception,display);
    exception.application().on_activate=[] {throw std::runtime_error("Action failed after effect");};
    threw=false;try{exception.bezel_button(attempt.token(),3);}catch(const std::runtime_error&){threw=true;}
    check(threw&&exception.application().activations==1&&!exception.bezel_button(attempt.token(),3),"Uncertain action automatically repeated");
}
struct SlowExecutor : foundation::ui::TaskExecutor {
    foundation::ui::TextTask task;
    foundation::ui::TaskUpdate start(std::vector<std::string> input) override{return task.start(std::move(input));}
    std::optional<foundation::ui::TaskUpdate> advance() override{return task.advance(1);}
    void cancel() noexcept override{task.cancel();}
    void shutdown() noexcept override{task.shutdown();}
};
struct RealApp : foundation::ui::Application {
    explicit RealApp(gui::Adapter& adapter):Application(adapter,std::make_unique<SlowExecutor>()){}
};
void authoritative_application() {
    foundation::host::FramebufferHost<RealApp> host;Display display;auto& app=host.application();
    const auto add=[&](std::string text){app.handle(gui::WidgetEvent{{"entries.editor",1},gui::EditText{std::move(text),""}});app.handle(gui::WidgetEvent{{"entries.add",1},gui::Activate{}});};
    add("First");add("Second");app.enable_remove_feature();
    const auto rows=gui::find_widget(app.view(),{"entries.list",1})->state.records;
    app.handle(gui::WidgetEvent{{"entries.list",1},gui::SelectRecord{rows[0].id}});
    auto remove=select(host,display,"Remove selected");
    app.handle(gui::WidgetEvent{{"entries.list",1},gui::SelectRecord{rows[1].id}});
    check(!host.bezel_button(remove.token(),3)&&gui::find_widget(app.view(),{"entries.list",1})->state.records==rows,
          "Same Remove key executed a newly selected operand");
    auto current=show(host,display);
    check(host.bezel_button(current.token(),3),"New Remove meaning not dispatchable");
    const auto remaining=gui::find_widget(app.view(),{"entries.list",1})->state.records;
    check(remaining.size()==1&&remaining.front().id==rows[0].id,"Fresh Remove deleted wrong record");
    add(std::string(256,'x'));app.handle(gui::WidgetEvent{{"entries.task.start",1},gui::Activate{}});
    auto cancel=select(host,display,"Cancel task");const auto epoch=app.input_epoch();const auto processed=app.task_progress().processed;
    host.resize({800,640},1.25);
    check(app.input_epoch()==epoch&&app.task_progress().processed>processed,"Layout/progress fixture changed input epoch");
    check(host.bezel_button(cancel.token(),3)&&!app.task_running(),"Unchanged Cancel invalidated by resize or incomplete progress");
    check(gui::find_widget(app.view(),{"entries.task.status",1})->state.text=="Task cancelled","Cancel did not reach authoritative application");
}
void failed_authoritative_publication() {
    foundation::host::FramebufferHost<RealApp> host;Display display;auto& app=host.application();
    app.handle(gui::WidgetEvent{{"entries.editor",1},gui::EditText{"First",""}});
    app.handle(gui::WidgetEvent{{"entries.add",1},gui::Activate{}});app.enable_remove_feature();
    const auto first=gui::find_widget(app.view(),{"entries.list",1})->state.records.front().id;
    app.handle(gui::WidgetEvent{{"entries.list",1},gui::SelectRecord{first}});
    auto remove=select(host,display,"Remove selected");const auto epoch=app.input_epoch();
    // Adapter publication rejects this geometry before allocating any pixels.
    // Accepted editor/core mutations then survive the same publication failure.
    const auto fails=[&](const gui::Event& event) {
        bool threw=false;try{app.handle(event);}catch(const std::length_error&){threw=true;}
        check(threw&&app.presentation_pending(),"Expected framebuffer publication failure missing");
    };
    fails(gui::ResizeEvent{{100000,100000},1});
    check(app.input_epoch()==epoch,"Failed layout-only publication changed semantic epoch");
    fails(gui::WidgetEvent{{"entries.editor",1},gui::EditText{"Second",""}});
    fails(gui::WidgetEvent{{"entries.editor",1},gui::SubmitText{}});
    check(app.input_epoch()==epoch+2,"Failed editor/core publication lost semantic epochs");
    check(gui::find_widget(host.adapter().snapshot(),{"entries.list",1})->state.records.size()==1,
          "Failed core publication unexpectedly reached old adapter pixels");
    bool threw=false;try{host.bezel_button(remove.token(),3);}catch(const std::length_error&){threw=true;}
    check(threw,"Pending publication key settlement did not propagate failure");
    app.handle(gui::ResizeEvent{{640,480},1});
    check(!host.bezel_button(remove.token(),3)&&!host.commit_bezel(remove.token()),"Failed settlement retained old Remove opportunity");
    const auto& rows=gui::find_widget(app.view(),{"entries.list",1})->state.records;
    check(rows.size()==2&&rows[0].accessible_text=="First"&&rows[1].accessible_text=="Second",
          "Failed publication lost/repeated core mutation or dispatched stale Remove");
}
}
int main(){try{
    projection_and_transactions();changing_declarations();transient_contexts();settlement_and_failures();authoritative_application();failed_authoritative_publication();
    std::cout<<"Bezel immutable display commits, authoritative meaning, stale/reentrant rejection and settlement passed\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
