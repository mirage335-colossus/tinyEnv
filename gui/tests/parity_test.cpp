#include "host/browser.hpp"
#include "tests/fixture.hpp"
#include <gui/terminal.hpp>
#include <gui/framebuffer.hpp>
#include <iostream>

namespace {
template<class Adapter> void check_adapter() {
    foundation::ui::Application* app=nullptr;
    Adapter adapter([&](const gui::Event& event){if(app)app->handle(event);});
    foundation::ui::Application application(adapter);app=&application;
    fixture::feature(application,
        [&](std::string text){adapter.policy().send(gui::WidgetEvent{{"entries.editor",1},gui::EditText{std::move(text),fixture::widget(app->view(),"entries.editor").state.text}});},
        [&](std::string id){adapter.policy().send(gui::WidgetEvent{{std::move(id),1},gui::Activate{}});},
        [&](std::string id){adapter.policy().send(gui::WidgetEvent{{"entries.list",1},gui::SelectRecord{std::move(id)}});}, []{});
    fixture::parity(application.view());
    fixture::unavailable_service(adapter);
    if constexpr(std::is_same_v<Adapter,gui::FramebufferAdapter>)
        fixture::visual_sizes(application,adapter,"framebuffer",[]{},[&](const std::string& name){
            const auto frame=adapter.frame();fixture::capture(frame.pixels->data(),frame.width,frame.height,name.c_str());
        });
}
void browser() {
    using namespace gui::web_detail;
    foundation::host::Browser<foundation::ui::Application> runtime("parity");
    std::uint64_t sequence=0;
    auto send=[&](Json::Object operation){
        const auto response=Parser(runtime.receive(encode(Json::Object{{"epoch","parity"},{"seq",std::to_string(++sequence)},{"operation",std::move(operation)}}))).parse();
        fixture::check(response.at("error").str().empty(),"Browser rejected fixture input");
    };
    fixture::feature(runtime.application(),
        [&](std::string text){send({{"type","edit"},{"key",key({"entries.editor",1})},{"base",fixture::widget(runtime.application().view(),"entries.editor").state.text},{"value",std::move(text)}});},
        [&](std::string id){send({{"type","activate"},{"key",key({std::move(id),1})}});},
        [&](std::string id){send({{"type","select"},{"key",key({"entries.list",1})},{"id",std::move(id)}});}, []{});
    fixture::parity(runtime.application().view());
    send({{"type","choose"},{"key",key({"entries.options",1})},{"id","heading"}});
    auto pending=Parser(runtime.initial()).parse().at("service");
    send({{"type","service"},{"id",pending.at("id")},{"status","cancelled"},{"value",""},{"error",""}});
    fixture::check(fixture::widget(runtime.application().view(),"entries.heading").state.text=="Entry list","Cancel changed heading");
    send({{"type","close"}});
    fixture::check(runtime.adapter.closed(),"Browser close failed");
    const auto stale=Parser(runtime.receive("{\"epoch\":\"obsolete\",\"seq\":\"1\",\"operation\":{\"type\":\"poll\"}}")).parse();
    fixture::check(!stale.at("error").str().empty(),"Stale browser epoch accepted");
}
}
int main(){try{check_adapter<gui::TerminalAdapter>();check_adapter<gui::FramebufferAdapter>();browser();
    std::cout<<"Terminal, framebuffer and browser declarations/actions/geometry agree\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
