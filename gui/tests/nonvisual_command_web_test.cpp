#include <gui/web.hpp>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value,const char* message) { if(!value)throw std::runtime_error(message); }
template<class F> void exceeds(F&& function,const char* message) {
    try { function(); } catch(const std::length_error&) { return; }
    throw std::runtime_error(message);
}
gui::Widget widget(gui::Kind kind,const char* id,gui::Rect bounds) {
    gui::Widget result;result.spec.key={id,1};result.spec.kind=kind;result.state.bounds=bounds;return result;
}
}
int main() {
    try {
        using J=gui::web_detail::Json;
        std::vector<gui::Event> events;
        gui::WebAdapter adapter([&](const gui::Event& event){events.push_back(event);});
        gui::Snapshot view;view.client_size={400,240};
        auto group=widget(gui::Kind::group,"pane",{0,0,180,180});
        auto first=widget(gui::Kind::text,"first",{10,10,150,50});first.spec.parent="pane";
        auto second=widget(gui::Kind::text,"second",{200,10,150,50});
        auto ordinary=widget(gui::Kind::button,"ordinary",{200,80,100,30});
        view.widgets={group,first,second,ordinary};
        const gui::WidgetKey undo{"command.undo",1},redo{"command.redo",1},global{"command.global",1};
        view.commands={{undo,true,first.spec.key},{redo,false,first.spec.key},{global,true,{}}};
        view.key_bindings={{gui::ShortcutKey::z,undo,true,false,false,first.spec.key},
            {gui::ShortcutKey::z,redo,true,true,false,first.spec.key},
            {gui::ShortcutKey::y,redo,true,false,false,first.spec.key},
            {gui::ShortcutKey::z,global,true,false,false,second.spec.key},
            {gui::ShortcutKey::f1,undo},
            {gui::ShortcutKey::f2,ordinary.spec.key}};
        adapter.present(view);adapter.focus(first.spec.key);
        gui::WebSession session(adapter,"nonvisual");std::uint64_t sequence=0;
        auto initial=gui::web_detail::Parser(session.initial()).parse();
        const auto& presentation=initial.at("snapshot");
        check(presentation.at("widgets").array().size()==4,"Nonvisual commands became browser widgets");
        const auto& commands=presentation.at("commands").array();
        check(commands.size()==3&&commands[0].at("key").at("id").str()==undo.id,
            "Browser presentation lost command identities");
        check(commands[0].at("key").at("generation").str()=="1"&&commands[0].at("enabled").boolean()&&
            commands[0].at("scope").at("id").str()==first.spec.key.id&&
            commands[0].at("scope").at("generation").str()=="1",
            "Browser command generation/scope metadata changed");
        check(!commands[1].at("enabled").boolean()&&std::holds_alternative<std::nullptr_t>(commands[2].at("scope").value),
            "Browser disabled/global command declarations changed");
        check(presentation.at("keyBindings").array()[0].at("target").at("id").str()==undo.id&&
            presentation.at("keyBindings").array()[0].at("focus").at("id").str()==first.spec.key.id,
            "Browser shortcut lost target or initiating control scope");
        const auto send=[&](J::Object operation){return gui::web_detail::Parser(session.receive(gui::web_detail::encode(J::Object{
            {"epoch","nonvisual"},{"seq",std::to_string(++sequence)},{"operation",std::move(operation)}}))).parse();};
        const auto stroke=[&](gui::ShortcutKey key,bool control=false,bool shift=false) {
            return send({{"type","shortcut"},{"key",int(key)},{"control",control},{"shift",shift},{"alt",false}});
        };
        stroke(gui::ShortcutKey::z,true);
        check(events.size()==1,"Enabled nonvisual browser shortcut was not delivered once");
        auto event=std::get<gui::WidgetEvent>(events.back());
        check(event.target==undo&&std::get<gui::Activate>(event.input).source==first.spec.key,
            "Browser command lost exact target or retained initiating editor");
        stroke(gui::ShortcutKey::z,true,true);stroke(gui::ShortcutKey::y,true);
        check(events.size()==1,"Disabled command shortcuts bypassed shared activation policy");
        view.commands[1].enabled=true;adapter.present(view);stroke(gui::ShortcutKey::y,true);
        check(events.size()==2&&std::get<gui::WidgetEvent>(events.back()).target==redo,
            "Enabled Ctrl+Y command did not use the declared target");
        const J::Object second_key{{"id","second"},{"generation","1"}};
        send({{"type","focus"},{"key",second_key}});stroke(gui::ShortcutKey::z,true);
        event=std::get<gui::WidgetEvent>(events.back());
        check(events.size()==3&&event.target==global&&std::get<gui::Activate>(event.input).source==second.spec.key,
            "Distinct focused editor shortcut used another editor's command");
        stroke(gui::ShortcutKey::f1);
        check(events.size()==3,"Command accepted activation from outside its declared scope");
        stroke(gui::ShortcutKey::f2);
        check(events.size()==4&&std::get<gui::WidgetEvent>(events.back()).target==ordinary.spec.key,
            "Ordinary button shortcut compatibility changed");
        send({{"type","focus"},{"key",J::Object{{"id","first"},{"generation","1"}}}});
        send({{"type","shortcut"},{"key",int(gui::ShortcutKey::z)},{"control",true},{"shift",false},{"alt",false},
            {"source",second_key}});
        event=std::get<gui::WidgetEvent>(events.back());
        check(events.size()==5&&event.target==undo&&std::get<gui::Activate>(event.input).source==first.spec.key,
            "Browser caller forged the initiating shortcut source");
        const J::Object command_key{{"id",undo.id},{"generation","1"}};
        for(const char* type:{"activate","focus","submit"}) {
            const auto reply=send({{"type",type},{"key",command_key}});
            check(reply.at("error").str()=="Stale widget generation"&&events.size()==5,
                "Nonvisual command acquired a direct browser widget capability");
        }
        check(!adapter.focus(undo),"Nonvisual command became a focus target");
        check(adapter.focus_next()&&adapter.focused()==second.spec.key,"Nonvisual command entered tab order");
        check(adapter.focus(first.spec.key),"Available command scope lost focus before withdrawal");
        view.widgets[0].state.visible=false;adapter.present(view);stroke(gui::ShortcutKey::f1);
        check(!adapter.focused()&&events.size()==5,"Hidden command scope retained stale focus or activated through an unscoped binding");
        view.widgets[0].state.visible=true;view.modal_root=group.spec.key;adapter.present(view);
        adapter.focus(first.spec.key);stroke(gui::ShortcutKey::z,true);
        check(events.size()==6&&std::get<gui::WidgetEvent>(events.back()).target==undo,
            "Current command scope inside a modal lost activation");
        view.key_bindings.push_back({gui::ShortcutKey::f3,global});adapter.present(view);stroke(gui::ShortcutKey::f3);
        check(events.size()==6,"Unscoped command activated behind a modal");
        view.modal_root.reset();view.widgets[1].spec.key.generation=2;
        view.commands[0].scope=view.widgets[1].spec.key;view.commands[1].scope=view.widgets[1].spec.key;
        for(auto& binding:view.key_bindings)if(binding.focus==first.spec.key)binding.focus=view.widgets[1].spec.key;
        view.commands[0].key.generation=2;
        view.commands[1].key.generation=2;
        for(auto& binding:view.key_bindings) {
            if(binding.target==undo)binding.target=view.commands[0].key;
            if(binding.target==redo)binding.target=view.commands[1].key;
        }
        adapter.present(view);adapter.focus(view.widgets[1].spec.key);stroke(gui::ShortcutKey::z,true);
        event=std::get<gui::WidgetEvent>(events.back());
        check(events.size()==7&&event.target==view.commands[0].key&&
            std::get<gui::Activate>(event.input).source==view.widgets[1].spec.key,
            "Replacement command/editor generations retained stale shortcut identities");
        check(!gui::find_widget(adapter.snapshot(),undo),"Retired command identity became a widget");
        auto too_many=view;too_many.commands.clear();
        for(std::size_t i=0;i<4097;++i)too_many.commands.push_back({{"limit."+std::to_string(i),1},true,{}});
        exceeds([&]{adapter.present(too_many);},"Browser command count bypassed profile limits");
        auto too_large=view;too_large.commands[0].key.id=std::string(4*1024*1024+1,'x');
        exceeds([&]{adapter.present(too_large);},"Browser command identity bypassed presentation text limits");
        std::cout<<"Browser nonvisual metadata, scoped Ctrl+Z/Shift+Z/Y, shared activation, no widget capabilities and profile limits passed\n";
    } catch(const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; }
}
