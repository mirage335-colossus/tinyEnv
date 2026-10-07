#include "host/contract.hpp"
#include "host/browser.hpp"
#include "tests/fixture.hpp"
#include <gui/framebuffer.hpp>
#include <gui/terminal.hpp>
#include <iostream>

using foundation::ui::TextTask;
using foundation::ui::TaskUpdate;
struct CooperativeApplication : foundation::ui::Application {
    explicit CooperativeApplication(gui::Adapter& adapter) : Application(adapter, std::make_unique<foundation::ui::CooperativeTaskExecutor>()) {}
};
void owned_task() {
    TextTask task;
    std::vector<std::string> input{"ab cd", "e"};
    const auto first=task.start(input);input[0]="changed";
    auto result=task.advance(2);fixture::check(result&&result->processed==2&&result->result==2&&!result->complete,"Task ignored step budget");
    result=task.advance(3);fixture::check(result&&result->processed==5&&result->result==4,"Task borrowed changed input");
    result=task.advance(2);fixture::check(result&&result->complete&&result->result==5,"Task result differs");
    fixture::check(!task.advance(),"Completed task repeated output");
    const auto second=task.start({"another"});fixture::check(second.generation>first.generation,"Replacement reused task identity");
    task.cancel();fixture::check(!task.advance(),"Cancelled task advanced");
    task.start({});result=task.advance();fixture::check(result&&result->complete&&result->total==0,"Empty task did not complete");
    bool rejected=false;try{task.start({std::string(257,'x')});}catch(const std::length_error&){rejected=true;}
    fixture::check(rejected,"Oversized task input accepted");
    task.shutdown();rejected=false;try{task.start({"late"});}catch(const std::logic_error&){rejected=true;}
    fixture::check(rejected&&!task.advance(),"Closed task accepted work");
}
template<class Adapter> void application_task() {
    foundation::host::Session<CooperativeApplication,Adapter> session;
    auto& app=session.application;
    auto activate=[&](const char* id){session.adapter.policy().send(gui::WidgetEvent{{id,1},gui::Activate{}});};
    for(unsigned i=0;i<4;++i) {
        app.handle(gui::WidgetEvent{{"entries.editor",1},gui::EditText{std::string(256,'x'),""}});
        activate("entries.add");
    }
    const auto before_start=app.input_epoch();
    activate("entries.task.start");const auto first=app.task_progress();
    fixture::check(app.task_running()&&first.total==1024,"Shared task did not capture core state");
    fixture::check(app.input_epoch()==before_start+1,"Task start retained semantic input epoch");
    const auto running_epoch=app.input_epoch();
    session.tick();fixture::check(app.task_progress().processed==256&&app.task_running(),"UI turn was not bounded");
    fixture::check(app.input_epoch()==running_epoch,"Intermediate progress changed semantic input epoch");
    activate("entries.task.cancel");fixture::check(!app.task_running(),"Shared cancellation failed");
    fixture::check(app.input_epoch()==running_epoch+1,"Task cancellation retained semantic input epoch");
    const auto cancelled_epoch=app.input_epoch();
    fixture::check(!app.complete_task({first.generation,1024,1024,1024,true}),"Cancelled completion accepted");
    fixture::check(app.input_epoch()==cancelled_epoch,"Cancelled completion changed semantic input epoch");
    activate("entries.task.start");const auto second=app.task_progress();
    fixture::check(second.generation>first.generation,"Restart identity reused");
    fixture::check(app.input_epoch()==cancelled_epoch+1,"Task restart retained semantic input epoch");
    const auto restarted_epoch=app.input_epoch();
    fixture::check(!app.complete_task({first.generation,1024,1024,1024,true}),"Previous task completed replacement");
    fixture::check(!app.complete_task({second.generation,1025,1024,1024,true}),"Malformed completion accepted");
    fixture::check(app.input_epoch()==restarted_epoch,"Rejected task completion changed semantic input epoch");
    app.handle(gui::WidgetEvent{{"entries.options",1},gui::ChooseOption{"clear"}});
    fixture::check(app.input_epoch()==restarted_epoch+1,"Clear command retained semantic input epoch");
    const auto before_completion=app.input_epoch();
    for(unsigned i=0;i<4;++i) {
        session.tick();
        fixture::check(app.input_epoch()==before_completion+(i==3?1:0),
            "Task input epoch did not distinguish progress from terminal completion");
    }
    fixture::check(!app.task_running()&&app.task_progress().result==1024,"Owned input changed with live collection");
    fixture::check(fixture::widget(app.view(),"entries.list").state.records.empty(),"UI input stalled during task");
    fixture::check(!app.complete_task(app.task_progress()),"Terminal completion repeated");
    fixture::check(app.input_epoch()==before_completion+1,"Repeated terminal completion changed semantic input epoch");
    activate("entries.task.start");const auto before_close=app.input_epoch();
    app.handle(gui::CloseEvent{});session.tick();
    fixture::check(!app.task_running()&&!app.complete_task(second),"Close retained task work");
    fixture::check(app.input_epoch()==before_close+1,"Close or repeated shutdown changed task input epoch");
}
void browser_task() {
    foundation::host::Browser<CooperativeApplication> runtime("task");
    using namespace gui::web_detail;std::uint64_t seq=0;
    const auto send=[&](Json::Object operation){return runtime.receive(encode(Json::Object{{"epoch","task"},{"seq",std::to_string(++seq)},{"operation",std::move(operation)}}));};
    for(unsigned i=0;i<2;++i){send({{"type","edit"},{"key",key({"entries.editor",1})},{"base",""},{"value",std::string(256,'a')}});send({{"type","activate"},{"key",key({"entries.add",1})}});}
    send({{"type","activate"},{"key",key({"entries.task.start",1})}});
    fixture::check(runtime.application().task_progress().processed==0,"Input dispatch advanced work outside tick");
    const auto running_epoch=runtime.application().input_epoch();
    const auto poll=encode(Json::Object{{"epoch","task"},{"seq",std::to_string(++seq)},{"operation",Json::Object{{"type","poll"}}}});
    runtime.receive(poll);fixture::check(runtime.application().task_progress().processed==256,"Authenticated poll did not advance task");
    fixture::check(runtime.application().input_epoch()==running_epoch,"Authenticated progress changed semantic input epoch");
    runtime.receive(poll);fixture::check(runtime.application().task_progress().processed==256,"Retried poll repeated task step");
    runtime.receive("{\"epoch\":\"old\",\"seq\":\"1\",\"operation\":{\"type\":\"poll\"}}");
    fixture::check(runtime.application().task_progress().processed==256,"Stale session advanced task");
    fixture::check(runtime.application().input_epoch()==running_epoch,"Retried or stale poll changed semantic input epoch");
    send({{"type","poll"}});fixture::check(!runtime.application().task_running(),"Browser task failed to complete");
    fixture::check(runtime.application().input_epoch()==running_epoch+1,"Browser task completion retained semantic input epoch");
}
int main(){try{owned_task();application_task<gui::TerminalAdapter>();application_task<gui::FramebufferAdapter>();browser_task();
    std::cout<<"Bounded owned work, responsive edits, cancel/restart, late-result rejection and close passed\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
