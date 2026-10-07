#include "host/native_session.hpp"
#include "shared/application.hpp"
#include <gui/retained_adapter.hpp>
#include <gui/terminal.hpp>
#include "host/native_framebuffer.hpp"
#include <fstream>
#include <iostream>
using namespace foundation;
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Selector : gui::RetainedAdapter {
    explicit Selector(gui::EventSink sink) : gui::RetainedAdapter(std::move(sink), [](const gui::TextMeasureRequest& r){return gui::Size{r.available_width,16};}) {}
    bool service_active() const { return false; }
    std::string selected;
    void service(gui::ServiceRequest request, std::function<void(gui::ServiceResult)> reply) {
        check(request.kind==gui::ServiceKind::prompt,"Content escaped host selector boundary");
        check(request.value.empty(),"Export content leaked to path selector");
        reply({request.id,gui::ServiceStatus::success,selected,{}});
    }
};
int main(){try{
    const auto directory=std::filesystem::current_path()/
        ("file-service-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directory(directory);
    struct Cleanup {std::filesystem::path path;~Cleanup(){std::filesystem::remove_all(path);}} cleanup{directory};
    const auto path=directory/"entries.txt";
    {std::ofstream file(path,std::ios::binary);file<<"first\r\nsecond\n";}
    host::NativeSession<ui::Application,Selector> session;session.adapter.selected=path.string();
    const auto option=[&](const char* id){session.application.handle(gui::WidgetEvent{{"entries.options",1},gui::ChooseOption{id}});session.services();};
    const auto status=[&]{return gui::find_widget(session.application.view(),{"entries.status",1})->state.text;};
    const auto wait=[&](const char* expected){const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
        while(status()!=expected&&std::chrono::steady_clock::now()<deadline){session.tick();std::this_thread::yield();}
        check(status()==expected,"Asynchronous file completion did not reach shared UI");};
    option("import");wait("Entries imported");
    auto rows=gui::find_widget(session.application.view(),{"entries.list",1})->state.records;
    check(rows.size()==2&&rows[0].accessible_text=="first","Content import differs");
    option("export");wait("Export handed to host");
    std::ifstream exported(path,std::ios::binary);std::string bytes((std::istreambuf_iterator<char>(exported)),{});
    check(bytes=="first\nsecond\n","Atomic native export differs");exported.close();
    {std::ofstream file(path,std::ios::binary);file<<"\xef\xbb\xbf" "first\n";}
    option("import");wait("text must contain printable ASCII only");
    check(gui::find_widget(session.application.view(),{"entries.list",1})->state.records==rows,"BOM import silently changed content");
    {std::ofstream file(path,std::ios::binary);file<<"valid\n\ninvalid";}
    option("import");wait("text must contain 1..256 bytes");
    check(gui::find_widget(session.application.view(),{"entries.list",1})->state.records==rows,"Invalid import partially changed records");
    const auto native_selector=[&]<class Adapter>() {
        host::NativeSession<ui::Application,Adapter> owner;
        owner.application.handle(gui::WidgetEvent{{"entries.options",1},gui::ChooseOption{"import"}});owner.services();
        check(bool(owner.adapter.prompt()),"Native content request did not reach generic selector");
        owner.adapter.text(path.string());owner.adapter.key(gui::Key::enter);
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
        while(gui::find_widget(owner.application.view(),{"entries.status",1})->state.text!="text must contain 1..256 bytes"&&std::chrono::steady_clock::now()<deadline) {
            owner.tick();std::this_thread::yield();
        }
        check(gui::find_widget(owner.application.view(),{"entries.status",1})->state.text=="text must contain 1..256 bytes","Selector did not deliver bounded content to shared validation");
    };
    native_selector.template operator()<gui::TerminalAdapter>();
    native_selector.template operator()<gui::FramebufferAdapter>();
    host::NativeFramebufferHost<ui::Application> embedded;
    embedded.application().handle(gui::WidgetEvent{{"entries.options",1},gui::ChooseOption{"import"}});
    struct Sink {
        std::vector<std::string> labels;
        void present(const gui::Frame&) {}
        void present(const gui::Frame&,const std::vector<std::string>& shown){labels=shown;}
    } sink;
    embedded.present(sink);check(bool(embedded.adapter().prompt()),"Native framebuffer embedding lacks file selector");
    const auto selector=embedded.prepare_bezel();check(bool(selector),"Native file selector preparation missing");
    sink.present(selector.frame(),selector.labels());
    check(sink.labels[0]=="Cancel"&&embedded.commit_bezel(selector.token()),"Native selector display commit missing");
    embedded.bezel_button(selector.token(),1);check(!embedded.adapter().prompt(),"Bezel cannot cancel native file selection");
    std::atomic_bool stop{true};
    gui::ServiceRequest request{71,gui::ServiceKind::write_text,"Export","cancelled",32};
    check(host::file_detail::transfer(request,path,stop).status==gui::ServiceStatus::cancelled,"Export cancellation lost");
    std::ifstream unchanged(path,std::ios::binary);bytes.assign(std::istreambuf_iterator<char>(unchanged),{});check(bytes=="valid\n\ninvalid","Cancelled export replaced destination");
    for(const auto& entry:std::filesystem::directory_iterator(directory))check(entry.path()==path,"Temporary export file leaked");
    stop=false;request.kind=gui::ServiceKind::read_text;request.value.clear();request.byte_limit=2;
    bool rejected=false;try{host::file_detail::transfer(request,path,stop);}catch(const std::length_error&){rejected=true;}check(rejected,"Oversized import accepted");
    gui::ServiceQueue queue;request.id=72;request.byte_limit=65537;
    rejected=false;try{queue.enqueue(request);}catch(const std::length_error&){rejected=true;}check(rejected,"Content contract accepted unbounded request");
    session.application.handle(gui::CloseEvent{});session.tick();
    check(!session.application.complete_service({71,gui::ServiceStatus::success,"late",{}}),"Closed app accepted stale file content");
    std::cout<<"Native selected-path isolation, bounded content, atomic import/export and cancellation passed\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
