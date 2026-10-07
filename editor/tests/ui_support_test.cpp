#include "visual/ui/ui.hpp"

#include <iostream>
#include <stdexcept>
#include <thread>

namespace v = foundation::visual;
namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
struct Adapter : gui::Adapter {
    gui::Snapshot snapshot;
    unsigned presentations = 0;
    bool fail = false, is_closed = false;
    gui::Point scroll_point;
    std::optional<gui::WidgetKey> focus_target;
    void present(gui::Snapshot value) override {
        if (fail) throw std::runtime_error("Presentation failed");
        gui::validate_snapshot(value); snapshot = std::move(value); ++presentations;
    }
    gui::Size measure_text(const gui::TextMeasureRequest&) const override { return {40,20}; }
    gui::Availability resolved_availability(const gui::WidgetKey& target) const override { return gui::availability(snapshot,target); }
    std::optional<gui::WidgetKey> focused() const override { return focus_target; }
    bool focus(std::optional<gui::WidgetKey> target) override { focus_target=std::move(target);return true; }
    bool focus_next(bool) override { return true; }
    void scroll(const gui::WidgetKey&,gui::Point) override {}
    gui::Point scroll_offset(const gui::WidgetKey& target) const override { return target.id=="scroll" ? scroll_point : gui::Point{}; }
    gui::TextSelection text_selection(const gui::WidgetKey&) const override { return {}; }
    void text_selection(const gui::WidgetKey&,gui::TextSelection) override {}
    bool open_popup(const gui::WidgetKey&) override { return true; }
    void close_popup(const gui::WidgetKey&) override {}
    void invalidate(const gui::WidgetKey&,gui::PixelRect) override {}
    bool closed() const override { return is_closed; }
    void close() override { is_closed=true; }
};
gui::Snapshot form() {
    gui::Snapshot view; view.title="Optional form";
    const auto add=[&](std::string id,gui::Kind kind,double y) -> gui::Widget& {
        gui::Widget w; w.spec.key={std::move(id),1}; w.spec.kind=kind;
        w.state.bounds={8,y,200,28}; view.widgets.push_back(std::move(w));return view.widgets.back();
    };
    add("status",gui::Kind::label,8).state.text="Ready";
    add("start",gui::Kind::button,40).state.label="Start";
    add("stop",gui::Kind::button,72).state.label="Stop";
    auto& choice=add("device",gui::Kind::choice,104);
    choice.state.options={{"a","Device A","a",true},{"b","Device B","b",true}};
    choice.state.selected="a";
    add("enabled",gui::Kind::toggle,136);
    auto& text=add("code",gui::Kind::text,168);
    text.spec.text_policy={true,false,1024,gui::SubmitKey::control_enter};
    add("results",gui::Kind::list,200).state.bounds.height=100;
    return view;
}
const gui::Widget& widget(const v::Ui& ui, std::string_view id) {
    return *gui::find_widget(ui.view(),*ui.widget(id));
}
void gui_model() {
    Adapter adapter;v::Ui ui(adapter,form());
    check(adapter.presentations==1,"initial presentation absent");
    auto status=*ui.widget("status");
    {
        auto batch=ui.batch();
        check(ui.set_text(status,"Receiving \xc3\xa9")==v::UiResult::applied,"UTF-8 text update failed");
        check(ui.set_enabled("start",false)==v::UiResult::applied,"button lockout failed");
        check(ui.show("stop",false)==v::UiResult::applied,"visibility update failed");
        check(adapter.presentations==1,"batch published too early");
    }
    check(adapter.presentations==2,"batch did not publish exactly once");
    check(ui.set_text(status,"Receiving \xc3\xa9")==v::UiResult::unchanged,"unchanged edit published");
    check(ui.set_text(status,std::string("invalid\0text",12))==v::UiResult::invalid_value,"invalid UTF-8 accepted");
    check(ui.set_checked(status,true)==v::UiResult::wrong_kind,"incompatible handle accepted");
    check(ui.set_text(gui::WidgetKey{"status",999},"stale")==v::UiResult::stale_widget,"stale widget accepted");
    check(ui.set_enabled("absent",false)==v::UiResult::missing_widget,"missing widget accepted");
    check(ui.replace_options("device",{{"a","Renamed","a",true},{"c","C","c",true}})==v::UiResult::applied,"choice replacement failed");
    check(ui.selected("device").value=="a","stable option selection lost");
    check(ui.replace_options("device",{{"c","C","c",true}})==v::UiResult::applied&&!ui.selected("device").value,"removed selection retained");
    ui.select("device",std::string("c"));
    ui.replace_options("device",{{"c","C","c",true}},v::SelectionPolicy::clear);
    check(!ui.selected("device").value,"explicit selection clear failed");
    check(ui.replace_options("device",{{"c","C","c",true},{"c","Again","c",true}})==v::UiResult::invalid_value,"duplicate options accepted");
    check(ui.select("device",std::string("missing"))==v::UiResult::invalid_value,"nonexistent selection accepted");
    gui::Record record;record.id="row";record.accessible_text="Result";
    record.cells.push_back({"value",{0,0,80,28},{},gui::TextWrap::none});
    check(ui.replace_records("results",{record})==v::UiResult::applied,"record update failed");
    ui.select("results",std::string("row"));
    ui.replace_records("results",{});
    check(!ui.selected("results").value,"removed record selection retained");
    check(ui.focus("code")==v::UiResult::applied&&adapter.focus_target==ui.widget("code"),"focus unavailable");
    adapter.fail=true;ui.set_text("status","Authoritative state");
    check(ui.presentation_pending()&&ui.presentation_error(),"failed presentation was discarded");
    const auto revision=ui.view().revision;
    adapter.fail=false;
    check(ui.publish()&&!ui.presentation_pending()&&ui.view().revision==revision,"presentation retry changed meaning");
    check(widget(ui,"status").state.text=="Authoritative state","failed presentation rolled back application state");
}
struct Services { unsigned starts=0; std::string result="Ready for samples"; };
void set_busy(v::Ui& ui,bool busy) {ui.set_enabled("start",!busy);ui.set_enabled("stop",busy);}
void dispatch() {
    Adapter adapter;v::Ui ui(adapter,form());Services services;
    unsigned depth=0,maximum_depth=0;std::vector<unsigned> order;
    check(ui.bind<gui::Activate>("start",[&](v::Ui& facade,const gui::Activate&) {
        ++depth;maximum_depth=std::max(depth,maximum_depth);order.push_back(1);
        ++services.starts;set_busy(facade,true);facade.set_text("status",services.result);
        check(facade.handle(gui::WidgetEvent{*facade.widget("stop"),gui::Activate{}})==v::DispatchResult::queued,"nested input was not queued");
        order.push_back(2);--depth;
    }),"typed handler registration failed");
    ui.bind<gui::Activate>("stop",[&](v::Ui& facade,const gui::Activate&) {
        ++depth;maximum_depth=std::max(depth,maximum_depth);order.push_back(3);set_busy(facade,false);--depth;
    });
    const auto start=*ui.widget("start");
    check(ui.handle(gui::WidgetEvent{start,gui::Activate{}})==v::DispatchResult::handled,"activation rejected");
    check(services.starts==1&&order==std::vector<unsigned>({1,2,3})&&maximum_depth==1,"dispatch reordered or reentered");
    ui.set_enabled("start",false);
    check(ui.handle(gui::WidgetEvent{start,gui::Activate{}})==v::DispatchResult::rejected&&services.starts==1,"disabled stale input reached handler");
    check(ui.handle(gui::WidgetEvent{*ui.widget("code"),gui::EditText{"source \xcf\x80",""}})==v::DispatchResult::handled,"source edit failed");
    check(widget(ui,"code").state.text=="source \xcf\x80","model missed native text update");
    check(ui.handle(gui::WidgetEvent{*ui.widget("code"),gui::EditText{"lost update",""}})==v::DispatchResult::rejected,"stale text base accepted");
    bool wrong_thread=false;
    std::thread invalid([&] {try { ui.set_enabled("start",true); }catch(const std::logic_error&) { wrong_thread=true; }});invalid.join();
    check(wrong_thread,"worker directly mutated UI model");
    Adapter stateful_adapter;v::Ui stateful(stateful_adapter,form());
    stateful.bind<gui::Activate>("start",[counter=0](v::Ui& facade,const gui::Activate&) mutable {
        facade.set_text("status",std::to_string(++counter));
    });
    stateful.handle(gui::WidgetEvent{*stateful.widget("start"),gui::Activate{}});
    stateful.handle(gui::WidgetEvent{*stateful.widget("start"),gui::Activate{}});
    check(widget(stateful,"status").state.text=="2","mutable handler state did not persist");
    stateful.bind<gui::Activate>("stop",[counter=std::make_unique<unsigned>(0)](v::Ui& facade,const gui::Activate&) {
        facade.set_text("status",std::to_string(++*counter));
    });
    stateful.handle(gui::WidgetEvent{*stateful.widget("stop"),gui::Activate{}});
    stateful.handle(gui::WidgetEvent{*stateful.widget("stop"),gui::Activate{}});
    check(widget(stateful,"status").state.text=="2","owned move-only callable state did not persist");
}
void mailbox() {
    Adapter adapter;v::Ui ui(adapter,form(),2);
    const auto status=*ui.widget("status"),start=*ui.widget("start");
    auto producer=ui.begin_request();
    check(producer.post(v::SetText{status,"10%"},v::Delivery::progress,"progress")==v::PostResult::accepted,"progress rejected");
    check(producer.post(v::SetText{status,"50%"},v::Delivery::progress,"progress")==v::PostResult::coalesced,"progress was not coalesced");
    check(producer.post(v::SetEnabled{start,false})==v::PostResult::accepted,"reliable transition rejected");
    check(producer.post(v::SetText{status,"Complete"})==v::PostResult::full,"full reliable queue did not acknowledge rejection");
    check(producer.pending()==2,"mailbox capacity changed during coalescing");
    const auto presentations=adapter.presentations;
    auto drained=ui.drain();
    check(drained.processed==2&&drained.errors.empty()&&drained.results==std::vector<v::UiResult>({v::UiResult::applied,v::UiResult::applied}),"drain failed");
    check(widget(ui,"status").state.text=="50%"&&!widget(ui,"start").state.enabled,"owned commands applied incorrectly");
    check(adapter.presentations==presentations+1,"mailbox update batch was fragmented");
    check(producer.post(v::SetText{status,"Complete"})==v::PostResult::accepted,"completion retry failed");
    ui.drain();check(widget(ui,"status").state.text=="Complete","reliable completion absent");
    auto current=ui.begin_request();
    check(producer.post(v::SetText{status,"Late completion"})==v::PostResult::stale,"canceled request was accepted");
    check(current.post(v::SetText{status,"missing key"},v::Delivery::progress)==v::PostResult::invalid_command,"unkeyed progress accepted");
    check(current.post(v::SetText{status,std::string(16*1024*1024,'x')})==v::PostResult::full,"mailbox byte limit absent");
    std::string reserved="tiny";reserved.reserve(17*1024*1024);
    check(current.post(v::SetText{status,std::move(reserved)})==v::PostResult::full,"reserved payload bypassed mailbox byte limit");
    v::PostResult from_worker=v::PostResult::closed;
    std::thread worker([producer=current,status,&from_worker] {from_worker=producer.post(v::SetText{status,"Owned worker result"});});worker.join();
    check(from_worker==v::PostResult::accepted,"worker post rejected");
    ui.drain();check(widget(ui,"status").state.text=="Owned worker result","worker result lost");
    current.post(v::SetText{status,"Queued obsolete result"});
    ui.restart(form());
    check(ui.set_text(status,"Stale handle")==v::UiResult::stale_widget,"replaced view retained old handle");
    check(current.post(v::SetText{status,"Late old view"})==v::PostResult::stale&&ui.drain().processed==0,"old view queue survived restart");
    const auto removed=*ui.widget("status");
    ui.restart(gui::Snapshot{});ui.restart(form());
    check(ui.set_text(removed,"Reused generation")==v::UiResult::stale_widget,"removed and reintroduced key reused its generation");
    auto final=ui.postbox();ui.close();
    check(final.post(v::SetText{status,"Closed"})==v::PostResult::closed,"close accepted command");
    v::UiPost expired;
    {
        v::Ui temporary(adapter,form());expired=temporary.postbox();
    }
    check(expired.post(v::SetText{status,"Destroyed"})==v::PostResult::closed,"destroyed UI retained a live capability");
}
void modal_guard() {
    Adapter adapter;auto view=form();
    gui::Widget group;group.spec.key={"modal",1};group.spec.kind=gui::Kind::group;group.state.bounds={0,0,640,480};
    view.widgets.insert(view.widgets.begin(),group);
    for(std::size_t i=1;i<view.widgets.size();++i)view.widgets[i].spec.parent="modal";
    view.modal_root=group.spec.key;v::Ui ui(adapter,std::move(view));
    check(ui.set_enabled("modal",false)==v::UiResult::invalid_value,"modal root was disabled");
    check(ui.show("modal",false)==v::UiResult::invalid_value,"modal root was hidden");
    check(!ui.presentation_pending(),"modal rejection corrupted model presentation");
}
void scrolled_focus() {
    Adapter adapter;gui::Snapshot view;
    gui::Widget group;group.spec.key={"scroll",1};group.spec.kind=gui::Kind::group;
    group.state.bounds={0,0,200,120};group.state.content_size={200,2000};view.widgets.push_back(group);
    gui::Widget child;child.spec.key={"child",1};child.spec.kind=gui::Kind::text;child.spec.parent="scroll";
    child.state.bounds={8,900,100,28};view.widgets.push_back(child);
    v::Ui ui(adapter,std::move(view));
    check(ui.focus("child")==v::UiResult::invalid_value,"clipped child incorrectly focusable");
    adapter.scroll_point={0,850};
    check(ui.focus("child")==v::UiResult::applied&&adapter.focus_target==ui.widget("child"),"scrolled visible child rejected focus");
}
}
int main() {
    try {gui_model();dispatch();mailbox();modal_guard();scrolled_focus();std::cout<<"UI support tests passed\n";return 0;}
    catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
