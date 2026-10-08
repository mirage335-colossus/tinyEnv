#include <gui/web.hpp>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value,const char* message) { if(!value)throw std::runtime_error(message); }
template<class F> void rejects(F&& function,const char* message) {
    try { function(); } catch(const std::invalid_argument&) { return; }
    throw std::runtime_error(message);
}
}
int main() {
    try {
        using J=gui::web_detail::Json;
        std::vector<gui::Event> events;
        gui::WebAdapter adapter([&](const gui::Event& event){events.push_back(event);});
        gui::Snapshot view;view.client_size={300,200};
        gui::Widget masked;masked.spec.key={"masked",1};masked.spec.kind=gui::Kind::text;
        masked.spec.text_policy.masked=true;masked.spec.text_policy.max_bytes=64;masked.spec.text_policy.submit=gui::SubmitKey::enter;
        masked.state.bounds={20,20,180,30};masked.state.text="a\xc3\xa9\xf0\x9f\x94\x92z";
        gui::Widget ordinary;ordinary.spec.key={"ordinary",1};ordinary.spec.kind=gui::Kind::text;
        ordinary.state.bounds={20,60,180,30};ordinary.state.text="Plain text";
        view.widgets={masked,ordinary};adapter.present(view);
        gui::WebSession session(adapter,"masking");std::uint64_t sequence=0;
        const auto initial=gui::web_detail::Parser(session.initial()).parse();
        const auto& widgets=initial.at("snapshot").at("widgets").array();
        check(widgets[0].at("masked").boolean()&&!widgets[1].at("masked").boolean(),"Browser masking flag changed its declared/default value");
        check(widgets[0].at("text").str()==masked.state.text,"Browser masking replaced owned actual text");
        check(widgets[0].at("options").array().empty(),"Masked editor unexpectedly gained suggestions");
        const auto send=[&](J::Object operation){return gui::web_detail::Parser(session.receive(gui::web_detail::encode(J::Object{
            {"epoch","masking"},{"seq",std::to_string(++sequence)},{"operation",std::move(operation)}}))).parse();};
        const auto key=[](std::string generation="1"){return J::Object{{"id","masked"},{"generation",std::move(generation)}};};
        auto reply=send({{"type","selection"},{"key",key()},{"anchor","7"},{"caret","1"}});
        check(reply.at("error").str().empty(),"Masked selection was rejected");
        const auto& selection=reply.at("snapshot").at("widgets").array()[0].at("selection").array();
        check(selection[0].number()==7&&selection[1].number()==1,"Masked UTF-8 selection did not retain actual byte offsets");
        const std::string replacement="pasted\xc3\xa9\xf0\x9f\x94\x92";
        reply=send({{"type","edit"},{"key",key()},{"value",replacement},{"base",masked.state.text}});
        check(reply.at("error").str().empty()&&events.size()==1,"Masked edit was lost in browser transport");
        const auto* edit=std::get_if<gui::EditText>(&std::get<gui::WidgetEvent>(events.back()).input);
        check(edit&&edit->value==replacement&&edit->base_text==masked.state.text,"Masked editing delivered masking glyphs instead of owned text");
        view.widgets[0].state.text=replacement;adapter.present(view);
        check(adapter.presentation().at("widgets").array()[0].at("text").str()==replacement,"Masked authoritative text was not preserved");
        send({{"type","edit"},{"key",key()},{"value","two\nlines"},{"base",replacement}});
        send({{"type","edit"},{"key",key()},{"value",std::string(65,'x')},{"base",replacement}});
        check(events.size()==1,"Masking bypassed ordinary line/byte edit constraints");
        send({{"type","submit"},{"key",key()}});check(events.size()==2,"Masked text lost declared submission");
        auto read_only=masked;read_only.spec.key={"readonly",1};read_only.spec.text_policy.read_only=true;
        read_only.state.bounds={20,100,180,30};view.widgets.push_back(read_only);adapter.present(view);
        check(adapter.presentation().at("widgets").array()[2].at("readOnly").boolean(),"Readonly masked editor lost its edit policy");
        const J::Object readonly_key{{"id","readonly"},{"generation","1"}};
        send({{"type","edit"},{"key",readonly_key},{"value",replacement},{"base",read_only.state.text}});
        send({{"type","submit"},{"key",readonly_key}});
        check(events.size()==2,"Readonly masked editor accepted an edit or submit intent");
        auto invalid=view;invalid.widgets[0].spec.key.generation=2;invalid.widgets[0].spec.text_policy.multiline=true;
        rejects([&]{adapter.present(invalid);},"Masked multiline presentation was accepted");
        invalid=view;invalid.widgets[0].state.options={{"one","Suggestion","Candidate",true}};
        rejects([&]{adapter.present(invalid);},"Masked suggestions were accepted");
        invalid=view;invalid.widgets[0].spec.text_policy.masked=false;
        rejects([&]{adapter.present(invalid);},"Masking policy changed without a fresh generation");
        check(adapter.presentation().at("widgets").array()[0].at("masked").boolean(),"Rejected presentation revoked masking");
        view.widgets[0].spec.key.generation=2;view.widgets[0].spec.text_policy.masked=false;view.widgets[0].state.text="Replacement";
        adapter.present(view);check(!adapter.presentation().at("widgets").array()[0].at("masked").boolean(),"Fresh ordinary generation retained old masking");
        reply=send({{"type","edit"},{"key",key()},{"value","stale"},{"base",replacement}});
        check(reply.at("error").str()=="Stale widget generation"&&events.size()==2,"Retired masked identity edited its successor");
        std::cout<<"Browser masking serialization, actual UTF-8 edit/selection, ordinary constraints and generation replacement passed\n";
    } catch(const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; }
}
