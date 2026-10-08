#include <gui/web.hpp>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool condition,const char* message) {if(!condition)throw std::runtime_error(message);}
}
int main() {
    try {
        std::vector<gui::Event> events;
        gui::WebAdapter adapter([&](const gui::Event& event){events.push_back(event);});
        gui::Snapshot view;view.client_size={400,300};
        gui::Widget plain;plain.spec.key={"plain",1};plain.spec.kind=gui::Kind::text;
        plain.spec.text_policy.multiline=true;plain.spec.text_policy.read_only=true;
        plain.state.bounds={20,20,180,100};plain.state.content_size={200,1000};
        for(int i=0;i<40;++i)plain.state.text+="one \xc3\xa9 two\n";
        gui::Widget secret;secret.spec.key={"secret",1};secret.spec.kind=gui::Kind::text;
        secret.spec.text_policy.masked=true;secret.state.bounds={220,20,150,30};secret.state.text="synthetic";
        gui::Widget label;label.spec.key={"label",1};label.spec.kind=gui::Kind::label;
        label.state.bounds={20,140,180,30};label.state.text="Label";
        view.widgets={plain,secret,label};adapter.present(view);
        check(plain.state.text_frame,"Default text framing was disabled");
        const auto presentation=adapter.presentation();
        check(presentation.at("widgets").array()[0].at("textFrame").boolean(),"Default framing did not serialize true");
        check(adapter.focus(plain.spec.key),"Text framing lost normal focus");
        adapter.scroll(plain.spec.key,{0,90});adapter.text_selection(plain.spec.key,{4,6});
        view.widgets[0].state.text_frame=false;view.widgets[1].state.text_frame=false;adapter.present(view);
        const auto frameless=adapter.presentation();
        const auto& record=frameless.at("widgets").array()[0];
        check(!record.at("textFrame").boolean()&&record.at("readOnly").boolean()&&
            record.at("text").str()==plain.state.text,"Frameless presentation changed text or readonly policy");
        check(record.at("bounds").array()[0].number()==20&&record.at("bounds").array()[2].number()==180,
            "Text framing changed declared geometry");
        check(adapter.focused()==plain.spec.key&&adapter.scroll_offset(plain.spec.key)==gui::Point{0,90}&&
            adapter.text_selection(plain.spec.key)==gui::TextSelection{4,6},"Text framing replaced focus, scrolling or UTF-8 selection");
        check(frameless.at("widgets").array()[1].at("masked").boolean()&&
            !frameless.at("widgets").array()[1].at("textFrame").boolean(),"Text framing changed masking");
        gui::WebSession session(adapter,"frame");
        const auto initial=gui::web_detail::Parser(session.initial()).parse();
        check(!initial.at("snapshot").at("widgets").array()[0].at("textFrame").boolean(),
            "Browser session lost frameless appearance");
        view.widgets[0].state.text_frame=true;adapter.present(view);
        check(adapter.presentation().at("widgets").array()[0].at("textFrame").boolean()&&
            adapter.text_selection(plain.spec.key)==gui::TextSelection{4,6}&&events.empty(),
            "Restoring framing changed selection or emitted input");
        auto invalid=view;invalid.widgets[2].state.text_frame=false;bool rejected=false;
        try {adapter.present(invalid);} catch(const std::invalid_argument&) {rejected=true;}
        check(rejected,"Nontext frameless appearance bypassed the shared contract");
        std::cout<<"Browser text-frame defaults, serialization, mutable appearance, retained focus/UTF-8 selection/scrolling and masking passed\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
